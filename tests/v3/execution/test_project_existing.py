"""Real existing v3 Project journals, process faults and zero remote activity."""
from contextlib import closing
import hashlib
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

from auto_g16 import execution
from auto_g16.execution import _project_existing as guard_module
from auto_g16.execution.project_provisioning import _ProductionProvisioningJournal as Journal, ProjectPhysicalBinding
from auto_g16.execution._identity import ExecutionValueError, semantic_id
from tests.v3.execution.test_execution import ExecutionFixture


def pins(path):
    return dict(expected_parent_chain=tuple((p.stat().st_dev,p.stat().st_ino) for p in reversed(path.parents)),
                expected_file_identity=(path.stat().st_dev,path.stat().st_ino))


class ProjectExistingTests(unittest.TestCase):

    def test_creation_absence_uses_same_owner_without_new_resources(self):
        before = self.path.read_bytes()
        with self.open() as journal:
            with patch.object(os, 'open', side_effect=AssertionError('new FD')), \
                    patch.object(sqlite3, 'connect', side_effect=AssertionError('new SQLite')):
                self.assertIsNone(journal.assert_no_creation_history(self.project.project_id))
            self.assertFalse(journal._connection.in_transaction)
        self.assertEqual(before, self.path.read_bytes())

    def test_creation_absence_rejects_every_valid_native_prefix(self):
        with self.open() as journal:
            intent = self.record(journal)
            for prefix in ('intent', 'result', 'binding'):
                if prefix == 'result':
                    journal._record_success(intent, self.project.project_id,
                                            'synthetic-parent', 'synthetic-project')
                if prefix == 'binding':
                    journal.append_binding(self.bound(intent))
                before = self.path.read_bytes()
                with self.subTest(prefix=prefix), self.assertRaisesRegex(ExecutionValueError, 'creation history'):
                    journal.assert_no_creation_history(self.project.project_id)
                self.assertIsNone(journal.assert_no_creation_history('another-project'))
                self.assertEqual(before, self.path.read_bytes())
                self.assertFalse(journal._existing_guard.poisoned)

    def test_creation_absence_rejects_orphan_inserted_after_open(self):
        with self.assertRaises(ExecutionValueError):
            with self.open() as journal:
                # Deliberate corruption after the opening validation, test only.
                journal._connection.execute("INSERT INTO provisioning_results VALUES('orphan','{}')").close()
                before = self.path.read_bytes()
                with self.assertRaises(ExecutionValueError):
                    journal.assert_no_creation_history(self.project.project_id)
                self.assertEqual(before, self.path.read_bytes())
                self.assertTrue(journal._existing_guard.poisoned)

    def test_creation_absence_rejects_transaction_and_foreign_process_before_rows(self):
        with self.open() as journal:
            journal._connection.execute('BEGIN IMMEDIATE').close()
            try:
                with patch.object(journal, '_validate_existing_rows', side_effect=AssertionError('row read')):
                    with self.assertRaises(ExecutionValueError):
                        journal.assert_no_creation_history(self.project.project_id)
                    with patch.object(os, 'getpid', return_value=-1):
                        with self.assertRaises(ExecutionValueError):
                            journal.assert_no_creation_history(self.project.project_id)
                self.assertTrue(journal._connection.in_transaction)
                self.assertFalse(journal._existing_guard.poisoned)
            finally:
                journal._connection.execute('ROLLBACK').close()

    def test_binding_exact_immutable_and_no_new_database_resources(self):
        before=self.path.read_bytes()
        with self.open() as store:
            guard=store._existing_guard
            expected=dict(path=str(self.path),parent_chain=tuple(guard.identities[:-1]),
                          file_identity=guard.identities[-1],native_identity=dict(journal_identity=self.identity))
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
                    with self.assertRaises(ExecutionValueError):store.assert_existing_binding()
                self.assertTrue(connection.in_transaction)
                self.assertFalse(store._existing_guard.poisoned)
                pid=os.fork()
                if pid==0:
                    class Forbidden:
                        def __getattribute__(self,name):raise AssertionError('inherited SQLite access')
                    store._connection=Forbidden()
                    try:store.assert_existing_binding()
                    except ExecutionValueError:os._exit(0)
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
            self.assertEqual(len(errors),1);self.assertIsInstance(errors[0],ExecutionValueError)
            try:
                with patch.object(os,'getpid',return_value=-1):
                    with self.assertRaises(ExecutionValueError):store.assert_existing_binding()
                store._closed=True
                with self.assertRaises(ExecutionValueError):store.assert_existing_binding()
            finally:store._connection=connection;store._closed=False
            store.assert_existing_binding()
        store._connection=Forbidden()
        with self.assertRaises(ExecutionValueError):store.assert_existing_binding()
        legacy=object.__new__(Journal)
        legacy._connection=Forbidden()
        with self.assertRaises(ExecutionValueError):legacy.assert_existing_binding()

    def test_binding_attached_database_and_replaced_connection_reject(self):
        for mode in ('attached','replaced'):
            with self.subTest(mode=mode),self.assertRaises(ExecutionValueError):
                with self.open() as store:
                    original=store._connection
                    if mode=='attached':
                        original.execute("ATTACH DATABASE ':memory:' AS other").close()
                        try:
                            with self.assertRaises(ExecutionValueError):store.assert_existing_binding()
                        finally:original.execute('DETACH DATABASE other').close()
                    else:
                        substitute=sqlite3.connect(':memory:',isolation_level=None)
                        store._connection=substitute
                        try:
                            with self.assertRaises(ExecutionValueError):store.assert_existing_binding()
                        finally:store._connection=original;substitute.close()
                    self.assertTrue(store._existing_guard.poisoned)

    def test_binding_sidecar_rejection_is_permanent(self):
        side=Path(str(self.path)+'-wal')
        with self.assertRaises(ExecutionValueError):
            with self.open() as store:
                side.write_bytes(b'synthetic sidecar')
                try:
                    with self.assertRaises(ExecutionValueError):store.assert_existing_binding()
                finally:side.unlink()
                with self.assertRaises(ExecutionValueError):store.assert_existing_binding()

    def test_creation_receipts_match_native_readonly_and_reject_partial(self):
        with self.open() as journal:
            with self.assertRaises(ExecutionValueError):journal.inspect_creation_receipts(self.project.project_id)
            intent=self.record(journal)
            with self.assertRaises(ExecutionValueError):journal.inspect_creation_receipts(self.project.project_id)
            journal._record_success(intent,self.project.project_id,'synthetic-parent','synthetic-project')
            with self.assertRaises(ExecutionValueError):journal.inspect_creation_receipts(self.project.project_id)
            journal.append_binding(self.bound(intent))
            before=self.path.read_bytes()
            with patch.object(os,'open',side_effect=AssertionError('new FD')), \
                    patch.object(sqlite3,'connect',side_effect=AssertionError('new SQLite')):
                result=journal.inspect_creation_receipts(self.project.project_id)
            self.assertEqual(result['intent']['intent_id'],intent)
            self.assertEqual(result['creation_result']['payload']['intent_id'],intent)
            with self.assertRaises(TypeError):result['intent']['payload']['project_id']='other'
            self.assertEqual(before,self.path.read_bytes())
        with Journal.open_existing_readonly(self.path,approved_root=self.root) as reader:
            self.assertEqual(result,reader._association_creation_source(self.project.project_id))

    def test_binding_file_and_ancestor_drift_preserves_original(self):
        for kind in ('file','ancestor'):
            before=self.path.read_bytes()
            with self.subTest(kind=kind),self.assertRaises(ExecutionValueError):
                with self.open() as store:
                    if kind=='file':
                        saved=self.root/'retained-original';self.path.rename(saved)
                        self.path.write_bytes(b'replacement')
                    else:
                        saved=self.root.with_name(self.root.name+'-retained')
                        self.root.rename(saved);self.root.mkdir();self.path.write_bytes(b'replacement')
                    try:
                        with self.assertRaises(ExecutionValueError):store.assert_existing_binding()
                        self.assertEqual(self.path.read_bytes(),b'replacement')
                    finally:
                        self.path.unlink()  # Only synthetic test replacement.
                        if kind=='file':saved.rename(self.path)
                        else:self.root.rmdir();saved.rename(self.root)
                    with self.assertRaises(ExecutionValueError):store.assert_existing_binding()
            self.assertEqual(before,self.path.read_bytes())

    def test_binding_rejects_coherent_replacement_of_native_journal_identity(self):
        with self.assertRaises(ExecutionValueError):
            with self.open() as journal:
                raw=journal._sql('SELECT identity_json FROM provisioning_meta').fetchone()[0]
                changed=json.loads(raw);changed['nonce']='f'*64
                canonical=json.dumps(changed,sort_keys=True,separators=(',',':'))
                triggers=journal._sql("SELECT name,sql FROM sqlite_schema WHERE type='trigger' AND tbl_name='provisioning_meta'").fetchall()
                def replace_metadata(value):
                    # Deliberate same-inode corruption, restoring the exact native schema.
                    for name,_ in triggers:journal._connection.execute('DROP TRIGGER '+name).close()
                    journal._connection.execute('UPDATE provisioning_meta SET identity_json=?',(value,)).close()
                    for _,ddl in triggers:journal._connection.execute(ddl).close()
                replace_metadata(canonical)
                journal._identity=semantic_id('project-provisioning-journal',changed)
                try:
                    with self.assertRaisesRegex(ExecutionValueError,'creation identity'):journal.assert_existing_binding()
                finally:
                    replace_metadata(raw)
                    journal._identity=self.identity
                self.assertTrue(journal._existing_guard.poisoned)

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.path=self.root/'journal.sqlite3'
        with Journal.create_new_recoverable(self.path,approved_root=self.root) as journal:self.identity=journal._identity
        self.bindings=pins(self.path)
        self.fixture=ExecutionFixture();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.target=execution.resolve_server_profile(self.fixture.profile())
        self.project=self.fixture.store.load_project('project-1')
        self.remote=self.target.remote_root+'/synthetic-project'

    def open(self,**overrides):
        values=dict(approved_root=self.root,expected_journal_identity=self.identity,**self.bindings)
        values.update(overrides)
        return Journal.open_existing_mutable(self.path,**values)

    def record(self,journal):
        return journal._record_intent(project_id=self.project.project_id,target=self.target,path=self.remote,
                                      parent_identity='synthetic-parent',authority_id='synthetic-authority')

    def bound(self,intent):
        return ProjectPhysicalBinding._from_attested(project=self.project,target=self.target,remote_project_dir=self.remote,
            provisioning_disposition='ABSENT',parent_physical_identity='synthetic-parent',project_physical_identity='synthetic-project',
            evidence_identity=semantic_id('project-provision-evidence',dict(intent_id=intent,parent='synthetic-parent',project='synthetic-project')),
            provisioning_authority_id='synthetic-authority')

    def test_empty_roundtrip_and_all_native_write_paths(self):
        before=self.path.read_bytes()
        with patch('socket.socket',side_effect=AssertionError('remote')),patch.object(Journal,'_open',side_effect=AssertionError('creating opener')):
            with self.open() as journal:self.assertIsNone(journal.load_binding('absent'))
        self.assertEqual(before,self.path.read_bytes())
        with self.open() as journal:
            intent=self.record(journal)
            journal._record_success(intent,self.project.project_id,'synthetic-parent','synthetic-project')
            bound=self.bound(intent);journal.append_binding(bound);journal.append_binding(bound)
            self.assertEqual(journal.load_binding(self.project.project_id),bound)
            with self.assertRaises(ExecutionValueError):self.record(journal)
        with self.open() as journal:self.assertEqual(journal.load_binding(self.project.project_id),bound)
        with self.assertRaises(ExecutionValueError):journal.load_binding(self.project.project_id)

    def test_exact_expected_bindings_required_before_sql(self):
        wrong=[dict(expected_journal_identity='00000000-0000-0000-0000-000000000001'),
               dict(expected_parent_chain=((0,1),)),dict(expected_file_identity=(False,1)),
               dict(approved_root=self.path),dict(expected_parent_chain=tuple((0,1) for _ in self.path.parents))]
        before=self.path.read_bytes()
        for value in wrong:
            with self.subTest(value=value):
                with self.assertRaises((ExecutionValueError,FileNotFoundError)):
                    with self.open(**value):pass
                self.assertEqual(before,self.path.read_bytes())

    def test_missing_empty_v2_bad_schema_and_no_mutations(self):
        for kind in ('missing','empty','v2','extra','wrong-version','wrong-app'):
            path=self.root/(kind+'.sqlite3')
            if kind=='missing':expected=(self.path.stat().st_dev,999999)
            elif kind=='empty':path.touch();expected=(path.stat().st_dev,path.stat().st_ino)
            else:
                create=Journal.create_new if kind=='v2' else Journal.create_new_recoverable
                with create(path,approved_root=self.root) as j:identity=j._identity
                expected=(path.stat().st_dev,path.stat().st_ino)
                if kind in ('extra','wrong-version','wrong-app'):
                    with closing(sqlite3.connect(path, isolation_level=None)) as db:db.execute({'extra':'CREATE TABLE extra(a)','wrong-version':'PRAGMA user_version=0','wrong-app':'PRAGMA application_id=0'}[kind])
            before=path.read_bytes() if path.exists() else None
            with self.assertRaises((ExecutionValueError,FileNotFoundError)):
                with Journal.open_existing_mutable(path,approved_root=self.root,expected_file_identity=expected,
                        expected_parent_chain=self.bindings['expected_parent_chain'],expected_journal_identity=self.identity):pass
            self.assertEqual(path.read_bytes() if path.exists() else None,before)

    def test_aliases_and_each_sidecar_preserved(self):
        raw=self.path.read_bytes()
        for suffix in ('-journal','-wal','-shm'):
            side=Path(str(self.path)+suffix);side.touch()
            with self.assertRaises(ExecutionValueError):
                with self.open():pass
            self.assertEqual(self.path.read_bytes(),raw);self.assertEqual(side.read_bytes(),b'');side.unlink()
        alias=self.root/'alias';alias.symlink_to(self.path)
        with self.assertRaises(ExecutionValueError):
            with Journal.open_existing_mutable(alias,approved_root=self.root,**self.bindings,expected_journal_identity=self.identity):pass
        hard=self.root/'hard';os.link(self.path,hard)
        with self.assertRaises(ExecutionValueError):
            with self.open():pass

    def test_replacement_poison_survives_restoration(self):
        with self.assertRaises(ExecutionValueError):
            with self.open() as journal:
                retained=self.root/'retained';self.path.rename(retained);self.path.write_bytes(b'sentinel')
                with self.assertRaises(ExecutionValueError):journal.load_binding('absent')
                self.assertEqual(self.path.read_bytes(),b'sentinel')
                self.path.unlink();retained.rename(self.path)
                with self.assertRaises(ExecutionValueError):journal.load_binding('absent')

    def test_all_write_paths_rollback_after_begin_and_keep_after_commit(self):
        original=guard_module.Guard.statement
        for operation in ('intent','result','binding'):
            for point in ('BEGIN IMMEDIATE','COMMIT'):
                with self.subTest(operation=operation,point=point):
                    path=self.root/(operation+point.split()[0]+'.sqlite3')
                    with Journal.create_new_recoverable(path,approved_root=self.root) as j:identity=j._identity
                    with Journal.open_existing_mutable(path,approved_root=self.root,**pins(path),expected_journal_identity=identity) as journal:
                        intent=None
                        if operation!='intent':intent=self.record(journal)
                        if operation=='binding':journal._record_success(intent,self.project.project_id,'synthetic-parent','synthetic-project')
                        triggered=[]
                        def interrupted(guard,connection,sql,parameters=()):
                            result=original(guard,connection,sql,parameters)
                            if sql==point and not triggered:triggered.append(True);raise KeyboardInterrupt('synthetic')
                            return result
                        with patch.object(guard_module.Guard,'statement',interrupted):
                            with self.assertRaises(KeyboardInterrupt):
                                if operation=='intent':self.record(journal)
                                elif operation=='result':journal._record_success(intent,self.project.project_id,'synthetic-parent','synthetic-project')
                                else:journal.append_binding(self.bound(intent))
                        self.assertFalse(journal._connection.in_transaction)
                    with closing(sqlite3.connect(path, isolation_level=None)) as db:
                        table={'intent':'provisioning_intents','result':'provisioning_results','binding':'project_physical_bindings'}[operation]
                        self.assertEqual(db.execute('SELECT count(*) FROM '+table).fetchone()[0],int(point=='COMMIT'))

    def test_real_hot_journal_is_retained_without_recovery(self):
        code="import sqlite3,os,sys;c=sqlite3.connect(sys.argv[1]);c.execute('BEGIN IMMEDIATE');c.execute('INSERT INTO provisioning_results VALUES(?,?)',('orphan','{}'));os._exit(78)"
        result=subprocess.run([sys.executable,'-B','-c',code,str(self.path)])
        self.assertEqual(result.returncode,78)
        side=Path(str(self.path)+'-journal');self.assertTrue(side.exists())
        before=(self.path.read_bytes(),side.read_bytes())
        with self.assertRaises(ExecutionValueError):
            with self.open():pass
        self.assertEqual(before,(self.path.read_bytes(),side.read_bytes()))

    def test_independent_process_reopen_of_intent_prefix(self):
        with self.open() as journal:intent=self.record(journal)
        value=dict(path=str(self.path),root=str(self.root),identity=self.identity,**self.bindings)
        code='''import json,sys
from auto_g16.execution.project_provisioning import _ProductionProvisioningJournal as J
v=json.loads(sys.argv[1])
with J.open_existing_mutable(v['path'],approved_root=v['root'],expected_parent_chain=tuple(map(tuple,v['expected_parent_chain'])),expected_file_identity=tuple(v['expected_file_identity']),expected_journal_identity=v['identity']) as j:
 print(json.dumps(dict(intent=dict(j.inspect_intent('project-1',intent_id=sys.argv[2])),binding=j.load_binding('project-1'))))
'''
        before=self.path.read_bytes();result=subprocess.run([sys.executable,'-B','-c',code,json.dumps(value),intent],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr);self.assertIsNone(json.loads(result.stdout)['binding'])
        self.assertEqual(self.path.read_bytes(),before)

    def test_cross_thread_and_fork_reject_before_sql(self):
        with self.assertRaises(ExecutionValueError):
            with self.open() as journal:
                errors=[]
                def other():
                    try:journal.load_binding('absent')
                    except ExecutionValueError:errors.append(True)
                thread=threading.Thread(target=other);thread.start();thread.join();self.assertEqual(errors,[True])
        with self.open() as journal:
            pid=os.fork()
            if pid==0:
                try:journal.load_binding('absent')
                except ExecutionValueError:os._exit(0)
                os._exit(3)
            self.assertEqual(os.waitpid(pid,0)[1],0)

    def test_real_writer_lock_stays_held_during_guard_checks(self):
        with self.open() as journal:
            with journal._existing_guard.transaction(journal):
                for _ in range(3):journal._attest()
                code="import sqlite3,sys;c=sqlite3.connect(sys.argv[1],timeout=0);\ntry:c.execute('BEGIN IMMEDIATE')\nexcept sqlite3.OperationalError:sys.exit(0)\nsys.exit(4)"
                result=subprocess.run([sys.executable,'-B','-c',code,str(self.path)])
                self.assertEqual(result.returncode,0)

    def test_business_rows_and_orphan_result_reject_before_rw(self):
        corruptions=["INSERT INTO provisioning_results VALUES('orphan','{}')",
                     "INSERT INTO provisioning_intents VALUES('wrong','project-x','target','/path','{}')",
                     "INSERT INTO project_physical_bindings VALUES('wrong','project-x','{}')"]
        for n,sql in enumerate(corruptions):
            path=self.root/('bad-row-'+str(n)+'.sqlite3')
            with Journal.create_new_recoverable(path,approved_root=self.root) as j:identity=j._identity
            with closing(sqlite3.connect(path,isolation_level=None)) as db:db.execute(sql)
            before=path.read_bytes();opened=[];connect=sqlite3.connect
            def observed(name,*args,**kwargs):opened.append(name);return connect(name,*args,**kwargs)
            with patch.object(guard_module.sqlite3,'connect',observed):
                with self.assertRaises((ExecutionValueError,ValueError,KeyError)):
                    with Journal.open_existing_mutable(path,approved_root=self.root,**pins(path),expected_journal_identity=identity):pass
            self.assertFalse(any('mode=rw' in name for name in opened));self.assertEqual(before,path.read_bytes())

    def test_ro_to_rw_replacement_never_writes_replacement(self):
        connect=sqlite3.connect;opened=[]
        def replace(name,*args,**kwargs):
            if 'mode=rw' in name and not opened:
                opened.append(True);self.path.rename(self.root/'retained')
                self.path.write_bytes(b'sentinel')
            return connect(name,*args,**kwargs)
        with patch.object(guard_module.sqlite3,'connect',replace):
            with self.assertRaises((ExecutionValueError,sqlite3.Error)):
                with self.open():pass
        self.assertEqual(self.path.read_bytes(),b'sentinel')

    def test_precommit_replacement_rolls_back_original(self):
        original=guard_module.Guard.statement;replaced=[]
        with self.assertRaises(ExecutionValueError):
            with self.open() as journal:
                def replace(guard,connection,sql,parameters=()):
                    if sql=='COMMIT' and not replaced:
                        replaced.append(True);self.path.rename(self.root/'retained');self.path.write_bytes(b'sentinel')
                    return original(guard,connection,sql,parameters)
                with patch.object(guard_module.Guard,'statement',replace):
                    with self.assertRaises(ExecutionValueError):self.record(journal)
        self.assertEqual(self.path.read_bytes(),b'sentinel')
        with closing(sqlite3.connect(self.root/'retained')) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM provisioning_intents').fetchone()[0],0)

    def test_existing_transaction_is_not_consumed_by_rejected_method(self):
        with self.open() as journal:
            journal._connection.execute('BEGIN IMMEDIATE')
            with self.assertRaises(ExecutionValueError):self.record(journal)
            self.assertTrue(journal._connection.in_transaction)
            journal._connection.execute('ROLLBACK')

    def test_readback_reentry_poison_retains_committed_fact(self):
        connect=sqlite3.connect;tripped=[]
        with self.assertRaises(ExecutionValueError):
            with self.open() as journal:
                def reenter(name,*args,**kwargs):
                    if journal._existing_guard.readback_active:
                        tripped.append(True)
                        with self.assertRaises(ExecutionValueError):journal.load_binding('absent')
                    return connect(name,*args,**kwargs)
                with patch.object(guard_module.sqlite3,'connect',reenter):
                    with self.assertRaises(ExecutionValueError):self.record(journal)
        self.assertEqual(tripped,[True])
        with self.open() as journal:self.assertEqual(len(journal._sql('SELECT * FROM provisioning_intents').fetchall()),1)

    def test_fork_context_exit_never_operates_inherited_transaction(self):
        context=self.open();journal=context.__enter__()
        with journal._existing_guard.transaction(journal):
            journal._sql('INSERT INTO provisioning_intents VALUES(?,?,?,?,?)',
                ('temporary','temporary','temporary','/temporary','{}'))
            pid=os.fork()
            if pid==0:
                try:context.__exit__(None,None,None)
                except ExecutionValueError:
                    retained=(os.getpid(),self.bindings['expected_file_identity']) in guard_module._QUARANTINE
                    os._exit(0 if retained else 4)
                os._exit(3)
            self.assertEqual(os.waitpid(pid,0)[1],0)
            journal._sql('ROLLBACK')
            # Restore a valid owner-managed empty transaction for the helper to commit.
            journal._sql('BEGIN IMMEDIATE')
        context.__exit__(None,None,None)

    def test_sqlite_close_failure_is_quarantined_without_reopen(self):
        # Run in a disposable child: unresolved resources are deliberately retained until exit.
        args=dict(path=str(self.path),root=str(self.root),identity=self.identity,**self.bindings)
        code='''import json,sys,os
from unittest.mock import patch
from auto_g16.execution import _project_existing as g
from auto_g16.execution.project_provisioning import _ProductionProvisioningJournal as J
v=json.loads(sys.argv[1]);opts=dict(approved_root=v['root'],expected_parent_chain=tuple(map(tuple,v['expected_parent_chain'])),expected_file_identity=tuple(v['expected_file_identity']),expected_journal_identity=v['identity'])
context=J.open_existing_mutable(v['path'],**opts);j=context.__enter__();connection=j._connection
class Failing:
 def close(self):raise OSError('before actual close')
 def __getattr__(self,name):return getattr(connection,name)
j._connection=Failing()
try:j.close()
except Exception:pass
else:os._exit(3)
try:context.__exit__(None,None,None)
except Exception:pass
else:os._exit(4)
with patch.object(g.sqlite3,'connect',side_effect=AssertionError('must reject before SQLite')):
 try:
  with J.open_existing_mutable(v['path'],**opts):pass
 except g.ExecutionValueError:pass
 else:os._exit(5)
assert j._existing_guard.fds and j._existing_guard.quarantined
print('quarantined-no-reopen',flush=True);os._exit(0)
'''
        result=subprocess.run([sys.executable,'-B','-c',code,json.dumps(args)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(result.stdout.strip(),'quarantined-no-reopen')

    def test_rollback_failure_preserves_original_and_closes_handle(self):
        statement=guard_module.Guard.statement;rows=guard_module.rows
        def interrupted(guard,connection,sql,parameters=()):
            result=statement(guard,connection,sql,parameters)
            if sql=='BEGIN IMMEDIATE':raise KeyboardInterrupt('original interruption')
            return result
        def failed_rollback(connection,sql,parameters=()):
            if sql=='ROLLBACK':raise OSError('private rollback detail')
            return rows(connection,sql,parameters)
        with self.assertRaises(KeyboardInterrupt) as caught:
            with self.open() as journal:
                with patch.object(guard_module.Guard,'statement',interrupted),patch.object(guard_module,'rows',failed_rollback):
                    self.record(journal)
        self.assertTrue(journal._closed)
        self.assertIn('Project rollback failed: OSError',caught.exception.__notes__)
        self.assertNotIn('private rollback detail',str(caught.exception.__notes__))
        with self.open() as journal:self.assertEqual(journal._sql('SELECT count(*) FROM provisioning_intents').fetchone(),(0,))

    def test_descriptor_close_failure_attempts_every_fd_once(self):
        context=self.open();journal=context.__enter__();fds=tuple(journal._existing_guard.fds)
        original=os.close;seen=[]
        def failed(fd):
            seen.append(fd);original(fd)
            if fd==fds[-1]:raise OSError('after close')
        with patch.object(guard_module.os,'close',failed):
            with self.assertRaises(ExecutionValueError):context.__exit__(None,None,None)
        self.assertEqual(seen,list(reversed(fds)))
        self.assertEqual(journal._existing_guard.fds,[])
        with self.open():pass

    def test_header_fstat_failure_closes_all_acquired_fds(self):
        fstat=os.fstat;close=os.close;opened=[];closed=[];open_=os.open
        def record_open(*args,**kwargs):
            fd=open_(*args,**kwargs);opened.append(fd);return fd
        def failure(fd):raise OSError('fstat synthetic')
        def record_close(fd):closed.append(fd);close(fd)
        with patch.object(guard_module.os,'open',record_open),patch.object(guard_module.os,'fstat',failure),patch.object(guard_module.os,'close',record_close):
            with self.assertRaises(ExecutionValueError):
                with self.open():pass
        self.assertEqual(closed,list(reversed(opened)))

    def test_outer_handled_exception_does_not_hide_cleanup_error(self):
        original=os.close;failed=[]
        def close(fd):
            original(fd)
            if not failed:failed.append(fd);raise OSError('close synthetic')
        try:raise RuntimeError('already handled')
        except RuntimeError:
            with patch.object(guard_module.os,'close',close):
                with self.assertRaises(ExecutionValueError):
                    with self.open():pass
