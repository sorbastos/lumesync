import json
import os
import re
import shutil
import time
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


def kept_files_directory(data=None):
    """Armazenamento privado das cópias que o usuário decidiu manter."""
    return Path(DATA if data is None else data) / 'kept-files'


def _drive_state_key(local, root_id, client_id):
    import hashlib
    identity = 'drive-v2|' + str(Path(local).resolve()) + '|' + root_id + '|' + client_id
    return hashlib.sha256(identity.encode()).hexdigest(), identity


def _copy_state_for_moved_storage(data, old_local, new_local, root_id):
    """Preserva a linha de base; a origem fica intacta para recuperação."""
    import sqlite3
    from .core import exclusive
    token_path = Path(data) / 'google-token.json'
    if not token_path.is_file():
        return
    token = json.loads(token_path.read_text())
    old_key, _ = _drive_state_key(old_local, root_id, token.get('client_id', ''))
    new_key, _ = _drive_state_key(new_local, root_id, token.get('client_id', ''))
    source = Path(data) / 'profiles' / old_key
    target = Path(data) / 'profiles' / new_key
    if not (source / 'state.sqlite3').is_file() or (target / 'state.sqlite3').exists():
        return
    with exclusive(source), exclusive(target):
        if (target / 'state.sqlite3').exists():
            return
        origin = sqlite3.connect(source / 'state.sqlite3')
        temporary = target / 'migration.sqlite3'
        destination = sqlite3.connect(temporary)
        try:
            origin.backup(destination)
            destination.execute("update metadata set value=? where key='identity'", (new_key,))
            destination.commit()
        finally:
            destination.close()
            origin.close()
        temporary.chmod(0o600)
        os.replace(temporary, target / 'state.sqlite3')


def migrate_offline_storage(config, data=None):
    """Move somente a antiga pasta padrão para o armazenamento privado."""
    data = Path(DATA if data is None else data)
    if config.get('mode') != 'drive' or config.get('access_mode') != 'online':
        return config
    desired = kept_files_directory(data)
    current = Path(config.get('offline_local', desired)).expanduser().absolute()
    if current == desired.absolute():
        return config
    local = Path(config.get('local', '')).expanduser().absolute()
    legacy = local.parent / 'Offline'
    if current != legacy:
        raise RuntimeError('A pasta antiga de arquivos offline foi personalizada. Mova seu conteúdo para a área privada antes de atualizar.')
    if current.is_symlink() or desired.is_symlink():
        raise RuntimeError('A pasta de arquivos mantidos não pode ser um link simbólico.')
    if desired.exists() and any(desired.iterdir()):
        raise RuntimeError('A área privada já contém arquivos. As duas pastas foram preservadas para revisão.')

    _copy_state_for_moved_storage(data, current, desired, config.get('root_id', 'root'))
    data.mkdir(parents=True, exist_ok=True, mode=0o700)
    if desired.exists():
        desired.rmdir()
    moved = False
    try:
        if current.exists():
            if not current.is_dir():
                raise RuntimeError('O caminho antigo de arquivos offline não é uma pasta.')
            os.replace(current, desired)
            moved = True
        else:
            desired.mkdir(mode=0o700)
        desired.chmod(0o700)
        updated = {**config, 'offline_local': str(desired)}
        current_config = data / 'config.json'
        if current_config.is_file():
            backup = data / ('config-before-kept-files-' + str(time.time_ns()) + '.json')
            shutil.copyfile(current_config, backup)
            backup.chmod(0o600)
        private_json(current_config, updated)
        try:
            from .setup_real import remove_place
            remove_place(Path.home()/'.local/share/user-places.xbel', current)
        except Exception:
            # A cópia já está segura e a configuração já foi atualizada.
            # Um favorito antigo pode ser removido manualmente no Dolphin.
            pass
        return updated
    except Exception:
        if moved and desired.exists() and not current.exists():
            os.replace(desired, current)
        raise


def load():
    if CONFIG.exists():
        try:
            value = json.loads(CONFIG.read_text())
            if not isinstance(value, dict) or value.get('mode') not in ('demo', 'drive') or not value.get('local'):
                raise ValueError('Configuração incompleta')
            value.setdefault('ignores', DEFAULT_IGNORES)
            return migrate_offline_storage(value)
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
        key, identity = _drive_state_key(local, provider.root_id, provider.token.get('client_id', ''))
    if config["mode"] == "demo":
        import hashlib
        key = hashlib.sha256(identity.encode()).hexdigest()
    if config['mode'] == 'drive':
        migrate_legacy_state(data, local, provider.root_id, provider.token, key)
    state = State(data / "profiles" / key)
    try:
        state.bind(key)
        patterns = config.get('ignores', DEFAULT_IGNORES)
        if config.get('ignore_file'):
            from .ignore import IgnoreRules, SENSITIVE_RULES
            lines = Path(config['ignore_file']).read_text(encoding='utf-8').splitlines()
            patterns = IgnoreRules([*lines, *SENSITIVE_RULES])
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
