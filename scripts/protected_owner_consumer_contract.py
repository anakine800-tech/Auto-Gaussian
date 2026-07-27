#!/usr/bin/env python3
"""Materialize one effect-ready local bundle without performing an effect.

The sole input is the exact owner-issued PR4 runtime/state capability.  This
module copies the already sealed non-checksum PR4F stage bytes into an additive
sibling directory, publishes a successor submission intent and checksum
manifest, consumes the runtime capability once, and durably publishes the
uncertain receipt before issuing any plan-input capability.

It never constructs ``_LegacyEffectPlan`` or ``_LegacyRawEffectOwner``, calls a
runner or adapter, opens a connection, transfers bytes, submits, reconciles,
retries, cancels, cleans up, deletes, migrates, rehashes, or backfills a
predecessor.
"""

from __future__ import annotations

try:
    _AUTO_G16_OWNER_CONSUMER_EXECUTION_GUARD
except NameError:
    _AUTO_G16_OWNER_CONSUMER_EXECUTION_GUARD = object()
else:
    raise ImportError("owner consumer module has already executed")

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
from pathlib import Path
from typing import Any, Callable


SCHEMA = "auto-g16-protected-owner-consumer-contract/1"
INTENT_SCHEMA = "auto-g16-protected-owner-submission-intent/1"
OWNER = "auto-g16-protected-owner-consumer-owner"
MODULE_NAME = "protected_owner_consumer_contract"
RUNTIME_MODULE_NAME = "protected_runtime_state_contract"
LEGACY_MODULE_NAME = "legacy_rtwin_pbs"
RUNTIME_SCHEMA = "auto-g16-protected-runtime-state-contract/1"
RUNTIME_RECEIPT_SCHEMA = "auto-g16-protected-runtime-state-receipt/1"
CONTAINER_BASENAME = ".auto-g16-protected-owner-consumer-v1"
INTENT_BASENAME = "submission-intent.json"
CHECKSUM_BASENAME = "checksums.sha256"
FIXED_REMOTE_ROOT = "/home/user100/SDL"
FIXED_EFFECT_STEPS = (
    "windows_directory_claim",
    "mac_to_windows_copy",
    "windows_sha256",
    "server_directory_claim",
    "windows_to_server_copy",
    "qsub_once",
)
LEGACY_PLAN_FIELDS = (
    "project",
    "windows_dir",
    "remote_dir",
    "files",
    "expected_bindings",
    "upload_timeout_seconds",
    "upload_hash_timeout_seconds",
    "attempt_id",
    "input_sha256",
    "mac_ssh_config",
    "rtwin_alias",
    "windows_server_config",
    "server_alias",
)
SCOPE = {
    "bind_exact_runtime_state_capability": True,
    "materialize_additive_sibling_upload_bundle": True,
    "publish_successor_submission_intent": True,
    "publish_replacement_checksum_manifest": True,
    "consume_runtime_state_once": True,
    "persist_uncertain_before_effect": True,
    "issue_local_effect_plan_inputs": True,
    "create_legacy_transaction_plan": False,
    "create_legacy_effect_plan": False,
    "create_raw_effect_owner": False,
    "invoke_adapter": False,
    "invoke_runner": False,
    "transfer": False,
    "submit": False,
    "remote_read": False,
    "retry": False,
    "cancel": False,
    "cleanup": False,
    "delete": False,
}
POLICY = {
    "single_owner_use": True,
    "single_plan_input_claim": True,
    "predecessor_directories_unchanged": True,
    "authorities_remain_distinct": True,
    "legacy_ledger_reservation_present": False,
    "uncertain_receipt_durable_before_first_effect": True,
    "read_only_reconciliation_only_after_uncertain": True,
    "automatic_retry": False,
    "automatic_cancel": False,
    "automatic_cleanup": False,
    "automatic_delete": False,
    "automatic_rollback": False,
    "historical_migration": False,
}
VALIDATION = {
    "draft_schema_structural_only": True,
    "public_validator_semantic_projection": True,
    "owner_replay_required": True,
    "in_process_seal_required": True,
    "schema_issues_seal": False,
}

SHA_RE = re.compile(r"^[a-f0-9]{64}$")
PROJECT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,14}$")
ATTEMPT_RE = re.compile(r"^qsub-attempt-[a-f0-9]{64}$")
RUNTIME_ID_RE = re.compile(r"^protected-runtime-state-[a-f0-9]{64}$")
JOURNAL_ID_RE = re.compile(r"^protected-runtime-journal-[a-f0-9]{64}$")
RECEIPT_ID_RE = re.compile(r"^protected-runtime-receipt-[a-f0-9]{64}$")
CONTRACT_ID_RE = re.compile(r"^protected-owner-consumer-[a-f0-9]{64}$")
INTENT_ID_RE = re.compile(r"^protected-owner-intent-[a-f0-9]{64}$")
SAFE_BASENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$")
_ZERO_SHA = "0" * 64
_MAX_JSON_DEPTH = 64
_MAX_JSON_BYTES = 4 * 1024 * 1024
_CHUNK_SIZE = 1024 * 1024
_SEAL_TOKEN = object()
_PLAN_INPUT_TOKEN = object()
_OWNER_TOKEN = object()
_MISSING = object()
_MODULE_LOCK = threading.RLock()
_REGISTRATION_ATTRIBUTE = (
    "_auto_g16_protected_owner_consumer_registration_v1"
)


class ProtectedOwnerConsumerError(ValueError):
    """The local owner-consumer boundary cannot be proved safely."""


def canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ProtectedOwnerConsumerError(
            f"owner consumer value is not canonical JSON: {exc}"
        ) from exc


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _rebuild_public_json(
    value: object,
    *,
    depth: int = 0,
    active: set[int] | None = None,
) -> Any:
    if depth > _MAX_JSON_DEPTH:
        raise ProtectedOwnerConsumerError(
            "owner consumer document exceeds the nesting bound"
        )
    if type(value) in {str, int, bool} or value is None:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ProtectedOwnerConsumerError(
                "owner consumer document contains a non-finite number"
            )
        return value
    if type(value) not in {dict, list}:
        raise ProtectedOwnerConsumerError(
            "owner consumer document accepts only exact builtin JSON"
        )
    if active is None:
        active = set()
    identity = id(value)
    if identity in active:
        raise ProtectedOwnerConsumerError(
            "owner consumer document contains a cycle"
        )
    active.add(identity)
    try:
        if type(value) is list:
            first = list(value)
            rebuilt = [
                _rebuild_public_json(
                    item,
                    depth=depth + 1,
                    active=active,
                )
                for item in first
            ]
            if list(value) != first:
                raise ProtectedOwnerConsumerError(
                    "owner consumer list changed during validation"
                )
            return rebuilt
        first_items = list(value.items())
        if any(type(key) is not str for key, _item in first_items):
            raise ProtectedOwnerConsumerError(
                "owner consumer object keys must be strings"
            )
        rebuilt_dict = {
            key: _rebuild_public_json(
                item,
                depth=depth + 1,
                active=active,
            )
            for key, item in first_items
        }
        if list(value.items()) != first_items:
            raise ProtectedOwnerConsumerError(
                "owner consumer object changed during validation"
            )
        return rebuilt_dict
    finally:
        active.remove(identity)


