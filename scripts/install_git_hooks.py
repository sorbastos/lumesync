#!/usr/bin/env python3
"""Install a local pre-commit check without touching global Git settings."""
from pathlib import Path
import shlex
import subprocess
import sys

root=Path(__file__).resolve().parents[1]
if not (root/'.git').is_dir():raise SystemExit('Initialize a standalone Git repository in this directory first.')
actual=subprocess.run(['git','-C',str(root),'rev-parse','--show-toplevel'],capture_output=True,text=True,check=True).stdout.strip()
if Path(actual).resolve()!=root:raise SystemExit('Refusing an inherited parent Git repository.')
script=root/'scripts/check_publication.py'
hook=root/'.git/hooks/pre-commit'
if hook.exists():raise SystemExit('Existing pre-commit hook preserved; integrate the publication check manually.')
python = root / '.venv/bin/python'
if sys.prefix == sys.base_prefix or not python.is_file():
    raise SystemExit('Use .venv/bin/python scripts/install_git_hooks.py after bash setup.sh.')
hook.write_text('#!/bin/sh\nexec '+shlex.quote(str(python))+' -I '+shlex.quote(str(script))+' --staged\n')
hook.chmod(0o755)
print('Local publication guard installed.')
