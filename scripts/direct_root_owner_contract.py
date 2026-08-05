#!/usr/bin/env python3
"""Own direct-backend root contracts and POSIX no-follow observation.

This module contains no SSH, PBS, transfer, submit, fetch, cancel, cleanup,
or filesystem-mutation implementation.  The backend factory has no caller
configuration: it observes only the root in an exact reviewed/hash-bound
direct profile chain and retains those same descriptors for one consumption.
"""

from __future__ import annotations

import copy
import hashlib
import hmac
import json
import os
import re
import secrets
import stat
import sys
import threading
import types
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable


MODULE_NAME = "direct_root_owner_contract"
OWNER_ID = "auto-g16-direct-workspace-policy-owner"
OWNER_VERSION = "direct-root-owner-contract/1"
PROFILE_POLICY_SCHEMA = "auto-g16-direct-profile-policy/1"
STABLE_EVIDENCE_SCHEMA = "auto-g16-stable-root-identity-evidence/1"
DIRECT_PROFILE_SCHEMA = "auto-g16-execution-profile/3"
DIRECT_AUTHORIZATION_SCHEMA = "auto-g16-execution-authorization/3"
FRESH_RECEIPT_SCHEMA = "auto-g16-fresh-root-observation-receipt/1"
FRESH_OPERATION_VERSION = "direct-root-fresh-observation/1"
BACKEND_KIND = "direct_ssh_pbs"
ROOT_POLICY = "backend_owned_reviewed_root_v1"
PATH_NORMALIZATION_VERSION = "posix-realpath-nofollow/1"
CONTAINMENT_VERSION = "descriptor-relative-containment/1"
PROJECT_GRAMMAR = "auto-g16-project-component/1"
SCRATCH_COMPONENT = "scratch"
SCHEDULER_DIALECT = "pbs_legacy_v1"
MAX_DOCUMENT_BYTES = 2 * 1024 * 1024
MAX_NESTING = 32
MAX_OBSERVED_ROOT_BYTES = 4096
MAX_OBSERVED_ROOT_COMPONENTS = 64
MAX_OBSERVED_COMPONENT_BYTES = 255

SHA_RE = re.compile(r"^[a-f0-9]{64}$")
ID_RE = re.compile(r"^[a-z][a-z0-9._-]{0,127}$")
PROJECT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")
NONCE_RE = re.compile(r"^[a-f0-9]{32,128}$")
TASK_RE = re.compile(r"^scientific-task-[a-f0-9]{64}$")
ATTEMPT_RE = re.compile(r"^qsub-attempt-[a-f0-9]{64}$")
NONNEGATIVE_DECIMAL_RE = re.compile(r"^(?:0|[1-9][0-9]*)$")
POSITIVE_DECIMAL_RE = re.compile(r"^[1-9][0-9]*$")
RFC3339_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$"
)

SAFETY = {
    "fresh_project_required": True,
    "no_overwrite": True,
    "no_symlink": True,
    "no_delete": True,
}
FRESH_RULES = {
    "operation_version": FRESH_OPERATION_VERSION,
    "single_consumption_required": True,
    "portable_receipt_authorizes_effect": False,
    "descriptor_capability_required": True,
    "descriptor_relative_operations_required": True,
    "path_reopen_allowed": False,
    "automatic_retry": False,
}
DECLARED_CAPABILITIES = (
    "direct_root_stable_identity",
    "direct_root_fresh_observation",
    "descriptor_relative_workspace_claim",
)

if globals().get("_AUTO_G16_DIRECT_ROOT_OWNER_EXECUTED", False):
    raise ImportError("direct root owner module has already executed")
_AUTO_G16_DIRECT_ROOT_OWNER_EXECUTED = True


