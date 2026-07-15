#!/usr/bin/env python3
"""Offline semantic checks for asymmetric-catalysis contract artifacts.

This validator uses only the Python standard library. It does not run Gaussian,
SSH, PBS, deployment commands, or any other subprocess.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse


SCHEMA_IDS = {
    "study": "gaussian-asymmetric-catalysis-study/1",
    "candidate": "gaussian-asymmetric-ts-candidate/1",
    "result": "gaussian-asymmetric-ts-result/1",
    "analysis": "gaussian-asymmetric-selectivity-analysis/1",
    "space": "gaussian-asymmetric-candidate-space-spec/1",
    "ledger": "gaussian-asymmetric-candidate-ledger/1",
    "energy-record": "gaussian-asymmetric-energy-record/1",
    "materializations": "gaussian-asymmetric-materializations/1",
    "metal-support": "gaussian-asymmetric-metal-support-design/1",
    "metal-ts-audit-template": "gaussian-asymmetric-metal-ts-audit-template/1",
    "metal-scientific-review-source": "gaussian-asymmetric-metal-scientific-review-source/1",
    "metal-scientific-review": "gaussian-asymmetric-metal-scientific-review/1",
    "metal-input-observation": "gaussian-asymmetric-metal-input-observation/1",
    "metal-result-observation": "gaussian-asymmetric-metal-result-observation/1",
    "metal-acceptance-review-source": "gaussian-asymmetric-metal-acceptance-review-source/1",
    "metal-acceptance-review": "gaussian-asymmetric-metal-acceptance-review/1",
    "smoke-proposal": "gaussian-asymmetric-smoke-proposal/1",
    "live-smoke-evidence": "gaussian-asymmetric-live-smoke-evidence/1",
    "literature-benchmark": "gaussian-asymmetric-literature-benchmark-ledger/1",
}
SCHEMAS = SCHEMA_IDS
SCHEMA_KINDS = {schema_id: kind for kind, schema_id in SCHEMA_IDS.items()}
SCHEMA_DIR = Path(__file__).resolve().parents[1] / "contracts" / "asymmetric-catalysis"
ID_RE = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
HASH_RE = re.compile(r"^[a-f0-9]{64}$")
PLACEHOLDER_RE = re.compile(r"(?:<[^>]+>|\bTBD\b|\bTODO\b|approved route)", re.I)
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
VALIDATION_RANK = {
    "failed": 0,
    "first_order_saddle_candidate": 1,
    "mode_reviewed": 2,
    "path_validated": 3,
}
METAL_REVIEW_SECTIONS = {
    "electron_accounting", "spin_surface", "wavefunction",
    "coordination", "method_protocol", "ts_and_path",
}
METAL_SEED_STRATEGIES = {
    "single_guess_hessian_guided", "endpoint_qst2_qst3",
    "reviewed_relaxed_coordinate_scan",
}
METAL_ACCEPTANCE_SECTIONS = {"wavefunction", "coordination", "mode", "input_acceptance"}
METAL_ACCEPTANCE_DECISIONS = {
    "accepted_for_bounded_offline_review", "rejected_by_reviewer", "blocked_missing_evidence",
}
SUPPORTED_SCHEMA_KEYWORDS = {
    "$schema", "$id", "$defs", "$ref", "$comment", "title", "description", "default", "examples",
    "type", "const", "enum", "allOf", "anyOf", "oneOf", "not", "required", "properties",
    "additionalProperties", "propertyNames", "items", "minItems", "maxItems", "uniqueItems",
    "minProperties", "maxProperties", "minLength", "maxLength", "pattern", "format", "minimum",
    "maximum", "exclusiveMinimum", "exclusiveMaximum",
}


class ContractError(ValueError):
    """Raised when an offline artifact violates the normative contract."""


def _reject_json_constant(value: str) -> None:
    raise ContractError(f"non-standard JSON numeric constant is forbidden: {value}")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for key, value in pairs:
        if key in data:
            raise ContractError(f"duplicate JSON object key is forbidden: {key}")
        data[key] = value
    return data


def load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=_reject_json_constant,
            object_pairs_hook=_reject_duplicate_keys,
        )
    except json.JSONDecodeError as exc:
        raise ContractError(f"{path}: invalid JSON: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise ContractError(f"{path}: top-level JSON value must be an object")
    return data


def _json_equal(left: Any, right: Any) -> bool:
    """Compare JSON values without Python's bool/int equivalence."""
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return not isinstance(left, bool) and not isinstance(right, bool) and left == right
    return type(left) is type(right) and left == right


def _schema_path(path: tuple[str | int, ...]) -> str:
    if not path:
        return "$"
    return "$" + "".join(f"[{item}]" if isinstance(item, int) else f".{item}" for item in path)


