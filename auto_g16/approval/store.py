"""Approval-owned append-only SQLite schema v1."""

from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Iterator, Mapping
import json
from pathlib import Path
import sqlite3
from typing import Final, cast
from uuid import UUID

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

_SCIENTIFIC_FIELDS: Final = frozenset(
    {
        "schema_version",
        "evidence_kind",
        "scientific_approval_id",
        "calculation_plan_id",
        "task_id",
        "calculation_plan_revision",
        "canonical_intent",
        "displayed_semantic_meaning",
        "reviewer_id",
        "reviewer_evidence",
        "decision",
    }
)
_BATCH_FIELDS: Final = frozenset(
    {
        "schema_version",
        "evidence_kind",
        "batch_submit_approval_id",
        "members",
        "reviewer_id",
        "reviewer_evidence",
        "decision",
    }
)
_BATCH_MEMBER_FIELDS: Final = frozenset(
    {
        "attempt_id",
        "task_id",
        "calculation_plan_id",
        "calculation_plan_revision",
        "scientific_approval_id",
    }
)
_OPERATIONAL_FIELDS: Final = frozenset(
    {
        "schema_version",
        "evidence_kind",
        "operational_confirmation_id",
        "execution_snapshot_id",
        "attempt_id",
        "calculation_plan_id",
        "calculation_plan_revision",
        "execution_snapshot_semantics",
        "confirmer_id",
        "confirmer_evidence",
        "decision",
    }
)
_SNAPSHOT_FIELDS: Final = frozenset(
    {
        "execution_snapshot_id",
        "attempt_id",
        "submission_intent_id",
        "calculation_plan_id",
        "calculation_plan_revision",
        "prepared_input_binding",
        "resolved_resource_request",
        "resolved_server_profile",
        "workspace_binding",
        "pbs_template_binding",
        "adapter_contract_version",
    }
)

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


def _integrity_failure(message: str) -> ApprovalStoreConflictError:
    return ApprovalStoreConflictError(f"persisted approval integrity failure: {message}")


def _exact_object(
    value: object,
    expected_fields: frozenset[str],
    name: str,
) -> dict[str, object]:
    if type(value) is not dict:
        raise _integrity_failure(f"{name} must be an exact JSON object")
    observed = set(value)
    if observed != expected_fields:
        missing = sorted(expected_fields - observed)
        extra = sorted(observed - expected_fields)
        raise _integrity_failure(
            f"{name} has a non-closed field set; missing={missing}, extra={extra}"
        )
    return cast(dict[str, object], value)


def _exact_text(value: object, name: str) -> str:
    if type(value) is not str:
        raise _integrity_failure(f"{name} must be an exact string")
    try:
        return require_text(value, name)
    except ApprovalValueError as exc:
        raise _integrity_failure(str(exc)) from exc


def _exact_positive_integer(value: object, name: str) -> int:
    if type(value) is not int or value < 1:
        raise _integrity_failure(f"{name} must be an exact positive integer")
    return value


def _uuid5_text(value: object, name: str) -> str:
    text = _exact_text(value, name)
    try:
        parsed = UUID(text)
    except ValueError as exc:
        raise _integrity_failure(f"{name} must be a UUID") from exc
    if parsed.version != 5 or str(parsed) != text:
        raise _integrity_failure(f"{name} must be a canonical UUIDv5")
    return text


def _sha256_text(value: object, name: str) -> str:
    text = _exact_text(value, name)
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise _integrity_failure(f"{name} must be a lowercase SHA-256 digest")
    return text


def _json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise _integrity_failure(f"duplicate JSON object key {key!r}")
        value[key] = item
    return value


def _reject_json_constant(value: str) -> object:
    raise _integrity_failure(f"unsupported JSON constant {value!r}")


def _decode_json_payload(value: object) -> dict[str, object]:
    if type(value) is not str:
        raise _integrity_failure("payload column must be an exact JSON string")
    try:
        decoded = json.loads(
            value,
            object_pairs_hook=_json_object,
            parse_constant=_reject_json_constant,
        )
    except ApprovalStoreConflictError:
        raise
    except (TypeError, json.JSONDecodeError, UnicodeError) as exc:
        raise _integrity_failure("payload is malformed JSON") from exc
    if type(decoded) is not dict:
        raise _integrity_failure("payload must be a top-level JSON object")
    return cast(dict[str, object], decoded)


def _decision_value(value: object, name: str) -> ApprovalDecision:
    text = _exact_text(value, name)
    try:
        return ApprovalDecision(text)
    except ValueError as exc:
        raise _integrity_failure(f"{name} is unsupported") from exc


