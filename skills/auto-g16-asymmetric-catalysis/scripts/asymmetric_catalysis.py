#!/usr/bin/env python3
"""Deterministic, offline builders for asymmetric-catalysis evidence.

This module uses only the Python standard library.  It never invokes Gaussian,
SSH, PBS, qdel, deployment, or any subprocess.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import itertools
import json
import math
import re
import sys
from datetime import date
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
METAL_REVIEW_SECTION_NAMES = (
    "electron_accounting",
    "spin_surface",
    "wavefunction",
    "coordination",
    "method_protocol",
    "ts_and_path",
)
METAL_ACCEPTANCE_SECTION_NAMES = (
    "wavefunction",
    "coordination",
    "mode",
    "input_acceptance",
)
METAL_ACCEPTANCE_DECISIONS = {
    "accepted_for_bounded_offline_review",
    "rejected_by_reviewer",
    "blocked_missing_evidence",
}
METAL_SEED_STRATEGIES = {
    "single_guess_hessian_guided",
    "endpoint_qst2_qst3",
    "reviewed_relaxed_coordinate_scan",
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


def _is_valid_iso_date(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def _validate_m1_scope_evidence_binding(provenance: dict[str, Any], label: str) -> None:
    """Prevent a synthetic or reviewer record from being relabelled as primary evidence."""
    scope_kind = provenance.get("scope_kind")
    sources = provenance.get("sources", [])
    source_types = {
        item.get("source_type") for item in sources if isinstance(item, dict)
    }
    primary_types = {"primary_article", "primary_supporting_information"}
    if scope_kind == "synthetic_nonresearch_fixture":
        require(
            source_types == {"synthetic_fixture"},
            f"{label}: synthetic scope requires only synthetic_fixture evidence",
        )
    elif scope_kind == "primary_literature_bound_review":
        require(
            bool(source_types) and source_types <= primary_types,
            f"{label}: primary-literature scope requires only primary article or supporting-information evidence",
        )
    elif scope_kind == "mixed_primary_and_reviewer_evidence":
        require(
            bool(source_types)
            and source_types <= primary_types | {"reviewer_record"}
            and bool(source_types & primary_types)
            and "reviewer_record" in source_types,
            f"{label}: mixed scope requires both primary-literature and reviewer-record evidence and forbids synthetic fixtures",
        )


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
    require(audit.get("schema") == "gaussian-checkpoint-geometry-audit/2" and audit.get("audit_status") == "passed", "new path validation requires owner-replayed checkpoint-geometry audit /2; /1 is historical only")
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
    path_acceptance_path: Path | None = None,
) -> dict[str, Any]:
    supplied_paths = {
        "candidate": candidate_path, "TS result": ts_result_path, "energy record": energy_path,
        "mode review": mode_review_path, "mode decision": mode_decision_path,
        "forward endpoint audit": forward_path, "reverse endpoint audit": reverse_path,
        "TS input": input_path, "TS log": log_path, "TS checkpoint": checkpoint_path,
        "checkpoint audit": checkpoint_audit_path, "IRC plan": irc_plan_path,
        "path acceptance": path_acceptance_path,
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
    require(ts.get("schema") in {"gaussian-ts-freq-result/1", "gaussian-ts-freq-result/2"}, "unrecognized TS result schema")
    ts_owner = None
    if ts.get("schema") == "gaussian-ts-freq-result/2":
        owner_path = Path(__file__).resolve().parents[2] / "auto-g16-ts-irc" / "scripts" / "ts_irc.py"
        spec = importlib.util.spec_from_file_location("auto_g16_asymmetric_ts_result_owner", owner_path)
        require(spec is not None and spec.loader is not None, "TS/Freq result /2 owner validator is unavailable")
        owner = importlib.util.module_from_spec(spec); spec.loader.exec_module(owner)
        ts_owner = owner
        try:
            owner.require_accepted_ts_result_v2(ts, ts_result_path)
        except (OSError, ValueError) as exc:
            raise OfflineError(f"TS/Freq result /2 owner validator rejected the evidence: {exc}") from exc
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
        raise OfflineError("historical endpoint-audit /1 evidence is replay-only and cannot open path_validated or comparison eligibility")
    if path_acceptance_path is not None:
        require(mode_reviewed, "path-acceptance ingestion requires an accepted hash-bound mode decision")
        if ts_owner is None:
            owner_path = Path(__file__).resolve().parents[2] / "auto-g16-ts-irc" / "scripts" / "ts_irc.py"
            spec = importlib.util.spec_from_file_location("auto_g16_asymmetric_path_owner", owner_path)
            require(spec is not None and spec.loader is not None, "path-acceptance /2 owner validator is unavailable")
            ts_owner = importlib.util.module_from_spec(spec); spec.loader.exec_module(ts_owner)
        try:
            acceptance = ts_owner.validate_path_acceptance_v2_artifact(path_acceptance_path)
        except (OSError, ValueError) as exc:
            raise OfflineError(f"path-acceptance /2 owner validator rejected the evidence: {exc}") from exc
        require(acceptance.get("schema") == "gaussian-ts-irc-path-acceptance/2", "new asymmetric path qualification requires path acceptance /2")
        require(acceptance.get("mechanism_binding", {}).get("study_id") == candidate.get("study_id"), "path acceptance belongs to another study")
        bound_result = ts_owner._closure_resolve_local_ref(acceptance["ts_result"], path_acceptance_path, "asymmetric TS result")
        require(bound_result.resolve() == ts_result_path.resolve(), "path acceptance does not bind the exact asymmetric TS result")
        path_forward = path_reverse = "completed_and_identified"
        endpoint_reviewed = True
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
            "path_acceptance": _nullable_artifact(path_acceptance_path),
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
        "mode_evidence": {"decision": mode_decision, "coordinate_projection_reviewed": mode_reviewed, "review_notes": "Hash-bound auto-g16-ts-irc mode decision." if mode_reviewed else "Mode acceptance is absent or incomplete."},
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
                "limitations": ["a plausible guess can converge to the wrong saddle or coordination state", "the observation-only parser cannot accept a metal TS and execution support is absent"],
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
            "blockers": ["no seed strategy is selected", "no transition-metal TS acceptance parser or reviewed input-acceptance contract exists", "no execution handoff is authorized"],
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
            {"milestone_id": "metal_m1_review_contract", "status": "implemented_offline", "deliverable": "Candidate-bound sidecar builder and validator for explicit bounded scientific-review records; it never grants scientific acceptance, promotion, input rendering or execution."},
            {"milestone_id": "metal_m1_scientific_review", "status": "pending_scientific_review", "deliverable": "Reviewed oxidation/electron count, spin, wavefunction, coordination, method and TS strategy for a bounded example."},
            {"milestone_id": "metal_m2a_candidate_audit_template", "status": "implemented_offline", "deliverable": "Candidate-bound atom-order, metal-center, coordination-contact, electronic-state, method, TS/path and seed-strategy audit template with unconditional execution refusal."},
            {"milestone_id": "metal_m2b_result_observation", "status": "implemented_offline", "deliverable": "Candidate-bound, read-only log observation parser for identity, termination, frequency, S**2/stability text and coordination distances; all scientific audits and promotion remain blocked."},
            {"milestone_id": "metal_m2c_input_observation", "status": "implemented_offline", "deliverable": "Candidate- and M1-bound read-only observation of an existing single-step Cartesian Gaussian input; no input acceptance, protocol selection, rendering or execution authority."},
            {"milestone_id": "metal_m2d_acceptance_review_contract", "status": "implemented_offline", "deliverable": "Candidate-bound reviewer sidecar for wavefunction, coordination, mode and input decisions; section-level records never grant promotion, submission or execution authority."},
            {"milestone_id": "metal_m2_offline_runtime_contract", "status": "blocked", "deliverable": "Metal-specific input acceptance, result acceptance, reviewed wavefunction/coordination checks and promotion gates beyond the observation-only M2b/M2c artifacts."},
            {"milestone_id": "metal_m3_execution_boundary", "status": "blocked", "deliverable": "Separately reviewed execution-layer design that cannot bypass exact scientific and live approval."},
            {"milestone_id": "metal_m4_live_smoke", "status": "blocked", "deliverable": "Explicitly approved small closed-shell single-reference metal TS smoke only after M1-M3 pass."},
        ],
        "acceptance_gates": ["chemical-state and elementary-step inventory reviewed", "oxidation/electron-count assignments reviewed", "spin alternatives and surface model reviewed", "wavefunction diagnostics and rejection thresholds specified", "coordination, hapticity, ligand count and counterion alternatives reviewed", "method/basis/ECP/relativity benchmark protocol reviewed", "TS seed strategy and coordinate evidence reviewed", "offline parser, builder, negative and refusal fixtures passed", "separate execution-layer implementation reviewed"],
        "refusal_tests": ["candidate promotion remains forbidden", "calculation_ready remains false", "no Gaussian/PBS input builder is called", "no route or TS algorithm is inferred", "no default singlet, oxidation state, d-electron count, wavefunction or coordination state is accepted", "no cross-state deduplication or aggregation is permitted"],
    }
    design["design_payload_sha256"] = sha256_data({key: value for key, value in design.items() if key != "design_payload_sha256"})
    write_json(output, design)
    return design


def _validate_metal_scientific_review_source(
    source: dict[str, Any],
    design: dict[str, Any],
    template: dict[str, Any],
    candidate: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], bool]:
    """Validate explicit M1 evidence without deriving a scientific assignment."""
    required_top = {
        "schema", "review_id", "design_payload_sha256",
        "template_payload_sha256", "candidate_sha256", "study_id",
        "candidate_id", "channel_id", "catalyst_state_id", "mechanism_id",
        "provenance", "identity", "sections",
    }
    require(set(source) == required_top, "metal scientific-review source fields are incomplete or unknown")
    require(
        source.get("schema") == "gaussian-asymmetric-metal-scientific-review-source/1",
        "metal scientific-review source schema is not recognized",
    )
    require(ID_RE.fullmatch(str(source.get("review_id", ""))) is not None, "invalid metal scientific-review review_id")
    require(
        source.get("design_payload_sha256") == design.get("design_payload_sha256"),
        "metal scientific-review source is not bound to the exact design payload",
    )
    require(
        source.get("template_payload_sha256") == template.get("template_payload_sha256"),
        "metal scientific-review source is not bound to the exact audit-template payload",
    )
    require(source.get("study_id") == design.get("study_id"), "metal scientific-review study binding differs")
    require(source.get("candidate_id") == candidate.get("candidate_id"), "metal scientific-review candidate binding differs")
    require(source.get("channel_id") == candidate.get("channel_id"), "metal scientific-review channel binding differs")

    states = {item["state_id"]: item for item in design.get("states", [])}
    state_id = source.get("catalyst_state_id")
    require(state_id in states, "metal scientific-review source references an unknown catalyst state")
    state = states[state_id]
    families = {item["mechanism_id"]: item for item in design.get("ts_search_families", [])}
    mechanism_id = source.get("mechanism_id")
    require(mechanism_id in families, "metal scientific-review source references an unknown mechanism")
    family = families[mechanism_id]
    require(family.get("active_state_id") == state_id, "metal scientific-review mechanism/state binding differs")
    for key in ("study_id", "candidate_id", "mechanism_id", "channel_id", "catalyst_state_id"):
        require(source.get(key) == template.get(key), f"metal scientific-review template {key} binding differs")
        require(source.get(key) == candidate.get(key), f"metal scientific-review candidate {key} binding differs")
    require(
        template.get("design_source", {}).get("sha256") is not None
        and template.get("candidate_source", {}).get("sha256") is not None,
        "metal scientific-review template lacks immutable source bindings",
    )

    provenance = source.get("provenance")
    require(isinstance(provenance, dict), "metal scientific-review provenance must be an object")
    require(
        set(provenance) == {"scope_kind", "reviewer", "review_date", "sources", "notes"},
        "metal scientific-review provenance fields are incomplete or unknown",
    )
    require(
        provenance.get("scope_kind") in {
            "synthetic_nonresearch_fixture",
            "primary_literature_bound_review",
            "mixed_primary_and_reviewer_evidence",
        },
        "metal scientific-review scope_kind is invalid",
    )
    require(isinstance(provenance.get("notes"), list), "metal scientific-review provenance notes must be an array")
    evidence_by_id: dict[str, dict[str, Any]] = {}
    for evidence in provenance.get("sources", []):
        require(isinstance(evidence, dict), "metal scientific-review evidence record must be an object")
        require(
            set(evidence) == {"source_id", "source_type", "citation", "doi", "url", "locator", "supports"},
            "metal scientific-review evidence fields are incomplete or unknown",
        )
        source_id = evidence.get("source_id")
        require(ID_RE.fullmatch(str(source_id or "")) is not None, "metal scientific-review evidence source_id is invalid")
        require(source_id not in evidence_by_id, f"duplicate metal scientific-review evidence source_id: {source_id}")
        require(
            evidence.get("source_type") in {
                "primary_article", "primary_supporting_information",
                "reviewer_record", "synthetic_fixture",
            },
            f"metal scientific-review evidence {source_id} has an invalid source_type",
        )
        require(isinstance(evidence.get("citation"), str) and evidence["citation"].strip(), f"metal scientific-review evidence {source_id} lacks a citation")
        require(isinstance(evidence.get("locator"), str) and evidence["locator"].strip(), f"metal scientific-review evidence {source_id} lacks a locator")
        url = evidence.get("url")
        require(url is None or (isinstance(url, str) and re.fullmatch(r"https?://\S+", url)), f"metal scientific-review evidence {source_id} has an invalid URL")
        doi = evidence.get("doi")
        require(doi is None or (isinstance(doi, str) and doi.strip()), f"metal scientific-review evidence {source_id} has an invalid DOI")
        supports = evidence.get("supports")
        require(
            isinstance(supports, list) and supports
            and set(supports) <= set(METAL_REVIEW_SECTION_NAMES),
            f"metal scientific-review evidence {source_id} has invalid section support",
        )
        evidence_by_id[source_id] = evidence
    require(evidence_by_id, "metal scientific-review source has no evidence records")
    _validate_m1_scope_evidence_binding(provenance, "metal scientific-review source")

    identity = source.get("identity")
    require(isinstance(identity, dict), "metal scientific-review identity must be an object")
    require(
        set(identity) == {"total_charge", "multiplicity", "metal_centers"},
        "metal scientific-review identity fields are incomplete or unknown",
    )
    declared_identity = state.get("electron_accounting", {}).get("declared", {})
    require(identity.get("total_charge") == declared_identity.get("total_charge"), "metal scientific-review total charge differs from the design state")
    require(identity.get("multiplicity") == declared_identity.get("multiplicity"), "metal scientific-review multiplicity differs from the design state")
    require(identity.get("total_charge") == template.get("identity_binding", {}).get("charge") == candidate.get("chemical_state", {}).get("charge"), "metal scientific-review total charge differs from the candidate/template")
    require(identity.get("multiplicity") == template.get("identity_binding", {}).get("multiplicity") == candidate.get("chemical_state", {}).get("multiplicity"), "metal scientific-review multiplicity differs from the candidate/template")
    expected_centers = [
        {"atom_index": item.get("atom_index"), "element": item.get("element")}
        for item in template.get("identity_binding", {}).get("metal_centers", [])
    ]
    require(identity.get("metal_centers") == expected_centers, "metal scientific-review metal-center identity differs from the design state")

    sections = source.get("sections")
    require(isinstance(sections, dict) and set(sections) == set(METAL_REVIEW_SECTION_NAMES), "metal scientific-review section inventory is incomplete")
    fact_fields = {
        "electron_accounting": {
            "metal_assignments", "total_valence_electron_count", "electron_parity",
            "parity_multiplicity_assessment", "ligand_charge_conventions",
            "metal_metal_bonding_convention", "non_innocent_ligand_alternatives",
        },
        "spin_surface": {
            "credible_multiplicities", "selected_multiplicity", "relative_energy_reference",
            "spin_crossover_relevance", "minimum_energy_crossing_relevance",
            "single_surface_assumption",
        },
        "wavefunction": {
            "reference_hypothesis", "scf_stability_policy", "expected_s2",
            "spin_contamination_policy", "occupation_inspection_policy",
            "alternative_solution_policy", "multireference_diagnostic_policy",
            "checkpoint_reuse_policy",
        },
        "coordination": {
            "nuclearity", "metal_center_models", "ligand_inventory",
            "denticity_hapticity_assignments", "coordination_contacts",
            "counterion_models", "solvent_additive_occupancy",
            "alternative_associated_dissociated_states",
        },
        "method_protocol": {
            "applicability", "method_or_functional", "dispersion", "basis_and_ecp",
            "relativistic_treatment", "solvation", "grid", "scf_controls",
            "geometry_frequency_relationship", "spin_wavefunction_sensitivity",
            "thermochemistry_policy", "three_tier_protocol_binding",
            "protocol_selection_authorization",
        },
        "ts_and_path": {
            "elementary_step_class", "reactant_state_id", "product_state_id",
            "coordinate_changes", "single_surface_assumption",
            "literature_search_strategy", "reviewed_strategy_candidate_id",
            "reviewed_strategy_candidate", "strategy_specific_evidence",
            "execution_selection_status", "path_model",
            "frequency_and_mode_acceptance_policy", "mode_path_evidence_status",
        },
    }
    for section_name in METAL_REVIEW_SECTION_NAMES:
        section = sections[section_name]
        require(isinstance(section, dict), f"metal scientific-review {section_name} section must be an object")
        require(
            set(section) == {"status", "facts", "evidence_ids", "review_notes", "blockers"},
            f"metal scientific-review {section_name} fields are incomplete or unknown",
        )
        status = section.get("status")
        require(status in {"reviewed_for_bounded_example", "blocked_missing_evidence"}, f"metal scientific-review {section_name} has an invalid status")
        facts = section.get("facts")
        require(isinstance(facts, dict) and set(facts) == fact_fields[section_name], f"metal scientific-review {section_name} fact fields are incomplete or unknown")
        evidence_ids = section.get("evidence_ids")
        require(isinstance(evidence_ids, list) and len(evidence_ids) == len(set(evidence_ids)), f"metal scientific-review {section_name} evidence IDs are invalid")
        for evidence_id in evidence_ids:
            require(evidence_id in evidence_by_id, f"metal scientific-review {section_name} references unknown evidence {evidence_id}")
            require(section_name in evidence_by_id[evidence_id]["supports"], f"metal scientific-review evidence {evidence_id} does not support {section_name}")
        blockers = section.get("blockers")
        require(isinstance(blockers, list), f"metal scientific-review {section_name} blockers must be an array")
        require(isinstance(section.get("review_notes"), str) and section["review_notes"].strip(), f"metal scientific-review {section_name} lacks review notes")
        if status == "reviewed_for_bounded_example":
            require(evidence_ids, f"metal scientific-review {section_name} cannot be reviewed without evidence")
            require(not blockers, f"metal scientific-review {section_name} cannot be reviewed while blockers remain")
        else:
            require(blockers, f"metal scientific-review {section_name} blocked status lacks blockers")

    electron = sections["electron_accounting"]
    electron_facts = electron["facts"]
    assignments = electron_facts["metal_assignments"]
    require(isinstance(assignments, list), "metal scientific-review electron assignments must be an array")
    assignment_identity = [
        {"atom_index": item.get("atom_index"), "element": item.get("element")}
        for item in assignments if isinstance(item, dict)
    ]
    require(assignment_identity == expected_centers, "metal scientific-review electron assignments differ from the design centers")
    for assignment, center in zip(assignments, state.get("metal_centers", []), strict=True):
        require(
            set(assignment) == {"atom_index", "element", "formal_oxidation_state", "d_electron_count", "assignment_basis"},
            "metal scientific-review metal assignment fields are incomplete or unknown",
        )
        oxidation_state = assignment.get("formal_oxidation_state")
        require(
            oxidation_state is None or oxidation_state == center.get("formal_oxidation_state"),
            "metal scientific-review oxidation-state assignment differs from the bound design state",
        )
    if electron["status"] == "reviewed_for_bounded_example":
        require(all(isinstance(item.get("formal_oxidation_state"), int) and isinstance(item.get("d_electron_count"), int) and item["d_electron_count"] >= 0 and isinstance(item.get("assignment_basis"), str) and item["assignment_basis"].strip() for item in assignments), "reviewed electron accounting requires explicit oxidation states, d counts and assignment bases")
        total_electrons = electron_facts.get("total_valence_electron_count")
        require(isinstance(total_electrons, int) and not isinstance(total_electrons, bool) and total_electrons >= 0, "reviewed electron accounting requires a total valence-electron count")
        expected_parity = "even" if total_electrons % 2 == 0 else "odd"
        require(electron_facts.get("electron_parity") == expected_parity, "metal scientific-review electron parity differs from the explicit count")
        multiplicity = identity.get("multiplicity")
        require(isinstance(multiplicity, int) and multiplicity >= 1, "reviewed electron accounting requires an explicit multiplicity")
        require((total_electrons % 2 == 0) == (multiplicity % 2 == 1), "metal scientific-review electron parity and multiplicity parity are inconsistent")
        require(electron_facts.get("parity_multiplicity_assessment") == "consistent", "reviewed electron accounting must record a consistent parity assessment")
        require(electron_facts.get("ligand_charge_conventions"), "reviewed electron accounting lacks ligand-charge conventions")
        require(electron_facts.get("non_innocent_ligand_alternatives"), "reviewed electron accounting must explicitly address non-innocent alternatives")

    spin = sections["spin_surface"]
    spin_facts = spin["facts"]
    if spin["status"] == "reviewed_for_bounded_example":
        credible = spin_facts.get("credible_multiplicities")
        selected = spin_facts.get("selected_multiplicity")
        require(isinstance(credible, list) and credible and all(isinstance(value, int) and value >= 1 for value in credible), "reviewed spin space requires explicit credible multiplicities")
        require(selected == identity.get("multiplicity") and selected in credible, "reviewed spin-space selection differs from the bound identity")
        require(isinstance(spin_facts.get("relative_energy_reference"), str) and spin_facts["relative_energy_reference"].strip(), "reviewed spin space lacks a common reference")
        for field in ("spin_crossover_relevance", "minimum_energy_crossing_relevance"):
            require(spin_facts.get(field) in {"not_indicated", "relevant_requires_extension"}, f"reviewed spin space leaves {field} unresolved")
        require(isinstance(spin_facts.get("single_surface_assumption"), bool), "reviewed spin space lacks an explicit single-surface decision")

    wavefunction = sections["wavefunction"]
    wavefunction_facts = wavefunction["facts"]
    if wavefunction["status"] == "reviewed_for_bounded_example":
        require(wavefunction_facts.get("reference_hypothesis") in {"restricted", "unrestricted", "restricted_open_shell", "broken_symmetry"}, "reviewed wavefunction lacks an explicit reference hypothesis")
        multiplicity = identity["multiplicity"]
        expected_s2 = ((multiplicity - 1) / 2.0) * ((multiplicity - 1) / 2.0 + 1.0)
        require(_is_finite_number(wavefunction_facts.get("expected_s2")) and math.isclose(float(wavefunction_facts["expected_s2"]), expected_s2, rel_tol=0.0, abs_tol=1e-8), "reviewed wavefunction expected S**2 differs from the bound multiplicity")
        for field in (
            "scf_stability_policy", "spin_contamination_policy", "occupation_inspection_policy",
            "alternative_solution_policy", "multireference_diagnostic_policy", "checkpoint_reuse_policy",
        ):
            require(isinstance(wavefunction_facts.get(field), str) and wavefunction_facts[field].strip(), f"reviewed wavefunction lacks {field}")

    coordination = sections["coordination"]
    coordination_facts = coordination["facts"]
    require(coordination_facts.get("nuclearity") == state.get("coordination", {}).get("declared", {}).get("nuclearity"), "metal scientific-review nuclearity differs from the design state")
    center_models = coordination_facts.get("metal_center_models")
    require(isinstance(center_models, list), "metal scientific-review coordination center models must be an array")
    require(
        [{"atom_index": item.get("atom_index"), "element": item.get("element")} for item in center_models if isinstance(item, dict)] == expected_centers,
        "metal scientific-review coordination center models differ from the design centers",
    )
    for model in center_models:
        require(set(model) == {"atom_index", "element", "coordination_number", "geometry"}, "metal scientific-review coordination center-model fields are incomplete or unknown")
    contacts = coordination_facts.get("coordination_contacts")
    require(isinstance(contacts, list), "metal scientific-review coordination contacts must be an array")
    for contact in contacts:
        require(isinstance(contact, dict) and set(contact) == {"donor_atom", "acceptor_atom", "kind", "distance_window_angstrom"}, "metal scientific-review coordination-contact fields are incomplete or unknown")
        require(contact.get("acceptor_atom") in {item["atom_index"] for item in expected_centers}, "metal scientific-review coordination contact is not bound to a reviewed metal center")
        window = contact.get("distance_window_angstrom")
        require(window is None or (isinstance(window, list) and len(window) == 2 and all(_is_finite_number(value) and float(value) >= 0 for value in window) and float(window[0]) <= float(window[1])), "metal scientific-review coordination distance window is invalid")
    expected_contact_inventory = {
        (item.get("donor_atom"), item.get("acceptor_atom"), item.get("kind"))
        for item in template.get("identity_binding", {}).get("coordination_contacts", [])
    }
    actual_contact_inventory = {
        (item.get("donor_atom"), item.get("acceptor_atom"), item.get("kind"))
        for item in contacts
    }
    require(actual_contact_inventory == expected_contact_inventory, "metal scientific-review coordination contacts differ from the candidate/template")
    if coordination["status"] == "reviewed_for_bounded_example":
        require(all(isinstance(item.get("coordination_number"), int) and item["coordination_number"] >= 0 and isinstance(item.get("geometry"), str) and item["geometry"].strip() for item in center_models), "reviewed coordination requires coordination numbers and geometries")
        require(contacts and all(item.get("distance_window_angstrom") is not None for item in contacts), "reviewed coordination requires explicit contact windows")
        for field in (
            "ligand_inventory", "denticity_hapticity_assignments", "counterion_models",
            "solvent_additive_occupancy", "alternative_associated_dissociated_states",
        ):
            require(isinstance(coordination_facts.get(field), list) and coordination_facts[field], f"reviewed coordination must explicitly address {field}")

    method = sections["method_protocol"]
    method_facts = method["facts"]
    require(method_facts.get("protocol_selection_authorization") is False, "metal scientific-review method record must not authorize protocol selection")
    if method["status"] == "reviewed_for_bounded_example":
        require(method_facts.get("applicability") in {"exact_literature_example_only", "reviewer_proposal_not_execution_approved", "synthetic_fixture_only"}, "reviewed method record lacks a bounded applicability")
        for field in (
            "method_or_functional", "dispersion", "relativistic_treatment", "solvation", "grid",
            "scf_controls", "geometry_frequency_relationship", "spin_wavefunction_sensitivity",
            "thermochemistry_policy",
        ):
            require(isinstance(method_facts.get(field), str) and method_facts[field].strip(), f"reviewed method record lacks {field}")
        basis = method_facts.get("basis_and_ecp")
        require(isinstance(basis, list) and basis, "reviewed method record lacks basis/ECP coverage")
        for assignment in basis:
            require(isinstance(assignment, dict) and set(assignment) == {"element_scope", "orbital_basis", "ecp", "ecp_core_electrons", "coverage_status"}, "metal scientific-review basis/ECP fields are incomplete or unknown")
            require(assignment.get("coverage_status") == "explicit" and isinstance(assignment.get("element_scope"), str) and assignment["element_scope"].strip() and isinstance(assignment.get("orbital_basis"), str) and assignment["orbital_basis"].strip(), "reviewed method record contains unresolved basis/ECP coverage")

    ts_and_path = sections["ts_and_path"]
    ts_facts = ts_and_path["facts"]
    require(ts_facts.get("coordinate_changes") == template.get("identity_binding", {}).get("coordinate_changes") == candidate.get("coordinate_changes"), "metal scientific-review intended coordinate differs from the candidate/template")
    normalized_review_coordinates = [
        (item.get("kind"), tuple(item.get("atoms", [])))
        for item in ts_facts.get("coordinate_changes", [])
    ]
    normalized_design_coordinates = [
        (item.get("kind"), tuple(item.get("atoms", [])))
        for item in family.get("coordinate_changes", [])
    ]
    require(normalized_review_coordinates == normalized_design_coordinates, "metal scientific-review intended coordinate atom map differs from the design family")
    inventory = {
        item.get("strategy_id"): item.get("strategy")
        for item in family.get("seed_strategy_candidates", [])
    }
    require(set(inventory.values()) == METAL_SEED_STRATEGIES, "metal scientific-review design lacks the complete strategy inventory")
    selected_strategy_id = ts_facts.get("reviewed_strategy_candidate_id")
    selected_strategy = ts_facts.get("reviewed_strategy_candidate")
    require(
        selected_strategy_id is None or inventory.get(selected_strategy_id) == selected_strategy,
        "metal scientific-review reviewed seed-strategy candidate differs from the design inventory",
    )
    require(ts_facts.get("execution_selection_status") == "not_selected", "metal scientific-review must not select an execution strategy")
    require(ts_facts.get("mode_path_evidence_status") == "not_applicable_no_result", "metal scientific-review must not claim result-level mode/path evidence")
    if ts_and_path["status"] == "reviewed_for_bounded_example":
        for field in ("elementary_step_class", "reactant_state_id", "product_state_id", "frequency_and_mode_acceptance_policy"):
            require(isinstance(ts_facts.get(field), str) and ts_facts[field].strip(), f"reviewed TS strategy lacks {field}")
        require(selected_strategy_id in inventory and selected_strategy in METAL_SEED_STRATEGIES, "reviewed TS design lacks an explicit strategy candidate")
        require(isinstance(ts_facts.get("strategy_specific_evidence"), list) and ts_facts["strategy_specific_evidence"], "reviewed TS strategy lacks strategy-specific evidence")
        require(ts_facts.get("single_surface_assumption") is True, "current reviewed TS strategy requires an explicit single-surface assumption")
        require(spin_facts.get("single_surface_assumption") is True and spin_facts.get("spin_crossover_relevance") == "not_indicated" and spin_facts.get("minimum_energy_crossing_relevance") == "not_indicated", "current reviewed TS strategies cannot represent a crossing surface")
        require(ts_facts.get("path_model") == "single_surface_candidate_no_connectivity_claim", "reviewed current TS strategy must retain the no-connectivity-claim path model")

    all_reviewed = all(
        sections[name]["status"] == "reviewed_for_bounded_example"
        for name in METAL_REVIEW_SECTION_NAMES
    )
    if all_reviewed:
        require(isinstance(provenance.get("reviewer"), str) and provenance["reviewer"].strip(), "complete metal scientific review requires an explicit reviewer")
        require(_is_valid_iso_date(provenance.get("review_date")), "complete metal scientific review requires a valid ISO review date")
    return state, family, all_reviewed


def build_metal_scientific_review(
    design_path: Path,
    template_path: Path,
    candidate_path: Path,
    review_source_path: Path,
    output: Path | None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Freeze an explicit bounded M1 review while preserving every runtime refusal."""
    require(dry_run or output is not None, "build-metal-scientific-review requires --output unless --dry-run is used")
    design = load_json(design_path)
    template = load_json(template_path)
    candidate = load_json(candidate_path)
    source = load_json(review_source_path)
    require(design.get("schema") == "gaussian-asymmetric-metal-support-design/1", "metal scientific review requires a metal-support design")
    require(
        design.get("design_payload_sha256")
        == sha256_data({key: value for key, value in design.items() if key != "design_payload_sha256"}),
        "metal-support design payload hash mismatch",
    )
    require(
        design.get("calculation_ready") is False
        and design.get("no_submission_authorization") is True
        and design.get("runtime_support_status") == "unsupported_requires_extension"
        and design.get("submission_decision") == "refused",
        "metal-support design widened the execution boundary",
    )
    require(template.get("schema") == "gaussian-asymmetric-metal-ts-audit-template/1", "metal scientific review requires a metal TS audit template")
    require(
        template.get("template_payload_sha256")
        == sha256_data({key: value for key, value in template.items() if key != "template_payload_sha256"}),
        "metal TS audit template payload hash mismatch",
    )
    require(
        template.get("calculation_ready") is False
        and template.get("no_submission_authorization") is True
        and template.get("runtime_support_status") == "unsupported_requires_extension"
        and template.get("submission_decision") == "refused"
        and template.get("status") == "blocked_pending_scientific_review"
        and template.get("claim_ceiling") == "design_only_no_ts_or_selectivity_claim",
        "metal TS audit template widened the scientific or execution boundary",
    )
    require(
        set(template.get("audit_sections", {}))
        == {"electron_accounting", "spin_surface", "wavefunction", "coordination", "method_protocol", "ts_and_path"}
        and all(section.get("status") == "blocked_pending_review" for section in template.get("audit_sections", {}).values()),
        "metal scientific review refuses an audit template whose review gate was bypassed",
    )
    require(
        template.get("seed_strategy_gate", {}).get("selected_strategy_id") is None
        and template.get("seed_strategy_gate", {}).get("selection_status") == "not_selected",
        "metal scientific review refuses an audit template with an execution strategy selection",
    )
    require(
        candidate.get("schema") == "gaussian-asymmetric-ts-candidate/1"
        and candidate.get("support_status") == "unsupported_transition_metal"
        and candidate.get("calculation_ready") is False
        and candidate.get("no_submission_authorization") is True
        and candidate.get("review_status") != "promoted_offline",
        "metal scientific review requires an unsupported, non-promoted metal candidate",
    )
    require(template.get("design_source", {}).get("sha256") == sha256_file(design_path), "metal scientific-review template design hash mismatch")
    require(template.get("candidate_source", {}).get("sha256") == sha256_file(candidate_path), "metal scientific-review template candidate hash mismatch")
    require(source.get("candidate_sha256") == sha256_file(candidate_path), "metal scientific-review source candidate hash mismatch")
    expected_order = _candidate_atom_order(candidate)
    _require_matching_atom_order(template.get("identity_binding", {}).get("atom_order"), expected_order, "metal scientific-review template")
    _state, _family, all_reviewed = _validate_metal_scientific_review_source(
        source, design, template, candidate
    )
    sections = copy.deepcopy(source["sections"])
    blocked_sections = sorted(
        name for name in METAL_REVIEW_SECTION_NAMES
        if sections[name]["status"] != "reviewed_for_bounded_example"
    )
    reviewed_sections = sorted(set(METAL_REVIEW_SECTION_NAMES) - set(blocked_sections))
    unresolved_blockers = [
        f"{name}: {blocker}"
        for name in METAL_REVIEW_SECTION_NAMES
        for blocker in sections[name]["blockers"]
    ]
    synthetic = source["provenance"]["scope_kind"] == "synthetic_nonresearch_fixture"
    if all_reviewed and synthetic:
        m1_status = "not_satisfied_synthetic_fixture"
    elif all_reviewed:
        m1_status = "reviewed_bounded_example_runtime_unsupported"
    else:
        m1_status = "pending_scientific_review"
    review = {
        "schema": "gaussian-asymmetric-metal-scientific-review/1",
        "review_id": source["review_id"],
        "design_source": {
            "sha256": sha256_file(design_path),
            "design_payload_sha256": design["design_payload_sha256"],
        },
        "template_source": {
            "sha256": sha256_file(template_path),
            "template_payload_sha256": template["template_payload_sha256"],
        },
        "candidate_source": {"sha256": sha256_file(candidate_path)},
        "review_source": {"sha256": sha256_file(review_source_path)},
        "study_id": source["study_id"],
        "candidate_id": source["candidate_id"],
        "channel_id": source["channel_id"],
        "catalyst_state_id": source["catalyst_state_id"],
        "mechanism_id": source["mechanism_id"],
        "status": "review_contract_complete_runtime_unsupported" if all_reviewed else "blocked_incomplete_scientific_review",
        "calculation_ready": False,
        "no_submission_authorization": True,
        "runtime_support_status": "unsupported_requires_extension",
        "submission_decision": "refused",
        "promotion_decision": "refused",
        "scientific_acceptance_decision": "not_granted_by_artifact",
        "literature_values_are_defaults": False,
        "review_scope": copy.deepcopy(source["provenance"]),
        "identity_binding": {
            "total_charge": source["identity"]["total_charge"],
            "multiplicity": source["identity"]["multiplicity"],
            "atom_count": template["identity_binding"]["atom_count"],
            "atom_order": copy.deepcopy(template["identity_binding"]["atom_order"]),
            "metal_centers": copy.deepcopy(source["identity"]["metal_centers"]),
            "coordinate_changes": copy.deepcopy(template["identity_binding"]["coordinate_changes"]),
            "coordination_contacts": copy.deepcopy(template["identity_binding"]["coordination_contacts"]),
        },
        "sections": sections,
        "completion": {
            "reviewed_sections": reviewed_sections,
            "blocked_sections": blocked_sections,
            "unresolved_blockers": unresolved_blockers,
            "metal_m1_scientific_review_status": m1_status,
            "metal_m2_offline_runtime_contract": "blocked",
            "metal_m3_execution_boundary": "blocked",
            "metal_m4_live_smoke": "blocked",
        },
        "hard_rejections": [
            "Do not interpret source-reported literature settings as defaults for another reaction, state, or candidate.",
            "Do not render a Gaussian route or input from this scientific-review artifact.",
            "Do not promote, stage, upload, submit, retry, cancel, clean up, or aggregate a transition-metal candidate from this artifact.",
            "Do not use the synthetic fixture success path as evidence that the real M1 scientific milestone is complete.",
            "Do not bypass the separate three-tier protocol selection, metal runtime, execution-boundary, or exact live-approval gates.",
        ],
        "claim_ceiling": "bounded_review_record_only_no_scientific_acceptance_ts_or_selectivity_claim",
    }
    review["review_payload_sha256"] = sha256_data(
        {key: value for key, value in review.items() if key != "review_payload_sha256"}
    )
    if not dry_run:
        assert output is not None
        write_json(output, review)
    return review