class DirectRootOwnerError(ValueError):
    """The direct-root owner contract cannot be proved exactly offline."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DirectRootOwnerError(message)


def _rebuild_public_json(value: Any, *, depth: int = 0) -> Any:
    if depth > MAX_NESTING:
        raise DirectRootOwnerError("direct-root document exceeds nesting bound")
    if value is None or type(value) in {str, bool, int}:
        return value
    if type(value) is list:
        return [
            _rebuild_public_json(item, depth=depth + 1)
            for item in value
        ]
    if type(value) is dict:
        result: dict[str, Any] = {}
        keys_before = list(value.keys())
        for key in keys_before:
            if type(key) is not str:
                raise DirectRootOwnerError(
                    "direct-root document keys must be exact strings"
                )
            result[key] = _rebuild_public_json(
                value[key],
                depth=depth + 1,
            )
        if list(value.keys()) != keys_before:
            raise DirectRootOwnerError(
                "direct-root document changed during validation"
            )
        return result
    raise DirectRootOwnerError(
        "direct-root document accepts only exact builtin JSON values"
    )


def canonical_bytes(value: Any) -> bytes:
    rebuilt = _rebuild_public_json(value)
    try:
        text = json.dumps(
            rebuilt,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise DirectRootOwnerError(
            f"direct-root document is not canonical JSON: {exc}"
        ) from exc
    return (text + "\n").encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _exact(value: Any, fields: set[str], label: str) -> dict[str, Any]:
    _require(type(value) is dict, f"{label} must be an exact object")
    _require(set(value) == fields, f"{label} fields differ")
    return value


def _text(value: Any, label: str, pattern: re.Pattern[str] = ID_RE) -> str:
    _require(type(value) is str and pattern.fullmatch(value) is not None, f"{label} is invalid")
    return value


def _sha(value: Any, label: str, *, nonzero: bool = True) -> str:
    _require(type(value) is str and SHA_RE.fullmatch(value) is not None, f"{label} is not SHA-256")
    if nonzero:
        _require(value != "0" * 64, f"{label} must be nonzero")
    return value


def _positive_integer(value: Any, label: str) -> int:
    _require(type(value) is int and value > 0, f"{label} must be a positive integer")
    return value


def _nonnegative_decimal(value: Any, label: str) -> int:
    _require(
        type(value) is str
        and NONNEGATIVE_DECIMAL_RE.fullmatch(value) is not None,
        f"{label} must be a canonical non-negative decimal string",
    )
    return int(value)


def _positive_decimal(
    value: Any,
    label: str,
    *,
    maximum: int | None = None,
) -> int:
    _require(
        type(value) is str
        and POSITIVE_DECIMAL_RE.fullmatch(value) is not None,
        f"{label} must be a canonical positive decimal string",
    )
    parsed = int(value)
    if maximum is not None:
        _require(parsed <= maximum, f"{label} exceeds owner bound")
    return parsed


def _utc_text(value: Any, label: str) -> datetime:
    _require(type(value) is str and RFC3339_RE.fullmatch(value) is not None, f"{label} must be UTC RFC3339")
    parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    _require(parsed.tzinfo == timezone.utc, f"{label} must be UTC")
    return parsed


def _format_utc(value: datetime) -> str:
    _require(
        type(value) is datetime
        and value.tzinfo is not None
        and value.utcoffset() == timedelta(0),
        "owner clock must return timezone-aware UTC",
    )
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _absolute_root(value: Any, label: str) -> str:
    _require(type(value) is str and value.startswith("/") and value != "/", f"{label} must be an absolute non-root path")
    _require(
        "\x00" not in value
        and "\\" not in value
        and not value.endswith("/")
        and "//" not in value,
        f"{label} path syntax is unsafe",
    )
    parts = PurePosixPath(value).parts
    _require(
        parts[0] == "/"
        and len(parts) > 1
        and all(part not in {"", ".", ".."} for part in parts[1:]),
        f"{label} path components are unsafe",
    )
    return value


def _project(value: Any, label: str = "project") -> str:
    _require(
        type(value) is str and PROJECT_RE.fullmatch(value) is not None,
        f"{label} is unsafe",
    )
    return value


def _self_hash(document: dict[str, Any], field: str, label: str) -> None:
    actual = _sha(document[field], f"{label} payload hash")
    projection = copy.deepcopy(document)
    del projection[field]
    expected = digest(projection)
    _require(hmac.compare_digest(actual, expected), f"{label} payload hash differs")


def _finalize(document: dict[str, Any], field: str) -> dict[str, Any]:
    result = copy.deepcopy(document)
    result[field] = ""
    projection = copy.deepcopy(result)
    del projection[field]
    result[field] = digest(projection)
    return result


def _safety(value: Any, label: str = "safety") -> dict[str, bool]:
    obj = _exact(value, set(SAFETY), label)
    _require(obj == SAFETY, f"{label} markers differ")
    return obj


def _owner_binding(value: Any) -> dict[str, str]:
    owner = _exact(
        value,
        {"owner_id", "owner_version", "owner_source_sha256"},
        "root-policy owner",
    )
    _require(owner["owner_id"] == OWNER_ID, "root-policy owner id differs")
    _require(owner["owner_version"] == OWNER_VERSION, "root-policy owner version differs")
    _sha(owner["owner_source_sha256"], "root-policy owner source")
    return owner


def _component_chain(value: Any, label: str) -> dict[str, Any]:
    chain = _exact(
        value,
        {"canonical_root", "components", "identity_chain_sha256"},
        label,
    )
    root = _absolute_root(chain["canonical_root"], f"{label}.canonical_root")
    _require(type(chain["components"]) is list and chain["components"], f"{label}.components must be non-empty")
    expected_ordinals = list(range(len(chain["components"])))
    ordinals: list[int] = []
    for item in chain["components"]:
        component = _exact(
            item,
            {"ordinal", "component_path_sha256", "identity_sha256"},
            f"{label}.component",
        )
        ordinals.append(
            _nonnegative_decimal(
                component["ordinal"],
                f"{label}.ordinal",
            )
        )
        _sha(component["component_path_sha256"], f"{label}.component path")
        _sha(component["identity_sha256"], f"{label}.component identity")
    _require(ordinals == expected_ordinals, f"{label}.component order differs")
    expected = digest(
        {
            "schema": "auto-g16-root-component-identity-chain/1",
            "canonical_root": root,
            "components": chain["components"],
        }
    )
    _require(
        hmac.compare_digest(
            _sha(chain["identity_chain_sha256"], f"{label}.identity chain"),
            expected,
        ),
        f"{label}.identity chain differs",
    )
    return chain


def _profile_policy_ref(value: Any) -> dict[str, str]:
    ref = _exact(
        value,
        {"schema", "profile_id", "profile_payload_sha256"},
        "profile-policy reference",
    )
    _require(ref["schema"] == PROFILE_POLICY_SCHEMA, "profile-policy reference schema differs")
    _text(ref["profile_id"], "profile-policy reference id")
    _sha(ref["profile_payload_sha256"], "profile-policy reference hash")
    return ref


def validate_profile_policy(document: Any) -> dict[str, Any]:
    policy = _exact(
        _rebuild_public_json(document),
        {
            "schema", "profile_id", "backend_kind", "root_policy_owner",
            "transport_identity_binding_sha256", "scheduler_dialect",
            "gaussian_runtime_binding_sha256", "resource_catalog_sha256",
            "declared_allowed_root", "root_policy",
            "path_normalization_version", "containment_version", "safety",
            "profile_payload_sha256",
        },
        "direct profile policy",
    )
    _require(policy["schema"] == PROFILE_POLICY_SCHEMA, "direct profile policy schema differs")
    _text(policy["profile_id"], "direct profile policy id")
    _require(policy["backend_kind"] == BACKEND_KIND, "direct profile policy backend differs")
    _owner_binding(policy["root_policy_owner"])
    _sha(policy["transport_identity_binding_sha256"], "transport identity binding")
    _require(policy["scheduler_dialect"] == SCHEDULER_DIALECT, "scheduler dialect differs")
    _sha(policy["gaussian_runtime_binding_sha256"], "Gaussian runtime binding")
    _sha(policy["resource_catalog_sha256"], "resource catalog")
    _absolute_root(policy["declared_allowed_root"], "declared allowed root")
    _require(policy["root_policy"] == ROOT_POLICY, "root policy differs")
    _require(policy["path_normalization_version"] == PATH_NORMALIZATION_VERSION, "path normalization version differs")
    _require(policy["containment_version"] == CONTAINMENT_VERSION, "containment version differs")
    _safety(policy["safety"])
    _self_hash(policy, "profile_payload_sha256", "direct profile policy")
    return copy.deepcopy(policy)


def validate_stable_root_identity_evidence(document: Any) -> dict[str, Any]:
    evidence = _exact(
        _rebuild_public_json(document),
        {
            "schema", "backend_kind", "root_policy_owner", "profile_policy",
            "reviewed_root_policy", "expected_root_identity", "derivation",
            "safety", "stable_projection", "evidence_payload_sha256",
        },
        "stable root identity evidence",
    )
    _require(evidence["schema"] == STABLE_EVIDENCE_SCHEMA, "stable evidence schema differs")
    _require(evidence["backend_kind"] == BACKEND_KIND, "stable evidence backend differs")
    _owner_binding(evidence["root_policy_owner"])
    _profile_policy_ref(evidence["profile_policy"])
    root_policy = _exact(
        evidence["reviewed_root_policy"],
        {"policy", "declared_allowed_root", "path_normalization_version", "containment_version"},
        "reviewed root policy",
    )
    _require(root_policy["policy"] == ROOT_POLICY, "reviewed root policy differs")
    root = _absolute_root(root_policy["declared_allowed_root"], "reviewed declared root")
    _require(root_policy["path_normalization_version"] == PATH_NORMALIZATION_VERSION, "reviewed normalization version differs")
    _require(root_policy["containment_version"] == CONTAINMENT_VERSION, "reviewed containment version differs")
    chain = _component_chain(evidence["expected_root_identity"], "expected root identity")
    _require(chain["canonical_root"] == root, "stable canonical root differs from policy")
    derivation = _exact(
        evidence["derivation"],
        {"project_component_grammar", "scratch_component", "scratch_is_project_relative"},
        "workspace derivation",
    )
    _require(derivation == {
        "project_component_grammar": PROJECT_GRAMMAR,
        "scratch_component": SCRATCH_COMPONENT,
        "scratch_is_project_relative": True,
    }, "workspace derivation differs")
    _safety(evidence["safety"])
    stable = _exact(
        evidence["stable_projection"],
        {
            "observation_time_excluded", "expiry_excluded", "nonce_excluded",
            "receipt_id_excluded", "per_operation_values_excluded",
        },
        "stable projection",
    )
    _require(all(value is True for value in stable.values()), "stable projection exclusions differ")
    forbidden = {"observed_at", "expires_at", "nonce", "receipt_id", "operation", "task_id", "attempt_id"}
    _require(not forbidden.intersection(evidence), "stable evidence contains per-operation fields")
    _self_hash(evidence, "evidence_payload_sha256", "stable root identity evidence")
    return copy.deepcopy(evidence)


def validate_direct_execution_profile(document: Any) -> dict[str, Any]:
    profile = _exact(
        _rebuild_public_json(document),
        {
            "schema", "profile_id", "backend_kind", "profile_policy",
            "root_policy_owner_version", "stable_root_identity_evidence_sha256",
            "transport_identity_binding_sha256", "scheduler_dialect",
            "gaussian_runtime_binding_sha256", "resource_catalog_sha256",
            "declared_allowed_root", "declared_capabilities",
            "profile_payload_sha256",
        },
        "direct execution profile",
    )
    _require(profile["schema"] == DIRECT_PROFILE_SCHEMA, "direct execution profile schema differs")
    _text(profile["profile_id"], "direct execution profile id")
    _require(profile["backend_kind"] == BACKEND_KIND, "direct execution profile backend differs")
    ref = _profile_policy_ref(profile["profile_policy"])
    _require(ref["profile_id"] == profile["profile_id"], "direct profile policy id mismatch")
    _require(profile["root_policy_owner_version"] == OWNER_VERSION, "direct profile owner version differs")
    for field, label in (
        ("stable_root_identity_evidence_sha256", "stable evidence"),
        ("transport_identity_binding_sha256", "transport identity binding"),
        ("gaussian_runtime_binding_sha256", "Gaussian runtime binding"),
        ("resource_catalog_sha256", "resource catalog"),
    ):
        _sha(profile[field], label)
    _require(profile["scheduler_dialect"] == SCHEDULER_DIALECT, "direct profile scheduler differs")
    _absolute_root(profile["declared_allowed_root"], "direct profile declared root")
    _require(
        type(profile["declared_capabilities"]) is list
        and tuple(profile["declared_capabilities"]) == DECLARED_CAPABILITIES,
        "direct profile capabilities differ",
    )
    _self_hash(profile, "profile_payload_sha256", "direct execution profile")
    return copy.deepcopy(profile)


def _workspace(value: Any) -> dict[str, Any]:
    workspace = _exact(
        value,
        {
            "project", "allowed_root", "remote_workdir", "scratch_workdir",
            "workspace_binding_sha256",
        },
        "authorization workspace",
    )
    project = _project(workspace["project"])
    root = _absolute_root(workspace["allowed_root"], "authorization allowed root")
    _require(workspace["remote_workdir"] == f"{root}/{project}", "authorization remote workdir differs")
    _require(workspace["scratch_workdir"] == f"{root}/{project}/{SCRATCH_COMPONENT}", "authorization scratch differs")
    expected = digest({
        "schema": "auto-g16-direct-workspace-binding/1",
        "project": project,
        "allowed_root": root,
        "remote_workdir": workspace["remote_workdir"],
        "scratch_workdir": workspace["scratch_workdir"],
    })
    _require(
        hmac.compare_digest(
            _sha(workspace["workspace_binding_sha256"], "workspace binding"),
            expected,
        ),
        "workspace binding differs",
    )
    return workspace


def _input_binding(value: Any) -> dict[str, Any]:
    binding = _exact(value, {"basename", "sha256", "size_bytes"}, "authorization input")
    _text(binding["basename"], "input basename", TOKEN_RE)
    _sha(binding["sha256"], "input hash")
    _positive_decimal(binding["size_bytes"], "input size")
    return binding


def _resources(value: Any) -> dict[str, Any]:
    resources = _exact(
        value,
        {"tier", "cores", "memory_gb", "walltime_seconds", "resources_binding_sha256"},
        "authorization resources",
    )
    _text(resources["tier"], "resource tier")
    for field in ("cores", "memory_gb", "walltime_seconds"):
        _positive_decimal(resources[field], f"resource {field}")
    expected = digest({
        "schema": "auto-g16-direct-resource-binding/1",
        "tier": resources["tier"],
        "cores": resources["cores"],
        "memory_gb": resources["memory_gb"],
        "walltime_seconds": resources["walltime_seconds"],
    })
    _require(
        hmac.compare_digest(
            _sha(resources["resources_binding_sha256"], "resources binding"),
            expected,
        ),
        "resources binding differs",
    )
    return resources


def _authorization_scope_projection(document: dict[str, Any]) -> dict[str, Any]:
    scope = document["scope"]
    return {
        "schema": "auto-g16-direct-authorization-scope/1",
        "authorization_id": document["authorization_id"],
        "profile": document["profile"],
        "root_evidence": document["root_evidence"],
        "workspace": document["workspace"],
        "input": document["input"],
        "resources": document["resources"],
        "operation": scope["operation"],
        "scientific_task_id": scope["scientific_task_id"],
        "attempt_id": scope["attempt_id"],
        "idempotency_key": scope["idempotency_key"],
        "fresh_observation_rules": document["fresh_observation_rules"],
    }


def validate_direct_execution_authorization(
    document: Any,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    authorization = _exact(
        _rebuild_public_json(document),
        {
            "schema", "authorization_id", "decision",
            "explicit_human_approval", "approved_at", "not_before",
            "expires_at", "profile", "root_evidence", "workspace", "input",
            "resources", "scope", "fresh_observation_rules", "consumption",
            "live_ready", "authorization_payload_sha256",
        },
        "direct execution authorization",
    )
    _require(authorization["schema"] == DIRECT_AUTHORIZATION_SCHEMA, "direct authorization schema differs")
    _text(authorization["authorization_id"], "direct authorization id")
    _require(authorization["decision"] == "approved", "direct authorization decision differs")
    _require(authorization["explicit_human_approval"] is True, "direct authorization requires explicit human approval")
    approved = _utc_text(authorization["approved_at"], "approved_at")
    not_before = _utc_text(authorization["not_before"], "not_before")
    expires = _utc_text(authorization["expires_at"], "expires_at")
    _require(approved <= not_before < expires, "direct authorization time order differs")
    profile = _exact(
        authorization["profile"],
        {"schema", "profile_id", "profile_payload_sha256"},
        "authorization profile",
    )
    _require(profile["schema"] == DIRECT_PROFILE_SCHEMA, "authorization profile schema differs")
    _text(profile["profile_id"], "authorization profile id")
    _sha(profile["profile_payload_sha256"], "authorization profile hash")
    root = _exact(
        authorization["root_evidence"],
        {
            "schema", "evidence_payload_sha256", "owner_version",
            "declared_allowed_root",
        },
        "authorization root evidence",
    )
    _require(root["schema"] == STABLE_EVIDENCE_SCHEMA, "authorization root evidence schema differs")
    _sha(root["evidence_payload_sha256"], "authorization stable evidence hash")
    _require(root["owner_version"] == OWNER_VERSION, "authorization root owner version differs")
    _absolute_root(root["declared_allowed_root"], "authorization root")
    workspace = _workspace(authorization["workspace"])
    _require(workspace["allowed_root"] == root["declared_allowed_root"], "authorization root/workspace mismatch")
    _input_binding(authorization["input"])
    _resources(authorization["resources"])
    scope = _exact(
        authorization["scope"],
        {
            "operation", "scientific_task_id", "attempt_id",
            "idempotency_key", "authorization_scope_sha256",
        },
        "authorization scope",
    )
    _require(scope["operation"] == "create_fresh_workspace_once", "authorization operation differs")
    _text(scope["scientific_task_id"], "scientific task id", TASK_RE)
    _text(scope["attempt_id"], "attempt id", ATTEMPT_RE)
    _text(scope["idempotency_key"], "idempotency key")
    expected_scope = digest(_authorization_scope_projection(authorization))
    _require(
        hmac.compare_digest(
            _sha(scope["authorization_scope_sha256"], "authorization scope hash"),
            expected_scope,
        ),
        "authorization scope hash differs",
    )
    rules = _exact(
        authorization["fresh_observation_rules"],
        set(FRESH_RULES) | {"maximum_receipt_age_seconds", "future_receipt_hash_prebound"},
        "fresh observation rules",
    )
    for key, expected in FRESH_RULES.items():
        _require(rules[key] == expected, f"fresh observation rule differs: {key}")
    _positive_decimal(
        rules["maximum_receipt_age_seconds"],
        "maximum receipt age",
        maximum=300,
    )
    _require(rules["future_receipt_hash_prebound"] is False, "future receipt hash must not be prebound")
    consumption = _exact(authorization["consumption"], {"single_use", "consumed"}, "authorization consumption")
    _require(consumption == {"single_use": True, "consumed": False}, "authorization consumption differs")
    _require(authorization["live_ready"] is False, "PR6A authorization cannot claim live readiness")
    _self_hash(authorization, "authorization_payload_sha256", "direct execution authorization")
    if now is not None:
        current = _format_utc(now)
        current_time = _utc_text(current, "trusted now")
        _require(not_before <= current_time < expires, "direct authorization is outside its trusted window")
    return copy.deepcopy(authorization)


def validate_fresh_root_observation_receipt(
    document: Any,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    receipt = _exact(
        _rebuild_public_json(document),
        {
            "schema", "profile", "stable_root_evidence", "authorization",
            "operation", "window", "observed_root", "comparison",
            "authority", "receipt_payload_sha256",
        },
        "fresh root observation receipt",
    )
    _require(receipt["schema"] == FRESH_RECEIPT_SCHEMA, "fresh receipt schema differs")
    profile = _exact(receipt["profile"], {"profile_id", "profile_payload_sha256"}, "fresh receipt profile")
    _text(profile["profile_id"], "fresh receipt profile id")
    _sha(profile["profile_payload_sha256"], "fresh receipt profile hash")
    stable = _exact(
        receipt["stable_root_evidence"],
        {"evidence_payload_sha256", "expected_identity_chain_sha256"},
        "fresh receipt stable evidence",
    )
    _sha(stable["evidence_payload_sha256"], "fresh receipt stable evidence hash")
    _sha(stable["expected_identity_chain_sha256"], "fresh receipt expected identity chain")
    authorization = _exact(
        receipt["authorization"],
        {"authorization_id", "authorization_payload_sha256", "authorization_scope_sha256"},
        "fresh receipt authorization",
    )
    _text(authorization["authorization_id"], "fresh receipt authorization id")
    _sha(authorization["authorization_payload_sha256"], "fresh receipt authorization hash")
    _sha(authorization["authorization_scope_sha256"], "fresh receipt authorization scope")
    operation = _exact(
        receipt["operation"],
        {"operation_version", "operation", "scientific_task_id", "attempt_id", "nonce"},
        "fresh receipt operation",
    )
    _require(operation["operation_version"] == FRESH_OPERATION_VERSION, "fresh receipt operation version differs")
    _require(operation["operation"] == "create_fresh_workspace_once", "fresh receipt operation differs")
    _text(operation["scientific_task_id"], "fresh receipt task", TASK_RE)
    _text(operation["attempt_id"], "fresh receipt attempt", ATTEMPT_RE)
    _text(operation["nonce"], "fresh receipt nonce", NONCE_RE)
    window = _exact(
        receipt["window"],
        {"observed_at", "expires_at", "maximum_receipt_age_seconds"},
        "fresh receipt window",
    )
    observed_at = _utc_text(window["observed_at"], "fresh receipt observed_at")
    expires_at = _utc_text(window["expires_at"], "fresh receipt expires_at")
    age = _positive_decimal(
        window["maximum_receipt_age_seconds"],
        "fresh receipt maximum age",
        maximum=300,
    )
    _require(expires_at == observed_at + timedelta(seconds=age), "fresh receipt expiry differs from maximum age")
    observed = _exact(
        receipt["observed_root"],
        {
            "identity", "project", "remote_workdir", "scratch_workdir",
            "workspace_binding_sha256", "fresh_project",
            "containment_verified", "no_symlink_verified",
            "descriptor_set_sha256",
        },
        "fresh observed root",
    )
    chain = _component_chain(observed["identity"], "fresh observed identity")
    project = _project(observed["project"], "fresh receipt project")
    root = chain["canonical_root"]
    _require(observed["remote_workdir"] == f"{root}/{project}", "fresh receipt remote workdir differs")
    _require(observed["scratch_workdir"] == f"{root}/{project}/{SCRATCH_COMPONENT}", "fresh receipt scratch differs")
    expected_workspace = digest({
        "schema": "auto-g16-direct-workspace-binding/1",
        "project": project,
        "allowed_root": root,
        "remote_workdir": observed["remote_workdir"],
        "scratch_workdir": observed["scratch_workdir"],
    })
    _require(
        hmac.compare_digest(
            _sha(observed["workspace_binding_sha256"], "fresh receipt workspace binding"),
            expected_workspace,
        ),
        "fresh receipt workspace binding differs",
    )
    _require(
        observed["fresh_project"] is True
        and observed["containment_verified"] is True
        and observed["no_symlink_verified"] is True,
        "fresh receipt root checks are incomplete",
    )
    _sha(observed["descriptor_set_sha256"], "fresh receipt descriptor set")
    comparison = _exact(
        receipt["comparison"],
        {
            "profile_matches", "stable_evidence_matches",
            "authorization_scope_matches", "root_identity_matches",
            "workspace_matches", "classification",
        },
        "fresh receipt comparison",
    )
    _require(
        all(comparison[key] is True for key in comparison if key != "classification")
        and comparison["classification"] == "verified",
        "fresh receipt comparison is not verified",
    )
    authority = _exact(
        receipt["authority"],
        {
            "portable_receipt_authorizes_effect",
            "descriptor_capability_required", "single_consumption_required",
            "descriptor_relative_operations_required", "path_reopen_allowed",
            "automatic_retry", "remote_effect_performed",
        },
        "fresh receipt authority",
    )
    _require(authority == {
        "portable_receipt_authorizes_effect": False,
        "descriptor_capability_required": True,
        "single_consumption_required": True,
        "descriptor_relative_operations_required": True,
        "path_reopen_allowed": False,
        "automatic_retry": False,
        "remote_effect_performed": False,
    }, "fresh receipt authority markers differ")
    _self_hash(receipt, "receipt_payload_sha256", "fresh root observation receipt")
    if now is not None:
        current = _utc_text(_format_utc(now), "trusted now")
        _require(observed_at <= current < expires_at, "fresh receipt is outside its trusted window")
    return copy.deepcopy(receipt)


def build_profile_policy(
    *,
    profile_id: str,
    declared_allowed_root: str,
    transport_identity_binding_sha256: str,
    gaussian_runtime_binding_sha256: str,
    resource_catalog_sha256: str,
) -> dict[str, Any]:
    _assert_owner_binding()
    document = {
        "schema": PROFILE_POLICY_SCHEMA,
        "profile_id": profile_id,
        "backend_kind": BACKEND_KIND,
        "root_policy_owner": {
            "owner_id": OWNER_ID,
            "owner_version": OWNER_VERSION,
            "owner_source_sha256": _OWNER_MODULE_BINDING.source.sha256,
        },
        "transport_identity_binding_sha256": transport_identity_binding_sha256,
        "scheduler_dialect": SCHEDULER_DIALECT,
        "gaussian_runtime_binding_sha256": gaussian_runtime_binding_sha256,
        "resource_catalog_sha256": resource_catalog_sha256,
        "declared_allowed_root": declared_allowed_root,
        "root_policy": ROOT_POLICY,
        "path_normalization_version": PATH_NORMALIZATION_VERSION,
        "containment_version": CONTAINMENT_VERSION,
        "safety": copy.deepcopy(SAFETY),
        "profile_payload_sha256": "",
    }
    return validate_profile_policy(_finalize(document, "profile_payload_sha256"))


def build_direct_execution_profile(
    profile_policy: dict[str, Any],
    stable_evidence: dict[str, Any] | "StableRootIdentityEvidence",
) -> dict[str, Any]:
    _assert_owner_binding()
    policy = validate_profile_policy(profile_policy)
    evidence_document = (
        stable_evidence.document()
        if type(stable_evidence) is StableRootIdentityEvidence
        else stable_evidence
    )
    evidence = validate_stable_root_identity_evidence(evidence_document)
    _require(
        evidence["profile_policy"]["profile_payload_sha256"]
        == policy["profile_payload_sha256"],
        "stable evidence/profile policy hash mismatch",
    )
    _require(
        evidence["reviewed_root_policy"]["declared_allowed_root"]
        == policy["declared_allowed_root"],
        "stable evidence/profile root mismatch",
    )
    document = {
        "schema": DIRECT_PROFILE_SCHEMA,
        "profile_id": policy["profile_id"],
        "backend_kind": BACKEND_KIND,
        "profile_policy": {
            "schema": policy["schema"],
            "profile_id": policy["profile_id"],
            "profile_payload_sha256": policy["profile_payload_sha256"],
        },
        "root_policy_owner_version": OWNER_VERSION,
        "stable_root_identity_evidence_sha256": evidence["evidence_payload_sha256"],
        "transport_identity_binding_sha256": policy["transport_identity_binding_sha256"],
        "scheduler_dialect": policy["scheduler_dialect"],
        "gaussian_runtime_binding_sha256": policy["gaussian_runtime_binding_sha256"],
        "resource_catalog_sha256": policy["resource_catalog_sha256"],
        "declared_allowed_root": policy["declared_allowed_root"],
        "declared_capabilities": list(DECLARED_CAPABILITIES),
        "profile_payload_sha256": "",
    }
    return validate_direct_execution_profile(_finalize(document, "profile_payload_sha256"))


def build_direct_execution_authorization(
    *,
    authorization_id: str,
    profile: dict[str, Any],
    stable_evidence: dict[str, Any] | "StableRootIdentityEvidence",
    project: str,
    input_basename: str,
    input_sha256: str,
    input_size_bytes: int,
    tier: str,
    cores: int,
    memory_gb: int,
    walltime_seconds: int,
    scientific_task_id: str,
    attempt_id: str,
    idempotency_key: str,
    approved_at: str,
    not_before: str,
    expires_at: str,
    maximum_receipt_age_seconds: int,
) -> dict[str, Any]:
    _assert_owner_binding()
    for value, label in (
        (input_size_bytes, "input size"),
        (cores, "resource cores"),
        (memory_gb, "resource memory"),
        (walltime_seconds, "resource walltime"),
        (maximum_receipt_age_seconds, "maximum receipt age"),
    ):
        _positive_integer(value, label)
    _require(
        maximum_receipt_age_seconds <= 300,
        "maximum receipt age exceeds owner bound",
    )
    input_size_text = str(input_size_bytes)
    cores_text = str(cores)
    memory_text = str(memory_gb)
    walltime_text = str(walltime_seconds)
    maximum_age_text = str(maximum_receipt_age_seconds)
    validated_profile = validate_direct_execution_profile(profile)
    evidence_document = (
        stable_evidence.document()
        if type(stable_evidence) is StableRootIdentityEvidence
        else stable_evidence
    )
    evidence = validate_stable_root_identity_evidence(evidence_document)
    _require(
        validated_profile["stable_root_identity_evidence_sha256"]
        == evidence["evidence_payload_sha256"],
        "authorization profile/stable evidence mismatch",
    )
    root = validated_profile["declared_allowed_root"]
    remote_workdir = f"{root}/{project}"
    workspace = {
        "project": project,
        "allowed_root": root,
        "remote_workdir": remote_workdir,
        "scratch_workdir": f"{remote_workdir}/{SCRATCH_COMPONENT}",
        "workspace_binding_sha256": "",
    }
    workspace["workspace_binding_sha256"] = digest({
        "schema": "auto-g16-direct-workspace-binding/1",
        "project": project,
        "allowed_root": root,
        "remote_workdir": remote_workdir,
        "scratch_workdir": workspace["scratch_workdir"],
    })
    resources = {
        "tier": tier,
        "cores": cores_text,
        "memory_gb": memory_text,
        "walltime_seconds": walltime_text,
        "resources_binding_sha256": "",
    }
    resources["resources_binding_sha256"] = digest({
        "schema": "auto-g16-direct-resource-binding/1",
        "tier": tier,
        "cores": cores_text,
        "memory_gb": memory_text,
        "walltime_seconds": walltime_text,
    })
    document = {
        "schema": DIRECT_AUTHORIZATION_SCHEMA,
        "authorization_id": authorization_id,
        "decision": "approved",
        "explicit_human_approval": True,
        "approved_at": approved_at,
        "not_before": not_before,
        "expires_at": expires_at,
        "profile": {
            "schema": DIRECT_PROFILE_SCHEMA,
            "profile_id": validated_profile["profile_id"],
            "profile_payload_sha256": validated_profile["profile_payload_sha256"],
        },
        "root_evidence": {
            "schema": STABLE_EVIDENCE_SCHEMA,
            "evidence_payload_sha256": evidence["evidence_payload_sha256"],
            "owner_version": OWNER_VERSION,
            "declared_allowed_root": root,
        },
        "workspace": workspace,
        "input": {
            "basename": input_basename,
            "sha256": input_sha256,
            "size_bytes": input_size_text,
        },
        "resources": resources,
        "scope": {
            "operation": "create_fresh_workspace_once",
            "scientific_task_id": scientific_task_id,
            "attempt_id": attempt_id,
            "idempotency_key": idempotency_key,
            "authorization_scope_sha256": "",
        },
        "fresh_observation_rules": {
            **FRESH_RULES,
            "maximum_receipt_age_seconds": maximum_age_text,
            "future_receipt_hash_prebound": False,
        },
        "consumption": {"single_use": True, "consumed": False},
        "live_ready": False,
        "authorization_payload_sha256": "",
    }
    document["scope"]["authorization_scope_sha256"] = digest(
        _authorization_scope_projection(document)
    )
    return validate_direct_execution_authorization(
        _finalize(document, "authorization_payload_sha256")
    )


@dataclass(frozen=True, slots=True)
class _FileSnapshot:
    path: Path
    identity: tuple[int, ...]
    sha256: str
    size_bytes: int
    source_bytes: bytes


@dataclass(frozen=True, slots=True)
class _OwnerModuleBinding:
    module: types.ModuleType
    issued_types: tuple[tuple[str, type], ...]
    source: _FileSnapshot


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


def _stable_file(path: Path) -> _FileSnapshot:
    resolved = Path(os.path.abspath(path))
    _require(resolved.is_absolute(), "owner source path must be absolute")
    descriptor = -1
    try:
        before = os.stat(resolved, follow_symlinks=False)
        _require(stat.S_ISREG(before.st_mode) and not stat.S_ISLNK(before.st_mode), "owner source is not a no-follow regular file")
        descriptor = os.open(
            resolved,
            os.O_RDONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
        )
        opened = os.fstat(descriptor)
        _require(_stat_identity(opened) == _stat_identity(before), "owner source changed while opening")
        _require(0 < opened.st_size <= MAX_DOCUMENT_BYTES, "owner source size is outside the bound")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 65536)
            if not chunk:
                break
            chunks.append(chunk)
        after_fd = os.fstat(descriptor)
        after_path = os.stat(resolved, follow_symlinks=False)
    except OSError as exc:
        raise DirectRootOwnerError(f"stable owner source read failed: {exc}") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    identities = {
        _stat_identity(before),
        _stat_identity(opened),
        _stat_identity(after_fd),
        _stat_identity(after_path),
    }
    _require(len(identities) == 1, "owner source identity drifted")
    raw = b"".join(chunks)
    _require(len(raw) == opened.st_size, "owner source read was short")
    return _FileSnapshot(
        path=resolved,
        identity=_stat_identity(opened),
        sha256=hashlib.sha256(raw).hexdigest(),
        size_bytes=len(raw),
        source_bytes=raw,
    )


def _module_origin(module: types.ModuleType) -> tuple[Path, Path]:
    raw_file = getattr(module, "__file__", None)
    raw_origin = getattr(getattr(module, "__spec__", None), "origin", None)
    _require(type(raw_file) is str and type(raw_origin) is str, "direct-root owner has no exact origin")
    return Path(raw_file).resolve(), Path(raw_origin).resolve()


def _owner_path() -> Path:
    path = Path(__file__).resolve(strict=True)
    _require(path.is_file() and not path.is_symlink(), "direct-root owner source is unavailable")
    return path


_OWNER_SOURCE = _stable_file(_owner_path())
_SEAL_TOKEN = object()
_SNAPSHOT_TOKEN = object()
_CAPABILITY_TOKEN = object()
_LEASE_TOKEN = object()
_OWNER_TOKEN = object()
_TEST_FACTORY_TOKEN = object()
_BACKEND_FACTORY_TOKEN = object()
_DESCRIPTOR_BUNDLE_TOKEN = object()


def _system_utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _system_nonce() -> str:
    return secrets.token_hex(16)


def _directory_identity(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_uid,
        info.st_gid,
        stat.S_IFMT(info.st_mode),
        stat.S_IMODE(info.st_mode),
    )


def _directory_identity_sha256(info: os.stat_result) -> str:
    identity = _directory_identity(info)
    return digest({
        "schema": "auto-g16-posix-directory-identity/1",
        "device": str(identity[0]),
        "inode": str(identity[1]),
        "uid": str(identity[2]),
        "gid": str(identity[3]),
        "file_type": str(identity[4]),
        "mode": str(identity[5]),
    })


def _close_directory_descriptors(descriptors: tuple[int, ...]) -> None:
    for descriptor in reversed(descriptors):
        try:
            os.close(descriptor)
        except OSError:
            pass


class _OwnedDescriptorBundle:
    __slots__ = ()

    def __new__(cls, *args: Any, **kwargs: Any) -> "_OwnedDescriptorBundle":
        raise TypeError("descriptor bundles are owner-issued only")

    @classmethod
    def _from_owner(
        cls,
        descriptors: tuple[int, ...],
        *,
        token: object,
    ) -> "_OwnedDescriptorBundle":
        if cls is not _OwnedDescriptorBundle or token is not _DESCRIPTOR_BUNDLE_TOKEN:
            raise DirectRootOwnerError("descriptor bundle seal differs")
        _require(
            type(descriptors) is tuple
            and descriptors
            and len(set(descriptors)) == len(descriptors)
            and all(type(item) is int and item >= 0 for item in descriptors),
            "descriptor bundle handles differ",
        )
        value = object.__new__(cls)
        _register_descriptor_bundle(
            value,
            _DescriptorBundleState(
                bundle=value,
                descriptors=descriptors,
                owner_pid=os.getpid(),
                lock=threading.Lock(),
            ),
        )
        return value


@dataclass(slots=True)
class _DescriptorBundleState:
    bundle: object
    descriptors: tuple[int, ...]
    owner_pid: int
    lock: threading.Lock
    closed: bool = False
    ownership_transferred: bool = False


_DESCRIPTOR_BUNDLE_REGISTRY_LOCK = threading.RLock()
_DESCRIPTOR_BUNDLE_REGISTRY: dict[int, _DescriptorBundleState] = {}
_ACTIVE_DESCRIPTOR_BUNDLE_REGISTRY: dict[int, _DescriptorBundleState] = {}
_AT_FORK_ACTIVE_BUNDLE_STATES: tuple[_DescriptorBundleState, ...] = ()


def _register_descriptor_bundle(
    bundle: object,
    state: _DescriptorBundleState,
) -> None:
    _require(state.bundle is bundle, "descriptor bundle state identity differs")
    with _DESCRIPTOR_BUNDLE_REGISTRY_LOCK:
        _require(
            id(bundle) not in _DESCRIPTOR_BUNDLE_REGISTRY,
            "descriptor bundle state is already registered",
        )
        _DESCRIPTOR_BUNDLE_REGISTRY[id(bundle)] = state
        _ACTIVE_DESCRIPTOR_BUNDLE_REGISTRY[id(bundle)] = state


def _descriptor_bundle_state_unlocked(bundle: object) -> _DescriptorBundleState:
    state = _DESCRIPTOR_BUNDLE_REGISTRY.get(id(bundle))
    _require(
        type(bundle) is _OwnedDescriptorBundle
        and type(state) is _DescriptorBundleState
        and state.bundle is bundle,
        "descriptor bundle state is unavailable",
    )
    return state


def _descriptor_bundle_state(bundle: object) -> _DescriptorBundleState:
    with _DESCRIPTOR_BUNDLE_REGISTRY_LOCK:
        return _descriptor_bundle_state_unlocked(bundle)


def _descriptor_bundle_handles(bundle: _OwnedDescriptorBundle) -> tuple[int, ...]:
    with _DESCRIPTOR_BUNDLE_REGISTRY_LOCK:
        state = _descriptor_bundle_state_unlocked(bundle)
        with state.lock:
            _require(
                _ACTIVE_DESCRIPTOR_BUNDLE_REGISTRY.get(id(bundle)) is state
                and not state.closed,
                "descriptor bundle is closed or inactive",
            )
            _require(
                state.owner_pid == os.getpid(),
                "descriptor bundle cannot cross a process or fork boundary",
            )
            return state.descriptors


def _transfer_descriptor_bundle_to_capability_once(
    bundle: _OwnedDescriptorBundle,
) -> None:
    with _DESCRIPTOR_BUNDLE_REGISTRY_LOCK:
        state = _descriptor_bundle_state_unlocked(bundle)
        with state.lock:
            _require(
                _ACTIVE_DESCRIPTOR_BUNDLE_REGISTRY.get(id(bundle)) is state
                and not state.closed,
                "descriptor bundle is closed or inactive",
            )
            _require(
                state.owner_pid == os.getpid(),
                "descriptor bundle cannot cross a process or fork boundary",
            )
            _require(
                not state.ownership_transferred,
                "descriptor bundle ownership is already transferred",
            )
            state.ownership_transferred = True


def _close_descriptor_bundle_once(
    bundle: _OwnedDescriptorBundle,
    *,
    owner: str,
) -> bool:
    _require(
        owner in {"observer", "capability"},
        "descriptor bundle close owner differs",
    )
    with _DESCRIPTOR_BUNDLE_REGISTRY_LOCK:
        state = _descriptor_bundle_state_unlocked(bundle)
        if _ACTIVE_DESCRIPTOR_BUNDLE_REGISTRY.get(id(bundle)) is not state:
            _require(state.closed, "inactive descriptor bundle is not closed")
            return False
        with state.lock:
            if state.closed:
                return False
            if owner == "observer" and state.ownership_transferred:
                return False
            _require(
                owner == "observer" or state.ownership_transferred,
                "descriptor bundle capability ownership is absent",
            )
            state.closed = True
            del _ACTIVE_DESCRIPTOR_BUNDLE_REGISTRY[id(bundle)]
            _close_directory_descriptors(state.descriptors)
            return True


def _open_root_components_no_follow(
    canonical_root: str,
) -> tuple[
    list[dict[str, Any]],
    tuple[str, ...],
    tuple[tuple[int, ...], ...],
    _OwnedDescriptorBundle,
]:
    with _DESCRIPTOR_BUNDLE_REGISTRY_LOCK:
        return _open_root_components_no_follow_while_fork_blocked(canonical_root)


def _open_root_components_no_follow_while_fork_blocked(
    canonical_root: str,
) -> tuple[
    list[dict[str, Any]],
    tuple[str, ...],
    tuple[tuple[int, ...], ...],
    _OwnedDescriptorBundle,
]:
    """Open one reviewed POSIX root component-by-component without following links."""
    root = _absolute_root(canonical_root, "backend observer root")
    _require(
        hasattr(os, "O_NOFOLLOW")
        and hasattr(os, "O_DIRECTORY")
        and hasattr(os, "register_at_fork"),
        "backend no-follow directory primitives are unavailable",
    )
    names = tuple(PurePosixPath(root).parts[1:])
    _require(
        len(root.encode("utf-8")) <= MAX_OBSERVED_ROOT_BYTES
        and len(names) <= MAX_OBSERVED_ROOT_COMPONENTS
        and all(
            len(name.encode("utf-8")) <= MAX_OBSERVED_COMPONENT_BYTES
            for name in names
        ),
        "backend observer root exceeds its component bound",
    )
    flags = (
        os.O_RDONLY
        | os.O_DIRECTORY
        | os.O_NOFOLLOW
        | getattr(os, "O_CLOEXEC", 0)
    )
    opened: list[int] = []
    components: list[dict[str, Any]] = []
    identities: list[tuple[int, ...]] = []
    try:
        anchor = os.open("/", flags)
        opened.append(anchor)
        anchor_info = os.fstat(anchor)
        _require(
            stat.S_ISDIR(anchor_info.st_mode),
            "backend root anchor is not a directory",
        )
        parent = anchor
        path_parts: list[str] = []
        for ordinal, name in enumerate(names):
            path_parts.append(name)
            before = os.stat(name, dir_fd=parent, follow_symlinks=False)
            _require(
                stat.S_ISDIR(before.st_mode) and not stat.S_ISLNK(before.st_mode),
                "backend root component is not a no-follow directory",
            )
            descriptor = os.open(name, flags, dir_fd=parent)
            opened.append(descriptor)
            opened_info = os.fstat(descriptor)
            after = os.stat(name, dir_fd=parent, follow_symlinks=False)
            identity = _directory_identity(opened_info)
            _require(
                identity == _directory_identity(before)
                and identity == _directory_identity(after)
                and stat.S_ISDIR(opened_info.st_mode),
                "backend root component identity drifted while opening",
            )
            component_path = "/" + "/".join(path_parts)
            components.append({
                "ordinal": str(ordinal),
                "component_path_sha256": hashlib.sha256(
                    component_path.encode("utf-8")
                ).hexdigest(),
                "identity_sha256": _directory_identity_sha256(opened_info),
            })
            identities.append(identity)
            parent = descriptor
    except (OSError, DirectRootOwnerError) as exc:
        _close_directory_descriptors(tuple(opened))
        if isinstance(exc, DirectRootOwnerError):
            raise
        raise DirectRootOwnerError(
            f"backend no-follow root observation failed: {exc}"
        ) from exc
    bundle = _OwnedDescriptorBundle._from_owner(
        tuple(opened),
        token=_DESCRIPTOR_BUNDLE_TOKEN,
    )
    return components, names, tuple(identities), bundle


def _project_is_fresh_at_root(descriptor: int, project: str) -> bool:
    component = _project(project, "backend observer project")
    try:
        os.stat(component, dir_fd=descriptor, follow_symlinks=False)
    except FileNotFoundError:
        return True
    except OSError as exc:
        raise DirectRootOwnerError(
            f"backend project freshness observation failed: {exc}"
        ) from exc
    return False


@dataclass(frozen=True, slots=True, init=False)
class StableRootIdentityEvidence:
    _canonical_document: bytes
    _seal: object

    def __new__(cls, *args: Any, **kwargs: Any) -> "StableRootIdentityEvidence":
        raise TypeError("stable root identity evidence is owner-issued only")

    @classmethod
    def _from_owner(cls, document: dict[str, Any], *, token: object) -> "StableRootIdentityEvidence":
        _assert_owner_binding()
        if cls is not _owner_issued_type("StableRootIdentityEvidence") or token is not _SEAL_TOKEN:
            raise DirectRootOwnerError("stable evidence seal differs")
        value = object.__new__(cls)
        object.__setattr__(value, "_canonical_document", canonical_bytes(document))
        object.__setattr__(value, "_seal", _SEAL_TOKEN)
        return value

    def document(self) -> dict[str, Any]:
        return json.loads(self._canonical_document)

    def assert_owner_sealed(self) -> "StableRootIdentityEvidence":
        _assert_owner_binding()
        _require(type(self) is StableRootIdentityEvidence and self._seal is _SEAL_TOKEN, "stable evidence seal differs")
        document = validate_stable_root_identity_evidence(self.document())
        _require(canonical_bytes(document) == self._canonical_document, "stable evidence projection differs")
        return self

    def __copy__(self) -> "StableRootIdentityEvidence":
        raise TypeError("stable root identity evidence is not clonable")

    def __deepcopy__(self, memo: dict[int, Any]) -> "StableRootIdentityEvidence":
        del memo
        raise TypeError("stable root identity evidence is not clonable")

    def __reduce__(self) -> object:
        raise TypeError("stable root identity evidence is not serializable")

    def __reduce_ex__(self, protocol: int) -> object:
        del protocol
        raise TypeError("stable root identity evidence is not serializable")


@dataclass(frozen=True, slots=True, init=False)
class FreshRootObservationReceipt:
    _canonical_document: bytes
    _seal: object

    def __new__(cls, *args: Any, **kwargs: Any) -> "FreshRootObservationReceipt":
        raise TypeError("fresh root observation receipts are owner-issued only")

    @classmethod
    def _from_owner(cls, document: dict[str, Any], *, token: object) -> "FreshRootObservationReceipt":
        _assert_owner_binding()
        if cls is not _owner_issued_type("FreshRootObservationReceipt") or token is not _SEAL_TOKEN:
            raise DirectRootOwnerError("fresh receipt seal differs")
        value = object.__new__(cls)
        object.__setattr__(value, "_canonical_document", canonical_bytes(document))
        object.__setattr__(value, "_seal", _SEAL_TOKEN)
        return value

    def document(self) -> dict[str, Any]:
        return json.loads(self._canonical_document)

    def assert_owner_sealed(self) -> "FreshRootObservationReceipt":
        _assert_owner_binding()
        _require(type(self) is FreshRootObservationReceipt and self._seal is _SEAL_TOKEN, "fresh receipt seal differs")
        document = validate_fresh_root_observation_receipt(self.document())
        _require(canonical_bytes(document) == self._canonical_document, "fresh receipt projection differs")
        return self

    def __copy__(self) -> "FreshRootObservationReceipt":
        raise TypeError("fresh root observation receipts are not clonable")

    def __deepcopy__(self, memo: dict[int, Any]) -> "FreshRootObservationReceipt":
        del memo
        raise TypeError("fresh root observation receipts are not clonable")

    def __reduce__(self) -> object:
        raise TypeError("fresh root observation receipts are not serializable")

    def __reduce_ex__(self, protocol: int) -> object:
        del protocol
        raise TypeError("fresh root observation receipts are not serializable")


@dataclass(frozen=True, slots=True, init=False)
class _OwnerRootIdentitySnapshot:
    canonical_root: str
    components: tuple[tuple[str, str, str], ...]
    identity_chain_sha256: str
    project: str
    remote_workdir: str
    scratch_workdir: str
    workspace_binding_sha256: str
    fresh_project: bool
    containment_verified: bool
    no_symlink_verified: bool
    _descriptor_set: object
    _seal: object

    def __new__(cls, *args: Any, **kwargs: Any) -> "_OwnerRootIdentitySnapshot":
        raise TypeError("root identity snapshots are owner-issued only")

    @classmethod
    def _from_owner(
        cls,
        *,
        canonical_root: str,
        components: list[dict[str, Any]],
        project: str,
        fresh_project: bool,
        containment_verified: bool,
        no_symlink_verified: bool,
        descriptor_set: "_DescriptorSet | None" = None,
        token: object,
    ) -> "_OwnerRootIdentitySnapshot":
        _assert_owner_binding()
        if cls is not _OwnerRootIdentitySnapshot or token is not _SNAPSHOT_TOKEN:
            raise DirectRootOwnerError("root snapshot seal differs")
        chain = {
            "canonical_root": canonical_root,
            "components": copy.deepcopy(components),
            "identity_chain_sha256": digest({
                "schema": "auto-g16-root-component-identity-chain/1",
                "canonical_root": canonical_root,
                "components": components,
            }),
        }
        _component_chain(chain, "owner root snapshot")
        project = _project(project, "owner root snapshot project")
        remote = f"{canonical_root}/{project}"
        scratch = f"{remote}/{SCRATCH_COMPONENT}"
        workspace_sha = digest({
            "schema": "auto-g16-direct-workspace-binding/1",
            "project": project,
            "allowed_root": canonical_root,
            "remote_workdir": remote,
            "scratch_workdir": scratch,
        })
        if descriptor_set is None:
            descriptor_set = _DescriptorSet._from_owner(
                identity_chain_sha256=chain["identity_chain_sha256"],
                workspace_binding_sha256=workspace_sha,
                token=_SNAPSHOT_TOKEN,
            )
        else:
            _require(
                type(descriptor_set) is _DescriptorSet,
                "root snapshot requires the exact backend descriptor set",
            )
            descriptor_set.assert_owner_sealed()
            _require(
                descriptor_set.identity_chain_sha256
                == chain["identity_chain_sha256"]
                and descriptor_set.workspace_binding_sha256 == workspace_sha,
                "root snapshot backend descriptor binding differs",
            )
        value = object.__new__(cls)
        object.__setattr__(value, "canonical_root", canonical_root)
        object.__setattr__(
            value,
            "components",
            tuple(
                (
                    item["ordinal"],
                    item["component_path_sha256"],
                    item["identity_sha256"],
                )
                for item in components
            ),
        )
        object.__setattr__(value, "identity_chain_sha256", chain["identity_chain_sha256"])
        object.__setattr__(value, "project", project)
        object.__setattr__(value, "remote_workdir", remote)
        object.__setattr__(value, "scratch_workdir", scratch)
        object.__setattr__(value, "workspace_binding_sha256", workspace_sha)
        object.__setattr__(value, "fresh_project", fresh_project)
        object.__setattr__(value, "containment_verified", containment_verified)
        object.__setattr__(value, "no_symlink_verified", no_symlink_verified)
        object.__setattr__(value, "_descriptor_set", descriptor_set)
        object.__setattr__(value, "_seal", _SNAPSHOT_TOKEN)
        return value

    def identity_document(self) -> dict[str, Any]:
        return {
            "canonical_root": self.canonical_root,
            "components": [
                {
                    "ordinal": ordinal,
                    "component_path_sha256": path_sha,
                    "identity_sha256": identity_sha,
                }
                for ordinal, path_sha, identity_sha in self.components
            ],
            "identity_chain_sha256": self.identity_chain_sha256,
        }

    def assert_owner_sealed(self) -> "_OwnerRootIdentitySnapshot":
        _assert_owner_binding()
        _require(type(self) is _OwnerRootIdentitySnapshot and self._seal is _SNAPSHOT_TOKEN, "root snapshot seal differs")
        chain = _component_chain(self.identity_document(), "owner root snapshot")
        _require(chain["identity_chain_sha256"] == self.identity_chain_sha256, "root snapshot identity differs")
        _require(type(self._descriptor_set) is _DescriptorSet, "root snapshot descriptor type differs")
        self._descriptor_set.assert_owner_sealed()
        _require(
            self._descriptor_set.identity_chain_sha256 == self.identity_chain_sha256
            and self._descriptor_set.workspace_binding_sha256 == self.workspace_binding_sha256,
            "root snapshot descriptor binding differs",
        )
        return self


@dataclass(frozen=True, slots=True, init=False)
class _DescriptorSet:
    identity_chain_sha256: str
    workspace_binding_sha256: str
    descriptor_set_sha256: str
    _opaque_handles: tuple[object, ...] | tuple[int, ...]
    _mode: str
    _component_names: tuple[str, ...]
    _component_identities: tuple[tuple[int, ...], ...]
    _descriptor_bundle: _OwnedDescriptorBundle | None
    _seal: object

    def __new__(cls, *args: Any, **kwargs: Any) -> "_DescriptorSet":
        raise TypeError("descriptor sets are owner-issued only")

    @classmethod
    def _from_owner(
        cls,
        *,
        identity_chain_sha256: str,
        workspace_binding_sha256: str,
        token: object,
    ) -> "_DescriptorSet":
        if cls is not _DescriptorSet or token is not _SNAPSHOT_TOKEN:
            raise DirectRootOwnerError("descriptor-set seal differs")
        value = object.__new__(cls)
        handles = (object(), object())
        set_sha = digest({
            "schema": "auto-g16-offline-descriptor-set-model/1",
            "identity_chain_sha256": identity_chain_sha256,
            "workspace_binding_sha256": workspace_binding_sha256,
            "handle_count": len(handles),
            "path_reopen_allowed": False,
        })
        object.__setattr__(value, "identity_chain_sha256", identity_chain_sha256)
        object.__setattr__(value, "workspace_binding_sha256", workspace_binding_sha256)
        object.__setattr__(value, "descriptor_set_sha256", set_sha)
        object.__setattr__(value, "_opaque_handles", handles)
        object.__setattr__(value, "_mode", "offline_synthetic")
        object.__setattr__(value, "_component_names", ())
        object.__setattr__(value, "_component_identities", ())
        object.__setattr__(value, "_descriptor_bundle", None)
        object.__setattr__(value, "_seal", _SNAPSHOT_TOKEN)
        return value

    @classmethod
    def _from_posix_owner(
        cls,
        *,
        identity_chain_sha256: str,
        workspace_binding_sha256: str,
        component_names: tuple[str, ...],
        component_identities: tuple[tuple[int, ...], ...],
        descriptor_bundle: _OwnedDescriptorBundle,
        token: object,
    ) -> "_DescriptorSet":
        if cls is not _DescriptorSet or token is not _SNAPSHOT_TOKEN:
            raise DirectRootOwnerError("descriptor-set seal differs")
        _require(
            type(component_names) is tuple
            and component_names
            and all(
                type(name) is str
                and name not in {"", ".", ".."}
                and "/" not in name
                for name in component_names
            ),
            "backend descriptor component names differ",
        )
        _require(
            type(component_identities) is tuple
            and len(component_identities) == len(component_names)
            and all(
                type(identity) is tuple
                and len(identity) == 6
                and all(type(item) is int for item in identity)
                for identity in component_identities
            ),
            "backend descriptor component identities differ",
        )
        _require(
            type(descriptor_bundle) is _OwnedDescriptorBundle,
            "backend descriptor bundle differs",
        )
        descriptors = _descriptor_bundle_handles(descriptor_bundle)
        _require(
            len(descriptors) == len(component_names) + 1,
            "backend descriptor handles differ",
        )
        set_sha = digest({
            "schema": "auto-g16-posix-nofollow-descriptor-set/1",
            "identity_chain_sha256": identity_chain_sha256,
            "workspace_binding_sha256": workspace_binding_sha256,
            "handle_count": len(descriptors),
            "component_count": len(component_names),
            "component_names_sha256": digest({
                "schema": "auto-g16-posix-root-component-names/1",
                "components": list(component_names),
            }),
            "path_reopen_allowed": False,
        })
        value = object.__new__(cls)
        object.__setattr__(value, "identity_chain_sha256", identity_chain_sha256)
        object.__setattr__(value, "workspace_binding_sha256", workspace_binding_sha256)
        object.__setattr__(value, "descriptor_set_sha256", set_sha)
        object.__setattr__(value, "_opaque_handles", descriptors)
        object.__setattr__(value, "_mode", "posix_nofollow")
        object.__setattr__(value, "_component_names", component_names)
        object.__setattr__(value, "_component_identities", component_identities)
        object.__setattr__(value, "_descriptor_bundle", descriptor_bundle)
        object.__setattr__(value, "_seal", _SNAPSHOT_TOKEN)
        value.assert_owner_sealed()
        return value

    def assert_owner_sealed(self) -> "_DescriptorSet":
        _require(type(self) is _DescriptorSet and self._seal is _SNAPSHOT_TOKEN, "descriptor-set seal differs")
        if self._mode == "offline_synthetic":
            _require(
                type(self._opaque_handles) is tuple
                and len(self._opaque_handles) == 2
                and all(type(item) is object for item in self._opaque_handles)
                and self._component_names == ()
                and self._component_identities == ()
                and self._descriptor_bundle is None,
                "descriptor-set handles differ",
            )
            expected = digest({
                "schema": "auto-g16-offline-descriptor-set-model/1",
                "identity_chain_sha256": self.identity_chain_sha256,
                "workspace_binding_sha256": self.workspace_binding_sha256,
                "handle_count": 2,
                "path_reopen_allowed": False,
            })
        else:
            _require(
                self._mode == "posix_nofollow"
                and type(self._opaque_handles) is tuple
                and len(self._opaque_handles) == len(self._component_names) + 1
                and len(set(self._opaque_handles)) == len(self._opaque_handles)
                and all(
                    type(item) is int and item >= 0
                    for item in self._opaque_handles
                )
                and len(self._component_identities) == len(self._component_names),
                "backend descriptor handles differ",
            )
            _require(
                type(self._descriptor_bundle) is _OwnedDescriptorBundle
                and _descriptor_bundle_handles(self._descriptor_bundle)
                is self._opaque_handles,
                "backend descriptor bundle differs",
            )
            try:
                anchor = os.fstat(self._opaque_handles[0])
                _require(
                    stat.S_ISDIR(anchor.st_mode),
                    "backend descriptor anchor is not a directory",
                )
                for index, (name, expected_identity) in enumerate(
                    zip(
                        self._component_names,
                        self._component_identities,
                        strict=True,
                    )
                ):
                    parent = self._opaque_handles[index]
                    child = self._opaque_handles[index + 1]
                    before = os.stat(
                        name,
                        dir_fd=parent,
                        follow_symlinks=False,
                    )
                    opened = os.fstat(child)
                    after = os.stat(
                        name,
                        dir_fd=parent,
                        follow_symlinks=False,
                    )
                    _require(
                        stat.S_ISDIR(before.st_mode)
                        and not stat.S_ISLNK(before.st_mode)
                        and _directory_identity(before) == expected_identity
                        and _directory_identity(opened) == expected_identity
                        and _directory_identity(after) == expected_identity,
                        "backend descriptor component identity drifted",
                    )
            except OSError as exc:
                raise DirectRootOwnerError(
                    f"backend descriptor replay failed: {exc}"
                ) from exc
            expected = digest({
                "schema": "auto-g16-posix-nofollow-descriptor-set/1",
                "identity_chain_sha256": self.identity_chain_sha256,
                "workspace_binding_sha256": self.workspace_binding_sha256,
                "handle_count": len(self._opaque_handles),
                "component_count": len(self._component_names),
                "component_names_sha256": digest({
                    "schema": "auto-g16-posix-root-component-names/1",
                    "components": list(self._component_names),
                }),
                "path_reopen_allowed": False,
            })
        _require(hmac.compare_digest(self.descriptor_set_sha256, expected), "descriptor-set digest differs")
        return self


def _observe_workspace_no_follow(
    *,
    canonical_root: str,
    project: str,
) -> _OwnerRootIdentitySnapshot:
    components, names, identities, descriptor_bundle = _open_root_components_no_follow(
        canonical_root
    )
    try:
        descriptors = _descriptor_bundle_handles(descriptor_bundle)
        project_name = _project(project, "backend observer project")
        fresh_project = _project_is_fresh_at_root(
            descriptors[-1],
            project_name,
        )
        _require(
            fresh_project,
            "backend project already exists or is not fresh",
        )
        identity_chain_sha256 = digest({
            "schema": "auto-g16-root-component-identity-chain/1",
            "canonical_root": canonical_root,
            "components": components,
        })
        remote = f"{canonical_root}/{project_name}"
        workspace_binding_sha256 = digest({
            "schema": "auto-g16-direct-workspace-binding/1",
            "project": project_name,
            "allowed_root": canonical_root,
            "remote_workdir": remote,
            "scratch_workdir": f"{remote}/{SCRATCH_COMPONENT}",
        })
        descriptor_set = _DescriptorSet._from_posix_owner(
            identity_chain_sha256=identity_chain_sha256,
            workspace_binding_sha256=workspace_binding_sha256,
            component_names=names,
            component_identities=identities,
            descriptor_bundle=descriptor_bundle,
            token=_SNAPSHOT_TOKEN,
        )
        return _OwnerRootIdentitySnapshot._from_owner(
            canonical_root=canonical_root,
            components=components,
            project=project_name,
            fresh_project=True,
            containment_verified=True,
            no_symlink_verified=True,
            descriptor_set=descriptor_set,
            token=_SNAPSHOT_TOKEN,
        )
    except BaseException:
        _close_descriptor_bundle_once(
            descriptor_bundle,
            owner="observer",
        )
        raise


@dataclass(frozen=True, slots=True, init=False)
class ConsumedWorkspaceDescriptorLease:
    receipt_payload_sha256: str
    authorization_scope_sha256: str
    descriptor_set_sha256: str
    remote_effect_authorized: bool
    path_reopen_allowed: bool
    _descriptor_set: _DescriptorSet
    _seal: object

    def __new__(cls, *args: Any, **kwargs: Any) -> "ConsumedWorkspaceDescriptorLease":
        raise TypeError("descriptor leases are owner-issued only")

    @classmethod
    def _from_owner(
        cls,
        *,
        receipt_payload_sha256: str,
        authorization_scope_sha256: str,
        descriptor_set: _DescriptorSet,
        token: object,
    ) -> "ConsumedWorkspaceDescriptorLease":
        _assert_owner_binding()
        if cls is not _owner_issued_type("ConsumedWorkspaceDescriptorLease") or token is not _LEASE_TOKEN:
            raise DirectRootOwnerError("descriptor lease seal differs")
        descriptor_set.assert_owner_sealed()
        value = object.__new__(cls)
        object.__setattr__(value, "receipt_payload_sha256", receipt_payload_sha256)
        object.__setattr__(value, "authorization_scope_sha256", authorization_scope_sha256)
        object.__setattr__(value, "descriptor_set_sha256", descriptor_set.descriptor_set_sha256)
        object.__setattr__(value, "remote_effect_authorized", False)
        object.__setattr__(value, "path_reopen_allowed", False)
        object.__setattr__(value, "_descriptor_set", descriptor_set)
        object.__setattr__(value, "_seal", _LEASE_TOKEN)
        return value

    def assert_owner_sealed(self) -> "ConsumedWorkspaceDescriptorLease":
        _assert_owner_binding()
        _require(type(self) is ConsumedWorkspaceDescriptorLease and self._seal is _LEASE_TOKEN, "descriptor lease seal differs")
        self._descriptor_set.assert_owner_sealed()
        _require(
            self.descriptor_set_sha256 == self._descriptor_set.descriptor_set_sha256
            and self.remote_effect_authorized is False
            and self.path_reopen_allowed is False,
            "descriptor lease binding differs",
        )
        return self

    def __copy__(self) -> "ConsumedWorkspaceDescriptorLease":
        raise TypeError("descriptor leases are not clonable")

    def __deepcopy__(self, memo: dict[int, Any]) -> "ConsumedWorkspaceDescriptorLease":
        del memo
        raise TypeError("descriptor leases are not clonable")

    def __reduce__(self) -> object:
        raise TypeError("descriptor leases are not serializable")

    def __reduce_ex__(self, protocol: int) -> object:
        del protocol
        raise TypeError("descriptor leases are not serializable")


@dataclass(slots=True)
class _CapabilityState:
    capability: object
    evidence: StableRootIdentityEvidence
    receipt: FreshRootObservationReceipt
    profile_bytes: bytes
    authorization_bytes: bytes
    descriptor_set: _DescriptorSet
    descriptor_handles: tuple[object, ...]
    descriptor_mode: str
    descriptor_component_names: tuple[str, ...]
    descriptor_component_identities: tuple[tuple[int, ...], ...]
    descriptor_set_sha256: str
    descriptor_bundle: _OwnedDescriptorBundle | None
    clock: Callable[[], datetime]
    lock: threading.Lock
    consumed: bool = False
    invalidated: bool = False
    latest_now: datetime | None = None


_CAPABILITY_REGISTRY_LOCK = threading.Lock()
_CAPABILITY_REGISTRY: dict[int, _CapabilityState] = {}


def _register_capability(
    capability: object,
    state: _CapabilityState,
) -> None:
    _require(
        state.capability is capability,
        "capability owner state identity differs",
    )
    key = id(capability)
    with _CAPABILITY_REGISTRY_LOCK:
        _require(
            key not in _CAPABILITY_REGISTRY,
            "capability owner state identity is already registered",
        )
        _CAPABILITY_REGISTRY[key] = state


def _capability_state(capability: object) -> _CapabilityState:
    with _CAPABILITY_REGISTRY_LOCK:
        state = _CAPABILITY_REGISTRY.get(id(capability))
    _require(
        type(state) is _CapabilityState
        and state.capability is capability,
        "capability owner state is unavailable",
    )
    return state


def _trusted_capability_now(state: _CapabilityState) -> datetime:
    current = state.clock()
    _format_utc(current)
    if state.latest_now is not None:
        _require(
            current >= state.latest_now,
            "trusted clock moved backward",
        )
    state.latest_now = current
    return current


def _assert_capability_current(
    capability: "SingleUseWorkspaceDescriptorCapability",
    state: _CapabilityState,
) -> None:
    _assert_owner_binding()
    _require(
        type(capability) is SingleUseWorkspaceDescriptorCapability
        and capability._seal is _CAPABILITY_TOKEN,
        "workspace capability seal differs",
    )
    _require(
        capability.evidence is state.evidence
        and capability.receipt is state.receipt
        and capability._evidence_identity is state.evidence
        and capability._receipt_identity is state.receipt,
        "workspace capability portable artifact identity differs",
    )
    _require(
        capability._profile_bytes == state.profile_bytes
        and capability._authorization_bytes == state.authorization_bytes,
        "workspace capability canonical snapshot differs",
    )
    _require(
        capability._descriptor_set is state.descriptor_set
        and capability._descriptor_handles is state.descriptor_handles
        and state.descriptor_set._mode == state.descriptor_mode
        and state.descriptor_set._component_names
        == state.descriptor_component_names
        and state.descriptor_set._component_identities
        == state.descriptor_component_identities
        and state.descriptor_set.descriptor_set_sha256
        == state.descriptor_set_sha256
        and state.descriptor_set._descriptor_bundle is state.descriptor_bundle,
        "capability descriptor set differs",
    )
    state.evidence.assert_owner_sealed()
    state.receipt.assert_owner_sealed()
    profile = validate_direct_execution_profile(
        json.loads(state.profile_bytes)
    )
    trusted_now = _trusted_capability_now(state)
    authorization = validate_direct_execution_authorization(
        json.loads(state.authorization_bytes),
        now=trusted_now,
    )
    receipt = validate_fresh_root_observation_receipt(
        state.receipt.document(),
        now=trusted_now,
    )
    state.descriptor_set.assert_owner_sealed()
    _require(
        state.descriptor_set._opaque_handles is state.descriptor_handles,
        "capability descriptor set differs",
    )
    _require(
        profile["profile_payload_sha256"]
        == authorization["profile"]["profile_payload_sha256"]
        == receipt["profile"]["profile_payload_sha256"],
        "capability profile replay differs",
    )
    _require(
        state.evidence.document()["evidence_payload_sha256"]
        == authorization["root_evidence"]["evidence_payload_sha256"]
        == receipt["stable_root_evidence"]["evidence_payload_sha256"],
        "capability stable evidence replay differs",
    )
    _require(
        authorization["scope"]["authorization_scope_sha256"]
        == receipt["authorization"]["authorization_scope_sha256"],
        "capability authorization scope replay differs",
    )
    _require(
        receipt["observed_root"]["descriptor_set_sha256"]
        == state.descriptor_set.descriptor_set_sha256,
        "capability descriptor set differs",
    )
    _require(
        receipt["observed_root"]["identity"]["identity_chain_sha256"]
        == state.descriptor_set.identity_chain_sha256,
        "capability descriptor identity differs",
    )
    _require(
        receipt["observed_root"]["workspace_binding_sha256"]
        == state.descriptor_set.workspace_binding_sha256,
        "capability descriptor workspace differs",
    )


@dataclass(frozen=True, slots=True, init=False)
class SingleUseWorkspaceDescriptorCapability:
    evidence: StableRootIdentityEvidence
    receipt: FreshRootObservationReceipt
    _evidence_identity: StableRootIdentityEvidence
    _receipt_identity: FreshRootObservationReceipt
    _profile_bytes: bytes
    _authorization_bytes: bytes
    _descriptor_set: _DescriptorSet
    _descriptor_handles: tuple[object, ...]
    _seal: object

    def __new__(cls, *args: Any, **kwargs: Any) -> "SingleUseWorkspaceDescriptorCapability":
        raise TypeError("workspace descriptor capabilities are owner-issued only")

    @classmethod
    def _from_owner(
        cls,
        *,
        evidence: StableRootIdentityEvidence,
        receipt: FreshRootObservationReceipt,
        profile: dict[str, Any],
        authorization: dict[str, Any],
        descriptor_set: _DescriptorSet,
        clock: Callable[[], datetime],
        token: object,
    ) -> "SingleUseWorkspaceDescriptorCapability":
        _assert_owner_binding()
        if cls is not _owner_issued_type("SingleUseWorkspaceDescriptorCapability") or token is not _CAPABILITY_TOKEN:
            raise DirectRootOwnerError("workspace capability seal differs")
        value = object.__new__(cls)
        object.__setattr__(value, "evidence", evidence)
        object.__setattr__(value, "receipt", receipt)
        object.__setattr__(value, "_evidence_identity", evidence)
        object.__setattr__(value, "_receipt_identity", receipt)
        object.__setattr__(value, "_profile_bytes", canonical_bytes(profile))
        object.__setattr__(value, "_authorization_bytes", canonical_bytes(authorization))
        object.__setattr__(value, "_descriptor_set", descriptor_set)
        object.__setattr__(
            value,
            "_descriptor_handles",
            descriptor_set._opaque_handles,
        )
        object.__setattr__(value, "_seal", _CAPABILITY_TOKEN)
        _register_capability(
            value,
            _CapabilityState(
                capability=value,
                evidence=evidence,
                receipt=receipt,
                profile_bytes=canonical_bytes(profile),
                authorization_bytes=canonical_bytes(authorization),
                descriptor_set=descriptor_set,
                descriptor_handles=descriptor_set._opaque_handles,
                descriptor_mode=descriptor_set._mode,
                descriptor_component_names=descriptor_set._component_names,
                descriptor_component_identities=(
                    descriptor_set._component_identities
                ),
                descriptor_set_sha256=descriptor_set.descriptor_set_sha256,
                descriptor_bundle=descriptor_set._descriptor_bundle,
                clock=clock,
                lock=threading.Lock(),
            ),
        )
        if descriptor_set._mode == "posix_nofollow":
            bundle = descriptor_set._descriptor_bundle
            _require(
                type(bundle) is _OwnedDescriptorBundle,
                "workspace capability descriptor bundle differs",
            )
            _transfer_descriptor_bundle_to_capability_once(bundle)
        return value

    def portable_receipt(self) -> dict[str, Any]:
        return self.receipt.document()

    def assert_current(self) -> "SingleUseWorkspaceDescriptorCapability":
        state = _capability_state(self)
        with state.lock:
            if state.invalidated:
                raise DirectRootOwnerError(
                    "workspace descriptor capability is terminally invalidated"
                )
            try:
                _assert_capability_current(self, state)
            except BaseException:
                if state.descriptor_bundle is not None:
                    state.invalidated = True
                    _close_descriptor_bundle_once(
                        state.descriptor_bundle,
                        owner="capability",
                    )
                raise
        return self

    def consume_once(self) -> ConsumedWorkspaceDescriptorLease:
        """Replay under one lock and consume the retained offline handle model."""
        state = _capability_state(self)
        with state.lock:
            if state.consumed:
                raise DirectRootOwnerError("workspace descriptor capability is already consumed")
            if state.invalidated:
                raise DirectRootOwnerError(
                    "workspace descriptor capability is terminally invalidated"
                )
            try:
                _assert_capability_current(self, state)
            except BaseException:
                if state.descriptor_bundle is not None:
                    state.invalidated = True
                    _close_descriptor_bundle_once(
                        state.descriptor_bundle,
                        owner="capability",
                    )
                raise
            state.consumed = True
            receipt = state.receipt.document()
            return ConsumedWorkspaceDescriptorLease._from_owner(
                receipt_payload_sha256=receipt["receipt_payload_sha256"],
                authorization_scope_sha256=receipt["authorization"]["authorization_scope_sha256"],
                descriptor_set=state.descriptor_set,
                token=_LEASE_TOKEN,
            )

    def __copy__(self) -> "SingleUseWorkspaceDescriptorCapability":
        raise TypeError("workspace descriptor capabilities are not clonable")

    def __deepcopy__(self, memo: dict[int, Any]) -> "SingleUseWorkspaceDescriptorCapability":
        del memo
        raise TypeError("workspace descriptor capabilities are not clonable")

    def __reduce__(self) -> object:
        raise TypeError("workspace descriptor capabilities are not serializable")

    def __reduce_ex__(self, protocol: int) -> object:
        del protocol
        raise TypeError("workspace descriptor capabilities are not serializable")


@dataclass(slots=True)
class _DirectRootOwnerState:
    owner: object
    clock: Callable[[], datetime]
    nonce_source: Callable[[], str]
    lock: threading.Lock
    fresh_used: bool = False


_DIRECT_ROOT_OWNER_REGISTRY_LOCK = threading.Lock()
_DIRECT_ROOT_OWNER_REGISTRY: dict[int, _DirectRootOwnerState] = {}


def _register_direct_root_owner(
    owner: object,
    state: _DirectRootOwnerState,
) -> None:
    _require(state.owner is owner, "direct-root owner state identity differs")
    with _DIRECT_ROOT_OWNER_REGISTRY_LOCK:
        _require(
            id(owner) not in _DIRECT_ROOT_OWNER_REGISTRY,
            "direct-root owner state is already registered",
        )
        _DIRECT_ROOT_OWNER_REGISTRY[id(owner)] = state


def _direct_root_owner_state(owner: object) -> _DirectRootOwnerState:
    _assert_owner_binding()
    with _DIRECT_ROOT_OWNER_REGISTRY_LOCK:
        state = _DIRECT_ROOT_OWNER_REGISTRY.get(id(owner))
    _require(
        type(owner) is DirectRootOwnerContractOwner
        and type(state) is _DirectRootOwnerState
        and state.owner is owner,
        "direct-root owner state is unavailable",
    )
    return state


def _lock_active_descriptor_bundles_before_fork() -> None:
    global _AT_FORK_ACTIVE_BUNDLE_STATES

    _DESCRIPTOR_BUNDLE_REGISTRY_LOCK.acquire()
    states = tuple(
        sorted(
            _ACTIVE_DESCRIPTOR_BUNDLE_REGISTRY.values(),
            key=lambda state: id(state.bundle),
        )
    )
    for state in states:
        state.lock.acquire()
    _AT_FORK_ACTIVE_BUNDLE_STATES = states


def _release_active_descriptor_bundles_after_fork_in_parent() -> None:
    global _AT_FORK_ACTIVE_BUNDLE_STATES

    for state in reversed(_AT_FORK_ACTIVE_BUNDLE_STATES):
        state.lock.release()
    _AT_FORK_ACTIVE_BUNDLE_STATES = ()
    _DESCRIPTOR_BUNDLE_REGISTRY_LOCK.release()


def _revoke_active_descriptor_bundles_after_fork_in_child() -> None:
    global _CAPABILITY_REGISTRY_LOCK
    global _DESCRIPTOR_BUNDLE_REGISTRY_LOCK
    global _DIRECT_ROOT_OWNER_REGISTRY_LOCK
    global _AT_FORK_ACTIVE_BUNDLE_STATES

    for state in _AT_FORK_ACTIVE_BUNDLE_STATES:
        if (
            _ACTIVE_DESCRIPTOR_BUNDLE_REGISTRY.get(id(state.bundle)) is state
            and not state.closed
        ):
            state.closed = True
            _close_directory_descriptors(state.descriptors)
    _ACTIVE_DESCRIPTOR_BUNDLE_REGISTRY.clear()
    for state in reversed(_AT_FORK_ACTIVE_BUNDLE_STATES):
        state.lock.release()
    _AT_FORK_ACTIVE_BUNDLE_STATES = ()
    _DESCRIPTOR_BUNDLE_REGISTRY_LOCK.release()

    _DESCRIPTOR_BUNDLE_REGISTRY_LOCK = threading.RLock()
    _CAPABILITY_REGISTRY_LOCK = threading.Lock()
    _DIRECT_ROOT_OWNER_REGISTRY_LOCK = threading.Lock()
    for state in _DESCRIPTOR_BUNDLE_REGISTRY.values():
        state.lock = threading.Lock()
    for state in _CAPABILITY_REGISTRY.values():
        state.lock = threading.Lock()
    for state in _DIRECT_ROOT_OWNER_REGISTRY.values():
        state.lock = threading.Lock()


if hasattr(os, "register_at_fork"):
    os.register_at_fork(
        before=_lock_active_descriptor_bundles_before_fork,
        after_in_parent=_release_active_descriptor_bundles_after_fork_in_parent,
        after_in_child=_revoke_active_descriptor_bundles_after_fork_in_child,
    )


class DirectRootOwnerContractOwner:
    """Sole owner for synthetic tests and production POSIX observations."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime],
        nonce_source: Callable[[], str],
        _factory_token: object,
    ) -> None:
        _assert_owner_binding()
        if (
            type(self) is not _owner_issued_type("DirectRootOwnerContractOwner")
            or _factory_token
            not in {_TEST_FACTORY_TOKEN, _BACKEND_FACTORY_TOKEN}
            or not callable(clock)
            or not callable(nonce_source)
        ):
            raise TypeError("direct-root owner requires its exact owner factory")
        _register_direct_root_owner(
            self,
            _DirectRootOwnerState(
                owner=self,
                clock=clock,
                nonce_source=nonce_source,
                lock=threading.Lock(),
            ),
        )

    @classmethod
    def for_posix_backend(cls) -> "DirectRootOwnerContractOwner":
        """Create the fixed backend observer owner with no caller configuration."""
        _assert_owner_binding()
        if cls is not _owner_issued_type("DirectRootOwnerContractOwner"):
            raise TypeError("direct-root backend owner class differs")
        return cls(
            clock=_system_utc_now,
            nonce_source=_system_nonce,
            _factory_token=_BACKEND_FACTORY_TOKEN,
        )

    @classmethod
    def _for_testing(
        cls,
        *,
        clock: Callable[[], datetime],
        nonce_source: Callable[[], str],
        _test_token: object,
    ) -> "DirectRootOwnerContractOwner":
        if _test_token is not _TEST_FACTORY_TOKEN:
            raise TypeError("direct-root private test token differs")
        return cls(
            clock=clock,
            nonce_source=nonce_source,
            _factory_token=_TEST_FACTORY_TOKEN,
        )

    def _snapshot_for_testing(
        self,
        *,
        canonical_root: str,
        component_identity_seeds: list[str],
        project: str,
        fresh_project: bool = True,
        containment_verified: bool = True,
        no_symlink_verified: bool = True,
        _test_token: object,
    ) -> _OwnerRootIdentitySnapshot:
        _direct_root_owner_state(self)
        if _test_token is not _TEST_FACTORY_TOKEN:
            raise TypeError("direct-root snapshot test token differs")
        root = _absolute_root(canonical_root, "owner snapshot root")
        _require(
            type(component_identity_seeds) is list
            and component_identity_seeds
            and all(type(seed) is str and seed for seed in component_identity_seeds),
            "owner snapshot identity seeds differ",
        )
        parts = PurePosixPath(root).parts[1:]
        _require(len(component_identity_seeds) == len(parts), "owner snapshot component count differs")
        components = [
            {
                "ordinal": str(index),
                "component_path_sha256": hashlib.sha256(
                    ("/" + "/".join(parts[: index + 1])).encode("utf-8")
                ).hexdigest(),
                "identity_sha256": hashlib.sha256(seed.encode("utf-8")).hexdigest(),
            }
            for index, seed in enumerate(component_identity_seeds)
        ]
        return _OwnerRootIdentitySnapshot._from_owner(
            canonical_root=root,
            components=components,
            project=project,
            fresh_project=fresh_project,
            containment_verified=containment_verified,
            no_symlink_verified=no_symlink_verified,
            token=_SNAPSHOT_TOKEN,
        )

    def _seal_stable_evidence(
        self,
        *,
        policy: dict[str, Any],
        identity_document: dict[str, Any],
    ) -> StableRootIdentityEvidence:
        _direct_root_owner_state(self)
        chain = _component_chain(
            identity_document,
            "stable owner root identity",
        )
        _require(
            chain["canonical_root"] == policy["declared_allowed_root"],
            "stable evidence expected root differs from profile policy",
        )
        document = {
            "schema": STABLE_EVIDENCE_SCHEMA,
            "backend_kind": BACKEND_KIND,
            "root_policy_owner": copy.deepcopy(policy["root_policy_owner"]),
            "profile_policy": {
                "schema": policy["schema"],
                "profile_id": policy["profile_id"],
                "profile_payload_sha256": policy["profile_payload_sha256"],
            },
            "reviewed_root_policy": {
                "policy": ROOT_POLICY,
                "declared_allowed_root": policy["declared_allowed_root"],
                "path_normalization_version": PATH_NORMALIZATION_VERSION,
                "containment_version": CONTAINMENT_VERSION,
            },
            "expected_root_identity": copy.deepcopy(chain),
            "derivation": {
                "project_component_grammar": PROJECT_GRAMMAR,
                "scratch_component": SCRATCH_COMPONENT,
                "scratch_is_project_relative": True,
            },
            "safety": copy.deepcopy(SAFETY),
            "stable_projection": {
                "observation_time_excluded": True,
                "expiry_excluded": True,
                "nonce_excluded": True,
                "receipt_id_excluded": True,
                "per_operation_values_excluded": True,
            },
            "evidence_payload_sha256": "",
        }
        validated = validate_stable_root_identity_evidence(
            _finalize(document, "evidence_payload_sha256")
        )
        sealed = StableRootIdentityEvidence._from_owner(
            validated,
            token=_SEAL_TOKEN,
        )
        sealed.assert_owner_sealed()
        return sealed

    def issue_stable_evidence(
        self,
        profile_policy: dict[str, Any],
        expected_identity: _OwnerRootIdentitySnapshot,
    ) -> StableRootIdentityEvidence:
        _direct_root_owner_state(self)
        policy = validate_profile_policy(profile_policy)
        _require(type(expected_identity) is _OwnerRootIdentitySnapshot, "stable evidence requires exact owner snapshot")
        expected_identity.assert_owner_sealed()
        return self._seal_stable_evidence(
            policy=policy,
            identity_document=expected_identity.identity_document(),
        )

    def issue_stable_evidence_from_reviewed_profile(
        self,
        profile_policy: dict[str, Any],
    ) -> StableRootIdentityEvidence:
        """Observe only the policy-owned root and publish its stable identity."""
        _direct_root_owner_state(self)
        policy = validate_profile_policy(profile_policy)
        components, _names, _identities, descriptor_bundle = (
            _open_root_components_no_follow(policy["declared_allowed_root"])
        )
        try:
            identity_document = {
                "canonical_root": policy["declared_allowed_root"],
                "components": components,
                "identity_chain_sha256": digest({
                    "schema": "auto-g16-root-component-identity-chain/1",
                    "canonical_root": policy["declared_allowed_root"],
                    "components": components,
                }),
            }
            return self._seal_stable_evidence(
                policy=policy,
                identity_document=identity_document,
            )
        finally:
            _close_descriptor_bundle_once(
                descriptor_bundle,
                owner="observer",
            )

    def issue_fresh_capability_once(
        self,
        *,
        profile: dict[str, Any],
        stable_evidence: StableRootIdentityEvidence,
        authorization: dict[str, Any],
        observation: _OwnerRootIdentitySnapshot,
    ) -> SingleUseWorkspaceDescriptorCapability:
        state = _direct_root_owner_state(self)
        with state.lock:
            if state.fresh_used:
                raise DirectRootOwnerError("direct-root owner fresh issuance is single-use")
            _assert_owner_binding()
            _require(type(stable_evidence) is StableRootIdentityEvidence, "fresh issuance requires exact stable evidence")
            _require(type(observation) is _OwnerRootIdentitySnapshot, "fresh issuance requires exact owner observation")
            stable_evidence.assert_owner_sealed()
            observation.assert_owner_sealed()
            validated_profile = validate_direct_execution_profile(profile)
            now = state.clock()
            validated_authorization = validate_direct_execution_authorization(
                authorization,
                now=now,
            )
            evidence = stable_evidence.document()
            _require(validated_profile["stable_root_identity_evidence_sha256"] == evidence["evidence_payload_sha256"], "fresh issuance profile/stable mismatch")
            _require(validated_authorization["profile"]["profile_payload_sha256"] == validated_profile["profile_payload_sha256"], "fresh issuance authorization/profile mismatch")
            _require(validated_authorization["root_evidence"]["evidence_payload_sha256"] == evidence["evidence_payload_sha256"], "fresh issuance authorization/stable mismatch")
            _require(observation.identity_chain_sha256 == evidence["expected_root_identity"]["identity_chain_sha256"], "fresh observation root identity drifted")
            _require(observation.canonical_root == validated_profile["declared_allowed_root"], "fresh observation root drifted")
            _require(observation.project == validated_authorization["workspace"]["project"], "fresh observation project drifted")
            _require(observation.workspace_binding_sha256 == validated_authorization["workspace"]["workspace_binding_sha256"], "fresh observation workspace drifted")
            _require(
                observation.fresh_project
                and observation.containment_verified
                and observation.no_symlink_verified,
                "fresh observation safety checks failed",
            )
            nonce = state.nonce_source()
            _text(nonce, "owner nonce", NONCE_RE)
            age_text = validated_authorization["fresh_observation_rules"][
                "maximum_receipt_age_seconds"
            ]
            age = _positive_decimal(
                age_text,
                "fresh issuance maximum receipt age",
                maximum=300,
            )
            observed_at = _format_utc(now)
            expires_at = _format_utc(now + timedelta(seconds=age))
            scope = validated_authorization["scope"]
            document = {
                "schema": FRESH_RECEIPT_SCHEMA,
                "profile": {
                    "profile_id": validated_profile["profile_id"],
                    "profile_payload_sha256": validated_profile["profile_payload_sha256"],
                },
                "stable_root_evidence": {
                    "evidence_payload_sha256": evidence["evidence_payload_sha256"],
                    "expected_identity_chain_sha256": evidence["expected_root_identity"]["identity_chain_sha256"],
                },
                "authorization": {
                    "authorization_id": validated_authorization["authorization_id"],
                    "authorization_payload_sha256": validated_authorization["authorization_payload_sha256"],
                    "authorization_scope_sha256": scope["authorization_scope_sha256"],
                },
                "operation": {
                    "operation_version": FRESH_OPERATION_VERSION,
                    "operation": scope["operation"],
                    "scientific_task_id": scope["scientific_task_id"],
                    "attempt_id": scope["attempt_id"],
                    "nonce": nonce,
                },
                "window": {
                    "observed_at": observed_at,
                    "expires_at": expires_at,
                    "maximum_receipt_age_seconds": age_text,
                },
                "observed_root": {
                    "identity": observation.identity_document(),
                    "project": observation.project,
                    "remote_workdir": observation.remote_workdir,
                    "scratch_workdir": observation.scratch_workdir,
                    "workspace_binding_sha256": observation.workspace_binding_sha256,
                    "fresh_project": True,
                    "containment_verified": True,
                    "no_symlink_verified": True,
                    "descriptor_set_sha256": observation._descriptor_set.descriptor_set_sha256,
                },
                "comparison": {
                    "profile_matches": True,
                    "stable_evidence_matches": True,
                    "authorization_scope_matches": True,
                    "root_identity_matches": True,
                    "workspace_matches": True,
                    "classification": "verified",
                },
                "authority": {
                    "portable_receipt_authorizes_effect": False,
                    "descriptor_capability_required": True,
                    "single_consumption_required": True,
                    "descriptor_relative_operations_required": True,
                    "path_reopen_allowed": False,
                    "automatic_retry": False,
                    "remote_effect_performed": False,
                },
                "receipt_payload_sha256": "",
            }
            validated_receipt = validate_fresh_root_observation_receipt(
                _finalize(document, "receipt_payload_sha256"),
                now=now,
            )
            receipt = FreshRootObservationReceipt._from_owner(
                validated_receipt,
                token=_SEAL_TOKEN,
            )
            capability = SingleUseWorkspaceDescriptorCapability._from_owner(
                evidence=stable_evidence,
                receipt=receipt,
                profile=validated_profile,
                authorization=validated_authorization,
                descriptor_set=observation._descriptor_set,
                clock=state.clock,
                token=_CAPABILITY_TOKEN,
            )
            capability.assert_current()
            state.fresh_used = True
            return capability

    def issue_fresh_capability_from_reviewed_profile_once(
        self,
        *,
        profile: dict[str, Any],
        stable_evidence: StableRootIdentityEvidence,
        authorization: dict[str, Any],
    ) -> SingleUseWorkspaceDescriptorCapability:
        """Make one fresh no-follow observation and retain those descriptors."""
        state = _direct_root_owner_state(self)
        _require(
            type(stable_evidence) is StableRootIdentityEvidence,
            "backend fresh issuance requires exact stable evidence",
        )
        stable_evidence.assert_owner_sealed()
        validated_profile = validate_direct_execution_profile(profile)
        now = state.clock()
        validated_authorization = validate_direct_execution_authorization(
            authorization,
            now=now,
        )
        evidence = stable_evidence.document()
        _require(
            validated_profile["stable_root_identity_evidence_sha256"]
            == evidence["evidence_payload_sha256"]
            == validated_authorization["root_evidence"][
                "evidence_payload_sha256"
            ],
            "backend fresh issuance stable evidence differs",
        )
        _require(
            validated_authorization["profile"]["profile_payload_sha256"]
            == validated_profile["profile_payload_sha256"],
            "backend fresh issuance profile differs",
        )
        observation = _observe_workspace_no_follow(
            canonical_root=validated_profile["declared_allowed_root"],
            project=validated_authorization["workspace"]["project"],
        )
        try:
            return self.issue_fresh_capability_once(
                profile=validated_profile,
                stable_evidence=stable_evidence,
                authorization=validated_authorization,
                observation=observation,
            )
        except BaseException:
            descriptor_set = observation._descriptor_set
            if (
                type(descriptor_set) is _DescriptorSet
                and descriptor_set._mode == "posix_nofollow"
            ):
                bundle = descriptor_set._descriptor_bundle
                _require(
                    type(bundle) is _OwnedDescriptorBundle,
                    "backend descriptor bundle differs",
                )
                _close_descriptor_bundle_once(
                    bundle,
                    owner="observer",
                )
            raise


