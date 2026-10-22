"""Google Drive v3 + OAuth instalado com PKCE e callback loopback."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlencode, urlparse, parse_qs, quote

import requests

from .core import Item, ignored, valid_path

API = "https://www.googleapis.com/drive/v3/files"
UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"
FOLDER = "application/vnd.google-apps.folder"
FIELDS = "id,name,mimeType,md5Checksum,size,version,parents"


def private_json(path: Path, value: dict):
    import tempfile
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(prefix='.lume-', suffix='.tmp', dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, 'w') as handle:
            json.dump(value, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def credentials(path: Path) -> dict:
    data = json.loads(path.read_text())
    client = data.get("installed")
    if not client or not client.get("client_id"):
        raise ValueError("Selecione um JSON OAuth do tipo Aplicativo para computador")
    # Endpoints are fixed rather than taken from a supplied JSON file.
    return {"client_id": client["client_id"], "client_secret": client.get("client_secret", "")}


def authorize(client_path: Path, token_path: Path, notify=lambda text: None):
    client = credentials(client_path)
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    result = {}
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            valid = parsed.path == "/callback" and secrets.compare_digest(query.get("state", [""])[0], state)
            if not valid:
                self.send_response(400); self.end_headers(); self.wfile.write(b"Callback invalido")
                return
            result.update({key: values[0] for key, values in query.items()})
            self.send_response(200); self.send_header("Content-Type", "text/plain; charset=utf-8"); self.end_headers()
            self.wfile.write("Autorização recebida. Volte ao Lume Sync.".encode())
        def log_message(self, *args):
            pass
    with HTTPServer(("127.0.0.1", 0), Handler) as server:
        server.timeout = 1
        redirect = f"http://127.0.0.1:{server.server_port}/callback"
        url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode({
            "client_id": client["client_id"], "redirect_uri": redirect, "response_type": "code",
            "scope": "https://www.googleapis.com/auth/drive", "access_type": "offline",
            "prompt": "consent", "state": state, "code_challenge": challenge, "code_challenge_method": "S256"})
        notify("Conclua a autorização no navegador (prazo: 3 minutos).")
        if not webbrowser.open(url):
            raise RuntimeError("Não foi possível abrir o navegador padrão")
        deadline = time.monotonic() + 180
        while not result and time.monotonic() < deadline:
            server.handle_request()
        if "code" not in result:
            raise RuntimeError("Autorização recusada ou prazo esgotado")
        response = requests.post("https://oauth2.googleapis.com/token", data={**client,
            "code": result["code"], "code_verifier": verifier, "grant_type": "authorization_code", "redirect_uri": redirect}, timeout=30)
        if response.status_code != 200:
            raise RuntimeError(f"Google recusou a troca OAuth (HTTP {response.status_code})")
        token = response.json()
        token.update(client)
        token["expires_at"] = time.time() + token.get("expires_in", 3600)
        private_json(token_path, token)


class DriveProvider:
    def __init__(self, token_path: Path, root_id="root"):
        if not root_id or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in root_id):
            raise ValueError("ID de pasta Google Drive inválido")
        self.token_path = token_path
        self.root_id = root_id
        self.token = json.loads(token_path.read_text())
        self.session = requests.Session()
        self.notices: list[str] = []
        self.folders = {"": root_id}
        self.folder_paths: set[str] = set()
        self.warnings = []
        self.blocked_paths = set()
        self.original_names = {}
        self.inventory_enabled = False
        self.include_paths = None
        self.cancelled = lambda: False
        self.progress = lambda message: None
        self.mapping_file = token_path.parent / ('drive-names-' + hashlib.sha256(root_id.encode()).hexdigest()[:16] + '.json')
        self.name_map = json.loads(self.mapping_file.read_text()) if self.mapping_file.exists() else {}

    def _access(self):
        if time.time() > self.token.get("expires_at", 0) - 90:
            response = requests.post("https://oauth2.googleapis.com/token", data={
                "client_id": self.token["client_id"], "client_secret": self.token.get("client_secret", ""),
                "refresh_token": self.token.get("refresh_token", ""), "grant_type": "refresh_token"}, timeout=30)
            if response.status_code != 200:
                raise RuntimeError("Sessão Google expirada; conecte novamente")
            self.token.update(response.json())
            self.token["expires_at"] = time.time() + self.token.get("expires_in", 3600)
            private_json(self.token_path, self.token)
        return self.token["access_token"]

    def request(self, method, url, **kwargs):
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = "Bearer " + self._access()
        # Retry reads only. Retrying writes without an idempotency key can duplicate files.
        attempts = 4 if method == "GET" else 1
        for attempt in range(attempts):
            response = self.session.request(method, url, headers=headers, timeout=(15, 120), **kwargs)
            if response.status_code not in (429, 500, 502, 503, 504) or attempt == attempts - 1:
                break
            response.close()
            time.sleep(2 ** attempt)
        if response.status_code >= 400:
            code = response.status_code
            response.close()
            raise RuntimeError(f"Google Drive HTTP {code}; nenhuma repetição automática de escrita")
        return response

    def children(self, folder):
        page = None
        while True:
            params = {"q": f"'{folder}' in parents and trashed = false", "fields": f"nextPageToken,files({FIELDS})",
                      "pageSize": 1000, "supportsAllDrives": "true", "includeItemsFromAllDrives": "true"}
            if page:
                params["pageToken"] = page
            data = self.request("GET", API, params=params).json()
            yield from data.get("files", [])
            page = data.get("nextPageToken")
            if not page:
                break

    def all_resources(self):
        """One paginated inventory, then traverse only the selected root locally."""
        from collections import defaultdict
        children = defaultdict(list)
        page = None
        count = 0
        while True:
            if self.cancelled():
                raise InterruptedError('Análise pausada')
            params = {'q': 'trashed = false', 'pageSize': 1000,
                      'fields': f'nextPageToken,incompleteSearch,files({FIELDS})',
                      'supportsAllDrives': 'true', 'includeItemsFromAllDrives': 'true'}
            if page:
                params['pageToken'] = page
            data = self.request('GET', API, params=params).json()
            if data.get('incompleteSearch'):
                raise RuntimeError('Google retornou uma listagem incompleta; nenhuma transferência iniciada')
            for resource in data.get('files', []):
                for parent in resource.get('parents', []):
                    children[parent].append(resource)
                count += 1
            self.progress(f'Analisando Drive: {count} itens inventariados')
            page = data.get('nextPageToken')
            if not page:
                return children

    def scan(self, patterns):
        from .names import allocate
        from .core import selected_path
        self.notices = []
        self.warnings = []
        self.blocked_paths = set()
        self.original_names = {}
        root_id = self.root_id
        if self.inventory_enabled and root_id == 'root':
            root_id = self.request('GET', API + '/root', params={'fields':'id'}).json()['id']
        self.folders = {'': root_id}
        self.folder_paths = set()
        inventory = self.all_resources() if self.inventory_enabled else None
        result = {}
        queue = [('', root_id)]
        visited = set()
        old_map = json.dumps(self.name_map, sort_keys=True)
        while queue:
            if self.cancelled():
                raise InterruptedError('Análise pausada')
            prefix, parent = queue.pop()
            if parent in visited:
                self.blocked_paths.add(prefix)
                self.warnings.append(f'Referência repetida ou circular preservada na nuvem: {prefix}')
                continue
            visited.add(parent)
            resources = list(inventory.get(parent, [])) if inventory is not None else list(self.children(parent))
            resources = [r for r in resources if not ignored((prefix + '/' if prefix else '') + r['name'], patterns, is_dir=r['mimeType'] == FOLDER)]
            aliases = allocate(resources, parent, self.name_map)
            for resource in resources:
                rid, name = resource['id'], resource['name']
                alias = aliases[rid]
                path = f'{prefix}/{alias}' if prefix else alias
                valid_path(path)
                if ignored(path, patterns, is_dir=resource['mimeType'] == FOLDER) or not selected_path(path, self.include_paths, is_dir=resource['mimeType'] == FOLDER):
                    continue
                self.original_names[rid] = name
                if alias != name:
                    self.notices.append(f'Nome local adaptado: {name!r} → {path}')
                mime = resource['mimeType']
                if mime == FOLDER:
                    self.folders[path] = rid
                    self.folder_paths.add(path)
                    queue.append((path, rid))
                elif mime.startswith('application/vnd.google-apps.'):
                    self.blocked_paths.add(path)
                    self.warnings.append(f'Documento nativo/atalho somente na nuvem: {path}')
                elif resource.get('md5Checksum'):
                    result[path] = Item(path, resource['md5Checksum'], int(resource.get('size', 0)), rid, str(resource.get('version', '')))
                else:
                    self.blocked_paths.add(path)
                    self.warnings.append(f'Arquivo sem checksum, preservado na nuvem: {path}')
        self.notices.extend(self.warnings)
        if json.dumps(self.name_map, sort_keys=True) != old_map:
            private_json(self.mapping_file, self.name_map)
        self.progress(f'Análise concluída: {len(result)} arquivos, {len(self.warnings)} avisos')
        return result

    def remember_name(self, resource_id, parent, original, local):
        if resource_id:
            self.name_map[resource_id] = {'parent': parent, 'name': original, 'local': local}
            self.original_names[resource_id] = original
            private_json(self.mapping_file, self.name_map)

    def download(self, item: Item, destination: Path):
        current = self.request("GET", API + "/" + item.remote_id, params={"fields": FIELDS, "supportsAllDrives": "true"}).json()
        if current.get("md5Checksum") != item.checksum:
            raise RuntimeError("Conteúdo remoto mudou; refaça a prévia")
        with self.request("GET", API + "/" + item.remote_id, params={"alt": "media", "supportsAllDrives": "true"}, stream=True) as response:
            with destination.open("wb") as handle:
                for chunk in response.iter_content(1024 * 1024):
                    handle.write(chunk)

    def ensure_folder(self, relative):
        if relative in self.folders:
            return self.folders[relative]
        parent, _, name = relative.rpartition("/")
        parent_id = self.ensure_folder(parent)
        matches = [r for r in self.children(parent_id) if r["name"] == name]
        if matches:
            if len(matches) != 1 or matches[0]["mimeType"] != FOLDER:
                raise RuntimeError(f"Colisão de nome: {relative}")
            self.folders[relative] = matches[0]["id"]
        else:
            result = self.request("POST", API, params={"fields": "id", "supportsAllDrives": "true"},
                                  json={"name": name, "mimeType": FOLDER, "parents": [parent_id]}).json()
            self.folders[relative] = result["id"]
            self.remember_name(result['id'], parent_id, name, name)
        return self.folders[relative]

    def upload(self, source: Path, relative: str, existing: Item | None):
        parent, _, name = relative.rpartition("/")
        parent_id = self.ensure_folder(parent)
        params = {"uploadType": "resumable", "fields": FIELDS, "supportsAllDrives": "true"}
        headers = {"X-Upload-Content-Type": "application/octet-stream", "X-Upload-Content-Length": str(source.stat().st_size)}
        if existing:
            response = self.request("GET", API + "/" + existing.remote_id, params={"fields": FIELDS, "supportsAllDrives": "true"})
            metadata = response.json()
            # Server-side metadata changes increment version without changing bytes.
            # Preserve checks on content, name and selected parent before overwriting.
            if (metadata.get("md5Checksum") != existing.checksum
                    or metadata.get("name") != self.original_names.get(existing.remote_id, name)
                    or parent_id != "root" and parent_id not in metadata.get("parents", [])):
                raise RuntimeError("Arquivo remoto mudou antes do upload")
            if response.headers.get("ETag"):
                headers["If-Match"] = response.headers["ETag"]
            response = self.request("PATCH", UPLOAD + "/" + existing.remote_id, params=params, json={}, headers=headers)
        else:
            if any(r["name"] == name for r in self.children(parent_id)):
                raise RuntimeError("Um item remoto apareceu com o mesmo nome; refaça a prévia")
            response = self.request("POST", UPLOAD, params=params, json={"name": name, "parents": [parent_id]}, headers=headers)
        location = response.headers.get("Location", "")
        parsed = urlparse(location)
        if parsed.scheme != "https" or parsed.hostname != "www.googleapis.com":
            raise RuntimeError("Endpoint de upload inesperado")
        from .core import digest
        checksum = digest(source)
        # Stream the body from disk; a failed transfer is surfaced for a new preview.
        with source.open("rb") as handle:
            response = self.request("PUT", location, data=handle if source.stat().st_size else b"", headers={"Content-Length": str(source.stat().st_size), "Content-Type": "application/octet-stream"})
        result = response.json()
        if result.get('md5Checksum') != checksum:
            raise RuntimeError('Não foi possível confirmar a integridade do upload')
        self.remember_name(result.get('id'), parent_id, self.original_names.get(existing.remote_id, name) if existing else name, name)
