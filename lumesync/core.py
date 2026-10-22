from __future__ import annotations

import contextlib
import fnmatch
import hashlib
import json
import os
import sqlite3
import tempfile
import time
from dataclasses import dataclass, asdict
from pathlib import Path, PurePosixPath
from typing import Protocol

DEFAULT_IGNORES = [".venv", "venv", "ambiente", "__pycache__", "*.pyc", ".git", "node_modules", ".Trash-*", ".lume-*", "*.insyncdl"]


def digest(path: Path) -> str:
    h = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def valid_path(relative: str) -> None:
    p = PurePosixPath(relative)
    if not relative or p.is_absolute() or any(x in ("", ".", "..") for x in relative.split("/")) or "\\" in relative or "\x00" in relative:
        raise ValueError(f"Caminho inseguro: {relative!r}")


def safe_path(root: Path, relative: str) -> Path:
    valid_path(relative)
    if root.is_symlink():
        raise ValueError("A pasta raiz não pode ser um link simbólico")
    root = root.absolute()
    target = root.joinpath(*PurePosixPath(relative).parts)
    current = root
    for part in PurePosixPath(relative).parts:
        current /= part
        if current.is_symlink():
            raise ValueError(f"Link simbólico bloqueado: {relative}")
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError("Caminho fora da pasta")
    return target


def ignored(relative: str, patterns: list[str], is_dir=False) -> bool:
    if hasattr(patterns, 'matches'):
        return patterns.matches(relative, is_dir)
    return any(fnmatch.fnmatchcase(part, pattern) or fnmatch.fnmatchcase(relative, pattern)
               for pattern in patterns for part in PurePosixPath(relative).parts)


@dataclass(frozen=True)
class Item:
    path: str
    checksum: str
    size: int
    remote_id: str = ""
    version: str = ""


@dataclass(frozen=True)
class Action:
    path: str
    kind: str
    reason: str
    local: Item | None
    remote: Item | None


class Provider(Protocol):
    notices: list[str]
    def scan(self, patterns: list[str]) -> dict[str, Item]: ...
    def download(self, item: Item, destination: Path) -> None: ...
    def upload(self, source: Path, relative: str, existing: Item | None) -> None: ...


class LocalProvider:
    """Backend de demonstração: outra pasta representa a nuvem."""
    def __init__(self, root: Path):
        self.root = root.absolute()
        self.notices: list[str] = []
        self.root.mkdir(parents=True, exist_ok=True)

    def scan(self, patterns: list[str]) -> dict[str, Item]:
        return scan_local(self.root, patterns)

    def download(self, item: Item, destination: Path) -> None:
        source = safe_path(self.root, item.path)
        if digest(source) != item.checksum:
            raise RuntimeError("A origem mudou durante a transferência; refaça a prévia")
        with source.open("rb") as src, destination.open("wb") as dst:
            while chunk := src.read(1024 * 1024):
                dst.write(chunk)

    def upload(self, source: Path, relative: str, existing: Item | None) -> None:
        target = safe_path(self.root, relative)
        if existing:
            if not target.is_file() or digest(target) != existing.checksum:
                raise RuntimeError("A nuvem mudou; refaça a prévia")
        elif target.exists():
            raise RuntimeError("Um arquivo apareceu na nuvem; refaça a prévia")
        atomic_download(target, digest(source), lambda temp: self._copy(source, temp))

    @staticmethod
    def _copy(source: Path, destination: Path) -> None:
        with source.open("rb") as src, destination.open("wb") as dst:
            while chunk := src.read(1024 * 1024):
                dst.write(chunk)


def selected_path(path, includes, is_dir=False):
    if includes is None:
        return True
    return any(path == chosen or path.startswith(chosen + '/') or
               is_dir and chosen.startswith(path + '/') for chosen in includes)


def scan_local(root: Path, patterns: list[str], includes=None) -> dict[str, Item]:
    if root.is_symlink():
        raise ValueError("Raiz com link simbólico não permitida")
    result: dict[str, Item] = {}
    def onerror(error):
        raise error
    for parent, dirs, files in os.walk(root, followlinks=False, onerror=onerror):
        base = Path(parent)
        dirs[:] = sorted(d for d in dirs if not (base / d).is_symlink() and not ignored((base / d).relative_to(root).as_posix(), patterns, is_dir=True) and selected_path((base / d).relative_to(root).as_posix(), includes, is_dir=True))
        for name in sorted(files):
            path = base / name
            rel = path.relative_to(root).as_posix()
            if path.is_symlink() or ignored(rel, patterns) or not selected_path(rel, includes):
                continue
            valid_path(rel)
            if not path.is_file():
                continue
            before = path.stat()
            checksum = digest(path)
            after = path.stat()
            if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
                raise RuntimeError(f"Arquivo em uso durante leitura: {rel}")
            result[rel] = Item(rel, checksum, after.st_size)
    return result


