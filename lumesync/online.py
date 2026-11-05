"""Drive sob demanda por rclone/FUSE + cópias offline selecionadas pelo usuário."""
from __future__ import annotations
import argparse
import configparser
import io
import json
import os
import shutil
import subprocess
import sys
import time
import tempfile
from datetime import datetime,timezone
from pathlib import Path

from .config import DATA,DEFAULT_IGNORE,PROFILE_NAME,load,save
from .drive import private_json,DriveProvider,API,FIELDS,FOLDER
from .ignore import DEFAULT_TEXT,IgnoreRules

REMOTE='lume-drive'


class UnavailablePin(RuntimeError):
    """Selection cannot be resolved safely; preserve its local files."""



def checked(arguments,**kwargs):
    result=subprocess.run(arguments,capture_output=True,text=True,timeout=kwargs.pop('timeout',90),**kwargs)
    if result.returncode:
        # No token or credential is passed as a command argument.
        raise RuntimeError((result.stderr or result.stdout or 'Comando não concluído').strip()[-2000:])
    return result.stdout


class OnlineDrive:
    def __init__(self,config=None,data=None):
        self.config=config if config is not None else load()
        self.data=data if data is not None else DATA
        self.folder=Path(self.config['local']).expanduser()
        self.rclone_config=self.data/'rclone-online.conf'
        self.filters=self.data/'rclone-online.filters'
        self.cache=self.data/'online-cache'
        self.log=self.data/'rclone-online.log'
        self.rclone=shutil.which('rclone')
        import hashlib
        self.service = 'lume-sync-drive-' + hashlib.sha256(str(self.data.resolve()).encode()).hexdigest()[:16]
        self.pending_auth = self.data/'.google-authorization.pending.json'
        self.pin_warnings = []
        self.unavailable_paths = []
        self.recovering_auth = False

    def command(self,*args):
        if not self.rclone:raise RuntimeError('Instale rclone e fuse3 para usar o acesso sob demanda.')
        return [self.rclone,*args,'--config',str(self.rclone_config)]

    def mount_source(self):
        result = subprocess.run(['findmnt','-rn','-M',str(self.folder),'-o','SOURCE,FSTYPE'],
                                capture_output=True,text=True,timeout=10)
        return result.stdout.strip() if result.returncode == 0 else ''

    def mounted(self):
        source = self.mount_source()
        if not source.startswith(REMOTE + ': ') or 'fuse.rclone' not in source:
            return False
        try:
            self.folder.stat()
            return True
        except OSError:
            return False

    def configure_backend(self):
        if not self.rclone:raise RuntimeError('rclone não encontrado')
        self.data.mkdir(parents=True,exist_ok=True,mode=0o700)
        if self.pending_auth.exists() and not self.recovering_auth:
            self.complete_authorization()
        # Existing backend token can be newer than the app token: retain it.
        if not self.rclone_config.exists():
            token=json.loads((self.data/'google-token.json').read_text())
            oauth={'access_token':token['access_token'],'refresh_token':token.get('refresh_token',''),
                   'token_type':token.get('token_type','Bearer'),
                   'expiry':datetime.fromtimestamp(token.get('expires_at',0),timezone.utc).isoformat()}
            parser=configparser.ConfigParser(interpolation=None)
            parser[REMOTE]={'type':'drive','scope':'drive','client_id':token['client_id'],
                            'client_secret':token.get('client_secret',''),'token':json.dumps(oauth),'root_folder_id':self.config.get('root_id','root'),
                            'export_formats':'desktop','use_trash':'true',
                            'lume_authorization_id':token.get('authorization_id','')}
            stream=io.StringIO();parser.write(stream)
            fd=os.open(self.rclone_config,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'w') as handle:handle.write(stream.getvalue())
        else:
            parser=configparser.ConfigParser(interpolation=None);parser.read(self.rclone_config)
            if parser.get(REMOTE,'root_folder_id',fallback='root')!=self.config.get('root_id','root'):
                raise RuntimeError('A raiz online mudou. Desmonte e reconfigure o perfil antes de continuar.')
        os.chmod(self.rclone_config,0o600)
        ignore=Path(self.config.get('ignore_file',str(DEFAULT_IGNORE)))
        rules=IgnoreRules.from_file(ignore) if ignore.exists() else IgnoreRules(DEFAULT_TEXT.splitlines())
        temporary=self.filters.with_suffix('.tmp');temporary.write_text(rules.rclone_filters());os.chmod(temporary,0o600);os.replace(temporary,self.filters)

    def complete_authorization(self):
        """A pending credential is a recovery journal, removed only after both consumers succeed."""
        if not self.pending_auth.exists():
            return
        provider = DriveProvider(self.pending_auth, self.config.get('root_id', 'root'))
        account_root = provider.request('GET', API+'/root', params={'fields':'id'}).json()['id']
        previous_path = self.data/'google-token.json'
        previous = json.loads(previous_path.read_text()) if previous_path.exists() else {}
        previous_account = previous.get('account_root_id')
        selected_root = self.config.get('root_id', 'root')
        if previous and (previous.get('client_id') != provider.token.get('client_id') or
                         previous_account and previous_account != account_root or
                         self.config.get('drive_scope') == 'all' and selected_root != 'root' and selected_root != account_root):
            self.pending_auth.unlink()
            raise RuntimeError('Esta autorização pertence a outra conta ou cliente Google. Use a conta original deste perfil.')
        provider.token['account_root_id'] = account_root
        private_json(self.pending_auth, provider.token)
        if previous and self.config.get('mode') == 'drive':
            from .config import build
            # Stabilize the exact legacy profile before rotating the old credential.
            engine = build(self.offline_config(), data=self.data)
            engine.state.close()
        self.recovering_auth = True
        try:
            self.refresh_authorization(self.pending_auth)
            private_json(previous_path, provider.token)
            self.pending_auth.unlink()
        finally:
            self.recovering_auth = False

    def refresh_authorization(self, token_path=None):
        """Apply explicit Google reauthorization without overwriting refreshed tokens on scans."""
        if not self.rclone_config.exists():
            return  # First connection: setup creates the backend after resolving the root.
        token=json.loads((token_path or self.data/'google-token.json').read_text())
        if not token.get('access_token') or not token.get('refresh_token') or not token.get('client_id'):
            raise RuntimeError('A nova autorização está incompleta. Conecte a conta Google novamente.')
        parser=configparser.ConfigParser(interpolation=None)
        parser.read(self.rclone_config)
        if not parser.has_section(REMOTE):
            raise RuntimeError('Configuração do acesso online inválida; a autorização anterior foi preservada.')
        oauth={'access_token':token['access_token'],'refresh_token':token['refresh_token'],
               'token_type':token.get('token_type','Bearer'),
               'expiry':datetime.fromtimestamp(token.get('expires_at',0),timezone.utc).isoformat()}
        parser[REMOTE].update({'client_id':token['client_id'],
                              'client_secret':token.get('client_secret',''),
                              'token':json.dumps(oauth),
                              'lume_authorization_id':token.get('authorization_id','')})
        # Stop the old process before replacing its config: it can write its old token back.
        legacy_active = self.adopt_legacy_service()
        status=subprocess.run(['systemctl','--user','is-active',self.service+'.service'],
                              capture_output=True,text=True,timeout=10)
        if status.returncode not in (0,3,4):
            raise RuntimeError('Não foi possível consultar o serviço do Drive. Tente conectar novamente.')
        active=status.returncode==0
        restart = active or legacy_active
        if active:
            checked(['systemctl','--user','stop',self.service+'.service'],timeout=45)
        temporary = None
        try:
            fd,name=tempfile.mkstemp(prefix='.rclone-auth-',dir=self.data)
            temporary=Path(name)
            with os.fdopen(fd,'w') as handle:
                parser.write(handle)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary,self.rclone_config)
        except OSError:
            if restart:
                self.start()
            raise
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        if restart:
            # --collect removes the transient unit when stopped; recreate it.
            self.start()

    def mount_arguments(self):
        return self.command('mount',REMOTE+':',str(self.folder),
            '--vfs-cache-mode','full',
            '--cache-dir',str(self.cache),'--vfs-cache-max-size','2G',
            '--vfs-cache-max-age','1h','--vfs-cache-min-free-space','2G',
            '--vfs-cache-poll-interval','30s','--buffer-size','8M',
            '--vfs-read-ahead','8M','--vfs-read-chunk-size','8M',
            '--vfs-read-chunk-size-limit','32M','--vfs-write-back','5s',
            '--dir-cache-time','5m','--poll-interval','30s','--umask','077',
            '--filter-from',str(self.filters),'--log-file',str(self.log),'--log-level','INFO',
            '--log-file-max-size','5M','--log-file-max-backups','2','--stats','1m')

    def adopt_legacy_service(self):
        result = subprocess.run(['systemctl','--user','show','lume-sync-drive.service','--property=ExecStart','--value'],
                                capture_output=True,text=True,timeout=10)
        if result.returncode == 0 and str(self.rclone_config) in result.stdout:
            checked(['systemctl','--user','stop','lume-sync-drive.service'],timeout=45)
            return True
        return False

    def start(self):
        self.adopt_legacy_service()
        if self.mounted():
            owner = subprocess.run(['systemctl','--user','show',self.service+'.service','--property=ExecStart','--value'],
                                   capture_output=True,text=True,timeout=10)
            if owner.returncode == 0 and str(self.rclone_config) in owner.stdout:
                return
            raise RuntimeError('A pasta já está montada por outro perfil. Feche a conexão desse perfil antes de continuar.')
        source = self.mount_source()
        if source:
            if not source.startswith(REMOTE + ': ') or 'fuse.rclone' not in source:
                raise RuntimeError('Já existe outro sistema de arquivos nesta pasta.')
            # Stale FUSE entry from an interrupted process; no data is removed.
            checked(['fusermount3','-u',str(self.folder)])
        if not Path('/dev/fuse').exists():raise RuntimeError('FUSE indisponível neste ambiente. Execute o app na sessão normal do computador.')
        if self.folder.is_symlink():raise ValueError('A pasta online não pode ser um link simbólico')
        self.folder.mkdir(parents=True,exist_ok=True)
        entries=list(self.folder.iterdir())
        marker=self.folder/'.lume-managed'
        if entries and entries!=[marker]:raise RuntimeError('A pasta contém arquivos locais. Eles serão preservados; use uma pasta vazia para montar o Drive.')
        self.configure_backend()
        if marker.exists():
            backup=self.data/('mount-marker-'+str(time.time_ns()))
            shutil.move(marker,backup)
        if not shutil.which('systemd-run'):
            raise RuntimeError('systemd de usuário é necessário para manter o Drive disponível em segundo plano')
        subprocess.run(['systemctl','--user','reset-failed',self.service+'.service'],
                       stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10)
        checked(['systemd-run','--user','--collect','--unit='+self.service,
                 '--property=Restart=on-failure','--property=RestartSec=5s',
                 '--',*self.mount_arguments()],timeout=15)
        deadline=time.monotonic()+30
        while time.monotonic()<deadline:
            if self.mounted():return
            time.sleep(.5)
        raise RuntimeError('Montagem não confirmada. Consulte runtime/rclone-online.log.')

    def reconnect(self):
        self.configure_backend()
        self.adopt_legacy_service()
        status = subprocess.run(['systemctl','--user','is-active',self.service+'.service'],capture_output=True,text=True,timeout=10)
        if status.returncode == 0:
            checked(['systemctl','--user','stop',self.service+'.service'],timeout=45)
        elif status.returncode not in (3,4):
            raise RuntimeError('Não foi possível consultar o serviço do Drive.')
        self.start()

    def entries(self,relative=''):
        self.configure_backend()
        # lsjson without --recursive lists metadata only, never bulk file contents.
        command = self.command('lsjson',REMOTE+':'+relative,'--max-depth','1','--filter-from',str(self.filters),'--drive-export-formats','desktop')
        try:
            raw=checked(command)
        except RuntimeError as error:
            if 'invalid_grant' not in str(error).lower():
                raise
            app_token=json.loads((self.data/'google-token.json').read_text())
            backend=configparser.ConfigParser(interpolation=None)
            backend.read(self.rclone_config)
            backend_token=json.loads(backend[REMOTE]['token'])
            if app_token.get('refresh_token') == backend_token.get('refresh_token'):
                raise
            private_json(self.pending_auth,app_token)
            self.complete_authorization()
            raw=checked(command)
        items=json.loads(raw)
        from collections import Counter
        counts=Counter(item['Name'] for item in items)
        for item in items:
            item['_duplicate']=counts[item['Name']]>1
        return sorted(items,key=lambda item:(not item.get('IsDir',False),item['Name'].casefold()))

    def resolve_item_path(self, provider, rid):
        from .names import allocate
        root_id = provider.root_id
        if root_id == 'root':
            root_id = provider.request('GET',API+'/root',params={'fields':'id'}).json()['id']
        current = rid
        chain = []
        seen = set()
        while current != root_id:
            if current in seen or len(seen) >= 128:
                raise RuntimeError('Não foi possível localizar a seleção offline dentro da pasta configurada.')
            seen.add(current)
            try:
                resource = provider.request('GET',API+'/'+current,params={'fields':FIELDS+',trashed'}).json()
            except RuntimeError as error:
                if 'HTTP 404' in str(error):
                    raise UnavailablePin('O item não está mais disponível nesta conta. A cópia local foi preservada.') from error
                raise
            if resource.get('trashed'):
                raise UnavailablePin('O item ou sua pasta está na lixeira do Google Drive. A cópia local foi preservada. Restaure-o no Drive para retomar a sincronização.')
            parents = resource.get('parents', [])
            if not parents:
                raise UnavailablePin('O item saiu da pasta configurada. A cópia local foi preservada; mova-o de volta para retomar a sincronização.')
            parent = parents[0]
            chain.append((resource,parent))
            current = parent
        parts, labels = [], []
        for resource,parent in reversed(chain):
            siblings = list(provider.children(parent))
            if not any(item['id'] == resource['id'] for item in siblings):
                raise UnavailablePin('O item mudou durante a consulta ou deixou de estar disponível. A cópia local foi preservada; atualize a lista para verificar novamente.')
            aliases = allocate(siblings,parent,provider.name_map)
            parts.append(aliases[resource['id']])
            labels.append(resource['name'])
        private_json(provider.mapping_file,provider.name_map)
        return '/'.join(parts), '/'.join(labels)

    def finish_pin_move(self, engine, journal):
        from .core import safe_path
        old, new = journal['old'], journal['new']
        source = safe_path(engine.local, old)
        destination = safe_path(engine.local, new)
        if source.exists():
            if destination.exists():
                raise RuntimeError('Renomeação offline encontrou outra cópia no destino. Arquivos preservados; resolva os caminhos antes de continuar.')
            destination.parent.mkdir(parents=True,exist_ok=True)
            source.rename(destination)
        # Reapplying the DB/config after a crash is idempotent.
        rows = list(engine.state.db.execute('select path,checksum from baseline'))
        for path, checksum in rows:
            if path == old or path.startswith(old+'/'):
                target = new+path[len(old):]
                engine.state.db.execute('delete from baseline where path=?',(path,))
                engine.state.db.execute('insert or replace into baseline values(?,?)',(target,checksum))
        engine.state.db.commit()
        private_json(self.data/'config.json',journal['config'])
        self.config = journal['config']
        (self.data/'.pin-move.pending.json').unlink(missing_ok=True)

    def reconcile_pins(self):
        """Follow explicitly selected IDs; preserve local edits and resume interrupted moves."""
        from .config import build
        from .core import exclusive
        pending = self.data/'.pin-move.pending.json'
        self.pin_warnings = []
        self.unavailable_paths = []
        if not self.config.get('pins') and not pending.exists():
            return
        engine = build(self.offline_config(), data=self.data)
        try:
            with exclusive(engine.state.directory):
                if pending.exists():
                    self.finish_pin_move(engine,json.loads(pending.read_text()))
                provider = engine.provider
                for pin in list(self.config.get('pins', [])):
                    try:
                        new, label = self.resolve_item_path(provider,pin['remote_id'])
                    except UnavailablePin as error:
                        self.unavailable_paths.append(pin['path'])
                        self.pin_warnings.append(pin.get('label', pin['path']) + ': ' + str(error))
                        continue
                    old = pin['path']
                    if not new:
                        raise RuntimeError('Selecione uma pasta ou arquivo dentro do Drive para manter offline.')
                    if new == old:
                        continue
                    if new.startswith(old+'/') or old.startswith(new+'/'):
                        raise RuntimeError('Renomeação de pastas sobrepostas requer revisão. Arquivos locais preservados.')
                    import copy
                    updated = copy.deepcopy(self.config)
                    for selected in updated['pins']:
                        if selected['path'] == old or selected['path'].startswith(old+'/'):
                            selected['path'] = new+selected['path'][len(old):]
                            selected['label'] = label+selected.get('label',old)[len(pin.get('label',old)):]
                    updated['offline_excludes'] = [new+p[len(old):] if p == old or p.startswith(old+'/') else p
                                                   for p in updated.get('offline_excludes', [])]
                    journal = {'old':old,'new':new,'config':updated}
                    private_json(pending,journal)
                    self.finish_pin_move(engine,journal)
        finally:
            engine.state.close()

    def pin(self,entry,relative):
        rid=entry.get('ID')
        if not rid:raise RuntimeError('O Drive não retornou o ID deste item; ele não foi marcado para download.')
        provider=DriveProvider(self.data/'google-token.json',self.config.get('root_id','root'))
        root_id=provider.root_id
        if root_id=='root':root_id=provider.request('GET',API+'/root',params={'fields':'id'}).json()['id']
        chain=[];current=rid;seen=set()
        while current!=root_id:
            if current in seen or len(chain)>128:raise RuntimeError('Caminho remoto inválido')
            seen.add(current)
            resource=provider.request('GET',API+'/'+current,params={'fields':FIELDS}).json()
            if current == rid and resource.get('mimeType', '').startswith('application/vnd.google-apps.') and resource.get('mimeType') != FOLDER:
                raise RuntimeError('Este documento Google é um link online. Exporte-o no navegador para criar uma cópia offline editável.')
            parents=resource.get('parents',[])
            if not parents:raise RuntimeError('O item não pertence à raiz configurada')
            parent=parents[0];chain.append((resource,parent));current=parent
        from .names import allocate
        parts=[]
        for resource,parent in reversed(chain):
            siblings=list(provider.children(parent))
            if not any(item['id'] == resource['id'] for item in siblings):
                raise UnavailablePin('O item não está mais disponível nesta pasta. Atualize a lista antes de selecionar novamente.')
            aliases=allocate(siblings,parent,provider.name_map)
            parts.append(aliases[resource['id']])
        path='/'.join(parts)
        if entry.get('MimeType','').startswith('application/vnd.google-apps.') and not entry.get('IsDir'):
            raise RuntimeError('Documentos nativos Google ficam online; use a exportação no navegador para obter uma cópia editável.')
        private_json(provider.mapping_file,provider.name_map)
        config=load();pins=config.setdefault('pins',[])
        if not any(pin['remote_id']==rid for pin in pins):pins.append({'remote_id':rid,'path':path,'label':relative})
        config['offline_excludes'] = [p for p in config.get('offline_excludes', [])
                                     if not (p == path or p.startswith(path + '/'))]
        config['access_mode']='online';save(config);self.config=config
        return path

    def release_file(self, relative):
        """Retira uma cópia local em dia, sem escrever ou apagar no Drive."""
        import copy
        from .config import build
        from .core import digest, exclusive, safe_path
        original = copy.deepcopy(self.config)
        if not any(relative == p['path'] or relative.startswith(p['path'] + '/')
                   for p in original.get('pins', [])):
            raise ValueError('Este arquivo não está selecionado para uso offline.')
        if any(relative == p or relative.startswith(p + '/') for p in original.get('offline_excludes', [])):
            raise ValueError('Este arquivo já foi retirado da seleção offline.')
        engine = build(self.offline_config(), data=self.data)
        try:
            with exclusive(engine.state.directory):
                target = safe_path(engine.local, relative)
                if not target.is_file():
                    raise ValueError('Selecione um arquivo baixado. A liberação de pastas inteiras ainda não está disponível.')
                action = next((a for a in engine.plan() if a.path == relative), None)
                if action is None or action.kind != 'equal' or not action.local or not action.remote:
                    raise RuntimeError('A cópia ainda não está igual à nuvem. Sincronize ou resolva as pendências antes de liberar espaço.')
                def identity():
                    stat = safe_path(engine.local, relative).stat()
                    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
                before = identity()
                if digest(target) != action.remote.checksum or identity() != before:
                    raise RuntimeError('O arquivo mudou durante a verificação. A cópia foi preservada; tente novamente.')
                updated = copy.deepcopy(original)
                updated['pins'] = [p for p in original.get('pins', []) if p['path'] != relative]
                updated['offline_excludes'] = sorted(set(original.get('offline_excludes', [])) | {relative})
                # Forget the intentional local absence so selecting it again downloads it.
                engine.state.db.execute('delete from baseline where path = ?', (relative,))
                engine.state.db.commit()
                save(updated)
                try:
                    if identity() != before:
                        raise RuntimeError('O arquivo mudou. A cópia local foi preservada.')
                    target.unlink()
                except Exception:
                    save(original)
                    raise
                self.config = updated
                return relative
        finally:
            engine.state.close()

    def offline_config(self):
        return {**self.config,'access_mode':'offline','local':self.config.get('offline_local',str(self.folder.parent/'Offline')),
                'include_paths':[p['path'] for p in self.config.get('pins',[])],
                'offline_excludes':list(self.config.get('offline_excludes', [])) + self.unavailable_paths}


