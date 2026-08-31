"""Exact-byte, single-job Gaussian facts for the v3 Result boundary."""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from .models import CaptureCompleteness, MalformedEnvelopeError, OutputEnvelope, ParseOutcome, ParseStatus

PARSER_NAME: Final = "auto-g16-v3-gaussian-job"
PARSER_VERSION: Final = "1.1.0"
RESULT_KIND: Final = "gaussian-job-facts"
GRAMMAR_ID: Final = "auto-g16-v3-gaussian-job-grammar/2"

H0, H1 = rb"[ \t]*", rb"[ \t]+"
UINT, INT = rb"[0-9]+", rb"[+-]?[0-9]+"
NUM = rb"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[EeDd][+-]?[0-9]+)?"
SYM, RAW = rb"[A-Za-z0-9?'+-]+", rb"[^ \t\r\n]+"


def _rx(body: bytes) -> re.Pattern[bytes]:
    return re.compile(rb"\A" + body + rb"\Z")


P = {
    "blank": _rx(H0),
    "job": _rx(rb" Entering Gaussian System, Link 0=g16"),
    "other_program": _rx(H1 + rb"Entering Gaussian System, Link 0=g(?:03|09)" + H0),
    "symbolic": _rx(H1 + rb"Symbolic Z-matrix:" + H0),
    "charge": _rx(H1 + rb"Charge" + H1 + rb"=" + H1 + INT + H1 + rb"Multiplicity" + H1 + rb"=" + H1 + rb"[1-9][0-9]*" + H0),
    "grad": _rx(H1 + rb"(?:Grad){2,}" + H0),
    "link1": _rx(H0 + rb"--Link1--" + H0),
    "internal": _rx(H1 + rb"(?:Link1:" + H1 + rb")?Proceeding" + H1 + rb"to" + H1 + rb"internal" + H1 + rb"job" + H1 + rb"step" + H1 + rb"number" + H1 + rb"(?P<n>[2-9][0-9]*)\." + H0),
    "internal_enter": _rx(H1 + rb"\(Enter" + H1 + rb"[\x21-\x7e]*/l1\.exe\)" + H0),
    "unsupported_orientation": _rx(H1 + rb"Z-Matrix orientation:" + H0),
    "normal": _rx(H1 + rb"Normal termination of Gaussian 16(?:" + H1 + rb"at" + H1 + rb"[\x20-\x7e]+)?\.?" + H0),
    "error_a": _rx(H1 + rb"Error" + H1 + rb"termination" + H1 + rb"via" + H1 + rb"Lnk1e" + H1 + rb"in" + H1 + rb"[\x21-\x7e]+" + H1 + rb"at" + H1 + rb"[\x20-\x7e]+\." + H0),
    "error_b": _rx(H1 + rb"Error" + H1 + rb"termination" + H1 + rb"request" + H1 + rb"processed" + H1 + rb"by" + H1 + rb"link" + H1 + rb"[0-9]+\." + H0),
    "scf": _rx(H1 + rb"SCF Done:" + H1 + rb"E\([^\r\n()]+\)" + H1 + rb"=" + H1 + rb"(?P<n>" + NUM + rb")" + H1 + rb"A\.U\.(?:" + H1 + rb"after" + H1 + UINT + H1 + rb"cycles)?" + H0),
    "opt_header": _rx(H1 + rb"Item" + H1 + rb"Value" + H1 + rb"Threshold" + H1 + rb"Converged\?" + H0),
    "opt_max_force": _rx(H1 + rb"Maximum" + H1 + rb"Force" + H1 + NUM + H1 + NUM + H1 + rb"(?:YES|NO)" + H0),
    "opt_rms_force": _rx(H1 + rb"RMS" + H1 + rb"Force" + H1 + NUM + H1 + NUM + H1 + rb"(?:YES|NO)" + H0),
    "opt_max_disp": _rx(H1 + rb"Maximum" + H1 + rb"Displacement" + H1 + NUM + H1 + NUM + H1 + rb"(?:YES|NO)" + H0),
    "opt_rms_disp": _rx(H1 + rb"RMS" + H1 + rb"Displacement" + H1 + NUM + H1 + NUM + H1 + rb"(?:YES|NO)" + H0),
    "opt_predicted": _rx(H1 + rb"Predicted" + H1 + rb"change" + H1 + rb"in" + H1 + rb"Energy=" + H0 + NUM + H0),
    "opt_done": _rx(H1 + rb"Optimization completed\." + H0),
    "stationary": _rx(H1 + rb"--" + H1 + rb"Stationary point found\." + H0),
    "fh1": _rx(H1 + rb"Harmonic frequencies \(cm\*\*-1\), IR intensities \(KM/Mole\), Raman scattering" + H0),
    "fh2": _rx(H1 + rb"activities \(A\*\*4/AMU\), depolarization ratios for plane and unpolarized" + H0),
    "fh3": _rx(H1 + rb"incident light, reduced masses \(AMU\), force constants \(mDyne/A\)," + H0),
    "fh4": _rx(H1 + rb"and normal coordinates:" + H0),
    "modes": _rx(H1 + rb"(?P<v>" + UINT + rb"(?:" + H1 + UINT + rb"){0,2})" + H0),
    "sym": _rx(H1 + rb"(?P<v>" + SYM + rb"(?:" + H1 + SYM + rb"){0,2})" + H0),
    "freq": _rx(H1 + rb"Frequencies" + H1 + rb"--" + H1 + rb"(?P<v>" + NUM + rb"(?:" + H1 + NUM + rb"){0,2})" + H0),
    "mass": _rx(H1 + rb"Red\. masses" + H1 + rb"--" + H1 + rb"(?P<v>" + NUM + rb"(?:" + H1 + NUM + rb"){0,2})" + H0),
    "force": _rx(H1 + rb"Frc consts" + H1 + rb"--" + H1 + rb"(?P<v>" + NUM + rb"(?:" + H1 + NUM + rb"){0,2})" + H0),
    "ir": _rx(H1 + rb"IR Inten" + H1 + rb"--" + H1 + rb"(?P<v>" + NUM + rb"(?:" + H1 + NUM + rb"){0,2})" + H0),
    "orientation": _rx(H1 + rb"(?P<k>Input|Standard) orientation:" + H0),
    "sep": _rx(H1 + rb"-{5,}" + H0),
    "gh1": _rx(H1 + rb"Center" + H1 + rb"Atomic" + H1 + rb"Atomic" + H1 + rb"Coordinates \(Angstroms\)" + H0),
    "gh2": _rx(H1 + rb"Number" + H1 + rb"Number" + H1 + rb"Type" + H1 + rb"X" + H1 + rb"Y" + H1 + rb"Z" + H0),
}

