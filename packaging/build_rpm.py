"""Constrói um RPM local Fedora 44, sem sudo e sem dados do usuário."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(args, **kwargs):
    return subprocess.run([str(a) for a in args], check=True, **kwargs)


def capture(args):
    return run(args, capture_output=True, text=True).stdout.strip()


def runtime_packages(venv):
    """Relaciona as bibliotecas nativas externas a pacotes Fedora instalados."""
    owners = set()
    ownership_cache = {}
    checked = set()
    missing = []
    site = venv/'lib/python3.14/site-packages'
    qt = site/'PySide6/Qt'
    libraries = [site/'PySide6'/name for name in ('QtCore.abi3.so', 'QtGui.abi3.so', 'QtWidgets.abi3.so')]
    libraries += list((site/'shiboken6').glob('*.so*'))
    for directory, names in {
        'platforms': ['libqxcb.so', 'libqwayland.so', 'libqminimal.so', 'libqoffscreen.so'],
        'platforminputcontexts': ['libcomposeplatforminputcontextplugin.so', 'libibusplatforminputcontextplugin.so'],
        'platformthemes': ['libqxdgdesktopportal.so'],
        'iconengines': ['libqsvgicon.so'],
        'imageformats': ['libqgif.so', 'libqico.so', 'libqjpeg.so', 'libqsvg.so'],
    }.items():
        libraries.extend(qt/'plugins'/directory/name for name in names)
    for directory in ('xcbglintegrations', 'wayland-graphics-integration-client', 'wayland-decoration-client', 'wayland-shell-integration'):
        libraries.extend((qt/'plugins'/directory).glob('*.so'))
    for library in sorted(libraries):
        if not library.is_file() or library.resolve() in checked:
            continue
        checked.add(library.resolve())
        result = subprocess.run(['ldd', str(library)], capture_output=True, text=True)
        for line in result.stdout.splitlines():
            if '=> not found' in line:
                missing.append((library.name, line.strip()))
            match = re.search(r'(?:=>\s+)?(/\S+)\s+\(', line)
            if not match:
                continue
            path = Path(match.group(1)).resolve()
            if path.is_relative_to(venv.resolve()):
                continue
            if path not in ownership_cache:
                ownership_cache[path] = capture(['rpm', '-qf', '--qf', '%{NAME}\n', str(path)])
            owner = ownership_cache[path]
            owners.update(owner.splitlines())
    required = {'QtCore.abi3.so', 'QtGui.abi3.so', 'QtWidgets.abi3.so',
                'libQt6Core.so.6', 'libQt6Gui.so.6', 'libQt6Widgets.so.6', 'libqxcb.so', 'libqwayland.so'}
    failures = [entry for entry in missing if entry[0] in required]
    if failures:
        raise RuntimeError('Bibliotecas gráficas necessárias ausentes: ' + repr(failures))
    if any(name.startswith('qt6-') for name in owners):
        raise RuntimeError('Uma biblioteca Qt foi resolvida fora do ambiente privado.')
    return sorted(owners), missing


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'dist')
    args = parser.parse_args()
    if sys.prefix == sys.base_prefix:
        parser.error('Use bash packaging/build-rpm.sh dentro do projeto com .venv preparada.')
    release = platform.freedesktop_os_release()
    if (release.get('ID'), release.get('VERSION_ID'), platform.machine(), sys.version_info[:2]) != ('fedora', '44', 'x86_64', (3, 14)):
        parser.error('Este alvo requer Fedora 44 x86_64 e Python 3.14.')
    builder = os.environ.get('RPMBUILD') or shutil.which('rpmbuild')
    if not builder:
        parser.error('Instale rpm-build ou informe RPMBUILD=/caminho/para/rpmbuild.')
    version = tomllib.loads((ROOT/'pyproject.toml').read_text())['project']['version']
    output = args.output.expanduser().absolute(); output.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'QT_QPA_PLATFORM': 'offscreen'}
    with tempfile.TemporaryDirectory(prefix='lumesync-rpm-') as directory:
        work = Path(directory); wheels = work/'wheels'; wheels.mkdir()
        python = Path(sys.executable)
        pip = [python, '-I', '-m', 'pip', '--isolated', '--require-virtualenv']
        run([*pip, 'download', '--only-binary=:all:', '--no-deps', '-r', ROOT/'packaging/requirements-fedora44.txt', '--dest', wheels], env=env)
        run([*pip, 'wheel', '--no-deps', '--wheel-dir', wheels, ROOT], env=env)
        app_wheels = list(wheels.glob('lume_sync-*.whl'))
        if len(app_wheels) != 1:
            raise RuntimeError('Wheel do aplicativo não encontrado.')
        with zipfile.ZipFile(app_wheels[0]) as package:
            for name in package.namelist():
                parts = Path(name).parts
                module = len(parts) == 2 and parts[0] == 'lumesync' and name.endswith('.py')
                metadata = bool(parts and parts[0].startswith('lume_sync-') and parts[0].endswith('.dist-info'))
                if not (module or metadata) or '..' in parts or name.startswith('/'):
                    raise RuntimeError('Arquivo inesperado no wheel do aplicativo: ' + name)
        # A fresh venv is created; the development environment is never copied.
        payload = work/'payload'; venv = payload/'opt/lumesync/venv'
        run([python, '-I', '-m', 'venv', '--without-pip', venv], env=env)
        managed_pip = [python, '-I', '-m', 'pip', '--isolated', '--python', venv/'bin/python', '--require-virtualenv']
        run([*managed_pip, 'install', '--no-index', '--find-links', wheels, '--no-compile', 'lume-sync==' + version], env=env)
        run([*managed_pip, 'check'], env=env)
        run([venv/'bin/python', '-I', '-B', '-c',
             'import sys; from PySide6.QtWidgets import QApplication; import lumesync.app; '
             'assert sys.prefix != sys.base_prefix; app=QApplication([]); print("RPM: imports e Qt validados")'], env=env)
        packages, missing = runtime_packages(venv)
        for path in (venv/'bin').iterdir():
            if not path.name.startswith('python'):
                path.unlink()
        cfg = venv/'pyvenv.cfg'
        cfg.write_text('\n'.join(line for line in cfg.read_text().splitlines() if not line.startswith('command =')) + '\n')
        if list(venv.rglob('direct_url.json')):
            raise RuntimeError('Metadados locais inesperados no ambiente empacotado.')
        for command, module in [('lume-sync', 'lumesync.app'), ('lume-sync-cli', 'lumesync.cli'), ('lume-sync-conectar', 'lumesync.online')]:
            path = payload/'usr/bin'/command; path.parent.mkdir(parents=True, exist_ok=True)
            extra = ' setup --launch' if command == 'lume-sync-conectar' else ''
            path.write_text('#!/bin/sh\nset -eu\nunset PYTHONHOME PYTHONPATH QT_PLUGIN_PATH QT_QPA_PLATFORM_PLUGIN_PATH\n'
                            'exec /opt/lumesync/venv/bin/python -I -B -m ' + module + extra + ' "$@"\n')
            path.chmod(0o755)
        for name, destination in [('io.github.sorbastos.LumeSync.desktop', 'usr/share/applications'),
                                  ('io.github.sorbastos.LumeSync.svg', 'usr/share/icons/hicolor/scalable/apps')]:
            folder = payload/destination; folder.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT/'packaging'/name, folder/name)
        docs = payload/'usr/share/doc/lumesync'; docs.mkdir(parents=True)
        shutil.copyfile(ROOT/'README.md', docs/'README.md')
        shutil.copyfile(ROOT/'packaging/requirements-fedora44.txt', docs/'requirements-fedora44.txt')
        manifest = ''.join(hashlib.sha256(p.read_bytes()).hexdigest() + '  ' + p.name + '\n' for p in sorted(wheels.glob('*.whl')))
        (docs/'wheels.sha256').write_text(manifest)
        (docs/'NOTICE').write_text('O aplicativo ainda não tem licença de redistribuição definida.\n'
                                 'As dependências preservam suas licenças em opt/lumesync/venv/lib/python3.14/site-packages.\n')
        top = work/'rpmbuild'
        for name in ('SOURCES', 'SPECS', 'BUILD', 'BUILDROOT', 'RPMS', 'SRPMS'):
            (top/name).mkdir(parents=True)
        archive = top/'SOURCES/payload.tar.gz'
        with tarfile.open(archive, 'w:gz', dereference=False) as stream:
            for child in sorted(payload.iterdir()):
                stream.add(child, arcname=child.name)
        spec = (ROOT/'packaging/lumesync.spec.in').read_text()
        requires = sorted(set(packages) | {'rclone', 'fuse3', 'systemd', 'xdg-utils'})
        spec = spec.replace('@VERSION@', version).replace('@REQUIRES@', ', '.join(requires))
        specpath = top/'SPECS/lumesync.spec'; specpath.write_text(spec)
        build_command = [builder, '-bb', '--define', '_topdir ' + str(top),
                         '--define', '_tmppath ' + str(work), '--define', '_buildhost localhost',
                         '--define', '_binary_payload w6.zstdio']
        helper = Path(builder).absolute().parent.parent/'lib/rpm/check-files'
        if helper.is_file():
            build_command += ['--define', '__check_files ' + str(helper) + ' %{buildroot}']
        run([*build_command, specpath], env=env)
        built = list((top/'RPMS').rglob('*.rpm'))
        if len(built) != 1:
            raise RuntimeError('Quantidade inesperada de RPMs produzidos.')
        result = output/built[0].name; shutil.copyfile(built[0], result)
        (output/(result.name + '.sha256')).write_text(hashlib.sha256(result.read_bytes()).hexdigest() + '  ' + result.name + '\n')
        (output/'build-report.json').write_text(json.dumps({'package': result.name, 'python': platform.python_version(),
              'version': version, 'native_packages': requires, 'optional_missing_libraries': missing,
              'private_dependencies': True, 'user_data_included': False}, indent=2) + '\n')
        print('Pacote pronto:', result)


if __name__ == '__main__':
    main()
