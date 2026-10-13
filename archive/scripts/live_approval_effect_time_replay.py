#!/usr/bin/env python3
"""Issue one non-authorizing, effect-time live-approval replay capability.

The owner is deliberately offline and effect-free.  It binds one exact
protected production-ingress predecessor to the already approved live
approval file, then permits exactly one replay through the existing
``legacy_rtwin_pbs`` live-approval owner.  It never constructs an effect plan,
calls a runner, invokes qsub, or accepts a caller path as authority.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import stat
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

import protected_production_ingress_contract as _INGRESS
import direct_ssh_pbs_offline as _DIRECT


MODULE_NAME = "live_approval_effect_time_replay"
SCHEMA = "auto-g16-live-approval-effect-time-replay/1"
OWNER = "auto-g16-live-approval-effect-time-replay-owner"
PHASE = "immediately_before_qsub"
SUPPORTED_APPROVALS = {
    "auto-g16-live-submission-approval/9",
    "auto-g16-live-submission-approval/10",
    "auto-g16-live-submission-approval/11",
    "auto-g16-live-submission-approval/13",
}
SHA_RE = re.compile(r"^[a-f0-9]{64}$")
CAPABILITY_ID_RE = re.compile(
    r"^pre-qsub-live-approval-replay-[a-f0-9]{64}$"
)
RFC3339_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$"
)
_MAX_APPROVAL_BYTES = 2 * 1024 * 1024
_MAX_JSON_DEPTH = 48
_REGISTRATION_ATTRIBUTE = (
    "_AUTO_G16_LIVE_APPROVAL_EFFECT_TIME_REPLAY_OWNER"
)
_CAPABILITY_TOKEN = object()
_RESULT_TOKEN = object()
_OWNER_TOKEN = object()
_TEST_OWNER_TOKEN = object()
_ZERO_SHA = "0" * 64
_LIVE_OWNER_LOCK = threading.RLock()
_DIRECT_PREDECESSOR_SCHEMA = "auto-g16-direct-server-session-live-source/1"


class LiveApprovalEffectTimeReplayError(ValueError):
    """The exact effect-time approval replay cannot be proved."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise LiveApprovalEffectTimeReplayError(message)


def _rebuild_json(
    value: Any,
    *,
    depth: int = 0,
    active: set[int] | None = None,
) -> Any:
    if depth > _MAX_JSON_DEPTH:
        raise LiveApprovalEffectTimeReplayError(
            "effect-time replay document exceeds nesting bound"
        )
    if value is None or type(value) in {str, bool, int}:
        return value
    if active is None:
        active = set()
    identity = id(value)
    if identity in active:
        raise LiveApprovalEffectTimeReplayError(
            "effect-time replay document contains a cycle"
        )
    active.add(identity)
    try:
        if type(value) is list:
            length = len(value)
            result = [
                _rebuild_json(item, depth=depth + 1, active=active)
                for item in value
            ]
            _require(
                len(value) == length,
                "effect-time replay list changed during validation",
            )
            return result
        if type(value) is dict:
            items = list(value.items())
            _require(
                all(type(key) is str for key, _ in items),
                "effect-time replay keys must be exact strings",
            )
            result = {
                key: _rebuild_json(
                    item,
                    depth=depth + 1,
                    active=active,
                )
                for key, item in items
            }
            _require(
                list(value.items()) == items,
                "effect-time replay object changed during validation",
            )
            return result
    finally:
        active.remove(identity)
    raise LiveApprovalEffectTimeReplayError(
        "effect-time replay accepts only exact builtin JSON values"
    )


