#!/usr/bin/env python3
"""Focused offline tests for the unique job/runtime coordinator."""

from __future__ import annotations

import copy
import hashlib
import json
import pickle
import sys
import tempfile
import types
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "skills" / "auto-g16-rtwin-pbs" / "scripts"))

from tests.test_protected_runtime_state_contract import RuntimeStateFixture  # noqa: E402,F401
from tests import test_protected_owner_consumer_contract as _CONSUMER_SUPPORT  # noqa: E402,F401
import protected_owner_consumer_contract as _CONSUMER  # noqa: E402,F401
import protected_production_ingress_contract as _INGRESS  # noqa: E402,F401
import protected_job_runtime_coordinator as COORDINATOR  # noqa: E402
import legacy_root_authority_contract as ROOT_AUTHORITY  # noqa: E402
import resource_efficiency as RESOURCE  # noqa: E402
import resource_effect_time_replay_owner as RESOURCE_REPLAY  # noqa: E402
from tests import test_live_approval_effect_time_replay as LIVE_SUPPORT  # noqa: E402


class ProtectedJobRuntimeCoordinatorTests(unittest.TestCase):
    def reseal(self, document: dict) -> None:
        projection = copy.deepcopy(document)
        projection["coordinator_id"] = ""
        projection["payload_sha256"] = ""
        document["payload_sha256"] = COORDINATOR.digest(projection)
        document["coordinator_id"] = (
            "protected-job-runtime-coordinator-"
            + COORDINATOR.digest(
                {
                    "schema": "auto-g16-protected-job-runtime-coordinator-id/1",
                    "identity": document["identity"],
                    "predecessors": document["predecessors"],
                    "payload_sha256": document["payload_sha256"],
                }
            )
        )

    def valid_projection(self) -> dict:
        identity = {
            "project": "safejob",
            "input_sha256": "5" * 64,
            "attempt_id": "qsub-attempt-" + "1" * 64,
            "scientific_task_id": "scientific-task-" + "2" * 64,
            "idempotency_key_sha256": "3" * 64,
        }
        predecessors = {
            "production_ingress_contract_id": "ingress-1",
            "runtime_contract_id": "runtime-1",
            "runtime_uncertain_receipt_id": "uncertain-1",
            "live_replay_capability_id": "live-1",
            "resource_replay_capability_id": "resource-1",
            "resource_reservation_capability_id": "reservation-1",
            "legacy_root_receipt_payload_sha256": "4" * 64,
        }
        document = {
            "schema": COORDINATOR.SCHEMA,
            "owner": COORDINATOR.OWNER,
            "coordinator_id": "",
            "identity": identity,
            "predecessors": predecessors,
            "owner_map": copy.deepcopy(COORDINATOR.OWNER_MAP),
            "state_machine": copy.deepcopy(COORDINATOR.STATE_MACHINE),
            "recovery_order": list(COORDINATOR.RECOVERY_ORDER),
            "factory_port": {
                "schema": COORDINATOR.FACTORY_PORT_SCHEMA,
                "input_types": [
                    "ProtectedLegacyEffectPlanFactoryPort",
                    "SealedProtectedRuntimeStateReceipt",
                    "CompletedPreQsubLiveApprovalReplay",
                    "ClaimedResourceEffectTimeReplay",
                    "ConsumedLegacyWorkspaceDescriptorLease",
                ],
                "output_type": "SealedProtectedCoordinatorFactoryPort",
                "future_consumer_output_type": "_LegacyEffectPlan",
                "single_claim": True,
                "current_legacy_factory_accepts_port": False,
                "factory_invoked": False,
                "effect_plan_created": False,
                "raw_effect_owner_created": False,
            },
            "authority": {
                "exact_in_process_capabilities_required": True,
                "canonical_module_class_source_required": True,
                "portable_projection_authorizes": False,
                "raw_json_authorizes": False,
                "raw_hash_authorizes": False,
                "projection_fields_authorize": False,
                "production_factory_consumer_implemented": False,
                "legacy_adapter_connected": False,
                "runner_calls": 0,
                "transport_calls": 0,
                "qsub_calls": 0,
                "remote_reads": 0,
                "external_effects": 0,
            },
            "payload_sha256": "",
        }
        self.reseal(document)
        return document

    def test_owner_map_state_machine_and_recovery_are_closed(self) -> None:
        document = self.valid_projection()
        self.assertEqual(
            COORDINATOR.validate_protected_job_runtime_coordinator(document),
            document,
        )
        self.assertEqual(
            document["owner_map"]["runtime_state_and_journal"],
            "auto-g16-protected-runtime-state-owner",
        )
        self.assertFalse(document["state_machine"]["automatic_retry"])
        self.assertFalse(document["state_machine"]["second_qsub"])
        self.assertEqual(
            document["recovery_order"][-1],
            "rebuild_legacy_job_state_as_derived_projection_last",
        )

    def test_ledger_owner_is_exact_real_package_4_predecessor(self) -> None:
        owners = (
            COORDINATOR.COORDINATOR_LEDGER_OWNER,
            RESOURCE.RESERVATION_CAPABILITY_OWNER,
            RESOURCE_REPLAY.RESOURCE_EFFECT_REPLAY_CAPABILITY_OWNER,
        )
        for owner in owners:
            self.assertIs(type(owner), str)
            self.assertEqual(owner, "auto-g16-package-4")
        self.assertEqual(
            COORDINATOR.OWNER_MAP["execution_batch_ledger"],
            COORDINATOR.COORDINATOR_LEDGER_OWNER,
        )
        for replacement in (
            "auto-g16-resource-efficiency-owner",
            "foreign-package-4-owner",
        ):
            with self.subTest(portable_owner=replacement):
                document = self.valid_projection()
                document["owner_map"]["execution_batch_ledger"] = replacement
                self.reseal(document)
                with self.assertRaises(
                    COORDINATOR.ProtectedJobRuntimeCoordinatorError
                ):
                    COORDINATOR.validate_protected_job_runtime_coordinator(
                        document
                    )
        for target, attribute, replacement in (
            (
                RESOURCE,
                "RESERVATION_CAPABILITY_OWNER",
                "auto-g16-resource-efficiency-owner",
            ),
            (
                RESOURCE_REPLAY,
                "RESOURCE_EFFECT_REPLAY_CAPABILITY_OWNER",
                "foreign-package-4-owner",
            ),
        ):
            with self.subTest(
                predecessor=f"{target.__name__}.{attribute}"
            ), mock.patch.object(target, attribute, replacement):
                with self.assertRaisesRegex(
                    COORDINATOR.ProtectedJobRuntimeCoordinatorError,
                    "owner",
                ):
                    COORDINATOR.validate_protected_job_runtime_coordinator(
                        self.valid_projection()
                    )

    def test_projection_and_semantic_splices_never_issue_authority(self) -> None:
        for section, field, replacement in (
            ("authority", "portable_projection_authorizes", True),
            ("authority", "qsub_calls", False),
            ("factory_port", "factory_invoked", True),
            ("state_machine", "automatic_retry", True),
        ):
            with self.subTest(section=section, field=field):
                document = self.valid_projection()
                document[section][field] = replacement
                self.reseal(document)
                with self.assertRaises(COORDINATOR.ProtectedJobRuntimeCoordinatorError):
                    COORDINATOR.validate_protected_job_runtime_coordinator(document)

    def test_all_capabilities_are_owner_issued_noncopyable_surfaces(self) -> None:
        for issued_type in (
            COORDINATOR.SealedProtectedJobRuntimeCoordinator,
            COORDINATOR.SealedProtectedCoordinatorFactoryPort,
            COORDINATOR.ClaimedProtectedCoordinatorFactoryPort,
        ):
            with self.subTest(issued_type=issued_type.__name__):
                with self.assertRaises(TypeError):
                    issued_type()
        owner = COORDINATOR.ProtectedJobRuntimeCoordinatorOwner.production()
        for operation in (copy.copy, copy.deepcopy, pickle.dumps):
            with self.subTest(operation=operation.__name__):
                with self.assertRaises(Exception):
                    operation(owner)

    def test_forged_inputs_fail_before_any_runtime_transition(self) -> None:
        owner = COORDINATOR.ProtectedJobRuntimeCoordinatorOwner.production()
        with self.assertRaisesRegex(
            COORDINATOR.ProtectedJobRuntimeCoordinatorError,
            "exact production ingress",
        ):
            owner.seal_once(
                production_ingress={},
                live_replay={},
                resource_replay={},
                legacy_root={},
            )

    def test_canonical_module_cache_replacement_fails_closed(self) -> None:
        original = sys.modules[COORDINATOR.MODULE_NAME]
        foreign = types.ModuleType(COORDINATOR.MODULE_NAME)
        foreign.__file__ = str(Path(COORDINATOR.__file__).resolve())
        sys.modules[COORDINATOR.MODULE_NAME] = foreign
        try:
            with self.assertRaisesRegex(
                COORDINATOR.ProtectedJobRuntimeCoordinatorError,
                "canonical coordinator module identity",
            ):
                COORDINATOR.ProtectedJobRuntimeCoordinatorOwner.production()
        finally:
            sys.modules[COORDINATOR.MODULE_NAME] = original

    def test_exact_integrated_owner_chain_issues_and_claims_effect_free_port(
        self,
    ) -> None:
        case = LIVE_SUPPORT.LiveApprovalEffectTimeReplayTests("runTest")
        case.setUp()
        try:
            live = case.capability()
            ingress = case.ingress
            protected = (
                case.fixture.local.lifecycle.invocation.local.protected
            )
            # This is the package-4 authority ledger. The materialized copy is
            # intentionally not mutated and remains a frozen runtime artifact.
            ledger_path = protected.ledger_path
            task = RESOURCE.validate_ledger(
                RESOURCE.load(ledger_path)
            )["tasks"][0]
            approval = json.loads(case.approval_path.read_text())
            execution = approval["scope"]["execution"]

            def artifact(name: str, document: dict) -> tuple[Path, str, int]:
                path = case.root / name
                path.write_text(
                    json.dumps(document, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                raw = path.read_bytes()
                return path, hashlib.sha256(raw).hexdigest(), len(raw)

            policy_path, _, _ = artifact(
                "coordinator-policy.json", protected.policy
            )
            gate_path, _, _ = artifact(
                "coordinator-gate.json", protected.gate
            )
            scheduler_path, scheduler_sha256, scheduler_size = artifact(
                "coordinator-scheduler.json", protected.scheduler
            )
            reservation = RESOURCE.reserve_attempt_capability(
                ledger_path,
                task["scientific_task_id"],
                identity=task["identity"],
                idempotency_key=execution["idempotency_key"],
                project="safejob",
                remote_workdir="/home/user100/SDL/safejob",
                input_sha256=approval["scope"]["input_sha256"],
                live_approval_id=approval["approval_id"],
                live_approval_sha256=hashlib.sha256(
                    case.approval_path.read_bytes()
                ).hexdigest(),
                estimated_core_hours_evidence=execution[
                    "estimated_core_hours_evidence"
                ],
                reserved_at="2030-01-01T12:02:30Z",
                audit_reason="offline exact coordinator fixture",
                policy=protected.policy,
                gate=protected.gate,
                scheduler_snapshot=protected.scheduler,
                scheduler_artifact_sha256=scheduler_sha256,
                scheduler_artifact_size=scheduler_size,
            )
            with mock.patch.object(
                RESOURCE_REPLAY,
                "_effect_wall_now",
                return_value=LIVE_SUPPORT.ISSUED,
            ), mock.patch.object(
                RESOURCE_REPLAY,
                "_effect_monotonic_ns",
                return_value=1_000_000_000,
            ):
                resource = (
                    RESOURCE_REPLAY
                    .issue_resource_effect_time_replay_capability(
                        reservation_capability=reservation,
                        ledger_path=ledger_path,
                        policy_path=policy_path,
                        gate_path=gate_path,
                        scheduler_path=scheduler_path,
                    )
                )

            root_owner = (
                ROOT_AUTHORITY.LegacyRootAuthorityContractOwner._for_testing(
                    clock=lambda: LIVE_SUPPORT.ISSUED,
                    nonce_source=lambda: "b" * 32,
                    _test_token=ROOT_AUTHORITY._TEST_TOKEN,
                )
            )
            root_snapshot = root_owner._root_snapshot_for_testing(
                ["home-device", "user100-directory", "sdl-directory"],
                _test_token=ROOT_AUTHORITY._TEST_TOKEN,
            )
            stable = root_owner.issue_stable_evidence(root_snapshot)
            authorization = root_owner.build_authorization(
                authorization_id="legacy-root-authorization-coordinator",
                profile_id="legacy-primary",
                profile_payload_sha256="a" * 64,
                stable_evidence=stable,
                protected_production_ingress=ingress,
                approved_at="2030-01-01T12:01:00.000000Z",
                not_before="2030-01-01T12:02:00.000000Z",
                expires_at="2030-01-01T12:10:00.000000Z",
                maximum_receipt_age_seconds=60,
            )
            observation = root_owner._workspace_observation_for_testing(
                root=root_snapshot,
                project="safejob",
                _test_token=ROOT_AUTHORITY._TEST_TOKEN,
            )
            root = root_owner.issue_fresh_capability_once(
                stable_evidence=stable,
                authorization=authorization,
                protected_production_ingress=ingress,
                observation=observation,
            )

            coordinator = (
                COORDINATOR.ProtectedJobRuntimeCoordinatorOwner.production()
                .seal_once(
                    production_ingress=ingress,
                    live_replay=live,
                    resource_replay=resource,
                    legacy_root=root,
                )
            )
            port = coordinator.issue_factory_port_once()
            with mock.patch.object(
                RESOURCE_REPLAY,
                "_effect_wall_now",
                return_value=LIVE_SUPPORT.ISSUED + timedelta(seconds=1),
            ), mock.patch.object(
                RESOURCE_REPLAY,
                "_effect_monotonic_ns",
                return_value=2_000_000_000,
            ):
                claim = port.claim_once()
            claim.assert_owner_sealed()
            self.assertEqual(
                claim.uncertain_receipt.document()["state"],
                "effect_started_outcome_uncertain",
            )
            self.assertFalse(claim.root_lease.remote_effect_authorized)
            self.assertFalse(
                claim.resource_replay.exact_scope()["authorizes_qsub"]
            )
            self.assertEqual(claim.live_replay.document()["qsub_calls"], 0)
            with self.assertRaisesRegex(
                COORDINATOR.ProtectedJobRuntimeCoordinatorError,
                "already claimed",
            ):
                port.claim_once()
        finally:
            case.tearDown()

    def test_contract_mentions_no_effect_consumer_and_no_pr4_pr6_wiring(self) -> None:
        document = self.valid_projection()
        self.assertFalse(
            document["factory_port"]["current_legacy_factory_accepts_port"]
        )
        self.assertFalse(document["authority"]["production_factory_consumer_implemented"])
        self.assertFalse(document["authority"]["legacy_adapter_connected"])
        self.assertEqual(document["authority"]["external_effects"], 0)


if __name__ == "__main__":
    unittest.main()
