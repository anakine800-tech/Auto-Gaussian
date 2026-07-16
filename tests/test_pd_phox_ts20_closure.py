from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "studies/metal_m4_p0_p1_baseline/pd-phox-ts20-candidate-closure.json"
SCHEMA = ROOT / "contracts/metal-ts/pd-phox-ts20-closure.schema.json"
VALIDATOR_PATH = ROOT / "scripts/validate_asymmetric_contract.py"
SPEC = importlib.util.spec_from_file_location("pd_phox_validator", VALIDATOR_PATH)
VALIDATOR = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(VALIDATOR)


def payload_digest(value: dict) -> str:
    payload = {key: item for key, item in value.items() if key != "payload_sha256"}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


class PdPhoxTs20ClosureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.artifact = json.loads(ARTIFACT.read_text())
        self.schema = json.loads(SCHEMA.read_text())

    def validate(self, value: dict) -> None:
        VALIDATOR.validate_schema_document(self.schema)
        VALIDATOR._validate_schema_instance(value, self.schema, self.schema)

    def test_strict_schema_and_payload_hash(self) -> None:
        self.validate(self.artifact)
        self.assertFalse(self.schema["additionalProperties"])
        self.assertEqual(self.artifact["payload_sha256"], payload_digest(self.artifact))

    def test_doi_mismatch_is_not_silently_merged(self) -> None:
        identity = self.artifact["source_identity"]
        self.assertEqual(identity["requested_doi_status"], "mismatch_not_pd_phox_ts20")
        self.assertEqual(identity["matched_doi"], "10.1021/jacs.0c06243")
        self.assertEqual(identity["identity_decision"], "do_not_merge_requested_doi_with_matched_article")
        confirmation = self.artifact["reviewer_confirmation"]
        self.assertEqual(confirmation["confirmed_doi"], "10.1021/jacs.0c06243")
        self.assertEqual(confirmation["scope"], "source_identity_only")
        self.assertFalse(confirmation["scientific_fields_supplied"])

    def test_followup_search_does_not_invent_missing_orca_evidence(self) -> None:
        search = self.artifact["followup_search"]
        self.assertEqual(search["new_primary_objects"], 0)
        self.assertEqual(search["result"], "no_candidate_level_orca_input_output_frequency_hessian_or_irc_dataset_found")
        version = self.artifact["method_facts"]["program_version"]
        self.assertEqual(version["status"], "source_ambiguous")
        self.assertEqual(version["value"]["article"], "ORCA 4.1.2")

    def test_coordinate_lineage_preserves_source_order_without_claiming_product(self) -> None:
        lineage = self.artifact["coordinate_lineage"]
        self.assertEqual(lineage["source_pdf_sha256"], "8dcc7689f7064943ba9aa7222fd4714e1b8edb9e76b97d9025dca4e72c706d5f")
        self.assertEqual(lineage["precursor"]["atom_count"], 82)
        self.assertEqual(lineage["candidate"]["atom_count"], 82)
        self.assertEqual(lineage["one_based_atom_map"]["mapping"], list(range(1, 83)))
        self.assertIsNone(lineage["product_or_successor"])
        self.assertIsNone(lineage["forming_bond"])

    def test_missing_scientific_fields_block_m1_and_p5(self) -> None:
        for key in ("total_charge", "multiplicity", "pd_oxidation_state_ligand_charge_d_count", "wavefunction_reference"):
            self.assertIsNone(self.artifact["candidate_facts"][key]["value"])
        self.assertFalse(self.artifact["m1_decision"]["formal_candidate_closed"])
        self.assertFalse(self.artifact["m1_decision"]["sidecar_emitted"])
        self.assertTrue(self.artifact["authorization"]["p5_blocked"])
        self.assertFalse(self.artifact["authorization"]["live_actions_executed"])

    def test_schema_rejects_forged_authority_and_unknown_fields(self) -> None:
        changed = copy.deepcopy(self.artifact)
        changed["authorization"]["live_actions_authorized"] = True
        with self.assertRaises(VALIDATOR.ContractError):
            self.validate(changed)
        changed = copy.deepcopy(self.artifact)
        changed["unknown"] = "forged"
        with self.assertRaises(VALIDATOR.ContractError):
            self.validate(changed)


if __name__ == "__main__":
    unittest.main()
