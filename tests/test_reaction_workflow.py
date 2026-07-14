#!/usr/bin/env python3
"""Offline tests for W0 reaction-package recovery and W1 intake builders."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
TOOL = ROOT / "skills" / "auto-g16-reaction-workflow" / "scripts" / "reaction_workflow.py"
PACKAGE_TOOL = ROOT / "skills" / "auto-g16-chemdraw-structures" / "scripts" / "create_reaction_scheme_package.py"
FIXTURES = ROOT / "tests" / "fixtures" / "reaction_workflow"
FINAL_WORKFLOW = ROOT / "docs" / "end-to-end-reaction-computation-workflow.md"
LITERATURE_DESIGN = (
    ROOT
    / "skills"
    / "auto-g16-reaction-workflow"
    / "references"
    / "literature-evidence-design.md"
)
KNOWLEDGE_DESIGN = (
    ROOT
    / "skills"
    / "auto-g16-reaction-workflow"
    / "references"
    / "knowledge-database-design.md"
)


def write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def atoms(species_id: str, count: int) -> list[dict[str, object]]:
    return [
        {
            "atom_id": f"{species_id}_c_{index:03d}",
            "element": "C",
            "structure_index": index,
        }
        for index in range(1, count + 1)
    ]


class ReactionWorkflowTests(unittest.TestCase):
    def run_python(self, script: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(script), *args],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

    def assert_success(self, completed: subprocess.CompletedProcess[str]) -> None:
        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)

    def registry_review(self, intake: dict[str, object]) -> dict[str, object]:
        occurrence_bindings = [
            {"source_id": "step_001_reactant_001", "species_id": "butadiene", "coefficient": 1},
            {"source_id": "step_001_reactant_002", "species_id": "ethene", "coefficient": 1},
            {"source_id": "step_001_product_001", "species_id": "cyclohexene", "coefficient": 1},
        ]
        species_specs = (
            ("butadiene", "1,3-butadiene", "C4H6", "butadiene.smi", 4, ["step_001_reactant_001"]),
            ("ethene", "ethene", "C2H4", "ethene.smi", 2, ["step_001_reactant_002"]),
            ("cyclohexene", "cyclohexene", "C6H10", "cyclohexene.smi", 6, ["step_001_product_001"]),
        )
        species = []
        for species_id, label, formula, filename, atom_count, refs in species_specs:
            species.append({
                "species_id": species_id,
                "preferred_label": label,
                "origin": "drawn_species",
                "required_for_claim": True,
                "source_refs": refs,
                "represented_form": "neutral_closed_shell",
                "structure": {
                    "path": str(FIXTURES / filename),
                    "format": "smiles",
                    "representation_limits": ["Fixture atom identity covers heavy atoms only."],
                },
                "formula": formula,
                "formal_charge": 0,
                "multiplicity": 1,
                "component_count": 1,
                "stereochemistry_status": "not_applicable",
                "protonation_status": "reviewed",
                "salt_solvate_status": "not_applicable",
                "atom_identity": {
                    "status": "reviewed",
                    "atom_scope": "heavy_atoms_only",
                    "atoms": atoms(species_id, atom_count),
                    "notes": ["Synthetic fixture mapping."],
                },
                "review_status": "reviewed",
                "blockers": [],
                "notes": [],
            })
        return {
            "schema": "gaussian-reaction-species-review/1",
            "study_id": "diels_alder_fixture",
            "intake_payload_sha256": intake["payload_sha256"],
            "species": species,
            "source_bindings": occurrence_bindings,
            "balance_review": {
                "status": "passed",
                "element_balance": "passed",
                "charge_balance": "passed",
                "unshown_species": [],
                "notes": ["C6H10 is balanced for the synthetic fixture."],
            },
            "review_decision": "accepted",
            "review_notes": ["Offline contract fixture only."],
        }

    def condition_review(self, intake: dict[str, object], registry: dict[str, object]) -> dict[str, object]:
        return {
            "schema": "gaussian-reaction-condition-review/1",
            "study_id": "diels_alder_fixture",
            "intake_payload_sha256": intake["payload_sha256"],
            "registry_payload_sha256": registry["payload_sha256"],
            "global_model": {
                "standard_state": {
                    "status": "reviewed",
                    "value": "1M",
                    "unit": None,
                    "model": {"scope": "per independently treated solution species"},
                    "rationale": "Explicit fixture decision; not an inferred default.",
                },
                "temperature_policy": {
                    "status": "reviewed",
                    "value": 353.15,
                    "unit": "K",
                    "model": {"source": "80 °C experimental condition"},
                    "rationale": "Use the transcribed reaction temperature for later proposals.",
                },
                "concentration_policy": {
                    "status": "not_applicable",
                    "value": None,
                    "unit": None,
                    "model": None,
                    "rationale": "No concentration was reported in the fixture.",
                },
                "pressure_policy": {
                    "status": "not_applicable",
                    "value": None,
                    "unit": None,
                    "model": None,
                    "rationale": "No pressure-dependent species was declared.",
                },
                "explicit_component_policy": {
                    "status": "reviewed",
                    "value": None,
                    "unit": None,
                    "model": {"explicit_species": []},
                    "rationale": "Toluene is represented only by the reviewed continuum choice.",
                },
            },
            "decisions": [
                {
                    "condition_id": "step_001_component_001",
                    "treatment": "continuum_environment",
                    "species_ids": [],
                    "model": {"solvent": "toluene", "candidate_model": "SMD"},
                    "rationale": "Explicit fixture decision; not selected by the builder.",
                    "review_status": "reviewed",
                },
                {
                    "condition_id": "step_001_field_001",
                    "treatment": "computational_parameter",
                    "species_ids": [],
                    "model": {"temperature_k": 353.15},
                    "rationale": "Bind the transcribed 80 °C condition.",
                    "review_status": "reviewed",
                },
                {
                    "condition_id": "step_001_field_002",
                    "treatment": "experimental_context_only",
                    "species_ids": [],
                    "model": None,
                    "rationale": "Reaction time is retained but does not select a Gaussian model.",
                    "review_status": "reviewed",
                },
                {
                    "condition_id": "step_001_field_003",
                    "treatment": "experimental_context_only",
                    "species_ids": [],
                    "model": None,
                    "rationale": "Experimental yield is retained for later comparison only.",
                    "review_status": "reviewed",
                },
            ],
            "review_decision": "accepted",
            "review_notes": ["Offline model fixture only."],
        }

    def build_chain(self, root: Path) -> tuple[Path, Path, Path, dict[str, object], dict[str, object], dict[str, object]]:
        intake_path = root / "intake.json"
        built_intake = self.run_python(
            TOOL,
            "build-intake",
            str(FIXTURES / "intake_request.json"),
            "--scheme",
            str(FIXTURES / "normalized_scheme.json"),
            "--output",
            str(intake_path),
        )
        self.assert_success(built_intake)
        intake = json.loads(intake_path.read_text(encoding="utf-8"))

        registry_review_path = root / "registry_review.json"
        write_json(registry_review_path, self.registry_review(intake))
        registry_path = root / "registry.json"
        built_registry = self.run_python(
            TOOL,
            "build-registry",
            str(intake_path),
            "--review",
            str(registry_review_path),
            "--output",
            str(registry_path),
        )
        self.assert_success(built_registry)
        registry = json.loads(registry_path.read_text(encoding="utf-8"))

        condition_review_path = root / "condition_review.json"
        write_json(condition_review_path, self.condition_review(intake, registry))
        condition_path = root / "condition_model.json"
        built_condition = self.run_python(
            TOOL,
            "build-condition-model",
            str(intake_path),
            str(registry_path),
            "--review",
            str(condition_review_path),
            "--output",
            str(condition_path),
        )
        self.assert_success(built_condition)
        condition = json.loads(condition_path.read_text(encoding="utf-8"))
        return intake_path, registry_path, condition_path, intake, registry, condition

    def test_all_commands_expose_help(self) -> None:
        for command in ("build-intake", "build-registry", "build-condition-model", "validate"):
            with self.subTest(command=command):
                self.assert_success(self.run_python(TOOL, command, "--help"))

    def test_end_to_end_offline_chain_is_hash_bound_and_non_authorizing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self.build_chain(Path(tmp))
            intake_path, registry_path, condition_path, intake, registry, condition = paths
            self.assertEqual(intake["gate_status"], "reviewed")
            self.assertEqual(registry["gate_status"], "reviewed")
            self.assertEqual(condition["gate_status"], "reviewed")
            self.assertFalse(condition["calculation_ready"])
            self.assertTrue(condition["no_submission_authorization"])
            self.assertEqual(len(condition["decisions"]), 4)
            self.assertEqual(registry["intake"]["payload_sha256"], intake["payload_sha256"])
            self.assertEqual(condition["species_registry"]["payload_sha256"], registry["payload_sha256"])
            for artifact_path in (intake_path, registry_path, condition_path):
                checked = self.run_python(TOOL, "validate", str(artifact_path))
                self.assert_success(checked)
                self.assertFalse(json.loads(checked.stdout)["live_actions"])

    def test_intake_preserves_source_exact_condition_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            intake_path = Path(tmp) / "intake.json"
            built = self.run_python(
                TOOL,
                "build-intake",
                str(FIXTURES / "intake_request.json"),
                "--scheme",
                str(FIXTURES / "normalized_scheme.json"),
                "--output",
                str(intake_path),
            )
            self.assert_success(built)
            intake = json.loads(intake_path.read_text(encoding="utf-8"))
            items = intake["steps"][0]["condition_items"]
            self.assertEqual(items[0]["raw_text"], "toluene")
            self.assertEqual(items[1]["source_value"]["raw_text"], "80 °C")
            self.assertEqual(items[2]["source_value"]["raw_text"], "4 h")
            self.assertEqual(items[3]["source_value"]["raw_text"], "92%")

    def test_catalytic_intake_preserves_roles_amounts_workup_and_blockers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            intake_path = Path(tmp) / "blocked_intake.json"
            built = self.run_python(
                TOOL,
                "build-intake",
                str(FIXTURES / "complex_blocked_request.json"),
                "--scheme",
                str(FIXTURES / "complex_blocked_scheme.json"),
                "--output",
                str(intake_path),
            )
            self.assert_success(built)
            intake = json.loads(intake_path.read_text(encoding="utf-8"))
            self.assertEqual(intake["gate_status"], "reviewed_with_blockers")
            self.assertFalse(intake["calculation_ready"])
            self.assertEqual(
                {item["blocker_id"] for item in intake["blockers"]},
                {
                    "ligand_identity_unresolved",
                    "product_stereochemistry_unresolved",
                    "step_001_component_002_confidence",
                    "step_001_product_001_confidence",
                    "unshown_balance_species",
                },
            )
            items = intake["steps"][0]["condition_items"]
            self.assertEqual(items[0]["role"], "catalyst")
            self.assertEqual(items[0]["mol_percent"], 5)
            self.assertEqual(items[1]["role"], "ligand")
            self.assertEqual(items[1]["mol_percent"], 6)
            self.assertEqual(items[2]["role"], "base")
            self.assertEqual(items[2]["equivalents"], 2.0)
            workup = next(item for item in items if item["kind"] == "workup")
            self.assertEqual(workup["source_value"]["raw_text"], "then sat. NH4Cl")
            self.assertTrue(any(
                "Do not infer the active palladium catalyst" in item
                for item in intake["claim_scope"]["non_goals"]
            ))

    def test_registry_rejects_unbound_drawn_occurrence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            intake_path = root / "intake.json"
            self.assert_success(self.run_python(
                TOOL, "build-intake", str(FIXTURES / "intake_request.json"),
                "--scheme", str(FIXTURES / "normalized_scheme.json"),
                "--output", str(intake_path),
            ))
            intake = json.loads(intake_path.read_text(encoding="utf-8"))
            review = self.registry_review(intake)
            review["source_bindings"] = review["source_bindings"][:-1]
            review_path = root / "review.json"
            write_json(review_path, review)
            failed = self.run_python(
                TOOL, "build-registry", str(intake_path), "--review", str(review_path),
                "--output", str(root / "registry.json"),
            )
            self.assertEqual(failed.returncode, 2)
            self.assertIn("every drawn reactant/product occurrence must be bound", failed.stderr)

    def test_registry_balances_unshown_byproduct_and_preserves_salt_and_implicit_h_limits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scheme_path = root / "scheme.json"
            write_json(scheme_path, {
                "scheme_id": "dehydration_fixture",
                "steps": [{
                    "step_id": "dehydration",
                    "arrow": {"type": "forward", "direction": "right"},
                    "reactants": [{"label": "ethanol"}],
                    "products": [{"label": "ethene"}],
                    "text_above": [],
                    "text_below": [],
                    "components": [],
                    "confidence": "certain",
                    "notes": [],
                }],
            })
            request_path = root / "request.json"
            write_json(request_path, {
                "schema": "gaussian-reaction-intake-request/1",
                "study_id": "dehydration_fixture",
                "source_files": [{
                    "source_id": "source_cdxml",
                    "path": str(FIXTURES / "source_scheme.cdxml"),
                    "role": "chemdraw_source",
                    "description": "Synthetic dehydration source fixture.",
                }],
                "claim_scope": {
                    "questions": ["thermodynamics"],
                    "claim_ceiling": "intake_only",
                    "non_goals": ["No calculation authorization."],
                },
                "unresolved_transcription": [],
                "review_decision": "accepted",
                "review_notes": [],
            })
            intake_path = root / "intake.json"
            self.assert_success(self.run_python(
                TOOL, "build-intake", str(request_path), "--scheme", str(scheme_path),
                "--output", str(intake_path),
            ))
            intake = json.loads(intake_path.read_text(encoding="utf-8"))

            def species_record(
                species_id: str,
                label: str,
                origin: str,
                required: bool,
                source_refs: list[str],
                filename: str,
                formula: str,
                component_count: int,
                atom_records: list[dict[str, object]],
                salt_status: str,
            ) -> dict[str, object]:
                return {
                    "species_id": species_id,
                    "preferred_label": label,
                    "origin": origin,
                    "required_for_claim": required,
                    "source_refs": source_refs,
                    "represented_form": "disconnected_salt" if component_count > 1 else "neutral_closed_shell",
                    "structure": {
                        "path": str(FIXTURES / filename),
                        "format": "smiles",
                        "representation_limits": ["Hydrogens are implicit in the fixture SMILES."],
                    },
                    "formula": formula,
                    "formal_charge": 0,
                    "multiplicity": 1,
                    "component_count": component_count,
                    "stereochemistry_status": "not_applicable",
                    "protonation_status": "reviewed",
                    "salt_solvate_status": salt_status,
                    "atom_identity": {
                        "status": "reviewed",
                        "atom_scope": "heavy_atoms_only",
                        "atoms": atom_records,
                        "notes": ["Implicit hydrogens must be expanded before proton-transfer mapping."],
                    },
                    "review_status": "reviewed",
                    "blockers": [],
                    "notes": [],
                }

            review = {
                "schema": "gaussian-reaction-species-review/1",
                "study_id": "dehydration_fixture",
                "intake_payload_sha256": intake["payload_sha256"],
                "species": [
                    species_record("ethanol", "ethanol", "drawn_species", True, ["step_001_reactant_001"], "ethanol.smi", "C2H6O", 1, atoms("ethanol", 2) + [{"atom_id": "ethanol_o_003", "element": "O", "structure_index": 3}], "not_applicable"),
                    species_record("ethene", "ethene", "drawn_species", True, ["step_001_product_001"], "ethene.smi", "C2H4", 1, atoms("ethene", 2), "not_applicable"),
                    species_record("water", "water", "unshown_species", True, [], "water.smi", "H2O", 1, [{"atom_id": "water_o_001", "element": "O", "structure_index": 1}], "not_applicable"),
                    species_record("sodium_chloride", "sodium chloride", "model_species", False, [], "sodium_chloride.smi", "ClNa", 2, [{"atom_id": "sodium_chloride_na_001", "element": "Na", "structure_index": 1}, {"atom_id": "sodium_chloride_cl_002", "element": "Cl", "structure_index": 2}], "reviewed"),
                ],
                "source_bindings": [
                    {"source_id": "step_001_reactant_001", "species_id": "ethanol", "coefficient": 1},
                    {"source_id": "step_001_product_001", "species_id": "ethene", "coefficient": 1},
                ],
                "balance_review": {
                    "status": "passed",
                    "element_balance": "passed",
                    "charge_balance": "passed",
                    "unshown_species": [{
                        "species_id": "water",
                        "step_id": "step_001",
                        "side": "product",
                        "coefficient": 1,
                    }],
                    "notes": ["Water is an explicit unshown product."],
                },
                "review_decision": "accepted",
                "review_notes": [],
            }
            review_path = root / "review.json"
            write_json(review_path, review)
            registry_path = root / "registry.json"
            built = self.run_python(
                TOOL, "build-registry", str(intake_path), "--review", str(review_path),
                "--output", str(registry_path),
            )
            self.assert_success(built)
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            computed = registry["balance_review"]["computed_steps"][0]
            self.assertTrue(computed["elements_balanced"])
            self.assertTrue(computed["charges_balanced"])
            self.assertEqual(registry["balance_review"]["unshown_species"][0]["species_id"], "water")
            salt = next(item for item in registry["species"] if item["species_id"] == "sodium_chloride")
            self.assertEqual(salt["component_count"], 2)
            self.assertEqual(salt["salt_solvate_status"], "reviewed")

    def test_registry_refuses_a_false_passed_balance_claim(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            intake_path = root / "intake.json"
            self.assert_success(self.run_python(
                TOOL, "build-intake", str(FIXTURES / "intake_request.json"),
                "--scheme", str(FIXTURES / "normalized_scheme.json"),
                "--output", str(intake_path),
            ))
            intake = json.loads(intake_path.read_text(encoding="utf-8"))
            review = self.registry_review(intake)
            review["species"][2]["formula"] = "C6H12"
            review_path = root / "review.json"
            write_json(review_path, review)
            failed = self.run_python(
                TOOL, "build-registry", str(intake_path), "--review", str(review_path),
                "--output", str(root / "registry.json"),
            )
            self.assertEqual(failed.returncode, 2)
            self.assertIn("claims passed elemental balance", failed.stderr)

    def test_condition_review_rejects_missing_decision_and_can_record_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            intake_path, registry_path, _, intake, registry, _ = self.build_chain(root)

            missing_review = self.condition_review(intake, registry)
            missing_review["decisions"] = missing_review["decisions"][:-1]
            missing_path = root / "missing_review.json"
            write_json(missing_path, missing_review)
            missing = self.run_python(
                TOOL, "build-condition-model", str(intake_path), str(registry_path),
                "--review", str(missing_path), "--output", str(root / "missing.json"),
            )
            self.assertEqual(missing.returncode, 2)
            self.assertIn("every condition item must have exactly one decision", missing.stderr)

            blocked_review = self.condition_review(intake, registry)
            blocked_review["review_decision"] = "accepted_with_blockers"
            blocked_review["decisions"][0] = {
                "condition_id": "step_001_component_001",
                "treatment": "unresolved",
                "species_ids": [],
                "model": None,
                "rationale": "",
                "review_status": "blocked",
            }
            blocked_path = root / "blocked_review.json"
            write_json(blocked_path, blocked_review)
            blocked_output = root / "blocked.json"
            blocked = self.run_python(
                TOOL, "build-condition-model", str(intake_path), str(registry_path),
                "--review", str(blocked_path), "--output", str(blocked_output),
            )
            self.assert_success(blocked)
            artifact = json.loads(blocked_output.read_text(encoding="utf-8"))
            self.assertEqual(artifact["gate_status"], "reviewed_with_blockers")
            self.assertEqual(artifact["blockers"][0]["scope"], "step_001_component_001")

    def test_payload_tampering_and_overwrite_are_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            intake_path, _, _, intake, _, _ = self.build_chain(root)
            intake["claim_scope"]["claim_ceiling"] = "tampered"
            tampered = root / "tampered.json"
            write_json(tampered, intake)
            checked = self.run_python(TOOL, "validate", str(tampered))
            self.assertEqual(checked.returncode, 2)
            self.assertIn("payload SHA-256 mismatch", checked.stderr)

            overwrite = self.run_python(
                TOOL, "build-intake", str(FIXTURES / "intake_request.json"),
                "--scheme", str(FIXTURES / "normalized_scheme.json"),
                "--output", str(intake_path),
            )
            self.assertEqual(overwrite.returncode, 2)
            self.assertIn("refusing to overwrite", overwrite.stderr)

    def test_recovered_chemdraw_reaction_package_builder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "package"
            built = self.run_python(
                PACKAGE_TOOL,
                str(FIXTURES / "normalized_scheme.json"),
                str(output),
            )
            self.assert_success(built)
            for filename in (
                "normalized_scheme.json",
                "reaction_steps.csv",
                "reaction_components.csv",
                "reaction_conditions.txt",
                "reaction_scheme.svg",
            ):
                self.assertTrue((output / filename).is_file(), filename)
            self.assertTrue(output.with_suffix(".zip").is_file())
            overwrite = self.run_python(
                PACKAGE_TOOL,
                str(FIXTURES / "normalized_scheme.json"),
                str(output),
            )
            self.assertNotEqual(overwrite.returncode, 0)
            self.assertIn("Output directory is not empty", overwrite.stderr)

    def test_future_literature_gate_is_explicit_and_non_authorizing(self) -> None:
        workflow = FINAL_WORKFLOW.read_text(encoding="utf-8")
        design = LITERATURE_DESIGN.read_text(encoding="utf-8")

        self.assertIn("### R04 — Literature evidence and transition-state precedents", workflow)
        self.assertIn(
            "### W2 — Knowledge databases, literature evidence and TS precedents",
            workflow,
        )
        for artifact in (
            "gaussian-reaction-literature-query/1",
            "gaussian-reaction-literature-evidence/1",
            "gaussian-reaction-mechanism-support/1",
            "gaussian-ts-precedent-map/1",
        ):
            self.assertIn(artifact, workflow)
            self.assertIn(artifact, design)

        self.assertIn("Literature similarity does not prove the current mechanism", design)
        self.assertIn("no_submission_authorization: true", design)
        self.assertIn("Coordinates unavailable from the source must not be fabricated", design)

    def test_future_knowledge_databases_are_reviewed_and_snapshot_bound(self) -> None:
        workflow = FINAL_WORKFLOW.read_text(encoding="utf-8")
        design = KNOWLEDGE_DESIGN.read_text(encoding="utf-8")

        self.assertIn(
            "### W2 — Knowledge databases, literature evidence and TS precedents",
            workflow,
        )
        self.assertIn("auto-g16-knowledge-base", workflow)
        self.assertIn("auto-g16-knowledge-base", design)
        for artifact in (
            "auto-g16-structure-record/1",
            "auto-g16-method-record/1",
            "auto-g16-source-record/1",
            "auto-g16-knowledge-link/1",
            "auto-g16-knowledge-snapshot/1",
        ):
            self.assertIn(artifact, workflow)
            self.assertIn(artifact, design)

        self.assertIn("structure registry", design)
        self.assertIn("computational-method registry", design)
        self.assertIn("literature and book registry", design)
        self.assertIn("later database updates do not change the study", design.lower())
        self.assertIn("no_submission_authorization: true", design)
        self.assertIn("It must never auto-select one", design)


if __name__ == "__main__":
    unittest.main()
