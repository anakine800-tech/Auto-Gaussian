"""Persistence and adversarial projection tests for minimal Observe."""

from __future__ import annotations

import ast
from pathlib import Path
import tempfile
import unittest

import auto_g16.core as core
import auto_g16.observe as observe


def populate_core(store: core.SQLiteRuntimeStore) -> None:
    store.store_project(core.Project(project_id="project-1"))
    store.store_workflow_run(
        core.WorkflowRun(
            workflow_run_id="run-1",
            project_id="project-1",
            workflow_name="minimum",
        )
    )
    store.store_task(
        core.Task(
            task_id="task-1",
            workflow_run_id="run-1",
            task_kind="calculation",
        )
    )
    store.create_attempt(core.Attempt(attempt_id="attempt-1", task_id="task-1", ordinal=1))
    store.store_task(
        core.Task(
            task_id="task-2",
            workflow_run_id="run-1",
            task_kind="calculation",
        )
    )
    store.create_attempt(core.Attempt(attempt_id="attempt-2", task_id="task-2", ordinal=1))


def sample(
    *,
    attempt_id: str = "attempt-1",
    source_kind: str = "scheduler",
    source_identity: str = "source-1",
    observed_at_utc: str = "2026-08-22T00:00:00.000000Z",
    freshness: str = "fresh",
    state: str = "running",
    progress_position: int | None = None,
) -> observe.AttemptObservation:
    return observe.AttemptObservation(
        attempt_id=attempt_id,
        source_kind=source_kind,
        source_identity=source_identity,
        observed_at_utc=observed_at_utc,
        freshness=freshness,
        state=state,
        progress_position=progress_position,
    )


class ObserveServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.database = Path(self.temporary.name) / "runtime.sqlite3"
        self.store = core.SQLiteRuntimeStore(self.database)
        populate_core(self.store)

    def tearDown(self) -> None:
        self.store.close()
        self.temporary.cleanup()

    def test_record_has_exact_core_payload_and_replay_is_idempotent(self) -> None:
        observation = sample()
        observe.record_attempt_observation(self.store, observation)
        observe.record_attempt_observation(self.store, observation)
        self.assertEqual(
            self.store.attempt_state("attempt-1"), core.AttemptState.PLANNED
        )
        records = self.store.observations_for_attempt("attempt-1")
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record.observation_id, observation.observation_id)
        self.assertEqual(record.attempt_id, "attempt-1")
        self.assertEqual(record.observation_type, observe.OBSERVATION_TYPE)
        self.assertEqual(
            dict(record.data),
            {
                "freshness": "fresh",
                "observed_at_utc": "2026-08-22T00:00:00.000000Z",
                "progress_position": None,
                "source_identity": "source-1",
                "source_kind": "scheduler",
                "state": "running",
            },
        )

    def test_missing_attempt_fails_before_append(self) -> None:
        with self.assertRaises(core.RecordNotFoundError):
            observe.record_attempt_observation(
                self.store, sample(attempt_id="missing-attempt")
            )
        self.assertEqual(self.store.observations_for_attempt("attempt-1"), ())

    def test_projection_uses_append_order_not_timestamp(self) -> None:
        first = sample(
            source_identity="newer-time",
            observed_at_utc="2026-08-22T02:00:00.000000Z",
            freshness="fresh",
            state="running",
        )
        second = sample(
            source_identity="later-append",
            observed_at_utc="2026-08-22T01:00:00.000000Z",
            freshness="stale",
            state="queued",
        )
        process = sample(
            source_kind="process",
            source_identity="process-1",
            state="absent",
        )
        gaussian = sample(
            source_kind="gaussian",
            source_identity="gaussian-1",
            state="optimization",
            progress_position=9,
        )
        for item in (first, process, gaussian, second):
            observe.record_attempt_observation(self.store, item)
        projection = observe.project_attempt_observations(
            self.store, attempt_id="attempt-1"
        )
        self.assertEqual(projection.scheduler, second)
        self.assertEqual(projection.process, process)
        self.assertEqual(projection.gaussian, gaussian)
        self.assertEqual(projection.observation_count, 4)
        self.assertEqual(projection.scheduler.state, "queued")
        self.assertEqual(projection.scheduler.freshness, "stale")

    def test_no_evidence_unknown_is_distinct_from_known_absent(self) -> None:
        empty = observe.project_attempt_observations(self.store, attempt_id="attempt-1")
        self.assertIsNone(empty.scheduler)
        self.assertIsNone(empty.process)
        self.assertIsNone(empty.gaussian)
        absent = sample(state="absent")
        observe.record_attempt_observation(self.store, absent)
        projection = observe.project_attempt_observations(
            self.store, attempt_id="attempt-1"
        )
        self.assertEqual(projection.scheduler, absent)

    def test_explicit_unknown_can_be_fresh_or_stale(self) -> None:
        fresh = sample(source_identity="fresh-unknown", state="unknown")
        stale = sample(
            source_identity="stale-unknown",
            observed_at_utc="2026-08-22T00:00:01.000000Z",
            freshness="stale",
            state="unknown",
        )
        observe.record_attempt_observation(self.store, fresh)
        observe.record_attempt_observation(self.store, stale)
        projected = observe.project_attempt_observations(
            self.store, attempt_id="attempt-1"
        ).scheduler
        self.assertEqual(projected, stale)
        self.assertEqual(projected.state, "unknown")
        self.assertEqual(projected.freshness, "stale")

    def test_freshness_only_change_preserves_known_state(self) -> None:
        fresh = sample(source_identity="same-source", freshness="fresh")
        stale = sample(
            source_identity="same-source",
            observed_at_utc="2026-08-22T00:00:01.000000Z",
            freshness="stale",
        )
        self.assertNotEqual(fresh.observation_id, stale.observation_id)
        observe.record_attempt_observation(self.store, fresh)
        observe.record_attempt_observation(self.store, stale)
        projected = observe.project_attempt_observations(
            self.store, attempt_id="attempt-1"
        ).scheduler
        self.assertEqual(projected.state, "running")
        self.assertEqual(projected.freshness, "stale")

    def test_non_observe_records_are_ignored(self) -> None:
        self.store.append_observation(
            core.Observation(
                observation_id="other-1",
                attempt_id="attempt-1",
                observation_type="other-evidence",
                data={"state": "failed", "retry": True},
            )
        )
        observation = sample()
        observe.record_attempt_observation(self.store, observation)
        projection = observe.project_attempt_observations(
            self.store, attempt_id="attempt-1"
        )
        self.assertEqual(projection.observation_count, 1)
        self.assertEqual(projection.scheduler, observation)

    def test_terminal_absent_and_termination_remain_independent_evidence(self) -> None:
        scheduler = sample(state="terminal")
        process = sample(
            source_kind="process",
            source_identity="process-absent",
            state="absent",
        )
        gaussian = sample(
            source_kind="gaussian",
            source_identity="gaussian-termination",
            state="termination",
        )
        for item in (scheduler, process, gaussian):
            observe.record_attempt_observation(self.store, item)
        projection = observe.project_attempt_observations(
            self.store, attempt_id="attempt-1"
        )
        self.assertEqual(projection.scheduler.state, "terminal")
        self.assertEqual(projection.process.state, "absent")
        self.assertEqual(projection.gaussian.state, "termination")
        self.assertEqual(
            self.store.attempt_state("attempt-1"), core.AttemptState.PLANNED
        )
        self.assertEqual(self.store.results_for_attempt("attempt-1"), ())

    def test_malformed_old_or_latest_matching_record_fails_whole_projection(self) -> None:
        for malformed_first in (True, False):
            with self.subTest(malformed_first=malformed_first):
                with core.SQLiteRuntimeStore(":memory:") as store:
                    populate_core(store)
                    valid = sample()
                    malformed = core.Observation(
                        observation_id="malformed",
                        attempt_id="attempt-1",
                        observation_type=observe.OBSERVATION_TYPE,
                        data={
                            "source_kind": "scheduler",
                            "source_identity": "bad-source",
                            "observed_at_utc": "2026-08-22T00:00:00.000000Z",
                            "freshness": "fresh",
                            "state": "running",
                            "progress_position": None,
                            "extra": "not allowed",
                        },
                    )
                    records = (malformed, valid) if malformed_first else (valid, malformed)
                    for item in records:
                        if isinstance(item, observe.AttemptObservation):
                            observe.record_attempt_observation(store, item)
                        else:
                            store.append_observation(item)
                    with self.assertRaises(observe.ObserveBoundaryError):
                        observe.project_attempt_observations(store, attempt_id="attempt-1")

    def test_forged_and_cross_attempt_identity_fail_closed(self) -> None:
        original = sample(attempt_id="attempt-1")
        for outer_attempt in ("attempt-1", "attempt-2"):
            with self.subTest(outer_attempt=outer_attempt):
                with core.SQLiteRuntimeStore(":memory:") as store:
                    populate_core(store)
                    store.append_observation(
                        core.Observation(
                            observation_id=original.observation_id,
                            attempt_id=outer_attempt,
                            observation_type=observe.OBSERVATION_TYPE,
                            data={
                                "source_kind": original.source_kind,
                                "source_identity": original.source_identity,
                                "observed_at_utc": original.observed_at_utc,
                                "freshness": original.freshness,
                                "state": "queued" if outer_attempt == "attempt-1" else original.state,
                                "progress_position": None,
                            },
                        )
                    )
                    with self.assertRaises(observe.ObserveBoundaryError):
                        observe.project_attempt_observations(store, attempt_id=outer_attempt)

    def test_durable_reopen_preserves_projection_and_count(self) -> None:
        observation = sample()
        observe.record_attempt_observation(self.store, observation)
        first = observe.project_attempt_observations(self.store, attempt_id="attempt-1")
        self.store.close()
        self.store = core.SQLiteRuntimeStore(self.database)
        second = observe.project_attempt_observations(self.store, attempt_id="attempt-1")
        self.assertEqual(second, first)
        self.assertEqual(second.observation_count, 1)

    def test_observe_dependency_is_core_only_and_has_no_acquisition_calls(self) -> None:
        package = Path(observe.__file__).resolve().parent
        imported_roots: set[str] = set()
        forbidden_calls = {"open", "system", "run", "Popen", "socket", "qsub", "qdel"}
        calls: set[str] = set()
        for path in sorted(package.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported_roots.update(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported_roots.add(node.module)
                elif isinstance(node, ast.Call):
                    function = node.func
                    if isinstance(function, ast.Name):
                        calls.add(function.id)
                    elif isinstance(function, ast.Attribute):
                        calls.add(function.attr)
        self.assertFalse(
            any(
                name.startswith(
                    (
                        "auto_g16.execution",
                        "auto_g16.result",
                        "auto_g16.approval",
                        "auto_g16.workflow",
                        "auto_g16.scientific_validation",
                    )
                )
                for name in imported_roots
            )
        )
        self.assertTrue(any(name.startswith("auto_g16.core") for name in imported_roots))
        self.assertTrue(calls.isdisjoint(forbidden_calls))

        repository = package.parent
        for path in sorted(repository.rglob("*.py")):
            if package in path.parents:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            imported: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module)
            self.assertFalse(
                any(name.startswith("auto_g16.observe") for name in imported),
                path,
            )


if __name__ == "__main__":
    unittest.main()