def atomic_download(target: Path, checksum: str, fetch, before_replace=None) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".lume-", dir=target.parent)
    os.close(fd)
    temp = Path(name)
    try:
        fetch(temp)
        if digest(temp) != checksum:
            raise RuntimeError("Checksum divergente; destino preservado")
        if before_replace:
            before_replace()
        with temp.open("rb") as f:
            os.fsync(f.fileno())
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)


class State:
    def __init__(self, directory: Path):
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.directory = directory
        self.db = sqlite3.connect(directory / "state.sqlite3")
        self.db.execute("create table if not exists baseline(path text primary key, checksum text not null)")
        self.db.execute("create table if not exists events(id integer primary key, timestamp real, path text, kind text, message text)")
        self.db.execute("create table if not exists metadata(key text primary key, value text)")
        self.db.commit()
        os.chmod(directory / "state.sqlite3", 0o600)

    def bind(self, identity: str):
        row = self.db.execute("select value from metadata where key='identity'").fetchone()
        if row and row[0] != identity:
            raise RuntimeError("Este estado pertence a outras pastas/conta. Use um diretório de dados novo.")
        self.db.execute("insert or replace into metadata values('identity',?)", (identity,))
        self.db.commit()

    def baseline(self) -> dict[str, str]:
        return dict(self.db.execute("select path,checksum from baseline"))

    def record(self, path: str, checksum: str):
        self.db.execute("insert or replace into baseline values(?,?)", (path, checksum))
        self.db.commit()

    def log(self, path: str, kind: str, message: str):
        self.db.execute("insert into events(timestamp,path,kind,message) values(?,?,?,?)", (time.time(), path, kind, message))
        self.db.commit()

    def close(self):
        self.db.close()


@contextlib.contextmanager
def exclusive(directory: Path):
    import fcntl
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "sync.lock").open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Outra sincronização está em execução") from None
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


