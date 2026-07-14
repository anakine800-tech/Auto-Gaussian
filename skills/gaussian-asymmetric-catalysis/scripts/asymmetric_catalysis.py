#!/usr/bin/env python3
"""Deterministic, offline builders for asymmetric-catalysis evidence.

This module uses only the Python standard library.  It never invokes Gaussian,
SSH, PBS, qdel, deployment, or any subprocess.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import itertools
import json
import math
import re
import sys
from pathlib import Path
from typing import Any, Iterable


ID_RE = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
REQUIRED_BORON_DIMENSIONS = {
    "boron_center",
    "boron_coordination_state",
    "binding_mode",
    "catalyst_conformer",
    "approach_topology",
}
VALIDATION_RANK = {
    "failed": 0,
    "first_order_saddle_candidate": 1,
    "mode_reviewed": 2,
    "path_validated": 3,
}
KCAL_PER_HARTREE = 627.5094740631
KCAL_PER_KJ = 1.0 / 4.184
ATOMIC_NUMBERS = {
    element: number
    for number, element in enumerate(
        (
            "X", "H", "He", "Li", "Be", "B", "C", "N", "O", "F", "Ne",
            "Na", "Mg", "Al", "Si", "P", "S", "Cl", "Ar", "K", "Ca", "Sc",
            "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn", "Ga", "Ge",
            "As", "Se", "Br", "Kr", "Rb", "Sr", "Y", "Zr", "Nb", "Mo", "Tc",
            "Ru", "Rh", "Pd", "Ag", "Cd", "In", "Sn", "Sb", "Te", "I", "Xe",
            "Cs", "Ba", "La", "Ce", "Pr", "Nd", "Pm", "Sm", "Eu", "Gd", "Tb",
            "Dy", "Ho", "Er", "Tm", "Yb", "Lu", "Hf", "Ta", "W", "Re", "Os",
            "Ir", "Pt", "Au", "Hg", "Tl", "Pb", "Bi", "Po", "At", "Rn",
        )
    )
    if element != "X"
}


class OfflineError(ValueError):
    """A deterministic offline input violated the workflow contract."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise OfflineError(message)


def _reject_json_constant(value: str) -> None:
    raise OfflineError(f"non-standard JSON numeric constant is forbidden: {value}")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in data, f"duplicate JSON object key is forbidden: {key}")
        data[key] = value
    return data


def _is_finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _require_sha256(value: Any, message: str) -> None:
    require(isinstance(value, str) and SHA256_RE.fullmatch(value) is not None, message)


def _resolve_artifact_path(reference: dict[str, Any], owner_path: Path, label: str) -> Path:
    require(isinstance(reference, dict), f"{label} artifact is missing")
    _require_sha256(reference.get("sha256"), f"{label} artifact has an invalid SHA-256")
    raw = reference.get("path")
    require(isinstance(raw, str) and raw and "://" not in raw, f"{label} artifact path must be a local file")
    path = Path(raw)
    if not path.is_absolute():
        path = owner_path.parent / path
    require(path.is_file() and not path.is_symlink(), f"{label} artifact not found or is a symlink: {path}")
    require(sha256_file(path) == reference["sha256"], f"{label} artifact hash mismatch")
    return path


