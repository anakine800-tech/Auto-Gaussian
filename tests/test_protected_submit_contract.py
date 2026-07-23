#!/usr/bin/env python3
"""Placeholder-only offline tests for the PR4D protected-submit contract."""

from __future__ import annotations

import contextlib
import copy
import hashlib
import inspect
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import types
import unittest
from unittest import mock
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).parents[1]
ROOT_SCRIPTS = ROOT / "scripts"
SKILL_SCRIPTS = ROOT / "skills" / "auto-g16-rtwin-pbs" / "scripts"
os.environ["AUTO_G16_RUNTIME_CONFIG"] = str(
    Path("/private/tmp")
    / "auto-g16-protected-submit-placeholder-runtime-config-does-not-exist.json"
)
sys.path.insert(0, str(ROOT_SCRIPTS))
sys.path.insert(0, str(SKILL_SCRIPTS))

import execution_batch as BATCH  # noqa: E402
import execution_facade as FACADE  # noqa: E402
import gaussian_rtwin_pbs as PBS  # noqa: E402
import protected_submit_contract as CONTRACT  # noqa: E402
import resource_efficiency as RESOURCE  # noqa: E402
import skill_package  # noqa: E402
from tests import test_protocol_selection as PROTOCOL_TESTS  # noqa: E402
from tests import test_transport_authority_closure as CLOSURE_TESTS  # noqa: E402


NOW = "2030-01-01T12:02:00Z"
APPROVED_AT = "2030-01-01T12:00:00Z"
EXPIRES_AT = "2030-01-01T12:04:00Z"


def parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
        timezone.utc
    )


class PrivateTestClock:
    def __init__(self, *values: str) -> None:
        self._values = tuple(parse_utc(value) for value in values)
        self._index = 0
        self._lock = threading.Lock()

    def __call__(self) -> datetime:
        with self._lock:
            value = self._values[min(self._index, len(self._values) - 1)]
            self._index += 1
            return value


def identity(input_sha256: str) -> dict[str, str]:
    return {
        "structure_sha256": hashlib.sha256(b"placeholder structure").hexdigest(),
        "chemical_hypothesis_sha256": hashlib.sha256(
            b"placeholder scientific hypothesis"
        ).hexdigest(),
        "method_protocol_sha256": hashlib.sha256(
            b"placeholder reviewed method"
        ).hexdigest(),
        "calculation_objective_sha256": hashlib.sha256(
            b"placeholder calculation objective"
        ).hexdigest(),
        "relevant_input_sha256": input_sha256,
    }


class ProtectedSubmitFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.transport = CLOSURE_TESTS.TransportAuthorityClosureTests(
            "test_request_authorization_and_actual_receipt_chain_close_offline"
        )
        self.transport.setUp()
        self.input_path, self.input_approval_path = self._input_approval()
        self.report = PBS.parse_gaussian(self.input_path)
        self.input_sha256 = self.report["input_sha256"]
        self.ledger_path, self.task_id = self._ledger()
        self.ledger = RESOURCE.validate_ledger(RESOURCE.load(self.ledger_path))
        self.policy = self._policy()
        (
            self.scheduler,
            self.scheduler_artifact_sha256,
            self.scheduler_artifact_size,
            self.scheduler_artifact_bytes,
        ) = self._scheduler_snapshot()
        self.idempotency_key = "protected-submit-placeholder-key"
        self.attempt_id = BATCH.attempt_id_for(
            self.ledger["batch"]["batch_id"], self.idempotency_key
        )
        self.gate = self._gate()
        self.input_approval = PBS.validate_input_approval(
            self.input_approval_path,
            self.input_path,
            self.report,
            "minimum",
        )
        self.live_approval_path = self._live_approval()

    def _input_approval(self) -> tuple[Path, Path]:
        protocol_helper = PROTOCOL_TESTS.ProtocolSelectionTests(
            "test_selection_is_hash_bound_and_only_authorizes_offline_draft"
        )
        _, _, options_path, options = protocol_helper.build_files(self.root)
        approval_path = self.root / "protocol-selection-approval.json"
        approval_path.write_text(
            json.dumps(
                {
                    "decision": "selected",
                    "tier": "strict",
                    "explicit_confirmation": True,
                    "decision_reason": "Placeholder reviewer selected the exact fixture.",
                }
            ),
            encoding="utf-8",
        )
        selection = PROTOCOL_TESTS.PROTOCOL.build_selection(
            options_path, "strict", approval_path
        )
        selection_path = self.root / "protocol-selection.json"
        PROTOCOL_TESTS.PROTOCOL.write_new_json(selection_path, selection)
        selected = PROTOCOL_TESTS.PROTOCOL.get_selected_option(options, selection)
        profile = selected["method_profiles"][0]
        task = selected["task_plan"][0]

        input_path = self.root / "minimum.gjf"
        input_path.write_text(
            "%chk=minimum.chk\n"
            "%mem=12GB\n"
            "%nprocshared=8\n"
            "#p hf/sto-3g opt freq\n\n"
            "placeholder minimum\n\n"
            "0 1\n"
            "C 0.0 0.0 0.0\n"
            "C 1.0 0.0 0.0\n"
            "O 2.0 0.0 0.0\n"
            "H 0.0 1.0 0.0\n"
            "H 0.0 -1.0 0.0\n"
            "H 1.0 1.0 0.0\n"
            "H 1.0 -1.0 0.0\n"
            "H 2.0 1.0 0.0\n"
            "H 2.0 -1.0 0.0\n\n",
            encoding="utf-8",
        )
        report = PBS.parse_gaussian(input_path)
        protocol_binding = {
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
        }
        route_mapping = {
            "exact_route": report["route"],
            "method": {
                "route_value": "hf",
                "profile_id": profile["profile_id"],
                "selected_value": copy.deepcopy(profile["functional_or_method"]),
                "human_confirmed": True,
            },
            "basis": {
                "route_value": "sto-3g",
                "profile_id": profile["profile_id"],
                "selected_value": copy.deepcopy(profile["basis_stack"]),
                "human_confirmed": True,
            },
            "solvent": {
                "route_value": "none",
                "profile_id": profile["profile_id"],
                "selected_value": copy.deepcopy(profile["solvation"]),
                "human_confirmed": True,
            },
            "scf": {
                "route_value": "default",
                "profile_id": profile["profile_id"],
                "selected_value": copy.deepcopy(profile["scf"]),
                "human_confirmed": True,
            },
            "tasks": [
                {
                    "task_index": 0,
                    "stage_type": task["stage_type"],
                    "profile_id": task["profile_id"],
                    "route_evidence": ["minimum_opt", "frequency"],
                    "human_confirmed": True,
                }
            ],
            "explicit_confirmation": True,
        }
        review_draft = {
            "schema": PBS.INPUT_REVIEW_SCHEMA,
            "review_id": "protected_submit_placeholder_minimum",
            "work_kind": "minimum",
            "protocol_task_types": selection["scope_binding"]["task_types"],
            "protocol_binding": protocol_binding,
            "route_profile_mapping": route_mapping,
            "protocol_family_completion": False,
            "approved_input": PBS._input_approval_facts(report),
            "decision": {
                "status": "accepted_exact_input",
                "explicit_confirmation": True,
                "reviewer": "placeholder reviewer",
                "reviewed_at": "2030-01-01T11:59:00Z",
                "rationale": "Placeholder-only exact local consistency fixture.",
            },
            "calculation_ready": False,
            "no_submission_authorization": True,
            "payload_sha256": None,
        }
        draft_path = self.root / "input-review-draft.json"
        review_path = self.root / "input-review.json"
        receipt_path = self.root / "input-approval.json"
        draft_path.write_text(json.dumps(review_draft), encoding="utf-8")
        PBS.finalize_input_review(draft_path, review_path)
        PBS.build_input_approval_receipt(
            options_path,
            selection_path,
            review_path,
            input_path,
            receipt_path,
            "protected-submit-placeholder-receipt",
        )
        return input_path, receipt_path

    def _ledger(self) -> tuple[Path, str]:
        review = BATCH.finalize_review(
            json.loads(
                (
                    ROOT
                    / "tests/fixtures/rtwin_pbs/execution_batch_review.template.json"
                ).read_text(encoding="utf-8")
            )
        )
        review_path = self.root / "execution-batch-review.json"
        review_path.write_text(json.dumps(review), encoding="utf-8")
        ledger_path = self.root / "execution-batch.json"
        BATCH.initialize(
            review_path, ledger_path, timestamp="2030-01-01T11:55:00Z"
        )
        task = BATCH.admit_task(
            ledger_path,
            identity(self.input_sha256),
            estimated_core_hours=4,
            reason="placeholder exact reviewed scientific task",
            reviewer="placeholder reviewer",
            reviewed_at="2030-01-01T11:56:00Z",
        )
        BATCH.migrate_to_submission_ledger(
            ledger_path,
            migrated_at="2030-01-01T11:57:00Z",
            migration_source="placeholder fixture",
        )
        RESOURCE.migrate_v2_to_v3(
            ledger_path,
            migrated_at="2030-01-01T11:58:00Z",
            migration_source="placeholder resource fixture",
        )
        return ledger_path, task["scientific_task_id"]

    def _policy(self) -> dict:
        return RESOURCE.finalize_policy(
            {
                "schema": RESOURCE.POLICY_SCHEMA,
                "policy_id": "protected-submit-placeholder-policy",
                "reviewed_at": "2030-01-01T11:58:30Z",
                "reviewer": "placeholder reviewer",
                "limits": {
                    "max_estimated_core_hours": 100,
                    "max_remaining_core_hours": 100,
                    "max_concurrent_unresolved_attempts": 2,
                    "max_concurrent_active_attempts": 2,
                    "max_total_cores": 16,
                    "max_total_memory_gb": 24,
                    "max_job_cores": 8,
                    "max_job_memory_gb": 12,
                    "max_job_walltime_seconds": 7200,
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
            }
        )

    def _scheduler_snapshot(self) -> tuple[dict, str, int, bytes]:
        snapshot = RESOURCE.finalize_scheduler_snapshot(
            {
                "schema": RESOURCE.SCHEDULER_SNAPSHOT_SCHEMA,
                "snapshot_id": "protected-submit-placeholder-snapshot",
                "collected_at": "2030-01-01T12:01:00Z",
                "source": "synthetic complete local snapshot",
                "scope": {
                    "kind": "complete_user_active_jobs",
                    "owner": "placeholder",
                    "completeness": "complete",
                    "batch_evidence_sha256": hashlib.sha256(
                        b"placeholder scheduler evidence"
                    ).hexdigest(),
                },
                "transport": {"classification": "success", "status": "known"},
                "freshness": {
                    "classification": "fresh",
                    "age_seconds": 60,
                    "max_age_seconds": 300,
                },
                "attempts": [],
                "payload_sha256": "",
            }
        )
        path = self.root / "scheduler-snapshot.json"
        path.write_text(
            json.dumps(snapshot, sort_keys=True) + "\n", encoding="utf-8"
        )
        raw = path.read_bytes()
        _, artifact_sha256, artifact_size = RESOURCE.load_artifact(path)
        return snapshot, artifact_sha256, artifact_size, raw

    def _gate(self) -> dict:
        return RESOURCE.evaluate_gate(
            self.ledger,
            self.policy,
            self.scheduler,
            gate_id="protected-submit-placeholder-gate",
            evaluated_at=NOW,
            scientific_task_id=self.task_id,
            attempt_id=self.attempt_id,
            project="safejob",
            input_sha256=self.input_sha256,
            resource_tier="simple",
            cores=8,
            memory_gb=12,
            walltime_seconds=3600,
            estimated_core_hours=4,
            scheduler_artifact_sha256=self.scheduler_artifact_sha256,
            scheduler_artifact_size=self.scheduler_artifact_size,
        )

    def _live_approval(self) -> Path:
        summary = PBS.live_approval_summary(
            "safejob",
            self.report,
            None,
            "minimum",
            self.input_approval,
        )
        summary["execution"] = {
            "batch_id": self.ledger["batch"]["batch_id"],
            "review_sha256": self.ledger["batch"]["review_sha256"],
            "scientific_task_id": self.task_id,
            "attempt_id": self.attempt_id,
            "idempotency_key": self.idempotency_key,
            "estimated_core_hours": 4,
            "estimated_core_hours_evidence": {
                "source": "placeholder reviewed estimate",
                "sha256": hashlib.sha256(
                    b"placeholder estimate evidence"
                ).hexdigest(),
            },
            "resource_binding": {
                "policy_id": self.gate["policy_id"],
                "policy_sha256": self.gate["policy_sha256"],
                "gate_id": self.gate["gate_id"],
                "gate_sha256": self.gate["gate_sha256"],
                "resource_tier": "simple",
                "cores": 8,
                "memory_gb": 12,
                "walltime_seconds": 3600,
            },
        }
        schema, scope = PBS.expected_live_approval_scope(summary)
        self.estimated_core_hours_evidence = copy.deepcopy(
            summary["execution"]["estimated_core_hours_evidence"]
        )
        live = {
            "schema": schema,
            "approval_id": "protected-submit-placeholder-approval",
            "approver_identity": "placeholder operator",
            "approved_at": APPROVED_AT,
            "expires_at": EXPIRES_AT,
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
        path = self.root / "live-approval.json"
        path.write_text(json.dumps(live, sort_keys=True) + "\n", encoding="utf-8")
        return path

    def transport_artifacts(self) -> dict[str, dict]:
        return {
            "successor_request": self.transport.request_v2,
            "successor_authorization": self.transport.authorization_v2,
            "base_request": self.transport.base_request,
            "base_authorization": self.transport.base_authorization,
            "profile_v1": self.transport.profile_v1,
            "profile_v2": self.transport.profile_v2,
            "identity_binding": self.transport.binding,
            "first_hop_request": self.transport.first_request,
            "first_hop_receipt": self.transport.first_receipt,
            "nested_hop_request": self.transport.nested_request,
            "nested_hop_receipt": self.transport.nested_receipt,
            "handshake_request": self.transport.handshake_request,
            "handshake_observation": self.transport.observation,
            "handshake_receipt": self.transport.handshake_receipt,
        }

    def evidence(self, **changes: object) -> CONTRACT.ProtectedSubmitEvidence:
        values: dict[str, object] = {
            "input_path": self.input_path,
            "input_approval_path": self.input_approval_path,
            "live_approval_path": self.live_approval_path,
            "execution_ledger": self.ledger,
            "resource_policy": self.policy,
            "resource_gate": self.gate,
            "scheduler_snapshot": self.scheduler,
            "scheduler_snapshot_artifact": self.scheduler_artifact_bytes,
            "project": "safejob",
            "scientific_task_id": self.task_id,
            "idempotency_key": self.idempotency_key,
            "estimated_core_hours_evidence": self.estimated_core_hours_evidence,
            "work_kind": "minimum",
            "transport_artifacts": self.transport_artifacts(),
        }
        values.update(changes)
        return CONTRACT.ProtectedSubmitEvidence(**values)  # type: ignore[arg-type]


class ProtectedSubmitContractTests(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.fixture = ProtectedSubmitFixture(self.root)
        self.state_root = self.root / "trusted-state"

    def tearDown(self) -> None:
        self.fixture.transport.tearDown()
        self.temporary.cleanup()

    def owner(
        self, *clock_values: str
    ) -> CONTRACT.ProtectedSubmitContractOwner:
        values = clock_values or (NOW,)
        return CONTRACT.ProtectedSubmitContractOwner._for_testing_with_clock(
            self.state_root,
            PrivateTestClock(*values),
            _test_token=CONTRACT._TEST_OWNER_TOKEN,
        )

    @contextlib.contextmanager
    def caller_runtime_environment(
        self,
        marker: str,
    ) -> object:
        saved = {
            name: (name in os.environ, os.environ.get(name))
            for name in CONTRACT._RUNTIME_ENVIRONMENT_NAMES
        }
        try:
            for name in CONTRACT._RUNTIME_ENVIRONMENT_NAMES:
                os.environ[name] = f"{marker}-{name.lower()}"
            yield
        finally:
            for name, (present, value) in saved.items():
                if present:
                    assert value is not None
                    os.environ[name] = value
                else:
                    os.environ.pop(name, None)

    def test_complete_existing_owner_closure_seals_non_executable_bundle(self) -> None:
        sealed = self.owner().seal(self.fixture.evidence())
        sealed.assert_owner_sealed()
        document = sealed.document()
        schema_path = (
            ROOT / "contracts/execution/protected-submit-bundle.schema.json"
        )
        self.assertEqual(CLOSURE_TESTS.schema_errors(schema_path, document), [])
        self.assertEqual(
            CONTRACT.validate_protected_submit_bundle(document), document
        )
        self.assertEqual(
            document["operation_order"],
            ["reserve_once", "stage_exact_bundle", "submit_once"],
        )
        self.assertEqual(document["workspace"]["allowed_root"], "/home/user100/SDL")
        self.assertTrue(document["authority"]["scope"]["stage"])
        self.assertTrue(document["authority"]["scope"]["submit"])
        for denied in (
            "status",
            "fetch",
            "cancel",
            "cleanup",
            "delete",
            "arbitrary_command",
        ):
            self.assertFalse(document["authority"]["scope"][denied])
        self.assertNotIn("path", json.dumps(document).lower())
        self.assertFalse(document["evidence_status"]["actual_adapter_verified"])
        self.assertFalse(document["evidence_status"]["live_validation_performed"])
        self.assertFalse(self.state_root.exists())

    def test_owner_replay_is_isolated_from_caller_runtime_configuration(self) -> None:
        invalid_config = self.root / "caller-runtime-config.json"
        invalid_config.write_text("not placeholder JSON\n", encoding="utf-8")
        saved = {
            name: os.environ.get(name)
            for name in CONTRACT._RUNTIME_ENVIRONMENT_NAMES
        }
        try:
            os.environ["AUTO_G16_RUNTIME_CONFIG"] = str(invalid_config)
            os.environ["AUTO_G16_WINDOWS_PROJECT_ROOT"] = (
                r"C:\caller-placeholder-project"
            )
            document = self.owner().seal(self.fixture.evidence()).document()
        finally:
            for name, value in saved.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value
        self.assertNotIn("caller-placeholder", json.dumps(document))
        self.assertEqual(
            os.environ.get("AUTO_G16_RUNTIME_CONFIG"),
            saved["AUTO_G16_RUNTIME_CONFIG"],
        )

    def test_delayed_scientific_and_resource_replay_stays_inside_isolation(self) -> None:
        caller_marker = str(self.root / "caller-placeholder-config")
        observations: list[str] = []
        real_graph = CONTRACT._skill_owner_graph

        @contextlib.contextmanager
        def observed_graph() -> object:
            with real_graph() as modules:
                resource_owner = modules["resource_efficiency"]
                scientific_owner = modules["gaussian_rtwin_pbs"]
                original_ledger = resource_owner.validate_ledger
                original_read = scientific_owner.read_stable_bytes

                def observed_validate_ledger(*args: object, **kwargs: object) -> object:
                    runtime_config = os.environ["AUTO_G16_RUNTIME_CONFIG"]
                    self.assertNotIn("caller-placeholder-config", runtime_config)
                    self.assertIn(
                        "intentionally-absent-runtime.json",
                        runtime_config,
                    )
                    observations.append(f"resource:{runtime_config}")
                    return original_ledger(*args, **kwargs)

                def observed_read_stable_bytes(
                    *args: object,
                    **kwargs: object,
                ) -> object:
                    runtime_config = os.environ["AUTO_G16_RUNTIME_CONFIG"]
                    self.assertNotIn("caller-placeholder-config", runtime_config)
                    observations.append(f"scientific:{runtime_config}")
                    return original_read(*args, **kwargs)

                resource_owner.validate_ledger = observed_validate_ledger
                scientific_owner.read_stable_bytes = (
                    observed_read_stable_bytes
                )
                try:
                    yield modules
                finally:
                    resource_owner.validate_ledger = original_ledger
                    scientific_owner.read_stable_bytes = original_read

        with self.caller_runtime_environment(caller_marker):
            with mock.patch.object(
                CONTRACT,
                "_skill_owner_graph",
                observed_graph,
            ):
                self.owner().seal(self.fixture.evidence())
            self.assertIn(
                "caller-placeholder-config",
                os.environ["AUTO_G16_RUNTIME_CONFIG"],
            )
        self.assertTrue(observations)
        self.assertTrue(any(item.startswith("resource:") for item in observations))
        self.assertTrue(any(item.startswith("scientific:") for item in observations))

    def test_delayed_transport_replay_stays_inside_isolation(self) -> None:
        caller_marker = str(self.root / "caller-transport-config")
        real_loader = CONTRACT._load_transport_owner
        observations: list[str] = []

        def observed_loader() -> object:
            module = real_loader()
            original_closure = module.validate_successor_closure
            original_receipt = module.validate_handshake_authority_binding

            def observed_closure(*args: object, **kwargs: object) -> object:
                runtime_config = os.environ["AUTO_G16_RUNTIME_CONFIG"]
                self.assertNotIn("caller-transport-config", runtime_config)
                observations.append(f"closure:{runtime_config}")
                return original_closure(*args, **kwargs)

            def observed_receipt(*args: object, **kwargs: object) -> object:
                runtime_config = os.environ["AUTO_G16_RUNTIME_CONFIG"]
                self.assertNotIn("caller-transport-config", runtime_config)
                observations.append(f"receipt:{runtime_config}")
                return original_receipt(*args, **kwargs)

            module.validate_successor_closure = observed_closure
            module.validate_handshake_authority_binding = observed_receipt
            return module

        with self.caller_runtime_environment(caller_marker):
            with mock.patch.object(
                CONTRACT,
                "_load_transport_owner",
                observed_loader,
            ):
                self.owner().seal(self.fixture.evidence())
            self.assertIn(
                "caller-transport-config",
                os.environ["AUTO_G16_RUNTIME_CONFIG"],
            )
        self.assertEqual(
            {item.split(":", 1)[0] for item in observations},
            {"closure", "receipt"},
        )

    def test_owner_graph_exception_restores_environment_and_module_cache_exactly(self) -> None:
        caller_marker = str(self.root / "caller-exception-config")
        cache_name = "runtime_config"
        unrelated_name = "_auto_g16_protected_submit_unrelated_placeholder"
        missing = object()
        previous_cache = sys.modules.get(cache_name, missing)
        previous_unrelated = sys.modules.get(unrelated_name, missing)
        caller_cache = types.ModuleType(cache_name)
        unrelated_cache = types.ModuleType(unrelated_name)
        sys.modules[cache_name] = caller_cache
        sys.modules[unrelated_name] = unrelated_cache
        real_graph = CONTRACT._skill_owner_graph

        @contextlib.contextmanager
        def failing_graph() -> object:
            with real_graph() as modules:
                resource_owner = modules["resource_efficiency"]
                original = resource_owner.validate_ledger

                def fail_delayed_replay(*_args: object, **_kwargs: object) -> object:
                    self.assertNotIn(
                        "caller-exception-config",
                        os.environ["AUTO_G16_RUNTIME_CONFIG"],
                    )
                    raise RuntimeError("placeholder delayed replay failure")

                resource_owner.validate_ledger = fail_delayed_replay
                try:
                    yield modules
                finally:
                    resource_owner.validate_ledger = original

        try:
            with self.caller_runtime_environment(caller_marker):
                with mock.patch.object(
                    CONTRACT,
                    "_skill_owner_graph",
                    failing_graph,
                ):
                    with self.assertRaisesRegex(
                        CONTRACT.ProtectedSubmitError,
                        "execution/resource owner rejected",
                    ):
                        self.owner().seal(self.fixture.evidence())
                self.assertIs(sys.modules[cache_name], caller_cache)
                self.assertIs(sys.modules[unrelated_name], unrelated_cache)
                self.assertIn(
                    "caller-exception-config",
                    os.environ["AUTO_G16_RUNTIME_CONFIG"],
                )
        finally:
            sys.modules.pop(cache_name, None)
            if previous_cache is not missing:
                sys.modules[cache_name] = previous_cache
            sys.modules.pop(unrelated_name, None)
            if previous_unrelated is not missing:
                sys.modules[unrelated_name] = previous_unrelated

    def test_concurrent_replay_restores_caller_environment_and_import_order(self) -> None:
        caller_marker = str(self.root / "caller-concurrent-config")
        cache_name = "runtime_config"
        missing = object()
        previous_cache = sys.modules.get(cache_name, missing)
        caller_cache = types.ModuleType(cache_name)
        sys.modules[cache_name] = caller_cache
        owner = self.owner()
        barrier = threading.Barrier(4)

        def seal(_: int) -> str:
            barrier.wait()
            return owner.seal(
                self.fixture.evidence()
            ).bundle_payload_sha256

        try:
            with self.caller_runtime_environment(caller_marker):
                with ThreadPoolExecutor(max_workers=4) as pool:
                    results = list(pool.map(seal, range(4)))
                self.assertEqual(len(set(results)), 1)
                self.assertIs(sys.modules[cache_name], caller_cache)
                self.assertIn(
                    "caller-concurrent-config",
                    os.environ["AUTO_G16_RUNTIME_CONFIG"],
                )
        finally:
            sys.modules.pop(cache_name, None)
            if previous_cache is not missing:
                sys.modules[cache_name] = previous_cache

    def test_reservation_wraps_only_replay_not_state_consumption_environment(self) -> None:
        caller_marker = str(self.root / "caller-reservation-config")
        owner = self.owner()
        original = (
            owner._state_owner.consume_after_replay_at_trusted_now
        )
        observations: list[str] = []

        def observed_consumption(intent: object, replay: object) -> object:
            observations.append(os.environ["AUTO_G16_RUNTIME_CONFIG"])

            def observed_replay(snapshot: object, trusted_now: object) -> str:
                self.assertIn(
                    "caller-reservation-config",
                    os.environ["AUTO_G16_RUNTIME_CONFIG"],
                )
                result = replay(snapshot, trusted_now)
                self.assertIn(
                    "caller-reservation-config",
                    os.environ["AUTO_G16_RUNTIME_CONFIG"],
                )
                return result

            result = original(intent, observed_replay)
            observations.append(os.environ["AUTO_G16_RUNTIME_CONFIG"])
            return result

        owner._state_owner.consume_after_replay_at_trusted_now = (
            observed_consumption
        )
        with self.caller_runtime_environment(caller_marker):
            owner.reserve_once(self.fixture.evidence())
        self.assertEqual(len(observations), 2)
        self.assertTrue(
            all("caller-reservation-config" in value for value in observations)
        )

    def test_missing_unknown_or_mismatched_predecessor_stops_before_reservation(self) -> None:
        changed_gate = copy.deepcopy(self.fixture.gate)
        changed_gate["execution_scope"]["project"] = "otherjob"
        changed_gate["gate_sha256"] = BATCH.digest_value(
            {key: value for key, value in changed_gate.items() if key != "gate_sha256"}
        )
        changed_transport = self.fixture.transport_artifacts()
        changed_transport["handshake_receipt"] = {}
        cases = (
            replace(
                self.fixture.evidence(),
                scheduler_snapshot_artifact=b"{}\n",
            ),
            replace(self.fixture.evidence(), resource_gate=changed_gate),
            replace(
                self.fixture.evidence(),
                transport_artifacts=changed_transport,
            ),
            replace(self.fixture.evidence(), project="otherjob"),
        )
        for case in cases:
            with self.subTest(case=case), self.assertRaises(Exception):
                self.owner().reserve_once(case)
            self.assertFalse(self.state_root.exists())

    def test_bounded_custom_helper_and_owner_reject_same_topology_mutations(self) -> None:
        document = self.owner().seal(self.fixture.evidence()).document()
        schema_path = (
            ROOT / "contracts/execution/protected-submit-bundle.schema.json"
        )
        cases: list[tuple[str, dict]] = []

        def at_path(value: object, path: tuple[object, ...]) -> object:
            current = value
            for part in path:
                current = current[part]  # type: ignore[index]
            return current

        def reseal(candidate: dict) -> dict:
            if "bundle_payload_sha256" not in candidate:
                return candidate
            return CONTRACT.finalize(candidate)

        def add_topology_mutations(
            value: object,
            path: tuple[object, ...] = (),
        ) -> None:
            if isinstance(value, dict):
                extra = copy.deepcopy(document)
                target = at_path(extra, path)
                target["unexpected"] = True  # type: ignore[index]
                cases.append((f"{path}.extra", reseal(extra)))
                for key, child in value.items():
                    missing = copy.deepcopy(document)
                    missing_target = at_path(missing, path)
                    del missing_target[key]  # type: ignore[index]
                    cases.append((f"{path}.missing.{key}", reseal(missing)))
                    add_topology_mutations(child, path + (key,))
                return
            wrong_type = copy.deepcopy(document)
            parent = at_path(wrong_type, path[:-1])
            original = at_path(wrong_type, path)
            if isinstance(original, bool):
                replacement: object = not original
            elif isinstance(original, int):
                replacement = "not-an-integer"
            elif isinstance(original, str):
                replacement = []
            elif isinstance(original, list):
                replacement = list(reversed(original))
            else:
                replacement = {"wrong": "type"}
            parent[path[-1]] = replacement  # type: ignore[index]
            if path == ("bundle_payload_sha256",):
                cases.append((f"{path}.wrong-type", wrong_type))
            else:
                cases.append((f"{path}.wrong-type", reseal(wrong_type)))

        add_topology_mutations(document)

        permuted = copy.deepcopy(document)
        permuted["operation_order"] = [
            "stage_exact_bundle",
            "reserve_once",
            "submit_once",
        ]
        cases.append(("operation-order", CONTRACT.finalize(permuted)))
        old_approval = copy.deepcopy(document)
        old_approval["approvals"]["live_submission_approval"][
            "schema"
        ] = "auto-g16-live-submission-approval/8"
        cases.append(("historical-live-approval", CONTRACT.finalize(old_approval)))
        bad_task = copy.deepcopy(document)
        bad_task["identity"]["scientific_task_id"] = "task"
        cases.append(("malformed-task", CONTRACT.finalize(bad_task)))
        boolean_cores = copy.deepcopy(document)
        boolean_cores["resources"]["cores"] = True
        cases.append(("boolean-cores", CONTRACT.finalize(boolean_cores)))
        self.assertGreater(len(cases), 100)
        for label, candidate in cases:
            with self.subTest(candidate=label):
                schema_accepts = not CLOSURE_TESTS.schema_errors(
                    schema_path, candidate
                )
                try:
                    CONTRACT.validate_protected_submit_bundle(candidate)
                except CONTRACT.ProtectedSubmitError:
                    owner_accepts = False
                else:
                    owner_accepts = True
                # This is a bounded fast structural corpus, not a claim that
                # the helper implements Draft 2020-12 or that Schema and owner
                # validity have globally identical acceptance sets.
                self.assertFalse(schema_accepts)
                self.assertFalse(owner_accepts)

        def reverse_objects(value: object) -> object:
            if isinstance(value, dict):
                return {
                    key: reverse_objects(value[key])
                    for key in reversed(tuple(value))
                }
            if isinstance(value, list):
                return [reverse_objects(item) for item in value]
            return value

        reordered = reverse_objects(document)
        self.assertFalse(CLOSURE_TESTS.schema_errors(schema_path, reordered))
        self.assertEqual(
            CONTRACT.validate_protected_submit_bundle(reordered), document
        )

    def test_schema_is_closed_and_carries_no_free_execution_surface(self) -> None:
        schema = json.loads(
            (
                ROOT / "contracts/execution/protected-submit-bundle.schema.json"
            ).read_text(encoding="utf-8")
        )

        def inspect_node(value: object) -> None:
            if isinstance(value, dict):
                if value.get("type") == "object":
                    self.assertFalse(value.get("additionalProperties", True))
                    self.assertEqual(
                        set(value.get("required", [])),
                        set(value.get("properties", {})),
                    )
                    forbidden = {
                        "command",
                        "argv",
                        "shell",
                        "backend",
                        "host",
                        "path",
                        "config",
                        "callable",
                        "executable",
                    }
                    self.assertTrue(
                        forbidden.isdisjoint(value.get("properties", {}))
                    )
                for child in value.values():
                    inspect_node(child)
            elif isinstance(value, list):
                for child in value:
                    inspect_node(child)

        inspect_node(schema)
        source = (
            ROOT / "scripts/protected_submit_contract.py"
        ).read_text(encoding="utf-8")
        for forbidden in (
            "LegacyTransportAdapter",
            "legacy_adapter_integration",
            "invoke_reserved_once",
            "reserve_submission_attempt",
            "reserve_attempt(",
        ):
            self.assertNotIn(forbidden, source)

    def test_concurrent_consumption_allows_exactly_one_reservation(self) -> None:
        owner = self.owner()
        barrier = threading.Barrier(8)

        def reserve(_: int) -> str:
            barrier.wait()
            try:
                owner.reserve_once(self.fixture.evidence())
            except Exception:
                return "blocked"
            return "reserved"

        with ThreadPoolExecutor(max_workers=8) as pool:
            outcomes = list(pool.map(reserve, range(8)))
        self.assertEqual(outcomes.count("reserved"), 1)
        self.assertEqual(outcomes.count("blocked"), 7)
        snapshot = owner._state_owner.snapshot()
        self.assertEqual(
            snapshot["consumed_authorization_ids"],
            (
                owner.seal(self.fixture.evidence()).bundle_id,
            ),
        )

    def test_expiration_at_final_trusted_time_stops_without_consumption(self) -> None:
        owner = self.owner(NOW, EXPIRES_AT)
        with self.assertRaisesRegex(
            Exception, "active window|live-approval owner blocked"
        ):
            owner.reserve_once(self.fixture.evidence())
        snapshot = owner._state_owner.snapshot()
        self.assertEqual(snapshot["consumed_authorization_ids"], ())

    def test_post_reservation_exception_retains_uncertain_single_use_state(self) -> None:
        owner = self.owner()
        reserved = owner.reserve_once(self.fixture.evidence())
        reserved.assert_owner_sealed()
        self.assertEqual(reserved.submission_state, "submission_uncertain")
        self.assertFalse(reserved.automatic_retry)
        with self.assertRaisesRegex(RuntimeError, "placeholder later effect"):
            raise RuntimeError("placeholder later effect failed")
        snapshot = owner._state_owner.snapshot()
        self.assertEqual(
            snapshot["consumed_authorization_ids"],
            (reserved.bundle.bundle_id,),
        )
        with self.assertRaises(Exception):
            owner.reserve_once(self.fixture.evidence())
        self.assertFalse(
            any(
                name.startswith(("execute", "invoke", "submit", "stage"))
                for name in dir(reserved)
            )
        )

    def test_public_api_is_typed_narrow_and_has_no_caller_time_or_effect(self) -> None:
        self.assertEqual(
            tuple(inspect.signature(FACADE.seal_protected_submit_bundle).parameters),
            ("evidence",),
        )
        self.assertEqual(
            tuple(
                inspect.signature(
                    FACADE.reserve_protected_submit_bundle_once
                ).parameters
            ),
            ("evidence",),
        )
        source = (
            SKILL_SCRIPTS / "execution_facade.py"
        ).read_text(encoding="utf-8")
        protected_section = source[source.index("def _protected_submit_owner") :]
        self.assertNotIn("LegacyTransportAdapter", protected_section)
        self.assertNotIn("legacy_adapter_integration", protected_section)
        self.assertEqual(
            sorted(
                name
                for name in dir(FACADE)
                if "protected_submit" in name and not name.startswith("_")
            ),
            [
                "reserve_protected_submit_bundle_once",
                "seal_protected_submit_bundle",
            ],
        )
        seal_source = inspect.getsource(
            FACADE.seal_protected_submit_bundle
        )
        reserve_source = inspect.getsource(
            FACADE.reserve_protected_submit_bundle_once
        )
        for entry_source, owner_call in (
            (seal_source, "owner.seal(exact_evidence)"),
            (reserve_source, "owner.reserve_once(exact_evidence)"),
        ):
            self.assertIn("_exact_protected_submit_contract()", entry_source)
            self.assertIn("_evidence_for_exact_owner", entry_source)
            self.assertIn(owner_call, entry_source)
        for forbidden in ("now", "consumed_at", "effect", "backend", "host"):
            self.assertNotIn(
                forbidden,
                inspect.signature(
                    FACADE.reserve_protected_submit_bundle_once
                ).parameters,
            )

    def test_historical_hashes_freeze_and_stage_extraction_is_explicit(self) -> None:
        manifest = json.loads(
            (
                ROOT
                / "tests/fixtures/rtwin_pbs/protected_submit_legacy_hashes.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(
            manifest["base_commit"],
            "3f0dfaac805de83626b45288994132fdac0501db",
        )
        extraction = json.loads(
            (
                ROOT
                / "tests/fixtures/rtwin_pbs/"
                "protected_invocation_mechanical_extraction.json"
            ).read_text(encoding="utf-8")
        )
        for relative, expected in manifest["files"].items():
            with self.subTest(path=relative):
                actual = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
                if relative in extraction["files"]:
                    record = extraction["files"][relative]
                    self.assertEqual(record["before_sha256"], expected)
                    self.assertEqual(actual, record["after_sha256"])
                    self.assertFalse(record["legacy_semantics_changed"])
                else:
                    self.assertEqual(actual, expected)

    def test_facade_exact_owner_survives_shadow_cache_and_both_relocation_orders(self) -> None:
        package = skill_package.package_files(ROOT, "auto-g16-rtwin-pbs")
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            layouts = {
                "root": temporary_root / "root-layout",
                "package": temporary_root / "package-layout",
            }
            for installed in layouts.values():
                for destination_name, source in package.items():
                    destination = installed / destination_name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, destination)
            shadow = temporary_root / "caller-shadow"
            shadow.mkdir()
            (shadow / "protected_submit_contract.py").write_text(
                "raise AssertionError('caller-path shadow was imported')\n",
                encoding="utf-8",
            )
            script = (
                "import importlib.util, sys, types\n"
                "from pathlib import Path\n"
                f"root_scripts=Path({str(layouts['root'] / 'scripts')!r})\n"
                f"package_scripts=Path({str(layouts['package'] / 'scripts')!r})\n"
                f"shadow=Path({str(shadow)!r})\n"
                "sys.path[:0]=[str(shadow),str(root_scripts),str(package_scripts)]\n"
                "unrelated=types.ModuleType('unrelated_owner_cache')\n"
                "sys.modules['unrelated_owner_cache']=unrelated\n"
                "def load(name,path):\n"
                " spec=importlib.util.spec_from_file_location(name,path)\n"
                " assert spec and spec.loader\n"
                " module=importlib.util.module_from_spec(spec)\n"
                " sys.modules[name]=module\n"
                " spec.loader.exec_module(module)\n"
                " return module\n"
                "def load_facade(name,directory):\n"
                " return load(name,directory/'execution_facade.py')\n"
                "root_cached=load('protected_submit_contract',"
                "root_scripts/'protected_submit_contract.py')\n"
                "package_facade=load_facade('package_execution_facade',"
                "package_scripts)\n"
                "owner=package_facade._protected_submit_owner()\n"
                "assert Path(owner.__class__.__init__.__code__.co_filename).resolve()=="
                "(package_scripts/'protected_submit_contract.py').resolve()\n"
                "assert sys.modules['protected_submit_contract'] is root_cached\n"
                "package_cached=load('protected_submit_contract',"
                "package_scripts/'protected_submit_contract.py')\n"
                "def evidence(module):\n"
                " return module.ProtectedSubmitEvidence("
                "input_path=Path('input.gjf'),"
                "input_approval_path=Path('input-approval.json'),"
                "live_approval_path=Path('live-approval.json'),"
                "execution_ledger={},resource_policy={},resource_gate={},"
                "scheduler_snapshot={},scheduler_snapshot_artifact=b'{}',"
                "project='safejob',scientific_task_id='scientific-task-'+'a'*64,"
                "idempotency_key='placeholder',"
                "estimated_core_hours_evidence={},work_kind='minimum',"
                "transport_artifacts={})\n"
                "package_evidence=evidence(package_cached)\n"
                "root_evidence=evidence(root_cached)\n"
                "with package_facade._exact_protected_submit_contract() as exact:\n"
                " rebound=package_facade._evidence_for_exact_owner("
                "exact,package_evidence)\n"
                " assert isinstance(rebound,exact.ProtectedSubmitEvidence)\n"
                " try:\n"
                "  package_facade._evidence_for_exact_owner(exact,root_evidence)\n"
                " except TypeError:\n"
                "  pass\n"
                " else:\n"
                "  raise AssertionError('cross-origin evidence was accepted')\n"
                "root_facade=load_facade('root_execution_facade',root_scripts)\n"
                "owner=root_facade._protected_submit_owner()\n"
                "assert Path(owner.__class__.__init__.__code__.co_filename).resolve()=="
                "(root_scripts/'protected_submit_contract.py').resolve()\n"
                "assert sys.modules['protected_submit_contract'] is package_cached\n"
                "sys.modules.pop('protected_submit_contract')\n"
                "owner=package_facade._protected_submit_owner()\n"
                "assert Path(owner.__class__.__init__.__code__.co_filename).resolve()=="
                "(package_scripts/'protected_submit_contract.py').resolve()\n"
                "assert 'protected_submit_contract' not in sys.modules\n"
                "fake=types.ModuleType('protected_submit_contract')\n"
                "fake.__file__=str(shadow/'protected_submit_contract.py')\n"
                "sys.modules['protected_submit_contract']=fake\n"
                "owner=package_facade._protected_submit_owner()\n"
                "assert Path(owner.__class__.__init__.__code__.co_filename).resolve()=="
                "(package_scripts/'protected_submit_contract.py').resolve()\n"
                "assert sys.modules['protected_submit_contract'] is fake\n"
                "assert sys.modules['unrelated_owner_cache'] is unrelated\n"
            )
            completed = subprocess.run(
                [sys.executable, "-c", script],
                cwd=temporary_root,
                env={"PATH": os.environ.get("PATH", "")},
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            self.assertEqual(
                completed.returncode,
                0,
                completed.stdout + completed.stderr,
            )

    def test_package_and_source_relocation_preserve_owner_and_schema(self) -> None:
        package = skill_package.package_files(ROOT, "auto-g16-rtwin-pbs")
        self.assertIn(Path("scripts/protected_submit_contract.py"), package)
        self.assertIn(
            Path("contracts/execution/protected-submit-bundle.schema.json"),
            package,
        )
        document = self.owner().seal(self.fixture.evidence()).document()
        evidence = self.fixture.evidence()
        portable_evidence = {
            "input_path": str(evidence.input_path),
            "input_approval_path": str(evidence.input_approval_path),
            "live_approval_path": str(evidence.live_approval_path),
            "execution_ledger": evidence.execution_ledger,
            "resource_policy": evidence.resource_policy,
            "resource_gate": evidence.resource_gate,
            "scheduler_snapshot": evidence.scheduler_snapshot,
            "scheduler_snapshot_artifact_hex": (
                evidence.scheduler_snapshot_artifact.hex()
            ),
            "project": evidence.project,
            "scientific_task_id": evidence.scientific_task_id,
            "idempotency_key": evidence.idempotency_key,
            "estimated_core_hours_evidence": (
                evidence.estimated_core_hours_evidence
            ),
            "work_kind": evidence.work_kind,
            "transport_artifacts": evidence.transport_artifacts,
        }
        with tempfile.TemporaryDirectory() as temporary:
            installed = Path(temporary) / "auto-g16-rtwin-pbs"
            for destination_name, source in package.items():
                destination = installed / destination_name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
            document_path = Path(temporary) / "bundle.json"
            document_path.write_text(
                json.dumps(document, sort_keys=True) + "\n", encoding="utf-8"
            )
            evidence_path = Path(temporary) / "evidence.json"
            evidence_path.write_text(
                json.dumps(portable_evidence, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            script = (
                "import json\n"
                "from datetime import datetime, timezone\n"
                "from pathlib import Path\n"
                "import execution_facade, protected_submit_contract as c\n"
                f"d=json.loads(Path({str(document_path)!r}).read_text())\n"
                f"raw=json.loads(Path({str(evidence_path)!r}).read_text())\n"
                "raw['input_path']=Path(raw['input_path'])\n"
                "raw['input_approval_path']=Path(raw['input_approval_path'])\n"
                "raw['live_approval_path']=Path(raw['live_approval_path'])\n"
                "raw['scheduler_snapshot_artifact']=bytes.fromhex("
                "raw.pop('scheduler_snapshot_artifact_hex'))\n"
                "e=c.ProtectedSubmitEvidence(**raw)\n"
                "clock=lambda: datetime(2030,1,1,12,2,tzinfo=timezone.utc)\n"
                f"owner=c.ProtectedSubmitContractOwner._for_testing_with_clock("
                f"Path({temporary!r})/'state',clock,_test_token=c._TEST_OWNER_TOKEN)\n"
                "assert c.validate_protected_submit_bundle(d)==d\n"
                "assert owner.seal(e).document()==d\n"
                "facade_owner=execution_facade._protected_submit_owner()\n"
                "expected=Path(execution_facade.__file__).resolve().with_name("
                "'protected_submit_contract.py')\n"
                "assert Path(facade_owner.__class__.__init__.__code__.co_filename)"
                ".resolve()==expected\n"
                "assert tuple(__import__('inspect').signature("
                "execution_facade.seal_protected_submit_bundle).parameters)==('evidence',)\n"
            )
            environment = {
                "PATH": os.environ.get("PATH", ""),
                "PYTHONPATH": str(installed / "scripts"),
                "AUTO_G16_RUNTIME_CONFIG": str(
                    Path(temporary) / "placeholder-config-does-not-exist.json"
                ),
            }
            completed = subprocess.run(
                [sys.executable, "-c", script],
                cwd=installed,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            self.assertEqual(
                completed.returncode,
                0,
                completed.stdout + completed.stderr,
            )


if __name__ == "__main__":
    unittest.main()
