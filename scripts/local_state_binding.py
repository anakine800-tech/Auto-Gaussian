#!/usr/bin/env python3
"""Deterministic, read-only local-state ownership for a future successor.

This module derives and seals local paths. It does not create directories,
change permissions, acquire the execution-batch reservation lock, write a
ledger, reserve authority, stage files, submit, monitor, fetch, cancel, clean
up, or expose an adapter/effect callback.
"""

from __future__ import annotations

import _imp
import contextlib
import copy
import hashlib
import importlib.util
import json
import os
import re
import stat
import sys
import threading
import types
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterator


SCHEMA = "auto-g16-local-state-binding/1"
OWNER = "auto-g16-local-state-binding-owner"
LAYOUT_SCHEMA = "auto-g16-local-state-layout/1"
OUTPUTS_COMPONENT = "outputs"
LEDGER_BASENAME = "execution-batch-v3.json"
PROTECTED_STATE_POLICY = "exact_execution_batch_v3_only"
SHA_RE = re.compile(r"^[a-f0-9]{64}$")
PROJECT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,14}$")
TASK_RE = re.compile(r"^scientific-task-[a-f0-9]{64}$")
ATTEMPT_RE = re.compile(r"^qsub-attempt-[a-f0-9]{64}$")
BUNDLE_RE = re.compile(r"^protected-submit-[a-f0-9]{64}$")
_SEAL_TOKEN = object()
_TEST_OWNER_TOKEN = object()
_MODULE_LOCK = threading.RLock()
_MISSING_MODULE = object()
_PROTECTED_MODULE_NAME = "protected_submit_contract"
_READ_CHUNK_SIZE = 1024 * 1024
_MAX_LEDGER_BYTES = 32 * 1024 * 1024


class LocalStateBindingError(ValueError):
    """The deterministic local-state closure cannot be proved exactly."""


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or SHA_RE.fullmatch(value) is None:
        raise LocalStateBindingError(f"{label} must be a lowercase SHA-256")
    return value


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise LocalStateBindingError(f"{label} must be a non-empty string")
    return value


def _draft_integer(value: Any, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool):
        raise LocalStateBindingError(f"{label} must be a Draft integer")
    if isinstance(value, int):
        result = value
    elif isinstance(value, float) and value.is_integer():
        result = int(value)
    else:
        raise LocalStateBindingError(f"{label} must be a Draft integer")
    if result < minimum:
        raise LocalStateBindingError(f"{label} must be at least {minimum}")
    return result