def _resolve_local_ref(root_schema: dict[str, Any], reference: str) -> Any:
    require(reference.startswith("#/"), f"schema: only internal JSON-pointer $ref values are supported: {reference}")
    current: Any = root_schema
    for raw_token in reference[2:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        require(isinstance(current, dict) and token in current, f"schema: unresolved $ref {reference}")
        current = current[token]
    return current


def _matches_type(instance: Any, expected: str) -> bool:
    if expected == "null":
        return instance is None
    if expected == "boolean":
        return isinstance(instance, bool)
    if expected == "object":
        return isinstance(instance, dict)
    if expected == "array":
        return isinstance(instance, list)
    if expected == "string":
        return isinstance(instance, str)
    if expected == "integer":
        return isinstance(instance, int) and not isinstance(instance, bool)
    if expected == "number":
        return (
            isinstance(instance, (int, float))
            and not isinstance(instance, bool)
            and (isinstance(instance, int) or math.isfinite(instance))
        )
    raise ContractError(f"schema: unsupported type {expected!r}")


def validate_schema_document(schema: dict[str, Any]) -> None:
    """Fail closed if a repository schema starts using an unsupported keyword."""
    require(schema.get("$schema") == "https://json-schema.org/draft/2020-12/schema", "schema: unsupported draft")

    def audit(node: Any, location: str) -> None:
        if isinstance(node, bool):
            return
        require(isinstance(node, dict), f"schema: invalid node at {location}")
        unknown = set(node) - SUPPORTED_SCHEMA_KEYWORDS
        require(not unknown, f"schema: unsupported keyword(s) at {location}: {', '.join(sorted(unknown))}")
        for mapping_key in ("properties", "$defs"):
            for key, subschema in node.get(mapping_key, {}).items():
                audit(subschema, f"{location}/{mapping_key}/{key}")
        for list_key in ("allOf", "anyOf", "oneOf"):
            for index, subschema in enumerate(node.get(list_key, [])):
                audit(subschema, f"{location}/{list_key}/{index}")
        for single_key in ("not", "items", "additionalProperties", "propertyNames"):
            subschema = node.get(single_key)
            if isinstance(subschema, (dict, bool)):
                audit(subschema, f"{location}/{single_key}")
        if "format" in node:
            require(node["format"] == "uri", f"schema: unsupported format at {location}: {node['format']}")

    audit(schema, "#")


def _validate_schema_instance(
    instance: Any,
    schema: Any,
    root_schema: dict[str, Any],
    path: tuple[str | int, ...] = (),
) -> None:
    location = _schema_path(path)
    if isinstance(schema, bool):
        require(schema, f"{location}: rejected by false schema")
        return
    require(isinstance(schema, dict), f"schema: invalid schema node at {location}")

    if "$ref" in schema:
        _validate_schema_instance(instance, _resolve_local_ref(root_schema, schema["$ref"]), root_schema, path)
    if "allOf" in schema:
        for subschema in schema["allOf"]:
            _validate_schema_instance(instance, subschema, root_schema, path)
    if "anyOf" in schema:
        matches = 0
        for subschema in schema["anyOf"]:
            try:
                _validate_schema_instance(instance, subschema, root_schema, path)
            except ContractError:
                continue
            matches += 1
        require(matches >= 1, f"{location}: value does not match any allowed schema")
    if "oneOf" in schema:
        matches = 0
        for subschema in schema["oneOf"]:
            try:
                _validate_schema_instance(instance, subschema, root_schema, path)
            except ContractError:
                continue
            matches += 1
        require(matches == 1, f"{location}: value must match exactly one allowed schema")
    if "not" in schema:
        try:
            _validate_schema_instance(instance, schema["not"], root_schema, path)
        except ContractError:
            pass
        else:
            raise ContractError(f"{location}: value matches a forbidden schema")

    if "const" in schema:
        require(_json_equal(instance, schema["const"]), f"{location}: value does not match const")
    if "enum" in schema:
        require(any(_json_equal(instance, allowed) for allowed in schema["enum"]), f"{location}: value is not in enum")
    if "type" in schema:
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        require(any(_matches_type(instance, expected) for expected in types), f"{location}: expected type {schema['type']!r}")

    if isinstance(instance, dict):
        missing = [key for key in schema.get("required", []) if key not in instance]
        require(not missing, f"{location}: missing required properties: {', '.join(missing)}")
        properties = schema.get("properties", {})
        for key, value in instance.items():
            if key in properties:
                _validate_schema_instance(value, properties[key], root_schema, path + (key,))
                continue
            additional = schema.get("additionalProperties", True)
            require(additional is not False, f"{location}: additional property is forbidden: {key}")
            if isinstance(additional, dict):
                _validate_schema_instance(value, additional, root_schema, path + (key,))
        if "propertyNames" in schema:
            for key in instance:
                _validate_schema_instance(key, schema["propertyNames"], root_schema, path + (key,))
        require(len(instance) >= schema.get("minProperties", 0), f"{location}: too few properties")
        if "maxProperties" in schema:
            require(len(instance) <= schema["maxProperties"], f"{location}: too many properties")

    if isinstance(instance, list):
        require(len(instance) >= schema.get("minItems", 0), f"{location}: too few items")
        if "maxItems" in schema:
            require(len(instance) <= schema["maxItems"], f"{location}: too many items")
        if schema.get("uniqueItems"):
            canonical = [json.dumps(item, sort_keys=True, separators=(",", ":"), ensure_ascii=False) for item in instance]
            require(len(canonical) == len(set(canonical)), f"{location}: array items must be unique")
        if "items" in schema:
            for index, value in enumerate(instance):
                _validate_schema_instance(value, schema["items"], root_schema, path + (index,))

    if isinstance(instance, str):
        require(len(instance) >= schema.get("minLength", 0), f"{location}: string is too short")
        if "maxLength" in schema:
            require(len(instance) <= schema["maxLength"], f"{location}: string is too long")
        if "pattern" in schema:
            require(re.search(schema["pattern"], instance) is not None, f"{location}: string does not match pattern")
        if schema.get("format") == "uri":
            parsed = urlparse(instance)
            require(bool(parsed.scheme) and (bool(parsed.netloc) or parsed.scheme not in {"http", "https"}), f"{location}: invalid URI")

    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        require(isinstance(instance, int) or math.isfinite(instance), f"{location}: non-finite number is forbidden")
        if "minimum" in schema:
            require(instance >= schema["minimum"], f"{location}: number is below minimum")
        if "maximum" in schema:
            require(instance <= schema["maximum"], f"{location}: number is above maximum")
        if "exclusiveMinimum" in schema:
            require(instance > schema["exclusiveMinimum"], f"{location}: number is not above exclusive minimum")
        if "exclusiveMaximum" in schema:
            require(instance < schema["exclusiveMaximum"], f"{location}: number is not below exclusive maximum")


def validate_structure(data: dict[str, Any], kind: str | None = None) -> str:
    """Validate one of the 12 repository artifact types against its JSON Schema."""
    inferred_kind = SCHEMA_KINDS.get(data.get("schema"))
    if kind is None:
        require(inferred_kind is not None, "artifact: unknown schema discriminator")
        kind = inferred_kind
    require(kind in SCHEMA_IDS, f"artifact: unknown schema kind {kind!r}")
    require(data.get("schema") == SCHEMA_IDS[kind], f"{kind}: wrong schema")
    schema = load_json(SCHEMA_DIR / f"{kind}.schema.json")
    validate_schema_document(schema)
    _validate_schema_instance(data, schema, schema)
    return kind


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def payload_sha256(data: Any) -> str:
    encoded = (json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def require_id(value: Any, label: str) -> str:
    require(isinstance(value, str) and ID_RE.fullmatch(value) is not None, f"{label}: invalid ID")
    return value


def require_hash(value: Any, label: str) -> str:
    require(isinstance(value, str) and HASH_RE.fullmatch(value) is not None, f"{label}: invalid SHA-256")
    return value


def unique_index(items: Iterable[dict[str, Any]], key: str, label: str) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for item in items:
        value = require_id(item.get(key), f"{label}.{key}")
        require(value not in index, f"{label}: duplicate {key} {value}")
        index[value] = item
    return index


def validate_common(data: dict[str, Any], kind: str) -> None:
    validate_structure(data, kind)
    require(data.get("schema") == SCHEMAS[kind], f"{kind}: wrong schema")
    require(data.get("calculation_ready") is False, f"{kind}: calculation_ready must be false")
    require(data.get("no_submission_authorization") is True, f"{kind}: no_submission_authorization must be true")


def validate_study(study: dict[str, Any]) -> None:
    validate_common(study, "study")
    require_id(study.get("study_id"), "study.study_id")
    require(study.get("status") in {"draft", "reviewed_offline", "superseded"}, "study: invalid status")

    species = unique_index(study.get("species", []), "species_id", "study.species")
    states = unique_index(study.get("catalyst_states", []), "state_id", "study.catalyst_states")
    mechanisms = unique_index(study.get("mechanism_hypotheses", []), "mechanism_id", "study.mechanisms")
    channels = unique_index(study.get("channels", []), "channel_id", "study.channels")
    protocols = unique_index(study.get("protocol_sets", []), "protocol_id", "study.protocols")
    groups = unique_index(study.get("comparison_groups", []), "comparison_group_id", "study.groups")
    dimensions = unique_index(study.get("coverage_dimensions", []), "dimension_id", "study.dimensions")
    require(len(channels) >= 2, "study: at least two channels are required")
    if study.get("status") == "reviewed_offline":
        g0 = next((gate for gate in study.get("gates", []) if gate.get("gate_id") == "g0"), None)
        require(g0 is not None and g0.get("status") == "accepted", "study: reviewed_offline requires accepted G0")

    catalyst_class = study.get("catalyst_class")
    for state_id, state in states.items():
        state_class = state.get("catalyst_class")
        metals = state.get("metal_centers", [])
        borons = state.get("boron_centers", [])
        if state_class in {"metal_chiral_ligand", "metal_and_chiral_boron_cooperative"}:
            require(bool(metals), f"state {state_id}: metal centers are required")
            require(state.get("support_status") == "unsupported_transition_metal", f"state {state_id}: version 1 metal state must remain unsupported")
        if state_class in {"chiral_boron", "metal_and_chiral_boron_cooperative"}:
            require(bool(borons), f"state {state_id}: boron centers are required")
        for entry in state.get("composition", []):
            require(entry.get("species_id") in species, f"state {state_id}: unknown species reference")
        require(state_class == catalyst_class or catalyst_class == "metal_and_chiral_boron_cooperative", f"state {state_id}: catalyst class mismatch")

    for mechanism_id, mechanism in mechanisms.items():
        require(mechanism.get("active_catalyst_state_id") in states, f"mechanism {mechanism_id}: unknown catalyst state")
        mechanism_channels = mechanism.get("channel_ids", [])
        require(len(set(mechanism_channels)) >= 2, f"mechanism {mechanism_id}: at least two unique channels required")
        require(set(mechanism_channels) <= set(channels), f"mechanism {mechanism_id}: unknown channel")
        for species_id in mechanism.get("reactant_species_ids", []) + mechanism.get("product_species_ids", []):
            require(species_id in species, f"mechanism {mechanism_id}: unknown species {species_id}")

    for channel_id, channel in channels.items():
        require(channel.get("product_species_id") in species, f"channel {channel_id}: unknown product")
        require(channel_id not in {"major", "minor", "major_channel", "minor_channel"}, f"channel {channel_id}: outcome label used as identity")

    for protocol_id, protocol in protocols.items():
        require(protocol.get("resolution_status") in {"pending", "reviewed"}, f"protocol {protocol_id}: invalid status")
        if protocol.get("resolution_status") == "reviewed":
            required_routes = ("ts_optimization", "frequency", "single_point")
            for route_name in required_routes:
                route = protocol.get("routes", {}).get(route_name)
                require(isinstance(route, str) and route.strip(), f"protocol {protocol_id}: missing {route_name} route")
                require(PLACEHOLDER_RE.search(route) is None, f"protocol {protocol_id}: placeholder in {route_name} route")
            for field in ("method", "low_frequency_policy"):
                value = protocol.get(field)
                require(isinstance(value, str) and value.strip(), f"protocol {protocol_id}: missing {field}")

    for group_id, group in groups.items():
        mechanism_id = group.get("mechanism_id")
        require(mechanism_id in mechanisms, f"group {group_id}: unknown mechanism")
        group_channels = group.get("channel_ids", [])
        require(len(set(group_channels)) >= 2, f"group {group_id}: at least two channels required")
        require(set(group_channels) <= set(channels), f"group {group_id}: unknown channel")
        require(set(group_channels) <= set(mechanisms[mechanism_id].get("channel_ids", [])), f"group {group_id}: channel outside mechanism")
        require(group.get("protocol_id") in protocols, f"group {group_id}: unknown protocol")
        require(set(group.get("coverage_dimension_ids", [])) <= set(dimensions), f"group {group_id}: unknown coverage dimension")


def validate_space(space: dict[str, Any], study: dict[str, Any] | None = None, study_path: Path | None = None) -> None:
    validate_structure(space, "space")
    dimensions = unique_index(space.get("dimensions", []), "dimension_id", "space.dimensions")
    for dimension_id, dimension in dimensions.items():
        level_ids: set[str] = set()
        for level in dimension.get("levels", []):
            level_id = level.get("level_id")
            require(isinstance(level_id, str) and level_id, f"space {dimension_id}: invalid level ID")
            require(level_id not in level_ids, f"space {dimension_id}: duplicate level {level_id}")
            level_ids.add(level_id)
    if study is None:
        return
    require(study_path is not None, "space: study_path is required when a study is supplied")
    validate_study(study)
    require(space.get("study_id") == study.get("study_id"), "space: study ID mismatch")
    require(space.get("study_sha256") == sha256(study_path), "space: study hash mismatch")
    groups = {item["comparison_group_id"]: item for item in study["comparison_groups"]}
    group_id = space.get("comparison_group_id")
    require(group_id in groups, "space: unknown comparison group")
    expected_dimensions = set(groups[group_id].get("coverage_dimension_ids", []))
    require(set(dimensions) == expected_dimensions, "space: dimensions do not match comparison group")
    state_ids = {item["state_id"] for item in study["catalyst_states"]}
    require(set(space.get("catalyst_state_ids", [])) <= state_ids, "space: unknown catalyst state")


def validate_ledger(
    ledger: dict[str, Any],
    study: dict[str, Any] | None = None,
    study_path: Path | None = None,
    space: dict[str, Any] | None = None,
    space_path: Path | None = None,
) -> None:
    validate_structure(ledger, "ledger")
    entries = unique_index(ledger.get("entries", []), "candidate_id", "ledger.entries")
    dimension_ids = ledger.get("dimension_ids", [])
    for candidate_id, entry in entries.items():
        require(set(entry.get("dimensions", {})) == set(dimension_ids), f"ledger {candidate_id}: dimension keys mismatch")
        status = entry.get("status")
        duplicate_of = entry.get("duplicate_of")
        if status in {"duplicate_logical", "duplicate_geometry"}:
            require(duplicate_of in entries, f"ledger {candidate_id}: missing duplicate target")
            require(duplicate_of != candidate_id, f"ledger {candidate_id}: self-duplicate is forbidden")
            require(entries[duplicate_of].get("channel_id") == entry.get("channel_id"), f"ledger {candidate_id}: cross-channel deduplication is forbidden")
        else:
            require(duplicate_of is None, f"ledger {candidate_id}: unique entry has duplicate target")
        if status == "materialized_unique":
            require(entry.get("candidate_artifact") is not None, f"ledger {candidate_id}: materialized candidate artifact is missing")
            require(entry.get("geometry_fingerprint") is not None, f"ledger {candidate_id}: materialized geometry fingerprint is missing")

    counts = ledger.get("counts", {})
    exclusions = ledger.get("excluded_combinations", [])
    require(counts.get("enumerated") == len(entries) + len(exclusions), "ledger: enumerated count mismatch")
    require(counts.get("retained") == sum(item.get("status") in {"unmaterialized", "materialized_unique", "duplicate_geometry"} for item in entries.values()), "ledger: retained count mismatch")
    require(counts.get("excluded") == len(exclusions), "ledger: excluded count mismatch")
    require(counts.get("logical_duplicates") == sum(item.get("status") == "duplicate_logical" for item in entries.values()), "ledger: logical duplicate count mismatch")
    require(counts.get("materialized_unique") == sum(item.get("status") == "materialized_unique" for item in entries.values()), "ledger: materialized count mismatch")
    require(counts.get("geometry_duplicates") == sum(item.get("status") == "duplicate_geometry" for item in entries.values()), "ledger: geometry duplicate count mismatch")

    if study is not None:
        require(study_path is not None, "ledger: study_path is required when a study is supplied")
        validate_study(study)
        require(ledger.get("study_id") == study.get("study_id"), "ledger: study ID mismatch")
        require(ledger.get("study_sha256") == sha256(study_path), "ledger: study hash mismatch")
        groups = {item["comparison_group_id"]: item for item in study["comparison_groups"]}
        group = groups.get(ledger.get("comparison_group_id"))
        require(group is not None, "ledger: unknown comparison group")
        require(ledger.get("mechanism_id") == group.get("mechanism_id"), "ledger: mechanism mismatch")
        require(ledger.get("protocol_id") == group.get("protocol_id"), "ledger: protocol mismatch")
        require(set(dimension_ids) == set(group.get("coverage_dimension_ids", [])), "ledger: dimension IDs mismatch")
        require(all(item.get("channel_id") in group.get("channel_ids", []) for item in entries.values()), "ledger: entry channel outside group")
    if space is not None:
        require(space_path is not None, "ledger: space_path is required when a space is supplied")
        validate_space(space, study, study_path) if study is not None else validate_space(space)
        require(ledger.get("candidate_space_spec", {}).get("sha256") == sha256(space_path), "ledger: candidate-space hash mismatch")
        require(ledger.get("geometry_dedup_tolerance_angstrom") == space.get("geometry_dedup_tolerance_angstrom"), "ledger: dedup tolerance mismatch")
        require(set(dimension_ids) == {item["dimension_id"] for item in space.get("dimensions", [])}, "ledger: candidate-space dimension mismatch")


def validate_energy_record(record: dict[str, Any], candidate: dict[str, Any] | None = None) -> None:
    validate_structure(record, "energy-record")
    if candidate is not None:
        validate_structure(candidate, "candidate")
        require(record.get("candidate_id") == candidate.get("candidate_id"), "energy record: candidate ID mismatch")
        require(record.get("inventory_key") == candidate.get("atom_inventory", {}).get("inventory_key"), "energy record: inventory mismatch")


def validate_materializations(
    materializations: dict[str, Any],
    ledger: dict[str, Any] | None = None,
    ledger_path: Path | None = None,
) -> None:
    validate_structure(materializations, "materializations")
    records = unique_index(materializations.get("records", []), "candidate_id", "materializations.records")
    if ledger is None:
        return
    require(ledger_path is not None, "materializations: ledger_path is required when a ledger is supplied")
    validate_ledger(ledger)
    require(materializations.get("ledger_sha256") == sha256(ledger_path), "materializations: ledger hash mismatch")
    materializable = {item["candidate_id"] for item in ledger.get("entries", []) if item.get("status") == "unmaterialized"}
    require(set(records) <= materializable, "materializations: missing or non-materializable candidate")


def validate_metal_support(design: dict[str, Any], study: dict[str, Any] | None = None, study_path: Path | None = None) -> None:
    validate_structure(design, "metal-support")
    expected_payload = payload_sha256({key: value for key, value in design.items() if key != "design_payload_sha256"})
    require(design.get("design_payload_sha256") == expected_payload, "metal-support: payload hash mismatch")
    require(design.get("calculation_ready") is False, "metal-support: calculation_ready must remain false")
    require(design.get("no_submission_authorization") is True, "metal-support: submission authority is forbidden")
    require(design.get("runtime_support_status") == "unsupported_requires_extension", "metal-support: runtime support must remain blocked")
    require(design.get("submission_decision") == "refused", "metal-support: submission decision must remain refused")
    scope = design.get("scope", {})
    require(scope.get("priority") == "transition_metal_ts_design_first", "metal-support: transition-metal TS design priority changed")
    require(scope.get("execution_scope") == "no_transition_metal_execution", "metal-support: execution scope was widened")
    states = unique_index(design.get("states", []), "state_id", "metal-support.states")
    for state_id, state in states.items():
        require(state.get("support_status") == "unsupported_transition_metal", f"metal-support: state {state_id} support refusal changed")
        require(state.get("submission_decision") == "refused", f"metal-support: state {state_id} submission refusal changed")
        require(state.get("ts_search_readiness", {}).get("status") == "blocked_offline_design_only", f"metal-support: state {state_id} TS readiness bypassed")
        centers = state.get("metal_centers", [])
        require(isinstance(centers, list) and centers, f"metal-support: state {state_id} has no metal-center audit")
        for center in centers:
            require(center.get("review_status") == "unreviewed_hypothesis", f"metal-support: state {state_id} contains an accepted metal assignment")
            require(center.get("d_electron_count") is None, f"metal-support: state {state_id} inferred a d-electron count")
        for block in ("electron_accounting", "spin_state_space", "wavefunction", "coordination", "method_protocol"):
            require(state.get(block, {}).get("status") in {"review_required", "unresolved"}, f"metal-support: state {state_id} {block} review was bypassed")
            require(state.get(block, {}).get("blockers"), f"metal-support: state {state_id} {block} lacks blockers")

    families = unique_index(design.get("ts_search_families", []), "mechanism_id", "metal-support.ts_search_families")
    expected_strategies = {"single_guess_hessian_guided", "endpoint_qst2_qst3", "reviewed_relaxed_coordinate_scan"}
    for mechanism_id, family in families.items():
        require(family.get("active_state_id") in states, f"metal-support: mechanism {mechanism_id} references an unknown state")
        require(family.get("elementary_step_class") == "unassigned_requires_review", f"metal-support: mechanism {mechanism_id} inferred an elementary-step class")
        strategies = family.get("seed_strategy_candidates", [])
        require({item.get("strategy") for item in strategies} == expected_strategies, f"metal-support: mechanism {mechanism_id} TS strategy inventory is incomplete")
        require(all(item.get("status") == "design_candidate_not_selected" for item in strategies), f"metal-support: mechanism {mechanism_id} selected a TS strategy")
        require(family.get("surface_model", {}).get("status") == "unresolved", f"metal-support: mechanism {mechanism_id} inferred an electronic surface")
        require(family.get("blockers"), f"metal-support: mechanism {mechanism_id} lacks execution blockers")

    milestones = unique_index(design.get("extension_milestones", []), "milestone_id", "metal-support.extension_milestones")
    require(milestones.get("metal_m0_offline_design", {}).get("status") == "implemented_offline", "metal-support: offline design milestone is missing")
    if "metal_m1_review_contract" in milestones:
        require(milestones["metal_m1_review_contract"].get("status") == "implemented_offline", "metal-support: M1 sidecar contract milestone has an invalid status")
    require(milestones.get("metal_m1_scientific_review", {}).get("status") == "pending_scientific_review", "metal-support: real M1 scientific review was incorrectly marked complete")
    require(milestones.get("metal_m2a_candidate_audit_template", {}).get("status") == "implemented_offline", "metal-support: candidate audit-template milestone is missing")
    if "metal_m2c_input_observation" in milestones:
        require(milestones["metal_m2c_input_observation"].get("status") == "implemented_offline", "metal-support: M2c input-observation milestone has an invalid status")
    if "metal_m2d_acceptance_review_contract" in milestones:
        require(milestones["metal_m2d_acceptance_review_contract"].get("status") == "implemented_offline", "metal-support: M2d acceptance-review milestone has an invalid status")
    for milestone_id, milestone in milestones.items():
        if milestone_id not in {
            "metal_m0_offline_design",
            "metal_m1_review_contract",
            "metal_m2a_candidate_audit_template",
            "metal_m2b_result_observation",
            "metal_m2c_input_observation",
            "metal_m2d_acceptance_review_contract",
        }:
            require(milestone.get("status") != "implemented_offline", f"metal-support: unsupported milestone {milestone_id} was marked implemented")
    if study is None:
        return
    require(study_path is not None, "metal-support: study_path is required when a study is supplied")
    validate_study(study)
    require(design.get("study_id") == study.get("study_id"), "metal-support: study ID mismatch")
    require(design.get("study_sha256") == sha256(study_path), "metal-support: study hash mismatch")
    metal_states = {item["state_id"] for item in study.get("catalyst_states", []) if item.get("metal_centers")}
    require(set(states) == metal_states, "metal-support: reviewed metal states mismatch")
    state_by_id = {item["state_id"]: item for item in study.get("catalyst_states", [])}
    for state_id, design_state in states.items():
        source_centers = state_by_id[state_id].get("metal_centers", [])
        design_centers = design_state.get("metal_centers", [])
        require(len(design_centers) == len(source_centers), f"metal-support: state {state_id} metal-center count mismatch")
        for source, audited in zip(source_centers, design_centers, strict=True):
            require(audited.get("atom_index") == source.get("atom_index") and audited.get("element") == source.get("element"), f"metal-support: state {state_id} metal-center identity mismatch")
            require(audited.get("formal_oxidation_state") == source.get("oxidation_state"), f"metal-support: state {state_id} oxidation-state provenance mismatch")
    metal_mechanisms = {
        item["mechanism_id"]
        for item in study.get("mechanism_hypotheses", [])
        if item.get("active_catalyst_state_id") in metal_states
    }
    require(set(families) == metal_mechanisms, "metal-support: metal mechanism TS-search inventory mismatch")


def validate_metal_ts_audit_template(
    template: dict[str, Any],
    design: dict[str, Any] | None = None,
    design_path: Path | None = None,
    candidate: dict[str, Any] | None = None,
    candidate_path: Path | None = None,
) -> None:
    validate_structure(template, "metal-ts-audit-template")
    expected_payload = payload_sha256(
        {key: value for key, value in template.items() if key != "template_payload_sha256"}
    )
    require(
        template.get("template_payload_sha256") == expected_payload,
        "metal TS audit template: payload hash mismatch",
    )
    require(template.get("calculation_ready") is False, "metal TS audit template: calculation_ready must remain false")
    require(template.get("no_submission_authorization") is True, "metal TS audit template: submission authority is forbidden")
    require(template.get("runtime_support_status") == "unsupported_requires_extension", "metal TS audit template: runtime support must remain blocked")
    require(template.get("submission_decision") == "refused", "metal TS audit template: submission decision must remain refused")
    require(template.get("status") == "blocked_pending_scientific_review", "metal TS audit template: scientific review gate was bypassed")
    require(template.get("claim_ceiling") == "design_only_no_ts_or_selectivity_claim", "metal TS audit template: claim ceiling was widened")

    identity = template.get("identity_binding", {})
    atom_order = identity.get("atom_order", [])
    require(
        [item.get("index") for item in atom_order] == list(range(1, len(atom_order) + 1)),
        "metal TS audit template: atom order must be contiguous and one-based",
    )
    require(identity.get("atom_count") == len(atom_order), "metal TS audit template: atom count differs from atom order")
    centers = identity.get("metal_centers", [])
    require(isinstance(centers, list) and centers, "metal TS audit template: metal centers are missing")
    elements = {item.get("index"): item.get("element") for item in atom_order}
    for center in centers:
        require(elements.get(center.get("atom_index")) == center.get("element"), "metal TS audit template: metal-center identity differs from atom order")
        require(center.get("d_electron_count") is None, "metal TS audit template: d-electron count was inferred")
        require(center.get("review_status") == "unreviewed_hypothesis", "metal TS audit template: metal-center hypothesis was accepted")
    for contact in identity.get("coordination_contacts", []):
        require(contact.get("donor_atom") in elements and contact.get("acceptor_atom") in elements, "metal TS audit template: coordination contact is outside atom order")
        require(contact.get("distance_window_angstrom") is None, "metal TS audit template: coordination distance window was inferred")
        require(contact.get("review_status") == "pending", "metal TS audit template: coordination contact was accepted")

    section_names = {
        "electron_accounting", "spin_surface", "wavefunction",
        "coordination", "method_protocol", "ts_and_path",
    }
    sections = template.get("audit_sections", {})
    require(set(sections) == section_names, "metal TS audit template: audit-section inventory is incomplete")
    for section_name, section in sections.items():
        require(section.get("status") == "blocked_pending_review", f"metal TS audit template: {section_name} review was bypassed")
        require(section.get("required_evidence"), f"metal TS audit template: {section_name} lacks evidence requirements")
        require(section.get("rejection_conditions"), f"metal TS audit template: {section_name} lacks rejection conditions")

    gate = template.get("seed_strategy_gate", {})
    strategies = gate.get("inventory", [])
    require(
        {item.get("strategy") for item in strategies}
        == {"single_guess_hessian_guided", "endpoint_qst2_qst3", "reviewed_relaxed_coordinate_scan"},
        "metal TS audit template: seed-strategy inventory is incomplete",
    )
    require(all(item.get("status") == "design_candidate_not_selected" for item in strategies), "metal TS audit template: a seed strategy was selected")
    require(gate.get("selected_strategy_id") is None and gate.get("selection_status") == "not_selected", "metal TS audit template: strategy selection was bypassed")
    require(template.get("hard_rejections"), "metal TS audit template: hard rejections are missing")

    if design is not None:
        require(design_path is not None, "metal TS audit template: design_path is required with a design")
        validate_metal_support(design)
        require(template.get("design_source", {}).get("sha256") == sha256(design_path), "metal TS audit template: design hash mismatch")
        require(template.get("study_id") == design.get("study_id"), "metal TS audit template: design study ID mismatch")
        states = {item["state_id"]: item for item in design.get("states", [])}
        families = {item["mechanism_id"]: item for item in design.get("ts_search_families", [])}
        require(template.get("catalyst_state_id") in states, "metal TS audit template: unknown design state")
        family = families.get(template.get("mechanism_id"))
        require(family is not None and family.get("active_state_id") == template.get("catalyst_state_id"), "metal TS audit template: design mechanism/state mismatch")
        require(template.get("channel_id") in family.get("channel_ids", []), "metal TS audit template: channel outside design family")
        require(
            {(item.get("strategy_id"), item.get("strategy"), item.get("status")) for item in strategies}
            == {(item.get("strategy_id"), item.get("strategy"), item.get("status")) for item in family.get("seed_strategy_candidates", [])},
            "metal TS audit template: seed strategies differ from the design",
        )

    if candidate is not None:
        require(candidate_path is not None, "metal TS audit template: candidate_path is required with a candidate")
        validate_structure(candidate, "candidate")
        require(candidate.get("support_status") == "unsupported_transition_metal", "metal TS audit template: candidate is not an unsupported metal case")
        require(candidate.get("review_status") != "promoted_offline", "metal TS audit template: unsupported candidate was promoted")
        require(template.get("candidate_source", {}).get("sha256") == sha256(candidate_path), "metal TS audit template: candidate hash mismatch")
        for key in ("study_id", "candidate_id", "mechanism_id", "channel_id", "catalyst_state_id"):
            require(template.get(key) == candidate.get(key), f"metal TS audit template: candidate {key} mismatch")
        expected_order = [
            {"index": item.get("index"), "element": item.get("element"), "role": item.get("role")}
            for item in candidate.get("atom_map", [])
        ]
        require(atom_order == expected_order, "metal TS audit template: candidate atom order mismatch")
        require(identity.get("charge") == candidate.get("chemical_state", {}).get("charge"), "metal TS audit template: candidate charge mismatch")
        require(identity.get("multiplicity") == candidate.get("chemical_state", {}).get("multiplicity"), "metal TS audit template: candidate multiplicity mismatch")
        expected_contacts = {
            (item.get("donor_atom"), item.get("acceptor_atom"), item.get("kind"))
            for item in candidate.get("binding_mode", {}).get("coordination_contacts", [])
        }
        actual_contacts = {
            (item.get("donor_atom"), item.get("acceptor_atom"), item.get("kind"))
            for item in identity.get("coordination_contacts", [])
        }
        require(actual_contacts == expected_contacts, "metal TS audit template: candidate coordination contacts mismatch")


def _validate_metal_review_content(
    provenance: dict[str, Any],
    identity: dict[str, Any],
    sections: dict[str, Any],
    label: str,
) -> tuple[bool, list[str], list[str], list[str]]:
    require(set(sections) == METAL_REVIEW_SECTIONS, f"{label}: review-section inventory is incomplete")
    evidence = unique_index(provenance.get("sources", []), "source_id", f"{label}.sources")
    require(evidence, f"{label}: evidence-source inventory is empty")
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
    reviewed: list[str] = []
    blocked: list[str] = []
    unresolved: list[str] = []
    for section_name in sorted(METAL_REVIEW_SECTIONS):
        section = sections[section_name]
        require(set(section.get("facts", {})) == fact_fields[section_name], f"{label}: {section_name} fact fields are incomplete or unknown")
        status = section.get("status")
        require(status in {"reviewed_for_bounded_example", "blocked_missing_evidence"}, f"{label}: {section_name} status is invalid")
        evidence_ids = section.get("evidence_ids", [])
        require(len(evidence_ids) == len(set(evidence_ids)), f"{label}: {section_name} evidence IDs are duplicated")
        for source_id in evidence_ids:
            require(source_id in evidence, f"{label}: {section_name} references unknown evidence {source_id}")
            require(section_name in evidence[source_id].get("supports", []), f"{label}: evidence {source_id} does not support {section_name}")
        blockers = section.get("blockers", [])
        if status == "reviewed_for_bounded_example":
            reviewed.append(section_name)
            require(evidence_ids, f"{label}: {section_name} was marked reviewed without evidence")
            require(not blockers, f"{label}: {section_name} was marked reviewed with unresolved blockers")
        else:
            blocked.append(section_name)
            require(blockers, f"{label}: {section_name} blocked status lacks blockers")
            unresolved.extend(f"{section_name}: {item}" for item in blockers)

    centers = identity.get("metal_centers", [])
    center_identity = [
        {"atom_index": item.get("atom_index"), "element": item.get("element")}
        for item in centers
    ]
    electron = sections["electron_accounting"]
    electron_facts = electron["facts"]
    assignments = electron_facts.get("metal_assignments", [])
    require(
        [{"atom_index": item.get("atom_index"), "element": item.get("element")} for item in assignments]
        == center_identity,
        f"{label}: electron assignments differ from the identity-bound metal centers",
    )
    if electron["status"] == "reviewed_for_bounded_example":
        require(all(isinstance(item.get("formal_oxidation_state"), int) and isinstance(item.get("d_electron_count"), int) and item["d_electron_count"] >= 0 and isinstance(item.get("assignment_basis"), str) and item["assignment_basis"].strip() for item in assignments), f"{label}: reviewed electron accounting is incomplete")
        total = electron_facts.get("total_valence_electron_count")
        multiplicity = identity.get("multiplicity")
        require(isinstance(total, int) and not isinstance(total, bool) and total >= 0, f"{label}: reviewed total electron count is invalid")
        require(electron_facts.get("electron_parity") == ("even" if total % 2 == 0 else "odd"), f"{label}: electron parity differs from the explicit count")
        require(isinstance(multiplicity, int) and multiplicity >= 1 and (total % 2 == 0) == (multiplicity % 2 == 1), f"{label}: electron and multiplicity parity are inconsistent")
        require(electron_facts.get("parity_multiplicity_assessment") == "consistent", f"{label}: reviewed parity assessment is not consistent")
        require(electron_facts.get("ligand_charge_conventions") and electron_facts.get("non_innocent_ligand_alternatives"), f"{label}: reviewed electron accounting omits ligand-charge or non-innocent alternatives")

    spin = sections["spin_surface"]
    spin_facts = spin["facts"]
    if spin["status"] == "reviewed_for_bounded_example":
        credible = spin_facts.get("credible_multiplicities", [])
        selected = spin_facts.get("selected_multiplicity")
        require(credible and all(isinstance(value, int) and value >= 1 for value in credible), f"{label}: reviewed spin inventory is invalid")
        require(selected == identity.get("multiplicity") and selected in credible, f"{label}: reviewed spin selection differs from the bound identity")
        require(isinstance(spin_facts.get("relative_energy_reference"), str) and spin_facts["relative_energy_reference"].strip(), f"{label}: reviewed spin inventory lacks a common reference")
        for field in ("spin_crossover_relevance", "minimum_energy_crossing_relevance"):
            require(spin_facts.get(field) in {"not_indicated", "relevant_requires_extension"}, f"{label}: reviewed spin inventory leaves {field} unresolved")
        require(isinstance(spin_facts.get("single_surface_assumption"), bool), f"{label}: reviewed spin inventory lacks a surface decision")

    wavefunction = sections["wavefunction"]
    wavefunction_facts = wavefunction["facts"]
    if wavefunction["status"] == "reviewed_for_bounded_example":
        require(wavefunction_facts.get("reference_hypothesis") in {"restricted", "unrestricted", "restricted_open_shell", "broken_symmetry"}, f"{label}: reviewed wavefunction reference is invalid")
        multiplicity = identity["multiplicity"]
        spin_value = (multiplicity - 1) / 2.0
        require(isinstance(wavefunction_facts.get("expected_s2"), (int, float)) and not isinstance(wavefunction_facts.get("expected_s2"), bool) and math.isfinite(wavefunction_facts["expected_s2"]) and math.isclose(wavefunction_facts["expected_s2"], spin_value * (spin_value + 1.0), rel_tol=0.0, abs_tol=1e-8), f"{label}: expected S**2 differs from the bound multiplicity")
        for field in ("scf_stability_policy", "spin_contamination_policy", "occupation_inspection_policy", "alternative_solution_policy", "multireference_diagnostic_policy", "checkpoint_reuse_policy"):
            require(isinstance(wavefunction_facts.get(field), str) and wavefunction_facts[field].strip(), f"{label}: reviewed wavefunction lacks {field}")

    coordination = sections["coordination"]
    coordination_facts = coordination["facts"]
    center_models = coordination_facts.get("metal_center_models", [])
    require(
        [{"atom_index": item.get("atom_index"), "element": item.get("element")} for item in center_models]
        == center_identity,
        f"{label}: coordination center models differ from the identity-bound metal centers",
    )
    contacts = coordination_facts.get("coordination_contacts", [])
    for contact in contacts:
        window = contact.get("distance_window_angstrom")
        require(window is None or (isinstance(window, list) and len(window) == 2 and all(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0 for value in window) and window[0] <= window[1]), f"{label}: coordination distance window is invalid")
    if coordination["status"] == "reviewed_for_bounded_example":
        require(all(isinstance(item.get("coordination_number"), int) and item["coordination_number"] >= 0 and isinstance(item.get("geometry"), str) and item["geometry"].strip() for item in center_models), f"{label}: reviewed coordination center model is incomplete")
        require(contacts and all(item.get("distance_window_angstrom") is not None for item in contacts), f"{label}: reviewed coordination requires exact contact windows")
        for field in ("ligand_inventory", "denticity_hapticity_assignments", "counterion_models", "solvent_additive_occupancy", "alternative_associated_dissociated_states"):
            require(coordination_facts.get(field), f"{label}: reviewed coordination omits {field}")

    method = sections["method_protocol"]
    method_facts = method["facts"]
    require(method_facts.get("protocol_selection_authorization") is False, f"{label}: method record granted protocol-selection authority")
    if method["status"] == "reviewed_for_bounded_example":
        require(method_facts.get("applicability") in {"exact_literature_example_only", "reviewer_proposal_not_execution_approved", "synthetic_fixture_only"}, f"{label}: method applicability is unbounded")
        for field in ("method_or_functional", "dispersion", "relativistic_treatment", "solvation", "grid", "scf_controls", "geometry_frequency_relationship", "spin_wavefunction_sensitivity", "thermochemistry_policy"):
            require(isinstance(method_facts.get(field), str) and method_facts[field].strip(), f"{label}: reviewed method record lacks {field}")
        basis = method_facts.get("basis_and_ecp", [])
        require(basis and all(item.get("coverage_status") == "explicit" and isinstance(item.get("element_scope"), str) and item["element_scope"].strip() and isinstance(item.get("orbital_basis"), str) and item["orbital_basis"].strip() for item in basis), f"{label}: reviewed basis/ECP coverage is incomplete")

    ts_and_path = sections["ts_and_path"]
    ts_facts = ts_and_path["facts"]
    require(ts_facts.get("execution_selection_status") == "not_selected", f"{label}: TS review selected an execution strategy")
    require(ts_facts.get("mode_path_evidence_status") == "not_applicable_no_result", f"{label}: M1 review claimed result-level mode/path evidence")
    reviewed_strategy = ts_facts.get("reviewed_strategy_candidate")
    require(reviewed_strategy is None or reviewed_strategy in METAL_SEED_STRATEGIES, f"{label}: reviewed TS strategy candidate is outside the supported design inventory")
    if ts_and_path["status"] == "reviewed_for_bounded_example":
        for field in ("elementary_step_class", "reactant_state_id", "product_state_id", "frequency_and_mode_acceptance_policy"):
            require(isinstance(ts_facts.get(field), str) and ts_facts[field].strip(), f"{label}: reviewed TS design lacks {field}")
        require(ts_facts.get("reviewed_strategy_candidate_id") and reviewed_strategy in METAL_SEED_STRATEGIES and ts_facts.get("strategy_specific_evidence"), f"{label}: reviewed TS design lacks a strategy candidate or evidence")
        require(ts_facts.get("single_surface_assumption") is True and spin_facts.get("single_surface_assumption") is True, f"{label}: current reviewed TS strategy lacks a single-surface decision")
        require(spin_facts.get("spin_crossover_relevance") == "not_indicated" and spin_facts.get("minimum_energy_crossing_relevance") == "not_indicated", f"{label}: current reviewed TS strategy cannot represent a crossing surface")
        require(ts_facts.get("path_model") == "single_surface_candidate_no_connectivity_claim", f"{label}: reviewed TS path model widened its claim")

    all_reviewed = not blocked
    if all_reviewed:
        require(isinstance(provenance.get("reviewer"), str) and provenance["reviewer"].strip(), f"{label}: complete review record lacks a reviewer")
        require(isinstance(provenance.get("review_date"), str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", provenance["review_date"]), f"{label}: complete review record lacks an ISO review date")
    return all_reviewed, sorted(reviewed), sorted(blocked), unresolved


def validate_metal_scientific_review_source(source: dict[str, Any]) -> None:
    validate_structure(source, "metal-scientific-review-source")
    _validate_metal_review_content(
        source.get("provenance", {}),
        source.get("identity", {}),
        source.get("sections", {}),
        "metal scientific-review source",
    )


def validate_metal_scientific_review(
    review: dict[str, Any],
    design: dict[str, Any] | None = None,
    design_path: Path | None = None,
    template: dict[str, Any] | None = None,
    template_path: Path | None = None,
    candidate: dict[str, Any] | None = None,
    candidate_path: Path | None = None,
    review_source: dict[str, Any] | None = None,
    review_source_path: Path | None = None,
) -> None:
    validate_structure(review, "metal-scientific-review")
    expected_payload = payload_sha256(
        {key: value for key, value in review.items() if key != "review_payload_sha256"}
    )
    require(review.get("review_payload_sha256") == expected_payload, "metal scientific review: payload hash mismatch")
    require(review.get("calculation_ready") is False, "metal scientific review: calculation_ready must remain false")
    require(review.get("no_submission_authorization") is True, "metal scientific review: submission authority is forbidden")
    require(review.get("runtime_support_status") == "unsupported_requires_extension", "metal scientific review: runtime support must remain blocked")
    require(review.get("submission_decision") == "refused", "metal scientific review: submission decision must remain refused")
    require(review.get("promotion_decision") == "refused", "metal scientific review: promotion decision must remain refused")
    require(review.get("scientific_acceptance_decision") == "not_granted_by_artifact", "metal scientific review: artifact granted scientific acceptance")
    require(review.get("literature_values_are_defaults") is False, "metal scientific review: literature values were treated as defaults")
    require(review.get("claim_ceiling") == "bounded_review_record_only_no_scientific_acceptance_ts_or_selectivity_claim", "metal scientific review: claim ceiling was widened")
    require(review.get("hard_rejections"), "metal scientific review: hard rejections are missing")

    identity = review.get("identity_binding", {})
    atom_order = identity.get("atom_order", [])
    require([item.get("index") for item in atom_order] == list(range(1, len(atom_order) + 1)), "metal scientific review: atom order must be contiguous and one-based")
    require(identity.get("atom_count") == len(atom_order), "metal scientific review: atom count differs from atom order")
    metal_indices = {item.get("atom_index") for item in identity.get("metal_centers", [])}
    atom_elements = {item.get("index"): item.get("element") for item in atom_order}
    for center in identity.get("metal_centers", []):
        require(atom_elements.get(center.get("atom_index")) == center.get("element"), "metal scientific review: metal-center identity differs from atom order")

    all_reviewed, reviewed_sections, blocked_sections, unresolved = _validate_metal_review_content(
        review.get("review_scope", {}), identity, review.get("sections", {}), "metal scientific review"
    )
    coordination_contacts = review.get("sections", {}).get("coordination", {}).get("facts", {}).get("coordination_contacts", [])
    expected_contacts = {
        (item.get("donor_atom"), item.get("acceptor_atom"), item.get("kind"))
        for item in identity.get("coordination_contacts", [])
    }
    actual_contacts = {
        (item.get("donor_atom"), item.get("acceptor_atom"), item.get("kind"))
        for item in coordination_contacts
    }
    require(expected_contacts == actual_contacts, "metal scientific review: coordination contacts differ from the identity binding")
    require(all(item.get("acceptor_atom") in metal_indices for item in coordination_contacts), "metal scientific review: coordination contact is not bound to a metal center")

    completion = review.get("completion", {})
    require(completion.get("reviewed_sections") == reviewed_sections, "metal scientific review: reviewed-section summary mismatch")
    require(completion.get("blocked_sections") == blocked_sections, "metal scientific review: blocked-section summary mismatch")
    require(sorted(completion.get("unresolved_blockers", [])) == sorted(unresolved), "metal scientific review: blocker summary mismatch")
    require(completion.get("metal_m2_offline_runtime_contract") == "blocked" and completion.get("metal_m3_execution_boundary") == "blocked" and completion.get("metal_m4_live_smoke") == "blocked", "metal scientific review: downstream boundary was widened")
    scope_kind = review.get("review_scope", {}).get("scope_kind")
    expected_m1 = (
        "not_satisfied_synthetic_fixture"
        if all_reviewed and scope_kind == "synthetic_nonresearch_fixture"
        else "reviewed_bounded_example_runtime_unsupported"
        if all_reviewed
        else "pending_scientific_review"
    )
    require(completion.get("metal_m1_scientific_review_status") == expected_m1, "metal scientific review: M1 status does not match scope and completeness")
    require(review.get("status") == ("review_contract_complete_runtime_unsupported" if all_reviewed else "blocked_incomplete_scientific_review"), "metal scientific review: top-level status does not match section completeness")

    if design is not None:
        require(design_path is not None, "metal scientific review: design_path is required with a design")
        validate_metal_support(design)
        require(review.get("design_source", {}).get("sha256") == sha256(design_path), "metal scientific review: design hash mismatch")
        require(review.get("design_source", {}).get("design_payload_sha256") == design.get("design_payload_sha256"), "metal scientific review: design payload binding mismatch")
        require(review.get("study_id") == design.get("study_id"), "metal scientific review: design study ID mismatch")
    if template is not None:
        require(template_path is not None, "metal scientific review: template_path is required with a template")
        validate_metal_ts_audit_template(template, design, design_path) if design is not None else validate_metal_ts_audit_template(template)
        require(review.get("template_source", {}).get("sha256") == sha256(template_path), "metal scientific review: template hash mismatch")
        require(review.get("template_source", {}).get("template_payload_sha256") == template.get("template_payload_sha256"), "metal scientific review: template payload binding mismatch")
        for key in ("study_id", "candidate_id", "mechanism_id", "channel_id", "catalyst_state_id"):
            require(review.get(key) == template.get(key), f"metal scientific review: template {key} mismatch")
        template_identity = template.get("identity_binding", {})
        require(identity.get("atom_order") == template_identity.get("atom_order"), "metal scientific review: template atom order mismatch")
        require(identity.get("coordinate_changes") == template_identity.get("coordinate_changes"), "metal scientific review: template coordinate changes mismatch")
    if candidate is not None:
        require(candidate_path is not None, "metal scientific review: candidate_path is required with a candidate")
        validate_structure(candidate, "candidate")
        require(candidate.get("support_status") == "unsupported_transition_metal" and candidate.get("review_status") != "promoted_offline", "metal scientific review: candidate is not an unsupported, non-promoted metal case")
        require(review.get("candidate_source", {}).get("sha256") == sha256(candidate_path), "metal scientific review: candidate hash mismatch")
        for key in ("study_id", "candidate_id", "mechanism_id", "channel_id", "catalyst_state_id"):
            require(review.get(key) == candidate.get(key), f"metal scientific review: candidate {key} mismatch")
        expected_order = [
            {"index": item.get("index"), "element": item.get("element"), "role": item.get("role")}
            for item in candidate.get("atom_map", [])
        ]
        require(identity.get("atom_order") == expected_order, "metal scientific review: candidate atom order mismatch")
        require(identity.get("total_charge") == candidate.get("chemical_state", {}).get("charge"), "metal scientific review: candidate charge mismatch")
        require(identity.get("multiplicity") == candidate.get("chemical_state", {}).get("multiplicity"), "metal scientific review: candidate multiplicity mismatch")
    if review_source is not None:
        require(review_source_path is not None, "metal scientific review: review_source_path is required with a review source")
        validate_metal_scientific_review_source(review_source)
        require(review.get("review_source", {}).get("sha256") == sha256(review_source_path), "metal scientific review: review-source hash mismatch")
        require(review.get("review_id") == review_source.get("review_id"), "metal scientific review: review-source ID mismatch")
        require(review.get("review_scope") == review_source.get("provenance"), "metal scientific review: review-source provenance drift")
        require(review.get("sections") == review_source.get("sections"), "metal scientific review: review-source section drift")
        require(review.get("candidate_source", {}).get("sha256") == review_source.get("candidate_sha256"), "metal scientific review: review-source candidate binding mismatch")
        if design is not None:
            require(review_source.get("design_payload_sha256") == design.get("design_payload_sha256"), "metal scientific review: review source/design payload mismatch")
        if template is not None:
            require(review_source.get("template_payload_sha256") == template.get("template_payload_sha256"), "metal scientific review: review source/template payload mismatch")


def validate_metal_result_observation(
    observation: dict[str, Any],
    template: dict[str, Any] | None = None,
    template_path: Path | None = None,
    candidate: dict[str, Any] | None = None,
    candidate_path: Path | None = None,
    log_path: Path | None = None,
) -> None:
    """Validate a read-only metal log observation without granting TS status."""
    validate_structure(observation, "metal-result-observation")
    expected_payload = payload_sha256(
        {key: value for key, value in observation.items() if key != "audit_payload_sha256"}
    )
    require(
        observation.get("audit_payload_sha256") == expected_payload,
        "metal result observation: payload hash mismatch",
    )
    require(observation.get("calculation_ready") is False, "metal result observation: calculation_ready must remain false")
    require(observation.get("no_submission_authorization") is True, "metal result observation: submission authority is forbidden")
    require(observation.get("runtime_support_status") == "unsupported_requires_extension", "metal result observation: runtime support must remain blocked")
    require(observation.get("submission_decision") == "refused", "metal result observation: submission decision must remain refused")
    require(observation.get("promotion_decision") == "refused", "metal result observation: promotion decision must remain refused")
    require(observation.get("status") == "parsed_observation_blocked", "metal result observation: blocked status was bypassed")
    require(
        observation.get("claim_ceiling") == "parsed_observation_only_no_ts_or_selectivity_claim",
        "metal result observation: claim ceiling was widened",
    )

    identity = observation.get("identity_binding", {})
    atom_order = identity.get("atom_order", [])
    require(
        [item.get("index") for item in atom_order] == list(range(1, len(atom_order) + 1)),
        "metal result observation: atom order must be contiguous and one-based",
    )
    require(identity.get("atom_count") == len(atom_order), "metal result observation: atom count differs from atom order")
    for atom in atom_order:
        require(
            ATOMIC_NUMBERS.get(atom.get("element")) == atom.get("atomic_number"),
            "metal result observation: atomic number and element differ",
        )
    require(identity.get("identity_observation_status") == "matched_candidate", "metal result observation: identity match is not established")
    require(identity.get("charge_multiplicity_record_count", 0) >= 1, "metal result observation: charge/multiplicity evidence is absent")
    require(identity.get("orientation_count", 0) >= 1, "metal result observation: orientation evidence is absent")

    frequencies = observation.get("frequency_observations", {})
    values = frequencies.get("frequencies_cm_1", [])
    imaginary = frequencies.get("imaginary_frequencies_cm_1", [])
    require(all(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) for value in values), "metal result observation: frequencies must be finite")
    require(all(value < 0 for value in imaginary), "metal result observation: imaginary-frequency list contains a non-negative value")
    require(frequencies.get("frequency_count") == len(values), "metal result observation: frequency count mismatch")
    require(imaginary == [value for value in values if value < 0], "metal result observation: imaginary-frequency list mismatch")
    require(frequencies.get("raw_imaginary_frequency_count") == len(imaginary), "metal result observation: imaginary-frequency count mismatch")
    require(frequencies.get("exactly_one_raw_imaginary_observed") is (len(imaginary) == 1), "metal result observation: one-imaginary observation flag mismatch")
    require(frequencies.get("completeness_status") == "unassessed_requires_expected_mode_count", "metal result observation: frequency completeness was inferred")
    require(frequencies.get("mode_review_status") == "not_performed", "metal result observation: mode review was inferred")

    wavefunction = observation.get("wavefunction_observations", {})
    require(wavefunction.get("threshold_assessment") == "not_performed_no_approved_policy", "metal result observation: wavefunction thresholds were inferred")
    for item in wavefunction.get("s2_observations", []):
        require(
            all(isinstance(item.get(key), (int, float)) and not isinstance(item.get(key), bool) and math.isfinite(item[key]) for key in ("before_annihilation", "after_annihilation")),
            "metal result observation: S**2 observations must be finite",
        )

    coordination = observation.get("coordination_observations", {})
    require(
        coordination.get("inventory_assessment") == "not_performed_no_reviewed_windows_or_hapticity_rules",
        "metal result observation: coordination inventory was accepted without reviewed rules",
    )
    for contact in coordination.get("contacts", []):
        initial = contact.get("initial_distance_angstrom")
        final = contact.get("final_distance_angstrom")
        delta = contact.get("distance_change_angstrom")
        require(
            all(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) for value in (initial, final, delta)),
            "metal result observation: coordination distances must be finite",
        )
        require(initial >= 0 and final >= 0, "metal result observation: coordination distances must be non-negative")
        require(math.isclose(delta, final - initial, abs_tol=1e-7), "metal result observation: coordination-distance delta mismatch")
        require(contact.get("distance_window_angstrom") is None, "metal result observation: coordination distance window was inferred")
        require(contact.get("review_status") == "observed_unreviewed_no_window", "metal result observation: coordination contact was accepted")

    required_sections = {
        "electron_accounting", "spin_surface", "wavefunction",
        "coordination", "method_protocol", "ts_and_path",
    }
    sections = observation.get("audit_sections", {})
    require(set(sections) == required_sections, "metal result observation: audit-section inventory is incomplete")
    require(
        all(item.get("status") == "blocked_pending_review" and item.get("reason") for item in sections.values()),
        "metal result observation: a scientific review section was bypassed",
    )
    require(observation.get("diagnostics"), "metal result observation: diagnostics are missing")

    if template is not None:
        require(template_path is not None, "metal result observation: template_path is required with a template")
        validate_metal_ts_audit_template(template)
        require(observation.get("template_source", {}).get("sha256") == sha256(template_path), "metal result observation: template hash mismatch")
        for key in ("study_id", "candidate_id", "mechanism_id", "channel_id", "catalyst_state_id"):
            require(observation.get(key) == template.get(key), f"metal result observation: template {key} mismatch")
        expected_contacts = {
            (item.get("donor_atom"), item.get("acceptor_atom"), item.get("kind"))
            for item in template.get("identity_binding", {}).get("coordination_contacts", [])
        }
        observed_contacts = {
            (item.get("donor_atom"), item.get("acceptor_atom"), item.get("kind"))
            for item in coordination.get("contacts", [])
        }
        require(observed_contacts == expected_contacts, "metal result observation: template coordination-contact inventory mismatch")

    if candidate is not None:
        require(candidate_path is not None, "metal result observation: candidate_path is required with a candidate")
        validate_structure(candidate, "candidate")
        require(candidate.get("support_status") == "unsupported_transition_metal", "metal result observation: candidate is not an unsupported metal case")
        require(candidate.get("review_status") != "promoted_offline", "metal result observation: unsupported candidate was promoted")
        require(observation.get("candidate_source", {}).get("sha256") == sha256(candidate_path), "metal result observation: candidate hash mismatch")
        require(identity.get("charge") == candidate.get("chemical_state", {}).get("charge"), "metal result observation: candidate charge mismatch")
        require(identity.get("multiplicity") == candidate.get("chemical_state", {}).get("multiplicity"), "metal result observation: candidate multiplicity mismatch")
        expected_order = [
            {"index": item.get("index"), "element": item.get("element")}
            for item in candidate.get("atom_map", [])
        ]
        observed_order = [
            {"index": item.get("index"), "element": item.get("element")}
            for item in atom_order
        ]
        require(observed_order == expected_order, "metal result observation: candidate atom order mismatch")

    if log_path is not None:
        require(log_path.is_file() and not log_path.is_symlink(), "metal result observation: log must be a regular non-symlink file")
        require(observation.get("log_source", {}).get("sha256") == sha256(log_path), "metal result observation: log hash mismatch")


def validate_metal_input_observation(
    observation: dict[str, Any],
    template: dict[str, Any] | None = None,
    template_path: Path | None = None,
    candidate: dict[str, Any] | None = None,
    candidate_path: Path | None = None,
    scientific_review: dict[str, Any] | None = None,
    scientific_review_path: Path | None = None,
    input_path: Path | None = None,
) -> None:
    """Validate a read-only existing-input observation with all authority refused."""
    validate_structure(observation, "metal-input-observation")
    expected_payload = payload_sha256(
        {key: value for key, value in observation.items() if key != "audit_payload_sha256"}
    )
    require(observation.get("audit_payload_sha256") == expected_payload, "metal input observation: payload hash mismatch")
    require(observation.get("status") == "parsed_input_observation_blocked", "metal input observation: blocked status was bypassed")
    require(observation.get("calculation_ready") is False, "metal input observation: calculation_ready must remain false")
    require(observation.get("no_submission_authorization") is True, "metal input observation: submission authority is forbidden")
    require(observation.get("runtime_support_status") == "unsupported_requires_extension", "metal input observation: runtime support must remain blocked")
    require(observation.get("input_acceptance_decision") == "not_granted_by_artifact", "metal input observation: input acceptance was granted")
    require(observation.get("protocol_selection_decision") == "absent_not_authorized", "metal input observation: protocol selection was inferred")
    require(observation.get("submission_decision") == "refused", "metal input observation: submission decision must remain refused")
    require(observation.get("promotion_decision") == "refused", "metal input observation: promotion decision must remain refused")
    require(
        observation.get("claim_ceiling") == "existing_input_observation_only_no_acceptance_execution_ts_or_selectivity_claim",
        "metal input observation: claim ceiling was widened",
    )
    parser = observation.get("parser", {})
    require(
        parser.get("parser_id") == "auto_g16_asymmetric_metal_input_observer_v1"
        and parser.get("scope") == "offline_read_only_existing_input_observation"
        and parser.get("renders_input") is False,
        "metal input observation: parser scope or rendering refusal changed",
    )

    identity = observation.get("identity_binding", {})
    atom_order = identity.get("atom_order", [])
    require(
        [item.get("index") for item in atom_order] == list(range(1, len(atom_order) + 1)),
        "metal input observation: atom order must be contiguous and one-based",
    )
    require(identity.get("atom_count") == len(atom_order), "metal input observation: atom count differs from atom order")
    for atom in atom_order:
        require(
            ATOMIC_NUMBERS.get(atom.get("element")) == atom.get("atomic_number"),
            "metal input observation: atomic number and element differ",
        )
    require(
        identity.get("identity_observation_status") == "matched_candidate_template_review",
        "metal input observation: exact identity match is not established",
    )

    parsed = observation.get("input_observations", {})
    require(parsed.get("charge") == identity.get("charge"), "metal input observation: parsed charge differs from identity")
    require(parsed.get("multiplicity") == identity.get("multiplicity"), "metal input observation: parsed multiplicity differs from identity")
    require(parsed.get("atom_count") == len(atom_order), "metal input observation: parsed atom count differs from identity")
    require(parsed.get("atom_order") == atom_order, "metal input observation: parsed atom order differs from identity")
    route = parsed.get("route_text", "")
    require(isinstance(route, str) and route.startswith("#"), "metal input observation: route observation is malformed")
    require(
        parsed.get("route_sha256") == hashlib.sha256(route.encode("utf-8")).hexdigest(),
        "metal input observation: route hash mismatch",
    )
    route_lower = route.lower()
    task = parsed.get("task_text_observations", {})
    expected_task = {
        "opt_text_observed": re.search(r"(?i)(?:^|[\s,(])opt(?:[\s,=(]|$)", route) is not None,
        "freq_text_observed": re.search(r"(?i)(?:^|[\s,(])freq(?:[\s,=(]|$)", route) is not None,
        "ts_text_observed": re.search(r"(?i)(?:^|[\s,(])ts(?:[\s,)=]|$)", route) is not None,
        "geom_check_text_observed": "geom=check" in route_lower or "geom=allcheck" in route_lower,
        "gen_or_genecp_text_observed": re.search(r"(?i)(?:^|[\s/])gen(?:ecp)?(?:[\s,]|$)", route) is not None,
    }
    require(task == expected_task, "metal input observation: task-text flags differ from the observed route")
    require(task.get("geom_check_text_observed") is False, "metal input observation: Geom=Check/AllCheck ambiguity was accepted")
    require(parsed.get("explicit_cartesian_geometry_status") == "parsed", "metal input observation: explicit Cartesian geometry was not parsed")
    require(parsed.get("protocol_selection_binding_status") == "absent_not_accepted", "metal input observation: protocol binding was inferred")
    require(parsed.get("remote_path_validation_status") == "not_performed_offline_no_execution_authority", "metal input observation: remote path safety was inferred")
    trailing_count = parsed.get("trailing_section_line_count")
    trailing_hash = parsed.get("trailing_section_sha256")
    require(
        isinstance(trailing_count, int) and not isinstance(trailing_count, bool) and trailing_count >= 0,
        "metal input observation: trailing-section line count is invalid",
    )
    require(
        (trailing_count == 0 and trailing_hash is None)
        or (trailing_count > 0 and isinstance(trailing_hash, str) and HASH_RE.fullmatch(trailing_hash) is not None),
        "metal input observation: trailing-section hash/count mismatch",
    )
    directives = parsed.get("link0_directives", [])
    keys = [item.get("key") for item in directives]
    require(len(keys) == len(set(keys)), "metal input observation: duplicate Link 0 directive")
    absolute_path = re.compile(r"^(?:/|[A-Za-z]:[\\/])")
    expected_absolute = any(absolute_path.match(str(item.get("value", ""))) is not None for item in directives)
    require(
        parsed.get("contains_absolute_link0_path_observed") is expected_absolute,
        "metal input observation: absolute Link 0 path flag mismatch",
    )

    review_binding = observation.get("review_binding", {})
    require(
        review_binding.get("scientific_acceptance_decision") == "not_granted_by_artifact",
        "metal input observation: bound review granted scientific acceptance",
    )
    sections = observation.get("audit_sections", {})
    require(set(sections) == METAL_REVIEW_SECTIONS, "metal input observation: audit-section inventory is incomplete")
    require(
        all(item.get("status") == "blocked_pending_review" and item.get("reason") for item in sections.values()),
        "metal input observation: a scientific review section was bypassed",
    )
    completion = observation.get("completion", {})
    require(completion.get("metal_m2c_input_observation") == "implemented_offline", "metal input observation: M2c status is invalid")
    require(completion.get("metal_m2_offline_runtime_contract") == "blocked", "metal input observation: M2 runtime contract was widened")
    require(completion.get("metal_m3_execution_boundary") == "blocked", "metal input observation: M3 execution boundary was widened")
    require(completion.get("metal_m4_live_smoke") == "blocked", "metal input observation: M4 live smoke was widened")
    require(observation.get("diagnostics") and observation.get("hard_rejections"), "metal input observation: refusal evidence is missing")

    if template is not None:
        require(template_path is not None, "metal input observation: template_path is required with a template")
        validate_metal_ts_audit_template(template)
        require(observation.get("template_source", {}).get("sha256") == sha256(template_path), "metal input observation: template hash mismatch")
        for key in ("study_id", "candidate_id", "mechanism_id", "channel_id", "catalyst_state_id"):
            require(observation.get(key) == template.get(key), f"metal input observation: template {key} mismatch")
        template_order = [
            {"index": item.get("index"), "element": item.get("element")}
            for item in template.get("identity_binding", {}).get("atom_order", [])
        ]
        observed_order = [{"index": item.get("index"), "element": item.get("element")} for item in atom_order]
        require(observed_order == template_order, "metal input observation: template atom order mismatch")
        require(identity.get("charge") == template.get("identity_binding", {}).get("charge"), "metal input observation: template charge mismatch")
        require(identity.get("multiplicity") == template.get("identity_binding", {}).get("multiplicity"), "metal input observation: template multiplicity mismatch")

    if candidate is not None:
        require(candidate_path is not None, "metal input observation: candidate_path is required with a candidate")
        validate_structure(candidate, "candidate")
        require(candidate.get("support_status") == "unsupported_transition_metal", "metal input observation: candidate is not an unsupported metal case")
        require(candidate.get("review_status") != "promoted_offline", "metal input observation: unsupported candidate was promoted")
        require(observation.get("candidate_source", {}).get("sha256") == sha256(candidate_path), "metal input observation: candidate hash mismatch")
        candidate_order = [
            {"index": item.get("index"), "element": item.get("element")}
            for item in candidate.get("atom_map", [])
        ]
        observed_order = [{"index": item.get("index"), "element": item.get("element")} for item in atom_order]
        require(observed_order == candidate_order, "metal input observation: candidate atom order mismatch")
        require(identity.get("charge") == candidate.get("chemical_state", {}).get("charge"), "metal input observation: candidate charge mismatch")
        require(identity.get("multiplicity") == candidate.get("chemical_state", {}).get("multiplicity"), "metal input observation: candidate multiplicity mismatch")

    if scientific_review is not None:
        require(scientific_review_path is not None, "metal input observation: scientific_review_path is required with a review")
        validate_metal_scientific_review(scientific_review)
        require(
            observation.get("scientific_review_source", {}).get("sha256") == sha256(scientific_review_path),
            "metal input observation: scientific-review hash mismatch",
        )
        require(review_binding.get("review_id") == scientific_review.get("review_id"), "metal input observation: review ID mismatch")
        require(review_binding.get("review_status") == scientific_review.get("status"), "metal input observation: review status mismatch")
        require(
            review_binding.get("metal_m1_scientific_review_status")
            == scientific_review.get("completion", {}).get("metal_m1_scientific_review_status"),
            "metal input observation: M1 status mismatch",
        )
        for key in ("study_id", "candidate_id", "mechanism_id", "channel_id", "catalyst_state_id"):
            require(observation.get(key) == scientific_review.get(key), f"metal input observation: review {key} mismatch")

    if input_path is not None:
        require(input_path.is_file() and not input_path.is_symlink(), "metal input observation: input must be a regular non-symlink file")
        require(observation.get("input_source", {}).get("sha256") == sha256(input_path), "metal input observation: input hash mismatch")


def _validate_metal_acceptance_sections(
    sections: Any,
    scientific_review: dict[str, Any] | None = None,
    input_observation: dict[str, Any] | None = None,
    result_observation: dict[str, Any] | None = None,
) -> dict[str, str]:
    require(isinstance(sections, dict) and set(sections) == METAL_ACCEPTANCE_SECTIONS, "metal acceptance: section inventory is incomplete")
    fact_fields = {
        "wavefunction": {"observed_s2_count", "stability_statement_observed", "spin_contamination_assessment", "occupation_assessment", "alternative_solution_assessment", "multireference_assessment"},
        "coordination": {"contact_assessments", "hapticity_assessment", "ligand_inventory_assessment", "unintended_state_change"},
        "mode": {"raw_imaginary_frequency_count", "mode_evidence_sha256", "intended_coordinate_assessment", "unintended_coordination_loss_assessment"},
        "input_acceptance": {"input_sha256", "protocol_options_sha256", "protocol_selection_sha256", "input_approval_sha256", "input_result_lineage_sha256", "exact_input_hash_confirmed", "route_reviewed", "element_basis_ecp_coverage_reviewed", "solvent_thermochemistry_reviewed", "resource_and_server_path_reviewed"},
    }
    decisions: dict[str, str] = {}
    for name in sorted(METAL_ACCEPTANCE_SECTIONS):
        section = sections[name]
        require(isinstance(section, dict) and set(section) == {"decision", "facts", "evidence", "review_notes", "blockers"}, f"metal acceptance: {name} section fields are incomplete")
        decision = section.get("decision")
        require(decision in METAL_ACCEPTANCE_DECISIONS, f"metal acceptance: {name} decision is invalid")
        decisions[name] = decision
        facts = section.get("facts")
        require(isinstance(facts, dict) and set(facts) == fact_fields[name], f"metal acceptance: {name} facts are incomplete")
        evidence = section.get("evidence")
        require(isinstance(evidence, list), f"metal acceptance: {name} evidence must be an array")
        evidence_ids: set[str] = set()
        for item in evidence:
            require(isinstance(item, dict) and set(item) == {"evidence_id", "evidence_kind", "sha256", "locator"}, f"metal acceptance: {name} evidence record is invalid")
            evidence_id = item.get("evidence_id")
            require(isinstance(evidence_id, str) and ID_RE.fullmatch(evidence_id) is not None and evidence_id not in evidence_ids, f"metal acceptance: {name} evidence ID is invalid or duplicate")
            evidence_ids.add(evidence_id)
            require(item.get("evidence_kind") in {"synthetic_fixture", "reviewer_record", "mode_displacement", "protocol_artifact", "input_approval", "coordination_review", "wavefunction_review"}, f"metal acceptance: {name} evidence kind is invalid")
            value = item.get("sha256")
            require(value is None or (isinstance(value, str) and HASH_RE.fullmatch(value) is not None), f"metal acceptance: {name} evidence hash is invalid")
            require(isinstance(item.get("locator"), str) and item["locator"].strip(), f"metal acceptance: {name} evidence locator is missing")
        require(isinstance(section.get("review_notes"), str) and section["review_notes"].strip(), f"metal acceptance: {name} review notes are missing")
        blockers = section.get("blockers")
        require(isinstance(blockers, list) and all(isinstance(item, str) and item.strip() for item in blockers), f"metal acceptance: {name} blockers are invalid")
        if decision == "blocked_missing_evidence":
            require(blockers, f"metal acceptance: {name} blocked decision lacks blockers")
        else:
            require(evidence and all(item.get("sha256") is not None for item in evidence), f"metal acceptance: {name} reviewed decision lacks hash-bound evidence")
        if decision == "accepted_for_bounded_offline_review":
            require(not blockers, f"metal acceptance: {name} accepted decision retains blockers")
            if scientific_review is not None:
                m1_name = {"wavefunction": "wavefunction", "coordination": "coordination", "mode": "ts_and_path", "input_acceptance": "method_protocol"}[name]
                require(scientific_review.get("sections", {}).get(m1_name, {}).get("status") == "reviewed_for_bounded_example", f"metal acceptance: {name} accepted while M1 is blocked")

    wave = sections["wavefunction"]["facts"]
    if result_observation is not None:
        observed = result_observation.get("wavefunction_observations", {})
        require(wave.get("observed_s2_count") in {None, len(observed.get("s2_observations", []))}, "metal acceptance: wavefunction S2 count mismatch")
        require(wave.get("stability_statement_observed") in {None, observed.get("stability_statement_observed")}, "metal acceptance: stability observation mismatch")
    if decisions["wavefunction"] == "accepted_for_bounded_offline_review":
        require(wave.get("stability_statement_observed") is True, "metal acceptance: wavefunction accepted without stability evidence")
        require(all(isinstance(wave.get(key), str) and wave[key].strip() for key in ("spin_contamination_assessment", "occupation_assessment", "alternative_solution_assessment", "multireference_assessment")), "metal acceptance: wavefunction accepted without full assessments")

    coordination = sections["coordination"]["facts"]
    contacts = coordination.get("contact_assessments")
    require(isinstance(contacts, list), "metal acceptance: coordination contacts must be an array")
    if result_observation is not None and contacts:
        expected = result_observation.get("coordination_observations", {}).get("contacts", [])
        keys = ("donor_atom", "acceptor_atom", "kind", "initial_distance_angstrom", "final_distance_angstrom")
        require([{key: item.get(key) for key in keys} for item in contacts] == [{key: item.get(key) for key in keys} for item in expected], "metal acceptance: coordination observation mismatch")
    if decisions["coordination"] == "accepted_for_bounded_offline_review":
        if result_observation is not None:
            require(len(contacts) == len(result_observation.get("coordination_observations", {}).get("contacts", [])), "metal acceptance: coordination contact coverage mismatch")
        require(all(item.get("within_reviewed_window") is True for item in contacts), "metal acceptance: coordination accepted with an unpassed contact")
        require(coordination.get("unintended_state_change") is False, "metal acceptance: coordination accepted an unintended state change")
        require(all(isinstance(coordination.get(key), str) and coordination[key].strip() for key in ("hapticity_assessment", "ligand_inventory_assessment")), "metal acceptance: coordination accepted without inventory review")

    mode = sections["mode"]["facts"]
    if result_observation is not None:
        count = result_observation.get("frequency_observations", {}).get("raw_imaginary_frequency_count")
        require(mode.get("raw_imaginary_frequency_count") in {None, count}, "metal acceptance: mode frequency count mismatch")
    if decisions["mode"] == "accepted_for_bounded_offline_review":
        require(mode.get("raw_imaginary_frequency_count") == 1, "metal acceptance: mode requires exactly one imaginary frequency")
        require(isinstance(mode.get("mode_evidence_sha256"), str) and HASH_RE.fullmatch(mode["mode_evidence_sha256"]) is not None, "metal acceptance: mode evidence hash is missing")
        require(all(isinstance(mode.get(key), str) and mode[key].strip() for key in ("intended_coordinate_assessment", "unintended_coordination_loss_assessment")), "metal acceptance: mode accepted without displacement assessments")

    input_facts = sections["input_acceptance"]["facts"]
    if input_observation is not None:
        require(input_facts.get("input_sha256") in {None, input_observation.get("input_source", {}).get("sha256")}, "metal acceptance: exact input hash mismatch")
    if decisions["input_acceptance"] == "accepted_for_bounded_offline_review":
        for key in ("input_sha256", "protocol_options_sha256", "protocol_selection_sha256", "input_approval_sha256", "input_result_lineage_sha256"):
            require(isinstance(input_facts.get(key), str) and HASH_RE.fullmatch(input_facts[key]) is not None, f"metal acceptance: input {key} is missing")
        for key in ("exact_input_hash_confirmed", "route_reviewed", "element_basis_ecp_coverage_reviewed", "solvent_thermochemistry_reviewed", "resource_and_server_path_reviewed"):
            require(input_facts.get(key) is True, f"metal acceptance: input {key} was not reviewed")
    return decisions


def validate_metal_acceptance_review_source(source: dict[str, Any]) -> None:
    validate_structure(source, "metal-acceptance-review-source")
    _validate_metal_acceptance_sections(source.get("sections"))


def validate_metal_acceptance_review(
    review: dict[str, Any],
    template: dict[str, Any] | None = None, template_path: Path | None = None,
    candidate: dict[str, Any] | None = None, candidate_path: Path | None = None,
    scientific_review: dict[str, Any] | None = None, scientific_review_path: Path | None = None,
    input_observation: dict[str, Any] | None = None, input_observation_path: Path | None = None,
    result_observation: dict[str, Any] | None = None, result_observation_path: Path | None = None,
    decision_source: dict[str, Any] | None = None, decision_source_path: Path | None = None,
) -> None:
    validate_structure(review, "metal-acceptance-review")
    expected_payload = payload_sha256({key: value for key, value in review.items() if key != "review_payload_sha256"})
    require(review.get("review_payload_sha256") == expected_payload, "metal acceptance review: payload hash mismatch")
    require(review.get("calculation_ready") is False and review.get("no_submission_authorization") is True, "metal acceptance review: offline refusal flags changed")
    require(review.get("runtime_support_status") == "unsupported_requires_extension", "metal acceptance review: runtime support was widened")
    for field in ("scientific_acceptance_decision", "input_acceptance_decision", "mode_acceptance_decision"):
        require(review.get(field) == "not_granted_by_artifact", f"metal acceptance review: {field} was granted")
    require(review.get("promotion_decision") == "refused" and review.get("submission_decision") == "refused", "metal acceptance review: promotion or submission was granted")
    require(review.get("claim_ceiling") == "manual_decision_record_only_no_runtime_promotion_ts_path_or_selectivity_claim", "metal acceptance review: claim ceiling was widened")
    decisions = _validate_metal_acceptance_sections(review.get("sections"), scientific_review, input_observation, result_observation)
    accepted = sorted(name for name, value in decisions.items() if value == "accepted_for_bounded_offline_review")
    rejected = sorted(name for name, value in decisions.items() if value == "rejected_by_reviewer")
    blocked = sorted(name for name, value in decisions.items() if value == "blocked_missing_evidence")
    summary = review.get("decision_summary", {})
    require(summary.get("accepted_sections") == accepted and summary.get("rejected_sections") == rejected and summary.get("blocked_sections") == blocked, "metal acceptance review: decision summary mismatch")
    all_accepted = len(accepted) == len(METAL_ACCEPTANCE_SECTIONS)
    expected_m2 = "not_satisfied_synthetic_fixture" if all_accepted and review.get("scope", {}).get("scope_kind") == "synthetic_nonresearch_fixture" else "reviewed_bounded_example_runtime_unsupported" if all_accepted else "reviewer_rejected" if rejected else "pending_acceptance_review"
    require(summary.get("metal_m2_acceptance_review_status") == expected_m2, "metal acceptance review: M2 status mismatch")
    expected_status = "acceptance_record_complete_runtime_unsupported" if all_accepted else "acceptance_record_contains_rejection_runtime_unsupported" if rejected else "blocked_incomplete_acceptance_review"
    require(review.get("status") == expected_status, "metal acceptance review: top-level status mismatch")
    completion = review.get("completion", {})
    require(completion.get("metal_m2d_acceptance_review_contract") == "implemented_offline" and completion.get("metal_m2_offline_runtime_contract") == "blocked" and completion.get("metal_m3_execution_boundary") == "blocked" and completion.get("metal_m4_live_smoke") == "blocked", "metal acceptance review: downstream boundary was widened")
    identity = review.get("identity_binding", {})
    order = identity.get("atom_order", [])
    require([item.get("index") for item in order] == list(range(1, len(order) + 1)) and identity.get("atom_count") == len(order), "metal acceptance review: atom order/count mismatch")
    require(all(ATOMIC_NUMBERS.get(item.get("element")) == item.get("atomic_number") for item in order), "metal acceptance review: atomic number/element mismatch")
    require(review.get("hard_rejections"), "metal acceptance review: hard rejections are missing")

    artifacts = (
        (template, template_path, "template_source", validate_metal_ts_audit_template),
        (candidate, candidate_path, "candidate_source", lambda value: validate_structure(value, "candidate")),
        (scientific_review, scientific_review_path, "scientific_review_source", validate_metal_scientific_review),
        (input_observation, input_observation_path, "input_observation_source", validate_metal_input_observation),
        (result_observation, result_observation_path, "result_observation_source", validate_metal_result_observation),
        (decision_source, decision_source_path, "decision_source", validate_metal_acceptance_review_source),
    )
    for artifact, path, binding, validator in artifacts:
        if artifact is None:
            continue
        require(path is not None, f"metal acceptance review: {binding} path is required")
        validator(artifact)
        require(review.get(binding, {}).get("sha256") == sha256(path), f"metal acceptance review: {binding} hash mismatch")
    if candidate is not None:
        require(candidate.get("support_status") == "unsupported_transition_metal" and candidate.get("review_status") != "promoted_offline", "metal acceptance review: candidate support boundary changed")
        require(identity.get("charge") == candidate.get("chemical_state", {}).get("charge") and identity.get("multiplicity") == candidate.get("chemical_state", {}).get("multiplicity"), "metal acceptance review: candidate charge/multiplicity mismatch")
        require([{"index": item.get("index"), "element": item.get("element")} for item in order] == [{"index": item.get("index"), "element": item.get("element")} for item in candidate.get("atom_map", [])], "metal acceptance review: candidate atom order mismatch")
    for artifact in (template, candidate, scientific_review, input_observation, result_observation, decision_source):
        if artifact is None:
            continue
        for key in ("study_id", "candidate_id", "mechanism_id", "channel_id", "catalyst_state_id"):
            if key in artifact:
                require(review.get(key) == artifact.get(key), f"metal acceptance review: {key} lineage mismatch")
    if decision_source is not None:
        require(review.get("review_id") == decision_source.get("review_id") and review.get("scope") == decision_source.get("scope") and review.get("sections") == decision_source.get("sections"), "metal acceptance review: decision source content drift")


def validate_smoke_proposal(
    proposal: dict[str, Any],
    literature_ledger: dict[str, Any] | None = None,
    literature_ledger_path: Path | None = None,
) -> None:
    validate_structure(proposal, "smoke-proposal")
    expected = payload_sha256({key: value for key, value in proposal.items() if key != "proposal_payload_sha256"})
    require(proposal.get("proposal_payload_sha256") == expected, "smoke-proposal: payload hash mismatch")
    gaussian = proposal.get("proposed_gaussian", {})
    require(gaussian.get("route") is None, "smoke-proposal: runnable route is forbidden")
    require(gaussian.get("input_text") is None, "smoke-proposal: rendered input is forbidden")
    require(gaussian.get("input_sha256") is None, "smoke-proposal: input hash implies an unauthorized rendered input")
    server = proposal.get("server_plan", {})
    require(server.get("status") == "not_created", "smoke-proposal: server project must not exist")
    require(server.get("fresh_project") is None, "smoke-proposal: server project must remain unset")
    require(server.get("overwrite") is False, "smoke-proposal: overwrite must remain false")
    require(server.get("allowed_root") == "/home/user100/SDL", "smoke-proposal: allowed server root changed")
    if literature_ledger is not None:
        require(literature_ledger_path is not None, "smoke-proposal: literature_ledger_path is required with a ledger")
        validate_literature_benchmark(literature_ledger)
        chemical = proposal.get("chemical_system", {})
        reference = chemical.get("literature_ledger", {})
        require(reference.get("sha256") == sha256(literature_ledger_path), "smoke-proposal: literature ledger hash mismatch")
        candidates = {item["candidate_id"]: item for item in literature_ledger.get("candidates", [])}
        candidate = candidates.get(chemical.get("candidate_id"))
        require(candidate is not None, "smoke-proposal: candidate absent from literature ledger")
        require(candidate.get("priority") == 1, "smoke-proposal: candidate is not priority 1")
        require(chemical.get("formula") == candidate.get("atom_inventory", {}).get("formula"), "smoke-proposal: formula mismatch")
        require(chemical.get("atom_count") == candidate.get("atom_inventory", {}).get("atom_count"), "smoke-proposal: atom-count mismatch")
        require(chemical.get("coordinate_artifact") == candidate.get("geometry", {}).get("artifact"), "smoke-proposal: coordinate artifact mismatch")


def validate_live_smoke_evidence(evidence: dict[str, Any]) -> None:
    validate_structure(evidence, "live-smoke-evidence")
    expected = payload_sha256({key: value for key, value in evidence.items() if key != "evidence_payload_sha256"})
    require(evidence.get("evidence_payload_sha256") == expected, "live-smoke-evidence: payload hash mismatch")
    if evidence.get("status") != "passed":
        return
    bindings = evidence.get("source_bindings", {})
    require(isinstance(bindings.get("protocol_options"), dict), "live-smoke-evidence: passed status requires pre-input protocol options provenance")
    require(isinstance(bindings.get("protocol_selection"), dict), "live-smoke-evidence: passed status requires explicit pre-input protocol selection provenance")
    execution = evidence.get("execution", {})
    for field in (
        "terminal_state_confirmed", "transport_hashes_verified",
        "fresh_project_guard_passed", "resource_policy_reviewed",
    ):
        require(execution.get(field) is True, f"live-smoke-evidence: passed status requires {field}")
    ts = evidence.get("ts_validation", {})
    require(ts.get("normal_termination") is True, "live-smoke-evidence: passed status requires normal termination")
    require(ts.get("error_termination") is False, "live-smoke-evidence: passed status conflicts with error termination")
    require(ts.get("stationary_point") is True, "live-smoke-evidence: passed status requires a stationary point")
    require(ts.get("frequency_complete") is True, "live-smoke-evidence: passed status requires complete frequencies")
    require(ts.get("raw_imaginary_frequency_count") == 1, "live-smoke-evidence: passed status requires exactly one raw imaginary frequency")
    require(ts.get("first_order_saddle_candidate") is True, "live-smoke-evidence: passed status requires a first-order saddle candidate")
    require(
        isinstance(ts.get("featured_imaginary_frequency_cm1"), (int, float))
        and not isinstance(ts.get("featured_imaginary_frequency_cm1"), bool)
        and math.isfinite(ts["featured_imaginary_frequency_cm1"])
        and ts["featured_imaginary_frequency_cm1"] < 0,
        "live-smoke-evidence: passed status requires one finite negative featured frequency",
    )
    mode = evidence.get("mode_validation", {})
    require(mode.get("decision") == "accepted", "live-smoke-evidence: passed status requires an accepted mode decision")
    require(mode.get("confirmed") is True, "live-smoke-evidence: passed status requires a confirmed mode decision")
    require(mode.get("coordinate_projection_reviewed") is True, "live-smoke-evidence: passed status requires coordinate review")


def validate_literature_benchmark(ledger: dict[str, Any]) -> None:
    validate_structure(ledger, "literature-benchmark")
    expected = payload_sha256({key: value for key, value in ledger.items() if key != "ledger_payload_sha256"})
    require(ledger.get("ledger_payload_sha256") == expected, "literature-benchmark: payload hash mismatch")
    candidates = unique_index(ledger.get("candidates", []), "candidate_id", "literature-benchmark.candidates")
    for candidate_id, candidate in candidates.items():
        inventory = candidate.get("atom_inventory", {})
        atom_count = inventory.get("atom_count")
        atom_order = inventory.get("atom_order", [])
        require(atom_count == len(atom_order), f"literature candidate {candidate_id}: atom order/count mismatch")
        require(sum(inventory.get("element_counts", {}).values()) == atom_count, f"literature candidate {candidate_id}: element count mismatch")
        for change in candidate.get("coordinate_changes", []):
            require(all(1 <= index <= atom_count for index in change.get("atoms", [])), f"literature candidate {candidate_id}: coordinate atom outside inventory")
            for pair in change.get("distance_pairs", []):
                require(all(1 <= index <= atom_count for index in pair.get("atoms", [])), f"literature candidate {candidate_id}: distance atom outside inventory")


def validate_candidate(candidate: dict[str, Any], study: dict[str, Any], study_path: Path) -> None:
    validate_common(candidate, "candidate")
    candidate_id = require_id(candidate.get("candidate_id"), "candidate.candidate_id")
    require(candidate.get("study_id") == study.get("study_id"), f"candidate {candidate_id}: study ID mismatch")
    require_hash(candidate.get("study_sha256"), f"candidate {candidate_id}.study_sha256")
    require(candidate["study_sha256"] == sha256(study_path), f"candidate {candidate_id}: study hash mismatch")

    states = {item["state_id"]: item for item in study["catalyst_states"]}
    mechanisms = {item["mechanism_id"]: item for item in study["mechanism_hypotheses"]}
    channels = {item["channel_id"]: item for item in study["channels"]}
    protocols = {item["protocol_id"]: item for item in study["protocol_sets"]}
    groups = {item["comparison_group_id"]: item for item in study["comparison_groups"]}
    group_id = candidate.get("comparison_group_id")
    require(group_id in groups, f"candidate {candidate_id}: unknown comparison group")
    group = groups[group_id]
    require(candidate.get("mechanism_id") == group.get("mechanism_id") and candidate.get("mechanism_id") in mechanisms, f"candidate {candidate_id}: mechanism mismatch")
    require(candidate.get("channel_id") in channels and candidate.get("channel_id") in group.get("channel_ids", []), f"candidate {candidate_id}: channel mismatch")
    require(candidate.get("catalyst_state_id") in states, f"candidate {candidate_id}: unknown catalyst state")
    require(candidate.get("protocol_id") in protocols and candidate.get("protocol_id") == group.get("protocol_id"), f"candidate {candidate_id}: protocol mismatch")

    state = states[candidate["catalyst_state_id"]]
    if state.get("metal_centers"):
        require(candidate.get("support_status") == "unsupported_transition_metal", f"candidate {candidate_id}: metal support refusal bypassed")
        require(candidate.get("review_status") != "promoted_offline", f"candidate {candidate_id}: unsupported metal candidate promoted")
    if candidate.get("support_status") != "supported_main_group_closed_shell":
        require(candidate.get("review_status") != "promoted_offline", f"candidate {candidate_id}: unsupported candidate promoted")
    else:
        require(state.get("support_status") == "supported_main_group_closed_shell", f"candidate {candidate_id}: support status conflicts with catalyst state")

    chemical = candidate.get("chemical_state", {})
    electronic = candidate.get("electronic_state", {})
    require(chemical.get("charge") == electronic.get("charge"), f"candidate {candidate_id}: charge mismatch")
    require(chemical.get("multiplicity") == electronic.get("multiplicity"), f"candidate {candidate_id}: multiplicity mismatch")
    atom_count = candidate.get("atom_inventory", {}).get("atom_count")
    atom_map = candidate.get("atom_map", [])
    require(atom_count == len(atom_map), f"candidate {candidate_id}: atom map length mismatch")
    require([item.get("index") for item in atom_map] == list(range(1, len(atom_map) + 1)), f"candidate {candidate_id}: atom map must be contiguous and one-based")
    for change in candidate.get("coordinate_changes", []):
        require(all(1 <= index <= atom_count for index in change.get("atoms", [])), f"candidate {candidate_id}: coordinate atom outside inventory")
    require(candidate.get("coverage_tags") == candidate.get("candidate_dimensions"), f"candidate {candidate_id}: coverage tags must match candidate dimensions")

    if candidate.get("review_status") == "promoted_offline":
        require(study.get("status") == "reviewed_offline", f"candidate {candidate_id}: study has not passed offline review")
        require(protocols[candidate["protocol_id"]].get("resolution_status") == "reviewed", f"candidate {candidate_id}: protocol unresolved")
        require(candidate.get("review", {}).get("decision") == "promoted_offline", f"candidate {candidate_id}: promotion decision mismatch")
        require(candidate.get("geometry", {}).get("stereochemistry_reviewed") is True, f"candidate {candidate_id}: stereochemistry not reviewed")
        require(candidate.get("geometry", {}).get("clash_reviewed") is True, f"candidate {candidate_id}: clash review missing")
        require(not candidate.get("warnings"), f"candidate {candidate_id}: unresolved warnings block promotion")


def validate_result(result: dict[str, Any], candidate: dict[str, Any], candidate_path: Path) -> None:
    validate_common(result, "result")
    result_id = require_id(result.get("result_id"), "result.result_id")
    require(result.get("candidate_id") == candidate.get("candidate_id"), f"result {result_id}: candidate ID mismatch")
    require(result.get("candidate_sha256") == sha256(candidate_path), f"result {result_id}: candidate hash mismatch")
    for field in ("study_id", "comparison_group_id", "channel_id", "protocol_id"):
        require(result.get(field) == candidate.get(field), f"result {result_id}: {field} mismatch")

    level = result.get("validation_level")
    require(level in VALIDATION_RANK, f"result {result_id}: unknown validation level")
    termination = result.get("termination", {})
    frequency = result.get("frequency_evidence", {})
    mode = result.get("mode_evidence", {})
    path = result.get("path_evidence", {})
    if VALIDATION_RANK[level] >= 1:
        require(termination.get("normal_termination") is True, f"result {result_id}: normal termination required")
        require(termination.get("error_termination") is False, f"result {result_id}: error termination conflicts with validation")
        require(termination.get("stationary_point") is True, f"result {result_id}: stationary point required")
        require(termination.get("frequency_complete") is True, f"result {result_id}: complete frequencies required")
        require(frequency.get("raw_imaginary_frequency_count") == 1, f"result {result_id}: exactly one raw imaginary frequency required")
    if VALIDATION_RANK[level] >= 2:
        require(mode.get("decision") == "accepted", f"result {result_id}: accepted mode required")
        require(mode.get("coordinate_projection_reviewed") is True, f"result {result_id}: coordinate projection review required")
        require(result.get("artifacts", {}).get("mode_review") is not None, f"result {result_id}: mode-review artifact required")
        require(result.get("artifacts", {}).get("mode_decision") is not None, f"result {result_id}: mode-decision artifact required")
    if VALIDATION_RANK[level] >= 3:
        require(path.get("forward") == "completed_and_identified", f"result {result_id}: forward path incomplete")
        require(path.get("reverse") == "completed_and_identified", f"result {result_id}: reverse path incomplete")
        require(path.get("endpoint_identity_reviewed") is True, f"result {result_id}: endpoints not reviewed")
        artifacts = result.get("artifacts", {})
        for artifact_name in ("checkpoint_audit", "irc_plan", "forward_path", "reverse_path"):
            require(artifacts.get(artifact_name) is not None, f"result {result_id}: {artifact_name} artifact required for path validation")

    eligible = result.get("comparison_eligibility", {}).get("eligible")
    if eligible:
        require(VALIDATION_RANK[level] >= 2, f"result {result_id}: unreviewed TS cannot be compared")
        require(result.get("energies", {}).get("comparison_free_energy") is not None, f"result {result_id}: missing comparison energy")


def validate_analysis(
    analysis: dict[str, Any],
    study: dict[str, Any],
    study_path: Path,
    results: dict[str, tuple[dict[str, Any], Path]],
) -> None:
    validate_common(analysis, "analysis")
    analysis_id = require_id(analysis.get("analysis_id"), "analysis.analysis_id")
    require(analysis.get("study_id") == study.get("study_id"), f"analysis {analysis_id}: study ID mismatch")
    require(analysis.get("study_sha256") == sha256(study_path), f"analysis {analysis_id}: study hash mismatch")
    groups = {item["comparison_group_id"]: item for item in study["comparison_groups"]}
    dimensions = {item["dimension_id"]: item for item in study["coverage_dimensions"]}
    group_id = analysis.get("comparison_group_id")
    require(group_id in groups, f"analysis {analysis_id}: unknown group")
    group = groups[group_id]
    require(analysis.get("protocol_id") == group.get("protocol_id"), f"analysis {analysis_id}: protocol mismatch")
    require(analysis.get("required_validation_level") == group.get("required_validation_level"), f"analysis {analysis_id}: validation requirement mismatch")
    require(analysis.get("aggregation", {}).get("model") == group.get("aggregation_model"), f"analysis {analysis_id}: aggregation model mismatch")

    included = analysis.get("included_results", [])
    included_channels: set[str] = set()
    result_energy_records: list[dict[str, Any]] = []
    for reference in included:
        result_id = reference.get("result_id")
        require(result_id in results, f"analysis {analysis_id}: result {result_id} not supplied")
        result, result_path = results[result_id]
        validate_structure(result, "result")
        require(reference.get("result_sha256") == sha256(result_path), f"analysis {analysis_id}: result hash mismatch")
        require(reference.get("candidate_id") == result.get("candidate_id"), f"analysis {analysis_id}: candidate reference mismatch")
        require(reference.get("channel_id") == result.get("channel_id"), f"analysis {analysis_id}: channel reference mismatch")
        require(reference.get("comparison_free_energy") == result.get("energies", {}).get("comparison_free_energy"), f"analysis {analysis_id}: energy reference mismatch")
        require(reference.get("degeneracy") == result.get("energies", {}).get("degeneracy"), f"analysis {analysis_id}: degeneracy mismatch")
        require(result.get("comparison_eligibility", {}).get("eligible") is True, f"analysis {analysis_id}: ineligible result included")
        require(VALIDATION_RANK[result["validation_level"]] >= VALIDATION_RANK[analysis["required_validation_level"]], f"analysis {analysis_id}: result below validation requirement")
        included_channels.add(result["channel_id"])
        result_energy_records.append(result["energies"])
    require(included_channels <= set(group.get("channel_ids", [])), f"analysis {analysis_id}: included channel outside group")

    comparability = analysis.get("comparability", {})
    comparable_flags = [
        comparability.get("common_protocol"),
        comparability.get("common_reference_state"),
        comparability.get("common_inventory_or_balanced_cycle"),
        comparability.get("common_temperature"),
        comparability.get("common_standard_state"),
        comparability.get("common_low_frequency_policy"),
    ]
    if comparability.get("status") == "passed":
        require(all(flag is True for flag in comparable_flags), f"analysis {analysis_id}: comparability flag failed")
        require(not comparability.get("blocking_reasons"), f"analysis {analysis_id}: passed comparison has blocking reasons")
        conditions = analysis.get("conditions", {})
        require(
            all(record.get("temperature_k") == conditions.get("temperature_k") for record in result_energy_records),
            f"analysis {analysis_id}: result temperatures differ",
        )
        require(
            all(record.get("standard_state") == conditions.get("standard_state") for record in result_energy_records),
            f"analysis {analysis_id}: result standard states differ",
        )
        require(
            all(record.get("low_frequency_policy") == conditions.get("low_frequency_policy") for record in result_energy_records),
            f"analysis {analysis_id}: result low-frequency policies differ",
        )
        if not group.get("reference_state", {}).get("balanced_cycle_required"):
            require(
                len({record.get("inventory_key") for record in result_energy_records}) <= 1,
                f"analysis {analysis_id}: inventory mismatch without a checked balanced cycle",
            )

    coverage = analysis.get("coverage", [])
    coverage_ids = {entry.get("dimension_id") for entry in coverage}
    require(len(coverage_ids) == len(coverage), f"analysis {analysis_id}: duplicate coverage dimension")
    require(coverage_ids == set(group.get("coverage_dimension_ids", [])), f"analysis {analysis_id}: coverage dimensions mismatch")
    require(coverage_ids <= set(dimensions), f"analysis {analysis_id}: unknown coverage dimension")

    status = analysis.get("status")
    model = analysis.get("aggregation", {}).get("model")
    if status == "validated":
        require(comparability.get("status") == "passed", f"analysis {analysis_id}: validated claim is incomparable")
        require(included_channels == set(group.get("channel_ids", [])), f"analysis {analysis_id}: validated claim lacks a channel")
        require(all(entry.get("coverage_status") in {"complete", "reviewed_pruned"} for entry in coverage), f"analysis {analysis_id}: validated claim has incomplete coverage")
        require(model != "lowest_ts_only_sensitivity", f"analysis {analysis_id}: lowest-TS sensitivity cannot validate")
        if analysis.get("required_validation_level") == "path_validated":
            require(analysis.get("claim", {}).get("path_validation_complete") is True, f"analysis {analysis_id}: required path validation absent")
    if comparability.get("status") == "failed":
        require(status == "blocked_incomparable", f"analysis {analysis_id}: failed comparability must block analysis")

    fractions = analysis.get("selectivity", {}).get("channel_fractions", {})
    if fractions:
        require(math.isclose(sum(fractions.values()), 1.0, rel_tol=0.0, abs_tol=1e-6), f"analysis {analysis_id}: channel fractions must sum to one")
        require(set(fractions) <= set(group.get("channel_ids", [])), f"analysis {analysis_id}: unknown fraction channel")
    selectivity = analysis.get("selectivity", {})
    major = selectivity.get("major_channel_id")
    minor = selectivity.get("minor_channel_id")
    ddg = selectivity.get("delta_delta_g_kcal_mol")
    if major is not None or minor is not None or ddg is not None:
        require(major in group.get("channel_ids", []) and minor in group.get("channel_ids", []) and major != minor, f"analysis {analysis_id}: invalid major/minor channels")
        require(isinstance(ddg, (int, float)) and ddg >= 0, f"analysis {analysis_id}: delta-delta-G sign convention violated")
        summaries = {item.get("channel_id"): item for item in analysis.get("aggregation", {}).get("channel_summaries", [])}
        require(major in summaries and minor in summaries, f"analysis {analysis_id}: missing major/minor channel summary")
        expected_ddg = summaries[minor].get("effective_barrier") - summaries[major].get("effective_barrier")
        require(math.isclose(ddg, expected_ddg, rel_tol=0.0, abs_tol=1e-6), f"analysis {analysis_id}: delta-delta-G does not match channel barriers")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path, action="append", default=[])
    parser.add_argument("--study", type=Path)
    parser.add_argument("--candidate", type=Path, action="append", default=[])
    parser.add_argument("--result", type=Path, action="append", default=[])
    parser.add_argument("--analysis", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    artifact_kinds: list[str] = []
    standalone_validators = {
        "study": validate_study,
        "space": validate_space,
        "ledger": validate_ledger,
        "energy-record": validate_energy_record,
        "materializations": validate_materializations,
        "metal-support": validate_metal_support,
        "metal-ts-audit-template": validate_metal_ts_audit_template,
        "metal-scientific-review-source": validate_metal_scientific_review_source,
        "metal-scientific-review": validate_metal_scientific_review,
        "metal-input-observation": validate_metal_input_observation,
        "metal-result-observation": validate_metal_result_observation,
        "metal-acceptance-review-source": validate_metal_acceptance_review_source,
        "metal-acceptance-review": validate_metal_acceptance_review,
        "smoke-proposal": validate_smoke_proposal,
        "live-smoke-evidence": validate_live_smoke_evidence,
        "literature-benchmark": validate_literature_benchmark,
    }
    for path in args.artifact:
        artifact_data = load_json(path)
        kind = validate_structure(artifact_data)
        validator = standalone_validators.get(kind)
        if validator is not None:
            validator(artifact_data)
        artifact_kinds.append(kind)

    require(args.study is not None or artifact_kinds, "supply --study and/or at least one --artifact")
    require(args.study is not None or not (args.candidate or args.result or args.analysis), "candidate/result/analysis validation requires --study")
    study = load_json(args.study) if args.study is not None else None
    if study is not None:
        validate_study(study)

    candidates: dict[str, tuple[dict[str, Any], Path]] = {}
    for path in args.candidate:
        candidate = load_json(path)
        validate_candidate(candidate, study, args.study)  # type: ignore[arg-type]
        candidate_id = candidate["candidate_id"]
        require(candidate_id not in candidates, f"duplicate candidate input {candidate_id}")
        candidates[candidate_id] = (candidate, path)

    results: dict[str, tuple[dict[str, Any], Path]] = {}
    for path in args.result:
        result = load_json(path)
        candidate_id = result.get("candidate_id")
        require(candidate_id in candidates, f"result {path}: matching candidate was not supplied")
        candidate, candidate_path = candidates[candidate_id]
        validate_result(result, candidate, candidate_path)
        result_id = result["result_id"]
        require(result_id not in results, f"duplicate result input {result_id}")
        results[result_id] = (result, path)

    if args.analysis:
        validate_analysis(load_json(args.analysis), study, args.study, results)  # type: ignore[arg-type]

    print(
        json.dumps(
            {
                "valid": True,
                "study_id": study["study_id"] if study is not None else None,
                "candidate_count": len(candidates),
                "result_count": len(results),
                "analysis_checked": args.analysis is not None,
                "artifact_count": len(artifact_kinds),
                "artifact_kinds": artifact_kinds,
                "live_actions": False,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