THERMO = {
    b"Zero-point correction=": ("zero_point_correction_hartree", rb"[ \t]+\(Hartree/Particle\)[ \t]*"),
    b"Thermal correction to Energy=": ("thermal_correction_energy_hartree", H0),
    b"Thermal correction to Enthalpy=": ("thermal_correction_enthalpy_hartree", H0),
    b"Thermal correction to Gibbs Free Energy=": ("thermal_correction_gibbs_hartree", H0),
    b"Sum of electronic and zero-point Energies=": ("sum_electronic_zpe_hartree", H0),
    b"Sum of electronic and thermal Enthalpies=": ("sum_electronic_enthalpy_hartree", H0),
    b"Sum of electronic and thermal Free Energies=": ("sum_electronic_gibbs_hartree", H0),
}

for index, (prefix, (_, suffix)) in enumerate(THERMO.items()):
    P[f"thermo_{index}"] = _rx(
        H1 + re.escape(prefix) + H0 + NUM + suffix
    )

PREFIXES = (
    (b"Normal termination", "unparseable-terminal"), (b"Error termination", "unparseable-terminal"),
    (b"Item", "unparseable-malformed-prefix"), (b"Maximum Force", "unparseable-malformed-prefix"),
    (b"RMS Force", "unparseable-malformed-prefix"), (b"Maximum Displacement", "unparseable-malformed-prefix"),
    (b"RMS Displacement", "unparseable-malformed-prefix"), (b"Predicted change in Energy=", "unparseable-malformed-prefix"),
    (b"Optimization completed", "unparseable-malformed-prefix"), (b"-- Stationary point found", "unparseable-malformed-prefix"),
    (b"Harmonic frequencies", "unparseable-malformed-prefix"), (b"activities", "unparseable-malformed-prefix"),
    (b"incident light", "unparseable-malformed-prefix"), (b"and normal coordinates:", "unparseable-malformed-prefix"),
    (b"Frequencies", "unparseable-malformed-prefix"), (b"Red. masses", "unparseable-malformed-prefix"),
    (b"Frc consts", "unparseable-malformed-prefix"), (b"IR Inten", "unparseable-malformed-prefix"),
    (b"Input orientation:", "unparseable-malformed-prefix"), (b"Standard orientation:", "unparseable-malformed-prefix"),
    (b"Z-Matrix orientation:", "unparseable-malformed-prefix"), (b"Center Atomic Atomic Coordinates", "unparseable-malformed-prefix"),
    (b"Number Number Type X Y Z", "unparseable-malformed-prefix"),
)


