# Segurança e privacidade

Nunca envie tokens OAuth, JSON de cliente OAuth, perfil rclone, arquivos `.env`, chaves, cookies, bancos SQLite, logs, capturas com dados pessoais ou conteúdo de pastas sincronizadas em commits, issues, discussões ou anexos públicos.

Os nomes `access_token`, `client_secret` e similares no código são parâmetros do protocolo. Os valores nos testes são fictícios; credenciais reais devem ficar exclusivamente nos arquivos privados de execução.

## Dados locais

`runtime/` e suas cópias/backup contêm dados privados, mesmo quando nenhum arquivo do Drive foi baixado. Índices e logs podem revelar nomes de documentos, IDs remotos e caminhos locais. O cache pode conter conteúdo e alterações ainda não enviadas. Não distribua esse diretório.

## Revisão antes de publicar

Use um repositório Git próprio para o projeto. Confira a raiz com `git rev-parse --show-toplevel`. Nunca execute `git add .` a partir de sua pasta pessoal.

Execute o verificador dos arquivos preparados e revise o diff. O verificador não detecta todo formato de segredo ou dado pessoal. Dados sensíveis também podem existir em commits antigos: apagar apenas o arquivo atual não os remove do histórico.

Se um segredo for publicado, revogue-o no provedor antes de tratar o histórico. Não cole o segredo em uma issue para pedir ajuda.

## Relatar vulnerabilidades

Não publique provas de conceito que incluam credenciais ou dados de contas reais. Prefira o recurso de relato privado de vulnerabilidade do GitHub quando estiver habilitado. Este projeto ainda não define outro canal privado ou prazo de resposta.

O acesso sob demanda permite que operações feitas pelo gerenciador de arquivos alcancem a nuvem. As regras de conflito e exclusão do motor de cópias offline não são uma barreira de proteção para todas as operações da montagem rclone.