def _exact_mapping(value: object, name: str) -> dict[str, object]:
    if type(value) is not dict:
        raise _integrity_failure(f"{name} must be an exact JSON object")
    return cast(dict[str, object], value)


def _validate_snapshot_semantics(
    value: object,
    *,
    execution_snapshot_id: str,
    attempt_id: str,
    calculation_plan_id: str,
    calculation_plan_revision: int,
) -> Mapping[str, object]:
    snapshot = _exact_object(value, _SNAPSHOT_FIELDS, "execution_snapshot_semantics")
    if _uuid5_text(snapshot["execution_snapshot_id"], "snapshot.execution_snapshot_id") != execution_snapshot_id:
        raise _integrity_failure("snapshot identity disagrees with confirmation envelope")
    if _exact_text(snapshot["attempt_id"], "snapshot.attempt_id") != attempt_id:
        raise _integrity_failure("snapshot Attempt disagrees with confirmation envelope")
    if _exact_text(snapshot["calculation_plan_id"], "snapshot.calculation_plan_id") != calculation_plan_id:
        raise _integrity_failure("snapshot plan disagrees with confirmation envelope")
    if _exact_positive_integer(
        snapshot["calculation_plan_revision"], "snapshot.calculation_plan_revision"
    ) != calculation_plan_revision:
        raise _integrity_failure("snapshot plan revision disagrees with confirmation envelope")
    _uuid5_text(snapshot["submission_intent_id"], "snapshot.submission_intent_id")
    _exact_text(snapshot["adapter_contract_version"], "snapshot.adapter_contract_version")

    prepared = _exact_object(
        snapshot["prepared_input_binding"],
        frozenset(
            {
                "prepared_input_binding_id",
                "attempt_id",
                "calculation_plan_id",
                "calculation_plan_revision",
                "input_format",
                "logical_name",
                "sha256",
                "size_bytes",
            }
        ),
        "snapshot.prepared_input_binding",
    )
    _uuid5_text(
        prepared["prepared_input_binding_id"],
        "snapshot.prepared_input_binding.id",
    )
    if _exact_text(prepared["attempt_id"], "snapshot.prepared_input_binding.attempt_id") != attempt_id:
        raise _integrity_failure("prepared input disagrees with snapshot Attempt")
    if _exact_text(
        prepared["calculation_plan_id"],
        "snapshot.prepared_input_binding.calculation_plan_id",
    ) != calculation_plan_id:
        raise _integrity_failure("prepared input disagrees with snapshot plan")
    if _exact_positive_integer(
        prepared["calculation_plan_revision"],
        "snapshot.prepared_input_binding.calculation_plan_revision",
    ) != calculation_plan_revision:
        raise _integrity_failure("prepared input disagrees with snapshot plan revision")
    _exact_text(prepared["input_format"], "snapshot.prepared_input_binding.input_format")
    _exact_text(prepared["logical_name"], "snapshot.prepared_input_binding.logical_name")
    _sha256_text(prepared["sha256"], "snapshot.prepared_input_binding.sha256")
    _exact_positive_integer(
        prepared["size_bytes"], "snapshot.prepared_input_binding.size_bytes"
    )

    resources = _exact_object(
        snapshot["resolved_resource_request"],
        frozenset(
            {
                "resolved_resource_request_id",
                "resource_spec_id",
                "cores",
                "memory_mb",
                "walltime_seconds",
                "queue",
            }
        ),
        "snapshot.resolved_resource_request",
    )
    _uuid5_text(
        resources["resolved_resource_request_id"],
        "snapshot.resolved_resource_request.id",
    )
    _exact_text(
        resources["resource_spec_id"],
        "snapshot.resolved_resource_request.resource_spec_id",
    )
    for field_name in ("cores", "memory_mb", "walltime_seconds"):
        _exact_positive_integer(
            resources[field_name], f"snapshot.resolved_resource_request.{field_name}"
        )
    if resources["queue"] is not None:
        _exact_text(resources["queue"], "snapshot.resolved_resource_request.queue")

    profile = _exact_object(
        snapshot["resolved_server_profile"],
        frozenset(
            {
                "resolved_server_profile_id",
                "server_profile_id",
                "profile_revision",
                "effective_config_sha256",
                "transport_kind",
                "target_identity",
                "remote_user",
                "remote_root",
                "platform_paths",
                "runtime_identities",
            }
        ),
        "snapshot.resolved_server_profile",
    )
    _uuid5_text(profile["resolved_server_profile_id"], "snapshot.resolved_profile.id")
    _exact_text(profile["server_profile_id"], "snapshot.resolved_profile.profile_id")
    _exact_positive_integer(profile["profile_revision"], "snapshot.resolved_profile.revision")
    _sha256_text(
        profile["effective_config_sha256"],
        "snapshot.resolved_profile.effective_config_sha256",
    )
    for field_name in ("transport_kind", "remote_user", "remote_root"):
        _exact_text(profile[field_name], f"snapshot.resolved_profile.{field_name}")
    target = _exact_object(
        profile["target_identity"],
        frozenset(
            {
                "batch_mode",
                "destination_host",
                "destination_port",
                "host_key_policy",
                "identities_only",
                "jump_topology",
            }
        ),
        "snapshot.resolved_profile.target_identity",
    )
    for field_name in ("batch_mode", "identities_only"):
        if type(target[field_name]) is not bool:
            raise _integrity_failure(
                f"snapshot.resolved_profile.target_identity.{field_name} must be boolean"
            )
    _exact_text(
        target["destination_host"],
        "snapshot.resolved_profile.target_identity.destination_host",
    )
    _exact_positive_integer(
        target["destination_port"],
        "snapshot.resolved_profile.target_identity.destination_port",
    )
    _exact_text(
        target["host_key_policy"],
        "snapshot.resolved_profile.target_identity.host_key_policy",
    )
    jump_topology = target["jump_topology"]
    if type(jump_topology) is not list:
        raise _integrity_failure("snapshot jump_topology must be an exact JSON array")
    for index, raw_hop in enumerate(jump_topology):
        hop = _exact_object(
            raw_hop,
            frozenset({"host", "port", "user"}),
            f"snapshot jump_topology[{index}]",
        )
        _exact_text(hop["host"], f"snapshot jump_topology[{index}].host")
        _exact_positive_integer(
            hop["port"], f"snapshot jump_topology[{index}].port"
        )
        _exact_text(hop["user"], f"snapshot jump_topology[{index}].user")
    platform_paths = _exact_mapping(
        profile["platform_paths"], "snapshot.resolved_profile.platform_paths"
    )
    for name, path in platform_paths.items():
        _exact_text(name, "snapshot.resolved_profile.platform path name")
        _exact_text(path, f"snapshot.resolved_profile.platform_paths.{name}")
    runtime_identities = _exact_mapping(
        profile["runtime_identities"], "snapshot.resolved_profile.runtime_identities"
    )
    for name, identity in runtime_identities.items():
        _exact_text(name, "snapshot.resolved_profile.runtime identity name")
        closed_identity = _exact_object(
            identity,
            frozenset({"sha256", "size_bytes"}),
            f"snapshot.resolved_profile.runtime_identities.{name}",
        )
        _sha256_text(closed_identity["sha256"], f"runtime_identities.{name}.sha256")
        _exact_positive_integer(
            closed_identity["size_bytes"], f"runtime_identities.{name}.size_bytes"
        )

    workspace = _exact_object(
        snapshot["workspace_binding"],
        frozenset(
            {
                "workspace_binding_id",
                "project_id",
                "attempt_id",
                "local_attempt_dir",
                "rtwin_attempt_dir",
                "remote_attempt_dir",
                "local_descriptor_anchor_sha256",
            }
        ),
        "snapshot.workspace_binding",
    )
    _uuid5_text(workspace["workspace_binding_id"], "snapshot.workspace_binding.id")
    _exact_text(workspace["project_id"], "snapshot.workspace_binding.project_id")
    if _exact_text(workspace["attempt_id"], "snapshot.workspace_binding.attempt_id") != attempt_id:
        raise _integrity_failure("workspace disagrees with snapshot Attempt")
    for field_name in ("local_attempt_dir", "remote_attempt_dir"):
        _exact_text(workspace[field_name], f"snapshot.workspace_binding.{field_name}")
    if workspace["rtwin_attempt_dir"] is not None:
        _exact_text(
            workspace["rtwin_attempt_dir"], "snapshot.workspace_binding.rtwin_attempt_dir"
        )
    _sha256_text(
        workspace["local_descriptor_anchor_sha256"],
        "snapshot.workspace_binding.local_descriptor_anchor_sha256",
    )

    template = _exact_object(
        snapshot["pbs_template_binding"],
        frozenset(
            {
                "pbs_template_binding_id",
                "logical_name",
                "sha256",
                "size_bytes",
                "template_contract_version",
            }
        ),
        "snapshot.pbs_template_binding",
    )
    _uuid5_text(template["pbs_template_binding_id"], "snapshot.pbs_template_binding.id")
    for field_name in ("logical_name", "template_contract_version"):
        _exact_text(template[field_name], f"snapshot.pbs_template_binding.{field_name}")
    _sha256_text(template["sha256"], "snapshot.pbs_template_binding.sha256")
    _exact_positive_integer(
        template["size_bytes"], "snapshot.pbs_template_binding.size_bytes"
    )
    return snapshot


