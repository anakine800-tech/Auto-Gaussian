#!/usr/bin/env python3
"""Focused offline tests for main-group multiplicity-family contracts."""

from __future__ import annotations

import ast
import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
STATE_PATH = ROOT / "skills/auto-g16-main-group-open-shell/scripts/open_shell_state.py"
FAMILY_PATH = ROOT / "skills/auto-g16-main-group-open-shell/scripts/multiplicity_family.py"
FIXTURES = ROOT / "tests/fixtures/main_group_open_shell"


def module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


STATE = module(STATE_PATH, "family_test_state")
FAMILY = module(FAMILY_PATH, "family_test_contract")
SCHEMA_VALIDATOR = module(ROOT / "scripts/validate_asymmetric_contract.py", "family_test_schema_validator")


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: dict, *, sealed: bool = False) -> Path:
    document = copy.deepcopy(value)
    if sealed:
        document["payload_sha256"] = STATE.payload_sha256(document)
    path.write_bytes(STATE.canonical_bytes(document))
    return path


def assert_closed(test: unittest.TestCase, value: object, path: str = "$") -> None:
    if isinstance(value, dict):
        if value.get("type") == "object":
            test.assertIs(value.get("additionalProperties"), False, path)
        for key, child in value.items():
            assert_closed(test, child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            assert_closed(test, child, f"{path}[{index}]")


class MultiplicityFamilyTests(unittest.TestCase):
    def prepare(self, root: Path) -> dict[str, Path | dict]:
        root = root.resolve()
        doublet_candidate = write_json(root / "ch3_doublet.candidate.json", load(FIXTURES / "ch3_candidate.json"))
        doublet_source = write_json(root / "ch3_doublet.review-source.json", load(FIXTURES / "ch3_review_source.json"))
        doublet_review_doc = STATE.build_review(doublet_candidate, doublet_source)
        doublet_review = STATE.write_new_json(root / "ch3_doublet.review.json", doublet_review_doc)

        quartet_candidate_doc = load(FIXTURES / "ch3_candidate.json")
        quartet_candidate_doc.update({"candidate_id": "ch3_quartet", "multiplicity": 4, "state_family": "excited_state", "electronic_scope": "excited_state"})
        quartet_candidate_doc["structure_sha256"] = "3" * 64
        quartet_candidate = write_json(root / "ch3_quartet.candidate.json", quartet_candidate_doc)
        quartet_source_doc = load(FIXTURES / "ch3_review_source.json")
        quartet_source_doc.update({"review_id": "ch3_quartet_review", "credible_multiplicities": [4]})
        quartet_source_doc["spin_contamination_policy"]["target_s2"] = 3.75
        quartet_source_doc["reviewer_decision"] = {"decision": "blocked", "rationale": "Quartet is retained for specialist review outside V1.", "confirmed": True}
        quartet_source_doc["alternative_solutions"] = [{"multiplicity": 2, "state_family": "doublet_ground_state", "disposition": "lower_priority", "evidence": "Family fixture binds the separately reviewed doublet."}]
        quartet_source = write_json(root / "ch3_quartet.review-source.json", quartet_source_doc)
        quartet_review_doc = STATE.build_review(quartet_candidate, quartet_source)
        quartet_review = STATE.write_new_json(root / "ch3_quartet.review.json", quartet_review_doc)

        common_doc = {
            "schema": FAMILY.SCHEMA_COMMON,
            "protocol_id": "ch3_common_protocol",
            "approval": {"decision": "approved_common_comparison_protocol", "reviewer": "synthetic_fixture_reviewer", "rationale": "Compare only separately accepted electronic energies under an exact common reference.", "confirmed": True},
            "energy_quantity": "electronic_energy_hartree",
            "common_reference": "Synthetic exact method/basis/solvent/settings reference supplied by a human; no values inferred.",
            "comparability_statement": "Only identically bound settings and accepted independent result lineages are comparable.",
            "thermochemistry_policy": "not_compared",
            "ground_state_policy": "no_automatic_ground_state_claim",
            "settings_sha256": "4" * 64,
            "calculation_ready": False,
            "no_submission_authorization": True,
        }
        common = write_json(root / "common.protocol.json", common_doc, sealed=True)

        member_paths: dict[str, dict[str, Path]] = {}
        for member_id, disposition, candidate, review, candidate_doc, review_doc, marker in (
            ("ch3_doublet", FAMILY.SUPPORTED, doublet_candidate, doublet_review, load(doublet_candidate), doublet_review_doc, "5"),
            ("ch3_quartet", FAMILY.BLOCKED, quartet_candidate, quartet_review, load(quartet_candidate), quartet_review_doc, "6"),
        ):
            candidate_payload = STATE.payload_sha256(candidate_doc)
            protocol_doc = {
                "schema": FAMILY.SCHEMA_MEMBER_PROTOCOL, "member_id": member_id, "disposition": disposition,
                "candidate_payload_sha256": candidate_payload, "state_review_payload_sha256": review_doc["payload_sha256"],
                "common_protocol_payload_sha256": load(common)["payload_sha256"], "comparison_settings_sha256": "4" * 64,
                "method_selection_source": "Synthetic human-supplied protocol fixture; no method inferred.",
                "calculation_ready": False, "no_submission_authorization": True,
            }
            protocol = write_json(root / f"{member_id}.protocol.json", protocol_doc, sealed=True)
            protocol_payload = load(protocol)["payload_sha256"]
            input_doc = {
                "schema": FAMILY.SCHEMA_MEMBER_INPUT, "member_id": member_id, "disposition": disposition,
                "candidate_payload_sha256": candidate_payload, "member_protocol_payload_sha256": protocol_payload,
                "input_artifact_sha256": marker * 64 if disposition == FAMILY.SUPPORTED else None,
                "handoff_status": "eligible_after_separate_input_approval" if disposition == FAMILY.SUPPORTED else FAMILY.BLOCKED,
                "calculation_ready": False, "no_submission_authorization": True,
            }
            input_lineage = write_json(root / f"{member_id}.input-lineage.json", input_doc, sealed=True)
            member_paths[member_id] = {"candidate": candidate, "review": review, "protocol": protocol, "input": input_lineage}

        source_doc = {
            "schema": FAMILY.SCHEMA_SOURCE, "family_id": "ch3_doublet_quartet_family", "composition_signature": "C1H3;charge=0;reviewed-atom-map-v1",
            "structure_relationship": {"kind": "same_composition_reviewed_atom_mapping", "statement": "Both branches preserve the reviewed C,H,H,H atom mapping and differ only by reviewed state branch.", "atom_mapping_reviewed": True, "confirmed": True},
            "common_protocol_path": str(common),
            "members": [
                {"member_id": member_id, "state_label": "reviewed doublet" if member_id == "ch3_doublet" else "quartet needs specialist", "multiplicity": 2 if member_id == "ch3_doublet" else 4, "disposition": FAMILY.SUPPORTED if member_id == "ch3_doublet" else FAMILY.BLOCKED, "candidate_path": str(paths["candidate"]), "state_review_path": str(paths["review"]), "protocol_path": str(paths["protocol"]), "input_lineage_path": str(paths["input"])}
                for member_id, paths in member_paths.items()
            ],
            "comparison_claims": {"energy_ordering": "not_claimed", "ground_state": "not_claimed", "thermochemistry": "not_compared"},
            "review": {"reviewer": "synthetic_fixture_reviewer", "rationale": "Retain both multiplicities while gating only the V1-supported member.", "confirmed": True},
            "calculation_ready": False, "no_submission_authorization": True,
        }
        source = write_json(root / "family.source.json", source_doc, sealed=True)
        plan_doc = FAMILY.build_plan(source)
        plan = STATE.write_new_json(root / "family.plan.json", plan_doc)
        return {"source": source, "source_doc": load(source), "common": common, "plan": plan, "plan_doc": plan_doc, "members": member_paths, "doublet_review": doublet_review}

    def add_result(self, root: Path, prepared: dict[str, Path | dict]) -> tuple[Path, Path, dict]:
        observation = STATE.build_observation(FIXTURES / "ch3_success.synthetic.txt", "family_doublet_observation")
        observation_path = STATE.write_new_json(root / "doublet.observation.json", observation)
        acceptance = STATE.build_acceptance(prepared["doublet_review"], observation_path, FIXTURES / "acceptance_policy.json", "family_doublet_acceptance")
        acceptance_path = STATE.write_new_json(root / "doublet.acceptance.json", acceptance)
        protocol = load(prepared["members"]["ch3_doublet"]["protocol"])
        input_lineage = load(prepared["members"]["ch3_doublet"]["input"])
        common = load(prepared["common"])
        result_source_doc = {
            "schema": FAMILY.SCHEMA_RESULT_SOURCE,
            "lineage_id": "family_doublet_result_lineage",
            "family_id": "ch3_doublet_quartet_family",
            "member_id": "ch3_doublet",
            "plan_path": str(prepared["plan"]),
            "acceptance_path": str(acceptance_path),
            "declared_bindings": {
                "common_protocol_payload_sha256": common["payload_sha256"],
                "comparison_settings_sha256": common["settings_sha256"],
                "member_protocol_payload_sha256": protocol["payload_sha256"],
                "member_input_lineage_payload_sha256": input_lineage["payload_sha256"],
                "input_artifact_sha256": input_lineage["input_artifact_sha256"],
                "acceptance_payload_sha256": acceptance["payload_sha256"],
                "observation_payload_sha256": observation["payload_sha256"],
                "result_source_sha256": STATE.file_sha256(FIXTURES / "ch3_success.synthetic.txt"),
            },
            "association_review": {"decision": "confirmed_supplied_offline_input_result_binding", "reviewer": "synthetic_fixture_reviewer", "rationale": "Synthetic fixture explicitly binds this exact input hash to this exact supplied result evidence.", "confirmed": True},
            "provenance": {"kind": "supplied_offline_binding", "statement": "Synthetic offline fixture binding only; it is not transport or live-execution provenance.", "transport_provenance_claimed": False, "live_execution_provenance_claimed": False},
            "calculation_ready": False,
            "no_submission_authorization": True,
        }
        result_source = write_json(root / "doublet.result-lineage-source.json", result_source_doc, sealed=True)
        result_lineage_doc = FAMILY.build_member_result_lineage(result_source)
        result_lineage = STATE.write_new_json(root / "doublet.result-lineage.json", result_lineage_doc)
        prepared["result_source"] = result_source
        prepared["result_lineage"] = result_lineage
        manifest_doc = {
            "schema": "auto-g16-main-group-multiplicity-family-result-manifest/1", "family_id": "ch3_doublet_quartet_family",
            "results": [{"member_id": "ch3_doublet", "member_result_lineage_path": str(result_lineage)}, {"member_id": "ch3_quartet", "member_result_lineage_path": None}],
            "comparison_statement": "no_energy_ordering_or_ground_state_claim", "calculation_ready": False, "no_submission_authorization": True,
        }
        manifest = write_json(root / "family.results.json", manifest_doc, sealed=True)
        audit_doc = FAMILY.build_audit(prepared["plan"], manifest)
        audit = STATE.write_new_json(root / "family.audit.json", audit_doc)
        return manifest, audit, audit_doc

    def test_contract_schemas_are_closed_versioned_and_fixture_catalogued(self) -> None:
        expected = {"multiplicity-family-source.schema.json", "multiplicity-comparison-protocol.schema.json", "multiplicity-member-protocol.schema.json", "multiplicity-member-input-lineage.schema.json", "multiplicity-member-result-lineage-source.schema.json", "multiplicity-member-result-lineage.schema.json", "multiplicity-family-plan.schema.json", "multiplicity-family-result-manifest.schema.json", "multiplicity-family-comparison-audit.schema.json"}
        paths = [ROOT / "contracts/main-group-open-shell" / name for name in expected]
        self.assertTrue(all(path.is_file() for path in paths))
        for path in paths:
            schema = load(path)
            self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
            self.assertTrue(schema["$id"].endswith("/1"))
            self.assertTrue(schema["title"].startswith("Auto-G16"))
            assert_closed(self, schema)
            SCHEMA_VALIDATOR.validate_schema_document(schema)
        cases = load(FIXTURES / "multiplicity_family_cases.json")
        self.assertIn("forbidden_energy_ordering_claim", cases["negative"])
        self.assertIn("existing closed-shell adapter", cases["closed_shell_regression"])

    def test_doublet_quartet_plan_preserves_independent_lineage_and_blocks_unsupported_member(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            prepared = self.prepare(Path(tmp))
            plan = prepared["plan_doc"]
            self.assertEqual(plan["planning_status"], "ready_for_independent_v1_handoffs")
            by_id = {item["member_id"]: item for item in plan["members"]}
            self.assertEqual(by_id["ch3_doublet"]["handoff_status"], "eligible_after_separate_input_approval")
            self.assertEqual(by_id["ch3_quartet"]["handoff_status"], FAMILY.BLOCKED)
            for kind in ("candidate", "state_review", "protocol", "input_lineage"):
                self.assertNotEqual(by_id["ch3_doublet"]["lineage"][kind]["sha256"], by_id["ch3_quartet"]["lineage"][kind]["sha256"])
            self.assertEqual(plan["comparison_status"], "planned_not_performed")
            self.assertIn("cross_multiplicity_conformer_ensemble", plan["exclusions"])
            self.assertEqual(FAMILY.validate_artifact(prepared["plan"])["payload_sha256"], plan["payload_sha256"])

    def test_all_family_artifact_instances_match_closed_schemas(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            prepared = self.prepare(root)
            manifest, audit, _ = self.add_result(root, prepared)
            artifacts = {
                "multiplicity-family-source.schema.json": prepared["source"],
                "multiplicity-comparison-protocol.schema.json": prepared["common"],
                "multiplicity-member-protocol.schema.json": prepared["members"]["ch3_doublet"]["protocol"],
                "multiplicity-member-input-lineage.schema.json": prepared["members"]["ch3_doublet"]["input"],
                "multiplicity-member-result-lineage-source.schema.json": prepared["result_source"],
                "multiplicity-member-result-lineage.schema.json": prepared["result_lineage"],
                "multiplicity-family-plan.schema.json": prepared["plan"],
                "multiplicity-family-result-manifest.schema.json": manifest,
                "multiplicity-family-comparison-audit.schema.json": audit,
            }
            for schema_name, artifact_path in artifacts.items():
                with self.subTest(schema=schema_name):
                    schema = load(ROOT / "contracts/main-group-open-shell" / schema_name)
                    SCHEMA_VALIDATOR._validate_schema_instance(load(artifact_path), schema, schema)

    def test_result_audit_retains_blocked_state_and_never_orders_energy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            prepared = self.prepare(root)
            _, audit_path, audit = self.add_result(root, prepared)
            self.assertEqual(audit["comparison_status"], "blocked_insufficient_supported_results")
            self.assertEqual(audit["energy_ordering"], "not_evaluated")
            self.assertEqual(audit["ground_state_claim"], "not_made")
            self.assertEqual(audit["thermochemistry"], "not_compared")
            blocked = next(item for item in audit["members"] if item["member_id"] == "ch3_quartet")
            self.assertEqual(blocked["status"], FAMILY.BLOCKED)
            self.assertIsNone(blocked["result_lineage"])
            FAMILY.validate_artifact(audit_path)

            forged = copy.deepcopy(audit)
            forged["members"][0]["electronic_energy_hartree"] -= 0.5
            forged_path = write_json(root / "forged-family.audit.json", forged, sealed=True)
            with self.assertRaisesRegex(FAMILY.ContractError, "deterministic reconstruction"):
                FAMILY.validate_artifact(forged_path)

    def test_missing_or_drifted_input_result_proof_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            prepared = self.prepare(root)
            manifest_path, _, _ = self.add_result(root, prepared)

            missing = load(manifest_path)
            missing["results"][0]["member_result_lineage_path"] = None
            missing_path = write_json(root / "missing-lineage.results.json", missing, sealed=True)
            blocked = FAMILY.build_audit(prepared["plan"], missing_path)
            self.assertEqual(blocked["comparison_status"], "blocked_insufficient_supported_results")
            row = next(item for item in blocked["members"] if item["member_id"] == "ch3_doublet")
            self.assertEqual(row["status"], "blocked_missing_proven_input_result_lineage")

            base_source = load(prepared["result_source"])
            drift_cases = {
                "common_protocol": "common_protocol_payload_sha256",
                "settings": "comparison_settings_sha256",
                "member_protocol": "member_protocol_payload_sha256",
                "member_input": "member_input_lineage_payload_sha256",
                "input_hash": "input_artifact_sha256",
                "acceptance": "acceptance_payload_sha256",
                "observation": "observation_payload_sha256",
                "result_source": "result_source_sha256",
            }
            for name, field in drift_cases.items():
                with self.subTest(name=name):
                    drifted = copy.deepcopy(base_source)
                    current = drifted["declared_bindings"][field]
                    drifted["declared_bindings"][field] = "f" * 64 if current != "f" * 64 else "e" * 64
                    drift_path = write_json(root / f"{name}-drift.result-source.json", drifted, sealed=True)
                    with self.assertRaisesRegex(FAMILY.ContractError, "declared input-result lineage bindings drift"):
                        FAMILY.build_member_result_lineage(drift_path)

            cross_member = copy.deepcopy(base_source)
            cross_member["member_id"] = "ch3_quartet"
            cross_path = write_json(root / "cross-member.result-source.json", cross_member, sealed=True)
            with self.assertRaisesRegex(FAMILY.ContractError, "blocked/needs-specialist"):
                FAMILY.build_member_result_lineage(cross_path)

            no_confirmation = copy.deepcopy(base_source)
            no_confirmation["association_review"]["confirmed"] = False
            no_confirmation_path = write_json(root / "unconfirmed.result-source.json", no_confirmation, sealed=True)
            with self.assertRaisesRegex(FAMILY.ContractError, "explicitly confirmed"):
                FAMILY.build_member_result_lineage(no_confirmation_path)

    def test_resealed_member_result_substitutions_and_live_provenance_claims_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            prepared = self.prepare(root)
            self.add_result(root, prepared)
            original = load(prepared["result_lineage"])
            mutations = {
                "common_protocol": lambda value: value["common_comparison_protocol"].update({"sha256": "a" * 64}),
                "member_protocol": lambda value: value["member_protocol"].update({"sha256": "b" * 64}),
                "input_lineage": lambda value: value["member_input_lineage"].update({"sha256": "c" * 64}),
                "input_hash": lambda value: value.update({"input_artifact_sha256": "d" * 64}),
                "acceptance": lambda value: value["acceptance"].update({"sha256": "e" * 64}),
                "observation": lambda value: value["observation"].update({"sha256": "f" * 64}),
                "result_source": lambda value: value["observation_source"].update({"sha256": "1" * 64}),
            }
            for name, mutate in mutations.items():
                with self.subTest(name=name):
                    forged = copy.deepcopy(original)
                    mutate(forged)
                    forged_path = write_json(root / f"forged-{name}.result-lineage.json", forged, sealed=True)
                    with self.assertRaisesRegex(FAMILY.ContractError, "deterministic reconstruction"):
                        FAMILY.validate_artifact(forged_path)

            live_claim = copy.deepcopy(load(prepared["result_source"]))
            live_claim["provenance"]["live_execution_provenance_claimed"] = True
            live_path = write_json(root / "forged-live-claim.result-source.json", live_claim, sealed=True)
            with self.assertRaisesRegex(FAMILY.ContractError, "must not claim transport or live execution"):
                FAMILY.build_member_result_lineage(live_path)

    def test_result_lineage_cli_and_public_validator_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            prepared = self.prepare(root)
            self.add_result(root, prepared)
            for artifact in (prepared["result_source"], prepared["result_lineage"]):
                checked = subprocess.run([sys.executable, str(FAMILY_PATH), "validate", str(artifact)], text=True, capture_output=True, check=False)
                self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
                self.assertIn('"valid": true', checked.stdout)
            output = root / "cli.result-lineage.json"
            built = subprocess.run([sys.executable, str(FAMILY_PATH), "bind-result", str(prepared["result_source"]), "--output", str(output)], text=True, capture_output=True, check=False)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            self.assertEqual(load(output), load(prepared["result_lineage"]))

    def test_family_member_hash_protocol_and_claim_drift_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            prepared = self.prepare(root)
            source = copy.deepcopy(prepared["source_doc"])
            source["members"][1]["protocol_path"] = source["members"][0]["protocol_path"]
            drift = write_json(root / "protocol-reuse.source.json", source, sealed=True)
            with self.assertRaisesRegex(FAMILY.ContractError, "identity mismatch|disposition drift|reused"):
                FAMILY.build_plan(drift)

            claim = copy.deepcopy(prepared["source_doc"])
            claim["comparison_claims"]["energy_ordering"] = "doublet_below_quartet"
            forbidden = write_json(root / "forbidden-claim.source.json", claim, sealed=True)
            with self.assertRaisesRegex(FAMILY.ContractError, "must not assert energy ordering"):
                FAMILY.build_plan(forbidden)

            member_set = copy.deepcopy(prepared["source_doc"])
            member_set["members"][1]["member_id"] = "drifted_quartet"
            drifted = write_json(root / "member-drift.source.json", member_set, sealed=True)
            with self.assertRaisesRegex(FAMILY.ContractError, "identity drift"):
                FAMILY.build_plan(drifted)

            composition = copy.deepcopy(load(prepared["members"]["ch3_quartet"]["candidate"]))
            composition["atoms"][-1]["element"] = "F"
            composition_path = write_json(root / "composition-drift.candidate.json", composition)
            composition_source = copy.deepcopy(prepared["source_doc"])
            composition_source["members"][1]["candidate_path"] = str(composition_path)
            composition_drift = write_json(root / "composition-drift.source.json", composition_source, sealed=True)
            with self.assertRaisesRegex(FAMILY.ContractError, "composition, atom count, or charge drift"):
                FAMILY.build_plan(composition_drift)

            metal = copy.deepcopy(load(prepared["members"]["ch3_quartet"]["candidate"]))
            metal["atoms"][0]["element"] = "Fe"
            metal_path = write_json(root / "metal.candidate.json", metal)
            metal_source = copy.deepcopy(prepared["source_doc"])
            metal_source["members"][1]["candidate_path"] = str(metal_path)
            metal_family = write_json(root / "metal.source.json", metal_source, sealed=True)
            with self.assertRaisesRegex(FAMILY.ContractError, "main-group only"):
                FAMILY.build_plan(metal_family)

    def test_unsupported_result_and_manifest_ordering_claim_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            prepared = self.prepare(root)
            manifest, _, _ = self.add_result(root, prepared)
            value = load(manifest)
            value["results"][1]["member_result_lineage_path"] = value["results"][0]["member_result_lineage_path"]
            bypass = write_json(root / "blocked-bypass.results.json", value, sealed=True)
            with self.assertRaisesRegex(FAMILY.ContractError, "blocked/needs-specialist"):
                FAMILY.build_audit(prepared["plan"], bypass)

            ordering = load(manifest)
            ordering["comparison_statement"] = "doublet_is_ground_state"
            claim = write_json(root / "ordering.results.json", ordering, sealed=True)
            with self.assertRaisesRegex(FAMILY.ContractError, "forbidden comparison claim"):
                FAMILY.build_audit(prepared["plan"], claim)

    def test_offline_surface_and_closed_shell_adapter_remain_unchanged(self) -> None:
        tree = ast.parse(FAMILY_PATH.read_text(encoding="utf-8"))
        imports = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        imports |= {str(node.module).split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        self.assertTrue(imports.isdisjoint({"subprocess", "socket", "requests", "paramiko", "asyncssh"}))
        adapter_schema = load(ROOT / "contracts/reaction-workflow/candidate-input-handoff.schema.json")
        self.assertEqual(adapter_schema["properties"]["workflow_kind"]["const"], "closed_shell_main_group_single_guess_ts_freq")
        self.assertEqual(adapter_schema["$defs"]["identity"]["properties"]["multiplicity"]["const"], 1)


if __name__ == "__main__":
    unittest.main()
