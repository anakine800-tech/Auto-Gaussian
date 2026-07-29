#!/usr/bin/env python3
"""Own the fixed legacy RTwin/PBS root authority offline.

The module accepts only the exact sealed protected production-ingress
capability and models a stable root identity, a fresh no-follow observation,
and one owner-private descriptor-capability consumption.  It contains no
transport, remote observation, filesystem mutation, PBS, or Gaussian action.
"""

from __future__ import annotations

import copy
import hashlib
import hmac
import json
import os
import re
import stat
import sys
import threading
import types
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable


MODULE_NAME = "legacy_root_authority_contract"
INGRESS_MODULE_NAME = "protected_production_ingress_contract"
BACKEND_KIND = "legacy_rtwin_pbs"
FIXED_REMOTE_ROOT = "/home/user100/SDL"
OWNER_ID = "auto-g16-legacy-root-authority-owner"
OWNER_VERSION = "legacy-root-authority-contract/1"
STABLE_SCHEMA = "auto-g16-legacy-stable-root-identity-evidence/1"
AUTHORIZATION_SCHEMA = "auto-g16-legacy-root-authority-authorization/1"
RECEIPT_SCHEMA = "auto-g16-legacy-fresh-root-observation-receipt/1"
PROFILE_SCHEMA = "auto-g16-execution-profile/2"
INGRESS_SCHEMA = "auto-g16-protected-production-ingress-contract/1"
OPERATION_VERSION = "legacy-root-fresh-observation/1"
OPERATION = "observe_and_consume_fixed_legacy_root_once"
MAX_DOCUMENT_BYTES = 2 * 1024 * 1024
MAX_NESTING = 32

SHA_RE = re.compile(r"^[a-f0-9]{64}$")
ID_RE = re.compile(r"^[a-z][a-z0-9._-]{0,127}$")
PROJECT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,14}$")
ATTEMPT_RE = re.compile(r"^qsub-attempt-[a-f0-9]{64}$")
NONCE_RE = re.compile(r"^[a-f0-9]{32,128}$")
UTC_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$"
)
NONNEGATIVE_DECIMAL_RE = re.compile(r"^(?:0|[1-9][0-9]*)$")
POSITIVE_DECIMAL_RE = re.compile(r"^[1-9][0-9]*$")

SAFETY = {
    "fresh_project_required": True,
    "no_overwrite": True,
    "no_symlink": True,
    "no_reparse_point": True,
    "no_root_escape": True,
    "no_delete": True,
}
AUTHORITY = {
    "portable_evidence_authorizes_remote_effect": False,
    "synthetic_observation_authorizes_remote_effect": False,
    "descriptor_capability_required": True,
    "single_consumption_required": True,
    "descriptor_relative_operations_required": True,
    "path_reopen_allowed": False,
    "automatic_retry": False,
    "remote_effect_performed": False,
}

if globals().get("_AUTO_G16_LEGACY_ROOT_AUTHORITY_EXECUTED", False):
    raise ImportError("legacy root authority owner module has already executed")
_AUTO_G16_LEGACY_ROOT_AUTHORITY_EXECUTED = True


