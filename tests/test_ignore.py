import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from lumesync.ignore import IgnoreRules


class IgnoreTests(unittest.TestCase):
    def test_comments_and_negation_last_match_wins(self):
        rules=IgnoreRules(['# comment','*.tmp','!keep.tmp'])
        self.assertTrue(rules.matches('nested/skip.tmp'))
        self.assertFalse(rules.matches('keep.tmp'))
        self.assertFalse(rules.matches('notes.txt'))

    def test_root_anchor_and_nested_path(self):
        rules=IgnoreRules(['/Filmes/','docs/private/*'])
        self.assertTrue(rules.matches('Filmes/movie.mkv'))
        self.assertFalse(rules.matches('other/Filmes/movie.mkv'))
        self.assertTrue(rules.matches('docs/private/a.txt'))
        self.assertFalse(rules.matches('other/docs/private/a.txt'))

    def test_directory_rule_does_not_hide_same_named_file(self):
        rules=IgnoreRules(['cache/'])
        self.assertTrue(rules.matches('cache',is_dir=True))
        self.assertTrue(rules.matches('nested/cache/a'))
        self.assertFalse(rules.matches('cache',is_dir=False))

    def test_double_star_and_escaped_comment(self):
        rules=IgnoreRules(['docs/**/private?.txt',r'\#draft'])
        self.assertTrue(rules.matches('docs/private1.txt'))
        self.assertTrue(rules.matches('docs/a/b/private2.txt'))
        self.assertFalse(rules.matches('docs/a/b/private22.txt'))
        self.assertTrue(rules.matches('#draft'))

    @unittest.skipUnless(shutil.which('rclone'),'rclone indisponível')
    def test_native_rclone_filter_matches_exclusions_and_exceptions(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'source';source.mkdir()
            names=['.venv/x','nested/.venv/y','keep.tmp','nested/keep.tmp','skip.tmp','nested/skip.tmp','notes.txt']
            for name in names:
                p=source/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('a')
            rules=IgnoreRules(['.venv/','*.tmp','!keep.tmp'])
            filters=root/'filters';filters.write_text(rules.rclone_filters())
            result=subprocess.run(['rclone','lsf',str(source),'--recursive','--files-only','--filter-from',str(filters)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(set(result.stdout.splitlines()),{name for name in names if not rules.matches(name)})


if __name__=='__main__':unittest.main()
