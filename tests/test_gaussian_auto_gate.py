#!/usr/bin/env python3
"""Fail-closed tests for the exact-input Auto-G16 runner."""

from __future__ import annotations

import importlib.util
import io
import json
import copy
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).parents[1]
SCRIPTS = ROOT / "skills" / "auto-g16-rtwin-pbs" / "scripts"
MODULE = SCRIPTS / "gaussian_auto.py"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location("gaussian_auto", MODULE)
assert SPEC and SPEC.loader
AUTO = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUTO)

CALC_TEST_PATH = ROOT / "tests" / "test_calculation_artifacts.py"
CALC_TEST_SPEC = importlib.util.spec_from_file_location("gaussian_auto_input_approval_fixture", CALC_TEST_PATH)
assert CALC_TEST_SPEC and CALC_TEST_SPEC.loader
CALC_TEST = importlib.util.module_from_spec(CALC_TEST_SPEC)
CALC_TEST_SPEC.loader.exec_module(CALC_TEST)


class GaussianAutoGateTests(unittest.TestCase):
    def write_ordinary_input(self, path: Path, *, z: int = 1) -> None:
        path.write_text(
            "%chk=ordinary.chk\n%mem=12GB\n%nprocshared=8\n"
            f"#p hf/sto-3g\n\nordinary\n\n0 1\nH 0 0 0\nH 0 0 {z}\n\n",
            encoding="utf-8",
        )

    def write_protected_ts_input(self, path: Path) -> None:
        path.write_text(
            "%chk=protected.chk\n%mem=12GB\n%nprocshared=8\n"
            "#p hf/sto-3g opt=(ts,calcfc) freq\n\nprotected\n\n0 1\nH 0 0 0\nH 0 0 1\n\n",
            encoding="utf-8",
        )

    def fake_input_approval(self, report: dict, work_kind: str = "ordinary") -> dict:
        return {
            "status": "validated_exact_input_approval",
            "schema": AUTO.transport.INPUT_APPROVAL_SCHEMA,
            "sha256": "f" * 64,
            "payload_sha256": "e" * 64,
            "input_sha256": report["input_sha256"],
            "work_kind": work_kind,
            "protocol_options_schema": "gaussian-protocol-options/1",
            "protocol_selection_schema": "gaussian-protocol-selection/1",
            "input_review_schema": AUTO.transport.INPUT_REVIEW_SCHEMA,
            "no_submission_authorization": True,
        }

    def write_live_v3(self, path: Path, report: dict, input_approval: dict, *, project: str = "ordinary") -> None:
        summary = AUTO.transport.live_approval_summary(
            project, report, None, input_approval["work_kind"], input_approval
        )
        schema, scope = AUTO.transport.expected_live_approval_scope(summary)
        path.write_text(json.dumps({
            "schema": schema, "decision": "approved", "explicit_confirmation": True,
            "scope": scope, "authorizations": self.approval_record()["authorizations"],
        }), encoding="utf-8")

    def make_generic_input_approval(self, root: Path) -> tuple[Path, Path, dict]:
        helper = CALC_TEST.CalculationArtifactTests(
            "test_every_emitted_adapter_document_validates_against_its_schema"
        )
        chain = helper.make_input_chain(root)
        input_path, _, _, _ = helper.build_handoff(root, chain)
        report = AUTO.transport.parse_gaussian(input_path)
        selected = AUTO.transport.protocol_selection.get_selected_option(
            chain["options"], chain["selection"]
        )
        profile = selected["method_profiles"][0]
        task = selected["task_plan"][0]
        protocol_binding = {
            "options_sha256": AUTO.transport.sha256(chain["options_path"]),
            "options_payload_sha256": chain["options"]["proposal_payload_sha256"],
            "selection_sha256": AUTO.transport.sha256(chain["selection_path"]),
            "selection_payload_sha256": chain["selection"]["selection_payload_sha256"],
            "selected_option": copy.deepcopy(chain["selection"]["selected_option"]),
            "used_profile_ids": [profile["profile_id"]],
            "used_tasks": [{
                "task_index": 0,
                "stage_type": task["stage_type"],
                "profile_id": task["profile_id"],
            }],
        }
        route_mapping = {
            "exact_route": report["route"],
            "method": {
                "route_value": "b3lyp", "profile_id": profile["profile_id"],
                "selected_value": profile["functional_or_method"], "human_confirmed": True,
            },
            "basis": {
                "route_value": "6-31g(d)", "profile_id": profile["profile_id"],
                "selected_value": copy.deepcopy(profile["basis_stack"]), "human_confirmed": True,
            },
            "solvent": {
                "route_value": "none", "profile_id": profile["profile_id"],
                "selected_value": copy.deepcopy(profile["solvation"]), "human_confirmed": True,
            },
            "scf": {
                "route_value": "default", "profile_id": profile["profile_id"],
                "selected_value": copy.deepcopy(profile["scf"]), "human_confirmed": True,
            },
            "tasks": [{
                "task_index": 0, "stage_type": task["stage_type"],
                "profile_id": task["profile_id"],
                "route_evidence": ["opt_ts", "frequency"],
                "human_confirmed": True,
            }],
            "explicit_confirmation": True,
        }
        draft = {
            "schema": AUTO.transport.INPUT_REVIEW_SCHEMA,
            "review_id": "generic_exact_single_guess_ts",
            "work_kind": "ts_pilot",
            "protocol_task_types": chain["selection"]["scope_binding"]["task_types"],
            "protocol_binding": protocol_binding,
            "route_profile_mapping": route_mapping,
            "protocol_family_completion": False,
            "approved_input": AUTO.transport._input_approval_facts(report),
            "decision": {
                "status": "accepted_exact_input", "explicit_confirmation": True,
                "reviewer": "offline fixture reviewer", "reviewed_at": "2026-07-17",
                "rationale": "Exact selected option, profiles, tasks, route and input reviewed.",
            },
            "calculation_ready": False,
            "no_submission_authorization": True,
            "payload_sha256": None,
        }
        draft_path = root / "generic-input-review-draft.json"
        review_path = root / "generic-input-review.json"
        receipt_path = root / "generic-input-approval.json"
        draft_path.write_text(json.dumps(draft), encoding="utf-8")
        AUTO.transport.finalize_input_review(draft_path, review_path)
        receipt = AUTO.transport.build_input_approval_receipt(
            chain["options_path"], chain["selection_path"], review_path,
            input_path, receipt_path, "generic-ts-receipt",
        )
        return input_path, receipt_path, receipt

    def approval_summary(self) -> dict:
        return {
            "project": "reviewed_job",
            "remote_workdir": "/home/user100/SDL/reviewed_job",
            "input_sha256": "a" * 64,
            "protocol": {
                "route": "#p hf/sto-3g opt",
                "mem": "12GB",
                "nproc": 8,
            },
            "charge": 0,
            "multiplicity": 1,
        }

    def approval_record(self) -> dict:
        return {
            "schema": "auto-g16-live-submission-approval/1",
            "decision": "approved",
            "explicit_confirmation": True,
            "scope": {
                "project": "reviewed_job",
                "remote_workdir": "/home/user100/SDL/reviewed_job",
                "input_sha256": "a" * 64,
                "route": "#p hf/sto-3g opt",
                "mem": "12GB",
                "nprocshared": 8,
                "charge": 0,
                "multiplicity": 1,
            },
            "authorizations": {
                "create_server_directory": True,
                "submit": True,
                "retry": False,
                "cancel": False,
                "cleanup": False,
                "delete_server_data": False,
            },
        }

    def test_raw_structure_cannot_bypass_protocol_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            process = subprocess.run(
                [
                    sys.executable,
                    str(MODULE),
                    "prepare",
                    "O",
                    "--project",
                    "water",
                    "--local-dir",
                    temp,
                ],
                text=True,
                capture_output=True,
            )
        self.assertNotEqual(process.returncode, 0)
        self.assertIn("accepts only an existing reviewed", process.stderr)

    def test_live_approval_must_match_exact_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "approval.json"
            approval = self.approval_record()
            path.write_text(json.dumps(approval), encoding="utf-8")
            self.assertEqual(
                AUTO.validate_live_approval(path, self.approval_summary()), approval
            )
            approval["scope"]["input_sha256"] = "b" * 64
            path.write_text(json.dumps(approval), encoding="utf-8")
            with self.assertRaises(SystemExit):
                AUTO.validate_live_approval(path, self.approval_summary())

    def test_shared_live_approval_validator_preserves_ordinary_v1_and_ts_v2(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            ordinary_path = root / "ordinary-approval.json"
            ordinary = self.approval_record()
            ordinary_path.write_text(json.dumps(ordinary), encoding="utf-8")
            self.assertEqual(
                AUTO.transport.validate_live_approval(ordinary_path, self.approval_summary()),
                ordinary,
            )

            ts_summary = {
                "scientific_maturity": {
                    "edge_id": "edge_activation", "node_id": "ts_candidate_primary",
                    "pilot": True, "maturity_gate_sha256": "b" * 64,
                    "maturity_gate_payload_sha256": "c" * 64,
                    "exact_action_authorization": {
                        "sha256": "d" * 64, "payload_sha256": "e" * 64,
                    },
                },
                **self.approval_summary(),
            }
            ts = self.approval_record()
            ts["schema"] = "auto-g16-live-submission-approval/2"
            ts["scope"]["scientific_maturity"] = {
                "edge_id": "edge_activation", "node_id": "ts_candidate_primary",
                "pilot": True, "maturity_gate_sha256": "b" * 64,
                "maturity_gate_payload_sha256": "c" * 64,
                "scientific_action_authorization_sha256": "d" * 64,
                "scientific_action_authorization_payload_sha256": "e" * 64,
            }
            ts_path = root / "ts-approval.json"
            ts_path.write_text(json.dumps(ts), encoding="utf-8")
            self.assertEqual(AUTO.transport.validate_live_approval(ts_path, ts_summary), ts)

    def test_low_level_ordinary_dry_run_is_explicitly_not_live_ready_without_input_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            gjf = root / "ordinary.gjf"
            gjf.write_text(
                "%chk=ordinary.chk\n%mem=12GB\n%nprocshared=8\n"
                "#p hf/sto-3g opt\n\nordinary\n\n0 1\nH 0 0 0\nH 0 0 1\n\n",
                encoding="utf-8",
            )
            report = AUTO.transport.parse_gaussian(gjf)
            summary = AUTO.transport.live_approval_summary("ordinary", report, None)
            approval = self.approval_record()
            approval["scope"] = {
                "project": summary["project"], "remote_workdir": summary["remote_workdir"],
                "input_sha256": summary["input_sha256"], "route": summary["protocol"]["route"],
                "mem": summary["protocol"]["mem"], "nprocshared": summary["protocol"]["nproc"],
                "charge": summary["charge"], "multiplicity": summary["multiplicity"],
            }
            approval_path = root / "approval.json"
            approval_path.write_text(json.dumps(approval), encoding="utf-8")
            args = AUTO.transport.build_parser().parse_args([
                "submit", str(gjf), "--project", "ordinary", "--local-dir", str(root / "bundle"),
                "--confirmed", "--dry-run", "--work-kind", "minimum",
                "--approval-record", str(approval_path),
            ])
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                args.func(args)
            plan = json.loads(stdout.getvalue())
            self.assertEqual(plan["live_approval"]["status"], "not_evaluated_missing_exact_input_approval")
            self.assertEqual(plan["input_approval"]["status"], "missing_required_for_live_submission")
            self.assertFalse(plan["live_submission_ready"])

    def test_low_level_live_submit_refuses_missing_exact_approval_before_network(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            gjf = root / "ordinary.gjf"
            gjf.write_text(
                "%chk=ordinary.chk\n%mem=12GB\n%nprocshared=8\n"
                "#p hf/sto-3g opt\n\nordinary\n\n0 1\nH 0 0 0\nH 0 0 1\n\n",
                encoding="utf-8",
            )
            args = AUTO.transport.build_parser().parse_args([
                "submit", str(gjf), "--project", "ordinary",
                "--local-dir", str(root / "bundle"), "--confirmed", "--work-kind", "ordinary",
            ])
            with mock.patch.object(
                AUTO.transport, "run", return_value=SimpleNamespace(stdout="")
            ) as remote_run:
                with self.assertRaises(SystemExit):
                    args.func(args)
            self.assertFalse(remote_run.called)

    def test_live_submit_requires_explicit_work_kind_before_network(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            gjf = root / "ordinary.gjf"
            gjf.write_text(
                "%chk=ordinary.chk\n%mem=12GB\n%nprocshared=8\n"
                "#p hf/sto-3g opt\n\nordinary\n\n0 1\nH 0 0 0\nH 0 0 1\n\n",
                encoding="utf-8",
            )
            args = AUTO.transport.build_parser().parse_args([
                "submit", str(gjf), "--project", "ordinary",
                "--local-dir", str(root / "bundle"), "--confirmed",
            ])
            with mock.patch.object(AUTO.transport, "run") as remote_run:
                with self.assertRaises(SystemExit) as stopped:
                    args.func(args)
            self.assertEqual(stopped.exception.code, 2)
            self.assertFalse(remote_run.called)

    def test_staged_bundle_explicitly_retains_no_submission_authority(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            gjf = root / "offline.gjf"
            gjf.write_text(
                "%chk=offline.chk\n%mem=12GB\n%nprocshared=8\n"
                "#p hf/sto-3g opt\n\noffline\n\n0 1\nH 0 0 0\nH 0 0 1\n\n",
                encoding="utf-8",
            )
            job, _ = AUTO.transport.stage(gjf, "offline", root / "bundle")
            self.assertFalse(job["calculation_ready"])
            self.assertTrue(job["no_submission_authorization"])

    def test_generic_receipt_replays_protocol_route_mapping_and_exact_input_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            input_path, receipt_path, receipt = self.make_generic_input_approval(root)
            report = AUTO.transport.parse_gaussian(input_path)
            validated = AUTO.transport.validate_input_approval(
                receipt_path, input_path, report, "ts_pilot"
            )
            self.assertEqual(validated["schema"], receipt["schema"])
            self.assertEqual(validated["input_sha256"], report["input_sha256"])
            self.assertEqual(validated["protocol_selection_schema"], "gaussian-protocol-selection/1")
            self.assertEqual(validated["input_review_schema"], "gaussian-input-draft-review/2")

            changed = root / "changed.gjf"
            changed.write_bytes(input_path.read_bytes() + b"\n")
            changed_report = dict(report, input_sha256=AUTO.transport.sha256(changed))
            with self.assertRaises(SystemExit):
                AUTO.transport.validate_input_approval(
                    receipt_path, changed, changed_report, "ts_pilot"
                )

    def test_generic_receipt_rejects_route_mapping_not_replayed_from_selected_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            input_path, receipt_path, _ = self.make_generic_input_approval(root)
            review_path = root / "generic-input-review.json"
            review = json.loads(review_path.read_text(encoding="utf-8"))
            review["route_profile_mapping"]["method"]["selected_value"] = "unselected_method"
            review["payload_sha256"] = AUTO.transport.contract_payload_sha256(review)
            review_path.write_text(json.dumps(review), encoding="utf-8")
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["sources"]["input_review"]["sha256"] = AUTO.transport.sha256(review_path)
            receipt["sources"]["input_review"]["size_bytes"] = review_path.stat().st_size
            receipt["sources"]["input_review"]["payload_sha256"] = review["payload_sha256"]
            receipt["payload_sha256"] = AUTO.transport.contract_payload_sha256(receipt)
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            with self.assertRaises(ValueError):
                AUTO.transport.validate_input_approval_receipt(
                    receipt_path, input_path=input_path,
                    report=AUTO.transport.parse_gaussian(input_path), work_kind="ts_pilot",
                )

    def test_generic_v1_blocks_specialist_input_families(self) -> None:
        base = {"route": "#p b3lyp/6-31g(d) opt=(ts,calcfc) freq", "geometry_source": "explicit_cartesian", "oldcheckpoint": None}
        self.assertEqual(AUTO.transport.input_approval_compatibility(base, "ts_pilot")["status"], "supported_generic_v1")
        cases = [
            ({**base, "route": "#p b3lyp/6-31g(d) opt=(qst2,calcfc) freq"}, "formal_ts"),
            ({**base, "route": "#p b3lyp/6-31g(d) irc=(forward)"}, "irc_forward"),
            ({**base, "route": "#p b3lyp/6-31g(d) geom=allcheck guess=read", "geometry_source": "geom_allcheck_from_reviewed_checkpoint", "oldcheckpoint": "ts.chk"}, "endpoint_reopt"),
            ({**base, "route": "#p b3lyp/6-31g(d) opt=modredundant"}, "ts_scan"),
        ]
        for report, work_kind in cases:
            with self.subTest(work_kind=work_kind):
                result = AUTO.transport.input_approval_compatibility(report, work_kind)
                self.assertEqual(result["status"], "blocked_missing_specialist_input_approval")

        ordinary = {"route": "#p b3lyp/6-31g(d)", "geometry_source": "explicit_cartesian", "oldcheckpoint": None}
        minimum = {**ordinary, "route": "#p b3lyp/6-31g(d) opt freq"}
        self.assertEqual(AUTO.transport.input_approval_compatibility(ordinary, "ordinary")["status"], "supported_generic_v1")
        self.assertEqual(AUTO.transport.input_approval_compatibility(minimum, "minimum")["status"], "supported_generic_v1")

    def test_generic_v1_blocks_link1_even_when_first_route_looks_ordinary(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "link1.gjf"
            path.write_text(
                "%chk=first.chk\n%mem=12GB\n%nprocshared=8\n#p hf/sto-3g\n\nfirst\n\n0 1\nH 0 0 0\nH 0 0 1\n\n"
                "--Link1--\n%chk=second.chk\n#p hf/sto-3g irc(forward) geom(allcheck) guess(read)\n\n",
                encoding="utf-8",
            )
            report = AUTO.transport.parse_gaussian(path)
            self.assertEqual(
                AUTO.transport.input_approval_compatibility(report, "ordinary")["status"],
                "blocked_missing_specialist_input_approval",
            )

    def test_no_equals_specialist_route_forms_are_fail_closed(self) -> None:
        base = {"geometry_source": "explicit_cartesian", "oldcheckpoint": None, "link1_count": 0, "route_section_count": 1}
        cases = [
            ("#p b3lyp/6-31g(d) opt(ts,calcfc)", "ts_pilot"),
            ("#p b3lyp/6-31g(d) opt(scan,modredundant)", "ordinary"),
            ("#p b3lyp/6-31g(d) geom(allcheck)", "ordinary"),
            ("#p b3lyp/6-31g(d) guess(read)", "ordinary"),
        ]
        for route, work_kind in cases:
            with self.subTest(route=route):
                result = AUTO.transport.input_approval_compatibility({**base, "route": route}, work_kind)
                self.assertNotEqual(result["status"], "supported_generic_v1")

    def test_later_protected_option_cannot_be_hidden_by_first_keyword_occurrence(self) -> None:
        route = "#p b3lyp/6-31g(d) opt=loose opt(ts,calcfc) freq"
        self.assertTrue(AUTO.transport.route_has_option(route, "opt", "ts"))
        report = {
            "route": route, "geometry_source": "explicit_cartesian", "oldcheckpoint": None,
            "link1_count": 0, "route_section_count": 1,
        }
        self.assertEqual(
            AUTO.transport.input_approval_compatibility(report, "ts_pilot")["status"],
            "blocked_missing_specialist_input_approval",
        )

    def test_route_task_predicates_reject_ts_without_frequency_and_arbitrary_evidence(self) -> None:
        consumed = [{"task_index": 0, "stage_type": "single_guess_ts_opt_freq", "profile_id": "ts_profile"}]
        mapping = [{
            "task_index": 0, "stage_type": "single_guess_ts_opt_freq", "profile_id": "ts_profile",
            "route_evidence": ["opt"], "human_confirmed": True,
        }]
        with self.assertRaises(ValueError):
            AUTO.transport._assert_consumed_tasks_match_route(
                "#p b3lyp/6-31g(d) opt(ts,calcfc)", consumed, mapping
            )

    def test_ordinary_cannot_downgrade_an_optimization_route(self) -> None:
        report = {
            "route": "#p b3lyp/6-31g(d) opt freq", "geometry_source": "explicit_cartesian",
            "oldcheckpoint": None, "link1_count": 0, "route_section_count": 1,
        }
        self.assertEqual(
            AUTO.transport.input_approval_compatibility(report, "ordinary")["status"],
            "work_kind_route_mismatch",
        )
        report["route"] = "#p b3lyp/6-31g(d) frequency"
        self.assertEqual(
            AUTO.transport.input_approval_compatibility(report, "ordinary")["status"],
            "work_kind_route_mismatch",
        )

    def test_protocol_structure_scope_requires_complete_formula_element_counts(self) -> None:
        request_structure = {
            "sha256": "a" * 64, "formula": "CH4", "atom_count": 5,
            "elements": ["C", "H"], "charge": 0, "multiplicity": 1,
        }
        report = {"charge": 0, "multiplicity": 1, "atom_count": 5, "elements": {"C": 2, "H": 3}}
        with self.assertRaises(ValueError):
            AUTO.transport._assert_protocol_structure_scope(request_structure, report)

    def test_input_approval_receipt_symlink_is_rejected_before_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            _, receipt_path, _ = self.make_generic_input_approval(root)
            link = root / "receipt-link.json"
            link.symlink_to(receipt_path.name)
            with self.assertRaises(ValueError):
                AUTO.transport.validate_input_approval_receipt(link)

    def test_direct_submit_rejects_historical_live_v1_and_v2_before_network(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            gjf = root / "ordinary.gjf"
            self.write_ordinary_input(gjf)
            report = AUTO.transport.parse_gaussian(gjf)
            fake = self.fake_input_approval(report)
            for schema in ("auto-g16-live-submission-approval/1", "auto-g16-live-submission-approval/2"):
                with self.subTest(schema=schema):
                    approval = self.approval_record()
                    approval["schema"] = schema
                    approval["scope"].update({
                        "project": "ordinary", "remote_workdir": "/home/user100/SDL/ordinary",
                        "input_sha256": report["input_sha256"], "route": report["route"],
                    })
                    approval_path = root / f"old-{schema.rsplit('/', 1)[1]}.json"
                    approval_path.write_text(json.dumps(approval), encoding="utf-8")
                    args = AUTO.transport.build_parser().parse_args([
                        "submit", str(gjf), "--project", "ordinary", "--local-dir", str(root / f"bundle-{schema[-1]}"),
                        "--work-kind", "ordinary", "--input-approval-record", str(root / "dummy.json"),
                        "--approval-record", str(approval_path), "--confirmed",
                    ])
                    with mock.patch.object(AUTO.transport, "validate_input_approval", return_value=fake), mock.patch.object(AUTO.transport, "run") as remote_run:
                        with self.assertRaises(SystemExit):
                            args.func(args)
                    self.assertFalse(remote_run.called)

    def test_protected_direct_and_wrapper_live_fail_before_first_run_by_explicit_gate_schema(self) -> None:
        """Neither maturity /1 plus live /3 nor currently blocked /2 can reach a runner."""
        for gate_version in (1, 2):
            for surface in ("direct", "wrapper"):
                with self.subTest(gate_version=gate_version, surface=surface), tempfile.TemporaryDirectory() as temp:
                    root = Path(temp)
                    gjf = root / "protected.gjf"
                    self.write_protected_ts_input(gjf)
                    gate = root / f"maturity-v{gate_version}.json"
                    gate.write_text(json.dumps({
                        "schema": f"gaussian-scientific-maturity-gate/{gate_version}",
                        "payload_sha256": "a" * 64,
                    }), encoding="utf-8")
                    common = [
                        str(gjf), "--project", "protected", "--local-dir", str(root / "bundle"),
                        "--confirmed", "--work-kind", "ts_pilot", "--pilot",
                        "--scientific-maturity", str(gate), "--edge-id", "edge_activation",
                        "--node-id", "ts_candidate_primary", "--input-approval-record", str(root / "input.json"),
                        "--approval-record", str(root / "live-v3.json"),
                    ]
                    args = (
                        AUTO.transport.build_parser().parse_args(["submit", *common])
                        if surface == "direct"
                        else AUTO.build_parser().parse_args(["auto", *common])
                    )
                    v1_owner = SimpleNamespace(validate_gate=mock.Mock(return_value={
                        "schema": "gaussian-scientific-maturity-gate/1", "payload_sha256": "a" * 64,
                    }))
                    v2_owner = SimpleNamespace(assert_action=mock.Mock(
                        side_effect=ValueError("minimum_candidate_input_result_lineage_unavailable_v2")
                    ))
                    with (
                        mock.patch.object(AUTO.transport, "_load_scientific_maturity", return_value=v1_owner) as load_v1,
                        mock.patch.object(AUTO.transport, "_load_scientific_maturity_v2", return_value=v2_owner) as load_v2,
                        mock.patch.object(AUTO.transport, "run") as transport_run,
                        mock.patch.object(AUTO.subprocess, "run") as wrapper_run,
                        self.assertRaises(SystemExit),
                    ):
                        args.func(args)
                    self.assertFalse(transport_run.called)
                    self.assertFalse(wrapper_run.called)
                    self.assertEqual(load_v1.called, gate_version == 1)
                    self.assertEqual(load_v2.called, gate_version == 2)

    def test_ordinary_wrapper_dry_run_reaches_only_the_mocked_local_transport(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            gjf = root / "ordinary.gjf"
            self.write_ordinary_input(gjf)
            args = AUTO.build_parser().parse_args([
                "auto", str(gjf), "--project", "ordinary", "--local-dir", str(root / "bundle"),
                "--confirmed", "--dry-run", "--work-kind", "ordinary",
            ])
            completed = SimpleNamespace(returncode=0)
            with (
                mock.patch.object(AUTO.transport, "run") as network_run,
                mock.patch.object(AUTO.subprocess, "run", return_value=completed) as local_transport,
                redirect_stdout(io.StringIO()),
            ):
                args.func(args)
            self.assertFalse(network_run.called)
            local_transport.assert_called_once()
            self.assertIn("--dry-run", local_transport.call_args.args[0])
            self.assertIn("ordinary", local_transport.call_args.args[0])

    def test_ordinary_and_minimum_live_paths_complete_with_every_network_run_mocked(self) -> None:
        for work_kind in ("ordinary", "minimum"):
            with self.subTest(work_kind=work_kind), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                gjf = root / f"{work_kind}.gjf"
                route = "#p hf/sto-3g" if work_kind == "ordinary" else "#p hf/sto-3g opt freq"
                gjf.write_text(
                    f"%chk={work_kind}.chk\n%mem=12GB\n%nprocshared=8\n{route}\n\n{work_kind}\n\n0 1\nH 0 0 0\nH 0 0 1\n\n",
                    encoding="utf-8",
                )
                report = AUTO.transport.parse_gaussian(gjf)
                input_approval = self.fake_input_approval(report, work_kind)
                bundle = root / "bundle"
                args = AUTO.transport.build_parser().parse_args([
                    "submit", str(gjf), "--project", work_kind, "--local-dir", str(bundle),
                    "--confirmed", "--work-kind", work_kind,
                    "--input-approval-record", str(root / "input.json"),
                    "--approval-record", str(root / "live-v3.json"),
                ])

                def mocked_network(_command, *, input_bytes=None, check=True):
                    if input_bytes and b"qsub" in input_bytes:
                        return SimpleNamespace(stdout="123.server\n", stderr="", returncode=0)
                    hashes = []
                    if bundle.is_dir():
                        hashes = [
                            f"{path.name} {AUTO.transport.sha256(path)}"
                            for path in bundle.iterdir() if path.is_file() and path.name != "job.json"
                        ]
                    return SimpleNamespace(stdout="\n".join(hashes), stderr="", returncode=0)

                stdout = io.StringIO()
                with (
                    mock.patch.object(AUTO.transport, "validate_input_approval", return_value=input_approval),
                    mock.patch.object(AUTO.transport, "validate_live_approval_binding", return_value=({"schema": "auto-g16-live-submission-approval/3"}, "d" * 64)),
                    mock.patch.object(AUTO.transport, "run", side_effect=mocked_network) as network_run,
                    redirect_stdout(stdout),
                ):
                    args.func(args)
                result = json.loads(stdout.getvalue())
                self.assertTrue(result["submitted"])
                self.assertEqual(result["job_id"], "123.server")
                self.assertGreater(network_run.call_count, 0)

    def test_submit_uses_one_snapshot_when_source_changes_after_input_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            gjf = root / "ordinary.gjf"
            self.write_ordinary_input(gjf, z=1)
            original = gjf.read_bytes()
            report = AUTO.transport.parse_gaussian(gjf)
            fake = self.fake_input_approval(report)
            live = root / "live-v3.json"
            self.write_live_v3(live, report, fake)
            args = AUTO.transport.build_parser().parse_args([
                "submit", str(gjf), "--project", "ordinary", "--local-dir", str(root / "bundle"),
                "--work-kind", "ordinary", "--input-approval-record", str(root / "dummy.json"),
                "--approval-record", str(live), "--confirmed", "--dry-run",
            ])
            def mutate_after_validation(*_args, **_kwargs):
                self.write_ordinary_input(gjf, z=2)
                return fake
            stdout = io.StringIO()
            with mock.patch.object(AUTO.transport, "validate_input_approval", side_effect=mutate_after_validation), redirect_stdout(stdout):
                args.func(args)
            plan = json.loads(stdout.getvalue())
            self.assertEqual(plan["input_sha256"], AUTO.transport.hashlib.sha256(original).hexdigest())
            self.assertEqual((root / "bundle" / gjf.name).read_bytes(), original)

    def test_submit_rechecks_staged_bytes_before_dry_run_or_network(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            gjf = root / "ordinary.gjf"
            self.write_ordinary_input(gjf)
            report = AUTO.transport.parse_gaussian(gjf)
            fake = self.fake_input_approval(report)
            live = root / "live-v3.json"
            self.write_live_v3(live, report, fake)
            args = AUTO.transport.build_parser().parse_args([
                "submit", str(gjf), "--project", "ordinary", "--local-dir", str(root / "bundle"),
                "--work-kind", "ordinary", "--input-approval-record", str(root / "dummy.json"),
                "--approval-record", str(live), "--confirmed", "--dry-run",
            ])
            real_stage = AUTO.transport.stage
            def mutating_stage(*stage_args, **stage_kwargs):
                job, files = real_stage(*stage_args, **stage_kwargs)
                staged = Path(stage_args[2]) / job["input"]
                staged.chmod(0o600)
                self.write_ordinary_input(staged, z=9)
                return job, files
            with mock.patch.object(AUTO.transport, "validate_input_approval", return_value=fake), mock.patch.object(AUTO.transport, "stage", side_effect=mutating_stage):
                with self.assertRaises(SystemExit):
                    args.func(args)

    def test_live_v3_scope_binds_work_kind_and_input_approval_receipt(self) -> None:
        summary = self.approval_summary()
        summary["work_kind"] = "minimum"
        summary["input_approval"] = {
            "schema": AUTO.transport.INPUT_APPROVAL_SCHEMA,
            "sha256": "f" * 64,
            "payload_sha256": "e" * 64,
            "input_sha256": summary["input_sha256"],
            "work_kind": "minimum",
        }
        expected = AUTO.transport.expected_live_approval_scope(summary)
        self.assertEqual(expected[0], "auto-g16-live-submission-approval/3")
        self.assertEqual(expected[1]["work_kind"], "minimum")
        self.assertEqual(expected[1]["input_approval"]["sha256"], "f" * 64)
        with tempfile.TemporaryDirectory() as temp:
            approval = {
                "schema": expected[0], "decision": "approved", "explicit_confirmation": True,
                "scope": expected[1], "authorizations": self.approval_record()["authorizations"],
            }
            path = Path(temp) / "live-v3.json"
            path.write_text(json.dumps(approval), encoding="utf-8")
            self.assertEqual(AUTO.transport.validate_live_approval(path, summary), approval)

    def test_multi_stage_protocol_allows_one_input_to_bind_a_nonempty_task_subset(self) -> None:
        binding = {
            "options_sha256": "a" * 64, "options_payload_sha256": "b" * 64,
            "selection_sha256": "c" * 64, "selection_payload_sha256": "d" * 64,
            "selected_option": {"tier": "standard", "option_id": "multi", "option_payload_sha256": "e" * 64},
            "used_profile_ids": ["sp_profile"],
            "used_tasks": [{"task_index": 2, "stage_type": "single_point", "profile_id": "sp_profile"}],
        }
        self.assertEqual(AUTO.transport._validate_protocol_binding_shape(binding), binding)

    def test_multi_stage_protocol_rejects_duplicate_consumed_task_indices(self) -> None:
        binding = {
            "options_sha256": "a" * 64, "options_payload_sha256": "b" * 64,
            "selection_sha256": "c" * 64, "selection_payload_sha256": "d" * 64,
            "selected_option": {"tier": "standard", "option_id": "multi", "option_payload_sha256": "e" * 64},
            "used_profile_ids": ["sp_profile"],
            "used_tasks": [
                {"task_index": 2, "stage_type": "single_point", "profile_id": "sp_profile"},
                {"task_index": 2, "stage_type": "single_point", "profile_id": "sp_profile"},
            ],
        }
        with self.assertRaises(ValueError):
            AUTO.transport._validate_protocol_binding_shape(binding)

    def test_immutable_json_publication_never_clobbers_existing_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "immutable.json"
            target.write_text('{"original":true}\n', encoding="utf-8")
            with self.assertRaises(ValueError):
                AUTO.transport.publish_new_json(target, {"replacement": True})
            self.assertEqual(target.read_text(encoding="utf-8"), '{"original":true}\n')

    def test_generic_review_and_receipt_validate_against_closed_schemas(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            _, receipt_path, _ = self.make_generic_input_approval(root)
            pairs = [
                (root / "generic-input-review.json", ROOT / "contracts/rtwin-pbs/input-draft-review-v2.schema.json"),
                (receipt_path, ROOT / "contracts/rtwin-pbs/input-approval-receipt.schema.json"),
            ]
            for artifact_path, schema_path in pairs:
                schema = json.loads(schema_path.read_text(encoding="utf-8"))
                document = json.loads(artifact_path.read_text(encoding="utf-8"))
                CALC_TEST.ADAPTER.asym_contract.validate_schema_document(schema)
                CALC_TEST.ADAPTER.asym_contract._validate_schema_instance(document, schema, schema)


if __name__ == "__main__":
    unittest.main()