def _canonical_payload_text(payload: Mapping[str, object]) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _decode_scientific(payload: dict[str, object]) -> ScientificApproval:
    value = _exact_object(payload, _SCIENTIFIC_FIELDS, "Scientific Approval payload")
    record = ScientificApproval._from_values(
        calculation_plan_id=_exact_text(
            value["calculation_plan_id"], "calculation_plan_id"
        ),
        task_id=_exact_text(value["task_id"], "task_id"),
        calculation_plan_revision=_exact_positive_integer(
            value["calculation_plan_revision"], "calculation_plan_revision"
        ),
        canonical_intent=_exact_mapping(value["canonical_intent"], "canonical_intent"),
        displayed_semantic_meaning=_exact_mapping(
            value["displayed_semantic_meaning"], "displayed_semantic_meaning"
        ),
        reviewer_id=_exact_text(value["reviewer_id"], "reviewer_id"),
        reviewer_evidence=_exact_mapping(
            value["reviewer_evidence"], "reviewer_evidence"
        ),
        decision=_decision_value(value["decision"], "decision"),
    )
    return record


def _decode_batch(payload: dict[str, object]) -> BatchSubmitApproval:
    value = _exact_object(payload, _BATCH_FIELDS, "Batch Submit Approval payload")
    raw_members = value["members"]
    if type(raw_members) is not list or not raw_members:
        raise _integrity_failure("Batch members must be an exact non-empty JSON array")
    members: list[BatchApprovalMember] = []
    for index, raw_member in enumerate(raw_members):
        member = _exact_object(
            raw_member, _BATCH_MEMBER_FIELDS, f"Batch member {index}"
        )
        members.append(
            BatchApprovalMember(
                attempt_id=_exact_text(member["attempt_id"], "member.attempt_id"),
                task_id=_exact_text(member["task_id"], "member.task_id"),
                calculation_plan_id=_exact_text(
                    member["calculation_plan_id"], "member.calculation_plan_id"
                ),
                calculation_plan_revision=_exact_positive_integer(
                    member["calculation_plan_revision"],
                    "member.calculation_plan_revision",
                ),
                scientific_approval_id=_uuid5_text(
                    member["scientific_approval_id"], "member.scientific_approval_id"
                ),
            )
        )
    return BatchSubmitApproval._from_values(
        members=tuple(members),
        reviewer_id=_exact_text(value["reviewer_id"], "reviewer_id"),
        reviewer_evidence=_exact_mapping(
            value["reviewer_evidence"], "reviewer_evidence"
        ),
        decision=_decision_value(value["decision"], "decision"),
    )


