#!/usr/bin/env python3
"""Offline tests for the pre-input three-tier Gaussian protocol gate."""

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
MODULE = ROOT / "skills" / "gaussian-rtwin-pbs" / "scripts" / "protocol_selection.py"
SPEC = importlib.util.spec_from_file_location("protocol_selection", MODULE)
assert SPEC and SPEC.loader
PROTOCOL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROTOCOL)


def dump(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def request_fixture(*, support_status: str = "supported") -> dict:
    return {
        "schema": "gaussian-calculation-request/1",
        "request_id": "neutral_main_group_opt_freq",
        "goal": "Compare three reviewed protocols before drafting an Opt/Freq input.",
        "claim_scope": "Geometry and harmonic-frequency evidence for one neutral closed-shell structure.",
        "task_types": ["optimization", "frequency"],
        "structure": {
            "sha256": "1" * 64,
            "formula": "C2H6O",
            "atom_count": 9,
            "elements": ["C", "H", "O"],
            "charge": 0,
            "multiplicity": 1,
        },
        "system_class": "main_group_closed_shell",
        "support_status": support_status,
        "calculation_ready": False,
        "no_submission_authorization": True,
    }


def method_profile(tier: str) -> dict:
    return {
        "profile_id": f"{tier}_opt_freq_profile",
        "stages": ["optimization", "frequency"],
        "functional_or_method": {
            "loose": "reviewed_screening_method",
            "standard": "reviewed_production_method",
            "strict": "reviewed_sensitivity_method",
        }[tier],
        "basis_stack": [
            {
                "elements": ["C", "H", "O"],
                "orbital_basis": {
                    "loose": "reviewed_screening_basis",
                    "standard": "reviewed_production_basis",
                    "strict": "reviewed_sensitivity_basis",
                }[tier],
                "ecp": None,
                "ecp_core_electrons": None,
                "aux_basis": None,
            }
        ],
        "dispersion": {"mode": "reviewed", "detail": f"{tier} dispersion decision"},
        "solvation": {
            "mode": "continuum",
            "model": "reviewed_continuum_model",
            "solvent_identity": "reviewed_solvent",
            "explicit_species": [],
        },
        "grid": {"loose": "reviewed_grid_l", "standard": "reviewed_grid_s", "strict": "reviewed_grid_x"}[tier],
        "scf": {
            "reference": "closed_shell",
            "convergence": f"reviewed_{tier}_convergence",
            "max_cycles": 128,
            "stability_check": "reviewed",
            "broken_symmetry_policy": "not_applicable",
        },
        "relativistic_treatment": "not_required_for_reviewed_elements",
        "software_compatibility": "reviewed_for_installed_g16",
    }


def option_fixture(tier: str, *, status: str = "selectable") -> dict:
    resource_tier = {"loose": "complex", "standard": "general", "strict": "simple"}[tier]
    unresolved = [] if status == "selectable" else [f"{tier} scientific protocol remains unresolved"]
    return {
        "option_id": f"neutral_main_group_{tier}",
        "tier": tier,
        "rigor_rank": PROTOCOL.RANKS[tier],
        "option_status": status,
        "purpose": {
            "loose": "Screening and diagnostic geometry only.",
            "standard": "Primary reviewed production geometry and frequencies.",
            "strict": "Independent method and numerical-sensitivity evidence.",
        }[tier],
        "applicability": {
            "task_types": ["optimization", "frequency"],
            "system_classes": ["main_group_closed_shell"],
            "prerequisites": ["reviewed identity and electronic state"],
            "exclusions": ["transition metal and open shell"],
            "fit_assessment": "reviewed" if status == "selectable" else "blocked",
            "reason": f"Explicit {tier} candidate for the fixture.",
        },
        "method_profiles": [method_profile(tier)] if status == "selectable" else [],
        "task_plan": [
            {
                "stage_type": "opt_freq",
                "profile_id": f"{tier}_opt_freq_profile",
                "required": True,
                "acceptance_checks": ["normal termination", "stationary point", "complete frequencies"],
            }
        ] if status == "selectable" else [],
        "validation_plan": {
            "minimum_acceptance": ["normal termination", "complete frequency parse"],
            "claim_limit": f"{tier} claim scope only",
        },
        "coverage_plan": {"structures": "one reviewed structure", "sensitivity": tier},
        "resources": {
            "resource_tier": resource_tier,
            "mem_gb": {"loose": 120, "standard": 50, "strict": 12}[tier],
            "cores": {"loose": 44, "standard": 22, "strict": 8}[tier],
            "job_count": {"loose": 1, "standard": 1, "strict": 3}[tier],
            "relative_cost_units": {"loose": 1, "standard": 3, "strict": 10}[tier],
            "assumptions": ["qualitative estimate only; no wall-time promise"],
        },
        "expected_cost": {
            "band": {"loose": "low", "standard": "medium", "strict": "high"}[tier],
            "drivers": ["basis size", "stage count", "sensitivity coverage"],
            "confidence": "qualitative",
        },
        "limitations": ["The tier label does not validate the chemical model."],
        "provenance": ["Explicit fixture values standing in for reviewed literature or benchmark evidence."],
        "unresolved": unresolved,
    }


def profiles_fixture(*, blocked_tier: str | None = None) -> dict:
    return {
        "schema": "gaussian-protocol-profile-source/1",
        "proposal_id": "neutral_main_group_three_tiers",
        "difficulty_assessment": {
            "class": "moderate",
            "drivers": ["frequency stage"],
            "evidence": ["reviewed request snapshot"],
            "review_status": "reviewed",
        },
        "common_constraints": {
            "temperature_k": 298.15,
            "standard_state": "1M",
            "comparison_scope": "Do not mix tiers in one final comparison.",
        },
        "options": [
            option_fixture(tier, status="blocked" if tier == blocked_tier else "selectable")
            for tier in PROTOCOL.TIERS
        ],
        "comparison_notes": [
            "Difficulty, protocol rigor and server resources are three independent decisions."
        ],
        "non_claims": [
            "Strict is not an accuracy guarantee and does not prove the chemical model.",
            "No option or selection authorizes input submission or a retry.",
        ],
    }


class ProtocolSelectionTests(unittest.TestCase):
    def build_files(self, root: Path, *, blocked_tier: str | None = None) -> tuple[Path, Path, Path, dict]:
        request_path = root / "request.json"
        profiles_path = root / "profiles.json"
        options_path = root / "options.json"
        dump(request_path, request_fixture())
        dump(profiles_path, profiles_fixture(blocked_tier=blocked_tier))
        options = PROTOCOL.build_options(request_path, profiles_path)
        PROTOCOL.write_new_json(options_path, options)
        return request_path, profiles_path, options_path, options

    def test_contract_schema_documents_are_closed_draft_2020_12_objects(self) -> None:
        contract_dir = ROOT / "contracts" / "gaussian-protocol"
        self.assertEqual({path.name for path in contract_dir.glob("*.schema.json")}, {"options.schema.json", "selection.schema.json"})
        for path in contract_dir.glob("*.schema.json"):
            document = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(document["$schema"], "https://json-schema.org/draft/2020-12/schema")
            self.assertEqual(document["type"], "object")
            self.assertFalse(document["additionalProperties"])

    def test_builds_exact_three_tiers_with_resources_orthogonal_to_rigor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, _, _, options = self.build_files(root)
            PROTOCOL.validate_options(options)
            by_tier = {item["tier"]: item for item in options["options"]}
            self.assertEqual(set(by_tier), set(PROTOCOL.TIERS))
            self.assertEqual(
                [by_tier[tier]["display_name"] for tier in PROTOCOL.TIERS],
                ["宽松", "标准", "严格"],
            )
            self.assertEqual(by_tier["loose"]["resources"]["resource_tier"], "complex")
            self.assertEqual(by_tier["strict"]["resources"]["resource_tier"], "simple")
            self.assertFalse(options["calculation_ready"])
            self.assertTrue(options["no_input_render_authorization"])
            self.assertFalse(list(root.glob("*.gjf")))
            self.assertFalse(list(root.glob("*.com")))

    def test_selection_is_hash_bound_and_only_authorizes_offline_draft(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, _, options_path, options = self.build_files(root)
            approval_path = root / "approval.json"
            dump(
                approval_path,
                {
                    "decision": "selected",
                    "tier": "standard",
                    "explicit_confirmation": True,
                    "decision_reason": "The user selected the displayed standard candidate.",
                },
            )
            selection = PROTOCOL.build_selection(options_path, "standard", approval_path)
            selection_path = root / "selection.json"
            PROTOCOL.write_new_json(selection_path, selection)
            _, _, selected = PROTOCOL.load_validated_selection(selection_path)
            self.assertEqual(selected["tier"], "standard")
            self.assertTrue(selection["authorizations"]["render_input_draft"])
            for action in ("submit", "create_server_directory", "retry", "irc", "cancel", "cleanup"):
                self.assertFalse(selection["authorizations"][action])

            tampered = copy.deepcopy(options)
            tampered["options"][1]["purpose"] += " changed"
            dump(options_path, tampered)
            with self.assertRaisesRegex(PROTOCOL.ContractError, "hash mismatch"):
                PROTOCOL.load_validated_selection(selection_path)

    def test_request_source_and_snapshot_are_hash_bound(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            request_path, _, _, options = self.build_files(root)
            changed = request_fixture()
            changed["goal"] += " changed"
            dump(request_path, changed)
            with self.assertRaisesRegex(PROTOCOL.ContractError, "request file hash mismatch"):
                PROTOCOL.validate_options(options)

    def test_repository_local_bindings_use_portable_relative_paths(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            root = Path(tmp)
            request_path, _, options_path, options = self.build_files(root)
            self.assertEqual(
                options["request_source"]["path"],
                str(request_path.resolve().relative_to(ROOT.resolve())),
            )

            approval_path = root / "approval.json"
            dump(
                approval_path,
                {
                    "decision": "selected",
                    "tier": "standard",
                    "explicit_confirmation": True,
                    "decision_reason": "Explicit portable-path selection.",
                },
            )
            selection = PROTOCOL.build_selection(options_path, "standard", approval_path)
            self.assertEqual(
                selection["options_source"]["path"],
                str(options_path.resolve().relative_to(ROOT.resolve())),
            )
            self.assertEqual(
                selection["approval_evidence"]["path"],
                str(approval_path.resolve().relative_to(ROOT.resolve())),
            )

    def test_missing_duplicate_or_identical_tiers_are_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            request_path = root / "request.json"
            profiles_path = root / "profiles.json"
            dump(request_path, request_fixture())
            profiles = profiles_fixture()

            missing = copy.deepcopy(profiles)
            missing["options"].pop()
            dump(profiles_path, missing)
            with self.assertRaisesRegex(PROTOCOL.ContractError, "exactly three"):
                PROTOCOL.build_options(request_path, profiles_path)

            duplicate = copy.deepcopy(profiles)
            duplicate["options"][2]["tier"] = "standard"
            duplicate["options"][2]["rigor_rank"] = 2
            dump(profiles_path, duplicate)
            with self.assertRaisesRegex(PROTOCOL.ContractError, "unique loose/standard/strict"):
                PROTOCOL.build_options(request_path, profiles_path)

            identical = copy.deepcopy(profiles)
            base = identical["options"][0]
            for tier in PROTOCOL.TIERS[1:]:
                target = next(item for item in identical["options"] if item["tier"] == tier)
                for field in ("purpose", "applicability", "method_profiles", "task_plan", "validation_plan", "coverage_plan"):
                    target[field] = copy.deepcopy(base[field])
                target["method_profiles"][0]["profile_id"] = f"{tier}_opt_freq_profile"
                target["task_plan"][0]["profile_id"] = f"{tier}_opt_freq_profile"
            dump(profiles_path, identical)
            with self.assertRaisesRegex(PROTOCOL.ContractError, "scientifically identical"):
                PROTOCOL.build_options(request_path, profiles_path)

    def test_selectable_option_requires_complete_basis_and_no_unresolved_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            request_path = root / "request.json"
            profiles_path = root / "profiles.json"
            dump(request_path, request_fixture())
            profiles = profiles_fixture()
            profiles["options"][1]["method_profiles"][0]["basis_stack"][0]["elements"] = ["C", "H"]
            dump(profiles_path, profiles)
            with self.assertRaisesRegex(PROTOCOL.ContractError, "coverage"):
                PROTOCOL.build_options(request_path, profiles_path)

            profiles = profiles_fixture()
            profiles["options"][1]["unresolved"] = ["solvent identity unresolved"]
            dump(profiles_path, profiles)
            with self.assertRaisesRegex(PROTOCOL.ContractError, "selectable option has unresolved"):
                PROTOCOL.build_options(request_path, profiles_path)

    def test_blocked_option_cannot_be_selected_and_unsupported_request_cannot_be_selectable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, _, options_path, _ = self.build_files(root, blocked_tier="strict")
            approval = root / "approval.json"
            dump(
                approval,
                {
                    "decision": "selected", "tier": "strict", "explicit_confirmation": True,
                    "decision_reason": "Attempted blocked selection.",
                },
            )
            with self.assertRaisesRegex(PROTOCOL.ContractError, "blocked option"):
                PROTOCOL.build_selection(options_path, "strict", approval)

            request_path = root / "unsupported-request.json"
            profiles_path = root / "unsupported-profiles.json"
            dump(request_path, request_fixture(support_status="unsupported"))
            dump(profiles_path, profiles_fixture())
            with self.assertRaisesRegex(PROTOCOL.ContractError, "unsupported request"):
                PROTOCOL.build_options(request_path, profiles_path)

            blocked_profiles = profiles_fixture(blocked_tier="strict")
            blocked_profiles["options"][2]["method_profiles"] = [method_profile("strict")]
            dump(profiles_path, blocked_profiles)
            with self.assertRaisesRegex(PROTOCOL.ContractError, "blocked option must not carry"):
                PROTOCOL.build_options(root / "request.json", profiles_path)

    def test_forbidden_runnable_fields_overwrite_and_cli_confirmation_are_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            request_path = root / "request.json"
            profiles_path = root / "profiles.json"
            dump(request_path, request_fixture())
            profiles = profiles_fixture()
            profiles["options"][0]["method_profiles"][0]["route"] = "#p forbidden"
            dump(profiles_path, profiles)
            with self.assertRaisesRegex(PROTOCOL.ContractError, "forbidden pre-input field"):
                PROTOCOL.build_options(request_path, profiles_path)

            dump(profiles_path, profiles_fixture())
            options_path = root / "options.json"
            PROTOCOL.write_new_json(options_path, PROTOCOL.build_options(request_path, profiles_path))
            with self.assertRaisesRegex(PROTOCOL.ContractError, "refusing to overwrite"):
                PROTOCOL.write_new_json(options_path, {"different": True})

            approval = root / "approval.json"
            dump(
                approval,
                {
                    "decision": "selected", "tier": "standard", "explicit_confirmation": True,
                    "decision_reason": "Explicit standard selection.",
                },
            )
            selection_path = root / "selection.json"
            completed = subprocess.run(
                [
                    sys.executable, str(MODULE), "select", str(options_path), "--tier", "standard",
                    "--approval-record", str(approval), "--output", str(selection_path),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 2)
            self.assertIn("requires --confirmed", completed.stderr)
            self.assertFalse(selection_path.exists())

    def test_cli_round_trip_is_offline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            request_path = root / "request.json"
            profiles_path = root / "profiles.json"
            options_path = root / "options.json"
            approval_path = root / "approval.json"
            selection_path = root / "selection.json"
            dump(request_path, request_fixture())
            dump(profiles_path, profiles_fixture())
            dump(
                approval_path,
                {
                    "decision": "selected", "tier": "standard", "explicit_confirmation": True,
                    "decision_reason": "Explicitly selected after reviewing all three candidates.",
                },
            )
            commands = (
                [sys.executable, str(MODULE), "propose", str(request_path), "--profiles", str(profiles_path), "--output", str(options_path)],
                [sys.executable, str(MODULE), "select", str(options_path), "--tier", "standard", "--approval-record", str(approval_path), "--confirmed", "--output", str(selection_path)],
                [sys.executable, str(MODULE), "validate", str(selection_path), "--options", str(options_path)],
            )
            for command in commands:
                completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
                self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
                self.assertFalse(json.loads(completed.stdout)["live_actions"])
            self.assertFalse(list(root.glob("*.gjf")))
            self.assertFalse(list(root.glob("*.com")))


if __name__ == "__main__":
    unittest.main()
