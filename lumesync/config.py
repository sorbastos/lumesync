import json
import os
import re
from pathlib import Path
from .core import State, Engine, LocalProvider, DEFAULT_IGNORES
from .drive import DriveProvider, private_json

PROJECT = Path(__file__).resolve().parent.parent
SOURCE_CHECKOUT = (PROJECT / 'pyproject.toml').is_file()


def profile_name(environ=None):
    environ = os.environ if environ is None else environ
    value = environ.get('LUMESYNC_PROFILE', '')
    if value and not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,31}', value):
        raise ValueError('LUMESYNC_PROFILE contém um nome de perfil inválido.')
    return value


def data_directory(project=PROJECT, home=None, environ=None):
    home = Path.home() if home is None else Path(home)
    environ = os.environ if environ is None else environ
    override = environ.get('LUMESYNC_DATA_DIR')
    if override:
        path = Path(override).expanduser()
        if not path.is_absolute():
            raise ValueError('LUMESYNC_DATA_DIR precisa ser um caminho absoluto.')
        return path
    profile = profile_name(environ)
    if profile:
        base = Path(environ.get('XDG_DATA_HOME') or home / '.local/share')
        if not base.is_absolute():
            base = home / '.local/share'
        return base / 'lumesync' / 'named-profiles' / profile
    if (project / 'pyproject.toml').is_file():
        return project / 'runtime'
    base = Path(environ.get('XDG_DATA_HOME') or home / '.local/share')
    if not base.is_absolute():
        base = home / '.local/share'
    return base / 'lumesync'


DATA = data_directory()
CONFIG = DATA / 'config.json'
PROFILE_NAME = profile_name()
DEMO = PROJECT / 'demo' if SOURCE_CHECKOUT and not PROFILE_NAME else DATA / 'demo'
DEFAULT_IGNORE = PROJECT / '.lumeignore' if SOURCE_CHECKOUT else DATA / '.lumeignore'


def load():
    if CONFIG.exists():
        try:
            value = json.loads(CONFIG.read_text())
            if not isinstance(value, dict) or value.get('mode') not in ('demo', 'drive') or not value.get('local'):
                raise ValueError('Configuração incompleta')
            value.setdefault('ignores', DEFAULT_IGNORES)
            return value
        except (ValueError, OSError) as error:
            raise RuntimeError('Não foi possível ler a configuração. O arquivo foi preservado. Restaure um backup pela opção de recuperação.') from error
    return {"mode": "demo", "local": str(DEMO / "local"), "remote": str(DEMO / "nuvem"),
            "root_id": "root", "interval": 60, "ignores": DEFAULT_IGNORES}


def save(config):
    if CONFIG.exists():
        try:
            previous = json.loads(CONFIG.read_text())
            if isinstance(previous, dict) and previous.get('mode') in ('demo','drive') and previous.get('local'):
                private_json(DATA/'config-last-good.json', previous)
        except (ValueError, OSError):
            pass
    private_json(CONFIG, config)


def build(config, data=None):
    data = DATA if data is None else Path(data)
    if config.get('access_mode') == 'online':
        raise ValueError('O modo sob demanda não faz cópia integral. Use a interface para marcar itens offline.')
    local = Path(config["local"]).expanduser().absolute()
    if "Insync" in local.parts:
        raise ValueError("Escolha uma pasta separada da usada pelo Insync")
    if config["mode"] == "demo":
        remote = Path(config["remote"]).expanduser().absolute()
        if data.resolve().is_relative_to(remote.resolve()):
            raise ValueError("A pasta de nuvem de teste não pode conter os dados do app")
        provider = LocalProvider(remote)
        identity = "demo|" + str(local.resolve()) + "|" + str(remote.resolve())
    else:
        provider = DriveProvider(data / "google-token.json", config.get("root_id", "root"))
        provider.include_paths = config.get('include_paths')
        provider.inventory_enabled = provider.include_paths is None
        # Account root is stable across explicit OAuth reauthorization. Never use a credential as identity.
        identity = "drive-v2|" + str(local.resolve()) + "|" + provider.root_id + "|" + provider.token.get('client_id', '')
    import hashlib
    # No credentials are persisted in the baseline identity.
    key = hashlib.sha256(identity.encode()).hexdigest()
    if config['mode'] == 'drive':
        migrate_legacy_state(data, local, provider.root_id, provider.token, key)
    state = State(data / "profiles" / key)
    try:
        state.bind(key)
        patterns = config.get('ignores', DEFAULT_IGNORES)
        if config.get('ignore_file'):
            from .ignore import IgnoreRules
            patterns = IgnoreRules.from_file(Path(config['ignore_file']))
        if config.get('offline_excludes'):
            from .ignore import OfflineExclusions
            patterns = OfflineExclusions(patterns, config['offline_excludes'])
        engine = Engine(local, provider, state, patterns)
    except Exception:
        state.close()
        raise
    return engine


def migrate_legacy_state(data, local, root_id, token, key):
    """Copy only a positively identified legacy DB; preserve the original for rollback."""
    import hashlib
    import sqlite3
    from .core import exclusive
    old_identity = 'drive|' + str(local.resolve()) + '|' + root_id + '|' + token.get('refresh_token', '')
    old_key = hashlib.sha256(old_identity.encode()).hexdigest()
    source = data/'profiles'/old_key
    target = data/'profiles'/key
    if not (source/'state.sqlite3').is_file() or (target/'state.sqlite3').exists():
        return
    with exclusive(source):
        with exclusive(target):
            if (target/'state.sqlite3').exists():
                return
            origin = sqlite3.connect(source/'state.sqlite3')
            temporary = target/'migration.sqlite3'
            destination = sqlite3.connect(temporary)
            try:
                origin.backup(destination)
                destination.execute("update metadata set value=? where key='identity'", (key,))
                destination.commit()
            finally:
                destination.close()
                origin.close()
            temporary.chmod(0o600)
            os.replace(temporary, target/'state.sqlite3')


def restore_backup(path):
    import time
    candidate = Path(path)
    value = json.loads(candidate.read_text())
    if not isinstance(value, dict) or value.get('mode') not in ('demo','drive') or not value.get('local'):
        raise ValueError('Backup inválido. A configuração atual foi preservada.')
    value.setdefault('ignores', DEFAULT_IGNORES)
    if CONFIG.exists():
        backup = DATA/('config-damaged-'+str(time.time_ns())+'.json')
        backup.write_bytes(CONFIG.read_bytes())
        backup.chmod(0o600)
    save(value)
    return value