def build_metal_ts_audit_template(
    design_path: Path,
    candidate_path: Path,
    output: Path,
) -> dict[str, Any]:
    """Bind one unsupported metal TS candidate to a fail-closed offline audit template."""
    design = load_json(design_path)
    candidate = load_json(candidate_path)
    require(
        design.get("schema") == "gaussian-asymmetric-metal-support-design/1",
        "metal TS audit template requires a metal-support design",
    )
    require(
        design.get("design_payload_sha256")
        == sha256_data({key: value for key, value in design.items() if key != "design_payload_sha256"}),
        "metal-support design payload hash mismatch",
    )
    require(
        design.get("calculation_ready") is False
        and design.get("no_submission_authorization") is True
        and design.get("submission_decision") == "refused",
        "metal-support design widened the execution boundary",
    )
    require(
        candidate.get("schema") == "gaussian-asymmetric-ts-candidate/1"
        and candidate.get("support_status") == "unsupported_transition_metal",
        "metal TS audit template requires an unsupported transition-metal candidate",
    )
    require(
        candidate.get("calculation_ready") is False
        and candidate.get("no_submission_authorization") is True
        and candidate.get("review_status") != "promoted_offline",
        "metal TS audit template refuses a promotable or calculation-ready candidate",
    )
    require(
        candidate.get("study_id") == design.get("study_id")
        and candidate.get("study_sha256") == design.get("study_sha256"),
        "metal candidate and support design study bindings differ",
    )

    states = {item["state_id"]: item for item in design.get("states", [])}
    state_id = candidate.get("catalyst_state_id")
    require(state_id in states, "metal candidate references a state absent from the support design")
    state = states[state_id]
    families = {item["mechanism_id"]: item for item in design.get("ts_search_families", [])}
    mechanism_id = candidate.get("mechanism_id")
    require(mechanism_id in families, "metal candidate references a mechanism absent from the support design")
    family = families[mechanism_id]
    require(family.get("active_state_id") == state_id, "metal candidate mechanism/state binding differs from the support design")
    require(candidate.get("channel_id") in family.get("channel_ids", []), "metal candidate channel is outside the support design")

    expected_atom_order = _candidate_atom_order(candidate)
    atom_map = candidate["atom_map"]
    role_by_index = {item["index"]: item.get("role", "unassigned") for item in atom_map}
    element_by_index = {item["index"]: item["element"] for item in atom_map}
    centers = []
    for center in state.get("metal_centers", []):
        atom_index = center.get("atom_index")
        require(atom_index in element_by_index, "metal-center atom index is outside the candidate atom map")
        require(element_by_index[atom_index] == center.get("element"), "metal-center element differs from the candidate atom map")
        centers.append(
            {
                "atom_index": atom_index,
                "element": center["element"],
                "formal_oxidation_state": center.get("formal_oxidation_state"),
                "d_electron_count": None,
                "coordination_number": center.get("coordination_number"),
                "geometry": center.get("geometry"),
                "review_status": "unreviewed_hypothesis",
            }
        )
    require(centers, "metal TS audit template has no bound metal center")

    contacts = []
    for contact in candidate.get("binding_mode", {}).get("coordination_contacts", []):
        donor = contact.get("donor_atom")
        acceptor = contact.get("acceptor_atom")
        require(donor in element_by_index and acceptor in element_by_index, "coordination contact is outside the candidate atom map")
        contacts.append(
            {
                "donor_atom": donor,
                "acceptor_atom": acceptor,
                "kind": contact.get("kind"),
                "distance_window_angstrom": None,
                "review_status": "pending",
            }
        )
    contacts.sort(key=lambda item: (item["acceptor_atom"], item["donor_atom"], str(item["kind"])))

    audit_sections = {
        "electron_accounting": {
            "status": "blocked_pending_review",
            "required_evidence": [
                "reviewed ligand-charge and metal-metal bonding conventions",
                "formal oxidation state and d-electron count for every metal",
                "total valence-electron count, parity, charge and multiplicity consistency",
                "explicit non-innocent-ligand alternatives",
            ],
            "rejection_conditions": [
                "any electron count or ligand-charge convention is inferred",
                "electron parity and multiplicity are inconsistent or unreviewed",
            ],
        },
        "spin_surface": {
            "status": "blocked_pending_review",
            "required_evidence": [
                "credible multiplicity inventory for the exact coordination state",
                "common reference for spin-state comparisons",
                "single-surface, spin-crossover and MECP relevance decision",
            ],
            "rejection_conditions": [
                "a multiplicity is selected from electron parity alone",
                "different spin surfaces are mixed in one TS ensemble",
            ],
        },
        "wavefunction": {
            "status": "blocked_pending_review",
            "required_evidence": [
                "explicit restricted, unrestricted, RO or broken-symmetry hypothesis",
                "state-specific SCF stability and occupation-inspection policy",
                "expected S(S+1), spin-contamination threshold and alternative-solution checks",
                "system-appropriate single-reference or multireference diagnostics",
            ],
            "rejection_conditions": [
                "SCF convergence is used as electronic-state validation",
                "wavefunction stability, occupations or multireference risk remain unresolved",
            ],
        },
        "coordination": {
            "status": "blocked_pending_review",
            "required_evidence": [
                "one-based metal-donor map with reviewed distance windows",
                "ligand count, denticity, hapticity and hemilability inventory",
                "substrate, counterion, solvent and additive occupancy alternatives",
                "pre/post geometry audit for coordination-number or binding-mode drift",
            ],
            "rejection_conditions": [
                "a ligand, counterion or substrate contact changes outside its reviewed window",
                "coordination or hapticity changes are silently treated as the same state",
            ],
        },
        "method_protocol": {
            "status": "blocked_pending_review",
            "required_evidence": [
                "three-tier protocol proposal after state review",
                "basis/ECP and core-electron accounting for every element",
                "relativity, dispersion, solvent, grid and SCF policies",
                "spin-state, wavefunction and geometry/frequency sensitivity plan",
            ],
            "rejection_conditions": [
                "a literature method is copied as an unreviewed default",
                "any element lacks an explicit basis/ECP/relativity assignment",
            ],
        },
        "ts_and_path": {
            "status": "blocked_pending_review",
            "required_evidence": [
                "reviewed elementary-step class and atom correspondence",
                "selected seed strategy with strategy-specific provenance",
                "normal stationary-point and complete frequency evidence",
                "exactly one raw imaginary mode reviewed for the intended coordinate and unintended coordination loss",
                "metal-specific endpoint or crossing model appropriate to the reviewed surface",
            ],
            "rejection_conditions": [
                "frequency count alone is used to accept a TS",
                "main-group IRC logic is used to claim metal path connectivity",
            ],
        },
    }
    strategies = [
        {
            "strategy_id": item["strategy_id"],
            "strategy": item["strategy"],
            "status": item["status"],
        }
        for item in sorted(family.get("seed_strategy_candidates", []), key=lambda value: value["strategy"])
    ]
    require(
        {item["strategy"] for item in strategies}
        == {"single_guess_hessian_guided", "endpoint_qst2_qst3", "reviewed_relaxed_coordinate_scan"},
        "metal support design lacks the complete seed-strategy inventory",
    )

    template = {
        "schema": "gaussian-asymmetric-metal-ts-audit-template/1",
        "template_id": f"metal_audit_{sha256_data([design['study_id'], candidate['candidate_id']])[:12]}",
        "design_source": {"sha256": sha256_file(design_path)},
        "candidate_source": {"sha256": sha256_file(candidate_path)},
        "study_id": design["study_id"],
        "candidate_id": candidate["candidate_id"],
        "mechanism_id": mechanism_id,
        "channel_id": candidate["channel_id"],
        "catalyst_state_id": state_id,
        "status": "blocked_pending_scientific_review",
        "calculation_ready": False,
        "no_submission_authorization": True,
        "runtime_support_status": "unsupported_requires_extension",
        "submission_decision": "refused",
        "identity_binding": {
            "charge": candidate["chemical_state"]["charge"],
            "multiplicity": candidate["chemical_state"]["multiplicity"],
            "atom_count": candidate["atom_inventory"]["atom_count"],
            "atom_order": [
                {"index": item["index"], "element": item["element"], "role": role_by_index[item["index"]]}
                for item in expected_atom_order
            ],
            "metal_centers": centers,
            "coordinate_changes": copy.deepcopy(candidate["coordinate_changes"]),
            "coordination_contacts": contacts,
        },
        "audit_sections": audit_sections,
        "seed_strategy_gate": {
            "inventory": strategies,
            "selected_strategy_id": None,
            "selection_status": "not_selected",
            "selection_required": True,
        },
        "hard_rejections": [
            "Do not render a Gaussian route or input from this template.",
            "Do not stage, upload, submit, retry, cancel or clean up a metal job.",
            "Do not promote the candidate while any audit section is blocked.",
            "Do not reuse a checkpoint, Hessian, guess or energy across unreviewed electronic or coordination states.",
            "Do not aggregate different spin surfaces without a separately reviewed crossing or kinetic model.",
        ],
        "claim_ceiling": "design_only_no_ts_or_selectivity_claim",
    }
    template["template_payload_sha256"] = sha256_data(
        {key: value for key, value in template.items() if key != "template_payload_sha256"}
    )
    write_json(output, template)
    return template


