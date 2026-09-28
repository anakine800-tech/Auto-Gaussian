"""Native local exclusive-publication checks; no scientific or remote effects."""
from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import patch

from auto_g16.core import SQLiteRuntimeStore
from auto_g16.result._revision_file import publish_revision
from auto_g16.result.models import ProvenanceConflictError


class RevisionFileTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.path = self.root/'revision.sqlite3'
        store = SQLiteRuntimeStore()
        self.raw = store._connection.serialize()
        store.close()

    def publish(self):
        return publish_revision(self.raw, path=self.path, root=self.root)

    def test_new_exact_replay_and_source_bytes_readable(self):
        first = self.publish()
        before = self.path.stat()
        self.assertEqual(self.publish(), first)
        self.assertEqual(self.path.stat().st_ino, before.st_ino)
        with SQLiteRuntimeStore.read_snapshot(self.path) as store:
            self.assertEqual(store._connection.serialize(), self.raw)

    def test_partial_write_retained_and_conflicting_replay_rejects(self):
        write = os.write
        def partial(fd, data):
            write(fd, data[:5])
            raise OSError('injected interrupted write')
        with patch('auto_g16.result._revision_file.os.write', side_effect=partial):
            with self.assertRaises(OSError):
                self.publish()
        before = self.path.read_bytes()
        self.assertEqual(len(before), 5)
        with self.assertRaises(ProvenanceConflictError):
            self.publish()
        self.assertEqual(self.path.read_bytes(), before)

    def test_fsync_failure_is_not_acceptance_but_explicit_replay_recloses(self):
        with patch('auto_g16.result._revision_file.os.fsync', side_effect=OSError('injected fsync failure')):
            with self.assertRaises(OSError):
                self.publish()
        self.assertEqual(self.path.read_bytes(), self.raw)
        with patch('auto_g16.result._revision_file.os.fsync', wraps=os.fsync) as sync:
            self.publish()
            self.assertEqual(sync.call_count, 2)

    def test_symlink_hardlink_and_forbidden_identity(self):
        target = self.root/'original.sqlite3'
        target.write_bytes(self.raw)
        self.path.symlink_to(target)
        with self.assertRaises(OSError):
            self.publish()
        hard = self.root/'hard.sqlite3'
        os.link(target, hard)
        with self.assertRaises(ProvenanceConflictError):
            publish_revision(self.raw, path=hard, root=self.root)
        independent = self.root/'independent.sqlite3'
        independent.write_bytes(self.raw)
        info = independent.stat()
        with self.assertRaises(ProvenanceConflictError):
            publish_revision(self.raw, path=independent, root=self.root,
                             forbidden_identities=((info.st_dev, info.st_ino),))
        self.assertEqual(target.read_bytes(), self.raw)

    def test_replaced_parent_does_not_return_success_receipt(self):
        parent = self.root/'parent'
        parent.mkdir()
        self.path = parent/'revision.sqlite3'
        write = os.write
        def replace_parent(fd, data):
            parent.rename(self.root/'retained-parent')
            parent.mkdir()
            return write(fd, data)
        with patch('auto_g16.result._revision_file.os.write', side_effect=replace_parent):
            with self.assertRaises(ProvenanceConflictError):
                self.publish()
        self.assertFalse(self.path.exists())
        self.assertTrue((self.root/'retained-parent'/'revision.sqlite3').exists())

    def test_root_escape_and_symlink_parent(self):
        with self.assertRaises(ProvenanceConflictError):
            publish_revision(self.raw, path=self.path, root=self.root/'not-parent')
        link = self.root/'link'
        link.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(OSError):
            publish_revision(self.raw, path=link/'another.sqlite3', root=self.root)
