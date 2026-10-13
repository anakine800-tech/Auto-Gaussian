#!/usr/bin/env python3
"""Offline tests for immutable private-manual evidence receipts."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
TOOL = ROOT / "skills" / "auto-g16-knowledge-base" / "scripts" / "manual_evidence.py"
CONTRACTS = ROOT / "contracts" / "knowledge-base"
FIXTURES = ROOT / "tests" / "fixtures" / "knowledge_base" / "manual_evidence"

SPEC = importlib.util.spec_from_file_location("auto_g16_manual_evidence", TOOL)
assert SPEC and SPEC.loader
MANUAL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MANUAL)

SCHEMA_SPEC = importlib.util.spec_from_file_location(
    "auto_g16_manual_evidence_schema_validator",
    ROOT / "scripts" / "validate_asymmetric_contract.py",
)
assert SCHEMA_SPEC and SCHEMA_SPEC.loader
SCHEMA_VALIDATOR = importlib.util.module_from_spec(SCHEMA_SPEC)
SCHEMA_SPEC.loader.exec_module(SCHEMA_VALIDATOR)


def load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ManualEvidenceTests(unittest.TestCase):
    maxDiff = None

    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(TOOL), *args],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def create_database(self, path: Path, *, locator: bool = True, quality_notes: str | None = "Synthetic OCR quality is limited.") -> None:
        connection = sqlite3.connect(path)
        try:
            connection.execute(
                """
                CREATE TABLE manual_chunks (
                    result_id TEXT PRIMARY KEY,
                    canonical_store_digest TEXT NOT NULL,
                    source_record_id TEXT NOT NULL,
                    source_revision TEXT NOT NULL,
                    source_payload_sha256 TEXT NOT NULL,
                    source_object_sha256 TEXT NOT NULL,
                    source_kind TEXT NOT NULL,
                    locator_kind TEXT NOT NULL,
                    page INTEGER,
                    logical_chunk TEXT,
                    text_quality TEXT NOT NULL,
                    text_quality_notes TEXT,
                    source_program TEXT,
                    source_major_version TEXT,
                    source_version TEXT,
                    evidence_text TEXT NOT NULL
                )
                """
            )
            long_private_tail = " PRIVATE_LONG_TEXT_MUST_NOT_ENTER_RECEIPT" * 40
            connection.execute(
                "INSERT INTO manual_chunks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "chunk_g09_opt",
                    "a" * 64,
                    "gaussian09_manual",
                    "gaussian09_manual_revision_d01",
                    "b" * 64,
                    "c" * 64,
                    "gaussian_program_manual",
                    "physical_page",
                    42 if locator else None,
                    None,
                    "embedded_ocr_unreviewed",
                    quality_notes,
                    "Gaussian",
                    "G09",
                    "Gaussian 09 Revision D.01 synthetic source",
                    "Optimization convergence behavior is described for the synthetic fixture." + long_private_tail,
                ),
            )
            connection.execute(
                "INSERT INTO manual_chunks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "chunk_g16_scf",
                    "a" * 64,
                    "gaussian16_manual",
                    "gaussian16_manual_revision_c02",
                    "d" * 64,
                    "e" * 64,
                    "gaussian_program_manual",
                    "physical_page",
                    77,
                    "scf_chunk_077",
                    "embedded_text",
                    None,
                    "Gaussian",
                    "G16",
                    "Gaussian 16 Revision C.02 synthetic source",
                    "A separate synthetic passage discusses SCF convergence.",
                ),
            )
            connection.execute(
                "INSERT INTO manual_chunks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "chunk_general_variational",
                    "f" * 64,
                    "modern_quantum_chemistry",
                    "modern_quantum_chemistry_revision_001",
                    "1" * 64,
                    "2" * 64,
                    "general_electronic_structure",
                    "physical_page",
                    18,
                    None,
                    "embedded_text",
                    None,
                    None,
                    None,
                    None,
                    "Variational principle evidence for a general electronic-structure discussion.",
                ),
            )
            connection.execute(
                "INSERT INTO manual_chunks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "chunk_legacy_doc_007",
                    "4" * 64,
                    "exploring_chemistry_legacy",
                    "exploring_chemistry_revision_001",
                    "5" * 64,
                    "6" * 64,
                    "gaussian_associated_text",
                    "logical_chunk",
                    None,
                    "legacy_doc_chunk_007",
                    "legacy_word_text_pagination_unstable",
                    "Legacy Word numeric sections are logical chunks, not stable pages.",
                    None,
                    None,
                    None,
                    "Legacy pagination discussion for a synthetic logical chunk.",
                ),
            )
            connection.execute(
                "INSERT INTO manual_chunks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "metadata_gaussian09",
                    "a" * 64,
                    "gaussian09_manual",
                    "gaussian09_manual_revision_d01",
                    "b" * 64,
                    "c" * 64,
                    "gaussian_program_manual",
                    "metadata",
                    0,
                    "metadata_gaussian09",
                    "embedded_text",
                    None,
                    "Gaussian",
                    "G09",
                    "Gaussian 09 Revision D.01 synthetic source",
                    "Metadata sentinel that must be excluded from normal page retrieval.",
                ),
            )
            connection.execute(
                "INSERT INTO manual_chunks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "image_only_page_003",
                    "7" * 64,
                    "image_only_manual",
                    "image_only_manual_revision_001",
                    "8" * 64,
                    "9" * 64,
                    "gaussian_associated_text",
                    "physical_page",
                    3,
                    None,
                    "image_only",
                    "No OCR text exists; review must use the exact page image object.",
                    None,
                    None,
                    None,
                    "",
                ),
            )
            connection.commit()
        finally:
            connection.close()

    def build(self, root: Path, review: dict[str, object] | None = None) -> tuple[Path, subprocess.CompletedProcess[str]]:
        database = root / "private-manual.sqlite"
        self.create_database(database)
        review_path = root / "review.json"
        write(review_path, review or load(FIXTURES / "review.json"))
        output = root / "receipt.json"
        result = self.run_cli(
            "build-receipt",
            "--config", str(FIXTURES / "adapter.json"),
            "--database", str(database),
            "--expected-db-sha256", digest(database),
            "--review", str(review_path),
            "--output", str(output),
        )
        return output, result

    def assert_schema_valid(self, schema_name: str, instance: dict[str, object]) -> None:
        schema = SCHEMA_VALIDATOR.load_json(CONTRACTS / schema_name)
        SCHEMA_VALIDATOR.validate_schema_document(schema)
        SCHEMA_VALIDATOR._validate_schema_instance(instance, schema, schema)

    def test_contracts_are_closed_and_supported_by_the_offline_schema_validator(self) -> None:
        for name in (
            "manual-evidence-receipt.schema.json",
            "manual-retrieval-adapter.schema.json",
            "manual-evidence-review.schema.json",
        ):
            with self.subTest(schema=name):
                schema = SCHEMA_VALIDATOR.load_json(CONTRACTS / name)
                SCHEMA_VALIDATOR.validate_schema_document(schema)
                self.assertFalse(schema["additionalProperties"])
        self.assert_schema_valid("manual-retrieval-adapter.schema.json", load(FIXTURES / "adapter.json"))
        self.assert_schema_valid("manual-evidence-review.schema.json", load(FIXTURES / "review.json"))
        self.assertNotIn("claim_scope", MANUAL.REQUIRED_RESULT_COLUMNS)
        self.assertNotIn("claim_scope", load(FIXTURES / "adapter.json")["query_sql"])
        source = TOOL.read_text(encoding="utf-8")
        for forbidden in ("import subprocess", "import socket", "requests", "paramiko", "qsub", "qdel"):
            self.assertNotIn(forbidden, source)

    def test_synthetic_readonly_query_and_receipt_build_are_hash_bound_and_text_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            database = root / "private-manual.sqlite"
            self.create_database(database)
            before = digest(database)
            queried = self.run_cli(
                "query",
                "--config", str(FIXTURES / "adapter.json"),
                "--database", str(database),
                "--expected-db-sha256", before,
                "--query", "optimization convergence",
                "--limit", "5",
            )
            self.assertEqual(queried.returncode, 0, queried.stderr)
            report = json.loads(queried.stdout)
            self.assertEqual([item["result_id"] for item in report["candidates"]], ["chunk_g09_opt"])
            self.assertLessEqual(len(report["candidates"][0]["preview"]), 120)
            self.assertTrue(report["private_operational_output_do_not_commit"])
            self.assertEqual(digest(database), before)
            self.assertFalse(Path(str(database) + "-journal").exists())
            self.assertFalse(Path(str(database) + "-wal").exists())

            review_path = root / "review.json"
            write(review_path, load(FIXTURES / "review.json"))
            output = root / "receipt.json"
            built = self.run_cli(
                "build-receipt",
                "--config", str(FIXTURES / "adapter.json"),
                "--database", str(database),
                "--expected-db-sha256", before,
                "--review", str(review_path),
                "--output", str(output),
            )
            self.assertEqual(built.returncode, 0, built.stderr)
            receipt = load(output)
            MANUAL.validate_receipt(receipt)
            self.assert_schema_valid("manual-evidence-receipt.schema.json", receipt)
            self.assertEqual(receipt["retrieval"]["retrieval_database_sha256"], before)
            self.assertEqual(receipt["retrieval"]["canonical_store_digest"], "a" * 64)
            self.assertEqual(receipt["source"]["revision"], "gaussian09_manual_revision_d01")
            self.assertEqual(receipt["source"]["payload_sha256"], "b" * 64)
            self.assertEqual(receipt["source"]["object_sha256"], "c" * 64)
            self.assertEqual(receipt["source"]["locator"], {"kind": "physical_page", "page": 42, "logical_chunk": None})
            self.assertEqual(receipt["source"]["record_id"], "gaussian09_manual")
            self.assertEqual(receipt["source"]["source_kind"], "gaussian_program_manual")
            self.assertEqual(receipt["source"]["claim_scope"], "gaussian_syntax_or_version")
            self.assertEqual(receipt["source"]["text_quality"]["classification"], "embedded_ocr_unreviewed")
            self.assertEqual(receipt["evidence"]["whole_page_visual_review"]["status"], "reviewed")
            self.assertEqual(receipt["source"]["program"]["major_version"], "G09")
            self.assertEqual(receipt["target_installation"]["major_version"], "G16")
            self.assertEqual(receipt["applicability"]["decision"], "applicable_with_limits")
            self.assertEqual(receipt["downstream_role"], "scientific_maturity_supporting_evidence")
            self.assertFalse(receipt["calculation_ready"])
            self.assertTrue(receipt["no_submission_authorization"])
            self.assertTrue(receipt["no_method_selection_authorization"])
            self.assertTrue(receipt["no_input_generation_authorization"])
            serialized = output.read_text(encoding="utf-8")
            self.assertNotIn("PRIVATE_LONG_TEXT_MUST_NOT_ENTER_RECEIPT", serialized)
            self.assertNotIn(str(root), serialized)
            self.assertEqual(serialized.count('"downstream_role"'), 1)
            self.assertEqual(digest(database), before)

            validated = self.run_cli("validate", str(output))
            self.assertEqual(validated.returncode, 0, validated.stderr)
            duplicate = self.run_cli(
                "build-receipt",
                "--config", str(FIXTURES / "adapter.json"),
                "--database", str(database),
                "--expected-db-sha256", before,
                "--review", str(review_path),
                "--output", str(output),
            )
            self.assertNotEqual(duplicate.returncode, 0)
            self.assertIn("refusing to overwrite", duplicate.stderr)

    def test_g09_to_g16_without_installed_revision_review_fails_closed(self) -> None:
        review = load(FIXTURES / "review.json")
        review["installed_revision_review"] = {
            "status": "not_reviewed",
            "reviewer": None,
            "reviewed_at": None,
            "evidence_sha256": [],
            "notes": ["Target installed revision has not been reviewed."],
        }
        with tempfile.TemporaryDirectory() as temp:
            output, failed = self.build(Path(temp), review)
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn("G09-to-G16 evidence must fail closed", failed.stderr)
            self.assertFalse(output.exists())

        review["applicability_decision"] = "blocked_pending_installed_revision_review"
        review["applicability_rationale"] = "No positive applicability is claimed before installed-revision review."
        with tempfile.TemporaryDirectory() as temp:
            output, passed = self.build(Path(temp), review)
            self.assertEqual(passed.returncode, 0, passed.stderr)
            receipt = load(output)
            self.assertEqual(receipt["applicability"]["decision"], "blocked_pending_installed_revision_review")
            self.assertEqual(receipt["applicability"]["installed_revision_review"]["status"], "not_reviewed")

        nonversion = load(FIXTURES / "review.json")
        nonversion["receipt_id"] = "fixture_g09_nonversion_concept"
        nonversion["claim_scope"] = "gaussian_nonversion_concept"
        nonversion["installed_revision_review"] = {
            "status": "not_applicable_non_version_claim",
            "reviewer": None,
            "reviewed_at": None,
            "evidence_sha256": [],
            "notes": ["This review uses the G09 source only for a non-version concept."],
        }
        nonversion["applicability_rationale"] = "The same G09 page is bounded to a non-version concept; no installed-revision compatibility claim is made."
        with tempfile.TemporaryDirectory() as temp:
            output, passed = self.build(Path(temp), nonversion)
            self.assertEqual(passed.returncode, 0, passed.stderr)
            receipt = load(output)
            self.assertEqual(receipt["source"]["claim_scope"], "gaussian_nonversion_concept")
            self.assertEqual(receipt["applicability"]["decision"], "applicable_with_limits")
            self.assertEqual(receipt["applicability"]["installed_revision_review"]["status"], "not_applicable_non_version_claim")

    def test_general_theory_source_has_null_program_version_and_no_fake_g09_g16_gate(self) -> None:
        review = load(FIXTURES / "review.json")
        review.update(
            {
                "receipt_id": "fixture_general_variational_evidence",
                "query": "variational principle",
                "selected_result_id": "chunk_general_variational",
                "claim_scope": "general_electronic_structure",
                "short_paraphrase": "The selected textbook page supports a general variational-principle concept without asserting Gaussian syntax or version behavior.",
                "installed_revision_review": {
                    "status": "not_applicable_non_version_claim",
                    "reviewer": None,
                    "reviewed_at": None,
                    "evidence_sha256": [],
                    "notes": ["Installed Gaussian revision review is not applicable to this general theoretical claim."],
                },
                "applicability_decision": "applicable",
                "applicability_rationale": "The evidence is bounded to a general electronic-structure concept, not Gaussian program behavior.",
                "uncertainties": [],
            }
        )
        with tempfile.TemporaryDirectory() as temp:
            output, result = self.build(Path(temp), review)
            self.assertEqual(result.returncode, 0, result.stderr)
            receipt = load(output)
            self.assertEqual(receipt["source"]["source_kind"], "general_electronic_structure")
            self.assertEqual(receipt["source"]["claim_scope"], "general_electronic_structure")
            self.assertEqual(receipt["source"]["program"], {"name": None, "major_version": None, "version": None})
            self.assertEqual(receipt["applicability"]["installed_revision_review"]["status"], "not_applicable_non_version_claim")
            self.assertEqual(receipt["applicability"]["decision"], "applicable")
            self.assert_schema_valid("manual-evidence-receipt.schema.json", receipt)

    def test_metadata_zero_is_excluded_and_legacy_doc_is_a_reviewed_logical_chunk(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            database = root / "manual.sqlite"
            self.create_database(database)
            database_sha = digest(database)
            metadata = self.run_cli(
                "query", "--config", str(FIXTURES / "adapter.json"),
                "--database", str(database), "--expected-db-sha256", database_sha,
                "--query", "Metadata sentinel", "--limit", "5",
            )
            self.assertEqual(metadata.returncode, 0, metadata.stderr)
            self.assertEqual(json.loads(metadata.stdout)["candidates"], [])

            legacy = self.run_cli(
                "query", "--config", str(FIXTURES / "adapter.json"),
                "--database", str(database), "--expected-db-sha256", database_sha,
                "--query", "Legacy pagination", "--limit", "5",
            )
            self.assertEqual(legacy.returncode, 0, legacy.stderr)
            candidate = json.loads(legacy.stdout)["candidates"][0]
            self.assertEqual(candidate["locator_kind"], "logical_chunk")
            self.assertIsNone(candidate["page"])
            self.assertEqual(candidate["logical_chunk"], "legacy_doc_chunk_007")

        review = load(FIXTURES / "review.json")
        review.update(
            {
                "receipt_id": "fixture_legacy_doc_logical_chunk",
                "query": "Legacy pagination",
                "selected_result_id": "chunk_legacy_doc_007",
                "claim_scope": "gaussian_nonversion_concept",
                "short_paraphrase": "The reviewed legacy Word block supports a bounded non-version concept; its numeric label is not treated as a physical page.",
                "whole_page_visual_review": {
                    "status": "not_applicable_logical_chunk_only",
                    "reviewer": None,
                    "reviewed_at": None,
                    "notes": ["Legacy Word pagination is unstable and no physical page is claimed."],
                },
                "logical_chunk_review": {
                    "status": "reviewed",
                    "reviewer": "fixture_manual_reviewer",
                    "reviewed_at": "2026-07-17T04:00:00Z",
                    "notes": ["The complete synthetic logical chunk was reviewed."],
                },
                "installed_revision_review": {
                    "status": "not_applicable_non_version_claim",
                    "reviewer": None,
                    "reviewed_at": None,
                    "evidence_sha256": [],
                    "notes": ["Installed-revision comparison is not applicable to this non-version claim."],
                },
                "applicability_rationale": "Only the reviewed logical chunk and its propagated legacy limitations are applicable.",
                "uncertainties": ["Legacy Word pagination is unstable; the numeric source label is not a page."],
            }
        )
        with tempfile.TemporaryDirectory() as temp:
            output, result = self.build(Path(temp), review)
            self.assertEqual(result.returncode, 0, result.stderr)
            receipt = load(output)
            self.assertEqual(
                receipt["source"]["locator"],
                {"kind": "logical_chunk", "page": None, "logical_chunk": "legacy_doc_chunk_007"},
            )
            self.assertEqual(receipt["evidence"]["logical_chunk_review"]["status"], "reviewed")

    def test_image_only_exact_locator_supports_empty_preview_but_requires_page_review(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            database = root / "manual.sqlite"
            self.create_database(database)
            database_sha = digest(database)
            config = load(FIXTURES / "adapter.json")
            config["query_sql"] = config["query_sql"].replace(
                "WHERE (page IS NULL OR page > 0) AND instr(lower(evidence_text), lower(:query)) > 0 ORDER BY result_id LIMIT :limit",
                "WHERE result_id = :query AND :limit > 0 LIMIT :limit",
            )
            config["selection_sql"] = config["selection_sql"].replace(
                "WHERE result_id = :result_id AND (page IS NULL OR page > 0) AND instr(lower(evidence_text), lower(:query)) > 0",
                "WHERE result_id = :result_id AND result_id = :query",
            )
            config_path = root / "image-locator-adapter.json"
            write(config_path, config)
            queried = self.run_cli(
                "query", "--config", str(config_path), "--database", str(database),
                "--expected-db-sha256", database_sha, "--query", "image_only_page_003", "--limit", "1",
            )
            self.assertEqual(queried.returncode, 0, queried.stderr)
            candidate = json.loads(queried.stdout)["candidates"][0]
            self.assertEqual(candidate["text_quality"], "image_only")
            self.assertEqual(candidate["preview"], "")

            review = load(FIXTURES / "review.json")
            review.update(
                {
                    "receipt_id": "fixture_image_only_page_review",
                    "query": "image_only_page_003",
                    "selected_result_id": "image_only_page_003",
                    "claim_scope": "gaussian_nonversion_concept",
                    "short_paraphrase": "The exact page image was manually reviewed; no searchable OCR or extracted text is claimed.",
                    "logical_chunk_review": {
                        "status": "not_applicable_no_logical_chunk",
                        "reviewer": None,
                        "reviewed_at": None,
                        "notes": ["The source is located by exact physical page."],
                    },
                    "installed_revision_review": {
                        "status": "not_applicable_non_version_claim",
                        "reviewer": None,
                        "reviewed_at": None,
                        "evidence_sha256": [],
                        "notes": ["No version-specific claim is made."],
                    },
                    "applicability_rationale": "Positive use is limited to the manually reviewed exact page image.",
                    "uncertainties": ["No OCR or embedded text exists; content was not full-text searchable."],
                }
            )
            review_path = root / "image-review.json"
            write(review_path, review)
            output = root / "image-receipt.json"
            built = self.run_cli(
                "build-receipt", "--config", str(config_path), "--database", str(database),
                "--expected-db-sha256", database_sha, "--review", str(review_path), "--output", str(output),
            )
            self.assertEqual(built.returncode, 0, built.stderr)
            receipt = load(output)
            self.assertEqual(receipt["retrieval"]["retrieved_text_sha256"], hashlib.sha256(b"").hexdigest())
            self.assertEqual(receipt["source"]["locator"]["kind"], "physical_page")

            review["whole_page_visual_review"] = {
                "status": "not_reviewed",
                "reviewer": None,
                "reviewed_at": None,
                "notes": ["Exact page image has not been reviewed."],
            }
            negative_path = root / "image-negative-review.json"
            write(negative_path, review)
            failed = self.run_cli(
                "build-receipt", "--config", str(config_path), "--database", str(database),
                "--expected-db-sha256", database_sha, "--review", str(negative_path),
                "--output", str(root / "image-negative-receipt.json"),
            )
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn("requires whole-page visual review", failed.stderr)

    def test_degraded_source_classes_require_notes_uncertainty_and_bounded_decision(self) -> None:
        base = {
            "result_id": "fixture_result",
            "canonical_store_digest": "1" * 64,
            "source_record_id": "fixture_source",
            "source_revision": "fixture_revision",
            "source_payload_sha256": "2" * 64,
            "source_object_sha256": "3" * 64,
            "source_kind": "gaussian_program_manual",
            "locator_kind": "logical_chunk",
            "page": None,
            "logical_chunk": "fixture_chunk",
            "text_quality": "embedded_ocr_unreviewed",
            "text_quality_notes": None,
            "source_program": "Gaussian",
            "source_major_version": "G09",
            "source_version": "Gaussian 09 synthetic",
            "evidence_text": "fixture evidence",
        }
        for quality in ("embedded_ocr_unreviewed", "legacy_word_text_pagination_unstable", "image_only"):
            with self.subTest(quality=quality):
                row = copy.deepcopy(base)
                row["text_quality"] = quality
                if quality == "image_only":
                    row["evidence_text"] = ""
                with self.assertRaisesRegex(MANUAL.ManualEvidenceError, "text_quality_notes"):
                    MANUAL._normalize_row(row)
                row["text_quality_notes"] = f"Explicit {quality} limitation."
                normalized, _ = MANUAL._normalize_row(row)
                self.assertEqual(normalized["text_quality"], quality)
                self.assertEqual(normalized["text_quality_notes"], f"Explicit {quality} limitation.")

        legacy = copy.deepcopy(base)
        legacy.update(
            {
                "text_quality": "legacy_word_text_pagination_unstable",
                "text_quality_notes": "Legacy Word pagination is unstable.",
            }
        )
        legacy_row, _ = MANUAL._normalize_row(legacy)
        legacy_review = load(FIXTURES / "review.json")
        legacy_review["selected_result_id"] = "fixture_result"
        legacy_review["whole_page_visual_review"] = {
            "status": "not_applicable_logical_chunk_only",
            "reviewer": None,
            "reviewed_at": None,
            "notes": ["Legacy Word source has no stable page."],
        }
        legacy_review["logical_chunk_review"] = {
            "status": "not_reviewed",
            "reviewer": None,
            "reviewed_at": None,
            "notes": ["Logical chunk has not been reviewed."],
        }
        with self.assertRaisesRegex(MANUAL.ManualEvidenceError, "logical-chunk review"):
            MANUAL.validate_review(legacy_review, legacy_row)

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output, built = self.build(root)
            self.assertEqual(built.returncode, 0, built.stderr)
            receipt = load(output)
            receipt["uncertainties"] = []
            receipt["payload_sha256"] = MANUAL.payload_sha(receipt)
            with self.assertRaisesRegex(MANUAL.ManualEvidenceError, "uncertainty propagation"):
                MANUAL.validate_receipt(receipt)

    def test_hash_drift_locator_gaps_and_sql_write_shapes_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            database = root / "manual.sqlite"
            self.create_database(database)
            failed = self.run_cli(
                "query",
                "--config", str(FIXTURES / "adapter.json"),
                "--database", str(database),
                "--expected-db-sha256", "0" * 64,
                "--query", "optimization convergence",
            )
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn("database SHA-256 mismatch", failed.stderr)

            sidecar = Path(str(database) + "-wal")
            sidecar.write_bytes(b"synthetic unstable sidecar")
            failed = self.run_cli(
                "query",
                "--config", str(FIXTURES / "adapter.json"),
                "--database", str(database),
                "--expected-db-sha256", digest(database),
                "--query", "optimization convergence",
            )
            self.assertIn("unstable SQLite sidecar", failed.stderr)

        unsafe = load(FIXTURES / "adapter.json")
        unsafe["query_sql"] = "DELETE FROM manual_chunks WHERE evidence_text = :query LIMIT :limit"
        with self.assertRaisesRegex(MANUAL.ManualEvidenceError, "SELECT/WITH"):
            MANUAL.validate_config(unsafe)
        unsafe = load(FIXTURES / "adapter.json")
        unsafe["query_sql"] += "; SELECT :query, :limit"
        with self.assertRaisesRegex(MANUAL.ManualEvidenceError, "statement separator"):
            MANUAL.validate_config(unsafe)

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            database = root / "manual.sqlite"
            self.create_database(database, locator=False)
            failed = self.run_cli(
                "query",
                "--config", str(FIXTURES / "adapter.json"),
                "--database", str(database),
                "--expected-db-sha256", digest(database),
                "--query", "optimization convergence",
            )
            self.assertIn("requires page or logical_chunk", failed.stderr)

    def test_sql_function_row_and_step_budgets_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            database = root / "manual.sqlite"
            self.create_database(database)
            database_sha = digest(database)

            function_config = load(FIXTURES / "adapter.json")
            function_config["query_sql"] = function_config["query_sql"].replace(
                "evidence_text FROM",
                "randomblob(8) AS evidence_text FROM",
                1,
            )
            function_path = root / "function-config.json"
            write(function_path, function_config)
            failed = self.run_cli(
                "query", "--config", str(function_path), "--database", str(database),
                "--expected-db-sha256", database_sha, "--query", "optimization", "--limit", "1",
            )
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn("randomblob", failed.stderr)
            self.assertIn("not authorized", failed.stderr)

            unlimited_config = load(FIXTURES / "adapter.json")
            unlimited_config["query_sql"] = unlimited_config["query_sql"].replace(
                " ORDER BY result_id LIMIT :limit",
                " AND :limit >= 0 ORDER BY result_id",
            )
            unlimited_path = root / "unlimited-config.json"
            write(unlimited_path, unlimited_config)
            failed = self.run_cli(
                "query", "--config", str(unlimited_path), "--database", str(database),
                "--expected-db-sha256", database_sha, "--query", "e", "--limit", "1",
            )
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn("more than the allowed 1 rows", failed.stderr)

            multi_config = load(FIXTURES / "adapter.json")
            multi_config["selection_sql"] = multi_config["selection_sql"].replace(
                "result_id = :result_id AND (page IS NULL OR page > 0) AND instr(lower(evidence_text), lower(:query)) > 0",
                "(page IS NULL OR page > 0) AND instr(lower(evidence_text), lower(:query)) > 0 AND :result_id = :result_id",
            )
            multi_path = root / "multi-config.json"
            write(multi_path, multi_config)
            review = load(FIXTURES / "review.json")
            review["query"] = "e"
            review_path = root / "multi-review.json"
            write(review_path, review)
            failed = self.run_cli(
                "build-receipt", "--config", str(multi_path), "--database", str(database),
                "--expected-db-sha256", database_sha, "--review", str(review_path),
                "--output", str(root / "multi-receipt.json"),
            )
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn("more than the allowed 1 rows", failed.stderr)

            fixed = {
                "result_id": "'budget_result'",
                "canonical_store_digest": "'" + "1" * 64 + "'",
                "source_record_id": "'budget_source'",
                "source_revision": "'budget_revision'",
                "source_payload_sha256": "'" + "2" * 64 + "'",
                "source_object_sha256": "'" + "3" * 64 + "'",
                "source_kind": "'gaussian_associated_text'",
                "locator_kind": "'logical_chunk'",
                "page": "NULL",
                "logical_chunk": "'budget_chunk'",
                "text_quality": "'embedded_text'",
                "text_quality_notes": "NULL",
                "source_program": "NULL",
                "source_major_version": "NULL",
                "source_version": "NULL",
                "evidence_text": "'budget evidence'",
            }
            projection = ", ".join(f"{value} AS {name}" for name, value in fixed.items())
            budget_config = load(FIXTURES / "adapter.json")
            budget_config["query_sql"] = (
                "WITH RECURSIVE x(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM x WHERE n < 5000) "
                f"SELECT {projection} FROM x AS a CROSS JOIN x AS b "
                "WHERE lower(:query) = lower(:query) AND :limit > 0 ORDER BY a.n + b.n DESC"
            )
            budget_path = root / "budget-config.json"
            write(budget_path, budget_config)
            failed = self.run_cli(
                "query", "--config", str(budget_path), "--database", str(database),
                "--expected-db-sha256", database_sha, "--query", "budget", "--limit", "1",
            )
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn("deterministic 1000000-step budget", failed.stderr)

    def test_positive_locator_review_machine_path_and_long_quote_gates(self) -> None:
        review = load(FIXTURES / "review.json")
        review["whole_page_visual_review"] = {
            "status": "not_reviewed",
            "reviewer": None,
            "reviewed_at": None,
            "notes": ["Whole page has not been checked."],
        }
        with tempfile.TemporaryDirectory() as temp:
            output, failed = self.build(Path(temp), review)
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn("requires whole-page visual review", failed.stderr)
            self.assertFalse(output.exists())

        path_review = load(FIXTURES / "review.json")
        path_review["short_paraphrase"] = "Evidence copied from " + "/" + "Users/example/private/manual.pdf"
        with tempfile.TemporaryDirectory() as temp:
            output, failed = self.build(Path(temp), path_review)
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn("machine absolute path", failed.stderr)
            self.assertFalse(output.exists())

        quote_review = load(FIXTURES / "review.json")
        quote_review["statement_type"] = "short_quote"
        quote_review["short_paraphrase"] = " ".join(f"word{index}" for index in range(26))
        with tempfile.TemporaryDirectory() as temp:
            output, failed = self.build(Path(temp), quote_review)
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn("25-word limit", failed.stderr)
            self.assertFalse(output.exists())

        chinese_quote = load(FIXTURES / "review.json")
        chinese_quote["statement_type"] = "short_quote"
        chinese_quote["short_paraphrase"] = "引" * 121
        with tempfile.TemporaryDirectory() as temp:
            output, failed = self.build(Path(temp), chinese_quote)
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn("120-character limit", failed.stderr)
            self.assertFalse(output.exists())

    def test_receipt_tampering_unknown_fields_and_authorization_escalation_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output, built = self.build(Path(temp))
            self.assertEqual(built.returncode, 0, built.stderr)
            receipt = load(output)

            tampered = copy.deepcopy(receipt)
            tampered["evidence"]["short_paraphrase"] = "Changed without resealing."
            with self.assertRaisesRegex(MANUAL.ManualEvidenceError, "payload SHA-256 mismatch"):
                MANUAL.validate_receipt(tampered)

            unknown = copy.deepcopy(receipt)
            unknown["selected_method"] = "forbidden"
            unknown["payload_sha256"] = MANUAL.payload_sha(unknown)
            with self.assertRaisesRegex(MANUAL.ManualEvidenceError, "unknown fields"):
                MANUAL.validate_receipt(unknown)

            row_drift = copy.deepcopy(receipt)
            row_drift["source"]["revision"] = "different_source_revision"
            row_drift["payload_sha256"] = MANUAL.payload_sha(row_drift)
            with self.assertRaisesRegex(MANUAL.ManualEvidenceError, "retrieval row SHA-256 mismatch"):
                MANUAL.validate_receipt(row_drift)

            for field, value in (
                ("calculation_ready", True),
                ("no_submission_authorization", False),
                ("no_method_selection_authorization", False),
                ("no_input_generation_authorization", False),
            ):
                escalated = copy.deepcopy(receipt)
                escalated[field] = value
                escalated["payload_sha256"] = MANUAL.payload_sha(escalated)
                with self.subTest(field=field), self.assertRaises(MANUAL.ManualEvidenceError):
                    MANUAL.validate_receipt(escalated)


if __name__ == "__main__":
    unittest.main()
