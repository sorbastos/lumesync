# Lume Sync

Acesse seu Google Drive pelo gerenciador de arquivos do Linux e escolha o que quer manter no computador.

Projeto em desenvolvimento, com interface em português e foco no Fedora/KDE.

## Como funciona

- Os arquivos do Drive são baixados conforme você os abre.
- A opção **Manter neste computador** cria uma cópia offline e mantém a sincronização enquanto o app está aberto.
- **Liberar cópia offline** remove apenas o arquivo do computador e mantém a versão no Drive. O arquivo precisa estar sincronizado; para baixar de novo, use **Manter neste computador**.
- Use `.lumeignore` para excluir arquivos e pastas da sincronização.
- Conflitos precisam da sua escolha. As cópias offline não propagam exclusões automaticamente.

O acesso online usa cache e ocupa espaço no disco. Os arquivos escolhidos para uso offline ocupam espaço adicional.

## Instalar no Fedora

O pacote RPM é preparado para **Fedora 44 x86_64**. Depois de baixar o arquivo:

```bash
sudo dnf install ./lumesync-0.3.0-1.fc44.x86_64.rpm
```

Abra **Lume Sync** pelo menu de aplicativos. Para preparar as pastas após conectar a conta, execute `lume-sync-conectar`.

A versão instalada guarda seus dados em `~/.local/share/lumesync/` e não importa automaticamente a conta usada no projeto. Veja [os detalhes do pacote](packaging/README.md) para usar um perfil existente ou construir o RPM.

## Executar pelo código

Você precisa de Python 3.11 ou superior, rclone, FUSE3 e systemd de usuário.

Na pasta do projeto, execute:

```bash
bash setup.sh
bash start.sh
```

O primeiro comando cria o ambiente virtual `.venv` e instala as dependências nele. Nenhum pacote é instalado no Python global.

Em **Configurações → Aparência**, escolha o tema **Escuro** ou **Claro**. A escolha é salva automaticamente.

Nas próximas vezes, basta executar `bash start.sh`. O início automático ao entrar no sistema ainda não é configurado.

## Conectar o Google Drive

1. No Google Cloud, habilite a Google Drive API e crie uma credencial OAuth do tipo **Aplicativo para computador**. Se o projeto estiver em teste, adicione sua conta aos usuários de teste.
2. No app, abra **Configurações → Conectar Google Drive**, selecione o JSON da credencial e autorize sua conta no navegador.
3. Execute:

```bash
bash sincronizar-meus-arquivos.sh
```

As pastas ficam em `~/Lume Sync/`, com atalhos no Dolphin. Cada pessoa deve usar suas próprias credenciais; a autorização permite acesso amplo ao Drive.

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
