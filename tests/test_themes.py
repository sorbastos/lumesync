import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from lumesync import themes
from lumesync.app import Window


class ThemeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.preference = root/'appearance.ini'
        self.store_patch = patch('lumesync.themes.settings', side_effect=lambda: QSettings(str(self.preference), QSettings.Format.IniFormat))
        self.store_patch.start()
        self.config = {'mode': 'demo', 'local': str(root/'local'), 'remote': str(root/'remote'),
                       'root_id': 'root', 'interval': 60, 'ignores': []}
        self.config_patch = patch('lumesync.app.load', return_value=self.config); self.config_patch.start()
        self.log_patch = patch.object(Window, 'log'); self.log_patch.start()
        self.windows = []

    def tearDown(self):
        for window in self.windows:
            window.close()
        self.app.processEvents()
        self.store_patch.stop(); self.config_patch.stop(); self.log_patch.stop()
        self.temp.cleanup()

    def window(self):
        window = Window(); self.windows.append(window)
        return window

    def test_new_install_defaults_to_dark(self):
        window = self.window()
        self.assertEqual(window.theme, 'dark')
        self.assertEqual(window.theme_selector.currentText(), 'Escuro')
        self.assertFalse(self.preference.exists())

    def test_switch_applies_immediately_and_survives_new_window(self):
        window = self.window()
        with patch('lumesync.app.save') as save_sync:
            window.theme_selector.setCurrentIndex(1)
            self.assertEqual(window.theme, 'light')
            self.assertIn('#f6f8fb', self.app.styleSheet())
            save_sync.assert_not_called()
        second = self.window()
        self.assertEqual(second.theme_selector.currentText(), 'Claro')
        second.theme_selector.setCurrentIndex(0)
        self.assertEqual(themes.load_theme(), 'dark')

    def test_invalid_preference_uses_dark(self):
        store = themes.settings(); store.setValue('theme', 'unexpected'); store.sync()
        self.assertEqual(themes.load_theme(), 'dark')

    def test_save_failure_preserves_previous_theme(self):
        window = self.window()
        with patch('lumesync.app.save_theme', side_effect=OSError('Falha de gravação')), patch('lumesync.app.QMessageBox.warning') as warning:
            window.theme_selector.setCurrentIndex(1)
            self.assertEqual(window.theme, 'dark')
            self.assertEqual(window.theme_selector.currentData(), 'dark')
            warning.assert_called_once()

    def test_theme_does_not_modify_pending_configuration(self):
        import copy
        window = self.window()
        window.local.setText('pasta ainda não salva')
        before = copy.deepcopy(window.config)
        window.theme_selector.setCurrentIndex(1)
        self.assertEqual(window.local.text(), 'pasta ainda não salva')
        self.assertEqual(window.config, before)
