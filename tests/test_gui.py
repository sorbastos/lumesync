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



class StatusAndRetryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        self.config = {'mode': 'drive', 'access_mode': 'online', 'local': str(root/'mount'),
                       'offline_local': str(root/'Offline'), 'remote': str(root/'remote'),
                       'root_id': 'root', 'interval': 60, 'ignores': [],
                       'pins': [{'remote_id': 'id', 'path': 'a.txt', 'label': 'a.txt'}]}
        self.load = patch('lumesync.app.load', return_value=self.config); self.load.start()
        self.logging = patch.object(Window, 'log'); self.logging.start()
        self.window = Window(); self.window.force_exit = True

    def tearDown(self):
        self.window.close(); self.app.processEvents()
        self.load.stop(); self.logging.stop(); self.directory.cleanup()

    def result(self, errors=None):
        from lumesync.core import Action, Item
        item = Item('a.txt', 'hash', 4)
        return {'config': self.config, 'relative': '', 'mounted': True,
                'entries': [{'ID': 'id', 'Name': 'a.txt', 'Size': 4}, {'ID': 'other', 'Name': 'cloud.txt', 'Size': 1}],
                'offline_actions': [Action('a.txt', 'download', 'Novo na nuvem', None, item)], 'errors': errors or []}

    def test_cloud_pending_and_active_states(self):
        self.window.completed_online(self.result())
        self.assertEqual(self.window.table.item(0, 1).text(), 'Aguardando download')
        self.assertIn('Na nuvem', self.window.table.item(1, 1).text())
        self.window.receive_transfer({'path': 'a.txt', 'kind': 'download'})
        self.assertEqual(self.window.table.item(0, 1).text(), 'Baixando…')

    def test_failed_file_survives_metadata_refresh_and_retry_is_scoped(self):
        self.window.last_request = {'job': 'offline-sync'}
        self.window.completed_online(self.result([{'path': 'a.txt', 'message': 'Connection timed out'}]))
        self.window.last_request = {'job': 'scan'}
        self.window.completed_online(self.result())
        self.assertIn('Erro', self.window.table.item(0, 1).text())
        self.assertIn('Confira a internet', self.window.issues.toPlainText())
        with patch.object(self.window, 'start') as start:
            self.window.retry_failed()
            start.assert_called_once_with('offline-sync', retry_paths={'a.txt'})

    def test_successful_retry_clears_error(self):
        self.window.file_errors = {'a.txt': 'timeout'}
        self.window.last_request = {'job': 'offline-sync'}
        self.window.completed_online(self.result())
        self.assertEqual(self.window.file_errors, {})
        self.assertIsNone(self.window.retry_context)

    def test_global_failure_offers_retry_without_replaying_resolution(self):
        self.window.last_request = {'job': 'offline-resolve', 'relative': '', 'entry': None, 'client': None}
        self.window.failure('Connection timed out')
        self.assertIn('Confira a internet', self.window.subtitle.text())
        with patch.object(self.window, 'start') as start:
            self.window.retry_failed()
            start.assert_called_once_with('scan', client=None)

    def test_retry_replans_without_downloading_unrelated_file(self):
        from lumesync.app import Worker
        root = Path(self.directory.name); local = root/'local'; remote = root/'remote'
        local.mkdir(); remote.mkdir()
        (remote/'a.txt').write_text('retry this')
        (remote/'other.txt').write_text('not selected for retry')
        config = {**self.config, 'access_mode': 'offline', 'mode': 'demo', 'local': str(local), 'remote': str(remote)}
        events = []; results = []; errors = []
        worker = Worker(config, 'sync'); worker.retry_paths = {'a.txt'}
        worker.transferring.connect(events.append); worker.completed.connect(results.append); worker.failed.connect(errors.append)
        def build(_):
            return Engine(local, LocalProvider(remote), State(root/'state'))
        with patch('lumesync.app.build', side_effect=build):
            worker.run()
        self.assertFalse(errors)
        self.assertEqual((local/'a.txt').read_text(), 'retry this')
        self.assertFalse((local/'other.txt').exists())
        self.assertEqual(events, [{'path': 'a.txt', 'kind': 'download'}])
        self.assertTrue(results)

    def test_retry_does_not_overwrite_new_conflict(self):
        from lumesync.app import Worker
        root = Path(self.directory.name); local = root/'local'; remote = root/'remote'
        local.mkdir(); remote.mkdir()
        (local/'a.txt').write_text('local change')
        (remote/'a.txt').write_text('cloud change')
        config = {**self.config, 'access_mode': 'offline', 'mode': 'demo', 'local': str(local), 'remote': str(remote)}
        worker = Worker(config, 'sync'); worker.retry_paths = {'a.txt'}
        errors = []; worker.failed.connect(errors.append)
        with patch('lumesync.app.build', side_effect=lambda _: Engine(local, LocalProvider(remote), State(root/'state'))):
            worker.run()
        self.assertFalse(errors)
        self.assertEqual((local/'a.txt').read_text(), 'local change')
        self.assertEqual((remote/'a.txt').read_text(), 'cloud change')


if __name__ == '__main__':
    unittest.main()
