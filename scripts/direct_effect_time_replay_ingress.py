#!/usr/bin/env python3
"""Exact, non-authorizing direct resource/live effect-time replay ingress.

This adapter consumes only the existing sole-owner capability objects.  It
does not issue resource or live approval authority, construct a transport,
invoke qsub, or provide a portable-document fallback.
"""

from __future__ import annotations

if globals().get("_AUTO_G16_DIRECT_EFFECT_TIME_REPLAY_INGRESS_EXECUTED", False):
    raise ImportError("direct effect-time replay ingress module has already executed")
_AUTO_G16_DIRECT_EFFECT_TIME_REPLAY_INGRESS_EXECUTED = True

import copy
import hashlib
import json
import os
import sys
import threading
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NamedTuple

import direct_root_owner_contract as ROOT
import direct_ssh_pbs_offline as DIRECT
import live_approval_effect_time_replay as LIVE
import resource_effect_time_replay_owner as RESOURCE


MODULE_NAME = "direct_effect_time_replay_ingress"
REGISTRATION_ATTRIBUTE = (
    "_auto_g16_direct_effect_time_replay_ingress_owner_registration_v1"
)
SCHEMA = "auto-g16-direct-effect-time-replay-ingress/1"
RESULT_SCHEMA = "auto-g16-direct-effect-time-replay-ingress-result/1"
OWNER = "auto-g16-direct-effect-time-replay-ingress-owner"
PHASE = "immediately_before_qsub"
BACKEND_KIND = "direct_ssh_pbs"
ZERO_SHA = "0" * 64

