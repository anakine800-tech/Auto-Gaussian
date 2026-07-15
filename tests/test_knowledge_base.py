#!/usr/bin/env python3
"""Offline tests for the W2A Auto-G16 reusable knowledge contracts."""

from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).parents[1]
SKILL = ROOT / "skills" / "auto-g16-knowledge-base"
SCRIPT = SKILL / "scripts" / "knowledge_base.py"
CONTRACTS = ROOT / "contracts" / "knowledge-base"
FIXTURES = ROOT / "tests" / "fixtures" / "knowledge_base"
RECORDS = FIXTURES / "records"
DRAFTS = FIXTURES / "drafts"

SPEC = importlib.util.spec_from_file_location("auto_g16_knowledge_base", SCRIPT)
assert SPEC and SPEC.loader
KB = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(KB)


def load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def rehash(record: dict[str, object]) -> dict[str, object]:
    if record.get("schema") == "auto-g16-knowledge-snapshot/1":
        record["dependency_digest"] = KB.snapshot_dependency_digest(record)
    record["payload_sha256"] = KB.payload_sha256(record)
    return record


class KnowledgeBaseTests(unittest.TestCase):
    def run_cli(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            cwd=ROOT,
            check=check,
            capture_output=True,
            text=True,
        )

    def assert_rejected(self, record: dict[str, object], expected: str) -> None:
        rehash(record)
        with self.assertRaisesRegex(KB.OfflineError, expected):
            KB.validate_record(record)

    def test_write_json_remains_exclusive_if_precheck_state_is_stale(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "existing.json"
            output.write_bytes(b"sentinel\n")
            with mock.patch.object(Path, "exists", return_value=False):
                with self.assertRaisesRegex(KB.OfflineError, "refusing to overwrite"):
                    KB.write_json(output, {"replacement": True})
            self.assertEqual(output.read_bytes(), b"sentinel\n")

    def test_skill_metadata_and_offline_boundaries_are_complete(self) -> None:
        skill = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        metadata = (SKILL / "agents" / "openai.yaml").read_text(encoding="utf-8")
        script = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("TODO", skill)
        self.assertIn("name: auto-g16-knowledge-base", skill)
        self.assertIn("Auto-G16 Knowledge Base", metadata)
        self.assertIn("$auto-g16-knowledge-base", metadata)
        self.assertIn("calculation_ready: false", skill)
        self.assertIn("no_submission_authorization: true", skill)
        for forbidden in ("import subprocess", "import socket", "requests", "paramiko", "qsub", "qdel"):
            self.assertNotIn(forbidden, script)

    def test_five_closed_contracts_are_present(self) -> None:
        expected = {
            "structure-record.schema.json": "auto-g16-structure-record/1",
            "method-record.schema.json": "auto-g16-method-record/1",
            "source-record.schema.json": "auto-g16-source-record/1",
            "knowledge-link.schema.json": "auto-g16-knowledge-link/1",
            "knowledge-snapshot.schema.json": "auto-g16-knowledge-snapshot/1",
        }
        for name, schema_name in expected.items():
            with self.subTest(contract=name):
                contract = load(CONTRACTS / name)
                self.assertFalse(contract["additionalProperties"])
                self.assertEqual(contract["properties"]["schema"]["const"], schema_name)
                self.assertEqual(contract["properties"]["calculation_ready"]["const"], False)
                self.assertEqual(contract["properties"]["no_submission_authorization"]["const"], True)
        common = load(CONTRACTS / "_common.schema.json")
        for definition in ("review", "access", "provenance", "recordRef", "anchorRef", "objectRef", "fact"):
            self.assertFalse(common["$defs"][definition]["additionalProperties"])

    def test_all_finalized_fixtures_validate(self) -> None:
        records = sorted(RECORDS.glob("*.json"))
        self.assertEqual(len(records), 8)
        seen_schemas: set[str] = set()
        for path in records:
            with self.subTest(record=path.name):
                result = self.run_cli("validate", str(path))
                report = json.loads(result.stdout)
                self.assertTrue(report["valid"])
                self.assertFalse(report["calculation_ready"])
                self.assertTrue(report["no_submission_authorization"])
                seen_schemas.add(report["schema"])
        self.assertEqual(seen_schemas, set(KB.SCHEMAS))

    def test_finalize_is_deterministic_non_authorizing_and_refuses_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "source.json"
            result = self.run_cli(
                "finalize",
                str(DRAFTS / "source-article.json"),
                "--output",
                str(output),
            )
            report = json.loads(result.stdout)
            self.assertFalse(report["calculation_ready"])
            self.assertTrue(report["no_submission_authorization"])
            self.assertEqual(output.read_bytes(), (RECORDS / "source-article.json").read_bytes())
            failed = self.run_cli(
                "finalize",
                str(DRAFTS / "source-article.json"),
                "--output",
                str(output),
                check=False,
            )
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn("refusing to overwrite", failed.stderr)

    def test_tampering_unknown_fields_duplicate_keys_and_nonfinite_numbers_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            tampered = load(RECORDS / "structure-identity.json")
            tampered["identity"]["formula"] = "C4H12B"
            tampered_path = root / "tampered.json"
            tampered_path.write_text(json.dumps(tampered), encoding="utf-8")
            failed = self.run_cli("validate", str(tampered_path), check=False)
            self.assertIn("payload SHA-256 mismatch", failed.stderr)

            unknown = load(RECORDS / "source-article.json")
            unknown["method_selected"] = True
            unknown_path = root / "unknown.json"
            unknown_path.write_text(json.dumps(rehash(unknown)), encoding="utf-8")
            failed = self.run_cli("validate", str(unknown_path), check=False)
            self.assertIn("unknown fields", failed.stderr)

            duplicate_path = root / "duplicate.json"
            duplicate_path.write_text('{"schema":"x","schema":"y"}', encoding="utf-8")
            failed = self.run_cli("validate", str(duplicate_path), check=False)
            self.assertIn("duplicate JSON object key", failed.stderr)

            nan_path = root / "nan.json"
            nan_path.write_text('{"schema":NaN}', encoding="utf-8")
            failed = self.run_cli("validate", str(nan_path), check=False)
            self.assertIn("non-standard JSON numeric constant", failed.stderr)

    def test_identity_state_and_geometry_scopes_cannot_be_collapsed(self) -> None:
        identity = load(RECORDS / "structure-identity.json")
        identity["record_scope"] = "state"
        self.assert_rejected(identity, "state scope")

        state = load(RECORDS / "structure-state.json")
        state["parent_identity"] = None
        self.assert_rejected(state, "parent_identity")

        geometry = load(RECORDS / "structure-geometry.json")
        geometry["representations"][0]["geometry_provenance"] = "normalized_2d"
        self.assert_rejected(geometry, "three-dimensional geometry provenance")

    def test_reported_methods_require_anchors_and_explicit_limits(self) -> None:
        method = load(RECORDS / "method-reported.json")
        method["protocol"]["functional"]["source_anchor_refs"] = []
        self.assert_rejected(method, "reported facts require a source anchor")

        incomplete = load(RECORDS / "method-reported.json")
        incomplete["protocol"]["integration_grid"] = {
            "status": "not_reported",
            "value": None,
            "source_anchor_refs": [],
            "notes": ["Missing in source."],
        }
        self.assert_rejected(incomplete, "reviewed_with_limits")

        selected = load(RECORDS / "method-reported.json")
        selected["selected_for_calculation"] = True
        self.assert_rejected(selected, "unknown fields")

    def test_sources_require_book_edition_claim_anchors_and_short_quotes(self) -> None:
        book = load(RECORDS / "source-book.json")
        book["version"]["edition"] = None
        self.assert_rejected(book, "require an edition")

        article = load(RECORDS / "source-article.json")
        article["claims"][0]["anchor_ids"] = []
        self.assert_rejected(article, "requires a source anchor")

        quote = load(RECORDS / "source-article.json")
        quote["claims"][0]["statement_type"] = "short_quote"
        quote["claims"][0]["text"] = " ".join(["word"] * 26)
        self.assert_rejected(quote, "exceeds 25 words")

    def test_confidential_access_and_link_evidence_fail_closed(self) -> None:
        confidential = load(RECORDS / "structure-identity.json")
        confidential["access"] = {
            "class": "confidential_unpublished",
            "owner_project": "fixture_project",
            "permitted_principals": [],
            "export_policy": "full",
        }
        self.assert_rejected(confidential, "confidential records require permitted_principals")

        link = load(RECORDS / "knowledge-link.json")
        link["source_anchors"] = []
        link["evidence_record_refs"] = []
        self.assert_rejected(link, "reviewed scientific links require evidence")

    def test_snapshot_rejects_unreviewed_members_and_membership_drift(self) -> None:
        snapshot = load(RECORDS / "knowledge-snapshot.json")
        snapshot["included_records"][0]["review_status"] = "draft"
        self.assert_rejected(snapshot, "unreviewed revision")

        membership = load(RECORDS / "knowledge-snapshot.json")
        membership["selection_decisions"] = membership["selection_decisions"][:-1]
        self.assert_rejected(membership, "exactly match included selection decisions")

        digest = load(RECORDS / "knowledge-snapshot.json")
        digest["dependency_digest"] = "e" * 64
        digest["payload_sha256"] = KB.payload_sha256(digest)
        with self.assertRaisesRegex(KB.OfflineError, "dependency digest mismatch"):
            KB.validate_record(digest)

    def test_audit_set_reports_duplicates_and_conflicts_without_merging(self) -> None:
        scenario = load(FIXTURES / "audit-scenarios.json")
        identity = load(FIXTURES / scenario["base_record"])
        duplicate = copy.deepcopy(identity)
        duplicate.update(scenario["duplicate_candidate"])
        rehash(duplicate)
        conflict = copy.deepcopy(identity)
        conflict["identity"]["formula"] = scenario["conflicting_revision"]["identity_formula"]
        rehash(conflict)

        report = KB.audit_record_set([identity, duplicate, conflict])
        kinds = {item["kind"] for item in report["duplicate_candidates"]}
        conflict_kinds = {item["kind"] for item in report["conflicts"]}
        self.assertIn(scenario["expected_duplicate_kind"], kinds)
        self.assertIn(scenario["expected_conflict_kind"], conflict_kinds)
        self.assertFalse(report["automatic_merge_performed"])
        self.assertFalse(report["calculation_ready"])
        self.assertTrue(report["no_submission_authorization"])

    def test_snapshot_remains_valid_when_unrelated_records_are_added_to_an_audit(self) -> None:
        snapshot = load(RECORDS / "knowledge-snapshot.json")
        original_hash = snapshot["payload_sha256"]
        extra = load(RECORDS / "structure-identity.json")
        extra["record_id"] = "fixture_unrelated_identity"
        extra["revision_id"] = "fixture_unrelated_identity_r001"
        extra["identity"]["canonical_smiles"] = "C"
        extra["identity"]["inchikey"] = "UNRELATEDFIXTUREKEY0000000"
        rehash(extra)
        KB.audit_record_set([extra])
        KB.validate_record(snapshot)
        self.assertEqual(snapshot["payload_sha256"], original_hash)


if __name__ == "__main__":
    unittest.main()
