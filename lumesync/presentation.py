"""Textos e estados da interface, sem acesso à rede ou aos arquivos do usuário."""
from __future__ import annotations

STATES = {"equal": "Disponível offline · em dia", "upload": "Aguardando envio",
          "download": "Aguardando download", "conflict": "Conflito · escolha uma versão",
          "deletion": "Arquivo ausente · escolha uma versão", "blocked": "Bloqueado"}


def error_help(message):
    text = message.casefold()
    if 'conta do google drive não conectada' in text or ('google-token.json' in text and ('no such file' in text or 'inexistente' in text)):
        return 'Conecte sua conta do Google Drive', 'Abra Configurações e clique em Conectar Google Drive.'
    if 'a cópia ainda não está igual' in text:
        return 'A cópia offline tem pendências', 'Sincronize o arquivo ou resolva o conflito antes de liberar espaço.'
    if any(word in text for word in ('espaço', 'no space left', 'disk full')):
        return 'Sem espaço no computador', 'Libere espaço ou selecione menos itens offline e tente novamente.'
    if any(word in text for word in ('401', 'invalid_grant', 'unauthorized', 'token expir', 'revoked')):
        return 'A conta precisa de autorização', 'Conecte sua conta novamente em Configurações.'
    if any(word in text for word in ('403', 'permission denied', 'permissão', 'forbidden')):
        return 'Acesso não permitido', 'Confira sua permissão no Drive e na pasta local antes de tentar novamente.'
    if any(word in text for word in ('429', 'rate limit', 'quota exceeded')):
        return 'Limite temporário do Google Drive', 'Aguarde alguns minutos e tente novamente.'
    if any(word in text for word in ('timeout', 'timed out', 'connection', 'network', 'resolve host', 'conexão')):
        return 'Falha de conexão', 'Confira a internet e tente novamente.'
    if any(word in text for word in ('mudou', 'desatualizada')):
        return 'O arquivo mudou durante a operação', 'Tente novamente para analisar a versão atual. Conflitos exigem sua escolha.'
    return 'Não foi possível concluir', 'Confira o detalhe abaixo, corrija a causa e tente novamente.'


def pin_for_entry(entry, relative, pins, excludes=()):
    label = '/'.join(filter(None, (relative, entry['Name'])))
    for pin in pins:
        if entry.get('ID') == pin['remote_id']:
            return None if any(pin['path'] == p or pin['path'].startswith(p + '/') for p in excludes) else pin
        parent = pin.get('label', pin['path']).rstrip('/')
        if label.startswith(parent + '/'):
            path = pin['path'] + label[len(parent):]
            if any(path == p or path.startswith(p + '/') for p in excludes):
                return None
            return {**pin, 'path': path}
    return None


def offline_state(path, actions, errors, active=None):
    matches = [a for a in actions if a.path == path or a.path.startswith(path.rstrip('/') + '/')]
    if any(p == path or p.startswith(path.rstrip('/') + '/') for p in errors):
        return 'Erro · tentar novamente'
    if active and (active['path'] == path or active['path'].startswith(path.rstrip('/') + '/')):
        return 'Baixando…' if active['kind'] == 'download' else 'Enviando…'
    for kind in ('conflict', 'deletion', 'blocked', 'upload', 'download'):
        if any(a.kind == kind for a in matches):
            return STATES[kind]
    return STATES['equal'] if matches else 'Selecionado · aguardando análise'
