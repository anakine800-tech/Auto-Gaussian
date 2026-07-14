#!/usr/bin/env python3
"""Offline provenance tests for the BF3 transition-state benchmark sequence."""

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
B2 = STUDY / "bf3_ts2_b2"


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
        self.assertEqual(snapshot["state"], "completed")
        self.assertIsNone(snapshot["process_alive"])
        self.assertEqual(snapshot["normal_termination_count"], 2)
        self.assertEqual(snapshot["error_termination_count"], 0)
        self.assertTrue(snapshot["stationary_point_found"])
        self.assertEqual(snapshot["frequency_count"], 228)
        self.assertEqual(snapshot["raw_imaginary_frequency_count"], 1)
        self.assertEqual(snapshot["scientific_acceptance"], "mode_consistent_first_order_saddle_candidate")
        self.assertFalse(snapshot["contains_job_id"])
        self.assertFalse(snapshot["contains_server_path"])
        self.assertTrue(status["no_submission_authorization"])

        irc = b1["irc_submission_history"]
        self.assertEqual(irc["protocol_proposal"]["sha256"], digest(B1 / "irc-protocol-proposal.json"))
        self.assertEqual(irc["plan"]["sha256"], digest(B1 / "irc/irc_plan.json"))
        self.assertEqual([item["direction"] for item in irc["directions"]], ["forward", "reverse"])
        for item in irc["directions"]:
            self.assertEqual(item["input_sha256"], digest(ROOT / item["input_path"]))
            self.assertEqual(item["manifest_sha256"], digest(ROOT / item["manifest_path"]))
            self.assertFalse(item["terminal_evidence"])
        self.assertFalse(irc["contains_job_id"])
        self.assertFalse(irc["contains_server_path"])
        self.assertFalse(irc["new_live_action_authorized"])

    def test_b1_terminal_acceptance_plan_is_precommitted_and_non_authorizing(self) -> None:
        plan_path = B1 / "terminal-acceptance-plan.json"
        plan = load(plan_path)
        self.assertEqual(
            plan["plan_payload_sha256"],
            payload_digest(plan, "plan_payload_sha256"),
        )
        self.assertEqual(plan["source_bindings"]["rendered_input"]["sha256"], digest(B1 / "w24_bf3ts2_b1_s01.gjf"))
        self.assertEqual(plan["expected_system"]["expected_harmonic_mode_count"], 228)
        self.assertEqual(plan["ts_acceptance_gate"]["required_raw_imaginary_frequency_count"], 1)
        self.assertEqual(plan["mode_review_gate"]["atom_pair"], [13, 21])
        self.assertFalse(plan["mode_review_gate"]["static_distance_is_sufficient"])
        self.assertFalse(plan["mode_review_gate"]["numerical_frequency_match_required"])
        self.assertFalse(plan["path_claim"]["path_validated"])
        self.assertTrue(plan["no_submission_authorization"])
        self.assertTrue(all(not item["automatic_action"] for item in plan["outcome_matrix"]))

        status = load(STUDY / "workflow-status.json")
        b1 = next(item for item in status["candidates"] if item["candidate_id"] == "wang2024_bf3_ts2_b1")
        self.assertEqual(b1["terminal_acceptance_plan"]["sha256"], digest(plan_path))

    def test_b2_standard_input_is_hash_bound_and_still_offline_only(self) -> None:
        request = load(B2 / "calculation-request.json")
        profiles = load(B2 / "protocol-profiles.json")
        options = load(B2 / "protocol-options.json")
        selection_path = B2 / "protocol-selection-standard.json"
        input_path = B2 / "w24_bf3ts2_b2_s01.gjf"
        manifest_path = B2 / "input-draft-manifest.json"
        plan_path = B2 / "terminal-acceptance-plan.json"
        selection, _, selected = PROTOCOL.load_validated_selection(
            selection_path, B2 / "protocol-options.json"
        )
        manifest = load(manifest_path)
        plan = load(plan_path)
        parsed = TS.parse_cartesian_input(input_path)
        source_xyz = STUDY / "coordinates" / "bf3_ts2_b2.xyz"
        status = load(STUDY / "workflow-status.json")

        self.assertEqual(request["structure"]["sha256"], digest(STUDY / "coordinates/bf3_ts2_b2.xyz"))
        self.assertEqual(request["structure"]["atom_count"], 78)
        self.assertEqual(request["structure"]["charge"], 0)
        self.assertEqual(request["structure"]["multiplicity"], 1)
        self.assertFalse(request["calculation_ready"])
        self.assertTrue(request["no_submission_authorization"])

        self.assertEqual(profiles["proposal_id"], "wang2024_bf3_ts2_b2_three_tiers")
        self.assertEqual([item["tier"] for item in profiles["options"]], ["loose", "standard", "strict"])
        self.assertTrue(all("BF3-TS2-B1" in " ".join(item["applicability"]["prerequisites"]) for item in profiles["options"]))

        self.assertEqual(options["status"], "ready_for_selection")
        self.assertEqual(options["request_source"]["sha256"], digest(B2 / "calculation-request.json"))
        self.assertEqual([item["tier"] for item in options["options"]], ["loose", "standard", "strict"])
        self.assertTrue(options["no_input_render_authorization"])
        self.assertTrue(options["no_submission_authorization"])

        self.assertEqual(selected["tier"], "standard")
        self.assertEqual(selected["resources"]["resource_tier"], "complex")
        self.assertEqual(selected["resources"]["mem_gb"], 120)
        self.assertEqual(selected["resources"]["cores"], 44)
        self.assertTrue(selection["authorizations"]["render_input_draft"])
        for action in ("submit", "create_server_directory", "retry", "irc", "cancel", "cleanup"):
            self.assertFalse(selection["authorizations"][action])

        self.assertEqual(parsed["sha256"], digest(input_path))
        self.assertEqual(parsed["sha256"], manifest["rendered_input"]["sha256"])
        self.assertEqual(parsed["charge"], 0)
        self.assertEqual(parsed["multiplicity"], 1)
        self.assertEqual(len(parsed["atoms"]), 78)
        xyz_rows = [line.split() for line in source_xyz.read_text(encoding="utf-8").splitlines()[2:]]
        self.assertEqual([atom["element"] for atom in parsed["atoms"]], [row[0] for row in xyz_rows])
        for atom, row in zip(parsed["atoms"], xyz_rows, strict=True):
            self.assertEqual((atom["x"], atom["y"], atom["z"]), tuple(map(float, row[1:4])))
        atom13 = parsed["atoms"][12]
        atom21 = parsed["atoms"][20]
        distance = math.sqrt(sum((atom13[axis] - atom21[axis]) ** 2 for axis in ("x", "y", "z")))
        self.assertAlmostEqual(distance, 2.22485843, places=8)
        self.assertEqual(manifest["manifest_payload_sha256"], payload_digest(manifest, "manifest_payload_sha256"))
        self.assertEqual(
            load(B2 / "input-audit.json")["structures"]["ts"]["path"],
            "studies/wang_2024_bf3_ts/bf3_ts2_b2/w24_bf3ts2_b2_s01.gjf",
        )
        self.assertFalse(manifest["approval_state"]["exact_input_hash_approved_for_live_use"])
        self.assertFalse(manifest["approval_state"]["pbs_submission_authorized"])
        self.assertEqual(plan["plan_payload_sha256"], payload_digest(plan, "plan_payload_sha256"))
        self.assertEqual(plan["source_bindings"]["rendered_input"]["sha256"], digest(input_path))
        self.assertEqual(plan["expected_system"]["expected_harmonic_mode_count"], 228)
        self.assertEqual(plan["mode_review_gate"]["atom_pair"], [13, 21])
        self.assertFalse(plan["path_claim"]["path_validated"])
        self.assertTrue(all(not item["automatic_action"] for item in plan["outcome_matrix"]))

        b2 = next(item for item in status["candidates"] if item["candidate_id"] == "wang2024_bf3_ts2_b2")
        self.assertEqual(b2["sequence_gate"], "bf3_ts2_b1_mode_decision_satisfied")
        self.assertEqual(b2["protocol_options"]["sha256"], digest(B2 / "protocol-options.json"))
        self.assertTrue(b2["protocol_options"]["input_render_authorized"])
        self.assertEqual(b2["protocol_selection"]["sha256"], digest(selection_path))
        self.assertEqual(b2["input_draft"]["sha256"], digest(input_path))
        self.assertEqual(b2["input_draft"]["manifest_sha256"], digest(manifest_path))
        self.assertEqual(b2["terminal_acceptance_plan"]["sha256"], digest(plan_path))
        self.assertEqual(
            b2["live_submission_approval"]["sha256"],
            digest(B2 / "live-submission-approval.json"),
        )
        self.assertTrue(b2["live_submission_approval"]["authorization_exercised"])
        self.assertFalse(b2["live_submission_approval"]["new_live_action_authorized"])
        self.assertEqual(b2["last_verified_live_snapshot"]["state"], "queued")
        self.assertFalse(b2["last_verified_live_snapshot"]["contains_job_id"])
        self.assertFalse(b2["last_verified_live_snapshot"]["contains_server_path"])


if __name__ == "__main__":
    unittest.main()
