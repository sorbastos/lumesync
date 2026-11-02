# Pacote RPM

Alvo: **Fedora 44, x86_64, Python 3.14**. Pacote local, sem assinatura; não é um pacote oficial do Fedora.

## Construir

Instale `rpm-build`, prepare o ambiente e execute:

```bash
bash setup.sh
bash packaging/build-rpm.sh
```

O RPM e seu SHA-256 ficam em `dist/`. A construção baixa wheels do PyPI com as versões fixadas em `requirements-fedora44.txt`. Não usa sudo nem instala dependências Python globais. Apenas PySide6-Essentials é incluído, pois o app usa Qt Widgets.

Para usar um rpmbuild extraído localmente, defina `RPMBUILD=/caminho/para/rpmbuild` antes do comando. Os pacotes que fornecem as bibliotecas nativas são identificados no Fedora usado para construir; gere outro pacote para outra versão do sistema.

## Instalar e remover

```bash
sudo dnf install ./dist/lumesync-0.4.1-1.fc44.x86_64.rpm
sudo dnf remove lumesync
```

Após instalar, abra **Lume Sync** no menu. Os comandos `lume-sync` e `lume-sync-cli` também ficam disponíveis. A interface prepara as pastas automaticamente após a autorização; `lume-sync-conectar` continua disponível como alternativa pelo terminal.

## Arquivos

- Aplicativo e dependências isoladas: `/opt/lumesync/venv/`.
- Atalhos: `/usr/bin/`, menu e ícone do sistema.
- Dados privados da versão instalada: `~/.local/share/lumesync/`, respeitando `XDG_DATA_HOME`.
- O projeto executado pelo código mantém seu `runtime/` atual.

O pacote não inclui contas, tokens, arquivos sincronizados ou cache e não importa automaticamente o perfil do projeto. A remoção do RPM preserva os dados do usuário. Para abrir com um perfil existente, feche a versão anterior e informe um caminho absoluto em `LUMESYNC_DATA_DIR`; não execute duas versões com o mesmo perfil ao mesmo tempo.

```bash
# Dentro da pasta do projeto, usando o perfil existente:
LUMESYNC_DATA_DIR="$PWD/runtime" lume-sync
```

O pacote contém licenças das dependências nos respectivos diretórios `*.dist-info`. A licença de redistribuição do aplicativo ainda não foi definida. Não há configuração de início automático nem migração de credenciais feita pelo instalador.

## Verificação e assinatura

Os wheels do RPM usam versões e hashes SHA-256 fixados. O arquivo `.sha256` ao lado do RPM permite conferir o download. Para assinar com uma chave GPG sua já configurada, use `bash packaging/build-rpm.sh --sign-key IDENTIDADE`. Sem essa opção o pacote continua local e sem assinatura.

Os testes comuns usam `QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest discover -s tests`. O teste de ciclo real do serviço é opcional: `LUMESYNC_INTEGRATION=1 QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest discover -s tests -p test_service_integration.py`. Ele usa uma unidade temporária e sleep; não monta pastas nem acessa o Google. Testes de reinício completo do KDE, suspensão e interrupção de energia devem ser feitos em uma VM descartável antes de uma distribuição ampla.

A migração do histórico copia somente o banco identificado pela credencial anterior conhecida e preserva o original. Bancos antigos de autorizações já perdidas não são mesclados por suposição. A recuperação da configuração oferece escolher um backup e preserva o arquivo danificado.
