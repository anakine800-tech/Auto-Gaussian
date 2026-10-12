"""Held source checkpoint metadata never refreshes its original full-hash baseline."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from auto_g16.study import _installation as owner
from tests.v3.study.test_installation import Fixture


class HeldSourceTests(unittest.TestCase):
    def test_metadata_checkpoint_reads_no_source_bytes_but_full_check_still_does(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary).resolve())
            inspection = owner._inspect(str(fixture.bundle), False)
            try:
                with patch.object(inspection.pins, 'read', side_effect=AssertionError('source reread')):
                    inspection.assert_held_current()
                    with self.assertRaisesRegex(AssertionError, 'source reread'):inspection.check()
                with self.assertRaises(owner.InstallationFactsError):inspection.assert_held_current()
            finally:inspection.pins.close()

    def run_drift(self, variant):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary).resolve())
            inspection = owner._inspect(str(fixture.bundle), False)
            source = fixture.source/'foo'/'bar'
            original = source.read_bytes()
            before = source.stat()
            try:
                inspection.assert_held_current()
                if variant == 'same-size':
                    source.write_bytes(b'x' * len(original))
                    self.assertEqual(source.stat().st_size, before.st_size)
                    os.utime(source, ns=(before.st_atime_ns,before.st_mtime_ns))
                elif variant == 'mode':source.chmod(0o755)
                elif variant == 'replacement':
                    replacement = source.with_name('replacement')
                    replacement.write_bytes(original)
                    replacement.replace(source)
                elif variant == 'inventory':(fixture.source/'unlisted').write_bytes(b'extra')
                elif variant == 'hardlink':os.link(source, Path(temporary)/'outside-hardlink')
                else:raise AssertionError(variant)
                with self.assertRaises(owner.InstallationFactsError):inspection.assert_held_current()
                self.assertTrue(inspection._held_failed)
                if variant == 'inventory':(fixture.source/'unlisted').unlink()
                elif variant == 'hardlink':(Path(temporary)/'outside-hardlink').unlink()
                else:
                    source.write_bytes(original)
                    source.chmod(before.st_mode & 0o777)
                    os.utime(source, ns=(before.st_atime_ns,before.st_mtime_ns))
                # Restored bytes/inventory cannot revive a failed inspection.
                with self.assertRaises(owner.InstallationFactsError):inspection.assert_held_current()
                with self.assertRaises(owner.InstallationFactsError):inspection.check()
            finally:inspection.pins.close()

    def test_same_size_write_with_restored_mtime_rejects(self):self.run_drift('same-size')
    def test_mode_change_rejects(self):self.run_drift('mode')
    def test_same_content_replacement_rejects(self):self.run_drift('replacement')
    def test_inventory_change_rejects(self):self.run_drift('inventory')
    def test_added_hardlink_rejects(self):self.run_drift('hardlink')
