import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from lumesync.online import OnlineDrive
from lumesync.core import Engine,State,LocalProvider


class OnlineTests(unittest.TestCase):
    def test_mount_command_is_bounded_and_has_no_bulk_sync(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            c=OnlineDrive({'local':str(root/'mount')},root/'runtime')
            c.rclone='/usr/bin/rclone';args=c.mount_arguments()
            self.assertIn('mount',args);self.assertNotIn('sync',args);self.assertNotIn('copy',args)
            self.assertEqual(args[args.index('--vfs-cache-max-size')+1],'2G')
            self.assertEqual(args[args.index('--buffer-size')+1],'8M')
            self.assertNotIn('--allow-non-empty',args)

    def test_offline_config_limits_scope_to_explicit_pins(self):
        c=OnlineDrive({'local':'/tmp/cloud','access_mode':'online','pins':[{'path':'Finance','remote_id':'id'}]})
        config=c.offline_config()
        self.assertEqual(config['access_mode'],'offline')
        self.assertEqual(config['include_paths'],['Finance'])
        self.assertNotEqual(config['local'],'/tmp/cloud')

    def test_online_mode_refuses_bulk_engine(self):
        from lumesync.config import build
        with self.assertRaises(ValueError):build({'access_mode':'online'})

    def test_only_selected_files_are_copied_offline(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);provider=LocalProvider(root/'remote')
            (provider.root/'chosen').mkdir();(provider.root/'chosen/a').write_text('a')
            (provider.root/'not-chosen').write_text('must stay online')
            provider.include_paths=['chosen']
            state=State(root/'state')
            try:
                engine=Engine(root/'offline',provider,state)
                plan=engine.plan();self.assertEqual([a.path for a in plan],['chosen/a'])
                engine.apply(plan)
                self.assertTrue((root/'offline/chosen/a').exists())
                self.assertFalse((root/'offline/not-chosen').exists())
            finally:state.close()

    def test_no_pins_means_no_downloads(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);provider=LocalProvider(root/'remote');(provider.root/'a').write_text('a')
            provider.include_paths=[];state=State(root/'state')
            try:self.assertEqual(Engine(root/'offline',provider,state).plan(),[])
            finally:state.close()


    def test_drive_oauth_client_secret_uses_plain_config_field(self):
        import configparser,json
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);data=root/'runtime';data.mkdir()
            (data/'google-token.json').write_text(json.dumps({'access_token':'fake','refresh_token':'fake-refresh',
                'client_id':'fake-client','client_secret':'literal-desktop-secret','expires_at':2000000000}))
            c=OnlineDrive({'local':str(root/'mount'),'root_id':'root'},data)
            c.rclone='/usr/bin/rclone';c.configure_backend()
            parser=configparser.ConfigParser(interpolation=None);parser.read(c.rclone_config)
            self.assertEqual(parser['lume-drive']['client_secret'],'literal-desktop-secret')
            self.assertEqual(c.rclone_config.stat().st_mode & 0o777,0o600)

    def test_existing_backend_refresh_token_is_preserved(self):
        import configparser,json
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);data=root/'runtime';data.mkdir()
            (data/'google-token.json').write_text(json.dumps({'access_token':'old','client_id':'fake',
                'client_secret':'secret','expires_at':2000000000}))
            c=OnlineDrive({'local':str(root/'mount'),'root_id':'root'},data)
            c.rclone='/usr/bin/rclone';c.configure_backend()
            parser=configparser.ConfigParser(interpolation=None);parser.read(c.rclone_config)
            parser['lume-drive']['token']='{"access_token":"newer"}'
            with c.rclone_config.open('w') as handle:parser.write(handle)
            c.configure_backend();parser.read(c.rclone_config)
            self.assertEqual(json.loads(parser['lume-drive']['token'])['access_token'],'newer')


if __name__=='__main__':unittest.main()
