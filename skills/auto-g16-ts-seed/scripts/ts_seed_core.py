#!/usr/bin/env python3
"""Fail-closed offline builders for hash-bound TS seed artifacts."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
from pathlib import Path, PurePosixPath
from typing import Any


CANDIDATE_SCHEMA = "gaussian-ts-seed-candidate/1"
PORTFOLIO_SCHEMA = "gaussian-ts-seed-portfolio/1"
STRATEGIES = (
    "exact_reviewed_target_coordinates",
    "analogous_reaction_core_transfer",
    "reviewed_endpoint_qst2",
    "reviewed_qst3",
    "constrained_directional_scan",
    "de_novo",
)
HASH_KEYS = {
    "geometry_sha256", "hypothesis_signature_sha256", "target_signature_sha256",
    "structural_fingerprint_sha256", "payload_sha256",
}


class ContractError(ValueError):
    """Raised when an artifact is unsafe, ambiguous, or scientifically incomplete."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def _reject_constant(value: str) -> None:
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
            parse_constant=_reject_constant,
            object_pairs_hook=_object,
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read JSON {path}: {exc}") from exc
    require(isinstance(value, dict), f"{path}: top-level value must be an object")
    return value


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def object_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def payload_sha256(document: dict[str, Any]) -> str:
    return object_sha256({key: value for key, value in document.items() if key != "payload_sha256"})


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _exact(value: Any, keys: set[str], label: str) -> dict[str, Any]:
    require(isinstance(value, dict), f"{label} must be an object")
    actual = set(value)
    require(actual == keys, f"{label} keys must be exactly {sorted(keys)}; got {sorted(actual)}")
    return value


def _nonempty(value: Any, label: str) -> str:
    require(isinstance(value, str) and value.strip(), f"{label} must be a non-empty string")
    return value


def _sha(value: Any, label: str) -> str:
    require(isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value), f"{label} must be lowercase SHA-256")
    return value


def _safe_relative(path_text: Any, base: Path, label: str) -> Path:
    text = _nonempty(path_text, f"{label}.path")
    pure = PurePosixPath(text)
    require(not pure.is_absolute() and ".." not in pure.parts and "." not in pure.parts, f"{label}.path must be package-relative without parent traversal")
    root = base.resolve()
    cursor = root
    for part in pure.parts:
        cursor = cursor / part
        require(not cursor.is_symlink(), f"{label}.path must not traverse a symlink")
    candidate = (root / Path(*pure.parts)).resolve()
    require(candidate == root or root in candidate.parents, f"{label}.path escapes its package")
    require(candidate.is_file() and not candidate.is_symlink(), f"{label}.path must name a regular non-symlink file")
    return candidate


def validate_artifact_ref(value: Any, base: Path, label: str) -> dict[str, Any]:
    ref = _exact(value, {"path", "sha256", "size_bytes", "schema", "payload_sha256"}, label)
    target = _safe_relative(ref["path"], base, label)
    require(file_sha256(target) == _sha(ref["sha256"], f"{label}.sha256"), f"{label} file hash drift")
    require(target.stat().st_size == ref["size_bytes"], f"{label} size drift")
    source = load_json(target)
    require(source.get("schema") == _nonempty(ref["schema"], f"{label}.schema"), f"{label} schema drift")
    expected_payload = _sha(ref["payload_sha256"], f"{label}.payload_sha256")
    require(source.get("payload_sha256") == expected_payload, f"{label} declared payload drift")
    require(payload_sha256(source) == expected_payload, f"{label} payload hash mismatch")
    return ref


def artifact_ref(path: Path, base: Path) -> dict[str, Any]:
    source = load_json(path)
    require("schema" in source and "payload_sha256" in source, f"{path}: artifact lacks schema or payload hash")
    require(payload_sha256(source) == source["payload_sha256"], f"{path}: payload hash mismatch")
    relative = path.resolve().relative_to(base.resolve()).as_posix()
    return {
        "path": relative, "sha256": file_sha256(path), "size_bytes": path.stat().st_size,
        "schema": source["schema"], "payload_sha256": source["payload_sha256"],
    }


