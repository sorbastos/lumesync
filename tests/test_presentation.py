import unittest
from lumesync.core import Action, Item
from lumesync.presentation import error_help, offline_state, pin_for_entry


class PresentationTests(unittest.TestCase):
    def action(self, kind, path='pasta/a.txt'):
        item = Item(path, 'hash', 1)
        return Action(path, kind, 'teste', item, item)

    def test_unknown_pin_is_not_reported_as_downloaded(self):
        self.assertIn('aguardando análise', offline_state('pasta', [], {}))

    def test_folder_pending_upload_wins_over_equal_files(self):
        actions = [self.action('equal'), self.action('upload', 'pasta/b.txt')]
        self.assertEqual(offline_state('pasta', actions, {}), 'Aguardando envio')

    def test_active_download_and_errors_are_visible(self):
        action = self.action('download')
        self.assertEqual(offline_state('pasta', [action], {}, {'path': action.path, 'kind': 'download'}), 'Baixando…')
        self.assertIn('Erro', offline_state('pasta', [action], {action.path: 'timeout'}))

    def test_similar_prefix_is_not_a_child(self):
        self.assertIn('aguardando análise', offline_state('pasta', [self.action('equal', 'pasta2/a')], {}))

    def test_child_of_pinned_folder_uses_alias_path(self):
        pins = [{'remote_id': 'folder', 'path': 'Cursos~id', 'label': 'Cursos'}]
        result = pin_for_entry({'Name': 'a.txt', 'ID': 'file'}, 'Cursos', pins)
        self.assertEqual(result['path'], 'Cursos~id/a.txt')
        self.assertIsNone(pin_for_entry({'Name': 'a.txt', 'ID': 'file'}, 'Cursos2', pins))

    def test_error_guidance(self):
        for text, expected in [('Connection timed out', 'conexão'), ('No space left on device', 'espaço'),
                               ('HTTP 401 invalid_grant', 'autorização'), ('HTTP 403', 'permitido'),
                               ('HTTP 429', 'temporário'), ('Prévia desatualizada', 'mudou')]:
            with self.subTest(text=text):
                self.assertIn(expected, error_help(text)[0])
                self.assertTrue(error_help(text)[1])