def _parse_gaussian_cartesian_input_observation(text: str) -> dict[str, Any]:
    """Parse one existing single-step Cartesian input without approving its chemistry."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    require("--Link1--" not in normalized, "metal input observation refuses multi-step --Link1-- input")
    lines = normalized.split("\n")
    position = 0
    while position < len(lines) and not lines[position].strip():
        position += 1

    link0: list[dict[str, str]] = []
    seen_link0: set[str] = set()
    while position < len(lines) and lines[position].lstrip().startswith("%"):
        match = re.fullmatch(r"\s*%([A-Za-z][A-Za-z0-9]*)\s*=\s*(\S(?:.*\S)?)\s*", lines[position])
        require(match is not None, "metal input observation found an unsupported Link 0 directive")
        key = match.group(1).lower()
        require(key not in seen_link0, f"metal input observation found duplicate Link 0 directive: %{key}")
        seen_link0.add(key)
        link0.append({"key": key, "value": match.group(2)})
        position += 1

    require(position < len(lines) and lines[position].lstrip().startswith("#"), "metal input observation found no Gaussian route section")
    route_lines: list[str] = []
    while position < len(lines) and lines[position].strip():
        route_lines.append(lines[position].strip())
        position += 1
    route_text = " ".join(route_lines)
    require(route_text.startswith("#"), "metal input observation route section is malformed")

    while position < len(lines) and not lines[position].strip():
        position += 1
    title_lines: list[str] = []
    while position < len(lines) and lines[position].strip():
        title_lines.append(lines[position].strip())
        position += 1
    require(title_lines, "metal input observation found no title section")

    while position < len(lines) and not lines[position].strip():
        position += 1
    require(position < len(lines), "metal input observation found no charge/multiplicity line")
    charge_multiplicity = re.fullmatch(r"\s*(-?\d+)\s+(\d+)\s*", lines[position])
    require(charge_multiplicity is not None, "metal input observation charge/multiplicity line is malformed")
    charge = int(charge_multiplicity.group(1))
    multiplicity = int(charge_multiplicity.group(2))
    require(multiplicity >= 1, "metal input observation multiplicity must be positive")
    position += 1

    number = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[DEde][-+]?\d+)?"
    coordinate_row = re.compile(
        rf"\s*([A-Z][a-z]?)\s+({number})\s+({number})\s+({number})\s*"
    )
    coordinates: list[dict[str, Any]] = []
    while position < len(lines) and lines[position].strip():
        match = coordinate_row.fullmatch(lines[position])
        require(match is not None, "metal input observation supports only explicit element-symbol Cartesian coordinates")
        element = match.group(1)
        require(element in ATOMIC_NUMBERS, f"metal input observation contains unsupported element: {element}")
        xyz = [float(match.group(index).replace("D", "E").replace("d", "e")) for index in (2, 3, 4)]
        require(all(math.isfinite(value) for value in xyz), "metal input observation contains a non-finite coordinate")
        coordinates.append(
            {
                "index": len(coordinates) + 1,
                "atomic_number": ATOMIC_NUMBERS[element],
                "element": element,
                "x": xyz[0],
                "y": xyz[1],
                "z": xyz[2],
            }
        )
        position += 1
    require(coordinates, "metal input observation found no explicit Cartesian coordinates")

    trailing_lines = [line.rstrip() for line in lines[position:] if line.strip()]
    trailing_text = "\n".join(trailing_lines)
    absolute_path = re.compile(r"^(?:/|[A-Za-z]:[\\/])")
    route_lower = route_text.lower()
    return {
        "link0_directives": link0,
        "route_text": route_text,
        "route_sha256": hashlib.sha256(route_text.encode("utf-8")).hexdigest(),
        "title_line_count": len(title_lines),
        "title_sha256": hashlib.sha256("\n".join(title_lines).encode("utf-8")).hexdigest(),
        "charge": charge,
        "multiplicity": multiplicity,
        "atom_count": len(coordinates),
        "atom_order": [
            {"index": item["index"], "atomic_number": item["atomic_number"], "element": item["element"]}
            for item in coordinates
        ],
        "coordinate_block_sha256": sha256_data(coordinates),
        "explicit_cartesian_geometry_status": "parsed",
        "trailing_section_line_count": len(trailing_lines),
        "trailing_section_sha256": hashlib.sha256(trailing_text.encode("utf-8")).hexdigest() if trailing_lines else None,
        "contains_absolute_link0_path_observed": any(
            absolute_path.match(item["value"]) is not None for item in link0
        ),
        "task_text_observations": {
            "opt_text_observed": re.search(r"(?i)(?:^|[\s,(])opt(?:[\s,=(]|$)", route_text) is not None,
            "freq_text_observed": re.search(r"(?i)(?:^|[\s,(])freq(?:[\s,=(]|$)", route_text) is not None,
            "ts_text_observed": re.search(r"(?i)(?:^|[\s,(])ts(?:[\s,)=]|$)", route_text) is not None,
            "geom_check_text_observed": "geom=check" in route_lower or "geom=allcheck" in route_lower,
            "gen_or_genecp_text_observed": re.search(r"(?i)(?:^|[\s/])gen(?:ecp)?(?:[\s,]|$)", route_text) is not None,
        },
        "protocol_selection_binding_status": "absent_not_accepted",
        "remote_path_validation_status": "not_performed_offline_no_execution_authority",
    }


def audit_metal_input_observation(
    template_path: Path,
    candidate_path: Path,
    scientific_review_path: Path,
    input_path: Path,
    output: Path | None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Observe one existing metal Gaussian input; never render, accept, or execute it."""
    template = load_json(template_path)
    candidate = load_json(candidate_path)
    review = load_json(scientific_review_path)
    require(
        template.get("schema") == "gaussian-asymmetric-metal-ts-audit-template/1"
        and template.get("template_payload_sha256")
        == sha256_data({key: value for key, value in template.items() if key != "template_payload_sha256"}),
        "metal input observation requires an intact metal TS audit template",
    )
    require(
        template.get("calculation_ready") is False
        and template.get("no_submission_authorization") is True
        and template.get("submission_decision") == "refused"
        and template.get("runtime_support_status") == "unsupported_requires_extension"
        and template.get("status") == "blocked_pending_scientific_review"
        and template.get("claim_ceiling") == "design_only_no_ts_or_selectivity_claim"
        and all(section.get("status") == "blocked_pending_review" for section in template.get("audit_sections", {}).values())
        and template.get("seed_strategy_gate", {}).get("selected_strategy_id") is None
        and template.get("seed_strategy_gate", {}).get("selection_status") == "not_selected",
        "metal input observation refuses a template that bypassed a scientific gate",
    )
    require(
        candidate.get("schema") == "gaussian-asymmetric-ts-candidate/1"
        and candidate.get("support_status") == "unsupported_transition_metal"
        and candidate.get("calculation_ready") is False
        and candidate.get("no_submission_authorization") is True
        and candidate.get("review_status") != "promoted_offline",
        "metal input observation requires an unsupported, non-promoted metal candidate",
    )
    require(
        template.get("candidate_source", {}).get("sha256") == sha256_file(candidate_path),
        "metal input observation candidate hash differs from the audit template",
    )
    require(
        review.get("schema") == "gaussian-asymmetric-metal-scientific-review/1"
        and review.get("review_payload_sha256")
        == sha256_data({key: value for key, value in review.items() if key != "review_payload_sha256"}),
        "metal input observation requires an intact metal scientific-review record",
    )
    require(
        review.get("calculation_ready") is False
        and review.get("no_submission_authorization") is True
        and review.get("runtime_support_status") == "unsupported_requires_extension"
        and review.get("submission_decision") == "refused"
        and review.get("promotion_decision") == "refused"
        and review.get("scientific_acceptance_decision") == "not_granted_by_artifact"
        and review.get("literature_values_are_defaults") is False,
        "metal input observation refuses a scientific-review record that widened authority",
    )
    require(
        review.get("template_source", {}).get("sha256") == sha256_file(template_path)
        and review.get("candidate_source", {}).get("sha256") == sha256_file(candidate_path),
        "metal input observation scientific-review lineage differs from template/candidate",
    )
    for key in ("study_id", "candidate_id", "mechanism_id", "channel_id", "catalyst_state_id"):
        require(template.get(key) == candidate.get(key) == review.get(key), f"metal input observation {key} binding mismatch")

    expected_order = _candidate_atom_order(candidate)
    _require_matching_atom_order(template.get("identity_binding", {}).get("atom_order"), expected_order, "metal TS audit template")
    _require_matching_atom_order(review.get("identity_binding", {}).get("atom_order"), expected_order, "metal scientific review")
    expected_charge = candidate.get("chemical_state", {}).get("charge")
    expected_multiplicity = candidate.get("chemical_state", {}).get("multiplicity")
    require(
        template.get("identity_binding", {}).get("charge") == expected_charge
        and template.get("identity_binding", {}).get("multiplicity") == expected_multiplicity
        and review.get("identity_binding", {}).get("total_charge") == expected_charge
        and review.get("identity_binding", {}).get("multiplicity") == expected_multiplicity,
        "metal input observation candidate/template/review charge or multiplicity differs",
    )

    require(input_path.is_file() and not input_path.is_symlink(), "metal input observation input must be a regular non-symlink file")
    parsed = _parse_gaussian_cartesian_input_observation(input_path.read_text(encoding="utf-8"))
    require(
        parsed["charge"] == expected_charge and parsed["multiplicity"] == expected_multiplicity,
        "metal input observation charge/multiplicity differs from candidate",
    )
    _require_matching_atom_order(parsed["atom_order"], expected_order, "metal Gaussian input")
    require(
        not parsed["task_text_observations"]["geom_check_text_observed"],
        "metal input observation requires explicit coordinates and refuses Geom=Check/AllCheck ambiguity",
    )

    m1_status = review.get("completion", {}).get("metal_m1_scientific_review_status")
    blocked_sections = {
        name: {"status": "blocked_pending_review", "reason": reason}
        for name, reason in {
            "electron_accounting": "The M1 record is bound, but observing an input cannot accept electron accounting or ligand-charge conventions.",
            "spin_surface": "Matching charge/multiplicity text does not accept the spin inventory, surface model or crossing relevance.",
            "wavefunction": "The input text does not provide accepted stability, occupation, alternative-solution or multireference evidence.",
            "coordination": "Element order is matched, but coordinates are not accepted against reviewed hapticity, ligand-inventory or post-optimization rules.",
            "method_protocol": "Route and trailing sections are observed only; no hash-bound three-tier protocol selection is present or accepted.",
            "ts_and_path": "Task text is not a selected TS strategy, normal-mode decision, endpoint identity or metal-specific path model.",
        }.items()
    }
    diagnostics = [
        "The existing input was read but never rendered, modified, staged, uploaded, submitted or executed.",
        "Route, Link 0, Cartesian and trailing-section facts are observations only and are not protocol or scientific acceptance.",
        f"Bound M1 milestone status is {m1_status}; this input observation cannot change it.",
    ]
    if parsed["contains_absolute_link0_path_observed"]:
        diagnostics.append("An absolute Link 0 path was observed; no remote realpath or /home/user100/SDL safety validation was performed offline.")
    if parsed["trailing_section_line_count"]:
        diagnostics.append("Trailing input sections were hash-bound but not interpreted as basis, ECP, connectivity or constraints.")

    observation = {
        "schema": "gaussian-asymmetric-metal-input-observation/1",
        "audit_id": f"metal_input_obs_{sha256_data([template['template_id'], sha256_file(input_path)])[:12]}",
        "template_source": {"sha256": sha256_file(template_path)},
        "candidate_source": {"sha256": sha256_file(candidate_path)},
        "scientific_review_source": {"sha256": sha256_file(scientific_review_path)},
        "input_source": {"sha256": sha256_file(input_path)},
        "study_id": template["study_id"],
        "candidate_id": template["candidate_id"],
        "mechanism_id": template["mechanism_id"],
        "channel_id": template["channel_id"],
        "catalyst_state_id": template["catalyst_state_id"],
        "status": "parsed_input_observation_blocked",
        "calculation_ready": False,
        "no_submission_authorization": True,
        "runtime_support_status": "unsupported_requires_extension",
        "input_acceptance_decision": "not_granted_by_artifact",
        "protocol_selection_decision": "absent_not_authorized",
        "submission_decision": "refused",
        "promotion_decision": "refused",
        "parser": {
            "parser_id": "auto_g16_asymmetric_metal_input_observer_v1",
            "scope": "offline_read_only_existing_input_observation",
            "renders_input": False,
        },
        "review_binding": {
            "review_id": review["review_id"],
            "review_status": review["status"],
            "metal_m1_scientific_review_status": m1_status,
            "scientific_acceptance_decision": review["scientific_acceptance_decision"],
        },
        "identity_binding": {
            "charge": expected_charge,
            "multiplicity": expected_multiplicity,
            "atom_count": len(expected_order),
            "atom_order": expected_order,
            "identity_observation_status": "matched_candidate_template_review",
        },
        "input_observations": parsed,
        "audit_sections": blocked_sections,
        "completion": {
            "metal_m2c_input_observation": "implemented_offline",
            "metal_m2_offline_runtime_contract": "blocked",
            "metal_m3_execution_boundary": "blocked",
            "metal_m4_live_smoke": "blocked",
        },
        "diagnostics": diagnostics,
        "hard_rejections": [
            "Do not treat route text as a selected protocol or approved Gaussian input.",
            "Do not infer basis/ECP, solvent, spin, wavefunction, TS algorithm, IRC or thermochemistry acceptance.",
            "Do not stage, upload, submit, retry, cancel, clean up or deploy from this artifact.",
            "Do not promote a metal candidate from input identity matching or task-keyword observations.",
        ],
        "claim_ceiling": "existing_input_observation_only_no_acceptance_execution_ts_or_selectivity_claim",
    }
    observation["audit_payload_sha256"] = sha256_data(
        {key: value for key, value in observation.items() if key != "audit_payload_sha256"}
    )
    require(dry_run or output is not None, "audit-metal-input requires --output unless --dry-run is used")
    if not dry_run:
        assert output is not None
        write_json(output, observation)
    return observation