class LegacyRootAuthorityError(ValueError):
    """The fixed legacy root authority cannot be proved exactly offline."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise LegacyRootAuthorityError(message)


def _rebuild_json(value: Any, *, depth: int = 0) -> Any:
    if depth > MAX_NESTING:
        raise LegacyRootAuthorityError("legacy-root document exceeds nesting bound")
    if value is None or type(value) in {str, bool, int}:
        return value
    if type(value) is list:
        return [_rebuild_json(item, depth=depth + 1) for item in value]
    if type(value) is dict:
        keys = list(value)
        result: dict[str, Any] = {}
        for key in keys:
            if type(key) is not str:
                raise LegacyRootAuthorityError(
                    "legacy-root document keys must be exact strings"
                )
            result[key] = _rebuild_json(value[key], depth=depth + 1)
        _require(list(value) == keys, "legacy-root document changed during validation")
        return result
    raise LegacyRootAuthorityError(
        "legacy-root document accepts only exact builtin JSON values"
    )


def canonical_bytes(value: Any) -> bytes:
    try:
        text = json.dumps(
            _rebuild_json(value),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise LegacyRootAuthorityError(
            f"legacy-root document is not canonical JSON: {exc}"
        ) from exc
    return (text + "\n").encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _exact(value: Any, fields: set[str], label: str) -> dict[str, Any]:
    _require(type(value) is dict, f"{label} must be an exact object")
    _require(set(value) == fields, f"{label} fields differ")
    return value


def _text(value: Any, label: str, pattern: re.Pattern[str] = ID_RE) -> str:
    _require(
        type(value) is str and pattern.fullmatch(value) is not None,
        f"{label} is invalid",
    )
    return value


def _sha(value: Any, label: str) -> str:
    _require(
        type(value) is str
        and SHA_RE.fullmatch(value) is not None
        and value != "0" * 64,
        f"{label} is not a nonzero SHA-256",
    )
    return value


def _positive_integer(value: Any, label: str, *, maximum: int | None = None) -> int:
    _require(type(value) is int and value > 0, f"{label} must be a positive integer")
    if maximum is not None:
        _require(value <= maximum, f"{label} exceeds owner bound")
    return value


def _positive_decimal(value: Any, label: str, *, maximum: int | None = None) -> int:
    _require(
        type(value) is str and POSITIVE_DECIMAL_RE.fullmatch(value) is not None,
        f"{label} must be a canonical positive decimal string",
    )
    parsed = int(value)
    if maximum is not None:
        _require(parsed <= maximum, f"{label} exceeds owner bound")
    return parsed


def _utc(value: Any, label: str) -> datetime:
    _require(
        type(value) is str and UTC_RE.fullmatch(value) is not None,
        f"{label} must be UTC RFC3339",
    )
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


def _finalize(document: dict[str, Any], field: str) -> dict[str, Any]:
    result = copy.deepcopy(document)
    result[field] = ""
    projection = copy.deepcopy(result)
    del projection[field]
    result[field] = digest(projection)
    return result


def _self_hash(document: dict[str, Any], field: str, label: str) -> None:
    supplied = _sha(document[field], f"{label} payload hash")
    projection = copy.deepcopy(document)
    del projection[field]
    _require(
        hmac.compare_digest(supplied, digest(projection)),
        f"{label} payload hash differs",
    )


def _fixed_root_policy(value: Any) -> dict[str, Any]:
    policy = _exact(
        value,
        {
            "backend_kind",
            "allowed_root",
            "remote_root_override_allowed",
            "cli_override_allowed",
            "environment_override_allowed",
            "runtime_override_allowed",
            "caller_override_allowed",
        },
        "fixed legacy root policy",
    )
    _require(
        policy
        == {
            "backend_kind": BACKEND_KIND,
            "allowed_root": FIXED_REMOTE_ROOT,
            "remote_root_override_allowed": False,
            "cli_override_allowed": False,
            "environment_override_allowed": False,
            "runtime_override_allowed": False,
            "caller_override_allowed": False,
        },
        "fixed legacy root policy differs",
    )
    return policy


def _component_chain(value: Any, label: str) -> dict[str, Any]:
    chain = _exact(
        value,
        {"canonical_root", "components", "identity_chain_sha256"},
        label,
    )
    _require(chain["canonical_root"] == FIXED_REMOTE_ROOT, f"{label} root differs")
    _require(
        type(chain["components"]) is list and len(chain["components"]) == 3,
        f"{label} must contain the three fixed SDL components",
    )
    for index, item in enumerate(chain["components"]):
        component = _exact(
            item,
            {"ordinal", "component_path_sha256", "identity_sha256"},
            f"{label} component",
        )
        _require(
            type(component["ordinal"]) is str
            and NONNEGATIVE_DECIMAL_RE.fullmatch(component["ordinal"]) is not None
            and int(component["ordinal"]) == index,
            f"{label} component order differs",
        )
        _sha(component["component_path_sha256"], f"{label} component path")
        _sha(component["identity_sha256"], f"{label} component identity")
    expected = digest(
        {
            "schema": "auto-g16-legacy-root-component-identity-chain/1",
            "canonical_root": FIXED_REMOTE_ROOT,
            "components": chain["components"],
        }
    )
    _require(
        hmac.compare_digest(
            _sha(chain["identity_chain_sha256"], f"{label} identity chain"),
            expected,
        ),
        f"{label} identity chain differs",
    )
    return chain


def _source_bindings(value: Any) -> dict[str, str]:
    bindings = _exact(
        value,
        {
            "legacy_root_authority_source_sha256",
            "production_ingress_source_sha256",
            "owner_consumer_source_sha256",
            "runtime_state_source_sha256",
            "facade_source_sha256",
            "legacy_backend_source_sha256",
        },
        "owner source bindings",
    )
    for key, item in bindings.items():
        _sha(item, key)
    return bindings


def validate_legacy_stable_root_identity_evidence(
    document: Any,
) -> dict[str, Any]:
    evidence = _exact(
        _rebuild_json(document),
        {
            "schema",
            "owner",
            "fixed_root_policy",
            "expected_root_identity",
            "source_bindings",
            "safety",
            "stable_projection",
            "evidence_payload_sha256",
        },
        "legacy stable root identity evidence",
    )
    _require(evidence["schema"] == STABLE_SCHEMA, "legacy stable schema differs")
    owner = _exact(
        evidence["owner"],
        {"owner_id", "owner_version", "owner_source_sha256"},
        "legacy root owner",
    )
    _require(
        owner["owner_id"] == OWNER_ID and owner["owner_version"] == OWNER_VERSION,
        "legacy root owner identity differs",
    )
    _sha(owner["owner_source_sha256"], "legacy root owner source")
    _fixed_root_policy(evidence["fixed_root_policy"])
    _component_chain(evidence["expected_root_identity"], "expected root identity")
    _source_bindings(evidence["source_bindings"])
    _require(evidence["safety"] == SAFETY, "legacy root safety policy differs")
    stable = _exact(
        evidence["stable_projection"],
        {
            "observation_time_excluded",
            "expiry_excluded",
            "nonce_excluded",
            "receipt_id_excluded",
            "project_excluded",
            "attempt_excluded",
            "input_excluded",
            "per_operation_values_excluded",
        },
        "stable projection",
    )
    _require(all(item is True for item in stable.values()), "stable exclusions differ")
    forbidden = {
        "observed_at",
        "expires_at",
        "nonce",
        "receipt_id",
        "project",
        "attempt_id",
        "input_sha256",
    }
    _require(
        not forbidden.intersection(evidence),
        "stable evidence contains per-operation values",
    )
    _self_hash(evidence, "evidence_payload_sha256", "legacy stable evidence")
    return copy.deepcopy(evidence)


def _ingress_reference(value: Any) -> dict[str, str]:
    reference = _exact(
        value,
        {
            "schema",
            "contract_id",
            "contract_payload_sha256",
            "project",
            "attempt_id",
            "input_sha256",
        },
        "protected production ingress reference",
    )
    _require(reference["schema"] == INGRESS_SCHEMA, "ingress schema differs")
    _text(reference["contract_id"], "ingress contract id")
    _sha(reference["contract_payload_sha256"], "ingress contract payload")
    _text(reference["project"], "ingress project", PROJECT_RE)
    _text(reference["attempt_id"], "ingress attempt", ATTEMPT_RE)
    _sha(reference["input_sha256"], "ingress input")
    return reference


def _authorization_scope_projection(document: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "auto-g16-legacy-root-authority-scope/1",
        "authorization_id": document["authorization_id"],
        "profile": document["profile"],
        "stable_root_evidence": document["stable_root_evidence"],
        "protected_production_ingress": document["protected_production_ingress"],
        "operation": document["scope"]["operation"],
        "maximum_receipt_age_seconds": document["scope"][
            "maximum_receipt_age_seconds"
        ],
    }


def validate_legacy_root_authority_authorization(
    document: Any,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    authorization = _exact(
        _rebuild_json(document),
        {
            "schema",
            "authorization_id",
            "decision",
            "explicit_human_approval",
            "approved_at",
            "not_before",
            "expires_at",
            "fixed_root_policy",
            "profile",
            "stable_root_evidence",
            "protected_production_ingress",
            "scope",
            "authority",
            "authorization_payload_sha256",
        },
        "legacy root authority authorization",
    )
    _require(
        authorization["schema"] == AUTHORIZATION_SCHEMA,
        "legacy root authorization schema differs",
    )
    _text(authorization["authorization_id"], "legacy root authorization id")
    _require(
        authorization["decision"] == "approved"
        and authorization["explicit_human_approval"] is True,
        "legacy root authorization approval differs",
    )
    approved = _utc(authorization["approved_at"], "approved_at")
    not_before = _utc(authorization["not_before"], "not_before")
    expires = _utc(authorization["expires_at"], "expires_at")
    _require(approved <= not_before < expires, "authorization time order differs")
    _fixed_root_policy(authorization["fixed_root_policy"])
    profile = _exact(
        authorization["profile"],
        {"schema", "profile_id", "profile_payload_sha256"},
        "legacy profile reference",
    )
    _require(profile["schema"] == PROFILE_SCHEMA, "legacy profile schema differs")
    _text(profile["profile_id"], "legacy profile id")
    _sha(profile["profile_payload_sha256"], "legacy profile payload")
    stable = _exact(
        authorization["stable_root_evidence"],
        {"schema", "evidence_payload_sha256"},
        "legacy stable evidence reference",
    )
    _require(stable["schema"] == STABLE_SCHEMA, "stable evidence schema differs")
    _sha(stable["evidence_payload_sha256"], "stable evidence payload")
    _ingress_reference(authorization["protected_production_ingress"])
    scope = _exact(
        authorization["scope"],
        {
            "operation_version",
            "operation",
            "maximum_receipt_age_seconds",
            "authorization_scope_sha256",
        },
        "legacy root authorization scope",
    )
    _require(
        scope["operation_version"] == OPERATION_VERSION
        and scope["operation"] == OPERATION,
        "legacy root authorization operation differs",
    )
    _positive_decimal(
        scope["maximum_receipt_age_seconds"],
        "maximum receipt age",
        maximum=300,
    )
    _require(
        hmac.compare_digest(
            _sha(scope["authorization_scope_sha256"], "authorization scope"),
            digest(_authorization_scope_projection(authorization)),
        ),
        "authorization scope hash differs",
    )
    _require(authorization["authority"] == AUTHORITY, "authorization authority differs")
    _self_hash(
        authorization,
        "authorization_payload_sha256",
        "legacy root authorization",
    )
    if now is not None:
        current = _utc(_format_utc(now), "trusted now")
        _require(not_before <= current < expires, "authorization is outside its window")
    return copy.deepcopy(authorization)


def validate_legacy_fresh_root_observation_receipt(
    document: Any,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    receipt = _exact(
        _rebuild_json(document),
        {
            "schema",
            "profile",
            "stable_root_evidence",
            "authorization",
            "protected_production_ingress",
            "operation",
            "window",
            "observed_root",
            "comparison",
            "authority",
            "receipt_payload_sha256",
        },
        "legacy fresh root observation receipt",
    )
    _require(receipt["schema"] == RECEIPT_SCHEMA, "fresh receipt schema differs")
    profile = _exact(
        receipt["profile"],
        {"profile_id", "profile_payload_sha256"},
        "fresh receipt profile",
    )
    _text(profile["profile_id"], "fresh receipt profile id")
    _sha(profile["profile_payload_sha256"], "fresh receipt profile payload")
    stable = _exact(
        receipt["stable_root_evidence"],
        {"evidence_payload_sha256", "expected_identity_chain_sha256"},
        "fresh stable evidence",
    )
    _sha(stable["evidence_payload_sha256"], "fresh stable evidence payload")
    _sha(stable["expected_identity_chain_sha256"], "expected identity chain")
    authorization = _exact(
        receipt["authorization"],
        {
            "authorization_id",
            "authorization_payload_sha256",
            "authorization_scope_sha256",
        },
        "fresh authorization reference",
    )
    _text(authorization["authorization_id"], "fresh authorization id")
    _sha(authorization["authorization_payload_sha256"], "fresh authorization payload")
    _sha(authorization["authorization_scope_sha256"], "fresh authorization scope")
    _ingress_reference(receipt["protected_production_ingress"])
    operation = _exact(
        receipt["operation"],
        {
            "operation_version",
            "operation",
            "project",
            "attempt_id",
            "input_sha256",
            "nonce",
        },
        "fresh operation",
    )
    _require(
        operation["operation_version"] == OPERATION_VERSION
        and operation["operation"] == OPERATION,
        "fresh operation differs",
    )
    _text(operation["project"], "fresh project", PROJECT_RE)
    _text(operation["attempt_id"], "fresh attempt", ATTEMPT_RE)
    _sha(operation["input_sha256"], "fresh input")
    _text(operation["nonce"], "fresh nonce", NONCE_RE)
    window = _exact(
        receipt["window"],
        {"observed_at", "expires_at", "maximum_receipt_age_seconds"},
        "fresh receipt window",
    )
    observed_at = _utc(window["observed_at"], "fresh observed_at")
    expires_at = _utc(window["expires_at"], "fresh expires_at")
    age = _positive_decimal(
        window["maximum_receipt_age_seconds"],
        "fresh maximum age",
        maximum=300,
    )
    _require(
        expires_at == observed_at + timedelta(seconds=age),
        "fresh receipt expiry differs",
    )
    observed = _exact(
        receipt["observed_root"],
        {
            "identity",
            "project",
            "remote_workdir",
            "scratch_workdir",
            "workspace_binding_sha256",
            "descriptor_set_sha256",
            "fresh_project",
            "containment_verified",
            "symlink_detected",
            "reparse_point_detected",
            "root_escape_detected",
        },
        "fresh observed root",
    )
    chain = _component_chain(observed["identity"], "fresh observed identity")
    project = _text(observed["project"], "fresh observed project", PROJECT_RE)
    _require(
        observed["remote_workdir"] == f"{FIXED_REMOTE_ROOT}/{project}"
        and observed["scratch_workdir"]
        == f"{FIXED_REMOTE_ROOT}/{project}/scratch",
        "fresh workspace paths differ",
    )
    expected_workspace = digest(
        {
            "schema": "auto-g16-legacy-workspace-binding/1",
            "project": project,
            "allowed_root": FIXED_REMOTE_ROOT,
            "remote_workdir": observed["remote_workdir"],
            "scratch_workdir": observed["scratch_workdir"],
        }
    )
    _require(
        hmac.compare_digest(
            _sha(observed["workspace_binding_sha256"], "fresh workspace binding"),
            expected_workspace,
        ),
        "fresh workspace binding differs",
    )
    _sha(observed["descriptor_set_sha256"], "fresh descriptor set")
    _require(
        observed["fresh_project"] is True
        and observed["containment_verified"] is True
        and observed["symlink_detected"] is False
        and observed["reparse_point_detected"] is False
        and observed["root_escape_detected"] is False,
        "fresh root checks failed",
    )
    comparison = _exact(
        receipt["comparison"],
        {
            "profile_matches",
            "stable_evidence_matches",
            "authorization_scope_matches",
            "production_ingress_matches",
            "root_identity_matches",
            "workspace_matches",
            "classification",
        },
        "fresh comparison",
    )
    _require(
        all(comparison[key] is True for key in comparison if key != "classification")
        and comparison["classification"] == "verified",
        "fresh comparison is not verified",
    )
    _require(receipt["authority"] == AUTHORITY, "fresh receipt authority differs")
    _require(
        operation["project"]
        == project
        == receipt["protected_production_ingress"]["project"]
        and operation["attempt_id"]
        == receipt["protected_production_ingress"]["attempt_id"]
        and operation["input_sha256"]
        == receipt["protected_production_ingress"]["input_sha256"]
        and chain["identity_chain_sha256"]
        == stable["expected_identity_chain_sha256"],
        "fresh receipt cross-field identity differs",
    )
    _self_hash(receipt, "receipt_payload_sha256", "legacy fresh receipt")
    if now is not None:
        current = _utc(_format_utc(now), "trusted now")
        _require(observed_at <= current < expires_at, "fresh receipt is outside its window")
    return copy.deepcopy(receipt)


@dataclass(frozen=True, slots=True)
class _FileSnapshot:
    path: Path
    identity: tuple[int, ...]
    sha256: str
    source_bytes: bytes


@dataclass(frozen=True, slots=True)
class _IngressBinding:
    module: types.ModuleType
    sealed_type: type
    source: _FileSnapshot
    source_bindings: tuple[tuple[str, str], ...]


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


def _stable_source(path: Path) -> _FileSnapshot:
    descriptor = -1
    try:
        before = os.stat(path, follow_symlinks=False)
        _require(
            stat.S_ISREG(before.st_mode) and not stat.S_ISLNK(before.st_mode),
            "owner source must be a no-follow regular file",
        )
        descriptor = os.open(
            path,
            os.O_RDONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
        )
        opened = os.fstat(descriptor)
        _require(
            _stat_identity(opened) == _stat_identity(before),
            "owner source changed while opening",
        )
        _require(
            0 < opened.st_size <= MAX_DOCUMENT_BYTES,
            "owner source size is outside the bound",
        )
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 65536)
            if not chunk:
                break
            chunks.append(chunk)
        after_fd = os.fstat(descriptor)
        after_path = os.stat(path, follow_symlinks=False)
    except OSError as exc:
        raise LegacyRootAuthorityError(f"stable owner source read failed: {exc}") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    _require(
        len(
            {
                _stat_identity(before),
                _stat_identity(opened),
                _stat_identity(after_fd),
                _stat_identity(after_path),
            }
        )
        == 1,
        "owner source identity drifted",
    )
    raw = b"".join(chunks)
    _require(len(raw) == opened.st_size, "owner source stable read was short")
    return _FileSnapshot(
        path=path.resolve(strict=True),
        identity=_stat_identity(opened),
        sha256=hashlib.sha256(raw).hexdigest(),
        source_bytes=raw,
    )


def _module_origin(module: types.ModuleType) -> tuple[Path, Path]:
    raw_file = getattr(module, "__file__", None)
    raw_origin = getattr(getattr(module, "__spec__", None), "origin", None)
    _require(
        type(raw_file) is str and type(raw_origin) is str,
        "bound owner module has no exact origin",
    )
    return Path(raw_file).resolve(), Path(raw_origin).resolve()


def _owner_path() -> Path:
    path = Path(__file__).resolve(strict=True)
    _require(path.is_file() and not path.is_symlink(), "legacy root owner is unavailable")
    return path


def _ingress_path() -> Path:
    here = _owner_path()
    path = here.with_name(f"{INGRESS_MODULE_NAME}.py")
    _require(
        path.is_file() and not path.is_symlink() and path.resolve().parent == here.parent,
        "exact adjacent production-ingress owner is unavailable",
    )
    return path.resolve(strict=True)


_OWNER_SOURCE = _stable_source(_owner_path())


def _capture_ingress_binding() -> _IngressBinding:
    path = _ingress_path()
    module = sys.modules.get(INGRESS_MODULE_NAME)
    if not isinstance(module, types.ModuleType) or _module_origin(module) != (path, path):
        raise ImportError("exact production-ingress owner must load first")
    sealed_type = getattr(module, "SealedProtectedProductionIngressCapability", None)
    if not isinstance(sealed_type, type):
        raise ImportError("production-ingress sealed class identity differs")
    ingress_source = getattr(module, "_OWNER_SOURCE", None)
    consumer = getattr(module, "_CONSUMER_BINDING", None)
    facade = getattr(module, "_FACADE_BINDING", None)
    legacy = getattr(module, "_LEGACY_BINDING", None)
    runtime = getattr(getattr(consumer, "module", None), "_RUNTIME_BINDING", None)
    values = {
        "production_ingress_source_sha256": getattr(ingress_source, "sha256", None),
        "owner_consumer_source_sha256": getattr(
            getattr(consumer, "source", None), "sha256", None
        ),
        "runtime_state_source_sha256": getattr(
            getattr(runtime, "source", None), "sha256", None
        ),
        "facade_source_sha256": getattr(
            getattr(facade, "source", None), "sha256", None
        ),
        "legacy_backend_source_sha256": getattr(
            getattr(legacy, "source", None), "sha256", None
        ),
    }
    if any(type(value) is not str or SHA_RE.fullmatch(value) is None for value in values.values()):
        raise ImportError("protected owner source bindings are unavailable")
    return _IngressBinding(
        module=module,
        sealed_type=sealed_type,
        source=_stable_source(path),
        source_bindings=tuple(values.items()),
    )


_INGRESS_BINDING = _capture_ingress_binding()
_OWNER_MODULE = sys.modules.get(MODULE_NAME)


def _assert_bindings_current() -> None:
    _require(
        isinstance(_OWNER_MODULE, types.ModuleType)
        and sys.modules.get(MODULE_NAME) is _OWNER_MODULE
        and _module_origin(_OWNER_MODULE) == (_owner_path(), _owner_path())
        and _stable_source(_owner_path()) == _OWNER_SOURCE,
        "legacy root owner module/source identity differs",
    )
    _require(
        sys.modules.get(INGRESS_MODULE_NAME) is _INGRESS_BINDING.module
        and _module_origin(_INGRESS_BINDING.module)
        == (_INGRESS_BINDING.source.path, _INGRESS_BINDING.source.path)
        and _stable_source(_INGRESS_BINDING.source.path) == _INGRESS_BINDING.source
        and getattr(
            _INGRESS_BINDING.module,
            "SealedProtectedProductionIngressCapability",
            None,
        )
        is _INGRESS_BINDING.sealed_type,
        "production-ingress module/source/class identity differs",
    )
    assertion = getattr(_INGRESS_BINDING.module, "_assert_bindings_current", None)
    _require(callable(assertion), "production-ingress replay owner is unavailable")
    assertion()
    current = _capture_ingress_binding()
    _require(
        current.module is _INGRESS_BINDING.module
        and current.sealed_type is _INGRESS_BINDING.sealed_type
        and current.source == _INGRESS_BINDING.source
        and current.source_bindings == _INGRESS_BINDING.source_bindings,
        "protected owner source binding drifted",
    )
    for name in _ISSUED_TYPE_NAMES:
        _require(
            getattr(_OWNER_MODULE, name, None) is _ISSUED_TYPES[name],
            f"legacy root owner class identity differs: {name}",
        )


_SEAL_TOKEN = object()
_SNAPSHOT_TOKEN = object()
_CAPABILITY_TOKEN = object()
_LEASE_TOKEN = object()
_OWNER_TOKEN = object()
_TEST_TOKEN = object()


@dataclass(frozen=True, slots=True, init=False)
class LegacyStableRootIdentityEvidence:
    _canonical_document: bytes
    _seal: object

    def __new__(cls, *args: Any, **kwargs: Any) -> "LegacyStableRootIdentityEvidence":
        raise TypeError("legacy stable root evidence is owner-issued only")

    @classmethod
    def _from_owner(
        cls, document: dict[str, Any], *, token: object
    ) -> "LegacyStableRootIdentityEvidence":
        _assert_bindings_current()
        _require(
            cls is _ISSUED_TYPES["LegacyStableRootIdentityEvidence"]
            and token is _SEAL_TOKEN,
            "legacy stable evidence seal differs",
        )
        value = object.__new__(cls)
        object.__setattr__(value, "_canonical_document", canonical_bytes(document))
        object.__setattr__(value, "_seal", _SEAL_TOKEN)
        return value

    def document(self) -> dict[str, Any]:
        return json.loads(self._canonical_document)

    def assert_current(self) -> "LegacyStableRootIdentityEvidence":
        _assert_bindings_current()
        _require(
            type(self) is _ISSUED_TYPES["LegacyStableRootIdentityEvidence"]
            and self._seal is _SEAL_TOKEN,
            "legacy stable evidence seal differs",
        )
        validated = validate_legacy_stable_root_identity_evidence(self.document())
        _require(
            canonical_bytes(validated) == self._canonical_document,
            "legacy stable evidence projection differs",
        )
        return self

    def __copy__(self) -> "LegacyStableRootIdentityEvidence":
        raise TypeError("legacy stable root evidence is not clonable")

    def __deepcopy__(self, memo: dict[int, Any]) -> "LegacyStableRootIdentityEvidence":
        del memo
        raise TypeError("legacy stable root evidence is not clonable")

    def __reduce__(self) -> object:
        raise TypeError("legacy stable root evidence is not serializable")

    def __reduce_ex__(self, protocol: int) -> object:
        del protocol
        raise TypeError("legacy stable root evidence is not serializable")


@dataclass(frozen=True, slots=True, init=False)
class LegacyFreshRootObservationReceipt:
    _canonical_document: bytes
    _seal: object

    def __new__(cls, *args: Any, **kwargs: Any) -> "LegacyFreshRootObservationReceipt":
        raise TypeError("legacy fresh root receipts are owner-issued only")

    @classmethod
    def _from_owner(
        cls, document: dict[str, Any], *, token: object
    ) -> "LegacyFreshRootObservationReceipt":
        _assert_bindings_current()
        _require(
            cls is _ISSUED_TYPES["LegacyFreshRootObservationReceipt"]
            and token is _SEAL_TOKEN,
            "legacy fresh receipt seal differs",
        )
        value = object.__new__(cls)
        object.__setattr__(value, "_canonical_document", canonical_bytes(document))
        object.__setattr__(value, "_seal", _SEAL_TOKEN)
        return value

    def document(self) -> dict[str, Any]:
        return json.loads(self._canonical_document)

    def assert_current(self) -> "LegacyFreshRootObservationReceipt":
        _assert_bindings_current()
        _require(
            type(self) is _ISSUED_TYPES["LegacyFreshRootObservationReceipt"]
            and self._seal is _SEAL_TOKEN,
            "legacy fresh receipt seal differs",
        )
        validated = validate_legacy_fresh_root_observation_receipt(self.document())
        _require(
            canonical_bytes(validated) == self._canonical_document,
            "legacy fresh receipt projection differs",
        )
        return self

    def __copy__(self) -> "LegacyFreshRootObservationReceipt":
        raise TypeError("legacy fresh root receipt is not clonable")

    def __deepcopy__(self, memo: dict[int, Any]) -> "LegacyFreshRootObservationReceipt":
        del memo
        raise TypeError("legacy fresh root receipt is not clonable")

    def __reduce__(self) -> object:
        raise TypeError("legacy fresh root receipt is not serializable")

    def __reduce_ex__(self, protocol: int) -> object:
        del protocol
        raise TypeError("legacy fresh root receipt is not serializable")


@dataclass(frozen=True, slots=True, init=False)
class _RootIdentitySnapshot:
    components: tuple[tuple[str, str, str], ...]
    identity_chain_sha256: str
    _seal: object

    def __new__(cls, *args: Any, **kwargs: Any) -> "_RootIdentitySnapshot":
        raise TypeError("legacy root snapshots are owner-issued only")

    @classmethod
    def _from_owner(
        cls, component_identity_seeds: list[str], *, token: object
    ) -> "_RootIdentitySnapshot":
        _require(
            cls is _RootIdentitySnapshot
            and token is _SNAPSHOT_TOKEN
            and type(component_identity_seeds) is list
            and len(component_identity_seeds) == 3
            and all(type(item) is str and item for item in component_identity_seeds),
            "legacy root snapshot inputs differ",
        )
        paths = ("/home", "/home/user100", FIXED_REMOTE_ROOT)
        components = [
            {
                "ordinal": str(index),
                "component_path_sha256": hashlib.sha256(path.encode()).hexdigest(),
                "identity_sha256": hashlib.sha256(seed.encode()).hexdigest(),
            }
            for index, (path, seed) in enumerate(
                zip(paths, component_identity_seeds)
            )
        ]
        chain = {
            "canonical_root": FIXED_REMOTE_ROOT,
            "components": components,
            "identity_chain_sha256": digest(
                {
                    "schema": "auto-g16-legacy-root-component-identity-chain/1",
                    "canonical_root": FIXED_REMOTE_ROOT,
                    "components": components,
                }
            ),
        }
        _component_chain(chain, "legacy root snapshot")
        value = object.__new__(cls)
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
        object.__setattr__(value, "_seal", _SNAPSHOT_TOKEN)
        return value

    def document(self) -> dict[str, Any]:
        return {
            "canonical_root": FIXED_REMOTE_ROOT,
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

    def assert_current(self) -> "_RootIdentitySnapshot":
        _require(
            type(self) is _RootIdentitySnapshot and self._seal is _SNAPSHOT_TOKEN,
            "legacy root snapshot seal differs",
        )
        _component_chain(self.document(), "legacy root snapshot")
        return self


@dataclass(frozen=True, slots=True, init=False)
class _DescriptorSet:
    identity_chain_sha256: str
    workspace_binding_sha256: str
    descriptor_set_sha256: str
    _opaque_handles: tuple[object, ...]
    _seal: object

    def __new__(cls, *args: Any, **kwargs: Any) -> "_DescriptorSet":
        raise TypeError("legacy descriptor sets are owner-issued only")

    @classmethod
    def _from_owner(
        cls,
        *,
        identity_chain_sha256: str,
        workspace_binding_sha256: str,
        token: object,
    ) -> "_DescriptorSet":
        _require(
            cls is _DescriptorSet and token is _SNAPSHOT_TOKEN,
            "legacy descriptor set seal differs",
        )
        handles = (object(), object(), object())
        set_sha = digest(
            {
                "schema": "auto-g16-legacy-offline-descriptor-set-model/1",
                "identity_chain_sha256": identity_chain_sha256,
                "workspace_binding_sha256": workspace_binding_sha256,
                "handle_count": "3",
                "path_reopen_allowed": False,
            }
        )
        value = object.__new__(cls)
        object.__setattr__(value, "identity_chain_sha256", identity_chain_sha256)
        object.__setattr__(value, "workspace_binding_sha256", workspace_binding_sha256)
        object.__setattr__(value, "descriptor_set_sha256", set_sha)
        object.__setattr__(value, "_opaque_handles", handles)
        object.__setattr__(value, "_seal", _SNAPSHOT_TOKEN)
        return value

    def assert_current(self) -> "_DescriptorSet":
        _require(
            type(self) is _DescriptorSet
            and self._seal is _SNAPSHOT_TOKEN
            and type(self._opaque_handles) is tuple
            and len(self._opaque_handles) == 3
            and all(type(item) is object for item in self._opaque_handles),
            "legacy descriptor set identity differs",
        )
        expected = digest(
            {
                "schema": "auto-g16-legacy-offline-descriptor-set-model/1",
                "identity_chain_sha256": self.identity_chain_sha256,
                "workspace_binding_sha256": self.workspace_binding_sha256,
                "handle_count": "3",
                "path_reopen_allowed": False,
            }
        )
        _require(
            hmac.compare_digest(self.descriptor_set_sha256, expected),
            "legacy descriptor set digest differs",
        )
        return self


@dataclass(frozen=True, slots=True, init=False)
class _WorkspaceObservation:
    root: _RootIdentitySnapshot
    project: str
    remote_workdir: str
    scratch_workdir: str
    workspace_binding_sha256: str
    fresh_project: bool
    containment_verified: bool
    symlink_detected: bool
    reparse_point_detected: bool
    root_escape_detected: bool
    descriptor_set: _DescriptorSet
    _seal: object

    def __new__(cls, *args: Any, **kwargs: Any) -> "_WorkspaceObservation":
        raise TypeError("legacy workspace observations are owner-issued only")

    @classmethod
    def _from_owner(
        cls,
        *,
        root: _RootIdentitySnapshot,
        project: str,
        fresh_project: bool,
        containment_verified: bool,
        symlink_detected: bool,
        reparse_point_detected: bool,
        root_escape_detected: bool,
        token: object,
    ) -> "_WorkspaceObservation":
        _require(
            cls is _WorkspaceObservation
            and token is _SNAPSHOT_TOKEN
            and type(root) is _RootIdentitySnapshot,
            "legacy workspace observation seal differs",
        )
        root.assert_current()
        project = _text(project, "legacy workspace project", PROJECT_RE)
        remote = f"{FIXED_REMOTE_ROOT}/{project}"
        scratch = f"{remote}/scratch"
        workspace_sha = digest(
            {
                "schema": "auto-g16-legacy-workspace-binding/1",
                "project": project,
                "allowed_root": FIXED_REMOTE_ROOT,
                "remote_workdir": remote,
                "scratch_workdir": scratch,
            }
        )
        descriptor_set = _DescriptorSet._from_owner(
            identity_chain_sha256=root.identity_chain_sha256,
            workspace_binding_sha256=workspace_sha,
            token=_SNAPSHOT_TOKEN,
        )
        value = object.__new__(cls)
        for name, item in (
            ("root", root),
            ("project", project),
            ("remote_workdir", remote),
            ("scratch_workdir", scratch),
            ("workspace_binding_sha256", workspace_sha),
            ("fresh_project", fresh_project),
            ("containment_verified", containment_verified),
            ("symlink_detected", symlink_detected),
            ("reparse_point_detected", reparse_point_detected),
            ("root_escape_detected", root_escape_detected),
            ("descriptor_set", descriptor_set),
            ("_seal", _SNAPSHOT_TOKEN),
        ):
            object.__setattr__(value, name, item)
        return value

    def assert_current(self) -> "_WorkspaceObservation":
        _require(
            type(self) is _WorkspaceObservation and self._seal is _SNAPSHOT_TOKEN,
            "legacy workspace observation seal differs",
        )
        self.root.assert_current()
        self.descriptor_set.assert_current()
        _require(
            self.descriptor_set.identity_chain_sha256 == self.root.identity_chain_sha256
            and self.descriptor_set.workspace_binding_sha256
            == self.workspace_binding_sha256,
            "legacy workspace descriptor binding differs",
        )
        return self


@dataclass(frozen=True, slots=True, init=False)
class ConsumedLegacyWorkspaceDescriptorLease:
    receipt_payload_sha256: str
    authorization_scope_sha256: str
    production_ingress_contract_id: str
    descriptor_set_sha256: str
    remote_effect_authorized: bool
    path_reopen_allowed: bool
    _descriptor_set: _DescriptorSet
    _seal: object

    def __new__(
        cls, *args: Any, **kwargs: Any
    ) -> "ConsumedLegacyWorkspaceDescriptorLease":
        raise TypeError("legacy workspace descriptor leases are owner-issued only")

    @classmethod
    def _from_owner(
        cls,
        *,
        receipt: dict[str, Any],
        descriptor_set: _DescriptorSet,
        token: object,
    ) -> "ConsumedLegacyWorkspaceDescriptorLease":
        _assert_bindings_current()
        _require(
            cls is _ISSUED_TYPES["ConsumedLegacyWorkspaceDescriptorLease"]
            and token is _LEASE_TOKEN,
            "legacy descriptor lease seal differs",
        )
        descriptor_set.assert_current()
        value = object.__new__(cls)
        object.__setattr__(
            value, "receipt_payload_sha256", receipt["receipt_payload_sha256"]
        )
        object.__setattr__(
            value,
            "authorization_scope_sha256",
            receipt["authorization"]["authorization_scope_sha256"],
        )
        object.__setattr__(
            value,
            "production_ingress_contract_id",
            receipt["protected_production_ingress"]["contract_id"],
        )
        object.__setattr__(
            value, "descriptor_set_sha256", descriptor_set.descriptor_set_sha256
        )
        object.__setattr__(value, "remote_effect_authorized", False)
        object.__setattr__(value, "path_reopen_allowed", False)
        object.__setattr__(value, "_descriptor_set", descriptor_set)
        object.__setattr__(value, "_seal", _LEASE_TOKEN)
        return value

    def assert_current(self) -> "ConsumedLegacyWorkspaceDescriptorLease":
        _assert_bindings_current()
        _require(
            type(self) is _ISSUED_TYPES["ConsumedLegacyWorkspaceDescriptorLease"]
            and self._seal is _LEASE_TOKEN,
            "legacy descriptor lease seal differs",
        )
        self._descriptor_set.assert_current()
        _require(
            self.descriptor_set_sha256 == self._descriptor_set.descriptor_set_sha256
            and self.remote_effect_authorized is False
            and self.path_reopen_allowed is False,
            "legacy descriptor lease binding differs",
        )
        return self

    def __copy__(self) -> "ConsumedLegacyWorkspaceDescriptorLease":
        raise TypeError("legacy descriptor lease is not clonable")

    def __deepcopy__(
        self, memo: dict[int, Any]
    ) -> "ConsumedLegacyWorkspaceDescriptorLease":
        del memo
        raise TypeError("legacy descriptor lease is not clonable")

    def __reduce__(self) -> object:
        raise TypeError("legacy descriptor lease is not serializable")

    def __reduce_ex__(self, protocol: int) -> object:
        del protocol
        raise TypeError("legacy descriptor lease is not serializable")


@dataclass(slots=True)
class _CapabilityState:
    capability: object
    ingress: object
    ingress_document: bytes
    evidence: LegacyStableRootIdentityEvidence
    authorization: bytes
    receipt: LegacyFreshRootObservationReceipt
    descriptor_set: _DescriptorSet
    descriptor_handles: tuple[object, ...]
    clock: Callable[[], datetime]
    lock: threading.Lock
    consumed: bool = False
    latest_now: datetime | None = None


_CAPABILITY_REGISTRY_LOCK = threading.Lock()
_CAPABILITY_REGISTRY: dict[int, _CapabilityState] = {}


def _register_capability(capability: object, state: _CapabilityState) -> None:
    _require(state.capability is capability, "capability owner state differs")
    with _CAPABILITY_REGISTRY_LOCK:
        _require(
            id(capability) not in _CAPABILITY_REGISTRY,
            "capability owner state is already registered",
        )
        _CAPABILITY_REGISTRY[id(capability)] = state


def _capability_state(capability: object) -> _CapabilityState:
    with _CAPABILITY_REGISTRY_LOCK:
        state = _CAPABILITY_REGISTRY.get(id(capability))
    _require(
        type(state) is _CapabilityState and state.capability is capability,
        "capability owner-private state is unavailable",
    )
    return state


def _trusted_now(state: _CapabilityState) -> datetime:
    current = state.clock()
    _format_utc(current)
    if state.latest_now is not None:
        _require(current >= state.latest_now, "trusted clock moved backward")
    state.latest_now = current
    return current


@dataclass(frozen=True, slots=True, init=False)
class SingleUseLegacyWorkspaceDescriptorCapability:
    evidence: LegacyStableRootIdentityEvidence
    receipt: LegacyFreshRootObservationReceipt
    _ingress_identity: object
    _evidence_identity: LegacyStableRootIdentityEvidence
    _receipt_identity: LegacyFreshRootObservationReceipt
    _authorization_bytes: bytes
    _descriptor_set: _DescriptorSet
    _descriptor_handles: tuple[object, ...]
    _seal: object

    def __new__(
        cls, *args: Any, **kwargs: Any
    ) -> "SingleUseLegacyWorkspaceDescriptorCapability":
        raise TypeError("legacy workspace capabilities are owner-issued only")

    @classmethod
    def _from_owner(
        cls,
        *,
        ingress: object,
        evidence: LegacyStableRootIdentityEvidence,
        authorization: dict[str, Any],
        receipt: LegacyFreshRootObservationReceipt,
        descriptor_set: _DescriptorSet,
        clock: Callable[[], datetime],
        token: object,
    ) -> "SingleUseLegacyWorkspaceDescriptorCapability":
        _assert_bindings_current()
        _require(
            cls is _ISSUED_TYPES["SingleUseLegacyWorkspaceDescriptorCapability"]
            and token is _CAPABILITY_TOKEN,
            "legacy workspace capability seal differs",
        )
        value = object.__new__(cls)
        for name, item in (
            ("evidence", evidence),
            ("receipt", receipt),
            ("_ingress_identity", ingress),
            ("_evidence_identity", evidence),
            ("_receipt_identity", receipt),
            ("_authorization_bytes", canonical_bytes(authorization)),
            ("_descriptor_set", descriptor_set),
            ("_descriptor_handles", descriptor_set._opaque_handles),
            ("_seal", _CAPABILITY_TOKEN),
        ):
            object.__setattr__(value, name, item)
        _register_capability(
            value,
            _CapabilityState(
                capability=value,
                ingress=ingress,
                ingress_document=canonical_bytes(ingress.document()),
                evidence=evidence,
                authorization=canonical_bytes(authorization),
                receipt=receipt,
                descriptor_set=descriptor_set,
                descriptor_handles=descriptor_set._opaque_handles,
                clock=clock,
                lock=threading.Lock(),
            ),
        )
        return value

    def portable_receipt(self) -> dict[str, Any]:
        return self.receipt.document()

    def _assert_current_locked(self, state: _CapabilityState) -> None:
        _assert_bindings_current()
        _require(
            type(self) is _ISSUED_TYPES[
                "SingleUseLegacyWorkspaceDescriptorCapability"
            ]
            and self._seal is _CAPABILITY_TOKEN,
            "legacy workspace capability seal differs",
        )
        _require(
            self._ingress_identity is state.ingress
            and self.evidence is state.evidence
            and self.receipt is state.receipt
            and self._evidence_identity is state.evidence
            and self._receipt_identity is state.receipt
            and self._authorization_bytes == state.authorization
            and self._descriptor_set is state.descriptor_set
            and self._descriptor_handles is state.descriptor_handles,
            "legacy workspace capability snapshot differs",
        )
        _require(
            type(state.ingress) is _INGRESS_BINDING.sealed_type,
            "production-ingress capability type differs",
        )
        state.ingress.assert_current()
        _require(
            canonical_bytes(state.ingress.document()) == state.ingress_document,
            "production-ingress capability projection drifted",
        )
        state.evidence.assert_current()
        now = _trusted_now(state)
        authorization = validate_legacy_root_authority_authorization(
            json.loads(state.authorization),
            now=now,
        )
        receipt = validate_legacy_fresh_root_observation_receipt(
            state.receipt.document(),
            now=now,
        )
        state.descriptor_set.assert_current()
        _require(
            state.descriptor_set._opaque_handles is state.descriptor_handles,
            "legacy descriptor handles were replaced",
        )
        ingress = state.ingress.document()
        _require(
            ingress["contract_id"]
            == authorization["protected_production_ingress"]["contract_id"]
            == receipt["protected_production_ingress"]["contract_id"]
            and ingress["contract_payload_sha256"]
            == authorization["protected_production_ingress"][
                "contract_payload_sha256"
            ]
            == receipt["protected_production_ingress"][
                "contract_payload_sha256"
            ],
            "production-ingress replay differs",
        )
        _require(
            receipt["observed_root"]["descriptor_set_sha256"]
            == state.descriptor_set.descriptor_set_sha256,
            "legacy descriptor receipt binding differs",
        )

    def assert_current(self) -> "SingleUseLegacyWorkspaceDescriptorCapability":
        state = _capability_state(self)
        with state.lock:
            self._assert_current_locked(state)
        return self

    def consume_once(self) -> ConsumedLegacyWorkspaceDescriptorLease:
        """Consume the owner-retained offline descriptor model exactly once."""
        state = _capability_state(self)
        with state.lock:
            if state.consumed:
                raise LegacyRootAuthorityError(
                    "legacy workspace descriptor capability is already consumed"
                )
            self._assert_current_locked(state)
            state.consumed = True
            return ConsumedLegacyWorkspaceDescriptorLease._from_owner(
                receipt=state.receipt.document(),
                descriptor_set=state.descriptor_set,
                token=_LEASE_TOKEN,
            )

    def __copy__(self) -> "SingleUseLegacyWorkspaceDescriptorCapability":
        raise TypeError("legacy workspace capability is not clonable")

    def __deepcopy__(
        self, memo: dict[int, Any]
    ) -> "SingleUseLegacyWorkspaceDescriptorCapability":
        del memo
        raise TypeError("legacy workspace capability is not clonable")

    def __reduce__(self) -> object:
        raise TypeError("legacy workspace capability is not serializable")

    def __reduce_ex__(self, protocol: int) -> object:
        del protocol
        raise TypeError("legacy workspace capability is not serializable")


class LegacyRootAuthorityContractOwner:
    """Issue stable legacy evidence and one effect-free fresh capability."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime],
        nonce_source: Callable[[], str],
        _factory_token: object,
    ) -> None:
        _assert_bindings_current()
        if (
            type(self) is not _ISSUED_TYPES["LegacyRootAuthorityContractOwner"]
            or _factory_token is not _OWNER_TOKEN
            or not callable(clock)
            or not callable(nonce_source)
        ):
            raise TypeError("legacy root owner requires its private offline factory")
        self._clock = clock
        self._nonce_source = nonce_source
        self._lock = threading.Lock()
        self._fresh_used = False

    @classmethod
    def _for_testing(
        cls,
        *,
        clock: Callable[[], datetime],
        nonce_source: Callable[[], str],
        _test_token: object,
    ) -> "LegacyRootAuthorityContractOwner":
        if _test_token is not _TEST_TOKEN:
            raise TypeError("legacy root owner private test token differs")
        return cls(
            clock=clock,
            nonce_source=nonce_source,
            _factory_token=_OWNER_TOKEN,
        )

    def _root_snapshot_for_testing(
        self,
        component_identity_seeds: list[str],
        *,
        _test_token: object,
    ) -> _RootIdentitySnapshot:
        if _test_token is not _TEST_TOKEN:
            raise TypeError("legacy root snapshot private test token differs")
        return _RootIdentitySnapshot._from_owner(
            component_identity_seeds,
            token=_SNAPSHOT_TOKEN,
        )

    def _workspace_observation_for_testing(
        self,
        *,
        root: _RootIdentitySnapshot,
        project: str,
        fresh_project: bool = True,
        containment_verified: bool = True,
        symlink_detected: bool = False,
        reparse_point_detected: bool = False,
        root_escape_detected: bool = False,
        _test_token: object,
    ) -> _WorkspaceObservation:
        if _test_token is not _TEST_TOKEN:
            raise TypeError("legacy workspace observation private test token differs")
        return _WorkspaceObservation._from_owner(
            root=root,
            project=project,
            fresh_project=fresh_project,
            containment_verified=containment_verified,
            symlink_detected=symlink_detected,
            reparse_point_detected=reparse_point_detected,
            root_escape_detected=root_escape_detected,
            token=_SNAPSHOT_TOKEN,
        )

    def issue_stable_evidence(
        self, expected_root: _RootIdentitySnapshot
    ) -> LegacyStableRootIdentityEvidence:
        _assert_bindings_current()
        _require(
            type(expected_root) is _RootIdentitySnapshot,
            "legacy stable evidence requires exact owner snapshot",
        )
        expected_root.assert_current()
        sources = {
            "legacy_root_authority_source_sha256": _OWNER_SOURCE.sha256,
            **dict(_INGRESS_BINDING.source_bindings),
        }
        document = {
            "schema": STABLE_SCHEMA,
            "owner": {
                "owner_id": OWNER_ID,
                "owner_version": OWNER_VERSION,
                "owner_source_sha256": _OWNER_SOURCE.sha256,
            },
            "fixed_root_policy": {
                "backend_kind": BACKEND_KIND,
                "allowed_root": FIXED_REMOTE_ROOT,
                "remote_root_override_allowed": False,
                "cli_override_allowed": False,
                "environment_override_allowed": False,
                "runtime_override_allowed": False,
                "caller_override_allowed": False,
            },
            "expected_root_identity": expected_root.document(),
            "source_bindings": sources,
            "safety": copy.deepcopy(SAFETY),
            "stable_projection": {
                "observation_time_excluded": True,
                "expiry_excluded": True,
                "nonce_excluded": True,
                "receipt_id_excluded": True,
                "project_excluded": True,
                "attempt_excluded": True,
                "input_excluded": True,
                "per_operation_values_excluded": True,
            },
            "evidence_payload_sha256": "",
        }
        validated = validate_legacy_stable_root_identity_evidence(
            _finalize(document, "evidence_payload_sha256")
        )
        sealed = LegacyStableRootIdentityEvidence._from_owner(
            validated,
            token=_SEAL_TOKEN,
        )
        sealed.assert_current()
        return sealed

    def build_authorization(
        self,
        *,
        authorization_id: str,
        profile_id: str,
        profile_payload_sha256: str,
        stable_evidence: LegacyStableRootIdentityEvidence,
        protected_production_ingress: object,
        approved_at: str,
        not_before: str,
        expires_at: str,
        maximum_receipt_age_seconds: int,
    ) -> dict[str, Any]:
        _assert_bindings_current()
        _positive_integer(
            maximum_receipt_age_seconds,
            "maximum receipt age",
            maximum=300,
        )
        _require(
            type(stable_evidence) is _ISSUED_TYPES[
                "LegacyStableRootIdentityEvidence"
            ],
            "legacy authorization requires exact stable evidence",
        )
        stable_evidence.assert_current()
        _require(
            type(protected_production_ingress) is _INGRESS_BINDING.sealed_type,
            "legacy authorization requires exact production ingress",
        )
        protected_production_ingress.assert_current()
        ingress = protected_production_ingress.document()
        identity = ingress["identity"]
        ingress_ref = {
            "schema": ingress["schema"],
            "contract_id": ingress["contract_id"],
            "contract_payload_sha256": ingress["contract_payload_sha256"],
            "project": identity["project"],
            "attempt_id": identity["attempt_id"],
            "input_sha256": identity["input_sha256"],
        }
        stable = stable_evidence.document()
        document = {
            "schema": AUTHORIZATION_SCHEMA,
            "authorization_id": authorization_id,
            "decision": "approved",
            "explicit_human_approval": True,
            "approved_at": approved_at,
            "not_before": not_before,
            "expires_at": expires_at,
            "fixed_root_policy": {
                "backend_kind": BACKEND_KIND,
                "allowed_root": FIXED_REMOTE_ROOT,
                "remote_root_override_allowed": False,
                "cli_override_allowed": False,
                "environment_override_allowed": False,
                "runtime_override_allowed": False,
                "caller_override_allowed": False,
            },
            "profile": {
                "schema": PROFILE_SCHEMA,
                "profile_id": profile_id,
                "profile_payload_sha256": profile_payload_sha256,
            },
            "stable_root_evidence": {
                "schema": STABLE_SCHEMA,
                "evidence_payload_sha256": stable["evidence_payload_sha256"],
            },
            "protected_production_ingress": ingress_ref,
            "scope": {
                "operation_version": OPERATION_VERSION,
                "operation": OPERATION,
                "maximum_receipt_age_seconds": str(
                    maximum_receipt_age_seconds
                ),
                "authorization_scope_sha256": "",
            },
            "authority": copy.deepcopy(AUTHORITY),
            "authorization_payload_sha256": "",
        }
        document["scope"]["authorization_scope_sha256"] = digest(
            _authorization_scope_projection(document)
        )
        return validate_legacy_root_authority_authorization(
            _finalize(document, "authorization_payload_sha256")
        )

    def issue_fresh_capability_once(
        self,
        *,
        stable_evidence: LegacyStableRootIdentityEvidence,
        authorization: dict[str, Any],
        protected_production_ingress: object,
        observation: _WorkspaceObservation,
    ) -> SingleUseLegacyWorkspaceDescriptorCapability:
        with self._lock:
            if self._fresh_used:
                raise LegacyRootAuthorityError(
                    "legacy root owner fresh issuance is single-use"
                )
            _assert_bindings_current()
            _require(
                type(stable_evidence) is _ISSUED_TYPES[
                    "LegacyStableRootIdentityEvidence"
                ]
                and type(protected_production_ingress)
                is _INGRESS_BINDING.sealed_type
                and type(observation) is _WorkspaceObservation,
                "legacy fresh issuance exact types differ",
            )
            stable_evidence.assert_current()
            protected_production_ingress.assert_current()
            observation.assert_current()
            now = self._clock()
            validated_authorization = validate_legacy_root_authority_authorization(
                authorization,
                now=now,
            )
            stable = stable_evidence.document()
            ingress = protected_production_ingress.document()
            ingress_ref = validated_authorization["protected_production_ingress"]
            _require(
                ingress["contract_id"] == ingress_ref["contract_id"]
                and ingress["contract_payload_sha256"]
                == ingress_ref["contract_payload_sha256"]
                and ingress["identity"]["project"] == ingress_ref["project"]
                and ingress["identity"]["attempt_id"] == ingress_ref["attempt_id"]
                and ingress["identity"]["input_sha256"]
                == ingress_ref["input_sha256"]
                and stable["evidence_payload_sha256"]
                == validated_authorization["stable_root_evidence"][
                    "evidence_payload_sha256"
                ],
                "legacy fresh issuance predecessor replay differs",
            )
            identity = ingress["identity"]
            _require(
                observation.project == identity["project"],
                "legacy fresh observation project drifted",
            )
            _require(
                observation.root.identity_chain_sha256
                == stable["expected_root_identity"]["identity_chain_sha256"],
                "legacy fresh observation root identity drifted",
            )
            _require(
                observation.fresh_project
                and observation.containment_verified
                and not observation.symlink_detected
                and not observation.reparse_point_detected
                and not observation.root_escape_detected,
                "legacy fresh observation safety checks failed",
            )
            nonce = self._nonce_source()
            _text(nonce, "legacy fresh nonce", NONCE_RE)
            age_text = validated_authorization["scope"][
                "maximum_receipt_age_seconds"
            ]
            age = _positive_decimal(
                age_text,
                "legacy fresh maximum age",
                maximum=300,
            )
            receipt_document = {
                "schema": RECEIPT_SCHEMA,
                "profile": {
                    "profile_id": validated_authorization["profile"]["profile_id"],
                    "profile_payload_sha256": validated_authorization["profile"][
                        "profile_payload_sha256"
                    ],
                },
                "stable_root_evidence": {
                    "evidence_payload_sha256": stable["evidence_payload_sha256"],
                    "expected_identity_chain_sha256": stable[
                        "expected_root_identity"
                    ]["identity_chain_sha256"],
                },
                "authorization": {
                    "authorization_id": validated_authorization[
                        "authorization_id"
                    ],
                    "authorization_payload_sha256": validated_authorization[
                        "authorization_payload_sha256"
                    ],
                    "authorization_scope_sha256": validated_authorization[
                        "scope"
                    ]["authorization_scope_sha256"],
                },
                "protected_production_ingress": copy.deepcopy(ingress_ref),
                "operation": {
                    "operation_version": OPERATION_VERSION,
                    "operation": OPERATION,
                    "project": identity["project"],
                    "attempt_id": identity["attempt_id"],
                    "input_sha256": identity["input_sha256"],
                    "nonce": nonce,
                },
                "window": {
                    "observed_at": _format_utc(now),
                    "expires_at": _format_utc(now + timedelta(seconds=age)),
                    "maximum_receipt_age_seconds": age_text,
                },
                "observed_root": {
                    "identity": observation.root.document(),
                    "project": observation.project,
                    "remote_workdir": observation.remote_workdir,
                    "scratch_workdir": observation.scratch_workdir,
                    "workspace_binding_sha256": observation.workspace_binding_sha256,
                    "descriptor_set_sha256": observation.descriptor_set.descriptor_set_sha256,
                    "fresh_project": True,
                    "containment_verified": True,
                    "symlink_detected": False,
                    "reparse_point_detected": False,
                    "root_escape_detected": False,
                },
                "comparison": {
                    "profile_matches": True,
                    "stable_evidence_matches": True,
                    "authorization_scope_matches": True,
                    "production_ingress_matches": True,
                    "root_identity_matches": True,
                    "workspace_matches": True,
                    "classification": "verified",
                },
                "authority": copy.deepcopy(AUTHORITY),
                "receipt_payload_sha256": "",
            }
            validated_receipt = validate_legacy_fresh_root_observation_receipt(
                _finalize(receipt_document, "receipt_payload_sha256"),
                now=now,
            )
            receipt = LegacyFreshRootObservationReceipt._from_owner(
                validated_receipt,
                token=_SEAL_TOKEN,
            )
            capability = SingleUseLegacyWorkspaceDescriptorCapability._from_owner(
                ingress=protected_production_ingress,
                evidence=stable_evidence,
                authorization=validated_authorization,
                receipt=receipt,
                descriptor_set=observation.descriptor_set,
                clock=self._clock,
                token=_CAPABILITY_TOKEN,
            )
            capability.assert_current()
            self._fresh_used = True
            return capability


_ISSUED_TYPE_NAMES = (
    "LegacyStableRootIdentityEvidence",
    "LegacyFreshRootObservationReceipt",
    "ConsumedLegacyWorkspaceDescriptorLease",
    "SingleUseLegacyWorkspaceDescriptorCapability",
    "LegacyRootAuthorityContractOwner",
)
_ISSUED_TYPES = {name: getattr(_OWNER_MODULE, name) for name in _ISSUED_TYPE_NAMES}
for _name, _type in _ISSUED_TYPES.items():
    if (
        not isinstance(_type, type)
        or _type.__module__ != MODULE_NAME
        or _type.__qualname__ != _name
    ):
        raise ImportError(f"legacy root owner class identity differs: {_name}")
_assert_bindings_current()
