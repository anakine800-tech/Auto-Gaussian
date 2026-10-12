"""Existing-only Approval persistence; synthetic stores and local processes only."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading
import unittest
from unittest.mock import patch

from auto_g16.approval import store as owner
from . import test_store as fixtures


class ExistingApprovalTests(unittest.TestCase):

    def test_binding_exact_immutable_and_no_new_database_resources(self):
        before=self.path.read_bytes()
        with self.open() as store:
            guard=store._existing_mutable_guard
            expected=dict(path=str(self.path),parent_chain=tuple(guard.identities[:-1]),
                          file_identity=guard.identities[-1],native_identity=None)
            from contextlib import nullcontext
            with nullcontext():
                with patch.object(os,'open',side_effect=AssertionError('new FD')), \
                        patch.object(sqlite3,'connect',side_effect=AssertionError('new SQLite')):
                    result=store.assert_existing_binding()
                self.assertEqual(dict(result),expected)
                with self.assertRaises(TypeError):result['path']='changed'
                if result['native_identity'] is not None:
                    with self.assertRaises(TypeError):result['native_identity']['other']='changed'
                with self.assertRaises(TypeError):store.assert_existing_binding('argument')
            self.assertFalse(store._connection.in_transaction)
        self.assertEqual(before,self.path.read_bytes())

    def test_binding_active_transaction_preserves_lock_and_handle(self):
        with self.open() as store:
            connection=store._connection
            connection.execute('BEGIN IMMEDIATE').close()
            try:
                with patch.object(os,'open',side_effect=AssertionError('new FD')), \
                        patch.object(sqlite3,'connect',side_effect=AssertionError('new SQLite')):
                    with self.assertRaises(owner.ApprovalStoreError):store.assert_existing_binding()
                self.assertTrue(connection.in_transaction)
                self.assertFalse(store._existing_mutable_guard.poisoned)
                pid=os.fork()
                if pid==0:
                    class Forbidden:
                        def __getattribute__(self,name):raise AssertionError('inherited SQLite access')
                    store._connection=Forbidden()
                    try:store.assert_existing_binding()
                    except owner.ApprovalStoreError:os._exit(0)
                    except BaseException:os._exit(2)
                    os._exit(3)
                self.assertEqual(os.waitpid(pid,0)[1],0)
                self.assertTrue(connection.in_transaction)
                script="import sqlite3,sys;c=sqlite3.connect(sys.argv[1],timeout=0);\ntry:c.execute('BEGIN IMMEDIATE')\nexcept sqlite3.OperationalError:sys.exit(0)\nelse:sys.exit(3)"
                child=subprocess.run([sys.executable,'-c',script,str(self.path)],capture_output=True,text=True,timeout=10)
                self.assertEqual(child.returncode,0,child.stderr)
            finally:connection.execute('ROLLBACK').close()
            store.assert_existing_binding()

    def test_binding_wrong_thread_pid_and_closed_reject_before_sqlite(self):
        class Forbidden:
            def __getattribute__(self,name):raise AssertionError('SQLite touched '+name)
        with self.open() as store:
            connection=store._connection
            store._connection=Forbidden()
            errors=[]
            def other():
                try:store.assert_existing_binding()
                except BaseException as error:errors.append(error)
            thread=threading.Thread(target=other);thread.start();thread.join(5)
            self.assertFalse(thread.is_alive())
            self.assertEqual(len(errors),1);self.assertIsInstance(errors[0],owner.ApprovalStoreError)
            try:
                with patch.object(os,'getpid',return_value=-1):
                    with self.assertRaises(owner.ApprovalStoreError):store.assert_existing_binding()
                store._closed=True
                with self.assertRaises(owner.ApprovalStoreError):store.assert_existing_binding()
            finally:store._connection=connection;store._closed=False
            store.assert_existing_binding()
        store._connection=Forbidden()
        with self.assertRaises(owner.ApprovalStoreError):store.assert_existing_binding()
        legacy=object.__new__(owner.SQLiteApprovalStore)
        legacy._connection=Forbidden()
        with self.assertRaises(owner.ApprovalStoreError):legacy.assert_existing_binding()

    def test_binding_attached_database_and_replaced_connection_reject(self):
        for mode in ('attached','replaced'):
            with self.subTest(mode=mode),self.assertRaises(owner.ApprovalStoreError):
                with self.open() as store:
                    original=store._connection
                    if mode=='attached':
                        original.execute("ATTACH DATABASE ':memory:' AS other").close()
                        try:
                            with self.assertRaises(owner.ApprovalStoreError):store.assert_existing_binding()
                        finally:original.execute('DETACH DATABASE other').close()
                    else:
                        substitute=sqlite3.connect(':memory:',isolation_level=None)
                        store._connection=substitute
                        try:
                            with self.assertRaises(owner.ApprovalStoreError):store.assert_existing_binding()
                        finally:store._connection=original;substitute.close()
                    self.assertTrue(store._existing_mutable_guard.poisoned)

    def test_binding_sidecar_rejection_is_permanent(self):
        side=Path(str(self.path)+'-wal')
        with self.assertRaises(owner.ApprovalStoreError):
            with self.open() as store:
                side.write_bytes(b'synthetic sidecar')
                try:
                    with self.assertRaises(owner.ApprovalStoreError):store.assert_existing_binding()
                finally:side.unlink()
                with self.assertRaises(owner.ApprovalStoreError):store.assert_existing_binding()

    def test_binding_file_and_ancestor_drift_preserves_original(self):
        for kind in ('file','ancestor'):
            before=self.path.read_bytes()
            with self.subTest(kind=kind),self.assertRaises(owner.ApprovalStoreError):
                with self.open() as store:
                    if kind=='file':
                        saved=self.root/'retained-original';self.path.rename(saved)
                        self.path.write_bytes(b'replacement')
                    else:
                        saved=self.root.with_name(self.root.name+'-retained')
                        self.root.rename(saved);self.root.mkdir();self.path.write_bytes(b'replacement')
                    try:
                        with self.assertRaises(owner.ApprovalStoreError):store.assert_existing_binding()
                        self.assertEqual(self.path.read_bytes(),b'replacement')
                    finally:
                        self.path.unlink()  # Only synthetic test replacement.
                        if kind=='file':saved.rename(self.path)
                        else:self.root.rmdir();saved.rename(self.root)
                    with self.assertRaises(owner.ApprovalStoreError):store.assert_existing_binding()
            self.assertEqual(before,self.path.read_bytes())

    def setUp(self):
        fixtures.ApprovalStoreTests.setUp(self)
        self.path = self.root / 'approval.sqlite3'
        with owner.SQLiteApprovalStore(self.path):
            pass
        st = self.path.stat()
        self.identity = (st.st_dev, st.st_ino)

    def open(self, path=None, root=None, identity=None):
        return owner.SQLiteApprovalStore.open_existing_mutable(
            self.path if path is None else path, approved_root=self.root if root is None else root,
            expected_file_identity=self.identity if identity is None else identity)

    def inventory(self):
        return {p.name: p.read_bytes() for p in self.root.glob('approval.sqlite3*')}

    def test_three_domains_real_process_replay_without_creation_or_core_effect(self):
        rows = [(self.science, 'scientific_approval', 'scientific_approval_id'),
                (self.batch, 'batch_submit_approval', 'batch_submit_approval_id'),
                (self.confirmation, 'operational_confirmation', 'operational_confirmation_id')]
        core_before = (self.root/'runtime.sqlite3').read_bytes()
        with patch.object(owner.SQLiteApprovalStore, '__init__', side_effect=AssertionError('constructor')), \
                patch.object(owner.SQLiteApprovalStore, '_reserve_new_file', side_effect=AssertionError('reserve')), \
                patch.object(owner.SQLiteApprovalStore, '_initialize_reserved_database', side_effect=AssertionError('init')):
            with self.open() as store:
                self.assertEqual(store.evidence_count(), 0)
                for record, domain, field in rows:
                    getattr(store, 'store_'+domain)(record)
                    self.assertEqual(getattr(store, 'load_'+domain)(getattr(record, field)), record)
                self.assertEqual(store.load_current_operational_confirmation(
                    self.confirmation.operational_confirmation_id, self.current_snapshot), self.confirmation)
        before = self.inventory()
        script = '''import json,sys
from pathlib import Path
from auto_g16.approval import SQLiteApprovalStore
p=Path(sys.argv[1]);st=p.stat()
with SQLiteApprovalStore.open_existing_mutable(p,approved_root=p.parent,expected_file_identity=(st.st_dev,st.st_ino)) as store:
 for domain,identity in json.loads(sys.argv[2]):
  record=getattr(store,'load_'+domain)(identity)
  getattr(store,'store_'+domain)(record)
 print(store.evidence_count())
'''
        child = subprocess.run([sys.executable, '-B', '-c', script, str(self.path),
            json.dumps([(domain, getattr(record, field)) for record, domain, field in rows])],
            cwd=Path(__file__).resolve().parents[3], capture_output=True, text=True, timeout=30)
        self.assertEqual(child.returncode, 0, child.stderr)
        self.assertEqual(child.stdout.strip(), '3')
        self.assertEqual(before, self.inventory())
        self.assertEqual(core_before, (self.root/'runtime.sqlite3').read_bytes())
        self.assertIsNone(self.runtime.load_submission_intent('attempt-1'))

    def test_missing_empty_foreign_headers_schema_and_bad_rows_stay_unchanged(self):
        missing = self.root/'absent.sqlite3'
        with self.assertRaises(FileNotFoundError), self.open(missing): pass
        self.assertFalse(missing.exists())
        original = self.path.read_bytes()
        for mode in ('empty', 'foreign', 'application', 'version', 'extra', 'record'):
            with self.subTest(mode=mode):
                self.path.write_bytes(original)
                if mode == 'empty': self.path.write_bytes(b'')
                elif mode == 'foreign': self.path.write_bytes(b'not sqlite')
                else:
                    with sqlite3.connect(self.path) as c:
                        if mode == 'application': c.execute('PRAGMA application_id=0')
                        if mode == 'version': c.execute('PRAGMA user_version=0')
                        if mode == 'extra': c.execute('CREATE TABLE unexpected(value)')
                        if mode == 'record': c.execute("INSERT INTO approval_evidence VALUES('bad','scientific-approval','{}')")
                before = self.inventory()
                with self.assertRaises(owner.ApprovalStoreError), self.open(): pass
                self.assertEqual(before, self.inventory())

    def test_canonical_containment_aliases_hardlinks_and_exact_integer_identity(self):
        alias = self.root/'alias.sqlite3';alias.symlink_to(self.path)
        directory = self.root/'alias-dir';directory.symlink_to(self.root, target_is_directory=True)
        for path in (b'/unsupported-bytes-path', ':memory:', 'approval.sqlite3', self.path.as_uri()+'?mode=rw',
                     str(self.root)+'/./approval.sqlite3', alias, directory/'approval.sqlite3'):
            with self.subTest(path=path), self.assertRaises(owner.ApprovalStoreError), self.open(path): pass
        for identity in ((True, self.identity[1]), (self.identity[0], False),
                         (self.identity[0], self.identity[1]+1), list(self.identity)):
            with self.subTest(identity=identity), self.assertRaises(owner.ApprovalStoreError), self.open(identity=identity): pass
        with self.assertRaises(owner.ApprovalStoreError), self.open(root=self.root/'other'): pass
        os.link(self.path, self.root/'hard.sqlite3')
        with self.assertRaises(owner.ApprovalStoreError), self.open(): pass

    def test_all_sidecars_including_empty_reject_before_any_sqlite_open(self):
        for suffix in ('-journal', '-wal', '-shm'):
            side = Path(str(self.path)+suffix)
            for raw in (b'', b'synthetic'):
                side.write_bytes(raw);before=self.inventory()
                with patch.object(sqlite3, 'connect', side_effect=AssertionError('must not open')):
                    with self.assertRaises(owner.ApprovalStoreError), self.open(): pass
                self.assertEqual(before, self.inventory())
            side.unlink()  # Disposable synthetic sidecar only.

    def test_real_hot_journal_retained_without_recovery(self):
        with sqlite3.connect(self.path) as c:
            c.execute('CREATE TABLE hot_fixture(value BLOB)')
            c.executemany('INSERT INTO hot_fixture VALUES(?)', [(b'a'*4096,)]*80)
        subprocess.run([sys.executable, '-I', '-B', '-c',
            "import sqlite3,os,sys;c=sqlite3.connect(sys.argv[1]);c.execute('PRAGMA cache_size=1');"
            "c.execute('BEGIN IMMEDIATE');c.execute('UPDATE hot_fixture SET value=zeroblob(4096)');os._exit(0)",
            str(self.path)], check=True, timeout=30)
        self.assertEqual(Path(str(self.path)+'-journal').read_bytes()[:8], bytes.fromhex('d9d505f920a163d7'))
        before=self.inventory()
        with patch.object(sqlite3, 'connect', side_effect=AssertionError('no recovery')):
            with self.assertRaises(owner.ApprovalStoreError), self.open(): pass
        self.assertEqual(before, self.inventory())

    def test_startup_validates_readonly_then_query_only_writer_and_all_rows(self):
        calls=[];original=sqlite3.connect
        def tracked(database,*args,**kwargs):
            c=original(database,*args,**kwargs); statements=[]
            calls.append((str(database),statements));c.set_trace_callback(statements.append);return c
        with patch.object(sqlite3,'connect',side_effect=tracked):
            with self.open() as store:self.assertEqual(store.evidence_count(),0)
        self.assertEqual(len(calls),2)
        for i,(path,statements) in enumerate(calls):
            self.assertIn('?mode='+('ro' if i==0 else 'rw')+'&cache=private',path)
            self.assertLess(statements.index('PRAGMA query_only=ON'),statements.index('PRAGMA main.integrity_check'))
            self.assertTrue(any('SELECT evidence_id,evidence_kind,payload_json' in x for x in statements))
            self.assertFalse(any(x.upper().startswith(('CREATE ','INSERT ','UPDATE ','DELETE ')) for x in statements))
        self.assertLess(calls[1][1].index('PRAGMA main.integrity_check'),calls[1][1].index('PRAGMA query_only=OFF'))

    def test_precommit_replacement_rolls_back_original(self):
        retained=self.root/'retained.sqlite3'
        with self.assertRaises(owner.ApprovalStoreError),self.open() as store:
            with store._transaction(immediate=True) as c:
                c.execute('INSERT INTO approval_evidence VALUES(?,?,?)',
                    (self.science.scientific_approval_id,'scientific-approval',owner._payload_text(self.science)))
                self.path.rename(retained);self.path.write_bytes(b'replacement retained')
        self.assertEqual(self.path.read_bytes(),b'replacement retained')
        with sqlite3.connect(retained) as c:self.assertEqual(c.execute('SELECT count(*) FROM approval_evidence').fetchone()[0],0)

    def test_failed_guard_cannot_revive_and_committed_fact_survives(self):
        for mode in ('rename','sidecar'):
            with self.subTest(mode=mode):
                with self.assertRaises(owner.ApprovalStoreError),self.open() as store:
                    guard=store._existing_mutable_guard
                    store.store_scientific_approval(self.science)
                    moved=self.root/'moved.sqlite3';side=Path(str(self.path)+'-journal')
                    if mode=='rename':self.path.rename(moved)
                    else:side.write_bytes(b'synthetic')
                    try:
                        with self.assertRaises((owner.ApprovalStoreError,FileNotFoundError)):store.evidence_count()
                    finally:
                        if mode=='rename':moved.rename(self.path)
                        else:side.unlink()  # Disposable fixture only.
                    with self.assertRaisesRegex(owner.ApprovalStoreError,'permanently invalid'):store.evidence_count()
                self.assertEqual(guard.fds,[])
                with self.open() as store:self.assertEqual(store.evidence_count(),1)

    def test_ancestor_replacement_poisoned_before_native_write(self):
        moved=self.root.with_name(self.root.name+'-moved')
        try:
            with self.assertRaises((owner.ApprovalStoreError,FileNotFoundError)),self.open() as store:
                self.root.rename(moved);self.root.mkdir()
                store.store_scientific_approval(self.science)
        finally:
            if moved.exists():
                self.root.rmdir()  # Empty synthetic replacement only.
                moved.rename(self.root)
        with self.open() as store:self.assertEqual(store.evidence_count(),0)

    def test_keyboard_interrupt_rolls_back_and_system_exit_keeps_prior_commit(self):
        with self.assertRaises(KeyboardInterrupt),self.open() as store:
            guard=store._existing_mutable_guard
            with store._transaction(immediate=True) as c:
                c.execute('INSERT INTO approval_evidence VALUES(?,?,?)',
                    (self.science.scientific_approval_id,'scientific-approval',owner._payload_text(self.science)))
                raise KeyboardInterrupt()
        self.assertEqual(guard.fds,[])
        with self.open() as store:self.assertEqual(store.evidence_count(),0)
        with self.assertRaises(SystemExit),self.open() as store:
            guard=store._existing_mutable_guard
            store.store_scientific_approval(self.science)
            raise SystemExit(74)
        self.assertEqual(guard.fds,[])
        with self.open() as store:self.assertEqual(store.evidence_count(),1)

    def test_after_commit_identity_failure_keeps_committed_approval(self):
        retained=self.root/'committed.sqlite3'
        with self.assertRaises(owner.ApprovalStoreError),self.open() as store:
            guard=store._existing_mutable_guard;original=guard.check
            statements=[];store._connection.set_trace_callback(statements.append)
            armed=True
            def replace_after_commit(*,idle=False):
                nonlocal armed
                if armed and idle and statements and statements[-1]=='COMMIT':
                    armed=False
                    self.path.rename(retained);self.path.write_bytes(b'replacement retained')
                original(idle=idle)
            with patch.object(guard,'check',side_effect=replace_after_commit):
                store.store_scientific_approval(self.science)
        self.assertEqual(self.path.read_bytes(),b'replacement retained')
        st=retained.stat()
        with owner.SQLiteApprovalStore.open_existing_mutable(retained,
                approved_root=self.root,expected_file_identity=(st.st_dev,st.st_ino)) as store:
            self.assertEqual(store.load_scientific_approval(self.science.scientific_approval_id),self.science)

    def test_replacement_between_preflight_and_writer_connect_is_rejected_unchanged(self):
        connect=sqlite3.connect;retained=self.root/'original.sqlite3'
        def replaced(database,*args,**kwargs):
            if '?mode=rw&' in str(database):
                self.path.rename(retained);self.path.write_bytes(b'')
            return connect(database,*args,**kwargs)
        with patch.object(sqlite3,'connect',side_effect=replaced):
            with self.assertRaises(owner.ApprovalStoreError),self.open():pass
        self.assertEqual(self.path.read_bytes(),b'')
        self.assertEqual(set(self.inventory()),{'approval.sqlite3'})

    def test_native_begin_and_commit_interruptions_clean_up_before_caller_catches(self):
        original_bytes=self.path.read_bytes()
        for statement,after in (('BEGIN IMMEDIATE',True),('COMMIT',False),('COMMIT',True)):
            with self.subTest(statement=statement,after=after):
                self.path.write_bytes(original_bytes)
                with self.open() as store:
                    connection=store._connection
                    class InterruptedConnection:
                        armed=True
                        def __getattr__(self,name):return getattr(connection,name)
                        def execute(self,sql,*args):
                            if self.armed and sql==statement:
                                self.armed=False
                                if after:connection.execute(sql,*args)
                                raise KeyboardInterrupt('synthetic transaction interruption')
                            return connection.execute(sql,*args)
                    store._connection=InterruptedConnection()
                    with self.assertRaises(KeyboardInterrupt):store.store_scientific_approval(self.science)
                    self.assertFalse(connection.in_transaction)
                    self.assertFalse(Path(str(self.path)+'-journal').exists())
                    store._connection=connection
                    self.assertEqual(store.evidence_count(),int(statement=='COMMIT' and after))

    def test_descriptor_stays_open_until_sqlite_closes(self):
        with self.open() as store:
            target=store._existing_mutable_guard.fds[-1];original=os.close
            def protected(fd):
                if fd==target:raise AssertionError('closed active database descriptor')
                return original(fd)
            with patch.object(os,'close',side_effect=protected):
                store.store_scientific_approval(self.science)
                self.assertEqual(store.evidence_count(),1)
        self.assertTrue(store._closed)
        self.assertEqual(store._existing_mutable_guard.fds,[])
        with self.assertRaises(owner.ApprovalStoreError):store.evidence_count()

    def test_unknown_close_and_rollback_retained_in_real_processes(self):
        script = r"""
