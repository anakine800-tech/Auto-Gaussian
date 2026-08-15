"""Local SQLite persistence and Attempt lifecycle for the clean runtime core."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from enum import Enum
import json
from pathlib import Path
import sqlite3
from typing import cast

from .models import (
    Attempt,
    Batch,
    CalculationPlan,
    CoreValidationError,
    Observation,
    Project,
    RecoveryProposal,
    ResourceSpec,
    Result,
    Task,
    WorkflowRun,
    _freeze_record,
    _require_text,
    _semantic_record_from_encoded,
)


SCHEMA_VERSION = 1


class RuntimeStoreError(Exception):
    """Base class for clean-core persistence failures."""


class RuntimeStoreSchemaError(RuntimeStoreError):
    """The database schema is absent, unknown, or internally inconsistent."""


class RecordNotFoundError(RuntimeStoreError):
    """A required immutable record does not exist."""


class RecordConflictError(RuntimeStoreError):
    """An immutable identity was reused with different content."""


class AttemptStateError(RuntimeStoreError):
    """An Attempt operation is invalid for its durable current state."""


class AttemptState(str, Enum):
    PLANNED = "PLANNED"
    SUBMISSION_INTENT_RECORDED = "SUBMISSION_INTENT_RECORDED"
    SUBMITTED = "SUBMITTED"
    UNKNOWN = "UNKNOWN"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    NOT_SUBMITTED = "NOT_SUBMITTED"


class SubmissionOutcome(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNKNOWN = "UNKNOWN"


class SubmissionIntentClaim(Enum):
    WINNER = "WINNER"
    REPLAY = "REPLAY"

    def __bool__(self) -> bool:
        raise TypeError("submission intent claims require an explicit WINNER comparison")


class ReconciliationResolution(str, Enum):
    UNRESOLVED = "UNRESOLVED"
    SUBMITTED = "SUBMITTED"
    NOT_SUBMITTED = "NOT_SUBMITTED"


_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE projects (
        project_id TEXT PRIMARY KEY
    )
    """,
    """
    CREATE TABLE workflow_runs (
        workflow_run_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(project_id),
        workflow_name TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE batches (
        batch_id TEXT PRIMARY KEY,
        workflow_run_id TEXT NOT NULL REFERENCES workflow_runs(workflow_run_id),
        purpose TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE tasks (
        task_id TEXT PRIMARY KEY,
        workflow_run_id TEXT NOT NULL REFERENCES workflow_runs(workflow_run_id),
        task_kind TEXT NOT NULL,
        batch_id TEXT REFERENCES batches(batch_id)
    )
    """,
    """
    CREATE TABLE calculation_plans (
        calculation_plan_id TEXT PRIMARY KEY,
        task_id TEXT NOT NULL REFERENCES tasks(task_id),
        revision INTEGER NOT NULL CHECK (revision > 0),
        intent TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE resource_specs (
        resource_spec_id TEXT PRIMARY KEY,
        task_id TEXT NOT NULL REFERENCES tasks(task_id),
        resources TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE attempts (
        attempt_id TEXT PRIMARY KEY,
        task_id TEXT NOT NULL REFERENCES tasks(task_id),
        ordinal INTEGER NOT NULL CHECK (ordinal > 0),
        parent_attempt_id TEXT REFERENCES attempts(attempt_id),
        state TEXT NOT NULL CHECK (state IN (
            'PLANNED', 'SUBMISSION_INTENT_RECORDED', 'SUBMITTED', 'UNKNOWN',
            'RUNNING', 'SUCCEEDED', 'FAILED', 'NOT_SUBMITTED'
        )),
        UNIQUE (task_id, ordinal)
    )
    """,
    """
    CREATE UNIQUE INDEX attempt_single_root_per_task
    ON attempts(task_id)
    WHERE parent_attempt_id IS NULL
    """,
    """
    CREATE TABLE submission_intents (
        attempt_id TEXT PRIMARY KEY REFERENCES attempts(attempt_id),
        intent_id TEXT NOT NULL,
        UNIQUE (intent_id),
        UNIQUE (attempt_id, intent_id)
    )
    """,
    """
    CREATE TABLE submission_outcomes (
        attempt_id TEXT PRIMARY KEY REFERENCES attempts(attempt_id),
        intent_id TEXT NOT NULL,
        outcome TEXT NOT NULL CHECK (outcome IN ('SUBMITTED', 'UNKNOWN')),
        FOREIGN KEY (attempt_id, intent_id)
            REFERENCES submission_intents(attempt_id, intent_id)
    )
    """,
    """
    CREATE TABLE observations (
        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
        observation_id TEXT NOT NULL UNIQUE,
        attempt_id TEXT NOT NULL REFERENCES attempts(attempt_id),
        observation_type TEXT NOT NULL,
        data TEXT NOT NULL,
        UNIQUE (observation_id, attempt_id)
    )
    """,
    """
    CREATE TABLE results (
        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
        result_id TEXT NOT NULL UNIQUE,
        attempt_id TEXT NOT NULL REFERENCES attempts(attempt_id),
        result_type TEXT NOT NULL,
        data TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE reconciliations (
        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
        attempt_id TEXT NOT NULL REFERENCES attempts(attempt_id),
        observation_id TEXT NOT NULL,
        resolution TEXT NOT NULL CHECK (resolution IN (
            'UNRESOLVED', 'SUBMITTED', 'NOT_SUBMITTED'
        )),
        UNIQUE (attempt_id, observation_id, resolution),
        FOREIGN KEY (observation_id, attempt_id)
            REFERENCES observations(observation_id, attempt_id)
    )
    """,
    """
    CREATE UNIQUE INDEX reconciliation_terminal_once
    ON reconciliations(attempt_id)
    WHERE resolution != 'UNRESOLVED'
    """,
    """
    CREATE TABLE recovery_proposals (
        recovery_proposal_id TEXT PRIMARY KEY,
        attempt_id TEXT NOT NULL REFERENCES attempts(attempt_id),
        reason TEXT NOT NULL,
        proposed_calculation_plan_id TEXT NOT NULL
    )
    """,
)


