"""Existing-only Core opening and real local crash/no-create boundaries."""
from pathlib import Path
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from auto_g16.core import store as owner
from auto_g16.core import Project


class ExistingMutableTests(unittest.TestCase):
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


if __name__ == '__main__': unittest.main()
