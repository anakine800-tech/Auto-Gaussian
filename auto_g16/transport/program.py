"""Private successor xTB/CREST transport grammar and driver seam.

This module contains no Core state. Its durable store records only the private
physical-effect side of successor authority; Core receipts remain owned by
``auto_g16.execution``. Preparation is pure, and driver calls are available
only through the explicit invocation seam.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import os
from pathlib import Path
import re
import secrets
import sqlite3
import stat
import weakref
from threading import RLock, Lock, get_ident
from contextlib import contextmanager, ExitStack
from typing import Protocol, runtime_checkable
from uuid import UUID, uuid5

from ._canonical import (
    TransportBoundaryError, canonical_bytes, canonical_json_bytes,
    strict_canonical_json,
)
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
_COMPLETION_STORE_SCHEMA = "auto-g16-v31-program-transport-store/2"
_COMPLETION_STORE_DDL = (
    _PROGRAM_STORE_DDL[0][:-1] + ",completion_guard_binding BLOB NOT NULL)",
    *_PROGRAM_STORE_DDL[1:],
)
_COMPLETION_STORE_SCHEMA_IDENTITY = canonical_bytes(
    [*_COMPLETION_STORE_DDL, *[statement for _name, statement in _PROGRAM_STORE_TRIGGERS]]
)

# Directory descriptors, not SQLite descriptors, own the completion lock.
# Keep registry entries alive: removing an entry can split same-process owners.
_DIRECTORY_MUTEX = Lock()
_DIRECTORY_LOCKS = {}
_DIRECTORY_FDS = set()
_STORE_HANDLES = weakref.WeakSet()
_FORK_QUARANTINE = []
_FORK_READY = False
_FORK_CHILD_QUARANTINED = False


class _DirectoryReleaseError(TransportBoundaryError):
    """Descriptor ownership became uncertain; invalidate its store handle."""


def _before_store_fork():
    _DIRECTORY_MUTEX.acquire()


def _parent_store_fork():
    _DIRECTORY_MUTEX.release()


def _after_store_fork():
    global _DIRECTORY_MUTEX, _DIRECTORY_LOCKS, _DIRECTORY_FDS, _FORK_READY, _FORK_CHILD_QUARANTINED
    _FORK_CHILD_QUARANTINED = True
    _FORK_READY = False
    for descriptor in _DIRECTORY_FDS:
        try:
            # LOCK_UN here would unlock the parent's shared open description.
            os.close(descriptor)
        except OSError:
            _FORK_READY = False
    _FORK_QUARANTINE.extend(_STORE_HANDLES)
    _DIRECTORY_FDS = set()
    _DIRECTORY_LOCKS = {}
    _DIRECTORY_MUTEX.release()
    _DIRECTORY_MUTEX = Lock()


if hasattr(os, "register_at_fork"):
    os.register_at_fork(
        before=_before_store_fork,
        after_in_parent=_parent_store_fork,
        after_in_child=_after_store_fork,
    )
    _FORK_READY = True


@contextmanager
def _directory_walk(path, root):
    """Retain the complete lexical no-follow chain; never touch a DB FD."""
    descriptors = []
    creator_pid = os.getpid()
    try:
        for value in (path, root):
            if type(value) is not str or value != os.path.abspath(value) or "//" in value or (value != "/" and value.endswith("/")):
                raise TransportBoundaryError("completion store path is not canonical")
        if os.path.commonpath((path, root)) != root or path == root:
            raise TransportBoundaryError("completion store escapes its approved root")
        parent = os.path.dirname(path)
        with _DIRECTORY_MUTEX:
            for component in ("/", *Path(parent).parts[1:]):
                descriptor = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                                     dir_fd=descriptors[-1] if descriptors else None)
                descriptors.append(descriptor)
                _DIRECTORY_FDS.add(descriptor)
            identities = [[os.fstat(fd).st_dev, os.fstat(fd).st_ino] for fd in descriptors]
        if any(type(dev) is not int or dev < 0 or type(ino) is not int or ino < 1 for dev, ino in identities):
            raise TransportBoundaryError("completion directory identity is invalid")
        binding = {"schema": "v31-completion-directory-guard/1", "lock_directory": parent,
                   "component_identities": identities}
        canonical_bytes(binding)
        yield binding, descriptors[-1]
    except (OSError, AttributeError) as exc:
        raise TransportBoundaryError("completion directory is unavailable or unsafe") from exc
    finally:
        failure = None
        with _DIRECTORY_MUTEX:
            for descriptor in reversed(descriptors) if creator_pid == os.getpid() else ():
                try:
                    os.close(descriptor)
                except OSError as exc:
                    failure = exc
                finally:
                    _DIRECTORY_FDS.discard(descriptor)
        if failure is not None:
            raise _DirectoryReleaseError("completion directory close failed") from failure


@contextmanager
def _directory_guard(path, root):
    if not _FORK_READY:
        raise TransportBoundaryError("completion native fork/lock primitives unavailable")
    import fcntl
    with _directory_walk(path, root) as (binding, descriptor):
        key = (os.getpid(), *binding["component_identities"][-1])
        with _DIRECTORY_MUTEX:
            lock = _DIRECTORY_LOCKS.setdefault(key, Lock())
        if not lock.acquire(blocking=False):
            raise TransportBoundaryError("completion owner is busy")
        held = False
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                held = True
            except OSError as exc:
                raise TransportBoundaryError("completion physical owner is busy or unsupported") from exc
            with _directory_walk(path, root) as (current, _fd):
                if binding != current:
                    raise TransportBoundaryError("completion directory identity drifted")
            yield binding, descriptor, lock
        finally:
            try:
                if held and key[0] == os.getpid():
                    try:
                        fcntl.flock(descriptor, fcntl.LOCK_UN)
                    except OSError as exc:
                        raise _DirectoryReleaseError("completion directory unlock failed") from exc
            finally:
                if key[0] == os.getpid():
                    lock.release()
_OPERATION_TABLE_SHA256 = sha256(canonical_bytes((_PROTOCOL, _OPERATIONS))).hexdigest()


_SCHEDULER_RAW_SCHEMA = "auto-g16-v31-scheduler-raw-evidence/1"
_SCHEDULER_RAW_PREFIX = "scheduler-raw-audit:"
_PHYSICAL_EFFECT_COLUMNS = (
    "physical_effect_authority_id", "program_transport_store_id",
    "store_instance_id", "runtime_attestation_id", "attempt_id",
    "program_execution_snapshot_id", "effect_intent_id", "operation",
    "request_sha256", "effect_classification", "job_id", "submit_once_key",
    "payload",
)


def _scheduler_raw_payload(
    request: Mapping[str, object], result: Mapping[str, object], acquired_at: str,
) -> dict[str, object]:
    # Capture bytes before semantic scheduler parsing, without broadening caps.
    from ._driver import _canonical_b64
    _exact_keys(result, {
        "stdout_base64", "stderr_base64", "returncode", "eof_stdout",
        "eof_stderr", "completion_status",
    }, "raw scheduler result")
    for key, cap in (("stdout_base64", 262144), ("stderr_base64", 65536)):
        encoded = result[key]
        if type(encoded) is not str or len(encoded) > 4 * ((cap + 2) // 3):
            raise TransportBoundaryError("raw scheduler encoded streams exceed caps")
    out = _canonical_b64(result["stdout_base64"])
    err = _canonical_b64(result["stderr_base64"])
    if len(out) > 262144 or len(err) > 65536:
        raise TransportBoundaryError("raw scheduler streams exceed caps")
    if type(result["returncode"]) is not int or any(
        type(result[key]) is not bool for key in ("eof_stdout", "eof_stderr")
    ):
        raise TransportBoundaryError("raw scheduler result types are invalid")
    _text(result["completion_status"], "raw scheduler completion")
    if type(acquired_at) is not str:
        raise TransportBoundaryError("raw scheduler acquisition time is invalid")
    try:
        stamp = datetime.strptime(acquired_at, "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError as exc:
        raise TransportBoundaryError("raw scheduler acquisition time is invalid") from exc
    if stamp.strftime("%Y-%m-%dT%H:%M:%S.%fZ") != acquired_at:
        raise TransportBoundaryError("raw scheduler acquisition time is not canonical")
    payload = request["payload"]
    assert isinstance(payload, Mapping)
    return {
        "schema": _SCHEDULER_RAW_SCHEMA, "purpose": "audit-only",
        "acquired_at": acquired_at, "binding": dict(request["binding"]),
        "request": _request("QUERY_SCHEDULER", dict(request["binding"]), dict(payload)),
        "request_sha256": _digest(request),
        "job_id": _job_id(payload["job_id"]), "raw_result": dict(result),
        "stdout_sha256": sha256(out).hexdigest(),
        "stderr_sha256": sha256(err).hexdigest(),
        "raw_result_sha256": sha256(canonical_json_bytes(dict(result))).hexdigest(),
    }


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


def _require_store_process():
    if _FORK_CHILD_QUARANTINED:
        raise TransportBoundaryError("fork child requires exec before opening any program store")


def _readonly_source_state(path, root):
    with _directory_walk(path, root) as (binding, parent_fd):
        name = Path(path).name
        for suffix in ("-journal", "-wal", "-shm"):
            try:
                os.stat(name + suffix, dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                continue
            raise TransportBoundaryError("read-only source has a SQLite sidecar")
        descriptor = os.open(name, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC,
                             dir_fd=parent_fd)
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise TransportBoundaryError("read-only source must be a single regular file")
            header = os.read(descriptor, 100)
            if len(header) != 100 or header[:16] != b"SQLite format 3\x00" or header[18:20] != b"\x01\x01":
                raise TransportBoundaryError("read-only source requires rollback journal format")
            named = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            if (named.st_dev, named.st_ino) != (info.st_dev, info.st_ino):
                raise TransportBoundaryError("read-only source path changed")
            return binding, info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns, header
        finally:
            os.close(descriptor)


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
        _require_store_process()
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
    def _create_completion_store(cls, path, *, approved_root):
        _require_store_process()
        # Unlike v1's historical normalizer, C4 requires already canonical paths.
        raw_path, raw_root = os.fspath(path), os.fspath(approved_root)
        value = None
        try:
            with _directory_guard(raw_path, raw_root) as (binding, parent_fd, _lock):
                descriptor = os.open(Path(raw_path).name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                                     0o600, dir_fd=parent_fd)
                os.close(descriptor)  # Before SQLite exists; never a lock descriptor.
                value = cls._open(raw_path, raw_root, version=2)
                value._guard_binding = binding
                token = value._set_completion_owner(parent_fd)
                try:
                    value._check_completion_path()
                    value._configure_connection()
                    value._create_schema()
                    value._require_completion_guard(token)
                except BaseException:
                    value._completion_owner = None
                    value.close()
                    raise
                finally:
                    value._completion_owner = None
        except BaseException:
            if value is not None:
                value.close()
            raise
        return value

    @classmethod
    def open_existing(cls, path, *, approved_root):
        return cls._open_existing(path, approved_root=approved_root)

    @classmethod
    def _open_readonly_existing(cls, path, *, approved_root):
        return cls._open_existing(path, approved_root=approved_root, readonly=True)

    @classmethod
    def _open_existing(cls, path, *, approved_root, readonly=False):
        _require_store_process()
        absolute_path, absolute_root = _store_paths(path, approved_root)
        # The same SQLite connection identifies format, never accepts authority.
        # A v1 store does not inherit v2's directory-lock or full-chain policy.
        value = None
        try:
            with ExitStack() as stack:
                try:
                    binding, _fd = stack.enter_context(_directory_walk(os.fspath(path), os.fspath(approved_root)))
                except TransportBoundaryError:
                    if readonly:
                        raise
                    binding = None
                before = _readonly_source_state(absolute_path, absolute_root) if readonly else None
                value = cls._open(absolute_path, absolute_root, version=None, readonly=readonly)
                try:
                    if value._version == 1:
                        value._attest()
                    else:
                        if binding is None:
                            raise TransportBoundaryError("completion directory was not safely observed")
                        value._guard_binding = binding
                        with _directory_guard(absolute_path, absolute_root) as (current, parent_fd, _lock):
                            if binding != current:
                                raise TransportBoundaryError("completion directory changed across SQLite open")
                            token = value._set_completion_owner(parent_fd)
                            try:
                                value._check_completion_path()
                                value._configure_connection()
                                value._require_completion_guard(token)
                            finally:
                                value._completion_owner = None
                    if readonly and _readonly_source_state(absolute_path, absolute_root) != before:
                        raise TransportBoundaryError("read-only source changed across SQLite open")
                    return value
                except BaseException:
                    value.close()
                    raise
        except BaseException as error:
            if value is not None:
                value.close()
            if readonly and 'before' in locals() and before is not None:
                try:
                    if _readonly_source_state(absolute_path, absolute_root) != before:
                        raise TransportBoundaryError("read-only source changed on failed open")
                except BaseException as recheck:
                    error.add_note(f"source recheck failed: {recheck!r}")
            raise

    @classmethod
    def _open(cls, path: str, root: str, *, version=1, readonly=False):
        _require_store_process()
        identity = _store_file_identity(path)
        value = object.__new__(cls)
        value._path, value._root, value._file_identity = path, root, identity
        value._creator_pid = os.getpid()
        value._version = version
        value._lock = RLock()
        value._completion_lock = Lock()
        value._completion_owner = None
        value._guard_binding = None
        value._invalid = False
        value._closed = False
        # Fork cannot miss a just-created connection in the quarantine registry.
        with _DIRECTORY_MUTEX:
            if readonly:
                value._connection = sqlite3.connect(Path(path).as_uri() + "?mode=ro&cache=private",
                                                   uri=True, isolation_level=None, check_same_thread=False)
            else:
                value._connection = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
            _STORE_HANDLES.add(value)
        try:
            if readonly:
                value._connection.execute("PRAGMA query_only=ON")
            if version is None:
                application = value._connection.execute("PRAGMA application_id").fetchone()[0]
                value._version = value._connection.execute("PRAGMA user_version").fetchone()[0]
                if application != _PROGRAM_STORE_APPLICATION_ID or value._version not in (1, 2):
                    raise TransportBoundaryError("program transport store schema drifted")
            value._schema = _PROGRAM_STORE_SCHEMA if value._version == 1 else _COMPLETION_STORE_SCHEMA
            if value._version == 1:
                value._configure_connection()
            if _store_file_identity(path) != identity:
                raise TransportBoundaryError("program transport store changed across SQLite open")
            return value
        except BaseException:
            value.close()
            raise

    def _configure_connection(self):
        self._check_pid()
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._connection.execute("PRAGMA trusted_schema=OFF")
        self._connection.execute("PRAGMA synchronous=FULL")

    def _check_pid(self):
        if self._creator_pid != os.getpid():
            raise TransportBoundaryError("inherited program store is unqualified; exec required")

    def _set_completion_owner(self, descriptor):
        self._check_pid()
        with self._lock:
            if self._closed or self._invalid:
                raise TransportBoundaryError("completion store handle is invalid or closed")
            token = object()
            info = os.fstat(descriptor)
            self._completion_owner = (token, os.getpid(), get_ident(), descriptor,
                                      info.st_dev, info.st_ino,
                                      getattr(self, "store_instance_id", None), self)
            return token

    def _check_completion_path(self):
        self._check_pid()
        if self._invalid or self._closed:
            raise TransportBoundaryError("completion store handle is invalid or closed")
        try:
            with _directory_walk(self._path, self._root) as (current, parent_fd):
                if current != self._guard_binding:
                    raise TransportBoundaryError("completion persistent directory identity drifted")
                info = os.stat(Path(self._path).name, dir_fd=parent_fd, follow_symlinks=False)
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or (info.st_dev, info.st_ino) != self._file_identity:
                    raise TransportBoundaryError("completion database identity or hardlink drifted")
        except (TransportBoundaryError, OSError):
            self._invalid = True
            raise

    @contextmanager
    def _completion_guard(self):
        self._check_pid()
        if self._version != 2:
            raise TransportBoundaryError("completion-store-not-qualified")
        if self._closed or self._invalid:
            raise TransportBoundaryError("completion store handle is invalid or closed")
        try:
            with _directory_guard(self._path, self._root) as (binding, descriptor, lock):
                if binding != self._guard_binding:
                    self._invalid = True
                    raise TransportBoundaryError("completion persistent directory identity drifted")
                self._completion_lock = lock
                token = self._set_completion_owner(descriptor)
                try:
                    self._require_completion_guard(token)
                    yield token
                    self._require_completion_guard(token)
                finally:
                    self._completion_owner = None
        except _DirectoryReleaseError:
            self._invalid = True
            raise

    def _require_completion_guard(self, token):
        self._check_pid()
        owner = self._completion_owner
        if (token is None or owner is None or token is not owner[0]
                or owner[1:3] != (os.getpid(), get_ident()) or owner[7] is not self):
            raise TransportBoundaryError("completion owner token is absent or foreign")
        info = os.fstat(owner[3])
        if (info.st_dev, info.st_ino) != owner[4:6] or (owner[6] is not None and owner[6] != self.store_instance_id):
            raise TransportBoundaryError("completion owner identity drifted")
        with self._lock:
            self._attest_locked()

    def _require_current_completion_owner(self):
        self._check_pid()
        owner = self._completion_owner
        self._require_completion_guard(owner[0] if owner else None)

    @contextmanager
    def _store_access(self):
        self._check_pid()
        if self._version == 1:
            yield
        elif self._completion_owner is not None and self._completion_owner[1:3] == (os.getpid(), get_ident()):
            self._require_current_completion_owner()
            yield
        else:
            with self._completion_guard():
                yield

    def _create_schema(self) -> None:
        self._check_pid()
        if self._version == 2:
            self._check_completion_path()
        nonce = secrets.token_bytes(32)
        store_payload = {
            "schema": self._schema,
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
        if self._version == 2:
            instance_payload["completion_guard_binding_sha256"] = _digest(self._guard_binding)
        instance_id = _identity("program-transport-store-instance", instance_payload)
        with self._lock:
            self._connection.execute(
                f"PRAGMA application_id={_PROGRAM_STORE_APPLICATION_ID}"
            )
            self._connection.execute(f"PRAGMA user_version={self._version}")
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                for statement in (_PROGRAM_STORE_DDL if self._version == 1 else _COMPLETION_STORE_DDL):
                    self._connection.execute(statement)
                for _name, statement in _PROGRAM_STORE_TRIGGERS:
                    self._connection.execute(statement)
                self._connection.execute(
                    "INSERT INTO program_transport_meta VALUES(1," + ",".join("?" for _ in range(8 if self._version == 1 else 9)) + ")",
                    (
                        _PROGRAM_STORE_SCHEMA_IDENTITY if self._version == 1 else _COMPLETION_STORE_SCHEMA_IDENTITY,
                        store_id,
                        instance_id,
                        nonce,
                        self._root,
                        self._path,
                        self._file_identity[0],
                        self._file_identity[1],
                    ) + (() if self._version == 1 else (canonical_bytes(self._guard_binding),)),
                )
                if self._version == 2:
                    self._check_completion_path()
                self._connection.execute("COMMIT")
            except Exception:
                self._connection.execute("ROLLBACK")
                raise
        self._attest()
        if self._version == 2:
            self._completion_owner = (*self._completion_owner[:6], instance_id, self)

    def _attest(self) -> None:
        with self._store_access():
            with self._lock:
                self._attest_locked()

    def _attest_locked(self) -> None:
        self._check_pid()
        if self._version == 2:
            self._check_completion_path()
        if getattr(self, "_closed", True):
            raise TransportBoundaryError("program transport store is closed")
        if _store_file_identity(self._path) != self._file_identity:
            raise TransportBoundaryError("program transport store identity drifted")
        if (
            self._connection.execute("PRAGMA application_id").fetchone()[0]
            != _PROGRAM_STORE_APPLICATION_ID
            or self._connection.execute("PRAGMA user_version").fetchone()[0]
            != self._version
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
            **dict(zip(_PROGRAM_STORE_TABLES, _PROGRAM_STORE_DDL if self._version == 1 else _COMPLETION_STORE_DDL)),
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
                "schema": self._schema,
                "approved_store_root": self._root,
                "approved_store_path": self._path,
            },
        )
        expected_instance_id = None
        if type(nonce) is bytes and len(nonce) == 32:
            expected_instance_id = _identity(
                "program-transport-store-instance",
                {
                    "schema": self._schema,
                    "approved_store_root": self._root,
                    "approved_store_path": self._path,
                    "program_transport_store_id": expected_store_id,
                    "creation_nonce_sha256": sha256(nonce).hexdigest(),
                    "store_device": self._file_identity[0],
                    "store_inode": self._file_identity[1],
                    **({"completion_guard_binding_sha256": _digest(self._guard_binding)} if self._version == 2 else {}),
                },
            )
        if (
            row[0] != 1
            or row[1] != (_PROGRAM_STORE_SCHEMA_IDENTITY if self._version == 1 else _COMPLETION_STORE_SCHEMA_IDENTITY)
            or (self._version == 2 and row[9] != canonical_bytes(self._guard_binding))
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
        self._check_pid()
        with self._lock:
            if self._completion_owner is not None:
                raise TransportBoundaryError("cannot close a held completion owner")
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
        with self._store_access(), self._lock:
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
                if self._version == 2:
                    self._check_completion_path()
                self._connection.execute("COMMIT")
            except Exception:
                self._connection.execute("ROLLBACK")
                raise

    def _runtime_attestation_record(
        self,
        *,
        program_execution_snapshot_id: str,
        resolved_server_profile_id: str,
        qualification: Mapping[str, object],
    ):
        self._attest()
        closed = dict(_runtime_qualification(qualification))
        payload = {
            "schema": self._schema,
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
        return identity, columns, values

    def attest_runtime(
        self, *, program_execution_snapshot_id: str,
        resolved_server_profile_id: str, qualification: Mapping[str, object],
        persist: bool = True,
    ) -> str:
        identity, columns, values = self._runtime_attestation_record(
            program_execution_snapshot_id=program_execution_snapshot_id,
            resolved_server_profile_id=resolved_server_profile_id, qualification=qualification)
        if persist:
            self._insert_exact("program_runtime_attestation", columns, values, identity)
        return identity

    def _require_recorded_runtime(self, *, program_execution_snapshot_id, resolved_server_profile_id, qualification) -> str:
        """Pure all-column reclosure of the persisted historical runtime row."""
        identity, columns, values = self._runtime_attestation_record(
            program_execution_snapshot_id=program_execution_snapshot_id,
            resolved_server_profile_id=resolved_server_profile_id, qualification=qualification)
        with self._store_access(), self._lock:
            self._attest()
            rows = self._connection.execute(
                "SELECT " + ",".join(columns) + " FROM program_runtime_attestation WHERE runtime_attestation_id=?",
                (identity,),
            ).fetchall()
            if len(rows) != 1 or tuple(rows[0]) != values:
                raise TransportBoundaryError("historical runtime attestation differs or is missing")
        return identity

    def _scheduler_raw_request(self, request: Mapping[str, object]) -> Mapping[str, object]:
        self._attest()
        if not isinstance(request, Mapping) or request.get("operation") != "QUERY_SCHEDULER":
            raise TransportBoundaryError("raw audit requires an exact scheduler request")
        binding = request.get("binding")
        closed = _base_binding(binding)
        _validate_program_effect_request(request, binding)
        if (closed["program_transport_store_id"] != self.program_transport_store_id
                or closed["store_instance_id"] != self.store_instance_id):
            raise TransportBoundaryError("raw scheduler request names another physical store")
        with self._lock:
            rows = self._connection.execute(
                "SELECT program_transport_store_id,store_instance_id,"
                "program_execution_snapshot_id,resolved_server_profile_id,protocol,"
                "operation_table_sha256 FROM program_runtime_attestation "
                "WHERE runtime_attestation_id=?", (closed["runtime_attestation_id"],),
            ).fetchall()
        expected = tuple(closed[key] for key in (
            "program_transport_store_id", "store_instance_id",
            "program_execution_snapshot_id", "resolved_server_profile_id",
        )) + (_PROTOCOL, _OPERATION_TABLE_SHA256)
        if rows != [expected]:
            raise TransportBoundaryError("raw scheduler runtime binding differs")
        return closed

    def _scheduler_raw_values(
        self, payload: Mapping[str, object], binding: Mapping[str, object],
    ) -> tuple[object, ...]:
        raw = canonical_json_bytes(payload)
        identity = _SCHEDULER_RAW_PREFIX + _identity("scheduler-raw-audit", raw)
        return (
            identity, self.program_transport_store_id, self.store_instance_id,
            binding["runtime_attestation_id"], binding["attempt_id"],
            binding["program_execution_snapshot_id"], binding["effect_intent_id"],
            "QUERY_SCHEDULER", payload["request_sha256"], "UNKNOWN", None, None,
            raw,
        )

    def _record_scheduler_raw(
        self, *, request: Mapping[str, object], result: Mapping[str, object],
    ) -> str:
        """Persist audit-only acquired bytes before attempting normalization."""
        binding = self._scheduler_raw_request(request)
        acquired_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        payload = _scheduler_raw_payload(request, result, acquired_at)
        values = self._scheduler_raw_values(payload, binding)
        identity = str(values[0])
        self._insert_exact(
            "program_effect_physical_authority", _PHYSICAL_EFFECT_COLUMNS,
            values, identity,
        )
        return identity

    def _read_scheduler_raw(
        self, identity: str, *, request: Mapping[str, object],
    ) -> Mapping[str, object]:
        """Reclose one raw acquisition against its expected exact request."""
        binding = self._scheduler_raw_request(request)
        if type(identity) is not str or not identity.startswith(_SCHEDULER_RAW_PREFIX):
            raise TransportBoundaryError("raw scheduler identity is invalid")
        with self._lock:
            rows = self._connection.execute(
                f"SELECT {','.join(_PHYSICAL_EFFECT_COLUMNS)} "
                "FROM program_effect_physical_authority "
                "WHERE physical_effect_authority_id=?", (identity,),
            ).fetchall()
        if len(rows) != 1:
            raise TransportBoundaryError("raw scheduler audit is absent or ambiguous")
        payload = strict_canonical_json(rows[0][-1], "raw scheduler audit")
        _exact_keys(payload, {
            "schema", "purpose", "acquired_at", "binding", "request",
            "request_sha256", "job_id", "raw_result", "stdout_sha256",
            "stderr_sha256", "raw_result_sha256",
        }, "raw scheduler audit")
        rebuilt = _scheduler_raw_payload(request, payload["raw_result"], payload["acquired_at"])
        if payload != rebuilt or tuple(rows[0]) != self._scheduler_raw_values(rebuilt, binding):
            raise TransportBoundaryError("raw scheduler audit hash or binding differs")
        return payload

    def _list_scheduler_raw_ids(self, *, request: Mapping[str, object]) -> tuple[str, ...]:
        """Discover only this exact request's audit records and revalidate each."""
        self._scheduler_raw_request(request)
        # Enumerate only this physical store's prefixed audit rows. Do not trust
        # denormalized request indexes to decide which records need validation.
        with self._lock:
            rows = self._connection.execute(
                "SELECT physical_effect_authority_id,payload "
                "FROM program_effect_physical_authority "
                "WHERE physical_effect_authority_id LIKE ? "
                "ORDER BY physical_effect_authority_id",
                (_SCHEDULER_RAW_PREFIX + "%",),
            ).fetchall()
        identities = []
        for identity, raw in rows:
            payload = strict_canonical_json(raw, "raw scheduler discovery")
            if not isinstance(payload, Mapping) or not isinstance(payload.get("request"), Mapping):
                raise TransportBoundaryError("raw scheduler discovery request is malformed")
            audit = self._read_scheduler_raw(identity, request=payload["request"])
            if audit["request"] == request:
                identities.append(identity)
        return tuple(identities)

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
            "schema": self._schema,
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
            "schema": self._schema,
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
        with self._lock:
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
        if value.get("schema") == "v31-exact-observed-job-reconciliation-request/1":
            payload = _exact_keys(value, {"schema", "submit_receipt_id", "observed_job_id", "continuation_sha256"}, "exact recovery payload")
            _text(payload["submit_receipt_id"], "submit receipt ID")
            _job_id(payload["observed_job_id"])
            if type(payload["continuation_sha256"]) is not str or _SHA256.fullmatch(payload["continuation_sha256"]) is None:
                raise TransportBoundaryError("invalid recovery continuation digest")
            return payload
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
    if not isinstance(value, Mapping) or set(value) not in ({"job_id", "state"}, {"job_id", "state", "exit_status"}):
        raise _ProgramEffectUnknown("scheduler response has an invalid closed shape")
    response = value
    if response["job_id"] != expected_job_id or response["state"] not in _SCHEDULER_STATES:
        raise _ProgramEffectUnknown("scheduler response differs from job authority")
    if "exit_status" in response and (response["state"] != "terminal" or type(response["exit_status"]) is not int or not -(2**31) <= response["exit_status"] < 2**31):
        raise _ProgramEffectUnknown("scheduler exit status is not exact terminal evidence")
    return response


def _reconciliation_response(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise _ProgramEffectUnknown("reconciliation response is malformed")
    if value.get("schema") == "v31-exact-observed-job-reconciliation-proof/1":
        from . import _submission_recovery as recovery
        recovery.closed(value, {"schema", "outcome", "job_id", "request", "expected", "raw_observation_id", "raw"})
        if value["outcome"] not in {"SUCCEEDED", "UNKNOWN"}:
            raise _ProgramEffectUnknown("exact recovery disposition")
        if value["outcome"] == "SUCCEEDED":
            if recovery.interpret(value["raw"], value["expected"]) != value["job_id"]:
                raise _ProgramEffectUnknown("recovery job mismatch")
        elif value["job_id"] is not None:
            raise _ProgramEffectUnknown("unresolved recovery has a job")
        return value
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
