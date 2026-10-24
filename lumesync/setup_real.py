"""Configura uma pasta real e o favorito do Dolphin, executado pelo usuário."""
from __future__ import annotations
import argparse
import os
import shutil
import sys
import time
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

from .config import DATA, DEMO
from .core import DEFAULT_IGNORES
from .drive import DriveProvider, private_json, API, FOLDER

BOOKMARK_NS = 'http://www.freedesktop.org/standards/desktop-bookmarks'
ET.register_namespace('bookmark', BOOKMARK_NS)
ET.register_namespace('kdepriv', 'http://www.kde.org/kdepriv')
ET.register_namespace('mime', 'http://www.freedesktop.org/standards/shared-mime-info')


def add_place(places: Path, folder: Path):
    """Preserva favoritos e guarda backup antes de adicionar uma única entrada."""
    original = places.read_bytes() if places.exists() else None
    root = ET.fromstring(original) if original is not None else ET.Element('xbel')
    if root.tag != 'xbel':
        raise ValueError('Formato inesperado do arquivo de locais do Dolphin')
    href = folder.absolute().as_uri()
    if any(item.get('href') == href for item in root.findall('bookmark')):
        return
    bookmark = ET.SubElement(root, 'bookmark', href=href)
    ET.SubElement(bookmark, 'title').text = 'Google Drive · Lume Sync'
    info = ET.SubElement(bookmark, 'info')
    meta = ET.SubElement(info, 'metadata', owner='http://freedesktop.org')
    ET.SubElement(meta, '{'+BOOKMARK_NS+'}icon', name='folder-cloud')
    meta = ET.SubElement(info, 'metadata', owner='http://www.kde.org')
    ET.SubElement(meta, 'ID').text = 'lume-sync-'+uuid.uuid4().hex
    ET.SubElement(meta, 'isSystemItem').text = 'false'
    ET.SubElement(meta, 'isHidden').text = 'false'
    places.parent.mkdir(parents=True, exist_ok=True)
    if original is not None:
        backup = places.with_name(places.name+'.lume-backup-'+str(time.time_ns()))
        backup.write_bytes(original)
        os.chmod(backup, 0o600)
    # Refuse to clobber concurrent edits made by the file manager.
    if places.exists() and places.read_bytes() != original:
        raise RuntimeError('Os locais do Dolphin mudaram. Execute novamente.')
    temporary = places.with_name(places.name+'.lume-'+uuid.uuid4().hex+'.tmp')
    try:
        ET.indent(root, space=' ')
        temporary.write_bytes(b'<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xbel>\n'+ET.tostring(root, encoding='utf-8'))
        os.chmod(temporary, 0o600)
        os.replace(temporary, places)
    finally:
        temporary.unlink(missing_ok=True)


def prepare(home: Path, data: Path, root_id: str):
    folder = home/'Lume Sync'/'Google Drive'
    for candidate in (home/'Lume Sync', folder):
        if candidate.is_symlink():
            raise ValueError('A pasta de sincronização não pode ser um link simbólico')
    marker = folder/'.lume-managed'
    if folder.exists() and any(folder.iterdir()) and not marker.is_file():
        raise ValueError(f'A pasta {folder} já contém arquivos. Escolha outro nome antes de continuar.')
    folder.mkdir(parents=True, exist_ok=True)
    marker.write_text('Pasta de sincronização do Lume Sync.\n')
    config = {'mode':'drive','local':str(folder),'remote':str(DEMO/'nuvem'),
              'root_id':root_id,'interval':300,'ignores':DEFAULT_IGNORES}
    add_place(home/'.local/share/user-places.xbel', folder)
    current = data/'config.json'
    if current.exists():
        backup = data/('config-before-real-'+str(time.time_ns())+'.json')
        shutil.copyfile(current, backup)
        os.chmod(backup,0o600)
    private_json(current,config)
    return folder


def main():
    parser = argparse.ArgumentParser(description='Configurar Meu Drive em uma pasta do Dolphin')
    parser.add_argument('--launch',action='store_true',help='Abrir o app e ativar sincronização periódica')
    args=parser.parse_args()
    try:
        if not (DATA/'google-token.json').is_file():
            raise RuntimeError('Conecte sua conta Google nas configurações do Lume Sync antes de continuar.')
        provider=DriveProvider(DATA/'google-token.json')
        print('Verificando a autorização do Google Drive...',flush=True)
        resource=provider.request('GET',API+'/root',params={'fields':'id,mimeType'}).json()
        if resource.get('mimeType') != FOLDER:
            raise RuntimeError('Não foi possível identificar a raiz de Meu Drive')
        folder=prepare(Path.home(),DATA,resource['id'])
        print('Pasta preparada:',folder,flush=True)
        print('Local adicionado ao Dolphin. Feche e reabra o Dolphin se o favorito ainda não aparecer.',flush=True)
        print('A primeira análise pode demorar. Documentos nativos Google permanecem na nuvem nesta versão.',flush=True)
        if args.launch:
            # Replace this process, retaining output and the same Python environment.
            os.execv(sys.executable,[sys.executable,'-m','lumesync.app','--monitor'])
    except Exception as error:
        parser.exit(1,f'Não foi possível configurar: {error}\n')


if __name__ == '__main__':main()
