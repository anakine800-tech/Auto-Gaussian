"""Existing-only native v2 store: real SQLite, processes and local faults."""
import base64
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from auto_g16.transport import program as p
from auto_g16.transport import _program_existing as g


def pins(path):
    return dict(expected_parent_chain=tuple((v.stat().st_dev,v.stat().st_ino) for v in reversed(path.parents)),
                expected_file_identity=(path.stat().st_dev,path.stat().st_ino))


def qualification():
    return dict(deployment_id='test-deployment',bootstrap_protocol='test-bootstrap',
                bootstrap_source_sha256='a'*64,bootstrap_source_size_bytes=12)


def record(store, *, operation='ALLOCATE_WORKSPACE'):
    rid=store.attest_runtime(program_execution_snapshot_id='snapshot',resolved_server_profile_id='profile',qualification=qualification())
    binding={key:key for key in p._BINDING_FIELDS}
    binding.update(program_transport_store_id=store.program_transport_store_id,store_instance_id=store.store_instance_id,
                   runtime_attestation_id=rid,program_execution_snapshot_id='snapshot',resolved_server_profile_id='profile')
    payload={}
    if operation=='SUBMIT_QSUB_ONCE':
        binding.update({key:key for key in p._WORKSPACE_AUTHORITY_FIELDS})
        payload=dict(scheduler_portable_name='job.pbs',scheduler_artifact_authority_id='scheduler',program_input_artifact_authority_ids=('input',))
    if operation=='QUERY_SCHEDULER':
        binding.update(job_authority_id='job-authority');payload=dict(job_id='1.master')
    request=p._request(operation,binding,payload)
    eid=store.record_effect(binding=binding,request=request,classification='SUCCEEDED',response={})
    if operation=='QUERY_SCHEDULER':
        store._record_scheduler_raw(request=request,result=dict(stdout_base64=base64.b64encode(b'Q').decode(),
            stderr_base64='',returncode=0,eof_stdout=True,eof_stderr=True,completion_status='complete'))
    return eid


def child_open(path, root, binding, mode):
    binding['expected_parent_chain']=tuple(map(tuple,binding['expected_parent_chain']))
    binding['expected_file_identity']=tuple(binding['expected_file_identity'])
    with p._ProgramTransportStore.open_existing_mutable(path,approved_root=root,**binding) as store:
        if mode=='record':record(store,operation='SUBMIT_QSUB_ONCE')
        if mode=='hold':
            with store._completion_guard():
                print('HELD',flush=True);sys.stdin.readline()
        if mode=='lock':
            with store._completion_guard(), store._existing_guard.write(store):
                store._sql('INSERT INTO program_runtime_attestation VALUES(?,?,?,?,?,?,?,?,?)',
                    store._runtime_attestation_record(program_execution_snapshot_id='locked',resolved_server_profile_id='profile',qualification=qualification())[2])
                code="import sqlite3,sys;c=sqlite3.connect(sys.argv[1],timeout=0);\ntry:c.execute('BEGIN IMMEDIATE')\nexcept sqlite3.OperationalError:sys.exit(0)\nelse:sys.exit(3)"
                require=subprocess.run([sys.executable,'-c',code,path],check=False)
                assert require.returncode==0
        print('OK',flush=True)


