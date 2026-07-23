#!/usr/bin/env python3
"""Offline contract tests for F-only constrained preoptimization approval."""

from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).parents[1]
SCRIPTS = ROOT / "skills" / "auto-g16-rtwin-pbs" / "scripts"
sys.path.insert(0, str(SCRIPTS))


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PBS = load("fixed_constraint_pbs", SCRIPTS / "gaussian_rtwin_pbs.py")
PROTOCOL = load("fixed_constraint_protocol", SCRIPTS / "protocol_selection.py")
PROTOCOL_TEST = load(
    "fixed_constraint_protocol_fixtures", ROOT / "tests" / "test_protocol_selection.py"
)


def dump(path: Path, value: dict) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


class FixedConstraintInputApprovalTests(unittest.TestCase):
    def test_one_command_help_names_specialist_receipt_and_live_contract(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "gaussian_auto.py"), "auto", "--help"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        normalized_help = " ".join(result.stdout.split()).replace("- ", "-")
        self.assertIn("gaussian-input-approval-receipt/4", normalized_help)
        self.assertIn("/9, /10, /11, or /12", normalized_help)

    def build_protocol(self, root: Path) -> tuple[Path, Path, dict, dict]:
        request = PROTOCOL_TEST.request_fixture()
        request.update(
            {
                "request_id": "h2_fixed_constraint_preopt",
                "goal": "Review one F-only constrained preoptimization.",
                "claim_scope": (
                    "Seed relaxation only; never a minimum, frequency, scan, TS, or path claim."
                ),
                "task_types": ["constrained_geometry_preoptimization"],
            }
        )
        request["structure"] = {
            "sha256": "1" * 64,
            "formula": "H2",
            "atom_count": 2,
            "elements": ["H"],
            "charge": 0,
            "multiplicity": 1,
        }
        profiles = PROTOCOL_TEST.profiles_fixture()
        profiles["proposal_id"] = "h2_fixed_constraint_three_tiers"
        for option in profiles["options"]:
            profile = option["method_profiles"][0]
            profile_id = f"{option['tier']}_fixed_constraint_preopt"
            option["option_id"] = profile_id
            option["applicability"]["task_types"] = [
                "constrained_geometry_preoptimization"
            ]
            profile.update(
                {
                    "profile_id": profile_id,
                    "stages": ["constrained_geometry_preoptimization"],
                    "functional_or_method": "HF",
                    "basis_stack": [
                        {
                            "elements": ["H"],
                            "orbital_basis": "STO-3G",
                            "ecp": None,
                            "ecp_core_electrons": None,
                            "aux_basis": None,
                        }
                    ],
                    "solvation": {
                        "mode": "gas_phase",
                        "model": "none",
                        "solvent_identity": "none",
                        "explicit_species": [],
                    },
                }
            )
            option["task_plan"] = [
                {
                    "stage_type": "constrained_geometry_preoptimization",
                    "profile_id": profile_id,
                    "required": True,
                    "acceptance_checks": [
                        "normal termination",
                        "exact F-only constraints retained",
                    ],
                }
            ]
            option["resources"].update(
                {"resource_tier": "general", "mem_gb": 50, "cores": 22}
            )
        request_path = root / "request.json"
        profiles_path = root / "profiles.json"
        options_path = root / "options.json"
        approval_path = root / "selection-decision.json"
        selection_path = root / "selection.json"
        dump(request_path, request)
        dump(profiles_path, profiles)
        options = PROTOCOL.build_options(request_path, profiles_path)
        PROTOCOL.write_new_json(options_path, options)
        dump(
            approval_path,
            {
                "decision": "selected",
                "tier": "standard",
                "explicit_confirmation": True,
                "decision_reason": "Offline fixture selects the reviewed standard protocol.",
            },
        )
        selection = PROTOCOL.build_selection(
            options_path, "standard", approval_path
        )
        PROTOCOL.write_new_json(selection_path, selection)
        return options_path, selection_path, options, selection

    def write_input(
        self,
        path: Path,
        *,
        route: str = "#p HF/STO-3G Opt=(ModRedundant,CalcFC,MaxCycles=40)",
        tail: str = "B 1 2 F\n",
    ) -> None:
        path.write_text(
            "%chk=fixed.chk\n%mem=50GB\n%nprocshared=22\n"
            f"{route}\n\nfixed constraint fixture\n\n0 1\n"
            "H 0.000000 0.000000 0.000000\n"
            "H 0.000000 0.000000 0.740000\n\n"
            f"{tail}\n",
            encoding="utf-8",
        )

    def build_review(
        self,
        root: Path,
        input_path: Path,
        options_path: Path,
        selection_path: Path,
        options: dict,
        selection: dict,
    ) -> Path:
        report = PBS.parse_gaussian(input_path)
        selected = PROTOCOL.get_selected_option(options, selection)
        task = selected["task_plan"][0]
        profile = selected["method_profiles"][0]
        review = {
            "schema": PBS.FIXED_CONSTRAINT_INPUT_REVIEW_SCHEMA,
            "review_id": "fixed_constraint_exact_input_review",
            "work_kind": "minimum",
            "protocol_task_types": selection["scope_binding"]["task_types"],
            "protocol_binding": {
                "options_sha256": PBS.sha256(options_path),
                "options_payload_sha256": options["proposal_payload_sha256"],
                "selection_sha256": PBS.sha256(selection_path),
                "selection_payload_sha256": selection["selection_payload_sha256"],
                "selected_option": copy.deepcopy(selection["selected_option"]),
                "used_profile_ids": [profile["profile_id"]],
                "used_tasks": [
                    {
                        "task_index": 0,
                        "stage_type": task["stage_type"],
                        "profile_id": task["profile_id"],
                    }
                ],
            },
            "route_profile_mapping": {
                "exact_route": report["route"],
                "method": {
                    "route_value": "HF",
                    "profile_id": profile["profile_id"],
                    "selected_value": profile["functional_or_method"],
                    "human_confirmed": True,
                },
                "basis": {
                    "route_value": "STO-3G",
                    "profile_id": profile["profile_id"],
                    "selected_value": profile["basis_stack"],
                    "human_confirmed": True,
                },
                "solvent": {
                    "route_value": "none",
                    "profile_id": profile["profile_id"],
                    "selected_value": profile["solvation"],
                    "human_confirmed": True,
                },
                "scf": {
                    "route_value": "default",
                    "profile_id": profile["profile_id"],
                    "selected_value": profile["scf"],
                    "human_confirmed": True,
                },
                "tasks": [
                    {
                        "task_index": 0,
                        "stage_type": task["stage_type"],
                        "profile_id": task["profile_id"],
                        "route_evidence": ["fixed_constraint_preoptimization"],
                        "human_confirmed": True,
                    }
                ],
                "explicit_confirmation": True,
            },
            "protocol_family_completion": False,
            "approved_input": PBS._input_approval_facts(report),
            "decision": {
                "status": "accepted_exact_input",
                "explicit_confirmation": True,
                "reviewer": "offline fixture reviewer",
                "reviewed_at": "2026-07-23T00:00:00Z",
                "rationale": "Exact input and F-only constraint set reviewed.",
            },
            "calculation_ready": False,
            "no_submission_authorization": True,
            "payload_sha256": None,
        }
        draft_path = root / "input-review-draft.json"
        review_path = root / "input-review.json"
        dump(draft_path, review)
        PBS.finalize_fixed_constraint_input_review(draft_path, review_path)
        return review_path

    def build_chain(self, root: Path):
        options_path, selection_path, options, selection = self.build_protocol(root)
        input_path = root / "fixed.gjf"
        self.write_input(input_path)
        review_path = self.build_review(
            root,
            input_path,
            options_path,
            selection_path,
            options,
            selection,
        )
        audit_path = root / "fixed-audit.json"
        receipt_path = root / "fixed-receipt.json"
        audit = PBS.build_fixed_constraint_audit(
            input_path, review_path, audit_path, "fixed-audit-1"
        )
        receipt = PBS.build_input_approval_receipt(
            options_path,
            selection_path,
            review_path,
            input_path,
            receipt_path,
            "fixed-receipt-1",
            fixed_constraint_audit_path=audit_path,
        )
        return input_path, review_path, audit_path, audit, receipt_path, receipt

    def test_builds_replays_and_projects_receipt_v4_to_live_v12(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            input_path, _, audit_path, audit, receipt_path, receipt = self.build_chain(
                root
            )
            report = PBS.parse_gaussian(input_path)
            self.assertEqual(
                PBS.classify_protected_input(report), "fixed_constraint_preopt"
            )
            self.assertEqual(report["fixed_constraint_directive_count"], 1)
            self.assertTrue(report["has_only_fixed_constraint_directives"])
            self.assertEqual(audit["schema"], PBS.FIXED_CONSTRAINT_AUDIT_SCHEMA)
            self.assertEqual(
                receipt["schema"], PBS.FIXED_CONSTRAINT_INPUT_APPROVAL_SCHEMA
            )
            validated = PBS.validate_input_approval(
                receipt_path, input_path, report, "minimum"
            )
            self.assertEqual(
                validated["specialist_owner_binding"]["constraint_count"], 1
            )
            summary = PBS.live_approval_summary(
                "fixedjob", report, None, "minimum", validated
            )
            summary["execution"] = {
                "batch_id": "batch",
                "review_sha256": "1" * 64,
                "scientific_task_id": "scientific-task-" + "2" * 64,
                "attempt_id": "qsub-attempt-" + "3" * 64,
                "idempotency_key": "fixed-attempt",
                "estimated_core_hours": 4.0,
                "estimated_core_hours_evidence": {
                    "source": "offline-fixture",
                    "sha256": "4" * 64,
                },
                "resource_binding": {
                    "policy_id": "policy",
                    "policy_sha256": "5" * 64,
                    "gate_id": "gate",
                    "gate_sha256": "6" * 64,
                    "resource_tier": "general",
                    "cores": 22,
                    "memory_gb": 50,
                    "walltime_seconds": 86400,
                },
            }
            schema, scope = PBS.expected_live_approval_scope(summary)
            self.assertEqual(schema, PBS.FIXED_CONSTRAINT_LIVE_APPROVAL_V12_SCHEMA)
            self.assertEqual(
                scope["fixed_constraint_owner"]["constraints_sha256"],
                audit["constraints_sha256"],
            )
            now = datetime.now(timezone.utc)
            live = {
                "schema": schema,
                "approval_id": "fixed-constraint-live-once",
                "approver_identity": "offline fixture operator",
                "approved_at": (now - timedelta(minutes=1)).isoformat(),
                "expires_at": (now + timedelta(minutes=30)).isoformat(),
                "decision": "approved",
                "explicit_confirmation": True,
                "scope": scope,
                "revocation": {
                    "revoked": False,
                    "revoked_at": None,
                    "reason": None,
                },
                "consumption": {"single_use": True, "consumed": False},
                "authorizations": {
                    "create_server_directory": True,
                    "submit": True,
                    "retry": False,
                    "cancel": False,
                    "cleanup": False,
                    "delete_server_data": False,
                },
            }
            self.assertEqual(
                PBS._validate_live_approval_document(live, summary), live
            )
            wrong_generation = copy.deepcopy(live)
            wrong_generation["schema"] = PBS.LIVE_APPROVAL_V9_SCHEMA
            with self.assertRaises(SystemExit):
                PBS._validate_live_approval_document(wrong_generation, summary)

    def test_generic_v1_remains_closed_for_fixed_constraint_input(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "fixed.gjf"
            self.write_input(path)
            report = PBS.parse_gaussian(path)
            compatibility = PBS.input_approval_compatibility(report, "minimum")
            self.assertEqual(
                compatibility["status"],
                "blocked_missing_fixed_constraint_input_approval",
            )
            self.assertEqual(
                compatibility["required_schema"],
                PBS.FIXED_CONSTRAINT_INPUT_APPROVAL_SCHEMA,
            )
            ordinary = dict(
                report,
                route="#p HF/STO-3G Opt",
                has_only_fixed_constraint_directives=False,
                fixed_constraint_directive_count=0,
                fixed_constraint_directives=[],
            )
            self.assertEqual(
                PBS.input_approval_compatibility(ordinary, "minimum")["status"],
                "supported_generic_v1",
            )

    def test_scan_and_non_f_tail_never_enter_fixed_constraint_owner(self) -> None:
        cases = (
            ("B 1 2 S 10 0.10\n", "relaxed scan"),
            ("B 1 2 F\nB 1 2 F\n", "duplicate"),
            ("B 1 3 F\n", "out of range"),
            ("X 1 F\n", "unsupported coordinate"),
            ("B 1 2 0.80 F\n", "embedded target value"),
        )
        for tail, label in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temp:
                root = Path(temp).resolve()
                options_path, selection_path, options, selection = self.build_protocol(
                    root
                )
                input_path = root / "rejected.gjf"
                self.write_input(input_path, tail=tail)
                report = PBS.parse_gaussian(input_path)
                if label == "relaxed scan":
                    self.assertTrue(report["has_relaxed_scan_directive"])
                self.assertNotEqual(
                    PBS.fixed_constraint_input_compatibility(report, "minimum")[
                        "status"
                    ],
                    "supported_fixed_constraint_v1",
                )
                review_path = self.build_review(
                    root,
                    input_path,
                    options_path,
                    selection_path,
                    options,
                    selection,
                )
                with self.assertRaises(ValueError):
                    PBS.build_fixed_constraint_audit(
                        input_path,
                        review_path,
                        root / "rejected-audit.json",
                        "rejected",
                    )

    def test_freq_ts_checkpoint_and_link1_remain_blocked(self) -> None:
        routes = (
            "#p HF/STO-3G Opt=(ModRedundant,CalcFC) Freq",
            "#p HF/STO-3G Opt=(ModRedundant,TS,CalcFC)",
            "#p HF/STO-3G Opt=(ModRedundant,QST2,CalcFC)",
            "#p HF/STO-3G IRC=(Forward) Opt=ModRedundant",
            "#p HF/STO-3G Opt=(ModRedundant,Restart)",
            "#p HF/STO-3G Opt=(ModRedundant,AddRedundant)",
            "#p HF/STO-3G Opt=ModRedundant Geom=Check Guess=Read",
        )
        for route in routes:
            with self.subTest(route=route), tempfile.TemporaryDirectory() as temp:
                path = Path(temp) / "rejected.gjf"
                self.write_input(path, route=route)
                report = PBS.parse_gaussian(path)
                self.assertNotEqual(
                    PBS.fixed_constraint_input_compatibility(report, "minimum")[
                        "status"
                    ],
                    "supported_fixed_constraint_v1",
                )
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "link1.gjf"
            self.write_input(path)
            path.write_text(
                path.read_text(encoding="utf-8")
                + "--Link1--\n%chk=second.chk\n%mem=50GB\n%nprocshared=22\n"
                "#p HF/STO-3G\n\nsecond\n\n0 1\nH 0 0 0\nH 0 0 1\n\n",
                encoding="utf-8",
            )
            report = PBS.parse_gaussian(path)
            self.assertNotEqual(
                PBS.fixed_constraint_input_compatibility(report, "minimum")[
                    "status"
                ],
                "supported_fixed_constraint_v1",
            )

    def test_audit_and_receipt_tampering_fail_replay(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            input_path, _, audit_path, _, receipt_path, _ = self.build_chain(root)
            audit = json.loads(audit_path.read_text(encoding="utf-8"))
            audit["constraints"][0]["atom_indices"] = [2, 1]
            audit["constraints_sha256"] = PBS.canonical_value_sha256(
                audit["constraints"]
            )
            audit["payload_sha256"] = PBS.contract_payload_sha256(audit)
            dump(audit_path, audit)
            with self.assertRaises(ValueError):
                PBS.validate_fixed_constraint_audit(audit_path)
            with self.assertRaises(ValueError):
                PBS.validate_input_approval_receipt(
                    receipt_path,
                    input_path=input_path,
                    report=PBS.parse_gaussian(input_path),
                    work_kind="minimum",
                )


if __name__ == "__main__":
    unittest.main()
