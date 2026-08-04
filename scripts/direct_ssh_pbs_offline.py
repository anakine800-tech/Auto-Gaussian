#!/usr/bin/env python3
"""Minimal non-executable direct SSH/PBS synthetic transaction.

There is no SSH, shell, network, PBS, Gaussian, qsub, qdel, delete, cleanup,
or fallback implementation here.  The fake transport records only fixed typed
in-memory operations and every returned artifact is non-authorizing.
"""

from __future__ import annotations

import copy
import hashlib
import json
import threading
from dataclasses import dataclass
from enum import Enum
from typing import Any

import direct_root_mutation_boundary as ROOT_BOUNDARY
import direct_root_owner_contract as ROOT_OWNER


BACKEND_KIND = "direct_ssh_pbs"
TRANSPORT_KIND = "direct_ssh"
SCHEDULER_DIALECT = "pbs_legacy_v1"
READY = "ready"
SUBMISSION_UNCERTAIN = "submission_uncertain"
INTENT_RECORDED = "synthetic_qsub_intent_recorded"


class DirectOfflineError(ValueError):
    pass


class SyntheticOutcomeUnknown(RuntimeError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DirectOfflineError(message)


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


def finalized(document: dict[str, Any], field: str) -> dict[str, Any]:
    value = copy.deepcopy(document)
    value[field] = ""
    value[field] = digest(value)
    return value


class Operation(str, Enum):
    PUBLISH_UNCERTAIN = "publish_submission_uncertain"
    RECORD_WORKSPACE = "record_workspace_claim"
    TRANSFER_INPUT = "transfer_immutable_input"
    RECORD_QSUB_INTENT = "record_synthetic_qsub_intent"
    INSPECT = "inspect_read_only"
    FETCH = "fetch_read_only"


MUTATIONS = (
    Operation.PUBLISH_UNCERTAIN,
    Operation.RECORD_WORKSPACE,
    Operation.TRANSFER_INPUT,
    Operation.RECORD_QSUB_INTENT,
)


@dataclass(frozen=True, slots=True)
class OwnerGap:
    port: str
    exact_owner: str
    expected_type: str

    def document(self) -> dict[str, Any]:
        return {
            "port": self.port,
            "exact_owner": self.exact_owner,
            "expected_type": self.expected_type,
            "status": "required_exact_direct_ingress_unavailable",
            "fallback_allowed": False,
            "synthetic_substitute_allowed": False,
        }


OWNER_GAPS = (
    OwnerGap(
        "resource_effect_time_replay",
        "resource_effect_time_replay_owner",
        "ResourceEffectTimeReplayCapability",
    ),
    OwnerGap(
        "live_approval_effect_time_replay",
        "live_approval_effect_time_replay",
        "PreQsubLiveApprovalReplayCapability",
    ),
)


@dataclass(frozen=True, slots=True)
class ImmutableInput:
    basename: str
    payload: bytes

    def __post_init__(self) -> None:
        _require(type(self.basename) is str and bool(self.basename), "input basename differs")
        _require(type(self.payload) is bytes and bool(self.payload), "input must be non-empty exact bytes")

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.payload).hexdigest()

    @property
    def size_bytes(self) -> str:
        return str(len(self.payload))

    def metadata(self) -> dict[str, str]:
        return {
            "basename": self.basename,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
        }


@dataclass(frozen=True, slots=True)
class Binding:
    _bytes: bytes

    def document(self) -> dict[str, Any]:
        return json.loads(self._bytes)

    @property
    def sha256(self) -> str:
        return self.document()["binding_payload_sha256"]


