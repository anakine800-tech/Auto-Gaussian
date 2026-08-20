"""Immutable value records for the frozen Auto-G16 v3 Workflow contract."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
import json
from math import isfinite
from typing import Final
from uuid import UUID, uuid5

from auto_g16.core import AttemptState


WORKFLOW_SCHEMA_VERSION: Final = 1
_WORKFLOW_NAMESPACE: Final = UUID("538d5a9e-2e85-5d36-a437-b821f8597c93")
_TERMINAL_STATES: Final = frozenset(
    {AttemptState.SUCCEEDED, AttemptState.FAILED, AttemptState.NOT_SUBMITTED}
)


class WorkflowValueError(ValueError):
    """A Workflow value violates the frozen public contract."""


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
            return self._items == _freeze_mapping(other, "mapping")._items
        except WorkflowValueError:
            return False

    def __hash__(self) -> int:
        return hash(self._items)


def _text(value: object, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or "\x00" in value
    ):
        raise WorkflowValueError(
            f"{field_name} must be a non-empty string without surrounding whitespace or NUL"
        )
    return value


def _positive_integer(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise WorkflowValueError(f"{field_name} must be a positive integer")
    return value


def _text_tuple(
    value: Sequence[str], field_name: str, *, allow_empty: bool = True
) -> tuple[str, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise WorkflowValueError(f"{field_name} must be a finite sequence")
    result = tuple(_text(item, f"{field_name}[{index}]") for index, item in enumerate(value))
    if not allow_empty and not result:
        raise WorkflowValueError(f"{field_name} must not be empty")
    if len(result) != len(set(result)):
        raise WorkflowValueError(f"{field_name} must not contain duplicates")
    return tuple(sorted(result))


def _freeze_value(value: object, path: str, active: set[int]) -> object:
    if value is None or type(value) in {bool, int, str}:
        return value
    if type(value) is float:
        if not isfinite(value):
            raise WorkflowValueError(f"{path} must not contain a non-finite float")
        return value
    if isinstance(value, Mapping):
        identity = id(value)
        if identity in active:
            raise WorkflowValueError(f"{path} must not contain a container cycle")
        active.add(identity)
        try:
            items: list[tuple[str, object]] = []
            for key, item in value.items():
                if not isinstance(key, str) or not key:
                    raise WorkflowValueError(f"{path} keys must be non-empty strings")
                items.append((key, _freeze_value(item, f"{path}.{key}", active)))
            return _FrozenMapping(tuple(sorted(items, key=lambda pair: pair[0])))
        finally:
            active.remove(identity)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        identity = id(value)
        if identity in active:
            raise WorkflowValueError(f"{path} must not contain a container cycle")
        active.add(identity)
        try:
            return tuple(
                _freeze_value(item, f"{path}[{index}]", active)
                for index, item in enumerate(value)
            )
        finally:
            active.remove(identity)
    raise WorkflowValueError(
        f"{path} contains unsupported value type {type(value).__name__}"
    )


def _freeze_mapping(value: Mapping[str, object], field_name: str) -> _FrozenMapping:
    frozen = _freeze_value(value, field_name, set())
    if not isinstance(frozen, _FrozenMapping):
        raise WorkflowValueError(f"{field_name} must be a mapping")
    return frozen


def _plain(value: object) -> object:
    if isinstance(value, AttemptState):
        return value.value
    if isinstance(value, Mapping):
        return {key: _plain(value[key]) for key in sorted(value)}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_plain(item) for item in value]
    return value


def _canonical_node(value: object) -> object:
    if value is None:
        return ["null", None]
    if type(value) is bool:
        return ["boolean", value]
    if type(value) is int:
        return ["integer", value]
    if type(value) is float:
        if not isfinite(value):
            raise WorkflowValueError("identity payload contains a non-finite float")
        return ["float", value]
    if type(value) is str:
        return ["string", value]
    if isinstance(value, AttemptState):
        return ["string", value.value]
    if isinstance(value, Mapping):
        return [
            "mapping",
            [[key, _canonical_node(value[key])] for key in sorted(value)],
        ]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return ["sequence", [_canonical_node(item) for item in value]]
    raise WorkflowValueError(
        f"identity payload contains unsupported value type {type(value).__name__}"
    )


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        _canonical_node(value),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=False,
    ).encode("utf-8")


def _identity(domain: str, payload: Mapping[str, object]) -> str:
    if domain not in {"workflow-definition", "condition-decision", "human-gate-decision"}:
        raise WorkflowValueError(f"unsupported Workflow identity domain {domain!r}")
    namespace = uuid5(
        _WORKFLOW_NAMESPACE,
        f"auto_g16.workflow/v{WORKFLOW_SCHEMA_VERSION}/{domain}",
    )
    name = _canonical_bytes(
        {
            "schema_version": WORKFLOW_SCHEMA_VERSION,
            "domain": domain,
            "authority": payload,
        }
    ).decode("utf-8")
    return str(uuid5(namespace, name))


@dataclass(frozen=True, slots=True, kw_only=True)
class Node:
    node_id: str
    task_id: str
    calculation_plan_id: str
    calculation_plan_revision: int
    node_kind: str
    input_roles: tuple[str, ...]
    output_roles: tuple[str, ...]

    def __post_init__(self) -> None:
        _text(self.node_id, "node_id")
        _text(self.task_id, "task_id")
        _text(self.calculation_plan_id, "calculation_plan_id")
        _positive_integer(self.calculation_plan_revision, "calculation_plan_revision")
        _text(self.node_kind, "node_kind")
        object.__setattr__(self, "input_roles", _text_tuple(self.input_roles, "input_roles"))
        object.__setattr__(self, "output_roles", _text_tuple(self.output_roles, "output_roles"))

    def _payload(self) -> dict[str, object]:
        return {
            "node_id": self.node_id,
            "task_id": self.task_id,
            "calculation_plan_id": self.calculation_plan_id,
            "calculation_plan_revision": self.calculation_plan_revision,
            "node_kind": self.node_kind,
            "input_roles": self.input_roles,
            "output_roles": self.output_roles,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class Edge:
    edge_id: str
    source_node_id: str
    source_output_role: str
    target_node_id: str
    target_input_role: str
    condition_id: str | None
    branch: str

    def __post_init__(self) -> None:
        _text(self.edge_id, "edge_id")
        _text(self.source_node_id, "source_node_id")
        _text(self.source_output_role, "source_output_role")
        _text(self.target_node_id, "target_node_id")
        _text(self.target_input_role, "target_input_role")
        if self.condition_id is not None:
            _text(self.condition_id, "condition_id")
        if self.branch not in {"always", "true", "false"}:
            raise WorkflowValueError("branch must be always, true, or false")

    def _payload(self) -> dict[str, object]:
        return {
            "edge_id": self.edge_id,
            "source_node_id": self.source_node_id,
            "source_output_role": self.source_output_role,
            "target_node_id": self.target_node_id,
            "target_input_role": self.target_input_role,
            "condition_id": self.condition_id,
            "branch": self.branch,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class Map:
    map_id: str
    source_node_id: str
    source_output_role: str
    items: tuple[tuple[str, str, str], ...]

    def __post_init__(self) -> None:
        _text(self.map_id, "map_id")
        _text(self.source_node_id, "source_node_id")
        _text(self.source_output_role, "source_output_role")
        if not isinstance(self.items, Sequence) or isinstance(
            self.items, (str, bytes, bytearray)
        ):
            raise WorkflowValueError("items must be a finite sequence")
        normalized: list[tuple[str, str, str]] = []
        for index, item in enumerate(self.items):
            if not isinstance(item, Sequence) or isinstance(item, (str, bytes, bytearray)) or len(item) != 3:
                raise WorkflowValueError(f"items[{index}] must be a three-item tuple")
            normalized.append(
                (
                    _text(item[0], f"items[{index}].item_key"),
                    _text(item[1], f"items[{index}].target_node_id"),
                    _text(item[2], f"items[{index}].target_input_role"),
                )
            )
        if not normalized:
            raise WorkflowValueError("items must not be empty")
        keys = [item[0] for item in normalized]
        if len(keys) != len(set(keys)):
            raise WorkflowValueError("Map item keys must be unique")
        object.__setattr__(self, "items", tuple(sorted(normalized, key=lambda item: item[0])))

    def _payload(self) -> dict[str, object]:
        return {
            "map_id": self.map_id,
            "source_node_id": self.source_node_id,
            "source_output_role": self.source_output_role,
            "items": self.items,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class Condition:
    condition_id: str
    source_node_id: str
    predicate: str
    expected_states: tuple[AttemptState, ...]
    true_edge_ids: tuple[str, ...]
    false_edge_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _text(self.condition_id, "condition_id")
        _text(self.source_node_id, "source_node_id")
        if self.predicate != "attempt_state_in":
            raise WorkflowValueError("predicate must be attempt_state_in")
        if not isinstance(self.expected_states, Sequence) or isinstance(
            self.expected_states, (str, bytes, bytearray)
        ):
            raise WorkflowValueError("expected_states must be a finite sequence")
        states: list[AttemptState] = []
        for value in self.expected_states:
            try:
                state = value if isinstance(value, AttemptState) else AttemptState(value)
            except (TypeError, ValueError) as exc:
                raise WorkflowValueError("expected_states contains an invalid AttemptState") from exc
            if state not in _TERMINAL_STATES:
                raise WorkflowValueError("expected_states must contain only closed terminal states")
            states.append(state)
        if not states or len(states) != len(set(states)):
            raise WorkflowValueError("expected_states must be non-empty and unique")
        object.__setattr__(self, "expected_states", tuple(sorted(states, key=lambda item: item.value)))
        object.__setattr__(self, "true_edge_ids", _text_tuple(self.true_edge_ids, "true_edge_ids"))
        object.__setattr__(self, "false_edge_ids", _text_tuple(self.false_edge_ids, "false_edge_ids"))
        if set(self.true_edge_ids).intersection(self.false_edge_ids):
            raise WorkflowValueError("true_edge_ids and false_edge_ids must be disjoint")
        if not self.true_edge_ids and not self.false_edge_ids:
            raise WorkflowValueError("a Condition must declare at least one branch Edge")

    def _payload(self) -> dict[str, object]:
        return {
            "condition_id": self.condition_id,
            "source_node_id": self.source_node_id,
            "predicate": self.predicate,
            "expected_states": self.expected_states,
            "true_edge_ids": self.true_edge_ids,
            "false_edge_ids": self.false_edge_ids,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class HumanGate:
    human_gate_id: str
    target_node_ids: tuple[str, ...]
    prompt: str

    def __post_init__(self) -> None:
        _text(self.human_gate_id, "human_gate_id")
        object.__setattr__(
            self,
            "target_node_ids",
            _text_tuple(self.target_node_ids, "target_node_ids", allow_empty=False),
        )
        _text(self.prompt, "prompt")

    def _payload(self) -> dict[str, object]:
        return {
            "human_gate_id": self.human_gate_id,
            "target_node_ids": self.target_node_ids,
            "prompt": self.prompt,
        }


@dataclass(frozen=True, slots=True, kw_only=True, init=False)
class WorkflowDefinition:
    schema_version: int
    workflow_definition_id: str = field(init=False)
    workflow_run_id: str
    workflow_name: str
    nodes: tuple[Node, ...]
    edges: tuple[Edge, ...]
    maps: tuple[Map, ...]
    conditions: tuple[Condition, ...]
    human_gates: tuple[HumanGate, ...]

    def __init__(
        self,
        *,
        schema_version: int,
        workflow_run_id: str,
        workflow_name: str,
        nodes: Sequence[Node],
        edges: Sequence[Edge] = (),
        maps: Sequence[Map] = (),
        conditions: Sequence[Condition] = (),
        human_gates: Sequence[HumanGate] = (),
    ) -> None:
        if schema_version != WORKFLOW_SCHEMA_VERSION:
            raise WorkflowValueError("schema_version must be 1")
        object.__setattr__(self, "schema_version", schema_version)
        object.__setattr__(self, "workflow_run_id", _text(workflow_run_id, "workflow_run_id"))
        object.__setattr__(self, "workflow_name", _text(workflow_name, "workflow_name"))
        normalized = (
            _component_tuple(nodes, Node, "nodes", "node_id", allow_empty=False),
            _component_tuple(edges, Edge, "edges", "edge_id"),
            _component_tuple(maps, Map, "maps", "map_id"),
            _component_tuple(conditions, Condition, "conditions", "condition_id"),
            _component_tuple(human_gates, HumanGate, "human_gates", "human_gate_id"),
        )
        for name, value in zip(
            ("nodes", "edges", "maps", "conditions", "human_gates"), normalized
        ):
            object.__setattr__(self, name, value)
        object.__setattr__(
            self,
            "workflow_definition_id",
            _identity("workflow-definition", self._authority_payload()),
        )

    def _authority_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "workflow_run_id": self.workflow_run_id,
            "workflow_name": self.workflow_name,
            "nodes": tuple(item._payload() for item in self.nodes),
            "edges": tuple(item._payload() for item in self.edges),
            "maps": tuple(item._payload() for item in self.maps),
            "conditions": tuple(item._payload() for item in self.conditions),
            "human_gates": tuple(item._payload() for item in self.human_gates),
        }

    def _payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "workflow_definition_id": self.workflow_definition_id,
            **self._authority_payload(),
        }

    @classmethod
    def _from_values(cls, *, workflow_definition_id: str, **values: object) -> WorkflowDefinition:
        record = cls(**values)  # type: ignore[arg-type]
        if _text(workflow_definition_id, "workflow_definition_id") != record.workflow_definition_id:
            raise WorkflowValueError("WorkflowDefinition identity does not match its complete payload")
        return record


def _component_tuple(
    value: Sequence[object],
    expected_type: type[object],
    field_name: str,
    id_field: str,
    *,
    allow_empty: bool = True,
) -> tuple[object, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise WorkflowValueError(f"{field_name} must be a finite sequence")
    result = tuple(value)
    if not allow_empty and not result:
        raise WorkflowValueError(f"{field_name} must not be empty")
    if not all(isinstance(item, expected_type) for item in result):
        raise WorkflowValueError(f"{field_name} contains an invalid component type")
    identities = [getattr(item, id_field) for item in result]
    if len(identities) != len(set(identities)):
        raise WorkflowValueError(f"{field_name} contains duplicate local identifiers")
    return tuple(sorted(result, key=lambda item: getattr(item, id_field)))


@dataclass(frozen=True, slots=True, kw_only=True)
class WorkflowEvaluationInput:
    workflow_definition_id: str
    node_attempt_ids: Mapping[str, object] = field(repr=False)

    def __post_init__(self) -> None:
        _text(self.workflow_definition_id, "workflow_definition_id")
        if not isinstance(self.node_attempt_ids, Mapping):
            raise WorkflowValueError("node_attempt_ids must be a mapping")
        normalized: dict[str, object] = {}
        for node_id, attempt_id in self.node_attempt_ids.items():
            normalized[_text(node_id, "node_attempt_ids key")] = _text(
                attempt_id, f"node_attempt_ids[{node_id!r}]"
            )
        object.__setattr__(
            self, "node_attempt_ids", _freeze_mapping(normalized, "node_attempt_ids")
        )

    def _payload(self) -> dict[str, object]:
        return {
            "workflow_definition_id": self.workflow_definition_id,
            "node_attempt_ids": self.node_attempt_ids,
        }


@dataclass(frozen=True, slots=True, kw_only=True, init=False)
class ConditionDecision:
    condition_decision_id: str = field(init=False)
    workflow_definition_id: str
    workflow_run_id: str
    condition_id: str
    node_id: str
    attempt_id: str
    observed_state: AttemptState
    selected_edge_ids: tuple[str, ...]

    def __init__(self) -> None:
        raise TypeError("ConditionDecision is created only by record_condition_decision")

    @classmethod
    def _create(
        cls,
        *,
        workflow_definition_id: str,
        workflow_run_id: str,
        condition_id: str,
        node_id: str,
        attempt_id: str,
        observed_state: AttemptState,
        selected_edge_ids: Sequence[str],
        condition_decision_id: str | None = None,
    ) -> ConditionDecision:
        value = object.__new__(cls)
        for name, item in (
            ("workflow_definition_id", workflow_definition_id),
            ("workflow_run_id", workflow_run_id),
            ("condition_id", condition_id),
            ("node_id", node_id),
            ("attempt_id", attempt_id),
        ):
            object.__setattr__(value, name, _text(item, name))
        if not isinstance(observed_state, AttemptState) or observed_state not in _TERMINAL_STATES:
            raise WorkflowValueError("observed_state must be a closed terminal AttemptState")
        object.__setattr__(value, "observed_state", observed_state)
        object.__setattr__(
            value,
            "selected_edge_ids",
            _text_tuple(selected_edge_ids, "selected_edge_ids"),
        )
        expected_id = _identity("condition-decision", value._authority_payload())
        if condition_decision_id is not None and _text(
            condition_decision_id, "condition_decision_id"
        ) != expected_id:
            raise WorkflowValueError("ConditionDecision identity does not match its payload")
        object.__setattr__(value, "condition_decision_id", expected_id)
        return value

    def _authority_payload(self) -> dict[str, object]:
        return {
            "workflow_definition_id": self.workflow_definition_id,
            "workflow_run_id": self.workflow_run_id,
            "condition_id": self.condition_id,
            "node_id": self.node_id,
            "attempt_id": self.attempt_id,
            "observed_state": self.observed_state,
            "selected_edge_ids": self.selected_edge_ids,
        }

    def _payload(self) -> dict[str, object]:
        return {"condition_decision_id": self.condition_decision_id, **self._authority_payload()}


@dataclass(frozen=True, slots=True, kw_only=True, init=False)
class HumanGateDecision:
    human_gate_decision_id: str = field(init=False)
    workflow_definition_id: str
    workflow_run_id: str
    human_gate_id: str
    decision: str
    reviewer_id: str
    review_evidence: Mapping[str, object] = field(repr=False)

    def __init__(self) -> None:
        raise TypeError("HumanGateDecision is created only by record_human_gate_decision")

    @classmethod
    def _create(
        cls,
        *,
        workflow_definition_id: str,
        workflow_run_id: str,
        human_gate_id: str,
        decision: str,
        reviewer_id: str,
        review_evidence: Mapping[str, object],
        human_gate_decision_id: str | None = None,
    ) -> HumanGateDecision:
        value = object.__new__(cls)
        for name, item in (
            ("workflow_definition_id", workflow_definition_id),
            ("workflow_run_id", workflow_run_id),
            ("human_gate_id", human_gate_id),
            ("reviewer_id", reviewer_id),
        ):
            object.__setattr__(value, name, _text(item, name))
        if decision not in {"approved", "rejected"}:
            raise WorkflowValueError("decision must be approved or rejected")
        object.__setattr__(value, "decision", decision)
        object.__setattr__(
            value,
            "review_evidence",
            _freeze_mapping(review_evidence, "review_evidence"),
        )
        expected_id = _identity("human-gate-decision", value._authority_payload())
        if human_gate_decision_id is not None and _text(
            human_gate_decision_id, "human_gate_decision_id"
        ) != expected_id:
            raise WorkflowValueError("HumanGateDecision identity does not match its payload")
        object.__setattr__(value, "human_gate_decision_id", expected_id)
        return value

    def _authority_payload(self) -> dict[str, object]:
        return {
            "workflow_definition_id": self.workflow_definition_id,
            "workflow_run_id": self.workflow_run_id,
            "human_gate_id": self.human_gate_id,
            "decision": self.decision,
            "reviewer_id": self.reviewer_id,
            "review_evidence": self.review_evidence,
        }

    def _payload(self) -> dict[str, object]:
        return {"human_gate_decision_id": self.human_gate_decision_id, **self._authority_payload()}


@dataclass(frozen=True, slots=True, kw_only=True)
class WorkflowRunView:
    workflow_definition_id: str
    workflow_run_id: str
    active_node_ids: tuple[str, ...]
    ready_node_ids: tuple[str, ...]
    pending_node_ids: tuple[str, ...]
    blocked_node_ids: tuple[str, ...]
    terminal_node_ids: tuple[str, ...]
    condition_decision_ids: tuple[str, ...]
    human_gate_decision_ids: tuple[str, ...]
    run_outcome: str

    def __post_init__(self) -> None:
        _text(self.workflow_definition_id, "workflow_definition_id")
        _text(self.workflow_run_id, "workflow_run_id")
        for name in (
            "active_node_ids",
            "ready_node_ids",
            "pending_node_ids",
            "blocked_node_ids",
            "terminal_node_ids",
            "condition_decision_ids",
            "human_gate_decision_ids",
        ):
            object.__setattr__(self, name, _text_tuple(getattr(self, name), name))
        if self.run_outcome not in {"pending", "active", "blocked", "completed"}:
            raise WorkflowValueError("run_outcome is invalid")


def _payload_text(value: Mapping[str, object]) -> str:
    return json.dumps(
        _plain(value),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )
