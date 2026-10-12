"""Existing-only Core opening and real local crash/no-create boundaries."""
from pathlib import Path
import os
import sqlite3
import subprocess
import sys
import threading
import tempfile
import unittest
from unittest.mock import patch

from auto_g16.core import store as owner
from auto_g16.core import Project


class ExistingMutableTests(unittest.TestCase):

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
                    with self.assertRaises(owner.RuntimeStoreError):store.assert_existing_binding()
                self.assertTrue(connection.in_transaction)
                self.assertFalse(store._existing_mutable_guard.poisoned)
                pid=os.fork()
                if pid==0:
                    class Forbidden:
                        def __getattribute__(self,name):raise AssertionError('inherited SQLite access')
                    store._connection=Forbidden()
                    try:store.assert_existing_binding()
                    except owner.RuntimeStoreError:os._exit(0)
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
            self.assertEqual(len(errors),1);self.assertIsInstance(errors[0],owner.RuntimeStoreError)
            try:
                with patch.object(os,'getpid',return_value=-1):
                    with self.assertRaises(owner.RuntimeStoreError):store.assert_existing_binding()
                store._closed=True
                with self.assertRaises(owner.RuntimeStoreError):store.assert_existing_binding()
            finally:store._connection=connection;store._closed=False
            store.assert_existing_binding()
        store._connection=Forbidden()
        with self.assertRaises(owner.RuntimeStoreError):store.assert_existing_binding()
        legacy=object.__new__(owner.SQLiteRuntimeStore)
        legacy._connection=Forbidden()
        with self.assertRaises(owner.RuntimeStoreError):legacy.assert_existing_binding()

    def test_binding_attached_database_and_replaced_connection_reject(self):
        for mode in ('attached','replaced'):
            with self.subTest(mode=mode),self.assertRaises(owner.RuntimeStoreError):
                with self.open() as store:
                    original=store._connection
                    if mode=='attached':
                        original.execute("ATTACH DATABASE ':memory:' AS other").close()
                        try:
                            with self.assertRaises(owner.RuntimeStoreError):store.assert_existing_binding()
                        finally:original.execute('DETACH DATABASE other').close()
                    else:
                        substitute=sqlite3.connect(':memory:',isolation_level=None)
                        store._connection=substitute
                        try:
                            with self.assertRaises(owner.RuntimeStoreError):store.assert_existing_binding()
                        finally:store._connection=original;substitute.close()
                    self.assertTrue(store._existing_mutable_guard.poisoned)

    def test_binding_sidecar_rejection_is_permanent(self):
        side=Path(str(self.path)+'-wal')
        with self.assertRaises(owner.RuntimeStoreError):
            with self.open() as store:
                side.write_bytes(b'synthetic sidecar')
                try:
                    with self.assertRaises(owner.RuntimeStoreError):store.assert_existing_binding()
                finally:side.unlink()
                with self.assertRaises(owner.RuntimeStoreError):store.assert_existing_binding()

    def test_binding_file_and_ancestor_drift_preserves_original(self):
        for kind in ('file','ancestor'):
            before=self.path.read_bytes()
            with self.subTest(kind=kind),self.assertRaises(owner.RuntimeStoreError):
                with self.open() as store:
                    if kind=='file':
                        saved=self.root/'retained-original';self.path.rename(saved)
                        self.path.write_bytes(b'replacement')
                    else:
                        saved=self.root.with_name(self.root.name+'-retained')
                        self.root.rename(saved);self.root.mkdir();self.path.write_bytes(b'replacement')
                    try:
                        with self.assertRaises(owner.RuntimeStoreError):store.assert_existing_binding()
                        self.assertEqual(self.path.read_bytes(),b'replacement')
                    finally:
                        self.path.unlink()  # Only synthetic test replacement.
                        if kind=='file':saved.rename(self.path)
                        else:self.root.rmdir();saved.rename(self.root)
                    with self.assertRaises(owner.RuntimeStoreError):store.assert_existing_binding()
            self.assertEqual(before,self.path.read_bytes())

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.path = self.root / 'core.sqlite3'
        with owner.SQLiteRuntimeStore(self.path) as store:
            store.store_project(Project(project_id='existing'))
        st = self.path.stat()
        self.identity = (st.st_dev, st.st_ino)

    def open(self, path=None, root=None, identity=None):
        return owner.SQLiteRuntimeStore.open_existing_mutable(path or self.path,
            approved_root=root or self.root, expected_file_identity=identity or self.identity)

    def inventory(self):
        return {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}

    def test_existing_write_roundtrip_and_no_initialization(self):
        with patch.object(owner.SQLiteRuntimeStore, '_initialize_schema', side_effect=AssertionError('initialization')):
            with self.open() as store:
                self.assertEqual(store.load_project('existing').project_id, 'existing')
                self.assertEqual(store._connection.execute('PRAGMA query_only').fetchone()[0], 0)
                store.store_project(Project(project_id='new'))
                with self.assertRaises(owner.RuntimeStoreError):
                    store.export_memory_snapshot()
            with self.open() as store:
                self.assertEqual([p.project_id for p in store.list_projects()], ['existing', 'new'])
        self.assertEqual(set(self.inventory()), {'core.sqlite3'})

    def test_missing_empty_foreign_partial_extra_schema_and_fk_preserve_bytes(self):
        missing = self.root / 'missing.sqlite3'
        with self.assertRaises(FileNotFoundError), self.open(missing):
            pass
        self.assertFalse(missing.exists())
        original = self.path.read_bytes()
        for mode in ('empty', 'foreign', 'partial', 'extra', 'fk', 'unversioned'):
            with self.subTest(mode=mode):
                self.path.write_bytes(original)
                if mode == 'empty':
                    self.path.write_bytes(b'')
                elif mode == 'foreign':
                    self.path.write_bytes(b'not sqlite')
                else:
                    with sqlite3.connect(self.path) as c:
                        if mode == 'partial': c.execute('DROP TABLE recovery_proposals')
                        if mode == 'extra': c.execute('CREATE TABLE extra(value)')
                        if mode == 'fk': c.execute("INSERT INTO workflow_runs VALUES ('bad','missing','bad')")
                        if mode == 'unversioned': c.execute('PRAGMA user_version=0')
                before = self.inventory()
                with self.assertRaises(owner.RuntimeStoreSchemaError), self.open():
                    pass
                self.assertEqual(self.inventory(), before)

    def test_alias_paths_and_wrong_identity_reject(self):
        link = self.root / 'alias.sqlite3'
        link.symlink_to(self.path)
        hard = self.root / 'hard.sqlite3'
        os.link(self.path, hard)
        with self.assertRaises(owner.RuntimeStoreError), self.open(): pass
        hard.unlink()  # Synthetic test fixture only.
        alias = self.root / 'alias-dir'
        alias.symlink_to(self.root, target_is_directory=True)
        cases = [':memory:', self.path.as_uri()+'?mode=rw', 'core.sqlite3',
                 str(self.root)+'/./core.sqlite3', link, alias/'core.sqlite3']
        before = self.inventory()
        for value in cases:
            with self.subTest(value=value), self.assertRaises((owner.RuntimeStoreError, OSError)), self.open(value): pass
        with self.assertRaises(owner.RuntimeStoreError), self.open(identity=(self.identity[0], self.identity[1]+1)): pass
        with self.assertRaises(owner.RuntimeStoreError), self.open(root=self.root/'outside'): pass
        self.assertEqual(self.inventory(), before)

    def test_sidecars_reject_before_sqlite_connect(self):
        for suffix in ('-journal', '-wal', '-shm'):
            side = Path(str(self.path)+suffix); side.write_bytes(b'synthetic')
            before = self.inventory()
            with patch.object(sqlite3, 'connect', side_effect=AssertionError('no connect')) as connect:
                with self.assertRaisesRegex(owner.RuntimeStoreError, 'sidecar'), self.open(): pass
                connect.assert_not_called()
            self.assertEqual(self.inventory(), before)
            side.unlink()  # Synthetic test fixture only.

    def test_real_hot_journal_is_retained_without_recovery(self):
        with sqlite3.connect(self.path) as c:
            c.execute('CREATE TABLE hot_fixture(value BLOB)')
            c.executemany('INSERT INTO hot_fixture VALUES(?)', [(b'a'*4096,)]*80)
        subprocess.run([sys.executable, '-I', '-c',
            "import sqlite3,os,sys;c=sqlite3.connect(sys.argv[1]);c.execute('PRAGMA cache_size=1');"
            "c.execute('BEGIN IMMEDIATE');c.execute(\"UPDATE hot_fixture SET value=zeroblob(4096)\");os._exit(0)",
            str(self.path)], check=True)
        self.assertEqual(Path(str(self.path)+'-journal').read_bytes()[:8], bytes.fromhex('d9d505f920a163d7'))
        before = self.inventory()
        with patch.object(sqlite3, 'connect', side_effect=AssertionError('no recovery')):
            with self.assertRaisesRegex(owner.RuntimeStoreError, 'sidecar'), self.open(): pass
        self.assertEqual(self.inventory(), before)

    def test_replacement_before_native_commit_rolls_back_original(self):
        retained = self.root/'retained.sqlite3'
        with self.assertRaises((owner.RuntimeStoreError, FileNotFoundError)), self.open() as store:
            with store._transaction() as c:
                c.execute("INSERT INTO projects VALUES ('uncommitted')")
                self.path.rename(retained)
                self.path.write_bytes(b'replacement is retained')
        self.assertEqual(self.path.read_bytes(), b'replacement is retained')
        # The connection rolled back against its original descriptor.
        with sqlite3.connect(retained) as c:
            self.assertEqual(c.execute('SELECT project_id FROM projects').fetchall(), [('existing',)])

    def test_exception_keeps_successful_commit_and_closes_guard(self):
        store = guard = None
        with self.assertRaisesRegex(ValueError, 'caller failure'), self.open() as store:
            guard = store._existing_mutable_guard
            store.store_project(Project(project_id='committed'))
            raise ValueError('caller failure')
        self.assertEqual(guard.fds, [])
        with self.assertRaises(owner.RuntimeStoreError): store.list_projects()
        with self.open() as reopened:
            self.assertEqual([x.project_id for x in reopened.list_projects()], ['committed', 'existing'])

    def test_ancestor_replacement_rejects_before_native_write(self):
        moved = self.root.with_name(self.root.name + '-moved')
        try:
            with self.assertRaises((owner.RuntimeStoreError, FileNotFoundError)), self.open() as store:
                self.root.rename(moved)
                self.root.mkdir()
                store.store_project(Project(project_id='forbidden'))
        finally:
            if moved.exists():
                self.root.rmdir()  # Empty synthetic replacement directory only.
                moved.rename(self.root)
        with self.open() as store:
            self.assertEqual([x.project_id for x in store.list_projects()], ['existing'])

    def test_startup_uses_readonly_preflight_then_query_only_writer_validation(self):
        calls = []
        original = sqlite3.connect
        def tracked(database, *args, **kwargs):
            connection = original(database, *args, **kwargs)
            if str(database) != ':memory:':
                calls.append((str(database), []))
                statements = calls[-1][1]
                connection.set_trace_callback(statements.append)
            return connection
        with patch.object(sqlite3, 'connect', side_effect=tracked):
            with self.open(): pass
        self.assertEqual(len(calls), 2)
        self.assertIn('?mode=ro&cache=private', calls[0][0])
        self.assertIn('?mode=rw&cache=private', calls[1][0])
        for _, statements in calls:
            self.assertFalse(any(x.upper().startswith(('CREATE ', 'INSERT ', 'UPDATE ', 'DELETE ')) for x in statements))
            self.assertIn('PRAGMA query_only=ON', statements)
        statements = calls[1][1]
        self.assertLess(statements.index('PRAGMA query_only=ON'), statements.index('PRAGMA foreign_key_check'))
        self.assertLess(statements.index('PRAGMA foreign_key_check'), statements.index('PRAGMA query_only=OFF'))

    def test_real_process_restart_retains_exact_submission_claim(self):
        from tests.v3.core.test_store import store_base_records
        with self.open() as store:
            store_base_records(store)
            self.assertEqual(store.record_submission_intent('attempt-1', 'intent-1').value, 'WINNER')
        script = """import json,sys
from pathlib import Path
from auto_g16.core import SQLiteRuntimeStore
p=Path(sys.argv[1]);s=p.stat()
with SQLiteRuntimeStore.open_existing_mutable(p,approved_root=p.parent,expected_file_identity=(s.st_dev,s.st_ino)) as store:
 result=store.record_submission_intent('attempt-1','intent-1')
 print(json.dumps({'claim':result.value,'attempts':len(store.list_attempts('task-1')),'intent':store.load_submission_intent('attempt-1')}))
"""
        result = subprocess.run([sys.executable, '-c', script, str(self.path)], check=True, text=True, capture_output=True)
        import json
        self.assertEqual(json.loads(result.stdout), {'claim':'REPLAY','attempts':1,'intent':'intent-1'})

    def test_failed_guard_cannot_revive_after_namespace_is_restored(self):
        for mode in ('rename', 'sidecar'):
            with self.subTest(mode=mode):
                with self.assertRaises(owner.RuntimeStoreError), self.open() as store:
                    guard = store._existing_mutable_guard
                    store.store_project(Project(project_id='committed'))
                    renamed = self.root/'renamed.sqlite3'
                    sidecar = Path(str(self.path)+'-journal')
                    if mode == 'rename': self.path.rename(renamed)
                    else: sidecar.write_bytes(b'synthetic unexpected journal')
                    try:
                        with self.assertRaises((owner.RuntimeStoreError, FileNotFoundError)):
                            store.load_project('existing')
                    finally:
                        if mode == 'rename': renamed.rename(self.path)
                        else: sidecar.unlink()  # Synthetic test fixture only.
                    with self.assertRaisesRegex(owner.RuntimeStoreError, 'permanently invalid'):
                        store.store_project(Project(project_id='forbidden'))
                self.assertTrue(guard.poisoned)
                self.assertEqual(guard.fds, [])
                with self.open() as reopened:
                    self.assertEqual([x.project_id for x in reopened.list_projects()], ['committed', 'existing'])

    def test_attestation_does_not_close_database_descriptor_during_transaction(self):
        with self.open() as store:
            target_fd = store._existing_mutable_guard.fds[-1]
            original_close = os.close
            def guarded_close(fd):
                if fd == target_fd: raise AssertionError('target descriptor closed while live')
                return original_close(fd)
            with patch.object(os, 'close', side_effect=guarded_close):
                store.store_project(Project(project_id='held'))
                self.assertEqual(store.load_project('held').project_id, 'held')



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
                result = subprocess.run([sys.executable, '-B', '-c', script, 'core', mode],
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
        result = subprocess.run([sys.executable, '-B', '-c', script, 'core'],
            cwd=Path(__file__).resolve().parents[3], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'parent lock and commit retained')

    def test_preexisting_transaction_is_not_consumed(self):
        with self.open() as store:
            store._connection.execute('BEGIN IMMEDIATE')
            with self.assertRaises(owner.RuntimeStoreError):
                with store._transaction():pass
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
                    with self.assertRaises(KeyboardInterrupt):store.store_project(Project(project_id='interrupted'))
                    self.assertFalse(connection.in_transaction)
                    self.assertFalse(Path(str(self.path)+'-journal').exists())
                    store._connection=connection
                    self.assertEqual(len(store.list_projects()),1+int(statement=='COMMIT' and after))



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

if __name__ == '__main__': unittest.main()
