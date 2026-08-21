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
_GAUSSIAN_JOB_RESULT_KIND = "gaussian-job-facts"
_GAUSSIAN_LOG_TUPLE = (
    "auto-g16-v3-gaussian-log",
    "1.0.0",
    _GAUSSIAN_RESULT_KIND,
)
_GAUSSIAN_JOB_TUPLE = (
    "auto-g16-v3-gaussian-job",
    "1.0.0",
    _GAUSSIAN_JOB_RESULT_KIND,
)
_GAUSSIAN_JOB_GRAMMAR_ID = "auto-g16-v3-gaussian-job-grammar/1"
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


def _legacy_program_facts(value: Mapping[str, object]) -> None:
    if not value:
        return
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


_ATTRIBUTED_FACT_KEYS = frozenset(
    {
        "facts_schema_version",
        "grammar_id",
        "source_artifact",
        "job_section",
        "program_status",
        "normal_termination_count",
        "error_termination_count",
        "termination_evidence",
        "optimization_completed_marker",
        "optimization_completed_evidence",
        "stationary_point_marker",
        "stationary_point_evidence",
        "scf_calculation_count",
        "scf_calculations",
        "final_energy_hartree",
        "frequency_count",
        "frequency_parse_complete",
        "imaginary_frequency_count",
        "frequencies_cm-1",
        "frequency_blocks",
        "thermochemistry",
        "geometry_blocks",
    }
)
_SOURCE_KEYS = {
    "envelope_observation_id",
    "artifact_kind",
    "logical_name",
    "sha256",
    "size_bytes",
}
_SPAN_KEYS = _SOURCE_KEYS | {"start", "end"}
_ATTRIBUTED_DIAGNOSTICS = frozenset(
    {
        "capture-partial",
        "unsupported-gaussian-log-cardinality",
        "unsupported-program",
        "unsupported-multiple-job",
        "unsupported-valid-gaussian-grammar",
        "unparseable-line-terminator",
        "unparseable-job-start",
        "unparseable-echo-boundary",
        "unparseable-ambiguous-transition",
        "unparseable-orphan-anchor",
        "unparseable-malformed-prefix",
        "unparseable-duplicate-evidence",
        "unparseable-optimization-block",
        "unparseable-frequency-block",
        "unparseable-geometry-block",
        "unparseable-geometry-row",
        "unparseable-numeric-token",
        "unparseable-terminal",
        "unparseable-trailing-content",
    }
)


def _finite_float(value: object, name: str) -> float:
    if type(value) is not float or not isfinite(value):
        raise ResultBoundaryError(f"{name} must be a finite float")
    return value


def _tuple(value: object, name: str) -> tuple[object, ...]:
    if not isinstance(value, tuple):
        raise ResultBoundaryError(f"{name} must be a tuple")
    return value


