# Lume Sync

Aplicativo experimental de Google Drive para Linux/KDE, com interface em português, acesso sob demanda pelo Dolphin e cópias offline selecionadas.

## Funcionamento

- A montagem **Google Drive** usa rclone/FUSE e transfere conteúdo conforme os arquivos são abertos ou editados.
- **Manter neste computador** cria cópias na pasta **Offline**, verificadas aproximadamente a cada minuto enquanto o app estiver em execução.
- As regras `.lumeignore` excluem arquivos e pastas; há suporte a comentários, padrões comuns, `/` na raiz e exceções `!`.
- Conflitos nas cópias offline exigem escolha. O motor offline não propaga exclusões automaticamente.

As pastas online e offline são separadas. Documentos nativos Google aparecem como links online; edição offline desses documentos exige exportação pelo Google. Nomes duplicados podem não ser distinguíveis pelo mesmo caminho no Dolphin; a interface usa IDs para seleção offline.

## Dependências e execução

Requer Python 3.11+, PySide6, requests, rclone, FUSE3 e systemd de usuário para a montagem. Ainda não há pacote RPM ou instalador tradicional.

```bash
bash setup.sh
bash start.sh
```

O instalador cria `.venv` sem compartilhar pacotes do sistema, instala as dependências de `requirements.txt` e o projeto em modo editável. O Python do sistema é usado apenas para criar o ambiente; não recebe instalações. Os lançadores exigem a `.venv` e não recorrem ao Python global. Não é necessário ativar o ambiente. Para escolher outro Python compatível, use `PYTHON_BIN=python3.12 bash setup.sh`.

`pyproject.toml` mantém os metadados e lê as dependências do mesmo `requirements.txt`, evitando listas divergentes. As faixas de versões não constituem um lockfile.

Depois de mover o projeto, recrie a `.venv`: ambientes virtuais não são portáveis. Não remova `runtime/` ao recriar o ambiente.

Uma cópia nova inicia em demonstração, sem conta conectada. Para gerar arquivos fictícios:

```bash
.venv/bin/python -m lumesync.demo
```

## Conectar uma conta própria

Habilite a Google Drive API em um projeto próprio do Google Cloud e crie um cliente OAuth **Aplicativo para computador**. Configure os usuários de teste conforme solicitado pelo Google. No app, use **Configurações → Conectar Google Drive** e autorize pelo navegador.

Depois de conectar, execute:

```bash
bash sincronizar-meus-arquivos.sh
```

O preparador cria pastas sob `~/Lume Sync/`, adiciona favoritos no Dolphin e usa um serviço de usuário transitório para a montagem. Não há início automático instalado no login.

O escopo OAuth `drive` permite acesso amplo à conta autorizada. Cada pessoa deve usar suas próprias credenciais. Este repositório não fornece credenciais nem uma conta compartilhada.

## Cache e privacidade

O cache online tem alvo de 2 GiB e buffer de 8 MiB por arquivo aberto. Esse alvo pode ser excedido por arquivos abertos ou uploads pendentes. Nunca limpe o cache manualmente sem verificar alterações pendentes. Cópias offline ocupam espaço adicional conforme os itens selecionados.

`runtime/` guarda credenciais, índices, logs e cache privados. O diretório não deve ser compartilhado ou versionado. Arquivos de credenciais são privados ao usuário; ainda não há integração com um cofre de segredos do sistema.

## Testes

```bash
.venv/bin/python -m unittest discover -s tests
.venv/bin/python scripts/check_publication.py --staged
```

Os testes usam dados fictícios e diretórios temporários. Não usam credenciais de uma conta real. Alguns testes de filtros exigem rclone instalado.

Para instalar a proteção de commit neste clone:

```bash
.venv/bin/python scripts/install_git_hooks.py
```

## Publicação segura

O verificador local e o hook ajudam a impedir inclusões acidentais; não substituem revisão humana e não garantem ausência de vulnerabilidades.

Ainda não foi definida uma licença de redistribuição. O projeto é experimental e não tem equivalência completa com clientes comerciais. Não há garantia de operação sob perda de energia, rede instável prolongada ou edições concorrentes em vários computadores.

Referências: [rclone mount](https://rclone.org/commands/rclone_mount/), [backend Drive](https://rclone.org/drive/) e [OAuth desktop Google](https://developers.google.com/identity/protocols/oauth2/native-app).
