#!/usr/bin/env python3
"""Focused offline tests for scientific TS seed contracts and builders."""

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
CORE_PATH = ROOT / "skills/auto-g16-ts-seed/scripts/ts_seed_core.py"
SPEC = importlib.util.spec_from_file_location("ts_seed_core_test", CORE_PATH)
assert SPEC and SPEC.loader
CORE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CORE)


def write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def artifact(path: Path, schema: str, content: str) -> None:
    value = {"schema": schema, "content": content, "payload_sha256": ""}
    value["payload_sha256"] = CORE.payload_sha256(value)
    write(path, value)


class TSSeedTests(unittest.TestCase):
    def package(self, root: Path) -> dict[str, dict]:
        paths = {}
        for name, schema in (
            ("target", "reviewed-target-coordinates/1"),
            ("reactant", "accepted-endpoint/1"),
            ("product", "accepted-endpoint/1"),
            ("protocol", "gaussian-protocol-selection/1"),
        ):
            path = root / f"{name}.json"
            artifact(path, schema, f"reviewed {name}")
            paths[name] = CORE.artifact_ref(path, root)
        return paths

    def precedence(self, selected: str) -> list[dict]:
        rank = CORE.STRATEGIES.index(selected)
        result = []
        for index, strategy in enumerate(CORE.STRATEGIES):
            status = "selected" if index == rank else ("unavailable" if index < rank else "not_evaluated_lower_priority")
            result.append({"strategy": strategy, "status": status, "rationale": f"Reviewed disposition for {strategy}."})
        return result

    def source(self, root: Path, candidate_id: str = "seed_primary", hypothesis: str = "Concerted hydrogen transfer", shift: float = 0.0) -> dict:
        refs = self.package(root)
        strategy = "exact_reviewed_target_coordinates"
        return {
            "candidate_id": candidate_id,
            "target_id": "target_edge_01",
            "target_coordinates": refs["target"],
            "seed_strategy": strategy,
            "coordinates": [
                {"index": 1, "atom_id": "atom_h01", "element": "H", "x": shift, "y": 0.0, "z": 0.0},
                {"index": 2, "atom_id": "atom_c01", "element": "C", "x": 1.3 + shift, "y": 0.0, "z": 0.0},
            ],
            "atom_mapping": [
                {"candidate_atom_id": "atom_h01", "element": "H", "reactant_atom_id": "react_h01", "product_atom_id": "prod_h001"},
                {"candidate_atom_id": "atom_c01", "element": "C", "reactant_atom_id": "react_c01", "product_atom_id": "prod_c001"},
            ],
            "reaction_coordinate": {
                "forming_bonds": [{"atom_ids": ["atom_h01", "atom_c01"], "from_order": 0, "to_order": 1, "rationale": "Reviewed forming bond."}],
                "breaking_bonds": [], "collective_coordinates": [],
                "reviewed_description": "Hydrogen moves along the reviewed H-C coordinate.",
            },
            "electronic_state": {"charge": 0, "multiplicity": 1, "electronic_state_label": "closed_shell_singlet", "open_shell": False, "transition_metal": False, "reviewed": True},
            "stereochemical_binding_mode": {"stereochemical_channel": "channel_re", "binding_mode": "outer_sphere", "reviewed": True, "rationale": "Reviewed channel and binding mode."},
            "reactant_endpoint": refs["reactant"], "product_endpoint": refs["product"],
            "method_protocol_reference": refs["protocol"],
            "geometry_review": {"sanity": "passed", "connectivity_status": "passed", "clashes": {"status": "passed", "minimum_distance_angstrom": 1.3, "pairs": []}, "review_notes": ["No unresolved clash."]},
            "provenance": {"source_summary": "Exact reviewed target coordinates.", "source_artifacts": [refs["target"]], "precedence_review": self.precedence(strategy), "transfer_atom_mapping": [], "transformations": []},
            "confidence": {"level": "high", "basis": "Exact reviewed target lineage.", "limitations": ["A seed is not a transition state."]},
            "construction_policy": {"system_complexity": "complex", "chemical_hypothesis": hypothesis, "reaction_coordinate_lineage_id": f"lineage_{candidate_id}", "cosmetic_cartesian_permutations_used": False},
            "specialist_routing": {"required": False, "routes": [], "status": "not_applicable", "evidence": []},
            "review": {"status": "reviewed", "reviewer": "user_and_agent", "review_notes": ["Reviewed offline fixture."]},
        }

    def build(self, root: Path, source: dict, name: str) -> tuple[dict, Path]:
        source_path = root / f"{name}-source.json"
        write(source_path, source)
        candidate = CORE.build_candidate(source, source_path)
        path = root / f"{name}.json"
        write(path, candidate)
        return candidate, path

    def test_candidate_is_hash_bound_non_executable_and_method_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            candidate, path = self.build(root, self.source(root), "candidate")
            CORE.validate_candidate(candidate, path)
            self.assertFalse(candidate["calculation_ready"])
            self.assertFalse(candidate["executable"])
            self.assertTrue(candidate["no_submission_authorization"])
            self.assertTrue(candidate["portfolio_eligible"])
            self.assertEqual(candidate["strategy_rank"], 1)
            forged = copy.deepcopy(candidate)
            forged["method_protocol_reference"]["sha256"] = "0" * 64
            forged["payload_sha256"] = CORE.payload_sha256(forged)
            with self.assertRaisesRegex(CORE.ContractError, "method_protocol_reference file hash drift"):
                CORE.validate_candidate(forged, path)

    def test_ordered_provenance_and_cartesian_permutation_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self.source(root)
            source["seed_strategy"] = "de_novo"
            source["provenance"]["precedence_review"] = self.precedence("de_novo")
            source["provenance"]["precedence_review"][0]["status"] = "not_evaluated_lower_priority"
            path = root / "source.json"; write(path, source)
            with self.assertRaisesRegex(CORE.ContractError, "higher-priority strategy"):
                CORE.build_candidate(source, path)
            source = self.source(root)
            source["construction_policy"]["cosmetic_cartesian_permutations_used"] = True
            write(path, source)
            with self.assertRaisesRegex(CORE.ContractError, "Cartesian"):
                CORE.build_candidate(source, path)

    def test_open_shell_and_metal_cases_route_to_specialists(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self.source(root)
            source["electronic_state"].update({"multiplicity": 2, "electronic_state_label": "reviewed_doublet", "open_shell": True})
            source["specialist_routing"] = {"required": True, "routes": ["auto-g16-main-group-open-shell"], "status": "pending_specialist_review", "evidence": []}
            candidate, _ = self.build(root, source, "open-shell")
            self.assertFalse(candidate["portfolio_eligible"])
            source = self.source(root)
            source["electronic_state"]["transition_metal"] = True
            source["specialist_routing"] = {"required": True, "routes": [], "status": "pending_specialist_review", "evidence": []}
            path = root / "metal-source.json"; write(path, source)
            with self.assertRaisesRegex(CORE.ContractError, "specialist route"):
                CORE.build_candidate(source, path)

    def test_portfolio_accepts_one_plus_one_distinct_hypotheses(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, primary = self.build(root, self.source(root), "primary")
            _, backup = self.build(root, self.source(root, "seed_backup", "Stepwise ion-pair transfer", 0.4), "backup")
            source = {
                "portfolio_id": "portfolio_001", "target_id": "target_edge_01",
                "selections": [
                    {"path": primary.name, "role": "primary", "scientific_rationale": "Best exact-target lineage.", "user_reviewed": True},
                    {"path": backup.name, "role": "backup", "scientific_rationale": "Independent stepwise hypothesis.", "user_reviewed": True},
                ],
                "exception_review": {"approved": False, "new_scientific_rationale": None, "user_reviewed": False},
                "review": {"status": "reviewed", "reviewer": "user_and_agent", "review_notes": ["Bounded 1+1 portfolio."]},
            }
            path = root / "portfolio-source.json"; write(path, source)
            portfolio = CORE.build_portfolio(source, path)
            self.assertEqual([item["role"] for item in portfolio["entries"]], ["primary", "backup"])
            self.assertFalse(portfolio["executable"])

    def test_portfolio_rejects_same_hypothesis_cosmetics_and_unreviewed_expansion(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first_source = self.source(root)
            _, primary = self.build(root, first_source, "primary")
            second_source = self.source(root, "seed_cosmetic", first_source["construction_policy"]["chemical_hypothesis"], 0.5)
            second_source["construction_policy"]["reaction_coordinate_lineage_id"] = first_source["construction_policy"]["reaction_coordinate_lineage_id"]
            _, cosmetic = self.build(root, second_source, "cosmetic")
            source = {"portfolio_id": "portfolio_002", "target_id": "target_edge_01", "selections": [
                {"path": primary.name, "role": "primary", "scientific_rationale": "Primary.", "user_reviewed": True},
                {"path": cosmetic.name, "role": "backup", "scientific_rationale": "Only Cartesian displacement.", "user_reviewed": True}],
                "exception_review": {"approved": False, "new_scientific_rationale": None, "user_reviewed": False},
                "review": {"status": "reviewed", "reviewer": "chemist", "review_notes": []}}
            path = root / "portfolio-source.json"; write(path, source)
            with self.assertRaisesRegex(CORE.ContractError, "same-hypothesis cosmetic"):
                CORE.build_portfolio(source, path)
            third_source = self.source(root, "seed_third", "Third mechanistic hypothesis", 0.9)
            _, third = self.build(root, third_source, "third")
            fourth_source = self.source(root, "seed_fourth", "Fourth mechanistic hypothesis", 1.2)
            _, fourth = self.build(root, fourth_source, "fourth")
            source["selections"][1] = {"path": third.name, "role": "backup", "scientific_rationale": "Distinct backup.", "user_reviewed": True}
            source["selections"].append({"path": fourth.name, "role": "additional", "scientific_rationale": "Third seed.", "user_reviewed": True})
            with self.assertRaisesRegex(CORE.ContractError, "explicit exception review"):
                CORE.build_portfolio(source, path)

    def test_cli_help_exposes_builders_and_validation(self) -> None:
        result = subprocess.run([sys.executable, str(ROOT / "skills/auto-g16-ts-seed/scripts/ts_seed.py"), "--help"], text=True, capture_output=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        for command in ("build-candidate", "build-portfolio", "validate"):
            self.assertIn(command, result.stdout)


if __name__ == "__main__":
    unittest.main()