def _decode_operational(payload: dict[str, object]) -> ExactOperationalConfirmation:
    value = _exact_object(
        payload, _OPERATIONAL_FIELDS, "Operational Confirmation payload"
    )
    execution_snapshot_id = _uuid5_text(
        value["execution_snapshot_id"], "execution_snapshot_id"
    )
    attempt_id = _exact_text(value["attempt_id"], "attempt_id")
    calculation_plan_id = _exact_text(
        value["calculation_plan_id"], "calculation_plan_id"
    )
    calculation_plan_revision = _exact_positive_integer(
        value["calculation_plan_revision"], "calculation_plan_revision"
    )
    snapshot = _validate_snapshot_semantics(
        value["execution_snapshot_semantics"],
        execution_snapshot_id=execution_snapshot_id,
        attempt_id=attempt_id,
        calculation_plan_id=calculation_plan_id,
        calculation_plan_revision=calculation_plan_revision,
    )
    return ExactOperationalConfirmation._from_values(
        execution_snapshot_id=execution_snapshot_id,
        attempt_id=attempt_id,
        calculation_plan_id=calculation_plan_id,
        calculation_plan_revision=calculation_plan_revision,
        execution_snapshot_semantics=snapshot,
        confirmer_id=_exact_text(value["confirmer_id"], "confirmer_id"),
        confirmer_evidence=_exact_mapping(
            value["confirmer_evidence"], "confirmer_evidence"
        ),
        decision=_decision_value(value["decision"], "decision"),
    )