def _gaussian_orientation_blocks(text: str) -> list[list[dict[str, Any]]]:
    """Parse Gaussian orientation tables without assigning chemical meaning."""
    row = re.compile(
        r"^\s*(\d+)\s+(\d+)\s+(-?\d+)\s+"
        r"([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[DEde][-+]?\d+)?)\s+"
        r"([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[DEde][-+]?\d+)?)\s+"
        r"([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[DEde][-+]?\d+)?)\s*$"
    )
    lines = text.splitlines()
    blocks: list[list[dict[str, Any]]] = []
    for marker, line in enumerate(lines):
        if not re.fullmatch(r"\s*(?:Standard|Input) orientation:\s*", line):
            continue
        atoms: list[dict[str, Any]] = []
        for candidate_line in lines[marker + 1 :]:
            match = row.fullmatch(candidate_line)
            if match:
                atomic_number = int(match.group(2))
                element = next(
                    (symbol for symbol, number in ATOMIC_NUMBERS.items() if number == atomic_number),
                    None,
                )
                require(element is not None, f"Gaussian orientation contains unsupported atomic number: {atomic_number}")
                coordinates = [
                    float(match.group(index).replace("D", "E").replace("d", "e"))
                    for index in (4, 5, 6)
                ]
                require(all(math.isfinite(value) for value in coordinates), "Gaussian orientation contains a non-finite coordinate")
                atoms.append(
                    {
                        "index": int(match.group(1)),
                        "atomic_number": atomic_number,
                        "element": element,
                        "x": coordinates[0],
                        "y": coordinates[1],
                        "z": coordinates[2],
                    }
                )
            elif atoms and re.fullmatch(r"\s*-{5,}\s*", candidate_line):
                break
        if atoms:
            blocks.append(atoms)
    return blocks


