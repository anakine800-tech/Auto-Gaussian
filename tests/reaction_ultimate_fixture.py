"""Reusable synthetic fixture for the fully connected offline reaction chain."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "reaction_workflow"


def _write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _nonmetal_review(review: dict[str, Any]) -> None:
    """Convert the catalytic network fixture into an explicit noncatalytic one."""

    for state in review["states"]:
        state["atoms"] = [atom for atom in state["atoms"] if atom["element"] != "Pd"]
        components = []
        for component in state["components"]:
            component["atom_ids"] = [
                atom_id for atom_id in component["atom_ids"]
                if not atom_id.endswith("_pd")
            ]
            if component["atom_ids"]:
                components.append(component)
        state["components"] = components
        state["connections"] = [
            connection for connection in state["connections"]
            if not any(atom_id.endswith("_pd") for atom_id in connection["atom_ids"])
        ]
        state["catalyst_projection"] = None
        state["environment_model"]["rationale"] = (
            "The fixture Pd condition is explicitly excluded from this "
            "noncatalytic computational model."
        )
        state["notes"].append(
            "Pd was removed only to create a main-group offline contract fixture."
        )
    for edge in review["edges"]:
        edge["atom_mapping"] = [
            mapping for mapping in edge["atom_mapping"]
            if not mapping["from_atom_id"].endswith("_pd")
            and not mapping["to_atom_id"].endswith("_pd")
        ]
        edge["connection_changes"] = [
            change for change in edge["connection_changes"]
            if not any(atom_id.endswith("_pd") for atom_id in change["atom_ids"])
        ]
        edge["transfers"] = [
            transfer for transfer in edge["transfers"]
            if not any(
                transfer[key].endswith("_pd")
                for key in ("atom_id", "donor_atom_id", "acceptor_atom_id")
            )
        ]
        edge["state_changes"] = {
            "oxidation_state": "not applicable in the main-group fixture",
            "spin": "singlet fixture throughout",
            "ligand": "not applicable",
            "coordination": "no metal coordination is represented",
            "protonation": "none",
        }
    for network in review["networks"]:
        network["catalyst_cycle"] = {
            "required": False,
            "start_state_id": None,
            "regenerated_state_id": None,
            "closure_edge_ids": [],
            "review_status": "not_applicable",
            "rationale": "No catalyst atom is represented in the main-group fixture network.",
        }
    review["review_notes"].append(
        "Synthetic noncatalytic main-group fixture; no chemical claim is made."
    )


def _build_context(root: Path, *, nonmetal: bool) -> tuple[Any, dict[str, Any]]:
    from tests.test_mechanism_network import MechanismNetworkTests
    from tests.test_ts_precedent_map import TsPrecedentMapTests
    import mechanism_network as mn
    import mechanism_support as ms

    helper = TsPrecedentMapTests(
        "test_four_analogy_classes_and_novel_de_novo_plan_are_exactly_gated"
    )
    if nonmetal:
        network_helper = MechanismNetworkTests("test_help_is_offline_and_exposed")
        (
            intake_path,
            registry_path,
            _original_condition_path,
            intake,
            registry,
            _original_condition,
        ) = network_helper.build_upstream(root)
        import reaction_workflow as rw

        policy_not_applicable = {
            "status": "not_applicable",
            "value": None,
            "unit": None,
            "model": None,
            "rationale": "Not assigned by the noncatalytic contract fixture.",
        }
        nonmetal_condition_review = {
            "schema": "gaussian-reaction-condition-review/1",
            "study_id": intake["study_id"],
            "intake_payload_sha256": intake["payload_sha256"],
            "registry_payload_sha256": registry["payload_sha256"],
            "global_model": {
                "standard_state": dict(policy_not_applicable),
                "temperature_policy": dict(policy_not_applicable),
                "concentration_policy": dict(policy_not_applicable),
                "pressure_policy": dict(policy_not_applicable),
                "explicit_component_policy": dict(policy_not_applicable),
            },
            "decisions": [
                {
                    "condition_id": "step_001_component_001",
                    "treatment": "experimental_context_only",
                    "species_ids": [],
                    "model": None,
                    "rationale": "Pd is explicitly excluded only for this noncatalytic main-group contract fixture.",
                    "review_status": "reviewed",
                }
            ],
            "review_decision": "accepted",
            "review_notes": [
                "The source Pd label is retained, but its computational exclusion is explicit and hash-bound."
            ],
        }
        nonmetal_condition_review_path = root / "nonmetal_condition_review.json"
        _write_json(nonmetal_condition_review_path, nonmetal_condition_review)
        condition_path = root / "nonmetal_condition.json"
        condition = rw.build_condition_model(
            intake_path,
            registry_path,
            nonmetal_condition_review_path,
            condition_path,
        )
        mechanism_review_path, mechanism_review = network_helper.review(
            root, intake, registry, condition
        )
        _nonmetal_review(mechanism_review)
        mechanism_review_path.unlink()
        _write_json(mechanism_review_path, mechanism_review)
        mechanism_path = root / "mechanism_nonmetal.json"
        mechanism = mn.build(
            intake_path,
            registry_path,
            condition_path,
            mechanism_review_path,
            mechanism_path,
        )
        w1 = (
            intake_path,
            registry_path,
            condition_path,
            mechanism_path,
            intake,
            registry,
            condition,
            mechanism,
        )
    else:
        w1 = helper.build_mechanism(root)
        mechanism_review_path = root / "mechanism_review.json"

    snapshot_path, snapshot = helper.build_snapshot(root, w1[0], w1[4])
    evidence_path, evidence, cases, location = helper.build_evidence(
        root, w1, snapshot_path, snapshot
    )
    support_path, support = helper.build_support(
        root, w1, snapshot_path, snapshot, evidence_path, evidence
    )
    ms.validate(support_path)
    context = {
        "network_path": w1[3],
        "network": w1[7],
        "snapshot_path": snapshot_path,
        "snapshot": snapshot,
        "evidence_path": evidence_path,
        "evidence": evidence,
        "support_path": support_path,
        "support": support,
        "support_review_path": root / "ts_mechanism_support_review.json",
        "intake_path": w1[0],
        "registry_path": w1[1],
        "condition_path": w1[2],
        "mechanism_review_path": mechanism_review_path,
        "literature_cases": cases,
        "source_location": location,
    }
    return helper, context


def _ts_record(
    network: dict[str, Any],
    location: dict[str, str],
    coordinate_path: Path,
) -> dict[str, Any]:
    import reaction_workflow as rw

    states = {item["state_id"]: item for item in network["states"]}
    edge = next(item for item in network["edges"] if item["edge_id"] == "edge_activation")
    source = states[edge["from_state_id"]]
    source_atoms_sorted = sorted(
        source["atoms"],
        key=lambda item: ({"H": 0, "I": 1, "Pd": 2}.get(item["element"], 9), item["atom_id"]),
    )
    counts: dict[str, int] = {}
    source_atoms = []
    mapping = []
    edge_mapping = {
        item["from_atom_id"]: item["to_atom_id"] for item in edge["atom_mapping"]
    }
    for index, atom in enumerate(source_atoms_sorted, start=1):
        counts[atom["element"]] = counts.get(atom["element"], 0) + 1
        source_id = f"src_{atom['element'].lower()}{counts[atom['element']]}"
        source_atoms.append(
            {
                "source_atom_id": source_id,
                "order_index": index,
                "element": atom["element"],
            }
        )
        mapping.append(
            {
                "source_atom_id": source_id,
                "from_atom_id": atom["atom_id"],
                "to_atom_id": edge_mapping[atom["atom_id"]],
            }
        )
    contains_metal = any(atom["element"] == "Pd" for atom in source_atoms_sorted)
    dimensions = [
        {
            "dimension": name,
            "value": "exact",
            "rationale": "Synthetic reviewed comparison.",
            "source_anchor": location["locator"],
        }
        for name in (
            "net_transformation",
            "elementary_step_and_atom_correspondence",
            "substrate_electronics_sterics_and_groups",
            "catalyst_and_active_state",
            "atom_inventory_charge_multiplicity_and_spin",
            "coordination_ion_pair_additives_and_solvent",
            "stereochemical_channel",
            "experimental_conditions",
            "computational_protocol_and_validation",
        )
    ]
    return {
        "precedent_id": "precedent_supported_exact",
        "target": {
            "edge_id": edge["edge_id"],
            "from_state_id": edge["from_state_id"],
            "to_state_id": edge["to_state_id"],
            "stereochemical_channel": edge["stereochemical_channel"],
            "eligibility": "eligible",
            "eligibility_reviewed": True,
            "stereochemical_channel_reviewed": True,
            "forming_pairs": [
                change["atom_ids"]
                for change in edge["connection_changes"]
                if change["before_order"] is None
            ],
            "breaking_pairs": [
                change["atom_ids"]
                for change in edge["connection_changes"]
                if change["after_order"] is None
            ],
            "transfers": edge["transfers"],
        },
        "source_precedent": {
            "candidate_id": "lit_exact",
            "evidence_target": "coordinates",
            "source_location": location,
            "applicability_dimensions": dimensions,
            "bounded_use": "geometry_seed_support",
            "relationship": "exact",
        },
        "source_structure": {
            "atom_order_review_status": "reviewed",
            "source_atoms": source_atoms,
            "audits": {
                name: "reviewed"
                for name in (
                    "identity",
                    "atom_order",
                    "stereochemistry",
                    "formal_charge",
                    "multiplicity",
                    "coordination",
                )
            },
            "coordinate_provenance": {
                "status": "published_coordinates",
                "evidence_candidate_id": "lit_exact",
                "evidence_source_location": location,
                "source_object": rw._artifact_ref(coordinate_path),
                "coordinate_block_anchor": location["locator"],
                "coordinates_copied": False,
            },
        },
        "source_to_target_atom_mapping": mapping,
        "target_context": {
            "catalyst_state": (
                "reviewed synthetic Pd fixture"
                if contains_metal
                else "not applicable; no catalyst represented"
            ),
            "coordination": "reviewed synthetic connectivity",
            "ion_pair_additive_placement": "not applicable in fixture",
            "formal_charge": source["formal_charge"],
            "multiplicity": source["multiplicity"],
            "approach_topology": "synthetic reviewed topology",
            "facial_orientational_relationship": "not applicable in achiral fixture",
            "conformer_family": "single synthetic family",
            "review_status": "reviewed",
            "rationale": "Explicit fixture context; no chemistry inferred.",
        },
        "geometry_transfer": [
            {
                "geometry_item_id": "geom_h1_h2",
                "kind": "distance",
                "transfer_status": "transferable",
                "descriptor": None,
                "value": 1.5,
                "range": None,
                "unit": "angstrom",
                "atom_refs": [
                    {"state_id": source["state_id"], "atom_id": "r_h1"},
                    {"state_id": source["state_id"], "atom_id": "r_h2"},
                ],
                "provenance": {
                    "candidate_id": "lit_exact",
                    "source_location": location,
                    "evidence_form": "published_coordinates",
                },
                "applicability": "exact",
                "limitations": ["Synthetic coordinate object only."],
            }
        ],
        "seed_strategy": "published_coordinates",
        "strategy_prerequisites": {
            "status": "complete",
            "endpoint_state_ids": [],
            "geometry_item_ids": ["geom_h1_h2"],
            "source_object": None,
            "source_anchor": None,
            "reviewed_assertions": [
                "coordinate_identity_order_stereo_charge_multiplicity_coordination_audit_complete"
            ],
            "notes": ["All source-coordinate transfer audits complete."],
        },
        "applicability_review": {
            "status": "reviewed",
            "rationale": "Synthetic applicability review.",
            "limitations": ["Offline contract fixture only."],
        },
        "uncertainties": ["No real chemical transferability is claimed."],
        "alternatives": ["Alternative seed families remain outside this fixture."],
        "negative_evidence": [],
        "disposition": {
            "status": "accepted_for_candidate_construction",
            "promotion_review": {
                "status": "approved",
                "reviewer": "fixture_reviewer",
                "reviewed_at": "2026-07-16T00:00:00+00:00",
                "rationale": "Synthetic promotion decision.",
            },
        },
        "blockers": [],
        "notes": ["Synthetic TS-precedent contract record."],
    }


def build_supported_chain(root: Path, *, nonmetal: bool = True) -> dict[str, Any]:
    import ts_precedent_map as tsp

    _, context = _build_context(root, nonmetal=nonmetal)
    coordinate_path = FIXTURES / (
        "ts_precedent_source_main_group.xyz"
        if nonmetal
        else "ts_precedent_source.xyz"
    )
    ts_review = {
        "schema": "gaussian-ts-precedent-map-review/1",
        "study_id": context["network"]["study_id"],
        "mechanism_network_payload_sha256": context["network"]["payload_sha256"],
        "knowledge_snapshot_payload_sha256": context["snapshot"]["payload_sha256"],
        "literature_evidence_payload_sha256": context["evidence"][
            "evidence_review_payload_sha256"
        ],
        "mechanism_support_payload_sha256": context["support"]["payload_sha256"],
        "records": [
            _ts_record(context["network"], context["source_location"], coordinate_path)
        ],
        "de_novo_seed_plans": [],
        "review_decision": "accepted",
        "review_notes": ["Synthetic support-to-precedent integration review."],
    }
    ts_review_path = root / "supported_ts_review.json"
    _write_json(ts_review_path, ts_review)
    ts_map_path = root / "supported_ts_map.json"
    ts_map = tsp.build(
        context["network_path"],
        context["snapshot_path"],
        context["evidence_path"],
        context["support_path"],
        ts_review_path,
        ts_map_path,
    )
    tsp.validate(ts_map_path)
    context.update(
        {
            "ts_review_path": ts_review_path,
            "ts_map_path": ts_map_path,
            "ts_map": ts_map,
            "coordinate_path": coordinate_path,
        }
    )
    return context
