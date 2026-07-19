#!/usr/bin/env python3
"""Offline provenance and tampering tests for asymmetric-catalysis builders."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
MODULE = ROOT / "skills" / "auto-g16-asymmetric-catalysis" / "scripts" / "asymmetric_catalysis.py"
FIXTURES = ROOT / "tests" / "fixtures" / "asymmetric_catalysis"
SPEC = importlib.util.spec_from_file_location("asymmetric_catalysis_provenance", MODULE)
assert SPEC and SPEC.loader
ASYM = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ASYM)


def dump(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class AsymmetricProvenanceTests(unittest.TestCase):
    def load_fixture(self, name: str) -> dict:
        return json.loads((FIXTURES / name).read_text(encoding="utf-8"))

    def atom_order(self, candidate: dict) -> list[dict]:
        return [
            {"index": atom["index"], "atomic_number": ASYM.ATOMIC_NUMBERS[atom["element"]], "element": atom["element"]}
            for atom in candidate["atom_map"]
        ]

    def make_ingest_chain(self, root: Path) -> dict[str, Path]:
        candidate_path = root / "candidate.json"
        candidate = self.load_fixture("boron_candidate_r.json")
        dump(candidate_path, candidate)
        order = self.atom_order(candidate)

        input_path = root / "ts.gjf"
        input_path.write_text("reviewed offline TS input fixture\n", encoding="utf-8")
        log_path = root / "ts.log"
        log_path.write_text("reviewed offline TS log fixture\n", encoding="utf-8")
        checkpoint_path = root / "ts.chk"
        checkpoint_path.write_bytes(b"reviewed offline checkpoint fixture")

        ts_path = root / "ts-result.json"
        ts = {
            "schema": "gaussian-ts-freq-result/1", "status": "completed",
            "normal_termination_count": 1, "error_termination_count": 0,
            "optimization_completed": True, "stationary_point_found": True,
            "frequency_count": 3, "frequencies_cm-1": [-250.0, 100.0, 200.0],
            "raw_imaginary_frequency_count": 1,
            "imaginary_modes": [{"frequency_cm-1": -250.0, "displacements": copy.deepcopy(order)}],
            "first_order_saddle_candidate": True, "final_coordinates": copy.deepcopy(order),
            "log_sha256": digest(log_path), "diagnostics": [],
        }
        dump(ts_path, ts)
        review_path = root / "mode-review.json"
        dump(review_path, {"schema": "gaussian-ts-mode-review/1", "ts_result_sha256": digest(ts_path), "scientific_decision": "required"})
        decision_path = root / "mode-decision.json"
        dump(decision_path, {"schema": "gaussian-ts-mode-decision/1", "ts_result_sha256": digest(ts_path), "mode_review_sha256": digest(review_path), "decision": "accepted", "confirmed": True})

        audit_path = root / "checkpoint-audit.json"
        audit = {
            "schema": "gaussian-checkpoint-geometry-audit/1", "audit_status": "passed",
            "ts_input_sha256": digest(input_path), "ts_log_sha256": digest(log_path),
            "ts_result_sha256": digest(ts_path), "mode_review_sha256": digest(review_path),
            "mode_decision_sha256": digest(decision_path), "checkpoint_sha256": digest(checkpoint_path),
            "checkpoint_file": checkpoint_path.name,
            "charge": 0, "multiplicity": 1, "atom_count": len(order), "atom_order": copy.deepcopy(order),
            "checks": {
                "ts_input_checkpoint_name_matches": True, "ts_result_log_hash_matches": True,
                "charge_multiplicity_matches": True, "input_log_result_atom_order_matches": True,
                "imaginary_mode_atom_order_matches": True, "accepted_mode_decision_hashes_match": True,
            },
        }
        dump(audit_path, audit)

        plan_path = root / "irc-plan.json"
        dump(plan_path, {
            "schema": "gaussian-irc-plan/1", "ts_result_sha256": digest(ts_path),
            "mode_decision_sha256": digest(decision_path), "checkpoint_sha256": digest(checkpoint_path),
            "directions": [
                {"direction": "forward", "project": "fixture_ircf", "route": "#p fixture IRC=(Forward)"},
                {"direction": "reverse", "project": "fixture_ircr", "route": "#p fixture IRC=(Reverse)"},
            ],
            "submission_status": "planned_not_submitted",
        })

        endpoint_paths = {}
        for direction, side, project, marker in (
            ("forward", "reactant", "fixture_ircf", "1"),
            ("reverse", "product", "fixture_ircr", "2"),
        ):
            endpoint = {
                "schema": "gaussian-irc-endpoint-audit/1", "audit_status": "passed",
                "project": project, "direction": direction, "chemical_side": side,
                "completed_point": 30, "corrector_convergence_count": 30,
                "checkpoint_sha256": marker * 64, "irc_input_sha256": "3" * 64,
                "irc_log_sha256": "4" * 64, "irc_result_sha256": "5" * 64,
                "irc_job_sha256": "6" * 64, "charge": 0, "multiplicity": 1,
                "atom_count": len(order), "atom_order": copy.deepcopy(order),
                "reviewed_forming_bond_distances": [{"pair": [3, 4], "distance_angstrom": 1.8}],
                "checks": {
                    "directional_path_complete": True, "all_points_corrector_converged": True,
                    "normal_termination": True, "input_job_hash_matches": True,
                    "checkpoint_name_matches": True, "log_result_atom_order_and_coordinates_match": True,
                },
            }
            endpoint_path = root / f"{direction}-endpoint.json"
            dump(endpoint_path, endpoint)
            endpoint_paths[direction] = endpoint_path

        energy_path = root / "energy.json"
        dump(energy_path, {
            "schema": "gaussian-asymmetric-energy-record/1", "result_id": "res_boron_ts_r_conf_a",
            "candidate_id": candidate["candidate_id"], "energy_unit": "kcal_mol",
            "electronic_energy": -100.0, "thermal_gibbs_correction": 10.0,
            "comparison_free_energy": 10.0, "comparison_energy_definition": "common fixture zero",
            "temperature_k": 298.15, "standard_state": "1M",
            "low_frequency_policy": "raw harmonic fixture values; no correction",
            "inventory_key": candidate["atom_inventory"]["inventory_key"], "degeneracy": 1,
        })
        return {
            "candidate": candidate_path, "ts": ts_path, "energy": energy_path,
            "review": review_path, "decision": decision_path, "forward": endpoint_paths["forward"],
            "reverse": endpoint_paths["reverse"], "input": input_path, "log": log_path,
            "checkpoint": checkpoint_path, "audit": audit_path, "plan": plan_path,
        }

    def ingest(self, paths: dict[str, Path], output: Path) -> dict:
        return ASYM.ingest_result(
            paths["candidate"], paths["ts"], paths["energy"], output,
            paths["review"], paths["decision"], paths["forward"], paths["reverse"],
            paths["input"], paths["log"], paths["checkpoint"], paths["audit"], paths["plan"],
        )

    def make_fixture_ledger(self, root: Path) -> tuple[Path, list[Path]]:
        study_path = FIXTURES / "boron_study.json"
        entries = []
        result_paths = []
        for suffix, marker in (("r", "1"), ("s", "2")):
            candidate_path = FIXTURES / f"boron_candidate_{suffix}.json"
            candidate = self.load_fixture(f"boron_candidate_{suffix}.json")
            result_path = root / f"result-{suffix}.json"
            dump(result_path, self.load_fixture(f"boron_result_{suffix}.json"))
            result_paths.append(result_path)
            entries.append({
                "candidate_id": candidate["candidate_id"], "channel_id": candidate["channel_id"],
                "catalyst_state_id": candidate["catalyst_state_id"], "dimensions": candidate["candidate_dimensions"],
                "canonical_key": marker * 64, "logical_equivalence_key": marker * 64,
                "status": "materialized_unique", "duplicate_of": None,
                "candidate_artifact": {"path": str(candidate_path), "sha256": digest(candidate_path)},
                "geometry_fingerprint": {"method": "fixture", "sha256": marker * 64}, "diagnostics": [],
            })
        ledger = {
            "schema": "gaussian-asymmetric-candidate-ledger/1", "study_id": "fixture_boron_selectivity",
            "study_sha256": digest(study_path), "comparison_group_id": "boron_face_pair",
            "mechanism_id": "boron_c_c_formation", "protocol_id": "fixture_boron_protocol",
            "calculation_ready": False, "no_submission_authorization": True,
            "candidate_space_spec": {"path": "fixture://space", "sha256": "a" * 64},
            "geometry_dedup_tolerance_angstrom": 0.01,
            "dimension_ids": ["binding_mode", "catalyst_conformer", "approach_face"],
            "entries": entries, "excluded_combinations": [],
            "counts": {"enumerated": 2, "retained": 2, "logical_duplicates": 0, "excluded": 0, "materialized_unique": 2, "geometry_duplicates": 0},
        }
        ledger_path = root / "ledger.json"
        dump(ledger_path, ledger)
        return ledger_path, result_paths

    def test_ingest_requires_promoted_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = self.make_ingest_chain(root)
            candidate = json.loads(paths["candidate"].read_text())
            candidate["review_status"] = "proposed"
            candidate["review"]["decision"] = "pending"
            dump(paths["candidate"], candidate)
            with self.assertRaisesRegex(ASYM.OfflineError, "promoted_offline"):
                self.ingest(paths, root / "result.json")

    def test_complete_hash_bound_path_lineage_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = self.make_ingest_chain(root)
            result = self.ingest(paths, root / "result.json")
            self.assertEqual(result["validation_level"], "path_validated")
            self.assertTrue(result["path_evidence"]["endpoint_identity_reviewed"])
            self.assertEqual(result["artifacts"]["checkpoint_audit"]["sha256"], digest(paths["audit"]))
            self.assertEqual(result["artifacts"]["irc_plan"]["sha256"], digest(paths["plan"]))
            self.assertFalse(result["calculation_ready"])

    def test_ts_result_v2_allowlist_invokes_the_canonical_owner_validator(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = self.make_ingest_chain(root)
            malformed = json.loads(paths["ts"].read_text(encoding="utf-8"))
            malformed["schema"] = "gaussian-ts-freq-result/2"
            dump(paths["ts"], malformed)
            with self.assertRaisesRegex(ASYM.OfflineError, r"TS/Freq result /2|source_log|unknown or missing"):
                self.ingest(paths, root / "malformed-v2.json")

        from tests.test_scientific_closure_lineage import TS, ts_execution_sources, water_log
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = self.make_ingest_chain(root)
            log_path = root / "owner-ts.log"
            log_path.write_text(water_log(" Frequencies -- -100.0 200.0 300.0").replace(" SCF Done:", " Charge = 0 Multiplicity = 1\n SCF Done:"), encoding="utf-8")
            sources = ts_execution_sources(root, log_path)
            paths["ts"] = root / "owner-ts-result.json"
            TS.build_ts_result_v2(log_path, paths["ts"], sources)
            result = ASYM.ingest_result(paths["candidate"], paths["ts"], paths["energy"], root / "accepted-v2.json")
            self.assertEqual(result["validation_level"], "first_order_saddle_candidate")
            self.assertFalse(result["calculation_ready"])

    def test_ingest_rejects_endpoint_atom_order_and_project_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = self.make_ingest_chain(root)
            endpoint = json.loads(paths["forward"].read_text())
            endpoint["atom_order"][0], endpoint["atom_order"][1] = endpoint["atom_order"][1], endpoint["atom_order"][0]
            dump(paths["forward"], endpoint)
            with self.assertRaisesRegex(ASYM.OfflineError, "atom order differs"):
                self.ingest(paths, root / "bad-order.json")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = self.make_ingest_chain(root)
            endpoint = json.loads(paths["forward"].read_text())
            endpoint["project"] = "forged_project"
            dump(paths["forward"], endpoint)
            with self.assertRaisesRegex(ASYM.OfflineError, "differs from IRC plan"):
                self.ingest(paths, root / "bad-project.json")

    def test_aggregate_binds_results_to_ledger_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger_path, result_paths = self.make_fixture_ledger(root)
            analysis = ASYM.aggregate(FIXTURES / "boron_study.json", ledger_path, result_paths, root / "analysis.json", 1.0)
            self.assertEqual(analysis["status"], "provisional")

            forged = json.loads(result_paths[0].read_text())
            forged["candidate_sha256"] = "0" * 64
            forged_path = root / "forged.json"
            dump(forged_path, forged)
            with self.assertRaisesRegex(ASYM.OfflineError, "candidate hash mismatch"):
                ASYM.aggregate(FIXTURES / "boron_study.json", ledger_path, [forged_path, result_paths[1]], root / "forged-analysis.json", 1.0)

            outside = json.loads(result_paths[0].read_text())
            outside["candidate_id"] = "outside_candidate"
            outside_path = root / "outside.json"
            dump(outside_path, outside)
            with self.assertRaisesRegex(ASYM.OfflineError, "outside the ledger"):
                ASYM.aggregate(FIXTURES / "boron_study.json", ledger_path, [outside_path, result_paths[1]], root / "outside-analysis.json", 1.0)

    def test_aggregate_rejects_nonfinite_values_and_unsupported_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger_path, result_paths = self.make_fixture_ledger(root)
            bad = json.loads(result_paths[0].read_text())
            bad["energies"]["comparison_free_energy"] = float("nan")
            bad_path = root / "nan.json"
            dump(bad_path, bad)
            with self.assertRaisesRegex(ASYM.OfflineError, "non-standard JSON numeric constant"):
                ASYM.aggregate(FIXTURES / "boron_study.json", ledger_path, [bad_path, result_paths[1]], root / "nan-analysis.json", 1.0)

            bad = json.loads(result_paths[0].read_text())
            bad["energies"]["degeneracy"] = 0
            bad_path = root / "degeneracy.json"
            dump(bad_path, bad)
            with self.assertRaisesRegex(ASYM.OfflineError, "degeneracy must be a positive integer"):
                ASYM.aggregate(FIXTURES / "boron_study.json", ledger_path, [bad_path, result_paths[1]], root / "degeneracy-analysis.json", 1.0)

            study = self.load_fixture("boron_study.json")
            study["comparison_groups"][0]["aggregation_model"] = "lowest_ts_only_sensitivity"
            study_path = root / "unsupported-study.json"
            dump(study_path, study)
            ledger = json.loads(ledger_path.read_text())
            ledger["study_sha256"] = digest(study_path)
            dump(ledger_path, ledger)
            with self.assertRaisesRegex(ASYM.OfflineError, "only boltzmann_ts_ensemble"):
                ASYM.aggregate(study_path, ledger_path, result_paths, root / "unsupported-analysis.json", 1.0)


if __name__ == "__main__":
    unittest.main()
