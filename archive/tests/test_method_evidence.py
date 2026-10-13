#!/usr/bin/env python3
"""Focused offline tests for the Auto-G16 v2.5 method-evidence slice."""

from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "skills" / "auto-g16-knowledge-base" / "scripts" / "method_evidence.py"
CONTRACTS = ROOT / "contracts" / "knowledge-base"

SPEC = importlib.util.spec_from_file_location("auto_g16_method_evidence", SCRIPT)
assert SPEC and SPEC.loader
METHOD_EVIDENCE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(METHOD_EVIDENCE)


def record_ref(record_type: str, record_id: str) -> dict[str, object]:
    return {
        "record_type": record_type,
        "record_id": record_id,
        "revision_id": f"{record_id}_r001",
        "payload_sha256": "a" * 64,
    }


def access(access_class: str = "public") -> dict[str, object]:
    if access_class == "confidential_unpublished":
        return {
            "class": access_class,
            "owner_project": "synthetic_project",
            "permitted_principals": ["fixture_reviewer"],
            "export_policy": "no_export",
        }
    if access_class == "project_restricted":
        return {
            "class": access_class,
            "owner_project": "synthetic_project",
            "permitted_principals": ["fixture_reviewer"],
            "export_policy": "metadata_redacted",
        }
    return {
        "class": access_class,
        "owner_project": None,
        "permitted_principals": [],
        "export_policy": "full",
    }


def profile(*, family: str = "minimum_opt_freq", property_name: str = "stationary_point_geometry") -> dict[str, object]:
    return {
        "calculation_family": family,
        "elements": ["B", "C", "H", "N"],
        "ecp_elements": [],
        "charge": 0,
        "multiplicity": 1,
        "electronic_state_constraints": ["closed_shell_singlet_reviewed"],
        "reference_constraints": ["restricted_reference"],
        "phase": "solution",
        "solvent": {
            "status": "specified",
            "identity": "synthetic_solvent",
            "model_constraints": ["continuum_model_required"],
        },
        "target_properties": [property_name],
        "resource_constraints": {
            "max_cores": 8,
            "max_memory_gb": 12.0,
            "max_walltime_hours": 24.0,
            "notes": ["Synthetic offline resource ceiling."],
        },
    }


def common(schema: str, artifact_id: str, *, access_class: str = "public") -> dict[str, object]:
    return {
        "schema": schema,
        "artifact_id": artifact_id,
        "revision_id": f"{artifact_id}_r001",
        "created_at": "2026-07-19T12:00:00+08:00",
        "created_by": "fixture_reviewer",
        "review": {
            "status": "reviewed",
            "reviewer": "fixture_reviewer",
            "reviewed_at": "2026-07-19T12:00:00+08:00",
            "notes": ["Synthetic sanitized fixture; no live system data."],
        },
        "access": access(access_class),
        "provenance": {
            "source_kind": "manual_review",
            "importer": None,
            "source_artifacts": [],
        },
        "source_revision_refs": [record_ref("source", "synthetic_source")],
        "supersedes": [],
        "exclusions": ["No raw output, scheduler identifier, host, credential, or private source text is retained."],
        "calculation_ready": False,
        "no_submission_authorization": True,
        "no_method_selection_authorization": True,
        "no_approval_authorization": True,
        "payload_sha256": None,
    }


def context() -> dict[str, object]:
    value = common("auto-g16-method-selection-context/1", "synthetic_method_context")
    value.update(
        {
            "question": "What reviewed evidence is relevant to this synthetic minimum context?",
            "context_profile": profile(),
            "reviewed_calculation_refs": [record_ref("reaction", "synthetic_reaction")],
        }
    )
    return METHOD_EVIDENCE.finalize_artifact(value)