import importlib, os, sqlite3, sys, tempfile
from pathlib import Path
from unittest.mock import patch
owner=importlib.import_module('auto_g16.'+sys.argv[1]+'.store')
cls=getattr(owner, 'SQLiteRuntimeStore' if sys.argv[1]=='core' else 'SQLiteApprovalStore')
mode=sys.argv[2]; root=Path(tempfile.mkdtemp()).resolve(); p=root/'owner.sqlite3'
with cls(p): pass
identity=(p.stat().st_dev,p.stat().st_ino); real=sqlite3.connect; calls=[]; guards=[]
original=owner._ExistingMutableGuard.__init__
def remember(self,*args,**kwargs):
 original(self,*args,**kwargs);guards.append(self)
class Fault(sqlite3.Connection):
 def close(self):
  calls.append('close')
  if mode=='close-after': super().close()
  if mode!='rollback': raise OSError('private close detail')
  return super().close()
 def execute(self,sql,*args,**kwargs):
  if mode=='rollback' and sql=='ROLLBACK':raise OSError('private rollback detail')
  return super().execute(sql,*args,**kwargs)
def connect(*args,**kwargs):
 if ('mode=ro' if mode=='startup' else 'mode=rw') in str(args[0]):kwargs['factory']=Fault
 return real(*args,**kwargs)
