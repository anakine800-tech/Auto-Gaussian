#!/usr/bin/env python3
"""Standard-library core for non-executable dual-route conformer audits."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import math
import os
import re
import shutil
from pathlib import Path
from typing import Any, Iterable


SCHEMAS = {
    "request": "gaussian-conformer-search-request/1",
    "dependencies": "gaussian-conformer-dependency-diagnostic/1",
    "freedom": "gaussian-conformer-freedom-analysis/1",
    "plan": "gaussian-conformer-search-plan/1",
    "candidates": "gaussian-conformer-candidate-set/1",
    "ledger": "gaussian-conformer-validity-ledger/1",
    "manifest": "gaussian-conformer-ensemble-manifest/1",
    "handoff": "gaussian-conformer-candidate-handoff/1",
}
ID_RE = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
HASH_RE = re.compile(r"^[a-f0-9]{64}$")
ROUTES = {"route_a", "route_b"}
SUBROUTES = {"a1_crest", "a2_xtb_md", "b1_etkdg", "b2_directed"}
SUBROUTE_ROUTE = {
    "a1_crest": "route_a",
    "a2_xtb_md": "route_a",
    "b1_etkdg": "route_b",
    "b2_directed": "route_b",
}
UNSUPPORTED_FLAGS = (
    "transition_metal",
    "open_shell",
    "excited_state",
    "multireference",
    "unknown_coordination",
    "connectivity_change_expected",
)


def _resource_path(*parts: str) -> Path:
    """Resolve repository or deployed-Skill resources without network access."""
    script = Path(__file__).resolve()
    candidates = (
        script.parents[3].joinpath(*parts),
        script.parents[1].joinpath(*parts),
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise RuntimeError(f"required packaged resource is unavailable: {'/'.join(parts)}")


def _load_schema_validator() -> Any:
    candidates = (
        Path(__file__).resolve().with_name("validate_asymmetric_contract.py"),
        _resource_path("scripts", "validate_asymmetric_contract.py"),
    )
    path = next((candidate for candidate in candidates if candidate.is_file()), None)
    if path is None:
        raise RuntimeError("packaged JSON Schema validator is unavailable")
    spec = importlib.util.spec_from_file_location("auto_g16_conformer_schema_validator", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load JSON Schema validator: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SCHEMA_VALIDATOR = _load_schema_validator()
CONTRACT_DIR = _resource_path("contracts", "conformer-search")


class ContractError(ValueError):
    """Raised when an offline artifact fails closed."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def validate_schema(value: dict[str, Any], filename: str) -> None:
    """Apply the packaged fail-closed JSON Schema subset."""
    schema = load_json(CONTRACT_DIR / filename)
    try:
        SCHEMA_VALIDATOR.validate_schema_document(schema)
        SCHEMA_VALIDATOR._validate_schema_instance(value, schema, schema)
    except Exception as exc:
        raise ContractError(f"{filename}: schema validation failed: {exc}") from exc


def _constant(value: str) -> None:
    raise ContractError(f"non-standard JSON numeric constant is forbidden: {value}")


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON key is forbidden: {key}")
        result[key] = value
    return result


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=_constant,
            object_pairs_hook=_object,
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read JSON {path}: {exc}") from exc
    require(isinstance(value, dict), f"JSON root must be an object: {path}")
    return value


def canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        + "\n"
    ).encode("utf-8")


def payload_sha256(value: dict[str, Any]) -> str:
    payload = copy.deepcopy(value)
    payload.pop("payload_sha256", None)
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_new_json(path: Path, value: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    except FileExistsError as exc:
        raise ContractError(f"refusing to overwrite existing output: {path}") from exc


def binding(path: Path, schema: str, *, payload: str | None = None) -> dict[str, Any]:
    path = path.expanduser().resolve()
    result = {
        "path": str(path),
        "sha256": file_sha256(path),
        "size_bytes": path.stat().st_size,
        "schema": schema,
    }
    if payload is not None:
        result["payload_sha256"] = payload
    return result


def verify_binding(record: dict[str, Any], path: Path, schema: str) -> None:
    path = path.expanduser().resolve()
    require(record.get("schema") == schema, "bound artifact schema differs")
    require(record.get("path") == str(path), "bound artifact path differs")
    require(record.get("sha256") == file_sha256(path), "bound artifact SHA-256 differs")
    require(record.get("size_bytes") == path.stat().st_size, "bound artifact size differs")


def resolve_bound_path(owner_path: Path, raw_path: Any, label: str) -> Path:
    require(isinstance(raw_path, str) and raw_path, f"{label} path is required")
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = owner_path.expanduser().resolve().parent / candidate
    require(not candidate.is_symlink(), f"{label} must not be a symlink")
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise ContractError(f"{label} is unavailable: {candidate}") from exc
    require(resolved.is_file(), f"{label} must be a regular file")
    return resolved


def verify_document_matches_path(document: dict[str, Any], path: Path, label: str) -> None:
    require(not path.is_symlink() and path.is_file(), f"{label} must be an existing non-symlink file")
    require(load_json(path) == document, f"{label} in-memory content differs from bound file")


def _id(value: Any, label: str) -> str:
    require(isinstance(value, str) and ID_RE.fullmatch(value) is not None, f"{label} must be a safe ID")
    return value


def _finite(value: Any, label: str) -> float:
    require(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value), f"{label} must be finite")
    return float(value)


def _hash(value: Any, label: str) -> str:
    require(isinstance(value, str) and HASH_RE.fullmatch(value) is not None, f"{label} must be SHA-256")
    return value


def normalize_bond(bond: dict[str, Any]) -> tuple[int, int, float]:
    atoms = bond.get("atoms")
    require(isinstance(atoms, list) and len(atoms) == 2, "bond atoms must contain two indices")
    left, right = atoms
    require(isinstance(left, int) and isinstance(right, int) and left != right, "bond indices are invalid")
    order = _finite(bond.get("order"), "bond order")
    require(order in {1.0, 1.5, 2.0, 3.0}, "bond order is unsupported")
    return min(left, right), max(left, right), order


