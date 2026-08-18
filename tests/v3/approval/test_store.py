from __future__ import annotations

from collections.abc import Callable
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock
from uuid import UUID, uuid5

import auto_g16.approval as approval
from auto_g16.approval import models as approval_models
from auto_g16.approval import store as approval_store
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
        self.current_snapshot = snapshot(self.runtime, self.root / "local")
        self.confirmation = approval.ExactOperationalConfirmation.for_snapshot(
            self.runtime,
            self.current_snapshot,
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
            return (
                self._fresh_scientific(),
                "store_scientific_approval",
                "load_scientific_approval",
                "scientific_approval_id",
            )
        if domain == "batch-submit-approval":
            return (
                self._fresh_batch(),
                "store_batch_submit_approval",
                "load_batch_submit_approval",
                "batch_submit_approval_id",
            )
        return (
            self._fresh_confirmation(),
            "store_operational_confirmation",
            "load_operational_confirmation",
            "operational_confirmation_id",
        )

    @staticmethod
    def _raw_count(database: Path) -> int:
        with closing(sqlite3.connect(database)) as connection:
            return connection.execute(
                "SELECT COUNT(*) FROM approval_evidence"
            ).fetchone()[0]

    @staticmethod
    def _rewrite_operational_row(
        database: Path,
        evidence_id: str,
        mutate: Callable[[dict[str, object]], None],
    ) -> str:
        with closing(sqlite3.connect(database)) as connection:
            payload = json.loads(
                connection.execute(
                    "SELECT payload_json FROM approval_evidence "
                    "WHERE evidence_id = ?",
                    (evidence_id,),
                ).fetchone()[0]
            )
            mutate(payload)
            authority = {
                key: payload[key]
                for key in (
                    "execution_snapshot_id",
                    "attempt_id",
                    "calculation_plan_id",
                    "calculation_plan_revision",
                    "execution_snapshot_semantics",
                    "confirmer_id",
                    "confirmer_evidence",
                    "decision",
                )
            }
            rewritten_id = approval_models.identity_for(
                "operational-confirmation", authority
            )
            payload["operational_confirmation_id"] = rewritten_id
            connection.execute(
                "UPDATE approval_evidence SET evidence_id = ?, payload_json = ? "
                "WHERE evidence_id = ?",
                (rewritten_id, json.dumps(payload, sort_keys=True), evidence_id),
            )
            connection.commit()
        return rewritten_id

    def test_sqlite_v1_identity_is_exact_and_minimal(self) -> None:
        database = self.root / "approval.sqlite3"
        with approval.SQLiteApprovalStore(database) as store:
            self.assertEqual(store.evidence_count(), 0)
        with closing(sqlite3.connect(database)) as connection:
            self.assertEqual(
                connection.execute("PRAGMA application_id").fetchone()[0],
                0x41473341,
            )
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 1)
            objects = connection.execute(
                "SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name"
            ).fetchall()
            self.assertEqual(len(objects), 1)
            self.assertEqual(objects[0][0:3], ("table", "approval_evidence", "approval_evidence"))
            self.assertEqual(objects[0][3], approval_store._SCHEMA)
            self.assertTrue(objects[0][3].endswith("WITHOUT ROWID"))
            self.assertNotIn("AUTOINCREMENT", objects[0][3])
            self.assertEqual(
                connection.execute("PRAGMA table_xinfo('approval_evidence')").fetchall(),
                list(approval_store._TABLE_XINFO),
            )

    def test_create_new_is_exclusive_and_incomplete_existing_files_fail_closed(self) -> None:
        zero = self.root / "zero.sqlite3"
        zero.touch()
        with self.assertRaises(approval.ApprovalPersistenceIntegrityError):
            approval.SQLiteApprovalStore(zero)
        self.assertEqual(zero.stat().st_size, 0)

        half = self.root / "half.sqlite3"
        with closing(sqlite3.connect(half)) as connection:
            connection.execute("PRAGMA application_id = 123")
            connection.execute("PRAGMA user_version = 1")
        before = half.read_bytes()
        with self.assertRaises(approval.ApprovalPersistenceIntegrityError):
            approval.SQLiteApprovalStore(half)
        self.assertEqual(half.read_bytes(), before)

    def test_terminal_symlink_aliases_fail_before_sqlite_open(self) -> None:
        database = self.root / "direct.sqlite3"
        with approval.SQLiteApprovalStore(database) as direct:
            self.assertEqual(direct.evidence_count(), 0)

        alias = self.root / "alias.sqlite3"
        alias.symlink_to(database)
        self.assertEqual(
            approval.SQLiteApprovalStore._canonical_database_path(alias), alias
        )
        with self.assertRaises(approval.ApprovalPersistenceIntegrityError):
            approval.SQLiteApprovalStore(alias)

        create_alias = self.root / "create-alias.sqlite3"
        create_alias.symlink_to(self.root / "missing.sqlite3")
        with self.assertRaises(approval.ApprovalPersistenceIntegrityError):
            approval.SQLiteApprovalStore(create_alias)
        self.assertTrue(create_alias.is_symlink())
        self.assertFalse((self.root / "missing.sqlite3").exists())

        with approval.SQLiteApprovalStore(database) as reopened:
            self.assertEqual(reopened.evidence_count(), 0)

    def test_failed_initialization_is_retained_and_never_auto_repaired(self) -> None:
        database = self.root / "failed-init.sqlite3"
        with mock.patch.object(approval_store, "_SCHEMA", "CREATE TABL broken"):
            with self.assertRaises(approval.ApprovalPersistenceIntegrityError):
                approval.SQLiteApprovalStore(database)
        self.assertTrue(database.exists())
        retained = database.read_bytes()
        with self.assertRaises(approval.ApprovalPersistenceIntegrityError):
            approval.SQLiteApprovalStore(database)
        self.assertEqual(database.read_bytes(), retained)

    def test_all_domains_are_idempotent_and_durable_across_reopen(self) -> None:
        database = self.root / "approval.sqlite3"
        first = approval.SQLiteApprovalStore(database)
        for _ in range(2):
            first.store_scientific_approval(self.science)
            first.store_batch_submit_approval(self.batch)
            first.store_operational_confirmation(self.confirmation)
        self.assertEqual(first.evidence_count(), 3)
        first.close()
        with approval.SQLiteApprovalStore(database) as reopened:
            reopened.store_scientific_approval(self.science)
            reopened.store_batch_submit_approval(self.batch)
            reopened.store_operational_confirmation(self.confirmation)
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
            rejected = scientific(
                self.runtime, decision=approval.ApprovalDecision.REJECTED
            )
            reopened.store_scientific_approval(rejected)
            rejected_id = rejected.scientific_approval_id
        with approval.SQLiteApprovalStore(database) as final_reopen:
            self.assertEqual(
                final_reopen.load_scientific_approval(rejected_id), rejected
            )
            self.assertEqual(final_reopen.evidence_count(), 4)

    def test_operational_confirmation_replay_requires_exact_current_snapshot(self) -> None:
        database = self.root / "current-confirmation.sqlite3"
        with approval.SQLiteApprovalStore(database) as store:
            store.store_operational_confirmation(self.confirmation)
            self.assertEqual(
                store.load_current_operational_confirmation(
                    self.confirmation.operational_confirmation_id,
                    self.current_snapshot,
                ),
                self.confirmation,
            )
        with approval.SQLiteApprovalStore(database) as reopened:
            self.assertEqual(
                reopened.load_current_operational_confirmation(
                    self.confirmation.operational_confirmation_id,
                    self.current_snapshot,
                ),
                self.confirmation,
            )

    def test_current_snapshot_is_closed_by_public_execution_verifier(self) -> None:
        database = self.root / "stale-current.sqlite3"
        current_snapshot = snapshot(self.runtime, self.root / "stale-current-local")
        confirmation = approval.ExactOperationalConfirmation.for_snapshot(
            self.runtime,
            current_snapshot,
            confirmer_id="operator-1",
            confirmer_evidence={"displayed": "exact snapshot"},
        )
        with approval.SQLiteApprovalStore(database) as store:
            store.store_operational_confirmation(confirmation)
            object.__setattr__(
                current_snapshot.resolved_resource_request, "cores", 99
            )
            with self.assertRaises(execution.ExecutionValueError):
                execution.assert_execution_snapshot_identity(current_snapshot)
            with self.assertRaises(execution.ExecutionValueError):
                store.load_current_operational_confirmation(
                    confirmation.operational_confirmation_id,
                    current_snapshot,
                )

    def test_rewritten_persisted_snapshot_never_authenticates_current_authority(
        self,
    ) -> None:
        namespace = UUID("5ffbb693-1fe5-5c64-9b2a-68af1871417b")

        def change_cores(payload: dict[str, object]) -> None:
            semantics = payload["execution_snapshot_semantics"]
            assert isinstance(semantics, dict)
            resources = semantics["resolved_resource_request"]
            assert isinstance(resources, dict)
            resources["cores"] = 99

        def change_snapshot_id(payload: dict[str, object]) -> None:
            changed = str(uuid5(namespace, "different-snapshot"))
            payload["execution_snapshot_id"] = changed
            semantics = payload["execution_snapshot_semantics"]
            assert isinstance(semantics, dict)
            semantics["execution_snapshot_id"] = changed

        def change_submission_intent(payload: dict[str, object]) -> None:
            semantics = payload["execution_snapshot_semantics"]
            assert isinstance(semantics, dict)
            semantics["submission_intent_id"] = str(
                uuid5(namespace, "different-submission-intent")
            )

        def change_attempt(payload: dict[str, object]) -> None:
            payload["attempt_id"] = "different-attempt"
            semantics = payload["execution_snapshot_semantics"]
            assert isinstance(semantics, dict)
            semantics["attempt_id"] = "different-attempt"
            prepared = semantics["prepared_input_binding"]
            workspace = semantics["workspace_binding"]
            assert isinstance(prepared, dict)
            assert isinstance(workspace, dict)
            prepared["attempt_id"] = "different-attempt"
            workspace["attempt_id"] = "different-attempt"

        def change_plan(payload: dict[str, object]) -> None:
            payload["calculation_plan_id"] = "different-plan"
            semantics = payload["execution_snapshot_semantics"]
            assert isinstance(semantics, dict)
            semantics["calculation_plan_id"] = "different-plan"
            prepared = semantics["prepared_input_binding"]
            assert isinstance(prepared, dict)
            prepared["calculation_plan_id"] = "different-plan"

        def change_revision(payload: dict[str, object]) -> None:
            payload["calculation_plan_revision"] = 4
            semantics = payload["execution_snapshot_semantics"]
            assert isinstance(semantics, dict)
            semantics["calculation_plan_revision"] = 4
            prepared = semantics["prepared_input_binding"]
            assert isinstance(prepared, dict)
            prepared["calculation_plan_revision"] = 4

        mutations = {
            "cores": change_cores,
            "snapshot-id": change_snapshot_id,
            "submission-intent": change_submission_intent,
            "attempt": change_attempt,
            "plan": change_plan,
            "revision": change_revision,
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                database = self.root / f"rewritten-{label}.sqlite3"
                with approval.SQLiteApprovalStore(database) as store:
                    store.store_operational_confirmation(self.confirmation)
                rewritten_id = self._rewrite_operational_row(
                    database,
                    self.confirmation.operational_confirmation_id,
                    mutate,
                )
                with approval.SQLiteApprovalStore(database) as reopened:
                    structurally_valid = reopened.load_operational_confirmation(
                        rewritten_id
                    )
                    self.assertEqual(
                        structurally_valid.operational_confirmation_id,
                        rewritten_id,
                    )
                    with self.assertRaises(approval.ApprovalStoreConflictError):
                        reopened.load_current_operational_confirmation(
                            rewritten_id,
                            self.current_snapshot,
                        )

    def test_same_identity_different_payload_conflicts_for_every_domain(self) -> None:
        with approval.SQLiteApprovalStore(self.root / "approval.sqlite3") as store:
            records = (
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
            )
            for record, persist, field_name, changed in records:
                persist(record)
                object.__setattr__(record, field_name, changed)
                with self.assertRaises(approval.ApprovalStoreConflictError):
                    persist(record)
            self.assertEqual(store.evidence_count(), 3)

    def test_first_append_rejects_counterfeit_authority_before_sql(self) -> None:
        cases = (
            (
                self._fresh_scientific,
                "store_scientific_approval",
                lambda value: object.__setattr__(
                    value, "reviewer_id", "forged-reviewer"
                ),
            ),
            (
                self._fresh_batch,
                "store_batch_submit_approval",
                lambda value: object.__setattr__(
                    value.members[0], "attempt_id", "forged-attempt"
                ),
            ),
            (
                self._fresh_confirmation,
                "store_operational_confirmation",
                lambda value: object.__setattr__(
                    value, "execution_snapshot_id", "forged-snapshot"
                ),
            ),
        )
        for index, (factory, method_name, mutate) in enumerate(cases):
            with self.subTest(method=method_name):
                database = self.root / f"counterfeit-{index}.sqlite3"
                with approval.SQLiteApprovalStore(database) as store:
                    record = factory()
                    mutate(record)
                    with mock.patch.object(
                        store,
                        "_store",
                        side_effect=AssertionError("SQL boundary must not be reached"),
                    ):
                        with self.assertRaises(
                            (approval.ApprovalValueError, approval.ApprovalStoreConflictError)
                        ):
                            getattr(store, method_name)(record)
                    self.assertEqual(store.evidence_count(), 0)
                with approval.SQLiteApprovalStore(database) as reopened:
                    self.assertEqual(reopened.evidence_count(), 0)

    def test_domain_swapped_records_never_reach_append_boundary(self) -> None:
        with approval.SQLiteApprovalStore(self.root / "domain.sqlite3") as store:
            cases = (
                (store.store_scientific_approval, self.batch),
                (store.store_batch_submit_approval, self.confirmation),
                (store.store_operational_confirmation, self.science),
            )
            with mock.patch.object(
                store,
                "_store",
                side_effect=AssertionError("SQL boundary must not be reached"),
            ):
                for persist, record in cases:
                    with self.assertRaises(approval.ApprovalValueError):
                        persist(record)  # type: ignore[arg-type]
            self.assertEqual(store.evidence_count(), 0)

    def test_persistent_schema_attack_matrix_fails_closed(self) -> None:
        attacks = {
            "before-trigger": """
                CREATE TRIGGER suppress_approval BEFORE INSERT ON approval_evidence
                BEGIN SELECT RAISE(IGNORE); END
            """,
            "after-trigger": """
                CREATE TRIGGER mutate_approval AFTER INSERT ON approval_evidence
                BEGIN UPDATE approval_evidence SET payload_json='{}'
                WHERE evidence_id=NEW.evidence_id; END
            """,
            "view": "CREATE VIEW approval_shadow AS SELECT * FROM approval_evidence",
            "index": "CREATE INDEX approval_kind_index ON approval_evidence(evidence_kind)",
            "table": "CREATE TABLE approval_shadow(value TEXT)",
        }
        for label, statement in attacks.items():
            with self.subTest(label=label):
                database = self.root / f"schema-{label}.sqlite3"
                with approval.SQLiteApprovalStore(database):
                    pass
                with closing(sqlite3.connect(database)) as connection:
                    connection.executescript(statement)
                with self.assertRaises(approval.ApprovalPersistenceIntegrityError):
                    approval.SQLiteApprovalStore(database)

    def test_suppressed_append_never_reports_success_or_mutates_rows(self) -> None:
        database = self.root / "suppressed.sqlite3"
        with approval.SQLiteApprovalStore(database) as store:
            with closing(sqlite3.connect(database)) as attacker:
                attacker.executescript(
                    """
                    CREATE TRIGGER suppress_approval BEFORE INSERT ON approval_evidence
                    BEGIN SELECT RAISE(IGNORE); END;
                    """
                )
            with self.assertRaises(approval.ApprovalPersistenceIntegrityError):
                store.store_scientific_approval(self.science)
        self.assertEqual(self._raw_count(database), 0)

    def test_temp_trigger_and_attach_fail_before_authority_write(self) -> None:
        temp_database = self.root / "temp.sqlite3"
        with approval.SQLiteApprovalStore(temp_database) as store:
            store._db().executescript(
                """
                CREATE TEMP TRIGGER temp_suppress BEFORE INSERT
                ON main.approval_evidence
                BEGIN SELECT RAISE(IGNORE); END;
                """
            )
            with self.assertRaises(approval.ApprovalPersistenceIntegrityError):
                store.store_scientific_approval(self.science)
        self.assertEqual(self._raw_count(temp_database), 0)

        attached_database = self.root / "attached.sqlite3"
        with approval.SQLiteApprovalStore(attached_database) as store:
            store._db().execute("ATTACH DATABASE ':memory:' AS surprise")
            with self.assertRaises(approval.ApprovalPersistenceIntegrityError):
                store.store_scientific_approval(self.science)
        self.assertEqual(self._raw_count(attached_database), 0)

    def test_database_header_attack_matrix_fails_closed(self) -> None:
        for pragma, value in (("application_id", 123), ("user_version", 2)):
            with self.subTest(pragma=pragma):
                database = self.root / f"wrong-{pragma}.sqlite3"
                with approval.SQLiteApprovalStore(database):
                    pass
                with closing(sqlite3.connect(database)) as connection:
                    connection.execute(f"PRAGMA {pragma} = {value}")
                with self.assertRaises(approval.ApprovalPersistenceIntegrityError):
                    approval.SQLiteApprovalStore(database)

    def test_hostile_persisted_rows_share_one_fail_closed_integrity_boundary(self) -> None:
        domains = (
            "scientific-approval",
            "batch-submit-approval",
            "operational-confirmation",
        )
        corruptions = (
            "malformed-json",
            "extra-field",
            "evidence-id-mismatch",
            "kind-mismatch",
            "payload-drift",
        )
        other_domain = {
            "scientific-approval": "batch-submit-approval",
            "batch-submit-approval": "operational-confirmation",
            "operational-confirmation": "scientific-approval",
        }
        namespace = UUID("5ffbb693-1fe5-5c64-9b2a-68af1871417b")

        for domain in domains:
            for corruption in corruptions:
                with self.subTest(domain=domain, corruption=corruption):
                    record, store_name, _load_name, identity_field = self._fresh_family(
                        domain
                    )
                    evidence_id = getattr(record, identity_field)
                    database = self.root / f"hostile-{domain}-{corruption}.sqlite3"
                    with approval.SQLiteApprovalStore(database) as store:
                        getattr(store, store_name)(record)
                    with closing(sqlite3.connect(database)) as connection:
                        payload_text = connection.execute(
                            "SELECT payload_json FROM approval_evidence "
                            "WHERE evidence_id = ?",
                            (evidence_id,),
                        ).fetchone()[0]
                        payload = json.loads(payload_text)
                        if corruption == "malformed-json":
                            connection.execute(
                                "UPDATE approval_evidence SET payload_json = ?",
                                ("{",),
                            )
                        elif corruption == "extra-field":
                            payload["unexpected_authority_shadow"] = True
                            connection.execute(
                                "UPDATE approval_evidence SET payload_json = ?",
                                (json.dumps(payload, sort_keys=True),),
                            )
                        elif corruption == "evidence-id-mismatch":
                            changed_id = str(uuid5(namespace, f"row-{domain}"))
                            connection.execute(
                                "UPDATE approval_evidence SET evidence_id = ?",
                                (changed_id,),
                            )
                        elif corruption == "kind-mismatch":
                            connection.execute(
                                "UPDATE approval_evidence SET evidence_kind = ?",
                                (other_domain[domain],),
                            )
                        else:
                            field = (
                                "confirmer_id"
                                if domain == "operational-confirmation"
                                else "reviewer_id"
                            )
                            payload[field] = "forged-authority"
                            connection.execute(
                                "UPDATE approval_evidence SET payload_json = ?",
                                (json.dumps(payload, sort_keys=True),),
                            )
                        connection.commit()
                    with self.assertRaises(approval.ApprovalPersistenceIntegrityError):
                        approval.SQLiteApprovalStore(database)
                    self.assertEqual(self._raw_count(database), 1)

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
                with approval.SQLiteApprovalStore(database) as store:
                    store.store_operational_confirmation(record)
                with closing(sqlite3.connect(database)) as connection:
                    payload = json.loads(
                        connection.execute(
                            "SELECT payload_json FROM approval_evidence "
                            "WHERE evidence_id = ?",
                            (evidence_id,),
                        ).fetchone()[0]
                    )
                    payload[field_name] = changed
                    connection.execute(
                        "UPDATE approval_evidence SET payload_json = ? "
                        "WHERE evidence_id = ?",
                        (json.dumps(payload, sort_keys=True), evidence_id),
                    )
                    connection.commit()
                with self.assertRaises(approval.ApprovalPersistenceIntegrityError):
                    approval.SQLiteApprovalStore(database)

    def test_begin_immediate_closes_cooperative_schema_toctou(self) -> None:
        database = self.root / "locked.sqlite3"
        with approval.SQLiteApprovalStore(database) as store:
            attacker = sqlite3.connect(database, timeout=0.05, isolation_level=None)
            self.addCleanup(attacker.close)
            with store._transaction(immediate=True) as transaction:
                store._attest_database_and_decode_all_rows(transaction)
                with self.assertRaisesRegex(sqlite3.OperationalError, "locked"):
                    attacker.execute("CREATE TABLE injected(value TEXT)")
                store._attest_database_and_decode_all_rows(transaction)
            store.store_scientific_approval(self.science)
            self.assertEqual(store.evidence_count(), 1)

    def test_approval_store_is_independent_from_core_schema(self) -> None:
        approval_database = self.root / "approval.sqlite3"
        with approval.SQLiteApprovalStore(approval_database) as store:
            store.store_scientific_approval(self.science)
        with closing(sqlite3.connect(approval_database)) as connection:
            objects = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_schema WHERE type='table'"
                )
            }
            self.assertEqual(objects, {"approval_evidence"})
        with closing(sqlite3.connect(self.root / "runtime.sqlite3")) as connection:
            objects = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_schema WHERE type='table'"
                )
            }
            self.assertNotIn("approval_evidence", objects)

    def test_rejected_decisions_persist_but_never_validate(self) -> None:
        rejected = scientific(self.runtime, decision=approval.ApprovalDecision.REJECTED)
        with approval.SQLiteApprovalStore(self.root / "approval.sqlite3") as store:
            store.store_scientific_approval(rejected)
            loaded = store.load_scientific_approval(rejected.scientific_approval_id)
            with self.assertRaises(approval.ApprovalRejectedError):
                loaded.assert_current(
                    plan(), displayed_semantic_meaning=DISPLAYED_MEANING
                )


if __name__ == "__main__":
    unittest.main()