@dataclass(frozen=True, slots=True)
class _Line:
    start: int
    content_end: int
    end: int
    content: bytes


@dataclass(frozen=True, slots=True)
class _Recognition:
    status: ParseStatus
    facts: Mapping[str, object]
    diagnostic: str | None
    failure_position: int | None = None
    failure_span: tuple[int, int] | None = None


def _fail(code: str, position: int | None, span: tuple[int, int] | None, status: ParseStatus = ParseStatus.UNPARSEABLE) -> _Recognition:
    return _Recognition(status, {}, code, position, span)


def _line_fail(code: str, line: _Line, status: ParseStatus = ParseStatus.UNPARSEABLE) -> _Recognition:
    return _fail(code, line.start, (line.start, line.end), status)


def _tokenize(data: bytes) -> tuple[tuple[_Line, ...], _Recognition | None]:
    lines: list[_Line] = []
    start = 0
    while start < len(data):
        lf = data.find(b"\n", start)
        if lf < 0:
            end = len(data)
            content = data[start:end]
        else:
            end = lf + 1
            content = data[start : lf - 1 if lf > start and data[lf - 1] == 13 else lf]
        lone = content.find(b"\r")
        if lone >= 0:
            pos = start + lone
            return (), _fail("unparseable-line-terminator", pos, (pos, pos + 1))
        lines.append(_Line(start, start + len(content), end, content))
        start = end
    return tuple(lines), None


def _m(name: str, line: _Line) -> re.Match[bytes] | None:
    return P[name].fullmatch(line.content)


def _number(raw: bytes) -> float | None:
    if re.fullmatch(NUM, raw) is None:
        return None
    try:
        value = float(raw.replace(b"D", b"E").replace(b"d", b"e"))
    except (ValueError, OverflowError):
        return None
    return value if math.isfinite(value) else None


def _body(line: _Line) -> bytes | None:
    match = re.match(H1, line.content)
    return None if match is None else line.content[match.end() :]


def _span(source: Mapping[str, object], start: int, end: int) -> dict[str, object]:
    return {**source, "start": start, "end": end}


def _numeric_failure(line: _Line, match: re.Match[bytes], name: str) -> _Recognition:
    start = line.start + match.start(name)
    return _fail("unparseable-numeric-token", start, (start, line.start + match.end(name)))


def _terminal(line: _Line) -> str | None:
    if _m("normal", line):
        return "normal-termination"
    if _m("error_a", line) or _m("error_b", line):
        return "error-termination"
    return None


def _multi(line: _Line) -> bool:
    return bool(_m("job", line) or _m("link1", line) or _m("internal", line))


ORPHANS = tuple(name for name in P if name not in {"blank", "sep", "modes", "sym"})


def _orphan(line: _Line, allowed: set[str] = frozenset()) -> bool:
    return any(name not in allowed and _m(name, line) for name in ORPHANS)


def _direct(line: _Line, prefix: bytes, suffix: bytes) -> tuple[re.Match[bytes] | None, float | None]:
    match = _rx(H1 + re.escape(prefix) + H0 + rb"(?P<n>" + RAW + rb")" + suffix).fullmatch(line.content)
    return (match, None if match is None else _number(match.group("n")))


def _thermo(line: _Line) -> tuple[str, float] | _Recognition | None:
    body = _body(line)
    if body is None:
        return None
    for prefix, (key, suffix) in THERMO.items():
        if not body.startswith(prefix):
            continue
        match, value = _direct(line, prefix, suffix)
        if match is None:
            return _line_fail("unparseable-malformed-prefix", line)
        if value is None:
            return _numeric_failure(line, match, "n")
        return key, value
    return None


def _scf(line: _Line) -> float | _Recognition | None:
    body = _body(line)
    if body is None or not body.startswith(b"SCF Done:"):
        return None
    exact = _m("scf", line)
    if exact:
        value = _number(exact.group("n"))
        return value if value is not None else _numeric_failure(line, exact, "n")
    shape = _rx(H1 + rb"SCF Done:" + H1 + rb"E\([^\r\n()]+\)" + H1 + rb"=" + H1 + rb"(?P<n>" + RAW + rb")" + H1 + rb"A\.U\.(?:" + H1 + rb"after" + H1 + UINT + H1 + rb"cycles)?" + H0).fullmatch(line.content)
    if shape and _number(shape.group("n")) is None:
        return _numeric_failure(line, shape, "n")
    return _line_fail("unparseable-malformed-prefix", line)


