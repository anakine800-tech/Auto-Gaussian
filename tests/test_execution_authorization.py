#!/usr/bin/env python3
"""Focused synthetic offline tests for v2.6 execution authorization."""

from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import inspect
import json
import re
import shutil
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType
from unittest import mock

from tests.test_open_shell_input_receipt_bridge import OpenShellInputReceiptBridgeTests


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "skills" / "auto-g16-rtwin-pbs" / "scripts"))

import execution_authorization as AUTH  # noqa: E402
import platform_contracts as PLATFORM  # noqa: E402
import skill_package  # noqa: E402


def load_owner(name: str, filename: str):
    path = ROOT / "skills" / "auto-g16-rtwin-pbs" / "scripts" / filename
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BATCH = load_owner("execution_authorization_batch_fixture", "execution_batch.py")
RESOURCE = load_owner("execution_authorization_resource_fixture", "resource_efficiency.py")


def digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def hop(kind: str, label: str) -> dict[str, str]:
    return {
        "transport_kind": kind,
        "config_source_bundle_sha256": digest(f"{label}-config"),
        "alias_utf8_sha256": digest(f"{label}-alias"),
        "effective_target_identity_sha256": digest(f"{label}-target"),
        "host_key_policy": "strict_pinned",
        "host_key_evidence_sha256": digest(f"{label}-host-key"),
        "resolver_version": "synthetic-resolver-v1",
    }


def file_ref(path: Path, schema: str, payload: str) -> dict[str, object]:
    raw = path.read_bytes()
    return {
        "schema": schema,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "size_bytes": len(raw),
        "payload_sha256": payload,
    }


def seal_embedded(value: dict[str, object], field: str) -> dict[str, object]:
    result = copy.deepcopy(value)
    result[field] = ""
    projection = {key: item for key, item in result.items() if key != field}
    result[field] = hashlib.sha256(PLATFORM.canonical_bytes(projection)).hexdigest()
    return result