def child_fault(path, root, binding, mode):
    binding['expected_parent_chain']=tuple(map(tuple,binding['expected_parent_chain']))
    binding['expected_file_identity']=tuple(binding['expected_file_identity'])
    opener=lambda:p._ProgramTransportStore.open_existing_mutable(path,approved_root=root,**binding)
    if mode.startswith('close-'):
        real=sqlite3.connect;calls=[];saved=[]
        class BadClose(sqlite3.Connection):
            def close(self):
                calls.append(id(self))
                if mode=='close-after':super().close()
                raise OSError('synthetic close fault')
        def connect(*args,**kwargs):
            if 'mode=rw' in str(args[0]):kwargs['factory']=BadClose
            return real(*args,**kwargs)
        with patch.object(g.sqlite3,'connect',connect):
            try:
                with opener() as store:
                    saved.extend(store._existing_guard.fds)
                    if mode=='close-body':raise KeyboardInterrupt('original')
            except KeyboardInterrupt as exc:
                assert mode=='close-body' and 'original' in str(exc)
            except p.TransportBoundaryError:
                assert mode!='close-body'
            else:raise AssertionError('close did not reject')
        assert len(calls)==1
        class Forbidden:
            def __getattribute__(self,name):raise AssertionError('quarantined SQLite access '+name)
        store._connection=Forbidden()
        try:store.close()
        except p.TransportBoundaryError:pass
        else:raise AssertionError('quarantined close reused')
        assert len(calls)==1
        for fd in saved:os.fstat(fd)
        with patch.object(g.sqlite3,'connect',side_effect=AssertionError('reopen')):
            try:
                with opener():pass
            except p.TransportBoundaryError:pass
            else:raise AssertionError('quarantine bypass')
        print('QUARANTINED',flush=True)
        return
    if mode=='rollback':
        real=g.rows
        def failing(connection,sql,args=()):
            if sql=='ROLLBACK':raise OSError('rollback')
            if sql.startswith('INSERT'):raise KeyboardInterrupt('original')
            return real(connection,sql,args)
        try:
            with opener() as store:
                with patch.object(g,'rows',failing):record(store)
        except KeyboardInterrupt as exc:
            assert 'original' in str(exc)
            assert any('rollback' in note for note in exc.__notes__)
            assert store._existing_guard.quarantined
            for fd in store._existing_guard.fds:os.fstat(fd)
        else:raise AssertionError('interrupt lost')
        print('QUARANTINED',flush=True)
        return
    if mode=='fork':
        cm=opener();store=cm.__enter__()
        with store._completion_guard(),store._existing_guard.write(store):
            values=store._runtime_attestation_record(program_execution_snapshot_id='fork',resolved_server_profile_id='profile',qualification=qualification())[2]
            store._sql('INSERT INTO program_runtime_attestation VALUES(?,?,?,?,?,?,?,?,?)',values)
            pid=os.fork()
            if pid==0:
                class Forbidden:
                    def __getattribute__(self,name):raise AssertionError('child SQLite access '+name)
                store._connection=Forbidden()
                try:
                    try:store._attest()
                    except p.TransportBoundaryError:pass
                    else:os._exit(21)
                    try:cm.__exit__(None,None,None)
                    except p.TransportBoundaryError:pass
                    else:os._exit(22)
                    try:
                        with opener():pass
                    except p.TransportBoundaryError:pass
                    else:os._exit(23)
                except BaseException:os._exit(24)
                os._exit(0)
            assert os.waitpid(pid,0)[1]==0
            code="import sqlite3,sys;c=sqlite3.connect(sys.argv[1],timeout=0);\ntry:c.execute('BEGIN IMMEDIATE')\nexcept sqlite3.OperationalError:sys.exit(0)\nelse:sys.exit(3)"
            assert subprocess.run([sys.executable,'-c',code,path]).returncode==0
        cm.__exit__(None,None,None)
        with opener() as check:assert check._sql('SELECT count(*) FROM program_runtime_attestation').fetchone()==(1,)
        print('FORK-PARENT-COMMITTED',flush=True)


