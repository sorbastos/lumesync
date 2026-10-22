"""Cria exemplos somente quando as pastas de demonstração estão vazias."""
from pathlib import Path
from .config import PROJECT


def main():
    local, remote = PROJECT / 'demo/local', PROJECT / 'demo/nuvem'
    if any(path.exists() and any(path.iterdir()) for path in (local, remote)):
        print('A demonstração já contém arquivos. Nenhum arquivo foi alterado.')
        return
    for root, name, text in [
        (local, 'Boas-vindas.txt', 'Este arquivo nasceu no computador.\n'),
        (remote, 'Da nuvem.txt', 'Este arquivo nasceu na nuvem de demonstração.\n'),
        (local, 'Decisão.txt', 'Versão local\n'),
        (remote, 'Decisão.txt', 'Versão remota\n'),
    ]:
        root.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding='utf-8')
    print('Exemplos criados. Execute ./start.sh para abrir.')


if __name__ == '__main__': main()
