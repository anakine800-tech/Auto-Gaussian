"""Private successor xTB/CREST transport grammar and driver seam.

This module contains no Core state. Its durable store records only the private
physical-effect side of successor authority; Core receipts remain owned by
``auto_g16.execution``. Preparation is pure, and driver calls are available
only through the explicit invocation seam.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
import os
from pathlib import Path
import re
import secrets
import sqlite3
from threading import RLock
from typing import Protocol, runtime_checkable
from uuid import UUID, uuid5

from ._canonical import TransportBoundaryError, canonical_bytes
_PROTOCOL = "auto-g16-v31-program-effect/1"
_RECEIPT_TYPE = "v31-program-effect-receipt/1"
_PROGRAM_STORE_SCHEMA = "auto-g16-v31-program-transport-store/1"
_ROOT_NAMESPACE = UUID("a51f091c-dfd0-59b6-bf26-86a505a5cb43")
_OPERATIONS = (
    "ALLOCATE_WORKSPACE", "STAGE_EXACT_FILE", "SUBMIT_QSUB_ONCE",
    "QUERY_SCHEDULER", "STAT_EXACT_FILE", "FETCH_EXACT_FILE",
    "RECONCILE_SUBMISSION",
)
_BINDING_FIELDS = {
    "program_transport_store_id", "store_instance_id", "runtime_attestation_id",
    "attempt_id", "program_execution_snapshot_id", "effect_intent_id",
    "program_execution_spec_id", "project_physical_binding_id",
    "workspace_binding_id", "resolved_server_profile_id", "remote_workspace",
}
_WORKSPACE_AUTHORITY_FIELDS = {
    "workspace_authority_id", "workspace_receipt_id", "workspace_physical_token",
}
_JOB_AUTHORITY_FIELDS = {"job_authority_id"}
_STAGE_FIELDS = {
    "artifact_kind", "logical_role", "portable_name", "format", "sha256",
    "size_bytes",
}
_PORTABLE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_JOB = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_SCHEDULER_STATES = frozenset(
    {"queued", "running", "held", "exiting", "terminal", "absent", "unknown"}
)
_RUNTIME_QUALIFICATION_FIELDS = {
    "deployment_id", "bootstrap_protocol", "bootstrap_source_sha256",
    "bootstrap_source_size_bytes",
}
_PROGRAM_STORE_APPLICATION_ID = 1_093_879_637
_PROGRAM_STORE_VERSION = 1
_PROGRAM_STORE_TABLES = (
    "program_transport_meta",
    "program_runtime_attestation",
    "program_effect_physical_authority",
)
_PROGRAM_STORE_DDL = (
    "CREATE TABLE program_transport_meta(singleton INTEGER PRIMARY KEY CHECK(singleton=1),schema_identity BLOB NOT NULL,program_transport_store_id TEXT NOT NULL UNIQUE,store_instance_id TEXT NOT NULL UNIQUE,creation_nonce BLOB NOT NULL CHECK(length(creation_nonce)=32),approved_store_root TEXT NOT NULL,approved_store_path TEXT NOT NULL,store_device INTEGER NOT NULL,store_inode INTEGER NOT NULL)",
    "CREATE TABLE program_runtime_attestation(runtime_attestation_id TEXT PRIMARY KEY,program_transport_store_id TEXT NOT NULL,store_instance_id TEXT NOT NULL,program_execution_snapshot_id TEXT NOT NULL,resolved_server_profile_id TEXT NOT NULL,protocol TEXT NOT NULL,operation_table_sha256 TEXT NOT NULL,qualified_runtime_sha256 TEXT NOT NULL,payload BLOB NOT NULL)",
    "CREATE TABLE program_effect_physical_authority(physical_effect_authority_id TEXT PRIMARY KEY,program_transport_store_id TEXT NOT NULL,store_instance_id TEXT NOT NULL,runtime_attestation_id TEXT NOT NULL REFERENCES program_runtime_attestation(runtime_attestation_id),attempt_id TEXT NOT NULL,program_execution_snapshot_id TEXT NOT NULL,effect_intent_id TEXT NOT NULL,operation TEXT NOT NULL,request_sha256 TEXT NOT NULL,effect_classification TEXT NOT NULL,job_id TEXT,submit_once_key TEXT UNIQUE,payload BLOB NOT NULL)",
)
_PROGRAM_STORE_TRIGGERS = tuple(
    (
        f"{table}_no_{verb}",
        f"CREATE TRIGGER {table}_no_{verb} BEFORE {verb.upper()} ON {table} "
        "BEGIN SELECT RAISE(ABORT,'append-only'); END",
    )
    for table in _PROGRAM_STORE_TABLES
    for verb in ("update", "delete")
)
_PROGRAM_STORE_SCHEMA_IDENTITY = canonical_bytes(
    [*_PROGRAM_STORE_DDL, *[statement for _name, statement in _PROGRAM_STORE_TRIGGERS]]
)
_OPERATION_TABLE_SHA256 = sha256(canonical_bytes((_PROTOCOL, _OPERATIONS))).hexdigest()


class _ProgramConfirmedFailure(RuntimeError):
    """The driver proved that the requested operation had no effect."""


class _ProgramEffectUnknown(RuntimeError):
    """The driver could not prove whether an operation took effect."""


def _text(value: object, label: str) -> str:
    if (
        not isinstance(value, str) or not value or value != value.strip()
        or any(character in value for character in "\x00\r\n")
    ):
        raise TransportBoundaryError(f"{label} is invalid")
    return value


def _positive(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise TransportBoundaryError(f"{label} must be a positive integer")
    return value


def _nonnegative(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise TransportBoundaryError(f"{label} must be a non-negative integer")
    return value


def _digest(value: object) -> str:
    return sha256(canonical_bytes(value)).hexdigest()


def _identity(domain: str, payload: object) -> str:
    namespace = uuid5(_ROOT_NAMESPACE, f"{_PROTOCOL}/{domain}")
    return str(uuid5(namespace, canonical_bytes(payload).decode("ascii")))


def _exact_keys(value: object, keys: set[str], label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise TransportBoundaryError(f"{label} has an invalid closed shape")
    return value


def _portable(value: object, label: str) -> str:
    text = _text(value, label)
    if text in {".", ".."} or _PORTABLE.fullmatch(text) is None:
        raise TransportBoundaryError(f"{label} is not a portable name")
    return text


def _store_paths(
    path: str | os.PathLike[str], approved_root: str | os.PathLike[str]
) -> tuple[str, str]:
    raw_path, raw_root = os.fspath(path), os.fspath(approved_root)
    if not isinstance(raw_path, str) or not isinstance(raw_root, str):
        raise TransportBoundaryError("program transport store paths must be strings")
    absolute_path = os.path.abspath(raw_path)
    absolute_root = os.path.abspath(raw_root)
    if (
        not os.path.isdir(absolute_root)
        or os.path.commonpath((absolute_path, absolute_root)) != absolute_root
        or absolute_path == absolute_root
        or not os.path.isdir(os.path.dirname(absolute_path))
    ):
        raise TransportBoundaryError(
            "program transport store must be a strict descendant of an existing root"
        )
    relative_parent = os.path.relpath(os.path.dirname(absolute_path), absolute_root)
    current = Path(absolute_root)
    if current.is_symlink():
        raise TransportBoundaryError("program transport store root must not be a symlink")
    if relative_parent != ".":
        for component in Path(relative_parent).parts:
            if component in {"", ".", ".."}:
                raise TransportBoundaryError("program transport store parent is invalid")
            current = current / component
            if current.is_symlink() or not current.is_dir():
                raise TransportBoundaryError(
                    "program transport store parent must be a real directory"
                )
    return absolute_path, absolute_root


def _store_file_identity(path: str) -> tuple[int, int]:
    try:
        metadata = os.stat(path, follow_symlinks=False)
    except OSError as exc:
        raise TransportBoundaryError("program transport store file is unavailable") from exc
    if not os.path.isfile(path) or os.path.islink(path):
        raise TransportBoundaryError("program transport store must be a regular file")
    return metadata.st_dev, metadata.st_ino


def _runtime_qualification(value: object) -> Mapping[str, object]:
    qualification = _exact_keys(
        value, _RUNTIME_QUALIFICATION_FIELDS, "program runtime qualification"
    )
    _text(qualification["deployment_id"], "program deployment ID")
    _text(qualification["bootstrap_protocol"], "program bootstrap protocol")
    digest = qualification["bootstrap_source_sha256"]
    if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
        raise TransportBoundaryError("program bootstrap source SHA-256 is invalid")
    _positive(
        qualification["bootstrap_source_size_bytes"],
        "program bootstrap source size",
    )
    canonical_bytes(qualification)
    return qualification


class _ProgramTransportStore:
    """Private append-only physical authority for successor effects only."""

    def __init__(self) -> None:
        raise TypeError("use _ProgramTransportStore.create_new/open_existing")

    @classmethod
    def create_new(
        cls,
        path: str | os.PathLike[str],
        *,
        approved_root: str | os.PathLike[str],
    ) -> _ProgramTransportStore:
        absolute_path, absolute_root = _store_paths(path, approved_root)
        flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0)
        )
        try:
            descriptor = os.open(absolute_path, flags, 0o600)
        except OSError as exc:
            raise TransportBoundaryError(
                "program transport store create-new reservation failed"
            ) from exc
        os.close(descriptor)
        value = cls._open(absolute_path, absolute_root)
        try:
            value._create_schema()
            return value
        except Exception:
            value.close()
            raise

    @classmethod
    def open_existing(
        cls,
        path: str | os.PathLike[str],
        *,
        approved_root: str | os.PathLike[str],
    ) -> _ProgramTransportStore:
        absolute_path, absolute_root = _store_paths(path, approved_root)
        value = cls._open(absolute_path, absolute_root)
        try:
            value._attest()
            return value
        except Exception:
            value.close()
            raise

    @classmethod
    def _open(cls, path: str, root: str) -> _ProgramTransportStore:
        identity = _store_file_identity(path)
        value = object.__new__(cls)
        value._path = path
        value._root = root
        value._file_identity = identity
        value._connection = sqlite3.connect(
            path, isolation_level=None, check_same_thread=False
        )
        value._connection.execute("PRAGMA foreign_keys=ON")
        value._connection.execute("PRAGMA trusted_schema=OFF")
        value._connection.execute("PRAGMA synchronous=FULL")
        value._lock = RLock()
        value._closed = False
        if _store_file_identity(path) != identity:
            value._connection.close()
            value._closed = True
            raise TransportBoundaryError(
                "program transport store changed across SQLite open"
            )
        return value

    def _create_schema(self) -> None:
        nonce = secrets.token_bytes(32)
        store_payload = {
            "schema": _PROGRAM_STORE_SCHEMA,
            "approved_store_root": self._root,
            "approved_store_path": self._path,
        }
        store_id = _identity("program-transport-store", store_payload)
        instance_payload = {
            **store_payload,
            "program_transport_store_id": store_id,
            "creation_nonce_sha256": sha256(nonce).hexdigest(),
            "store_device": self._file_identity[0],
            "store_inode": self._file_identity[1],
        }
        instance_id = _identity("program-transport-store-instance", instance_payload)
        with self._lock:
            self._connection.execute(
                f"PRAGMA application_id={_PROGRAM_STORE_APPLICATION_ID}"
            )
            self._connection.execute(f"PRAGMA user_version={_PROGRAM_STORE_VERSION}")
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                for statement in _PROGRAM_STORE_DDL:
                    self._connection.execute(statement)
                for _name, statement in _PROGRAM_STORE_TRIGGERS:
                    self._connection.execute(statement)
                self._connection.execute(
                    "INSERT INTO program_transport_meta VALUES(1,?,?,?,?,?,?,?,?)",
                    (
                        _PROGRAM_STORE_SCHEMA_IDENTITY,
                        store_id,
                        instance_id,
                        nonce,
                        self._root,
                        self._path,
                        self._file_identity[0],
                        self._file_identity[1],
                    ),
                )
                self._connection.execute("COMMIT")
            except Exception:
                self._connection.execute("ROLLBACK")
                raise
        self._attest()

    def _attest(self) -> None:
        if getattr(self, "_closed", True):
            raise TransportBoundaryError("program transport store is closed")
        if _store_file_identity(self._path) != self._file_identity:
            raise TransportBoundaryError("program transport store identity drifted")
        if (
            self._connection.execute("PRAGMA application_id").fetchone()[0]
            != _PROGRAM_STORE_APPLICATION_ID
            or self._connection.execute("PRAGMA user_version").fetchone()[0]
            != _PROGRAM_STORE_VERSION
            or self._connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1
            or self._connection.execute("PRAGMA trusted_schema").fetchone()[0] != 0
            or self._connection.execute("PRAGMA synchronous").fetchone()[0] != 2
        ):
            raise TransportBoundaryError("program transport store schema drifted")
        definitions = {
            row[0]: row[1]
            for row in self._connection.execute(
                "SELECT name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
            )
        }
        expected = {
            **dict(zip(_PROGRAM_STORE_TABLES, _PROGRAM_STORE_DDL)),
            **dict(_PROGRAM_STORE_TRIGGERS),
        }
        if definitions != expected:
            raise TransportBoundaryError("program transport store inventory drifted")
        rows = self._connection.execute(
            "SELECT * FROM program_transport_meta"
        ).fetchall()
        if len(rows) != 1:
            raise TransportBoundaryError("program transport store meta drifted")
        row = rows[0]
        nonce = row[4]
        expected_store_id = _identity(
            "program-transport-store",
            {
                "schema": _PROGRAM_STORE_SCHEMA,
                "approved_store_root": self._root,
                "approved_store_path": self._path,
            },
        )
        expected_instance_id = None
        if type(nonce) is bytes and len(nonce) == 32:
            expected_instance_id = _identity(
                "program-transport-store-instance",
                {
                    "schema": _PROGRAM_STORE_SCHEMA,
                    "approved_store_root": self._root,
                    "approved_store_path": self._path,
                    "program_transport_store_id": expected_store_id,
                    "creation_nonce_sha256": sha256(nonce).hexdigest(),
                    "store_device": self._file_identity[0],
                    "store_inode": self._file_identity[1],
                },
            )
        if (
            row[0] != 1
            or row[1] != _PROGRAM_STORE_SCHEMA_IDENTITY
            or row[2] != expected_store_id
            or row[3] != expected_instance_id
            or row[5] != self._root
            or row[6] != self._path
            or (row[7], row[8]) != self._file_identity
        ):
            raise TransportBoundaryError("program transport store meta authority drifted")
        self.program_transport_store_id = row[2]
        self.store_instance_id = row[3]

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._connection.close()
                self._closed = True

    def _insert_exact(
        self,
        table: str,
        columns: tuple[str, ...],
        values: tuple[object, ...],
        identity: str,
    ) -> None:
        with self._lock:
            self._attest()
            marks = ",".join("?" for _ in values)
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                try:
                    self._connection.execute(
                        f"INSERT INTO {table}({','.join(columns)}) VALUES({marks})",
                        values,
                    )
                except sqlite3.IntegrityError:
                    existing = self._connection.execute(
                        f"SELECT {','.join(columns)} FROM {table} "
                        f"WHERE {columns[0]}=?",
                        (identity,),
                    ).fetchone()
                    if existing is None or tuple(existing) != values:
                        raise TransportBoundaryError(
                            f"conflicting {table} authority"
                        )
                loaded = self._connection.execute(
                    f"SELECT {','.join(columns)} FROM {table} "
                    f"WHERE {columns[0]}=?",
                    (identity,),
                ).fetchall()
                if len(loaded) != 1 or tuple(loaded[0]) != values:
                    raise TransportBoundaryError(f"{table} append/replay failed")
                self._connection.execute("COMMIT")
            except Exception:
                self._connection.execute("ROLLBACK")
                raise

    def attest_runtime(
        self,
        *,
        program_execution_snapshot_id: str,
        resolved_server_profile_id: str,
        qualification: Mapping[str, object],
    ) -> str:
        self._attest()
        closed = dict(_runtime_qualification(qualification))
        payload = {
            "schema": _PROGRAM_STORE_SCHEMA,
            "program_transport_store_id": self.program_transport_store_id,
            "store_instance_id": self.store_instance_id,
            "program_execution_snapshot_id": _text(
                program_execution_snapshot_id, "program execution snapshot ID"
            ),
            "resolved_server_profile_id": _text(
                resolved_server_profile_id, "resolved server profile ID"
            ),
            "protocol": _PROTOCOL,
            "operation_table_sha256": _OPERATION_TABLE_SHA256,
            "qualified_runtime": closed,
        }
        identity = _identity("program-runtime-attestation", payload)
        columns = (
            "runtime_attestation_id", "program_transport_store_id",
            "store_instance_id", "program_execution_snapshot_id",
            "resolved_server_profile_id", "protocol",
            "operation_table_sha256", "qualified_runtime_sha256", "payload",
        )
        values = (
            identity,
            self.program_transport_store_id,
            self.store_instance_id,
            payload["program_execution_snapshot_id"],
            payload["resolved_server_profile_id"],
            _PROTOCOL,
            _OPERATION_TABLE_SHA256,
            _digest(closed),
            canonical_bytes(payload),
        )
        self._insert_exact(
            "program_runtime_attestation", columns, values, identity
        )
        return identity

    def record_effect(
        self,
        *,
        binding: Mapping[str, object],
        request: Mapping[str, object],
        classification: str,
        response: Mapping[str, object],
        job_id: str | None = None,
    ) -> str:
        self._attest()
        closed_binding = _base_binding(binding)
        if (
            closed_binding["program_transport_store_id"]
            != self.program_transport_store_id
            or closed_binding["store_instance_id"] != self.store_instance_id
        ):
            raise TransportBoundaryError(
                "successor effect binding names another physical store"
            )
        _validate_program_effect_request(request, binding)
        if classification not in {"SUCCEEDED", "FAILED", "UNKNOWN"}:
            raise TransportBoundaryError("physical effect classification is invalid")
        if not isinstance(response, Mapping):
            raise TransportBoundaryError("physical effect response must be a mapping")
        if job_id is not None:
            _job_id(job_id)
        payload = {
            "schema": _PROGRAM_STORE_SCHEMA,
            "program_transport_store_id": self.program_transport_store_id,
            "store_instance_id": self.store_instance_id,
            "runtime_attestation_id": closed_binding["runtime_attestation_id"],
            "attempt_id": closed_binding["attempt_id"],
            "program_execution_snapshot_id": closed_binding[
                "program_execution_snapshot_id"
            ],
            "effect_intent_id": closed_binding["effect_intent_id"],
            "operation": request["operation"],
            "request": dict(request),
            "request_sha256": _digest(request),
            "effect_classification": classification,
            "response": dict(response),
            "job_id": job_id,
        }
        identity = _identity("program-physical-effect", payload)
        columns = (
            "physical_effect_authority_id", "program_transport_store_id",
            "store_instance_id", "runtime_attestation_id", "attempt_id",
            "program_execution_snapshot_id", "effect_intent_id", "operation",
            "request_sha256", "effect_classification", "job_id",
            "submit_once_key", "payload",
        )
        submit_once_key = (
            _identity(
                "program-submit-once",
                {
                    "attempt_id": closed_binding["attempt_id"],
                    "program_execution_snapshot_id": closed_binding[
                        "program_execution_snapshot_id"
                    ],
                    "effect_intent_id": closed_binding["effect_intent_id"],
                },
            )
            if request["operation"] == "SUBMIT_QSUB_ONCE"
            else None
        )
        values = (
            identity,
            self.program_transport_store_id,
            self.store_instance_id,
            closed_binding["runtime_attestation_id"],
            closed_binding["attempt_id"],
            closed_binding["program_execution_snapshot_id"],
            closed_binding["effect_intent_id"],
            request["operation"],
            payload["request_sha256"],
            classification,
            job_id,
            submit_once_key,
            canonical_bytes(payload),
        )
        self._insert_exact(
            "program_effect_physical_authority", columns, values, identity
        )
        return identity

    def require_matching_effect(
        self,
        *,
        binding: Mapping[str, object],
        request: Mapping[str, object],
        classification: str,
        response: Mapping[str, object],
        job_id: str | None = None,
    ) -> str:
        self._attest()
        closed_binding = _base_binding(binding)
        if (
            closed_binding["program_transport_store_id"]
            != self.program_transport_store_id
            or closed_binding["store_instance_id"] != self.store_instance_id
        ):
            raise TransportBoundaryError(
                "successor effect binding names another physical store"
            )
        _validate_program_effect_request(request, binding)
        payload = {
            "schema": _PROGRAM_STORE_SCHEMA,
            "program_transport_store_id": self.program_transport_store_id,
            "store_instance_id": self.store_instance_id,
            "runtime_attestation_id": closed_binding["runtime_attestation_id"],
            "attempt_id": closed_binding["attempt_id"],
            "program_execution_snapshot_id": closed_binding[
                "program_execution_snapshot_id"
            ],
            "effect_intent_id": closed_binding["effect_intent_id"],
            "operation": request["operation"],
            "request": dict(request),
            "request_sha256": _digest(request),
            "effect_classification": classification,
            "response": dict(response),
            "job_id": job_id,
        }
        identity = _identity("program-physical-effect", payload)
        rows = self._connection.execute(
            "SELECT payload FROM program_effect_physical_authority "
            "WHERE physical_effect_authority_id=?",
            (identity,),
        ).fetchall()
        if len(rows) != 1 or rows[0][0] != canonical_bytes(payload):
            raise TransportBoundaryError(
                "matching successor physical-effect authority is required"
            )
        return identity


def _validate_binding(value: object) -> Mapping[str, object]:
    binding = _exact_keys(value, _BINDING_FIELDS, "successor binding")
    for key in _BINDING_FIELDS:
        _text(binding[key], f"successor binding.{key}")
    canonical_bytes(binding)
    return binding


def _base_binding(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not _BINDING_FIELDS.issubset(value):
        raise TransportBoundaryError("successor request lacks its base binding")
    return _validate_binding({key: value[key] for key in _BINDING_FIELDS})


def _validate_operation_payload(
    operation: str, value: object
) -> Mapping[str, object]:
    if operation == "ALLOCATE_WORKSPACE":
        return _exact_keys(value, set(), "allocate payload")
    if operation == "STAGE_EXACT_FILE":
        payload = _exact_keys(value, _STAGE_FIELDS, "stage payload")
        _portable(payload["portable_name"], "stage portable_name")
        for key in ("artifact_kind", "logical_role", "format"):
            _text(payload[key], f"stage {key}")
        if payload["artifact_kind"] not in {"program-input", "scheduler-script"}:
            raise TransportBoundaryError("stage artifact kind is outside the closed set")
        if not isinstance(payload["sha256"], str) or _SHA256.fullmatch(payload["sha256"]) is None:
            raise TransportBoundaryError("stage sha256 is invalid")
        _positive(payload["size_bytes"], "stage size_bytes")
        return payload
    if operation == "SUBMIT_QSUB_ONCE":
        payload = _exact_keys(
            value,
            {
                "scheduler_portable_name", "scheduler_artifact_authority_id",
                "program_input_artifact_authority_ids",
            },
            "submit payload",
        )
        _portable(payload["scheduler_portable_name"], "scheduler portable_name")
        _text(
            payload["scheduler_artifact_authority_id"],
            "scheduler artifact authority ID",
        )
        input_ids = payload["program_input_artifact_authority_ids"]
        if (
            not isinstance(input_ids, tuple) or not input_ids
            or len(input_ids) != len(set(input_ids))
        ):
            raise TransportBoundaryError("program input authorities are invalid")
        for item in input_ids:
            _text(item, "program input artifact authority ID")
        return payload
    if operation == "QUERY_SCHEDULER":
        payload = _exact_keys(value, {"job_id"}, "scheduler query payload")
        _job_id(payload["job_id"])
        return payload
    if operation == "RECONCILE_SUBMISSION":
        payload = _exact_keys(
            value, {"submit_receipt_id"}, "reconciliation payload"
        )
        _text(payload["submit_receipt_id"], "submit receipt ID")
        return payload
    if operation == "STAT_EXACT_FILE":
        payload = _exact_keys(
            value, {"logical_role", "portable_name", "format"}, "stat payload"
        )
        _text(payload["logical_role"], "output logical role")
        _portable(payload["portable_name"], "output portable name")
        _text(payload["format"], "output format")
        return payload
    payload = _exact_keys(
        value,
        {
            "logical_role", "portable_name", "format", "expected_size_bytes",
            "expected_file_physical_token", "stat_receipt_id",
        },
        "fetch payload",
    )
    _text(payload["logical_role"], "output logical role")
    _portable(payload["portable_name"], "output portable name")
    _text(payload["format"], "output format")
    _nonnegative(payload["expected_size_bytes"], "expected output size")
    _text(payload["expected_file_physical_token"], "output physical token")
    _text(payload["stat_receipt_id"], "stat receipt ID")
    return payload


def _request(
    operation: str, binding: Mapping[str, object], payload: Mapping[str, object]
) -> dict[str, object]:
    if operation not in _OPERATIONS:
        raise TransportBoundaryError("successor operation is outside the closed set")
    expected_binding_fields = set(_BINDING_FIELDS)
    if operation in {"STAGE_EXACT_FILE", "SUBMIT_QSUB_ONCE"}:
        expected_binding_fields.update(_WORKSPACE_AUTHORITY_FIELDS)
    elif operation in {"QUERY_SCHEDULER", "STAT_EXACT_FILE", "FETCH_EXACT_FILE"}:
        expected_binding_fields.update(_JOB_AUTHORITY_FIELDS)
    _exact_keys(binding, expected_binding_fields, "successor request binding")
    for key in expected_binding_fields:
        _text(binding[key], f"successor request binding.{key}")
    closed_payload = _validate_operation_payload(operation, payload)
    request = {
        "protocol": _PROTOCOL, "operation": operation,
        "binding": dict(binding), "payload": dict(closed_payload),
    }
    canonical_bytes(request)
    return request


def _validate_program_effect_request(
    value: object, expected_binding: Mapping[str, object]
) -> Mapping[str, object]:
    request = _exact_keys(
        value, {"protocol", "operation", "binding", "payload"},
        "successor effect request",
    )
    if request["protocol"] != _PROTOCOL or not isinstance(request["operation"], str):
        raise TransportBoundaryError("successor effect protocol is invalid")
    operation = request["operation"]
    if request["binding"] != expected_binding or not isinstance(
        request["payload"], Mapping
    ):
        raise TransportBoundaryError("successor effect binding is not current")
    expected = _request(operation, expected_binding, request["payload"])
    if dict(request) != expected:
        raise TransportBoundaryError("successor effect request does not re-close")
    return request


@dataclass(frozen=True, slots=True)
class _PreparedProgramEffects:
    binding: Mapping[str, object]
    material: tuple[tuple[Mapping[str, object], bytes], ...]
    allocate_request: Mapping[str, object]
    scheduler_portable_name: str

    def assert_closed(self) -> None:
        expected = _prepare_program_effect_requests(self.binding, self.material)
        if expected != self:
            raise TransportBoundaryError("prepared successor requests are stale")


def _prepare_program_effect_requests(
    binding: Mapping[str, object],
    material: tuple[tuple[Mapping[str, object], bytes], ...],
) -> _PreparedProgramEffects:
    """Validate and freeze all static pre-effect request material; call no driver."""

    closed_binding = dict(_validate_binding(binding))
    if not isinstance(material, tuple) or not material:
        raise TransportBoundaryError("successor stage material must be non-empty tuple")
    closed_material: list[tuple[Mapping[str, object], bytes]] = []
    scheduler_names: list[str] = []
    seen_names: set[str] = set()
    for index, item in enumerate(material):
        if not isinstance(item, tuple) or len(item) != 2:
            raise TransportBoundaryError("successor stage material item is malformed")
        payload = _exact_keys(item[0], _STAGE_FIELDS, f"stage material[{index}]")
        content = item[1]
        name = _portable(payload["portable_name"], "stage portable_name")
        for key in ("artifact_kind", "logical_role", "format"):
            _text(payload[key], f"stage {key}")
        if (
            name in seen_names
            or not isinstance(payload["sha256"], str)
            or _SHA256.fullmatch(payload["sha256"]) is None
            or type(content) is not bytes
            or len(content) != _positive(payload["size_bytes"], "stage size_bytes")
            or sha256(content).hexdigest() != payload["sha256"]
        ):
            raise TransportBoundaryError("successor stage material identity is invalid")
        seen_names.add(name)
        if payload["artifact_kind"] == "scheduler-script":
            scheduler_names.append(name)
        elif payload["artifact_kind"] != "program-input":
            raise TransportBoundaryError("successor artifact kind is outside the closed set")
        closed_material.append((dict(payload), content))
    if len(scheduler_names) != 1:
        raise TransportBoundaryError("successor requires exactly one scheduler script")
    allocate = _request("ALLOCATE_WORKSPACE", closed_binding, {})
    placeholder_workspace = {
        "workspace_authority_id": "pre-effect-placeholder",
        "workspace_receipt_id": "pre-effect-placeholder",
        "workspace_physical_token": "pre-effect-placeholder",
    }
    for payload, _content in closed_material:
        _request("STAGE_EXACT_FILE", {**closed_binding, **placeholder_workspace}, payload)
    _request(
        "SUBMIT_QSUB_ONCE", {**closed_binding, **placeholder_workspace},
        {
            "scheduler_portable_name": scheduler_names[0],
            "scheduler_artifact_authority_id": "pre-effect-placeholder",
            "program_input_artifact_authority_ids": ("pre-effect-placeholder",),
        },
    )
    return _PreparedProgramEffects(
        closed_binding, tuple(closed_material), allocate, scheduler_names[0]
    )


@runtime_checkable
class _ProgramEffectDriver(Protocol):
    runtime_qualification: Mapping[str, object]

    def allocate_workspace(self, request: Mapping[str, object]) -> Mapping[str, object]: ...
    def stage_exact_file(self, request: Mapping[str, object], content: bytes) -> Mapping[str, object]: ...
    def submit_qsub_once(self, request: Mapping[str, object]) -> Mapping[str, object]: ...
    def query_scheduler(self, request: Mapping[str, object]) -> Mapping[str, object]: ...
    def stat_exact_file(self, request: Mapping[str, object]) -> Mapping[str, object]: ...
    def fetch_exact_file(self, request: Mapping[str, object]) -> Mapping[str, object]: ...
    def reconcile_submission(self, request: Mapping[str, object]) -> Mapping[str, object]: ...


def _require_driver(driver: object) -> _ProgramEffectDriver:
    if not isinstance(driver, _ProgramEffectDriver):
        raise TransportBoundaryError("successor driver lacks the closed operation seam")
    _runtime_qualification(driver.runtime_qualification)
    return driver


def _call(
    driver_call: object, request: Mapping[str, object], *args: object
) -> Mapping[str, object]:
    before = _digest(request)
    if not callable(driver_call):
        raise TransportBoundaryError("successor driver operation is unavailable")
    result = driver_call(request, *args)
    if before != _digest(request):
        raise _ProgramEffectUnknown("driver mutated an exact successor request")
    if not isinstance(result, Mapping):
        raise _ProgramEffectUnknown("driver returned a malformed response")
    return result


def _job_id(value: object) -> str:
    job_id = _text(value, "job_id")
    if _JOB.fullmatch(job_id) is None:
        raise TransportBoundaryError("successor job ID is invalid")
    return job_id


def _stage_request(
    binding: Mapping[str, object], workspace: Mapping[str, object],
    payload: Mapping[str, object],
) -> Mapping[str, object]:
    return _request("STAGE_EXACT_FILE", {**binding, **workspace}, payload)


def _submit_request(
    binding: Mapping[str, object], workspace: Mapping[str, object], *,
    scheduler_portable_name: str,
    scheduler_artifact_authority_id: str,
    program_input_artifact_authority_ids: tuple[str, ...],
) -> Mapping[str, object]:
    return _request(
        "SUBMIT_QSUB_ONCE", {**binding, **workspace},
        {
            "scheduler_portable_name": scheduler_portable_name,
            "scheduler_artifact_authority_id": scheduler_artifact_authority_id,
            "program_input_artifact_authority_ids": program_input_artifact_authority_ids,
        },
    )


def _scheduler_request(
    binding: Mapping[str, object], *, job_authority_id: str, job_id: str,
) -> Mapping[str, object]:
    return _request(
        "QUERY_SCHEDULER", {**binding, "job_authority_id": job_authority_id},
        {"job_id": job_id},
    )


def _reconciliation_request(
    binding: Mapping[str, object], *, submit_receipt_id: str,
) -> Mapping[str, object]:
    return _request(
        "RECONCILE_SUBMISSION", binding,
        {"submit_receipt_id": submit_receipt_id},
    )


def _stat_request(
    binding: Mapping[str, object], *, job_authority_id: str,
    declaration: Mapping[str, object],
) -> Mapping[str, object]:
    return _request(
        "STAT_EXACT_FILE", {**binding, "job_authority_id": job_authority_id},
        {
            "logical_role": declaration["logical_role"],
            "portable_name": declaration["portable_name"],
            "format": declaration["format"],
        },
    )


def _fetch_request(
    binding: Mapping[str, object], *, job_authority_id: str,
    declaration: Mapping[str, object], announced_size: int,
    file_physical_token: str, stat_receipt_id: str,
) -> Mapping[str, object]:
    return _request(
        "FETCH_EXACT_FILE", {**binding, "job_authority_id": job_authority_id},
        {
            "logical_role": declaration["logical_role"],
            "portable_name": declaration["portable_name"],
            "format": declaration["format"],
            "expected_size_bytes": announced_size,
            "expected_file_physical_token": file_physical_token,
            "stat_receipt_id": stat_receipt_id,
        },
    )


def _workspace_response(value: object, expected_workspace: str) -> Mapping[str, object]:
    response = _exact_keys(
        value, {"remote_workspace", "workspace_physical_token"}, "workspace response"
    )
    if response["remote_workspace"] != expected_workspace:
        raise _ProgramEffectUnknown("allocated workspace differs from snapshot")
    _text(response["workspace_physical_token"], "workspace physical token")
    return response


def _stage_response(
    value: object, payload: Mapping[str, object]
) -> Mapping[str, object]:
    response = _exact_keys(value, set(payload) | {"artifact_physical_token"}, "stage response")
    if any(response[key] != item for key, item in payload.items()):
        raise _ProgramEffectUnknown("staged artifact response drifted")
    _text(response["artifact_physical_token"], "artifact physical token")
    return response


def _submit_response(value: object) -> Mapping[str, object]:
    response = _exact_keys(value, {"job_id"}, "submit response")
    _job_id(response["job_id"])
    return response


def _scheduler_response(
    value: object, expected_job_id: str
) -> Mapping[str, object]:
    response = _exact_keys(value, {"job_id", "state"}, "scheduler response")
    if response["job_id"] != expected_job_id or response["state"] not in _SCHEDULER_STATES:
        raise _ProgramEffectUnknown("scheduler response differs from job authority")
    return response


def _reconciliation_response(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise _ProgramEffectUnknown("reconciliation response is malformed")
    if set(value) == {"outcome"}:
        if value["outcome"] not in {"FAILED", "UNKNOWN"}:
            raise _ProgramEffectUnknown("reconciliation response is malformed")
    elif set(value) == {"outcome", "job_id"}:
        if value["outcome"] != "SUCCEEDED":
            raise _ProgramEffectUnknown("reconciliation response is malformed")
        _job_id(value["job_id"])
    else:
        raise _ProgramEffectUnknown("reconciliation response is malformed")
    return value


def _stat_response(
    value: object, *, name: str, max_size_bytes: int
) -> tuple[Mapping[str, object], int | None]:
    if isinstance(value, Mapping) and set(value) == {"portable_name", "presence"}:
        if value["portable_name"] != name or value["presence"] != "absent":
            raise TransportBoundaryError("output stat response is malformed")
        return value, None
    response = _exact_keys(
        value,
        {"portable_name", "presence", "size_bytes", "file_physical_token"},
        "output stat response",
    )
    size = _nonnegative(response["size_bytes"], "output size")
    if response["portable_name"] != name or response["presence"] != "present" or size > max_size_bytes:
        raise TransportBoundaryError("output stat differs from exact declaration")
    _text(response["file_physical_token"], "output physical token")
    return response, size


def _fetch_response(
    value: object, *, name: str, token: str, announced_size: int,
    max_size_bytes: int,
) -> tuple[Mapping[str, object], bytes, str, int]:
    response = _exact_keys(
        value,
        {"portable_name", "content", "sha256", "size_bytes", "file_physical_token"},
        "output fetch response",
    )
    content = response["content"]
    if type(content) is not bytes:
        raise TransportBoundaryError("fetched output must be immutable bytes")
    digest, size = sha256(content).hexdigest(), len(content)
    if (
        response["portable_name"] != name or response["sha256"] != digest
        or response["size_bytes"] != size or response["file_physical_token"] != token
        or size != announced_size or size > max_size_bytes
    ):
        raise TransportBoundaryError("fetched output differs from exact stat authority")
    return response, content, digest, size


@dataclass(frozen=True, slots=True)
class _ProgramOutputArtifact:
    logical_role: str
    portable_name: str
    format: str
    presence: str
    sha256: str | None
    size_bytes: int | None
    program_execution_snapshot_id: str
    effect_intent_id: str
    job_authority_id: str
    fetch_receipt_id: str | None
    content: bytes | None

    def identity_payload(self) -> dict[str, object]:
        return {
            "logical_role": self.logical_role, "portable_name": self.portable_name,
            "format": self.format, "presence": self.presence,
            "sha256": self.sha256, "size_bytes": self.size_bytes,
            "program_execution_snapshot_id": self.program_execution_snapshot_id,
            "effect_intent_id": self.effect_intent_id,
            "job_authority_id": self.job_authority_id,
            "fetch_receipt_id": self.fetch_receipt_id,
        }


@dataclass(frozen=True, slots=True)
class _ProgramOutputCapture:
    capture_authority_id: str
    program_execution_snapshot_id: str
    effect_intent_id: str
    job_authority_id: str
    artifacts: tuple[_ProgramOutputArtifact, ...]


__all__: tuple[str, ...] = ()
