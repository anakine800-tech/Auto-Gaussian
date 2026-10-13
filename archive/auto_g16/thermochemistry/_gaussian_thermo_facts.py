"""Exact-byte Gaussian thermochemistry fact supplement for one accepted Freq section."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import math
import re

from auto_g16.result import ParseOutcome, ParseStatus

from .models import _freeze_mapping, _payload_sha256


_SUPPORTED_RESULT_TUPLES = {
    ("auto-g16-v3-gaussian-job", "1.0.0", "gaussian-job-facts"),
    ("auto-g16-v3-gaussian-job", "1.1.0", "gaussian-job-facts"),
}
_SOURCE_KEYS = {
    "envelope_observation_id", "artifact_kind", "logical_name", "sha256", "size_bytes",
}
_SPAN_KEYS = _SOURCE_KEYS | {"start", "end"}
_MINIMUM_KEYS = {
    "authority_schema", "two_stage_minimum_authority_id", "source", "method_id",
    "optimization", "frequency", "classification",
}
_FREQUENCY_RESULT_KEYS = {
    "result_id", "result_payload_sha256", "source_artifact", "job_section",
    "frequency_blocks", "frequencies_cm1", "mode_count", "v30_outcome",
}
_FLOAT = rb"[+]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[DEde][+-]?[0-9]+)?"
_MASS = re.compile(rb"^[ \t]*Molecular mass:[ \t]+(" + _FLOAT + rb")[ \t]+amu\.[ \t]*$")
_SYMMETRY = re.compile(
    rb"^[ \t]*Rotational symmetry number[ \t]+([1-9][0-9]*)\.[ \t]*$"
)
_ROTATIONAL_TEMPERATURES = re.compile(
    rb"^[ \t]*Rotational temperatures \(Kelvin\)[ \t]+"
    rb"(" + _FLOAT + rb")[ \t]+(" + _FLOAT + rb")[ \t]+(" + _FLOAT + rb")[ \t]*$"
)
_POINT_GROUP = re.compile(
    rb"^[ \t]*Full point group[ \t]+([A-Za-z0-9*]+)(?:[ \t]+NOp[ \t]+[1-9][0-9]*)?[ \t]*$"
)


class GaussianThermoFactsError(ValueError):
    """The exact accepted Gaussian section cannot supply closed thermo facts."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise GaussianThermoFactsError(message)


def _closed(value: object, keys: set[str], name: str) -> Mapping[str, object]:
    _require(isinstance(value, Mapping) and set(value) == keys, f"{name} fields are not exact")
    assert isinstance(value, Mapping)
    return value


def _float(token: bytes, name: str) -> float:
    try:
        value = float(token.replace(b"D", b"E").replace(b"d", b"e"))
    except ValueError as exc:
        raise GaussianThermoFactsError(f"{name} is malformed") from exc
    _require(math.isfinite(value) and value > 0.0, f"{name} must be finite and positive")
    return value


def _validate_minimum_and_result(
    result: ParseOutcome,
    minimum_authority: Mapping[str, object],
) -> tuple[Mapping[str, object], Mapping[str, object]]:
    minimum = _closed(minimum_authority, _MINIMUM_KEYS, "two-stage minimum authority")
    payload = {key: minimum[key] for key in minimum if key != "two_stage_minimum_authority_id"}
    expected_id = "v31-two-stage-minimum-authority-" + _payload_sha256(
        {"domain": "v31-two-stage-minimum-authority", "payload": payload}
    )
    _require(
        minimum["two_stage_minimum_authority_id"] == expected_id,
        "two-stage minimum authority identity is stale",
    )
    _require(
        minimum["authority_schema"] == "v31-conformer-two-stage-minimum-authority/1"
        and minimum["classification"] == "VALIDATED_TWO_STAGE_MINIMUM",
        "current authority is not an accepted two-stage minimum",
    )
    frequency = _closed(minimum["frequency"], {"calculation_plan", "prepared_input", "result"}, "frequency authority")
    frequency_result = _closed(frequency["result"], _FREQUENCY_RESULT_KEYS, "frequency Result authority")
    _require(type(result) is ParseOutcome, "source Result must be an exact ParseOutcome")
    _require(result.parse_status is ParseStatus.PARSED, "source Result is not parsed")
    _require(
        (result.parser_name, result.parser_version, result.result_kind) in _SUPPORTED_RESULT_TUPLES,
        "source Result contract is unsupported",
    )
    _require(result.result_id == frequency_result["result_id"], "source Result identity differs from minimum authority")
    _require(
        _payload_sha256(result.payload()) == frequency_result["result_payload_sha256"],
        "source Result payload differs from minimum authority",
    )
    facts = result.facts
    source = _closed(facts.get("source_artifact"), _SOURCE_KEYS, "source artifact")
    section = _closed(facts.get("job_section"), _SPAN_KEYS, "job section")
    _require(source == frequency_result["source_artifact"], "source artifact differs from minimum authority")
    _require(section == frequency_result["job_section"], "job section differs from minimum authority")
    _require(
        facts.get("frequency_blocks") == frequency_result["frequency_blocks"]
        and facts.get("frequencies_cm-1") == frequency_result["frequencies_cm1"]
        and facts.get("frequency_count") == frequency_result["mode_count"],
        "frequency evidence differs from minimum authority",
    )
    return source, section