def _exact(value: Any, fields: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise LocalStateBindingError(
            f"{label} must contain exactly {sorted(fields)}"
        )
    return value


def _canonical_relative_path(value: Any, label: str) -> PurePosixPath:
    text = _text(value, label)
    if unicodedata.normalize("NFC", text) != text or "\\" in text:
        raise LocalStateBindingError(f"{label} is not canonical portable text")
    path = PurePosixPath(text)
    if (
        path.is_absolute()
        or str(path) != text
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise LocalStateBindingError(f"{label} is not a canonical relative path")
    return path


def _canonicalize_portable_integers(
    document: dict[str, Any],
) -> dict[str, Any]:
    ledger = document.get("ledger")
    if isinstance(ledger, dict):
        for field in (
            "artifact_size_bytes",
            "revision",
            "resource_state_revision",
        ):
            if field in ledger:
                ledger[field] = _draft_integer(
                    ledger[field],
                    f"ledger.{field}",
                )
    return document


def finalize(document: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise LocalStateBindingError(
            "local-state binding must be a JSON object"
        )
    result = _canonicalize_portable_integers(copy.deepcopy(document))
    result["binding_payload_sha256"] = digest(
        {
            key: value
            for key, value in result.items()
            if key != "binding_payload_sha256"
        }
    )
    return validate_local_state_binding(result)


def validate_local_state_binding(
    document: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise LocalStateBindingError(
            "local-state binding must be a JSON object"
        )
    value = _canonicalize_portable_integers(copy.deepcopy(document))
    _exact(
        value,
        {
            "schema",
            "owner",
            "layout",
            "path_bindings",
            "ledger",
            "identity",
            "protected_submit",
            "policy",
            "binding_payload_sha256",
        },
        "local-state binding",
    )
    if value["schema"] != SCHEMA or value["owner"] != OWNER:
        raise LocalStateBindingError("local-state schema or owner differs")

    layout = _exact(
        value["layout"],
        {
            "schema",
            "relative_local_dir",
            "relative_ledger_path",
            "ledger_basename",
        },
        "local-state layout",
    )
    if (
        layout["schema"] != LAYOUT_SCHEMA
        or layout["ledger_basename"] != LEDGER_BASENAME
    ):
        raise LocalStateBindingError("local-state fixed layout differs")

    identity = _exact(
        value["identity"],
        {
            "project",
            "attempt_id",
            "scientific_task_id",
            "input_sha256",
            "idempotency_key_sha256",
        },
        "local-state identity",
    )
    project = _text(identity["project"], "identity.project")
    attempt_id = _text(identity["attempt_id"], "identity.attempt_id")
    if PROJECT_RE.fullmatch(project) is None:
        raise LocalStateBindingError("local-state project is unsafe")
    if ATTEMPT_RE.fullmatch(attempt_id) is None:
        raise LocalStateBindingError("local-state attempt ID is unsafe")
    if TASK_RE.fullmatch(
        _text(identity["scientific_task_id"], "identity.scientific_task_id")
    ) is None:
        raise LocalStateBindingError("local-state scientific task ID is unsafe")
    _sha(identity["input_sha256"], "identity.input_sha256")
    _sha(
        identity["idempotency_key_sha256"],
        "identity.idempotency_key_sha256",
    )

    local_relative = _canonical_relative_path(
        layout["relative_local_dir"],
        "layout.relative_local_dir",
    )
    ledger_relative = _canonical_relative_path(
        layout["relative_ledger_path"],
        "layout.relative_ledger_path",
    )
    expected_local = PurePosixPath(OUTPUTS_COMPONENT, project, attempt_id)
    expected_ledger = expected_local / LEDGER_BASENAME
    if local_relative != expected_local or ledger_relative != expected_ledger:
        raise LocalStateBindingError(
            "local-state relative paths differ from owner-derived identity"
        )

    path_bindings = _exact(
        value["path_bindings"],
        {"workspace_root_path_sha256", "local_dir_path_sha256"},
        "local-state path bindings",
    )
    _sha(
        path_bindings["workspace_root_path_sha256"],
        "workspace-root path",
    )
    _sha(path_bindings["local_dir_path_sha256"], "local-dir path")

    ledger = _exact(
        value["ledger"],
        {
            "schema",
            "artifact_sha256",
            "artifact_size_bytes",
            "ledger_sha256",
            "revision",
            "resource_state_revision",
            "resource_state_sha256",
            "batch_id_sha256",
            "review_sha256",
        },
        "local-state ledger",
    )
    if ledger["schema"] != "gaussian-execution-batch/3":
        raise LocalStateBindingError("local-state ledger must be current /3")
    for field in (
        "artifact_sha256",
        "ledger_sha256",
        "resource_state_sha256",
        "review_sha256",
    ):
        _sha(ledger[field], f"ledger.{field}")
    _draft_integer(
        ledger["artifact_size_bytes"],
        "ledger.artifact_size_bytes",
        minimum=1,
    )
    _draft_integer(ledger["revision"], "ledger.revision")
    _draft_integer(
        ledger["resource_state_revision"],
        "ledger.resource_state_revision",
    )
    _sha(ledger["batch_id_sha256"], "ledger.batch_id_sha256")

    protected = _exact(
        value["protected_submit"],
        {"schema", "bundle_id", "bundle_payload_sha256"},
        "protected-submit binding",
    )
    if protected["schema"] != "auto-g16-protected-submit-bundle/1":
        raise LocalStateBindingError("protected-submit predecessor differs")
    if BUNDLE_RE.fullmatch(
        _text(protected["bundle_id"], "protected-submit bundle ID")
    ) is None:
        raise LocalStateBindingError("protected-submit bundle ID is unsafe")
    _sha(
        protected["bundle_payload_sha256"],
        "protected-submit bundle payload",
    )

    if value["policy"] != {
        "future_protected_successor_only": True,
        "no_execution_authorization": True,
        "local_state_directory_creation_performed": False,
        "local_state_permissions_changed": False,
        "ledger_lock_acquired": False,
        "ledger_write_performed": False,
        "external_actions_performed": False,
        "legacy_cli_unchanged": True,
        "historical_migration": False,
        "protected_state_policy": PROTECTED_STATE_POLICY,
    }:
        raise LocalStateBindingError("local-state policy boundary differs")

    _sha(value["binding_payload_sha256"], "local-state binding payload")
    expected_hash = digest(
        {
            key: item
            for key, item in value.items()
            if key != "binding_payload_sha256"
        }
    )
    if value["binding_payload_sha256"] != expected_hash:
        raise LocalStateBindingError("local-state binding payload hash differs")
    return value


@dataclass(frozen=True, slots=True)
class LocalStateBindingEvidence:
    """Typed seal input; caller supplies no local directory."""

    workspace_root: Path
    ledger_path: Path
    protected_submit_evidence: object

    def snapshot(self) -> "LocalStateBindingEvidence":
        if not isinstance(self.workspace_root, Path):
            raise TypeError("workspace_root must be an exact pathlib.Path")
        if not isinstance(self.ledger_path, Path):
            raise TypeError("ledger_path must be an exact pathlib.Path")
        return LocalStateBindingEvidence(
            workspace_root=self.workspace_root,
            ledger_path=self.ledger_path,
            protected_submit_evidence=self.protected_submit_evidence,
        )


@dataclass(frozen=True, slots=True)
class _DirectoryIdentity:
    device: int
    inode: int
    uid: int
    mode: int
    mtime_ns: int
    ctime_ns: int


@dataclass(frozen=True, slots=True)
class _FileIdentity:
    device: int
    inode: int
    uid: int
    mode: int
    size: int
    mtime_ns: int
    ctime_ns: int
    sha256: str


@dataclass(frozen=True, slots=True, init=False)
class LocalStatePaths:
    """Owner-issued canonical paths with their initial filesystem identities."""

    workspace_root: Path
    local_dir: Path
    ledger_path: Path
    workspace_identity: _DirectoryIdentity
    local_dir_identity: _DirectoryIdentity
    ledger_identity: _FileIdentity
    _seal: object

    def __new__(cls, *args: Any, **kwargs: Any) -> "LocalStatePaths":
        raise TypeError("LocalStatePaths is issued only by the local-state owner")

    @classmethod
    def _from_owner(
        cls,
        *,
        workspace_root: Path,
        local_dir: Path,
        ledger_path: Path,
        workspace_identity: _DirectoryIdentity,
        local_dir_identity: _DirectoryIdentity,
        ledger_identity: _FileIdentity,
        token: object,
    ) -> "LocalStatePaths":
        if token is not _SEAL_TOKEN:
            raise LocalStateBindingError("local-state path seal differs")
        value = object.__new__(cls)
        fields = {
            "workspace_root": workspace_root,
            "local_dir": local_dir,
            "ledger_path": ledger_path,
            "workspace_identity": workspace_identity,
            "local_dir_identity": local_dir_identity,
            "ledger_identity": ledger_identity,
            "_seal": _SEAL_TOKEN,
        }
        for name, item in fields.items():
            object.__setattr__(value, name, item)
        return value

    def assert_owner_sealed(self) -> None:
        if self._seal is not _SEAL_TOKEN:
            raise LocalStateBindingError("local-state path seal differs")

    def assert_current(self) -> "LocalStatePaths":
        _assert_paths_current(self)
        return self


@dataclass(frozen=True, slots=True, init=False)
class SealedLocalStateBinding:
    """Owner-issued portable binding plus non-portable exact path identities."""

    _canonical_document: bytes
    paths: LocalStatePaths
    project: str
    attempt_id: str
    binding_payload_sha256: str
    _seal: object

    def __new__(
        cls,
        *args: Any,
        **kwargs: Any,
    ) -> "SealedLocalStateBinding":
        raise TypeError(
            "SealedLocalStateBinding is issued only by the local-state owner"
        )

    @classmethod
    def _from_owner(
        cls,
        document: dict[str, Any],
        paths: LocalStatePaths,
        *,
        token: object,
    ) -> "SealedLocalStateBinding":
        if token is not _SEAL_TOKEN:
            raise LocalStateBindingError("local-state binding seal differs")
        paths.assert_owner_sealed()
        validated = validate_local_state_binding(document)
        value = object.__new__(cls)
        fields = {
            "_canonical_document": canonical_bytes(validated),
            "paths": paths,
            "project": validated["identity"]["project"],
            "attempt_id": validated["identity"]["attempt_id"],
            "binding_payload_sha256": validated[
                "binding_payload_sha256"
            ],
            "_seal": _SEAL_TOKEN,
        }
        for name, item in fields.items():
            object.__setattr__(value, name, item)
        return value

    def document(self) -> dict[str, Any]:
        return json.loads(self._canonical_document)

    def assert_owner_sealed(self) -> None:
        if self._seal is not _SEAL_TOKEN:
            raise LocalStateBindingError("local-state binding seal differs")
        self.paths.assert_owner_sealed()
        document = validate_local_state_binding(self.document())
        if (
            document["identity"]["project"] != self.project
            or document["identity"]["attempt_id"] != self.attempt_id
            or document["binding_payload_sha256"]
            != self.binding_payload_sha256
        ):
            raise LocalStateBindingError(
                "local-state sealed projection differs"
            )

    def assert_current(self) -> "SealedLocalStateBinding":
        self.assert_owner_sealed()
        _assert_binding_current(self)
        return self


def _protected_contract_path() -> Path:
    here = Path(__file__).resolve()
    path = here.with_name(f"{_PROTECTED_MODULE_NAME}.py")
    if path.is_symlink() or not path.is_file():
        raise ImportError(
            f"exact adjacent protected-submit owner is unavailable: {path}"
        )
    resolved = path.resolve()
    if resolved.parent != here.parent:
        raise ImportError(
            "protected-submit owner is not adjacent to local-state owner"
        )
    return resolved


def _module_origin(module: types.ModuleType) -> tuple[Path, Path]:
    raw_file = getattr(module, "__file__", None)
    spec = getattr(module, "__spec__", None)
    raw_spec_origin = getattr(spec, "origin", None)
    if (
        not isinstance(raw_file, str)
        or not raw_file
        or not isinstance(raw_spec_origin, str)
        or not raw_spec_origin
    ):
        raise ImportError("protected-submit owner has no resolved origin")
    return Path(raw_file).resolve(), Path(raw_spec_origin).resolve()


@contextlib.contextmanager
def _exact_protected_contract() -> Iterator[types.ModuleType]:
    path = _protected_contract_path()
    with _MODULE_LOCK:
        _imp.acquire_lock()
        previous = sys.modules.get(_PROTECTED_MODULE_NAME, _MISSING_MODULE)
        try:
            sys.modules.pop(_PROTECTED_MODULE_NAME, None)
            spec = importlib.util.spec_from_file_location(
                _PROTECTED_MODULE_NAME,
                path,
            )
            if spec is None or spec.loader is None:
                raise ImportError(
                    f"exact protected-submit owner cannot be loaded: {path}"
                )
            module = importlib.util.module_from_spec(spec)
            sys.modules[_PROTECTED_MODULE_NAME] = module
            spec.loader.exec_module(module)
            file_origin, spec_origin = _module_origin(module)
            if file_origin != path or spec_origin != path:
                raise ImportError("protected-submit owner origin changed")
            yield module
        finally:
            sys.modules.pop(_PROTECTED_MODULE_NAME, None)
            if previous is not _MISSING_MODULE:
                sys.modules[_PROTECTED_MODULE_NAME] = previous
            _imp.release_lock()


def _protected_evidence_for_exact_owner(
    protected: types.ModuleType,
    evidence: object,
) -> object:
    expected = _protected_contract_path()
    expected_type = protected.ProtectedSubmitEvidence
    if isinstance(evidence, expected_type):
        return evidence
    snapshot_method = getattr(type(evidence), "snapshot", None)
    code = getattr(snapshot_method, "__code__", None)
    raw_source = getattr(code, "co_filename", None)
    if not isinstance(raw_source, str) or Path(raw_source).resolve() != expected:
        raise TypeError(
            "protected-submit evidence must come from the adjacent owner"
        )
    snapshot = evidence.snapshot()
    fields = tuple(expected_type.__dataclass_fields__)
    if any(not hasattr(snapshot, field) for field in fields):
        raise TypeError("protected-submit evidence fields differ")
    return expected_type(
        **{field: getattr(snapshot, field) for field in fields}
    )


def _require_canonical_path(path: Path, label: str) -> Path:
    if not isinstance(path, Path):
        raise LocalStateBindingError(f"{label} must be a pathlib.Path")
    raw = os.fspath(path)
    if (
        not path.is_absolute()
        or "\x00" in raw
        or any(part in {"", ".", ".."} for part in path.parts[1:])
        or unicodedata.normalize("NFC", raw) != raw
    ):
        raise LocalStateBindingError(
            f"{label} must be canonical absolute NFC text without traversal"
        )
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise LocalStateBindingError(f"{label} is unavailable: {exc}") from exc
    if resolved != path or Path(os.path.realpath(raw)) != path:
        raise LocalStateBindingError(
            f"{label} has lexical/realpath drift or a symlink"
        )
    return path


def _directory_identity(info: os.stat_result) -> _DirectoryIdentity:
    return _DirectoryIdentity(
        device=info.st_dev,
        inode=info.st_ino,
        uid=info.st_uid,
        mode=stat.S_IMODE(info.st_mode),
        mtime_ns=info.st_mtime_ns,
        ctime_ns=info.st_ctime_ns,
    )


def _open_exact_directory(
    path: Path,
    label: str,
    *,
    require_current_owner: bool,
) -> tuple[int, _DirectoryIdentity]:
    canonical = _require_canonical_path(path, label)
    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        descriptor = os.open("/", flags)
    except OSError as exc:
        raise LocalStateBindingError(
            f"cannot open filesystem root for {label}: {exc}"
        ) from exc
    try:
        for component in canonical.parts[1:]:
            entries = os.listdir(descriptor)
            if component not in entries:
                raise LocalStateBindingError(
                    f"{label} component uses a case/Unicode alias: {component!r}"
                )
            before = os.stat(
                component,
                dir_fd=descriptor,
                follow_symlinks=False,
            )
            if stat.S_ISLNK(before.st_mode) or not stat.S_ISDIR(before.st_mode):
                raise LocalStateBindingError(
                    f"{label} contains a symlink or non-directory ancestor"
                )
            child = os.open(component, flags, dir_fd=descriptor)
            after = os.fstat(child)
            if (
                before.st_dev,
                before.st_ino,
                before.st_mode,
            ) != (
                after.st_dev,
                after.st_ino,
                after.st_mode,
            ):
                os.close(child)
                raise LocalStateBindingError(
                    f"{label} directory identity changed while opening"
                )
            os.close(descriptor)
            descriptor = child
        info = os.fstat(descriptor)
        if not stat.S_ISDIR(info.st_mode):
            raise LocalStateBindingError(f"{label} is not a directory")
        if (
            require_current_owner
            and hasattr(os, "getuid")
            and info.st_uid != os.getuid()
        ):
            raise LocalStateBindingError(
                f"{label} is not owned by the current user"
            )
        return descriptor, _directory_identity(info)
    except OSError as exc:
        os.close(descriptor)
        raise LocalStateBindingError(
            f"{label} changed or became unavailable while opening: {exc}"
        ) from exc
    except BaseException:
        os.close(descriptor)
        raise


def _read_file_once(
    directory_descriptor: int,
    name: str,
    label: str,
) -> tuple[bytes, _FileIdentity]:
    before = os.stat(
        name,
        dir_fd=directory_descriptor,
        follow_symlinks=False,
    )
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise LocalStateBindingError(
            f"{label} must be a regular no-follow file"
        )
    if (
        hasattr(os, "getuid")
        and before.st_uid != os.getuid()
    ):
        raise LocalStateBindingError(
            f"{label} is not owned by the current user"
        )
    if before.st_size < 1 or before.st_size > _MAX_LEDGER_BYTES:
        raise LocalStateBindingError(f"{label} size is outside the safe bound")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(
        name,
        flags,
        dir_fd=directory_descriptor,
    )
    try:
        opened = os.fstat(descriptor)
        if (
            before.st_dev,
            before.st_ino,
            before.st_mode,
        ) != (
            opened.st_dev,
            opened.st_ino,
            opened.st_mode,
        ):
            raise LocalStateBindingError(
                f"{label} identity changed before descriptor binding"
            )
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, _READ_CHUNK_SIZE)
            if not chunk:
                break
            total += len(chunk)
            if total > _MAX_LEDGER_BYTES:
                raise LocalStateBindingError(
                    f"{label} exceeds the safe read bound"
                )
            chunks.append(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    current = os.stat(
        name,
        dir_fd=directory_descriptor,
        follow_symlinks=False,
    )
    stable_fields = (
        "st_dev",
        "st_ino",
        "st_uid",
        "st_mode",
        "st_size",
        "st_mtime_ns",
        "st_ctime_ns",
    )
    expected = tuple(getattr(opened, field) for field in stable_fields)
    if (
        tuple(getattr(after, field) for field in stable_fields) != expected
        or tuple(getattr(current, field) for field in stable_fields) != expected
    ):
        raise LocalStateBindingError(f"{label} changed during stable read")
    data = b"".join(chunks)
    if len(data) != opened.st_size:
        raise LocalStateBindingError(f"{label} size changed during stable read")
    artifact_sha256 = hashlib.sha256(data).hexdigest()
    return data, _FileIdentity(
        device=opened.st_dev,
        inode=opened.st_ino,
        uid=opened.st_uid,
        mode=stat.S_IMODE(opened.st_mode),
        size=opened.st_size,
        mtime_ns=opened.st_mtime_ns,
        ctime_ns=opened.st_ctime_ns,
        sha256=artifact_sha256,
    )


def _require_exact_ledger_only(directory_descriptor: int) -> None:
    entries = os.listdir(directory_descriptor)
    if entries != [LEDGER_BASENAME]:
        raise LocalStateBindingError(
            "derived local directory must contain only execution-batch-v3.json"
        )


def _path_digest(path: Path, domain: bytes) -> str:
    return hashlib.sha256(
        domain + b"\0" + os.fsencode(path)
    ).hexdigest()


def _text_digest(value: str, domain: bytes) -> str:
    return hashlib.sha256(domain + b"\0" + value.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class _LedgerCapture:
    data: bytes
    document: dict[str, Any]
    local_dir_identity: _DirectoryIdentity
    file_identity: _FileIdentity


def _capture_ledger(
    paths: LocalStatePaths | tuple[Path, Path],
    protected: types.ModuleType,
) -> _LedgerCapture:
    if isinstance(paths, LocalStatePaths):
        local_dir = paths.local_dir
        ledger_path = paths.ledger_path
    else:
        local_dir, ledger_path = paths

    descriptor, local_identity = _open_exact_directory(
        local_dir,
        "derived local directory",
        require_current_owner=True,
    )
    try:
        _require_exact_ledger_only(descriptor)
        first_data, first_identity = _read_file_once(
            descriptor,
            LEDGER_BASENAME,
            "execution-batch /3 ledger",
        )
        second_data, second_identity = _read_file_once(
            descriptor,
            LEDGER_BASENAME,
            "execution-batch /3 ledger replay",
        )
        _require_exact_ledger_only(descriptor)
    finally:
        os.close(descriptor)
    if first_data != second_data or first_identity != second_identity:
        raise LocalStateBindingError(
            "execution-batch /3 changed across stable reads"
        )

    try:
        with protected._skill_owner_graph() as modules:
            batch_owner = modules["execution_batch"]
            resource_owner = modules["resource_efficiency"]
            stable_owner = modules["gaussian_rtwin_pbs"]
            owner_path_1, owner_data_1, owner_sha_1 = (
                stable_owner.read_stable_bytes(
                    ledger_path,
                    "local-state execution-batch /3",
                )
            )
            owner_path_2, owner_data_2, owner_sha_2 = (
                stable_owner.read_stable_bytes(
                    ledger_path,
                    "local-state execution-batch /3 replay",
                )
            )
            if (
                owner_path_1 != ledger_path
                or owner_path_2 != ledger_path
                or owner_data_1 != first_data
                or owner_data_2 != first_data
                or owner_sha_1 != first_identity.sha256
                or owner_sha_2 != first_identity.sha256
            ):
                raise LocalStateBindingError(
                    "existing stable-byte owner observed ledger drift"
                )
            try:
                parsed = json.loads(
                    first_data.decode("utf-8"),
                    parse_constant=batch_owner._reject_constant,
                    object_pairs_hook=batch_owner._reject_duplicates,
                )
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise LocalStateBindingError(
                    "execution-batch /3 is not strict UTF-8 JSON"
                ) from exc
            if not isinstance(parsed, dict):
                raise LocalStateBindingError(
                    "execution-batch /3 top level must be an object"
                )
            document = resource_owner.validate_ledger(parsed)
    except LocalStateBindingError:
        raise
    except Exception as exc:
        raise LocalStateBindingError(
            f"existing execution-batch /3 owner rejected ledger: {exc}"
        ) from exc

    replay_descriptor, replay_local_identity = _open_exact_directory(
        local_dir,
        "derived local directory replay",
        require_current_owner=True,
    )
    try:
        _require_exact_ledger_only(replay_descriptor)
        replay_data, replay_file_identity = _read_file_once(
            replay_descriptor,
            LEDGER_BASENAME,
            "execution-batch /3 final replay",
        )
        _require_exact_ledger_only(replay_descriptor)
    finally:
        os.close(replay_descriptor)
    if (
        replay_local_identity != local_identity
        or replay_file_identity != first_identity
        or replay_data != first_data
    ):
        raise LocalStateBindingError(
            "local directory or ledger identity changed during owner replay"
        )
    return _LedgerCapture(
        data=first_data,
        document=copy.deepcopy(document),
        local_dir_identity=local_identity,
        file_identity=first_identity,
    )


def _derive_paths(
    workspace_root: Path,
    ledger_path: Path,
    *,
    project: str,
    attempt_id: str,
) -> tuple[Path, Path, _DirectoryIdentity]:
    if PROJECT_RE.fullmatch(project) is None:
        raise LocalStateBindingError("owner-derived project is unsafe")
    if ATTEMPT_RE.fullmatch(attempt_id) is None:
        raise LocalStateBindingError("owner-derived attempt ID is unsafe")
    root_descriptor, root_identity = _open_exact_directory(
        workspace_root,
        "reviewed workspace root",
        require_current_owner=True,
    )
    os.close(root_descriptor)
    local_dir = workspace_root / OUTPUTS_COMPONENT / project / attempt_id
    expected_ledger = local_dir / LEDGER_BASENAME
    if ledger_path != expected_ledger:
        raise LocalStateBindingError(
            "exact ledger path differs from the owner-derived fixed layout"
        )
    _require_canonical_path(ledger_path, "exact execution-batch ledger path")
    try:
        local_dir.relative_to(workspace_root)
    except ValueError as exc:
        raise LocalStateBindingError(
            "derived local directory is outside the reviewed workspace root"
        ) from exc
    return local_dir, expected_ledger, root_identity


def _build_document(
    *,
    workspace_root: Path,
    local_dir: Path,
    ledger: _LedgerCapture,
    protected_document: dict[str, Any],
) -> dict[str, Any]:
    identity = protected_document["identity"]
    relative_local = PurePosixPath(
        OUTPUTS_COMPONENT,
        identity["project"],
        identity["attempt_id"],
    )
    relative_ledger = relative_local / LEDGER_BASENAME
    ledger_document = ledger.document
    return finalize(
        {
            "schema": SCHEMA,
            "owner": OWNER,
            "layout": {
                "schema": LAYOUT_SCHEMA,
                "relative_local_dir": str(relative_local),
                "relative_ledger_path": str(relative_ledger),
                "ledger_basename": LEDGER_BASENAME,
            },
            "path_bindings": {
                "workspace_root_path_sha256": _path_digest(
                    workspace_root,
                    b"auto-g16-workspace-root-path/1",
                ),
                "local_dir_path_sha256": _path_digest(
                    local_dir,
                    b"auto-g16-local-dir-path/1",
                ),
            },
            "ledger": {
                "schema": ledger_document["schema"],
                "artifact_sha256": ledger.file_identity.sha256,
                "artifact_size_bytes": ledger.file_identity.size,
                "ledger_sha256": ledger_document["ledger_sha256"],
                "revision": ledger_document["revision"],
                "resource_state_revision": ledger_document[
                    "resource_state_revision"
                ],
                "resource_state_sha256": ledger_document[
                    "resource_state_sha256"
                ],
                "batch_id_sha256": _text_digest(
                    ledger_document["batch"]["batch_id"],
                    b"auto-g16-execution-batch-id/1",
                ),
                "review_sha256": ledger_document["batch"]["review_sha256"],
            },
            "identity": {
                "project": identity["project"],
                "attempt_id": identity["attempt_id"],
                "scientific_task_id": identity["scientific_task_id"],
                "input_sha256": identity["input_sha256"],
                "idempotency_key_sha256": identity[
                    "idempotency_key_sha256"
                ],
            },
            "protected_submit": {
                "schema": protected_document["schema"],
                "bundle_id": protected_document["bundle_id"],
                "bundle_payload_sha256": protected_document[
                    "bundle_payload_sha256"
                ],
            },
            "policy": {
                "future_protected_successor_only": True,
                "no_execution_authorization": True,
                "local_state_directory_creation_performed": False,
                "local_state_permissions_changed": False,
                "ledger_lock_acquired": False,
                "ledger_write_performed": False,
                "external_actions_performed": False,
                "legacy_cli_unchanged": True,
                "historical_migration": False,
                "protected_state_policy": PROTECTED_STATE_POLICY,
            },
            "binding_payload_sha256": "",
        }
    )


class LocalStateBindingOwner:
    """Derive and seal only the deterministic read-only local-state closure."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime],
        _factory_token: object,
    ) -> None:
        if _factory_token not in {_SEAL_TOKEN, _TEST_OWNER_TOKEN}:
            raise TypeError(
                "LocalStateBindingOwner requires a fixed owner factory"
            )
        self._clock = clock

    @classmethod
    def production(cls) -> "LocalStateBindingOwner":
        return cls(clock=_utc_now, _factory_token=_SEAL_TOKEN)

    @classmethod
    def _for_testing_with_clock(
        cls,
        clock: Callable[[], datetime],
        *,
        _test_token: object,
    ) -> "LocalStateBindingOwner":
        if _test_token is not _TEST_OWNER_TOKEN:
            raise TypeError("private local-state test factory token differs")
        return cls(clock=clock, _factory_token=_TEST_OWNER_TOKEN)

    def _seal_impl(
        self,
        evidence: LocalStateBindingEvidence,
    ) -> SealedLocalStateBinding:
        if not isinstance(evidence, LocalStateBindingEvidence):
            raise LocalStateBindingError(
                "local-state evidence must use the typed owner input"
            )
        snapshot = evidence.snapshot()
        current = self._clock()
        if (
            not isinstance(current, datetime)
            or current.tzinfo is None
            or current.utcoffset() is None
        ):
            raise LocalStateBindingError(
                "local-state owner clock must return timezone-aware UTC"
            )
        current = current.astimezone(timezone.utc)
        workspace_root = _require_canonical_path(
            snapshot.workspace_root,
            "reviewed workspace root",
        )
        ledger_path = Path(snapshot.ledger_path)

        with _exact_protected_contract() as protected:
            exact_protected_evidence = _protected_evidence_for_exact_owner(
                protected,
                snapshot.protected_submit_evidence,
            )
            protected_owner = (
                protected.ProtectedSubmitContractOwner.production()
            )
            try:
                protected_bundle = protected_owner._seal_at(
                    exact_protected_evidence,
                    current,
                )
                protected_bundle.assert_owner_sealed()
                protected_document = protected_bundle.document()
            except Exception as exc:
                raise LocalStateBindingError(
                    f"protected-submit owner rejected local-state evidence: {exc}"
                ) from exc

            identity = protected_document["identity"]
            local_dir, expected_ledger, workspace_identity = _derive_paths(
                workspace_root,
                ledger_path,
                project=identity["project"],
                attempt_id=identity["attempt_id"],
            )
            capture = _capture_ledger(
                (local_dir, expected_ledger),
                protected,
            )
            typed_ledger = copy.deepcopy(
                dict(exact_protected_evidence.execution_ledger)
            )
            if capture.document != typed_ledger:
                raise LocalStateBindingError(
                    "exact ledger bytes differ from PR4D typed ledger evidence"
                )
            root_descriptor, final_workspace_identity = _open_exact_directory(
                workspace_root,
                "reviewed workspace root final replay",
                require_current_owner=True,
            )
            os.close(root_descriptor)
            if final_workspace_identity != workspace_identity:
                raise LocalStateBindingError(
                    "workspace-root identity changed during owner replay"
                )

        paths = LocalStatePaths._from_owner(
            workspace_root=workspace_root,
            local_dir=local_dir,
            ledger_path=expected_ledger,
            workspace_identity=workspace_identity,
            local_dir_identity=capture.local_dir_identity,
            ledger_identity=capture.file_identity,
            token=_SEAL_TOKEN,
        )
        document = _build_document(
            workspace_root=workspace_root,
            local_dir=local_dir,
            ledger=capture,
            protected_document=protected_document,
        )
        return SealedLocalStateBinding._from_owner(
            document,
            paths,
            token=_SEAL_TOKEN,
        )

    def _seal(
        self,
        evidence: LocalStateBindingEvidence,
    ) -> SealedLocalStateBinding:
        try:
            return self._seal_impl(evidence)
        except LocalStateBindingError:
            raise
        except OSError as exc:
            raise LocalStateBindingError(
                f"local-state filesystem evidence became unavailable: {exc}"
            ) from exc

    def derive(self, evidence: LocalStateBindingEvidence) -> LocalStatePaths:
        """Return only owner-derived paths; no caller local directory exists."""
        return self._seal(evidence).paths

    def seal(
        self,
        evidence: LocalStateBindingEvidence,
    ) -> SealedLocalStateBinding:
        return self._seal(evidence)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _assert_paths_current_impl(paths: LocalStatePaths) -> _LedgerCapture:
    paths.assert_owner_sealed()
    root_descriptor, root_identity = _open_exact_directory(
        paths.workspace_root,
        "reviewed workspace root replay",
        require_current_owner=True,
    )
    os.close(root_descriptor)
    if root_identity != paths.workspace_identity:
        raise LocalStateBindingError("workspace-root identity changed")
    with _exact_protected_contract() as protected:
        capture = _capture_ledger(paths, protected)
    if (
        capture.local_dir_identity != paths.local_dir_identity
        or capture.file_identity != paths.ledger_identity
    ):
        raise LocalStateBindingError(
            "local directory or ledger identity changed after sealing"
        )
    return capture


def _assert_paths_current(paths: LocalStatePaths) -> _LedgerCapture:
    try:
        return _assert_paths_current_impl(paths)
    except LocalStateBindingError:
        raise
    except OSError as exc:
        raise LocalStateBindingError(
            f"local-state replay evidence became unavailable: {exc}"
        ) from exc


def _assert_binding_current(binding: SealedLocalStateBinding) -> None:
    document = validate_local_state_binding(binding.document())
    capture = _assert_paths_current(binding.paths)
    current_ledger = capture.document
    expected = document["ledger"]
    observed = {
        "schema": current_ledger["schema"],
        "artifact_sha256": capture.file_identity.sha256,
        "artifact_size_bytes": capture.file_identity.size,
        "ledger_sha256": current_ledger["ledger_sha256"],
        "revision": current_ledger["revision"],
        "resource_state_revision": current_ledger[
            "resource_state_revision"
        ],
        "resource_state_sha256": current_ledger[
            "resource_state_sha256"
        ],
        "batch_id_sha256": _text_digest(
            current_ledger["batch"]["batch_id"],
            b"auto-g16-execution-batch-id/1",
        ),
        "review_sha256": current_ledger["batch"]["review_sha256"],
    }
    if observed != expected:
        raise LocalStateBindingError(
            "current execution-batch /3 differs from sealed binding"
        )
    path_bindings = document["path_bindings"]
    if (
        path_bindings["workspace_root_path_sha256"]
        != _path_digest(
            binding.paths.workspace_root,
            b"auto-g16-workspace-root-path/1",
        )
        or path_bindings["local_dir_path_sha256"]
        != _path_digest(
            binding.paths.local_dir,
            b"auto-g16-local-dir-path/1",
        )
    ):
        raise LocalStateBindingError("sealed path digest differs")
