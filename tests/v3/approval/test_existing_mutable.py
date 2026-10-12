"""Existing-only Approval persistence; synthetic stores and local processes only."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import unittest
from unittest.mock import patch

from auto_g16.approval import store as owner
from . import test_store as fixtures


class ExistingApprovalTests(unittest.TestCase):
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

    def test_rollback_failure_keeps_original_interrupt_and_closes_handle(self):
        with self.assertRaises(owner.ApprovalStoreError),self.open() as store:
            connection=store._connection
            class InterruptedConnection:
                def __getattr__(self,name):return getattr(connection,name)
                def execute(self,sql,*args):
                    if sql=='COMMIT':raise KeyboardInterrupt('original interruption')
                    if sql=='ROLLBACK':raise OSError('cleanup detail not exposed')
                    return connection.execute(sql,*args)
            store._connection=InterruptedConnection()
            with self.assertRaises(KeyboardInterrupt) as caught:store.store_scientific_approval(self.science)
            self.assertTrue(store._closed)
            self.assertTrue(store._existing_mutable_guard.poisoned)
            self.assertIn('approval rollback failed: OSError',caught.exception.__notes__)
            self.assertNotIn('cleanup detail',str(caught.exception.__notes__))
        with self.open() as store:self.assertEqual(store.evidence_count(),0)

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
