"""Opt-in local archive queue. No remote transport, calculation or Core writes."""
import json
import os
from pathlib import Path
import re
import sqlite3
import threading
from contextlib import contextmanager
from hashlib import sha256
from datetime import datetime, timezone
from .archive import read_pinned, LIMIT, ArchiveQuery
from .details import DetailQuery
from .local_import import import_folder, stable_bytes, SMALL_SUFFIXES

APP_ID=1095191625
SCHEMA='autog-local-library/1'

def now():return datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode()
def root_path(value):
    p=Path(value)
    if not p.is_absolute() or '..' in p.parts or len(p.parts)<4 or p.resolve()!=p or p.is_symlink():raise ValueError('invalid library root')
    return p

@contextmanager
def open_db(root,write=False):
    p=root/'library.sqlite'
    if p.resolve()!=p or p.is_symlink():raise ValueError('invalid library database')
    if not write and not p.exists():raise ValueError('library not initialized')
    db=sqlite3.connect(p if write else p.as_uri()+'?mode=ro',uri=not write,timeout=5)
    db.row_factory=sqlite3.Row
    identity=db.execute('PRAGMA application_id').fetchone()[0]
    if identity!=APP_ID:
        if not write or identity or db.execute("SELECT count(*) FROM sqlite_master").fetchone()[0]:db.close();raise ValueError('not a library database')
        db.execute(f'PRAGMA application_id={APP_ID}')
        db.execute('CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
        db.execute('CREATE TABLE ingestions(id TEXT PRIMARY KEY,state TEXT NOT NULL,updated_at TEXT NOT NULL,profile TEXT,error TEXT)')
        db.commit()
    try:
        with db: yield db
    finally: db.close()

class LibraryManager:
    def __init__(self,config,seed_profile):
        self.config=Path(config);self.seed_profile=Path(seed_profile);self.lock=threading.RLock();self.work=threading.Lock();self.stop=threading.Event();self.wake=threading.Event();self.thread=None
        if not self.config.is_absolute() or self.config.resolve()!=self.config:raise ValueError('invalid library config')
        if self.config.exists():self.settings()
    def settings(self):
        data=json.loads(self.config.read_bytes())
        if set(data)!={'schema','root','auto_archive'} or data['schema']!=SCHEMA or type(data['auto_archive']) is not bool:raise ValueError('invalid library settings')
        root_path(data['root']);return data
    def current_profile(self):
        with self.lock:
            if not self.config.exists():return self.seed_profile
            root=root_path(self.settings()['root'])
            with open_db(root) as db:row=db.execute("SELECT value FROM metadata WHERE key='profile'").fetchone()
            return Path(row[0]) if row else self.seed_profile
    def queries(self):
        p=json.loads(self.current_profile().read_bytes());a=ArchiveQuery(Path(p['archive_index']),p['archive_sha256'])
        return a,DetailQuery(Path(p['database']),a,Path(p['evidence_catalog']),p['evidence_sha256'])
    def configure(self,body):
        if not isinstance(body,dict) or set(body)!={'root','auto_archive'} or type(body['auto_archive']) is not bool or not isinstance(body['root'],str):raise ValueError('invalid settings')
        root=root_path(body['root'])
        with self.lock:
            old=self.current_profile() if self.config.exists() else self.seed_profile
            root.mkdir(parents=True,exist_ok=True,mode=0o700)
            for name in ('incoming','imports'):
                p=root/name
                if p.resolve()!=p or p.is_symlink():raise ValueError('linked library path')
                p.mkdir(exist_ok=True,mode=0o700)
            with open_db(root,True) as db:db.execute("INSERT OR IGNORE INTO metadata VALUES('profile',?)",(str(old),))
            self.config.parent.mkdir(parents=True,exist_ok=True)
            tmp=self.config.with_name(self.config.name+'.'+os.urandom(8).hex()+'.tmp')
            with tmp.open('xb') as f:f.write(canonical(dict(schema=SCHEMA,**body)));f.flush();os.fsync(f.fileno())
            os.replace(tmp,self.config)
        if body['auto_archive']:self.wake.set()
        return self.status()
    def status(self):
        with self.lock:
            if not self.config.exists():return dict(schema=SCHEMA,configured=False,root='',incoming='',auto_archive=False,jobs=[],worker_scope='while-workbench-running',checkpoint_policy='not-copied',receipt_required=True)
            s=self.settings();root=root_path(s['root'])
            with open_db(root) as db:jobs=[dict(r) for r in db.execute('SELECT id,state,updated_at,error FROM ingestions ORDER BY updated_at DESC LIMIT 50')]
            return dict(schema=SCHEMA,profile_revision=sha256(str(self.current_profile()).encode()).hexdigest(),configured=True,root=str(root),incoming=str(root/'incoming'),auto_archive=s['auto_archive'],jobs=jobs,worker_scope='while-workbench-running',checkpoint_policy='not-copied',receipt_required=True)
    def retry(self,identity):
        if not re.fullmatch('[0-9a-f]{64}',identity):raise ValueError('invalid receipt')
        root=root_path(self.settings()['root'])
        with open_db(root,True) as db:
            row=db.execute('SELECT state FROM ingestions WHERE id=?',(identity,)).fetchone()
            if not row or row[0]!='failed':raise ValueError('only failed archive can retry')
            db.execute("UPDATE ingestions SET state='queued',error=NULL,updated_at=? WHERE id=?",(now(),identity))
        self.wake.set();return self.status()
    def run_once(self):
        if not self.work.acquire(blocking=False):return
        try:
            s=self.settings();root=root_path(s['root']);incoming=root/'incoming'
            # Only complete, explicitly produced receipts enter the queue.
            for p in sorted(incoming.glob('*.ready.json')):
                identity=p.name.removesuffix('.ready.json')
                if not re.fullmatch('[0-9a-f]{64}',identity):continue
                with open_db(root,True) as db:db.execute('INSERT OR IGNORE INTO ingestions VALUES(?,?,?,?,?)',(identity,'queued',now(),None,None))
            with open_db(root) as db:row=db.execute("SELECT id FROM ingestions WHERE state='queued' ORDER BY updated_at LIMIT 1").fetchone()
            if not row:return
            identity=row[0]
            with open_db(root,True) as db:db.execute("UPDATE ingestions SET state='importing',updated_at=? WHERE id=?",(now(),identity))
            try:
                receipt=json.loads(stable_bytes(incoming/(identity+'.ready.json'),LIMIT)[0])
                if set(receipt)!={'schema','files','source','completion'} or receipt['schema']!='autog-completed-local-fetch/1' or receipt['completion']!='local-transfer-complete':raise ValueError('invalid receipt')
                files=receipt['files']
                if not isinstance(files,list) or not 1<=len(files)<=5000 or sha256(canonical(files)).hexdigest()!=identity:raise ValueError('receipt identity mismatch')
                source=incoming/'captures'/identity
                allowed=set()
                for ref in files:
                    if set(ref)!={'relative_path','sha256','size_bytes'}:raise ValueError('invalid captured file')
                    relative=Path(ref['relative_path'])
                    if relative.is_absolute() or '..' in relative.parts or str(relative)!=ref['relative_path'] or relative in allowed:raise ValueError('invalid captured path')
                    allowed.add(relative);raw,_=stable_bytes(source/relative,32*1024*1024)
                    if len(raw)!=ref['size_bytes'] or sha256(raw).hexdigest()!=ref['sha256']:raise ValueError('captured bytes changed')
                actual={p.relative_to(source) for p in source.rglob('*') if p.is_file() or p.is_symlink()}
                if actual!=allowed:raise ValueError('unexpected captured file')
                dest=root/'imports'/('receipt-'+identity)
                if dest.resolve()!=dest:raise ValueError('linked archive destination')
                previous=self.current_profile()
                if not dest.exists():
                    result=import_folder(source,dest,previous)
                    if result['failures']:raise ValueError('some local files failed archive; inspect batch report')
                report=json.loads((dest/'import-report.json').read_bytes())
                if report['failures'] or report['source']!=str(source):raise ValueError('incomplete or mismatched archive batch')
                profile=dest/'profile.json';p=json.loads(profile.read_bytes())
                a=ArchiveQuery(Path(p['archive_index']),p['archive_sha256']);a.list_archives()
                catalog=json.loads(read_pinned(Path(p['evidence_catalog']),p['evidence_sha256']))
                from .details import document
                for e in catalog['entries']:
                    for k in ('log','parse_outcome','vibrations','history_links','conditions','input_conditions','browse','workflow','analysis'):
                        if k in e:document(e[k],limit=32*1024*1024)
                with open_db(root,True) as db:
                    # Settings can change during parsing; publish only in the captured root.
                    db.execute("INSERT OR REPLACE INTO metadata VALUES('profile',?)",(str(profile),))
                    db.execute("UPDATE ingestions SET state='archived',updated_at=?,profile=?,error=NULL WHERE id=?",(now(),str(profile),identity))
            except Exception as e:
                with open_db(root,True) as db:db.execute("UPDATE ingestions SET state='failed',updated_at=?,error=? WHERE id=?",(now(),type(e).__name__+': '+str(e)[:240],identity))
        finally:self.work.release()
    def start(self):
        if self.config.exists():
            root=root_path(self.settings()['root'])
            with open_db(root,True) as db:db.execute("UPDATE ingestions SET state='failed',error='Previous local import interrupted; explicit retry available' WHERE state='importing'")
        def loop():
            while not self.stop.is_set():
                forced=self.wake.wait(3);self.wake.clear()
                if self.stop.is_set():break
                try:
                    if forced or self.settings()['auto_archive']:self.run_once()
                except Exception:pass  # status/config remains inspectable; no scientific or remote retry.
        self.thread=threading.Thread(target=loop,daemon=True);self.thread.start()
    def close(self):self.stop.set();self.wake.set()

class LiveArchives:
    def __init__(self,manager):self.manager=manager
    def list_archives(self):return self.manager.queries()[0].list_archives()
    def get_archive(self,identity):return self.manager.queries()[0].get_archive(identity)
class LiveDetails:
    def __init__(self,manager):self.manager=manager
    def execution_source(self,*args):return self.manager.queries()[1].execution_source(*args)
    def get_details(self,*args):return self.manager.queries()[1].get_details(*args)
    def get_log(self,*args):return self.manager.queries()[1].get_log(*args)
    def get_vibrations(self,*args):return self.manager.queries()[1].get_vibrations(*args)
    def get_workflow(self,*args):return self.manager.queries()[1].get_workflow(*args)
    def get_conditions(self,*args):return self.manager.queries()[1].get_conditions(*args)
    def get_history_links(self,*args):return self.manager.queries()[1].get_history_links(*args)
    def log_window(self,*args,**kwargs):
        from .log_window import read_window
        return read_window(self.manager.queries()[1],*args,**kwargs)

def capture_completed(source,config):
    """Call ONLY after the local result-transfer stage succeeds. Never fetch remotely."""
    source=root_path(str(source));settings=json.loads(Path(config).read_bytes());root=root_path(settings['root']);files=[]
    if source==root or source in root.parents or source==root/'incoming' or source==root/'incoming'/'captures' or root/'incoming'/'captures' in source.parents:raise ValueError('source overlaps library capture storage')
    for base,dirs,names in os.walk(source,followlinks=False):
        dirs[:]=sorted(d for d in dirs if not (Path(base)/d).is_symlink())
        for name in sorted(names):
            p=Path(base)/name
            if p.is_symlink() or p.suffix.lower() not in SMALL_SUFFIXES|{'.log','.out'}:continue
            raw,_=stable_bytes(p,32*1024*1024)
            if not raw:continue
            if len(files)>=5000:raise ValueError('too many files')
            files.append(dict(relative_path=str(p.relative_to(source)),sha256=sha256(raw).hexdigest(),size_bytes=len(raw)))
    if not files or len(files)>5000:raise ValueError('no eligible files or too many')
    identity=sha256(canonical(files)).hexdigest();dest=root/'incoming'/'captures'/identity
    receipt=root/'incoming'/(identity+'.ready.json')
    if source==root or source in root.parents or source==root/'incoming' or source==root/'incoming'/'captures' or root/'incoming'/'captures' in source.parents:raise ValueError('source overlaps library capture storage')
    if dest.resolve()!=dest:raise ValueError('linked capture target')
    dest.mkdir(parents=True,exist_ok=True)
    for ref in files:
        relative=Path(ref['relative_path']);raw,_=stable_bytes(source/relative,32*1024*1024)
        if sha256(raw).hexdigest()!=ref['sha256']:raise ValueError('source changed during capture')
        out=dest/relative;out.parent.mkdir(parents=True,exist_ok=True)
        if out.resolve()!=out:raise ValueError('linked capture destination')
        if out.exists():
            if stable_bytes(out,32*1024*1024)[0]!=raw:raise ValueError('capture collision')
        else:
            with out.open('xb') as f:f.write(raw)
    actual={str(p.relative_to(source)) for p in source.rglob('*') if p.is_file() and not p.is_symlink() and p.suffix.lower() in SMALL_SUFFIXES|{'.log','.out'} and p.stat().st_size>0}
    if actual!={ref['relative_path'] for ref in files}:raise ValueError('source file set changed during capture')
    payload=canonical(dict(schema='autog-completed-local-fetch/1',files=files,source=str(source),completion='local-transfer-complete'))
    if receipt.exists():
        existing=json.loads(stable_bytes(receipt,LIMIT)[0])
        if existing.get('files')!=files or existing.get('completion')!='local-transfer-complete' or existing.get('schema')!='autog-completed-local-fetch/1':raise ValueError('receipt collision')
        return identity
    tmp=receipt.with_suffix('.'+os.urandom(8).hex()+'.pending')
    with tmp.open('xb') as f:f.write(payload);f.flush();os.fsync(f.fileno())
    os.link(tmp,receipt)  # publish without replacing a pre-existing receipt
    tmp.unlink()
    return identity

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser(description='Post-transfer local archive receipt; no remote or calculation actions')
    p.add_argument('--completed-fetch',type=Path,required=True);p.add_argument('--library-config',type=Path,required=True)
    a=p.parse_args();print(capture_completed(a.completed_fetch,a.library_config))
