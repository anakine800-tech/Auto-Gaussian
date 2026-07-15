#!/usr/bin/env python3
"""Focused offline tests for gaussian-reaction-mechanism-support/1."""

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


ROOT = Path(__file__).parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "reaction_workflow"
TOOL = ROOT / "skills" / "auto-g16-reaction-workflow" / "scripts" / "mechanism_support.py"
SCHEMA = ROOT / "contracts" / "reaction-workflow" / "mechanism-support.schema.json"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


TS_TEST = load_module("mechanism_support_ts_fixture", ROOT / "tests" / "test_ts_precedent_map.py")
LIT = load_module("mechanism_support_lit", ROOT / "skills" / "auto-g16-reaction-literature" / "scripts" / "literature_search.py")
CONTRACT = load_module("mechanism_support_schema", ROOT / "scripts" / "validate_asymmetric_contract.py")


def write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def upstream_ref(path: Path, data: dict[str, object], schema: str) -> dict[str, str]:
    return {
        "path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "schema": schema, "payload_sha256": str(data["payload_sha256"]),
    }


def rehash(data: dict[str, object]) -> None:
    payload = copy.deepcopy(data)
    payload.pop("payload_sha256", None)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n"
    data["payload_sha256"] = hashlib.sha256(encoded.encode()).hexdigest()


