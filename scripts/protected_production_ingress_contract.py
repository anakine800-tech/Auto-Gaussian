#!/usr/bin/env python3
"""Seal one effect-free production-ingress and legacy factory-port capability.

The sole public input is the exact owner-issued protected owner-consumer
contract.  This owner replays that contract, claims its already sealed
effect-plan inputs once, snapshots only those owner-derived values, and issues
one non-executable production-ingress capability.  The capability may expose
one non-executable legacy sole-owner factory port.

This module never reads caller paths or configuration, stages bytes, reserves
state, writes a receipt, constructs a legacy transaction/effect plan or raw
owner, invokes a factory, adapter or runner, opens a connection, transfers
bytes, submits, reconciles, retries, cancels, cleans up, deletes, migrates,
rehashes, or backfills any predecessor.
"""

from __future__ import annotations

try:
    _AUTO_G16_PRODUCTION_INGRESS_EXECUTION_GUARD
except NameError:
    _AUTO_G16_PRODUCTION_INGRESS_EXECUTION_GUARD = object()
else:
    raise ImportError("production ingress owner module has already executed")

import hashlib
import json
import math
import os
import re
import stat
import sys
import threading
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SCHEMA = "auto-g16-protected-production-ingress-contract/1"
OWNER = "auto-g16-protected-production-ingress-owner"
MODULE_NAME = "protected_production_ingress_contract"
CONSUMER_MODULE_NAME = "protected_owner_consumer_contract"
FACADE_MODULE_NAME = "execution_facade"
LEGACY_MODULE_NAME = "legacy_rtwin_pbs"
CONSUMER_SCHEMA = "auto-g16-protected-owner-consumer-contract/1"
RUNTIME_RECEIPT_SCHEMA = "auto-g16-protected-runtime-state-receipt/1"
FIXED_REMOTE_ROOT = "/home/user100/SDL"
PLAN_FIELDS = (
    "project",
    "windows_dir",
    "remote_dir",
    "files",
    "expected_bindings",
    "upload_timeout_seconds",
    "upload_hash_timeout_seconds",
    "attempt_id",
    "input_sha256",
    "mac_ssh_config",
    "rtwin_alias",
    "windows_server_config",
    "server_alias",
)
EFFECT_STEPS = (
    "windows_directory_claim",
    "mac_to_windows_copy",
    "windows_sha256",
    "server_directory_claim",
    "windows_to_server_copy",
    "qsub_once",
)
CALL_CHAIN = (
    "production_submit_receives_owner_issued_ingress_capability",
    "ingress_replays_exact_predecessor_and_uncertain_receipt",
    "legacy_module_consumes_exact_factory_port_once",
    "legacy_module_constructs_one_effect_plan_as_sole_owner",
    "legacy_module_claims_one_raw_effect_owner",
    "legacy_module_enters_one_bounded_effect_lifecycle",
)
VALIDATION = {
    "draft_schema_structural_only": True,
    "public_validator_semantic_projection": True,
    "owner_replay_required": True,
    "in_process_seal_required": True,
    "schema_valid_is_sealed": False,
}
SCOPE = {
    "consume_exact_owner_consumer_capability": True,
    "claim_exact_plan_inputs_once": True,
    "issue_production_ingress_capability": True,
    "issue_legacy_factory_port": True,
    "read_caller_paths": False,
    "read_caller_runtime_config": False,
    "stage": False,
    "reserve": False,
    "write": False,
    "consume_runtime_state": False,
    "construct_legacy_transaction_plan": False,
    "construct_legacy_effect_plan": False,
    "construct_raw_effect_owner": False,
    "invoke_legacy_factory": False,
    "invoke_adapter": False,
    "invoke_runner": False,
    "transfer": False,
    "submit": False,
    "remote_read": False,
    "retry": False,
    "cancel": False,
    "cleanup": False,
    "delete": False,
}
POLICY = {
    "single_owner_use": True,
    "single_factory_port_claim": True,
    "snapshot_isolation": True,
    "pre_call_canonical_cache_replacement_rejected": True,
    "post_check_direct_sys_modules_mutation_protected": False,
    "uncertain_receipt_required_before_ingress": True,
    "predecessor_bytes_unchanged": True,
    "legacy_source_bytes_unchanged": True,
    "raw_effect_owner_unchanged": True,
    "automatic_retry": False,
    "automatic_cancel": False,
    "automatic_cleanup": False,
    "automatic_delete": False,
    "automatic_rollback": False,
    "historical_migration": False,
}
THREAT_MODEL = {
    "foreign_identical_module_rejected": True,
    "foreign_identical_class_rejected": True,
    "wrong_import_order_rejected": True,
    "pre_call_source_drift_rejected": True,
    "pre_call_cache_replacement_zero_claim": True,
    "post_check_arbitrary_same_process_mutation_prevented": False,
    "process_isolation_required_for_post_check_attacker": True,
}

SHA_RE = re.compile(r"^[a-f0-9]{64}$")
PROJECT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,14}$")
ATTEMPT_RE = re.compile(r"^qsub-attempt-[a-f0-9]{64}$")
CONSUMER_ID_RE = re.compile(r"^protected-owner-consumer-[a-f0-9]{64}$")
INTENT_ID_RE = re.compile(r"^protected-owner-intent-[a-f0-9]{64}$")
RECEIPT_ID_RE = re.compile(r"^protected-runtime-receipt-[a-f0-9]{64}$")
INGRESS_ID_RE = re.compile(r"^protected-production-ingress-[a-f0-9]{64}$")
_ZERO_SHA = "0" * 64
_MAX_JSON_DEPTH = 64
_MAX_SOURCE_BYTES = 4 * 1024 * 1024
_SOURCE_CHUNK = 64 * 1024
_OWNER_TOKEN = object()
_INGRESS_TOKEN = object()
_PORT_TOKEN = object()
_MISSING = object()
_REGISTRATION_ATTRIBUTE = (
    "_auto_g16_protected_production_ingress_registration_v1"
)


