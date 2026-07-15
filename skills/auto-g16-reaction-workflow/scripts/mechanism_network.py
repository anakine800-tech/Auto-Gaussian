#!/usr/bin/env python3
"""Build and validate immutable, offline reaction mechanism-network artifacts.

This first W3 slice performs deterministic bookkeeping only.  It never infers
a mechanism or method and never invokes Gaussian, SSH, PBS, deployment, or any
subprocess.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import reaction_workflow as rw


REVIEW_SCHEMA = "gaussian-reaction-mechanism-network-review/1"
OUTPUT_SCHEMA = "gaussian-reaction-mechanism-network/1"
SUPPORT_SCHEMA = "gaussian-reaction-mechanism-support/1"
REVIEW_KEYS = {
    "schema", "study_id", "intake_payload_sha256", "registry_payload_sha256",
    "condition_model_payload_sha256", "states", "edges", "networks",
    "reference_basins", "review_decision", "review_notes",
}
CONNECTION_KINDS = {"covalent", "coordination"}
CONNECTION_ORDERS = {"single", "double", "triple", "aromatic", "unspecified"}


def _exact(data: Any, keys: set[str], label: str) -> dict[str, Any]:
    rw.require(isinstance(data, dict), f"{label} must be an object")
    rw._require_exact_keys(data, keys, keys, label)
    return data


def _unique_ids(items: Any, key: str, label: str) -> dict[str, dict[str, Any]]:
    rw.require(isinstance(items, list) and items, f"{label} must be a non-empty array")
    result: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(items):
        rw.require(isinstance(item, dict), f"{label}[{index}] must be an object")
        item_id = rw._require_id(item.get(key), f"{label}[{index}].{key}")
        rw.require(item_id not in result, f"duplicate {key}: {item_id}")
        result[item_id] = item
    return result


def _derived_id(value: str, suffix: str) -> str:
    candidate = f"{value}_{suffix}"
    if len(candidate) <= 64:
        return candidate
    return f"w3_{rw.sha256_data(candidate)[:20]}_{suffix[:20]}"


def _registry_atom_metadata(registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for species in registry["species"]:
        species_id = species["species_id"]
        identity = species.get("atom_identity", {})
        atoms: dict[str, str] = {}
        for atom in identity.get("atoms", []):
            atom_id = atom.get("atom_id")
            element = atom.get("element")
            if isinstance(atom_id, str) and isinstance(element, str):
                atoms[atom_id] = element
        formula_counts = None
        if isinstance(species.get("formula"), str):
            formula_counts = rw._parse_formula(species["formula"], f"species {species_id}.formula")
        result[species_id] = {
            "atom_scope": identity.get("atom_scope"),
            "atoms": atoms,
            "atom_counts": dict(sorted(Counter(atoms.values()).items())),
            "formula_counts": formula_counts,
        }
    return result


def _normalize_connection(raw: Any, atom_ids: set[str], label: str) -> dict[str, Any]:
    data = _exact(raw, {"atom_ids", "kind", "order"}, label)
    pair = rw._string_list(data["atom_ids"], f"{label}.atom_ids")
    rw.require(len(pair) == 2 and pair[0] != pair[1], f"{label}.atom_ids must contain two distinct atoms")
    rw.require(set(pair) <= atom_ids, f"{label} references an unknown atom")
    kind = rw._require_string(data["kind"], f"{label}.kind")
    order = rw._require_string(data["order"], f"{label}.order")
    rw.require(kind in CONNECTION_KINDS, f"{label}.kind is invalid")
    rw.require(order in CONNECTION_ORDERS, f"{label}.order is invalid")
    if kind == "coordination":
        rw.require(order == "unspecified", f"{label}: coordination order must be unspecified")
    return {"atom_ids": sorted(pair), "kind": kind, "order": order}


def _connection_map(state: dict[str, Any]) -> dict[tuple[str, str, str], str]:
    return {
        (item["atom_ids"][0], item["atom_ids"][1], item["kind"]): item["order"]
        for item in state["connections"]
    }


def _normalize_state(
    raw: dict[str, Any],
    registry_metadata: dict[str, dict[str, Any]],
    condition_decisions: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    keys = {
        "state_id", "label", "state_class", "atoms", "components", "formal_charge",
        "multiplicity", "connections", "connectivity_complete", "stereochemistry",
        "environment_model", "catalyst_projection", "review_status", "blockers", "notes",
    }
    data = _exact(raw, keys, f"state {raw.get('state_id', '?')}")
    state_id = rw._require_id(data["state_id"], "state_id")
    atom_rows = data["atoms"]
    rw.require(isinstance(atom_rows, list) and atom_rows, f"state {state_id}.atoms must be non-empty")
    atoms: list[dict[str, Any]] = []
    atom_ids: set[str] = set()
    elements: dict[str, str] = {}
    atom_keys = {"atom_id", "element", "registry_atom_refs"}
    for index, raw_atom in enumerate(atom_rows):
        atom = _exact(raw_atom, atom_keys, f"state {state_id}.atoms[{index}]")
        atom_id = rw._require_id(atom["atom_id"], f"state {state_id}.atoms[{index}].atom_id")
        rw.require(atom_id not in atom_ids, f"state {state_id} contains duplicate atom_id {atom_id}")
        atom_ids.add(atom_id)
        element = rw._require_string(atom["element"], f"state {state_id} atom {atom_id}.element")
        rw.require(rw.ELEMENT_RE.fullmatch(element) is not None, f"state {state_id} atom {atom_id} has invalid element")
        refs = atom["registry_atom_refs"]
        rw.require(isinstance(refs, list) and refs, f"state {state_id} atom {atom_id} requires registry atom provenance")
        normalized_refs: list[dict[str, str]] = []
        seen_refs: set[tuple[str, str]] = set()
        for ref_index, raw_ref in enumerate(refs):
            ref = _exact(raw_ref, {"species_id", "atom_id"}, f"state {state_id} atom {atom_id} ref {ref_index}")
            species_id = rw._require_id(ref["species_id"], "registry species_id")
            source_atom_id = rw._require_id(ref["atom_id"], "registry atom_id")
            rw.require(species_id in registry_metadata, f"state {state_id} atom {atom_id} references an unknown registry species")
            metadata = registry_metadata[species_id]
            rw.require(metadata["atom_scope"] == "explicit_structure_atoms", f"state {state_id} atom {atom_id} requires registry atom_scope explicit_structure_atoms")
            rw.require(metadata["formula_counts"] is not None and metadata["formula_counts"] == metadata["atom_counts"], f"registry species {species_id} formula and explicit atom inventory differ")
            key = (species_id, source_atom_id)
            rw.require(source_atom_id in metadata["atoms"], f"state {state_id} atom {atom_id} references an unknown registry atom")
            rw.require(metadata["atoms"][source_atom_id] == element, f"state {state_id} atom {atom_id} changes the registry element")
            rw.require(key not in seen_refs, f"state {state_id} atom {atom_id} repeats a registry atom reference")
            seen_refs.add(key)
            normalized_refs.append({"species_id": species_id, "atom_id": source_atom_id})
        elements[atom_id] = element
        atoms.append({"atom_id": atom_id, "element": element, "registry_atom_refs": sorted(normalized_refs, key=lambda item: (item["species_id"], item["atom_id"]))})

    state_source_inventories: dict[str, Counter[str]] = {}
    for atom in atoms:
        for ref in atom["registry_atom_refs"]:
            state_source_inventories.setdefault(ref["species_id"], Counter())[ref["atom_id"]] += 1
    for species_id, observed in state_source_inventories.items():
        expected_atom_ids = set(registry_metadata[species_id]["atoms"])
        rw.require(set(observed) == expected_atom_ids, f"state {state_id} contains a partial registry atom inventory for species {species_id}")
        occurrence_counts = set(observed.values())
        rw.require(len(occurrence_counts) == 1, f"state {state_id} registry atom provenance has inconsistent occurrence counts for species {species_id}")

    components_raw = data["components"]
    rw.require(isinstance(components_raw, list) and components_raw, f"state {state_id}.components must be non-empty")
    components: list[dict[str, Any]] = []
    covered: list[str] = []
    component_ids: set[str] = set()
    component_keys = {"component_id", "label", "atom_ids", "formal_charge", "multiplicity", "registry_species_id", "represented_form"}
    for index, raw_component in enumerate(components_raw):
        component = _exact(raw_component, component_keys, f"state {state_id}.components[{index}]")
        component_id = rw._require_id(component["component_id"], "component_id")
        rw.require(component_id not in component_ids, f"state {state_id} contains duplicate component_id {component_id}")
        component_ids.add(component_id)
        member_ids = rw._string_list(component["atom_ids"], f"component {component_id}.atom_ids", nonempty=True)
        rw.require(len(member_ids) == len(set(member_ids)) and set(member_ids) <= atom_ids, f"component {component_id} atom inventory is invalid")
        charge = component["formal_charge"]
        multiplicity = component["multiplicity"]
        rw.require(isinstance(charge, int) and not isinstance(charge, bool), f"component {component_id}.formal_charge must be integer")
        rw.require(isinstance(multiplicity, int) and not isinstance(multiplicity, bool) and multiplicity > 0, f"component {component_id}.multiplicity must be positive integer")
        registry_species_id = component["registry_species_id"]
        rw.require(registry_species_id is None or isinstance(registry_species_id, str), f"component {component_id}.registry_species_id must be string or null")
        if registry_species_id is not None:
            registry_species_id = rw._require_id(registry_species_id, f"component {component_id}.registry_species_id")
            rw.require(registry_species_id in registry_metadata, f"component {component_id} references an unknown registry species")
            source_atom_ids: list[str] = []
            for atom_id in member_ids:
                matching_refs = [
                    ref["atom_id"]
                    for atom in atoms
                    if atom["atom_id"] == atom_id
                    for ref in atom["registry_atom_refs"]
                    if ref["species_id"] == registry_species_id
                ]
                rw.require(len(matching_refs) == 1, f"component {component_id} atoms must each bind exactly one atom of its registry species")
                source_atom_ids.extend(matching_refs)
            expected_source_atoms = set(registry_metadata[registry_species_id]["atoms"])
            rw.require(len(source_atom_ids) == len(set(source_atom_ids)) and set(source_atom_ids) == expected_source_atoms, f"component {component_id} does not cover the complete registry species atom inventory")
        components.append({
            "component_id": component_id,
            "label": rw._require_string(component["label"], f"component {component_id}.label"),
            "atom_ids": sorted(member_ids),
            "formal_charge": charge,
            "multiplicity": multiplicity,
            "registry_species_id": registry_species_id,
            "represented_form": rw._require_string(component["represented_form"], f"component {component_id}.represented_form"),
        })
        covered.extend(member_ids)
    rw.require(Counter(covered) == Counter(atom_ids), f"state {state_id} components must partition every atom exactly once")
    formal_charge = data["formal_charge"]
    multiplicity = data["multiplicity"]
    rw.require(isinstance(formal_charge, int) and not isinstance(formal_charge, bool), f"state {state_id}.formal_charge must be integer")
    rw.require(sum(item["formal_charge"] for item in components) == formal_charge, f"state {state_id} component charges do not sum to the state charge")
    rw.require(isinstance(multiplicity, int) and not isinstance(multiplicity, bool) and multiplicity > 0, f"state {state_id}.multiplicity must be positive integer")
    rw.require(data["connectivity_complete"] is True, f"state {state_id} must explicitly assert connectivity_complete: true")
    connections = [_normalize_connection(item, atom_ids, f"state {state_id}.connections[{index}]") for index, item in enumerate(data["connections"])]
    connection_keys = [(item["atom_ids"][0], item["atom_ids"][1], item["kind"]) for item in connections]
    rw.require(len(connection_keys) == len(set(connection_keys)), f"state {state_id} contains duplicate connections")

    stereo = _exact(data["stereochemistry"], {"status", "assignments", "notes"}, f"state {state_id}.stereochemistry")
    stereo_status = rw._require_string(stereo["status"], f"state {state_id}.stereochemistry.status")
    rw.require(stereo_status in {"reviewed", "not_applicable", "blocked"}, f"state {state_id}.stereochemistry.status is invalid")
    rw.require(isinstance(stereo["assignments"], list), f"state {state_id}.stereochemistry.assignments must be an array")
    stereo_assignments: list[dict[str, Any]] = []
    assignment_ids: set[str] = set()
    for index, raw_assignment in enumerate(stereo["assignments"]):
        assignment = _exact(raw_assignment, {"assignment_id", "atom_ids", "descriptor", "review_status", "rationale"}, f"state {state_id}.stereochemistry.assignments[{index}]")
        assignment_id = rw._require_id(assignment["assignment_id"], f"state {state_id} stereochemistry assignment_id")
        rw.require(assignment_id not in assignment_ids, f"state {state_id} repeats stereochemistry assignment_id {assignment_id}")
        assignment_ids.add(assignment_id)
        assignment_atoms = rw._string_list(assignment["atom_ids"], f"state {state_id} stereochemistry assignment {assignment_id}.atom_ids", nonempty=True)
        rw.require(len(assignment_atoms) == len(set(assignment_atoms)) and set(assignment_atoms) <= atom_ids, f"state {state_id} stereochemistry assignment {assignment_id} atom inventory is invalid")
        assignment_status = rw._require_string(assignment["review_status"], f"state {state_id} stereochemistry assignment {assignment_id}.review_status")
        rw.require(assignment_status in {"reviewed", "blocked"}, f"state {state_id} stereochemistry assignment {assignment_id}.review_status is invalid")
        stereo_assignments.append({
            "assignment_id": assignment_id,
            "atom_ids": sorted(assignment_atoms),
            "descriptor": rw._require_string(assignment["descriptor"], f"state {state_id} stereochemistry assignment {assignment_id}.descriptor"),
            "review_status": assignment_status,
            "rationale": rw._require_string(assignment["rationale"], f"state {state_id} stereochemistry assignment {assignment_id}.rationale"),
        })
    environment = _exact(data["environment_model"], {"condition_decision_ids", "additional_terms", "review_status", "rationale"}, f"state {state_id}.environment_model")
    state_conditions = rw._string_list(environment["condition_decision_ids"], f"state {state_id}.environment_model.condition_decision_ids")
    rw.require(set(state_conditions) <= set(condition_decisions), f"state {state_id} references unknown condition decisions")
    represented_species = set(state_source_inventories)
    for condition_id in state_conditions:
        condition_decision = condition_decisions[condition_id]
        if condition_decision["treatment"] == "explicit_component":
            missing_species = set(condition_decision["species_ids"]) - represented_species
            rw.require(
                not missing_species,
                f"state {state_id} references explicit condition {condition_id} but omits species: {', '.join(sorted(missing_species))}",
            )
    for condition_id, condition_decision in condition_decisions.items():
        if condition_decision["treatment"] == "explicit_component" and represented_species & set(condition_decision["species_ids"]):
            rw.require(
                condition_id in state_conditions,
                f"state {state_id} contains species from explicit condition {condition_id} without binding that condition decision",
            )
    additional_terms = rw._string_list(environment["additional_terms"], f"state {state_id}.environment_model.additional_terms")
    environment_status = rw._require_string(environment["review_status"], f"state {state_id}.environment_model.review_status")
    rw.require(environment_status in {"reviewed", "blocked"}, f"state {state_id}.environment_model.review_status is invalid")

    projection = data["catalyst_projection"]
    normalized_projection = None
    if projection is not None:
        projection = _exact(projection, {"status", "catalyst_atom_ids", "formal_charge", "multiplicity", "oxidation_state", "ligand_environment", "protonation_state", "notes"}, f"state {state_id}.catalyst_projection")
        catalyst_atoms = rw._string_list(projection["catalyst_atom_ids"], f"state {state_id}.catalyst_projection.catalyst_atom_ids", nonempty=True)
        rw.require(len(catalyst_atoms) == len(set(catalyst_atoms)) and set(catalyst_atoms) <= atom_ids, f"state {state_id} catalyst projection atom inventory is invalid")
        normalized_projection = {
            "status": rw._require_string(projection["status"], f"state {state_id}.catalyst_projection.status"),
            "catalyst_atom_ids": sorted(catalyst_atoms),
            "formal_charge": projection["formal_charge"],
            "multiplicity": projection["multiplicity"],
            "oxidation_state": rw._require_string(projection["oxidation_state"], f"state {state_id}.catalyst_projection.oxidation_state"),
            "ligand_environment": sorted(rw._string_list(projection["ligand_environment"], f"state {state_id}.catalyst_projection.ligand_environment")),
            "protonation_state": rw._require_string(projection["protonation_state"], f"state {state_id}.catalyst_projection.protonation_state"),
            "notes": rw._string_list(projection["notes"], f"state {state_id}.catalyst_projection.notes"),
        }
        rw.require(normalized_projection["status"] == "reviewed", f"state {state_id} catalyst projection must be reviewed")
        rw.require(isinstance(normalized_projection["formal_charge"], int) and not isinstance(normalized_projection["formal_charge"], bool), f"state {state_id} catalyst projection charge must be integer")
        rw.require(isinstance(normalized_projection["multiplicity"], int) and normalized_projection["multiplicity"] > 0, f"state {state_id} catalyst projection multiplicity must be positive integer")

    review_status = rw._require_string(data["review_status"], f"state {state_id}.review_status")
    rw.require(review_status in {"reviewed_hypothesis", "blocked"}, f"state {state_id}.review_status is invalid")
    return {
        "state_id": state_id,
        "label": rw._require_string(data["label"], f"state {state_id}.label"),
        "state_class": rw._require_string(data["state_class"], f"state {state_id}.state_class"),
        "atoms": sorted(atoms, key=lambda item: item["atom_id"]),
        "components": sorted(components, key=lambda item: item["component_id"]),
        "formal_charge": formal_charge,
        "multiplicity": multiplicity,
        "connections": sorted(connections, key=lambda item: (item["atom_ids"], item["kind"], item["order"])),
        "connectivity_complete": True,
        "stereochemistry": {"status": stereo_status, "assignments": sorted(stereo_assignments, key=lambda item: item["assignment_id"]), "notes": rw._string_list(stereo["notes"], f"state {state_id}.stereochemistry.notes")},
        "environment_model": {"condition_decision_ids": sorted(set(state_conditions)), "additional_terms": sorted(set(additional_terms)), "review_status": environment_status, "rationale": rw._require_string(environment["rationale"], f"state {state_id}.environment_model.rationale")},
        "catalyst_projection": normalized_projection,
        "review_status": review_status,
        "blockers": rw._string_list(data["blockers"], f"state {state_id}.blockers"),
        "notes": rw._string_list(data["notes"], f"state {state_id}.notes"),
        "_elements": elements,
    }


def _state_counts(state: dict[str, Any]) -> dict[str, int]:
    return dict(sorted(Counter(state["_elements"].values()).items()))


def _normalize_edge(raw: dict[str, Any], states: dict[str, dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    keys = {"edge_id", "label", "from_state_id", "to_state_id", "atom_mapping", "connection_changes", "transfers", "molecularity", "reversibility", "state_changes", "stereochemical_channel", "support_claim_ids", "review_status", "blockers", "notes"}
    data = _exact(raw, keys, f"edge {raw.get('edge_id', '?')}")
    edge_id = rw._require_id(data["edge_id"], "edge_id")
    from_id = rw._require_id(data["from_state_id"], f"edge {edge_id}.from_state_id")
    to_id = rw._require_id(data["to_state_id"], f"edge {edge_id}.to_state_id")
    rw.require(from_id in states and to_id in states and from_id != to_id, f"edge {edge_id} state references are invalid")
    source = states[from_id]
    target = states[to_id]
    mappings_raw = data["atom_mapping"]
    rw.require(isinstance(mappings_raw, list) and mappings_raw, f"edge {edge_id}.atom_mapping must be non-empty")
    mappings: list[dict[str, str]] = []
    forward: dict[str, str] = {}
    reverse: dict[str, str] = {}
    for index, raw_mapping in enumerate(mappings_raw):
        mapping = _exact(raw_mapping, {"from_atom_id", "to_atom_id"}, f"edge {edge_id}.atom_mapping[{index}]")
        from_atom = rw._require_id(mapping["from_atom_id"], f"edge {edge_id} from_atom_id")
        to_atom = rw._require_id(mapping["to_atom_id"], f"edge {edge_id} to_atom_id")
        rw.require(from_atom in source["_elements"] and to_atom in target["_elements"], f"edge {edge_id} atom mapping references an unknown atom")
        rw.require(from_atom not in forward and to_atom not in reverse, f"edge {edge_id} atom mapping must be one-to-one")
        rw.require(source["_elements"][from_atom] == target["_elements"][to_atom], f"edge {edge_id} atom mapping changes element identity")
        forward[from_atom] = to_atom
        reverse[to_atom] = from_atom
        mappings.append({"from_atom_id": from_atom, "to_atom_id": to_atom})
    rw.require(set(forward) == set(source["_elements"]) and set(reverse) == set(target["_elements"]), f"edge {edge_id} atom mapping must cover both state atom inventories exactly")

    source_connections = _connection_map(source)
    target_connections: dict[tuple[str, str, str], str] = {}
    for (atom_a, atom_b, kind), order in _connection_map(target).items():
        pair = sorted((reverse[atom_a], reverse[atom_b]))
        target_connections[(pair[0], pair[1], kind)] = order
    changed_keys = sorted(set(source_connections) | set(target_connections))
    computed_changes = [
        {"atom_ids": [key[0], key[1]], "kind": key[2], "before_order": source_connections.get(key), "after_order": target_connections.get(key)}
        for key in changed_keys if source_connections.get(key) != target_connections.get(key)
    ]
    declared_changes: list[dict[str, Any]] = []
    for index, raw_change in enumerate(data["connection_changes"]):
        change = _exact(raw_change, {"atom_ids", "kind", "before_order", "after_order"}, f"edge {edge_id}.connection_changes[{index}]")
        pair = rw._string_list(change["atom_ids"], f"edge {edge_id} connection change atom_ids")
        rw.require(len(pair) == 2 and pair[0] != pair[1] and set(pair) <= set(source["_elements"]), f"edge {edge_id} connection change atom_ids are invalid")
        kind = rw._require_string(change["kind"], f"edge {edge_id} connection change kind")
        rw.require(kind in CONNECTION_KINDS, f"edge {edge_id} connection change kind is invalid")
        before_order = change["before_order"]
        after_order = change["after_order"]
        rw.require(before_order is None or before_order in CONNECTION_ORDERS, f"edge {edge_id} before_order is invalid")
        rw.require(after_order is None or after_order in CONNECTION_ORDERS, f"edge {edge_id} after_order is invalid")
        rw.require(before_order != after_order and (before_order is not None or after_order is not None), f"edge {edge_id} declares a no-op connection change")
        declared_changes.append({"atom_ids": sorted(pair), "kind": kind, "before_order": before_order, "after_order": after_order})
    declared_changes.sort(key=lambda item: (item["atom_ids"], item["kind"], str(item["before_order"]), str(item["after_order"])))
    computed_changes.sort(key=lambda item: (item["atom_ids"], item["kind"], str(item["before_order"]), str(item["after_order"])))
    rw.require(declared_changes == computed_changes, f"edge {edge_id} declared connection changes do not match the mapped state connectivity difference")

    transfers: list[dict[str, str]] = []
    for index, raw_transfer in enumerate(data["transfers"]):
        transfer = _exact(raw_transfer, {"atom_id", "donor_atom_id", "acceptor_atom_id"}, f"edge {edge_id}.transfers[{index}]")
        atom_id = rw._require_id(transfer["atom_id"], f"edge {edge_id} transfer atom")
        donor = rw._require_id(transfer["donor_atom_id"], f"edge {edge_id} transfer donor")
        acceptor = rw._require_id(transfer["acceptor_atom_id"], f"edge {edge_id} transfer acceptor")
        rw.require({atom_id, donor, acceptor} <= set(source["_elements"]) and len({atom_id, donor, acceptor}) == 3, f"edge {edge_id} transfer atoms are invalid")
        breaking = any(set(item["atom_ids"]) == {atom_id, donor} and item["before_order"] is not None and item["after_order"] is None for item in computed_changes)
        forming = any(set(item["atom_ids"]) == {atom_id, acceptor} and item["before_order"] is None and item["after_order"] is not None for item in computed_changes)
        rw.require(breaking and forming, f"edge {edge_id} transfer is inconsistent with breaking/forming connectivity")
        transfers.append({"atom_id": atom_id, "donor_atom_id": donor, "acceptor_atom_id": acceptor})

    support_claim_ids = rw._string_list(data["support_claim_ids"], f"edge {edge_id}.support_claim_ids")
    rw.require(not support_claim_ids, f"edge {edge_id} cannot cite child mechanism-support claims inside its upstream network artifact; bind {SUPPORT_SCHEMA} separately")
    state_changes = _exact(data["state_changes"], {"oxidation_state", "spin", "ligand", "coordination", "protonation"}, f"edge {edge_id}.state_changes")
    normalized_state_changes = {key: rw._require_string(state_changes[key], f"edge {edge_id}.state_changes.{key}") for key in sorted(state_changes)}
    review_status = rw._require_string(data["review_status"], f"edge {edge_id}.review_status")
    rw.require(review_status in {"reviewed_hypothesis", "blocked"}, f"edge {edge_id}.review_status is invalid")
    normalized = {
        "edge_id": edge_id,
        "label": rw._require_string(data["label"], f"edge {edge_id}.label"),
        "from_state_id": from_id,
        "to_state_id": to_id,
        "atom_mapping": sorted(mappings, key=lambda item: item["from_atom_id"]),
        "connection_changes": declared_changes,
        "transfers": sorted(transfers, key=lambda item: (item["atom_id"], item["donor_atom_id"], item["acceptor_atom_id"])),
        "molecularity": rw._positive_integer(data["molecularity"], f"edge {edge_id}.molecularity"),
        "reversibility": rw._require_string(data["reversibility"], f"edge {edge_id}.reversibility"),
        "state_changes": normalized_state_changes,
        "stereochemical_channel": data["stereochemical_channel"],
        "support_claim_ids": [],
        "review_status": review_status,
        "blockers": rw._string_list(data["blockers"], f"edge {edge_id}.blockers"),
        "notes": rw._string_list(data["notes"], f"edge {edge_id}.notes"),
        "_mapping": forward,
    }
    rw.require(normalized["reversibility"] in {"reversible", "irreversible", "unresolved"}, f"edge {edge_id}.reversibility is invalid")
    rw.require(normalized["stereochemical_channel"] is None or isinstance(normalized["stereochemical_channel"], str), f"edge {edge_id}.stereochemical_channel must be string or null")
    element_delta = {element: _state_counts(target).get(element, 0) - _state_counts(source).get(element, 0) for element in sorted(set(_state_counts(source)) | set(_state_counts(target)))}
    element_delta = {key: value for key, value in element_delta.items() if value}
    diagnostic = {
        "edge_id": edge_id,
        "atom_mapping_complete": True,
        "element_delta_product_minus_reactant": element_delta,
        "charge_delta_product_minus_reactant": target["formal_charge"] - source["formal_charge"],
        "elements_conserved": not element_delta,
        "charge_conserved": target["formal_charge"] == source["formal_charge"],
        "connection_changes_consistent": True,
    }
    return normalized, diagnostic


def _projection_descriptor(projection: dict[str, Any]) -> dict[str, Any]:
    return {key: copy.deepcopy(projection[key]) for key in ("formal_charge", "multiplicity", "oxidation_state", "ligand_environment", "protonation_state")}


def _normalize_network(raw: dict[str, Any], states: dict[str, dict[str, Any]], edges: dict[str, dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    keys = {"network_id", "label", "role", "state_ids", "edge_ids", "entry_state_id", "exit_state_id", "catalyst_cycle", "disposition", "review_status", "blockers", "notes"}
    data = _exact(raw, keys, f"network {raw.get('network_id', '?')}")
    network_id = rw._require_id(data["network_id"], "network_id")
    state_ids = rw._string_list(data["state_ids"], f"network {network_id}.state_ids", nonempty=True)
    edge_ids = rw._string_list(data["edge_ids"], f"network {network_id}.edge_ids", nonempty=True)
    rw.require(len(state_ids) == len(set(state_ids)) and set(state_ids) <= set(states), f"network {network_id} state inventory is invalid")
    rw.require(len(edge_ids) == len(set(edge_ids)) and set(edge_ids) <= set(edges), f"network {network_id} edge inventory is invalid")
    for edge_id in edge_ids:
        rw.require({edges[edge_id]["from_state_id"], edges[edge_id]["to_state_id"]} <= set(state_ids), f"network {network_id} edge {edge_id} escapes its state inventory")
    entry = rw._require_id(data["entry_state_id"], f"network {network_id}.entry_state_id")
    exit_state = rw._require_id(data["exit_state_id"], f"network {network_id}.exit_state_id")
    rw.require(entry in state_ids and exit_state in state_ids, f"network {network_id} entry/exit state is invalid")
    role = rw._require_string(data["role"], f"network {network_id}.role")
    rw.require(role in {"primary", "competing"}, f"network {network_id}.role is invalid")
    cycle = _exact(data["catalyst_cycle"], {"required", "start_state_id", "regenerated_state_id", "closure_edge_ids", "review_status", "rationale"}, f"network {network_id}.catalyst_cycle")
    rw.require(type(cycle["required"]) is bool, f"network {network_id}.catalyst_cycle.required must be boolean")
    if cycle["required"]:
        start_id = rw._require_id(cycle["start_state_id"], f"network {network_id} catalyst start")
        regenerated_id = rw._require_id(cycle["regenerated_state_id"], f"network {network_id} catalyst regenerated state")
        closure_edge_ids = rw._string_list(cycle["closure_edge_ids"], f"network {network_id}.catalyst_cycle.closure_edge_ids", nonempty=True)
        rw.require(set(closure_edge_ids) <= set(edge_ids), f"network {network_id} closure path uses an edge outside the network")
        current_state = start_id
        mapped_atoms: dict[str, str] | None = None
        for position, edge_id in enumerate(closure_edge_ids):
            edge = edges[edge_id]
            rw.require(edge["from_state_id"] == current_state, f"network {network_id} catalyst closure edges are not a contiguous directed path")
            if position == 0:
                mapped_atoms = dict(edge["_mapping"])
            else:
                assert mapped_atoms is not None
                mapped_atoms = {origin: edge["_mapping"][current] for origin, current in mapped_atoms.items()}
            current_state = edge["to_state_id"]
        rw.require(current_state == regenerated_id, f"network {network_id} catalyst closure path does not end at regenerated_state_id")
        start_projection = states[start_id]["catalyst_projection"]
        end_projection = states[regenerated_id]["catalyst_projection"]
        rw.require(start_projection is not None and end_projection is not None, f"network {network_id} catalyst closure requires reviewed endpoint projections")
        assert mapped_atoms is not None
        mapped_catalyst_atoms = {mapped_atoms[atom_id] for atom_id in start_projection["catalyst_atom_ids"]}
        atom_projection_closed = mapped_catalyst_atoms == set(end_projection["catalyst_atom_ids"])
        descriptor_equivalent = _projection_descriptor(start_projection) == _projection_descriptor(end_projection)
        start_internal = _connection_map(states[start_id])
        end_internal = _connection_map(states[regenerated_id])
        projected_start_connections = {
            (tuple(sorted((mapped_atoms[key[0]], mapped_atoms[key[1]]))), key[2], order)
            for key, order in start_internal.items()
            if key[0] in start_projection["catalyst_atom_ids"] or key[1] in start_projection["catalyst_atom_ids"]
        }
        projected_end_connections = {
            ((key[0], key[1]), key[2], order)
            for key, order in end_internal.items()
            if key[0] in end_projection["catalyst_atom_ids"] or key[1] in end_projection["catalyst_atom_ids"]
        }
        connectivity_equivalent = projected_start_connections == projected_end_connections
        closed = atom_projection_closed and descriptor_equivalent and connectivity_equivalent
        rw.require(closed, f"network {network_id} catalyst projection does not close")
        cycle_status = rw._require_string(cycle["review_status"], f"network {network_id}.catalyst_cycle.review_status")
        rw.require(cycle_status == "reviewed", f"network {network_id} catalyst cycle must be reviewed")
        diagnostic_status = "reviewed_closed"
        closure_path_valid: bool | None = True
    else:
        rw.require(cycle["start_state_id"] is None and cycle["regenerated_state_id"] is None, f"network {network_id} noncatalytic cycle must use null endpoint states")
        closure_edge_ids = rw._string_list(cycle["closure_edge_ids"], f"network {network_id}.catalyst_cycle.closure_edge_ids")
        rw.require(not closure_edge_ids, f"network {network_id} noncatalytic cycle must not list closure edges")
        cycle_status = rw._require_string(cycle["review_status"], f"network {network_id}.catalyst_cycle.review_status")
        rw.require(cycle_status == "not_applicable", f"network {network_id} noncatalytic cycle review_status must be not_applicable")
        rw.require(all(states[state_id]["catalyst_projection"] is None for state_id in state_ids), f"network {network_id} cannot mark catalyst closure not applicable while retaining catalyst projections")
        start_id = None
        regenerated_id = None
        atom_projection_closed = None
        descriptor_equivalent = None
        connectivity_equivalent = None
        closed = None
        diagnostic_status = "not_applicable"
        closure_path_valid = None
    review_status = rw._require_string(data["review_status"], f"network {network_id}.review_status")
    rw.require(review_status in {"reviewed_hypothesis", "blocked"}, f"network {network_id}.review_status is invalid")
    disposition = rw._require_string(data["disposition"], f"network {network_id}.disposition")
    rw.require(disposition in {"included_hypothesis", "competing_hypothesis", "excluded", "unresolved"}, f"network {network_id}.disposition is invalid")
    normalized = {
        "network_id": network_id,
        "label": rw._require_string(data["label"], f"network {network_id}.label"),
        "role": role,
        "state_ids": sorted(state_ids),
        "edge_ids": sorted(edge_ids),
        "entry_state_id": entry,
        "exit_state_id": exit_state,
        "catalyst_cycle": {"required": cycle["required"], "start_state_id": start_id, "regenerated_state_id": regenerated_id, "closure_edge_ids": closure_edge_ids, "review_status": cycle_status, "rationale": rw._require_string(cycle["rationale"], f"network {network_id}.catalyst_cycle.rationale")},
        "disposition": disposition,
        "review_status": review_status,
        "blockers": rw._string_list(data["blockers"], f"network {network_id}.blockers"),
        "notes": rw._string_list(data["notes"], f"network {network_id}.notes"),
    }
    diagnostic = {
        "network_id": network_id,
        "catalyst_cycle_required": cycle["required"],
        "diagnostic_status": diagnostic_status,
        "closure_path_valid": closure_path_valid,
        "catalyst_atom_projection_closed": atom_projection_closed,
        "catalyst_descriptor_equivalent": descriptor_equivalent,
        "catalyst_connectivity_equivalent": connectivity_equivalent,
        "catalyst_cycle_closed": closed,
    }
    return normalized, diagnostic


def _normalize_basin(raw: dict[str, Any], states: dict[str, dict[str, Any]], edges: dict[str, dict[str, Any]], networks: dict[str, dict[str, Any]], condition_ids: set[str]) -> tuple[dict[str, Any], dict[str, Any]]:
    keys = {"basin_id", "label", "network_ids", "edge_ids", "reference_state_id", "reference_type", "condition_decision_ids", "aggregation_model", "equilibration_assumptions", "symmetry_degeneracy_policy", "review_status", "blockers", "notes"}
    data = _exact(raw, keys, f"reference basin {raw.get('basin_id', '?')}")
    basin_id = rw._require_id(data["basin_id"], "basin_id")
    network_ids = rw._string_list(data["network_ids"], f"basin {basin_id}.network_ids", nonempty=True)
    edge_ids = rw._string_list(data["edge_ids"], f"basin {basin_id}.edge_ids", nonempty=True)
    rw.require(len(network_ids) == len(set(network_ids)) and set(network_ids) <= set(networks), f"basin {basin_id} network inventory is invalid")
    rw.require(len(edge_ids) == len(set(edge_ids)) and set(edge_ids) <= set(edges), f"basin {basin_id} edge inventory is invalid")
    for edge_id in edge_ids:
        rw.require(any(edge_id in networks[network_id]["edge_ids"] for network_id in network_ids), f"basin {basin_id} edge {edge_id} is absent from its declared networks")
    reference_state_id = rw._require_id(data["reference_state_id"], f"basin {basin_id}.reference_state_id")
    rw.require(reference_state_id in states, f"basin {basin_id} references an unknown state")
    basin_conditions = rw._string_list(data["condition_decision_ids"], f"basin {basin_id}.condition_decision_ids")
    rw.require(set(basin_conditions) <= condition_ids, f"basin {basin_id} references unknown condition decisions")
    reference = states[reference_state_id]
    per_edge: list[dict[str, Any]] = []
    common_inventory = True
    common_charge = True
    for edge_id in sorted(edge_ids):
        source = states[edges[edge_id]["from_state_id"]]
        inventory_match = _state_counts(reference) == _state_counts(source)
        charge_match = reference["formal_charge"] == source["formal_charge"]
        common_inventory &= inventory_match
        common_charge &= charge_match
        per_edge.append({"edge_id": edge_id, "element_inventory_matches_reference": inventory_match, "charge_matches_reference": charge_match})
    review_status = rw._require_string(data["review_status"], f"basin {basin_id}.review_status")
    rw.require(review_status in {"reviewed", "blocked"}, f"basin {basin_id}.review_status is invalid")
    reference_type = rw._require_string(data["reference_type"], f"basin {basin_id}.reference_type")
    rw.require(reference_type in {"separated_species", "pre_reactive_complex", "balanced_thermodynamic_cycle"}, f"basin {basin_id}.reference_type is invalid")
    normalized = {
        "basin_id": basin_id,
        "label": rw._require_string(data["label"], f"basin {basin_id}.label"),
        "network_ids": sorted(network_ids),
        "edge_ids": sorted(edge_ids),
        "reference_state_id": reference_state_id,
        "reference_type": reference_type,
        "condition_decision_ids": sorted(set(basin_conditions)),
        "aggregation_model": rw._require_string(data["aggregation_model"], f"basin {basin_id}.aggregation_model"),
        "equilibration_assumptions": sorted(rw._string_list(data["equilibration_assumptions"], f"basin {basin_id}.equilibration_assumptions", nonempty=True)),
        "symmetry_degeneracy_policy": rw._require_string(data["symmetry_degeneracy_policy"], f"basin {basin_id}.symmetry_degeneracy_policy"),
        "review_status": review_status,
        "blockers": rw._string_list(data["blockers"], f"basin {basin_id}.blockers"),
        "notes": rw._string_list(data["notes"], f"basin {basin_id}.notes"),
    }
    diagnostic = {"basin_id": basin_id, "common_element_inventory": common_inventory, "common_charge": common_charge, "edge_comparisons": per_edge}
    return normalized, diagnostic


def _strip_private(item: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in item.items() if not key.startswith("_")}


def _analyze(raw_states: Any, raw_edges: Any, raw_networks: Any, raw_basins: Any, registry: dict[str, Any], condition: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    registry_metadata = _registry_atom_metadata(registry)
    condition_decisions = {item["condition_id"]: item for item in condition["decisions"]}
    condition_ids = set(condition_decisions)
    state_inputs = _unique_ids(raw_states, "state_id", "states")
    states = {
        state_id: _normalize_state(raw, registry_metadata, condition_decisions)
        for state_id, raw in state_inputs.items()
    }
    edge_inputs = _unique_ids(raw_edges, "edge_id", "edges")
    edges: dict[str, dict[str, Any]] = {}
    edge_diagnostics: list[dict[str, Any]] = []
    for edge_id, raw in edge_inputs.items():
        normalized, diagnostic = _normalize_edge(raw, states)
        edges[edge_id] = normalized
        edge_diagnostics.append(diagnostic)
    network_inputs = _unique_ids(raw_networks, "network_id", "networks")
    networks: dict[str, dict[str, Any]] = {}
    network_diagnostics: list[dict[str, Any]] = []
    for network_id, raw in network_inputs.items():
        normalized, diagnostic = _normalize_network(raw, states, edges)
        networks[network_id] = normalized
        network_diagnostics.append(diagnostic)
    roles = {item["role"] for item in networks.values()}
    rw.require({"primary", "competing"} <= roles, "mechanism review must retain both a primary and a competing network hypothesis")
    basin_inputs = _unique_ids(raw_basins, "basin_id", "reference_basins")
    basins: dict[str, dict[str, Any]] = {}
    basin_diagnostics: list[dict[str, Any]] = []
    for basin_id, raw in basin_inputs.items():
        normalized, diagnostic = _normalize_basin(raw, states, edges, networks, condition_ids)
        basins[basin_id] = normalized
        basin_diagnostics.append(diagnostic)
    covered_edges = [edge_id for basin in basins.values() for edge_id in basin["edge_ids"]]
    rw.require(Counter(covered_edges) == Counter(edges.keys()), "every edge must belong to exactly one reference basin")

    blockers = [rw._blocker("mechanism_support_unavailable", "study", f"The upstream network has no child {SUPPORT_SCHEMA} binding; all networks remain hypotheses until a separately hash-bound support artifact is reviewed.", ("mechanism_promotion", "calculation_dag", "ts_seed_construction"))]
    for collection, kind in ((states, "state"), (edges, "edge"), (networks, "network"), (basins, "basin")):
        for item_id, item in collection.items():
            if item["review_status"] in {"blocked"} or item.get("blockers"):
                blockers.append(rw._blocker(_derived_id(item_id, "review_blocked"), item_id, f"{kind.capitalize()} review remains blocked: " + "; ".join(item.get("blockers") or [item["review_status"]]), ("mechanism_promotion", "calculation_dag")))
    for diagnostic in edge_diagnostics:
        if not diagnostic["elements_conserved"]:
            blockers.append(rw._blocker(_derived_id(diagnostic["edge_id"], "element_balance"), diagnostic["edge_id"], "Elementary edge does not conserve the explicit element inventory.", ("mechanism_promotion", "reference_basin")))
        if not diagnostic["charge_conserved"]:
            blockers.append(rw._blocker(_derived_id(diagnostic["edge_id"], "charge_balance"), diagnostic["edge_id"], "Elementary edge does not conserve explicit formal charge; missing charged species or electron bookkeeping remains unresolved.", ("mechanism_promotion", "reference_basin")))
    for diagnostic in basin_diagnostics:
        if not diagnostic["common_element_inventory"] or not diagnostic["common_charge"]:
            blockers.append(rw._blocker(_derived_id(diagnostic["basin_id"], "reference_mismatch"), diagnostic["basin_id"], "Reference basin and one or more compared edges lack a common element/charge inventory.", ("barrier_comparison", "calculation_dag")))
    diagnostics = {
        "edge_conservation_and_connectivity": sorted(edge_diagnostics, key=lambda item: item["edge_id"]),
        "network_catalyst_projection_closure": sorted(network_diagnostics, key=lambda item: item["network_id"]),
        "reference_basin_consistency": sorted(basin_diagnostics, key=lambda item: item["basin_id"]),
    }
    return (
        [_strip_private(states[key]) for key in sorted(states)],
        [_strip_private(edges[key]) for key in sorted(edges)],
        [_strip_private(networks[key]) for key in sorted(networks)],
        [_strip_private(basins[key]) for key in sorted(basins)],
        diagnostics,
        rw._sort_blockers(blockers),
    )


def _load_chain(intake_path: Path, registry_path: Path, condition_path: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    for path in (intake_path, registry_path, condition_path):
        rw.validate_artifact(path)
    intake = rw.load_json(intake_path)
    registry = rw.load_json(registry_path)
    condition = rw.load_json(condition_path)
    rw.require(intake["study_id"] == registry["study_id"] == condition["study_id"], "upstream study IDs differ")
    rw.require(registry["intake"]["payload_sha256"] == intake["payload_sha256"], "registry is not bound to the supplied intake")
    rw.require(condition["intake"]["payload_sha256"] == intake["payload_sha256"], "condition model is not bound to the supplied intake")
    rw.require(condition["species_registry"]["payload_sha256"] == registry["payload_sha256"], "condition model is not bound to the supplied registry")
    return intake, registry, condition


def _normalize_review(
    review: dict[str, Any],
    intake: dict[str, Any],
    registry: dict[str, Any],
    condition: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any], list[dict[str, Any]], str, list[str]]:
    _exact(review, REVIEW_KEYS, "mechanism-network review")
    rw.require(review["schema"] == REVIEW_SCHEMA, "unrecognized mechanism-network review schema")
    rw.require(review["study_id"] == intake["study_id"], "mechanism-network review study_id differs from upstream")
    rw.require(review["intake_payload_sha256"] == intake["payload_sha256"], "mechanism-network review intake hash mismatch")
    rw.require(review["registry_payload_sha256"] == registry["payload_sha256"], "mechanism-network review registry hash mismatch")
    rw.require(review["condition_model_payload_sha256"] == condition["payload_sha256"], "mechanism-network review condition-model hash mismatch")
    decision = rw._require_string(review["review_decision"], "mechanism-network review_decision")
    rw.require(decision in rw.REVIEW_DECISIONS, "invalid mechanism-network review_decision")
    states, edges, networks, basins, diagnostics, blockers = _analyze(review["states"], review["edges"], review["networks"], review["reference_basins"], registry, condition)
    for label, upstream in (("intake", intake), ("registry", registry), ("condition_model", condition)):
        if upstream["gate_status"] != "reviewed":
            blockers.append(rw._blocker(_derived_id(f"upstream_{label}", "gate"), label, f"Upstream {label} gate is {upstream['gate_status']}.", ("mechanism_promotion", "calculation_dag")))
    return states, edges, networks, basins, diagnostics, rw._sort_blockers(blockers), decision, rw._string_list(review["review_notes"], "mechanism-network review_notes")


def _referenced_path(reference: dict[str, Any], owner_path: Path) -> Path:
    path = Path(reference["path"])
    return path if path.is_absolute() else owner_path.parent / path


def build(intake_path: Path, registry_path: Path, condition_path: Path, review_path: Path, output: Path) -> dict[str, Any]:
    intake_path = intake_path.absolute()
    registry_path = registry_path.absolute()
    condition_path = condition_path.absolute()
    review_path = review_path.absolute()
    output = output.absolute()
    intake, registry, condition = _load_chain(intake_path, registry_path, condition_path)
    review = rw.load_json(review_path)
    states, edges, networks, basins, diagnostics, blockers, decision, review_notes = _normalize_review(review, intake, registry, condition)
    artifact = {
        "schema": OUTPUT_SCHEMA,
        "study_id": intake["study_id"],
        "intake": rw._artifact_input_ref(intake_path, intake),
        "species_registry": rw._artifact_input_ref(registry_path, registry),
        "condition_model": rw._artifact_input_ref(condition_path, condition),
        "mechanism_support": None,
        "review_source": rw._artifact_ref(review_path),
        "states": states,
        "edges": edges,
        "networks": networks,
        "reference_basins": basins,
        "diagnostics": diagnostics,
        "blockers": blockers,
        "review": {"decision": decision, "notes": review_notes},
        "gate_status": rw._gate_status(decision, blockers),
        "calculation_ready": False,
        "no_submission_authorization": True,
    }
    rw.finalize_artifact(artifact)
    rw.write_json(output, artifact)
    return artifact


def validate(path: Path) -> dict[str, Any]:
    artifact = rw.load_json(path)
    keys = {"schema", "study_id", "intake", "species_registry", "condition_model", "mechanism_support", "review_source", "states", "edges", "networks", "reference_basins", "diagnostics", "blockers", "review", "gate_status", "calculation_ready", "no_submission_authorization", "payload_sha256"}
    _exact(artifact, keys, "mechanism-network artifact")
    rw.require(artifact["schema"] == OUTPUT_SCHEMA, "unrecognized mechanism-network artifact schema")
    rw.validate_payload_hash(artifact)
    rw.require(artifact["calculation_ready"] is False and artifact["no_submission_authorization"] is True, "mechanism-network artifact violates offline safety flags")
    rw.require(artifact["mechanism_support"] is None, f"the upstream W3 network must retain a null child {SUPPORT_SCHEMA} binding to avoid circular hashes")
    intake = rw._verify_bound_artifact(artifact["intake"], path, rw.INTAKE_SCHEMA, "mechanism-network intake")
    registry = rw._verify_bound_artifact(artifact["species_registry"], path, rw.REGISTRY_SCHEMA, "mechanism-network registry")
    condition = rw._verify_bound_artifact(artifact["condition_model"], path, rw.CONDITION_SCHEMA, "mechanism-network condition model")
    for reference in (artifact["intake"], artifact["species_registry"], artifact["condition_model"]):
        rw.validate_artifact(_referenced_path(reference, path))
    rw.require(artifact["study_id"] == intake["study_id"] == registry["study_id"] == condition["study_id"], "mechanism-network study IDs differ")
    rw.require(registry["intake"]["payload_sha256"] == intake["payload_sha256"], "mechanism-network registry is not bound to its intake")
    rw.require(condition["intake"]["payload_sha256"] == intake["payload_sha256"], "mechanism-network condition model is not bound to its intake")
    rw.require(condition["species_registry"]["payload_sha256"] == registry["payload_sha256"], "mechanism-network condition model is not bound to its registry")
    review_ref = _exact(artifact["review_source"], {"path", "sha256", "size_bytes"}, "mechanism-network review_source")
    review_path = Path(review_ref["path"])
    if not review_path.is_absolute():
        review_path = path.parent / review_path
    rw.require(review_path.is_file() and not review_path.is_symlink(), "mechanism-network review source is missing or a symlink")
    rw.require(review_ref["sha256"] == rw.sha256_file(review_path) and review_ref["size_bytes"] == review_path.stat().st_size, "mechanism-network review source hash/size mismatch")
    source_review = rw.load_json(review_path)
    states, edges, networks, basins, diagnostics, computed_blockers, decision, review_notes = _normalize_review(source_review, intake, registry, condition)
    rw.require(artifact["states"] == states and artifact["edges"] == edges and artifact["networks"] == networks and artifact["reference_basins"] == basins, "mechanism-network artifact is not in deterministic normalized form")
    rw.require(artifact["diagnostics"] == diagnostics, "mechanism-network diagnostics mismatch independent recomputation")
    rw.require(artifact["blockers"] == computed_blockers, "mechanism-network blockers mismatch independent recomputation")
    review = _exact(artifact["review"], {"decision", "notes"}, "mechanism-network artifact review")
    rw.require(review == {"decision": decision, "notes": review_notes}, "mechanism-network artifact review differs from its immutable review source")
    rw.require(artifact["gate_status"] == rw._gate_status(review["decision"], artifact["blockers"]), "mechanism-network gate status is inconsistent")
    return {"schema": "gaussian-reaction-mechanism-network-validation/1", "artifact_schema": OUTPUT_SCHEMA, "study_id": artifact["study_id"], "gate_status": artifact["gate_status"], "blocker_count": len(artifact["blockers"]), "payload_sha256": artifact["payload_sha256"], "live_actions": False}


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    build_parser = commands.add_parser("build", help="build one immutable offline mechanism-network artifact")
    build_parser.add_argument("intake", type=Path)
    build_parser.add_argument("registry", type=Path)
    build_parser.add_argument("condition_model", type=Path)
    build_parser.add_argument("--review", type=Path, required=True)
    build_parser.add_argument("--output", type=Path, required=True)
    validate_parser = commands.add_parser("validate", help="validate and independently recompute one mechanism-network artifact")
    validate_parser.add_argument("artifact", type=Path)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        result = build(args.intake, args.registry, args.condition_model, args.review, args.output) if args.command == "build" else validate(args.artifact)
    except (rw.OfflineError, OSError, ValueError, AssertionError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