def _prefix_failure(line: _Line) -> _Recognition | None:
    body = _body(line)
    if body is None:
        return None
    if body.startswith(b"SCF Done:"):
        result = _scf(line)
        return result if isinstance(result, _Recognition) else None
    for prefix in THERMO:
        if body.startswith(prefix):
            result = _thermo(line)
            return result if isinstance(result, _Recognition) else None
    for prefix, code in PREFIXES:
        if body.startswith(prefix):
            if prefix in {
                b"Maximum Force",
                b"RMS Force",
                b"Maximum Displacement",
                b"RMS Displacement",
            } and body[len(prefix) :].lstrip(b" \t").startswith(b"="):
                continue
            return _line_fail(code, line)
    return None


def _raw_slots(line: _Line, label: bytes, count: int, tail: bytes = H0) -> re.Match[bytes] | None:
    label_rx = H1.join(re.escape(part) for part in label.split())
    if label:
        body = H1 + label_rx + b"".join(
            H1 + rb"(?P<n" + str(i).encode() + rb">" + RAW + rb")"
            for i in range(count)
        )
    else:
        body = H1 + rb"(?P<n0>" + RAW + rb")" + b"".join(
            H1 + rb"(?P<n" + str(i).encode() + rb">" + RAW + rb")"
            for i in range(1, count)
        )
    return _rx(body + tail).fullmatch(line.content)


def _opt_row(line: _Line, label: bytes) -> _Recognition | None:
    match = _raw_slots(line, label, 2, H1 + rb"(?:YES|NO)" + H0)
    if match is None:
        return _line_fail("unparseable-optimization-block", line)
    for name in ("n0", "n1"):
        if _number(match.group(name)) is None:
            return _numeric_failure(line, match, name)
    return None


def _predicted(line: _Line) -> bool | _Recognition:
    body = _body(line)
    if body is None or not body.startswith(b"Predicted change in Energy="):
        return False
    match, value = _direct(line, b"Predicted change in Energy=", H0)
    if match is None:
        return _line_fail("unparseable-optimization-block", line)
    return True if value is not None else _numeric_failure(line, match, "n")


def _series(line: _Line, label: bytes, count: int) -> tuple[float, ...] | _Recognition:
    match = _rx(H1 + re.escape(label) + H1 + rb"--" + H1 + rb"(?P<v>" + RAW + rb"(?:" + H1 + RAW + rb")*)" + H0).fullmatch(line.content)
    if match is None:
        return _line_fail("unparseable-frequency-block", line)
    raw = match.group("v")
    tokens = list(re.finditer(RAW, raw))
    if len(tokens) != count:
        return _line_fail("unparseable-frequency-block", line)
    values: list[float] = []
    for token in tokens:
        value = _number(token.group())
        if value is None:
            start = line.start + match.start("v") + token.start()
            return _fail("unparseable-numeric-token", start, (start, start + len(token.group())))
        values.append(value)
    return tuple(values)


def _atom(line: _Line, expected_center: int) -> tuple[dict[str, object] | None, _Recognition | None]:
    match = _raw_slots(line, b"", 6)
    if match is None:
        return None, _line_fail("unparseable-geometry-row", line)
    patterns = (UINT, UINT, INT, NUM, NUM, NUM)
    for i, pattern in enumerate(patterns):
        name = f"n{i}"
        raw = match.group(name)
        if re.fullmatch(pattern, raw) is None or (i >= 3 and _number(raw) is None):
            return None, _numeric_failure(line, match, name)
    center, atomic_number = int(match.group("n0")), int(match.group("n1"))
    if center != expected_center or not 0 <= atomic_number <= 118:
        return None, _line_fail("unparseable-geometry-row", line)
    return {"center": center, "atomic_number": atomic_number, "x": _number(match.group("n3")), "y": _number(match.group("n4")), "z": _number(match.group("n5"))}, None


