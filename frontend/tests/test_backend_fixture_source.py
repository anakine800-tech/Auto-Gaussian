"""Migration-path and fail-closed checks without importing backend fixtures."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from tests.backend_fixture_source import (
    CHECKOUT_ENV, FIXTURE_FILES, OWNER_FILES, backend_fixture_checkout,
)


class BackendFixtureSourceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.frontend = self.root / 'joint' / 'frontend'
        self.frontend.mkdir(parents=True)
        self.package = self.root / 'installed' / 'site-packages' / 'auto_g16'
        for relative in OWNER_FILES:
            path = self.package / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'synthetic installed owner: ' + relative.encode())
        self.enterContext(patch.dict(os.environ))
        os.environ.pop(CHECKOUT_ENV, None)

    def checkout(self, root):
        (root / 'scripts').mkdir(parents=True, exist_ok=True)
        for relative in FIXTURE_FILES:
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('raise AssertionError("fixture must not be imported by discovery")\n')
        for relative in OWNER_FILES:
            path = root / 'auto_g16' / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((self.package / relative).read_bytes())
        return root

    def resolve(self):
        before = list(sys.path)
        try:
            return backend_fixture_checkout(self.frontend, self.package)
        finally:
            self.assertEqual(sys.path, before)

    def test_explicit_joint_root_overrides_legacy_checkout_without_importing_it(self):
        joint = self.checkout(self.frontend.parent)
        legacy = self.checkout(self.frontend / '.ci' / 'backend')
        (legacy / 'auto_g16' / OWNER_FILES[0]).write_bytes(b'wrong owner')
        os.environ[CHECKOUT_ENV] = str(joint)
        self.assertEqual(self.resolve(), joint)

    def test_legacy_ci_checkout_remains_supported(self):
        legacy = self.checkout(self.frontend / '.ci' / 'backend')
        self.assertEqual(self.resolve(), legacy)

    def test_source_checkout_fallback_remains_supported(self):
        root = self.checkout(self.root / 'source-backend')
        self.package = root / 'auto_g16'
        self.assertEqual(self.resolve(), root)

    def test_invalid_explicit_path_never_falls_back_to_valid_legacy(self):
        self.checkout(self.frontend / '.ci' / 'backend')
        not_directory = self.root / 'file'
        not_directory.write_text('not a checkout')
        for value in ('', 'relative/path', str(self.root / 'missing'),
                      str(not_directory), str(self.frontend)):
            with self.subTest(value=value), patch.dict(os.environ, {CHECKOUT_ENV: value}):
                with self.assertRaises(RuntimeError):
                    self.resolve()

    def test_missing_owner_or_fixture_or_scripts_rejects(self):
        for index, relative in enumerate((*FIXTURE_FILES, 'scripts', 'auto_g16/' + OWNER_FILES[0])):
            with self.subTest(relative=relative):
                checkout = self.checkout(self.root / f'incomplete-{index}')
                path = checkout / relative
                path.rmdir() if path.is_dir() else path.unlink()
                with patch.dict(os.environ, {CHECKOUT_ENV: str(checkout)}), self.assertRaises(RuntimeError):
                    self.resolve()

    def test_each_checked_owner_mismatch_rejects_before_fixture_import(self):
        checkout = self.checkout(self.frontend.parent)
        os.environ[CHECKOUT_ENV] = str(checkout)
        for relative in OWNER_FILES:
            with self.subTest(relative=relative):
                path = checkout / 'auto_g16' / relative
                original = path.read_bytes()
                path.write_bytes(original + b' changed')
                with self.assertRaisesRegex(RuntimeError, 'fixture/installed owner mismatch'):
                    self.resolve()
                path.write_bytes(original)
