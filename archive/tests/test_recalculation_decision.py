#!/usr/bin/env python3
"""Offline unit, integration, and refusal tests for recalculation decisions."""

from __future__ import annotations

import copy
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).parents[1]
MODULE_PATH = ROOT / "skills" / "auto-g16-reaction-workflow" / "scripts" / "recalculation_decision.py"
VALIDATOR_PATH = ROOT / "scripts" / "validate_asymmetric_contract.py"
FIXTURES = ROOT / "tests" / "fixtures" / "reaction_workflow" / "recalculation_decision"
SCHEMA_PATH = ROOT / "contracts" / "reaction-workflow" / "recalculation-decision.schema.json"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


DECISION = load_module("recalculation_decision_test", MODULE_PATH)
SCHEMA_VALIDATOR = load_module("recalculation_schema_validator_test", VALIDATOR_PATH)


def dump(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


class RecalculationDecisionTests(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / "tests")
        self.root = Path(self.temp.name).resolve()
        shutil.copytree(FIXTURES, self.root / "evidence")
        self.source_paths = {
            "attempt": Path("evidence/attempt.json"),
            "input": Path("evidence/input.json"),
            "protocol": Path("evidence/protocol.json"),
            "result": Path("evidence/result.json"),
            "terminal_evidence": Path("evidence/terminal-evidence.json"),
        }
        self.draft_path = Path("evidence/positive-review.draft.json")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def load_draft(self) -> dict:
        return json.loads((self.root / self.draft_path).read_text(encoding="utf-8"))

    def write_draft(self, value: dict, name: str = "review.draft.json") -> Path:
        path = Path(name)
        dump(self.root / path, value)
        return path

    def finalize(self, draft: Path | None = None, output: str = "decision.json") -> dict:
        return DECISION.finalize_decision(
            self.root,
            draft or self.draft_path,
            self.source_paths,
            Path(output),
        )

    def test_positive_fixture_finalizes_validates_and_matches_closed_schema(self) -> None:
        artifact = self.finalize()
        summary = DECISION.validate_decision(self.root, Path("decision.json"))
        self.assertTrue(summary["valid"])
        self.assertEqual(summary["decision"], "approve_one_exact_recalculation_proposal")
        self.assertFalse(summary["calculation_ready"])
        self.assertTrue(summary["no_submission_authorization"])
        self.assertTrue(summary["no_automatic_retry"])
        schema = SCHEMA_VALIDATOR.load_json(SCHEMA_PATH)
        SCHEMA_VALIDATOR.validate_schema_document(schema)
        SCHEMA_VALIDATOR._validate_schema_instance(artifact, schema, schema)

    def test_cli_round_trip_is_offline_and_root_relative(self) -> None:
        command = [
            sys.executable,
            str(MODULE_PATH),
            "finalize",
            "--root",
            str(self.root),
            str(self.draft_path),
            "--attempt",
            str(self.source_paths["attempt"]),
            "--input",
            str(self.source_paths["input"]),
            "--protocol",
            str(self.source_paths["protocol"]),
            "--result",
            str(self.source_paths["result"]),
            "--terminal-evidence",
            str(self.source_paths["terminal_evidence"]),
            "--output",
            "cli-decision.json",
        ]
        finalized = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
        self.assertEqual(finalized.returncode, 0, finalized.stderr)
        summary = json.loads(finalized.stdout)
        self.assertFalse(summary["live_actions"])
        validated = subprocess.run(
            [sys.executable, str(MODULE_PATH), "validate", "--root", str(self.root), "cli-decision.json"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(validated.returncode, 0, validated.stderr)

    def test_all_decision_enumerations_have_closed_action_semantics(self) -> None:
        for decision, status, empty in (
            ("no_retry", None, True),
            ("defer", "deferred", False),
            ("reject_proposal", "rejected", False),
        ):
            draft = self.load_draft()
            draft["review"]["decision"] = decision
            if empty:
                draft["candidate_actions"] = []
            else:
                draft["candidate_actions"][0]["status"] = status
            draft_path = self.write_draft(draft, f"{decision}.draft.json")
            artifact = self.finalize(draft_path, f"{decision}.json")
            self.assertEqual(artifact["review"]["decision"], decision)

    def test_normal_termination_alone_and_single_error_source_are_refused(self) -> None:
        draft = self.load_draft()
        draft["failure_classification"]["evidence"] = [
            {
                "source": "result",
                "json_pointer": "/normal_termination_count",
                "interpretation": "Normal termination was observed.",
            }
        ]
        path = self.write_draft(draft, "normal-only.draft.json")
        with self.assertRaisesRegex(DECISION.DecisionError, "at least two exact evidence observations"):
            self.finalize(path)
        draft = self.load_draft()
        draft["failure_classification"]["evidence"] = [
            {"source": "terminal_evidence", "json_pointer": "/error_codes", "interpretation": "A code was recorded."},
            {"source": "terminal_evidence", "json_pointer": "/outcome", "interpretation": "The same source records failure."},
        ]
        path = self.write_draft(draft, "single-source.draft.json")
        with self.assertRaisesRegex(DECISION.DecisionError, "must span at least two bound sources"):
            self.finalize(path)

    def test_reviewer_time_notes_and_uncertainties_are_required(self) -> None:
        for field, value, message in (
            ("reviewer", "", "review.reviewer"),
            ("reviewed_at", "2026-07-17", "must include a timezone"),
            ("notes", [], "review.notes"),
            ("uncertainties", [], "review.uncertainties"),
        ):
            draft = self.load_draft()
            draft["review"][field] = value
            path = self.write_draft(draft, f"missing-{field}.draft.json")
            with self.assertRaisesRegex(DECISION.DecisionError, message):
                self.finalize(path, f"missing-{field}.json")

    def test_approval_requires_one_exact_human_delta_and_every_new_gate(self) -> None:
        draft = self.load_draft()
        second = copy.deepcopy(draft["candidate_actions"][0])
        second["proposal_id"] = "second_exact_proposal"
        draft["candidate_actions"].append(second)
        path = self.write_draft(draft, "two-proposals.draft.json")
        with self.assertRaisesRegex(DECISION.DecisionError, "approval requires exactly one proposal"):
            self.finalize(path)
        draft = self.load_draft()
        draft["candidate_actions"][0]["required_new_reviews"]["live_approval"] = False
        path = self.write_draft(draft, "missing-live-gate.draft.json")
        with self.assertRaisesRegex(DECISION.DecisionError, "must require fresh protocol, maturity, input, and live approvals"):
            self.finalize(path)
        draft = self.load_draft()
        draft["candidate_actions"][0]["proposed_exact_delta"][0]["change_origin"] = "automatic"
        path = self.write_draft(draft, "automatic-delta.draft.json")
        with self.assertRaisesRegex(DECISION.DecisionError, "must be human_authored"):
            self.finalize(path)

    def test_absolute_paths_parent_escape_and_machine_path_content_are_refused(self) -> None:
        sources = dict(self.source_paths)
        sources["attempt"] = (self.root / sources["attempt"]).resolve()
        with self.assertRaisesRegex(DECISION.DecisionError, "absolute paths are forbidden"):
            DECISION.finalize_decision(self.root, self.draft_path, sources, Path("absolute.json"))
        with self.assertRaisesRegex(DECISION.DecisionError, "parent traversal"):
            DECISION.finalize_decision(self.root, Path("../review.json"), self.source_paths, Path("escape.json"))
        draft = self.load_draft()
        draft["review"]["notes"] = ["See " + "/" + "Users" + "/example/private/job.log"]
        path = self.write_draft(draft, "machine-path.draft.json")
        with self.assertRaisesRegex(DECISION.DecisionError, "machine-local path"):
            self.finalize(path, "machine-path.json")

    def test_artifact_contains_no_absolute_or_machine_paths(self) -> None:
        artifact = self.finalize()
        for role, binding in artifact["evidence_bindings"].items():
            path = binding["artifact"]["path"]
            self.assertFalse(Path(path).is_absolute(), role)
            self.assertNotIn("..", Path(path).parts)
            self.assertEqual(binding["artifact"]["owner_validation"], "not_performed_no_semantic_acceptance")
        serialized = json.dumps(artifact, ensure_ascii=False)
        for marker in (
            "/" + "Users" + "/",
            "/" + "home" + "/",
            "/" + "private" + "/",
            "file" + "://",
        ):
            self.assertNotIn(marker, serialized)

    def test_role_schema_swap_and_unknown_owner_claim_are_refused(self) -> None:
        sources = dict(self.source_paths)
        sources["protocol"] = self.source_paths["result"]
        with self.assertRaisesRegex(DECISION.DecisionError, "protocol evidence schema is not allowlisted"):
            DECISION.finalize_decision(self.root, self.draft_path, sources, Path("swapped.json"))
        unknown = json.loads((self.root / self.source_paths["protocol"]).read_text(encoding="utf-8"))
        unknown["schema"] = "gaussian-unknown-owner-artifact/1"
        unknown["owner_accepted"] = True
        dump(self.root / self.source_paths["protocol"], unknown)
        with self.assertRaisesRegex(DECISION.DecisionError, "protocol evidence schema is not allowlisted"):
            self.finalize(output="unknown-owner.json")

    def test_ts_result_v2_allowlist_invokes_the_canonical_owner_validator(self) -> None:
        result_path = self.root / self.source_paths["result"]
        malformed = json.loads(result_path.read_text(encoding="utf-8"))
        malformed["schema"] = "gaussian-ts-freq-result/2"
        malformed["payload_sha256"] = DECISION.rw.sha256_data(malformed)
        dump(result_path, malformed)
        with self.assertRaisesRegex(DECISION.DecisionError, r"TS/Freq result /2|source_log|unknown or missing"):
            self.finalize(output="malformed-v2.json")

    def test_schema_null_raw_evidence_stays_integrity_only(self) -> None:
        protocol_path = self.root / self.source_paths["protocol"]
        raw = json.loads(protocol_path.read_text(encoding="utf-8"))
        raw.pop("schema")
        dump(protocol_path, raw)
        artifact = self.finalize(output="raw-protocol.json")
        ref = artifact["evidence_bindings"]["protocol"]["artifact"]
        self.assertIsNone(ref["schema"])
        self.assertIsNone(ref["payload_sha256"])
        self.assertEqual(ref["integrity_validation"], "bytes_only")
        self.assertEqual(ref["owner_validation"], "not_performed_no_semantic_acceptance")

    def test_source_drift_and_rehashed_derived_edits_are_refused(self) -> None:
        artifact = self.finalize()
        result_path = self.root / self.source_paths["result"]
        result = json.loads(result_path.read_text(encoding="utf-8"))
        result["optimization_completed"] = True
        dump(result_path, result)
        with self.assertRaisesRegex(DECISION.DecisionError, "artifact reference drift"):
            DECISION.validate_decision(self.root, Path("decision.json"))
        dump_path = self.root / "derived-edit.json"
        edited = copy.deepcopy(artifact)
        edited["candidate_actions"][0]["proposed_exact_delta"][0]["to_canonical_json"] = "200"
        edited.pop("payload_sha256")
        DECISION.rw.finalize_artifact(edited)
        dump(dump_path, edited)
        with self.assertRaises(DECISION.DecisionError):
            DECISION.validate_decision(self.root, Path("derived-edit.json"))

    def test_atomic_publication_failure_leaves_no_partial_artifact(self) -> None:
        output = self.root / "atomic.json"
        with mock.patch.object(DECISION.os, "link", side_effect=OSError("injected link failure")):
            with self.assertRaisesRegex(OSError, "injected link failure"):
                self.finalize(output="atomic.json")
        self.assertFalse(output.exists())
        self.assertEqual(list(self.root.glob(".atomic.json.*")), [])

    def test_concurrent_target_creation_is_never_clobbered(self) -> None:
        output = self.root / "concurrent.json"
        external_bytes = b"external-writer-owned-target\n"
        real_link = DECISION.os.link

        def create_external_target_then_link(source, target):
            Path(target).write_bytes(external_bytes)
            return real_link(source, target)

        with mock.patch.object(DECISION.os, "link", side_effect=create_external_target_then_link):
            with self.assertRaisesRegex(DECISION.DecisionError, "concurrent or overwrite"):
                self.finalize(output="concurrent.json")
        self.assertEqual(output.read_bytes(), external_bytes)
        self.assertEqual(list(self.root.glob(".concurrent.json.*")), [])

    def test_overwrite_is_refused_and_original_bytes_are_unchanged(self) -> None:
        self.finalize(output="immutable.json")
        output = self.root / "immutable.json"
        original = output.read_bytes()
        with self.assertRaisesRegex(DECISION.DecisionError, "refusing to overwrite"):
            self.finalize(output="immutable.json")
        self.assertEqual(output.read_bytes(), original)
        self.assertEqual(list(self.root.glob(".immutable.json.*")), [])

    def test_committed_negative_fixture_catalog_covers_security_regressions(self) -> None:
        catalog = json.loads((self.root / "evidence/negative-cases.json").read_text(encoding="utf-8"))
        ids = {case["case_id"] for case in catalog["cases"]}
        self.assertTrue(
            {
                "absolute_reference_is_refused",
                "role_schema_swap_is_refused",
                "unknown_schema_cannot_claim_owner_acceptance",
                "partial_publication_is_removed",
                "concurrent_target_is_never_clobbered",
                "evidence_drift_is_refused",
            }
            <= ids
        )


if __name__ == "__main__":
    unittest.main()
