#!/usr/bin/env python3
"""Offline contract and refusal tests for the human decision layer."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
TOOL = ROOT / "skills" / "auto-g16-reaction-workflow" / "scripts" / "human_scientific_decision.py"
SCHEMA_VALIDATOR = ROOT / "scripts" / "validate_asymmetric_contract.py"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HD = load("human_scientific_decision_test", TOOL)
SV = load("human_scientific_decision_schema", SCHEMA_VALIDATOR)


def dump(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


class HumanScientificDecisionTests(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / "tests")
        self.root = Path(self.temp.name).resolve()
        self.mechanism = self.source("mechanism.json", "gaussian-mechanism-proposal/1", "Mechanism proposal")
        self.network = self.source("network.json", "gaussian-reaction-mechanism-network/1", "Network proposal")
        self.evidence = self.source("evidence.json", "gaussian-reaction-literature-evidence/1", "Reviewed evidence")
        self.new_evidence = self.source("new-evidence.json", "gaussian-result-observation/1", "New observation")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def source(self, name: str, schema: str, summary: str) -> Path:
        path = self.root / name
        value = {"schema": schema, "summary": summary}
        HD.rw.finalize_artifact(value)
        dump(path, value)
        return Path(name)

    def discussion_draft(self) -> dict:
        return {
            "schema": HD.DISCUSSION_DRAFT,
            "discussion_id": "discussion_one",
            "study_id": "study_fixture",
            "source_hashes": {
                "mechanism": HD.rw.sha256_file(self.root / self.mechanism),
                "network": HD.rw.sha256_file(self.root / self.network),
                "evidence": [HD.rw.sha256_file(self.root / self.evidence)],
            },
            "scientific_question": "Which reviewed active-state and elementary-step proposal should enter later gates?",
            "established_facts": ["The exact source artifacts are hash-bound."],
            "uncertainties": ["The target mechanism is not proven by the present evidence."],
            "alternatives": [
                {"alternative_id": "path_alpha", "summary": "First bounded hypothesis.", "origin": "ai_generated", "proposal_only": True},
                {"alternative_id": "path_beta", "summary": "Competing bounded hypothesis.", "origin": "human_submitted", "proposal_only": True},
            ],
            "ai_assessment": {
                "recommendation": "Review path alpha first.", "rationale": "It best separates the stated alternatives.",
                "risks": ["Analogy may not transfer to the target system."], "origin": "ai_generated", "proposal_only": True, "may_confirm": False,
            },
            "user_decision": {
                "decision": "confirm_selected", "exact_text": "I confirm path alpha only for later independent review gates.",
                "confirmed_claims": [{"claim_type": "elementary_step", "claim_id": "edge_alpha", "alternative_id": "path_alpha", "decision": "confirmed_by_user"}],
                "origin": "explicit_user_input", "assistant_generated": False, "automated_command_generated": False,
                "approver": "fixture_operator", "decided_at": "2026-07-19T10:00:00+08:00",
            },
        }

    def build_discussion(self, draft: dict | None = None, output: str = "discussion.json") -> dict:
        draft_path = self.root / "discussion.draft.json"
        dump(draft_path, draft or self.discussion_draft())
        return HD.build_discussion(self.root, Path(draft_path.name), self.mechanism, self.network, [self.evidence], Path(output))

    def action_draft(self, discussion: dict) -> dict:
        return {
            "schema": HD.ACTION_DRAFT, "card_id": "action_card_one", "study_id": "study_fixture",
            "discussion_payload_sha256": discussion["payload_sha256"], "disposition": "run",
            "purpose": "Test one bounded hypothesis after all independent gates.",
            "exact_scope": {"target_kind": "elementary_step", "target_ids": ["edge_alpha"], "included_actions": ["prepare_for_later_input_review"]},
            "prerequisites": [{"name": "human mechanism discussion", "status": "satisfied", "evidence": "Exact discussion payload is bound."}],
            "scientific_value": "The scoped result would discriminate path alpha from path beta.",
            "estimated_cost": {"status": "unknown", "task_count": None, "core_hours_band": None, "walltime_band": None, "assumptions": ["No resource estimate has been approved."]},
            "success_confidence": {"band": "unknown", "rationale": "No calibrated success data are available."},
            "closure_confidence": {"band": "low", "rationale": "One result would not close the mechanism."},
            "stop_conditions": ["Stop if any prerequisite becomes stale."],
            "continuation": {"on_success": ["Return to scientific review."], "on_failure": ["Return to mechanism discussion without expansion."]},
            "rollback": ["Retain the prior approved discussion unchanged."], "unauthorized_actions": list(HD.UNAUTHORIZED),
        }

    def learning_draft(self, discussion: dict) -> dict:
        return {
            "schema": HD.LEARNING_DRAFT, "update_id": "learning_update_one", "study_id": "study_fixture",
            "discussion_payload_sha256": discussion["payload_sha256"],
            "evidence_hashes": [HD.rw.sha256_file(self.root / self.new_evidence)],
            "observations": ["A new exact evidence artifact was recorded."],
            "interpretations": [{"text": "The earlier edge decision may need revision.", "origin": "ai_generated", "proposal_only": True}],
            "affected_approved_decisions": ["edge_alpha"], "decision_effect": "invalidates_requires_new_discussion",
            "proposed_changes": [{"target_claim_id": "edge_alpha", "proposal": "Re-open the edge choice.", "origin": "ai_generated", "proposal_only": True}],
            "decision_handling": {"approved_decisions_rewritten": False, "new_confirmation_required": True, "automatic_promotion": False},
            "review": {"reviewer": "fixture_operator", "reviewed_at": "2026-07-19T11:00:00+08:00", "notes": ["Record only; no decision is rewritten."]},
        }

    def test_all_three_artifacts_round_trip_and_match_schemas(self) -> None:
        discussion = self.build_discussion()
        action_draft = self.root / "action.draft.json"; dump(action_draft, self.action_draft(discussion))
        action = HD.build_action(self.root, Path(action_draft.name), Path("discussion.json"), Path("action.json"))
        learning_draft = self.root / "learning.draft.json"; dump(learning_draft, self.learning_draft(discussion))
        learning = HD.build_learning(self.root, Path(learning_draft.name), Path("discussion.json"), [self.new_evidence], Path("learning.json"))
        for name, artifact, schema_name in (
            ("discussion.json", discussion, "mechanism-discussion.schema.json"),
            ("action.json", action, "operator-action-card.schema.json"),
            ("learning.json", learning, "study-learning-update.schema.json"),
        ):
            self.assertTrue(HD.validate(self.root, Path(name))["valid"])
            schema = SV.load_json(ROOT / "contracts" / "reaction-workflow" / schema_name)
            SV.validate_schema_document(schema)
            SV._validate_schema_instance(artifact, schema, schema)
        self.assertFalse(action["calculation_ready"])
        self.assertTrue(action["no_submission_authorization"])

    def test_ai_or_automation_cannot_spoof_human_confirmation(self) -> None:
        for field, value, message in (
            ("origin", "ai_generated", "AI-generated content cannot be user confirmation"),
            ("assistant_generated", True, "assistant-generated content cannot be user confirmation"),
            ("automated_command_generated", True, "automated command cannot generate user confirmation"),
        ):
            draft = self.discussion_draft(); draft["user_decision"][field] = value
            with self.assertRaisesRegex(HD.DecisionError, message):
                self.build_discussion(draft, f"spoof-{field}.json")

    def test_stale_evidence_hash_is_rejected_at_build_and_validation(self) -> None:
        draft = self.discussion_draft(); draft["source_hashes"]["evidence"] = ["0" * 64]
        with self.assertRaisesRegex(HD.DecisionError, "evidence review hash is stale"):
            self.build_discussion(draft, "stale-build.json")
        self.build_discussion()
        evidence = json.loads((self.root / self.evidence).read_text(encoding="utf-8")); evidence["summary"] = "Changed evidence"
        HD.rw.finalize_artifact(evidence); dump(self.root / self.evidence, evidence)
        with self.assertRaisesRegex(HD.DecisionError, "evidence hash is stale"):
            HD.validate(self.root, Path("discussion.json"))

    def test_learning_update_cannot_rewrite_approved_decision(self) -> None:
        discussion = self.build_discussion()
        draft = self.learning_draft(discussion)
        draft["decision_handling"]["approved_decisions_rewritten"] = True
        path = self.root / "rewrite.draft.json"; dump(path, draft)
        with self.assertRaisesRegex(HD.DecisionError, "may not rewrite an approved decision"):
            HD.build_learning(self.root, Path(path.name), Path("discussion.json"), [self.new_evidence], Path("rewrite.json"))

    def test_run_action_card_requires_every_hard_prerequisite_satisfied(self) -> None:
        discussion = self.build_discussion()
        for status in ("blocked", "unknown"):
            draft = self.action_draft(discussion)
            draft["prerequisites"].append({"name": "exact minimum lineage", "status": status, "evidence": "No accepted lineage is bound."})
            path = self.root / f"action-{status}.draft.json"; dump(path, draft)
            with self.assertRaisesRegex(HD.DecisionError, "every hard prerequisite"):
                HD.build_action(self.root, Path(path.name), Path("discussion.json"), Path(f"action-{status}.json"))

    def test_changed_evidence_affecting_approval_requires_new_discussion(self) -> None:
        discussion = self.build_discussion()
        draft = self.learning_draft(discussion); draft["decision_effect"] = "proposal_for_review"
        path = self.root / "no-invalidation.draft.json"; dump(path, draft)
        with self.assertRaisesRegex(HD.DecisionError, "requires renewed confirmation"):
            HD.build_learning(self.root, Path(path.name), Path("discussion.json"), [self.new_evidence], Path("no-invalidation.json"))


if __name__ == "__main__":
    unittest.main()
