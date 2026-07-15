#!/usr/bin/env python3
"""Focused offline tests for the mechanism-support matrix sidecar."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
SUPPORT_TOOL = ROOT / "skills" / "auto-g16-reaction-workflow" / "scripts" / "mechanism_support.py"
SUPPORT_FIXTURE = FIXTURES / "mechanism_support" / "mechanism_support_review.template.json"
SNAPSHOT_FIXTURE = FIXTURES / "knowledge_base" / "records" / "knowledge-snapshot.json"
SCHEMA_PATH = ROOT / "contracts" / "reaction-workflow" / "mechanism-support.schema.json"
if str(SUPPORT_TOOL.parent) not in sys.path:
    sys.path.insert(0, str(SUPPORT_TOOL.parent))


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SUPPORT = load_module("mechanism_support_tests", SUPPORT_TOOL)
NETWORK_TESTS = load_module("mechanism_network_fixture_helpers", ROOT / "tests" / "test_mechanism_network.py")
SCHEMA_VALIDATOR = load_module("mechanism_support_schema_validator", ROOT / "scripts" / "validate_asymmetric_contract.py")


def write_json(path: Path, data: object, *, allow_nan: bool = False) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=allow_nan) + "\n",
        encoding="utf-8",
    )


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def literature_hash(data: dict[str, object], field: str) -> str:
    payload = copy.deepcopy(data)
    payload.pop(field, None)
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def legacy_ref(path: Path, data: dict[str, object]) -> dict[str, object]:
    return {
        "path": str(path),
        "sha256": file_sha256(path),
        "schema": data["schema"],
        "payload_sha256": data["payload_sha256"],
    }


class MechanismSupportTests(unittest.TestCase):
    maxDiff = None

    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SUPPORT_TOOL), *args],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

    def assert_success(self, result: subprocess.CompletedProcess[str]) -> None:
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def build_network(self, root: Path) -> tuple[Path, dict[str, object]]:
        helper = NETWORK_TESTS.MechanismNetworkTests(methodName="test_help_is_offline_and_exposed")
        network_path, _, result = helper.build_network(root)
        self.assertEqual(result.returncode, 0, result.stderr)
        return network_path, json.loads(network_path.read_text(encoding="utf-8"))

    def build_snapshot(self, root: Path, network: dict[str, object]) -> tuple[Path, dict[str, object]]:
        intake_path = Path(network["intake"]["path"])
        intake = json.loads(intake_path.read_text(encoding="utf-8"))
        snapshot = json.loads(SNAPSHOT_FIXTURE.read_text(encoding="utf-8"))
        snapshot["study_id"] = network["study_id"]
        snapshot["parent_reaction_intake"] = {
            "path": str(intake_path),
            "sha256": file_sha256(intake_path),
            "size_bytes": intake_path.stat().st_size,
            "schema": intake["schema"],
            "payload_sha256": intake["payload_sha256"],
        }
        snapshot["payload_sha256"] = SUPPORT.kb.payload_sha256(snapshot)
        SUPPORT.kb.validate_record(snapshot)
        path = root / "knowledge_snapshot.json"
        write_json(path, snapshot)
        return path, snapshot

    def build_evidence(
        self,
        root: Path,
        network: dict[str, object],
        snapshot_path: Path,
        snapshot: dict[str, object],
    ) -> tuple[Path, dict[str, object], Path, dict[str, object]]:
        intake_path = Path(network["intake"]["path"])
        registry_path = Path(network["species_registry"]["path"])
        condition_path = Path(network["condition_model"]["path"])
        intake = json.loads(intake_path.read_text(encoding="utf-8"))
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        condition = json.loads(condition_path.read_text(encoding="utf-8"))
        upstream_artifacts = {
            "reaction_intake": legacy_ref(intake_path, intake),
            "species_registry": legacy_ref(registry_path, registry),
            "condition_model": legacy_ref(condition_path, condition),
            "knowledge_snapshot": legacy_ref(snapshot_path, snapshot),
        }

        search_plan_path = root / "synthetic_search_plan.json"
        search_plan = {
            "schema": "gaussian-reaction-literature-query/1",
            "request_id": "synthetic-support-request",
            "calculation_ready": False,
            "no_submission_authorization": True,
            "search_plan_payload_sha256": None,
        }
        search_plan["search_plan_payload_sha256"] = literature_hash(
            search_plan, "search_plan_payload_sha256"
        )
        write_json(search_plan_path, search_plan)
        retrieval_path = root / "synthetic_retrieval.json"
        retrieval = {
            "schema": "gaussian-reaction-literature-retrieval/1",
            "request_id": "synthetic-support-request",
            "mode": "offline_fixture_replay",
            "calculation_ready": False,
            "no_submission_authorization": True,
            "retrieval_payload_sha256": None,
        }
        retrieval["retrieval_payload_sha256"] = literature_hash(
            retrieval, "retrieval_payload_sha256"
        )
        write_json(retrieval_path, retrieval)

        score_categories = {
            "catalyst_terms": [],
            "evidence_abstract": [],
            "evidence_title": ["mechanism"],
            "exact_phrases": [],
            "exclusions": [],
            "mechanism_terms": [],
            "substrate_terms": [],
            "transformation_terms": [],
        }
        ledger = {
            "schema": "gaussian-reaction-literature-candidate-ledger/1",
            "request_id": "synthetic-support-request",
            "created_at": "2026-07-16T00:00:00Z",
            "search_plan_artifact": {
                "path": str(search_plan_path),
                "sha256": file_sha256(search_plan_path),
            },
            "retrieval_artifact": {
                "path": str(retrieval_path),
                "sha256": file_sha256(retrieval_path),
            },
            "target_evidence": ["proposed_mechanism", "active_catalyst_state", "computational_protocol"],
            "upstream_artifacts": upstream_artifacts,
            "w2_binding_status": "complete_for_search_scope_review",
            "promotion_blockers": [],
            "counts": {
                "normalized_raw_records": 1,
                "unique_candidates": 1,
                "candidates_retained": 1,
            },
            "ranking_policy": {
                "type": "transparent_lexical_screening_only",
                "citation_count_used_in_score": False,
                "scientific_acceptance_performed": False,
            },
            "candidates": [{
                "candidate_id": "lit-synth-001",
                "deduplication_key": "doi:10.5555/auto.g16.synthetic",
                "doi": "10.5555/auto.g16.synthetic",
                "title": "Synthetic mechanism-support contract source",
                "authors": ["Synthetic Reviewer"],
                "year": 2026,
                "venue": "Synthetic Contract Journal",
                "url": "https://local.invalid/synthetic-source",
                "publication_type": "journal-article",
                "cited_by_count": 0,
                "record_status_signals": {
                    "crossref_relation_present": False,
                    "crossref_update_to_present": False,
                    "openalex_is_retracted": None,
                },
                "metadata_abstract_available": False,
                "discovery_observations": [{
                    "source": "crossref",
                    "query_id": "q001",
                    "lane": "exact_system",
                    "raw_sha256": "0" * 64,
                }],
                "lexical_score": 1,
                "score_breakdown": {
                    "matched_terms": score_categories,
                    "points": {
                        key: (1 if key == "evidence_title" else 0)
                        for key in score_categories
                    },
                },
                "screening_tier": "high_priority_screen",
                "screening_status": "metadata_only_unverified",
                "directness": "not_reviewed",
            }],
            "limitations": [
                "Sanitized synthetic metadata only; primary-source review remains separately recorded."
            ],
            "calculation_ready": False,
            "promotable_to_mechanism_support": False,
            "promotable_to_ts_precedent_map": False,
            "no_submission_authorization": True,
            "candidate_ledger_payload_sha256": None,
        }
        ledger["candidate_ledger_payload_sha256"] = literature_hash(ledger, "candidate_ledger_payload_sha256")
        ledger_path = root / "candidate_ledger.json"
        write_json(ledger_path, ledger)

        dimensions = {dimension: "exact" for dimension in SUPPORT.APPLICABILITY_DIMENSIONS}
        review = {
            "candidate_id": "lit-synth-001",
            "bibliography": {
                "doi": "10.5555/auto.g16.synthetic",
                "title": "Synthetic mechanism-support contract source",
                "authors": ["Synthetic Reviewer"],
                "year": 2026,
                "venue": "Synthetic Contract Journal",
                "url": "https://local.invalid/synthetic-source",
                "publication_type": "journal-article",
            },
            "discovery": {"lexical_score": 1, "screening_tier": "high_priority_screen", "metadata_only": True},
            "source_checks": {
                "doi_or_publisher_record_checked": True,
                "primary_article_checked": True,
                "supporting_information_checked": False,
                "correction_or_retraction_checked": True,
                "access_notes": ["Synthetic source; no restricted content."],
            },
            "directness_dimensions": dimensions,
            "evidence": {
                "proposed_mechanism": {
                    "status": "source_reports",
                    "source_locations": [{
                        "source_type": "primary_article",
                        "locator": "synthetic section 1",
                        "url_or_doi": "10.5555/auto.g16.synthetic",
                        "checked_at": "2026-07-16T00:00:00Z",
                    }],
                    "paraphrase": "The synthetic source reports a pathway used only to test the support contract.",
                },
                "active_catalyst_state": {"status": "not_found", "source_locations": [], "paraphrase": None},
                "computational_protocol": {"status": "source_ambiguous", "source_locations": [], "paraphrase": None},
            },
            "reported_protocol": {
                "status": "not_reviewed_not_approved_protocol",
                "optimization_frequency": None,
                "single_point": None,
                "solvation": None,
                "dispersion": None,
                "temperature_k": None,
                "standard_state": None,
                "low_frequency_treatment": None,
                "program_version": None,
            },
            "reported_ts_path": {
                "ts_labels": [],
                "charge_multiplicity": None,
                "model_truncations": None,
                "imaginary_frequencies_cm1": [],
                "normal_mode_interpretation": None,
                "irc_directions_reported": [],
                "identified_endpoints": [],
                "coordinates_available": None,
            },
            "exact_quotes": [],
            "reviewer_decision": {
                "status": "source_reports_direct_precedent",
                "bounded_use": "mechanism_support",
                "rationale": "Synthetic directness is accepted only for contract validation.",
                "reviewed_at": "2026-07-16T00:00:00Z",
            },
        }
        evidence = {
            "schema": "gaussian-reaction-literature-evidence/1",
            "request_id": ledger["request_id"],
            "created_at": "2026-07-16T00:00:00Z",
            "record_status": "validated_review_record",
            "candidate_ledger_artifact": {"path": str(ledger_path), "sha256": file_sha256(ledger_path)},
            "upstream_artifacts": copy.deepcopy(upstream_artifacts),
            "w2_binding_status": "complete_for_search_scope_review",
            "promotion_blockers": [],
            "allowed_evidence_statuses": ["not_reviewed", "not_found", "source_ambiguous", "source_reports"],
            "allowed_decisions": ["pending", "source_checked_background", "source_reports_analogy", "source_reports_direct_precedent", "exclude"],
            "allowed_applicability_values": ["exact", "close", "remote", "contradictory", "unknown", "not_applicable"],
            "allowed_bounded_uses": [
                "discovery_only",
                "mechanism_support",
                "ts_topology_support",
                "geometry_seed_support",
                "protocol_candidate_support",
                "not_applicable_to_target",
            ],
            "reviews": [review],
            "calculation_ready": False,
            "promotable_to_mechanism_support": False,
            "promotable_to_ts_precedent_map": False,
            "no_submission_authorization": True,
            "evidence_review_payload_sha256": None,
            "validated_at": "2026-07-16T00:00:00Z",
        }
        evidence["evidence_review_payload_sha256"] = literature_hash(evidence, "evidence_review_payload_sha256")
        evidence_path = root / "literature_evidence.json"
        write_json(evidence_path, evidence)
        return evidence_path, evidence, ledger_path, ledger

    def build_review(
        self,
        root: Path,
        network: dict[str, object],
        snapshot: dict[str, object],
        evidence: dict[str, object],
        *,
        name: str = "mechanism_support_review.json",
    ) -> tuple[Path, dict[str, object]]:
        review = json.loads(SUPPORT_FIXTURE.read_text(encoding="utf-8"))
        review.update({
            "mechanism_network_payload_sha256": network["payload_sha256"],
            "intake_payload_sha256": json.loads(Path(network["intake"]["path"]).read_text(encoding="utf-8"))["payload_sha256"],
            "species_registry_payload_sha256": json.loads(Path(network["species_registry"]["path"]).read_text(encoding="utf-8"))["payload_sha256"],
            "condition_model_payload_sha256": json.loads(Path(network["condition_model"]["path"]).read_text(encoding="utf-8"))["payload_sha256"],
            "knowledge_snapshot_payload_sha256": snapshot["payload_sha256"],
            "literature_evidence_payload_sha256": evidence["evidence_review_payload_sha256"],
        })
        path = root / name
        write_json(path, review)
        return path, review

    def chain(self, root: Path) -> dict[str, object]:
        network_path, network = self.build_network(root)
        snapshot_path, snapshot = self.build_snapshot(root, network)
        evidence_path, evidence, ledger_path, ledger = self.build_evidence(root, network, snapshot_path, snapshot)
        review_path, review = self.build_review(root, network, snapshot, evidence)
        return {
            "network_path": network_path,
            "network": network,
            "snapshot_path": snapshot_path,
            "snapshot": snapshot,
            "evidence_path": evidence_path,
            "evidence": evidence,
            "ledger_path": ledger_path,
            "ledger": ledger,
            "review_path": review_path,
            "review": review,
        }

    def build_support(self, context: dict[str, object], review_path: Path, output: Path) -> subprocess.CompletedProcess[str]:
        return self.run_cli(
            "build",
            str(context["network_path"]),
            str(context["evidence_path"]),
            str(context["snapshot_path"]),
            "--review",
            str(review_path),
            "--output",
            str(output),
        )

    @staticmethod
    def cell(review: dict[str, object], column_id: str) -> dict[str, object]:
        return next(item for item in review["cells"] if item["column_id"] == column_id)

    def write_review_variant(self, root: Path, review: dict[str, object], name: str) -> Path:
        path = root / name
        write_json(path, review)
        return path

    def refresh_evidence_and_review_binding(self, context: dict[str, object]) -> None:
        evidence = context["evidence"]
        evidence_path = context["evidence_path"]
        ledger_path = context["ledger_path"]
        review = context["review"]
        review_path = context["review_path"]
        evidence["candidate_ledger_artifact"]["sha256"] = file_sha256(ledger_path)
        evidence["evidence_review_payload_sha256"] = literature_hash(
            evidence, "evidence_review_payload_sha256"
        )
        write_json(evidence_path, evidence)
        review["literature_evidence_payload_sha256"] = evidence[
            "evidence_review_payload_sha256"
        ]
        write_json(review_path, review)

    def refresh_literature_chain(self, context: dict[str, object]) -> None:
        ledger = context["ledger"]
        ledger_path = context["ledger_path"]
        ledger["candidate_ledger_payload_sha256"] = literature_hash(
            ledger, "candidate_ledger_payload_sha256"
        )
        write_json(ledger_path, ledger)
        self.refresh_evidence_and_review_binding(context)

    def test_complete_fixture_builds_deterministically_and_matches_closed_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            context = self.chain(root)
            output = root / "support.json"
            built = self.build_support(context, context["review_path"], output)
            self.assert_success(built)
            artifact = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(artifact["schema"], "gaussian-reaction-mechanism-support/1")
            self.assertEqual(artifact["claim_ceiling"], "bounded_hypothesis_space_not_mechanism_proof")
            self.assertFalse(artifact["mechanism_proven"])
            self.assertFalse(artifact["calculation_ready"])
            self.assertTrue(artifact["no_submission_authorization"])
            self.assertEqual(artifact["downstream_reviewable_edge_ids"], ["edge_activation", "edge_direct", "edge_release"])
            self.assertEqual({cell["evidence_status"] for cell in artifact["matrix"]["cells"]}, {"positive", "negative", "incomplete"})
            values = {
                dimension["value"]
                for cell in artifact["matrix"]["cells"]
                for dimension in cell["applicability"].values()
            }
            self.assertTrue({"exact", "close", "remote", "contradictory"} <= values)
            self.assertEqual(artifact["coverage"]["actual_cell_count"], artifact["coverage"]["expected_cell_count"])
            for key in ("mechanism_network", "reaction_intake", "species_registry", "condition_model", "knowledge_snapshot", "literature_evidence", "candidate_ledger", "review_source"):
                self.assertEqual(set(artifact[key]), {"path", "sha256", "size_bytes", "schema", "payload_sha256"})
            checked = self.run_cli("validate", str(output))
            self.assert_success(checked)
            self.assertFalse(json.loads(checked.stdout)["live_actions"])

            schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
            SCHEMA_VALIDATOR.validate_schema_document(schema)
            SCHEMA_VALIDATOR._validate_schema_instance(artifact, schema, schema)

            second = root / "support_second.json"
            self.assert_success(self.build_support(context, context["review_path"], second))
            self.assertEqual(output.read_bytes(), second.read_bytes())
            overwrite = self.build_support(context, context["review_path"], output)
            self.assertEqual(overwrite.returncode, 2)
            self.assertIn("refusing to overwrite", overwrite.stderr)

    def test_all_cell_states_and_row_dispositions_remain_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            context = self.chain(root)
            base = context["review"]

            optional = copy.deepcopy(base)
            missing = self.cell(optional, "column_missing_claim")
            missing.update({"evidence_status": "no_evidence", "reviewer_decision": "record_no_evidence", "confidence": "unknown", "blockers": []})
            optional["row_promotion_reviews"][0]["disposition"] = "optional"
            optional_path = self.write_review_variant(root, optional, "optional_review.json")
            optional_output = root / "optional_support.json"
            self.assert_success(self.build_support(context, optional_path, optional_output))
            self.assertEqual(json.loads(optional_output.read_text())["row_dispositions"][0]["disposition"], "optional")

            inaccessible = copy.deepcopy(base)
            ambiguous = self.cell(inaccessible, "column_ambiguous_claim")
            ambiguous.update({
                "evidence_status": "inaccessible",
                "reviewer_decision": "retain_inaccessible",
                "blockers": [{"blocker_id": "source_access_incomplete", "code": "search_access_incomplete", "rationale": "Synthetic access blocker."}],
            })
            inaccessible_path = self.write_review_variant(root, inaccessible, "inaccessible_review.json")
            inaccessible_output = root / "inaccessible_support.json"
            self.assert_success(self.build_support(context, inaccessible_path, inaccessible_output))

            rejected = copy.deepcopy(base)
            ambiguous = self.cell(rejected, "column_ambiguous_claim")
            ambiguous.update({
                "evidence_status": "rejected",
                "reviewer_decision": "reject",
                "blockers": [{"blocker_id": "remote_analogy_rejected", "code": "analogy_too_remote", "rationale": "Synthetic rejection."}],
            })
            rejected_path = self.write_review_variant(root, rejected, "rejected_review.json")
            rejected_output = root / "rejected_support.json"
            self.assert_success(self.build_support(context, rejected_path, rejected_output))

            contradicted = copy.deepcopy(base)
            primary = self.cell(contradicted, "column_primary_claim")
            primary["evidence_status"] = "contradictory"
            primary["bounded_claim"]["relationship"] = "contradicts"
            primary["reviewer_decision"] = "include_contradiction"
            primary["blockers"] = [{"blocker_id": "direct_contradiction", "code": "contradictory_evidence", "rationale": "Synthetic contradiction."}]
            contradicted["row_promotion_reviews"][0]["disposition"] = "contradicted"
            contradicted_path = self.write_review_variant(root, contradicted, "contradicted_review.json")
            contradicted_output = root / "contradicted_support.json"
            self.assert_success(self.build_support(context, contradicted_path, contradicted_output))
            contradicted_artifact = json.loads(contradicted_output.read_text())
            self.assertEqual(contradicted_artifact["row_dispositions"][0]["disposition"], "contradicted")
            self.assertEqual(contradicted_artifact["downstream_reviewable_edge_ids"], [])

            unresolved = copy.deepcopy(base)
            primary = self.cell(unresolved, "column_primary_claim")
            primary.update({
                "evidence_status": "no_evidence",
                "bounded_claim": {"relationship": "unknown", "text": "No evidence is assigned to this row."},
                "directness": "unknown",
                "evidence_basis": "unknown",
                "confidence": "unknown",
                "reviewer_decision": "record_no_evidence",
                "bounded_use": "discovery_only",
                "blockers": [],
            })
            for dimension in primary["applicability"].values():
                dimension.update({"value": "unknown", "source_anchor_ids": []})
            unresolved["row_promotion_reviews"][0]["disposition"] = "unresolved"
            unresolved_path = self.write_review_variant(root, unresolved, "unresolved_review.json")
            unresolved_output = root / "unresolved_support.json"
            self.assert_success(self.build_support(context, unresolved_path, unresolved_output))
            statuses = {
                "positive", "negative", "contradictory", "inaccessible",
                "incomplete", "rejected", "no_evidence",
            }
            observed = {cell["evidence_status"] for path in (optional_output, inaccessible_output, rejected_output, contradicted_output, unresolved_output) for cell in json.loads(path.read_text())["matrix"]["cells"]}
            self.assertEqual(observed, statuses)

    def test_incomplete_coverage_and_invalid_state_edge_claim_anchor_refs_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            context = self.chain(root)
            cases = []
            missing_cell = copy.deepcopy(context["review"])
            missing_cell["cells"].pop()
            cases.append(("missing_cell", missing_cell, "every row/evidence-column intersection"))
            bad_state = copy.deepcopy(context["review"])
            bad_state["rows"][0]["state_ids"].append("state_unknown")
            cases.append(("bad_state", bad_state, "unknown mechanism-network state"))
            bad_edge = copy.deepcopy(context["review"])
            bad_edge["rows"][0]["edge_ids"].append("edge_unknown")
            cases.append(("bad_edge", bad_edge, "unknown mechanism-network edge"))
            bad_claim = copy.deepcopy(context["review"])
            bad_claim["evidence_columns"][0]["evidence_category"] = "normal_mode"
            cases.append(("bad_claim", bad_claim, "unknown finalized literature claim"))
            bad_anchor = copy.deepcopy(context["review"])
            bad_anchor["evidence_columns"][0]["source_anchors"][0]["source_location_index"] = 1
            cases.append(("bad_anchor", bad_anchor, "source_location_index is invalid"))
            omitted_claim = copy.deepcopy(context["review"])
            omitted_claim["evidence_columns"].pop()
            omitted_claim["cells"] = [cell for cell in omitted_claim["cells"] if cell["column_id"] != "column_ambiguous_claim"]
            cases.append(("omitted_claim", omitted_claim, "every finalized literature candidate/claim"))
            for name, review, expected in cases:
                with self.subTest(case=name):
                    path = self.write_review_variant(root, review, f"{name}.json")
                    result = self.build_support(context, path, root / f"{name}_output.json")
                    self.assertEqual(result.returncode, 2)
                    self.assertIn(expected, result.stderr)

    def test_omitted_network_target_requires_an_explicit_exclusion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            context = self.chain(root)
            cases = []
            missing_state = copy.deepcopy(context["review"])
            missing_state["rows"][0]["state_ids"].pop()
            cases.append(("missing_state_target", missing_state, "every mechanism-network state"))
            missing_edge = copy.deepcopy(context["review"])
            missing_edge["rows"][0]["edge_ids"].pop()
            cases.append(("missing_edge_target", missing_edge, "every mechanism-network edge"))
            for name, review, expected in cases:
                with self.subTest(case=name):
                    path = self.write_review_variant(root, review, f"{name}.json")
                    result = self.build_support(context, path, root / f"{name}_output.json")
                    self.assertEqual(result.returncode, 2)
                    self.assertIn(expected, result.stderr)

    def test_ledger_and_evidence_w1_bindings_and_blockers_cannot_diverge(self) -> None:
        cases = ("upstream_mismatch", "ledger_promotion_blocker")
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                context = self.chain(root)
                ledger = context["ledger"]
                if case == "upstream_mismatch":
                    ledger["upstream_artifacts"]["knowledge_snapshot"]["payload_sha256"] = "f" * 64
                else:
                    ledger["w2_binding_status"] = "blocked_missing_upstream_bindings"
                    ledger["promotion_blockers"] = [
                        "missing_upstream_binding:knowledge_snapshot"
                    ]
                self.refresh_literature_chain(context)
                result = self.build_support(
                    context, context["review_path"], root / f"{case}_output.json"
                )
                self.assertEqual(result.returncode, 2)

    def test_invalid_literature_source_type_cannot_be_promoted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            context = self.chain(root)
            claim = context["evidence"]["reviews"][0]["evidence"]["proposed_mechanism"]
            claim["source_locations"][0]["source_type"] = "metadata_snippet"
            self.refresh_evidence_and_review_binding(context)
            result = self.build_support(
                context, context["review_path"], root / "invalid_source_type_output.json"
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("source type", result.stderr.lower())

    def test_contradiction_requires_reviewed_directness_and_evidence_basis(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            context = self.chain(root)
            review = copy.deepcopy(context["review"])
            primary = self.cell(review, "column_primary_claim")
            primary.update({
                "evidence_status": "contradictory",
                "bounded_claim": {
                    "relationship": "contradicts",
                    "text": "The source is asserted to contradict the row without a classified basis.",
                },
                "directness": "unknown",
                "evidence_basis": "not_applicable",
                "reviewer_decision": "include_contradiction",
                "blockers": [{
                    "blocker_id": "unclassified_contradiction",
                    "code": "contradictory_evidence",
                    "rationale": "A contradiction cannot be promoted without its directness and evidence basis.",
                }],
            })
            review["row_promotion_reviews"][0]["disposition"] = "contradicted"
            review_path = self.write_review_variant(
                root, review, "unclassified_contradiction_review.json"
            )
            result = self.build_support(
                context, review_path, root / "unclassified_contradiction_output.json"
            )
            self.assertEqual(result.returncode, 2)

    def test_nonpromoted_cells_cannot_claim_future_ts_or_protocol_uses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            context = self.chain(root)
            cases = (
                ("column_missing_claim", "geometry_seed_support"),
                ("column_ambiguous_claim", "protocol_candidate_support"),
            )
            for column_id, forbidden_use in cases:
                with self.subTest(bounded_use=forbidden_use):
                    review = copy.deepcopy(context["review"])
                    column = next(
                        item for item in review["evidence_columns"]
                        if item["column_id"] == column_id
                    )
                    column["bounded_use"] = forbidden_use
                    self.cell(review, column_id)["bounded_use"] = forbidden_use
                    review_path = self.write_review_variant(
                        root, review, f"{forbidden_use}_review.json"
                    )
                    result = self.build_support(
                        context, review_path, root / f"{forbidden_use}_output.json"
                    )
                    self.assertEqual(result.returncode, 2)

    def test_blocked_review_emits_no_downstream_reviewable_edges(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            context = self.chain(root)
            review = copy.deepcopy(context["review"])
            review["review_decision"] = "blocked"
            review["review_notes"].append(
                "The overall promotion review is blocked despite retained row-level analysis."
            )
            review_path = self.write_review_variant(root, review, "blocked_review.json")
            output = root / "blocked_support.json"
            self.assert_success(self.build_support(context, review_path, output))
            artifact = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(artifact["gate_status"], "blocked")
            self.assertEqual(artifact["downstream_reviewable_edge_ids"], [])

    def test_duplicate_nonfinite_unknown_and_promotion_gate_inputs_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            context = self.chain(root)
            duplicate_id = copy.deepcopy(context["review"])
            duplicate_id["evidence_columns"][1]["claim_id"] = duplicate_id["evidence_columns"][0]["claim_id"]
            duplicate_path = self.write_review_variant(root, duplicate_id, "duplicate_id.json")
            result = self.build_support(context, duplicate_path, root / "duplicate_id_output.json")
            self.assertEqual(result.returncode, 2)
            self.assertIn("duplicate claim_id", result.stderr)

            unknown = copy.deepcopy(context["review"])
            unknown["gaussian_route"] = "forbidden"
            unknown_path = self.write_review_variant(root, unknown, "unknown.json")
            result = self.build_support(context, unknown_path, root / "unknown_output.json")
            self.assertEqual(result.returncode, 2)
            self.assertIn("unknown fields", result.stderr)

            nonfinite = copy.deepcopy(context["review"])
            nonfinite["cells"][0]["confidence_number"] = float("nan")
            nonfinite_path = root / "nonfinite.json"
            write_json(nonfinite_path, nonfinite, allow_nan=True)
            result = self.build_support(context, nonfinite_path, root / "nonfinite_output.json")
            self.assertEqual(result.returncode, 2)
            self.assertIn("non-standard JSON numeric constant", result.stderr)

            duplicate_key_path = root / "duplicate_key.json"
            original = context["review_path"].read_text(encoding="utf-8")
            duplicate_key_path.write_text(original.replace('{\n  "cells"', '{\n  "schema": "gaussian-reaction-mechanism-support-review/1",\n  "cells"', 1), encoding="utf-8")
            result = self.build_support(context, duplicate_key_path, root / "duplicate_key_output.json")
            self.assertEqual(result.returncode, 2)
            self.assertIn("duplicate JSON object key", result.stderr)

            promotion = copy.deepcopy(context["review"])
            column = next(item for item in promotion["evidence_columns"] if item["column_id"] == "column_primary_claim")
            column.update({"promotion_decision": "retained_without_promotion", "bounded_use": "discovery_only"})
            promotion_path = self.write_review_variant(root, promotion, "promotion_gate.json")
            result = self.build_support(context, promotion_path, root / "promotion_gate_output.json")
            self.assertEqual(result.returncode, 2)
            self.assertIn("lacks an accepted source-reported promotion", result.stderr)

    def test_hash_size_drift_forged_payload_and_unstable_order_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            context = self.chain(root)
            output = root / "support.json"
            self.assert_success(self.build_support(context, context["review_path"], output))
            context["evidence_path"].write_bytes(context["evidence_path"].read_bytes() + b"\n")
            checked = self.run_cli("validate", str(output))
            self.assertEqual(checked.returncode, 2)
            self.assertIn("file SHA-256 mismatch", checked.stderr)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            context = self.chain(root)
            output = root / "support.json"
            self.assert_success(self.build_support(context, context["review_path"], output))
            artifact = json.loads(output.read_text(encoding="utf-8"))
            artifact["downstream_reviewable_edge_ids"] = []
            SUPPORT.rw.finalize_artifact(artifact)
            forged = root / "forged.json"
            write_json(forged, artifact)
            checked = self.run_cli("validate", str(forged))
            self.assertEqual(checked.returncode, 2)
            self.assertIn("independent reconstruction", checked.stderr)

            reordered = json.loads(output.read_text(encoding="utf-8"))
            reordered["matrix"]["evidence_columns"].reverse()
            SUPPORT.rw.finalize_artifact(reordered)
            unstable = root / "unstable.json"
            write_json(unstable, reordered)
            checked = self.run_cli("validate", str(unstable))
            self.assertEqual(checked.returncode, 2)
            self.assertIn("independent reconstruction", checked.stderr)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            context = self.chain(root)
            network = json.loads(context["network_path"].read_text(encoding="utf-8"))
            network["diagnostics"]["edge_conservation_and_connectivity"][0]["charge_conserved"] = False
            SUPPORT.rw.finalize_artifact(network)
            write_json(context["network_path"], network)
            result = self.build_support(context, context["review_path"], root / "forged_upstream_output.json")
            self.assertEqual(result.returncode, 2)
            self.assertIn("diagnostics mismatch", result.stderr)

    def test_bound_file_size_is_checked_independently_of_file_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            context = self.chain(root)
            output = root / "support.json"
            self.assert_success(self.build_support(context, context["review_path"], output))
            artifact = json.loads(output.read_text(encoding="utf-8"))
            artifact["literature_evidence"]["size_bytes"] += 1
            SUPPORT.rw.finalize_artifact(artifact)
            forged = root / "forged_size.json"
            write_json(forged, artifact)
            checked = self.run_cli("validate", str(forged))
            self.assertEqual(checked.returncode, 2)
            self.assertIn("file size mismatch", checked.stderr)

    def test_valid_supersession_binds_prior_and_detects_hash_or_file_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            context = self.chain(root)
            prior_output = root / "support_prior.json"
            self.assert_success(
                self.build_support(context, context["review_path"], prior_output)
            )
            prior = json.loads(prior_output.read_text(encoding="utf-8"))

            successor_review = copy.deepcopy(context["review"])
            successor_review.update({
                "support_id": "support_synthetic_network_v2",
                "reviewed_at": "2026-07-17T00:00:00Z",
                "supersedes": {
                    "path": str(prior_output),
                    "payload_sha256": prior["payload_sha256"],
                },
            })
            successor_path = self.write_review_variant(
                root, successor_review, "support_successor_review.json"
            )
            successor_output = root / "support_successor.json"
            self.assert_success(
                self.build_support(context, successor_path, successor_output)
            )
            successor = json.loads(successor_output.read_text(encoding="utf-8"))
            self.assertEqual(
                set(successor["supersedes"]),
                {"path", "sha256", "size_bytes", "schema", "payload_sha256"},
            )
            self.assertEqual(
                successor["supersedes"]["payload_sha256"], prior["payload_sha256"]
            )
            self.assert_success(self.run_cli("validate", str(successor_output)))

            wrong_hash_review = copy.deepcopy(successor_review)
            wrong_hash_review["support_id"] = "support_synthetic_network_bad_hash"
            wrong_hash_review["supersedes"]["payload_sha256"] = "f" * 64
            wrong_hash_path = self.write_review_variant(
                root, wrong_hash_review, "support_wrong_hash_review.json"
            )
            wrong_hash = self.build_support(
                context, wrong_hash_path, root / "support_wrong_hash.json"
            )
            self.assertEqual(wrong_hash.returncode, 2)
            self.assertIn("supersedes payload hash mismatch", wrong_hash.stderr)

            prior_output.write_bytes(prior_output.read_bytes() + b"\n")
            drifted = self.run_cli("validate", str(successor_output))
            self.assertEqual(drifted.returncode, 2)
            self.assertIn("file SHA-256 mismatch", drifted.stderr)

    def test_dangling_output_symlink_is_refused_without_creating_its_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            context = self.chain(root)
            target = root / "must_not_be_created.json"
            output_link = root / "dangling_output.json"
            output_link.symlink_to(target)
            result = self.build_support(context, context["review_path"], output_link)
            self.assertEqual(result.returncode, 2)
            self.assertFalse(target.exists())
            self.assertTrue(output_link.is_symlink())
            self.assertTrue(
                "symlink" in result.stderr.lower()
                or "overwrite" in result.stderr.lower()
            )

    def test_symlinks_and_live_capabilities_are_absent(self) -> None:
        source = SUPPORT_TOOL.read_text(encoding="utf-8")
        self.assertNotIn("import subprocess", source)
        self.assertNotIn("urllib", source)
        self.assertNotIn("socket", source)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            context = self.chain(root)
            review_link = root / "review_link.json"
            review_link.symlink_to(context["review_path"])
            result = self.build_support(context, review_link, root / "symlink_output.json")
            self.assertEqual(result.returncode, 2)
            self.assertIn("symlink", result.stderr)

            with (
                mock.patch("socket.create_connection", side_effect=AssertionError("network forbidden")),
                mock.patch("subprocess.run", side_effect=AssertionError("subprocess forbidden")),
            ):
                direct_output = root / "direct_output.json"
                artifact = SUPPORT.build(
                    context["network_path"], context["evidence_path"], context["snapshot_path"], context["review_path"], direct_output
                )
            self.assertFalse(artifact["calculation_ready"])
            self.assertTrue(artifact["no_submission_authorization"])

    def test_schema_is_closed_and_enumerates_all_retained_cell_states(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        SCHEMA_VALIDATOR.validate_schema_document(schema)
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(schema["properties"]["schema"]["const"], "gaussian-reaction-mechanism-support/1")
        self.assertFalse(schema["properties"]["calculation_ready"]["const"])
        self.assertTrue(schema["properties"]["no_submission_authorization"]["const"])
        self.assertEqual(
            set(schema["$defs"]["cell"]["properties"]["evidence_status"]["enum"]),
            {"positive", "negative", "contradictory", "inaccessible", "incomplete", "rejected", "no_evidence"},
        )
        for name, definition in schema["$defs"].items():
            if definition.get("type") == "object":
                self.assertFalse(definition.get("additionalProperties", True), name)


if __name__ == "__main__":
    unittest.main()