def validate_request(request: dict[str, Any], request_path: Path) -> None:
    validate_schema(request, "request.schema.json")
    verify_document_matches_path(request, request_path, "conformer-search request")
    require(request.get("schema") == SCHEMAS["request"], "unsupported request schema")
    _id(request.get("request_id"), "request_id")
    revision = request.get("revision")
    require(isinstance(revision, dict), "revision is required")
    _id(revision.get("revision_id"), "revision_id")
    supersedes = revision.get("supersedes")
    if supersedes is not None:
        require(isinstance(supersedes, dict), "supersedes must be an artifact binding or null")
        _hash(supersedes.get("sha256"), "supersedes sha256")
        _hash(supersedes.get("payload_sha256"), "supersedes payload_sha256")
    handoff = request.get("r08_handoff")
    require(isinstance(handoff, dict) and handoff.get("immutable") is True and handoff.get("reviewed") is True, "R08 handoff must be immutable and reviewed")
    _hash(handoff.get("sha256"), "R08 handoff sha256")
    r08_path = resolve_bound_path(request_path, handoff.get("path"), "R08 handoff")
    require(file_sha256(r08_path) == handoff["sha256"], "R08 handoff SHA-256 differs")
    r08_document = load_json(r08_path)
    require(r08_document.get("schema") == handoff.get("schema"), "R08 handoff schema differs")
    state = request.get("state")
    require(isinstance(state, dict), "state is required")
    _id(state.get("state_id"), "state_id")
    atoms = state.get("atoms")
    require(isinstance(atoms, list) and len(atoms) >= 2, "state requires at least two atoms")
    atom_ids: list[str] = []
    map_ids: list[str] = []
    indices: list[int] = []
    fragment_ids: set[str] = set()
    for atom in atoms:
        require(isinstance(atom, dict), "atom must be an object")
        atom_ids.append(_id(atom.get("atom_id"), "atom_id"))
        map_ids.append(_id(atom.get("map_id"), "map_id"))
        index = atom.get("atom_index")
        require(isinstance(index, int) and not isinstance(index, bool), "atom_index must be integer")
        indices.append(index)
        require(isinstance(atom.get("element"), str) and re.fullmatch(r"[A-Z][a-z]?", atom["element"]) is not None, "atom element is invalid")
        fragment_ids.add(_id(atom.get("fragment_id"), "fragment_id"))
        require(isinstance(atom.get("explicit_hydrogen"), bool), "explicit_hydrogen must be boolean")
    require(indices == list(range(len(atoms))), "atom_index must be contiguous and ordered")
    require(len(set(atom_ids)) == len(atom_ids) and len(set(map_ids)) == len(map_ids), "atom_id and map_id must be unique")
    require(state.get("component_count") == len(fragment_ids), "component_count differs from atom fragments")
    require(isinstance(state.get("formal_charge"), int) and not isinstance(state["formal_charge"], bool), "formal_charge must be integer")
    require(isinstance(state.get("multiplicity"), int) and state["multiplicity"] >= 1, "multiplicity must be positive integer")
    bonds = state.get("bonds")
    require(isinstance(bonds, list), "state bonds must be a list")
    normalized = [normalize_bond(bond) for bond in bonds]
    require(len(set(normalized)) == len(normalized), "state bonds contain duplicates")
    require(all(0 <= a < len(atoms) and 0 <= b < len(atoms) for a, b, _ in normalized), "state bond index is out of range")
    flags = state.get("unsupported_flags")
    require(isinstance(flags, dict) and set(flags) == set(UNSUPPORTED_FLAGS), "unsupported_flags must be explicit and closed")
    require(all(isinstance(flags[key], bool) for key in UNSUPPORTED_FLAGS), "unsupported flags must be boolean")
    categories = request.get("categories")
    require(isinstance(categories, list) and categories, "at least one category is required")
    category_ids = []
    for category in categories:
        require(isinstance(category, dict), "category must be an object")
        category_ids.append(_id(category.get("category_id"), "category_id"))
        require(isinstance(category.get("labels"), list) and category["labels"], "category labels are required")
        require(isinstance(category.get("total_quota"), int) and category["total_quota"] >= 2, "category total_quota must be at least two")
        constraints = category.get("constraints")
        require(isinstance(constraints, dict), "category constraints are required")
        for key in ("required_bonds", "forbidden_bonds"):
            require(isinstance(constraints.get(key), list), f"{key} must be a list")
            for pair in constraints[key]:
                require(isinstance(pair, list) and len(pair) == 2 and all(isinstance(index, int) for index in pair), f"{key} contains an invalid pair")
        descriptors = constraints.get("descriptor_constraints")
        require(isinstance(descriptors, list), "descriptor_constraints must be a list")
        for descriptor in descriptors:
            require(isinstance(descriptor, dict), "descriptor constraint must be an object")
            _id(descriptor.get("descriptor_id"), "descriptor_id")
            require(descriptor.get("kind") in {"distance", "angle", "dihedral", "centroid_distance", "plane_angle", "lateral_slip", "contact", "custom"}, "descriptor kind is unsupported")
            minimum = _finite(descriptor.get("minimum"), "descriptor minimum")
            maximum = _finite(descriptor.get("maximum"), "descriptor maximum")
            require(minimum <= maximum, "descriptor range is inverted")
    require(len(set(category_ids)) == len(category_ids), "category IDs must be unique")
    freedom = request.get("freedom_inputs")
    require(isinstance(freedom, dict), "freedom_inputs are required")
    for key in ("flexible_ring_count", "relative_constraints"):
        require(isinstance(freedom.get(key), int) and freedom[key] >= 0, f"{key} must be non-negative integer")
    for key in ("weak_interaction_types", "face_ids", "symmetry_classes"):
        require(isinstance(freedom.get(key), list), f"{key} must be a list")
    policy = request.get("quota_policy")
    require(isinstance(policy, dict) and policy.get("locked_before_results") is True and policy.get("reviewed") is True, "quota weights must be reviewed and locked before results")
    route_weights = policy.get("route_weights")
    require(isinstance(route_weights, dict) and set(route_weights) == ROUTES, "route_weights must define route_a and route_b")
    require(abs(sum(_finite(route_weights[key], key) for key in ROUTES) - 1.0) < 1e-9, "route weights must sum to one")
    require(all(0.25 <= route_weights[key] <= 0.75 for key in ROUTES), "each route weight must be between 0.25 and 0.75")
    subroute_weights = policy.get("subroute_weights")
    require(isinstance(subroute_weights, dict) and set(subroute_weights) == SUBROUTES, "all four subroute weights are required")
    for route, children in (("route_a", ("a1_crest", "a2_xtb_md")), ("route_b", ("b1_etkdg", "b2_directed"))):
        require(abs(sum(_finite(subroute_weights[key], key) for key in children) - 1.0) < 1e-9, f"{route} subroute weights must sum to one")
    protocol = request.get("shared_xtb_protocol")
    require(isinstance(protocol, dict), "shared_xtb_protocol is required")
    for key in ("method", "solvent_model", "optimization_convergence", "constraint_release_strategy"):
        require(isinstance(protocol.get(key), str) and protocol[key], f"shared xTB {key} must be explicit")
    require(protocol.get("formal_charge") == state["formal_charge"], "xTB charge differs from state")
    require(protocol.get("multiplicity") == state["multiplicity"], "xTB multiplicity differs from state")
    adapters = request.get("adapters")
    require(isinstance(adapters, list) and {item.get("subroute_id") for item in adapters if isinstance(item, dict)} == SUBROUTES, "exactly four adapters are required")
    for adapter in adapters:
        require(adapter.get("route_id") == SUBROUTE_ROUTE[adapter["subroute_id"]], "subroute belongs to wrong route")
        require(adapter.get("execution_approved") is False, "adapter execution_approved must be false")
        require(isinstance(adapter.get("random_seeds"), list) and adapter["random_seeds"], "adapter random seeds are required")
        require(all(isinstance(seed, int) and not isinstance(seed, bool) for seed in adapter["random_seeds"]), "random seeds must be integers")
        require(isinstance(adapter.get("argv_template"), list), "adapter argv_template must be a list")
        settings = adapter.get("settings")
        require(isinstance(settings, dict), "adapter settings are required")
        subroute = adapter["subroute_id"]
        if subroute == "a1_crest":
            require(settings.get("sampling_mode") == "enhanced_sampling" and isinstance(settings.get("trajectory_count"), int) and settings["trajectory_count"] >= 1, "A1 enhanced-sampling settings are incomplete")
            require(settings.get("candidate_output") == "complete_candidate_set", "A1 must request the complete candidate set")
        elif subroute == "a2_xtb_md":
            require(isinstance(settings.get("temperature_schedule"), list) and settings["temperature_schedule"], "A2 temperature schedule is required")
            require(_finite(settings.get("time_step_fs"), "A2 time step") > 0 and _finite(settings.get("trajectory_length_ps"), "A2 trajectory length") > 0, "A2 time settings must be positive")
            require(isinstance(settings.get("thermostat"), str) and settings["thermostat"], "A2 thermostat is required")
            require(isinstance(settings.get("initial_structure_ref"), str) and settings["initial_structure_ref"], "A2 initial structure is required")
        elif subroute == "b1_etkdg":
            require(settings.get("embedding_method") == "ETKDGv3" and settings.get("enforce_chirality") is True, "B1 must use chirality-preserving ETKDGv3")
            require(settings.get("force_field_policy") == "MMFF94s_if_complete_else_UFF" and settings.get("record_parameter_completeness") is True and settings.get("record_convergence") is True, "B1 force-field audit settings are incomplete")
        elif subroute == "b2_directed":
            require(settings.get("directed_generator") == "configuration_driven" and set(settings.get("category_ids", [])) == set(category_ids), "B2 must bind every reviewed category through configuration")
    for dependency, configured_path in request.get("dependency_paths", {}).items():
        if configured_path is not None:
            require(isinstance(configured_path, str) and os.path.isabs(configured_path), f"configured {dependency} path must be absolute")
    similarity = request.get("similarity")
    require(isinstance(similarity, dict), "similarity configuration is required")
    weights = similarity.get("weights")
    expected_weights = {"mapped_rmsd", "symmetry_rmsd", "key_distance", "torsion", "contact", "fragment", "aromatic", "custom"}
    require(isinstance(weights, dict) and set(weights) == expected_weights, "similarity weights are incomplete")
    require(all(_finite(weights[key], key) >= 0 for key in weights) and sum(weights.values()) > 0, "similarity weights must be non-negative and nonzero")
    thresholds = similarity.get("thresholds")
    require(isinstance(thresholds, dict), "similarity thresholds are required")
    for key in ("duplicate_rmsd", "duplicate_key_distance", "high_rmsd", "high_key_distance", "boundary_rmsd", "minimum_contact_similarity"):
        _finite(thresholds.get(key), key)
    for permutation in similarity.get("symmetry_permutations", []):
        require(isinstance(permutation, list) and sorted(permutation) == list(range(len(atoms))), "symmetry permutation must be a complete atom-index bijection")
        require([atoms[index]["element"] for index in permutation] == [atom["element"] for atom in atoms], "symmetry permutation must preserve elements")
    reviews = request.get("reviews")
    require(isinstance(reviews, dict) and reviews and all(value is True for value in reviews.values()), "all request review flags must be true")