def benchmark(*, artifact_id: str = "synthetic_benchmark", access_class: str = "public", cost_status: str = "reported", family: str = "minimum_opt_freq") -> dict[str, object]:
    value = common("auto-g16-method-benchmark-case/1", artifact_id, access_class=access_class)
    cost = {
        "status": cost_status,
        "walltime_hours": 2.0 if cost_status != "unknown" else None,
        "core_hours": 16.0 if cost_status != "unknown" else None,
        "peak_memory_gb": 4.0 if cost_status != "unknown" else None,
        "resource_tier": "synthetic_small" if cost_status != "unknown" else None,
        "notes": ["Synthetic cost observation."] if cost_status != "unknown" else ["Cost was not available."],
    }
    value.update(
        {
            "context_profile": profile(family=family),
            "method_record_ref": record_ref("method", "synthetic_method"),
            "source_anchor_refs": [
                {"source_record": record_ref("source", "synthetic_source"), "anchor_id": "synthetic_anchor"}
            ],
            "benchmark_quality": {
                "status": "strong",
                "comparison_scope": "Synthetic same-family comparison.",
                "reference_data_quality": "Reviewed synthetic values.",
                "notes": [],
            },
            "technical_feasibility": {"status": "demonstrated", "notes": ["Synthetic completion evidence."]},
            "convergence_history": {"status": "consistent", "attempt_count": 2, "notes": ["Two sanitized observations."]},
            "cost_observation": cost,
            "observed_outcomes": ["Synthetic stationary-point observation."],
        }
    )
    return METHOD_EVIDENCE.finalize_artifact(value)


def run_observation() -> dict[str, object]:
    value = common("auto-g16-method-run-observation/1", "synthetic_run_observation")
    value.update(
        {
            "context_profile": profile(),
            "method_record_ref": record_ref("method", "synthetic_method"),
            "result_record_refs": [record_ref("result", "synthetic_result")],
            "observation_status": "completed",
            "technical_feasibility": {"status": "demonstrated", "notes": ["Sanitized technical observation."]},
            "convergence_history": {"status": "consistent", "attempt_count": 1, "notes": ["One sanitized attempt."]},
            "cost_observation": {
                "status": "observed",
                "walltime_hours": 1.5,
                "core_hours": 12.0,
                "peak_memory_gb": 3.0,
                "resource_tier": "synthetic_small",
                "notes": ["Synthetic observation only."],
            },
            "observed_outcomes": ["Completed synthetic parser fixture."],
        }
    )
    return METHOD_EVIDENCE.finalize_artifact(value)


def metadata() -> dict[str, str]:
    return {
        "artifact_id": "synthetic_method_brief",
        "revision_id": "synthetic_method_brief_r001",
        "created_at": "2026-07-19T12:30:00+08:00",
        "created_by": "fixture_reviewer",
    }


