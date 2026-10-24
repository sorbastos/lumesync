import json
from pathlib import Path
from .core import State, Engine, LocalProvider, DEFAULT_IGNORES
from .drive import DriveProvider, private_json

# Portable by default: runtime files stay beside the source, outside synced roots.
PROJECT = Path(__file__).resolve().parent.parent
DATA = PROJECT / "runtime"
CONFIG = DATA / "config.json"


def load():
    if CONFIG.exists():
        return json.loads(CONFIG.read_text())
    return {"mode": "demo", "local": str(PROJECT / "demo/local"), "remote": str(PROJECT / "demo/nuvem"),
            "root_id": "root", "interval": 60, "ignores": DEFAULT_IGNORES}


def save(config):
    private_json(CONFIG, config)


def build(config):
    if config.get('access_mode') == 'online':
        raise ValueError('O modo sob demanda não faz cópia integral. Use a interface para marcar itens offline.')
    local = Path(config["local"]).expanduser().absolute()
    if "Insync" in local.parts:
        raise ValueError("Escolha uma pasta separada da usada pelo Insync")
    if config["mode"] == "demo":
        remote = Path(config["remote"]).expanduser().absolute()
        if DATA.resolve().is_relative_to(remote.resolve()):
            raise ValueError("A pasta de nuvem de teste não pode conter os dados do app")
        provider = LocalProvider(remote)
        identity = "demo|" + str(local.resolve()) + "|" + str(remote.resolve())
    else:
        provider = DriveProvider(DATA / "google-token.json", config.get("root_id", "root"))
        provider.include_paths = config.get('include_paths')
        provider.inventory_enabled = provider.include_paths is None
        # OAuth client + remote root + local path identify this baseline.
        identity = "drive|" + str(local.resolve()) + "|" + provider.root_id + "|" + provider.token.get("refresh_token", "")
    import hashlib
    # No credentials are persisted in the baseline identity.
    key = hashlib.sha256(identity.encode()).hexdigest()
    state = State(DATA / "profiles" / key)
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
