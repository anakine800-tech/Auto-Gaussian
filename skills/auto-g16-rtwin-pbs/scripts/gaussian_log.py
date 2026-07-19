#!/usr/bin/env python3
"""Parse Gaussian logs into a compact machine-readable result."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any


ELEMENTS = [
    "X", "H", "He", "Li", "Be", "B", "C", "N", "O", "F", "Ne",
    "Na", "Mg", "Al", "Si", "P", "S", "Cl", "Ar", "K", "Ca",
    "Sc", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn",
    "Ga", "Ge", "As", "Se", "Br", "Kr", "Rb", "Sr", "Y", "Zr",
    "Nb", "Mo", "Tc", "Ru", "Rh", "Pd", "Ag", "Cd", "In", "Sn",
    "Sb", "Te", "I", "Xe",
]
R_J_MOL_K = 8.31446261815324
R_L_ATM_MOL_K = 0.082057366080960
HARTREE_J_MOL = 2625499.6394799
HARTREE_KCAL_MOL = 627.5094740631
PARSER_NAME = "auto-g16-gaussian-log"
PARSER_VERSION = "2.0.0"
PARSER_SCHEMA = "auto-g16-gaussian-log-parser/2"


def _parse_frequencies(text: str) -> tuple[list[float], list[dict[str, Any]]]:
    """Parse every frequency token without silently discarding corruption."""

    frequencies: list[float] = []
    diagnostics: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        match = re.match(r"^\s*Frequencies\s+--\s*(.*)$", line)
        if not match:
            continue
        tokens = match.group(1).split()
        if not tokens:
            diagnostics.append({"code": "empty_frequency_group", "line": line_number, "token": None})
            continue
        for token in tokens:
            try:
                value = float(token.replace("D", "E").replace("d", "e"))
            except ValueError:
                diagnostics.append({"code": "malformed_frequency_token", "line": line_number, "token": token})
                continue
            if not math.isfinite(value):
                diagnostics.append({"code": "nonfinite_frequency_token", "line": line_number, "token": token})
                continue
            frequencies.append(value)
    return frequencies, diagnostics


def _geometry_is_linear(coordinates: list[dict[str, Any]]) -> bool | None:
    """Classify exact parsed Cartesian geometry for the 3N-5/3N-6 gate."""

    if not coordinates:
        return None
    if len(coordinates) <= 2:
        return True
    points = [(float(atom["x"]), float(atom["y"]), float(atom["z"])) for atom in coordinates]
    left, right = max(
        ((a, b) for a in range(len(points)) for b in range(a + 1, len(points))),
        key=lambda pair: math.dist(points[pair[0]], points[pair[1]]),
    )
    span = math.dist(points[left], points[right])
    if span <= 1e-10:
        return None
    origin = points[left]
    direction = tuple((points[right][axis] - origin[axis]) / span for axis in range(3))
    tolerance = max(1e-6, span * 1e-7)
    for point in points:
        delta = tuple(point[axis] - origin[axis] for axis in range(3))
        projection = sum(delta[axis] * direction[axis] for axis in range(3))
        perpendicular = tuple(delta[axis] - projection * direction[axis] for axis in range(3))
        if math.sqrt(sum(value * value for value in perpendicular)) > tolerance:
            return False
    return True


def expected_vibrational_mode_count(coordinates: list[dict[str, Any]]) -> tuple[int | None, bool | None]:
    atom_count = len(coordinates)
    linear = _geometry_is_linear(coordinates)
    if atom_count == 0 or linear is None:
        return None, linear
    if atom_count == 1:
        return 0, True
    return 3 * atom_count - (5 if linear else 6), linear


def last_orientation(text: str) -> list[dict[str, Any]]:
    matches = list(re.finditer(r"(?m)^\s*(?:Standard|Input) orientation:\s*$", text))
    for match in reversed(matches):
        lines = text[match.end():].splitlines()
        separators = [i for i, line in enumerate(lines) if re.match(r"^\s*-{10,}\s*$", line)]
        if len(separators) < 3:
            continue
        coordinates: list[dict[str, Any]] = []
        for line in lines[separators[1] + 1:separators[2]]:
            fields = line.split()
            if len(fields) < 6:
                continue
            try:
                center = int(fields[0])
                atomic_number = int(fields[1])
                x, y, z = map(float, fields[3:6])
            except ValueError:
                continue
            symbol = ELEMENTS[atomic_number] if 0 < atomic_number < len(ELEMENTS) else f"X{atomic_number}"
            coordinates.append(
                {
                    "center": center,
                    "atomic_number": atomic_number,
                    "element": symbol,
                    "x": x,
                    "y": y,
                    "z": z,
                }
            )
        if coordinates:
            return coordinates
    return []


def diagnose(text: str) -> list[dict[str, str]]:
    rules = [
        ("zsymb_eof", "End of file in ZSymb", "Repair Gaussian section termination and trailing blank lines; do not retry unchanged."),
        ("scf_convergence", "Convergence failure", "Review the wavefunction and consider an explicitly approved SCF=XQC restart."),
        ("irc_corrector_convergence", "Maximum number of corrector steps exceded", "Preserve both directional results and require a new scientific approval before changing IRC integration settings or retrying."),
        ("optimization_steps", "Number of steps exceeded", "Review geometry and convergence; consider an explicitly approved Opt=Restart from checkpoint."),
        ("memory", "Out-of-memory", "Reduce memory demand or resource use; never exceed the 120 GB server ceiling."),
        ("memory", "galloc", "Inspect the final Link error and reduce memory demand if confirmed."),
        ("disk", "Erroneous write", "Check free space inside the SDL project and scratch directories; do not write elsewhere."),
        ("termination", "Error termination", "Inspect the final 80–120 log lines before changing chemistry or resubmitting."),
    ]
    found: list[dict[str, str]] = []
    seen: set[str] = set()
    for code, needle, recommendation in rules:
        if needle.lower() in text.lower() and code not in seen:
            found.append({"code": code, "evidence": needle, "recommendation": recommendation})
            seen.add(code)
    return found


def analyze_log_text(text: str) -> dict[str, Any]:
    energy_values = [
        float(value.replace("D", "E"))
        for value in re.findall(r"SCF Done:\s+E\([^)]*\)\s*=\s*([-+0-9.DEded]+)", text)
    ]
    steps = [int(value) for value in re.findall(r"Step number\s+(\d+)", text)]
    frequencies, frequency_parse_diagnostics = _parse_frequencies(text)
    normal_count = text.count("Normal termination of Gaussian")
    error_count = text.count("Error termination")
    normal = normal_count > 0
    error = error_count > 0
    optimization_completed = "Optimization completed" in text
    stationary_point = "Stationary point found" in text
    coordinates = last_orientation(text)
    expected_frequency_count, linear = expected_vibrational_mode_count(coordinates)
    last_normal = text.rfind("Normal termination of Gaussian")
    last_error = text.rfind("Error termination")
    status = "failed" if last_error > last_normal else "completed" if normal else "incomplete"
    return {
        "schema": "gaussian-result/1",
        "status": status,
        "normal_termination": normal,
        "normal_termination_count": normal_count,
        "error_termination": error,
        "error_termination_count": error_count,
        "optimization_completed": optimization_completed,
        "stationary_point_found": stationary_point,
        "optimization_success": normal and optimization_completed and stationary_point,
        "optimization_steps": max(steps) if steps else 0,
        "scf_calculations": len(energy_values),
        "final_energy_hartree": energy_values[-1] if energy_values else None,
        "frequency_count": len(frequencies),
        "expected_frequency_count": expected_frequency_count,
        "frequency_parse_complete": not frequency_parse_diagnostics,
        "frequency_parse_diagnostics": frequency_parse_diagnostics,
        "imaginary_frequency_count": sum(value < 0 for value in frequencies),
        "frequencies_cm-1": frequencies,
        "final_coordinate_count": len(coordinates),
        "final_coordinates": coordinates,
        "linearity": "linear" if linear is True else "nonlinear" if linear is False else "undetermined",
        "parser": {"name": PARSER_NAME, "version": PARSER_VERSION, "schema": PARSER_SCHEMA},
        "diagnostics": diagnose(text),
    }


def _last_float(text: str, pattern: str) -> float | None:
    values = re.findall(pattern, text, flags=re.I | re.M)
    return float(values[-1].replace("D", "E")) if values else None


def standard_state_correction_hartree(temperature_k: float, standard_state: str) -> float:
    if temperature_k <= 0:
        raise ValueError("temperature must be positive")
    if standard_state == "1atm":
        return 0.0
    if standard_state != "1M":
        raise ValueError("standard_state must be 1atm or 1M")
    return (
        R_J_MOL_K
        * temperature_k
        * math.log(R_L_ATM_MOL_K * temperature_k)
        / HARTREE_J_MOL
    )


def analyze_workflow_log_text(
    text: str,
    *,
    temperature_k: float,
    standard_state: str,
    expected_stages: int = 3,
) -> dict[str, Any]:
    """Analyze a linked Opt -> Freq -> single-point Gaussian output."""

    base = analyze_log_text(text)
    thermochemistry = {
        "zero_point_correction_hartree": _last_float(
            text, r"Zero-point correction=\s*([-+0-9.DEded]+)"
        ),
        "thermal_correction_energy_hartree": _last_float(
            text, r"Thermal correction to Energy=\s*([-+0-9.DEded]+)"
        ),
        "thermal_correction_enthalpy_hartree": _last_float(
            text, r"Thermal correction to Enthalpy=\s*([-+0-9.DEded]+)"
        ),
        "thermal_correction_gibbs_hartree": _last_float(
            text, r"Thermal correction to Gibbs Free Energy=\s*([-+0-9.DEded]+)"
        ),
        "frequency_sum_electronic_zpe_hartree": _last_float(
            text, r"Sum of electronic and zero-point Energies=\s*([-+0-9.DEded]+)"
        ),
        "frequency_sum_electronic_enthalpy_hartree": _last_float(
            text, r"Sum of electronic and thermal Enthalpies=\s*([-+0-9.DEded]+)"
        ),
        "frequency_sum_electronic_gibbs_hartree": _last_float(
            text, r"Sum of electronic and thermal Free Energies=\s*([-+0-9.DEded]+)"
        ),
    }
    state_correction = standard_state_correction_hartree(temperature_k, standard_state)
    sp_energy = base["final_energy_hartree"]
    thermal_g = thermochemistry["thermal_correction_gibbs_hartree"]
    composite_1atm = sp_energy + thermal_g if sp_energy is not None and thermal_g is not None else None
    composite_target = composite_1atm + state_correction if composite_1atm is not None else None
    thermochemistry.update(
        {
            "single_point_energy_hartree": sp_energy,
            "temperature_k": temperature_k,
            "standard_state": standard_state,
            "standard_state_correction_hartree_per_species": state_correction,
            "standard_state_correction_kcal_mol_per_species": state_correction * HARTREE_KCAL_MOL,
            "composite_gibbs_1atm_hartree": composite_1atm,
            "composite_gibbs_target_hartree": composite_target,
            "quasi_harmonic_correction_applied": False,
        }
    )
    execution_complete = (
        base["normal_termination_count"] >= expected_stages
        and base["error_termination_count"] == 0
    )
    expected_frequency_count = base["expected_frequency_count"]
    frequency_complete = (
        expected_frequency_count is not None
        and base["frequency_parse_complete"] is True
        and base["frequency_count"] == expected_frequency_count
        and thermal_g is not None
    )
    minimum_validated = (
        base["optimization_success"]
        and frequency_complete
        and base["imaginary_frequency_count"] == 0
    )
    workflow_success = execution_complete and minimum_validated and composite_target is not None
    low_frequencies = [
        value for value in base["frequencies_cm-1"] if 0.0 <= value < 100.0
    ]
    result = dict(base)
    result.update(
        {
            "schema": "gaussian-opt-freq-sp-result/1",
            "status": (
                "completed" if workflow_success
                else "validation_failed" if execution_complete
                else base["status"]
            ),
            "expected_stage_count": expected_stages,
            "execution_complete": execution_complete,
            "frequency_complete": frequency_complete,
            "minimum_validated": minimum_validated,
            "single_point_complete": execution_complete and sp_energy is not None,
            "workflow_success": workflow_success,
            "low_frequency_count_below_100_cm-1": len(low_frequencies),
            "low_frequencies_cm-1": low_frequencies,
            "thermochemistry": thermochemistry,
            "scientific_notes": [
                "No quasi-harmonic correction was applied.",
                "The 1 atm to 1 M correction is per independently treated species; reaction corrections depend on stoichiometry.",
            ],
        }
    )
    return result


def _write_result_files(result: dict[str, Any], log_path: Path, output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    result_path = output_dir / "result.json"
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    coordinates = result["final_coordinates"]
    if coordinates:
        xyz_path = output_dir / "optimized.xyz"
        lines = [str(len(coordinates)), f"Extracted from {log_path.name}"]
        lines.extend(
            f"{item['element']:<3} {item['x']: .8f} {item['y']: .8f} {item['z']: .8f}"
            for item in coordinates
        )
        xyz_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        result["optimized_xyz"] = str(xyz_path)
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def analyze_log_file(log_path: Path, output_dir: Path | None = None) -> dict[str, Any]:
    text = log_path.read_text(encoding="utf-8", errors="replace")
    result = analyze_log_text(text)
    result["log"] = str(log_path.resolve())
    if output_dir is not None:
        _write_result_files(result, log_path, output_dir)
    return result


def analyze_workflow_log_file(
    log_path: Path,
    output_dir: Path | None,
    *,
    temperature_k: float,
    standard_state: str,
    expected_stages: int = 3,
) -> dict[str, Any]:
    text = log_path.read_text(encoding="utf-8", errors="replace")
    result = analyze_workflow_log_text(
        text,
        temperature_k=temperature_k,
        standard_state=standard_state,
        expected_stages=expected_stages,
    )
    result["log"] = str(log_path.resolve())
    if output_dir is not None:
        _write_result_files(result, log_path, output_dir)
    return result
