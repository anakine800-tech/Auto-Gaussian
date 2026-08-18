from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock
from uuid import UUID, uuid5

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

    def _fresh_scientific(self) -> approval.ScientificApproval:
        return scientific(self.runtime)

    def _fresh_batch(self) -> approval.BatchSubmitApproval:
        return approval.BatchSubmitApproval.for_existing_attempts(
            self.runtime,
            [
                ("attempt-1", scientific(self.runtime)),
                ("attempt-2", scientific_two(self.runtime)),
            ],
            reviewer_id="batch-reviewer",
            reviewer_evidence={"scope": "two exact attempts"},
        )

    def _fresh_confirmation(self) -> approval.ExactOperationalConfirmation:
        return approval.ExactOperationalConfirmation.for_snapshot(
            self.runtime,
            snapshot(self.runtime, self.root / "local"),
            confirmer_id="operator-1",
            confirmer_evidence={"displayed": "exact snapshot"},
        )

    def _fresh_family(
        self, domain: str
    ) -> tuple[object, str, str, str]:
        if domain == "scientific-approval":
            record = self._fresh_scientific()
            return (
                record,
                "store_scientific_approval",
                "load_scientific_approval",
                "scientific_approval_id",
            )
        if domain == "batch-submit-approval":
            record = self._fresh_batch()
            return (
                record,
                "store_batch_submit_approval",
                "load_batch_submit_approval",
                "batch_submit_approval_id",
            )
        record = self._fresh_confirmation()
        return (
            record,
            "store_operational_confirmation",
            "load_operational_confirmation",
            "operational_confirmation_id",
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

    def test_first_append_rejects_stale_or_malformed_authority_without_sql(self) -> None:
        cases = (
            (
                "scientific-plan",
                self._fresh_scientific,
                "store_scientific_approval",
                lambda value: object.__setattr__(
                    value, "calculation_plan_id", "forged-plan"
                ),
            ),
            (
                "scientific-task",
                self._fresh_scientific,
                "store_scientific_approval",
                lambda value: object.__setattr__(value, "task_id", "forged-task"),
            ),
            (
                "scientific-revision-bool",
                self._fresh_scientific,
                "store_scientific_approval",
                lambda value: object.__setattr__(
                    value, "calculation_plan_revision", True
                ),
            ),
            (
                "scientific-intent",
                self._fresh_scientific,
                "store_scientific_approval",
                lambda value: object.__setattr__(
                    value, "canonical_intent", {"route": "forged"}
                ),
            ),
            (
                "scientific-displayed-meaning",
                self._fresh_scientific,
                "store_scientific_approval",
                lambda value: object.__setattr__(
                    value, "displayed_semantic_meaning", {"job": "forged"}
                ),
            ),
            (
                "scientific-reviewer",
                self._fresh_scientific,
                "store_scientific_approval",
                lambda value: object.__setattr__(
                    value, "reviewer_id", "forged-reviewer"
                ),
            ),
            (
                "scientific-reviewer-evidence",
                self._fresh_scientific,
                "store_scientific_approval",
                lambda value: object.__setattr__(
                    value, "reviewer_evidence", {"statement": "forged"}
                ),
            ),
            (
                "scientific-decision-type",
                self._fresh_scientific,
                "store_scientific_approval",
                lambda value: object.__setattr__(value, "decision", "approved"),
            ),
            (
                "scientific-domain-id-swap",
                self._fresh_scientific,
                "store_scientific_approval",
                lambda value: object.__setattr__(
                    value,
                    "scientific_approval_id",
                    self.batch.batch_submit_approval_id,
                ),
            ),
            (
                "scientific-schema-bool",
                self._fresh_scientific,
                "store_scientific_approval",
                lambda value: object.__setattr__(value, "schema_version", True),
            ),
            (
                "batch-member-attempt",
                self._fresh_batch,
                "store_batch_submit_approval",
                lambda value: object.__setattr__(
                    value.members[0], "attempt_id", "forged-attempt"
                ),
            ),
            (
                "batch-member-task",
                self._fresh_batch,
                "store_batch_submit_approval",
                lambda value: object.__setattr__(
                    value.members[0], "task_id", "forged-task"
                ),
            ),
            (
                "batch-member-plan",
                self._fresh_batch,
                "store_batch_submit_approval",
                lambda value: object.__setattr__(
                    value.members[0], "calculation_plan_id", "forged-plan"
                ),
            ),
            (
                "batch-member-revision-bool",
                self._fresh_batch,
                "store_batch_submit_approval",
                lambda value: object.__setattr__(
                    value.members[0], "calculation_plan_revision", True
                ),
            ),
            (
                "batch-member-scientific-id",
                self._fresh_batch,
                "store_batch_submit_approval",
                lambda value: object.__setattr__(
                    value.members[0], "scientific_approval_id", "forged-science-id"
                ),
            ),
            (
                "batch-members-container",
                self._fresh_batch,
                "store_batch_submit_approval",
                lambda value: object.__setattr__(value, "members", list(value.members)),
            ),
            (
                "batch-empty-members",
                self._fresh_batch,
                "store_batch_submit_approval",
                lambda value: object.__setattr__(value, "members", ()),
            ),
            (
                "batch-reviewer",
                self._fresh_batch,
                "store_batch_submit_approval",
                lambda value: object.__setattr__(
                    value, "reviewer_id", "forged-reviewer"
                ),
            ),
            (
                "batch-reviewer-evidence",
                self._fresh_batch,
                "store_batch_submit_approval",
                lambda value: object.__setattr__(
                    value, "reviewer_evidence", {"scope": "forged"}
                ),
            ),
            (
                "batch-decision-type",
                self._fresh_batch,
                "store_batch_submit_approval",
                lambda value: object.__setattr__(value, "decision", "approved"),
            ),
            (
                "batch-domain-id-swap",
                self._fresh_batch,
                "store_batch_submit_approval",
                lambda value: object.__setattr__(
                    value,
                    "batch_submit_approval_id",
                    self.science.scientific_approval_id,
                ),
            ),
            (
                "batch-schema-bool",
                self._fresh_batch,
                "store_batch_submit_approval",
                lambda value: object.__setattr__(value, "schema_version", True),
            ),
            (
                "confirmation-snapshot-id",
                self._fresh_confirmation,
                "store_operational_confirmation",
                lambda value: object.__setattr__(
                    value, "execution_snapshot_id", "forged-snapshot"
                ),
            ),
            (
                "confirmation-attempt",
                self._fresh_confirmation,
                "store_operational_confirmation",
                lambda value: object.__setattr__(
                    value, "attempt_id", "forged-attempt"
                ),
            ),
            (
                "confirmation-plan",
                self._fresh_confirmation,
                "store_operational_confirmation",
                lambda value: object.__setattr__(
                    value, "calculation_plan_id", "forged-plan"
                ),
            ),
            (
                "confirmation-revision-bool",
                self._fresh_confirmation,
                "store_operational_confirmation",
                lambda value: object.__setattr__(
                    value, "calculation_plan_revision", True
                ),
            ),
            (
                "confirmation-snapshot-semantics",
                self._fresh_confirmation,
                "store_operational_confirmation",
                lambda value: object.__setattr__(
                    value,
                    "execution_snapshot_semantics",
                    {"execution_snapshot_id": "forged", "attempt_id": "attempt-1"},
                ),
            ),
            (
                "confirmation-confirmer",
                self._fresh_confirmation,
                "store_operational_confirmation",
                lambda value: object.__setattr__(
                    value, "confirmer_id", "forged-confirmer"
                ),
            ),
            (
                "confirmation-confirmer-evidence",
                self._fresh_confirmation,
                "store_operational_confirmation",
                lambda value: object.__setattr__(
                    value, "confirmer_evidence", {"displayed": "forged"}
                ),
            ),
            (
                "confirmation-decision-type",
                self._fresh_confirmation,
                "store_operational_confirmation",
                lambda value: object.__setattr__(value, "decision", "approved"),
            ),
            (
                "confirmation-domain-id-swap",
                self._fresh_confirmation,
                "store_operational_confirmation",
                lambda value: object.__setattr__(
                    value,
                    "operational_confirmation_id",
                    self.science.scientific_approval_id,
                ),
            ),
            (
                "confirmation-schema-bool",
                self._fresh_confirmation,
                "store_operational_confirmation",
                lambda value: object.__setattr__(value, "schema_version", True),
            ),
        )

        expected_failures = (
            approval.ApprovalValueError,
            approval.ApprovalStoreConflictError,
        )
        for index, (label, factory, method_name, mutate) in enumerate(cases):
            with self.subTest(label=label):
                database = self.root / f"first-append-forgery-{index}.sqlite3"
                store = approval.SQLiteApprovalStore(database)
                record = factory()
                mutate(record)
                with mock.patch.object(
                    store,
                    "_store",
                    side_effect=AssertionError("SQL append boundary must not be reached"),
                ):
                    with self.assertRaises(expected_failures):
                        getattr(store, method_name)(record)
                self.assertEqual(store.evidence_count(), 0)
                store.close()
                reopened = approval.SQLiteApprovalStore(database)
                self.assertEqual(reopened.evidence_count(), 0)
                reopened.close()

    def test_domain_swapped_records_never_reach_append_boundary(self) -> None:
        store = approval.SQLiteApprovalStore(self.root / "domain-swapped.sqlite3")
        self.addCleanup(store.close)
        cases = (
            (store.store_scientific_approval, self.batch),
            (store.store_batch_submit_approval, self.confirmation),
            (store.store_operational_confirmation, self.science),
        )
        with mock.patch.object(
            store,
            "_store",
            side_effect=AssertionError("SQL append boundary must not be reached"),
        ):
            for persist, record in cases:
                with self.subTest(persist=persist.__name__):
                    with self.assertRaises(approval.ApprovalValueError):
                        persist(record)  # type: ignore[arg-type]
        self.assertEqual(store.evidence_count(), 0)

    def test_hostile_persisted_rows_share_one_fail_closed_integrity_boundary(self) -> None:
        domains = (
            "scientific-approval",
            "batch-submit-approval",
            "operational-confirmation",
        )
        common_corruptions = (
            "missing-embedded-schema",
            "unsupported-embedded-schema",
            "unsupported-row-schema",
            "extra-top-level-field",
            "extra-semantic-field",
            "row-id-changed",
            "embedded-id-changed",
            "payload-changed-id-unchanged",
            "embedded-kind-changed",
            "row-kind-changed",
            "malformed-json",
            "malformed-uuid",
            "revision-bool",
            "duplicate-json-key",
        )
        other_domain = {
            "scientific-approval": "batch-submit-approval",
            "batch-submit-approval": "operational-confirmation",
            "operational-confirmation": "scientific-approval",
        }
        namespace = UUID("5ffbb693-1fe5-5c64-9b2a-68af1871417b")

        for domain in domains:
            for corruption in common_corruptions:
                with self.subTest(domain=domain, corruption=corruption):
                    record, store_name, load_name, identity_field = self._fresh_family(
                        domain
                    )
                    evidence_id = getattr(record, identity_field)
                    database = self.root / f"hostile-{domain}-{corruption}.sqlite3"
                    store = approval.SQLiteApprovalStore(database)
                    getattr(store, store_name)(record)
                    store.close()

                    connection = sqlite3.connect(database)
                    try:
                        row = connection.execute(
                            "SELECT payload FROM approval_evidence WHERE evidence_id = ?",
                            (evidence_id,),
                        ).fetchone()
                        self.assertIsNotNone(row)
                        payload = json.loads(row[0])
                        load_id = evidence_id
                        raw_payload: str | None = None

                        if corruption == "missing-embedded-schema":
                            payload.pop("schema_version")
                        elif corruption == "unsupported-embedded-schema":
                            payload["schema_version"] = 2
                        elif corruption == "unsupported-row-schema":
                            connection.execute("PRAGMA ignore_check_constraints = ON")
                            connection.execute(
                                "UPDATE approval_evidence SET schema_version = 2"
                            )
                        elif corruption == "extra-top-level-field":
                            payload["unexpected"] = "forged"
                        elif corruption == "extra-semantic-field":
                            if domain == "scientific-approval":
                                payload["canonical_intent"]["unexpected"] = "forged"
                            elif domain == "batch-submit-approval":
                                payload["members"][0]["unexpected"] = "forged"
                            else:
                                payload["execution_snapshot_semantics"][
                                    "unexpected"
                                ] = "forged"
                        elif corruption == "row-id-changed":
                            load_id = str(uuid5(namespace, f"row-{domain}"))
                            connection.execute(
                                "UPDATE approval_evidence SET evidence_id = ?",
                                (load_id,),
                            )
                        elif corruption == "embedded-id-changed":
                            payload[identity_field] = str(
                                uuid5(namespace, f"embedded-{domain}")
                            )
                        elif corruption == "payload-changed-id-unchanged":
                            field_name = (
                                "confirmer_id"
                                if domain == "operational-confirmation"
                                else "reviewer_id"
                            )
                            payload[field_name] = "forged-reviewer"
                        elif corruption == "embedded-kind-changed":
                            payload["evidence_kind"] = other_domain[domain]
                        elif corruption == "row-kind-changed":
                            connection.execute(
                                "UPDATE approval_evidence SET domain = ?",
                                (other_domain[domain],),
                            )
                        elif corruption == "malformed-json":
                            raw_payload = "{"
                        elif corruption == "malformed-uuid":
                            load_id = "not-a-uuid"
                            payload[identity_field] = load_id
                            connection.execute(
                                "UPDATE approval_evidence SET evidence_id = ?",
                                (load_id,),
                            )
                        elif corruption == "revision-bool":
                            if domain == "batch-submit-approval":
                                payload["members"][0][
                                    "calculation_plan_revision"
                                ] = True
                            else:
                                payload["calculation_plan_revision"] = True
                        elif corruption == "duplicate-json-key":
                            encoded = json.dumps(payload, sort_keys=True)
                            raw_payload = (
                                '{"schema_version":1,' + encoded[1:]
                            )

                        if corruption not in {
                            "unsupported-row-schema",
                            "row-id-changed",
                            "row-kind-changed",
                        }:
                            connection.execute(
                                "UPDATE approval_evidence SET payload = ?",
                                (
                                    raw_payload
                                    if raw_payload is not None
                                    else json.dumps(payload, sort_keys=True),
                                ),
                            )
                        connection.commit()
                    finally:
                        connection.close()

                    reopened = approval.SQLiteApprovalStore(database)
                    try:
                        with self.assertRaises(approval.ApprovalStoreConflictError):
                            getattr(reopened, load_name)(load_id)
                        if corruption not in {"row-id-changed", "malformed-uuid"}:
                            before = reopened._db().execute(
                                "SELECT domain, evidence_id, schema_version, payload "
                                "FROM approval_evidence"
                            ).fetchall()
                            with self.assertRaises(
                                approval.ApprovalStoreConflictError
                            ):
                                getattr(reopened, store_name)(record)
                            after = reopened._db().execute(
                                "SELECT domain, evidence_id, schema_version, payload "
                                "FROM approval_evidence"
                            ).fetchall()
                            self.assertEqual(
                                [tuple(row) for row in after],
                                [tuple(row) for row in before],
                            )
                        self.assertEqual(reopened.evidence_count(), 1)
                    finally:
                        reopened.close()

    def test_operational_envelope_and_snapshot_duplicates_must_agree(self) -> None:
        mutations = (
            ("attempt_id", "forged-attempt"),
            ("calculation_plan_id", "forged-plan"),
            (
                "execution_snapshot_id",
                "e682de51-7047-5e87-8505-0c8055708bd8",
            ),
        )
        for field_name, changed in mutations:
            with self.subTest(field_name=field_name):
                record = self._fresh_confirmation()
                evidence_id = record.operational_confirmation_id
                database = self.root / f"duplicate-{field_name}.sqlite3"
                store = approval.SQLiteApprovalStore(database)
                store.store_operational_confirmation(record)
                store.close()
                connection = sqlite3.connect(database)
                try:
                    payload = json.loads(
                        connection.execute(
                            "SELECT payload FROM approval_evidence WHERE evidence_id = ?",
                            (evidence_id,),
                        ).fetchone()[0]
                    )
                    payload[field_name] = changed
                    connection.execute(
                        "UPDATE approval_evidence SET payload = ? WHERE evidence_id = ?",
                        (json.dumps(payload, sort_keys=True), evidence_id),
                    )
                    connection.commit()
                finally:
                    connection.close()
                reopened = approval.SQLiteApprovalStore(database)
                try:
                    with self.assertRaises(approval.ApprovalStoreConflictError):
                        reopened.load_operational_confirmation(evidence_id)
                    self.assertEqual(reopened.evidence_count(), 1)
                finally:
                    reopened.close()

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