def _encode_payload(value: object) -> str:
    return json.dumps(
        _freeze_record(value, "payload"),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )


def _tupleize(value: object) -> object:
    if isinstance(value, list):
        return tuple(_tupleize(item) for item in value)
    return value


def _decode_payload(value: str, field_name: str) -> Mapping[str, object]:
    try:
        decoded = json.loads(value)
        return _semantic_record_from_encoded(_tupleize(decoded), field_name)
    except (json.JSONDecodeError, CoreValidationError) as exc:
        raise RuntimeStoreSchemaError(f"stored {field_name} payload is invalid") from exc


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _schema_identity(connection: sqlite3.Connection) -> tuple[object, ...]:
    objects = tuple(
        tuple(row)
        for row in connection.execute(
            """
            SELECT type, name, tbl_name, sql
            FROM sqlite_master
            WHERE name NOT GLOB 'sqlite_*'
            ORDER BY type, name
            """
        )
    )
    table_names = sorted(row[1] for row in objects if row[0] == "table")
    tables: list[object] = []
    for table_name in table_names:
        quoted_table = _quote_identifier(cast(str, table_name))
        columns = tuple(
            tuple(row)
            for row in connection.execute(f"PRAGMA table_xinfo({quoted_table})")
        )
        foreign_keys = tuple(
            tuple(row)
            for row in connection.execute(f"PRAGMA foreign_key_list({quoted_table})")
        )
        indexes = tuple(
            tuple(row)
            for row in connection.execute(f"PRAGMA index_list({quoted_table})")
        )
        index_columns = tuple(
            (
                index[1],
                tuple(
                    tuple(row)
                    for row in connection.execute(
                        f"PRAGMA index_xinfo({_quote_identifier(cast(str, index[1]))})"
                    )
                ),
            )
            for index in indexes
        )
        tables.append(
            (table_name, columns, foreign_keys, indexes, index_columns)
        )
    return (objects, tuple(tables))


def _expected_schema_identity() -> tuple[object, ...]:
    reference = sqlite3.connect(":memory:", isolation_level=None)
    try:
        reference.execute("PRAGMA foreign_keys = ON")
        for statement in _SCHEMA_STATEMENTS:
            reference.execute(statement)
        return _schema_identity(reference)
    finally:
        reference.close()


