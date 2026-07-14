#!/usr/bin/env python3
"""Offline tests for the mechanism/TS literature discovery Skill."""

from __future__ import annotations

import json
import runpy
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
SKILL = ROOT / "skills" / "auto-g16-reaction-literature"
SCRIPT = SKILL / "scripts" / "literature_search.py"
FIXTURES = ROOT / "tests" / "fixtures" / "reaction_literature"


class ReactionLiteratureTests(unittest.TestCase):
    def run_cli(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            cwd=ROOT,
            check=check,
            capture_output=True,
            text=True,
        )

    def build_offline_chain(self, root: Path) -> tuple[Path, Path, Path]:
        plan = root / "plan.json"
        retrieval_dir = root / "retrieval"
        ledger = root / "ledger.json"
        self.run_cli("plan", str(FIXTURES / "intake.json"), "--output", str(plan))
        self.run_cli(
            "retrieve",
            str(plan),
            "--output-dir",
            str(retrieval_dir),
            "--sources",
            "crossref,openalex",
            "--query-ids",
            "q001",
            "--offline-fixture-dir",
            str(FIXTURES),
        )
        self.run_cli(
            "rank",
            str(plan),
            str(retrieval_dir / "retrieval.json"),
            "--output",
            str(ledger),
            "--report",
            str(root / "report.md"),
        )
        return plan, retrieval_dir, ledger

    def test_skill_has_complete_metadata_and_boundaries(self) -> None:
        skill = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        metadata = (SKILL / "agents" / "openai.yaml").read_text(encoding="utf-8")
        self.assertNotIn("TODO", skill)
        self.assertIn("name: auto-g16-reaction-literature", skill)
        self.assertIn("discovery metadata only", skill)
        self.assertIn("Auto-G16", metadata)

    def test_plan_retrieve_rank_chain_is_offline_and_hash_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan_path, retrieval_dir, ledger_path = self.build_offline_chain(root)
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            retrieval = json.loads((retrieval_dir / "retrieval.json").read_text(encoding="utf-8"))
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))

            self.assertEqual(plan["schema"], "gaussian-reaction-literature-query/1")
            self.assertGreater(plan["query_count"], 5)
            self.assertEqual(plan["w2_binding_status"], "standalone_search_not_promotable")
            self.assertEqual(len(plan["promotion_blockers"]), 4)
            self.assertEqual(retrieval["mode"], "offline_fixture_replay")
            self.assertEqual(retrieval["summary"]["successful_payloads"], 2)
            self.assertEqual(ledger["counts"]["normalized_raw_records"], 4)
            self.assertEqual(ledger["counts"]["unique_candidates"], 3)
            self.assertFalse(ledger["ranking_policy"]["citation_count_used_in_score"])
            self.assertFalse(ledger["calculation_ready"])
            self.assertTrue(ledger["no_submission_authorization"])
            self.assertFalse(ledger["promotable_to_mechanism_support"])

            top = ledger["candidates"][0]
            self.assertEqual(top["doi"], "10.1021/jacs.4c09067")
            self.assertIn("α-Alkylation", top["title"])
            self.assertIn(
                "Borane-Catalyzed Enantioselective alpha-Alkylation",
                top["score_breakdown"]["matched_terms"]["exact_phrases"],
            )
            self.assertEqual(len(top["discovery_observations"]), 2)
            unrelated = next(item for item in ledger["candidates"] if item["doi"] == "10.5555/unrelated")
            self.assertEqual(unrelated["cited_by_count"], 9999)
            self.assertEqual(unrelated["lexical_score"], 0)

    def test_title_identity_key_preserves_non_latin_distinctions(self) -> None:
        namespace = runpy.run_path(str(SCRIPT), run_name="literature_search_test")
        self.assertNotEqual(
            namespace["title_key"]("反应机理"), namespace["title_key"]("过渡态")
        )

    def test_review_template_validates_and_finalizes_without_authorization(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _, _, ledger = self.build_offline_chain(root)
            draft = root / "review-draft.json"
            final = root / "review-final.json"
            self.run_cli("init-review", str(ledger), "--output", str(draft), "--limit", "2")
            draft_data = json.loads(draft.read_text(encoding="utf-8"))
            self.assertEqual(draft_data["record_status"], "editable_review_template")
            self.assertIsNone(draft_data["evidence_review_payload_sha256"])
            self.run_cli("validate-review", str(draft), "--output", str(final))
            final_data = json.loads(final.read_text(encoding="utf-8"))
            self.assertEqual(final_data["record_status"], "validated_review_record")
            self.assertEqual(final_data["schema"], "gaussian-reaction-literature-evidence/1")
            self.assertTrue(final_data["evidence_review_payload_sha256"])
            self.assertFalse(final_data["calculation_ready"])

    def test_review_rejects_unlocated_claim_and_long_quote(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _, _, ledger = self.build_offline_chain(root)
            draft = root / "review-draft.json"
            self.run_cli("init-review", str(ledger), "--output", str(draft), "--limit", "1")
            review = json.loads(draft.read_text(encoding="utf-8"))
            claim = next(iter(review["reviews"][0]["evidence"].values()))
            claim["status"] = "source_reports"
            draft.write_text(json.dumps(review), encoding="utf-8")
            failed = self.run_cli("validate-review", str(draft), check=False)
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn("requires a source location", failed.stderr)

            claim["status"] = "not_reviewed"
            review["reviews"][0]["exact_quotes"] = [
                {"text": " ".join(["word"] * 26), "locator": "page 1"}
            ]
            draft.write_text(json.dumps(review), encoding="utf-8")
            failed = self.run_cli("validate-review", str(draft), check=False)
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn("exceeds 25 words", failed.stderr)

    def test_review_rejects_missing_target_and_bibliography_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _, _, ledger = self.build_offline_chain(root)
            draft = root / "review-draft.json"
            self.run_cli("init-review", str(ledger), "--output", str(draft), "--limit", "1")
            review = json.loads(draft.read_text(encoding="utf-8"))
            original_evidence = dict(review["reviews"][0]["evidence"])
            review["reviews"][0]["evidence"].pop("proposed_mechanism")
            draft.write_text(json.dumps(review), encoding="utf-8")
            failed = self.run_cli("validate-review", str(draft), check=False)
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn("exactly match the bound target_evidence", failed.stderr)

            review["reviews"][0]["evidence"] = original_evidence
            review["reviews"][0]["bibliography"]["doi"] = "10.5555/different"
            draft.write_text(json.dumps(review), encoding="utf-8")
            failed = self.run_cli("validate-review", str(draft), check=False)
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn("DOI differs from the bound candidate ledger", failed.stderr)

    def test_outputs_are_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "plan.json"
            self.run_cli("plan", str(FIXTURES / "intake.json"), "--output", str(output))
            failed = self.run_cli(
                "plan", str(FIXTURES / "intake.json"), "--output", str(output), check=False
            )
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn("refusing to overwrite", failed.stderr)

    def test_nonstandard_and_duplicate_key_json_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            duplicate = root / "duplicate.json"
            duplicate.write_text(
                '{"schema":"gaussian-reaction-literature-request/1",'
                '"schema":"gaussian-reaction-literature-request/1"}',
                encoding="utf-8",
            )
            failed = self.run_cli(
                "plan", str(duplicate), "--output", str(root / "duplicate-plan.json"), check=False
            )
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn("duplicate JSON key", failed.stderr)

            nonfinite = root / "nonfinite.json"
            nonfinite.write_text('{"value":NaN}', encoding="utf-8")
            failed = self.run_cli(
                "plan", str(nonfinite), "--output", str(root / "nonfinite-plan.json"), check=False
            )
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn("non-standard JSON numeric constant", failed.stderr)


if __name__ == "__main__":
    unittest.main()
