from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STUDY = ROOT / "studies/metal_m4_p0_p1_baseline"
CONTRACTS = ROOT / "contracts/metal-ts"
SPEC = importlib.util.spec_from_file_location("decision_validator", ROOT / "scripts/validate_asymmetric_contract.py")
VALIDATOR = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(VALIDATOR)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def payload_digest(value: dict, field: str) -> str:
    payload = {key: item for key, item in value.items() if key != field}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


class MetalSmokeCandidateDecisionTests(unittest.TestCase):
    def validate(self, artifact_name: str, schema_name: str) -> dict:
        artifact = json.loads((STUDY / artifact_name).read_text())
        schema = json.loads((CONTRACTS / schema_name).read_text())
        VALIDATOR.validate_schema_document(schema)
        VALIDATOR._validate_schema_instance(artifact, schema, schema)
        return artifact

    def test_r33_rejection_is_hash_bound_and_narrow(self) -> None:
        decision = self.validate("r33-first-metal-smoke-decision.json", "first-metal-smoke-decision.schema.json")
        self.assertEqual(decision["decision_payload_sha256"], payload_digest(decision, "decision_payload_sha256"))
        self.assertEqual(decision["decision"], "rejected_as_first_metal_smoke")
        self.assertIn("not a rejection", decision["scope"])
        git_history_available = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=ROOT, check=False, capture_output=True,
        ).returncode == 0
        for binding in decision["bindings"]:
            self.assertRegex(binding["git_revision"], re.compile(r"^[0-9a-f]{40}$"))
            bound_path = Path(binding["path"])
            self.assertFalse(bound_path.is_absolute())
            self.assertNotIn("..", bound_path.parts)
            self.assertTrue((ROOT / bound_path).is_file())
            if git_history_available:
                historical = subprocess.run(
                    ["git", "show", f'{binding["git_revision"]}:{binding["path"]}'],
                    cwd=ROOT, check=True, capture_output=True,
                ).stdout
                self.assertEqual(binding["sha256"], hashlib.sha256(historical).hexdigest())
        self.assertFalse(decision["consequences"]["r33_p1_closed"])
        self.assertFalse(decision["consequences"]["r33_m1_emitted"])
        self.assertFalse(decision["consequences"]["r33_p5_executable"])
        self.assertFalse(any(decision["live_actions"].values()))

    def test_replacement_review_fails_closed_without_synthetic_m1(self) -> None:
        ledger = self.validate("replacement-candidate-selection.json", "replacement-candidate-selection.schema.json")
        self.assertEqual(ledger["ledger_payload_sha256"], payload_digest(ledger, "ledger_payload_sha256"))
        self.assertEqual(ledger["status"], "blocked_no_candidate_closed")
        self.assertGreaterEqual(len(ledger["promotion_criteria"]), 10)
        self.assertEqual([item["rank"] for item in ledger["ranked_shortlist"]], [1, 2, 3])
        self.assertTrue(all(item["disposition"] == "blocked_not_promoted" for item in ledger["ranked_shortlist"]))
        self.assertIsNone(ledger["selection_decision"]["selected_candidate"])
        self.assertFalse(ledger["selection_decision"]["formal_candidate_emitted"])
        self.assertFalse(any(ledger["m1_outcome"].values()))
        self.assertFalse(any(ledger["live_actions"].values()))

    def test_r33_p5_remains_non_executable_after_rejection(self) -> None:
        package = json.loads((STUDY / "r33-p5-approval-package.json").read_text())
        self.assertEqual(package["status"], "planned_not_submitted")
        self.assertFalse(package["live_authorization"]["authorized"])
        self.assertFalse(package["live_authorization"]["package_is_submission_authorization"])
        self.assertFalse(any(package["automatic_actions"].values()))
        self.assertFalse(package["server_plan"]["actual_directory_created"])
        self.assertEqual(package["server_plan"]["allowed_root"], "/home/user100/SDL")


if __name__ == "__main__":
    unittest.main()
