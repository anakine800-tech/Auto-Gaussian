"""Exact append-only SQLite v1 persistence for Workflow authority records."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3
import stat
from typing import cast

from auto_g16.core import AttemptState

from ._validation import validate_definition_structure
from .models import (
    Condition,
    ConditionDecision,
    Edge,
    HumanGate,
    HumanGateDecision,
    Map,
    Node,
    WorkflowDefinition,
    WorkflowValueError,
    _payload_text,
)


_APPLICATION_ID = 0x41334757
_USER_VERSION = 1
_SCHEMA_STATEMENTS = (
    """CREATE TABLE workflow_definitions (
        workflow_definition_id TEXT PRIMARY KEY,
        payload_json TEXT NOT NULL
    )""",
    """CREATE TABLE condition_decisions (
        condition_decision_id TEXT PRIMARY KEY,
        workflow_definition_id TEXT NOT NULL REFERENCES workflow_definitions(workflow_definition_id),
        condition_id TEXT NOT NULL,
        attempt_id TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        UNIQUE (workflow_definition_id, condition_id, attempt_id)
    )""",
    """CREATE TABLE human_gate_decisions (
        human_gate_decision_id TEXT PRIMARY KEY,
        workflow_definition_id TEXT NOT NULL REFERENCES workflow_definitions(workflow_definition_id),
        human_gate_id TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        UNIQUE (workflow_definition_id, human_gate_id)
    )""",
)


class WorkflowStoreError(Exception):
    """Workflow persistence failed closed."""


class WorkflowStoreSchemaError(WorkflowStoreError):
    """The database is not the exact Workflow SQLite v1 schema."""


class WorkflowStoreConflictError(WorkflowStoreError):
    """An immutable identity or authority key has conflicting content."""


class WorkflowStoreNotFoundError(WorkflowStoreError):
    """A requested Workflow authority record is absent."""


def _object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise WorkflowStoreSchemaError(f"duplicate JSON key is forbidden: {key!r}")
        result[key] = value
    return result


def _decode_json(payload: str) -> dict[str, object]:
    try:
        value = json.loads(payload, object_pairs_hook=_object)
    except (json.JSONDecodeError, TypeError) as exc:
        raise WorkflowStoreSchemaError("Workflow payload is not exact JSON") from exc
    if not isinstance(value, dict):
        raise WorkflowStoreSchemaError("Workflow payload must be an object")
    return value


def _exact_keys(value: Mapping[str, object], keys: set[str], label: str) -> None:
    if set(value) != keys:
        raise WorkflowStoreSchemaError(f"{label} has an invalid closed field set")


def _sequence(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise WorkflowStoreSchemaError(f"{label} must be an array")
    return value


def _record(value: object, keys: set[str], label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise WorkflowStoreSchemaError(f"{label} must be an object")
    _exact_keys(value, keys, label)
    return value


def _decode_node(value: object) -> Node:
    item = _record(
        value,
        {
            "node_id", "task_id", "calculation_plan_id",
            "calculation_plan_revision", "node_kind", "input_roles", "output_roles",
        },
        "Node",
    )
    return Node(**item)  # type: ignore[arg-type]


def _decode_edge(value: object) -> Edge:
    item = _record(
        value,
        {
            "edge_id", "source_node_id", "source_output_role", "target_node_id",
            "target_input_role", "condition_id", "branch",
        },
        "Edge",
    )
    return Edge(**item)  # type: ignore[arg-type]


def _decode_map(value: object) -> Map:
    item = _record(value, {"map_id", "source_node_id", "source_output_role", "items"}, "Map")
    return Map(**item)  # type: ignore[arg-type]


def _decode_condition(value: object) -> Condition:
    item = _record(
        value,
        {
            "condition_id", "source_node_id", "predicate", "expected_states",
            "true_edge_ids", "false_edge_ids",
        },
        "Condition",
    )
    return Condition(**item)  # type: ignore[arg-type]


def _decode_gate(value: object) -> HumanGate:
    item = _record(value, {"human_gate_id", "target_node_ids", "prompt"}, "HumanGate")
    return HumanGate(**item)  # type: ignore[arg-type]


def _decode_definition(payload: str) -> WorkflowDefinition:
    value = _decode_json(payload)
    _exact_keys(
        value,
        {
            "schema_version", "workflow_definition_id", "workflow_run_id", "workflow_name",
            "nodes", "edges", "maps", "conditions", "human_gates",
        },
        "WorkflowDefinition",
    )
    try:
        record = WorkflowDefinition._from_values(
            schema_version=value["schema_version"],
            workflow_definition_id=cast(str, value["workflow_definition_id"]),
            workflow_run_id=value["workflow_run_id"],
            workflow_name=value["workflow_name"],
            nodes=tuple(_decode_node(item) for item in _sequence(value["nodes"], "nodes")),
            edges=tuple(_decode_edge(item) for item in _sequence(value["edges"], "edges")),
            maps=tuple(_decode_map(item) for item in _sequence(value["maps"], "maps")),
            conditions=tuple(
                _decode_condition(item) for item in _sequence(value["conditions"], "conditions")
            ),
            human_gates=tuple(
                _decode_gate(item) for item in _sequence(value["human_gates"], "human_gates")
            ),
        )
    except (TypeError, WorkflowValueError, ValueError) as exc:
        raise WorkflowStoreSchemaError("WorkflowDefinition row is invalid") from exc
    if _payload_text(record._payload()) != payload:
        raise WorkflowStoreSchemaError("WorkflowDefinition row is not canonical and exact")
    return record


def _decode_condition_decision(payload: str) -> ConditionDecision:
    value = _decode_json(payload)
    _exact_keys(
        value,
        {
            "condition_decision_id", "workflow_definition_id", "workflow_run_id",
            "condition_id", "node_id", "attempt_id", "observed_state", "selected_edge_ids",
        },
        "ConditionDecision",
    )
    try:
        record = ConditionDecision._create(
            condition_decision_id=cast(str, value["condition_decision_id"]),
            workflow_definition_id=cast(str, value["workflow_definition_id"]),
            workflow_run_id=cast(str, value["workflow_run_id"]),
            condition_id=cast(str, value["condition_id"]),
            node_id=cast(str, value["node_id"]),
            attempt_id=cast(str, value["attempt_id"]),
            observed_state=AttemptState(value["observed_state"]),
            selected_edge_ids=cast(list[str], value["selected_edge_ids"]),
        )
    except (TypeError, WorkflowValueError, ValueError) as exc:
        raise WorkflowStoreSchemaError("ConditionDecision row is invalid") from exc
    if _payload_text(record._payload()) != payload:
        raise WorkflowStoreSchemaError("ConditionDecision row is not canonical and exact")
    return record


def _decode_human_gate_decision(payload: str) -> HumanGateDecision:
    value = _decode_json(payload)
    _exact_keys(
        value,
        {
            "human_gate_decision_id", "workflow_definition_id", "workflow_run_id",
            "human_gate_id", "decision", "reviewer_id", "review_evidence",
        },
        "HumanGateDecision",
    )
    try:
        record = HumanGateDecision._create(
            human_gate_decision_id=cast(str, value["human_gate_decision_id"]),
            workflow_definition_id=cast(str, value["workflow_definition_id"]),
            workflow_run_id=cast(str, value["workflow_run_id"]),
            human_gate_id=cast(str, value["human_gate_id"]),
            decision=cast(str, value["decision"]),
            reviewer_id=cast(str, value["reviewer_id"]),
            review_evidence=cast(dict[str, object], value["review_evidence"]),
        )
    except (TypeError, WorkflowValueError, ValueError) as exc:
        raise WorkflowStoreSchemaError("HumanGateDecision row is invalid") from exc
    if _payload_text(record._payload()) != payload:
        raise WorkflowStoreSchemaError("HumanGateDecision row is not canonical and exact")
    return record


def _schema_identity(connection: sqlite3.Connection) -> tuple[tuple[object, ...], ...]:
    return tuple(
        tuple(row)
        for row in connection.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_schema "
            "WHERE name NOT GLOB 'sqlite_*' ORDER BY type,name"
        )
    )


def _expected_schema_identity() -> tuple[tuple[object, ...], ...]:
    connection = sqlite3.connect(":memory:")
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        for statement in _SCHEMA_STATEMENTS:
            connection.execute(statement)
        return _schema_identity(connection)
    finally:
        connection.close()


class SQLiteWorkflowStore:
    """Opaque Workflow-owned store with explicit create/reopen lifecycle."""

    __slots__ = ("_closed", "_connection", "_database_path", "_file_identity")

    def __init__(self) -> None:
        raise TypeError("use SQLiteWorkflowStore.create_new or open_existing")

    @classmethod
    def create_new(cls, path: str | Path) -> SQLiteWorkflowStore:
        database_path = cls._canonical_path(path)
        flags = os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(database_path, flags, 0o600)
        except FileExistsError as exc:
            raise WorkflowStoreConflictError("Workflow store target already exists") from exc
        except OSError as exc:
            raise WorkflowStoreError("Workflow store target could not be created") from exc
        try:
            os.fchmod(descriptor, 0o600)
            observed = os.fstat(descriptor)
            if not stat.S_ISREG(observed.st_mode):
                raise WorkflowStoreError("Workflow store target is not a regular file")
            identity = (observed.st_dev, observed.st_ino)
        finally:
            os.close(descriptor)
        value = cls._connect(database_path, identity)
        try:
            with value._transaction(immediate=True) as connection:
                if connection.execute("PRAGMA user_version").fetchone()[0] != 0:
                    raise WorkflowStoreSchemaError("new Workflow store is not unversioned")
                if _schema_identity(connection):
                    raise WorkflowStoreSchemaError("new Workflow store is not empty")
                connection.execute(f"PRAGMA application_id = {_APPLICATION_ID}")
                connection.execute(f"PRAGMA user_version = {_USER_VERSION}")
                for statement in _SCHEMA_STATEMENTS:
                    connection.execute(statement)
                value._attest(connection)
        except Exception:
            value.close()
            raise
        return value

    @classmethod
    def open_existing(cls, path: str | Path) -> SQLiteWorkflowStore:
        database_path = cls._canonical_path(path)
        try:
            observed = os.lstat(database_path)
        except FileNotFoundError as exc:
            raise WorkflowStoreNotFoundError("Workflow store target is missing") from exc
        if stat.S_ISLNK(observed.st_mode) or not stat.S_ISREG(observed.st_mode):
            raise WorkflowStoreSchemaError("Workflow store target must be a regular non-symlink file")
        value = cls._connect(database_path, (observed.st_dev, observed.st_ino))
        try:
            with value._transaction(immediate=False) as connection:
                value._attest(connection)
        except Exception:
            value.close()
            raise
        return value

    @staticmethod
    def _canonical_path(path: str | Path) -> Path:
        value = Path(path).expanduser()
        if not value.is_absolute():
            value = Path.cwd() / value
        return Path(os.path.abspath(os.fspath(value)))

    @classmethod
    def _connect(
        cls, path: Path, identity: tuple[int, int]
    ) -> SQLiteWorkflowStore:
        value = object.__new__(cls)
        object.__setattr__(value, "_closed", True)
        object.__setattr__(value, "_database_path", path)
        object.__setattr__(value, "_file_identity", identity)
        try:
            connection = sqlite3.connect(
                f"{path.as_uri()}?mode=rw&cache=private", uri=True, isolation_level=None
            )
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA trusted_schema = OFF")
            connection.execute("PRAGMA synchronous = FULL")
            connection.execute("PRAGMA busy_timeout = 250")
            object.__setattr__(value, "_connection", connection)
            object.__setattr__(value, "_closed", False)
            value._assert_file_identity()
        except Exception:
            connection = getattr(value, "_connection", None)
            if connection is not None:
                connection.close()
            raise
        return value

    def close(self) -> None:
        if not self._closed:
            self._connection.close()
            self._closed = True

    def _db(self) -> sqlite3.Connection:
        if self._closed:
            raise WorkflowStoreError("Workflow store is closed")
        self._assert_file_identity()
        return self._connection

    def _assert_file_identity(self) -> None:
        try:
            observed = os.lstat(self._database_path)
        except FileNotFoundError as exc:
            raise WorkflowStoreError("Workflow store path disappeared") from exc
        if (
            stat.S_ISLNK(observed.st_mode)
            or not stat.S_ISREG(observed.st_mode)
            or (observed.st_dev, observed.st_ino) != self._file_identity
        ):
            raise WorkflowStoreError("Workflow store path identity changed")

    @contextmanager
    def _transaction(self, *, immediate: bool) -> Iterator[sqlite3.Connection]:
        connection = self._db()
        try:
            connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            yield connection
            connection.execute("COMMIT")
        except sqlite3.Error as exc:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise WorkflowStoreError("Workflow SQLite operation failed") from exc
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise

    def _attest(self, connection: sqlite3.Connection) -> None:
        self._assert_file_identity()
        databases = tuple(tuple(row) for row in connection.execute("PRAGMA database_list"))
        if (
            not databases
            or databases[0][0:2] != (0, "main")
            or any(row not in {(1, "temp", "")} for row in databases[1:])
        ):
            raise WorkflowStoreSchemaError("Workflow store has an unexpected attached database")
        if len(databases) == 2 and tuple(
            connection.execute("SELECT type,name,tbl_name,sql FROM temp.sqlite_schema")
        ):
            raise WorkflowStoreSchemaError("Workflow store has unexpected temp schema objects")
        if connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
            raise WorkflowStoreSchemaError("Workflow store foreign keys are disabled")
        if (
            connection.execute("PRAGMA application_id").fetchone()[0] != _APPLICATION_ID
            or connection.execute("PRAGMA user_version").fetchone()[0] != _USER_VERSION
        ):
            raise WorkflowStoreSchemaError("Workflow store header is not exact schema version 1")
        if _schema_identity(connection) != _expected_schema_identity():
            raise WorkflowStoreSchemaError("Workflow store schema identity is not exact version 1")
        integrity = tuple(row[0] for row in connection.execute("PRAGMA integrity_check"))
        if integrity != ("ok",):
            raise WorkflowStoreSchemaError("Workflow store failed integrity_check")
        definitions: dict[str, WorkflowDefinition] = {}
        for row in connection.execute(
            "SELECT workflow_definition_id,payload_json FROM workflow_definitions "
            "ORDER BY workflow_definition_id"
        ):
            record = _decode_definition(cast(str, row["payload_json"]))
            try:
                validate_definition_structure(record)
            except WorkflowValueError as exc:
                raise WorkflowStoreSchemaError(
                    "persisted WorkflowDefinition is structurally invalid"
                ) from exc
            if row["workflow_definition_id"] != record.workflow_definition_id:
                raise WorkflowStoreSchemaError("WorkflowDefinition row identity is spliced")
            definitions[record.workflow_definition_id] = record
        for row in connection.execute(
            "SELECT condition_decision_id,workflow_definition_id,condition_id,attempt_id,payload_json "
            "FROM condition_decisions ORDER BY condition_decision_id"
        ):
            record = _decode_condition_decision(cast(str, row["payload_json"]))
            if tuple(row)[0:4] != (
                record.condition_decision_id,
                record.workflow_definition_id,
                record.condition_id,
                record.attempt_id,
            ):
                raise WorkflowStoreSchemaError("ConditionDecision row authority is spliced")
            definition = definitions.get(record.workflow_definition_id)
            if definition is None or record.workflow_run_id != definition.workflow_run_id:
                raise WorkflowStoreSchemaError("ConditionDecision definition/run binding is invalid")
            conditions = {item.condition_id: item for item in definition.conditions}
            condition = conditions.get(record.condition_id)
            if condition is None or condition.source_node_id != record.node_id:
                raise WorkflowStoreSchemaError("ConditionDecision component binding is invalid")
            selected = (
                condition.true_edge_ids
                if record.observed_state in condition.expected_states
                else condition.false_edge_ids
            )
            if record.selected_edge_ids != selected:
                raise WorkflowStoreSchemaError("ConditionDecision selected Edge tuple is invalid")
        for row in connection.execute(
            "SELECT human_gate_decision_id,workflow_definition_id,human_gate_id,payload_json "
            "FROM human_gate_decisions ORDER BY human_gate_decision_id"
        ):
            record = _decode_human_gate_decision(cast(str, row["payload_json"]))
            if tuple(row)[0:3] != (
                record.human_gate_decision_id,
                record.workflow_definition_id,
                record.human_gate_id,
            ):
                raise WorkflowStoreSchemaError("HumanGateDecision row authority is spliced")
            definition = definitions.get(record.workflow_definition_id)
            if (
                definition is None
                or record.workflow_run_id != definition.workflow_run_id
                or record.human_gate_id not in {item.human_gate_id for item in definition.human_gates}
            ):
                raise WorkflowStoreSchemaError("HumanGateDecision component binding is invalid")

    def _append(
        self,
        *,
        table: str,
        identity_column: str,
        identity: str,
        columns: tuple[str, ...],
        values: tuple[object, ...],
    ) -> None:
        with self._transaction(immediate=True) as connection:
            self._attest(connection)
            existing = connection.execute(
                f"SELECT {','.join(columns)} FROM {table} WHERE {identity_column} = ?",
                (identity,),
            ).fetchone()
            if existing is not None:
                if tuple(existing) == values:
                    return
                raise WorkflowStoreConflictError(
                    f"Workflow identity {identity!r} already has different content"
                )
            try:
                connection.execute(
                    f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join('?' for _ in values)})",
                    values,
                )
            except sqlite3.IntegrityError as exc:
                raise WorkflowStoreConflictError(
                    "Workflow authority key already has a competing decision"
                ) from exc
            self._attest(connection)

    def _record_definition(self, record: WorkflowDefinition) -> None:
        self._append(
            table="workflow_definitions",
            identity_column="workflow_definition_id",
            identity=record.workflow_definition_id,
            columns=("workflow_definition_id", "payload_json"),
            values=(record.workflow_definition_id, _payload_text(record._payload())),
        )

    def _record_condition_decision(self, record: ConditionDecision) -> None:
        self._append(
            table="condition_decisions",
            identity_column="condition_decision_id",
            identity=record.condition_decision_id,
            columns=(
                "condition_decision_id", "workflow_definition_id", "condition_id",
                "attempt_id", "payload_json",
            ),
            values=(
                record.condition_decision_id, record.workflow_definition_id,
                record.condition_id, record.attempt_id, _payload_text(record._payload()),
            ),
        )

    def _record_human_gate_decision(self, record: HumanGateDecision) -> None:
        self._append(
            table="human_gate_decisions",
            identity_column="human_gate_decision_id",
            identity=record.human_gate_decision_id,
            columns=(
                "human_gate_decision_id", "workflow_definition_id", "human_gate_id",
                "payload_json",
            ),
            values=(
                record.human_gate_decision_id, record.workflow_definition_id,
                record.human_gate_id, _payload_text(record._payload()),
            ),
        )

    def _load_definition(self, workflow_definition_id: str) -> WorkflowDefinition:
        with self._transaction(immediate=False) as connection:
            self._attest(connection)
            row = connection.execute(
                "SELECT payload_json FROM workflow_definitions WHERE workflow_definition_id = ?",
                (workflow_definition_id,),
            ).fetchone()
            if row is None:
                raise WorkflowStoreNotFoundError(
                    f"WorkflowDefinition {workflow_definition_id!r} was not found"
                )
            return _decode_definition(cast(str, row[0]))

    def _load_condition_decisions(self, workflow_definition_id: str) -> tuple[ConditionDecision, ...]:
        with self._transaction(immediate=False) as connection:
            self._attest(connection)
            rows = connection.execute(
                "SELECT payload_json FROM condition_decisions WHERE workflow_definition_id = ? "
                "ORDER BY condition_decision_id",
                (workflow_definition_id,),
            ).fetchall()
            return tuple(_decode_condition_decision(cast(str, row[0])) for row in rows)

    def _load_human_gate_decisions(self, workflow_definition_id: str) -> tuple[HumanGateDecision, ...]:
        with self._transaction(immediate=False) as connection:
            self._attest(connection)
            rows = connection.execute(
                "SELECT payload_json FROM human_gate_decisions WHERE workflow_definition_id = ? "
                "ORDER BY human_gate_decision_id",
                (workflow_definition_id,),
            ).fetchall()
            return tuple(_decode_human_gate_decision(cast(str, row[0])) for row in rows)