def _decode_evidence_row(
    row: sqlite3.Row,
    *,
    expected_domain: str,
) -> object:
    """Decode one hostile row through the single persistence integrity seam."""

    try:
        if tuple(row.keys()) != ("domain", "evidence_id", "schema_version", "payload"):
            raise _integrity_failure("row envelope columns are not exact")
        domain = _exact_text(row["domain"], "row.domain")
        if domain not in _DOMAINS or domain != expected_domain:
            raise _integrity_failure("row evidence kind disagrees with requested type")
        evidence_id = _uuid5_text(row["evidence_id"], "row.evidence_id")
        schema_version = row["schema_version"]
        if type(schema_version) is not int or schema_version != APPROVAL_SCHEMA_VERSION:
            raise _integrity_failure("row schema version is unsupported")
        payload = _decode_json_payload(row["payload"])
        if type(payload.get("schema_version")) is not int:
            raise _integrity_failure("embedded schema version has the wrong type")
        if payload.get("schema_version") != schema_version:
            raise _integrity_failure("row and embedded schema versions disagree")
        if payload.get("evidence_kind") != domain:
            raise _integrity_failure("row and embedded evidence kinds disagree")
        identity_field, record_type = _DOMAINS[domain]
        if payload.get(identity_field) != evidence_id:
            raise _integrity_failure("row and embedded evidence identities disagree")
        if domain == "scientific-approval":
            record = _decode_scientific(payload)
        elif domain == "batch-submit-approval":
            record = _decode_batch(payload)
        else:
            record = _decode_operational(payload)
        if not isinstance(record, record_type):
            raise _integrity_failure("decoded evidence has the wrong authority type")
        if getattr(record, identity_field) != evidence_id:
            raise _integrity_failure("deterministic evidence identity does not match row")
        if _payload_text(record) != _canonical_payload_text(payload):
            raise _integrity_failure("decoded authority payload is not canonical and exact")
        return record
    except ApprovalStoreConflictError:
        raise
    except (ApprovalValueError, KeyError, TypeError, ValueError) as exc:
        raise _integrity_failure("typed authority payload is malformed") from exc


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
                    SELECT domain, evidence_id, schema_version, payload
                    FROM approval_evidence WHERE evidence_id = ?
                    """,
                    (evidence_id,),
                ).fetchone()
                if existing is None:
                    raise ApprovalStoreConflictError(
                        f"approval evidence {evidence_id!r} conflicted without a row"
                    ) from exc
                decoded = _decode_evidence_row(existing, expected_domain=domain)
                identity_field, _record_type = _DOMAINS[domain]
                if (
                    getattr(decoded, identity_field) == evidence_id
                    and _payload_text(decoded) == payload
                ):
                    return
                raise ApprovalStoreConflictError(
                    f"approval evidence {evidence_id!r} already has different content"
                ) from exc

    def _load_record(self, domain: str, evidence_id: str) -> object:
        require_text(evidence_id, "evidence_id")
        row = self._db().execute(
            """
            SELECT domain, evidence_id, schema_version, payload
            FROM approval_evidence WHERE evidence_id = ?
            """,
            (evidence_id,),
        ).fetchone()
        if row is None:
            raise ApprovalStoreNotFoundError(
                f"{domain} evidence {evidence_id!r} was not found"
            )
        return _decode_evidence_row(row, expected_domain=domain)

    def store_scientific_approval(self, record: ScientificApproval) -> None:
        if not isinstance(record, ScientificApproval):
            raise ApprovalValueError("record must be a ScientificApproval")
        _assert_scientific_record_closed(record)
        self._store("scientific-approval", record.scientific_approval_id, record)

    def load_scientific_approval(self, evidence_id: str) -> ScientificApproval:
        record = self._load_record("scientific-approval", evidence_id)
        if not isinstance(record, ScientificApproval):
            raise _integrity_failure("decoded record is not a Scientific Approval")
        return record

    def store_batch_submit_approval(self, record: BatchSubmitApproval) -> None:
        if not isinstance(record, BatchSubmitApproval):
            raise ApprovalValueError("record must be a BatchSubmitApproval")
        _assert_batch_record_closed(record)
        self._store("batch-submit-approval", record.batch_submit_approval_id, record)

    def load_batch_submit_approval(self, evidence_id: str) -> BatchSubmitApproval:
        record = self._load_record("batch-submit-approval", evidence_id)
        if not isinstance(record, BatchSubmitApproval):
            raise _integrity_failure("decoded record is not a Batch Submit Approval")
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
        record = self._load_record("operational-confirmation", evidence_id)
        if not isinstance(record, ExactOperationalConfirmation):
            raise _integrity_failure("decoded record is not an Operational Confirmation")
        return record

    def evidence_count(self) -> int:
        return cast(
            int,
            self._db().execute("SELECT COUNT(*) FROM approval_evidence").fetchone()[0],
        )
