"""Regras inspiradas em gitignore: comentários, glob, caminhos, pastas e !."""
import re
from dataclasses import dataclass
from pathlib import Path

DEFAULT_TEXT = '''# Lume Sync — exclusões. Não apagam arquivos da nuvem.
# Uma regra por linha; / ancora na raiz; ! inclui novamente.
.venv/
venv/
ambiente/
__pycache__/
*.pyc
.git/
node_modules/
.Trash-*/
.lume-*
*.insyncdl
.lumeignore
# Exemplos:
# /Filmes/
# /Series/
# *.tmp
# !anotacoes.tmp
'''


def glob_regex(pattern):
    out='';i=0
    while i<len(pattern):
        char=pattern[i]
        if pattern[i:i+3]=='**/':out+='(?:.*/)?';i+=3;continue
        if pattern[i:i+2]=='**':out+='.*';i+=2;continue
        if char=='*':out+='[^/]*'
        elif char=='?':out+='[^/]'
        elif char=='[':
            end=pattern.find(']',i+1)
            if end!=-1:
                content=pattern[i+1:end]
                if content.startswith('!'):content='^'+content[1:]
                out+='['+content.replace('\\','\\\\')+']';i=end
            else:out+='\\['
        elif char=='\\' and i+1<len(pattern):i+=1;out+=re.escape(pattern[i])
        else:out+=re.escape(char)
        i+=1
    return out


@dataclass
class Rule:
    pattern:str
    include:bool
    directory:bool
    regex:object


class IgnoreRules:
    def __init__(self,lines):
        self.rules=[]
        for raw in lines:
            line=raw.rstrip()
            if not line or line.startswith('#'):continue
            include=line.startswith('!')
            if include:line=line[1:]
            directory=line.endswith('/')
            pattern=line.rstrip('/')
            anchored=pattern.startswith('/') or '/' in pattern
            pattern=pattern.lstrip('/')
            if not pattern:continue
            prefix='^' if anchored else r'^(?:.*/)?'
            regex=re.compile(prefix+glob_regex(pattern)+r'(?P<descendant>/.*)?$')
            self.rules.append(Rule(('/' if anchored else '')+pattern,include,directory,regex))

    @classmethod
    def from_file(cls,path:Path):return cls(path.read_text(encoding='utf-8').splitlines())

    def matches(self,path,is_dir=False):
        excluded=False
        for rule in self.rules:
            match=rule.regex.match(path)
            if match and (not rule.directory or is_dir or match.group('descendant')):
                excluded=not rule.include
        return excluded

    def rclone_filters(self):
        # Git-style last match wins; rclone evaluates first match wins.
        out=[]
        for rule in reversed(self.rules):
            pattern=rule.pattern
            prefix='+ ' if rule.include else '- '
            out.append(prefix+pattern+'/**')
            if not rule.directory:out.append(prefix+pattern)
        return '\n'.join(out)+'\n'
