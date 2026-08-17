"""Pure offline Gaussian output facts for the v3 result boundary."""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Mapping
from typing import Final

from .models import (
    CaptureCompleteness,
    MalformedEnvelopeError,
    OutputEnvelope,
    ParseOutcome,
    ParseStatus,
)


PARSER_NAME: Final = "auto-g16-v3-gaussian-log"
PARSER_VERSION: Final = "1.0.0"
RESULT_KIND: Final = "gaussian-log-facts"

_THERMOCHEMISTRY = {
    "zero_point_correction_hartree": re.compile(
        rb"Zero-point correction=\s*([-+0-9.DEded]+)", re.I
    ),
    "thermal_correction_energy_hartree": re.compile(
        rb"Thermal correction to Energy=\s*([-+0-9.DEded]+)", re.I
    ),
    "thermal_correction_enthalpy_hartree": re.compile(
        rb"Thermal correction to Enthalpy=\s*([-+0-9.DEded]+)", re.I
    ),
    "thermal_correction_gibbs_hartree": re.compile(
        rb"Thermal correction to Gibbs Free Energy=\s*([-+0-9.DEded]+)", re.I
    ),
    "sum_electronic_zpe_hartree": re.compile(
        rb"Sum of electronic and zero-point Energies=\s*([-+0-9.DEded]+)",
        re.I,
    ),
    "sum_electronic_enthalpy_hartree": re.compile(
        rb"Sum of electronic and thermal Enthalpies=\s*([-+0-9.DEded]+)",
        re.I,
    ),
    "sum_electronic_gibbs_hartree": re.compile(
        rb"Sum of electronic and thermal Free Energies=\s*([-+0-9.DEded]+)",
        re.I,
    ),
}


def _last_float(data: bytes, pattern: re.Pattern[bytes]) -> float | None:
    values = pattern.findall(data)
    if not values:
        return None
    try:
        value = float(values[-1].replace(b"D", b"E").replace(b"d", b"e"))
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def _facts(data: bytes) -> tuple[dict[str, object], tuple[str, ...]]:
    diagnostics: list[str] = []
    energy_pattern = re.compile(
        rb"SCF Done:\s+E\([^)]*\)\s*=\s*([-+0-9.DEded]+)"
    )
    energy_values: list[float] = []
    for raw in energy_pattern.findall(data):
        try:
            value = float(raw.replace(b"D", b"E").replace(b"d", b"e"))
        except ValueError:
            diagnostics.append("malformed SCF energy token")
            continue
        if math.isfinite(value):
            energy_values.append(value)
        else:
            diagnostics.append("non-finite SCF energy token")

    frequencies: list[float] = []
    frequency_parse_complete = True
    for line_number, line in enumerate(data.splitlines(), start=1):
        match = re.match(rb"^\s*Frequencies\s+--\s*(.*)$", line)
        if not match:
            continue
        tokens = match.group(1).split()
        if not tokens:
            diagnostics.append(f"empty frequency group at line {line_number}")
            frequency_parse_complete = False
            continue
        for raw in tokens:
            try:
                value = float(raw.replace(b"D", b"E").replace(b"d", b"e"))
            except ValueError:
                diagnostics.append(
                    f"malformed frequency token at line {line_number}: "
                    + raw.decode("ascii", "replace")
                )
                frequency_parse_complete = False
                continue
            if not math.isfinite(value):
                diagnostics.append(
                    f"non-finite frequency token at line {line_number}"
                )
                frequency_parse_complete = False
                continue
            frequencies.append(value)

    normal_count = data.count(b"Normal termination of Gaussian")
    error_count = data.count(b"Error termination")
    last_normal = data.rfind(b"Normal termination of Gaussian")
    last_error = data.rfind(b"Error termination")
    if last_error > last_normal:
        program_status = "error-termination"
    elif normal_count:
        program_status = "normal-termination"
    else:
        program_status = "no-terminal-marker"

    thermochemistry = {
        name: value
        for name, pattern in _THERMOCHEMISTRY.items()
        if (value := _last_float(data, pattern)) is not None
    }
    facts: dict[str, object] = {
        "program_status": program_status,
        "normal_termination_count": normal_count,
        "error_termination_count": error_count,
        "optimization_completed_marker": b"Optimization completed" in data,
        "stationary_point_marker": b"Stationary point found" in data,
        "scf_calculation_count": len(energy_values),
        "final_energy_hartree": energy_values[-1] if energy_values else None,
        "frequency_count": len(frequencies),
        "frequency_parse_complete": frequency_parse_complete,
        "imaginary_frequency_count": sum(value < 0 for value in frequencies),
        "frequencies_cm-1": tuple(frequencies),
        "thermochemistry": thermochemistry,
    }
    return facts, tuple(diagnostics)


class GaussianLogParser:
    """Validate exact captured bytes and return facts, never acceptance."""

    parser_name = PARSER_NAME
    parser_version = PARSER_VERSION
    result_kind = RESULT_KIND

    def parse(
        self,
        envelope: OutputEnvelope,
        artifact_bytes: Mapping[str, bytes],
    ) -> ParseOutcome:
        expected = {item.logical_name: item for item in envelope.artifacts}
        if set(artifact_bytes) != set(expected):
            raise MalformedEnvelopeError(
                "artifact bytes must match the exact envelope artifact set"
            )
        for logical_name, data in artifact_bytes.items():
            if not isinstance(data, bytes):
                raise MalformedEnvelopeError("captured artifact content must be bytes")
            artifact = expected[logical_name]
            if len(data) != artifact.size_bytes:
                raise MalformedEnvelopeError(
                    f"artifact size does not match envelope: {logical_name}"
                )
            if hashlib.sha256(data).hexdigest() != artifact.sha256:
                raise MalformedEnvelopeError(
                    f"artifact digest does not match envelope: {logical_name}"
                )

        logs = [
            item for item in envelope.artifacts if item.artifact_kind == "gaussian-log"
        ]
        if len(logs) != 1:
            return ParseOutcome(
                attempt_id=envelope.attempt_id,
                envelope_observation_id=envelope.observation_id,
                parser_name=self.parser_name,
                parser_version=self.parser_version,
                result_kind=self.result_kind,
                parse_status=(
                    ParseStatus.PARTIAL
                    if envelope.capture_completeness is CaptureCompleteness.PARTIAL
                    else ParseStatus.UNSUPPORTED
                ),
                facts={},
                diagnostics=("exactly one gaussian-log artifact is required",),
            )

        facts, diagnostics = _facts(artifact_bytes[logs[0].logical_name])
        recognizable = bool(
            facts["normal_termination_count"]
            or facts["error_termination_count"]
            or facts["scf_calculation_count"]
            or facts["frequency_count"]
            or facts["optimization_completed_marker"]
            or facts["stationary_point_marker"]
        )
        if envelope.capture_completeness is CaptureCompleteness.PARTIAL:
            status = ParseStatus.PARTIAL
        elif recognizable and diagnostics:
            status = ParseStatus.PARTIAL
        elif recognizable:
            status = ParseStatus.PARSED
        else:
            status = ParseStatus.UNPARSEABLE
            diagnostics += ("captured bytes contain no recognized Gaussian facts",)
        return ParseOutcome(
            attempt_id=envelope.attempt_id,
            envelope_observation_id=envelope.observation_id,
            parser_name=self.parser_name,
            parser_version=self.parser_version,
            result_kind=self.result_kind,
            parse_status=status,
            facts=facts,
            diagnostics=diagnostics,
        )
