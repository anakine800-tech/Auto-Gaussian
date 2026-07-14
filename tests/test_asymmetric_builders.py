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
MODULE = ROOT / "skills" / "gaussian-asymmetric-catalysis" / "scripts" / "asymmetric_catalysis.py"
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
                "metal_m0_offline_design", "metal_m2a_candidate_audit_template",
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
            self.assertEqual(proposal["status"], "planned_not_submitted")
            self.assertFalse(proposal["calculation_ready"])
            self.assertEqual(proposal["chemical_system"]["candidate_id"], "wang2024_bf3_ts1")
            self.assertIsNone(proposal["proposed_gaussian"]["route"])
            with self.assertRaisesRegex(ASYM.OfflineError, "priority-1"):
                ASYM.propose_smoke(WANG_BF3 / "candidate-ledger.json", "wang2024_bf3_ts2_b1", root / "forbidden-smoke.json")

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
