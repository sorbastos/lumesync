#!/usr/bin/env python3
"""Audit only Git blobs; never print a matched secret. No third-party dependencies."""
import argparse
import re
import subprocess
import sys
from pathlib import Path,PurePosixPath

ROOT=Path(__file__).resolve().parents[1]
ROOT_FILES={'.gitignore','.lumeignore','README.md','SECURITY.md','PUBLICATION.md','pyproject.toml','start.sh','sincronizar-meus-arquivos.sh'}
PATTERNS={
    'Google OAuth secret':re.compile(rb'GOCSPX-[A-Za-z0-9_-]{12,}'),
    'Google access token':re.compile(rb'ya29\.[A-Za-z0-9_.-]{16,}'),
    'Google refresh token':re.compile(rb'1//[A-Za-z0-9_-]{24,}'),
    'GitHub token':re.compile(rb'(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})'),
    'Google API key':re.compile(rb'AIza[A-Za-z0-9_-]{30,}'),
    'AWS access key':re.compile(rb'(?:AKIA|ASIA)[A-Z0-9]{16}'),
    'Private key':re.compile(b'-----BEGIN '+rb'(?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    'JWT':re.compile(rb'eyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}'),
    'Personal home path':re.compile(b'/' + b'home/' + rb'[^/\s]+/'),
}


def git(*args):
    return subprocess.run(['git','-C',str(ROOT),*args],capture_output=True,check=True).stdout


def allowed(path):
    p=PurePosixPath(path)
    if path in ROOT_FILES:return True
    if len(p.parts)==2 and p.parts[0]=='lumesync' and p.suffix=='.py':return True
    if len(p.parts)==2 and p.parts[0]=='tests' and p.name.startswith('test_') and p.suffix=='.py':return True
    return path in {'scripts/check_publication.py','scripts/install_git_hooks.py'}


def check_blob(path,mode,sha):
    errors=[]
    if not allowed(path):errors.append('outside-public-allowlist')
    if mode not in ('100644','100755'):errors.append('non-regular-file')
    data=git('cat-file','blob',sha)
    if len(data)>1024*1024:errors.append('oversized-source-file')
    if b'\x00' in data:errors.append('binary-data')
    for label,pattern in PATTERNS.items():
        if pattern.search(data):errors.append(label)
    return errors


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--staged',action='store_true')
    parser.add_argument('--history',action='store_true')
    args=parser.parse_args()
    if not (ROOT/'.git').is_dir() or Path(git('rev-parse','--show-toplevel').decode().strip()).resolve()!=ROOT:
        parser.exit(2,'A standalone Git repository is required at the project root.\n')
    records=[]
    for raw in git('ls-files','--stage','-z').split(b'\x00'):
        if not raw:continue
        meta,name=raw.split(b'\t',1);mode,sha,stage=meta.decode().split()
        if stage!='0':parser.exit(2,'Resolve staged merge conflicts before publication.\n')
        records.append(('index',name.decode(),mode,sha))
    if args.history:
        for commit in git('rev-list','--all').decode().splitlines():
            for raw in git('ls-tree','-r','-z',commit).split(b'\x00'):
                if not raw:continue
                meta,name=raw.split(b'\t',1);mode,kind,sha=meta.decode().split()
                records.append((commit[:12],name.decode(),mode,sha))
    failures=[];seen=set()
    for context,path,mode,sha in records:
        key=(path,mode,sha)
        if key in seen:continue
        seen.add(key)
        for label in check_blob(path,mode,sha):failures.append(f'{context}: {path}: {label} (value redacted)')
    if failures:
        print('\n'.join(failures),file=sys.stderr);return 1
    print(f'Publication guard passed: {len(seen)} unique file revisions; allowlist and known-secret patterns checked.')
    return 0


if __name__=='__main__':sys.exit(main())
