"""Immutable public records for the frozen v3 Transport boundary."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
import os
from pathlib import Path
import re
import secrets
import sqlite3
import stat
from threading import Lock, RLock
from typing import Final
import weakref

from auto_g16.execution import (
    EffectKind,
    EffectState,
    ExecutionSnapshot,
    ReceiptJournal,
    ServerProfile,
    assert_execution_snapshot_identity,
    resolve_server_profile,
)

from ._canonical import (
    TransportBoundaryError,
    _positive,
    _text,
    canonical_bytes,
    capture_id,
    physical_id,
    scheduler_id,
)


MAX_ARTIFACT_REQUESTS: Final = 4
MAX_FETCH_ARTIFACT_BYTES: Final = 134_217_728
MAX_FETCH_CAPTURE_BYTES: Final = 268_435_456
_PORTABLE_NAME: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_JOB_ID: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_ARTIFACT_KINDS: Final = frozenset({"gaussian-log", "stdout", "stderr"})
_CAPTURE_STATUSES: Final = frozenset(
    {"captured", "capture-in-progress", "capture-interrupted", "capture-error"}
)
_COMPLETENESS: Final = frozenset({"partial", "complete"})
_BINDING_REGISTRY: dict[
    int, tuple[weakref.ReferenceType[ExactRemoteJobBinding], tuple[str, ...]]
] = {}
_BINDING_REGISTRY_LOCK = Lock()


def _timestamp(value: object, field_name: str) -> str:
    _text(value, field_name)
    assert isinstance(value, str)
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError as exc:
        raise TransportBoundaryError(
            f"{field_name} must be exact UTC with six fractional digits"
        ) from exc
    if parsed.strftime("%Y-%m-%dT%H:%M:%S.%fZ") != value:
        raise TransportBoundaryError(
            f"{field_name} must be exact UTC with six fractional digits"
        )
    return value


def _portable_name(value: object, field_name: str) -> str:
    _text(value, field_name)
    assert isinstance(value, str)
    if value in {".", ".."} or _PORTABLE_NAME.fullmatch(value) is None:
        raise TransportBoundaryError(f"{field_name} must be one portable component")
    if any(character in value for character in "*?[]{};$`|&<>!()'\""):
        raise TransportBoundaryError(f"{field_name} contains shell or glob syntax")
    return value


def _binding_payload(binding: ExactRemoteJobBinding) -> dict[str, object]:
    return {
        "transport_store_id": binding.transport_store_id,
        "store_instance_id": binding.store_instance_id,
        "attempt_id": binding.attempt_id,
        "execution_snapshot_id": binding.execution_snapshot_id,
        "submission_intent_id": binding.submission_intent_id,
        "remote_effect_receipt_id": binding.remote_effect_receipt_id,
        "remote_workspace": binding.remote_workspace,
        "job_id": binding.job_id,
    }


def _assert_profile_current(
    snapshot: ExecutionSnapshot, current_profile: ServerProfile
) -> None:
    assert_execution_snapshot_identity(snapshot)
    try:
        current = resolve_server_profile(current_profile)
    except Exception as exc:
        raise TransportBoundaryError("current ServerProfile cannot be resolved") from exc
    frozen = snapshot.resolved_server_profile
    if (
        current != frozen
        or current.resolved_server_profile_id != frozen.resolved_server_profile_id
        or current.effective_config_sha256 != frozen.effective_config_sha256
        or current.semantic_payload() != frozen.semantic_payload()
    ):
        raise TransportBoundaryError("current ServerProfile differs from the exact snapshot")


_APPLICATION_ID: Final = 1_093_879_636
_SCHEMA_VERSION: Final = 1
_TABLES: Final = (
    "transport_meta", "transport_runtime_attestation", "transport_workspace_authority",
    "transport_artifact_authority", "transport_job_authority", "transport_receipt_binding",
)
_DDL: Final = (
    "CREATE TABLE transport_meta(singleton INTEGER PRIMARY KEY CHECK(singleton=1),schema_identity BLOB NOT NULL,transport_store_id TEXT NOT NULL UNIQUE,store_instance_id TEXT NOT NULL UNIQUE,creation_nonce BLOB NOT NULL CHECK(length(creation_nonce)=32),approved_store_root TEXT NOT NULL,approved_store_path TEXT NOT NULL,store_file_identity BLOB NOT NULL,parent_identity_chain BLOB NOT NULL)",
    "CREATE TABLE transport_runtime_attestation(runtime_attestation_id TEXT PRIMARY KEY,schema_version INTEGER NOT NULL CHECK(schema_version=1),transport_store_id TEXT NOT NULL,store_instance_id TEXT NOT NULL,execution_snapshot_id TEXT NOT NULL,resolved_server_profile_id TEXT NOT NULL,effective_config_sha256 TEXT NOT NULL,deployment_manifest_name TEXT NOT NULL,deployment_manifest_sha256 TEXT NOT NULL,deployment_manifest_size_bytes INTEGER NOT NULL,deployment_id TEXT NOT NULL,bootstrap_protocol TEXT NOT NULL,operation_table_sha256 TEXT NOT NULL,operation_table_size_bytes INTEGER NOT NULL,bootstrap_source_name TEXT NOT NULL,bootstrap_source_sha256 TEXT NOT NULL,bootstrap_source_size_bytes INTEGER NOT NULL,payload BLOB NOT NULL)",
    "CREATE TABLE transport_workspace_authority(workspace_authority_id TEXT PRIMARY KEY,schema_version INTEGER NOT NULL CHECK(schema_version=1),transport_store_id TEXT NOT NULL,store_instance_id TEXT NOT NULL,runtime_attestation_id TEXT NOT NULL REFERENCES transport_runtime_attestation(runtime_attestation_id),attempt_id TEXT NOT NULL,execution_snapshot_id TEXT NOT NULL,submission_intent_id TEXT NOT NULL,remote_workspace TEXT NOT NULL,workspace_physical_token BLOB NOT NULL,payload BLOB NOT NULL,UNIQUE(attempt_id,execution_snapshot_id,submission_intent_id,remote_workspace))",
    "CREATE TABLE transport_artifact_authority(artifact_authority_id TEXT PRIMARY KEY,schema_version INTEGER NOT NULL CHECK(schema_version=1),transport_store_id TEXT NOT NULL,store_instance_id TEXT NOT NULL,workspace_authority_id TEXT NOT NULL REFERENCES transport_workspace_authority(workspace_authority_id),runtime_attestation_id TEXT NOT NULL REFERENCES transport_runtime_attestation(runtime_attestation_id),attempt_id TEXT NOT NULL,execution_snapshot_id TEXT NOT NULL,submission_intent_id TEXT NOT NULL,artifact_kind TEXT NOT NULL,logical_name TEXT NOT NULL,remote_relative_name TEXT NOT NULL,sha256 TEXT NOT NULL,size_bytes INTEGER NOT NULL,artifact_physical_token BLOB NOT NULL,payload BLOB NOT NULL,UNIQUE(workspace_authority_id,artifact_kind,logical_name),UNIQUE(workspace_authority_id,remote_relative_name))",
    "CREATE TABLE transport_job_authority(job_authority_id TEXT PRIMARY KEY,schema_version INTEGER NOT NULL CHECK(schema_version=1),transport_store_id TEXT NOT NULL,store_instance_id TEXT NOT NULL,workspace_authority_id TEXT NOT NULL UNIQUE REFERENCES transport_workspace_authority(workspace_authority_id),runtime_attestation_id TEXT NOT NULL REFERENCES transport_runtime_attestation(runtime_attestation_id),attempt_id TEXT NOT NULL,execution_snapshot_id TEXT NOT NULL,submission_intent_id TEXT NOT NULL,job_id TEXT NOT NULL,payload BLOB NOT NULL)",
    "CREATE TABLE transport_receipt_binding(receipt_binding_id TEXT PRIMARY KEY,schema_version INTEGER NOT NULL CHECK(schema_version=1),transport_store_id TEXT NOT NULL,store_instance_id TEXT NOT NULL,job_authority_id TEXT NOT NULL UNIQUE REFERENCES transport_job_authority(job_authority_id),workspace_authority_id TEXT NOT NULL REFERENCES transport_workspace_authority(workspace_authority_id),attempt_id TEXT NOT NULL,execution_snapshot_id TEXT NOT NULL,submission_intent_id TEXT NOT NULL,remote_effect_receipt_id TEXT NOT NULL UNIQUE,job_id TEXT NOT NULL,payload BLOB NOT NULL)",
)
_TRIGGERS: Final = tuple(
    (f"{table}_no_{verb}", f"CREATE TRIGGER {table}_no_{verb} BEFORE {verb.upper()} ON {table} BEGIN SELECT RAISE(ABORT,'append-only'); END")
    for table in _TABLES for verb in ("update", "delete")
)
_SCHEMA_IDENTITY: Final = canonical_bytes([*_DDL, *[ddl for _name, ddl in _TRIGGERS]])


def _lexical_store_path(path: str | os.PathLike[str], root: str | os.PathLike[str]) -> tuple[str, str]:
    raw_path, raw_root = os.fspath(path), os.fspath(root)
    if not isinstance(raw_path, str) or not isinstance(raw_root, str):
        raise TransportBoundaryError("TransportStore paths must be strings")
    absolute_path, absolute_root = os.path.abspath(raw_path), os.path.abspath(raw_root)
    if os.path.commonpath((absolute_path, absolute_root)) != absolute_root or absolute_path == absolute_root:
        raise TransportBoundaryError("TransportStore path must be a strict root descendant")
    return absolute_path, absolute_root


def _open_parent_chain(path: str, root: str) -> tuple[list[int], list[list[object]], str]:
    relative_parent = os.path.relpath(os.path.dirname(path), root)
    components = [] if relative_parent == "." else relative_parent.split(os.sep)
    if any(component in {"", ".", ".."} for component in components):
        raise TransportBoundaryError("TransportStore parent chain is invalid")
    flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    current = root
    descriptors: list[int] = []
    chain: list[list[object]] = []
    try:
        descriptor = os.open(root, flags)
        descriptors.append(descriptor)
        opened = os.fstat(descriptor)
        named = os.stat(root, follow_symlinks=False)
        if not stat.S_ISDIR(opened.st_mode) or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino):
            raise TransportBoundaryError("TransportStore approved root is unsafe")
        chain.append([current, opened.st_dev, opened.st_ino, "directory"])
        for component in components:
            current = os.path.join(current, component)
            descriptor = os.open(component, flags, dir_fd=descriptors[-1])
            descriptors.append(descriptor)
            opened = os.fstat(descriptor)
            named = os.stat(component, dir_fd=descriptors[-2], follow_symlinks=False)
            if not stat.S_ISDIR(opened.st_mode) or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino):
                raise TransportBoundaryError("TransportStore parent changed during traversal")
            chain.append([current, opened.st_dev, opened.st_ino, "directory"])
        return descriptors, chain, os.path.basename(path)
    except (OSError, TransportBoundaryError) as exc:
        for descriptor in reversed(descriptors):
            os.close(descriptor)
        if isinstance(exc, TransportBoundaryError):
            raise
        raise TransportBoundaryError("TransportStore parent is unavailable") from exc


def _path_evidence(path: str, root: str) -> tuple[list[object], list[list[object]]]:
    descriptors, chain, basename = _open_parent_chain(path, root)
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
        terminal = os.open(basename, flags, dir_fd=descriptors[-1])
        try:
            opened = os.fstat(terminal)
            named = os.stat(basename, dir_fd=descriptors[-1], follow_symlinks=False)
            if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino):
                raise TransportBoundaryError("TransportStore terminal changed during open")
            return ["posix-file", opened.st_dev, opened.st_ino, "regular"], chain
        finally:
            os.close(terminal)
    except OSError as exc:
        raise TransportBoundaryError("TransportStore file is unavailable") from exc
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


class TransportStore:
    """Transport-owned append-only physical authority database."""

    def __init__(self) -> None:
        raise TypeError("use TransportStore.create_new/open_existing")

    @classmethod
    def create_new(cls, path: str | os.PathLike[str], *, approved_root: str | os.PathLike[str]) -> TransportStore:
        absolute_path, absolute_root = _lexical_store_path(path, approved_root)
        if not os.path.isdir(absolute_root):
            raise TransportBoundaryError("approved TransportStore root must already exist")
        descriptors, _chain, basename = _open_parent_chain(absolute_path, absolute_root)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
        try:
            descriptor = os.open(basename, flags, 0o600, dir_fd=descriptors[-1])
        except OSError as exc:
            raise TransportBoundaryError("TransportStore create-new reservation failed") from exc
        finally:
            for parent_descriptor in reversed(descriptors):
                os.close(parent_descriptor)
        os.close(descriptor)
        try:
            value = cls._open(absolute_path, absolute_root)
            value._create_schema()
            return value
        except Exception:
            # The reserved empty file is intentionally left as failed evidence.
            if "value" in locals():
                value.close()
            raise

    @classmethod
    def open_existing(cls, path: str | os.PathLike[str], *, approved_root: str | os.PathLike[str]) -> TransportStore:
        absolute_path, absolute_root = _lexical_store_path(path, approved_root)
        value = cls._open(absolute_path, absolute_root)
        try:
            value._attest()
        except Exception:
            value.close()
            raise
        return value

    @classmethod
    def _open(cls, path: str, root: str) -> TransportStore:
        file_identity, parent_chain = _path_evidence(path, root)
        value = object.__new__(cls)
        value._path, value._root = path, root
        value._file_identity, value._parent_chain = file_identity, parent_chain
        value._connection = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        value._connection.execute("PRAGMA foreign_keys=ON")
        value._connection.execute("PRAGMA trusted_schema=OFF")
        value._connection.execute("PRAGMA synchronous=FULL")
        value._lock, value._closed = RLock(), False
        post_file, post_chain = _path_evidence(path, root)
        if post_file != file_identity or post_chain != parent_chain:
            value._connection.close()
            raise TransportBoundaryError("TransportStore changed across SQLite open")
        return value

    def _create_schema(self) -> None:
        nonce = secrets.token_bytes(32)
        store_payload = ["auto-g16-transport/store", 1, self._root, self._path]
        store_id = physical_id("transport-store", store_payload)
        instance_payload = ["auto-g16-transport/store-instance", 1, store_id, nonce, self._root, self._path, self._file_identity, self._parent_chain]
        instance_id = physical_id("store-instance", instance_payload)
        with self._lock:
            self._connection.execute(f"PRAGMA application_id={_APPLICATION_ID}")
            self._connection.execute(f"PRAGMA user_version={_SCHEMA_VERSION}")
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                for statement in _DDL:
                    self._connection.execute(statement)
                for _name, statement in _TRIGGERS:
                    self._connection.execute(statement)
                self._connection.execute(
                    "INSERT INTO transport_meta VALUES(1,?,?,?,?,?,?,?,?)",
                    (_SCHEMA_IDENTITY, store_id, instance_id, nonce, self._root, self._path, canonical_bytes(self._file_identity), canonical_bytes(self._parent_chain)),
                )
                self._connection.execute("COMMIT")
            except Exception:
                self._connection.execute("ROLLBACK")
                raise
        self._attest()

    def _attest(self) -> None:
        if getattr(self, "_closed", True):
            raise TransportBoundaryError("TransportStore is closed")
        file_identity, parent_chain = _path_evidence(self._path, self._root)
        if file_identity != self._file_identity or parent_chain != self._parent_chain:
            raise TransportBoundaryError("TransportStore physical identity drifted")
        app = self._connection.execute("PRAGMA application_id").fetchone()[0]
        version = self._connection.execute("PRAGMA user_version").fetchone()[0]
        foreign_keys = self._connection.execute("PRAGMA foreign_keys").fetchone()[0]
        trusted_schema = self._connection.execute("PRAGMA trusted_schema").fetchone()[0]
        synchronous = self._connection.execute("PRAGMA synchronous").fetchone()[0]
        if app != _APPLICATION_ID or version != _SCHEMA_VERSION or foreign_keys != 1 or trusted_schema != 0 or synchronous != 2:
            raise TransportBoundaryError("TransportStore schema version drifted")
        definitions = {row[0]: row[1] for row in self._connection.execute("SELECT name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'")}
        expected = {**dict(zip(_TABLES, _DDL)), **dict(_TRIGGERS)}
        if definitions != expected:
            raise TransportBoundaryError("TransportStore object inventory drifted")
        row = self._connection.execute("SELECT * FROM transport_meta").fetchall()
        if len(row) != 1:
            raise TransportBoundaryError("TransportStore meta authority drifted")
        meta=row[0]
        expected_store=physical_id("transport-store",["auto-g16-transport/store",1,self._root,self._path])
        expected_instance=physical_id("store-instance",["auto-g16-transport/store-instance",1,expected_store,meta[4],self._root,self._path,self._file_identity,self._parent_chain]) if type(meta[4]) is bytes and len(meta[4])==32 else None
        if meta[0] != 1 or meta[1] != _SCHEMA_IDENTITY or meta[2]!=expected_store or meta[3]!=expected_instance or meta[5] != self._root or meta[6] != self._path or meta[7] != canonical_bytes(self._file_identity) or meta[8] != canonical_bytes(self._parent_chain):
            raise TransportBoundaryError("TransportStore meta authority drifted")
        self.transport_store_id, self.store_instance_id = meta[2], meta[3]

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._connection.close()
                self._closed = True

    def _insert(self, table: str, columns: tuple[str, ...], values: tuple[object, ...], identity: str, payload: bytes) -> None:
        with self._lock:
            self._attest()
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                self._attest()
                try:
                    marks = ",".join("?" for _ in values)
                    self._connection.execute(f"INSERT INTO {table}({','.join(columns)}) VALUES({marks})", values)
                except sqlite3.IntegrityError:
                    row = self._connection.execute(f"SELECT {','.join(columns)} FROM {table} WHERE {columns[0]}=?", (identity,)).fetchone()
                    if row is None or tuple(row) != values:
                        raise TransportBoundaryError(f"conflicting {table} authority")
                row = self._connection.execute(f"SELECT {','.join(columns)} FROM {table} WHERE {columns[0]}=?", (identity,)).fetchall()
                if len(row) != 1 or tuple(row[0]) != values or row[0][-1] != payload:
                    raise TransportBoundaryError(f"{table} append/replay failed")
                self._attest()
                self._connection.execute("COMMIT")
            except Exception:
                self._connection.execute("ROLLBACK")
                raise
            self._attest()

    def _read_rows(self, query: str, parameters: tuple[object, ...]) -> list[tuple[object, ...]]:
        with self._lock:
            self._attest()
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                self._attest()
                rows = self._connection.execute(query, parameters).fetchall()
                self._attest()
                self._connection.execute("COMMIT")
            except Exception:
                self._connection.execute("ROLLBACK")
                raise
            self._attest()
            return rows

    def _runtime(self, snapshot: ExecutionSnapshot, authority: object) -> dict[str, object]:
        from ._bridge import _BOOTSTRAP_SOURCE_NAME
        from ._driver import _MANIFEST_NAME, _OPERATION_TABLE_SHA256, _OPERATION_TABLE_BYTES
        manifest = authority.manifest
        payload_value = ["auto-g16-transport/runtime-attestation",1,self.transport_store_id,self.store_instance_id,snapshot.execution_snapshot_id,authority.resolved_server_profile_id,authority.effective_config_sha256,_MANIFEST_NAME,manifest.sha256,manifest.size_bytes,manifest.deployment_id,manifest.bootstrap_protocol,_OPERATION_TABLE_SHA256,len(_OPERATION_TABLE_BYTES),_BOOTSTRAP_SOURCE_NAME,authority.bootstrap_source_sha256,authority.bootstrap_source_size_bytes]
        payload = canonical_bytes(payload_value); identity = physical_id("runtime-attestation", payload_value)
        columns=("runtime_attestation_id","schema_version","transport_store_id","store_instance_id","execution_snapshot_id","resolved_server_profile_id","effective_config_sha256","deployment_manifest_name","deployment_manifest_sha256","deployment_manifest_size_bytes","deployment_id","bootstrap_protocol","operation_table_sha256","operation_table_size_bytes","bootstrap_source_name","bootstrap_source_sha256","bootstrap_source_size_bytes","payload")
        values=(identity,1,self.transport_store_id,self.store_instance_id,snapshot.execution_snapshot_id,authority.resolved_server_profile_id,authority.effective_config_sha256,_MANIFEST_NAME,manifest.sha256,manifest.size_bytes,manifest.deployment_id,manifest.bootstrap_protocol,_OPERATION_TABLE_SHA256,len(_OPERATION_TABLE_BYTES),_BOOTSTRAP_SOURCE_NAME,authority.bootstrap_source_sha256,authority.bootstrap_source_size_bytes,payload)
        self._insert("transport_runtime_attestation",columns,values,identity,payload)
        return {"runtime_attestation_id":identity,"transport_store_id":self.transport_store_id,"store_instance_id":self.store_instance_id}

    def _workspace(self, snapshot: ExecutionSnapshot) -> dict[str, object]:
        rows=self._read_rows("SELECT workspace_authority_id,schema_version,transport_store_id,store_instance_id,runtime_attestation_id,attempt_id,execution_snapshot_id,submission_intent_id,remote_workspace,workspace_physical_token,payload FROM transport_workspace_authority WHERE attempt_id=? AND execution_snapshot_id=? AND submission_intent_id=? AND remote_workspace=?",(snapshot.attempt_id,snapshot.execution_snapshot_id,snapshot.submission_intent_id,snapshot.workspace_binding.remote_attempt_dir))
        if len(rows)!=1: raise TransportBoundaryError("exact workspace authority is unavailable")
        row=rows[0]; name=["auto-g16-transport/workspace-physical",1,self.transport_store_id,self.store_instance_id,row[4],snapshot.attempt_id,snapshot.execution_snapshot_id,snapshot.submission_intent_id,snapshot.workspace_binding.remote_attempt_dir,row[9]]; payload=canonical_bytes(name)
        if row!=(physical_id("workspace-physical",name),1,self.transport_store_id,self.store_instance_id,row[4],snapshot.attempt_id,snapshot.execution_snapshot_id,snapshot.submission_intent_id,snapshot.workspace_binding.remote_attempt_dir,row[9],payload): raise TransportBoundaryError("workspace authority row is malformed")
        return {"workspace_authority_id":row[0],"runtime_attestation_id":row[4],"workspace_physical_token":row[9]}

    def _record_workspace(self,snapshot:ExecutionSnapshot,runtime_id:str,token:bytes)->dict[str,object]:
        if type(token) is not bytes or not 1<=len(token)<=4096: raise TransportBoundaryError("workspace physical token is invalid")
        name=["auto-g16-transport/workspace-physical",1,self.transport_store_id,self.store_instance_id,runtime_id,snapshot.attempt_id,snapshot.execution_snapshot_id,snapshot.submission_intent_id,snapshot.workspace_binding.remote_attempt_dir,token]; payload=canonical_bytes(name); identity=physical_id("workspace-physical",name)
        columns=("workspace_authority_id","schema_version","transport_store_id","store_instance_id","runtime_attestation_id","attempt_id","execution_snapshot_id","submission_intent_id","remote_workspace","workspace_physical_token","payload")
        self._insert("transport_workspace_authority",columns,(identity,1,self.transport_store_id,self.store_instance_id,runtime_id,snapshot.attempt_id,snapshot.execution_snapshot_id,snapshot.submission_intent_id,snapshot.workspace_binding.remote_attempt_dir,token,payload),identity,payload)
        return self._workspace(snapshot)

    def _artifact(self,workspace_id:str,kind:str)->dict[str,object]:
        rows=self._read_rows("SELECT artifact_authority_id,schema_version,transport_store_id,store_instance_id,workspace_authority_id,runtime_attestation_id,attempt_id,execution_snapshot_id,submission_intent_id,artifact_kind,logical_name,remote_relative_name,sha256,size_bytes,artifact_physical_token,payload FROM transport_artifact_authority WHERE workspace_authority_id=? AND artifact_kind=?",(workspace_id,kind))
        if len(rows)!=1: raise TransportBoundaryError("exact staged artifact authority is unavailable")
        row=rows[0]; name=["auto-g16-transport/artifact-physical",1,self.transport_store_id,self.store_instance_id,*row[4:15]]; payload=canonical_bytes(name)
        if row!=(physical_id("artifact-physical",name),1,self.transport_store_id,self.store_instance_id,*row[4:15],payload): raise TransportBoundaryError("artifact authority row is malformed")
        return dict(zip(("artifact_authority_id","logical_name","remote_relative_name","sha256","size_bytes","artifact_physical_token"),(row[0],row[10],row[11],row[12],row[13],row[14])))

    def _record_artifact(self,snapshot:ExecutionSnapshot,runtime_id:str,workspace_id:str,*,kind:str,logical_name:str,digest:str,size:int,token:bytes)->dict[str,object]:
        if kind not in {"prepared-input","pbs-template"} or type(token) is not bytes or not 1<=len(token)<=4096: raise TransportBoundaryError("artifact authority is invalid")
        name=["auto-g16-transport/artifact-physical",1,self.transport_store_id,self.store_instance_id,workspace_id,runtime_id,snapshot.attempt_id,snapshot.execution_snapshot_id,snapshot.submission_intent_id,kind,logical_name,logical_name,digest,size,token]; payload=canonical_bytes(name); identity=physical_id("artifact-physical",name)
        columns=("artifact_authority_id","schema_version","transport_store_id","store_instance_id","workspace_authority_id","runtime_attestation_id","attempt_id","execution_snapshot_id","submission_intent_id","artifact_kind","logical_name","remote_relative_name","sha256","size_bytes","artifact_physical_token","payload")
        self._insert("transport_artifact_authority",columns,(identity,1,self.transport_store_id,self.store_instance_id,workspace_id,runtime_id,snapshot.attempt_id,snapshot.execution_snapshot_id,snapshot.submission_intent_id,kind,logical_name,logical_name,digest,size,token,payload),identity,payload)
        return self._artifact(workspace_id,kind)

    def _record_job(self,snapshot:ExecutionSnapshot,runtime_id:str,workspace_id:str,job_id:str)->dict[str,object]:
        name=["auto-g16-transport/job-physical",1,self.transport_store_id,self.store_instance_id,workspace_id,runtime_id,snapshot.attempt_id,snapshot.execution_snapshot_id,snapshot.submission_intent_id,job_id]; payload=canonical_bytes(name); identity=physical_id("job-physical",name)
        columns=("job_authority_id","schema_version","transport_store_id","store_instance_id","workspace_authority_id","runtime_attestation_id","attempt_id","execution_snapshot_id","submission_intent_id","job_id","payload")
        self._insert("transport_job_authority",columns,(identity,1,self.transport_store_id,self.store_instance_id,workspace_id,runtime_id,snapshot.attempt_id,snapshot.execution_snapshot_id,snapshot.submission_intent_id,job_id,payload),identity,payload)
        return {"job_authority_id":identity,"job_id":job_id}

    def _job(self,snapshot:ExecutionSnapshot)->dict[str,object]:
        workspace=self._workspace(snapshot); rows=self._read_rows("SELECT job_authority_id,schema_version,transport_store_id,store_instance_id,workspace_authority_id,runtime_attestation_id,attempt_id,execution_snapshot_id,submission_intent_id,job_id,payload FROM transport_job_authority WHERE workspace_authority_id=?",(workspace["workspace_authority_id"],))
        if len(rows)!=1: raise TransportBoundaryError("exact job authority is unavailable")
        row=rows[0]; name=["auto-g16-transport/job-physical",1,self.transport_store_id,self.store_instance_id,*row[4:10]]; payload=canonical_bytes(name)
        if row!=(physical_id("job-physical",name),1,self.transport_store_id,self.store_instance_id,*row[4:10],payload): raise TransportBoundaryError("job authority row is malformed")
        return {**workspace,"job_authority_id":row[0],"runtime_attestation_id":row[5],"job_id":row[9]}

    def _record_receipt(self,snapshot:ExecutionSnapshot,receipt:object)->dict[str,object]:
        job=self._job(snapshot)
        if receipt.job_id!=job["job_id"] or receipt.attempt_id!=snapshot.attempt_id or receipt.execution_snapshot_id!=snapshot.execution_snapshot_id or receipt.submission_intent_id!=snapshot.submission_intent_id: raise TransportBoundaryError("receipt differs from stored job authority")
        name=["auto-g16-transport/receipt-binding",1,self.transport_store_id,self.store_instance_id,job["job_authority_id"],job["workspace_authority_id"],snapshot.attempt_id,snapshot.execution_snapshot_id,snapshot.submission_intent_id,receipt.remote_effect_receipt_id,receipt.job_id]; payload=canonical_bytes(name); identity=physical_id("receipt-binding",name)
        columns=("receipt_binding_id","schema_version","transport_store_id","store_instance_id","job_authority_id","workspace_authority_id","attempt_id","execution_snapshot_id","submission_intent_id","remote_effect_receipt_id","job_id","payload")
        self._insert("transport_receipt_binding",columns,(identity,1,self.transport_store_id,self.store_instance_id,job["job_authority_id"],job["workspace_authority_id"],snapshot.attempt_id,snapshot.execution_snapshot_id,snapshot.submission_intent_id,receipt.remote_effect_receipt_id,receipt.job_id,payload),identity,payload)
        return {**job,"receipt_binding_id":identity,"remote_effect_receipt_id":receipt.remote_effect_receipt_id}

    def _receipt(self,snapshot:ExecutionSnapshot,receipt_id:str)->dict[str,object]:
        rows=self._read_rows("SELECT receipt_binding_id,schema_version,transport_store_id,store_instance_id,job_authority_id,workspace_authority_id,attempt_id,execution_snapshot_id,submission_intent_id,remote_effect_receipt_id,job_id,payload FROM transport_receipt_binding WHERE remote_effect_receipt_id=? AND attempt_id=? AND execution_snapshot_id=? AND submission_intent_id=?",(receipt_id,snapshot.attempt_id,snapshot.execution_snapshot_id,snapshot.submission_intent_id))
        if len(rows)!=1: raise TransportBoundaryError("exact receipt binding is unavailable")
        workspace=self._workspace(snapshot)
        row=rows[0]; name=["auto-g16-transport/receipt-binding",1,self.transport_store_id,self.store_instance_id,*row[4:11]]; payload=canonical_bytes(name)
        if row!=(physical_id("receipt-binding",name),1,self.transport_store_id,self.store_instance_id,*row[4:11],payload) or row[5]!=workspace["workspace_authority_id"]: raise TransportBoundaryError("receipt authority row is malformed")
        return {**workspace,"receipt_binding_id":row[0],"job_authority_id":row[4],"job_id":row[10],"remote_effect_receipt_id":receipt_id}


@dataclass(frozen=True, slots=True, weakref_slot=True, kw_only=True, init=False)
class ExactRemoteJobBinding:
    transport_store_id: str
    store_instance_id: str
    attempt_id: str
    execution_snapshot_id: str
    submission_intent_id: str
    remote_effect_receipt_id: str
    remote_workspace: str
    job_id: str

    def __init__(self) -> None:
        raise TypeError("ExactRemoteJobBinding requires persisted receipt authority")

    @classmethod
    def from_persisted_receipt(
        cls,
        snapshot: ExecutionSnapshot,
        journal: ReceiptJournal,
        *,
        remote_effect_receipt_id: str,
        current_profile: ServerProfile,
        transport_store: TransportStore,
    ) -> ExactRemoteJobBinding:
        if not isinstance(snapshot, ExecutionSnapshot):
            raise TransportBoundaryError("snapshot must be an ExecutionSnapshot")
        if type(journal) is not ReceiptJournal:
            raise TransportBoundaryError("journal must be a public ReceiptJournal")
        if not isinstance(transport_store, TransportStore):
            raise TransportBoundaryError("transport_store must be a TransportStore")
        _text(remote_effect_receipt_id, "remote_effect_receipt_id")
        try:
            _assert_profile_current(snapshot, current_profile)
            receipts = journal.receipts_for_attempt(snapshot.attempt_id)
        except TransportBoundaryError:
            raise
        except Exception as exc:
            raise TransportBoundaryError("persisted receipt journal is malformed") from exc
        selected = tuple(
            receipt
            for receipt in receipts
            if receipt.remote_effect_receipt_id == remote_effect_receipt_id
        )
        if len(selected) != 1:
            raise TransportBoundaryError("exactly one persisted receipt ID is required")
        receipt = selected[0]
        if receipt.effect_kind not in {
            EffectKind.SUBMISSION,
            EffectKind.SUBMISSION_RECONCILIATION,
        } or receipt.effect_state is not EffectState.CONFIRMED_EFFECT:
            raise TransportBoundaryError("receipt does not confirm submission effect")
        if (
            receipt.attempt_id != snapshot.attempt_id
            or receipt.execution_snapshot_id != snapshot.execution_snapshot_id
            or receipt.submission_intent_id != snapshot.submission_intent_id
            or receipt.remote_workspace != snapshot.workspace_binding.remote_attempt_dir
            or not isinstance(receipt.job_id, str)
            or _JOB_ID.fullmatch(receipt.job_id) is None
        ):
            raise TransportBoundaryError("persisted receipt does not bind the exact remote job")
        value = object.__new__(cls)
        stored = transport_store._record_receipt(snapshot, receipt)
        object.__setattr__(value, "transport_store_id", transport_store.transport_store_id)
        object.__setattr__(value, "store_instance_id", transport_store.store_instance_id)
        object.__setattr__(value, "attempt_id", snapshot.attempt_id)
        object.__setattr__(value, "execution_snapshot_id", snapshot.execution_snapshot_id)
        object.__setattr__(value, "submission_intent_id", snapshot.submission_intent_id)
        object.__setattr__(value, "remote_effect_receipt_id", remote_effect_receipt_id)
        object.__setattr__(value, "remote_workspace", receipt.remote_workspace)
        object.__setattr__(value, "job_id", receipt.job_id)
        if stored["job_id"] != receipt.job_id:
            raise TransportBoundaryError("TransportStore job differs from receipt")
        marker = tuple(str(item) for item in _binding_payload(value).values())
        identity = id(value)

        def discard(reference: weakref.ReferenceType[ExactRemoteJobBinding]) -> None:
            with _BINDING_REGISTRY_LOCK:
                registered = _BINDING_REGISTRY.get(identity)
                if registered is not None and registered[0] is reference:
                    _BINDING_REGISTRY.pop(identity, None)

        reference = weakref.ref(value, discard)
        with _BINDING_REGISTRY_LOCK:
            _BINDING_REGISTRY[identity] = (reference, marker)
        return value


def _assert_persisted_binding(binding: ExactRemoteJobBinding) -> None:
    marker = tuple(str(item) for item in _binding_payload(binding).values())
    with _BINDING_REGISTRY_LOCK:
        registered = _BINDING_REGISTRY.get(id(binding))
    if (
        registered is None
        or registered[0]() is not binding
        or registered[1] != marker
    ):
        raise TransportBoundaryError("remote job binding lacks persisted journal authority")


def _assert_binding_matches_snapshot(
    snapshot: ExecutionSnapshot,
    binding: ExactRemoteJobBinding,
    current_profile: ServerProfile,
) -> None:
    if not isinstance(binding, ExactRemoteJobBinding):
        raise TransportBoundaryError("binding must be persisted exact job authority")
    _assert_persisted_binding(binding)
    _assert_profile_current(snapshot, current_profile)
    if (
        binding.attempt_id != snapshot.attempt_id
        or binding.execution_snapshot_id != snapshot.execution_snapshot_id
        or binding.submission_intent_id != snapshot.submission_intent_id
        or binding.remote_workspace != snapshot.workspace_binding.remote_attempt_dir
    ):
        raise TransportBoundaryError("remote job binding differs from the current snapshot")


@dataclass(frozen=True, slots=True, kw_only=True, init=False)
class SchedulerReadEvidence:
    binding: ExactRemoteJobBinding
    source_identity: str
    observed_at_utc: str
    freshness: str
    state: str
    evidence_sha256: str
    evidence_size_bytes: int
    schema_version: int = field(init=False, default=1)
    source_kind: str = field(init=False, default="scheduler")
    progress_position: None = field(init=False, default=None)

    def __init__(self) -> None:
        raise TypeError("SchedulerReadEvidence is created only by scheduler acquisition")

    @classmethod
    def _from_classified(
        cls,
        *,
        binding: ExactRemoteJobBinding,
        observed_at_utc: str,
        freshness: str,
        state: str,
        evidence_sha256: str,
        evidence_size_bytes: int,
    ) -> SchedulerReadEvidence:
        _timestamp(observed_at_utc, "observed_at_utc")
        if freshness not in {"fresh", "unknown"}:
            raise TransportBoundaryError("new scheduler evidence has invalid freshness")
        if state not in {
            "queued",
            "running",
            "held",
            "exiting",
            "terminal",
            "absent",
            "unknown",
        }:
            raise TransportBoundaryError("scheduler evidence has invalid state")
        if freshness == "unknown" and state != "unknown":
            raise TransportBoundaryError("uncertain scheduler acquisition must remain unknown")
        if len(evidence_sha256) != 64 or any(
            character not in "0123456789abcdef" for character in evidence_sha256
        ):
            raise TransportBoundaryError("evidence_sha256 must be a lowercase digest")
        if isinstance(evidence_size_bytes, bool) or not isinstance(evidence_size_bytes, int) or evidence_size_bytes < 0:
            raise TransportBoundaryError("evidence_size_bytes must be a non-negative integer")
        name = [
            "auto-g16-transport/scheduler-read",
            1,
            _binding_payload(binding),
            observed_at_utc,
            freshness,
            state,
            evidence_sha256,
            evidence_size_bytes,
        ]
        value = object.__new__(cls)
        object.__setattr__(value, "binding", binding)
        object.__setattr__(value, "source_identity", scheduler_id(name))
        object.__setattr__(value, "observed_at_utc", observed_at_utc)
        object.__setattr__(value, "freshness", freshness)
        object.__setattr__(value, "state", state)
        object.__setattr__(value, "evidence_sha256", evidence_sha256)
        object.__setattr__(value, "evidence_size_bytes", evidence_size_bytes)
        object.__setattr__(value, "schema_version", 1)
        object.__setattr__(value, "source_kind", "scheduler")
        object.__setattr__(value, "progress_position", None)
        return value


@dataclass(frozen=True, slots=True, kw_only=True)
class ExactArtifactRequest:
    artifact_kind: str
    logical_name: str
    remote_relative_name: str
    required: bool

    def __post_init__(self) -> None:
        if self.artifact_kind not in _ARTIFACT_KINDS:
            raise TransportBoundaryError("artifact_kind is outside the v1 allowlist")
        _portable_name(self.logical_name, "logical_name")
        _portable_name(self.remote_relative_name, "remote_relative_name")
        if type(self.required) is not bool:
            raise TransportBoundaryError("required must be a boolean")


def _request_payload(request: ExactArtifactRequest) -> dict[str, object]:
    return {
        "artifact_kind": request.artifact_kind,
        "logical_name": request.logical_name,
        "remote_relative_name": request.remote_relative_name,
        "required": request.required,
    }


@dataclass(frozen=True, slots=True, kw_only=True)
class FetchedArtifact:
    request: ExactArtifactRequest
    content: bytes
    sha256: str = field(init=False)
    size_bytes: int = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.request, ExactArtifactRequest):
            raise TransportBoundaryError("request must be an ExactArtifactRequest")
        if type(self.content) is not bytes:
            raise TransportBoundaryError("fetched content must be immutable bytes")
        if len(self.content) > MAX_FETCH_ARTIFACT_BYTES:
            raise TransportBoundaryError("fetched artifact exceeds its byte cap")
        object.__setattr__(self, "sha256", sha256(self.content).hexdigest())
        object.__setattr__(self, "size_bytes", len(self.content))


def _artifact_metadata(artifact: FetchedArtifact) -> dict[str, object]:
    return {
        "artifact_kind": artifact.request.artifact_kind,
        "logical_name": artifact.request.logical_name,
        "sha256": artifact.sha256,
        "size_bytes": artifact.size_bytes,
    }


def _validate_requests(requests: tuple[ExactArtifactRequest, ...]) -> None:
    if not isinstance(requests, tuple) or not requests or len(requests) > MAX_ARTIFACT_REQUESTS:
        raise TransportBoundaryError("requests must be a finite non-empty tuple of at most four")
    if any(not isinstance(item, ExactArtifactRequest) for item in requests):
        raise TransportBoundaryError("requests contain an invalid item")
    logical_keys = tuple((item.artifact_kind, item.logical_name) for item in requests)
    remote_names = tuple(item.remote_relative_name for item in requests)
    if len(set(logical_keys)) != len(logical_keys) or len(set(remote_names)) != len(remote_names):
        raise TransportBoundaryError("requests contain duplicate authority names")


@dataclass(frozen=True, slots=True, kw_only=True)
class FetchedOutputCapture:
    binding: ExactRemoteJobBinding
    input_binding_observation_id: str
    capture_source_id: str = field(init=False)
    capture_sequence: int
    capture_status: str
    capture_completeness: str
    requests: tuple[ExactArtifactRequest, ...]
    artifacts: tuple[FetchedArtifact, ...]
    missing_requests: tuple[ExactArtifactRequest, ...]
    capture_manifest_sha256: str = field(init=False)
    captured_at_utc: str
    schema_version: int = field(init=False, default=1)

    def __post_init__(self) -> None:
        if not isinstance(self.binding, ExactRemoteJobBinding):
            raise TransportBoundaryError("binding must be an ExactRemoteJobBinding")
        _assert_persisted_binding(self.binding)
        _text(self.input_binding_observation_id, "input_binding_observation_id")
        _positive(self.capture_sequence, "capture_sequence")
        if self.capture_status not in _CAPTURE_STATUSES:
            raise TransportBoundaryError("capture_status is outside the v1 vocabulary")
        if self.capture_completeness not in _COMPLETENESS:
            raise TransportBoundaryError("capture_completeness is outside the v1 vocabulary")
        _timestamp(self.captured_at_utc, "captured_at_utc")
        _validate_requests(self.requests)
        if not isinstance(self.artifacts, tuple) or not self.artifacts or any(
            not isinstance(item, FetchedArtifact) for item in self.artifacts
        ):
            raise TransportBoundaryError("artifacts must be a non-empty tuple")
        if not isinstance(self.missing_requests, tuple) or any(
            not isinstance(item, ExactArtifactRequest) for item in self.missing_requests
        ):
            raise TransportBoundaryError("missing_requests must be a request tuple")
        successful = tuple(artifact.request for artifact in self.artifacts)
        if successful != self.requests[: len(successful)]:
            raise TransportBoundaryError("artifacts are not the exact request prefix")
        if self.missing_requests != self.requests[len(successful) :]:
            raise TransportBoundaryError("missing requests are not the exact request suffix")
        if sum(artifact.size_bytes for artifact in self.artifacts) > MAX_FETCH_CAPTURE_BYTES:
            raise TransportBoundaryError("capture exceeds its aggregate byte cap")
        if self.capture_completeness == "complete":
            if (
                self.capture_status != "captured"
                or self.missing_requests
                or len(self.artifacts) != len(self.requests)
            ):
                raise TransportBoundaryError("complete capture has an invalid partition")
        elif not self.missing_requests or len(self.artifacts) >= len(self.requests):
            raise TransportBoundaryError("partial capture requires a non-empty exact suffix")
        if self.capture_status != "captured" and self.capture_completeness != "partial":
            raise TransportBoundaryError("non-captured status must remain partial")
        manifest = [
            "auto-g16-transport/capture-manifest",
            1,
            [_request_payload(item) for item in self.requests],
            [_artifact_metadata(item) for item in self.artifacts],
            [_request_payload(item) for item in self.missing_requests],
        ]
        manifest_digest = sha256(canonical_bytes(manifest)).hexdigest()
        identity_name = [
            "auto-g16-transport/output-capture",
            1,
            _binding_payload(self.binding),
            self.input_binding_observation_id,
            self.capture_sequence,
            self.capture_status,
            self.capture_completeness,
            [_request_payload(item) for item in self.requests],
            [_artifact_metadata(item) for item in self.artifacts],
            [_request_payload(item) for item in self.missing_requests],
            manifest_digest,
            self.captured_at_utc,
        ]
        object.__setattr__(self, "capture_manifest_sha256", manifest_digest)
        object.__setattr__(self, "capture_source_id", capture_id(identity_name))
        object.__setattr__(self, "schema_version", 1)


__all__ = [
    "ExactArtifactRequest",
    "ExactRemoteJobBinding",
    "FetchedArtifact",
    "FetchedOutputCapture",
    "SchedulerReadEvidence",
    "TransportStore",
]
