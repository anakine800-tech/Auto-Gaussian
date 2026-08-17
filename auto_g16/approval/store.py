"""Approval-owned append-only SQLite schema v1."""

from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Iterator, Mapping
import json
from pathlib import Path
import sqlite3
from typing import Final, cast

from .models import (
    APPROVAL_SCHEMA_VERSION,
    ApprovalValueError,
    ApprovalDecision,
    BatchApprovalMember,
    BatchSubmitApproval,
    ExactOperationalConfirmation,
    ScientificApproval,
    plain_value,
    require_text,
)


_DOMAINS: Final = {
    "scientific-approval": ("scientific_approval_id", ScientificApproval),
    "batch-submit-approval": ("batch_submit_approval_id", BatchSubmitApproval),
    "operational-confirmation": (
        "operational_confirmation_id",
        ExactOperationalConfirmation,
    ),
}

_SCHEMA = f"""
CREATE TABLE approval_evidence (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    domain TEXT NOT NULL CHECK (
        domain IN ('scientific-approval', 'batch-submit-approval', 'operational-confirmation')
    ),
    evidence_id TEXT NOT NULL UNIQUE,
    schema_version INTEGER NOT NULL CHECK (schema_version = {APPROVAL_SCHEMA_VERSION}),
    payload TEXT NOT NULL
)
""".strip()


class ApprovalStoreError(Exception):
    """Base failure for approval-owned persistence."""


class ApprovalStoreSchemaError(ApprovalStoreError):
    """The approval database is not the exact supported schema."""


class ApprovalStoreConflictError(ApprovalStoreError):
    """An evidence identity already has a different immutable payload."""


class ApprovalStoreNotFoundError(ApprovalStoreError):
    """Requested approval evidence was not found."""


def _schema_identity(connection: sqlite3.Connection) -> tuple[object, ...]:
    table = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='approval_evidence'"
    ).fetchone()
    columns = tuple(
        tuple(row)
        for row in connection.execute("PRAGMA table_info('approval_evidence')")
    )
    indexes = tuple(
        tuple(row)
        for row in connection.execute("PRAGMA index_list('approval_evidence')")
    )
    return (None if table is None else table[0], columns, indexes)


def _expected_schema_identity() -> tuple[object, ...]:
    connection = sqlite3.connect(":memory:")
    try:
        connection.execute(_SCHEMA)
        return _schema_identity(connection)
    finally:
        connection.close()


