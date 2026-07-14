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
VALIDATION_RANK = {
    "failed": 0,
    "first_order_saddle_candidate": 1,
    "mode_reviewed": 2,
    "path_validated": 3,
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
    states = unique_index(design.get("states", []), "state_id", "metal-support.states")
    if study is None:
        return
    require(study_path is not None, "metal-support: study_path is required when a study is supplied")
    validate_study(study)
    require(design.get("study_id") == study.get("study_id"), "metal-support: study ID mismatch")
    require(design.get("study_sha256") == sha256(study_path), "metal-support: study hash mismatch")
    metal_states = {item["state_id"] for item in study.get("catalyst_states", []) if item.get("metal_centers")}
    require(set(states) == metal_states, "metal-support: reviewed metal states mismatch")


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
