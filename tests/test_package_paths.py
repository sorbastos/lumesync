import tempfile
import unittest
from pathlib import Path
from lumesync.config import data_directory
from lumesync.launcher import select_profile


class PackagePathsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project = self.root/'package'; self.project.mkdir()
        self.home_dir = self.root/'user'

    def tearDown(self):
        self.temp.cleanup()

    def test_installed_package_uses_user_data_directory(self):
        data = data_directory(self.project, self.home_dir, {})
        self.assertEqual(data, self.home_dir/'.local/share/lumesync')
        self.assertFalse(data.exists())
        self.assertFalse(data.is_relative_to(self.project))

    def test_source_checkout_preserves_existing_runtime(self):
        (self.project/'pyproject.toml').touch()
        self.assertEqual(data_directory(self.project, self.home_dir, {}), self.project/'runtime')

    def test_xdg_path_and_relative_fallback(self):
        base = self.root/'user-data'
        self.assertEqual(data_directory(self.project, self.home_dir, {'XDG_DATA_HOME': str(base)}), base/'lumesync')
        self.assertEqual(data_directory(self.project, self.home_dir, {'XDG_DATA_HOME': 'relative'}), self.home_dir/'.local/share/lumesync')

    def test_explicit_existing_profile_requires_absolute_path(self):
        profile = self.root/'existing-profile'
        self.assertEqual(data_directory(self.project, self.home_dir, {'LUMESYNC_DATA_DIR': str(profile)}), profile)
        with self.assertRaises(ValueError):
            data_directory(self.project, self.home_dir, {'LUMESYNC_DATA_DIR': 'runtime'})

    def test_named_profile_is_isolated_and_does_not_move_default_profile(self):
        normal = data_directory(self.project, self.home_dir, {})
        test = data_directory(self.project, self.home_dir, {'LUMESYNC_PROFILE': 'teste'})
        other = data_directory(self.project, self.home_dir, {'LUMESYNC_PROFILE': 'outro-teste'})
        self.assertEqual(normal, self.home_dir/'.local/share/lumesync')
        self.assertEqual(test, normal/'named-profiles/teste')
        self.assertEqual(other, normal/'named-profiles/outro-teste')
        self.assertNotEqual(test, other)

    def test_launcher_selects_named_profile_before_importing_application(self):
        environ = {}
        remaining = select_profile(['--profile', 'teste', '--monitor'], environ)
        self.assertEqual(environ['LUMESYNC_PROFILE'], 'teste')
        self.assertEqual(remaining, ['--monitor'])

    def test_invalid_or_ambiguous_profile_is_rejected(self):
        for name in ('Teste', '../teste', 'teste_2', 'a'*33):
            with self.subTest(name=name), self.assertRaises(SystemExit):
                select_profile(['--profile', name], {})
        with self.assertRaises(SystemExit):
            select_profile(['--profile', 'teste'], {'LUMESYNC_DATA_DIR': str(self.root/'profile')})
        with self.assertRaises(ValueError):
            data_directory(self.project, self.home_dir, {'LUMESYNC_PROFILE': '../teste'})