class ProgramExistingTests(unittest.TestCase):

    def test_binding_exact_immutable_and_no_new_database_resources(self):
        before=self.path.read_bytes()
        with self.open() as store:
            guard=store._existing_guard
            expected=dict(path=str(self.path),parent_chain=tuple(guard.identities[:-1]),
                          file_identity=guard.identities[-1],native_identity=dict(program_transport_store_id=store.program_transport_store_id,store_instance_id=self.instance))
            context=store._completion_guard()
            with context:
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
                    with self.assertRaises(p.TransportBoundaryError):store.assert_existing_binding()
                self.assertTrue(connection.in_transaction)
                self.assertFalse(store._existing_guard.poisoned)
                pid=os.fork()
                if pid==0:
                    class Forbidden:
                        def __getattribute__(self,name):raise AssertionError('inherited SQLite access')
                    store._connection=Forbidden()
                    try:store.assert_existing_binding()
                    except p.TransportBoundaryError:os._exit(0)
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
            self.assertEqual(len(errors),1);self.assertIsInstance(errors[0],p.TransportBoundaryError)
            try:
                with patch.object(os,'getpid',return_value=-1):
                    with self.assertRaises(p.TransportBoundaryError):store.assert_existing_binding()
                store._closed=True
                with self.assertRaises(p.TransportBoundaryError):store.assert_existing_binding()
            finally:store._connection=connection;store._closed=False
            store.assert_existing_binding()
        store._connection=Forbidden()
        with self.assertRaises(p.TransportBoundaryError):store.assert_existing_binding()
        legacy=object.__new__(p._ProgramTransportStore)
        legacy._connection=Forbidden()
        with self.assertRaises(p.TransportBoundaryError):legacy.assert_existing_binding()

    def test_binding_attached_database_and_replaced_connection_reject(self):
        for mode in ('attached','replaced'):
            with self.subTest(mode=mode),self.assertRaises(p.TransportBoundaryError):
                with self.open() as store:
                    original=store._connection
                    if mode=='attached':
                        original.execute("ATTACH DATABASE ':memory:' AS other").close()
                        try:
                            with self.assertRaises(p.TransportBoundaryError):store.assert_existing_binding()
                        finally:original.execute('DETACH DATABASE other').close()
                    else:
                        substitute=sqlite3.connect(':memory:',isolation_level=None)
                        store._connection=substitute
                        try:
                            with self.assertRaises(p.TransportBoundaryError):store.assert_existing_binding()
                        finally:store._connection=original;substitute.close()
                    self.assertTrue(store._existing_guard.poisoned)

    def test_binding_sidecar_rejection_is_permanent(self):
        side=Path(str(self.path)+'-wal')
        with self.assertRaises(p.TransportBoundaryError):
            with self.open() as store:
                side.write_bytes(b'synthetic sidecar')
                try:
                    with self.assertRaises(p.TransportBoundaryError):store.assert_existing_binding()
                finally:side.unlink()
                with self.assertRaises(p.TransportBoundaryError):store.assert_existing_binding()

    def test_binding_file_and_ancestor_drift_preserves_original(self):
        for kind in ('file','ancestor'):
            before=self.path.read_bytes()
            with self.subTest(kind=kind),self.assertRaises(p.TransportBoundaryError):
                with self.open() as store:
                    if kind=='file':
                        saved=self.root/'retained-original';self.path.rename(saved)
                        self.path.write_bytes(b'replacement')
                    else:
                        saved=self.root.with_name(self.root.name+'-retained')
                        self.root.rename(saved);self.root.mkdir();self.path.write_bytes(b'replacement')
                    try:
                        with self.assertRaises(p.TransportBoundaryError):store.assert_existing_binding()
                        self.assertEqual(self.path.read_bytes(),b'replacement')
                    finally:
                        self.path.unlink()  # Only synthetic test replacement.
                        if kind=='file':saved.rename(self.path)
                        else:self.root.rmdir();saved.rename(self.root)
                    with self.assertRaises(p.TransportBoundaryError):store.assert_existing_binding()
            self.assertEqual(before,self.path.read_bytes())

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.path=self.root/'transport.sqlite3'
        store=p._ProgramTransportStore._create_completion_store(self.path,approved_root=self.root)
        self.instance=store.store_instance_id;store.close()
        self.binding={**pins(self.path),'expected_store_instance_id':self.instance}

    def open(self,**changes):
        kwargs=dict(approved_root=self.root,**self.binding);kwargs.update(changes)
        return p._ProgramTransportStore.open_existing_mutable(self.path,**kwargs)

    def child(self,mode):
        return [sys.executable,'-c',"from tests.v31.transport.test_program_existing import child_open;import sys,json;child_open(sys.argv[1],sys.argv[2],json.loads(sys.argv[3]),sys.argv[4])",
                str(self.path),str(self.root),json.dumps(self.binding),mode]

    def test_empty_populated_guard_reacquisition_and_replay_process(self):
        original=self.path.read_bytes()
        with patch.object(p._ProgramTransportStore,'_open',side_effect=AssertionError('legacy open')),patch.object(p._ProgramTransportStore,'_create_schema',side_effect=AssertionError('creation')):
            with self.open() as store:
                self.assertIsNone(store._completion_owner)
                for _ in range(2):
                    with store._completion_guard() as token:store._require_completion_guard(token)
            self.assertEqual(original,self.path.read_bytes())
        with self.open() as store:
            record(store);record(store,operation='SUBMIT_QSUB_ONCE');record(store,operation='QUERY_SCHEDULER')
        before=self.path.read_bytes()
        result=subprocess.run(self.child('record'),capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(before,self.path.read_bytes())
        with self.open() as store:
            self.assertEqual(store._sql('SELECT count(*) FROM program_effect_physical_authority WHERE submit_once_key IS NOT NULL').fetchone(),(1,))

    def test_missing_bad_bindings_and_formats_never_create(self):
        before=self.path.read_bytes()
        for changes in ({'expected_parent_chain':((0,1),)}, {'expected_file_identity':(False,1)},
                        {'expected_store_instance_id':'0'*36},{'approved_root':self.path}):
            with self.subTest(changes=changes),self.assertRaises(p.TransportBoundaryError):
                with self.open(**changes):pass
        self.assertEqual(before,self.path.read_bytes())
        self.path.rename(self.root/'saved')
        for kind in ('missing','empty'):
            if kind=='empty':self.path.touch()
            with patch.object(g.sqlite3,'connect',side_effect=AssertionError('must not connect')):
                with self.assertRaises(p.TransportBoundaryError):
                    with self.open():pass
            self.assertEqual(self.path.exists(),kind=='empty')
        self.path.unlink()
        old=p._ProgramTransportStore.create_new(self.path,approved_root=self.root);old.close()
        self.binding.update(pins(self.path));before=self.path.read_bytes()
        with self.assertRaises(p.TransportBoundaryError):
            with self.open():pass
        self.assertEqual(before,self.path.read_bytes())

    def test_sidecars_and_real_hot_journal_preserved(self):
        for suffix in ('-journal','-wal','-shm'):
            side=Path(str(self.path)+suffix);side.touch()
            with patch.object(g.sqlite3,'connect',side_effect=AssertionError('sidecar connect')):
                with self.assertRaises(p.TransportBoundaryError):
                    with self.open():pass
            self.assertEqual(side.read_bytes(),b'');side.unlink()
        c=sqlite3.connect(self.path);c.execute('CREATE TABLE hot(value BLOB)');c.executemany('INSERT INTO hot VALUES(?)',[(b'a'*4096,)]*80);c.commit();c.close()
        subprocess.run([sys.executable,'-c',"import sqlite3,os,sys;c=sqlite3.connect(sys.argv[1]);c.execute('PRAGMA cache_size=1');c.execute('BEGIN IMMEDIATE');c.execute('UPDATE hot SET value=zeroblob(4096)');os._exit(0)",str(self.path)],check=True)
        before={x.name:x.read_bytes() for x in self.root.iterdir()}
        self.assertEqual(before['transport.sqlite3-journal'][:8],bytes.fromhex('d9d505f920a163d7'))
        with self.assertRaises(p.TransportBoundaryError):
            with self.open():pass
        self.assertEqual(before,{x.name:x.read_bytes() for x in self.root.iterdir()})

    def test_all_rows_checked_even_when_unused(self):
        for alteration in ('runtime','index','key','orphan','raw'):
            with self.subTest(alteration=alteration):
                temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
                root=Path(temp.name).resolve();path=root/'db';s=p._ProgramTransportStore._create_completion_store(path,approved_root=root)
                record(s,operation='SUBMIT_QSUB_ONCE');record(s,operation='QUERY_SCHEDULER');iid=s.store_instance_id;s.close()
                c=sqlite3.connect(path)
                for table in p._PROGRAM_STORE_TABLES:c.execute('DROP TRIGGER '+table+'_no_update')
                if alteration=='runtime':c.execute("UPDATE program_runtime_attestation SET payload=?",(b'invalid',))
                elif alteration=='index':c.execute("UPDATE program_effect_physical_authority SET operation='bad' WHERE submit_once_key IS NOT NULL")
                elif alteration=='key':c.execute("UPDATE program_effect_physical_authority SET submit_once_key='fake' WHERE submit_once_key IS NOT NULL")
                elif alteration=='orphan':c.execute("UPDATE program_effect_physical_authority SET runtime_attestation_id='missing'")
                else:c.execute("UPDATE program_effect_physical_authority SET payload=? WHERE physical_effect_authority_id LIKE ?",(b'{}\n',p._SCHEDULER_RAW_PREFIX+'%'))
                for name,stmt in p._PROGRAM_STORE_TRIGGERS:
                    if name.endswith('_update'):c.execute(stmt)
                c.commit();c.close();before=path.read_bytes()
                with self.assertRaises(p.TransportBoundaryError):
                    with p._ProgramTransportStore.open_existing_mutable(path,approved_root=root,expected_store_instance_id=iid,**pins(path)):pass
                self.assertEqual(before,path.read_bytes())

    def test_ro_rw_replacement_preserves_replacement(self):
        real=g.close_connection;done=False
        def closing(guard,connection):
            nonlocal done
            real(guard,connection)
            if not done:
                done=True;self.path.rename(self.root/'original');self.path.write_bytes(b'replacement')
        with patch.object(g,'close_connection',closing),self.assertRaises(p.TransportBoundaryError):
            with self.open():pass
        self.assertEqual(self.path.read_bytes(),b'replacement')

    def test_identity_or_sidecar_failure_is_permanent(self):
        for mode in ('rename','sidecar'):
            with self.subTest(mode=mode):
                with self.assertRaises(p.TransportBoundaryError):
                    with self.open() as store:
                        if mode=='rename':self.path.rename(self.root/'away')
                        else:Path(str(self.path)+'-wal').touch()
                        with self.assertRaises(Exception):store._attest()
                        if mode=='rename':(self.root/'away').rename(self.path)
                        else:Path(str(self.path)+'-wal').unlink()
                        with self.assertRaises(p.TransportBoundaryError):store._attest()
                with self.open():pass

    def test_foreign_thread_and_nested_guard_rejected(self):
        with self.assertRaises(p.TransportBoundaryError), self.open() as store:
            errors=[]
            def other():
                try:store._attest()
                except Exception as exc:errors.append(type(exc))
            t=threading.Thread(target=other);t.start();t.join()
            self.assertEqual(errors,[p.TransportBoundaryError])
        with self.open() as store:
            with store._completion_guard():
                with self.assertRaises(p.TransportBoundaryError):
                    with store._completion_guard():pass

    def test_real_process_lock_busy_then_release(self):
        child=subprocess.Popen(self.child('hold'),stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            self.assertEqual(child.stdout.readline().strip(),'HELD')
            with self.assertRaises(p.TransportBoundaryError):
                with self.open():pass
        finally:
            out,err=child.communicate('\n',timeout=15)
        self.assertEqual(child.returncode,0,err)
        with self.open():pass
        child=subprocess.run(self.child('lock'),capture_output=True,text=True)
        self.assertEqual(child.returncode,0,child.stderr)

    def test_begin_commit_interruptions_leave_no_owned_transaction(self):
        for phase in ('begin-after','commit-before','commit-after'):
            with self.subTest(phase=phase):
                with self.open() as store:
                    real=g.rows;fired=False
                    def injected(connection,sql,args=()):
                        nonlocal fired
                        trigger=not fired and ((sql=='BEGIN IMMEDIATE' and phase=='begin-after') or (sql=='COMMIT' and phase.startswith('commit')))
                        if trigger:
                            fired=True
                            if phase!='commit-before':real(connection,sql,args)
                            raise KeyboardInterrupt(phase)
                        return real(connection,sql,args)
                    with patch.object(g,'rows',injected),self.assertRaises(KeyboardInterrupt):
                        store.attest_runtime(program_execution_snapshot_id=phase,resolved_server_profile_id='profile',qualification=qualification())
                    self.assertFalse(store._connection.in_transaction)
                    self.assertTrue(store._existing_guard.poisoned)
                    store.close()
                with self.open() as store:
                    count=store._sql('SELECT count(*) FROM program_runtime_attestation WHERE program_execution_snapshot_id=?',(phase,)).fetchone()[0]
                    self.assertEqual(count,int(phase=='commit-after'))

    def test_preexisting_transaction_not_consumed(self):
        with self.open() as store:
            with store._completion_guard():
                g.rows(store._connection,'BEGIN')
                with self.assertRaises(p.TransportBoundaryError):
                    with store._existing_guard.write(store):pass
                self.assertTrue(store._connection.in_transaction)
                g.rows(store._connection,'ROLLBACK')

    def test_no_database_reopen_or_close_inside_transaction(self):
        real_open=g.os.open;real_close=g.os.close
        with self.open() as store:
            target=store._existing_guard.fds[-1]
            def opening(path,*args,**kwargs):
                self.assertNotEqual(str(path),self.path.name);self.assertNotEqual(str(path),str(self.path))
                return real_open(path,*args,**kwargs)
            def closing(fd):
                self.assertNotEqual(fd,target);return real_close(fd)
            with patch.object(g.os,'open',opening),patch.object(g.os,'close',closing):record(store)

    def test_explicit_close_is_idempotent(self):
        with self.open() as store:store.close();store.close()
        with self.assertRaises(p.TransportBoundaryError):store._attest()

    def test_close_uncertainty_and_rollback_failure_in_real_processes(self):
        for mode in ('close-before','close-after','close-body','rollback','fork'):
            with self.subTest(mode=mode):
                command=[sys.executable,'-c',
                    "from tests.v31.transport.test_program_existing import child_fault;import sys,json;child_fault(sys.argv[1],sys.argv[2],json.loads(sys.argv[3]),sys.argv[4])",
                    str(self.path),str(self.root),json.dumps(self.binding),mode]
                result=subprocess.run(command,capture_output=True,text=True,timeout=30)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_tagged_parser_strict_roundtrip(self):
        for value in (None,False,123,-12,'中文',b'bytes',dict(z=(1,'a'),a=True)):
            self.assertEqual(g.decode(p.canonical_bytes(value)),value)
        for raw in (b'n;x',b'i01;',b'i+1;',b'i-0;',b'i;',b'i'+b'1'*5000+b';',
                    b'o2:s1:ai1;s1:ai2;',b's2:a',b's1:\xff',b'y1:AA',
                    b'a99999999999999999999999999999999999999:',b'a1:'*2000+b'n;'):
            with self.subTest(raw=raw[:30]),self.assertRaises(p.TransportBoundaryError):g.decode(raw)

    def test_parent_replacement_and_hardlink_rejected(self):
        linked=self.root/'linked';os.link(self.path,linked)
        with self.assertRaises(p.TransportBoundaryError):
            with self.open():pass
        linked.unlink()
        with self.assertRaises(p.TransportBoundaryError):
            with self.open() as store:
                original=self.root.with_name(self.root.name+'-renamed')
                self.root.rename(original);self.root.mkdir()
                try:
                    with self.assertRaises(p.TransportBoundaryError):store._attest()
                finally:
                    self.root.rmdir();original.rename(self.root)
        with self.open():pass

    def test_pre_and_post_commit_path_changes_preserve_facts(self):
        for phase in ('before','after'):
            with self.subTest(phase=phase):
                real=g.rows;fired=False
                def changed(connection,sql,args=()):
                    nonlocal fired
                    if sql=='COMMIT' and not fired:
                        fired=True
                        if phase=='after':result=real(connection,sql,args)
                        self.path.rename(self.root/'away')
                        if phase=='after':return result
                    return real(connection,sql,args)
                with self.assertRaises((p.TransportBoundaryError,OSError)):
                    with self.open() as store:
                        with patch.object(g,'rows',changed):
                            store.attest_runtime(program_execution_snapshot_id=phase,resolved_server_profile_id='profile',qualification=qualification())
                (self.root/'away').rename(self.path)
                with self.open() as store:
                    count=store._sql('SELECT count(*) FROM program_runtime_attestation WHERE program_execution_snapshot_id=?',(phase,)).fetchone()[0]
                    # A change injected inside COMMIT before its actual native call
                    # is not preventable by a preceding check. Its committed fact
                    # must be retained, with a failing postcheck.
                    self.assertEqual(count,1)

    def test_precommit_owner_checkpoint_rolls_back(self):
        real=g.Guard.check;fired=False
        def checked(guard):
            nonlocal fired
            if guard.transaction and guard.journal_identity is not None and not fired:
                fired=True;self.path.rename(self.root/'away')
            return real(guard)
        with self.assertRaises((p.TransportBoundaryError,OSError)):
            with self.open() as store:
                with patch.object(g.Guard,'check',checked):record(store)
        (self.root/'away').rename(self.path)
        with self.open() as store:self.assertEqual(store._sql('SELECT count(*) FROM program_runtime_attestation').fetchone(),(0,))

    def test_fstat_and_descriptor_close_failures_release_once(self):
        real_stat=g.os.fstat;real_open=g.os.open;real_close=g.os.close;opened=[];closed=[]
        def opening(*args,**kwargs):
            fd=real_open(*args,**kwargs);opened.append(fd);return fd
        def closing(fd):closed.append(fd);return real_close(fd)
        with patch.object(g.os,'open',opening),patch.object(g.os,'close',closing),patch.object(g.os,'fstat',side_effect=OSError('fstat')):
            with self.assertRaises(p.TransportBoundaryError):
                with self.open():pass
        self.assertEqual(sorted(opened),sorted(closed));self.assertEqual(len(closed),len(set(closed)))
        with self.open() as store:
            target=store._existing_guard.fds[-1];seen=[]
            def fail_after_close(fd):
                if fd==target:
                    seen.append(fd);real_close(fd);raise OSError('close')
                return real_close(fd)
            with patch.object(g.os,'close',fail_after_close),self.assertRaises(p.TransportBoundaryError):store.close()
            self.assertEqual(seen,[target])

    def test_actual_completion_decorator_reacquires_native_guard(self):
        from types import SimpleNamespace
        from auto_g16.execution import program_runtime as runtime
        @runtime._completion_owned
        def observed(core,*,snapshot,program_transport_store,_completion_token=None):
            program_transport_store._require_completion_guard(_completion_token)
            return _completion_token
        with self.open() as store,patch.object(runtime,'_uses_completion_receipt',return_value=True):
            snapshot=SimpleNamespace(program_execution_spec=object())
            first=observed(None,snapshot=snapshot,program_transport_store=store)
            second=observed(None,snapshot=snapshot,program_transport_store=store)
            self.assertIsNot(first,second);self.assertIsNone(store._completion_owner)

    def test_startup_loser_never_opens_database_descriptor(self):
        held=threading.Event();release=threading.Event();active=threading.Event();finish=threading.Event();errors=[]
        initialize=g.Guard.__init__;winner_id=[]
        def paused(guard,*args,**kwargs):
            initialize(guard,*args,**kwargs)
            if threading.get_ident()==winner_id[0]:
                held.set()
                if not release.wait(10):raise AssertionError('loser did not finish')
        def winner():
            winner_id.append(threading.get_ident())
            try:
                with self.open() as store,store._completion_guard(),store._existing_guard.write(store):
                    values=store._runtime_attestation_record(program_execution_snapshot_id='winner',resolved_server_profile_id='profile',qualification=qualification())[2]
                    store._sql('INSERT INTO program_runtime_attestation VALUES(?,?,?,?,?,?,?,?,?)',values)
                    active.set()
                    if not finish.wait(10):raise AssertionError('active loser did not finish')
                    code="import sqlite3,sys;c=sqlite3.connect(sys.argv[1],timeout=0);\ntry:c.execute('BEGIN IMMEDIATE')\nexcept sqlite3.OperationalError:sys.exit(0)\nelse:sys.exit(3)"
                    self.assertEqual(subprocess.run([sys.executable,'-c',code,str(self.path)]).returncode,0)
            except BaseException as exc:errors.append(exc);held.set();active.set()
        original=g.os.open;dbopens=[];loser=threading.get_ident()
        def opening(path,*args,**kwargs):
            if threading.get_ident()==loser and str(path) in (str(self.path),self.path.name):dbopens.append(path)
            return original(path,*args,**kwargs)
        with patch.object(g.Guard,'__init__',paused),patch.object(g.os,'open',opening):
            thread=threading.Thread(target=winner);thread.start()
            self.assertTrue(held.wait(10))
            try:
                # Winner is after target pin but before handle registration or
                # SQLite. Only the native startup directory lock excludes us.
                with self.assertRaises(p.TransportBoundaryError):
                    with self.open():pass
                self.assertEqual(dbopens,[])
                release.set()
                self.assertTrue(active.wait(10))
                with self.assertRaises(p.TransportBoundaryError):
                    with self.open():pass
                self.assertEqual(dbopens,[])
            finally:
                release.set();finish.set();thread.join(15)
        self.assertFalse(thread.is_alive());self.assertEqual(errors,[])

    def test_coherent_same_inode_metadata_cannot_rebind_instance(self):
        with self.assertRaises(p.TransportBoundaryError):
            with self.open() as store:
                nonce=b'b'*32
                payload=dict(schema=store._schema,approved_store_root=store._root,approved_store_path=store._path,
                    program_transport_store_id=store.program_transport_store_id,creation_nonce_sha256=p.sha256(nonce).hexdigest(),
                    store_device=store._file_identity[0],store_inode=store._file_identity[1],
                    completion_guard_binding_sha256=p._digest(store._guard_binding))
                replacement=p._identity('program-transport-store-instance',payload)
                g.rows(store._connection,'DROP TRIGGER program_transport_meta_no_update')
                g.rows(store._connection,'UPDATE program_transport_meta SET creation_nonce=?,store_instance_id=?',(nonce,replacement))
                stmt=dict(p._PROGRAM_STORE_TRIGGERS)['program_transport_meta_no_update'];g.rows(store._connection,stmt)
                with self.assertRaises(p.TransportBoundaryError):record(store)
                self.assertEqual(g.rows(store._connection,'SELECT count(*) FROM program_runtime_attestation').fetchone(),(0,))
                self.assertEqual(store.store_instance_id,self.instance)

    def test_cursor_close_failure_preserves_original_interrupt(self):
        class Cursor:
            def execute(self,*args):raise KeyboardInterrupt('original')
            def close(self):raise OSError('cursor close')
        class Connection:
            def cursor(self):return Cursor()
        with self.assertRaises(KeyboardInterrupt) as caught:g.rows(Connection(),'SELECT 1')
        self.assertTrue(any('cursor close' in x for x in caught.exception.__notes__))

    def test_native_submission_completion_and_replay_with_guarded_handle(self):
        from tests.v31.transport import test_program_completion as completion_tests
        fixture=completion_tests.CompletionTests()
        fixture.setUp()
        try:
            old=fixture.program_transport_store
            path=Path(old._path);root=Path(old._root);iid=old.store_instance_id;old.close()
            with p._ProgramTransportStore.open_existing_mutable(path,approved_root=root,
                    expected_store_instance_id=iid,**pins(path)) as store:
                fixture.program_transport_store=store
                fixture.test_success_durable_bundle_and_zero_read_replay()
            with p._ProgramTransportStore.open_existing_mutable(path,approved_root=root,
                    expected_store_instance_id=iid,**pins(path)) as store:
                self.assertGreater(store._sql('SELECT count(*) FROM program_effect_physical_authority').fetchone()[0],1)
        finally:fixture.doCleanups()

    def test_descriptor_close_interrupt_still_releases_remaining_once(self):
        real=g.os.close
        with self.open() as store:
            descriptors=list(store._existing_guard.fds);seen=[]
            def interrupted(fd):
                seen.append(fd);real(fd)
                if fd==descriptors[-1]:raise KeyboardInterrupt('descriptor interrupt')
            with patch.object(g.os,'close',interrupted),self.assertRaises(KeyboardInterrupt):store.close()
            self.assertEqual(seen,list(reversed(descriptors)))
            for fd in descriptors:
                with self.assertRaises(OSError):os.fstat(fd)


if __name__=='__main__':unittest.main()