def canonical_bytes(value: Any) -> bytes:
    rebuilt = _rebuild_json(value)
    try:
        raw = json.dumps(
            rebuilt,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise LiveApprovalEffectTimeReplayError(
            f"effect-time replay document is not canonical JSON: {exc}"
        ) from exc
    return (raw + "\n").encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _exact(
    value: Any,
    fields: set[str],
    label: str,
) -> dict[str, Any]:
    _require(
        type(value) is dict and set(value) == fields,
        f"{label} fields differ",
    )
    return value


def _text(value: Any, label: str) -> str:
    _require(type(value) is str and value != "", f"{label} is empty")
    return value


def _sha(value: Any, label: str, *, nonzero: bool = True) -> str:
    _require(
        type(value) is str and SHA_RE.fullmatch(value) is not None,
        f"{label} is not SHA-256",
    )
    if nonzero:
        _require(value != _ZERO_SHA, f"{label} must be nonzero")
    return value


def _positive_integer(value: Any, label: str) -> int:
    _require(
        type(value) is int and value > 0,
        f"{label} must be a positive integer",
    )
    return value


def _fixed_boolean(value: Any, expected: bool, label: str) -> bool:
    _require(
        type(value) is bool and value is expected,
        f"{label} differs",
    )
    return expected


def _fixed_integer(value: Any, expected: int, label: str) -> int:
    _require(
        type(value) is int and value == expected,
        f"{label} differs",
    )
    return expected


def _utc(value: Any, label: str) -> datetime:
    _require(
        type(value) is str and RFC3339_RE.fullmatch(value) is not None,
        f"{label} must be canonical UTC",
    )
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise LiveApprovalEffectTimeReplayError(
            f"{label} is not a real timestamp"
        ) from exc
    _require(parsed.utcoffset() == timedelta(0), f"{label} must be UTC")
    return parsed


def _trusted_wall(value: datetime) -> datetime:
    _require(
        type(value) is datetime
        and value.tzinfo is not None
        and value.utcoffset() is not None,
        "owner wall clock must return timezone-aware UTC",
    )
    return value.astimezone(timezone.utc)


def _format_utc(value: datetime) -> str:
    return _trusted_wall(value).isoformat(
        timespec="microseconds"
    ).replace("+00:00", "Z")


def _parse_json_bytes(raw: bytes, label: str) -> dict[str, Any]:
    def reject_constant(token: str) -> None:
        raise LiveApprovalEffectTimeReplayError(
            f"{label} contains non-standard number {token}"
        )

    def reject_duplicates(
        pairs: list[tuple[str, Any]],
    ) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise LiveApprovalEffectTimeReplayError(
                    f"{label} contains duplicate key {key}"
                )
            result[key] = value
        return result

    try:
        value = json.loads(
            raw.decode("utf-8"),
            parse_constant=reject_constant,
            object_pairs_hook=reject_duplicates,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LiveApprovalEffectTimeReplayError(
            f"{label} is not strict UTF-8 JSON"
        ) from exc
    _require(type(value) is dict, f"{label} must be an object")
    return value


@dataclass(frozen=True, slots=True)
class _FileSnapshot:
    path: Path
    identity: tuple[int, int, int, int, int]
    raw: bytes
    sha256: str

    @property
    def identity_sha256(self) -> str:
        return digest(
            {
                "schema": "auto-g16-file-identity/1",
                "resolved_path_sha256": digest(str(self.path)),
                "device": str(self.identity[0]),
                "inode": str(self.identity[1]),
                "size": str(self.identity[2]),
                "mtime_ns": str(self.identity[3]),
                "ctime_ns": str(self.identity[4]),
            }
        )


@dataclass(frozen=True, slots=True)
class _SourceSnapshot:
    path: Path
    identity: tuple[int, int, int, int, int]
    sha256: str


def _stat_identity(info: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _capture_file(path: Path, label: str) -> _FileSnapshot:
    expanded = Path(path).expanduser().absolute()
    _require(not expanded.is_symlink(), f"{label} must not be a symlink")
    try:
        resolved = expanded.resolve(strict=True)
        descriptor = os.open(
            resolved,
            os.O_RDONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
        )
    except OSError as exc:
        raise LiveApprovalEffectTimeReplayError(
            f"{label} cannot be opened without following the file: {exc}"
        ) from exc
    try:
        before = os.fstat(descriptor)
        _require(stat.S_ISREG(before.st_mode), f"{label} is not regular")
        _require(
            before.st_size <= _MAX_APPROVAL_BYTES,
            f"{label} exceeds the bounded owner read",
        )
        chunks: list[bytes] = []
        total = 0
        hasher = hashlib.sha256()
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            hasher.update(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    identity = _stat_identity(before)
    _require(
        identity == _stat_identity(after) and total == before.st_size,
        f"{label} changed during owner capture",
    )
    current = resolved.lstat()
    _require(
        not stat.S_ISLNK(current.st_mode)
        and _stat_identity(current) == identity,
        f"{label} path identity differs from the captured descriptor",
    )
    return _FileSnapshot(
        resolved,
        identity,
        b"".join(chunks),
        hasher.hexdigest(),
    )


def _capture_source(module: ModuleType, label: str) -> _SourceSnapshot:
    raw_path = getattr(module, "__file__", None)
    _require(type(raw_path) is str, f"{label} has no exact source")
    snapshot = _capture_file(Path(raw_path), f"{label} source")
    return _SourceSnapshot(
        snapshot.path,
        snapshot.identity,
        snapshot.sha256,
    )


def _assert_source_current(
    expected: _SourceSnapshot,
    module: ModuleType,
    label: str,
) -> None:
    current = _capture_source(module, label)
    _require(current == expected, f"{label} source was replaced or changed")


def _module_registration() -> ModuleType:
    current = sys.modules.get(MODULE_NAME)
    _require(
        type(current) is ModuleType and current.__name__ == MODULE_NAME,
        "effect-time replay owner must use its canonical module",
    )
    return current


_THIS_MODULE = _module_registration()
_require(
    not hasattr(_INGRESS, _REGISTRATION_ATTRIBUTE),
    "effect-time replay owner is already registered",
)
setattr(_INGRESS, _REGISTRATION_ATTRIBUTE, _THIS_MODULE)
_LEGACY = _INGRESS._LEGACY_BINDING.module
_LIVE_VALIDATOR = _LEGACY.validate_live_approval_binding
_LIVE_SCOPE_OWNER = _LEGACY.expected_live_approval_scope
_OWNER_SOURCE = _capture_source(_THIS_MODULE, "effect-time replay owner")
_INGRESS_SOURCE = _capture_source(_INGRESS, "production ingress owner")
_LIVE_OWNER_SOURCE = _capture_source(_LEGACY, "live-approval owner")
_DIRECT_OWNER_SOURCE = _capture_source(_DIRECT, "direct server-session owner")


def _assert_bindings_current() -> None:
    _require(
        sys.modules.get(MODULE_NAME) is _THIS_MODULE,
        "canonical effect-time replay module was replaced",
    )
    _require(
        getattr(_INGRESS, _REGISTRATION_ATTRIBUTE, None) is _THIS_MODULE,
        "effect-time replay owner registration was replaced",
    )
    _INGRESS._assert_bindings_current()
    _require(
        _INGRESS._LEGACY_BINDING.module is _LEGACY
        and sys.modules.get(_DIRECT.__name__) is _DIRECT
        and getattr(_DIRECT, "DirectServerSessionTransaction", None)
        is _DIRECT.DirectServerSessionTransaction
        and _LEGACY.validate_live_approval_binding is _LIVE_VALIDATOR
        and _LEGACY.expected_live_approval_scope is _LIVE_SCOPE_OWNER,
        "existing live-approval owner identity was replaced",
    )
    _assert_source_current(
        _OWNER_SOURCE,
        _THIS_MODULE,
        "effect-time replay owner",
    )
    _assert_source_current(
        _INGRESS_SOURCE,
        _INGRESS,
        "production ingress owner",
    )
    _assert_source_current(
        _LIVE_OWNER_SOURCE,
        _LEGACY,
        "live-approval owner",
    )
    _assert_source_current(
        _DIRECT_OWNER_SOURCE,
        _DIRECT,
        "direct server-session owner",
    )


def _summary_from_approval(
    approval: dict[str, Any],
) -> dict[str, Any]:
    scope = _exact(
        approval.get("scope"),
        {
            "project",
            "remote_workdir",
            "input_sha256",
            "route",
            "mem",
            "nprocshared",
            "charge",
            "multiplicity",
            "work_kind",
            "input_approval",
            "operation",
            "execution",
        }
        | (
            {"open_shell_owner"}
            if approval.get("schema")
            == "auto-g16-live-submission-approval/10"
            else {"open_shell_family"}
            if approval.get("schema")
            == "auto-g16-live-submission-approval/11"
            else {"ts_qst_owner", "scientific_maturity"}
            if approval.get("schema")
            == "auto-g16-live-submission-approval/13"
            else set()
        ),
        "live approval scope",
    )
    input_approval = copy.deepcopy(scope["input_approval"])
    _require(
        type(input_approval) is dict,
        "live approval input binding is not an object",
    )
    input_approval["status"] = "validated_exact_input_approval"
    if "open_shell_owner" in scope:
        input_approval["specialist_owner_binding"] = copy.deepcopy(
            scope["open_shell_owner"]
        )
    if "open_shell_family" in scope:
        input_approval["specialist_family_binding"] = copy.deepcopy(
            scope["open_shell_family"]
        )
    if "ts_qst_owner" in scope:
        input_approval["specialist_owner_binding"] = copy.deepcopy(
            scope["ts_qst_owner"]
        )
    summary = {
        "project": scope["project"],
        "remote_workdir": scope["remote_workdir"],
        "input_sha256": scope["input_sha256"],
        "protocol": {
            "route": scope["route"],
            "mem": scope["mem"],
            "nproc": scope["nprocshared"],
        },
        "charge": scope["charge"],
        "multiplicity": scope["multiplicity"],
        "work_kind": scope["work_kind"],
        "input_approval": input_approval,
        "execution": copy.deepcopy(scope["execution"]),
    }
    if "scientific_maturity" in scope:
        owner = scope["ts_qst_owner"]
        summary["scientific_maturity"] = {
            "schema": "gaussian-scientific-maturity-action/2",
            "edge_id": scope["scientific_maturity"]["edge_id"],
            "node_id": scope["scientific_maturity"]["node_id"],
            "pilot": scope["scientific_maturity"]["pilot"],
            "maturity_gate_sha256": scope["scientific_maturity"][
                "maturity_gate_sha256"
            ],
            "maturity_gate_payload_sha256": scope["scientific_maturity"][
                "maturity_gate_payload_sha256"
            ],
            "exact_action_authorization": {
                "sha256": owner[
                    "scientific_action_authorization_sha256"
                ],
                "payload_sha256": owner[
                    "scientific_action_authorization_payload_sha256"
                ],
                "candidate_search": copy.deepcopy(
                    owner.get("candidate_search")
                ),
            },
        }
    return summary


def _bind_live_owner_clock(
    trusted_now: datetime,
) -> tuple[type[datetime], type[datetime]]:
    original = _LEGACY.datetime

    class BoundDateTime(datetime):
        @classmethod
        def now(cls, tz: timezone | None = None) -> datetime:
            if tz is None:
                return trusted_now.replace(tzinfo=None)
            return trusted_now.astimezone(tz)

    _LEGACY.datetime = BoundDateTime
    return original, BoundDateTime


def _replay_existing_owner(
    path: Path,
    expected_snapshot: _FileSnapshot,
    expected_document: dict[str, Any] | None,
    trusted_now: datetime,
) -> tuple[dict[str, Any], _FileSnapshot]:
    with _LIVE_OWNER_LOCK:
        before = _capture_file(path, "live approval record")
        _require(
            before == expected_snapshot,
            "live approval file identity, bytes, or hash drifted",
        )
        parsed = _parse_json_bytes(before.raw, "live approval record")
        summary = _summary_from_approval(parsed)
        original, bound = _bind_live_owner_clock(trusted_now)
        try:
            validated, artifact_sha256 = _LIVE_VALIDATOR(path, summary)
        except SystemExit as exc:
            raise LiveApprovalEffectTimeReplayError(
                "existing live-approval owner rejected effect-time replay"
            ) from exc
        finally:
            _require(
                _LEGACY.datetime is bound,
                "existing live-approval owner clock binding was replaced",
            )
            _LEGACY.datetime = original
        after = _capture_file(path, "live approval record")
        _require(
            after == before == expected_snapshot,
            "live approval file changed across existing-owner replay",
        )
        _require(
            artifact_sha256 == expected_snapshot.sha256
            and validated == parsed,
            "existing live-approval owner replay differs from captured bytes",
        )
        if expected_document is not None:
            _require(
                validated == expected_document,
                "live approval document differs from issued capability",
            )
        return copy.deepcopy(validated), after


def _protected_submit_from_ingress(ingress: object) -> object:
    _require(
        type(ingress)
        is _INGRESS.SealedProtectedProductionIngressCapability,
        "effect-time replay accepts only exact production ingress",
    )
    ingress.assert_current()
    consumer = ingress.predecessor
    runtime = consumer.runtime_state
    invocation = (
        runtime.handoff.materialization.lifecycle
        .protected_invocation_bundle
    )
    protected = invocation.protected_submit_bundle
    protected.assert_owner_sealed()
    return protected


def _assert_scope_matches_predecessor(
    ingress: object,
    approval: dict[str, Any],
    artifact_sha256: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    ingress.assert_current()
    ingress_document = ingress.document()
    consumer_document = ingress.predecessor.document()
    intent = consumer_document["intent"]
    protected = _protected_submit_from_ingress(ingress)
    protected_document = protected.document()
    protected_approval = protected_document["approvals"][
        "live_submission_approval"
    ]
    protected_identity = protected_document["identity"]
    protected_execution = protected_document["execution"]
    protected_resources = protected_document["resources"]
    scope = approval["scope"]
    execution = scope["execution"]
    resources = execution["resource_binding"]
    _require(
        approval["schema"] in SUPPORTED_APPROVALS
        and approval["approval_id"] == protected_approval["approval_id"]
        and approval["approval_id"] == intent["live_approval_id"]
        and artifact_sha256 == protected_approval["artifact_sha256"]
        and artifact_sha256 == intent["live_approval_artifact_sha256"],
        "live approval identity differs from sealed predecessor",
    )
    _require(
        approval["approved_at"] == protected_approval["not_before"]
        and approval["expires_at"] == protected_approval["expires_at"],
        "live approval window differs from sealed predecessor",
    )
    _require(
        scope["operation"] == "submit"
        and scope["project"] == protected_identity["project"]
        and scope["input_sha256"] == protected_identity["input_sha256"]
        and execution["batch_id"] == protected_execution["batch_id"]
        and execution["review_sha256"]
        == protected_execution["review_sha256"]
        and execution["scientific_task_id"]
        == protected_identity["scientific_task_id"]
        and execution["attempt_id"] == protected_identity["attempt_id"]
        and hashlib.sha256(
            execution["idempotency_key"].encode("utf-8")
        ).hexdigest()
        == protected_identity["idempotency_key_sha256"],
        "live approval execution tuple differs from sealed predecessor",
    )
    expected_resources = {
        "policy_id": protected_resources["policy_id"],
        "policy_sha256": protected_resources["policy_sha256"],
        "gate_id": protected_resources["gate_id"],
        "gate_sha256": protected_resources["gate_sha256"],
        "resource_tier": protected_resources["resource_tier"],
        "cores": protected_resources["cores"],
        "memory_gb": protected_resources["memory_gb"],
        "walltime_seconds": protected_resources["walltime_seconds"],
    }
    _require(
        resources == expected_resources,
        "live approval resource tuple differs from sealed predecessor",
    )
    _require(
        ingress_document["identity"]
        == {
            "project": protected_identity["project"],
            "attempt_id": protected_identity["attempt_id"],
            "input_sha256": protected_identity["input_sha256"],
        },
        "production ingress identity differs from protected submit",
    )
    return protected_document, intent, scope


class _DirectServerSessionIngress:
    __slots__ = ("_binding_bytes", "_transaction")

    def __init__(self, transaction: _DIRECT.DirectServerSessionTransaction) -> None:
        _require(
            type(transaction) is _DIRECT.DirectServerSessionTransaction,
            "direct live source requires the exact server-session transaction",
        )
        self._transaction = transaction
        self._binding_bytes = _DIRECT.canonical_bytes(transaction.binding())

    def assert_current(self) -> None:
        _require(
            type(self._transaction) is _DIRECT.DirectServerSessionTransaction
            and _DIRECT.canonical_bytes(self._transaction.binding()) == self._binding_bytes,
            "direct server-session live source drifted",
        )

    def binding(self) -> dict[str, Any]:
        self.assert_current()
        return json.loads(self._binding_bytes)


def _assert_scope_matches_direct(
    ingress: _DirectServerSessionIngress,
    approval: dict[str, Any],
) -> dict[str, Any]:
    ingress.assert_current()
    binding = ingress.binding()
    scope = approval["scope"]
    execution = scope["execution"]
    resources = execution["resource_binding"]
    direct_resources = binding["resources"]
    _require(
        scope["operation"] == "submit"
        and scope["project"] == binding["workspace"]["project"]
        and scope["input_sha256"] == binding["input"]["sha256"]
        and execution["scientific_task_id"] == binding["scope"]["scientific_task_id"]
        and execution["attempt_id"] == binding["scope"]["attempt_id"]
        and execution["idempotency_key"] == binding["scope"]["idempotency_key"]
        and resources["resource_tier"] == direct_resources["tier"]
        and resources["cores"] == int(direct_resources["cores"])
        and resources["memory_gb"] == int(direct_resources["memory_gb"])
        and resources["walltime_seconds"] == int(direct_resources["walltime_seconds"]),
        "direct server-session live approval scope differs",
    )
    return scope


def _build_direct_document(
    ingress: _DirectServerSessionIngress,
    approval: dict[str, Any],
    snapshot: _FileSnapshot,
    issued_at: datetime,
) -> dict[str, Any]:
    scope = _assert_scope_matches_direct(ingress, approval)
    execution = scope["execution"]
    resource = execution["resource_binding"]
    binding = ingress.binding()
    predecessor = {
        "schema": _DIRECT_PREDECESSOR_SCHEMA,
        "contract_id": "direct-server-session-live-" + binding["binding_payload_sha256"],
        "contract_payload_sha256": binding["binding_payload_sha256"],
        "owner_consumer_contract_id": "direct-session-owner-" + binding["authorization"]["authorization_payload_sha256"],
        "protected_bundle_id": "direct-session-input-" + binding["input"]["sha256"],
        "protected_bundle_payload_sha256": binding["input"]["sha256"],
        "protected_consumption_sha256": binding["authorization"]["authorization_scope_sha256"],
    }
    artifact = {
        "schema": approval["schema"],
        "approval_id": approval["approval_id"],
        "artifact_sha256": snapshot.sha256,
        "size_bytes": len(snapshot.raw),
        "resolved_path_sha256": digest(str(snapshot.path)),
        "file_identity_sha256": snapshot.identity_sha256,
        "scope_sha256": digest(scope),
        "approver_identity": approval["approver_identity"],
        "approved_at": approval["approved_at"],
        "expires_at": approval["expires_at"],
        "revocation": copy.deepcopy(approval["revocation"]),
    }
    document = {
        "schema": SCHEMA,
        "owner": OWNER,
        "capability_id": "pre-qsub-live-approval-replay-" + _ZERO_SHA,
        "predecessor": predecessor,
        "approval_artifact": artifact,
        "execution_scope": {
            "operation": "submit",
            "batch_id": execution["batch_id"],
            "review_sha256": execution["review_sha256"],
            "scientific_task_id": execution["scientific_task_id"],
            "attempt_id": execution["attempt_id"],
            "idempotency_key_sha256": hashlib.sha256(
                execution["idempotency_key"].encode("utf-8")
            ).hexdigest(),
            "project": scope["project"],
            "input_sha256": scope["input_sha256"],
            "resources": copy.deepcopy(resource),
        },
        "replay": {
            "phase": PHASE,
            "issued_at": _format_utc(issued_at),
            "single_use": True,
            "replay_count": 0,
            "owner_private_registry": True,
            "owner_private_lock": True,
            "trusted_wall_time": True,
            "trusted_monotonic_lower_bound": True,
            "clock_rollback_rejected": True,
            "capability_authorizes_effect": False,
        },
        "source_bindings": {
            "owner_source_sha256": _OWNER_SOURCE.sha256,
            "production_ingress_source_sha256": _INGRESS_SOURCE.sha256,
            "live_approval_owner_source_sha256": _LIVE_OWNER_SOURCE.sha256,
        },
        "effect_boundary": {
            "production_submit_wired": False,
            "factory_calls": 0,
            "runner_calls": 0,
            "qsub_calls": 0,
            "transport_calls": 0,
            "external_effects_performed": False,
            "non_authorizing": True,
        },
        "contract_payload_sha256": "",
    }
    document["contract_payload_sha256"] = digest(
        {**document, "capability_id": "", "contract_payload_sha256": ""}
    )
    document["capability_id"] = "pre-qsub-live-approval-replay-" + digest(
        {
            "schema": "auto-g16-pre-qsub-replay-capability-id/1",
            "predecessor_contract_id": predecessor["contract_id"],
            "approval_artifact_sha256": artifact["artifact_sha256"],
            "file_identity_sha256": artifact["file_identity_sha256"],
            "issued_at": document["replay"]["issued_at"],
            "contract_payload_sha256": document["contract_payload_sha256"],
        }
    )
    return validate_live_approval_effect_time_replay(document)


def _build_document(
    ingress: object,
    approval: dict[str, Any],
    snapshot: _FileSnapshot,
    issued_at: datetime,
) -> dict[str, Any]:
    protected, intent, scope = _assert_scope_matches_predecessor(
        ingress,
        approval,
        snapshot.sha256,
    )
    execution = scope["execution"]
    resource = execution["resource_binding"]
    ingress_document = ingress.document()
    artifact = {
        "schema": approval["schema"],
        "approval_id": approval["approval_id"],
        "artifact_sha256": snapshot.sha256,
        "size_bytes": len(snapshot.raw),
        "resolved_path_sha256": digest(str(snapshot.path)),
        "file_identity_sha256": snapshot.identity_sha256,
        "scope_sha256": digest(scope),
        "approver_identity": approval["approver_identity"],
        "approved_at": approval["approved_at"],
        "expires_at": approval["expires_at"],
        "revocation": copy.deepcopy(approval["revocation"]),
    }
    predecessor = {
        "schema": ingress_document["schema"],
        "contract_id": ingress_document["contract_id"],
        "contract_payload_sha256": ingress_document[
            "contract_payload_sha256"
        ],
        "owner_consumer_contract_id": ingress_document["predecessor"][
            "contract_id"
        ],
        "protected_bundle_id": intent["protected_authority"][
            "bundle_id"
        ],
        "protected_bundle_payload_sha256": intent[
            "protected_authority"
        ]["bundle_payload_sha256"],
        "protected_consumption_sha256": intent["protected_authority"][
            "consumption_sha256"
        ],
    }
    execution_scope = {
        "operation": "submit",
        "batch_id": execution["batch_id"],
        "review_sha256": execution["review_sha256"],
        "scientific_task_id": execution["scientific_task_id"],
        "attempt_id": execution["attempt_id"],
        "idempotency_key_sha256": hashlib.sha256(
            execution["idempotency_key"].encode("utf-8")
        ).hexdigest(),
        "project": scope["project"],
        "input_sha256": scope["input_sha256"],
        "resources": copy.deepcopy(resource),
    }
    document: dict[str, Any] = {
        "schema": SCHEMA,
        "owner": OWNER,
        "capability_id": "pre-qsub-live-approval-replay-" + _ZERO_SHA,
        "predecessor": predecessor,
        "approval_artifact": artifact,
        "execution_scope": execution_scope,
        "replay": {
            "phase": PHASE,
            "issued_at": _format_utc(issued_at),
            "single_use": True,
            "replay_count": 0,
            "owner_private_registry": True,
            "owner_private_lock": True,
            "trusted_wall_time": True,
            "trusted_monotonic_lower_bound": True,
            "clock_rollback_rejected": True,
            "capability_authorizes_effect": False,
        },
        "source_bindings": {
            "owner_source_sha256": _OWNER_SOURCE.sha256,
            "production_ingress_source_sha256": _INGRESS_SOURCE.sha256,
            "live_approval_owner_source_sha256": _LIVE_OWNER_SOURCE.sha256,
        },
        "effect_boundary": {
            "production_submit_wired": False,
            "factory_calls": 0,
            "runner_calls": 0,
            "qsub_calls": 0,
            "transport_calls": 0,
            "external_effects_performed": False,
            "non_authorizing": True,
        },
        "contract_payload_sha256": "",
    }
    document["contract_payload_sha256"] = digest(
        {
            **document,
            "capability_id": "",
            "contract_payload_sha256": "",
        }
    )
    document["capability_id"] = (
        "pre-qsub-live-approval-replay-"
        + digest(
            {
                "schema": "auto-g16-pre-qsub-replay-capability-id/1",
                "predecessor_contract_id": predecessor["contract_id"],
                "approval_artifact_sha256": artifact["artifact_sha256"],
                "file_identity_sha256": artifact[
                    "file_identity_sha256"
                ],
                "issued_at": document["replay"]["issued_at"],
                "contract_payload_sha256": document[
                    "contract_payload_sha256"
                ],
            }
        )
    )
    _require(
        protected["approvals"]["live_submission_approval"][
            "artifact_sha256"
        ]
        == artifact["artifact_sha256"],
        "protected live approval artifact differs",
    )
    return validate_live_approval_effect_time_replay(document)


def validate_live_approval_effect_time_replay(
    value: Any,
) -> dict[str, Any]:
    document = _rebuild_json(value)
    _require(
        len(canonical_bytes(document)) <= _MAX_APPROVAL_BYTES,
        "effect-time replay contract exceeds size bound",
    )
    document = _exact(
        document,
        {
            "schema",
            "owner",
            "capability_id",
            "predecessor",
            "approval_artifact",
            "execution_scope",
            "replay",
            "source_bindings",
            "effect_boundary",
            "contract_payload_sha256",
        },
        "effect-time replay contract",
    )
    _require(
        document["schema"] == SCHEMA and document["owner"] == OWNER,
        "effect-time replay schema or owner differs",
    )
    _require(
        type(document["capability_id"]) is str
        and CAPABILITY_ID_RE.fullmatch(document["capability_id"])
        is not None,
        "effect-time replay capability id differs",
    )
    predecessor = _exact(
        document["predecessor"],
        {
            "schema",
            "contract_id",
            "contract_payload_sha256",
            "owner_consumer_contract_id",
            "protected_bundle_id",
            "protected_bundle_payload_sha256",
            "protected_consumption_sha256",
        },
        "effect-time replay predecessor",
    )
    if predecessor["schema"] == _DIRECT_PREDECESSOR_SCHEMA:
        _require(
            _text(predecessor["contract_id"], "predecessor contract id").startswith(
                "direct-server-session-live-"
            )
            and _text(
                predecessor["owner_consumer_contract_id"],
                "owner-consumer contract id",
            ).startswith("direct-session-owner-")
            and _text(
                predecessor["protected_bundle_id"],
                "protected bundle id",
            ).startswith("direct-session-input-"),
            "direct effect-time replay predecessor identity differs",
        )
    else:
        _require(
            predecessor["schema"]
            == "auto-g16-protected-production-ingress-contract/1"
            and _text(predecessor["contract_id"], "predecessor contract id")
            .startswith("protected-production-ingress-")
            and _text(
                predecessor["owner_consumer_contract_id"],
                "owner-consumer contract id",
            ).startswith("protected-owner-consumer-")
            and _text(
                predecessor["protected_bundle_id"],
                "protected bundle id",
            ).startswith("protected-submit-"),
            "effect-time replay predecessor identity differs",
        )
    for field in (
        "contract_payload_sha256",
        "protected_bundle_payload_sha256",
        "protected_consumption_sha256",
    ):
        _sha(predecessor[field], f"predecessor {field}")
    artifact = _exact(
        document["approval_artifact"],
        {
            "schema",
            "approval_id",
            "artifact_sha256",
            "size_bytes",
            "resolved_path_sha256",
            "file_identity_sha256",
            "scope_sha256",
            "approver_identity",
            "approved_at",
            "expires_at",
            "revocation",
        },
        "effect-time approval artifact",
    )
    _require(
        artifact["schema"] in SUPPORTED_APPROVALS,
        "effect-time approval generation differs",
    )
    _text(artifact["approval_id"], "approval id")
    _text(artifact["approver_identity"], "approver identity")
    _positive_integer(artifact["size_bytes"], "approval size")
    for field in (
        "artifact_sha256",
        "resolved_path_sha256",
        "file_identity_sha256",
        "scope_sha256",
    ):
        _sha(artifact[field], f"approval {field}")
    approved = _utc(artifact["approved_at"], "approval approved_at")
    expires = _utc(artifact["expires_at"], "approval expires_at")
    _require(approved < expires, "approval window is empty")
    _require(
        artifact["revocation"]
        == {"revoked": False, "revoked_at": None, "reason": None},
        "approval revocation state differs",
    )
    execution = _exact(
        document["execution_scope"],
        {
            "operation",
            "batch_id",
            "review_sha256",
            "scientific_task_id",
            "attempt_id",
            "idempotency_key_sha256",
            "project",
            "input_sha256",
            "resources",
        },
        "effect-time execution scope",
    )
    _require(
        execution["operation"] == "submit"
        and _text(execution["batch_id"], "batch id")
        and _text(execution["scientific_task_id"], "scientific task id")
        .startswith("scientific-task-")
        and _text(execution["attempt_id"], "attempt id").startswith(
            "qsub-attempt-"
        )
        and _text(execution["project"], "project"),
        "effect-time execution identity differs",
    )
    for field in (
        "review_sha256",
        "idempotency_key_sha256",
        "input_sha256",
    ):
        _sha(execution[field], f"execution {field}")
    resources = _exact(
        execution["resources"],
        {
            "policy_id",
            "policy_sha256",
            "gate_id",
            "gate_sha256",
            "resource_tier",
            "cores",
            "memory_gb",
            "walltime_seconds",
        },
        "effect-time resources",
    )
    for field in ("policy_id", "gate_id", "resource_tier"):
        _text(resources[field], f"resources {field}")
    for field in ("policy_sha256", "gate_sha256"):
        _sha(resources[field], f"resources {field}")
    for field in ("cores", "memory_gb", "walltime_seconds"):
        _positive_integer(resources[field], f"resources {field}")
    replay = _exact(
        document["replay"],
        {
            "phase",
            "issued_at",
            "single_use",
            "replay_count",
            "owner_private_registry",
            "owner_private_lock",
            "trusted_wall_time",
            "trusted_monotonic_lower_bound",
            "clock_rollback_rejected",
            "capability_authorizes_effect",
        },
        "effect-time replay policy",
    )
    issued_at = replay["issued_at"]
    _utc(issued_at, "replay issued_at")
    _require(replay["phase"] == PHASE, "effect-time replay phase differs")
    replay_boolean_fields = {
        "single_use": True,
        "owner_private_registry": True,
        "owner_private_lock": True,
        "trusted_wall_time": True,
        "trusted_monotonic_lower_bound": True,
        "clock_rollback_rejected": True,
        "capability_authorizes_effect": False,
    }
    rebuilt_replay: dict[str, Any] = {
        "phase": PHASE,
        "issued_at": issued_at,
    }
    for field, expected in replay_boolean_fields.items():
        rebuilt_replay[field] = _fixed_boolean(
            replay[field],
            expected,
            f"effect-time replay {field}",
        )
    rebuilt_replay["replay_count"] = _fixed_integer(
        replay["replay_count"],
        0,
        "effect-time replay replay_count",
    )
    document["replay"] = rebuilt_replay
    replay = rebuilt_replay
    sources = _exact(
        document["source_bindings"],
        {
            "owner_source_sha256",
            "production_ingress_source_sha256",
            "live_approval_owner_source_sha256",
        },
        "effect-time source bindings",
    )
    for field in sources:
        _sha(sources[field], f"source binding {field}")
    effect_boundary = _exact(
        document["effect_boundary"],
        {
            "production_submit_wired",
            "factory_calls",
            "runner_calls",
            "qsub_calls",
            "transport_calls",
            "external_effects_performed",
            "non_authorizing",
        },
        "effect-time effect boundary",
    )
    rebuilt_effect_boundary = {
        "production_submit_wired": _fixed_boolean(
            effect_boundary["production_submit_wired"],
            False,
            "effect-time effect boundary production_submit_wired",
        ),
        "factory_calls": _fixed_integer(
            effect_boundary["factory_calls"],
            0,
            "effect-time effect boundary factory_calls",
        ),
        "runner_calls": _fixed_integer(
            effect_boundary["runner_calls"],
            0,
            "effect-time effect boundary runner_calls",
        ),
        "qsub_calls": _fixed_integer(
            effect_boundary["qsub_calls"],
            0,
            "effect-time effect boundary qsub_calls",
        ),
        "transport_calls": _fixed_integer(
            effect_boundary["transport_calls"],
            0,
            "effect-time effect boundary transport_calls",
        ),
        "external_effects_performed": _fixed_boolean(
            effect_boundary["external_effects_performed"],
            False,
            "effect-time effect boundary external_effects_performed",
        ),
        "non_authorizing": _fixed_boolean(
            effect_boundary["non_authorizing"],
            True,
            "effect-time effect boundary non_authorizing",
        ),
    }
    document["effect_boundary"] = rebuilt_effect_boundary
    payload = _sha(
        document["contract_payload_sha256"],
        "effect-time replay payload",
    )
    expected_payload = digest(
        {
            **document,
            "capability_id": "",
            "contract_payload_sha256": "",
        }
    )
    _require(payload == expected_payload, "effect-time replay payload differs")
    expected_id = "pre-qsub-live-approval-replay-" + digest(
        {
            "schema": "auto-g16-pre-qsub-replay-capability-id/1",
            "predecessor_contract_id": predecessor["contract_id"],
            "approval_artifact_sha256": artifact["artifact_sha256"],
            "file_identity_sha256": artifact["file_identity_sha256"],
            "issued_at": replay["issued_at"],
            "contract_payload_sha256": payload,
        }
    )
    _require(
        document["capability_id"] == expected_id,
        "effect-time replay capability id is not closed",
    )
    return copy.deepcopy(document)


@dataclass(slots=True)
class _ReplayState:
    ingress: object
    approval_path: Path
    approval_snapshot: _FileSnapshot
    approval_document: dict[str, Any]
    issued_wall: datetime
    issued_monotonic_ns: int
    wall_clock: Callable[[], datetime]
    monotonic_clock: Callable[[], int]
    document_bytes: bytes
    status: str = "issued"


_REGISTRY_LOCK = threading.RLock()
_CAPABILITY_REGISTRY: dict[object, _ReplayState] = {}
_RESULT_REGISTRY: dict[object, bytes] = {}
_ISSUANCE_REGISTRY: dict[int, tuple[object, str, str]] = {}


def _snapshot_current_capability_locked(
    capability: "PreQsubLiveApprovalReplayCapability",
    unavailable_message: str,
) -> tuple[_ReplayState, dict[str, Any]]:
    state = _CAPABILITY_REGISTRY.get(capability)
    _require(
        type(capability) is PreQsubLiveApprovalReplayCapability
        and capability._seal is _CAPABILITY_TOKEN
        and state is not None
        and state.status == "issued",
        unavailable_message,
    )
    if state is None:
        raise LiveApprovalEffectTimeReplayError(unavailable_message)
    document = validate_live_approval_effect_time_replay(
        json.loads(state.document_bytes)
    )
    _require(
        type(capability.capability_id) is str
        and document["capability_id"] == capability.capability_id,
        "replay capability projection differs",
    )
    return state, document


class PreQsubLiveApprovalReplayCapability:
    """One in-process replay claim; it never authorizes or invokes an effect."""

    __slots__ = ("capability_id", "_seal")

    def __new__(
        cls,
        *args: Any,
        **kwargs: Any,
    ) -> "PreQsubLiveApprovalReplayCapability":
        raise TypeError("pre-qsub replay capabilities are owner-issued only")

    @classmethod
    def _from_owner(
        cls,
        document: dict[str, Any],
        *,
        token: object,
    ) -> "PreQsubLiveApprovalReplayCapability":
        _require(token is _CAPABILITY_TOKEN, "capability seal differs")
        value = object.__new__(cls)
        object.__setattr__(value, "capability_id", document["capability_id"])
        object.__setattr__(value, "_seal", _CAPABILITY_TOKEN)
        return value

    def document(self) -> dict[str, Any]:
        with _REGISTRY_LOCK:
            state = _CAPABILITY_REGISTRY.get(self)
            _require(state is not None, "replay capability is not registered")
            return json.loads(state.document_bytes)

    def assert_current(self) -> "PreQsubLiveApprovalReplayCapability":
        _assert_bindings_current()
        with _REGISTRY_LOCK:
            state, _ = _snapshot_current_capability_locked(
                self,
                "replay capability is not current",
            )
            state.ingress.assert_current()
        return self

    def replay_once(self) -> "CompletedPreQsubLiveApprovalReplay":
        return _consume_replay_capability(self)

    def __copy__(self) -> "PreQsubLiveApprovalReplayCapability":
        raise TypeError("pre-qsub replay capabilities are not clonable")

    def __deepcopy__(
        self,
        memo: dict[int, Any],
    ) -> "PreQsubLiveApprovalReplayCapability":
        del memo
        raise TypeError("pre-qsub replay capabilities are not clonable")

    def __reduce__(self) -> object:
        raise TypeError("pre-qsub replay capabilities are not serializable")

    def __reduce_ex__(self, protocol: int) -> object:
        del protocol
        raise TypeError("pre-qsub replay capabilities are not serializable")


class CompletedPreQsubLiveApprovalReplay:
    """Owner-sealed evidence of one current replay; still non-authorizing."""

    __slots__ = ("capability_id", "replayed_at", "_seal")

    def __new__(
        cls,
        *args: Any,
        **kwargs: Any,
    ) -> "CompletedPreQsubLiveApprovalReplay":
        raise TypeError("completed replay results are owner-issued only")

    @classmethod
    def _from_owner(
        cls,
        document: dict[str, Any],
        *,
        token: object,
    ) -> "CompletedPreQsubLiveApprovalReplay":
        _require(token is _RESULT_TOKEN, "replay result seal differs")
        value = object.__new__(cls)
        object.__setattr__(value, "capability_id", document["capability_id"])
        object.__setattr__(value, "replayed_at", document["replayed_at"])
        object.__setattr__(value, "_seal", _RESULT_TOKEN)
        _RESULT_REGISTRY[value] = canonical_bytes(document)
        return value

    def document(self) -> dict[str, Any]:
        with _REGISTRY_LOCK:
            raw = _RESULT_REGISTRY.get(self)
            _require(raw is not None, "replay result is not registered")
            return json.loads(raw)

    def assert_owner_sealed(self) -> None:
        _assert_bindings_current()
        with _REGISTRY_LOCK:
            document = self.document()
            _require(
                type(self) is CompletedPreQsubLiveApprovalReplay
                and self._seal is _RESULT_TOKEN
                and document["capability_id"] == self.capability_id
                and document["replayed_at"] == self.replayed_at
                and document["status"] == "approval_replayed_current"
                and document["single_use_consumed"] is True
                and document["non_authorizing"] is True
                and document["factory_calls"] == 0
                and document["runner_calls"] == 0
                and document["qsub_calls"] == 0
                and document["transport_calls"] == 0,
                "replay result projection differs",
            )

    def __copy__(self) -> "CompletedPreQsubLiveApprovalReplay":
        raise TypeError("completed replay results are not clonable")

    def __deepcopy__(
        self,
        memo: dict[int, Any],
    ) -> "CompletedPreQsubLiveApprovalReplay":
        del memo
        raise TypeError("completed replay results are not clonable")

    def __reduce__(self) -> object:
        raise TypeError("completed replay results are not serializable")

    def __reduce_ex__(self, protocol: int) -> object:
        del protocol
        raise TypeError("completed replay results are not serializable")


def _system_wall_clock() -> datetime:
    return datetime.now(timezone.utc)


def _system_monotonic_ns() -> int:
    return time.monotonic_ns()


def _read_clock(
    wall_clock: Callable[[], datetime],
    monotonic_clock: Callable[[], int],
) -> tuple[datetime, int]:
    before = monotonic_clock()
    wall = _trusted_wall(wall_clock())
    after = monotonic_clock()
    _require(
        type(before) is int
        and type(after) is int
        and before >= 0
        and after >= before,
        "owner monotonic clock moved backward",
    )
    return wall, after


class LiveApprovalEffectTimeReplayOwner:
    """Single-issue owner for one exact pre-qsub replay capability."""

    def __init__(
        self,
        *,
        wall_clock: Callable[[], datetime],
        monotonic_clock: Callable[[], int],
        token: object,
    ) -> None:
        _assert_bindings_current()
        _require(
            token in {_OWNER_TOKEN, _TEST_OWNER_TOKEN},
            "effect-time replay owner factory differs",
        )
        self._wall_clock = wall_clock
        self._monotonic_clock = monotonic_clock
        self._lock = threading.Lock()
        self._used = False

    @classmethod
    def production(cls) -> "LiveApprovalEffectTimeReplayOwner":
        return cls(
            wall_clock=_system_wall_clock,
            monotonic_clock=_system_monotonic_ns,
            token=_OWNER_TOKEN,
        )

    @classmethod
    def _for_testing(
        cls,
        *,
        wall_clock: Callable[[], datetime],
        monotonic_clock: Callable[[], int],
        _test_token: object,
    ) -> "LiveApprovalEffectTimeReplayOwner":
        _require(
            _test_token is _TEST_OWNER_TOKEN,
            "private replay test owner token differs",
        )
        return cls(
            wall_clock=wall_clock,
            monotonic_clock=monotonic_clock,
            token=_TEST_OWNER_TOKEN,
        )

    def issue_once(
        self,
        ingress: object,
        approval_path: Path,
    ) -> PreQsubLiveApprovalReplayCapability:
        with self._lock:
            _require(not self._used, "effect-time replay owner is single-use")
            self._used = True
            _assert_bindings_current()
            _require(
                type(ingress)
                is _INGRESS.SealedProtectedProductionIngressCapability,
                "effect-time replay requires exact production ingress",
            )
            ingress.assert_current()
            issued_wall, issued_monotonic_ns = _read_clock(
                self._wall_clock,
                self._monotonic_clock,
            )
            snapshot = _capture_file(
                Path(approval_path),
                "live approval record",
            )
            issuance_key = id(ingress)
            with _REGISTRY_LOCK:
                _require(
                    issuance_key not in _ISSUANCE_REGISTRY,
                    "approval replay capability was already issued",
                )
                _ISSUANCE_REGISTRY[issuance_key] = (
                    ingress,
                    snapshot.sha256,
                    "claiming",
                )
            try:
                parsed = _parse_json_bytes(
                    snapshot.raw,
                    "live approval record",
                )
                validated, after = _replay_existing_owner(
                    snapshot.path,
                    snapshot,
                    None,
                    issued_wall,
                )
                _require(
                    after == snapshot,
                    "live approval changed during capability issuance",
                )
                document = _build_document(
                    ingress,
                    validated,
                    snapshot,
                    issued_wall,
                )
                capability = (
                    PreQsubLiveApprovalReplayCapability._from_owner(
                        document,
                        token=_CAPABILITY_TOKEN,
                    )
                )
                _require(
                    validated == parsed,
                    "captured approval differs from owner replay",
                )
                with _REGISTRY_LOCK:
                    _require(
                        _ISSUANCE_REGISTRY.get(issuance_key)
                        == (ingress, snapshot.sha256, "claiming")
                        and capability not in _CAPABILITY_REGISTRY,
                        "replay capability issuance registry differs",
                    )
                    _CAPABILITY_REGISTRY[capability] = _ReplayState(
                        ingress=ingress,
                        approval_path=snapshot.path,
                        approval_snapshot=snapshot,
                        approval_document=validated,
                        issued_wall=issued_wall,
                        issued_monotonic_ns=issued_monotonic_ns,
                        wall_clock=self._wall_clock,
                        monotonic_clock=self._monotonic_clock,
                        document_bytes=canonical_bytes(document),
                    )
                    _ISSUANCE_REGISTRY[issuance_key] = (
                        ingress,
                        snapshot.sha256,
                        "issued",
                    )
                capability.assert_current()
                return capability
            except BaseException:
                with _REGISTRY_LOCK:
                    if _ISSUANCE_REGISTRY.get(issuance_key) == (
                        ingress,
                        snapshot.sha256,
                        "claiming",
                    ):
                        _ISSUANCE_REGISTRY[issuance_key] = (
                            ingress,
                            snapshot.sha256,
                            "failed",
                        )
                raise

    def issue_direct_server_session_once(
        self,
        transaction: _DIRECT.DirectServerSessionTransaction,
        approval_path: Path,
    ) -> PreQsubLiveApprovalReplayCapability:
        """Issue through the same live owner for one exact direct transaction."""
        with self._lock:
            _require(not self._used, "effect-time replay owner is single-use")
            self._used = True
            _assert_bindings_current()
            _require(
                type(transaction) is _DIRECT.DirectServerSessionTransaction,
                "direct replay requires the exact server-session transaction",
            )
            ingress = _DirectServerSessionIngress(transaction)
            ingress.assert_current()
            issued_wall, issued_monotonic_ns = _read_clock(
                self._wall_clock,
                self._monotonic_clock,
            )
            snapshot = _capture_file(Path(approval_path), "direct live approval record")
            issuance_key = id(ingress)
            with _REGISTRY_LOCK:
                _require(
                    issuance_key not in _ISSUANCE_REGISTRY,
                    "direct approval replay capability was already issued",
                )
                _ISSUANCE_REGISTRY[issuance_key] = (
                    ingress,
                    snapshot.sha256,
                    "claiming",
                )
            try:
                parsed = _parse_json_bytes(snapshot.raw, "direct live approval record")
                validated, after = _replay_existing_owner(
                    snapshot.path,
                    snapshot,
                    None,
                    issued_wall,
                )
                _require(
                    after == snapshot and validated == parsed,
                    "direct live approval changed during capability issuance",
                )
                _assert_scope_matches_direct(ingress, validated)
                document = _build_direct_document(
                    ingress,
                    validated,
                    snapshot,
                    issued_wall,
                )
                capability = PreQsubLiveApprovalReplayCapability._from_owner(
                    document,
                    token=_CAPABILITY_TOKEN,
                )
                with _REGISTRY_LOCK:
                    _require(
                        _ISSUANCE_REGISTRY.get(issuance_key)
                        == (ingress, snapshot.sha256, "claiming")
                        and capability not in _CAPABILITY_REGISTRY,
                        "direct replay capability issuance registry differs",
                    )
                    _CAPABILITY_REGISTRY[capability] = _ReplayState(
                        ingress=ingress,
                        approval_path=snapshot.path,
                        approval_snapshot=snapshot,
                        approval_document=validated,
                        issued_wall=issued_wall,
                        issued_monotonic_ns=issued_monotonic_ns,
                        wall_clock=self._wall_clock,
                        monotonic_clock=self._monotonic_clock,
                        document_bytes=canonical_bytes(document),
                    )
                    _ISSUANCE_REGISTRY[issuance_key] = (
                        ingress,
                        snapshot.sha256,
                        "issued",
                    )
                capability.assert_current()
                return capability
            except BaseException:
                with _REGISTRY_LOCK:
                    if _ISSUANCE_REGISTRY.get(issuance_key) == (
                        ingress,
                        snapshot.sha256,
                        "claiming",
                    ):
                        _ISSUANCE_REGISTRY[issuance_key] = (
                            ingress,
                            snapshot.sha256,
                            "failed",
                        )
                raise


def _consume_replay_capability(
    capability: PreQsubLiveApprovalReplayCapability,
) -> CompletedPreQsubLiveApprovalReplay:
    _assert_bindings_current()
    with _REGISTRY_LOCK:
        state, document = _snapshot_current_capability_locked(
            capability,
            "pre-qsub replay capability is unavailable or already used",
        )
        state.status = "claiming"
        try:
            current_wall, current_monotonic_ns = _read_clock(
                state.wall_clock,
                state.monotonic_clock,
            )
            _require(
                current_monotonic_ns >= state.issued_monotonic_ns,
                "owner monotonic clock rolled back",
            )
            _require(
                current_wall >= state.issued_wall,
                "owner wall clock rolled back",
            )
            elapsed_ns = current_monotonic_ns - state.issued_monotonic_ns
            monotonic_lower_bound = state.issued_wall + timedelta(
                microseconds=elapsed_ns // 1000
            )
            trusted_now = max(current_wall, monotonic_lower_bound)
            _assert_bindings_current()
            state.ingress.assert_current()
            replayed, snapshot = _replay_existing_owner(
                state.approval_path,
                state.approval_snapshot,
                state.approval_document,
                trusted_now,
            )
            if type(state.ingress) is _DirectServerSessionIngress:
                _assert_scope_matches_direct(state.ingress, replayed)
            else:
                _assert_scope_matches_predecessor(
                    state.ingress,
                    replayed,
                    snapshot.sha256,
                )
            result_document = {
                "schema": "auto-g16-live-approval-effect-time-replay-result/1",
                "capability_id": document["capability_id"],
                "approval_artifact_sha256": snapshot.sha256,
                "approval_file_identity_sha256": snapshot.identity_sha256,
                "phase": PHASE,
                "replayed_at": _format_utc(trusted_now),
                "monotonic_elapsed_ns": str(elapsed_ns),
                "status": "approval_replayed_current",
                "single_use_consumed": True,
                "non_authorizing": True,
                "factory_calls": 0,
                "runner_calls": 0,
                "qsub_calls": 0,
                "transport_calls": 0,
                "result_payload_sha256": "",
            }
            result_document["result_payload_sha256"] = digest(
                {
                    **result_document,
                    "result_payload_sha256": "",
                }
            )
            result = CompletedPreQsubLiveApprovalReplay._from_owner(
                result_document,
                token=_RESULT_TOKEN,
            )
            state.status = "consumed"
            result.assert_owner_sealed()
            return result
        except BaseException:
            state.status = "failed"
            raise
