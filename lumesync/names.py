"""Mapeamento estável por ID: nomes remotos nunca viram caminhos sem validação."""
import hashlib
from .core import valid_path


def component(name):
    out = ''.join(''.join('%%%02X' % b for b in char.encode('utf-8'))
                  if char in '/\\%\x00' or ord(char)<32 or ord(char)==127 else char for char in name)
    if out in ('', '.', '..'):
        out = ''.join('%%%02X' % b for b in name.encode()) or '%00'
    # Leave space for a suffix and for the filesystem's 255-byte component limit.
    if len(out.encode())>180:
        shortened=out.encode()[:160].decode('utf-8',errors='ignore')
        out=shortened+'~'+hashlib.sha256(name.encode()).hexdigest()[:16]
    valid_path(out)
    return out


def allocate(resources, parent, cache):
    """Keep existing aliases, reserve natural names, disambiguate by immutable ID."""
    names={r['id']:component(r['name']) for r in resources}
    natural=set(names.values()); used=set(); result={}
    for resource in sorted(resources,key=lambda r:r['id']):
        old=cache.get(resource['id'],{})
        if old.get('parent')==parent and old.get('name')==resource['name']:
            alias=old.get('local','')
            valid_path(alias)
            if '/' in alias or len(alias.encode())>255:
                raise ValueError('Mapeamento de nomes inválido; origem preservada')
            if alias in used:
                raise ValueError('Mapeamento duplicado; origem preservada')
            result[resource['id']]=alias;used.add(alias)
    for resource in sorted(resources,key=lambda r:r['id']):
        rid=resource['id']
        if rid in result:continue
        alias=names[rid]
        if alias in used:
            suffix=hashlib.sha256(rid.encode()).hexdigest()[:16]
            alias=names[rid]+'~'+suffix
            counter=0
            while alias in used or alias in natural:
                counter+=1;alias=names[rid]+'~'+suffix+'-'+str(counter)
        used.add(alias);result[rid]=alias
    for resource in resources:
        rid=resource['id'];cache[rid]={'parent':parent,'name':resource['name'],'local':result[rid]}
    return result
