"""Regressions for the review findings, using synthetic profiles and files."""
import configparser
import hashlib
import json
import os
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from lumesync import config
from lumesync.core import Engine, LocalProvider, State, digest
from lumesync.drive import DriveProvider
from lumesync.online import OnlineDrive, REMOTE
from lumesync.presentation import error_help


class ReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root/'data'
        self.data.mkdir()
        self.token = {'access_token':'synthetic-access','refresh_token':'synthetic-refresh',
                      'client_id':'synthetic-client','expires_at':2000000000}
        self.write_token()
        self.cfg = {'mode':'drive','root_id':'canonical-root','drive_scope':'all',
                    'local':str(self.root/'mount'),'offline_local':str(self.root/'offline'),
                    'pins':[], 'ignores':[]}
        self.controller = OnlineDrive(self.cfg,self.data)
        self.controller.rclone = '/usr/bin/rclone'

    def write_token(self):
        (self.data/'google-token.json').write_text(json.dumps(self.token))

    def local_engine(self):
        provider=LocalProvider(self.root/'remote')
        state=State(self.root/'state')
        self.addCleanup(state.close)
        return Engine(self.root/'local',provider,state,[])

    def test_legacy_history_is_copied_and_survives_new_refresh_token(self):
        local=Path(self.cfg['offline_local'])
        old='drive|'+str(local.resolve())+'|canonical-root|synthetic-refresh'
        old_key=hashlib.sha256(old.encode()).hexdigest()
        legacy=State(self.data/'profiles'/old_key)
        legacy.bind(old_key);legacy.record('edited.txt','previous-checksum');legacy.close()
        cfg={**self.cfg,'access_mode':'offline','local':str(local)}
        a=config.build(cfg,data=self.data)
        path=a.state.directory
        self.assertEqual(a.state.baseline(),{'edited.txt':'previous-checksum'})
        a.state.close()
        self.token['refresh_token']='synthetic-new'
        self.write_token()
        b=config.build(cfg,data=self.data)
        self.assertEqual(b.state.directory,path)
        self.assertIn('edited.txt',b.state.baseline());b.state.close()
        self.assertTrue((self.data/'profiles'/old_key/'state.sqlite3').exists())

    def test_same_size_download_requires_temporary_space_and_preserves_target(self):
        engine=self.local_engine()
        (engine.local/'a').write_text('old')
        (engine.provider.root/'a').write_text('old')
        engine.apply(engine.plan())
        (engine.provider.root/'a').write_text('new')
        with patch('shutil.disk_usage',return_value=SimpleNamespace(free=0)):
            with self.assertRaisesRegex(RuntimeError,'Espaço'):
                engine.apply(engine.plan())
        self.assertEqual((engine.local/'a').read_text(),'old')

    def test_upload_checks_profile_volume(self):
        engine=self.local_engine();(engine.local/'a').write_text('content')
        with patch('shutil.disk_usage',return_value=SimpleNamespace(free=0)) as usage:
            with self.assertRaisesRegex(RuntimeError,'temporária de upload'):
                engine.apply(engine.plan())
        self.assertEqual(usage.call_args.args[0],engine.state.directory)
        self.assertFalse((engine.provider.root/'a').exists())

    def test_checksum_cache_invalidates_even_on_same_size_edit(self):
        engine=self.local_engine();(engine.local/'a').write_text('old')
        before=engine.plan()[0].local.checksum
        (engine.local/'a').write_text('new')
        self.assertNotEqual(before,engine.plan()[0].local.checksum)

    def test_network_refresh_failure_does_not_claim_revoked_authorization(self):
        self.token['expires_at']=0;self.write_token()
        provider=DriveProvider(self.data/'google-token.json')
        response=Mock(status_code=503);response.json.side_effect=ValueError()
        with patch('lumesync.drive.requests.post',return_value=response):
            with self.assertRaisesRegex(RuntimeError,'temporária'):
                provider._access()
        self.assertIn('autorização',error_help('Sessão Google expirada; conecte novamente')[0])

    def test_profiles_get_different_service_units(self):
        other=OnlineDrive(self.cfg,self.root/'other-profile')
        self.assertNotEqual(self.controller.service,other.service)

    def test_reconnect_recreates_missing_transient_service(self):
        with patch.object(self.controller,'configure_backend'), patch.object(self.controller,'adopt_legacy_service'), patch('lumesync.online.subprocess.run',return_value=subprocess.CompletedProcess([],4)), patch.object(self.controller,'start') as start, patch('lumesync.online.checked') as checked:
            self.controller.reconnect()
        start.assert_called_once();checked.assert_not_called()

    def test_new_credentials_are_not_committed_if_backend_update_fails(self):
        before=(self.data/'google-token.json').read_bytes()
        pending={**self.token,'refresh_token':'synthetic-next'}
        self.controller.pending_auth.write_text(json.dumps(pending))
        provider=Mock(token=pending)
        provider.request.return_value.json.return_value={'id':'canonical-root'}
        engine=Mock()
        with patch('lumesync.online.DriveProvider',return_value=provider),patch('lumesync.config.build',return_value=engine),patch.object(self.controller,'refresh_authorization',side_effect=RuntimeError('service failed')):
            with self.assertRaises(RuntimeError):self.controller.complete_authorization()
        self.assertEqual((self.data/'google-token.json').read_bytes(),before)
        self.assertTrue(self.controller.pending_auth.exists())

    def test_pending_authorization_is_recoverable_and_commits_both_sides(self):
        pending={**self.token,'refresh_token':'synthetic-next'}
        self.controller.pending_auth.write_text(json.dumps(pending))
        provider=Mock(token=pending)
        provider.request.return_value.json.return_value={'id':'canonical-root'}
        with patch('lumesync.online.DriveProvider',return_value=provider),patch('lumesync.config.build',return_value=Mock()),patch.object(self.controller,'refresh_authorization') as refresh:
            self.controller.complete_authorization()
        refresh.assert_called_once_with(self.controller.pending_auth)
        self.assertFalse(self.controller.pending_auth.exists())
        self.assertEqual(json.loads((self.data/'google-token.json').read_text())['refresh_token'],'synthetic-next')

    def test_other_account_is_rejected_before_service_or_file_changes(self):
        self.controller.pending_auth.write_text(json.dumps(self.token))
        provider=Mock(token=self.token)
        provider.request.return_value.json.return_value={'id':'different-account-root'}
        with patch('lumesync.online.DriveProvider',return_value=provider),patch.object(self.controller,'refresh_authorization') as refresh:
            with self.assertRaisesRegex(RuntimeError,'outra conta'):
                self.controller.complete_authorization()
        refresh.assert_not_called()

    def test_corrupt_config_preserved_and_valid_backup_can_be_restored(self):
        current=self.data/'config.json';current.write_text('broken-json')
        backup=self.data/'backup.json';backup.write_text(json.dumps(self.cfg))
        with patch.object(config,'DATA',self.data),patch.object(config,'CONFIG',current):
            with self.assertRaisesRegex(RuntimeError,'preservado'):config.load()
            self.assertEqual(current.read_text(),'broken-json')
            config.restore_backup(backup)
            self.assertEqual(config.load()['root_id'],'canonical-root')
        self.assertEqual(len(list(self.data.glob('config-damaged-*'))),1)

    def test_pin_move_preserves_unsent_edits_and_migrates_baseline(self):
        engine=self.local_engine()
        (engine.local/'old').mkdir();(engine.local/'old/edit.txt').write_text('unsent edit')
        engine.state.record('old/edit.txt','cloud-checksum')
        updated={**self.cfg,'pins':[{'path':'new','remote_id':'folder-id','label':'new'}]}
        journal={'old':'old','new':'new','config':updated}
        self.controller.finish_pin_move(engine,journal)
        self.assertEqual((engine.local/'new/edit.txt').read_text(),'unsent edit')
        self.assertEqual(engine.state.baseline(),{'new/edit.txt':'cloud-checksum'})
        self.controller.finish_pin_move(engine,journal)  # Simulated crash before journal removal.
        self.assertEqual(engine.state.baseline(),{'new/edit.txt':'cloud-checksum'})

    def test_pin_move_collision_preserves_both_copies(self):
        engine=self.local_engine()
        (engine.local/'old').write_text('old edits');(engine.local/'new').write_text('other edits')
        with self.assertRaisesRegex(RuntimeError,'preservados'):
            self.controller.finish_pin_move(engine,{'old':'old','new':'new','config':self.cfg})
        self.assertEqual((engine.local/'old').read_text(),'old edits')
        self.assertEqual((engine.local/'new').read_text(),'other edits')