def _validate_precedence(provenance: dict[str, Any], strategy: str) -> None:
    review = provenance["precedence_review"]
    require(isinstance(review, list) and len(review) == len(STRATEGIES), "precedence_review must cover all six ordered strategies")
    selected = STRATEGIES.index(strategy)
    for index, expected in enumerate(STRATEGIES):
        item = _exact(review[index], {"strategy", "status", "rationale"}, f"precedence_review[{index}]")
        require(item["strategy"] == expected, "precedence_review is not in required strategy order")
        _nonempty(item["rationale"], f"precedence_review[{index}].rationale")
        allowed = "selected" if index == selected else ("not_evaluated_lower_priority" if index > selected else None)
        if index < selected:
            require(item["status"] in {"unavailable", "rejected_with_rationale"}, f"higher-priority strategy {expected} must be unavailable or explicitly rejected")
        else:
            require(item["status"] == allowed, f"precedence status is invalid for {expected}")


def _validate_coordinates(document: dict[str, Any]) -> tuple[set[str], dict[str, str]]:
    coordinates = document["coordinates"]
    require(isinstance(coordinates, list) and coordinates, "coordinates must be non-empty")
    ids: set[str] = set()
    elements: dict[str, str] = {}
    indexes: set[int] = set()
    for index, atom in enumerate(coordinates):
        item = _exact(atom, {"index", "atom_id", "element", "x", "y", "z"}, f"coordinates[{index}]")
        require(isinstance(item["index"], int) and not isinstance(item["index"], bool) and item["index"] >= 1, "coordinate index must be positive integer")
        atom_id = _nonempty(item["atom_id"], "coordinate atom_id")
        require(item["index"] not in indexes and atom_id not in ids, "coordinate indexes and atom IDs must be unique")
        indexes.add(item["index"]); ids.add(atom_id)
        elements[atom_id] = _nonempty(item["element"], "coordinate element")
        for axis in ("x", "y", "z"):
            require(isinstance(item[axis], (int, float)) and not isinstance(item[axis], bool) and math.isfinite(item[axis]), f"coordinate {axis} must be finite")
    require(indexes == set(range(1, len(coordinates) + 1)), "coordinate indexes must be contiguous from 1")
    return ids, elements


