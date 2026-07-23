#!/usr/bin/env python3
"""Own the offline-only Auto-G16 v2.6 transport-authority closure.

This additive owner never opens a connection or performs a transport action.
It preserves the published PR2/PR3 ``/1`` owners as historical replay owners
and validates the successor profile, permanently non-authorizing request,
exact authorization closure, actual Stage A/B receipts, and read-only
second-hop identity-handshake observation/receipt chain.
"""

from __future__ import annotations

import copy
import hashlib
import hmac
import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any, Sequence, TypedDict


PROFILE_SCHEMA_V2 = "auto-g16-execution-profile/2"
REQUEST_SCHEMA_V2 = "auto-g16-execution-request/2"
AUTHORIZATION_SCHEMA_V2 = "auto-g16-execution-authorization/2"
HANDSHAKE_REQUEST_SCHEMA = "auto-g16-nested-hop-identity-handshake-request/1"
HANDSHAKE_OBSERVATION_SCHEMA = "auto-g16-nested-hop-identity-handshake-observation/1"
HANDSHAKE_RECEIPT_SCHEMA = "auto-g16-nested-hop-identity-handshake-receipt/1"
HANDSHAKE_OPERATION_VERSION = "nested-hop-host-key-identity-handshake/1"
SUCCESSOR_CLOSURE_SEAL_SCHEMA = "auto-g16-successor-closure-seal/1"
ADAPTER_OWNER = "auto-g16-rtwin-pbs"
FIRST_HOP_CONFIG_REF = "rtwin_ssh_config"
SECOND_HOP_CONFIG_REF = "windows_server_config"
MAX_WINDOW_SECONDS = 300
OPERATION_CONTRACTS = (
    ("attest_first_hop_once", "first-hop-identity-attestation/1", ["read_local_identity_sources", "network_identity_handshake"]),
    ("attest_nested_hop_once", "nested-hop-identity-attestation/1", ["read_remote_identity_source_hashes"]),
    ("handshake_nested_hop_identity_once", HANDSHAKE_OPERATION_VERSION, ["network_identity_handshake"]),
)


class TransportAuthorityError(ValueError):
    """The successor transport-authority closure is not exact and closed."""


_SUCCESSOR_CLOSURE_SEAL = object()


class SealedSuccessorClosure:
    """Owner-issued immutable handle proving the full successor replay ran."""

    __slots__ = ("_canonical_payload", "_payload_sha256")

    def __init__(self, canonical_payload: bytes, payload_sha256: str, *, seal: object) -> None:
        if seal is not _SUCCESSOR_CLOSURE_SEAL:
            raise TypeError("successor closure handles can only be issued by the owner")
        object.__setattr__(self, "_canonical_payload", canonical_payload)
        object.__setattr__(self, "_payload_sha256", payload_sha256)

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError("successor closure handles are immutable")

    @property
    def payload_sha256(self) -> str:
        return self._payload_sha256


def _load_owner(filename: str, owner_name: str) -> ModuleType:
    path = Path(__file__).resolve().with_name(filename)
    if not path.is_file() or path.is_symlink():
        raise ImportError(f"{owner_name} owner is unavailable")
    name = f"_auto_g16_transport_authority_{owner_name}_{hashlib.sha256(str(path).encode()).hexdigest()[:16]}"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"{owner_name} owner cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(name, None)
    if Path(module.__file__).resolve() != path.resolve():
        raise ImportError(f"{owner_name} owner origin changed")
    return module


platform_contracts = _load_owner("platform_contracts.py", "platform_contracts")
execution_authorization = _load_owner("execution_authorization.py", "execution_authorization")


class ExecutionProfileV2(TypedDict):
    schema: str
    profile_id: str
    backend_kind: str
    transport_config_bindings: dict[str, Any]
    transport_identity_binding_sha256: str
    scheduler_dialect: str
    gaussian_runtime: dict[str, str]
    workspace_policy: dict[str, Any]
    resource_catalog: dict[str, Any]
    declared_capabilities: list[str]
    profile_payload_sha256: str


def require(condition: bool, message: str) -> None:
    if not condition:
        raise TransportAuthorityError(message)


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
    require(platform_contracts.ID_RE.fullmatch(text) is not None, f"{label} is not a portable identifier")
    return text


def _sha(value: Any, label: str) -> str:
    text = _text(value, label)
    require(platform_contracts.SHA_RE.fullmatch(text) is not None and text != "0" * 64, f"{label} must be a nonzero lowercase SHA-256")
    return text


def _nonce(value: Any, label: str) -> str:
    text = _text(value, label)
    require(platform_contracts.NONCE_RE.fullmatch(text) is not None, f"{label} must be 32-128 lowercase hex characters")
    return text


def _time(value: Any, label: str) -> datetime:
    text = _text(value, label)
    require(platform_contracts.RFC3339_RE.fullmatch(text) is not None, f"{label} must be second-precision RFC3339 UTC")
    try:
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise TransportAuthorityError(f"{label} is not a real UTC timestamp") from exc


def _current(now: str | datetime) -> datetime:
    if isinstance(now, str):
        return _time(now, "now")
    require(isinstance(now, datetime) and now.tzinfo is not None, "now must be timezone-aware")
    return now.astimezone(timezone.utc)


def finalize(document: dict[str, Any], self_field: str) -> dict[str, Any]:
    return platform_contracts.finalize(document, self_field)


def _verify_hash(document: dict[str, Any], field: str, label: str) -> None:
    actual = _sha(document.get(field), field)
    expected = platform_contracts.payload_sha256(document, field)
    require(hmac.compare_digest(actual, expected), f"{label} {field} mismatch")


def _constant_fields_equal(
    actual: dict[str, Any], expected: dict[str, Any], fields: Sequence[str],
) -> bool:
    """Compare closed text identity/digest bindings without timing shortcuts."""
    matches = 1
    for field in fields:
        actual_value = actual.get(field)
        expected_value = expected.get(field)
        strings = isinstance(actual_value, str) and isinstance(expected_value, str)
        matches &= int(strings)
        matches &= int(hmac.compare_digest(
            actual_value if isinstance(actual_value, str) else "",
            expected_value if isinstance(expected_value, str) else "",
        ))
    return bool(matches)


