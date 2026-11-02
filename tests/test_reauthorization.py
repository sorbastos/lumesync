"""Regression tests for the two independent Google authorizations."""
import configparser
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lumesync.online import OnlineDrive, REMOTE


class ReauthorizationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.data = Path(self.temporary.name)
        self.controller = OnlineDrive({'local': str(self.data/'mount'), 'root_id': 'folder'}, self.data)
        self.controller.rclone = '/usr/bin/rclone'
        self.token = {'access_token': 'synthetic-old', 'refresh_token': 'synthetic-old-refresh',
                      'client_id': 'synthetic-client', 'client_secret': 'synthetic-secret',
                      'expires_at': 2000000000}
        self.write_token()
        self.controller.configure_backend()
        self.before = self.controller.rclone_config.read_bytes()
        self.token.update(access_token='synthetic-new', refresh_token='synthetic-new-refresh')
        self.write_token()

    def write_token(self):
        (self.data/'google-token.json').write_text(json.dumps(self.token))

    def read_backend(self):
        parser = configparser.ConfigParser(interpolation=None)
        parser.read(self.controller.rclone_config)
        return parser[REMOTE]

    def test_active_service_stops_before_replace_and_starts_with_new_credentials(self):
        calls = []
        def command(args, **kwargs):
            calls.append(args[2])
            token = json.loads(self.read_backend()['token'])
            self.assertEqual(token['refresh_token'], 'synthetic-old-refresh' if args[2] == 'stop' else 'synthetic-new-refresh')
        with patch('lumesync.online.subprocess.run', return_value=subprocess.CompletedProcess([], 0, stdout='')), patch('lumesync.online.checked', side_effect=command), patch.object(self.controller, 'start', side_effect=lambda: command(['systemctl', '--user', 'start'])):
            self.controller.refresh_authorization()
        self.assertEqual(calls, ['stop', 'start'])
        backend = self.read_backend()
        self.assertEqual(backend['root_folder_id'], 'folder')
        self.assertEqual(backend['client_secret'], 'synthetic-secret')
        self.assertEqual(self.controller.rclone_config.stat().st_mode & 0o777, 0o600)
        # Subsequent scans must keep the backend's latest access token.
        self.controller.configure_backend()
        self.assertEqual(json.loads(self.read_backend()['token'])['access_token'], 'synthetic-new')

    def test_inactive_service_updates_without_starting_missing_unit(self):
        with patch('lumesync.online.subprocess.run', return_value=subprocess.CompletedProcess([], 3, stdout='')), patch('lumesync.online.checked') as command:
            self.controller.refresh_authorization()
        command.assert_not_called()
        self.assertEqual(json.loads(self.read_backend()['token'])['refresh_token'], 'synthetic-new-refresh')

    def test_first_connection_defers_creation_to_setup(self):
        self.controller.rclone_config.unlink()
        with patch('lumesync.online.subprocess.run') as run:
            self.controller.refresh_authorization()
        run.assert_not_called()
        self.assertFalse(self.controller.rclone_config.exists())

    def test_failed_stop_preserves_existing_backend(self):
        with patch('lumesync.online.subprocess.run', return_value=subprocess.CompletedProcess([], 0, stdout='')), patch('lumesync.online.checked', side_effect=RuntimeError('stop failed')):
            with self.assertRaises(RuntimeError):
                self.controller.refresh_authorization()
        self.assertEqual(self.controller.rclone_config.read_bytes(), self.before)

    def test_failed_atomic_replace_preserves_existing_backend(self):
        with patch('lumesync.online.subprocess.run', return_value=subprocess.CompletedProcess([], 3, stdout='')), patch('lumesync.online.os.replace', side_effect=OSError('disk failed')):
            with self.assertRaises(OSError):
                self.controller.refresh_authorization()
        self.assertEqual(self.controller.rclone_config.read_bytes(), self.before)
        self.assertEqual(list(self.data.glob('.rclone-auth-*')), [])

    def test_incomplete_authorization_does_not_touch_service_or_backend(self):
        self.token.pop('refresh_token')
        self.write_token()
        with patch('lumesync.online.subprocess.run') as run:
            with self.assertRaises(RuntimeError):
                self.controller.refresh_authorization()
        run.assert_not_called()
        self.assertEqual(self.controller.rclone_config.read_bytes(), self.before)

    def test_auth_worker_updates_backend_before_reporting_success(self):
        from lumesync.app import Worker
        events = []
        worker = Worker({'local': str(self.data/'mount')}, 'auth', client='synthetic.json')
        worker.completed.connect(lambda result: events.append('completed'))
        with patch('lumesync.app.authorize', side_effect=lambda *args: events.append('authorize')), patch('lumesync.online.OnlineDrive') as controller:
            controller.return_value.complete_authorization.side_effect = lambda: events.append('backend')
            worker.run()
        self.assertEqual(events, ['authorize', 'backend', 'completed'])
