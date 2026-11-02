"""Opt-in real user-systemd lifecycle test; never mounts or contacts Google."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from lumesync.online import OnlineDrive


@unittest.skipUnless(os.environ.get('LUMESYNC_INTEGRATION') == '1', 'enable LUMESYNC_INTEGRATION=1 with a user systemd session')
class ServiceIntegrationTests(unittest.TestCase):
    def test_collected_unit_is_recreated_after_reauthorization_and_reconnect(self):
        with tempfile.TemporaryDirectory(prefix='lumesync-service-test-') as d:
            data=Path(d)
            token={'access_token':'synthetic','refresh_token':'synthetic-refresh','client_id':'synthetic','expires_at':2000000000}
            (data/'google-token.json').write_text(json.dumps(token))
            controller=OnlineDrive({'local':str(data/'mount'),'root_id':'root'},data)
            def active():
                return subprocess.run(['systemctl','--user','is-active','--quiet',controller.service+'.service']).returncode == 0
            controller.configure_backend()
            try:
                # Real systemd-run / stop / collect. A harmless sleep replaces rclone/FUSE.
                with patch.object(controller,'mount_source',return_value=''),patch.object(controller,'mounted',side_effect=active),patch.object(controller,'mount_arguments',return_value=[shutil.which('sleep'),'30']):
                    controller.start()
                    self.assertTrue(active())
                    token['refresh_token']='synthetic-new-refresh'
                    (data/'google-token.json').write_text(json.dumps(token))
                    controller.refresh_authorization()
                    self.assertTrue(active())
                    controller.reconnect()
                    self.assertTrue(active())
            finally:
                subprocess.run(['systemctl','--user','stop',controller.service+'.service'],capture_output=True)