def _source(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ResultBoundaryError("facts.source_artifact must be a mapping")
    _require_exact_keys(value, _SOURCE_KEYS, "facts.source_artifact")
    _require_text(value["envelope_observation_id"], "source envelope_observation_id")
    if value["artifact_kind"] != "gaussian-log":
        raise ResultBoundaryError("source artifact_kind must be gaussian-log")
    _require_logical_name(value["logical_name"], "source logical_name")
    _require_sha256(value["sha256"], "source sha256")
    _require_size(value["size_bytes"], "source size_bytes")
    return value


def _span(
    value: object,
    source: Mapping[str, object],
    name: str,
    job_bounds: tuple[int, int] | None = None,
) -> tuple[int, int]:
    if not isinstance(value, Mapping):
        raise ResultBoundaryError(f"{name} must be a mapping")
    _require_exact_keys(value, _SPAN_KEYS, name)
    for key in _SOURCE_KEYS:
        if value[key] != source[key]:
            raise ResultBoundaryError(f"{name} does not bind the source artifact")
    start, end = value["start"], value["end"]
    if (
        isinstance(start, bool)
        or not isinstance(start, int)
        or isinstance(end, bool)
        or not isinstance(end, int)
        or not 0 <= start < end <= source["size_bytes"]
    ):
        raise ResultBoundaryError(f"{name} is not a valid half-open byte span")
    if job_bounds is not None and not (
        job_bounds[0] <= start < end <= job_bounds[1]
    ):
        raise ResultBoundaryError(f"{name} lies outside the job section")
    return start, end


def _ordered_spans(spans: list[tuple[int, int, int]]) -> None:
    ordered = sorted(spans)
    if any(left[1] > right[0] for left, right in zip(ordered, ordered[1:])):
        raise ResultBoundaryError("distinct attributed evidence spans overlap")


def _attributed_program_facts(value: Mapping[str, object]) -> None:
    _require_exact_keys(value, set(_ATTRIBUTED_FACT_KEYS), "facts")
    if type(value["facts_schema_version"]) is not int or value["facts_schema_version"] != 1:
        raise ResultBoundaryError("facts_schema_version must be 1")
    if value["grammar_id"] != _GAUSSIAN_JOB_GRAMMAR_ID:
        raise ResultBoundaryError("facts.grammar_id is not the frozen grammar")
    source = _source(value["source_artifact"])
    job = _span(value["job_section"], source, "facts.job_section")
    status = value["program_status"]
    if status not in {"normal-termination", "error-termination"}:
        raise ResultBoundaryError("attributed program_status must be terminal")
    normal = _require_size(value["normal_termination_count"], "normal count")
    error = _require_size(value["error_termination_count"], "error count")
    if (normal, error) != ((1, 0) if status == "normal-termination" else (0, 1)):
        raise ResultBoundaryError("terminal counts do not match program_status")

    all_spans: list[tuple[int, int, int]] = []
    terminal = _tuple(value["termination_evidence"], "termination_evidence")
    if len(terminal) != 1 or not isinstance(terminal[0], Mapping):
        raise ResultBoundaryError("termination_evidence must contain exactly one item")
    _require_exact_keys(terminal[0], {"kind", "source_span"}, "termination item")
    if terminal[0]["kind"] != status:
        raise ResultBoundaryError("termination evidence kind does not match status")
    terminal_span = _span(
        terminal[0]["source_span"], source, "termination span", job
    )
    if job[1] != terminal_span[1]:
        raise ResultBoundaryError("job section must end at the terminal record")
    all_spans.append((*terminal_span, 0))

    for flag_name, collection_name, kind_order in (
        ("optimization_completed_marker", "optimization_completed_evidence", 1),
        ("stationary_point_marker", "stationary_point_evidence", 2),
    ):
        flag = value[flag_name]
        if type(flag) is not bool:
            raise ResultBoundaryError(f"facts.{flag_name} must be boolean")
        collection = _tuple(value[collection_name], collection_name)
        if flag != bool(collection):
            raise ResultBoundaryError(f"facts.{flag_name} disagrees with evidence")
        previous: tuple[int, int] | None = None
        for item in collection:
            current = _span(item, source, collection_name, job)
            if previous is not None and previous >= current:
                raise ResultBoundaryError(f"{collection_name} is not ordered")
            previous = current
            all_spans.append((*current, kind_order))

    scfs = _tuple(value["scf_calculations"], "scf_calculations")
    if _require_size(value["scf_calculation_count"], "scf count") != len(scfs):
        raise ResultBoundaryError("scf_calculation_count disagrees with evidence")
    scf_values: list[float] = []
    previous = None
    for item in scfs:
        if not isinstance(item, Mapping):
            raise ResultBoundaryError("SCF evidence must be a mapping")
        _require_exact_keys(item, {"energy_hartree", "source_span"}, "SCF item")
        scf_values.append(_finite_float(item["energy_hartree"], "SCF energy"))
        current = _span(item["source_span"], source, "SCF span", job)
        if previous is not None and previous >= current:
            raise ResultBoundaryError("SCF evidence is not ordered")
        previous = current
        all_spans.append((*current, 3))
    final_energy = value["final_energy_hartree"]
    if final_energy is not None:
        _finite_float(final_energy, "final_energy_hartree")
    if scf_values:
        if final_energy != scf_values[-1]:
            raise ResultBoundaryError("final_energy_hartree is not the last SCF fact")
    elif final_energy is not None:
        raise ResultBoundaryError("final energy exists without SCF evidence")

    frequencies = _tuple(value["frequencies_cm-1"], "frequencies_cm-1")
    for item in frequencies:
        _finite_float(item, "frequency")
    if _require_size(value["frequency_count"], "frequency count") != len(frequencies):
        raise ResultBoundaryError("frequency_count disagrees with frequencies")
    if value["frequency_parse_complete"] is not True:
        raise ResultBoundaryError("parsed attributed frequencies must be complete")
    if _require_size(value["imaginary_frequency_count"], "imaginary count") != sum(item < 0 for item in frequencies):
        raise ResultBoundaryError("imaginary_frequency_count disagrees with frequencies")
    blocks = _tuple(value["frequency_blocks"], "frequency_blocks")
    flattened: list[float] = []
    previous = None
    for block in blocks:
        if not isinstance(block, Mapping):
            raise ResultBoundaryError("frequency block must be a mapping")
        _require_exact_keys(block, {"source_span", "frequencies_cm-1"}, "frequency block")
        group = _tuple(block["frequencies_cm-1"], "frequency block values")
        if not 1 <= len(group) <= 3:
            raise ResultBoundaryError("frequency block cardinality must be 1..3")
        for item in group:
            flattened.append(_finite_float(item, "frequency block value"))
        current = _span(block["source_span"], source, "frequency block span", job)
        if previous is not None and previous >= current:
            raise ResultBoundaryError("frequency blocks are not ordered")
        previous = current
        all_spans.append((*current, 4))
    if tuple(flattened) != frequencies:
        raise ResultBoundaryError("top-level frequencies are not the block projection")

    thermo = value["thermochemistry"]
    if not isinstance(thermo, Mapping) or set(thermo) - _THERMOCHEMISTRY_FACT_KEYS:
        raise ResultBoundaryError("thermochemistry has unsupported keys")
    thermo_spans: list[tuple[int, int]] = []
    for key, item in thermo.items():
        if not isinstance(item, Mapping):
            raise ResultBoundaryError(f"thermochemistry.{key} must be a mapping")
        _require_exact_keys(item, {"value_hartree", "source_span"}, f"thermochemistry.{key}")
        _finite_float(item["value_hartree"], f"thermochemistry.{key}.value_hartree")
        current = _span(item["source_span"], source, f"thermochemistry.{key}.span", job)
        thermo_spans.append(current)
    for current in sorted(thermo_spans):
        all_spans.append((*current, 5))

    geometries = _tuple(value["geometry_blocks"], "geometry_blocks")
    previous = None
    for block in geometries:
        if not isinstance(block, Mapping):
            raise ResultBoundaryError("geometry block must be a mapping")
        _require_exact_keys(block, {"orientation_kind", "units", "source_span", "atoms"}, "geometry block")
        if block["orientation_kind"] not in {"input-orientation", "standard-orientation"} or block["units"] != "angstrom":
            raise ResultBoundaryError("geometry block kind or units are invalid")
        atoms = _tuple(block["atoms"], "geometry atoms")
        if not atoms:
            raise ResultBoundaryError("geometry atoms must be non-empty")
        for index, atom in enumerate(atoms, start=1):
            if not isinstance(atom, Mapping):
                raise ResultBoundaryError("geometry atom must be a mapping")
            _require_exact_keys(atom, {"center", "atomic_number", "x", "y", "z"}, "geometry atom")
            if (
                isinstance(atom["center"], bool)
                or not isinstance(atom["center"], int)
                or atom["center"] != index
                or isinstance(atom["atomic_number"], bool)
                or not isinstance(atom["atomic_number"], int)
                or not 0 <= atom["atomic_number"] <= 118
            ):
                raise ResultBoundaryError("geometry center or atomic number is invalid")
            for coordinate in ("x", "y", "z"):
                _finite_float(atom[coordinate], f"geometry atom {coordinate}")
        current = _span(block["source_span"], source, "geometry block span", job)
        if previous is not None and previous >= current:
            raise ResultBoundaryError("geometry blocks are not ordered")
        previous = current
        all_spans.append((*current, 6))
    _ordered_spans(all_spans)


def _program_facts(
    value: Mapping[str, object],
    parser_tuple: tuple[str, str, str],
    status: ParseStatus,
    diagnostics: tuple[str, ...],
) -> None:
    # Preserve the historical schema-v1 compatibility surface: old persisted
    # gaussian-log-facts rows may carry their original parser name/version.
    if parser_tuple[2] == _GAUSSIAN_RESULT_KIND:
        _legacy_program_facts(value)
        return
    if parser_tuple != _GAUSSIAN_JOB_TUPLE:
        raise ResultBoundaryError("parse outcome uses an unsupported parser tuple")
    if status is ParseStatus.PARSED:
        if not value or diagnostics:
            raise ResultBoundaryError("parsed gaussian-job-facts require facts and no diagnostic")
        _attributed_program_facts(value)
        return
    if value or len(diagnostics) != 1 or diagnostics[0] not in _ATTRIBUTED_DIAGNOSTICS:
        raise ResultBoundaryError("non-parsed gaussian-job-facts require one closed diagnostic and empty facts")
    expected = {
        ParseStatus.PARTIAL: {"capture-partial"},
        ParseStatus.UNSUPPORTED: {
            "unsupported-gaussian-log-cardinality",
            "unsupported-program",
            "unsupported-multiple-job",
            "unsupported-valid-gaussian-grammar",
        },
        ParseStatus.UNPARSEABLE: _ATTRIBUTED_DIAGNOSTICS
        - {
            "capture-partial",
            "unsupported-gaussian-log-cardinality",
            "unsupported-program",
            "unsupported-multiple-job",
            "unsupported-valid-gaussian-grammar",
        },
    }[status]
    if diagnostics[0] not in expected:
        raise ResultBoundaryError("diagnostic code does not match parse_status")


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
        if self.result_kind not in {
            _GAUSSIAN_RESULT_KIND,
            _GAUSSIAN_JOB_RESULT_KIND,
        }:
            raise ResultBoundaryError(
                "result_kind must be a supported Result facts kind"
            )
        try:
            status = ParseStatus(self.parse_status)
        except ValueError as exc:
            raise ResultBoundaryError(
                "parse_status must be parsed, partial, unparseable, or unsupported"
            ) from exc
        object.__setattr__(self, "parse_status", status)
        facts = _freeze_mapping(self.facts, "facts")
        diagnostics = tuple(self.diagnostics)
        if not all(isinstance(item, str) and item for item in diagnostics):
            raise ResultBoundaryError("diagnostics must contain non-empty strings")
        object.__setattr__(self, "diagnostics", diagnostics)
        _program_facts(
            facts,
            (self.parser_name, self.parser_version, self.result_kind),
            status,
            diagnostics,
        )
        object.__setattr__(self, "facts", facts)
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