def _validate_candidate_semantics(document: dict[str, Any], base: Path, verify_refs: bool = True) -> None:
    require(document["schema"] == CANDIDATE_SCHEMA, "wrong candidate schema")
    require(document["strategy_rank"] == STRATEGIES.index(document["seed_strategy"]) + 1, "strategy rank drift")
    require(document["construction_policy"]["cosmetic_cartesian_permutations_used"] is False, "Cartesian face/angle/distance permutations are forbidden")
    _nonempty(document["construction_policy"]["chemical_hypothesis"], "chemical hypothesis")
    _nonempty(document["construction_policy"]["reaction_coordinate_lineage_id"], "reaction-coordinate lineage")
    atom_ids, elements = _validate_coordinates(document)
    mapping = document["atom_mapping"]
    require(isinstance(mapping, list) and len(mapping) == len(atom_ids), "atom mapping must cover every coordinate exactly once")
    mapped: set[str] = set()
    for index, raw in enumerate(mapping):
        item = _exact(raw, {"candidate_atom_id", "element", "reactant_atom_id", "product_atom_id"}, f"atom_mapping[{index}]")
        atom_id = _nonempty(item["candidate_atom_id"], "mapped candidate atom")
        require(atom_id in atom_ids and atom_id not in mapped, "atom mapping contains unknown or duplicate candidate atom")
        require(elements[atom_id] == item["element"], "atom mapping element drift")
        _nonempty(item["reactant_atom_id"], "reactant atom mapping")
        _nonempty(item["product_atom_id"], "product atom mapping")
        mapped.add(atom_id)
    coordinate = document["reaction_coordinate"]
    require(any(coordinate[key] for key in ("forming_bonds", "breaking_bonds", "collective_coordinates")), "forming/breaking bond or collective coordinate is required")
    for group in ("forming_bonds", "breaking_bonds"):
        for bond in coordinate[group]:
            require(len(bond["atom_ids"]) == 2 and set(bond["atom_ids"]) <= atom_ids, f"{group} references unknown atoms")
    for collective in coordinate["collective_coordinates"]:
        require(set(collective["atom_ids"]) <= atom_ids, "collective coordinate references unknown atoms")
    state = document["electronic_state"]
    routes = document["specialist_routing"]
    required_routes: set[str] = set()
    if state["open_shell"]:
        required_routes.add("auto-g16-main-group-open-shell")
    if state["transition_metal"]:
        required_routes.add("auto-g16-metal-ts")
    require(routes["required"] == bool(required_routes), "specialist routing required flag drift")
    require(required_routes <= set(routes["routes"]), "open-shell/metal candidate is missing its specialist route")
    if required_routes:
        require(routes["status"] in {"pending_specialist_review", "reviewed_by_specialist"}, "specialist routing status is invalid")
        if routes["status"] == "reviewed_by_specialist":
            require(routes["evidence"], "reviewed specialist routing requires hash-bound evidence")
    else:
        require(routes == {"required": False, "routes": [], "status": "not_applicable", "evidence": []}, "closed-shell non-metal routing must be not_applicable")
    if verify_refs:
        for label in ("target_coordinates", "reactant_endpoint", "product_endpoint", "method_protocol_reference"):
            validate_artifact_ref(document[label], base, label)
        for index, ref in enumerate(document["provenance"]["source_artifacts"]):
            validate_artifact_ref(ref, base, f"source_artifacts[{index}]")
        for index, ref in enumerate(routes["evidence"]):
            validate_artifact_ref(ref, base, f"specialist evidence[{index}]")
    _validate_precedence(document["provenance"], document["seed_strategy"])
    if document["seed_strategy"] == "exact_reviewed_target_coordinates":
        require(any(ref["payload_sha256"] == document["target_coordinates"]["payload_sha256"] for ref in document["provenance"]["source_artifacts"]), "exact-target strategy must bind the reviewed target coordinates")
    if document["seed_strategy"] == "analogous_reaction_core_transfer":
        require(document["provenance"]["transfer_atom_mapping"], "analogous-core transfer requires reviewed transfer atom mapping")
    review_pass = document["review"]["status"] == "reviewed"
    geometry_pass = document["geometry_review"]["sanity"] == "passed" and document["geometry_review"]["connectivity_status"] == "passed" and document["geometry_review"]["clashes"]["status"] == "passed"
    specialist_pass = not required_routes or routes["status"] == "reviewed_by_specialist"
    require(document["portfolio_eligible"] == (review_pass and geometry_pass and specialist_pass), "portfolio eligibility gate drift")
    require(document["calculation_ready"] is False and document["executable"] is False and document["no_submission_authorization"] is True, "TS seed candidate must remain non-executable")
    require(document["geometry_sha256"] == object_sha256(document["coordinates"]), "geometry hash mismatch")
    hypothesis_payload = {"chemical_hypothesis": document["construction_policy"]["chemical_hypothesis"], "reaction_coordinate_lineage_id": document["construction_policy"]["reaction_coordinate_lineage_id"], "reaction_coordinate": document["reaction_coordinate"], "stereochemical_binding_mode": document["stereochemical_binding_mode"]}
    require(document["hypothesis_signature_sha256"] == object_sha256(hypothesis_payload), "hypothesis signature mismatch")
    target_payload = {"target_id": document["target_id"], "target_coordinates": document["target_coordinates"]["payload_sha256"], "reactant_endpoint": document["reactant_endpoint"]["payload_sha256"], "product_endpoint": document["product_endpoint"]["payload_sha256"], "method_protocol": document["method_protocol_reference"]["payload_sha256"], "electronic_state": state}
    require(document["target_signature_sha256"] == object_sha256(target_payload), "target signature mismatch")
    structural = [{"element": atom["element"], "x": round(atom["x"], 6), "y": round(atom["y"], 6), "z": round(atom["z"], 6)} for atom in document["coordinates"]]
    require(document["structural_fingerprint_sha256"] == object_sha256(structural), "structural fingerprint mismatch")
    require(document["payload_sha256"] == payload_sha256(document), "candidate payload hash mismatch")


