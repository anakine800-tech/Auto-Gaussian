#!/usr/bin/env python3
"""Focused offline tests for gaussian-ts-precedent-map/1."""

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
TOOL = ROOT / "skills" / "auto-g16-reaction-workflow" / "scripts" / "ts_precedent_map.py"
W3_TOOL = ROOT / "skills" / "auto-g16-reaction-workflow" / "scripts" / "mechanism_network.py"
SCHEMA = ROOT / "contracts" / "reaction-workflow" / "ts-precedent-map.schema.json"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MECH_TEST = load_module("ts_precedent_mechanism_fixture", ROOT / "tests" / "test_mechanism_network.py")
KB = load_module("ts_precedent_kb", ROOT / "skills" / "auto-g16-knowledge-base" / "scripts" / "knowledge_base.py")
LIT = load_module("ts_precedent_lit", ROOT / "skills" / "auto-g16-reaction-literature" / "scripts" / "literature_search.py")
CONTRACT = load_module("ts_precedent_schema", ROOT / "scripts" / "validate_asymmetric_contract.py")


def write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def file_ref(path: Path) -> dict[str, object]:
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "size_bytes": path.stat().st_size}


def upstream_ref(path: Path, data: dict[str, object], schema: str, payload_key: str = "payload_sha256") -> dict[str, str]:
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "schema": schema, "payload_sha256": str(data[payload_key])}


