import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication
from lumesync.app import Window, STYLE
from lumesync.core import Engine, State, LocalProvider, DEFAULT_IGNORES


class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyleSheet(STYLE)

    def test_preview_then_sync_preserves_conflict(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); local = root/'local'; remote = root/'remote'
            local.mkdir(); remote.mkdir()
            (local/'send.txt').write_text('local')
            (remote/'receive.txt').write_text('remote')
            (local/'conflict.txt').write_text('left')
            (remote/'conflict.txt').write_text('right')
            config = {'mode':'demo', 'local': str(local), 'remote': str(remote), 'root_id':'root', 'interval':60, 'ignores':DEFAULT_IGNORES}
            def build(_):
                return Engine(local, LocalProvider(remote), State(root/'state'))
            def wait(window):
                deadline = time.monotonic() + 10
                while window.worker.isRunning() and time.monotonic() < deadline:
                    self.app.processEvents(); time.sleep(.005)
                self.assertFalse(window.worker.isRunning())
                self.app.processEvents()
            with patch('lumesync.app.load', return_value=config), patch('lumesync.app.build', side_effect=build):
                window = Window()
                try:
                    window.start('scan'); wait(window)
                    self.assertEqual(window.table.rowCount(), 3)
                    self.assertEqual(window.cards['attention'].text(), '1')
                    self.assertTrue(window.sync_button.isEnabled())
                    window.sync_preview(); wait(window)
                    self.assertTrue((remote/'send.txt').exists())
                    self.assertTrue((local/'receive.txt').exists())
                    self.assertEqual((local/'conflict.txt').read_text(), 'left')
                    self.assertEqual((remote/'conflict.txt').read_text(), 'right')
                    self.assertEqual(window.cards['equal'].text(), '2')
                    self.assertEqual(window.cards['attention'].text(), '1')
                finally:
                    window.close(); self.app.processEvents()


    def test_online_ui_shows_pin_and_never_starts_bulk_sync(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            config={'mode':'drive','access_mode':'online','local':str(root/'mount'),'offline_local':str(root/'Offline'),
                    'remote':'demo','root_id':'root','interval':60,'ignores':DEFAULT_IGNORES,'pins':[]}
            with patch('lumesync.app.load',return_value=config):
                window=Window();window.force_exit=True
                try:
                    window.completed_online({'config':config,'relative':'','entries':[{'Name':'a.txt','ID':'id','IsDir':False,'Size':4}],
                                             'mounted':True,'offline_actions':None,'errors':[]})
                    self.assertEqual(window.cards['equal'].text(),'Ativo')
                    self.assertEqual(window.cards['download'].text(),'0')
                    self.assertFalse(window.auto.isVisible())
                    self.assertEqual(window.table.rowCount(),1)
                    with patch.object(window,'start') as start:
                        window.sync_preview()
                        start.assert_called_once_with('sync')
                finally:window.close();self.app.processEvents()

    def test_unpin_preserves_existing_offline_file(self):
        from PySide6.QtWidgets import QMessageBox
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);offline=root/'Offline';offline.mkdir();local=offline/'a.txt';local.write_text('unsent edit')
            config={'mode':'drive','access_mode':'online','local':str(root/'mount'),'offline_local':str(offline),
                    'remote':'demo','root_id':'root','interval':60,'ignores':DEFAULT_IGNORES,
                    'pins':[{'path':'a.txt','remote_id':'id','label':'a.txt'}]}
            with patch('lumesync.app.load',return_value=config),patch('lumesync.app.save') as save:
                window=Window();window.force_exit=True
                try:
                    window.completed_online({'config':config,'relative':'','entries':[{'Name':'a.txt','ID':'id','IsDir':False,'Size':4}],
                                             'mounted':True,'offline_actions':None,'errors':[]})
                    window.table.selectRow(0)
                    with patch('lumesync.app.QMessageBox.question',return_value=QMessageBox.StandardButton.Yes),patch.object(window,'start'):
                        window.pin_selected()
                    self.assertEqual(window.config['pins'],[])
                    self.assertEqual(local.read_text(),'unsent edit')
                    save.assert_called_once()
                finally:window.close();self.app.processEvents()


if __name__ == '__main__': unittest.main()