def analyze_freedom(request: dict[str, Any], request_path: Path) -> dict[str, Any]:
    validate_request(request, request_path)
    state = request["state"]
    atoms = state["atoms"]
    bonds = state["bonds"]
    degrees = [0] * len(atoms)
    heavy_degrees = [0] * len(atoms)
    normalized = [normalize_bond(bond) for bond in bonds]
    for left, right, _order in normalized:
        degrees[left] += 1
        degrees[right] += 1
        if atoms[left]["element"] != "H" and atoms[right]["element"] != "H":
            heavy_degrees[left] += 1
            heavy_degrees[right] += 1
    rotatable = []
    exclusions = []
    for index, (left, right, order) in enumerate(normalized):
        reason = None
        bond = bonds[index]
        if order != 1.0:
            reason = "non_single"
        elif bond.get("in_ring") is True:
            reason = "ring_bond"
        elif atoms[left]["element"] == "H" or atoms[right]["element"] == "H":
            reason = "hydrogen_bond"
        elif heavy_degrees[left] <= 1 or heavy_degrees[right] <= 1:
            reason = "terminal_heavy_atom"
        elif _amide_like(left, right, atoms, normalized) or _amide_like(right, left, atoms, normalized):
            reason = "amide_like"
        record = {"bond_index": index, "atoms": [left, right]}
        (exclusions if reason else rotatable).append({**record, **({"reason": reason} if reason else {})})
    fi = request["freedom_inputs"]
    fragment_count = state["component_count"]
    vector = {
        "n_rot": len(rotatable),
        "n_ring": fi["flexible_ring_count"],
        "d_relative": max(0, 6 * (fragment_count - 1) - fi["relative_constraints"]),
        "n_weak": len(fi["weak_interaction_types"]),
        "n_face": len(fi["face_ids"]),
        "n_symmetry": sum(max(0, len(group) - 1) for group in fi["symmetry_classes"]),
    }
    score = vector["n_rot"] + 2 * vector["n_ring"] + vector["d_relative"] + vector["n_weak"] + vector["n_face"] + vector["n_symmetry"]
    ion_pair = any("ion_pair" in label for category in request["categories"] for label in category["labels"])
    flexibility_class, route_weights, sub_a = recommend_route_policy(vector, fragment_count, ion_pair)
    directed = len(request["categories"]) > 1 or vector["n_weak"] > 0 or vector["n_face"] > 0
    sub_b = {"b1_etkdg": 0.5 if directed else 0.75, "b2_directed": 0.5 if directed else 0.25}
    suggested_total = max(
        sum(category["total_quota"] for category in request["categories"]),
        min(500, 12 + 4 * vector["n_rot"] + 6 * vector["n_ring"] + 3 * vector["d_relative"] + 2 * (vector["n_weak"] + vector["n_face"] + vector["n_symmetry"])),
    )
    blockers = [f"unsupported state flag: {key}" for key in UNSUPPORTED_FLAGS if state["unsupported_flags"][key]]
    analysis = {
        "schema": SCHEMAS["freedom"],
        "analysis_id": request["request_id"] + "_freedom",
        "request": binding(request_path, SCHEMAS["request"]),
        "vector": vector,
        "rotatable_bonds": rotatable,
        "rotatable_exclusions": exclusions,
        "mechanism_category_count": len(request["categories"]),
        "flexibility_class": flexibility_class,
        "complexity_score": score,
        "suggested_total_candidates": suggested_total,
        "recommended_route_weights": route_weights,
        "recommended_subroute_weights": {**sub_a, **sub_b},
        "minimum_category_coverage": [
            {"category_id": category["category_id"], "route_a_minimum": 1, "route_b_minimum": 1}
            for category in request["categories"]
        ],
        "basis": [
            "D_relative is a search-complexity indicator, not a vibrational degree-of-freedom count.",
            "Recommendations are heuristic and do not replace preregistered reviewed weights.",
        ],
        "limitations": [
            "Ring modes, faces, weak interactions, and symmetry classes are reviewed inputs rather than inferred chemistry.",
            "Axial chirality and coordination changes require separate review.",
        ],
        "blockers": blockers,
        "supported": not blockers,
        "calculation_ready": False,
        "no_submission_authorization": True,
    }
    analysis["payload_sha256"] = payload_sha256(analysis)
    return analysis


