"""Real file and SQLite lock counterexamples for the external CLI capture."""
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from auto_g16.study import _xtb_capture as subject
from auto_g16.study._model import StudyError
from tests.v3.study.test_installation import binding


class CaptureBoundaryTests(unittest.TestCase):
    def capture(self, path, roots=()):
        parent = subject._CaptureParent(str(path.parent), lock=False)
        raw, _ = parent.read(path.name, 4096)
        value = subject._Captured({}, roots, [(parent, path.name, raw, binding(path, True))])
        return parent, value

    def test_unknown_teardown_never_reopens_replaced_database_alias(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            evidence, database = root/'evidence', root/'original.sqlite3'
            evidence.write_bytes(b'original human evidence')
            parent, captured = self.capture(evidence)
            connection = sqlite3.connect(database)
            connection.execute('create table original(value)')
            connection.commit()
            connection.execute('begin exclusive')
            def locked():
                result = subprocess.run([sys.executable, '-c', '''
import sqlite3,sys
connection=sqlite3.connect(sys.argv[1],timeout=0)
try:connection.execute('select * from original').fetchall()
except sqlite3.OperationalError as error:
 assert 'locked' in str(error)
else:raise AssertionError('original SQLite lock was released')
''', str(database)], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            try:
                locked()
                evidence.unlink()
                os.link(database, evidence)
                with patch.object(subject.os, 'open', side_effect=AssertionError('external reopen')):
                    with self.assertRaises(StudyError):captured.assert_current()
                    # This is the exact cleanup branch after retained UNKNOWN owners.
                    parent.__exit__(RuntimeError, RuntimeError('retained UNKNOWN'), None)
                locked()
                self.assertTrue(connection.in_transaction)
            finally:
                connection.close()
                if parent.fds:parent.close()

    def test_mode_change_invalidates_original_signature(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary).resolve()/'evidence'
            path.write_bytes(b'original')
            path.chmod(0o600)
            parent, captured = self.capture(path)
            try:
                captured.assert_current()
                path.chmod(0o400)
                with self.assertRaises(StudyError):captured.assert_current()
            finally:parent.close()

    def test_physical_root_alias_rejected_even_with_different_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary).resolve()/'evidence'
            path.write_bytes(b'original')
            root = binding(path.parent)
            root['path'] = '/a-different-lexical-alias'
            parent, captured = self.capture(path, [root])
            try:
                with self.assertRaises(StudyError):captured.assert_current()
            finally:parent.close()

    def test_descriptor_mode_drift_during_read_rejects_before_capture(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary).resolve()/'evidence'
            path.write_bytes(b'original')
            path.chmod(0o600)
            parent = subject._CaptureParent(str(path.parent), lock=False)
            original = os.read
            def mutate(fd, cap):
                raw = original(fd, cap)
                os.fchmod(fd, 0o400)
                return raw
            try:
                with patch.object(subject.os, 'read', side_effect=mutate):
                    with self.assertRaises(StudyError):parent.read(path.name, 4096)
                self.assertEqual(parent.seen, {})
            finally:parent.close()