def build_binding(
    root_capability: ROOT_OWNER.SingleUseWorkspaceDescriptorCapability,
    root_transaction: ROOT_BOUNDARY.SingleUseDirectRootSyntheticMutationTransaction,
    immutable_input: ImmutableInput,
) -> Binding:
    """Replay predecessor owners and retain only one exact closed projection."""
    _require(type(immutable_input) is ImmutableInput, "exact immutable input is required")
    _require(
        type(root_capability) is ROOT_OWNER.SingleUseWorkspaceDescriptorCapability,
        "exact direct-root capability is required",
    )
    root_capability.assert_current()
    _require(
        type(root_transaction)
        is ROOT_BOUNDARY.SingleUseDirectRootSyntheticMutationTransaction
        and root_transaction._root_capability is root_capability,
        "root transaction and capability identities differ",
    )

    profile = ROOT_OWNER.validate_direct_execution_profile(
        json.loads(root_capability._profile_bytes)
    )
    authorization = ROOT_OWNER.validate_direct_execution_authorization(
        json.loads(root_capability._authorization_bytes)
    )
    receipt = ROOT_OWNER.validate_fresh_root_observation_receipt(
        root_capability.portable_receipt()
    )
    root = root_transaction.portable_binding()
    scope = authorization["scope"]
    workspace = authorization["workspace"]
    approved_input = authorization["input"]

    _require(
        profile["backend_kind"] == BACKEND_KIND
        and profile["scheduler_dialect"] == SCHEDULER_DIALECT,
        "unsupported direct topology",
    )
    _require(
        authorization["live_ready"] is False
        and authorization["profile"]["profile_payload_sha256"]
        == profile["profile_payload_sha256"]
        and receipt["profile"]["profile_payload_sha256"]
        == profile["profile_payload_sha256"]
        and receipt["stable_root_evidence"]["evidence_payload_sha256"]
        == profile["stable_root_identity_evidence_sha256"]
        and receipt["authorization"]["authorization_payload_sha256"]
        == authorization["authorization_payload_sha256"]
        and receipt["authorization"]["authorization_scope_sha256"]
        == scope["authorization_scope_sha256"],
        "profile, evidence, receipt, or authorization join differs",
    )
    _require(
        root["backend_kind"] == BACKEND_KIND
        and root["profile_payload_sha256"] == profile["profile_payload_sha256"]
        and root["stable_root_evidence_sha256"]
        == receipt["stable_root_evidence"]["evidence_payload_sha256"]
        and root["receipt_payload_sha256"] == receipt["receipt_payload_sha256"]
        and root["workspace_binding_sha256"] == workspace["workspace_binding_sha256"]
        and root["descriptor_set_sha256"]
        == receipt["observed_root"]["descriptor_set_sha256"],
        "milestone-1 root join differs",
    )
    _require(
        receipt["operation"]["scientific_task_id"] == scope["scientific_task_id"]
        and receipt["operation"]["attempt_id"] == scope["attempt_id"]
        and receipt["observed_root"]["project"] == workspace["project"]
        and immutable_input.metadata() == approved_input,
        "workspace, task, attempt, or immutable input join differs",
    )

    document = finalized(
        {
            "schema": "auto-g16-direct-ssh-pbs-offline-binding/1",
            "backend_kind": BACKEND_KIND,
            "transport_kind": TRANSPORT_KIND,
            "scheduler_dialect": SCHEDULER_DIALECT,
            "profile": {
                "profile_id": profile["profile_id"],
                "profile_payload_sha256": profile["profile_payload_sha256"],
                "stable_root_evidence_sha256": profile[
                    "stable_root_identity_evidence_sha256"
                ],
                "resource_catalog_sha256": profile["resource_catalog_sha256"],
            },
            "receipt_payload_sha256": receipt["receipt_payload_sha256"],
            "authorization": {
                "authorization_id": authorization["authorization_id"],
                "authorization_payload_sha256": authorization[
                    "authorization_payload_sha256"
                ],
                "authorization_scope_sha256": scope["authorization_scope_sha256"],
            },
            "workspace": {
                "project": workspace["project"],
                "workspace_binding_sha256": workspace["workspace_binding_sha256"],
                "descriptor_set_sha256": receipt["observed_root"][
                    "descriptor_set_sha256"
                ],
            },
            "input": copy.deepcopy(approved_input),
            "resources": copy.deepcopy(authorization["resources"]),
            "scope": {
                "scientific_task_id": scope["scientific_task_id"],
                "attempt_id": scope["attempt_id"],
                "idempotency_key": scope["idempotency_key"],
            },
            "owner_gaps": [gap.document() for gap in OWNER_GAPS],
            "live_ready": False,
            "binding_payload_sha256": "",
        },
        "binding_payload_sha256",
    )
    return Binding(canonical_bytes(document))


@dataclass(frozen=True, slots=True)
class Inspection:
    binding_sha256: str
    state: str
    input_present: bool
    qsub_intent_count: int
    operation: Operation = Operation.INSPECT
    read_only: bool = True
    remote_effect_performed: bool = False


