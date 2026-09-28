"""Finite local queries; no SQL, effect owner, raw artifact reader or cache."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
import sqlite3

from auto_g16.core import (
    AttemptState, CoreValidationError, RecordNotFoundError, RuntimeStoreError, SQLiteRuntimeStore,
)
from auto_g16.observe import OBSERVATION_TYPE, ObserveBoundaryError, project_attempt_observations
from auto_g16.result import (
    INPUT_BINDING_OBSERVATION, OUTPUT_ENVELOPE_OBSERVATION, PARSED_RESULT_TYPE,
    ResultProvenanceService,
)

from .models import QUERY_SCHEMA, FieldDTO, QueryDTO, QueryError


def _plain(value: object) -> object:
    if value is None or type(value) in (str, int, float, bool):
        return value
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    raise QueryError("invalid-evidence")


def _field(value: object, source: str) -> FieldDTO:
    return {"availability": "available", "value": _plain(value), "source": source, "reason": None}


def _missing(reason: str, *, unavailable: bool = False) -> FieldDTO:
    return {"availability": "unavailable" if unavailable else "missing",
            "value": None, "source": None, "reason": reason}


def _id(value: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise QueryError("invalid-id")
    return value


def _result_view(store: SQLiteRuntimeStore, attempt_id: str):
    store.load_attempt(attempt_id)
    try:
        return ResultProvenanceService(store).current_view(attempt_id)
    except RecordNotFoundError:
        # The requested Attempt exists; missing referenced evidence is corruption,
        # not a missing HTTP resource.
        raise QueryError("invalid-evidence") from None


def _coverage(store: SQLiteRuntimeStore, attempt_id: str) -> dict[str, object]:
    """Inventory type/ID only; never interpret unowned payloads or guess a program."""
    observations = store.observations_for_attempt(attempt_id)
    results = store.results_for_attempt(attempt_id)
    supported_observations = (INPUT_BINDING_OBSERVATION, OUTPUT_ENVELOPE_OBSERVATION, OBSERVATION_TYPE)
    unprojected_observations = [
        {"observation_id": item.observation_id, "observation_type": item.observation_type}
        for item in observations if item.observation_type not in supported_observations]
    unprojected_results = [{"result_id": item.result_id, "result_type": item.result_type}
                          for item in results if item.result_type != PARSED_RESULT_TYPE]
    return {"scope": "persisted-core-evidence-protocols",
            "status": "unsupported-protocols-present" if unprojected_observations or unprojected_results
                      else "recognized-protocols-only",
            "supported_observation_types": list(supported_observations),
            "supported_result_types": [PARSED_RESULT_TYPE],
            "unprojected_observations": unprojected_observations,
            "unprojected_results": unprojected_results}


class QueryService:
    """Each call opens/closes a verified Core snapshot; construction performs no I/O.

    Supply a server-configured canonical absolute database path, never a URL
    parameter. Results contain only detached JSON values. They carry no effects
    or approvals and are returned only after the snapshot's final safety check.
    """

    def __init__(self, database: str | Path) -> None:
        self.database = database

    def _read(self, kind: str, operation: Callable[[SQLiteRuntimeStore], dict[str, object]]) -> QueryDTO:
        try:
            with SQLiteRuntimeStore.read_snapshot(self.database) as store:
                data = operation(store)
            return {"schema": QUERY_SCHEMA, "kind": kind, "data": data}
        except QueryError:
            raise
        except RecordNotFoundError:
            raise QueryError("not-found") from None
        except (RuntimeStoreError, sqlite3.Error, OSError):
            raise QueryError("store-unavailable") from None
        except (CoreValidationError, ObserveBoundaryError, ValueError, TypeError, KeyError):
            raise QueryError("invalid-evidence") from None

    @staticmethod
    def _project(store: SQLiteRuntimeStore, project_id: str) -> dict[str, object]:
        project = store.load_project(project_id)
        runs = store.list_workflow_runs(project_id)
        tasks = [task for run in runs for task in store.list_tasks(run.workflow_run_id)]
        counts = {state.value: 0 for state in AttemptState}
        for task in tasks:
            for attempt in store.list_attempts(task.task_id):
                counts[store.attempt_state(attempt.attempt_id).value] += 1
        return {"project_id": project.project_id,
                "name": _missing("not-recorded-by-core"),
                "created_at": _missing("not-recorded-by-core"),
                "last_activity_at": _missing("no-authoritative-project-activity-clock"),
                "workflow_run_ids": [run.workflow_run_id for run in runs],
                "task_count": len(tasks),
                "attempt_summary": {"scope": "all-persisted-attempts", "source": "Core.attempt_state",
                                    "total": sum(counts.values()), "state_counts": counts},
                "current_task_state": _missing("no-canonical-current-task-attempt-selection", unavailable=True)}

    @staticmethod
    def _task(store: SQLiteRuntimeStore, task_id: str) -> dict[str, object]:
        task = store.load_task(task_id)
        run = store.load_workflow_run(task.workflow_run_id)
        store.load_project(run.project_id)
        return {"task_id": task.task_id, "workflow_run_id": run.workflow_run_id,
                "project_id": run.project_id, "workflow_name": run.workflow_name,
                "task_kind": task.task_kind, "batch_id": task.batch_id,
                "attempt_ids": [attempt.attempt_id for attempt in store.list_attempts(task_id)]}

    @staticmethod
    def _tasks(store: SQLiteRuntimeStore, project_id: str) -> list[dict[str, object]]:
        return [QueryService._task(store, task.task_id)
                for run in store.list_workflow_runs(project_id)
                for task in store.list_tasks(run.workflow_run_id)]

    def list_projects(self) -> QueryDTO:
        return self._read("projects", lambda store: {"items": [
            self._project(store, project.project_id) for project in store.list_projects()]})

    def get_project(self, project_id: str) -> QueryDTO:
        _id(project_id)
        return self._read("project", lambda store: self._project(store, project_id))

    def list_tasks(self, project_id: str) -> QueryDTO:
        _id(project_id)
        return self._read("tasks", lambda store: {"items": self._tasks(store, project_id)})

    def get_task(self, task_id: str) -> QueryDTO:
        _id(task_id)
        return self._read("task", lambda store: self._task(store, task_id))

    def list_attempts(self, *, project_id: str | None = None, task_id: str | None = None) -> QueryDTO:
        if (project_id is None) == (task_id is None):
            raise QueryError("exactly-one-parent-required")
        _id(project_id if project_id is not None else task_id)

        def operation(store: SQLiteRuntimeStore) -> dict[str, object]:
            task_ids = ([task_id] if task_id is not None else [
                item["task_id"] for item in self._tasks(store, project_id)])
            return {"items": [self._attempt(store, attempt.attempt_id)
                              for identity in task_ids for attempt in store.list_attempts(identity)]}
        return self._read("attempts", operation)

    @staticmethod
    def _observation(store: SQLiteRuntimeStore, attempt_id: str) -> dict[str, object]:
        projection = project_attempt_observations(store, attempt_id=attempt_id)
        axes: dict[str, object] = {}
        for axis in ("scheduler", "process", "gaussian"):
            record = getattr(projection, axis)
            axes[axis] = _missing("no-persisted-observe-sample") if record is None else _field({
                "observation_id": record.observation_id, "source_identity": record.source_identity,
                "observed_at_utc": record.observed_at_utc, "freshness": record.freshness,
                "state": record.state, "progress_position": record.progress_position,
            }, "Observe.project_attempt_observations")
        return {"attempt_id": attempt_id, "scope": "observe-records-only",
                "observation_count": projection.observation_count, **axes}

    @staticmethod
    def _result(store: SQLiteRuntimeStore, attempt_id: str) -> dict[str, object]:
        view = _result_view(store, attempt_id)
        binding = view.input_binding
        coverage = _coverage(store, attempt_id)
        unsupported = coverage["status"] == "unsupported-protocols-present"
        supported = {"scope": "result-provenance-records-only", "state": view.state.value, "incomplete": view.incomplete,
                "selection_reason": view.selection_reason,
                "input_binding": None if binding is None else {
                    "observation_id": binding.observation_id, **_plain(binding.payload())},
                "selected_envelope_id": view.selected_envelope_id,
                "selected_result_ids": [item.result_id for item in view.selected_results],
                "envelopes": [{"observation_id": item.observation_id, **_plain(item.payload())}
                              for item in view.envelopes],
                "results": [{"result_id": item.result_id, **_plain(item.payload())} for item in view.results]}
        return {"attempt_id": attempt_id, "coverage": coverage,
                "state": "unavailable" if unsupported else view.state.value,
                "incomplete": None if unsupported else view.incomplete,
                "selection_reason": "unsupported-evidence-protocol" if unsupported else view.selection_reason,
                "supported_projection": supported,
                "record_inventory": [{"result_id": item.result_id, "result_type": item.result_type}
                                     for item in store.results_for_attempt(attempt_id)],
                "validation": _missing("validation-store-readonly-interface-unavailable", unavailable=True),
                "scientific_acceptance": _missing("validation-store-readonly-interface-unavailable", unavailable=True)}

    @staticmethod
    def _attempt(store: SQLiteRuntimeStore, attempt_id: str) -> dict[str, object]:
        attempt = store.load_attempt(attempt_id)
        task = QueryService._task(store, attempt.task_id)
        view = _result_view(store, attempt_id)
        coverage = _coverage(store, attempt_id)
        unsupported = coverage["status"] == "unsupported-protocols-present"
        binding = view.input_binding
        metadata: dict[str, object] = {}
        for key in ("program", "method", "basis", "charge", "multiplicity"):
            metadata[key] = _missing("no-exact-attempt-input-binding")
        plan_reference = None
        if binding is not None:
            plan = store.load_calculation_plan(binding.calculation_plan_id)
            plan_reference = {"calculation_plan_id": plan.calculation_plan_id, "revision": plan.revision,
                              "input_binding_observation_id": binding.observation_id}
            for key in metadata:
                if key not in plan.intent:
                    metadata[key] = _missing("field-not-declared-in-bound-plan")
                    continue
                value = plan.intent[key]
                valid = (type(value) is int if key in ("charge", "multiplicity") else
                         isinstance(value, str) and bool(value.strip()))
                if key == "multiplicity" and valid:
                    valid = value > 0
                metadata[key] = (_field(value, f"CalculationPlan:{plan.calculation_plan_id}@{plan.revision}/intent/{key}")
                                 if valid else _missing("unsupported-declared-field-shape", unavailable=True))
        selected = next((item for item in view.envelopes if item.observation_id == view.selected_envelope_id), None)
        if unsupported:
            metadata = {key: _missing("unsupported-evidence-protocol", unavailable=True) for key in metadata}
        return {"attempt_id": attempt_id, "task_id": attempt.task_id,
                "workflow_run_id": task["workflow_run_id"], "project_id": task["project_id"],
                "ordinal": attempt.ordinal, "parent_attempt_id": store.parent_attempt_id(attempt_id),
                "execution_state": store.attempt_state(attempt_id).value,
                "coverage": coverage,
                "effect": _missing("execution-receipt-reader-not-connected", unavailable=True),
                "bound_plan": plan_reference, "declared_science": metadata,
                "input": _missing("unsupported-evidence-protocol", unavailable=True) if unsupported else
                _missing("no-exact-attempt-input-binding") if binding is None else _field({
                    "observation_id": binding.observation_id, "format": binding.input_format,
                    "logical_name": binding.logical_name, "sha256": binding.sha256,
                    "size_bytes": binding.size_bytes, "execution_snapshot_id": binding.execution_snapshot_id,
                }, "Result.InputBinding"),
                "resources": _missing("attempt-snapshot-reader-not-connected", unavailable=True),
                "job": _missing("execution-receipt-reader-not-connected", unavailable=True),
                "observation": QueryService._observation(store, attempt_id),
                "collection": _missing("unsupported-evidence-protocol", unavailable=True) if unsupported else
                _missing("no-persisted-output-envelope") if selected is None else _field({
                    "envelope_observation_id": selected.observation_id,
                    "capture_status": selected.capture_status.value,
                    "capture_completeness": selected.capture_completeness.value,
                }, "Result.current_view"),
                "result_state": "unavailable" if unsupported else view.state.value,
                "validation": _missing("validation-store-readonly-interface-unavailable", unavailable=True),
                "review": _missing("validation-store-readonly-interface-unavailable", unavailable=True),
                "logs_availability": _missing("unsupported-evidence-protocol", unavailable=True) if unsupported else
                _field({"scope": "result-provenance-envelope-references-only"}, "Result.current_view"),
                "logs": [{"envelope_observation_id": envelope.observation_id,
                          "artifact_kind": artifact.artifact_kind, "logical_name": artifact.logical_name,
                          "sha256": artifact.sha256, "size_bytes": artifact.size_bytes,
                          "content": _missing("artifact-content-access-not-enabled", unavailable=True)}
                         for envelope in view.envelopes for artifact in envelope.artifacts
                         if artifact.artifact_kind in ("gaussian-log", "stdout", "stderr")]}

    def get_attempt(self, attempt_id: str) -> QueryDTO:
        _id(attempt_id)
        return self._read("attempt", lambda store: self._attempt(store, attempt_id))

    def get_attempt_observation(self, attempt_id: str) -> QueryDTO:
        _id(attempt_id)
        return self._read("attempt-observation", lambda store: self._observation(store, attempt_id))

    def get_attempt_result(self, attempt_id: str) -> QueryDTO:
        _id(attempt_id)
        return self._read("attempt-result", lambda store: self._result(store, attempt_id))

    def get_review_bundle(self, attempt_id: str) -> QueryDTO:
        _id(attempt_id)

        def operation(store: SQLiteRuntimeStore) -> dict[str, object]:
            result = self._result(store, attempt_id)
            supported = result["supported_projection"]
            return {"attempt_id": attempt_id, "coverage": result["coverage"],
                    "selection_scope": "result-provenance-records-only",
                    "selected_envelope_id": supported["selected_envelope_id"],
                    "selected_result_ids": supported["selected_result_ids"],
                    "bundle": _missing("validation-store-readonly-interface-unavailable", unavailable=True)}
        return self._read("review-bundle", operation)