class TsPrecedentMapTests(unittest.TestCase):
    maxDiff = None

    def run_tool(self, tool: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, str(tool), *args], cwd=ROOT, check=False, capture_output=True, text=True)

    def assert_success(self, result: subprocess.CompletedProcess[str]) -> None:
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def build_mechanism(self, root: Path):
        helper = MECH_TEST.MechanismNetworkTests("test_help_is_offline_and_exposed")
        intake_path, registry_path, condition_path, intake, registry, condition = helper.build_upstream(root)
        review_path, _ = helper.review(root, intake, registry, condition)
        mechanism_path = root / "mechanism.json"
        built = self.run_tool(W3_TOOL, "build", str(intake_path), str(registry_path), str(condition_path), "--review", str(review_path), "--output", str(mechanism_path))
        self.assert_success(built)
        return (
            intake_path, registry_path, condition_path, mechanism_path,
            intake, registry, condition, json.loads(mechanism_path.read_text(encoding="utf-8")),
        )

    def build_snapshot(self, root: Path, intake_path: Path, intake: dict[str, object]) -> tuple[Path, dict[str, object]]:
        source = ROOT / "tests" / "fixtures" / "knowledge_base" / "records" / "knowledge-snapshot.json"
        snapshot = json.loads(source.read_text(encoding="utf-8"))
        snapshot["study_id"] = "mechanism_network_fixture"
        snapshot["parent_reaction_intake"] = {
            "path": str(intake_path), "sha256": hashlib.sha256(intake_path.read_bytes()).hexdigest(),
            "size_bytes": intake_path.stat().st_size, "schema": "gaussian-reaction-intake/1",
            "payload_sha256": intake["payload_sha256"],
        }
        snapshot["payload_sha256"] = KB.payload_sha256(snapshot)
        KB.validate_record(snapshot)
        path = root / "knowledge_snapshot.json"
        write_json(path, snapshot)
        return path, snapshot

    def evidence_review(self, case: dict[str, str], location: dict[str, str]) -> dict[str, object]:
        dimensions = {name: "exact" for name in (
            "net_transformation", "elementary_step_and_atom_correspondence",
            "substrate_electronics_sterics_and_groups", "catalyst_and_active_state",
            "atom_inventory_charge_multiplicity_and_spin",
            "coordination_ion_pair_additives_and_solvent", "stereochemical_channel",
            "experimental_conditions", "computational_protocol_and_validation",
        )}
        if case["relationship"] != "exact":
            dimensions["net_transformation"] = case["dimension_value"]
        source_reports = {"status": "source_reports", "source_locations": [location], "paraphrase": "Synthetic source-located TS precedent fact for offline validation."}
        coordinates = source_reports if case["relationship"] == "exact" else {"status": "not_found", "source_locations": [], "paraphrase": None}
        return {
            "candidate_id": case["candidate_id"],
            "bibliography": {"doi": f"10.5555/{case['candidate_id']}", "title": f"Synthetic {case['relationship']} TS precedent", "authors": ["Fixture Author"], "year": 2026, "venue": "Offline Fixtures", "url": "https://example.invalid/fixture", "publication_type": "journal-article"},
            "discovery": {"lexical_score": 1, "screening_tier": "fixture", "metadata_only": False},
            "source_checks": {"doi_or_publisher_record_checked": True, "primary_article_checked": True, "supporting_information_checked": True, "correction_or_retraction_checked": True, "access_notes": ["Synthetic public fixture; no copyrighted content."]},
            "directness_dimensions": dimensions,
            "evidence": {"transition_state_model": source_reports, "coordinates": coordinates},
            "reported_protocol": {"status": "not_reviewed_not_approved_protocol", "optimization_frequency": None, "single_point": None, "solvation": None, "dispersion": None, "temperature_k": None, "standard_state": None, "low_frequency_treatment": None, "program_version": None},
            "reported_ts_path": {"ts_labels": [], "charge_multiplicity": None, "model_truncations": None, "imaginary_frequencies_cm1": [], "normal_mode_interpretation": None, "irc_directions_reported": [], "identified_endpoints": [], "coordinates_available": None},
            "exact_quotes": [],
            "reviewer_decision": {"status": case["evidence_decision"], "bounded_use": case["bounded_use"], "rationale": "Synthetic bounded-use decision.", "reviewed_at": "2026-07-16T00:00:00+00:00"},
        }

    def build_evidence(self, root: Path, w1, snapshot_path: Path, snapshot: dict[str, object]) -> tuple[Path, dict[str, object], list[dict[str, str]], dict[str, str]]:
        intake_path, registry_path, condition_path, _, intake, registry, condition, _ = w1
        cases = json.loads((FIXTURES / "ts_precedent_cases.json").read_text(encoding="utf-8"))["cases"]
        location = {"source_type": "supporting_information", "locator": "synthetic coordinate block or figure 1", "url_or_doi": "10.5555/offline.ts.fixture", "checked_at": "2026-07-16T00:00:00+00:00"}
        candidates = []
        reviews = []
        for case in cases:
            review = self.evidence_review(case, location)
            reviews.append(review)
            candidates.append({"candidate_id": case["candidate_id"], "doi": review["bibliography"]["doi"], "title": review["bibliography"]["title"]})
        ledger = {
            "schema": LIT.LEDGER_SCHEMA, "request_id": "ts_precedent_fixture",
            "target_evidence": ["transition_state_model", "coordinates"], "candidates": candidates,
        }
        ledger = LIT.add_payload_hash(ledger, "candidate_ledger_payload_sha256")
        ledger_path = root / "candidate_ledger.json"
        write_json(ledger_path, ledger)
        evidence = {
            "schema": LIT.REVIEW_SCHEMA, "request_id": "ts_precedent_fixture",
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
        path = root / "literature_evidence.json"
        write_json(path, evidence)
        return path, evidence, cases, location

    def base_record(self, case: dict[str, str], location: dict[str, str]) -> dict[str, object]:
        exact = case["relationship"] == "exact"
        close = case["relationship"] == "close"
        source_atoms = [
            {"source_atom_id": "src_h1", "order_index": 1, "element": "H"},
            {"source_atom_id": "src_h2", "order_index": 2, "element": "H"},
            {"source_atom_id": "src_i1", "order_index": 3, "element": "I"},
            {"source_atom_id": "src_i2", "order_index": 4, "element": "I"},
            {"source_atom_id": "src_pd", "order_index": 5, "element": "Pd"},
        ] if exact or close else []
        mapping = [
            {"source_atom_id": source, "from_atom_id": source.replace("src_", "r_"), "to_atom_id": source.replace("src_", "m_")}
            for source in ("src_h1", "src_h2", "src_i1", "src_i2", "src_pd")
        ] if exact or close else []
        dimensions = []
        for dimension in (
            "net_transformation", "elementary_step_and_atom_correspondence",
            "substrate_electronics_sterics_and_groups", "catalyst_and_active_state",
            "atom_inventory_charge_multiplicity_and_spin",
            "coordination_ion_pair_additives_and_solvent", "stereochemical_channel",
            "experimental_conditions", "computational_protocol_and_validation",
        ):
            value = case["dimension_value"] if dimension == "net_transformation" and not exact else "exact"
            dimensions.append({"dimension": dimension, "value": value, "rationale": "Synthetic reviewed comparison.", "source_anchor": location["locator"]})
        if exact:
            geometry = [{
                "geometry_item_id": "geom_pd_h1", "kind": "coordination_contact", "transfer_status": "transferable",
                "descriptor": None, "value": 1.65, "range": None, "unit": "angstrom",
                "atom_refs": [{"state_id": "state_reactants", "atom_id": "r_h1"}, {"state_id": "state_reactants", "atom_id": "r_pd"}],
                "provenance": {"candidate_id": case["candidate_id"], "source_location": location, "evidence_form": "published_coordinates"},
                "applicability": "exact", "limitations": ["Synthetic coordinate object only; no geometry is copied by the builder."],
            }]
        elif close:
            geometry = [
                {
                    "geometry_item_id": "geom_pd_h1_range", "kind": "coordination_contact", "transfer_status": "transferable",
                    "descriptor": None, "value": None, "range": {"minimum": 1.5, "maximum": 1.9}, "unit": "angstrom",
                    "atom_refs": [{"state_id": "state_reactants", "atom_id": "r_h1"}, {"state_id": "state_reactants", "atom_id": "r_pd"}],
                    "provenance": {"candidate_id": case["candidate_id"], "source_location": location, "evidence_form": "figure_or_topology"},
                    "applicability": "close", "limitations": ["Approximate figure evidence; only a bounded interval is retained."],
                },
                {
                    "geometry_item_id": "geom_close_topology", "kind": "topology", "transfer_status": "transferable",
                    "descriptor": "side_on_pd_h_activation_arrangement", "value": None, "range": None, "unit": "not_applicable",
                    "atom_refs": [{"state_id": "state_reactants", "atom_id": "r_h1"}, {"state_id": "state_reactants", "atom_id": "r_h2"}, {"state_id": "state_reactants", "atom_id": "r_pd"}],
                    "provenance": {"candidate_id": case["candidate_id"], "source_location": location, "evidence_form": "figure_or_topology"},
                    "applicability": "close", "limitations": ["Only the reviewed qualitative approach topology is transferable."],
                },
            ]
        else:
            geometry = [{
                "geometry_item_id": f"geom_{case['relationship']}_topology", "kind": "topology", "transfer_status": "rebuild_required",
                "descriptor": None, "value": None, "range": None, "unit": "not_applicable",
                "atom_refs": [{"state_id": "state_reactants", "atom_id": "r_pd"}],
                "provenance": {"candidate_id": case["candidate_id"], "source_location": location, "evidence_form": "reviewer_assessment"},
                "applicability": case["dimension_value"], "limitations": ["No target geometry may be transferred."],
            }]
        if exact:
            strategy = "published_coordinates"
            prerequisites = {"status": "complete", "endpoint_state_ids": [], "geometry_item_ids": ["geom_pd_h1"], "source_object": None, "source_anchor": None, "reviewed_assertions": ["coordinate_identity_order_stereo_charge_multiplicity_coordination_audit_complete"], "notes": ["All source-coordinate transfer audits complete."]}
            promotion_status, reviewer, reviewed_at = "approved", "fixture_reviewer", "2026-07-16T00:00:00+00:00"
        elif close:
            strategy = "reviewed_structure_rebuild"
            prerequisites = {"status": "incomplete", "endpoint_state_ids": [], "geometry_item_ids": ["geom_pd_h1_range"], "source_object": None, "source_anchor": None, "reviewed_assertions": [], "notes": ["Proposal remains unpromoted."]}
            promotion_status, reviewer, reviewed_at = "pending", None, None
        else:
            strategy = "unsupported"
            prerequisites = {"status": "not_applicable", "endpoint_state_ids": [], "geometry_item_ids": [], "source_object": None, "source_anchor": None, "reviewed_assertions": [], "notes": ["Analogy is not usable for a seed."]}
            promotion_status = "rejected" if case["disposition"] == "rejected" else "blocked"
            reviewer, reviewed_at = "fixture_reviewer", "2026-07-16T00:00:00+00:00"
        coordinate_provenance = {
            "status": "published_coordinates" if exact else "figure_or_topology" if close else "not_available",
            "evidence_candidate_id": case["candidate_id"] if exact or close else None,
            "evidence_source_location": location if exact or close else None,
            "source_object": file_ref(FIXTURES / "synthetic_ts_coordinates.txt") if exact else None,
            "coordinate_block_anchor": "synthetic coordinate block" if exact else None,
            "coordinates_copied": False,
        }
        audits = {key: "reviewed" if exact else "reviewed" if close and key in {"identity", "atom_order"} else "not_available" for key in ("identity", "atom_order", "stereochemistry", "formal_charge", "multiplicity", "coordination")}
        return {
            "precedent_id": case["precedent_id"],
            "target": {
                "edge_id": "edge_activation", "from_state_id": "state_reactants", "to_state_id": "state_activated", "stereochemical_channel": None,
                "eligibility": "eligible" if exact or close else "ineligible" if case["relationship"] == "remote" else "blocked",
                "eligibility_reviewed": True, "stereochemical_channel_reviewed": True,
                "forming_pairs": [["r_h1", "r_pd"], ["r_h2", "r_pd"]], "breaking_pairs": [["r_h1", "r_h2"]], "transfers": [],
            },
            "source_precedent": {"candidate_id": case["candidate_id"], "evidence_target": "coordinates" if exact else "transition_state_model", "source_location": location, "applicability_dimensions": dimensions, "bounded_use": case["bounded_use"], "relationship": case["relationship"]},
            "source_structure": {"atom_order_review_status": "reviewed" if exact or close else "not_available", "source_atoms": source_atoms, "audits": audits, "coordinate_provenance": coordinate_provenance},
            "source_to_target_atom_mapping": mapping,
            "target_context": {"catalyst_state": "reviewed synthetic Pd fixture", "coordination": "two Pd-H contacts form", "ion_pair_additive_placement": "not applicable in fixture", "formal_charge": 0, "multiplicity": 1, "approach_topology": "synthetic reviewed topology", "facial_orientational_relationship": "not applicable in achiral fixture", "conformer_family": "single synthetic family", "review_status": "reviewed" if exact or close else "blocked", "rationale": "Explicit fixture context; no chemistry inferred."},
            "geometry_transfer": geometry, "seed_strategy": strategy, "strategy_prerequisites": prerequisites,
            "applicability_review": {"status": "reviewed" if case["relationship"] != "unusable" else "blocked", "rationale": "Synthetic applicability review.", "limitations": ["Offline contract fixture only."]},
            "uncertainties": ["No real chemical transferability is claimed."], "alternatives": ["Alternative seed families remain outside this fixture."],
            "negative_evidence": ["Remote or contradictory dimensions remain visible."] if not exact else [],
            "disposition": {"status": case["disposition"], "promotion_review": {"status": promotion_status, "reviewer": reviewer, "reviewed_at": reviewed_at, "rationale": "Synthetic promotion decision."}},
            "blockers": [] if exact else ["Not promoted by this fixture disposition."], "notes": ["Synthetic TS-precedent contract record."],
        }

    def prepare(self, root: Path) -> dict[str, object]:
        w1 = self.build_mechanism(root)
        snapshot_path, snapshot = self.build_snapshot(root, w1[0], w1[4])
        evidence_path, evidence, cases, location = self.build_evidence(root, w1, snapshot_path, snapshot)
        review = {
            "schema": "gaussian-ts-precedent-map-review/1", "study_id": "mechanism_network_fixture",
            "mechanism_network_payload_sha256": w1[7]["payload_sha256"],
            "knowledge_snapshot_payload_sha256": snapshot["payload_sha256"],
            "literature_evidence_payload_sha256": evidence["evidence_review_payload_sha256"],
            "records": [self.base_record(case, location) for case in reversed(cases)],
            "review_decision": "accepted", "review_notes": ["Synthetic review of exact, close, remote, and unusable precedents."],
        }
        review_path = root / "ts_precedent_review.json"
        write_json(review_path, review)
        return {"w1": w1, "snapshot_path": snapshot_path, "snapshot": snapshot, "evidence_path": evidence_path, "evidence": evidence, "review_path": review_path, "review": review}

    def build_map(self, root: Path, mutator=None):
        prepared = self.prepare(root)
        review = prepared["review"]
        if mutator:
            mutator(review)
            prepared["review_path"].unlink()
            write_json(prepared["review_path"], review)
        output = root / "ts_precedent_map.json"
        result = self.run_tool(TOOL, "build", str(prepared["w1"][3]), str(prepared["snapshot_path"]), str(prepared["evidence_path"]), "--review", str(prepared["review_path"]), "--output", str(output))
        return prepared, output, result

    def test_four_analogy_classes_build_deterministically_and_remain_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            prepared, output, result = self.build_map(root)
            self.assert_success(result)
            artifact = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual([item["precedent_id"] for item in artifact["records"]], ["precedent_close", "precedent_exact", "precedent_remote", "precedent_unusable"])
            self.assertEqual({item["source_precedent"]["relationship"] for item in artifact["records"]}, {"exact", "close", "remote", "unusable"})
            self.assertEqual({item["disposition"]["status"] for item in artifact["records"]}, {"proposed", "accepted_for_candidate_construction", "rejected", "blocked"})
            accepted = next(item for item in artifact["records"] if item["disposition"]["status"] == "accepted_for_candidate_construction")
            close = next(item for item in artifact["records"] if item["precedent_id"] == "precedent_close")
            qualitative = next(item for item in close["geometry_transfer"] if item["kind"] == "topology")
            self.assertEqual(qualitative["descriptor"], "side_on_pd_h_activation_arrangement")
            self.assertIsNone(qualitative["value"])
            self.assertIsNone(qualitative["range"])
            self.assertTrue(accepted["promotion_requirements_complete"])
            self.assertEqual(accepted["candidate_construction_gate"], "blocked_pending_mechanism_support")
            self.assertEqual([item["blocker_id"] for item in artifact["blockers"]], ["mechanism_support_unavailable"])
            self.assertFalse(artifact["candidate_construction_promotable"])
            self.assertFalse(artifact["calculation_ready"])
            self.assertTrue(artifact["no_submission_authorization"])
            self.assert_success(self.run_tool(TOOL, "validate", str(output)))

            schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
            CONTRACT.validate_schema_document(schema)
            CONTRACT._validate_schema_instance(artifact, schema, schema)
            invalid_qualitative = copy.deepcopy(artifact)
            invalid_close = next(item for item in invalid_qualitative["records"] if item["precedent_id"] == "precedent_close")
            next(item for item in invalid_close["geometry_transfer"] if item["kind"] == "topology")["descriptor"] = None
            with self.assertRaises(CONTRACT.ContractError):
                CONTRACT._validate_schema_instance(invalid_qualitative, schema, schema)

            second = root / "second.json"
            again = self.run_tool(TOOL, "build", str(prepared["w1"][3]), str(prepared["snapshot_path"]), str(prepared["evidence_path"]), "--review", str(prepared["review_path"]), "--output", str(second))
            self.assert_success(again)
            self.assertEqual(output.read_bytes(), second.read_bytes())
            overwrite = self.run_tool(TOOL, "build", str(prepared["w1"][3]), str(prepared["snapshot_path"]), str(prepared["evidence_path"]), "--review", str(prepared["review_path"]), "--output", str(output))
            self.assertEqual(overwrite.returncode, 2)
            self.assertIn("refusing to overwrite", overwrite.stderr)

    def test_stable_atom_and_bijective_correspondence_failures(self) -> None:
        mutations = {
            "must reference two target atoms": lambda record: record["target"]["forming_pairs"][0].__setitem__(0, "r_unknown"),
            "must be one-to-one": lambda record: record["source_to_target_atom_mapping"][1].__setitem__("source_atom_id", "src_h1"),
            "changes a known source element": lambda record: record["source_structure"]["source_atoms"][0].__setitem__("element", "I"),
        }
        for expected, mutate in mutations.items():
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as temp:
                def apply(review):
                    record = next(item for item in review["records"] if item["precedent_id"] == "precedent_exact")
                    mutate(record)
                _, output, result = self.build_map(Path(temp), apply)
                self.assertEqual(result.returncode, 2)
                self.assertIn(expected, result.stderr)
                self.assertFalse(output.exists())

    def test_coordinate_provenance_and_geometry_range_unit_refusals(self) -> None:
        def mutate_hash(record):
            record["source_structure"]["coordinate_provenance"]["source_object"]["sha256"] = "0" * 64
        def mutate_range(record):
            item = record["geometry_transfer"][0]
            item["value"] = None; item["range"] = {"minimum": 2.0, "maximum": 1.0}; item["provenance"]["evidence_form"] = "figure_or_topology"
        def mutate_unit(record):
            record["geometry_transfer"][0]["unit"] = "degree"
        for expected, mutation in (("file hash mismatch", mutate_hash), ("bounded and increasing", mutate_range), ("unit must be angstrom", mutate_unit)):
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as temp:
                def apply(review):
                    mutation(next(item for item in review["records"] if item["precedent_id"] == "precedent_exact"))
                _, output, result = self.build_map(Path(temp), apply)
                self.assertEqual(result.returncode, 2)
                self.assertIn(expected, result.stderr)
                self.assertFalse(output.exists())

    def test_qualitative_and_quantitative_geometry_are_not_conflated(self) -> None:
        mutations = {
            "qualitative geometry cannot carry a numeric value/range": lambda item: item.__setitem__("value", 1.0),
            "descriptor must be a non-empty string": lambda item: item.__setitem__("descriptor", None),
        }
        for expected, mutation in mutations.items():
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as temp:
                def apply(review):
                    record = next(item for item in review["records"] if item["precedent_id"] == "precedent_close")
                    item = next(item for item in record["geometry_transfer"] if item["kind"] == "topology")
                    mutation(item)
                _, output, result = self.build_map(Path(temp), apply)
                self.assertEqual(result.returncode, 2)
                self.assertIn(expected, result.stderr)
                self.assertFalse(output.exists())

    def test_context_and_record_promotion_semantics_fail_closed(self) -> None:
        mutations = {
            "formal_charge differs from endpoint state": lambda record: record["target_context"].__setitem__("formal_charge", 1),
            "multiplicity differs from endpoint state": lambda record: record["target_context"].__setitem__("multiplicity", 3),
            "accepted disposition cannot retain record blockers": lambda record: record["blockers"].append("Unresolved promotion issue."),
        }
        for expected, mutation in mutations.items():
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as temp:
                def apply(review):
                    mutation(next(item for item in review["records"] if item["precedent_id"] == "precedent_exact"))
                _, output, result = self.build_map(Path(temp), apply)
                self.assertEqual(result.returncode, 2)
                self.assertIn(expected, result.stderr)
                self.assertFalse(output.exists())

        for precedent_id in ("precedent_remote", "precedent_unusable"):
            with self.subTest(missing_negative_evidence=precedent_id), tempfile.TemporaryDirectory() as temp:
                def remove_negative_evidence(review):
                    record = next(item for item in review["records"] if item["precedent_id"] == precedent_id)
                    record["negative_evidence"] = []
                _, output, result = self.build_map(Path(temp), remove_negative_evidence)
                self.assertEqual(result.returncode, 2)
                self.assertIn("require explicit negative_evidence", result.stderr)
                self.assertFalse(output.exists())

    def test_accepted_disposition_rejects_rehashed_disallowed_bounded_use(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            prepared = self.prepare(root)
            evidence = copy.deepcopy(prepared["evidence"])
            evidence_record = next(item for item in evidence["reviews"] if item["candidate_id"] == "lit_exact")
            evidence_record["reviewer_decision"]["bounded_use"] = "protocol_candidate_support"
            evidence = LIT.add_payload_hash(evidence, "evidence_review_payload_sha256")
            prepared["evidence_path"].unlink()
            write_json(prepared["evidence_path"], evidence)

            review = prepared["review"]
            review["literature_evidence_payload_sha256"] = evidence["evidence_review_payload_sha256"]
            exact = next(item for item in review["records"] if item["precedent_id"] == "precedent_exact")
            exact["source_precedent"]["bounded_use"] = "protocol_candidate_support"
            prepared["review_path"].unlink()
            write_json(prepared["review_path"], review)

            output = root / "ts_precedent_map.json"
            result = self.run_tool(
                TOOL, "build", str(prepared["w1"][3]), str(prepared["snapshot_path"]),
                str(prepared["evidence_path"]), "--review", str(prepared["review_path"]),
                "--output", str(output),
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("requires geometry_seed_support or ts_topology_support", result.stderr)
            self.assertFalse(output.exists())

    def test_strategy_references_and_published_geometry_provenance_are_closed(self) -> None:
        def dangling_geometry(record):
            record["strategy_prerequisites"]["geometry_item_ids"] = ["geom_unknown"]

        def dangling_endpoint(record):
            record["strategy_prerequisites"]["endpoint_state_ids"] = ["state_unknown"]

        def unpaired_source_anchor(record):
            record["strategy_prerequisites"]["source_anchor"] = "orphan anchor"

        def detach_published_coordinates(record):
            provenance = record["source_structure"]["coordinate_provenance"]
            provenance.update({
                "status": "not_available", "evidence_candidate_id": None,
                "evidence_source_location": None, "source_object": None,
                "coordinate_block_anchor": None,
            })

        def mismatch_coordinate_evidence(record):
            record["source_structure"]["coordinate_provenance"]["evidence_candidate_id"] = "lit_close"

        def incomplete_coordinate_audit(record):
            record["source_structure"]["audits"]["coordination"] = "not_available"

        mutations = {
            "reference unknown geometry items": dangling_geometry,
            "reference states outside the target edge": dangling_endpoint,
            "must be supplied together": unpaired_source_anchor,
            "requires matching published source coordinates": detach_published_coordinates,
            "must refer to the same source evidence": mismatch_coordinate_evidence,
            "requires completed identity/order/stereochemistry/charge/multiplicity/coordination audits": incomplete_coordinate_audit,
        }
        for expected, mutation in mutations.items():
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as temp:
                def apply(review):
                    mutation(next(item for item in review["records"] if item["precedent_id"] == "precedent_exact"))
                _, output, result = self.build_map(Path(temp), apply)
                self.assertEqual(result.returncode, 2)
                self.assertIn(expected, result.stderr)
                self.assertFalse(output.exists())

    def test_each_seed_strategy_fails_closed_when_prerequisites_are_incomplete(self) -> None:
        strategies = {
            "published_coordinates": {"reviewed_assertions": []},
            "reviewed_structure_rebuild": {"reviewed_assertions": []},
            "endpoint_qst_family": {"endpoint_state_ids": ["state_reactants"], "reviewed_assertions": ["endpoint_geometries_reviewed"]},
            "relaxed_scan": {"geometry_item_ids": [], "reviewed_assertions": ["scan_scope_and_coordinate_reviewed"]},
            "hessian_guided_guess": {"source_object": None, "source_anchor": None, "reviewed_assertions": ["hessian_mode_applicability_reviewed"]},
            "unsupported": {"status": "not_applicable"},
        }
        for strategy, changes in strategies.items():
            with self.subTest(strategy=strategy), tempfile.TemporaryDirectory() as temp:
                def apply(review):
                    record = next(item for item in review["records"] if item["precedent_id"] == "precedent_exact")
                    record["seed_strategy"] = strategy
                    record["strategy_prerequisites"].update(changes)
                _, output, result = self.build_map(Path(temp), apply)
                self.assertEqual(result.returncode, 2)
                self.assertIn("prerequisites are incomplete", result.stderr)
                self.assertFalse(output.exists())

    def test_immutable_binding_drift_and_rehashed_forgery_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            prepared, output, result = self.build_map(root)
            self.assert_success(result)
            evidence = prepared["evidence_path"]
            evidence.write_bytes(evidence.read_bytes() + b" ")
            checked = self.run_tool(TOOL, "validate", str(output))
            self.assertEqual(checked.returncode, 2)
            self.assertIn("file binding mismatch", checked.stderr)

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _, output, result = self.build_map(root)
            self.assert_success(result)
            artifact = json.loads(output.read_text(encoding="utf-8"))
            artifact["records"][0]["target_context"]["catalyst_state"] = "forged"
            payload = copy.deepcopy(artifact); payload.pop("payload_sha256")
            artifact["payload_sha256"] = hashlib.sha256((json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()).hexdigest()
            forged = root / "forged.json"
            forged.write_text(json.dumps(artifact, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
            checked = self.run_tool(TOOL, "validate", str(forged))
            self.assertEqual(checked.returncode, 2)
            self.assertIn("immutable review recomputation", checked.stderr)

    def test_unknown_duplicate_key_and_nonfinite_json_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            prepared = self.prepare(root)
            review = prepared["review"]
            review["records"][0]["gaussian_route"] = "forbidden"
            prepared["review_path"].unlink(); write_json(prepared["review_path"], review)
            result = self.run_tool(TOOL, "build", str(prepared["w1"][3]), str(prepared["snapshot_path"]), str(prepared["evidence_path"]), "--review", str(prepared["review_path"]), "--output", str(root / "unknown.json"))
            self.assertEqual(result.returncode, 2)
            self.assertIn("unknown fields", result.stderr)

            duplicate = root / "duplicate.json"
            duplicate.write_text('{"schema":"gaussian-ts-precedent-map-review/1","schema":"gaussian-ts-precedent-map-review/1"}', encoding="utf-8")
            result = self.run_tool(TOOL, "build", str(prepared["w1"][3]), str(prepared["snapshot_path"]), str(prepared["evidence_path"]), "--review", str(duplicate), "--output", str(root / "duplicate-output.json"))
            self.assertEqual(result.returncode, 2)
            self.assertIn("duplicate JSON object key", result.stderr)

            nonfinite = root / "nonfinite.json"
            nonfinite.write_text('{"value":NaN}', encoding="utf-8")
            result = self.run_tool(TOOL, "build", str(prepared["w1"][3]), str(prepared["snapshot_path"]), str(prepared["evidence_path"]), "--review", str(nonfinite), "--output", str(root / "nonfinite-output.json"))
            self.assertEqual(result.returncode, 2)
            self.assertIn("non-standard JSON numeric constant", result.stderr)


if __name__ == "__main__":
    unittest.main()