def _recognize(data: bytes, source: Mapping[str, object]) -> _Recognition:
    lines, failed = _tokenize(data)
    if failed:
        return failed
    state, return_state, index = "PREAMBLE", "MACHINE_BODY", 0
    job_start = terminal_line = last_grammar_line = None
    geometry_kind = None
    echo_molecule = predicted_seen = False
    next_internal_step = 2
    opt_done = None
    group_modes: tuple[int, ...] = ()
    group_values: tuple[float, ...] = ()
    group_start = last_mode = geometry_start = None
    geometry_atoms: list[dict[str, object]] = []
    opts: list[dict[str, object]] = []
    stations: list[dict[str, object]] = []
    scfs: list[dict[str, object]] = []
    freq_blocks: list[dict[str, object]] = []
    thermos: dict[str, dict[str, object]] = {}
    geometries: list[dict[str, object]] = []
    terminals: list[dict[str, object]] = []

    def consumed(line: _Line) -> None:
        nonlocal last_grammar_line
        last_grammar_line = line

    def body_step(line: _Line, parent: str) -> tuple[str, _Recognition | None]:
        nonlocal return_state, predicted_seen, opt_done, geometry_start, geometry_kind, geometry_atoms, terminal_line, last_mode
        parsed_scf = _scf(line)
        if isinstance(parsed_scf, _Recognition):
            return parent, parsed_scf
        if parsed_scf is not None:
            scfs.append({"energy_hartree": parsed_scf, "source_span": _span(source, line.start, line.end)})
            consumed(line)
            return parent, None
        if _m("opt_header", line):
            return_state, predicted_seen, opt_done = parent, False, None
            consumed(line)
            return "OPT_MAX_FORCE", None
        if _m("fh1", line):
            return_state = parent
            consumed(line)
            return "FREQ_HEAD_2", None
        orientation = _m("orientation", line)
        if orientation:
            return_state, geometry_start, geometry_atoms = parent, line.start, []
            geometry_kind = "input-orientation" if orientation.group("k") == b"Input" else "standard-orientation"
            consumed(line)
            return "GEOM_SEP_1", None
        parsed_thermo = _thermo(line)
        if isinstance(parsed_thermo, _Recognition):
            return parent, parsed_thermo
        if parsed_thermo:
            key, value = parsed_thermo
            if key in thermos:
                return parent, _line_fail("unparseable-duplicate-evidence", line)
            thermos[key] = {"value_hartree": value, "source_span": _span(source, line.start, line.end)}
            consumed(line)
            return parent, None
        kind = _terminal(line)
        if kind:
            terminal_line = line
            terminals.append(
                {"kind": kind, "source_span": _span(source, line.start, line.end)}
            )
            consumed(line)
            return "TERMINATED", None
        if _multi(line):
            return parent, _line_fail("unsupported-multiple-job", line, ParseStatus.UNSUPPORTED)
        if _m("other_program", line):
            return parent, _line_fail("unsupported-program", line, ParseStatus.UNSUPPORTED)
        if _m("unsupported_orientation", line):
            return parent, _line_fail("unsupported-valid-gaussian-grammar", line, ParseStatus.UNSUPPORTED)
        if _m("grad", line):
            consumed(line)
            return parent, None
        if _m("symbolic", line) or _m("charge", line):
            return parent, _line_fail("unparseable-echo-boundary", line)
        allowed = {"scf", "opt_header", "fh1", "orientation", "normal", "error_a", "error_b"}
        if _orphan(line, allowed):
            return parent, _line_fail("unparseable-orphan-anchor", line)
        return parent, _prefix_failure(line)

    while index < len(lines):
        line, advance = lines[index], True
        if state == "PREAMBLE":
            if _m("job", line):
                job_start, state = line, "INPUT_ECHO"; consumed(line)
            elif _m("other_program", line):
                return _line_fail("unsupported-program", line, ParseStatus.UNSUPPORTED)
        elif state == "INPUT_ECHO":
            if _m("symbolic", line): state = "INPUT_MOLECULE"; consumed(line)
            elif _m("charge", line) or _m("grad", line): return _line_fail("unparseable-echo-boundary", line)
        elif state == "INPUT_MOLECULE":
            if _m("charge", line): state, echo_molecule = "INPUT_BOUND", False; consumed(line)
            elif _m("symbolic", line) or _m("grad", line): return _line_fail("unparseable-echo-boundary", line)
        elif state == "INPUT_BOUND":
            if _m("symbolic", line) or _m("charge", line): return _line_fail("unparseable-echo-boundary", line)
            if _m("grad", line):
                if not echo_molecule: return _line_fail("unparseable-echo-boundary", line)
                state = "MACHINE_BODY"; consumed(line)
            elif not _m("blank", line): echo_molecule = True; consumed(line)
        elif state in {"MACHINE_BODY", "FREQUENCY_BODY"}:
            mode = _m("modes", line) if state == "FREQUENCY_BODY" else None
            next_sym = _m("sym", lines[index + 1]) if index + 1 < len(lines) else None
            next_body = _body(lines[index + 2]) if index + 2 < len(lines) else None
            frequency_continuation = bool(
                mode
                and next_sym
                and len(next_sym.group("v").split()) == len(mode.group("v").split())
                and next_body is not None
                and next_body.startswith(b"Frequencies")
            )
            if frequency_continuation:
                assert mode is not None
                modes = tuple(int(v) for v in mode.group("v").split())
                if any(b != a + 1 for a, b in zip(modes, modes[1:])) or (last_mode is not None and modes[0] != last_mode + 1):
                    return _line_fail("unparseable-frequency-block", line)
                group_modes, group_start, state = modes, line.start, "FREQ_SYM"; consumed(line)
            else:
                state, failed = body_step(line, state)
                if failed: return failed
        elif state in {"OPT_MAX_FORCE", "OPT_RMS_FORCE", "OPT_MAX_DISP", "OPT_RMS_DISP"}:
            spec = {"OPT_MAX_FORCE": (b"Maximum Force", "OPT_RMS_FORCE"), "OPT_RMS_FORCE": (b"RMS Force", "OPT_MAX_DISP"), "OPT_MAX_DISP": (b"Maximum Displacement", "OPT_RMS_DISP"), "OPT_RMS_DISP": (b"RMS Displacement", "OPT_AFTER")}
            label, next_state = spec[state]
            failed = _opt_row(line, label)
            if failed:
                if _orphan(line): return _line_fail("unparseable-orphan-anchor", line)
                return failed
            consumed(line)
            state = next_state
        elif state == "OPT_AFTER":
            predicted = _predicted(line)
            if isinstance(predicted, _Recognition): return predicted
            if predicted:
                if predicted_seen: return _line_fail("unparseable-optimization-block", line)
                predicted_seen = True; consumed(line)
            elif _m("opt_done", line): opt_done, state = line, "OPT_STATIONARY"; consumed(line)
            else: state, advance = return_state, False
        elif state == "OPT_STATIONARY":
            if _m("stationary", line):
                assert opt_done is not None
                opts.append(_span(source, opt_done.start, opt_done.end)); stations.append(_span(source, line.start, line.end)); state = return_state; consumed(line)
            elif _orphan(line, {"stationary"}): return _line_fail("unparseable-orphan-anchor", line)
            else: return _line_fail("unparseable-optimization-block", line)
        elif state in {"FREQ_HEAD_2", "FREQ_HEAD_3", "FREQ_HEAD_4"}:
            wanted, next_state = {"FREQ_HEAD_2": ("fh2", "FREQ_HEAD_3"), "FREQ_HEAD_3": ("fh3", "FREQ_HEAD_4"), "FREQ_HEAD_4": ("fh4", "FREQUENCY_EMPTY")}[state]
            if _m(wanted, line): state = next_state; consumed(line)
            elif _orphan(line, {wanted}): return _line_fail("unparseable-orphan-anchor", line)
            else: return _line_fail("unparseable-frequency-block", line)
        elif state == "FREQUENCY_EMPTY":
            mode = _m("modes", line)
            if _m("blank", line): pass
            elif mode:
                modes = tuple(int(v) for v in mode.group("v").split())
                if any(b != a + 1 for a, b in zip(modes, modes[1:])) or (
                    last_mode is not None and modes[0] != last_mode + 1
                ):
                    return _line_fail("unparseable-frequency-block", line)
                group_modes, group_start, state = modes, line.start, "FREQ_SYM"; consumed(line)
            elif _orphan(line, {"modes"}): return _line_fail("unparseable-orphan-anchor", line)
            else: return _line_fail("unparseable-frequency-block", line)
        elif state == "FREQ_SYM":
            sym = _m("sym", line)
            if sym and len(sym.group("v").split()) == len(group_modes): state = "FREQ_VALUES"; consumed(line)
            elif _orphan(line, {"sym"}): return _line_fail("unparseable-orphan-anchor", line)
            else: return _line_fail("unparseable-frequency-block", line)
        elif state in {"FREQ_VALUES", "FREQ_MASS", "FREQ_FORCE", "FREQ_IR"}:
            label, exact_name, next_state = {"FREQ_VALUES": (b"Frequencies", "freq", "FREQ_MASS"), "FREQ_MASS": (b"Red. masses", "mass", "FREQ_FORCE"), "FREQ_FORCE": (b"Frc consts", "force", "FREQ_IR"), "FREQ_IR": (b"IR Inten", "ir", "FREQUENCY_BODY")}[state]
            exact = _m(exact_name, line)
            if exact and len(exact.group("v").split()) == len(group_modes):
                values = tuple(_number(raw) for raw in exact.group("v").split())
                if any(v is None for v in values): parsed = _series(line, label, len(group_modes))
                else: parsed = tuple(v for v in values if v is not None)
            elif _orphan(line, {exact_name}): return _line_fail("unparseable-orphan-anchor", line)
            else: parsed = _series(line, label, len(group_modes))
            if isinstance(parsed, _Recognition): return parsed
            consumed(line)
            if state == "FREQ_VALUES": group_values = parsed
            if state == "FREQ_IR":
                assert group_start is not None
                freq_blocks.append({"source_span": _span(source, group_start, line.end), "frequencies_cm-1": group_values}); last_mode = group_modes[-1]
            state = next_state
        elif state in {"GEOM_SEP_1", "GEOM_HEAD_1", "GEOM_HEAD_2", "GEOM_SEP_2"}:
            wanted, next_state = {"GEOM_SEP_1": ("sep", "GEOM_HEAD_1"), "GEOM_HEAD_1": ("gh1", "GEOM_HEAD_2"), "GEOM_HEAD_2": ("gh2", "GEOM_SEP_2"), "GEOM_SEP_2": ("sep", "GEOM_ROWS")}[state]
            if _m(wanted, line): state = next_state; consumed(line)
            elif _orphan(line, {wanted}): return _line_fail("unparseable-orphan-anchor", line)
            else: return _line_fail("unparseable-geometry-block", line)
        elif state == "GEOM_ROWS":
            body = _body(line)
            if body is not None and body.startswith(b"-"):
                if not _m("sep", line) or not geometry_atoms: return _line_fail("unparseable-geometry-block", line)
                assert geometry_start is not None and geometry_kind is not None
                geometries.append({"orientation_kind": geometry_kind, "units": "angstrom", "source_span": _span(source, geometry_start, line.end), "atoms": tuple(geometry_atoms)}); state = return_state; consumed(line)
            elif _orphan(line): return _line_fail("unparseable-orphan-anchor", line)
            else:
                atom, failed = _atom(line, len(geometry_atoms) + 1)
                if failed: return failed
                assert atom is not None; geometry_atoms.append(atom); consumed(line)
        elif state == "TERMINATED":
            if _m("blank", line): pass
            elif _m("internal_enter", line):
                if terminals[-1]["kind"] != "normal-termination":
                    return _line_fail("unparseable-trailing-content", line)
                state = "INTERNAL_ENTER"; consumed(line)
            elif (internal := _m("internal", line)):
                step = int(internal.group("n"))
                if terminals[-1]["kind"] != "normal-termination" or step != next_internal_step:
                    return _line_fail("unparseable-ambiguous-transition", line)
                next_internal_step += 1
                state, echo_molecule = "INPUT_MOLECULE", False; consumed(line)
            elif _m("job", line) or _m("link1", line): return _line_fail("unsupported-multiple-job", line, ParseStatus.UNSUPPORTED)
            elif _m("other_program", line): return _line_fail("unsupported-program", line, ParseStatus.UNSUPPORTED)
            elif _terminal(line): return _line_fail("unparseable-terminal", line)
            else: return _line_fail("unparseable-trailing-content", line)
        elif state == "INTERNAL_ENTER":
            internal = _m("internal", line)
            if internal is None:
                return _line_fail("unparseable-ambiguous-transition", line)
            step = int(internal.group("n"))
            if step != next_internal_step:
                return _line_fail("unparseable-ambiguous-transition", line)
            next_internal_step += 1
            state, echo_molecule = "INPUT_MOLECULE", False; consumed(line)
        if advance: index += 1

    last_span = None if last_grammar_line is None else (last_grammar_line.start, last_grammar_line.end)
    if state == "PREAMBLE": return _fail("unparseable-job-start", len(data), None)
    if state in {"INPUT_ECHO", "INPUT_MOLECULE", "INPUT_BOUND"}: return _fail("unparseable-echo-boundary", len(data), last_span)
    if state == "INTERNAL_ENTER": return _fail("unparseable-ambiguous-transition", len(data), last_span)
    if state.startswith("OPT_"): return _fail("unparseable-optimization-block", len(data), last_span)
    if state == "FREQUENCY_BODY": return _fail("unparseable-terminal", len(data), last_span)
    if state.startswith("FREQ_") or state.startswith("FREQUENCY_"): return _fail("unparseable-frequency-block", len(data), last_span)
    if state.startswith("GEOM_"): return _fail("unparseable-geometry-block", len(data), last_span)
    if state in {"MACHINE_BODY", "FREQUENCY_BODY"}: return _fail("unparseable-terminal", len(data), last_span)
    if state != "TERMINATED" or job_start is None or terminal_line is None or not terminals: return _fail("unparseable-ambiguous-transition", len(data), None)

    frequencies = tuple(value for block in freq_blocks for value in block["frequencies_cm-1"])
    normal_count = sum(item["kind"] == "normal-termination" for item in terminals)
    error_count = sum(item["kind"] == "error-termination" for item in terminals)
    terminal_kind = "normal-termination" if error_count == 0 else "error-termination"
    facts = {
        "facts_schema_version": 1, "grammar_id": GRAMMAR_ID, "source_artifact": dict(source),
        "job_section": _span(source, job_start.start, terminal_line.end), "program_status": terminal_kind,
        "normal_termination_count": normal_count, "error_termination_count": error_count,
        "termination_evidence": tuple(terminals), "optimization_completed_marker": bool(opts), "optimization_completed_evidence": tuple(opts),
        "stationary_point_marker": bool(stations), "stationary_point_evidence": tuple(stations), "scf_calculation_count": len(scfs),
        "scf_calculations": tuple(scfs), "final_energy_hartree": scfs[-1]["energy_hartree"] if scfs else None,
        "frequency_count": len(frequencies), "frequency_parse_complete": True, "imaginary_frequency_count": sum(v < 0 for v in frequencies),
        "frequencies_cm-1": frequencies, "frequency_blocks": tuple(freq_blocks), "thermochemistry": thermos, "geometry_blocks": tuple(geometries),
    }
    return _Recognition(ParseStatus.PARSED, facts, None)


