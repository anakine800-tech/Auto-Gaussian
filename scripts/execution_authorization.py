#!/usr/bin/env python3
"""Own the Auto-G16 v2.6 execution request and authorization gate offline."""

from __future__ import annotations

import copy
import hashlib
import hmac
import importlib.util
import io
import re
import sys
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any, Sequence

import platform_contracts


REQUEST_SCHEMA = "auto-g16-execution-request/1"
AUTHORIZATION_SCHEMA = "auto-g16-execution-authorization/1"
REGISTRY_SCHEMA = "auto-g16-execution-authorization-registry-snapshot/1"
READINESS_SCHEMA = "auto-g16-execution-authorization-readiness/1"

SCIENTIFIC_RECEIPT_SCHEMAS = {
    "gaussian-input-approval-receipt/1",
    "gaussian-input-approval-receipt/2",
    "gaussian-input-approval-receipt/3",
}
WORK_KINDS = {"ordinary", "minimum"}
BACKENDS = {"legacy_rtwin_pbs", "direct_ssh_pbs"}
CAPABILITIES = set(platform_contracts.DECLARED_CAPABILITIES)
REQUIRED_EXECUTION_CAPABILITIES = {
    "typed_identity_attestation",
    "pbs_submit_once",
}
FIXED_REMOTE_ROOT = platform_contracts.FIXED_REMOTE_ROOT

ID_RE = re.compile(r"^[a-z][a-z0-9._-]{0,127}$")
SHA_RE = re.compile(r"^[a-f0-9]{64}$")
NONCE_RE = re.compile(r"^[a-f0-9]{32,128}$")
TASK_RE = re.compile(r"^scientific-task-[a-f0-9]{64}$")
ATTEMPT_RE = re.compile(r"^qsub-attempt-[a-f0-9]{64}$")
PROJECT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,14}$")

REQUEST_FIELDS = {
    "schema", "request_id", "input", "scientific_task_id", "attempt_id",
    "idempotency_key", "work_kind", "profile_id", "profile_sha256",
    "backend_kind", "required_capabilities", "proposed_resources",
    "upstream_artifact_refs", "intent_only", "proposal_only",
    "calculation_ready", "no_execution_authorization",
    "live_actions_performed", "request_payload_sha256",
}
AUTHORIZATION_FIELDS = {
    "schema", "authorization_id", "request", "approver", "approved_at",
    "not_before", "expires_at", "decision", "explicit_human_approval",
    "profile", "transport", "target", "workspace_binding", "runtime_binding",
    "resources", "scientific_owner_receipt", "resource_chain", "execution",
    "identity_attestation", "revocation", "consumption", "scope_sha256",
    "authorizations", "authorization_payload_sha256",
}
UPSTREAM_ROLES = (
    "scientific_owner_receipt",
    "resource_policy",
    "scheduler_resource_snapshot",
    "resource_gate",
    "execution_batch",
)
UPSTREAM_SCHEMAS = {
    "scientific_owner_receipt": SCIENTIFIC_RECEIPT_SCHEMAS,
    "resource_policy": {"gaussian-execution-resource-policy/1"},
    "scheduler_resource_snapshot": {"gaussian-scheduler-resource-snapshot/1"},
    "resource_gate": {"gaussian-execution-resource-gate/2"},
    "execution_batch": {"gaussian-execution-batch/3"},
}