def adapter_config_reference_sha256(*, hop_role: str, private_reference: str) -> str:
    """Hash an adapter-private reference without serializing its plaintext."""
    require(hop_role in {"first_hop", "second_hop"}, "adapter config hop role is unsupported")
    reference = _text(private_reference, "adapter-private config reference")
    projection = {
        "domain": "auto-g16-adapter-config-reference/1",
        "adapter_owner": ADAPTER_OWNER,
        "hop_role": hop_role,
        "private_reference": reference,
    }
    return hashlib.sha256(platform_contracts.canonical_bytes(projection)).hexdigest()


def build_transport_config_bindings(*, first_hop_ref_sha256: str, second_hop_ref_sha256: str) -> dict[str, Any]:
    document = {
        "adapter_owner": ADAPTER_OWNER,
        "first_hop": {
            "hop_role": "first_hop",
            "adapter_config_ref": FIRST_HOP_CONFIG_REF,
            "adapter_config_ref_sha256": first_hop_ref_sha256,
        },
        "second_hop": {
            "hop_role": "second_hop",
            "adapter_config_ref": SECOND_HOP_CONFIG_REF,
            "adapter_config_ref_sha256": second_hop_ref_sha256,
        },
        "bindings_payload_sha256": "",
    }
    return validate_transport_config_bindings(finalize(document, "bindings_payload_sha256"))


def validate_transport_config_bindings(value: Any) -> dict[str, Any]:
    bindings = _exact(value, {"adapter_owner", "first_hop", "second_hop", "bindings_payload_sha256"}, "transport config bindings")
    require(bindings["adapter_owner"] == ADAPTER_OWNER, "transport config adapter owner changed")
    expected = (
        ("first_hop", FIRST_HOP_CONFIG_REF),
        ("second_hop", SECOND_HOP_CONFIG_REF),
    )
    for field, logical_ref in expected:
        item = _exact(bindings[field], {"hop_role", "adapter_config_ref", "adapter_config_ref_sha256"}, f"transport config {field}")
        require(item["hop_role"] == field, f"transport config {field} role changed")
        require(item["adapter_config_ref"] == logical_ref, f"transport config {field} logical reference changed")
        _sha(item["adapter_config_ref_sha256"], f"transport config {field} digest")
    projected = platform_contracts.canonical_bytes(bindings).decode("utf-8").lower()
    for forbidden in ("/" + "users/", "c:\\\\", "hostname", "username", "identityfile", "known_hosts", "fingerprint"):
        require(forbidden not in projected, "transport config bindings contain private identity material")
    _verify_hash(bindings, "bindings_payload_sha256", "transport config bindings")
    return copy.deepcopy(bindings)


def build_execution_profile_v2(
    *, profile_id: str, identity_binding: Any, transport_config_bindings: Any,
    declared_capabilities: Sequence[str] | None = None, executable_ref: str = "g16",
) -> ExecutionProfileV2:
    identity = platform_contracts.validate_transport_identity_binding(identity_binding)
    require(identity["profile_id"] == profile_id and len(identity["hops"]) == 2, "profile /2 requires the exact legacy two-hop identity binding")
    bindings = validate_transport_config_bindings(transport_config_bindings)
    document = {
        "schema": PROFILE_SCHEMA_V2,
        "profile_id": profile_id,
        "backend_kind": "legacy_rtwin_pbs",
        "transport_config_bindings": bindings,
        "transport_identity_binding_sha256": identity["binding_payload_sha256"],
        "scheduler_dialect": platform_contracts.SCHEDULER_DIALECT,
        "gaussian_runtime": {"invocation_mode": "legacy_stdin", "executable_ref": executable_ref},
        "workspace_policy": platform_contracts._workspace_policy(),
        "resource_catalog": platform_contracts.build_resource_catalog(),
        "declared_capabilities": list(declared_capabilities) if declared_capabilities is not None else sorted(platform_contracts.DECLARED_CAPABILITIES),
        "profile_payload_sha256": "",
    }
    return validate_execution_profile_v2(finalize(document, "profile_payload_sha256"))


def validate_execution_profile_v2(value: Any) -> ExecutionProfileV2:
    profile = _exact(value, {
        "schema", "profile_id", "backend_kind", "transport_config_bindings",
        "transport_identity_binding_sha256", "scheduler_dialect", "gaussian_runtime",
        "workspace_policy", "resource_catalog", "declared_capabilities", "profile_payload_sha256",
    }, "execution profile /2")
    require(profile["schema"] == PROFILE_SCHEMA_V2, "execution profile successor schema is unsupported")
    _identifier(profile["profile_id"], "profile_id")
    require(profile["backend_kind"] == "legacy_rtwin_pbs", "execution profile /2 is restricted to the legacy two-hop backend")
    validate_transport_config_bindings(profile["transport_config_bindings"])
    _sha(profile["transport_identity_binding_sha256"], "transport identity binding digest")
    require(profile["scheduler_dialect"] == platform_contracts.SCHEDULER_DIALECT, "scheduler dialect is unsupported")
    runtime = _exact(profile["gaussian_runtime"], {"invocation_mode", "executable_ref"}, "Gaussian runtime")
    require(runtime["invocation_mode"] == "legacy_stdin", "Gaussian invocation mode is unsupported")
    require(platform_contracts.TOKEN_RE.fullmatch(_text(runtime["executable_ref"], "Gaussian executable reference")) is not None, "Gaussian executable reference is unsafe")
    require(profile["workspace_policy"] == platform_contracts._workspace_policy(), "workspace policy must remain fixed to SDL")
    platform_contracts.validate_resource_catalog(profile["resource_catalog"])
    capabilities = profile["declared_capabilities"]
    require(
        isinstance(capabilities, list) and bool(capabilities)
        and all(isinstance(item, str) for item in capabilities)
        and len(capabilities) == len(set(capabilities)),
        "declared capabilities must be a non-empty unique array",
    )
    require(set(capabilities).issubset(platform_contracts.DECLARED_CAPABILITIES), "profile declares an unsupported capability")
    _verify_hash(profile, "profile_payload_sha256", "execution profile /2")
    return copy.deepcopy(profile)