def _exact(value: object, fields: set[str], label: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != fields:
        raise ProtectedOwnerConsumerError(f"{label} topology differs")
    return value


def _sha(value: object, label: str, *, nonzero: bool = True) -> str:
    if (
        type(value) is not str
        or SHA_RE.fullmatch(value) is None
        or (nonzero and value == _ZERO_SHA)
    ):
        raise ProtectedOwnerConsumerError(f"{label} is not an exact SHA-256")
    return value


def _integer(value: object, label: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ProtectedOwnerConsumerError(f"{label} is not an exact integer")
    return value


def _fixed(value: object, expected: dict[str, bool], label: str) -> None:
    item = _exact(value, set(expected), label)
    if any(item[key] is not expected[key] for key in expected):
        raise ProtectedOwnerConsumerError(f"{label} differs")


def _safe_basename(value: object, label: str) -> str:
    if (
        type(value) is not str
        or SAFE_BASENAME_RE.fullmatch(value) is None
        or value in {".", ".."}
        or "/" in value
        or "\\" in value
    ):
        raise ProtectedOwnerConsumerError(f"{label} is not a safe basename")
    return value


def _payload_sha256(
    document: dict[str, Any],
    *,
    id_field: str,
    payload_field: str,
) -> str:
    projection = dict(document)
    projection[id_field] = ""
    projection[payload_field] = ""
    return digest(projection)


def validate_protected_owner_submission_intent(
    value: object,
) -> dict[str, Any]:
    document = _rebuild_public_json(value)
    if len(canonical_bytes(document)) > _MAX_JSON_BYTES:
        raise ProtectedOwnerConsumerError("submission intent exceeds the bound")
    document = _exact(
        document,
        {
            "schema",
            "owner",
            "intent_id",
            "project",
            "job_name",
            "remote_workdir",
            "input_sha256",
            "scientific_task_id",
            "attempt_id",
            "idempotency_key_sha256",
            "live_approval_id",
            "live_approval_artifact_sha256",
            "protected_authority",
            "reserved_at",
            "automatic_retry",
            "intent_payload_sha256",
        },
        "submission intent",
    )
    if document["schema"] != INTENT_SCHEMA or document["owner"] != OWNER:
        raise ProtectedOwnerConsumerError("submission intent owner differs")
    if (
        type(document["intent_id"]) is not str
        or INTENT_ID_RE.fullmatch(document["intent_id"]) is None
        or type(document["project"]) is not str
        or PROJECT_RE.fullmatch(document["project"]) is None
        or document["job_name"] != document["project"]
        or document["remote_workdir"]
        != f"{FIXED_REMOTE_ROOT}/{document['project']}"
        or type(document["attempt_id"]) is not str
        or ATTEMPT_RE.fullmatch(document["attempt_id"]) is None
        or type(document["scientific_task_id"]) is not str
        or not document["scientific_task_id"]
        or type(document["live_approval_id"]) is not str
        or not document["live_approval_id"]
        or type(document["reserved_at"]) is not str
        or not document["reserved_at"].endswith("Z")
        or document["automatic_retry"] is not False
    ):
        raise ProtectedOwnerConsumerError("submission intent identity differs")
    for field in (
        "input_sha256",
        "idempotency_key_sha256",
        "live_approval_artifact_sha256",
        "intent_payload_sha256",
    ):
        _sha(document[field], f"submission intent {field}")
    authority = _exact(
        document["protected_authority"],
        {
            "schema",
            "bundle_id",
            "bundle_payload_sha256",
            "consumption_sha256",
            "submission_state",
            "legacy_execution_batch_reservation_present",
            "legacy_ledger_is_authority",
        },
        "submission intent authority",
    )
    if (
        authority["schema"] != "auto-g16-protected-submit-reservation/1"
        or type(authority["bundle_id"]) is not str
        or not authority["bundle_id"].startswith("protected-submit-")
        or authority["submission_state"] != "submission_uncertain"
        or authority["legacy_execution_batch_reservation_present"] is not False
        or authority["legacy_ledger_is_authority"] is not False
    ):
        raise ProtectedOwnerConsumerError(
            "submission intent reservation authority differs"
        )
    _sha(authority["bundle_payload_sha256"], "bundle payload")
    _sha(authority["consumption_sha256"], "consumption")
    expected_payload = _payload_sha256(
        document,
        id_field="intent_id",
        payload_field="intent_payload_sha256",
    )
    if document["intent_payload_sha256"] != expected_payload:
        raise ProtectedOwnerConsumerError("submission intent payload differs")
    expected_id = "protected-owner-intent-" + digest(
        {
            "schema": "auto-g16-protected-owner-intent-id/1",
            "attempt_id": document["attempt_id"],
            "consumption_sha256": authority["consumption_sha256"],
            "intent_payload_sha256": expected_payload,
        }
    )
    if document["intent_id"] != expected_id:
        raise ProtectedOwnerConsumerError("submission intent id differs")
    return document


def validate_protected_owner_consumer_contract(
    value: object,
) -> dict[str, Any]:
    document = _rebuild_public_json(value)
    if len(canonical_bytes(document)) > _MAX_JSON_BYTES:
        raise ProtectedOwnerConsumerError("owner consumer contract exceeds the bound")
    document = _exact(
        document,
        {
            "schema",
            "owner",
            "contract_id",
            "runtime_state",
            "identity",
            "intent",
            "upload_bundle",
            "effect_plan_projection",
            "reconciliation_inputs",
            "owner_bindings",
            "validation",
            "scope",
            "policy",
            "contract_payload_sha256",
        },
        "owner consumer contract",
    )
    if document["schema"] != SCHEMA or document["owner"] != OWNER:
        raise ProtectedOwnerConsumerError("owner consumer schema differs")
    if (
        type(document["contract_id"]) is not str
        or CONTRACT_ID_RE.fullmatch(document["contract_id"]) is None
    ):
        raise ProtectedOwnerConsumerError("owner consumer id differs")
    runtime = _exact(
        document["runtime_state"],
        {
            "schema",
            "contract_id",
            "contract_payload_sha256",
            "journal_id",
            "uncertain_receipt_id",
            "uncertain_receipt_payload_sha256",
            "uncertain_state",
        },
        "runtime state projection",
    )
    if (
        runtime["schema"] != RUNTIME_SCHEMA
        or type(runtime["contract_id"]) is not str
        or RUNTIME_ID_RE.fullmatch(runtime["contract_id"]) is None
        or type(runtime["uncertain_receipt_id"]) is not str
        or RECEIPT_ID_RE.fullmatch(runtime["uncertain_receipt_id"]) is None
        or type(runtime["journal_id"]) is not str
        or JOURNAL_ID_RE.fullmatch(runtime["journal_id"]) is None
        or runtime["uncertain_state"] != "effect_started_outcome_uncertain"
    ):
        raise ProtectedOwnerConsumerError("runtime state projection differs")
    for field in (
        "contract_payload_sha256",
        "uncertain_receipt_payload_sha256",
    ):
        _sha(runtime[field], f"runtime state {field}")
    identity = _exact(
        document["identity"],
        {"project", "attempt_id", "input_sha256"},
        "owner consumer identity",
    )
    if (
        type(identity["project"]) is not str
        or PROJECT_RE.fullmatch(identity["project"]) is None
        or type(identity["attempt_id"]) is not str
        or ATTEMPT_RE.fullmatch(identity["attempt_id"]) is None
    ):
        raise ProtectedOwnerConsumerError("owner consumer identity differs")
    _sha(identity["input_sha256"], "owner consumer input")
    intent = validate_protected_owner_submission_intent(document["intent"])
    if any(intent[field] != identity[field] for field in ("project", "attempt_id", "input_sha256")):
        raise ProtectedOwnerConsumerError("intent identity is spliced")
    upload = _exact(
        document["upload_bundle"],
        {
            "container_basename",
            "directory_path_sha256",
            "artifacts",
            "artifact_count",
            "total_size_bytes",
            "expected_bindings_sha256",
            "checksum_semantics",
            "predecessor_checksum_uploaded",
            "predecessor_state_uploaded",
            "predecessor_ledger_uploaded",
        },
        "upload bundle",
    )
    if (
        upload["container_basename"] != CONTAINER_BASENAME
        or upload["predecessor_checksum_uploaded"] is not False
        or upload["predecessor_state_uploaded"] is not False
        or upload["predecessor_ledger_uploaded"] is not False
    ):
        raise ProtectedOwnerConsumerError("upload bundle boundary differs")
    _sha(upload["directory_path_sha256"], "upload directory")
    _sha(upload["expected_bindings_sha256"], "expected bindings")
    artifacts = upload["artifacts"]
    if type(artifacts) is not list or not artifacts:
        raise ProtectedOwnerConsumerError("upload artifacts are unavailable")
    portable = []
    names = []
    for index, raw in enumerate(artifacts, start=1):
        item = _exact(
            raw,
            {"role", "relative_name", "order", "sha256", "size_bytes"},
            f"upload artifact {index}",
        )
        if (
            type(item["role"]) is not str
            or not item["role"]
            or _safe_basename(item["relative_name"], "upload artifact name")
            != item["relative_name"]
            or item["order"] != index
        ):
            raise ProtectedOwnerConsumerError("upload artifact order differs")
        _sha(item["sha256"], "upload artifact")
        _integer(item["size_bytes"], "upload artifact size", 1)
        portable.append(item)
        names.append(item["relative_name"])
    if len(set(names)) != len(names) or names[-2:] != [INTENT_BASENAME, CHECKSUM_BASENAME]:
        raise ProtectedOwnerConsumerError("upload artifact topology differs")
    if (
        upload["artifact_count"] != len(portable)
        or upload["total_size_bytes"] != sum(item["size_bytes"] for item in portable)
        or upload["expected_bindings_sha256"]
        != digest([(item["relative_name"], item["sha256"]) for item in portable])
    ):
        raise ProtectedOwnerConsumerError("upload artifact aggregate differs")
    checksum = _exact(
        upload["checksum_semantics"],
        {
            "schema",
            "basename",
            "line_format",
            "line_order",
            "self_entry",
            "intent_entry",
        },
        "checksum semantics",
    )
    if checksum != {
        "schema": "auto-g16-legacy-checksum-manifest-semantics/1",
        "basename": CHECKSUM_BASENAME,
        "line_format": "<sha256><two-spaces><basename><LF>",
        "line_order": names[:-1],
        "self_entry": False,
        "intent_entry": True,
    }:
        raise ProtectedOwnerConsumerError("checksum semantics differ")
    plan = _exact(
        document["effect_plan_projection"],
        {
            "legacy_module",
            "legacy_plan_class",
            "required_fields",
            "effect_steps",
            "windows_directory_sha256",
            "remote_directory",
            "first_hop_config_path_sha256",
            "first_hop_alias_sha256",
            "second_hop_config_sha256",
            "server_alias_sha256",
            "upload_timeout_seconds",
            "upload_hash_timeout_seconds",
            "effect_plan_created",
            "raw_effect_owner_created",
        },
        "effect plan projection",
    )
    if (
        plan["legacy_module"] != LEGACY_MODULE_NAME
        or plan["legacy_plan_class"] != "_LegacyEffectPlan"
        or plan["required_fields"] != list(LEGACY_PLAN_FIELDS)
        or plan["effect_steps"] != list(FIXED_EFFECT_STEPS)
        or plan["remote_directory"] != f"{FIXED_REMOTE_ROOT}/{identity['project']}"
        or plan["effect_plan_created"] is not False
        or plan["raw_effect_owner_created"] is not False
    ):
        raise ProtectedOwnerConsumerError("effect plan projection differs")
    for field in (
        "windows_directory_sha256",
        "first_hop_config_path_sha256",
        "first_hop_alias_sha256",
        "second_hop_config_sha256",
        "server_alias_sha256",
    ):
        _sha(plan[field], f"effect plan {field}")
    _integer(plan["upload_timeout_seconds"], "upload timeout", 1)
    _integer(plan["upload_hash_timeout_seconds"], "hash timeout", 1)
    reconciliation = _exact(
        document["reconciliation_inputs"],
        {
            "schema",
            "project",
            "attempt_id",
            "input_sha256",
            "intent_id",
            "intent_file_sha256",
            "uncertain_receipt_id",
            "uncertain_receipt_payload_sha256",
            "required_remote_observations",
            "observation_acquired",
            "remote_read_performed",
            "automatic_effect_authorized",
            "automatic_retry",
        },
        "reconciliation inputs",
    )
    if (
        reconciliation["schema"]
        != "auto-g16-protected-owner-consumer-reconciliation-inputs/1"
        or any(reconciliation[field] != identity[field] for field in ("project", "attempt_id", "input_sha256"))
        or reconciliation["intent_id"] != intent["intent_id"]
        or reconciliation["uncertain_receipt_id"] != runtime["uncertain_receipt_id"]
        or reconciliation["uncertain_receipt_payload_sha256"]
        != runtime["uncertain_receipt_payload_sha256"]
        or reconciliation["required_remote_observations"]
        != ["project_directory", "submission_intent", "submission_receipt", "qstat_exact_attempt"]
        or reconciliation["observation_acquired"] is not False
        or reconciliation["remote_read_performed"] is not False
        or reconciliation["automatic_effect_authorized"] is not False
        or reconciliation["automatic_retry"] is not False
    ):
        raise ProtectedOwnerConsumerError("reconciliation input boundary differs")
    _sha(reconciliation["intent_file_sha256"], "reconciliation intent file")
    bindings = _exact(
        document["owner_bindings"],
        {
            "consumer_owner_source_sha256",
            "runtime_owner_source_sha256",
            "legacy_owner_source_sha256",
        },
        "owner bindings",
    )
    for field in bindings:
        _sha(bindings[field], f"owner binding {field}")
    _fixed(document["validation"], VALIDATION, "validation")
    _fixed(document["scope"], SCOPE, "scope")
    _fixed(document["policy"], POLICY, "policy")
    expected_payload = _payload_sha256(
        document,
        id_field="contract_id",
        payload_field="contract_payload_sha256",
    )
    if document["contract_payload_sha256"] != expected_payload:
        raise ProtectedOwnerConsumerError("owner consumer payload differs")
    expected_id = "protected-owner-consumer-" + digest(
        {
            "schema": "auto-g16-protected-owner-consumer-id/1",
            "runtime_contract_id": runtime["contract_id"],
            "uncertain_receipt_payload_sha256": runtime[
                "uncertain_receipt_payload_sha256"
            ],
            "expected_bindings_sha256": upload["expected_bindings_sha256"],
            "contract_payload_sha256": expected_payload,
        }
    )
    if document["contract_id"] != expected_id:
        raise ProtectedOwnerConsumerError("owner consumer contract id differs")
    return document


@dataclass(frozen=True, slots=True)
class _SourceSnapshot:
    path: Path
    identity: tuple[int, ...]
    sha256: str
    source_bytes: bytes


@dataclass(frozen=True, slots=True)
class _FileIdentity:
    identity: tuple[int, ...]
    sha256: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class _RuntimeBinding:
    module: types.ModuleType
    sealed_type: type
    receipt_type: type
    source: _SourceSnapshot
    normalize_root: Callable[..., object]
    normalize_path: Callable[..., object]


@dataclass(frozen=True, slots=True)
class _LegacyBinding:
    module: types.ModuleType
    plan_type: type
    source: _SourceSnapshot
    upload_timeout: Callable[[int], int]
    hash_timeout: Callable[[int], int]
    server_alias: str


def _stat_identity(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_uid,
        info.st_mode,
        info.st_nlink,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _stable_source(path: Path) -> _SourceSnapshot:
    descriptor = -1
    try:
        before = os.stat(path, follow_symlinks=False)
        if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
            raise ProtectedOwnerConsumerError("owner source must be a regular file")
        descriptor = os.open(
            path,
            os.O_RDONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
        )
        opened = os.fstat(descriptor)
        if _stat_identity(opened) != _stat_identity(before):
            raise ProtectedOwnerConsumerError("owner source changed while opening")
        chunks = []
        while True:
            chunk = os.read(descriptor, 64 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(descriptor)
        path_after = os.stat(path, follow_symlinks=False)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if len({_stat_identity(before), _stat_identity(opened), _stat_identity(after), _stat_identity(path_after)}) != 1:
        raise ProtectedOwnerConsumerError("owner source identity drifted")
    raw = b"".join(chunks)
    if len(raw) != opened.st_size:
        raise ProtectedOwnerConsumerError("owner source stable read was short")
    return _SourceSnapshot(
        path.resolve(strict=True),
        _stat_identity(opened),
        hashlib.sha256(raw).hexdigest(),
        raw,
    )


def _module_origin(module: types.ModuleType) -> tuple[Path, Path]:
    raw_file = getattr(module, "__file__", None)
    raw_origin = getattr(getattr(module, "__spec__", None), "origin", None)
    if type(raw_file) is not str or type(raw_origin) is not str:
        raise ImportError("bound owner module has no exact origin")
    return Path(raw_file).resolve(), Path(raw_origin).resolve()


def _runtime_path() -> Path:
    here = Path(__file__).resolve(strict=True)
    path = here.with_name(f"{RUNTIME_MODULE_NAME}.py")
    if path.is_symlink() or not path.is_file() or path.resolve().parent != here.parent:
        raise ImportError("exact adjacent runtime/state owner is unavailable")
    return path.resolve(strict=True)


def _legacy_path() -> Path:
    here = Path(__file__).resolve(strict=True)
    adjacent = here.with_name(f"{LEGACY_MODULE_NAME}.py")
    if not adjacent.is_symlink() and adjacent.is_file() and adjacent.resolve().parent == here.parent:
        return adjacent.resolve(strict=True)
    repository = (
        here.parent.parent
        / "skills"
        / "auto-g16-rtwin-pbs"
        / "scripts"
        / f"{LEGACY_MODULE_NAME}.py"
    )
    if not repository.is_symlink() and repository.is_file():
        return repository.resolve(strict=True)
    raise ImportError("exact legacy effect-plan owner is unavailable")


def _capture_runtime_binding() -> _RuntimeBinding:
    path = _runtime_path()
    source = _stable_source(path)
    module = sys.modules.get(RUNTIME_MODULE_NAME)
    if not isinstance(module, types.ModuleType) or _module_origin(module) != (path, path):
        raise ImportError("exact runtime/state owner must load first")
    sealed_type = getattr(module, "SealedProtectedRuntimeStateContract", None)
    receipt_type = getattr(module, "SealedProtectedRuntimeStateReceipt", None)
    normalize_root = getattr(module, "_normalized_windows_root", None)
    normalize_path = getattr(module, "_normalized_windows_path", None)
    if (
        not isinstance(sealed_type, type)
        or not isinstance(receipt_type, type)
        or not callable(normalize_root)
        or not callable(normalize_path)
    ):
        raise ImportError("runtime/state owner identity differs")
    return _RuntimeBinding(
        module,
        sealed_type,
        receipt_type,
        source,
        normalize_root,
        normalize_path,
    )


def _capture_legacy_binding() -> _LegacyBinding:
    path = _legacy_path()
    source = _stable_source(path)
    module = sys.modules.get(LEGACY_MODULE_NAME)
    if not isinstance(module, types.ModuleType) or _module_origin(module) != (path, path):
        raise ImportError("exact legacy owner must load first")
    plan_type = getattr(module, "_LegacyEffectPlan", None)
    upload_timeout = getattr(module, "transfer_timeout_seconds", None)
    hash_timeout = getattr(module, "hash_timeout_seconds", None)
    server_alias = getattr(module, "DEFAULT_SERVER_ALIAS", None)
    if (
        not isinstance(plan_type, type)
        or tuple(getattr(plan_type, "__slots__", ())) != (*LEGACY_PLAN_FIELDS, "_factory_state", "_owner_seal")
        or not callable(upload_timeout)
        or not callable(hash_timeout)
        or type(server_alias) is not str
        or not server_alias
    ):
        raise ImportError("legacy effect-plan owner identity differs")
    return _LegacyBinding(
        module,
        plan_type,
        source,
        upload_timeout,
        hash_timeout,
        server_alias,
    )


def _register_owner(runtime: _RuntimeBinding) -> None:
    if __name__ != MODULE_NAME or sys.modules.get(MODULE_NAME) is not sys.modules.get(__name__):
        raise ImportError("owner consumer must load under its canonical name")
    current = sys.modules[MODULE_NAME]
    existing = vars(runtime.module).get(_REGISTRATION_ATTRIBUTE, _MISSING)
    if existing is not _MISSING and existing is not current:
        raise ImportError("owner consumer is already registered")
    setattr(runtime.module, _REGISTRATION_ATTRIBUTE, current)


_OWNER_SOURCE = _stable_source(Path(__file__).resolve(strict=True))
_RUNTIME_BINDING = _capture_runtime_binding()
_LEGACY_BINDING = _capture_legacy_binding()
_register_owner(_RUNTIME_BINDING)


def _assert_bindings_current() -> None:
    if (
        sys.modules.get(MODULE_NAME) is not vars(_RUNTIME_BINDING.module).get(_REGISTRATION_ATTRIBUTE)
        or sys.modules.get(RUNTIME_MODULE_NAME) is not _RUNTIME_BINDING.module
        or sys.modules.get(LEGACY_MODULE_NAME) is not _LEGACY_BINDING.module
        or _stable_source(Path(__file__).resolve(strict=True)) != _OWNER_SOURCE
        or _stable_source(_runtime_path()) != _RUNTIME_BINDING.source
        or _stable_source(_legacy_path()) != _LEGACY_BINDING.source
        or getattr(_RUNTIME_BINDING.module, "SealedProtectedRuntimeStateContract", None)
        is not _RUNTIME_BINDING.sealed_type
        or getattr(_RUNTIME_BINDING.module, "SealedProtectedRuntimeStateReceipt", None)
        is not _RUNTIME_BINDING.receipt_type
        or getattr(_RUNTIME_BINDING.module, "_normalized_windows_root", None)
        is not _RUNTIME_BINDING.normalize_root
        or getattr(_RUNTIME_BINDING.module, "_normalized_windows_path", None)
        is not _RUNTIME_BINDING.normalize_path
        or getattr(_LEGACY_BINDING.module, "_LegacyEffectPlan", None)
        is not _LEGACY_BINDING.plan_type
        or getattr(_LEGACY_BINDING.module, "transfer_timeout_seconds", None)
        is not _LEGACY_BINDING.upload_timeout
        or getattr(_LEGACY_BINDING.module, "hash_timeout_seconds", None)
        is not _LEGACY_BINDING.hash_timeout
        or getattr(_LEGACY_BINDING.module, "DEFAULT_SERVER_ALIAS", None)
        != _LEGACY_BINDING.server_alias
    ):
        raise ProtectedOwnerConsumerError("owner module or class identity differs")


def _file_identity(path: Path) -> _FileIdentity:
    descriptor = -1
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
        )
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise ProtectedOwnerConsumerError(
                f"consumer file is not a private regular file: {path.name}"
            )
        hasher = hashlib.sha256()
        total = 0
        while True:
            chunk = os.read(descriptor, _CHUNK_SIZE)
            if not chunk:
                break
            total += len(chunk)
            hasher.update(chunk)
        after = os.fstat(descriptor)
    except OSError as exc:
        raise ProtectedOwnerConsumerError(
            f"consumer file identity is unavailable: {path.name}"
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if _stat_identity(before) != _stat_identity(after) or total != before.st_size:
        raise ProtectedOwnerConsumerError(f"consumer file drifted: {path.name}")
    return _FileIdentity(_stat_identity(after), hasher.hexdigest(), total)


def _write_new_bytes(directory_fd: int, name: str, raw: bytes) -> _FileIdentity:
    descriptor = -1
    try:
        descriptor = os.open(
            name,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            0o600,
            dir_fd=directory_fd,
        )
        view = memoryview(raw)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise ProtectedOwnerConsumerError(
                    f"consumer write made no progress: {name}"
                )
            view = view[written:]
        os.fsync(descriptor)
        info = os.fstat(descriptor)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    expected = hashlib.sha256(raw).hexdigest()
    if info.st_size != len(raw):
        raise ProtectedOwnerConsumerError(f"consumer write was short: {name}")
    return _FileIdentity(_stat_identity(info), expected, len(raw))


def _copy_new_file(
    directory_fd: int,
    source: Path,
    name: str,
    *,
    expected_sha256: str,
    expected_size: int,
) -> _FileIdentity:
    source_fd = -1
    target_fd = -1
    try:
        source_fd = os.open(
            source,
            os.O_RDONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
        )
        source_before = os.fstat(source_fd)
        if not stat.S_ISREG(source_before.st_mode) or source_before.st_nlink != 1:
            raise ProtectedOwnerConsumerError(
                f"predecessor upload source is unsafe: {name}"
            )
        target_fd = os.open(
            name,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            0o600,
            dir_fd=directory_fd,
        )
        hasher = hashlib.sha256()
        total = 0
        while True:
            chunk = os.read(source_fd, _CHUNK_SIZE)
            if not chunk:
                break
            hasher.update(chunk)
            total += len(chunk)
            view = memoryview(chunk)
            while view:
                written = os.write(target_fd, view)
                if written <= 0:
                    raise ProtectedOwnerConsumerError(
                        f"consumer copy made no progress: {name}"
                    )
                view = view[written:]
        os.fsync(target_fd)
        source_after = os.fstat(source_fd)
        target = os.fstat(target_fd)
    finally:
        if target_fd >= 0:
            os.close(target_fd)
        if source_fd >= 0:
            os.close(source_fd)
    actual_sha = hasher.hexdigest()
    if (
        _stat_identity(source_before) != _stat_identity(source_after)
        or total != expected_size
        or target.st_size != expected_size
        or actual_sha != expected_sha256
    ):
        raise ProtectedOwnerConsumerError(
            f"consumer copy differs from exact predecessor bytes: {name}"
        )
    return _FileIdentity(_stat_identity(target), actual_sha, total)


def _derive_intent(runtime_state: object) -> dict[str, Any]:
    materialization = runtime_state.handoff.materialization
    materialization_document = materialization.document()
    invocation = materialization.lifecycle.protected_invocation_bundle
    invocation.assert_owner_sealed()
    protected = invocation.protected_submit_bundle
    protected.assert_owner_sealed()
    protected_document = protected.document()
    reservation = materialization_document["reservation"]
    identity = protected_document["identity"]
    approval = protected_document["approvals"]["live_submission_approval"]
    execution = protected_document["execution"]
    document: dict[str, Any] = {
        "schema": INTENT_SCHEMA,
        "owner": OWNER,
        "intent_id": "protected-owner-intent-" + _ZERO_SHA,
        "project": identity["project"],
        "job_name": identity["project"],
        "remote_workdir": f"{FIXED_REMOTE_ROOT}/{identity['project']}",
        "input_sha256": identity["input_sha256"],
        "scientific_task_id": identity["scientific_task_id"],
        "attempt_id": identity["attempt_id"],
        "idempotency_key_sha256": identity["idempotency_key_sha256"],
        "live_approval_id": approval["approval_id"],
        "live_approval_artifact_sha256": approval["artifact_sha256"],
        "protected_authority": {
            "schema": "auto-g16-protected-submit-reservation/1",
            "bundle_id": protected.bundle_id,
            "bundle_payload_sha256": protected.bundle_payload_sha256,
            "consumption_sha256": reservation["consumption_sha256"],
            "submission_state": reservation["submission_state"],
            "legacy_execution_batch_reservation_present": False,
            "legacy_ledger_is_authority": False,
        },
        "reserved_at": reservation["consumed_at"],
        "automatic_retry": False,
        "intent_payload_sha256": "",
    }
    if (
        execution["batch_id"] == ""
        or reservation["attempt_id"] != identity["attempt_id"]
        or reservation["automatic_retry"] is not False
    ):
        raise ProtectedOwnerConsumerError("protected reservation identity differs")
    document["intent_payload_sha256"] = _payload_sha256(
        document,
        id_field="intent_id",
        payload_field="intent_payload_sha256",
    )
    document["intent_id"] = "protected-owner-intent-" + digest(
        {
            "schema": "auto-g16-protected-owner-intent-id/1",
            "attempt_id": document["attempt_id"],
            "consumption_sha256": reservation["consumption_sha256"],
            "intent_payload_sha256": document["intent_payload_sha256"],
        }
    )
    return validate_protected_owner_submission_intent(document)


def _consumer_path(runtime_state: object) -> Path:
    local_dir = runtime_state.handoff.materialization.local_dir
    if (
        not isinstance(local_dir, Path)
        or not local_dir.is_absolute()
        or local_dir.is_symlink()
    ):
        raise ProtectedOwnerConsumerError("predecessor local directory differs")
    attempt_id = runtime_state.document()["identity"]["attempt_id"]
    return local_dir.parent / CONTAINER_BASENAME / attempt_id


def _ensure_container(path: Path) -> int:
    parent = path.parent.parent
    if parent.is_symlink() or not parent.is_dir():
        raise ProtectedOwnerConsumerError("consumer parent directory differs")
    try:
        os.mkdir(path.parent, mode=0o700)
    except FileExistsError:
        pass
    if path.parent.is_symlink() or not path.parent.is_dir():
        raise ProtectedOwnerConsumerError("consumer container is unsafe")
    return os.open(
        path.parent,
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0),
    )


def _portable_source_artifacts(runtime_state: object) -> list[dict[str, Any]]:
    materialization = runtime_state.handoff.materialization
    document = materialization.document()
    artifacts = []
    for raw in document["materialized_files"]:
        if raw["role"] == "checksums_manifest":
            if raw["relative_name"] != CHECKSUM_BASENAME:
                raise ProtectedOwnerConsumerError(
                    "predecessor checksum role differs"
                )
            continue
        artifacts.append(
            {
                key: raw[key]
                for key in (
                    "role",
                    "relative_name",
                    "order",
                    "sha256",
                    "size_bytes",
                )
            }
        )
    if not artifacts:
        raise ProtectedOwnerConsumerError("predecessor stage bytes are unavailable")
    return artifacts


def _expected_bundle(
    runtime_state: object,
) -> tuple[
    Path,
    dict[str, Any],
    bytes,
    list[dict[str, Any]],
    bytes,
]:
    path = _consumer_path(runtime_state)
    intent = _derive_intent(runtime_state)
    intent_raw = canonical_bytes(intent) + b"\n"
    artifacts = _portable_source_artifacts(runtime_state)
    portable = [
        {
            **item,
            "order": index,
        }
        for index, item in enumerate(artifacts, start=1)
    ]
    portable.append(
        {
            "role": "submission_intent",
            "relative_name": INTENT_BASENAME,
            "order": len(portable) + 1,
            "sha256": hashlib.sha256(intent_raw).hexdigest(),
            "size_bytes": len(intent_raw),
        }
    )
    checksum_raw = "".join(
        f"{item['sha256']}  {item['relative_name']}\n"
        for item in portable
    ).encode("utf-8")
    portable.append(
        {
            "role": "checksums_manifest",
            "relative_name": CHECKSUM_BASENAME,
            "order": len(portable) + 1,
            "sha256": hashlib.sha256(checksum_raw).hexdigest(),
            "size_bytes": len(checksum_raw),
        }
    )
    return path, intent, intent_raw, portable, checksum_raw


def _materialize_bundle(
    runtime_state: object,
) -> tuple[Path, dict[str, _FileIdentity], list[dict[str, Any]]]:
    path, _intent, intent_raw, portable, checksum_raw = _expected_bundle(runtime_state)
    container_fd = _ensure_container(path)
    directory_fd = -1
    try:
        os.mkdir(path.name, mode=0o700, dir_fd=container_fd)
        directory_fd = os.open(
            path.name,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            dir_fd=container_fd,
        )
        identities: dict[str, _FileIdentity] = {}
        source_dir = runtime_state.handoff.materialization.local_dir
        for item in portable[:-2]:
            name = item["relative_name"]
            identities[name] = _copy_new_file(
                directory_fd,
                source_dir / name,
                name,
                expected_sha256=item["sha256"],
                expected_size=item["size_bytes"],
            )
        identities[INTENT_BASENAME] = _write_new_bytes(
            directory_fd,
            INTENT_BASENAME,
            intent_raw,
        )
        identities[CHECKSUM_BASENAME] = _write_new_bytes(
            directory_fd,
            CHECKSUM_BASENAME,
            checksum_raw,
        )
        os.fsync(directory_fd)
        os.fsync(container_fd)
    except FileExistsError as exc:
        raise ProtectedOwnerConsumerError(
            "consumer upload bundle already exists; explicit recovery is required"
        ) from exc
    except OSError as exc:
        raise ProtectedOwnerConsumerError(
            f"consumer upload materialization failed: {exc}"
        ) from exc
    finally:
        if directory_fd >= 0:
            os.close(directory_fd)
        os.close(container_fd)
    _assert_bundle_current(path, identities, portable)
    return path, identities, portable


def _recover_bundle(
    runtime_state: object,
) -> tuple[Path, dict[str, _FileIdentity], list[dict[str, Any]]]:
    path, _intent, _intent_raw, portable, _checksum_raw = _expected_bundle(runtime_state)
    if path.is_symlink() or not path.is_dir():
        raise ProtectedOwnerConsumerError(
            "recoverable consumer upload bundle is unavailable"
        )
    identities = {
        item["relative_name"]: _file_identity(path / item["relative_name"])
        for item in portable
    }
    _assert_bundle_current(path, identities, portable)
    return path, identities, portable


def _assert_bundle_current(
    path: Path,
    identities: dict[str, _FileIdentity],
    portable: list[dict[str, Any]],
) -> None:
    expected_names = [item["relative_name"] for item in portable]
    if (
        path.is_symlink()
        or not path.is_dir()
        or sorted(os.listdir(path)) != sorted(expected_names)
        or set(identities) != set(expected_names)
    ):
        raise ProtectedOwnerConsumerError("consumer upload topology differs")
    for item in portable:
        name = item["relative_name"]
        current = _file_identity(path / name)
        if (
            current != identities[name]
            or current.sha256 != item["sha256"]
            or current.size_bytes != item["size_bytes"]
        ):
            raise ProtectedOwnerConsumerError(
                f"consumer upload identity differs: {name}"
            )


def _private_plan_values(
    runtime_state: object,
    upload_path: Path,
    portable: list[dict[str, Any]],
) -> dict[str, Any]:
    values = dict(runtime_state.runtime_values)
    document = runtime_state.document()
    identity = document["identity"]
    normalized_root, _root_identity = _RUNTIME_BINDING.normalize_root(
        values["windows_project_root"]
    )
    normalized_second, _second_identity = _RUNTIME_BINDING.normalize_path(
        values["windows_server_config"],
        label="second-hop config reference",
        allow_hidden_component=True,
    )
    files = tuple(upload_path / item["relative_name"] for item in portable)
    bindings = tuple(
        (item["relative_name"], item["sha256"]) for item in portable
    )
    total = sum(item["size_bytes"] for item in portable)
    plan = {
        "project": identity["project"],
        "windows_dir": f"{normalized_root}\\{identity['project']}",
        "remote_dir": f"{FIXED_REMOTE_ROOT}/{identity['project']}",
        "files": files,
        "expected_bindings": bindings,
        "upload_timeout_seconds": _LEGACY_BINDING.upload_timeout(total),
        "upload_hash_timeout_seconds": _LEGACY_BINDING.hash_timeout(total),
        "attempt_id": identity["attempt_id"],
        "input_sha256": identity["input_sha256"],
        "mac_ssh_config": values["rtwin_ssh_config"],
        "rtwin_alias": values["windows_target"],
        "windows_server_config": normalized_second,
        "server_alias": _LEGACY_BINDING.server_alias,
    }
    if set(plan) != set(LEGACY_PLAN_FIELDS):
        raise ProtectedOwnerConsumerError("legacy plan field mapping differs")
    return plan


def _build_document(
    runtime_state: object,
    uncertain_receipt: object,
    upload_path: Path,
    portable: list[dict[str, Any]],
    plan: dict[str, Any],
) -> dict[str, Any]:
    runtime_document = runtime_state.document()
    receipt = uncertain_receipt.document()
    intent = _derive_intent(runtime_state)
    total = sum(item["size_bytes"] for item in portable)
    names = [item["relative_name"] for item in portable]
    intent_file_sha = portable[-2]["sha256"]
    document: dict[str, Any] = {
        "schema": SCHEMA,
        "owner": OWNER,
        "contract_id": "protected-owner-consumer-" + _ZERO_SHA,
        "runtime_state": {
            "schema": runtime_document["schema"],
            "contract_id": runtime_document["contract_id"],
            "contract_payload_sha256": runtime_document[
                "contract_payload_sha256"
            ],
            "journal_id": runtime_document["journal"]["journal_id"],
            "uncertain_receipt_id": receipt["receipt_id"],
            "uncertain_receipt_payload_sha256": receipt[
                "receipt_payload_sha256"
            ],
            "uncertain_state": receipt["state"],
        },
        "identity": {
            "project": runtime_document["identity"]["project"],
            "attempt_id": runtime_document["identity"]["attempt_id"],
            "input_sha256": runtime_document["identity"]["input_sha256"],
        },
        "intent": intent,
        "upload_bundle": {
            "container_basename": CONTAINER_BASENAME,
            "directory_path_sha256": digest(str(upload_path)),
            "artifacts": portable,
            "artifact_count": len(portable),
            "total_size_bytes": total,
            "expected_bindings_sha256": digest(
                [(item["relative_name"], item["sha256"]) for item in portable]
            ),
            "checksum_semantics": {
                "schema": "auto-g16-legacy-checksum-manifest-semantics/1",
                "basename": CHECKSUM_BASENAME,
                "line_format": "<sha256><two-spaces><basename><LF>",
                "line_order": names[:-1],
                "self_entry": False,
                "intent_entry": True,
            },
            "predecessor_checksum_uploaded": False,
            "predecessor_state_uploaded": False,
            "predecessor_ledger_uploaded": False,
        },
        "effect_plan_projection": {
            "legacy_module": LEGACY_MODULE_NAME,
            "legacy_plan_class": "_LegacyEffectPlan",
            "required_fields": list(LEGACY_PLAN_FIELDS),
            "effect_steps": list(FIXED_EFFECT_STEPS),
            "windows_directory_sha256": digest(plan["windows_dir"]),
            "remote_directory": plan["remote_dir"],
            "first_hop_config_path_sha256": digest(plan["mac_ssh_config"]),
            "first_hop_alias_sha256": digest(plan["rtwin_alias"]),
            "second_hop_config_sha256": digest(plan["windows_server_config"]),
            "server_alias_sha256": digest(plan["server_alias"]),
            "upload_timeout_seconds": plan["upload_timeout_seconds"],
            "upload_hash_timeout_seconds": plan[
                "upload_hash_timeout_seconds"
            ],
            "effect_plan_created": False,
            "raw_effect_owner_created": False,
        },
        "reconciliation_inputs": {
            "schema": "auto-g16-protected-owner-consumer-reconciliation-inputs/1",
            "project": runtime_document["identity"]["project"],
            "attempt_id": runtime_document["identity"]["attempt_id"],
            "input_sha256": runtime_document["identity"]["input_sha256"],
            "intent_id": intent["intent_id"],
            "intent_file_sha256": intent_file_sha,
            "uncertain_receipt_id": receipt["receipt_id"],
            "uncertain_receipt_payload_sha256": receipt[
                "receipt_payload_sha256"
            ],
            "required_remote_observations": [
                "project_directory",
                "submission_intent",
                "submission_receipt",
                "qstat_exact_attempt",
            ],
            "observation_acquired": False,
            "remote_read_performed": False,
            "automatic_effect_authorized": False,
            "automatic_retry": False,
        },
        "owner_bindings": {
            "consumer_owner_source_sha256": _OWNER_SOURCE.sha256,
            "runtime_owner_source_sha256": _RUNTIME_BINDING.source.sha256,
            "legacy_owner_source_sha256": _LEGACY_BINDING.source.sha256,
        },
        "validation": dict(VALIDATION),
        "scope": dict(SCOPE),
        "policy": dict(POLICY),
        "contract_payload_sha256": "",
    }
    document["contract_payload_sha256"] = _payload_sha256(
        document,
        id_field="contract_id",
        payload_field="contract_payload_sha256",
    )
    document["contract_id"] = "protected-owner-consumer-" + digest(
        {
            "schema": "auto-g16-protected-owner-consumer-id/1",
            "runtime_contract_id": runtime_document["contract_id"],
            "uncertain_receipt_payload_sha256": receipt[
                "receipt_payload_sha256"
            ],
            "expected_bindings_sha256": document["upload_bundle"][
                "expected_bindings_sha256"
            ],
            "contract_payload_sha256": document[
                "contract_payload_sha256"
            ],
        }
    )
    return validate_protected_owner_consumer_contract(document)


@dataclass(frozen=True, slots=True, init=False)
class ProtectedLegacyEffectPlanInputs:
    project: str
    windows_dir: str
    remote_dir: str
    files: tuple[Path, ...]
    expected_bindings: tuple[tuple[str, str], ...]
    upload_timeout_seconds: int
    upload_hash_timeout_seconds: int
    attempt_id: str
    input_sha256: str
    mac_ssh_config: str
    rtwin_alias: str
    windows_server_config: str
    server_alias: str
    _seal: object

    def __new__(cls, *args: Any, **kwargs: Any) -> "ProtectedLegacyEffectPlanInputs":
        raise TypeError("legacy effect-plan inputs are owner-issued only")

    @classmethod
    def _from_owner(
        cls,
        values: dict[str, Any],
        *,
        token: object,
    ) -> "ProtectedLegacyEffectPlanInputs":
        _assert_bindings_current()
        if cls is not ProtectedLegacyEffectPlanInputs or token is not _PLAN_INPUT_TOKEN:
            raise ProtectedOwnerConsumerError("legacy effect-plan input seal differs")
        value = object.__new__(cls)
        for name in LEGACY_PLAN_FIELDS:
            object.__setattr__(value, name, values[name])
        object.__setattr__(value, "_seal", _PLAN_INPUT_TOKEN)
        return value

    def assert_owner_sealed(self) -> "ProtectedLegacyEffectPlanInputs":
        _assert_bindings_current()
        if type(self) is not ProtectedLegacyEffectPlanInputs or self._seal is not _PLAN_INPUT_TOKEN:
            raise ProtectedOwnerConsumerError("legacy effect-plan input seal differs")
        if (
            tuple(path.name for path in self.files)
            != tuple(name for name, _sha256 in self.expected_bindings)
            or self.remote_dir != f"{FIXED_REMOTE_ROOT}/{self.project}"
            or type(self.upload_timeout_seconds) is not int
            or self.upload_timeout_seconds < 1
            or type(self.upload_hash_timeout_seconds) is not int
            or self.upload_hash_timeout_seconds < 1
        ):
            raise ProtectedOwnerConsumerError("legacy effect-plan inputs differ")
        return self

    def __copy__(self) -> "ProtectedLegacyEffectPlanInputs":
        raise TypeError("legacy effect-plan inputs are not clonable")

    def __deepcopy__(self, memo: dict[int, Any]) -> "ProtectedLegacyEffectPlanInputs":
        del memo
        raise TypeError("legacy effect-plan inputs are not clonable")

    def __reduce__(self) -> object:
        raise TypeError("legacy effect-plan inputs are not serializable")

    def __reduce_ex__(self, protocol: int) -> object:
        del protocol
        raise TypeError("legacy effect-plan inputs are not serializable")


@dataclass(frozen=True, slots=True, init=False)
class SealedProtectedOwnerConsumerContract:
    _canonical_document: bytes
    runtime_state: object
    uncertain_receipt: object
    upload_path: Path
    _identities: dict[str, _FileIdentity]
    _portable: tuple[tuple[str, str, int, str, int], ...]
    _plan_values: dict[str, Any]
    _claim_lock: threading.Lock
    _claimed: bool
    _seal: object

    def __new__(cls, *args: Any, **kwargs: Any) -> "SealedProtectedOwnerConsumerContract":
        raise TypeError("owner consumer contracts are owner-issued only")

    @classmethod
    def _from_owner(
        cls,
        document: dict[str, Any],
        *,
        runtime_state: object,
        uncertain_receipt: object,
        upload_path: Path,
        identities: dict[str, _FileIdentity],
        portable: list[dict[str, Any]],
        plan_values: dict[str, Any],
        token: object,
    ) -> "SealedProtectedOwnerConsumerContract":
        _assert_bindings_current()
        if cls is not SealedProtectedOwnerConsumerContract or token is not _SEAL_TOKEN:
            raise ProtectedOwnerConsumerError("owner consumer seal differs")
        value = object.__new__(cls)
        object.__setattr__(value, "_canonical_document", canonical_bytes(document))
        object.__setattr__(value, "runtime_state", runtime_state)
        object.__setattr__(value, "uncertain_receipt", uncertain_receipt)
        object.__setattr__(value, "upload_path", upload_path)
        object.__setattr__(value, "_identities", dict(identities))
        object.__setattr__(
            value,
            "_portable",
            tuple(
                (
                    item["role"],
                    item["relative_name"],
                    item["order"],
                    item["sha256"],
                    item["size_bytes"],
                )
                for item in portable
            ),
        )
        object.__setattr__(value, "_plan_values", dict(plan_values))
        object.__setattr__(value, "_claim_lock", threading.Lock())
        object.__setattr__(value, "_claimed", False)
        object.__setattr__(value, "_seal", _SEAL_TOKEN)
        return value

    def document(self) -> dict[str, Any]:
        return json.loads(self._canonical_document)

    def _portable_documents(self) -> list[dict[str, Any]]:
        return [
            {
                "role": role,
                "relative_name": name,
                "order": order,
                "sha256": sha256,
                "size_bytes": size,
            }
            for role, name, order, sha256, size in self._portable
        ]

    def assert_current(self) -> "SealedProtectedOwnerConsumerContract":
        _assert_bindings_current()
        if (
            type(self) is not SealedProtectedOwnerConsumerContract
            or self._seal is not _SEAL_TOKEN
            or type(self.runtime_state) is not _RUNTIME_BINDING.sealed_type
            or type(self.uncertain_receipt) is not _RUNTIME_BINDING.receipt_type
        ):
            raise ProtectedOwnerConsumerError("owner consumer identity differs")
        self.runtime_state.assert_current()
        self.uncertain_receipt.assert_current()
        current = self.runtime_state.current_receipt
        if (
            current is not self.uncertain_receipt
            or current.document()["state"] != "effect_started_outcome_uncertain"
        ):
            raise ProtectedOwnerConsumerError("owner consumer uncertain state differs")
        _assert_bundle_current(
            self.upload_path,
            self._identities,
            self._portable_documents(),
        )
        document = validate_protected_owner_consumer_contract(self.document())
        if canonical_bytes(document) != self._canonical_document:
            raise ProtectedOwnerConsumerError("owner consumer projection differs")
        expected_plan = _private_plan_values(
            self.runtime_state,
            self.upload_path,
            self._portable_documents(),
        )
        if expected_plan != self._plan_values:
            raise ProtectedOwnerConsumerError("owner consumer private plan mapping differs")
        return self

    def claim_effect_plan_inputs_once(self) -> ProtectedLegacyEffectPlanInputs:
        with self._claim_lock:
            if self._claimed:
                raise ProtectedOwnerConsumerError(
                    "owner consumer plan inputs have already been claimed"
                )
            self.assert_current()
            object.__setattr__(self, "_claimed", True)
            return ProtectedLegacyEffectPlanInputs._from_owner(
                self._plan_values,
                token=_PLAN_INPUT_TOKEN,
            )

    def read_only_reconciliation_inputs(self) -> dict[str, Any]:
        self.assert_current()
        return self.document()["reconciliation_inputs"]

    def __copy__(self) -> "SealedProtectedOwnerConsumerContract":
        raise TypeError("owner consumer contracts are not clonable")

    def __deepcopy__(self, memo: dict[int, Any]) -> "SealedProtectedOwnerConsumerContract":
        del memo
        raise TypeError("owner consumer contracts are not clonable")

    def __reduce__(self) -> object:
        raise TypeError("owner consumer contracts are not serializable")

    def __reduce_ex__(self, protocol: int) -> object:
        del protocol
        raise TypeError("owner consumer contracts are not serializable")


class ProtectedOwnerConsumerContractOwner:
    """The sole local consumer of one exact ready runtime/state capability."""

    def __init__(self, *, _factory_token: object) -> None:
        _assert_bindings_current()
        if type(self) is not ProtectedOwnerConsumerContractOwner or _factory_token is not _OWNER_TOKEN:
            raise TypeError("owner consumer requires its fixed factory")
        self._lock = threading.Lock()
        self._used = False

    @classmethod
    def production(cls) -> "ProtectedOwnerConsumerContractOwner":
        return cls(_factory_token=_OWNER_TOKEN)

    def _finish(
        self,
        runtime_state: object,
        *,
        recover_existing: bool,
    ) -> SealedProtectedOwnerConsumerContract:
        if type(runtime_state) is not _RUNTIME_BINDING.sealed_type:
            raise TypeError("owner consumer accepts only exact runtime/state capability")
        runtime_state.assert_current()
        if recover_existing:
            upload_path, identities, portable = _recover_bundle(runtime_state)
        else:
            upload_path, identities, portable = _materialize_bundle(runtime_state)
        runtime_state.assert_current()
        current = runtime_state.current_receipt
        state = current.document()["state"]
        if state == "ready":
            not_started = runtime_state.consume_for_effect_once()
        elif recover_existing and state == "effect_not_started":
            not_started = current
        else:
            raise ProtectedOwnerConsumerError(
                "owner consumer requires ready or recoverable not-started state"
            )
        _assert_bindings_current()
        runtime_state.assert_current()
        _assert_bundle_current(upload_path, identities, portable)
        uncertain = runtime_state.prepare_effect_boundary_once(not_started)
        uncertain.assert_current()
        plan = _private_plan_values(runtime_state, upload_path, portable)
        document = _build_document(
            runtime_state,
            uncertain,
            upload_path,
            portable,
            plan,
        )
        sealed = SealedProtectedOwnerConsumerContract._from_owner(
            document,
            runtime_state=runtime_state,
            uncertain_receipt=uncertain,
            upload_path=upload_path,
            identities=identities,
            portable=portable,
            plan_values=plan,
            token=_SEAL_TOKEN,
        )
        sealed.assert_current()
        return sealed

    def prepare_once(
        self,
        runtime_state: object,
    ) -> SealedProtectedOwnerConsumerContract:
        with self._lock:
            if self._used:
                raise ProtectedOwnerConsumerError("owner consumer is single-use")
            self._used = True
            return self._finish(runtime_state, recover_existing=False)

    def recover_before_effect_once(
        self,
        runtime_state: object,
    ) -> SealedProtectedOwnerConsumerContract:
        with self._lock:
            if self._used:
                raise ProtectedOwnerConsumerError("owner consumer is single-use")
            self._used = True
            return self._finish(runtime_state, recover_existing=True)

    def read_only_reconciliation_inputs(
        self,
        runtime_state: object,
    ) -> dict[str, Any]:
        """Rebuild only local reconciliation inputs from an uncertain journal."""
        with self._lock:
            if self._used:
                raise ProtectedOwnerConsumerError("owner consumer is single-use")
            self._used = True
            if type(runtime_state) is not _RUNTIME_BINDING.sealed_type:
                raise TypeError("owner consumer accepts only exact runtime/state capability")
            runtime_state.assert_current()
            if (
                runtime_state.current_receipt.document()["state"]
                != "effect_started_outcome_uncertain"
            ):
                raise ProtectedOwnerConsumerError(
                    "read-only reconciliation requires uncertain state"
                )
            upload_path, identities, portable = _recover_bundle(runtime_state)
            _assert_bundle_current(upload_path, identities, portable)
            intent = _derive_intent(runtime_state)
            return {
                "schema": "auto-g16-protected-owner-consumer-reconciliation-inputs/1",
                "project": intent["project"],
                "attempt_id": intent["attempt_id"],
                "input_sha256": intent["input_sha256"],
                "intent_id": intent["intent_id"],
                "intent_file_sha256": portable[-2]["sha256"],
                "uncertain_receipt_id": runtime_state.current_receipt.document()[
                    "receipt_id"
                ],
                "uncertain_receipt_payload_sha256": runtime_state.current_receipt.document()[
                    "receipt_payload_sha256"
                ],
                "required_remote_observations": [
                    "project_directory",
                    "submission_intent",
                    "submission_receipt",
                    "qstat_exact_attempt",
                ],
                "observation_acquired": False,
                "remote_read_performed": False,
                "automatic_effect_authorized": False,
                "automatic_retry": False,
            }
