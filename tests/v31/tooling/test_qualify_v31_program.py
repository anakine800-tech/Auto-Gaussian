"""Synthetic local-file evidence checks; no real program is invoked."""

from __future__ import annotations

import ast
import base64
from contextlib import redirect_stderr, redirect_stdout
import hashlib
from io import StringIO
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from scripts import qualify_v31_program as Q
from auto_g16.execution.models import _XTB_REQUIRED_RUNTIME_DATA_FILES, _canonical_xtb_runtime_data_manifest


class LocalProgramInventoryTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.binary = self.root / "program"
        self.binary.write_bytes(b"synthetic supplied program bytes\n")
        self.data = self.root / "share"
        self.data.mkdir()
        for name in _XTB_REQUIRED_RUNTIME_DATA_FILES:
            (self.data / name).write_bytes(("synthetic " + name).encode())

    def run_inventory(self, kind="xtb", **changes):
        arguments = {"kind": kind, "path": str(self.binary),
                     "runtime_data": str(self.data) if kind == "xtb" else None}
        arguments.update(changes)
        return Q.qualify_program(**arguments)

    def claim(self, *, kind="crest", version="3.0.2"):
        return {"schema": "auto-g16-v31-captured-version-claim/1", "kind": kind,
                "binary_identity": {"canonical_path": str(self.binary), "size_bytes": self.binary.stat().st_size,
                                    "sha256": hashlib.sha256(self.binary.read_bytes()).hexdigest()},
                "reported_version": version, "captured_at": "2026-09-11T00:00:00Z",
                "stdout_base64": base64.b64encode(f"synthetic captured version {version}\n".encode()).decode(),
                "stderr_base64": ""}

    def write_claim(self, value):
        evidence = self.root / "captured.json"
        evidence.write_bytes(json.dumps(value).encode())
        return str(evidence)

    def test_xtb_complete_inventory_uses_existing_canonical_manifest_contract(self):
        nested = self.data / "extra"
        nested.mkdir()
        (nested / "data.txt").write_bytes(b"extra retained content")
        report = self.run_inventory()
        self.assertEqual(report["sha256"], hashlib.sha256(self.binary.read_bytes()).hexdigest())
        self.assertEqual(report["canonical_path"], str(self.binary))
        self.assertEqual(report["size_bytes"], self.binary.stat().st_size)
        runtime = report["runtime_data"]
        files = runtime["manifest"]["files"]
        expected = set(_XTB_REQUIRED_RUNTIME_DATA_FILES) | {"extra/data.txt"}
        self.assertEqual(set(files), expected)
        for name in expected:
            raw = (self.data / name).read_bytes()
            self.assertEqual(files[name], {"sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw)})
        canonical = _canonical_xtb_runtime_data_manifest(json.dumps(runtime["manifest"]).encode())
        self.assertEqual(runtime["manifest_canonical_utf8"].encode(), canonical)
        self.assertEqual(runtime["manifest_sha256"], hashlib.sha256(canonical).hexdigest())
        self.assertEqual(runtime["manifest_size_bytes"], len(canonical))
        self.assertIsNone(report["version"])
        self.assertEqual(report["version_verification"], "UNVERIFIED_PROBE_DEFERRED")

    def test_matching_captured_claim_stays_unverified_and_does_not_authorize(self):
        report = self.run_inventory("crest", version_evidence=self.write_claim(self.claim()))
        self.assertEqual(report["version"], "3.0.2")
        self.assertEqual(report["version_verification"], "UNVERIFIED_CAPTURED_CLAIM")
        self.assertEqual(report["production_qualification"], "UNVERIFIED")
        for field in ("live_authority", "program_executed", "executable_format_verified"):
            self.assertIs(report[field], False)
        self.assertIs(report["version_evidence"]["capture_authenticity_verified"], False)
        self.assertIsNone(report["runtime_data"])

    def test_xtb_version_claim_has_no_implicit_supported_version_policy(self):
        report = self.run_inventory(version_evidence=self.write_claim(self.claim(kind="xtb", version="6.7.1")))
        self.assertEqual(report["version"], "6.7.1")
        self.assertEqual(report["production_qualification"], "UNVERIFIED")

    def test_crest_wrong_or_decorated_version_is_rejected(self):
        for version in ("3.0.1", "3.0.20", "3.0.2-dev", "3.0.2+patched"):
            with self.subTest(version=version), self.assertRaisesRegex(Q.QualificationError, "exactly reported version 3.0.2"):
                self.run_inventory("crest", version_evidence=self.write_claim(self.claim(version=version)))

    def test_claim_cannot_splice_identity_kind_or_detach_version_from_output(self):
        mutations = (("kind", "xtb"), ("binary_identity", {}), ("captured_at", "2026-02-30T00:00:00Z"),
                     ("stdout_base64", base64.b64encode(b"version 3.0.20").decode()),
                     ("stderr_base64", "not base64"), ("extra", "not allowed"))
        for field, value in mutations:
            with self.subTest(field=field):
                claim = self.claim()
                claim[field] = value
                with self.assertRaises((Q.QualificationError, ValueError)):
                    self.run_inventory("crest", version_evidence=self.write_claim(claim))
        for field, value in (("sha256", "a" * 64), ("size_bytes", True), ("canonical_path", str(self.root / "other"))):
            claim = self.claim()
            claim["binary_identity"][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.run_inventory("crest", version_evidence=self.write_claim(claim))

    def test_duplicate_or_oversized_version_evidence_is_rejected(self):
        path = self.root / "captured.json"
        raw = json.dumps(self.claim())
        for content in (raw[:-1] + ', "kind": "crest"}', " " * (Q.MAX_VERSION_EVIDENCE_BYTES + 1)):
            path.write_text(content)
            with self.assertRaises(ValueError):
                self.run_inventory("crest", version_evidence=str(path))

    def test_symlinked_binary_parent_data_and_nested_entries_are_rejected(self):
        alias = self.root / "alias"
        alias.symlink_to(self.binary)
        with self.assertRaises(ValueError):
            self.run_inventory("crest", path=str(alias))
        alias.unlink()
        alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.run_inventory("crest", path=str(alias / "program"))
        alias.unlink()
        alias.symlink_to(self.data, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.run_inventory(runtime_data=str(alias))
        (self.data / "link").symlink_to(self.binary)
        with self.assertRaises(ValueError):
            self.run_inventory()

    def test_noncanonical_paths_and_runtime_data_kind_mismatch_reject(self):
        for path in ("program", str(self.binary) + "/", str(self.root) + "/./program", "/" + str(self.binary)):
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.run_inventory("crest", path=path)
        with self.assertRaises(ValueError):
            self.run_inventory(runtime_data=None)
        with self.assertRaises(ValueError):
            self.run_inventory("crest", runtime_data=str(self.data))

    def test_missing_empty_special_or_over_budget_runtime_data_rejects(self):
        one = self.data / sorted(_XTB_REQUIRED_RUNTIME_DATA_FILES)[0]
        one.unlink()
        with self.assertRaises(ValueError):
            self.run_inventory()
        one.write_bytes(b"")
        with self.assertRaises(ValueError):
            self.run_inventory()
        one.write_bytes(b"restored")
        with mock.patch.object(Q, "MAX_ENTRIES", 1), self.assertRaises(ValueError):
            self.run_inventory()
        fifo = self.data / "pipe"
        os.mkfifo(fifo)
        with self.assertRaises(ValueError):
            self.run_inventory()

    def test_final_verification_detects_added_removed_and_replaced_files(self):
        original = Q._LocalReader.verify
        for mutation in ("added", "removed", "binary-replaced", "directory-replaced"):
            with self.subTest(mutation=mutation):
                def changed(reader):
                    if mutation == "added":
                        (self.data / "added").write_bytes(b"unlisted")
                    elif mutation == "removed":
                        (self.data / "added").unlink()
                    elif mutation == "binary-replaced":
                        self.binary.rename(self.root / "old-program")
                        self.binary.write_bytes(b"synthetic supplied program bytes\n")
                    else:
                        self.data.rename(self.root / "old-share")
                        self.data.mkdir()
                    original(reader)
                with mock.patch.object(Q._LocalReader, "verify", changed), self.assertRaises((ValueError, OSError)):
                    self.run_inventory()

    def test_in_place_modification_during_read_rejects(self):
        original = os.read
        changed = False
        def read(fd, length):
            nonlocal changed
            content = original(fd, length)
            if content and not changed:
                changed = True
                self.binary.write_bytes(b"changed length")
            return content
        with mock.patch.object(Q.os, "read", read), self.assertRaises(ValueError):
            self.run_inventory("crest")

    def test_cli_output_and_open_flags_have_no_write_or_execution_authority(self):
        opened = os.open
        flags_seen = []
        def read_only(path, flags, *args, **kwargs):
            flags_seen.append(flags)
            self.assertFalse(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
            return opened(path, flags, *args, **kwargs)
        output = StringIO()
        with mock.patch.object(Q.os, "open", read_only), mock.patch("subprocess.Popen", side_effect=AssertionError("program execution forbidden")), redirect_stdout(output):
            self.assertEqual(Q.main(["--kind", "crest", "--path", str(self.binary)]), 0)
        self.assertTrue(flags_seen)
        self.assertEqual(json.loads(output.getvalue())["status"], "LOCAL_CONTENT_INVENTORY_COMPLETE")
        self.assertFalse((self.root / "report.json").exists())
        tree = ast.parse(Path(Q.__file__).read_text())
        imports = {node.names[0].name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import)}
        self.assertFalse(imports & {"subprocess", "socket", "urllib", "requests", "paramiko"})
        output = StringIO()
        with redirect_stdout(output), redirect_stderr(StringIO()), self.assertRaises(SystemExit) as stopped:
            Q.main(["--kind", "crest", "--path", "relative"])
        self.assertEqual(stopped.exception.code, 2)
        self.assertEqual(output.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