@dataclass(frozen=True, slots=True)
class FetchedInput:
    binding_sha256: str
    basename: str
    payload: bytes
    operation: Operation = Operation.FETCH
    read_only: bool = True
    remote_effect_performed: bool = False

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.payload).hexdigest()


class ClosedFakeTransport:
    """One fixed in-memory operation set; no command or generic executor."""

    def __init__(
        self,
        *,
        failure_at: Operation | None = None,
        unknown_at: Operation | None = None,
    ) -> None:
        _require(
            (failure_at is None or type(failure_at) is Operation)
            and (unknown_at is None or type(unknown_at) is Operation)
            and not (failure_at and unknown_at),
            "fake transport configuration differs",
        )
        self._failure_at = failure_at
        self._unknown_at = unknown_at
        self._lock = threading.Lock()
        self._binding_sha: str | None = None
        self._state = READY
        self._trace: list[str] = []
        self._input: ImmutableInput | None = None
        self._qsub_intent: bytes | None = None

    def _finish(self, operation: Operation) -> None:
        if self._unknown_at is operation:
            raise SyntheticOutcomeUnknown(f"outcome unknown after {operation.value}")
        if self._failure_at is operation:
            raise RuntimeError(f"synthetic failure after {operation.value}")

    def publish_uncertain(self, binding: Binding) -> None:
        with self._lock:
            _require(self._state == READY and not self._trace, "transaction already published")
            self._binding_sha = binding.sha256
            self._state = SUBMISSION_UNCERTAIN
            self._trace.append(Operation.PUBLISH_UNCERTAIN.value)
            self._finish(Operation.PUBLISH_UNCERTAIN)

    def _same(self, binding: Binding) -> None:
        _require(
            type(binding) is Binding and binding.sha256 == self._binding_sha,
            "fake transport binding differs",
        )

    def record_workspace(self, binding: Binding, root_result: dict[str, Any]) -> None:
        with self._lock:
            self._same(binding)
            ROOT_BOUNDARY.validate_synthetic_mutation_result(root_result)
            _require(Operation.RECORD_WORKSPACE.value not in self._trace, "workspace already recorded")
            self._trace.append(Operation.RECORD_WORKSPACE.value)
            self._finish(Operation.RECORD_WORKSPACE)

    def transfer_input(self, binding: Binding, value: ImmutableInput) -> dict[str, Any]:
        with self._lock:
            self._same(binding)
            _require(type(value) is ImmutableInput and self._input is None, "input already transferred")
            _require(value.metadata() == binding.document()["input"], "transfer input differs")
            self._input = ImmutableInput(value.basename, bytes(value.payload))
            self._trace.append(Operation.TRANSFER_INPUT.value)
            self._finish(Operation.TRANSFER_INPUT)
            return finalized(
                {
                    "schema": "auto-g16-direct-synthetic-transfer/1",
                    "binding_payload_sha256": binding.sha256,
                    "input": value.metadata(),
                    "immutable": True,
                    "remote_effect_performed": False,
                    "payload_sha256": "",
                },
                "payload_sha256",
            )

    def record_qsub_intent(self, binding: Binding, transfer: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._same(binding)
            _require(self._input is not None and self._qsub_intent is None, "second qsub intent forbidden")
            _require(
                type(transfer) is dict
                and transfer.get("binding_payload_sha256") == binding.sha256
                and transfer.get("remote_effect_performed") is False,
                "transfer receipt differs",
            )
            scope = binding.document()["scope"]
            intent = finalized(
                {
                    "schema": "auto-g16-direct-synthetic-qsub-intent/1",
                    "binding_payload_sha256": binding.sha256,
                    "transfer_payload_sha256": transfer["payload_sha256"],
                    **scope,
                    "command_present": False,
                    "qsub_invoked": False,
                    "scheduler_effect_performed": False,
                    "payload_sha256": "",
                },
                "payload_sha256",
            )
            self._qsub_intent = canonical_bytes(intent)
            self._trace.append(Operation.RECORD_QSUB_INTENT.value)
            self._finish(Operation.RECORD_QSUB_INTENT)
            return intent

    def inspect(self, binding: Binding) -> Inspection:
        with self._lock:
            self._same(binding)
            return Inspection(
                binding.sha256,
                self._state,
                self._input is not None,
                int(self._qsub_intent is not None),
            )

    def fetch(self, binding: Binding) -> FetchedInput:
        with self._lock:
            self._same(binding)
            _require(self._input is not None, "no input is available")
            return FetchedInput(binding.sha256, self._input.basename, bytes(self._input.payload))

    def snapshot(self) -> tuple[str, tuple[str, ...], int, bool]:
        with self._lock:
            return (
                self._state,
                tuple(self._trace),
                int(self._qsub_intent is not None),
                self._input is not None,
            )


AUTHORITY = {
    "synthetic_only": True,
    "schema_valid_is_capability": False,
    "backend_supported": False,
    "live_ready": False,
    "remote_effect_performed": False,
    "transport_authorized": False,
    "qsub_authorized": False,
    "qsub_invoked": False,
    "qdel_capability": False,
    "qdel_requires_separate_exact_authorization": True,
    "delete_capability": False,
    "cleanup_capability": False,
    "automatic_retry": False,
}


@dataclass(frozen=True, slots=True)
class SyntheticResult:
    _bytes: bytes

    def document(self) -> dict[str, Any]:
        result = json.loads(self._bytes)
        _require(
            set(result)
            == {
                "schema",
                "binding",
                "state",
                "root_result_sha256",
                "transfer_sha256",
                "qsub_intent_sha256",
                "owner_gaps",
                "authority",
                "result_payload_sha256",
            }
            and ROOT_BOUNDARY._is_exact_builtin_value(
                result["schema"],
                "auto-g16-direct-ssh-pbs-offline-result/1",
            )
            and ROOT_BOUNDARY._is_exact_builtin_value(
                result["state"],
                INTENT_RECORDED,
            )
            and ROOT_BOUNDARY._is_exact_builtin_value(
                result["owner_gaps"],
                [gap.document() for gap in OWNER_GAPS],
            )
            and ROOT_BOUNDARY._is_exact_builtin_value(
                result["authority"],
                AUTHORITY,
            ),
            "closed synthetic result differs",
        )
        projection = copy.deepcopy(result)
        projection["result_payload_sha256"] = ""
        _require(digest(projection) == result["result_payload_sha256"], "result hash differs")
        return result


class SyntheticTransaction:
    def __init__(
        self,
        *,
        root_capability: ROOT_OWNER.SingleUseWorkspaceDescriptorCapability,
        root_transaction: ROOT_BOUNDARY.SingleUseDirectRootSyntheticMutationTransaction,
        immutable_input: ImmutableInput,
        transport: ClosedFakeTransport,
    ) -> None:
        _require(type(transport) is ClosedFakeTransport, "exact closed fake transport is required")
        self._binding = build_binding(root_capability, root_transaction, immutable_input)
        self._root_transaction = root_transaction
        self._input = immutable_input
        self._transport = transport
        self._lock = threading.Lock()
        self._state = READY

    def binding(self) -> dict[str, Any]:
        return self._binding.document()

    def state(self) -> str:
        with self._lock:
            return self._state

    def run_once(self) -> SyntheticResult:
        with self._lock:
            _require(self._state == READY, "transaction already terminal")
            # This terminal-for-retry state precedes every helper invocation.
            self._state = SUBMISSION_UNCERTAIN
            self._transport.publish_uncertain(self._binding)
            root = self._root_transaction.consume_and_apply_synthetic_once()
            self._transport.record_workspace(self._binding, root)
            transfer = self._transport.transfer_input(self._binding, self._input)
            intent = self._transport.record_qsub_intent(self._binding, transfer)
            self._state = INTENT_RECORDED
            result = finalized(
                {
                    "schema": "auto-g16-direct-ssh-pbs-offline-result/1",
                    "binding": self._binding.document(),
                    "state": self._state,
                    "root_result_sha256": root["result_payload_sha256"],
                    "transfer_sha256": transfer["payload_sha256"],
                    "qsub_intent_sha256": intent["payload_sha256"],
                    "owner_gaps": [gap.document() for gap in OWNER_GAPS],
                    "authority": copy.deepcopy(AUTHORITY),
                    "result_payload_sha256": "",
                },
                "result_payload_sha256",
            )
            return SyntheticResult(canonical_bytes(result))

    def inspect(self) -> Inspection:
        return self._transport.inspect(self._binding)

    def fetch(self) -> FetchedInput:
        return self._transport.fetch(self._binding)