def _distance(atoms: list[dict[str, Any]], left: int, right: int) -> float:
    by_index = {item["index"]: item for item in atoms}
    require(left in by_index and right in by_index, "coordination contact is outside parsed geometry")
    a = by_index[left]
    b = by_index[right]
    distance = math.sqrt(sum((float(a[axis]) - float(b[axis])) ** 2 for axis in ("x", "y", "z")))
    require(math.isfinite(distance), "parsed coordination distance is non-finite")
    return distance


def audit_metal_result_observation(
    template_path: Path,
    candidate_path: Path,
    log_path: Path,
    output: Path | None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Parse one metal log as blocked evidence; never promote it to a TS result."""
    template = load_json(template_path)
    candidate = load_json(candidate_path)
    require(
        template.get("schema") == "gaussian-asymmetric-metal-ts-audit-template/1",
        "metal result observation requires a metal TS audit template",
    )
    require(
        template.get("template_payload_sha256")
        == sha256_data({key: value for key, value in template.items() if key != "template_payload_sha256"}),
        "metal TS audit template payload hash mismatch",
    )
    require(
        template.get("calculation_ready") is False
        and template.get("no_submission_authorization") is True
        and template.get("submission_decision") == "refused"
        and template.get("runtime_support_status") == "unsupported_requires_extension",
        "metal TS audit template widened the execution boundary",
    )
    require(
        template.get("status") == "blocked_pending_scientific_review"
        and template.get("claim_ceiling") == "design_only_no_ts_or_selectivity_claim"
        and set(template.get("audit_sections", {}))
        == {
            "electron_accounting", "spin_surface", "wavefunction",
            "coordination", "method_protocol", "ts_and_path",
        }
        and all(
            section.get("status") == "blocked_pending_review"
            for section in template.get("audit_sections", {}).values()
        )
        and template.get("seed_strategy_gate", {}).get("selected_strategy_id") is None
        and template.get("seed_strategy_gate", {}).get("selection_status") == "not_selected",
        "metal TS audit template bypassed a scientific review gate",
    )
    require(
        candidate.get("schema") == "gaussian-asymmetric-ts-candidate/1"
        and candidate.get("support_status") == "unsupported_transition_metal"
        and candidate.get("calculation_ready") is False
        and candidate.get("no_submission_authorization") is True
        and candidate.get("review_status") != "promoted_offline",
        "metal result observation requires an unsupported, non-promoted metal candidate",
    )
    require(
        template.get("candidate_source", {}).get("sha256") == sha256_file(candidate_path),
        "metal result observation candidate hash differs from the audit template",
    )
    for key in ("study_id", "candidate_id", "mechanism_id", "channel_id", "catalyst_state_id"):
        require(template.get(key) == candidate.get(key), f"metal result observation {key} binding mismatch")

    expected_order = _candidate_atom_order(candidate)
    template_order = template.get("identity_binding", {}).get("atom_order")
    require(isinstance(template_order, list), "metal TS audit template atom order is missing")
    _require_matching_atom_order(template_order, expected_order, "metal TS audit template")
    expected_charge = candidate.get("chemical_state", {}).get("charge")
    expected_multiplicity = candidate.get("chemical_state", {}).get("multiplicity")
    require(
        template.get("identity_binding", {}).get("charge") == expected_charge
        and template.get("identity_binding", {}).get("multiplicity") == expected_multiplicity,
        "metal TS audit template charge/multiplicity differs from candidate",
    )

    require(log_path.is_file() and not log_path.is_symlink(), "metal observation log must be a regular non-symlink file")
    text = log_path.read_text(encoding="utf-8", errors="replace")
    charge_multiplicity = [
        (int(charge), int(multiplicity))
        for charge, multiplicity in re.findall(
            r"Charge\s*=\s*(-?\d+)\s+Multiplicity\s*=\s*(\d+)", text
        )
    ]
    require(charge_multiplicity, "metal observation log has no charge/multiplicity record")
    require(
        set(charge_multiplicity) == {(expected_charge, expected_multiplicity)},
        "metal observation log charge/multiplicity differs from candidate",
    )
    orientations = _gaussian_orientation_blocks(text)
    require(orientations, "metal observation log has no parseable orientation")
    _require_matching_atom_order(orientations[0], expected_order, "initial metal log geometry")
    _require_matching_atom_order(orientations[-1], expected_order, "final metal log geometry")

    frequencies = [
        float(value.replace("D", "E").replace("d", "e"))
        for values in re.findall(r"(?m)^\s*Frequencies\s+--\s+(.+)$", text)
        for value in values.split()
    ]
    require(all(math.isfinite(value) for value in frequencies), "metal observation log contains a non-finite frequency")
    imaginary = [value for value in frequencies if value < 0.0]
    s2_observations = [
        {
            "before_annihilation": float(before.replace("D", "E").replace("d", "e")),
            "after_annihilation": float(after.replace("D", "E").replace("d", "e")),
        }
        for before, after in re.findall(
            r"S\*\*2\s+before\s+annihilation\s+([-+0-9.DEde]+),\s*after\s+([-+0-9.DEde]+)",
            text,
        )
    ]
    require(
        all(
            math.isfinite(item["before_annihilation"]) and math.isfinite(item["after_annihilation"])
            for item in s2_observations
        ),
        "metal observation log contains a non-finite S**2 value",
    )

    contacts = []
    for contact in template.get("identity_binding", {}).get("coordination_contacts", []):
        require(
            contact.get("distance_window_angstrom") is None and contact.get("review_status") == "pending",
            "metal result observation refuses a template with inferred coordination acceptance",
        )
        initial_distance = _distance(orientations[0], contact["donor_atom"], contact["acceptor_atom"])
        final_distance = _distance(orientations[-1], contact["donor_atom"], contact["acceptor_atom"])
        contacts.append(
            {
                "donor_atom": contact["donor_atom"],
                "acceptor_atom": contact["acceptor_atom"],
                "kind": contact["kind"],
                "initial_distance_angstrom": round(initial_distance, 8),
                "final_distance_angstrom": round(final_distance, 8),
                "distance_change_angstrom": round(final_distance - initial_distance, 8),
                "distance_window_angstrom": None,
                "review_status": "observed_unreviewed_no_window",
            }
        )

    revision = re.search(r"Gaussian\s+16(?:[:,]\s*|\s+)([^\n]+)", text)
    diagnostics = [
        "Parsed values are observations only; no electronic-state, coordination, mode, path, or method acceptance is inferred.",
        "The generic main-group TS/IRC result contract is not used for this transition-metal log.",
    ]
    if not frequencies:
        diagnostics.append("No frequency lines were observed; frequency completeness remains unassessed.")
    if len(imaginary) == 1:
        diagnostics.append("Exactly one raw imaginary frequency was observed, but no TS claim is allowed without metal-specific mode and state review.")
    if not s2_observations:
        diagnostics.append("No S**2 before/after-annihilation record was observed; no spin-state conclusion is allowed.")

    blocked_sections = {
        name: {
            "status": "blocked_pending_review",
            "reason": reason,
        }
        for name, reason in {
            "electron_accounting": "Ligand-charge convention, d-electron count and parity review are not supplied by a log.",
            "spin_surface": "Multiplicity alternatives, common references and crossing relevance remain unreviewed.",
            "wavefunction": "Observed stability/S**2 text lacks approved state-specific thresholds and occupation diagnostics.",
            "coordination": "Distances were measured, but no reviewed distance windows, hapticity or ligand-inventory acceptance rules exist.",
            "method_protocol": "No hash-bound approved three-tier metal protocol is bound to this observation.",
            "ts_and_path": "Frequency observations lack an accepted displacement review and a metal-specific surface/path model.",
        }.items()
    }
    observation = {
        "schema": "gaussian-asymmetric-metal-result-observation/1",
        "audit_id": f"metal_obs_{sha256_data([template['template_id'], sha256_file(log_path)])[:12]}",
        "template_source": {"sha256": sha256_file(template_path)},
        "candidate_source": {"sha256": sha256_file(candidate_path)},
        "log_source": {"sha256": sha256_file(log_path)},
        "study_id": template["study_id"],
        "candidate_id": template["candidate_id"],
        "mechanism_id": template["mechanism_id"],
        "channel_id": template["channel_id"],
        "catalyst_state_id": template["catalyst_state_id"],
        "status": "parsed_observation_blocked",
        "calculation_ready": False,
        "no_submission_authorization": True,
        "runtime_support_status": "unsupported_requires_extension",
        "submission_decision": "refused",
        "promotion_decision": "refused",
        "parser": {
            "parser_id": "auto_g16_asymmetric_metal_log_observer_v1",
            "scope": "offline_read_only_observation",
            "g16_revision_observed": revision.group(1).strip() if revision else None,
        },
        "identity_binding": {
            "charge": expected_charge,
            "multiplicity": expected_multiplicity,
            "atom_count": len(expected_order),
            "atom_order": [
                {"index": item["index"], "atomic_number": item["atomic_number"], "element": item["element"]}
                for item in expected_order
            ],
            "charge_multiplicity_record_count": len(charge_multiplicity),
            "orientation_count": len(orientations),
            "identity_observation_status": "matched_candidate",
        },
        "termination_observations": {
            "normal_termination_count": text.count("Normal termination of Gaussian"),
            "error_termination_count": text.count("Error termination"),
            "optimization_completed_observed": "Optimization completed" in text,
            "stationary_point_observed": "Stationary point found" in text,
        },
        "frequency_observations": {
            "frequency_count": len(frequencies),
            "frequencies_cm_1": frequencies,
            "raw_imaginary_frequency_count": len(imaginary),
            "imaginary_frequencies_cm_1": imaginary,
            "exactly_one_raw_imaginary_observed": len(imaginary) == 1,
            "completeness_status": "unassessed_requires_expected_mode_count",
            "mode_review_status": "not_performed",
        },
        "wavefunction_observations": {
            "scf_done_count": len(re.findall(r"(?m)^\s*SCF Done:", text)),
            "s2_observations": s2_observations,
            "stability_statement_observed": "The wavefunction is stable under the perturbations considered." in text,
            "threshold_assessment": "not_performed_no_approved_policy",
        },
        "coordination_observations": {
            "contacts": contacts,
            "inventory_assessment": "not_performed_no_reviewed_windows_or_hapticity_rules",
        },
        "audit_sections": blocked_sections,
        "diagnostics": diagnostics,
        "claim_ceiling": "parsed_observation_only_no_ts_or_selectivity_claim",
    }
    observation["audit_payload_sha256"] = sha256_data(
        {key: value for key, value in observation.items() if key != "audit_payload_sha256"}
    )
    require(dry_run or output is not None, "metal result observation requires --output unless --dry-run is used")
    if not dry_run:
        require(output is not None, "metal result observation output path is missing")
        write_json(output, observation)
    return observation


def build_metal_acceptance_review(
    template_path: Path,
    candidate_path: Path,
    scientific_review_path: Path,
    input_observation_path: Path,
    result_observation_path: Path,
    decision_source_path: Path,
    output: Path | None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Record four manual M2 decisions without granting runtime or promotion authority."""
    template = load_json(template_path)
    candidate = load_json(candidate_path)
    scientific_review = load_json(scientific_review_path)
    input_observation = load_json(input_observation_path)
    result_observation = load_json(result_observation_path)
    source = load_json(decision_source_path)

    require(
        template.get("schema") == "gaussian-asymmetric-metal-ts-audit-template/1"
        and template.get("template_payload_sha256")
        == sha256_data({key: value for key, value in template.items() if key != "template_payload_sha256"}),
        "metal acceptance review requires an intact M2a template",
    )
    require(
        candidate.get("schema") == "gaussian-asymmetric-ts-candidate/1"
        and candidate.get("support_status") == "unsupported_transition_metal"
        and candidate.get("calculation_ready") is False
        and candidate.get("no_submission_authorization") is True
        and candidate.get("review_status") != "promoted_offline",
        "metal acceptance review requires an unsupported, non-promoted metal candidate",
    )
    require(
        scientific_review.get("schema") == "gaussian-asymmetric-metal-scientific-review/1"
        and scientific_review.get("review_payload_sha256")
        == sha256_data({key: value for key, value in scientific_review.items() if key != "review_payload_sha256"})
        and scientific_review.get("scientific_acceptance_decision") == "not_granted_by_artifact"
        and scientific_review.get("promotion_decision") == "refused",
        "metal acceptance review requires an intact, refusal-preserving M1 record",
    )
    require(
        input_observation.get("schema") == "gaussian-asymmetric-metal-input-observation/1"
        and input_observation.get("audit_payload_sha256")
        == sha256_data({key: value for key, value in input_observation.items() if key != "audit_payload_sha256"})
        and input_observation.get("input_acceptance_decision") == "not_granted_by_artifact"
        and input_observation.get("promotion_decision") == "refused",
        "metal acceptance review requires an intact, blocked M2c input observation",
    )
    require(
        result_observation.get("schema") == "gaussian-asymmetric-metal-result-observation/1"
        and result_observation.get("audit_payload_sha256")
        == sha256_data({key: value for key, value in result_observation.items() if key != "audit_payload_sha256"})
        and result_observation.get("promotion_decision") == "refused",
        "metal acceptance review requires an intact, blocked M2b result observation",
    )
    require(
        template.get("candidate_source", {}).get("sha256") == sha256_file(candidate_path)
        and scientific_review.get("template_source", {}).get("sha256") == sha256_file(template_path)
        and scientific_review.get("candidate_source", {}).get("sha256") == sha256_file(candidate_path)
        and input_observation.get("template_source", {}).get("sha256") == sha256_file(template_path)
        and input_observation.get("candidate_source", {}).get("sha256") == sha256_file(candidate_path)
        and input_observation.get("scientific_review_source", {}).get("sha256") == sha256_file(scientific_review_path)
        and result_observation.get("template_source", {}).get("sha256") == sha256_file(template_path)
        and result_observation.get("candidate_source", {}).get("sha256") == sha256_file(candidate_path),
        "metal acceptance review input lineage is inconsistent",
    )
    for key in ("study_id", "candidate_id", "mechanism_id", "channel_id", "catalyst_state_id"):
        require(
            template.get(key) == candidate.get(key) == scientific_review.get(key)
            == input_observation.get(key) == result_observation.get(key),
            f"metal acceptance review {key} binding mismatch",
        )
    expected_order = _candidate_atom_order(candidate)
    for label, artifact, field in (
        ("template", template, "identity_binding"),
        ("scientific review", scientific_review, "identity_binding"),
        ("input observation", input_observation, "identity_binding"),
        ("result observation", result_observation, "identity_binding"),
    ):
        _require_matching_atom_order(artifact.get(field, {}).get("atom_order"), expected_order, f"metal acceptance {label}")
    charge = candidate.get("chemical_state", {}).get("charge")
    multiplicity = candidate.get("chemical_state", {}).get("multiplicity")
    require(
        template.get("identity_binding", {}).get("charge") == charge
        and scientific_review.get("identity_binding", {}).get("total_charge") == charge
        and input_observation.get("identity_binding", {}).get("charge") == charge
        and result_observation.get("identity_binding", {}).get("charge") == charge,
        "metal acceptance review charge binding mismatch",
    )
    require(
        template.get("identity_binding", {}).get("multiplicity") == multiplicity
        and scientific_review.get("identity_binding", {}).get("multiplicity") == multiplicity
        and input_observation.get("identity_binding", {}).get("multiplicity") == multiplicity
        and result_observation.get("identity_binding", {}).get("multiplicity") == multiplicity,
        "metal acceptance review multiplicity binding mismatch",
    )

    require(
        set(source) == {
            "schema", "review_id", "source_bindings", "study_id", "candidate_id",
            "mechanism_id", "channel_id", "catalyst_state_id", "scope", "sections",
        },
        "metal acceptance decision source fields are incomplete or unknown",
    )
    require(
        source.get("schema") == "gaussian-asymmetric-metal-acceptance-review-source/1",
        "metal acceptance decision source schema is not recognized",
    )
    require(ID_RE.fullmatch(str(source.get("review_id", ""))) is not None, "metal acceptance decision source review_id is invalid")
    expected_bindings = {
        "template_sha256": sha256_file(template_path),
        "candidate_sha256": sha256_file(candidate_path),
        "scientific_review_sha256": sha256_file(scientific_review_path),
        "input_observation_sha256": sha256_file(input_observation_path),
        "result_observation_sha256": sha256_file(result_observation_path),
    }
    require(source.get("source_bindings") == expected_bindings, "metal acceptance decision source hash binding mismatch")
    for key in ("study_id", "candidate_id", "mechanism_id", "channel_id", "catalyst_state_id"):
        require(source.get(key) == candidate.get(key), f"metal acceptance decision source {key} mismatch")
    scope = source.get("scope")
    require(
        isinstance(scope, dict)
        and set(scope) == {"scope_kind", "reviewer", "review_date", "notes"}
        and scope.get("scope_kind") in {"synthetic_nonresearch_fixture", "reviewer_bound_real_case"}
        and isinstance(scope.get("notes"), list),
        "metal acceptance decision source scope is invalid",
    )
    _validate_m1_scope_evidence_binding(
        scientific_review.get("review_scope", {}),
        "metal acceptance upstream M1 review",
    )
    real_scope = scope["scope_kind"] == "reviewer_bound_real_case"
    if real_scope:
        require(
            isinstance(scope.get("reviewer"), str) and scope["reviewer"].strip(),
            "real metal acceptance review requires a non-empty reviewer",
        )
        require(
            _is_valid_iso_date(scope.get("review_date")),
            "real metal acceptance review requires a valid ISO review date",
        )
        require(
            scientific_review.get("completion", {}).get("metal_m1_scientific_review_status")
            == "reviewed_bounded_example_runtime_unsupported"
            and scientific_review.get("review_scope", {}).get("scope_kind")
            in {"primary_literature_bound_review", "mixed_primary_and_reviewer_evidence"},
            "real metal acceptance review requires an upstream real non-synthetic M1 review",
        )
    sections = source.get("sections")
    require(isinstance(sections, dict) and set(sections) == set(METAL_ACCEPTANCE_SECTION_NAMES), "metal acceptance section inventory is incomplete")
    fact_fields = {
        "wavefunction": {
            "observed_s2_count", "stability_statement_observed",
            "spin_contamination_assessment", "occupation_assessment",
            "alternative_solution_assessment", "multireference_assessment",
        },
        "coordination": {
            "contact_assessments", "hapticity_assessment",
            "ligand_inventory_assessment", "unintended_state_change",
        },
        "mode": {
            "raw_imaginary_frequency_count", "mode_evidence_sha256",
            "intended_coordinate_assessment", "unintended_coordination_loss_assessment",
        },
        "input_acceptance": {
            "input_sha256", "protocol_options_sha256", "protocol_selection_sha256",
            "input_approval_sha256", "input_result_lineage_sha256",
            "exact_input_hash_confirmed", "route_reviewed",
            "element_basis_ecp_coverage_reviewed", "solvent_thermochemistry_reviewed",
            "resource_and_server_path_reviewed",
        },
    }
    decisions: dict[str, str] = {}
    for name in METAL_ACCEPTANCE_SECTION_NAMES:
        section = sections[name]
        require(
            isinstance(section, dict)
            and set(section) == {"decision", "facts", "evidence", "review_notes", "blockers"},
            f"metal acceptance {name} section fields are incomplete or unknown",
        )
        decision = section.get("decision")
        require(decision in METAL_ACCEPTANCE_DECISIONS, f"metal acceptance {name} decision is invalid")
        decisions[name] = decision
        facts = section.get("facts")
        require(isinstance(facts, dict) and set(facts) == fact_fields[name], f"metal acceptance {name} facts are incomplete or unknown")
        evidence = section.get("evidence")
        require(isinstance(evidence, list), f"metal acceptance {name} evidence must be an array")
        evidence_ids: set[str] = set()
        for item in evidence:
            require(
                isinstance(item, dict)
                and set(item) == {"evidence_id", "evidence_kind", "sha256", "locator"},
                f"metal acceptance {name} evidence record is invalid",
            )
            evidence_id = item.get("evidence_id")
            require(ID_RE.fullmatch(str(evidence_id or "")) is not None and evidence_id not in evidence_ids, f"metal acceptance {name} evidence ID is invalid or duplicate")
            evidence_ids.add(evidence_id)
            require(item.get("evidence_kind") in {"synthetic_fixture", "reviewer_record", "mode_displacement", "protocol_artifact", "input_approval", "coordination_review", "wavefunction_review"}, f"metal acceptance {name} evidence kind is invalid")
            require(
                not real_scope or item.get("evidence_kind") != "synthetic_fixture",
                f"real metal acceptance {name} section forbids synthetic_fixture evidence",
            )
            value = item.get("sha256")
            require(value is None or (isinstance(value, str) and SHA256_RE.fullmatch(value) is not None), f"metal acceptance {name} evidence SHA-256 is invalid")
            require(isinstance(item.get("locator"), str) and item["locator"].strip(), f"metal acceptance {name} evidence locator is missing")
        require(isinstance(section.get("review_notes"), str) and section["review_notes"].strip(), f"metal acceptance {name} review notes are missing")
        blockers = section.get("blockers")
        require(isinstance(blockers, list) and all(isinstance(item, str) and item.strip() for item in blockers), f"metal acceptance {name} blockers are invalid")
        if decision == "blocked_missing_evidence":
            require(blockers, f"metal acceptance {name} blocked decision lacks blockers")
        else:
            require(evidence, f"metal acceptance {name} reviewed decision lacks evidence")
            require(all(item.get("sha256") is not None for item in evidence), f"metal acceptance {name} reviewed evidence is not hash-bound")
        if decision == "accepted_for_bounded_offline_review":
            require(not blockers, f"metal acceptance {name} accepted decision retains blockers")
            m1_section = {
                "wavefunction": "wavefunction", "coordination": "coordination",
                "mode": "ts_and_path", "input_acceptance": "method_protocol",
            }[name]
            require(
                scientific_review.get("sections", {}).get(m1_section, {}).get("status") == "reviewed_for_bounded_example",
                f"metal acceptance {name} cannot be accepted while the corresponding M1 section is blocked",
            )

    wave = sections["wavefunction"]["facts"]
    observed_wave = result_observation.get("wavefunction_observations", {})
    require(wave.get("observed_s2_count") in {None, len(observed_wave.get("s2_observations", []))}, "metal acceptance wavefunction S**2 count differs from M2b")
    require(wave.get("stability_statement_observed") in {None, observed_wave.get("stability_statement_observed")}, "metal acceptance stability observation differs from M2b")
    if decisions["wavefunction"] == "accepted_for_bounded_offline_review":
        require(wave.get("stability_statement_observed") is True, "metal acceptance wavefunction requires reviewed stability evidence")
        require(all(isinstance(wave.get(key), str) and wave[key].strip() for key in ("spin_contamination_assessment", "occupation_assessment", "alternative_solution_assessment", "multireference_assessment")), "metal acceptance wavefunction accepted decision lacks assessments")

    coordination = sections["coordination"]["facts"]
    expected_contacts = result_observation.get("coordination_observations", {}).get("contacts", [])
    assessments = coordination.get("contact_assessments")
    require(isinstance(assessments, list), "metal acceptance coordination contact assessments must be an array")
    if assessments:
        normalized = [
            {key: item.get(key) for key in ("donor_atom", "acceptor_atom", "kind", "initial_distance_angstrom", "final_distance_angstrom")}
            for item in assessments
        ]
        expected = [
            {key: item.get(key) for key in ("donor_atom", "acceptor_atom", "kind", "initial_distance_angstrom", "final_distance_angstrom")}
            for item in expected_contacts
        ]
        require(normalized == expected, "metal acceptance coordination observations differ from M2b")
    if decisions["coordination"] == "accepted_for_bounded_offline_review":
        require(len(assessments) == len(expected_contacts) and all(item.get("within_reviewed_window") is True for item in assessments), "metal acceptance coordination accepted decision lacks passed contact reviews")
        require(coordination.get("unintended_state_change") is False, "metal acceptance coordination accepted an unintended state change")
        require(all(isinstance(coordination.get(key), str) and coordination[key].strip() for key in ("hapticity_assessment", "ligand_inventory_assessment")), "metal acceptance coordination accepted decision lacks inventory assessments")

    mode = sections["mode"]["facts"]
    observed_imaginary = result_observation.get("frequency_observations", {}).get("raw_imaginary_frequency_count")
    require(mode.get("raw_imaginary_frequency_count") in {None, observed_imaginary}, "metal acceptance mode frequency count differs from M2b")
    if decisions["mode"] == "accepted_for_bounded_offline_review":
        require(observed_imaginary == 1 and mode.get("raw_imaginary_frequency_count") == 1, "metal acceptance mode requires exactly one raw imaginary frequency")
        _require_sha256(mode.get("mode_evidence_sha256"), "metal acceptance mode evidence hash is missing")
        require(all(isinstance(mode.get(key), str) and mode[key].strip() for key in ("intended_coordinate_assessment", "unintended_coordination_loss_assessment")), "metal acceptance mode accepted decision lacks displacement assessments")

    input_facts = sections["input_acceptance"]["facts"]
    observed_input_sha = input_observation.get("input_source", {}).get("sha256")
    require(input_facts.get("input_sha256") in {None, observed_input_sha}, "metal acceptance input hash differs from M2c")
    if decisions["input_acceptance"] == "accepted_for_bounded_offline_review":
        for key in ("input_sha256", "protocol_options_sha256", "protocol_selection_sha256", "input_approval_sha256", "input_result_lineage_sha256"):
            _require_sha256(input_facts.get(key), f"metal acceptance input {key} is missing")
        for key in ("exact_input_hash_confirmed", "route_reviewed", "element_basis_ecp_coverage_reviewed", "solvent_thermochemistry_reviewed", "resource_and_server_path_reviewed"):
            require(input_facts.get(key) is True, f"metal acceptance input {key} was not reviewed")

    accepted = sorted(name for name, value in decisions.items() if value == "accepted_for_bounded_offline_review")
    rejected = sorted(name for name, value in decisions.items() if value == "rejected_by_reviewer")
    blocked = sorted(name for name, value in decisions.items() if value == "blocked_missing_evidence")
    all_accepted = len(accepted) == len(METAL_ACCEPTANCE_SECTION_NAMES)
    scope_kind = scope["scope_kind"]
    m2_status = (
        "not_satisfied_synthetic_fixture"
        if all_accepted and scope_kind == "synthetic_nonresearch_fixture"
        else "reviewed_bounded_example_runtime_unsupported"
        if all_accepted
        else "reviewer_rejected"
        if rejected
        else "pending_acceptance_review"
    )
    status = (
        "acceptance_record_complete_runtime_unsupported"
        if all_accepted
        else "acceptance_record_contains_rejection_runtime_unsupported"
        if rejected
        else "blocked_incomplete_acceptance_review"
    )
    review = {
        "schema": "gaussian-asymmetric-metal-acceptance-review/1",
        "review_id": source["review_id"],
        "template_source": {"sha256": sha256_file(template_path)},
        "candidate_source": {"sha256": sha256_file(candidate_path)},
        "scientific_review_source": {"sha256": sha256_file(scientific_review_path)},
        "input_observation_source": {"sha256": sha256_file(input_observation_path)},
        "result_observation_source": {"sha256": sha256_file(result_observation_path)},
        "decision_source": {"sha256": sha256_file(decision_source_path)},
        "study_id": candidate["study_id"],
        "candidate_id": candidate["candidate_id"],
        "mechanism_id": candidate["mechanism_id"],
        "channel_id": candidate["channel_id"],
        "catalyst_state_id": candidate["catalyst_state_id"],
        "status": status,
        "calculation_ready": False,
        "no_submission_authorization": True,
        "runtime_support_status": "unsupported_requires_extension",
        "scientific_acceptance_decision": "not_granted_by_artifact",
        "input_acceptance_decision": "not_granted_by_artifact",
        "mode_acceptance_decision": "not_granted_by_artifact",
        "promotion_decision": "refused",
        "submission_decision": "refused",
        "scope": copy.deepcopy(scope),
        "identity_binding": {
            "charge": charge,
            "multiplicity": multiplicity,
            "atom_count": len(expected_order),
            "atom_order": expected_order,
        },
        "sections": copy.deepcopy(sections),
        "decision_summary": {
            "accepted_sections": accepted,
            "rejected_sections": rejected,
            "blocked_sections": blocked,
            "metal_m2_acceptance_review_status": m2_status,
        },
        "completion": {
            "metal_m2d_acceptance_review_contract": "implemented_offline",
            "metal_m2_offline_runtime_contract": "blocked",
            "metal_m3_execution_boundary": "blocked",
            "metal_m4_live_smoke": "blocked",
        },
        "hard_rejections": [
            "Section-level accepted_for_bounded_offline_review records do not grant top-level scientific, input or mode acceptance.",
            "Do not promote, submit, retry, run IRC, deploy, cancel or clean up from this sidecar.",
            "Do not infer missing wavefunction, coordination, mode, method, protocol, resource or server-path evidence.",
            "A synthetic complete fixture cannot satisfy a real M2 scientific milestone.",
        ],
        "claim_ceiling": "manual_decision_record_only_no_runtime_promotion_ts_path_or_selectivity_claim",
    }
    review["review_payload_sha256"] = sha256_data(
        {key: value for key, value in review.items() if key != "review_payload_sha256"}
    )
    require(dry_run or output is not None, "build-metal-acceptance-review requires --output unless --dry-run is used")
    if not dry_run:
        assert output is not None
        write_json(output, review)
    return review


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
    ingest = sub.add_parser("ingest-result"); ingest.add_argument("candidate"); ingest.add_argument("ts_result"); ingest.add_argument("energy_record"); ingest.add_argument("--mode-review"); ingest.add_argument("--mode-decision"); ingest.add_argument("--forward-audit"); ingest.add_argument("--reverse-audit"); ingest.add_argument("--input"); ingest.add_argument("--log"); ingest.add_argument("--checkpoint"); ingest.add_argument("--checkpoint-audit"); ingest.add_argument("--irc-plan"); ingest.add_argument("--path-acceptance"); ingest.add_argument("--output", required=True)
    agg = sub.add_parser("aggregate"); agg.add_argument("study"); agg.add_argument("ledger"); agg.add_argument("results", nargs="+"); agg.add_argument("--energy-shift-kcal", type=float, default=1.0); agg.add_argument("--output", required=True)
    metal = sub.add_parser("design-metal-support"); metal.add_argument("study"); metal.add_argument("--output", required=True)
    metal_audit = sub.add_parser("build-metal-ts-audit-template"); metal_audit.add_argument("metal_support"); metal_audit.add_argument("candidate"); metal_audit.add_argument("--output", required=True)
    metal_review = sub.add_parser("build-metal-scientific-review"); metal_review.add_argument("metal_support"); metal_review.add_argument("metal_ts_audit_template"); metal_review.add_argument("candidate"); metal_review.add_argument("review_source"); metal_review.add_argument("--output"); metal_review.add_argument("--dry-run", action="store_true")
    metal_input_observation = sub.add_parser("audit-metal-input"); metal_input_observation.add_argument("metal_ts_audit_template"); metal_input_observation.add_argument("candidate"); metal_input_observation.add_argument("metal_scientific_review"); metal_input_observation.add_argument("input"); metal_input_observation.add_argument("--output"); metal_input_observation.add_argument("--dry-run", action="store_true")
    metal_observation = sub.add_parser("audit-metal-result"); metal_observation.add_argument("metal_ts_audit_template"); metal_observation.add_argument("candidate"); metal_observation.add_argument("log"); metal_observation.add_argument("--output"); metal_observation.add_argument("--dry-run", action="store_true")
    metal_acceptance = sub.add_parser("build-metal-acceptance-review"); metal_acceptance.add_argument("metal_ts_audit_template"); metal_acceptance.add_argument("candidate"); metal_acceptance.add_argument("metal_scientific_review"); metal_acceptance.add_argument("metal_input_observation"); metal_acceptance.add_argument("metal_result_observation"); metal_acceptance.add_argument("decision_source"); metal_acceptance.add_argument("--output"); metal_acceptance.add_argument("--dry-run", action="store_true")
    smoke = sub.add_parser("propose-smoke"); smoke.add_argument("ledger"); smoke.add_argument("--candidate-id", required=True); smoke.add_argument("--output", required=True)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "build-study": build_study(Path(args.source), Path(args.output))
        elif args.command == "enumerate-boron": enumerate_boron(Path(args.study), Path(args.space), Path(args.output))
        elif args.command == "build-literature-benchmark": build_literature_benchmark(Path(args.source), Path(args.output))
        elif args.command == "build-candidates": materialize_candidates(Path(args.study), Path(args.ledger), Path(args.materializations), Path(args.output_dir))
        elif args.command == "ingest-result": ingest_result(Path(args.candidate), Path(args.ts_result), Path(args.energy_record), Path(args.output), Path(args.mode_review) if args.mode_review else None, Path(args.mode_decision) if args.mode_decision else None, Path(args.forward_audit) if args.forward_audit else None, Path(args.reverse_audit) if args.reverse_audit else None, Path(args.input) if args.input else None, Path(args.log) if args.log else None, Path(args.checkpoint) if args.checkpoint else None, Path(args.checkpoint_audit) if args.checkpoint_audit else None, Path(args.irc_plan) if args.irc_plan else None, Path(args.path_acceptance) if args.path_acceptance else None)
        elif args.command == "aggregate": aggregate(Path(args.study), Path(args.ledger), [Path(item) for item in args.results], Path(args.output), args.energy_shift_kcal)
        elif args.command == "design-metal-support": design_metal_support(Path(args.study), Path(args.output))
        elif args.command == "build-metal-ts-audit-template": build_metal_ts_audit_template(Path(args.metal_support), Path(args.candidate), Path(args.output))
        elif args.command == "build-metal-scientific-review":
            review = build_metal_scientific_review(
                Path(args.metal_support),
                Path(args.metal_ts_audit_template),
                Path(args.candidate),
                Path(args.review_source),
                Path(args.output) if args.output else None,
                args.dry_run,
            )
            if args.dry_run:
                print(json.dumps({
                    "valid": True,
                    "dry_run": True,
                    "schema": review["schema"],
                    "status": review["status"],
                    "metal_m1_scientific_review_status": review["completion"]["metal_m1_scientific_review_status"],
                    "scientific_acceptance_decision": review["scientific_acceptance_decision"],
                    "promotion_decision": review["promotion_decision"],
                    "submission_decision": review["submission_decision"],
                    "would_write": str(args.output) if args.output else None,
                    "live_actions": False,
                }, indent=2))
        elif args.command == "audit-metal-input":
            observation = audit_metal_input_observation(
                Path(args.metal_ts_audit_template),
                Path(args.candidate),
                Path(args.metal_scientific_review),
                Path(args.input),
                Path(args.output) if args.output else None,
                args.dry_run,
            )
            if args.dry_run:
                print(json.dumps({
                    "valid": True,
                    "dry_run": True,
                    "schema": observation["schema"],
                    "status": observation["status"],
                    "input_acceptance_decision": observation["input_acceptance_decision"],
                    "promotion_decision": observation["promotion_decision"],
                    "submission_decision": observation["submission_decision"],
                    "would_write": str(args.output) if args.output else None,
                    "live_actions": False,
                }, indent=2))
        elif args.command == "audit-metal-result":
            observation = audit_metal_result_observation(
                Path(args.metal_ts_audit_template),
                Path(args.candidate),
                Path(args.log),
                Path(args.output) if args.output else None,
                args.dry_run,
            )
            if args.dry_run:
                print(json.dumps({
                    "valid": True,
                    "dry_run": True,
                    "schema": observation["schema"],
                    "status": observation["status"],
                    "promotion_decision": observation["promotion_decision"],
                    "submission_decision": observation["submission_decision"],
                    "would_write": str(args.output) if args.output else None,
                    "live_actions": False,
                }, indent=2))
        elif args.command == "build-metal-acceptance-review":
            review = build_metal_acceptance_review(
                Path(args.metal_ts_audit_template),
                Path(args.candidate),
                Path(args.metal_scientific_review),
                Path(args.metal_input_observation),
                Path(args.metal_result_observation),
                Path(args.decision_source),
                Path(args.output) if args.output else None,
                args.dry_run,
            )
            if args.dry_run:
                print(json.dumps({
                    "valid": True,
                    "dry_run": True,
                    "schema": review["schema"],
                    "status": review["status"],
                    "metal_m2_acceptance_review_status": review["decision_summary"]["metal_m2_acceptance_review_status"],
                    "scientific_acceptance_decision": review["scientific_acceptance_decision"],
                    "input_acceptance_decision": review["input_acceptance_decision"],
                    "mode_acceptance_decision": review["mode_acceptance_decision"],
                    "promotion_decision": review["promotion_decision"],
                    "submission_decision": review["submission_decision"],
                    "would_write": str(args.output) if args.output else None,
                    "live_actions": False,
                }, indent=2))
        elif args.command == "propose-smoke": propose_smoke(Path(args.ledger), args.candidate_id, Path(args.output))
        else: raise AssertionError(args.command)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