def recommend_route_policy(vector: dict[str, int], fragment_count: int, ion_pair: bool) -> tuple[str, dict[str, float], dict[str, float]]:
    """Return heuristic A/B and A1/A2 recommendations without selecting them."""
    score = vector["n_rot"] + 2 * vector["n_ring"] + vector["d_relative"] + vector["n_weak"] + vector["n_face"] + vector["n_symmetry"]
    if ion_pair or score >= 18:
        return "very_high", {"route_a": 0.75, "route_b": 0.25}, {"a1_crest": 0.35, "a2_xtb_md": 0.65}
    elif fragment_count > 1 or score >= 10:
        return "high", {"route_a": 0.67, "route_b": 0.33}, {"a1_crest": 0.4, "a2_xtb_md": 0.6}
    elif score >= 4:
        return "moderate", {"route_a": 0.5, "route_b": 0.5}, {"a1_crest": 0.65, "a2_xtb_md": 0.35}
    return "low", {"route_a": 0.35, "route_b": 0.65}, {"a1_crest": 0.75, "a2_xtb_md": 0.25}


def _amide_like(carbon: int, nitrogen: int, atoms: list[dict[str, Any]], bonds: list[tuple[int, int, float]]) -> bool:
    if atoms[carbon]["element"] != "C" or atoms[nitrogen]["element"] != "N":
        return False
    return any(order == 2.0 and carbon in (left, right) and atoms[right if left == carbon else left]["element"] in {"O", "S"} for left, right, order in bonds)


def dependency_diagnostic(request: dict[str, Any], request_path: Path) -> dict[str, Any]:
    validate_request(request, request_path)
    configured = request.get("dependency_paths", {})
    executable_names = {"xtb": "xtb", "crest": "crest", "openbabel": "obabel"}
    python_modules = {"rdkit": "rdkit", "spyrmsd": "spyrmsd", "numpy": "numpy", "scipy": "scipy", "scikit_learn": "sklearn", "mdanalysis": "MDAnalysis", "mdtraj": "mdtraj"}
    records = []
    for dependency, executable in executable_names.items():
        configured_path = configured.get(dependency)
        found = str(Path(configured_path).expanduser().resolve()) if isinstance(configured_path, str) and configured_path else shutil.which(executable)
        records.append({
            "dependency": dependency,
            "kind": "executable",
            "available": bool(found and Path(found).is_file()),
            "absolute_path": found if found and os.path.isabs(found) else None,
            "version": None,
            "capability_probe": "not_executed_by_policy",
            "installation_attempted": False,
        })
    for dependency, module in python_modules.items():
        available = importlib.util.find_spec(module) is not None
        records.append({
            "dependency": dependency,
            "kind": "python_module",
            "available": available,
            "absolute_path": None,
            "version": None,
            "capability_probe": "module_spec_only_no_import",
            "installation_attempted": False,
        })
    diagnostic = {
        "schema": SCHEMAS["dependencies"],
        "diagnostic_id": request["request_id"] + "_dependencies",
        "request": binding(request_path, SCHEMAS["request"]),
        "dependencies": records,
        "execution_performed": False,
        "installation_performed": False,
        "blockers": [f"missing dependency: {item['dependency']}" for item in records if not item["available"]],
        "no_submission_authorization": True,
    }
    diagnostic["payload_sha256"] = payload_sha256(diagnostic)
    return diagnostic


def allocate_weighted(total: int, weights: dict[str, float], *, minimum: int = 1) -> dict[str, int]:
    require(total >= minimum * len(weights), "quota is too small for minimum route coverage")
    require(all(weight >= 0 for weight in weights.values()) and sum(weights.values()) > 0, "quota weights are invalid")
    normalized = {key: weights[key] / sum(weights.values()) for key in weights}
    result = {key: minimum for key in weights}
    while sum(result.values()) < total:
        key = min(result, key=lambda item: (result[item] - total * normalized[item], item))
        result[key] += 1
    return dict(sorted(result.items()))


def build_plan(request: dict[str, Any], request_path: Path) -> dict[str, Any]:
    verify_supersedes(request["revision"], request_path)
    freedom = analyze_freedom(request, request_path)
    policy = request["quota_policy"]
    route_weights = policy["route_weights"]
    sub_weights = policy["subroute_weights"]
    category_quotas = []
    for category in request["categories"]:
        routes = allocate_weighted(category["total_quota"], route_weights)
        subroutes = {}
        for route, children in (("route_a", ("a1_crest", "a2_xtb_md")), ("route_b", ("b1_etkdg", "b2_directed"))):
            subroutes.update(allocate_weighted(routes[route], {child: sub_weights[child] for child in children}, minimum=0 if routes[route] < 2 else 1))
        category_quotas.append({"category_id": category["category_id"], "total_quota": category["total_quota"], "route_quotas": routes, "subroute_quotas": dict(sorted(subroutes.items()))})
    adapters = []
    for adapter in sorted(request["adapters"], key=lambda item: item["subroute_id"]):
        adapters.append({
            "route_id": adapter["route_id"],
            "subroute_id": adapter["subroute_id"],
            "required_dependencies": adapter["required_dependencies"],
            "random_seeds": adapter["random_seeds"],
            "argv_template": adapter["argv_template"],
            "environment": adapter["environment"],
            "settings": copy.deepcopy(adapter["settings"]),
            "execution_allowed": False,
            "command_review_status": "inert_reviewed_template",
        })
    plan = {
        "schema": SCHEMAS["plan"],
        "plan_id": request["request_id"] + "_plan",
        "revision": copy.deepcopy(request["revision"]),
        "request": binding(request_path, SCHEMAS["request"]),
        "r08_handoff": copy.deepcopy(request["r08_handoff"]),
        "state_signature": state_signature(request["state"]),
        "freedom_analysis": freedom,
        "locked_route_weights": copy.deepcopy(route_weights),
        "locked_subroute_weights": copy.deepcopy(sub_weights),
        "category_quotas": category_quotas,
        "category_contracts": [
            {"category_id": category["category_id"], **copy.deepcopy(category["constraints"])}
            for category in request["categories"]
        ],
        "quota_credit_definition": "legal_xtb_converged_route_internal_independent_structures",
        "shared_xtb_protocol": copy.deepcopy(request["shared_xtb_protocol"]),
        "adapters": adapters,
        "similarity": copy.deepcopy(request["similarity"]),
        "dry_run": True,
        "execution_allowed": False,
        "external_execution_performed": False,
        "calculation_ready": False,
        "no_submission_authorization": True,
        "blockers": [
            *freedom["blockers"],
            "dependency versions and version-specific capabilities are not bound to this dry-run plan",
            "external adapter execution requires a separate future authorization and implementation",
        ],
    }
    plan["payload_sha256"] = payload_sha256(plan)
    return plan


def verify_supersedes(revision: dict[str, Any], request_path: Path) -> None:
    supersedes = revision.get("supersedes")
    if supersedes is None:
        return
    previous = Path(supersedes["path"]).expanduser()
    if not previous.is_absolute():
        previous = request_path.expanduser().resolve().parent / previous
    require(previous.is_file() and not previous.is_symlink(), "superseded artifact must be an existing regular non-symlink file")
    require(file_sha256(previous) == supersedes["sha256"], "superseded artifact file hash differs")
    document = load_json(previous)
    require(document.get("payload_sha256") == supersedes["payload_sha256"], "superseded artifact payload hash differs")
    require(document.get("payload_sha256") == payload_sha256(document), "superseded artifact payload is invalid")


def state_signature(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "state_id": state["state_id"],
        "identity": state["identity"],
        "atom_order": [atom["map_id"] for atom in state["atoms"]],
        "elements": [atom["element"] for atom in state["atoms"]],
        "fragment_ids": [atom["fragment_id"] for atom in state["atoms"]],
        "explicit_hydrogens": [atom["explicit_hydrogen"] for atom in state["atoms"]],
        "bonds": [list(item) for item in sorted(normalize_bond(bond) for bond in state["bonds"])],
        "formal_charge": state["formal_charge"],
        "multiplicity": state["multiplicity"],
        "component_count": state["component_count"],
        "stereochemistry": state["stereochemistry"],
        "state_labels": state["state_labels"],
    }


