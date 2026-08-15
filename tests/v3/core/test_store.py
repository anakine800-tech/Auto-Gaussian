"""Focused and adversarial tests for the V30-CORE-01 SQLite runtime store."""

from __future__ import annotations

import sqlite3
import shutil
import tempfile
import threading
import unittest
from pathlib import Path

import auto_g16.core as core


def store_base_records(store: core.SQLiteRuntimeStore) -> dict[str, object]:
    records: dict[str, object] = {
        "project": core.Project(project_id="project-1"),
        "run": core.WorkflowRun(
            workflow_run_id="run-1",
            project_id="project-1",
            workflow_name="minimum",
        ),
        "batch": core.Batch(
            batch_id="batch-1",
            workflow_run_id="run-1",
            purpose="review",
        ),
        "task": core.Task(
            task_id="task-1",
            workflow_run_id="run-1",
            task_kind="calculation",
            batch_id="batch-1",
        ),
        "plan": core.CalculationPlan(
            calculation_plan_id="plan-1",
            task_id="task-1",
            revision=1,
            intent={"charge": 0, "labels": ["reviewed"]},
        ),
        "resources": core.ResourceSpec(
            resource_spec_id="resources-1",
            task_id="task-1",
            resources={"cores": 8, "memory_mib": 12288},
        ),
        "attempt": core.Attempt(attempt_id="attempt-1", task_id="task-1", ordinal=1),
    }
    store.store_project(records["project"])  # type: ignore[arg-type]
    store.store_workflow_run(records["run"])  # type: ignore[arg-type]
    store.store_batch(records["batch"])  # type: ignore[arg-type]
    store.store_task(records["task"])  # type: ignore[arg-type]
    store.store_calculation_plan(records["plan"])  # type: ignore[arg-type]
    store.store_resource_spec(records["resources"])  # type: ignore[arg-type]
    store.create_attempt(records["attempt"])  # type: ignore[arg-type]
    return records


def store_second_task(store: core.SQLiteRuntimeStore) -> None:
    store.store_task(
        core.Task(
            task_id="task-2",
            workflow_run_id="run-1",
            task_kind="calculation",
            batch_id="batch-1",
        )
    )


class StorePersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.database = Path(self.temporary.name) / "runtime.sqlite3"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_all_ten_records_survive_close_and_reopen(self) -> None:
        with core.SQLiteRuntimeStore(self.database) as store:
            records = store_base_records(store)
            observation = core.Observation(
                observation_id="observation-1",
                attempt_id="attempt-1",
                observation_type="state",
                data={"state": "planned"},
            )
            result = core.Result(
                result_id="result-1",
                attempt_id="attempt-1",
                result_type="parsed",
                data={"complete": False},
            )
            proposal = core.RecoveryProposal(
                recovery_proposal_id="recovery-1",
                attempt_id="attempt-1",
                reason="review required",
                proposed_calculation_plan_id="plan-2",
            )
            store.append_observation(observation)
            store.append_result(result)
            store.store_recovery_proposal(proposal)

        with core.SQLiteRuntimeStore(self.database) as store:
            self.assertEqual(store.load_project("project-1"), records["project"])
            self.assertEqual(store.load_workflow_run("run-1"), records["run"])
            self.assertEqual(store.load_batch("batch-1"), records["batch"])
            self.assertEqual(store.load_task("task-1"), records["task"])
            self.assertEqual(store.load_calculation_plan("plan-1"), records["plan"])
            self.assertEqual(store.load_resource_spec("resources-1"), records["resources"])
            self.assertEqual(store.load_attempt("attempt-1"), records["attempt"])
            self.assertEqual(store.load_recovery_proposal("recovery-1"), proposal)
            self.assertEqual(store.observations_for_attempt("attempt-1"), (observation,))
            self.assertEqual(store.results_for_attempt("attempt-1"), (result,))
            self.assertEqual(store.attempt_state("attempt-1"), core.AttemptState.PLANNED)
            self.assertIsNone(store.parent_attempt_id("attempt-1"))

    def test_unknown_or_unversioned_nonempty_schema_fails_closed(self) -> None:
        connection = sqlite3.connect(self.database)
        connection.execute("PRAGMA user_version = 99")
        connection.close()
        with self.assertRaises(core.RuntimeStoreSchemaError):
            core.SQLiteRuntimeStore(self.database)

        second = Path(self.temporary.name) / "unversioned.sqlite3"
        connection = sqlite3.connect(second)
        connection.execute("CREATE TABLE unrelated (value TEXT)")
        connection.close()
        with self.assertRaises(core.RuntimeStoreSchemaError):
            core.SQLiteRuntimeStore(second)

        third = Path(self.temporary.name) / "incomplete-v1.sqlite3"
        connection = sqlite3.connect(third)
        connection.execute("CREATE TABLE projects (project_id TEXT PRIMARY KEY)")
        connection.execute("PRAGMA user_version = 1")
        connection.close()
        with self.assertRaises(core.RuntimeStoreSchemaError):
            core.SQLiteRuntimeStore(third)

    def test_same_named_counterfeit_v1_tables_fail_closed(self) -> None:
        table_names = (
            "attempts",
            "batches",
            "calculation_plans",
            "observations",
            "projects",
            "reconciliations",
            "recovery_proposals",
            "resource_specs",
            "results",
            "submission_intents",
            "submission_outcomes",
            "tasks",
            "workflow_runs",
        )
        connection = sqlite3.connect(self.database)
        for table_name in table_names:
            connection.execute(f"CREATE TABLE {table_name} (counterfeit TEXT)")
        connection.execute("PRAGMA user_version = 1")
        connection.close()
        with self.assertRaises(core.RuntimeStoreSchemaError):
            core.SQLiteRuntimeStore(self.database)

    def test_v1_reopen_validates_columns_keys_checks_unique_relations_and_indexes(self) -> None:
        with core.SQLiteRuntimeStore(self.database):
            pass
        mutations = (
            (
                "column",
                "projects",
                "project_id TEXT PRIMARY KEY",
                "project_id TEXT PRIMARY KEY, extra TEXT",
            ),
            (
                "primary-key",
                "projects",
                "project_id TEXT PRIMARY KEY",
                "project_id TEXT UNIQUE",
            ),
            (
                "foreign-key",
                "workflow_runs",
                "REFERENCES projects(project_id)",
                "REFERENCES projects(project_id) ON DELETE CASCADE",
            ),
            (
                "check",
                "calculation_plans",
                "CHECK (revision > 0)",
                "CHECK (revision >= 0)",
            ),
            (
                "unique",
                "attempts",
                "UNIQUE (task_id, ordinal)",
                "UNIQUE (task_id, ordinal, state)",
            ),
        )
        for label, object_name, before, after in mutations:
            with self.subTest(label=label):
                candidate = Path(self.temporary.name) / f"{label}.sqlite3"
                shutil.copyfile(self.database, candidate)
                connection = sqlite3.connect(candidate)
                sql = connection.execute(
                    "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
                    (object_name,),
                ).fetchone()[0]
                self.assertIn(before, sql)
                changed = sql.replace(before, after, 1)
                connection.execute("PRAGMA writable_schema = ON")
                connection.execute(
                    "UPDATE sqlite_master SET sql = ? WHERE type = 'table' AND name = ?",
                    (changed, object_name),
                )
                connection.commit()
                schema_version = connection.execute("PRAGMA schema_version").fetchone()[0]
                connection.execute(f"PRAGMA schema_version = {schema_version + 1}")
                connection.execute("PRAGMA writable_schema = OFF")
                connection.close()
                with self.assertRaises(core.RuntimeStoreSchemaError):
                    core.SQLiteRuntimeStore(candidate)

        missing_index = Path(self.temporary.name) / "missing-index.sqlite3"
        shutil.copyfile(self.database, missing_index)
        connection = sqlite3.connect(missing_index)
        connection.execute("DROP INDEX attempt_single_root_per_task")
        connection.close()
        with self.assertRaises(core.RuntimeStoreSchemaError):
            core.SQLiteRuntimeStore(missing_index)

    def test_foreign_key_and_same_workflow_relations_fail_closed(self) -> None:
        with core.SQLiteRuntimeStore(self.database) as store:
            with self.assertRaises(core.RecordConflictError):
                store.store_workflow_run(
                    core.WorkflowRun(
                        workflow_run_id="run-missing",
                        project_id="missing",
                        workflow_name="minimum",
                    )
                )
            store.store_project(core.Project(project_id="project-1"))
            store.store_workflow_run(
                core.WorkflowRun(
                    workflow_run_id="run-1",
                    project_id="project-1",
                    workflow_name="minimum",
                )
            )
            store.store_workflow_run(
                core.WorkflowRun(
                    workflow_run_id="run-2",
                    project_id="project-1",
                    workflow_name="minimum",
                )
            )
            store.store_batch(
                core.Batch(batch_id="batch-1", workflow_run_id="run-1", purpose="review")
            )
            with self.assertRaises(core.RecordConflictError):
                store.store_task(
                    core.Task(
                        task_id="task-1",
                        workflow_run_id="run-2",
                        task_kind="calculation",
                        batch_id="batch-1",
                    )
                )

    def test_immutable_replay_is_idempotent_and_conflict_does_not_overwrite(self) -> None:
        with core.SQLiteRuntimeStore(self.database) as store:
            store.store_project(core.Project(project_id="project-1"))
            first = core.WorkflowRun(
                workflow_run_id="run-1",
                project_id="project-1",
                workflow_name="minimum",
            )
            store.store_workflow_run(first)
            store.store_workflow_run(first)
            with self.assertRaises(core.RecordConflictError):
                store.store_workflow_run(
                    core.WorkflowRun(
                        workflow_run_id="run-1",
                        project_id="project-1",
                        workflow_name="changed",
                    )
                )
            self.assertEqual(store.load_workflow_run("run-1"), first)

    def test_two_store_handles_share_durable_exactly_once_state(self) -> None:
        with core.SQLiteRuntimeStore(self.database) as first:
            store_base_records(first)
            with core.SQLiteRuntimeStore(self.database) as second:
                self.assertEqual(
                    first.record_submission_intent("attempt-1", "intent-1"),
                    core.SubmissionIntentClaim.WINNER,
                )
                self.assertEqual(
                    second.record_submission_intent("attempt-1", "intent-1"),
                    core.SubmissionIntentClaim.REPLAY,
                )
                with self.assertRaises(core.RecordConflictError):
                    second.record_submission_intent("attempt-1", "intent-2")
                second.record_submission_outcome(
                    "attempt-1", "intent-1", core.SubmissionOutcome.UNKNOWN
                )
                self.assertEqual(first.attempt_state("attempt-1"), core.AttemptState.UNKNOWN)

    def test_concurrent_submission_intent_has_one_unique_winner(self) -> None:
        with core.SQLiteRuntimeStore(self.database) as store:
            store_base_records(store)

        barrier = threading.Barrier(3)
        lock = threading.Lock()
        claims: list[core.SubmissionIntentClaim] = []
        errors: list[BaseException] = []

        def contender() -> None:
            try:
                barrier.wait()
                with core.SQLiteRuntimeStore(self.database) as store:
                    claim = store.record_submission_intent("attempt-1", "intent-1")
                with lock:
                    claims.append(claim)
            except BaseException as exc:
                with lock:
                    errors.append(exc)

        threads = [threading.Thread(target=contender) for _index in range(2)]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join(timeout=10)

        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(errors, [])
        self.assertCountEqual(
            claims,
            [core.SubmissionIntentClaim.WINNER, core.SubmissionIntentClaim.REPLAY],
        )
        self.assertNotEqual(
            core.SubmissionIntentClaim.REPLAY, core.SubmissionIntentClaim.WINNER
        )
        with self.assertRaises(TypeError):
            bool(core.SubmissionIntentClaim.WINNER)
        with self.assertRaises(TypeError):
            bool(core.SubmissionIntentClaim.REPLAY)


class AttemptLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = core.SQLiteRuntimeStore()
        store_base_records(self.store)

    def tearDown(self) -> None:
        self.store.close()

    def test_submission_intent_and_outcome_are_exactly_once(self) -> None:
        self.assertEqual(
            self.store.record_submission_intent("attempt-1", "intent-1"),
            core.SubmissionIntentClaim.WINNER,
        )
        self.assertEqual(
            self.store.record_submission_intent("attempt-1", "intent-1"),
            core.SubmissionIntentClaim.REPLAY,
        )
        with self.assertRaises(core.RecordConflictError):
            self.store.record_submission_intent("attempt-1", "intent-2")
        store_second_task(self.store)
        second = core.Attempt(attempt_id="attempt-2", task_id="task-2", ordinal=1)
        self.store.create_attempt(second)
        with self.assertRaises(core.RecordConflictError):
            self.store.record_submission_intent("attempt-2", "intent-1")
        with self.assertRaises(core.RecordConflictError):
            self.store.record_submission_outcome(
                "attempt-1", "intent-2", core.SubmissionOutcome.SUBMITTED
            )
        self.assertEqual(
            self.store.record_submission_outcome(
                "attempt-1", "intent-1", core.SubmissionOutcome.SUBMITTED
            ),
            core.AttemptState.SUBMITTED,
        )
        self.assertEqual(
            self.store.record_submission_outcome(
                "attempt-1", "intent-1", core.SubmissionOutcome.SUBMITTED
            ),
            core.AttemptState.SUBMITTED,
        )
        with self.assertRaises(core.RecordConflictError):
            self.store.record_submission_outcome(
                "attempt-1", "intent-1", core.SubmissionOutcome.UNKNOWN
            )
        self.assertEqual(self.store.attempt_state("attempt-1"), core.AttemptState.SUBMITTED)

    def test_normal_progression_and_terminal_states_fail_closed(self) -> None:
        with self.assertRaises(core.AttemptStateError):
            self.store.advance_attempt("attempt-1", core.AttemptState.RUNNING)
        self.assertEqual(self.store.attempt_state("attempt-1"), core.AttemptState.PLANNED)
        self.store.record_submission_intent("attempt-1", "intent-1")
        self.store.record_submission_outcome(
            "attempt-1", "intent-1", core.SubmissionOutcome.SUBMITTED
        )
        self.assertEqual(
            self.store.advance_attempt("attempt-1", core.AttemptState.RUNNING),
            core.AttemptState.RUNNING,
        )
        self.assertEqual(
            self.store.advance_attempt("attempt-1", core.AttemptState.SUCCEEDED),
            core.AttemptState.SUCCEEDED,
        )
        self.assertEqual(
            self.store.advance_attempt("attempt-1", core.AttemptState.SUCCEEDED),
            core.AttemptState.SUCCEEDED,
        )
        with self.assertRaises(core.AttemptStateError):
            self.store.advance_attempt("attempt-1", core.AttemptState.FAILED)
        self.assertEqual(self.store.attempt_state("attempt-1"), core.AttemptState.SUCCEEDED)

    def test_unknown_requires_persisted_same_attempt_evidence(self) -> None:
        self.store.record_submission_intent("attempt-1", "intent-1")
        self.store.record_submission_outcome(
            "attempt-1", "intent-1", core.SubmissionOutcome.UNKNOWN
        )
        with self.assertRaises(core.RecordNotFoundError):
            self.store.reconcile_unknown(
                "attempt-1", "missing", core.ReconciliationResolution.SUBMITTED
            )
        with self.assertRaises(core.AttemptStateError):
            self.store.advance_attempt("attempt-1", core.AttemptState.RUNNING)
        observation = core.Observation(
            observation_id="observation-1",
            attempt_id="attempt-1",
            observation_type="reconciliation",
            data={"submitted": None},
        )
        self.store.append_observation(observation)
        self.assertEqual(
            self.store.reconcile_unknown(
                "attempt-1", "observation-1", core.ReconciliationResolution.UNRESOLVED
            ),
            core.AttemptState.UNKNOWN,
        )
        self.assertEqual(
            self.store.reconcile_unknown(
                "attempt-1", "observation-1", core.ReconciliationResolution.NOT_SUBMITTED
            ),
            core.AttemptState.NOT_SUBMITTED,
        )
        self.assertEqual(
            self.store.reconcile_unknown(
                "attempt-1", "observation-1", core.ReconciliationResolution.NOT_SUBMITTED
            ),
            core.AttemptState.NOT_SUBMITTED,
        )
        with self.assertRaises(core.RecordConflictError):
            self.store.reconcile_unknown(
                "attempt-1", "observation-1", core.ReconciliationResolution.SUBMITTED
            )

    def test_cross_attempt_observation_cannot_reconcile_unknown(self) -> None:
        store_second_task(self.store)
        second = core.Attempt(attempt_id="attempt-2", task_id="task-2", ordinal=1)
        self.store.create_attempt(second)
        self.store.record_submission_intent("attempt-2", "intent-2")
        self.store.record_submission_outcome(
            "attempt-2", "intent-2", core.SubmissionOutcome.UNKNOWN
        )
        self.store.append_observation(
            core.Observation(
                observation_id="observation-1",
                attempt_id="attempt-1",
                observation_type="state",
            )
        )
        with self.assertRaises(core.RecordConflictError):
            self.store.reconcile_unknown(
                "attempt-2", "observation-1", core.ReconciliationResolution.SUBMITTED
            )
        self.assertEqual(self.store.attempt_state("attempt-2"), core.AttemptState.UNKNOWN)

    def test_unknown_root_cannot_be_bypassed_by_second_root(self) -> None:
        self.store.record_submission_intent("attempt-1", "intent-1")
        self.store.record_submission_outcome(
            "attempt-1", "intent-1", core.SubmissionOutcome.UNKNOWN
        )
        bypass = core.Attempt(attempt_id="attempt-2", task_id="task-1", ordinal=2)
        with self.assertRaises(core.RecordConflictError):
            self.store.create_attempt(bypass)
        with self.assertRaises(core.RecordNotFoundError):
            self.store.record_submission_intent("attempt-2", "intent-2")
        self.assertEqual(self.store.attempt_state("attempt-1"), core.AttemptState.UNKNOWN)

    def test_child_attempt_requires_explicit_terminal_parent_and_preserves_lineage(self) -> None:
        self.store.record_submission_intent("attempt-1", "intent-1")
        self.store.record_submission_outcome(
            "attempt-1", "intent-1", core.SubmissionOutcome.UNKNOWN
        )
        child = core.Attempt(attempt_id="attempt-2", task_id="task-1", ordinal=2)
        with self.assertRaises(core.AttemptStateError):
            self.store.create_child_attempt("attempt-1", child)
        self.store.append_observation(
            core.Observation(
                observation_id="observation-1",
                attempt_id="attempt-1",
                observation_type="reconciliation",
                data={"submitted": False},
            )
        )
        self.store.reconcile_unknown(
            "attempt-1", "observation-1", core.ReconciliationResolution.NOT_SUBMITTED
        )
        self.store.create_child_attempt("attempt-1", child)
        self.store.create_child_attempt("attempt-1", child)
        self.assertEqual(self.store.load_attempt("attempt-2"), child)
        self.assertEqual(self.store.parent_attempt_id("attempt-2"), "attempt-1")
        self.assertEqual(self.store.attempt_state("attempt-2"), core.AttemptState.PLANNED)
        with self.assertRaises(core.RecordConflictError):
            self.store.create_child_attempt(
                "attempt-1",
                core.Attempt(attempt_id="attempt-3", task_id="task-1", ordinal=1),
            )
        self.store.record_submission_intent("attempt-2", "intent-2")
        self.store.record_submission_outcome(
            "attempt-2", "intent-2", core.SubmissionOutcome.SUBMITTED
        )
        self.store.advance_attempt("attempt-2", core.AttemptState.FAILED)
        grandchild = core.Attempt(attempt_id="attempt-3", task_id="task-1", ordinal=3)
        self.store.create_child_attempt("attempt-2", grandchild)
        self.assertEqual(self.store.parent_attempt_id("attempt-3"), "attempt-2")


class EvidencePersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.database = Path(self.temporary.name) / "runtime.sqlite3"
        self.store = core.SQLiteRuntimeStore(self.database)
        store_base_records(self.store)

    def tearDown(self) -> None:
        self.store.close()
        self.temporary.cleanup()

    def test_observations_and_results_are_ordered_replay_safe_and_append_only(self) -> None:
        first_observation = core.Observation(
            observation_id="observation-1",
            attempt_id="attempt-1",
            observation_type="state",
            data={"sequence": 1},
        )
        second_observation = core.Observation(
            observation_id="observation-2",
            attempt_id="attempt-1",
            observation_type="state",
            data={"sequence": 2},
        )
        first_result = core.Result(
            result_id="result-1",
            attempt_id="attempt-1",
            result_type="parsed",
            data={"sequence": 1},
        )
        second_result = core.Result(
            result_id="result-2",
            attempt_id="attempt-1",
            result_type="parsed",
            data={"sequence": 2},
        )
        self.store.append_observation(first_observation)
        self.store.append_observation(second_observation)
        self.store.append_observation(first_observation)
        self.store.append_result(first_result)
        self.store.append_result(second_result)
        self.store.append_result(first_result)
        with self.assertRaises(core.RecordConflictError):
            self.store.append_observation(
                core.Observation(
                    observation_id="observation-1",
                    attempt_id="attempt-1",
                    observation_type="changed",
                )
            )
        with self.assertRaises(core.RecordConflictError):
            self.store.append_result(
                core.Result(
                    result_id="result-1",
                    attempt_id="attempt-1",
                    result_type="changed",
                )
            )
        self.assertEqual(
            self.store.observations_for_attempt("attempt-1"),
            (first_observation, second_observation),
        )
        self.assertEqual(
            self.store.results_for_attempt("attempt-1"),
            (first_result, second_result),
        )

    def test_submission_intent_and_unknown_survive_reopen_without_retry_authority(self) -> None:
        self.store.record_submission_intent("attempt-1", "intent-1")
        self.store.record_submission_outcome(
            "attempt-1", "intent-1", core.SubmissionOutcome.UNKNOWN
        )
        self.store.close()
        self.store = core.SQLiteRuntimeStore(self.database)
        self.assertEqual(
            self.store.record_submission_intent("attempt-1", "intent-1"),
            core.SubmissionIntentClaim.REPLAY,
        )
        self.assertEqual(
            self.store.record_submission_outcome(
                "attempt-1", "intent-1", core.SubmissionOutcome.UNKNOWN
            ),
            core.AttemptState.UNKNOWN,
        )
        with self.assertRaises(core.RecordConflictError):
            self.store.record_submission_intent("attempt-1", "intent-2")
        with self.assertRaises(core.AttemptStateError):
            self.store.create_child_attempt(
                "attempt-1",
                core.Attempt(attempt_id="attempt-2", task_id="task-1", ordinal=2),
            )

    def test_evidence_requires_existing_attempt(self) -> None:
        with self.assertRaises(core.RecordConflictError):
            self.store.append_observation(
                core.Observation(
                    observation_id="observation-missing",
                    attempt_id="missing",
                    observation_type="state",
                )
            )
        with self.assertRaises(core.RecordConflictError):
            self.store.append_result(
                core.Result(
                    result_id="result-missing",
                    attempt_id="missing",
                    result_type="parsed",
                )
            )


if __name__ == "__main__":
    unittest.main()
