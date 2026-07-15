#!/usr/bin/env python3
"""Focused offline tests for gaussian-reaction-mechanism-support-matrix/1."""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
TOOL = ROOT / "skills/auto-g16-reaction-workflow/scripts/mechanism_support_matrix.py"
OUTPUT_SCHEMA = ROOT / "contracts/reaction-workflow/mechanism-support-matrix.schema.json"
REVIEW_SCHEMA = ROOT / "contracts/reaction-workflow/mechanism-support-matrix-review.schema.json"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SUPPORT_TEST = load_module("matrix_support_fixture", ROOT / "tests/test_mechanism_support.py")
SCHEMA_VALIDATOR = load_module("matrix_schema_validator", ROOT / "scripts/validate_asymmetric_contract.py")


def write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


class MechanismSupportMatrixTests(unittest.TestCase):
    maxDiff = None

    def run_tool(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, str(TOOL), *args], cwd=ROOT, check=False, capture_output=True, text=True)

    def assert_success(self, result: subprocess.CompletedProcess[str]) -> None:
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def build_owner_support(self, root: Path, review_mutator=None):
        helper = SUPPORT_TEST.MechanismSupportTests("test_supported_conditional_unsupported_contradicted_and_novel_missing")
        _, path, result = helper.build_support(root, review_mutator=review_mutator)
        self.assert_success(result)
        return path, json.loads(path.read_text(encoding="utf-8"))

    def matrix_review(self, support: dict[str, object]) -> dict[str, object]:
        records = {item["support_record_id"]: item for item in support["records"]}
        rows = []
        row_ids = {}
        for summary in support["edge_channel_summary"]:
            edge_id = summary["edge_id"]
            row_id = f"row_{edge_id.removeprefix('edge_')}"
            row_ids[(edge_id, summary["stereochemical_channel"])] = row_id
            rows.append({
                "row_id": row_id, "label": f"Synthetic comparison row for {edge_id}",
                "edge_id": edge_id, "stereochemical_channel": summary["stereochemical_channel"],
                "bounded_hypothesis": "Synthetic matrix row; no real mechanism or chemical inference is represented.",
            })
        status_map = {"direct": "positive", "analogy": "positive", "contradictory": "contradictory", "missing": "no_evidence", "excluded": "rejected"}
        relationship_map = {"supports": "supports", "contradicts": "contradicts", "does_not_address": "does_not_address", "excluded": "does_not_address"}
        cells = []
        for row in rows:
            row_key = (row["edge_id"], row["stereochemical_channel"])
            for record_id in sorted(records):
                record = records[record_id]
                native = row_key == (record["target"]["edge_id"], record["target"]["stereochemical_channel"])
                if native:
                    status = status_map[record["classification"]["category"]]
                    relationship = relationship_map[record["classification"]["claim_effect"]]
                    dimensions = [
                        {"dimension": item["dimension"], "value": item["value"], "rationale": "Synthetic native-cell applicability copied from the owner-reviewed value."}
                        for item in record["applicability_dimensions"]
                    ]
                    decision = "rejected" if status == "rejected" else "retained"
                    confidence = "high" if status == "positive" and record["classification"]["category"] == "direct" else "medium"
                else:
                    status, relationship, decision, confidence = "no_evidence", "does_not_address", "retained", "unknown"
                    dimensions = [
                        {"dimension": name, "value": "unknown", "rationale": "Synthetic cross-row comparison was not established."}
                        for name in sorted({item["dimension"] for item in next(iter(records.values()))["applicability_dimensions"]})
                    ]
                cells.append({
                    "row_id": row["row_id"], "support_record_id": record_id,
                    "evidence_status": status,
                    "bounded_claim": {"relationship": relationship, "text": "Synthetic bounded comparison only; this cell does not prove a mechanism."},
                    "applicability_dimensions": dimensions,
                    "mismatches": [] if native else ["The support record belongs to another exact edge/channel."],
                    "alternative_explanations": ["A different reviewed network row may account for the synthetic evidence."],
                    "confidence": confidence, "reviewer_decision": decision,
                    "bounded_use": "hypothesis_exploration_review" if native else "matrix_comparison_only",
                    "blockers": [], "notes": ["Sanitized standard-library-only fixture."],
                })
        dispositions = []
        for row in rows:
            if row["edge_id"] == "edge_activation":
                disposition = "mandatory"
            elif row["edge_id"] == "edge_release":
                disposition = "optional"
            else:
                disposition = "contradicted"
            dispositions.append({
                "row_id": row["row_id"], "disposition": disposition,
                "rationale": "Synthetic explicit matrix disposition; owner evidence gates remain controlling.",
                "reviewed_by": "fixture_reviewer", "reviewed_at": "2026-07-16T00:00:00+00:00",
            })
        return {
            "schema": "gaussian-reaction-mechanism-support-matrix-review/1",
            "matrix_id": "synthetic_support_matrix", "study_id": support["study_id"],
            "mechanism_support_payload_sha256": support["payload_sha256"],
            "mechanism_network_payload_sha256": support["mechanism_network"]["payload_sha256"],
            "rows": rows, "cells": cells,
            "coverage": {"excluded_edge_channels": [], "matrix_complete": True, "absent_evidence_explicit": True, "rationale": "Every synthetic owner edge/channel is covered and every absent cross-cell is explicit."},
            "row_promotion_reviews": dispositions, "supersedes": None,
            "review_decision": "accepted", "reviewer": "fixture_reviewer",
            "reviewed_at": "2026-07-16T00:00:00+00:00",
            "review_notes": ["Synthetic offline matrix fixture; no publication or mechanism claim."],
        }

    def build_matrix(self, root: Path, *, owner_mutator=None, review_mutator=None, output_name="mechanism_support_matrix.json"):
        support_path, support = self.build_owner_support(root, owner_mutator)
        review = self.matrix_review(support)
        if review_mutator:
            review_mutator(review)
        review_path = root / f"review_{output_name}"
        write_json(review_path, review)
        output = root / output_name
        result = self.run_tool("build", str(support_path), "--review", str(review_path), "--output", str(output))
        return support_path, support, review_path, review, output, result

    def test_build_validate_schema_and_owner_gate_compatibility(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            support_path, support, review_path, review, output, result = self.build_matrix(root)
            self.assert_success(result)
            artifact = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(artifact["schema"], "gaussian-reaction-mechanism-support-matrix/1")
            self.assertEqual(artifact["mechanism_support"]["payload_sha256"], support["payload_sha256"])
            self.assertEqual(artifact["mechanism_network"]["payload_sha256"], support["mechanism_network"]["payload_sha256"])
            self.assertEqual(artifact["coverage"]["actual_cell_count"], len(support["records"]) * len(support["edge_channel_summary"]))
            self.assertEqual({item["edge_id"] for item in artifact["downstream_reviewable_targets"]}, {"edge_activation", "edge_release"})
            for item in artifact["downstream_reviewable_targets"]:
                self.assertTrue(item["owner_hypothesis_exploration_eligible"])
                self.assertFalse(item["mechanism_claim_validated"])
            self.assertFalse(artifact["mechanism_proven"])
            self.assertFalse(artifact["mechanism_claim_validation_present"])
            self.assertFalse(artifact["calculation_ready"])
            self.assertTrue(artifact["no_submission_authorization"])
            validation = self.run_tool("validate", str(output))
            self.assert_success(validation)
            self.assertFalse(json.loads(validation.stdout)["live_actions"])
            for schema_path, instance in ((OUTPUT_SCHEMA, artifact), (REVIEW_SCHEMA, review)):
                schema = json.loads(schema_path.read_text(encoding="utf-8"))
                SCHEMA_VALIDATOR.validate_schema_document(schema)
                SCHEMA_VALIDATOR._validate_schema_instance(instance, schema, schema)
            template = json.loads((ROOT / "tests/fixtures/reaction_workflow/mechanism_support_matrix_review.template.json").read_text(encoding="utf-8"))
            review_schema = json.loads(REVIEW_SCHEMA.read_text(encoding="utf-8"))
            SCHEMA_VALIDATOR._validate_schema_instance(template, review_schema, review_schema)
            before = support_path.read_bytes()
            self.assertEqual(before, support_path.read_bytes(), "matrix validation must not mutate support/1")

    def test_supersession_binds_exact_prior_matrix_without_rewrite(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            support_path, support, _, _, first_path, first_result = self.build_matrix(root)
            self.assert_success(first_result)
            first_bytes = first_path.read_bytes()
            first = json.loads(first_bytes)
            review = self.matrix_review(support)
            review["matrix_id"] = "synthetic_support_matrix_revision"
            review["supersedes"] = {"path": str(first_path), "payload_sha256": first["payload_sha256"]}
            review["review_notes"] = ["Synthetic immutable superseding matrix revision."]
            review_path = root / "matrix_revision_review.json"
            write_json(review_path, review)
            second_path = root / "mechanism_support_matrix_revision.json"
            result = self.run_tool("build", str(support_path), "--review", str(review_path), "--output", str(second_path))
            self.assert_success(result)
            second = json.loads(second_path.read_text(encoding="utf-8"))
            self.assertEqual(second["supersedes"]["payload_sha256"], first["payload_sha256"])
            self.assertEqual(first_path.read_bytes(), first_bytes)
            self.assert_success(self.run_tool("validate", str(second_path)))

    def test_output_is_deterministic_and_rejects_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            _, _, _, _, output, result = self.build_matrix(root)
            self.assert_success(result)
            first = output.read_bytes()
            validation = self.run_tool("validate", str(output))
            self.assert_success(validation)
            self.assertEqual(first, output.read_bytes())
            overwrite = self.run_tool("build", str(root / "mechanism_support.json"), "--review", str(root / "review_mechanism_support_matrix.json"), "--output", str(output))
            self.assertNotEqual(overwrite.returncode, 0)
            self.assertIn("overwrite", overwrite.stderr)

    def test_unknown_duplicate_nonfinite_and_incomplete_matrix_fail_closed(self) -> None:
        mutations = (
            (lambda review: review.update({"unknown_field": True}), "unknown or missing fields"),
            (lambda review: review["cells"].pop(), "exactly one cell"),
            (lambda review: review["cells"][0]["applicability_dimensions"].pop(), "all nine dimensions"),
            (lambda review: review["cells"][0].update({"confidence": "certain"}), "invalid review enum"),
        )
        for mutation, expected in mutations:
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as temporary:
                _, _, _, _, _, result = self.build_matrix(Path(temporary).resolve(), review_mutator=mutation)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected, result.stderr)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            support_path, support = self.build_owner_support(root)
            review = self.matrix_review(support)
            review_path = root / "duplicate.json"
            document = json.dumps(review, allow_nan=False)
            review_path.write_text(document.replace('{"schema":', '{"schema":"duplicate","schema":', 1), encoding="utf-8")
            result = self.run_tool("build", str(support_path), "--review", str(review_path), "--output", str(root / "duplicate-output.json"))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("duplicate", result.stderr)
            review_path.write_text(document.replace('"confidence": "high"', '"confidence": NaN', 1), encoding="utf-8")
            result = self.run_tool("build", str(support_path), "--review", str(review_path), "--output", str(root / "nan-output.json"))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("non-standard JSON", result.stderr)

    def test_native_owner_facts_and_exploration_gate_cannot_be_weakened(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            def conflict(review):
                cell = next(item for item in review["cells"] if item["row_id"] == "row_activation" and item["support_record_id"] == "support_direct")
                cell["evidence_status"] = "no_evidence"
            _, _, _, _, _, result = self.build_matrix(Path(temporary).resolve(), review_mutator=conflict)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("owner evidence classification", result.stderr)

        with tempfile.TemporaryDirectory() as temporary:
            def block_release(review):
                record = next(item for item in review["records"] if item["support_record_id"] == "support_analogy")
                record["exploration_decision"]["status"] = "blocked"
                record["exploration_decision"]["resolved_blockers"] = []
                record["exploration_decision"]["unresolved_blockers"] = ["Synthetic owner gate remains blocked."]
            _, _, _, _, _, result = self.build_matrix(Path(temporary).resolve(), owner_mutator=block_release)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("cannot bypass the mechanism-support exploration gate", result.stderr)

    def test_rehashed_forgery_source_drift_and_symlinks_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            support_path, _, review_path, _, output, result = self.build_matrix(root)
            self.assert_success(result)
            artifact = json.loads(output.read_text(encoding="utf-8"))
            artifact["downstream_reviewable_targets"] = []
            SUPPORT_TEST.rehash(artifact)
            output.write_text(json.dumps(artifact, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
            forged = self.run_tool("validate", str(output))
            self.assertNotEqual(forged.returncode, 0)
            self.assertIn("independent reconstruction", forged.stderr)
            review_path.write_text(review_path.read_text(encoding="utf-8") + " ", encoding="utf-8")
            drifted = self.run_tool("validate", str(output))
            self.assertNotEqual(drifted.returncode, 0)

            linked_support = root / "linked-support.json"
            try:
                linked_support.symlink_to(support_path)
            except OSError:
                return
            linked = self.run_tool("build", str(linked_support), "--review", str(review_path), "--output", str(root / "linked-output.json"))
            self.assertNotEqual(linked.returncode, 0)
            self.assertIn("symlink", linked.stderr)
            real_dir = root / "real-dir"
            real_dir.mkdir()
            linked_dir = root / "linked-dir"
            linked_dir.symlink_to(real_dir, target_is_directory=True)
            bad_output = self.run_tool("build", str(support_path), "--review", str(review_path), "--output", str(linked_dir / "matrix.json"))
            self.assertNotEqual(bad_output.returncode, 0)
            self.assertIn("symlink", bad_output.stderr)

    def test_schema_module_and_no_live_namespaces_do_not_collide(self) -> None:
        schema_ids = {}
        discriminators = {}
        for path in sorted((ROOT / "contracts").rglob("*.schema.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertNotIn(data["$id"], schema_ids, f"duplicate schema $id in {path} and {schema_ids.get(data['$id'])}")
            schema_ids[data["$id"]] = path
            discriminator = data.get("properties", {}).get("schema", {}).get("const")
            if discriminator:
                self.assertNotIn(discriminator, discriminators, f"duplicate schema discriminator in {path} and {discriminators.get(discriminator)}")
                discriminators[discriminator] = path
        self.assertEqual(discriminators["gaussian-reaction-mechanism-support/1"].name, "mechanism-support.schema.json")
        self.assertEqual(discriminators["gaussian-reaction-mechanism-support-matrix/1"].name, "mechanism-support-matrix.schema.json")
        self.assertTrue((TOOL.parent / "mechanism_support.py").is_file())
        self.assertNotEqual(TOOL.name, "mechanism_support.py")
        source = TOOL.read_text(encoding="utf-8").lower()
        for forbidden in ("import subprocess", "paramiko", "qsub", "gaussian_auto", "ssh "):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
