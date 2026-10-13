#!/usr/bin/env python3
"""Offline tests for persistent Gaussian execution-batch governance."""

from __future__ import annotations

import copy
import importlib.util
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


ROOT = Path(__file__).parents[1]
MODULE = ROOT / "skills" / "auto-g16-rtwin-pbs" / "scripts" / "execution_batch.py"
SPEC = importlib.util.spec_from_file_location("execution_batch", MODULE)
assert SPEC and SPEC.loader
BATCH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BATCH)

SCHEMA_MODULE = ROOT / "scripts" / "validate_asymmetric_contract.py"
SCHEMA_SPEC = importlib.util.spec_from_file_location("execution_batch_schema", SCHEMA_MODULE)
assert SCHEMA_SPEC and SCHEMA_SPEC.loader
SCHEMA = importlib.util.module_from_spec(SCHEMA_SPEC)
SCHEMA_SPEC.loader.exec_module(SCHEMA)


def identity(index: int) -> dict[str, str]:
    values = [f"{index * 10 + offset:064x}"[-64:] for offset in range(1, 6)]
    return dict(zip(BATCH.SHA256_FIELDS, values, strict=True))


class ExecutionBatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        template = json.loads(
            (ROOT / "tests" / "fixtures" / "rtwin_pbs" / "execution_batch_review.template.json").read_text(encoding="utf-8")
        )
        self.review = BATCH.finalize_review(template)
        self.review_path = self.root / "review.json"
        self.review_path.write_text(json.dumps(self.review), encoding="utf-8")
        self.ledger_path = self.root / "ledger.json"
        BATCH.initialize(self.review_path, self.ledger_path, timestamp="2026-01-01T00:00:00Z")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def admit(self, index: int, *, timestamp: str = "2026-01-01T00:01:00Z") -> dict[str, object]:
        return BATCH.admit_task(
            self.ledger_path,
            identity(index),
            estimated_core_hours=index + 0.5,
            reason=f"synthetic reviewed task {index}",
            reviewer="fixture-reviewer",
            reviewed_at=timestamp,
        )

    def test_cap_is_distinct_scientific_identity_not_names_splits_or_retries(self) -> None:
        first = self.admit(0)
        again = self.admit(0, timestamp="2026-01-01T00:02:00Z")
        self.assertEqual(first["scientific_task_id"], again["scientific_task_id"])
        self.assertFalse(again["new_slot_consumed"])
        for index in range(1, 10):
            self.admit(index)
        deferred = self.admit(10)
        self.assertEqual(deferred["decision"], "deferred")
        self.assertIn("10 distinct", deferred["reason"])
        ledger = BATCH.validate_ledger(BATCH.load_json(self.ledger_path))
        self.assertEqual(ledger["counters"]["distinct_scientific_tasks"], 10)
        self.assertEqual(len({task["scientific_task_id"] for task in ledger["tasks"]}), 10)
        self.assertNotIn("filename", json.dumps(ledger))
        self.assertNotIn("job_name", json.dumps(ledger))

    def test_concurrent_admission_is_locked_and_never_exceeds_cap(self) -> None:
        def worker(index: int) -> str:
            return self.admit(index)["decision"]  # type: ignore[return-value]

        with ThreadPoolExecutor(max_workers=20) as pool:
            decisions = list(pool.map(worker, range(20)))
        ledger = BATCH.validate_ledger(BATCH.load_json(self.ledger_path))
        self.assertEqual(decisions.count("admitted"), 10)
        self.assertEqual(decisions.count("deferred"), 10)
        self.assertEqual(ledger["counters"]["distinct_scientific_tasks"], 10)
        self.assertGreaterEqual(ledger["revision"], 20)

    def test_operator_decisions_include_admitted_deferred_and_rejected_reasons(self) -> None:
        admitted = self.admit(0)
        rejected = BATCH.admit_task(
            self.ledger_path,
            identity(1),
            estimated_core_hours=1,
            reason="synthetic mismatch",
            reviewer="fixture-reviewer",
            reviewed_at="2026-01-01T00:02:00Z",
            requested_task_id="scientific-task-" + "f" * 32,
        )
        for index in range(1, 10):
            self.admit(index)
        deferred = self.admit(11)
        self.assertEqual([admitted["decision"], deferred["decision"], rejected["decision"]], ["admitted", "deferred", "rejected"])
        for decision in (admitted, deferred, rejected):
            self.assertTrue(decision["reason"])

    def test_retry_classification_is_exact_across_all_scientific_identity_fields(self) -> None:
        original = identity(0)
        exact = BATCH.classify_retry(original, copy.deepcopy(original))
        self.assertEqual(exact["classification"], "exact_resubmission")
        self.assertFalse(exact["consumes_new_task_slot"])
        self.assertFalse(exact["automatic_qsub_authorized"])
        for field in BATCH.SHA256_FIELDS:
            changed = copy.deepcopy(original)
            changed[field] = "f" * 64
            classified = BATCH.classify_retry(original, changed)
            self.assertEqual(classified["classification"], "new_scientific_task")
            self.assertEqual(classified["changed_fields"], [field])
            self.assertTrue(classified["consumes_new_task_slot"])

    def test_attempt_idempotency_fresh_approval_and_separate_counters(self) -> None:
        decision = self.admit(0)
        task_id = str(decision["scientific_task_id"])
        attempt = BATCH.reserve_attempt(
            self.ledger_path,
            task_id,
            identity=identity(0),
            idempotency_key="attempt-request-1",
            input_sha256=identity(0)["relevant_input_sha256"],
            live_approval_sha256="a" * 64,
            estimated_core_hours=4,
            reserved_at="2026-01-01T00:03:00Z",
            audit_reason="fresh exact approval replayed offline",
        )
        repeated = BATCH.reserve_attempt(
            self.ledger_path,
            task_id,
            identity=identity(0),
            idempotency_key="attempt-request-1",
            input_sha256=identity(0)["relevant_input_sha256"],
            live_approval_sha256="a" * 64,
            estimated_core_hours=4,
            reserved_at="2026-01-01T00:04:00Z",
            audit_reason="same idempotent request",
        )
        self.assertEqual(attempt["attempt_id"], repeated["attempt_id"])
        ledger = BATCH.validate_ledger(BATCH.load_json(self.ledger_path))
        self.assertEqual(ledger["counters"], {
            "distinct_scientific_tasks": 1,
            "physical_qsub_attempts": 1,
            "estimated_core_hours": 4.0,
            "consumed_core_hours": 0,
        })
        with self.assertRaisesRegex(BATCH.BatchError, "unresolved physical attempt"):
            BATCH.reserve_attempt(
                self.ledger_path, task_id, identity=identity(0), idempotency_key="attempt-request-2",
                input_sha256=identity(0)["relevant_input_sha256"], live_approval_sha256="b" * 64,
                estimated_core_hours=4, reserved_at="2026-01-01T00:05:00Z", audit_reason="blocked duplicate",
            )
        BATCH.reconcile_attempt(
            self.ledger_path, attempt["attempt_id"], state="failed", observed_at="2026-01-01T00:06:00Z",
            reason="synthetic terminal failure", consumed_core_hours=1.25,
        )
        retry = BATCH.reserve_attempt(
            self.ledger_path, task_id, identity=identity(0), idempotency_key="attempt-request-2",
            input_sha256=identity(0)["relevant_input_sha256"], live_approval_sha256="b" * 64,
            estimated_core_hours=5, reserved_at="2026-01-01T00:07:00Z", audit_reason="new approval for exact resubmission",
        )
        self.assertNotEqual(retry["attempt_id"], attempt["attempt_id"])
        ledger = BATCH.validate_ledger(BATCH.load_json(self.ledger_path))
        self.assertEqual(ledger["counters"]["distinct_scientific_tasks"], 1)
        self.assertEqual(ledger["counters"]["physical_qsub_attempts"], 2)
        self.assertEqual(ledger["counters"]["estimated_core_hours"], 9.0)
        self.assertEqual(ledger["counters"]["consumed_core_hours"], 1.25)
        with self.assertRaisesRegex(BATCH.BatchError, "fresh live approval"):
            BATCH.reconcile_attempt(self.ledger_path, retry["attempt_id"], state="failed", observed_at="2026-01-01T00:08:00Z", reason="synthetic")
            BATCH.reserve_attempt(
                self.ledger_path, task_id, identity=identity(0), idempotency_key="attempt-request-3",
                input_sha256=identity(0)["relevant_input_sha256"], live_approval_sha256="a" * 64,
                estimated_core_hours=5, reserved_at="2026-01-01T00:09:00Z", audit_reason="reused approval refused",
            )

    def test_changed_retry_identity_cannot_use_existing_task(self) -> None:
        decision = self.admit(0)
        changed = identity(0)
        changed["chemical_hypothesis_sha256"] = "f" * 64
        with self.assertRaisesRegex(BATCH.BatchError, "chemical_hypothesis_sha256"):
            BATCH.reserve_attempt(
                self.ledger_path, str(decision["scientific_task_id"]), identity=changed,
                idempotency_key="changed-retry", input_sha256=identity(0)["relevant_input_sha256"],
                live_approval_sha256="a" * 64, estimated_core_hours=1,
                reserved_at="2026-01-01T00:03:00Z", audit_reason="must fail closed",
            )

    def test_submission_uncertain_reserves_until_explicit_reconciliation(self) -> None:
        decision = self.admit(0)
        task_id = str(decision["scientific_task_id"])
        attempt = BATCH.reserve_attempt(
            self.ledger_path, task_id, identity=identity(0), idempotency_key="uncertain-1",
            input_sha256=identity(0)["relevant_input_sha256"], live_approval_sha256="a" * 64,
            estimated_core_hours=2, reserved_at="2026-01-01T00:03:00Z", audit_reason="pre-submit reservation",
        )
        with self.assertRaisesRegex(BATCH.BatchError, "unresolved physical attempt"):
            BATCH.reserve_attempt(
                self.ledger_path, task_id, identity=identity(0), idempotency_key="uncertain-2",
                input_sha256=identity(0)["relevant_input_sha256"], live_approval_sha256="b" * 64,
                estimated_core_hours=2, reserved_at="2026-01-01T00:04:00Z", audit_reason="duplicate blocked",
            )
        BATCH.reconcile_attempt(
            self.ledger_path, attempt["attempt_id"], state="reconciled_not_submitted",
            observed_at="2026-01-01T00:05:00Z", reason="read-only evidence proved no scheduler submission",
        )
        ledger = BATCH.validate_ledger(BATCH.load_json(self.ledger_path))
        self.assertEqual(ledger["counters"]["physical_qsub_attempts"], 0)
        next_attempt = BATCH.reserve_attempt(
            self.ledger_path, task_id, identity=identity(0), idempotency_key="uncertain-2",
            input_sha256=identity(0)["relevant_input_sha256"], live_approval_sha256="b" * 64,
            estimated_core_hours=2, reserved_at="2026-01-01T00:06:00Z", audit_reason="fresh approved attempt",
        )
        self.assertEqual(next_attempt["state"], "submission_uncertain")

    def test_concurrent_attempt_reservations_allow_only_one_unresolved_attempt(self) -> None:
        task_id = str(self.admit(0)["scientific_task_id"])

        def worker(index: int) -> str:
            try:
                BATCH.reserve_attempt(
                    self.ledger_path, task_id, identity=identity(0), idempotency_key=f"race-{index}",
                    input_sha256=identity(0)["relevant_input_sha256"], live_approval_sha256=f"{index + 1:064x}",
                    estimated_core_hours=1, reserved_at="2026-01-01T00:03:00Z", audit_reason="concurrent synthetic reservation",
                )
                return "reserved"
            except BATCH.BatchError:
                return "blocked"

        with ThreadPoolExecutor(max_workers=12) as pool:
            outcomes = list(pool.map(worker, range(12)))
        self.assertEqual(outcomes.count("reserved"), 1)
        ledger = BATCH.validate_ledger(BATCH.load_json(self.ledger_path))
        self.assertEqual(ledger["counters"]["physical_qsub_attempts"], 1)
        self.assertEqual(len(ledger["attempts"]), 1)

    def test_monitoring_emits_immediate_events_and_60_minute_read_only_summary(self) -> None:
        self.admit(0, timestamp="2026-01-01T00:01:00Z")
        BATCH.record_error(
            self.ledger_path, code="synthetic_failure", message="sanitized offline error",
            observed_at="2026-01-01T00:10:00Z",
        )
        before = self.ledger_path.read_bytes()
        early = BATCH.monitoring_summary(self.ledger_path, now="2026-01-01T00:59:59Z")
        self.assertFalse(early["cumulative_summary_due"])
        self.assertIsNone(early["cumulative_summary"])
        self.assertTrue(any(event["event_type"] == "important_error" for event in early["immediate_events"]))
        due = BATCH.monitoring_summary(self.ledger_path, now="2026-01-01T01:00:00Z")
        self.assertTrue(due["cumulative_summary_due"])
        self.assertEqual(due["cadence_minutes"], 60)
        self.assertEqual(due["cumulative_summary"]["counters"]["distinct_scientific_tasks"], 1)
        self.assertTrue(due["read_only"])
        self.assertTrue(all(value is False for value in due["live_actions"].values()))
        self.assertEqual(before, self.ledger_path.read_bytes())

    def test_tampering_and_immutable_review_drift_fail_closed(self) -> None:
        ledger = BATCH.load_json(self.ledger_path)
        ledger["batch"]["batch_id"] = "renamed-to-evade-governance"
        self.ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
        with self.assertRaisesRegex(BATCH.BatchError, "ledger_sha256 mismatch"):
            BATCH.validate_ledger(BATCH.load_json(self.ledger_path))

    def test_symlink_ledger_and_idempotent_identity_drift_fail_closed(self) -> None:
        decision = self.admit(0)
        task_id = str(decision["scientific_task_id"])
        BATCH.reserve_attempt(
            self.ledger_path, task_id, identity=identity(0), idempotency_key="identity-bound",
            input_sha256=identity(0)["relevant_input_sha256"], live_approval_sha256="a" * 64,
            estimated_core_hours=1, reserved_at="2026-01-01T00:03:00Z", audit_reason="identity-bound request",
        )
        changed = identity(0)
        changed["method_protocol_sha256"] = "f" * 64
        with self.assertRaisesRegex(BATCH.BatchError, "method_protocol_sha256"):
            BATCH.reserve_attempt(
                self.ledger_path, task_id, identity=changed, idempotency_key="identity-bound",
                input_sha256=identity(0)["relevant_input_sha256"], live_approval_sha256="a" * 64,
                estimated_core_hours=1, reserved_at="2026-01-01T00:04:00Z", audit_reason="drifted replay",
            )
        link = self.root / "ledger-link.json"
        link.symlink_to(self.ledger_path)
        with self.assertRaisesRegex(BATCH.BatchError, "symlink"):
            BATCH.load_json(link)

    def test_contracts_are_closed_and_module_has_no_live_transport(self) -> None:
        for name in ("execution-batch-review.schema.json", "execution-batch.schema.json"):
            schema = json.loads((ROOT / "contracts" / "rtwin-pbs" / name).read_text(encoding="utf-8"))
            SCHEMA.validate_schema_document(schema)
            self.assertFalse(schema["additionalProperties"])
        source = MODULE.read_text(encoding="utf-8").lower()
        for forbidden in ("import subprocess", "import socket", "paramiko", "requests", "ssh "):
            self.assertNotIn(forbidden, source)
        self.assertNotIn("cancel", BATCH.build_parser().format_help())
        self.assertNotIn("submit", BATCH.build_parser().format_help())


if __name__ == "__main__":
    unittest.main()