class MethodEvidenceTests(unittest.TestCase):
    maxDiff = None

    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_four_closed_hash_bound_contracts_are_present(self) -> None:
        expected = {
            "method-selection-context.schema.json": "auto-g16-method-selection-context/1",
            "method-benchmark-case.schema.json": "auto-g16-method-benchmark-case/1",
            "method-run-observation.schema.json": "auto-g16-method-run-observation/1",
            "method-evidence-brief.schema.json": "auto-g16-method-evidence-brief/1",
        }
        for filename, schema_id in expected.items():
            with self.subTest(contract=filename):
                schema = json.loads((CONTRACTS / filename).read_text(encoding="utf-8"))
                self.assertFalse(schema["additionalProperties"])
                self.assertEqual(schema["properties"]["schema"]["const"], schema_id)
                self.assertEqual(schema["properties"]["calculation_ready"]["const"], False)
                self.assertEqual(schema["properties"]["no_submission_authorization"]["const"], True)
                self.assertEqual(schema["properties"]["no_method_selection_authorization"]["const"], True)
                self.assertEqual(schema["properties"]["no_approval_authorization"]["const"], True)

    def test_builder_keeps_five_dimensions_and_never_selects_or_approves(self) -> None:
        brief = METHOD_EVIDENCE.build_brief(context(), [benchmark(), run_observation()], None, metadata())
        reordered = METHOD_EVIDENCE.build_brief(context(), [run_observation(), benchmark()], None, metadata())
        METHOD_EVIDENCE.validate_artifact(brief)
        self.assertEqual(brief["payload_sha256"], reordered["payload_sha256"])
        self.assertEqual(brief["evidence_status"], "reviewable")
        self.assertEqual(brief["method_selection"], {"status": "not_performed", "selected_method_record_ref": None})
        self.assertEqual(brief["approval"], {"status": "not_granted", "approved_protocol_ref": None})
        self.assertFalse(brief["calculation_ready"])
        self.assertTrue(brief["no_submission_authorization"])
        candidate = brief["candidate_evidence"][0]
        self.assertEqual(
            set(candidate) - {"method_record_ref"},
            {"chemical_directness", "benchmark_quality", "technical_feasibility", "convergence_history", "cost"},
        )
        serialized = json.dumps(brief, sort_keys=True)
        for forbidden in ("opaque_score", "overall_score", "success_probability", "selected_functional", "approved_route"):
            self.assertNotIn(forbidden, serialized)

    def test_unknown_cost_and_empty_evidence_fail_closed_as_insufficient(self) -> None:
        incomplete = METHOD_EVIDENCE.build_brief(context(), [benchmark(cost_status="unknown")], None, metadata())
        self.assertEqual(incomplete["evidence_status"], "insufficient")
        self.assertEqual(incomplete["candidate_evidence"][0]["cost"]["status"], "unknown")
        empty = METHOD_EVIDENCE.build_brief(context(), [], None, metadata())
        self.assertEqual(empty["evidence_status"], "insufficient")
        self.assertEqual(empty["candidate_evidence"], [])

    def test_query_filters_context_and_permissions_without_leaking_denied_identity(self) -> None:
        denied = benchmark(artifact_id="restricted_synthetic_benchmark", access_class="confidential_unpublished")
        mismatch = benchmark(artifact_id="mismatched_synthetic_benchmark", family="transition_state")
        result = METHOD_EVIDENCE.query_evidence(context(), [benchmark(), denied, mismatch], None)
        self.assertEqual(result["summary"], {"supplied": 3, "included": 1, "excluded_permission": 1, "excluded_context": 1})
        self.assertEqual(result["excluded"][0]["reasons"], ["calculation_family_mismatch"])
        self.assertNotIn("restricted_synthetic_benchmark", json.dumps(result, sort_keys=True))

    def test_derived_brief_preserves_restricted_permission_and_export_policy(self) -> None:
        principal = {
            "schema": "auto-g16-knowledge-principal/1",
            "principal_id": "fixture_reviewer",
            "group_member": True,
            "projects": ["synthetic_project"],
            "confidential_record_ids": [],
        }
        brief = METHOD_EVIDENCE.build_brief(
            context(),
            [benchmark(access_class="project_restricted")],
            principal,
            metadata(),
        )
        self.assertEqual(
            brief["access"],
            {
                "class": "project_restricted",
                "owner_project": "synthetic_project",
                "permitted_principals": ["fixture_reviewer"],
                "export_policy": "metadata_redacted",
            },
        )

    def test_tampering_unknown_authority_fields_and_fabricated_unknown_cost_are_rejected(self) -> None:
        tampered = benchmark()
        tampered["benchmark_quality"]["status"] = "weak"
        with self.assertRaisesRegex(METHOD_EVIDENCE.EvidenceError, "payload SHA-256 mismatch"):
            METHOD_EVIDENCE.validate_artifact(tampered)

        selecting = copy.deepcopy(benchmark())
        selecting["selected_method"] = "synthetic_method"
        selecting["payload_sha256"] = METHOD_EVIDENCE.payload_sha256(selecting)
        with self.assertRaisesRegex(METHOD_EVIDENCE.EvidenceError, "unknown fields"):
            METHOD_EVIDENCE.validate_artifact(selecting)

        fabricated = copy.deepcopy(benchmark(cost_status="unknown"))
        fabricated["cost_observation"]["walltime_hours"] = 1.0
        fabricated["payload_sha256"] = METHOD_EVIDENCE.payload_sha256(fabricated)
        with self.assertRaisesRegex(METHOD_EVIDENCE.EvidenceError, "cannot contain fabricated measurements"):
            METHOD_EVIDENCE.validate_artifact(fabricated)

    def test_cli_builds_exclusive_hash_bound_brief(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            context_path = root / "context.json"
            evidence_path = root / "benchmark.json"
            output = root / "brief.json"
            context_path.write_bytes(METHOD_EVIDENCE.canonical_bytes(context()))
            evidence_path.write_bytes(METHOD_EVIDENCE.canonical_bytes(benchmark()))
            args = (
                "build-brief", "--context", str(context_path), "--evidence", str(evidence_path),
                "--brief-id", "synthetic_cli_brief", "--revision-id", "synthetic_cli_brief_r001",
                "--created-at", "2026-07-19T12:30:00+08:00", "--created-by", "fixture_reviewer",
                "--output", str(output),
            )
            completed = self.run_cli(*args)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            brief = json.loads(output.read_text(encoding="utf-8"))
            METHOD_EVIDENCE.validate_artifact(brief)
            second = self.run_cli(*args)
            self.assertEqual(second.returncode, 2)
            self.assertIn("refusing to overwrite", second.stderr)


if __name__ == "__main__":
    unittest.main()