class ProtectedProductionIngressError(ValueError):
    """The non-executable production ingress cannot be proved safely."""


def canonical_bytes(value: Any) -> bytes:
    try:
        return (
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ProtectedProductionIngressError(
            f"production ingress value is not canonical JSON: {exc}"
        ) from exc


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _rebuild_public_json(
    value: object,
    *,
    depth: int = 0,
    active: set[int] | None = None,
) -> Any:
    if depth > _MAX_JSON_DEPTH:
        raise ProtectedProductionIngressError(
            "production ingress document exceeds the nesting bound"
        )
    if type(value) in {str, int, bool} or value is None:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ProtectedProductionIngressError(
                "production ingress document contains a non-finite number"
            )
        return value
    if type(value) not in {dict, list}:
        raise ProtectedProductionIngressError(
            "production ingress accepts only exact builtin JSON"
        )
    if active is None:
        active = set()
    identity = id(value)
    if identity in active:
        raise ProtectedProductionIngressError(
            "production ingress document contains a cycle"
        )
    active.add(identity)
    try:
        if type(value) is list:
            first = list(value)
            rebuilt = [
                _rebuild_public_json(item, depth=depth + 1, active=active)
                for item in first
            ]
            if list(value) != first:
                raise ProtectedProductionIngressError(
                    "production ingress list changed during validation"
                )
            return rebuilt
        first_items = list(value.items())
        if any(type(key) is not str for key, _item in first_items):
            raise ProtectedProductionIngressError(
                "production ingress object keys must be strings"
            )
        rebuilt_dict = {
            key: _rebuild_public_json(
                item,
                depth=depth + 1,
                active=active,
            )
            for key, item in first_items
        }
        if list(value.items()) != first_items:
            raise ProtectedProductionIngressError(
                "production ingress object changed during validation"
            )
        return rebuilt_dict
    finally:
        active.remove(identity)


def _exact(value: object, fields: set[str], label: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != fields:
        raise ProtectedProductionIngressError(f"{label} topology differs")
    return value


def _sha(value: object, label: str, *, nonzero: bool = True) -> str:
    if (
        type(value) is not str
        or SHA_RE.fullmatch(value) is None
        or (nonzero and value == _ZERO_SHA)
    ):
        raise ProtectedProductionIngressError(
            f"{label} is not an exact SHA-256"
        )
    return value


def _integer(value: object, label: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ProtectedProductionIngressError(
            f"{label} is not an exact integer"
        )
    return value


def _fixed(value: object, expected: dict[str, bool], label: str) -> None:
    item = _exact(value, set(expected), label)
    if any(
        type(item[key]) is not bool or item[key] is not expected[key]
        for key in expected
    ):
        raise ProtectedProductionIngressError(f"{label} differs")


def _payload_sha256(document: dict[str, Any]) -> str:
    projection = dict(document)
    projection["contract_id"] = ""
    projection["contract_payload_sha256"] = ""
    return digest(projection)


def validate_protected_production_ingress_contract(
    value: object,
) -> dict[str, Any]:
    document = _rebuild_public_json(value)
    document = _exact(
        document,
        {
            "schema",
            "owner",
            "contract_id",
            "predecessor",
            "identity",
            "production_ingress",
            "legacy_factory_port",
            "call_chain",
            "owner_bindings",
            "validation",
            "scope",
            "policy",
            "threat_model",
            "contract_payload_sha256",
        },
        "production ingress contract",
    )
    if document["schema"] != SCHEMA or document["owner"] != OWNER:
        raise ProtectedProductionIngressError(
            "production ingress schema or owner differs"
        )
    if (
        type(document["contract_id"]) is not str
        or INGRESS_ID_RE.fullmatch(document["contract_id"]) is None
    ):
        raise ProtectedProductionIngressError(
            "production ingress id differs"
        )
    predecessor = _exact(
        document["predecessor"],
        {
            "schema",
            "contract_id",
            "contract_payload_sha256",
            "intent_id",
            "intent_file_sha256",
            "checksum_file_sha256",
            "expected_bindings_sha256",
            "uncertain_receipt_schema",
            "uncertain_receipt_id",
            "uncertain_receipt_payload_sha256",
            "uncertain_state",
        },
        "production ingress predecessor",
    )
    if (
        predecessor["schema"] != CONSUMER_SCHEMA
        or type(predecessor["contract_id"]) is not str
        or CONSUMER_ID_RE.fullmatch(predecessor["contract_id"]) is None
        or type(predecessor["intent_id"]) is not str
        or INTENT_ID_RE.fullmatch(predecessor["intent_id"]) is None
        or predecessor["uncertain_receipt_schema"]
        != RUNTIME_RECEIPT_SCHEMA
        or type(predecessor["uncertain_receipt_id"]) is not str
        or RECEIPT_ID_RE.fullmatch(predecessor["uncertain_receipt_id"])
        is None
        or predecessor["uncertain_state"]
        != "effect_started_outcome_uncertain"
    ):
        raise ProtectedProductionIngressError(
            "production ingress predecessor differs"
        )
    for field in (
        "contract_payload_sha256",
        "intent_file_sha256",
        "checksum_file_sha256",
        "expected_bindings_sha256",
        "uncertain_receipt_payload_sha256",
    ):
        _sha(predecessor[field], f"predecessor {field}")
    identity = _exact(
        document["identity"],
        {"project", "attempt_id", "input_sha256"},
        "production ingress identity",
    )
    if (
        type(identity["project"]) is not str
        or PROJECT_RE.fullmatch(identity["project"]) is None
        or type(identity["attempt_id"]) is not str
        or ATTEMPT_RE.fullmatch(identity["attempt_id"]) is None
    ):
        raise ProtectedProductionIngressError(
            "production ingress identity differs"
        )
    _sha(identity["input_sha256"], "production ingress input")
    ingress = _exact(
        document["production_ingress"],
        {
            "issuer_module",
            "issuer_type",
            "designated_consumer_module",
            "designated_consumer_class",
            "designated_consumer_method",
            "accepted_predecessor_type",
            "accepted_plan_input_type",
            "caller_paths_read",
            "runtime_config_read",
            "staging_repeated",
            "reservation_repeated",
            "runtime_consumption_repeated",
            "production_submit_wired",
        },
        "production ingress",
    )
    if ingress != {
        "issuer_module": MODULE_NAME,
        "issuer_type": "SealedProtectedProductionIngressCapability",
        "designated_consumer_module": FACADE_MODULE_NAME,
        "designated_consumer_class": "LegacyCLICompatibilityAdapter",
        "designated_consumer_method": "_submit_new",
        "accepted_predecessor_type": "SealedProtectedOwnerConsumerContract",
        "accepted_plan_input_type": "ProtectedLegacyEffectPlanInputs",
        "caller_paths_read": False,
        "runtime_config_read": False,
        "staging_repeated": False,
        "reservation_repeated": False,
        "runtime_consumption_repeated": False,
        "production_submit_wired": False,
    }:
        raise ProtectedProductionIngressError(
            "production ingress boundary differs"
        )
    port = _exact(
        document["legacy_factory_port"],
        {
            "issuer_module",
            "issuer_type",
            "designated_consumer_module",
            "sole_factory",
            "legacy_transaction_type",
            "legacy_plan_type",
            "legacy_raw_owner_type",
            "required_fields",
            "effect_steps",
            "plan_inputs",
            "plan_inputs_sha256",
            "current_factory_requires_cli_transaction",
            "current_factory_accepts_port",
            "factory_invoked",
            "effect_plan_created",
            "raw_effect_owner_created",
        },
        "legacy factory port",
    )
    if (
        port["issuer_module"] != MODULE_NAME
        or port["issuer_type"] != "ProtectedLegacyEffectPlanFactoryPort"
        or port["designated_consumer_module"] != LEGACY_MODULE_NAME
        or port["sole_factory"] != "_legacy_effect_plan_from_transaction"
        or port["legacy_transaction_type"] != "_LegacyTransactionPlan"
        or port["legacy_plan_type"] != "_LegacyEffectPlan"
        or port["legacy_raw_owner_type"] != "_LegacyRawEffectOwner"
        or port["required_fields"] != list(PLAN_FIELDS)
        or port["effect_steps"] != list(EFFECT_STEPS)
        or port["current_factory_requires_cli_transaction"] is not True
        or port["current_factory_accepts_port"] is not False
        or port["factory_invoked"] is not False
        or port["effect_plan_created"] is not False
        or port["raw_effect_owner_created"] is not False
    ):
        raise ProtectedProductionIngressError(
            "legacy factory port boundary differs"
        )
    plan = _exact(
        port["plan_inputs"],
        {
            "project",
            "windows_directory_sha256",
            "remote_directory",
            "files",
            "expected_bindings",
            "upload_timeout_seconds",
            "upload_hash_timeout_seconds",
            "attempt_id",
            "input_sha256",
            "mac_ssh_config_sha256",
            "rtwin_alias_sha256",
            "windows_server_config_sha256",
            "server_alias_sha256",
        },
        "legacy factory plan inputs",
    )
    if (
        plan["project"] != identity["project"]
        or plan["remote_directory"]
        != f"{FIXED_REMOTE_ROOT}/{identity['project']}"
        or plan["attempt_id"] != identity["attempt_id"]
        or plan["input_sha256"] != identity["input_sha256"]
        or type(plan["files"]) is not list
        or not plan["files"]
        or type(plan["expected_bindings"]) is not list
        or len(plan["files"]) != len(plan["expected_bindings"])
    ):
        raise ProtectedProductionIngressError(
            "legacy factory plan identity differs"
        )
    for index, binding in enumerate(plan["expected_bindings"]):
        item = _exact(
            binding,
            {"relative_name", "sha256", "order"},
            f"legacy factory binding {index}",
        )
        if (
            type(item["relative_name"]) is not str
            or not item["relative_name"]
            or item["order"] != index + 1
            or plan["files"][index] != item["relative_name"]
        ):
            raise ProtectedProductionIngressError(
                "legacy factory binding order differs"
            )
        _sha(item["sha256"], "legacy factory binding")
    if len(set(plan["files"])) != len(plan["files"]):
        raise ProtectedProductionIngressError(
            "legacy factory files are duplicated"
        )
    for field in (
        "windows_directory_sha256",
        "mac_ssh_config_sha256",
        "rtwin_alias_sha256",
        "windows_server_config_sha256",
        "server_alias_sha256",
    ):
        _sha(plan[field], f"legacy factory {field}")
    _integer(plan["upload_timeout_seconds"], "legacy upload timeout", 1)
    _integer(
        plan["upload_hash_timeout_seconds"],
        "legacy upload hash timeout",
        1,
    )
    expected_plan_sha = digest(plan)
    if port["plan_inputs_sha256"] != expected_plan_sha:
        raise ProtectedProductionIngressError(
            "legacy factory plan inputs hash differs"
        )
    call_chain = _exact(
        document["call_chain"],
        {
            "required_order",
            "implemented_through",
            "remaining_gate",
            "effects_performed",
        },
        "production call chain",
    )
    if call_chain != {
        "required_order": list(CALL_CHAIN),
        "implemented_through": (
            "production_ingress_and_factory_port_issued_effect_free"
        ),
        "remaining_gate": (
            "exact_legacy_internal_port_consumer_and_production_wiring"
        ),
        "effects_performed": False,
    }:
        raise ProtectedProductionIngressError(
            "production call chain differs"
        )
    bindings = _exact(
        document["owner_bindings"],
        {
            "ingress_owner_source_sha256",
            "owner_consumer_source_sha256",
            "facade_source_sha256",
            "legacy_source_sha256",
        },
        "production ingress owner bindings",
    )
    for field in bindings:
        _sha(bindings[field], f"owner binding {field}")
    _fixed(document["validation"], VALIDATION, "validation")
    _fixed(document["scope"], SCOPE, "scope")
    _fixed(document["policy"], POLICY, "policy")
    _fixed(document["threat_model"], THREAT_MODEL, "threat model")
    expected_payload = _payload_sha256(document)
    if document["contract_payload_sha256"] != expected_payload:
        raise ProtectedProductionIngressError(
            "production ingress payload differs"
        )
    expected_id = "protected-production-ingress-" + digest(
        {
            "schema": "auto-g16-protected-production-ingress-id/1",
            "predecessor_contract_id": predecessor["contract_id"],
            "uncertain_receipt_payload_sha256": predecessor[
                "uncertain_receipt_payload_sha256"
            ],
            "plan_inputs_sha256": port["plan_inputs_sha256"],
            "contract_payload_sha256": expected_payload,
        }
    )
    if document["contract_id"] != expected_id:
        raise ProtectedProductionIngressError(
            "production ingress contract id differs"
        )
    return document


@dataclass(frozen=True, slots=True)
class _SourceSnapshot:
    path: Path
    identity: tuple[int, ...]
    sha256: str
    source_bytes: bytes


@dataclass(frozen=True, slots=True)
class _ConsumerBinding:
    module: types.ModuleType
    sealed_type: type
    plan_input_type: type
    source: _SourceSnapshot


@dataclass(frozen=True, slots=True)
class _FacadeBinding:
    module: types.ModuleType
    adapter_type: type
    submit_method: types.FunctionType
    source: _SourceSnapshot


@dataclass(frozen=True, slots=True)
class _LegacyBinding:
    module: types.ModuleType
    transaction_type: type
    plan_type: type
    raw_owner_type: type
    plan_factory: types.FunctionType
    raw_owner_factory: types.FunctionType
    source: _SourceSnapshot


def _stat_identity(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_uid,
        info.st_mode,
        info.st_nlink,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _stable_source(path: Path) -> _SourceSnapshot:
    descriptor = -1
    try:
        before = os.stat(path, follow_symlinks=False)
        if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
            raise ProtectedProductionIngressError(
                "bound owner source must be a regular file"
            )
        descriptor = os.open(
            path,
            os.O_RDONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
        )
        opened = os.fstat(descriptor)
        if _stat_identity(opened) != _stat_identity(before):
            raise ProtectedProductionIngressError(
                "bound owner source changed while opening"
            )
        if opened.st_size < 1 or opened.st_size > _MAX_SOURCE_BYTES:
            raise ProtectedProductionIngressError(
                "bound owner source size is outside the limit"
            )
        chunks = []
        while True:
            chunk = os.read(descriptor, _SOURCE_CHUNK)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(descriptor)
        path_after = os.stat(path, follow_symlinks=False)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if len(
        {
            _stat_identity(before),
            _stat_identity(opened),
            _stat_identity(after),
            _stat_identity(path_after),
        }
    ) != 1:
        raise ProtectedProductionIngressError(
            "bound owner source identity drifted"
        )
    raw = b"".join(chunks)
    if len(raw) != opened.st_size:
        raise ProtectedProductionIngressError(
            "bound owner source stable read was short"
        )
    return _SourceSnapshot(
        path.resolve(strict=True),
        _stat_identity(opened),
        hashlib.sha256(raw).hexdigest(),
        raw,
    )


def _module_origin(module: types.ModuleType) -> tuple[Path, Path]:
    raw_file = getattr(module, "__file__", None)
    raw_origin = getattr(getattr(module, "__spec__", None), "origin", None)
    if type(raw_file) is not str or type(raw_origin) is not str:
        raise ImportError("bound production ingress module has no exact origin")
    return Path(raw_file).resolve(), Path(raw_origin).resolve()


def _owner_path() -> Path:
    path = Path(__file__).resolve(strict=True)
    if path.is_symlink() or not path.is_file():
        raise ImportError("production ingress owner is unavailable")
    return path


def _repository_or_adjacent(name: str, *, legacy_layout: bool = False) -> Path:
    here = _owner_path()
    adjacent = here.with_name(f"{name}.py")
    if (
        not adjacent.is_symlink()
        and adjacent.is_file()
        and adjacent.resolve().parent == here.parent
    ):
        return adjacent.resolve(strict=True)
    if legacy_layout:
        repository = (
            here.parent.parent
            / "skills"
            / "auto-g16-rtwin-pbs"
            / "scripts"
            / f"{name}.py"
        )
        if not repository.is_symlink() and repository.is_file():
            return repository.resolve(strict=True)
    raise ImportError(f"exact {name} owner is unavailable")


def _capture_consumer_binding() -> _ConsumerBinding:
    path = _repository_or_adjacent(CONSUMER_MODULE_NAME)
    source = _stable_source(path)
    module = sys.modules.get(CONSUMER_MODULE_NAME)
    if not isinstance(module, types.ModuleType) or _module_origin(module) != (
        path,
        path,
    ):
        raise ImportError("exact owner-consumer module must load first")
    sealed_type = getattr(
        module,
        "SealedProtectedOwnerConsumerContract",
        None,
    )
    plan_input_type = getattr(
        module,
        "ProtectedLegacyEffectPlanInputs",
        None,
    )
    if not isinstance(sealed_type, type) or not isinstance(plan_input_type, type):
        raise ImportError("owner-consumer class identity differs")
    return _ConsumerBinding(
        module,
        sealed_type,
        plan_input_type,
        source,
    )


def _capture_facade_binding() -> _FacadeBinding:
    path = _repository_or_adjacent(FACADE_MODULE_NAME, legacy_layout=True)
    source = _stable_source(path)
    module = sys.modules.get(FACADE_MODULE_NAME)
    if not isinstance(module, types.ModuleType) or _module_origin(module) != (
        path,
        path,
    ):
        raise ImportError("exact execution facade must load first")
    adapter_type = getattr(module, "LegacyCLICompatibilityAdapter", None)
    submit_method = getattr(adapter_type, "_submit_new", None)
    if (
        not isinstance(adapter_type, type)
        or not isinstance(submit_method, types.FunctionType)
    ):
        raise ImportError("production submit ingress identity differs")
    return _FacadeBinding(
        module,
        adapter_type,
        submit_method,
        source,
    )


def _capture_legacy_binding() -> _LegacyBinding:
    path = _repository_or_adjacent(LEGACY_MODULE_NAME, legacy_layout=True)
    source = _stable_source(path)
    module = sys.modules.get(LEGACY_MODULE_NAME)
    if not isinstance(module, types.ModuleType) or _module_origin(module) != (
        path,
        path,
    ):
        raise ImportError("exact legacy module must load first")
    transaction_type = getattr(module, "_LegacyTransactionPlan", None)
    plan_type = getattr(module, "_LegacyEffectPlan", None)
    raw_owner_type = getattr(module, "_LegacyRawEffectOwner", None)
    plan_factory = getattr(
        module,
        "_legacy_effect_plan_from_transaction",
        None,
    )
    raw_owner_factory = getattr(
        module,
        "_legacy_raw_effect_owner_from_plan",
        None,
    )
    if (
        not isinstance(transaction_type, type)
        or not isinstance(plan_type, type)
        or not isinstance(raw_owner_type, type)
        or not isinstance(plan_factory, types.FunctionType)
        or not isinstance(raw_owner_factory, types.FunctionType)
        or tuple(getattr(plan_type, "__slots__", ()))
        != (*PLAN_FIELDS, "_factory_state", "_owner_seal")
    ):
        raise ImportError("legacy sole-owner factory identity differs")
    return _LegacyBinding(
        module,
        transaction_type,
        plan_type,
        raw_owner_type,
        plan_factory,
        raw_owner_factory,
        source,
    )


def _register_owner(consumer: _ConsumerBinding) -> None:
    if (
        __name__ != MODULE_NAME
        or sys.modules.get(MODULE_NAME) is not sys.modules.get(__name__)
    ):
        raise ImportError(
            "production ingress owner must load under its canonical name"
        )
    current = sys.modules[MODULE_NAME]
    existing = vars(consumer.module).get(_REGISTRATION_ATTRIBUTE, _MISSING)
    if existing is not _MISSING and existing is not current:
        raise ImportError("production ingress owner is already registered")
    setattr(consumer.module, _REGISTRATION_ATTRIBUTE, current)


_OWNER_SOURCE = _stable_source(_owner_path())
_CONSUMER_BINDING = _capture_consumer_binding()
_FACADE_BINDING = _capture_facade_binding()
_LEGACY_BINDING = _capture_legacy_binding()
_register_owner(_CONSUMER_BINDING)
_OWNER_MODULE = sys.modules[MODULE_NAME]


def _assert_bindings_current() -> None:
    if (
        sys.modules.get(MODULE_NAME) is not _OWNER_MODULE
        or vars(_CONSUMER_BINDING.module).get(_REGISTRATION_ATTRIBUTE)
        is not _OWNER_MODULE
        or sys.modules.get(CONSUMER_MODULE_NAME)
        is not _CONSUMER_BINDING.module
        or sys.modules.get(FACADE_MODULE_NAME) is not _FACADE_BINDING.module
        or sys.modules.get(LEGACY_MODULE_NAME) is not _LEGACY_BINDING.module
        or _stable_source(_owner_path()) != _OWNER_SOURCE
        or _stable_source(_repository_or_adjacent(CONSUMER_MODULE_NAME))
        != _CONSUMER_BINDING.source
        or _stable_source(
            _repository_or_adjacent(FACADE_MODULE_NAME, legacy_layout=True)
        )
        != _FACADE_BINDING.source
        or _stable_source(
            _repository_or_adjacent(LEGACY_MODULE_NAME, legacy_layout=True)
        )
        != _LEGACY_BINDING.source
        or getattr(
            _CONSUMER_BINDING.module,
            "SealedProtectedOwnerConsumerContract",
            None,
        )
        is not _CONSUMER_BINDING.sealed_type
        or getattr(
            _CONSUMER_BINDING.module,
            "ProtectedLegacyEffectPlanInputs",
            None,
        )
        is not _CONSUMER_BINDING.plan_input_type
        or getattr(
            _FACADE_BINDING.module,
            "LegacyCLICompatibilityAdapter",
            None,
        )
        is not _FACADE_BINDING.adapter_type
        or getattr(
            _FACADE_BINDING.adapter_type,
            "_submit_new",
            None,
        )
        is not _FACADE_BINDING.submit_method
        or getattr(_LEGACY_BINDING.module, "_LegacyTransactionPlan", None)
        is not _LEGACY_BINDING.transaction_type
        or getattr(_LEGACY_BINDING.module, "_LegacyEffectPlan", None)
        is not _LEGACY_BINDING.plan_type
        or getattr(_LEGACY_BINDING.module, "_LegacyRawEffectOwner", None)
        is not _LEGACY_BINDING.raw_owner_type
        or getattr(
            _LEGACY_BINDING.module,
            "_legacy_effect_plan_from_transaction",
            None,
        )
        is not _LEGACY_BINDING.plan_factory
        or getattr(
            _LEGACY_BINDING.module,
            "_legacy_raw_effect_owner_from_plan",
            None,
        )
        is not _LEGACY_BINDING.raw_owner_factory
        or getattr(
            _OWNER_MODULE,
            "ProtectedProductionIngressContractOwner",
            None,
        )
        is not _INGRESS_OWNER_TYPE
        or getattr(
            _OWNER_MODULE,
            "SealedProtectedProductionIngressCapability",
            None,
        )
        is not _INGRESS_CAPABILITY_TYPE
        or getattr(
            _OWNER_MODULE,
            "ProtectedLegacyEffectPlanFactoryPort",
            None,
        )
        is not _INGRESS_PORT_TYPE
    ):
        raise ProtectedProductionIngressError(
            "production ingress module, source, class or callable identity differs"
        )


def _plan_snapshot(values: object) -> tuple[Any, ...]:
    if type(values) is not _CONSUMER_BINDING.plan_input_type:
        raise TypeError(
            "production ingress accepts only exact owner-issued plan inputs"
        )
    values.assert_owner_sealed()
    project = values.project
    windows_dir = values.windows_dir
    remote_dir = values.remote_dir
    files = values.files
    expected = values.expected_bindings
    if (
        type(project) is not str
        or type(windows_dir) is not str
        or type(remote_dir) is not str
        or type(files) is not tuple
        or not files
        or not all(isinstance(path, Path) for path in files)
        or type(expected) is not tuple
        or len(files) != len(expected)
        or not all(
            type(item) is tuple
            and len(item) == 2
            and type(item[0]) is str
            and type(item[1]) is str
            and SHA_RE.fullmatch(item[1]) is not None
            for item in expected
        )
        or tuple(path.name for path in files)
        != tuple(item[0] for item in expected)
    ):
        raise ProtectedProductionIngressError(
            "owner-issued plan inputs differ"
        )
    scalar_names = (
        "upload_timeout_seconds",
        "upload_hash_timeout_seconds",
    )
    if any(
        type(getattr(values, name)) is not int
        or getattr(values, name) < 1
        for name in scalar_names
    ):
        raise ProtectedProductionIngressError(
            "owner-issued plan timeout differs"
        )
    for name in (
        "attempt_id",
        "input_sha256",
        "mac_ssh_config",
        "rtwin_alias",
        "windows_server_config",
        "server_alias",
    ):
        if type(getattr(values, name)) is not str:
            raise ProtectedProductionIngressError(
                "owner-issued plan scalar differs"
            )
    return (
        project,
        windows_dir,
        remote_dir,
        tuple(str(path) for path in files),
        tuple((name, sha256) for name, sha256 in expected),
        values.upload_timeout_seconds,
        values.upload_hash_timeout_seconds,
        values.attempt_id,
        values.input_sha256,
        values.mac_ssh_config,
        values.rtwin_alias,
        values.windows_server_config,
        values.server_alias,
    )


def _plan_document(snapshot: tuple[Any, ...]) -> dict[str, Any]:
    (
        project,
        windows_dir,
        remote_dir,
        files,
        expected,
        upload_timeout,
        hash_timeout,
        attempt_id,
        input_sha256,
        mac_ssh_config,
        rtwin_alias,
        windows_server_config,
        server_alias,
    ) = snapshot
    return {
        "project": project,
        "windows_directory_sha256": digest(windows_dir),
        "remote_directory": remote_dir,
        "files": [Path(path).name for path in files],
        "expected_bindings": [
            {
                "relative_name": name,
                "sha256": sha256,
                "order": index,
            }
            for index, (name, sha256) in enumerate(expected, start=1)
        ],
        "upload_timeout_seconds": upload_timeout,
        "upload_hash_timeout_seconds": hash_timeout,
        "attempt_id": attempt_id,
        "input_sha256": input_sha256,
        "mac_ssh_config_sha256": digest(mac_ssh_config),
        "rtwin_alias_sha256": digest(rtwin_alias),
        "windows_server_config_sha256": digest(windows_server_config),
        "server_alias_sha256": digest(server_alias),
    }


def _snapshot_from_consumer(consumer: object) -> tuple[Any, ...]:
    consumer.assert_current()
    values = getattr(consumer, "_plan_values", None)
    if type(values) is not dict or set(values) != set(PLAN_FIELDS):
        raise ProtectedProductionIngressError(
            "owner-consumer private plan mapping differs"
        )
    proxy = object.__new__(_CONSUMER_BINDING.plan_input_type)
    for name in PLAN_FIELDS:
        object.__setattr__(proxy, name, values[name])
    token = getattr(_CONSUMER_BINDING.module, "_PLAN_INPUT_TOKEN", None)
    object.__setattr__(proxy, "_seal", token)
    return _plan_snapshot(proxy)


def _build_document(
    consumer: object,
    snapshot: tuple[Any, ...],
) -> dict[str, Any]:
    predecessor = consumer.document()
    artifacts = predecessor["upload_bundle"]["artifacts"]
    plan_document = _plan_document(snapshot)
    receipt = consumer.uncertain_receipt.document()
    document: dict[str, Any] = {
        "schema": SCHEMA,
        "owner": OWNER,
        "contract_id": "protected-production-ingress-" + _ZERO_SHA,
        "predecessor": {
            "schema": predecessor["schema"],
            "contract_id": predecessor["contract_id"],
            "contract_payload_sha256": predecessor[
                "contract_payload_sha256"
            ],
            "intent_id": predecessor["intent"]["intent_id"],
            "intent_file_sha256": artifacts[-2]["sha256"],
            "checksum_file_sha256": artifacts[-1]["sha256"],
            "expected_bindings_sha256": predecessor["upload_bundle"][
                "expected_bindings_sha256"
            ],
            "uncertain_receipt_schema": receipt["schema"],
            "uncertain_receipt_id": receipt["receipt_id"],
            "uncertain_receipt_payload_sha256": receipt[
                "receipt_payload_sha256"
            ],
            "uncertain_state": receipt["state"],
        },
        "identity": {
            "project": predecessor["identity"]["project"],
            "attempt_id": predecessor["identity"]["attempt_id"],
            "input_sha256": predecessor["identity"]["input_sha256"],
        },
        "production_ingress": {
            "issuer_module": MODULE_NAME,
            "issuer_type": "SealedProtectedProductionIngressCapability",
            "designated_consumer_module": FACADE_MODULE_NAME,
            "designated_consumer_class": "LegacyCLICompatibilityAdapter",
            "designated_consumer_method": "_submit_new",
            "accepted_predecessor_type": (
                "SealedProtectedOwnerConsumerContract"
            ),
            "accepted_plan_input_type": "ProtectedLegacyEffectPlanInputs",
            "caller_paths_read": False,
            "runtime_config_read": False,
            "staging_repeated": False,
            "reservation_repeated": False,
            "runtime_consumption_repeated": False,
            "production_submit_wired": False,
        },
        "legacy_factory_port": {
            "issuer_module": MODULE_NAME,
            "issuer_type": "ProtectedLegacyEffectPlanFactoryPort",
            "designated_consumer_module": LEGACY_MODULE_NAME,
            "sole_factory": "_legacy_effect_plan_from_transaction",
            "legacy_transaction_type": "_LegacyTransactionPlan",
            "legacy_plan_type": "_LegacyEffectPlan",
            "legacy_raw_owner_type": "_LegacyRawEffectOwner",
            "required_fields": list(PLAN_FIELDS),
            "effect_steps": list(EFFECT_STEPS),
            "plan_inputs": plan_document,
            "plan_inputs_sha256": digest(plan_document),
            "current_factory_requires_cli_transaction": True,
            "current_factory_accepts_port": False,
            "factory_invoked": False,
            "effect_plan_created": False,
            "raw_effect_owner_created": False,
        },
        "call_chain": {
            "required_order": list(CALL_CHAIN),
            "implemented_through": (
                "production_ingress_and_factory_port_issued_effect_free"
            ),
            "remaining_gate": (
                "exact_legacy_internal_port_consumer_and_production_wiring"
            ),
            "effects_performed": False,
        },
        "owner_bindings": {
            "ingress_owner_source_sha256": _OWNER_SOURCE.sha256,
            "owner_consumer_source_sha256": _CONSUMER_BINDING.source.sha256,
            "facade_source_sha256": _FACADE_BINDING.source.sha256,
            "legacy_source_sha256": _LEGACY_BINDING.source.sha256,
        },
        "validation": dict(VALIDATION),
        "scope": dict(SCOPE),
        "policy": dict(POLICY),
        "threat_model": dict(THREAT_MODEL),
        "contract_payload_sha256": "",
    }
    document["contract_payload_sha256"] = _payload_sha256(document)
    document["contract_id"] = "protected-production-ingress-" + digest(
        {
            "schema": "auto-g16-protected-production-ingress-id/1",
            "predecessor_contract_id": predecessor["contract_id"],
            "uncertain_receipt_payload_sha256": receipt[
                "receipt_payload_sha256"
            ],
            "plan_inputs_sha256": document["legacy_factory_port"][
                "plan_inputs_sha256"
            ],
            "contract_payload_sha256": document[
                "contract_payload_sha256"
            ],
        }
    )
    return validate_protected_production_ingress_contract(document)


@dataclass(frozen=True, slots=True, init=False)
class ProtectedLegacyEffectPlanFactoryPort:
    project: str
    windows_dir: str
    remote_dir: str
    files: tuple[str, ...]
    expected_bindings: tuple[tuple[str, str], ...]
    upload_timeout_seconds: int
    upload_hash_timeout_seconds: int
    attempt_id: str
    input_sha256: str
    mac_ssh_config: str
    rtwin_alias: str
    windows_server_config: str
    server_alias: str
    predecessor: object
    _snapshot: tuple[Any, ...]
    _seal: object

    def __new__(
        cls,
        *args: Any,
        **kwargs: Any,
    ) -> "ProtectedLegacyEffectPlanFactoryPort":
        raise TypeError("legacy factory ports are owner-issued only")

    @classmethod
    def _from_owner(
        cls,
        predecessor: object,
        snapshot: tuple[Any, ...],
        *,
        token: object,
    ) -> "ProtectedLegacyEffectPlanFactoryPort":
        _assert_bindings_current()
        if (
            cls is not ProtectedLegacyEffectPlanFactoryPort
            or token is not _PORT_TOKEN
        ):
            raise ProtectedProductionIngressError(
                "legacy factory port seal differs"
            )
        value = object.__new__(cls)
        for name, item in zip(PLAN_FIELDS, snapshot):
            object.__setattr__(value, name, item)
        object.__setattr__(value, "predecessor", predecessor)
        object.__setattr__(value, "_snapshot", tuple(snapshot))
        object.__setattr__(value, "_seal", _PORT_TOKEN)
        return value

    def assert_owner_sealed(
        self,
    ) -> "ProtectedLegacyEffectPlanFactoryPort":
        _assert_bindings_current()
        if (
            type(self) is not ProtectedLegacyEffectPlanFactoryPort
            or self._seal is not _PORT_TOKEN
            or type(self.predecessor)
            is not _CONSUMER_BINDING.sealed_type
        ):
            raise ProtectedProductionIngressError(
                "legacy factory port identity differs"
            )
        current = _snapshot_from_consumer(self.predecessor)
        observed = tuple(getattr(self, name) for name in PLAN_FIELDS)
        if current != self._snapshot or observed != self._snapshot:
            raise ProtectedProductionIngressError(
                "legacy factory port snapshot differs"
            )
        return self

    def __copy__(self) -> "ProtectedLegacyEffectPlanFactoryPort":
        raise TypeError("legacy factory ports are not clonable")

    def __deepcopy__(
        self,
        memo: dict[int, Any],
    ) -> "ProtectedLegacyEffectPlanFactoryPort":
        del memo
        raise TypeError("legacy factory ports are not clonable")

    def __reduce__(self) -> object:
        raise TypeError("legacy factory ports are not serializable")

    def __reduce_ex__(self, protocol: int) -> object:
        del protocol
        raise TypeError("legacy factory ports are not serializable")


@dataclass(frozen=True, slots=True, init=False)
class SealedProtectedProductionIngressCapability:
    _canonical_document: bytes
    predecessor: object
    _snapshot: tuple[Any, ...]
    _claim_lock: threading.Lock
    _claimed: bool
    _seal: object

    def __new__(
        cls,
        *args: Any,
        **kwargs: Any,
    ) -> "SealedProtectedProductionIngressCapability":
        raise TypeError("production ingress capabilities are owner-issued only")

    @classmethod
    def _from_owner(
        cls,
        document: dict[str, Any],
        *,
        predecessor: object,
        snapshot: tuple[Any, ...],
        token: object,
    ) -> "SealedProtectedProductionIngressCapability":
        _assert_bindings_current()
        if (
            cls is not SealedProtectedProductionIngressCapability
            or token is not _INGRESS_TOKEN
        ):
            raise ProtectedProductionIngressError(
                "production ingress seal differs"
            )
        value = object.__new__(cls)
        object.__setattr__(
            value,
            "_canonical_document",
            canonical_bytes(document),
        )
        object.__setattr__(value, "predecessor", predecessor)
        object.__setattr__(value, "_snapshot", tuple(snapshot))
        object.__setattr__(value, "_claim_lock", threading.Lock())
        object.__setattr__(value, "_claimed", False)
        object.__setattr__(value, "_seal", _INGRESS_TOKEN)
        return value

    def document(self) -> dict[str, Any]:
        return json.loads(self._canonical_document)

    def assert_current(
        self,
    ) -> "SealedProtectedProductionIngressCapability":
        _assert_bindings_current()
        if (
            type(self) is not SealedProtectedProductionIngressCapability
            or self._seal is not _INGRESS_TOKEN
            or type(self.predecessor)
            is not _CONSUMER_BINDING.sealed_type
        ):
            raise ProtectedProductionIngressError(
                "production ingress capability identity differs"
            )
        current = _snapshot_from_consumer(self.predecessor)
        if current != self._snapshot:
            raise ProtectedProductionIngressError(
                "production ingress snapshot differs"
            )
        document = validate_protected_production_ingress_contract(
            self.document()
        )
        if (
            canonical_bytes(document) != self._canonical_document
            or document["legacy_factory_port"]["plan_inputs"]
            != _plan_document(current)
        ):
            raise ProtectedProductionIngressError(
                "production ingress projection differs"
            )
        return self

    def claim_legacy_factory_port_once(
        self,
    ) -> ProtectedLegacyEffectPlanFactoryPort:
        with self._claim_lock:
            if self._claimed:
                raise ProtectedProductionIngressError(
                    "legacy factory port has already been claimed"
                )
            self.assert_current()
            object.__setattr__(self, "_claimed", True)
            return ProtectedLegacyEffectPlanFactoryPort._from_owner(
                self.predecessor,
                self._snapshot,
                token=_PORT_TOKEN,
            )

    def __copy__(
        self,
    ) -> "SealedProtectedProductionIngressCapability":
        raise TypeError("production ingress capabilities are not clonable")

    def __deepcopy__(
        self,
        memo: dict[int, Any],
    ) -> "SealedProtectedProductionIngressCapability":
        del memo
        raise TypeError("production ingress capabilities are not clonable")

    def __reduce__(self) -> object:
        raise TypeError("production ingress capabilities are not serializable")

    def __reduce_ex__(self, protocol: int) -> object:
        del protocol
        raise TypeError("production ingress capabilities are not serializable")


class ProtectedProductionIngressContractOwner:
    """Consume one exact predecessor and issue one effect-free ingress."""

    def __init__(self, *, _factory_token: object) -> None:
        _assert_bindings_current()
        if (
            type(self) is not ProtectedProductionIngressContractOwner
            or _factory_token is not _OWNER_TOKEN
        ):
            raise TypeError(
                "production ingress owner requires its fixed factory"
            )
        self._lock = threading.Lock()
        self._used = False

    @classmethod
    def production(cls) -> "ProtectedProductionIngressContractOwner":
        return cls(_factory_token=_OWNER_TOKEN)

    def seal_once(
        self,
        predecessor: object,
    ) -> SealedProtectedProductionIngressCapability:
        with self._lock:
            if self._used:
                raise ProtectedProductionIngressError(
                    "production ingress owner is single-use"
                )
            _assert_bindings_current()
            if type(predecessor) is not _CONSUMER_BINDING.sealed_type:
                raise TypeError(
                    "production ingress accepts only the exact owner-consumer capability"
                )
            predecessor.assert_current()
            self._used = True
            plan_inputs = predecessor.claim_effect_plan_inputs_once()
            if type(plan_inputs) is not _CONSUMER_BINDING.plan_input_type:
                raise ProtectedProductionIngressError(
                    "owner-consumer plan input type differs"
                )
            snapshot = _plan_snapshot(plan_inputs)
            predecessor.assert_current()
            _assert_bindings_current()
            document = _build_document(predecessor, snapshot)
            sealed = SealedProtectedProductionIngressCapability._from_owner(
                document,
                predecessor=predecessor,
                snapshot=snapshot,
                token=_INGRESS_TOKEN,
            )
            sealed.assert_current()
            return sealed


_INGRESS_PORT_TYPE = ProtectedLegacyEffectPlanFactoryPort
_INGRESS_CAPABILITY_TYPE = SealedProtectedProductionIngressCapability
_INGRESS_OWNER_TYPE = ProtectedProductionIngressContractOwner