def extract_gaussian_thermo_facts(
    *,
    raw_gaussian_bytes: bytes,
    source_result: ParseOutcome,
    minimum_authority: Mapping[str, object],
) -> Mapping[str, object]:
    """Extract only mass, symmetry, rotational temperatures, and point-group diagnostic."""

    _require(type(raw_gaussian_bytes) is bytes, "raw Gaussian source must be exact bytes")
    source, section = _validate_minimum_and_result(source_result, minimum_authority)
    _require(len(raw_gaussian_bytes) == source["size_bytes"], "raw Gaussian source size mismatch")
    _require(
        hashlib.sha256(raw_gaussian_bytes).hexdigest() == source["sha256"],
        "raw Gaussian source SHA-256 mismatch",
    )
    start, end = section["start"], section["end"]
    _require(type(start) is int and type(end) is int and 0 <= start < end <= len(raw_gaussian_bytes), "job section span is invalid")
    selected = raw_gaussian_bytes[start:end]
    masses: list[float] = []
    symmetries: list[int] = []
    rotational_temperatures: list[tuple[float, float, float]] = []
    point_groups: list[str] = []
    for raw_line in selected.split(b"\n"):
        if raw_line.endswith(b"\r"):
            raw_line = raw_line[:-1]
        if match := _MASS.fullmatch(raw_line):
            masses.append(_float(match.group(1), "molecular mass"))
        elif raw_line.lstrip().startswith(b"Molecular mass:"):
            raise GaussianThermoFactsError("molecular mass evidence is malformed")
        elif match := _SYMMETRY.fullmatch(raw_line):
            symmetries.append(int(match.group(1)))
        elif raw_line.lstrip().startswith(b"Rotational symmetry number"):
            raise GaussianThermoFactsError("rotational symmetry evidence is malformed")
        elif match := _ROTATIONAL_TEMPERATURES.fullmatch(raw_line):
            rotational_temperatures.append(
                tuple(_float(match.group(index), "rotational temperature") for index in (1, 2, 3))
            )
        elif raw_line.lstrip().startswith(b"Rotational temperatures"):
            raise GaussianThermoFactsError("rotational temperature evidence is malformed")
        elif match := _POINT_GROUP.fullmatch(raw_line):
            point_groups.append(match.group(1).decode("ascii"))
        elif raw_line.lstrip().startswith(b"Full point group"):
            raise GaussianThermoFactsError("point-group diagnostic is malformed")
    _require(len(masses) == 1, "exact accepted section must contain one molecular mass")
    _require(bool(symmetries), "exact accepted section lacks a rotational symmetry number")
    _require(len(set(symmetries)) == 1, "exact accepted section has conflicting symmetry numbers")
    _require(
        len(rotational_temperatures) == 1,
        "exact accepted section must contain one three-value rotational temperature record",
    )
    _require(
        not point_groups or len(set(point_groups)) == 1,
        "exact accepted section has conflicting point-group diagnostics",
    )
    return _freeze_mapping(
        {
            "molecular_mass_amu": masses[0],
            "rotational_symmetry_number": symmetries[0],
            "rotational_symmetry_observation_count": len(symmetries),
            "rotational_temperatures_kelvin": rotational_temperatures[0],
            "point_group_diagnostic": point_groups[0] if point_groups else None,
            "source_result_id": source_result.result_id,
            "source_result_payload_sha256": _payload_sha256(source_result.payload()),
            "source_artifact": source,
            "job_section": section,
            "two_stage_minimum_authority_id": minimum_authority["two_stage_minimum_authority_id"],
        },
        "gaussian_thermo_facts",
    )