def opened():return cls.open_existing_mutable(p,approved_root=root,expected_file_identity=identity)
try:
 with patch.object(owner._ExistingMutableGuard,'__init__',remember), patch.object(owner.sqlite3,'connect',connect):
  with opened() as store:
   if mode=='rollback':
    with store._transaction(**({'immediate':True} if sys.argv[1]=='approval' else {})):
     raise KeyboardInterrupt('original body')
   if mode=='body':raise KeyboardInterrupt('original body')
except BaseException as error:
 if mode in ('body','rollback'):
  assert type(error) is KeyboardInterrupt,repr(error)
  assert 'private' not in str(getattr(error,'__notes__',[]))
 else:assert type(error) is OSError,repr(error)
else:raise AssertionError('fault was lost')
guard=guards[0];assert guard.unresolved and guard.poisoned
assert guard.fds and all(os.fstat(fd) for fd in guard.fds)
assert owner._UNRESOLVED_EXISTING[(os.getpid(),*identity)] is guard
assert len(calls)==(0 if mode=='rollback' else 1),calls
for value in guard.stores:
 try:value.close()
 except Exception:pass
 else:raise AssertionError('quarantined close accepted')
with patch.object(owner.os,'open',side_effect=AssertionError('target FD reopened')),patch.object(owner.sqlite3,'connect',side_effect=AssertionError('SQLite reopened')):
 try:
  with opened():pass
 except (owner.RuntimeStoreError if sys.argv[1]=='core' else owner.ApprovalStoreError):pass
 else:raise AssertionError('quarantined inode reopened')
