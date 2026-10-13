#!/usr/bin/env python3
"""Validate and build Auto-G16 v2.6 platform contracts entirely offline."""

from __future__ import annotations

import argparse
import copy
import errno
import hashlib
import hmac
import importlib.util
import json
import os
import re
import secrets
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from types import ModuleType
from typing import Any, Sequence, TypedDict


PROFILE_SCHEMA = "auto-g16-execution-profile/1"
BINDING_SCHEMA = "auto-g16-transport-identity-binding/1"
ATTESTATION_RECEIPT_SCHEMA = "auto-g16-transport-identity-attestation-receipt/1"
FIRST_HOP_REQUEST_SCHEMA = "auto-g16-first-hop-identity-attestation-request/1"
NESTED_HOP_REQUEST_SCHEMA = "auto-g16-nested-hop-identity-attestation-request/1"
CAPABILITY_SCHEMA = "auto-g16-execution-capability-report/1"
CATALOG_SCHEMA = "auto-g16-resource-catalog/1"
LEGACY_MAPPING_SCHEMA = "auto-g16-legacy-runtime-mapping-result/1"
SANITIZATION_VERSION = "auto-g16-capability-sanitization/1"
LEGACY_RUNTIME_SCHEMA = "auto-g16-runtime-config/1"

FIXED_REMOTE_ROOT = "/home/user100/SDL"
CATALOG_ID = "legacy-pbs-resource-catalog"
SCHEDULER_DIALECT = "pbs_legacy_v1"
MAX_ATTESTATION_WINDOW_SECONDS = 300
MAX_CONFIG_SOURCES = 256
MAX_CONFIG_SOURCE_BUNDLE_BYTES = 8 * 1024 * 1024
FIRST_HOP_OPERATION_VERSION = "first-hop-identity-attestation/1"
NESTED_HOP_OPERATION_VERSION = "nested-hop-identity-attestation/1"

SHA_RE = re.compile(r"^[a-f0-9]{64}$")
ID_RE = re.compile(r"^[a-z][a-z0-9._-]{0,63}$")
NONCE_RE = re.compile(r"^[a-f0-9]{32,128}$")
TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")
RFC3339_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
DECIMAL_INTEGER_RE = re.compile(r"^(?:0|-[1-9][0-9]*|[1-9][0-9]*)$")

BACKENDS = {"legacy_rtwin_pbs", "direct_ssh_pbs"}
DECLARED_CAPABILITIES = {
    "typed_identity_attestation",
    "pbs_submit_once",
    "pbs_inspect_exact",
    "pbs_fetch_allowlist",
    "pbs_cancel_exact",
}
UNSUPPORTED_BACKENDS = ("local_gaussian", "slurm", "mcp")
UNKNOWN_LIVE_PROPERTIES = (
    "network_reachability",
    "license_validity",
    "gaussian_availability",
    "live_authority",
    "transport_identity_attestation",
)
SENSITIVE_REFERENCE_NAMES = {
    ".ssh",
    ".gnupg",
    "authorized_keys",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "id_rsa",
    "known_hosts",
}
SENSITIVE_REFERENCE_SUFFIXES = {".key", ".pem", ".p12", ".pfx", ".ppk"}
LEGACY_RUNTIME_KEYS = {
    "core_python",
    "rdkit_python",
    "chemdraw_pipeline_scripts",
    "rtwin_ssh_config",
    "windows_target",
    "windows_control_socket",
    "windows_project_root",
    "windows_server_config",
    "gaussview_exe",
}
LEGACY_EXECUTION_KEYS = {
    "rtwin_ssh_config",
    "windows_project_root",
    "windows_server_config",
}


class PlatformContractError(ValueError):
    """A platform contract cannot be proved exactly and safely offline."""


class ResourceTuple(TypedDict):
    tier: str
    cores: int
    memory_gb: int


class ResourceCatalog(TypedDict):
    schema: str
    catalog_id: str
    capacity: dict[str, int]
    reviewed_tuples: list[ResourceTuple]
    custom_reviewed_allowed: bool
    walltime_must_be_explicitly_reviewed: bool
    proposal_markers: dict[str, bool]
    catalog_payload_sha256: str


class TransportHop(TypedDict):
    transport_kind: str
    config_source_bundle_sha256: str
    alias_utf8_sha256: str
    effective_target_identity_sha256: str
    host_key_policy: str
    host_key_evidence_sha256: str
    resolver_version: str


class TransportIdentityBinding(TypedDict):
    schema: str
    binding_id: str
    profile_id: str
    hops: list[TransportHop]
    binding_payload_sha256: str


class ExecutionProfile(TypedDict):
    schema: str
    profile_id: str
    backend_kind: str
    transport_config_ref: str
    transport_identity_binding_sha256: str
    scheduler_dialect: str
    gaussian_runtime: dict[str, str]
    workspace_policy: dict[str, Any]
    resource_catalog: ResourceCatalog
    declared_capabilities: list[str]
    profile_payload_sha256: str


class FirstHopIdentityReceipt(TypedDict):
    schema: str
    receipt_kind: str
    profile_sha256: str
    transport_identity_binding_sha256: str
    first_hop_identity_sha256: str
    config_source_bundle_sha256: str
    alias_utf8_sha256: str
    effective_target_identity_sha256: str
    host_key_evidence_sha256: str
    observed_fingerprint_evidence_sha256: str
    request_nonce: str
    issued_at: str
    expires_at: str
    operation_version: str
    classification: str
    read_only_attestation: bool
    automatic_retry: bool
    no_execution_authorization: bool
    receipt_payload_sha256: str


class NestedHopIdentityReceipt(TypedDict):
    schema: str
    receipt_kind: str
    profile_sha256: str
    transport_identity_binding_sha256: str
    first_hop_identity_sha256: str
    first_hop_receipt_sha256: str
    config_source_bundle_sha256: str
    alias_utf8_sha256: str
    effective_target_identity_sha256: str
    host_key_evidence_sha256: str
    request_nonce: str
    issued_at: str
    expires_at: str
    operation_version: str
    classification: str
    read_only_attestation: bool
    automatic_retry: bool
    no_execution_authorization: bool
    receipt_payload_sha256: str


class CapabilityReport(TypedDict):
    schema: str
    profile_id: str
    profile_sha256: str
    backend_kind: str
    transport_identity_binding_sha256: str
    scheduler: dict[str, str]
    gaussian_runtime: dict[str, str]
    configured_typed_operations: list[dict[str, str]]
    unsupported_backends: list[str]
    unknown_live_properties: list[str]
    offline_only: bool
    sanitization_version: str
    report_payload_sha256: str


class LegacyMappingResult(TypedDict):
    schema: str
    mapping_id: str
    source_runtime_schema: str
    source_configured_keys: list[str]
    runtime_execution_subset_sha256: str
    backend_kind: str
    derived_profile_summary: dict[str, Any]
    resource_catalog: ResourceCatalog
    conflicts: list[dict[str, str]]
    migration_performed: bool
    legacy_approval_authorizes_profile_mode: bool
    legacy_approval_authorizes_direct: bool
    live_attestation_required: bool
    mapping_payload_sha256: str


def require(condition: bool, message: str) -> None:
    if not condition:
        raise PlatformContractError(message)


def _reject_constant(token: str) -> None:
    raise PlatformContractError(f"non-standard JSON numeric constant is forbidden: {token}")


def _reject_float(token: str) -> None:
    raise PlatformContractError(f"floating-point or exponent JSON number is forbidden: {token}")


def _parse_integer(token: str) -> int:
    require(DECIMAL_INTEGER_RE.fullmatch(token) is not None, "JSON integer is not canonical decimal syntax")
    require(token != "-0", "negative zero is forbidden")
    return int(token)


def _closed_pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        require(key not in result, f"duplicate JSON key is forbidden: {key}")
        result[key] = value
    return result


def strict_json_loads(raw: bytes | str, *, label: str = "JSON document") -> Any:
    """Decode the RFC strict JSON subset without accepting lossy numbers."""
    if isinstance(raw, bytes):
        require(not raw.startswith(b"\xef\xbb\xbf"), f"{label} must not contain a UTF-8 BOM")
        try:
            text = raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise PlatformContractError(f"{label} is not well-formed UTF-8: {exc}") from exc
    else:
        require(isinstance(raw, str), f"{label} must be bytes or text")
        text = raw
        require(not text.startswith("\ufeff"), f"{label} must not contain a BOM")
        try:
            text.encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise PlatformContractError(f"{label} contains a non-scalar Unicode value: {exc}") from exc
    try:
        return json.loads(
            text,
            object_pairs_hook=_closed_pairs,
            parse_constant=_reject_constant,
            parse_float=_reject_float,
            parse_int=_parse_integer,
        )
    except json.JSONDecodeError as exc:
        raise PlatformContractError(f"malformed {label}: {exc}") from exc


