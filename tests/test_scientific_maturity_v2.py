#!/usr/bin/env python3
"""Offline owner-evidence overlay /2 tests and bypass regressions."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


ROOT = Path(__file__).parents[1]
V2_PATH = ROOT / "skills" / "auto-g16-reaction-workflow" / "scripts" / "scientific_maturity_v2.py"
V1_PATH = ROOT / "skills" / "auto-g16-reaction-workflow" / "scripts" / "scientific_maturity.py"
CONFORMER_DIR = ROOT / "skills" / "auto-g16-conformer-search" / "scripts"
FIXTURES = ROOT / "tests" / "fixtures"
SCHEMA_DIR = ROOT / "contracts" / "reaction-workflow"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(path.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


V2 = load_module("scientific_maturity_v2_tests", V2_PATH)
V1 = load_module("scientific_maturity_v1_compatibility_tests", V1_PATH)
CONFORMER = load_module("scientific_maturity_v2_conformer_fixture", CONFORMER_DIR / "conformer_core.py")
SCHEMA_VALIDATOR = load_module("scientific_maturity_v2_schema_validator", ROOT / "scripts" / "validate_asymmetric_contract.py")
MATURITY_FIXTURE = load_module("scientific_maturity_v2_base_fixture", ROOT / "tests" / "test_scientific_maturity.py")
MANUAL_FIXTURE = load_module("scientific_maturity_v2_manual_fixture", ROOT / "tests" / "test_manual_evidence.py")
OPEN_SHELL_FIXTURE = load_module("scientific_maturity_v2_open_shell_fixture", ROOT / "tests" / "test_main_group_open_shell.py")


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def binding(path: Path, root: Path) -> dict:
    value = load(path)
    return {
        "path": path.resolve().relative_to(root.resolve()).as_posix(),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "size_bytes": path.stat().st_size,
        "schema": value["schema"],
        "payload_sha256": value["payload_sha256"],
    }


class ScientificMaturityV2Tests(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        self.base = MATURITY_FIXTURE.ScientificMaturityTests("test_owner_validated_support_and_precedent_plus_minima_open_formal_ts")
        fixture = load(FIXTURES / "reaction_workflow" / "scientific_maturity_v2_cases.json")
        self.cases = {item["case_id"]: item for item in fixture["cases"]}

    def conformer_handoff(self, root: Path, minimum: dict, state: dict, *, multiplicity: int | None = None) -> tuple[Path, str]:
        stem = minimum["minimum_id"]
        r08_path = root / f"{stem}-r08.json"
        write(r08_path, {"schema": "gaussian-conformer-ensemble/1", "fixture_id": stem, "candidate_only": True, "review_status": "reviewed_for_v2_fixture"})
        request = load(FIXTURES / "conformer_search" / "request_generic.json")
        request["request_id"] = f"{stem}_search"
        request["revision"] = {"revision_id": f"{stem}_revision", "supersedes": None}
        request["r08_handoff"].update({"path": r08_path.name, "sha256": CONFORMER.file_sha256(r08_path)})
        component_by_atom = {
            atom_id: component["component_id"]
            for component in state["components"] for atom_id in component["atom_ids"]
        }
        atoms = [
            {
                "atom_id": atom["atom_id"], "map_id": atom["atom_id"], "atom_index": index,
                "element": atom["element"], "fragment_id": component_by_atom[atom["atom_id"]],
                "explicit_hydrogen": atom["element"] == "H",
            }
            for index, atom in enumerate(state["atoms"])
        ]
        index_by_id = {atom["atom_id"]: index for index, atom in enumerate(state["atoms"])}
        order_map = {"single": 1, "double": 2, "triple": 3, "aromatic": 1.5}
        bonds = [
            {"atoms": [index_by_id[item["atom_ids"][0]], index_by_id[item["atom_ids"][1]]], "order": order_map[item["order"]], "in_ring": False}
            for item in state["connections"] if item["order"] in order_map
        ]
        selected_multiplicity = state["multiplicity"] if multiplicity is None else multiplicity
        request["state"] = {
            "state_id": state["state_id"], "identity": state["label"], "atoms": atoms, "bonds": bonds,
            "formal_charge": state["formal_charge"], "multiplicity": selected_multiplicity,
            "component_count": len(state["components"]), "stereochemistry": {},
            "state_labels": ["minimum_search", "owner_evidence_fixture"],
            "unsupported_flags": {
                "transition_metal": any(atom["element"] == "Pd" for atom in state["atoms"]),
                "open_shell": selected_multiplicity > 1, "excited_state": False, "multireference": False,
                "unknown_coordination": False, "connectivity_change_expected": False,
            },
        }
        request["categories"] = [{
            "category_id": "minimum_search", "labels": ["minimum", "fixture"], "total_quota": 4,
            "constraints": {"required_bonds": [], "forbidden_bonds": [], "descriptor_constraints": [{"descriptor_id": "site_pair", "kind": "distance", "minimum": 0.5, "maximum": 10.0}]},
        }]
        request["freedom_inputs"] = {"flexible_ring_count": 0, "relative_constraints": 0, "weak_interaction_types": [], "face_ids": [], "symmetry_classes": []}
        request["shared_xtb_protocol"]["formal_charge"] = state["formal_charge"]
        request["shared_xtb_protocol"]["multiplicity"] = selected_multiplicity
        for adapter in request["adapters"]:
            adapter["settings"]["category_ids"] = ["minimum_search"]
        request["similarity"]["symmetry_permutations"] = []
        request_path = root / f"{stem}-request.json"
        write(request_path, request)
        plan = CONFORMER.build_plan(request, request_path)
        plan_path = root / f"{stem}-plan.json"; write(plan_path, plan)

        def candidate(candidate_id: str, route: str, subroute: str) -> dict:
            signature = plan["state_signature"]
            coordinates = [[float(index) * 1.5, 0.0, 0.0] for index in range(len(atoms))]
            return {
                "candidate_id": candidate_id, "route_id": route, "subroute_id": subroute, "category_id": "minimum_search",
                "atom_order": signature["atom_order"], "elements": signature["elements"], "fragment_ids": signature["fragment_ids"],
                "explicit_hydrogens": signature["explicit_hydrogens"], "observed_bonds": request["state"]["bonds"],
                "formal_charge": signature["formal_charge"], "multiplicity": signature["multiplicity"], "component_count": signature["component_count"],
                "stereochemistry": signature["stereochemistry"], "state_labels": signature["state_labels"],
                "coordinates_angstrom": coordinates, "association_status": "intact", "non_target_transfer": False,
                "retain_as_hypothesis": False, "xtb_optimization_status": "converged", "source_input_sha256": "a" * 64,
                "source_argv": ["inert", "fixture", candidate_id], "random_seed": 101,
                "software": {"name": "synthetic_fixture", "version": "1", "absolute_path": "/synthetic/fixture"},
                "energy_observation": {"value": -1.0, "unit": "fixture_unit", "method": "synthetic", "ranking_allowed": False},
                "key_distances_angstrom": {"site_pair": 1.5}, "torsions_degrees": {}, "contact_fingerprint": ["minimum_contact"],
                "fragment_descriptors": {}, "aromatic_descriptors": {}, "custom_descriptors": {}, "force_backend_review": False,
            }

        candidates = {
            "schema": "gaussian-conformer-candidate-set/1", "plan_sha256": CONFORMER.file_sha256(plan_path),
            "raw_sampling_counts": {"a1_crest": 1, "a2_xtb_md": 1, "b1_etkdg": 1, "b2_directed": 1},
            "audit_policy": {"minimum_distance_angstrom": 0.4}, "category_contracts": plan["category_contracts"],
            "candidates": [
                candidate(minimum["conformer_origin"]["source_id"], "route_a", "a1_crest"), candidate(f"{stem}_a2", "route_a", "a2_xtb_md"),
                candidate(f"{stem}_b1", "route_b", "b1_etkdg"), candidate(f"{stem}_b2", "route_b", "b2_directed"),
            ],
        }
        candidates_path = root / f"{stem}-candidates.json"; write(candidates_path, candidates)
        ledger = CONFORMER.audit_candidates(plan, plan_path, candidates, candidates_path)
        ledger_path = root / f"{stem}-ledger.json"; write(ledger_path, ledger)
        manifest = CONFORMER.crosscheck(plan, plan_path, candidates, candidates_path, ledger, ledger_path)
        manifest_path = root / f"{stem}-manifest.json"; write(manifest_path, manifest)
        selected = manifest["clusters"][0]["medoid_candidate_id"]
        handoff_review = {
            "schema": "gaussian-conformer-handoff-review/1", "manifest_sha256": CONFORMER.file_sha256(manifest_path),
            "selected_candidate_ids": [selected], "reviewer": "v2_fixture_reviewer",
            "decision": "selected_for_downstream_input_review", "confirmed": True,
        }
        handoff_review_path = root / f"{stem}-handoff-review.json"; write(handoff_review_path, handoff_review)
        handoff = CONFORMER.build_handoff(manifest, manifest_path, handoff_review, handoff_review_path)
        handoff_path = root / f"{stem}-handoff.json"; write(handoff_path, handoff)
        self.assertEqual(CONFORMER.validate_handoff(handoff_path), handoff)
        return handoff_path, selected

    def base_context(self, root: Path, *, open_shell_bypass: bool = False) -> tuple[Path, Path, dict, dict]:
        plan_path = self.base.build_owner_gated_plan(root)
        if not open_shell_bypass:
            _, base_gate_path = self.base.build_gate(root, plan=plan_path)
        else:
            review_value = self.base.review(root, plan_path)
            for minimum in review_value["minimum_records"]:
                minimum["multiplicity"] = 2
                result_path = root / minimum["result"]["path"]
                result = load(result_path); result["chemical_identity"]["multiplicity"] = 2
                MATURITY_FIXTURE.rehash(result); write(result_path, result)
                minimum["result"] = MATURITY_FIXTURE.json_binding(result_path)
            draft = root / "open-shell-base-review.draft.json"; review_path = root / "open-shell-base-review.json"; base_gate_path = root / "open-shell-base-gate.json"
            write(draft, review_value)
            V1.finalize_review(draft, review_path)
            V1.build_gate(plan_path, review_path, base_gate_path)
            self.assertTrue(all(item["accepted"] for item in load(base_gate_path)["minimum_gates"]))
        base_gate = load(base_gate_path)
        base_review = load(root / base_gate["review_source"]["path"])
        plan = load(plan_path)
        mechanism = load(root / plan["mechanism_network"]["path"])
        return plan_path, base_gate_path, base_review, mechanism

    def formal_base_context(self, root: Path) -> tuple[Path, Path, dict, dict]:
        """Build a direct-support + promoted-precedent plan through the owner builders."""

        helper = MATURITY_FIXTURE.TS_PRECEDENT_FIXTURE.TsPrecedentMapTests(
            "test_four_analogy_classes_and_novel_de_novo_plan_are_exactly_gated"
        )
        prepared = helper.prepare(root)
        evidence = copy.deepcopy(prepared["evidence"])
        source_review = next(item for item in evidence["reviews"] if item["candidate_id"] == "lit_exact")
        direct_review = copy.deepcopy(source_review)
        direct_review["candidate_id"] = "lit_mechanism_direct"
        direct_review["bibliography"]["doi"] = "10.5555/lit_mechanism_direct"
        direct_review["bibliography"]["title"] = "Synthetic direct mechanism support"
        direct_review["reviewer_decision"]["bounded_use"] = "mechanism_support"
        evidence["reviews"].append(direct_review)
        ledger_path = Path(evidence["candidate_ledger_artifact"]["path"])
        ledger = load(ledger_path)
        ledger["candidates"].append({
            "candidate_id": direct_review["candidate_id"], "doi": direct_review["bibliography"]["doi"],
            "title": direct_review["bibliography"]["title"],
        })
        ledger = MATURITY_FIXTURE.TS_PRECEDENT_FIXTURE.LIT.add_payload_hash(ledger, "candidate_ledger_payload_sha256")
        write(ledger_path, ledger)
        evidence["candidate_ledger_artifact"]["sha256"] = hashlib.sha256(ledger_path.read_bytes()).hexdigest()
        evidence = MATURITY_FIXTURE.TS_PRECEDENT_FIXTURE.LIT.add_payload_hash(evidence, "evidence_review_payload_sha256")
        evidence_path = root / "formal_literature_evidence.json"
        write(evidence_path, evidence)
        support_review_path = root / "ts_mechanism_support_review.json"
        support_review = load(support_review_path)
        support_review["literature_evidence_payload_sha256"] = evidence["evidence_review_payload_sha256"]
        exact = next(item for item in support_review["records"] if item["support_record_id"] == "ts_support_exact")
        exact["evidence"]["candidate_id"] = direct_review["candidate_id"]
        exact["claim_support_decision"] = {
            "status": "promoted", "rationale": "Synthetic direct source-located mechanism support is promoted for the exact fixture target.",
            "reviewer": "fixture_reviewer", "reviewed_at": "2026-07-16T00:00:00+00:00",
            "resolved_blockers": ["Exact target, channel, applicability, and source location were independently reviewed."],
            "unresolved_blockers": [], "resolved_conflict_record_ids": [],
        }
        write(support_review_path, support_review)
        support_path = root / "formal_mechanism_support.json"
        support_result = helper.run_tool(
            MATURITY_FIXTURE.TS_PRECEDENT_FIXTURE.SUPPORT_TOOL, "build", str(prepared["w1"][3]),
            str(prepared["snapshot_path"]), str(evidence_path), "--review", str(support_review_path),
            "--output", str(support_path),
        )
        self.assertEqual(support_result.returncode, 0, support_result.stderr or support_result.stdout)
        support = load(support_path)
        self.assertTrue(next(item for item in support["edge_channel_summary"] if item["edge_id"] == "edge_activation")["mechanism_claim_supported"])

        precedent_review = copy.deepcopy(prepared["review"])
        precedent_review["mechanism_support_payload_sha256"] = support["payload_sha256"]
        precedent_review["literature_evidence_payload_sha256"] = evidence["evidence_review_payload_sha256"]
        precedent_review_path = root / "formal_ts_precedent_review.json"
        precedent_path = root / "formal_ts_precedent_map.json"
        write(precedent_review_path, precedent_review)
        precedent_result = helper.run_tool(
            MATURITY_FIXTURE.TS_PRECEDENT_FIXTURE.TOOL, "build", str(prepared["w1"][3]),
            str(prepared["snapshot_path"]), str(evidence_path), str(support_path),
            "--review", str(precedent_review_path), "--output", str(precedent_path),
        )
        self.assertEqual(precedent_result.returncode, 0, precedent_result.stderr or precedent_result.stdout)
        precedent = load(precedent_path)
        exact_precedent = next(item for item in precedent["records"] if item["precedent_id"] == "precedent_exact")
        self.assertTrue(exact_precedent["mechanism_support_gate"]["mechanism_claim_supported"])
        self.assertTrue(exact_precedent["promotion_requirements_complete"])

        intake_path, registry_path, condition_path, mechanism_path = prepared["w1"][:4]
        artifacts = {
            "intake": load(intake_path), "registry": load(registry_path), "condition": load(condition_path),
            "mechanism": load(mechanism_path), "support": support, "precedent": precedent,
        }
        calculation_review = load(FIXTURES / "reaction_workflow" / "calculation_plan_review.template.json")
        for key, artifact_key in (
            ("intake_payload_sha256", "intake"), ("species_registry_payload_sha256", "registry"),
            ("condition_model_payload_sha256", "condition"), ("mechanism_network_payload_sha256", "mechanism"),
            ("mechanism_support_payload_sha256", "support"), ("ts_precedent_map_payload_sha256", "precedent"),
        ):
            calculation_review[key] = artifacts[artifact_key]["payload_sha256"]
        calculation_draft = root / "formal_calculation_review_draft.json"
        calculation_final = root / "formal_calculation_review.json"
        plan_path = root / "formal_calculation_plan.json"
        write(calculation_draft, calculation_review)
        finalized = self.base.run_cli(MATURITY_FIXTURE.DAG_TOOL, "finalize-review", str(calculation_draft), "--output", str(calculation_final))
        self.assertEqual(finalized.returncode, 0, finalized.stderr or finalized.stdout)
        built = self.base.run_cli(
            MATURITY_FIXTURE.DAG_TOOL, "build-plan", str(intake_path), str(registry_path), str(condition_path), str(mechanism_path),
            "--review", str(calculation_final), "--mechanism-support", str(support_path),
            "--ts-precedent-map", str(precedent_path), "--output", str(plan_path),
        )
        self.assertEqual(built.returncode, 0, built.stderr or built.stdout)
        _, base_gate_path = self.base.build_gate(root, plan=plan_path)
        base_gate = load(base_gate_path)
        base_review = load(root / base_gate["review_source"]["path"])
        return plan_path, base_gate_path, base_review, load(mechanism_path)

    def review_v2(self, root: Path, base_gate_path: Path, base_review: dict, mechanism: dict, *, precedent: str = "precedent_exact", handfill: bool = False, multiplicity_override: int | None = None, manual_claims: list[dict] | None = None) -> dict:
        state_map = {item["state_id"]: item for item in mechanism["states"]}
        minima = []
        for minimum in base_review["minimum_records"]:
            handoff_path, selected = self.conformer_handoff(root, minimum, state_map[minimum["state_id"]], multiplicity=multiplicity_override)
            minima.append({
                "minimum_id": minimum["minimum_id"], "state_id": minimum["state_id"],
                "composition_signature": minimum["composition_signature"], "formal_charge": minimum["formal_charge"],
                "multiplicity": minimum["multiplicity"],
                "conformer_origin": copy.deepcopy(minimum["conformer_origin"]),
                "selected_candidate_id": "unreviewed_handfilled_candidate" if handfill and not minima else selected,
                "conformer_handoff": binding(handoff_path, root), "open_shell_acceptance": None,
                "minimum_lineage": None,
            })
        return {
            "schema": V2.REVIEW_SCHEMA, "review_id": "owner_evidence_fixture", "study_id": base_review["study_id"],
            "base_gate_payload_sha256": load(base_gate_path)["payload_sha256"],
            "edge_evidence": [{
                "edge_id": "edge_activation", "stereochemical_channel": None,
                "mechanism_support_record_ids": ["ts_support_exact"],
                "candidate_construction": {"kind": "precedent_record", "source_id": precedent},
            }],
            "minimum_evidence": minima, "manual_claims": manual_claims or [], "review_decision": "accepted",
            "reviewer": "v2_fixture_reviewer", "reviewed_at": "2026-07-17T12:00:00Z", "review_notes": ["Synthetic offline fixture only."],
            "calculation_ready": False, "no_submission_authorization": True,
            "no_method_selection_authorization": True, "no_input_generation_authorization": True, "payload_sha256": None,
        }

    def build_overlay(self, root: Path, review_value: dict, base_gate_path: Path) -> tuple[Path, Path, Path]:
        draft = root / "maturity-v2-review.draft.json"; review_path = root / "maturity-v2-review.json"
        receipt_path = root / "maturity-v2-evidence-receipt.json"; gate_path = root / "maturity-v2-gate.json"
        write(draft, review_value); V2.finalize_review(draft, review_path)
        V2.build_evidence_receipt(base_gate_path, review_path, receipt_path)
        V2.build_gate(base_gate_path, receipt_path, review_path, gate_path)
        return review_path, receipt_path, gate_path

    def test_positive_pilot_roundtrip_schemas_and_v1_compatibility(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, base_gate_path, base_review, mechanism = self.base_context(root)
            review_value = self.review_v2(root, base_gate_path, base_review, mechanism)
            review_path, receipt_path, gate_path = self.build_overlay(root, review_value, base_gate_path)
            self.assertEqual(V1.validate_gate(base_gate_path)["schema"], "gaussian-scientific-maturity-gate/1")
            self.assertEqual(V2.validate_evidence_receipt(receipt_path)["schema"], V2.EVIDENCE_RECEIPT_SCHEMA)
            gate = V2.validate_gate(gate_path)
            expected = self.cases["owner_evidence_pilot_positive"]
            evidence = load(receipt_path)
            self.assertEqual(evidence["edge_evidence"][0]["pilot_owner_evidence_ready"], expected["expected_edge_pilot"])
            self.assertEqual(gate["edge_gates"][0]["pilot_scientifically_ready"], expected["expected_gate_pilot"])
            self.assertEqual(gate["edge_gates"][0]["formal_scientifically_ready"], expected["expected_formal"])
            self.assertTrue(all(not item["owner_evidence_ready"] for item in evidence["minimum_evidence"]))
            self.assertTrue(all("minimum_candidate_input_result_lineage_unavailable_v2" in item["blockers"] for item in evidence["minimum_evidence"]))
            with self.assertRaisesRegex(V2.EvidenceOverlayError, "minimum_.*_owner_evidence_blocked"):
                V2.assert_action(gate_path, "edge_activation", "ts_candidate_primary", "ts_submission", pilot=True)
            base_gate = load(base_gate_path); base_gate["__path"] = str(base_gate_path)
            self.assertEqual(V2._action_nodes(base_gate, gate["edge_gates"][0], "ts_input", True), {"ts_candidate_primary": "ts_candidate"})
            self.assertEqual(V2._action_nodes(base_gate, gate["edge_gates"][0], "ts_input", False), {"ts_freq_activation": "ts_freq"})
            schema_instances = {
                "scientific-maturity-review-v2.schema.json": load(review_path),
                "scientific-evidence-receipt.schema.json": load(receipt_path),
                "scientific-maturity-gate-v2.schema.json": load(gate_path),
            }
            for name, instance in schema_instances.items():
                schema = load(SCHEMA_DIR / name)
                SCHEMA_VALIDATOR.validate_schema_document(schema)
                SCHEMA_VALIDATOR._validate_schema_instance(instance, schema, schema)
            SCHEMA_VALIDATOR.validate_schema_document(load(SCHEMA_DIR / "scientific-maturity-action-v2.schema.json"))
            with self.assertRaisesRegex(V2.EvidenceOverlayError, "complete_owner_thermochemistry_evidence_v2_required"):
                V2.assert_action(gate_path, "edge_activation", "thermochemistry_activation", "formal_barrier_reporting")
            with self.assertRaisesRegex(V2.EvidenceOverlayError, "exact_owner_ts_mode_artifact_v2_required"):
                V2.assert_action(gate_path, "edge_activation", "irc_forward_activation", "irc_input")

    def test_exact_owner_supported_edge_still_blocks_formal_actions_without_minimum_lineage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, base_gate_path, base_review, mechanism = self.formal_base_context(root)
            review_value = self.review_v2(root, base_gate_path, base_review, mechanism)
            _, receipt_path, gate_path = self.build_overlay(root, review_value, base_gate_path)
            evidence = V2.validate_evidence_receipt(receipt_path)["edge_evidence"][0]
            self.assertTrue(evidence["mechanism_claim_supported"])
            self.assertTrue(evidence["promotion_requirements_complete"])
            self.assertTrue(evidence["formal_owner_evidence_ready"])
            gate = V2.validate_gate(gate_path)
            expected = self.cases["owner_evidence_formal_positive"]
            self.assertEqual(evidence["formal_owner_evidence_ready"], expected["expected_edge_formal"])
            self.assertEqual(gate["edge_gates"][0]["pilot_scientifically_ready"], expected["expected_gate_pilot"])
            self.assertEqual(gate["edge_gates"][0]["formal_scientifically_ready"], expected["expected_gate_formal"])
            for action_name in ("ts_input", "ts_submission"):
                with self.subTest(action=action_name):
                    action_path = root / f"formal-{action_name}.json"
                    with self.assertRaisesRegex(V2.EvidenceOverlayError, "minimum_.*_owner_evidence_blocked"):
                        V2.build_action(gate_path, "edge_activation", "ts_freq_activation", action_name, action_path)
                    self.assertFalse(action_path.exists())

    def test_precedent_presence_and_conformer_handfill_bypasses_are_blocked(self) -> None:
        for name, case_id, options in (
            ("precedent", "precedent_presence_bypass", {"precedent": "precedent_close"}),
            ("conformer", "conformer_handfill_bypass", {"handfill": True}),
        ):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                _, base_gate_path, base_review, mechanism = self.base_context(root)
                review_value = self.review_v2(root, base_gate_path, base_review, mechanism, **options)
                _, receipt_path, gate_path = self.build_overlay(root, review_value, base_gate_path)
                serialized = json.dumps(load(receipt_path))
                self.assertIn(self.cases[case_id]["expected_blocker"], serialized)
                with self.assertRaises(V2.EvidenceOverlayError):
                    V2.assert_action(gate_path, "edge_activation", "ts_candidate_primary", "ts_input", pilot=True)

    def test_base_conformer_origin_mismatch_is_an_ancestry_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, base_gate_path, base_review, mechanism = self.base_context(root)
            review_value = self.review_v2(root, base_gate_path, base_review, mechanism)
            review_value["minimum_evidence"][0]["conformer_origin"]["source_id"] = "replacement_candidate_same_state"
            draft = root / "origin-mismatch.draft.json"; review_path = root / "origin-mismatch.json"
            write(draft, review_value); V2.finalize_review(draft, review_path)
            with self.assertRaisesRegex(V2.EvidenceOverlayError, "conformer_origin differs from base review /1"):
                V2.build_evidence_receipt(base_gate_path, review_path, root / "origin-mismatch-receipt.json")

    def test_open_shell_v1_bypass_remains_specialist_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, base_gate_path, base_review, mechanism = self.base_context(root, open_shell_bypass=True)
            review_value = self.review_v2(root, base_gate_path, base_review, mechanism, multiplicity_override=2)
            _, receipt_path, gate_path = self.build_overlay(root, review_value, base_gate_path)
            serialized = json.dumps(load(receipt_path))
            self.assertIn(self.cases["open_shell_specialist_bypass"]["expected_blocker"], serialized)
            with self.assertRaises(V2.EvidenceOverlayError):
                V2.assert_action(gate_path, "edge_activation", "ts_candidate_primary", "ts_input", pilot=True)

    def test_main_group_open_shell_owner_acceptance_missing_blocked_mismatch_and_exact(self) -> None:
        owner = OPEN_SHELL_FIXTURE.OPEN_SHELL
        owner_fixtures = OPEN_SHELL_FIXTURE.FIXTURES
        for prefix in ("ch3", "triplet_ch2"):
            with self.subTest(prefix=prefix), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                review_path, _, acceptance_path, _, _, acceptance = OPEN_SHELL_FIXTURE.MainGroupOpenShellTests(
                    "test_ch3_doublet_and_triplet_carbene_positive_chains"
                ).build_chain(root, prefix)
                candidate = load(owner_fixtures / f"{prefix}_candidate.json")
                signature = {"elements": [atom["element"] for atom in candidate["atoms"]]}
                item = {
                    "formal_charge": candidate["charge"], "multiplicity": candidate["multiplicity"],
                    "open_shell_acceptance": binding(acceptance_path, root),
                }
                projection, blockers = V2._project_open_shell_evidence(
                    item, signature, candidate["candidate_id"], root / "maturity-v2-review.json", owner,
                )
                self.assertEqual(blockers, [])
                self.assertEqual(projection["payload_sha256"], acceptance["payload_sha256"])
                self.assertEqual(projection["candidate_id"], candidate["candidate_id"])
                self.assertEqual(not blockers, self.cases["main_group_open_shell_exact"]["expected_specialist_valid"])

                missing = dict(item); missing["open_shell_acceptance"] = None
                _, missing_blockers = V2._project_open_shell_evidence(
                    missing, signature, candidate["candidate_id"], root / "maturity-v2-review.json", owner,
                )
                self.assertIn(self.cases["main_group_open_shell_missing"]["expected_blocker"], missing_blockers)

                _, mismatch_blockers = V2._project_open_shell_evidence(
                    item, signature, "different_reviewed_medoid", root / "maturity-v2-review.json", owner,
                )
                self.assertIn("open_shell_candidate_differs_from_selected_conformer", mismatch_blockers)
                charge_mismatch = dict(item); charge_mismatch["formal_charge"] = candidate["charge"] + 1
                _, identity_blockers = V2._project_open_shell_evidence(
                    charge_mismatch, signature, candidate["candidate_id"], root / "maturity-v2-review.json", owner,
                )
                self.assertIn(self.cases["main_group_open_shell_identity_mismatch"]["expected_blocker"], identity_blockers)

                if prefix == "ch3":
                    alternate_log = root / "ch3-alternate-valid.synthetic.txt"
                    alternate_log.write_text(
                        " Synthetic alternate raw-log identity.\n"
                        + (owner_fixtures / "ch3_success.synthetic.txt").read_text(encoding="utf-8"),
                        encoding="utf-8",
                    )
                    alternate_observation = owner.build_observation(alternate_log, "ch3_alternate_observation")
                    alternate_observation_path = owner.write_new_json(root / "ch3-alternate.observation.json", alternate_observation)
                    alternate_acceptance = owner.build_acceptance(
                        review_path, alternate_observation_path, owner_fixtures / "acceptance_policy.json", "ch3_alternate_acceptance",
                    )
                    alternate_path = owner.write_new_json(root / "ch3-alternate.acceptance.json", alternate_acceptance)
                    alternate_item = dict(item); alternate_item["open_shell_acceptance"] = binding(alternate_path, root)
                    alternate_projection, alternate_blockers = V2._project_open_shell_evidence(
                        alternate_item, signature, candidate["candidate_id"], root / "maturity-v2-review.json", owner,
                    )
                    self.assertEqual(alternate_blockers, [])
                    self.assertNotEqual(projection["raw_log_sha256"], alternate_projection["raw_log_sha256"])
                    self.assertIn(
                        "minimum_candidate_input_result_lineage_unavailable_v2",
                        V2._minimum_candidate_input_result_lineage_blockers(),
                    )

                    contaminated_log = root / "ch3-contaminated.synthetic.txt"
                    contaminated_log.write_text(
                        (owner_fixtures / "ch3_success.synthetic.txt").read_text(encoding="utf-8").replace(
                            "after 0.7505", "after 1.2000",
                        ),
                        encoding="utf-8",
                    )
                    observation = owner.build_observation(contaminated_log, "ch3_contaminated_observation")
                    observation_path = owner.write_new_json(root / "ch3-contaminated.observation.json", observation)
                    blocked_acceptance = owner.build_acceptance(
                        review_path, observation_path, owner_fixtures / "acceptance_policy.json", "ch3_blocked_acceptance",
                    )
                    blocked_path = owner.write_new_json(root / "ch3-blocked.acceptance.json", blocked_acceptance)
                    blocked_item = dict(item); blocked_item["open_shell_acceptance"] = binding(blocked_path, root)
                    blocked_projection, blocked_reasons = V2._project_open_shell_evidence(
                        blocked_item, signature, candidate["candidate_id"], root / "maturity-v2-review.json", owner,
                    )
                    self.assertEqual(blocked_projection["status"], "blocked")
                    self.assertIn(self.cases["main_group_open_shell_blocked"]["expected_blocker"], blocked_reasons)

    def test_open_shell_owner_relative_cwd_source_paths_are_reused_exactly(self) -> None:
        owner = OPEN_SHELL_FIXTURE.OPEN_SHELL
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            root = Path(temporary).resolve()
            _, _, acceptance_path, _, _, acceptance = OPEN_SHELL_FIXTURE.MainGroupOpenShellTests(
                "test_ch3_doublet_and_triplet_carbene_positive_chains"
            ).build_chain(root, "ch3")
            self.assertFalse(Path(acceptance["review_source"]["path"]).is_absolute())
            candidate = load(OPEN_SHELL_FIXTURE.FIXTURES / "ch3_candidate.json")
            item = {
                "formal_charge": candidate["charge"], "multiplicity": candidate["multiplicity"],
                "open_shell_acceptance": binding(acceptance_path, root),
            }
            projection, blockers = V2._project_open_shell_evidence(
                item, {"elements": [atom["element"] for atom in candidate["atoms"]]},
                candidate["candidate_id"], root / "maturity-v2-review.json", owner,
            )
            self.assertEqual(blockers, [])
            self.assertEqual(projection["payload_sha256"], acceptance["payload_sha256"])
            moved_cwd = subprocess.run(
                [sys.executable, str(OPEN_SHELL_FIXTURE.MODULE), "validate", str(acceptance_path)],
                cwd=root, text=True, capture_output=True, check=False,
            )
            self.assertNotEqual(moved_cwd.returncode, 0)
            self.assertIn("must be an existing regular file", moved_cwd.stderr)

    def manual_receipt(self, root: Path, *, quality_blocked: bool) -> Path:
        root.mkdir()
        helper = MANUAL_FIXTURE.ManualEvidenceTests("test_g09_to_g16_without_installed_revision_review_fails_closed")
        review = load(FIXTURES / "knowledge_base" / "manual_evidence" / "review.json")
        if quality_blocked:
            review["receipt_id"] = "fixture_quality_blocked"
            review["whole_page_visual_review"] = {"status": "not_reviewed", "reviewer": None, "reviewed_at": None, "notes": ["Whole-page review is incomplete."]}
            review["applicability_decision"] = "blocked_insufficient_evidence"
            review["applicability_rationale"] = "Degraded OCR evidence is not positively applicable without complete page review."
        else:
            review["receipt_id"] = "fixture_version_blocked"
            review["installed_revision_review"] = {"status": "not_reviewed", "reviewer": None, "reviewed_at": None, "evidence_sha256": [], "notes": ["Installed G16 revision has not been reviewed."]}
            review["applicability_decision"] = "blocked_pending_installed_revision_review"
            review["applicability_rationale"] = "No positive version applicability is claimed."
        output, result = helper.build(root, review)
        self.assertEqual(result.returncode, 0, result.stderr)
        return output

    def test_manual_version_and_quality_receipts_are_supporting_only_and_fail_closed(self) -> None:
        for name, quality in (("version", False), ("quality", True)):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                _, base_gate_path, base_review, mechanism = self.base_context(root)
                receipt = self.manual_receipt(root / f"manual-{name}", quality_blocked=quality)
                claim = {"claim_id": f"manual_{name}_claim", "target_kind": "edge", "target_id": "edge_activation", "intended_use": "syntax_version_context", "receipt": binding(receipt, root)}
                review_value = self.review_v2(root, base_gate_path, base_review, mechanism, manual_claims=[claim])
                _, evidence_path, gate_path = self.build_overlay(root, review_value, base_gate_path)
                evidence = load(evidence_path)["manual_evidence"][0]
                self.assertTrue(evidence["supporting_only"])
                self.assertFalse(evidence["owner_evidence_ready"])
                self.assertIn(self.cases[f"manual_{name}_gate"]["expected_blocker"], evidence["blockers"])
                with self.assertRaises(V2.EvidenceOverlayError):
                    V2.assert_action(gate_path, "edge_activation", "ts_candidate_primary", "ts_input", pilot=True)

    def test_general_theory_manual_receipt_cannot_claim_syntax_version_context(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, base_gate_path, base_review, mechanism = self.base_context(root)
            manual_root = root / "manual-general"; manual_root.mkdir()
            helper = MANUAL_FIXTURE.ManualEvidenceTests("test_general_theory_source_has_null_program_version_and_no_fake_g09_g16_gate")
            general_review = load(FIXTURES / "knowledge_base" / "manual_evidence" / "review.json")
            general_review.update({
                "receipt_id": "fixture_general_syntax_mismatch", "query": "variational principle",
                "selected_result_id": "chunk_general_variational", "claim_scope": "general_electronic_structure",
                "short_paraphrase": "The selected textbook page supports only a general variational-principle context.",
                "installed_revision_review": {
                    "status": "not_applicable_non_version_claim", "reviewer": None, "reviewed_at": None,
                    "evidence_sha256": [], "notes": ["No installed-version claim is made by this general source."],
                },
                "applicability_decision": "applicable",
                "applicability_rationale": "The source is applicable only to general electronic-structure context.",
                "uncertainties": [],
            })
            manual_receipt, result = helper.build(manual_root, general_review)
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            claim = {
                "claim_id": "general_source_as_syntax", "target_kind": "edge", "target_id": "edge_activation",
                "intended_use": "syntax_version_context", "receipt": binding(manual_receipt, root),
            }
            review_value = self.review_v2(root, base_gate_path, base_review, mechanism, manual_claims=[claim])
            _, evidence_path, gate_path = self.build_overlay(root, review_value, base_gate_path)
            manual_projection = load(evidence_path)["manual_evidence"][0]
            self.assertIn(
                self.cases["manual_general_source_as_syntax"]["expected_blocker"],
                manual_projection["blockers"],
            )
            self.assertTrue(manual_projection["supporting_only"])
            with self.assertRaises(V2.EvidenceOverlayError):
                V2.assert_action(gate_path, "edge_activation", "ts_candidate_primary", "ts_input", pilot=True)

    def test_manual_owner_constraints_are_projected_without_losing_uncertainty(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, base_gate_path, base_review, mechanism = self.base_context(root)
            manual_root = root / "manual-exact"; manual_root.mkdir()
            helper = MANUAL_FIXTURE.ManualEvidenceTests("test_synthetic_readonly_query_and_receipt_build_are_hash_bound_and_text_bounded")
            manual_receipt_path, result = helper.build(manual_root)
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            manual_receipt = load(manual_receipt_path)
            claim = {
                "claim_id": "exact_manual_projection", "target_kind": "edge", "target_id": "edge_activation",
                "intended_use": "syntax_version_context", "receipt": binding(manual_receipt_path, root),
            }
            review_value = self.review_v2(root, base_gate_path, base_review, mechanism, manual_claims=[claim])
            _, evidence_path, _ = self.build_overlay(root, review_value, base_gate_path)
            projection = load(evidence_path)["manual_evidence"][0]
            self.assertTrue(projection["owner_evidence_ready"])
            self.assertEqual(projection["downstream_role"], manual_receipt["downstream_role"])
            self.assertEqual(projection["source_kind"], manual_receipt["source"]["source_kind"])
            self.assertEqual(projection["claim_scope"], manual_receipt["source"]["claim_scope"])
            self.assertEqual(projection["source_program"], manual_receipt["source"]["program"])
            self.assertEqual(projection["source_object_sha256"], manual_receipt["source"]["object_sha256"])
            self.assertEqual(projection["retrieved_text_sha256"], manual_receipt["retrieval"]["retrieved_text_sha256"])
            self.assertEqual(projection["retrieval_row_sha256"], manual_receipt["retrieval"]["retrieval_row_sha256"])
            self.assertEqual(projection["uncertainties"], manual_receipt["uncertainties"])
            self.assertEqual(projection["applicability"]["decision"], "applicable_with_limits")
            self.assertTrue(projection["uncertainties"])

    def test_paths_json_and_no_clobber_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            top = Path(temporary); root = top / "artifact"; root.mkdir(); outside = top / "outside"; outside.mkdir()
            owner = root / "owner.json"; write(owner, {"schema": "fixture-owner/1"})
            target = outside / "target.json"; value = V2._finalize({"schema": "fixture/1"}); write(target, value)
            (root / "link").symlink_to(outside, target_is_directory=True)
            escaped = {"path": "link/target.json", "sha256": hashlib.sha256(target.read_bytes()).hexdigest(), "size_bytes": target.stat().st_size, "schema": "fixture/1", "payload_sha256": value["payload_sha256"]}
            with self.assertRaisesRegex(V2.EvidenceOverlayError, "symlink"):
                V2._resolve(escaped, owner, "fixture/1")
            for raw in ("../outside/target.json", str(target)):
                bad = dict(escaped); bad["path"] = raw
                with self.assertRaises(V2.EvidenceOverlayError):
                    V2._binding_literal(bad, "fixture/1", "fixture")
            existing = root / "existing.json"; existing.write_text("sentinel\n", encoding="utf-8")
            with self.assertRaisesRegex(V2.EvidenceOverlayError, "overwrite"):
                V2._write(existing, {"safe": True})
            self.assertEqual(existing.read_text(encoding="utf-8"), "sentinel\n")
            concurrent = root / "concurrent.json"
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: self._write_result(concurrent), range(2)))
            self.assertEqual(sorted(results), ["created", "refused"])

            unknown = self.minimal_review_draft(); unknown["unknown"] = True
            duplicate = root / "duplicate.json"; duplicate.write_text('{"schema":"gaussian-scientific-maturity-review/2","schema":"duplicate"}\n', encoding="utf-8")
            nonfinite = root / "nonfinite.json"; nonfinite.write_text('{"value":NaN}\n', encoding="utf-8")
            unknown_path = root / "unknown.json"; write(unknown_path, unknown)
            for source in (duplicate, nonfinite, unknown_path):
                with self.assertRaises((ValueError, V2.EvidenceOverlayError)):
                    V2.finalize_review(source, root / f"{source.stem}-out.json")

    def _write_result(self, path: Path) -> str:
        try:
            V2._write(path, {"safe": True})
            return "created"
        except V2.EvidenceOverlayError:
            return "refused"

    def minimal_review_draft(self) -> dict:
        return {
            "schema": V2.REVIEW_SCHEMA, "review_id": "minimal_review", "study_id": "minimal_study", "base_gate_payload_sha256": "a" * 64,
            "edge_evidence": [], "minimum_evidence": [], "manual_claims": [], "review_decision": "blocked", "reviewer": "fixture", "reviewed_at": "2026-07-17T00:00:00Z", "review_notes": [],
            "calculation_ready": False, "no_submission_authorization": True, "no_method_selection_authorization": True, "no_input_generation_authorization": True, "payload_sha256": None,
        }

    def test_dependency_blockers_are_ignored_only_after_exact_recursive_projection(self) -> None:
        def node(node_id: str, blockers: list[str], dependencies: list[str], edge_ids: list[str]) -> dict:
            return {"node_id": node_id, "disposition": "planned", "depends_on": dependencies, "target": {"edge_ids": edge_ids}, "readiness": {"scientific": {"blocker_ids": blockers}}}
        exact = {"nodes": [
            node("minimum_owner", ["mechanism_support_channel_mapping_missing"], [], []),
            node("ts_owner", ["ts_owner_dependency_blocked", "mechanism_support_channel_mapping_missing"], ["minimum_owner"], ["edge_fixture"]),
        ]}
        self.assertEqual(
            V2._plan_edge_blockers(exact, "edge_fixture"),
            ["mechanism_support_channel_mapping_missing", "ts_owner_dependency_blocked"],
        )
        self.assertEqual(V2._plan_edge_blockers(exact, "edge_fixture", exact_mechanism_support_projection=True), [])
        unknown = copy.deepcopy(exact)
        unknown["nodes"][1]["readiness"]["scientific"]["blocker_ids"].append("unknown_dependency_blocked")
        self.assertEqual(
            V2._plan_edge_blockers(unknown, "edge_fixture", exact_mechanism_support_projection=True),
            ["unknown_dependency_blocked"],
        )
        unresolved_parent = copy.deepcopy(exact)
        unresolved_parent["nodes"][0]["readiness"]["scientific"]["blocker_ids"].append("minimum_identity_unresolved")
        self.assertEqual(
            V2._plan_edge_blockers(unresolved_parent, "edge_fixture", exact_mechanism_support_projection=True),
            ["minimum_identity_unresolved", "ts_owner_dependency_blocked"],
        )


if __name__ == "__main__":
    unittest.main()
