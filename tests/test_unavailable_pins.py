import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from lumesync.online import OnlineDrive, UnavailablePin
from lumesync.core import Engine, LocalProvider, State
from lumesync.ignore import OfflineExclusions


class UnavailablePinTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.cfg={'mode':'drive','local':str(self.root/'mount'),'offline_local':str(self.root/'offline'),
                  'pins':[{'path':'trashed','label':'trashed','remote_id':'gone'},
                          {'path':'kept','label':'kept','remote_id':'kept-id'}]}
        self.controller=OnlineDrive(self.cfg,self.root/'data')

    def test_trashed_item_never_looks_up_alias(self):
        provider=Mock(root_id='root-id')
        provider.request.return_value.json.return_value={'id':'gone','trashed':True,'parents':['root-id']}
        with self.assertRaisesRegex(UnavailablePin,'lixeira'):
            self.controller.resolve_item_path(provider,'gone')
        provider.children.assert_not_called()

    def test_trashed_parent_is_also_blocked(self):
        provider=Mock(root_id='root-id')
        provider.request.return_value.json.side_effect=[{'id':'child','parents':['parent'],'trashed':False},
                                                       {'id':'parent','parents':['root-id'],'trashed':True}]
        with self.assertRaisesRegex(UnavailablePin,'lixeira'):
            self.controller.resolve_item_path(provider,'child')
        provider.children.assert_not_called()

    def test_missing_sibling_becomes_explanatory_warning_not_keyerror(self):
        provider=Mock(root_id='root-id',name_map={})
        provider.request.return_value.json.return_value={'id':'gone','parents':['root-id'],'name':'gone'}
        provider.children.return_value=[]
        with self.assertRaisesRegex(UnavailablePin,'mudou durante'):
            self.controller.resolve_item_path(provider,'gone')

    def test_unavailable_pin_cannot_upload_local_files_but_other_pin_syncs(self):
        remote=LocalProvider(self.root/'remote');state=State(self.root/'state')
        self.addCleanup(state.close)
        engine=Engine(self.root/'offline',remote,state)
        (engine.local/'trashed').mkdir();(engine.local/'trashed/edit').write_text('unsent edit')
        (remote.root/'kept').mkdir();(remote.root/'kept/new').write_text('cloud')
        with patch('lumesync.config.build',return_value=engine),patch.object(state,'close'),patch.object(self.controller,'resolve_item_path',side_effect=[UnavailablePin('Na lixeira; cópia preservada'),('kept','kept')]):
            self.controller.reconcile_pins()
        cfg=self.controller.offline_config()
        remote.include_paths=cfg['include_paths']
        engine=Engine(engine.local,remote,state,OfflineExclusions([],cfg['offline_excludes']))
        engine.apply(engine.plan())
        self.assertEqual((engine.local/'trashed/edit').read_text(),'unsent edit')
        self.assertFalse((remote.root/'trashed').exists())
        self.assertEqual((engine.local/'kept/new').read_text(),'cloud')
        self.assertEqual(len(self.controller.pin_warnings),1)
        self.assertNotIn('offline_excludes',self.controller.config)
        # Restoration is reconsidered on the next cycle, not permanently excluded.
        with patch('lumesync.config.build',return_value=engine),patch.object(state,'close'),patch.object(self.controller,'resolve_item_path',side_effect=[('trashed','trashed'),('kept','kept')]):
            self.controller.reconcile_pins()
        self.assertEqual(self.controller.unavailable_paths,[])
        self.assertEqual(self.controller.pin_warnings,[])