def validate_plan(plan: dict[str, Any], plan_path: Path) -> None:
    validate_schema(plan, "search-plan.schema.json")
    verify_document_matches_path(plan, plan_path, "conformer-search plan")
    require(plan.get("schema") == SCHEMAS["plan"], "unsupported plan schema")
    require(plan.get("payload_sha256") == payload_sha256(plan), "plan payload hash is invalid")
    require(plan.get("dry_run") is True and plan.get("execution_allowed") is False, "plan execution boundary is invalid")
    require(plan.get("calculation_ready") is False and plan.get("no_submission_authorization") is True, "plan authority boundary is invalid")
    request_record = plan.get("request")
    require(isinstance(request_record, dict), "plan request binding is required")
    request_path = resolve_bound_path(plan_path, request_record.get("path"), "bound conformer-search request")
    verify_binding(request_record, request_path, SCHEMAS["request"])
    request = load_json(request_path)
    validate_request(request, request_path)
    require(plan == build_plan(request, request_path), "plan does not match a fresh semantic rebuild from its bound request")


def audit_candidates(plan: dict[str, Any], plan_path: Path, candidates: dict[str, Any], candidates_path: Path) -> dict[str, Any]:
    validate_plan(plan, plan_path)
    validate_schema(candidates, "candidate-set.schema.json")
    verify_document_matches_path(candidates, candidates_path, "conformer candidate set")
    require(candidates.get("schema") == SCHEMAS["candidates"], "unsupported candidate-set schema")
    require(candidates.get("plan_sha256") == file_sha256(plan_path), "candidate set is not bound to exact plan")
    expected = plan["state_signature"]
    quota_categories = {item["category_id"] for item in plan["category_quotas"]}
    require(candidates.get("category_contracts") == plan["category_contracts"], "candidate-set category contracts differ from the plan")
    entries = []
    seen_ids: set[str] = set()
    for candidate in candidates.get("candidates", []):
        candidate_id = _id(candidate.get("candidate_id"), "candidate_id")
        require(candidate_id not in seen_ids, "candidate IDs must be unique")
        seen_ids.add(candidate_id)
        reasons: list[str] = []
        state_change: list[str] = []
        route_id, subroute_id = candidate.get("route_id"), candidate.get("subroute_id")
        require(route_id in ROUTES and subroute_id in SUBROUTES and SUBROUTE_ROUTE[subroute_id] == route_id, "candidate route/subroute is invalid")
        category_id = candidate.get("category_id")
        require(category_id in quota_categories, "candidate category is not planned")
        if candidate.get("atom_order") != expected["atom_order"]:
            reasons.append("mapping_or_atom_order_drift")
        if candidate.get("elements") != expected["elements"]:
            state_change.append("element_inventory_changed")
        if candidate.get("fragment_ids") != expected["fragment_ids"]:
            state_change.append("fragment_or_explicit_h_ownership_changed")
        if candidate.get("explicit_hydrogens") != expected["explicit_hydrogens"]:
            state_change.append("explicit_hydrogen_identity_changed")
        observed_bonds = [list(item) for item in sorted(normalize_bond(bond) for bond in candidate.get("observed_bonds", []))]
        if observed_bonds != expected["bonds"]:
            state_change.append("molecular_graph_changed")
        if candidate.get("formal_charge") != expected["formal_charge"]:
            state_change.append("formal_charge_changed")
        if candidate.get("multiplicity") != expected["multiplicity"]:
            state_change.append("multiplicity_changed")
        if candidate.get("component_count") != expected["component_count"]:
            state_change.append("component_count_changed")
        if candidate.get("stereochemistry") != expected["stereochemistry"]:
            state_change.append("stereochemistry_changed")
        if candidate.get("state_labels") != expected["state_labels"]:
            state_change.append("state_labels_changed")
        coordinates = candidate.get("coordinates_angstrom")
        if not isinstance(coordinates, list) or len(coordinates) != len(expected["atom_order"]):
            reasons.append("coordinate_atom_count_mismatch")
        else:
            if not all(isinstance(point, list) and len(point) == 3 and all(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) for value in point) for point in coordinates):
                reasons.append("nonfinite_or_malformed_coordinates")
            elif minimum_distance(coordinates) < float(candidates["audit_policy"]["minimum_distance_angstrom"]):
                reasons.append("atom_collision")
        category = next(item for item in candidates["category_contracts"] if item["category_id"] == category_id)
        bond_pairs = {tuple(item[:2]) for item in observed_bonds}
        for pair in category["required_bonds"]:
            if tuple(sorted(pair)) not in bond_pairs:
                state_change.append("required_connection_missing")
        for pair in category["forbidden_bonds"]:
            if tuple(sorted(pair)) in bond_pairs:
                state_change.append("forbidden_connection_formed")
        descriptor_sources = {
            "distance": candidate.get("key_distances_angstrom", {}),
            "angle": candidate.get("custom_descriptors", {}),
            "dihedral": candidate.get("torsions_degrees", {}),
            "centroid_distance": candidate.get("aromatic_descriptors", {}),
            "plane_angle": candidate.get("aromatic_descriptors", {}),
            "lateral_slip": candidate.get("aromatic_descriptors", {}),
            "contact": candidate.get("custom_descriptors", {}),
            "custom": candidate.get("custom_descriptors", {}),
        }
        for descriptor in category["descriptor_constraints"]:
            observed = descriptor_sources[descriptor["kind"]].get(descriptor["descriptor_id"])
            if observed is None:
                reasons.append(f"missing_descriptor:{descriptor['descriptor_id']}")
            elif not descriptor["minimum"] <= float(observed) <= descriptor["maximum"]:
                reasons.append(f"descriptor_out_of_range:{descriptor['descriptor_id']}")
        if candidate.get("association_status") in {"dissociated", "collapsed_to_other_state"}:
            state_change.append(candidate["association_status"])
        if candidate.get("non_target_transfer") is True:
            state_change.append("non_target_transfer")
        if candidate.get("xtb_optimization_status") != "converged":
            reasons.append("xtb_optimization_not_converged")
        software = candidate.get("software", {})
        if not isinstance(software.get("absolute_path"), str) or not os.path.isabs(software["absolute_path"]):
            reasons.append("software_absolute_path_missing")
        if not isinstance(software.get("version"), str) or not software["version"]:
            reasons.append("software_version_missing")
        if state_change:
            status = "state_changed"
            disposition = "new_hypothesis_candidate" if candidate.get("retain_as_hypothesis") is True else "negative_evidence"
        elif reasons:
            status, disposition = "invalid", "negative_evidence"
        else:
            status, disposition = "valid", "quota_candidate"
        entries.append({
            "candidate_id": candidate_id,
            "route_id": route_id,
            "subroute_id": subroute_id,
            "category_id": category_id,
            "status": status,
            "disposition": disposition,
            "accepted_into_quota": status == "valid",
            "reasons": sorted(set(reasons)),
            "state_change_evidence": sorted(set(state_change)),
            "source_input_sha256": candidate["source_input_sha256"],
            "source_argv": candidate["source_argv"],
            "random_seed": candidate["random_seed"],
            "software": candidate["software"],
            "energy_observation": candidate["energy_observation"],
        })
    require(entries, "candidate set must not be empty")
    ledger = {
        "schema": SCHEMAS["ledger"],
        "ledger_id": plan["plan_id"] + "_validity",
        "plan": binding(plan_path, SCHEMAS["plan"], payload=plan["payload_sha256"]),
        "candidate_set": binding(candidates_path, SCHEMAS["candidates"]),
        "entries": entries,
        "counts": {
            "observed": len(entries),
            "valid": sum(item["status"] == "valid" for item in entries),
            "invalid": sum(item["status"] == "invalid" for item in entries),
            "state_changed": sum(item["status"] == "state_changed" for item in entries),
        },
        "negative_evidence_preserved": True,
        "candidate_only": True,
        "calculation_ready": False,
        "no_submission_authorization": True,
    }
    ledger["payload_sha256"] = payload_sha256(ledger)
    return ledger