class ExecutionAuthorizationError(ValueError):
    """An offline execution authorization closure cannot be proved exactly."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ExecutionAuthorizationError(message)


def _exact(value: Any, fields: set[str], label: str) -> dict[str, Any]:
    require(isinstance(value, dict), f"{label} must be an object")
    unknown = sorted(set(value) - fields)
    missing = sorted(fields - set(value))
    require(not unknown and not missing, f"{label} fields differ; unknown={unknown}, missing={missing}")
    return value


def _text(value: Any, label: str) -> str:
    require(isinstance(value, str) and value and value == value.strip(), f"{label} must be non-blank trimmed text")
    require(not any(ord(character) < 0x20 for character in value), f"{label} contains a control character")
    return value


def _identifier(value: Any, label: str) -> str:
    text = _text(value, label)
    require(ID_RE.fullmatch(text) is not None, f"{label} is not a portable identifier")
    return text


def _sha(value: Any, label: str) -> str:
    text = _text(value, label)
    require(SHA_RE.fullmatch(text) is not None and text != "0" * 64, f"{label} must be a nonzero lowercase SHA-256")
    return text


def _positive_integer(value: Any, label: str) -> int:
    require(isinstance(value, int) and not isinstance(value, bool) and value > 0, f"{label} must be a positive integer")
    return value


def _parse_time(value: Any, label: str) -> datetime:
    text = _text(value, label)
    require(platform_contracts.RFC3339_RE.fullmatch(text) is not None, f"{label} must be second-precision RFC3339 UTC")
    try:
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise ExecutionAuthorizationError(f"{label} is not a real UTC timestamp") from exc


def _current_time(now: str | datetime) -> datetime:
    if isinstance(now, str):
        return _parse_time(now, "now")
    require(isinstance(now, datetime) and now.tzinfo is not None, "now must be timezone-aware")
    return now.astimezone(timezone.utc)


def _verify_self_hash(document: dict[str, Any], field: str, label: str) -> None:
    actual = _sha(document.get(field), field)
    expected = platform_contracts.payload_sha256(document, field)
    require(hmac.compare_digest(actual, expected), f"{label} {field} mismatch")


def finalize(document: dict[str, Any], self_field: str) -> dict[str, Any]:
    return platform_contracts.finalize(document, self_field)


def _embedded_hash(document: dict[str, Any], field: str, label: str) -> str:
    actual = _sha(document.get(field), f"{label}.{field}")
    projection = {key: value for key, value in document.items() if key != field}
    expected = hashlib.sha256(platform_contracts.canonical_bytes(projection)).hexdigest()
    require(hmac.compare_digest(actual, expected), f"{label} {field} mismatch")
    return actual


def _scalar_sha256(value: Any) -> str:
    return hashlib.sha256(platform_contracts.canonical_bytes(value)).hexdigest()


def _validate_file_binding(value: Any, label: str) -> dict[str, Any]:
    binding = _exact(value, {"sha256", "size_bytes"}, label)
    _sha(binding["sha256"], f"{label}.sha256")
    _positive_integer(binding["size_bytes"], f"{label}.size_bytes")
    return copy.deepcopy(binding)


def _validate_resources(value: Any, label: str) -> dict[str, Any]:
    resource = _exact(value, {"tier", "cores", "memory_gb", "walltime_seconds"}, label)
    try:
        platform_contracts.validate_exact_resource(
            platform_contracts.build_resource_catalog(),
            tier=resource["tier"],
            cores=resource["cores"],
            memory_gb=resource["memory_gb"],
            walltime_seconds=resource["walltime_seconds"],
        )
    except (ValueError, TypeError) as exc:
        raise ExecutionAuthorizationError(f"{label} is not an exact supported resource tuple: {exc}") from exc
    return copy.deepcopy(resource)


def _validate_artifact_ref(value: Any, label: str, *, role: str | None = None) -> dict[str, Any]:
    fields = {"schema", "sha256", "size_bytes", "payload_sha256"}
    if role is not None:
        fields.add("role")
    ref = _exact(value, fields, label)
    if role is not None:
        require(ref["role"] == role, f"{label} role mismatch")
        schema = _text(ref["schema"], f"{label}.schema")
        require(schema in UPSTREAM_SCHEMAS[role], f"{label} schema is unsupported")
    else:
        _text(ref["schema"], f"{label}.schema")
    _sha(ref["sha256"], f"{label}.sha256")
    _positive_integer(ref["size_bytes"], f"{label}.size_bytes")
    _sha(ref["payload_sha256"], f"{label}.payload_sha256")
    return copy.deepcopy(ref)


def validate_execution_request(document: Any) -> dict[str, Any]:
    request = _exact(document, REQUEST_FIELDS, "execution request")
    require(request["schema"] == REQUEST_SCHEMA, "execution request schema is unsupported")
    _identifier(request["request_id"], "request_id")
    _validate_file_binding(request["input"], "request.input")
    require(isinstance(request["scientific_task_id"], str) and TASK_RE.fullmatch(request["scientific_task_id"]) is not None, "scientific_task_id is malformed")
    require(isinstance(request["attempt_id"], str) and ATTEMPT_RE.fullmatch(request["attempt_id"]) is not None, "attempt_id is malformed")
    _identifier(request["idempotency_key"], "idempotency_key")
    require(isinstance(request["work_kind"], str) and request["work_kind"] in WORK_KINDS, "profile-mode work_kind is unsupported")
    _identifier(request["profile_id"], "profile_id")
    _sha(request["profile_sha256"], "profile_sha256")
    require(isinstance(request["backend_kind"], str) and request["backend_kind"] in BACKENDS, "execution backend is unsupported")
    capabilities = request["required_capabilities"]
    require(isinstance(capabilities, list) and all(isinstance(item, str) for item in capabilities), "required_capabilities must be an array of strings")
    require(capabilities == sorted(set(capabilities)), "required_capabilities must be unique and sorted")
    require(set(capabilities).issubset(CAPABILITIES), "request requires an unknown capability")
    require(REQUIRED_EXECUTION_CAPABILITIES.issubset(capabilities), "request omits a mandatory execution capability")
    _validate_resources(request["proposed_resources"], "request.proposed_resources")
    refs = request["upstream_artifact_refs"]
    require(isinstance(refs, list) and len(refs) == len(UPSTREAM_ROLES), "request must bind the exact five upstream artifacts")
    for index, role in enumerate(UPSTREAM_ROLES):
        _validate_artifact_ref(refs[index], f"upstream_artifact_refs[{index}]", role=role)
    markers = {
        "intent_only": True,
        "proposal_only": True,
        "calculation_ready": False,
        "no_execution_authorization": True,
        "live_actions_performed": False,
    }
    require(all(request[key] is expected for key, expected in markers.items()), "execution request authority markers changed")
    _verify_self_hash(request, "request_payload_sha256", "execution request")
    return copy.deepcopy(request)


def build_execution_request(
    *,
    request_id: str,
    input_sha256: str,
    input_size_bytes: int,
    scientific_task_id: str,
    attempt_id: str,
    idempotency_key: str,
    work_kind: str,
    profile_id: str,
    profile_sha256: str,
    backend_kind: str,
    required_capabilities: Sequence[str],
    proposed_resources: dict[str, Any],
    upstream_artifact_refs: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    document = {
        "schema": REQUEST_SCHEMA,
        "request_id": request_id,
        "input": {"sha256": input_sha256, "size_bytes": input_size_bytes},
        "scientific_task_id": scientific_task_id,
        "attempt_id": attempt_id,
        "idempotency_key": idempotency_key,
        "work_kind": work_kind,
        "profile_id": profile_id,
        "profile_sha256": profile_sha256,
        "backend_kind": backend_kind,
        "required_capabilities": list(required_capabilities),
        "proposed_resources": copy.deepcopy(proposed_resources),
        "upstream_artifact_refs": [copy.deepcopy(item) for item in upstream_artifact_refs],
        "intent_only": True,
        "proposal_only": True,
        "calculation_ready": False,
        "no_execution_authorization": True,
        "live_actions_performed": False,
        "request_payload_sha256": "",
    }
    return validate_execution_request(finalize(document, "request_payload_sha256"))


def _validate_workspace(value: Any) -> dict[str, Any]:
    workspace = _exact(value, {
        "root_policy", "allowed_root", "project", "remote_workdir",
        "fresh_project_required", "no_overwrite", "no_symlink", "no_delete",
        "workspace_binding_sha256",
    }, "workspace binding")
    require(workspace["root_policy"] == "fixed_sdl" and workspace["allowed_root"] == FIXED_REMOTE_ROOT, "workspace root policy changed")
    project = _text(workspace["project"], "workspace.project")
    require(PROJECT_RE.fullmatch(project) is not None, "workspace project is unsafe")
    require(workspace["remote_workdir"] == f"{FIXED_REMOTE_ROOT}/{project}", "workspace remote_workdir differs from the fixed exact project")
    fixed = {"fresh_project_required": True, "no_overwrite": True, "no_symlink": True, "no_delete": True}
    require(all(workspace[key] is expected for key, expected in fixed.items()), "workspace safety markers changed")
    _embedded_hash(workspace, "workspace_binding_sha256", "workspace binding")
    return copy.deepcopy(workspace)


def _validate_runtime(value: Any) -> dict[str, Any]:
    runtime = _exact(value, {
        "invocation_mode", "executable_ref_sha256", "input_sha256",
        "workspace_binding_sha256", "resources", "runtime_binding_sha256",
    }, "runtime binding")
    require(runtime["invocation_mode"] == "legacy_stdin", "runtime invocation mode is unsupported")
    for field in ("executable_ref_sha256", "input_sha256", "workspace_binding_sha256"):
        _sha(runtime[field], f"runtime_binding.{field}")
    _validate_resources(runtime["resources"], "runtime_binding.resources")
    _embedded_hash(runtime, "runtime_binding_sha256", "runtime binding")
    return copy.deepcopy(runtime)


def _validate_scientific_ref(value: Any) -> dict[str, Any]:
    ref = _exact(value, {"schema", "sha256", "size_bytes", "payload_sha256", "input_sha256", "work_kind"}, "scientific owner receipt binding")
    require(isinstance(ref["schema"], str) and ref["schema"] in SCIENTIFIC_RECEIPT_SCHEMAS, "scientific owner receipt schema is unsupported")
    for field in ("sha256", "payload_sha256", "input_sha256"):
        _sha(ref[field], f"scientific_owner_receipt.{field}")
    _positive_integer(ref["size_bytes"], "scientific_owner_receipt.size_bytes")
    require(isinstance(ref["work_kind"], str) and ref["work_kind"] in WORK_KINDS, "scientific owner receipt work_kind is unsupported")
    if ref["schema"] != "gaussian-input-approval-receipt/1":
        require(ref["work_kind"] == "minimum", "specialist scientific receipt is restricted to minimum")
    return copy.deepcopy(ref)


def _validate_resource_chain(value: Any) -> dict[str, Any]:
    chain = _exact(value, {"policy", "scheduler_snapshot", "gate", "execution_batch"}, "resource chain")
    expected = {
        "policy": "gaussian-execution-resource-policy/1",
        "scheduler_snapshot": "gaussian-scheduler-resource-snapshot/1",
        "gate": "gaussian-execution-resource-gate/2",
        "execution_batch": "gaussian-execution-batch/3",
    }
    for name, schema in expected.items():
        ref = _validate_artifact_ref(chain[name], f"resource_chain.{name}")
        require(ref["schema"] == schema, f"resource_chain.{name} schema mismatch")
    return copy.deepcopy(chain)


def _validate_execution(value: Any) -> dict[str, Any]:
    execution = _exact(value, {"batch_id", "review_sha256", "scientific_task_id", "attempt_id", "idempotency_key"}, "execution binding")
    _identifier(execution["batch_id"], "execution.batch_id")
    _sha(execution["review_sha256"], "execution.review_sha256")
    require(isinstance(execution["scientific_task_id"], str) and TASK_RE.fullmatch(execution["scientific_task_id"]) is not None, "execution scientific_task_id is malformed")
    require(isinstance(execution["attempt_id"], str) and ATTEMPT_RE.fullmatch(execution["attempt_id"]) is not None, "execution attempt_id is malformed")
    _identifier(execution["idempotency_key"], "execution.idempotency_key")
    return copy.deepcopy(execution)


def _validate_attestation_chain(value: Any, *, backend_kind: str, authorization_window: tuple[datetime, datetime], now: datetime) -> dict[str, Any]:
    chain = _exact(value, {"mode", "operations"}, "identity attestation chain")
    expected_mode = "legacy_two_stage" if backend_kind == "legacy_rtwin_pbs" else "direct_single_stage"
    expected_operations = (
        ("attest_first_hop_once", "first-hop-identity-attestation/1", ["read_local_identity_sources", "network_identity_handshake"]),
        ("attest_nested_hop_once", "nested-hop-identity-attestation/1", ["read_remote_identity_source_hashes"]),
    ) if expected_mode == "legacy_two_stage" else (
        ("attest_first_hop_once", "first-hop-identity-attestation/1", ["read_local_identity_sources", "network_identity_handshake"]),
    )
    require(chain["mode"] == expected_mode, "identity attestation mode differs from backend")
    operations = chain["operations"]
    require(isinstance(operations, list) and len(operations) == len(expected_operations), "identity attestation operation count differs from backend")
    nonces: set[str] = set()
    authorization_start, authorization_end = authorization_window
    for index, (expected_operation, expected_version, expected_effects) in enumerate(expected_operations):
        operation = _exact(operations[index], {
            "operation", "operation_version", "request_nonce", "not_before", "expires_at",
            "allowed_read_only_side_effects", "read_only", "automatic_retry", "mutation_allowed",
        }, f"identity attestation operation {index}")
        require(operation["operation"] == expected_operation, f"identity attestation operation {index} changed")
        require(operation["operation_version"] == expected_version, f"identity attestation operation {index} version changed")
        nonce = _text(operation["request_nonce"], f"identity_attestation.operations[{index}].request_nonce")
        require(NONCE_RE.fullmatch(nonce) is not None and nonce not in nonces, "identity attestation nonce is malformed or duplicated")
        nonces.add(nonce)
        starts = _parse_time(operation["not_before"], f"identity_attestation.operations[{index}].not_before")
        expires = _parse_time(operation["expires_at"], f"identity_attestation.operations[{index}].expires_at")
        require(starts < expires and (expires - starts).total_seconds() <= platform_contracts.MAX_ATTESTATION_WINDOW_SECONDS, "identity attestation time window is inverted or too wide")
        require(authorization_start <= starts <= now < expires <= authorization_end, "identity attestation operation is outside its active authorization window")
        require(operation["allowed_read_only_side_effects"] == expected_effects, "identity attestation read-only side effects expanded")
        require(operation["read_only"] is True and operation["automatic_retry"] is False and operation["mutation_allowed"] is False, "identity attestation safety markers changed")
    return copy.deepcopy(chain)


def _scope_sha256(document: dict[str, Any]) -> str:
    # The authorization artifact is the human approval record.  Its scope binds
    # every authority-bearing field, including signer, time/state, and the exact
    # operations.  Per-operation copies of this digest are omitted to avoid a
    # recursive hash definition.
    projection = {
        field: copy.deepcopy(value)
        for field, value in document.items()
        if field not in {"scope_sha256", "authorization_payload_sha256"}
    }
    projection["authorizations"] = [
        {key: value for key, value in operation.items() if key != "scope_sha256"}
        for operation in document["authorizations"]
    ]
    return hashlib.sha256(platform_contracts.canonical_bytes(projection)).hexdigest()


def validate_execution_authorization(document: Any, *, now: str | datetime) -> dict[str, Any]:
    authorization = _exact(document, AUTHORIZATION_FIELDS, "execution authorization")
    require(authorization["schema"] == AUTHORIZATION_SCHEMA, "execution authorization schema is unsupported")
    _identifier(authorization["authorization_id"], "authorization_id")
    request = _exact(authorization["request"], {"request_id", "request_payload_sha256"}, "authorization request binding")
    _identifier(request["request_id"], "authorization.request.request_id")
    _sha(request["request_payload_sha256"], "authorization.request.request_payload_sha256")
    approver = _exact(authorization["approver"], {"principal_id"}, "authorization approver")
    _identifier(approver["principal_id"], "approver.principal_id")
    approved = _parse_time(authorization["approved_at"], "approved_at")
    starts = _parse_time(authorization["not_before"], "not_before")
    expires = _parse_time(authorization["expires_at"], "expires_at")
    current = _current_time(now)
    require(approved <= starts <= current < expires, "execution authorization is future, expired, inverted, or outside its time window")
    require(authorization["decision"] == "approved" and authorization["explicit_human_approval"] is True, "execution authorization lacks an explicit human approved decision")
    profile = _exact(authorization["profile"], {"profile_id", "profile_sha256", "backend_kind"}, "authorization profile")
    _identifier(profile["profile_id"], "authorization.profile.profile_id")
    _sha(profile["profile_sha256"], "authorization.profile.profile_sha256")
    require(isinstance(profile["backend_kind"], str) and profile["backend_kind"] in BACKENDS, "authorization backend is unsupported")
    transport = _exact(authorization["transport"], {"identity_binding_sha256", "hop_count"}, "authorization transport")
    _sha(transport["identity_binding_sha256"], "transport.identity_binding_sha256")
    require(transport["hop_count"] == (2 if profile["backend_kind"] == "legacy_rtwin_pbs" else 1), "authorization transport hop count differs from backend")
    target = _exact(authorization["target"], {"target_kind", "effective_target_identity_sha256"}, "authorization target")
    require(target["target_kind"] == "profile_transport_identity", "authorization target kind changed")
    _sha(target["effective_target_identity_sha256"], "target.effective_target_identity_sha256")
    _validate_workspace(authorization["workspace_binding"])
    _validate_runtime(authorization["runtime_binding"])
    _validate_resources(authorization["resources"], "authorization.resources")
    _validate_scientific_ref(authorization["scientific_owner_receipt"])
    _validate_resource_chain(authorization["resource_chain"])
    _validate_execution(authorization["execution"])
    _validate_attestation_chain(
        authorization["identity_attestation"],
        backend_kind=profile["backend_kind"],
        authorization_window=(starts, expires),
        now=current,
    )
    require(authorization["revocation"] == {"revoked": False, "revoked_at": None, "reason": None}, "execution authorization is revoked or revocation state is malformed")
    require(authorization["consumption"] == {"single_use": True, "consumed": False}, "execution authorization must be active, unconsumed, and single-use")
    authorizations = authorization["authorizations"]
    expected_operations = ("create_fresh_workspace_once", "transfer_exact_bundle_once", "pbs_submit_once")
    require(isinstance(authorizations, list) and len(authorizations) == len(expected_operations), "authorizations must contain the exact three one-time operations")
    operation_scopes: list[str] = []
    for index, operation_name in enumerate(expected_operations):
        operation = _exact(authorizations[index], {"operation", "occurrence_limit", "automatic_retry", "scope_sha256"}, f"authorization operation {index}")
        operation_scope = _sha(operation["scope_sha256"], f"authorization operation {index}.scope_sha256")
        operation_scopes.append(operation_scope)
        require({key: value for key, value in operation.items() if key != "scope_sha256"} == {
            "operation": operation_name,
            "occurrence_limit": 1,
            "automatic_retry": False,
        }, f"authorization operation {index} is not the exact closed permission")
    expected_scope = _scope_sha256(authorization)
    require(hmac.compare_digest(_sha(authorization["scope_sha256"], "scope_sha256"), expected_scope), "execution authorization scope_sha256 mismatch")
    require(all(hmac.compare_digest(value, expected_scope) for value in operation_scopes), "authorization operation scope differs from full approved scope")
    _verify_self_hash(authorization, "authorization_payload_sha256", "execution authorization")
    return copy.deepcopy(authorization)


def validate_registry_snapshot(document: Any, *, now: str | datetime) -> dict[str, Any]:
    registry = _exact(document, {
        "schema", "snapshot_id", "captured_at", "known_authorization_ids",
        "consumed_authorization_ids", "known_attestation_nonces", "immutable",
        "offline_snapshot_only", "registry_payload_sha256",
    }, "authorization registry snapshot")
    require(registry["schema"] == REGISTRY_SCHEMA, "authorization registry snapshot schema is unsupported")
    _identifier(registry["snapshot_id"], "registry.snapshot_id")
    require(_parse_time(registry["captured_at"], "registry.captured_at") <= _current_time(now), "authorization registry snapshot is future-dated")
    for field in ("known_authorization_ids", "consumed_authorization_ids"):
        values = registry[field]
        require(isinstance(values, list) and all(isinstance(item, str) for item in values), f"registry.{field} must be an array of identifiers")
        require(values == sorted(set(values)), f"registry.{field} must be unique and sorted")
        for index, value in enumerate(values):
            _identifier(value, f"registry.{field}[{index}]")
    nonces = registry["known_attestation_nonces"]
    require(isinstance(nonces, list) and all(isinstance(item, str) for item in nonces), "registry.known_attestation_nonces must be an array of nonces")
    require(nonces == sorted(set(nonces)), "registry.known_attestation_nonces must be unique and sorted")
    for index, nonce in enumerate(nonces):
        require(isinstance(nonce, str) and NONCE_RE.fullmatch(nonce) is not None, f"registry nonce {index} is malformed")
    require(set(registry["consumed_authorization_ids"]).issubset(registry["known_authorization_ids"]), "registry consumed IDs must be a subset of known IDs")
    require(registry["immutable"] is True and registry["offline_snapshot_only"] is True, "registry snapshot authority markers changed")
    _verify_self_hash(registry, "registry_payload_sha256", "authorization registry snapshot")
    return copy.deepcopy(registry)


def validate_readiness_result(document: Any) -> dict[str, Any]:
    result = _exact(document, {
        "schema", "status", "request_id", "request_payload_sha256",
        "authorization_id", "authorization_payload_sha256", "profile_id",
        "profile_sha256", "backend_kind", "input_sha256", "scientific_task_id",
        "attempt_id", "resource_gate_sha256", "registry_snapshot_sha256",
        "single_use_declared", "registry_negative_evidence_only",
        "registry_uniqueness_proven", "future_owner_replay_required",
        "atomic_consumption_required", "offline_validation_only", "live_ready",
        "calculation_ready", "network_performed", "mutation_performed",
        "submission_performed", "readiness_payload_sha256",
    }, "authorization readiness result")
    require(result["schema"] == READINESS_SCHEMA and result["status"] == "closure_valid_offline", "readiness result schema/status changed")
    for field in ("request_id", "authorization_id", "profile_id"):
        _identifier(result[field], field)
    for field in (
        "request_payload_sha256", "authorization_payload_sha256", "profile_sha256",
        "input_sha256", "resource_gate_sha256", "registry_snapshot_sha256",
    ):
        _sha(result[field], field)
    require(isinstance(result["backend_kind"], str) and result["backend_kind"] in BACKENDS, "readiness backend is unsupported")
    require(isinstance(result["scientific_task_id"], str) and TASK_RE.fullmatch(result["scientific_task_id"]) is not None, "readiness task id is malformed")
    require(isinstance(result["attempt_id"], str) and ATTEMPT_RE.fullmatch(result["attempt_id"]) is not None, "readiness attempt id is malformed")
    expected_markers = {
        "single_use_declared": True,
        "registry_negative_evidence_only": True,
        "registry_uniqueness_proven": False,
        "future_owner_replay_required": True,
        "atomic_consumption_required": True,
        "offline_validation_only": True,
        "live_ready": False,
        "calculation_ready": False,
        "network_performed": False,
        "mutation_performed": False,
        "submission_performed": False,
    }
    require(all(result[key] is expected for key, expected in expected_markers.items()), "readiness non-live markers changed")
    _verify_self_hash(result, "readiness_payload_sha256", "authorization readiness result")
    return copy.deepcopy(result)


def _load_owner(filename: str, module_name: str) -> ModuleType:
    here = Path(__file__).parent
    candidates = (
        here / filename,
        here.parent / "skills" / "auto-g16-rtwin-pbs" / "scripts" / filename,
    )
    path = next((candidate for candidate in candidates if candidate.is_file()), None)
    require(path is not None, f"required original owner is unavailable: {filename}")
    owner_dir = str(path.parent)
    inserted = owner_dir not in sys.path
    if inserted:
        sys.path.insert(0, owner_dir)
    try:
        spec = importlib.util.spec_from_file_location(module_name, path)
        require(spec is not None and spec.loader is not None, f"required original owner cannot be imported: {filename}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        if inserted:
            sys.path.remove(owner_dir)


def _read_strict_artifact(path: Path, label: str) -> tuple[dict[str, Any], bytes, str, int]:
    try:
        raw = platform_contracts._open_regular_nofollow(path.absolute())
        document = platform_contracts.strict_json_loads(raw, label=label)
    except (OSError, platform_contracts.PlatformContractError) as exc:
        raise ExecutionAuthorizationError(f"{label} cannot be loaded safely: {exc}") from exc
    require(isinstance(document, dict), f"{label} must be a JSON object")
    return document, raw, hashlib.sha256(raw).hexdigest(), len(raw)


def _read_regular_artifact_bytes(path: Path, label: str) -> tuple[bytes, str, int]:
    """Read stable no-follow bytes without imposing PR3 JSON number rules on old owners."""
    try:
        raw = platform_contracts._open_regular_nofollow(path.absolute())
    except (OSError, platform_contracts.PlatformContractError) as exc:
        raise ExecutionAuthorizationError(f"{label} cannot be loaded safely: {exc}") from exc
    require(bool(raw), f"{label} must not be empty")
    return raw, hashlib.sha256(raw).hexdigest(), len(raw)


def _load_new_contract(path: Path, validator: Any, label: str, *, now: str | datetime | None = None) -> dict[str, Any]:
    document, _, _, _ = _read_strict_artifact(path, label)
    if now is None:
        return validator(document)
    return validator(document, now=now)


def _artifact_ref(schema: str, digest: str, size: int, payload: str) -> dict[str, Any]:
    return {"schema": schema, "sha256": digest, "size_bytes": size, "payload_sha256": payload}


def _with_role(role: str, ref: dict[str, Any]) -> dict[str, Any]:
    return {"role": role, **copy.deepcopy(ref)}


def _replay_scientific_owner(input_path: Path, receipt_path: Path, work_kind: str) -> tuple[dict[str, Any], dict[str, Any]]:
    owner = _load_owner("gaussian_rtwin_pbs.py", "auto_g16_execution_authorization_scientific_owner")
    input_raw, _, _ = _read_regular_artifact_bytes(input_path, "Gaussian input")
    receipt_raw, receipt_sha, receipt_size = _read_regular_artifact_bytes(receipt_path, "scientific owner receipt")
    try:
        muted_out = io.StringIO()
        muted_err = io.StringIO()
        with redirect_stdout(muted_out), redirect_stderr(muted_err):
            report = owner.parse_gaussian(input_path.absolute())
            summary = owner.validate_input_approval(receipt_path.absolute(), input_path.absolute(), report, work_kind)
    except (SystemExit, ValueError, OSError) as exc:
        raise ExecutionAuthorizationError("original scientific owner rejected the exact input/receipt") from exc
    require(platform_contracts._open_regular_nofollow(input_path.absolute()) == input_raw, "Gaussian input bytes changed during owner replay")
    require(platform_contracts._open_regular_nofollow(receipt_path.absolute()) == receipt_raw, "scientific receipt bytes changed during owner replay")
    require(summary["status"] == "validated_exact_input_approval" and summary["no_submission_authorization"] is True, "scientific owner replay overclaimed authority")
    facts = {
        "schema": summary["schema"],
        "sha256": receipt_sha,
        "size_bytes": receipt_size,
        "payload_sha256": summary["payload_sha256"],
        "input_sha256": summary["input_sha256"],
        "work_kind": summary["work_kind"],
    }
    return facts, {"raw": input_raw, "report": report}


def validate_authorization_gate(
    *,
    request_path: Path,
    authorization_path: Path,
    profile_path: Path,
    identity_binding_path: Path,
    input_path: Path,
    scientific_receipt_path: Path,
    resource_policy_path: Path,
    scheduler_snapshot_path: Path,
    resource_gate_path: Path,
    execution_batch_path: Path,
    registry_snapshot_path: Path,
    now: str | datetime,
) -> dict[str, Any]:
    """Replay every existing owner and return only an immutable offline result."""
    request = _load_new_contract(request_path, validate_execution_request, "execution request")
    authorization = _load_new_contract(authorization_path, validate_execution_authorization, "execution authorization", now=now)
    registry = _load_new_contract(registry_snapshot_path, validate_registry_snapshot, "authorization registry snapshot", now=now)

    try:
        profile = platform_contracts.load_execution_profile(profile_path.absolute())
        identity = platform_contracts.load_transport_identity_binding(identity_binding_path.absolute())
    except (OSError, platform_contracts.PlatformContractError) as exc:
        raise ExecutionAuthorizationError(f"PR2 platform owner rejected profile/identity binding: {exc}") from exc
    require(profile["transport_identity_binding_sha256"] == identity["binding_payload_sha256"], "profile differs from the exact identity binding")
    require(profile["profile_id"] == identity["profile_id"], "profile id differs from the exact identity binding")

    input_raw, input_sha, input_size = _read_regular_artifact_bytes(input_path, "Gaussian input")
    scientific, replay = _replay_scientific_owner(input_path, scientific_receipt_path, request["work_kind"])
    require(replay["raw"] == input_raw, "scientific owner replay used different input bytes")
    require(scientific["input_sha256"] == input_sha, "scientific owner input hash differs from exact input bytes")

    resource_owner = _load_owner("resource_efficiency.py", "auto_g16_execution_authorization_resource_owner")
    batch_owner = _load_owner("execution_batch.py", "auto_g16_execution_authorization_batch_owner")
    policy_raw, policy_sha, policy_size = _read_regular_artifact_bytes(resource_policy_path, "resource policy")
    snapshot_raw, snapshot_sha, snapshot_size = _read_regular_artifact_bytes(scheduler_snapshot_path, "scheduler resource snapshot")
    gate_raw, gate_sha, gate_size = _read_regular_artifact_bytes(resource_gate_path, "resource gate")
    ledger_raw, ledger_sha, ledger_size = _read_regular_artifact_bytes(execution_batch_path, "execution batch")
    try:
        policy_doc = resource_owner.load(resource_policy_path.absolute())
        snapshot_doc = resource_owner.load(scheduler_snapshot_path.absolute())
        gate_doc = resource_owner.load(resource_gate_path.absolute())
        ledger_doc = resource_owner.load(execution_batch_path.absolute())
        policy = resource_owner.validate_policy(policy_doc)
        snapshot = resource_owner.validate_scheduler_snapshot(snapshot_doc, now=now if isinstance(now, str) else now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        gate = resource_owner._validate_gate_binding(gate_doc, allow_historical=False)
        ledger = resource_owner.validate_ledger(ledger_doc)
    except (ValueError, TypeError) as exc:
        raise ExecutionAuthorizationError(f"original resource/batch owner rejected closure: {exc}") from exc
    require(platform_contracts._open_regular_nofollow(resource_policy_path.absolute()) == policy_raw, "resource policy bytes changed during replay")
    require(platform_contracts._open_regular_nofollow(scheduler_snapshot_path.absolute()) == snapshot_raw, "scheduler snapshot bytes changed during replay")
    require(platform_contracts._open_regular_nofollow(resource_gate_path.absolute()) == gate_raw, "resource gate bytes changed during replay")
    require(platform_contracts._open_regular_nofollow(execution_batch_path.absolute()) == ledger_raw, "execution batch bytes changed during replay")

    policy_ref = _artifact_ref(policy["schema"], policy_sha, policy_size, policy["payload_sha256"])
    snapshot_ref = _artifact_ref(snapshot["schema"], snapshot_sha, snapshot_size, snapshot["payload_sha256"])
    gate_ref = _artifact_ref(gate["schema"], gate_sha, gate_size, gate["gate_sha256"])
    ledger_ref = _artifact_ref(ledger["schema"], ledger_sha, ledger_size, ledger["ledger_sha256"])
    actual_upstream = [
        _with_role("scientific_owner_receipt", {key: scientific[key] for key in ("schema", "sha256", "size_bytes", "payload_sha256")}),
        _with_role("resource_policy", policy_ref),
        _with_role("scheduler_resource_snapshot", snapshot_ref),
        _with_role("resource_gate", gate_ref),
        _with_role("execution_batch", ledger_ref),
    ]

    require(request["request_id"] == authorization["request"]["request_id"], "authorization request_id mismatch")
    require(request["request_payload_sha256"] == authorization["request"]["request_payload_sha256"], "authorization request hash mismatch")
    require(request["input"] == {"sha256": input_sha, "size_bytes": input_size}, "request input binding mismatch")
    require(request["upstream_artifact_refs"] == actual_upstream, "request upstream artifact closure mismatch")
    require(request["profile_id"] == profile["profile_id"] == authorization["profile"]["profile_id"], "profile id closure mismatch")
    require(request["profile_sha256"] == profile["profile_payload_sha256"] == authorization["profile"]["profile_sha256"], "profile hash closure mismatch")
    require(request["backend_kind"] == profile["backend_kind"] == authorization["profile"]["backend_kind"], "backend closure mismatch")
    require(set(request["required_capabilities"]).issubset(profile["declared_capabilities"]), "profile lacks a required capability")
    require(authorization["transport"] == {
        "identity_binding_sha256": identity["binding_payload_sha256"],
        "hop_count": len(identity["hops"]),
    }, "transport binding closure mismatch")
    require(authorization["target"]["effective_target_identity_sha256"] == identity["hops"][-1]["effective_target_identity_sha256"], "exact target identity closure mismatch")
    require(authorization["workspace_binding"]["root_policy"] == profile["workspace_policy"]["root_policy"], "workspace root policy differs from profile")
    require(authorization["workspace_binding"]["allowed_root"] == profile["workspace_policy"]["allowed_root"], "workspace allowed root differs from profile")
    for marker in ("fresh_project_required", "no_overwrite", "no_symlink", "no_delete"):
        require(authorization["workspace_binding"][marker] is profile["workspace_policy"][marker], f"workspace {marker} differs from profile")
    runtime = authorization["runtime_binding"]
    require(runtime["invocation_mode"] == profile["gaussian_runtime"]["invocation_mode"], "runtime invocation differs from profile")
    require(runtime["executable_ref_sha256"] == _scalar_sha256(profile["gaussian_runtime"]["executable_ref"]), "runtime executable reference digest differs from profile")
    require(runtime["input_sha256"] == input_sha, "runtime input hash mismatch")
    require(runtime["workspace_binding_sha256"] == authorization["workspace_binding"]["workspace_binding_sha256"], "runtime/workspace binding mismatch")
    require(runtime["resources"] == authorization["resources"] == request["proposed_resources"], "request/authorization/runtime resource tuple mismatch")
    require(authorization["scientific_owner_receipt"] == scientific, "authorization scientific owner receipt closure mismatch")
    require(authorization["scientific_owner_receipt"]["work_kind"] == request["work_kind"], "scientific work_kind closure mismatch")
    require(authorization["resource_chain"] == {
        "policy": policy_ref,
        "scheduler_snapshot": snapshot_ref,
        "gate": gate_ref,
        "execution_batch": ledger_ref,
    }, "authorization resource chain mismatch")

    execution = authorization["execution"]
    require(execution["scientific_task_id"] == request["scientific_task_id"], "scientific task closure mismatch")
    require(execution["attempt_id"] == request["attempt_id"], "attempt closure mismatch")
    require(execution["idempotency_key"] == request["idempotency_key"], "idempotency closure mismatch")
    require(execution["batch_id"] == ledger["batch"]["batch_id"], "batch id closure mismatch")
    require(execution["review_sha256"] == ledger["batch"]["review_sha256"], "batch review closure mismatch")
    task = next((item for item in ledger["tasks"] if item["scientific_task_id"] == execution["scientific_task_id"]), None)
    require(task is not None and task["identity"]["relevant_input_sha256"] == input_sha, "execution task/input is absent from reviewed batch")
    derived_attempt = batch_owner.attempt_id_for(execution["batch_id"], execution["idempotency_key"])
    require(execution["attempt_id"] == derived_attempt, "attempt id differs from batch/idempotency owner")
    require(not any(item["attempt_id"] == execution["attempt_id"] for item in ledger["attempts"]), "execution attempt is already present in the ledger")
    require(gate["execution_scope"] == {
        "scientific_task_id": execution["scientific_task_id"],
        "attempt_id": execution["attempt_id"],
        "project": authorization["workspace_binding"]["project"],
        "input_sha256": input_sha,
    }, "resource gate execution scope mismatch")
    gate_tuple = {key: gate["requested_resources"][key] for key in ("resource_tier", "cores", "memory_gb", "walltime_seconds")}
    expected_tuple = {
        "resource_tier": authorization["resources"]["tier"],
        "cores": authorization["resources"]["cores"],
        "memory_gb": authorization["resources"]["memory_gb"],
        "walltime_seconds": authorization["resources"]["walltime_seconds"],
    }
    require(gate_tuple == expected_tuple, "resource gate exact tuple mismatch")
    require(gate["policy_id"] == policy["policy_id"] and gate["policy_sha256"] == policy["payload_sha256"], "resource gate/policy binding mismatch")
    require(gate["resource_state_sha256"] == ledger["resource_state_sha256"] and gate["resource_state_revision"] == ledger["resource_state_revision"], "resource gate is stale relative to execution batch")
    require(gate["scheduler_snapshot"] == {
        "snapshot_id": snapshot["snapshot_id"],
        "payload_sha256": snapshot["payload_sha256"],
        "artifact_sha256": snapshot_sha,
        "artifact_size": snapshot_size,
        "collected_at": snapshot["collected_at"],
        "source": snapshot["source"],
        "freshness": snapshot["freshness"]["classification"],
        "transport_classification": snapshot["transport"]["classification"],
    }, "resource gate scheduler snapshot binding mismatch")

    require(authorization["authorization_id"] not in registry["known_authorization_ids"], "authorization_id already exists in caller registry snapshot")
    request_nonces = [item["request_nonce"] for item in authorization["identity_attestation"]["operations"]]
    require(not set(request_nonces).intersection(registry["known_attestation_nonces"]), "identity attestation nonce already exists in caller registry snapshot")

    result = {
        "schema": READINESS_SCHEMA,
        "status": "closure_valid_offline",
        "request_id": request["request_id"],
        "request_payload_sha256": request["request_payload_sha256"],
        "authorization_id": authorization["authorization_id"],
        "authorization_payload_sha256": authorization["authorization_payload_sha256"],
        "profile_id": profile["profile_id"],
        "profile_sha256": profile["profile_payload_sha256"],
        "backend_kind": profile["backend_kind"],
        "input_sha256": input_sha,
        "scientific_task_id": execution["scientific_task_id"],
        "attempt_id": execution["attempt_id"],
        "resource_gate_sha256": gate["gate_sha256"],
        "registry_snapshot_sha256": registry["registry_payload_sha256"],
        "single_use_declared": True,
        "registry_negative_evidence_only": True,
        "registry_uniqueness_proven": False,
        "future_owner_replay_required": True,
        "atomic_consumption_required": True,
        "offline_validation_only": True,
        "live_ready": False,
        "calculation_ready": False,
        "network_performed": False,
        "mutation_performed": False,
        "submission_performed": False,
        "readiness_payload_sha256": "",
    }
    return validate_readiness_result(finalize(result, "readiness_payload_sha256"))
