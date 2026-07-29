#!/usr/bin/env python3
"""Additive package-4 resource effect-time replay capability owner."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import secrets
import stat
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import resource_efficiency as RESOURCE


ResourceError = RESOURCE.ResourceError
execution_batch = RESOURCE.execution_batch
POLICY_SCHEMA = RESOURCE.POLICY_SCHEMA
GATE_SCHEMA = RESOURCE.GATE_SCHEMA
LEDGER_SCHEMA = RESOURCE.LEDGER_SCHEMA
SCHEDULER_SNAPSHOT_SCHEMA = RESOURCE.SCHEDULER_SNAPSHOT_SCHEMA
RESERVATION_CAPABILITY_SCHEMA = RESOURCE.RESERVATION_CAPABILITY_SCHEMA
RESERVATION_CAPABILITY_OWNER = RESOURCE.RESERVATION_CAPABILITY_OWNER
ExecutionBatchReservationCapability = (
    RESOURCE.ExecutionBatchReservationCapability
)
PROJECT_RE = RESOURCE.PROJECT_RE
RESOURCE_EFFECT_REPLAY_CAPABILITY_SCHEMA = (
    "auto-g16-resource-effect-time-replay-capability/1"
)
RESOURCE_EFFECT_REPLAY_CAPABILITY_OWNER = "auto-g16-package-4"
RESOURCE_EFFECT_REPLAY_MAX_AGE_SECONDS = 30
RESOURCE_EFFECT_REPLAY_CLOCK_SKEW_SECONDS = 5.0

_exact = RESOURCE._exact
_rebuild_fixed_builtin_mapping = RESOURCE._rebuild_fixed_builtin_mapping
_text = RESOURCE._text
_sha = RESOURCE._sha
_number = RESOURCE._number
_time = RESOURCE._time
_payload = RESOURCE._payload
_not_copyable = RESOURCE._not_copyable
validate_resource_tuple = RESOURCE.validate_resource_tuple
validate_reservation_capability_document = (
    RESOURCE.validate_reservation_capability_document
)
validate_ledger = RESOURCE.validate_ledger
validate_policy = RESOURCE.validate_policy
_validate_gate_binding = RESOURCE._validate_gate_binding
validate_scheduler_snapshot = RESOURCE.validate_scheduler_snapshot

_RESOURCE_EFFECT_REPLAY_ISSUE_TOKEN = object()
_RESOURCE_EFFECT_REPLAY_REGISTRY_LOCK = threading.Lock()
_RESOURCE_EFFECT_REPLAY_REGISTRY: dict[Any, Any] = {}
_SELF_MODULE_CACHE_ENTRY = sys.modules.get(__name__)
_RESOURCE_OWNER_MODULE_CACHE_ENTRY = sys.modules.get(RESOURCE.__name__)


def _source_path_binding(
    source_path: Path,
    label: str,
) -> tuple[Path, tuple[int, int, int, int], str]:
    if source_path.is_symlink() or not source_path.is_file():
        raise ResourceError(f"{label} source must be a regular non-symlink file")
    metadata = source_path.stat()
    identity = (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
    )
    return (
        source_path.resolve(),
        identity,
        hashlib.sha256(source_path.read_bytes()).hexdigest(),
    )


def _source_binding(
    module: Any,
    label: str,
) -> tuple[Path, tuple[int, int, int, int], str]:
    raw_path = getattr(module, "__file__", None)
    if type(raw_path) is not str:
        raise ResourceError(f"{label} source path is unavailable")
    return _source_path_binding(Path(raw_path), label)


_SELF_SOURCE_BINDING = _source_path_binding(
    Path(__file__),
    "resource effect-time replay owner",
)
_RESOURCE_OWNER_SOURCE_BINDING = _source_binding(
    RESOURCE,
    "package-4 resource owner",
)
_RESOURCE_OWNER_CAPABILITY_TYPE = RESOURCE.ExecutionBatchReservationCapability


def _assert_resource_owner_module_cache() -> None:
    if (
        _SELF_MODULE_CACHE_ENTRY is None
        or sys.modules.get(__name__) is not _SELF_MODULE_CACHE_ENTRY
    ):
        raise ResourceError(
            "resource effect-time replay owner module cache identity changed"
        )
    if (
        _RESOURCE_OWNER_MODULE_CACHE_ENTRY is None
        or sys.modules.get(RESOURCE.__name__)
        is not _RESOURCE_OWNER_MODULE_CACHE_ENTRY
        or _RESOURCE_OWNER_MODULE_CACHE_ENTRY is not RESOURCE
        or RESOURCE.ExecutionBatchReservationCapability
        is not _RESOURCE_OWNER_CAPABILITY_TYPE
    ):
        raise ResourceError(
            "package-4 resource owner module cache identity changed"
        )
    if _source_binding(
        _SELF_MODULE_CACHE_ENTRY,
        "resource effect-time replay owner",
    ) != _SELF_SOURCE_BINDING:
        raise ResourceError(
            "resource effect-time replay owner source identity changed"
        )
    if _source_binding(
        RESOURCE,
        "package-4 resource owner",
    ) != _RESOURCE_OWNER_SOURCE_BINDING:
        raise ResourceError(
            "package-4 resource owner source identity changed"
        )

class _ResourceEffectReplayCapabilityState:
    __slots__ = (
        "lock",
        "status",
        "ledger_path",
        "policy_path",
        "gate_path",
        "scheduler_path",
        "reservation_projection",
        "reservation_scope",
        "expected_replay",
        "issued_wall",
        "issued_monotonic_ns",
        "registered_capability",
        "owner_document_bytes",
        "owner_document_snapshot",
    )

    def __init__(
        self,
        *,
        ledger_path: Path,
        policy_path: Path,
        gate_path: Path,
        scheduler_path: Path,
        reservation_projection: dict[str, Any],
        reservation_scope: dict[str, Any],
        expected_replay: dict[str, Any],
        issued_wall: datetime,
        issued_monotonic_ns: int,
    ) -> None:
        self.lock = threading.Lock()
        self.status = "unconsumed"
        self.ledger_path = ledger_path
        self.policy_path = policy_path
        self.gate_path = gate_path
        self.scheduler_path = scheduler_path
        self.reservation_projection = copy.deepcopy(reservation_projection)
        self.reservation_scope = copy.deepcopy(reservation_scope)
        self.expected_replay = copy.deepcopy(expected_replay)
        self.issued_wall = issued_wall
        self.issued_monotonic_ns = issued_monotonic_ns
        self.registered_capability = None
        self.owner_document_bytes = None
        self.owner_document_snapshot = None

class ClaimedResourceEffectTimeReplay:
    """Exact effect-time resource replay result with no execution surface."""

    __slots__ = ("__scope",)

    def __new__(
        cls, *_args: Any, **_kwargs: Any
    ) -> "ClaimedResourceEffectTimeReplay":
        raise TypeError("resource effect-time replay claims are owner-issued only")

    @classmethod
    def _from_owner(
        cls,
        scope: dict[str, Any],
        *,
        token: object,
    ) -> "ClaimedResourceEffectTimeReplay":
        if token is not _RESOURCE_EFFECT_REPLAY_ISSUE_TOKEN:
            raise TypeError(
                "resource effect-time replay claims are owner-issued only"
            )
        value = object.__new__(cls)
        object.__setattr__(
            value,
            "_ClaimedResourceEffectTimeReplay__scope",
            copy.deepcopy(scope),
        )
        return value

    def exact_scope(self) -> dict[str, Any]:
        return copy.deepcopy(self.__scope)

    def __copy__(self) -> "ClaimedResourceEffectTimeReplay":
        raise _not_copyable("resource effect-time replay claims")

    def __deepcopy__(
        self, _memo: dict[int, Any]
    ) -> "ClaimedResourceEffectTimeReplay":
        raise _not_copyable("resource effect-time replay claims")

    def __reduce__(self) -> Any:
        raise _not_copyable("resource effect-time replay claims")

    def __reduce_ex__(self, _protocol: int) -> Any:
        raise _not_copyable("resource effect-time replay claims")

class ResourceEffectTimeReplayCapability:
    """Fresh, registry-bound, single-use effect-time resource replay handle."""

    __slots__ = ("__document",)

    def __new__(
        cls, *_args: Any, **_kwargs: Any
    ) -> "ResourceEffectTimeReplayCapability":
        raise TypeError(
            "resource effect-time replay capabilities are owner-issued only"
        )

    @classmethod
    def _from_owner(
        cls,
        document: dict[str, Any],
        state: _ResourceEffectReplayCapabilityState,
        *,
        token: object,
    ) -> "ResourceEffectTimeReplayCapability":
        if token is not _RESOURCE_EFFECT_REPLAY_ISSUE_TOKEN:
            raise TypeError(
                "resource effect-time replay capabilities are owner-issued only"
            )
        validate_resource_effect_time_replay_capability_document(document)
        value = object.__new__(cls)
        object.__setattr__(
            value,
            "_ResourceEffectTimeReplayCapability__document",
            copy.deepcopy(document),
        )
        owner_document_snapshot = copy.deepcopy(document)
        owner_document_bytes = execution_batch.canonical_bytes(
            owner_document_snapshot
        )
        with _RESOURCE_EFFECT_REPLAY_REGISTRY_LOCK:
            if (
                state.registered_capability is not None
                or state.owner_document_bytes is not None
                or state.owner_document_snapshot is not None
            ):
                raise ResourceError(
                    "resource effect-time replay registry state is already bound"
                )
            state.registered_capability = value
            state.owner_document_bytes = owner_document_bytes
            state.owner_document_snapshot = owner_document_snapshot
            _RESOURCE_EFFECT_REPLAY_REGISTRY[value] = state
        return value

    def portable_projection(self) -> dict[str, Any]:
        return copy.deepcopy(self.__document)

    def consume_once(self) -> ClaimedResourceEffectTimeReplay:
        _assert_resource_owner_module_cache()
        if type(self) is not ResourceEffectTimeReplayCapability:
            raise ResourceError("resource effect-time replay capability type differs")
        with _RESOURCE_EFFECT_REPLAY_REGISTRY_LOCK:
            state = _RESOURCE_EFFECT_REPLAY_REGISTRY.get(self)
        if state is None:
            raise ResourceError(
                "resource effect-time replay capability is absent from the "
                "owner-private registry"
            )
        with state.lock:
            owner_document = _registered_owner_document(self, state)
            if state.status != "unconsumed":
                raise ResourceError(
                    "resource effect-time replay capability has already been consumed"
                )
            state.status = "consuming"
            try:
                scope = _consume_resource_effect_time_replay(
                    state,
                    owner_document,
                )
                claim = ClaimedResourceEffectTimeReplay._from_owner(
                    scope,
                    token=_RESOURCE_EFFECT_REPLAY_ISSUE_TOKEN,
                )
            except BaseException:
                state.status = "failed"
                raise
            state.status = "consumed"
            return claim

    def __copy__(self) -> "ResourceEffectTimeReplayCapability":
        raise _not_copyable("resource effect-time replay capabilities")

    def __deepcopy__(
        self, _memo: dict[int, Any]
    ) -> "ResourceEffectTimeReplayCapability":
        raise _not_copyable("resource effect-time replay capabilities")

    def __reduce__(self) -> Any:
        raise _not_copyable("resource effect-time replay capabilities")

    def __reduce_ex__(self, _protocol: int) -> Any:
        raise _not_copyable("resource effect-time replay capabilities")


def _registered_owner_document(
    capability: ResourceEffectTimeReplayCapability,
    state: _ResourceEffectReplayCapabilityState,
) -> dict[str, Any]:
    if (
        type(capability) is not ResourceEffectTimeReplayCapability
        or type(state) is not _ResourceEffectReplayCapabilityState
        or state.registered_capability is not capability
        or type(state.owner_document_bytes) is not bytes
        or type(state.owner_document_snapshot) is not dict
    ):
        raise ResourceError(
            "resource effect-time replay registered object identity differs"
        )
    current = copy.deepcopy(
        object.__getattribute__(
            capability,
            "_ResourceEffectTimeReplayCapability__document",
        )
    )
    validate_resource_effect_time_replay_capability_document(current)
    owner_snapshot = copy.deepcopy(state.owner_document_snapshot)
    if (
        execution_batch.canonical_bytes(current)
        != state.owner_document_bytes
        or execution_batch.canonical_bytes(owner_snapshot)
        != state.owner_document_bytes
        or current != owner_snapshot
    ):
        raise ResourceError(
            "resource effect-time replay registered owner document differs"
        )
    return owner_snapshot


def validate_resource_effect_time_replay_capability_document(
    document: dict[str, Any],
) -> dict[str, Any]:
    _exact(
        document,
        {
            "schema",
            "owner",
            "capability_id",
            "identity",
            "reservation_capability",
            "resource_policy",
            "resource_gate",
            "scheduler_snapshot",
            "current_resource_state",
            "freshness",
            "authority",
            "failure_policy",
            "payload_sha256",
        },
        "resource effect-time replay capability projection",
    )
    if document["schema"] != RESOURCE_EFFECT_REPLAY_CAPABILITY_SCHEMA:
        raise ResourceError("resource effect-time replay capability schema differs")
    if document["owner"] != RESOURCE_EFFECT_REPLAY_CAPABILITY_OWNER:
        raise ResourceError("resource effect-time replay capability owner differs")
    if re.fullmatch(
        r"resource-effect-replay-capability-[a-f0-9]{64}",
        _text(document["capability_id"], "capability_id"),
    ) is None:
        raise ResourceError(
            "resource effect-time replay capability id is malformed"
        )
    identity = _exact(
        document["identity"],
        {
            "scientific_task_id",
            "attempt_id",
            "idempotency_key_sha256",
            "project",
            "input_sha256",
            "resource_tier",
            "cores",
            "memory_gb",
        },
        "resource effect-time replay identity",
    )
    if re.fullmatch(
        r"scientific-task-[a-f0-9]{64}",
        _text(identity["scientific_task_id"], "scientific_task_id"),
    ) is None:
        raise ResourceError("resource replay scientific task is malformed")
    if re.fullmatch(
        r"qsub-attempt-[a-f0-9]{64}",
        _text(identity["attempt_id"], "attempt_id"),
    ) is None:
        raise ResourceError("resource replay attempt is malformed")
    _sha(identity["idempotency_key_sha256"], "idempotency_key_sha256")
    if PROJECT_RE.fullmatch(_text(identity["project"], "project")) is None:
        raise ResourceError("resource replay project is unsafe")
    _sha(identity["input_sha256"], "input_sha256")
    validate_resource_tuple(
        identity["resource_tier"],
        identity["cores"],
        identity["memory_gb"],
    )
    reservation = _exact(
        document["reservation_capability"],
        {"schema", "owner", "capability_id", "payload_sha256"},
        "resource replay reservation capability",
    )
    if (
        reservation["schema"] != RESERVATION_CAPABILITY_SCHEMA
        or reservation["owner"] != RESERVATION_CAPABILITY_OWNER
        or re.fullmatch(
            r"reservation-capability-[a-f0-9]{64}",
            _text(reservation["capability_id"], "reservation capability_id"),
        )
        is None
    ):
        raise ResourceError("resource replay reservation capability differs")
    _sha(reservation["payload_sha256"], "reservation payload_sha256")
    policy = _exact(
        document["resource_policy"],
        {
            "schema",
            "policy_revision_id",
            "policy_sha256",
            "artifact_sha256",
            "artifact_size",
        },
        "resource replay policy",
    )
    if policy["schema"] != POLICY_SCHEMA:
        raise ResourceError("resource replay policy schema differs")
    _text(policy["policy_revision_id"], "policy_revision_id")
    _sha(policy["policy_sha256"], "policy_sha256")
    _sha(policy["artifact_sha256"], "policy artifact_sha256")
    if (
        _number(policy["artifact_size"], "policy artifact_size", integer=True)
        < 1
    ):
        raise ResourceError("policy artifact_size must be positive")
    gate = _exact(
        document["resource_gate"],
        {
            "schema",
            "gate_id",
            "gate_sha256",
            "artifact_sha256",
            "artifact_size",
            "evaluated_resource_state_revision",
            "evaluated_resource_state_sha256",
        },
        "resource replay gate",
    )
    if gate["schema"] != GATE_SCHEMA:
        raise ResourceError("resource replay gate schema differs")
    _text(gate["gate_id"], "gate_id")
    _sha(gate["gate_sha256"], "gate_sha256")
    _sha(gate["artifact_sha256"], "gate artifact_sha256")
    if _number(gate["artifact_size"], "gate artifact size", integer=True) < 1:
        raise ResourceError("gate artifact size must be positive")
    _number(
        gate["evaluated_resource_state_revision"],
        "evaluated resource_state_revision",
        integer=True,
    )
    _sha(
        gate["evaluated_resource_state_sha256"],
        "evaluated resource_state_sha256",
    )
    scheduler = _exact(
        document["scheduler_snapshot"],
        {
            "schema",
            "snapshot_id",
            "payload_sha256",
            "artifact_sha256",
            "artifact_size",
            "collected_at",
            "max_age_seconds",
        },
        "resource replay scheduler snapshot",
    )
    if scheduler["schema"] != SCHEDULER_SNAPSHOT_SCHEMA:
        raise ResourceError("resource replay scheduler schema differs")
    _text(scheduler["snapshot_id"], "snapshot_id")
    _sha(scheduler["payload_sha256"], "scheduler payload_sha256")
    _sha(scheduler["artifact_sha256"], "scheduler artifact_sha256")
    if (
        _number(
            scheduler["artifact_size"],
            "scheduler artifact size",
            integer=True,
        )
        < 1
    ):
        raise ResourceError("scheduler artifact size must be positive")
    _time(scheduler["collected_at"], "scheduler collected_at")
    if (
        _number(
            scheduler["max_age_seconds"],
            "scheduler max_age_seconds",
        )
        <= 0
    ):
        raise ResourceError("scheduler max_age_seconds must be positive")
    state = _exact(
        document["current_resource_state"],
        {
            "ledger_schema",
            "batch_id",
            "ledger_revision",
            "resource_state_revision",
            "resource_state_sha256",
            "attempt_state",
        },
        "current resource state",
    )
    if state["ledger_schema"] != LEDGER_SCHEMA:
        raise ResourceError("current resource state ledger schema differs")
    _text(state["batch_id"], "batch_id")
    _number(state["ledger_revision"], "ledger_revision", integer=True)
    _number(
        state["resource_state_revision"],
        "resource_state_revision",
        integer=True,
    )
    _sha(state["resource_state_sha256"], "resource_state_sha256")
    if state["attempt_state"] != "submission_uncertain":
        raise ResourceError("resource replay attempt state differs")
    freshness = _rebuild_fixed_builtin_mapping(
        document["freshness"],
        {
            "max_age_seconds": RESOURCE_EFFECT_REPLAY_MAX_AGE_SECONDS,
            "wall_clock_enforced": True,
            "monotonic_clock_enforced": True,
        },
        "resource replay freshness",
        variable_types={"issued_at": str, "expires_at": str},
    )
    issued = _time(freshness["issued_at"], "issued_at")
    expires = _time(freshness["expires_at"], "expires_at")
    if (
        expires - issued
    ).total_seconds() != RESOURCE_EFFECT_REPLAY_MAX_AGE_SECONDS:
        raise ResourceError("resource replay freshness interval differs")
    _rebuild_fixed_builtin_mapping(
        document["authority"],
        {
            "owner_private_registry_required": True,
            "canonical_module_cache_required": True,
            "single_consumption": True,
            "schema_valid_is_capability": False,
            "portable_projection_authorizes": False,
            "raw_json_authorizes": False,
            "raw_hash_authorizes": False,
            "cli_argument_authorizes": False,
            "capability_authorizes_runner": False,
            "capability_authorizes_transport": False,
            "capability_authorizes_qsub": False,
            "production_port_wired": False,
        },
        "resource replay authority",
    )
    _rebuild_fixed_builtin_mapping(
        document["failure_policy"],
        {
            "fail_closed_on_drift": True,
            "failed_consumption_terminal": True,
            "automatic_retry": False,
            "external_effect": False,
        },
        "resource replay failure policy",
    )
    if _sha(document["payload_sha256"], "payload_sha256") != _payload(document):
        raise ResourceError("resource effect-time replay payload hash mismatch")
    return document

def load_artifact(path: Path) -> tuple[dict[str, Any], str, int]:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ResourceError(
            "resource artifact must be a readable regular non-symlink file"
        ) from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ResourceError("resource artifact must be a regular file")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        data = b"".join(chunks)
    finally:
        os.close(descriptor)
    try:
        document = json.loads(
            data.decode("utf-8"),
            parse_constant=execution_batch._reject_constant,
            object_pairs_hook=execution_batch._reject_duplicates,
        )
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        execution_batch.BatchError,
    ) as exc:
        raise ResourceError(f"resource artifact JSON is invalid: {exc}") from exc
    if not isinstance(document, dict):
        raise ResourceError("resource artifact top-level value must be an object")
    return document, __import__("hashlib").sha256(data).hexdigest(), len(data)

def _effect_wall_now() -> datetime:
    return datetime.now(timezone.utc)

def _effect_monotonic_ns() -> int:
    return time.monotonic_ns()

def _effect_time_text(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ResourceError("resource replay wall clock must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

def _require_effect_path(value: Any, label: str) -> Path:
    if not isinstance(value, Path):
        raise ResourceError(f"{label} must be a pathlib.Path")
    return value

def _replay_resource_effect_time_scope(
    *,
    ledger_path: Path,
    policy_path: Path,
    gate_path: Path,
    scheduler_path: Path,
    reservation_projection: dict[str, Any],
    reservation_scope: dict[str, Any],
    now: datetime,
    expected_replay: dict[str, Any] | None,
) -> dict[str, Any]:
    validate_reservation_capability_document(reservation_projection)
    identity = reservation_projection["identity"]
    resources = reservation_projection["resources"]
    expected_claim = {
        "schema": RESERVATION_CAPABILITY_SCHEMA,
        "capability_id": reservation_projection["capability_id"],
        "scientific_task_id": identity["scientific_task_id"],
        "attempt_id": identity["attempt_id"],
        "idempotency_key": reservation_scope.get("idempotency_key"),
        "project": identity["project"],
        "input_sha256": identity["input_sha256"],
        "resource_state_revision": reservation_projection["ledger"][
            "resource_state_revision"
        ],
        "resource_state_sha256": reservation_projection["ledger"][
            "resource_state_sha256"
        ],
        "submission_state": "submission_uncertain",
        "second_physical_attempt_permanently_forbidden": True,
        "authorizes_external_effect": False,
    }
    if reservation_scope != expected_claim:
        raise ResourceError("reservation capability private scope differs")
    idempotency_key = _text(
        reservation_scope["idempotency_key"],
        "reservation idempotency_key",
    )
    if (
        __import__("hashlib").sha256(idempotency_key.encode("utf-8")).hexdigest()
        != identity["idempotency_key_sha256"]
    ):
        raise ResourceError("reservation idempotency identity differs")
    with execution_batch._locked(ledger_path):
        ledger = validate_ledger(execution_batch.load_json(ledger_path))
        policy, policy_artifact_sha, policy_artifact_size = load_artifact(
            policy_path
        )
        gate, gate_artifact_sha, gate_artifact_size = load_artifact(gate_path)
        scheduler, scheduler_artifact_sha, scheduler_artifact_size = load_artifact(
            scheduler_path
        )
        validate_policy(policy)
        _validate_gate_binding(gate, allow_historical=False)
        validate_scheduler_snapshot(scheduler, now=_effect_time_text(now))
        projection_ledger = reservation_projection["ledger"]
        if (
            ledger["schema"] != projection_ledger["schema"]
            or ledger["batch"]["batch_id"] != projection_ledger["batch_id"]
            or ledger["revision"] != projection_ledger["revision"]
            or ledger["resource_state_revision"]
            != projection_ledger["resource_state_revision"]
            or ledger["resource_state_sha256"]
            != projection_ledger["resource_state_sha256"]
        ):
            raise ResourceError(
                "resource ledger revision/hash/state drifted after reservation"
            )
        attempt = next(
            (
                item
                for item in ledger["attempts"]
                if item["attempt_id"] == identity["attempt_id"]
            ),
            None,
        )
        if attempt is None:
            raise ResourceError("reserved resource attempt is absent")
        if (
            attempt["scientific_task_id"] != identity["scientific_task_id"]
            or attempt["idempotency_key"] != idempotency_key
            or attempt["project"] != identity["project"]
            or attempt["input_sha256"] != identity["input_sha256"]
            or attempt["state"] != "submission_uncertain"
        ):
            raise ResourceError("reserved resource attempt identity/state drifted")
        request = attempt["resource_gate"]["requested_resources"]
        if (
            request["resource_tier"] != resources["resource_tier"]
            or request["cores"] != resources["cores"]
            or request["memory_gb"] != resources["memory_gb"]
            or request["walltime_seconds"] != resources["walltime_seconds"]
            or request["estimated_core_hours"]
            != resources["estimated_core_hours"]
        ):
            raise ResourceError("reserved resource tuple drifted")
        if (
            gate != attempt["resource_gate"]
            or gate["gate_id"] != resources["gate_id"]
            or gate["gate_sha256"] != resources["gate_sha256"]
            or gate["policy_id"] != policy["policy_id"]
            or gate["policy_sha256"] != policy["payload_sha256"]
            or gate["policy_sha256"] != resources["policy_sha256"]
            or gate["execution_scope"]
            != {
                "scientific_task_id": identity["scientific_task_id"],
                "attempt_id": identity["attempt_id"],
                "project": identity["project"],
                "input_sha256": identity["input_sha256"],
            }
        ):
            raise ResourceError("resource policy/gate revision or identity drifted")
        scheduler_binding = gate["scheduler_snapshot"]
        if (
            scheduler["snapshot_id"] != scheduler_binding["snapshot_id"]
            or scheduler["payload_sha256"]
            != scheduler_binding["payload_sha256"]
            or scheduler_artifact_sha
            != scheduler_binding["artifact_sha256"]
            or scheduler_artifact_size != scheduler_binding["artifact_size"]
        ):
            raise ResourceError("scheduler resource state identity drifted")
        if not any(
            event["event_type"] == "reservation_capability_issued"
            and event["details"].get("capability_id")
            == reservation_projection["capability_id"]
            and event["details"].get("attempt_id") == identity["attempt_id"]
            for event in ledger["events"]
        ):
            raise ResourceError("reservation capability issuance evidence is absent")
        replay = {
            "identity": {
                **copy.deepcopy(identity),
                "resource_tier": resources["resource_tier"],
                "cores": resources["cores"],
                "memory_gb": resources["memory_gb"],
            },
            "reservation_capability": {
                "schema": reservation_projection["schema"],
                "owner": reservation_projection["owner"],
                "capability_id": reservation_projection["capability_id"],
                "payload_sha256": reservation_projection["payload_sha256"],
            },
            "resource_policy": {
                "schema": policy["schema"],
                "policy_revision_id": policy["policy_id"],
                "policy_sha256": policy["payload_sha256"],
                "artifact_sha256": policy_artifact_sha,
                "artifact_size": policy_artifact_size,
            },
            "resource_gate": {
                "schema": gate["schema"],
                "gate_id": gate["gate_id"],
                "gate_sha256": gate["gate_sha256"],
                "artifact_sha256": gate_artifact_sha,
                "artifact_size": gate_artifact_size,
                "evaluated_resource_state_revision": gate[
                    "resource_state_revision"
                ],
                "evaluated_resource_state_sha256": gate[
                    "resource_state_sha256"
                ],
            },
            "scheduler_snapshot": {
                "schema": scheduler["schema"],
                "snapshot_id": scheduler["snapshot_id"],
                "payload_sha256": scheduler["payload_sha256"],
                "artifact_sha256": scheduler_artifact_sha,
                "artifact_size": scheduler_artifact_size,
                "collected_at": scheduler["collected_at"],
                "max_age_seconds": scheduler["freshness"]["max_age_seconds"],
            },
            "current_resource_state": {
                "ledger_schema": ledger["schema"],
                "batch_id": ledger["batch"]["batch_id"],
                "ledger_revision": ledger["revision"],
                "resource_state_revision": ledger["resource_state_revision"],
                "resource_state_sha256": ledger["resource_state_sha256"],
                "attempt_state": attempt["state"],
            },
        }
        if expected_replay is not None and replay != expected_replay:
            raise ResourceError(
                "resource effect-time replay bytes or bindings drifted"
            )
        return replay

def issue_resource_effect_time_replay_capability(
    *,
    reservation_capability: ExecutionBatchReservationCapability,
    ledger_path: Path,
    policy_path: Path,
    gate_path: Path,
    scheduler_path: Path,
) -> ResourceEffectTimeReplayCapability:
    """Consume one reservation authority and issue one fresh replay handle."""

    _assert_resource_owner_module_cache()
    if type(reservation_capability) is not ExecutionBatchReservationCapability:
        raise ResourceError("foreign reservation capability owner/type rejected")
    ledger_path = _require_effect_path(ledger_path, "ledger_path")
    policy_path = _require_effect_path(policy_path, "policy_path")
    gate_path = _require_effect_path(gate_path, "gate_path")
    scheduler_path = _require_effect_path(scheduler_path, "scheduler_path")
    issued_wall = _effect_wall_now()
    issued_monotonic_ns = _effect_monotonic_ns()
    if (
        type(issued_wall) is not datetime
        or issued_wall.tzinfo is None
        or issued_wall.utcoffset() is None
        or type(issued_monotonic_ns) is not int
        or issued_monotonic_ns < 0
    ):
        raise ResourceError("resource replay clock source is invalid")
    reservation_projection = reservation_capability.portable_projection()
    reservation_claim = reservation_capability.claim_once()
    reservation_scope = reservation_claim.exact_scope()
    replay = _replay_resource_effect_time_scope(
        ledger_path=ledger_path,
        policy_path=policy_path,
        gate_path=gate_path,
        scheduler_path=scheduler_path,
        reservation_projection=reservation_projection,
        reservation_scope=reservation_scope,
        now=issued_wall,
        expected_replay=None,
    )
    _assert_resource_owner_module_cache()
    expires_wall = issued_wall + timedelta(
        seconds=RESOURCE_EFFECT_REPLAY_MAX_AGE_SECONDS
    )
    nonce = secrets.token_hex(32)
    capability_id = (
        "resource-effect-replay-capability-"
        + execution_batch.digest_value(
            {
                "schema": RESOURCE_EFFECT_REPLAY_CAPABILITY_SCHEMA,
                "reservation_capability_id": reservation_projection[
                    "capability_id"
                ],
                "current_resource_state": replay["current_resource_state"],
                "issued_at": _effect_time_text(issued_wall),
                "nonce": nonce,
            }
        )
    )
    document = {
        "schema": RESOURCE_EFFECT_REPLAY_CAPABILITY_SCHEMA,
        "owner": RESOURCE_EFFECT_REPLAY_CAPABILITY_OWNER,
        "capability_id": capability_id,
        **copy.deepcopy(replay),
        "freshness": {
            "issued_at": _effect_time_text(issued_wall),
            "expires_at": _effect_time_text(expires_wall),
            "max_age_seconds": RESOURCE_EFFECT_REPLAY_MAX_AGE_SECONDS,
            "wall_clock_enforced": True,
            "monotonic_clock_enforced": True,
        },
        "authority": {
            "owner_private_registry_required": True,
            "canonical_module_cache_required": True,
            "single_consumption": True,
            "schema_valid_is_capability": False,
            "portable_projection_authorizes": False,
            "raw_json_authorizes": False,
            "raw_hash_authorizes": False,
            "cli_argument_authorizes": False,
            "capability_authorizes_runner": False,
            "capability_authorizes_transport": False,
            "capability_authorizes_qsub": False,
            "production_port_wired": False,
        },
        "failure_policy": {
            "fail_closed_on_drift": True,
            "failed_consumption_terminal": True,
            "automatic_retry": False,
            "external_effect": False,
        },
        "payload_sha256": "",
    }
    document["payload_sha256"] = _payload(document)
    state = _ResourceEffectReplayCapabilityState(
        ledger_path=ledger_path,
        policy_path=policy_path,
        gate_path=gate_path,
        scheduler_path=scheduler_path,
        reservation_projection=reservation_projection,
        reservation_scope=reservation_scope,
        expected_replay=replay,
        issued_wall=issued_wall,
        issued_monotonic_ns=issued_monotonic_ns,
    )
    return ResourceEffectTimeReplayCapability._from_owner(
        document,
        state,
        token=_RESOURCE_EFFECT_REPLAY_ISSUE_TOKEN,
    )

def _assert_resource_effect_replay_clock(
    state: _ResourceEffectReplayCapabilityState,
) -> datetime:
    now_wall = _effect_wall_now()
    now_monotonic_ns = _effect_monotonic_ns()
    if (
        type(now_wall) is not datetime
        or now_wall.tzinfo is None
        or now_wall.utcoffset() is None
        or type(now_monotonic_ns) is not int
    ):
        raise ResourceError("resource replay clock source is invalid")
    wall_elapsed = (now_wall - state.issued_wall).total_seconds()
    monotonic_elapsed = (
        now_monotonic_ns - state.issued_monotonic_ns
    ) / 1_000_000_000
    if wall_elapsed < -RESOURCE_EFFECT_REPLAY_CLOCK_SKEW_SECONDS:
        raise ResourceError("resource replay wall clock regressed")
    if monotonic_elapsed < 0:
        raise ResourceError("resource replay monotonic clock regressed")
    if (
        abs(wall_elapsed - monotonic_elapsed)
        > RESOURCE_EFFECT_REPLAY_CLOCK_SKEW_SECONDS
    ):
        raise ResourceError("resource replay wall/monotonic clocks diverged")
    if (
        wall_elapsed > RESOURCE_EFFECT_REPLAY_MAX_AGE_SECONDS
        or monotonic_elapsed > RESOURCE_EFFECT_REPLAY_MAX_AGE_SECONDS
    ):
        raise ResourceError("resource effect-time replay capability expired")
    return now_wall

def _consume_resource_effect_time_replay(
    state: _ResourceEffectReplayCapabilityState,
    owner_document: dict[str, Any],
) -> dict[str, Any]:
    _assert_resource_owner_module_cache()
    validate_resource_effect_time_replay_capability_document(owner_document)
    if (
        execution_batch.canonical_bytes(owner_document)
        != state.owner_document_bytes
    ):
        raise ResourceError(
            "resource effect-time replay owner snapshot bytes differ"
        )
    now_wall = _assert_resource_effect_replay_clock(state)
    replay = _replay_resource_effect_time_scope(
        ledger_path=state.ledger_path,
        policy_path=state.policy_path,
        gate_path=state.gate_path,
        scheduler_path=state.scheduler_path,
        reservation_projection=state.reservation_projection,
        reservation_scope=state.reservation_scope,
        now=now_wall,
        expected_replay=state.expected_replay,
    )
    _assert_resource_effect_replay_clock(state)
    _assert_resource_owner_module_cache()
    return {
        "schema": RESOURCE_EFFECT_REPLAY_CAPABILITY_SCHEMA,
        "capability_id": owner_document["capability_id"],
        **copy.deepcopy(replay),
        "resource_replay_passed": True,
        "authorizes_runner": False,
        "authorizes_transport": False,
        "authorizes_qsub": False,
        "production_port_wired": False,
    }
