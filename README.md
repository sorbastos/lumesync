# Lume Sync

Acesse seu Google Drive pelo gerenciador de arquivos do Linux e escolha o que quer manter no computador.

Projeto em desenvolvimento, com interface em português e foco no Fedora/KDE.

## Como funciona

- Os arquivos do Drive são baixados conforme você os abre.
- A opção **Manter neste computador** cria uma cópia offline e mantém a sincronização enquanto o app está aberto.
- Use `.lumeignore` para excluir arquivos e pastas da sincronização.
- Conflitos precisam da sua escolha. As cópias offline não propagam exclusões automaticamente.

O acesso online usa cache e ocupa espaço no disco. Os arquivos escolhidos para uso offline ocupam espaço adicional.

## Instalar e abrir

Você precisa de Python 3.11 ou superior, rclone, FUSE3 e systemd de usuário.

Na pasta do projeto, execute:

```bash
bash setup.sh
bash start.sh
```

O primeiro comando cria o ambiente virtual `.venv` e instala as dependências nele. Nenhum pacote é instalado no Python global.

Nas próximas vezes, basta executar `bash start.sh`. Ainda não há instalador RPM nem início automático ao entrar no sistema.

## Conectar o Google Drive

1. No Google Cloud, habilite a Google Drive API e crie uma credencial OAuth do tipo **Aplicativo para computador**. Se o projeto estiver em teste, adicione sua conta aos usuários de teste.
2. No app, abra **Configurações → Conectar Google Drive**, selecione o JSON da credencial e autorize sua conta no navegador.
3. Execute:

```bash
bash sincronizar-meus-arquivos.sh
```

As pastas ficam em `~/Lume Sync/`, com atalhos no Dolphin. Cada pessoa deve usar suas próprias credenciais; a autorização permite acesso amplo ao Drive.

## Cuidados

- Não compartilhe a pasta `runtime/`: ela contém credenciais e dados privados.
- Não apague o cache enquanto houver alterações pendentes de envio.
- Se mover o projeto, recrie a `.venv` com `bash setup.sh`. Preserve a pasta `runtime/`.
- Documentos do Google aparecem como links no acesso online. Para uso offline, precisam ser exportados.
- Arquivos com nomes duplicados no Drive podem ter limitações no gerenciador de arquivos.

## Desenvolvimento

Rodar os testes:

```bash
.venv/bin/python -m unittest discover -s tests
```

Instalar a verificação antes dos commits:

```bash
.venv/bin/python scripts/install_git_hooks.py
```

As dependências ficam em `requirements.txt`; os metadados, em `pyproject.toml`.

O projeto ainda não tem licença de redistribuição definida.