class ExecutionAuthorizationTests(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(dir=ROOT)
        self.root = Path(self.temporary.name).resolve()
        self.now = "2030-01-01T12:02:00Z"
        self.fixture = self.build_fixture()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_new(self, name: str, value: dict[str, object]) -> Path:
        path = self.root / name
        path.write_bytes(PLATFORM.canonical_bytes(value))
        return path

    def build_fixture(self) -> dict[str, object]:
        scientific_chain = OpenShellInputReceiptBridgeTests().build_receipt(self.root)
        input_path = scientific_chain["input_path"]
        receipt_path = scientific_chain["receipt_path"]
        input_raw = input_path.read_bytes()
        input_sha = hashlib.sha256(input_raw).hexdigest()

        profile_id = "profile-placeholder"
        binding = PLATFORM.build_transport_identity_binding(
            binding_id="binding-placeholder",
            profile_id=profile_id,
            hops=[
                hop("legacy_rtwin_first_hop", "first"),
                hop("legacy_rtwin_nested_hop", "nested"),
            ],
        )
        profile = PLATFORM.build_execution_profile(
            profile_id=profile_id,
            backend_kind="legacy_rtwin_pbs",
            transport_config_ref="/opt/placeholder/config/rtwin-ssh-config",
            identity_binding=binding,
        )
        profile_path = self.write_new("profile.json", profile)
        binding_path = self.write_new("identity-binding.json", binding)

        review = BATCH.finalize_review(json.loads(
            (ROOT / "tests" / "fixtures" / "rtwin_pbs" / "execution_batch_review.template.json").read_text(encoding="utf-8")
        ))
        review_path = self.root / "batch-review.json"
        review_path.write_text(json.dumps(review), encoding="utf-8")
        ledger_path = self.root / "execution-batch.json"
        BATCH.initialize(review_path, ledger_path, timestamp="2030-01-01T11:50:00Z")
        identity = {
            "structure_sha256": digest("structure"),
            "chemical_hypothesis_sha256": digest("hypothesis"),
            "method_protocol_sha256": digest("protocol"),
            "calculation_objective_sha256": digest("objective"),
            "relevant_input_sha256": input_sha,
        }
        task = BATCH.admit_task(
            ledger_path,
            identity,
            estimated_core_hours=4,
            reason="synthetic exact minimum fixture",
            reviewer="fixture-reviewer",
            reviewed_at="2030-01-01T11:51:00Z",
        )
        BATCH.migrate_to_submission_ledger(
            ledger_path,
            migrated_at="2030-01-01T11:52:00Z",
            migration_source="synthetic fixture",
        )
        RESOURCE.migrate_v2_to_v3(
            ledger_path,
            migrated_at="2030-01-01T11:53:00Z",
            migration_source="synthetic fixture",
        )
        ledger = RESOURCE.validate_ledger(RESOURCE.load(ledger_path))
        idempotency_key = "attempt-key-placeholder"
        attempt_id = BATCH.attempt_id_for(ledger["batch"]["batch_id"], idempotency_key)

        policy = RESOURCE.finalize_policy({
            "schema": RESOURCE.POLICY_SCHEMA,
            "policy_id": "policy-placeholder",
            "reviewed_at": "2030-01-01T11:54:00Z",
            "reviewer": "fixture-reviewer",
            "limits": {
                "max_estimated_core_hours": 100,
                "max_remaining_core_hours": 100,
                "max_concurrent_unresolved_attempts": 3,
                "max_concurrent_active_attempts": 3,
                "max_total_cores": 44,
                "max_total_memory_gb": 120,
                "max_job_cores": 44,
                "max_job_memory_gb": 120,
                "max_job_walltime_seconds": 86400,
            },
            "governance": {
                "unknown_scheduler_or_ledger_state_fails_closed": True,
                "resources_must_be_exact_reviewed_bindings": True,
                "walltime_must_be_explicitly_reviewed": True,
                "automatic_resource_change": False,
                "automatic_retry": False,
                "monitoring_changes_scientific_conclusion": False,
            },
            "payload_sha256": "",
        })
        policy_path = self.root / "resource-policy.json"
        policy_path.write_text(json.dumps(policy, sort_keys=True) + "\n", encoding="utf-8")
        snapshot = RESOURCE.finalize_scheduler_snapshot({
            "schema": RESOURCE.SCHEDULER_SNAPSHOT_SCHEMA,
            "snapshot_id": "snapshot-placeholder",
            "collected_at": "2030-01-01T12:00:00Z",
            "source": "synthetic complete user scope",
            "scope": {
                "kind": "complete_user_active_jobs",
                "owner": "fixture-owner",
                "completeness": "complete",
                "batch_evidence_sha256": digest("batch-evidence"),
            },
            "transport": {"classification": "success", "status": "known"},
            "freshness": {"classification": "fresh", "age_seconds": 0, "max_age_seconds": 300},
            "attempts": [],
            "payload_sha256": "",
        })
        snapshot_path = self.root / "scheduler-snapshot.json"
        snapshot_path.write_text(json.dumps(snapshot, sort_keys=True) + "\n", encoding="utf-8")
        snapshot_raw = snapshot_path.read_bytes()
        resources = {"tier": "simple", "cores": 8, "memory_gb": 12, "walltime_seconds": 3600}
        gate = RESOURCE.evaluate_gate(
            ledger,
            policy,
            snapshot,
            gate_id="gate-placeholder",
            evaluated_at="2030-01-01T12:01:00Z",
            resource_tier=resources["tier"],
            cores=resources["cores"],
            memory_gb=resources["memory_gb"],
            walltime_seconds=resources["walltime_seconds"],
            estimated_core_hours=4,
            scheduler_artifact_sha256=hashlib.sha256(snapshot_raw).hexdigest(),
            scheduler_artifact_size=len(snapshot_raw),
            scientific_task_id=task["scientific_task_id"],
            attempt_id=attempt_id,
            project="safejob",
            input_sha256=input_sha,
        )
        gate_path = self.root / "resource-gate.json"
        gate_path.write_text(json.dumps(gate, sort_keys=True) + "\n", encoding="utf-8")

        scientific_ref = file_ref(
            receipt_path,
            scientific_chain["receipt"]["schema"],
            scientific_chain["receipt"]["payload_sha256"],
        )
        policy_ref = file_ref(policy_path, policy["schema"], policy["payload_sha256"])
        snapshot_ref = file_ref(snapshot_path, snapshot["schema"], snapshot["payload_sha256"])
        gate_ref = file_ref(gate_path, gate["schema"], gate["gate_sha256"])
        ledger = RESOURCE.validate_ledger(RESOURCE.load(ledger_path))
        ledger_ref = file_ref(ledger_path, ledger["schema"], ledger["ledger_sha256"])
        upstream = [
            {"role": "scientific_owner_receipt", **scientific_ref},
            {"role": "resource_policy", **policy_ref},
            {"role": "scheduler_resource_snapshot", **snapshot_ref},
            {"role": "resource_gate", **gate_ref},
            {"role": "execution_batch", **ledger_ref},
        ]
        request = AUTH.build_execution_request(
            request_id="request-placeholder",
            input_sha256=input_sha,
            input_size_bytes=len(input_raw),
            scientific_task_id=task["scientific_task_id"],
            attempt_id=attempt_id,
            idempotency_key=idempotency_key,
            work_kind="minimum",
            profile_id=profile_id,
            profile_sha256=profile["profile_payload_sha256"],
            backend_kind="legacy_rtwin_pbs",
            required_capabilities=["pbs_submit_once", "typed_identity_attestation"],
            proposed_resources=resources,
            upstream_artifact_refs=upstream,
        )
        request_path = self.write_new("execution-request.json", request)

        workspace = seal_embedded({
            "root_policy": "fixed_sdl",
            "allowed_root": "/home/user100/SDL",
            "project": "safejob",
            "remote_workdir": "/home/user100/SDL/safejob",
            "fresh_project_required": True,
            "no_overwrite": True,
            "no_symlink": True,
            "no_delete": True,
            "workspace_binding_sha256": "",
        }, "workspace_binding_sha256")
        runtime = seal_embedded({
            "invocation_mode": "legacy_stdin",
            "executable_ref_sha256": hashlib.sha256(PLATFORM.canonical_bytes("g16")).hexdigest(),
            "input_sha256": input_sha,
            "workspace_binding_sha256": workspace["workspace_binding_sha256"],
            "resources": resources,
            "runtime_binding_sha256": "",
        }, "runtime_binding_sha256")
        authorization: dict[str, object] = {
            "schema": AUTH.AUTHORIZATION_SCHEMA,
            "authorization_id": "authorization-placeholder",
            "request": {"request_id": request["request_id"], "request_payload_sha256": request["request_payload_sha256"]},
            "approver": {"principal_id": "human-reviewer"},
            "approved_at": "2030-01-01T12:00:00Z",
            "not_before": "2030-01-01T12:00:00Z",
            "expires_at": "2030-01-01T12:05:00Z",
            "decision": "approved",
            "explicit_human_approval": True,
            "profile": {"profile_id": profile_id, "profile_sha256": profile["profile_payload_sha256"], "backend_kind": "legacy_rtwin_pbs"},
            "transport": {"identity_binding_sha256": binding["binding_payload_sha256"], "hop_count": 2},
            "target": {"target_kind": "profile_transport_identity", "effective_target_identity_sha256": binding["hops"][-1]["effective_target_identity_sha256"]},
            "workspace_binding": workspace,
            "runtime_binding": runtime,
            "resources": resources,
            "scientific_owner_receipt": {**scientific_ref, "input_sha256": input_sha, "work_kind": "minimum"},
            "resource_chain": {"policy": policy_ref, "scheduler_snapshot": snapshot_ref, "gate": gate_ref, "execution_batch": ledger_ref},
            "execution": {
                "batch_id": ledger["batch"]["batch_id"],
                "review_sha256": ledger["batch"]["review_sha256"],
                "scientific_task_id": task["scientific_task_id"],
                "attempt_id": attempt_id,
                "idempotency_key": idempotency_key,
            },
            "identity_attestation": {
                "mode": "legacy_two_stage",
                "operations": [
                    {
                        "operation": "attest_first_hop_once",
                        "operation_version": "first-hop-identity-attestation/1",
                        "request_nonce": "1" * 32,
                        "not_before": "2030-01-01T12:00:00Z",
                        "expires_at": "2030-01-01T12:05:00Z",
                        "allowed_read_only_side_effects": ["read_local_identity_sources", "network_identity_handshake"],
                        "read_only": True,
                        "automatic_retry": False,
                        "mutation_allowed": False,
                    },
                    {
                        "operation": "attest_nested_hop_once",
                        "operation_version": "nested-hop-identity-attestation/1",
                        "request_nonce": "2" * 32,
                        "not_before": "2030-01-01T12:00:00Z",
                        "expires_at": "2030-01-01T12:05:00Z",
                        "allowed_read_only_side_effects": ["read_remote_identity_source_hashes"],
                        "read_only": True,
                        "automatic_retry": False,
                        "mutation_allowed": False,
                    },
                ],
            },
            "revocation": {"revoked": False, "revoked_at": None, "reason": None},
            "consumption": {"single_use": True, "consumed": False},
            "scope_sha256": "",
            "authorizations": [],
            "authorization_payload_sha256": "",
        }
        authorization["authorizations"] = [
            {"operation": operation, "occurrence_limit": 1, "automatic_retry": False, "scope_sha256": "0" * 64}
            for operation in ("create_fresh_workspace_once", "transfer_exact_bundle_once", "pbs_submit_once")
        ]
        authorization["scope_sha256"] = AUTH._scope_sha256(authorization)
        for operation in authorization["authorizations"]:
            operation["scope_sha256"] = authorization["scope_sha256"]
        authorization = AUTH.finalize(authorization, "authorization_payload_sha256")
        AUTH.validate_execution_authorization(authorization, now=self.now)
        authorization_path = self.write_new("execution-authorization.json", authorization)
        registry = AUTH.finalize({
            "schema": AUTH.REGISTRY_SCHEMA,
            "snapshot_id": "registry-placeholder",
            "captured_at": "2030-01-01T12:01:00Z",
            "known_authorization_ids": [],
            "consumed_authorization_ids": [],
            "known_attestation_nonces": [],
            "immutable": True,
            "offline_snapshot_only": True,
            "registry_payload_sha256": "",
        }, "registry_payload_sha256")
        registry_path = self.write_new("registry-snapshot.json", registry)
        return {
            "input_path": input_path,
            "receipt_path": receipt_path,
            "profile_path": profile_path,
            "binding_path": binding_path,
            "policy_path": policy_path,
            "snapshot_path": snapshot_path,
            "gate_path": gate_path,
            "ledger_path": ledger_path,
            "request_path": request_path,
            "authorization_path": authorization_path,
            "registry_path": registry_path,
            "request": request,
            "authorization": authorization,
            "registry": registry,
        }

    def run_gate(self, **overrides: Path) -> dict[str, object]:
        values = {
            "request_path": self.fixture["request_path"],
            "authorization_path": self.fixture["authorization_path"],
            "profile_path": self.fixture["profile_path"],
            "identity_binding_path": self.fixture["binding_path"],
            "input_path": self.fixture["input_path"],
            "scientific_receipt_path": self.fixture["receipt_path"],
            "resource_policy_path": self.fixture["policy_path"],
            "scheduler_snapshot_path": self.fixture["snapshot_path"],
            "resource_gate_path": self.fixture["gate_path"],
            "execution_batch_path": self.fixture["ledger_path"],
            "registry_snapshot_path": self.fixture["registry_path"],
            "now": self.now,
        }
        values.update(overrides)
        return AUTH.validate_authorization_gate(**values)

    def reseal_resource_closure(
        self, *, policy_path: Path, policy: dict[str, object], gate_path: Path,
        gate: dict[str, object], label: str,
    ) -> tuple[Path, Path]:
        request = copy.deepcopy(self.fixture["request"])
        request["upstream_artifact_refs"][1] = {
            "role": "resource_policy",
            **file_ref(policy_path, policy["schema"], policy["payload_sha256"]),
        }
        request["upstream_artifact_refs"][3] = {
            "role": "resource_gate",
            **file_ref(gate_path, gate["schema"], gate["gate_sha256"]),
        }
        request = AUTH.finalize(request, "request_payload_sha256")
        request_path = self.write_new(f"request-{label}.json", request)

        authorization = copy.deepcopy(self.fixture["authorization"])
        authorization["request"]["request_payload_sha256"] = request["request_payload_sha256"]
        authorization["resource_chain"]["policy"] = file_ref(
            policy_path, policy["schema"], policy["payload_sha256"],
        )
        authorization["resource_chain"]["gate"] = file_ref(
            gate_path, gate["schema"], gate["gate_sha256"],
        )
        authorization["scope_sha256"] = AUTH._scope_sha256(authorization)
        for operation in authorization["authorizations"]:
            operation["scope_sha256"] = authorization["scope_sha256"]
        authorization = AUTH.finalize(authorization, "authorization_payload_sha256")
        authorization_path = self.write_new(f"authorization-{label}.json", authorization)
        return request_path, authorization_path

    def test_exact_synthetic_happy_path_is_only_closure_valid_offline(self) -> None:
        result = self.run_gate()
        self.assertEqual(result["status"], "closure_valid_offline")
        self.assertFalse(result["live_ready"])
        self.assertFalse(result["calculation_ready"])
        self.assertTrue(result["future_owner_replay_required"])
        self.assertTrue(result["atomic_consumption_required"])
        self.assertTrue(result["registry_negative_evidence_only"])
        self.assertFalse(result["registry_uniqueness_proven"])
        self.assertFalse(result["network_performed"])
        self.assertFalse(result["external_mutation_performed"])
        self.assertFalse(result["persistent_mutation_performed"])
        self.assertTrue(result["ephemeral_validation_copy_performed"])
        self.assertFalse(result["submission_performed"])
        self.assertEqual(
            result["readiness_payload_sha256"],
            PLATFORM.payload_sha256(result, "readiness_payload_sha256"),
        )

    def test_resource_gate_is_recomputed_not_trusted_after_semantic_reseal(self) -> None:
        policy = copy.deepcopy(RESOURCE.load(self.fixture["policy_path"]))
        policy["limits"]["max_job_cores"] = 1
        policy = RESOURCE.finalize_policy(policy)
        policy_path = self.root / "resource-policy-restricted.json"
        policy_path.write_text(json.dumps(policy, sort_keys=True) + "\n", encoding="utf-8")

        gate = copy.deepcopy(RESOURCE.load(self.fixture["gate_path"]))
        gate["policy_sha256"] = policy["payload_sha256"]
        gate["gate_sha256"] = BATCH.digest_value({
            key: value for key, value in gate.items() if key != "gate_sha256"
        })
        gate_path = self.root / "resource-gate-semantically-resealed.json"
        gate_path.write_text(json.dumps(gate, sort_keys=True) + "\n", encoding="utf-8")
        RESOURCE.validate_policy(policy)
        RESOURCE._validate_gate_binding(gate, allow_historical=False)
        request_path, authorization_path = self.reseal_resource_closure(
            policy_path=policy_path,
            policy=policy,
            gate_path=gate_path,
            gate=gate,
            label="semantic-resource-reseal",
        )
        with self.assertRaisesRegex(
            AUTH.ExecutionAuthorizationError,
            "original resource/batch owner rejected closure",
        ):
            self.run_gate(
                resource_policy_path=policy_path,
                resource_gate_path=gate_path,
                request_path=request_path,
                authorization_path=authorization_path,
            )

    def test_all_owners_read_one_private_snapshot_during_path_swap(self) -> None:
        original_policy = self.fixture["policy_path"].read_bytes()
        replacement = copy.deepcopy(RESOURCE.load(self.fixture["policy_path"]))
        replacement["limits"]["max_job_cores"] = 1
        replacement = RESOURCE.finalize_policy(replacement)
        replacement_raw = (json.dumps(replacement, sort_keys=True) + "\n").encode("utf-8")
        observed: dict[str, object] = {}
        original_snapshots = AUTH._validation_snapshots

        @contextmanager
        def swap_after_capture(**kwargs):
            with original_snapshots(**kwargs) as snapshots:
                direct = (
                    snapshots.profile, snapshots.identity_binding,
                    snapshots.scientific.receipt, snapshots.scientific.input,
                    snapshots.resource_policy, snapshots.scheduler_snapshot,
                    snapshots.resource_gate, snapshots.execution_batch,
                )
                observed["all_private"] = all(
                    snapshot.private_path.is_relative_to(snapshots.private_root)
                    for snapshot in direct
                )
                observed["root_mode"] = snapshots.private_root.stat().st_mode & 0o777
                observed["copy_modes"] = {
                    snapshot.private_path.stat().st_mode & 0o777 for snapshot in direct
                }
                observed["captured_policy"] = snapshots.resource_policy.raw
                self.fixture["policy_path"].write_bytes(replacement_raw)
                try:
                    yield snapshots
                finally:
                    self.fixture["policy_path"].write_bytes(original_policy)

        with mock.patch.object(AUTH, "_validation_snapshots", swap_after_capture):
            result = self.run_gate()
        self.assertEqual(result["status"], "closure_valid_offline")
        self.assertEqual(observed["captured_policy"], original_policy)
        self.assertTrue(observed["all_private"])
        self.assertEqual(observed["root_mode"], 0o700)
        self.assertEqual(observed["copy_modes"], {0o400})
        self.assertEqual(self.fixture["policy_path"].read_bytes(), original_policy)

    def test_controlled_owner_bundle_rejects_poisoned_module_cache(self) -> None:
        poison = ModuleType("execution_batch")
        poison.__file__ = str(self.root / "poisoned-execution-batch.py")
        prior = sys.modules.get("execution_batch")
        sys.modules["execution_batch"] = poison
        try:
            with self.assertRaisesRegex(
                AUTH.ExecutionAuthorizationError,
                "preexisting owner cache origin mismatch: execution_batch",
            ):
                self.run_gate()
            self.assertIs(sys.modules["execution_batch"], poison)
        finally:
            sys.modules.pop("execution_batch", None)
            if prior is not None:
                sys.modules["execution_batch"] = prior

        with AUTH._controlled_owner_bundle() as owners:
            _, expected_paths = AUTH._owner_source_paths()
            for name, expected in expected_paths.items():
                self.assertEqual(AUTH._module_origin(getattr(owners, name)), expected)
            self.assertIs(owners.resource_efficiency.execution_batch, owners.execution_batch)
            self.assertIs(owners.gaussian_rtwin_pbs.execution_batch, owners.execution_batch)
            self.assertIs(owners.gaussian_rtwin_pbs.resource_efficiency, owners.resource_efficiency)
            self.assertIs(owners.gaussian_rtwin_pbs.protocol_selection, owners.protocol_selection)
        if prior is not None:
            self.assertIs(sys.modules.get("execution_batch"), prior)

    def test_registry_is_untrusted_negative_evidence_only_and_hits_reject(self) -> None:
        empty = self.run_gate()
        self.assertFalse(empty["registry_uniqueness_proven"])
        for field, value in (
            ("known_authorization_ids", [self.fixture["authorization"]["authorization_id"]]),
            ("known_attestation_nonces", ["1" * 32]),
        ):
            registry = copy.deepcopy(self.fixture["registry"])
            registry[field] = value
            registry = AUTH.finalize(registry, "registry_payload_sha256")
            path = self.write_new(f"registry-{field}.json", registry)
            with self.subTest(field=field), self.assertRaises(AUTH.ExecutionAuthorizationError):
                self.run_gate(registry_snapshot_path=path)

        consumed = copy.deepcopy(self.fixture["registry"])
        consumed["known_authorization_ids"] = [self.fixture["authorization"]["authorization_id"]]
        consumed["consumed_authorization_ids"] = [self.fixture["authorization"]["authorization_id"]]
        consumed = AUTH.finalize(consumed, "registry_payload_sha256")
        consumed_path = self.write_new("registry-consumed.json", consumed)
        with self.assertRaises(AUTH.ExecutionAuthorizationError):
            self.run_gate(registry_snapshot_path=consumed_path)

        for field, value in (
            ("known_authorization_ids", ["duplicate-id", "duplicate-id"]),
            ("known_attestation_nonces", ["1" * 32, "1" * 32]),
            ("trusted", True),
            ("validated", True),
        ):
            malformed = copy.deepcopy(self.fixture["registry"])
            malformed[field] = value
            malformed = AUTH.finalize(malformed, "registry_payload_sha256")
            with self.subTest(malformed_field=field), self.assertRaises(AUTH.ExecutionAuthorizationError):
                AUTH.validate_registry_snapshot(malformed, now=self.now)

    def test_request_is_non_authorizing_and_rejects_permission_escalation(self) -> None:
        request = self.fixture["request"]
        self.assertTrue(request["intent_only"])
        self.assertTrue(request["proposal_only"])
        self.assertTrue(request["no_execution_authorization"])
        self.assertFalse(request["calculation_ready"])
        for field, value in (
            ("submit", True),
            ("command", "qsub placeholder"),
            ("argv", ["qsub"]),
            ("path", "/placeholder"),
            ("host", "placeholder.invalid"),
            ("credential", "placeholder"),
        ):
            changed = copy.deepcopy(request)
            changed[field] = value
            changed = AUTH.finalize(changed, "request_payload_sha256")
            with self.subTest(field=field), self.assertRaises(AUTH.ExecutionAuthorizationError):
                AUTH.validate_execution_request(changed)

    def test_authorization_rejects_time_state_side_effect_and_operation_expansion(self) -> None:
        cases: list[dict[str, object]] = []
        for field, value in (
            ("decision", "proposed"),
            ("explicit_human_approval", False),
            ("revocation", {"revoked": True, "revoked_at": "2030-01-01T12:01:00Z", "reason": "synthetic"}),
            ("consumption", {"single_use": True, "consumed": True}),
            ("consumption", {"single_use": False, "consumed": False}),
        ):
            changed = copy.deepcopy(self.fixture["authorization"])
            changed[field] = value
            cases.append(AUTH.finalize(changed, "authorization_payload_sha256"))
        expanded = copy.deepcopy(self.fixture["authorization"])
        expanded["identity_attestation"]["operations"][1]["allowed_read_only_side_effects"].append("run_remote_command")
        expanded["scope_sha256"] = AUTH._scope_sha256(expanded)
        for operation in expanded["authorizations"]:
            operation["scope_sha256"] = expanded["scope_sha256"]
        cases.append(AUTH.finalize(expanded, "authorization_payload_sha256"))
        retry = copy.deepcopy(self.fixture["authorization"])
        retry["authorizations"][2]["automatic_retry"] = True
        cases.append(AUTH.finalize(retry, "authorization_payload_sha256"))
        for case in cases:
            with self.subTest(case=case), self.assertRaises(AUTH.ExecutionAuthorizationError):
                AUTH.validate_execution_authorization(case, now=self.now)

    def test_authorization_artifact_is_the_complete_human_approval_provenance(self) -> None:
        authorization = self.fixture["authorization"]
        self.assertEqual(authorization["approver"], {"principal_id": "human-reviewer"})
        self.assertNotIn("human_decision_record_sha256", json.dumps(authorization))
        base_scope = authorization["scope_sha256"]
        mutations = (
            ("approver", {"principal_id": "second-reviewer"}),
            ("approved_at", "2030-01-01T11:59:59Z"),
            ("revocation", {"revoked": True, "revoked_at": "2030-01-01T12:01:00Z", "reason": "synthetic"}),
            ("consumption", {"single_use": True, "consumed": True}),
        )
        for field, value in mutations:
            changed = copy.deepcopy(authorization)
            changed[field] = value
            with self.subTest(field=field):
                self.assertNotEqual(AUTH._scope_sha256(changed), base_scope)
        changed_operation = copy.deepcopy(authorization)
        changed_operation["authorizations"][2]["automatic_retry"] = True
        self.assertNotEqual(AUTH._scope_sha256(changed_operation), base_scope)

        fake_external_provenance = copy.deepcopy(authorization)
        fake_external_provenance["approver"]["human_decision_record_sha256"] = digest("arbitrary")
        fake_external_provenance = AUTH.finalize(fake_external_provenance, "authorization_payload_sha256")
        with self.assertRaises(AUTH.ExecutionAuthorizationError):
            AUTH.validate_execution_authorization(fake_external_provenance, now=self.now)

    def test_finite_request_schema_owner_shape_parity(self) -> None:
        schema = json.loads((ROOT / "contracts" / "execution" / "execution-request.schema.json").read_text(encoding="utf-8"))
        schema_capabilities = {
            tuple(branch["const"])
            for branch in schema["properties"]["required_capabilities"]["oneOf"]
        }
        optional = ("pbs_cancel_exact", "pbs_fetch_allowlist", "pbs_inspect_exact")
        expected_capabilities = set()
        for mask in range(1 << len(optional)):
            values = {"pbs_submit_once", "typed_identity_attestation"}
            values.update(optional[index] for index in range(len(optional)) if mask & (1 << index))
            expected_capabilities.add(tuple(sorted(values)))
        self.assertEqual(schema_capabilities, expected_capabilities)
        candidates = list(expected_capabilities) + [
            ("typed_identity_attestation", "pbs_submit_once"),
            ("pbs_submit_once",),
            ("pbs_submit_once", "typed_identity_attestation", "unknown"),
            ("pbs_submit_once", "pbs_submit_once", "typed_identity_attestation"),
        ]
        for capabilities in candidates:
            changed = copy.deepcopy(self.fixture["request"])
            changed["required_capabilities"] = list(capabilities)
            changed = AUTH.finalize(changed, "request_payload_sha256")
            owner_accepts = True
            try:
                AUTH.validate_execution_request(changed)
            except AUTH.ExecutionAuthorizationError:
                owner_accepts = False
            with self.subTest(capabilities=capabilities):
                self.assertEqual(tuple(capabilities) in schema_capabilities, owner_accepts)

        sha_pattern = re.compile(schema["$defs"]["sha256"]["pattern"])
        for value in (digest("valid"), "0" * 64, "f" * 63, "G" * 64):
            schema_accepts = sha_pattern.fullmatch(value) is not None
            owner_accepts = True
            try:
                AUTH._sha(value, "finite.sha")
            except AUTH.ExecutionAuthorizationError:
                owner_accepts = False
            with self.subTest(sha=value):
                self.assertEqual(schema_accepts, owner_accepts)

        def schema_resource_accepts(value: dict[str, object]) -> bool:
            for branch_ref in schema["$defs"]["resources"]["oneOf"]:
                branch = schema["$defs"][branch_ref["$ref"].rsplit("/", 1)[1]]
                rules = branch["properties"]
                if set(value) != {"tier", "cores", "memory_gb", "walltime_seconds"}:
                    continue
                accepted = True
                for field, rule in rules.items():
                    item = value[field]
                    if "const" in rule and item != rule["const"]:
                        accepted = False
                    if rule.get("type") == "integer" and (not isinstance(item, int) or isinstance(item, bool)):
                        accepted = False
                    if "minimum" in rule and isinstance(item, int) and item < rule["minimum"]:
                        accepted = False
                    if "maximum" in rule and isinstance(item, int) and item > rule["maximum"]:
                        accepted = False
                if accepted:
                    return True
            return False

        resources = (
            {"tier": "simple", "cores": 8, "memory_gb": 12, "walltime_seconds": 1},
            {"tier": "simple", "cores": 9, "memory_gb": 12, "walltime_seconds": 1},
            {"tier": "general", "cores": 22, "memory_gb": 50, "walltime_seconds": 3600},
            {"tier": "complex", "cores": 44, "memory_gb": 120, "walltime_seconds": 3600},
            {"tier": "custom_reviewed", "cores": 1, "memory_gb": 1, "walltime_seconds": 1},
            {"tier": "custom_reviewed", "cores": 45, "memory_gb": 1, "walltime_seconds": 1},
            {"tier": "custom_reviewed", "cores": 1, "memory_gb": 121, "walltime_seconds": 1},
            {"tier": "custom_reviewed", "cores": 1, "memory_gb": 1, "walltime_seconds": 0},
        )
        for resource in resources:
            owner_accepts = True
            try:
                AUTH._validate_resources(resource, "finite.resources")
            except AUTH.ExecutionAuthorizationError:
                owner_accepts = False
            with self.subTest(resource=resource):
                self.assertEqual(schema_resource_accepts(resource), owner_accepts)

    def test_finite_backend_topology_schema_owner_parity(self) -> None:
        schema = json.loads((ROOT / "contracts" / "execution" / "execution-authorization.schema.json").read_text(encoding="utf-8"))
        topology: dict[str, tuple[int, str]] = {}
        for branch in schema["allOf"]:
            backend = branch["if"]["properties"]["profile"]["properties"]["backend_kind"]["const"]
            hop_count = branch["then"]["properties"]["transport"]["properties"]["hop_count"]["const"]
            attestation_ref = branch["then"]["properties"]["identity_attestation"]["$ref"].rsplit("/", 1)[1]
            mode = schema["$defs"][attestation_ref]["properties"]["mode"]["const"]
            topology[backend] = (hop_count, mode)
        self.assertEqual(topology, {
            "legacy_rtwin_pbs": (2, "legacy_two_stage"),
            "direct_ssh_pbs": (1, "direct_single_stage"),
        })
        original_operations = self.fixture["authorization"]["identity_attestation"]["operations"]
        for backend in topology:
            for hop_count in (1, 2):
                for mode in ("direct_single_stage", "legacy_two_stage"):
                    changed = copy.deepcopy(self.fixture["authorization"])
                    changed["profile"]["backend_kind"] = backend
                    changed["transport"]["hop_count"] = hop_count
                    changed["identity_attestation"]["mode"] = mode
                    changed["identity_attestation"]["operations"] = copy.deepcopy(
                        original_operations[:1] if mode == "direct_single_stage" else original_operations
                    )
                    changed["scope_sha256"] = AUTH._scope_sha256(changed)
                    for operation in changed["authorizations"]:
                        operation["scope_sha256"] = changed["scope_sha256"]
                    changed = AUTH.finalize(changed, "authorization_payload_sha256")
                    owner_accepts = True
                    try:
                        AUTH.validate_execution_authorization(changed, now=self.now)
                    except AUTH.ExecutionAuthorizationError:
                        owner_accepts = False
                    schema_accepts = topology[backend] == (hop_count, mode)
                    with self.subTest(backend=backend, hop_count=hop_count, mode=mode):
                        self.assertEqual(schema_accepts, owner_accepts)

    def test_finite_scientific_receipt_work_kind_parity_and_time_semantics(self) -> None:
        schema = json.loads((ROOT / "contracts" / "execution" / "execution-authorization.schema.json").read_text(encoding="utf-8"))
        rules = schema["$defs"]["scientific_ref"]["oneOf"]
        schema_pairs: set[tuple[str, str]] = set()
        for rule in rules:
            properties = rule["properties"]
            receipt_schemas = [properties["schema"]["const"]] if "const" in properties["schema"] else properties["schema"]["enum"]
            work_kinds = [properties["work_kind"]["const"]] if "const" in properties["work_kind"] else properties["work_kind"]["enum"]
            schema_pairs.update((receipt_schema, work_kind) for receipt_schema in receipt_schemas for work_kind in work_kinds)
        expected_pairs = {
            ("gaussian-input-approval-receipt/1", "ordinary"),
            ("gaussian-input-approval-receipt/1", "minimum"),
            ("gaussian-input-approval-receipt/2", "minimum"),
            ("gaussian-input-approval-receipt/3", "minimum"),
        }
        self.assertEqual(schema_pairs, expected_pairs)
        for receipt_schema in AUTH.SCIENTIFIC_RECEIPT_SCHEMAS:
            for work_kind in AUTH.WORK_KINDS:
                value = copy.deepcopy(self.fixture["authorization"]["scientific_owner_receipt"])
                value["schema"] = receipt_schema
                value["work_kind"] = work_kind
                owner_accepts = True
                try:
                    AUTH._validate_scientific_ref(value)
                except AUTH.ExecutionAuthorizationError:
                    owner_accepts = False
                with self.subTest(receipt_schema=receipt_schema, work_kind=work_kind):
                    self.assertEqual((receipt_schema, work_kind) in schema_pairs, owner_accepts)

        lexical_pattern = re.compile(schema["$defs"]["time"]["pattern"])
        time_cases = (
            ("2030-01-01T12:00:00Z", True, True),
            ("2030-02-30T12:00:00Z", True, False),
            ("2030-01-01T12:00:00", False, False),
            ("2030-01-01T12:00:00+00:00", False, False),
        )
        for value, lexical_accepts, semantic_accepts in time_cases:
            self.assertEqual(lexical_pattern.fullmatch(value) is not None, lexical_accepts)
            owner_accepts = True
            try:
                AUTH._parse_time(value, "finite.time")
            except AUTH.ExecutionAuthorizationError:
                owner_accepts = False
            with self.subTest(time=value):
                self.assertEqual(owner_accepts, semantic_accepts)

    def test_authorization_time_windows_fail_closed(self) -> None:
        cases = (
            ("approved_at", "2030-02-30T12:00:00Z"),
            ("not_before", "2030-01-01T12:03:00Z"),
            ("expires_at", "2030-01-01T12:02:00Z"),
            ("not_before", "2030-01-01T12:00:00+00:00"),
            ("expires_at", "2030-01-01T12:00:00Z"),
        )
        for field, value in cases:
            changed = copy.deepcopy(self.fixture["authorization"])
            changed[field] = value
            changed["scope_sha256"] = AUTH._scope_sha256(changed)
            for operation in changed["authorizations"]:
                operation["scope_sha256"] = changed["scope_sha256"]
            changed = AUTH.finalize(changed, "authorization_payload_sha256")
            with self.subTest(field=field, value=value), self.assertRaises(AUTH.ExecutionAuthorizationError):
                AUTH.validate_execution_authorization(changed, now=self.now)

    def test_exact_binding_mutations_fail_closed(self) -> None:
        mutations = (
            ("profile", "profile_sha256", digest("wrong-profile")),
            ("transport", "identity_binding_sha256", digest("wrong-transport")),
            ("target", "effective_target_identity_sha256", digest("wrong-target")),
            ("resources", "cores", 22),
            ("execution", "idempotency_key", "different-key"),
            ("scientific_owner_receipt", "input_sha256", digest("wrong-input")),
        )
        for section, field, value in mutations:
            authorization = copy.deepcopy(self.fixture["authorization"])
            authorization[section][field] = value
            if section == "resources":
                authorization["runtime_binding"]["resources"][field] = value
                authorization["runtime_binding"] = seal_embedded(authorization["runtime_binding"], "runtime_binding_sha256")
            authorization["scope_sha256"] = AUTH._scope_sha256(authorization)
            for operation in authorization["authorizations"]:
                operation["scope_sha256"] = authorization["scope_sha256"]
            authorization = AUTH.finalize(authorization, "authorization_payload_sha256")
            path = self.write_new(f"changed-{section}-{field}.json", authorization)
            with self.subTest(section=section, field=field), self.assertRaises(AUTH.ExecutionAuthorizationError):
                self.run_gate(authorization_path=path)

    def test_each_upstream_reference_and_exact_input_mismatch_fails_closed(self) -> None:
        for index in range(5):
            request = copy.deepcopy(self.fixture["request"])
            request["upstream_artifact_refs"][index]["sha256"] = digest(f"wrong-upstream-{index}")
            request = AUTH.finalize(request, "request_payload_sha256")
            request_path = self.write_new(f"request-upstream-{index}.json", request)
            authorization = copy.deepcopy(self.fixture["authorization"])
            authorization["request"]["request_payload_sha256"] = request["request_payload_sha256"]
            authorization["scope_sha256"] = AUTH._scope_sha256(authorization)
            for operation in authorization["authorizations"]:
                operation["scope_sha256"] = authorization["scope_sha256"]
            authorization = AUTH.finalize(authorization, "authorization_payload_sha256")
            authorization_path = self.write_new(f"authorization-upstream-{index}.json", authorization)
            with self.subTest(upstream_index=index), self.assertRaises(AUTH.ExecutionAuthorizationError):
                self.run_gate(request_path=request_path, authorization_path=authorization_path)

        request = copy.deepcopy(self.fixture["request"])
        request["input"]["sha256"] = digest("wrong-exact-input")
        request = AUTH.finalize(request, "request_payload_sha256")
        request_path = self.write_new("request-wrong-input.json", request)
        authorization = copy.deepcopy(self.fixture["authorization"])
        authorization["request"]["request_payload_sha256"] = request["request_payload_sha256"]
        authorization["scope_sha256"] = AUTH._scope_sha256(authorization)
        for operation in authorization["authorizations"]:
            operation["scope_sha256"] = authorization["scope_sha256"]
        authorization = AUTH.finalize(authorization, "authorization_payload_sha256")
        authorization_path = self.write_new("authorization-wrong-request-input.json", authorization)
        with self.assertRaises(AUTH.ExecutionAuthorizationError):
            self.run_gate(request_path=request_path, authorization_path=authorization_path)

    def test_capability_workspace_runtime_gate_batch_task_attempt_closure_mismatches(self) -> None:
        binding = PLATFORM.load_transport_identity_binding(self.fixture["binding_path"])
        profile = PLATFORM.build_execution_profile(
            profile_id="profile-placeholder",
            backend_kind="legacy_rtwin_pbs",
            transport_config_ref="/opt/placeholder/config/rtwin-ssh-config",
            identity_binding=binding,
            declared_capabilities=["typed_identity_attestation"],
        )
        profile_path = self.write_new("profile-missing-capability.json", profile)
        request = copy.deepcopy(self.fixture["request"])
        request["profile_sha256"] = profile["profile_payload_sha256"]
        request = AUTH.finalize(request, "request_payload_sha256")
        request_path = self.write_new("request-missing-capability.json", request)
        authorization = copy.deepcopy(self.fixture["authorization"])
        authorization["profile"]["profile_sha256"] = profile["profile_payload_sha256"]
        authorization["request"]["request_payload_sha256"] = request["request_payload_sha256"]
        authorization["scope_sha256"] = AUTH._scope_sha256(authorization)
        for operation in authorization["authorizations"]:
            operation["scope_sha256"] = authorization["scope_sha256"]
        authorization = AUTH.finalize(authorization, "authorization_payload_sha256")
        authorization_path = self.write_new("authorization-missing-capability.json", authorization)
        with self.assertRaises(AUTH.ExecutionAuthorizationError):
            self.run_gate(profile_path=profile_path, request_path=request_path, authorization_path=authorization_path)

        mutations: list[tuple[str, dict[str, object]]] = []
        workspace = copy.deepcopy(self.fixture["authorization"])
        workspace["workspace_binding"]["project"] = "otherjob"
        workspace["workspace_binding"]["remote_workdir"] = "/home/user100/SDL/otherjob"
        workspace["workspace_binding"] = seal_embedded(workspace["workspace_binding"], "workspace_binding_sha256")
        workspace["runtime_binding"]["workspace_binding_sha256"] = workspace["workspace_binding"]["workspace_binding_sha256"]
        workspace["runtime_binding"] = seal_embedded(workspace["runtime_binding"], "runtime_binding_sha256")
        mutations.append(("workspace", workspace))
        runtime = copy.deepcopy(self.fixture["authorization"])
        runtime["runtime_binding"]["executable_ref_sha256"] = digest("different-executable")
        runtime["runtime_binding"] = seal_embedded(runtime["runtime_binding"], "runtime_binding_sha256")
        mutations.append(("runtime", runtime))
        resource_gate = copy.deepcopy(self.fixture["authorization"])
        resource_gate["resource_chain"]["gate"]["sha256"] = digest("different-gate")
        mutations.append(("resource-gate", resource_gate))
        batch = copy.deepcopy(self.fixture["authorization"])
        batch["execution"]["batch_id"] = "different-batch"
        mutations.append(("batch", batch))
        task = copy.deepcopy(self.fixture["authorization"])
        task["execution"]["scientific_task_id"] = "scientific-task-" + digest("different-task")
        mutations.append(("task", task))
        attempt = copy.deepcopy(self.fixture["authorization"])
        attempt["execution"]["attempt_id"] = "qsub-attempt-" + digest("different-attempt")
        mutations.append(("attempt", attempt))
        for label, changed in mutations:
            changed["scope_sha256"] = AUTH._scope_sha256(changed)
            for operation in changed["authorizations"]:
                operation["scope_sha256"] = changed["scope_sha256"]
            changed = AUTH.finalize(changed, "authorization_payload_sha256")
            path = self.write_new(f"authorization-{label}.json", changed)
            with self.subTest(label=label), self.assertRaises(AUTH.ExecutionAuthorizationError):
                self.run_gate(authorization_path=path)

    def test_nonce_chain_and_sensitive_or_command_fields_fail_closed(self) -> None:
        duplicated_nonce = copy.deepcopy(self.fixture["authorization"])
        duplicated_nonce["identity_attestation"]["operations"][1]["request_nonce"] = "1" * 32
        duplicated_nonce["scope_sha256"] = AUTH._scope_sha256(duplicated_nonce)
        for operation in duplicated_nonce["authorizations"]:
            operation["scope_sha256"] = duplicated_nonce["scope_sha256"]
        duplicated_nonce = AUTH.finalize(duplicated_nonce, "authorization_payload_sha256")
        with self.assertRaises(AUTH.ExecutionAuthorizationError):
            AUTH.validate_execution_authorization(duplicated_nonce, now=self.now)

        for field, value in (
            ("command", "qsub placeholder"),
            ("shell", "placeholder-shell"),
            ("argv", ["qsub", "placeholder"]),
            ("credential_path", "/placeholder/private.key"),
            ("host", "placeholder.invalid"),
        ):
            changed = copy.deepcopy(self.fixture["authorization"])
            changed[field] = value
            changed = AUTH.finalize(changed, "authorization_payload_sha256")
            with self.subTest(field=field), self.assertRaises(AUTH.ExecutionAuthorizationError):
                AUTH.validate_execution_authorization(changed, now=self.now)

    def test_legacy_only_live_approval_cannot_enter_profile_mode(self) -> None:
        legacy = {
            "schema": "auto-g16-live-submission-approval/9",
            "decision": "approved",
            "explicit_confirmation": True,
        }
        path = self.write_new("legacy-live-approval.json", legacy)
        with self.assertRaises(AUTH.ExecutionAuthorizationError):
            self.run_gate(authorization_path=path)

    def test_new_contract_decoder_rejects_duplicate_bom_float_and_symlink(self) -> None:
        bad = self.root / "bad-request.json"
        for raw in (
            b'{"schema":"auto-g16-execution-request/1","schema":"auto-g16-execution-request/1"}',
            b"\xef\xbb\xbf{}",
            b'{"schema":NaN}',
            b'{"schema":1.0}',
            bytes((255, 254, 123, 125)),
            b'[]',
        ):
            bad.write_bytes(raw)
            with self.subTest(raw=raw), self.assertRaises(AUTH.ExecutionAuthorizationError):
                AUTH._load_new_contract(bad, AUTH.validate_execution_request, "execution request")
        link = self.root / "request-link.json"
        try:
            link.symlink_to(self.fixture["request_path"].name)
        except OSError:
            self.skipTest("symlinks unavailable")
        with self.assertRaises(AUTH.ExecutionAuthorizationError):
            AUTH._load_new_contract(link, AUTH.validate_execution_request, "execution request")

        wrong_hash = copy.deepcopy(self.fixture["request"])
        wrong_hash["request_payload_sha256"] = digest("wrong-self-hash")
        with self.assertRaises(AUTH.ExecutionAuthorizationError):
            AUTH.validate_execution_request(wrong_hash)

        request_type_cases = (
            ("required_capabilities", [{"not": "hashable"}]),
            ("work_kind", ["minimum"]),
            ("backend_kind", ["legacy_rtwin_pbs"]),
        )
        for field, value in request_type_cases:
            changed = copy.deepcopy(self.fixture["request"])
            changed[field] = value
            changed = AUTH.finalize(changed, "request_payload_sha256")
            with self.subTest(request_field=field), self.assertRaises(AUTH.ExecutionAuthorizationError):
                AUTH.validate_execution_request(changed)

        authorization_type_cases = (
            ("authorizations", [1, 2, 3]),
            ("profile", {**self.fixture["authorization"]["profile"], "backend_kind": ["legacy_rtwin_pbs"]}),
        )
        for field, value in authorization_type_cases:
            changed = copy.deepcopy(self.fixture["authorization"])
            changed[field] = value
            changed = AUTH.finalize(changed, "authorization_payload_sha256")
            with self.subTest(authorization_field=field), self.assertRaises(AUTH.ExecutionAuthorizationError):
                AUTH.validate_execution_authorization(changed, now=self.now)

        registry = copy.deepcopy(self.fixture["registry"])
        registry["known_authorization_ids"] = [{"not": "hashable"}]
        registry = AUTH.finalize(registry, "registry_payload_sha256")
        with self.assertRaises(AUTH.ExecutionAuthorizationError):
            AUTH.validate_registry_snapshot(registry, now=self.now)

        input_link = self.root / "input-link.gjf"
        input_link.symlink_to(self.fixture["input_path"].name)
        with self.assertRaises(AUTH.ExecutionAuthorizationError):
            self.run_gate(input_path=input_link)

    def test_schema_documents_are_closed_required_equals_properties_and_only_two_new_schemas(self) -> None:
        paths = {
            "execution-request.schema.json": AUTH.REQUEST_SCHEMA,
            "execution-authorization.schema.json": AUTH.AUTHORIZATION_SCHEMA,
        }
        self.assertFalse((ROOT / "contracts" / "execution" / "execution-authorization-readiness.schema.json").exists())
        self.assertFalse((ROOT / "contracts" / "execution" / "execution-authorization-registry-snapshot.schema.json").exists())

        def inspect(node: object) -> None:
            if isinstance(node, dict):
                if node.get("type") == "object" and "properties" in node:
                    self.assertFalse(node.get("additionalProperties", True))
                    self.assertEqual(set(node.get("required", [])), set(node["properties"]))
                for value in node.values():
                    inspect(value)
            elif isinstance(node, list):
                for value in node:
                    inspect(value)

        for name, schema_id in paths.items():
            schema = json.loads((ROOT / "contracts" / "execution" / name).read_text(encoding="utf-8"))
            self.assertEqual(schema["$id"], schema_id)
            inspect(schema)

    def test_closed_skill_package_has_single_owner_and_git_free_import(self) -> None:
        package = skill_package.package_files(ROOT, "auto-g16-rtwin-pbs")
        self.assertEqual(
            package[Path("scripts/execution_authorization.py")],
            ROOT / "scripts" / "execution_authorization.py",
        )
        for name in ("execution-request.schema.json", "execution-authorization.schema.json"):
            self.assertEqual(
                package[Path("contracts/execution") / name],
                ROOT / "contracts" / "execution" / name,
            )
        self.assertFalse((ROOT / "skills" / "auto-g16-rtwin-pbs" / "scripts" / "execution_authorization.py").exists())

        with tempfile.TemporaryDirectory() as temporary:
            installed = Path(temporary) / "auto-g16-rtwin-pbs"
            for target, source in package.items():
                destination = installed / target
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
            self.assertFalse((installed / ".git").exists())
            script_dir = installed / "scripts"
            prior_owners = {
                name: sys.modules.pop(name, None)
                for name in AUTH._OWNER_MODULE_FILENAMES
            }
            sys.path.insert(0, str(script_dir))
            try:
                spec = importlib.util.spec_from_file_location("packaged_execution_authorization", script_dir / "execution_authorization.py")
                self.assertIsNotNone(spec)
                self.assertIsNotNone(spec.loader if spec else None)
                module = importlib.util.module_from_spec(spec)
                assert spec and spec.loader
                sys.modules[spec.name] = module
                try:
                    spec.loader.exec_module(module)
                finally:
                    sys.modules.pop(spec.name, None)
                self.assertEqual(Path(module.platform_contracts.__file__).resolve(), (script_dir / "platform_contracts.py").resolve())
                packaged_request = module.validate_execution_request(self.fixture["request"])
                self.assertEqual(module.platform_contracts.canonical_bytes(packaged_request), PLATFORM.canonical_bytes(self.fixture["request"]))
            finally:
                sys.path.remove(str(script_dir))
                for name in AUTH._OWNER_MODULE_FILENAMES:
                    sys.modules.pop(name, None)
                    if prior_owners[name] is not None:
                        sys.modules[name] = prior_owners[name]

    def test_owner_has_no_cli_network_subprocess_or_mutating_registry_surface(self) -> None:
        source = (ROOT / "scripts" / "execution_authorization.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports: set[str] = set()
        functions = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module.split(".", 1)[0])
        self.assertTrue(imports.isdisjoint({"argparse", "subprocess", "socket", "urllib", "requests", "paramiko"}))
        self.assertFalse(any(name.startswith(("submit", "consume", "persist", "reserve", "cancel", "delete")) for name in functions))
        self.assertEqual(set(inspect.signature(AUTH.validate_authorization_gate).parameters), {
            "request_path", "authorization_path", "profile_path", "identity_binding_path",
            "input_path", "scientific_receipt_path", "resource_policy_path",
            "scheduler_snapshot_path", "resource_gate_path", "execution_batch_path",
            "registry_snapshot_path", "now",
        })
        for forbidden in ("ready_to_submit", "authorized_for_live", "qdel", "rm -", "ssh "):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
