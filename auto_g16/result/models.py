"""Immutable public records for the Auto-G16 v3 result boundary."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from math import isfinite
from types import MappingProxyType
from typing import Final
from uuid import UUID, uuid5


NS_INPUT_BINDING: Final = UUID("2caa8c92-f020-5326-b999-f591dcde6559")
NS_OUTPUT_ENVELOPE: Final = UUID("84c71351-81f8-5143-84b4-12dc8e016c16")
NS_PARSED_RESULT: Final = UUID("698489ce-1b85-5ab5-8991-d8a953b4b222")

INPUT_BINDING_OBSERVATION = "v30-result-input-binding"
OUTPUT_ENVELOPE_OBSERVATION = "v30-result-output-envelope"
PARSED_RESULT_TYPE = "v30-result-parse-outcome"

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ARTIFACT_KINDS = frozenset(
    {"gaussian-log", "stdout", "stderr", "checkpoint-manifest"}
)
_GAUSSIAN_RESULT_KIND = "gaussian-log-facts"
_PROGRAM_FACT_KEYS = frozenset(
    {
        "program_status",
        "normal_termination_count",
        "error_termination_count",
        "optimization_completed_marker",
        "stationary_point_marker",
        "scf_calculation_count",
        "final_energy_hartree",
        "frequency_count",
        "frequency_parse_complete",
        "imaginary_frequency_count",
        "frequencies_cm-1",
        "thermochemistry",
    }
)
_PROGRAM_STATUSES = frozenset(
    {"normal-termination", "error-termination", "no-terminal-marker"}
)
_THERMOCHEMISTRY_FACT_KEYS = frozenset(
    {
        "zero_point_correction_hartree",
        "thermal_correction_energy_hartree",
        "thermal_correction_enthalpy_hartree",
        "thermal_correction_gibbs_hartree",
        "sum_electronic_zpe_hartree",
        "sum_electronic_enthalpy_hartree",
        "sum_electronic_gibbs_hartree",
    }
)


class ResultBoundaryError(ValueError):
    """Result provenance metadata does not satisfy the frozen v3 boundary."""


class MalformedEnvelopeError(ResultBoundaryError):
    """An output envelope or its artifact binding is invalid."""


class ProvenanceConflictError(ResultBoundaryError):
    """Stored records do not form one exact Attempt-bound provenance chain."""


class CaptureCompleteness(str, Enum):
    PARTIAL = "partial"
    COMPLETE = "complete"


class CaptureStatus(str, Enum):
    CAPTURED = "captured"
    IN_PROGRESS = "capture-in-progress"
    INTERRUPTED = "capture-interrupted"
    ERROR = "capture-error"


class ParseStatus(str, Enum):
    PARSED = "parsed"
    PARTIAL = "partial"
    UNPARSEABLE = "unparseable"
    UNSUPPORTED = "unsupported"


class ResultViewState(str, Enum):
    AWAITING_INPUT_BINDING = "awaiting-input-binding"
    AWAITING_CAPTURE = "awaiting-capture"
    CAPTURE_INCOMPLETE = "capture-incomplete"
    AWAITING_PARSE = "awaiting-parse"
    PARSED = "parsed"
    UNPARSEABLE = "unparseable"
    UNSUPPORTED = "unsupported"


def _require_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ResultBoundaryError(
            f"{name} must be a non-empty string without surrounding whitespace"
        )
    return value


def _require_positive_integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ResultBoundaryError(f"{name} must be a positive integer")
    return value


def _require_size(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ResultBoundaryError(f"{name} must be a non-negative integer")
    return value


def _require_sha256(value: object, name: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ResultBoundaryError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _require_logical_name(value: object, name: str) -> str:
    text = _require_text(value, name)
    if text in {".", ".."} or "/" in text or "\\" in text:
        raise ResultBoundaryError(f"{name} must be a portable logical leaf name")
    return text


def _require_utc(value: object, name: str) -> str:
    text = _require_text(value, name)
    if not text.endswith("Z"):
        raise ResultBoundaryError(f"{name} must use an explicit UTC Z suffix")
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as exc:
        raise ResultBoundaryError(f"{name} must be an ISO-8601 UTC timestamp") from exc
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ResultBoundaryError(f"{name} must be UTC")
    return text


def _identity(namespace: UUID, values: tuple[object, ...]) -> str:
    name = json.dumps(
        values, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    )
    return str(uuid5(namespace, name))


def _freeze_value(
    value: object, path: str, active_containers: set[int] | None = None
) -> object:
    active = set() if active_containers is None else active_containers
    if value is None or type(value) in {bool, int, str}:
        return value
    if type(value) is float:
        if not isfinite(value):
            raise ResultBoundaryError(f"{path} must not contain a non-finite float")
        return value
    if isinstance(value, Mapping):
        identity = id(value)
        if identity in active:
            raise ResultBoundaryError(f"{path} must not contain a container cycle")
        active.add(identity)
        try:
            frozen: dict[str, object] = {}
            for key, item in value.items():
                if not isinstance(key, str):
                    raise ResultBoundaryError(f"{path} must contain only string keys")
                frozen[key] = _freeze_value(item, f"{path}.{key}", active)
            return MappingProxyType(dict(sorted(frozen.items())))
        finally:
            active.remove(identity)
    if isinstance(value, (list, tuple)):
        identity = id(value)
        if identity in active:
            raise ResultBoundaryError(f"{path} must not contain a container cycle")
        active.add(identity)
        try:
            return tuple(
                _freeze_value(item, f"{path}[{index}]", active)
                for index, item in enumerate(value)
            )
        finally:
            active.remove(identity)
    raise ResultBoundaryError(f"{path} contains unsupported {type(value).__name__}")


def _freeze_mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ResultBoundaryError(f"{name} must be a mapping")
    frozen = _freeze_value(value, name)
    assert isinstance(frozen, Mapping)
    return frozen


def _require_exact_keys(
    value: Mapping[object, object], expected: set[str], name: str
) -> None:
    keys = set(value)
    if keys != expected:
        missing = sorted(expected - keys)
        extra = sorted(str(key) for key in keys - expected)
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if extra:
            details.append("unexpected " + ", ".join(extra))
        raise ResultBoundaryError(f"{name} has " + "; ".join(details))


def _program_facts(value: Mapping[str, object], result_kind: str) -> None:
    if not value:
        return
    if result_kind != _GAUSSIAN_RESULT_KIND:
        raise ResultBoundaryError(
            "non-empty facts are supported only for gaussian-log-facts"
        )
    _require_exact_keys(value, set(_PROGRAM_FACT_KEYS), "facts")
    if value["program_status"] not in _PROGRAM_STATUSES:
        raise ResultBoundaryError("facts.program_status is not a supported program fact")
    for name in (
        "normal_termination_count",
        "error_termination_count",
        "scf_calculation_count",
        "frequency_count",
        "imaginary_frequency_count",
    ):
        _require_size(value[name], f"facts.{name}")
    if (
        value["program_status"] == "normal-termination"
        and value["normal_termination_count"] == 0
    ):
        raise ResultBoundaryError("normal program status requires its terminal marker")
    if (
        value["program_status"] == "error-termination"
        and value["error_termination_count"] == 0
    ):
        raise ResultBoundaryError("error program status requires its terminal marker")
    if value["program_status"] == "no-terminal-marker" and (
        value["normal_termination_count"] or value["error_termination_count"]
    ):
        raise ResultBoundaryError("no-terminal-marker conflicts with terminal counts")
    for name in (
        "optimization_completed_marker",
        "stationary_point_marker",
        "frequency_parse_complete",
    ):
        if type(value[name]) is not bool:
            raise ResultBoundaryError(f"facts.{name} must be a boolean")
    energy = value["final_energy_hartree"]
    if energy is not None and (type(energy) is not float or not isfinite(energy)):
        raise ResultBoundaryError("facts.final_energy_hartree must be finite or null")
    frequencies = value["frequencies_cm-1"]
    if not isinstance(frequencies, tuple) or not all(
        type(item) is float and isfinite(item) for item in frequencies
    ):
        raise ResultBoundaryError(
            "facts.frequencies_cm-1 must contain only finite floats"
        )
    if value["frequency_count"] != len(frequencies):
        raise ResultBoundaryError("facts.frequency_count does not match frequencies")
    if value["imaginary_frequency_count"] != sum(item < 0 for item in frequencies):
        raise ResultBoundaryError(
            "facts.imaginary_frequency_count does not match frequencies"
        )
    if value["scf_calculation_count"] == 0 and energy is not None:
        raise ResultBoundaryError("final energy requires at least one SCF calculation")
    if value["scf_calculation_count"] > 0 and energy is None:
        raise ResultBoundaryError("SCF calculations require a final energy fact")
    thermochemistry = value["thermochemistry"]
    if not isinstance(thermochemistry, Mapping):
        raise ResultBoundaryError("facts.thermochemistry must be a mapping")
    unknown_thermochemistry = set(thermochemistry) - _THERMOCHEMISTRY_FACT_KEYS
    if unknown_thermochemistry:
        raise ResultBoundaryError(
            "facts.thermochemistry has unsupported keys: "
            + ", ".join(sorted(unknown_thermochemistry))
        )
    if not all(type(item) is float and isfinite(item) for item in thermochemistry.values()):
        raise ResultBoundaryError(
            "facts.thermochemistry values must be finite floats"
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class OutputArtifact:
    artifact_kind: str
    logical_name: str
    sha256: str
    size_bytes: int

    def __post_init__(self) -> None:
        _require_text(self.artifact_kind, "artifact_kind")
        if self.artifact_kind not in _ARTIFACT_KINDS:
            raise MalformedEnvelopeError(
                f"artifact_kind {self.artifact_kind!r} is not allowlisted"
            )
        _require_logical_name(self.logical_name, "logical_name")
        _require_sha256(self.sha256, "sha256")
        _require_size(self.size_bytes, "size_bytes")

    def payload(self) -> Mapping[str, object]:
        return {
            "artifact_kind": self.artifact_kind,
            "logical_name": self.logical_name,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
        }

    @classmethod
    def from_payload(cls, value: object) -> OutputArtifact:
        if not isinstance(value, Mapping):
            raise MalformedEnvelopeError("artifact payload must be a mapping")
        _require_exact_keys(
            value,
            {"artifact_kind", "logical_name", "sha256", "size_bytes"},
            "artifact payload",
        )
        try:
            return cls(
                artifact_kind=value["artifact_kind"],
                logical_name=value["logical_name"],
                sha256=value["sha256"],
                size_bytes=value["size_bytes"],
            )
        except KeyError as exc:
            raise MalformedEnvelopeError(
                f"artifact payload is missing {exc.args[0]}"
            ) from exc


@dataclass(frozen=True, slots=True, kw_only=True)
class InputBinding:
    attempt_id: str
    calculation_plan_id: str
    calculation_plan_revision: int
    prepared_input_binding_id: str
    execution_snapshot_id: str
    input_format: str
    logical_name: str
    sha256: str
    size_bytes: int
    schema_version: int = 1

    def __post_init__(self) -> None:
        _require_text(self.attempt_id, "attempt_id")
        _require_text(self.calculation_plan_id, "calculation_plan_id")
        _require_positive_integer(
            self.calculation_plan_revision, "calculation_plan_revision"
        )
        _require_text(self.prepared_input_binding_id, "prepared_input_binding_id")
        _require_text(self.execution_snapshot_id, "execution_snapshot_id")
        _require_text(self.input_format, "input_format")
        _require_logical_name(self.logical_name, "logical_name")
        _require_sha256(self.sha256, "sha256")
        _require_size(self.size_bytes, "size_bytes")
        if self.schema_version != 1:
            raise ResultBoundaryError("input binding schema_version must be 1")

    @property
    def observation_id(self) -> str:
        return _identity(
            NS_INPUT_BINDING,
            (
                self.attempt_id,
                self.calculation_plan_id,
                self.calculation_plan_revision,
                self.prepared_input_binding_id,
                self.execution_snapshot_id,
            ),
        )

    def payload(self) -> Mapping[str, object]:
        return {
            "schema_version": self.schema_version,
            "attempt_id": self.attempt_id,
            "calculation_plan_id": self.calculation_plan_id,
            "calculation_plan_revision": self.calculation_plan_revision,
            "prepared_input_binding_id": self.prepared_input_binding_id,
            "execution_snapshot_id": self.execution_snapshot_id,
            "input_format": self.input_format,
            "logical_name": self.logical_name,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
        }

    @classmethod
    def from_payload(cls, value: object) -> InputBinding:
        if not isinstance(value, Mapping):
            raise ProvenanceConflictError("input binding payload must be a mapping")
        _require_exact_keys(
            value, set(cls.__dataclass_fields__), "input binding payload"
        )
        try:
            return cls(**{name: value[name] for name in cls.__dataclass_fields__})
        except KeyError as exc:
            raise ProvenanceConflictError(
                f"input binding payload is missing {exc.args[0]}"
            ) from exc


@dataclass(frozen=True, slots=True, kw_only=True)
class OutputEnvelope:
    attempt_id: str
    input_binding_observation_id: str
    execution_snapshot_id: str
    capture_source_id: str
    capture_sequence: int
    capture_status: CaptureStatus
    capture_completeness: CaptureCompleteness
    artifacts: tuple[OutputArtifact, ...]
    capture_manifest_sha256: str
    captured_at_utc: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        _require_text(self.attempt_id, "attempt_id")
        _require_text(
            self.input_binding_observation_id, "input_binding_observation_id"
        )
        _require_text(self.execution_snapshot_id, "execution_snapshot_id")
        _require_text(self.capture_source_id, "capture_source_id")
        _require_positive_integer(self.capture_sequence, "capture_sequence")
        try:
            capture_status = CaptureStatus(self.capture_status)
        except ValueError as exc:
            raise MalformedEnvelopeError(
                "capture_status must express an allowlisted capture-layer fact"
            ) from exc
        object.__setattr__(self, "capture_status", capture_status)
        try:
            completeness = CaptureCompleteness(self.capture_completeness)
        except ValueError as exc:
            raise MalformedEnvelopeError(
                "capture_completeness must be partial or complete"
            ) from exc
        object.__setattr__(self, "capture_completeness", completeness)
        if not isinstance(self.artifacts, tuple):
            object.__setattr__(self, "artifacts", tuple(self.artifacts))
        if not self.artifacts or not all(
            isinstance(item, OutputArtifact) for item in self.artifacts
        ):
            raise MalformedEnvelopeError(
                "artifacts must contain at least one OutputArtifact"
            )
        names = [item.logical_name for item in self.artifacts]
        if len(names) != len(set(names)):
            raise MalformedEnvelopeError("artifact logical names must be unique")
        object.__setattr__(
            self, "artifacts", tuple(sorted(self.artifacts, key=lambda item: item.logical_name))
        )
        _require_sha256(self.capture_manifest_sha256, "capture_manifest_sha256")
        _require_utc(self.captured_at_utc, "captured_at_utc")
        if self.schema_version != 1:
            raise MalformedEnvelopeError("output envelope schema_version must be 1")

    @property
    def observation_id(self) -> str:
        return _identity(
            NS_OUTPUT_ENVELOPE,
            (
                self.attempt_id,
                self.input_binding_observation_id,
                self.capture_source_id,
                self.capture_manifest_sha256,
                self.capture_completeness.value,
            ),
        )

    def payload(self) -> Mapping[str, object]:
        return {
            "schema_version": self.schema_version,
            "attempt_id": self.attempt_id,
            "input_binding_observation_id": self.input_binding_observation_id,
            "execution_snapshot_id": self.execution_snapshot_id,
            "capture_source_id": self.capture_source_id,
            "capture_sequence": self.capture_sequence,
            "capture_status": self.capture_status.value,
            "capture_completeness": self.capture_completeness.value,
            "artifacts": tuple(item.payload() for item in self.artifacts),
            "capture_manifest_sha256": self.capture_manifest_sha256,
            "captured_at_utc": self.captured_at_utc,
        }

    @classmethod
    def from_payload(cls, value: object) -> OutputEnvelope:
        if not isinstance(value, Mapping):
            raise MalformedEnvelopeError("output envelope payload must be a mapping")
        _require_exact_keys(
            value, set(cls.__dataclass_fields__), "output envelope payload"
        )
        try:
            artifacts = tuple(
                OutputArtifact.from_payload(item) for item in value["artifacts"]
            )
            return cls(
                **{
                    name: artifacts if name == "artifacts" else value[name]
                    for name in cls.__dataclass_fields__
                }
            )
        except KeyError as exc:
            raise MalformedEnvelopeError(
                f"output envelope payload is missing {exc.args[0]}"
            ) from exc
        except TypeError as exc:
            raise MalformedEnvelopeError("artifacts must be a sequence") from exc


@dataclass(frozen=True, slots=True, kw_only=True)
class ParseOutcome:
    attempt_id: str
    envelope_observation_id: str
    parser_name: str
    parser_version: str
    result_kind: str
    parse_status: ParseStatus
    facts: Mapping[str, object] = field(default_factory=dict, repr=False)
    diagnostics: tuple[str, ...] = ()
    schema_version: int = 1

    def __post_init__(self) -> None:
        _require_text(self.attempt_id, "attempt_id")
        _require_text(self.envelope_observation_id, "envelope_observation_id")
        _require_text(self.parser_name, "parser_name")
        _require_text(self.parser_version, "parser_version")
        _require_text(self.result_kind, "result_kind")
        if self.result_kind != _GAUSSIAN_RESULT_KIND:
            raise ResultBoundaryError(
                "result_kind must be the supported gaussian-log-facts kind"
            )
        try:
            status = ParseStatus(self.parse_status)
        except ValueError as exc:
            raise ResultBoundaryError(
                "parse_status must be parsed, partial, unparseable, or unsupported"
            ) from exc
        object.__setattr__(self, "parse_status", status)
        facts = _freeze_mapping(self.facts, "facts")
        _program_facts(facts, self.result_kind)
        object.__setattr__(self, "facts", facts)
        diagnostics = tuple(self.diagnostics)
        if not all(isinstance(item, str) and item for item in diagnostics):
            raise ResultBoundaryError("diagnostics must contain non-empty strings")
        object.__setattr__(self, "diagnostics", diagnostics)
        if self.schema_version != 1:
            raise ResultBoundaryError("parse outcome schema_version must be 1")

    @property
    def result_id(self) -> str:
        return _identity(
            NS_PARSED_RESULT,
            (
                self.envelope_observation_id,
                self.parser_name,
                self.parser_version,
                self.result_kind,
            ),
        )

    def payload(self) -> Mapping[str, object]:
        return {
            "schema_version": self.schema_version,
            "attempt_id": self.attempt_id,
            "envelope_observation_id": self.envelope_observation_id,
            "parser_name": self.parser_name,
            "parser_version": self.parser_version,
            "result_kind": self.result_kind,
            "parse_status": self.parse_status.value,
            "facts": self.facts,
            "diagnostics": self.diagnostics,
        }

    @classmethod
    def from_payload(cls, value: object) -> ParseOutcome:
        if not isinstance(value, Mapping):
            raise ProvenanceConflictError("parse outcome payload must be a mapping")
        _require_exact_keys(
            value, set(cls.__dataclass_fields__), "parse outcome payload"
        )
        try:
            return cls(**{name: value[name] for name in cls.__dataclass_fields__})
        except KeyError as exc:
            raise ProvenanceConflictError(
                f"parse outcome payload is missing {exc.args[0]}"
            ) from exc


@dataclass(frozen=True, slots=True, kw_only=True)
class AttemptResultView:
    attempt_id: str
    state: ResultViewState
    input_binding: InputBinding | None
    envelopes: tuple[OutputEnvelope, ...]
    results: tuple[ParseOutcome, ...]
    selected_envelope_id: str | None
    selected_results: tuple[ParseOutcome, ...]
    incomplete: bool
    selection_reason: str
