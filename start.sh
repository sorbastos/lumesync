#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if [[ ! -x .venv/bin/python ]] || ! .venv/bin/python -c 'import sys; raise SystemExit(sys.prefix == sys.base_prefix)' ; then
  printf '%s\n' 'Ambiente virtual ausente ou inválido. Execute: bash setup.sh' >&2
  exit 1
fi
export PYTHONNOUSERSITE=1
unset PYTHONPATH PYTHONHOME
if ! .venv/bin/python -I -c 'import importlib.util; raise SystemExit(importlib.util.find_spec("lumesync") is None)' ; then
  printf '%s\n' 'O ambiente precisa ser atualizado para o Python atual. Execute: bash setup.sh' >&2
  exit 1
fi
exec .venv/bin/python -I -m lumesync.app "$@"
