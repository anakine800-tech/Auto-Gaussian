#!/usr/bin/env python3
"""Reserve and materialize one exact PR4K lifecycle locally, then stop.

This owner performs only the bounded PR4K prefix:

1. exact-origin PR4K seal and current replay;
2. exact nested PR4D single-use reservation;
3. no-clobber materialization of the already sealed PR4F stage bytes; and
4. final no-clobber publication of one sealed local-state record.

It exposes no adapter, runner, command, transfer, qsub, retry, rollback,
cleanup, cancellation, deletion, migration, or reconciliation operation.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import stat
import sys
import threading
import types
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator


SCHEMA = "auto-g16-protected-local-materialization/1"
OWNER = "auto-g16-protected-local-materialization-owner"
LIFECYCLE_SCHEMA = (
    "auto-g16-protected-lifecycle-structural-projection/1"
)
LIFECYCLE_MODULE_NAME = "protected_lifecycle_contract"
STATE_BASENAME = "protected-local-materialization-v1.json"
LEDGER_BASENAME = "execution-batch-v3.json"
SCOPE = {
    "reserve": True,
    "materialize_exact_stage_bytes": True,
    "publish_local_state": True,
    "invoke_adapter": False,
    "transfer": False,
    "submit": False,
    "status": False,
    "fetch": False,
    "cancel": False,
    "cleanup": False,
    "delete": False,
    "arbitrary_command": False,
}
STATUS = {
    "reserved": True,
    "submission_uncertain": True,
    "local_materialization_complete": True,
    "state_publication_complete": True,
    "effects_performed": False,
    "qsub_invocation_started": False,
    "long_process_owner_lifecycle_gate_open": False,
    "adapter_connected": False,
    "reconciliation_performed": False,
    "live_validation_performed": False,
}
POLICY = {
    "exact_pr4k_evidence_only": True,
    "reserve_before_materialize": True,
    "no_clobber": True,
    "state_record_published_last": True,
    "automatic_retry": False,
    "automatic_cancel": False,
    "automatic_cleanup": False,
    "automatic_delete": False,
    "automatic_rollback": False,
    "historical_migration": False,
    "legacy_cli_unchanged": True,
    "legacy_adapter_remains_fail_closed": True,
}
SHA_RE = re.compile(r"^[a-f0-9]{64}$")
MATERIALIZATION_ID_RE = re.compile(
    r"^protected-local-materialization-[a-f0-9]{64}$"
)
LIFECYCLE_ID_RE = re.compile(
    r"^protected-lifecycle-[a-f0-9]{64}$"
)
INVOCATION_ID_RE = re.compile(
    r"^protected-invocation-[a-f0-9]{64}$"
)
ATTEMPT_ID_RE = re.compile(r"^qsub-attempt-[a-f0-9]{64}$")
_SEAL_TOKEN = object()
_TEST_OWNER_TOKEN = object()
_MODULE_LOCK = threading.RLock()
_OWNER_READ_CHUNK_SIZE = 64 * 1024
_MAX_OWNER_SOURCE_BYTES = 3 * 1024 * 1024
_MAX_STATE_BYTES = 4 * 1024 * 1024
_MAX_PUBLIC_JSON_DEPTH = 64
_FILE_IDENTITY_FIELDS = (
    "device",
    "inode",
    "uid",
    "mode",
    "size_bytes",
    "mtime_ns",
    "ctime_ns",
    "nlink",
    "sha256",
)
_DIRECTORY_IDENTITY_FIELDS = (
    "device",
    "inode",
    "uid",
    "mode",
    "mtime_ns",
    "ctime_ns",
)


class ProtectedLocalMaterializationError(ValueError):
    """The bounded local materialization cannot be proved safely."""


def canonical_bytes(value: Any) -> bytes:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ProtectedLocalMaterializationError(
            f"local materialization value is not canonical JSON: {exc}"
        ) from exc
    return (encoded + "\n").encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _rebuild_public_json(
    value: object,
    *,
    depth: int = 0,
    active: set[int] | None = None,
) -> object:
    if depth > _MAX_PUBLIC_JSON_DEPTH:
        raise ProtectedLocalMaterializationError(
            "local materialization state exceeds the nesting bound"
        )
    value_type = type(value)
    if value_type in {str, int, bool} or value is None:
        return value
    if value_type is float:
        if not math.isfinite(value):
            raise ProtectedLocalMaterializationError(
                "local materialization state contains a non-finite number"
            )
        return value
    if value_type not in {dict, list}:
        raise ProtectedLocalMaterializationError(
            "local materialization state accepts only exact builtin JSON"
        )
    if active is None:
        active = set()
    identity = id(value)
    if identity in active:
        raise ProtectedLocalMaterializationError(
            "local materialization state contains a cycle"
        )
    active.add(identity)
    try:
        if value_type is list:
            return [
                _rebuild_public_json(
                    item,
                    depth=depth + 1,
                    active=active,
                )
                for item in value
            ]
        rebuilt: dict[str, object] = {}
        for key, item in value.items():
            if type(key) is not str:
                raise ProtectedLocalMaterializationError(
                    "local materialization object keys must be strings"
                )
            rebuilt[key] = _rebuild_public_json(
                item,
                depth=depth + 1,
                active=active,
            )
        return rebuilt
    except RuntimeError as exc:
        raise ProtectedLocalMaterializationError(
            "local materialization state changed during rebuild"
        ) from exc
    finally:
        active.remove(identity)


def _exact(value: object, fields: set[str], label: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != fields:
        raise ProtectedLocalMaterializationError(
            f"{label} must contain exactly {sorted(fields)}"
        )
    return value


def _text(value: object, label: str) -> str:
    if type(value) is not str or not value:
        raise ProtectedLocalMaterializationError(
            f"{label} must be a non-empty string"
        )
    return value


def _sha(value: object, label: str) -> str:
    if type(value) is not str or SHA_RE.fullmatch(value) is None:
        raise ProtectedLocalMaterializationError(
            f"{label} must be a lowercase SHA-256"
        )
    return value


def _integer(value: object, label: str, *, minimum: int = 0) -> int:
    if type(value) is float and value.is_integer() and value >= minimum:
        return int(value)
    if type(value) is not int or value < minimum:
        raise ProtectedLocalMaterializationError(
            f"{label} must be an integer >= {minimum}"
        )
    return value


def _fixed_mapping(
    value: object,
    expected: dict[str, bool],
    label: str,
) -> dict[str, bool]:
    result = _exact(value, set(expected), label)
    for field, expected_value in expected.items():
        if type(result[field]) is not bool or result[field] is not expected_value:
            raise ProtectedLocalMaterializationError(
                f"{label}.{field} must be exact boolean {expected_value!r}"
            )
    return result


def _utc_time(value: object, label: str) -> str:
    raw = _text(value, label)
    if not raw.endswith("Z"):
        raise ProtectedLocalMaterializationError(
            f"{label} must be explicit UTC"
        )
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProtectedLocalMaterializationError(
            f"{label} must be an RFC 3339 timestamp"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ProtectedLocalMaterializationError(
            f"{label} must be timezone-aware"
        )
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _relative_basename(value: object, label: str) -> str:
    raw = _text(value, label)
    if (
        raw in {".", ".."}
        or "/" in raw
        or "\\" in raw
        or "\x00" in raw
        or Path(raw).name != raw
    ):
        raise ProtectedLocalMaterializationError(
            f"{label} must be one canonical basename"
        )
    return raw


def _file_identity_document(
    value: object,
    label: str,
) -> dict[str, Any]:
    result = _exact(value, set(_FILE_IDENTITY_FIELDS), label)
    for field in _FILE_IDENTITY_FIELDS[:-1]:
        result[field] = _integer(result[field], f"{label}.{field}")
    _sha(result["sha256"], f"{label}.sha256")
    if result["nlink"] != 1:
        raise ProtectedLocalMaterializationError(
            f"{label}.nlink must be exactly one"
        )
    return result


def _validate_artifact(
    value: object,
    label: str,
    *,
    with_identity: bool,
) -> dict[str, Any]:
    fields = {
        "role",
        "relative_name",
        "order",
        "sha256",
        "size_bytes",
    }
    if with_identity:
        fields.add("identity")
    result = _exact(value, fields, label)
    _text(result["role"], f"{label}.role")
    _relative_basename(
        result["relative_name"],
        f"{label}.relative_name",
    )
    result["order"] = _integer(
        result["order"],
        f"{label}.order",
        minimum=1,
    )
    _sha(result["sha256"], f"{label}.sha256")
    result["size_bytes"] = _integer(
        result["size_bytes"],
        f"{label}.size_bytes",
    )
    if with_identity:
        identity = _file_identity_document(
            result["identity"],
            f"{label}.identity",
        )
        if (
            identity["sha256"] != result["sha256"]
            or identity["size_bytes"] != result["size_bytes"]
        ):
            raise ProtectedLocalMaterializationError(
                f"{label} portable and local identities differ"
            )
    return result


def _state_payload_sha256(document: dict[str, Any]) -> str:
    projection = copy.deepcopy(document)
    projection["materialization_id"] = (
        "protected-local-materialization-" + "0" * 64
    )
    projection["state_payload_sha256"] = ""
    return digest(projection)


def validate_protected_local_materialization_state(
    value: object,
) -> dict[str, Any]:
    """Validate the portable/local state record without issuing a seal."""

    document = _rebuild_public_json(value)
    canonical_bytes(document)
    document = _exact(
        document,
        {
            "schema",
            "owner",
            "materialization_id",
            "lifecycle",
            "invocation",
            "reservation",
            "local_state",
            "ledger",
            "stage_plan",
            "materialized_files",
            "directory_topology",
            "publication",
            "scope",
            "status",
            "policy",
            "state_payload_sha256",
        },
        "local materialization state",
    )
    if document["schema"] != SCHEMA or document["owner"] != OWNER:
        raise ProtectedLocalMaterializationError(
            "local materialization schema or owner differs"
        )
    if (
        type(document["materialization_id"]) is not str
        or MATERIALIZATION_ID_RE.fullmatch(
            document["materialization_id"]
        )
        is None
    ):
        raise ProtectedLocalMaterializationError(
            "materialization_id is malformed"
        )

    lifecycle = _exact(
        document["lifecycle"],
        {
            "schema",
            "lifecycle_id",
            "structural_projection_sha256",
        },
        "lifecycle",
    )
    if lifecycle["schema"] != LIFECYCLE_SCHEMA:
        raise ProtectedLocalMaterializationError(
            "lifecycle schema differs"
        )
    if (
        type(lifecycle["lifecycle_id"]) is not str
        or LIFECYCLE_ID_RE.fullmatch(lifecycle["lifecycle_id"]) is None
    ):
        raise ProtectedLocalMaterializationError(
            "lifecycle_id is malformed"
        )
    _sha(
        lifecycle["structural_projection_sha256"],
        "lifecycle structural projection",
    )

    invocation = _exact(
        document["invocation"],
        {
            "schema",
            "invocation_id",
            "invocation_payload_sha256",
            "stage_manifest_sha256",
            "stage_artifact_count",
        },
        "invocation",
    )
    if invocation["schema"] != "auto-g16-protected-invocation-bundle/1":
        raise ProtectedLocalMaterializationError(
            "invocation schema differs"
        )
    if (
        type(invocation["invocation_id"]) is not str
        or INVOCATION_ID_RE.fullmatch(invocation["invocation_id"]) is None
    ):
        raise ProtectedLocalMaterializationError(
            "invocation_id is malformed"
        )
    _sha(
        invocation["invocation_payload_sha256"],
        "invocation payload",
    )
    _sha(invocation["stage_manifest_sha256"], "stage manifest")
    invocation["stage_artifact_count"] = _integer(
        invocation["stage_artifact_count"],
        "stage_artifact_count",
        minimum=1,
    )

    reservation = _exact(
        document["reservation"],
        {
            "bundle_id",
            "bundle_payload_sha256",
            "attempt_id",
            "consumption_sha256",
            "consumed_at",
            "submission_state",
            "automatic_retry",
            "reconciliation",
        },
        "reservation",
    )
    _text(reservation["bundle_id"], "reservation.bundle_id")
    _sha(
        reservation["bundle_payload_sha256"],
        "reservation.bundle_payload_sha256",
    )
    if (
        type(reservation["attempt_id"]) is not str
        or ATTEMPT_ID_RE.fullmatch(reservation["attempt_id"]) is None
    ):
        raise ProtectedLocalMaterializationError(
            "reservation.attempt_id is malformed"
        )
    _sha(
        reservation["consumption_sha256"],
        "reservation.consumption_sha256",
    )
    reservation["consumed_at"] = _utc_time(
        reservation["consumed_at"],
        "reservation.consumed_at",
    )
    if (
        reservation["submission_state"] != "submission_uncertain"
        or reservation["automatic_retry"] is not False
        or reservation["reconciliation"]
        != "existing_read_only_reconciliation_only"
    ):
        raise ProtectedLocalMaterializationError(
            "reservation state differs"
        )

    local_state = _exact(
        document["local_state"],
        {
            "binding_schema",
            "binding_payload_sha256",
            "relative_local_dir",
            "ledger_basename",
            "workspace_root_path_sha256",
            "local_dir_path_sha256",
            "initial_ledger_identity_sha256",
        },
        "local_state",
    )
    if (
        local_state["binding_schema"] != "auto-g16-local-state-binding/1"
        or local_state["ledger_basename"] != LEDGER_BASENAME
    ):
        raise ProtectedLocalMaterializationError(
            "local-state predecessor differs"
        )
    _text(local_state["relative_local_dir"], "relative_local_dir")
    for field in (
        "binding_payload_sha256",
        "workspace_root_path_sha256",
        "local_dir_path_sha256",
        "initial_ledger_identity_sha256",
    ):
        _sha(local_state[field], f"local_state.{field}")

    ledger = _exact(
        document["ledger"],
        {"relative_name", "sha256", "size_bytes", "identity"},
        "ledger",
    )
    if ledger["relative_name"] != LEDGER_BASENAME:
        raise ProtectedLocalMaterializationError(
            "ledger basename differs"
        )
    _sha(ledger["sha256"], "ledger.sha256")
    ledger["size_bytes"] = _integer(
        ledger["size_bytes"],
        "ledger.size_bytes",
        minimum=1,
    )
    ledger_identity = _file_identity_document(
        ledger["identity"],
        "ledger.identity",
    )
    if (
        ledger_identity["sha256"] != ledger["sha256"]
        or ledger_identity["size_bytes"] != ledger["size_bytes"]
    ):
        raise ProtectedLocalMaterializationError(
            "ledger portable and local identities differ"
        )

    stage = _exact(
        document["stage_plan"],
        {"schema", "manifest_sha256", "artifact_count", "artifacts"},
        "stage_plan",
    )
    if stage["schema"] != "auto-g16-legacy-stage-byte-plan/1":
        raise ProtectedLocalMaterializationError(
            "stage-plan schema differs"
        )
    _sha(stage["manifest_sha256"], "stage_plan.manifest_sha256")
    stage["artifact_count"] = _integer(
        stage["artifact_count"],
        "stage_plan.artifact_count",
        minimum=1,
    )
    if (
        type(stage["artifacts"]) is not list
        or len(stage["artifacts"]) != stage["artifact_count"]
        or stage["artifact_count"]
        != invocation["stage_artifact_count"]
    ):
        raise ProtectedLocalMaterializationError(
            "stage-plan artifact count differs"
        )
    portable_artifacts = []
    names = set()
    for index, raw in enumerate(stage["artifacts"], start=1):
        artifact = _validate_artifact(
            raw,
            f"stage_plan.artifacts[{index - 1}]",
            with_identity=False,
        )
        if artifact["order"] != index:
            raise ProtectedLocalMaterializationError(
                "stage artifact order differs"
            )
        if artifact["relative_name"] in names:
            raise ProtectedLocalMaterializationError(
                "stage artifact basename is duplicated"
            )
        if artifact["relative_name"] in {LEDGER_BASENAME, STATE_BASENAME}:
            raise ProtectedLocalMaterializationError(
                "stage artifact collides with owner state"
            )
        names.add(artifact["relative_name"])
        portable_artifacts.append(artifact)
    if stage["manifest_sha256"] != invocation["stage_manifest_sha256"]:
        raise ProtectedLocalMaterializationError(
            "stage manifest projections differ"
        )

    materialized = document["materialized_files"]
    if type(materialized) is not list or len(materialized) != len(
        portable_artifacts
    ):
        raise ProtectedLocalMaterializationError(
            "materialized file count differs"
        )
    for index, (raw, portable) in enumerate(
        zip(materialized, portable_artifacts, strict=True)
    ):
        entry = _validate_artifact(
            raw,
            f"materialized_files[{index}]",
            with_identity=True,
        )
        if {
            key: entry[key]
            for key in (
                "role",
                "relative_name",
                "order",
                "sha256",
                "size_bytes",
            )
        } != portable:
            raise ProtectedLocalMaterializationError(
                "materialized file differs from exact PR4F artifact"
            )

    topology = document["directory_topology"]
    expected_topology = (
        [LEDGER_BASENAME]
        + [item["relative_name"] for item in portable_artifacts]
        + [STATE_BASENAME]
    )
    if (
        type(topology) is not list
        or topology != expected_topology
        or len(set(topology)) != len(topology)
    ):
        raise ProtectedLocalMaterializationError(
            "materialized directory topology differs"
        )
    publication = _exact(
        document["publication"],
        {"state_basename", "published_last", "no_clobber"},
        "publication",
    )
    if (
        publication["state_basename"] != STATE_BASENAME
        or publication["published_last"] is not True
        or publication["no_clobber"] is not True
    ):
        raise ProtectedLocalMaterializationError(
            "state publication contract differs"
        )
    _fixed_mapping(document["scope"], SCOPE, "scope")
    _fixed_mapping(document["status"], STATUS, "status")
    _fixed_mapping(document["policy"], POLICY, "policy")
    _sha(document["state_payload_sha256"], "state_payload_sha256")
    if document["state_payload_sha256"] != _state_payload_sha256(document):
        raise ProtectedLocalMaterializationError(
            "state payload hash differs"
        )
    seed = digest(
        {
            "schema": "auto-g16-protected-local-materialization-id/1",
            "lifecycle_id": lifecycle["lifecycle_id"],
            "invocation_payload_sha256": invocation[
                "invocation_payload_sha256"
            ],
            "consumption_sha256": reservation["consumption_sha256"],
            "local_state_binding_payload_sha256": local_state[
                "binding_payload_sha256"
            ],
            "state_payload_sha256": document["state_payload_sha256"],
        }
    )
    if document["materialization_id"] != (
        f"protected-local-materialization-{seed}"
    ):
        raise ProtectedLocalMaterializationError(
            "materialization_id differs"
        )
    return document


@dataclass(frozen=True, slots=True)
class _OwnerFileSnapshot:
    canonical_path: Path
    device: int
    inode: int
    uid: int
    mode: int
    size: int
    mtime_ns: int
    ctime_ns: int
    sha256: str
    source_bytes: bytes


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
    size_bytes: int
    mtime_ns: int
    ctime_ns: int
    nlink: int
    sha256: str

    def document(self) -> dict[str, int | str]:
        return {
            "device": self.device,
            "inode": self.inode,
            "uid": self.uid,
            "mode": self.mode,
            "size_bytes": self.size_bytes,
            "mtime_ns": self.mtime_ns,
            "ctime_ns": self.ctime_ns,
            "nlink": self.nlink,
            "sha256": self.sha256,
        }


def _lifecycle_owner_path() -> Path:
    here = Path(__file__).resolve(strict=True)
    path = here.with_name(f"{LIFECYCLE_MODULE_NAME}.py")
    if path.is_symlink() or not path.is_file():
        raise ImportError(
            "exact adjacent protected lifecycle owner is unavailable"
        )
    resolved = path.resolve(strict=True)
    if resolved.parent != here.parent:
        raise ImportError(
            "protected lifecycle owner is not adjacent"
        )
    return resolved


def _stat_identity(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_uid,
        info.st_mode,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _stable_lifecycle_owner_snapshot() -> _OwnerFileSnapshot:
    path = _lifecycle_owner_path()
    descriptor = -1
    try:
        before = os.stat(path, follow_symlinks=False)
        if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
            raise ProtectedLocalMaterializationError(
                "protected lifecycle owner must be a regular file"
            )
        descriptor = os.open(
            path,
            os.O_RDONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
        )
        opened = os.fstat(descriptor)
        if _stat_identity(opened) != _stat_identity(before):
            raise ProtectedLocalMaterializationError(
                "protected lifecycle owner changed while opening"
            )
        if opened.st_size < 1 or opened.st_size > _MAX_OWNER_SOURCE_BYTES:
            raise ProtectedLocalMaterializationError(
                "protected lifecycle owner size is outside the bound"
            )
        chunks = []
        while True:
            chunk = os.read(descriptor, _OWNER_READ_CHUNK_SIZE)
            if not chunk:
                break
            chunks.append(chunk)
        after_descriptor = os.fstat(descriptor)
        after_path = os.stat(path, follow_symlinks=False)
    except OSError as exc:
        raise ProtectedLocalMaterializationError(
            f"protected lifecycle owner stable read failed: {exc}"
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if len(
        {
            _stat_identity(before),
            _stat_identity(opened),
            _stat_identity(after_descriptor),
            _stat_identity(after_path),
        }
    ) != 1:
        raise ProtectedLocalMaterializationError(
            "protected lifecycle owner identity drifted"
        )
    source_bytes = b"".join(chunks)
    if len(source_bytes) != opened.st_size:
        raise ProtectedLocalMaterializationError(
            "protected lifecycle owner stable read was short"
        )
    return _OwnerFileSnapshot(
        canonical_path=path,
        device=opened.st_dev,
        inode=opened.st_ino,
        uid=opened.st_uid,
        mode=opened.st_mode,
        size=opened.st_size,
        mtime_ns=opened.st_mtime_ns,
        ctime_ns=opened.st_ctime_ns,
        sha256=hashlib.sha256(source_bytes).hexdigest(),
        source_bytes=source_bytes,
    )


def _module_origin(module: types.ModuleType) -> tuple[Path, Path]:
    raw_file = getattr(module, "__file__", None)
    raw_origin = getattr(getattr(module, "__spec__", None), "origin", None)
    if (
        type(raw_file) is not str
        or not raw_file
        or type(raw_origin) is not str
        or not raw_origin
    ):
        raise ImportError("protected lifecycle owner has no exact origin")
    return Path(raw_file).resolve(), Path(raw_origin).resolve()


def _exact_lifecycle_module(
    evidence: object,
) -> tuple[types.ModuleType, _OwnerFileSnapshot]:
    snapshot = _stable_lifecycle_owner_snapshot()
    module = sys.modules.get(LIFECYCLE_MODULE_NAME)
    if not isinstance(module, types.ModuleType):
        raise ProtectedLocalMaterializationError(
            "exact protected lifecycle owner must already own the evidence"
        )
    if _module_origin(module) != (
        snapshot.canonical_path,
        snapshot.canonical_path,
    ):
        raise ProtectedLocalMaterializationError(
            "protected lifecycle owner origin differs"
        )
    if type(evidence) is not module.ProtectedLifecycleEvidence:
        raise TypeError(
            "materialization accepts only exact typed PR4K evidence"
        )
    if (
        hashlib.sha256(snapshot.source_bytes).hexdigest()
        != snapshot.sha256
    ):
        raise ProtectedLocalMaterializationError(
            "protected lifecycle owner snapshot differs"
        )
    return module, snapshot


def _trusted_now(clock: Callable[[], datetime]) -> datetime:
    value = clock()
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ProtectedLocalMaterializationError(
            "materialization owner clock must return aware UTC"
        )
    return value.astimezone(timezone.utc)


def _seal_current_lifecycle(
    module: types.ModuleType,
    evidence: object,
    *,
    current: datetime,
    testing: bool,
) -> object:
    if testing:
        owner = (
            module.ProtectedLifecycleContractOwner
            ._for_testing_with_clock(
                lambda: current,
                _test_token=module._TEST_OWNER_TOKEN,
            )
        )
    else:
        owner = module.ProtectedLifecycleContractOwner.production()
    sealed = owner.seal(evidence)
    sealed.assert_owner_sealed()
    original = module._utc_now
    module._utc_now = lambda: current
    try:
        sealed.assert_current()
    finally:
        module._utc_now = original
    return sealed


def _protected_submit_namespace(
    sealed_lifecycle: object,
) -> tuple[dict[str, Any], object]:
    invocation = sealed_lifecycle.protected_invocation_bundle
    evidence = invocation.protected_submit_evidence
    snapshot_method = getattr(type(evidence), "snapshot", None)
    namespace = getattr(snapshot_method, "__globals__", None)
    if not isinstance(namespace, dict):
        raise ProtectedLocalMaterializationError(
            "exact PR4D evidence owner namespace is unavailable"
        )
    snapshots = {
        item.name: item
        for item in invocation._predecessor_owner_snapshots
    }
    protected_snapshot = snapshots.get("protected_submit_contract")
    raw_file = namespace.get("__file__")
    if (
        protected_snapshot is None
        or type(raw_file) is not str
        or Path(raw_file).resolve()
        != protected_snapshot.canonical_path
        or hashlib.sha256(protected_snapshot.source_bytes).hexdigest()
        != protected_snapshot.sha256
        or type(evidence) is not namespace.get("ProtectedSubmitEvidence")
    ):
        raise ProtectedLocalMaterializationError(
            "exact PR4D evidence owner identity differs"
        )
    return namespace, evidence


def _reserve_protected_submit_once(
    sealed_lifecycle: object,
    *,
    current: datetime,
    testing: bool,
    state_root: Path | None,
) -> object:
    namespace, evidence = _protected_submit_namespace(sealed_lifecycle)
    owner_type = namespace["ProtectedSubmitContractOwner"]
    if testing:
        if not isinstance(state_root, Path):
            raise ProtectedLocalMaterializationError(
                "private test reservation root is unavailable"
            )
        owner = owner_type._for_testing_with_clock(
            state_root,
            lambda: current,
            _test_token=namespace["_TEST_OWNER_TOKEN"],
        )
    else:
        owner = owner_type.production()
    reserved = owner.reserve_once(evidence)
    reserved.assert_owner_sealed()
    if (
        reserved.submission_state != "submission_uncertain"
        or reserved.automatic_retry is not False
    ):
        raise ProtectedLocalMaterializationError(
            "PR4D reservation state differs"
        )
    return reserved


def _directory_identity(info: os.stat_result) -> _DirectoryIdentity:
    if not stat.S_ISDIR(info.st_mode):
        raise ProtectedLocalMaterializationError(
            "local state path is not a directory"
        )
    return _DirectoryIdentity(
        device=info.st_dev,
        inode=info.st_ino,
        uid=info.st_uid,
        mode=stat.S_IMODE(info.st_mode),
        mtime_ns=info.st_mtime_ns,
        ctime_ns=info.st_ctime_ns,
    )


def _file_identity(
    info: os.stat_result,
    sha256: str,
) -> _FileIdentity:
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ProtectedLocalMaterializationError(
            "materialized entry must be one regular no-hardlink file"
        )
    return _FileIdentity(
        device=info.st_dev,
        inode=info.st_ino,
        uid=info.st_uid,
        mode=stat.S_IMODE(info.st_mode),
        size_bytes=info.st_size,
        mtime_ns=info.st_mtime_ns,
        ctime_ns=info.st_ctime_ns,
        nlink=info.st_nlink,
        sha256=sha256,
    )


def _pr4g_directory_identity(value: object) -> _DirectoryIdentity:
    return _DirectoryIdentity(
        device=value.device,
        inode=value.inode,
        uid=value.uid,
        mode=value.mode,
        mtime_ns=value.mtime_ns,
        ctime_ns=value.ctime_ns,
    )


def _pr4g_file_identity(value: object) -> _FileIdentity:
    return _FileIdentity(
        device=value.device,
        inode=value.inode,
        uid=value.uid,
        mode=value.mode,
        size_bytes=value.size,
        mtime_ns=value.mtime_ns,
        ctime_ns=value.ctime_ns,
        nlink=1,
        sha256=value.sha256,
    )


def _open_local_directory(paths: object) -> int:
    local_dir = paths.local_dir
    if not isinstance(local_dir, Path) or local_dir.is_symlink():
        raise ProtectedLocalMaterializationError(
            "owner-derived local directory differs"
        )
    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    try:
        descriptor = os.open(local_dir, flags)
    except OSError as exc:
        raise ProtectedLocalMaterializationError(
            f"owner-derived local directory open failed: {exc}"
        ) from exc
    try:
        actual = _directory_identity(os.fstat(descriptor))
        expected = _pr4g_directory_identity(paths.local_dir_identity)
        if actual != expected:
            raise ProtectedLocalMaterializationError(
                "owner-derived local directory identity differs"
            )
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def _read_entry(
    directory_descriptor: int,
    name: str,
    *,
    maximum: int | None = None,
) -> tuple[bytes, _FileIdentity]:
    flags = (
        os.O_RDONLY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    descriptor = -1
    try:
        descriptor = os.open(
            name,
            flags,
            dir_fd=directory_descriptor,
        )
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or (maximum is not None and before.st_size > maximum)
        ):
            raise ProtectedLocalMaterializationError(
                f"local materialization entry is unsafe: {name}"
            )
        chunks = []
        hasher = hashlib.sha256()
        total = 0
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if maximum is not None and total > maximum:
                raise ProtectedLocalMaterializationError(
                    f"local materialization entry exceeds bound: {name}"
                )
            chunks.append(chunk)
            hasher.update(chunk)
        after = os.fstat(descriptor)
    except OSError as exc:
        raise ProtectedLocalMaterializationError(
            f"local materialization entry read failed for {name}: {exc}"
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if _stat_identity(before) != _stat_identity(after) or total != before.st_size:
        raise ProtectedLocalMaterializationError(
            f"local materialization entry changed during read: {name}"
        )
    return b"".join(chunks), _file_identity(after, hasher.hexdigest())


def _write_chunks(
    descriptor: int,
    chunks: Iterator[bytes],
    *,
    expected_sha256: str,
    expected_size: int,
) -> _FileIdentity:
    hasher = hashlib.sha256()
    total = 0
    for chunk in chunks:
        if type(chunk) is not bytes:
            raise ProtectedLocalMaterializationError(
                "sealed PR4F stage source yielded non-bytes"
            )
        view = memoryview(chunk)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise ProtectedLocalMaterializationError(
                    "materialized file write made no progress"
                )
            part = bytes(view[:written])
            hasher.update(part)
            total += written
            view = view[written:]
    os.fsync(descriptor)
    info = os.fstat(descriptor)
    actual_sha256 = hasher.hexdigest()
    if (
        total != expected_size
        or info.st_size != expected_size
        or actual_sha256 != expected_sha256
    ):
        raise ProtectedLocalMaterializationError(
            "materialized bytes differ from exact PR4F stage bytes"
        )
    return _file_identity(info, actual_sha256)


def _artifact_chunks(artifact: object) -> Iterator[bytes]:
    data = artifact.data
    if data is not None:
        if type(data) is not bytes:
            raise ProtectedLocalMaterializationError(
                "sealed stage bytes differ"
            )
        yield data
        return
    snapshot = artifact.private_snapshot
    lock = getattr(snapshot, "_lock", None)
    file_object = getattr(snapshot, "_file", None)
    if lock is None or file_object is None:
        raise ProtectedLocalMaterializationError(
            "sealed private stage snapshot is unavailable"
        )
    with lock:
        try:
            file_object.seek(0)
            while True:
                chunk = file_object.read(1024 * 1024)
                if not chunk:
                    break
                if type(chunk) is not bytes:
                    raise TypeError("private stage snapshot yielded non-bytes")
                yield chunk
            file_object.seek(0)
        except Exception as exc:
            raise ProtectedLocalMaterializationError(
                f"sealed private stage replay failed: {exc}"
            ) from exc


def _create_no_clobber(
    directory_descriptor: int,
    name: str,
    chunks: Iterator[bytes],
    *,
    expected_sha256: str,
    expected_size: int,
) -> _FileIdentity:
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    descriptor = -1
    try:
        descriptor = os.open(
            name,
            flags,
            0o600,
            dir_fd=directory_descriptor,
        )
        return _write_chunks(
            descriptor,
            chunks,
            expected_sha256=expected_sha256,
            expected_size=expected_size,
        )
    except OSError as exc:
        raise ProtectedLocalMaterializationError(
            f"no-clobber materialization failed for {name}: {exc}"
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _write_materialized_artifact(
    directory_descriptor: int,
    artifact: object,
) -> _FileIdentity:
    return _create_no_clobber(
        directory_descriptor,
        artifact.relative_name,
        _artifact_chunks(artifact),
        expected_sha256=artifact.sha256,
        expected_size=artifact.size_bytes,
    )


def _publish_state_record(
    directory_descriptor: int,
    raw: bytes,
) -> _FileIdentity:
    return _create_no_clobber(
        directory_descriptor,
        STATE_BASENAME,
        iter((raw,)),
        expected_sha256=hashlib.sha256(raw).hexdigest(),
        expected_size=len(raw),
    )


def _assert_entries(
    directory_descriptor: int,
    expected: dict[str, _FileIdentity],
) -> None:
    actual_names = os.listdir(directory_descriptor)
    if (
        len(actual_names) != len(expected)
        or set(actual_names) != set(expected)
    ):
        raise ProtectedLocalMaterializationError(
            "materialized directory topology drifted"
        )
    for name, identity in expected.items():
        _, actual = _read_entry(
            directory_descriptor,
            name,
            maximum=(
                _MAX_STATE_BYTES if name == STATE_BASENAME else None
            ),
        )
        if actual != identity:
            raise ProtectedLocalMaterializationError(
                f"materialized entry identity drifted: {name}"
            )


def _build_state_document(
    sealed_lifecycle: object,
    reserved: object,
    ledger_identity: _FileIdentity,
    materialized: list[tuple[object, _FileIdentity]],
) -> dict[str, Any]:
    lifecycle_document = sealed_lifecycle.document()
    invocation = sealed_lifecycle.protected_invocation_bundle
    invocation_document = invocation.document()
    local_binding = invocation.local_state_binding
    local_document = local_binding.document()
    stage_plan = invocation.stage_plan
    portable_artifacts = stage_plan.portable_artifacts()
    materialized_files = []
    for portable, (artifact, identity) in zip(
        portable_artifacts,
        materialized,
        strict=True,
    ):
        if (
            artifact.relative_name != portable["relative_name"]
            or artifact.sha256 != portable["sha256"]
            or artifact.size_bytes != portable["size_bytes"]
        ):
            raise ProtectedLocalMaterializationError(
                "sealed PR4F stage projections differ"
            )
        materialized_files.append(
            {
                **portable,
                "identity": identity.document(),
            }
        )
    protected_bundle = invocation.protected_submit_bundle
    state = {
        "schema": SCHEMA,
        "owner": OWNER,
        "materialization_id": (
            "protected-local-materialization-" + "0" * 64
        ),
        "lifecycle": {
            "schema": lifecycle_document["schema"],
            "lifecycle_id": lifecycle_document["lifecycle_id"],
            "structural_projection_sha256": lifecycle_document[
                "structural_projection_sha256"
            ],
        },
        "invocation": {
            "schema": invocation_document["schema"],
            "invocation_id": invocation_document["invocation_id"],
            "invocation_payload_sha256": invocation_document[
                "invocation_payload_sha256"
            ],
            "stage_manifest_sha256": invocation_document["stage_plan"][
                "manifest_sha256"
            ],
            "stage_artifact_count": invocation_document["stage_plan"][
                "artifact_count"
            ],
        },
        "reservation": {
            "bundle_id": protected_bundle.bundle_id,
            "bundle_payload_sha256": (
                protected_bundle.bundle_payload_sha256
            ),
            "attempt_id": protected_bundle.attempt_id,
            "consumption_sha256": reserved.consumption_sha256,
            "consumed_at": reserved.consumed_at,
            "submission_state": reserved.submission_state,
            "automatic_retry": reserved.automatic_retry,
            "reconciliation": reserved.reconciliation,
        },
        "local_state": {
            "binding_schema": local_document["schema"],
            "binding_payload_sha256": local_document[
                "binding_payload_sha256"
            ],
            "relative_local_dir": local_document["layout"][
                "relative_local_dir"
            ],
            "ledger_basename": local_document["layout"][
                "ledger_basename"
            ],
            "workspace_root_path_sha256": local_document[
                "path_bindings"
            ]["workspace_root_path_sha256"],
            "local_dir_path_sha256": local_document["path_bindings"][
                "local_dir_path_sha256"
            ],
            "initial_ledger_identity_sha256": invocation_document[
                "ledger"
            ]["ledger_identity_sha256"],
        },
        "ledger": {
            "relative_name": LEDGER_BASENAME,
            "sha256": ledger_identity.sha256,
            "size_bytes": ledger_identity.size_bytes,
            "identity": ledger_identity.document(),
        },
        "stage_plan": {
            "schema": stage_plan.schema,
            "manifest_sha256": stage_plan.manifest_sha256,
            "artifact_count": len(portable_artifacts),
            "artifacts": portable_artifacts,
        },
        "materialized_files": materialized_files,
        "directory_topology": (
            [LEDGER_BASENAME]
            + [item["relative_name"] for item in portable_artifacts]
            + [STATE_BASENAME]
        ),
        "publication": {
            "state_basename": STATE_BASENAME,
            "published_last": True,
            "no_clobber": True,
        },
        "scope": copy.deepcopy(SCOPE),
        "status": copy.deepcopy(STATUS),
        "policy": copy.deepcopy(POLICY),
        "state_payload_sha256": "",
    }
    state["state_payload_sha256"] = _state_payload_sha256(state)
    seed = digest(
        {
            "schema": "auto-g16-protected-local-materialization-id/1",
            "lifecycle_id": state["lifecycle"]["lifecycle_id"],
            "invocation_payload_sha256": state["invocation"][
                "invocation_payload_sha256"
            ],
            "consumption_sha256": state["reservation"][
                "consumption_sha256"
            ],
            "local_state_binding_payload_sha256": state["local_state"][
                "binding_payload_sha256"
            ],
            "state_payload_sha256": state["state_payload_sha256"],
        }
    )
    state["materialization_id"] = (
        f"protected-local-materialization-{seed}"
    )
    return validate_protected_local_materialization_state(state)


@dataclass(frozen=True, slots=True, init=False)
class SealedProtectedLocalMaterialization:
    """Owner-issued state capability; no external-effect method exists."""

    _canonical_document: bytes
    lifecycle: object
    reservation: object
    local_dir: Path
    lifecycle_owner_snapshot: _OwnerFileSnapshot
    final_directory_identity: _DirectoryIdentity
    entry_identities: tuple[tuple[str, _FileIdentity], ...]
    materialization_id: str
    state_payload_sha256: str
    _seal: object

    def __new__(
        cls,
        *args: Any,
        **kwargs: Any,
    ) -> "SealedProtectedLocalMaterialization":
        raise TypeError(
            "SealedProtectedLocalMaterialization is issued only by its owner"
        )

    @classmethod
    def _from_owner(
        cls,
        document: dict[str, Any],
        *,
        lifecycle: object,
        reservation: object,
        local_dir: Path,
        lifecycle_owner_snapshot: _OwnerFileSnapshot,
        final_directory_identity: _DirectoryIdentity,
        entry_identities: dict[str, _FileIdentity],
        token: object,
    ) -> "SealedProtectedLocalMaterialization":
        if token is not _SEAL_TOKEN:
            raise ProtectedLocalMaterializationError(
                "local materialization seal differs"
            )
        lifecycle.assert_owner_sealed()
        reservation.assert_owner_sealed()
        validated = validate_protected_local_materialization_state(document)
        value = object.__new__(cls)
        for name, item in {
            "_canonical_document": canonical_bytes(validated),
            "lifecycle": lifecycle,
            "reservation": reservation,
            "local_dir": local_dir,
            "lifecycle_owner_snapshot": lifecycle_owner_snapshot,
            "final_directory_identity": final_directory_identity,
            "entry_identities": tuple(entry_identities.items()),
            "materialization_id": validated["materialization_id"],
            "state_payload_sha256": validated["state_payload_sha256"],
            "_seal": _SEAL_TOKEN,
        }.items():
            object.__setattr__(value, name, item)
        return value

    def document(self) -> dict[str, Any]:
        return json.loads(self._canonical_document)

    def __copy__(self) -> "SealedProtectedLocalMaterialization":
        raise TypeError("sealed local materialization is not clonable")

    def __deepcopy__(
        self,
        memo: dict[int, Any],
    ) -> "SealedProtectedLocalMaterialization":
        del memo
        raise TypeError("sealed local materialization is not clonable")

    def __reduce__(self) -> object:
        raise TypeError("sealed local materialization is not serializable")

    def assert_owner_sealed(self) -> None:
        if self._seal is not _SEAL_TOKEN:
            raise ProtectedLocalMaterializationError(
                "local materialization seal differs"
            )
        self.lifecycle.assert_owner_sealed()
        self.reservation.assert_owner_sealed()
        document = validate_protected_local_materialization_state(
            self.document()
        )
        if (
            document["materialization_id"] != self.materialization_id
            or document["state_payload_sha256"]
            != self.state_payload_sha256
            or canonical_bytes(document) != self._canonical_document
        ):
            raise ProtectedLocalMaterializationError(
                "sealed local materialization projection differs"
            )

    def assert_current(self) -> "SealedProtectedLocalMaterialization":
        self.assert_owner_sealed()
        if (
            _stable_lifecycle_owner_snapshot()
            != self.lifecycle_owner_snapshot
        ):
            raise ProtectedLocalMaterializationError(
                "protected lifecycle owner identity differs"
            )
        flags = (
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0)
        )
        descriptor = -1
        try:
            descriptor = os.open(self.local_dir, flags)
            if (
                _directory_identity(os.fstat(descriptor))
                != self.final_directory_identity
            ):
                raise ProtectedLocalMaterializationError(
                    "materialized directory identity differs"
                )
            expected = dict(self.entry_identities)
            _assert_entries(descriptor, expected)
            state_raw, _ = _read_entry(
                descriptor,
                STATE_BASENAME,
                maximum=_MAX_STATE_BYTES,
            )
            if state_raw != self._canonical_document:
                raise ProtectedLocalMaterializationError(
                    "published local-state bytes differ"
                )
        except OSError as exc:
            raise ProtectedLocalMaterializationError(
                f"materialized local-state replay failed: {exc}"
            ) from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)
        return self


class ProtectedLocalMaterializationOwner:
    """Own the bounded reserve -> materialize -> state publication prefix."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime],
        state_root: Path | None,
        _factory_token: object,
    ) -> None:
        if _factory_token not in {_SEAL_TOKEN, _TEST_OWNER_TOKEN}:
            raise TypeError(
                "ProtectedLocalMaterializationOwner requires a fixed factory"
            )
        if _factory_token is _SEAL_TOKEN and state_root is not None:
            raise ProtectedLocalMaterializationError(
                "production reservation root has no caller override"
            )
        self._clock = clock
        self._state_root = state_root
        self._testing = _factory_token is _TEST_OWNER_TOKEN

    @classmethod
    def production(cls) -> "ProtectedLocalMaterializationOwner":
        return cls(
            clock=_utc_now,
            state_root=None,
            _factory_token=_SEAL_TOKEN,
        )

    @classmethod
    def _for_testing_with_clock(
        cls,
        state_root: Path,
        clock: Callable[[], datetime],
        *,
        _test_token: object,
    ) -> "ProtectedLocalMaterializationOwner":
        if _test_token is not _TEST_OWNER_TOKEN:
            raise TypeError(
                "private local materialization test token differs"
            )
        if not isinstance(state_root, Path):
            raise TypeError("private test state_root must be pathlib.Path")
        return cls(
            clock=clock,
            state_root=state_root,
            _factory_token=_TEST_OWNER_TOKEN,
        )

    def materialize_once(
        self,
        evidence: object,
    ) -> SealedProtectedLocalMaterialization:
        lifecycle_module, owner_snapshot = _exact_lifecycle_module(
            evidence
        )
        current = _trusted_now(self._clock)
        with _MODULE_LOCK:
            sealed_lifecycle = _seal_current_lifecycle(
                lifecycle_module,
                evidence,
                current=current,
                testing=self._testing,
            )
            if (
                _stable_lifecycle_owner_snapshot()
                != owner_snapshot
            ):
                raise ProtectedLocalMaterializationError(
                    "protected lifecycle owner drifted before reservation"
                )

            reserved = _reserve_protected_submit_once(
                sealed_lifecycle,
                current=current,
                testing=self._testing,
                state_root=self._state_root,
            )
            sealed_lifecycle.assert_owner_sealed()
            invocation = sealed_lifecycle.protected_invocation_bundle
            paths = invocation.local_state_binding.paths
            directory_descriptor = _open_local_directory(paths)
            try:
                names = os.listdir(directory_descriptor)
                if names != [LEDGER_BASENAME]:
                    raise ProtectedLocalMaterializationError(
                        "post-reservation local directory is not ledger-only"
                    )
                ledger_raw, ledger_identity = _read_entry(
                    directory_descriptor,
                    LEDGER_BASENAME,
                )
                expected_ledger = _pr4g_file_identity(
                    paths.ledger_identity
                )
                if (
                    ledger_identity != expected_ledger
                    or hashlib.sha256(ledger_raw).hexdigest()
                    != expected_ledger.sha256
                ):
                    raise ProtectedLocalMaterializationError(
                        "post-reservation ledger identity differs"
                    )

                artifacts = invocation.stage_plan.artifacts
                materialized: list[tuple[object, _FileIdentity]] = []
                for artifact in artifacts:
                    identity = _write_materialized_artifact(
                        directory_descriptor,
                        artifact,
                    )
                    materialized.append((artifact, identity))
                os.fsync(directory_descriptor)

                expected_entries = {
                    LEDGER_BASENAME: ledger_identity,
                    **{
                        artifact.relative_name: identity
                        for artifact, identity in materialized
                    },
                }
                _assert_entries(directory_descriptor, expected_entries)
                state_document = _build_state_document(
                    sealed_lifecycle,
                    reserved,
                    ledger_identity,
                    materialized,
                )
                state_raw = canonical_bytes(state_document)
                if len(state_raw) > _MAX_STATE_BYTES:
                    raise ProtectedLocalMaterializationError(
                        "local materialization state exceeds the bound"
                    )
                state_identity = _publish_state_record(
                    directory_descriptor,
                    state_raw,
                )
                os.fsync(directory_descriptor)
                expected_entries[STATE_BASENAME] = state_identity
                _assert_entries(directory_descriptor, expected_entries)
                final_directory_identity = _directory_identity(
                    os.fstat(directory_descriptor)
                )
            finally:
                os.close(directory_descriptor)

            if (
                _stable_lifecycle_owner_snapshot()
                != owner_snapshot
            ):
                raise ProtectedLocalMaterializationError(
                    "protected lifecycle owner drifted during materialization"
                )
            sealed = SealedProtectedLocalMaterialization._from_owner(
                state_document,
                lifecycle=sealed_lifecycle,
                reservation=reserved,
                local_dir=paths.local_dir,
                lifecycle_owner_snapshot=owner_snapshot,
                final_directory_identity=final_directory_identity,
                entry_identities=expected_entries,
                token=_SEAL_TOKEN,
            )
            sealed.assert_current()
            return sealed


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)
