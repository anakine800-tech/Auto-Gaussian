#!/usr/bin/env python3
"""Offline tests for the first W3 mechanism-network slice."""

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
W1_TOOL = ROOT / "skills" / "auto-g16-reaction-workflow" / "scripts" / "reaction_workflow.py"
W3_TOOL = ROOT / "skills" / "auto-g16-reaction-workflow" / "scripts" / "mechanism_network.py"
FIXTURES = ROOT / "tests" / "fixtures" / "reaction_workflow"
SCHEMA_PATH = ROOT / "contracts" / "reaction-workflow" / "mechanism-network.schema.json"
SCHEMA_VALIDATOR_PATH = ROOT / "scripts" / "validate_asymmetric_contract.py"
SCHEMA_SPEC = importlib.util.spec_from_file_location("mechanism_network_schema_validator", SCHEMA_VALIDATOR_PATH)
assert SCHEMA_SPEC and SCHEMA_SPEC.loader
SCHEMA_VALIDATOR = importlib.util.module_from_spec(SCHEMA_SPEC)
SCHEMA_SPEC.loader.exec_module(SCHEMA_VALIDATOR)


def write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def rehash_artifact(data: dict[str, object]) -> None:
    payload = copy.deepcopy(data)
    payload.pop("payload_sha256", None)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n"
    data["payload_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class MechanismNetworkTests(unittest.TestCase):
    def run_tool(self, tool: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, str(tool), *args], cwd=ROOT, check=False, capture_output=True, text=True)

    def assert_success(self, result: subprocess.CompletedProcess[str]) -> None:
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def species(self, species_id: str, label: str, formula: str, filename: str, refs: list[str], atoms: list[tuple[str, str]], origin: str = "drawn_species") -> dict[str, object]:
        return {
            "species_id": species_id,
            "preferred_label": label,
            "origin": origin,
            "required_for_claim": True,
            "source_refs": refs,
            "represented_form": "explicit closed-shell contract fixture",
            "structure": {"path": str(FIXTURES / filename), "format": "smiles", "representation_limits": ["Synthetic contract fixture only."]},
            "formula": formula,
            "formal_charge": 0,
            "multiplicity": 1,
            "component_count": 1,
            "stereochemistry_status": "not_applicable",
            "protonation_status": "reviewed",
            "salt_solvate_status": "not_applicable",
            "atom_identity": {
                "status": "reviewed",
                "atom_scope": "explicit_structure_atoms",
                "atoms": [
                    {"atom_id": atom_id, "element": element, "structure_index": index}
                    for index, (atom_id, element) in enumerate(atoms, start=1)
                ],
                "notes": ["Explicit atom identity for W3 mapping tests."],
            },
            "review_status": "reviewed",
            "blockers": [],
            "notes": [],
        }

    def build_upstream(self, root: Path, registry_mutator=None) -> tuple[Path, Path, Path, dict[str, object], dict[str, object], dict[str, object]]:
        intake_path = root / "intake.json"
        self.assert_success(self.run_tool(
            W1_TOOL, "build-intake", str(FIXTURES / "mechanism_network_intake_request.json"),
            "--scheme", str(FIXTURES / "mechanism_network_scheme.json"), "--output", str(intake_path),
        ))
        intake = json.loads(intake_path.read_text(encoding="utf-8"))
        registry_review = {
            "schema": "gaussian-reaction-species-review/1",
            "study_id": "mechanism_network_fixture",
            "intake_payload_sha256": intake["payload_sha256"],
            "species": [
                self.species("hydrogen", "H2", "H2", "hydrogen_explicit.smi", ["step_001_reactant_001"], [("hydrogen_h1", "H"), ("hydrogen_h2", "H")]),
                self.species("iodine", "I2", "I2", "iodine_explicit.smi", ["step_001_reactant_002"], [("iodine_i1", "I"), ("iodine_i2", "I")]),
                self.species("hydrogen_iodide", "HI", "HI", "hydrogen_iodide_explicit.smi", ["step_001_product_001", "step_001_product_002"], [("hi_h", "H"), ("hi_i", "I")]),
                self.species("palladium", "Pd fixture", "Pd", "palladium.smi", ["step_001_component_001"], [("palladium_pd", "Pd")], origin="condition_component"),
            ],
            "source_bindings": [
                {"source_id": "step_001_reactant_001", "species_id": "hydrogen", "coefficient": 1},
                {"source_id": "step_001_reactant_002", "species_id": "iodine", "coefficient": 1},
                {"source_id": "step_001_product_001", "species_id": "hydrogen_iodide", "coefficient": 1},
                {"source_id": "step_001_product_002", "species_id": "hydrogen_iodide", "coefficient": 1},
                {"source_id": "step_001_component_001", "species_id": "palladium", "coefficient": 1},
            ],
            "balance_review": {"status": "passed", "element_balance": "passed", "charge_balance": "passed", "unshown_species": [], "notes": ["H2 + I2 -> 2 HI is balanced in the fixture."]},
            "review_decision": "accepted",
            "review_notes": ["Offline fixture only."],
        }
        if registry_mutator is not None:
            registry_mutator(registry_review)
        registry_review_path = root / "registry_review.json"
        write_json(registry_review_path, registry_review)
        registry_path = root / "registry.json"
        self.assert_success(self.run_tool(W1_TOOL, "build-registry", str(intake_path), "--review", str(registry_review_path), "--output", str(registry_path)))
        registry = json.loads(registry_path.read_text(encoding="utf-8"))

        policy_not_applicable = {"status": "not_applicable", "value": None, "unit": None, "model": None, "rationale": "Not assigned by the contract fixture."}
        condition_review = {
            "schema": "gaussian-reaction-condition-review/1",
            "study_id": "mechanism_network_fixture",
            "intake_payload_sha256": intake["payload_sha256"],
            "registry_payload_sha256": registry["payload_sha256"],
            "global_model": {
                "standard_state": copy.deepcopy(policy_not_applicable),
                "temperature_policy": copy.deepcopy(policy_not_applicable),
                "concentration_policy": copy.deepcopy(policy_not_applicable),
                "pressure_policy": copy.deepcopy(policy_not_applicable),
                "explicit_component_policy": {"status": "reviewed", "value": None, "unit": None, "model": {"explicit_species": ["palladium"]}, "rationale": "Pd is an explicit fixture component."},
            },
            "decisions": [{"condition_id": "step_001_component_001", "treatment": "explicit_component", "species_ids": ["palladium"], "model": None, "rationale": "Explicit fixture catalyst component.", "review_status": "reviewed"}],
            "review_decision": "accepted",
            "review_notes": ["Offline fixture only."],
        }
        condition_review_path = root / "condition_review.json"
        write_json(condition_review_path, condition_review)
        condition_path = root / "condition.json"
        self.assert_success(self.run_tool(W1_TOOL, "build-condition-model", str(intake_path), str(registry_path), "--review", str(condition_review_path), "--output", str(condition_path)))
        condition = json.loads(condition_path.read_text(encoding="utf-8"))
        return intake_path, registry_path, condition_path, intake, registry, condition

    def review(self, root: Path, intake: dict[str, object], registry: dict[str, object], condition: dict[str, object]) -> tuple[Path, dict[str, object]]:
        review = json.loads((FIXTURES / "mechanism_network_review.template.json").read_text(encoding="utf-8"))
        review["intake_payload_sha256"] = intake["payload_sha256"]
        review["registry_payload_sha256"] = registry["payload_sha256"]
        review["condition_model_payload_sha256"] = condition["payload_sha256"]
        path = root / "mechanism_review.json"
        write_json(path, review)
        return path, review

    def build_network(self, root: Path, review_mutator=None, registry_mutator=None) -> tuple[Path, dict[str, object], subprocess.CompletedProcess[str]]:
        intake_path, registry_path, condition_path, intake, registry, condition = self.build_upstream(root, registry_mutator)
        review_path, review = self.review(root, intake, registry, condition)
        if review_mutator is not None:
            review_mutator(review)
            review_path.unlink()
            write_json(review_path, review)
        output = root / "mechanism_network.json"
        result = self.run_tool(W3_TOOL, "build", str(intake_path), str(registry_path), str(condition_path), "--review", str(review_path), "--output", str(output))
        return output, review, result

    def test_help_is_offline_and_exposed(self) -> None:
        for command in ("build", "validate"):
            with self.subTest(command=command):
                self.assert_success(self.run_tool(W3_TOOL, command, "--help"))

    def test_closed_shell_fixture_builds_deterministically_with_mandatory_support_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output, _, result = self.build_network(root)
            self.assert_success(result)
            artifact = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(artifact["schema"], "gaussian-reaction-mechanism-network/1")
            self.assertEqual(artifact["gate_status"], "reviewed_with_blockers")
            self.assertFalse(artifact["calculation_ready"])
            self.assertTrue(artifact["no_submission_authorization"])
            self.assertIsNone(artifact["mechanism_support"])
            self.assertEqual([item["blocker_id"] for item in artifact["blockers"]], ["mechanism_support_unavailable"])
            self.assertEqual({item["role"] for item in artifact["networks"]}, {"primary", "competing"})
            self.assertTrue(all(item["elements_conserved"] and item["charge_conserved"] and item["connection_changes_consistent"] for item in artifact["diagnostics"]["edge_conservation_and_connectivity"]))
            self.assertTrue(all(item["catalyst_cycle_closed"] for item in artifact["diagnostics"]["network_catalyst_projection_closure"]))
            self.assertTrue(artifact["diagnostics"]["reference_basin_consistency"][0]["common_element_inventory"])
            checked = self.run_tool(W3_TOOL, "validate", str(output))
            self.assert_success(checked)
            self.assertFalse(json.loads(checked.stdout)["live_actions"])
            schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
            SCHEMA_VALIDATOR.validate_schema_document(schema)
            SCHEMA_VALIDATOR._validate_schema_instance(artifact, schema, schema)

            second = root / "mechanism_network_second.json"
            command = json.loads(result.stdout)
            built_again = self.run_tool(
                W3_TOOL, "build", artifact["intake"]["path"], artifact["species_registry"]["path"], artifact["condition_model"]["path"],
                "--review", artifact["review_source"]["path"], "--output", str(second),
            )
            self.assert_success(built_again)
            self.assertEqual(output.read_bytes(), second.read_bytes())
            self.assertEqual(command["payload_sha256"], json.loads(second.read_text(encoding="utf-8"))["payload_sha256"])
            overwrite = self.run_tool(
                W3_TOOL, "build", artifact["intake"]["path"], artifact["species_registry"]["path"], artifact["condition_model"]["path"],
                "--review", artifact["review_source"]["path"], "--output", str(output),
            )
            self.assertEqual(overwrite.returncode, 2)
            self.assertIn("refusing to overwrite", overwrite.stderr)

    def test_output_schema_is_closed_and_non_authorizing(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(schema["properties"]["schema"]["const"], "gaussian-reaction-mechanism-network/1")
        self.assertEqual(schema["properties"]["mechanism_support"]["type"], "null")
        self.assertFalse(schema["properties"]["calculation_ready"]["const"])
        self.assertTrue(schema["properties"]["no_submission_authorization"]["const"])
        for definition in ("stereochemistry", "environmentModel", "catalystProjection", "stateChanges", "catalystCycle", "edgeDiagnostic", "networkDiagnostic", "basinDiagnostic"):
            self.assertFalse(schema["$defs"][definition]["additionalProperties"], definition)

    def test_schema_rejects_nested_unknown_and_missing_fields_in_real_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output, _, result = self.build_network(Path(tmp))
            self.assert_success(result)
            artifact = json.loads(output.read_text(encoding="utf-8"))
            schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
            SCHEMA_VALIDATOR._validate_schema_instance(artifact, schema, schema)

            unknown = copy.deepcopy(artifact)
            unknown["states"][0]["environment_model"]["gaussian_route"] = "forbidden"
            with self.assertRaisesRegex(SCHEMA_VALIDATOR.ContractError, "additional property is forbidden"):
                SCHEMA_VALIDATOR._validate_schema_instance(unknown, schema, schema)

            missing = copy.deepcopy(artifact)
            del missing["networks"][0]["catalyst_cycle"]["rationale"]
            with self.assertRaisesRegex(SCHEMA_VALIDATOR.ContractError, "missing required properties"):
                SCHEMA_VALIDATOR._validate_schema_instance(missing, schema, schema)

    def test_negative_fixture_cases_fail_closed_or_record_charge_blocker(self) -> None:
        cases = json.loads((FIXTURES / "mechanism_network_negative_cases.json").read_text(encoding="utf-8"))["cases"]
        for case in cases:
            with self.subTest(case=case["case_id"]), tempfile.TemporaryDirectory() as tmp:
                mutation = case["mutation"]

                def mutate(review: dict[str, object]) -> None:
                    edges = {item["edge_id"]: item for item in review["edges"]}
                    states = {item["state_id"]: item for item in review["states"]}
                    if mutation == "remove_edge_direct_last_atom_mapping":
                        edges["edge_direct"]["atom_mapping"].pop()
                    elif mutation == "remove_edge_activation_first_connection_change":
                        edges["edge_activation"]["connection_changes"].pop(0)
                    elif mutation == "change_product_catalyst_oxidation_state":
                        states["state_products"]["catalyst_projection"]["oxidation_state"] = "Pd(II) non-closing mutation"
                    elif mutation == "add_product_palladium_iodine_connection":
                        states["state_products"]["connections"].append({"atom_ids": ["p_i1", "p_pd"], "kind": "coordination", "order": "unspecified"})
                        edges["edge_direct"]["connection_changes"].append({"atom_ids": ["r_i1", "r_pd"], "kind": "coordination", "before_order": None, "after_order": "unspecified"})
                        edges["edge_release"]["connection_changes"].append({"atom_ids": ["m_i1", "m_pd"], "kind": "coordination", "before_order": None, "after_order": "unspecified"})
                    elif mutation == "split_hydrogen_component_without_full_registry_inventory":
                        reactants = states["state_reactants"]
                        hydrogen = next(item for item in reactants["components"] if item["component_id"] == "reactant_hydrogen")
                        hydrogen["atom_ids"] = ["r_h1"]
                        reactants["components"].append({"component_id": "orphan_hydrogen", "label": "orphan H fixture", "atom_ids": ["r_h2"], "formal_charge": 0, "multiplicity": 1, "registry_species_id": None, "represented_form": "invalid split fixture"})
                    elif mutation == "set_product_component_and_state_charge_to_one":
                        states["state_products"]["components"][0]["formal_charge"] = 1
                        states["state_products"]["formal_charge"] = 1
                    else:  # pragma: no cover
                        raise AssertionError(mutation)

                output, _, result = self.build_network(Path(tmp), mutate)
                if "expected_error" in case:
                    self.assertEqual(result.returncode, 2)
                    self.assertIn(case["expected_error"], result.stderr)
                    self.assertFalse(output.exists())
                else:
                    self.assert_success(result)
                    artifact = json.loads(output.read_text(encoding="utf-8"))
                    self.assertIn(case["expected_blocker"], {item["blocker_id"] for item in artifact["blockers"]})
                    self.assertTrue(any(not item["charge_conserved"] for item in artifact["diagnostics"]["edge_conservation_and_connectivity"]))
                    self.assert_success(self.run_tool(W3_TOOL, "validate", str(output)))

    def test_heavy_atom_only_registry_cannot_enter_complete_w3_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            def mutate_registry(review: dict[str, object]) -> None:
                review["species"][0]["atom_identity"]["atom_scope"] = "heavy_atoms_only"

            output, _, result = self.build_network(Path(tmp), registry_mutator=mutate_registry)
            self.assertEqual(result.returncode, 2)
            self.assertIn("requires registry atom_scope explicit_structure_atoms", result.stderr)
            self.assertFalse(output.exists())

    def test_unknown_execution_or_method_fields_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            def mutate(review: dict[str, object]) -> None:
                review["gaussian_route"] = "forbidden"

            output, _, result = self.build_network(Path(tmp), mutate)
            self.assertEqual(result.returncode, 2)
            self.assertIn("unknown fields", result.stderr)
            self.assertFalse(output.exists())

    def test_validator_recomputes_diagnostics_even_with_a_rehashed_tamper(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output, _, result = self.build_network(root)
            self.assert_success(result)
            artifact = json.loads(output.read_text(encoding="utf-8"))
            artifact["diagnostics"]["edge_conservation_and_connectivity"][0]["charge_conserved"] = False
            rehash_artifact(artifact)
            tampered = root / "tampered.json"
            tampered.write_text(json.dumps(artifact, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n", encoding="utf-8")
            checked = self.run_tool(W3_TOOL, "validate", str(tampered))
            self.assertEqual(checked.returncode, 2)
            self.assertIn("diagnostics mismatch", checked.stderr)

    def test_validator_rejects_unrelated_review_source_even_after_rehash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output, _, result = self.build_network(root)
            self.assert_success(result)
            artifact = json.loads(output.read_text(encoding="utf-8"))
            unrelated = FIXTURES / "mechanism_network_negative_cases.json"
            artifact["review_source"] = {
                "path": str(unrelated),
                "sha256": hashlib.sha256(unrelated.read_bytes()).hexdigest(),
                "size_bytes": unrelated.stat().st_size,
            }
            rehash_artifact(artifact)
            forged = root / "forged_review_source.json"
            forged.write_text(json.dumps(artifact, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n", encoding="utf-8")
            checked = self.run_tool(W3_TOOL, "validate", str(forged))
            self.assertEqual(checked.returncode, 2)
            self.assertIn("mechanism-network review", checked.stderr)


if __name__ == "__main__":
    unittest.main()