class Engine:
    def __init__(self, local: Path, provider: Provider, state: State, patterns=None):
        self.local = local.absolute()
        if self.local.is_symlink():
            raise ValueError("A raiz não pode ser um link simbólico")
        self.local.mkdir(parents=True, exist_ok=True)
        self.provider, self.state = provider, state
        self.include_paths = getattr(provider, 'include_paths', None)
        self.patterns = DEFAULT_IGNORES if patterns is None else patterns
        if isinstance(provider, LocalProvider):
            a, b = self.local.resolve(), provider.root.resolve()
            if a.is_relative_to(b) or b.is_relative_to(a):
                raise ValueError("As pastas de demonstração devem ser separadas e não podem conter uma à outra")
        if state.directory.resolve().is_relative_to(self.local.resolve()):
            raise ValueError("Os dados do app devem ficar fora da pasta sincronizada")

    def plan(self) -> list[Action]:
        local = scan_local(self.local, self.patterns, self.include_paths)
        remote = self.provider.scan(self.patterns)
        baseline = self.state.baseline()
        actions = []
        # Detect file-versus-directory collisions before scheduling child transfers.
        collision_roots = set()
        for path in local:
            if any(parent.as_posix() in remote for parent in PurePosixPath(path).parents if parent.as_posix() != '.'):
                collision_roots.add(path)
                collision_roots.update(parent.as_posix() for parent in PurePosixPath(path).parents if parent.as_posix() in remote)
        for path in remote:
            if any(parent.as_posix() in local for parent in PurePosixPath(path).parents if parent.as_posix() != '.'):
                collision_roots.add(path)
                collision_roots.update(parent.as_posix() for parent in PurePosixPath(path).parents if parent.as_posix() in local)
        collision_roots.update(set(local) & getattr(self.provider, "folder_paths", set()))
        if isinstance(self.provider, LocalProvider):
            collision_roots.update(path for path in local if safe_path(self.provider.root, path).is_dir())
        for path in sorted(local.keys() | remote.keys() | baseline.keys()):
            if ignored(path, self.patterns) or not selected_path(path, self.include_paths):
                continue
            l, r, old = local.get(path), remote.get(path), baseline.get(path)
            if any(path == blocked or path.startswith(blocked + '/') for blocked in getattr(self.provider, 'blocked_paths', set())):
                kind, reason = 'blocked', 'Item remoto não sincronizável; veja Pendências'
            elif path in collision_roots or (l and safe_path(self.local, path).is_dir()):
                kind, reason = "blocked", "Colisão entre arquivo e pasta"
            elif r and safe_path(self.local, path).exists() and safe_path(self.local, path).is_dir():
                kind, reason = "blocked", "Colisão entre arquivo e pasta"
            elif l and r:
                if l.checksum == r.checksum:
                    kind, reason = "equal", "Conteúdo igual"
                elif old and r.checksum == old:
                    kind, reason = "upload", "Alteração local"
                elif old and l.checksum == old:
                    kind, reason = "download", "Alteração na nuvem"
                else:
                    kind, reason = "conflict", "Os dois lados têm conteúdo diferente"
            elif l:
                kind, reason = ("deletion", "Ausência na nuvem; decisão necessária") if old else ("upload", "Novo arquivo local")
            elif r:
                kind, reason = ("deletion", "Ausência local; decisão necessária") if old else ("download", "Novo arquivo na nuvem")
            else:
                continue
            actions.append(Action(path, kind, reason, l, r))
        return actions

    def apply(self, actions: list[Action], resolutions=None, notify=None, cancelled=None, continue_on_error=False):
        self.errors = []
        resolutions = resolutions or {}
        notify = notify or (lambda message: None)
        cancelled = cancelled or (lambda: False)
        with exclusive(self.state.directory):
            fresh = {a.path: a for a in self.plan()}
            import shutil
            required = sum(max(0, (a.remote.size if a.remote else 0) - (a.local.size if a.local else 0))
                           for a in actions if a.kind == 'download' or resolutions.get(a.path) == 'remote')
            if required and required + 256 * 1024 * 1024 > shutil.disk_usage(self.local).free:
                raise RuntimeError(f'Espaço insuficiente para as cópias selecionadas ({required / 1024**3:.2f} GiB adicionais). Selecione menos itens offline.')
            for action in actions:
                if cancelled():
                    notify("Pausado entre transferências")
                    break
                current = fresh.get(action.path)
                def signature(candidate):
                    if candidate is None:
                        return None
                    def content(item):
                        return (item.path, item.checksum, item.size, item.remote_id) if item else None
                    return (candidate.path, candidate.kind, content(candidate.local), content(candidate.remote))
                # Drive version also changes for metadata-only server updates.
                if signature(current) != signature(action):
                    message = f'Prévia desatualizada: {action.path}. Analise novamente.'
                    if not continue_on_error:
                        raise RuntimeError(message)
                    self.errors.append({'path':action.path, 'message':message})
                    self.state.log(action.path, 'error', message)
                    notify(message)
                    continue
                kind = action.kind
                if kind == "equal":
                    self.state.record(action.path, action.local.checksum)
                    continue
                if kind in ("conflict", "deletion"):
                    choice = resolutions.get(action.path)
                    if choice not in ("local", "remote"):
                        continue
                    # A missing side is never interpreted as permission to erase.
                    if choice == "local" and not action.local or choice == "remote" and not action.remote:
                        continue
                    kind = "upload" if choice == "local" else "download"
                if kind not in ("upload", "download"):
                    continue
                try:
                    target = safe_path(self.local, action.path)
                    def check_local():
                        safe_path(self.local, action.path)
                        if action.local:
                            if not target.is_file() or digest(target) != action.local.checksum:
                                raise RuntimeError("Arquivo local mudou; destino preservado")
                        elif target.exists():
                            raise RuntimeError("Um arquivo local apareceu; destino preservado")
                    check_local()
                    if kind == "upload":
                        # Snapshot prevents an editor changing content during upload.
                        with tempfile.TemporaryDirectory(prefix="upload-", dir=self.state.directory) as directory:
                            snapshot = Path(directory) / "content"
                            LocalProvider._copy(target, snapshot)
                            if digest(snapshot) != action.local.checksum:
                                raise RuntimeError("Origem mudou antes do upload")
                            self.provider.upload(snapshot, action.path, action.remote)
                        checksum = action.local.checksum
                    else:
                        atomic_download(target, action.remote.checksum,
                                        lambda temp: self.provider.download(action.remote, temp), check_local)
                        checksum = action.remote.checksum
                    self.state.record(action.path, checksum)
                    self.state.log(action.path, kind, "Concluído")
                    notify(f"{'Enviado' if kind == 'upload' else 'Recebido'}: {action.path}")
                except Exception as error:
                    self.state.log(action.path, "error", str(error))
                    notify(f"Erro em {action.path}: {error}")
                    self.errors.append({'path':action.path, 'message':str(error)})
                    if not continue_on_error:
                        raise
