"""Immutable approval evidence for the frozen V30-3A authority contract."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
import json
from math import isfinite
from typing import Final
from uuid import UUID, uuid5

from auto_g16.core import (
    Attempt,
    AttemptState,
    CalculationPlan,
    CoreValidationError,
    RuntimeStoreError,
    SQLiteRuntimeStore,
)
from auto_g16.execution import (
    ExecutionSnapshot,
    ExecutionValueError,
    prepare_execution_snapshot,
)

APPROVAL_SCHEMA_VERSION: Final = 1
_APPROVAL_NAMESPACE: Final = UUID("b6f5ea80-fd5d-5e67-a66b-e4b7f66e90b3")
_IDENTITY_DOMAINS: Final = frozenset(
    {"scientific-approval", "batch-submit-approval", "operational-confirmation"}
)


class ApprovalValueError(ValueError):
    """Approval evidence does not satisfy the frozen v3 authority contract."""


class _FrozenMapping(Mapping[str, object]):
    __slots__ = ("_items",)

    def __init__(self, items: tuple[tuple[str, object], ...]) -> None:
        self._items = items

    def __getitem__(self, key: str) -> object:
        for item_key, value in self._items:
            if item_key == key:
                return value
        raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        return (key for key, _value in self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __repr__(self) -> str:
        return repr(dict(self._items))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Mapping):
            return False
        try:
            return self._items == freeze_mapping(other, "mapping")._items
        except ApprovalValueError:
            return False

    def __hash__(self) -> int:
        return hash(self._items)


def require_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ApprovalValueError(
            f"{field_name} must be a non-empty string without surrounding whitespace"
        )
    if "\x00" in value:
        raise ApprovalValueError(f"{field_name} must not contain NUL")
    return value


def require_positive_integer(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ApprovalValueError(f"{field_name} must be a positive integer")
    return value


def freeze_mapping(value: Mapping[str, object], field_name: str) -> _FrozenMapping:
    frozen = _freeze_value(value, field_name, set())
    if not isinstance(frozen, _FrozenMapping):
        raise ApprovalValueError(f"{field_name} must be a mapping")
    return frozen


def _freeze_value(value: object, path: str, active: set[int]) -> object:
    if value is None or type(value) in {bool, int, str}:
        return value
    if type(value) is float:
        if not isfinite(value):
            raise ApprovalValueError(f"{path} must not contain a non-finite float")
        return value
    if isinstance(value, Mapping):
        identity = id(value)
        if identity in active:
            raise ApprovalValueError(f"{path} must not contain a container cycle")
        active.add(identity)
        try:
            items: list[tuple[str, object]] = []
            for key, item in value.items():
                if not isinstance(key, str) or not key:
                    raise ApprovalValueError(f"{path} keys must be non-empty strings")
                items.append((key, _freeze_value(item, f"{path}.{key}", active)))
            return _FrozenMapping(tuple(sorted(items, key=lambda pair: pair[0])))
        finally:
            active.remove(identity)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        identity = id(value)
        if identity in active:
            raise ApprovalValueError(f"{path} must not contain a container cycle")
        active.add(identity)
        try:
            return tuple(
                _freeze_value(item, f"{path}[{index}]", active)
                for index, item in enumerate(value)
            )
        finally:
            active.remove(identity)
    raise ApprovalValueError(
        f"{path} contains unsupported value type {type(value).__name__}"
    )


def _canonical_node(value: object) -> object:
    if value is None:
        return ["null", None]
    if type(value) is bool:
        return ["boolean", value]
    if type(value) is int:
        return ["integer", value]
    if type(value) is float:
        if not isfinite(value):
            raise ApprovalValueError("identity payload contains a non-finite float")
        return ["float", value]
    if type(value) is str:
        return ["string", value]
    if isinstance(value, Mapping):
        return [
            "mapping",
            [[key, _canonical_node(value[key])] for key in sorted(value)],
        ]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return ["sequence", [_canonical_node(item) for item in value]]
    raise ApprovalValueError(
        f"identity payload contains unsupported value type {type(value).__name__}"
    )


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        _canonical_node(value),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=False,
    ).encode("utf-8")


def identity_for(domain: str, payload: Mapping[str, object]) -> str:
    if domain not in _IDENTITY_DOMAINS:
        raise ApprovalValueError(f"unsupported approval identity domain {domain!r}")
    domain_namespace = uuid5(
        _APPROVAL_NAMESPACE,
        f"auto-g16.approval/v{APPROVAL_SCHEMA_VERSION}/{domain}",
    )
    name = canonical_bytes(
        {
            "schema_version": APPROVAL_SCHEMA_VERSION,
            "domain": domain,
            "authority": payload,
        }
    ).decode("utf-8")
    return str(uuid5(domain_namespace, name))


def plain_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: plain_value(value[key]) for key in sorted(value)}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [plain_value(item) for item in value]
    return value


class ApprovalDecision(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"


def _decision(value: object, field_name: str) -> ApprovalDecision:
    if not isinstance(value, ApprovalDecision):
        raise ApprovalValueError(f"{field_name} must be an ApprovalDecision")
    return value


@dataclass(frozen=True, slots=True, kw_only=True, init=False)
class ScientificApproval:
    calculation_plan_id: str
    task_id: str
    calculation_plan_revision: int
    canonical_intent: Mapping[str, object] = field(repr=False)
    displayed_semantic_meaning: Mapping[str, object] = field(repr=False)
    reviewer_id: str
    reviewer_evidence: Mapping[str, object] = field(repr=False)
    decision: ApprovalDecision
    schema_version: int = field(init=False, default=APPROVAL_SCHEMA_VERSION)
    scientific_approval_id: str = field(init=False)

    def __init__(self) -> None:
        raise TypeError("ScientificApproval is created only by for_plan")

    @classmethod
    def _from_values(
        cls,
        *,
        calculation_plan_id: str,
        task_id: str,
        calculation_plan_revision: int,
        canonical_intent: Mapping[str, object],
        displayed_semantic_meaning: Mapping[str, object],
        reviewer_id: str,
        reviewer_evidence: Mapping[str, object],
        decision: ApprovalDecision,
    ) -> ScientificApproval:
        require_text(calculation_plan_id, "calculation_plan_id")
        require_text(task_id, "task_id")
        require_positive_integer(calculation_plan_revision, "calculation_plan_revision")
        require_text(reviewer_id, "reviewer_id")
        _decision(decision, "decision")
        value = object.__new__(cls)
        object.__setattr__(value, "calculation_plan_id", calculation_plan_id)
        object.__setattr__(value, "task_id", task_id)
        object.__setattr__(value, "calculation_plan_revision", calculation_plan_revision)
        object.__setattr__(
            value, "canonical_intent", freeze_mapping(canonical_intent, "canonical_intent")
        )
        object.__setattr__(
            value,
            "displayed_semantic_meaning",
            freeze_mapping(displayed_semantic_meaning, "displayed_semantic_meaning"),
        )
        object.__setattr__(value, "reviewer_id", reviewer_id)
        object.__setattr__(
            value,
            "reviewer_evidence",
            freeze_mapping(reviewer_evidence, "reviewer_evidence"),
        )
        object.__setattr__(value, "decision", decision)
        object.__setattr__(value, "schema_version", APPROVAL_SCHEMA_VERSION)
        object.__setattr__(
            value,
            "scientific_approval_id",
            identity_for("scientific-approval", value.authority_payload()),
        )
        return value

    @classmethod
    def for_plan(
        cls,
        runtime_store: SQLiteRuntimeStore,
        plan: CalculationPlan,
        *,
        displayed_semantic_meaning: Mapping[str, object],
        reviewer_id: str,
        reviewer_evidence: Mapping[str, object],
        decision: ApprovalDecision = ApprovalDecision.APPROVED,
    ) -> ScientificApproval:
        if not isinstance(runtime_store, SQLiteRuntimeStore):
            raise ApprovalValueError("runtime_store must be a public Core SQLiteRuntimeStore")
        if not isinstance(plan, CalculationPlan):
            raise ApprovalValueError("plan must be a public Core CalculationPlan")
        if runtime_store.load_calculation_plan(plan.calculation_plan_id) != plan:
            raise ApprovalConflictError("plan differs from its current durable Core record")
        return cls._from_values(
            calculation_plan_id=plan.calculation_plan_id,
            task_id=plan.task_id,
            calculation_plan_revision=plan.revision,
            canonical_intent=plan.intent,
            displayed_semantic_meaning=displayed_semantic_meaning,
            reviewer_id=reviewer_id,
            reviewer_evidence=reviewer_evidence,
            decision=decision,
        )

    def authority_payload(self) -> Mapping[str, object]:
        return freeze_mapping(
            {
                "calculation_plan_id": self.calculation_plan_id,
                "task_id": self.task_id,
                "calculation_plan_revision": self.calculation_plan_revision,
                "canonical_intent": self.canonical_intent,
                "displayed_semantic_meaning": self.displayed_semantic_meaning,
                "reviewer_id": self.reviewer_id,
                "reviewer_evidence": self.reviewer_evidence,
                "decision": self.decision.value,
            },
            "scientific approval authority",
        )

    def _assert_plan_current(self, plan: CalculationPlan) -> None:
        if not isinstance(plan, CalculationPlan):
            raise ApprovalValueError("plan must be a public Core CalculationPlan")
        observed = {
            "calculation_plan_id": plan.calculation_plan_id,
            "task_id": plan.task_id,
            "calculation_plan_revision": plan.revision,
            "canonical_intent": plan.intent,
        }
        for key, value in observed.items():
            if self.authority_payload()[key] != value:
                raise StaleApprovalError(f"Scientific Approval {key} is stale")
        if identity_for("scientific-approval", self.authority_payload()) != self.scientific_approval_id:
            raise ApprovalConflictError("Scientific Approval identity is stale")
        if self.decision is not ApprovalDecision.APPROVED:
            raise ApprovalRejectedError("Scientific Approval is not approved")

    def assert_current(
        self,
        plan: CalculationPlan,
        *,
        displayed_semantic_meaning: Mapping[str, object],
    ) -> None:
        self._assert_plan_current(plan)
        displayed = freeze_mapping(
            displayed_semantic_meaning, "displayed_semantic_meaning"
        )
        if displayed != self.displayed_semantic_meaning:
            raise StaleApprovalError(
                "Scientific Approval displayed semantic meaning is stale"
            )

    def persisted_payload(self) -> Mapping[str, object]:
        return freeze_mapping(
            {
                "schema_version": self.schema_version,
                "evidence_kind": "scientific-approval",
                "scientific_approval_id": self.scientific_approval_id,
                **dict(self.authority_payload()),
            },
            "persisted Scientific Approval",
        )


@dataclass(frozen=True, slots=True, kw_only=True, order=True)
class BatchApprovalMember:
    attempt_id: str
    task_id: str
    calculation_plan_id: str
    calculation_plan_revision: int
    scientific_approval_id: str

    def __post_init__(self) -> None:
        require_text(self.attempt_id, "attempt_id")
        require_text(self.task_id, "task_id")
        require_text(self.calculation_plan_id, "calculation_plan_id")
        require_positive_integer(
            self.calculation_plan_revision, "calculation_plan_revision"
        )
        require_text(self.scientific_approval_id, "scientific_approval_id")

    def payload(self) -> Mapping[str, object]:
        return freeze_mapping(
            {
                "attempt_id": self.attempt_id,
                "task_id": self.task_id,
                "calculation_plan_id": self.calculation_plan_id,
                "calculation_plan_revision": self.calculation_plan_revision,
                "scientific_approval_id": self.scientific_approval_id,
            },
            "Batch member",
        )


@dataclass(frozen=True, slots=True, kw_only=True, init=False)
class BatchSubmitApproval:
    members: tuple[BatchApprovalMember, ...]
    reviewer_id: str
    reviewer_evidence: Mapping[str, object] = field(repr=False)
    decision: ApprovalDecision
    schema_version: int = field(init=False, default=APPROVAL_SCHEMA_VERSION)
    batch_submit_approval_id: str = field(init=False)

    def __init__(self) -> None:
        raise TypeError("BatchSubmitApproval is created only by for_existing_attempts")

    @classmethod
    def _from_values(
        cls,
        *,
        members: tuple[BatchApprovalMember, ...],
        reviewer_id: str,
        reviewer_evidence: Mapping[str, object],
        decision: ApprovalDecision,
    ) -> BatchSubmitApproval:
        if not isinstance(members, tuple) or not members:
            raise ApprovalValueError("Batch Submit Approval requires a finite non-empty tuple")
        if not all(isinstance(member, BatchApprovalMember) for member in members):
            raise ApprovalValueError("members must contain only BatchApprovalMember values")
        canonical = tuple(sorted(members, key=lambda member: member.attempt_id))
        if len({member.attempt_id for member in canonical}) != len(canonical):
            raise ApprovalValueError("Batch Submit Approval contains duplicate Attempt identity")
        require_text(reviewer_id, "reviewer_id")
        _decision(decision, "decision")
        value = object.__new__(cls)
        object.__setattr__(value, "members", canonical)
        object.__setattr__(value, "reviewer_id", reviewer_id)
        object.__setattr__(
            value,
            "reviewer_evidence",
            freeze_mapping(reviewer_evidence, "reviewer_evidence"),
        )
        object.__setattr__(value, "decision", decision)
        object.__setattr__(value, "schema_version", APPROVAL_SCHEMA_VERSION)
        object.__setattr__(
            value,
            "batch_submit_approval_id",
            identity_for("batch-submit-approval", value.authority_payload()),
        )
        return value

    @classmethod
    def for_existing_attempts(
        cls,
        runtime_store: SQLiteRuntimeStore,
        bindings: Sequence[tuple[str, ScientificApproval]],
        *,
        reviewer_id: str,
        reviewer_evidence: Mapping[str, object],
        decision: ApprovalDecision = ApprovalDecision.APPROVED,
    ) -> BatchSubmitApproval:
        if not isinstance(runtime_store, SQLiteRuntimeStore):
            raise ApprovalValueError("runtime_store must be a public Core SQLiteRuntimeStore")
        if not isinstance(bindings, Sequence) or isinstance(bindings, (str, bytes)):
            raise ApprovalValueError("bindings must be a finite sequence")
        members: list[BatchApprovalMember] = []
        for index, binding in enumerate(bindings):
            if not isinstance(binding, tuple) or len(binding) != 2:
                raise ApprovalValueError(f"bindings[{index}] must be (attempt_id, approval)")
            attempt_id, scientific = binding
            require_text(attempt_id, f"bindings[{index}].attempt_id")
            if not isinstance(scientific, ScientificApproval):
                raise ApprovalValueError(f"bindings[{index}] approval is invalid")
            attempt = runtime_store.load_attempt(attempt_id)
            if runtime_store.attempt_state(attempt_id) is not AttemptState.PLANNED:
                raise ApprovalScopeError(
                    "Batch Submit Approval requires an existing PLANNED Attempt"
                )
            plan = runtime_store.load_calculation_plan(scientific.calculation_plan_id)
            scientific._assert_plan_current(plan)
            if attempt.task_id != plan.task_id:
                raise ApprovalConflictError("Attempt and approved plan belong to different Tasks")
            members.append(
                BatchApprovalMember(
                    attempt_id=attempt.attempt_id,
                    task_id=attempt.task_id,
                    calculation_plan_id=plan.calculation_plan_id,
                    calculation_plan_revision=plan.revision,
                    scientific_approval_id=scientific.scientific_approval_id,
                )
            )
        return cls._from_values(
            members=tuple(members),
            reviewer_id=reviewer_id,
            reviewer_evidence=reviewer_evidence,
            decision=decision,
        )

    def authority_payload(self) -> Mapping[str, object]:
        return freeze_mapping(
            {
                "members": tuple(member.payload() for member in self.members),
                "reviewer_id": self.reviewer_id,
                "reviewer_evidence": self.reviewer_evidence,
                "decision": self.decision.value,
            },
            "Batch Submit Approval authority",
        )

    def member_for(self, attempt_id: str) -> BatchApprovalMember:
        require_text(attempt_id, "attempt_id")
        if identity_for("batch-submit-approval", self.authority_payload()) != self.batch_submit_approval_id:
            raise ApprovalConflictError("Batch Submit Approval identity is stale")
        if self.decision is not ApprovalDecision.APPROVED:
            raise ApprovalRejectedError("Batch Submit Approval is not approved")
        for member in self.members:
            if member.attempt_id == attempt_id:
                return member
        raise ApprovalScopeError("Attempt is not an exact Batch Submit Approval member")

    def persisted_payload(self) -> Mapping[str, object]:
        return freeze_mapping(
            {
                "schema_version": self.schema_version,
                "evidence_kind": "batch-submit-approval",
                "batch_submit_approval_id": self.batch_submit_approval_id,
                **dict(self.authority_payload()),
            },
            "persisted Batch Submit Approval",
        )


@dataclass(frozen=True, slots=True, kw_only=True, init=False)
class ExactOperationalConfirmation:
    execution_snapshot_id: str
    attempt_id: str
    calculation_plan_id: str
    calculation_plan_revision: int
    execution_snapshot_semantics: Mapping[str, object] = field(repr=False)
    confirmer_id: str
    confirmer_evidence: Mapping[str, object] = field(repr=False)
    decision: ApprovalDecision
    schema_version: int = field(init=False, default=APPROVAL_SCHEMA_VERSION)
    operational_confirmation_id: str = field(init=False)

    def __init__(self) -> None:
        raise TypeError("ExactOperationalConfirmation is created only by for_snapshot")

    @classmethod
    def _from_values(
        cls,
        *,
        execution_snapshot_id: str,
        attempt_id: str,
        calculation_plan_id: str,
        calculation_plan_revision: int,
        execution_snapshot_semantics: Mapping[str, object],
        confirmer_id: str,
        confirmer_evidence: Mapping[str, object],
        decision: ApprovalDecision,
    ) -> ExactOperationalConfirmation:
        require_text(execution_snapshot_id, "execution_snapshot_id")
        require_text(attempt_id, "attempt_id")
        require_text(calculation_plan_id, "calculation_plan_id")
        require_positive_integer(calculation_plan_revision, "calculation_plan_revision")
        require_text(confirmer_id, "confirmer_id")
        _decision(decision, "decision")
        value = object.__new__(cls)
        object.__setattr__(value, "execution_snapshot_id", execution_snapshot_id)
        object.__setattr__(value, "attempt_id", attempt_id)
        object.__setattr__(value, "calculation_plan_id", calculation_plan_id)
        object.__setattr__(value, "calculation_plan_revision", calculation_plan_revision)
        object.__setattr__(
            value,
            "execution_snapshot_semantics",
            freeze_mapping(
                execution_snapshot_semantics, "execution_snapshot_semantics"
            ),
        )
        object.__setattr__(value, "confirmer_id", confirmer_id)
        object.__setattr__(
            value,
            "confirmer_evidence",
            freeze_mapping(confirmer_evidence, "confirmer_evidence"),
        )
        object.__setattr__(value, "decision", decision)
        object.__setattr__(value, "schema_version", APPROVAL_SCHEMA_VERSION)
        object.__setattr__(
            value,
            "operational_confirmation_id",
            identity_for("operational-confirmation", value.authority_payload()),
        )
        return value

    @classmethod
    def for_snapshot(
        cls,
        runtime_store: SQLiteRuntimeStore,
        snapshot: ExecutionSnapshot,
        *,
        confirmer_id: str,
        confirmer_evidence: Mapping[str, object],
        decision: ApprovalDecision = ApprovalDecision.APPROVED,
    ) -> ExactOperationalConfirmation:
        _assert_execution_snapshot_closed(runtime_store, snapshot)
        return cls._from_values(
            execution_snapshot_id=snapshot.execution_snapshot_id,
            attempt_id=snapshot.attempt_id,
            calculation_plan_id=snapshot.calculation_plan_id,
            calculation_plan_revision=snapshot.calculation_plan_revision,
            execution_snapshot_semantics=snapshot.semantic_payload(),
            confirmer_id=confirmer_id,
            confirmer_evidence=confirmer_evidence,
            decision=decision,
        )

    def authority_payload(self) -> Mapping[str, object]:
        return freeze_mapping(
            {
                "execution_snapshot_id": self.execution_snapshot_id,
                "attempt_id": self.attempt_id,
                "calculation_plan_id": self.calculation_plan_id,
                "calculation_plan_revision": self.calculation_plan_revision,
                "execution_snapshot_semantics": self.execution_snapshot_semantics,
                "confirmer_id": self.confirmer_id,
                "confirmer_evidence": self.confirmer_evidence,
                "decision": self.decision.value,
            },
            "Exact Operational Confirmation authority",
        )

    def assert_current(
        self,
        runtime_store: SQLiteRuntimeStore,
        snapshot: ExecutionSnapshot,
    ) -> None:
        _assert_execution_snapshot_closed(runtime_store, snapshot)
        observed = {
            "execution_snapshot_id": snapshot.execution_snapshot_id,
            "attempt_id": snapshot.attempt_id,
            "calculation_plan_id": snapshot.calculation_plan_id,
            "calculation_plan_revision": snapshot.calculation_plan_revision,
            "execution_snapshot_semantics": snapshot.semantic_payload(),
        }
        for key, value in observed.items():
            if self.authority_payload()[key] != value:
                raise StaleApprovalError(f"Operational Confirmation {key} is stale")
        if identity_for("operational-confirmation", self.authority_payload()) != self.operational_confirmation_id:
            raise ApprovalConflictError("Operational Confirmation identity is stale")
        if self.decision is not ApprovalDecision.APPROVED:
            raise ApprovalRejectedError("Operational Confirmation is not approved")

    def persisted_payload(self) -> Mapping[str, object]:
        return freeze_mapping(
            {
                "schema_version": self.schema_version,
                "evidence_kind": "operational-confirmation",
                "operational_confirmation_id": self.operational_confirmation_id,
                **dict(self.authority_payload()),
            },
            "persisted Operational Confirmation",
        )


class ApprovalError(Exception):
    """Base failure for approval authority validation."""


class ApprovalConflictError(ApprovalError):
    """Evidence identity or binding conflicts with its authority payload."""


class StaleApprovalError(ApprovalError):
    """Approval evidence no longer matches the current semantic object."""


class ApprovalScopeError(ApprovalError):
    """An Attempt or object is outside the exact authority scope."""


class ApprovalRejectedError(ApprovalError):
    """The recorded human decision is not approved."""


def _assert_execution_snapshot_closed(
    runtime_store: SQLiteRuntimeStore,
    snapshot: ExecutionSnapshot,
) -> None:
    """Rebuild one snapshot through Execution's public closure boundary."""

    if not isinstance(runtime_store, SQLiteRuntimeStore):
        raise ApprovalValueError("runtime_store must be a public Core SQLiteRuntimeStore")
    if not isinstance(snapshot, ExecutionSnapshot):
        raise ApprovalValueError("snapshot must be a public ExecutionSnapshot")
    try:
        rebuilt = prepare_execution_snapshot(
            runtime_store,
            attempt_id=snapshot.attempt_id,
            calculation_plan_id=snapshot.calculation_plan_id,
            resource_spec_id=snapshot.resolved_resource_request.resource_spec_id,
            prepared_input_binding=snapshot.prepared_input_binding,
            resolved_resource_request=snapshot.resolved_resource_request,
            resolved_server_profile=snapshot.resolved_server_profile,
            workspace_binding=snapshot.workspace_binding,
            pbs_template_binding=snapshot.pbs_template_binding,
            adapter_contract_version=snapshot.adapter_contract_version,
        )
    except (CoreValidationError, RuntimeStoreError, ExecutionValueError) as exc:
        raise ApprovalConflictError(
            "ExecutionSnapshot is not closed over its current public Execution records"
        ) from exc
    if (
        rebuilt.execution_snapshot_id != snapshot.execution_snapshot_id
        or rebuilt.semantic_payload() != snapshot.semantic_payload()
    ):
        raise ApprovalConflictError(
            "ExecutionSnapshot identity is stale for its effect-relevant semantics"
        )


