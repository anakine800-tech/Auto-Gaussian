#!/usr/bin/env python3
"""End-to-end offline tests for deterministic asymmetric builders."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
MODULE = ROOT / "skills" / "auto-g16-asymmetric-catalysis" / "scripts" / "asymmetric_catalysis.py"
FIXTURES = ROOT / "tests" / "fixtures" / "asymmetric_catalysis"
WANG_BF3 = ROOT / "studies" / "wang_2024_bf3_ts"
SPEC = importlib.util.spec_from_file_location("asymmetric_catalysis", MODULE)
assert SPEC and SPEC.loader
ASYM = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ASYM)


def dump(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class AsymmetricBuilderTests(unittest.TestCase):
    def test_wang_bf3_literature_ledger_is_deterministic_and_current(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "first.json"
            second = Path(tmp) / "second.json"
            one = ASYM.build_literature_benchmark(WANG_BF3 / "benchmark-source.json", first)
            ASYM.build_literature_benchmark(WANG_BF3 / "benchmark-source.json", second)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(first.read_bytes(), (WANG_BF3 / "candidate-ledger.json").read_bytes())
            self.assertFalse(one["calculation_ready"])
            self.assertTrue(one["no_submission_authorization"])
            records = {item["candidate_id"]: item for item in one["candidates"]}
            self.assertEqual(set(records), {"wang2024_bf3_ts1", "wang2024_bf3_ts2_b1", "wang2024_bf3_ts2_b2"})
            self.assertEqual(records["wang2024_bf3_ts1"]["atom_inventory"]["atom_count"], 57)
            self.assertEqual(records["wang2024_bf3_ts2_b1"]["atom_inventory"]["atom_count"], 78)
            self.assertEqual(records["wang2024_bf3_ts2_b2"]["atom_inventory"]["atom_count"], 78)
            self.assertAlmostEqual(records["wang2024_bf3_ts1"]["coordinate_changes"][0]["distance_pairs"][0]["measured_from_coordinates_angstrom"], 1.42932434)
            self.assertAlmostEqual(records["wang2024_bf3_ts2_b1"]["coordinate_changes"][0]["distance_pairs"][0]["measured_from_coordinates_angstrom"], 2.15133529)
            serialized = first.read_text(encoding="utf-8").lower()
            for forbidden in ("qsub", "nprocshared", "/home/user100/sdl", "#p "):
                self.assertNotIn(forbidden, serialized)

    def test_wang_bf3_literature_builder_rejects_coordinate_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copytree(WANG_BF3, root / "case")
            source = root / "case" / "benchmark-source.json"
            geometry = root / "case" / "coordinates" / "bf3_ts1.xyz"
            text = geometry.read_text(encoding="utf-8").replace("2.69735000", "2.69745000", 1)
            geometry.write_text(text, encoding="utf-8")
            with self.assertRaisesRegex(ASYM.OfflineError, "coordinate-block hash mismatch"):
                ASYM.build_literature_benchmark(source, root / "tampered-ledger.json")

    def make_study(self, root: Path) -> Path:
        source = json.loads((FIXTURES / "boron_study.json").read_text())
        source["status"] = "draft"
        source["comparison_groups"][0]["coverage_dimension_ids"] = [
            "boron_center", "boron_coordination_state", "binding_mode",
            "catalyst_conformer", "approach_topology",
        ]
        source["coverage_dimensions"] = [
            {"dimension_id": "boron_center", "name": "B center", "applicable": True, "expected_levels": ["b_site_a"], "review_rule": "Enumerate reviewed B centers."},
            {"dimension_id": "boron_coordination_state", "name": "B coordination", "applicable": True, "expected_levels": ["three_coordinate"], "review_rule": "Enumerate coordination states."},
            {"dimension_id": "binding_mode", "name": "Binding mode", "applicable": True, "expected_levels": ["mono_o_at_b_site_a"], "review_rule": "Enumerate binding modes."},
            {"dimension_id": "catalyst_conformer", "name": "Catalyst conformer", "applicable": True, "expected_levels": ["cat_conf_a", "cat_conf_alias", "cat_conf_b"], "review_rule": "Enumerate and deduplicate conformers."},
            {"dimension_id": "approach_topology", "name": "Approach", "applicable": True, "expected_levels": ["topology_re", "topology_si"], "review_rule": "Enumerate channel-bound approaches."},
        ]
        source_path = root / "study-source.json"
        dump(source_path, source)
        study_path = root / "study.json"
        ASYM.build_study(source_path, study_path)
        return study_path

    def make_space(self, root: Path, study_path: Path) -> Path:
        space = {
            "schema": "gaussian-asymmetric-candidate-space-spec/1",
            "study_id": "fixture_boron_selectivity", "study_sha256": digest(study_path),
            "comparison_group_id": "boron_face_pair", "candidate_id_prefix": "boron_auto",
            "catalyst_state_ids": ["boron_free_state"], "geometry_dedup_tolerance_angstrom": 0.01,
            "dimensions": [
                {"dimension_id": "boron_center", "levels": [{"level_id": "b_site_a", "equivalence_key": "b_site_a", "metadata": {"catalyst_state_id": "boron_free_state", "atom_index": 1}}]},
                {"dimension_id": "boron_coordination_state", "levels": [{"level_id": "three_coordinate", "equivalence_key": "three_coordinate", "metadata": {"coordination_number": 3}}]},
                {"dimension_id": "binding_mode", "levels": [{"level_id": "mono_o_at_b_site_a", "equivalence_key": "mono_o_at_b_site_a", "metadata": {"boron_center": "b_site_a", "boron_coordination_state": "three_coordinate"}}]},
                {"dimension_id": "catalyst_conformer", "levels": [
                    {"level_id": "cat_conf_a", "equivalence_key": "cat_conf_a", "metadata": {}},
                    {"level_id": "cat_conf_alias", "equivalence_key": "cat_conf_a", "metadata": {}},
                    {"level_id": "cat_conf_b", "equivalence_key": "cat_conf_b", "metadata": {}},
                ]},
                {"dimension_id": "approach_topology", "levels": [
                    {"level_id": "topology_re", "equivalence_key": "topology_re", "metadata": {"channel_id": "channel_r"}},
                    {"level_id": "topology_si", "equivalence_key": "topology_si", "metadata": {"channel_id": "channel_s"}},
                ]},
            ],
            "exclusion_rules": [],
        }
        path = root / "space.json"
        dump(path, space)
        return path

    def materialization(self, candidate_id: str, geometry_name: str, face: str) -> dict:
        return {
            "candidate_id": candidate_id, "geometry_path": geometry_name, "geometry_format": "xyz",
            "chemical_state": {"identity": "synthetic B/substrate TS assembly", "charge": 0, "multiplicity": 1, "component_count": 1, "stereochemistry_status": "assigned"},
            "binding_mode": {"label": "mono_o_at_b_site_a", "coordination_contacts": [{"donor_atom": 3, "acceptor_atom": 1, "kind": "boron_coordination"}], "review_notes": "Synthetic test binding."},
            "approach_topology": {"label": f"topology_{face}", "substrate_face": face, "topology_notes": "Synthetic test topology."},
            "conformer_sources": [{"role": "complex", "conformer_id": "synthetic_conf", "source": {"path": "synthetic://conf.xyz", "sha256": "1" * 64}, "prescreen_method": "fixture", "prescreen_energy": 0.0, "energy_unit": "kcal_mol"}],
            "electronic_state": {"charge": 0, "multiplicity": 1, "oxidation_state_notes": "not applicable", "spin_state_notes": "closed-shell singlet fixture", "broken_symmetry": "not_applicable", "multireference_concern": "none_identified"},
            "atom_inventory": {"formula": "BCHO", "atom_count": 4, "element_counts": {"B": 1, "C": 1, "H": 1, "O": 1}, "inventory_key": "fixture_bcho_neutral_singlet"},
            "atom_map": [{"index": 1, "element": "B", "role": "boron", "source_atom_id": "b1"}, {"index": 2, "element": "C", "role": "forming_carbon", "source_atom_id": "c1"}, {"index": 3, "element": "O", "role": "donor", "source_atom_id": "o1"}, {"index": 4, "element": "H", "role": "hydrogen", "source_atom_id": "h1"}],
            "coordinate_changes": [{"kind": "forming", "atoms": [2, 3], "description": "Synthetic coordinate."}],
            "construction_method": "Deterministic synthetic XYZ fixture.", "stereochemistry_reviewed": False, "clash_reviewed": False, "resource_tier_proposal": "unresolved",
        }

    def prepare_candidates(self, root: Path):
        study_path = self.make_study(root)
        space_path = self.make_space(root, study_path)
        ledger_path = root / "ledger.json"
        ASYM.enumerate_boron(study_path, space_path, ledger_path)
        xyz = "4\nsynthetic\nB 0 0 0\nC 1.5 0 0\nO 0 1.4 0\nH 0 0 1.1\n"
        (root / "r.xyz").write_text(xyz)
        (root / "s.xyz").write_text(xyz)
        ledger = json.loads(ledger_path.read_text())
        records = []
        for entry in ledger["entries"]:
            if entry["status"] == "unmaterialized":
                face = "re" if entry["channel_id"] == "channel_r" else "si"
                records.append(self.materialization(entry["candidate_id"], f"{'r' if face == 're' else 's'}.xyz", face))
        spec_path = root / "materializations.json"
        dump(spec_path, {"schema": "gaussian-asymmetric-materializations/1", "ledger_sha256": digest(ledger_path), "records": records})
        output_dir = root / "candidates"
        updated = ASYM.materialize_candidates(study_path, ledger_path, spec_path, output_dir)
        return study_path, output_dir / "candidate-ledger.json", updated, output_dir

    def test_study_builder_and_boron_enumerator_are_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            study = self.make_study(root)
            source = root / "study-source.json"
            second = root / "study-second.json"
            ASYM.build_study(source, second)
            self.assertEqual(study.read_bytes(), second.read_bytes())
            space = self.make_space(root, study)
            ledger = root / "ledger.json"
            data = ASYM.enumerate_boron(study, space, ledger)
            self.assertEqual(data["counts"]["retained"], 4)
            self.assertEqual(data["counts"]["logical_duplicates"], 2)
            self.assertEqual(data["counts"]["excluded"], 6)

    def test_materialization_preserves_channels_and_deduplicates_geometry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, _, ledger, _ = self.prepare_candidates(Path(tmp))
            self.assertEqual(ledger["counts"]["materialized_unique"], 2)
            self.assertEqual(ledger["counts"]["geometry_duplicates"], 2)
            unique = [entry for entry in ledger["entries"] if entry["status"] == "materialized_unique"]
            self.assertEqual({entry["channel_id"] for entry in unique}, {"channel_r", "channel_s"})

    def make_ts_evidence(self, root: Path, candidate: Path, energy: float):
        c = json.loads(candidate.read_text())
        ts_path = root / f"{c['candidate_id']}-ts.json"
        ts = {"schema": "gaussian-ts-freq-result/1", "status": "completed", "normal_termination_count": 1, "error_termination_count": 0, "optimization_completed": True, "stationary_point_found": True, "frequency_count": 3, "frequencies_cm-1": [-250.0, 100.0, 200.0], "raw_imaginary_frequency_count": 1, "imaginary_modes": [{"frequency_cm-1": -250.0}], "first_order_saddle_candidate": True, "diagnostics": []}
        dump(ts_path, ts)
        review_path = root / f"{c['candidate_id']}-review.json"
        dump(review_path, {"schema": "gaussian-ts-mode-review/1", "ts_result_sha256": digest(ts_path), "scientific_decision": "required"})
        decision_path = root / f"{c['candidate_id']}-decision.json"
        dump(decision_path, {"schema": "gaussian-ts-mode-decision/1", "mode_review_sha256": digest(review_path), "ts_result_sha256": digest(ts_path), "decision": "accepted", "confirmed": True})
        energy_path = root / f"{c['candidate_id']}-energy.json"
        dump(energy_path, {"schema": "gaussian-asymmetric-energy-record/1", "result_id": f"res_{c['candidate_id']}", "candidate_id": c["candidate_id"], "energy_unit": "kcal_mol", "electronic_energy": None, "thermal_gibbs_correction": None, "comparison_free_energy": energy, "comparison_energy_definition": "Synthetic common-zero free energy", "temperature_k": 298.15, "standard_state": "1M", "low_frequency_policy": "raw harmonic fixture values; no correction", "inventory_key": "fixture_bcho_neutral_singlet", "degeneracy": 1})
        output = root / f"{c['candidate_id']}-result.json"
        ASYM.ingest_result(candidate, ts_path, energy_path, output, review_path, decision_path)
        return output

    def test_result_ingestion_boltzmann_ee_and_sensitivity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            study, ledger_path, ledger, candidates = self.prepare_candidates(root)
            unique = [entry for entry in ledger["entries"] if entry["status"] == "materialized_unique"]
            for entry in unique:
                candidate_path = candidates / f"{entry['candidate_id']}.json"
                candidate = json.loads(candidate_path.read_text())
                candidate["review_status"] = "promoted_offline"
                candidate["review"] = {"reviewer": "fixture", "decision": "promoted_offline", "decision_record": None}
                dump(candidate_path, candidate)
                entry["candidate_artifact"]["sha256"] = digest(candidate_path)
            dump(ledger_path, ledger)
            paths = []
            for entry in unique:
                energy = 10.0 if entry["channel_id"] == "channel_r" else 11.5
                paths.append(self.make_ts_evidence(root, candidates / f"{entry['candidate_id']}.json", energy))
            analysis_path = root / "analysis.json"
            analysis = ASYM.aggregate(study, ledger_path, paths, analysis_path, 1.0)
            self.assertEqual(analysis["status"], "provisional")
            self.assertEqual(analysis["selectivity"]["major_channel_id"], "channel_r")
            self.assertAlmostEqual(analysis["selectivity"]["ee_percent"], 85.267, places=2)
            self.assertGreaterEqual(len(analysis["uncertainty"]["sensitivity_scenarios"]), 2)

    def test_metal_design_and_smoke_proposal_preserve_refusal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            metal = root / "metal.json"
            smoke = root / "smoke.json"
            design = ASYM.design_metal_support(FIXTURES / "metal_study.json", metal)
            proposal = ASYM.propose_smoke(WANG_BF3 / "candidate-ledger.json", "wang2024_bf3_ts1", smoke)
            self.assertEqual(design["submission_decision"], "refused")
            self.assertEqual(design["runtime_support_status"], "unsupported_requires_extension")
            self.assertEqual(design["scope"]["priority"], "transition_metal_ts_design_first")
            self.assertEqual(design["scope"]["execution_scope"], "no_transition_metal_execution")
            self.assertEqual(len(design["states"]), 1)
            self.assertIsNone(design["states"][0]["metal_centers"][0]["d_electron_count"])
            self.assertEqual(design["states"][0]["ts_search_readiness"]["status"], "blocked_offline_design_only")
            strategies = {item["strategy"] for item in design["ts_search_families"][0]["seed_strategy_candidates"]}
            self.assertEqual(strategies, {"single_guess_hessian_guided", "endpoint_qst2_qst3", "reviewed_relaxed_coordinate_scan"})
            self.assertTrue(all(item["status"] == "design_candidate_not_selected" for item in design["ts_search_families"][0]["seed_strategy_candidates"]))
            self.assertEqual(design["extension_milestones"][0]["status"], "implemented_offline")
            implemented = {
                item["milestone_id"]
                for item in design["extension_milestones"]
                if item["status"] == "implemented_offline"
            }
            self.assertEqual(implemented, {
                "metal_m0_offline_design", "metal_m1_review_contract",
                "metal_m2a_candidate_audit_template",
                "metal_m2b_result_observation",
                "metal_m2c_input_observation",
                "metal_m2d_acceptance_review_contract",
            })
            audit_template_path = root / "metal-ts-audit-template.json"
            audit_template = ASYM.build_metal_ts_audit_template(
                metal, FIXTURES / "metal_candidate.json", audit_template_path
            )
            second_audit_template_path = root / "metal-ts-audit-template-second.json"
            ASYM.build_metal_ts_audit_template(
                metal, FIXTURES / "metal_candidate.json", second_audit_template_path
            )
            self.assertEqual(
                audit_template_path.read_bytes(), second_audit_template_path.read_bytes()
            )
            self.assertEqual(audit_template["submission_decision"], "refused")
            self.assertEqual(audit_template["claim_ceiling"], "design_only_no_ts_or_selectivity_claim")
            self.assertEqual(set(audit_template["audit_sections"]), {
                "electron_accounting", "spin_surface", "wavefunction",
                "coordination", "method_protocol", "ts_and_path",
            })
            self.assertEqual(len(audit_template["seed_strategy_gate"]["inventory"]), 3)
            self.assertTrue(all(
                contact["distance_window_angstrom"] is None
                for contact in audit_template["identity_binding"]["coordination_contacts"]
            ))
            review_path = root / "metal-scientific-review.json"
            review = ASYM.build_metal_scientific_review(
                metal,
                audit_template_path,
                FIXTURES / "metal_candidate.json",
                FIXTURES / "metal_scientific_review_complete.json",
                review_path,
            )
            second_review_path = root / "metal-scientific-review-second.json"
            ASYM.build_metal_scientific_review(
                metal,
                audit_template_path,
                FIXTURES / "metal_candidate.json",
                FIXTURES / "metal_scientific_review_complete.json",
                second_review_path,
            )
            self.assertEqual(review_path.read_bytes(), second_review_path.read_bytes())
            self.assertEqual(review["status"], "review_contract_complete_runtime_unsupported")
            self.assertEqual(review["scientific_acceptance_decision"], "not_granted_by_artifact")
            self.assertEqual(
                review["completion"]["metal_m1_scientific_review_status"],
                "not_satisfied_synthetic_fixture",
            )
            self.assertFalse(review["literature_values_are_defaults"])
            self.assertFalse(review["calculation_ready"])

            input_observation_path = root / "metal-input-observation.json"
            input_observation = ASYM.audit_metal_input_observation(
                audit_template_path,
                FIXTURES / "metal_candidate.json",
                review_path,
                FIXTURES / "metal_input_observation.gjf",
                input_observation_path,
            )
            second_input_observation_path = root / "metal-input-observation-second.json"
            ASYM.audit_metal_input_observation(
                audit_template_path,
                FIXTURES / "metal_candidate.json",
                review_path,
                FIXTURES / "metal_input_observation.gjf",
                second_input_observation_path,
            )
            self.assertEqual(input_observation_path.read_bytes(), second_input_observation_path.read_bytes())
            self.assertEqual(input_observation["status"], "parsed_input_observation_blocked")
            self.assertEqual(input_observation["input_acceptance_decision"], "not_granted_by_artifact")
            self.assertEqual(input_observation["protocol_selection_decision"], "absent_not_authorized")
            self.assertEqual(input_observation["promotion_decision"], "refused")
            self.assertEqual(input_observation["submission_decision"], "refused")
            self.assertFalse(input_observation["parser"]["renders_input"])
            self.assertEqual(input_observation["input_observations"]["atom_count"], 7)
            self.assertTrue(input_observation["input_observations"]["task_text_observations"]["ts_text_observed"])
            self.assertTrue(all(
                section["status"] == "blocked_pending_review"
                for section in input_observation["audit_sections"].values()
            ))

            incomplete_review_path = root / "metal-scientific-review-incomplete.json"
            incomplete_review = ASYM.build_metal_scientific_review(
                metal,
                audit_template_path,
                FIXTURES / "metal_candidate.json",
                FIXTURES / "metal_scientific_review_incomplete.json",
                incomplete_review_path,
            )
            self.assertEqual(incomplete_review["status"], "blocked_incomplete_scientific_review")
            self.assertEqual(len(incomplete_review["completion"]["blocked_sections"]), 6)
            self.assertIsNone(
                incomplete_review["sections"]["electron_accounting"]["facts"]["total_valence_electron_count"]
            )
            incomplete_input_observation = ASYM.audit_metal_input_observation(
                audit_template_path,
                FIXTURES / "metal_candidate.json",
                incomplete_review_path,
                FIXTURES / "metal_input_observation.gjf",
                root / "metal-input-observation-incomplete-m1.json",
            )
            self.assertEqual(
                incomplete_input_observation["review_binding"]["metal_m1_scientific_review_status"],
                "pending_scientific_review",
            )
            self.assertEqual(
                incomplete_input_observation["input_acceptance_decision"],
                "not_granted_by_artifact",
            )
            observation_path = root / "metal-result-observation.json"
            observation = ASYM.audit_metal_result_observation(
                audit_template_path,
                FIXTURES / "metal_candidate.json",
                FIXTURES / "metal_observation_success.txt",
                observation_path,
            )
            second_observation_path = root / "metal-result-observation-second.json"
            ASYM.audit_metal_result_observation(
                audit_template_path,
                FIXTURES / "metal_candidate.json",
                FIXTURES / "metal_observation_success.txt",
                second_observation_path,
            )
            self.assertEqual(observation_path.read_bytes(), second_observation_path.read_bytes())
            self.assertEqual(observation["status"], "parsed_observation_blocked")
            self.assertFalse(observation["calculation_ready"])
            self.assertEqual(observation["promotion_decision"], "refused")
            self.assertEqual(observation["frequency_observations"]["raw_imaginary_frequency_count"], 1)
            self.assertTrue(observation["frequency_observations"]["exactly_one_raw_imaginary_observed"])
            self.assertEqual(observation["frequency_observations"]["mode_review_status"], "not_performed")
            self.assertTrue(all(
                section["status"] == "blocked_pending_review"
                for section in observation["audit_sections"].values()
            ))
            self.assertTrue(all(
                contact["review_status"] == "observed_unreviewed_no_window"
                for contact in observation["coordination_observations"]["contacts"]
            ))
            acceptance_path = root / "metal-acceptance-review.json"
            acceptance = ASYM.build_metal_acceptance_review(
                audit_template_path,
                FIXTURES / "metal_candidate.json",
                review_path,
                input_observation_path,
                observation_path,
                FIXTURES / "metal_acceptance_review_complete.json",
                acceptance_path,
            )
            second_acceptance_path = root / "metal-acceptance-review-second.json"
            ASYM.build_metal_acceptance_review(
                audit_template_path,
                FIXTURES / "metal_candidate.json",
                review_path,
                input_observation_path,
                observation_path,
                FIXTURES / "metal_acceptance_review_complete.json",
                second_acceptance_path,
            )
            self.assertEqual(acceptance_path.read_bytes(), second_acceptance_path.read_bytes())
            self.assertEqual(acceptance["status"], "acceptance_record_complete_runtime_unsupported")
            self.assertEqual(acceptance["decision_summary"]["metal_m2_acceptance_review_status"], "not_satisfied_synthetic_fixture")
            self.assertEqual(acceptance["scientific_acceptance_decision"], "not_granted_by_artifact")
            self.assertEqual(acceptance["input_acceptance_decision"], "not_granted_by_artifact")
            self.assertEqual(acceptance["mode_acceptance_decision"], "not_granted_by_artifact")
            self.assertEqual(acceptance["promotion_decision"], "refused")

            incomplete_acceptance = ASYM.build_metal_acceptance_review(
                audit_template_path,
                FIXTURES / "metal_candidate.json",
                review_path,
                input_observation_path,
                observation_path,
                FIXTURES / "metal_acceptance_review_incomplete.json",
                root / "metal-acceptance-review-incomplete.json",
            )
            self.assertEqual(incomplete_acceptance["status"], "blocked_incomplete_acceptance_review")
            self.assertEqual(len(incomplete_acceptance["decision_summary"]["blocked_sections"]), 4)
            serialized_observation = observation_path.read_text(encoding="utf-8").lower()
            for forbidden in ("qsub", "#p ", "/home/user100/sdl", "gaussian-asymmetric-ts-result/1"):
                self.assertNotIn(forbidden, serialized_observation)

            incomplete_path = root / "metal-result-incomplete.json"
            incomplete = ASYM.audit_metal_result_observation(
                audit_template_path,
                FIXTURES / "metal_candidate.json",
                FIXTURES / "metal_observation_incomplete.txt",
                incomplete_path,
            )
            self.assertEqual(incomplete["termination_observations"]["error_termination_count"], 1)
            self.assertEqual(incomplete["frequency_observations"]["frequency_count"], 0)
            self.assertEqual(incomplete["status"], "parsed_observation_blocked")
            self.assertEqual(proposal["status"], "planned_not_submitted")
            self.assertFalse(proposal["calculation_ready"])
            self.assertEqual(proposal["chemical_system"]["candidate_id"], "wang2024_bf3_ts1")
            self.assertIsNone(proposal["proposed_gaussian"]["route"])
            with self.assertRaisesRegex(ASYM.OfflineError, "priority-1"):
                ASYM.propose_smoke(WANG_BF3 / "candidate-ledger.json", "wang2024_bf3_ts2_b1", root / "forbidden-smoke.json")

    def test_metal_input_observation_rejects_identity_route_and_authority_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            design_path = root / "metal-support.json"
            template_path = root / "metal-template.json"
            review_path = root / "metal-review.json"
            ASYM.design_metal_support(FIXTURES / "metal_study.json", design_path)
            ASYM.build_metal_ts_audit_template(
                design_path, FIXTURES / "metal_candidate.json", template_path
            )
            ASYM.build_metal_scientific_review(
                design_path,
                template_path,
                FIXTURES / "metal_candidate.json",
                FIXTURES / "metal_scientific_review_complete.json",
                review_path,
            )
            source = (FIXTURES / "metal_input_observation.gjf").read_text(encoding="utf-8")

            wrong_charge = root / "wrong-charge.gjf"
            wrong_charge.write_text(source.replace("\n0 1\nPd", "\n1 1\nPd"), encoding="utf-8")
            with self.assertRaisesRegex(ASYM.OfflineError, "charge/multiplicity differs"):
                ASYM.audit_metal_input_observation(
                    template_path, FIXTURES / "metal_candidate.json", review_path,
                    wrong_charge, root / "wrong-charge.json",
                )

            wrong_order = root / "wrong-order.gjf"
            wrong_order.write_text(
                source.replace("P   2.000000", "C   2.000000", 1), encoding="utf-8"
            )
            with self.assertRaisesRegex(ASYM.OfflineError, "atom order differs"):
                ASYM.audit_metal_input_observation(
                    template_path, FIXTURES / "metal_candidate.json", review_path,
                    wrong_order, root / "wrong-order.json",
                )

            link1 = root / "link1.gjf"
            link1.write_text(source + "\n--Link1--\n", encoding="utf-8")
            with self.assertRaisesRegex(ASYM.OfflineError, "multi-step"):
                ASYM.audit_metal_input_observation(
                    template_path, FIXTURES / "metal_candidate.json", review_path,
                    link1, root / "link1.json",
                )

            geom_check = root / "geom-check.gjf"
            geom_check.write_text(
                source.replace("#p synthetic_fixture", "#p synthetic_fixture geom=check"),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ASYM.OfflineError, "Geom=Check"):
                ASYM.audit_metal_input_observation(
                    template_path, FIXTURES / "metal_candidate.json", review_path,
                    geom_check, root / "geom-check.json",
                )

            absolute_and_trailing = root / "absolute-and-trailing.gjf"
            absolute_and_trailing.write_text(
                source.replace(
                    "%chk=synthetic_metal_fixture.chk",
                    "%chk=/outside_unvalidated/fixture.chk",
                ) + "\nPd 0\n****\n",
                encoding="utf-8",
            )
            edge_observation = ASYM.audit_metal_input_observation(
                template_path, FIXTURES / "metal_candidate.json", review_path,
                absolute_and_trailing, root / "absolute-and-trailing.json",
            )
            self.assertTrue(
                edge_observation["input_observations"]["contains_absolute_link0_path_observed"]
            )
            self.assertEqual(edge_observation["input_observations"]["trailing_section_line_count"], 2)
            self.assertIsNotNone(edge_observation["input_observations"]["trailing_section_sha256"])
            self.assertEqual(
                edge_observation["input_observations"]["remote_path_validation_status"],
                "not_performed_offline_no_execution_authority",
            )

            widened_review = json.loads(review_path.read_text(encoding="utf-8"))
            widened_review["scientific_acceptance_decision"] = "accepted"
            widened_review["review_payload_sha256"] = ASYM.sha256_data({
                key: value for key, value in widened_review.items()
                if key != "review_payload_sha256"
            })
            widened_review_path = root / "widened-review.json"
            widened_review_path.write_text(
                json.dumps(widened_review, sort_keys=True), encoding="utf-8"
            )
            with self.assertRaisesRegex(ASYM.OfflineError, "widened authority"):
                ASYM.audit_metal_input_observation(
                    template_path, FIXTURES / "metal_candidate.json", widened_review_path,
                    FIXTURES / "metal_input_observation.gjf", root / "widened.json",
                )

    def test_metal_result_observation_rejects_identity_and_lineage_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            design_path = root / "metal-support.json"
            template_path = root / "metal-template.json"
            ASYM.design_metal_support(FIXTURES / "metal_study.json", design_path)
            ASYM.build_metal_ts_audit_template(
                design_path, FIXTURES / "metal_candidate.json", template_path
            )

            wrong_charge = root / "wrong-charge.log"
            wrong_charge.write_text(
                (FIXTURES / "metal_observation_success.txt").read_text(encoding="utf-8").replace(
                    "Charge = 0 Multiplicity = 1", "Charge = 1 Multiplicity = 1"
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ASYM.OfflineError, "charge/multiplicity differs"):
                ASYM.audit_metal_result_observation(
                    template_path, FIXTURES / "metal_candidate.json", wrong_charge,
                    root / "wrong-charge.json",
                )

            wrong_order = root / "wrong-order.log"
            wrong_order.write_text(
                (FIXTURES / "metal_observation_success.txt").read_text(encoding="utf-8").replace(
                    "      1         46           0", "      1         15           0"
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ASYM.OfflineError, "atom order differs"):
                ASYM.audit_metal_result_observation(
                    template_path, FIXTURES / "metal_candidate.json", wrong_order,
                    root / "wrong-order.json",
                )

            tampered_template = json.loads(template_path.read_text(encoding="utf-8"))
            tampered_template["candidate_id"] = "metal_ts_drifted"
            tampered_path = root / "tampered-template.json"
            dump(tampered_path, tampered_template)
            with self.assertRaisesRegex(ASYM.OfflineError, "payload hash mismatch"):
                ASYM.audit_metal_result_observation(
                    tampered_path, FIXTURES / "metal_candidate.json",
                    FIXTURES / "metal_observation_success.txt", root / "tampered.json",
                )

            bypassed_template = json.loads(template_path.read_text(encoding="utf-8"))
            bypassed_template["audit_sections"]["wavefunction"]["status"] = "accepted"
            bypassed_template["template_payload_sha256"] = ASYM.sha256_data(
                {
                    key: value
                    for key, value in bypassed_template.items()
                    if key != "template_payload_sha256"
                }
            )
            bypassed_path = root / "bypassed-template.json"
            dump(bypassed_path, bypassed_template)
            with self.assertRaisesRegex(ASYM.OfflineError, "bypassed a scientific review gate"):
                ASYM.audit_metal_result_observation(
                    bypassed_path, FIXTURES / "metal_candidate.json",
                    FIXTURES / "metal_observation_success.txt", root / "bypassed.json",
                )

    def test_metal_acceptance_review_records_rejection_and_refuses_missing_acceptance_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            design = root / "design.json"
            template = root / "template.json"
            review = root / "review.json"
            input_observation = root / "input.json"
            result_observation = root / "result.json"
            ASYM.design_metal_support(FIXTURES / "metal_study.json", design)
            ASYM.build_metal_ts_audit_template(design, FIXTURES / "metal_candidate.json", template)
            ASYM.build_metal_scientific_review(
                design, template, FIXTURES / "metal_candidate.json",
                FIXTURES / "metal_scientific_review_complete.json", review,
            )
            ASYM.audit_metal_input_observation(
                template, FIXTURES / "metal_candidate.json", review,
                FIXTURES / "metal_input_observation.gjf", input_observation,
            )
            ASYM.audit_metal_result_observation(
                template, FIXTURES / "metal_candidate.json",
                FIXTURES / "metal_observation_success.txt", result_observation,
            )
            source = json.loads(
                (FIXTURES / "metal_acceptance_review_complete.json").read_text(encoding="utf-8")
            )

            scope_flip = copy.deepcopy(source)
            scope_flip["scope"]["scope_kind"] = "reviewer_bound_real_case"
            scope_flip_path = root / "scope-flip-source.json"
            dump(scope_flip_path, scope_flip)
            with self.assertRaisesRegex(ASYM.OfflineError, "upstream real non-synthetic M1"):
                ASYM.build_metal_acceptance_review(
                    template, FIXTURES / "metal_candidate.json", review,
                    input_observation, result_observation, scope_flip_path,
                    root / "scope-flip-review.json",
                )

            missing_reviewer = copy.deepcopy(scope_flip)
            missing_reviewer["scope"]["reviewer"] = ""
            missing_reviewer_path = root / "missing-reviewer-source.json"
            dump(missing_reviewer_path, missing_reviewer)
            with self.assertRaisesRegex(ASYM.OfflineError, "non-empty reviewer"):
                ASYM.build_metal_acceptance_review(
                    template, FIXTURES / "metal_candidate.json", review,
                    input_observation, result_observation, missing_reviewer_path,
                    root / "missing-reviewer-review.json",
                )

            invalid_date = copy.deepcopy(scope_flip)
            invalid_date["scope"]["review_date"] = "2026-02-30"
            invalid_date_path = root / "invalid-date-source.json"
            dump(invalid_date_path, invalid_date)
            with self.assertRaisesRegex(ASYM.OfflineError, "valid ISO review date"):
                ASYM.build_metal_acceptance_review(
                    template, FIXTURES / "metal_candidate.json", review,
                    input_observation, result_observation, invalid_date_path,
                    root / "invalid-date-review.json",
                )

            rejected = copy.deepcopy(source)
            rejected["review_id"] = "fixture_metal_m2_rejected"
            rejected["sections"]["wavefunction"]["decision"] = "rejected_by_reviewer"
            rejected["sections"]["wavefunction"]["blockers"] = ["Synthetic reviewer rejection token."]
            rejected_path = root / "rejected-source.json"
            dump(rejected_path, rejected)
            rejected_review = ASYM.build_metal_acceptance_review(
                template, FIXTURES / "metal_candidate.json", review,
                input_observation, result_observation, rejected_path,
                root / "rejected-review.json",
            )
            self.assertEqual(rejected_review["status"], "acceptance_record_contains_rejection_runtime_unsupported")
            self.assertEqual(rejected_review["decision_summary"]["metal_m2_acceptance_review_status"], "reviewer_rejected")
            self.assertEqual(rejected_review["promotion_decision"], "refused")

            missing_mode = copy.deepcopy(source)
            missing_mode["review_id"] = "fixture_metal_m2_missing_mode"
            missing_mode["sections"]["mode"]["facts"]["mode_evidence_sha256"] = None
            missing_mode_path = root / "missing-mode.json"
            dump(missing_mode_path, missing_mode)
            with self.assertRaisesRegex(ASYM.OfflineError, "mode evidence hash"):
                ASYM.build_metal_acceptance_review(
                    template, FIXTURES / "metal_candidate.json", review,
                    input_observation, result_observation, missing_mode_path,
                    root / "missing-mode-review.json",
                )

            unreviewed_input = copy.deepcopy(source)
            unreviewed_input["review_id"] = "fixture_metal_m2_unreviewed_input"
            unreviewed_input["sections"]["input_acceptance"]["facts"]["route_reviewed"] = False
            unreviewed_input_path = root / "unreviewed-input.json"
            dump(unreviewed_input_path, unreviewed_input)
            with self.assertRaisesRegex(ASYM.OfflineError, "route_reviewed was not reviewed"):
                ASYM.build_metal_acceptance_review(
                    template, FIXTURES / "metal_candidate.json", review,
                    input_observation, result_observation, unreviewed_input_path,
                    root / "unreviewed-input-review.json",
                )

            lineage_drift = copy.deepcopy(source)
            lineage_drift["review_id"] = "fixture_metal_m2_lineage_drift"
            lineage_drift["source_bindings"]["result_observation_sha256"] = "0" * 64
            lineage_drift_path = root / "lineage-drift.json"
            dump(lineage_drift_path, lineage_drift)
            with self.assertRaisesRegex(ASYM.OfflineError, "hash binding mismatch"):
                ASYM.build_metal_acceptance_review(
                    template, FIXTURES / "metal_candidate.json", review,
                    input_observation, result_observation, lineage_drift_path,
                    root / "lineage-drift-review.json",
                )

    def test_metal_scientific_review_rejects_lineage_defaults_and_strategy_bypass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            design_path = root / "metal-support.json"
            template_path = root / "metal-template.json"
            ASYM.design_metal_support(FIXTURES / "metal_study.json", design_path)
            ASYM.build_metal_ts_audit_template(
                design_path, FIXTURES / "metal_candidate.json", template_path
            )

            wrong_hash = json.loads(
                (FIXTURES / "metal_scientific_review_complete.json").read_text(encoding="utf-8")
            )
            wrong_hash["candidate_sha256"] = "f" * 64
            wrong_hash_path = root / "wrong-hash.json"
            dump(wrong_hash_path, wrong_hash)
            with self.assertRaisesRegex(ASYM.OfflineError, "candidate hash mismatch"):
                ASYM.build_metal_scientific_review(
                    design_path, template_path, FIXTURES / "metal_candidate.json",
                    wrong_hash_path, root / "wrong-hash-review.json",
                )

            scope_flip = json.loads(
                (FIXTURES / "metal_scientific_review_complete.json").read_text(encoding="utf-8")
            )
            scope_flip["provenance"]["scope_kind"] = "primary_literature_bound_review"
            scope_flip_path = root / "scope-flip.json"
            dump(scope_flip_path, scope_flip)
            with self.assertRaisesRegex(ASYM.OfflineError, "primary-literature scope"):
                ASYM.build_metal_scientific_review(
                    design_path, template_path, FIXTURES / "metal_candidate.json",
                    scope_flip_path, root / "scope-flip-review.json",
                )

            selected_execution = json.loads(
                (FIXTURES / "metal_scientific_review_complete.json").read_text(encoding="utf-8")
            )
            selected_execution["sections"]["ts_and_path"]["facts"]["execution_selection_status"] = "selected"
            selected_execution_path = root / "selected-execution.json"
            dump(selected_execution_path, selected_execution)
            with self.assertRaisesRegex(ASYM.OfflineError, "must not select an execution strategy"):
                ASYM.build_metal_scientific_review(
                    design_path, template_path, FIXTURES / "metal_candidate.json",
                    selected_execution_path, root / "selected-execution-review.json",
                )

            outside_strategy = json.loads(
                (FIXTURES / "metal_scientific_review_complete.json").read_text(encoding="utf-8")
            )
            outside_strategy["sections"]["ts_and_path"]["facts"]["reviewed_strategy_candidate_id"] = "mts_outside_inventory"
            outside_strategy_path = root / "outside-strategy.json"
            dump(outside_strategy_path, outside_strategy)
            with self.assertRaisesRegex(ASYM.OfflineError, "differs from the design inventory"):
                ASYM.build_metal_scientific_review(
                    design_path, template_path, FIXTURES / "metal_candidate.json",
                    outside_strategy_path, root / "outside-strategy-review.json",
                )

            blocked_with_no_reason = json.loads(
                (FIXTURES / "metal_scientific_review_incomplete.json").read_text(encoding="utf-8")
            )
            blocked_with_no_reason["sections"]["method_protocol"]["blockers"] = []
            blocked_with_no_reason_path = root / "blocked-no-reason.json"
            dump(blocked_with_no_reason_path, blocked_with_no_reason)
            with self.assertRaisesRegex(ASYM.OfflineError, "blocked status lacks blockers"):
                ASYM.build_metal_scientific_review(
                    design_path, template_path, FIXTURES / "metal_candidate.json",
                    blocked_with_no_reason_path, root / "blocked-no-reason-review.json",
                )

            bypassed_template = json.loads(template_path.read_text(encoding="utf-8"))
            bypassed_template["audit_sections"]["coordination"]["status"] = "accepted"
            bypassed_template["template_payload_sha256"] = ASYM.sha256_data(
                {
                    key: value
                    for key, value in bypassed_template.items()
                    if key != "template_payload_sha256"
                }
            )
            bypassed_template_path = root / "review-bypassed-template.json"
            dump(bypassed_template_path, bypassed_template)
            with self.assertRaisesRegex(ASYM.OfflineError, "review gate was bypassed"):
                ASYM.build_metal_scientific_review(
                    design_path, bypassed_template_path,
                    FIXTURES / "metal_candidate.json",
                    FIXTURES / "metal_scientific_review_complete.json",
                    root / "review-bypassed-template-output.json",
                )

    def test_result_ingestion_refuses_transition_metal_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ts = root / "ts.json"
            energy = root / "energy.json"
            dump(ts, {"schema": "gaussian-ts-freq-result/1"})
            dump(energy, {"schema": "gaussian-asymmetric-energy-record/1"})
            with self.assertRaisesRegex(ASYM.OfflineError, "refuses unsupported"):
                ASYM.ingest_result(FIXTURES / "metal_candidate.json", ts, energy, root / "result.json")

    def test_builder_rejects_nonstandard_json_and_duplicate_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            nonfinite = root / "nonfinite.json"
            nonfinite.write_text('{"study_id":"fixture_study","temperature_k":NaN}\n')
            with self.assertRaisesRegex(ASYM.OfflineError, "non-standard JSON numeric constant"):
                ASYM.load_json(nonfinite)

            duplicate = root / "duplicate.json"
            duplicate.write_text('{"study_id":"fixture_one","study_id":"fixture_two"}\n')
            with self.assertRaisesRegex(ASYM.OfflineError, "duplicate JSON object key"):
                ASYM.load_json(duplicate)

    def test_builder_refuses_to_overwrite_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = json.loads((FIXTURES / "boron_study.json").read_text())
            source_path = root / "source.json"
            output = root / "study.json"
            dump(source_path, source)
            ASYM.build_study(source_path, output)
            with self.assertRaisesRegex(ASYM.OfflineError, "refusing to overwrite"):
                ASYM.build_study(source_path, output)


if __name__ == "__main__":
    unittest.main()
