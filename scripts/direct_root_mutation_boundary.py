#!/usr/bin/env python3
"""Minimal non-executable consumer of the direct-root owner capability.

This module models one descriptor-relative transaction with opaque synthetic
handles.  It has no path, command, callback, transport, or filesystem API.
The existing ``direct_root_owner_contract`` remains the sole authority for
profile /3, authorization /3, stable evidence, fresh observation and
single-use descriptor consumption.
"""

from __future__ import annotations

import copy
import hashlib
import hmac
import json
import threading
from dataclasses import dataclass
from typing import Any

import direct_root_owner_contract as ROOT


OWNER_ID = "auto-g16-direct-root-mutation-boundary-owner"
BOUNDARY_VERSION = "direct-root-mutation-boundary/1"
BINDING_SCHEMA = "auto-g16-direct-root-synthetic-mutation-binding/1"
RESULT_SCHEMA = "auto-g16-direct-root-synthetic-mutation-result/1"
BACKEND_KIND = "direct_ssh_pbs"

READY = "ready"
DESCRIPTOR_CONSUMPTION_FAILED = "descriptor_consumption_failed"
DESCRIPTOR_CONSUMED_NO_EFFECT_TERMINAL = "descriptor_consumed_no_effect_terminal"
EFFECT_STARTED_OUTCOME_UNCERTAIN = "effect_started_outcome_uncertain"
COMPLETED = "completed"

_OWNER_TOKEN = object()
_HELPER_TOKEN = object()
_TRANSACTION_TOKEN = object()
_TEST_TOKEN = object()