def _candidate_atom_order(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    atom_map = candidate.get("atom_map")
    require(isinstance(atom_map, list) and atom_map, "candidate atom map is missing")
    expected: list[dict[str, Any]] = []
    for index, atom in enumerate(atom_map, start=1):
        require(isinstance(atom, dict) and atom.get("index") == index, "candidate atom map is not contiguous and one-based")
        element = atom.get("element")
        require(element in ATOMIC_NUMBERS, f"candidate atom map contains unsupported element: {element}")
        expected.append({"index": index, "atomic_number": ATOMIC_NUMBERS[element], "element": element})
    inventory = candidate.get("atom_inventory", {})
    require(inventory.get("atom_count") == len(expected), "candidate atom inventory/count mismatch")
    return expected


def _require_matching_atom_order(actual: Any, expected: list[dict[str, Any]], label: str) -> None:
    require(isinstance(actual, list) and len(actual) == len(expected), f"{label} atom count differs from candidate")
    normalized = []
    for atom in actual:
        require(isinstance(atom, dict), f"{label} atom-order record is invalid")
        index = atom.get("index", atom.get("center"))
        element = atom.get("element")
        atomic_number = atom.get("atomic_number")
        if atomic_number is None and element in ATOMIC_NUMBERS:
            atomic_number = ATOMIC_NUMBERS[element]
        if element is None and isinstance(atomic_number, int):
            element = next((symbol for symbol, number in ATOMIC_NUMBERS.items() if number == atomic_number), None)
        normalized.append({"index": index, "atomic_number": atomic_number, "element": element})
    require(normalized == expected, f"{label} atom order differs from candidate")


def _validate_result_shape(result: dict[str, Any]) -> None:
    """Validate the aggregation-critical result contract without external packages."""
    require(result.get("schema") == "gaussian-asymmetric-ts-result/1", "unrecognized result schema")
    require(result.get("calculation_ready") is False and result.get("no_submission_authorization") is True, "result violates offline safety flags")
    for field in ("result_id", "candidate_id", "study_id", "comparison_group_id", "channel_id", "protocol_id"):
        require(ID_RE.fullmatch(str(result.get(field, ""))) is not None, f"result has invalid {field}")
    require(result.get("validation_level") in VALIDATION_RANK, "result has invalid validation_level")
    for field in ("artifacts", "termination", "frequency_evidence", "mode_evidence", "path_evidence", "energies", "comparison_eligibility"):
        require(isinstance(result.get(field), dict), f"result.{field} must be an object")
    _require_sha256(result.get("candidate_sha256"), "result candidate SHA-256 is invalid")
    energies = result["energies"]
    require(energies.get("energy_unit") in {"hartree", "kcal_mol", "kj_mol"}, "result energy unit is invalid")
    for field in ("electronic_energy", "thermal_gibbs_correction", "comparison_free_energy"):
        value = energies.get(field)
        require(value is None or _is_finite_number(value), f"result {field} must be finite or null")
    require(_is_finite_number(energies.get("temperature_k")) and float(energies["temperature_k"]) > 0, "result temperature must be finite and positive")
    degeneracy = energies.get("degeneracy")
    require(isinstance(degeneracy, int) and not isinstance(degeneracy, bool) and degeneracy >= 1, "result degeneracy must be a positive integer")
    if result["comparison_eligibility"].get("eligible"):
        require(_is_finite_number(energies.get("comparison_free_energy")), "eligible result requires a finite comparison free energy")


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(
        path.read_text(encoding="utf-8"),
        parse_constant=_reject_json_constant,
        object_pairs_hook=_reject_duplicate_keys,
    )
    require(isinstance(data, dict), f"{path}: top-level JSON must be an object")
    return data


def canonical_bytes(data: Any) -> bytes:
    return (
        json.dumps(
            data,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_data(data: Any) -> str:
    return hashlib.sha256(canonical_bytes(data)).hexdigest()


def artifact(path: Path) -> dict[str, str]:
    require(path.is_file(), f"artifact not found: {path}")
    return {"path": str(path), "sha256": sha256_file(path)}


def write_json(path: Path, data: Any) -> None:
    require(not path.exists(), f"refusing to overwrite existing artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(data))


def _sort_named(items: Iterable[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    return sorted(items, key=lambda item: item.get(key, ""))


def normalize_study(source: dict[str, Any]) -> dict[str, Any]:
    """Normalize a complete study specification without inventing chemistry."""
    study = copy.deepcopy(source)
    study["schema"] = "gaussian-asymmetric-catalysis-study/1"
    study["calculation_ready"] = False
    study["no_submission_authorization"] = True
    require(ID_RE.fullmatch(str(study.get("study_id", ""))) is not None, "invalid study_id")
    for field, key in (
        ("species", "species_id"),
        ("catalyst_states", "state_id"),
        ("mechanism_hypotheses", "mechanism_id"),
        ("channels", "channel_id"),
        ("protocol_sets", "protocol_id"),
        ("comparison_groups", "comparison_group_id"),
        ("coverage_dimensions", "dimension_id"),
        ("gates", "gate_id"),
    ):
        require(isinstance(study.get(field), list), f"study.{field} must be an array")
        study[field] = _sort_named(study[field], key)
    for mechanism in study["mechanism_hypotheses"]:
        mechanism["channel_ids"] = sorted(mechanism.get("channel_ids", []))
        mechanism["reactant_species_ids"] = sorted(mechanism.get("reactant_species_ids", []))
        mechanism["product_species_ids"] = sorted(mechanism.get("product_species_ids", []))
    for group in study["comparison_groups"]:
        group["channel_ids"] = sorted(group.get("channel_ids", []))
        group["coverage_dimension_ids"] = sorted(group.get("coverage_dimension_ids", []))
    for dimension in study["coverage_dimensions"]:
        dimension["expected_levels"] = sorted(dimension.get("expected_levels", []))
    return study


def build_study(source_path: Path, output: Path) -> dict[str, Any]:
    study = normalize_study(load_json(source_path))
    write_json(output, study)
    return study


def _dimension_index(space: dict[str, Any]) -> dict[str, dict[str, Any]]:
    dimensions: dict[str, dict[str, Any]] = {}
    for dimension in space.get("dimensions", []):
        dim_id = dimension.get("dimension_id")
        require(ID_RE.fullmatch(str(dim_id or "")) is not None, "candidate space has invalid dimension_id")
        require(dim_id not in dimensions, f"duplicate candidate-space dimension: {dim_id}")
        levels = dimension.get("levels", [])
        require(levels, f"candidate-space dimension {dim_id} has no levels")
        seen: set[str] = set()
        for level in levels:
            level_id = level.get("level_id")
            require(isinstance(level_id, str) and level_id, f"{dim_id}: invalid level_id")
            require(level_id not in seen, f"{dim_id}: duplicate level {level_id}")
            seen.add(level_id)
            level.setdefault("equivalence_key", level_id)
            level.setdefault("metadata", {})
        dimensions[dim_id] = dimension
    return dimensions


def _compatible(
    channel_id: str,
    state_id: str,
    selection: dict[str, dict[str, Any]],
    constraints: list[dict[str, Any]],
) -> tuple[bool, str | None]:
    center = selection["boron_center"].get("metadata", {})
    if center.get("catalyst_state_id") not in {None, state_id}:
        return False, "boron center belongs to a different catalyst state"
    binding = selection["binding_mode"].get("metadata", {})
    if binding.get("boron_center") not in {None, selection["boron_center"]["level_id"]}:
        return False, "binding mode is incompatible with boron center"
    if binding.get("boron_coordination_state") not in {None, selection["boron_coordination_state"]["level_id"]}:
        return False, "binding mode is incompatible with boron coordination state"
    approach = selection["approach_topology"].get("metadata", {})
    if approach.get("channel_id") not in {None, channel_id}:
        return False, "approach topology belongs to a different stereochemical channel"
    ids = {key: value["level_id"] for key, value in selection.items()}
    for rule in constraints:
        when = rule.get("when", {})
        if all((key == "channel_id" and value == channel_id) or (key == "catalyst_state_id" and value == state_id) or ids.get(key) == value for key, value in when.items()):
            forbidden = rule.get("forbid", {})
            if all(ids.get(key) == value for key, value in forbidden.items()):
                return False, str(rule.get("reason") or "explicit candidate-space exclusion")
    return True, None


def enumerate_boron(study_path: Path, space_path: Path, output: Path) -> dict[str, Any]:
    study = load_json(study_path)
    space = load_json(space_path)
    require(study.get("schema") == "gaussian-asymmetric-catalysis-study/1", "unrecognized study schema")
    require(space.get("schema") == "gaussian-asymmetric-candidate-space-spec/1", "unrecognized candidate-space schema")
    require(study.get("catalyst_class") == "chiral_boron", "boron enumerator supports chiral_boron only")
    require(space.get("study_id") == study.get("study_id"), "candidate space study_id mismatch")
    require(space.get("study_sha256") == sha256_file(study_path), "candidate space study hash mismatch")
    groups = {item["comparison_group_id"]: item for item in study["comparison_groups"]}
    group_id = space.get("comparison_group_id")
    require(group_id in groups, "unknown comparison group")
    group = groups[group_id]
    mechanisms = {item["mechanism_id"]: item for item in study["mechanism_hypotheses"]}
    mechanism = mechanisms[group["mechanism_id"]]
    states = {item["state_id"]: item for item in study["catalyst_states"]}
    state_ids = sorted(space.get("catalyst_state_ids", [mechanism["active_catalyst_state_id"]]))
    for state_id in state_ids:
        require(state_id in states, f"unknown catalyst state: {state_id}")
        require(states[state_id].get("boron_centers"), f"state {state_id} has no boron center")
        require(not states[state_id].get("metal_centers"), "metal-containing states are refused by boron enumerator")
    dimensions = _dimension_index(space)
    require(REQUIRED_BORON_DIMENSIONS <= set(dimensions), "candidate space lacks required boron dimensions")
    dimension_ids = sorted(dimensions)
    expected = {item["dimension_id"]: set(item["expected_levels"]) for item in study["coverage_dimensions"]}
    for dim_id in dimension_ids:
        if dim_id in expected:
            actual = {item["level_id"] for item in dimensions[dim_id]["levels"]}
            require(actual == expected[dim_id], f"{dim_id}: candidate-space levels differ from study coverage")

    entries: list[dict[str, Any]] = []
    seen_equivalence: dict[str, str] = {}
    exclusions: list[dict[str, Any]] = []
    prefix = space.get("candidate_id_prefix", "boron_ts")
    require(ID_RE.fullmatch(prefix) is not None and len(prefix) <= 48, "invalid candidate_id_prefix")
    level_lists = [sorted(dimensions[dim_id]["levels"], key=lambda x: x["level_id"]) for dim_id in dimension_ids]
    for state_id, channel_id, combination in itertools.product(state_ids, sorted(group["channel_ids"]), itertools.product(*level_lists)):
        selection = dict(zip(dimension_ids, combination))
        compatible, reason = _compatible(channel_id, state_id, selection, space.get("exclusion_rules", []))
        selected_ids = {key: selection[key]["level_id"] for key in dimension_ids}
        base = {"channel_id": channel_id, "catalyst_state_id": state_id, "dimensions": selected_ids}
        if not compatible:
            exclusions.append({**base, "reason": reason})
            continue
        canonical_key = sha256_data(base)
        equivalence = {
            "channel_id": channel_id,
            "catalyst_state_id": state_id,
            "dimensions": {key: selection[key]["equivalence_key"] for key in dimension_ids},
        }
        equivalence_key = sha256_data(equivalence)
        candidate_id = f"{prefix}_{canonical_key[:12]}"
        duplicate_of = seen_equivalence.get(equivalence_key)
        if duplicate_of is None:
            seen_equivalence[equivalence_key] = candidate_id
        entries.append(
            {
                "candidate_id": candidate_id,
                "channel_id": channel_id,
                "catalyst_state_id": state_id,
                "dimensions": selected_ids,
                "canonical_key": canonical_key,
                "logical_equivalence_key": equivalence_key,
                "status": "duplicate_logical" if duplicate_of else "unmaterialized",
                "duplicate_of": duplicate_of,
                "candidate_artifact": None,
                "geometry_fingerprint": None,
                "diagnostics": ["logically equivalent level combination"] if duplicate_of else [],
            }
        )
    ledger = {
        "schema": "gaussian-asymmetric-candidate-ledger/1",
        "study_id": study["study_id"],
        "study_sha256": sha256_file(study_path),
        "comparison_group_id": group_id,
        "mechanism_id": group["mechanism_id"],
        "protocol_id": group["protocol_id"],
        "calculation_ready": False,
        "no_submission_authorization": True,
        "candidate_space_spec": artifact(space_path),
        "geometry_dedup_tolerance_angstrom": float(space.get("geometry_dedup_tolerance_angstrom", 0.01)),
        "dimension_ids": dimension_ids,
        "entries": sorted(entries, key=lambda x: x["candidate_id"]),
        "excluded_combinations": sorted(exclusions, key=lambda x: canonical_bytes(x)),
        "counts": {
            "enumerated": len(entries) + len(exclusions),
            "retained": sum(item["status"] == "unmaterialized" for item in entries),
            "logical_duplicates": sum(item["status"] == "duplicate_logical" for item in entries),
            "excluded": len(exclusions),
            "materialized_unique": 0,
            "geometry_duplicates": 0,
        },
    }
    write_json(output, ledger)
    return ledger


def parse_xyz(path: Path) -> tuple[list[str], list[tuple[float, float, float]]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    require(lines, f"empty XYZ: {path}")
    count = int(lines[0].strip())
    require(len(lines) >= count + 2, f"truncated XYZ: {path}")
    elements: list[str] = []
    coordinates: list[tuple[float, float, float]] = []
    for line in lines[2 : count + 2]:
        fields = line.split()
        require(len(fields) >= 4, f"malformed XYZ row: {line}")
        elements.append(fields[0])
        coordinates.append(tuple(float(value) for value in fields[1:4]))
    return elements, coordinates


def geometry_fingerprint(elements: list[str], coordinates: list[tuple[float, float, float]], precision: int = 6) -> dict[str, Any]:
    distances: list[float] = []
    for index, left in enumerate(coordinates):
        for right in coordinates[index + 1 :]:
            distances.append(round(math.dist(left, right), precision))
    payload = {"elements": elements, "upper_triangle_distances_angstrom": distances}
    return {"method": "ordered_atom_pair_distance_matrix_v1", "sha256": sha256_data(payload), **payload}


def _hill_formula(elements: list[str]) -> tuple[str, dict[str, int]]:
    counts: dict[str, int] = {}
    for element in elements:
        require(re.fullmatch(r"[A-Z][a-z]?", element) is not None, f"invalid element symbol: {element}")
        counts[element] = counts.get(element, 0) + 1
    order: list[str] = []
    if "C" in counts:
        order.append("C")
        if "H" in counts:
            order.append("H")
    order.extend(sorted(element for element in counts if element not in order))
    formula = "".join(element + (str(counts[element]) if counts[element] != 1 else "") for element in order)
    return formula, counts


def _coordinate_block_sha256(elements: list[str], coordinates: list[tuple[float, float, float]]) -> str:
    block = "".join(
        f"{element} {x:.8f} {y:.8f} {z:.8f}\n"
        for element, (x, y, z) in zip(elements, coordinates)
    )
    return hashlib.sha256(block.encode("ascii")).hexdigest()


def build_literature_benchmark(source_path: Path, output: Path) -> dict[str, Any]:
    """Build a non-runnable, hash-bound ledger from reviewed literature XYZ files."""
    source = load_json(source_path)
    require(source.get("schema") == "gaussian-asymmetric-literature-benchmark-source/1", "unrecognized literature benchmark source schema")
    ledger_id = source.get("ledger_id")
    require(ID_RE.fullmatch(str(ledger_id or "")) is not None, "invalid literature benchmark ledger_id")
    records = source.get("candidates", [])
    require(isinstance(records, list) and records, "literature benchmark candidates must be a non-empty array")
    reported_protocol = source.get("reported_protocol", {})
    require(reported_protocol.get("status") == "literature_record_not_approved_protocol", "literature protocol must remain unapproved")
    require(reported_protocol.get("route_keywords") is None, "literature benchmark must not carry a runnable Gaussian route")
    candidate_ids = [item.get("candidate_id") for item in records]
    require(len(candidate_ids) == len(set(candidate_ids)), "duplicate literature benchmark candidate_id")
    root = source_path.parent.resolve()
    built: list[dict[str, Any]] = []
    for record in sorted(records, key=lambda item: item.get("candidate_id", "")):
        candidate_id = record.get("candidate_id")
        require(ID_RE.fullmatch(str(candidate_id or "")) is not None, "invalid literature benchmark candidate_id")
        relative_geometry = Path(str(record.get("geometry_path", "")))
        require(not relative_geometry.is_absolute(), f"{candidate_id}: geometry path must be relative")
        supplied_geometry = source_path.parent / relative_geometry
        require(not supplied_geometry.is_symlink(), f"{candidate_id}: geometry symlinks are refused")
        geometry_path = supplied_geometry.resolve()
        require(geometry_path.is_relative_to(root), f"{candidate_id}: geometry escapes benchmark directory")
        require(geometry_path.is_file(), f"{candidate_id}: geometry not found")
        elements, coordinates = parse_xyz(geometry_path)
        formula, element_counts = _hill_formula(elements)
        block_sha256 = _coordinate_block_sha256(elements, coordinates)
        require(len(elements) == record.get("expected_atom_count"), f"{candidate_id}: atom-count mismatch")
        require(formula == record.get("expected_formula"), f"{candidate_id}: formula mismatch")
        require(block_sha256 == record.get("expected_coordinate_block_sha256"), f"{candidate_id}: canonical coordinate-block hash mismatch")
        changes: list[dict[str, Any]] = []
        for change in record.get("coordinate_changes", []):
            atoms = change.get("atoms", [])
            require(len(atoms) in {2, 3} and all(isinstance(index, int) and 1 <= index <= len(elements) for index in atoms), f"{candidate_id}: invalid coordinate-change atom indices")
            measured = []
            for pair in change.get("distance_pairs", []):
                pair_atoms = pair.get("atoms", [])
                require(len(pair_atoms) == 2 and all(isinstance(index, int) and 1 <= index <= len(elements) for index in pair_atoms), f"{candidate_id}: invalid distance-pair atom indices")
                distance = math.dist(coordinates[pair_atoms[0] - 1], coordinates[pair_atoms[1] - 1])
                measured.append({**pair, "measured_from_coordinates_angstrom": round(distance, 8)})
            changes.append({key: value for key, value in change.items() if key != "distance_pairs"} | {"distance_pairs": measured})
        fingerprint = geometry_fingerprint(elements, coordinates)
        built.append(
            {
                "candidate_id": candidate_id,
                "literature_label": record["literature_label"],
                "priority": record["priority"],
                "stage": record["stage"],
                "identity": record["identity"],
                "geometry": {
                    "format": "xyz",
                    "artifact": {"path": relative_geometry.as_posix(), "sha256": sha256_file(geometry_path)},
                    "canonical_coordinate_block_sha256": block_sha256,
                    "geometry_fingerprint": {"method": fingerprint["method"], "sha256": fingerprint["sha256"]},
                    "source_pages": record["source_pages"],
                    "extraction_review": record["extraction_review"],
                },
                "atom_inventory": {
                    "formula": formula,
                    "atom_count": len(elements),
                    "element_counts": dict(sorted(element_counts.items())),
                    "atom_order": elements,
                },
                "electronic_state": record["electronic_state"],
                "coordinate_changes": changes,
                "expected_result": record["expected_result"],
                "calculation_ready": False,
                "no_submission_authorization": True,
                "review_status": "literature_coordinates_verified_offline",
                "gates": record["gates"],
            }
        )
    ledger = {
        "schema": "gaussian-asymmetric-literature-benchmark-ledger/1",
        "ledger_id": ledger_id,
        "status": "offline_literature_reference",
        "calculation_ready": False,
        "no_submission_authorization": True,
        "source_spec": {"path": source_path.name, "sha256": sha256_file(source_path)},
        "citation": source["citation"],
        "reported_protocol": reported_protocol,
        "unresolved_submission_fields": source["unresolved_submission_fields"],
        "candidates": built,
        "deferred_benchmarks": sorted(source.get("deferred_benchmarks", []), key=lambda item: item.get("benchmark_id", "")),
        "workflow_order": source["workflow_order"],
    }
    ledger["ledger_payload_sha256"] = sha256_data(ledger)
    write_json(output, ledger)
    return ledger


def _same_geometry(left: dict[str, Any], right: dict[str, Any], tolerance: float) -> bool:
    if left["elements"] != right["elements"]:
        return False
    a = left["upper_triangle_distances_angstrom"]
    b = right["upper_triangle_distances_angstrom"]
    return len(a) == len(b) and all(abs(x - y) <= tolerance for x, y in zip(a, b))


def materialize_candidates(study_path: Path, ledger_path: Path, materializations_path: Path, output_dir: Path) -> dict[str, Any]:
    study = load_json(study_path)
    ledger = load_json(ledger_path)
    specs = load_json(materializations_path)
    require(ledger.get("schema") == "gaussian-asymmetric-candidate-ledger/1", "unrecognized ledger schema")
    require(ledger.get("study_sha256") == sha256_file(study_path), "ledger study hash mismatch")
    require(specs.get("schema") == "gaussian-asymmetric-materializations/1", "unrecognized materialization schema")
    require(specs.get("ledger_sha256") == sha256_file(ledger_path), "materialization ledger hash mismatch")
    by_id = {item["candidate_id"]: item for item in specs.get("records", [])}
    require(len(by_id) == len(specs.get("records", [])), "duplicate materialization candidate_id")
    materializable_ids = {item["candidate_id"] for item in ledger.get("entries", []) if item.get("status") == "unmaterialized"}
    require(set(by_id) <= materializable_ids, "materialization references a missing or logically duplicate ledger entry")
    groups = {item["comparison_group_id"]: item for item in study["comparison_groups"]}
    group = groups[ledger["comparison_group_id"]]
    mechanisms = {item["mechanism_id"]: item for item in study["mechanism_hypotheses"]}
    mechanism = mechanisms[ledger["mechanism_id"]]
    states = {item["state_id"]: item for item in study["catalyst_states"]}
    channels = {item["channel_id"]: item for item in study["channels"]}
    output_dir.mkdir(parents=True, exist_ok=True)
    seen: list[tuple[str, str, str, dict[str, Any]]] = []
    updated = copy.deepcopy(ledger)
    candidates_written = 0
    geometry_duplicates = 0
    for entry in updated["entries"]:
        if entry["status"] == "duplicate_logical":
            continue
        spec = by_id.get(entry["candidate_id"])
        if spec is None:
            continue
        supplied_geometry_path = materializations_path.parent / spec["geometry_path"]
        require(not supplied_geometry_path.is_symlink(), f"geometry symlinks are refused: {supplied_geometry_path}")
        geometry_path = supplied_geometry_path.resolve()
        require(geometry_path.is_file(), f"invalid geometry path: {geometry_path}")
        require(spec.get("geometry_format") == "xyz", "version 1 materializer accepts XYZ only")
        elements, coordinates = parse_xyz(geometry_path)
        atom_map = spec.get("atom_map", [])
        require(elements == [item.get("element") for item in atom_map], f"{entry['candidate_id']}: XYZ/atom-map element mismatch")
        inventory = spec.get("atom_inventory", {})
        require(inventory.get("atom_count") == len(atom_map), f"{entry['candidate_id']}: atom inventory/map mismatch")
        element_counts: dict[str, int] = {}
        for element in elements:
            element_counts[element] = element_counts.get(element, 0) + 1
        require(inventory.get("element_counts") == element_counts, f"{entry['candidate_id']}: element-count mismatch")
        require(spec.get("chemical_state", {}).get("charge") == spec.get("electronic_state", {}).get("charge"), f"{entry['candidate_id']}: charge mismatch")
        require(spec.get("chemical_state", {}).get("multiplicity") == spec.get("electronic_state", {}).get("multiplicity"), f"{entry['candidate_id']}: multiplicity mismatch")
        fp = geometry_fingerprint(elements, coordinates)
        duplicate_of = None
        for channel_id, state_id, atom_key, previous in seen:
            current_atom_key = sha256_data(atom_map)
            if channel_id == entry["channel_id"] and state_id == entry["catalyst_state_id"] and atom_key == current_atom_key and _same_geometry(fp, previous["fingerprint"], ledger["geometry_dedup_tolerance_angstrom"]):
                duplicate_of = previous["candidate_id"]
                break
        state = states[entry["catalyst_state_id"]]
        support = state.get("support_status", "unresolved")
        if state.get("metal_centers"):
            support = "unsupported_transition_metal"
        electronic = spec["electronic_state"]
        if electronic.get("multiplicity") != 1 or electronic.get("broken_symmetry") not in {"not_applicable", "not_requested"} or electronic.get("multireference_concern") != "none_identified":
            support = "unsupported_electronic_structure"
        review_status = "rejected" if duplicate_of else "proposed"
        dimensions = entry["dimensions"]
        candidate = {
            "schema": "gaussian-asymmetric-ts-candidate/1",
            "candidate_id": entry["candidate_id"],
            "study_id": study["study_id"],
            "study_sha256": sha256_file(study_path),
            "comparison_group_id": ledger["comparison_group_id"],
            "mechanism_id": ledger["mechanism_id"],
            "channel_id": entry["channel_id"],
            "catalyst_state_id": entry["catalyst_state_id"],
            "protocol_id": ledger["protocol_id"],
            "calculation_ready": False,
            "no_submission_authorization": True,
            "support_status": support,
            "review_status": review_status,
            "chemical_state": spec["chemical_state"],
            "candidate_dimensions": dimensions,
            "binding_mode": spec["binding_mode"],
            "approach_topology": spec["approach_topology"],
            "conformer_sources": spec["conformer_sources"],
            "electronic_state": electronic,
            "atom_inventory": inventory,
            "atom_map": atom_map,
            "coordinate_changes": spec.get("coordinate_changes", mechanism["coordinate_changes"]),
            "geometry": {
                "format": "xyz",
                "artifact": artifact(geometry_path),
                "construction_method": spec["construction_method"],
                "stereochemistry_reviewed": bool(spec.get("stereochemistry_reviewed", False)),
                "clash_reviewed": bool(spec.get("clash_reviewed", False)),
            },
            "resource_tier_proposal": spec.get("resource_tier_proposal", "unresolved"),
            "deduplication": {
                "status": "duplicate" if duplicate_of else "unique",
                "duplicate_of": duplicate_of,
                "method": "channel-preserving ordered atom-pair distance matrix",
                "review_notes": "Automatic offline geometry duplicate; rejected pending human review." if duplicate_of else "Unique within the materialized same-channel/state set.",
            },
            "coverage_tags": dimensions,
            "warnings": (["Geometry duplicate; automatic promotion is forbidden."] if duplicate_of else []) + (["Unsupported transition-metal state; submission is refused."] if support == "unsupported_transition_metal" else []) + (["Unsupported electronic structure; submission is refused."] if support == "unsupported_electronic_structure" else []),
            "review": {"reviewer": None, "decision": "rejected" if duplicate_of else "pending", "decision_record": None},
        }
        candidate_path = output_dir / f"{entry['candidate_id']}.json"
        write_json(candidate_path, candidate)
        entry["status"] = "duplicate_geometry" if duplicate_of else "materialized_unique"
        entry["duplicate_of"] = duplicate_of
        entry["candidate_artifact"] = artifact(candidate_path)
        entry["geometry_fingerprint"] = {"method": fp["method"], "sha256": fp["sha256"]}
        if duplicate_of:
            geometry_duplicates += 1
        else:
            seen.append((entry["channel_id"], entry["catalyst_state_id"], sha256_data(atom_map), {"candidate_id": entry["candidate_id"], "fingerprint": fp}))
        candidates_written += 1
    updated["counts"]["materialized_unique"] = sum(item["status"] == "materialized_unique" for item in updated["entries"])
    updated["counts"]["geometry_duplicates"] = geometry_duplicates
    updated["materialization_spec"] = artifact(materializations_path)
    updated["candidates_written"] = candidates_written
    write_json(output_dir / "candidate-ledger.json", updated)
    return updated


def _nullable_artifact(path: Path | None) -> dict[str, str] | None:
    return artifact(path) if path is not None else None


def _validate_checkpoint_lineage(
    audit: dict[str, Any],
    audit_path: Path,
    candidate: dict[str, Any],
    expected_order: list[dict[str, Any]],
    ts_result_path: Path,
    mode_review_path: Path,
    mode_decision_path: Path,
    input_path: Path,
    log_path: Path,
    checkpoint_path: Path,
) -> None:
    require(audit.get("schema") == "gaussian-checkpoint-geometry-audit/1" and audit.get("audit_status") == "passed", "path validation requires a passed checkpoint-geometry audit")
    bindings = {
        "ts_input_sha256": input_path,
        "ts_log_sha256": log_path,
        "ts_result_sha256": ts_result_path,
        "mode_review_sha256": mode_review_path,
        "mode_decision_sha256": mode_decision_path,
        "checkpoint_sha256": checkpoint_path,
    }
    for field, path in bindings.items():
        require(audit.get(field) == sha256_file(path), f"checkpoint audit {field} mismatch")
    chemical = candidate.get("chemical_state", {})
    require(audit.get("charge") == chemical.get("charge"), "checkpoint audit charge differs from candidate")
    require(audit.get("multiplicity") == chemical.get("multiplicity"), "checkpoint audit multiplicity differs from candidate")
    require(audit.get("atom_count") == len(expected_order), "checkpoint audit atom count differs from candidate")
    require(audit.get("checkpoint_file") == checkpoint_path.name, "checkpoint audit filename differs from supplied checkpoint")
    _require_matching_atom_order(audit.get("atom_order"), expected_order, "checkpoint audit")
    checks = audit.get("checks")
    required_checks = {
        "ts_input_checkpoint_name_matches", "ts_result_log_hash_matches", "charge_multiplicity_matches",
        "input_log_result_atom_order_matches", "imaginary_mode_atom_order_matches", "accepted_mode_decision_hashes_match",
    }
    require(isinstance(checks, dict) and all(checks.get(key) is True for key in required_checks), "checkpoint audit checks are incomplete")
    require(audit_path.is_file() and not audit_path.is_symlink(), "checkpoint audit must be an existing non-symlink file")


def _validate_irc_plan(
    plan: dict[str, Any],
    ts_result_path: Path,
    mode_decision_path: Path,
    checkpoint_path: Path,
    endpoint_by_direction: dict[str, dict[str, Any]],
) -> None:
    require(plan.get("schema") == "gaussian-irc-plan/1", "unrecognized IRC plan")
    require(plan.get("submission_status") == "planned_not_submitted", "IRC plan has an invalid submission status")
    require(plan.get("ts_result_sha256") == sha256_file(ts_result_path), "IRC plan TS result hash mismatch")
    require(plan.get("mode_decision_sha256") == sha256_file(mode_decision_path), "IRC plan mode decision hash mismatch")
    require(plan.get("checkpoint_sha256") == sha256_file(checkpoint_path), "IRC plan checkpoint hash mismatch")
    directions = plan.get("directions")
    require(isinstance(directions, list) and len(directions) == 2, "IRC plan must contain exactly two directions")
    planned: dict[str, dict[str, Any]] = {}
    for item in directions:
        require(isinstance(item, dict) and item.get("direction") in {"forward", "reverse"}, "IRC plan has an invalid direction")
        require(item["direction"] not in planned, "IRC plan repeats a direction")
        require(isinstance(item.get("project"), str) and item["project"], "IRC plan direction lacks a project")
        planned[item["direction"]] = item
    require(set(planned) == {"forward", "reverse"}, "IRC plan directions are incomplete")
    require(planned["forward"]["project"] != planned["reverse"]["project"], "IRC plan projects must be distinct")
    for direction, item in planned.items():
        route = str(item.get("route", ""))
        opposite = "reverse" if direction == "forward" else "forward"
        require(re.search(r"\birc\b", route, re.I) is not None and re.search(rf"\b{direction}\b", route, re.I) is not None and re.search(rf"\b{opposite}\b", route, re.I) is None, f"IRC plan {direction} route is invalid")
    for direction, endpoint in endpoint_by_direction.items():
        require(planned[direction]["project"] == endpoint.get("project"), f"{direction} endpoint project differs from IRC plan")


def _validate_endpoint_audit(
    endpoint: dict[str, Any],
    direction: str,
    candidate: dict[str, Any],
    expected_order: list[dict[str, Any]],
) -> None:
    require(endpoint.get("schema") == "gaussian-irc-endpoint-audit/1", f"unrecognized {direction} endpoint audit")
    require(endpoint.get("audit_status") == "passed", f"{direction} endpoint audit did not pass")
    require(endpoint.get("direction") == direction, f"{direction} endpoint direction mismatch")
    require(endpoint.get("chemical_side") in {"reactant", "product"}, f"{direction} endpoint lacks a reviewed chemical side")
    chemical = candidate.get("chemical_state", {})
    require(endpoint.get("charge") == chemical.get("charge"), f"{direction} endpoint charge differs from candidate")
    require(endpoint.get("multiplicity") == chemical.get("multiplicity"), f"{direction} endpoint multiplicity differs from candidate")
    require(endpoint.get("atom_count") == len(expected_order), f"{direction} endpoint atom count differs from candidate")
    _require_matching_atom_order(endpoint.get("atom_order"), expected_order, f"{direction} endpoint")
    for field in ("checkpoint_sha256", "irc_input_sha256", "irc_log_sha256", "irc_result_sha256", "irc_job_sha256"):
        _require_sha256(endpoint.get(field), f"{direction} endpoint lacks a valid {field}")
    require(isinstance(endpoint.get("project"), str) and endpoint["project"], f"{direction} endpoint lacks a project")
    require(isinstance(endpoint.get("completed_point"), int) and endpoint["completed_point"] >= 1, f"{direction} endpoint completed point is invalid")
    require(isinstance(endpoint.get("corrector_convergence_count"), int) and endpoint["corrector_convergence_count"] >= endpoint["completed_point"], f"{direction} endpoint lacks complete corrector convergence evidence")
    checks = endpoint.get("checks")
    required_checks = {
        "directional_path_complete", "all_points_corrector_converged", "normal_termination",
        "input_job_hash_matches", "checkpoint_name_matches", "log_result_atom_order_and_coordinates_match",
    }
    require(isinstance(checks, dict) and all(checks.get(key) is True for key in required_checks), f"{direction} endpoint audit checks are incomplete")
    reviewed_pairs = {
        tuple(sorted(item.get("pair", [])))
        for item in endpoint.get("reviewed_forming_bond_distances", [])
        if isinstance(item, dict)
    }
    require(bool(reviewed_pairs), f"{direction} endpoint lacks reviewed forming-bond distances")
    for item in endpoint.get("reviewed_forming_bond_distances", []):
        require(isinstance(item, dict) and _is_finite_number(item.get("distance_angstrom")) and item["distance_angstrom"] > 0, f"{direction} endpoint has an invalid reviewed distance")
    expected_pairs = {
        tuple(sorted(change.get("atoms", [])))
        for change in candidate.get("coordinate_changes", [])
        if isinstance(change, dict) and change.get("kind") == "forming"
    }
    require(expected_pairs <= reviewed_pairs, f"{direction} endpoint lacks reviewed forming-bond distances")


def ingest_result(
    candidate_path: Path,
    ts_result_path: Path,
    energy_path: Path,
    output: Path,
    mode_review_path: Path | None = None,
    mode_decision_path: Path | None = None,
    forward_path: Path | None = None,
    reverse_path: Path | None = None,
    input_path: Path | None = None,
    log_path: Path | None = None,
    checkpoint_path: Path | None = None,
    checkpoint_audit_path: Path | None = None,
    irc_plan_path: Path | None = None,
) -> dict[str, Any]:
    supplied_paths = {
        "candidate": candidate_path, "TS result": ts_result_path, "energy record": energy_path,
        "mode review": mode_review_path, "mode decision": mode_decision_path,
        "forward endpoint audit": forward_path, "reverse endpoint audit": reverse_path,
        "TS input": input_path, "TS log": log_path, "TS checkpoint": checkpoint_path,
        "checkpoint audit": checkpoint_audit_path, "IRC plan": irc_plan_path,
    }
    for label, path in supplied_paths.items():
        if path is not None:
            require(path.is_file() and not path.is_symlink(), f"{label} must be an existing non-symlink file")
    candidate = load_json(candidate_path)
    ts = load_json(ts_result_path)
    energy = load_json(energy_path)
    require(candidate.get("schema") == "gaussian-asymmetric-ts-candidate/1", "unrecognized candidate schema")
    require(candidate.get("support_status") == "supported_main_group_closed_shell", "result ingestion refuses unsupported electronic structures")
    require(candidate.get("review_status") == "promoted_offline" and candidate.get("review", {}).get("decision") == "promoted_offline", "result ingestion requires a promoted_offline candidate")
    require(candidate.get("calculation_ready") is False and candidate.get("no_submission_authorization") is True, "candidate violates offline safety flags")
    require(ts.get("schema") == "gaussian-ts-freq-result/1", "unrecognized TS result schema")
    require(energy.get("schema") == "gaussian-asymmetric-energy-record/1", "unrecognized energy record schema")
    require(energy.get("candidate_id") == candidate.get("candidate_id"), "energy candidate mismatch")
    expected_order = _candidate_atom_order(candidate)
    require(energy.get("inventory_key") == candidate.get("atom_inventory", {}).get("inventory_key"), "energy inventory differs from candidate")
    for field in ("electronic_energy", "thermal_gibbs_correction", "comparison_free_energy"):
        value = energy.get(field)
        require(value is None or _is_finite_number(value), f"energy {field} must be finite or null")
    require(_is_finite_number(energy.get("temperature_k")) and float(energy["temperature_k"]) > 0, "energy temperature must be finite and positive")
    require(energy.get("energy_unit") in {"hartree", "kcal_mol", "kj_mol"}, "energy unit is invalid")
    require(isinstance(energy.get("comparison_energy_definition"), str) and energy["comparison_energy_definition"].strip(), "energy comparison definition is missing")
    require(energy.get("standard_state") in {"1M", "1atm", "explicit_custom"}, "energy standard state is invalid")
    require(isinstance(energy.get("low_frequency_policy"), str) and energy["low_frequency_policy"].strip(), "energy low-frequency policy is missing")
    degeneracy = energy.get("degeneracy")
    require(isinstance(degeneracy, int) and not isinstance(degeneracy, bool) and degeneracy >= 1, "energy degeneracy must be a positive integer")
    first_order = bool(ts.get("status") == "completed" and ts.get("normal_termination_count", 0) >= 1 and ts.get("error_termination_count", 0) == 0 and ts.get("optimization_completed") and ts.get("stationary_point_found") and ts.get("frequency_count", 0) > 0 and ts.get("raw_imaginary_frequency_count") == 1 and ts.get("first_order_saddle_candidate"))
    level = "first_order_saddle_candidate" if first_order else "failed"
    mode_decision = "not_available"
    mode_reviewed = False
    if mode_review_path is not None or mode_decision_path is not None:
        require(mode_review_path is not None and mode_decision_path is not None, "mode review and decision must be supplied together")
        review = load_json(mode_review_path)
        decision = load_json(mode_decision_path)
        require(review.get("schema") == "gaussian-ts-mode-review/1", "unrecognized mode review")
        require(review.get("ts_result_sha256") == sha256_file(ts_result_path), "mode review TS hash mismatch")
        require(decision.get("schema") == "gaussian-ts-mode-decision/1", "unrecognized mode decision")
        require(decision.get("ts_result_sha256") == sha256_file(ts_result_path), "mode decision TS hash mismatch")
        require(decision.get("mode_review_sha256") == sha256_file(mode_review_path), "mode decision review hash mismatch")
        mode_decision = decision.get("decision", "unclear")
        mode_reviewed = first_order and mode_decision == "accepted" and decision.get("confirmed") is True
        if mode_reviewed:
            level = "mode_reviewed"
    path_forward = "not_run"
    path_reverse = "not_run"
    endpoint_reviewed = False
    if forward_path is not None or reverse_path is not None:
        require(forward_path is not None and reverse_path is not None, "both endpoint audits are required")
        require(mode_reviewed and mode_review_path is not None and mode_decision_path is not None, "endpoint ingestion requires an accepted hash-bound mode decision")
        require(all(path is not None for path in (input_path, log_path, checkpoint_path, checkpoint_audit_path, irc_plan_path)), "endpoint ingestion requires TS input, log, checkpoint, checkpoint audit, and IRC plan")
        require(ts.get("log_sha256") == sha256_file(log_path), "TS result log hash mismatch")  # type: ignore[arg-type]
        _require_matching_atom_order(ts.get("final_coordinates"), expected_order, "TS result")
        imaginary_modes = ts.get("imaginary_modes", [])
        require(len(imaginary_modes) == 1, "path validation requires exactly one parsed imaginary mode")
        _require_matching_atom_order(imaginary_modes[0].get("displacements"), expected_order, "TS imaginary-mode displacement")
        forward = load_json(forward_path)
        reverse = load_json(reverse_path)
        require(forward.get("direction") == "forward" and reverse.get("direction") == "reverse", "forward/reverse endpoint arguments are swapped")
        endpoint_by_direction = {str(item.get("direction")): item for item in (forward, reverse)}
        require(set(endpoint_by_direction) == {"forward", "reverse"}, "endpoint directions are incomplete")
        for direction, endpoint in endpoint_by_direction.items():
            _validate_endpoint_audit(endpoint, direction, candidate, expected_order)
        require({forward.get("chemical_side"), reverse.get("chemical_side")} == {"reactant", "product"}, "endpoint identities are not complementary")
        checkpoint_audit = load_json(checkpoint_audit_path)  # type: ignore[arg-type]
        _validate_checkpoint_lineage(
            checkpoint_audit, checkpoint_audit_path, candidate, expected_order, ts_result_path,
            mode_review_path, mode_decision_path, input_path, log_path, checkpoint_path,  # type: ignore[arg-type]
        )
        plan = load_json(irc_plan_path)  # type: ignore[arg-type]
        _validate_irc_plan(plan, ts_result_path, mode_decision_path, checkpoint_path, endpoint_by_direction)  # type: ignore[arg-type]
        path_forward = path_reverse = "completed_and_identified"
        endpoint_reviewed = True
        if mode_reviewed:
            level = "path_validated"
    energies = {key: energy[key] for key in ("energy_unit", "electronic_energy", "thermal_gibbs_correction", "comparison_free_energy", "comparison_energy_definition", "temperature_k", "standard_state", "low_frequency_policy", "inventory_key", "degeneracy")}
    reasons: list[str] = []
    if VALIDATION_RANK[level] < 2:
        reasons.append("TS normal mode has not been explicitly accepted")
    if energies["comparison_free_energy"] is None:
        reasons.append("comparison free energy is absent")
    eligible = not reasons
    result = {
        "schema": "gaussian-asymmetric-ts-result/1",
        "result_id": energy.get("result_id") or f"res_{candidate['candidate_id']}",
        "candidate_id": candidate["candidate_id"],
        "candidate_sha256": sha256_file(candidate_path),
        "study_id": candidate["study_id"],
        "comparison_group_id": candidate["comparison_group_id"],
        "channel_id": candidate["channel_id"],
        "protocol_id": candidate["protocol_id"],
        "calculation_ready": False,
        "no_submission_authorization": True,
        "validation_level": level,
        "artifacts": {
            "input": _nullable_artifact(input_path), "log": _nullable_artifact(log_path), "checkpoint": _nullable_artifact(checkpoint_path),
            "parsed_ts_result": artifact(ts_result_path), "mode_review": _nullable_artifact(mode_review_path), "mode_decision": _nullable_artifact(mode_decision_path),
            "checkpoint_audit": _nullable_artifact(checkpoint_audit_path), "irc_plan": _nullable_artifact(irc_plan_path),
            "forward_path": _nullable_artifact(forward_path), "reverse_path": _nullable_artifact(reverse_path),
        },
        "termination": {
            "normal_termination": ts.get("normal_termination_count", 0) >= 1,
            "error_termination": ts.get("error_termination_count", 0) > 0,
            "stationary_point": bool(ts.get("stationary_point_found")),
            "frequency_complete": ts.get("frequency_count", 0) > 0,
        },
        "frequency_evidence": {
            "frequencies_cm1": ts.get("frequencies_cm-1", []),
            "raw_imaginary_frequency_count": int(ts.get("raw_imaginary_frequency_count", 0)),
            "reviewed_imaginary_frequency_cm1": ts.get("imaginary_modes", [{}])[0].get("frequency_cm-1") if mode_reviewed and ts.get("imaginary_modes") else None,
        },
        "mode_evidence": {"decision": mode_decision, "coordinate_projection_reviewed": mode_reviewed, "review_notes": "Hash-bound gaussian-ts-irc mode decision." if mode_reviewed else "Mode acceptance is absent or incomplete."},
        "path_evidence": {"forward": path_forward, "reverse": path_reverse, "endpoint_identity_reviewed": endpoint_reviewed, "review_notes": "Both hash-bound endpoint audits passed." if endpoint_reviewed else "IRC path evidence is absent."},
        "energies": energies,
        "comparison_eligibility": {"eligible": eligible, "reasons": reasons},
        "diagnostics": list(ts.get("diagnostics", [])),
    }
    write_json(output, result)
    return result


def _to_kcal(value: float, unit: str) -> float:
    if unit == "kcal_mol":
        return value
    if unit == "kj_mol":
        return value * KCAL_PER_KJ
    if unit == "hartree":
        return value * KCAL_PER_HARTREE
    raise OfflineError(f"unsupported energy unit: {unit}")


def _logsumexp(values: list[float]) -> float:
    peak = max(values)
    return peak + math.log(sum(math.exp(value - peak) for value in values))


def _selectivity(records: list[dict[str, Any]], channels: list[str], temperature: float, perturb: dict[str, float] | None = None) -> dict[str, Any]:
    r_kcal = 0.00198720425864083
    perturb = perturb or {}
    raw: list[tuple[str, str, float, int]] = []
    for item in records:
        energy = _to_kcal(float(item["energies"]["comparison_free_energy"]), item["energies"]["energy_unit"]) + perturb.get(item["result_id"], 0.0)
        raw.append((item["channel_id"], item["result_id"], energy, int(item["energies"]["degeneracy"])))
    zero = min(item[2] for item in raw)
    channel_logs: dict[str, float] = {}
    summaries: list[dict[str, Any]] = []
    for channel in channels:
        subset = [item for item in raw if item[0] == channel]
        require(subset, f"channel {channel} has no included result")
        logs = [math.log(degeneracy) - (energy - zero) / (r_kcal * temperature) for _, _, energy, degeneracy in subset]
        log_weight = _logsumexp(logs)
        channel_logs[channel] = log_weight
        effective = zero - r_kcal * temperature * log_weight
        summaries.append({"channel_id": channel, "candidate_result_ids": sorted(item[1] for item in subset), "log_weight": log_weight, "effective_barrier": effective, "normalized_fraction": 0.0})
    total = _logsumexp(list(channel_logs.values()))
    fractions = {channel: math.exp(value - total) for channel, value in channel_logs.items()}
    for summary in summaries:
        summary["normalized_fraction"] = fractions[summary["channel_id"]]
    ranked = sorted(channels, key=lambda channel: (-fractions[channel], channel))
    major, minor = ranked[0], ranked[1]
    ratio = fractions[major] / fractions[minor]
    ddg = r_kcal * temperature * math.log(ratio)
    ee = 100.0 * (fractions[major] - fractions[minor]) / (fractions[major] + fractions[minor]) if len(channels) == 2 else None
    return {"summaries": summaries, "fractions": fractions, "major": major, "minor": minor, "ratio": ratio, "ddg": ddg, "ee": ee, "zero": zero}


def aggregate(study_path: Path, ledger_path: Path, result_paths: list[Path], output: Path, energy_shift: float) -> dict[str, Any]:
    study = load_json(study_path)
    ledger = load_json(ledger_path)
    require(study.get("schema") == "gaussian-asymmetric-catalysis-study/1", "unrecognized study schema")
    require(ledger.get("schema") == "gaussian-asymmetric-candidate-ledger/1", "unrecognized ledger schema")
    require(ledger.get("calculation_ready") is False and ledger.get("no_submission_authorization") is True, "ledger violates offline safety flags")
    require(ledger.get("study_sha256") == sha256_file(study_path), "ledger study hash mismatch")
    require(_is_finite_number(energy_shift) and energy_shift >= 0, "energy shift must be finite and non-negative")
    require(result_paths, "at least one result is required")
    results = [load_json(path) for path in result_paths]
    for result in results:
        _validate_result_shape(result)
    require(len({item.get("result_id") for item in results}) == len(results), "duplicate result_id")
    groups = {item["comparison_group_id"]: item for item in study["comparison_groups"]}
    require(ledger.get("comparison_group_id") in groups, "ledger comparison group is not in the study")
    group = groups[ledger["comparison_group_id"]]
    require(group.get("aggregation_model") == "boltzmann_ts_ensemble", "aggregate currently supports only boltzmann_ts_ensemble")
    protocols = {item["protocol_id"]: item for item in study["protocol_sets"]}
    require(group.get("protocol_id") in protocols, "comparison-group protocol is not in the study")
    protocol = protocols[group["protocol_id"]]
    require(_is_finite_number(protocol.get("temperature_k")) and float(protocol["temperature_k"]) > 0, "protocol temperature must be finite and positive")
    required = group["required_validation_level"]
    require(required in VALIDATION_RANK, "comparison group has an invalid validation requirement")
    entries = ledger.get("entries")
    require(isinstance(entries, list), "ledger entries must be an array")
    ledger_by_id: dict[str, dict[str, Any]] = {}
    for entry in entries:
        candidate_id = entry.get("candidate_id") if isinstance(entry, dict) else None
        require(ID_RE.fullmatch(str(candidate_id or "")) is not None, "ledger contains an invalid candidate_id")
        require(candidate_id not in ledger_by_id, f"ledger repeats candidate {candidate_id}")
        ledger_by_id[candidate_id] = entry
    path_by_id = {result["result_id"]: path for result, path in zip(results, result_paths)}
    for result in results:
        candidate_id = result["candidate_id"]
        require(candidate_id in ledger_by_id, f"result candidate is outside the ledger: {candidate_id}")
        entry = ledger_by_id[candidate_id]
        require(entry.get("status") == "materialized_unique", f"result candidate is not a unique materialized ledger entry: {candidate_id}")
        candidate_path = _resolve_artifact_path(entry.get("candidate_artifact"), ledger_path, f"candidate {candidate_id}")
        candidate = load_json(candidate_path)
        candidate_hash = sha256_file(candidate_path)
        require(result.get("candidate_sha256") == candidate_hash, f"result candidate hash mismatch: {candidate_id}")
        require(entry["candidate_artifact"].get("sha256") == candidate_hash, f"ledger candidate hash mismatch: {candidate_id}")
        require(candidate.get("schema") == "gaussian-asymmetric-ts-candidate/1" and candidate.get("candidate_id") == candidate_id, f"ledger candidate artifact identity mismatch: {candidate_id}")
        require(candidate.get("review_status") == "promoted_offline" and candidate.get("review", {}).get("decision") == "promoted_offline", f"ledger candidate is not promoted_offline: {candidate_id}")
        require(candidate.get("calculation_ready") is False and candidate.get("no_submission_authorization") is True, f"candidate violates offline safety flags: {candidate_id}")
        require(candidate.get("study_id") == study.get("study_id") and candidate.get("study_sha256") == sha256_file(study_path), f"candidate study binding mismatch: {candidate_id}")
        require(candidate.get("comparison_group_id") == group["comparison_group_id"], f"candidate comparison-group mismatch: {candidate_id}")
        require(candidate.get("channel_id") == entry.get("channel_id") == result.get("channel_id"), f"candidate/result channel mismatch: {candidate_id}")
        require(candidate.get("catalyst_state_id") == entry.get("catalyst_state_id"), f"candidate catalyst-state mismatch: {candidate_id}")
        require(candidate.get("protocol_id") == ledger.get("protocol_id") == group["protocol_id"] == result.get("protocol_id"), f"candidate/result protocol mismatch: {candidate_id}")
        require(result.get("study_id") == study.get("study_id") and result.get("comparison_group_id") == group["comparison_group_id"], f"result study or comparison-group mismatch: {candidate_id}")
    included: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for result in results:
        reasons: list[str] = []
        if result.get("study_id") != study.get("study_id") or result.get("comparison_group_id") != group["comparison_group_id"]:
            reasons.append("study or comparison-group mismatch")
        if not result.get("comparison_eligibility", {}).get("eligible"):
            reasons.extend(result.get("comparison_eligibility", {}).get("reasons", ["result is ineligible"]))
        if VALIDATION_RANK.get(result.get("validation_level"), -1) < VALIDATION_RANK[required]:
            reasons.append("validation level below comparison requirement")
        if reasons:
            excluded.append({"result_id": result["result_id"], "result_sha256": sha256_file(path_by_id[result["result_id"]]), "reason": "; ".join(reasons), "reviewed": False})
        else:
            included.append(result)
    conditions = {
        "temperature_k": float(protocol["temperature_k"]),
        "standard_state": protocol["standard_state"],
        "energy_unit": "kcal_mol",
        "low_frequency_policy": protocol["low_frequency_policy"],
    }
    checks = {
        "common_protocol": len({item["protocol_id"] for item in included}) <= 1 and all(item["protocol_id"] == group["protocol_id"] for item in included),
        "common_reference_state": len({item["energies"]["comparison_energy_definition"] for item in included}) <= 1,
        "common_inventory_or_balanced_cycle": len({item["energies"]["inventory_key"] for item in included}) <= 1,
        "common_temperature": all(item["energies"]["temperature_k"] == conditions["temperature_k"] for item in included),
        "common_standard_state": all(item["energies"]["standard_state"] == conditions["standard_state"] for item in included),
        "common_low_frequency_policy": all(item["energies"]["low_frequency_policy"] == conditions["low_frequency_policy"] for item in included),
    }
    blocking = [key for key, value in checks.items() if not value]
    channels = sorted(group["channel_ids"])
    has_channels = set(channels) <= {item["channel_id"] for item in included}
    can_aggregate = bool(included) and has_channels and not blocking
    if can_aggregate:
        selected = _selectivity(included, channels, conditions["temperature_k"])
        selectivity = {"major_channel_id": selected["major"], "minor_channel_id": selected["minor"], "delta_delta_g_kcal_mol": selected["ddg"], "major_minor_ratio": selected["ratio"], "ee_percent": selected["ee"], "channel_fractions": selected["fractions"], "sign_convention": "G_eff(minor)-G_eff(major)"}
        summaries = selected["summaries"]
    else:
        selected = None
        selectivity = {"major_channel_id": None, "minor_channel_id": None, "delta_delta_g_kcal_mol": None, "major_minor_ratio": None, "ee_percent": None, "channel_fractions": {}, "sign_convention": "G_eff(minor)-G_eff(major)"}
        summaries = []
    dimension_map = {item["dimension_id"]: item for item in study["coverage_dimensions"]}
    included_candidate_ids = {item["candidate_id"] for item in included}
    def represented_by_included(entry: dict[str, Any]) -> bool:
        seen_ids: set[str] = set()
        current = entry
        while current["candidate_id"] not in seen_ids:
            seen_ids.add(current["candidate_id"])
            if current["candidate_id"] in included_candidate_ids:
                return True
            duplicate_of = current.get("duplicate_of")
            if not duplicate_of or duplicate_of not in ledger_by_id:
                return False
            current = ledger_by_id[duplicate_of]
        return False

    coverage = []
    for dim_id in group["coverage_dimension_ids"]:
        expected_levels = sorted(dimension_map[dim_id]["expected_levels"])
        observed = sorted({entry["dimensions"][dim_id] for entry in ledger["entries"] if represented_by_included(entry)})
        counts = {channel: sum(item["channel_id"] == channel for item in included) for channel in channels}
        coverage.append({"dimension_id": dim_id, "expected_levels": expected_levels, "observed_levels": observed, "candidate_counts_by_channel": counts, "exclusions": [], "coverage_status": "complete" if set(observed) == set(expected_levels) and all(counts.values()) else "incomplete"})
    sensitivity: list[dict[str, Any]] = []
    if selected:
        lowest = []
        for channel in channels:
            subset = [item for item in included if item["channel_id"] == channel]
            lowest.append(min(subset, key=lambda item: (_to_kcal(item["energies"]["comparison_free_energy"], item["energies"]["energy_unit"]), item["result_id"])))
        low = _selectivity(lowest, channels, conditions["temperature_k"])
        sensitivity.append({"scenario_id": "lowest_ts_only", "description": "One lowest-energy result per channel.", "major_channel_id": low["major"], "ee_percent": low["ee"], "delta_delta_g_kcal_mol": low["ddg"]})
        perturb = {item["result_id"]: (energy_shift if item["channel_id"] == selected["major"] else -energy_shift) for item in included}
        adversarial = _selectivity(included, channels, conditions["temperature_k"], perturb)
        sensitivity.append({"scenario_id": "adversarial_energy_shift", "description": f"Major-channel energies +{energy_shift:g} and minor-channel energies -{energy_shift:g} kcal/mol.", "major_channel_id": adversarial["major"], "ee_percent": adversarial["ee"], "delta_delta_g_kcal_mol": adversarial["ddg"]})
        if len(included) > len(channels):
            for omitted in sorted(included, key=lambda x: x["result_id"]):
                remaining = [item for item in included if item is not omitted]
                if set(channels) <= {item["channel_id"] for item in remaining}:
                    loo = _selectivity(remaining, channels, conditions["temperature_k"])
                    sensitivity.append({"scenario_id": f"leave_out_{omitted['result_id']}", "description": f"Leave-one-result-out: {omitted['result_id']}.", "major_channel_id": loo["major"], "ee_percent": loo["ee"], "delta_delta_g_kcal_mol": loo["ddg"]})
    ordering_stable = "unknown" if not sensitivity or not selected else ("stable_in_tested_model" if all(item["major_channel_id"] == selected["major"] for item in sensitivity) else "sensitive")
    all_coverage = all(item["coverage_status"] in {"complete", "reviewed_pruned"} for item in coverage)
    status = "blocked_incomparable" if blocking else "incomplete" if not can_aggregate or not all_coverage else "provisional"
    analysis = {
        "schema": "gaussian-asymmetric-selectivity-analysis/1",
        "analysis_id": f"ana_{group['comparison_group_id']}_{sha256_data([item['result_id'] for item in included])[:10]}",
        "study_id": study["study_id"], "study_sha256": sha256_file(study_path), "comparison_group_id": group["comparison_group_id"],
        "calculation_ready": False, "no_submission_authorization": True, "status": status, "protocol_id": group["protocol_id"], "required_validation_level": required,
        "conditions": conditions,
        "included_results": [{"result_id": item["result_id"], "result_sha256": sha256_file(path_by_id[item["result_id"]]), "candidate_id": item["candidate_id"], "channel_id": item["channel_id"], "comparison_free_energy": item["energies"]["comparison_free_energy"], "degeneracy": item["energies"]["degeneracy"]} for item in sorted(included, key=lambda x: x["result_id"])],
        "excluded_results": sorted(excluded, key=lambda x: x["result_id"]),
        "comparability": {"status": "passed" if not blocking else "failed", **checks, "blocking_reasons": blocking},
        "coverage": coverage,
        "aggregation": {"model": "boltzmann_ts_ensemble", "formula": "W_c=sum_i g_i exp(-(G_i-G_0)/(R*T)); G_eff,c=G_0-R*T*ln(W_c)", "gas_constant": 0.00198720425864083, "gas_constant_unit": "kcal_mol_k", "common_energy_zero": f"minimum included comparison energy ({selected['zero']:.12g} kcal/mol)" if selected else "not available", "channel_summaries": summaries, "external_model": None},
        "selectivity": selectivity,
        "uncertainty": {"coverage_limitations": [f"{item['dimension_id']} coverage incomplete" for item in coverage if item["coverage_status"] == "incomplete"], "method_sensitivity": "No alternate electronic-structure protocol evaluated.", "thermochemistry_sensitivity": f"Adversarial +/-{energy_shift:g} kcal/mol and lowest-TS-only scenarios evaluated." if selected else "Not evaluated.", "ordering_stability": ordering_stable, "claim_limitations": ["Automatically generated analysis is provisional until explicit scientific review."], "sensitivity_scenarios": sensitivity},
        "claim": {"statement": "Provisional offline ensemble result; not a validated mechanistic claim." if can_aggregate else "No selectivity claim.", "scope": "Only the supplied, eligible, hash-bound result ensemble.", "path_validation_complete": bool(included) and all(item["validation_level"] == "path_validated" for item in included), "reviewer": None, "decision_record": None},
        "supersedes": None,
    }
    write_json(output, analysis)
    return analysis


def design_metal_support(study_path: Path, output: Path) -> dict[str, Any]:
    study = load_json(study_path)
    require(study.get("catalyst_class") in {"metal_chiral_ligand", "metal_and_chiral_boron_cooperative"}, "study is not a transition-metal case")
    mechanisms = study.get("mechanism_hypotheses", [])
    require(isinstance(mechanisms, list) and mechanisms, "metal study has no mechanism hypotheses")
    states = []
    for state in study.get("catalyst_states", []):
        if not state.get("metal_centers"):
            continue
        state_mechanisms = sorted(
            item["mechanism_id"]
            for item in mechanisms
            if item.get("active_catalyst_state_id") == state.get("state_id")
        )
        centers = [
            {
                "atom_index": center["atom_index"],
                "element": center["element"],
                "formal_oxidation_state": center.get("oxidation_state"),
                "d_electron_count": None,
                "coordination_number": center.get("coordination_number"),
                "geometry": center.get("geometry"),
                "spin_hypothesis": center.get("spin_hypothesis"),
                "assignment_basis": center.get("assignment_basis", "No assignment basis supplied."),
                "review_status": "unreviewed_hypothesis",
            }
            for center in state["metal_centers"]
        ]
        states.append({
            "state_id": state["state_id"], "support_status": "unsupported_transition_metal", "submission_decision": "refused",
            "metal_centers": centers,
            "electron_accounting": {
                "status": "review_required",
                "declared": {
                    "total_charge": state.get("total_charge"),
                    "multiplicity": state.get("multiplicity"),
                    "formal_oxidation_states": [item["formal_oxidation_state"] for item in centers],
                    "d_electron_counts": [None for _ in centers],
                    "electron_parity_consistency": None,
                    "ligand_charge_conventions": [],
                    "non_innocent_ligand_alternatives": [],
                },
                "required_review": ["formal oxidation state per metal", "explicit ligand charge convention", "d-electron count per metal", "overall electron count and parity", "non-innocent ligand alternatives"],
                "blockers": ["d-electron counts and ligand charge conventions have not been reviewed", "electron parity has not been cross-checked against multiplicity"],
            },
            "spin_state_space": {
                "status": "review_required",
                "declared": {
                    "study_multiplicity": state.get("multiplicity"),
                    "credible_multiplicities": [],
                    "relative_energy_reference": None,
                    "spin_crossover_relevance": "unresolved",
                    "minimum_energy_crossing_relevance": "unresolved",
                },
                "required_review": ["enumerate every chemically credible multiplicity for each coordination state", "define common spin-state reference energies", "assess spin crossover and minimum-energy crossing points"],
                "blockers": ["the study multiplicity is a hypothesis, not an accepted spin-state space"],
            },
            "wavefunction": {
                "status": "unresolved",
                "declared": {
                    "reference_candidates": [],
                    "broken_symmetry": "unresolved",
                    "multireference_concern": "unresolved",
                    "stability_analysis": None,
                    "spin_contamination_threshold": None,
                },
                "required_review": ["restricted, unrestricted, RO, or broken-symmetry reference", "SCF stability evidence", "<S^2> and spin-contamination assessment", "alternative broken-symmetry solutions", "system-appropriate multireference diagnostics"],
                "blockers": ["no wavefunction reference or diagnostic policy is approved"],
            },
            "coordination": {
                "status": "review_required",
                "declared": {
                    "nuclearity": state.get("nuclearity"),
                    "center_coordination_numbers": [item["coordination_number"] for item in centers],
                    "center_geometries": [item["geometry"] for item in centers],
                    "ligand_and_binding_notes": state.get("ligand_and_binding_notes"),
                    "hapticity_assignments": [],
                    "counterion_models": [],
                    "solvent_additive_occupancy": [],
                    "agostic_or_secondary_contacts": [],
                },
                "required_review": ["coordination number and geometry", "ligand stoichiometry, denticity and hapticity", "labile and vacant sites", "counterion and ion-pair placement", "solvent/additive occupancy", "agostic and secondary contacts", "substrate binding face"],
                "blockers": ["explicit donor/acceptor coordination map and competing associated/dissociated states are absent"],
            },
            "method_protocol": {
                "status": "unresolved",
                "declared": {
                    "functional_or_method": None,
                    "basis_and_ecp": [],
                    "relativistic_treatment": None,
                    "dispersion": None,
                    "solvation": None,
                    "grid": None,
                    "scf_controls": None,
                    "spin_state_benchmark": None,
                },
                "required_review": ["three-tier protocol proposal", "basis/ECP coverage for every element", "relativistic treatment", "dispersion and solvation", "grid and SCF controls", "spin-state and wavefunction sensitivity"],
                "blockers": ["no transition-metal protocol may be inferred from the molecule or literature precedent"],
            },
            "ts_search_readiness": {
                "status": "blocked_offline_design_only",
                "mechanism_ids": state_mechanisms,
                "blocking_reasons": ["transition-metal input and execution support is not implemented", "electronic-state and coordination audits are incomplete", "no TS seed strategy has been scientifically selected"],
            },
            "known_hypotheses": state.get("metal_centers", []),
            "unresolved": ["No transition-metal execution backend is implemented.", "No route, Gaussian input, PBS plan, or submission artifact may be generated from this design."],
        })
    require(states, "no metal centers found")
    state_ids = {item["state_id"] for item in states}
    ts_search_families = []
    for mechanism in mechanisms:
        active_state = mechanism.get("active_catalyst_state_id")
        if active_state not in state_ids:
            continue
        mechanism_id = mechanism["mechanism_id"]
        strategies = [
            {
                "strategy_id": f"mts_{sha256_data([mechanism_id, 'single_guess'])[:12]}",
                "strategy": "single_guess_hessian_guided",
                "status": "design_candidate_not_selected",
                "prerequisites": ["reviewed TS-like geometry", "explicit reaction-coordinate atom map", "reviewed electronic and coordination state", "approved Hessian provenance"],
                "limitations": ["a plausible guess can converge to the wrong saddle or coordination state", "current transition-metal TS audit and execution support is absent"],
            },
            {
                "strategy_id": f"mts_{sha256_data([mechanism_id, 'qst'])[:12]}",
                "strategy": "endpoint_qst2_qst3",
                "status": "design_candidate_not_selected",
                "prerequisites": ["reviewed reactant and product structures on the same electronic surface", "identical atom order and explicit atom map", "verified installed-Gaussian syntax"],
                "limitations": ["QST endpoints do not resolve spin crossing or multireference surfaces", "raw multi-structure syntax must not be guessed"],
            },
            {
                "strategy_id": f"mts_{sha256_data([mechanism_id, 'scan'])[:12]}",
                "strategy": "reviewed_relaxed_coordinate_scan",
                "status": "design_candidate_not_selected",
                "prerequisites": ["explicit scan coordinates and direction", "reviewed constraints that preserve coordination and stereochemistry", "separate rule for promoting scan maxima to TS guesses"],
                "limitations": ["a one-dimensional scan can miss coupled coordinates and alternative surfaces", "the current workflow has no metal scan execution backend"],
            },
        ]
        ts_search_families.append({
            "mechanism_id": mechanism_id,
            "active_state_id": active_state,
            "channel_ids": sorted(mechanism.get("channel_ids", [])),
            "coordinate_changes": copy.deepcopy(mechanism.get("coordinate_changes", [])),
            "elementary_step_class": "unassigned_requires_review",
            "surface_model": {
                "status": "unresolved",
                "declared": {"single_surface_assumption": None, "included_multiplicities": [], "spin_crossing_model": None, "surface_hopping_or_mecp_required": "unresolved"},
                "required_review": ["assign the elementary-step class", "define the electronic surface for every endpoint and TS guess", "decide whether spin crossing or an MECP is mechanistically relevant"],
                "blockers": ["the TS cannot be searched until the state/surface relationship is reviewed"],
            },
            "seed_strategy_candidates": strategies,
            "required_pre_ts_evidence": ["reviewed atom map and intended forming/breaking/transferring coordinates", "reviewed oxidation, charge, multiplicity and wavefunction state", "reviewed coordination/hapticity and ligand/counterion inventory", "selected three-tier protocol candidate", "strategy-specific endpoint, Hessian, or scan evidence"],
            "blockers": ["no seed strategy is selected", "no transition-metal TS parser/input audit exists", "no execution handoff is authorized"],
        })
    require(ts_search_families, "no metal mechanism is bound to a reviewed metal state")
    design = {
        "schema": "gaussian-asymmetric-metal-support-design/1", "study_id": study["study_id"], "study_sha256": sha256_file(study_path),
        "calculation_ready": False, "no_submission_authorization": True, "runtime_support_status": "unsupported_requires_extension", "submission_decision": "refused",
        "scope": {
            "priority": "transition_metal_ts_design_first",
            "current_capability": "deterministic_offline_design_and_refusal_audit",
            "output_scope": "state_space_and_ts_search_plan_only",
            "execution_scope": "no_transition_metal_execution",
            "chiral_boron_priority": "deferred_until_after_transition_metal_design",
        },
        "states": states,
        "ts_search_families": ts_search_families,
        "cross_state_rules": ["Never compare or deduplicate candidates across oxidation, charge, multiplicity, nuclearity, coordination, hapticity, ligand-count, or wavefunction hypotheses.", "Never reuse a Hessian, checkpoint, endpoint, or TS guess across electronic states without a separately reviewed provenance map.", "Never mix spin surfaces in one Boltzmann ensemble; use a separately approved crossing/kinetic model when surfaces communicate.", "A normal mode must be reviewed for the intended chemical coordinate and for unintended ligand, counterion, or coordination loss."],
        "extension_milestones": [
            {"milestone_id": "metal_m0_offline_design", "status": "implemented_offline", "deliverable": "Deterministic state, audit, TS-seed-strategy, blocker, and refusal artifact."},
            {"milestone_id": "metal_m1_scientific_review", "status": "pending_scientific_review", "deliverable": "Reviewed oxidation/electron count, spin, wavefunction, coordination, method and TS strategy for a bounded example."},
            {"milestone_id": "metal_m2_offline_runtime_contract", "status": "blocked", "deliverable": "Metal-specific input audit, parser, wavefunction/coordination checks, negative fixtures and promotion gates."},
            {"milestone_id": "metal_m3_execution_boundary", "status": "blocked", "deliverable": "Separately reviewed execution-layer design that cannot bypass exact scientific and live approval."},
            {"milestone_id": "metal_m4_live_smoke", "status": "blocked", "deliverable": "Explicitly approved small closed-shell single-reference metal TS smoke only after M1-M3 pass."},
        ],
        "acceptance_gates": ["chemical-state and elementary-step inventory reviewed", "oxidation/electron-count assignments reviewed", "spin alternatives and surface model reviewed", "wavefunction diagnostics and rejection thresholds specified", "coordination, hapticity, ligand count and counterion alternatives reviewed", "method/basis/ECP/relativity benchmark protocol reviewed", "TS seed strategy and coordinate evidence reviewed", "offline parser, builder, negative and refusal fixtures passed", "separate execution-layer implementation reviewed"],
        "refusal_tests": ["candidate promotion remains forbidden", "calculation_ready remains false", "no Gaussian/PBS input builder is called", "no route or TS algorithm is inferred", "no default singlet, oxidation state, d-electron count, wavefunction or coordination state is accepted", "no cross-state deduplication or aggregation is permitted"],
    }
    design["design_payload_sha256"] = sha256_data({key: value for key, value in design.items() if key != "design_payload_sha256"})
    write_json(output, design)
    return design


def propose_smoke(ledger_path: Path, candidate_id: str, output: Path) -> dict[str, Any]:
    ledger = load_json(ledger_path)
    require(ledger.get("schema") == "gaussian-asymmetric-literature-benchmark-ledger/1", "smoke proposal requires a literature benchmark ledger")
    by_id = {item["candidate_id"]: item for item in ledger.get("candidates", [])}
    require(candidate_id in by_id, "smoke proposal candidate is absent from literature ledger")
    candidate = by_id[candidate_id]
    require(candidate.get("priority") == 1, "smoke proposal must select the priority-1 literature candidate")
    require(candidate.get("electronic_state", {}).get("proposed_multiplicity") == 1, "smoke proposal requires a singlet hypothesis")
    transition_metals = {"Sc", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn", "Y", "Zr", "Nb", "Mo", "Tc", "Ru", "Rh", "Pd", "Ag", "Cd", "Hf", "Ta", "W", "Re", "Os", "Ir", "Pt", "Au", "Hg"}
    require(not transition_metals.intersection(candidate["atom_inventory"]["element_counts"]), "smoke proposal refuses transition metals")
    proposal = {
        "schema": "gaussian-asymmetric-smoke-proposal/1", "proposal_id": "wang2024_bf3_ts1_offline_v1",
        "status": "planned_not_submitted", "calculation_ready": False, "no_submission_authorization": True,
        "purpose": "First closed-shell main-group literature TS test: reproduce and manually review the BF3-TS1 proton-transfer saddle before considering BF3-TS2-B1/B2.",
        "chemical_system": {
            "candidate_id": candidate_id, "literature_label": candidate["literature_label"], "formula": candidate["atom_inventory"]["formula"],
            "atom_count": candidate["atom_inventory"]["atom_count"], "main_group_only": True, "closed_shell_status": "neutral-singlet hypothesis requires explicit approval",
            "proposed_charge": candidate["electronic_state"]["proposed_charge"], "proposed_multiplicity": candidate["electronic_state"]["proposed_multiplicity"],
            "coordinate_artifact": candidate["geometry"]["artifact"], "canonical_coordinate_block_sha256": candidate["geometry"]["canonical_coordinate_block_sha256"],
            "literature_ledger": {"path": str(ledger_path), "sha256": sha256_file(ledger_path)},
        },
        "proposed_gaussian": {
            "status": "not_rendered_pending_scientific_approval", "reported_literature_protocol": ledger["reported_protocol"],
            "route": None, "solvent_identity": None, "resource_tier": None, "input_text": None, "input_sha256": None,
            "reason": "The SI does not provide all route, solvent, charge/multiplicity, standard-state, and low-frequency metadata needed for an exact approved input.",
        },
        "server_plan": {"status": "not_created", "allowed_root": "/home/user100/SDL", "fresh_project": None, "overwrite": False},
        "required_pre_submission_review": [
            "confirm the 57-atom coordinate artifact and atom order", "explicitly approve charge 0 and multiplicity 1", "approve the exact TS/Freq route and SMD solvent identity",
            "approve temperature, standard state, low-frequency policy, resources, checkpoint, and fresh project", "review the fully rendered input and its SHA-256", "explicitly approve the exact job"
        ],
        "acceptance_evidence": [
            "normal termination and stationary-point evidence", "complete frequency parse with exactly one raw imaginary mode",
            "hash-bound manual review that H14 moves along C13-H14-N23", "comparison with the reported featured imaginary frequency of -1455.35 cm-1 without requiring numerical identity"
        ],
        "non_claims": [
            "No Gaussian input, server directory, PBS job, or IRC is authorized by this artifact.",
            "The literature reports an IRC method generally but not candidate-specific endpoint identities; path validation remains absent.",
            "BF3-TS1 is a workflow and mechanism-submodel benchmark, not an ee or full-BCF validation.",
            "A successful smoke test does not authorize BF3-TS2-B1/B2, full BCF, or transition-metal submission."
        ],
    }
    proposal["proposal_payload_sha256"] = sha256_data({key: value for key, value in proposal.items() if key != "proposal_payload_sha256"})
    write_json(output, proposal)
    return proposal


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    sub = root.add_subparsers(dest="command", required=True)
    study = sub.add_parser("build-study"); study.add_argument("source"); study.add_argument("--output", required=True)
    enum = sub.add_parser("enumerate-boron"); enum.add_argument("study"); enum.add_argument("space"); enum.add_argument("--output", required=True)
    literature = sub.add_parser("build-literature-benchmark"); literature.add_argument("source"); literature.add_argument("--output", required=True)
    materialize = sub.add_parser("build-candidates"); materialize.add_argument("study"); materialize.add_argument("ledger"); materialize.add_argument("materializations"); materialize.add_argument("--output-dir", required=True)
    ingest = sub.add_parser("ingest-result"); ingest.add_argument("candidate"); ingest.add_argument("ts_result"); ingest.add_argument("energy_record"); ingest.add_argument("--mode-review"); ingest.add_argument("--mode-decision"); ingest.add_argument("--forward-audit"); ingest.add_argument("--reverse-audit"); ingest.add_argument("--input"); ingest.add_argument("--log"); ingest.add_argument("--checkpoint"); ingest.add_argument("--checkpoint-audit"); ingest.add_argument("--irc-plan"); ingest.add_argument("--output", required=True)
    agg = sub.add_parser("aggregate"); agg.add_argument("study"); agg.add_argument("ledger"); agg.add_argument("results", nargs="+"); agg.add_argument("--energy-shift-kcal", type=float, default=1.0); agg.add_argument("--output", required=True)
    metal = sub.add_parser("design-metal-support"); metal.add_argument("study"); metal.add_argument("--output", required=True)
    smoke = sub.add_parser("propose-smoke"); smoke.add_argument("ledger"); smoke.add_argument("--candidate-id", required=True); smoke.add_argument("--output", required=True)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "build-study": build_study(Path(args.source), Path(args.output))
        elif args.command == "enumerate-boron": enumerate_boron(Path(args.study), Path(args.space), Path(args.output))
        elif args.command == "build-literature-benchmark": build_literature_benchmark(Path(args.source), Path(args.output))
        elif args.command == "build-candidates": materialize_candidates(Path(args.study), Path(args.ledger), Path(args.materializations), Path(args.output_dir))
        elif args.command == "ingest-result": ingest_result(Path(args.candidate), Path(args.ts_result), Path(args.energy_record), Path(args.output), Path(args.mode_review) if args.mode_review else None, Path(args.mode_decision) if args.mode_decision else None, Path(args.forward_audit) if args.forward_audit else None, Path(args.reverse_audit) if args.reverse_audit else None, Path(args.input) if args.input else None, Path(args.log) if args.log else None, Path(args.checkpoint) if args.checkpoint else None, Path(args.checkpoint_audit) if args.checkpoint_audit else None, Path(args.irc_plan) if args.irc_plan else None)
        elif args.command == "aggregate": aggregate(Path(args.study), Path(args.ledger), [Path(item) for item in args.results], Path(args.output), args.energy_shift_kcal)
        elif args.command == "design-metal-support": design_metal_support(Path(args.study), Path(args.output))
        elif args.command == "propose-smoke": propose_smoke(Path(args.ledger), args.candidate_id, Path(args.output))
        else: raise AssertionError(args.command)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
