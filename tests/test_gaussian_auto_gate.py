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

    def test_submit_wrapper_allows_slow_transport_transaction_without_umbrella_timeout(self) -> None:
        args = SimpleNamespace(
            confirmed=True, dry_run=True, work_kind="ordinary", project="safejob",
            local_dir="/synthetic/local", scientific_maturity=None, edge_id=None,
            node_id=None, pilot=False, scientific_action_authorization=None,
            input_approval_record=None, approval_record=None, watch=False,
            mac_ssh_config=None, rtwin_alias=None, windows_root=None,
            windows_server_config=None, server_alias=None,
            execution_batch_ledger=None, scientific_task_id=None, idempotency_key=None,
            estimated_core_hours=None, estimated_core_hours_evidence_source=None,
            estimated_core_hours_evidence_sha256=None, resource_policy=None,
            resource_gate=None, scheduler_resource_snapshot=None, resource_tier=None,
            resource_cores=None, resource_memory_gb=None, walltime_seconds=None,
        )
        summary = {
            "gaussian_input": "/synthetic/input.gjf",
            "input_approval": {"status": "validated_exact_input_approval"},
        }
        logical_elapsed = {"seconds": 0}

        def slow_submit(command, **kwargs):
            logical_elapsed["seconds"] = 61
            self.assertNotIn("timeout", kwargs)
            return subprocess.CompletedProcess(command, 0)

        with mock.patch.object(AUTO, "prepare_source", return_value=summary), \
             mock.patch.object(AUTO.subprocess, "run", side_effect=slow_submit) as submit:
            AUTO.command_auto(args)
        self.assertEqual(logical_elapsed["seconds"], 61)
        self.assertEqual(submit.call_count, 1)

        uncertain = subprocess.TimeoutExpired(["synthetic-submit"], 61)
        with mock.patch.object(AUTO, "prepare_source", return_value=summary), \
             mock.patch.object(AUTO.subprocess, "run", side_effect=uncertain) as submit, \
             self.assertRaises(subprocess.TimeoutExpired):
            AUTO.command_auto(args)
        self.assertEqual(submit.call_count, 1)

    def test_watch_near_deadline_allows_audited_slow_fetch_and_propagates_fetch_budget_failure(self) -> None:
        for outcome in ("completed", "fetch_timeout"):
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as temp:
                root = Path(temp).resolve(); bundle = root / "bundle"; bundle.mkdir(); output = root / "results"
                args = SimpleNamespace(
                    confirmed=True, dry_run=False, work_kind="ordinary", project="safejob",
                    local_dir=str(bundle), scientific_maturity=None, edge_id=None, node_id=None,
                    pilot=False, scientific_action_authorization=None,
                    input_approval_record=str(root / "input-approval.json"), approval_record=str(root / "live.json"),
                    watch=True, output_dir=str(output), poll_seconds=30, timeout_seconds=120,
                    mac_ssh_config=None, rtwin_alias=None, windows_root=None,
                    windows_server_config=None, server_alias=None,
                    execution_batch_ledger=str(root / "ledger.json"), scientific_task_id="scientific-task-fixture",
                    idempotency_key="near-deadline", estimated_core_hours=1.0,
                    estimated_core_hours_evidence_source="offline fixture",
                    estimated_core_hours_evidence_sha256="c" * 64,
                    resource_policy=str(root / "policy.json"), resource_gate=str(root / "gate.json"),
                    scheduler_resource_snapshot=str(root / "scheduler.json"), resource_tier="simple",
                    resource_cores=8, resource_memory_gb=12, walltime_seconds=3600,
                )
                summary = self.approval_summary()
                summary.update({
                    "project": "safejob", "remote_workdir": "/home/user100/SDL/safejob",
                    "gaussian_input": str(root / "input.gjf"), "local_dir": str(bundle),
                    "work_kind": "ordinary",
                })
                summary["input_approval"] = self.fake_input_approval(summary, "ordinary")
                ledger = {"batch": {"batch_id": "batch", "review_sha256": "d" * 64}, "tasks": [{"scientific_task_id": "scientific-task-fixture", "identity": {"relevant_input_sha256": summary["input_sha256"]}}]}
                policy = {"policy_id": "policy", "payload_sha256": "e" * 64}
                gate = {"gate_id": "gate", "gate_sha256": "f" * 64, "policy_sha256": "e" * 64, "scheduler_snapshot": {"payload_sha256": "1" * 64}}
                scheduler = {"payload_sha256": "1" * 64}
                known_bytes = 180 * 1024 * 1024
                fetch_budget = AUTO.transport.transfer_timeout_seconds(known_bytes)
                self.assertGreater(fetch_budget, 60)
                calls: list[list[str]] = []

                def child(command, **kwargs):
                    self.assertNotIn("timeout", kwargs)
                    calls.append(command)
                    if len(calls) == 1:
                        (bundle / "job.json").write_text(json.dumps({"job_id": "123.master", "input": "input.gjf"}), encoding="utf-8")
                        return subprocess.CompletedProcess(command, 0)
                    self.assertIn("watch", command); self.assertIn("--fetch", command)
                    deadline_index = command.index("--timeout-seconds") + 1
                    self.assertEqual(command[deadline_index], "120")
                    output.mkdir()
                    (output / "terminal-inspection.json").write_text(json.dumps({"state": "completed", "monitor_elapsed_seconds": 119}), encoding="utf-8")
                    if outcome == "completed":
                        (output / "transfer.json").write_text(json.dumps({
                            "snapshot_complete": True,
                            "monitor_elapsed_seconds": 119,
                            "fetch_elapsed_seconds": 90,
                            "transfer_timeout_evidence": {
                                "known_changed_size_bytes": known_bytes,
                                "server_to_rtwin_timeout_seconds": fetch_budget,
                                "rtwin_to_mac_timeout_seconds": fetch_budget,
                            },
                        }), encoding="utf-8")
                        return subprocess.CompletedProcess(command, 0)
                    (output / ".fetch-in-progress").write_text("incomplete\n", encoding="utf-8")
                    (output / "fetch-failure.json").write_text(json.dumps({
                        "known_changed_size_bytes": known_bytes,
                        "timeout_seconds": fetch_budget,
                        "elapsed_seconds": fetch_budget + 1,
                        "snapshot_published": False,
                    }), encoding="utf-8")
                    return subprocess.CompletedProcess(command, 2)

                with mock.patch.object(AUTO, "prepare_source", return_value=summary), \
                     mock.patch.object(AUTO.transport.resource_efficiency, "load", side_effect=[ledger, policy, gate, scheduler]), \
                     mock.patch.object(AUTO.transport.resource_efficiency, "validate_ledger", return_value=ledger), \
                     mock.patch.object(AUTO.transport.resource_efficiency, "validate_policy", return_value=policy), \
                     mock.patch.object(AUTO.transport.resource_efficiency, "_validate_gate_binding", return_value=gate), \
                     mock.patch.object(AUTO.transport.resource_efficiency, "validate_scheduler_snapshot", return_value=scheduler), \
                     mock.patch.object(AUTO, "validate_live_approval", return_value={"decision": "approved"}), \
                     mock.patch.object(AUTO.subprocess, "run", side_effect=child):
                    with redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as stopped:
                        AUTO.command_auto(args)
                self.assertEqual(stopped.exception.code, 0 if outcome == "completed" else 2)
                self.assertEqual(len(calls), 2)
                if outcome == "completed":
                    transfer = json.loads((output / "transfer.json").read_text(encoding="utf-8"))
                    self.assertLess(transfer["monitor_elapsed_seconds"], args.timeout_seconds)
                    self.assertGreater(transfer["fetch_elapsed_seconds"], 60)
                    self.assertLess(transfer["fetch_elapsed_seconds"], fetch_budget)
                else:
                    self.assertTrue((output / ".fetch-in-progress").is_file())
                    self.assertFalse((output / "transfer.json").exists())
                    failure = json.loads((output / "fetch-failure.json").read_text(encoding="utf-8"))
                    self.assertGreater(failure["elapsed_seconds"], failure["timeout_seconds"])
                    self.assertFalse(failure["snapshot_published"])

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
                    "schema": AUTO.transport.MATURITY_ACTION_V1_SCHEMA,
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

    def test_mixed_maturity_input_receipt_and_live_v3_is_rejected_explicitly(self) -> None:
        summary = self.approval_summary()
        summary["scientific_maturity"] = {
            "schema": AUTO.transport.MATURITY_ACTION_V1_SCHEMA,
            "exact_action_authorization": {"sha256": "d" * 64, "payload_sha256": "e" * 64},
        }
        summary["work_kind"] = "ts_pilot"
        summary["input_approval"] = self.fake_input_approval(summary, "ts_pilot")
        with self.assertRaises(SystemExit):
            AUTO.transport.expected_live_approval_scope(summary)

    def test_protected_prospective_live_v1_is_historical_only_in_direct_and_wrapper(self) -> None:
        maturity_test_path = ROOT / "tests" / "test_scientific_maturity.py"
        maturity_spec = importlib.util.spec_from_file_location("gaussian_auto_maturity_fixture", maturity_test_path)
        assert maturity_spec and maturity_spec.loader
        maturity_fixture = importlib.util.module_from_spec(maturity_spec)
        maturity_spec.loader.exec_module(maturity_fixture)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            input_path, receipt_path, receipt = self.make_generic_input_approval(root)
            report = AUTO.transport.parse_gaussian(input_path)
            _plan, gate_path = maturity_fixture.ScientificMaturityTests(
                "test_two_accepted_minima_open_low_cost_ts_pilot_but_preserve_owner_gates"
            ).build_gate(root / "maturity")
            fake = self.fake_input_approval(report, "ts_pilot")
            live_path = root / "mixed-live-v3.json"
            self.write_live_v3(live_path, report, fake, project="protected")
            common = [
                str(input_path), "--project", "protected", "--local-dir", str(root / "direct"),
                "--work-kind", "ts_pilot", "--pilot", "--scientific-maturity", str(gate_path),
                "--edge-id", "edge_activation", "--node-id", "ts_candidate_primary",
                "--input-approval-record", str(receipt_path), "--approval-record", str(live_path),
                "--confirmed",
            ]
            args = AUTO.transport.build_parser().parse_args(["submit", *common])
            with mock.patch.object(AUTO.transport, "run") as remote_run, self.assertRaises(SystemExit):
                args.func(args)
            self.assertFalse(remote_run.called)

            wrapper = AUTO.build_parser().parse_args([
                "auto", *common[:5], *common[5:],
            ])
            with mock.patch.object(AUTO.subprocess, "run") as wrapper_run, self.assertRaises(SystemExit):
                wrapper.func(wrapper)
            self.assertFalse(wrapper_run.called)

    def test_protected_prospective_live_v2_blocker_is_reported_before_network(self) -> None:
        class BlockedV2Owner:
            @staticmethod
            def assert_action(*_args, **_kwargs):
                raise ValueError("minimum_candidate_input_result_lineage_unavailable_v2")

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            input_path, _, _ = self.make_generic_input_approval(root)
            gate_path = root / "maturity-v2.json"
            gate_path.write_text(json.dumps({"schema": AUTO.transport.MATURITY_GATE_V2_SCHEMA}), encoding="utf-8")
            args = AUTO.transport.build_parser().parse_args([
                "submit", str(input_path), "--project", "protected", "--local-dir", str(root / "bundle"),
                "--work-kind", "ts_pilot", "--pilot", "--scientific-maturity", str(gate_path),
                "--edge-id", "edge_activation", "--node-id", "ts_candidate_primary", "--confirmed",
            ])
            real_loader = AUTO.transport._load_scientific_maturity
            def load_owner(version=1):
                return BlockedV2Owner if version == 2 else real_loader(version)
            with mock.patch.object(AUTO.transport, "_load_scientific_maturity", side_effect=load_owner), mock.patch.object(AUTO.transport, "run") as remote_run:
                with self.assertRaises(SystemExit):
                    args.func(args)
            self.assertFalse(remote_run.called)

    def test_maturity_dispatch_returns_first_stable_resolved_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            owner = root / "owner"
            owner.mkdir()
            gate = owner / "maturity.json"
            gate.write_text(
                json.dumps({"schema": AUTO.transport.MATURITY_GATE_V2_SCHEMA}),
                encoding="utf-8",
            )
            active = root / "active"
            active.symlink_to(owner, target_is_directory=True)
            schema, _validator, resolved = AUTO.transport._maturity_owner_for_gate(
                active / gate.name
            )
            self.assertEqual(schema, AUTO.transport.MATURITY_GATE_V2_SCHEMA)
            self.assertEqual(resolved, gate.resolve())
            self.assertFalse(resolved.is_symlink())

    def test_maturity_audit_replays_dispatchers_frozen_path(self) -> None:
        seen: list[Path] = []

        class FrozenOwner:
            @staticmethod
            def assert_action(path, *_args, **_kwargs):
                seen.append(path)
                return {"schema": AUTO.transport.MATURITY_ACTION_V2_SCHEMA}

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            raw = root / "active" / "maturity.json"
            frozen = root / "first-owner" / "maturity.json"
            args = SimpleNamespace(
                work_kind="ts_pilot", pilot=True, scientific_maturity=str(raw),
                edge_id="edge_activation", node_id="ts_candidate_primary",
                _prospective_live=False,
            )
            report = {
                "route": "#p b3lyp/6-31g(d) opt=(ts,calcfc) freq",
                "mem": "12GB", "nprocshared": 8,
            }
            with mock.patch.object(
                AUTO.transport, "_maturity_owner_for_gate",
                return_value=(AUTO.transport.MATURITY_GATE_V2_SCHEMA, FrozenOwner, frozen),
            ):
                check = AUTO.transport.audit_scientific_maturity(args, report, "ts_input")
            self.assertEqual(check["schema"], AUTO.transport.MATURITY_ACTION_V2_SCHEMA)
            self.assertEqual(seen, [frozen])

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

    def test_ordinary_and_minimum_exact_input_plus_live_v3_reach_offline_dry_run(self) -> None:
        for work_kind, route in (
            ("ordinary", "#p hf/sto-3g"),
            ("minimum", "#p hf/sto-3g opt freq"),
        ):
            with self.subTest(work_kind=work_kind), tempfile.TemporaryDirectory() as temp:
                root = Path(temp).resolve()
                gjf = root / f"{work_kind}.gjf"
                gjf.write_text(
                    f"%chk={work_kind}.chk\n%mem=12GB\n%nprocshared=8\n{route}\n\n"
                    f"{work_kind}\n\n0 1\nH 0 0 0\nH 0 0 1\n\n",
                    encoding="utf-8",
                )
                report = AUTO.transport.parse_gaussian(gjf)
                approved_input = self.fake_input_approval(report, work_kind)
                live = root / "live-v3.json"
                self.write_live_v3(live, report, approved_input, project=work_kind)
                direct = AUTO.transport.build_parser().parse_args([
                    "submit", str(gjf), "--project", work_kind,
                    "--local-dir", str(root / "direct"), "--confirmed", "--dry-run",
                    "--work-kind", work_kind, "--input-approval-record", str(root / "receipt.json"),
                    "--approval-record", str(live),
                ])
                stdout = io.StringIO()
                with mock.patch.object(AUTO.transport, "validate_input_approval", return_value=approved_input), mock.patch.object(AUTO.transport, "run") as remote_run, redirect_stdout(stdout):
                    direct.func(direct)
                plan = json.loads(stdout.getvalue())
                self.assertTrue(plan["live_submission_ready"])
                self.assertFalse(remote_run.called)

                wrapper = AUTO.build_parser().parse_args([
                    "auto", str(gjf), "--project", work_kind,
                    "--local-dir", str(root / "wrapper"), "--confirmed", "--dry-run",
                    "--work-kind", work_kind, "--input-approval-record", str(root / "receipt.json"),
                    "--approval-record", str(live),
                ])
                with mock.patch.object(AUTO.transport, "validate_input_approval", return_value=approved_input), mock.patch.object(AUTO.subprocess, "run", return_value=SimpleNamespace(returncode=0)) as child:
                    wrapper.func(wrapper)
                self.assertTrue(child.called)
                self.assertIn("--dry-run", child.call_args.args[0])

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
        open_shell_ordinary = {**ordinary, "multiplicity": 2}
        blocked = AUTO.transport.input_approval_compatibility(open_shell_ordinary, "ordinary")
        self.assertEqual(blocked["status"], "blocked_unsupported_open_shell_ordinary")
        self.assertIsNone(blocked["required_schema"])
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

    def test_opt_saddle_forms_are_protected_but_saddle_zero_is_not(self) -> None:
        protected = (
            "#p b3lyp/6-31g(d) opt=(saddle=1,calcfc) freq",
            "#p b3lyp/6-31g(d) opt=saddle=1 freq",
            "#P b3lyp/6-31g(d) OPT=(SADDLE=2,CALCFC) FREQ",
            "#p b3lyp/6-31g(d) opt=loose opt=(saddle=3,calcfc) freq",
        )
        for route in protected:
            with self.subTest(route=route):
                self.assertTrue(AUTO.transport.route_has_ts_optimization(route))
                self.assertEqual(AUTO.transport.classify_protected_work(route), "ts")
                report = {
                    "route": route, "geometry_source": "explicit_cartesian", "oldcheckpoint": None,
                    "link1_count": 0, "route_section_count": 1,
                }
                self.assertNotEqual(
                    AUTO.transport.input_approval_compatibility(report, "minimum")["status"],
                    "supported_generic_v1",
                )
        zero = "#p b3lyp/6-31g(d) opt=(saddle=0,calcfc) freq"
        self.assertFalse(AUTO.transport.route_has_ts_optimization(zero))
        self.assertIsNone(AUTO.transport.classify_protected_work(zero))

    def test_opt_saddle_minimum_live_bypass_is_blocked_in_direct_and_wrapper_before_network(self) -> None:
        routes = (
            "#p b3lyp/6-31g(d) opt=(saddle=1,calcfc) freq",
            "#p b3lyp/6-31g(d) opt=saddle=1 freq",
        )
        for index, route in enumerate(routes):
            with self.subTest(route=route), tempfile.TemporaryDirectory() as temp:
                root = Path(temp).resolve()
                gjf = root / "saddle.gjf"
                gjf.write_text(
                    f"%chk=saddle.chk\n%mem=12GB\n%nprocshared=8\n{route}\n\n"
                    "saddle\n\n0 1\nH 0 0 0\nH 0 0 1\n\n",
                    encoding="utf-8",
                )
                direct = AUTO.transport.build_parser().parse_args([
                    "submit", str(gjf), "--project", f"saddle{index}",
                    "--local-dir", str(root / "direct"), "--confirmed", "--work-kind", "minimum",
                    "--input-approval-record", str(root / "receipt.json"),
                    "--approval-record", str(root / "live-v3.json"),
                ])
                with mock.patch.object(AUTO.transport, "run") as remote_run, self.assertRaises(SystemExit):
                    direct.func(direct)
                self.assertFalse(remote_run.called)

                wrapper = AUTO.build_parser().parse_args([
                    "auto", str(gjf), "--project", f"saddle{index}",
                    "--local-dir", str(root / "wrapper"), "--confirmed", "--work-kind", "minimum",
                    "--input-approval-record", str(root / "receipt.json"),
                    "--approval-record", str(root / "live-v3.json"),
                ])
                with mock.patch.object(AUTO.subprocess, "run") as wrapper_run, self.assertRaises(SystemExit):
                    wrapper.func(wrapper)
                self.assertFalse(wrapper_run.called)

    def assert_generic_receipt_rejected(self, route: str, trailing: str = "", work_kind: str = "minimum") -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            input_path, receipt_path, _ = self.make_generic_input_approval(root)
            original_receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            input_path.write_text(
                "%chk=fixture.chk\n%mem=12GB\n%nprocshared=8\n"
                f"{route}\n\n"
                f"specialist\n\n0 1\nH 0 0 0\nH 0 0 1\n\n{trailing}",
                encoding="utf-8",
            )
            report = AUTO.transport.parse_gaussian(input_path)
            review_path = root / "generic-input-review.json"
            review = json.loads(review_path.read_text(encoding="utf-8"))
            review["work_kind"] = work_kind
            review["approved_input"] = AUTO.transport._input_approval_facts(report)
            review["route_profile_mapping"]["exact_route"] = report["route"]
            review["payload_sha256"] = AUTO.transport.contract_payload_sha256(review)
            review_path.write_text(json.dumps(review), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "work_kind_route_mismatch|specialist"):
                AUTO.transport.build_input_approval_receipt(
                    root / "options.json", root / "selection.json",
                    review_path, input_path, root / "rejected-receipt.json", "saddle-minimum",
                )

            forged = original_receipt
            forged["work_kind"] = work_kind
            forged["input"] = AUTO.transport._input_blob_binding(input_path, root)
            forged["approved_input"] = AUTO.transport._input_approval_facts(report)
            forged["sources"]["input_review"].update({
                "sha256": AUTO.transport.sha256(review_path),
                "size_bytes": review_path.stat().st_size,
                "payload_sha256": review["payload_sha256"],
            })
            forged["protocol_review_binding"]["input_review_payload_sha256"] = review["payload_sha256"]
            forged["protocol_review_binding"]["exact_route"] = report["route"]
            forged["protocol_review_binding"]["route_profile_mapping_sha256"] = AUTO.transport.canonical_value_sha256(review["route_profile_mapping"])
            forged["payload_sha256"] = AUTO.transport.contract_payload_sha256(forged)
            receipt_path.write_text(json.dumps(forged), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "work_kind_route_mismatch|specialist"):
                AUTO.transport.validate_input_approval_receipt(receipt_path)

    def test_generic_minimum_receipt_build_and_replay_reject_opt_saddle(self) -> None:
        self.assert_generic_receipt_rejected(
            "#p b3lyp/6-31g(d) opt=(saddle=1,calcfc) freq"
        )

    def test_specialist_aliases_and_relaxed_scan_tail_fail_closed(self) -> None:
        specialist = (
            "#p b3lyp/6-31g(d) opt=(conical,calcfc) freq",
            "#p b3lyp/6-31g(d) opt=avoided freq",
            "#P b3lyp/6-31g(d) OPT=(AVOIDED,CALCFC) FREQ",
        )
        for route in specialist:
            with self.subTest(route=route):
                self.assertTrue(AUTO.transport.route_has_specialist_optimization(route))
                self.assertFalse(AUTO.transport.route_has_ts_optimization(route))
                self.assertEqual(AUTO.transport.classify_protected_work(route), "specialist_opt")
        scans = (
            "#p b3lyp/6-31g(d) opt=addredundant freq",
            "#p b3lyp/6-31g(d) opt=(addredundant,calcfc) freq",
            "#P b3lyp/6-31g(d) OPT=(ADDREDUNDANT,CALCFC) FREQ",
        )
        for route in scans:
            with self.subTest(route=route):
                self.assertTrue(AUTO.transport.route_has_scan(route))
                self.assertEqual(AUTO.transport.classify_protected_work(route), "ts_scan")
        gic_routes = (
            "#p b3lyp/6-31g(d) opt=gic freq",
            "#p b3lyp/6-31g(d) opt=addgic freq",
            "#p b3lyp/6-31g(d) opt=readallgic freq",
            "#p b3lyp/6-31g(d) geom=gic opt freq",
        )
        for route in gic_routes:
            with self.subTest(route=route):
                self.assertTrue(AUTO.transport.route_has_gic_optimization(route))
                self.assertFalse(AUTO.transport.route_has_scan(route))
                self.assertEqual(AUTO.transport.classify_protected_work(route), "specialist_opt")

        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "tail-scan.gjf"
            path.write_text(
                "%chk=scan.chk\n%mem=12GB\n%nprocshared=8\n#p b3lyp/6-31g(d) opt=addredundant freq\n\n"
                "scan\n\n0 1\nH 0 0 0\nH 0 0 1\n\nB 1 2 S 10 0.10\n\n",
                encoding="utf-8",
            )
            report = AUTO.transport.parse_gaussian(path)
            self.assertTrue(report["has_relaxed_scan_directive"])
            self.assertEqual(report["trailing_section_line_count"], 1)
            self.assertEqual(AUTO.transport.classify_protected_input(report), "ts_scan")
            self.assertEqual(
                AUTO.transport.input_approval_compatibility(report, "minimum")["status"],
                "blocked_missing_specialist_input_approval",
            )
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "gic-scan.gjf"
            path.write_text(
                "%chk=gic.chk\n%mem=12GB\n%nprocshared=8\n#p b3lyp/6-31g(d) opt=gic freq\n\n"
                "gic scan\n\n0 1\nH 0 0 0\nH 0 0 1\n\n"
                "F1F2(NSteps=10,StepSize=0.2)\n\n",
                encoding="utf-8",
            )
            report = AUTO.transport.parse_gaussian(path)
            self.assertTrue(report["has_relaxed_scan_directive"])
            self.assertEqual(AUTO.transport.classify_protected_input(report), "ts_scan")

    def test_specialist_alias_live_bypasses_stop_direct_and_wrapper_before_network(self) -> None:
        cases = (
            ("#p b3lyp/6-31g(d) opt=(conical,calcfc) freq", ""),
            ("#p b3lyp/6-31g(d) opt=avoided freq", ""),
            ("#p b3lyp/6-31g(d) opt=addredundant freq", "B 1 2 S 10 0.10\n\n"),
            ("#p b3lyp/6-31g(d) opt=gic freq", "F1F2(NSteps=10,StepSize=0.2)\n\n"),
        )
        for index, (route, trailing) in enumerate(cases):
            with self.subTest(route=route, trailing=bool(trailing)), tempfile.TemporaryDirectory() as temp:
                root = Path(temp).resolve()
                gjf = root / "specialist.gjf"
                gjf.write_text(
                    f"%chk=specialist.chk\n%mem=12GB\n%nprocshared=8\n{route}\n\n"
                    f"specialist\n\n0 1\nH 0 0 0\nH 0 0 1\n\n{trailing}",
                    encoding="utf-8",
                )
                common = [
                    str(gjf), "--project", f"alias{index}", "--local-dir", str(root / "direct"),
                    "--confirmed", "--work-kind", "minimum", "--input-approval-record", str(root / "receipt.json"),
                    "--approval-record", str(root / "live-v3.json"),
                ]
                direct = AUTO.transport.build_parser().parse_args(["submit", *common])
                with mock.patch.object(AUTO.transport, "run") as remote_run, self.assertRaises(SystemExit):
                    direct.func(direct)
                self.assertFalse(remote_run.called)
                common[4] = str(root / "wrapper")
                wrapper = AUTO.build_parser().parse_args(["auto", *common])
                with mock.patch.object(AUTO.subprocess, "run") as wrapper_run, self.assertRaises(SystemExit):
                    wrapper.func(wrapper)
                self.assertFalse(wrapper_run.called)

    def test_specialist_alias_generic_minimum_receipt_build_and_replay_are_blocked(self) -> None:
        for route, trailing in (
            ("#p b3lyp/6-31g(d) opt=(conical,calcfc) freq", ""),
            ("#p b3lyp/6-31g(d) opt=avoided freq", ""),
            ("#p b3lyp/6-31g(d) opt=addredundant freq", "B 1 2 S 10 0.10\n\n"),
            ("#p b3lyp/6-31g(d) opt=gic freq", "F1F2(NSteps=10,StepSize=0.2)\n\n"),
        ):
            with self.subTest(route=route, trailing=bool(trailing)):
                self.assert_generic_receipt_rejected(route, trailing)

    def test_gen_basis_s_shell_is_not_misclassified_as_relaxed_scan(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "gen-basis.gjf"
            path.write_text(
                "%chk=gen.chk\n%mem=12GB\n%nprocshared=8\n#p b3lyp/gen opt freq\n\n"
                "gen basis\n\n0 1\nH 0 0 0\nH 0 0 1\n\n"
                "H 0\nS 3 1.00\n  3.42525091 0.15432897\n  0.62391373 0.53532814\n"
                "  0.16885540 0.44463454\n****\n\n",
                encoding="utf-8",
            )
            report = AUTO.transport.parse_gaussian(path)
            self.assertGreater(report["trailing_section_line_count"], 0)
            self.assertFalse(report["has_relaxed_scan_directive"])
            self.assertIsNone(AUTO.transport.classify_protected_input(report))

    def test_fopt_popt_are_optimization_family_and_generic_specialist_only(self) -> None:
        cases = (
            ("#p b3lyp/6-31g(d) fopt=qst2", "ts"),
            ("#P b3lyp/6-31g(d) FOPT=(QST2,CALCFC)", "ts"),
            ("#p b3lyp/6-31g(d) popt(saddle=1)", "ts"),
            ("#p b3lyp/6-31g(d) fopt=conical", "specialist_opt"),
            ("#p b3lyp/6-31g(d) popt=addredundant", "ts_scan"),
        )
        for route, classification in cases:
            with self.subTest(route=route):
                self.assertTrue(AUTO.transport.route_has_optimization_keyword(route))
                self.assertEqual(AUTO.transport.classify_protected_work(route), classification)
                report = {
                    "route": route, "geometry_source": "explicit_cartesian", "oldcheckpoint": None,
                    "link1_count": 0, "route_section_count": 1,
                }
                for work_kind in ("ordinary", "minimum"):
                    self.assertEqual(
                        AUTO.transport.input_approval_compatibility(report, work_kind)["status"],
                        "blocked_missing_specialist_input_approval",
                    )
        with self.assertRaises(ValueError):
            AUTO.transport._assert_consumed_tasks_match_route(
                "#p b3lyp/6-31g(d) fopt=qst2",
                [{"task_index": 0, "stage_type": "single_point", "profile_id": "sp"}],
                [{
                    "task_index": 0, "stage_type": "single_point", "profile_id": "sp",
                    "route_evidence": ["single_point"], "human_confirmed": True,
                }],
            )

    def test_fopt_qst2_and_popt_saddle_live_and_receipt_bypasses_are_blocked(self) -> None:
        cases = (
            ("#p b3lyp/6-31g(d) fopt=qst2", "ordinary"),
            ("#p b3lyp/6-31g(d) popt(saddle=1)", "minimum"),
        )
        for index, (route, work_kind) in enumerate(cases):
            with self.subTest(route=route), tempfile.TemporaryDirectory() as temp:
                root = Path(temp).resolve()
                gjf = root / "optimization-family.gjf"
                gjf.write_text(
                    f"%chk=family.chk\n%mem=12GB\n%nprocshared=8\n{route}\n\n"
                    "family\n\n0 1\nH 0 0 0\nH 0 0 1\n\n",
                    encoding="utf-8",
                )
                common = [
                    str(gjf), "--project", f"family{index}", "--local-dir", str(root / "direct"),
                    "--confirmed", "--work-kind", work_kind, "--input-approval-record", str(root / "receipt.json"),
                    "--approval-record", str(root / "live-v3.json"),
                ]
                direct = AUTO.transport.build_parser().parse_args(["submit", *common])
                with mock.patch.object(AUTO.transport, "run") as remote_run, self.assertRaises(SystemExit):
                    direct.func(direct)
                self.assertFalse(remote_run.called)
                common[4] = str(root / "wrapper")
                wrapper = AUTO.build_parser().parse_args(["auto", *common])
                with mock.patch.object(AUTO.subprocess, "run") as wrapper_run, self.assertRaises(SystemExit):
                    wrapper.func(wrapper)
                self.assertFalse(wrapper_run.called)
            self.assert_generic_receipt_rejected(route, work_kind=work_kind)

    def test_ircmax_is_specialist_path_and_cannot_be_single_point(self) -> None:
        route = "#p IRCMax(B3LYP/6-31G(d):HF/3-21G,CalcFC)"
        self.assertTrue(AUTO.transport.route_has_specialist_path(route))
        self.assertEqual(AUTO.transport.classify_protected_work(route), "specialist_path")
        self.assertNotEqual(AUTO.transport.classify_protected_work(route), "irc")
        report = {
            "route": route, "geometry_source": "explicit_cartesian", "oldcheckpoint": None,
            "link1_count": 0, "route_section_count": 1,
        }
        self.assertEqual(
            AUTO.transport.input_approval_compatibility(report, "ordinary")["status"],
            "blocked_missing_specialist_input_approval",
        )
        with self.assertRaises(ValueError):
            AUTO.transport._assert_consumed_tasks_match_route(
                route,
                [{"task_index": 0, "stage_type": "single_point", "profile_id": "sp"}],
                [{
                    "task_index": 0, "stage_type": "single_point", "profile_id": "sp",
                    "route_evidence": ["single_point"], "human_confirmed": True,
                }],
            )
        self.assertEqual(
            AUTO.transport.classify_protected_work("#p Scan B3LYP/6-31G(d)"),
            "specialist_path",
        )

    def test_ircmax_live_and_generic_receipt_bypasses_are_blocked(self) -> None:
        route = "#p IRCMax(B3LYP/6-31G(d):HF/3-21G,CalcFC)"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            gjf = root / "ircmax.gjf"
            gjf.write_text(
                f"%chk=ircmax.chk\n%mem=12GB\n%nprocshared=8\n{route}\n\n"
                "ircmax\n\n0 1\nH 0 0 0\nH 0 0 1\n\n",
                encoding="utf-8",
            )
            common = [
                str(gjf), "--project", "ircmax", "--local-dir", str(root / "direct"),
                "--confirmed", "--work-kind", "ordinary", "--input-approval-record", str(root / "receipt.json"),
                "--approval-record", str(root / "live-v3.json"),
            ]
            direct = AUTO.transport.build_parser().parse_args(["submit", *common])
            with mock.patch.object(AUTO.transport, "run") as remote_run, self.assertRaises(SystemExit):
                direct.func(direct)
            self.assertFalse(remote_run.called)
            common[4] = str(root / "wrapper")
            wrapper = AUTO.build_parser().parse_args(["auto", *common])
            with mock.patch.object(AUTO.subprocess, "run") as wrapper_run, self.assertRaises(SystemExit):
                wrapper.func(wrapper)
            self.assertFalse(wrapper_run.called)
        self.assert_generic_receipt_rejected(route, work_kind="ordinary")

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

    def test_resource_bound_wrapper_dry_run_replaces_stale_proposal_with_exact_v9_scope(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); source = root / "input.gjf"; source.write_text("#p hf/sto-3g\n\nX\n\n0 1\nH 0 0 0\n\n")
            summary = {
                "project": "safejob", "remote_workdir": "/home/user100/SDL/safejob", "input_sha256": AUTO.transport.sha256(source),
                "protocol": {"route": "#p hf/sto-3g", "mem": "12GB", "nproc": 8}, "charge": 0, "multiplicity": 1,
                "work_kind": "ordinary", "gaussian_input": str(source),
                "input_approval": {"status": "validated_exact_input_approval", "schema": AUTO.transport.INPUT_APPROVAL_SCHEMA, "sha256": "a" * 64, "payload_sha256": "b" * 64, "input_sha256": AUTO.transport.sha256(source), "work_kind": "ordinary"},
            }
            summary["live_approval_requirement"] = AUTO.transport.live_approval_scope_proposal(summary)
            self.assertEqual(summary["live_approval_requirement"]["required_schema"], AUTO.transport.LIVE_APPROVAL_V3_SCHEMA)
            args = AUTO.build_parser().parse_args([
                "auto", str(source), "--project", "safejob", "--local-dir", str(root / "bundle"), "--work-kind", "ordinary", "--confirmed", "--dry-run",
                "--execution-batch-ledger", str(root / "ledger.json"), "--scientific-task-id", "scientific-task-fixture", "--idempotency-key", "once",
                "--estimated-core-hours", "0.000001", "--estimated-core-hours-evidence-source", "fixture", "--estimated-core-hours-evidence-sha256", "c" * 64,
                "--resource-policy", str(root / "policy.json"), "--resource-gate", str(root / "gate.json"), "--scheduler-resource-snapshot", str(root / "scheduler.json"),
                "--resource-tier", "simple", "--resource-cores", "8", "--resource-memory-gb", "12", "--walltime-seconds", "3600",
            ])
            ledger = {"batch": {"batch_id": "batch", "review_sha256": "d" * 64}, "tasks": [{"scientific_task_id": "scientific-task-fixture", "identity": {"relevant_input_sha256": summary["input_sha256"]}}]}
            policy = {"policy_id": "policy", "payload_sha256": "e" * 64}
            gate = {"gate_id": "gate", "gate_sha256": "f" * 64, "policy_sha256": "e" * 64, "scheduler_snapshot": {"payload_sha256": "1" * 64}}
            scheduler = {"payload_sha256": "1" * 64}
            with mock.patch.object(AUTO, "prepare_source", return_value=copy.deepcopy(summary)), mock.patch.object(AUTO.transport.resource_efficiency, "load", side_effect=[ledger, policy, gate, scheduler]), mock.patch.object(AUTO.transport.resource_efficiency, "validate_ledger", return_value=ledger), mock.patch.object(AUTO.transport.resource_efficiency, "validate_policy", return_value=policy), mock.patch.object(AUTO.transport.resource_efficiency, "_validate_gate_binding", return_value=gate), mock.patch.object(AUTO.transport.resource_efficiency, "validate_scheduler_snapshot", return_value=scheduler), mock.patch.object(AUTO.subprocess, "run", return_value=SimpleNamespace(returncode=0)):
                output = io.StringIO()
                with redirect_stdout(output):
                    AUTO.command_auto(args)
            preflight = json.loads(output.getvalue())["approved_preflight"]
            proposal = preflight["live_approval_requirement"]
            self.assertEqual(proposal["required_schema"], AUTO.transport.LIVE_APPROVAL_V9_SCHEMA)
            required_schema, exact_scope = AUTO.transport.expected_live_approval_scope(preflight)
            self.assertEqual((required_schema, proposal["scope_proposal"]), (AUTO.transport.LIVE_APPROVAL_V9_SCHEMA, exact_scope))
            self.assertNotEqual(proposal["scope_proposal"], summary["live_approval_requirement"]["scope_proposal"])


if __name__ == "__main__":
    unittest.main()
