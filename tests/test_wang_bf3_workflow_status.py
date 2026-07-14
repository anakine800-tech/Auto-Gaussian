#!/usr/bin/env python3
"""Offline provenance tests for BF3-TS1 evidence and BF3-TS2-B1 preparation."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
STUDY = ROOT / "studies" / "wang_2024_bf3_ts"
B1 = STUDY / "bf3_ts2_b1"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CONTRACT = load_module(
    "asymmetric_contract_bf3_status",
    ROOT / "scripts" / "validate_asymmetric_contract.py",
)
PROTOCOL = load_module(
    "protocol_selection_bf3_status",
    ROOT / "skills" / "gaussian-rtwin-pbs" / "scripts" / "protocol_selection.py",
)
TS = load_module(
    "ts_irc_bf3_status",
    ROOT / "skills" / "gaussian-ts-irc" / "scripts" / "ts_irc.py",
)


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def payload_digest(document: dict, hash_field: str) -> str:
    payload = {key: value for key, value in document.items() if key != hash_field}
    encoded = (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
    return hashlib.sha256(encoded).hexdigest()


class WangBf3WorkflowStatusTests(unittest.TestCase):
    def test_ts1_sanitized_evidence_is_passed_and_hash_valid(self) -> None:
        evidence = load(STUDY / "bf3-ts1-live-smoke-evidence.json")
        CONTRACT.validate_live_smoke_evidence(evidence)
        self.assertEqual(evidence["status"], "passed")
        self.assertEqual(evidence["ts_validation"]["raw_imaginary_frequency_count"], 1)
        self.assertEqual(evidence["mode_validation"]["decision"], "accepted")
        self.assertFalse(evidence["contains_job_id"])
        self.assertFalse(evidence["contains_server_path"])
        self.assertFalse(evidence["contains_gaussian_log"])
        self.assertFalse(evidence["contains_checkpoint"])

    def test_b1_selection_is_portable_hash_bound_and_offline_only(self) -> None:
        selection_path = B1 / "protocol-selection-standard.json"
        options_path = B1 / "protocol-options.json"
        selection, options, selected = PROTOCOL.load_validated_selection(
            selection_path, options_path
        )
        self.assertEqual(options["request_source"]["path"], str(options_path.parent.relative_to(ROOT) / "calculation-request.json"))
        self.assertEqual(selection["options_source"]["path"], str(options_path.relative_to(ROOT)))
        self.assertEqual(selection["approval_evidence"]["path"], str((B1 / "user-selection-standard.json").relative_to(ROOT)))
        self.assertEqual(selected["tier"], "standard")
        self.assertEqual(selected["resources"]["resource_tier"], "complex")
        self.assertEqual(selected["resources"]["mem_gb"], 120)
        self.assertEqual(selected["resources"]["cores"], 44)
        self.assertTrue(selection["authorizations"]["render_input_draft"])
        for action in ("submit", "create_server_directory", "retry", "irc", "cancel", "cleanup"):
            self.assertFalse(selection["authorizations"][action])

    def test_b1_input_preserves_literature_coordinates_and_reaction_map(self) -> None:
        input_path = B1 / "w24_bf3ts2_b1_s01.gjf"
        source_xyz = STUDY / "coordinates" / "bf3_ts2_b1.xyz"
        manifest = load(B1 / "input-draft-manifest.json")
        parsed = TS.parse_cartesian_input(input_path)
        xyz_lines = source_xyz.read_text(encoding="utf-8").splitlines()[2:]
        xyz_atoms = [line.split() for line in xyz_lines]

        self.assertEqual(parsed["sha256"], manifest["rendered_input"]["sha256"])
        self.assertEqual(len(parsed["atoms"]), 78)
        self.assertEqual(parsed["charge"], 0)
        self.assertEqual(parsed["multiplicity"], 1)
        self.assertEqual([atom["element"] for atom in parsed["atoms"]], [row[0] for row in xyz_atoms])
        for atom, row in zip(parsed["atoms"], xyz_atoms, strict=True):
            self.assertEqual((atom["x"], atom["y"], atom["z"]), tuple(map(float, row[1:4])))

        atom13 = parsed["atoms"][12]
        atom21 = parsed["atoms"][20]
        distance = math.sqrt(sum((atom13[axis] - atom21[axis]) ** 2 for axis in ("x", "y", "z")))
        self.assertAlmostEqual(distance, 2.15133529, places=8)
        self.assertFalse(manifest["approval_state"]["exact_input_hash_approved_for_live_use"])
        self.assertFalse(manifest["approval_state"]["pbs_submission_authorized"])
        self.assertEqual(
            load(B1 / "input-audit.json")["structures"]["ts"]["path"],
            "studies/wang_2024_bf3_ts/bf3_ts2_b1/w24_bf3ts2_b1_s01.gjf",
        )
        self.assertEqual(
            manifest["manifest_payload_sha256"],
            payload_digest(manifest, "manifest_payload_sha256"),
        )

    def test_workflow_status_records_exercised_b1_authority_without_granting_more(self) -> None:
        status = load(STUDY / "workflow-status.json")
        records = {item["candidate_id"]: item for item in status["candidates"]}
        self.assertEqual(
            status["status_payload_sha256"],
            payload_digest(status, "status_payload_sha256"),
        )
        self.assertEqual(
            records["wang2024_bf3_ts1"]["sanitized_live_evidence"]["sha256"],
            digest(STUDY / "bf3-ts1-live-smoke-evidence.json"),
        )
        b1 = records["wang2024_bf3_ts2_b1"]
        self.assertEqual(
            b1["input_draft"]["manifest_sha256"],
            digest(B1 / "input-draft-manifest.json"),
        )
        self.assertEqual(b1["protocol_selection"]["tier"], "standard")
        history = b1["live_authority_history"]
        self.assertTrue(history["exact_input_hash_approved"])
        self.assertTrue(history["submission_authorized"])
        self.assertTrue(history["authorization_exercised"])
        self.assertFalse(history["new_live_action_authorized"])
        snapshot = b1["last_verified_live_snapshot"]
        self.assertEqual(snapshot["input_sha256"], digest(B1 / "w24_bf3ts2_b1_s01.gjf"))
        self.assertEqual(snapshot["state"], "running")
        self.assertTrue(snapshot["process_alive"])
        self.assertEqual(snapshot["normal_termination_count"], 0)
        self.assertEqual(snapshot["error_termination_count"], 0)
        self.assertEqual(snapshot["scientific_acceptance"], "pending")
        self.assertFalse(snapshot["contains_job_id"])
        self.assertFalse(snapshot["contains_server_path"])
        self.assertTrue(status["no_submission_authorization"])


if __name__ == "__main__":
    unittest.main()