def _validate_operation(value: Any, *, expected: tuple[str, str, list[str]], label: str, now: datetime, outer: tuple[datetime, datetime]) -> dict[str, Any]:
    operation = _exact(value, {
        "operation", "operation_version", "request_nonce", "not_before", "expires_at",
        "allowed_read_only_side_effects", "read_only", "single_attempt", "automatic_retry", "mutation_allowed",
    }, label)
    name, version, effects = expected
    require(operation["operation"] == name and operation["operation_version"] == version, f"{label} operation/version changed")
    _nonce(operation["request_nonce"], f"{label} nonce")
    starts, expires = _time(operation["not_before"], f"{label} not_before"), _time(operation["expires_at"], f"{label} expires_at")
    require(starts < expires and (expires - starts).total_seconds() <= MAX_WINDOW_SECONDS, f"{label} time window is inverted or too wide")
    require(outer[0] <= starts <= now < expires <= outer[1], f"{label} is outside the active authorization window")
    require(operation["allowed_read_only_side_effects"] == effects, f"{label} read-only side effects changed")
    require(operation["read_only"] is True and operation["single_attempt"] is True, f"{label} must remain read-only and single-attempt")
    require(operation["automatic_retry"] is False and operation["mutation_allowed"] is False, f"{label} retry/mutation markers changed")
    return copy.deepcopy(operation)


def _validate_requested_operation(value: Any, *, expected: tuple[str, str, list[str]], label: str) -> dict[str, Any]:
    operation = _exact(value, {
        "operation", "operation_version", "request_nonce", "not_before", "expires_at",
        "allowed_read_only_side_effects", "read_only", "single_attempt", "automatic_retry", "mutation_allowed",
    }, label)
    name, version, effects = expected
    require(operation["operation"] == name and operation["operation_version"] == version, f"{label} operation/version changed")
    _nonce(operation["request_nonce"], f"{label} nonce")
    starts, expires = _time(operation["not_before"], f"{label} not_before"), _time(operation["expires_at"], f"{label} expires_at")
    require(starts < expires and (expires - starts).total_seconds() <= MAX_WINDOW_SECONDS, f"{label} time window is inverted or too wide")
    require(operation["allowed_read_only_side_effects"] == effects, f"{label} read-only side effects changed")
    require(operation["read_only"] is True and operation["single_attempt"] is True, f"{label} must remain read-only and single-attempt")
    require(operation["automatic_retry"] is False and operation["mutation_allowed"] is False, f"{label} retry/mutation markers changed")
    return copy.deepcopy(operation)


def _scope_sha256(document: dict[str, Any]) -> str:
    projection = {key: copy.deepcopy(value) for key, value in document.items() if key not in {"scope_sha256", "authorization_payload_sha256"}}
    return hashlib.sha256(platform_contracts.canonical_bytes(projection)).hexdigest()


def _request_ref(document: dict[str, Any]) -> dict[str, str]:
    return {
        "schema": document["schema"],
        "request_id": document["request_id"],
        "request_payload_sha256": document["request_payload_sha256"],
    }


def _historical_request_ref(document: dict[str, Any]) -> dict[str, str]:
    return {
        "schema": document["schema"],
        "request_id": document["request_id"],
        "request_payload_sha256": document["request_payload_sha256"],
    }


def _historical_authorization_ref(document: dict[str, Any]) -> dict[str, str]:
    return {
        "schema": document["schema"],
        "authorization_id": document["authorization_id"],
        "scope_sha256": document["scope_sha256"],
        "authorization_payload_sha256": document["authorization_payload_sha256"],
    }


