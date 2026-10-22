import tempfile
import unittest
from pathlib import Path
from lumesync.drive import DriveProvider, private_json, FOLDER, credentials
from lumesync.core import Item, digest


class DriveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.token = self.root/'token.json'; private_json(self.token, {'access_token': 'fake', 'expires_at': 99999999999})
        self.provider = DriveProvider(self.token)

    def tearDown(self): self.temp.cleanup()

    def test_duplicate_names_get_distinct_stable_aliases(self):
        self.provider.children = lambda folder: iter([
            {'id': '1', 'name': 'same', 'mimeType': 'text/plain', 'md5Checksum': 'abc'},
            {'id': '2', 'name': 'same', 'mimeType': 'text/plain', 'md5Checksum': 'def'}])
        first = self.provider.scan([])
        self.assertEqual(len(first), 2)
        self.assertEqual({i.remote_id for i in first.values()}, {'1', '2'})
        self.assertEqual(first, self.provider.scan([]))

    def test_unsafe_cloud_name(self):
        self.provider.children = lambda folder: iter([{'id': '1', 'name': '../x', 'mimeType': 'text/plain', 'md5Checksum': 'abc'}])
        result = self.provider.scan([])
        self.assertEqual(len(result), 1)
        self.assertNotIn('/', next(iter(result)))
        self.assertTrue(self.provider.mapping_file.exists())

    def test_native_google_document_notice(self):
        self.provider.children = lambda folder: iter([{'id': '1', 'name': 'Notas', 'mimeType': 'application/vnd.google-apps.document'}])
        self.assertEqual(self.provider.scan([]), {})
        self.assertEqual(len(self.provider.notices), 1)

    def test_subfolder_and_ignore(self):
        resources = {'root': [{'id': 'folder', 'name': 'Projetos', 'mimeType': FOLDER}, {'id': 'env', 'name': '.venv', 'mimeType': FOLDER}],
                     'folder': [{'id': 'file', 'name': 'a.txt', 'mimeType': 'text/plain', 'size': '3', 'md5Checksum': 'abc', 'version': '7'}]}
        self.provider.children = lambda folder: iter(resources[folder])
        result = self.provider.scan(['.venv'])
        self.assertEqual(result['Projetos/a.txt'].version, '7')
        self.assertNotIn('.venv', self.provider.folders)


    def test_upload_rejects_changed_remote_version(self):
        class Response:
            headers = {}
            def json(self): return {'version': '2'}
        source = self.root/'source'; source.write_text('content')
        self.provider.request = lambda *args, **kwargs: Response()
        with self.assertRaises(RuntimeError):
            self.provider.upload(source, 'file', Item('file', 'old', 7, 'id', '1'))

    def test_new_upload_stream_and_checksum(self):
        source = self.root/'source'; source.write_text('content')
        calls = []
        class Response:
            headers = {'Location': 'https://www.googleapis.com/upload/session'}
            def json(self): return {'md5Checksum': digest(source)}
        def request(method, url, **kwargs):
            calls.append(method)
            if method == 'PUT': self.assertEqual(kwargs['data'].read(), b'content')
            return Response()
        self.provider.children = lambda folder: iter([])
        self.provider.request = request
        self.provider.upload(source, 'file', None)
        self.assertEqual(calls, ['POST', 'PUT'])

    def test_new_upload_refuses_existing_name(self):
        source = self.root/'source'; source.write_text('content')
        self.provider.children = lambda folder: iter([{'name': 'file'}])
        with self.assertRaises(RuntimeError): self.provider.upload(source, 'file', None)


    def test_empty_upload_does_not_send_chunked_encoding(self):
        import requests
        source = self.root/'empty'; source.write_bytes(b'')
        class Response:
            headers = {'Location': 'https://www.googleapis.com/upload/session'}
            def json(self): return {'md5Checksum': digest(source)}
        def request(method, url, **kwargs):
            if method == 'PUT':
                prepared = requests.Request(method, url, data=kwargs['data'], headers=kwargs['headers']).prepare()
                self.assertEqual(prepared.headers.get('Content-Length'), '0')
                self.assertNotIn('Transfer-Encoding', prepared.headers)
            return Response()
        self.provider.children = lambda folder: iter([])
        self.provider.request = request
        self.provider.upload(source, 'empty', None)


    def test_download_allows_metadata_version_change_with_identical_content(self):
        source = self.root/'source'; source.write_bytes(b'data')
        class Response:
            def json(self): return {'version': '2', 'md5Checksum': digest(source)}
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def iter_content(self, size): yield b'data'
        self.provider.request = lambda *args, **kwargs: Response()
        destination = self.root/'download'
        self.provider.download(Item('file', digest(source), 4, 'id', '1'), destination)
        self.assertEqual(destination.read_bytes(), b'data')

    def test_download_rejects_changed_content_before_writing(self):
        class Response:
            def json(self): return {'version': '2', 'md5Checksum': 'changed'}
        self.provider.request = lambda *args, **kwargs: Response()
        destination = self.root/'download'; destination.write_bytes(b'preserve')
        with self.assertRaises(RuntimeError):
            self.provider.download(Item('file', 'original', 4, 'id', '1'), destination)
        self.assertEqual(destination.read_bytes(), b'preserve')


    def test_upload_allows_metadata_only_version_change(self):
        source = self.root/'source'; source.write_bytes(b'new content')
        calls = []
        class Response:
            headers = {'Location': 'https://www.googleapis.com/upload/session'}
            def __init__(self, method): self.method = method
            def json(self):
                if self.method == 'GET': return {'version': '2', 'md5Checksum': 'old-content', 'name': 'file', 'parents': ['root']}
                return {'md5Checksum': digest(source)}
        def request(method, url, **kwargs):
            calls.append(method)
            return Response(method)
        self.provider.request = request
        self.provider.upload(source, 'file', Item('file', 'old-content', 3, 'id', '1'))
        self.assertEqual(calls, ['GET', 'PATCH', 'PUT'])


    def test_mapped_cloud_name_is_preserved_on_upload(self):
        source=self.root/'source';source.write_bytes(b'new')
        self.provider.original_names['id']='with/slash'
        class Response:
            headers={'Location':'https://www.googleapis.com/upload/session'}
            def __init__(self,method):self.method=method
            def json(self):
                if self.method=='GET':return {'md5Checksum':'old','name':'with/slash','parents':['root']}
                return {'md5Checksum':digest(source),'id':'id'}
        self.provider.request=lambda method,*args,**kwargs:Response(method)
        self.provider.upload(source,'with%2Fslash',Item('with%2Fslash','old',3,'id','1'))
        self.assertEqual(self.provider.name_map['id']['name'],'with/slash')
        self.assertEqual(self.provider.name_map['id']['local'],'with%2Fslash')

    def test_incomplete_inventory_aborts_before_transfers(self):
        self.provider.inventory_enabled=True
        class Response:
            def json(self):return {'incompleteSearch':True,'files':[]}
        self.provider.request=lambda *args,**kwargs:Response()
        self.provider.root_id='real-root'
        with self.assertRaises(RuntimeError):self.provider.scan([])

    def test_no_checksum_item_does_not_abort_other_files(self):
        self.provider.children=lambda folder:iter([
            {'id':'a','name':'unsupported','mimeType':'application/octet-stream'},
            {'id':'b','name':'normal','mimeType':'text/plain','md5Checksum':'abc'}])
        result=self.provider.scan([])
        self.assertEqual(list(result),['normal'])
        self.assertIn('unsupported',self.provider.blocked_paths)
        self.assertEqual(len(self.provider.warnings),1)

    def test_token_permissions(self): self.assertEqual(self.token.stat().st_mode & 0o777, 0o600)

    def test_requires_desktop_oauth(self):
        client = self.root/'client.json'; client.write_text('{"web":{"client_id":"x"}}')
        with self.assertRaises(ValueError): credentials(client)


if __name__ == '__main__': unittest.main()