def build_candidate(source: dict[str, Any], source_path: Path) -> dict[str, Any]:
    keys = {
        "candidate_id", "target_id", "target_coordinates", "seed_strategy", "coordinates",
        "atom_mapping", "reaction_coordinate", "electronic_state", "stereochemical_binding_mode",
        "reactant_endpoint", "product_endpoint", "method_protocol_reference", "geometry_review",
        "provenance", "confidence", "construction_policy", "specialist_routing", "review",
    }
    _exact(source, keys, "candidate source")
    require(source["seed_strategy"] in STRATEGIES, "unknown seed strategy")
    base = source_path.resolve().parent
    document = {"schema": CANDIDATE_SCHEMA, **source, "strategy_rank": STRATEGIES.index(source["seed_strategy"]) + 1}
    document["geometry_sha256"] = object_sha256(document["coordinates"])
    document["hypothesis_signature_sha256"] = object_sha256({"chemical_hypothesis": document["construction_policy"]["chemical_hypothesis"], "reaction_coordinate_lineage_id": document["construction_policy"]["reaction_coordinate_lineage_id"], "reaction_coordinate": document["reaction_coordinate"], "stereochemical_binding_mode": document["stereochemical_binding_mode"]})
    document["target_signature_sha256"] = object_sha256({"target_id": document["target_id"], "target_coordinates": document["target_coordinates"]["payload_sha256"], "reactant_endpoint": document["reactant_endpoint"]["payload_sha256"], "product_endpoint": document["product_endpoint"]["payload_sha256"], "method_protocol": document["method_protocol_reference"]["payload_sha256"], "electronic_state": document["electronic_state"]})
    document["structural_fingerprint_sha256"] = object_sha256([{"element": atom["element"], "x": round(atom["x"], 6), "y": round(atom["y"], 6), "z": round(atom["z"], 6)} for atom in document["coordinates"]])
    required = document["electronic_state"]["open_shell"] or document["electronic_state"]["transition_metal"]
    document["portfolio_eligible"] = document["review"]["status"] == "reviewed" and document["geometry_review"]["sanity"] == "passed" and document["geometry_review"]["connectivity_status"] == "passed" and document["geometry_review"]["clashes"]["status"] == "passed" and (not required or document["specialist_routing"]["status"] == "reviewed_by_specialist")
    document.update({"calculation_ready": False, "executable": False, "no_submission_authorization": True})
    document["payload_sha256"] = payload_sha256(document)
    _validate_candidate_semantics(document, base)
    validate_schema(document, CANDIDATE_SCHEMA)
    return document


def validate_candidate(document: dict[str, Any], path: Path) -> None:
    validate_schema(document, CANDIDATE_SCHEMA)
    _validate_candidate_semantics(document, path.resolve().parent)


def build_portfolio(source: dict[str, Any], source_path: Path) -> dict[str, Any]:
    _exact(source, {"portfolio_id", "target_id", "selections", "exception_review", "review"}, "portfolio source")
    base = source_path.resolve().parent
    selections = source["selections"]
    require(isinstance(selections, list) and selections, "portfolio selections must be non-empty")
    entries: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    for index, raw in enumerate(selections):
        selection = _exact(raw, {"path", "role", "scientific_rationale", "user_reviewed"}, f"selections[{index}]")
        require(selection["role"] in {"primary", "backup", "additional"}, "invalid portfolio role")
        require(selection["user_reviewed"] is True, "every selected seed requires explicit user review")
        _nonempty(selection["scientific_rationale"], "selection scientific rationale")
        path = _safe_relative(selection["path"], base, f"selections[{index}]")
        candidate = load_json(path)
        validate_candidate(candidate, path)
        require(candidate["portfolio_eligible"] is True, "portfolio cannot select a blocked or unreviewed candidate")
        candidates.append(candidate)
        entries.append({"candidate_id": candidate["candidate_id"], "role": selection["role"], "scientific_rationale": selection["scientific_rationale"], "user_reviewed": True, "candidate": artifact_ref(path, base), "geometry_sha256": candidate["geometry_sha256"], "hypothesis_signature_sha256": candidate["hypothesis_signature_sha256"], "target_signature_sha256": candidate["target_signature_sha256"]})
    require(sum(entry["role"] == "primary" for entry in entries) == 1, "portfolio requires exactly one primary seed")
    require(sum(entry["role"] == "backup" for entry in entries) <= 1, "portfolio permits at most one backup")
    require(len({entry["geometry_sha256"] for entry in entries}) == len(entries), "duplicate structural variants are forbidden")
    require(len({entry["hypothesis_signature_sha256"] for entry in entries}) == len(entries), "same-hypothesis cosmetic permutations are forbidden")
    require(len({entry["target_signature_sha256"] for entry in entries}) == 1 and all(candidate["target_id"] == source["target_id"] for candidate in candidates), "portfolio candidates must share one exact target")
    exception = source["exception_review"]
    if len(entries) <= 2:
        require(exception == {"approved": False, "new_scientific_rationale": None, "user_reviewed": False}, "normal 1+1 portfolio must not claim an exception")
        require(all(entry["role"] in {"primary", "backup"} for entry in entries), "additional role requires an exception")
    else:
        require(exception["approved"] is True and exception["user_reviewed"] is True, "more than 1+1 seeds require explicit exception review")
        _nonempty(exception["new_scientific_rationale"], "exception new scientific rationale")
        require(all(entry["role"] == "additional" for entry in entries[2:]), "seeds beyond 1+1 must use additional role")
    document = {"schema": PORTFOLIO_SCHEMA, "portfolio_id": source["portfolio_id"], "target_id": source["target_id"], "target_signature_sha256": entries[0]["target_signature_sha256"], "entries": entries, "policy": {"normal_limit": 2, "primary_count": 1, "backup_count": sum(entry["role"] == "backup" for entry in entries), "exception_review": exception, "deduplication": "geometry_and_scientific_hypothesis"}, "review": source["review"], "calculation_ready": False, "executable": False, "no_submission_authorization": True}
    document["payload_sha256"] = payload_sha256(document)
    validate_portfolio(document, source_path, verify_candidates=False)
    return document


