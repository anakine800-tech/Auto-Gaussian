#!/usr/bin/env python3
"""Focused offline tests for main-group open-shell V1 contracts."""

from __future__ import annotations

import ast
import copy
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
MODULE = ROOT / "skills" / "auto-g16-main-group-open-shell" / "scripts" / "open_shell_state.py"
FIXTURES = ROOT / "tests" / "fixtures" / "main_group_open_shell"
SPEC = importlib.util.spec_from_file_location("open_shell_state", MODULE)
assert SPEC and SPEC.loader
OPEN_SHELL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(OPEN_SHELL)


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def dump(path: Path, value: dict, *, canonical: bool = False) -> None:
    if canonical:
        path.write_bytes(OPEN_SHELL.canonical_bytes(value))
    else:
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def assert_all_object_schemas_closed(test: unittest.TestCase, value: object, path: str = "$") -> None:
    if isinstance(value, dict):
        if value.get("type") == "object":
            test.assertIs(value.get("additionalProperties"), False, path)
        for key, child in value.items():
            assert_all_object_schemas_closed(test, child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            assert_all_object_schemas_closed(test, child, f"{path}[{index}]")


class MainGroupOpenShellTests(unittest.TestCase):
    def build_chain(self, root: Path, prefix: str = "ch3") -> tuple[Path, Path, Path, dict, dict, dict]:
        root = root.resolve()
        candidate = FIXTURES / f"{prefix}_candidate.json"
        review_source = FIXTURES / f"{prefix}_review_source.json"
        log = FIXTURES / f"{prefix}_success.synthetic.txt"
        review = OPEN_SHELL.build_review(candidate, review_source)
        review_path = root / f"{prefix}.review.json"
        OPEN_SHELL.write_new_json(review_path, review)
        observation = OPEN_SHELL.build_observation(log, f"{prefix}_observation")
        observation_path = root / f"{prefix}.observation.json"
        OPEN_SHELL.write_new_json(observation_path, observation)
        acceptance = OPEN_SHELL.build_acceptance(
            review_path, observation_path, FIXTURES / "acceptance_policy.json", f"{prefix}_acceptance"
        )
        acceptance_path = root / f"{prefix}.acceptance.json"
        OPEN_SHELL.write_new_json(acceptance_path, acceptance)
        return review_path, observation_path, acceptance_path, review, observation, acceptance

    def test_contract_schemas_are_closed_versioned_draft_2020_12(self) -> None:
        contract_dir = ROOT / "contracts" / "main-group-open-shell"
        self.assertEqual(
            {path.name for path in contract_dir.glob("*.schema.json")},
            {"electronic-state-review.schema.json", "gaussian-result-observation.schema.json", "result-acceptance.schema.json"},
        )
        for path in contract_dir.glob("*.schema.json"):
            schema = load(path)
            self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
            self.assertTrue(schema["$id"].endswith("/1"))
            self.assertTrue(schema["title"].startswith("Auto-G16"))
            assert_all_object_schemas_closed(self, schema)

    def test_ch3_doublet_and_triplet_carbene_positive_chains(self) -> None:
        for prefix, electrons, target_s2 in (("ch3", 9, 0.75), ("triplet_ch2", 8, 2.0)):
            with self.subTest(prefix=prefix), tempfile.TemporaryDirectory() as tmp:
                review_path, observation_path, acceptance_path, review, observation, acceptance = self.build_chain(Path(tmp), prefix)
                self.assertEqual(review["electron_accounting"]["electron_count"], electrons)
                self.assertTrue(review["electron_accounting"]["multiplicity_parity_consistent"])
                self.assertEqual(review["wavefunction_policy"]["target_s2"], target_s2)
                self.assertEqual(review["status"], "accepted")
                self.assertEqual(observation["observation_status"], "complete")
                self.assertFalse(observation["scientific_acceptance"])
                self.assertEqual(acceptance["status"], "accepted")
                self.assertEqual(acceptance["decision"], "accepted_for_v1_minimum_evidence")
                for path in (review_path, observation_path, acceptance_path):
                    self.assertEqual(OPEN_SHELL.validate_artifact(path)["payload_sha256"], load(path)["payload_sha256"])
                self.assertFalse(acceptance["calculation_ready"])
                self.assertTrue(acceptance["no_submission_authorization"])
                self.assertTrue(all(value is False for value in acceptance["authorizations"].values()))

    def test_result_facts_fail_closed_for_missing_s2_contamination_instability_and_state_drift(self) -> None:
        cases = {
            "missing_s2": lambda text: reline(text, "Annihilation of the first spin contaminant:\nS**2 before annihilation 0.7600, after 0.7505\n", ""),
            "contaminated": lambda text: text.replace("after 0.7505", "after 1.2000"),
            "unstable": lambda text: text.replace("The wavefunction is stable under the perturbations considered.", "The wavefunction has an internal instability."),
            "state_drift": lambda text: text.replace("Multiplicity = 2", "Multiplicity = 4"),
            "partial_frequencies": lambda text: reline(text, "Frequencies -- 510.0 780.0 1100.0\nFrequencies -- 1200.0 1500.0 3000.0", "Frequencies -- 510.0"),
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            review = OPEN_SHELL.build_review(FIXTURES / "ch3_candidate.json", FIXTURES / "ch3_review_source.json")
            review_path = OPEN_SHELL.write_new_json(root / "review.json", review)
            base = (FIXTURES / "ch3_success.synthetic.txt").read_text(encoding="utf-8")
            for name, mutate in cases.items():
                with self.subTest(name=name):
                    log_path = root / f"{name}.txt"
                    log_path.write_text(mutate(base), encoding="utf-8")
                    observation = OPEN_SHELL.build_observation(log_path, f"{name}_observation")
                    observation_path = OPEN_SHELL.write_new_json(root / f"{name}.observation.json", observation)
                    acceptance = OPEN_SHELL.build_acceptance(review_path, observation_path, FIXTURES / "acceptance_policy.json", f"{name}_acceptance")
                    self.assertEqual(acceptance["status"], "blocked")
                    blocked = {item["check"] for item in acceptance["checks"] if item["status"] == "block"}
                    expected = {"missing_s2": "s2_present", "contaminated": "s2_within_policy", "unstable": "stability", "state_drift": "state_identity", "partial_frequencies": "frequencies_complete"}[name]
                    self.assertIn(expected, blocked)

    def test_review_rejects_or_blocks_parity_singlet_multireference_and_metal(self) -> None:
        candidate_base = load(FIXTURES / "ch3_candidate.json")
        source_base = load(FIXTURES / "ch3_review_source.json")
        cases: list[tuple[str, dict, dict, bool, str]] = []

        parity = copy.deepcopy(candidate_base)
        parity["multiplicity"] = 3
        parity_source = copy.deepcopy(source_base)
        parity_source["credible_multiplicities"] = [3]
        parity_source["spin_contamination_policy"]["target_s2"] = 2.0
        cases.append(("parity", parity, parity_source, True, "electron_parity_multiplicity_mismatch"))

        singlet = copy.deepcopy(candidate_base)
        singlet["multiplicity"] = 1
        singlet["state_family"] = "open_shell_singlet"
        singlet["electronic_scope"] = "broken_symmetry"
        singlet_source = copy.deepcopy(source_base)
        singlet_source["credible_multiplicities"] = [1]
        singlet_source["spin_contamination_policy"]["target_s2"] = 0.0
        singlet_source["reviewer_decision"] = {"decision": "blocked", "rationale": "Open-shell singlet is outside V1.", "confirmed": True}
        cases.append(("singlet", singlet, singlet_source, False, "state_family_outside_v1"))

        multireference_source = copy.deepcopy(source_base)
        multireference_source["multireference_risk"] = {"level": "unresolved", "evidence": ["Synthetic unresolved diagnostic."], "action": "escalate"}
        multireference_source["reviewer_decision"] = {"decision": "blocked", "rationale": "Multireference risk unresolved.", "confirmed": True}
        cases.append(("multireference", candidate_base, multireference_source, False, "multireference_risk_unresolved_or_material"))

        metal = copy.deepcopy(candidate_base)
        metal["atoms"][0]["element"] = "Fe"
        metal_source = copy.deepcopy(source_base)
        metal_source["reviewer_decision"] = {"decision": "blocked", "rationale": "Metal-containing candidate is outside V1.", "confirmed": True}
        cases.append(("metal", metal, metal_source, False, "metal_or_non_main_group_element"))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            for name, candidate, source, must_raise, reason in cases:
                with self.subTest(name=name):
                    candidate["candidate_id"] = f"{name}_candidate"
                    source["review_id"] = f"{name}_review"
                    candidate_path, source_path = root / f"{name}.candidate.json", root / f"{name}.source.json"
                    dump(candidate_path, candidate)
                    dump(source_path, source)
                    if must_raise:
                        with self.assertRaisesRegex(OPEN_SHELL.ContractError, reason):
                            OPEN_SHELL.build_review(candidate_path, source_path)
                    else:
                        review = OPEN_SHELL.build_review(candidate_path, source_path)
                        self.assertEqual(review["status"], "blocked")
                        self.assertIn(reason, review["conclusion"]["reasons"])

    def test_strict_json_hash_overwrite_symlink_and_unknown_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            review = OPEN_SHELL.build_review(FIXTURES / "ch3_candidate.json", FIXTURES / "ch3_review_source.json")
            review_path = OPEN_SHELL.write_new_json(root / "review.json", review)
            with self.assertRaisesRegex(OPEN_SHELL.ContractError, "overwrite"):
                OPEN_SHELL.write_new_json(review_path, review)

            forged = copy.deepcopy(review)
            forged["electron_accounting"]["electron_count"] = 10
            dump(root / "forged.json", forged, canonical=True)
            with self.assertRaisesRegex(OPEN_SHELL.ContractError, "payload hash mismatch"):
                OPEN_SHELL.validate_artifact(root / "forged.json")

            unknown = copy.deepcopy(review)
            unknown["unknown"] = True
            unknown["payload_sha256"] = OPEN_SHELL.payload_sha256(unknown)
            dump(root / "unknown.json", unknown, canonical=True)
            with self.assertRaisesRegex(OPEN_SHELL.ContractError, "unknown"):
                OPEN_SHELL.validate_artifact(root / "unknown.json")

            duplicate = root / "duplicate.json"
            duplicate.write_text('{"schema":"x","schema":"y"}\n', encoding="utf-8")
            with self.assertRaisesRegex(OPEN_SHELL.ContractError, "duplicate JSON key"):
                OPEN_SHELL.load_json(duplicate)

            nonfinite = root / "nonfinite.json"
            nonfinite.write_text('{"value":NaN}\n', encoding="utf-8")
            with self.assertRaisesRegex(OPEN_SHELL.ContractError, "non-finite"):
                OPEN_SHELL.load_json(nonfinite)

            symlink = root / "review-link.json"
            try:
                os.symlink(review_path, symlink)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks unavailable")
            with self.assertRaisesRegex(OPEN_SHELL.ContractError, "symlink"):
                OPEN_SHELL.validate_artifact(symlink)

            real_input = root / "real-input"
            real_input.mkdir()
            nested_review = real_input / "review.json"
            nested_review.write_bytes(review_path.read_bytes())
            linked_input = root / "linked-input"
            os.symlink(real_input, linked_input, target_is_directory=True)
            with self.assertRaisesRegex(OPEN_SHELL.ContractError, "contains a symlink"):
                OPEN_SHELL.validate_artifact(linked_input / "review.json")

            real_output = root / "real-output"
            real_output.mkdir()
            linked_output = root / "linked-output"
            os.symlink(real_output, linked_output, target_is_directory=True)
            with self.assertRaisesRegex(OPEN_SHELL.ContractError, "contains a symlink"):
                OPEN_SHELL.write_new_json(linked_output / "new.json", review)

    def test_no_live_execution_surface(self) -> None:
        tree = ast.parse(MODULE.read_text(encoding="utf-8"))
        imported = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        imported |= {str(node.module).split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        self.assertTrue(imported.isdisjoint({"subprocess", "socket", "requests", "paramiko", "asyncssh"}))
        parser = OPEN_SHELL.build_parser()
        choices = next(action.choices for action in parser._actions if getattr(action, "choices", None))
        self.assertEqual(set(choices), {"review", "observe", "accept", "validate"})


def reline(text: str, old: str, new: str) -> str:
    return text.replace(old, new)


if __name__ == "__main__":
    unittest.main()