def validate_effect_authority(
    *,
    runtime_store: SQLiteRuntimeStore,
    attempt: Attempt,
    plan: CalculationPlan,
    displayed_semantic_meaning: Mapping[str, object],
    scientific_approval: ScientificApproval,
    batch_submit_approval: BatchSubmitApproval,
    execution_snapshot: ExecutionSnapshot,
    operational_confirmation: ExactOperationalConfirmation,
) -> None:
    """Purely validate one exact, current, unspliced pre-effect authority chain."""

    if not isinstance(runtime_store, SQLiteRuntimeStore):
        raise ApprovalValueError("runtime_store must be a public Core SQLiteRuntimeStore")
    if not isinstance(attempt, Attempt):
        raise ApprovalValueError("attempt must be a public Core Attempt")
    if not isinstance(plan, CalculationPlan):
        raise ApprovalValueError("plan must be a public Core CalculationPlan")
    if not isinstance(scientific_approval, ScientificApproval):
        raise ApprovalValueError("scientific_approval must be a ScientificApproval")
    if not isinstance(batch_submit_approval, BatchSubmitApproval):
        raise ApprovalValueError("batch_submit_approval must be a BatchSubmitApproval")
    if not isinstance(execution_snapshot, ExecutionSnapshot):
        raise ApprovalValueError("execution_snapshot must be an ExecutionSnapshot")
    if not isinstance(operational_confirmation, ExactOperationalConfirmation):
        raise ApprovalValueError(
            "operational_confirmation must be an ExactOperationalConfirmation"
        )
    if runtime_store.load_attempt(attempt.attempt_id) != attempt:
        raise ApprovalConflictError("Attempt differs from its current durable Core record")
    if runtime_store.load_calculation_plan(plan.calculation_plan_id) != plan:
        raise ApprovalConflictError("CalculationPlan differs from its current durable Core record")
    if runtime_store.attempt_state(attempt.attempt_id) is not AttemptState.PLANNED:
        raise ApprovalScopeError("effect authority validation requires a PLANNED Attempt")
    scientific_approval.assert_current(
        plan, displayed_semantic_meaning=displayed_semantic_meaning
    )
    member = batch_submit_approval.member_for(attempt.attempt_id)
    expected_member = BatchApprovalMember(
        attempt_id=attempt.attempt_id,
        task_id=attempt.task_id,
        calculation_plan_id=plan.calculation_plan_id,
        calculation_plan_revision=plan.revision,
        scientific_approval_id=scientific_approval.scientific_approval_id,
    )
    if member != expected_member:
        raise ApprovalConflictError("Batch member cross-splices Attempt, plan, or approval")
    if execution_snapshot.attempt_id != attempt.attempt_id:
        raise ApprovalConflictError("ExecutionSnapshot belongs to another Attempt")
    if execution_snapshot.calculation_plan_id != plan.calculation_plan_id:
        raise ApprovalConflictError("ExecutionSnapshot belongs to another CalculationPlan")
    if execution_snapshot.calculation_plan_revision != plan.revision:
        raise StaleApprovalError("ExecutionSnapshot plan revision is stale")
    operational_confirmation.assert_current(runtime_store, execution_snapshot)