def minimum_distance(coordinates: list[list[float]]) -> float:
    if len(coordinates) < 2:
        return math.inf
    return min(math.dist(coordinates[left], coordinates[right]) for left in range(len(coordinates)) for right in range(left + 1, len(coordinates)))


def _center(points: list[list[float]]) -> tuple[list[list[float]], list[float]]:
    centroid = [sum(point[axis] for point in points) / len(points) for axis in range(3)]
    return [[point[axis] - centroid[axis] for axis in range(3)] for point in points], centroid


def _largest_eigenvector_symmetric(matrix: list[list[float]]) -> list[float]:
    size = len(matrix)
    a = [row[:] for row in matrix]
    vectors = [[1.0 if i == j else 0.0 for j in range(size)] for i in range(size)]
    for _ in range(100):
        p, q = max(((i, j) for i in range(size) for j in range(i + 1, size)), key=lambda pair: abs(a[pair[0]][pair[1]]))
        if abs(a[p][q]) < 1e-14:
            break
        phi = 0.5 * math.atan2(2 * a[p][q], a[q][q] - a[p][p])
        c, s = math.cos(phi), math.sin(phi)
        for i in range(size):
            api, aqi = a[i][p], a[i][q]
            a[i][p], a[i][q] = c * api - s * aqi, s * api + c * aqi
        for j in range(size):
            apj, aqj = a[p][j], a[q][j]
            a[p][j], a[q][j] = c * apj - s * aqj, s * apj + c * aqj
        for i in range(size):
            vip, viq = vectors[i][p], vectors[i][q]
            vectors[i][p], vectors[i][q] = c * vip - s * viq, s * vip + c * viq
    index = max(range(size), key=lambda item: a[item][item])
    vector = [vectors[row][index] for row in range(size)]
    norm = math.sqrt(sum(value * value for value in vector))
    return [value / norm for value in vector]


def mapped_rmsd(left: list[list[float]], right: list[list[float]], indices: list[int]) -> float:
    require(len(left) == len(right), "RMSD atom counts differ")
    x, _ = _center([left[index] for index in indices])
    y, _ = _center([right[index] for index in indices])
    sxx = sum(a[0] * b[0] for a, b in zip(x, y)); sxy = sum(a[0] * b[1] for a, b in zip(x, y)); sxz = sum(a[0] * b[2] for a, b in zip(x, y))
    syx = sum(a[1] * b[0] for a, b in zip(x, y)); syy = sum(a[1] * b[1] for a, b in zip(x, y)); syz = sum(a[1] * b[2] for a, b in zip(x, y))
    szx = sum(a[2] * b[0] for a, b in zip(x, y)); szy = sum(a[2] * b[1] for a, b in zip(x, y)); szz = sum(a[2] * b[2] for a, b in zip(x, y))
    n = [
        [sxx + syy + szz, syz - szy, szx - sxz, sxy - syx],
        [syz - szy, sxx - syy - szz, sxy + syx, szx + sxz],
        [szx - sxz, sxy + syx, -sxx + syy - szz, syz + szy],
        [sxy - syx, szx + sxz, syz + szy, -sxx - syy + szz],
    ]
    w, qx, qy, qz = _largest_eigenvector_symmetric(n)
    rotation = [
        [1 - 2 * (qy * qy + qz * qz), 2 * (qx * qy - qz * w), 2 * (qx * qz + qy * w)],
        [2 * (qx * qy + qz * w), 1 - 2 * (qx * qx + qz * qz), 2 * (qy * qz - qx * w)],
        [2 * (qx * qz - qy * w), 2 * (qy * qz + qx * w), 1 - 2 * (qx * qx + qy * qy)],
    ]
    rotated = [[sum(rotation[row][col] * point[col] for col in range(3)) for row in range(3)] for point in x]
    return math.sqrt(sum(sum((a[axis] - b[axis]) ** 2 for axis in range(3)) for a, b in zip(rotated, y)) / len(indices))


def periodic_difference(left: float, right: float) -> float:
    return abs((left - right + 180.0) % 360.0 - 180.0)


def _rmse(values: Iterable[float]) -> float:
    values = list(values)
    return math.sqrt(sum(value * value for value in values) / len(values)) if values else 0.0


def _jaccard(left: Iterable[str], right: Iterable[str]) -> float:
    a, b = set(left), set(right)
    return len(a & b) / len(a | b) if a or b else 1.0


def _dictionary_rmse(left: dict[str, float], right: dict[str, float]) -> float:
    keys = sorted(set(left) | set(right))
    return _rmse(float(left.get(key, 0.0)) - float(right.get(key, 0.0)) for key in keys)


