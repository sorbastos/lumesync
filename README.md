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
python3 -m venv .venv
.venv/bin/python -m pip install -e .
./start.sh
```

Uma cópia nova inicia em demonstração, sem conta conectada. Para gerar arquivos fictícios:

```bash
.venv/bin/python -m lumesync.demo
```

## Conectar uma conta própria

Habilite a Google Drive API em um projeto próprio do Google Cloud e crie um cliente OAuth **Aplicativo para computador**. Configure os usuários de teste conforme solicitado pelo Google. No app, use **Configurações → Conectar Google Drive** e autorize pelo navegador.

Depois de conectar, execute:

```bash
./sincronizar-meus-arquivos.sh
```

O preparador cria pastas sob `~/Lume Sync/`, adiciona favoritos no Dolphin e usa um serviço de usuário transitório para a montagem. Não há início automático instalado no login.

O escopo OAuth `drive` permite acesso amplo à conta autorizada. Cada pessoa deve usar suas próprias credenciais. Este repositório não fornece credenciais nem uma conta compartilhada.

## Cache e privacidade

O cache online tem alvo de 2 GiB e buffer de 8 MiB por arquivo aberto. Esse alvo pode ser excedido por arquivos abertos ou uploads pendentes. Nunca limpe o cache manualmente sem verificar alterações pendentes. Cópias offline ocupam espaço adicional conforme os itens selecionados.

`runtime/` guarda credenciais, índices, logs e cache privados. O diretório não deve ser compartilhado ou versionado. Arquivos de credenciais são privados ao usuário; ainda não há integração com um cofre de segredos do sistema.

## Testes

```bash
.venv/bin/python -m unittest discover -s tests
python3 scripts/check_publication.py --staged
```

Os testes usam dados fictícios e diretórios temporários. Não usam credenciais de uma conta real. Alguns testes de filtros exigem rclone instalado.

## Publicação segura

Leia [PUBLICATION.md](PUBLICATION.md) e [SECURITY.md](SECURITY.md). A lista de permissão do Git, o verificador local e o hook ajudam a impedir inclusões acidentais; não substituem revisão humana e não garantem ausência de vulnerabilidades.

Ainda não foi definida uma licença de redistribuição. O projeto é experimental e não tem equivalência completa com clientes comerciais. Não há garantia de operação sob perda de energia, rede instável prolongada ou edições concorrentes em vários computadores.

Referências: [rclone mount](https://rclone.org/commands/rclone_mount/), [backend Drive](https://rclone.org/drive/) e [OAuth desktop Google](https://developers.google.com/identity/protocols/oauth2/native-app).