def validate_portfolio(document: dict[str, Any], path: Path, verify_candidates: bool = True) -> None:
    validate_schema(document, PORTFOLIO_SCHEMA)
    require(document["calculation_ready"] is False and document["executable"] is False and document["no_submission_authorization"] is True, "TS seed portfolio must remain non-executable")
    require(document["policy"]["normal_limit"] == 2 and document["policy"]["primary_count"] == 1 and document["policy"]["backup_count"] <= 1, "1+1 portfolio policy drift")
    entries = document["entries"]
    require(sum(item["role"] == "primary" for item in entries) == 1, "portfolio requires exactly one primary")
    require(len({item["geometry_sha256"] for item in entries}) == len(entries), "duplicate structural variants are forbidden")
    require(len({item["hypothesis_signature_sha256"] for item in entries}) == len(entries), "same-hypothesis cosmetic permutations are forbidden")
    require(all(item["target_signature_sha256"] == document["target_signature_sha256"] for item in entries), "portfolio target binding drift")
    if len(entries) > 2:
        exception = document["policy"]["exception_review"]
        require(exception["approved"] is True and exception["user_reviewed"] is True and isinstance(exception["new_scientific_rationale"], str) and exception["new_scientific_rationale"].strip(), "extra candidates require a new scientific rationale and user review")
    if verify_candidates:
        base = path.resolve().parent
        for index, entry in enumerate(entries):
            ref = validate_artifact_ref(entry["candidate"], base, f"entries[{index}].candidate")
            candidate_path = _safe_relative(ref["path"], base, f"entries[{index}].candidate")
            candidate = load_json(candidate_path)
            validate_candidate(candidate, candidate_path)
            for key in ("geometry_sha256", "hypothesis_signature_sha256", "target_signature_sha256"):
                require(entry[key] == candidate[key], f"portfolio candidate {key} drift")
    require(document["payload_sha256"] == payload_sha256(document), "portfolio payload hash mismatch")


def _locations() -> tuple[Path, Path]:
    here = Path(__file__).resolve()
    installed = here.parents[1]
    if (installed / "contracts" / "ts-seed").is_dir():
        return installed / "contracts" / "ts-seed", here.parent / "validate_asymmetric_contract.py"
    repo = here.parents[3]
    return repo / "contracts" / "ts-seed", repo / "scripts" / "validate_asymmetric_contract.py"


def validate_schema(document: dict[str, Any], schema_id: str) -> None:
    schema_dir, validator_path = _locations()
    filename = "candidate.schema.json" if schema_id == CANDIDATE_SCHEMA else "portfolio.schema.json"
    spec = importlib.util.spec_from_file_location("ts_seed_schema_validator", validator_path)
    require(spec is not None and spec.loader is not None, "schema validator is unavailable")
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    schema = load_json(schema_dir / filename)
    module.validate_schema_document(schema)
    module._validate_schema_instance(document, schema, schema)


def write_new_json(path: Path, document: dict[str, Any]) -> None:
    require(not path.exists(), f"refusing to overwrite {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
