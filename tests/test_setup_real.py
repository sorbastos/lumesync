import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from lumesync.setup_real import add_place,prepare


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.home=self.root/'home';self.home.mkdir();self.data=self.root/'runtime'
    def tearDown(self):self.temp.cleanup()
    def test_prepare_folder_config_and_dolphin_place(self):
        folder=prepare(self.home,self.data,'real-root-id')
        self.assertTrue(folder.is_dir())
        config=json.loads((self.data/'config.json').read_text())
        self.assertEqual(config['local'],str(folder))
        self.assertEqual(config['root_id'],'real-root-id')
        places=ET.parse(self.home/'.local/share/user-places.xbel').getroot()
        self.assertEqual(places.find('bookmark').get('href'),folder.as_uri())
    def test_preserve_favorites_and_idempotence(self):
        places=self.home/'places.xbel'
        original=b'<xbel><bookmark href="file:///original"><title>Original</title></bookmark></xbel>'
        places.write_bytes(original)
        add_place(places,self.home/'Drive');add_place(places,self.home/'Drive')
        bookmarks=ET.parse(places).getroot().findall('bookmark')
        self.assertEqual(len(bookmarks),2)
        self.assertEqual(bookmarks[0].findtext('title'),'Original')
        self.assertEqual(next(self.home.glob('*.lume-backup-*')).read_bytes(),original)
    def test_existing_personal_folder_refused(self):
        folder=self.home/'Lume Sync/Google Drive';folder.mkdir(parents=True);(folder/'personal').write_text('keep')
        with self.assertRaises(ValueError):prepare(self.home,self.data,'root')
        self.assertEqual((folder/'personal').read_text(),'keep')
        self.assertFalse((self.data/'config.json').exists())
    def test_symlink_refused(self):
        (self.home/'Lume Sync').symlink_to(self.root,target_is_directory=True)
        with self.assertRaises(ValueError):prepare(self.home,self.data,'root')
    def test_invalid_bookmarks_preserved(self):
        places=self.home/'places.xbel';places.write_text('invalid XML')
        with self.assertRaises(ET.ParseError):add_place(places,self.home/'Drive')
        self.assertEqual(places.read_text(),'invalid XML')
    def test_previous_configuration_backed_up(self):
        self.data.mkdir();(self.data/'config.json').write_text('{"mode":"demo"}')
        prepare(self.home,self.data,'root')
        self.assertEqual(json.loads(next(self.data.glob('config-before-real-*')).read_text()),{'mode':'demo'})


if __name__=='__main__':unittest.main()