def build_execution_request_v2(
    *, request_id: str, historical_request: Any, profile_v2: Any,
    identity_binding: Any, project: str, operations: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    """Build a permanent non-authorizing successor intent from reviewed artifacts."""
    historical = execution_authorization.validate_execution_request(historical_request)
    profile = validate_execution_profile_v2(profile_v2)
    identity = platform_contracts.validate_transport_identity_binding(identity_binding)
    require(
        len(identity["hops"]) == 2
        and hmac.compare_digest(profile["transport_identity_binding_sha256"], identity["binding_payload_sha256"]),
        "execution request /2 profile differs from the exact two-hop identity binding",
    )
    document = {
        "schema": REQUEST_SCHEMA_V2,
        "request_id": request_id,
        "historical_request": _historical_request_ref(historical),
        "profile": {
            "schema": profile["schema"],
            "profile_id": profile["profile_id"],
            "profile_sha256": profile["profile_payload_sha256"],
            "backend_kind": profile["backend_kind"],
        },
        "project": project,
        "transport": {
            "identity_binding_sha256": identity["binding_payload_sha256"],
            "hop_count": 2,
            "transport_config_bindings": copy.deepcopy(profile["transport_config_bindings"]),
        },
        "requested_operations": copy.deepcopy(list(operations)),
        "intent_only": True,
        "proposal_only": True,
        "no_execution_authorization": True,
        "live_actions_performed": False,
        "request_payload_sha256": "",
    }
    return validate_execution_request_v2(finalize(document, "request_payload_sha256"))


def validate_execution_request_v2(value: Any) -> dict[str, Any]:
    request = _exact(value, {
        "schema", "request_id", "historical_request", "profile", "project",
        "transport", "requested_operations", "intent_only", "proposal_only",
        "no_execution_authorization", "live_actions_performed", "request_payload_sha256",
    }, "execution request /2")
    require(request["schema"] == REQUEST_SCHEMA_V2, "execution request successor schema is unsupported")
    _identifier(request["request_id"], "request_id")
    historical = _exact(
        request["historical_request"],
        {"schema", "request_id", "request_payload_sha256"},
        "historical request provenance",
    )
    require(historical["schema"] == execution_authorization.REQUEST_SCHEMA, "historical request provenance must remain execution-request/1")
    execution_authorization._identifier(historical["request_id"], "historical request id")
    _sha(historical["request_payload_sha256"], "historical request digest")
    profile = _exact(request["profile"], {"schema", "profile_id", "profile_sha256", "backend_kind"}, "request profile")
    require(profile["schema"] == PROFILE_SCHEMA_V2 and profile["backend_kind"] == "legacy_rtwin_pbs", "execution request /2 requires legacy execution-profile/2")
    _identifier(profile["profile_id"], "request profile id")
    _sha(profile["profile_sha256"], "request profile digest")
    project = _text(request["project"], "request project")
    require(execution_authorization.PROJECT_RE.fullmatch(project) is not None, "execution request /2 project is unsafe")
    transport = _exact(request["transport"], {"identity_binding_sha256", "hop_count", "transport_config_bindings"}, "request transport")
    _sha(transport["identity_binding_sha256"], "request identity binding digest")
    require(transport["hop_count"] == 2, "execution request /2 requires exact two-hop transport")
    validate_transport_config_bindings(transport["transport_config_bindings"])
    operations = request["requested_operations"]
    require(isinstance(operations, list) and len(operations) == 3, "execution request /2 requires exactly three operations")
    for index, expected in enumerate(OPERATION_CONTRACTS):
        _validate_requested_operation(operations[index], expected=expected, label=f"requested operation {index}")
    require(
        request["intent_only"] is True and request["proposal_only"] is True
        and request["no_execution_authorization"] is True
        and request["live_actions_performed"] is False,
        "execution request /2 must remain permanently non-authorizing",
    )
    _verify_hash(request, "request_payload_sha256", "execution request /2")
    return copy.deepcopy(request)


def validate_execution_authorization_v2(value: Any, *, now: str | datetime) -> dict[str, Any]:
    fields = {
        "schema", "authorization_id", "request", "historical_execution_authorization",
        "approver", "approved_at", "not_before", "expires_at", "decision",
        "explicit_human_approval", "profile", "project", "transport", "identity_attestation",
        "authority_delta", "revocation", "consumption", "scope_sha256", "authorization_payload_sha256",
    }
    authorization = _exact(value, fields, "execution authorization /2")
    require(authorization["schema"] == AUTHORIZATION_SCHEMA_V2, "execution authorization successor schema is unsupported")
    _identifier(authorization["authorization_id"], "authorization_id")
    request = _exact(authorization["request"], {"schema", "request_id", "request_payload_sha256"}, "execution request /2 binding")
    require(request["schema"] == REQUEST_SCHEMA_V2, "authorization /2 must reference execution-request/2")
    _identifier(request["request_id"], "execution request /2 id")
    _sha(request["request_payload_sha256"], "execution request /2 payload digest")
    historical = _exact(
        authorization["historical_execution_authorization"],
        {"schema", "authorization_id", "scope_sha256", "authorization_payload_sha256"},
        "historical execution authorization provenance",
    )
    require(historical["schema"] == execution_authorization.AUTHORIZATION_SCHEMA, "historical authorization provenance must remain execution-authorization/1")
    execution_authorization._identifier(historical["authorization_id"], "historical authorization id")
    _sha(historical["scope_sha256"], "historical authorization scope digest")
    _sha(historical["authorization_payload_sha256"], "historical authorization payload digest")
    approver = _exact(authorization["approver"], {"principal_id"}, "approver")
    execution_authorization._identifier(approver["principal_id"], "approver principal")
    approved, starts, expires, current = _time(authorization["approved_at"], "approved_at"), _time(authorization["not_before"], "not_before"), _time(authorization["expires_at"], "expires_at"), _current(now)
    require(approved <= starts <= current < expires, "execution authorization /2 is outside its active window")
    require(authorization["decision"] == "approved" and authorization["explicit_human_approval"] is True, "execution authorization /2 lacks explicit human approval")
    profile = _exact(authorization["profile"], {"schema", "profile_id", "profile_sha256", "backend_kind"}, "successor profile binding")
    require(profile["schema"] == PROFILE_SCHEMA_V2 and profile["backend_kind"] == "legacy_rtwin_pbs", "authorization /2 requires legacy execution-profile/2")
    _identifier(profile["profile_id"], "profile id")
    _sha(profile["profile_sha256"], "profile digest")
    project = _text(authorization["project"], "project")
    require(execution_authorization.PROJECT_RE.fullmatch(project) is not None, "authorization /2 project is unsafe")
    transport = _exact(authorization["transport"], {"identity_binding_sha256", "hop_count", "transport_config_bindings_sha256"}, "authorization transport")
    _sha(transport["identity_binding_sha256"], "transport identity binding digest")
    require(transport["hop_count"] == 2, "authorization /2 requires exact two-hop transport")
    _sha(transport["transport_config_bindings_sha256"], "transport config bindings digest")
    chain = _exact(authorization["identity_attestation"], {"mode", "operations"}, "identity attestation")
    require(chain["mode"] == "legacy_two_stage_then_nested_handshake", "identity attestation successor mode changed")
    operations = chain["operations"]
    require(isinstance(operations, list) and len(operations) == 3, "identity attestation successor requires exactly three operations")
    for index, expected in enumerate(OPERATION_CONTRACTS):
        _validate_operation(operations[index], expected=expected, label=f"identity attestation operation {index}", now=current, outer=(starts, expires))
    require(authorization["authority_delta"] == {
        "read_only_identity_handshake_only": True,
        "stage_authorized": False,
        "submit_authorized": False,
        "cancel_authorized": False,
        "fetch_authorized": False,
        "arbitrary_command_authorized": False,
    }, "authorization /2 authority delta expanded beyond the read-only identity handshake")
    require(authorization["revocation"] == {"revoked": False, "revoked_at": None, "reason": None}, "authorization /2 is revoked or malformed")
    require(authorization["consumption"] == {"single_use": True, "consumed": False}, "authorization /2 must remain active, unconsumed, and single-use")
    require(hmac.compare_digest(_sha(authorization["scope_sha256"], "scope_sha256"), _scope_sha256(authorization)), "authorization /2 scope digest mismatch")
    _verify_hash(authorization, "authorization_payload_sha256", "execution authorization /2")
    return copy.deepcopy(authorization)


def validate_successor_closure(
    *, successor_request: Any, successor_authorization: Any,
    base_request: Any, base_authorization: Any,
    profile_v1: Any, profile_v2: Any, identity_binding: Any, now: str | datetime,
) -> SealedSuccessorClosure:
    """Replay the complete successor once and return an owner-issued seal."""
    historical_request = execution_authorization.validate_execution_request(base_request)
    base = execution_authorization.validate_execution_authorization(base_authorization, now=now)
    old_profile = platform_contracts.validate_execution_profile(profile_v1)
    new_profile = validate_execution_profile_v2(profile_v2)
    identity = platform_contracts.validate_transport_identity_binding(identity_binding)
    request = validate_execution_request_v2(successor_request)
    authorization = validate_execution_authorization_v2(successor_authorization, now=now)
    require(
        _constant_fields_equal(
            base["request"], historical_request,
            ("request_id", "request_payload_sha256"),
        ),
        "historical authorization/request binding mismatch",
    )
    require(
        request["historical_request"]["schema"] == historical_request["schema"]
        and _constant_fields_equal(
            request["historical_request"], historical_request,
            ("request_id", "request_payload_sha256"),
        ),
        "execution request /2 historical request provenance mismatch",
    )
    require(
        authorization["request"]["schema"] == request["schema"]
        and _constant_fields_equal(
            authorization["request"], request,
            ("request_id", "request_payload_sha256"),
        ),
        "authorization /2 execution-request/2 binding mismatch",
    )
    require(
        authorization["historical_execution_authorization"]["schema"] == base["schema"]
        and _constant_fields_equal(
            authorization["historical_execution_authorization"], base,
            ("authorization_id", "scope_sha256", "authorization_payload_sha256"),
        ),
        "authorization /2 historical authorization provenance mismatch",
    )
    require(authorization["approver"] == base["approver"], "successor approver differs from historical authorization")
    require(request["project"] == authorization["project"] == base["workspace_binding"]["project"], "request/authorization project closure mismatch")
    profile_ref = {
        "schema": new_profile["schema"],
        "profile_id": new_profile["profile_id"],
        "profile_sha256": new_profile["profile_payload_sha256"],
        "backend_kind": new_profile["backend_kind"],
    }
    require(
        request["profile"]["schema"] == authorization["profile"]["schema"] == profile_ref["schema"]
        and request["profile"]["backend_kind"] == authorization["profile"]["backend_kind"] == profile_ref["backend_kind"]
        and _constant_fields_equal(request["profile"], profile_ref, ("profile_id", "profile_sha256"))
        and _constant_fields_equal(authorization["profile"], profile_ref, ("profile_id", "profile_sha256")),
        "request/authorization profile closure mismatch",
    )
    common_fields = ("profile_id", "backend_kind", "scheduler_dialect", "gaussian_runtime", "workspace_policy", "resource_catalog", "declared_capabilities")
    require(all(old_profile[field] == new_profile[field] for field in common_fields), "profile /1 and /2 differ outside the transport-config closure")
    require(
        _constant_fields_equal(
            old_profile,
            new_profile,
            ("transport_identity_binding_sha256",),
        ),
        "profile /1 and /2 identity binding differs outside the transport-config closure",
    )
    require(
        hmac.compare_digest(old_profile["profile_payload_sha256"], historical_request["profile_sha256"])
        & hmac.compare_digest(old_profile["profile_payload_sha256"], base["profile"]["profile_sha256"]),
        "base PR3 closure does not bind the supplied historical profile",
    )
    require(
        len(identity["hops"]) == 2
        and hmac.compare_digest(identity["binding_payload_sha256"], new_profile["transport_identity_binding_sha256"]),
        "successor profile differs from exact two-hop identity binding",
    )
    bindings = new_profile["transport_config_bindings"]
    request_transport = {
        "identity_binding_sha256": identity["binding_payload_sha256"],
        "hop_count": 2,
        "transport_config_bindings": bindings,
    }
    authorization_transport = {
        "identity_binding_sha256": identity["binding_payload_sha256"],
        "hop_count": 2,
        "transport_config_bindings_sha256": bindings["bindings_payload_sha256"],
    }
    require(
        request["transport"]["hop_count"] == request_transport["hop_count"]
        and request["transport"]["transport_config_bindings"] == bindings
        and hmac.compare_digest(request["transport"]["identity_binding_sha256"], identity["binding_payload_sha256"]),
        "execution request /2 transport closure mismatch",
    )
    require(
        authorization["transport"]["hop_count"] == authorization_transport["hop_count"]
        and _constant_fields_equal(
            authorization["transport"], authorization_transport,
            ("identity_binding_sha256", "transport_config_bindings_sha256"),
        ),
        "authorization /2 transport closure mismatch",
    )
    require(request["requested_operations"] == authorization["identity_attestation"]["operations"], "authorization operations differ from execution-request/2")
    base_operations = base["identity_attestation"]["operations"]
    for index in (0, 1):
        successor_operation = copy.deepcopy(authorization["identity_attestation"]["operations"][index])
        successor_operation.pop("single_attempt")
        require(successor_operation == base_operations[index], f"successor operation {index} differs from the PR3 base closure")
    base_start, base_end = _time(base["not_before"], "base not_before"), _time(base["expires_at"], "base expires_at")
    require(base_start <= _time(authorization["not_before"], "successor not_before") < _time(authorization["expires_at"], "successor expires_at") <= base_end, "successor window exceeds the historical authorization")
    closure = {
        "schema": SUCCESSOR_CLOSURE_SEAL_SCHEMA,
        "successor_request": request,
        "successor_authorization": authorization,
        "base_request": historical_request,
        "base_authorization": base,
        "profile_v1": old_profile,
        "profile_v2": new_profile,
        "identity_binding": identity,
    }
    canonical_payload = platform_contracts.canonical_bytes(closure)
    payload_sha256 = hashlib.sha256(canonical_payload).hexdigest()
    return SealedSuccessorClosure(
        canonical_payload,
        payload_sha256,
        seal=_SUCCESSOR_CLOSURE_SEAL,
    )


def _consume_successor_closure(
    value: Any, *, now: str | datetime,
) -> dict[str, Any]:
    require(type(value) is SealedSuccessorClosure, "handshake authority requires an owner-sealed successor closure")
    canonical_payload = value._canonical_payload
    require(isinstance(canonical_payload, bytes), "successor closure canonical payload is unavailable")
    actual_digest = hashlib.sha256(canonical_payload).hexdigest()
    require(
        hmac.compare_digest(actual_digest, value.payload_sha256),
        "successor closure canonical digest mismatch",
    )
    closure = platform_contracts.strict_json_loads(
        canonical_payload,
        label="owner-sealed successor closure",
    )
    closure = _exact(closure, {
        "schema", "successor_request", "successor_authorization",
        "base_request", "base_authorization", "profile_v1", "profile_v2",
        "identity_binding",
    }, "owner-sealed successor closure")
    require(closure["schema"] == SUCCESSOR_CLOSURE_SEAL_SCHEMA, "successor closure seal schema is unsupported")
    replayed = validate_successor_closure(
        successor_request=closure["successor_request"],
        successor_authorization=closure["successor_authorization"],
        base_request=closure["base_request"],
        base_authorization=closure["base_authorization"],
        profile_v1=closure["profile_v1"],
        profile_v2=closure["profile_v2"],
        identity_binding=closure["identity_binding"],
        now=now,
    )
    require(
        hmac.compare_digest(replayed.payload_sha256, value.payload_sha256)
        and hmac.compare_digest(replayed._canonical_payload, canonical_payload),
        "successor closure replay differs from its canonical seal",
    )
    return closure


def build_nested_handshake_request(
    *, profile_v2: Any, identity_binding: Any,
    first_hop_request: Any, first_hop_receipt: Any,
    nested_hop_request: Any, nested_hop_receipt: Any,
    request_nonce: str, issued_at: str, expires_at: str,
) -> dict[str, Any]:
    stages = validate_stage_receipt_chain(
        profile_v2=profile_v2,
        identity_binding=identity_binding,
        first_hop_request=first_hop_request,
        first_hop_receipt=first_hop_receipt,
        nested_hop_request=nested_hop_request,
        nested_hop_receipt=nested_hop_receipt,
        now=issued_at,
    )
    return validate_nested_handshake_request({
        "schema": HANDSHAKE_REQUEST_SCHEMA,
        "profile_sha256": stages["profile"]["profile_payload_sha256"],
        "transport_identity_binding_sha256": stages["identity_binding"]["binding_payload_sha256"],
        "transport_config_bindings_sha256": stages["profile"]["transport_config_bindings"]["bindings_payload_sha256"],
        "first_hop_receipt_sha256": stages["first_hop_receipt"]["receipt_payload_sha256"],
        "nested_hop_receipt_sha256": stages["nested_hop_receipt"]["receipt_payload_sha256"],
        "request_nonce": request_nonce,
        "issued_at": issued_at,
        "expires_at": expires_at,
        "operation_version": HANDSHAKE_OPERATION_VERSION,
        "allowed_read_only_side_effects": ["network_identity_handshake"],
        "read_only": True, "single_attempt": True, "automatic_retry": False, "mutation_allowed": False,
    }, now=issued_at)


def validate_nested_handshake_request(value: Any, *, now: str | datetime) -> dict[str, Any]:
    request = _exact(value, {
        "schema", "profile_sha256", "transport_identity_binding_sha256", "transport_config_bindings_sha256",
        "first_hop_receipt_sha256", "nested_hop_receipt_sha256", "request_nonce", "issued_at", "expires_at",
        "operation_version", "allowed_read_only_side_effects", "read_only", "single_attempt", "automatic_retry", "mutation_allowed",
    }, "nested-hop handshake request")
    require(request["schema"] == HANDSHAKE_REQUEST_SCHEMA, "nested-hop handshake request schema is unsupported")
    for field in ("profile_sha256", "transport_identity_binding_sha256", "transport_config_bindings_sha256", "first_hop_receipt_sha256", "nested_hop_receipt_sha256"):
        _sha(request[field], field)
    operation = {
        "operation": "handshake_nested_hop_identity_once",
        "operation_version": request["operation_version"],
        "request_nonce": request["request_nonce"],
        "not_before": request["issued_at"],
        "expires_at": request["expires_at"],
        "allowed_read_only_side_effects": request["allowed_read_only_side_effects"],
        "read_only": request["read_only"],
        "single_attempt": request["single_attempt"],
        "automatic_retry": request["automatic_retry"],
        "mutation_allowed": request["mutation_allowed"],
    }
    _validate_operation(
        operation,
        expected=("handshake_nested_hop_identity_once", HANDSHAKE_OPERATION_VERSION, ["network_identity_handshake"]),
        label="nested-hop handshake request",
        now=_current(now),
        outer=(_time(request["issued_at"], "issued_at"), _time(request["expires_at"], "expires_at")),
    )
    return copy.deepcopy(request)


def validate_stage_receipt_chain(
    *, profile_v2: Any, identity_binding: Any,
    first_hop_request: Any, first_hop_receipt: Any,
    nested_hop_request: Any, nested_hop_receipt: Any,
    now: str | datetime,
) -> dict[str, Any]:
    """Owner-validate both actual PR2 stage receipts and compute their digests."""
    profile = validate_execution_profile_v2(profile_v2)
    binding = platform_contracts.validate_transport_identity_binding(identity_binding)
    require(len(binding["hops"]) == 2, "Stage A/B receipt replay requires exact two-hop identity binding")
    first = platform_contracts.validate_first_hop_receipt(
        first_hop_receipt,
        request=first_hop_request,
        binding=binding,
        now=now,
    )
    nested = platform_contracts.validate_nested_hop_receipt(
        nested_hop_receipt,
        request=nested_hop_request,
        binding=binding,
        first_hop_receipt=first,
        first_hop_request=first_hop_request,
        now=now,
    )
    for label, receipt in (("Stage A", first), ("Stage B", nested)):
        require(
            hmac.compare_digest(receipt["profile_sha256"], profile["profile_payload_sha256"]),
            f"{label} receipt profile differs from execution-profile/2",
        )
        require(
            hmac.compare_digest(receipt["transport_identity_binding_sha256"], binding["binding_payload_sha256"]),
            f"{label} receipt identity binding differs from the exact two-hop binding",
        )
    require(
        hmac.compare_digest(nested["first_hop_receipt_sha256"], first["receipt_payload_sha256"]),
        "Stage B receipt does not bind the owner-validated Stage A receipt",
    )
    return {
        "profile": profile,
        "identity_binding": binding,
        "first_hop_request": platform_contracts.validate_first_hop_request(first_hop_request, now=now),
        "first_hop_receipt": first,
        "nested_hop_request": platform_contracts.validate_nested_hop_request(nested_hop_request, now=now),
        "nested_hop_receipt": nested,
    }


def validate_nested_handshake_observation(
    value: Any, *, request: Any, profile_v2: Any, identity_binding: Any,
    first_hop_request: Any, first_hop_receipt: Any,
    nested_hop_request: Any, nested_hop_receipt: Any,
    now: str | datetime,
) -> dict[str, Any]:
    """Validate a future-adapter observation; never manufacture verified evidence."""
    observation = _exact(value, {
        "schema", "profile_sha256", "transport_identity_binding_sha256",
        "transport_config_bindings_sha256", "first_hop_receipt_sha256",
        "nested_hop_receipt_sha256", "second_hop_identity_sha256",
        "approved_host_key_evidence_sha256", "observed_fingerprint_evidence_sha256",
        "request_nonce", "issued_at", "expires_at", "operation_version",
        "classification", "read_only", "single_attempt", "automatic_retry",
        "mutation_allowed", "no_execution_authorization",
        "observation_payload_sha256",
    }, "nested-hop handshake observation")
    checked = validate_nested_handshake_request(request, now=now)
    stages = validate_stage_receipt_chain(
        profile_v2=profile_v2,
        identity_binding=identity_binding,
        first_hop_request=first_hop_request,
        first_hop_receipt=first_hop_receipt,
        nested_hop_request=nested_hop_request,
        nested_hop_receipt=nested_hop_receipt,
        now=now,
    )
    profile = stages["profile"]
    binding = stages["identity_binding"]
    stage_digests = {
        "first_hop_receipt_sha256": stages["first_hop_receipt"]["receipt_payload_sha256"],
        "nested_hop_receipt_sha256": stages["nested_hop_receipt"]["receipt_payload_sha256"],
    }
    expected = {
        "profile_sha256": profile["profile_payload_sha256"],
        "transport_identity_binding_sha256": binding["binding_payload_sha256"],
        "transport_config_bindings_sha256": profile["transport_config_bindings"]["bindings_payload_sha256"],
        **stage_digests,
        "second_hop_identity_sha256": platform_contracts._hop_identity_sha256(binding["hops"][1]),
        "approved_host_key_evidence_sha256": binding["hops"][1]["host_key_evidence_sha256"],
        "request_nonce": checked["request_nonce"],
        "issued_at": checked["issued_at"],
        "expires_at": checked["expires_at"],
        "operation_version": checked["operation_version"],
    }
    require(observation["schema"] == HANDSHAKE_OBSERVATION_SCHEMA and observation["classification"] == "observed", "nested-hop handshake observation is unsupported")
    for field, expected_value in expected.items():
        require(
            hmac.compare_digest(_text(observation[field], field), expected_value),
            f"nested-hop handshake observation {field} mismatch",
        )
    observed_fingerprint = _sha(
        observation["observed_fingerprint_evidence_sha256"],
        "observed fingerprint evidence digest",
    )
    require(
        hmac.compare_digest(
            observed_fingerprint,
            expected["approved_host_key_evidence_sha256"],
        ),
        "observed fingerprint evidence differs from approved second-hop host-key evidence",
    )
    for field, expected_value in stage_digests.items():
        require(hmac.compare_digest(checked[field], expected_value), f"nested-hop handshake request {field} differs from owner-computed stage receipt digest")
    require(
        observation["read_only"] is True and observation["single_attempt"] is True
        and observation["automatic_retry"] is False and observation["mutation_allowed"] is False,
        "nested-hop handshake observation safety markers changed",
    )
    require(observation["no_execution_authorization"] is True, "nested-hop handshake observation must remain non-authorizing")
    _verify_hash(observation, "observation_payload_sha256", "nested-hop handshake observation")
    return copy.deepcopy(observation)


def build_nested_handshake_receipt(
    *, request: Any, observation: Any, profile_v2: Any, identity_binding: Any,
    first_hop_request: Any, first_hop_receipt: Any,
    nested_hop_request: Any, nested_hop_receipt: Any,
) -> dict[str, Any]:
    checked = validate_nested_handshake_request(request, now=request.get("issued_at") if isinstance(request, dict) else "")
    observed = validate_nested_handshake_observation(
        observation,
        request=checked,
        profile_v2=profile_v2,
        identity_binding=identity_binding,
        first_hop_request=first_hop_request,
        first_hop_receipt=first_hop_receipt,
        nested_hop_request=nested_hop_request,
        nested_hop_receipt=nested_hop_receipt,
        now=checked["issued_at"],
    )
    document = {
        "schema": HANDSHAKE_RECEIPT_SCHEMA,
        **{key: checked[key] for key in ("profile_sha256", "transport_identity_binding_sha256", "transport_config_bindings_sha256", "first_hop_receipt_sha256", "nested_hop_receipt_sha256", "request_nonce", "issued_at", "expires_at", "operation_version")},
        "second_hop_identity_sha256": observed["second_hop_identity_sha256"],
        "observed_fingerprint_evidence_sha256": observed["observed_fingerprint_evidence_sha256"],
        "handshake_observation_sha256": observed["observation_payload_sha256"],
        "classification": "verified",
        "read_only": True, "single_attempt": True, "automatic_retry": False, "mutation_allowed": False,
        "no_execution_authorization": True,
        "receipt_payload_sha256": "",
    }
    return validate_nested_handshake_receipt(
        finalize(document, "receipt_payload_sha256"), request=checked, observation=observed,
        profile_v2=profile_v2, identity_binding=identity_binding,
        first_hop_request=first_hop_request, first_hop_receipt=first_hop_receipt,
        nested_hop_request=nested_hop_request, nested_hop_receipt=nested_hop_receipt,
        now=checked["issued_at"],
    )


def validate_nested_handshake_receipt(
    value: Any, *, request: Any, observation: Any, profile_v2: Any,
    identity_binding: Any, first_hop_request: Any, first_hop_receipt: Any,
    nested_hop_request: Any, nested_hop_receipt: Any, now: str | datetime,
) -> dict[str, Any]:
    receipt = _exact(value, {
        "schema", "profile_sha256", "transport_identity_binding_sha256", "transport_config_bindings_sha256",
        "first_hop_receipt_sha256", "nested_hop_receipt_sha256", "second_hop_identity_sha256",
        "observed_fingerprint_evidence_sha256", "handshake_observation_sha256",
        "request_nonce", "issued_at", "expires_at", "operation_version",
        "classification", "read_only", "single_attempt", "automatic_retry", "mutation_allowed",
        "no_execution_authorization", "receipt_payload_sha256",
    }, "nested-hop handshake receipt")
    checked = validate_nested_handshake_request(request, now=now)
    observed = validate_nested_handshake_observation(
        observation,
        request=checked,
        profile_v2=profile_v2,
        identity_binding=identity_binding,
        first_hop_request=first_hop_request,
        first_hop_receipt=first_hop_receipt,
        nested_hop_request=nested_hop_request,
        nested_hop_receipt=nested_hop_receipt,
        now=now,
    )
    require(receipt["schema"] == HANDSHAKE_RECEIPT_SCHEMA and receipt["classification"] == "verified", "nested-hop handshake receipt is unsupported or unverified")
    for field in ("profile_sha256", "transport_identity_binding_sha256", "transport_config_bindings_sha256", "first_hop_receipt_sha256", "nested_hop_receipt_sha256", "request_nonce", "issued_at", "expires_at", "operation_version"):
        require(hmac.compare_digest(_text(receipt[field], field), checked[field]), f"nested-hop handshake receipt {field} mismatch")
    for field in ("second_hop_identity_sha256", "observed_fingerprint_evidence_sha256"):
        require(hmac.compare_digest(_sha(receipt[field], field), observed[field]), f"nested-hop handshake receipt {field} mismatch")
    require(
        hmac.compare_digest(_sha(receipt["handshake_observation_sha256"], "handshake observation digest"), observed["observation_payload_sha256"]),
        "nested-hop handshake receipt observation digest mismatch",
    )
    require(receipt["read_only"] is True and receipt["single_attempt"] is True and receipt["automatic_retry"] is False and receipt["mutation_allowed"] is False, "nested-hop handshake receipt safety markers changed")
    require(receipt["no_execution_authorization"] is True, "nested-hop handshake receipt must remain non-authorizing")
    _verify_hash(receipt, "receipt_payload_sha256", "nested-hop handshake receipt")
    return copy.deepcopy(receipt)


def validate_handshake_authority_binding(
    *, successor_closure: Any,
    request: Any, observation: Any, receipt: Any,
    first_hop_request: Any, first_hop_receipt: Any,
    nested_hop_request: Any, nested_hop_receipt: Any,
    now: str | datetime,
) -> dict[str, Any]:
    """Consume the full sealed closure and bind all three actual operations."""
    closure = _consume_successor_closure(successor_closure, now=now)
    authority_request = closure["successor_request"]
    authorization = closure["successor_authorization"]
    profile = closure["profile_v2"]
    binding = closure["identity_binding"]
    checked_request = validate_nested_handshake_request(request, now=now)
    require(
        _constant_fields_equal(
            authorization["request"],
            authority_request,
            ("request_id", "request_payload_sha256"),
        ),
        "sealed authorization /2 does not bind its execution-request/2",
    )
    require(
        authorization["profile"] == authority_request["profile"]
        and authorization["project"] == authority_request["project"]
        and authorization["identity_attestation"]["operations"] == authority_request["requested_operations"],
        "sealed authorization /2 authority differs from execution-request/2",
    )
    stages = validate_stage_receipt_chain(
        profile_v2=profile,
        identity_binding=binding,
        first_hop_request=first_hop_request,
        first_hop_receipt=first_hop_receipt,
        nested_hop_request=nested_hop_request,
        nested_hop_receipt=nested_hop_receipt,
        now=now,
    )
    operations = authorization["identity_attestation"]["operations"]
    for index, stage_request in enumerate((
        stages["first_hop_request"],
        stages["nested_hop_request"],
    )):
        operation = operations[index]
        expected_stage = {
            "request_nonce": operation["request_nonce"],
            "issued_at": operation["not_before"],
            "expires_at": operation["expires_at"],
            "operation_version": operation["operation_version"],
            "read_only_attestation": operation["read_only"],
            "automatic_retry": operation["automatic_retry"],
        }
        for field, expected_value in expected_stage.items():
            actual_value = stage_request[field]
            matches = (
                hmac.compare_digest(actual_value, expected_value)
                if isinstance(actual_value, str) and isinstance(expected_value, str)
                else actual_value == expected_value
            )
            require(matches, f"actual Stage {'A' if index == 0 else 'B'} request differs from authorized operation {index}")
        require(
            hmac.compare_digest(stage_request["profile_sha256"], profile["profile_payload_sha256"])
            and hmac.compare_digest(
                stage_request["transport_identity_binding_sha256"],
                binding["binding_payload_sha256"],
            ),
            f"actual Stage {'A' if index == 0 else 'B'} request authority binding differs from authorized operation {index}",
        )
    operation = operations[2]
    expected = {
        "profile_sha256": authorization["profile"]["profile_sha256"],
        "transport_identity_binding_sha256": authorization["transport"]["identity_binding_sha256"],
        "transport_config_bindings_sha256": authorization["transport"]["transport_config_bindings_sha256"],
        "request_nonce": operation["request_nonce"],
        "issued_at": operation["not_before"],
        "expires_at": operation["expires_at"],
        "operation_version": operation["operation_version"],
        "allowed_read_only_side_effects": operation["allowed_read_only_side_effects"],
        "read_only": operation["read_only"],
        "single_attempt": operation["single_attempt"],
        "automatic_retry": operation["automatic_retry"],
        "mutation_allowed": operation["mutation_allowed"],
    }
    for field, expected_value in expected.items():
        actual_value = checked_request[field]
        matches = (
            hmac.compare_digest(actual_value, expected_value)
            if isinstance(actual_value, str) and isinstance(expected_value, str)
            else actual_value == expected_value
        )
        require(matches, f"nested-hop handshake request {field} differs from authorized operation")
    require(hmac.compare_digest(profile["profile_payload_sha256"], expected["profile_sha256"]), "nested-hop handshake profile differs from authorization")
    require(hmac.compare_digest(binding["binding_payload_sha256"], expected["transport_identity_binding_sha256"]), "nested-hop handshake identity binding differs from authorization")
    return validate_nested_handshake_receipt(
        receipt, request=checked_request, observation=observation, profile_v2=profile,
        identity_binding=binding, first_hop_request=first_hop_request,
        first_hop_receipt=first_hop_receipt, nested_hop_request=nested_hop_request,
        nested_hop_receipt=nested_hop_receipt, now=now,
    )


def load_contract(path: Path, validator: Any, *, now: str | datetime | None = None) -> dict[str, Any]:
    raw = platform_contracts._open_regular_nofollow(path)
    document = platform_contracts.strict_json_loads(raw, label=str(path))
    return validator(document) if now is None else validator(document, now=now)
