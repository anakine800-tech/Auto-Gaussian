#!/usr/bin/env python3
"""Focused hostile tests for the non-authorizing direct qstat evidence core."""

from __future__ import annotations

import ast
import copy
import hashlib
import json
import re
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import direct_read_only_evidence as EVIDENCE  # noqa: E402
import skill_package as SKILL_PACKAGE  # noqa: E402


FIXTURE_PATH = ROOT / "tests/fixtures/rtwin_pbs/direct_read_only_qstat_cases.json"
REQUESTED = "2026-08-06T00:00:00.000000Z"
COLLECTED = "2026-08-06T00:00:01.000000Z"
RECEIVED = "2026-08-06T00:00:02.000000Z"

# Frozen current W5 independent-PBS stdout grammar, minus no semantics.  This
# parity test is an integration dependency until W5 consumes one shared owner.
W5_JOB_ID_STDOUT_RE = re.compile(
    r"^(?P<sequence>[1-9][0-9]{0,19})\.(?P<server>[A-Za-z0-9][A-Za-z0-9.-]{0,127})\n$"
)


class DirectReadOnlyEvidenceTests(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        if set(cls.fixture) != {"schema", "job_id", "job_name", "cases"}:
            raise AssertionError("direct qstat fixture is not closed")

    def binding(self, *, job_id: str | None = None) -> EVIDENCE.DirectJobBinding:
        return EVIDENCE.DirectJobBinding(
            project=self.fixture["job_name"],
            job_id=job_id or self.fixture["job_id"],
            attempt_id="qsub-attempt-" + "a" * 64,
            input_sha256="b" * 64,
            direct_binding_sha256="c" * 64,
        )

    def observation(
        self,
        case: str,
        *,
        stdout: bytes | None = None,
        stderr: bytes | None = None,
        returncode: int | None | object = object(),
        timed_out: bool = False,
        eof_complete: bool = True,
        requested_at: str = REQUESTED,
        collected_at: str = COLLECTED,
        received_at: str = RECEIVED,
    ) -> EVIDENCE.QstatObservation:
        value = self.fixture["cases"][case]
        effective_returncode = value["returncode"] if type(returncode) is object else returncode
        return EVIDENCE.QstatObservation(
            returncode=effective_returncode,  # type: ignore[arg-type]
            stdout=value["stdout"].encode() if stdout is None else stdout,
            stderr=value["stderr"].encode() if stderr is None else stderr,
            timed_out=timed_out,
            eof_complete=eof_complete,
            requested_at=requested_at,
            collected_at=collected_at,
            received_at=received_at,
        )

    def classification(self, case: str, **changes: object) -> EVIDENCE.QstatClassification:
        observation = self.observation(case, **changes)
        return EVIDENCE.classify_qstat_bytes(
            expected_job_id=self.fixture["job_id"],
            expected_job_name=self.fixture["job_name"],
            returncode=observation.returncode,
            stdout=observation.stdout,
            stderr=observation.stderr,
            timed_out=observation.timed_out,
            eof_complete=observation.eof_complete,
        )

    def evidence(self, case: str, **changes: object) -> EVIDENCE.DirectQstatEvidence:
        return EVIDENCE.build_qstat_evidence(
            self.binding(),
            self.observation(case, **changes),
        )

    def rehash_evidence(self, document: dict[str, object]) -> dict[str, object]:
        changed = copy.deepcopy(document)
        qstat = changed["qstat"]
        observation_projection = copy.deepcopy(qstat)
        observation_projection.pop("observation_payload_sha256")
        qstat["observation_payload_sha256"] = EVIDENCE.digest(observation_projection)
        changed["qstat_evidence_sha256"] = ""
        changed["qstat_evidence_sha256"] = EVIDENCE.digest(changed)
        return changed

    def test_fixture_q_r_h_e_terminal_absent_unknown_matrix(self) -> None:
        self.assertEqual(self.fixture["schema"], "auto-g16-direct-read-only-qstat-cases/1")
        for name, case in self.fixture["cases"].items():
            with self.subTest(case=name):
                self.assertEqual(
                    set(case),
                    {"returncode", "stdout", "stderr", "status", "lifecycle"},
                )
                result = self.classification(name)
                self.assertEqual(result.status, case["status"])
                self.assertEqual(result.lifecycle, case["lifecycle"])
                evidence = self.evidence(name).document()
                self.assertEqual(evidence["state"], case["lifecycle"])
                self.assertEqual(evidence["qstat"]["status"], case["status"])
                self.assertFalse(evidence["authority"]["authorizes_effect"])
                self.assertFalse(evidence["authority"]["scientific_acceptance"])
                self.assertFalse(evidence["authority"]["production_supported"])

    def test_exact_independent_pbs_job_id_matches_frozen_w5_grammar(self) -> None:
        candidates = {
            "1.a": True,
            "9.master": True,
            "123.server.example": True,
            "12345678901234567890.master": True,
            "123456789012345678901.master": False,
            "123": False,
            "0.master": False,
            "01.master": False,
            "1.": False,
            ".master": False,
            "1.master\n2.master": False,
            "1.master;id": False,
            " 1.master": False,
        }
        for candidate, accepted in candidates.items():
            with self.subTest(candidate=candidate):
                core_accepts = EVIDENCE.JOB_ID_RE.fullmatch(candidate) is not None
                w5_accepts = W5_JOB_ID_STDOUT_RE.fullmatch(candidate + "\n") is not None
                self.assertEqual(core_accepts, w5_accepts)
                self.assertEqual(core_accepts, accepted)

    def test_parser_is_single_block_closed_and_duplicate_free(self) -> None:
        base = self.fixture["cases"]["running"]["stdout"].encode()
        parsed = EVIDENCE.parse_qstat_single_job(base, self.fixture["job_id"])
        self.assertEqual(parsed["job_id"], self.fixture["job_id"])
        self.assertEqual(parsed["fields"]["session_id"], "31415")
        hostile = {
            "duplicate-key": base.replace(b"    job_state = R\n", b"    job_state = R\n    job_state = Q\n"),
            "second-block": base + base,
            "unknown-field": base.replace(b"    job_state = R\n", b"    job_state = R\n    server_extension = x\n"),
            "continued-line": base.replace(b"    job_state = R\n", b"    job_state = R\n\tcontinued\n"),
            "blank-line": base.replace(b"    job_state = R\n", b"\n    job_state = R\n"),
            "missing-final-lf": base[:-1],
            "unsupported-state": base.replace(b"job_state = R", b"job_state = X"),
            "duplicate-header": base.replace(b"    job_state = R\n", b"Job Id: 123.master\n    job_state = R\n"),
        }
        for name, raw in hostile.items():
            with self.subTest(case=name):
                with self.assertRaises(EVIDENCE.DirectReadOnlyEvidenceError):
                    EVIDENCE.parse_qstat_single_job(raw, self.fixture["job_id"])
                result = EVIDENCE.classify_qstat_bytes(
                    expected_job_id=self.fixture["job_id"],
                    expected_job_name=self.fixture["job_name"],
                    returncode=0,
                    stdout=raw,
                    stderr=b"",
                    timed_out=False,
                    eof_complete=True,
                )
                self.assertEqual((result.status, result.record_present), ("unknown", None))

    def test_bounded_strict_utf8_timeout_and_eof_fail_closed(self) -> None:
        cases = {
            "oversize": self.classification(
                "running", stdout=b"x" * (EVIDENCE.MAX_QSTAT_OUTPUT_BYTES + 1)
            ),
            "invalid-utf8": self.classification("running", stdout=b"\xff"),
            "bom": self.classification("running", stdout=b"\xef\xbb\xbfJob Id: 123.master\n"),
            "timeout": self.classification("running", timed_out=True),
            "eof": self.classification("running", eof_complete=False),
        }
        expected = {
            "oversize": "output_too_large",
            "invalid-utf8": "invalid_utf8",
            "bom": "invalid_utf8",
            "timeout": "timeout",
            "eof": "incomplete_eof",
        }
        for name, result in cases.items():
            with self.subTest(case=name):
                self.assertEqual(result.status, "unknown")
                self.assertEqual(result.reason, expected[name])
                self.assertIsNone(result.record_present)

    def test_oversize_precedes_timeout_and_eof_through_owner_hashes(self) -> None:
        oversized = b"x" * (EVIDENCE.MAX_QSTAT_OUTPUT_BYTES + 1)
        for name, flags in (
            ("timeout", {"timed_out": True, "eof_complete": True}),
            ("incomplete-eof", {"timed_out": False, "eof_complete": False}),
        ):
            with self.subTest(case=name):
                observation = self.observation("running", stdout=oversized, **flags)
                classification = EVIDENCE.classify_qstat_bytes(
                    expected_job_id=self.fixture["job_id"],
                    expected_job_name=self.fixture["job_name"],
                    returncode=observation.returncode,
                    stdout=observation.stdout,
                    stderr=observation.stderr,
                    timed_out=observation.timed_out,
                    eof_complete=observation.eof_complete,
                )
                self.assertEqual(
                    (classification.status, classification.reason),
                    ("unknown", "output_too_large"),
                )
                document = EVIDENCE.build_qstat_evidence(
                    self.binding(), observation
                ).document()
                self.assertEqual(document["qstat"]["reason"], "output_too_large")
                self.assertEqual(document["state"], "unknown")
                qstat_projection = copy.deepcopy(document["qstat"])
                inner_hash = qstat_projection.pop("observation_payload_sha256")
                self.assertEqual(EVIDENCE.digest(qstat_projection), inner_hash)
                outer_projection = copy.deepcopy(document)
                outer_hash = outer_projection["qstat_evidence_sha256"]
                outer_projection["qstat_evidence_sha256"] = ""
                self.assertEqual(EVIDENCE.digest(outer_projection), outer_hash)
                self.assertEqual(EVIDENCE.validate_qstat_evidence(document), document)

    def test_exact_job_id_and_job_name_mismatch_or_injection_are_unknown(self) -> None:
        base = self.fixture["cases"]["running"]["stdout"].encode()
        variants = {
            "different-id": base.replace(b"123.master", b"124.master", 1),
            "id-injection": base.replace(b"123.master", b"123.master; id", 1),
            "second-id": base.replace(b"123.master", b"123.master\nJob Id: 124.master", 1),
            "different-name": base.replace(b"fixturejob", b"otherjob", 1),
        }
        for name, stdout in variants.items():
            with self.subTest(case=name):
                result = self.classification("running", stdout=stdout)
                self.assertEqual((result.status, result.record_present), ("unknown", None))
        for job_id in ("123", "123.master;id", "123.master\n124.master", "0.master"):
            with self.subTest(requested_job_id=job_id):
                with self.assertRaises(EVIDENCE.DirectReadOnlyEvidenceError):
                    EVIDENCE.classify_qstat_bytes(
                        expected_job_id=job_id,
                        expected_job_name=self.fixture["job_name"],
                        returncode=0,
                        stdout=base,
                        stderr=b"",
                        timed_out=False,
                        eof_complete=True,
                    )

    def test_only_exact_allowlisted_unknown_job_id_is_absent(self) -> None:
        exact = self.classification("absent")
        self.assertEqual((exact.status, exact.record_present), ("absent", False))
        variants = (
            (153, b"", b"qstat: Unknown Job Id 123.master"),
            (153, b"", b"qstat: Unknown Job Identifier 123.master\n"),
            (153, b"", b"qstat: Unknown Job Id 124.master\n"),
            (153, b"prefix\n", b"qstat: Unknown Job Id 123.master\n"),
            (1, b"", b"qstat: Unknown Job Id 123.master\n"),
            (255, b"", b"qstat: Unknown Job Id 123.master\n"),
        )
        for returncode, stdout, stderr in variants:
            with self.subTest(returncode=returncode, stdout=stdout, stderr=stderr):
                result = self.classification(
                    "absent",
                    returncode=returncode,
                    stdout=stdout,
                    stderr=stderr,
                )
                self.assertEqual((result.status, result.record_present), ("unknown", None))

    def test_rehashed_present_and_absent_stream_splices_fail_owner(self) -> None:
        present = self.evidence("terminal_c").document()
        absent = self.evidence("absent").document()
        absent_bytes = (
            f"qstat: Unknown Job Id {self.fixture['job_id']}\n".encode("utf-8")
        )
        self.assertEqual(
            absent["qstat"]["stdout_sha256"],
            hashlib.sha256(b"").hexdigest(),
        )
        self.assertEqual(absent["qstat"]["stderr_size_bytes"], str(len(absent_bytes)))
        self.assertEqual(
            absent["qstat"]["stderr_sha256"],
            hashlib.sha256(absent_bytes).hexdigest(),
        )

        mutations = []
        forged_present_documents = []
        for source, field, value in (
            (present, "stdout_size_bytes", "0"),
            (present, "stderr_size_bytes", "1"),
            (absent, "stdout_size_bytes", "1"),
            (absent, "stderr_size_bytes", "0"),
        ):
            changed = copy.deepcopy(source)
            changed["qstat"][field] = value
            rehashed = self.rehash_evidence(changed)
            mutations.append(rehashed)
            if source is present:
                forged_present_documents.append(rehashed)
        changed = copy.deepcopy(absent)
        changed["qstat"]["stderr_sha256"] = "d" * 64
        mutations.append(self.rehash_evidence(changed))
        for changed in mutations:
            with self.assertRaises(EVIDENCE.DirectReadOnlyEvidenceError):
                EVIDENCE.validate_qstat_evidence(changed)
        for changed in forged_present_documents:
            forged = EVIDENCE.DirectQstatEvidence(EVIDENCE.canonical_bytes(changed))
            with self.assertRaises(EVIDENCE.DirectReadOnlyEvidenceError):
                EVIDENCE.build_terminal_receipt(forged)

    def test_timestamp_fresh_stale_and_invalid_chronology(self) -> None:
        fresh = self.evidence("terminal_c").document()
        self.assertEqual(fresh["collection"]["freshness"], "fresh")
        self.assertEqual(fresh["collection"]["age_seconds"], "1")
        self.assertEqual(fresh["state"], "terminal")
        stale = self.evidence(
            "terminal_c",
            received_at="2026-08-06T00:03:00.000000Z",
        ).document()
        self.assertEqual(stale["collection"]["freshness"], "stale")
        self.assertEqual(stale["state"], "unknown")
        self.assertFalse(stale["terminal_receipt_eligible"])
        fractional_boundary = self.evidence(
            "terminal_c",
            received_at="2026-08-06T00:02:01.000001Z",
        ).document()
        self.assertEqual(fractional_boundary["collection"]["age_seconds"], "121")
        self.assertEqual(fractional_boundary["collection"]["freshness"], "stale")
        self.assertEqual(fractional_boundary["state"], "unknown")
        self.assertFalse(fractional_boundary["terminal_receipt_eligible"])
        chronology = self.evidence(
            "running",
            requested_at="2026-08-06T00:00:03.000000Z",
        ).document()
        self.assertEqual(chronology["collection"]["freshness"], "unknown")
        self.assertIsNone(chronology["collection"]["age_seconds"])
        self.assertEqual(chronology["state"], "unknown")
        with self.assertRaises(EVIDENCE.DirectReadOnlyEvidenceError):
            self.evidence("running", collected_at="2026-08-06T00:00:01Z")

    def test_scheduler_terminal_receipt_is_only_c_or_f_and_never_science(self) -> None:
        for case in ("terminal_c", "terminal_f"):
            with self.subTest(case=case):
                evidence = self.evidence(case)
                receipt = EVIDENCE.build_terminal_receipt(evidence).document(evidence)
                self.assertEqual(
                    receipt["schema"],
                    "gaussian-scheduler-terminal-evidence-receipt/1",
                )
                self.assertEqual(receipt["terminal_state"], "scheduler_terminal")
                self.assertFalse(receipt["authority"]["scientific_acceptance"])
                self.assertFalse(receipt["authority"]["production_supported"])
                self.assertNotIn("qstat", receipt)
        for case in ("queued", "running", "held", "exiting", "absent", "unknown_returncode"):
            with self.subTest(case=case):
                with self.assertRaisesRegex(
                    EVIDENCE.DirectReadOnlyEvidenceError,
                    "not fresh scheduler-terminal",
                ):
                    EVIDENCE.build_terminal_receipt(self.evidence(case))

    def test_hash_binding_and_cross_topology_splices_reject(self) -> None:
        evidence = self.evidence("terminal_c")
        source = evidence.document()
        direct_mutations = []
        changed = copy.deepcopy(source)
        changed["binding"]["input_sha256"] = "d" * 64
        direct_mutations.append(changed)
        changed = copy.deepcopy(source)
        changed["qstat"]["pbs_state"] = "F"
        direct_mutations.append(changed)
        changed = copy.deepcopy(source)
        changed["collection"]["received_at"] = "2026-08-06T00:00:03.000000Z"
        direct_mutations.append(changed)
        for changed in direct_mutations:
            with self.assertRaises(EVIDENCE.DirectReadOnlyEvidenceError):
                EVIDENCE.validate_qstat_evidence(changed)

        legacy_splice = copy.deepcopy(source)
        legacy_splice["topology"] = {
            "topology": "legacy_nested_ssh",
            "hop_count": 2,
            "backend_kind": "legacy_rtwin_pbs",
            "transport_kind": "nested_ssh",
            "scheduler_dialect": "pbs_legacy_v1",
        }
        legacy_splice["qstat_evidence_sha256"] = ""
        legacy_splice["qstat_evidence_sha256"] = EVIDENCE.digest(legacy_splice)
        with self.assertRaisesRegex(EVIDENCE.DirectReadOnlyEvidenceError, "topology differs"):
            EVIDENCE.validate_qstat_evidence(legacy_splice)

        receipt = EVIDENCE.build_terminal_receipt(evidence).document()
        binding_splice = copy.deepcopy(receipt)
        binding_splice["binding"]["direct_binding_sha256"] = "e" * 64
        binding_splice["receipt_sha256"] = ""
        binding_splice["receipt_sha256"] = EVIDENCE.digest(binding_splice)
        with self.assertRaisesRegex(EVIDENCE.DirectReadOnlyEvidenceError, "binding differ"):
            EVIDENCE.validate_terminal_receipt(binding_splice, evidence=evidence)

    def test_no_rtwin_hash_legacy_transport_or_effect_surface(self) -> None:
        source_path = SCRIPTS / "direct_read_only_evidence.py"
        source = source_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        for forbidden in (
            "argparse",
            "asyncio",
            "os",
            "pathlib",
            "socket",
            "subprocess",
            "paramiko",
            "legacy_rtwin_pbs",
        ):
            self.assertNotIn(forbidden, imports)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                names = {argument.arg for argument in (*node.args.args, *node.args.kwonlyargs)}
                self.assertTrue(names.isdisjoint({"command", "argv", "callback", "runner", "host", "config"}))
        self.assertNotIn("rtwin_sha256", source)
        documents = [
            self.evidence("running").document(),
            EVIDENCE.build_terminal_receipt(self.evidence("terminal_c")).document(),
        ]
        for document in documents:
            text = json.dumps(document, sort_keys=True)
            self.assertNotIn("rtwin_sha256", text)
            self.assertFalse(document["authority"]["transport_implemented"])
            self.assertFalse(document["authority"]["remote_effect_performed"])

    def test_named_skill_supplement_maps_only_core_schemas_and_reference(self) -> None:
        package = SKILL_PACKAGE.package_files_with_supplements(
            ROOT, "auto-g16-rtwin-pbs"
        )
        expected = {
            Path("scripts/direct_read_only_evidence.py"): SCRIPTS / "direct_read_only_evidence.py",
            Path("contracts/rtwin-pbs/direct-qstat-evidence-core.schema.json"): ROOT / "contracts/direct-execution/direct-qstat-evidence-core.schema.json",
            Path("contracts/rtwin-pbs/direct-scheduler-terminal-evidence-receipt.schema.json"): ROOT / "contracts/direct-execution/direct-scheduler-terminal-evidence-receipt.schema.json",
            Path("references/direct-read-only-evidence-core.md"): ROOT / "docs/v2.7-direct-read-only-evidence-core.md",
        }
        for target, source in expected.items():
            self.assertEqual(package[target], source)
        self.assertFalse((ROOT / "skills/auto-g16-rtwin-pbs/scripts/direct_read_only_evidence.py").exists())


if __name__ == "__main__":
    unittest.main()
