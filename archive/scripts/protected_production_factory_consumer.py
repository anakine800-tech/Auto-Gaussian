#!/usr/bin/env python3
"""Unique offline consumer for the protected production factory port.

The consumer accepts only the exact coordinator-issued in-process port.  It
claims that port once, replays every returned owner object, and seals one
non-executable production factory result.  The frozen legacy factory remains
the sole owner of ``_LegacyEffectPlan`` and is deliberately not invoked here.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import sys
import threading
import types
from pathlib import Path
from typing import Any, NamedTuple

import legacy_root_authority_contract as ROOT
import legacy_rtwin_pbs as LEGACY
import live_approval_effect_time_replay as LIVE
import protected_job_runtime_coordinator as COORDINATOR
import protected_production_ingress_contract as INGRESS
import protected_runtime_state_contract as RUNTIME
import resource_effect_time_replay_owner as RESOURCE


SCHEMA = "auto-g16-protected-production-factory-result/1"
OWNER = "auto-g16-protected-production-factory-consumer"
MODULE_NAME = "protected_production_factory_consumer"
ENTRYPOINT = "consume_protected_production_factory_once"
_RESULT_TOKEN = object()

COORDINATOR_CLAIM_ORDER = [
    "consume_exact_legacy_root_capability_once",
    "consume_exact_resource_replay_capability_once",
    "replay_exact_live_approval_capability_once",
    "replay_exact_uncertain_runtime_receipt",
    "claim_exact_production_ingress_factory_port_once",
]

CONSUMER_ORDER = [
    "validate_exact_coordinator_factory_port_before_claim",
    "claim_exact_coordinator_factory_port_once",
    "replay_exact_owner_issued_claim_objects",
    "seal_non_executable_production_factory_result",
]

OUTPUT = {
    "type": "SealedProtectedProductionFactoryResult",
    "contains_exact_owner_objects": True,
    "portable_projection_authorizes": False,
    "legacy_effect_plan_created": False,
    "legacy_raw_effect_owner_created": False,
    "production_adapter_connected": False,
    "physical_effect_possible": False,
}

UNCERTAIN_BOUNDARY = {
    "required_runtime_state": "effect_started_outcome_uncertain",
    "failure_before_coordinator_claim": "no_predecessor_consumption",
    "failure_after_coordinator_claim_started": (
        "typed_read_only_reconciliation_only"
    ),
    "recovery_owner": "protected-job-runtime-coordinator-owner",
    "automatic_retry": False,
    "second_physical_attempt": False,
    "second_qsub": False,
}

AUTHORITY = {
    "exact_in_process_owner_objects_required": True,
    "canonical_module_class_source_required": True,
    "schema_valid_is_sealed_result": False,
    "raw_json_authorizes": False,
    "raw_hash_authorizes": False,
    "thirteen_field_projection_authorizes": False,
    "parallel_owner_created": False,
    "legacy_transaction_plan_created": False,
    "legacy_factory_calls": 0,
    "legacy_raw_owner_calls": 0,
    "adapter_calls": 0,
    "runner_calls": 0,
    "write_calls": 0,
    "transport_calls": 0,
    "qsub_calls": 0,
    "remote_reads": 0,
    "external_effects": 0,
}


class ProtectedProductionFactoryConsumerError(ValueError):
    """The exact production factory consumer boundary was not satisfied."""


class _ResultOwnerState(NamedTuple):
    result: Any
    result_document_bytes: bytes
    result_document_sha256: str
    claim: Any
    coordinator_port: Any
    coordinator: Any
    coordinator_document_bytes: bytes
    coordinator_document_sha256: str


_RESULT_REGISTRY_LOCK = threading.RLock()
_RESULT_REGISTRY: dict[Any, _ResultOwnerState] = {}


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
        raise ProtectedProductionFactoryConsumerError(message)


def _exact(
    value: Any,
    fields: set[str],
    label: str,
) -> dict[str, Any]:
    _require(type(value) is dict, f"{label} must be an exact object")
    _require(set(value) == fields, f"{label} fields differ")
    return value


def _same_exact(value: Any, expected: Any) -> bool:
    if type(value) is not type(expected):
        return False
    if type(value) is dict:
        return (
            set(value) == set(expected)
            and all(
                _same_exact(value[key], expected[key])
                for key in value
            )
        )
    if type(value) is list:
        return (
            len(value) == len(expected)
            and all(
                _same_exact(observed, wanted)
                for observed, wanted in zip(value, expected)
            )
        )
    return bool(value == expected)


def _fixed(value: Any, expected: Any, label: str) -> None:
    _require(_same_exact(value, expected), f"{label} differs")


def _sha(value: Any, label: str) -> str:
    _require(
        type(value) is str
        and re.fullmatch(r"[a-f0-9]{64}", value) is not None,
        f"{label} is malformed",
    )
    return value


def _text(value: Any, label: str) -> str:
    _require(type(value) is str and value != "", f"{label} differs")
    return value


def _payload(document: dict[str, Any]) -> str:
    projection = copy.deepcopy(document)
    projection["result_id"] = ""
    projection["payload_sha256"] = ""
    return digest(projection)


def _result_id(document: dict[str, Any]) -> str:
    return "protected-production-factory-result-" + digest(
        {
            "schema": (
                "auto-g16-protected-production-factory-result-id/1"
            ),
            "identity": document["identity"],
            "predecessors": document["predecessors"],
            "payload_sha256": document["payload_sha256"],
        }
    )


def validate_protected_production_factory_result(
    document: dict[str, Any],
) -> dict[str, Any]:
    """Validate the non-authorizing portable projection."""

    _assert_module_binding()
    document = copy.deepcopy(document)
    _exact(
        document,
        {
            "schema",
            "owner",
            "result_id",
            "identity",
            "predecessors",
            "coordinator_claim_order",
            "consumer_order",
            "output",
            "legacy_factory_binding",
            "uncertain_boundary",
            "authority",
            "payload_sha256",
        },
        "production factory result",
    )
    _fixed(document["schema"], SCHEMA, "result schema")
    _fixed(document["owner"], OWNER, "result owner")
    _require(
        type(document["result_id"]) is str
        and re.fullmatch(
            r"protected-production-factory-result-[a-f0-9]{64}",
            document["result_id"],
        )
        is not None,
        "result id is malformed",
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
        "result identity",
    )
    _text(identity["project"], "identity project")
    _sha(identity["input_sha256"], "identity input_sha256")
    _require(
        type(identity["attempt_id"]) is str
        and identity["attempt_id"].startswith("qsub-attempt-"),
        "identity attempt_id differs",
    )
    _require(
        type(identity["scientific_task_id"]) is str
        and identity["scientific_task_id"].startswith(
            "scientific-task-"
        ),
        "identity scientific_task_id differs",
    )
    _sha(
        identity["idempotency_key_sha256"],
        "identity idempotency_key_sha256",
    )
    predecessors = _exact(
        document["predecessors"],
        {
            "coordinator_id",
            "production_ingress_contract_id",
            "runtime_contract_id",
            "runtime_uncertain_receipt_id",
            "runtime_uncertain_receipt_payload_sha256",
            "live_replay_capability_id",
            "live_replay_result_payload_sha256",
            "resource_replay_capability_id",
            "resource_reservation_capability_id",
            "legacy_root_receipt_payload_sha256",
            "legacy_root_authorization_scope_sha256",
            "legacy_root_descriptor_set_sha256",
            "plan_inputs_sha256",
        },
        "result predecessors",
    )
    for name in (
        "runtime_uncertain_receipt_payload_sha256",
        "live_replay_result_payload_sha256",
        "legacy_root_receipt_payload_sha256",
        "legacy_root_authorization_scope_sha256",
        "legacy_root_descriptor_set_sha256",
        "plan_inputs_sha256",
    ):
        _sha(predecessors[name], name)
    for name in set(predecessors) - {
        "runtime_uncertain_receipt_payload_sha256",
        "live_replay_result_payload_sha256",
        "legacy_root_receipt_payload_sha256",
        "legacy_root_authorization_scope_sha256",
        "legacy_root_descriptor_set_sha256",
        "plan_inputs_sha256",
    }:
        _text(predecessors[name], name)
    _fixed(
        document["coordinator_claim_order"],
        COORDINATOR_CLAIM_ORDER,
        "coordinator claim order",
    )
    _fixed(document["consumer_order"], CONSUMER_ORDER, "consumer order")
    _fixed(document["output"], OUTPUT, "result output")
    factory = _exact(
        document["legacy_factory_binding"],
        {
            "module",
            "factory",
            "effect_plan_type",
            "raw_owner_factory",
            "raw_owner_type",
            "legacy_source_sha256",
            "exact_identity_bound",
            "frozen_predecessor_bytes_modified",
            "factory_invoked",
        },
        "legacy factory binding",
    )
    _fixed(factory["module"], "legacy_rtwin_pbs", "legacy module")
    _fixed(
        factory["factory"],
        "_legacy_effect_plan_from_transaction",
        "legacy factory",
    )
    _fixed(
        factory["effect_plan_type"],
        "_LegacyEffectPlan",
        "legacy effect plan type",
    )
    _fixed(
        factory["raw_owner_factory"],
        "_legacy_raw_effect_owner_from_plan",
        "legacy raw owner factory",
    )
    _fixed(
        factory["raw_owner_type"],
        "_LegacyRawEffectOwner",
        "legacy raw owner type",
    )
    _sha(factory["legacy_source_sha256"], "legacy source sha256")
    _fixed(
        factory["legacy_source_sha256"],
        _LEGACY_SOURCE_SNAPSHOT[1],
        "legacy source sha256",
    )
    _fixed(factory["exact_identity_bound"], True, "legacy identity binding")
    _fixed(
        factory["frozen_predecessor_bytes_modified"],
        False,
        "frozen predecessor mutation",
    )
    _fixed(factory["factory_invoked"], False, "legacy factory invocation")
    _fixed(
        document["uncertain_boundary"],
        UNCERTAIN_BOUNDARY,
        "uncertain boundary",
    )
    _fixed(document["authority"], AUTHORITY, "result authority")
    _sha(document["payload_sha256"], "result payload sha256")
    _require(
        document["payload_sha256"] == _payload(document),
        "result payload sha256 differs",
    )
    _require(document["result_id"] == _result_id(document), "result id differs")
    return document


def _plan_snapshot(plan: Any) -> dict[str, Any]:
    return {
        name: (
            list(getattr(plan, name))
            if name == "files"
            else [list(item) for item in getattr(plan, name)]
            if name == "expected_bindings"
            else getattr(plan, name)
        )
        for name in INGRESS.PLAN_FIELDS
    }


def _assert_exact_coordinator_port(
    coordinator_port: Any,
    coordinator_document_bytes: bytes,
) -> tuple[Any, dict[str, Any]]:
    _require(
        type(coordinator_port)
        is COORDINATOR.SealedProtectedCoordinatorFactoryPort,
        "consumer requires exact coordinator factory port",
    )
    _require(
        type(coordinator_document_bytes) is bytes
        and type(coordinator_port._document) is bytes,
        "coordinator owner document bytes differ",
    )
    coordinator = coordinator_port._coordinator
    _require(
        type(coordinator)
        is COORDINATOR.SealedProtectedJobRuntimeCoordinator,
        "coordinator object identity differs",
    )
    _require(
        coordinator_port._seal is COORDINATOR._PORT_TOKEN
        and coordinator._seal is COORDINATOR._SEAL_TOKEN
        and coordinator_port._document is coordinator_document_bytes
        and coordinator._document is coordinator_document_bytes,
        "coordinator port owner snapshot differs",
    )
    document = COORDINATOR.validate_protected_job_runtime_coordinator(
        json.loads(coordinator_document_bytes)
    )
    _require(
        canonical_bytes(document) == coordinator_document_bytes
        and canonical_bytes(coordinator_port.document())
        == coordinator_document_bytes
        and canonical_bytes(coordinator.document())
        == coordinator_document_bytes,
        "coordinator owner document differs",
    )
    return coordinator, document


def _assert_exact_claim(
    claim: Any,
    coordinator_port: Any,
    coordinator_document_bytes: bytes,
) -> tuple[
    Any,
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
]:
    coordinator, coordinator_document = _assert_exact_coordinator_port(
        coordinator_port,
        coordinator_document_bytes,
    )
    _require(
        coordinator_port._claimed is True,
        "coordinator factory port claim state differs",
    )
    _require(
        type(claim) is COORDINATOR.ClaimedProtectedCoordinatorFactoryPort,
        "consumer requires exact coordinator claim",
    )
    claim.assert_owner_sealed()
    _require(
        type(claim.legacy_plan_inputs)
        is INGRESS.ProtectedLegacyEffectPlanFactoryPort,
        "legacy plan input class identity differs",
    )
    _require(
        type(claim.uncertain_receipt)
        is RUNTIME.SealedProtectedRuntimeStateReceipt,
        "runtime receipt class identity differs",
    )
    _require(
        type(claim.live_replay) is LIVE.CompletedPreQsubLiveApprovalReplay,
        "live replay result class identity differs",
    )
    _require(
        type(claim.resource_replay)
        is RESOURCE.ClaimedResourceEffectTimeReplay,
        "resource replay claim class identity differs",
    )
    _require(
        type(claim.root_lease)
        is ROOT.ConsumedLegacyWorkspaceDescriptorLease,
        "legacy root lease class identity differs",
    )
    plan = claim.legacy_plan_inputs.assert_owner_sealed()
    receipt = claim.uncertain_receipt.assert_current().document()
    claim.live_replay.assert_owner_sealed()
    live = claim.live_replay.document()
    resource = claim.resource_replay.exact_scope()
    root = claim.root_lease.assert_current()
    identity = coordinator_document["identity"]
    predecessors = coordinator_document["predecessors"]
    for name in ("project", "attempt_id", "input_sha256"):
        _require(
            getattr(plan, name) == identity[name],
            f"legacy plan {name} differs",
        )
    _require(
        receipt["state"] == "effect_started_outcome_uncertain",
        "runtime receipt is not uncertain",
    )
    _require(
        receipt["receipt_id"]
        == predecessors["runtime_uncertain_receipt_id"],
        "runtime receipt identity differs",
    )
    _require(
        live["capability_id"]
        == predecessors["live_replay_capability_id"],
        "live replay capability identity differs",
    )
    _require(
        resource["capability_id"]
        == predecessors["resource_replay_capability_id"],
        "resource replay capability identity differs",
    )
    _require(
        resource["reservation_capability"]["capability_id"]
        == predecessors["resource_reservation_capability_id"],
        "resource reservation capability identity differs",
    )
    for name in identity:
        _require(
            resource["identity"][name] == identity[name],
            f"resource replay {name} differs",
        )
    _require(
        root.receipt_payload_sha256
        == predecessors["legacy_root_receipt_payload_sha256"],
        "legacy root receipt identity differs",
    )
    if "legacy_root_authorization_scope_sha256" in predecessors:
        _require(
            root.authorization_scope_sha256
            == predecessors["legacy_root_authorization_scope_sha256"],
            "legacy root authorization scope differs",
        )
    _require(
        root.production_ingress_contract_id
        == predecessors["production_ingress_contract_id"],
        "legacy root production ingress identity differs",
    )
    _require(
        root.remote_effect_authorized is False
        and root.path_reopen_allowed is False,
        "legacy root lease effect boundary differs",
    )
    _require(
        resource["authorizes_runner"] is False
        and resource["authorizes_transport"] is False
        and resource["authorizes_qsub"] is False,
        "resource replay authority differs",
    )
    _require(
        live["factory_calls"] == 0
        and live["runner_calls"] == 0
        and live["transport_calls"] == 0
        and live["qsub_calls"] == 0,
        "live replay effect boundary differs",
    )
    return (
        coordinator,
        coordinator_document,
        receipt,
        live,
        resource,
        _plan_snapshot(plan),
    )


def _build_document(
    coordinator_port: Any,
    coordinator_document_bytes: bytes,
    claim: Any,
) -> dict[str, Any]:
    (
        _coordinator,
        coordinator_document,
        receipt,
        live,
        resource,
        plan,
    ) = _assert_exact_claim(
        claim,
        coordinator_port,
        coordinator_document_bytes,
    )
    predecessors = coordinator_document["predecessors"]
    document = {
        "schema": SCHEMA,
        "owner": OWNER,
        "result_id": "",
        "identity": copy.deepcopy(coordinator_document["identity"]),
        "predecessors": {
            "coordinator_id": coordinator_document["coordinator_id"],
            "production_ingress_contract_id": predecessors[
                "production_ingress_contract_id"
            ],
            "runtime_contract_id": predecessors["runtime_contract_id"],
            "runtime_uncertain_receipt_id": receipt["receipt_id"],
            "runtime_uncertain_receipt_payload_sha256": receipt[
                "receipt_payload_sha256"
            ],
            "live_replay_capability_id": live["capability_id"],
            "live_replay_result_payload_sha256": live[
                "result_payload_sha256"
            ],
            "resource_replay_capability_id": resource["capability_id"],
            "resource_reservation_capability_id": resource[
                "reservation_capability"
            ]["capability_id"],
            "legacy_root_receipt_payload_sha256": (
                claim.root_lease.receipt_payload_sha256
            ),
            "legacy_root_authorization_scope_sha256": (
                claim.root_lease.authorization_scope_sha256
            ),
            "legacy_root_descriptor_set_sha256": (
                claim.root_lease.descriptor_set_sha256
            ),
            "plan_inputs_sha256": digest(plan),
        },
        "coordinator_claim_order": list(COORDINATOR_CLAIM_ORDER),
        "consumer_order": list(CONSUMER_ORDER),
        "output": copy.deepcopy(OUTPUT),
        "legacy_factory_binding": {
            "module": "legacy_rtwin_pbs",
            "factory": "_legacy_effect_plan_from_transaction",
            "effect_plan_type": "_LegacyEffectPlan",
            "raw_owner_factory": "_legacy_raw_effect_owner_from_plan",
            "raw_owner_type": "_LegacyRawEffectOwner",
            "legacy_source_sha256": _LEGACY_SOURCE_SNAPSHOT[1],
            "exact_identity_bound": True,
            "frozen_predecessor_bytes_modified": False,
            "factory_invoked": False,
        },
        "uncertain_boundary": copy.deepcopy(UNCERTAIN_BOUNDARY),
        "authority": copy.deepcopy(AUTHORITY),
        "payload_sha256": "",
    }
    document["payload_sha256"] = _payload(document)
    document["result_id"] = _result_id(document)
    return validate_protected_production_factory_result(document)


class SealedProtectedProductionFactoryResult:
    """One exact, owner-sealed and deliberately non-executable result."""

    __slots__ = ("_canonical_document", "_claim", "_seal")

    def __new__(
        cls,
        *_args: Any,
        **_kwargs: Any,
    ) -> "SealedProtectedProductionFactoryResult":
        raise TypeError("production factory results are owner-issued only")

    @classmethod
    def _from_owner(
        cls,
        document: dict[str, Any],
        claim: Any,
        coordinator_port: Any,
        coordinator_document_bytes: bytes,
        *,
        token: object,
    ) -> "SealedProtectedProductionFactoryResult":
        _assert_module_binding()
        _require(
            cls is SealedProtectedProductionFactoryResult
            and token is _RESULT_TOKEN,
            "production factory result seal differs",
        )
        coordinator, coordinator_document = _assert_exact_coordinator_port(
            coordinator_port,
            coordinator_document_bytes,
        )
        _require(
            coordinator_port._claimed is True
            and document["predecessors"]["coordinator_id"]
            == coordinator_document["coordinator_id"],
            "result coordinator owner binding differs",
        )
        result_document_bytes = canonical_bytes(document)
        value = object.__new__(cls)
        object.__setattr__(
            value,
            "_canonical_document",
            result_document_bytes,
        )
        object.__setattr__(value, "_claim", claim)
        object.__setattr__(value, "_seal", _RESULT_TOKEN)
        state = _ResultOwnerState(
            result=value,
            result_document_bytes=result_document_bytes,
            result_document_sha256=hashlib.sha256(
                result_document_bytes
            ).hexdigest(),
            claim=claim,
            coordinator_port=coordinator_port,
            coordinator=coordinator,
            coordinator_document_bytes=coordinator_document_bytes,
            coordinator_document_sha256=hashlib.sha256(
                coordinator_document_bytes
            ).hexdigest(),
        )
        with _RESULT_REGISTRY_LOCK:
            _require(
                value not in _RESULT_REGISTRY,
                "production factory result is already registered",
            )
            _RESULT_REGISTRY[value] = state
        return value

    def document(self) -> dict[str, Any]:
        with _RESULT_REGISTRY_LOCK:
            state = _RESULT_REGISTRY.get(self)
            _require(
                state is not None
                and state.result is self
                and self._canonical_document
                is state.result_document_bytes,
                "production factory result is not owner-registered",
            )
            return json.loads(state.result_document_bytes)

    def assert_owner_sealed(
        self,
    ) -> "SealedProtectedProductionFactoryResult":
        _assert_module_binding()
        with _RESULT_REGISTRY_LOCK:
            state = _RESULT_REGISTRY.get(self)
        _require(
            type(self) is SealedProtectedProductionFactoryResult
            and state is not None
            and state.result is self
            and self._seal is _RESULT_TOKEN
            and self._canonical_document
            is state.result_document_bytes
            and self._claim is state.claim,
            "production factory result seal differs",
        )
        if state is None:
            raise ProtectedProductionFactoryConsumerError(
                "production factory result is not owner-registered"
            )
        _require(
            type(state.result_document_bytes) is bytes
            and hashlib.sha256(state.result_document_bytes).hexdigest()
            == state.result_document_sha256
            and type(state.coordinator_document_bytes) is bytes
            and hashlib.sha256(
                state.coordinator_document_bytes
            ).hexdigest()
            == state.coordinator_document_sha256,
            "production factory result owner bytes differ",
        )
        coordinator, coordinator_document = _assert_exact_coordinator_port(
            state.coordinator_port,
            state.coordinator_document_bytes,
        )
        _require(
            coordinator is state.coordinator,
            "production factory result coordinator object differs",
        )
        document = validate_protected_production_factory_result(
            json.loads(state.result_document_bytes)
        )
        _require(
            document["predecessors"]["coordinator_id"]
            == coordinator_document["coordinator_id"],
            "production factory result coordinator id differs",
        )
        _require(
            state.claim.root_lease.authorization_scope_sha256
            == document["predecessors"][
                "legacy_root_authorization_scope_sha256"
            ],
            "legacy root authorization scope differs",
        )
        rebuilt = _build_document(
            state.coordinator_port,
            state.coordinator_document_bytes,
            state.claim,
        )
        _require(
            canonical_bytes(rebuilt) == state.result_document_bytes,
            "production factory result owner objects differ",
        )
        return self

    def exact_owner_objects(self) -> Any:
        """Return the still-sealed claim; it exposes no execution method."""

        self.assert_owner_sealed()
        return self._claim

    def __copy__(self) -> "SealedProtectedProductionFactoryResult":
        raise TypeError("production factory results are not clonable")

    def __deepcopy__(
        self,
        _memo: dict[int, Any],
    ) -> "SealedProtectedProductionFactoryResult":
        raise TypeError("production factory results are not clonable")

    def __reduce__(self) -> object:
        raise TypeError("production factory results are not serializable")

    def __reduce_ex__(self, _protocol: int) -> object:
        raise TypeError("production factory results are not serializable")


def consume_protected_production_factory_once(
    factory_port: Any,
) -> SealedProtectedProductionFactoryResult:
    """Consume the sole exact coordinator port and seal an offline result."""

    _assert_module_binding()
    _require(
        type(factory_port)
        is COORDINATOR.SealedProtectedCoordinatorFactoryPort,
        "consumer requires exact coordinator factory port",
    )
    factory_port.assert_owner_sealed()
    coordinator_document_bytes = factory_port._document
    coordinator, _coordinator_document = _assert_exact_coordinator_port(
        factory_port,
        coordinator_document_bytes,
    )
    claim = factory_port.claim_once()
    document = _build_document(
        factory_port,
        coordinator_document_bytes,
        claim,
    )
    result = SealedProtectedProductionFactoryResult._from_owner(
        document,
        claim,
        factory_port,
        coordinator_document_bytes,
        token=_RESULT_TOKEN,
    )
    _require(
        result.assert_owner_sealed().exact_owner_objects() is claim
        and coordinator is factory_port._coordinator,
        "production factory result issuance binding differs",
    )
    return result.assert_owner_sealed()


def _stable_source(path: Path) -> tuple[tuple[int, int, int, int, int], str]:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
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
        f"source changed during capture: {path.name}",
    )
    return identity, hashlib.sha256(raw).hexdigest()


_MODULE = sys.modules.get(MODULE_NAME)
_SOURCE = Path(__file__).resolve()
_SOURCE_SNAPSHOT = _stable_source(_SOURCE)
_COORDINATOR_MODULE = sys.modules.get(COORDINATOR.MODULE_NAME)
_COORDINATOR_SOURCE = Path(COORDINATOR.__file__).resolve()
_COORDINATOR_SOURCE_SNAPSHOT = _stable_source(_COORDINATOR_SOURCE)
_COORDINATOR_BINDINGS = {
    "SealedProtectedCoordinatorFactoryPort.document": (
        COORDINATOR.SealedProtectedCoordinatorFactoryPort.document
    ),
    "SealedProtectedCoordinatorFactoryPort.assert_owner_sealed": (
        COORDINATOR.SealedProtectedCoordinatorFactoryPort
        .assert_owner_sealed
    ),
    "SealedProtectedCoordinatorFactoryPort.claim_once": (
        COORDINATOR.SealedProtectedCoordinatorFactoryPort.claim_once
    ),
    "ClaimedProtectedCoordinatorFactoryPort.assert_owner_sealed": (
        COORDINATOR.ClaimedProtectedCoordinatorFactoryPort
        .assert_owner_sealed
    ),
    "SealedProtectedJobRuntimeCoordinator.document": (
        COORDINATOR.SealedProtectedJobRuntimeCoordinator.document
    ),
    "SealedProtectedJobRuntimeCoordinator.assert_current": (
        COORDINATOR.SealedProtectedJobRuntimeCoordinator.assert_current
    ),
    "SealedProtectedJobRuntimeCoordinator._claim_factory_inputs_once": (
        COORDINATOR.SealedProtectedJobRuntimeCoordinator
        ._claim_factory_inputs_once
    ),
}
_LEGACY_MODULE = sys.modules.get("legacy_rtwin_pbs")
_LEGACY_SOURCE = Path(LEGACY.__file__).resolve()
_LEGACY_SOURCE_SNAPSHOT = _stable_source(_LEGACY_SOURCE)
_LEGACY_BINDINGS = {
    "_LegacyTransactionPlan": LEGACY._LegacyTransactionPlan,
    "_LegacyEffectPlan": LEGACY._LegacyEffectPlan,
    "_LegacyRawEffectOwner": LEGACY._LegacyRawEffectOwner,
    "_legacy_effect_plan_from_transaction": (
        LEGACY._legacy_effect_plan_from_transaction
    ),
    "_legacy_raw_effect_owner_from_plan": (
        LEGACY._legacy_raw_effect_owner_from_plan
    ),
}


def _assert_module_binding() -> None:
    module = sys.modules.get(MODULE_NAME)
    _require(
        isinstance(module, types.ModuleType)
        and module is _MODULE
        and Path(getattr(module, "__file__", "")).resolve() == _SOURCE,
        "canonical production factory consumer module identity differs",
    )
    _require(
        _stable_source(_SOURCE) == _SOURCE_SNAPSHOT,
        "production factory consumer source identity or bytes differ",
    )
    _require(
        getattr(module, ENTRYPOINT, None)
        is consume_protected_production_factory_once
        and getattr(module, "SealedProtectedProductionFactoryResult", None)
        is SealedProtectedProductionFactoryResult,
        "production factory consumer entrypoint identity differs",
    )
    COORDINATOR._assert_module_binding()
    _require(
        sys.modules.get(COORDINATOR.MODULE_NAME) is _COORDINATOR_MODULE
        and Path(COORDINATOR.__file__).resolve() == _COORDINATOR_SOURCE
        and _stable_source(_COORDINATOR_SOURCE)
        == _COORDINATOR_SOURCE_SNAPSHOT,
        "coordinator module identity or bytes differ",
    )
    for binding, value in _COORDINATOR_BINDINGS.items():
        type_name, method_name = binding.split(".", 1)
        coordinator_type = getattr(COORDINATOR, type_name, None)
        _require(
            isinstance(coordinator_type, type)
            and getattr(coordinator_type, method_name, None) is value,
            f"coordinator method identity differs: {binding}",
        )
    _require(
        sys.modules.get("legacy_rtwin_pbs") is _LEGACY_MODULE
        and Path(LEGACY.__file__).resolve() == _LEGACY_SOURCE
        and _stable_source(_LEGACY_SOURCE) == _LEGACY_SOURCE_SNAPSHOT,
        "legacy module identity or bytes differ",
    )
    for name, value in _LEGACY_BINDINGS.items():
        _require(
            getattr(LEGACY, name, None) is value,
            f"legacy class or factory identity differs: {name}",
        )


_assert_module_binding()