def _parse_exact_json(raw: bytes, label: str) -> dict[str, Any]:
    _require(raw and len(raw) <= MAX_DOCUMENT_BYTES, f"{label} size is outside the bound")
    _require(not raw.startswith(b"\xef\xbb\xbf"), f"{label} must not contain a UTF-8 BOM")

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise DirectRootOwnerError(f"{label} repeats JSON key: {key}")
            result[key] = value
        return result

    def reject_float(token: str) -> Any:
        raise DirectRootOwnerError(f"{label} contains a non-integer number: {token}")

    def reject_constant(token: str) -> Any:
        raise DirectRootOwnerError(f"{label} contains a non-standard number: {token}")

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=pairs,
            parse_float=reject_float,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DirectRootOwnerError(f"{label} is not strict UTF-8 JSON: {exc}") from exc
    _require(type(value) is dict, f"{label} must contain one object")
    return value


def load_exact_document(
    path: Path,
    validator: Callable[[Any], dict[str, Any]],
) -> dict[str, Any]:
    _require(isinstance(path, Path) and path.is_absolute(), "contract path must be an absolute Path")
    snapshot = _stable_file(path)
    document = _parse_exact_json(snapshot.source_bytes, path.name)
    validated = validator(document)
    _require(canonical_bytes(validated) == snapshot.source_bytes, f"{path.name} bytes are not canonical")
    _require(_stable_file(path) == snapshot, f"{path.name} changed after validation")
    return validated