def _encode_string(value: str) -> str:
    pieces = ['"']
    short = {
        '"': '\\"',
        "\\": "\\\\",
        "\b": "\\b",
        "\t": "\\t",
        "\n": "\\n",
        "\f": "\\f",
        "\r": "\\r",
    }
    for character in value:
        codepoint = ord(character)
        require(not 0xD800 <= codepoint <= 0xDFFF, "canonical JSON forbids non-scalar Unicode values")
        if character in short:
            pieces.append(short[character])
        elif codepoint <= 0x1F:
            pieces.append(f"\\u{codepoint:04x}")
        else:
            pieces.append(character)
    pieces.append('"')
    return "".join(pieces)


def _canonical_text(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    require(not isinstance(value, float), "canonical JSON forbids floating-point values")
    if isinstance(value, str):
        return _encode_string(value)
    if isinstance(value, list) or isinstance(value, tuple):
        return "[" + ",".join(_canonical_text(item) for item in value) + "]"
    if isinstance(value, dict):
        require(all(isinstance(key, str) for key in value), "canonical JSON object keys must be strings")
        ordered = sorted(value)
        return "{" + ",".join(
            _encode_string(key) + ":" + _canonical_text(value[key]) for key in ordered
        ) + "}"
    raise PlatformContractError(f"canonical JSON does not support {type(value).__name__}")


def canonical_bytes(value: Any) -> bytes:
    """Return the single v2.6 canonical JSON projection with one terminal LF."""
    return (_canonical_text(value) + "\n").encode("utf-8", errors="strict")


def payload_sha256(document: dict[str, Any], self_field: str) -> str:
    require(self_field in document, f"{self_field} is missing from the document")
    payload = {key: value for key, value in document.items() if key != self_field}
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def finalize(document: dict[str, Any], self_field: str) -> dict[str, Any]:
    result = copy.deepcopy(document)
    result[self_field] = ""
    result[self_field] = payload_sha256(result, self_field)
    return result


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
    require(ID_RE.fullmatch(text) is not None, f"{label} must be a non-sensitive portable identifier")
    return text


def _sha(value: Any, label: str) -> str:
    text = _text(value, label)
    require(SHA_RE.fullmatch(text) is not None, f"{label} must be a lowercase SHA-256")
    require(text != "0" * 64, f"{label} must not use an all-zero sentinel")
    return text


def _positive_integer(value: Any, label: str) -> int:
    require(isinstance(value, int) and not isinstance(value, bool) and value > 0, f"{label} must be a positive integer")
    return value


def _boolean(value: Any, label: str) -> bool:
    require(isinstance(value, bool), f"{label} must be a boolean")
    return value


def _verify_self_hash(document: dict[str, Any], field: str, label: str) -> None:
    actual = _sha(document.get(field), field)
    expected = payload_sha256(document, field)
    require(hmac.compare_digest(actual, expected), f"{label} {field} mismatch")


def _private_reference(value: Any, label: str) -> str:
    text = _text(value, label)
    require("\\" not in text, f"{label} must be an absolute POSIX reference")
    path = PurePosixPath(text)
    require(path.is_absolute() and text != "/", f"{label} must be an absolute non-root POSIX reference")
    require(all(part not in {"", ".", ".."} for part in path.parts[1:]), f"{label} contains unsafe traversal")
    require(text == path.as_posix(), f"{label} must use one normalized lexical POSIX form")
    lowered = {part.lower() for part in path.parts}
    require(not lowered.intersection(SENSITIVE_REFERENCE_NAMES), f"{label} identifies a sensitive credential location")
    require(path.suffix.lower() not in SENSITIVE_REFERENCE_SUFFIXES, f"{label} identifies a sensitive credential file")
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        try:
            opened = os.lstat(current)
        except FileNotFoundError:
            break
        require(not stat.S_ISLNK(opened.st_mode), f"{label} contains a symlink component")
    return text


def _load_resource_owner() -> ModuleType:
    here = Path(__file__).parent
    candidates = (
        here / "resource_efficiency.py",
        here.parent / "skills" / "auto-g16-rtwin-pbs" / "scripts" / "resource_efficiency.py",
    )
    owner_path = next((candidate for candidate in candidates if candidate.is_file()), None)
    require(owner_path is not None, "legacy resource owner is unavailable")
    owner_dir = str(owner_path.parent)
    inserted = owner_dir not in sys.path
    if inserted:
        sys.path.insert(0, owner_dir)
    try:
        spec = importlib.util.spec_from_file_location("auto_g16_resource_catalog_owner", owner_path)
        require(spec is not None and spec.loader is not None, "legacy resource owner cannot be imported")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        if inserted:
            sys.path.remove(owner_dir)


def _resource_facts() -> dict[str, Any]:
    owner = _load_resource_owner()
    require(hasattr(owner, "legacy_resource_catalog_facts"), "legacy resource owner lacks catalog facts")
    facts = owner.legacy_resource_catalog_facts()
    require(isinstance(facts, dict), "legacy resource facts are invalid")
    result = copy.deepcopy(facts)
    reviewed = result.get("reviewed_tuples")
    require(isinstance(reviewed, (list, tuple)), "legacy reviewed resource facts are invalid")
    result["reviewed_tuples"] = [copy.deepcopy(item) for item in reviewed]
    return result


def build_resource_catalog() -> ResourceCatalog:
    facts = _resource_facts()
    document: dict[str, Any] = {
        "schema": CATALOG_SCHEMA,
        "catalog_id": CATALOG_ID,
        **facts,
        "catalog_payload_sha256": "",
    }
    result = finalize(document, "catalog_payload_sha256")
    return validate_resource_catalog(result)


def validate_resource_catalog(document: Any) -> ResourceCatalog:
    catalog = _exact(document, {
        "schema", "catalog_id", "capacity", "reviewed_tuples",
        "custom_reviewed_allowed", "walltime_must_be_explicitly_reviewed",
        "proposal_markers", "catalog_payload_sha256",
    }, "resource catalog")
    require(catalog["schema"] == CATALOG_SCHEMA, "resource catalog schema is unsupported")
    require(catalog["catalog_id"] == CATALOG_ID, "resource catalog id is unsupported")
    capacity = _exact(catalog["capacity"], {"max_job_cores", "max_job_memory_gb"}, "resource capacity")
    _positive_integer(capacity["max_job_cores"], "capacity.max_job_cores")
    _positive_integer(capacity["max_job_memory_gb"], "capacity.max_job_memory_gb")
    reviewed = catalog["reviewed_tuples"]
    require(isinstance(reviewed, list) and reviewed, "reviewed_tuples must be a non-empty array")
    normalized: list[dict[str, Any]] = []
    tiers: set[str] = set()
    for index, item in enumerate(reviewed):
        value = _exact(item, {"tier", "cores", "memory_gb"}, f"reviewed_tuples[{index}]")
        tier = _identifier(value["tier"], f"reviewed_tuples[{index}].tier")
        require(tier not in tiers, "reviewed resource tiers must be unique")
        tiers.add(tier)
        cores = _positive_integer(value["cores"], f"reviewed_tuples[{index}].cores")
        memory = _positive_integer(value["memory_gb"], f"reviewed_tuples[{index}].memory_gb")
        require(cores <= capacity["max_job_cores"], "reviewed cores exceed catalog capacity")
        require(memory <= capacity["max_job_memory_gb"], "reviewed memory exceeds catalog capacity")
        normalized.append({"tier": tier, "cores": cores, "memory_gb": memory})
    _boolean(catalog["custom_reviewed_allowed"], "custom_reviewed_allowed")
    require(catalog["custom_reviewed_allowed"] is True, "legacy custom_reviewed policy changed")
    require(catalog["walltime_must_be_explicitly_reviewed"] is True, "walltime review policy changed")
    markers = _exact(catalog["proposal_markers"], {
        "proposal_only", "calculation_ready", "no_submission_authorization",
    }, "proposal markers")
    require(markers == {
        "proposal_only": True,
        "calculation_ready": False,
        "no_submission_authorization": True,
    }, "resource proposal authority markers changed")
    facts = _resource_facts()
    require(catalog["capacity"] == facts["capacity"], "legacy resource capacity drifted")
    require(normalized == list(facts["reviewed_tuples"]), "legacy reviewed resource tuples drifted")
    require(catalog["custom_reviewed_allowed"] == facts["custom_reviewed_allowed"], "legacy custom policy drifted")
    require(
        catalog["walltime_must_be_explicitly_reviewed"] == facts["walltime_must_be_explicitly_reviewed"],
        "legacy walltime policy drifted",
    )
    require(catalog["proposal_markers"] == facts["proposal_markers"], "legacy proposal markers drifted")
    _verify_self_hash(catalog, "catalog_payload_sha256", "resource catalog")
    return copy.deepcopy(catalog)


def validate_exact_resource(
    catalog: Any,
    *,
    tier: Any,
    cores: Any,
    memory_gb: Any,
    walltime_seconds: Any,
) -> dict[str, Any]:
    validated = validate_resource_catalog(catalog)
    tier_text = _identifier(tier, "resource tier")
    core_count = _positive_integer(cores, "resource cores")
    memory = _positive_integer(memory_gb, "resource memory_gb")
    walltime = _positive_integer(walltime_seconds, "resource walltime_seconds")
    named = {item["tier"]: (item["cores"], item["memory_gb"]) for item in validated["reviewed_tuples"]}
    if tier_text in named:
        require((core_count, memory) == named[tier_text], "named tier conflicts with exact cores/memory")
    else:
        require(tier_text == "custom_reviewed", "resource tier is unsupported")
        require(validated["custom_reviewed_allowed"], "custom_reviewed is not permitted")
    require(core_count <= validated["capacity"]["max_job_cores"], "resource cores exceed capacity")
    require(memory <= validated["capacity"]["max_job_memory_gb"], "resource memory exceeds capacity")
    return {
        "tier": tier_text,
        "cores": core_count,
        "memory_gb": memory,
        "walltime_seconds": walltime,
    }


def build_resource_proposal(catalog: Any, **exact: Any) -> dict[str, Any]:
    validated = validate_resource_catalog(catalog)
    resource = validate_exact_resource(validated, **exact)
    return {
        "resource": resource,
        **copy.deepcopy(validated["proposal_markers"]),
    }


def config_source_bundle_sha256(sources: Sequence[bytes]) -> str:
    """Hash resolver-ordered exact config bytes with unambiguous framing."""
    require(isinstance(sources, Sequence) and not isinstance(sources, (bytes, bytearray, str)), "config sources must be an ordered byte sequence")
    require(bool(sources), "config source bundle must not be empty")
    require(len(sources) <= MAX_CONFIG_SOURCES, "config source bundle contains too many sources")
    digest = hashlib.sha256()
    digest.update(b"auto-g16-config-source-bundle/1\x00")
    digest.update(len(sources).to_bytes(8, "big"))
    total = 0
    for index, source in enumerate(sources):
        require(isinstance(source, bytes), f"config source {index} must be exact bytes")
        total += len(source)
        require(total <= MAX_CONFIG_SOURCE_BUNDLE_BYTES, "config source bundle exceeds the offline size limit")
        digest.update(index.to_bytes(8, "big"))
        digest.update(len(source).to_bytes(8, "big"))
        digest.update(source)
    return digest.hexdigest()


def _validate_hop(document: Any, index: int) -> TransportHop:
    hop = _exact(document, {
        "transport_kind", "config_source_bundle_sha256", "alias_utf8_sha256",
        "effective_target_identity_sha256", "host_key_policy",
        "host_key_evidence_sha256", "resolver_version",
    }, f"transport hop {index}")
    kind = _text(hop["transport_kind"], f"hops[{index}].transport_kind")
    require(kind in {"direct_ssh", "legacy_rtwin_first_hop", "legacy_rtwin_nested_hop"}, "transport hop kind is unsupported")
    for field in (
        "config_source_bundle_sha256", "alias_utf8_sha256",
        "effective_target_identity_sha256", "host_key_evidence_sha256",
    ):
        _sha(hop[field], f"hops[{index}].{field}")
    require(hop["host_key_policy"] == "strict_pinned", "host key policy must be strict_pinned")
    _identifier(hop["resolver_version"], f"hops[{index}].resolver_version")
    return copy.deepcopy(hop)


def build_transport_identity_binding(
    *,
    binding_id: str,
    profile_id: str,
    hops: Sequence[dict[str, Any]],
) -> TransportIdentityBinding:
    document: dict[str, Any] = {
        "schema": BINDING_SCHEMA,
        "binding_id": binding_id,
        "profile_id": profile_id,
        "hops": [copy.deepcopy(item) for item in hops],
        "binding_payload_sha256": "",
    }
    return validate_transport_identity_binding(finalize(document, "binding_payload_sha256"))


def validate_transport_identity_binding(document: Any) -> TransportIdentityBinding:
    binding = _exact(document, {
        "schema", "binding_id", "profile_id", "hops", "binding_payload_sha256",
    }, "transport identity binding")
    require(binding["schema"] == BINDING_SCHEMA, "transport identity binding schema is unsupported")
    _identifier(binding["binding_id"], "binding_id")
    _identifier(binding["profile_id"], "profile_id")
    hops = binding["hops"]
    require(isinstance(hops, list) and len(hops) in {1, 2}, "transport identity binding must contain one or two ordered hops")
    validated = [_validate_hop(item, index) for index, item in enumerate(hops)]
    kinds = [item["transport_kind"] for item in validated]
    require(
        kinds == ["direct_ssh"] or kinds == ["legacy_rtwin_first_hop", "legacy_rtwin_nested_hop"],
        "transport hop order or combination is unsupported",
    )
    _verify_self_hash(binding, "binding_payload_sha256", "transport identity binding")
    return copy.deepcopy(binding)


def _workspace_policy() -> dict[str, Any]:
    return {
        "root_policy": "fixed_sdl",
        "allowed_root": FIXED_REMOTE_ROOT,
        "fresh_project_required": True,
        "no_overwrite": True,
        "no_symlink": True,
        "no_delete": True,
    }


def build_execution_profile(
    *,
    profile_id: str,
    backend_kind: str,
    transport_config_ref: str,
    identity_binding: Any,
    declared_capabilities: Sequence[str] | None = None,
    executable_ref: str = "g16",
) -> ExecutionProfile:
    binding = validate_transport_identity_binding(identity_binding)
    require(binding["profile_id"] == profile_id, "profile id differs from transport binding")
    expected_hops = 2 if backend_kind == "legacy_rtwin_pbs" else 1
    require(len(binding["hops"]) == expected_hops, "backend kind differs from transport hop shape")
    capabilities = list(declared_capabilities or sorted(DECLARED_CAPABILITIES))
    document: dict[str, Any] = {
        "schema": PROFILE_SCHEMA,
        "profile_id": profile_id,
        "backend_kind": backend_kind,
        "transport_config_ref": transport_config_ref,
        "transport_identity_binding_sha256": binding["binding_payload_sha256"],
        "scheduler_dialect": SCHEDULER_DIALECT,
        "gaussian_runtime": {
            "invocation_mode": "legacy_stdin",
            "executable_ref": executable_ref,
        },
        "workspace_policy": _workspace_policy(),
        "resource_catalog": build_resource_catalog(),
        "declared_capabilities": capabilities,
        "profile_payload_sha256": "",
    }
    return validate_execution_profile(finalize(document, "profile_payload_sha256"))


def validate_execution_profile(document: Any) -> ExecutionProfile:
    profile = _exact(document, {
        "schema", "profile_id", "backend_kind", "transport_config_ref",
        "transport_identity_binding_sha256", "scheduler_dialect", "gaussian_runtime",
        "workspace_policy", "resource_catalog", "declared_capabilities",
        "profile_payload_sha256",
    }, "execution profile")
    require(profile["schema"] == PROFILE_SCHEMA, "execution profile schema is unsupported")
    _identifier(profile["profile_id"], "profile_id")
    require(profile["backend_kind"] in BACKENDS, "execution backend is unsupported")
    _private_reference(profile["transport_config_ref"], "transport_config_ref")
    _sha(profile["transport_identity_binding_sha256"], "transport_identity_binding_sha256")
    require(profile["scheduler_dialect"] == SCHEDULER_DIALECT, "scheduler dialect is unsupported")
    runtime = _exact(profile["gaussian_runtime"], {"invocation_mode", "executable_ref"}, "gaussian runtime")
    require(runtime["invocation_mode"] == "legacy_stdin", "Gaussian invocation mode is unsupported")
    executable = _text(runtime["executable_ref"], "gaussian_runtime.executable_ref")
    require(TOKEN_RE.fullmatch(executable) is not None, "Gaussian executable reference is unsafe")
    workspace = _exact(profile["workspace_policy"], {
        "root_policy", "allowed_root", "fresh_project_required", "no_overwrite",
        "no_symlink", "no_delete",
    }, "workspace policy")
    require(workspace == _workspace_policy(), "workspace policy must remain fixed to SDL with no overwrite/delete/symlink")
    validate_resource_catalog(profile["resource_catalog"])
    capabilities = profile["declared_capabilities"]
    require(isinstance(capabilities, list) and capabilities, "declared_capabilities must be a non-empty array")
    require(all(isinstance(item, str) for item in capabilities), "declared capabilities must be strings")
    require(len(capabilities) == len(set(capabilities)), "declared capabilities must be unique")
    require(set(capabilities).issubset(DECLARED_CAPABILITIES), "execution profile declares an unsupported capability")
    _verify_self_hash(profile, "profile_payload_sha256", "execution profile")
    return copy.deepcopy(profile)


def build_capability_report(profile: Any) -> CapabilityReport:
    validated = validate_execution_profile(profile)
    operations = [
        {"operation": item, "status": "configured_expressible_unverified"}
        for item in sorted(validated["declared_capabilities"])
    ]
    document: dict[str, Any] = {
        "schema": CAPABILITY_SCHEMA,
        "profile_id": validated["profile_id"],
        "profile_sha256": validated["profile_payload_sha256"],
        "backend_kind": validated["backend_kind"],
        "transport_identity_binding_sha256": validated["transport_identity_binding_sha256"],
        "scheduler": {
            "dialect": validated["scheduler_dialect"],
            "status": "configured_expressible_unverified",
        },
        "gaussian_runtime": {
            "invocation_mode": validated["gaussian_runtime"]["invocation_mode"],
            "status": "configured_expressible_unverified",
        },
        "configured_typed_operations": operations,
        "unsupported_backends": list(UNSUPPORTED_BACKENDS),
        "unknown_live_properties": list(UNKNOWN_LIVE_PROPERTIES),
        "offline_only": True,
        "sanitization_version": SANITIZATION_VERSION,
        "report_payload_sha256": "",
    }
    return validate_capability_report(finalize(document, "report_payload_sha256"))


def validate_capability_report(document: Any) -> CapabilityReport:
    report = _exact(document, {
        "schema", "profile_id", "profile_sha256", "backend_kind",
        "transport_identity_binding_sha256", "scheduler", "gaussian_runtime",
        "configured_typed_operations", "unsupported_backends",
        "unknown_live_properties", "offline_only", "sanitization_version",
        "report_payload_sha256",
    }, "capability report")
    require(report["schema"] == CAPABILITY_SCHEMA, "capability report schema is unsupported")
    _identifier(report["profile_id"], "profile_id")
    _sha(report["profile_sha256"], "profile_sha256")
    require(report["backend_kind"] in BACKENDS, "capability backend is unsupported")
    _sha(report["transport_identity_binding_sha256"], "transport identity binding digest")
    scheduler = _exact(report["scheduler"], {"dialect", "status"}, "scheduler capability")
    require(scheduler == {"dialect": SCHEDULER_DIALECT, "status": "configured_expressible_unverified"}, "scheduler capability overclaims support")
    runtime = _exact(report["gaussian_runtime"], {"invocation_mode", "status"}, "Gaussian capability")
    require(runtime == {"invocation_mode": "legacy_stdin", "status": "configured_expressible_unverified"}, "Gaussian capability overclaims support")
    operations = report["configured_typed_operations"]
    require(isinstance(operations, list) and operations, "configured operations must be a non-empty array")
    names: list[str] = []
    for index, operation in enumerate(operations):
        item = _exact(operation, {"operation", "status"}, f"configured operation {index}")
        require(item["operation"] in DECLARED_CAPABILITIES, "configured operation is unsupported")
        require(item["status"] == "configured_expressible_unverified", "configured operation overclaims live support")
        names.append(item["operation"])
    require(names == sorted(set(names)), "configured operations must be unique and sorted")
    require(report["unsupported_backends"] == list(UNSUPPORTED_BACKENDS), "unsupported backend list changed")
    require(report["unknown_live_properties"] == list(UNKNOWN_LIVE_PROPERTIES), "unknown live property list changed")
    require(report["offline_only"] is True, "capability report must remain offline_only")
    require(report["sanitization_version"] == SANITIZATION_VERSION, "capability sanitization version is unsupported")
    forbidden_fragments = (
        "hostname",
        "username",
        "known_hosts",
        "identityfile",
        "host_key",
        "fingerprint",
        '"port":',
    )
    projected = canonical_bytes({key: value for key, value in report.items() if key != "report_payload_sha256"}).decode("utf-8").lower()
    require(not any(fragment in projected for fragment in forbidden_fragments), "capability report contains an identity/path-like fragment")
    _verify_self_hash(report, "report_payload_sha256", "capability report")
    return copy.deepcopy(report)


def _parse_time(value: Any, label: str) -> datetime:
    text = _text(value, label)
    require(RFC3339_RE.fullmatch(text) is not None, f"{label} must be second-precision RFC3339 UTC")
    try:
        parsed = datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise PlatformContractError(f"{label} is not a real UTC timestamp") from exc
    return parsed


def _validate_window(issued_at: Any, expires_at: Any, *, now: str | datetime | None) -> tuple[datetime, datetime]:
    issued = _parse_time(issued_at, "issued_at")
    expires = _parse_time(expires_at, "expires_at")
    require(issued < expires, "attestation time window is inverted or empty")
    require((expires - issued).total_seconds() <= MAX_ATTESTATION_WINDOW_SECONDS, "attestation time window is too wide")
    if now is None:
        current = datetime.now(timezone.utc)
    elif isinstance(now, str):
        current = _parse_time(now, "now")
    else:
        require(isinstance(now, datetime) and now.tzinfo is not None, "now must be timezone-aware")
        current = now.astimezone(timezone.utc)
    require(issued <= current < expires, "attestation receipt is not currently valid")
    return issued, expires


def build_first_hop_request(
    *,
    profile_sha256: str,
    binding_sha256: str,
    request_nonce: str,
    issued_at: str,
    expires_at: str,
) -> dict[str, Any]:
    request = {
        "schema": FIRST_HOP_REQUEST_SCHEMA,
        "profile_sha256": profile_sha256,
        "transport_identity_binding_sha256": binding_sha256,
        "request_nonce": request_nonce,
        "issued_at": issued_at,
        "expires_at": expires_at,
        "operation_version": FIRST_HOP_OPERATION_VERSION,
        "read_only_attestation": True,
        "automatic_retry": False,
    }
    return validate_first_hop_request(request, now=issued_at)


def validate_first_hop_request(document: Any, *, now: str | datetime | None) -> dict[str, Any]:
    request = _exact(document, {
        "schema", "profile_sha256", "transport_identity_binding_sha256",
        "request_nonce", "issued_at", "expires_at", "operation_version",
        "read_only_attestation", "automatic_retry",
    }, "first-hop attestation request")
    require(request["schema"] == FIRST_HOP_REQUEST_SCHEMA, "first-hop request schema is unsupported")
    _sha(request["profile_sha256"], "profile_sha256")
    _sha(request["transport_identity_binding_sha256"], "transport identity binding digest")
    nonce = _text(request["request_nonce"], "request_nonce")
    require(NONCE_RE.fullmatch(nonce) is not None, "request nonce must be 32-128 lowercase hex characters")
    require(request["operation_version"] == FIRST_HOP_OPERATION_VERSION, "first-hop operation version is unsupported")
    require(request["read_only_attestation"] is True, "first-hop attestation must remain read-only")
    require(request["automatic_retry"] is False, "first-hop attestation automatic retry is forbidden")
    _validate_window(request["issued_at"], request["expires_at"], now=now)
    return copy.deepcopy(request)


def build_nested_hop_request(
    *,
    profile_sha256: str,
    binding_sha256: str,
    first_hop_receipt_sha256: str,
    request_nonce: str,
    issued_at: str,
    expires_at: str,
) -> dict[str, Any]:
    request = {
        "schema": NESTED_HOP_REQUEST_SCHEMA,
        "profile_sha256": profile_sha256,
        "transport_identity_binding_sha256": binding_sha256,
        "first_hop_receipt_sha256": first_hop_receipt_sha256,
        "request_nonce": request_nonce,
        "issued_at": issued_at,
        "expires_at": expires_at,
        "operation_version": NESTED_HOP_OPERATION_VERSION,
        "read_only_attestation": True,
        "automatic_retry": False,
    }
    return validate_nested_hop_request(request, now=issued_at)


def validate_nested_hop_request(document: Any, *, now: str | datetime | None) -> dict[str, Any]:
    request = _exact(document, {
        "schema", "profile_sha256", "transport_identity_binding_sha256",
        "first_hop_receipt_sha256", "request_nonce", "issued_at", "expires_at",
        "operation_version", "read_only_attestation", "automatic_retry",
    }, "nested-hop attestation request")
    require(request["schema"] == NESTED_HOP_REQUEST_SCHEMA, "nested-hop request schema is unsupported")
    _sha(request["profile_sha256"], "profile_sha256")
    _sha(request["transport_identity_binding_sha256"], "transport identity binding digest")
    _sha(request["first_hop_receipt_sha256"], "first_hop_receipt_sha256")
    nonce = _text(request["request_nonce"], "request_nonce")
    require(NONCE_RE.fullmatch(nonce) is not None, "request nonce must be 32-128 lowercase hex characters")
    require(request["operation_version"] == NESTED_HOP_OPERATION_VERSION, "nested-hop operation version is unsupported")
    require(request["read_only_attestation"] is True, "nested-hop attestation must remain read-only")
    require(request["automatic_retry"] is False, "nested-hop attestation automatic retry is forbidden")
    _validate_window(request["issued_at"], request["expires_at"], now=now)
    return copy.deepcopy(request)


def _hop_identity_sha256(hop: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_bytes(hop)).hexdigest()


def build_first_hop_receipt(
    *,
    request: Any,
    binding: Any,
    observed_fingerprint_evidence_sha256: str,
) -> FirstHopIdentityReceipt:
    """Finalize caller-supplied verified digests; perform no handshake or authorization."""
    checked_binding = validate_transport_identity_binding(binding)
    checked_request = validate_first_hop_request(request, now=request.get("issued_at") if isinstance(request, dict) else None)
    hop = checked_binding["hops"][0]
    document: dict[str, Any] = {
        "schema": ATTESTATION_RECEIPT_SCHEMA,
        "receipt_kind": "first_hop",
        "profile_sha256": checked_request["profile_sha256"],
        "transport_identity_binding_sha256": checked_binding["binding_payload_sha256"],
        "first_hop_identity_sha256": _hop_identity_sha256(hop),
        "config_source_bundle_sha256": hop["config_source_bundle_sha256"],
        "alias_utf8_sha256": hop["alias_utf8_sha256"],
        "effective_target_identity_sha256": hop["effective_target_identity_sha256"],
        "host_key_evidence_sha256": hop["host_key_evidence_sha256"],
        "observed_fingerprint_evidence_sha256": observed_fingerprint_evidence_sha256,
        "request_nonce": checked_request["request_nonce"],
        "issued_at": checked_request["issued_at"],
        "expires_at": checked_request["expires_at"],
        "operation_version": checked_request["operation_version"],
        "classification": "verified",
        "read_only_attestation": True,
        "automatic_retry": False,
        "no_execution_authorization": True,
        "receipt_payload_sha256": "",
    }
    result = finalize(document, "receipt_payload_sha256")
    return validate_first_hop_receipt(result, request=checked_request, binding=checked_binding, now=checked_request["issued_at"])


def validate_first_hop_receipt(
    document: Any,
    *,
    request: Any,
    binding: Any,
    now: str | datetime | None,
) -> FirstHopIdentityReceipt:
    receipt = _exact(document, {
        "schema", "receipt_kind", "profile_sha256",
        "transport_identity_binding_sha256", "first_hop_identity_sha256",
        "config_source_bundle_sha256", "alias_utf8_sha256",
        "effective_target_identity_sha256", "host_key_evidence_sha256",
        "observed_fingerprint_evidence_sha256", "request_nonce", "issued_at",
        "expires_at", "operation_version", "classification", "receipt_payload_sha256",
        "read_only_attestation", "automatic_retry", "no_execution_authorization",
    }, "first-hop identity receipt")
    checked_request = validate_first_hop_request(request, now=now)
    checked_binding = validate_transport_identity_binding(binding)
    require(
        hmac.compare_digest(
            checked_request["transport_identity_binding_sha256"],
            checked_binding["binding_payload_sha256"],
        ),
        "first-hop request transport identity binding mismatch",
    )
    require(receipt["schema"] == ATTESTATION_RECEIPT_SCHEMA, "attestation receipt schema is unsupported")
    require(receipt["receipt_kind"] == "first_hop", "attestation receipt kind mismatch")
    require(receipt["classification"] == "verified", "first-hop attestation is unknown, partial, or refused")
    require(receipt["read_only_attestation"] is True, "first-hop receipt must remain read-only")
    require(receipt["automatic_retry"] is False, "first-hop receipt automatic retry is forbidden")
    require(receipt["no_execution_authorization"] is True, "first-hop receipt must remain non-authorizing")
    hop = checked_binding["hops"][0]
    comparisons = {
        "profile_sha256": checked_request["profile_sha256"],
        "transport_identity_binding_sha256": checked_binding["binding_payload_sha256"],
        "first_hop_identity_sha256": _hop_identity_sha256(hop),
        "config_source_bundle_sha256": hop["config_source_bundle_sha256"],
        "alias_utf8_sha256": hop["alias_utf8_sha256"],
        "effective_target_identity_sha256": hop["effective_target_identity_sha256"],
        "host_key_evidence_sha256": hop["host_key_evidence_sha256"],
        "request_nonce": checked_request["request_nonce"],
        "issued_at": checked_request["issued_at"],
        "expires_at": checked_request["expires_at"],
        "operation_version": checked_request["operation_version"],
    }
    for field, expected in comparisons.items():
        actual = _text(receipt[field], field)
        require(hmac.compare_digest(actual, expected), f"first-hop receipt {field} mismatch")
    _sha(receipt["observed_fingerprint_evidence_sha256"], "observed fingerprint evidence digest")
    _validate_window(receipt["issued_at"], receipt["expires_at"], now=now)
    _verify_self_hash(receipt, "receipt_payload_sha256", "first-hop identity receipt")
    return copy.deepcopy(receipt)


def build_nested_hop_receipt(
    *,
    request: Any,
    binding: Any,
    first_hop_receipt: Any,
    first_hop_request: Any,
) -> NestedHopIdentityReceipt:
    """Finalize caller-supplied Stage-B digests; perform no remote operation or authorization."""
    checked_binding = validate_transport_identity_binding(binding)
    require(len(checked_binding["hops"]) == 2, "nested-hop attestation requires a two-hop binding")
    checked_first = validate_first_hop_receipt(
        first_hop_receipt,
        request=first_hop_request,
        binding=checked_binding,
        now=first_hop_request.get("issued_at") if isinstance(first_hop_request, dict) else None,
    )
    checked_request = validate_nested_hop_request(request, now=request.get("issued_at") if isinstance(request, dict) else None)
    require(
        hmac.compare_digest(checked_request["first_hop_receipt_sha256"], checked_first["receipt_payload_sha256"]),
        "nested request first-hop receipt mismatch",
    )
    hop = checked_binding["hops"][1]
    document: dict[str, Any] = {
        "schema": ATTESTATION_RECEIPT_SCHEMA,
        "receipt_kind": "nested_hop",
        "profile_sha256": checked_request["profile_sha256"],
        "transport_identity_binding_sha256": checked_binding["binding_payload_sha256"],
        "first_hop_identity_sha256": checked_first["first_hop_identity_sha256"],
        "first_hop_receipt_sha256": checked_first["receipt_payload_sha256"],
        "config_source_bundle_sha256": hop["config_source_bundle_sha256"],
        "alias_utf8_sha256": hop["alias_utf8_sha256"],
        "effective_target_identity_sha256": hop["effective_target_identity_sha256"],
        "host_key_evidence_sha256": hop["host_key_evidence_sha256"],
        "request_nonce": checked_request["request_nonce"],
        "issued_at": checked_request["issued_at"],
        "expires_at": checked_request["expires_at"],
        "operation_version": checked_request["operation_version"],
        "classification": "verified",
        "read_only_attestation": True,
        "automatic_retry": False,
        "no_execution_authorization": True,
        "receipt_payload_sha256": "",
    }
    result = finalize(document, "receipt_payload_sha256")
    return validate_nested_hop_receipt(
        result,
        request=checked_request,
        binding=checked_binding,
        first_hop_receipt=checked_first,
        first_hop_request=first_hop_request,
        now=checked_request["issued_at"],
    )


def validate_nested_hop_receipt(
    document: Any,
    *,
    request: Any,
    binding: Any,
    first_hop_receipt: Any,
    first_hop_request: Any,
    now: str | datetime | None,
) -> NestedHopIdentityReceipt:
    receipt = _exact(document, {
        "schema", "receipt_kind", "profile_sha256",
        "transport_identity_binding_sha256", "first_hop_identity_sha256",
        "first_hop_receipt_sha256", "config_source_bundle_sha256",
        "alias_utf8_sha256", "effective_target_identity_sha256",
        "host_key_evidence_sha256", "request_nonce", "issued_at", "expires_at",
        "operation_version", "classification", "receipt_payload_sha256",
        "read_only_attestation", "automatic_retry", "no_execution_authorization",
    }, "nested-hop identity receipt")
    checked_request = validate_nested_hop_request(request, now=now)
    checked_binding = validate_transport_identity_binding(binding)
    require(len(checked_binding["hops"]) == 2, "nested-hop receipt requires a two-hop binding")
    checked_first = validate_first_hop_receipt(
        first_hop_receipt,
        request=first_hop_request,
        binding=checked_binding,
        now=now,
    )
    require(
        hmac.compare_digest(
            checked_request["transport_identity_binding_sha256"],
            checked_binding["binding_payload_sha256"],
        ),
        "nested request transport identity binding mismatch",
    )
    require(
        hmac.compare_digest(
            checked_request["first_hop_receipt_sha256"],
            checked_first["receipt_payload_sha256"],
        ),
        "nested request first-hop receipt mismatch",
    )
    require(
        hmac.compare_digest(
            checked_request["profile_sha256"],
            checked_first["profile_sha256"],
        ),
        "nested request profile differs from first-hop receipt",
    )
    require(receipt["schema"] == ATTESTATION_RECEIPT_SCHEMA, "attestation receipt schema is unsupported")
    require(receipt["receipt_kind"] == "nested_hop", "attestation receipt kind mismatch")
    require(receipt["classification"] == "verified", "nested-hop attestation is unknown, partial, or refused")
    require(receipt["read_only_attestation"] is True, "nested-hop receipt must remain read-only")
    require(receipt["automatic_retry"] is False, "nested-hop receipt automatic retry is forbidden")
    require(receipt["no_execution_authorization"] is True, "nested-hop receipt must remain non-authorizing")
    hop = checked_binding["hops"][1]
    comparisons = {
        "profile_sha256": checked_request["profile_sha256"],
        "transport_identity_binding_sha256": checked_binding["binding_payload_sha256"],
        "first_hop_identity_sha256": checked_first["first_hop_identity_sha256"],
        "first_hop_receipt_sha256": checked_first["receipt_payload_sha256"],
        "config_source_bundle_sha256": hop["config_source_bundle_sha256"],
        "alias_utf8_sha256": hop["alias_utf8_sha256"],
        "effective_target_identity_sha256": hop["effective_target_identity_sha256"],
        "host_key_evidence_sha256": hop["host_key_evidence_sha256"],
        "request_nonce": checked_request["request_nonce"],
        "issued_at": checked_request["issued_at"],
        "expires_at": checked_request["expires_at"],
        "operation_version": checked_request["operation_version"],
    }
    for field, expected in comparisons.items():
        actual = _text(receipt[field], field)
        require(hmac.compare_digest(actual, expected), f"nested-hop receipt {field} mismatch")
    _validate_window(receipt["issued_at"], receipt["expires_at"], now=now)
    _verify_self_hash(receipt, "receipt_payload_sha256", "nested-hop identity receipt")
    return copy.deepcopy(receipt)


def _load_legacy_runtime_owner() -> ModuleType:
    here = Path(__file__).parent
    candidates = (
        here / "platform_runtime_config_owner.py",
        here / "runtime_config.py",
    )
    path = next((candidate for candidate in candidates if candidate.is_file()), None)
    require(path is not None, "legacy runtime validator owner is unavailable")
    spec = importlib.util.spec_from_file_location("auto_g16_legacy_runtime_owner", path)
    require(spec is not None and spec.loader is not None, "legacy runtime validator cannot be imported")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_legacy_runtime_exact(path: Path) -> dict[str, str]:
    """Read runtime /1 through its unchanged repository/deployed owner."""
    owner = _load_legacy_runtime_owner()
    require(getattr(owner, "SCHEMA", None) == LEGACY_RUNTIME_SCHEMA, "legacy runtime validator schema changed")
    require(hasattr(owner, "load"), "legacy runtime validator lacks load")
    value = owner.load(path, missing_ok=False)
    require(isinstance(value, dict) and set(value).issubset(LEGACY_RUNTIME_KEYS), "legacy runtime owner returned an invalid result")
    return copy.deepcopy(value)


def _validated_legacy_runtime(value: Any) -> dict[str, str]:
    owner = _load_legacy_runtime_owner()
    require(getattr(owner, "SCHEMA", None) == LEGACY_RUNTIME_SCHEMA, "legacy runtime validator schema changed")
    require(hasattr(owner, "validate"), "legacy runtime validator lacks validate")
    validated = owner.validate(value)
    require(
        isinstance(validated, dict) and set(validated).issubset(LEGACY_RUNTIME_KEYS),
        "legacy runtime owner returned an invalid result",
    )
    return copy.deepcopy(validated)


def map_legacy_runtime(
    validated_runtime: Any,
    *,
    legacy_cli_values: dict[str, str] | None = None,
    explicit_profile: Any | None = None,
) -> LegacyMappingResult:
    runtime = _validated_legacy_runtime(validated_runtime)
    cli_values = legacy_cli_values or {}
    allowed_cli = {"mac_ssh_config", "windows_root", "windows_server_config"}
    require(set(cli_values).issubset(allowed_cli), "legacy mapping received an unsupported CLI field")
    conflicts: set[str] = set()
    comparisons = {
        "mac_ssh_config": "rtwin_ssh_config",
        "windows_root": "windows_project_root",
        "windows_server_config": "windows_server_config",
    }
    for cli_field, runtime_field in comparisons.items():
        if cli_field in cli_values and runtime_field in runtime:
            _text(cli_values[cli_field], f"legacy CLI {cli_field}")
            if not hmac.compare_digest(cli_values[cli_field], runtime[runtime_field]):
                conflicts.add(runtime_field)
    if explicit_profile is not None:
        profile = validate_execution_profile(explicit_profile)
        if profile["backend_kind"] != "legacy_rtwin_pbs":
            conflicts.add("backend_kind")
        if "rtwin_ssh_config" in runtime and not hmac.compare_digest(
            profile["transport_config_ref"], runtime["rtwin_ssh_config"]
        ):
            conflicts.add("rtwin_ssh_config")
    subset = {key: runtime[key] for key in sorted(LEGACY_EXECUTION_KEYS & set(runtime))}
    subset_sha = hashlib.sha256(canonical_bytes(subset)).hexdigest()
    profile_id = f"legacy-{subset_sha[:16]}"
    catalog = build_resource_catalog()
    workspace_sha = hashlib.sha256(canonical_bytes(_workspace_policy())).hexdigest()
    profile_status = "conflict" if conflicts else "blocked_live_attestation_required"
    document: dict[str, Any] = {
        "schema": LEGACY_MAPPING_SCHEMA,
        "mapping_id": f"mapping-{subset_sha[:16]}",
        "source_runtime_schema": LEGACY_RUNTIME_SCHEMA,
        "source_configured_keys": sorted(runtime),
        "runtime_execution_subset_sha256": subset_sha,
        "backend_kind": "legacy_rtwin_pbs",
        "derived_profile_summary": {
            "profile_id": profile_id,
            "backend_kind": "legacy_rtwin_pbs",
            "scheduler_dialect": SCHEDULER_DIALECT,
            "workspace_policy_sha256": workspace_sha,
            "resource_catalog_sha256": catalog["catalog_payload_sha256"],
            "transport_identity_binding_status": "live_attestation_required",
            "profile_status": profile_status,
            "profile_payload_sha256": None,
        },
        "resource_catalog": catalog,
        "conflicts": [
            {"field": field, "classification": "execution_relevant_value_conflict"}
            for field in sorted(conflicts)
        ],
        "migration_performed": False,
        "legacy_approval_authorizes_profile_mode": False,
        "legacy_approval_authorizes_direct": False,
        "live_attestation_required": True,
        "mapping_payload_sha256": "",
    }
    return validate_legacy_mapping_result(finalize(document, "mapping_payload_sha256"))


def derive_legacy_profile(validated_runtime: Any, identity_binding: Any) -> ExecutionProfile:
    runtime = _validated_legacy_runtime(validated_runtime)
    require("rtwin_ssh_config" in runtime, "legacy runtime lacks rtwin_ssh_config")
    mapping = map_legacy_runtime(runtime)
    profile_id = mapping["derived_profile_summary"]["profile_id"]
    binding = validate_transport_identity_binding(identity_binding)
    require(binding["profile_id"] == profile_id, "legacy binding profile id differs from derived mapping")
    return build_execution_profile(
        profile_id=profile_id,
        backend_kind="legacy_rtwin_pbs",
        transport_config_ref=runtime["rtwin_ssh_config"],
        identity_binding=binding,
    )


def validate_legacy_mapping_result(document: Any) -> LegacyMappingResult:
    mapping = _exact(document, {
        "schema", "mapping_id", "source_runtime_schema", "source_configured_keys",
        "runtime_execution_subset_sha256", "backend_kind", "derived_profile_summary",
        "resource_catalog", "conflicts", "migration_performed",
        "legacy_approval_authorizes_profile_mode", "legacy_approval_authorizes_direct",
        "live_attestation_required", "mapping_payload_sha256",
    }, "legacy mapping result")
    require(mapping["schema"] == LEGACY_MAPPING_SCHEMA, "legacy mapping schema is unsupported")
    _identifier(mapping["mapping_id"], "mapping_id")
    require(mapping["source_runtime_schema"] == LEGACY_RUNTIME_SCHEMA, "legacy runtime schema changed")
    keys = mapping["source_configured_keys"]
    require(isinstance(keys, list) and keys == sorted(set(keys)), "legacy configured keys must be unique and sorted")
    require(set(keys).issubset(LEGACY_RUNTIME_KEYS), "legacy mapping exposes an unknown runtime key")
    _sha(mapping["runtime_execution_subset_sha256"], "runtime execution subset digest")
    require(mapping["backend_kind"] == "legacy_rtwin_pbs", "legacy mapping backend changed")
    summary = _exact(mapping["derived_profile_summary"], {
        "profile_id", "backend_kind", "scheduler_dialect", "workspace_policy_sha256",
        "resource_catalog_sha256", "transport_identity_binding_status", "profile_status",
        "profile_payload_sha256",
    }, "derived legacy profile summary")
    _identifier(summary["profile_id"], "derived profile id")
    require(summary["backend_kind"] == "legacy_rtwin_pbs", "derived legacy backend changed")
    require(summary["scheduler_dialect"] == SCHEDULER_DIALECT, "derived scheduler dialect changed")
    _sha(summary["workspace_policy_sha256"], "workspace policy digest")
    catalog = validate_resource_catalog(mapping["resource_catalog"])
    require(hmac.compare_digest(summary["resource_catalog_sha256"], catalog["catalog_payload_sha256"]), "derived catalog digest mismatch")
    require(summary["transport_identity_binding_status"] == "live_attestation_required", "legacy nested identity was inferred offline")
    require(summary["profile_status"] in {"blocked_live_attestation_required", "conflict"}, "derived profile status overclaims readiness")
    require(summary["profile_payload_sha256"] is None, "offline legacy mapping must not claim a complete profile hash")
    conflicts = mapping["conflicts"]
    require(isinstance(conflicts, list), "legacy conflicts must be an array")
    names: list[str] = []
    for index, conflict in enumerate(conflicts):
        item = _exact(conflict, {"field", "classification"}, f"legacy conflict {index}")
        require(item["field"] in LEGACY_RUNTIME_KEYS | {"backend_kind"}, "legacy conflict field is unsupported")
        require(item["classification"] == "execution_relevant_value_conflict", "legacy conflict classification changed")
        names.append(item["field"])
    require(names == sorted(set(names)), "legacy conflicts must be unique and sorted")
    require((summary["profile_status"] == "conflict") == bool(conflicts), "legacy conflict status is inconsistent")
    require(mapping["migration_performed"] is False, "legacy mapping must not migrate files")
    require(mapping["legacy_approval_authorizes_profile_mode"] is False, "legacy approval must not authorize profile mode")
    require(mapping["legacy_approval_authorizes_direct"] is False, "legacy approval must not authorize direct execution")
    require(mapping["live_attestation_required"] is True, "legacy mapping must require live nested attestation")
    _verify_self_hash(mapping, "mapping_payload_sha256", "legacy mapping result")
    return copy.deepcopy(mapping)


def _open_regular_nofollow(path: Path) -> bytes:
    require(path.is_absolute(), "contract path must be absolute")
    _private_reference(str(path), "contract path")
    require(hasattr(os, "O_NOFOLLOW") and hasattr(os, "O_DIRECTORY"), "no-follow filesystem primitives are unavailable")
    parts = path.parts[1:]
    require(bool(parts) and all(part not in {"", ".", ".."} for part in parts), "contract path is unsafe")
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path.anchor, directory_flags)
    try:
        for part in parts[:-1]:
            try:
                next_descriptor = os.open(part, directory_flags, dir_fd=descriptor)
            except OSError as exc:
                if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
                    raise PlatformContractError(f"contract path contains a symlink or non-directory ancestor: {path}") from exc
                raise
            os.close(descriptor)
            descriptor = next_descriptor
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        try:
            leaf = os.open(parts[-1], flags, dir_fd=descriptor)
        except OSError as exc:
            if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
                raise PlatformContractError(f"contract path must not be a symlink: {path}") from exc
            raise
        try:
            opened = os.fstat(leaf)
            require(stat.S_ISREG(opened.st_mode), "contract artifact must be a regular file")
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = os.read(leaf, 1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                require(total <= 8 * 1024 * 1024, "contract artifact exceeds the offline size limit")
                chunks.append(chunk)
            return b"".join(chunks)
        finally:
            os.close(leaf)
    finally:
        os.close(descriptor)


def load_contract(path: Path, validator: Any) -> dict[str, Any]:
    raw = _open_regular_nofollow(path)
    document = strict_json_loads(raw, label=str(path))
    return validator(document)


def load_execution_profile(path: Path) -> ExecutionProfile:
    return load_contract(path, validate_execution_profile)  # type: ignore[return-value]


def load_transport_identity_binding(path: Path) -> TransportIdentityBinding:
    return load_contract(path, validate_transport_identity_binding)  # type: ignore[return-value]


def _publish_private_atomic(path: Path, data: bytes, validator: Any) -> None:
    require(path.is_absolute(), "init output path must be absolute")
    _private_reference(str(path), "init output path")
    require(hasattr(os, "O_NOFOLLOW") and hasattr(os, "O_DIRECTORY"), "no-follow filesystem primitives are unavailable")
    parts = path.parts[1:]
    require(bool(parts) and all(part not in {"", ".", ".."} for part in parts), "init output path is unsafe")
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
    directory = os.open(path.anchor, directory_flags)
    temporary_name: str | None = None
    try:
        for part in parts[:-1]:
            try:
                next_directory = os.open(part, directory_flags, dir_fd=directory)
            except OSError as exc:
                if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
                    raise PlatformContractError(f"init output contains a symlink or non-directory ancestor: {path}") from exc
                raise
            os.close(directory)
            directory = next_directory
        final_name = parts[-1]
        for _ in range(16):
            candidate = f".{final_name}.tmp.{secrets.token_hex(8)}"
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
            try:
                leaf = os.open(candidate, flags, 0o600, dir_fd=directory)
                temporary_name = candidate
                break
            except FileExistsError:
                continue
        else:
            raise PlatformContractError("could not reserve a private same-directory init artifact")
        try:
            os.fchmod(leaf, 0o600)
            offset = 0
            while offset < len(data):
                written = os.write(leaf, data[offset:])
                require(written > 0, "init temporary artifact write made no progress")
                offset += written
            os.fsync(leaf)
            opened = os.fstat(leaf)
            require(stat.S_ISREG(opened.st_mode), "init temporary artifact is not regular")
            require(stat.S_IMODE(opened.st_mode) == 0o600, "init temporary artifact is not private mode 0600")
        finally:
            os.close(leaf)
        temporary_bytes = _open_regular_nofollow(path.parent / temporary_name)
        require(hmac.compare_digest(temporary_bytes, data), "init temporary artifact bytes changed")
        validator(strict_json_loads(temporary_bytes, label="init temporary artifact"))
        try:
            os.link(
                temporary_name,
                final_name,
                src_dir_fd=directory,
                dst_dir_fd=directory,
                follow_symlinks=False,
            )
        except FileExistsError as exc:
            raise PlatformContractError(f"init refuses to overwrite existing output: {path}") from exc
        published = os.stat(final_name, dir_fd=directory, follow_symlinks=False)
        require(stat.S_ISREG(published.st_mode), "published init artifact is not regular")
        require(stat.S_IMODE(published.st_mode) == 0o600, "published init artifact is not private mode 0600")
        os.fsync(directory)
    finally:
        if temporary_name is not None:
            try:
                os.unlink(temporary_name, dir_fd=directory)
            except FileNotFoundError:
                pass
        os.close(directory)


def _summary(kind: str, path: Path, digest: str) -> dict[str, Any]:
    return {
        "schema": "auto-g16-platform-contract-cli-result/1",
        "operation": kind,
        "path": str(path),
        "payload_sha256": digest,
        "offline_only": True,
        "live_authority": False,
    }


def _write_stdout(value: dict[str, Any]) -> None:
    sys.stdout.write(canonical_bytes(value).decode("utf-8"))


def _validate_command(args: argparse.Namespace) -> dict[str, Any]:
    path = args.path.absolute()
    validators = {
        "profile": validate_execution_profile,
        "binding": validate_transport_identity_binding,
        "catalog": validate_resource_catalog,
        "capability": validate_capability_report,
        "legacy-mapping": validate_legacy_mapping_result,
    }
    if args.kind in validators:
        document = load_contract(path, validators[args.kind])
        digest_field = {
            "profile": "profile_payload_sha256",
            "binding": "binding_payload_sha256",
            "catalog": "catalog_payload_sha256",
            "capability": "report_payload_sha256",
            "legacy-mapping": "mapping_payload_sha256",
        }[args.kind]
        return _summary(f"validate_{args.kind}", path, document[digest_field])
    document = strict_json_loads(_open_regular_nofollow(path), label=str(path))
    if args.kind == "first-hop-request":
        validated = validate_first_hop_request(document, now=args.now)
        digest = hashlib.sha256(canonical_bytes(validated)).hexdigest()
    elif args.kind == "nested-hop-request":
        validated = validate_nested_hop_request(document, now=args.now)
        digest = hashlib.sha256(canonical_bytes(validated)).hexdigest()
    elif args.kind == "first-hop-receipt":
        require(args.request is not None, "first-hop receipt validation requires --request")
        require(args.identity_binding is not None, "first-hop receipt validation requires --identity-binding")
        request = strict_json_loads(
            _open_regular_nofollow(args.request.absolute()),
            label=str(args.request),
        )
        binding = load_transport_identity_binding(args.identity_binding.absolute())
        validated = validate_first_hop_receipt(
            document,
            request=request,
            binding=binding,
            now=args.now,
        )
        digest = validated["receipt_payload_sha256"]
    else:
        require(args.request is not None, "nested-hop receipt validation requires --request")
        require(args.identity_binding is not None, "nested-hop receipt validation requires --identity-binding")
        require(args.first_hop_request is not None, "nested-hop receipt validation requires --first-hop-request")
        require(args.first_hop_receipt is not None, "nested-hop receipt validation requires --first-hop-receipt")
        request = strict_json_loads(
            _open_regular_nofollow(args.request.absolute()),
            label=str(args.request),
        )
        binding = load_transport_identity_binding(args.identity_binding.absolute())
        first_request = strict_json_loads(
            _open_regular_nofollow(args.first_hop_request.absolute()),
            label=str(args.first_hop_request),
        )
        first_receipt = strict_json_loads(
            _open_regular_nofollow(args.first_hop_receipt.absolute()),
            label=str(args.first_hop_receipt),
        )
        validated = validate_nested_hop_receipt(
            document,
            request=request,
            binding=binding,
            first_hop_receipt=first_receipt,
            first_hop_request=first_request,
            now=args.now,
        )
        digest = validated["receipt_payload_sha256"]
    return _summary(f"validate_{args.kind}", path, digest)


def _doctor_command(args: argparse.Namespace) -> dict[str, Any]:
    require(args.profile is not None or args.legacy_runtime is not None, "doctor requires --profile or --legacy-runtime")
    if args.profile is not None and args.legacy_runtime is not None:
        profile_path = args.profile.absolute()
        runtime_path = args.legacy_runtime.absolute()
        profile = load_execution_profile(profile_path)
        runtime = load_legacy_runtime_exact(runtime_path)
        mapping = map_legacy_runtime(runtime, explicit_profile=profile)
        return {
            "schema": "auto-g16-platform-doctor-result/1",
            "subject": "explicit_profile_with_legacy_runtime",
            "profile_path": str(profile_path),
            "legacy_runtime_path": str(runtime_path),
            "status": "conflict" if mapping["conflicts"] else "explicit_profile_selected",
            "capability_report": build_capability_report(profile),
            "legacy_mapping": mapping,
            "live_attestation_required": True,
            "offline_only": True,
            "live_authority": False,
        }
    if args.profile is not None:
        path = args.profile.absolute()
        profile = load_execution_profile(path)
        report = build_capability_report(profile)
        return {
            "schema": "auto-g16-platform-doctor-result/1",
            "subject": "execution_profile",
            "path": str(path),
            "status": "configured_expressibility_only",
            "capability_report": report,
            "live_attestation_required": True,
            "offline_only": True,
            "live_authority": False,
        }
    path = args.legacy_runtime.absolute()
    runtime = load_legacy_runtime_exact(path)
    mapping = map_legacy_runtime(runtime)
    return {
        "schema": "auto-g16-platform-doctor-result/1",
        "subject": "legacy_runtime_mapping",
        "path": str(path),
        "status": "live_attestation_required",
        "mapping": mapping,
        "offline_only": True,
        "live_authority": False,
    }


def _init_command(args: argparse.Namespace) -> dict[str, Any]:
    require(args.output.is_absolute(), "init --output must be an explicit absolute path")
    require(args.identity_binding.is_absolute(), "init --identity-binding must be an explicit absolute path")
    output = args.output
    _private_reference(str(output), "init output path")
    binding = load_transport_identity_binding(args.identity_binding)
    profile = build_execution_profile(
        profile_id=args.profile_id,
        backend_kind=args.backend_kind,
        transport_config_ref=args.transport_config_ref,
        identity_binding=binding,
        executable_ref=args.executable_ref,
    )
    result = _summary("init_profile", output, profile["profile_payload_sha256"])
    result["dry_run"] = bool(args.dry_run)
    result["written"] = False
    result["mode"] = "0600"
    result["no_clobber"] = True
    result["atomic_publish"] = True
    if not args.dry_run:
        _publish_private_atomic(output, canonical_bytes(profile), validate_execution_profile)
        result["written"] = True
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate", help="validate one new contract without side effects")
    validate_parser.add_argument("kind", choices=(
        "profile", "binding", "catalog", "capability", "legacy-mapping",
        "first-hop-request", "nested-hop-request", "first-hop-receipt", "nested-hop-receipt",
    ))
    validate_parser.add_argument("path", type=Path)
    validate_parser.add_argument("--request", type=Path)
    validate_parser.add_argument("--identity-binding", type=Path)
    validate_parser.add_argument("--first-hop-request", type=Path)
    validate_parser.add_argument("--first-hop-receipt", type=Path)
    validate_parser.add_argument("--now")
    validate_parser.set_defaults(handler=_validate_command)

    doctor = subparsers.add_parser("doctor", help="emit a sanitized offline-only configuration diagnosis")
    doctor.add_argument("--profile", type=Path)
    doctor.add_argument("--legacy-runtime", type=Path)
    doctor.set_defaults(handler=_doctor_command)

    init = subparsers.add_parser("init", help="explicitly create one private no-clobber execution profile")
    init.add_argument("--output", required=True, type=Path)
    init.add_argument("--profile-id", required=True)
    init.add_argument("--backend-kind", required=True, choices=sorted(BACKENDS))
    init.add_argument("--transport-config-ref", required=True)
    init.add_argument("--identity-binding", required=True, type=Path)
    init.add_argument("--executable-ref", default="g16")
    init.add_argument("--dry-run", action="store_true")
    init.set_defaults(handler=_init_command)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        _write_stdout(args.handler(args))
        return 0
    except (PlatformContractError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
