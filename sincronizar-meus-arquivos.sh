#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if [[ ! -x .venv/bin/python ]] || ! .venv/bin/python -c 'import sys; raise SystemExit(sys.prefix == sys.base_prefix)' ; then
  printf '%s\n' 'Ambiente virtual ausente ou inválido. Execute: bash setup.sh' >&2
  exit 1
fi
export PYTHONNOUSERSITE=1
unset PYTHONPATH PYTHONHOME
exec .venv/bin/python -I -m lumesync.online setup --launch "$@"
