#!/usr/bin/env python3
"""Offline unit, integration, schema, and regression tests for conformer search."""

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
SKILL = ROOT / "skills" / "auto-g16-conformer-search"
SCRIPTS = SKILL / "scripts"
CLI = SCRIPTS / "conformer_search.py"
FIXTURES = ROOT / "tests" / "fixtures" / "conformer_search"
REQUEST_PATH = FIXTURES / "request_generic.json"
R08_PATH = FIXTURES / "r08_handoff_generic.json"
SCHEMA_DIR = ROOT / "contracts" / "conformer-search"
sys.path.insert(0, str(SCRIPTS))
import conformer_core as CORE

VALIDATOR_PATH = ROOT / "scripts" / "validate_asymmetric_contract.py"
SPEC = importlib.util.spec_from_file_location("conformer_schema_validator", VALIDATOR_PATH)
assert SPEC and SPEC.loader
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def validate(schema_name: str, value: dict) -> None:
    schema = load(SCHEMA_DIR / schema_name)
    VALIDATOR.validate_schema_document(schema)
    VALIDATOR._validate_schema_instance(value, schema, schema)


class ConformerSearchTests(unittest.TestCase):
    def request(self) -> dict:
        return load(REQUEST_PATH)

    def coordinates(self) -> list[list[float]]:
        return [[0, 0, 0], [1.5, 0, 0], [2.5, 1.0, 0], [3.7, 1.2, 0], [-1.0, 0, 0], [4.7, 1.2, 0]]

    def transformed(self, points: list[list[float]]) -> list[list[float]]:
        return [[-point[1] + 7, point[0] + 3, point[2] + 2] for point in points]

    def base_candidate(self, candidate_id: str, route: str, subroute: str, category: str, coordinates: list[list[float]] | None = None) -> dict:
        state = self.request()["state"]
        return {
            "candidate_id": candidate_id,
            "route_id": route,
            "subroute_id": subroute,
            "category_id": category,
            "atom_order": [atom["map_id"] for atom in state["atoms"]],
            "elements": [atom["element"] for atom in state["atoms"]],
            "fragment_ids": [atom["fragment_id"] for atom in state["atoms"]],
            "explicit_hydrogens": [atom["explicit_hydrogen"] for atom in state["atoms"]],
            "observed_bonds": copy.deepcopy(state["bonds"]),
            "formal_charge": state["formal_charge"],
            "multiplicity": state["multiplicity"],
            "component_count": state["component_count"],
            "stereochemistry": copy.deepcopy(state["stereochemistry"]),
            "state_labels": copy.deepcopy(state["state_labels"]),
            "coordinates_angstrom": coordinates or self.coordinates(),
            "association_status": "intact",
            "non_target_transfer": False,
            "retain_as_hypothesis": False,
            "xtb_optimization_status": "converged",
            "source_input_sha256": "a" * 64,
            "source_argv": ["inert", "fixture", candidate_id],
            "random_seed": 101,
            "software": {"name": "synthetic_fixture", "version": "1", "absolute_path": "/synthetic/fixture"},
            "energy_observation": {"value": -1.0, "unit": "fixture_unit", "method": "synthetic", "ranking_allowed": False},
            "key_distances_angstrom": {"site_pair": 2.5},
            "torsions_degrees": {"central": 60.0},
            "contact_fingerprint": ["contact_alpha"],
            "fragment_descriptors": {"relative_distance": 2.5},
            "aromatic_descriptors": {},
            "custom_descriptors": {"orientation": 0.5},
            "force_backend_review": False,
        }

    def candidate_set(self, plan_path: Path) -> dict:
        result = load(FIXTURES / "candidate_set.template.json")
        result["plan_sha256"] = CORE.file_sha256(plan_path)
        coords = self.coordinates()
        different_a = copy.deepcopy(coords)
        different_a[3] = [2.2, 2.5, 0.2]
        different_b = copy.deepcopy(coords)
        different_b[2] = [1.8, 1.4, 0.8]
        different_b[3] = [1.0, 2.1, 1.2]
        b_unique = self.base_candidate("b_contact_unique", "route_b", "b2_directed", "contact_face", different_b)
        b_unique["contact_fingerprint"] = ["contact_beta"]
        result["candidates"] = [
            self.base_candidate("a_contact_primary", "route_a", "a1_crest", "contact_face", coords),
            self.base_candidate("b_contact_primary", "route_b", "b1_etkdg", "contact_face", self.transformed(coords)),
            self.base_candidate("a_contact_unique", "route_a", "a2_xtb_md", "contact_face", different_a),
            b_unique,
            self.base_candidate("a_loose_primary", "route_a", "a1_crest", "loose_face", coords),
            self.base_candidate("b_loose_primary", "route_b", "b1_etkdg", "loose_face", self.transformed(coords)),
        ]
        failures = load(FIXTURES / "candidate_failure_cases.json")["cases"]
        for case in failures:
            candidate = self.base_candidate(case["case_id"], "route_a", "a2_xtb_md", "contact_face")
            mutation = case["mutation"]
            if mutation == "swap_first_two_map_ids":
                candidate["atom_order"][0], candidate["atom_order"][1] = candidate["atom_order"][1], candidate["atom_order"][0]
            elif mutation == "add_forbidden_bond_0_2":
                candidate["observed_bonds"].append({"atoms": [0, 2], "order": 1, "in_ring": False})
            elif mutation == "change_explicit_h_fragment":
                candidate["fragment_ids"][4] = "frag_transfer"
                candidate["non_target_transfer"] = True
            elif mutation == "mark_dissociated":
                candidate["association_status"] = "dissociated"
            elif mutation == "move_atom_1_within_0_1_angstrom":
                candidate["coordinates_angstrom"][1] = [0.1, 0, 0]
            elif mutation == "mark_xtb_failed":
                candidate["xtb_optimization_status"] = "failed"
            result["candidates"].append(candidate)
        return result

    def chain(self, root: Path) -> dict[str, object]:
        request = self.request()
        plan = CORE.build_plan(request, REQUEST_PATH)
        plan_path = root / "plan.json"
        write(plan_path, plan)
        candidates = self.candidate_set(plan_path)
        candidates_path = root / "candidates.json"
        write(candidates_path, candidates)
        ledger = CORE.audit_candidates(plan, plan_path, candidates, candidates_path)
        ledger_path = root / "ledger.json"
        write(ledger_path, ledger)
        manifest = CORE.crosscheck(plan, plan_path, candidates, candidates_path, ledger, ledger_path)
        manifest_path = root / "manifest.json"
        write(manifest_path, manifest)
        return {
            "plan": plan, "plan_path": plan_path,
            "candidates": candidates, "candidates_path": candidates_path,
            "ledger": ledger, "ledger_path": ledger_path,
            "manifest": manifest, "manifest_path": manifest_path,
        }

    def test_request_schema_and_semantic_validation_are_closed(self) -> None:
        request = self.request()
        validate("request.schema.json", request)
        CORE.validate_request(request, REQUEST_PATH)
        bad = copy.deepcopy(request)
        bad["unexpected"] = True
        with self.assertRaises(VALIDATOR.ContractError):
            validate("request.schema.json", bad)
        bad = copy.deepcopy(request)
        bad["quota_policy"]["route_weights"] = {"route_a": 0.9, "route_b": 0.1}
        with self.assertRaises(CORE.ContractError):
            CORE.validate_request(bad, REQUEST_PATH)
        bad = copy.deepcopy(request)
        bad["similarity"]["symmetry_permutations"] = [[0, 1, 2]]
        with self.assertRaises(CORE.ContractError):
            CORE.validate_request(bad, REQUEST_PATH)
        bad = copy.deepcopy(request)
        bad["dependency_paths"]["xtb"] = "relative/xtb"
        with self.assertRaises(CORE.ContractError):
            CORE.validate_request(bad, REQUEST_PATH)

    def test_six_component_freedom_analysis_and_policy_cases(self) -> None:
        analysis = CORE.analyze_freedom(self.request(), REQUEST_PATH)
        self.assertEqual(set(analysis["vector"]), {"n_rot", "n_ring", "d_relative", "n_weak", "n_face", "n_symmetry"})
        self.assertEqual(analysis["vector"]["n_rot"], 1)
        self.assertEqual(analysis["vector"]["d_relative"], 0)
        for case in load(FIXTURES / "freedom_cases.json")["cases"]:
            vector = {key: case[key] for key in ("n_rot", "n_ring", "d_relative", "n_weak", "n_face", "n_symmetry")}
            category, weights, sub_a = CORE.recommend_route_policy(vector, case["fragment_count"], case["case_id"] == "contact_ion_pair")
            self.assertEqual(category, case["expected_class"])
            self.assertGreaterEqual(min(weights.values()), 0.25)
            if category in {"high", "very_high"}:
                self.assertGreater(sub_a["a2_xtb_md"], sub_a["a1_crest"])

    def test_preregistered_category_route_and_subroute_quotas_are_deterministic(self) -> None:
        plan = CORE.build_plan(self.request(), REQUEST_PATH)
        for category in plan["category_quotas"]:
            self.assertEqual(sum(category["route_quotas"].values()), category["total_quota"])
            self.assertEqual(category["route_quotas"], {"route_a": 2, "route_b": 2})
            self.assertEqual(sum(value for key, value in category["subroute_quotas"].items() if key.startswith("a")), 2)
            self.assertEqual(sum(value for key, value in category["subroute_quotas"].items() if key.startswith("b")), 2)
        self.assertEqual(plan["quota_credit_definition"], "legal_xtb_converged_route_internal_independent_structures")

    def test_dependency_diagnostic_never_executes_or_installs(self) -> None:
        with mock.patch.object(CORE.shutil, "which", return_value=None), mock.patch.object(CORE.importlib.util, "find_spec", return_value=None):
            diagnostic = CORE.dependency_diagnostic(self.request(), REQUEST_PATH)
        self.assertFalse(diagnostic["execution_performed"])
        self.assertFalse(diagnostic["installation_performed"])
        self.assertTrue(diagnostic["blockers"])
        self.assertTrue(all(item["installation_attempted"] is False for item in diagnostic["dependencies"]))
        source = (SCRIPTS / "conformer_core.py").read_text(encoding="utf-8") + CLI.read_text(encoding="utf-8")
        self.assertNotIn("import subprocess", source)
        self.assertNotIn("pip install", source)

    def test_unsupported_electronic_state_is_explicitly_blocked(self) -> None:
        request = self.request()
        request["state"]["unsupported_flags"]["transition_metal"] = True
        request["r08_handoff"]["path"] = str(R08_PATH)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "request.json"
            write(path, request)
            analysis = CORE.analyze_freedom(request, path)
            plan = CORE.build_plan(request, path)
        self.assertFalse(analysis["supported"])
        self.assertIn("unsupported state flag: transition_metal", plan["blockers"])
        self.assertFalse(plan["execution_allowed"])

    def test_candidate_legality_audit_preserves_every_failure_class(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            chain = self.chain(Path(temp))
        entries = {item["candidate_id"]: item for item in chain["ledger"]["entries"]}
        for case in load(FIXTURES / "candidate_failure_cases.json")["cases"]:
            entry = entries[case["case_id"]]
            self.assertEqual(entry["status"], case["expected_status"])
            evidence = set(entry["reasons"]) | set(entry["state_change_evidence"])
            self.assertIn(case["expected_evidence"], evidence)
            self.assertFalse(entry["accepted_into_quota"])
        self.assertTrue(chain["ledger"]["negative_evidence_preserved"])

    def test_candidate_set_cannot_weaken_plan_constraints_and_ledger_is_replayed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            chain = self.chain(root)
            weakened = copy.deepcopy(chain["candidates"])
            weakened["category_contracts"][0]["forbidden_bonds"] = []
            weakened_path = root / "weakened.json"; write(weakened_path, weakened)
            with self.assertRaises(CORE.ContractError):
                CORE.audit_candidates(chain["plan"], chain["plan_path"], weakened, weakened_path)
            forged = copy.deepcopy(chain["ledger"])
            forged["entries"][0]["status"] = "invalid"
            forged["payload_sha256"] = CORE.payload_sha256(forged)
            forged_path = root / "forged-ledger.json"; write(forged_path, forged)
            with self.assertRaises(CORE.ContractError):
                CORE.crosscheck(chain["plan"], chain["plan_path"], chain["candidates"], chain["candidates_path"], forged, forged_path)

    def test_mapped_rmsd_is_rigid_transform_invariant(self) -> None:
        left = self.coordinates()
        right = self.transformed(left)
        self.assertAlmostEqual(CORE.mapped_rmsd(left, right, [0, 1, 2, 3]), 0.0, places=7)

    def test_composite_similarity_respects_categories_and_symmetry_review(self) -> None:
        plan = CORE.build_plan(self.request(), REQUEST_PATH)
        left = self.base_candidate("left_candidate", "route_a", "a1_crest", "contact_face")
        right = self.base_candidate("right_candidate", "route_b", "b1_etkdg", "contact_face", self.transformed(self.coordinates()))
        comparison = CORE.pair_distance(left, right, plan)
        self.assertEqual(comparison["classification"], "duplicate")
        self.assertTrue(comparison["independent_backend_review_required"])
        right["category_id"] = "loose_face"
        comparison = CORE.pair_distance(left, right, plan)
        self.assertEqual(comparison["classification"], "different_category")
        self.assertTrue(comparison["category_merge_forbidden"])

    def test_crosscheck_builds_consensus_secondary_medoid_and_negative_sets(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            chain = self.chain(Path(temp))
        manifest = chain["manifest"]
        self.assertTrue(manifest["consensus_cluster_ids"])
        self.assertTrue(manifest["secondary_cluster_ids"])
        self.assertEqual(len(manifest["invalid_candidates"]), 6)
        self.assertTrue(all(cluster["medoid_candidate_id"] in cluster["member_candidate_ids"] for cluster in manifest["clusters"]))
        categories = {cluster["cluster_id"]: cluster["category_id"] for cluster in manifest["clusters"]}
        self.assertIn("contact_face", categories.values())
        self.assertIn("loose_face", categories.values())
        self.assertFalse(manifest["energies_used_for_ranking"])
        self.assertTrue(manifest["candidate_only"])
        self.assertFalse(manifest["calculation_ready"])

    def test_handoff_requires_exact_human_review_and_remains_non_authorizing(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            chain = self.chain(root)
            selected = chain["manifest"]["clusters"][0]["medoid_candidate_id"]
            review = {"schema": "gaussian-conformer-handoff-review/1", "manifest_sha256": CORE.file_sha256(chain["manifest_path"]), "selected_candidate_ids": [selected], "reviewer": "fixture_reviewer", "decision": "selected_for_downstream_input_review", "confirmed": True}
            review_path = root / "review.json"
            write(review_path, review)
            handoff = CORE.build_handoff(chain["manifest"], chain["manifest_path"], review, review_path)
            self.assertTrue(handoff["candidate_only"])
            self.assertFalse(handoff["calculation_ready"])
            self.assertFalse(handoff["gaussian_input_present"])
            handoff_path = root / "handoff.json"
            write(handoff_path, handoff)
            self.assertEqual(CORE.validate_handoff(handoff_path), handoff)
            bad = copy.deepcopy(review)
            bad["manifest_sha256"] = "f" * 64
            with self.assertRaises(CORE.ContractError):
                CORE.build_handoff(chain["manifest"], chain["manifest_path"], bad, review_path)

    def test_owner_absolute_bindings_fail_closed_after_package_move(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            top = Path(temp)
            original = top / "original"; original.mkdir()
            chain = self.chain(original)
            selected = chain["manifest"]["clusters"][0]["medoid_candidate_id"]
            review = {
                "schema": "gaussian-conformer-handoff-review/1",
                "manifest_sha256": CORE.file_sha256(chain["manifest_path"]),
                "selected_candidate_ids": [selected], "reviewer": "fixture_reviewer",
                "decision": "selected_for_downstream_input_review", "confirmed": True,
            }
            review_path = original / "review.json"; write(review_path, review)
            handoff = CORE.build_handoff(chain["manifest"], chain["manifest_path"], review, review_path)
            handoff_path = original / "handoff.json"; write(handoff_path, handoff)
            moved = top / "moved"; original.rename(moved)
            with self.assertRaises(CORE.ContractError):
                CORE.validate_handoff(moved / "handoff.json")

    def test_revision_and_supersedes_are_preserved_without_overwrite(self) -> None:
        request = self.request()
        request["r08_handoff"]["path"] = str(R08_PATH)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            old = {"schema": "gaussian-conformer-ensemble-manifest/1", "record_id": "old_fixture"}
            old["payload_sha256"] = CORE.payload_sha256(old)
            old_path = root / "old.json"
            write(old_path, old)
            request["revision"] = {"revision_id": "generic_rev2", "supersedes": {"path": "old.json", "sha256": CORE.file_sha256(old_path), "payload_sha256": old["payload_sha256"]}}
            request_path = root / "request.json"
            write(request_path, request)
            plan = CORE.build_plan(request, request_path)
            self.assertEqual(plan["revision"], request["revision"])
            output = root / "plan.json"
            CORE.write_new_json(output, plan)
            with self.assertRaises(CORE.ContractError):
                CORE.write_new_json(output, plan)

    def test_resealed_plan_forgery_and_nested_unknown_fields_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan = CORE.build_plan(self.request(), REQUEST_PATH)
            forged = copy.deepcopy(plan)
            forged["category_contracts"][0]["forbidden_bonds"] = []
            forged["payload_sha256"] = CORE.payload_sha256(forged)
            forged_path = root / "forged-plan.json"
            write(forged_path, forged)
            with self.assertRaisesRegex(CORE.ContractError, "semantic rebuild"):
                CORE.validate_plan(forged, forged_path)

            nested = copy.deepcopy(plan)
            nested["state_signature"]["unexpected_execution_surface"] = True
            nested["payload_sha256"] = CORE.payload_sha256(nested)
            nested_path = root / "nested-forgery.json"
            write(nested_path, nested)
            with self.assertRaisesRegex(CORE.ContractError, "schema validation failed"):
                CORE.validate_plan(nested, nested_path)

    def test_false_r08_path_hash_and_schema_bindings_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cases = (
                ("missing", str(root / "missing-r08.json"), CORE.file_sha256(R08_PATH), "gaussian-conformer-ensemble/1"),
                ("wrong_hash", str(R08_PATH), "f" * 64, "gaussian-conformer-ensemble/1"),
                ("wrong_schema", str(R08_PATH), CORE.file_sha256(R08_PATH), "gaussian-other-artifact/1"),
            )
            for name, path_value, digest, schema in cases:
                with self.subTest(name=name):
                    request = self.request()
                    request["r08_handoff"].update({"path": path_value, "sha256": digest, "schema": schema})
                    request_path = root / f"request-{name}.json"
                    write(request_path, request)
                    with self.assertRaises(CORE.ContractError):
                        CORE.build_plan(request, request_path)

    def test_every_object_schema_is_explicitly_closed_or_typed_map(self) -> None:
        for schema_path in sorted(SCHEMA_DIR.glob("*.json")):
            schema = load(schema_path)
            open_paths: list[str] = []

            def audit(node: object, path: str = "$") -> None:
                if isinstance(node, dict):
                    if node.get("type") == "object" and "additionalProperties" not in node and "unevaluatedProperties" not in node:
                        open_paths.append(path)
                    for key, value in node.items():
                        audit(value, f"{path}/{key}")
                elif isinstance(node, list):
                    for index, value in enumerate(node):
                        audit(value, f"{path}/{index}")

            audit(schema)
            self.assertEqual(open_paths, [], f"{schema_path.name} has open object schemas")

    def test_all_generated_artifacts_validate_against_versioned_schemas(self) -> None:
        request = self.request()
        validate("request.schema.json", request)
        dependencies = CORE.dependency_diagnostic(request, REQUEST_PATH)
        freedom = CORE.analyze_freedom(request, REQUEST_PATH)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            chain = self.chain(root)
            selected = chain["manifest"]["clusters"][0]["medoid_candidate_id"]
            review = {"schema": "gaussian-conformer-handoff-review/1", "manifest_sha256": CORE.file_sha256(chain["manifest_path"]), "selected_candidate_ids": [selected], "reviewer": "fixture_reviewer", "decision": "selected_for_downstream_input_review", "confirmed": True}
            review_path = root / "review.json"; write(review_path, review)
            handoff = CORE.build_handoff(chain["manifest"], chain["manifest_path"], review, review_path)
        validate("dependency-diagnostic.schema.json", dependencies)
        validate("freedom-analysis.schema.json", freedom)
        validate("search-plan.schema.json", chain["plan"])
        validate("candidate-set.schema.json", chain["candidates"])
        validate("validity-ledger.schema.json", chain["ledger"])
        validate("ensemble-manifest.schema.json", chain["manifest"])
        validate("handoff-review.schema.json", review)
        validate("candidate-handoff.schema.json", handoff)

    def test_cli_dry_run_chain_has_no_live_side_effect_and_refuses_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan_path = root / "plan.json"
            result = subprocess.run([sys.executable, str(CLI), "plan", str(REQUEST_PATH), "--output", str(plan_path)], cwd=ROOT, text=True, capture_output=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            candidates_path = root / "candidates.json"; write(candidates_path, self.candidate_set(plan_path))
            ledger_path = root / "ledger.json"
            result = subprocess.run([sys.executable, str(CLI), "audit", str(plan_path), str(candidates_path), "--output", str(ledger_path)], cwd=ROOT, text=True, capture_output=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest_path = root / "manifest.json"
            result = subprocess.run([sys.executable, str(CLI), "crosscheck", str(plan_path), str(candidates_path), str(ledger_path), "--output", str(manifest_path)], cwd=ROOT, text=True, capture_output=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            repeated = subprocess.run([sys.executable, str(CLI), "plan", str(REQUEST_PATH), "--output", str(plan_path)], cwd=ROOT, text=True, capture_output=True, check=False)
            self.assertNotEqual(repeated.returncode, 0)
            self.assertIn("refusing to overwrite", repeated.stderr)
            self.assertFalse(load(manifest_path)["external_execution_performed"])


if __name__ == "__main__":
    unittest.main()
