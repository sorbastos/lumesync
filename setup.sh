#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
unset PYTHONPATH PYTHONHOME
export PYTHONNOUSERSITE=1
if [[ ! -e .venv ]]; then
  "${PYTHON_BIN:-python3}" -c 'import sys; assert sys.version_info >= (3, 11), "Requer Python 3.11 ou superior"'
  "${PYTHON_BIN:-python3}" -m venv .venv
fi
if [[ ! -x .venv/bin/python ]] || ! .venv/bin/python -c 'import sys; raise SystemExit(sys.prefix == sys.base_prefix)' ; then
  printf '%s\n' 'A .venv existente é inválida. Recrie apenas o ambiente virtual e tente novamente.' >&2
  exit 1
fi
if grep -Eiq '^include-system-site-packages[[:space:]]*=[[:space:]]*true' .venv/pyvenv.cfg; then
  printf '%s\n' 'A .venv não pode compartilhar pacotes do sistema. Recrie-a sem --system-site-packages.' >&2
  exit 1
fi
.venv/bin/python -I -m pip --require-virtualenv install -r requirements.txt
.venv/bin/python -I -m pip --require-virtualenv install --no-deps -e .
.venv/bin/python -I -m pip check
printf '%s\n' 'Ambiente pronto. Execute: bash start.sh'
