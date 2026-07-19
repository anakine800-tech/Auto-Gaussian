#!/usr/bin/env python3
"""Adversarial offline tests for Auto-G16 package 4."""

from __future__ import annotations

import base64
import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).parents[1]
SCRIPTS = ROOT / "skills" / "auto-g16-rtwin-pbs" / "scripts"
sys.path.insert(0, str(SCRIPTS))


def load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module


BATCH = load("package4_batch", "execution_batch.py")
RESOURCE = load("package4_resource", "resource_efficiency.py")
PBS = load("package4_pbs", "gaussian_rtwin_pbs.py")


def load_schema_validator():
    path = ROOT / "scripts" / "validate_asymmetric_contract.py"
    spec = importlib.util.spec_from_file_location("package4_schema_validator", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module


SCHEMA_VALIDATOR = load_schema_validator()


def identity(digest: str, salt: str = "1") -> dict[str, str]:
    return {
        "structure_sha256": salt * 64, "chemical_hypothesis_sha256": "2" * 64,
        "method_protocol_sha256": "3" * 64, "calculation_objective_sha256": "4" * 64,
        "relevant_input_sha256": digest,
    }


class ResourceMonitorEfficiencyTests(unittest.TestCase):
    def make_ledger(self, root: Path, digest: str = "5" * 64):
        review = BATCH.finalize_review(json.loads((ROOT / "tests/fixtures/rtwin_pbs/execution_batch_review.template.json").read_text()))
        review_path = root / "review.json"; review_path.write_text(json.dumps(review))
        ledger_path = root / "ledger.json"
        BATCH.initialize(review_path, ledger_path, timestamp="2026-01-01T00:00:00Z")
        task = BATCH.admit_task(ledger_path, identity(digest), estimated_core_hours=4, reason="exact fixture", reviewer="fixture", reviewed_at="2026-01-01T00:01:00Z")
        BATCH.migrate_to_submission_ledger(ledger_path, migrated_at="2026-01-01T00:02:00Z", migration_source="fixture")
        RESOURCE.migrate_v2_to_v3(ledger_path, migrated_at="2026-01-01T00:03:00Z", migration_source="package4 fixture")
        return ledger_path, task["scientific_task_id"]

    def policy(self, **limits):
        values = {
            "max_estimated_core_hours": 100, "max_remaining_core_hours": 100,
            "max_concurrent_unresolved_attempts": 3, "max_concurrent_active_attempts": 3,
            "max_total_cores": 64, "max_total_memory_gb": 256, "max_job_cores": 44,
            "max_job_memory_gb": 120, "max_job_walltime_seconds": 172800,
        }; values.update(limits)
        return RESOURCE.finalize_policy({
            "schema": RESOURCE.POLICY_SCHEMA, "policy_id": "policy-1",
            "reviewed_at": "2026-01-01T00:00:00Z", "reviewer": "fixture", "limits": values,
            "governance": {
                "unknown_scheduler_or_ledger_state_fails_closed": True,
                "resources_must_be_exact_reviewed_bindings": True,
                "walltime_must_be_explicitly_reviewed": True, "automatic_resource_change": False,
                "automatic_retry": False, "monitoring_changes_scientific_conclusion": False,
            }, "payload_sha256": "",
        })

    def snapshot_artifact(self, root: Path, attempts=None, *, collected="2026-01-01T00:04:00Z", max_age=3600):
        snapshot = RESOURCE.finalize_scheduler_snapshot({
            "schema": RESOURCE.SCHEDULER_SNAPSHOT_SCHEMA, "snapshot_id": "snapshot-1",
            "collected_at": collected, "source": "synthetic exact batch qstat",
            "scope": {"kind": "complete_user_active_jobs", "owner": "fixture", "completeness": "complete", "batch_evidence_sha256": "e" * 64},
            "transport": {"classification": "success", "status": "known"},
            "freshness": {"classification": "fresh", "age_seconds": 0, "max_age_seconds": max_age},
            "attempts": attempts or [], "payload_sha256": "",
        })
        path = root / ("scheduler-" + str(len(list(root.glob("scheduler-*.json")))) + ".json")
        path.write_text(json.dumps(snapshot, sort_keys=True) + "\n")
        document, digest, size = RESOURCE.load_artifact(path)
        return document, digest, size, path

    def gate(self, ledger_path: Path, policy, snapshot_tuple, *, evaluated="2026-01-01T00:05:00Z", **request):
        snapshot, artifact_sha, artifact_size, _ = snapshot_tuple
        values = {"resource_tier": "simple", "cores": 8, "memory_gb": 12, "walltime_seconds": 3600, "estimated_core_hours": 4}
        values.update(request)
        ledger = RESOURCE.validate_ledger(RESOURCE.load(ledger_path)); task_id = ledger["tasks"][0]["scientific_task_id"]
        return RESOURCE.evaluate_gate(
            ledger, policy, snapshot,
            gate_id="gate-1", evaluated_at=evaluated,
            scheduler_artifact_sha256=artifact_sha, scheduler_artifact_size=artifact_size, **values,
            scientific_task_id=task_id,
            attempt_id=BATCH.attempt_id_for(ledger["batch"]["batch_id"], "key-1"),
            project="safejob", input_sha256="5" * 64,
        )

    def reserve(self, ledger_path, task_id, policy, gate, snapshot_tuple, **overrides):
        snapshot, artifact_sha, artifact_size, _ = snapshot_tuple
        values = {"project": "safejob", "remote_workdir": "/home/user100/SDL/safejob"}; values.update(overrides)
        return RESOURCE.reserve_attempt(
            ledger_path, task_id, identity=identity("5" * 64), idempotency_key="key-1",
            input_sha256="5" * 64, live_approval_id="approval-1", live_approval_sha256="a" * 64,
            estimated_core_hours_evidence={"source": "fixture", "sha256": "b" * 64},
            reserved_at="2026-01-01T00:06:00Z", audit_reason="fixture", policy=policy, gate=gate,
            scheduler_snapshot=snapshot, scheduler_artifact_sha256=artifact_sha,
            scheduler_artifact_size=artifact_size, **values,
        )

    def make_submitted_bundle(self, root: Path):
        ledger_path, task_id = self.make_ledger(root)
        policy = self.policy(); snapshot = self.snapshot_artifact(root)
        attempt = self.reserve(ledger_path, task_id, policy, self.gate(ledger_path, policy, snapshot), snapshot)
        attempt = RESOURCE.reconcile_attempt(
            ledger_path, attempt["attempt_id"], state="submitted",
            observed_at="2026-01-01T00:07:00Z", reason="fixture submission",
            scheduler_reference="123.master",
            reconciliation_evidence={"source": "fixture", "sha256": "c" * 64},
        )
        local_dir = root / "bundle"; local_dir.mkdir()
        input_bytes = b"%chk=input.chk\n%mem=12GB\n%nprocshared=8\n#p hf/sto-3g\n\nfixture\n\n0 1\nH 0 0 0\n\n"
        (local_dir / "input.gjf").write_bytes(input_bytes)
        PBS.initialize_job_state(local_dir, {
            "schema": "gaussian-rtwin-pbs/1", "project": "safejob",
            "remote_workdir": "/home/user100/SDL/safejob", "job_id": "123.master",
            "status": "submitted", "input": "input.gjf",
            "input_sha256": __import__("hashlib").sha256(input_bytes).hexdigest(),
            "execution_batch": {"attempt_id": attempt["attempt_id"]},
        })
        return ledger_path, attempt, local_dir

    @staticmethod
    def inspection(state: str, *, pbs_state=None, pbs_present=False, normal=0, error=0, candidate=False, mtime=1):
        value = {
            "schema": "gaussian-job-inspection/2", "project": "safejob", "job_id": "123.master",
            "state": state, "collected_at": "2026-01-01T00:08:00Z",
            "source": "single_remote_read_only_snapshot", "freshness": "fresh", "age_seconds": 0,
            "transport_classification": "success", "pbs_state": pbs_state,
            "pbs_record_present": pbs_present, "log_size": 100, "log_mtime_epoch": mtime,
            "full_normal_termination_count": normal, "full_error_termination_count": error,
            "workflow_expected_stages": None, "interrupted_candidate": candidate,
            "interruption_proof": None, "analysis": {
                "normal_termination": False, "error_termination": False,
                "normal_termination_count": 0, "error_termination_count": 0,
            },
        }
        value["evidence_sha256"] = PBS.canonical_digest(value)
        return value

    @staticmethod
    def watch_args(root: Path, ledger_path: Path, attempt_id: str, *, fetch=False):
        output = root / "output"; output.mkdir(exist_ok=True)
        return SimpleNamespace(
            poll_seconds=2, timeout_seconds=10, local_dir=str(root / "bundle"),
            output_dir=str(output), project="safejob", input_stem="input", job_id="123.master",
            execution_batch_ledger=str(ledger_path), attempt_id=attempt_id, fetch=fetch,
            auto_cleanup_zombie=False, zombie_stability_seconds=2, zombie_verify_seconds=2,
        )

    def make_live_submit_fixture(self, root: Path):
        source = root / "source.gjf"
        source.write_text("%chk=source.chk\n%mem=12GB\n%nprocshared=8\n#p hf/sto-3g\n\nfixture\n\n0 1\nH 0 0 0\n\n")
        digest = PBS.sha256(source)
        ledger_path, task_id = self.make_ledger(root, digest)
        policy = self.policy()
        collected = PBS.utc_now()
        scheduler = self.snapshot_artifact(root, collected=collected, max_age=3600)
        ledger = RESOURCE.load(ledger_path)
        attempt_id = BATCH.attempt_id_for(ledger["batch"]["batch_id"], "submit-key")
        gate = RESOURCE.evaluate_gate(
            ledger, policy, scheduler[0], gate_id="submit-gate", evaluated_at=collected,
            scientific_task_id=task_id, attempt_id=attempt_id, project="safejob",
            input_sha256=digest, resource_tier="simple", cores=8, memory_gb=12,
            walltime_seconds=3600, estimated_core_hours=4,
            scheduler_artifact_sha256=scheduler[1], scheduler_artifact_size=scheduler[2],
        )
        policy_path = root / "policy.json"; policy_path.write_text(json.dumps(policy, sort_keys=True) + "\n")
        gate_path = root / "gate.json"; gate_path.write_text(json.dumps(gate, sort_keys=True) + "\n")
        input_approval_path = root / "input-approval.json"; input_approval_path.write_text("{}")
        approval_path = root / "live.json"; approval_path.write_text("{}")
        config = root / "ssh_config"; config.write_text("Host rtwin\n")
        args = PBS.build_parser().parse_args([
            "submit", str(source), "--project", "safejob", "--local-dir", str(root / "bundle"),
            "--work-kind", "ordinary", "--input-approval-record", str(input_approval_path),
            "--approval-record", str(approval_path), "--execution-batch-ledger", str(ledger_path),
            "--scientific-task-id", task_id, "--idempotency-key", "submit-key",
            "--estimated-core-hours", "4", "--estimated-core-hours-evidence-source", "fixture",
            "--estimated-core-hours-evidence-sha256", "f" * 64,
            "--resource-policy", str(policy_path), "--resource-gate", str(gate_path),
            "--scheduler-resource-snapshot", str(scheduler[3]), "--resource-tier", "simple",
            "--resource-cores", "8", "--resource-memory-gb", "12", "--walltime-seconds", "3600",
            "--mac-ssh-config", str(config), "--confirmed",
        ])
        input_approval = {
            "status": "validated_exact_input_approval", "schema": PBS.INPUT_APPROVAL_SCHEMA,
            "sha256": "a" * 64, "payload_sha256": "b" * 64, "input_sha256": digest,
            "work_kind": "ordinary", "protocol_options_schema": "gaussian-protocol-options/1",
            "protocol_selection_schema": "gaussian-protocol-selection/1",
            "input_review_schema": "gaussian-input-draft-review/2", "no_submission_authorization": True,
        }
        live = {"schema": PBS.LIVE_APPROVAL_V9_SCHEMA, "approval_id": "approval-once", "approver_identity": "fixture"}
        return args, ledger_path, attempt_id, input_approval, live

    def test_v2_to_v3_is_explicit_and_v2_interface_remains_historical(self):
        with tempfile.TemporaryDirectory() as temp:
            path, _ = self.make_ledger(Path(temp)); ledger = RESOURCE.validate_ledger(RESOURCE.load(path))
            self.assertEqual(ledger["schema"], "gaussian-execution-batch/3")
            self.assertEqual(ledger["resource_policy_interface"]["status"], "enforced_for_every_new_live_submit")
            self.assertTrue(any(event["event_type"] == "ledger_migrated_to_v3" for event in ledger["events"]))

    def test_every_hard_limit_fails_closed(self):
        cases = {
            "max_estimated_core_hours": {"max_estimated_core_hours": 3},
            "max_remaining_core_hours": {"max_remaining_core_hours": 3},
            "max_concurrent_unresolved_attempts": {"max_concurrent_unresolved_attempts": 0},
            "max_concurrent_active_attempts": {"max_concurrent_active_attempts": 0},
            "max_total_cores": {"max_total_cores": 7}, "max_total_memory_gb": {"max_total_memory_gb": 11},
            "max_job_cores": {"max_job_cores": 7}, "max_job_memory_gb": {"max_job_memory_gb": 11},
            "max_job_walltime_seconds": {"max_job_walltime_seconds": 3599},
        }
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); path, _ = self.make_ledger(root); snapshot = self.snapshot_artifact(root)
            for label, limits in cases.items():
                with self.subTest(label=label), self.assertRaises(RESOURCE.ResourceError):
                    self.gate(path, self.policy(**limits), snapshot)

    def test_reservation_owner_api_rejects_unsafe_project_and_remote_path(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); path, task = self.make_ledger(root); policy = self.policy(); snapshot = self.snapshot_artifact(root); gate = self.gate(path, policy, snapshot)
            for values in ({"project": "../bad", "remote_workdir": "/home/user100/SDL/../bad"}, {"project": "safejob", "remote_workdir": "/tmp/safejob"}):
                with self.subTest(values=values), self.assertRaises(RESOURCE.ResourceError): self.reserve(path, task, policy, gate, snapshot, **values)
            self.assertEqual(RESOURCE.load(path)["attempts"], [])

    def test_snapshot_is_replayed_and_expiry_blocks_reservation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); path, task = self.make_ledger(root); policy = self.policy(); snapshot = self.snapshot_artifact(root, max_age=60); gate = self.gate(path, policy, snapshot, evaluated="2026-01-01T00:04:30Z")
            changed = copy.deepcopy(snapshot[0]); changed["snapshot_id"] = "changed"; changed = RESOURCE.finalize_scheduler_snapshot(changed)
            with self.assertRaisesRegex(RESOURCE.ResourceError, "differs"):
                RESOURCE.reserve_attempt(path, task, identity=identity("5" * 64), idempotency_key="x", project="safejob", remote_workdir="/home/user100/SDL/safejob", input_sha256="5" * 64, live_approval_id="a", live_approval_sha256="a" * 64, estimated_core_hours_evidence={"source": "x", "sha256": "b" * 64}, reserved_at="2026-01-01T00:04:40Z", audit_reason="x", policy=policy, gate=gate, scheduler_snapshot=changed, scheduler_artifact_sha256=snapshot[1], scheduler_artifact_size=snapshot[2])
            with self.assertRaisesRegex(RESOURCE.ResourceError, "expired"):
                self.reserve(path, task, policy, gate, snapshot)

    def test_pre_qsub_resource_replay_rechecks_freshness_without_command(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); ledger_path, _ = self.make_ledger(root)
            policy = self.policy(); snapshot = self.snapshot_artifact(root, max_age=60)
            gate = self.gate(ledger_path, policy, snapshot, evaluated="2026-01-01T00:04:30Z")
            policy_path = root / "policy.json"; gate_path = root / "gate.json"
            policy_path.write_text(json.dumps(policy, sort_keys=True) + "\n")
            gate_path.write_text(json.dumps(gate, sort_keys=True) + "\n")
            _, policy_sha, policy_size = RESOURCE.load_artifact(policy_path)
            _, gate_sha, gate_size = RESOURCE.load_artifact(gate_path)
            bindings = {"policy": (policy_sha, policy_size), "gate": (gate_sha, gate_size), "scheduler": (snapshot[1], snapshot[2])}
            with mock.patch.object(PBS, "run") as remote, self.assertRaisesRegex(ValueError, "expired"):
                PBS.replay_resource_artifacts_before_qsub(
                    policy_path=policy_path, gate_path=gate_path, scheduler_path=snapshot[3],
                    expected_policy=policy, expected_gate=gate, expected_scheduler=snapshot[0],
                    expected_bindings=bindings, now="2026-01-01T00:06:00Z",
                )
            remote.assert_not_called()

    def test_every_post_reservation_local_failure_releases_budget_before_network(self):
        for failure in ("preexisting_intent", "consumption_publication", "verify"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temp:
                root = Path(temp).resolve()
                args, ledger_path, attempt_id, input_approval, live = self.make_live_submit_fixture(root)
                bundle = root / "bundle"
                if failure == "preexisting_intent":
                    bundle.mkdir(); (bundle / "submission-intent.json").write_text("owner")
                real_publish = PBS.publish_new_json
                def publish(path, value, validator=None):
                    if failure == "consumption_publication" and Path(path).name == "live-approval-consumption.json":
                        raise ValueError("synthetic consumption publication failure")
                    return real_publish(path, value, validator)
                real_verify = PBS.verify_staged_submission; verify_calls = {"count": 0}
                def verify(*values, **kwargs):
                    verify_calls["count"] += 1
                    if failure == "verify" and verify_calls["count"] == 2:
                        raise ValueError("synthetic post-reservation verify failure")
                    return real_verify(*values, **kwargs)
                with mock.patch.object(PBS, "validate_input_approval", return_value=input_approval), \
                     mock.patch.object(PBS, "validate_live_approval_binding", return_value=(live, "d" * 64)), \
                     mock.patch.object(PBS, "publish_new_json", side_effect=publish), \
                     mock.patch.object(PBS, "verify_staged_submission", side_effect=verify), \
                     mock.patch.object(PBS, "run") as network, self.assertRaises(SystemExit):
                    PBS.command_submit(args)
                network.assert_not_called()
                ledger = RESOURCE.load(ledger_path)
                attempt = next(item for item in ledger["attempts"] if item["attempt_id"] == attempt_id)
                self.assertEqual(attempt["state"], "reconciled_not_submitted")
                self.assertEqual(ledger["tasks"][0]["state"], "reviewed")

    def test_unresolved_scheduler_omission_wrong_resources_and_state_conflict_close_gate(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); path, task = self.make_ledger(root); policy = self.policy(); empty = self.snapshot_artifact(root); gate = self.gate(path, policy, empty); attempt = self.reserve(path, task, policy, gate, empty)
            with self.assertRaisesRegex(RESOURCE.ResourceError, "submission_uncertain"): self.gate(path, policy, self.snapshot_artifact(root))
            RESOURCE.reconcile_attempt(path, attempt["attempt_id"], state="submitted", observed_at="2026-01-01T00:07:00Z", reason="fixture", scheduler_reference="123.master", reconciliation_evidence={"source": "fixture", "sha256": "c" * 64})
            for attempts, message in (
                ([], "omitted"),
                ([{"attempt_id": attempt["attempt_id"], "state": "submitted", "cores": 9, "memory_gb": 12}], "conflict"),
                ([{"attempt_id": attempt["attempt_id"], "state": "queued", "cores": 8, "memory_gb": 12}], "conflict"),
            ):
                with self.subTest(message=message), self.assertRaisesRegex(RESOURCE.ResourceError, message):
                    self.gate(path, policy, self.snapshot_artifact(root, attempts))

    def test_reconcile_same_state_is_idempotent_but_different_evidence_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); path, task = self.make_ledger(root); policy = self.policy(); snapshot = self.snapshot_artifact(root); attempt = self.reserve(path, task, policy, self.gate(path, policy, snapshot), snapshot)
            kwargs = {"state": "submitted", "observed_at": "2026-01-01T00:07:00Z", "reason": "fixture", "scheduler_reference": "123.master", "reconciliation_evidence": {"source": "fixture", "sha256": "c" * 64}}
            first = RESOURCE.reconcile_attempt(path, attempt["attempt_id"], **kwargs); second = RESOURCE.reconcile_attempt(path, attempt["attempt_id"], **kwargs)
            self.assertEqual(first, second)
            changed = copy.deepcopy(kwargs); changed["reconciliation_evidence"] = {"source": "fixture", "sha256": "d" * 64}
            with self.assertRaisesRegex(RESOURCE.ResourceError, "differs"): RESOURCE.reconcile_attempt(path, attempt["attempt_id"], **changed)

    def test_accounting_duplicate_is_unknown_and_exact_terminal_binding_reconciles(self):
        duplicate = "Job Id: 123.master\nresources_used.cput = 00:10:00\nresources_used.cput = 00:11:00\nresources_used.walltime = 00:05:00\nncpus = 8\n"
        record = RESOURCE.parse_accounting(duplicate, job_id="123.master", attempt_id="attempt", input_sha256="5" * 64, evidence_source="fixture", collected_at="2026-01-01T01:00:00Z")
        self.assertEqual(record["classification"], "unknown_ambiguous_duplicate"); self.assertIsNone(record["actual_core_hours"]); self.assertEqual(record["parser"]["version"], 1)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); path, task = self.make_ledger(root); policy = self.policy(); snapshot = self.snapshot_artifact(root); attempt = self.reserve(path, task, policy, self.gate(path, policy, snapshot), snapshot)
            RESOURCE.reconcile_attempt(path, attempt["attempt_id"], state="completed", observed_at="2026-01-01T00:07:00Z", reason="terminal", scheduler_reference="123.master", reconciliation_evidence={"source": "fixture", "sha256": "c" * 64})
            missing_identity = RESOURCE.parse_accounting("resources_used.cput = 01:00:00\n", job_id="123.master", attempt_id=attempt["attempt_id"], input_sha256="5" * 64, evidence_source="fixture", collected_at="2026-01-01T00:59:00Z")
            self.assertEqual(missing_identity["classification"], "unknown_job_identity")
            raw = b"Job Id: 123.master\nresources_used.cput = 01:00:00\nresources_used.walltime = 00:10:00\nresources_used.mem = 1gb\nresources_used.vmem = 2gb\nncpus = 8\n"
            known = RESOURCE.parse_accounting(raw.decode(), job_id="123.master", attempt_id=attempt["attempt_id"], input_sha256="5" * 64, evidence_source="fixture accounting", collected_at="2026-01-01T01:00:00Z")
            tampered = copy.deepcopy(known); tampered["actual_core_hours"] = 999; tampered["payload_sha256"] = BATCH.digest_value({key: value for key, value in tampered.items() if key != "payload_sha256"})
            with self.assertRaisesRegex(RESOURCE.ResourceError, "deterministic"):
                RESOURCE.validate_accounting(tampered)
            reconciled = RESOURCE.reconcile_accounting(path, known, raw_evidence=raw); self.assertEqual(reconciled["consumed_core_hours"], 1.0); self.assertEqual(reconciled["estimated_core_hours"], 4)
            wrong = copy.deepcopy(known); wrong["job_id"] = "124.master"; wrong["payload_sha256"] = BATCH.digest_value({key: value for key, value in wrong.items() if key != "payload_sha256"})
            with self.assertRaises(RESOURCE.ResourceError): RESOURCE.reconcile_accounting(path, wrong, raw_evidence=raw)

    def test_monitor_transport_and_freshness_cross_constraints_are_closed(self):
        base = {"collected_at": "2026-01-01T00:00:00Z", "source": "fixture", "freshness": "unknown", "age_seconds": 0, "transport_classification": "timeout", "state": "unknown", "interruption_proof": None, "evidence_sha256": "a" * 64}
        self.assertEqual(RESOURCE.validate_monitor_observation(base), base)
        for mutation in ({"transport_classification": "anything"}, {"transport_classification": "timeout", "state": "running"}, {"transport_classification": "success", "freshness": "stale", "state": "running"}):
            candidate = {**base, **mutation}
            with self.assertRaises(RESOURCE.ResourceError): RESOURCE.validate_monitor_observation(candidate)

    def test_fresh_exact_monitor_reconciles_state_but_unknown_and_conflict_only_append(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); path, task = self.make_ledger(root); policy = self.policy(); snapshot = self.snapshot_artifact(root)
            attempt = self.reserve(path, task, policy, self.gate(path, policy, snapshot), snapshot)
            arbitrary = {"collected_at": "2026-01-01T00:06:30Z", "source": "unbound arbitrary job", "freshness": "fresh", "age_seconds": 0, "transport_classification": "success", "state": "running", "interruption_proof": None, "evidence_sha256": "9" * 64}
            RESOURCE.record_monitor_observation(path, attempt_id=attempt["attempt_id"], project="safejob", job_id="999.master", observation=arbitrary)
            guarded = RESOURCE.load(path); self.assertEqual(guarded["attempts"][0]["state"], "submission_uncertain"); self.assertIsNone(guarded["attempts"][0]["scheduler_reference"])
            self.assertEqual(guarded["events"][-1]["details"]["reconciliation_classification"], "conflict_unknown")
            RESOURCE.reconcile_attempt(path, attempt["attempt_id"], state="submitted", observed_at="2026-01-01T00:07:00Z", reason="fixture", scheduler_reference="123.master", reconciliation_evidence={"source": "fixture", "sha256": "c" * 64})
            queued = {"collected_at": "2026-01-01T00:08:00Z", "source": "one-call exact snapshot", "freshness": "fresh", "age_seconds": 0, "transport_classification": "success", "state": "queued", "interruption_proof": None, "evidence_sha256": "d" * 64}
            RESOURCE.record_monitor_observation(path, attempt_id=attempt["attempt_id"], project="safejob", observation=queued, job_id="123.master")
            self.assertEqual(RESOURCE.load(path)["attempts"][0]["state"], "queued")
            fresh = {"collected_at": "2026-01-01T00:08:30Z", "source": "one-call exact snapshot", "freshness": "fresh", "age_seconds": 0, "transport_classification": "success", "state": "running", "interruption_proof": None, "evidence_sha256": "2" * 64}
            RESOURCE.record_monitor_observation(path, attempt_id=attempt["attempt_id"], project="safejob", observation=fresh, job_id="123.master")
            ledger = RESOURCE.load(path); self.assertEqual(ledger["attempts"][0]["state"], "running")
            unknown = {"collected_at": "2026-01-01T00:09:00Z", "source": "one-call timeout", "freshness": "unknown", "age_seconds": 0, "transport_classification": "timeout", "state": "unknown", "interruption_proof": None, "evidence_sha256": "e" * 64}
            RESOURCE.record_monitor_observation(path, attempt_id=attempt["attempt_id"], project="safejob", observation=unknown, job_id="123.master")
            conflict = {"collected_at": "2026-01-01T00:10:00Z", "source": "one-call conflict", "freshness": "fresh", "age_seconds": 0, "transport_classification": "success", "state": "queued", "interruption_proof": None, "evidence_sha256": "f" * 64}
            RESOURCE.record_monitor_observation(path, attempt_id=attempt["attempt_id"], project="safejob", observation=conflict, job_id="123.master")
            ledger = RESOURCE.load(path); self.assertEqual(ledger["attempts"][0]["state"], "running")
            self.assertEqual(ledger["events"][-1]["details"]["reconciliation_classification"], "conflict_unknown")
            interrupted = {"collected_at": "2026-01-01T00:11:00Z", "source": "repeated stable exact interruption proof", "freshness": "fresh", "age_seconds": 0, "transport_classification": "success", "state": "interrupted", "interruption_proof": {"stable_repeats": 2, "scheduler_record_absent": True, "log_signature_stable": True, "normal_termination_absent": True, "stable_duration_seconds": 60, "log_age_seconds": 60, "full_normal_termination_count": 0, "full_error_termination_count": 0}, "evidence_sha256": "1" * 64}
            RESOURCE.record_monitor_observation(path, attempt_id=attempt["attempt_id"], project="safejob", observation=interrupted, job_id="123.master")
            ledger = RESOURCE.load(path); self.assertEqual(ledger["attempts"][0]["state"], "failed")
            self.assertFalse(ledger["events"][-2]["details"]["scientific_conclusion_changed"])

    def test_append_only_monitor_journal_does_not_starve_another_resource_gate(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            review = BATCH.finalize_review(json.loads((ROOT / "tests/fixtures/rtwin_pbs/execution_batch_review.template.json").read_text()))
            review_path = root / "review.json"; review_path.write_text(json.dumps(review))
            ledger_path = root / "ledger.json"
            BATCH.initialize(review_path, ledger_path, timestamp="2026-01-01T00:00:00Z")
            first = BATCH.admit_task(ledger_path, identity("5" * 64), estimated_core_hours=4, reason="first", reviewer="fixture", reviewed_at="2026-01-01T00:01:00Z")
            second = BATCH.admit_task(ledger_path, identity("6" * 64, "6"), estimated_core_hours=4, reason="second", reviewer="fixture", reviewed_at="2026-01-01T00:01:30Z")
            BATCH.migrate_to_submission_ledger(ledger_path, migrated_at="2026-01-01T00:02:00Z", migration_source="fixture")
            RESOURCE.migrate_v2_to_v3(ledger_path, migrated_at="2026-01-01T00:03:00Z", migration_source="fixture")
            policy = self.policy(); empty = self.snapshot_artifact(root, collected="2026-01-01T00:04:00Z")
            ledger = RESOURCE.load(ledger_path)
            first_attempt_id = BATCH.attempt_id_for(ledger["batch"]["batch_id"], "first-key")
            first_gate = RESOURCE.evaluate_gate(
                ledger, policy, empty[0], gate_id="first-gate", evaluated_at="2026-01-01T00:05:00Z",
                scientific_task_id=first["scientific_task_id"], attempt_id=first_attempt_id,
                project="safejob", input_sha256="5" * 64, resource_tier="simple", cores=8,
                memory_gb=12, walltime_seconds=3600, estimated_core_hours=4,
                scheduler_artifact_sha256=empty[1], scheduler_artifact_size=empty[2],
            )
            first_attempt = RESOURCE.reserve_attempt(
                ledger_path, first["scientific_task_id"], identity=identity("5" * 64),
                idempotency_key="first-key", project="safejob", remote_workdir="/home/user100/SDL/safejob",
                input_sha256="5" * 64, live_approval_id="first-approval", live_approval_sha256="a" * 64,
                estimated_core_hours_evidence={"source": "fixture", "sha256": "b" * 64},
                reserved_at="2026-01-01T00:06:00Z", audit_reason="first", policy=policy, gate=first_gate,
                scheduler_snapshot=empty[0], scheduler_artifact_sha256=empty[1], scheduler_artifact_size=empty[2],
            )
            RESOURCE.reconcile_attempt(
                ledger_path, first_attempt["attempt_id"], state="submitted", observed_at="2026-01-01T00:07:00Z",
                reason="submitted", scheduler_reference="123.master",
                reconciliation_evidence={"source": "fixture", "sha256": "c" * 64},
            )
            active = self.snapshot_artifact(root, attempts=[{
                "attempt_id": first_attempt["attempt_id"], "state": "submitted",
                "cores": 8, "memory_gb": 12,
            }], collected="2026-01-01T00:08:00Z")
            ledger = RESOURCE.load(ledger_path)
            second_attempt_id = BATCH.attempt_id_for(ledger["batch"]["batch_id"], "second-key")
            second_gate = RESOURCE.evaluate_gate(
                ledger, policy, active[0], gate_id="second-gate", evaluated_at="2026-01-01T00:09:00Z",
                scientific_task_id=second["scientific_task_id"], attempt_id=second_attempt_id,
                project="secondjob", input_sha256="6" * 64, resource_tier="simple", cores=8,
                memory_gb=12, walltime_seconds=3600, estimated_core_hours=4,
                scheduler_artifact_sha256=active[1], scheduler_artifact_size=active[2],
            )
            state_before = (ledger["resource_state_revision"], ledger["resource_state_sha256"])
            observation = {"collected_at": "2026-01-01T00:09:30Z", "source": "timeout journal", "freshness": "unknown", "age_seconds": 0, "transport_classification": "timeout", "state": "unknown", "interruption_proof": None, "evidence_sha256": "d" * 64}
            RESOURCE.record_monitor_observation(ledger_path, attempt_id=first_attempt["attempt_id"], project="safejob", job_id="123.master", observation=observation)
            journaled = RESOURCE.load(ledger_path)
            self.assertGreater(journaled["revision"], ledger["revision"])
            self.assertEqual((journaled["resource_state_revision"], journaled["resource_state_sha256"]), state_before)
            reserved = RESOURCE.reserve_attempt(
                ledger_path, second["scientific_task_id"], identity=identity("6" * 64, "6"),
                idempotency_key="second-key", project="secondjob", remote_workdir="/home/user100/SDL/secondjob",
                input_sha256="6" * 64, live_approval_id="second-approval", live_approval_sha256="e" * 64,
                estimated_core_hours_evidence={"source": "fixture", "sha256": "f" * 64},
                reserved_at="2026-01-01T00:10:00Z", audit_reason="second", policy=policy, gate=second_gate,
                scheduler_snapshot=active[0], scheduler_artifact_sha256=active[1], scheduler_artifact_size=active[2],
            )
            self.assertEqual(reserved["attempt_id"], second_attempt_id)

    def test_retry_wrapper_never_wraps_mutating_commands(self):
        for command in (["qsub", "job.pbs"], ["qdel", "123.master"], ["scp", "a", "b"], ["ssh", "host", "touch", "x"], ["ssh", "host", "rm", "x"], ["ssh", "host", "tee", "x"], ["ssh", "host", "chmod", "x"], ["ssh", "host", "Set-Content", "x"], ["ssh", "host", "sh", "-c", "> x"]):
            with self.assertRaises(ValueError): PBS.run_read_only(command)
        command = ["ssh", "-F", "cfg", "rtwin", "ssh", "-F", "wcfg", "server", "bash", "-s"]; script = PBS.COMPLETE_USER_QSTAT_SCRIPT
        with self.assertRaises(ValueError):
            PBS._exact_read_only_capability("complete_user_qstat", ["sh", "-c", "touch /tmp/x", *command], script)
        with self.assertRaises(ValueError):
            PBS._exact_read_only_capability("complete_user_qstat", command, b"rm -f /tmp/x\n")
        capability = PBS._exact_read_only_capability("complete_user_qstat", command, script)
        with mock.patch.object(PBS, "run", side_effect=[subprocess.CompletedProcess([], 255, "", "lost"), subprocess.CompletedProcess([], 0, "ok", "")]) as run, mock.patch.object(PBS.time, "sleep"):
            result = PBS.run_read_only(command, input_bytes=script, capability=capability)
        self.assertEqual(result.returncode, 0); self.assertEqual(run.call_count, 2)

    def test_single_job_snapshot_and_batch_status_each_use_one_remote_call(self):
        def b64(text): return base64.b64encode(text.encode()).decode()
        now_epoch = int(time.time())
        framed = "\n".join([
            f"COLLECTED_EPOCH\t{now_epoch}", "QSTAT_RC\t0",
            "QSTAT_B64\t" + b64("Job Id: 123.master\n    Job_Name = safejob\n    job_state = Q\n"),
            "PROCESS_RC\t125", "PROCESS_B64\t", "MANIFEST_RC\t1", "MANIFEST_B64\t",
            "TAIL_RC\t0", "TAIL_B64\t" + b64("SCF Done"), f"LOG_STAT\t10:{now_epoch}",
            "NORMAL_COUNT\t0", "ERROR_COUNT\t0",
        ]) + "\n"
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / "config"; config.write_text("Host rtwin\n")
            args = SimpleNamespace(mac_ssh_config=str(config), rtwin_alias="rtwin", windows_server_config="cfg", server_alias="server")
            with mock.patch.object(PBS, "run_read_only", return_value=subprocess.CompletedProcess([], 0, framed, "")) as remote:
                inspection = PBS.inspect_job(args, "safejob", "input", "123.master")
            self.assertEqual(remote.call_count, 1); self.assertEqual(inspection["schema"], "gaussian-job-inspection/2")
            qstat = "AUTO_G16_OWNER\tfixture\nJob Id: 123.master\n    Job_Owner = fixture@host\n    Job_Name = a\n    job_state = R\nJob Id: 124.master\n    Job_Owner = fixture@host\n    Job_Name = b\n    job_state = Q\n"
            with mock.patch.object(PBS, "run_read_only", return_value=subprocess.CompletedProcess([], 0, qstat, "")) as remote:
                batch = PBS.batch_qstat_snapshot(args, ["123.master", "124.master"])
            self.assertEqual(remote.call_count, 1); self.assertEqual(set(batch["records"]), {"123.master", "124.master"})

    def test_future_remote_clock_is_unknown_and_single_snapshot_retains_session_for_zombie(self):
        def b64(text): return base64.b64encode(text.encode()).decode()
        now_epoch = int(time.time())
        def frame(epoch, normal=0):
            return "\n".join([
                f"COLLECTED_EPOCH\t{epoch}", "QSTAT_RC\t0",
                "QSTAT_B64\t" + b64("Job Id: 123.master\n    Job_Name = safejob\n    job_state = R\n    session_id = 77\n"),
                "PROCESS_RC\t1", "PROCESS_B64\t", "MANIFEST_RC\t1", "MANIFEST_B64\t",
                "TAIL_RC\t0", "TAIL_B64\t" + b64("tail without terminal marker"),
                f"LOG_STAT\t100:{now_epoch - 120}", f"NORMAL_COUNT\t{normal}", "ERROR_COUNT\t0",
            ]) + "\n"
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / "config"; config.write_text("Host rtwin\n")
            args = SimpleNamespace(mac_ssh_config=str(config), rtwin_alias="rtwin", windows_server_config="cfg", server_alias="server")
            with mock.patch.object(PBS, "run_read_only", return_value=subprocess.CompletedProcess([], 0, frame(now_epoch + PBS.MAX_REMOTE_CLOCK_SKEW_SECONDS + 30), "")):
                bad_clock = PBS.inspect_job(args, "safejob", "input", "123.master")
            self.assertEqual(bad_clock["state"], "unknown")
            self.assertEqual(bad_clock["freshness"], "unknown")
            self.assertEqual(bad_clock["transport_classification"], "parse_failed")
            with mock.patch.object(PBS, "run_read_only", return_value=subprocess.CompletedProcess([], 0, frame(now_epoch, 1), "")):
                exact = PBS.inspect_job(args, "safejob", "input", "123.master")
            self.assertEqual(exact["session_id"], "77")
            diagnosis = PBS.assess_zombie_observations("safejob", "123.master", [exact, copy.deepcopy(exact)])
            self.assertEqual(diagnosis["classification"], "confirmed_scheduler_zombie")
            self.assertTrue(diagnosis["cleanup_eligible"])

    def test_whole_log_terminal_outside_tail_publishes_receipt_reconciles_and_fetches(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve(); ledger_path, attempt, local_dir = self.make_submitted_bundle(root)
            completed = self.inspection("completed", normal=1)
            args = self.watch_args(root, ledger_path, attempt["attempt_id"], fetch=True)
            def fetched(_args, _project, output_dir):
                transfer = {"snapshot_complete": True}
                (output_dir / "transfer.json").write_text(json.dumps(transfer))
                (output_dir / "result.json").write_text("{}")
                return transfer
            with mock.patch.object(PBS, "inspect_job", return_value=completed), mock.patch.object(PBS, "fetch_results", side_effect=fetched) as fetch:
                PBS.command_watch(args)
            self.assertEqual(fetch.call_count, 1)
            receipt = json.loads((local_dir / "terminal-inspection.json").read_text())
            self.assertEqual(receipt["terminal_state"], "completed")
            self.assertEqual(receipt["inspection"]["full_normal_termination_count"], 1)
            self.assertTrue(PBS.read_job_state(local_dir)["results_fetched"])
            self.assertEqual(RESOURCE.load(ledger_path)["attempts"][0]["state"], "completed")

    def test_transient_absence_and_stale_present_record_never_interrupt_or_release(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve(); ledger_path, attempt, local_dir = self.make_submitted_bundle(root)
            args = self.watch_args(root, ledger_path, attempt["attempt_id"])
            transient = self.inspection("unknown", pbs_present=False, candidate=True, mtime=1)
            with mock.patch.object(PBS, "inspect_job", return_value=copy.deepcopy(transient)), \
                 mock.patch.object(PBS.time, "monotonic", side_effect=[0, 0, 1, 11]), \
                 mock.patch.object(PBS.time, "time", side_effect=[100, 100, 102]), \
                 mock.patch.object(PBS.time, "sleep"), self.assertRaises(SystemExit):
                PBS.command_watch(args)
            self.assertFalse((local_dir / "terminal-inspection.json").exists())
            self.assertEqual(RESOURCE.load(ledger_path)["attempts"][0]["state"], "submitted")

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve(); ledger_path, attempt, local_dir = self.make_submitted_bundle(root)
            args = self.watch_args(root, ledger_path, attempt["attempt_id"])
            stale_present = self.inspection("stale", pbs_state="R", pbs_present=True, candidate=False, mtime=1)
            with mock.patch.object(PBS, "inspect_job", return_value=copy.deepcopy(stale_present)), \
                 mock.patch.object(PBS.time, "monotonic", side_effect=[0, 0, 61, 71]), \
                 mock.patch.object(PBS.time, "sleep"), self.assertRaises(SystemExit):
                PBS.command_watch(args)
            self.assertFalse((local_dir / "terminal-inspection.json").exists())
            self.assertEqual(RESOURCE.load(ledger_path)["attempts"][0]["state"], "submitted")

    def test_held_and_exiting_are_append_only_and_watch_passes_exact_project_binding(self):
        for state, pbs_state in (("held", "H"), ("exiting", "E")):
            with self.subTest(state=state), tempfile.TemporaryDirectory() as temp:
                root = Path(temp).resolve(); ledger_path, attempt, _ = self.make_submitted_bundle(root)
                args = self.watch_args(root, ledger_path, attempt["attempt_id"])
                observed = self.inspection(state, pbs_state=pbs_state, pbs_present=True)
                with mock.patch.object(PBS, "inspect_job", return_value=observed), \
                     mock.patch.object(PBS.time, "monotonic", side_effect=[0, 0, 11]), \
                     mock.patch.object(PBS.time, "sleep"), self.assertRaises(SystemExit):
                    PBS.command_watch(args)
                ledger = RESOURCE.load(ledger_path)
                self.assertEqual(ledger["attempts"][0]["state"], "submitted")
                event = next(event for event in reversed(ledger["events"]) if event["event_type"] == "read_only_monitor_observation")
                self.assertEqual(event["details"]["project"], "safejob")
                self.assertEqual(event["details"]["state"], "unknown")

    def test_cross_job_local_binding_and_tampered_terminal_receipt_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve(); ledger_path, attempt, local_dir = self.make_submitted_bundle(root)
            args = self.watch_args(root, ledger_path, attempt["attempt_id"]); args.job_id = "999.master"
            completed = self.inspection("completed", normal=1); completed["job_id"] = "999.master"
            completed["evidence_sha256"] = PBS.canonical_digest({key: value for key, value in completed.items() if key != "evidence_sha256"})
            with mock.patch.object(PBS, "inspect_job", return_value=completed), self.assertRaises(SystemExit):
                PBS.command_watch(args)
            self.assertFalse((local_dir / "terminal-inspection.json").exists())
            self.assertEqual(PBS.read_job_state(local_dir)["status"], "submitted")

            exact = self.inspection("completed", normal=1)
            job = PBS.validate_local_job_binding(local_dir, "safejob", "123.master", "input", require_fetched=False, expected_attempt_id=attempt["attempt_id"])
            PBS.publish_terminal_inspection_receipt(local_dir, job, exact, "input")
            receipt_path = local_dir / "terminal-inspection.json"
            receipt = json.loads(receipt_path.read_text()); receipt["terminal_state"] = "failed"
            receipt_path.write_text(json.dumps(receipt))
            with self.assertRaises(SystemExit):
                PBS.validate_terminal_inspection_receipt(local_dir, job, "safejob", "123.master", "input")

    def test_one_batch_poll_builds_closed_snapshot_then_operational_gate_without_inference(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); ledger_path, task_id = self.make_ledger(root)
            config = root / "config"; config.write_text("Host rtwin\n")
            args = SimpleNamespace(mac_ssh_config=str(config), rtwin_alias="rtwin", windows_server_config="cfg", server_alias="server")
            qstat = "AUTO_G16_OWNER\tfixture\nJob Id: 999.master\n    Job_Owner = fixture@host\n    Job_Name = external\n    job_state = R\n    Resource_List.nodes = 2:ppn=8\n    Resource_List.mem = 4gb\n"
            with mock.patch.object(PBS, "run_read_only", return_value=subprocess.CompletedProcess([], 0, qstat, "")) as remote:
                observation = PBS.batch_qstat_snapshot(args, [])
            self.assertEqual(remote.call_count, 1)
            self.assertEqual(observation["scope"]["completeness"], "complete")
            scheduler = RESOURCE.build_scheduler_snapshot(RESOURCE.load(ledger_path), observation, snapshot_id="built-snapshot", max_age_seconds=300)
            self.assertEqual(scheduler["attempts"][0]["cores"], 16); self.assertEqual(scheduler["attempts"][0]["memory_gb"], 4)
            scheduler_path = root / "built-scheduler.json"; scheduler_path.write_text(json.dumps(scheduler, sort_keys=True) + "\n")
            scheduler_doc, scheduler_sha, scheduler_size = RESOURCE.load_artifact(scheduler_path)
            ledger = RESOURCE.load(ledger_path)
            gate = RESOURCE.evaluate_gate(
                ledger, self.policy(), scheduler_doc, gate_id="built-gate", evaluated_at=observation["collected_at"],
                scientific_task_id=task_id, attempt_id=BATCH.attempt_id_for(ledger["batch"]["batch_id"], "key-1"),
                project="safejob", input_sha256="5" * 64, resource_tier="simple", cores=8,
                memory_gb=12, walltime_seconds=3600, estimated_core_hours=4,
                scheduler_artifact_sha256=scheduler_sha, scheduler_artifact_size=scheduler_size,
            )
            self.assertEqual(gate["status"], "passed")
            missing = copy.deepcopy(observation); missing["records"]["999.master"]["cores"] = None
            missing["evidence_sha256"] = BATCH.digest_value({key: value for key, value in missing.items() if key != "evidence_sha256"})
            with self.assertRaisesRegex(RESOURCE.ResourceError, "cores/memory"):
                RESOURCE.build_scheduler_snapshot(ledger, missing, snapshot_id="bad", max_age_seconds=300)

            zero_output = "AUTO_G16_OWNER\tfixture\n"
            with mock.patch.object(PBS, "run_read_only", return_value=subprocess.CompletedProcess([], 0, zero_output, "")) as remote:
                zero = PBS.batch_qstat_snapshot(args)
            self.assertEqual(remote.call_count, 1)
            zero_scheduler = RESOURCE.build_scheduler_snapshot(ledger, zero, snapshot_id="zero", max_age_seconds=300)
            self.assertEqual(zero_scheduler["attempts"], [])
            with mock.patch.object(PBS, "run_read_only", return_value=subprocess.CompletedProcess([], 153, zero_output, "unknown")):
                unproven_empty = PBS.batch_qstat_snapshot(args)
            self.assertNotEqual(unproven_empty["transport_classification"], "success")
            with self.assertRaisesRegex(RESOURCE.ResourceError, "unknown"):
                RESOURCE.build_scheduler_snapshot(ledger, unproven_empty, snapshot_id="rc153", max_age_seconds=300)
            warning_only = "AUTO_G16_OWNER\tfixture\nqstat: PARTIAL WARNING\n"
            with mock.patch.object(PBS, "run_read_only", return_value=subprocess.CompletedProcess([], 0, warning_only, "")):
                warning_snapshot = PBS.batch_qstat_snapshot(args)
            self.assertEqual(warning_snapshot["transport_classification"], "parse_failed")
            self.assertEqual(warning_snapshot["scope"]["completeness"], "unknown")
            trailing_warning = qstat + "qstat: PARTIAL WARNING\n"
            with mock.patch.object(PBS, "run_read_only", return_value=subprocess.CompletedProcess([], 0, trailing_warning, "")):
                trailing_snapshot = PBS.batch_qstat_snapshot(args)
            self.assertEqual(trailing_snapshot["transport_classification"], "parse_failed")
            self.assertEqual(trailing_snapshot["records"], {})
            malformed = copy.deepcopy(observation); malformed["records"]["999.master"]["extra"] = True
            malformed["evidence_sha256"] = BATCH.digest_value({key: value for key, value in malformed.items() if key != "evidence_sha256"})
            with self.assertRaisesRegex(RESOURCE.ResourceError, "exactly"):
                RESOURCE.build_scheduler_snapshot(ledger, malformed, snapshot_id="extra", max_age_seconds=300)

    def test_package4_schemas_are_closed_and_match_owner_validators(self):
        schema_paths = [
            ROOT / "contracts/rtwin-pbs/resource-policy.schema.json",
            ROOT / "contracts/rtwin-pbs/scheduler-resource-snapshot.schema.json",
            ROOT / "contracts/rtwin-pbs/resource-gate.schema.json",
            ROOT / "contracts/rtwin-pbs/resource-accounting.schema.json",
            ROOT / "contracts/rtwin-pbs/execution-batch-v3.schema.json",
            ROOT / "contracts/rtwin-pbs/live-submission-approval-v9.schema.json",
            ROOT / "contracts/rtwin-pbs/live-submission-approval-v10.schema.json",
            ROOT / "contracts/rtwin-pbs/live-submission-approval-v11.schema.json",
        ]
        for path in schema_paths:
            document = json.loads(path.read_text())
            stack = [("$", document)]
            while stack:
                location, node = stack.pop()
                if isinstance(node, dict):
                    if node.get("type") == "object":
                        self.assertIs(node.get("additionalProperties"), False, f"{path.name}:{location}")
                    stack.extend((f"{location}.{key}", value) for key, value in node.items())
                elif isinstance(node, list):
                    stack.extend((f"{location}[{index}]", value) for index, value in enumerate(node))
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); ledger_path, _ = self.make_ledger(root)
            policy = self.policy(); snapshot = self.snapshot_artifact(root)
            gate = self.gate(ledger_path, policy, snapshot)
            instances = [
                (schema_paths[0], policy), (schema_paths[1], snapshot[0]),
                (schema_paths[2], gate), (schema_paths[4], RESOURCE.load(ledger_path)),
            ]
            for path, instance in instances:
                schema = json.loads(path.read_text())
                SCHEMA_VALIDATOR._validate_schema_instance(instance, schema, schema)
                mutated = copy.deepcopy(instance); mutated["unexpected"] = True
                with self.assertRaises(Exception):
                    SCHEMA_VALIDATOR._validate_schema_instance(mutated, schema, schema)

        batch_schema = json.loads((ROOT / "contracts/rtwin-pbs/batch-qstat-snapshot.schema.json").read_text())
        self.assertFalse(batch_schema["additionalProperties"])
        self.assertFalse(batch_schema["$defs"]["record"]["additionalProperties"])

    def test_immutable_output_publication_is_no_clobber_and_symlink_safe(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve(); target = root / "artifact.json"
            target.write_text("owner")
            with self.assertRaisesRegex(RESOURCE.ResourceError, "overwrite"):
                RESOURCE._write_new(target, {"value": 1})
            self.assertEqual(target.read_text(), "owner")
            target.unlink(); raced = {"done": False}; real_link = RESOURCE.os.link
            def race(source, destination, **kwargs):
                if not raced["done"]:
                    raced["done"] = True
                    (root / destination).write_text("racer")
                return real_link(source, destination, **kwargs)
            with mock.patch.object(RESOURCE.os, "link", side_effect=race), self.assertRaisesRegex(RESOURCE.ResourceError, "overwrite"):
                RESOURCE._write_new(target, {"value": 2})
            self.assertEqual(target.read_text(), "racer")
            real = root / "real"; real.mkdir(); linked = root / "linked"; linked.symlink_to(real, target_is_directory=True)
            with self.assertRaisesRegex(RESOURCE.ResourceError, "symlink"):
                RESOURCE._write_new(linked / "blocked.json", {"value": 3})

    def test_pbs_script_matches_exact_input_resources_and_walltime(self):
        script = PBS.pbs_text("safejob", "input.gjf", 8, mem_gb=12, walltime_seconds=3661, resource_tier="simple")
        self.assertIn("nodes=1:ppn=8", script); self.assertIn("mem=12gb", script); self.assertIn("walltime=01:01:01", script); self.assertIn("RESOURCE_TIER=simple", script)

    def test_incremental_reuse_requires_exact_binding_and_rehashed_local_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve(); old = root / "old"; old.mkdir(); data = b"immutable"; (old / "input.log").write_bytes(data)
            digest = __import__("hashlib").sha256(data).hexdigest(); transfer = {"schema": "gaussian-fetch-snapshot/1", "project": "safejob", "job_id": "123.master", "input_stem": "input", "snapshot_complete": True, "terminal_inspection_receipt_sha256": "a" * 64, "artifacts": {"input.log": {"sha256": digest, "size": len(data)}}, "per_hop": {"input.log": {"server_sha256": digest, "rtwin_sha256": digest, "mac_sha256": digest, "size": len(data)}}, "payload_sha256": ""}
            transfer["payload_sha256"] = BATCH.digest_value({key: value for key, value in transfer.items() if key != "payload_sha256"})
            (old / "transfer.json").write_text(json.dumps(transfer))
            reusable = PBS.reusable_snapshot_files(str(old), {"project": "safejob", "job_id": "123.master", "input_stem": "input", "snapshot_id": "new"}, {"input.log": {"sha256": digest, "size": len(data)}})
            self.assertEqual(reusable, {"input.log": old / "input.log"})
            tampered_transfer = copy.deepcopy(transfer)
            tampered_transfer["job_id"] = "999.master"
            (old / "transfer.json").write_text(json.dumps(tampered_transfer))
            with self.assertRaises(SystemExit):
                PBS.reusable_snapshot_files(str(old), {"project": "safejob", "job_id": "123.master", "input_stem": "input", "snapshot_id": "new"}, {"input.log": {"sha256": digest, "size": len(data)}})
            (old / "transfer.json").write_text(json.dumps(transfer))
            new = root / "new"; new.mkdir(); copied = new / "input.log"
            PBS.atomic_private_reuse_copy(old / "input.log", copied, {"sha256": digest, "size": len(data)})
            self.assertNotEqual((old / "input.log").stat().st_ino, copied.stat().st_ino)
            (old / "input.log").chmod(0o600); (old / "input.log").write_bytes(b"changed")
            self.assertEqual(copied.read_bytes(), data)
            occupied = new / "occupied.log"; occupied.write_bytes(b"owner")
            with self.assertRaises(SystemExit): PBS.atomic_private_reuse_copy(copied, occupied, {"sha256": digest, "size": len(data)})
            self.assertEqual(occupied.read_bytes(), b"owner")
            partial = root / "partial"; marker = PBS.begin_fetch_snapshot(partial, {"project": "safejob", "job_id": "123.master", "input_stem": "input", "snapshot_id": "partial"})
            partial_target = partial / "input.log"; partial_target.write_bytes(b"preexisting")
            with self.assertRaises(SystemExit): PBS.atomic_private_reuse_copy(copied, partial_target, {"sha256": digest, "size": len(data)})
            self.assertTrue(marker.exists()); self.assertFalse((partial / "transfer.json").exists())
            self.assertEqual(PBS.reusable_snapshot_files(str(old), {"project": "safejob", "job_id": "123.master", "input_stem": "input", "snapshot_id": "new"}, {"input.log": {"sha256": digest, "size": len(data)}}), {})


if __name__ == "__main__": unittest.main()
