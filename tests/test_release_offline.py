"""Liberação local com pastas temporárias; nenhuma conta real é utilizada."""
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from lumesync.core import Engine, LocalProvider, State, exclusive
from lumesync.ignore import OfflineExclusions
from lumesync.online import OnlineDrive
from lumesync.presentation import pin_for_entry


class ReleaseOfflineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.local = self.root/'Offline'; self.remote = self.root/'Drive'
        self.local.mkdir(); self.remote.mkdir()
        (self.remote/'pasta').mkdir()
        (self.remote/'pasta/a.txt').write_text('conteúdo seguro')
        (self.remote/'pasta/b.txt').write_text('outro arquivo')
        self.config = {'local': str(self.root/'mount'), 'offline_local': str(self.local),
                       'access_mode': 'online', 'pins': [{'remote_id': 'folder', 'path': 'pasta', 'label': 'pasta'}]}
        self.saved = copy.deepcopy(self.config)
        self.builder = patch('lumesync.config.build', side_effect=self.build); self.builder.start()
        self.saver = patch('lumesync.online.save', side_effect=self.save); self.saver.start()
        self.controller = OnlineDrive(copy.deepcopy(self.config), self.root/'runtime')
        engine = self.build(self.controller.offline_config())
        try:
            engine.apply(engine.plan())
        finally:
            engine.state.close()

    def tearDown(self):
        self.saver.stop(); self.builder.stop(); self.temp.cleanup()

    def save(self, config):
        self.saved = copy.deepcopy(config)

    def build(self, config):
        provider = LocalProvider(self.remote)
        provider.include_paths = config['include_paths']
        patterns = OfflineExclusions([], config.get('offline_excludes', []))
        return Engine(self.local, provider, State(self.root/'state'), patterns)

    def test_release_preserves_cloud_and_does_not_download_again(self):
        before = (self.remote/'pasta/a.txt').read_bytes()
        self.controller.release_file('pasta/a.txt')
        self.assertFalse((self.local/'pasta/a.txt').exists())
        self.assertEqual((self.remote/'pasta/a.txt').read_bytes(), before)
        self.assertTrue((self.local/'pasta/b.txt').is_file())
        self.assertEqual(self.saved['offline_excludes'], ['pasta/a.txt'])
        engine = self.build(self.controller.offline_config())
        try:
            self.assertEqual([a.path for a in engine.plan()], ['pasta/b.txt'])
            engine.apply(engine.plan())
            self.assertFalse((self.local/'pasta/a.txt').exists())
        finally:
            engine.state.close()

    def test_explicit_file_pin_is_removed(self):
        self.controller.config['pins'] = [{'remote_id': 'file', 'path': 'pasta/a.txt', 'label': 'pasta/a.txt'}]
        self.controller.release_file('pasta/a.txt')
        self.assertEqual(self.saved['pins'], [])
        self.assertTrue((self.remote/'pasta/a.txt').is_file())

    def test_unsent_local_edit_is_preserved(self):
        (self.local/'pasta/a.txt').write_text('alteração ainda não enviada')
        with self.assertRaisesRegex(RuntimeError, 'Sincronize'):
            self.controller.release_file('pasta/a.txt')
        self.assertEqual((self.local/'pasta/a.txt').read_text(), 'alteração ainda não enviada')
        self.assertEqual((self.remote/'pasta/a.txt').read_text(), 'conteúdo seguro')
        self.assertNotIn('offline_excludes', self.saved)

    def test_missing_remote_blocks_local_removal(self):
        (self.remote/'pasta/a.txt').unlink()
        with self.assertRaises(RuntimeError):
            self.controller.release_file('pasta/a.txt')
        self.assertTrue((self.local/'pasta/a.txt').exists())

    def test_directory_and_unsafe_path_are_refused(self):
        for path in ['pasta', 'pasta/../../outside']:
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.controller.release_file(path)
        self.assertTrue((self.local/'pasta/a.txt').exists())

    def test_symlink_is_refused(self):
        (self.local/'pasta/a.txt').unlink()
        (self.local/'pasta/a.txt').symlink_to(self.remote/'pasta/a.txt')
        with self.assertRaises(ValueError):
            self.controller.release_file('pasta/a.txt')
        self.assertTrue((self.remote/'pasta/a.txt').exists())

    def test_concurrent_sync_blocks_release(self):
        with exclusive(self.root/'state'), self.assertRaisesRegex(RuntimeError, 'sincronização'):
            self.controller.release_file('pasta/a.txt')
        self.assertTrue((self.local/'pasta/a.txt').exists())

    def test_save_failure_preserves_local_file(self):
        with patch('lumesync.online.save', side_effect=OSError('disco indisponível')):
            with self.assertRaises(OSError):
                self.controller.release_file('pasta/a.txt')
        self.assertTrue((self.local/'pasta/a.txt').exists())

    def test_unlink_failure_restores_selection(self):
        with patch.object(Path, 'unlink', side_effect=PermissionError('bloqueado')):
            with self.assertRaises(PermissionError):
                self.controller.release_file('pasta/a.txt')
        self.assertTrue((self.local/'pasta/a.txt').exists())
        self.assertEqual(self.saved, self.config)

    def test_reselect_downloads_instead_of_creating_deletion_conflict(self):
        self.controller.release_file('pasta/a.txt')
        resource = {'id': 'file', 'name': 'a.txt', 'mimeType': 'text/plain', 'parents': ['folder']}
        folder = {'id': 'folder', 'name': 'pasta', 'mimeType': 'application/vnd.google-apps.folder', 'parents': ['rootid']}
        provider = Mock(root_id='rootid', name_map={}, mapping_file=self.root/'mapping.json')
        provider.request.side_effect = lambda method, url, **kwargs: Mock(json=lambda: resource if url.endswith('/file') else folder)
        provider.children.side_effect = lambda parent: [resource] if parent == 'folder' else [folder]
        with patch('lumesync.online.DriveProvider', return_value=provider), patch('lumesync.online.load', side_effect=lambda: copy.deepcopy(self.saved)):
            self.controller.pin({'ID': 'file', 'Name': 'a.txt'}, 'pasta/a.txt')
        self.assertEqual(self.saved['offline_excludes'], [])
        engine = self.build(self.controller.offline_config())
        try:
            action = next(a for a in engine.plan() if a.path == 'pasta/a.txt')
            self.assertEqual(action.kind, 'download')
        finally:
            engine.state.close()

    def test_literal_exclusion_and_ui_state(self):
        rules = OfflineExclusions([], ['pasta/a[1]*.txt'])
        self.assertTrue(rules.matches('pasta/a[1]*.txt'))
        self.assertFalse(rules.matches('pasta/a1test.txt'))
        entry = {'ID': 'file', 'Name': 'a.txt'}
        self.assertIsNone(pin_for_entry(entry, 'pasta', self.config['pins'], ['pasta/a.txt']))
