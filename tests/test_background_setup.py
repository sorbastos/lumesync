import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication
from lumesync.app import Window, Worker
from lumesync.folders import drive_folder
from lumesync.core import DEFAULT_IGNORES
from lumesync.drive import FOLDER, DriveProvider
from lumesync.presentation import error_help


class FolderChoiceTests(unittest.TestCase):
    def test_all_drive_needs_no_identifier(self):
        self.assertEqual(drive_folder('all'), 'root')
        self.assertEqual(drive_folder('all', 'old value ignored'), 'root')

    def test_folder_links_and_legacy_identifiers(self):
        for link in ('https://drive.google.com/drive/folders/Folder123?usp=sharing',
                     'https://drive.google.com/drive/u/0/folders/Folder123',
                     'drive.google.com/drive/folders/Folder123', 'Folder123'):
            with self.subTest(link=link):
                self.assertEqual(drive_folder('folder', link), 'Folder123')

    def test_invalid_links_are_rejected(self):
        for link in ('', 'https://example.org/drive/folders/Folder123',
                     'https://drive.google.com.evil.test/folders/Folder123',
                     'https://drive.google.com/file/d/Folder123/view'):
            with self.subTest(link=link), self.assertRaises(ValueError):
                drive_folder('folder', link)

    def test_missing_token_has_connection_guidance(self):
        with tempfile.TemporaryDirectory() as d, self.assertRaisesRegex(RuntimeError, 'Conectar Google Drive'):
            DriveProvider(Path(d)/'google-token.json')
        self.assertIn('Conecte sua conta', error_help('Conta do Google Drive não conectada.')[0])


class BackgroundAndSetupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.config = {'mode': 'demo', 'local': str(self.root/'local'), 'remote': str(self.root/'remote'),
                       'root_id': 'root', 'interval': 60, 'ignores': DEFAULT_IGNORES}
        self.patches = [patch('lumesync.app.load', return_value=self.config),
                        patch('lumesync.app.DATA', self.root/'runtime'), patch.object(Window, 'log')]
        for item in self.patches: item.start()
        self.window = Window(); self.window.tray_timer.stop()

    def tearDown(self):
        self.window.force_exit = True; self.window.close(); self.app.processEvents()
        for item in reversed(self.patches): item.stop()
        self.temp.cleanup()

    def test_close_hides_in_every_mode_and_keeps_timer_active(self):
        self.window.show(); self.window.timer.start(60000)
        event = QCloseEvent()
        with patch('lumesync.app.QSystemTrayIcon.isSystemTrayAvailable', return_value=True), patch.object(self.window, 'pause') as pause:
            self.window.closeEvent(event)
            pause.assert_not_called()
        self.assertFalse(event.isAccepted())
        self.assertFalse(self.window.isVisible())
        self.assertTrue(self.window.timer.isActive())

    def test_no_tray_minimizes_instead_of_quitting_or_hiding_forever(self):
        self.window.show(); event = QCloseEvent()
        with patch('lumesync.app.QSystemTrayIcon.isSystemTrayAvailable', return_value=False):
            self.window.closeEvent(event)
        self.assertFalse(event.isAccepted())
        self.assertTrue(self.window.isMinimized())
        self.assertTrue(self.window.isVisible())

    def test_explicit_exit_quits_application(self):
        with patch.object(self.app, 'quit') as quit_app:
            self.window.request_quit()
            quit_app.assert_called_once()
        self.assertTrue(self.window.force_exit)

    def test_scope_hides_link_for_all_drive_and_extracts_folder_url(self):
        self.assertTrue(self.window.root_id.isHidden())
        self.window.mode.setCurrentIndex(1)
        self.window.drive_scope.setCurrentIndex(1)
        self.assertFalse(self.window.root_id.isHidden())
        self.window.root_id.setText('https://drive.google.com/drive/folders/Selected123')
        self.assertEqual(self.window.form_config()['root_id'], 'Selected123')

    def test_missing_account_routes_to_settings_without_worker(self):
        self.window.config['mode'] = 'drive'
        with patch('lumesync.app.Worker') as worker:
            self.window.start('scan')
            worker.assert_not_called()
        self.assertEqual(self.window.tabs.currentIndex(), self.window.settings_tab_index)
        self.assertIn('Conecte sua conta', self.window.status.text())

    def test_authorization_schedules_setup_after_worker_is_idle(self):
        with patch.object(self.window, 'setup_drive') as setup:
            self.window.completed({'authorized': True})
            self.assertTrue(self.window.pending_setup)
            self.window.idle(); self.app.processEvents()
            setup.assert_called_once()

    def test_setup_worker_does_not_bulk_download(self):
        worker = Worker(self.config, 'setup-drive'); results = []
        worker.completed.connect(results.append)
        controller = Mock(config={'mode': 'drive', 'root_id': 'canonical'})
        with patch('lumesync.online.setup', return_value=controller) as setup, patch('lumesync.app.build') as build:
            worker.run()
            build.assert_not_called()
            setup.assert_called_once_with(config=self.config)
        self.assertTrue(results[0]['setup'])


class SetupFolderTests(unittest.TestCase):
    def test_setup_respects_specific_folder(self):
        import lumesync.online as online
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)/'user'; home.mkdir(); data = Path(d)/'runtime'
            old = {'root_id': 'Selected123', 'drive_scope': 'folder', 'pins': []}
            provider = Mock(); provider.request.return_value.json.return_value = {'id': 'Selected123', 'mimeType': FOLDER}
            controller = Mock()
            with patch.object(online, 'DATA', data), patch.object(online, 'DriveProvider', return_value=provider), patch.object(online, 'OnlineDrive', return_value=controller) as factory, patch.object(online, 'save'), patch('lumesync.setup_real.add_place'):
                online.setup(home, old)
            self.assertTrue(provider.request.call_args.args[1].endswith('/Selected123'))
            self.assertEqual(factory.call_args.args[0]['root_id'], 'Selected123')
            controller.configure_backend.assert_called_once()
            controller.start.assert_called_once()

    def test_all_drive_resolves_canonical_root_without_using_stale_id(self):
        import lumesync.online as online
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)/'user'; home.mkdir()
            provider = Mock(); provider.request.return_value.json.return_value = {'id': 'CanonicalRoot', 'mimeType': FOLDER}
            with patch.object(online, 'DATA', Path(d)/'runtime'), patch.object(online, 'DriveProvider', return_value=provider), patch.object(online, 'OnlineDrive') as factory, patch.object(online, 'save'), patch('lumesync.setup_real.add_place'):
                online.setup(home, {'root_id': 'old-id', 'drive_scope': 'all'})
            self.assertTrue(provider.request.call_args.args[1].endswith('/root'))
            self.assertEqual(factory.call_args.args[0]['root_id'], 'CanonicalRoot')
