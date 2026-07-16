import importlib.util
import copy
import hashlib
import json
import re
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / "studies/metal_m4_p0_p1_baseline/p0-p5-readiness.json"
SCHEMA = ROOT / "contracts/metal-ts/p0-p5-readiness.schema.json"
VALIDATOR_PATH = ROOT / "scripts/validate_asymmetric_contract.py"
SPEC = importlib.util.spec_from_file_location("asymmetric_schema_validator", VALIDATOR_PATH)
VALIDATOR = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(VALIDATOR)


class MetalP0P5ReadinessTests(unittest.TestCase):
    def setUp(self):
        self.matrix = json.loads(MATRIX.read_text())
        self.schema = json.loads(SCHEMA.read_text())

    def validate_index(self, matrix):
        VALIDATOR._validate_schema_instance(matrix, self.schema, self.schema)
        payload = {key: value for key, value in matrix.items() if key != "readiness_payload_sha256"}
        expected = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
        self.assertEqual(matrix["readiness_payload_sha256"], expected)
        self.assertEqual([item["phase"] for item in matrix["milestones"]], ["P0", "P1", "P2", "P3", "P4", "P5"])
        has_git_object_store = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode == 0
        for milestone in matrix["milestones"]:
            for evidence in milestone["evidence"]:
                if evidence["kind"] == "commit":
                    self.assertRegex(evidence["locator"], r"^[0-9a-f]{40}$")
                    self.assertIsNone(evidence["sha256"])
                    if has_git_object_store:
                        self.assertEqual(subprocess.run(["git", "cat-file", "-e", f"{evidence['locator']}^{{commit}}"], cwd=ROOT).returncode, 0)
                else:
                    path = ROOT / evidence["locator"]
                    self.assertTrue(path.is_file())
                    self.assertFalse(path.is_symlink())
                    self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), evidence["sha256"])

    def reseal(self, matrix):
        payload = {key: value for key, value in matrix.items() if key != "readiness_payload_sha256"}
        matrix["readiness_payload_sha256"] = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
        return matrix

    def test_matrix_validates_against_schema(self):
        VALIDATOR.validate_schema_document(self.schema)
        self.validate_index(self.matrix)

    def test_phase_order_and_claim_dimensions_are_fail_closed(self):
        milestones = self.matrix["milestones"]
        self.assertEqual([item["phase"] for item in milestones], ["P0", "P1", "P2", "P3", "P4", "P5"])
        self.assertTrue(all(not item["evidence_complete"] and not item["executable"] for item in milestones))
        self.assertTrue(all(item["implemented"] for item in milestones))

    def test_scientific_and_live_blockers_are_explicit(self):
        by_phase = {item["phase"]: item for item in self.matrix["milestones"]}
        self.assertIn("multiplicity", " ".join(by_phase["P1"]["blockers"]))
        self.assertIn("closed-shell", " ".join(by_phase["P1"]["blockers"]))
        self.assertTrue(all("P1" in " ".join(by_phase[p]["blockers"]) for p in ("P2", "P3", "P4")))
        self.assertEqual(self.matrix["live_actions"], {"authorized": False, "executed": False})
        self.assertEqual(by_phase["P5"]["status"], "approval_package_assembled_planned_not_submitted_blocked")

    def test_index_rejects_payload_path_hash_and_phase_forgery(self):
        cases = []
        changed = copy.deepcopy(self.matrix); changed["milestones"][0]["blockers"].append("tampered"); cases.append(changed)
        missing = copy.deepcopy(self.matrix); missing["milestones"][0]["evidence"][1]["locator"] = "missing/evidence.json"; cases.append(self.reseal(missing))
        wrong_hash = copy.deepcopy(self.matrix); wrong_hash["milestones"][0]["evidence"][1]["sha256"] = "0" * 64; cases.append(self.reseal(wrong_hash))
        duplicate = copy.deepcopy(self.matrix); duplicate["milestones"][1]["phase"] = "P0"; cases.append(self.reseal(duplicate))
        out_of_order = copy.deepcopy(self.matrix); out_of_order["milestones"][0], out_of_order["milestones"][1] = out_of_order["milestones"][1], out_of_order["milestones"][0]; cases.append(self.reseal(out_of_order))
        for value in cases:
            with self.assertRaises(AssertionError):
                self.validate_index(value)

    def test_index_rejects_readiness_or_live_authority_escalation(self):
        for field in ("evidence_complete", "executable"):
            changed = copy.deepcopy(self.matrix); changed["milestones"][2][field] = True
            with self.assertRaises(VALIDATOR.ContractError):
                self.validate_index(changed)
        changed = copy.deepcopy(self.matrix); changed["live_actions"]["authorized"] = True
        with self.assertRaises(VALIDATOR.ContractError):
            self.validate_index(changed)


if __name__ == "__main__":
    unittest.main()