_OWNER_ISSUED_TYPE_NAMES = (
    "StableRootIdentityEvidence",
    "FreshRootObservationReceipt",
    "ConsumedWorkspaceDescriptorLease",
    "SingleUseWorkspaceDescriptorCapability",
    "DirectRootOwnerContractOwner",
)


def _capture_owner_binding() -> _OwnerModuleBinding:
    if __name__ != MODULE_NAME:
        raise ImportError("direct-root owner must load under its canonical module name")
    module = sys.modules.get(MODULE_NAME)
    if not isinstance(module, types.ModuleType):
        raise ImportError("canonical direct-root owner module is unavailable")
    path = _owner_path()
    if _module_origin(module) != (path, path):
        raise ImportError("canonical direct-root owner origin differs")
    issued: list[tuple[str, type]] = []
    for name in _OWNER_ISSUED_TYPE_NAMES:
        value = getattr(module, name, None)
        if (
            not isinstance(value, type)
            or value.__module__ != MODULE_NAME
            or value.__qualname__ != name
        ):
            raise ImportError(f"canonical direct-root owner class identity differs: {name}")
        issued.append((name, value))
    return _OwnerModuleBinding(module=module, issued_types=tuple(issued), source=_OWNER_SOURCE)


def _assert_owner_binding() -> None:
    binding = _OWNER_MODULE_BINDING
    _require(isinstance(binding, _OwnerModuleBinding), "direct-root owner module is not registered")
    path = _owner_path()
    _require(
        sys.modules.get(MODULE_NAME) is binding.module
        and _module_origin(binding.module) == (path, path)
        and _stable_file(path) == binding.source,
        "direct-root owner module/source identity differs",
    )
    for name, expected in binding.issued_types:
        _require(getattr(binding.module, name, None) is expected, f"direct-root owner class identity differs: {name}")


def _owner_issued_type(name: str) -> type:
    for issued_name, issued_type in _OWNER_MODULE_BINDING.issued_types:
        if issued_name == name:
            return issued_type
    raise DirectRootOwnerError(f"direct-root owner issued type is unavailable: {name}")


_OWNER_MODULE_BINDING: _OwnerModuleBinding | None = None
_OWNER_MODULE_BINDING = _capture_owner_binding()
