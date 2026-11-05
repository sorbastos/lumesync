"""Seleciona o perfil antes de carregar os módulos do aplicativo."""
from __future__ import annotations

import argparse
import os
import re
import sys


PROFILE_PATTERN = re.compile(r'[a-z0-9][a-z0-9-]{0,31}')


def select_profile(argv=None, environ=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    environ = os.environ if environ is None else environ
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--profile', metavar='NOME')
    options, remaining = parser.parse_known_args(argv)
    if options.profile:
        if not PROFILE_PATTERN.fullmatch(options.profile):
            parser.error('o perfil deve usar letras minúsculas, números e hífen (máximo de 32 caracteres)')
        if environ.get('LUMESYNC_DATA_DIR'):
            parser.error('--profile não pode ser combinado com LUMESYNC_DATA_DIR')
        environ['LUMESYNC_PROFILE'] = options.profile
    return remaining


def _launch(module, argv=None):
    remaining = select_profile(argv)
    sys.argv = [sys.argv[0], *remaining]
    if module == 'app':
        from .app import main
    elif module == 'cli':
        from .cli import main
    elif module == 'online':
        from .online import main
    else:
        raise ValueError('Destino de inicialização inválido')
    return main()


def gui_main():
    return _launch('app')


def cli_main():
    return _launch('cli')


def online_main():
    return _launch('online')


def main():
    parser = argparse.ArgumentParser(description='Inicializador do Lume Sync')
    parser.add_argument('target', choices=('app', 'cli', 'online'))
    options, remaining = parser.parse_known_args()
    return _launch(options.target, remaining)


if __name__ == '__main__':
    raise SystemExit(main())
