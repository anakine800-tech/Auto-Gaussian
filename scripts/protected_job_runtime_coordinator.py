#!/usr/bin/env python3
"""Offline-only owner composition for the future legacy production consumer.

This module is deliberately not a transport adapter.  It composes exact
owner-issued capabilities, advances only the existing protected runtime
journal, and returns a sealed, single-claim factory port.  No effect plan,
runner, transport, qsub, remote read, or filesystem cleanup is reachable.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
import threading
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import protected_production_ingress_contract as INGRESS
import protected_runtime_state_contract as RUNTIME
import legacy_root_authority_contract as ROOT
import live_approval_effect_time_replay as LIVE
import resource_effect_time_replay_owner as RESOURCE


SCHEMA = "auto-g16-protected-job-runtime-coordinator/1"
OWNER = "auto-g16-protected-job-runtime-coordinator-owner"
MODULE_NAME = "protected_job_runtime_coordinator"
FACTORY_PORT_SCHEMA = "auto-g16-protected-coordinator-factory-port/1"
_ZERO_SHA = "0" * 64
_OWNER_TOKEN = object()
_SEAL_TOKEN = object()
_PORT_TOKEN = object()
_CLAIM_TOKEN = object()

OWNER_MAP = {
    "transition_caller": OWNER,
    "runtime_state_and_journal": RUNTIME.OWNER,
    "execution_batch_ledger": "auto-g16-resource-efficiency-owner",
    "job_state_projection": "legacy-job-state-derived-projection-only",
    "live_approval_replay": LIVE.OWNER,
    "resource_effect_time_replay": RESOURCE.RESOURCE_EFFECT_REPLAY_CAPABILITY_OWNER,
    "legacy_root_descriptor": ROOT.OWNER_ID,
    "read_only_reconciliation": RUNTIME.OWNER,
    "effect_plan_and_raw_owner": "legacy_rtwin_pbs-sole-owner",
}

STATE_MACHINE = {
    "states": [
        "effect_started_outcome_uncertain",
        "factory_port_issued",
        "effect_replays_claiming",
        "factory_port_claimed",
        "accepted_terminal",
    ],
    "initial_state": "effect_started_outcome_uncertain",
    "durable_runtime_states": [
        "effect_started_outcome_uncertain",
        "accepted_terminal",
    ],
    "allowed_transitions": [
        "effect_started_outcome_uncertain->factory_port_issued",
        "factory_port_issued->effect_replays_claiming",
        "effect_replays_claiming->factory_port_claimed",
        "effect_started_outcome_uncertain->accepted_terminal",
    ],
    "failure_after_durable_consumption": "typed_read_only_reconciliation_only",
    "automatic_retry": False,
    "second_physical_attempt": False,
    "second_qsub": False,
}

RECOVERY_ORDER = [
    "open_exact_attempt_lock_read_only",
    "validate_execution_batch_submission_uncertain_and_permanent_reservation",
    "replay_complete_protected_runtime_journal",
    "reject_missing_in_process_capabilities_for_effect_recovery",
    "acquire_typed_read_only_observation_outside_this_contract",
    "accept_only_submitted_unique_or_definitely_not_submitted",
    "reconcile_execution_batch_ledger_under_its_owner_lock",
    "append_runtime_accepted_terminal_through_runtime_owner",
    "rebuild_legacy_job_state_as_derived_projection_last",
]


class ProtectedJobRuntimeCoordinatorError(ValueError):
    pass


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ProtectedJobRuntimeCoordinatorError(message)


def _exact(value: Any, fields: set[str], label: str) -> dict[str, Any]:
    _require(type(value) is dict, f"{label} must be an exact object")
    _require(set(value) == fields, f"{label} fields differ")
    return value


def _same_exact(value: Any, expected: Any) -> bool:
    if type(value) is not type(expected):
        return False
    if type(value) is dict:
        return (
            set(value) == set(expected)
            and all(_same_exact(value[key], expected[key]) for key in value)
        )
    if type(value) is list:
        return len(value) == len(expected) and all(
            _same_exact(observed, wanted)
            for observed, wanted in zip(value, expected)
        )
    return bool(value == expected)


def _fixed(value: Any, expected: Any, label: str) -> None:
    _require(_same_exact(value, expected), f"{label} differs")


def validate_protected_job_runtime_coordinator(
    document: dict[str, Any],
) -> dict[str, Any]:
    document = copy.deepcopy(document)
    _exact(
        document,
        {
            "schema",
            "owner",
            "coordinator_id",
            "identity",
            "predecessors",
            "owner_map",
            "state_machine",
            "recovery_order",
            "factory_port",
            "authority",
            "payload_sha256",
        },
        "coordinator projection",
    )
    _fixed(document["schema"], SCHEMA, "coordinator schema")
    _fixed(document["owner"], OWNER, "coordinator owner")
    _require(
        type(document["coordinator_id"]) is str
        and document["coordinator_id"].startswith("protected-job-runtime-coordinator-")
        and len(document["coordinator_id"]) == 98,
        "coordinator id is malformed",
    )
    identity = _exact(
        document["identity"],
        {
            "project",
            "input_sha256",
            "attempt_id",
            "scientific_task_id",
            "idempotency_key_sha256",
        },
        "coordinator identity",
    )
    for field in ("input_sha256", "idempotency_key_sha256"):
        _require(
            type(identity[field]) is str
            and len(identity[field]) == 64
            and all(character in "0123456789abcdef" for character in identity[field]),
            f"{field} is malformed",
        )
    _require(type(identity["project"]) is str and identity["project"], "project differs")
    _require(
        type(identity["attempt_id"]) is str
        and identity["attempt_id"].startswith("qsub-attempt-"),
        "attempt id differs",
    )
    _require(
        type(identity["scientific_task_id"]) is str
        and identity["scientific_task_id"].startswith("scientific-task-"),
        "scientific task differs",
    )
    predecessors = _exact(
        document["predecessors"],
        {
            "production_ingress_contract_id",
            "runtime_contract_id",
            "runtime_uncertain_receipt_id",
            "live_replay_capability_id",
            "resource_replay_capability_id",
            "resource_reservation_capability_id",
            "legacy_root_receipt_payload_sha256",
        },
        "coordinator predecessors",
    )
    for name, value in predecessors.items():
        _require(type(value) is str and value, f"{name} differs")
    _fixed(document["owner_map"], OWNER_MAP, "owner map")
    _fixed(document["state_machine"], STATE_MACHINE, "state machine")
    _fixed(document["recovery_order"], RECOVERY_ORDER, "recovery order")
    _fixed(
        document["factory_port"],
        {
            "schema": FACTORY_PORT_SCHEMA,
            "input_types": [
                "ProtectedLegacyEffectPlanFactoryPort",
                "SealedProtectedRuntimeStateReceipt",
                "CompletedPreQsubLiveApprovalReplay",
                "ClaimedResourceEffectTimeReplay",
                "ConsumedLegacyWorkspaceDescriptorLease",
            ],
            "output_type": "SealedProtectedCoordinatorFactoryPort",
            "future_consumer_output_type": "_LegacyEffectPlan",
            "single_claim": True,
            "current_legacy_factory_accepts_port": False,
            "factory_invoked": False,
            "effect_plan_created": False,
            "raw_effect_owner_created": False,
        },
        "factory port",
    )
    _fixed(
        document["authority"],
        {
            "exact_in_process_capabilities_required": True,
            "canonical_module_class_source_required": True,
            "portable_projection_authorizes": False,
            "raw_json_authorizes": False,
            "raw_hash_authorizes": False,
            "projection_fields_authorize": False,
            "production_factory_consumer_implemented": False,
            "legacy_adapter_connected": False,
            "runner_calls": 0,
            "transport_calls": 0,
            "qsub_calls": 0,
            "remote_reads": 0,
            "external_effects": 0,
        },
        "authority",
    )
    _require(
        type(document["payload_sha256"]) is str
        and len(document["payload_sha256"]) == 64,
        "payload sha256 is malformed",
    )
    projection = copy.deepcopy(document)
    projection["coordinator_id"] = ""
    projection["payload_sha256"] = ""
    expected_payload = digest(projection)
    _require(document["payload_sha256"] == expected_payload, "payload sha256 differs")
    expected_id = "protected-job-runtime-coordinator-" + digest(
        {
            "schema": "auto-g16-protected-job-runtime-coordinator-id/1",
            "identity": identity,
            "predecessors": predecessors,
            "payload_sha256": expected_payload,
        }
    )
    _require(document["coordinator_id"] == expected_id, "coordinator id differs")
    return document


def _identity_from_live(live_document: dict[str, Any]) -> dict[str, Any]:
    identity = live_document["execution_scope"]
    return {
        "project": identity["project"],
        "input_sha256": identity["input_sha256"],
        "attempt_id": identity["attempt_id"],
        "scientific_task_id": identity["scientific_task_id"],
        "idempotency_key_sha256": identity["idempotency_key_sha256"],
    }


def _assert_exact_inputs(
    ingress: Any,
    live: Any,
    resource: Any,
    root: Any,
) -> tuple[Any, dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    _assert_module_binding()
    _require(
        type(ingress) is INGRESS.SealedProtectedProductionIngressCapability,
        "coordinator requires exact production ingress",
    )
    _require(
        type(live) is LIVE.PreQsubLiveApprovalReplayCapability,
        "coordinator requires exact live replay capability",
    )
    _require(
        type(resource) is RESOURCE.ResourceEffectTimeReplayCapability,
        "coordinator requires exact resource replay capability",
    )
    _require(
        type(root) is ROOT.SingleUseLegacyWorkspaceDescriptorCapability,
        "coordinator requires exact legacy root capability",
    )
    ingress.assert_current()
    live.assert_current()
    root.assert_current()
    resource_document = RESOURCE.validate_resource_effect_time_replay_capability_document(
        resource.portable_projection()
    )
    ingress_document = ingress.document()
    live_document = LIVE.validate_live_approval_effect_time_replay(live.document())
    root_document = root.portable_receipt()
    runtime = ingress.predecessor.runtime_state
    _require(
        type(runtime) is RUNTIME.SealedProtectedRuntimeStateContract,
        "coordinator runtime state type differs",
    )
    runtime.assert_current()
    receipt = runtime.current_receipt
    receipt_document = receipt.document()
    _require(
        receipt_document["state"] == "effect_started_outcome_uncertain",
        "coordinator requires exact uncertain runtime",
    )
    identity = _identity_from_live(live_document)
    ingress_identity = ingress_document["identity"]
    consumer_intent = ingress.predecessor.document()["intent"]
    for field in ("project", "input_sha256", "attempt_id"):
        _require(
            ingress_identity[field] == identity[field],
            "production ingress identity differs",
        )
    for field in ("scientific_task_id", "idempotency_key_sha256"):
        _require(
            consumer_intent[field] == identity[field],
            "owner-consumer identity differs",
        )
    for observed, label in ((resource_document["identity"], "resource replay"),):
        for field in identity:
            _require(observed[field] == identity[field], f"{label} identity differs")
    _require(
        root_document["protected_production_ingress"]["contract_id"]
        == ingress_document["contract_id"],
        "legacy root ingress identity differs",
    )
    return runtime, ingress_document, live_document, resource_document, root_document


def _build_document(
    ingress_document: dict[str, Any],
    live_document: dict[str, Any],
    resource_document: dict[str, Any],
    root_document: dict[str, Any],
    runtime: Any,
) -> dict[str, Any]:
    runtime_document = runtime.document()
    ready = runtime.current_receipt.document()
    document = {
        "schema": SCHEMA,
        "owner": OWNER,
        "coordinator_id": "",
        "identity": _identity_from_live(live_document),
        "predecessors": {
            "production_ingress_contract_id": ingress_document["contract_id"],
            "runtime_contract_id": runtime_document["contract_id"],
            "runtime_uncertain_receipt_id": ready["receipt_id"],
            "live_replay_capability_id": live_document["capability_id"],
            "resource_replay_capability_id": resource_document["capability_id"],
            "resource_reservation_capability_id": resource_document[
                "reservation_capability"
            ]["capability_id"],
            "legacy_root_receipt_payload_sha256": root_document[
                "receipt_payload_sha256"
            ],
        },
        "owner_map": copy.deepcopy(OWNER_MAP),
        "state_machine": copy.deepcopy(STATE_MACHINE),
        "recovery_order": list(RECOVERY_ORDER),
        "factory_port": {
            "schema": FACTORY_PORT_SCHEMA,
            "input_types": [
                "ProtectedLegacyEffectPlanFactoryPort",
                "SealedProtectedRuntimeStateReceipt",
                "CompletedPreQsubLiveApprovalReplay",
                "ClaimedResourceEffectTimeReplay",
                "ConsumedLegacyWorkspaceDescriptorLease",
            ],
            "output_type": "SealedProtectedCoordinatorFactoryPort",
            "future_consumer_output_type": "_LegacyEffectPlan",
            "single_claim": True,
            "current_legacy_factory_accepts_port": False,
            "factory_invoked": False,
            "effect_plan_created": False,
            "raw_effect_owner_created": False,
        },
        "authority": {
            "exact_in_process_capabilities_required": True,
            "canonical_module_class_source_required": True,
            "portable_projection_authorizes": False,
            "raw_json_authorizes": False,
            "raw_hash_authorizes": False,
            "projection_fields_authorize": False,
            "production_factory_consumer_implemented": False,
            "legacy_adapter_connected": False,
            "runner_calls": 0,
            "transport_calls": 0,
            "qsub_calls": 0,
            "remote_reads": 0,
            "external_effects": 0,
        },
        "payload_sha256": "",
    }
    projection = copy.deepcopy(document)
    projection["coordinator_id"] = ""
    projection["payload_sha256"] = ""
    document["payload_sha256"] = digest(projection)
    document["coordinator_id"] = "protected-job-runtime-coordinator-" + digest(
        {
            "schema": "auto-g16-protected-job-runtime-coordinator-id/1",
            "identity": document["identity"],
            "predecessors": document["predecessors"],
            "payload_sha256": document["payload_sha256"],
        }
    )
    return validate_protected_job_runtime_coordinator(document)


@dataclass(frozen=True, slots=True, init=False)
class ClaimedProtectedCoordinatorFactoryPort:
    legacy_plan_inputs: Any
    uncertain_receipt: Any
    live_replay: Any
    resource_replay: Any
    root_lease: Any
    _seal: object

    def __new__(cls, *_args: Any, **_kwargs: Any) -> "ClaimedProtectedCoordinatorFactoryPort":
        raise TypeError("coordinator factory claims are owner-issued only")

    def assert_owner_sealed(self) -> "ClaimedProtectedCoordinatorFactoryPort":
        _assert_module_binding()
        _require(
            type(self) is ClaimedProtectedCoordinatorFactoryPort
            and self._seal is _CLAIM_TOKEN,
            "coordinator factory claim seal differs",
        )
        self.legacy_plan_inputs.assert_owner_sealed()
        self.uncertain_receipt.assert_current()
        self.live_replay.assert_owner_sealed()
        self.resource_replay.exact_scope()
        self.root_lease.assert_current()
        return self

    def __copy__(self) -> Any:
        raise TypeError("coordinator factory claims are not clonable")

    def __deepcopy__(self, _memo: Any) -> Any:
        raise TypeError("coordinator factory claims are not clonable")

    def __reduce__(self) -> Any:
        raise TypeError("coordinator factory claims are not serializable")


@dataclass(frozen=True, slots=True, init=False)
class SealedProtectedCoordinatorFactoryPort:
    _document: bytes
    _coordinator: Any
    _lock: threading.Lock
    _claimed: bool
    _seal: object

    def __new__(cls, *_args: Any, **_kwargs: Any) -> "SealedProtectedCoordinatorFactoryPort":
        raise TypeError("coordinator factory ports are owner-issued only")

    def document(self) -> dict[str, Any]:
        return json.loads(self._document)

    def assert_owner_sealed(self) -> "SealedProtectedCoordinatorFactoryPort":
        _assert_module_binding()
        _require(
            type(self) is SealedProtectedCoordinatorFactoryPort
            and self._seal is _PORT_TOKEN,
            "coordinator factory port seal differs",
        )
        validate_protected_job_runtime_coordinator(self.document())
        self._coordinator.assert_current()
        return self

    def claim_once(self) -> ClaimedProtectedCoordinatorFactoryPort:
        with self._lock:
            _require(not self._claimed, "coordinator factory port is already claimed")
            self.assert_owner_sealed()
            object.__setattr__(self, "_claimed", True)
            return self._coordinator._claim_factory_inputs_once()

    def __copy__(self) -> Any:
        raise TypeError("coordinator factory ports are not clonable")

    def __deepcopy__(self, _memo: Any) -> Any:
        raise TypeError("coordinator factory ports are not clonable")

    def __reduce__(self) -> Any:
        raise TypeError("coordinator factory ports are not serializable")


@dataclass(frozen=True, slots=True, init=False)
class SealedProtectedJobRuntimeCoordinator:
    _document: bytes
    ingress: Any
    live: Any
    resource: Any
    root: Any
    runtime: Any
    _lock: threading.Lock
    _issued: bool
    _seal: object

    def __new__(cls, *_args: Any, **_kwargs: Any) -> "SealedProtectedJobRuntimeCoordinator":
        raise TypeError("job/runtime coordinators are owner-issued only")

    def document(self) -> dict[str, Any]:
        return json.loads(self._document)

    def assert_current(self) -> "SealedProtectedJobRuntimeCoordinator":
        _require(
            type(self) is SealedProtectedJobRuntimeCoordinator
            and self._seal is _SEAL_TOKEN,
            "coordinator seal differs",
        )
        runtime, ingress_document, live_document, resource_document, root_document = (
            _assert_exact_inputs(self.ingress, self.live, self.resource, self.root)
        )
        _require(runtime is self.runtime, "coordinator runtime object differs")
        expected = _build_document(
            ingress_document, live_document, resource_document, root_document, runtime
        )
        _require(canonical_bytes(expected) == self._document, "coordinator projection differs")
        return self

    def issue_factory_port_once(self) -> SealedProtectedCoordinatorFactoryPort:
        with self._lock:
            _require(not self._issued, "coordinator factory port was already attempted")
            self.assert_current()
            object.__setattr__(self, "_issued", True)
            port = object.__new__(SealedProtectedCoordinatorFactoryPort)
            for name, value in (
                ("_document", self._document),
                ("_coordinator", self),
                ("_lock", threading.Lock()),
                ("_claimed", False),
                ("_seal", _PORT_TOKEN),
            ):
                object.__setattr__(port, name, value)
            port.assert_owner_sealed()
            return port

    def _claim_factory_inputs_once(self) -> ClaimedProtectedCoordinatorFactoryPort:
        """Effect-time claim for the future sole legacy-internal consumer."""
        # These owner-private claims perform every final bytes/state/currentness
        # replay. The exact predecessor already published the uncertain receipt;
        # this coordinator never duplicates its runtime-journal transitions.
        root_lease = self.root.consume_once()
        resource_claim = self.resource.consume_once()
        live_result = self.live.replay_once()
        uncertain = self.runtime.current_receipt
        uncertain.assert_current()
        legacy_plan_inputs = self.ingress.claim_legacy_factory_port_once()
        claim = object.__new__(ClaimedProtectedCoordinatorFactoryPort)
        for name, value in (
            ("legacy_plan_inputs", legacy_plan_inputs),
            ("uncertain_receipt", uncertain),
            ("live_replay", live_result),
            ("resource_replay", resource_claim),
            ("root_lease", root_lease),
            ("_seal", _CLAIM_TOKEN),
        ):
            object.__setattr__(claim, name, value)
        claim.assert_owner_sealed()
        return claim

    def __copy__(self) -> Any:
        raise TypeError("job/runtime coordinators are not clonable")

    def __deepcopy__(self, _memo: Any) -> Any:
        raise TypeError("job/runtime coordinators are not clonable")

    def __reduce__(self) -> Any:
        raise TypeError("job/runtime coordinators are not serializable")


class ProtectedJobRuntimeCoordinatorOwner:
    def __init__(self, *, _token: object) -> None:
        _assert_module_binding()
        if type(self) is not ProtectedJobRuntimeCoordinatorOwner or _token is not _OWNER_TOKEN:
            raise TypeError("coordinator owner requires its fixed factory")
        self._lock = threading.Lock()
        self._sealed = False

    @classmethod
    def production(cls) -> "ProtectedJobRuntimeCoordinatorOwner":
        return cls(_token=_OWNER_TOKEN)

    def seal_once(
        self,
        *,
        production_ingress: Any,
        live_replay: Any,
        resource_replay: Any,
        legacy_root: Any,
    ) -> SealedProtectedJobRuntimeCoordinator:
        with self._lock:
            _require(not self._sealed, "coordinator owner is single-use")
            runtime, ingress_document, live_document, resource_document, root_document = (
                _assert_exact_inputs(
                    production_ingress, live_replay, resource_replay, legacy_root
                )
            )
            document = _build_document(
                ingress_document, live_document, resource_document, root_document, runtime
            )
            self._sealed = True
            value = object.__new__(SealedProtectedJobRuntimeCoordinator)
            for name, item in (
                ("_document", canonical_bytes(document)),
                ("ingress", production_ingress),
                ("live", live_replay),
                ("resource", resource_replay),
                ("root", legacy_root),
                ("runtime", runtime),
                ("_lock", threading.Lock()),
                ("_issued", False),
                ("_seal", _SEAL_TOKEN),
            ):
                object.__setattr__(value, name, item)
            return value

    def __copy__(self) -> Any:
        raise TypeError("coordinator owners are not clonable")

    def __deepcopy__(self, _memo: Any) -> Any:
        raise TypeError("coordinator owners are not clonable")

    def __reduce__(self) -> Any:
        raise TypeError("coordinator owners are not serializable")


_ISSUED_TYPES = (
    ClaimedProtectedCoordinatorFactoryPort,
    SealedProtectedCoordinatorFactoryPort,
    SealedProtectedJobRuntimeCoordinator,
    ProtectedJobRuntimeCoordinatorOwner,
)
_MODULE = sys.modules.get(MODULE_NAME)
_SOURCE = Path(__file__).resolve()


def _stable_source(path: Path) -> tuple[tuple[int, int, int, int, int], str]:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        raw = bytearray()
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            raw.extend(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    identity = (
        int(before.st_dev),
        int(before.st_ino),
        int(before.st_size),
        int(before.st_mtime_ns),
        int(before.st_ctime_ns),
    )
    _require(
        identity
        == (
            int(after.st_dev),
            int(after.st_ino),
            int(after.st_size),
            int(after.st_mtime_ns),
            int(after.st_ctime_ns),
        )
        and len(raw) == before.st_size,
        "coordinator source changed during capture",
    )
    return identity, hashlib.sha256(raw).hexdigest()


_SOURCE_SNAPSHOT = _stable_source(_SOURCE)


def _assert_module_binding() -> None:
    module = sys.modules.get(MODULE_NAME)
    _require(
        isinstance(module, types.ModuleType)
        and module is _MODULE
        and Path(getattr(module, "__file__", "")).resolve() == _SOURCE,
        "canonical coordinator module identity differs",
    )
    _require(
        _stable_source(_SOURCE) == _SOURCE_SNAPSHOT,
        "coordinator source identity or bytes differ",
    )
    for issued_type in _ISSUED_TYPES:
        _require(
            getattr(module, issued_type.__name__, None) is issued_type,
            f"coordinator class identity differs: {issued_type.__name__}",
        )


_assert_module_binding()