class DirectRootMutationBoundaryError(ValueError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DirectRootMutationBoundaryError(message)


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


def _finalize(document: dict[str, Any], field: str) -> dict[str, Any]:
    result = copy.deepcopy(document)
    result[field] = ""
    result[field] = digest(result)
    return result


def _is_exact_builtin_value(value: Any, expected: Any) -> bool:
    """Compare one closed builtin structure without bool/int equivalence."""
    if type(value) is not type(expected):
        return False
    if type(expected) is dict:
        if len(value) != len(expected):
            return False
        for expected_key, expected_value in expected.items():
            keys = [
                key
                for key in value
                if type(key) is type(expected_key) and key == expected_key
            ]
            if len(keys) != 1 or not _is_exact_builtin_value(
                value[keys[0]],
                expected_value,
            ):
                return False
        return True
    if type(expected) in {list, tuple}:
        return len(value) == len(expected) and all(
            _is_exact_builtin_value(item, expected_item)
            for item, expected_item in zip(value, expected, strict=True)
        )
    return value == expected


@dataclass(frozen=True, slots=True)
class FixedDirectRootOperation:
    kind: str
    relative_components: tuple[str, ...]

    def document(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "relative_components": list(self.relative_components),
            "create_mode": "exclusive",
            "no_follow": True,
            "overwrite_allowed": False,
            "delete_allowed": False,
        }


CREATE_PROJECT = FixedDirectRootOperation(
    "create_project_directory_exclusive",
    ("project",),
)
CREATE_SCRATCH = FixedDirectRootOperation(
    "create_scratch_directory_exclusive",
    ("project", "scratch"),
)
FIXED_OPERATIONS = (CREATE_PROJECT, CREATE_SCRATCH)
_FIXED_OPERATION_BYTES = tuple(
    canonical_bytes(operation.document()) for operation in FIXED_OPERATIONS
)
RESULT_AUTHORITY = {
    "synthetic_only": True,
    "schema_valid_is_capability": False,
    "filesystem_authority": False,
    "backend_supported": False,
    "live_ready": False,
    "remote_effect_performed": False,
    "transport_authorized": False,
    "shell_authorized": False,
    "qsub_authorized": False,
    "path_reopen_allowed": False,
    "automatic_retry": False,
}


def _validate_fixed_operations(value: Any) -> list[dict[str, Any]]:
    expected = [operation.document() for operation in FIXED_OPERATIONS]
    _require(_is_exact_builtin_value(value, expected), "fixed operations differ")
    for index, operation in enumerate(value):
        _require(
            canonical_bytes(operation) == _FIXED_OPERATION_BYTES[index],
            f"fixed operation {index} differs",
        )
    return copy.deepcopy(value)


def validate_synthetic_mutation_result(document: Any) -> dict[str, Any]:
    _require(type(document) is dict, "synthetic result must be an exact object")
    required = {
        "schema",
        "owner",
        "boundary_version",
        "backend_kind",
        "binding_payload_sha256",
        "operations",
        "outcome",
        "authority",
        "result_payload_sha256",
    }
    _require(set(document) == required, "synthetic result fields differ")
    result = copy.deepcopy(document)
    _require(
        _is_exact_builtin_value(result["schema"], RESULT_SCHEMA),
        "synthetic result schema differs",
    )
    _require(
        _is_exact_builtin_value(result["owner"], OWNER_ID),
        "synthetic result owner differs",
    )
    _require(
        _is_exact_builtin_value(result["boundary_version"], BOUNDARY_VERSION),
        "synthetic result version differs",
    )
    _require(
        _is_exact_builtin_value(result["backend_kind"], BACKEND_KIND),
        "synthetic backend differs",
    )
    for field in ("binding_payload_sha256", "result_payload_sha256"):
        value = result[field]
        _require(
            type(value) is str
            and len(value) == 64
            and all(character in "0123456789abcdef" for character in value)
            and value != "0" * 64,
            f"synthetic result {field} differs",
        )
    result["operations"] = _validate_fixed_operations(result["operations"])
    _require(
        _is_exact_builtin_value(result["outcome"], COMPLETED),
        "synthetic result outcome differs",
    )
    _require(
        _is_exact_builtin_value(result["authority"], RESULT_AUTHORITY),
        "synthetic result authority differs",
    )
    projection = copy.deepcopy(result)
    projection["result_payload_sha256"] = ""
    _require(
        hmac.compare_digest(result["result_payload_sha256"], digest(projection)),
        "synthetic result payload hash differs",
    )
    return result


def _assert_root_capability(
    capability: ROOT.SingleUseWorkspaceDescriptorCapability,
) -> None:
    ROOT._assert_owner_binding()
    _require(
        type(capability) is ROOT.SingleUseWorkspaceDescriptorCapability,
        "exact direct-root capability is required",
    )
    ROOT.SingleUseWorkspaceDescriptorCapability.assert_current(capability)
    _require(
        capability._descriptor_set._mode == "offline_synthetic",
        "synthetic boundary rejects production descriptor capabilities",
    )


def _binding_from_capability(
    capability: ROOT.SingleUseWorkspaceDescriptorCapability,
) -> dict[str, Any]:
    _assert_root_capability(capability)
    receipt = ROOT.validate_fresh_root_observation_receipt(
        capability.portable_receipt()
    )
    _require(
        receipt["observed_root"]["fresh_project"] is True
        and receipt["observed_root"]["containment_verified"] is True
        and receipt["observed_root"]["no_symlink_verified"] is True,
        "fresh root safety replay differs",
    )
    _require(
        receipt["authority"]["portable_receipt_authorizes_effect"] is False
        and receipt["authority"]["descriptor_relative_operations_required"]
        is True
        and receipt["authority"]["path_reopen_allowed"] is False
        and receipt["authority"]["automatic_retry"] is False
        and receipt["authority"]["remote_effect_performed"] is False,
        "fresh root authority replay differs",
    )
    document = {
        "schema": BINDING_SCHEMA,
        "owner": OWNER_ID,
        "boundary_version": BOUNDARY_VERSION,
        "backend_kind": BACKEND_KIND,
        "root_owner_version": ROOT.OWNER_VERSION,
        "profile_schema": ROOT.DIRECT_PROFILE_SCHEMA,
        "authorization_schema": ROOT.DIRECT_AUTHORIZATION_SCHEMA,
        "live_ready": False,
        "profile_payload_sha256": receipt["profile"]["profile_payload_sha256"],
        "stable_root_evidence_sha256": receipt["stable_root_evidence"][
            "evidence_payload_sha256"
        ],
        "authorization_id": receipt["authorization"]["authorization_id"],
        "authorization_payload_sha256": receipt["authorization"][
            "authorization_payload_sha256"
        ],
        "authorization_scope_sha256": receipt["authorization"][
            "authorization_scope_sha256"
        ],
        "receipt_payload_sha256": receipt["receipt_payload_sha256"],
        "workspace_binding_sha256": receipt["observed_root"][
            "workspace_binding_sha256"
        ],
        "descriptor_set_sha256": receipt["observed_root"][
            "descriptor_set_sha256"
        ],
        "operations": [operation.document() for operation in FIXED_OPERATIONS],
        "synthetic_only": True,
        "filesystem_authority": False,
        "path_reopen_allowed": False,
        "automatic_retry": False,
        "binding_payload_sha256": "",
    }
    return _finalize(document, "binding_payload_sha256")


class SyntheticDescriptorRelativeHelper:
    """Fixed in-memory recorder; never a production helper or capability."""

    __slots__ = ("_failure_after", "_invoked", "_lock", "_seal", "_trace")

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        raise TypeError("synthetic helpers are owner-issued only")

    @classmethod
    def _for_testing(
        cls,
        *,
        failure_after: str | None,
        token: object,
    ) -> "SyntheticDescriptorRelativeHelper":
        _require(
            cls is SyntheticDescriptorRelativeHelper
            and token is _HELPER_TOKEN
            and failure_after in {None, CREATE_PROJECT.kind, CREATE_SCRATCH.kind},
            "synthetic helper configuration differs",
        )
        value = object.__new__(cls)
        value._failure_after = failure_after
        value._invoked = False
        value._lock = threading.Lock()
        value._seal = _HELPER_TOKEN
        value._trace: list[str] = []
        return value

    def trace(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._trace)

    def _assert_ready(self) -> None:
        _require(
            type(self) is SyntheticDescriptorRelativeHelper
            and self._seal is _HELPER_TOKEN
            and self._invoked is False,
            "synthetic helper is foreign or already invoked",
        )

    def _apply_fixed_once(
        self,
        handles: tuple[object, ...],
        operations: tuple[FixedDirectRootOperation, ...],
    ) -> tuple[str, ...]:
        with self._lock:
            self._assert_ready()
            _require(
                type(handles) is tuple
                and len(handles) == 2
                and all(type(handle) is object for handle in handles),
                "synthetic descriptor handles differ",
            )
            _require(operations is FIXED_OPERATIONS, "synthetic operations differ")
            self._invoked = True
            for operation in operations:
                self._trace.append(operation.kind)
                if self._failure_after == operation.kind:
                    raise RuntimeError(
                        f"synthetic fixed-operation failure after {operation.kind}"
                    )
            return tuple(self._trace)


class SingleUseDirectRootSyntheticMutationTransaction:
    __slots__ = (
        "_binding",
        "_helper",
        "_lock",
        "_outcome",
        "_root_capability",
        "_seal",
    )

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        raise TypeError("synthetic transactions are owner-issued only")

    @classmethod
    def _from_owner(
        cls,
        *,
        root_capability: ROOT.SingleUseWorkspaceDescriptorCapability,
        helper: SyntheticDescriptorRelativeHelper,
        token: object,
    ) -> "SingleUseDirectRootSyntheticMutationTransaction":
        _require(
            cls is SingleUseDirectRootSyntheticMutationTransaction
            and token is _TRANSACTION_TOKEN,
            "synthetic transaction factory differs",
        )
        _assert_root_capability(root_capability)
        _require(type(helper) is SyntheticDescriptorRelativeHelper, "exact synthetic helper is required")
        helper._assert_ready()
        value = object.__new__(cls)
        value._binding = canonical_bytes(_binding_from_capability(root_capability))
        value._helper = helper
        value._lock = threading.Lock()
        value._outcome = READY
        value._root_capability = root_capability
        value._seal = _TRANSACTION_TOKEN
        return value

    def portable_binding(self) -> dict[str, Any]:
        return json.loads(self._binding)

    def outcome(self) -> str:
        with self._lock:
            return self._outcome

    def consume_and_apply_synthetic_once(self) -> dict[str, Any]:
        with self._lock:
            _require(
                type(self) is SingleUseDirectRootSyntheticMutationTransaction
                and self._seal is _TRANSACTION_TOKEN
                and self._outcome == READY,
                "synthetic transaction is already consumed or terminal",
            )
            _assert_root_capability(self._root_capability)
            self._helper._assert_ready()
            binding = json.loads(self._binding)
            try:
                lease = ROOT.SingleUseWorkspaceDescriptorCapability.consume_once(
                    self._root_capability
                )
            except BaseException:
                self._outcome = DESCRIPTOR_CONSUMPTION_FAILED
                raise
            self._outcome = DESCRIPTOR_CONSUMED_NO_EFFECT_TERMINAL
            ROOT.ConsumedWorkspaceDescriptorLease.assert_owner_sealed(lease)
            _require(
                lease.receipt_payload_sha256 == binding["receipt_payload_sha256"]
                and lease.authorization_scope_sha256
                == binding["authorization_scope_sha256"]
                and lease.descriptor_set_sha256 == binding["descriptor_set_sha256"]
                and lease.remote_effect_authorized is False
                and lease.path_reopen_allowed is False
                and lease._descriptor_set is self._root_capability._descriptor_set,
                "consumed direct-root lease differs",
            )
            handles = lease._descriptor_set._opaque_handles
            _require(
                handles is self._root_capability._descriptor_handles,
                "consumed direct-root handles differ",
            )
            self._outcome = EFFECT_STARTED_OUTCOME_UNCERTAIN
            trace = self._helper._apply_fixed_once(handles, FIXED_OPERATIONS)
            _require(
                trace == tuple(operation.kind for operation in FIXED_OPERATIONS),
                "synthetic helper trace differs",
            )
            result = {
                "schema": RESULT_SCHEMA,
                "owner": OWNER_ID,
                "boundary_version": BOUNDARY_VERSION,
                "backend_kind": BACKEND_KIND,
                "binding_payload_sha256": binding["binding_payload_sha256"],
                "operations": [operation.document() for operation in FIXED_OPERATIONS],
                "outcome": COMPLETED,
                "authority": copy.deepcopy(RESULT_AUTHORITY),
                "result_payload_sha256": "",
            }
            validated = validate_synthetic_mutation_result(
                _finalize(result, "result_payload_sha256")
            )
            self._outcome = COMPLETED
            return validated


class DirectRootMutationBoundaryOwner:
    __slots__ = ("_issued", "_lock", "_seal")

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        raise TypeError("direct-root mutation owners use the private test factory")

    @classmethod
    def _for_testing(
        cls,
        *,
        _test_token: object,
    ) -> "DirectRootMutationBoundaryOwner":
        _require(
            cls is DirectRootMutationBoundaryOwner and _test_token is _TEST_TOKEN,
            "direct-root mutation owner test factory differs",
        )
        value = object.__new__(cls)
        value._issued = False
        value._lock = threading.Lock()
        value._seal = _OWNER_TOKEN
        return value

    def _synthetic_helper_for_testing(
        self,
        *,
        failure_after: str | None = None,
        _test_token: object,
    ) -> SyntheticDescriptorRelativeHelper:
        _require(
            type(self) is DirectRootMutationBoundaryOwner
            and self._seal is _OWNER_TOKEN
            and _test_token is _TEST_TOKEN,
            "synthetic helper test factory differs",
        )
        return SyntheticDescriptorRelativeHelper._for_testing(
            failure_after=failure_after,
            token=_HELPER_TOKEN,
        )

    def issue_synthetic_transaction_once(
        self,
        *,
        root_capability: ROOT.SingleUseWorkspaceDescriptorCapability,
        helper: SyntheticDescriptorRelativeHelper,
    ) -> SingleUseDirectRootSyntheticMutationTransaction:
        with self._lock:
            _require(
                type(self) is DirectRootMutationBoundaryOwner
                and self._seal is _OWNER_TOKEN
                and self._issued is False,
                "direct-root mutation owner is foreign or already used",
            )
            transaction = SingleUseDirectRootSyntheticMutationTransaction._from_owner(
                root_capability=root_capability,
                helper=helper,
                token=_TRANSACTION_TOKEN,
            )
            self._issued = True
            return transaction
