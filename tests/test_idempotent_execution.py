#!/usr/bin/env python3
"""Offline adversarial tests for idempotent protected submission transactions."""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock
from types import SimpleNamespace


ROOT = Path(__file__).parents[1]
SCRIPTS = ROOT / "skills" / "auto-g16-rtwin-pbs" / "scripts"
sys.path.insert(0, str(SCRIPTS))


def load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BATCH = load("idempotent_execution_batch", "execution_batch.py")
PBS = load("idempotent_gaussian_rtwin_pbs", "gaussian_rtwin_pbs.py")


def load_path(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SCHEMA = load_path(
    "idempotent_schema_validator", ROOT / "scripts" / "validate_asymmetric_contract.py"
)


def identity(input_sha256: str) -> dict[str, str]:
    return {
        "structure_sha256": "1" * 64,
        "chemical_hypothesis_sha256": "2" * 64,
        "method_protocol_sha256": "3" * 64,
        "calculation_objective_sha256": "4" * 64,
        "relevant_input_sha256": input_sha256,
    }


class IdempotentExecutionTests(unittest.TestCase):
    def make_v2_ledger(self, root: Path, input_sha256: str = "5" * 64):
        template = json.loads(
            (ROOT / "tests/fixtures/rtwin_pbs/execution_batch_review.template.json").read_text()
        )
        review = BATCH.finalize_review(template)
        review_path = root / "review.json"
        review_path.write_text(json.dumps(review))
        ledger_path = root / "ledger.json"
        BATCH.initialize(review_path, ledger_path, timestamp="2026-01-01T00:00:00Z")
        admitted = BATCH.admit_task(
            ledger_path,
            identity(input_sha256),
            estimated_core_hours=4,
            reason="synthetic exact task",
            reviewer="fixture-reviewer",
            reviewed_at="2026-01-01T00:01:00Z",
        )
        BATCH.migrate_to_submission_ledger(
            ledger_path,
            migrated_at="2026-01-01T00:02:00Z",
            migration_source="fixture_review_and_estimate",
        )
        return ledger_path, admitted["scientific_task_id"]

    def fake_input_approval(self, input_sha256: str) -> dict:
        return {
            "status": "validated_exact_input_approval",
            "schema": PBS.INPUT_APPROVAL_SCHEMA,
            "sha256": "a" * 64,
            "payload_sha256": "b" * 64,
            "input_sha256": input_sha256,
            "work_kind": "ordinary",
            "protocol_options_schema": "gaussian-protocol-options/1",
            "protocol_selection_schema": "gaussian-protocol-selection/1",
            "input_review_schema": "gaussian-input-draft-review/2",
            "no_submission_authorization": True,
        }

    def submit_args(self, root: Path, source: Path, ledger_path: Path, task_id: str):
        approval_path = root / "live.json"
        approval_path.write_text("{}")
        input_approval_path = root / "input-approval.json"
        input_approval_path.write_text("{}")
        config = root / "ssh_config"
        config.write_text("Host rtwin\n")
        return PBS.build_parser().parse_args([
            "submit", str(source), "--project", "safejob", "--local-dir", str(root / "bundle"),
            "--work-kind", "ordinary", "--input-approval-record", str(input_approval_path),
            "--approval-record", str(approval_path), "--execution-batch-ledger", str(ledger_path),
            "--scientific-task-id", task_id, "--idempotency-key", "attempt-key",
            "--estimated-core-hours", "4", "--estimated-core-hours-evidence-source", "fixture",
            "--estimated-core-hours-evidence-sha256", "f" * 64,
            "--mac-ssh-config", str(config), "--confirmed",
        ])

    def reserve(self, ledger_path: Path, task_id: str, *, key: str = "attempt-1", approval_id: str = "approval-1", approval_sha: str = "a" * 64):
        return BATCH.reserve_submission_attempt(
            ledger_path,
            task_id,
            identity=identity("5" * 64),
            idempotency_key=key,
            project="safejob",
            remote_workdir="/home/user100/SDL/safejob",
            input_sha256="5" * 64,
            live_approval_id=approval_id,
            live_approval_sha256=approval_sha,
            estimated_core_hours=4,
            estimated_core_hours_evidence={"source": "fixture_estimate", "sha256": "b" * 64},
            reserved_at="2026-01-01T00:03:00Z",
            audit_reason="offline exact reservation fixture",
        )

    def test_v1_migration_is_explicit_hash_bound_and_v2_schema_valid(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            ledger_path, _ = self.make_v2_ledger(Path(temp))
            ledger = BATCH.validate_submission_ledger(BATCH.load_json(ledger_path))
            self.assertEqual(ledger["schema"], "gaussian-execution-batch/2")
            evidence = ledger["tasks"][0]["initial_estimated_core_hours_evidence"]
            self.assertEqual(evidence["source"], "fixture_review_and_estimate")
            self.assertRegex(evidence["sha256"], r"^[a-f0-9]{64}$")
            self.assertFalse(ledger["resource_policy_interface"]["hard_budget_gate_implemented"])

    def test_concurrent_reservation_allows_one_and_replay_cannot_duplicate_qsub_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            ledger_path, task_id = self.make_v2_ledger(Path(temp))

            def worker(index: int) -> str:
                try:
                    self.reserve(
                        ledger_path,
                        task_id,
                        key=f"attempt-{index}",
                        approval_id=f"approval-{index}",
                        approval_sha=f"{index + 1:064x}",
                    )
                    return "reserved"
                except BATCH.BatchError:
                    return "blocked"

            with ThreadPoolExecutor(max_workers=12) as pool:
                results = list(pool.map(worker, range(12)))
            self.assertEqual(results.count("reserved"), 1)
            ledger = BATCH.validate_submission_ledger(BATCH.load_json(ledger_path))
            self.assertEqual(len(ledger["attempts"]), 1)

    def test_one_time_approval_reuse_and_empty_scheduler_reference_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            ledger_path, task_id = self.make_v2_ledger(Path(temp))
            attempt = self.reserve(ledger_path, task_id)
            with self.assertRaisesRegex(BATCH.BatchError, "scheduler_reference"):
                BATCH.reconcile_submission_attempt(
                    ledger_path,
                    attempt["attempt_id"],
                    state="submitted",
                    observed_at="2026-01-01T00:04:00Z",
                    reason="empty reference forbidden",
                    scheduler_reference="",
                    reconciliation_evidence={"source": "fixture", "sha256": "c" * 64},
                )
            BATCH.reconcile_submission_attempt(
                ledger_path,
                attempt["attempt_id"],
                state="reconciled_not_submitted",
                observed_at="2026-01-01T00:04:00Z",
                reason="definitively negative fixture",
                reconciliation_evidence={"source": "fixture", "sha256": "c" * 64},
            )
            with self.assertRaisesRegex(BATCH.BatchError, "one-time live approval"):
                self.reserve(ledger_path, task_id, key="attempt-2")

    def test_reconcile_zero_one_and_multiple_are_distinct_and_never_retry(self) -> None:
        project = "safejob"
        digest = "5" * 64
        attempt = "qsub-attempt-" + "6" * 64
        intent = {"project": project, "job_name": project, "input_sha256": digest, "attempt_id": attempt}
        block = (
            "Job Id: 123.master\n"
            "    Job_Name = safejob\n"
            f"    Variable_List = AUTO_G16_ATTEMPT_ID={attempt},AUTO_G16_INPUT_SHA256={digest}\n"
        )
        zero = PBS.classify_submission_reconciliation(
            project=project, input_sha256=digest, attempt_id=attempt,
            directory_present=True, remote_intent=intent, remote_receipt=None, qstat_text="",
        )
        one = PBS.classify_submission_reconciliation(
            project=project, input_sha256=digest, attempt_id=attempt,
            directory_present=True, remote_intent=intent, remote_receipt=None, qstat_text=block,
        )
        multiple = PBS.classify_submission_reconciliation(
            project=project, input_sha256=digest, attempt_id=attempt,
            directory_present=True, remote_intent=intent, remote_receipt=None,
            qstat_text=block + block.replace("123.master", "124.master"),
        )
        absent = PBS.classify_submission_reconciliation(
            project=project, input_sha256=digest, attempt_id=attempt,
            directory_present=False, remote_intent=None, remote_receipt=None, qstat_text="",
        )
        contradictory = PBS.classify_submission_reconciliation(
            project=project, input_sha256=digest, attempt_id=attempt,
            directory_present=False, remote_intent=None, remote_receipt=None, qstat_text=block,
        )
        self.assertEqual(zero["classification"], "still_uncertain_zero")
        self.assertEqual(one["classification"], "submitted_unique")
        self.assertEqual(multiple["classification"], "still_uncertain_multiple")
        self.assertEqual(absent["classification"], "definitely_not_submitted")
        self.assertEqual(contradictory["classification"], "still_uncertain_one_unbound")
        self.assertTrue(all(not item["automatic_qsub_authorized"] for item in (zero, one, multiple, absent, contradictory)))

    def test_remote_claim_rejects_preexisting_empty_directory_and_qsub_is_receipt_bound(self) -> None:
        script = PBS.remote_empty_directory_guard("safejob")
        self.assertIn("already exists, even if empty", script)
        self.assertNotIn("find \"$jobdir\"", script)
        source = (SCRIPTS / "gaussian_rtwin_pbs.py").read_text()
        self.assertIn("AUTO_G16_ATTEMPT_ID=", source)
        self.assertIn("submission-receipt.json", source)
        self.assertNotIn("qsub {project}.pbs", source)

    def test_qsub_output_requires_exactly_one_job_id_or_stays_uncertain(self) -> None:
        unique = PBS.classify_qsub_outcome(SimpleNamespace(returncode=0, stdout="123.master\n", stderr=""))
        empty = PBS.classify_qsub_outcome(SimpleNamespace(returncode=0, stdout="", stderr="connection closed"))
        multiple = PBS.classify_qsub_outcome(SimpleNamespace(returncode=0, stdout="123.master\n124.master\n", stderr=""))
        failed_with_id = PBS.classify_qsub_outcome(SimpleNamespace(returncode=255, stdout="123.master\n", stderr="transport failed"))
        self.assertEqual(unique["classification"], "submitted_unique")
        self.assertTrue(all(
            item["classification"] == "submission_uncertain"
            for item in (empty, multiple, failed_with_id)
        ))

    def approval(self, summary: dict, *, expired: bool = False, revoked: bool = False) -> dict:
        schema, scope = PBS.expected_live_approval_scope(summary)
        now = datetime.now(timezone.utc)
        approved = now - timedelta(hours=2 if expired else 1)
        expires = now - timedelta(hours=1) if expired else now + timedelta(hours=1)
        return {
            "schema": schema,
            "approval_id": "one-time-approval",
            "approver_identity": "fixture-operator",
            "approved_at": approved.isoformat(),
            "expires_at": expires.isoformat(),
            "decision": "approved",
            "explicit_confirmation": True,
            "scope": scope,
            "revocation": {
                "revoked": revoked,
                "revoked_at": now.isoformat() if revoked else None,
                "reason": "fixture revoke" if revoked else None,
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

    def protected_summary(self) -> dict:
        digest = "5" * 64
        return {
            "project": "safejob",
            "remote_workdir": "/home/user100/SDL/safejob",
            "input_sha256": digest,
            "protocol": {"route": "#p hf/sto-3g", "mem": "12GB", "nproc": 8},
            "charge": 0,
            "multiplicity": 1,
            "work_kind": "ordinary",
            "input_approval": {
                "schema": PBS.INPUT_APPROVAL_SCHEMA,
                "sha256": "a" * 64,
                "payload_sha256": "b" * 64,
                "input_sha256": digest,
                "work_kind": "ordinary",
            },
            "execution": {
                "batch_id": "batch",
                "review_sha256": "c" * 64,
                "scientific_task_id": "scientific-task-" + "d" * 64,
                "attempt_id": "qsub-attempt-" + "e" * 64,
                "idempotency_key": "attempt-key",
                "estimated_core_hours": 4,
                "estimated_core_hours_evidence": {"source": "fixture", "sha256": "f" * 64},
            },
        }

    def protected_schema_document(self, version: int) -> dict:
        digest = "5" * 64
        scope = {
            "project": "safejob",
            "remote_workdir": "/home/user100/SDL/safejob",
            "input_sha256": digest,
            "route": "#p uhf/sto-3g opt freq",
            "mem": "12GB",
            "nprocshared": 8,
            "charge": 0,
            "multiplicity": 2,
            "work_kind": "minimum",
            "input_approval": {
                "schema": f"gaussian-input-approval-receipt/{version - 5}",
                "sha256": "a" * 64,
                "payload_sha256": "b" * 64,
                "input_sha256": digest,
                "work_kind": "minimum",
            },
            "operation": "submit",
            "execution": {
                "batch_id": "batch",
                "review_sha256": "c" * 64,
                "scientific_task_id": "scientific-task-" + "d" * 64,
                "attempt_id": "qsub-attempt-" + "e" * 64,
                "idempotency_key": "attempt-key",
                "estimated_core_hours": 4,
                "estimated_core_hours_evidence": {
                    "source": "fixture",
                    "sha256": "f" * 64,
                },
            },
        }
        if version == 7:
            scope["open_shell_owner"] = {
                "owner": "auto-g16-main-group-open-shell",
                "workflow": "main_group_open_shell_minimum_opt_freq_v1",
                "electronic_state_review_payload_sha256": "1" * 64,
                "input_handoff_payload_sha256": "2" * 64,
                "input_audit_payload_sha256": "3" * 64,
                "selected_option_payload_sha256": "4" * 64,
                "input_sha256": digest,
                "exact_route": "#p uhf/sto-3g opt freq",
                "charge": 0,
                "multiplicity": 2,
                "reference_family": "U",
                "resources": {"resource_tier": "simple", "mem_gb": 12, "cores": 8},
                "owner_replay_passed": True,
            }
        else:
            scope["open_shell_family"] = {
                "owner": "auto-g16-main-group-open-shell",
                "workflow": "main_group_open_shell_minimum_two_stage_v1",
                "family_payload_sha256": "1" * 64,
                "stage": "opt_freq",
                "input_sha256": digest,
                "route": "#p uhf/sto-3g opt freq",
                "charge": 0,
                "multiplicity": 2,
                "reference_family": "U",
                "method": "uhf",
                "basis": "sto-3g",
                "resources": {"resource_tier": "simple", "mem_gb": 12, "cores": 8},
                "checkpoint_sha256": None,
                "owner_replay_passed": True,
            }
        return {
            "schema": f"auto-g16-live-submission-approval/{version}",
            "approval_id": f"approval-v{version}",
            "approver_identity": "fixture-operator",
            "approved_at": "2026-01-01T00:00:00Z",
            "expires_at": "2026-01-01T01:00:00Z",
            "decision": "approved",
            "explicit_confirmation": True,
            "scope": scope,
            "revocation": {"revoked": False, "revoked_at": None, "reason": None},
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

    def test_protected_schemas_are_closed_and_match_exact_runtime_field_sets(self) -> None:
        schema_dir = ROOT / "contracts" / "rtwin-pbs"
        common_scope = {
            "project", "remote_workdir", "input_sha256", "route", "mem",
            "nprocshared", "charge", "multiplicity", "work_kind",
            "input_approval", "operation", "execution",
        }
        input_fields = {"schema", "sha256", "payload_sha256", "input_sha256", "work_kind"}
        execution_fields = {
            "batch_id", "review_sha256", "scientific_task_id", "attempt_id",
            "idempotency_key", "estimated_core_hours", "estimated_core_hours_evidence",
        }
        owner_fields = {
            "owner", "workflow", "electronic_state_review_payload_sha256",
            "input_handoff_payload_sha256", "input_audit_payload_sha256",
            "selected_option_payload_sha256", "input_sha256", "exact_route",
            "charge", "multiplicity", "reference_family", "resources",
            "owner_replay_passed",
        }
        family_fields = {
            "owner", "workflow", "family_payload_sha256", "stage", "input_sha256",
            "route", "charge", "multiplicity", "reference_family", "method", "basis",
            "resources", "checkpoint_sha256", "owner_replay_passed",
        }
        for version, owner_key, definition, fields in (
            (7, "open_shell_owner", "openShellOwner", owner_fields),
            (8, "open_shell_family", "openShellFamily", family_fields),
        ):
            with self.subTest(schema_version=version):
                schema = json.loads(
                    (schema_dir / f"live-submission-approval-v{version}.schema.json").read_text()
                )
                self.assertFalse(schema["$defs"]["scope"]["additionalProperties"])
                self.assertEqual(set(schema["$defs"]["scope"]["properties"]), common_scope | {owner_key})
                self.assertEqual(set(schema["$defs"]["inputApproval"]["properties"]), input_fields)
                self.assertEqual(set(schema["$defs"]["execution"]["properties"]), execution_fields)
                self.assertEqual(set(schema["$defs"][definition]["properties"]), fields)
                document = self.protected_schema_document(version)
                SCHEMA._validate_schema_instance(document, schema, schema)

                invalid_documents = []
                unknown_scope = copy.deepcopy(document)
                unknown_scope["scope"]["unreviewed"] = True
                invalid_documents.append(unknown_scope)
                wrong_execution_type = copy.deepcopy(document)
                wrong_execution_type["scope"]["execution"]["batch_id"] = 7
                invalid_documents.append(wrong_execution_type)
                missing_input_binding = copy.deepcopy(document)
                del missing_input_binding["scope"]["input_approval"]["payload_sha256"]
                invalid_documents.append(missing_input_binding)
                unknown_owner = copy.deepcopy(document)
                unknown_owner["scope"][owner_key]["unreviewed"] = True
                invalid_documents.append(unknown_owner)
                wrong_resource_type = copy.deepcopy(document)
                wrong_resource_type["scope"][owner_key]["resources"]["cores"] = "8"
                invalid_documents.append(wrong_resource_type)
                missing_owner_binding = copy.deepcopy(document)
                del missing_owner_binding["scope"][owner_key][next(iter(fields - {"owner", "workflow", "resources", "owner_replay_passed"}))]
                invalid_documents.append(missing_owner_binding)
                for index, invalid in enumerate(invalid_documents):
                    with self.subTest(schema_version=version, negative=index):
                        with self.assertRaises(SCHEMA.ContractError):
                            SCHEMA._validate_schema_instance(invalid, schema, schema)

        v6 = json.loads((schema_dir / "live-submission-approval-v6.schema.json").read_text())
        self.assertEqual(set(v6["$defs"]["scope"]["properties"]), common_scope)
        self.assertEqual(set(v6["$defs"]["inputApproval"]["properties"]), input_fields)
        self.assertEqual(set(v6["$defs"]["execution"]["properties"]), execution_fields)
        cancellation = json.loads((schema_dir / "exact-cancellation-approval.schema.json").read_text())
        self.assertEqual(
            set(cancellation["properties"]["scope"]["properties"]),
            {"operation", "project", "job_id", "local_job_sha256", "attempt_id", "attempt_sha256"},
        )
        ledger = json.loads((schema_dir / "execution-batch-v2.schema.json").read_text())
        self.assertEqual(
            set(ledger["properties"]),
            {"schema", "batch", "revision", "created_at", "tasks", "attempts", "events", "counters", "resource_policy_interface", "calculation_ready", "no_submission_authorization", "ledger_sha256"},
        )
        self.assertEqual(
            set(ledger["$defs"]["attempt"]["properties"]),
            {"attempt_id", "scientific_task_id", "idempotency_key", "state", "project", "job_name", "remote_workdir", "input_sha256", "live_approval_id", "live_approval_sha256", "estimated_core_hours", "estimated_core_hours_evidence", "consumed_core_hours", "consumed_core_hours_evidence", "reserved_at", "updated_at", "scheduler_reference", "reconciliation_evidence", "audit_reason", "resource_gate"},
        )

    def test_live_approval_v6_expired_revoked_and_old_v3_fail_closed(self) -> None:
        summary = self.protected_summary()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            valid = self.approval(summary)
            self.assertEqual(valid["schema"], PBS.LIVE_APPROVAL_V6_SCHEMA)
            path = root / "valid.json"
            path.write_text(json.dumps(valid))
            self.assertEqual(PBS.validate_live_approval(path, summary), valid)
            for label, document in (
                ("expired", self.approval(summary, expired=True)),
                ("revoked", self.approval(summary, revoked=True)),
            ):
                candidate = root / f"{label}.json"
                candidate.write_text(json.dumps(document))
                with self.assertRaises(SystemExit):
                    PBS.validate_live_approval(candidate, summary)
            legacy = copy.deepcopy(valid)
            legacy["schema"] = PBS.LIVE_APPROVAL_V3_SCHEMA
            legacy_path = root / "legacy.json"
            legacy_path.write_text(json.dumps(legacy))
            with self.assertRaises(SystemExit):
                PBS.validate_live_approval(legacy_path, summary)

    def test_job_state_updates_are_locked_append_only_and_no_lost_update(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            PBS.initialize_job_state(root, {"schema": "gaussian-rtwin-pbs/1", "status": "staged"})

            def worker(index: int) -> None:
                PBS.update_job(root, **{f"worker_{index}": index})

            with ThreadPoolExecutor(max_workers=16) as pool:
                list(pool.map(worker, range(32)))
            state = PBS.read_job_state(root)
            self.assertEqual(state["state_revision"], 33)
            for index in range(32):
                self.assertEqual(state[f"worker_{index}"], index)
            self.assertEqual(len((root / "job.events.jsonl").read_text().splitlines()), 33)
            self.assertEqual(list(root.glob("job.json.tmp")), [])

    def test_missing_reservation_arguments_stop_before_any_network(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "input.gjf"
            source.write_text(
                "%chk=input.chk\n%mem=12GB\n%nprocshared=8\n#p hf/sto-3g\n\nTitle\n\n0 1\nH 0 0 0\nH 0 0 0.7\n\n"
            )
            args = PBS.build_parser().parse_args([
                "submit", str(source), "--project", "safejob", "--local-dir", str(root / "bundle"),
                "--work-kind", "ordinary", "--confirmed",
            ])
            import io
            from contextlib import redirect_stderr
            error = io.StringIO()
            with mock.patch.object(PBS, "run") as run, self.assertRaises(SystemExit), redirect_stderr(error): args.func(args)
            run.assert_not_called()
            self.assertIn("protected live submit requires --execution-batch-ledger", error.getvalue())
            self.assertNotIn("%chk", error.getvalue())

    def test_legacy_v2_submit_arguments_block_before_reservation_and_network(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "input.gjf"
            source.write_text(
                "%chk=input.chk\n%mem=12GB\n%nprocshared=8\n#p hf/sto-3g\n\nTitle\n\n0 1\nH 0 0 0\nH 0 0 0.7\n\n"
            )
            digest = PBS.sha256(source)
            ledger_path, task_id = self.make_v2_ledger(root, digest)
            args = self.submit_args(root, source, ledger_path, task_id)
            live = {
                "schema": PBS.LIVE_APPROVAL_V6_SCHEMA,
                "approval_id": "approval-once",
                "approver_identity": "fixture",
            }
            with (
                mock.patch.object(PBS, "validate_input_approval", return_value=self.fake_input_approval(digest)),
                mock.patch.object(
                    PBS,
                    "validate_live_approval_binding",
                    side_effect=[(live, "d" * 64), SystemExit(2)],
                ),
                mock.patch.object(PBS, "run") as run,
                self.assertRaises(SystemExit),
            ):
                args.func(args)
            run.assert_not_called()
            ledger = BATCH.validate_submission_ledger(BATCH.load_json(ledger_path))
            self.assertEqual(ledger["attempts"], [])

    def test_legacy_v2_submit_cannot_enter_resource_bound_live_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "input.gjf"
            source.write_text(
                "%chk=input.chk\n%mem=12GB\n%nprocshared=8\n#p hf/sto-3g\n\nTitle\n\n0 1\nH 0 0 0\nH 0 0 0.7\n\n"
            )
            digest = PBS.sha256(source)
            ledger_path, task_id = self.make_v2_ledger(root, digest)
            args = self.submit_args(root, source, ledger_path, task_id)
            live = {
                "schema": PBS.LIVE_APPROVAL_V6_SCHEMA,
                "approval_id": "approval-once",
                "approver_identity": "fixture",
            }
            calls = []

            def fake_run(command, *, input_bytes=None, check=True):
                calls.append((command, input_bytes))
                if len(calls) == 3:
                    bundle = root / "bundle"
                    lines = [
                        f"{path.name} {PBS.sha256(path)}"
                        for path in bundle.iterdir() if path.is_file()
                    ]
                    return SimpleNamespace(returncode=0, stdout="\n".join(lines), stderr="")
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            with (
                mock.patch.object(PBS, "validate_input_approval", return_value=self.fake_input_approval(digest)),
                mock.patch.object(
                    PBS,
                    "validate_live_approval_binding",
                    side_effect=[(live, "d" * 64), (live, "d" * 64), SystemExit(2)],
                ),
                mock.patch.object(PBS, "run", side_effect=fake_run),
                self.assertRaises(SystemExit),
            ):
                args.func(args)
            self.assertFalse(any(input_bytes and b"qsub " in input_bytes for _, input_bytes in calls))
            ledger = BATCH.validate_submission_ledger(BATCH.load_json(ledger_path))
            self.assertEqual(ledger["attempts"], [])
            self.assertFalse((root / "bundle" / "job.json").exists())

    def test_cancel_scope_mismatch_is_blocked_before_qstat_or_qdel(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            ledger_path, task_id = self.make_v2_ledger(root)
            attempt = self.reserve(ledger_path, task_id)
            attempt = BATCH.reconcile_submission_attempt(
                ledger_path,
                attempt["attempt_id"],
                state="submitted",
                observed_at="2026-01-01T00:04:00Z",
                reason="synthetic submitted fixture",
                scheduler_reference="123.master",
                reconciliation_evidence={"source": "fixture", "sha256": "c" * 64},
            )
            local_dir = root / "bundle"
            local_dir.mkdir()
            PBS.initialize_job_state(local_dir, {
                "schema": "gaussian-rtwin-pbs/1",
                "project": "safejob",
                "remote_workdir": "/home/user100/SDL/safejob",
                "job_id": "123.master",
                "status": "running",
            })
            job = PBS.read_job_state(local_dir)
            now = datetime.now(timezone.utc)
            approval = {
                "schema": PBS.CANCELLATION_APPROVAL_SCHEMA,
                "approval_id": "cancel-once",
                "approver_identity": "fixture-operator",
                "approved_at": (now - timedelta(minutes=5)).isoformat(),
                "expires_at": (now + timedelta(minutes=5)).isoformat(),
                "decision": "approved",
                "explicit_confirmation": True,
                "scope": {
                    "operation": "cancel_active_job",
                    "project": "wrongjob",
                    "job_id": "123.master",
                    "local_job_sha256": job["state_sha256"],
                    "attempt_id": attempt["attempt_id"],
                    "attempt_sha256": PBS.canonical_digest(attempt),
                },
                "revocation": {"revoked": False, "revoked_at": None, "reason": None},
                "consumption": {"single_use": True, "consumed": False},
                "authorizations": {
                    "qdel_exact_job": True,
                    "retry": False,
                    "cleanup": False,
                    "delete_server_data": False,
                },
            }
            approval_path = root / "cancel.json"
            approval_path.write_text(json.dumps(approval))
            args = PBS.build_parser().parse_args([
                "cancel", "--job-id", "123.master", "--local-dir", str(local_dir),
                "--approval-record", str(approval_path), "--execution-batch-ledger", str(ledger_path),
                "--attempt-id", attempt["attempt_id"],
            ])
            with mock.patch.object(PBS, "run") as run, self.assertRaises(SystemExit):
                args.func(args)
            run.assert_not_called()

    def make_cancel_transaction(self, root: Path):
        ledger_path, task_id = self.make_v2_ledger(root)
        attempt = self.reserve(ledger_path, task_id)
        attempt = BATCH.reconcile_submission_attempt(
            ledger_path,
            attempt["attempt_id"],
            state="submitted",
            observed_at="2026-01-01T00:04:00Z",
            reason="synthetic submitted fixture",
            scheduler_reference="123.master",
            reconciliation_evidence={"source": "fixture", "sha256": "c" * 64},
        )
        local_dir = root / "bundle"
        local_dir.mkdir()
        PBS.initialize_job_state(local_dir, {
            "schema": "gaussian-rtwin-pbs/1",
            "project": "safejob",
            "remote_workdir": "/home/user100/SDL/safejob",
            "job_id": "123.master",
            "status": "running",
        })
        job = PBS.read_job_state(local_dir)
        now = datetime.now(timezone.utc)
        approval = {
            "schema": PBS.CANCELLATION_APPROVAL_SCHEMA,
            "approval_id": "cancel-once",
            "approver_identity": "fixture-operator",
            "approved_at": (now - timedelta(minutes=5)).isoformat(),
            "expires_at": (now + timedelta(minutes=5)).isoformat(),
            "decision": "approved",
            "explicit_confirmation": True,
            "scope": {
                "operation": "cancel_active_job",
                "project": "safejob",
                "job_id": "123.master",
                "local_job_sha256": job["state_sha256"],
                "attempt_id": attempt["attempt_id"],
                "attempt_sha256": PBS.canonical_digest(attempt),
            },
            "revocation": {"revoked": False, "revoked_at": None, "reason": None},
            "consumption": {"single_use": True, "consumed": False},
            "authorizations": {
                "qdel_exact_job": True,
                "retry": False,
                "cleanup": False,
                "delete_server_data": False,
            },
        }
        approval_path = root / "cancel-valid.json"
        approval_path.write_text(json.dumps(approval))
        config = root / "ssh_config"
        config.write_text("Host rtwin\n")
        argv = [
            "cancel", "--job-id", "123.master", "--local-dir", str(local_dir),
            "--approval-record", str(approval_path), "--execution-batch-ledger", str(ledger_path),
            "--attempt-id", attempt["attempt_id"], "--mac-ssh-config", str(config),
        ]
        return argv, local_dir

    def test_concurrent_cancel_intents_issue_at_most_one_qdel(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            argv, local_dir = self.make_cancel_transaction(root)
            qdel_calls = []

            def fake_run(command, *, input_bytes=None, check=True):
                if "qdel" in command:
                    qdel_calls.append(command)
                    return SimpleNamespace(returncode=0, stdout="", stderr="")
                return SimpleNamespace(
                    returncode=0,
                    stdout="Job Id: 123.master\n    Job_Name = safejob\n    job_state = R\n",
                    stderr="",
                )

            def worker(_index: int) -> str:
                args = PBS.build_parser().parse_args(argv)
                try:
                    args.func(args)
                    return "issued"
                except SystemExit:
                    return "blocked"

            with mock.patch.object(PBS, "run", side_effect=fake_run):
                with ThreadPoolExecutor(max_workers=8) as pool:
                    outcomes = list(pool.map(worker, range(8)))
            self.assertEqual(len(qdel_calls), 1)
            self.assertEqual(outcomes.count("issued"), 1)
            self.assertTrue((local_dir / "cancellation-intent.json").is_file())

    def test_qdel_transport_uncertain_consumes_intent_and_forbids_resend(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            argv, local_dir = self.make_cancel_transaction(root)
            qdel_calls = []

            def fake_run(command, *, input_bytes=None, check=True):
                if "qdel" in command:
                    qdel_calls.append(command)
                    return SimpleNamespace(returncode=255, stdout="", stderr="transport lost")
                return SimpleNamespace(
                    returncode=0,
                    stdout="Job Id: 123.master\n    Job_Name = safejob\n    job_state = R\n",
                    stderr="",
                )

            args = PBS.build_parser().parse_args(argv)
            with mock.patch.object(PBS, "run", side_effect=fake_run), self.assertRaises(SystemExit):
                args.func(args)
            second = PBS.build_parser().parse_args(argv)
            with mock.patch.object(PBS, "run") as second_run, self.assertRaises(SystemExit):
                second.func(second)
            second_run.assert_not_called()
            self.assertEqual(len(qdel_calls), 1)
            self.assertEqual(PBS.read_job_state(local_dir)["status"], "cancellation_uncertain")

    def test_cancellation_receipt_publication_failure_still_forbids_resend(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            argv, local_dir = self.make_cancel_transaction(root)
            real_publish = PBS.publish_new_json
            qdel_calls = []

            def fail_receipt(path, value, validator=None):
                if path.name == "cancellation-receipt.json":
                    raise ValueError("synthetic receipt publication failure")
                return real_publish(path, value, validator)

            def fake_run(command, *, input_bytes=None, check=True):
                if "qdel" in command:
                    qdel_calls.append(command)
                    return SimpleNamespace(returncode=0, stdout="", stderr="")
                return SimpleNamespace(
                    returncode=0,
                    stdout="Job Id: 123.master\n    Job_Name = safejob\n    job_state = R\n",
                    stderr="",
                )

            args = PBS.build_parser().parse_args(argv)
            with (
                mock.patch.object(PBS, "publish_new_json", side_effect=fail_receipt),
                mock.patch.object(PBS, "run", side_effect=fake_run),
                self.assertRaises(SystemExit),
            ):
                args.func(args)
            second = PBS.build_parser().parse_args(argv)
            with mock.patch.object(PBS, "run") as second_run, self.assertRaises(SystemExit):
                second.func(second)
            second_run.assert_not_called()
            self.assertEqual(len(qdel_calls), 1)
            state = PBS.read_job_state(local_dir)
            self.assertTrue(state["cancellation_receipt_publication_failed"])

    def test_read_only_cancellation_reconcile_classifies_without_qdel(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            argv, local_dir = self.make_cancel_transaction(root)
            # Reserve the intent and stop on unknown precheck before qdel.
            args = PBS.build_parser().parse_args(argv)
            with (
                mock.patch.object(PBS, "run", return_value=SimpleNamespace(returncode=255, stdout="", stderr="lost")),
                self.assertRaises(SystemExit),
            ):
                args.func(args)
            reconcile = PBS.build_parser().parse_args([
                "reconcile-cancellation", "--job-id", "123.master", "--local-dir", str(local_dir),
                "--mac-ssh-config", argv[argv.index("--mac-ssh-config") + 1],
            ])
            observed = []

            def only_qstat(command, *, input_bytes=None, check=True):
                observed.append(command)
                return SimpleNamespace(returncode=153, stdout="", stderr="qstat: Unknown Job Id")

            with mock.patch.object(PBS, "run", side_effect=only_qstat):
                reconcile.func(reconcile)
            self.assertEqual(len(observed), 1)
            self.assertNotIn("qdel", observed[0])


if __name__ == "__main__":
    unittest.main()
