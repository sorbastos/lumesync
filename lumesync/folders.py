"""Converte a escolha de pasta da interface em um identificador do Drive."""
import re
from urllib.parse import urlparse, parse_qs, unquote


def drive_folder(scope, value=''):
    if scope == 'all':
        return 'root'
    value = value.strip()
    if re.fullmatch(r'[A-Za-z0-9_-]{5,}', value):
        return value  # Compatibilidade com configurações anteriores.
    if value.startswith('drive.google.com/'):
        value = 'https://' + value
    url = urlparse(value)
    if url.scheme == 'https' and url.hostname == 'drive.google.com':
        match = re.search(r'/folders/([A-Za-z0-9_-]+)(?:/|$)', unquote(url.path))
        folder = match.group(1) if match else parse_qs(url.query).get('id', [''])[0]
        if re.fullmatch(r'[A-Za-z0-9_-]{5,}', folder):
            return folder
    raise ValueError('Abra a pasta no Google Drive e cole aqui o link completo da barra de endereço.')
