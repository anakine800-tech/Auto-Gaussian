#!/usr/bin/env python3
"""Offline hostile tests for the W5 -> W6 existing-job lineage owner."""

from __future__ import annotations

import copy
import importlib
import json
import os
import pickle
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.test_direct_trusted_session_composition import PortableSessionFixture


ROOT = Path(__file__).parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import direct_durable_submission_journal as W2  # noqa: E402
import direct_existing_job_lineage as LINEAGE  # noqa: E402
import direct_one_hop_transport as W5  # noqa: E402
import direct_trusted_session_composition as SESSION  # noqa: E402


class DirectExistingJobLineageTests(unittest.TestCase):
    maxDiff = None

    @staticmethod
    def completed_fixture(raw: str, job_id: str = "731.master") -> tuple[PortableSessionFixture, dict[str, object], bytes]:
        fixture = PortableSessionFixture(Path(raw).resolve())
        capability = fixture.compose()
        lease = capability.consume_for_w5_once()
        seam = SESSION.consume_w5_operation_seam_once(lease)
        receipt = W5._consume_with_test_driver_once(
            seam,
            W5._test_driver(stdout=(job_id + "\n").encode("ascii")),
            _test_token=W5._TEST_DRIVER_TOKEN,
        ).portable_projection()
        return fixture, receipt, W5.canonical_bytes(receipt)

    @staticmethod
    def owner(fixture: PortableSessionFixture) -> LINEAGE.DirectExistingJobLineageOwner:
        return LINEAGE.DirectExistingJobLineageOwner._for_fake_local_testing(
            durable_state_root=fixture.state,
            _test_token=LINEAGE._TEST_OWNER_TOKEN,
        )

    @staticmethod
    def rederive_receipt(document: dict[str, object]) -> dict[str, object]:
        value = copy.deepcopy(document)
        value["receipt_id"] = "direct-submission-receipt-" + W5.digest(
            {key: item for key, item in value.items() if key not in {"receipt_id", "result_payload_sha256"}}
        )
        value["result_payload_sha256"] = W5.digest({**value, "result_payload_sha256": ""})
        return value

    @staticmethod
    def different_sha(value: str) -> str:
        return ("a" if value[0] != "a" else "b") * 64

    def test_success_is_owner_issued_nonportable_fork_revoked_and_single_use(self) -> None:
        with tempfile.TemporaryDirectory(prefix="auto-g16-existing-lineage-success-") as raw:
            fixture, receipt, receipt_raw = self.completed_fixture(raw)
            try:
                capability = self.owner(fixture).issue_once(receipt_raw, fixture.artifacts)
                capability.assert_current()
                projection = capability.portable_projection()
                self.assertEqual(projection, LINEAGE.validate_lineage_projection(projection))
                self.assertEqual(projection["binding"]["job_id"], receipt["qsub"]["job_id"])
                self.assertEqual(projection["binding"]["qsub_calls"], "1")
                self.assertFalse(projection["authority"]["authorizes_effect"])
                self.assertFalse(projection["authority"]["portable_projection_authorizes_read"])
                self.assertFalse(projection["authority"]["scientific_acceptance"])
                self.assertFalse(projection["authority"]["query_implemented"])
                self.assertFalse(projection["authority"]["fetch_implemented"])
                for operation in (copy.copy, copy.deepcopy, pickle.dumps):
                    with self.assertRaises(TypeError):
                        operation(capability)
                with self.assertRaises(TypeError):
                    LINEAGE.DirectSubmittedJobReadCapability()

                read_fd, write_fd = os.pipe()
                pid = os.fork()
                if pid == 0:  # pragma: no cover - child assertion reported to parent
                    os.close(read_fd)
                    try:
                        capability.assert_current()
                    except BaseException:
                        os.write(write_fd, b"rejected")
                    else:
                        os.write(write_fd, b"accepted")
                    os.close(write_fd)
                    os._exit(0)
                os.close(write_fd)
                child_result = os.read(read_fd, 64)
                os.close(read_fd)
                waited, status = os.waitpid(pid, 0)
                self.assertEqual(waited, pid)
                self.assertEqual(os.waitstatus_to_exitcode(status), 0)
                self.assertEqual(child_result, b"rejected")
                capability.assert_current()

                lease = capability.consume_once()
                lease.assert_current()
                with self.assertRaises(LINEAGE.DirectExistingJobLineageError):
                    capability.assert_current()
                with self.assertRaises(LINEAGE.DirectExistingJobLineageError):
                    capability.consume_once()
                for operation in (copy.copy, copy.deepcopy, pickle.dumps):
                    with self.assertRaises(TypeError):
                        operation(lease)
                lease.close_once()
                with self.assertRaises(LINEAGE.DirectExistingJobLineageError):
                    lease.assert_current()
            finally:
                fixture.close()

    def test_every_artifact_zero_hash_rejects_after_result_rehash(self) -> None:
        with tempfile.TemporaryDirectory(prefix="auto-g16-existing-lineage-artifact-zero-") as raw:
            fixture, _receipt, receipt_raw = self.completed_fixture(raw)
            try:
                capability = self.owner(fixture).issue_once(receipt_raw, fixture.artifacts)
                projection = capability.portable_projection()
                capability.consume_once().close_once()
                for field in sorted(projection["artifact_sha256"]):
                    with self.subTest(field=field):
                        hostile = copy.deepcopy(projection)
                        hostile["artifact_sha256"][field] = LINEAGE.ZERO_SHA
                        hostile["result_payload_sha256"] = LINEAGE.digest(
                            {**hostile, "result_payload_sha256": ""}
                        )
                        with self.assertRaisesRegex(
                            LINEAGE.DirectExistingJobLineageError,
                            f"lineage artifact {field}",
                        ):
                            LINEAGE.validate_lineage_projection(hostile)
            finally:
                fixture.close()

    def test_receipt_fields_and_combined_rebinding_fail_even_after_rehash(self) -> None:
        with tempfile.TemporaryDirectory(prefix="auto-g16-existing-lineage-receipt-") as raw:
            fixture, receipt, _receipt_raw = self.completed_fixture(raw)
            try:
                mutations: dict[str, object] = {
                    "binding_payload_sha256": self.different_sha(receipt["binding_payload_sha256"]),
                    "journal_id": "direct-durable-submission-journal-" + "c" * 64,
                    "attempt_id": "qsub-attempt-" + "c" * 64,
                    "project": str(receipt["project"]) + "-foreign",
                    "input_sha256": self.different_sha(receipt["input_sha256"]),
                    "authorization_payload_sha256": self.different_sha(receipt["authorization_payload_sha256"]),
                }
                for field, replacement in mutations.items():
                    with self.subTest(field=field):
                        hostile = copy.deepcopy(receipt)
                        hostile[field] = replacement
                        hostile = self.rederive_receipt(hostile)
                        self.assertEqual(hostile, W5.validate_submission_receipt(hostile))
                        with self.assertRaises(LINEAGE.DirectExistingJobLineageError):
                            self.owner(fixture).issue_once(W5.canonical_bytes(hostile), fixture.artifacts)

                hostile_job = copy.deepcopy(receipt)
                hostile_job["outcome"]["job_id"] = "999.master"
                hostile_job["outcome"]["outcome_payload_sha256"] = W5.digest(
                    {key: item for key, item in hostile_job["outcome"].items() if key != "outcome_payload_sha256"}
                )
                hostile_job["qsub"]["job_id"] = "999.master"
                hostile_job["qsub"]["outcome_payload_sha256"] = hostile_job["outcome"]["outcome_payload_sha256"]
                hostile_job = self.rederive_receipt(hostile_job)
                self.assertEqual(hostile_job, W5.validate_submission_receipt(hostile_job))
                with self.assertRaises(LINEAGE.DirectExistingJobLineageError):
                    self.owner(fixture).issue_once(W5.canonical_bytes(hostile_job), fixture.artifacts)

                hostile_calls = copy.deepcopy(receipt)
                hostile_calls["qsub"]["calls"] = "2"
                hostile_calls = self.rederive_receipt(hostile_calls)
                with self.assertRaises(W5.DirectOneHopTransportError):
                    W5.validate_submission_receipt(hostile_calls)
                with self.assertRaises(LINEAGE.DirectExistingJobLineageError):
                    self.owner(fixture).issue_once(W5.canonical_bytes(hostile_calls), fixture.artifacts)

                combined = copy.deepcopy(receipt)
                combined.update(mutations)
                combined = self.rederive_receipt(combined)
                self.assertEqual(combined, W5.validate_submission_receipt(combined))
                combined_raw = W5.canonical_bytes(combined)
                project = fixture.root / receipt["project"]
                (project / W5.SUBMISSION_RECEIPT_BASENAME).write_bytes(combined_raw)
                with self.assertRaises(LINEAGE.DirectExistingJobLineageError):
                    self.owner(fixture).issue_once(combined_raw, fixture.artifacts)
            finally:
                fixture.close()

    def test_w2_unknown_started_only_inventory_and_receipt_w2_splice_are_reconciliation_only(self) -> None:
        cases = ("unknown", "started-only", "duplicate")
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory(prefix=f"auto-g16-existing-lineage-{case}-") as raw:
                fixture, receipt, receipt_raw = self.completed_fixture(raw)
                try:
                    journal = fixture.state / receipt["journal_id"]
                    terminal_path = journal / W2.TERMINAL_BASENAME
                    if case == "unknown":
                        terminal = json.loads(terminal_path.read_bytes())
                        terminal.update(
                            {
                                "event_type": "effect_outcome_unknown",
                                "state": "submission_uncertain",
                                "outcome": "unknown",
                                "evidence_sha256": "e" * 64,
                            }
                        )
                        terminal["event_payload_sha256"] = ""
                        terminal["event_payload_sha256"] = W2.digest(terminal)
                        terminal_path.write_bytes(W2.canonical_bytes(terminal))
                    elif case == "started-only":
                        terminal_path.unlink()
                    else:
                        (journal / "000002-duplicate.json").write_bytes(b"{}\n")
                    expected = (
                        LINEAGE.ExistingJobReconciliationOnly
                        if case in {"unknown", "started-only"}
                        else LINEAGE.DirectExistingJobLineageError
                    )
                    with self.assertRaises(expected):
                        self.owner(fixture).issue_once(receipt_raw, fixture.artifacts)
                finally:
                    fixture.close()

        with tempfile.TemporaryDirectory(prefix="auto-g16-existing-lineage-splice-a-") as raw_a, \
                tempfile.TemporaryDirectory(prefix="auto-g16-existing-lineage-splice-b-") as raw_b:
            fixture_a, receipt_a, receipt_raw_a = self.completed_fixture(raw_a, "811.master")
            fixture_b, receipt_b, _receipt_raw_b = self.completed_fixture(raw_b, "812.master")
            try:
                shutil.copytree(
                    fixture_b.state / receipt_b["journal_id"],
                    fixture_b.state / receipt_a["journal_id"],
                )
                owner = LINEAGE.DirectExistingJobLineageOwner._for_fake_local_testing(
                    durable_state_root=fixture_b.state,
                    _test_token=LINEAGE._TEST_OWNER_TOKEN,
                )
                with self.assertRaises(LINEAGE.DirectExistingJobLineageError):
                    owner.issue_once(receipt_raw_a, fixture_a.artifacts)
            finally:
                fixture_a.close()
                fixture_b.close()

    def test_remote_receipt_symlink_hardlink_ancestor_symlink_and_replacement_fail(self) -> None:
        for case in ("receipt-symlink", "receipt-hardlink", "ancestor-symlink"):
            with self.subTest(case=case), tempfile.TemporaryDirectory(prefix=f"auto-g16-existing-lineage-{case}-") as raw:
                fixture, receipt, receipt_raw = self.completed_fixture(raw)
                try:
                    project = fixture.root / receipt["project"]
                    receipt_path = project / W5.SUBMISSION_RECEIPT_BASENAME
                    if case == "receipt-symlink":
                        original = project / "saved-receipt.json"
                        receipt_path.rename(original)
                        receipt_path.symlink_to(original.name)
                    elif case == "receipt-hardlink":
                        os.link(receipt_path, project / "receipt-hardlink.json")
                    else:
                        real_root = fixture.root.with_name(fixture.root.name + "-real")
                        fixture.root.rename(real_root)
                        fixture.root.symlink_to(real_root.name, target_is_directory=True)
                    with self.assertRaises((LINEAGE.DirectExistingJobLineageError, OSError)):
                        self.owner(fixture).issue_once(receipt_raw, fixture.artifacts)
                finally:
                    fixture.close()

        with tempfile.TemporaryDirectory(prefix="auto-g16-existing-lineage-replacement-") as raw:
            fixture, receipt, receipt_raw = self.completed_fixture(raw)
            try:
                capability = self.owner(fixture).issue_once(receipt_raw, fixture.artifacts)
                project = fixture.root / receipt["project"]
                original = project.with_name(project.name + "-original")
                project.rename(original)
                project.mkdir(mode=0o700)
                (project / W5.SUBMISSION_RECEIPT_BASENAME).write_bytes(receipt_raw)
                with self.assertRaises(LINEAGE.DirectExistingJobLineageError):
                    capability.assert_current()
            finally:
                fixture.close()

    def test_project_receipt_and_descriptor_identity_drift_fail_currentness(self) -> None:
        for case in ("receipt-replaced", "project-named-drift", "descriptor-reuse"):
            with self.subTest(case=case), tempfile.TemporaryDirectory(prefix=f"auto-g16-existing-lineage-{case}-") as raw:
                fixture, receipt, receipt_raw = self.completed_fixture(raw)
                try:
                    capability = self.owner(fixture).issue_once(receipt_raw, fixture.artifacts)
                    project = fixture.root / receipt["project"]
                    receipt_path = project / W5.SUBMISSION_RECEIPT_BASENAME
                    if case == "receipt-replaced":
                        saved = project / "submission-receipt-original.json"
                        receipt_path.rename(saved)
                        receipt_path.write_bytes(receipt_raw)
                    elif case == "project-named-drift":
                        project.chmod(0o750)
                    else:
                        with mock.patch.object(LINEAGE, "_directory_identity", return_value=(999,) * 6):
                            with self.assertRaises(LINEAGE.DirectExistingJobLineageError):
                                capability.assert_current()
                        continue
                    with self.assertRaises(LINEAGE.DirectExistingJobLineageError):
                        capability.assert_current()
                finally:
                    fixture.close()

    def test_source_module_reload_and_predecessor_rebinding_fail_before_issuance(self) -> None:
        fixed_clean_probe_environment = {
            "AUTO_G16_RUNTIME_CONFIG": "/proc/auto-g16-disabled-runtime-config",
            "HOME": "/proc/auto-g16-disabled-home",
            "LANG": "C",
            "LC_ALL": "C",
        }
        self.assertEqual(
            fixed_clean_probe_environment,
            SESSION.FIXED_CLEAN_EXEC_ENVIRONMENT,
        )
        with self.assertRaisesRegex(
            LINEAGE.DirectExistingJobLineageError,
            "fixed -I -S server process",
        ):
            LINEAGE.DirectExistingJobLineageOwner.production()
        with tempfile.TemporaryDirectory(prefix="auto-g16-existing-lineage-rebind-") as raw:
            fixture, _receipt, receipt_raw = self.completed_fixture(raw)
            try:
                snapshot = LINEAGE._MODULE_BINDING.source
                hostile_snapshot = LINEAGE._SourceSnapshot(snapshot.path, snapshot.identity, "a" * 64)
                with mock.patch.object(LINEAGE, "_stable_source", return_value=hostile_snapshot):
                    with self.assertRaisesRegex(LINEAGE.DirectExistingJobLineageError, "source, module"):
                        self.owner(fixture).issue_once(receipt_raw, fixture.artifacts)
                with mock.patch.object(W5, "_assert_production_binding", return_value=None):
                    with self.assertRaisesRegex(LINEAGE.DirectExistingJobLineageError, "predecessor owner binding"):
                        self.owner(fixture).issue_once(receipt_raw, fixture.artifacts)
                with mock.patch.object(W2, "_validate_event", return_value={}):
                    with self.assertRaisesRegex(LINEAGE.DirectExistingJobLineageError, "predecessor owner binding"):
                        self.owner(fixture).issue_once(receipt_raw, fixture.artifacts)
            finally:
                fixture.close()

        probe = r'''
import importlib, pathlib, sys
scripts = pathlib.Path(sys.argv[1]).resolve()
sys.path.insert(0, str(scripts))
import direct_existing_job_lineage as owner
try:
    importlib.reload(owner)
except ImportError:
    print("RELOAD_REJECTED")
else:
    raise AssertionError("RELOAD_ACCEPTED")
'''
        result = subprocess.run(
            [sys.executable, "-I", "-S", "-c", probe, str(SCRIPTS)],
            check=False,
            capture_output=True,
            text=True,
            env=fixed_clean_probe_environment,
            cwd="/",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "RELOAD_REJECTED\n")

        clean_probe = r'''
import pathlib, sys
scripts = pathlib.Path(sys.argv[1]).resolve()
sys.path.insert(0, str(scripts))
import direct_existing_job_lineage as owner
value = owner.DirectExistingJobLineageOwner.production()
if value._state_root is not owner.SESSION.FIXED_PRODUCTION_DURABLE_STATE_ROOT:
    raise AssertionError("PRODUCTION_ROOT_REBOUND")
print("FIXED_CLEAN_EXEC_OWNER_READY_NO_EFFECT")
'''
        clean = subprocess.run(
            [sys.executable, "-I", "-S", "-c", clean_probe, str(SCRIPTS)],
            check=False,
            capture_output=True,
            text=True,
            env=fixed_clean_probe_environment,
            cwd="/",
        )
        self.assertEqual(clean.returncode, 0, clean.stderr)
        self.assertEqual(clean.stdout, "FIXED_CLEAN_EXEC_OWNER_READY_NO_EFFECT\n")


if __name__ == "__main__":
    unittest.main()
