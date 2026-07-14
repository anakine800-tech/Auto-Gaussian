#!/usr/bin/env python3
"""Deterministic offline builders for reaction-study intake artifacts.

This module uses only the Python standard library.  It never invokes Gaussian,
SSH, PBS, qsub, qdel, deployment, ChemDraw, or any subprocess.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import re
import sys
from pathlib import Path
from typing import Any, Iterable


ID_RE = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
ELEMENT_RE = re.compile(r"^[A-Z][a-z]?$" )
FORMULA_TOKEN_RE = re.compile(r"([A-Z][a-z]?)([0-9]*)")

INTAKE_REQUEST_SCHEMA = "gaussian-reaction-intake-request/1"
INTAKE_SCHEMA = "gaussian-reaction-intake/1"
REGISTRY_REVIEW_SCHEMA = "gaussian-reaction-species-review/1"
REGISTRY_SCHEMA = "gaussian-reaction-species-registry/1"
CONDITION_REVIEW_SCHEMA = "gaussian-reaction-condition-review/1"
CONDITION_SCHEMA = "gaussian-reaction-condition-model/1"

SOURCE_ROLES = {
    "chemdraw_source",
    "scheme_image",
    "normalized_transcription",
    "supporting_information",
    "experimental_reference",
    "other",
}
CLAIM_QUESTIONS = {
    "feasibility",
    "thermodynamics",
    "elementary_barrier",
    "mechanism_comparison",
    "selectivity",
    "catalytic_turnover",
    "literature_reproduction",
    "custom",
}
REVIEW_DECISIONS = {"accepted", "accepted_with_blockers", "blocked"}
SPECIES_ORIGINS = {
    "drawn_species",
    "condition_component",
    "unshown_species",
    "workup_species",
    "model_species",
}
REVIEW_STATUSES = {"reviewed", "not_applicable", "not_assessed", "unresolved", "blocked"}
CONDITION_TREATMENTS = {
    "explicit_component",
    "continuum_environment",
    "chemical_potential",
    "computational_parameter",
    "experimental_context_only",
    "excluded_spectator",
    "workup_only",
    "unresolved",
}
CONDITION_FIELD_KINDS = (
    "temperature",
    "time",
    "pressure",
    "atmosphere",
    "concentration",
    "yield",
    "selectivity",
    "workup",
    "purification",
)


class OfflineError(ValueError):
    """An offline input violated the reaction-workflow contract."""


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


def load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=_reject_json_constant,
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise OfflineError(f"could not read JSON {path}: {exc}") from exc
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


def write_json(path: Path, data: Any) -> None:
    require(not path.exists(), f"refusing to overwrite existing artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(data))


def payload_sha256(data: dict[str, Any]) -> str:
    payload = copy.deepcopy(data)
    payload.pop("payload_sha256", None)
    return sha256_data(payload)


def finalize_artifact(data: dict[str, Any]) -> dict[str, Any]:
    data["payload_sha256"] = payload_sha256(data)
    return data


def validate_payload_hash(data: dict[str, Any]) -> None:
    value = data.get("payload_sha256")
    require(isinstance(value, str) and SHA256_RE.fullmatch(value) is not None, "artifact payload SHA-256 is invalid")
    require(value == payload_sha256(data), "artifact payload SHA-256 mismatch")


def _require_id(value: Any, label: str) -> str:
    require(isinstance(value, str) and ID_RE.fullmatch(value) is not None, f"invalid {label}")
    return value


def _require_string(value: Any, label: str, *, allow_empty: bool = False) -> str:
    require(isinstance(value, str), f"{label} must be a string")
    if not allow_empty:
        require(bool(value.strip()), f"{label} must not be empty")
    return value


def _string_list(value: Any, label: str, *, nonempty: bool = False) -> list[str]:
    require(isinstance(value, list), f"{label} must be an array")
    require(all(isinstance(item, str) and item.strip() for item in value), f"{label} must contain non-empty strings")
    if nonempty:
        require(bool(value), f"{label} must not be empty")
    return list(value)


def _require_exact_keys(data: dict[str, Any], allowed: set[str], required: set[str], label: str) -> None:
    unknown = sorted(set(data) - allowed)
    missing = sorted(required - set(data))
    require(not unknown, f"{label} contains unknown fields: {', '.join(unknown)}")
    require(not missing, f"{label} is missing required fields: {', '.join(missing)}")


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _positive_integer(value: Any, label: str) -> int:
    require(isinstance(value, int) and not isinstance(value, bool) and value > 0, f"{label} must be a positive integer")
    return value


def _parse_formula(value: Any, label: str) -> dict[str, int]:
    formula = _require_string(value, label)
    position = 0
    counts: dict[str, int] = {}
    for match in FORMULA_TOKEN_RE.finditer(formula):
        require(match.start() == position, f"{label} uses unsupported formula syntax: {formula}")
        element = match.group(1)
        count = int(match.group(2) or "1")
        require(count > 0, f"{label} contains a non-positive element count")
        counts[element] = counts.get(element, 0) + count
        position = match.end()
    require(position == len(formula) and counts, f"{label} uses unsupported formula syntax: {formula}")
    return counts


def _resolve_file(raw: Any, owner: Path, label: str) -> tuple[Path, str]:
    path_text = _require_string(raw, f"{label}.path")
    require("://" not in path_text, f"{label}.path must be a local file")
    path = Path(path_text)
    if not path.is_absolute():
        path = owner.parent / path
    require(path.is_file(), f"{label} file not found: {path}")
    require(not path.is_symlink(), f"{label} file must not be a symlink: {path}")
    return path, path_text


def _artifact_ref(path: Path, display_path: str | None = None) -> dict[str, Any]:
    require(path.is_file() and not path.is_symlink(), f"artifact is missing or a symlink: {path}")
    return {
        "path": display_path if display_path is not None else str(path),
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


def _artifact_input_ref(path: Path, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": str(path),
        "sha256": sha256_file(path),
        "payload_sha256": data["payload_sha256"],
    }


def _slug_step(index: int) -> str:
    return f"step_{index:03d}"


def _source_entity(item: Any, label: str) -> dict[str, Any]:
    if isinstance(item, str):
        require(item.strip(), f"{label} requires a non-empty label")
        return {"label": item}
    require(isinstance(item, dict), f"{label} must be an object or string")
    result = copy.deepcopy(item)
    _require_string(result.get("label"), f"{label}.label")
    return result


def _validate_normalized_scheme(data: dict[str, Any]) -> list[dict[str, Any]]:
    _require_string(data.get("scheme_id"), "normalized scheme scheme_id")
    raw_steps = data.get("steps")
    require(isinstance(raw_steps, list) and raw_steps, "normalized scheme steps must be a non-empty array")
    source_step_ids: set[str] = set()
    normalized_steps: list[dict[str, Any]] = []
    for index, raw_step in enumerate(raw_steps, start=1):
        require(isinstance(raw_step, dict), f"normalized scheme steps[{index - 1}] must be an object")
        source_step_id = str(raw_step.get("step_id", index)).strip()
        require(source_step_id and source_step_id not in source_step_ids, "normalized scheme step IDs must be unique and non-empty")
        source_step_ids.add(source_step_id)
        arrow = raw_step.get("arrow")
        require(isinstance(arrow, dict), f"normalized scheme step {source_step_id} requires an arrow object")
        _require_string(arrow.get("type"), f"normalized scheme step {source_step_id} arrow.type")
        _require_string(arrow.get("direction"), f"normalized scheme step {source_step_id} arrow.direction")
        reactants = raw_step.get("reactants", [])
        products = raw_step.get("products", [])
        components = raw_step.get("components", [])
        require(isinstance(reactants, list), f"normalized scheme step {source_step_id} reactants must be an array")
        require(isinstance(products, list), f"normalized scheme step {source_step_id} products must be an array")
        require(isinstance(components, list), f"normalized scheme step {source_step_id} components must be an array")

        step_id = _slug_step(index)
        step: dict[str, Any] = {
            "step_id": step_id,
            "source_step_id": source_step_id,
            "arrow": copy.deepcopy(arrow),
            "reactants": [],
            "products": [],
            "condition_items": [],
            "text_above": copy.deepcopy(raw_step.get("text_above", [])),
            "text_below": copy.deepcopy(raw_step.get("text_below", [])),
            "confidence": str(raw_step.get("confidence", "certain")),
            "notes": copy.deepcopy(raw_step.get("notes", [])),
        }
        for side, items in (("reactant", reactants), ("product", products)):
            for entity_index, entity in enumerate(items, start=1):
                record = _source_entity(entity, f"step {source_step_id} {side}[{entity_index - 1}]")
                record["occurrence_id"] = f"{step_id}_{side}_{entity_index:03d}"
                record["side"] = side
                step[f"{side}s"].append(record)
        for component_index, raw_component in enumerate(components, start=1):
            require(isinstance(raw_component, dict), f"step {source_step_id} component {component_index} must be an object")
            component = copy.deepcopy(raw_component)
            _require_string(component.get("raw_text"), f"step {source_step_id} component {component_index}.raw_text")
            _require_string(component.get("role"), f"step {source_step_id} component {component_index}.role")
            component["condition_id"] = f"{step_id}_component_{component_index:03d}"
            component["kind"] = "component"
            step["condition_items"].append(component)
        field_index = 0
        for kind in CONDITION_FIELD_KINDS:
            value = raw_step.get(kind)
            if value in (None, "", [], {}):
                continue
            field_index += 1
            step["condition_items"].append({
                "condition_id": f"{step_id}_field_{field_index:03d}",
                "kind": kind,
                "source_value": copy.deepcopy(value),
            })
        normalized_steps.append(step)
    return normalized_steps


def _blocker(blocker_id: str, scope: str, description: str, required_for: Iterable[str]) -> dict[str, Any]:
    return {
        "blocker_id": blocker_id,
        "scope": scope,
        "description": description,
        "required_for": sorted(set(required_for)),
    }


def _sort_blockers(blockers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for blocker in sorted(blockers, key=lambda item: item["blocker_id"]):
        blocker_id = _require_id(blocker.get("blocker_id"), "blocker_id")
        require(blocker_id not in seen, f"duplicate blocker_id: {blocker_id}")
        seen.add(blocker_id)
        result.append(blocker)
    return result


def _gate_status(decision: str, blockers: list[dict[str, Any]]) -> str:
    if decision == "blocked":
        return "blocked"
    if blockers:
        return "reviewed_with_blockers"
    return "reviewed"


def build_intake(request_path: Path, scheme_path: Path, output: Path) -> dict[str, Any]:
    request = load_json(request_path)
    _require_exact_keys(
        request,
        {"schema", "study_id", "source_files", "claim_scope", "unresolved_transcription", "review_decision", "review_notes"},
        {"schema", "study_id", "source_files", "claim_scope", "unresolved_transcription", "review_decision", "review_notes"},
        "intake request",
    )
    require(request["schema"] == INTAKE_REQUEST_SCHEMA, "unrecognized intake-request schema")
    study_id = _require_id(request["study_id"], "study_id")
    decision = _require_string(request["review_decision"], "review_decision")
    require(decision in REVIEW_DECISIONS, "invalid intake review_decision")
    review_notes = _string_list(request["review_notes"], "review_notes")

    claim_scope = request["claim_scope"]
    require(isinstance(claim_scope, dict), "claim_scope must be an object")
    _require_exact_keys(
        claim_scope,
        {"questions", "claim_ceiling", "non_goals", "custom_question"},
        {"questions", "claim_ceiling", "non_goals"},
        "claim_scope",
    )
    questions = _string_list(claim_scope["questions"], "claim_scope.questions", nonempty=True)
    require(set(questions) <= CLAIM_QUESTIONS, "claim_scope.questions contains an unsupported value")
    if "custom" in questions:
        _require_string(claim_scope.get("custom_question"), "claim_scope.custom_question")
    _require_string(claim_scope["claim_ceiling"], "claim_scope.claim_ceiling")
    _string_list(claim_scope["non_goals"], "claim_scope.non_goals")

    source_files = request["source_files"]
    require(isinstance(source_files, list) and source_files, "source_files must be a non-empty array")
    normalized_sources: list[dict[str, Any]] = []
    source_ids: set[str] = set()
    source_roles: set[str] = set()
    for index, source in enumerate(source_files):
        require(isinstance(source, dict), f"source_files[{index}] must be an object")
        _require_exact_keys(source, {"source_id", "path", "role", "description"}, {"source_id", "path", "role", "description"}, f"source_files[{index}]")
        source_id = _require_id(source["source_id"], f"source_files[{index}].source_id")
        require(source_id not in source_ids, f"duplicate source_id: {source_id}")
        source_ids.add(source_id)
        role = _require_string(source["role"], f"source_files[{index}].role")
        require(role in SOURCE_ROLES, f"invalid source role: {role}")
        source_roles.add(role)
        path, display_path = _resolve_file(source["path"], request_path, f"source_files[{index}]")
        normalized_sources.append({
            "source_id": source_id,
            "role": role,
            "description": _require_string(source["description"], f"source_files[{index}].description"),
            "artifact": _artifact_ref(path, display_path),
        })
    require("chemdraw_source" in source_roles or "scheme_image" in source_roles, "source_files requires a ChemDraw source or scheme image")

    require(scheme_path.is_file() and not scheme_path.is_symlink(), "normalized scheme is missing or a symlink")
    scheme = load_json(scheme_path)
    steps = _validate_normalized_scheme(scheme)

    blockers: list[dict[str, Any]] = []
    unresolved = request["unresolved_transcription"]
    require(isinstance(unresolved, list), "unresolved_transcription must be an array")
    for index, raw in enumerate(unresolved):
        require(isinstance(raw, dict), f"unresolved_transcription[{index}] must be an object")
        _require_exact_keys(raw, {"blocker_id", "scope", "description", "required_for"}, {"blocker_id", "scope", "description", "required_for"}, f"unresolved_transcription[{index}]")
        blockers.append(_blocker(
            _require_id(raw["blocker_id"], f"unresolved_transcription[{index}].blocker_id"),
            _require_string(raw["scope"], f"unresolved_transcription[{index}].scope"),
            _require_string(raw["description"], f"unresolved_transcription[{index}].description"),
            _string_list(raw["required_for"], f"unresolved_transcription[{index}].required_for", nonempty=True),
        ))
    for step in steps:
        if not step["reactants"]:
            blockers.append(_blocker(
                f"{step['step_id']}_missing_reactants",
                step["step_id"],
                "No reactant structure or explicit unresolved reactant is recorded.",
                ("species_registry", "reaction_network"),
            ))
        if not step["products"]:
            blockers.append(_blocker(
                f"{step['step_id']}_missing_products",
                step["step_id"],
                "No product structure or explicit unresolved product is recorded.",
                ("species_registry", "reaction_network"),
            ))
        if step["confidence"] not in {"certain", "probable"}:
            blockers.append(_blocker(
                f"{step['step_id']}_transcription_confidence",
                step["step_id"],
                f"Step transcription confidence is {step['confidence']}.",
                ("species_registry", "condition_model"),
            ))
        for side in ("reactants", "products"):
            for entity in step[side]:
                if entity.get("confidence") in {"uncertain", "unresolved"}:
                    blockers.append(_blocker(
                        f"{entity['occurrence_id']}_confidence",
                        entity["occurrence_id"],
                        f"Drawn-species transcription confidence is {entity['confidence']}.",
                        ("species_registry", "reaction_network"),
                    ))
        for condition in step["condition_items"]:
            if condition.get("confidence") in {"uncertain", "unresolved"}:
                blockers.append(_blocker(
                    f"{condition['condition_id']}_confidence",
                    condition["condition_id"],
                    f"Condition transcription confidence is {condition['confidence']}.",
                    ("condition_model",),
                ))
    blockers = _sort_blockers(blockers)
    artifact = {
        "schema": INTAKE_SCHEMA,
        "study_id": study_id,
        "source_package": {
            "request": _artifact_ref(request_path),
            "normalized_scheme": _artifact_ref(scheme_path),
            "source_files": sorted(normalized_sources, key=lambda item: item["source_id"]),
            "scheme_id": scheme["scheme_id"],
        },
        "claim_scope": copy.deepcopy(claim_scope),
        "steps": steps,
        "blockers": blockers,
        "review": {"decision": decision, "notes": review_notes},
        "gate_status": _gate_status(decision, blockers),
        "calculation_ready": False,
        "no_submission_authorization": True,
    }
    finalize_artifact(artifact)
    write_json(output, artifact)
    return artifact


def _load_intake(path: Path) -> dict[str, Any]:
    intake = load_json(path)
    require(intake.get("schema") == INTAKE_SCHEMA, "unrecognized reaction-intake schema")
    validate_payload_hash(intake)
    require(intake.get("calculation_ready") is False and intake.get("no_submission_authorization") is True, "reaction intake violates offline safety flags")
    _require_id(intake.get("study_id"), "intake study_id")
    return intake


def _all_source_ids(intake: dict[str, Any]) -> tuple[set[str], set[str]]:
    occurrences: set[str] = set()
    conditions: set[str] = set()
    for step in intake.get("steps", []):
        for side in ("reactants", "products"):
            for item in step.get(side, []):
                occurrences.add(item["occurrence_id"])
        for item in step.get("condition_items", []):
            conditions.add(item["condition_id"])
    return occurrences, conditions


def _occurrence_context(intake: dict[str, Any]) -> dict[str, tuple[str, str]]:
    result: dict[str, tuple[str, str]] = {}
    for step in intake.get("steps", []):
        for side in ("reactants", "products"):
            chemical_side = "reactant" if side == "reactants" else "product"
            for item in step.get(side, []):
                result[item["occurrence_id"]] = (step["step_id"], chemical_side)
    return result


def _normalize_atom_identity(value: Any, species_id: str) -> dict[str, Any]:
    require(isinstance(value, dict), f"species {species_id} atom_identity must be an object")
    _require_exact_keys(value, {"status", "atom_scope", "atoms", "notes"}, {"status", "atom_scope", "atoms", "notes"}, f"species {species_id} atom_identity")
    status = _require_string(value["status"], f"species {species_id} atom_identity.status")
    require(status in REVIEW_STATUSES, f"species {species_id} atom_identity.status is invalid")
    atom_scope = _require_string(value["atom_scope"], f"species {species_id} atom_identity.atom_scope")
    require(atom_scope in {"explicit_structure_atoms", "heavy_atoms_only", "not_assessed"}, f"species {species_id} atom_identity.atom_scope is invalid")
    atoms = value["atoms"]
    require(isinstance(atoms, list), f"species {species_id} atom_identity.atoms must be an array")
    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for index, atom in enumerate(atoms, start=1):
        require(isinstance(atom, dict), f"species {species_id} atom {index} must be an object")
        _require_exact_keys(atom, {"atom_id", "element", "structure_index", "isotope"}, {"atom_id", "element", "structure_index"}, f"species {species_id} atom {index}")
        atom_id = _require_id(atom["atom_id"], f"species {species_id} atom_id")
        require(atom_id not in seen, f"species {species_id} has duplicate atom_id {atom_id}")
        seen.add(atom_id)
        element = _require_string(atom["element"], f"species {species_id} atom {atom_id}.element")
        require(ELEMENT_RE.fullmatch(element) is not None, f"species {species_id} atom {atom_id} has invalid element")
        structure_index = atom["structure_index"]
        require(isinstance(structure_index, int) and not isinstance(structure_index, bool) and structure_index == index, f"species {species_id} atom indices must be contiguous and one-based")
        record = {"atom_id": atom_id, "element": element, "structure_index": structure_index}
        if "isotope" in atom:
            isotope = atom["isotope"]
            require(isotope is None or (isinstance(isotope, int) and not isinstance(isotope, bool) and isotope > 0), f"species {species_id} atom {atom_id} isotope is invalid")
            record["isotope"] = isotope
        normalized.append(record)
    if status == "reviewed":
        require(atoms, f"species {species_id} reviewed atom identity requires atoms")
        require(atom_scope != "not_assessed", f"species {species_id} reviewed atom identity requires an assessed scope")
    return {"status": status, "atom_scope": atom_scope, "atoms": normalized, "notes": _string_list(value["notes"], f"species {species_id} atom_identity.notes")}


def _normalize_species(raw: Any, review_path: Path, known_source_ids: set[str]) -> dict[str, Any]:
    require(isinstance(raw, dict), "species entry must be an object")
    allowed = {
        "species_id", "preferred_label", "origin", "required_for_claim", "source_refs",
        "represented_form", "structure", "formula", "formal_charge", "multiplicity",
        "component_count", "stereochemistry_status", "protonation_status",
        "salt_solvate_status", "atom_identity", "review_status", "blockers", "notes",
    }
    _require_exact_keys(raw, allowed, allowed, "species entry")
    species_id = _require_id(raw["species_id"], "species_id")
    origin = _require_string(raw["origin"], f"species {species_id}.origin")
    require(origin in SPECIES_ORIGINS, f"species {species_id} has invalid origin")
    required_for_claim = raw["required_for_claim"]
    require(isinstance(required_for_claim, bool), f"species {species_id}.required_for_claim must be boolean")
    source_refs = _string_list(raw["source_refs"], f"species {species_id}.source_refs")
    unknown_sources = sorted(set(source_refs) - known_source_ids)
    require(not unknown_sources, f"species {species_id} references unknown source IDs: {', '.join(unknown_sources)}")
    structure = raw["structure"]
    structure_ref = None
    if structure is not None:
        require(isinstance(structure, dict), f"species {species_id}.structure must be an object or null")
        _require_exact_keys(structure, {"path", "format", "representation_limits"}, {"path", "format", "representation_limits"}, f"species {species_id}.structure")
        path, display_path = _resolve_file(structure["path"], review_path, f"species {species_id}.structure")
        structure_ref = {
            **_artifact_ref(path, display_path),
            "format": _require_string(structure["format"], f"species {species_id}.structure.format"),
            "representation_limits": _string_list(structure["representation_limits"], f"species {species_id}.structure.representation_limits"),
        }
    formal_charge = raw["formal_charge"]
    require(formal_charge is None or (isinstance(formal_charge, int) and not isinstance(formal_charge, bool)), f"species {species_id}.formal_charge must be integer or null")
    multiplicity = raw["multiplicity"]
    require(multiplicity is None or (isinstance(multiplicity, int) and not isinstance(multiplicity, bool) and multiplicity > 0), f"species {species_id}.multiplicity must be positive integer or null")
    component_count = raw["component_count"]
    require(component_count is None or (isinstance(component_count, int) and not isinstance(component_count, bool) and component_count > 0), f"species {species_id}.component_count must be positive integer or null")
    for field in ("stereochemistry_status", "protonation_status", "salt_solvate_status", "review_status"):
        status = _require_string(raw[field], f"species {species_id}.{field}")
        require(status in REVIEW_STATUSES, f"species {species_id}.{field} is invalid")
    formula = raw["formula"]
    require(formula is None or (isinstance(formula, str) and formula.strip()), f"species {species_id}.formula must be a non-empty string or null")
    return {
        "species_id": species_id,
        "preferred_label": _require_string(raw["preferred_label"], f"species {species_id}.preferred_label"),
        "origin": origin,
        "required_for_claim": required_for_claim,
        "source_refs": sorted(set(source_refs)),
        "represented_form": _require_string(raw["represented_form"], f"species {species_id}.represented_form"),
        "structure": structure_ref,
        "formula": formula,
        "formal_charge": formal_charge,
        "multiplicity": multiplicity,
        "component_count": component_count,
        "stereochemistry_status": raw["stereochemistry_status"],
        "protonation_status": raw["protonation_status"],
        "salt_solvate_status": raw["salt_solvate_status"],
        "atom_identity": _normalize_atom_identity(raw["atom_identity"], species_id),
        "review_status": raw["review_status"],
        "blockers": _string_list(raw["blockers"], f"species {species_id}.blockers"),
        "notes": _string_list(raw["notes"], f"species {species_id}.notes"),
    }


def build_registry(intake_path: Path, review_path: Path, output: Path) -> dict[str, Any]:
    intake = _load_intake(intake_path)
    review = load_json(review_path)
    _require_exact_keys(
        review,
        {"schema", "study_id", "intake_payload_sha256", "species", "source_bindings", "balance_review", "review_decision", "review_notes"},
        {"schema", "study_id", "intake_payload_sha256", "species", "source_bindings", "balance_review", "review_decision", "review_notes"},
        "species review",
    )
    require(review["schema"] == REGISTRY_REVIEW_SCHEMA, "unrecognized species-review schema")
    require(review["study_id"] == intake["study_id"], "species review study_id differs from intake")
    require(review["intake_payload_sha256"] == intake["payload_sha256"], "species review intake hash mismatch")
    decision = _require_string(review["review_decision"], "species review_decision")
    require(decision in REVIEW_DECISIONS, "invalid species review_decision")

    occurrence_ids, condition_ids = _all_source_ids(intake)
    known_source_ids = occurrence_ids | condition_ids
    raw_species = review["species"]
    require(isinstance(raw_species, list) and raw_species, "species review requires a non-empty species array")
    species = [_normalize_species(item, review_path, known_source_ids) for item in raw_species]
    species_ids = [item["species_id"] for item in species]
    require(len(species_ids) == len(set(species_ids)), "species IDs must be unique")
    species_index = {item["species_id"]: item for item in species}

    raw_bindings = review["source_bindings"]
    require(isinstance(raw_bindings, list), "source_bindings must be an array")
    bindings: list[dict[str, str]] = []
    bound_sources: set[str] = set()
    for index, binding in enumerate(raw_bindings):
        require(isinstance(binding, dict), f"source_bindings[{index}] must be an object")
        _require_exact_keys(binding, {"source_id", "species_id", "coefficient"}, {"source_id", "species_id", "coefficient"}, f"source_bindings[{index}]")
        source_id = _require_string(binding["source_id"], f"source_bindings[{index}].source_id")
        species_id = _require_id(binding["species_id"], f"source_bindings[{index}].species_id")
        require(source_id in known_source_ids, f"source binding references unknown source ID: {source_id}")
        require(species_id in species_index, f"source binding references unknown species ID: {species_id}")
        require(source_id not in bound_sources, f"source ID is bound more than once: {source_id}")
        require(source_id in species_index[species_id]["source_refs"], f"source binding {source_id} is absent from species {species_id}.source_refs")
        coefficient = _positive_integer(binding["coefficient"], f"source_bindings[{index}].coefficient")
        bound_sources.add(source_id)
        bindings.append({"source_id": source_id, "species_id": species_id, "coefficient": coefficient})
    missing_occurrences = sorted(occurrence_ids - bound_sources)
    require(not missing_occurrences, f"every drawn reactant/product occurrence must be bound; missing: {', '.join(missing_occurrences)}")

    balance = review["balance_review"]
    require(isinstance(balance, dict), "balance_review must be an object")
    _require_exact_keys(balance, {"status", "element_balance", "charge_balance", "unshown_species", "notes"}, {"status", "element_balance", "charge_balance", "unshown_species", "notes"}, "balance_review")
    for field in ("status", "element_balance", "charge_balance"):
        value = _require_string(balance[field], f"balance_review.{field}")
        require(value in {"passed", "blocked", "not_assessed", "not_applicable"}, f"balance_review.{field} is invalid")
    raw_unshown = balance["unshown_species"]
    require(isinstance(raw_unshown, list), "balance_review.unshown_species must be an array")
    step_ids = {step["step_id"] for step in intake.get("steps", [])}
    unshown: list[dict[str, Any]] = []
    for index, entry in enumerate(raw_unshown):
        require(isinstance(entry, dict), f"balance_review.unshown_species[{index}] must be an object")
        _require_exact_keys(entry, {"species_id", "step_id", "side", "coefficient"}, {"species_id", "step_id", "side", "coefficient"}, f"balance_review.unshown_species[{index}]")
        species_id = _require_id(entry["species_id"], f"balance_review.unshown_species[{index}].species_id")
        require(species_id in species_index, f"balance review references unknown unshown species ID: {species_id}")
        require(species_index[species_id]["origin"] == "unshown_species", f"balance unshown species {species_id} must use origin unshown_species")
        step_id = _require_id(entry["step_id"], f"balance_review.unshown_species[{index}].step_id")
        require(step_id in step_ids, f"balance unshown species {species_id} references unknown step {step_id}")
        side = _require_string(entry["side"], f"balance_review.unshown_species[{index}].side")
        require(side in {"reactant", "product"}, f"balance unshown species {species_id} has invalid side")
        coefficient = _positive_integer(entry["coefficient"], f"balance_review.unshown_species[{index}].coefficient")
        unshown.append({"species_id": species_id, "step_id": step_id, "side": side, "coefficient": coefficient})

    occurrence_context = _occurrence_context(intake)
    terms: dict[str, dict[str, list[tuple[str, int]]]] = {
        step_id: {"reactant": [], "product": []} for step_id in step_ids
    }
    for binding in bindings:
        context = occurrence_context.get(binding["source_id"])
        if context is None:
            continue
        step_id, side = context
        terms[step_id][side].append((binding["species_id"], binding["coefficient"]))
    for entry in unshown:
        terms[entry["step_id"]][entry["side"]].append((entry["species_id"], entry["coefficient"]))

    computed_steps: list[dict[str, Any]] = []
    all_elements_balanced = True
    all_charges_balanced = True
    for step_id in sorted(step_ids):
        element_delta: dict[str, int] = {}
        charge_delta = 0
        complete = True
        for side, sign in (("reactant", -1), ("product", 1)):
            for species_id, coefficient in terms[step_id][side]:
                item = species_index[species_id]
                if item["formula"] is None or item["formal_charge"] is None:
                    complete = False
                    continue
                counts = _parse_formula(item["formula"], f"species {species_id}.formula")
                for element, count in counts.items():
                    element_delta[element] = element_delta.get(element, 0) + sign * coefficient * count
                charge_delta += sign * coefficient * item["formal_charge"]
        element_delta = {element: delta for element, delta in sorted(element_delta.items()) if delta != 0}
        elements_balanced = complete and not element_delta
        charges_balanced = complete and charge_delta == 0
        all_elements_balanced = all_elements_balanced and elements_balanced
        all_charges_balanced = all_charges_balanced and charges_balanced
        computed_steps.append({
            "step_id": step_id,
            "complete_inputs": complete,
            "element_delta_product_minus_reactant": element_delta,
            "charge_delta_product_minus_reactant": charge_delta if complete else None,
            "elements_balanced": elements_balanced,
            "charges_balanced": charges_balanced,
        })
    if balance["element_balance"] == "passed":
        require(all_elements_balanced, "balance review claims passed elemental balance but independent recomputation differs")
    if balance["charge_balance"] == "passed":
        require(all_charges_balanced, "balance review claims passed charge balance but independent recomputation differs")
    if balance["status"] == "passed":
        require(balance["element_balance"] == "passed" and balance["charge_balance"] == "passed", "overall passed balance requires passed elemental and charge reviews")

    blockers: list[dict[str, Any]] = []
    for item in species:
        if not item["required_for_claim"]:
            continue
        species_id = item["species_id"]
        missing: list[str] = []
        if item["structure"] is None:
            missing.append("reviewed structure")
        if item["formula"] is None:
            missing.append("formula")
        if item["formal_charge"] is None:
            missing.append("formal charge")
        if item["multiplicity"] is None:
            missing.append("multiplicity")
        if item["component_count"] is None:
            missing.append("component count")
        for field in ("stereochemistry_status", "protonation_status", "salt_solvate_status", "review_status"):
            if item[field] in {"not_assessed", "unresolved", "blocked"}:
                missing.append(field.replace("_", " "))
        if item["atom_identity"]["status"] != "reviewed":
            missing.append("stable atom identity")
        missing.extend(item["blockers"])
        if missing:
            blockers.append(_blocker(
                f"{species_id}_review",
                species_id,
                "Required species is not fully reviewed: " + "; ".join(sorted(set(missing))),
                ("reaction_network", "calculation_plan"),
            ))
    if balance["status"] != "passed" or balance["element_balance"] != "passed" or balance["charge_balance"] != "passed":
        blockers.append(_blocker(
            "reaction_balance_review",
            "reaction",
            "Elemental and charge balance are not both reviewed as passed.",
            ("reaction_network", "reference_state"),
        ))
    blockers = _sort_blockers(blockers)
    artifact = {
        "schema": REGISTRY_SCHEMA,
        "study_id": intake["study_id"],
        "intake": _artifact_input_ref(intake_path, intake),
        "review_source": _artifact_ref(review_path),
        "species": sorted(species, key=lambda item: item["species_id"]),
        "source_bindings": sorted(bindings, key=lambda item: item["source_id"]),
        "balance_review": {
            "status": balance["status"],
            "element_balance": balance["element_balance"],
            "charge_balance": balance["charge_balance"],
            "unshown_species": sorted(unshown, key=lambda item: (item["step_id"], item["side"], item["species_id"])),
            "computed_steps": computed_steps,
            "notes": _string_list(balance["notes"], "balance_review.notes"),
        },
        "blockers": blockers,
        "review": {"decision": decision, "notes": _string_list(review["review_notes"], "species review_notes")},
        "gate_status": _gate_status(decision, blockers),
        "calculation_ready": False,
        "no_submission_authorization": True,
    }
    finalize_artifact(artifact)
    write_json(output, artifact)
    return artifact


def _load_registry(path: Path) -> dict[str, Any]:
    registry = load_json(path)
    require(registry.get("schema") == REGISTRY_SCHEMA, "unrecognized species-registry schema")
    validate_payload_hash(registry)
    require(registry.get("calculation_ready") is False and registry.get("no_submission_authorization") is True, "species registry violates offline safety flags")
    return registry


def _verify_bound_artifact(reference: Any, owner_path: Path, expected_schema: str, label: str) -> dict[str, Any]:
    require(isinstance(reference, dict), f"{label} reference must be an object")
    _require_exact_keys(reference, {"path", "sha256", "payload_sha256"}, {"path", "sha256", "payload_sha256"}, f"{label} reference")
    raw_path = _require_string(reference["path"], f"{label}.path")
    path = Path(raw_path)
    if not path.is_absolute():
        path = owner_path.parent / path
    require(path.is_file() and not path.is_symlink(), f"{label} artifact is missing or a symlink: {path}")
    require(isinstance(reference["sha256"], str) and reference["sha256"] == sha256_file(path), f"{label} artifact file hash mismatch")
    source = load_json(path)
    require(source.get("schema") == expected_schema, f"{label} artifact schema mismatch")
    validate_payload_hash(source)
    require(reference["payload_sha256"] == source["payload_sha256"], f"{label} artifact payload hash mismatch")
    return source


def _normalize_global_policy(value: Any, field: str) -> dict[str, Any]:
    require(isinstance(value, dict), f"global_model.{field} must be an object")
    _require_exact_keys(value, {"status", "value", "unit", "model", "rationale"}, {"status", "value", "unit", "model", "rationale"}, f"global_model.{field}")
    status = _require_string(value["status"], f"global_model.{field}.status")
    require(status in {"reviewed", "not_applicable", "unresolved", "blocked"}, f"global_model.{field}.status is invalid")
    for key in ("value", "unit", "model"):
        entry = value[key]
        require(entry is None or isinstance(entry, (str, int, float, dict, list)), f"global_model.{field}.{key} has an invalid type")
        if isinstance(entry, float):
            require(_finite_number(entry), f"global_model.{field}.{key} must be finite")
    return {
        "status": status,
        "value": copy.deepcopy(value["value"]),
        "unit": copy.deepcopy(value["unit"]),
        "model": copy.deepcopy(value["model"]),
        "rationale": _require_string(value["rationale"], f"global_model.{field}.rationale", allow_empty=status == "not_applicable"),
    }


def build_condition_model(intake_path: Path, registry_path: Path, review_path: Path, output: Path) -> dict[str, Any]:
    intake = _load_intake(intake_path)
    registry = _load_registry(registry_path)
    require(registry.get("study_id") == intake["study_id"], "registry study_id differs from intake")
    require(registry.get("intake", {}).get("payload_sha256") == intake["payload_sha256"], "registry is not bound to the supplied intake")
    review = load_json(review_path)
    _require_exact_keys(
        review,
        {"schema", "study_id", "intake_payload_sha256", "registry_payload_sha256", "global_model", "decisions", "review_decision", "review_notes"},
        {"schema", "study_id", "intake_payload_sha256", "registry_payload_sha256", "global_model", "decisions", "review_decision", "review_notes"},
        "condition review",
    )
    require(review["schema"] == CONDITION_REVIEW_SCHEMA, "unrecognized condition-review schema")
    require(review["study_id"] == intake["study_id"], "condition review study_id differs from intake")
    require(review["intake_payload_sha256"] == intake["payload_sha256"], "condition review intake hash mismatch")
    require(review["registry_payload_sha256"] == registry["payload_sha256"], "condition review registry hash mismatch")
    decision = _require_string(review["review_decision"], "condition review_decision")
    require(decision in REVIEW_DECISIONS, "invalid condition review_decision")

    _, condition_ids = _all_source_ids(intake)
    species_ids = {item["species_id"] for item in registry.get("species", [])}
    global_model = review["global_model"]
    require(isinstance(global_model, dict), "global_model must be an object")
    required_global = {"standard_state", "temperature_policy", "concentration_policy", "pressure_policy", "explicit_component_policy"}
    _require_exact_keys(global_model, required_global, required_global, "global_model")
    normalized_global = {field: _normalize_global_policy(global_model[field], field) for field in sorted(required_global)}

    raw_decisions = review["decisions"]
    require(isinstance(raw_decisions, list), "condition decisions must be an array")
    seen: set[str] = set()
    decisions: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_decisions):
        require(isinstance(raw, dict), f"condition decisions[{index}] must be an object")
        _require_exact_keys(raw, {"condition_id", "treatment", "species_ids", "model", "rationale", "review_status"}, {"condition_id", "treatment", "species_ids", "model", "rationale", "review_status"}, f"condition decisions[{index}]")
        condition_id = _require_string(raw["condition_id"], f"condition decisions[{index}].condition_id")
        require(condition_id in condition_ids, f"condition decision references unknown condition ID: {condition_id}")
        require(condition_id not in seen, f"condition ID is decided more than once: {condition_id}")
        seen.add(condition_id)
        treatment = _require_string(raw["treatment"], f"condition {condition_id}.treatment")
        require(treatment in CONDITION_TREATMENTS, f"condition {condition_id} has invalid treatment")
        targets = _string_list(raw["species_ids"], f"condition {condition_id}.species_ids")
        require(set(targets) <= species_ids, f"condition {condition_id} references unknown species IDs")
        review_status = _require_string(raw["review_status"], f"condition {condition_id}.review_status")
        require(review_status in {"reviewed", "blocked"}, f"condition {condition_id}.review_status is invalid")
        model = copy.deepcopy(raw["model"])
        require(model is None or isinstance(model, dict), f"condition {condition_id}.model must be an object or null")
        rationale = _require_string(raw["rationale"], f"condition {condition_id}.rationale", allow_empty=treatment == "unresolved")
        if treatment == "explicit_component":
            require(targets, f"condition {condition_id} explicit_component requires species_ids")
        else:
            require(not targets, f"condition {condition_id} may use species_ids only for explicit_component")
        if treatment in {"continuum_environment", "chemical_potential", "computational_parameter"}:
            require(isinstance(model, dict) and model, f"condition {condition_id} treatment requires a non-empty model")
        if treatment == "unresolved" or review_status == "blocked":
            blockers.append(_blocker(
                f"{condition_id}_model",
                condition_id,
                "Condition-to-model treatment remains unresolved or blocked.",
                ("reaction_network", "protocol_selection", "reference_state"),
            ))
        decisions.append({
            "condition_id": condition_id,
            "treatment": treatment,
            "species_ids": sorted(set(targets)),
            "model": model,
            "rationale": rationale,
            "review_status": review_status,
        })
    missing = sorted(condition_ids - seen)
    require(not missing, f"every condition item must have exactly one decision; missing: {', '.join(missing)}")
    for field, policy in normalized_global.items():
        if policy["status"] in {"unresolved", "blocked"}:
            blockers.append(_blocker(
                f"{field}_model",
                field,
                f"Global condition policy {field} remains {policy['status']}.",
                ("protocol_selection", "reference_state"),
            ))
    blockers = _sort_blockers(blockers)
    artifact = {
        "schema": CONDITION_SCHEMA,
        "study_id": intake["study_id"],
        "intake": _artifact_input_ref(intake_path, intake),
        "species_registry": _artifact_input_ref(registry_path, registry),
        "review_source": _artifact_ref(review_path),
        "global_model": normalized_global,
        "decisions": sorted(decisions, key=lambda item: item["condition_id"]),
        "blockers": blockers,
        "review": {"decision": decision, "notes": _string_list(review["review_notes"], "condition review_notes")},
        "gate_status": _gate_status(decision, blockers),
        "calculation_ready": False,
        "no_submission_authorization": True,
    }
    finalize_artifact(artifact)
    write_json(output, artifact)
    return artifact


def validate_artifact(path: Path) -> dict[str, Any]:
    data = load_json(path)
    schema = data.get("schema")
    require(schema in {INTAKE_SCHEMA, REGISTRY_SCHEMA, CONDITION_SCHEMA}, "unsupported reaction-workflow artifact schema")
    validate_payload_hash(data)
    require(data.get("calculation_ready") is False, "artifact must remain calculation_ready: false")
    require(data.get("no_submission_authorization") is True, "artifact must retain no_submission_authorization: true")
    _require_id(data.get("study_id"), "study_id")
    require(data.get("gate_status") in {"reviewed", "reviewed_with_blockers", "blocked"}, "artifact gate_status is invalid")
    blockers = data.get("blockers")
    require(isinstance(blockers, list), "artifact blockers must be an array")
    _sort_blockers(copy.deepcopy(blockers))
    review = data.get("review")
    require(isinstance(review, dict), "artifact review must be an object")
    _require_exact_keys(review, {"decision", "notes"}, {"decision", "notes"}, "artifact review")
    decision = _require_string(review["decision"], "artifact review.decision")
    require(decision in REVIEW_DECISIONS, "artifact review.decision is invalid")
    _string_list(review["notes"], "artifact review.notes")
    require(data["gate_status"] == _gate_status(decision, blockers), "artifact gate_status is inconsistent with its review decision and blockers")

    if schema == INTAKE_SCHEMA:
        _require_exact_keys(
            data,
            {"schema", "study_id", "source_package", "claim_scope", "steps", "blockers", "review", "gate_status", "calculation_ready", "no_submission_authorization", "payload_sha256"},
            {"schema", "study_id", "source_package", "claim_scope", "steps", "blockers", "review", "gate_status", "calculation_ready", "no_submission_authorization", "payload_sha256"},
            "reaction intake",
        )
        steps = data.get("steps")
        require(isinstance(steps, list) and steps, "reaction intake requires steps")
        occurrence_ids, condition_ids = _all_source_ids(data)
        require(len(occurrence_ids) == sum(len(step.get(side, [])) for step in steps for side in ("reactants", "products")), "reaction intake contains duplicate occurrence IDs")
        require(len(condition_ids) == sum(len(step.get("condition_items", [])) for step in steps), "reaction intake contains duplicate condition IDs")
    elif schema == REGISTRY_SCHEMA:
        _require_exact_keys(
            data,
            {"schema", "study_id", "intake", "review_source", "species", "source_bindings", "balance_review", "blockers", "review", "gate_status", "calculation_ready", "no_submission_authorization", "payload_sha256"},
            {"schema", "study_id", "intake", "review_source", "species", "source_bindings", "balance_review", "blockers", "review", "gate_status", "calculation_ready", "no_submission_authorization", "payload_sha256"},
            "species registry",
        )
        intake = _verify_bound_artifact(data["intake"], path, INTAKE_SCHEMA, "registry intake")
        require(intake["study_id"] == data["study_id"], "registry study_id differs from bound intake")
        species = data.get("species")
        require(isinstance(species, list) and species, "registry species must be a non-empty array")
        species_ids = [item.get("species_id") for item in species if isinstance(item, dict)]
        require(len(species_ids) == len(species) and len(species_ids) == len(set(species_ids)), "registry species IDs must be present and unique")
        bindings = data.get("source_bindings")
        require(isinstance(bindings, list), "registry source_bindings must be an array")
        bound_sources = [item.get("source_id") for item in bindings if isinstance(item, dict)]
        require(len(bound_sources) == len(bindings) and len(bound_sources) == len(set(bound_sources)), "registry source bindings must be present and unique")
        balance = data.get("balance_review")
        require(isinstance(balance, dict) and isinstance(balance.get("computed_steps"), list), "registry balance_review requires computed_steps")
        if balance.get("element_balance") == "passed":
            require(all(step.get("elements_balanced") is True for step in balance["computed_steps"]), "registry passed elemental balance disagrees with computed steps")
        if balance.get("charge_balance") == "passed":
            require(all(step.get("charges_balanced") is True for step in balance["computed_steps"]), "registry passed charge balance disagrees with computed steps")
    else:
        _require_exact_keys(
            data,
            {"schema", "study_id", "intake", "species_registry", "review_source", "global_model", "decisions", "blockers", "review", "gate_status", "calculation_ready", "no_submission_authorization", "payload_sha256"},
            {"schema", "study_id", "intake", "species_registry", "review_source", "global_model", "decisions", "blockers", "review", "gate_status", "calculation_ready", "no_submission_authorization", "payload_sha256"},
            "condition model",
        )
        intake = _verify_bound_artifact(data["intake"], path, INTAKE_SCHEMA, "condition-model intake")
        registry = _verify_bound_artifact(data["species_registry"], path, REGISTRY_SCHEMA, "condition-model registry")
        require(intake["study_id"] == data["study_id"] == registry["study_id"], "condition-model study IDs differ")
        decisions = data.get("decisions")
        require(isinstance(decisions, list), "condition-model decisions must be an array")
        decided = [item.get("condition_id") for item in decisions if isinstance(item, dict)]
        require(len(decided) == len(decisions) and len(decided) == len(set(decided)), "condition-model decision IDs must be present and unique")
        _, expected_conditions = _all_source_ids(intake)
        require(set(decided) == expected_conditions, "condition-model decisions do not cover the exact intake conditions")
    return {
        "schema": "gaussian-reaction-workflow-validation/1",
        "artifact_schema": schema,
        "study_id": data["study_id"],
        "gate_status": data["gate_status"],
        "blocker_count": len(blockers),
        "payload_sha256": data["payload_sha256"],
        "live_actions": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    intake = subparsers.add_parser("build-intake", help="build a hash-bound reaction-intake artifact")
    intake.add_argument("request", type=Path)
    intake.add_argument("--scheme", type=Path, required=True)
    intake.add_argument("--output", type=Path, required=True)

    registry = subparsers.add_parser("build-registry", help="build a reviewed species registry")
    registry.add_argument("intake", type=Path)
    registry.add_argument("--review", type=Path, required=True)
    registry.add_argument("--output", type=Path, required=True)

    condition = subparsers.add_parser("build-condition-model", help="build an explicit condition-to-model artifact")
    condition.add_argument("intake", type=Path)
    condition.add_argument("registry", type=Path)
    condition.add_argument("--review", type=Path, required=True)
    condition.add_argument("--output", type=Path, required=True)

    validate = subparsers.add_parser("validate", help="validate one reaction-workflow artifact")
    validate.add_argument("artifact", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "build-intake":
            result = build_intake(args.request, args.scheme, args.output)
        elif args.command == "build-registry":
            result = build_registry(args.intake, args.review, args.output)
        elif args.command == "build-condition-model":
            result = build_condition_model(args.intake, args.registry, args.review, args.output)
        elif args.command == "validate":
            result = validate_artifact(args.artifact)
        else:  # pragma: no cover
            raise OfflineError(f"unsupported command: {args.command}")
    except (OfflineError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