assert len(calls)==(0 if mode=='rollback' else 1)
print('retained; no retry')
"""
        for mode in ('close-before', 'close-after', 'body', 'startup', 'rollback'):
            with self.subTest(mode=mode):
                result = subprocess.run([sys.executable, '-B', '-c', script, 'approval', mode],
                    cwd=Path(__file__).resolve().parents[3], capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), 'retained; no retry')

    def test_fork_context_unwind_never_touches_inherited_sqlite(self):
        script = r"""
import importlib, os, sqlite3, sys, tempfile, subprocess
from pathlib import Path
owner=importlib.import_module('auto_g16.'+sys.argv[1]+'.store')
cls=getattr(owner,'SQLiteRuntimeStore' if sys.argv[1]=='core' else 'SQLiteApprovalStore')
root=Path(tempfile.mkdtemp()).resolve();p=root/'owner.sqlite3'
with cls(p):pass
identity=(p.stat().st_dev,p.stat().st_ino);original_pid=os.getpid(); touched=root/'touched'
class Forbidden:
 def __getattribute__(self,name):
  touched.write_text(name);raise AssertionError('child accessed SQLite')
try:
 with cls.open_existing_mutable(p,approved_root=root,expected_file_identity=identity) as store:
  with store._transaction(**({'immediate':True} if sys.argv[1]=='approval' else {})):
   child=os.fork()
   if child==0:
    store._connection=Forbidden()
    raise KeyboardInterrupt('child unwind')
   _,status=os.waitpid(child,0);assert os.waitstatus_to_exitcode(status)==0
   assert not touched.exists()
   # Another process cannot write until parent commits, including after child exit.
   code="import sqlite3,sys;c=sqlite3.connect(sys.argv[1],timeout=0);\ntry:c.execute('BEGIN IMMEDIATE')\nexcept sqlite3.OperationalError:sys.exit(0)\nsys.exit(1)"
   assert subprocess.run([sys.executable,'-c',code,str(p)]).returncode==0
  assert not store._connection.in_transaction
