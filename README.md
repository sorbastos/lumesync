# Lume Sync

Acesse seu Google Drive pelo gerenciador de arquivos do Linux e escolha o que quer manter no computador.

Projeto em desenvolvimento, com interface em português e foco no Fedora/KDE.

## Como funciona

- Os arquivos do Drive são baixados conforme você os abre.
- A opção **Manter neste computador** deixa o arquivo disponível sem internet e mantém a sincronização enquanto o app está aberto.
- **Liberar espaço** remove apenas a cópia mantida no computador e preserva a versão no Drive. Para baixar novamente, use **Manter neste computador**.
- Use `.lumeignore` para excluir arquivos e pastas da sincronização.
- Conflitos precisam da sua escolha. Arquivos mantidos no computador não propagam exclusões automaticamente.

**Pausar arquivos mantidos**, no ícone próximo ao relógio, pausa somente essa sincronização. O acesso pelo Dolphin continua independente.

O acesso online usa cache e ocupa espaço no disco. Os arquivos mantidos no computador ocupam espaço adicional, mas não aparecem em uma segunda pasta.

## Instalar no Fedora

O pacote RPM é preparado para **Fedora 44 x86_64**. Depois de baixar o arquivo:

```bash
sudo dnf install ./lumesync-0.6.0-1.fc44.x86_64.rpm
```

Abra **Lume Sync** pelo menu de aplicativos. A pasta do Drive é preparada automaticamente após conectar a conta.

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
2. Em **Configurações**, escolha **Todo o Meu Drive** ou **Uma pasta específica**. Para uma pasta específica, cole o link completo dela.
3. Clique em **Conectar Google Drive**, selecione o JSON da credencial e autorize sua conta no navegador.

O app prepara a pasta e o atalho no Dolphin automaticamente. Você escolhe depois o que quer manter no computador. Cada pessoa usa suas próprias credenciais. Projetos OAuth em teste exigem nova autorização após sete dias; em produção, reconecte a conta para renovar essa autorização.

Fechar a janela mantém o app em segundo plano. Clicar novamente no ícone do aplicativo reabre a janela existente, sem iniciar outra cópia. Abra-o pelo ícone próximo ao relógio; para encerrar, use **Aplicativo → Sair**. Sem bandeja disponível, a janela fica minimizada.

O projeto ainda não tem licença de redistribuição definida.