def setup(home=None, config=None):
    from .setup_real import add_place
    home=home if home is not None else Path.home()
    old=load() if config is None else config
    requested = 'root' if old.get('drive_scope') == 'all' else old.get('root_id', 'root')
    provider=DriveProvider(DATA/'google-token.json',requested)
    root=provider.request('GET',API+'/'+requested,params={'fields':'id,mimeType'}).json()
    if root.get('mimeType')!=FOLDER:raise RuntimeError('O link precisa ser de uma pasta do Google Drive. Selecione uma pasta e tente novamente.')
    parent=home/('Lume Sync' + (f' - {PROFILE_NAME}' if PROFILE_NAME else ''));ignore=parent/'.lumeignore'
    if parent.is_symlink():raise ValueError('A pasta do Lume Sync não pode ser um link simbólico')
    parent.mkdir(parents=True,exist_ok=True)
    if not ignore.exists():ignore.write_text(DEFAULT_TEXT)
    config={**old,'mode':'drive','access_mode':'online','root_id':root['id'],
            'local':str(parent/'Google Drive'),'offline_local':str(parent/'Offline'),
            'ignore_file':str(ignore),'pins':old.get('pins',[]),'interval':old.get('interval',60),
            'drive_scope':old.get('drive_scope', 'all' if requested == 'root' else 'folder')}
    private_json(DATA/('config-before-online-'+str(time.time_ns())+'.json'),old)
    controller=OnlineDrive(config)
    controller.configure_backend()
    controller.start()
    add_place(home/'.local/share/user-places.xbel',controller.folder, PROFILE_NAME)
    offline=Path(config['offline_local']);offline.mkdir(parents=True,exist_ok=True)
    add_place(home/'.local/share/user-places.xbel',offline, PROFILE_NAME)
    save(config)
    return controller


def main():
    parser=argparse.ArgumentParser(description='Lume Sync: Drive sob demanda')
    parser.add_argument('command',choices=['setup','mount','status'])
    parser.add_argument('--launch',action='store_true');args=parser.parse_args()
    try:
        if args.command=='setup':controller=setup()
        else:controller=OnlineDrive()
        if args.command=='mount':controller.start()
        print('Drive sob demanda:', 'montado' if controller.mounted() else 'desconectado',flush=True)
        print('Pasta:',controller.folder,flush=True)
        if args.launch:os.execv(sys.executable,[sys.executable,'-m','lumesync.app'])
    except Exception as error:parser.exit(1,str(error)+'\n')


if __name__=='__main__':main()