def _payload_text(record: object) -> str:
    payload = record.persisted_payload()  # type: ignore[attr-defined]
    return json.dumps(
        plain_value(payload),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ApprovalStoreSchemaError(f"stored {name} must be a mapping")
    return cast(Mapping[str, object], value)


def _assert_rebuilt_record(
    record: object,
    rebuilt: object,
    identity_field: str,
) -> None:
    schema_version = getattr(record, "schema_version", None)
    if type(schema_version) is not int or schema_version != APPROVAL_SCHEMA_VERSION:
        raise ApprovalValueError(
            f"record schema_version must be exactly {APPROVAL_SCHEMA_VERSION}"
        )
    evidence_id = getattr(record, identity_field, None)
    require_text(evidence_id, identity_field)
    if (
        getattr(rebuilt, identity_field) != evidence_id
        or _payload_text(rebuilt) != _payload_text(record)
    ):
        raise ApprovalStoreConflictError(
            "approval evidence identity is stale for its authority payload"
        )


def _assert_scientific_record_closed(record: ScientificApproval) -> None:
    rebuilt = ScientificApproval._from_values(
        calculation_plan_id=record.calculation_plan_id,
        task_id=record.task_id,
        calculation_plan_revision=record.calculation_plan_revision,
        canonical_intent=record.canonical_intent,
        displayed_semantic_meaning=record.displayed_semantic_meaning,
        reviewer_id=record.reviewer_id,
        reviewer_evidence=record.reviewer_evidence,
        decision=record.decision,
    )
    _assert_rebuilt_record(record, rebuilt, "scientific_approval_id")


def _assert_batch_record_closed(record: BatchSubmitApproval) -> None:
    if not isinstance(record.members, tuple):
        raise ApprovalValueError("Batch members must be an immutable tuple")
    members: list[BatchApprovalMember] = []
    for member in record.members:
        if not isinstance(member, BatchApprovalMember):
            raise ApprovalValueError("Batch members must be BatchApprovalMember values")
        members.append(
            BatchApprovalMember(
                attempt_id=member.attempt_id,
                task_id=member.task_id,
                calculation_plan_id=member.calculation_plan_id,
                calculation_plan_revision=member.calculation_plan_revision,
                scientific_approval_id=member.scientific_approval_id,
            )
        )
    rebuilt = BatchSubmitApproval._from_values(
        members=tuple(members),
        reviewer_id=record.reviewer_id,
        reviewer_evidence=record.reviewer_evidence,
        decision=record.decision,
    )
    _assert_rebuilt_record(record, rebuilt, "batch_submit_approval_id")


def _assert_operational_record_closed(record: ExactOperationalConfirmation) -> None:
    rebuilt = ExactOperationalConfirmation._from_values(
        execution_snapshot_id=record.execution_snapshot_id,
        attempt_id=record.attempt_id,
        calculation_plan_id=record.calculation_plan_id,
        calculation_plan_revision=record.calculation_plan_revision,
        execution_snapshot_semantics=record.execution_snapshot_semantics,
        confirmer_id=record.confirmer_id,
        confirmer_evidence=record.confirmer_evidence,
        decision=record.decision,
    )
    _assert_rebuilt_record(record, rebuilt, "operational_confirmation_id")


class SQLiteApprovalStore:
    """Minimal approval-layer store; its schema is not a cross-layer public ABI."""

    def __init__(self, database: str | Path = ":memory:") -> None:
        self._closed = False
        try:
            self._connection = sqlite3.connect(str(database), isolation_level=None)
            self._connection.row_factory = sqlite3.Row
            self._initialize_schema()
        except Exception:
            connection = getattr(self, "_connection", None)
            if connection is not None:
                connection.close()
            self._closed = True
            raise

    def __enter__(self) -> SQLiteApprovalStore:
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
            raise ApprovalStoreError("approval store is closed")
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
                raise ApprovalStoreSchemaError(
                    "refusing to initialize an unversioned database containing objects"
                )
            with self._transaction() as transaction:
                transaction.execute(_SCHEMA)
                transaction.execute(f"PRAGMA user_version = {APPROVAL_SCHEMA_VERSION}")
        elif version != APPROVAL_SCHEMA_VERSION:
            raise ApprovalStoreSchemaError(
                f"unsupported approval schema version {version}; "
                f"expected {APPROVAL_SCHEMA_VERSION}"
            )
        if _schema_identity(connection) != _expected_schema_identity():
            raise ApprovalStoreSchemaError(
                "approval store schema identity does not match schema version 1"
            )

    def _store(self, domain: str, evidence_id: str, record: object) -> None:
        require_text(evidence_id, "evidence_id")
        payload = _payload_text(record)
        with self._transaction() as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO approval_evidence
                        (domain, evidence_id, schema_version, payload)
                    VALUES (?, ?, ?, ?)
                    """,
                    (domain, evidence_id, APPROVAL_SCHEMA_VERSION, payload),
                )
            except sqlite3.IntegrityError as exc:
                existing = connection.execute(
                    """
                    SELECT domain, schema_version, payload
                    FROM approval_evidence WHERE evidence_id = ?
                    """,
                    (evidence_id,),
                ).fetchone()
                if existing is not None and tuple(existing) == (
                    domain,
                    APPROVAL_SCHEMA_VERSION,
                    payload,
                ):
                    return
                raise ApprovalStoreConflictError(
                    f"approval evidence {evidence_id!r} already has different content"
                ) from exc

    def _load_payload(self, domain: str, evidence_id: str) -> Mapping[str, object]:
        require_text(evidence_id, "evidence_id")
        row = self._db().execute(
            """
            SELECT schema_version, payload FROM approval_evidence
            WHERE domain = ? AND evidence_id = ?
            """,
            (domain, evidence_id),
        ).fetchone()
        if row is None:
            raise ApprovalStoreNotFoundError(
                f"{domain} evidence {evidence_id!r} was not found"
            )
        if row[0] != APPROVAL_SCHEMA_VERSION:
            raise ApprovalStoreSchemaError("stored approval evidence has another schema")
        try:
            value = json.loads(row[1])
        except (TypeError, json.JSONDecodeError) as exc:
            raise ApprovalStoreSchemaError("stored approval payload is malformed") from exc
        return _mapping(value, "approval payload")

    def store_scientific_approval(self, record: ScientificApproval) -> None:
        if not isinstance(record, ScientificApproval):
            raise ApprovalValueError("record must be a ScientificApproval")
        _assert_scientific_record_closed(record)
        self._store("scientific-approval", record.scientific_approval_id, record)

    def load_scientific_approval(self, evidence_id: str) -> ScientificApproval:
        payload = self._load_payload("scientific-approval", evidence_id)
        record = ScientificApproval._from_values(
            calculation_plan_id=cast(str, payload["calculation_plan_id"]),
            task_id=cast(str, payload["task_id"]),
            calculation_plan_revision=cast(int, payload["calculation_plan_revision"]),
            canonical_intent=_mapping(payload["canonical_intent"], "canonical_intent"),
            displayed_semantic_meaning=_mapping(
                payload["displayed_semantic_meaning"], "displayed_semantic_meaning"
            ),
            reviewer_id=cast(str, payload["reviewer_id"]),
            reviewer_evidence=_mapping(payload["reviewer_evidence"], "reviewer_evidence"),
            decision=ApprovalDecision(cast(str, payload["decision"])),
        )
        if record.scientific_approval_id != evidence_id:
            raise ApprovalStoreConflictError("stored Scientific Approval identity is stale")
        return record

    def store_batch_submit_approval(self, record: BatchSubmitApproval) -> None:
        if not isinstance(record, BatchSubmitApproval):
            raise ApprovalValueError("record must be a BatchSubmitApproval")
        _assert_batch_record_closed(record)
        self._store("batch-submit-approval", record.batch_submit_approval_id, record)

    def load_batch_submit_approval(self, evidence_id: str) -> BatchSubmitApproval:
        payload = self._load_payload("batch-submit-approval", evidence_id)
        raw_members = payload["members"]
        if not isinstance(raw_members, list):
            raise ApprovalStoreSchemaError("stored Batch members must be a sequence")
        members = tuple(
            BatchApprovalMember(
                attempt_id=cast(str, _mapping(item, "Batch member")["attempt_id"]),
                task_id=cast(str, _mapping(item, "Batch member")["task_id"]),
                calculation_plan_id=cast(
                    str, _mapping(item, "Batch member")["calculation_plan_id"]
                ),
                calculation_plan_revision=cast(
                    int,
                    _mapping(item, "Batch member")["calculation_plan_revision"],
                ),
                scientific_approval_id=cast(
                    str, _mapping(item, "Batch member")["scientific_approval_id"]
                ),
            )
            for item in raw_members
        )
        record = BatchSubmitApproval._from_values(
            members=members,
            reviewer_id=cast(str, payload["reviewer_id"]),
            reviewer_evidence=_mapping(payload["reviewer_evidence"], "reviewer_evidence"),
            decision=ApprovalDecision(cast(str, payload["decision"])),
        )
        if record.batch_submit_approval_id != evidence_id:
            raise ApprovalStoreConflictError("stored Batch Submit Approval identity is stale")
        return record

    def store_operational_confirmation(
        self, record: ExactOperationalConfirmation
    ) -> None:
        if not isinstance(record, ExactOperationalConfirmation):
            raise ApprovalValueError("record must be an ExactOperationalConfirmation")
        _assert_operational_record_closed(record)
        self._store(
            "operational-confirmation", record.operational_confirmation_id, record
        )

    def load_operational_confirmation(
        self, evidence_id: str
    ) -> ExactOperationalConfirmation:
        payload = self._load_payload("operational-confirmation", evidence_id)
        record = ExactOperationalConfirmation._from_values(
            execution_snapshot_id=cast(str, payload["execution_snapshot_id"]),
            attempt_id=cast(str, payload["attempt_id"]),
            calculation_plan_id=cast(str, payload["calculation_plan_id"]),
            calculation_plan_revision=cast(int, payload["calculation_plan_revision"]),
            execution_snapshot_semantics=_mapping(
                payload["execution_snapshot_semantics"],
                "execution_snapshot_semantics",
            ),
            confirmer_id=cast(str, payload["confirmer_id"]),
            confirmer_evidence=_mapping(
                payload["confirmer_evidence"], "confirmer_evidence"
            ),
            decision=ApprovalDecision(cast(str, payload["decision"])),
        )
        if record.operational_confirmation_id != evidence_id:
            raise ApprovalStoreConflictError(
                "stored Operational Confirmation identity is stale"
            )
        return record

    def evidence_count(self) -> int:
        return cast(
            int,
            self._db().execute("SELECT COUNT(*) FROM approval_evidence").fetchone()[0],
        )
