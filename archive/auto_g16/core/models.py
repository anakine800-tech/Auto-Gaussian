"""Immutable value records for the Auto-G16 v3 clean runtime core."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from math import isfinite
from typing import Literal, TypeAlias, cast


_CanonicalRecord: TypeAlias = tuple[
    Literal["record"], tuple[tuple[str, "_CanonicalValue"], ...]
]
_CanonicalValue: TypeAlias = (
    tuple[Literal["null"], None]
    | tuple[Literal["boolean"], bool]
    | tuple[Literal["integer"], int]
    | tuple[Literal["float"], float]
    | tuple[Literal["string"], str]
    | tuple[Literal["sequence"], tuple["_CanonicalValue", ...]]
    | _CanonicalRecord
)


class CoreValidationError(ValueError):
    """A clean-core value does not satisfy the public runtime contract."""


def _require_text(value: object, field_name: str) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise CoreValidationError(
            f"{field_name} must be a non-empty string without surrounding whitespace"
        )


def _require_positive_integer(value: object, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise CoreValidationError(f"{field_name} must be a positive integer")


def _freeze_value(value: object, path: str, active_containers: set[int]) -> _CanonicalValue:
    if value is None:
        return ("null", None)
    if type(value) is bool:
        return ("boolean", value)
    if type(value) is int:
        return ("integer", value)
    if type(value) is float:
        if not isfinite(value):
            raise CoreValidationError(f"{path} must not contain a non-finite float")
        return ("float", value)
    if type(value) is str:
        return ("string", value)
    if isinstance(value, (Mapping, list, tuple)):
        identity = id(value)
        if identity in active_containers:
            raise CoreValidationError(f"{path} must not contain a container cycle")
        active_containers.add(identity)
        try:
            if isinstance(value, Mapping):
                items: list[tuple[str, _CanonicalValue]] = []
                for key, item in value.items():
                    if not isinstance(key, str):
                        raise CoreValidationError(
                            f"{path} must contain only string mapping keys"
                        )
                    items.append(
                        (key, _freeze_value(item, f"{path}.{key}", active_containers))
                    )
                return ("record", tuple(sorted(items, key=lambda pair: pair[0])))
            return (
                "sequence",
                tuple(
                    _freeze_value(item, f"{path}[{index}]", active_containers)
                    for index, item in enumerate(value)
                ),
            )
        finally:
            active_containers.remove(identity)
    raise CoreValidationError(
        f"{path} contains unsupported value type {type(value).__name__}"
    )


def _validate_frozen_value(value: object, path: str) -> _CanonicalValue:
    if not isinstance(value, tuple) or len(value) != 2 or not isinstance(value[0], str):
        raise CoreValidationError(f"{path} is not a canonical tagged value")
    tag, payload = value
    scalar_types = {
        "null": type(None),
        "boolean": bool,
        "integer": int,
        "float": float,
        "string": str,
    }
    if tag in scalar_types:
        if type(payload) is not scalar_types[tag]:
            raise CoreValidationError(f"{path} has an invalid {tag} payload")
        if tag == "float" and not isfinite(payload):
            raise CoreValidationError(f"{path} must not contain a non-finite float")
        return cast(_CanonicalValue, value)
    if tag == "sequence":
        if not isinstance(payload, tuple):
            raise CoreValidationError(f"{path} has an invalid sequence payload")
        for index, item in enumerate(payload):
            _validate_frozen_value(item, f"{path}[{index}]")
        return cast(_CanonicalValue, value)
    if tag == "record":
        if not isinstance(payload, tuple):
            raise CoreValidationError(f"{path} has an invalid record payload")
        keys: list[str] = []
        for index, item in enumerate(payload):
            if not isinstance(item, tuple) or len(item) != 2 or not isinstance(item[0], str):
                raise CoreValidationError(f"{path} has an invalid record item at {index}")
            key, item_value = item
            keys.append(key)
            _validate_frozen_value(item_value, f"{path}.{key}")
        if keys != sorted(keys) or len(keys) != len(set(keys)):
            raise CoreValidationError(f"{path} record keys must be unique and sorted")
        return cast(_CanonicalValue, value)
    raise CoreValidationError(f"{path} has unsupported canonical tag {tag!r}")


def _freeze_record(value: object, field_name: str) -> _CanonicalRecord:
    if not isinstance(value, Mapping):
        raise CoreValidationError(f"{field_name} must be a mapping")
    if isinstance(value, _SemanticMapping):
        return value._canonical_record()
    frozen = _freeze_value(value, field_name, set())
    if frozen[0] != "record":
        raise CoreValidationError(f"{field_name} must be a mapping")
    return cast(_CanonicalRecord, frozen)


def _semantic_value(value: _CanonicalValue) -> object:
    tag, payload = value
    if tag in {"null", "boolean", "integer", "float", "string"}:
        return payload
    if tag == "sequence":
        return tuple(_semantic_value(item) for item in payload)
    return _SemanticMapping(cast(_CanonicalRecord, value))


class _SemanticMapping(Mapping[str, object]):
    """Immutable semantic view backed by the private canonical representation."""

    __slots__ = ("__canonical",)

    def __init__(self, canonical: _CanonicalRecord) -> None:
        object.__setattr__(self, "_SemanticMapping__canonical", canonical)

    def __setattr__(self, _name: str, _value: object) -> None:
        raise TypeError("semantic payload mappings are immutable")

    def __getitem__(self, key: str) -> object:
        for item_key, value in self.__canonical[1]:
            if item_key == key:
                return _semantic_value(value)
        raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        return (key for key, _value in self.__canonical[1])

    def __len__(self) -> int:
        return len(self.__canonical[1])

    def __repr__(self) -> str:
        return repr(dict(self.items()))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Mapping):
            return False
        try:
            return self.__canonical == _freeze_record(other, "payload")
        except CoreValidationError:
            return False

    def __hash__(self) -> int:
        return hash(self.__canonical)

    def _canonical_record(self) -> _CanonicalRecord:
        return self.__canonical


def _semantic_record(value: object, field_name: str) -> Mapping[str, object]:
    return _SemanticMapping(_freeze_record(value, field_name))


def _semantic_record_from_encoded(value: object, field_name: str) -> Mapping[str, object]:
    canonical = _validate_frozen_value(value, field_name)
    if canonical[0] != "record":
        raise CoreValidationError(f"{field_name} must encode a mapping")
    return _SemanticMapping(cast(_CanonicalRecord, canonical))


@dataclass(frozen=True, slots=True, kw_only=True)
class Project:
    project_id: str

    def __post_init__(self) -> None:
        _require_text(self.project_id, "project_id")


@dataclass(frozen=True, slots=True, kw_only=True)
class WorkflowRun:
    workflow_run_id: str
    project_id: str
    workflow_name: str

    def __post_init__(self) -> None:
        _require_text(self.workflow_run_id, "workflow_run_id")
        _require_text(self.project_id, "project_id")
        _require_text(self.workflow_name, "workflow_name")


@dataclass(frozen=True, slots=True, kw_only=True)
class Batch:
    batch_id: str
    workflow_run_id: str
    purpose: str

    def __post_init__(self) -> None:
        _require_text(self.batch_id, "batch_id")
        _require_text(self.workflow_run_id, "workflow_run_id")
        _require_text(self.purpose, "purpose")


@dataclass(frozen=True, slots=True, kw_only=True)
class Task:
    task_id: str
    workflow_run_id: str
    task_kind: str
    batch_id: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.task_id, "task_id")
        _require_text(self.workflow_run_id, "workflow_run_id")
        _require_text(self.task_kind, "task_kind")
        if self.batch_id is not None:
            _require_text(self.batch_id, "batch_id")


@dataclass(frozen=True, slots=True, kw_only=True)
class Attempt:
    attempt_id: str
    task_id: str
    ordinal: int

    def __post_init__(self) -> None:
        _require_text(self.attempt_id, "attempt_id")
        _require_text(self.task_id, "task_id")
        _require_positive_integer(self.ordinal, "ordinal")


@dataclass(frozen=True, slots=True, kw_only=True)
class CalculationPlan:
    calculation_plan_id: str
    task_id: str
    revision: int
    intent: Mapping[str, object] = field(repr=False)

    def __post_init__(self) -> None:
        _require_text(self.calculation_plan_id, "calculation_plan_id")
        _require_text(self.task_id, "task_id")
        _require_positive_integer(self.revision, "revision")
        object.__setattr__(self, "intent", _semantic_record(self.intent, "intent"))


@dataclass(frozen=True, slots=True, kw_only=True)
class ResourceSpec:
    resource_spec_id: str
    task_id: str
    resources: Mapping[str, object] = field(repr=False)

    def __post_init__(self) -> None:
        _require_text(self.resource_spec_id, "resource_spec_id")
        _require_text(self.task_id, "task_id")
        object.__setattr__(self, "resources", _semantic_record(self.resources, "resources"))


@dataclass(frozen=True, slots=True, kw_only=True)
class Observation:
    observation_id: str
    attempt_id: str
    observation_type: str
    data: Mapping[str, object] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        _require_text(self.observation_id, "observation_id")
        _require_text(self.attempt_id, "attempt_id")
        _require_text(self.observation_type, "observation_type")
        object.__setattr__(self, "data", _semantic_record(self.data, "data"))


@dataclass(frozen=True, slots=True, kw_only=True)
class Result:
    result_id: str
    attempt_id: str
    result_type: str
    data: Mapping[str, object] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        _require_text(self.result_id, "result_id")
        _require_text(self.attempt_id, "attempt_id")
        _require_text(self.result_type, "result_type")
        object.__setattr__(self, "data", _semantic_record(self.data, "data"))


@dataclass(frozen=True, slots=True, kw_only=True)
class RecoveryProposal:
    recovery_proposal_id: str
    attempt_id: str
    reason: str
    proposed_calculation_plan_id: str

    def __post_init__(self) -> None:
        _require_text(self.recovery_proposal_id, "recovery_proposal_id")
        _require_text(self.attempt_id, "attempt_id")
        _require_text(self.reason, "reason")
        _require_text(self.proposed_calculation_plan_id, "proposed_calculation_plan_id")