class DirectEffectTimeReplayIngressError(ValueError):
    """The direct effect-time capability join cannot be proved exactly."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DirectEffectTimeReplayIngressError(message)


def canonical_bytes(value: Any) -> bytes:
    try:
        return (
            json.dumps(
                value,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise DirectEffectTimeReplayIngressError(
            "direct replay ingress document is not canonical JSON"
        ) from exc


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _exact(value: Any, fields: set[str], label: str) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == fields, f"{label} fields differ")
    return value


def _same_exact(value: Any, expected: Any) -> bool:
    if type(value) is not type(expected):
        return False
    if type(value) is dict:
        return set(value) == set(expected) and all(
            _same_exact(value[key], expected[key]) for key in expected
        )
    if type(value) is list:
        return len(value) == len(expected) and all(
            _same_exact(item, wanted)
            for item, wanted in zip(value, expected, strict=True)
        )
    return value == expected


def _fixed(value: Any, expected: Any, label: str) -> None:
    _require(_same_exact(value, expected), f"{label} differs")


def _text(value: Any, label: str) -> str:
    _require(type(value) is str and bool(value), f"{label} differs")
    return value


def _sha(value: Any, label: str) -> str:
    _require(
        type(value) is str
        and len(value) == 64
        and value != ZERO_SHA
        and all(character in "0123456789abcdef" for character in value),
        f"{label} differs",
    )
    return value


def _positive_int(value: Any, label: str) -> int:
    _require(type(value) is int and value > 0, f"{label} differs")
    return value


def _positive_decimal(value: Any, label: str) -> int:
    _require(
        type(value) is str and value.isascii() and value.isdecimal(),
        f"{label} differs",
    )
    parsed = int(value, 10)
    _require(parsed > 0 and str(parsed) == value, f"{label} differs")
    return parsed


AUTHORITY = {
    "exact_in_process_capabilities_required": True,
    "sole_owner_replay_required": True,
    "single_consumption": True,
    "failed_consumption_terminal": True,
    "portable_document_authorizes": False,
    "schema_valid_authorizes": False,
    "legacy_fallback_allowed": False,
    "resource_selection_changed": False,
    "live_approval_logic_changed": False,
    "transport_connected": False,
    "backend_supported": False,
    "live_ready": False,
    "qsub_authorized": False,
    "qsub_calls": 0,
    "external_effects": 0,
    "automatic_retry": False,
}

EFFECT_TIME = {
    "phase": PHASE,
    "resource_consume_order": 1,
    "live_replay_order": 2,
    "direct_currentness_replayed_before": True,
    "direct_currentness_replayed_between": True,
    "direct_currentness_replayed_after": True,
    "future_consumer_must_invoke_immediately_before_first_qsub": True,
}

POLICY = {
    "ordinary_module_global_rebinding_rejected_at_original_owner_entry": True,
    "public_capability_field_drift_rejected_at_original_owner_entry": True,
    "ordinary_equal_record_replacement_rejected_at_original_owner_entry": True,
    "method_class_source_rebinding_rejected_at_original_owner_entry": True,
    "arbitrary_same_process_reflection_isolated": False,
    "unisolated_reflection_mechanisms": [
        "inspect.getclosurevars",
        "function.__closure__",
        "cell-contained mutable objects",
        "ctypes",
        "native code",
    ],
    "untrusted_arbitrary_same_process_code_allowed": False,
    "w4_process_isolation_required": True,
    "production_closure": False,
}


def _validate_direct_section(value: Any) -> dict[str, Any]:
    direct = _exact(
        value,
        {
            "backend_kind",
            "binding_payload_sha256",
            "profile",
            "authorization",
            "stable_root",
            "workspace",
            "identity",
            "input",
            "resources",
        },
        "direct replay ingress direct binding",
    )
    _fixed(direct["backend_kind"], BACKEND_KIND, "direct backend")
    _sha(direct["binding_payload_sha256"], "direct binding hash")
    profile = _exact(
        direct["profile"],
        {
            "schema",
            "profile_id",
            "profile_payload_sha256",
            "resource_catalog_sha256",
        },
        "direct profile binding",
    )
    _require(profile["schema"] in {ROOT.DIRECT_PROFILE_SCHEMA,
                                    ROOT.SUCCESSOR_DIRECT_PROFILE_SCHEMA},
             "direct profile schema differs")
    successor = profile["schema"] == ROOT.SUCCESSOR_DIRECT_PROFILE_SCHEMA
    _text(profile["profile_id"], "direct profile id")
    _sha(profile["profile_payload_sha256"], "direct profile hash")
    _sha(profile["resource_catalog_sha256"], "direct resource catalog hash")
    authorization = _exact(
        direct["authorization"],
        {
            "schema",
            "authorization_id",
            "authorization_payload_sha256",
            "authorization_scope_sha256",
        },
        "direct authorization binding",
    )
    _require(authorization["schema"] in {ROOT.DIRECT_AUTHORIZATION_SCHEMA,
                                          ROOT.SUCCESSOR_DIRECT_AUTHORIZATION_SCHEMA}
             and successor
             == (authorization["schema"] == ROOT.SUCCESSOR_DIRECT_AUTHORIZATION_SCHEMA),
             "direct authorization schema differs")
    _text(authorization["authorization_id"], "direct authorization id")
    _sha(authorization["authorization_payload_sha256"], "direct authorization hash")
    _sha(authorization["authorization_scope_sha256"], "direct authorization scope hash")
    stable = _exact(
        direct["stable_root"],
        {
            "schema",
            "evidence_payload_sha256",
            "receipt_payload_sha256",
            "descriptor_set_sha256",
        },
        "direct stable-root binding",
    )
    _require(stable["schema"] in {ROOT.STABLE_EVIDENCE_SCHEMA,
                                   ROOT.SUCCESSOR_STABLE_EVIDENCE_SCHEMA}
             and successor
             == (stable["schema"] == ROOT.SUCCESSOR_STABLE_EVIDENCE_SCHEMA),
             "stable evidence schema differs")
    for field in (
        "evidence_payload_sha256",
        "receipt_payload_sha256",
        "descriptor_set_sha256",
    ):
        _sha(stable[field], f"stable root {field}")
    workspace = _exact(
        direct["workspace"],
        {"project", "workspace_binding_sha256"},
        "direct workspace binding",
    )
    _text(workspace["project"], "workspace project")
    _sha(workspace["workspace_binding_sha256"], "workspace binding hash")
    identity = _exact(
        direct["identity"],
        {"scientific_task_id", "attempt_id", "idempotency_key_sha256"},
        "direct execution identity",
    )
    _text(identity["scientific_task_id"], "scientific task id")
    _text(identity["attempt_id"], "attempt id")
    _sha(identity["idempotency_key_sha256"], "idempotency key hash")
    input_binding = _exact(
        direct["input"],
        {"basename", "sha256", "size_bytes"},
        "direct input binding",
    )
    _text(input_binding["basename"], "input basename")
    _sha(input_binding["sha256"], "input hash")
    _positive_int(input_binding["size_bytes"], "input size")
    resources = _exact(
        direct["resources"],
        {
            "tier",
            "cores",
            "memory_gb",
            "walltime_seconds",
            "resources_binding_sha256",
            "policy_id",
            "policy_sha256",
            "gate_id",
            "gate_sha256",
        },
        "direct resource binding",
    )
    for field in ("tier", "policy_id", "gate_id"):
        _text(resources[field], f"resource {field}")
    for field in ("cores", "memory_gb", "walltime_seconds"):
        _positive_int(resources[field], f"resource {field}")
    for field in ("resources_binding_sha256", "policy_sha256", "gate_sha256"):
        _sha(resources[field], f"resource {field}")
    return direct


def _validate_predecessors(value: Any) -> dict[str, Any]:
    predecessors = _exact(
        value,
        {"resource_effect_time_replay", "live_approval_effect_time_replay"},
        "direct replay ingress predecessors",
    )
    resource = _exact(
        predecessors["resource_effect_time_replay"],
        {
            "schema",
            "owner",
            "capability_id",
            "payload_sha256",
            "reservation_capability_id",
            "reservation_payload_sha256",
        },
        "resource replay predecessor",
    )
    _fixed(
        resource["schema"],
        RESOURCE.RESOURCE_EFFECT_REPLAY_CAPABILITY_SCHEMA,
        "resource replay schema",
    )
    _fixed(
        resource["owner"],
        RESOURCE.RESOURCE_EFFECT_REPLAY_CAPABILITY_OWNER,
        "resource replay owner",
    )
    _text(resource["capability_id"], "resource replay capability id")
    _text(resource["reservation_capability_id"], "resource reservation capability id")
    _sha(resource["payload_sha256"], "resource replay payload hash")
    _sha(resource["reservation_payload_sha256"], "resource reservation payload hash")
    live = _exact(
        predecessors["live_approval_effect_time_replay"],
        {
            "schema",
            "owner",
            "capability_id",
            "contract_payload_sha256",
            "approval_id",
            "approval_artifact_sha256",
            "predecessor_contract_id",
        },
        "live replay predecessor",
    )
    _fixed(live["schema"], LIVE.SCHEMA, "live replay schema")
    _fixed(live["owner"], LIVE.OWNER, "live replay owner")
    for field in ("capability_id", "approval_id", "predecessor_contract_id"):
        _text(live[field], f"live replay {field}")
    _sha(live["contract_payload_sha256"], "live replay contract hash")
    _sha(live["approval_artifact_sha256"], "live approval artifact hash")
    return predecessors


def validate_direct_effect_time_replay_ingress(value: Any) -> dict[str, Any]:
    _require(type(value) is dict, "direct replay ingress must be an exact object")
    document = copy.deepcopy(value)
    _exact(
        document,
        {
            "schema",
            "owner",
            "ingress_id",
            "direct",
            "predecessors",
            "effect_time",
            "policy",
            "authority",
            "ingress_payload_sha256",
        },
        "direct replay ingress",
    )
    _fixed(document["schema"], SCHEMA, "direct replay ingress schema")
    _fixed(document["owner"], OWNER, "direct replay ingress owner")
    _require(
        type(document["ingress_id"]) is str
        and document["ingress_id"].startswith("direct-effect-time-replay-ingress-")
        and len(document["ingress_id"]) == 98,
        "direct replay ingress id differs",
    )
    direct = _validate_direct_section(document["direct"])
    predecessors = _validate_predecessors(document["predecessors"])
    _fixed(document["effect_time"], EFFECT_TIME, "direct replay effect-time policy")
    _fixed(document["policy"], POLICY, "direct replay same-process policy")
    _fixed(document["authority"], AUTHORITY, "direct replay ingress authority")
    payload = _sha(document["ingress_payload_sha256"], "direct replay ingress payload hash")
    projection = copy.deepcopy(document)
    projection["ingress_id"] = ""
    projection["ingress_payload_sha256"] = ""
    _require(payload == digest(projection), "direct replay ingress payload hash differs")
    expected_id = "direct-effect-time-replay-ingress-" + digest(
        {
            "schema": SCHEMA,
            "binding_payload_sha256": direct["binding_payload_sha256"],
            "resource_capability_id": predecessors["resource_effect_time_replay"]["capability_id"],
            "live_capability_id": predecessors["live_approval_effect_time_replay"]["capability_id"],
            "ingress_payload_sha256": payload,
        }
    )
    _require(document["ingress_id"] == expected_id, "direct replay ingress id is not closed")
    return document


def _direct_context(transaction: Any) -> tuple[Any, dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    _require(
        type(transaction) in {
            DIRECT.SyntheticTransaction,
            DIRECT.DirectServerSessionTransaction,
        },
        "direct replay ingress requires the exact direct transaction from a supported owner",
    )
    _require(transaction.state() == DIRECT.READY, "direct transaction is not at its effect-time entry")
    if type(transaction) is DIRECT.DirectServerSessionTransaction:
        root_transaction = None
        root_capability = transaction._root_capability
    else:
        root_transaction = transaction._root_transaction
        root_capability = getattr(root_transaction, "_root_capability", None)
    _require(
        type(root_capability) is ROOT.SingleUseWorkspaceDescriptorCapability,
        "direct transaction root capability type differs",
    )
    root_capability.assert_current()
    expected_binding = (
        DIRECT.build_server_session_binding(root_capability, transaction._input)
        if type(transaction) is DIRECT.DirectServerSessionTransaction
        else DIRECT.build_binding(root_capability, root_transaction, transaction._input)
    )
    _require(
        type(transaction._binding) is DIRECT.Binding
        and transaction._binding._bytes == expected_binding._bytes,
        "direct transaction binding bytes differ",
    )
    binding = expected_binding.document()
    profile = ROOT.validate_direct_execution_profile(
        json.loads(root_capability._profile_bytes)
    )
    authorization = ROOT.validate_direct_execution_authorization(
        json.loads(root_capability._authorization_bytes)
    )
    root_capability.evidence.assert_owner_sealed()
    stable = ROOT.validate_stable_root_identity_evidence(
        root_capability.evidence.document()
    )
    receipt = ROOT.validate_fresh_root_observation_receipt(
        root_capability.portable_receipt()
    )
    _require(
        binding["profile"]["profile_payload_sha256"] == profile["profile_payload_sha256"]
        and binding["authorization"]["authorization_payload_sha256"]
        == authorization["authorization_payload_sha256"]
        and binding["profile"]["stable_root_evidence_sha256"]
        == stable["evidence_payload_sha256"]
        and binding["receipt_payload_sha256"] == receipt["receipt_payload_sha256"],
        "direct profile, authorization, stable evidence, or receipt join differs",
    )
    return root_capability, binding, profile, authorization, receipt


def _capability_documents(resource: Any, live: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    _require(
        type(resource) is RESOURCE.ResourceEffectTimeReplayCapability,
        "direct replay ingress requires the exact resource replay capability",
    )
    _require(
        type(live) is LIVE.PreQsubLiveApprovalReplayCapability,
        "direct replay ingress requires the exact live replay capability",
    )
    live.assert_current()
    resource_document = RESOURCE.validate_resource_effect_time_replay_capability_document(
        resource.portable_projection()
    )
    live_document = LIVE.validate_live_approval_effect_time_replay(live.document())
    return resource_document, live_document


def _build_document(transaction: Any, resource: Any, live: Any) -> tuple[dict[str, Any], Any]:
    root, binding, profile, authorization, receipt = _direct_context(transaction)
    stable_schema = root.evidence.document()["schema"]
    _require(
        profile["schema"] == ROOT.SUCCESSOR_DIRECT_PROFILE_SCHEMA
        and authorization["schema"] == ROOT.SUCCESSOR_DIRECT_AUTHORIZATION_SCHEMA
        and stable_schema == ROOT.SUCCESSOR_STABLE_EVIDENCE_SCHEMA,
        "historical direct profile chain is replay-only before W3 seal",
    )
    resource_document, live_document = _capability_documents(resource, live)
    direct_scope = binding["scope"]
    direct_workspace = binding["workspace"]
    direct_input = binding["input"]
    direct_resources = binding["resources"]
    resource_identity = resource_document["identity"]
    live_scope = live_document["execution_scope"]
    live_resources = live_scope["resources"]
    idempotency_key_sha256 = hashlib.sha256(
        direct_scope["idempotency_key"].encode("utf-8")
    ).hexdigest()
    identity = {
        "scientific_task_id": direct_scope["scientific_task_id"],
        "attempt_id": direct_scope["attempt_id"],
        "idempotency_key_sha256": idempotency_key_sha256,
        "project": direct_workspace["project"],
        "input_sha256": direct_input["sha256"],
    }
    for field, value in identity.items():
        _require(
            resource_identity[field] == value and live_scope[field] == value,
            f"direct/resource/live scope differs: {field}",
        )
    converted_resources = {
        "tier": direct_resources["tier"],
        "cores": _positive_decimal(direct_resources["cores"], "direct resource cores"),
        "memory_gb": _positive_decimal(direct_resources["memory_gb"], "direct resource memory"),
        "walltime_seconds": _positive_decimal(
            direct_resources["walltime_seconds"],
            "direct resource walltime",
        ),
    }
    _require(
        resource_identity["resource_tier"] == converted_resources["tier"]
        and resource_identity["cores"] == converted_resources["cores"]
        and resource_identity["memory_gb"] == converted_resources["memory_gb"]
        and live_resources["resource_tier"] == converted_resources["tier"]
        and live_resources["cores"] == converted_resources["cores"]
        and live_resources["memory_gb"] == converted_resources["memory_gb"]
        and live_resources["walltime_seconds"] == converted_resources["walltime_seconds"],
        "direct/resource/live resource tuple differs",
    )
    _require(
        resource_document["resource_policy"]["policy_revision_id"]
        == live_resources["policy_id"]
        and resource_document["resource_policy"]["policy_sha256"]
        == live_resources["policy_sha256"]
        and resource_document["resource_gate"]["gate_id"]
        == live_resources["gate_id"]
        and resource_document["resource_gate"]["gate_sha256"]
        == live_resources["gate_sha256"],
        "resource owner and live approval policy/gate hashes differ",
    )
    document = {
        "schema": SCHEMA,
        "owner": OWNER,
        "ingress_id": "",
        "direct": {
            "backend_kind": binding["backend_kind"],
            "binding_payload_sha256": binding["binding_payload_sha256"],
            "profile": {
                "schema": profile["schema"],
                "profile_id": profile["profile_id"],
                "profile_payload_sha256": profile["profile_payload_sha256"],
                "resource_catalog_sha256": profile["resource_catalog_sha256"],
            },
            "authorization": {
                "schema": authorization["schema"],
                "authorization_id": authorization["authorization_id"],
                "authorization_payload_sha256": authorization["authorization_payload_sha256"],
                "authorization_scope_sha256": authorization["scope"]["authorization_scope_sha256"],
            },
            "stable_root": {
                "schema": root.evidence.document()["schema"],
                "evidence_payload_sha256": root.evidence.document()["evidence_payload_sha256"],
                "receipt_payload_sha256": receipt["receipt_payload_sha256"],
                "descriptor_set_sha256": receipt["observed_root"]["descriptor_set_sha256"],
            },
            "workspace": {
                "project": direct_workspace["project"],
                "workspace_binding_sha256": direct_workspace["workspace_binding_sha256"],
            },
            "identity": {
                "scientific_task_id": identity["scientific_task_id"],
                "attempt_id": identity["attempt_id"],
                "idempotency_key_sha256": identity["idempotency_key_sha256"],
            },
            "input": {
                "basename": direct_input["basename"],
                "sha256": direct_input["sha256"],
                "size_bytes": _positive_decimal(direct_input["size_bytes"], "direct input size"),
            },
            "resources": {
                **converted_resources,
                "resources_binding_sha256": direct_resources["resources_binding_sha256"],
                "policy_id": live_resources["policy_id"],
                "policy_sha256": live_resources["policy_sha256"],
                "gate_id": live_resources["gate_id"],
                "gate_sha256": live_resources["gate_sha256"],
            },
        },
        "predecessors": {
            "resource_effect_time_replay": {
                "schema": resource_document["schema"],
                "owner": resource_document["owner"],
                "capability_id": resource_document["capability_id"],
                "payload_sha256": resource_document["payload_sha256"],
                "reservation_capability_id": resource_document["reservation_capability"]["capability_id"],
                "reservation_payload_sha256": resource_document["reservation_capability"]["payload_sha256"],
            },
            "live_approval_effect_time_replay": {
                "schema": live_document["schema"],
                "owner": live_document["owner"],
                "capability_id": live_document["capability_id"],
                "contract_payload_sha256": live_document["contract_payload_sha256"],
                "approval_id": live_document["approval_artifact"]["approval_id"],
                "approval_artifact_sha256": live_document["approval_artifact"]["artifact_sha256"],
                "predecessor_contract_id": live_document["predecessor"]["contract_id"],
            },
        },
        "effect_time": copy.deepcopy(EFFECT_TIME),
        "policy": copy.deepcopy(POLICY),
        "authority": copy.deepcopy(AUTHORITY),
        "ingress_payload_sha256": "",
    }
    projection = copy.deepcopy(document)
    projection["ingress_id"] = ""
    projection["ingress_payload_sha256"] = ""
    document["ingress_payload_sha256"] = digest(projection)
    document["ingress_id"] = "direct-effect-time-replay-ingress-" + digest(
        {
            "schema": SCHEMA,
            "binding_payload_sha256": document["direct"]["binding_payload_sha256"],
            "resource_capability_id": document["predecessors"]["resource_effect_time_replay"]["capability_id"],
            "live_capability_id": document["predecessors"]["live_approval_effect_time_replay"]["capability_id"],
            "ingress_payload_sha256": document["ingress_payload_sha256"],
        }
    )
    return validate_direct_effect_time_replay_ingress(document), root


class ClaimedDirectEffectTimeReplayIngress:
    """Exact owner results retained together; still no effect authority."""

    __slots__ = ("ingress_id", "_seal")

    def __new__(cls, *_args: Any, **_kwargs: Any) -> "ClaimedDirectEffectTimeReplayIngress":
        raise TypeError("direct replay ingress claims are owner-issued only")

    def __copy__(self) -> Any:
        raise TypeError("direct replay ingress claims are not clonable")

    def __deepcopy__(self, _memo: Any) -> Any:
        raise TypeError("direct replay ingress claims are not clonable")

    def __reduce__(self) -> Any:
        raise TypeError("direct replay ingress claims are not serializable")


class DirectEffectTimeReplayIngressCapability:
    """Single-use direct ingress for the two exact predecessor capabilities."""

    __slots__ = ("ingress_id", "_seal")

    def __new__(cls, *_args: Any, **_kwargs: Any) -> "DirectEffectTimeReplayIngressCapability":
        raise TypeError("direct replay ingress capabilities are owner-issued only")

    def __copy__(self) -> Any:
        raise TypeError("direct replay ingress capabilities are not clonable")

    def __deepcopy__(self, _memo: Any) -> Any:
        raise TypeError("direct replay ingress capabilities are not clonable")

    def __reduce__(self) -> Any:
        raise TypeError("direct replay ingress capabilities are not serializable")


def _assert_claim_scope(ingress: dict[str, Any], scope: dict[str, Any]) -> None:
    direct = ingress["direct"]
    expected_identity = {
        **direct["identity"],
        "project": direct["workspace"]["project"],
        "input_sha256": direct["input"]["sha256"],
        "resource_tier": direct["resources"]["tier"],
        "cores": direct["resources"]["cores"],
        "memory_gb": direct["resources"]["memory_gb"],
    }
    _require(scope["identity"] == expected_identity, "resource replay claim scope differs")
    _require(
        scope["resource_policy"]["policy_revision_id"] == direct["resources"]["policy_id"]
        and scope["resource_policy"]["policy_sha256"] == direct["resources"]["policy_sha256"]
        and scope["resource_gate"]["gate_id"] == direct["resources"]["gate_id"]
        and scope["resource_gate"]["gate_sha256"] == direct["resources"]["gate_sha256"]
        and scope["resource_replay_passed"] is True
        and scope["authorizes_runner"] is False
        and scope["authorizes_transport"] is False
        and scope["authorizes_qsub"] is False,
        "resource replay claim authority or hashes differ",
    )


def _assert_live_result(ingress: dict[str, Any], result: dict[str, Any]) -> None:
    live = ingress["predecessors"]["live_approval_effect_time_replay"]
    _require(
        result["capability_id"] == live["capability_id"]
        and result["approval_artifact_sha256"] == live["approval_artifact_sha256"]
        and result["phase"] == PHASE
        and result["status"] == "approval_replayed_current"
        and result["single_use_consumed"] is True
        and result["non_authorizing"] is True
        and result["qsub_calls"] == 0
        and result["transport_calls"] == 0,
        "live approval replay result differs",
    )


def _build_result(
    ingress: dict[str, Any],
    resource_scope: dict[str, Any],
    live_result: dict[str, Any],
) -> dict[str, Any]:
    document = {
        "schema": RESULT_SCHEMA,
        "owner": OWNER,
        "ingress_id": ingress["ingress_id"],
        "ingress_payload_sha256": ingress["ingress_payload_sha256"],
        "phase": PHASE,
        "status": "exact_owner_replays_consumed",
        "resource": {
            "capability_id": ingress["predecessors"]["resource_effect_time_replay"]["capability_id"],
            "resource_state_sha256": resource_scope["current_resource_state"]["resource_state_sha256"],
            "status": "resource_replayed_current",
        },
        "live_approval": {
            "capability_id": live_result["capability_id"],
            "approval_artifact_sha256": live_result["approval_artifact_sha256"],
            "replayed_at": live_result["replayed_at"],
            "result_payload_sha256": live_result["result_payload_sha256"],
            "status": live_result["status"],
        },
        "authority": copy.deepcopy(AUTHORITY),
        "result_payload_sha256": "",
    }
    projection = copy.deepcopy(document)
    projection["result_payload_sha256"] = ""
    document["result_payload_sha256"] = digest(projection)
    return validate_direct_effect_time_replay_ingress_result(document)


def validate_direct_effect_time_replay_ingress_result(value: Any) -> dict[str, Any]:
    _require(type(value) is dict, "direct replay ingress result must be an exact object")
    document = copy.deepcopy(value)
    _exact(
        document,
        {
            "schema",
            "owner",
            "ingress_id",
            "ingress_payload_sha256",
            "phase",
            "status",
            "resource",
            "live_approval",
            "authority",
            "result_payload_sha256",
        },
        "direct replay ingress result",
    )
    _fixed(document["schema"], RESULT_SCHEMA, "direct replay result schema")
    _fixed(document["owner"], OWNER, "direct replay result owner")
    _text(document["ingress_id"], "direct replay result ingress id")
    _sha(document["ingress_payload_sha256"], "direct replay result ingress hash")
    _fixed(document["phase"], PHASE, "direct replay result phase")
    _fixed(document["status"], "exact_owner_replays_consumed", "direct replay result status")
    resource = _exact(
        document["resource"],
        {"capability_id", "resource_state_sha256", "status"},
        "direct replay resource result",
    )
    _text(resource["capability_id"], "resource result capability id")
    _sha(resource["resource_state_sha256"], "resource result state hash")
    _fixed(resource["status"], "resource_replayed_current", "resource result status")
    live = _exact(
        document["live_approval"],
        {
            "capability_id",
            "approval_artifact_sha256",
            "replayed_at",
            "result_payload_sha256",
            "status",
        },
        "direct replay live result",
    )
    _text(live["capability_id"], "live result capability id")
    _text(live["replayed_at"], "live result replayed_at")
    _sha(live["approval_artifact_sha256"], "live result approval hash")
    _sha(live["result_payload_sha256"], "live result payload hash")
    _fixed(live["status"], "approval_replayed_current", "live result status")
    _fixed(document["authority"], AUTHORITY, "direct replay result authority")
    payload = _sha(document["result_payload_sha256"], "direct replay result payload hash")
    projection = copy.deepcopy(document)
    projection["result_payload_sha256"] = ""
    _require(payload == digest(projection), "direct replay result payload hash differs")
    return document


class DirectEffectTimeReplayIngressOwner:
    """Single-issue owner for one exact direct replay ingress capability."""

    __slots__ = ()

    def __new__(cls, *_args: Any, **_kwargs: Any) -> "DirectEffectTimeReplayIngressOwner":
        raise TypeError("direct replay ingress owners are owner-issued only")

    def __copy__(self) -> Any:
        raise TypeError("direct replay ingress owners are not clonable")

    def __deepcopy__(self, _memo: Any) -> Any:
        raise TypeError("direct replay ingress owners are not clonable")

    def __reduce__(self) -> Any:
        raise TypeError("direct replay ingress owners are not serializable")


@dataclass(frozen=True, slots=True)
class _SourceSnapshot:
    path: Path
    identity: tuple[int, int, int, int, int]
    sha256: str


def _source_snapshot(module: types.ModuleType, label: str) -> _SourceSnapshot:
    raw_path = getattr(module, "__file__", None)
    _require(type(raw_path) is str, f"{label} source path is unavailable")
    path = Path(raw_path).resolve(strict=True)
    _require(path.is_file() and not path.is_symlink(), f"{label} source is not a regular file")
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
        f"{label} source changed during capture",
    )
    return _SourceSnapshot(path, identity, hashlib.sha256(raw).hexdigest())


_THIS_MODULE = sys.modules.get(MODULE_NAME)
_require(
    type(_THIS_MODULE) is types.ModuleType,
    "canonical direct replay ingress module is unavailable",
)
_registered_module = vars(DIRECT).setdefault(
    REGISTRATION_ATTRIBUTE,
    _THIS_MODULE,
)
_require(
    _registered_module is _THIS_MODULE,
    "canonical direct replay ingress owner is already registered",
)
del _registered_module
_MODULES = {
    MODULE_NAME: _THIS_MODULE,
    ROOT.__name__: ROOT,
    DIRECT.__name__: DIRECT,
    RESOURCE.__name__: RESOURCE,
    LIVE.__name__: LIVE,
}
_SOURCE_SNAPSHOTS = {
    name: _source_snapshot(module, name)
    for name, module in _MODULES.items()
    if type(module) is types.ModuleType
}
_ISSUED_TYPES = {
    "DirectEffectTimeReplayIngressCapability": DirectEffectTimeReplayIngressCapability,
    "ClaimedDirectEffectTimeReplayIngress": ClaimedDirectEffectTimeReplayIngress,
    "DirectEffectTimeReplayIngressOwner": DirectEffectTimeReplayIngressOwner,
}
_PREDECESSOR_TYPES = {
    (ROOT.__name__, "SingleUseWorkspaceDescriptorCapability"): ROOT.SingleUseWorkspaceDescriptorCapability,
    (DIRECT.__name__, "SyntheticTransaction"): DIRECT.SyntheticTransaction,
    (DIRECT.__name__, "DirectServerSessionTransaction"): DIRECT.DirectServerSessionTransaction,
    (RESOURCE.__name__, "ResourceEffectTimeReplayCapability"): RESOURCE.ResourceEffectTimeReplayCapability,
    (RESOURCE.__name__, "ClaimedResourceEffectTimeReplay"): RESOURCE.ClaimedResourceEffectTimeReplay,
    (LIVE.__name__, "PreQsubLiveApprovalReplayCapability"): LIVE.PreQsubLiveApprovalReplayCapability,
    (LIVE.__name__, "CompletedPreQsubLiveApprovalReplay"): LIVE.CompletedPreQsubLiveApprovalReplay,
}


def _assert_module_binding() -> None:
    for name, module in _MODULES.items():
        _require(
            type(module) is types.ModuleType
            and sys.modules.get(name) is module,
            f"canonical module identity differs: {name}",
        )
        _require(
            _source_snapshot(module, name) == _SOURCE_SNAPSHOTS[name],
            f"module source identity or bytes differ: {name}",
        )
    _require(DIRECT.ROOT_OWNER is ROOT, "direct root owner module identity differs")
    _require(
        vars(DIRECT).get(REGISTRATION_ATTRIBUTE) is _THIS_MODULE,
        "direct replay ingress owner registration differs",
    )
    for name, expected in _ISSUED_TYPES.items():
        _require(getattr(_THIS_MODULE, name, None) is expected, f"ingress class identity differs: {name}")
    for (module_name, name), expected in _PREDECESSOR_TYPES.items():
        _require(
            getattr(_MODULES[module_name], name, None) is expected,
            f"predecessor class identity differs: {module_name}.{name}",
        )


def _install_owner_private_api() -> None:
    """Install the public API over one closure-held sole-owner state store."""

    module = _THIS_MODULE
    require = _require
    canonical = canonical_bytes
    validate_ingress = validate_direct_effect_time_replay_ingress
    validate_result = validate_direct_effect_time_replay_ingress_result
    build_document = _build_document
    build_result = _build_result
    assert_claim_scope = _assert_claim_scope
    assert_live_result = _assert_live_result
    source_snapshot = _source_snapshot
    json_loads = json.loads
    json_dumps = json.dumps
    lock_type = type(threading.Lock())
    lock_factory = threading.Lock
    registry_lock_factory = threading.RLock
    sys_modules = sys.modules
    module_type = types.ModuleType
    capability_type = DirectEffectTimeReplayIngressCapability
    claim_type = ClaimedDirectEffectTimeReplayIngress
    owner_type = DirectEffectTimeReplayIngressOwner
    resource_capability_type = RESOURCE.ResourceEffectTimeReplayCapability
    resource_claim_type = RESOURCE.ClaimedResourceEffectTimeReplay
    live_capability_type = LIVE.PreQsubLiveApprovalReplayCapability
    live_result_type = LIVE.CompletedPreQsubLiveApprovalReplay
    owner_token = object()
    capability_token = object()
    result_token = object()
    capability_registry_lock = registry_lock_factory()
    result_registry_lock = registry_lock_factory()
    owner_registry_lock = registry_lock_factory()
    capability_registry: dict[object, object] = {}
    result_registry: dict[object, object] = {}
    owner_registry: dict[object, object] = {}
    capability_identity_anchors: dict[object, object] = {}
    result_identity_anchors: dict[object, object] = {}
    owner_identity_anchors: dict[object, object] = {}

    class _Status:
        __slots__ = ("value",)

        def __init__(self, value: str) -> None:
            self.value = value

    class _OwnerRecord(NamedTuple):
        registered_owner: object
        lock: object
        status: object
        token: object

    class _IngressRecord(NamedTuple):
        registered_capability: object
        transaction: object
        root: object
        resource: object
        live: object
        document_bytes: bytes
        lock: object
        status: object
        token: object

    class _ResultRecord(NamedTuple):
        registered_claim: object
        root: object
        resource_claim: object
        live_result: object
        document_bytes: bytes
        token: object

    forbidden_storage_globals = (
        "_OWNER_TOKEN",
        "_CAPABILITY_TOKEN",
        "_RESULT_TOKEN",
        "_REGISTRY_LOCK",
        "_CAPABILITY_REGISTRY",
        "_RESULT_REGISTRY",
        "_IngressState",
        "_ResultState",
        "_OwnerRecord",
        "_IngressRecord",
        "_ResultRecord",
        "_install_owner_private_api",
    )
    module_items = tuple(_MODULES.items())
    source_items = tuple(_SOURCE_SNAPSHOTS.items())
    predecessor_items = tuple(_PREDECESSOR_TYPES.items())
    issued_items = tuple(_ISSUED_TYPES.items())
    function_items = tuple(
        (name, value)
        for name, value in vars(module).items()
        if type(value) is types.FunctionType
        and name != "_install_owner_private_api"
    )
    module_object_items = (
        ("_THIS_MODULE", _THIS_MODULE),
        ("_MODULES", _MODULES),
        ("_SOURCE_SNAPSHOTS", _SOURCE_SNAPSHOTS),
        ("_ISSUED_TYPES", _ISSUED_TYPES),
        ("_PREDECESSOR_TYPES", _PREDECESSOR_TYPES),
        ("ROOT", ROOT),
        ("DIRECT", DIRECT),
        ("RESOURCE", RESOURCE),
        ("LIVE", LIVE),
        ("json", json),
        ("copy", copy),
        ("hashlib", hashlib),
        ("os", os),
        ("sys", sys),
        ("threading", threading),
        ("types", types),
    )
    fixed_scalars = (
        ("MODULE_NAME", MODULE_NAME),
        ("SCHEMA", SCHEMA),
        ("RESULT_SCHEMA", RESULT_SCHEMA),
        ("OWNER", OWNER),
        ("PHASE", PHASE),
        ("BACKEND_KIND", BACKEND_KIND),
    )
    authority_object = AUTHORITY
    effect_time_object = EFFECT_TIME
    policy_object = POLICY
    authority_snapshot = json_dumps(
        authority_object,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    effect_time_snapshot = json_dumps(
        effect_time_object,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    policy_snapshot = json_dumps(
        policy_object,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    installed_descriptors: dict[tuple[type, str], object] = {}
    registration_attribute = REGISTRATION_ATTRIBUTE

    def assert_private_binding() -> None:
        require(type(module) is module_type, "canonical ingress module identity differs")
        for name in forbidden_storage_globals:
            require(
                not hasattr(module, name),
                f"forged module-global owner storage differs: {name}",
            )
        for name, expected in module_object_items:
            require(getattr(module, name, None) is expected, f"module object differs: {name}")
        for name, expected_items in (
            ("_MODULES", module_items),
            ("_SOURCE_SNAPSHOTS", source_items),
            ("_ISSUED_TYPES", issued_items),
            ("_PREDECESSOR_TYPES", predecessor_items),
        ):
            current = getattr(module, name)
            require(
                type(current) is dict and len(current) == len(expected_items),
                f"module identity mapping differs: {name}",
            )
            for key, expected in expected_items:
                require(
                    key in current and current[key] is expected,
                    f"module identity mapping differs: {name}",
                )
        for name, expected in fixed_scalars:
            current = getattr(module, name, None)
            require(
                type(current) is type(expected) and current == expected,
                f"module scalar differs: {name}",
            )
        require(
            getattr(module, "AUTHORITY", None) is authority_object
            and json_dumps(
                authority_object,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            == authority_snapshot,
            "ingress authority constants differ",
        )
        require(
            getattr(module, "EFFECT_TIME", None) is effect_time_object
            and json_dumps(
                effect_time_object,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            == effect_time_snapshot,
            "ingress effect-time constants differ",
        )
        require(
            getattr(module, "POLICY", None) is policy_object
            and json_dumps(
                policy_object,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            == policy_snapshot,
            "ingress same-process policy constants differ",
        )
        for name, expected in function_items:
            require(
                getattr(module, name, None) is expected,
                f"ingress module function identity differs: {name}",
            )
        for name, expected in module_items:
            require(
                type(expected) is module_type and sys_modules.get(name) is expected,
                f"canonical module identity differs: {name}",
            )
        for name, expected in source_items:
            require(
                source_snapshot(dict(module_items)[name], name) == expected,
                f"module source identity or bytes differ: {name}",
            )
        require(DIRECT.ROOT_OWNER is ROOT, "direct root owner module identity differs")
        require(
            vars(DIRECT).get(registration_attribute) is module,
            "direct replay ingress owner registration differs",
        )
        for name, expected in issued_items:
            require(
                getattr(module, name, None) is expected,
                f"ingress class identity differs: {name}",
            )
        for (module_name, name), expected in predecessor_items:
            require(
                getattr(dict(module_items)[module_name], name, None) is expected,
                f"predecessor class identity differs: {module_name}.{name}",
            )
        for (cls, name), expected in installed_descriptors.items():
            require(
                cls.__dict__.get(name) is expected,
                f"ingress method identity differs: {cls.__name__}.{name}",
            )

    def owner_record(owner: object) -> _OwnerRecord:
        with owner_registry_lock:
            record = owner_registry.get(owner)
            original = owner_identity_anchors.get(owner)
        require(
            type(owner) is owner_type
            and type(record) is _OwnerRecord
            and record is original
            and record.registered_owner is owner
            and type(record.lock) is lock_type
            and type(record.status) is _Status
            and record.token is owner_token,
            "direct replay ingress owner registration differs",
        )
        return record

    def capability_record(capability: object) -> _IngressRecord:
        with capability_registry_lock:
            record = capability_registry.get(capability)
            original = capability_identity_anchors.get(capability)
        require(
            type(capability) is capability_type
            and type(record) is _IngressRecord
            and record is original
            and record.registered_capability is capability
            and type(record.document_bytes) is bytes
            and type(record.lock) is lock_type
            and type(record.status) is _Status
            and record.token is capability_token,
            "direct replay ingress canonical state identity differs",
        )
        return record

    def result_record(claim: object) -> _ResultRecord:
        with result_registry_lock:
            record = result_registry.get(claim)
            original = result_identity_anchors.get(claim)
        require(
            type(claim) is claim_type
            and type(record) is _ResultRecord
            and record is original
            and record.registered_claim is claim
            and type(record.document_bytes) is bytes
            and record.token is result_token,
            "direct replay ingress canonical result identity differs",
        )
        return record

    def current_locked(capability: object, record: _IngressRecord) -> dict[str, Any]:
        assert_private_binding()
        require(
            record.registered_capability is capability
            and capability._seal is capability_token,
            "direct replay ingress capability seal or registry identity differs",
        )
        document = validate_ingress(json_loads(record.document_bytes))
        require(
            type(capability.ingress_id) is str
            and capability.ingress_id == document["ingress_id"],
            "direct replay ingress live capability id differs",
        )
        expected, root = build_document(
            record.transaction,
            record.resource,
            record.live,
        )
        require(root is record.root, "direct replay ingress root identity differs")
        require(
            canonical(expected) == record.document_bytes,
            "direct replay ingress bytes differ",
        )
        return expected

    def claim_document(self: object) -> dict[str, Any]:
        record = result_record(self)
        return json_loads(record.document_bytes)

    def claim_resource(self: object) -> object:
        return result_record(self).resource_claim

    def claim_live(self: object) -> object:
        return result_record(self).live_result

    def claim_assert(self: object) -> object:
        assert_private_binding()
        record = result_record(self)
        document = validate_result(json_loads(record.document_bytes))
        require(
            self._seal is result_token,
            "direct replay claim seal differs",
        )
        require(
            type(self.ingress_id) is str
            and self.ingress_id == document["ingress_id"],
            "direct replay claim id differs",
        )
        require(
            type(record.resource_claim) is resource_claim_type
            and type(record.live_result) is live_result_type,
            "direct replay ingress owner result types differ",
        )
        record.root.assert_current()
        record.resource_claim.exact_scope()
        record.live_result.assert_owner_sealed()
        return self

    def capability_document(self: object) -> dict[str, Any]:
        record = capability_record(self)
        return json_loads(record.document_bytes)

    def capability_assert(self: object) -> object:
        record = capability_record(self)
        with record.lock:
            require(
                record.status.value == "issued",
                "direct replay ingress capability is unavailable",
            )
            try:
                current_locked(self, record)
            except BaseException:
                record.status.value = "failed"
                raise
        return self

    def capability_assert_server_session_pre_w2(
        self: object,
        direct_transaction: object,
    ) -> object:
        """Bind W2 started to this exact still-unconsumed server session."""
        record = capability_record(self)
        with record.lock:
            require(
                record.status.value == "issued"
                and type(direct_transaction) is DIRECT.DirectServerSessionTransaction
                and record.transaction is direct_transaction,
                "pre-W2 server-session ingress binding differs or was already used",
            )
            try:
                current_locked(self, record)
                direct_transaction.assert_current()
            except BaseException:
                record.status.value = "failed"
                raise
        return self

    def capability_consume(self: object) -> object:
        record = capability_record(self)
        with record.lock:
            require(
                record.status.value == "issued",
                "direct replay ingress capability is unavailable or already used",
            )
            try:
                expected = current_locked(self, record)
            except BaseException:
                record.status.value = "failed"
                raise
            record.status.value = "claiming"
            try:
                record.root.assert_current()
                resource_claim = record.resource.consume_once()
                resource_scope = resource_claim.exact_scope()
                require(
                    type(resource_claim) is resource_claim_type,
                    "resource replay claim type differs",
                )
                assert_claim_scope(expected, resource_scope)
                record.root.assert_current()
                live_result = record.live.replay_once()
                require(
                    type(live_result) is live_result_type,
                    "live replay result type differs",
                )
                live_result.assert_owner_sealed()
                live_document = live_result.document()
                assert_live_result(expected, live_document)
                record.root.assert_current()
                result_document = build_result(
                    expected,
                    resource_scope,
                    live_document,
                )
                claim = object.__new__(claim_type)
                object.__setattr__(claim, "ingress_id", expected["ingress_id"])
                object.__setattr__(claim, "_seal", result_token)
                result = _ResultRecord(
                    registered_claim=claim,
                    root=record.root,
                    resource_claim=resource_claim,
                    live_result=live_result,
                    document_bytes=canonical(result_document),
                    token=result_token,
                )
                with result_registry_lock:
                    require(
                        claim not in result_registry
                        and claim not in result_identity_anchors,
                        "direct replay ingress result registry differs",
                    )
                    result_registry[claim] = result
                    result_identity_anchors[claim] = result
                record.status.value = "consumed"
                claim_assert(claim)
                return claim
            except BaseException:
                record.status.value = "failed"
                raise

    def owner_production(cls: type) -> object:
        assert_private_binding()
        require(cls is owner_type, "direct replay ingress owner class differs")
        owner = object.__new__(owner_type)
        record = _OwnerRecord(
            registered_owner=owner,
            lock=lock_factory(),
            status=_Status("issued"),
            token=owner_token,
        )
        with owner_registry_lock:
            require(
                owner not in owner_registry and owner not in owner_identity_anchors,
                "direct replay ingress owner registry differs",
            )
            owner_registry[owner] = record
            owner_identity_anchors[owner] = record
        return owner

    def owner_seal(
        self: object,
        *,
        direct_transaction: Any,
        resource_replay: Any,
        live_approval_replay: Any,
    ) -> object:
        record = owner_record(self)
        with record.lock:
            require(
                record.status.value == "issued",
                "direct replay ingress owner is single-use",
            )
            record.status.value = "claiming"
            try:
                assert_private_binding()
                document, root = build_document(
                    direct_transaction,
                    resource_replay,
                    live_approval_replay,
                )
                capability = object.__new__(capability_type)
                object.__setattr__(capability, "ingress_id", document["ingress_id"])
                object.__setattr__(capability, "_seal", capability_token)
                capability_state = _IngressRecord(
                    registered_capability=capability,
                    transaction=direct_transaction,
                    root=root,
                    resource=resource_replay,
                    live=live_approval_replay,
                    document_bytes=canonical(document),
                    lock=lock_factory(),
                    status=_Status("issued"),
                    token=capability_token,
                )
                with capability_registry_lock:
                    require(
                        capability not in capability_registry
                        and capability not in capability_identity_anchors,
                        "direct replay ingress registry differs",
                    )
                    capability_registry[capability] = capability_state
                    capability_identity_anchors[capability] = capability_state
                capability_assert(capability)
                record.status.value = "consumed"
                return capability
            except BaseException:
                record.status.value = "failed"
                raise

    def owner_seal_server_session(
        self: object,
        *,
        direct_transaction: Any,
        resource_replay: Any,
        live_approval_replay: Any,
    ) -> object:
        require(
            type(direct_transaction) is DIRECT.DirectServerSessionTransaction,
            "server-session ingress requires the exact non-synthetic transaction",
        )
        return owner_seal(
            self,
            direct_transaction=direct_transaction,
            resource_replay=resource_replay,
            live_approval_replay=live_approval_replay,
        )

    claim_type.document = claim_document
    claim_type.resource_replay = property(claim_resource)
    claim_type.live_approval_replay = property(claim_live)
    claim_type.assert_owner_sealed = claim_assert
    capability_type.document = capability_document
    capability_type.assert_current = capability_assert
    capability_type.assert_server_session_pre_w2_current = (
        capability_assert_server_session_pre_w2
    )
    capability_type.consume_once = capability_consume
    owner_type.production = classmethod(owner_production)
    owner_type.seal_once = owner_seal
    owner_type.seal_server_session_once = owner_seal_server_session
    for cls, names in (
        (
            claim_type,
            ("document", "resource_replay", "live_approval_replay", "assert_owner_sealed"),
        ),
        (
            capability_type,
            (
                "document",
                "assert_current",
                "assert_server_session_pre_w2_current",
                "consume_once",
            ),
        ),
        (owner_type, ("production", "seal_once", "seal_server_session_once")),
    ):
        for name in names:
            installed_descriptors[(cls, name)] = cls.__dict__[name]


_install_owner_private_api()
del _install_owner_private_api
_assert_module_binding()
