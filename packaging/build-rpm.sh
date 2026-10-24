#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
if [[ ! -x .venv/bin/python ]]; then
  printf '%s\n' 'Execute bash setup.sh antes de construir o pacote.' >&2
  exit 1
fi
exec .venv/bin/python -I packaging/build_rpm.py "$@"
