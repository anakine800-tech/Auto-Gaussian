#!/usr/bin/env python3
"""Offline audit utilities for Gaussian TS–Freq–IRC workflow families.

This module intentionally does not contain network, scheduler, or Gaussian execution code.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import sys
from pathlib import Path
from typing import Any

SCHEMA = "gaussian-ts-irc-workflow/1"
TERMINAL_TEMPLATE_SCHEMA = "gaussian-terminal-intake-template/1"
TERMINAL_INTAKE_SCHEMA = "gaussian-terminal-intake/1"
PROJECT_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,14}$")
ELEMENTS = """X H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au Hg Tl Pb Bi Po At Rn Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf Es Fm Md No Lr Rf Db Sg Bh Hs Mt Ds Rg Cn Nh Fl Mc Lv Ts Og""".split()
COVALENT_RADII_ANGSTROM = {
    "H": 0.31,
    "B": 0.84,
    "C": 0.76,
    "N": 0.71,
    "O": 0.66,
    "F": 0.57,
    "Si": 1.11,
    "P": 1.07,
    "S": 1.05,
    "Cl": 1.02,
    "Se": 1.20,
    "Br": 1.20,
    "I": 1.39,
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _float(value: str) -> float:
    return float(value.replace("D", "E").replace("d", "e"))


def parse_cartesian_input(path: Path) -> dict[str, Any]:
    """Parse a standard Cartesian Gaussian input without interpreting chemistry."""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    index = 0
    while index < len(lines) and (not lines[index].strip() or lines[index].lstrip().startswith("%")):
        index += 1
    if index < len(lines) and lines[index].lstrip().startswith("#"):
        while index < len(lines) and lines[index].strip():
            index += 1
        while index < len(lines) and not lines[index].strip():
            index += 1
    if index >= len(lines):
        raise ValueError(f"{path}: missing title/charge/multiplicity section")
    while index < len(lines) and lines[index].strip():
        index += 1
    while index < len(lines) and not lines[index].strip():
        index += 1
    if index >= len(lines):
        raise ValueError(f"{path}: missing charge/multiplicity")
    charge_mult = lines[index].split()
    if len(charge_mult) != 2:
        raise ValueError(f"{path}: charge/multiplicity must contain exactly two values")
    try:
        charge, multiplicity = map(int, charge_mult)
    except ValueError as exc:
        raise ValueError(f"{path}: invalid charge/multiplicity") from exc
    index += 1
    atoms: list[dict[str, Any]] = []
    for line in lines[index:]:
        if not line.strip():
            break
        fields = line.split()
        if len(fields) < 4:
            raise ValueError(f"{path}: non-Cartesian or malformed coordinate: {line!r}")
        try:
            x, y, z = (_float(fields[1]), _float(fields[2]), _float(fields[3]))
        except ValueError as exc:
            raise ValueError(f"{path}: invalid Cartesian coordinate: {line!r}") from exc
        atoms.append({"index": len(atoms) + 1, "element": fields[0], "x": x, "y": y, "z": z})
    if not atoms:
        raise ValueError(f"{path}: no Cartesian atoms")
    return {"path": str(path.resolve()), "sha256": sha256(path), "charge": charge, "multiplicity": multiplicity, "atoms": atoms}


def _link0_value(path: Path, key: str) -> str | None:
    wanted = key.lower()
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("%") and "=" in line:
            name, value = line[1:].split("=", 1)
            if name.strip().lower() == wanted:
                return value.strip()
    return None


def _charge_multiplicity_from_log(text: str) -> tuple[int, int]:
    matches = re.findall(r"Charge\s*=\s*(-?\d+)\s+Multiplicity\s*=\s*(\d+)", text)
    if not matches:
        raise ValueError("TS log has no charge/multiplicity record")
    values = {(int(charge), int(multiplicity)) for charge, multiplicity in matches}
    if len(values) != 1:
        raise ValueError("TS log contains inconsistent charge/multiplicity records")
    return next(iter(values))


def audit_checkpoint_provenance(
    ts_input_path: Path,
    ts_log_path: Path,
    ts_result_path: Path,
    checkpoint_path: Path,
    review_path: Path,
    decision_path: Path,
) -> dict[str, Any]:
    """Bind a checkpoint hash to the reviewed TS atom order without decoding the binary file."""
    for label, path in {
        "TS input": ts_input_path,
        "TS log": ts_log_path,
        "TS result": ts_result_path,
        "checkpoint": checkpoint_path,
        "mode review": review_path,
        "mode decision": decision_path,
    }.items():
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"{label} must be an existing non-symlink file")
    if checkpoint_path.suffix.lower() != ".chk":
        raise ValueError("checkpoint must use a local .chk basename")

    ts_input = parse_cartesian_input(ts_input_path)
    declared_checkpoint = _link0_value(ts_input_path, "chk")
    if declared_checkpoint != checkpoint_path.name:
        raise ValueError("checkpoint filename does not match %chk in the reviewed TS input")

    log_text = ts_log_path.read_text(encoding="utf-8", errors="replace")
    result = json.loads(ts_result_path.read_text(encoding="utf-8"))
    review = json.loads(review_path.read_text(encoding="utf-8"))
    decision = json.loads(decision_path.read_text(encoding="utf-8"))
    if result.get("schema") != "gaussian-ts-freq-result/1" or not result.get("first_order_saddle_candidate"):
        raise ValueError("checkpoint audit requires an eligible TS/Freq result")
    if result.get("log_sha256") != sha256(ts_log_path):
        raise ValueError("TS result is not bound to the supplied TS log")
    if review.get("schema") != "gaussian-ts-mode-review/1" or review.get("ts_result_sha256") != sha256(ts_result_path):
        raise ValueError("mode review is not bound to the supplied TS result")
    if decision.get("schema") != "gaussian-ts-mode-decision/1" or decision.get("decision") != "accepted" or decision.get("confirmed") is not True:
        raise ValueError("checkpoint audit requires an accepted mode decision")
    if decision.get("ts_result_sha256") != sha256(ts_result_path) or decision.get("mode_review_sha256") != sha256(review_path):
        raise ValueError("mode decision hashes do not match the reviewed TS artifacts")

    charge, multiplicity = _charge_multiplicity_from_log(log_text)
    if (charge, multiplicity) != (ts_input["charge"], ts_input["multiplicity"]):
        raise ValueError("charge/multiplicity differs between TS input and completed TS log")
    log_geometry = _last_orientation(log_text)
    result_geometry = result.get("final_coordinates", [])
    input_numbers = []
    element_to_number = {element: number for number, element in enumerate(ELEMENTS) if element != "X"}
    for atom in ts_input["atoms"]:
        number = element_to_number.get(atom["element"])
        if number is None:
            raise ValueError(f"unsupported element in TS atom-order audit: {atom['element']}")
        input_numbers.append(number)
    log_numbers = [atom.get("atomic_number") for atom in log_geometry]
    result_numbers = [atom.get("atomic_number") for atom in result_geometry]
    if not input_numbers or input_numbers != log_numbers or input_numbers != result_numbers:
        raise ValueError("atom order differs among TS input, completed log, and TS result")
    if [atom.get("index") for atom in result_geometry] != list(range(1, len(input_numbers) + 1)):
        raise ValueError("TS result atom indices are not contiguous and one-based")

    imaginary_modes = result.get("imaginary_modes", [])
    if len(imaginary_modes) != 1:
        raise ValueError("checkpoint audit requires exactly one parsed imaginary mode")
    displacements = imaginary_modes[0].get("displacements", [])
    if [atom.get("index") for atom in displacements] != list(range(1, len(input_numbers) + 1)) or [atom.get("atomic_number") for atom in displacements] != input_numbers:
        raise ValueError("imaginary-mode displacement atom order differs from the reviewed TS order")

    atom_order = [
        {"index": index, "atomic_number": number, "element": ELEMENTS[number]}
        for index, number in enumerate(input_numbers, start=1)
    ]
    return {
        "schema": "gaussian-checkpoint-geometry-audit/1",
        "audit_status": "passed",
        "geometry_source": "reviewed_ts_checkpoint",
        "checkpoint_file": checkpoint_path.name,
        "checkpoint_sha256": sha256(checkpoint_path),
        "ts_input_sha256": sha256(ts_input_path),
        "ts_log_sha256": sha256(ts_log_path),
        "ts_result_sha256": sha256(ts_result_path),
        "mode_review_sha256": sha256(review_path),
        "mode_decision_sha256": sha256(decision_path),
        "charge": charge,
        "multiplicity": multiplicity,
        "atom_count": len(atom_order),
        "atom_order": atom_order,
        "checks": {
            "ts_input_checkpoint_name_matches": True,
            "ts_result_log_hash_matches": True,
            "charge_multiplicity_matches": True,
            "input_log_result_atom_order_matches": True,
            "imaginary_mode_atom_order_matches": True,
            "accepted_mode_decision_hashes_match": True,
        },
        "limitations": [
            "The binary checkpoint is identified by SHA-256; its internal records are not decoded.",
            "Atom order is established from the reviewed TS input/log/result provenance chain used to create the checkpoint.",
        ],
    }


def build_allcheck_irc_input(
    checkpoint_audit_path: Path,
    checkpoint_path: Path,
    output_path: Path,
    route: str,
    direction: str,
    memory: str,
    nprocshared: int,
) -> dict[str, Any]:
    """Build a coordinate-free IRC input bound to an audited TS checkpoint."""
    if output_path.exists() or output_path.with_suffix(".json").exists():
        raise ValueError("refusing to overwrite an existing AllCheck input or companion manifest")
    if output_path.suffix.lower() not in {".gjf", ".com"}:
        raise ValueError("AllCheck output must end in .gjf or .com")
    if not checkpoint_path.is_file() or checkpoint_path.is_symlink():
        raise ValueError("checkpoint must be an existing non-symlink file")
    audit = json.loads(checkpoint_audit_path.read_text(encoding="utf-8"))
    if audit.get("schema") != "gaussian-checkpoint-geometry-audit/1" or audit.get("audit_status") != "passed":
        raise ValueError("AllCheck input requires a passed checkpoint-geometry audit")
    if audit.get("checkpoint_file") != checkpoint_path.name or audit.get("checkpoint_sha256") != sha256(checkpoint_path):
        raise ValueError("checkpoint file or hash differs from the reviewed checkpoint audit")
    if direction not in {"forward", "reverse"}:
        raise ValueError("direction must be forward or reverse")
    _validate_directional_irc_route(route, direction)
    lowered = route.lower()
    if not re.search(r"\bgeom\s*=\s*allcheck\b", lowered):
        raise ValueError("coordinate-free IRC route must contain Geom=AllCheck")
    if not re.search(r"\bguess\s*=\s*read\b", lowered):
        raise ValueError("checkpoint IRC route must contain Guess=Read")
    if not re.search(r"\brcfc\b", lowered):
        raise ValueError("checkpoint IRC route must explicitly contain RCFC")
    if re.search(r"\brecorrect\s*=\s*never\b", lowered):
        raise ValueError("ReCorrect=Never is forbidden for an audited IRC path")
    if not isinstance(nprocshared, int) or not 1 <= nprocshared <= 44:
        raise ValueError("nprocshared must be an integer from 1 to 44")
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?(?:KB|MB|GB|TB)", memory, re.I):
        raise ValueError("memory must be an explicit Gaussian size such as 12GB")
    new_checkpoint = output_path.stem + ".chk"
    if new_checkpoint == checkpoint_path.name:
        raise ValueError("new %chk must differ from the reviewed %oldchk checkpoint")
    text = (
        f"%oldchk={checkpoint_path.name}\n"
        f"%chk={new_checkpoint}\n"
        f"%mem={memory}\n"
        f"%nprocshared={nprocshared}\n"
        f"{route.strip()}\n\n"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    staged_checkpoint = output_path.parent / checkpoint_path.name
    if staged_checkpoint.resolve() != checkpoint_path.resolve():
        if staged_checkpoint.exists():
            if staged_checkpoint.is_symlink() or not staged_checkpoint.is_file() or sha256(staged_checkpoint) != sha256(checkpoint_path):
                raise ValueError("refusing to overwrite a different staged checkpoint")
        else:
            shutil.copy2(checkpoint_path, staged_checkpoint)
    output_path.write_text(text, encoding="utf-8")
    manifest = {
        "schema": "gaussian-allcheck-input-manifest/1",
        "calculation_ready": True,
        "candidate_only": False,
        "warnings": [],
        "geometry_source": "geom_allcheck_from_reviewed_checkpoint",
        "no_explicit_molecule_specification": True,
        "direction": direction,
        "route": route.strip(),
        "input_sha256": sha256(output_path),
        "checkpoint_geometry_audit_sha256": sha256(checkpoint_audit_path),
        "checkpoint_file": audit["checkpoint_file"],
        "checkpoint_sha256": audit["checkpoint_sha256"],
        "charge": audit["charge"],
        "multiplicity": audit["multiplicity"],
        "atom_count": audit["atom_count"],
        "atom_order": audit["atom_order"],
    }
    output_path.with_suffix(".json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def audit_irc_endpoint_provenance(
    irc_input_path: Path,
    irc_log_path: Path,
    irc_result_path: Path,
    job_path: Path,
    checkpoint_path: Path,
    direction: str,
    chemical_side: str,
    expected_points: int,
    forming_pairs: list[tuple[int, int]],
) -> dict[str, Any]:
    """Bind a successful final IRC point to its exact continuation checkpoint."""
    for label, path in {
        "IRC input": irc_input_path,
        "IRC log": irc_log_path,
        "IRC result": irc_result_path,
        "job record": job_path,
        "IRC checkpoint": checkpoint_path,
    }.items():
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"{label} must be an existing non-symlink file")
    if direction not in {"forward", "reverse"}:
        raise ValueError("direction must be forward or reverse")
    if chemical_side not in {"reactant", "product"}:
        raise ValueError("chemical_side must be reactant or product after structural review")
    if expected_points < 1:
        raise ValueError("expected_points must be positive")
    if not forming_pairs:
        raise ValueError("at least one reviewed forming-bond pair is required")

    input_text = irc_input_path.read_text(encoding="utf-8", errors="replace")
    log_text = irc_log_path.read_text(encoding="utf-8", errors="replace")
    result = json.loads(irc_result_path.read_text(encoding="utf-8"))
    job = json.loads(job_path.read_text(encoding="utf-8"))
    if job.get("schema") != "gaussian-rtwin-pbs/1" or job.get("status") != "completed" or job.get("results_fetched") is not True:
        raise ValueError("endpoint audit requires a completed, fetched IRC job record")
    if job.get("input_sha256") != sha256(irc_input_path):
        raise ValueError("IRC input hash differs from the completed job record")
    gaussian = job.get("gaussian", {})
    route = str(gaussian.get("route", ""))
    _validate_directional_irc_route(route, direction)
    if not re.search(r"\bgeom\s*=\s*allcheck\b", route, re.I):
        raise ValueError("endpoint audit requires the successful IRC to use Geom=AllCheck")
    if gaussian.get("checkpoint") != checkpoint_path.name:
        raise ValueError("IRC checkpoint filename differs from the completed job record")
    if _link0_value(irc_input_path, "chk") != checkpoint_path.name:
        raise ValueError("IRC checkpoint filename differs from %chk in the completed input")
    if str(direction) not in input_text.lower():
        raise ValueError("IRC input does not contain its declared direction")

    if result.get("schema") != "gaussian-result/1" or result.get("status") != "completed" or result.get("normal_termination") is not True or result.get("error_termination") is True:
        raise ValueError("endpoint audit requires a normally terminated IRC result")
    completion = f"Calculation of {direction.upper()} path complete."
    if completion not in log_text or "Error termination" in log_text or "Normal termination of Gaussian 16" not in log_text:
        raise ValueError("IRC log lacks direction-specific completion and clean termination evidence")
    point_numbers = [int(value) for value in re.findall(r"Point Number:\s*(\d+)", log_text)]
    if not point_numbers or point_numbers[-1] != expected_points or max(point_numbers) != expected_points:
        raise ValueError("IRC log did not reach the declared final point")
    corrector_met = log_text.count("Delta-x Convergence Met")
    if corrector_met < expected_points:
        raise ValueError("not every declared IRC point has corrector convergence evidence")

    charge, multiplicity = _charge_multiplicity_from_log(log_text)
    geometry = _last_orientation(log_text)
    result_geometry = result.get("final_coordinates", [])
    if not geometry or len(geometry) != len(result_geometry):
        raise ValueError("IRC log/result final geometries are missing or differ in atom count")
    for log_atom, result_atom in zip(geometry, result_geometry):
        if log_atom.get("index") != result_atom.get("center") or log_atom.get("atomic_number") != result_atom.get("atomic_number"):
            raise ValueError("IRC log/result atom order differs")
        if any(abs(float(log_atom[axis]) - float(result_atom[axis])) > 1e-6 for axis in ("x", "y", "z")):
            raise ValueError("IRC log/result final coordinates differ")
    atom_order = [
        {"index": atom["index"], "atomic_number": atom["atomic_number"], "element": atom["element"]}
        for atom in geometry
    ]
    geometry_by_index = {atom["index"]: atom for atom in geometry}
    distances = []
    for first, second in forming_pairs:
        if first not in geometry_by_index or second not in geometry_by_index:
            raise ValueError(f"forming pair {first},{second} is outside the endpoint geometry")
        distances.append({"pair": [first, second], "distance_angstrom": _distance(geometry_by_index[first], geometry_by_index[second])})

    return {
        "schema": "gaussian-irc-endpoint-audit/1",
        "audit_status": "passed",
        "project": job.get("project"),
        "job_id": job.get("job_id"),
        "direction": direction,
        "chemical_side": chemical_side,
        "completed_point": expected_points,
        "corrector_convergence_count": corrector_met,
        "checkpoint_file": checkpoint_path.name,
        "checkpoint_sha256": sha256(checkpoint_path),
        "irc_input_sha256": sha256(irc_input_path),
        "irc_log_sha256": sha256(irc_log_path),
        "irc_result_sha256": sha256(irc_result_path),
        "irc_job_sha256": sha256(job_path),
        "charge": charge,
        "multiplicity": multiplicity,
        "atom_count": len(atom_order),
        "atom_order": atom_order,
        "reviewed_forming_bond_distances": distances,
        "final_energy_hartree": result.get("final_energy_hartree"),
        "geometry_source": "final_irc_checkpoint",
        "checks": {
            "directional_path_complete": True,
            "all_points_corrector_converged": True,
            "normal_termination": True,
            "input_job_hash_matches": True,
            "checkpoint_name_matches": True,
            "log_result_atom_order_and_coordinates_match": True,
        },
        "limitations": [
            "The binary checkpoint is identified by SHA-256; its internal records are not decoded.",
            "Chemical-side assignment is a reviewed structural label; endpoint minimum status requires Opt-Freq with zero imaginary frequencies.",
        ],
    }


def build_allcheck_endpoint_input(
    endpoint_audit_path: Path,
    checkpoint_path: Path,
    output_path: Path,
    route: str,
    memory: str,
    nprocshared: int,
) -> dict[str, Any]:
    """Build a coordinate-free endpoint Opt-Freq input from a reviewed IRC checkpoint."""
    if output_path.exists() or output_path.with_suffix(".json").exists():
        raise ValueError("refusing to overwrite an existing endpoint input or manifest")
    if output_path.suffix.lower() not in {".gjf", ".com"}:
        raise ValueError("endpoint output must end in .gjf or .com")
    if not checkpoint_path.is_file() or checkpoint_path.is_symlink():
        raise ValueError("endpoint checkpoint must be an existing non-symlink file")
    audit = json.loads(endpoint_audit_path.read_text(encoding="utf-8"))
    if audit.get("schema") != "gaussian-irc-endpoint-audit/1" or audit.get("audit_status") != "passed":
        raise ValueError("endpoint input requires a passed IRC endpoint audit")
    if audit.get("checkpoint_file") != checkpoint_path.name or audit.get("checkpoint_sha256") != sha256(checkpoint_path):
        raise ValueError("endpoint checkpoint file or hash differs from the audit")
    if not route_is_complete(route):
        raise ValueError("endpoint route must be complete")
    lowered = route.lower()
    for required, message in (
        (r"\bopt\b", "endpoint route must contain Opt"),
        (r"\bfreq\b", "endpoint route must contain Freq"),
        (r"\bgeom\s*=\s*allcheck\b", "endpoint route must contain Geom=AllCheck"),
        (r"\bguess\s*=\s*read\b", "endpoint route must contain Guess=Read"),
    ):
        if not re.search(required, lowered):
            raise ValueError(message)
    if re.search(r"\b(?:irc|opt\s*=\s*\(?ts)\b", lowered):
        raise ValueError("endpoint route must not contain IRC or TS optimization keywords")
    if not isinstance(nprocshared, int) or not 1 <= nprocshared <= 44:
        raise ValueError("nprocshared must be an integer from 1 to 44")
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?(?:KB|MB|GB|TB)", memory, re.I):
        raise ValueError("memory must be an explicit Gaussian size such as 12GB")
    new_checkpoint = output_path.stem + ".chk"
    if new_checkpoint == checkpoint_path.name:
        raise ValueError("new endpoint %chk must differ from the IRC %oldchk")
    text = (
        f"%oldchk={checkpoint_path.name}\n"
        f"%chk={new_checkpoint}\n"
        f"%mem={memory}\n"
        f"%nprocshared={nprocshared}\n"
        f"{route.strip()}\n\n"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    staged_checkpoint = output_path.parent / checkpoint_path.name
    if staged_checkpoint.resolve() != checkpoint_path.resolve():
        if staged_checkpoint.exists():
            if staged_checkpoint.is_symlink() or not staged_checkpoint.is_file() or sha256(staged_checkpoint) != sha256(checkpoint_path):
                raise ValueError("refusing to overwrite a different staged IRC checkpoint")
        else:
            shutil.copy2(checkpoint_path, staged_checkpoint)
    output_path.write_text(text, encoding="utf-8")
    manifest = {
        "schema": "gaussian-allcheck-input-manifest/1",
        "calculation_ready": True,
        "candidate_only": False,
        "warnings": [],
        "continuation_kind": "endpoint_opt_freq",
        "geometry_source": "geom_allcheck_from_reviewed_checkpoint",
        "no_explicit_molecule_specification": True,
        "chemical_side": audit["chemical_side"],
        "source_irc_direction": audit["direction"],
        "route": route.strip(),
        "input_sha256": sha256(output_path),
        "irc_endpoint_audit_sha256": sha256(endpoint_audit_path),
        "checkpoint_file": audit["checkpoint_file"],
        "checkpoint_sha256": audit["checkpoint_sha256"],
        "charge": audit["charge"],
        "multiplicity": audit["multiplicity"],
        "atom_count": audit["atom_count"],
        "atom_order": audit["atom_order"],
    }
    output_path.with_suffix(".json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def _hill_formula(elements: list[str]) -> str:
    counts: dict[str, int] = {}
    for element in elements:
        counts[element] = counts.get(element, 0) + 1
    if "C" in counts:
        order = ["C"] + (["H"] if "H" in counts else []) + sorted(
            element for element in counts if element not in {"C", "H"}
        )
    else:
        order = sorted(counts)
    return "".join(element + (str(counts[element]) if counts[element] != 1 else "") for element in order)


def propose_endpoint_components(
    endpoint_audit_path: Path,
    irc_result_path: Path,
    bond_scale: float = 1.25,
) -> dict[str, Any]:
    """Propose disconnected endpoint components without assigning fragment chemistry or spin."""
    for label, path in {"endpoint audit": endpoint_audit_path, "IRC result": irc_result_path}.items():
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"{label} must be an existing non-symlink file")
    if not 1.0 <= bond_scale <= 1.5:
        raise ValueError("bond_scale must be between 1.0 and 1.5")
    audit = json.loads(endpoint_audit_path.read_text(encoding="utf-8"))
    result = json.loads(irc_result_path.read_text(encoding="utf-8"))
    if audit.get("schema") != "gaussian-irc-endpoint-audit/1" or audit.get("audit_status") != "passed":
        raise ValueError("component proposal requires a passed IRC endpoint audit")
    if audit.get("irc_result_sha256") != sha256(irc_result_path):
        raise ValueError("IRC result hash differs from the endpoint audit")
    if result.get("schema") != "gaussian-result/1" or result.get("status") != "completed":
        raise ValueError("component proposal requires a completed IRC result")
    raw_geometry = result.get("final_coordinates")
    if not isinstance(raw_geometry, list) or not raw_geometry:
        raise ValueError("IRC result has no final coordinates")
    atom_order = audit.get("atom_order")
    if not isinstance(atom_order, list) or len(atom_order) != len(raw_geometry):
        raise ValueError("endpoint audit atom order differs from the IRC result geometry")

    geometry: list[dict[str, Any]] = []
    for expected_index, (order_item, atom) in enumerate(zip(atom_order, raw_geometry), start=1):
        index = atom.get("center", atom.get("index"))
        number = atom.get("atomic_number")
        element = atom.get("element")
        if index != expected_index or order_item.get("index") != expected_index:
            raise ValueError("endpoint atom indices must be contiguous and one-based")
        if number != order_item.get("atomic_number") or element != order_item.get("element"):
            raise ValueError("endpoint audit and IRC result atom order differ")
        if element not in COVALENT_RADII_ANGSTROM:
            raise ValueError(f"automatic component detection does not support element {element}")
        try:
            coordinates = {axis: float(atom[axis]) for axis in ("x", "y", "z")}
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("IRC result contains invalid endpoint coordinates") from exc
        geometry.append(
            {
                "source_index": expected_index,
                "atomic_number": number,
                "element": element,
                **coordinates,
            }
        )

    adjacency = {atom["source_index"]: set() for atom in geometry}
    bonds: list[dict[str, Any]] = []
    for offset, first in enumerate(geometry):
        for second in geometry[offset + 1 :]:
            threshold = bond_scale * (
                COVALENT_RADII_ANGSTROM[first["element"]]
                + COVALENT_RADII_ANGSTROM[second["element"]]
            )
            distance = _distance(first, second)
            if distance <= threshold:
                adjacency[first["source_index"]].add(second["source_index"])
                adjacency[second["source_index"]].add(first["source_index"])
                bonds.append(
                    {
                        "pair": [first["source_index"], second["source_index"]],
                        "distance_angstrom": distance,
                        "threshold_angstrom": threshold,
                    }
                )

    remaining = set(adjacency)
    component_indices: list[list[int]] = []
    while remaining:
        start = min(remaining)
        stack = [start]
        remaining.remove(start)
        component: list[int] = []
        while stack:
            current = stack.pop()
            component.append(current)
            for neighbor in sorted(adjacency[current], reverse=True):
                if neighbor in remaining:
                    remaining.remove(neighbor)
                    stack.append(neighbor)
        component_indices.append(sorted(component))

    geometry_by_index = {atom["source_index"]: atom for atom in geometry}
    components = []
    for component_id, indices in enumerate(component_indices, start=1):
        atoms = [geometry_by_index[index] for index in indices]
        index_set = set(indices)
        components.append(
            {
                "component_id": component_id,
                "formula": _hill_formula([atom["element"] for atom in atoms]),
                "atom_count": len(atoms),
                "source_atom_indices": indices,
                "atoms": atoms,
                "detected_bonds": [bond for bond in bonds if set(bond["pair"]) <= index_set],
            }
        )
    return {
        "schema": "gaussian-irc-component-proposal/1",
        "proposal_status": "review_required",
        "calculation_ready": False,
        "endpoint_audit_sha256": sha256(endpoint_audit_path),
        "irc_result_sha256": sha256(irc_result_path),
        "source_irc_project": audit.get("project"),
        "source_irc_direction": audit.get("direction"),
        "source_irc_point": audit.get("completed_point"),
        "chemical_side": audit.get("chemical_side"),
        "total_charge": audit.get("charge"),
        "total_multiplicity": audit.get("multiplicity"),
        "connectivity_model": {
            "kind": "scaled_single-bond-covalent-radii",
            "bond_scale": bond_scale,
            "radii_angstrom": COVALENT_RADII_ANGSTROM,
        },
        "component_count": len(components),
        "components": components,
        "warnings": [
            "Connectivity is a distance-based proposal and requires explicit component review.",
            "Fragment identities, charges, multiplicities, and spin coupling are not inferred.",
            "A multi-fragment endpoint must not be submitted as one unconstrained Tight Opt-Freq job by default.",
        ],
    }


def _validate_fragment_route(route: str) -> None:
    if not route_is_complete(route):
        raise ValueError("fragment endpoint route must be complete")
    lowered = route.lower()
    if not re.search(r"\bopt\b", lowered) or not re.search(r"\bfreq\b", lowered):
        raise ValueError("fragment endpoint route must contain Opt and Freq")
    if re.search(r"\b(?:irc|geom\s*=\s*allcheck|guess\s*=\s*read|opt\s*=\s*\(?ts)\b", lowered):
        raise ValueError("fragment endpoint route must use explicit coordinates and must not contain IRC, Geom=AllCheck, Guess=Read, or TS optimization")


def build_fragment_endpoint_inputs(
    proposal_path: Path,
    review_path: Path,
    output_dir: Path,
    route: str,
    memory: str,
    nprocshared: int,
) -> dict[str, Any]:
    """Build separately reviewed explicit-Cartesian Opt-Freq inputs for endpoint fragments."""
    for label, path in {"component proposal": proposal_path, "component review": review_path}.items():
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"{label} must be an existing non-symlink file")
    if output_dir.exists():
        raise ValueError("refusing to overwrite an existing fragment endpoint output directory")
    _validate_fragment_route(route)
    if not isinstance(nprocshared, int) or not 1 <= nprocshared <= 44:
        raise ValueError("nprocshared must be an integer from 1 to 44")
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?(?:KB|MB|GB|TB)", memory, re.I):
        raise ValueError("memory must be an explicit Gaussian size such as 50GB")

    proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
    review = json.loads(review_path.read_text(encoding="utf-8"))
    if proposal.get("schema") != "gaussian-irc-component-proposal/1" or proposal.get("proposal_status") != "review_required":
        raise ValueError("fragment builder requires an unmodified component proposal")
    if proposal.get("component_count", 0) < 2:
        raise ValueError("fragment builder requires a disconnected endpoint with at least two components")
    if review.get("schema") != "gaussian-irc-component-review/1":
        raise ValueError("fragment builder requires a gaussian-irc-component-review/1 record")
    if review.get("proposal_sha256") != sha256(proposal_path):
        raise ValueError("component review is not bound to this proposal hash")
    if review.get("decision") != "accepted" or review.get("confirmed") is not True:
        raise ValueError("fragment builder requires an explicitly accepted component review")
    if not isinstance(review.get("spin_coupling_note"), str) or not review["spin_coupling_note"].strip():
        raise ValueError("component review must record the reviewed fragment spin coupling")

    proposed_items = proposal.get("components")
    if not isinstance(proposed_items, list) or not all(isinstance(item, dict) for item in proposed_items):
        raise ValueError("component proposal has an invalid components list")
    proposed = {item.get("component_id"): item for item in proposed_items}
    if len(proposed) != len(proposed_items) or None in proposed:
        raise ValueError("component proposal has missing or duplicate component_id values")
    reviewed_items = review.get("components")
    if not isinstance(reviewed_items, list) or len(reviewed_items) != len(proposed):
        raise ValueError("component review must cover every proposed component exactly once")
    reviewed: dict[int, dict[str, Any]] = {}
    projects: set[str] = set()
    total_charge = 0
    for item in reviewed_items:
        if not isinstance(item, dict):
            raise ValueError("component review entries must be objects")
        component_id = item.get("component_id")
        source = proposed.get(component_id)
        if source is None or component_id in reviewed:
            raise ValueError("component review contains an unknown or duplicate component_id")
        if item.get("source_atom_indices") != source.get("source_atom_indices"):
            raise ValueError("reviewed component atom indices differ from the detected proposal")
        identity = item.get("identity")
        project = item.get("project")
        charge = item.get("charge")
        multiplicity = item.get("multiplicity")
        if not isinstance(identity, str) or not identity.strip():
            raise ValueError("every component requires an explicit reviewed identity")
        if not isinstance(project, str) or not PROJECT_RE.fullmatch(project) or project in projects:
            raise ValueError("component projects must be distinct 1-15 character PBS-safe names")
        if not isinstance(charge, int) or not isinstance(multiplicity, int) or multiplicity < 1:
            raise ValueError("every component requires an integer charge and positive multiplicity")
        projects.add(project)
        total_charge += charge
        reviewed[component_id] = item
    if set(reviewed) != set(proposed):
        raise ValueError("component review does not cover the proposal exactly")
    if total_charge != proposal.get("total_charge"):
        raise ValueError("sum of reviewed fragment charges differs from the audited endpoint charge")

    output_dir.mkdir(parents=True)
    plan_fragments = []
    for component_id in sorted(proposed):
        source = proposed[component_id]
        decision = reviewed[component_id]
        project = decision["project"]
        project_dir = output_dir / project
        project_dir.mkdir()
        input_path = project_dir / f"{project}.gjf"
        lines = [
            f"%chk={project}.chk",
            f"%mem={memory}",
            f"%nprocshared={nprocshared}",
            route.strip(),
            "",
            f"IRC endpoint fragment: {decision['identity']}",
            "",
            f"{decision['charge']} {decision['multiplicity']}",
        ]
        for atom in source["atoms"]:
            lines.append(
                f"{atom['element']:<3} {atom['x']: .9f} {atom['y']: .9f} {atom['z']: .9f}"
            )
        input_path.write_text("\n".join(lines) + "\n\n", encoding="utf-8")
        plan_fragments.append(
            {
                "component_id": component_id,
                "identity": decision["identity"].strip(),
                "formula": source["formula"],
                "project": project,
                "charge": decision["charge"],
                "multiplicity": decision["multiplicity"],
                "source_atom_indices": source["source_atom_indices"],
                "atom_count": source["atom_count"],
                "element_order": [atom["element"] for atom in source["atoms"]],
                "input_file": f"{project}/{project}.gjf",
                "input_sha256": sha256(input_path),
                "remote_workdir": f"/home/user100/SDL/{project}",
            }
        )
    plan = {
        "schema": "gaussian-irc-fragment-endpoint-plan/1",
        "status": "planned_not_submitted",
        "calculation_ready": True,
        "proposal_sha256": sha256(proposal_path),
        "component_review_sha256": sha256(review_path),
        "chemical_side": proposal.get("chemical_side"),
        "route": route.strip(),
        "memory": memory,
        "nprocshared": nprocshared,
        "spin_coupling_note": review["spin_coupling_note"].strip(),
        "fragments": plan_fragments,
        "safety": {
            "server_root": "/home/user100/SDL",
            "no_submission_authorization": True,
            "automatic_retry_authorized": False,
        },
        "limitations": [
            "Each fragment requires separate exact submission approval and zero-imaginary-frequency validation.",
            "Summed fragment electronic energies are not a reaction Gibbs energy.",
        ],
    }
    (output_dir / "fragment_endpoint_plan.json").write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    return plan


def audit_fragment_endpoint_results(
    plan_path: Path,
    result_paths: dict[str, Path],
    job_paths: dict[str, Path],
) -> dict[str, Any]:
    """Require every reviewed fragment to be a normally optimized zero-imaginary minimum."""
    if not plan_path.is_file() or plan_path.is_symlink():
        raise ValueError("fragment endpoint plan must be an existing non-symlink file")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if plan.get("schema") != "gaussian-irc-fragment-endpoint-plan/1" or plan.get("status") != "planned_not_submitted":
        raise ValueError("fragment result audit requires a valid fragment endpoint plan")
    fragments = plan.get("fragments")
    if not isinstance(fragments, list) or len(fragments) < 2:
        raise ValueError("fragment endpoint plan must contain at least two fragments")
    expected_projects = {item.get("project") for item in fragments}
    if set(result_paths) != expected_projects:
        raise ValueError("result paths must cover every planned fragment project exactly once")
    if set(job_paths) != expected_projects:
        raise ValueError("job paths must cover every planned fragment project exactly once")

    validated = []
    energy_sum = 0.0
    for fragment in fragments:
        project = fragment["project"]
        result_path = result_paths[project]
        job_path = job_paths[project]
        if not result_path.is_file() or result_path.is_symlink():
            raise ValueError(f"result for {project} must be an existing non-symlink file")
        if not job_path.is_file() or job_path.is_symlink():
            raise ValueError(f"job record for {project} must be an existing non-symlink file")
        result = json.loads(result_path.read_text(encoding="utf-8"))
        job = json.loads(job_path.read_text(encoding="utf-8"))
        if (
            job.get("schema") != "gaussian-rtwin-pbs/1"
            or job.get("project") != project
            or job.get("status") != "completed"
            or job.get("results_fetched") is not True
            or job.get("input_sha256") != fragment.get("input_sha256")
        ):
            raise ValueError(f"job record for {project} is not bound to the completed planned input")
        if (
            result.get("schema") != "gaussian-result/1"
            or result.get("status") != "completed"
            or result.get("normal_termination") is not True
            or result.get("error_termination") is True
            or result.get("optimization_success") is not True
            or result.get("stationary_point_found") is not True
        ):
            raise ValueError(f"fragment {project} lacks completed stationary-point optimization evidence")
        frequencies = result.get("frequencies_cm-1")
        if not isinstance(frequencies, list) or not frequencies or result.get("frequency_count") != len(frequencies):
            raise ValueError(f"fragment {project} lacks a complete frequency result")
        if result.get("imaginary_frequency_count") != 0 or any(float(value) < 0 for value in frequencies):
            raise ValueError(f"fragment {project} is not a zero-imaginary-frequency minimum")
        coordinates = result.get("final_coordinates")
        if not isinstance(coordinates, list) or len(coordinates) != fragment.get("atom_count"):
            raise ValueError(f"fragment {project} result atom count differs from the plan")
        if [atom.get("element") for atom in coordinates] != fragment.get("element_order"):
            raise ValueError(f"fragment {project} result element order differs from the plan")
        energy = result.get("final_energy_hartree")
        if not isinstance(energy, (int, float)):
            raise ValueError(f"fragment {project} has no final electronic energy")
        energy_sum += float(energy)
        validated.append(
            {
                "project": project,
                "identity": fragment["identity"],
                "formula": fragment["formula"],
                "result_sha256": sha256(result_path),
                "job_sha256": sha256(job_path),
                "job_id": job.get("job_id"),
                "final_energy_hartree": float(energy),
                "frequency_count": len(frequencies),
                "imaginary_frequency_count": 0,
                "lowest_frequency_cm-1": min(float(value) for value in frequencies),
                "minimum_accepted": True,
            }
        )
    return {
        "schema": "gaussian-irc-fragment-endpoint-validation/1",
        "validation_status": "passed",
        "chemical_side": plan.get("chemical_side"),
        "fragment_plan_sha256": sha256(plan_path),
        "fragment_count": len(validated),
        "fragments": validated,
        "isolated_fragment_electronic_energy_sum_hartree": energy_sum,
        "endpoint_minimum_evidence": "passed_as_separately_reviewed_isolated_fragments",
        "limitations": [
            "The electronic-energy sum is not a reaction Gibbs energy.",
            "No finite-distance supermolecule minimum is implied for asymptotically separated fragments.",
        ],
    }


def read_atom_map(path: Path, atom_count: int) -> list[int]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    values = raw.get("atom_map", raw) if isinstance(raw, dict) else raw
    if not isinstance(values, list) or not all(isinstance(value, int) for value in values):
        raise ValueError("atom map must be a JSON integer list or {\"atom_map\": [...]} object")
    if sorted(values) != list(range(1, atom_count + 1)):
        raise ValueError("atom map must be a one-to-one permutation of 1..atom_count")
    return values


def validate_input_family(mode: str, structures: dict[str, dict[str, Any]], atom_map: list[int]) -> dict[str, Any]:
    required = {"single_guess": {"ts"}, "qst2": {"reactant", "product"}, "qst3": {"reactant", "product", "ts"}}
    if mode not in required:
        raise ValueError(f"unsupported entry mode: {mode}")
    if set(structures) != required[mode]:
        raise ValueError(f"{mode} requires exactly: {', '.join(sorted(required[mode]))}")
    baseline = next(iter(structures.values()))
    if len(atom_map) != len(baseline["atoms"]):
        raise ValueError("atom-map length does not match atom count")
    mismatches: list[str] = []
    base_elements = [atom["element"] for atom in baseline["atoms"]]
    for label, structure in structures.items():
        if len(structure["atoms"]) != len(baseline["atoms"]):
            mismatches.append(f"{label}: atom count differs")
        if structure["charge"] != baseline["charge"] or structure["multiplicity"] != baseline["multiplicity"]:
            mismatches.append(f"{label}: charge/multiplicity differs")
        if [atom["element"] for atom in structure["atoms"]] != base_elements:
            mismatches.append(f"{label}: element order differs")
    return {"schema": SCHEMA, "entry_mode": mode, "valid": not mismatches, "atom_count": len(base_elements), "atom_map": atom_map, "structures": structures, "diagnostics": mismatches}


def create_family_manifest(audit: dict[str, Any], protocol: dict[str, Any]) -> dict[str, Any]:
    """Bind a reviewed input audit to explicit user-supplied protocol values."""
    if audit.get("schema") != SCHEMA or not audit.get("valid"):
        raise ValueError("family creation requires a valid input audit")
    required = ("workflow_id", "project_prefix", "expected_reactant_identity", "expected_product_identity", "coordinate_changes", "routes", "resource_tiers", "temperature_k", "standard_state")
    missing = [field for field in required if field not in protocol]
    if missing:
        raise ValueError("protocol is missing required fields: " + ", ".join(missing))
    prefix = protocol["project_prefix"]
    if not isinstance(prefix, str) or not PROJECT_RE.fullmatch(prefix):
        raise ValueError("project_prefix must be a 1–15 character PBS-safe name")
    if protocol["standard_state"] not in {"1atm", "1M"} or not isinstance(protocol["temperature_k"], (int, float)) or protocol["temperature_k"] <= 0:
        raise ValueError("temperature_k must be positive and standard_state must be 1atm or 1M")
    if not isinstance(protocol["coordinate_changes"], list) or not protocol["coordinate_changes"]:
        raise ValueError("coordinate_changes must be a non-empty explicit list")
    routes = protocol["routes"]
    route_keys = ("ts_freq", "irc_forward", "irc_reverse", "endpoint_opt_freq")
    if not isinstance(routes, dict) or any(not route_is_complete(routes.get(key, "")) for key in route_keys):
        raise ValueError("routes must contain complete ts_freq, irc_forward, irc_reverse, and endpoint_opt_freq route sections")
    tiers = protocol["resource_tiers"]
    tier_keys = ("ts_freq", "irc", "endpoint")
    if not isinstance(tiers, dict) or any(tiers.get(key) not in {"simple", "general", "complex"} for key in tier_keys):
        raise ValueError("resource_tiers must declare ts_freq, irc, endpoint as simple/general/complex")
    return {"schema": SCHEMA, "workflow_id": protocol["workflow_id"], "project_prefix": prefix, "input_audit": audit, "protocol": protocol, "review_states": {"G0": "pending", "G1": "passed", "G2": "pending", "G3": "pending", "G4": "pending"}, "status": "prepared_not_submitted", "safety": {"server_root": "/home/user100/SDL", "transport_skill": "gaussian-rtwin-pbs", "no_submission_authorization": True}}


def _last_orientation(text: str) -> list[dict[str, Any]]:
    matches = list(re.finditer(r"(?m)^\s*(?:Standard|Input) orientation:\s*$", text))
    for match in reversed(matches):
        lines = text[match.end():].splitlines()
        bars = [i for i, line in enumerate(lines) if re.match(r"^\s*-{10,}\s*$", line)]
        if len(bars) < 3:
            continue
        geometry: list[dict[str, Any]] = []
        for line in lines[bars[1] + 1:bars[2]]:
            fields = line.split()
            if len(fields) < 6:
                continue
            try:
                number = int(fields[1]); x, y, z = map(_float, fields[3:6])
            except ValueError:
                continue
            geometry.append({"index": int(fields[0]), "atomic_number": number, "element": ELEMENTS[number] if 0 < number < len(ELEMENTS) else f"X{number}", "x": x, "y": y, "z": z})
        if geometry:
            return geometry
    return []


def parse_modes(text: str) -> tuple[list[dict[str, Any]], list[str]]:
    """Parse Gaussian normal-coordinate tables attached to Frequency groups."""
    lines = text.splitlines()
    modes: list[dict[str, Any]] = []
    diagnostics: list[str] = []
    cursor = 0
    while cursor < len(lines):
        match = re.match(r"^\s*Frequencies\s+--\s+(.+)$", lines[cursor])
        if not match:
            cursor += 1; continue
        try:
            frequencies = [_float(value) for value in match.group(1).split()]
        except ValueError:
            diagnostics.append(f"malformed frequency line {cursor + 1}"); cursor += 1; continue
        header = cursor + 1
        while header < len(lines) and not re.match(r"^\s*Atom\s+AN\s+", lines[header]):
            if re.match(r"^\s*Frequencies\s+--", lines[header]): break
            header += 1
        vectors: list[list[dict[str, Any]]] = [[] for _ in frequencies]
        if header >= len(lines) or not re.match(r"^\s*Atom\s+AN\s+", lines[header]):
            diagnostics.append(f"missing normal-coordinate block for frequencies at line {cursor + 1}")
            modes.extend({"frequency_cm-1": value, "displacements": []} for value in frequencies)
            cursor += 1; continue
        row = header + 1
        while row < len(lines):
            fields = lines[row].split()
            if len(fields) < 2 + 3 * len(frequencies): break
            try:
                atom_index, atomic_number = int(fields[0]), int(fields[1])
                numbers = [_float(value) for value in fields[2:2 + 3 * len(frequencies)]]
            except ValueError:
                break
            for i in range(len(frequencies)):
                x, y, z = numbers[3 * i:3 * i + 3]
                vectors[i].append({"index": atom_index, "atomic_number": atomic_number, "x": x, "y": y, "z": z})
            row += 1
        for value, vector in zip(frequencies, vectors):
            modes.append({"frequency_cm-1": value, "displacements": vector})
        cursor = row
    return modes, diagnostics


def analyze_ts_log_text(text: str) -> dict[str, Any]:
    energy = re.findall(r"SCF Done:\s+E\([^)]*\)\s*=\s*([-+0-9.DEded]+)", text)
    revision = re.search(r"Gaussian 16,\s+Revision\s+([^,\r\n]+)", text)
    modes, diagnostics = parse_modes(text)
    frequencies = [item["frequency_cm-1"] for item in modes]
    negative = [item for item in modes if item["frequency_cm-1"] < 0]
    normal_count = text.count("Normal termination of Gaussian")
    error_count = text.count("Error termination")
    stationary = "Stationary point found" in text
    optimization = "Optimization completed" in text
    frequency_complete = bool(frequencies)
    candidate = normal_count > 0 and error_count == 0 and stationary and optimization and frequency_complete and len(negative) == 1
    if len(negative) == 1 and not negative[0]["displacements"]:
        diagnostics.append("imaginary mode has no displacement table")
    return {"schema": "gaussian-ts-freq-result/1", "status": "completed" if normal_count and not error_count else "failed" if error_count else "incomplete", "g16_revision": revision.group(1).strip() if revision else None, "normal_termination_count": normal_count, "error_termination_count": error_count, "optimization_completed": optimization, "stationary_point_found": stationary, "final_energy_hartree": _float(energy[-1]) if energy else None, "frequency_count": len(frequencies), "frequencies_cm-1": frequencies, "raw_imaginary_frequency_count": len(negative), "imaginary_modes": negative, "final_coordinates": _last_orientation(text), "first_order_saddle_candidate": candidate, "mode_review_status": "pending" if candidate else "not_eligible", "diagnostics": diagnostics}


def terminal_template_payload_sha256(template: dict[str, Any]) -> str:
    """Hash the semantic template payload without its self-hash field."""
    payload = dict(template)
    payload.pop("template_payload_sha256", None)
    rendered = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def validate_terminal_intake_template(
    template: dict[str, Any], input_path: Path
) -> dict[str, Any]:
    """Validate one offline terminal-intake template and its exact input."""
    if template.get("schema") != TERMINAL_TEMPLATE_SCHEMA:
        raise ValueError("unrecognized terminal-intake template schema")
    if template.get("status") != "prepared_offline" or template.get("no_submission_authorization") is not True:
        raise ValueError("terminal-intake template must be prepared offline and grant no submission authority")
    expected_hash = template.get("template_payload_sha256")
    if not isinstance(expected_hash, str) or expected_hash != terminal_template_payload_sha256(template):
        raise ValueError("terminal-intake template payload hash does not match")
    project = template.get("project")
    if not isinstance(project, str) or not PROJECT_RE.fullmatch(project):
        raise ValueError("terminal-intake template has an invalid project")
    task_kind = template.get("task_kind")
    if task_kind not in {"irc", "ts_freq"}:
        raise ValueError("terminal-intake task_kind must be irc or ts_freq")
    if not input_path.is_file() or input_path.is_symlink():
        raise ValueError("terminal-intake input must be an existing non-symlink file")
    input_hash = template.get("input_sha256")
    if not isinstance(input_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", input_hash):
        raise ValueError("terminal-intake template has an invalid input SHA-256")
    if sha256(input_path) != input_hash:
        raise ValueError("terminal-intake input hash differs from the template")
    expected = template.get("expected_system")
    if not isinstance(expected, dict):
        raise ValueError("terminal-intake template lacks expected_system")
    for key in ("atom_count", "charge", "multiplicity"):
        if not isinstance(expected.get(key), int):
            raise ValueError(f"expected_system.{key} must be an integer")
    if expected["atom_count"] < 1 or expected["multiplicity"] < 1:
        raise ValueError("expected atom count and multiplicity must be positive")
    acceptance = template.get("acceptance_gate")
    if not isinstance(acceptance, dict):
        raise ValueError("terminal-intake template lacks acceptance_gate")
    if task_kind == "irc":
        direction = acceptance.get("direction")
        if direction not in {"forward", "reverse"}:
            raise ValueError("IRC terminal template requires an explicit direction")
        if not isinstance(acceptance.get("maximum_points"), int) or acceptance["maximum_points"] < 1:
            raise ValueError("IRC terminal template requires a positive maximum_points")
    else:
        if not isinstance(acceptance.get("expected_frequency_count"), int) or acceptance["expected_frequency_count"] < 1:
            raise ValueError("TS/Freq terminal template requires expected_frequency_count")
        if acceptance.get("required_raw_imaginary_frequency_count") != 1:
            raise ValueError("TS/Freq terminal template must preserve the exactly-one-imaginary-mode gate")
    return template


def _load_terminal_file(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"{label} must be an existing non-symlink JSON file")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return value


def _audit_terminal_job(
    template: dict[str, Any], input_path: Path, job_path: Path, log_path: Path
) -> tuple[dict[str, Any], str]:
    """Require stable, fetched local terminal evidence before scientific parsing."""
    if not log_path.is_file() or log_path.is_symlink():
        raise ValueError("Gaussian log must be an existing non-symlink file")
    job = _load_terminal_file(job_path, "job record")
    project = template["project"]
    if job.get("schema") != "gaussian-rtwin-pbs/1" or job.get("project") != project:
        raise ValueError("job record is not bound to the template project")
    if job.get("input_sha256") != sha256(input_path):
        raise ValueError("job record input hash differs from the template-bound input")
    if job.get("status") not in {"completed", "failed", "interrupted"}:
        raise ValueError("job record is not terminal")
    if job.get("results_fetched") is not True:
        raise ValueError("terminal job results have not been fetched")
    if job.get("rtwin_sha256_verified") is not True or job.get("server_sha256_verified") is not True:
        raise ValueError("job record lacks verified submission transport hashes")
    inspection = job.get("last_inspection")
    if not isinstance(inspection, dict) or inspection.get("schema") != "gaussian-job-inspection/1":
        raise ValueError("job record lacks a terminal Gaussian inspection")
    if inspection.get("project") != project or inspection.get("job_id") != job.get("job_id"):
        raise ValueError("terminal inspection is not bound to the job record")
    if inspection.get("state") != job.get("status") or inspection.get("state") not in {"completed", "failed", "interrupted"}:
        raise ValueError("job and inspection terminal states disagree")
    if inspection.get("process_alive") is True:
        raise ValueError("Gaussian process is still alive; the log is not terminal evidence")
    if inspection.get("log_size") != log_path.stat().st_size:
        raise ValueError("fetched log size differs from the terminal inspection")
    text = log_path.read_text(encoding="utf-8", errors="replace")
    normal_count = text.count("Normal termination of Gaussian")
    error_count = text.count("Error termination")
    if inspection.get("full_normal_termination_count") != normal_count or inspection.get("full_error_termination_count") != error_count:
        raise ValueError("fetched log termination counts differ from the terminal inspection")
    return job, text


def ingest_terminal_artifacts(
    template_path: Path,
    input_path: Path,
    job_path: Path,
    log_path: Path,
) -> dict[str, Any]:
    """Ingest a fetched TS/Freq or IRC terminal state without making a chemical decision."""
    template = _load_terminal_file(template_path, "terminal-intake template")
    validate_terminal_intake_template(template, input_path)
    job, text = _audit_terminal_job(template, input_path, job_path, log_path)
    expected = template["expected_system"]
    charge, multiplicity = _charge_multiplicity_from_log(text)
    if (charge, multiplicity) != (expected["charge"], expected["multiplicity"]):
        raise ValueError("completed log charge/multiplicity differs from the terminal template")

    common = {
        "schema": TERMINAL_INTAKE_SCHEMA,
        "template_id": template.get("template_id"),
        "template_sha256": sha256(template_path),
        "template_payload_sha256": template["template_payload_sha256"],
        "task_kind": template["task_kind"],
        "project": template["project"],
        "runtime_job_id": job.get("job_id"),
        "artifacts": {
            "input_sha256": sha256(input_path),
            "job_sha256": sha256(job_path),
            "log_sha256": sha256(log_path),
            "log_size_bytes": log_path.stat().st_size,
        },
        "terminal_evidence": {
            "status": "passed",
            "job_state": job["status"],
            "results_fetched": True,
            "process_alive": job["last_inspection"].get("process_alive"),
            "submission_transport_hashes_verified": True,
            "normal_termination_count": text.count("Normal termination of Gaussian"),
            "error_termination_count": text.count("Error termination"),
        },
        "automatic_action_authorized": False,
    }

    if template["task_kind"] == "ts_freq":
        parsed = analyze_ts_log_text(text)
        acceptance = template["acceptance_gate"]
        geometry_complete = len(parsed["final_coordinates"]) == expected["atom_count"]
        frequency_complete = parsed["frequency_count"] == acceptance["expected_frequency_count"]
        if parsed["error_termination_count"] or job["status"] != "completed":
            outcome = "error_or_interrupted_termination"
        elif not parsed["optimization_completed"] or not parsed["stationary_point_found"] or not geometry_complete:
            outcome = "nonstationary_or_incomplete"
        elif not frequency_complete:
            outcome = "incomplete_frequency_analysis"
        elif parsed["raw_imaginary_frequency_count"] == 0:
            outcome = "zero_imaginary_modes"
        elif parsed["raw_imaginary_frequency_count"] > 1:
            outcome = "multiple_imaginary_modes"
        else:
            outcome = "ready_for_manual_mode_review"
        common.update(
            {
                "acceptance_status": "manual_review_required" if outcome == "ready_for_manual_mode_review" else "not_accepted",
                "outcome": outcome,
                "scientific_evidence": {
                    "optimization_completed": parsed["optimization_completed"],
                    "stationary_point_found": parsed["stationary_point_found"],
                    "atom_count": len(parsed["final_coordinates"]),
                    "expected_atom_count": expected["atom_count"],
                    "frequency_count": parsed["frequency_count"],
                    "expected_frequency_count": acceptance["expected_frequency_count"],
                    "raw_imaginary_frequency_count": parsed["raw_imaginary_frequency_count"],
                    "imaginary_frequencies_cm-1": [
                        mode["frequency_cm-1"] for mode in parsed["imaginary_modes"]
                    ],
                    "first_order_saddle_candidate": outcome == "ready_for_manual_mode_review",
                    "mode_review_status": "pending" if outcome == "ready_for_manual_mode_review" else "not_eligible",
                },
                "path_validated": False,
                "next_required_artifacts": [
                    "gaussian-ts-freq-result/1",
                    "gaussian-ts-mode-review/1",
                    "gaussian-ts-mode-decision/1",
                ] if outcome == "ready_for_manual_mode_review" else [],
            }
        )
        return common

    acceptance = template["acceptance_gate"]
    direction = acceptance["direction"]
    point_numbers = [int(value) for value in re.findall(r"Point Number:\s*(\d+)", text)]
    completed_point = max(point_numbers) if point_numbers else 0
    corrector_count = text.count("Delta-x Convergence Met")
    direction_complete = f"Calculation of {direction.upper()} path complete." in text
    geometry = _last_orientation(text)
    geometry_complete = len(geometry) == expected["atom_count"]
    clean_termination = (
        job["status"] == "completed"
        and text.count("Normal termination of Gaussian") > 0
        and text.count("Error termination") == 0
    )
    if not clean_termination:
        outcome = "error_or_interrupted_termination"
    elif completed_point < 1 or completed_point > acceptance["maximum_points"]:
        outcome = "invalid_or_missing_path_points"
    elif corrector_count < completed_point:
        outcome = "incomplete_corrector_convergence"
    elif not direction_complete:
        outcome = "directional_path_incomplete"
    elif not geometry_complete:
        outcome = "endpoint_geometry_incomplete"
    else:
        outcome = "ready_for_endpoint_structure_review"
    common.update(
        {
            "acceptance_status": "structural_review_required" if outcome == "ready_for_endpoint_structure_review" else "not_accepted",
            "outcome": outcome,
            "scientific_evidence": {
                "direction": direction,
                "directional_path_complete": direction_complete,
                "completed_point": completed_point,
                "maximum_points": acceptance["maximum_points"],
                "corrector_convergence_count": corrector_count,
                "atom_count": len(geometry),
                "expected_atom_count": expected["atom_count"],
                "chemical_side_assignment": "pending_structural_review",
            },
            "path_validated": False,
            "next_required_artifacts": [
                "reviewed chemical-side assignment",
                "gaussian-irc-endpoint-audit/1",
            ] if outcome == "ready_for_endpoint_structure_review" else [],
        }
    )
    return common


def _distance(a: dict[str, Any], b: dict[str, Any]) -> float:
    return math.sqrt((a["x"] - b["x"]) ** 2 + (a["y"] - b["y"]) ** 2 + (a["z"] - b["z"]) ** 2)


def _displace(geometry: dict[int, dict[str, Any]], vectors: dict[int, dict[str, Any]], amplitude: float) -> dict[int, dict[str, Any]]:
    displaced: dict[int, dict[str, Any]] = {}
    for index, atom in geometry.items():
        item = dict(atom)
        for axis in ("x", "y", "z"):
            item[axis] += amplitude * vectors[index][axis]
        displaced[index] = item
    return displaced


def _write_xyz(path: Path, geometry: dict[int, dict[str, Any]], comment: str) -> None:
    lines = [str(len(geometry)), comment]
    lines.extend(f"{atom['element']:<3} {atom['x']: .8f} {atom['y']: .8f} {atom['z']: .8f}" for _, atom in sorted(geometry.items()))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def create_mode_review(result: dict[str, Any], pairs: list[tuple[int, int]], output_dir: Path, amplitude: float, result_sha256: str) -> dict[str, Any]:
    if not result.get("first_order_saddle_candidate"):
        raise ValueError("TS result is not an eligible first-order-saddle candidate")
    mode = result["imaginary_modes"][0]
    geometry = {atom["index"]: atom for atom in result.get("final_coordinates", [])}
    vectors = {atom["index"]: atom for atom in mode["displacements"]}
    if not geometry or set(geometry) != set(vectors):
        raise ValueError("final geometry and imaginary-mode displacement table are incomplete or disagree")
    output_dir.mkdir(parents=True, exist_ok=False)
    plus_map = _displace(geometry, vectors, amplitude)
    minus_map = _displace(geometry, vectors, -amplitude)
    projections = []
    for first, second in pairs:
        if first not in geometry or second not in geometry:
            raise ValueError(f"declared pair {first},{second} is outside the geometry")
        projections.append({"pair": [first, second], "equilibrium_angstrom": _distance(geometry[first], geometry[second]), "plus_angstrom": _distance(plus_map[first], plus_map[second]), "minus_angstrom": _distance(minus_map[first], minus_map[second]), "plus_minus_change_angstrom": _distance(plus_map[first], plus_map[second]) - _distance(minus_map[first], minus_map[second])})
    review = {"schema": "gaussian-ts-mode-review/1", "ts_result_sha256": result_sha256, "imaginary_frequency_cm-1": mode["frequency_cm-1"], "amplitude": amplitude, "distance_projections": projections, "displacements": mode["displacements"], "visualization_artifacts": ["mode_plus.xyz", "mode_minus.xyz"], "scientific_decision": "required"}
    (output_dir / "mode_review.json").write_text(json.dumps(review, indent=2) + "\n", encoding="utf-8")
    _write_xyz(output_dir / "mode_plus.xyz", plus_map, f"Imaginary mode +{amplitude:g}; visualization aid only")
    _write_xyz(output_dir / "mode_minus.xyz", minus_map, f"Imaginary mode -{amplitude:g}; visualization aid only")
    return review


def record_mode_decision(review_path: Path, decision: str, output_path: Path) -> dict[str, Any]:
    review = json.loads(review_path.read_text(encoding="utf-8"))
    if review.get("schema") != "gaussian-ts-mode-review/1" or review.get("scientific_decision") != "required":
        raise ValueError("mode decision requires an unmodified pending mode-review artifact")
    if not review.get("ts_result_sha256"):
        raise ValueError("mode review is not bound to a TS result hash")
    if output_path.exists():
        raise ValueError("refusing to overwrite an existing mode-decision record")
    record = {
        "schema": "gaussian-ts-mode-decision/1",
        "mode_review_sha256": sha256(review_path),
        "ts_result_sha256": review["ts_result_sha256"],
        "imaginary_frequency_cm-1": review.get("imaginary_frequency_cm-1"),
        "decision": decision,
        "confirmed": True,
    }
    output_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


def route_is_complete(route: str) -> bool:
    return route.strip().startswith("#") and "<" not in route and ">" not in route and "todo" not in route.lower()


def _validate_directional_irc_route(route: str, direction: str) -> None:
    lowered = route.lower()
    opposite = "reverse" if direction == "forward" else "forward"
    if not route_is_complete(route) or not re.search(r"\birc\b", lowered) or not re.search(rf"\b{direction}\b", lowered) or re.search(rf"\b{opposite}\b", lowered):
        raise ValueError(f"{direction} route must be a complete IRC route containing only its explicit direction keyword")


def build_irc_plan(family: dict[str, Any], ts_path: Path, checkpoint: Path, review_path: Path, decision_path: Path, g16_revision: str, forward_route: str, reverse_route: str, forward_project: str, reverse_project: str) -> dict[str, Any]:
    result = json.loads(ts_path.read_text(encoding="utf-8"))
    decision = json.loads(decision_path.read_text(encoding="utf-8"))
    if family.get("schema") != SCHEMA:
        raise ValueError("unrecognized family manifest schema")
    if not result.get("first_order_saddle_candidate"):
        raise ValueError("IRC planning requires an eligible TS result")
    if decision.get("schema") != "gaussian-ts-mode-decision/1" or decision.get("decision") != "accepted" or decision.get("confirmed") is not True:
        raise ValueError("IRC planning requires an explicitly accepted imaginary-mode review")
    if decision.get("ts_result_sha256") != sha256(ts_path):
        raise ValueError("mode decision is not bound to this TS result hash")
    if decision.get("mode_review_sha256") != sha256(review_path):
        raise ValueError("mode decision is not bound to this mode-review hash")
    if not checkpoint.is_file():
        raise ValueError("reviewed TS checkpoint is missing")
    if not g16_revision.strip() or any(char in g16_revision for char in "<>\n\r"):
        raise ValueError("the verified installed Gaussian 16 revision is required")
    if result.get("g16_revision") != g16_revision.strip():
        raise ValueError("declared G16 revision does not match the revision parsed from the TS log")
    if not all(PROJECT_RE.fullmatch(name) for name in (forward_project, reverse_project)) or forward_project == reverse_project:
        raise ValueError("IRC projects must be distinct 1–15 character PBS-safe names")
    _validate_directional_irc_route(forward_route, "forward")
    _validate_directional_irc_route(reverse_route, "reverse")
    return {"schema": "gaussian-irc-plan/1", "workflow_id": family.get("workflow_id"), "g16_revision": g16_revision.strip(), "ts_result_sha256": sha256(ts_path), "mode_decision_sha256": sha256(decision_path), "checkpoint_sha256": sha256(checkpoint), "directions": [{"direction": "forward", "project": forward_project, "route": forward_route}, {"direction": "reverse", "project": reverse_project, "route": reverse_route}], "submission_status": "planned_not_submitted", "notes": ["Use gaussian-rtwin-pbs only after exact G3 approval.", "This plan does not grant submission, cancellation, overwrite, or deletion permission."]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("validate-inputs"); check.add_argument("--mode", choices=["single_guess", "qst2", "qst3"], required=True); check.add_argument("--ts"); check.add_argument("--reactant"); check.add_argument("--product"); check.add_argument("--atom-map", required=True); check.add_argument("--output")
    family = sub.add_parser("create-family"); family.add_argument("--input-audit", required=True); family.add_argument("--protocol", required=True); family.add_argument("--output", required=True)
    analyze = sub.add_parser("analyze-ts"); analyze.add_argument("log"); analyze.add_argument("--output", required=True)
    review = sub.add_parser("mode-review"); review.add_argument("result"); review.add_argument("--output-dir", required=True); review.add_argument("--forming", action="append", default=[]); review.add_argument("--breaking", action="append", default=[]); review.add_argument("--amplitude", type=float, default=0.1)
    decide = sub.add_parser("record-mode-decision"); decide.add_argument("mode_review"); decide.add_argument("--decision", choices=["accepted", "rejected", "unclear"], required=True); decide.add_argument("--output", required=True); decide.add_argument("--confirmed", action="store_true")
    plan = sub.add_parser("plan-irc"); plan.add_argument("family"); plan.add_argument("--ts-result", required=True); plan.add_argument("--checkpoint", required=True); plan.add_argument("--mode-review", required=True); plan.add_argument("--mode-decision", required=True); plan.add_argument("--g16-revision", required=True); plan.add_argument("--forward-route", required=True); plan.add_argument("--reverse-route", required=True); plan.add_argument("--forward-project", required=True); plan.add_argument("--reverse-project", required=True); plan.add_argument("--output", required=True); plan.add_argument("--confirmed", action="store_true")
    checkpoint_audit = sub.add_parser("audit-checkpoint"); checkpoint_audit.add_argument("--ts-input", required=True); checkpoint_audit.add_argument("--ts-log", required=True); checkpoint_audit.add_argument("--ts-result", required=True); checkpoint_audit.add_argument("--checkpoint", required=True); checkpoint_audit.add_argument("--mode-review", required=True); checkpoint_audit.add_argument("--mode-decision", required=True); checkpoint_audit.add_argument("--output", required=True)
    allcheck = sub.add_parser("build-allcheck-irc"); allcheck.add_argument("--checkpoint-audit", required=True); allcheck.add_argument("--checkpoint", required=True); allcheck.add_argument("--output", required=True); allcheck.add_argument("--route", required=True); allcheck.add_argument("--direction", choices=["forward", "reverse"], required=True); allcheck.add_argument("--memory", required=True); allcheck.add_argument("--nprocshared", type=int, required=True)
    endpoint_audit = sub.add_parser("audit-irc-endpoint"); endpoint_audit.add_argument("--irc-input", required=True); endpoint_audit.add_argument("--irc-log", required=True); endpoint_audit.add_argument("--irc-result", required=True); endpoint_audit.add_argument("--job", required=True); endpoint_audit.add_argument("--checkpoint", required=True); endpoint_audit.add_argument("--direction", choices=["forward", "reverse"], required=True); endpoint_audit.add_argument("--chemical-side", choices=["reactant", "product"], required=True); endpoint_audit.add_argument("--expected-points", type=int, required=True); endpoint_audit.add_argument("--forming", action="append", required=True); endpoint_audit.add_argument("--output", required=True)
    endpoint = sub.add_parser("build-allcheck-endpoint"); endpoint.add_argument("--endpoint-audit", required=True); endpoint.add_argument("--checkpoint", required=True); endpoint.add_argument("--output", required=True); endpoint.add_argument("--route", required=True); endpoint.add_argument("--memory", required=True); endpoint.add_argument("--nprocshared", type=int, required=True)
    components = sub.add_parser("propose-endpoint-components"); components.add_argument("--endpoint-audit", required=True); components.add_argument("--irc-result", required=True); components.add_argument("--bond-scale", type=float, default=1.25); components.add_argument("--output", required=True)
    fragment_build = sub.add_parser("build-fragment-endpoints"); fragment_build.add_argument("--component-proposal", required=True); fragment_build.add_argument("--component-review", required=True); fragment_build.add_argument("--output-dir", required=True); fragment_build.add_argument("--route", required=True); fragment_build.add_argument("--memory", required=True); fragment_build.add_argument("--nprocshared", type=int, required=True)
    fragment_audit = sub.add_parser("audit-fragment-endpoints"); fragment_audit.add_argument("--plan", required=True); fragment_audit.add_argument("--result", action="append", required=True, help="PROJECT=/path/to/result.json"); fragment_audit.add_argument("--job", action="append", required=True, help="PROJECT=/path/to/job.json"); fragment_audit.add_argument("--output", required=True)
    terminal = sub.add_parser("ingest-terminal"); terminal.add_argument("--template", required=True); terminal.add_argument("--input", required=True); terminal.add_argument("--job", required=True); terminal.add_argument("--log", required=True); terminal.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        if args.command == "validate-inputs":
            sources = {key: Path(value) for key, value in {"ts": args.ts, "reactant": args.reactant, "product": args.product}.items() if value}
            structures = {key: parse_cartesian_input(value) for key, value in sources.items()}
            result = validate_input_family(args.mode, structures, read_atom_map(Path(args.atom_map), len(next(iter(structures.values()))["atoms"])))
            output = json.dumps(result, indent=2) + "\n"
            if args.output: Path(args.output).write_text(output, encoding="utf-8")
            else: print(output, end="")
        elif args.command == "create-family":
            output_path = Path(args.output)
            if output_path.exists(): raise ValueError("refusing to overwrite an existing family manifest")
            result = create_family_manifest(json.loads(Path(args.input_audit).read_text(encoding="utf-8")), json.loads(Path(args.protocol).read_text(encoding="utf-8")))
            output_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        elif args.command == "analyze-ts":
            result = analyze_ts_log_text(Path(args.log).read_text(encoding="utf-8", errors="replace")); result["log_sha256"] = sha256(Path(args.log)); Path(args.output).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        elif args.command == "mode-review":
            pairs = [tuple(map(int, raw.split(","))) for raw in args.forming + args.breaking]
            result_path = Path(args.result)
            create_mode_review(json.loads(result_path.read_text(encoding="utf-8")), pairs, Path(args.output_dir), args.amplitude, sha256(result_path))
        elif args.command == "record-mode-decision":
            if not args.confirmed: raise ValueError("mode decision requires --confirmed after scientific review")
            record_mode_decision(Path(args.mode_review), args.decision, Path(args.output))
        elif args.command == "plan-irc":
            if not args.confirmed: raise ValueError("IRC planning requires --confirmed after exact G3 approval")
            output_path = Path(args.output)
            if output_path.exists(): raise ValueError("refusing to overwrite an existing IRC plan")
            result = build_irc_plan(json.loads(Path(args.family).read_text(encoding="utf-8")), Path(args.ts_result), Path(args.checkpoint), Path(args.mode_review), Path(args.mode_decision), args.g16_revision, args.forward_route, args.reverse_route, args.forward_project, args.reverse_project)
            output_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        elif args.command == "audit-checkpoint":
            output_path = Path(args.output)
            if output_path.exists(): raise ValueError("refusing to overwrite an existing checkpoint audit")
            result = audit_checkpoint_provenance(Path(args.ts_input), Path(args.ts_log), Path(args.ts_result), Path(args.checkpoint), Path(args.mode_review), Path(args.mode_decision))
            output_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        elif args.command == "build-allcheck-irc":
            build_allcheck_irc_input(Path(args.checkpoint_audit), Path(args.checkpoint), Path(args.output), args.route, args.direction, args.memory, args.nprocshared)
        elif args.command == "audit-irc-endpoint":
            output_path = Path(args.output)
            if output_path.exists(): raise ValueError("refusing to overwrite an existing IRC endpoint audit")
            pairs = [tuple(map(int, raw.split(","))) for raw in args.forming]
            if any(len(pair) != 2 for pair in pairs): raise ValueError("forming pairs must use atom1,atom2")
            result = audit_irc_endpoint_provenance(Path(args.irc_input), Path(args.irc_log), Path(args.irc_result), Path(args.job), Path(args.checkpoint), args.direction, args.chemical_side, args.expected_points, pairs)
            output_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        elif args.command == "build-allcheck-endpoint":
            build_allcheck_endpoint_input(Path(args.endpoint_audit), Path(args.checkpoint), Path(args.output), args.route, args.memory, args.nprocshared)
        elif args.command == "propose-endpoint-components":
            output_path = Path(args.output)
            if output_path.exists(): raise ValueError("refusing to overwrite an existing endpoint component proposal")
            result = propose_endpoint_components(Path(args.endpoint_audit), Path(args.irc_result), args.bond_scale)
            output_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        elif args.command == "build-fragment-endpoints":
            build_fragment_endpoint_inputs(Path(args.component_proposal), Path(args.component_review), Path(args.output_dir), args.route, args.memory, args.nprocshared)
        elif args.command == "audit-fragment-endpoints":
            output_path = Path(args.output)
            if output_path.exists(): raise ValueError("refusing to overwrite an existing fragment endpoint validation")
            assignments: dict[str, dict[str, Path]] = {}
            for label, values in (("result", args.result), ("job", args.job)):
                parsed: dict[str, Path] = {}
                for raw in values:
                    project, separator, value = raw.partition("=")
                    if not separator or not PROJECT_RE.fullmatch(project) or not value or project in parsed:
                        raise ValueError(f"each --{label} must be a unique PROJECT=/path/to/{label}.json assignment")
                    parsed[project] = Path(value)
                assignments[label] = parsed
            result = audit_fragment_endpoint_results(Path(args.plan), assignments["result"], assignments["job"])
            output_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        else:
            output_path = Path(args.output)
            if output_path.exists(): raise ValueError("refusing to overwrite an existing terminal-intake result")
            result = ingest_terminal_artifacts(
                Path(args.template), Path(args.input), Path(args.job), Path(args.log)
            )
            output_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
