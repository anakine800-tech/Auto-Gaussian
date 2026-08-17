from __future__ import annotations

from pathlib import Path
import sqlite3
import tempfile
import unittest

import auto_g16.approval as approval
import auto_g16.core as core

from ._fixtures import (
    DISPLAYED_MEANING,
    plan,
    populate_runtime_store,
    scientific,
    scientific_two,
    snapshot,
)


class ApprovalStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.runtime = core.SQLiteRuntimeStore(self.root / "runtime.sqlite3")
        self.addCleanup(self.runtime.close)
        populate_runtime_store(self.runtime)
        self.science = scientific(self.runtime)
        self.batch = approval.BatchSubmitApproval.for_existing_attempts(
            self.runtime,
            [("attempt-1", self.science), ("attempt-2", scientific_two(self.runtime))],
            reviewer_id="batch-reviewer",
            reviewer_evidence={"scope": "two exact attempts"},
        )
        self.confirmation = approval.ExactOperationalConfirmation.for_snapshot(
            self.runtime,
            snapshot(self.runtime, self.root / "local"),
            confirmer_id="operator-1",
            confirmer_evidence={"displayed": "exact snapshot"},
        )

    def test_all_domains_are_idempotent_and_durable_across_reopen(self) -> None:
        database = self.root / "approval.sqlite3"
        first = approval.SQLiteApprovalStore(database)
        for _ in range(2):
            first.store_scientific_approval(self.science)
            first.store_batch_submit_approval(self.batch)
            first.store_operational_confirmation(self.confirmation)
        self.assertEqual(first.evidence_count(), 3)
        first.close()
        reopened = approval.SQLiteApprovalStore(database)
        self.addCleanup(reopened.close)
        self.assertEqual(
            reopened.load_scientific_approval(self.science.scientific_approval_id),
            self.science,
        )
        self.assertEqual(
            reopened.load_batch_submit_approval(self.batch.batch_submit_approval_id),
            self.batch,
        )
        self.assertEqual(
            reopened.load_operational_confirmation(
                self.confirmation.operational_confirmation_id
            ),
            self.confirmation,
        )

    def test_same_identity_different_payload_conflicts_for_every_domain(self) -> None:
        store = approval.SQLiteApprovalStore(self.root / "approval.sqlite3")
        self.addCleanup(store.close)
        records = [
            (
                self.science,
                store.store_scientific_approval,
                "reviewer_id",
                "other-reviewer",
            ),
            (
                self.batch,
                store.store_batch_submit_approval,
                "reviewer_id",
                "other-reviewer",
            ),
            (
                self.confirmation,
                store.store_operational_confirmation,
                "confirmer_id",
                "other-confirmer",
            ),
        ]
        for record, persist, field_name, changed in records:
            persist(record)
            object.__setattr__(record, field_name, changed)
            with self.assertRaises(approval.ApprovalStoreConflictError):
                persist(record)

    def test_approval_store_is_independent_from_core_schema(self) -> None:
        approval_database = self.root / "approval.sqlite3"
        store = approval.SQLiteApprovalStore(approval_database)
        store.store_scientific_approval(self.science)
        store.close()
        with sqlite3.connect(approval_database) as connection:
            objects = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            self.assertIn("approval_evidence", objects)
            self.assertNotIn("attempts", objects)
        with sqlite3.connect(self.root / "runtime.sqlite3") as connection:
            objects = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            self.assertNotIn("approval_evidence", objects)

    def test_unknown_or_counterfeit_schema_fails_closed(self) -> None:
        wrong_version = self.root / "wrong.sqlite3"
        with sqlite3.connect(wrong_version) as connection:
            connection.execute("PRAGMA user_version = 2")
        with self.assertRaises(approval.ApprovalStoreSchemaError):
            approval.SQLiteApprovalStore(wrong_version)
        counterfeit = self.root / "counterfeit.sqlite3"
        with sqlite3.connect(counterfeit) as connection:
            connection.execute(
                "CREATE TABLE approval_evidence (evidence_id TEXT PRIMARY KEY, payload TEXT)"
            )
            connection.execute("PRAGMA user_version = 1")
        with self.assertRaises(approval.ApprovalStoreSchemaError):
            approval.SQLiteApprovalStore(counterfeit)

    def test_rejected_decisions_persist_but_never_validate(self) -> None:
        rejected = scientific(self.runtime, decision=approval.ApprovalDecision.REJECTED)
        store = approval.SQLiteApprovalStore(self.root / "approval.sqlite3")
        self.addCleanup(store.close)
        store.store_scientific_approval(rejected)
        loaded = store.load_scientific_approval(rejected.scientific_approval_id)
        with self.assertRaises(approval.ApprovalRejectedError):
            loaded.assert_current(
                plan(), displayed_semantic_meaning=DISPLAYED_MEANING
            )


if __name__ == "__main__":
    unittest.main()
