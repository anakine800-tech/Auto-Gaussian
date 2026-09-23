"""Existing native source opening must never recover or modify historical SQLite."""
from pathlib import Path
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from auto_g16.core import store as core
from auto_g16.transport import program as transport


class ReadonlySourceOpenTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.core_path = self.root / 'core.sqlite3'
        core.SQLiteRuntimeStore(self.core_path).close()
        self.transport_path = self.root / 'transport.sqlite3'
        transport._ProgramTransportStore._create_completion_store(self.transport_path, approved_root=self.root).close()

    def cases(self):
        return ((self.core_path, core.SQLiteRuntimeStore._open_readonly_existing),
                (self.transport_path, lambda p: transport._ProgramTransportStore._open_readonly_existing(p, approved_root=self.root)))

    def inventory(self):
        return {str(p): p.read_bytes() for p in self.root.iterdir() if p.is_file()}

    def test_native_original_readonly_and_public_writer_compatibility(self):
        before = self.inventory()
        for path, opener in self.cases():
            with self.subTest(path=path):
                value = opener(path)
                try:
                    connection = value._connection
                    self.assertEqual(connection.execute('PRAGMA database_list').fetchall()[0][2], str(path))
                    self.assertEqual(connection.execute('PRAGMA query_only').fetchone()[0], 1)
                    # Removing the additional query guard cannot defeat mode=ro.
                    connection.execute('PRAGMA query_only=OFF')
                    with self.assertRaises(sqlite3.OperationalError):
                        connection.execute('CREATE TABLE forbidden(value)')
                finally:
                    value.close()
        self.assertEqual(self.inventory(), before)
        writer = core.SQLiteRuntimeStore(self.core_path)
        writer._connection.execute('BEGIN IMMEDIATE');writer._connection.execute('ROLLBACK');writer.close()
        writer = transport._ProgramTransportStore.open_existing(self.transport_path, approved_root=self.root)
        writer._connection.execute('BEGIN IMMEDIATE');writer._connection.execute('ROLLBACK');writer.close()
        self.assertEqual(self.inventory(), before)

    def test_missing_file_sidecars_and_nonrollback_reject_before_connect(self):
        for path, opener in self.cases():
            with self.subTest(path=path):
                with patch.object(sqlite3, 'connect', side_effect=AssertionError('SQLite must not open')) as connect:
                    with self.assertRaises(Exception):opener(path.with_name('missing.sqlite3'))
                    connect.assert_not_called()
                    for suffix in ('-journal', '-wal', '-shm'):
                        sidecar = Path(str(path)+suffix);sidecar.write_bytes(b'inert')
                        before = self.inventory()
                        with self.assertRaisesRegex(Exception, 'sidecar'):opener(path)
                        self.assertEqual(self.inventory(), before);connect.assert_not_called()
                        sidecar.unlink()  # Synthetic test fixture only.
                    raw = path.read_bytes();path.write_bytes(raw[:18]+b'\x02\x02'+raw[20:])
                    before = self.inventory()
                    with self.assertRaisesRegex(Exception, 'rollback'):opener(path)
                    self.assertEqual(self.inventory(), before);connect.assert_not_called()
                    path.write_bytes(raw)
        self.assertFalse((self.root/'missing.sqlite3').exists())

    def test_real_hot_journals_remain_byte_exact_without_recovery(self):
        for path, opener in self.cases():
            # Fill a local synthetic native DB, then crash after dirty-page spill.
            connection = sqlite3.connect(path)
            connection.execute('CREATE TABLE hot_fixture(value BLOB)')
            connection.executemany('INSERT INTO hot_fixture VALUES(?)', [(b'a'*4096,)]*80)
            connection.commit();connection.close()
            result = subprocess.run([sys.executable, '-I', '-c',
                "import sqlite3,os,sys;c=sqlite3.connect(sys.argv[1]);c.execute('PRAGMA cache_size=1');"
                "c.execute('BEGIN IMMEDIATE');c.execute(\"UPDATE hot_fixture SET value=zeroblob(4096)\");os._exit(0)", str(path)], check=True)
            self.assertEqual(result.returncode, 0)
            journal = Path(str(path)+'-journal')
            self.assertEqual(journal.read_bytes()[:8], bytes.fromhex('d9d505f920a163d7'))
            before = self.inventory()
            with patch.object(sqlite3, 'connect', side_effect=AssertionError('no recovery')) as connect:
                with self.assertRaisesRegex(Exception, 'sidecar'):opener(path)
                connect.assert_not_called()
            self.assertEqual(self.inventory(), before)

    def test_failed_schema_open_preserves_original_and_reports_recheck_failure(self):
        for path, opener in self.cases():
            before = self.inventory()
            if path == self.core_path:
                owner, method = core, '_readonly_database_state'
                fail_owner, fail_method = core.SQLiteRuntimeStore, '_initialize_schema'
            else:
                owner, method = transport, '_readonly_source_state'
                fail_owner, fail_method = transport._ProgramTransportStore, '_require_completion_guard'
            actual = getattr(owner, method)
            calls = []
            def recheck(*args):
                calls.append(args)
                if len(calls) > 1:raise ValueError('injected recheck failure')
                return actual(*args)
            with patch.object(owner, method, side_effect=recheck), patch.object(fail_owner, fail_method, side_effect=ValueError('primary schema failure')):
                with self.assertRaisesRegex(ValueError, 'primary schema failure') as caught:opener(path)
            self.assertGreaterEqual(len(calls), 2)
            self.assertIn('injected recheck failure', str(caught.exception.__notes__))
            self.assertEqual(self.inventory(), before)