class MechanismSupportTests(unittest.TestCase):
    maxDiff = None

    def run_tool(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, str(TOOL), *args], cwd=ROOT, check=False, capture_output=True, text=True)

    def assert_success(self, result: subprocess.CompletedProcess[str]) -> None:
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def build_parents(self, root: Path):
        helper = TS_TEST.TsPrecedentMapTests("test_four_analogy_classes_and_novel_de_novo_plan_are_exactly_gated")
        w1 = helper.build_mechanism(root)
        snapshot_path, snapshot = helper.build_snapshot(root, w1[0], w1[4])
        return w1, snapshot_path, snapshot

    def evidence_review(self, case: dict[str, str], location: dict[str, str]) -> dict[str, object]:
        dimensions = {name: "exact" for name in (
            "net_transformation", "elementary_step_and_atom_correspondence",
            "substrate_electronics_sterics_and_groups", "catalyst_and_active_state",
            "atom_inventory_charge_multiplicity_and_spin",
            "coordination_ion_pair_additives_and_solvent", "stereochemical_channel",
            "experimental_conditions", "computational_protocol_and_validation",
        )}
        if case["classification"] != "direct":
            dimensions["net_transformation"] = case["dimension_value"]
        location_list = [location] if case["claim_status"] == "source_reports" else []
        claim = {
            "status": case["claim_status"], "source_locations": location_list,
            "paraphrase": "Synthetic source-located mechanism evidence for offline validation." if location_list else None,
        }
        return {
            "candidate_id": case["candidate_id"],
            "bibliography": {
                "doi": f"10.5555/{case['candidate_id']}",
                "title": f"Synthetic {case['classification']} mechanism evidence",
                "authors": ["Fixture Author"], "year": 2026, "venue": "Offline Fixtures",
                "url": "https://example.invalid/mechanism-support", "publication_type": "journal-article",
            },
            "discovery": {"lexical_score": 1, "screening_tier": "fixture", "metadata_only": False},
            "source_checks": {
                "doi_or_publisher_record_checked": True, "primary_article_checked": True,
                "supporting_information_checked": True, "correction_or_retraction_checked": True,
                "access_notes": ["Synthetic public fixture; no copyrighted content."],
            },
            "directness_dimensions": dimensions,
            "evidence": {"proposed_mechanism": claim},
            "reported_protocol": {
                "status": "not_reviewed_not_approved_protocol", "optimization_frequency": None,
                "single_point": None, "solvation": None, "dispersion": None,
                "temperature_k": None, "standard_state": None,
                "low_frequency_treatment": None, "program_version": None,
            },
            "reported_ts_path": {
                "ts_labels": [], "charge_multiplicity": None, "model_truncations": None,
                "imaginary_frequencies_cm1": [], "normal_mode_interpretation": None,
                "irc_directions_reported": [], "identified_endpoints": [], "coordinates_available": None,
            },
            "exact_quotes": [],
            "reviewer_decision": {
                "status": case["literature_decision"], "bounded_use": case["bounded_use"],
                "rationale": "Synthetic bounded-use literature decision.",
                "reviewed_at": "2026-07-16T00:00:00+00:00",
            },
        }

    def build_evidence(self, root: Path, w1, snapshot_path: Path, snapshot: dict[str, object]):
        cases = json.loads((FIXTURES / "mechanism_support_cases.json").read_text(encoding="utf-8"))["cases"]
        location = {
            "source_type": "supporting_information", "locator": "synthetic mechanism section 1",
            "url_or_doi": "10.5555/offline.mechanism.fixture", "checked_at": "2026-07-16T00:00:00+00:00",
        }
        reviews = [self.evidence_review(case, location) for case in cases]
        candidates = [
            {"candidate_id": item["candidate_id"], "doi": item["bibliography"]["doi"], "title": item["bibliography"]["title"]}
            for item in reviews
        ]
        ledger = {
            "schema": LIT.LEDGER_SCHEMA, "request_id": "mechanism_support_fixture",
            "target_evidence": ["proposed_mechanism"], "candidates": candidates,
        }
        ledger = LIT.add_payload_hash(ledger, "candidate_ledger_payload_sha256")
        ledger_path = root / "support_candidate_ledger.json"
        write_json(ledger_path, ledger)
        intake_path, registry_path, condition_path, _, intake, registry, condition, _ = w1
        evidence = {
            "schema": LIT.REVIEW_SCHEMA, "request_id": "mechanism_support_fixture",
            "created_at": "2026-07-16T00:00:00+00:00", "record_status": "validated_review_record",
            "candidate_ledger_artifact": {"path": str(ledger_path), "sha256": hashlib.sha256(ledger_path.read_bytes()).hexdigest()},
            "upstream_artifacts": {
                "reaction_intake": upstream_ref(intake_path, intake, "gaussian-reaction-intake/1"),
                "species_registry": upstream_ref(registry_path, registry, "gaussian-reaction-species-registry/1"),
                "condition_model": upstream_ref(condition_path, condition, "gaussian-reaction-condition-model/1"),
                "knowledge_snapshot": upstream_ref(snapshot_path, snapshot, "auto-g16-knowledge-snapshot/1"),
            },
            "w2_binding_status": "complete", "promotion_blockers": [],
            "allowed_evidence_statuses": ["not_reviewed", "not_found", "source_ambiguous", "source_reports"],
            "allowed_decisions": ["pending", "source_checked_background", "source_reports_analogy", "source_reports_direct_precedent", "exclude"],
            "allowed_applicability_values": ["exact", "close", "remote", "contradictory", "unknown", "not_applicable"],
            "allowed_bounded_uses": ["discovery_only", "mechanism_support", "ts_topology_support", "geometry_seed_support", "protocol_candidate_support", "not_applicable_to_target"],
            "reviews": reviews, "calculation_ready": False,
            "promotable_to_mechanism_support": False, "promotable_to_ts_precedent_map": False,
            "no_submission_authorization": True, "validated_at": "2026-07-16T00:00:00+00:00",
            "evidence_review_payload_sha256": None,
        }
        evidence = LIT.add_payload_hash(evidence, "evidence_review_payload_sha256")
        path = root / "support_literature_evidence.json"
        write_json(path, evidence)
        return path, evidence, cases, location

    def target(self, edge: dict[str, object]) -> dict[str, object]:
        return {
            "edge_id": edge["edge_id"], "from_state_id": edge["from_state_id"],
            "to_state_id": edge["to_state_id"], "stereochemical_channel": edge["stereochemical_channel"],
            "edge_atom_mapping": copy.deepcopy(edge["atom_mapping"]),
            "forming_pairs": [item["atom_ids"] for item in edge["connection_changes"] if item["before_order"] is None and item["after_order"] is not None],
            "breaking_pairs": [item["atom_ids"] for item in edge["connection_changes"] if item["before_order"] is not None and item["after_order"] is None],
            "transfers": copy.deepcopy(edge["transfers"]),
        }

    def mechanistic_review(self, edge: dict[str, object], states: dict[str, dict[str, object]]) -> dict[str, object]:
        source = states[str(edge["from_state_id"])]
        target = states[str(edge["to_state_id"])]
        coordination = lambda state: [copy.deepcopy(item) for item in state["connections"] if item["kind"] == "coordination"]
        reviewed = {"status": "reviewed", "rationale": "Synthetic complete scientific review."}
        return {
            "active_catalyst_state": {
                "from_catalyst_projection": copy.deepcopy(source["catalyst_projection"]),
                "to_catalyst_projection": copy.deepcopy(target["catalyst_projection"]), **reviewed,
            },
            "elementary_step_atom_correspondence": {"state_changes": copy.deepcopy(edge["state_changes"]), **reviewed},
            "charge_multiplicity_spin": {
                "from_formal_charge": source["formal_charge"], "from_multiplicity": source["multiplicity"],
                "from_spin_description": "Reviewed singlet fixture surface.",
                "to_formal_charge": target["formal_charge"], "to_multiplicity": target["multiplicity"],
                "to_spin_description": "Reviewed singlet fixture surface.", **reviewed,
            },
            "coordination_ion_pair": {
                "from_coordination_connections": coordination(source),
                "to_coordination_connections": coordination(target),
                "ion_pair_assessment": "No ion pair is present in the synthetic fixture.", **reviewed,
            },
            "stereochemical_channel": {
                "channel": edge["stereochemical_channel"],
                "from_stereochemistry": copy.deepcopy(source["stereochemistry"]),
                "to_stereochemistry": copy.deepcopy(target["stereochemistry"]), **reviewed,
            },
        }

    def support_record(self, case: dict[str, str], location: dict[str, str], edge: dict[str, object], states: dict[str, dict[str, object]]) -> dict[str, object]:
        dimensions = []
        for name in (
            "net_transformation", "elementary_step_and_atom_correspondence",
            "substrate_electronics_sterics_and_groups", "catalyst_and_active_state",
            "atom_inventory_charge_multiplicity_and_spin",
            "coordination_ion_pair_additives_and_solvent", "stereochemical_channel",
            "experimental_conditions", "computational_protocol_and_validation",
        ):
            value = case["dimension_value"] if name == "net_transformation" and case["classification"] != "direct" else "exact"
            dimensions.append({"dimension": name, "value": value, "rationale": "Synthetic explicit applicability review.", "source_anchor": location["locator"] if case["claim_status"] == "source_reports" else "No direct source location found."})
        contradiction_id = ["support_contradicted"] if case["support_record_id"] == "support_novel_missing" else []
        exploration_unresolved = ["Known contradictory evidence is unresolved."] if case["exploration_status"] == "blocked" else []
        claim_unresolved = [] if case["claim_support_status"] == "promoted" else ["Independent target-mechanism support is not established."]
        return {
            "support_record_id": case["support_record_id"], "target": self.target(edge),
            "evidence": {
                "candidate_id": case["candidate_id"], "evidence_target": "proposed_mechanism",
                "source_location": location if case["claim_status"] == "source_reports" else None,
            },
            "applicability_dimensions": dimensions,
            "classification": {
                "category": case["classification"], "evidence_basis": case["evidence_basis"],
                "claim_effect": case["claim_effect"], "evidence_kind": case["evidence_kind"],
                "rationale": "Synthetic classification separate from promotion.",
                "alternative_explanations": ["A competing synthetic edge remains possible."],
                "important_mismatches": [] if case["classification"] == "direct" else ["The evidence does not directly establish the target edge."],
            },
            "mechanistic_review": self.mechanistic_review(edge, states),
            "hypothesis_review": {
                "internal_rationale": "The reviewed atom and state changes define a falsifiable synthetic hypothesis.",
                "alternatives": ["The competing reviewed fixture network."],
                "uncertainties": ["No real chemical inference is made by this fixture."],
                "contradictions": ["Synthetic contradictory evidence is retained."] if case["edge_id"] == "edge_direct" else [],
                "falsifiers": ["Failure to connect the reviewed endpoint atom inventories would falsify this hypothesis."],
            },
            "exploration_decision": {
                "status": case["exploration_status"], "rationale": "Explicit independent exploration decision.",
                "reviewer": "fixture_reviewer", "reviewed_at": "2026-07-16T00:00:00+00:00",
                "resolved_blockers": ["Atom, charge, active-state, channel, alternatives, uncertainty, and falsifier reviews are complete."] if case["exploration_status"] == "eligible" else [],
                "unresolved_blockers": exploration_unresolved,
                "resolved_conflict_record_ids": contradiction_id,
            },
            "claim_support_decision": {
                "status": case["claim_support_status"], "rationale": "Explicit claim-support decision separate from exploration.",
                "reviewer": "fixture_reviewer", "reviewed_at": "2026-07-16T00:00:00+00:00",
                "resolved_blockers": ["Exact source-located direct support was reviewed."] if case["claim_support_status"] == "promoted" else [],
                "unresolved_blockers": claim_unresolved,
                "resolved_conflict_record_ids": [],
            },
            "negative_evidence": ["Synthetic contradiction retained."] if case["classification"] == "contradictory" else [],
            "notes": ["Sanitized offline contract fixture."],
        }

    def prepare(self, root: Path):
        w1, snapshot_path, snapshot = self.build_parents(root)
        evidence_path, evidence, cases, location = self.build_evidence(root, w1, snapshot_path, snapshot)
        mechanism = w1[7]
        edges = {item["edge_id"]: item for item in mechanism["edges"]}
        states = {item["state_id"]: item for item in mechanism["states"]}
        review = {
            "schema": "gaussian-reaction-mechanism-support-review/1",
            "study_id": mechanism["study_id"],
            "reaction_intake_payload_sha256": w1[4]["payload_sha256"],
            "species_registry_payload_sha256": w1[5]["payload_sha256"],
            "condition_model_payload_sha256": w1[6]["payload_sha256"],
            "mechanism_network_payload_sha256": mechanism["payload_sha256"],
            "knowledge_snapshot_payload_sha256": snapshot["payload_sha256"],
            "literature_evidence_payload_sha256": evidence["evidence_review_payload_sha256"],
            "records": [self.support_record(case, location, edges[case["edge_id"]], states) for case in reversed(cases)],
            "review_decision": "accepted", "reviewer": "fixture_reviewer",
            "reviewed_at": "2026-07-16T00:00:00+00:00",
            "review_notes": ["Synthetic edge/channel evidence classification and two-gate review."],
        }
        review_path = root / "mechanism_support_review.json"
        write_json(review_path, review)
        return {
            "w1": w1, "snapshot_path": snapshot_path, "snapshot": snapshot,
            "evidence_path": evidence_path, "evidence": evidence,
            "review_path": review_path, "review": review,
        }

    def build_support(self, root: Path, review_mutator=None, evidence_mutator=None):
        prepared = self.prepare(root)
        if evidence_mutator:
            evidence = copy.deepcopy(prepared["evidence"])
            evidence_mutator(evidence)
            evidence = LIT.add_payload_hash(evidence, "evidence_review_payload_sha256")
            prepared["evidence_path"].unlink()
            write_json(prepared["evidence_path"], evidence)
            prepared["evidence"] = evidence
            prepared["review"]["literature_evidence_payload_sha256"] = evidence["evidence_review_payload_sha256"]
        if review_mutator:
            review_mutator(prepared["review"])
        prepared["review_path"].unlink()
        write_json(prepared["review_path"], prepared["review"])
        output = root / "mechanism_support.json"
        result = self.run_tool(
            "build", str(prepared["w1"][3]), str(prepared["snapshot_path"]),
            str(prepared["evidence_path"]), "--review", str(prepared["review_path"]),
            "--output", str(output),
        )
        return prepared, output, result

    def test_supported_conditional_unsupported_contradicted_and_novel_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            prepared, output, result = self.build_support(root)
            self.assert_success(result)
            artifact = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual({item["support_status"] for item in artifact["records"]}, {"supported", "conditional", "unsupported", "contradicted", "missing"})
            novel = next(item for item in artifact["records"] if item["support_record_id"] == "support_novel_missing")
            self.assertEqual(novel["classification"]["evidence_basis"], "absence_of_direct_precedent")
            self.assertTrue(novel["hypothesis_exploration_eligible"])
            self.assertFalse(novel["mechanism_claim_supported"])
            self.assertFalse(novel["mechanism_claim_validated"])
            self.assertEqual(artifact["evidence_gaps"], [{
                "edge_id": "edge_direct", "stereochemical_channel": None,
                "support_record_id": "support_novel_missing",
                "gap": "novel_hypothesis_no_direct_precedent",
                "blocks_exploration": False, "mechanism_claim_supported": False,
            }])
            direct = next(item for item in artifact["records"] if item["support_record_id"] == "support_direct")
            self.assertTrue(direct["mechanism_claim_supported"])
            self.assertFalse(artifact["mechanism_claim_validation_present"])
            self.assertFalse(artifact["calculation_ready"])
            self.assertTrue(artifact["no_submission_authorization"])
            self.assertEqual(artifact["blockers"], [])
            self.assertEqual(artifact["gate_status"], "reviewed")
            self.assert_success(self.run_tool("validate", str(output)))

            schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
            CONTRACT.validate_schema_document(schema)
            CONTRACT._validate_schema_instance(artifact, schema, schema)
            second = root / "second.json"
            again = self.run_tool(
                "build", str(prepared["w1"][3]), str(prepared["snapshot_path"]),
                str(prepared["evidence_path"]), "--review", str(prepared["review_path"]),
                "--output", str(second),
            )
            self.assert_success(again)
            self.assertEqual(output.read_bytes(), second.read_bytes())
            overwrite = self.run_tool(
                "build", str(prepared["w1"][3]), str(prepared["snapshot_path"]),
                str(prepared["evidence_path"]), "--review", str(prepared["review_path"]),
                "--output", str(output),
            )
            self.assertEqual(overwrite.returncode, 2)
            self.assertIn("refusing to overwrite", overwrite.stderr)

    def test_atom_channel_review_and_conflict_resolution_fail_closed(self) -> None:
        mutations = {
            "atom mapping differs": lambda record: record["target"]["edge_atom_mapping"][0].__setitem__("to_atom_id", "m_unknown"),
            "stereochemical channel differs": lambda record: record["target"].__setitem__("stereochemical_channel", "invented_channel"),
            "requires completed active-state": lambda record: record["mechanistic_review"]["active_catalyst_state"].__setitem__("status", "blocked"),
            "explicitly resolve every known contradiction": lambda record: record["exploration_decision"].__setitem__("resolved_conflict_record_ids", []),
        }
        for expected, mutation in mutations.items():
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as temp:
                def apply(review):
                    record = next(item for item in review["records"] if item["support_record_id"] == "support_novel_missing")
                    mutation(record)
                _, output, result = self.build_support(Path(temp), review_mutator=apply)
                self.assertEqual(result.returncode, 2)
                self.assertIn(expected, result.stderr)
                self.assertFalse(output.exists())

        with tempfile.TemporaryDirectory() as temp:
            def block_top_level_review(review):
                review["review_decision"] = "blocked"
            _, output, result = self.build_support(Path(temp), review_mutator=block_top_level_review)
            self.assertEqual(result.returncode, 2)
            self.assertIn("blocked mechanism-support review cannot promote", result.stderr)
            self.assertFalse(output.exists())

    def test_discovery_only_evidence_cannot_promote_claim_support(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            def mutate_evidence(evidence):
                direct = next(item for item in evidence["reviews"] if item["candidate_id"] == "literature_direct")
                direct["reviewer_decision"]["bounded_use"] = "discovery_only"
            _, output, result = self.build_support(Path(temp), evidence_mutator=mutate_evidence)
            self.assertEqual(result.returncode, 2)
            self.assertIn("promotion requires mechanism_support bounded use", result.stderr)
            self.assertFalse(output.exists())

    def test_upstream_drift_rehashed_forgery_and_symlink_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            prepared, output, result = self.build_support(root)
            self.assert_success(result)
            prepared["evidence_path"].write_bytes(prepared["evidence_path"].read_bytes() + b" ")
            drift = self.run_tool("validate", str(output))
            self.assertEqual(drift.returncode, 2)
            self.assertIn("file binding mismatch", drift.stderr)

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _, output, result = self.build_support(root)
            self.assert_success(result)
            artifact = json.loads(output.read_text(encoding="utf-8"))
            artifact["edge_channel_summary"][0]["mechanism_claim_supported"] = not artifact["edge_channel_summary"][0]["mechanism_claim_supported"]
            rehash(artifact)
            forged = root / "forged.json"
            write_json(forged, artifact)
            checked = self.run_tool("validate", str(forged))
            self.assertEqual(checked.returncode, 2)
            self.assertIn("summaries differ", checked.stderr)

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            prepared = self.prepare(root)
            link = root / "mechanism_link.json"
            link.symlink_to(prepared["w1"][3])
            output = root / "out.json"
            result = self.run_tool(
                "build", str(link), str(prepared["snapshot_path"]), str(prepared["evidence_path"]),
                "--review", str(prepared["review_path"]), "--output", str(output),
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("symlink", result.stderr)

    def test_unknown_duplicate_key_and_nonfinite_json_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            def add_unknown(review):
                review["gaussian_route"] = "forbidden"
            _, output, result = self.build_support(Path(temp), review_mutator=add_unknown)
            self.assertEqual(result.returncode, 2)
            self.assertIn("unknown fields", result.stderr)
            self.assertFalse(output.exists())

        for name, content, expected in (
            ("duplicate.json", '{"schema":"gaussian-reaction-mechanism-support-review/1","schema":"gaussian-reaction-mechanism-support-review/1"}', "duplicate JSON object key"),
            ("nonfinite.json", '{"schema":"gaussian-reaction-mechanism-support-review/1","value":NaN}', "non-standard JSON numeric constant"),
        ):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                prepared = self.prepare(root)
                bad = root / name
                bad.write_text(content, encoding="utf-8")
                result = self.run_tool(
                    "build", str(prepared["w1"][3]), str(prepared["snapshot_path"]), str(prepared["evidence_path"]),
                    "--review", str(bad), "--output", str(root / "out.json"),
                )
                self.assertEqual(result.returncode, 2)
                self.assertIn(expected, result.stderr)


if __name__ == "__main__":
    unittest.main()