except KeyboardInterrupt:
 if os.getpid()!=original_pid:
  guard=store._existing_mutable_guard
  assert guard.unresolved and guard.fds and not touched.exists()
  os._exit(0)
 raise
with sqlite3.connect(p,timeout=0) as connection:connection.execute('BEGIN IMMEDIATE');connection.rollback()
print('parent lock and commit retained')
"""
        result = subprocess.run([sys.executable, '-B', '-c', script, 'approval'],
            cwd=Path(__file__).resolve().parents[3], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'parent lock and commit retained')

    def test_preexisting_transaction_is_not_consumed(self):
        with self.open() as store:
            store._connection.execute('BEGIN IMMEDIATE')
            with self.assertRaises(owner.ApprovalStoreError):
                with store._transaction(immediate=True):pass
            self.assertTrue(store._connection.in_transaction)
            store._connection.execute('ROLLBACK')

    def test_fd_close_attempts_all_once_and_preserves_body(self):
        calls = []
        with self.assertRaisesRegex(KeyboardInterrupt, 'original body') as caught:
            with self.open() as store:
                guard=store._existing_mutable_guard
                descriptors=list(guard.fds); real_close=os.close
                def fault(fd):
                    calls.append(fd);real_close(fd)
                    raise OSError('private descriptor detail')
                with patch.object(owner.os, 'close', fault):
                    try:raise KeyboardInterrupt('original body')
                    finally:guard.finish(sys.exception())
        self.assertCountEqual(calls, descriptors)
        self.assertEqual(len(calls),len(set(calls)))
        self.assertEqual(guard.fds, [])
        self.assertNotIn('private descriptor',str(caught.exception.__notes__))

    def test_partial_pin_fstat_failure_closes_each_fd_once(self):
        opened, closed = [], []
        real_open, real_close = os.open, os.close
        def remember(*args, **kwargs):
            fd = real_open(*args, **kwargs)
            opened.append(fd)
            return fd
        def close(fd):
            closed.append(fd)
            real_close(fd)
            raise OSError('private close detail')
        with patch.object(owner.os, 'open', remember), patch.object(owner.os, 'close', close), \
                patch.object(owner.os, 'fstat', side_effect=KeyboardInterrupt('original fstat')):
            with self.assertRaisesRegex(KeyboardInterrupt, 'original fstat') as caught:
                with self.open():pass
        self.assertTrue(opened)
        self.assertCountEqual(closed, opened)
        self.assertEqual(len(closed), len(set(closed)))
        self.assertNotIn('private close detail', str(caught.exception.__notes__))