def pair_distance(left: dict[str, Any], right: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    settings = plan["similarity"]
    heavy = [index for index, element in enumerate(plan["state_signature"]["elements"]) if element != "H"]
    mapped = mapped_rmsd(left["coordinates_angstrom"], right["coordinates_angstrom"], heavy)
    permutations = settings.get("symmetry_permutations", [])
    symmetry = mapped
    for permutation in permutations:
        permuted = [right["coordinates_angstrom"][index] for index in permutation]
        symmetry = min(symmetry, mapped_rmsd(left["coordinates_angstrom"], permuted, heavy))
    key_distance = _dictionary_rmse(left.get("key_distances_angstrom", {}), right.get("key_distances_angstrom", {}))
    torsion = _rmse(periodic_difference(float(left.get("torsions_degrees", {}).get(key, 0.0)), float(right.get("torsions_degrees", {}).get(key, 0.0))) / 180.0 for key in set(left.get("torsions_degrees", {})) | set(right.get("torsions_degrees", {})))
    contact_similarity = _jaccard(left.get("contact_fingerprint", []), right.get("contact_fingerprint", []))
    fragment = _dictionary_rmse(left.get("fragment_descriptors", {}), right.get("fragment_descriptors", {}))
    aromatic = _dictionary_rmse(left.get("aromatic_descriptors", {}), right.get("aromatic_descriptors", {}))
    custom = _dictionary_rmse(left.get("custom_descriptors", {}), right.get("custom_descriptors", {}))
    components = {
        "mapped_rmsd": mapped,
        "symmetry_rmsd": symmetry,
        "key_distance": key_distance,
        "torsion": torsion,
        "contact": 1.0 - contact_similarity,
        "fragment": fragment,
        "aromatic": aromatic,
        "custom": custom,
    }
    composite = sum(settings["weights"][key] * value for key, value in components.items())
    thresholds = settings["thresholds"]
    same_category = left["category_id"] == right["category_id"]
    contacts_equal = set(left.get("contact_fingerprint", [])) == set(right.get("contact_fingerprint", []))
    if not same_category:
        classification = "different_category"
    elif symmetry <= thresholds["duplicate_rmsd"] and key_distance <= thresholds["duplicate_key_distance"] and contacts_equal:
        classification = "duplicate"
    elif symmetry <= thresholds["high_rmsd"] and key_distance <= thresholds["high_key_distance"] and contact_similarity >= thresholds["minimum_contact_similarity"]:
        classification = "highly_similar"
    elif symmetry <= thresholds["boundary_rmsd"]:
        classification = "boundary"
    else:
        classification = "independent"
    conflict = (symmetry <= thresholds["duplicate_rmsd"] and contact_similarity < thresholds["minimum_contact_similarity"]) or (symmetry > thresholds["boundary_rmsd"] and contact_similarity >= thresholds["minimum_contact_similarity"])
    backend_review = classification == "boundary" or bool(permutations) or conflict or left.get("force_backend_review") is True or right.get("force_backend_review") is True
    return {
        "candidate_ids": sorted([left["candidate_id"], right["candidate_id"]]),
        "components": {key: round(value, 10) for key, value in components.items()},
        "contact_similarity": round(contact_similarity, 10),
        "composite_distance": round(composite, 10),
        "classification": classification,
        "category_merge_forbidden": not same_category,
        "independent_backend_review_required": backend_review,
        "independent_backend_review_reason": "symmetry_boundary_or_descriptor_conflict" if backend_review else None,
    }


def _union_clusters(candidate_ids: list[str], comparisons: list[dict[str, Any]]) -> list[list[str]]:
    index = {candidate_id: position for position, candidate_id in enumerate(candidate_ids)}
    parents = list(range(len(candidate_ids)))
    def find(position: int) -> int:
        while parents[position] != position:
            parents[position] = parents[parents[position]]
            position = parents[position]
        return position
    for comparison in comparisons:
        if comparison["classification"] not in {"duplicate", "highly_similar"} or comparison["category_merge_forbidden"]:
            continue
        left, right = (index[item] for item in comparison["candidate_ids"])
        a, b = find(left), find(right)
        if a != b:
            parents[max(a, b)] = min(a, b)
    groups: dict[int, list[str]] = {}
    for candidate_id in candidate_ids:
        groups.setdefault(find(index[candidate_id]), []).append(candidate_id)
    return sorted((sorted(group) for group in groups.values()), key=lambda group: group[0])


def crosscheck(plan: dict[str, Any], plan_path: Path, candidates: dict[str, Any], candidates_path: Path, ledger: dict[str, Any], ledger_path: Path) -> dict[str, Any]:
    validate_plan(plan, plan_path)
    validate_schema(ledger, "validity-ledger.schema.json")
    verify_document_matches_path(ledger, ledger_path, "conformer validity ledger")
    require(ledger.get("schema") == SCHEMAS["ledger"] and ledger.get("payload_sha256") == payload_sha256(ledger), "validity ledger is invalid")
    verify_binding(ledger["plan"], plan_path, SCHEMAS["plan"])
    verify_binding(ledger["candidate_set"], candidates_path, SCHEMAS["candidates"])
    require(ledger == audit_candidates(plan, plan_path, candidates, candidates_path), "validity ledger does not match a fresh semantic audit")
    require(candidates.get("plan_sha256") == file_sha256(plan_path), "candidate set plan binding differs")
    valid_ids = {item["candidate_id"] for item in ledger["entries"] if item["status"] == "valid"}
    by_id = {item["candidate_id"]: item for item in candidates["candidates"]}
    valid = [by_id[candidate_id] for candidate_id in sorted(valid_ids)]
    comparisons = [pair_distance(valid[left], valid[right], plan) for left in range(len(valid)) for right in range(left + 1, len(valid))]
    clusters_raw = _union_clusters([item["candidate_id"] for item in valid], comparisons) if valid else []
    distance_lookup = {tuple(item["candidate_ids"]): item["composite_distance"] for item in comparisons}
    clusters = []
    for number, members in enumerate(clusters_raw, 1):
        routes = sorted({by_id[item]["route_id"] for item in members})
        category_ids = sorted({by_id[item]["category_id"] for item in members})
        require(len(category_ids) == 1, "cluster crossed category boundary")
        def medoid_score(candidate_id: str) -> tuple[float, str]:
            score = sum(distance_lookup.get(tuple(sorted((candidate_id, other))), 0.0) for other in members if other != candidate_id)
            return score, candidate_id
        medoid = min(members, key=medoid_score)
        clusters.append({
            "cluster_id": f"cluster_{number:03d}",
            "category_id": category_ids[0],
            "member_candidate_ids": members,
            "route_ids": routes,
            "classification": "consensus_optimal" if routes == ["route_a", "route_b"] else "single_route_secondary",
            "medoid_candidate_id": medoid,
            "medoid_total_distance": round(medoid_score(medoid)[0], 10),
            "source_records_preserved": True,
            "requires_human_review": True,
        })
    quota_fulfillment = []
    for category in plan["category_quotas"]:
        for route_id in sorted(ROUTES):
            independent = sum(cluster["category_id"] == category["category_id"] and route_id in cluster["route_ids"] for cluster in clusters)
            required = category["route_quotas"][route_id]
            quota_fulfillment.append({"category_id": category["category_id"], "route_id": route_id, "required_independent": required, "observed_independent": independent, "fulfilled": independent >= required})
    backend_queue = [item for item in comparisons if item["independent_backend_review_required"]]
    invalid = [copy.deepcopy(item) for item in ledger["entries"] if item["status"] != "valid"]
    actual_counts = []
    for category in plan["category_quotas"]:
        for subroute_id in sorted(SUBROUTES):
            route_id = SUBROUTE_ROUTE[subroute_id]
            raw = [item for item in candidates["candidates"] if item["category_id"] == category["category_id"] and item["subroute_id"] == subroute_id]
            valid_raw = [item for item in raw if item["candidate_id"] in valid_ids]
            independent = sum(
                cluster["category_id"] == category["category_id"]
                and any(by_id[candidate_id]["subroute_id"] == subroute_id for candidate_id in cluster["member_candidate_ids"])
                for cluster in clusters
            )
            actual_counts.append({"category_id": category["category_id"], "route_id": route_id, "subroute_id": subroute_id, "observed_candidates": len(raw), "valid_candidates": len(valid_raw), "independent_clusters": independent})
    provenance = [
        {
            "candidate_id": item["candidate_id"], "route_id": item["route_id"], "subroute_id": item["subroute_id"],
            "category_id": item["category_id"], "source_input_sha256": item["source_input_sha256"],
            "source_argv": item["source_argv"], "random_seed": item["random_seed"],
            "software": item["software"], "energy_observation": item["energy_observation"],
        }
        for item in candidates["candidates"]
    ]
    blockers = []
    if backend_queue:
        blockers.append("independent symmetry/similarity backend review is pending")
    if not all(item["fulfilled"] for item in quota_fulfillment):
        blockers.append("one or more preregistered route/category quotas are unfulfilled")
    blockers.extend([
        "human cluster and medoid review is pending",
        "no Gaussian method, input, resource, server path, or live approval is present",
    ])
    manifest = {
        "schema": SCHEMAS["manifest"],
        "manifest_id": plan["plan_id"] + "_ensemble",
        "revision": copy.deepcopy(plan["revision"]),
        "plan": binding(plan_path, SCHEMAS["plan"], payload=plan["payload_sha256"]),
        "candidate_set": binding(candidates_path, SCHEMAS["candidates"]),
        "validity_ledger": binding(ledger_path, SCHEMAS["ledger"], payload=ledger["payload_sha256"]),
        "state_signature": copy.deepcopy(plan["state_signature"]),
        "locked_route_weights": copy.deepcopy(plan["locked_route_weights"]),
        "locked_subroute_weights": copy.deepcopy(plan["locked_subroute_weights"]),
        "category_quotas": copy.deepcopy(plan["category_quotas"]),
        "raw_sampling_counts": copy.deepcopy(candidates["raw_sampling_counts"]),
        "actual_route_subroute_counts": actual_counts,
        "candidate_provenance": provenance,
        "validity_counts": copy.deepcopy(ledger["counts"]),
        "comparisons": comparisons,
        "clusters": clusters,
        "consensus_cluster_ids": [item["cluster_id"] for item in clusters if item["classification"] == "consensus_optimal"],
        "secondary_cluster_ids": [item["cluster_id"] for item in clusters if item["classification"] == "single_route_secondary"],
        "invalid_candidates": invalid,
        "negative_evidence_preserved": True,
        "quota_fulfillment": quota_fulfillment,
        "independent_backend_review_queue": backend_queue,
        "independent_backend_review_complete": not backend_queue,
        "human_review_status": "pending",
        "downstream_handoff_status": "blocked_pending_review",
        "energies_used_for_ranking": False,
        "candidate_only": True,
        "calculation_ready": False,
        "no_submission_authorization": True,
        "external_execution_performed": False,
        "blockers": blockers,
    }
    manifest["payload_sha256"] = payload_sha256(manifest)
    return manifest


def build_handoff(manifest: dict[str, Any], manifest_path: Path, review: dict[str, Any], review_path: Path) -> dict[str, Any]:
    validate_schema(manifest, "ensemble-manifest.schema.json")
    verify_document_matches_path(manifest, manifest_path, "conformer ensemble manifest")
    validate_schema(review, "handoff-review.schema.json")
    verify_document_matches_path(review, review_path, "conformer handoff review")
    require(manifest.get("schema") == SCHEMAS["manifest"] and manifest.get("payload_sha256") == payload_sha256(manifest), "manifest is invalid")
    require(review.get("schema") == "gaussian-conformer-handoff-review/1", "handoff review schema is invalid")
    require(review.get("manifest_sha256") == file_sha256(manifest_path), "handoff review does not bind exact manifest")
    require(review.get("confirmed") is True and review.get("decision") == "selected_for_downstream_input_review", "handoff review is not confirmed")
    medoids = {cluster["medoid_candidate_id"] for cluster in manifest["clusters"]}
    selected = review.get("selected_candidate_ids")
    require(isinstance(selected, list) and selected and set(selected) <= medoids, "handoff may select only reviewed manifest medoids")
    handoff = {
        "schema": SCHEMAS["handoff"],
        "handoff_id": manifest["manifest_id"] + "_handoff",
        "manifest": binding(manifest_path, SCHEMAS["manifest"], payload=manifest["payload_sha256"]),
        "review": binding(review_path, "gaussian-conformer-handoff-review/1"),
        "state_signature": copy.deepcopy(manifest["state_signature"]),
        "selected_candidate_ids": selected,
        "selection_scope": "structure_candidates_only",
        "candidate_only": True,
        "calculation_ready": False,
        "no_submission_authorization": True,
        "gaussian_input_present": False,
        "gaussian_protocol_present": False,
        "server_or_resource_authorization_present": False,
        "required_next_review": "exact Gaussian structure/protocol/resource/input-hash approval",
    }
    handoff["payload_sha256"] = payload_sha256(handoff)
    return handoff


def validate_manifest(path: str | Path) -> dict[str, Any]:
    """Replay one ensemble manifest through every bound owner artifact."""

    manifest_path = Path(path).expanduser().resolve()
    manifest = load_json(manifest_path)
    validate_schema(manifest, "ensemble-manifest.schema.json")
    verify_document_matches_path(manifest, manifest_path, "conformer ensemble manifest")
    require(manifest.get("schema") == SCHEMAS["manifest"], "unsupported ensemble-manifest schema")
    require(manifest.get("payload_sha256") == payload_sha256(manifest), "ensemble-manifest payload hash is invalid")
    require(
        manifest.get("candidate_only") is True
        and manifest.get("calculation_ready") is False
        and manifest.get("no_submission_authorization") is True,
        "ensemble-manifest authority boundary is invalid",
    )

    plan_path = resolve_bound_path(manifest_path, manifest["plan"].get("path"), "bound conformer-search plan")
    candidates_path = resolve_bound_path(manifest_path, manifest["candidate_set"].get("path"), "bound conformer candidate set")
    ledger_path = resolve_bound_path(manifest_path, manifest["validity_ledger"].get("path"), "bound conformer validity ledger")
    verify_binding(manifest["plan"], plan_path, SCHEMAS["plan"])
    verify_binding(manifest["candidate_set"], candidates_path, SCHEMAS["candidates"])
    verify_binding(manifest["validity_ledger"], ledger_path, SCHEMAS["ledger"])
    require(manifest["plan"].get("payload_sha256") == load_json(plan_path).get("payload_sha256"), "manifest plan payload binding differs")
    require(manifest["validity_ledger"].get("payload_sha256") == load_json(ledger_path).get("payload_sha256"), "manifest ledger payload binding differs")
    expected = crosscheck(
        load_json(plan_path), plan_path,
        load_json(candidates_path), candidates_path,
        load_json(ledger_path), ledger_path,
    )
    require(manifest == expected, "ensemble manifest differs from deterministic bound-source reconstruction")
    return manifest


def validate_handoff(path: str | Path) -> dict[str, Any]:
    """Public replay API for an exact candidate handoff and its full chain."""

    handoff_path = Path(path).expanduser().resolve()
    handoff = load_json(handoff_path)
    validate_schema(handoff, "candidate-handoff.schema.json")
    verify_document_matches_path(handoff, handoff_path, "conformer candidate handoff")
    require(handoff.get("schema") == SCHEMAS["handoff"], "unsupported conformer handoff schema")
    require(handoff.get("payload_sha256") == payload_sha256(handoff), "conformer handoff payload hash is invalid")
    require(
        handoff.get("candidate_only") is True
        and handoff.get("calculation_ready") is False
        and handoff.get("no_submission_authorization") is True,
        "conformer handoff authority boundary is invalid",
    )

    manifest_path = resolve_bound_path(handoff_path, handoff["manifest"].get("path"), "bound conformer ensemble manifest")
    review_path = resolve_bound_path(handoff_path, handoff["review"].get("path"), "bound conformer handoff review")
    verify_binding(handoff["manifest"], manifest_path, SCHEMAS["manifest"])
    verify_binding(handoff["review"], review_path, "gaussian-conformer-handoff-review/1")
    manifest = validate_manifest(manifest_path)
    require(handoff["manifest"].get("payload_sha256") == manifest.get("payload_sha256"), "handoff manifest payload binding differs")
    expected = build_handoff(manifest, manifest_path, load_json(review_path), review_path)
    require(handoff == expected, "conformer handoff differs from deterministic bound-source reconstruction")
    return handoff
