#!/usr/bin/env python3
"""Build and validate immutable offline mechanism-support evidence gates.

The tool classifies source-located evidence against exact reviewed mechanism
edges and stereochemical channels, then records a separate human promotion
decision.  It never infers chemistry, constructs geometry, chooses a method,
creates Gaussian input, or performs a live action.
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import mechanism_network as mn
import reaction_workflow as rw


REVIEW_SCHEMA = "gaussian-reaction-mechanism-support-review/1"
OUTPUT_SCHEMA = "gaussian-reaction-mechanism-support/1"
LITERATURE_SCHEMA = "gaussian-reaction-literature-evidence/1"
KNOWLEDGE_SCHEMA = "auto-g16-knowledge-snapshot/1"

REVIEW_KEYS = {
    "schema", "study_id", "reaction_intake_payload_sha256",
    "species_registry_payload_sha256", "condition_model_payload_sha256",
    "mechanism_network_payload_sha256", "knowledge_snapshot_payload_sha256",
    "literature_evidence_payload_sha256", "records", "review_decision",
    "reviewer", "reviewed_at", "review_notes",
}
RECORD_KEYS = {
    "support_record_id", "target", "evidence", "applicability_dimensions",
    "classification", "mechanistic_review", "hypothesis_review",
    "exploration_decision", "claim_support_decision", "negative_evidence", "notes",
}
DIMENSIONS = {
    "net_transformation", "elementary_step_and_atom_correspondence",
    "substrate_electronics_sterics_and_groups", "catalyst_and_active_state",
    "atom_inventory_charge_multiplicity_and_spin",
    "coordination_ion_pair_additives_and_solvent", "stereochemical_channel",
    "experimental_conditions", "computational_protocol_and_validation",
}
APPLICABILITY = {"exact", "close", "remote", "contradictory", "unknown", "not_applicable"}
CLASSIFICATIONS = {"direct", "analogy", "contradictory", "missing", "excluded"}
CLAIM_EFFECTS = {"supports", "contradicts", "does_not_address", "excluded"}
EVIDENCE_KINDS = {"experimental", "computational", "mixed", "not_applicable"}
PROMOTION_STATUSES = {"promoted", "conditional", "not_promoted", "rejected"}
EXPLORATION_STATUSES = {"eligible", "ineligible", "blocked"}
REVIEW_STATUSES = {"reviewed", "blocked"}
EVIDENCE_BASES = {
    "direct_literature_support", "literature_analogy", "internal_rationale",
    "contradictory_evidence", "absence_of_direct_precedent",
    "later_experimental_evidence", "later_computational_evidence",
    "excluded_evidence",
}


def _load_sibling_module(name: str, relative: str) -> Any:
    path = Path(__file__).resolve().parents[2] / relative
    spec = importlib.util.spec_from_file_location(name, path)
    rw.require(spec is not None and spec.loader is not None, f"cannot load required validator: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


KB = _load_sibling_module("auto_g16_mechanism_support_kb", "auto-g16-knowledge-base/scripts/knowledge_base.py")
LIT = _load_sibling_module("auto_g16_mechanism_support_lit", "auto-g16-reaction-literature/scripts/literature_search.py")


def _exact(value: Any, keys: set[str], label: str) -> dict[str, Any]:
    rw.require(isinstance(value, dict), f"{label} must be an object")
    rw._require_exact_keys(value, keys, keys, label)
    return value


def _require_regular_file(path: Path, label: str) -> None:
    rw.require(path.is_file() and not path.is_symlink(), f"{label} is missing or a symlink")


def _resolve(reference: dict[str, Any], owner: Path) -> Path:
    path = Path(reference["path"])
    return path if path.is_absolute() else owner.parent / path


def _input_ref(path: Path, payload_sha256: str) -> dict[str, Any]:
    return {**rw._artifact_ref(path), "payload_sha256": payload_sha256}


def _verify_input_ref(
    value: Any, owner: Path, schema: str, payload_key: str, label: str
) -> tuple[Path, dict[str, Any]]:
    ref = _exact(value, {"path", "sha256", "size_bytes", "payload_sha256"}, label)
    path = _resolve(ref, owner)
    _require_regular_file(path, label)
    rw.require(ref["sha256"] == rw.sha256_file(path) and ref["size_bytes"] == path.stat().st_size, f"{label} file binding mismatch")
    data = rw.load_json(path)
    rw.require(data.get("schema") == schema, f"{label} schema mismatch")
    rw.require(data.get(payload_key) == ref["payload_sha256"], f"{label} payload binding mismatch")
    return path, data


def _artifact_binding_path(binding: Any, owner: Path, label: str) -> tuple[Path, dict[str, Any]]:
    item = _exact(binding, {"path", "sha256", "schema", "payload_sha256"}, label)
    path = _resolve(item, owner)
    _require_regular_file(path, label)
    rw.require(item["sha256"] == rw.sha256_file(path), f"{label} file hash mismatch")
    data = rw.load_json(path)
    rw.require(data.get("schema") == item["schema"], f"{label} schema mismatch")
    payload = data.get("evidence_review_payload_sha256") if item["schema"] == LITERATURE_SCHEMA else data.get("payload_sha256")
    rw.require(payload == item["payload_sha256"], f"{label} payload hash mismatch")
    return path, data


def _validate_finalized_evidence(path: Path) -> dict[str, Any]:
    evidence = LIT.load_json(path)
    rw.require(evidence.get("schema") == LITERATURE_SCHEMA, "literature evidence schema mismatch")
    rw.require(evidence.get("record_status") == "validated_review_record", "literature evidence must be finalized")
    LIT.verify_payload_hash(evidence, "evidence_review_payload_sha256")
    with contextlib.redirect_stdout(io.StringIO()):
        LIT.command_validate_review(SimpleNamespace(review=str(path), output=None))
    return evidence


def _load_upstream(
    mechanism_path: Path, snapshot_path: Path, evidence_path: Path
) -> tuple[
    dict[str, Any], dict[str, Any], dict[str, Any],
    dict[str, tuple[Path, dict[str, Any]]],
]:
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
    evidence = _validate_finalized_evidence(evidence_path)

    w1: dict[str, tuple[Path, dict[str, Any]]] = {}
    for key, network_key, schema in (
        ("reaction_intake", "intake", rw.INTAKE_SCHEMA),
        ("species_registry", "species_registry", rw.REGISTRY_SCHEMA),
        ("condition_model", "condition_model", rw.CONDITION_SCHEMA),
    ):
        ref = mechanism[network_key]
        path = _resolve(ref, mechanism_path)
        data = rw._verify_bound_artifact(ref, mechanism_path, schema, f"mechanism {key}")
        rw.validate_artifact(path)
        w1[key] = (path, data)

    intake_path, intake = w1["reaction_intake"]
    parent = snapshot["parent_reaction_intake"]
    parent_path = _resolve(parent, snapshot_path)
    _require_regular_file(parent_path, "knowledge snapshot parent intake")
    rw.require(parent_path.resolve() == intake_path.resolve(), "knowledge snapshot parent intake path differs from mechanism network")
    rw.require(parent["sha256"] == rw.sha256_file(intake_path) and parent["size_bytes"] == intake_path.stat().st_size, "knowledge snapshot parent intake file binding mismatch")
    rw.require(parent["payload_sha256"] == intake["payload_sha256"], "knowledge snapshot parent intake payload mismatch")
    rw.require(snapshot["study_id"] == mechanism["study_id"], "knowledge snapshot study_id differs from mechanism network")

    upstream = evidence.get("upstream_artifacts")
    rw.require(isinstance(upstream, dict) and set(upstream) == {"reaction_intake", "species_registry", "condition_model", "knowledge_snapshot"}, "literature evidence requires exact W1 and knowledge-snapshot bindings")
    for key in ("reaction_intake", "species_registry", "condition_model"):
        path, data = _artifact_binding_path(upstream[key], evidence_path, f"literature {key}")
        expected_path, expected = w1[key]
        rw.require(path.resolve() == expected_path.resolve(), f"literature {key} path differs from mechanism network")
        rw.require(data.get("payload_sha256") == expected["payload_sha256"], f"literature {key} payload differs from mechanism network")
    knowledge_path, knowledge = _artifact_binding_path(upstream["knowledge_snapshot"], evidence_path, "literature knowledge_snapshot")
    rw.require(knowledge_path.resolve() == snapshot_path.resolve(), "literature knowledge-snapshot path differs from supplied snapshot")
    rw.require(knowledge["payload_sha256"] == snapshot["payload_sha256"], "literature knowledge-snapshot payload differs from supplied snapshot")
    return mechanism, snapshot, evidence, w1


def _id_list(value: Any, label: str) -> list[str]:
    result = rw._string_list(value, label)
    for item in result:
        rw._require_id(item, label)
    rw.require(len(result) == len(set(result)), f"{label} must not contain duplicates")
    return result


def _pair_list(value: Any, label: str, atoms: set[str]) -> list[list[str]]:
    rw.require(isinstance(value, list), f"{label} must be an array")
    result: list[list[str]] = []
    for index, raw in enumerate(value):
        pair = _id_list(raw, f"{label}[{index}]")
        rw.require(len(pair) == 2 and pair[0] != pair[1] and set(pair) <= atoms, f"{label}[{index}] must reference two distinct from-state atoms")
        result.append(sorted(pair))
    result.sort()
    rw.require(len(result) == len({tuple(item) for item in result}), f"{label} contains duplicates")
    return result


def _normalize_target(
    raw: Any, edge: dict[str, Any], states: dict[str, dict[str, Any]], label: str
) -> dict[str, Any]:
    data = _exact(raw, {
        "edge_id", "from_state_id", "to_state_id", "stereochemical_channel",
        "edge_atom_mapping", "forming_pairs", "breaking_pairs", "transfers",
    }, label)
    rw.require(data["edge_id"] == edge["edge_id"], f"{label}.edge_id mismatch")
    rw.require(data["from_state_id"] == edge["from_state_id"] and data["to_state_id"] == edge["to_state_id"], f"{label} state IDs differ from mechanism edge")
    rw.require(data["stereochemical_channel"] == edge["stereochemical_channel"], f"{label} stereochemical channel differs from mechanism edge")
    mappings: list[dict[str, str]] = []
    rw.require(isinstance(data["edge_atom_mapping"], list), f"{label}.edge_atom_mapping must be an array")
    for index, raw_mapping in enumerate(data["edge_atom_mapping"]):
        mapping = _exact(raw_mapping, {"from_atom_id", "to_atom_id"}, f"{label}.edge_atom_mapping[{index}]")
        mappings.append({
            "from_atom_id": rw._require_id(mapping["from_atom_id"], f"{label}.from_atom_id"),
            "to_atom_id": rw._require_id(mapping["to_atom_id"], f"{label}.to_atom_id"),
        })
    mappings.sort(key=lambda item: item["from_atom_id"])
    rw.require(mappings == edge["atom_mapping"], f"{label} atom mapping differs from mechanism edge")
    source_atoms = {item["atom_id"] for item in states[edge["from_state_id"]]["atoms"]}
    forming = _pair_list(data["forming_pairs"], f"{label}.forming_pairs", source_atoms)
    breaking = _pair_list(data["breaking_pairs"], f"{label}.breaking_pairs", source_atoms)
    expected_forming = sorted(item["atom_ids"] for item in edge["connection_changes"] if item["before_order"] is None and item["after_order"] is not None)
    expected_breaking = sorted(item["atom_ids"] for item in edge["connection_changes"] if item["before_order"] is not None and item["after_order"] is None)
    rw.require(forming == expected_forming and breaking == expected_breaking, f"{label} forming/breaking pairs differ from mechanism edge")
    transfers: list[dict[str, str]] = []
    rw.require(isinstance(data["transfers"], list), f"{label}.transfers must be an array")
    for index, raw_transfer in enumerate(data["transfers"]):
        transfer = _exact(raw_transfer, {"atom_id", "donor_atom_id", "acceptor_atom_id"}, f"{label}.transfers[{index}]")
        normalized = {key: rw._require_id(transfer[key], f"{label}.transfers[{index}].{key}") for key in transfer}
        rw.require(set(normalized.values()) <= source_atoms, f"{label}.transfers[{index}] references an unknown atom")
        transfers.append(normalized)
    transfers.sort(key=lambda item: (item["atom_id"], item["donor_atom_id"], item["acceptor_atom_id"]))
    rw.require(transfers == edge["transfers"], f"{label}.transfers differ from mechanism edge")
    return {
        "edge_id": edge["edge_id"], "from_state_id": edge["from_state_id"],
        "to_state_id": edge["to_state_id"], "stereochemical_channel": edge["stereochemical_channel"],
        "edge_atom_mapping": mappings, "forming_pairs": forming,
        "breaking_pairs": breaking, "transfers": transfers,
    }


def _candidate_reviews(evidence: dict[str, Any]) -> dict[str, dict[str, Any]]:
    reviews = evidence.get("reviews")
    rw.require(isinstance(reviews, list), "literature evidence reviews must be an array")
    result: dict[str, dict[str, Any]] = {}
    for item in reviews:
        rw.require(isinstance(item, dict) and isinstance(item.get("candidate_id"), str), "literature evidence contains an invalid candidate review")
        rw.require(item["candidate_id"] not in result, "literature evidence contains duplicate candidate IDs")
        result[item["candidate_id"]] = item
    return result


def _binding_id(prefix: str, value: Any) -> str:
    return f"{prefix}_{rw.sha256_data(value)[:20]}"


def _normalize_evidence(raw: Any, candidate: dict[str, Any], label: str) -> dict[str, Any]:
    data = _exact(raw, {"candidate_id", "evidence_target", "source_location"}, label)
    rw.require(data["candidate_id"] == candidate["candidate_id"], f"{label}.candidate_id mismatch")
    target = rw._require_string(data["evidence_target"], f"{label}.evidence_target")
    claim = candidate.get("evidence", {}).get(target)
    rw.require(isinstance(claim, dict), f"{label} references an absent finalized evidence claim")
    claim_status = claim.get("status")
    rw.require(claim_status in {"source_reports", "not_found", "source_ambiguous", "not_reviewed"}, f"{label} claim status is invalid")
    location = data["source_location"]
    if claim_status == "source_reports":
        _exact(location, {"source_type", "locator", "url_or_doi", "checked_at"}, f"{label}.source_location")
        rw.require(location in claim.get("source_locations", []), f"{label}.source_location is absent from the finalized claim")
    else:
        rw.require(location is None, f"{label}.source_location must be null when no source-located claim exists")
    decision = candidate.get("reviewer_decision", {})
    candidate_hash = rw.sha256_data(candidate)
    claim_binding = {"candidate_id": candidate["candidate_id"], "evidence_target": target, "claim": claim}
    location_binding = None if location is None else {"candidate_id": candidate["candidate_id"], "evidence_target": target, "source_location": location}
    return {
        "candidate_id": candidate["candidate_id"],
        "candidate_review_payload_sha256": candidate_hash,
        "evidence_target": target,
        "claim_status": claim_status,
        "claim_binding_id": _binding_id("claim", claim_binding),
        "claim_payload_sha256": rw.sha256_data(claim_binding),
        "source_location": None if location is None else dict(location),
        "location_binding_id": None if location_binding is None else _binding_id("location", location_binding),
        "location_payload_sha256": None if location_binding is None else rw.sha256_data(location_binding),
        "literature_decision": decision.get("status"),
        "bounded_use": decision.get("bounded_use"),
    }


def _normalize_applicability(raw: Any, candidate: dict[str, Any], label: str) -> list[dict[str, str]]:
    rw.require(isinstance(raw, list) and len(raw) == len(DIMENSIONS), f"{label} requires all nine applicability dimensions")
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    directness = candidate.get("directness_dimensions", {})
    for index, item in enumerate(raw):
        row = _exact(item, {"dimension", "value", "rationale", "source_anchor"}, f"{label}[{index}]")
        dimension = rw._require_string(row["dimension"], f"{label}[{index}].dimension")
        rw.require(dimension in DIMENSIONS and dimension not in seen, f"{label} contains an invalid or duplicate dimension")
        seen.add(dimension)
        value = rw._require_string(row["value"], f"{label}[{index}].value")
        rw.require(value in APPLICABILITY, f"{label}[{index}].value is invalid")
        rw.require(directness.get(dimension) == value, f"{label}.{dimension} differs from finalized literature applicability")
        result.append({
            "dimension": dimension, "value": value,
            "rationale": rw._require_string(row["rationale"], f"{label}[{index}].rationale"),
            "source_anchor": rw._require_string(row["source_anchor"], f"{label}[{index}].source_anchor"),
        })
    return sorted(result, key=lambda item: item["dimension"])


def _normalize_classification(
    raw: Any, evidence: dict[str, Any], applicability: list[dict[str, str]], label: str
) -> dict[str, Any]:
    data = _exact(raw, {
        "category", "evidence_basis", "claim_effect", "evidence_kind", "rationale",
        "alternative_explanations", "important_mismatches",
    }, label)
    category = rw._require_string(data["category"], f"{label}.category")
    evidence_basis = rw._require_string(data["evidence_basis"], f"{label}.evidence_basis")
    effect = rw._require_string(data["claim_effect"], f"{label}.claim_effect")
    evidence_kind = rw._require_string(data["evidence_kind"], f"{label}.evidence_kind")
    rw.require(category in CLASSIFICATIONS and evidence_basis in EVIDENCE_BASES and effect in CLAIM_EFFECTS and evidence_kind in EVIDENCE_KINDS, f"{label} contains an invalid enum")
    values = {item["value"] for item in applicability}
    source_located = evidence["claim_status"] == "source_reports" and evidence["source_location"] is not None
    if category == "direct":
        rw.require(source_located and evidence["literature_decision"] == "source_reports_direct_precedent", f"{label}: direct classification requires a source-located direct precedent")
        rw.require(values <= {"exact", "not_applicable"}, f"{label}: direct classification requires exact applicability")
        rw.require(effect == "supports", f"{label}: direct classification must support the target claim")
        rw.require(evidence_basis in {"direct_literature_support", "later_experimental_evidence", "later_computational_evidence"}, f"{label}: direct classification has an incompatible evidence basis")
    elif category == "analogy":
        rw.require(source_located and evidence["literature_decision"] == "source_reports_analogy", f"{label}: analogy classification requires source-located analogy evidence")
        rw.require(bool(values & {"close", "remote", "unknown"}) and "contradictory" not in values, f"{label}: analogy classification requires an explicit non-exact applicability dimension")
        rw.require(effect == "supports", f"{label}: analogy classification must record bounded support")
        rw.require(evidence_basis == "literature_analogy", f"{label}: analogy classification requires literature_analogy basis")
    elif category == "contradictory":
        rw.require(source_located and effect == "contradicts", f"{label}: contradictory classification requires source-located contradictory evidence")
        rw.require("contradictory" in values or evidence["literature_decision"] == "exclude", f"{label}: contradictory classification requires an explicit contradiction")
        rw.require(evidence_basis == "contradictory_evidence", f"{label}: contradictory classification requires contradictory_evidence basis")
    elif category == "missing":
        rw.require(not source_located and evidence["claim_status"] in {"not_found", "source_ambiguous", "not_reviewed"}, f"{label}: missing classification requires a missing or ambiguous finalized claim")
        rw.require(effect == "does_not_address", f"{label}: missing classification must use does_not_address")
        rw.require(evidence_basis in {"absence_of_direct_precedent", "internal_rationale"}, f"{label}: missing classification must distinguish absence of precedent from internal rationale")
    else:
        rw.require(effect == "excluded", f"{label}: excluded classification must use excluded claim_effect")
        rw.require(evidence_basis == "excluded_evidence", f"{label}: excluded classification requires excluded_evidence basis")
    return {
        "category": category, "evidence_basis": evidence_basis,
        "claim_effect": effect, "evidence_kind": evidence_kind,
        "rationale": rw._require_string(data["rationale"], f"{label}.rationale"),
        "alternative_explanations": rw._string_list(data["alternative_explanations"], f"{label}.alternative_explanations"),
        "important_mismatches": rw._string_list(data["important_mismatches"], f"{label}.important_mismatches"),
    }


def _coordination_connections(state: dict[str, Any]) -> list[dict[str, Any]]:
    return sorted(
        [dict(item) for item in state["connections"] if item["kind"] == "coordination"],
        key=lambda item: (item["atom_ids"], item["order"]),
    )


def _normalize_status_review(raw: Any, keys: set[str], label: str) -> dict[str, Any]:
    data = _exact(raw, keys | {"status", "rationale"}, label)
    status = rw._require_string(data["status"], f"{label}.status")
    rw.require(status in REVIEW_STATUSES, f"{label}.status is invalid")
    return {**{key: data[key] for key in keys}, "status": status, "rationale": rw._require_string(data["rationale"], f"{label}.rationale")}


def _normalize_mechanistic_review(
    raw: Any, edge: dict[str, Any], states: dict[str, dict[str, Any]], label: str
) -> dict[str, Any]:
    data = _exact(raw, {
        "active_catalyst_state", "elementary_step_atom_correspondence",
        "charge_multiplicity_spin", "coordination_ion_pair",
        "stereochemical_channel",
    }, label)
    source = states[edge["from_state_id"]]
    target = states[edge["to_state_id"]]
    catalyst = _normalize_status_review(data["active_catalyst_state"], {"from_catalyst_projection", "to_catalyst_projection"}, f"{label}.active_catalyst_state")
    rw.require(catalyst["from_catalyst_projection"] == source["catalyst_projection"] and catalyst["to_catalyst_projection"] == target["catalyst_projection"], f"{label}.active_catalyst_state differs from mechanism states")
    elementary = _normalize_status_review(data["elementary_step_atom_correspondence"], {"state_changes"}, f"{label}.elementary_step_atom_correspondence")
    rw.require(elementary["state_changes"] == edge["state_changes"], f"{label}.elementary_step state changes differ from mechanism edge")
    charge_spin = _normalize_status_review(data["charge_multiplicity_spin"], {
        "from_formal_charge", "from_multiplicity", "from_spin_description",
        "to_formal_charge", "to_multiplicity", "to_spin_description",
    }, f"{label}.charge_multiplicity_spin")
    rw.require(charge_spin["from_formal_charge"] == source["formal_charge"] and charge_spin["to_formal_charge"] == target["formal_charge"], f"{label}.charge review differs from endpoint states")
    rw.require(charge_spin["from_multiplicity"] == source["multiplicity"] and charge_spin["to_multiplicity"] == target["multiplicity"], f"{label}.multiplicity review differs from endpoint states")
    charge_spin["from_spin_description"] = rw._require_string(charge_spin["from_spin_description"], f"{label}.from_spin_description")
    charge_spin["to_spin_description"] = rw._require_string(charge_spin["to_spin_description"], f"{label}.to_spin_description")
    coordination = _normalize_status_review(data["coordination_ion_pair"], {
        "from_coordination_connections", "to_coordination_connections", "ion_pair_assessment",
    }, f"{label}.coordination_ion_pair")
    rw.require(coordination["from_coordination_connections"] == _coordination_connections(source) and coordination["to_coordination_connections"] == _coordination_connections(target), f"{label}.coordination review differs from endpoint states")
    coordination["ion_pair_assessment"] = rw._require_string(coordination["ion_pair_assessment"], f"{label}.ion_pair_assessment")
    stereo = _normalize_status_review(data["stereochemical_channel"], {"channel", "from_stereochemistry", "to_stereochemistry"}, f"{label}.stereochemical_channel")
    rw.require(stereo["channel"] == edge["stereochemical_channel"], f"{label}.stereochemical channel differs from mechanism edge")
    rw.require(stereo["from_stereochemistry"] == source["stereochemistry"] and stereo["to_stereochemistry"] == target["stereochemistry"], f"{label}.stereochemistry review differs from endpoint states")
    return {
        "active_catalyst_state": catalyst,
        "elementary_step_atom_correspondence": elementary,
        "charge_multiplicity_spin": charge_spin,
        "coordination_ion_pair": coordination,
        "stereochemical_channel": stereo,
    }


def _normalize_claim_support_decision(raw: Any, label: str) -> dict[str, Any]:
    data = _exact(raw, {
        "status", "rationale", "reviewer", "reviewed_at", "resolved_blockers",
        "unresolved_blockers", "resolved_conflict_record_ids",
    }, label)
    status = rw._require_string(data["status"], f"{label}.status")
    rw.require(status in PROMOTION_STATUSES, f"{label}.status is invalid")
    reviewer = rw._require_string(data["reviewer"], f"{label}.reviewer")
    reviewed_at = rw._require_string(data["reviewed_at"], f"{label}.reviewed_at")
    return {
        "status": status,
        "rationale": rw._require_string(data["rationale"], f"{label}.rationale"),
        "reviewer": reviewer, "reviewed_at": reviewed_at,
        "resolved_blockers": rw._string_list(data["resolved_blockers"], f"{label}.resolved_blockers"),
        "unresolved_blockers": rw._string_list(data["unresolved_blockers"], f"{label}.unresolved_blockers"),
        "resolved_conflict_record_ids": sorted(_id_list(data["resolved_conflict_record_ids"], f"{label}.resolved_conflict_record_ids")),
    }


def _normalize_exploration_decision(raw: Any, label: str) -> dict[str, Any]:
    data = _exact(raw, {
        "status", "rationale", "reviewer", "reviewed_at", "resolved_blockers",
        "unresolved_blockers", "resolved_conflict_record_ids",
    }, label)
    status = rw._require_string(data["status"], f"{label}.status")
    rw.require(status in EXPLORATION_STATUSES, f"{label}.status is invalid")
    return {
        "status": status,
        "rationale": rw._require_string(data["rationale"], f"{label}.rationale"),
        "reviewer": rw._require_string(data["reviewer"], f"{label}.reviewer"),
        "reviewed_at": rw._require_string(data["reviewed_at"], f"{label}.reviewed_at"),
        "resolved_blockers": rw._string_list(data["resolved_blockers"], f"{label}.resolved_blockers"),
        "unresolved_blockers": rw._string_list(data["unresolved_blockers"], f"{label}.unresolved_blockers"),
        "resolved_conflict_record_ids": sorted(_id_list(data["resolved_conflict_record_ids"], f"{label}.resolved_conflict_record_ids")),
    }


def _normalize_hypothesis_review(raw: Any, label: str) -> dict[str, Any]:
    data = _exact(raw, {
        "internal_rationale", "alternatives", "uncertainties", "contradictions",
        "falsifiers",
    }, label)
    return {
        "internal_rationale": rw._require_string(data["internal_rationale"], f"{label}.internal_rationale"),
        "alternatives": rw._string_list(data["alternatives"], f"{label}.alternatives", nonempty=True),
        "uncertainties": rw._string_list(data["uncertainties"], f"{label}.uncertainties", nonempty=True),
        "contradictions": rw._string_list(data["contradictions"], f"{label}.contradictions"),
        "falsifiers": rw._string_list(data["falsifiers"], f"{label}.falsifiers", nonempty=True),
    }


def _support_status(classification: str, promotion: str) -> str:
    if promotion == "promoted":
        return "supported"
    if classification in {"direct", "analogy"}:
        return "conditional"
    return {"contradictory": "contradicted", "missing": "missing", "excluded": "unsupported"}[classification]


def _normalize_record(
    raw: dict[str, Any], edges: dict[str, dict[str, Any]], states: dict[str, dict[str, Any]],
    candidates: dict[str, dict[str, Any]], label: str,
) -> dict[str, Any]:
    data = _exact(raw, RECORD_KEYS, label)
    record_id = rw._require_id(data["support_record_id"], f"{label}.support_record_id")
    target_raw = data["target"]
    rw.require(isinstance(target_raw, dict), f"{label}.target must be an object")
    edge_id = rw._require_id(target_raw.get("edge_id"), f"{label}.target.edge_id")
    rw.require(edge_id in edges, f"{label} references an unknown mechanism edge")
    edge = edges[edge_id]
    target = _normalize_target(target_raw, edge, states, f"{label}.target")
    evidence_raw = data["evidence"]
    rw.require(isinstance(evidence_raw, dict), f"{label}.evidence must be an object")
    candidate_id = rw._require_id(evidence_raw.get("candidate_id"), f"{label}.evidence.candidate_id")
    rw.require(candidate_id in candidates, f"{label} references an unknown literature candidate")
    candidate = candidates[candidate_id]
    evidence = _normalize_evidence(evidence_raw, candidate, f"{label}.evidence")
    applicability = _normalize_applicability(data["applicability_dimensions"], candidate, f"{label}.applicability_dimensions")
    classification = _normalize_classification(data["classification"], evidence, applicability, f"{label}.classification")
    mechanistic = _normalize_mechanistic_review(data["mechanistic_review"], edge, states, f"{label}.mechanistic_review")
    hypothesis = _normalize_hypothesis_review(data["hypothesis_review"], f"{label}.hypothesis_review")
    exploration = _normalize_exploration_decision(data["exploration_decision"], f"{label}.exploration_decision")
    promotion = _normalize_claim_support_decision(data["claim_support_decision"], f"{label}.claim_support_decision")
    negative = rw._string_list(data["negative_evidence"], f"{label}.negative_evidence")
    if classification["category"] == "contradictory":
        rw.require(negative, f"{label}: contradictory classification requires preserved negative_evidence")
    if classification["category"] == "excluded":
        rw.require(promotion["status"] == "rejected", f"{label}: excluded classification requires a rejected promotion decision")
        rw.require(exploration["status"] != "eligible", f"{label}: excluded evidence cannot itself make a hypothesis exploration eligible")
    if exploration["status"] == "eligible":
        rw.require(classification["category"] not in {"contradictory", "excluded"}, f"{label}: contradictory or excluded evidence cannot itself make a hypothesis exploration eligible")
        rw.require(edge["review_status"] == "reviewed_hypothesis" and not edge["blockers"], f"{label}: exploration eligibility requires an unblocked reviewed mechanism edge")
        rw.require(all(item["status"] == "reviewed" for item in mechanistic.values()), f"{label}: exploration eligibility requires completed active-state, atom, charge/spin, coordination/ion-pair, and stereochemical review")
        rw.require(not exploration["unresolved_blockers"], f"{label}: exploration eligibility requires all atom/charge/state and scientific blockers to be resolved")
    if promotion["status"] == "promoted":
        rw.require(classification["category"] == "direct" and classification["claim_effect"] == "supports", f"{label}: promotion requires direct supporting evidence")
        rw.require(evidence["bounded_use"] == "mechanism_support", f"{label}: promotion requires mechanism_support bounded use; discovery-only, protocol-only, and TS-only evidence cannot promote")
        rw.require(edge["review_status"] == "reviewed_hypothesis" and not edge["blockers"], f"{label}: promotion requires an unblocked reviewed mechanism edge")
        rw.require(all(item["status"] == "reviewed" for item in mechanistic.values()), f"{label}: promotion requires completed active-state, atom, charge/spin, coordination/ion-pair, and stereochemical review")
        rw.require(not promotion["unresolved_blockers"], f"{label}: promotion requires all blockers to be resolved")
    elif evidence["bounded_use"] in {"discovery_only", "protocol_candidate_support"}:
        rw.require(promotion["status"] != "promoted", f"{label}: discovery-only or protocol-only evidence cannot promote mechanism support")
    return {
        "support_record_id": record_id, "target": target, "evidence": evidence,
        "applicability_dimensions": applicability, "classification": classification,
        "mechanistic_review": mechanistic, "hypothesis_review": hypothesis,
        "exploration_decision": exploration, "claim_support_decision": promotion,
        "negative_evidence": negative,
        "notes": rw._string_list(data["notes"], f"{label}.notes"),
        "support_status": _support_status(classification["category"], promotion["status"]),
        "hypothesis_exploration_eligible": exploration["status"] == "eligible",
        "mechanism_claim_supported": promotion["status"] == "promoted",
        "mechanism_claim_validated": False,
    }


def _edge_channel_key(record: dict[str, Any]) -> tuple[str, str | None]:
    target = record["target"]
    return target["edge_id"], target["stereochemical_channel"]


def _summarize(
    records: list[dict[str, Any]], edges: dict[str, dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    by_key: dict[tuple[str, str | None], list[dict[str, Any]]] = {}
    for record in records:
        by_key.setdefault(_edge_channel_key(record), []).append(record)
    expected = {(edge["edge_id"], edge["stereochemical_channel"]) for edge in edges.values()}
    missing = expected - set(by_key)
    rw.require(not missing, "mechanism-support review must contain at least one record for every edge/stereochemical channel")

    summaries: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    all_record_ids = {record["support_record_id"] for record in records}
    for key in sorted(by_key, key=lambda item: (item[0], "" if item[1] is None else item[1])):
        items = by_key[key]
        contradictions = sorted(item["support_record_id"] for item in items if item["classification"]["category"] == "contradictory")
        promoted = sorted(item["support_record_id"] for item in items if item["claim_support_decision"]["status"] == "promoted")
        exploration_eligible = sorted(item["support_record_id"] for item in items if item["exploration_decision"]["status"] == "eligible")
        for item in items:
            support_resolved = item["claim_support_decision"]["resolved_conflict_record_ids"]
            exploration_resolved = item["exploration_decision"]["resolved_conflict_record_ids"]
            rw.require(set(support_resolved) <= all_record_ids and set(exploration_resolved) <= all_record_ids, f"support record {item['support_record_id']} resolves an unknown conflict record")
            if item["claim_support_decision"]["status"] == "promoted":
                rw.require(support_resolved == contradictions, f"support record {item['support_record_id']} must explicitly resolve every contradictory record for claim support on its exact edge/channel")
            else:
                rw.require(not support_resolved, f"support record {item['support_record_id']} cannot resolve claim-support conflicts without promotion")
            if item["exploration_decision"]["status"] == "eligible":
                rw.require(exploration_resolved == contradictions, f"support record {item['support_record_id']} must explicitly resolve every known contradiction before exploration eligibility")
            else:
                rw.require(not exploration_resolved, f"support record {item['support_record_id']} cannot resolve exploration conflicts unless marked eligible")
        statuses = {item["support_status"] for item in items}
        if promoted:
            summary_status = "promoted"
        elif "contradicted" in statuses:
            summary_status = "contradicted"
        elif "conditional" in statuses:
            summary_status = "conditional"
        elif statuses == {"missing"}:
            summary_status = "missing"
        else:
            summary_status = "unsupported"
        summary = {
            "edge_id": key[0], "stereochemical_channel": key[1],
            "support_record_ids": sorted(item["support_record_id"] for item in items),
            "exploration_eligible_record_ids": exploration_eligible,
            "supported_record_ids": promoted,
            "contradictory_support_record_ids": contradictions,
            "claim_support_status": summary_status,
            "hypothesis_exploration_eligible": bool(exploration_eligible),
            "mechanism_claim_supported": bool(promoted),
            "mechanism_claim_validated": False,
        }
        summaries.append(summary)
        if not exploration_eligible:
            blockers.append(rw._blocker(
                f"{key[0]}_exploration_blocked" if len(f"{key[0]}_exploration_blocked") <= 64 else f"support_{rw.sha256_data(key)[:20]}_blocked",
                key[0],
                f"Hypothesis exploration for edge {key[0]} and its exact stereochemical channel is not eligible.",
                ("candidate_construction",),
            ))
    evidence_gaps = [
        {
            "edge_id": record["target"]["edge_id"],
            "stereochemical_channel": record["target"]["stereochemical_channel"],
            "support_record_id": record["support_record_id"],
            "gap": "novel_hypothesis_no_direct_precedent",
            "blocks_exploration": not record["hypothesis_exploration_eligible"],
            "mechanism_claim_supported": False,
        }
        for record in records
        if record["classification"]["evidence_basis"] == "absence_of_direct_precedent"
    ]
    return summaries, rw._sort_blockers(blockers), evidence_gaps


def _normalize_review(
    review: dict[str, Any], mechanism: dict[str, Any], snapshot: dict[str, Any],
    evidence: dict[str, Any], w1: dict[str, tuple[Path, dict[str, Any]]],
) -> tuple[
    list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]],
    list[dict[str, Any]], dict[str, Any],
]:
    _exact(review, REVIEW_KEYS, "mechanism-support review")
    rw.require(review["schema"] == REVIEW_SCHEMA, "unrecognized mechanism-support review schema")
    rw.require(review["study_id"] == mechanism["study_id"] == snapshot["study_id"], "mechanism-support review study_id differs from upstream")
    expected_hashes = {
        "reaction_intake_payload_sha256": w1["reaction_intake"][1]["payload_sha256"],
        "species_registry_payload_sha256": w1["species_registry"][1]["payload_sha256"],
        "condition_model_payload_sha256": w1["condition_model"][1]["payload_sha256"],
        "mechanism_network_payload_sha256": mechanism["payload_sha256"],
        "knowledge_snapshot_payload_sha256": snapshot["payload_sha256"],
        "literature_evidence_payload_sha256": evidence["evidence_review_payload_sha256"],
    }
    for key, expected in expected_hashes.items():
        rw.require(review[key] == expected, f"mechanism-support review {key} mismatch")
    edge_list = mechanism["edges"]
    state_list = mechanism["states"]
    edges = {item["edge_id"]: item for item in edge_list}
    states = {item["state_id"]: item for item in state_list}
    candidates = _candidate_reviews(evidence)
    raw_records = review["records"]
    rw.require(isinstance(raw_records, list) and raw_records, "mechanism-support review records must be a non-empty array")
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_records):
        rw.require(isinstance(raw, dict), f"mechanism-support records[{index}] must be an object")
        record = _normalize_record(raw, edges, states, candidates, f"mechanism-support records[{index}]")
        rw.require(record["support_record_id"] not in seen, f"duplicate support_record_id: {record['support_record_id']}")
        seen.add(record["support_record_id"])
        records.append(record)
    records.sort(key=lambda item: item["support_record_id"])
    summaries, blockers, evidence_gaps = _summarize(records, edges)
    decision = rw._require_string(review["review_decision"], "mechanism-support review_decision")
    rw.require(decision in rw.REVIEW_DECISIONS, "invalid mechanism-support review_decision")
    if decision == "blocked":
        rw.require(
            not any(
                record["hypothesis_exploration_eligible"]
                or record["mechanism_claim_supported"]
                for record in records
            ),
            "a blocked mechanism-support review cannot promote exploration or mechanism-claim support",
        )
    review_meta = {
        "decision": decision,
        "reviewer": rw._require_string(review["reviewer"], "mechanism-support reviewer"),
        "reviewed_at": rw._require_string(review["reviewed_at"], "mechanism-support reviewed_at"),
        "notes": rw._string_list(review["review_notes"], "mechanism-support review_notes"),
    }
    return records, summaries, blockers, evidence_gaps, review_meta


def build(
    mechanism_path: Path, snapshot_path: Path, evidence_path: Path,
    review_path: Path, output: Path,
) -> dict[str, Any]:
    mechanism_path = mechanism_path.absolute()
    snapshot_path = snapshot_path.absolute()
    evidence_path = evidence_path.absolute()
    review_path = review_path.absolute()
    output = output.absolute()
    _require_regular_file(review_path, "mechanism-support review input")
    mechanism, snapshot, evidence, w1 = _load_upstream(mechanism_path, snapshot_path, evidence_path)
    review = rw.load_json(review_path)
    records, summaries, blockers, evidence_gaps, review_meta = _normalize_review(review, mechanism, snapshot, evidence, w1)
    artifact = {
        "schema": OUTPUT_SCHEMA,
        "study_id": mechanism["study_id"],
        "reaction_intake": _input_ref(w1["reaction_intake"][0], w1["reaction_intake"][1]["payload_sha256"]),
        "species_registry": _input_ref(w1["species_registry"][0], w1["species_registry"][1]["payload_sha256"]),
        "condition_model": _input_ref(w1["condition_model"][0], w1["condition_model"][1]["payload_sha256"]),
        "mechanism_network": _input_ref(mechanism_path, mechanism["payload_sha256"]),
        "knowledge_snapshot": _input_ref(snapshot_path, snapshot["payload_sha256"]),
        "literature_evidence": _input_ref(evidence_path, evidence["evidence_review_payload_sha256"]),
        "review_source": rw._artifact_ref(review_path),
        "records": records,
        "edge_channel_summary": summaries,
        "evidence_gaps": evidence_gaps,
        "blockers": blockers,
        "review": review_meta,
        "gate_status": rw._gate_status(review_meta["decision"], blockers),
        "exploration_eligible_edge_channels_present": any(item["hypothesis_exploration_eligible"] for item in summaries),
        "mechanism_claim_support_present": any(item["mechanism_claim_supported"] for item in summaries),
        "mechanism_claim_validation_present": False,
        "calculation_ready": False,
        "no_submission_authorization": True,
    }
    rw.finalize_artifact(artifact)
    rw.write_json(output, artifact)
    return artifact


def validate(path: Path) -> dict[str, Any]:
    artifact = rw.load_json(path)
    keys = {
        "schema", "study_id", "reaction_intake", "species_registry",
        "condition_model", "mechanism_network", "knowledge_snapshot",
        "literature_evidence", "review_source", "records",
        "edge_channel_summary", "evidence_gaps", "blockers", "review", "gate_status",
        "exploration_eligible_edge_channels_present", "mechanism_claim_support_present",
        "mechanism_claim_validation_present", "calculation_ready",
        "no_submission_authorization", "payload_sha256",
    }
    _exact(artifact, keys, "mechanism-support artifact")
    rw.require(artifact["schema"] == OUTPUT_SCHEMA, "unrecognized mechanism-support artifact schema")
    rw.validate_payload_hash(artifact)
    rw.require(artifact["calculation_ready"] is False and artifact["no_submission_authorization"] is True, "mechanism-support artifact violates safety constants")
    mechanism_path, mechanism = _verify_input_ref(artifact["mechanism_network"], path, mn.OUTPUT_SCHEMA, "payload_sha256", "mechanism-support mechanism network")
    snapshot_path, snapshot = _verify_input_ref(artifact["knowledge_snapshot"], path, KNOWLEDGE_SCHEMA, "payload_sha256", "mechanism-support knowledge snapshot")
    evidence_path, evidence = _verify_input_ref(artifact["literature_evidence"], path, LITERATURE_SCHEMA, "evidence_review_payload_sha256", "mechanism-support literature evidence")
    loaded_mechanism, loaded_snapshot, loaded_evidence, w1 = _load_upstream(mechanism_path, snapshot_path, evidence_path)
    rw.require(mechanism == loaded_mechanism and snapshot == loaded_snapshot and evidence == loaded_evidence, "mechanism-support upstream recomputation mismatch")
    for key, schema in (
        ("reaction_intake", rw.INTAKE_SCHEMA),
        ("species_registry", rw.REGISTRY_SCHEMA),
        ("condition_model", rw.CONDITION_SCHEMA),
    ):
        _, bound = _verify_input_ref(artifact[key], path, schema, "payload_sha256", f"mechanism-support {key}")
        rw.require(bound == w1[key][1], f"mechanism-support {key} differs from mechanism-network W1 binding")
    review_ref = _exact(artifact["review_source"], {"path", "sha256", "size_bytes"}, "mechanism-support review_source")
    review_path = _resolve(review_ref, path)
    _require_regular_file(review_path, "mechanism-support review source")
    rw.require(review_ref["sha256"] == rw.sha256_file(review_path) and review_ref["size_bytes"] == review_path.stat().st_size, "mechanism-support review source binding mismatch")
    review = rw.load_json(review_path)
    records, summaries, blockers, evidence_gaps, review_meta = _normalize_review(review, mechanism, snapshot, evidence, w1)
    rw.require(artifact["study_id"] == mechanism["study_id"], "mechanism-support study_id differs from upstream")
    rw.require(artifact["records"] == records, "mechanism-support records differ from immutable review recomputation")
    rw.require(artifact["edge_channel_summary"] == summaries, "mechanism-support edge/channel summaries differ from recomputation")
    rw.require(artifact["evidence_gaps"] == evidence_gaps, "mechanism-support evidence gaps differ from recomputation")
    rw.require(artifact["blockers"] == blockers, "mechanism-support blockers differ from recomputation")
    rw.require(artifact["review"] == review_meta, "mechanism-support review differs from immutable source")
    rw.require(artifact["gate_status"] == rw._gate_status(review_meta["decision"], blockers), "mechanism-support gate_status is inconsistent")
    rw.require(artifact["exploration_eligible_edge_channels_present"] is any(item["hypothesis_exploration_eligible"] for item in summaries), "mechanism-support exploration summary is inconsistent")
    rw.require(artifact["mechanism_claim_support_present"] is any(item["mechanism_claim_supported"] for item in summaries), "mechanism-support claim-support summary is inconsistent")
    rw.require(artifact["mechanism_claim_validation_present"] is False, "mechanism-support cannot claim target-mechanism validation")
    return {
        "schema": "gaussian-reaction-mechanism-support-validation/1",
        "artifact_schema": OUTPUT_SCHEMA, "study_id": artifact["study_id"],
        "gate_status": artifact["gate_status"], "record_count": len(records),
        "exploration_eligible_edge_channel_count": sum(item["hypothesis_exploration_eligible"] for item in summaries),
        "supported_edge_channel_count": sum(item["mechanism_claim_supported"] for item in summaries),
        "payload_sha256": artifact["payload_sha256"], "live_actions": False,
    }


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    build_parser = commands.add_parser("build", help="build one immutable offline mechanism-support artifact")
    build_parser.add_argument("mechanism_network", type=Path)
    build_parser.add_argument("knowledge_snapshot", type=Path)
    build_parser.add_argument("literature_evidence", type=Path)
    build_parser.add_argument("--review", type=Path, required=True)
    build_parser.add_argument("--output", type=Path, required=True)
    validate_parser = commands.add_parser("validate", help="validate and independently recompute one mechanism-support artifact")
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
