from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest import mock
from uuid import UUID

import auto_g16.approval as approval
import auto_g16.core as core
import auto_g16.execution as execution

from ._fixtures import (
    DISPLAYED_MEANING,
    plan,
    populate_runtime_store,
    scientific,
    scientific_two,
    snapshot,
)


class ApprovalModelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.store = core.SQLiteRuntimeStore(self.root / "runtime.sqlite3")
        self.addCleanup(self.store.close)
        populate_runtime_store(self.store)

    def test_scientific_identity_replay_and_nonauthority_metadata_invariance(self) -> None:
        first = scientific(self.store)
        second = approval.ScientificApproval.for_plan(
            self.store,
            plan(intent={"multiplicity": 1, "charge": 0, "route": "#p b3lyp/6-31g(d) opt"}),
            displayed_semantic_meaning={
                "job": "minimum optimization",
                "method": "B3LYP/6-31G(d)",
            },
            reviewer_id="reviewer-1",
            reviewer_evidence={"statement": "reviewed semantic plan"},
        )
        self.assertEqual(first.scientific_approval_id, second.scientific_approval_id)
        self.assertEqual(UUID(first.scientific_approval_id).version, 5)
        self.assertFalse(hasattr(first, "timestamp"))
        self.assertFalse(hasattr(first, "temporary_path"))

    def test_each_scientific_authority_change_changes_identity_or_is_stale(self) -> None:
        baseline = scientific(self.store)
        variants = [
            scientific(self.store, displayed_semantic_meaning={"job": "frequency"}),
            scientific(self.store, reviewer_id="reviewer-2"),
            scientific(self.store, decision=approval.ApprovalDecision.REJECTED),
        ]
        self.assertEqual(len({item.scientific_approval_id for item in variants}), len(variants))
        self.assertNotIn(baseline.scientific_approval_id, {item.scientific_approval_id for item in variants})
        for changed_plan in (
            plan(calculation_plan_id="plan-2"),
            plan(task_id="task-2"),
            plan(revision=4),
            plan(intent={"route": "#p hf/sto-3g"}),
        ):
            with self.assertRaises(approval.StaleApprovalError):
                baseline.assert_current(
                    changed_plan, displayed_semantic_meaning=DISPLAYED_MEANING
                )
        with self.assertRaises(approval.StaleApprovalError):
            baseline.assert_current(
                plan(), displayed_semantic_meaning={"job": "frequency"}
            )
        with self.assertRaises(approval.ApprovalRejectedError):
            scientific(self.store, decision=approval.ApprovalDecision.REJECTED).assert_current(
                plan(), displayed_semantic_meaning=DISPLAYED_MEANING
            )

    def test_batch_is_exact_order_invariant_and_deduplicated(self) -> None:
        science = scientific(self.store)
        first = approval.BatchSubmitApproval.for_existing_attempts(
            self.store,
            [("attempt-2", scientific_two(self.store)), ("attempt-1", science)],
            reviewer_id="batch-reviewer",
            reviewer_evidence={"scope": "two exact attempts"},
        )
        second = approval.BatchSubmitApproval.for_existing_attempts(
            self.store,
            [("attempt-1", science), ("attempt-2", scientific_two(self.store))],
            reviewer_id="batch-reviewer",
            reviewer_evidence={"scope": "two exact attempts"},
        )
        self.assertEqual(first.batch_submit_approval_id, second.batch_submit_approval_id)
        self.assertEqual([member.attempt_id for member in first.members], ["attempt-1", "attempt-2"])
        with self.assertRaises(approval.ApprovalValueError):
            approval.BatchSubmitApproval.for_existing_attempts(
                self.store,
                [("attempt-1", science), ("attempt-1", science)],
                reviewer_id="batch-reviewer",
                reviewer_evidence={},
            )

    def test_batch_rejects_unlisted_future_replacement_and_recovery_child(self) -> None:
        science = scientific(self.store)
        batch = approval.BatchSubmitApproval.for_existing_attempts(
            self.store,
            [("attempt-1", science)],
            reviewer_id="batch-reviewer",
            reviewer_evidence={},
        )
        self.assertEqual(batch.member_for("attempt-1").attempt_id, "attempt-1")
        for attempt_id in ("attempt-2", "attempt-future", "attempt-replacement", "attempt-child"):
            with self.assertRaises(approval.ApprovalScopeError):
                batch.member_for(attempt_id)

    def test_recovery_child_reuses_science_but_requires_new_batch_membership(self) -> None:
        science = scientific(self.store)
        parent_batch = approval.BatchSubmitApproval.for_existing_attempts(
            self.store,
            [("attempt-1", science)],
            reviewer_id="batch-reviewer",
            reviewer_evidence={},
        )
        self.store.record_submission_intent("attempt-1", "intent-failed")
        self.store.record_submission_outcome(
            "attempt-1", "intent-failed", core.SubmissionOutcome.SUBMITTED
        )
        self.store.advance_attempt("attempt-1", core.AttemptState.FAILED)
        child = core.Attempt(attempt_id="attempt-child", task_id="task-1", ordinal=2)
        self.store.create_child_attempt("attempt-1", child)
        with self.assertRaises(approval.ApprovalScopeError):
            parent_batch.member_for(child.attempt_id)
        child_batch = approval.BatchSubmitApproval.for_existing_attempts(
            self.store,
            [(child.attempt_id, science)],
            reviewer_id="batch-reviewer",
            reviewer_evidence={"scope": "exact recovery child"},
        )
        self.assertEqual(child_batch.member_for(child.attempt_id).scientific_approval_id,
                         science.scientific_approval_id)

    def test_unknown_attempt_cannot_acquire_batch_or_retry_authority(self) -> None:
        science = scientific(self.store)
        batch = approval.BatchSubmitApproval.for_existing_attempts(
            self.store,
            [("attempt-1", science)],
            reviewer_id="batch-reviewer",
            reviewer_evidence={},
        )
        current_snapshot = snapshot(self.store, self.root / "local")
        confirmation = approval.ExactOperationalConfirmation.for_snapshot(
            current_snapshot,
            confirmer_id="operator-1",
            confirmer_evidence={},
        )
        self.store.record_submission_intent("attempt-1", "intent-unknown")
        self.store.record_submission_outcome(
            "attempt-1", "intent-unknown", core.SubmissionOutcome.UNKNOWN
        )
        with self.assertRaises(approval.ApprovalScopeError):
            approval.BatchSubmitApproval.for_existing_attempts(
                self.store,
                [("attempt-1", science)],
                reviewer_id="batch-reviewer",
                reviewer_evidence={},
            )
        with self.assertRaises(approval.ApprovalScopeError):
            approval.validate_effect_authority(
                runtime_store=self.store,
                attempt=self.store.load_attempt("attempt-1"),
                plan=self.store.load_calculation_plan("plan-1"),
                displayed_semantic_meaning=DISPLAYED_MEANING,
                scientific_approval=science,
                batch_submit_approval=batch,
                execution_snapshot=current_snapshot,
                operational_confirmation=confirmation,
            )

    def test_operational_confirmation_replay_and_nested_snapshot_drift(self) -> None:
        original = snapshot(self.store, self.root / "local")
        changed = snapshot(self.store, self.root / "local", cores=9)
        first = approval.ExactOperationalConfirmation.for_snapshot(
            original,
            confirmer_id="operator-1",
            confirmer_evidence={"displayed": "exact snapshot"},
        )
        replay = approval.ExactOperationalConfirmation.for_snapshot(
            original,
            confirmer_id="operator-1",
            confirmer_evidence={"displayed": "exact snapshot"},
        )
        self.assertEqual(first.operational_confirmation_id, replay.operational_confirmation_id)
        first.assert_current(original)
        with self.assertRaises(approval.StaleApprovalError):
            first.assert_current(changed)

    def test_three_domains_are_separated(self) -> None:
        science = scientific(self.store)
        batch = approval.BatchSubmitApproval.for_existing_attempts(
            self.store,
            [("attempt-1", science)],
            reviewer_id="reviewer-1",
            reviewer_evidence={"statement": "reviewed semantic plan"},
        )
        confirmation = approval.ExactOperationalConfirmation.for_snapshot(
            snapshot(self.store, self.root / "local"),
            confirmer_id="reviewer-1",
            confirmer_evidence={"statement": "reviewed semantic plan"},
        )
        identities = {
            science.scientific_approval_id,
            batch.batch_submit_approval_id,
            confirmation.operational_confirmation_id,
        }
        self.assertEqual(len(identities), 3)
        self.assertTrue(all(UUID(value).version == 5 for value in identities))

    def test_human_identity_evidence_and_decision_are_authority(self) -> None:
        science = scientific(self.store)
        scientific_variants = (
            scientific(self.store, reviewer_id="reviewer-2"),
            scientific(self.store, reviewer_evidence={"statement": "different"}),
            scientific(self.store, decision=approval.ApprovalDecision.REJECTED),
        )
        self.assertTrue(
            all(
                item.scientific_approval_id != science.scientific_approval_id
                for item in scientific_variants
            )
        )
        batch = approval.BatchSubmitApproval.for_existing_attempts(
            self.store,
            [("attempt-1", science)],
            reviewer_id="batch-reviewer",
            reviewer_evidence={"scope": "exact"},
        )
        batch_variants = (
            approval.BatchSubmitApproval.for_existing_attempts(
                self.store,
                [("attempt-1", science)],
                reviewer_id="batch-reviewer-2",
                reviewer_evidence={"scope": "exact"},
            ),
            approval.BatchSubmitApproval.for_existing_attempts(
                self.store,
                [("attempt-1", science)],
                reviewer_id="batch-reviewer",
                reviewer_evidence={"scope": "different"},
            ),
            approval.BatchSubmitApproval.for_existing_attempts(
                self.store,
                [("attempt-1", science)],
                reviewer_id="batch-reviewer",
                reviewer_evidence={"scope": "exact"},
                decision=approval.ApprovalDecision.REJECTED,
            ),
        )
        self.assertTrue(
            all(
                item.batch_submit_approval_id != batch.batch_submit_approval_id
                for item in batch_variants
            )
        )
        with self.assertRaises(approval.ApprovalRejectedError):
            batch_variants[-1].member_for("attempt-1")
        current_snapshot = snapshot(self.store, self.root / "local")
        confirmation = approval.ExactOperationalConfirmation.for_snapshot(
            current_snapshot,
            confirmer_id="operator-1",
            confirmer_evidence={"displayed": "exact"},
        )
        confirmation_variants = (
            approval.ExactOperationalConfirmation.for_snapshot(
                current_snapshot,
                confirmer_id="operator-2",
                confirmer_evidence={"displayed": "exact"},
            ),
            approval.ExactOperationalConfirmation.for_snapshot(
                current_snapshot,
                confirmer_id="operator-1",
                confirmer_evidence={"displayed": "different"},
            ),
            approval.ExactOperationalConfirmation.for_snapshot(
                current_snapshot,
                confirmer_id="operator-1",
                confirmer_evidence={"displayed": "exact"},
                decision=approval.ApprovalDecision.REJECTED,
            ),
        )
        self.assertTrue(
            all(
                item.operational_confirmation_id
                != confirmation.operational_confirmation_id
                for item in confirmation_variants
            )
        )
        with self.assertRaises(approval.ApprovalRejectedError):
            confirmation_variants[-1].assert_current(current_snapshot)

    def test_pure_chain_validation_is_unspliced_and_zero_effect(self) -> None:
        current_plan = self.store.load_calculation_plan("plan-1")
        attempt = self.store.load_attempt("attempt-1")
        science = scientific(self.store, current_plan)
        batch = approval.BatchSubmitApproval.for_existing_attempts(
            self.store,
            [(attempt.attempt_id, science)],
            reviewer_id="batch-reviewer",
            reviewer_evidence={},
        )
        current_snapshot = snapshot(self.store, self.root / "local")
        confirmation = approval.ExactOperationalConfirmation.for_snapshot(
            current_snapshot,
            confirmer_id="operator-1",
            confirmer_evidence={},
        )
        with mock.patch.object(
            core.SQLiteRuntimeStore,
            "record_submission_intent",
            side_effect=AssertionError("Core claim must not be called"),
        ), mock.patch.object(
            execution,
            "execute_once",
            side_effect=AssertionError("execution must not be called"),
        ):
            self.assertIsNone(
                approval.validate_effect_authority(
                    runtime_store=self.store,
                    attempt=attempt,
                    plan=current_plan,
                    displayed_semantic_meaning=DISPLAYED_MEANING,
                    scientific_approval=science,
                    batch_submit_approval=batch,
                    execution_snapshot=current_snapshot,
                    operational_confirmation=confirmation,
                )
            )
        self.assertIs(self.store.attempt_state("attempt-1"), core.AttemptState.PLANNED)

    def test_cross_domain_splicing_is_rejected_explicitly(self) -> None:
        current_plan = self.store.load_calculation_plan("plan-1")
        attempt = self.store.load_attempt("attempt-1")
        science = scientific(self.store, current_plan)
        batch = approval.BatchSubmitApproval.for_existing_attempts(
            self.store,
            [(attempt.attempt_id, science)],
            reviewer_id="batch-reviewer",
            reviewer_evidence={},
        )
        current_snapshot = snapshot(self.store, self.root / "local")
        confirmation = approval.ExactOperationalConfirmation.for_snapshot(
            current_snapshot,
            confirmer_id="operator-1",
            confirmer_evidence={},
        )
        with self.assertRaises(approval.ApprovalValueError):
            approval.validate_effect_authority(
                runtime_store=self.store,
                attempt=attempt,
                plan=current_plan,
                displayed_semantic_meaning=DISPLAYED_MEANING,
                scientific_approval=batch,  # type: ignore[arg-type]
                batch_submit_approval=science,  # type: ignore[arg-type]
                execution_snapshot=current_snapshot,
                operational_confirmation=confirmation,
            )

    def test_chain_rejects_cross_attempt_plan_snapshot_and_stale_member(self) -> None:
        current_plan = self.store.load_calculation_plan("plan-1")
        attempt = self.store.load_attempt("attempt-1")
        science = scientific(self.store, current_plan)
        batch = approval.BatchSubmitApproval.for_existing_attempts(
            self.store,
            [(attempt.attempt_id, science)],
            reviewer_id="batch-reviewer",
            reviewer_evidence={},
        )
        first_snapshot = snapshot(self.store, self.root / "local", attempt_id="attempt-1")
        confirmation = approval.ExactOperationalConfirmation.for_snapshot(
            first_snapshot,
            confirmer_id="operator-1",
            confirmer_evidence={},
        )
        cases = [
            dict(attempt=self.store.load_attempt("attempt-2"), execution_snapshot=first_snapshot),
            dict(attempt=attempt, plan=plan(revision=4), execution_snapshot=first_snapshot),
        ]
        for changes in cases:
            values = {
                "attempt": attempt,
                "plan": current_plan,
                "runtime_store": self.store,
                "displayed_semantic_meaning": DISPLAYED_MEANING,
                "scientific_approval": science,
                "batch_submit_approval": batch,
                "execution_snapshot": first_snapshot,
                "operational_confirmation": confirmation,
            }
            values.update(changes)
            with self.assertRaises(approval.ApprovalError):
                approval.validate_effect_authority(**values)  # type: ignore[arg-type]

    def test_no_effectful_composition_api_is_public(self) -> None:
        forbidden = {
            "approve_and_execute",
            "submit_if_approved",
            "execute_once",
            "record_submission_intent",
            "SyntheticRTWinAdapter",
        }
        self.assertTrue(forbidden.isdisjoint(approval.__all__))
        self.assertTrue(all(not hasattr(approval, name) for name in forbidden))

    def test_public_evidence_constructors_cannot_preapprove_future_objects(self) -> None:
        for record_type in (
            approval.ScientificApproval,
            approval.BatchSubmitApproval,
            approval.ExactOperationalConfirmation,
        ):
            with self.assertRaises(TypeError):
                record_type()  # type: ignore[call-arg]
        with self.assertRaises(core.RecordNotFoundError):
            approval.ScientificApproval.for_plan(
                self.store,
                plan(calculation_plan_id="future-plan"),
                displayed_semantic_meaning=DISPLAYED_MEANING,
                reviewer_id="reviewer-1",
                reviewer_evidence={},
            )


if __name__ == "__main__":
    unittest.main()
