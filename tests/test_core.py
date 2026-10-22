import tempfile
import unittest
from pathlib import Path

from lumesync.core import Engine, State, LocalProvider, digest, safe_path, atomic_download, exclusive


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.local = self.root / 'local'
        self.remote = self.root / 'remote'
        self.state = State(self.root / 'state')
        self.engine = Engine(self.local, LocalProvider(self.remote), self.state)

    def tearDown(self):
        self.state.close()
        self.temp.cleanup()

    def write(self, root, path, text):
        target = root / path; target.parent.mkdir(parents=True, exist_ok=True); target.write_text(text)

    def sync(self):
        self.engine.apply(self.engine.plan())

    def kinds(self):
        return {a.path: a.kind for a in self.engine.plan()}

    def test_bidirectional_and_nested_unicode(self):
        self.write(self.local, 'a/ação.txt', 'local')
        self.write(self.remote, 'b.txt', 'remote')
        self.sync()
        self.assertEqual((self.remote/'a/ação.txt').read_text(), 'local')
        self.assertEqual((self.local/'b.txt').read_text(), 'remote')
        self.assertTrue(all(k == 'equal' for k in self.kinds().values()))

    def test_updates_both_directions(self):
        self.write(self.local, 'a', 'v1'); self.sync()
        self.write(self.local, 'a', 'v2'); self.assertEqual(self.kinds()['a'], 'upload'); self.sync()
        self.write(self.remote, 'a', 'v3'); self.assertEqual(self.kinds()['a'], 'download'); self.sync()
        self.assertEqual((self.local/'a').read_text(), 'v3')

    def test_initial_conflict_preserves_both(self):
        self.write(self.local, 'a', 'left'); self.write(self.remote, 'a', 'right')
        self.assertEqual(self.kinds()['a'], 'conflict'); self.sync()
        self.assertEqual((self.local/'a').read_text(), 'left')
        self.assertEqual((self.remote/'a').read_text(), 'right')

    def test_simultaneous_edit_and_resolution(self):
        self.write(self.local, 'a', 'v1'); self.sync()
        self.write(self.local, 'a', 'local'); self.write(self.remote, 'a', 'remote')
        plan = self.engine.plan(); self.assertEqual(plan[0].kind, 'conflict')
        self.engine.apply(plan, {'a': 'local'})
        self.assertEqual((self.remote/'a').read_text(), 'local')

    def test_remote_resolution(self):
        self.write(self.local, 'a', 'one'); self.write(self.remote, 'a', 'two')
        self.engine.apply(self.engine.plan(), {'a': 'remote'})
        self.assertEqual((self.local/'a').read_text(), 'two')

    def test_local_delete_is_held_then_restored(self):
        self.write(self.local, 'a', 'v1'); self.sync(); (self.local/'a').unlink()
        self.assertEqual(self.kinds()['a'], 'deletion'); self.sync()
        self.assertFalse((self.local/'a').exists()); self.assertTrue((self.remote/'a').exists())
        self.engine.apply(self.engine.plan(), {'a': 'remote'})
        self.assertEqual((self.local/'a').read_text(), 'v1')

    def test_remote_delete_is_held_then_restored(self):
        self.write(self.local, 'a', 'v1'); self.sync(); (self.remote/'a').unlink()
        self.sync(); self.assertFalse((self.remote/'a').exists())
        self.engine.apply(self.engine.plan(), {'a': 'local'})
        self.assertTrue((self.remote/'a').exists())

    def test_cannot_erase_by_choosing_absent_side(self):
        self.write(self.local, 'a', 'v1'); self.sync(); (self.local/'a').unlink()
        self.engine.apply(self.engine.plan(), {'a': 'local'})
        self.assertEqual((self.remote/'a').read_text(), 'v1')

    def test_ignore_environments_on_both_sides(self):
        self.write(self.local, '.venv/lib/code.py', 'ignore'); self.write(self.remote, '__pycache__/x.pyc', 'ignore')
        self.write(self.local, 'app.py', 'keep'); self.sync()
        self.assertEqual(list(self.kinds()), ['app.py'])
        self.assertFalse((self.remote/'.venv').exists())

    def test_symlink_outside_not_followed(self):
        self.write(self.root, 'outside/secret', 'private')
        (self.local/'link').symlink_to(self.root/'outside', target_is_directory=True)
        self.assertEqual(self.engine.plan(), [])
        with self.assertRaises(ValueError): safe_path(self.local, 'link/secret')

    def test_unsafe_names(self):
        for name in ['../bad', '/etc/passwd', 'x/../../bad', 'a//b', '.', 'a\\b']:
            with self.subTest(name=name), self.assertRaises(ValueError): safe_path(self.local, name)

    def test_stale_local_preview(self):
        self.write(self.local, 'a', 'v1'); plan = self.engine.plan(); self.write(self.local, 'a', 'v2')
        with self.assertRaises(RuntimeError): self.engine.apply(plan)
        self.assertFalse((self.remote/'a').exists())

    def test_stale_remote_preview(self):
        self.write(self.remote, 'a', 'v1'); plan = self.engine.plan(); self.write(self.remote, 'a', 'v2')
        with self.assertRaises(RuntimeError): self.engine.apply(plan)
        self.assertFalse((self.local/'a').exists())

    def test_checksum_failure_preserves_destination(self):
        target = self.local/'a'; target.write_text('original')
        with self.assertRaises(RuntimeError):
            atomic_download(target, 'wrong', lambda temp: temp.write_text('bad'))
        self.assertEqual(target.read_text(), 'original')
        self.assertEqual(list(self.local.glob('.lume-*')), [])

    def test_edit_during_download_is_preserved(self):
        self.write(self.local, 'a', 'v1'); self.sync(); self.write(self.remote, 'a', 'v2')
        provider = self.engine.provider; original = provider.download
        def changing(item, destination):
            original(item, destination); self.write(self.local, 'a', 'edited during download')
        provider.download = changing
        with self.assertRaises(RuntimeError): self.sync()
        self.assertEqual((self.local/'a').read_text(), 'edited during download')

    def test_conflicting_file_directory_is_blocked(self):
        self.write(self.local, 'a', 'file'); self.write(self.remote, 'a/b', 'child')
        self.assertTrue(all(k == 'blocked' for k in self.kinds().values()))
        self.sync(); self.assertEqual((self.local/'a').read_text(), 'file')

    def test_empty_remote_directory_collision(self):
        self.write(self.local, 'a', 'file'); (self.remote/'a').mkdir()
        self.assertEqual(self.kinds()['a'], 'blocked')

    def test_nested_roots_rejected(self):
        with self.assertRaises(ValueError): Engine(self.local, LocalProvider(self.local/'child'), self.state)

    def test_empty_file(self):
        self.write(self.local, 'empty', ''); self.sync()
        self.assertEqual((self.remote/'empty').stat().st_size, 0)

    def test_lock(self):
        with exclusive(self.state.directory):
            with self.assertRaises(RuntimeError):
                with exclusive(self.state.directory): pass

    def test_pause_between_transfers(self):
        self.write(self.local, 'a', 'a'); self.write(self.local, 'b', 'b')
        self.engine.apply(self.engine.plan(), cancelled=lambda: True)
        self.assertEqual(list(self.remote.iterdir()), [])


    def test_metadata_only_change_does_not_invalidate_content_preview(self):
        from dataclasses import replace
        self.write(self.remote, 'a', 'unchanged')
        original_scan = self.engine.provider.scan
        generation = [0]
        def scan(patterns):
            generation[0] += 1
            return {path: replace(item, version=str(generation[0])) for path,item in original_scan(patterns).items()}
        self.engine.provider.scan = scan
        self.engine.apply(self.engine.plan())
        self.assertEqual((self.local/'a').read_text(), 'unchanged')


    def test_failure_can_be_isolated_without_stopping_remaining_files(self):
        self.write(self.remote, 'a-bad', 'bad'); self.write(self.remote, 'b-good', 'good')
        original=self.engine.provider.download
        def download(item,destination):
            if item.path=='a-bad':raise RuntimeError('simulated failure')
            return original(item,destination)
        self.engine.provider.download=download
        self.engine.apply(self.engine.plan(),continue_on_error=True)
        self.assertFalse((self.local/'a-bad').exists())
        self.assertEqual((self.local/'b-good').read_text(),'good')
        self.assertEqual(len(self.engine.errors),1)
        self.assertNotIn('a-bad',self.state.baseline())


    def test_insufficient_space_stops_before_any_download(self):
        from unittest.mock import patch
        from collections import namedtuple
        self.write(self.remote,'a','content')
        Usage=namedtuple('Usage','total used free')
        with patch('shutil.disk_usage',return_value=Usage(100,99,1)):
            with self.assertRaises(RuntimeError):self.engine.apply(self.engine.plan())
        self.assertFalse((self.local/'a').exists())

    def test_state_is_persistent(self):
        self.write(self.local, 'a', 'a'); self.sync(); self.state.close()
        self.state = State(self.root/'state'); self.engine.state = self.state
        self.assertIn('a', self.state.baseline())


if __name__ == '__main__': unittest.main()
