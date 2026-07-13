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
import sys
from pathlib import Path
from typing import Any

SCHEMA = "gaussian-ts-irc-workflow/1"
PROJECT_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,14}$")
ELEMENTS = ["X", "H", "He", "Li", "Be", "B", "C", "N", "O", "F", "Ne", "Na", "Mg", "Al", "Si", "P", "S", "Cl", "Ar"]


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
        else:
            if not args.confirmed: raise ValueError("IRC planning requires --confirmed after exact G3 approval")
            output_path = Path(args.output)
            if output_path.exists(): raise ValueError("refusing to overwrite an existing IRC plan")
            result = build_irc_plan(json.loads(Path(args.family).read_text(encoding="utf-8")), Path(args.ts_result), Path(args.checkpoint), Path(args.mode_review), Path(args.mode_decision), args.g16_revision, args.forward_route, args.reverse_route, args.forward_project, args.reverse_project)
            output_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
