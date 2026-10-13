from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR_PATH = ROOT / "scripts/validate_asymmetric_contract.py"
SPEC = importlib.util.spec_from_file_location("r33_contract_validator", VALIDATOR_PATH)
VALIDATOR = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(VALIDATOR)

STUDY_DIR = ROOT / "studies/metal_m4_p0_p1_baseline"
CONTRACT_DIR = ROOT / "contracts/metal-ts"
LEDGER_PATH = STUDY_DIR / "r33-p1-evidence-ledger.json"
M1_PATH = STUDY_DIR / "r33-m1-blocked-review.json"
P5_PATH = STUDY_DIR / "r33-p5-approval-package.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def payload_digest(value: dict, field: str) -> str:
    payload = {key: item for key, item in value.items() if key != field}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


class R33P1P5ReviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ledger = json.loads(LEDGER_PATH.read_text())
        self.m1 = json.loads(M1_PATH.read_text())
        self.p5 = json.loads(P5_PATH.read_text())

    def validate(self, artifact: dict, schema_name: str) -> None:
        schema = json.loads((CONTRACT_DIR / schema_name).read_text())
        VALIDATOR.validate_schema_document(schema)
        VALIDATOR._validate_schema_instance(artifact, schema, schema)

    def test_strict_schemas_and_payload_hashes(self) -> None:
        cases = [
            (self.ledger, "r33-p1-evidence-ledger.schema.json", "ledger_payload_sha256"),
            (self.m1, "r33-m1-blocked-review.schema.json", "review_payload_sha256"),
            (self.p5, "p5-approval-package.schema.json", "package_payload_sha256"),
        ]
        for artifact, schema_name, field in cases:
            with self.subTest(schema=schema_name):
                self.validate(artifact, schema_name)
                self.assertEqual(artifact[field], payload_digest(artifact, field))
                schema = json.loads((CONTRACT_DIR / schema_name).read_text())
                self.assertIs(schema["additionalProperties"], False)
                self.assertEqual(set(schema["required"]), set(schema["properties"]))

    def test_ledger_binds_exact_candidate_and_preserves_source_ceiling(self) -> None:
        inventory = STUDY_DIR / "r33-candidate-inventory.json"
        structures = STUDY_DIR / "r33-start-ts-end.xyz"
        binding = self.ledger["candidate_binding"]
        self.assertEqual(binding["inventory"]["sha256"], digest(inventory))
        self.assertEqual(binding["structures"]["sha256"], digest(structures))
        self.assertEqual(binding["total_charge"], 1)
        self.assertEqual(binding["multiplicity_candidate"], 1)
        self.assertIn("semantically_unsatisfied", binding["formal_candidate_status"])
        self.assertTrue(any(source["source_id"] == "semidalas_2022_full_text" for source in self.ledger["sources"]))
        unread = next(source for source in self.ledger["sources"] if source["source_id"] == "iron_2002_si_file_unread")
        self.assertIsNone(unread["retrieval"]["sha256"])
        self.assertIn("no content claim", unread["claim_ceiling"])

    def test_electron_spin_and_wavefunction_review_do_not_infer_missing_facts(self) -> None:
        sections = self.ledger["sections"]
        electron = sections["electron_accounting"]["facts"]
        self.assertEqual(electron["source_reported_total_charge"], 1)
        for field in (
            "formal_oxidation_state", "ligand_charge_convention", "non_innocent_ligand_alternatives",
            "d_electron_count", "total_electron_count", "electron_parity",
        ):
            self.assertIsNone(electron[field], field)
        self.assertFalse(electron["electron_count_arithmetic_performed"])

        spin = sections["spin_surface"]["facts"]
        self.assertEqual([item["multiplicity"] for item in spin["source_reported_multiplicity_candidates"]], [1])
        self.assertIsNone(spin["scientifically_accepted_multiplicity"])
        for field in (
            "credible_alternative_multiplicities", "relative_spin_state_reference", "single_surface_assumption",
            "spin_crossover_relevance", "minimum_energy_crossing_relevance",
        ):
            self.assertIsNone(spin[field], field)

        wavefunction = sections["wavefunction"]["facts"]
        for field in (
            "reference_family", "restricted_unrestricted_ro_or_broken_symmetry", "scf_stability_policy",
            "s2_target_and_tolerance", "occupation_inspection_policy", "alternative_solution_policy",
            "checkpoint_or_guess_reuse_policy", "multireference_acceptance_policy",
        ):
            self.assertIsNone(wavefunction[field], field)
        self.assertEqual(len(wavefunction["observed_diagnostics"]), 3)
        self.assertEqual(wavefunction["diagnostic_decision"], "observed_not_accepted_no_universal_threshold")

    def test_coordination_and_ts_tables_are_measurements_not_chemical_acceptance(self) -> None:
        coordination = self.ledger["sections"]["coordination"]["facts"]
        for field in (
            "coordination_number", "coordination_geometry", "ligand_identities", "ligand_stoichiometry",
            "denticity", "hapticity", "substrate_identity_and_binding", "counterion_identity_and_placement",
            "explicit_solvent_or_additive_occupancy",
        ):
            self.assertIsNone(coordination[field], field)
        contacts = coordination["one_based_pt_distance_table_angstrom"]
        self.assertEqual({item["other_atom"] for item in contacts}, set(range(1, 16)) - {2})
        self.assertTrue(all(item["chemical_assignment"] is None for item in contacts))

        ts_path = self.ledger["sections"]["reaction_ts_path"]["facts"]
        self.assertEqual([item["index"] for item in ts_path["atom_order"]], list(range(1, 16)))
        for field in (
            "reactant_identity", "product_identity", "elementary_step_class", "expected_forming_bond",
            "expected_breaking_bond", "expected_transferring_atoms", "source_reported_raw_imaginary_frequency",
            "mode_displacement_evidence", "irc_direction_evidence", "structurally_identified_endpoints",
        ):
            self.assertIsNone(ts_path[field], field)
        self.assertIn("Exactly one raw imaginary frequency", ts_path["required_future_mode_evidence"])

    def test_method_review_and_p1_closure_stay_blocked(self) -> None:
        method = self.ledger["sections"]["method_protocol"]["facts"]
        for field in (
            "optimization_method", "frequency_method", "single_point_method", "basis_by_element",
            "ecp_by_element", "ecp_core_electrons", "relativistic_treatment", "solvent_model_and_identity",
            "thermochemistry_temperature_standard_state_low_frequency", "ts_strategy", "route",
            "three_tier_protocol_options", "protocol_selection",
        ):
            self.assertIsNone(method[field], field)
        self.assertFalse(self.ledger["p1_closure"]["closed"])
        self.assertFalse(self.ledger["p1_closure"]["m1_builder_eligible"])
        self.assertFalse(self.ledger["p1_closure"]["can_enter_p2_real_case"])
        self.assertFalse(any(self.ledger["live_actions"].values()))

    def test_m1_record_is_real_gap_lineage_not_a_synthetic_sidecar(self) -> None:
        self.assertEqual(self.m1["p1_evidence_ledger"]["sha256"], digest(LEDGER_PATH))
        assessment = self.m1["existing_builder_assessment"]
        self.assertFalse(assessment["invoked"])
        self.assertFalse(assessment["synthetic_fixture_used"])
        self.assertEqual(self.m1["status"], "blocked_no_real_sidecar_emitted")
        self.assertEqual(self.m1["m1_status"], "pending_scientific_review")
        self.assertTrue(all(item["status"] == "blocked_missing_evidence" for item in self.m1["section_dispositions"]))
        self.assertTrue(all(item["current_value"] is None for item in self.m1["gap_ledger"]))
        self.assertFalse(self.m1["calculation_ready"])
        self.assertTrue(self.m1["no_submission_authorization"])
        self.assertEqual(self.m1["submission_decision"], "refused")

    def test_p5_package_is_exactly_bound_and_non_executable(self) -> None:
        self.assertEqual(self.p5["candidate"]["sha256"], digest(STUDY_DIR / "r33-candidate-inventory.json"))
        self.assertEqual(self.p5["p1_evidence_ledger"]["sha256"], digest(LEDGER_PATH))
        self.assertEqual(self.p5["m1_review"]["sha256"], digest(M1_PATH))
        self.assertEqual(self.p5["status"], "planned_not_submitted")
        self.assertEqual(self.p5["approval_readiness"], "blocked_not_ready_for_live_approval")
        self.assertIsNone(self.p5["protocol"]["options"])
        self.assertIsNone(self.p5["protocol"]["selection"])
        self.assertEqual(self.p5["protocol"]["selection_status"], "absent_not_authorized")
        self.assertEqual(self.p5["input_draft"]["status"], "not_rendered_blocked")
        self.assertIsNone(self.p5["input_draft"]["path"])
        self.assertIsNone(self.p5["input_draft"]["sha256"])
        self.assertIsNone(self.p5["input_draft"]["route"])
        self.assertTrue(all(self.p5["resources"][field] is None for field in ("tier", "memory_gb", "cores")))
        self.assertEqual(self.p5["server_plan"]["allowed_root"], "/home/user100/SDL")
        self.assertFalse(self.p5["server_plan"]["actual_directory_created"])
        self.assertTrue(all(self.p5["server_plan"][field] is None for field in ("project_name", "remote_workdir", "canonical_path")))
        self.assertFalse(self.p5["live_authorization"]["authorized"])
        self.assertFalse(self.p5["live_authorization"]["package_is_submission_authorization"])
        self.assertFalse(any(self.p5["automatic_actions"].values()))

    def test_schema_rejects_authority_or_unknown_field_forgery(self) -> None:
        changed = copy.deepcopy(self.p5)
        changed["live_authorization"]["authorized"] = True
        with self.assertRaises(VALIDATOR.ContractError):
            self.validate(changed, "p5-approval-package.schema.json")
        changed = copy.deepcopy(self.ledger)
        changed["unknown"] = "forged"
        with self.assertRaises(VALIDATOR.ContractError):
            self.validate(changed, "r33-p1-evidence-ledger.schema.json")


if __name__ == "__main__":
    unittest.main()