class SQLiteRuntimeStore:
    """Versioned local runtime store with explicit, fail-closed transactions."""

    def __init__(self, database: str | Path = ":memory:") -> None:
        self._closed = False
        try:
            self._connection = sqlite3.connect(str(database), isolation_level=None)
            self._connection.row_factory = sqlite3.Row
            self._connection.execute("PRAGMA foreign_keys = ON")
            if self._connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
                raise RuntimeStoreSchemaError("SQLite foreign keys could not be enabled")
            self._initialize_schema()
        except Exception:
            connection = getattr(self, "_connection", None)
            if connection is not None:
                connection.close()
            self._closed = True
            raise

    def __enter__(self) -> SQLiteRuntimeStore:
        self._db()
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        self.close()

    def close(self) -> None:
        if not self._closed:
            self._connection.close()
            self._closed = True

    def _db(self) -> sqlite3.Connection:
        if self._closed:
            raise RuntimeStoreError("runtime store is closed")
        return self._connection

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._db()
        connection.execute("BEGIN IMMEDIATE")
        try:
            yield connection
            connection.execute("COMMIT")
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise

    def _initialize_schema(self) -> None:
        connection = self._db()
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        objects = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE name NOT GLOB 'sqlite_*'"
            )
        }
        if version == 0:
            if objects:
                raise RuntimeStoreSchemaError(
                    "refusing to initialize an unversioned database containing objects"
                )
            with self._transaction() as transaction:
                for statement in _SCHEMA_STATEMENTS:
                    transaction.execute(statement)
                transaction.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        elif version != SCHEMA_VERSION:
            raise RuntimeStoreSchemaError(
                f"unsupported runtime store schema version {version}; expected {SCHEMA_VERSION}"
            )
        try:
            identity_matches = (
                _schema_identity(connection) == _expected_schema_identity()
            )
        except sqlite3.DatabaseError as exc:
            raise RuntimeStoreSchemaError(
                "runtime store schema identity could not be validated"
            ) from exc
        if not identity_matches:
            raise RuntimeStoreSchemaError(
                "runtime store schema identity does not match the version 1 contract"
            )

    def _store_row(
        self,
        connection: sqlite3.Connection,
        table: str,
        identity_column: str,
        columns: tuple[str, ...],
        values: tuple[object, ...],
    ) -> None:
        placeholders = ", ".join("?" for _item in values)
        try:
            connection.execute(
                f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})",
                values,
            )
            return
        except sqlite3.IntegrityError as exc:
            existing = connection.execute(
                f"SELECT {', '.join(columns)} FROM {table} WHERE {identity_column} = ?",
                (values[0],),
            ).fetchone()
            if existing is not None and tuple(existing) == values:
                return
            if existing is not None:
                raise RecordConflictError(
                    f"{table} identity {values[0]!r} already has different content"
                ) from exc
            raise RecordConflictError(f"{table} record violates a store relation") from exc

    def _load_row(
        self,
        table: str,
        identity_column: str,
        columns: tuple[str, ...],
        identity: str,
    ) -> sqlite3.Row:
        row = self._db().execute(
            f"SELECT {', '.join(columns)} FROM {table} WHERE {identity_column} = ?",
            (identity,),
        ).fetchone()
        if row is None:
            raise RecordNotFoundError(f"{table} record {identity!r} was not found")
        return cast(sqlite3.Row, row)

    def store_project(self, record: Project) -> None:
        with self._transaction() as connection:
            self._store_row(
                connection,
                "projects",
                "project_id",
                ("project_id",),
                (record.project_id,),
            )

    def load_project(self, project_id: str) -> Project:
        row = self._load_row("projects", "project_id", ("project_id",), project_id)
        return Project(project_id=row[0])

    def store_workflow_run(self, record: WorkflowRun) -> None:
        columns = ("workflow_run_id", "project_id", "workflow_name")
        values = (record.workflow_run_id, record.project_id, record.workflow_name)
        with self._transaction() as connection:
            self._store_row(connection, "workflow_runs", "workflow_run_id", columns, values)

    def load_workflow_run(self, workflow_run_id: str) -> WorkflowRun:
        columns = ("workflow_run_id", "project_id", "workflow_name")
        row = self._load_row("workflow_runs", "workflow_run_id", columns, workflow_run_id)
        return WorkflowRun(workflow_run_id=row[0], project_id=row[1], workflow_name=row[2])

    def store_batch(self, record: Batch) -> None:
        columns = ("batch_id", "workflow_run_id", "purpose")
        values = (record.batch_id, record.workflow_run_id, record.purpose)
        with self._transaction() as connection:
            self._store_row(connection, "batches", "batch_id", columns, values)

    def load_batch(self, batch_id: str) -> Batch:
        columns = ("batch_id", "workflow_run_id", "purpose")
        row = self._load_row("batches", "batch_id", columns, batch_id)
        return Batch(batch_id=row[0], workflow_run_id=row[1], purpose=row[2])

    def store_task(self, record: Task) -> None:
        columns = ("task_id", "workflow_run_id", "task_kind", "batch_id")
        values = (record.task_id, record.workflow_run_id, record.task_kind, record.batch_id)
        with self._transaction() as connection:
            if record.batch_id is not None:
                batch = connection.execute(
                    "SELECT workflow_run_id FROM batches WHERE batch_id = ?",
                    (record.batch_id,),
                ).fetchone()
                if batch is None:
                    raise RecordNotFoundError(f"batch {record.batch_id!r} was not found")
                if batch[0] != record.workflow_run_id:
                    raise RecordConflictError("task and batch must belong to the same WorkflowRun")
            self._store_row(connection, "tasks", "task_id", columns, values)

    def load_task(self, task_id: str) -> Task:
        columns = ("task_id", "workflow_run_id", "task_kind", "batch_id")
        row = self._load_row("tasks", "task_id", columns, task_id)
        return Task(task_id=row[0], workflow_run_id=row[1], task_kind=row[2], batch_id=row[3])

    def store_calculation_plan(self, record: CalculationPlan) -> None:
        columns = ("calculation_plan_id", "task_id", "revision", "intent")
        values = (
            record.calculation_plan_id,
            record.task_id,
            record.revision,
            _encode_payload(record.intent),
        )
        with self._transaction() as connection:
            self._store_row(
                connection,
                "calculation_plans",
                "calculation_plan_id",
                columns,
                values,
            )

    def load_calculation_plan(self, calculation_plan_id: str) -> CalculationPlan:
        columns = ("calculation_plan_id", "task_id", "revision", "intent")
        row = self._load_row(
            "calculation_plans", "calculation_plan_id", columns, calculation_plan_id
        )
        return CalculationPlan(
            calculation_plan_id=row[0],
            task_id=row[1],
            revision=row[2],
            intent=_decode_payload(row[3], "intent"),
        )

    def store_resource_spec(self, record: ResourceSpec) -> None:
        columns = ("resource_spec_id", "task_id", "resources")
        values = (record.resource_spec_id, record.task_id, _encode_payload(record.resources))
        with self._transaction() as connection:
            self._store_row(
                connection, "resource_specs", "resource_spec_id", columns, values
            )

    def load_resource_spec(self, resource_spec_id: str) -> ResourceSpec:
        columns = ("resource_spec_id", "task_id", "resources")
        row = self._load_row("resource_specs", "resource_spec_id", columns, resource_spec_id)
        return ResourceSpec(
            resource_spec_id=row[0],
            task_id=row[1],
            resources=_decode_payload(row[2], "resources"),
        )

    def create_attempt(self, record: Attempt) -> None:
        with self._transaction() as connection:
            self._insert_attempt(connection, record, parent_attempt_id=None)

    def _insert_attempt(
        self,
        connection: sqlite3.Connection,
        record: Attempt,
        *,
        parent_attempt_id: str | None,
    ) -> None:
        existing = connection.execute(
            "SELECT task_id, ordinal, parent_attempt_id FROM attempts WHERE attempt_id = ?",
            (record.attempt_id,),
        ).fetchone()
        immutable = (record.task_id, record.ordinal, parent_attempt_id)
        if existing is not None:
            if tuple(existing) == immutable:
                return
            raise RecordConflictError(
                f"Attempt identity {record.attempt_id!r} already has different content"
            )
        try:
            connection.execute(
                """
                INSERT INTO attempts (attempt_id, task_id, ordinal, parent_attempt_id, state)
                VALUES (?, ?, ?, ?, ?)
                """,
                (*((record.attempt_id,) + immutable), AttemptState.PLANNED.value),
            )
        except sqlite3.IntegrityError as exc:
            raise RecordConflictError(
                "Attempt violates task, parent, or ordinal constraints"
            ) from exc

    def load_attempt(self, attempt_id: str) -> Attempt:
        row = self._load_row(
            "attempts", "attempt_id", ("attempt_id", "task_id", "ordinal"), attempt_id
        )
        return Attempt(attempt_id=row[0], task_id=row[1], ordinal=row[2])

    def attempt_state(self, attempt_id: str) -> AttemptState:
        row = self._load_row("attempts", "attempt_id", ("state",), attempt_id)
        return AttemptState(row[0])

    def parent_attempt_id(self, attempt_id: str) -> str | None:
        row = self._load_row("attempts", "attempt_id", ("parent_attempt_id",), attempt_id)
        return cast(str | None, row[0])

    def create_child_attempt(self, parent_attempt_id: str, child: Attempt) -> None:
        _require_text(parent_attempt_id, "parent_attempt_id")
        with self._transaction() as connection:
            existing = connection.execute(
                "SELECT task_id, ordinal, parent_attempt_id FROM attempts WHERE attempt_id = ?",
                (child.attempt_id,),
            ).fetchone()
            immutable = (child.task_id, child.ordinal, parent_attempt_id)
            if existing is not None:
                if tuple(existing) == immutable:
                    return
                raise RecordConflictError(
                    f"Attempt identity {child.attempt_id!r} already has different content"
                )
            parent = connection.execute(
                "SELECT task_id, ordinal, state FROM attempts WHERE attempt_id = ?",
                (parent_attempt_id,),
            ).fetchone()
            if parent is None:
                raise RecordNotFoundError(f"parent Attempt {parent_attempt_id!r} was not found")
            parent_state = AttemptState(parent[2])
            if parent_state not in {AttemptState.FAILED, AttemptState.NOT_SUBMITTED}:
                raise AttemptStateError(
                    "child Attempt requires FAILED or NOT_SUBMITTED parent, got "
                    f"{parent_state.value}"
                )
            if child.task_id != parent[0]:
                raise RecordConflictError("child Attempt must preserve the parent task_id")
            if child.ordinal <= parent[1]:
                raise RecordConflictError("child Attempt ordinal must be greater than its parent")
            self._insert_attempt(connection, child, parent_attempt_id=parent_attempt_id)

    def record_submission_intent(
        self, attempt_id: str, intent_id: str
    ) -> SubmissionIntentClaim:
        _require_text(intent_id, "intent_id")
        with self._transaction() as connection:
            attempt = self._attempt_row(connection, attempt_id)
            existing = connection.execute(
                "SELECT intent_id FROM submission_intents WHERE attempt_id = ?",
                (attempt_id,),
            ).fetchone()
            if existing is not None:
                if existing[0] == intent_id:
                    return SubmissionIntentClaim.REPLAY
                raise RecordConflictError("Attempt already has a different submission intent")
            owner = connection.execute(
                "SELECT attempt_id FROM submission_intents WHERE intent_id = ?",
                (intent_id,),
            ).fetchone()
            if owner is not None:
                raise RecordConflictError("submission intent identity belongs to another Attempt")
            state = AttemptState(attempt["state"])
            if state is not AttemptState.PLANNED:
                raise AttemptStateError(
                    f"submission intent requires PLANNED, got {state.value}"
                )
            try:
                connection.execute(
                    "INSERT INTO submission_intents (attempt_id, intent_id) VALUES (?, ?)",
                    (attempt_id, intent_id),
                )
            except sqlite3.IntegrityError as exc:
                raise RecordConflictError("submission intent violates a store relation") from exc
            connection.execute(
                "UPDATE attempts SET state = ? WHERE attempt_id = ?",
                (AttemptState.SUBMISSION_INTENT_RECORDED.value, attempt_id),
            )
            return SubmissionIntentClaim.WINNER

    def record_submission_outcome(
        self,
        attempt_id: str,
        intent_id: str,
        outcome: SubmissionOutcome,
    ) -> AttemptState:
        _require_text(intent_id, "intent_id")
        if not isinstance(outcome, SubmissionOutcome):
            raise AttemptStateError("outcome must be a SubmissionOutcome")
        with self._transaction() as connection:
            attempt = self._attempt_row(connection, attempt_id)
            intent = connection.execute(
                "SELECT intent_id FROM submission_intents WHERE attempt_id = ?",
                (attempt_id,),
            ).fetchone()
            if intent is None or intent[0] != intent_id:
                raise RecordConflictError("submission outcome does not match the recorded intent")
            existing = connection.execute(
                "SELECT intent_id, outcome FROM submission_outcomes WHERE attempt_id = ?",
                (attempt_id,),
            ).fetchone()
            if existing is not None:
                if tuple(existing) == (intent_id, outcome.value):
                    return AttemptState(attempt["state"])
                raise RecordConflictError("Attempt already has a different submission outcome")
            state = AttemptState(attempt["state"])
            if state is not AttemptState.SUBMISSION_INTENT_RECORDED:
                raise AttemptStateError(
                    "submission outcome requires SUBMISSION_INTENT_RECORDED, "
                    f"got {state.value}"
                )
            connection.execute(
                """
                INSERT INTO submission_outcomes (attempt_id, intent_id, outcome)
                VALUES (?, ?, ?)
                """,
                (attempt_id, intent_id, outcome.value),
            )
            next_state = AttemptState(outcome.value)
            connection.execute(
                "UPDATE attempts SET state = ? WHERE attempt_id = ?",
                (next_state.value, attempt_id),
            )
            return next_state

    def advance_attempt(self, attempt_id: str, new_state: AttemptState) -> AttemptState:
        allowed = {
            AttemptState.SUBMITTED: {
                AttemptState.RUNNING,
                AttemptState.SUCCEEDED,
                AttemptState.FAILED,
            },
            AttemptState.RUNNING: {AttemptState.SUCCEEDED, AttemptState.FAILED},
        }
        if not isinstance(new_state, AttemptState) or new_state not in {
            AttemptState.RUNNING,
            AttemptState.SUCCEEDED,
            AttemptState.FAILED,
        }:
            raise AttemptStateError("advance_attempt accepts only RUNNING, SUCCEEDED, or FAILED")
        with self._transaction() as connection:
            current = AttemptState(self._attempt_row(connection, attempt_id)["state"])
            if current is new_state:
                return current
            if new_state not in allowed.get(current, set()):
                raise AttemptStateError(
                    f"invalid Attempt transition {current.value} -> {new_state.value}"
                )
            connection.execute(
                "UPDATE attempts SET state = ? WHERE attempt_id = ?",
                (new_state.value, attempt_id),
            )
            return new_state

    def reconcile_unknown(
        self,
        attempt_id: str,
        observation_id: str,
        resolution: ReconciliationResolution,
    ) -> AttemptState:
        if not isinstance(resolution, ReconciliationResolution):
            raise AttemptStateError("resolution must be a ReconciliationResolution")
        with self._transaction() as connection:
            current = AttemptState(self._attempt_row(connection, attempt_id)["state"])
            observation = connection.execute(
                "SELECT attempt_id FROM observations WHERE observation_id = ?",
                (observation_id,),
            ).fetchone()
            if observation is None:
                raise RecordNotFoundError(f"Observation {observation_id!r} was not found")
            if observation[0] != attempt_id:
                raise RecordConflictError("reconciliation Observation belongs to another Attempt")
            terminal = connection.execute(
                """
                SELECT observation_id, resolution FROM reconciliations
                WHERE attempt_id = ? AND resolution != 'UNRESOLVED'
                """,
                (attempt_id,),
            ).fetchone()
            if terminal is not None:
                expected = (observation_id, resolution.value)
                if tuple(terminal) == expected:
                    return current
                raise RecordConflictError("Attempt already has a terminal reconciliation")
            if current is not AttemptState.UNKNOWN:
                raise AttemptStateError(f"reconciliation requires UNKNOWN, got {current.value}")
            if resolution is ReconciliationResolution.UNRESOLVED:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO reconciliations
                        (attempt_id, observation_id, resolution)
                    VALUES (?, ?, ?)
                    """,
                    (attempt_id, observation_id, resolution.value),
                )
                return AttemptState.UNKNOWN
            try:
                connection.execute(
                    """
                    INSERT INTO reconciliations (attempt_id, observation_id, resolution)
                    VALUES (?, ?, ?)
                    """,
                    (attempt_id, observation_id, resolution.value),
                )
            except sqlite3.IntegrityError as exc:
                raise RecordConflictError("terminal reconciliation conflicts") from exc
            next_state = AttemptState(resolution.value)
            connection.execute(
                "UPDATE attempts SET state = ? WHERE attempt_id = ?",
                (next_state.value, attempt_id),
            )
            return next_state

    def store_recovery_proposal(self, record: RecoveryProposal) -> None:
        columns = (
            "recovery_proposal_id",
            "attempt_id",
            "reason",
            "proposed_calculation_plan_id",
        )
        values = (
            record.recovery_proposal_id,
            record.attempt_id,
            record.reason,
            record.proposed_calculation_plan_id,
        )
        with self._transaction() as connection:
            self._store_row(
                connection,
                "recovery_proposals",
                "recovery_proposal_id",
                columns,
                values,
            )

    def load_recovery_proposal(self, recovery_proposal_id: str) -> RecoveryProposal:
        columns = (
            "recovery_proposal_id",
            "attempt_id",
            "reason",
            "proposed_calculation_plan_id",
        )
        row = self._load_row(
            "recovery_proposals", "recovery_proposal_id", columns, recovery_proposal_id
        )
        return RecoveryProposal(
            recovery_proposal_id=row[0],
            attempt_id=row[1],
            reason=row[2],
            proposed_calculation_plan_id=row[3],
        )

    def append_observation(self, record: Observation) -> None:
        columns = ("observation_id", "attempt_id", "observation_type", "data")
        values = (
            record.observation_id,
            record.attempt_id,
            record.observation_type,
            _encode_payload(record.data),
        )
        with self._transaction() as connection:
            self._store_row(
                connection, "observations", "observation_id", columns, values
            )

    def observations_for_attempt(self, attempt_id: str) -> tuple[Observation, ...]:
        self._load_row("attempts", "attempt_id", ("attempt_id",), attempt_id)
        rows = self._db().execute(
            """
            SELECT observation_id, attempt_id, observation_type, data
            FROM observations WHERE attempt_id = ? ORDER BY sequence
            """,
            (attempt_id,),
        )
        return tuple(
            Observation(
                observation_id=row[0],
                attempt_id=row[1],
                observation_type=row[2],
                data=_decode_payload(row[3], "observation data"),
            )
            for row in rows
        )

    def append_result(self, record: Result) -> None:
        columns = ("result_id", "attempt_id", "result_type", "data")
        values = (
            record.result_id,
            record.attempt_id,
            record.result_type,
            _encode_payload(record.data),
        )
        with self._transaction() as connection:
            self._store_row(connection, "results", "result_id", columns, values)

    def results_for_attempt(self, attempt_id: str) -> tuple[Result, ...]:
        self._load_row("attempts", "attempt_id", ("attempt_id",), attempt_id)
        rows = self._db().execute(
            """
            SELECT result_id, attempt_id, result_type, data
            FROM results WHERE attempt_id = ? ORDER BY sequence
            """,
            (attempt_id,),
        )
        return tuple(
            Result(
                result_id=row[0],
                attempt_id=row[1],
                result_type=row[2],
                data=_decode_payload(row[3], "result data"),
            )
            for row in rows
        )

    def _attempt_row(self, connection: sqlite3.Connection, attempt_id: str) -> sqlite3.Row:
        row = connection.execute(
            """
            SELECT attempt_id, task_id, ordinal, parent_attempt_id, state
            FROM attempts WHERE attempt_id = ?
            """,
            (attempt_id,),
        ).fetchone()
        if row is None:
            raise RecordNotFoundError(f"Attempt {attempt_id!r} was not found")
        return cast(sqlite3.Row, row)
