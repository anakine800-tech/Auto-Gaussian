#!/usr/bin/env python3
"""Build and validate immutable offline TS-precedent review maps.

This tool translates only human-reviewed mechanism edges and literature
precedents.  It never creates coordinates, chooses a method, renders Gaussian
input, or performs a live action.
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import math
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import mechanism_network as mn
import reaction_workflow as rw


REVIEW_SCHEMA = "gaussian-ts-precedent-map-review/1"
OUTPUT_SCHEMA = "gaussian-ts-precedent-map/1"
LITERATURE_SCHEMA = "gaussian-reaction-literature-evidence/1"
KNOWLEDGE_SCHEMA = "auto-g16-knowledge-snapshot/1"
SUPPORT_SCHEMA = "gaussian-reaction-mechanism-support/1"

REVIEW_KEYS = {
    "schema", "study_id", "mechanism_network_payload_sha256",
    "knowledge_snapshot_payload_sha256", "literature_evidence_payload_sha256",
    "records", "review_decision", "review_notes",
}
RECORD_KEYS = {
    "precedent_id", "target", "source_precedent", "source_structure",
    "source_to_target_atom_mapping", "target_context", "geometry_transfer",
    "seed_strategy", "strategy_prerequisites", "applicability_review",
    "uncertainties", "alternatives", "negative_evidence", "disposition",
    "blockers", "notes",
}
DIMENSIONS = {
    "net_transformation", "elementary_step_and_atom_correspondence",
    "substrate_electronics_sterics_and_groups", "catalyst_and_active_state",
    "atom_inventory_charge_multiplicity_and_spin",
    "coordination_ion_pair_additives_and_solvent", "stereochemical_channel",
    "experimental_conditions", "computational_protocol_and_validation",
}
APPLICABILITY = {"exact", "close", "remote", "contradictory", "unknown", "not_applicable"}
STRATEGIES = {
    "published_coordinates", "reviewed_structure_rebuild", "endpoint_qst_family",
    "relaxed_scan", "hessian_guided_guess", "unsupported",
}
AUDIT_FIELDS = {
    "identity", "atom_order", "stereochemistry", "formal_charge",
    "multiplicity", "coordination",
}
AUDIT_STATUSES = {"reviewed", "not_available", "blocked"}
GEOMETRY_KINDS = {
    "distance", "angle", "dihedral", "coordination_contact", "topology",
    "facial_relationship", "orientation", "conformer_family",
}
QUANTITATIVE_GEOMETRY_KINDS = {"distance", "angle", "dihedral", "coordination_contact"}
QUALITATIVE_GEOMETRY_KINDS = GEOMETRY_KINDS - QUANTITATIVE_GEOMETRY_KINDS


def _load_sibling_module(name: str, relative: str) -> Any:
    path = Path(__file__).resolve().parents[2] / relative
    spec = importlib.util.spec_from_file_location(name, path)
    rw.require(spec is not None and spec.loader is not None, f"cannot load required validator: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


KB = _load_sibling_module("auto_g16_knowledge_base_validator", "auto-g16-knowledge-base/scripts/knowledge_base.py")
LIT = _load_sibling_module("auto_g16_reaction_literature_validator", "auto-g16-reaction-literature/scripts/literature_search.py")


def _exact(value: Any, keys: set[str], label: str) -> dict[str, Any]:
    rw.require(isinstance(value, dict), f"{label} must be an object")
    rw._require_exact_keys(value, keys, keys, label)
    return value


def _id_list(value: Any, label: str, *, nonempty: bool = False) -> list[str]:
    result = rw._string_list(value, label, nonempty=nonempty)
    for item in result:
        rw._require_id(item, label)
    rw.require(len(result) == len(set(result)), f"{label} must not contain duplicates")
    return result


def _finite(value: Any, label: str) -> float:
    rw.require(isinstance(value, (int, float)) and not isinstance(value, bool), f"{label} must be numeric")
    rw.require(math.isfinite(float(value)), f"{label} must be finite")
    return float(value)


def _resolve(reference: dict[str, Any], owner: Path) -> Path:
    path = Path(reference["path"])
    return path if path.is_absolute() else owner.parent / path


def _require_regular_file(path: Path, label: str) -> None:
    rw.require(path.is_file() and not path.is_symlink(), f"{label} is missing or a symlink")


def _write_json_exclusive(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(rw.canonical_bytes(data))
    except FileExistsError:
        raise rw.OfflineError(f"refusing to overwrite existing artifact: {path}") from None


def _verify_file_ref(value: Any, owner: Path, label: str) -> dict[str, Any]:
    ref = _exact(value, {"path", "sha256", "size_bytes"}, label)
    path = _resolve(ref, owner)
    rw.require(path.is_file() and not path.is_symlink(), f"{label} is missing or a symlink")
    rw.require(ref["sha256"] == rw.sha256_file(path), f"{label} file hash mismatch")
    rw.require(ref["size_bytes"] == path.stat().st_size, f"{label} size mismatch")
    return {"path": str(path), "sha256": ref["sha256"], "size_bytes": ref["size_bytes"]}


def _input_ref(path: Path, payload_sha256: str) -> dict[str, Any]:
    ref = rw._artifact_ref(path)
    return {**ref, "payload_sha256": payload_sha256}


def _verify_generic_input_ref(value: Any, owner: Path, schema: str, payload_key: str, label: str) -> dict[str, Any]:
    ref = _exact(value, {"path", "sha256", "size_bytes", "payload_sha256"}, label)
    path = _resolve(ref, owner)
    rw.require(path.is_file() and not path.is_symlink(), f"{label} is missing or a symlink")
    rw.require(ref["sha256"] == rw.sha256_file(path) and ref["size_bytes"] == path.stat().st_size, f"{label} file binding mismatch")
    data = rw.load_json(path)
    rw.require(data.get("schema") == schema, f"{label} schema mismatch")
    rw.require(data.get(payload_key) == ref["payload_sha256"], f"{label} payload binding mismatch")
    return data


def _artifact_binding_path(binding: Any, owner: Path, label: str) -> tuple[Path, dict[str, Any]]:
    item = _exact(binding, {"path", "sha256", "schema", "payload_sha256"}, label)
    path = _resolve(item, owner)
    rw.require(path.is_file() and not path.is_symlink(), f"{label} is missing or a symlink")
    rw.require(item["sha256"] == rw.sha256_file(path), f"{label} file hash mismatch")
    data = rw.load_json(path)
    rw.require(data.get("schema") == item["schema"], f"{label} schema mismatch")
    payload = data.get("payload_sha256")
    if item["schema"] == LITERATURE_SCHEMA:
        payload = data.get("evidence_review_payload_sha256")
    rw.require(payload == item["payload_sha256"], f"{label} payload hash mismatch")
    return path, data


def _load_upstream(mechanism_path: Path, snapshot_path: Path, evidence_path: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, tuple[Path, dict[str, Any]]]]:
    for path, label in (
        (mechanism_path, "mechanism-network input"),
        (snapshot_path, "knowledge-snapshot input"),
        (evidence_path, "literature-evidence input"),
    ):
        _require_regular_file(path, label)
    mn.validate(mechanism_path)
    mechanism = rw.load_json(mechanism_path)

    snapshot = KB.load_json(snapshot_path)
    KB.validate_record(snapshot)
    rw.require(snapshot["schema"] == KNOWLEDGE_SCHEMA, "knowledge artifact must be a reviewed snapshot")

    evidence = LIT.load_json(evidence_path)
    rw.require(evidence.get("schema") == LITERATURE_SCHEMA, "literature evidence schema mismatch")
    rw.require(evidence.get("record_status") == "validated_review_record", "literature evidence must be finalized")
    LIT.verify_payload_hash(evidence, "evidence_review_payload_sha256")
    with contextlib.redirect_stdout(io.StringIO()):
        LIT.command_validate_review(SimpleNamespace(review=str(evidence_path), output=None))

    network_bindings: dict[str, tuple[Path, dict[str, Any]]] = {}
    for key, schema in (
        ("reaction_intake", rw.INTAKE_SCHEMA),
        ("species_registry", rw.REGISTRY_SCHEMA),
        ("condition_model", rw.CONDITION_SCHEMA),
    ):
        network_key = {"reaction_intake": "intake", "species_registry": "species_registry", "condition_model": "condition_model"}[key]
        ref = mechanism[network_key]
        path = _resolve(ref, mechanism_path)
        data = rw._verify_bound_artifact(ref, mechanism_path, schema, f"mechanism {key}")
        network_bindings[key] = (path, data)

    intake_path, intake = network_bindings["reaction_intake"]
    parent = snapshot["parent_reaction_intake"]
    parent_path = _resolve(parent, snapshot_path)
    rw.require(parent_path.is_file() and not parent_path.is_symlink(), "knowledge snapshot parent intake is missing or a symlink")
    rw.require(parent_path.resolve() == intake_path.resolve(), "knowledge snapshot parent intake path differs from mechanism network")
    rw.require(parent["sha256"] == rw.sha256_file(intake_path), "knowledge snapshot parent intake file hash mismatch")
    rw.require(parent["payload_sha256"] == intake["payload_sha256"], "knowledge snapshot parent intake payload mismatch")
    rw.require(snapshot["study_id"] == mechanism["study_id"], "knowledge snapshot study_id differs from mechanism network")

    upstream = evidence.get("upstream_artifacts")
    rw.require(isinstance(upstream, dict) and set(upstream) == {"reaction_intake", "species_registry", "condition_model", "knowledge_snapshot"}, "literature evidence requires exact W1 and knowledge-snapshot bindings")
    for key in ("reaction_intake", "species_registry", "condition_model"):
        path, data = _artifact_binding_path(upstream[key], evidence_path, f"literature {key}")
        expected_path, expected = network_bindings[key]
        rw.require(path.resolve() == expected_path.resolve(), f"literature {key} path differs from mechanism network")
        rw.require(data.get("payload_sha256") == expected["payload_sha256"], f"literature {key} payload differs from mechanism network")
    knowledge_bound_path, knowledge_bound = _artifact_binding_path(upstream["knowledge_snapshot"], evidence_path, "literature knowledge_snapshot")
    rw.require(knowledge_bound_path.resolve() == snapshot_path.resolve(), "literature knowledge-snapshot path differs from supplied snapshot")
    rw.require(knowledge_bound["payload_sha256"] == snapshot["payload_sha256"], "literature knowledge-snapshot payload differs from supplied snapshot")
    return mechanism, snapshot, evidence, network_bindings


def _pair_list(value: Any, label: str, valid_atoms: set[str]) -> list[list[str]]:
    rw.require(isinstance(value, list), f"{label} must be an array")
    result: list[list[str]] = []
    for index, raw in enumerate(value):
        pair = _id_list(raw, f"{label}[{index}]", nonempty=True)
        rw.require(len(pair) == 2 and set(pair) <= valid_atoms, f"{label}[{index}] must reference two target atoms")
        result.append(sorted(pair))
    result.sort()
    rw.require(len(result) == len({tuple(item) for item in result}), f"{label} contains duplicates")
    return result


def _normalize_target(raw: Any, edge: dict[str, Any], states: dict[str, dict[str, Any]], label: str) -> dict[str, Any]:
    keys = {
        "edge_id", "from_state_id", "to_state_id", "stereochemical_channel",
        "eligibility", "eligibility_reviewed", "stereochemical_channel_reviewed",
        "forming_pairs", "breaking_pairs", "transfers",
    }
    data = _exact(raw, keys, label)
    rw.require(data["edge_id"] == edge["edge_id"], f"{label}.edge_id mismatch")
    rw.require(data["from_state_id"] == edge["from_state_id"] and data["to_state_id"] == edge["to_state_id"], f"{label} state IDs differ from mechanism edge")
    rw.require(data["stereochemical_channel"] == edge["stereochemical_channel"], f"{label} stereochemical channel differs from mechanism edge")
    rw.require(data["eligibility"] in {"eligible", "ineligible", "blocked"}, f"{label}.eligibility is invalid")
    rw.require(data["eligibility_reviewed"] is True and data["stereochemical_channel_reviewed"] is True, f"{label} requires explicit eligibility and stereochemical-channel review")
    source_atoms = {item["atom_id"] for item in states[edge["from_state_id"]]["atoms"]}
    forming = _pair_list(data["forming_pairs"], f"{label}.forming_pairs", source_atoms)
    breaking = _pair_list(data["breaking_pairs"], f"{label}.breaking_pairs", source_atoms)
    expected_forming = sorted(item["atom_ids"] for item in edge["connection_changes"] if item["before_order"] is None and item["after_order"] is not None)
    expected_breaking = sorted(item["atom_ids"] for item in edge["connection_changes"] if item["before_order"] is not None and item["after_order"] is None)
    rw.require(forming == expected_forming and breaking == expected_breaking, f"{label} forming/breaking pairs differ from the reviewed mechanism edge")
    transfers: list[dict[str, str]] = []
    rw.require(isinstance(data["transfers"], list), f"{label}.transfers must be an array")
    for index, raw_transfer in enumerate(data["transfers"]):
        transfer = _exact(raw_transfer, {"atom_id", "donor_atom_id", "acceptor_atom_id"}, f"{label}.transfers[{index}]")
        normalized = {key: rw._require_id(transfer[key], f"{label}.transfers[{index}].{key}") for key in transfer}
        rw.require(set(normalized.values()) <= source_atoms, f"{label}.transfers[{index}] references an unknown target atom")
        transfers.append(normalized)
    transfers.sort(key=lambda item: (item["atom_id"], item["donor_atom_id"], item["acceptor_atom_id"]))
    rw.require(transfers == edge["transfers"], f"{label}.transfers differ from the reviewed mechanism edge")
    return {
        "edge_id": edge["edge_id"], "from_state_id": edge["from_state_id"],
        "to_state_id": edge["to_state_id"], "stereochemical_channel": edge["stereochemical_channel"],
        "eligibility": data["eligibility"], "eligibility_reviewed": True,
        "stereochemical_channel_reviewed": True, "forming_pairs": forming,
        "breaking_pairs": breaking, "transfers": transfers,
        "edge_atom_mapping": edge["atom_mapping"],
    }


def _evidence_reviews(evidence: dict[str, Any]) -> dict[str, dict[str, Any]]:
    reviews = evidence.get("reviews")
    rw.require(isinstance(reviews, list), "literature evidence reviews must be an array")
    result: dict[str, dict[str, Any]] = {}
    for item in reviews:
        rw.require(isinstance(item, dict) and isinstance(item.get("candidate_id"), str), "literature evidence contains an invalid candidate review")
        rw.require(item["candidate_id"] not in result, "literature evidence contains duplicate candidate IDs")
        result[item["candidate_id"]] = item
    return result


def _normalize_source_precedent(raw: Any, candidate: dict[str, Any], label: str) -> dict[str, Any]:
    data = _exact(raw, {"candidate_id", "evidence_target", "source_location", "applicability_dimensions", "bounded_use", "relationship"}, label)
    rw.require(data["candidate_id"] == candidate["candidate_id"], f"{label}.candidate_id mismatch")
    target = rw._require_string(data["evidence_target"], f"{label}.evidence_target")
    claim = candidate.get("evidence", {}).get(target)
    rw.require(isinstance(claim, dict) and claim.get("status") == "source_reports", f"{label} requires source-located finalized evidence")
    location = _exact(data["source_location"], {"source_type", "locator", "url_or_doi", "checked_at"}, f"{label}.source_location")
    rw.require(location in claim.get("source_locations", []), f"{label}.source_location is absent from finalized evidence")
    decision = candidate.get("reviewer_decision", {})
    rw.require(data["bounded_use"] == decision.get("bounded_use"), f"{label}.bounded_use differs from finalized evidence")
    relationship = rw._require_string(data["relationship"], f"{label}.relationship")
    rw.require(relationship in {"exact", "close", "remote", "unusable"}, f"{label}.relationship is invalid")
    dimensions_raw = data["applicability_dimensions"]
    rw.require(isinstance(dimensions_raw, list) and len(dimensions_raw) == len(DIMENSIONS), f"{label} requires all applicability dimensions")
    dimensions: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, item in enumerate(dimensions_raw):
        row = _exact(item, {"dimension", "value", "rationale", "source_anchor"}, f"{label}.applicability_dimensions[{index}]")
        dimension = rw._require_string(row["dimension"], f"{label} dimension")
        rw.require(dimension in DIMENSIONS and dimension not in seen, f"{label} contains an invalid or duplicate dimension")
        seen.add(dimension)
        value = rw._require_string(row["value"], f"{label} dimension value")
        rw.require(value in APPLICABILITY and candidate["directness_dimensions"].get(dimension) == value, f"{label} dimension differs from finalized evidence")
        dimensions.append({
            "dimension": dimension, "value": value,
            "rationale": rw._require_string(row["rationale"], f"{label} dimension rationale"),
            "source_anchor": rw._require_string(row["source_anchor"], f"{label} dimension source_anchor"),
        })
    values = {item["value"] for item in dimensions}
    if relationship == "exact":
        rw.require(values <= {"exact", "not_applicable"} and decision.get("status") == "source_reports_direct_precedent", f"{label} exact relationship is not supported by the evidence decision")
    elif relationship == "close":
        rw.require("close" in values and values <= {"exact", "close", "not_applicable"}, f"{label} close relationship is inconsistent")
    elif relationship == "remote":
        rw.require(bool(values & {"remote", "unknown"}), f"{label} remote relationship requires an explicit remote/unknown dimension")
    else:
        rw.require(bool(values & {"contradictory", "unknown", "remote"}) or decision.get("status") == "exclude", f"{label} unusable relationship requires negative evidence")
    return {
        "candidate_id": data["candidate_id"], "evidence_target": target,
        "source_location": dict(location),
        "applicability_dimensions": sorted(dimensions, key=lambda item: item["dimension"]),
        "bounded_use": data["bounded_use"], "relationship": relationship,
    }


def _normalize_source_structure(
    raw: Any,
    source: dict[str, Any],
    review_path: Path,
    label: str,
) -> dict[str, Any]:
    data = _exact(raw, {"atom_order_review_status", "source_atoms", "audits", "coordinate_provenance"}, label)
    order_status = rw._require_string(data["atom_order_review_status"], f"{label}.atom_order_review_status")
    rw.require(order_status in AUDIT_STATUSES, f"{label}.atom_order_review_status is invalid")
    atoms_raw = data["source_atoms"]
    rw.require(isinstance(atoms_raw, list), f"{label}.source_atoms must be an array")
    atoms: list[dict[str, Any]] = []
    ids: set[str] = set()
    indices: set[int] = set()
    for index, raw_atom in enumerate(atoms_raw):
        atom = _exact(raw_atom, {"source_atom_id", "order_index", "element"}, f"{label}.source_atoms[{index}]")
        atom_id = rw._require_id(atom["source_atom_id"], f"{label}.source_atom_id")
        order_index = atom["order_index"]
        rw.require(isinstance(order_index, int) and not isinstance(order_index, bool) and order_index > 0, f"{label}.order_index must be positive integer")
        rw.require(atom_id not in ids and order_index not in indices, f"{label}.source_atoms IDs/order must be unique")
        ids.add(atom_id); indices.add(order_index)
        element = atom["element"]
        rw.require(element is None or (isinstance(element, str) and rw.ELEMENT_RE.fullmatch(element)), f"{label}.source atom element is invalid")
        atoms.append({"source_atom_id": atom_id, "order_index": order_index, "element": element})
    if atoms:
        rw.require(indices == set(range(1, len(atoms) + 1)), f"{label}.source atom ordering must be contiguous")
    audits = _exact(data["audits"], AUDIT_FIELDS, f"{label}.audits")
    for key, value in audits.items():
        rw.require(value in AUDIT_STATUSES, f"{label}.audits.{key} is invalid")
    provenance = _exact(
        data["coordinate_provenance"],
        {
            "status", "evidence_candidate_id", "evidence_source_location",
            "source_object", "coordinate_block_anchor", "coordinates_copied",
        },
        f"{label}.coordinate_provenance",
    )
    status = rw._require_string(provenance["status"], f"{label}.coordinate_provenance.status")
    rw.require(status in {"published_coordinates", "figure_or_topology", "not_available"}, f"{label}.coordinate_provenance.status is invalid")
    rw.require(provenance["coordinates_copied"] is False, f"{label} must not copy or fabricate coordinates")
    evidence_candidate_id = provenance["evidence_candidate_id"]
    evidence_source_location = provenance["evidence_source_location"]
    source_object = None
    anchor = provenance["coordinate_block_anchor"]
    if status == "not_available":
        rw.require(
            evidence_candidate_id is None and evidence_source_location is None,
            f"{label} unavailable coordinate provenance must not claim source evidence",
        )
        rw.require(provenance["source_object"] is None and anchor is None, f"{label} non-coordinate evidence must not claim a coordinate object/anchor")
    else:
        rw.require(
            evidence_candidate_id == source["candidate_id"]
            and evidence_source_location == source["source_location"],
            f"{label} coordinate provenance must refer to the same source evidence as source_precedent",
        )
        if status == "published_coordinates":
            source_object = _verify_file_ref(provenance["source_object"], review_path, f"{label}.coordinate source object")
            anchor = rw._require_string(anchor, f"{label}.coordinate_block_anchor")
        else:
            rw.require(provenance["source_object"] is None and anchor is None, f"{label} non-coordinate evidence must not claim a coordinate object/anchor")
    return {
        "atom_order_review_status": order_status,
        "source_atoms": sorted(atoms, key=lambda item: item["order_index"]),
        "audits": {key: audits[key] for key in sorted(audits)},
        "coordinate_provenance": {
            "status": status,
            "evidence_candidate_id": evidence_candidate_id,
            "evidence_source_location": None if evidence_source_location is None else dict(evidence_source_location),
            "source_object": source_object,
            "coordinate_block_anchor": anchor,
            "coordinates_copied": False,
        },
    }


def _normalize_mapping(raw: Any, source_structure: dict[str, Any], edge: dict[str, Any], states: dict[str, dict[str, Any]], label: str) -> list[dict[str, str]]:
    rw.require(isinstance(raw, list), f"{label} must be an array")
    source_atoms = {item["source_atom_id"]: item for item in source_structure["source_atoms"]}
    from_elements = {item["atom_id"]: item["element"] for item in states[edge["from_state_id"]]["atoms"]}
    edge_map = {item["from_atom_id"]: item["to_atom_id"] for item in edge["atom_mapping"]}
    seen_source: set[str] = set(); seen_from: set[str] = set(); seen_to: set[str] = set()
    result: list[dict[str, str]] = []
    for index, item in enumerate(raw):
        row = _exact(item, {"source_atom_id", "from_atom_id", "to_atom_id"}, f"{label}[{index}]")
        source_id = rw._require_id(row["source_atom_id"], f"{label}.source_atom_id")
        from_id = rw._require_id(row["from_atom_id"], f"{label}.from_atom_id")
        to_id = rw._require_id(row["to_atom_id"], f"{label}.to_atom_id")
        rw.require(source_id in source_atoms and from_id in edge_map and edge_map[from_id] == to_id, f"{label}[{index}] is not consistent with the reviewed edge atom map")
        rw.require(source_id not in seen_source and from_id not in seen_from and to_id not in seen_to, f"{label} must be one-to-one")
        known_element = source_atoms[source_id]["element"]
        rw.require(known_element is None or known_element == from_elements[from_id], f"{label}[{index}] changes a known source element")
        seen_source.add(source_id); seen_from.add(from_id); seen_to.add(to_id)
        result.append({"source_atom_id": source_id, "from_atom_id": from_id, "to_atom_id": to_id})
    return sorted(result, key=lambda item: item["source_atom_id"])


def _normalize_context(
    raw: Any,
    target: dict[str, Any],
    states: dict[str, dict[str, Any]],
    label: str,
) -> dict[str, Any]:
    keys = {"catalyst_state", "coordination", "ion_pair_additive_placement", "formal_charge", "multiplicity", "approach_topology", "facial_orientational_relationship", "conformer_family", "review_status", "rationale"}
    data = _exact(raw, keys, label)
    for key in keys - {"formal_charge", "multiplicity"}:
        rw._require_string(data[key], f"{label}.{key}")
    rw.require(isinstance(data["formal_charge"], int) and not isinstance(data["formal_charge"], bool), f"{label}.formal_charge must be integer")
    rw.require(isinstance(data["multiplicity"], int) and not isinstance(data["multiplicity"], bool) and data["multiplicity"] > 0, f"{label}.multiplicity must be positive integer")
    rw.require(data["review_status"] in {"reviewed", "blocked"}, f"{label}.review_status is invalid")
    for state_id in (target["from_state_id"], target["to_state_id"]):
        state = states[state_id]
        rw.require(data["formal_charge"] == state["formal_charge"], f"{label}.formal_charge differs from endpoint state {state_id}")
        rw.require(data["multiplicity"] == state["multiplicity"], f"{label}.multiplicity differs from endpoint state {state_id}")
    return dict(data)


def _normalize_geometry(
    raw: Any,
    target: dict[str, Any],
    states: dict[str, dict[str, Any]],
    source: dict[str, Any],
    source_structure: dict[str, Any],
    mapping: list[dict[str, str]],
    label: str,
) -> list[dict[str, Any]]:
    rw.require(isinstance(raw, list), f"{label} must be an array")
    result: list[dict[str, Any]] = []
    ids: set[str] = set()
    allowed_states = {target["from_state_id"], target["to_state_id"]}
    state_atoms = {state_id: {item["atom_id"] for item in states[state_id]["atoms"]} for state_id in allowed_states}
    mapped_target_atoms = {
        (target["from_state_id"], item["from_atom_id"])
        for item in mapping
    } | {
        (target["to_state_id"], item["to_atom_id"])
        for item in mapping
    }
    for index, raw_item in enumerate(raw):
        keys = {"geometry_item_id", "kind", "transfer_status", "descriptor", "value", "range", "unit", "atom_refs", "provenance", "applicability", "limitations"}
        item = _exact(raw_item, keys, f"{label}[{index}]")
        item_id = rw._require_id(item["geometry_item_id"], f"{label}.geometry_item_id")
        rw.require(item_id not in ids, f"{label} contains duplicate geometry_item_id")
        ids.add(item_id)
        kind = rw._require_string(item["kind"], f"{label}.{item_id}.kind")
        rw.require(kind in GEOMETRY_KINDS, f"{label}.{item_id}.kind is invalid")
        transfer_status = rw._require_string(item["transfer_status"], f"{label}.{item_id}.transfer_status")
        rw.require(transfer_status in {"transferable", "rebuild_required"}, f"{label}.{item_id}.transfer_status is invalid")
        atom_refs: list[dict[str, str]] = []
        rw.require(isinstance(item["atom_refs"], list), f"{label}.{item_id}.atom_refs must be an array")
        for ref_index, raw_ref in enumerate(item["atom_refs"]):
            ref = _exact(raw_ref, {"state_id", "atom_id"}, f"{label}.{item_id}.atom_refs[{ref_index}]")
            rw.require(ref["state_id"] in allowed_states and ref["atom_id"] in state_atoms[ref["state_id"]], f"{label}.{item_id} references an unknown target atom")
            atom_refs.append(dict(ref))
        rw.require(len(atom_refs) == len({(ref["state_id"], ref["atom_id"]) for ref in atom_refs}), f"{label}.{item_id}.atom_refs contains duplicates")
        required_count = {"distance": 2, "coordination_contact": 2, "angle": 3, "dihedral": 4}.get(kind)
        if required_count is not None:
            rw.require(len(atom_refs) == required_count, f"{label}.{item_id} requires {required_count} atom references")
        else:
            rw.require(bool(atom_refs), f"{label}.{item_id} requires target atom references")
        unit = rw._require_string(item["unit"], f"{label}.{item_id}.unit")
        expected_unit = (
            "not_applicable"
            if transfer_status == "rebuild_required"
            else "angstrom"
            if kind in {"distance", "coordination_contact"}
            else "degree"
            if kind in {"angle", "dihedral"}
            else "not_applicable"
        )
        rw.require(unit == expected_unit, f"{label}.{item_id}.unit must be {expected_unit}")
        descriptor = item["descriptor"]
        rw.require(descriptor is None or (isinstance(descriptor, str) and descriptor.strip()), f"{label}.{item_id}.descriptor must be null or a non-empty string")
        value = item["value"]
        range_value = item["range"]
        if transfer_status == "rebuild_required":
            rw.require(descriptor is None and value is None and range_value is None, f"{label}.{item_id} rebuild-required item cannot carry transferable geometry")
        elif kind in QUANTITATIVE_GEOMETRY_KINDS:
            rw.require(descriptor is None, f"{label}.{item_id} quantitative geometry must not carry a qualitative descriptor")
            rw.require((value is None) != (range_value is None), f"{label}.{item_id} transferable item requires exactly one value or range")
            if value is not None:
                value = _finite(value, f"{label}.{item_id}.value")
            if range_value is not None:
                range_data = _exact(range_value, {"minimum", "maximum"}, f"{label}.{item_id}.range")
                minimum = _finite(range_data["minimum"], f"{label}.{item_id}.range.minimum")
                maximum = _finite(range_data["maximum"], f"{label}.{item_id}.range.maximum")
                rw.require(minimum < maximum, f"{label}.{item_id}.range must be bounded and increasing")
                range_value = {"minimum": minimum, "maximum": maximum}
        else:
            rw.require(value is None and range_value is None, f"{label}.{item_id} qualitative geometry cannot carry a numeric value/range")
            rw.require(
                isinstance(descriptor, str) and bool(descriptor.strip()),
                f"{label}.{item_id}.descriptor must be a non-empty string",
            )
        provenance = _exact(item["provenance"], {"candidate_id", "source_location", "evidence_form"}, f"{label}.{item_id}.provenance")
        rw.require(provenance["candidate_id"] == source["candidate_id"] and provenance["source_location"] == source["source_location"], f"{label}.{item_id} provenance differs from its source precedent")
        evidence_form = rw._require_string(provenance["evidence_form"], f"{label}.{item_id}.evidence_form")
        rw.require(evidence_form in {"published_coordinates", "reported_value", "figure_or_topology", "reviewer_assessment"}, f"{label}.{item_id}.evidence_form is invalid")
        limitations = rw._string_list(item["limitations"], f"{label}.{item_id}.limitations", nonempty=True)
        if transfer_status == "transferable":
            rw.require(
                all((ref["state_id"], ref["atom_id"]) in mapped_target_atoms for ref in atom_refs),
                f"{label}.{item_id}: transferable geometry references a target atom without source correspondence",
            )
            rw.require(evidence_form != "reviewer_assessment", f"{label}.{item_id}: reviewer assessment alone cannot authorize geometry transfer")
        if evidence_form == "published_coordinates":
            rw.require(source["evidence_target"] == "coordinates" and source_structure["coordinate_provenance"]["status"] == "published_coordinates", f"{label}.{item_id}: published-coordinate geometry requires matching published source coordinates")
            rw.require(
                source_structure["atom_order_review_status"] == "reviewed"
                and all(value == "reviewed" for value in source_structure["audits"].values()),
                f"{label}.{item_id}: published-coordinate geometry requires completed identity/order/stereochemistry/charge/multiplicity/coordination audits",
            )
        if evidence_form == "figure_or_topology" and transfer_status == "transferable" and kind in QUANTITATIVE_GEOMETRY_KINDS:
            rw.require(value is None and range_value is not None, f"{label}.{item_id}: approximate figure/topology quantitative evidence permits only a bounded range")
        if range_value is not None:
            rw.require(evidence_form == "figure_or_topology", f"{label}.{item_id}: bounded ranges are reserved for approximate figure/topology evidence")
        applicability = rw._require_string(item["applicability"], f"{label}.{item_id}.applicability")
        rw.require(applicability in APPLICABILITY, f"{label}.{item_id}.applicability is invalid")
        result.append({
            "geometry_item_id": item_id, "kind": kind, "transfer_status": transfer_status,
            "descriptor": descriptor, "value": value, "range": range_value, "unit": unit,
            "atom_refs": sorted(atom_refs, key=lambda ref: (ref["state_id"], ref["atom_id"])),
            "provenance": {"candidate_id": provenance["candidate_id"], "source_location": dict(provenance["source_location"]), "evidence_form": evidence_form},
            "applicability": applicability, "limitations": limitations,
        })
    return sorted(result, key=lambda item: item["geometry_item_id"])


def _normalize_prerequisites(raw: Any, review_path: Path, label: str) -> dict[str, Any]:
    keys = {"status", "endpoint_state_ids", "geometry_item_ids", "source_object", "source_anchor", "reviewed_assertions", "notes"}
    data = _exact(raw, keys, label)
    status = rw._require_string(data["status"], f"{label}.status")
    rw.require(status in {"complete", "incomplete", "not_applicable"}, f"{label}.status is invalid")
    source_object = None if data["source_object"] is None else _verify_file_ref(data["source_object"], review_path, f"{label}.source_object")
    source_anchor = data["source_anchor"]
    rw.require(source_anchor is None or (isinstance(source_anchor, str) and source_anchor.strip()), f"{label}.source_anchor must be null or non-empty string")
    rw.require((source_object is None) == (source_anchor is None), f"{label}.source_object and source_anchor must be supplied together")
    return {
        "status": status,
        "endpoint_state_ids": sorted(_id_list(data["endpoint_state_ids"], f"{label}.endpoint_state_ids")),
        "geometry_item_ids": sorted(_id_list(data["geometry_item_ids"], f"{label}.geometry_item_ids")),
        "source_object": source_object, "source_anchor": source_anchor,
        "reviewed_assertions": sorted(set(rw._string_list(data["reviewed_assertions"], f"{label}.reviewed_assertions"))),
        "notes": rw._string_list(data["notes"], f"{label}.notes"),
    }


def _strategy_complete(strategy: str, prerequisites: dict[str, Any], source_structure: dict[str, Any], mapping: list[dict[str, str]], target: dict[str, Any], geometry: list[dict[str, Any]], states: dict[str, dict[str, Any]]) -> bool:
    if prerequisites["status"] != "complete" or strategy == "unsupported":
        return False
    geometry_ids = {item["geometry_item_id"] for item in geometry}
    if not set(prerequisites["geometry_item_ids"]) <= geometry_ids:
        return False
    complete_mapping = (
        len(mapping) == len(source_structure["source_atoms"])
        and {item["from_atom_id"] for item in mapping} == {item["atom_id"] for item in states[target["from_state_id"]]["atoms"]}
    )
    assertions = set(prerequisites["reviewed_assertions"])
    if strategy == "published_coordinates":
        return (
            source_structure["coordinate_provenance"]["status"] == "published_coordinates"
            and source_structure["atom_order_review_status"] == "reviewed"
            and all(value == "reviewed" for value in source_structure["audits"].values())
            and complete_mapping
            and "coordinate_identity_order_stereo_charge_multiplicity_coordination_audit_complete" in assertions
        )
    if strategy == "reviewed_structure_rebuild":
        return source_structure["atom_order_review_status"] == "reviewed" and all(value == "reviewed" for value in source_structure["audits"].values()) and complete_mapping and "source_structure_rebuild_scope_reviewed" in assertions
    if strategy == "endpoint_qst_family":
        return set(prerequisites["endpoint_state_ids"]) == {target["from_state_id"], target["to_state_id"]} and prerequisites["source_object"] is not None and bool(prerequisites["source_anchor"]) and "endpoint_geometries_reviewed" in assertions
    if strategy == "relaxed_scan":
        return bool(prerequisites["geometry_item_ids"]) and "scan_scope_and_coordinate_reviewed" in assertions
    if strategy == "hessian_guided_guess":
        return prerequisites["source_object"] is not None and bool(prerequisites["source_anchor"]) and "hessian_mode_applicability_reviewed" in assertions
    return False


def _normalize_record(raw: dict[str, Any], edges: dict[str, dict[str, Any]], states: dict[str, dict[str, Any]], edge_diagnostics: dict[str, dict[str, Any]], blocked_scopes: set[str], candidates: dict[str, dict[str, Any]], review_path: Path) -> dict[str, Any]:
    data = _exact(raw, RECORD_KEYS, f"precedent {raw.get('precedent_id', '?')}")
    precedent_id = rw._require_id(data["precedent_id"], "precedent_id")
    target_raw = data["target"]
    rw.require(isinstance(target_raw, dict) and target_raw.get("edge_id") in edges, f"precedent {precedent_id} references an unknown mechanism edge")
    edge = edges[target_raw["edge_id"]]
    target = _normalize_target(target_raw, edge, states, f"precedent {precedent_id}.target")
    source_raw = data["source_precedent"]
    rw.require(isinstance(source_raw, dict) and source_raw.get("candidate_id") in candidates, f"precedent {precedent_id} references an unknown evidence candidate")
    source = _normalize_source_precedent(source_raw, candidates[source_raw["candidate_id"]], f"precedent {precedent_id}.source_precedent")
    source_structure = _normalize_source_structure(data["source_structure"], source, review_path, f"precedent {precedent_id}.source_structure")
    mapping = _normalize_mapping(data["source_to_target_atom_mapping"], source_structure, edge, states, f"precedent {precedent_id}.source_to_target_atom_mapping")
    context = _normalize_context(data["target_context"], target, states, f"precedent {precedent_id}.target_context")
    geometry = _normalize_geometry(data["geometry_transfer"], target, states, source, source_structure, mapping, f"precedent {precedent_id}.geometry_transfer")
    if any(item["transfer_status"] == "transferable" for item in geometry):
        rw.require(source_structure["atom_order_review_status"] == "reviewed" and bool(mapping), f"precedent {precedent_id}: geometry transfer requires reviewed source atom ordering and explicit correspondence")
    strategy = rw._require_string(data["seed_strategy"], f"precedent {precedent_id}.seed_strategy")
    rw.require(strategy in STRATEGIES, f"precedent {precedent_id}.seed_strategy is invalid")
    prerequisites = _normalize_prerequisites(data["strategy_prerequisites"], review_path, f"precedent {precedent_id}.strategy_prerequisites")
    geometry_ids = {item["geometry_item_id"] for item in geometry}
    rw.require(set(prerequisites["geometry_item_ids"]) <= geometry_ids, f"precedent {precedent_id}: strategy prerequisites reference unknown geometry items")
    rw.require(set(prerequisites["endpoint_state_ids"]) <= {target["from_state_id"], target["to_state_id"]}, f"precedent {precedent_id}: strategy prerequisites reference states outside the target edge")
    complete = _strategy_complete(strategy, prerequisites, source_structure, mapping, target, geometry, states)
    applicability = _exact(data["applicability_review"], {"status", "rationale", "limitations"}, f"precedent {precedent_id}.applicability_review")
    rw.require(applicability["status"] in {"reviewed", "pending", "blocked"}, f"precedent {precedent_id}.applicability_review.status is invalid")
    applicability = {"status": applicability["status"], "rationale": rw._require_string(applicability["rationale"], f"precedent {precedent_id}.applicability rationale"), "limitations": rw._string_list(applicability["limitations"], f"precedent {precedent_id}.applicability limitations", nonempty=True)}
    uncertainties = rw._string_list(data["uncertainties"], f"precedent {precedent_id}.uncertainties")
    alternatives = rw._string_list(data["alternatives"], f"precedent {precedent_id}.alternatives")
    negative_evidence = rw._string_list(data["negative_evidence"], f"precedent {precedent_id}.negative_evidence")
    record_blockers = rw._string_list(data["blockers"], f"precedent {precedent_id}.blockers")
    disposition = _exact(data["disposition"], {"status", "promotion_review"}, f"precedent {precedent_id}.disposition")
    status = rw._require_string(disposition["status"], f"precedent {precedent_id}.disposition.status")
    rw.require(status in {"proposed", "accepted_for_candidate_construction", "rejected", "blocked"}, f"precedent {precedent_id}.disposition.status is invalid")
    promotion = _exact(disposition["promotion_review"], {"status", "reviewer", "reviewed_at", "rationale"}, f"precedent {precedent_id}.promotion_review")
    rw.require(promotion["status"] in {"pending", "approved", "rejected", "blocked"}, f"precedent {precedent_id}.promotion_review.status is invalid")
    for key in ("reviewer", "reviewed_at"):
        rw.require(promotion[key] is None or (isinstance(promotion[key], str) and promotion[key].strip()), f"precedent {precedent_id}.promotion_review.{key} is invalid")
    promotion["rationale"] = rw._require_string(promotion["rationale"], f"precedent {precedent_id}.promotion_review.rationale")
    if source["relationship"] == "unusable" or status in {"rejected", "blocked"}:
        rw.require(bool(negative_evidence), f"precedent {precedent_id}: unusable, rejected, or blocked records require explicit negative_evidence")
    if status == "accepted_for_candidate_construction":
        rw.require(edge["review_status"] == "reviewed_hypothesis" and not edge["blockers"], f"precedent {precedent_id}: accepted disposition requires an unblocked reviewed edge")
        rw.require(all(states[state_id]["review_status"] == "reviewed_hypothesis" and not states[state_id]["blockers"] for state_id in (target["from_state_id"], target["to_state_id"])), f"precedent {precedent_id}: accepted disposition requires unblocked reviewed endpoint states")
        diagnostic = edge_diagnostics[edge["edge_id"]]
        rw.require(diagnostic["elements_conserved"] and diagnostic["charge_conserved"] and diagnostic["connection_changes_consistent"], f"precedent {precedent_id}: accepted disposition requires a conserved, connectivity-consistent edge")
        rw.require(not ({edge["edge_id"], target["from_state_id"], target["to_state_id"]} & blocked_scopes), f"precedent {precedent_id}: mechanism-network blockers apply to the target edge or states")
        rw.require(target["eligibility"] == "eligible" and context["review_status"] == "reviewed", f"precedent {precedent_id}: accepted disposition requires reviewed target eligibility/context")
        rw.require(applicability["status"] == "reviewed" and promotion["status"] == "approved" and promotion["reviewer"] and promotion["reviewed_at"], f"precedent {precedent_id}: accepted disposition requires completed applicability and promotion review")
        rw.require(not record_blockers, f"precedent {precedent_id}: accepted disposition cannot retain record blockers")
        rw.require(source["bounded_use"] in {"geometry_seed_support", "ts_topology_support"}, f"precedent {precedent_id}: accepted disposition requires geometry_seed_support or ts_topology_support")
        rw.require(complete, f"precedent {precedent_id}: {strategy} prerequisites are incomplete")
        if strategy == "published_coordinates":
            rw.require(source["evidence_target"] == "coordinates" and source["bounded_use"] == "geometry_seed_support", f"precedent {precedent_id}: published-coordinate strategy requires source-located coordinate evidence and geometry_seed_support")
        elif strategy == "reviewed_structure_rebuild":
            rw.require(source["bounded_use"] in {"geometry_seed_support", "ts_topology_support"}, f"precedent {precedent_id}: structure rebuild requires a geometry/topology bounded use")
        rw.require(bool(uncertainties) and bool(alternatives), f"precedent {precedent_id}: accepted disposition requires explicit uncertainty and alternative review")
    gate = "blocked_pending_mechanism_support" if status == "accepted_for_candidate_construction" else "not_promoted_by_disposition"
    return {
        "precedent_id": precedent_id, "target": target, "source_precedent": source,
        "source_structure": source_structure, "source_to_target_atom_mapping": mapping,
        "target_context": context, "geometry_transfer": geometry,
        "seed_strategy": strategy, "strategy_prerequisites": prerequisites,
        "applicability_review": applicability, "uncertainties": uncertainties,
        "alternatives": alternatives, "negative_evidence": negative_evidence,
        "disposition": {"status": status, "promotion_review": dict(promotion)},
        "blockers": record_blockers,
        "notes": rw._string_list(data["notes"], f"precedent {precedent_id}.notes"),
        "promotion_requirements_complete": complete and applicability["status"] == "reviewed" and promotion["status"] == "approved",
        "candidate_construction_gate": gate,
    }


def _normalize_review(review: dict[str, Any], mechanism: dict[str, Any], snapshot: dict[str, Any], evidence: dict[str, Any], review_path: Path) -> tuple[list[dict[str, Any]], str, list[str]]:
    _exact(review, REVIEW_KEYS, "TS-precedent review")
    rw.require(review["schema"] == REVIEW_SCHEMA, "unrecognized TS-precedent review schema")
    rw.require(review["study_id"] == mechanism["study_id"] == snapshot["study_id"], "TS-precedent review study_id differs from upstream")
    rw.require(review["mechanism_network_payload_sha256"] == mechanism["payload_sha256"], "TS-precedent review mechanism-network hash mismatch")
    rw.require(review["knowledge_snapshot_payload_sha256"] == snapshot["payload_sha256"], "TS-precedent review knowledge-snapshot hash mismatch")
    rw.require(review["literature_evidence_payload_sha256"] == evidence["evidence_review_payload_sha256"], "TS-precedent review literature-evidence hash mismatch")
    raw_records = review["records"]
    rw.require(isinstance(raw_records, list) and raw_records, "TS-precedent review records must be a non-empty array")
    edges = {item["edge_id"]: item for item in mechanism["edges"]}
    states = {item["state_id"]: item for item in mechanism["states"]}
    edge_diagnostics = {item["edge_id"]: item for item in mechanism["diagnostics"]["edge_conservation_and_connectivity"]}
    blocked_scopes = {item["scope"] for item in mechanism["blockers"] if item["blocker_id"] != "mechanism_support_unavailable"}
    candidates = _evidence_reviews(evidence)
    records: list[dict[str, Any]] = []
    ids: set[str] = set()
    for raw in raw_records:
        normalized = _normalize_record(raw, edges, states, edge_diagnostics, blocked_scopes, candidates, review_path)
        rw.require(normalized["precedent_id"] not in ids, f"duplicate precedent_id: {normalized['precedent_id']}")
        ids.add(normalized["precedent_id"]); records.append(normalized)
    decision = rw._require_string(review["review_decision"], "TS-precedent review_decision")
    rw.require(decision in rw.REVIEW_DECISIONS, "invalid TS-precedent review_decision")
    return sorted(records, key=lambda item: item["precedent_id"]), decision, rw._string_list(review["review_notes"], "TS-precedent review_notes")


def build(mechanism_path: Path, snapshot_path: Path, evidence_path: Path, review_path: Path, output: Path) -> dict[str, Any]:
    mechanism, snapshot, evidence, w1 = _load_upstream(mechanism_path, snapshot_path, evidence_path)
    _require_regular_file(review_path, "TS-precedent review input")
    review = rw.load_json(review_path)
    records, decision, notes = _normalize_review(review, mechanism, snapshot, evidence, review_path)
    blocker = rw._blocker(
        "mechanism_support_unavailable", "study",
        f"Required {SUPPORT_SCHEMA} remains unimplemented; locally reviewed precedent dispositions cannot enter candidate construction.",
        ("candidate_construction", "mechanism_promotion", "ts_seed_construction"),
    )
    artifact = {
        "schema": OUTPUT_SCHEMA, "study_id": mechanism["study_id"],
        "reaction_intake": _input_ref(w1["reaction_intake"][0], w1["reaction_intake"][1]["payload_sha256"]),
        "species_registry": _input_ref(w1["species_registry"][0], w1["species_registry"][1]["payload_sha256"]),
        "condition_model": _input_ref(w1["condition_model"][0], w1["condition_model"][1]["payload_sha256"]),
        "mechanism_network": _input_ref(mechanism_path, mechanism["payload_sha256"]),
        "knowledge_snapshot": _input_ref(snapshot_path, snapshot["payload_sha256"]),
        "literature_evidence": _input_ref(evidence_path, evidence["evidence_review_payload_sha256"]),
        "review_source": rw._artifact_ref(review_path),
        "mechanism_support": {"schema": SUPPORT_SCHEMA, "status": "unavailable_unimplemented", "candidate_construction_promotable": False},
        "records": records, "blockers": [blocker],
        "review": {"decision": decision, "notes": notes},
        "gate_status": rw._gate_status(decision, [blocker]),
        "candidate_construction_promotable": False,
        "calculation_ready": False, "no_submission_authorization": True,
    }
    rw.finalize_artifact(artifact)
    _write_json_exclusive(output, artifact)
    return artifact


def validate(path: Path) -> dict[str, Any]:
    artifact = rw.load_json(path)
    keys = {
        "schema", "study_id", "reaction_intake", "species_registry", "condition_model",
        "mechanism_network", "knowledge_snapshot", "literature_evidence", "review_source",
        "mechanism_support", "records", "blockers", "review", "gate_status",
        "candidate_construction_promotable", "calculation_ready",
        "no_submission_authorization", "payload_sha256",
    }
    _exact(artifact, keys, "TS-precedent artifact")
    rw.require(artifact["schema"] == OUTPUT_SCHEMA, "unrecognized TS-precedent artifact schema")
    rw.validate_payload_hash(artifact)
    rw.require(artifact["calculation_ready"] is False and artifact["no_submission_authorization"] is True and artifact["candidate_construction_promotable"] is False, "TS-precedent artifact violates safety constants")
    mechanism = _verify_generic_input_ref(artifact["mechanism_network"], path, mn.OUTPUT_SCHEMA, "payload_sha256", "TS-precedent mechanism network")
    snapshot = _verify_generic_input_ref(artifact["knowledge_snapshot"], path, KNOWLEDGE_SCHEMA, "payload_sha256", "TS-precedent knowledge snapshot")
    evidence = _verify_generic_input_ref(artifact["literature_evidence"], path, LITERATURE_SCHEMA, "evidence_review_payload_sha256", "TS-precedent literature evidence")
    mechanism_path = _resolve(artifact["mechanism_network"], path)
    snapshot_path = _resolve(artifact["knowledge_snapshot"], path)
    evidence_path = _resolve(artifact["literature_evidence"], path)
    loaded_mechanism, loaded_snapshot, loaded_evidence, w1 = _load_upstream(mechanism_path, snapshot_path, evidence_path)
    rw.require(mechanism == loaded_mechanism and snapshot == loaded_snapshot and evidence == loaded_evidence, "TS-precedent upstream recomputation mismatch")
    for key, schema in (("reaction_intake", rw.INTAKE_SCHEMA), ("species_registry", rw.REGISTRY_SCHEMA), ("condition_model", rw.CONDITION_SCHEMA)):
        bound = _verify_generic_input_ref(artifact[key], path, schema, "payload_sha256", f"TS-precedent {key}")
        rw.require(bound == w1[key][1], f"TS-precedent {key} differs from mechanism-network W1 binding")
    review_ref = _exact(artifact["review_source"], {"path", "sha256", "size_bytes"}, "TS-precedent review_source")
    review_path = _resolve(review_ref, path)
    rw.require(review_path.is_file() and not review_path.is_symlink(), "TS-precedent review source is missing or a symlink")
    rw.require(review_ref["sha256"] == rw.sha256_file(review_path) and review_ref["size_bytes"] == review_path.stat().st_size, "TS-precedent review source binding mismatch")
    records, decision, notes = _normalize_review(rw.load_json(review_path), mechanism, snapshot, evidence, review_path)
    rw.require(artifact["records"] == records, "TS-precedent records differ from immutable review recomputation")
    expected_support = {"schema": SUPPORT_SCHEMA, "status": "unavailable_unimplemented", "candidate_construction_promotable": False}
    rw.require(artifact["mechanism_support"] == expected_support, "TS-precedent mechanism-support blocker was weakened")
    expected_blocker = rw._blocker("mechanism_support_unavailable", "study", f"Required {SUPPORT_SCHEMA} remains unimplemented; locally reviewed precedent dispositions cannot enter candidate construction.", ("candidate_construction", "mechanism_promotion", "ts_seed_construction"))
    rw.require(artifact["blockers"] == [expected_blocker], "TS-precedent blockers differ from mandatory fail-closed state")
    rw.require(artifact["review"] == {"decision": decision, "notes": notes}, "TS-precedent review differs from immutable source")
    rw.require(artifact["gate_status"] == rw._gate_status(decision, [expected_blocker]), "TS-precedent gate_status is inconsistent")
    return {"schema": "gaussian-ts-precedent-map-validation/1", "artifact_schema": OUTPUT_SCHEMA, "study_id": artifact["study_id"], "gate_status": artifact["gate_status"], "record_count": len(records), "payload_sha256": artifact["payload_sha256"], "live_actions": False}


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    build_parser = commands.add_parser("build", help="build one immutable offline TS-precedent map")
    build_parser.add_argument("mechanism_network", type=Path)
    build_parser.add_argument("knowledge_snapshot", type=Path)
    build_parser.add_argument("literature_evidence", type=Path)
    build_parser.add_argument("--review", type=Path, required=True)
    build_parser.add_argument("--output", type=Path, required=True)
    validate_parser = commands.add_parser("validate", help="validate and independently recompute one TS-precedent map")
    validate_parser.add_argument("artifact", type=Path)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "build":
            result = build(args.mechanism_network, args.knowledge_snapshot, args.literature_evidence, args.review, args.output)
        else:
            result = validate(args.artifact)
    except (rw.OfflineError, KB.OfflineError, OSError, ValueError, AssertionError, SystemExit) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
