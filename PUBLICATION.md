# Checklist para publicar

Este repositório deve conter somente código, testes fictícios, documentação genérica, regras de exclusão e scripts revisados.

1. Instale o hook local: `python3 scripts/install_git_hooks.py`.
2. Confira a raiz Git: `git rev-parse --show-toplevel`.
3. Prepare apenas os arquivos aprovados. A política `.gitignore` exclui arquivos por padrão.
4. Execute `python3 scripts/check_publication.py --staged`.
5. Revise `git diff --cached --stat` e `git diff --cached`.
6. Confira a identidade do commit e prefira o e-mail noreply do GitHub.
7. Confirme que não há histórico anterior com credenciais ou arquivos privados.

Não use `git add -f` para contornar os bloqueios. Não envie ZIPs da pasta usada para executar o aplicativo: eles podem conter runtime, backups, cache e dados pessoais.

A detecção de padrões de segredos cobre somente alguns formatos conhecidos. Ela não é certificação de segurança nem substitui revisão manual. O hook é local e pode ser desativado; não é uma regra aplicada automaticamente pelo servidor.