def _verify(envelope: OutputEnvelope, supplied: Mapping[str, bytes]) -> tuple[object, ...]:
    expected = {item.logical_name: item for item in envelope.artifacts}
    if set(supplied) != set(expected): raise MalformedEnvelopeError("artifact bytes must match the exact envelope artifact set")
    for name, data in supplied.items():
        if not isinstance(data, bytes): raise MalformedEnvelopeError("captured artifact content must be bytes")
        item = expected[name]
        if len(data) != item.size_bytes: raise MalformedEnvelopeError(f"artifact size does not match envelope: {name}")
        if hashlib.sha256(data).hexdigest() != item.sha256: raise MalformedEnvelopeError(f"artifact digest does not match envelope: {name}")
    return tuple(item for item in envelope.artifacts if item.artifact_kind == "gaussian-log")


class GaussianJobParser:
    """Parse one exact Gaussian 16 job into source-attributed neutral facts."""

    parser_name = PARSER_NAME
    parser_version = PARSER_VERSION
    result_kind = RESULT_KIND

    def parse(self, envelope: OutputEnvelope, artifact_bytes: Mapping[str, bytes]) -> ParseOutcome:
        logs = _verify(envelope, artifact_bytes)
        if envelope.capture_completeness is CaptureCompleteness.PARTIAL:
            parsed = _fail("capture-partial", None, None, ParseStatus.PARTIAL)
        elif len(logs) != 1:
            parsed = _fail("unsupported-gaussian-log-cardinality", None, None, ParseStatus.UNSUPPORTED)
        else:
            item = logs[0]
            source = {"envelope_observation_id": envelope.observation_id, "artifact_kind": item.artifact_kind, "logical_name": item.logical_name, "sha256": item.sha256, "size_bytes": item.size_bytes}
            parsed = _recognize(artifact_bytes[item.logical_name], source)
        return ParseOutcome(attempt_id=envelope.attempt_id, envelope_observation_id=envelope.observation_id, parser_name=self.parser_name, parser_version=self.parser_version, result_kind=self.result_kind, parse_status=parsed.status, facts=parsed.facts, diagnostics=() if parsed.diagnostic is None else (parsed.diagnostic,))
