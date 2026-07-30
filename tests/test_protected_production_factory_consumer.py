#!/usr/bin/env python3
"""Focused offline tests for the unique production factory consumer."""

from __future__ import annotations

import ast
import copy
import hashlib
import json
import pickle
import sys
import threading
import types
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(
    0,
    str(ROOT / "skills" / "auto-g16-rtwin-pbs" / "scripts"),
)

from tests.test_protected_runtime_state_contract import RuntimeStateFixture  # noqa: E402,F401
from tests import test_protected_owner_consumer_contract as _CONSUMER_SUPPORT  # noqa: E402,F401
import protected_owner_consumer_contract as _CONSUMER  # noqa: E402,F401
import protected_production_ingress_contract as _INGRESS  # noqa: E402,F401
import protected_job_runtime_coordinator as COORDINATOR  # noqa: E402
import legacy_root_authority_contract as ROOT_AUTHORITY  # noqa: E402
import protected_production_factory_consumer as CONSUMER  # noqa: E402
import legacy_rtwin_pbs as LEGACY  # noqa: E402
import resource_efficiency as RESOURCE  # noqa: E402
import resource_effect_time_replay_owner as RESOURCE_REPLAY  # noqa: E402
from tests import test_live_approval_effect_time_replay as LIVE_SUPPORT  # noqa: E402


class ProtectedProductionFactoryConsumerTests(unittest.TestCase):
    def registry_identity_snapshot(self) -> tuple:
        with CONSUMER._RESULT_REGISTRY_LOCK:
            return tuple(
                sorted(
                    (
                        id(result),
                        id(state),
                        id(state.result),
                        id(state.result_document_bytes),
                        state.result_document_sha256,
                        id(state.claim),
                        id(state.coordinator_port),
                        id(state.coordinator),
                        id(state.coordinator_document_bytes),
                        state.coordinator_document_sha256,
                    )
                    for result, state in CONSUMER._RESULT_REGISTRY.items()
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
        document = {
            "schema": CONSUMER.SCHEMA,
            "owner": CONSUMER.OWNER,
            "result_id": "",
            "identity": identity,
            "predecessors": {
                "coordinator_id": "coordinator-1",
                "production_ingress_contract_id": "ingress-1",
                "runtime_contract_id": "runtime-1",
                "runtime_uncertain_receipt_id": "uncertain-1",
                "runtime_uncertain_receipt_payload_sha256": "4" * 64,
                "live_replay_capability_id": "live-1",
                "live_replay_result_payload_sha256": "6" * 64,
                "resource_replay_capability_id": "resource-1",
                "resource_reservation_capability_id": "reservation-1",
                "legacy_root_receipt_payload_sha256": "7" * 64,
                "legacy_root_authorization_scope_sha256": "a" * 64,
                "legacy_root_descriptor_set_sha256": "8" * 64,
                "plan_inputs_sha256": "9" * 64,
            },
            "coordinator_claim_order": list(
                CONSUMER.COORDINATOR_CLAIM_ORDER
            ),
            "consumer_order": list(CONSUMER.CONSUMER_ORDER),
            "output": copy.deepcopy(CONSUMER.OUTPUT),
            "legacy_factory_binding": {
                "module": "legacy_rtwin_pbs",
                "factory": "_legacy_effect_plan_from_transaction",
                "effect_plan_type": "_LegacyEffectPlan",
                "raw_owner_factory": "_legacy_raw_effect_owner_from_plan",
                "raw_owner_type": "_LegacyRawEffectOwner",
                "legacy_source_sha256": (
                    CONSUMER._LEGACY_SOURCE_SNAPSHOT[1]
                ),
                "exact_identity_bound": True,
                "frozen_predecessor_bytes_modified": False,
                "factory_invoked": False,
            },
            "uncertain_boundary": copy.deepcopy(
                CONSUMER.UNCERTAIN_BOUNDARY
            ),
            "authority": copy.deepcopy(CONSUMER.AUTHORITY),
            "payload_sha256": "",
        }
        document["payload_sha256"] = CONSUMER._payload(document)
        document["result_id"] = CONSUMER._result_id(document)
        return document

    def make_port(
        self,
    ) -> COORDINATOR.SealedProtectedCoordinatorFactoryPort:
        case = LIVE_SUPPORT.LiveApprovalEffectTimeReplayTests("runTest")
        case.setUp()
        self.addCleanup(case.tearDown)
        live = case.capability()
        ingress = case.ingress
        protected = case.fixture.local.lifecycle.invocation.local.protected
        ledger_path = protected.ledger_path
        task = RESOURCE.validate_ledger(
            RESOURCE.load(ledger_path)
        )["tasks"][0]
        approval = json.loads(case.approval_path.read_text())
        execution = approval["scope"]["execution"]

        def artifact(
            name: str,
            document: dict,
        ) -> tuple[Path, str, int]:
            path = case.root / name
            path.write_text(
                json.dumps(document, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            raw = path.read_bytes()
            return path, hashlib.sha256(raw).hexdigest(), len(raw)

        policy_path, _, _ = artifact(
            "factory-consumer-policy.json",
            protected.policy,
        )
        gate_path, _, _ = artifact(
            "factory-consumer-gate.json",
            protected.gate,
        )
        scheduler_path, scheduler_sha256, scheduler_size = artifact(
            "factory-consumer-scheduler.json",
            protected.scheduler,
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
            audit_reason="offline exact production factory fixture",
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
                nonce_source=lambda: "c" * 32,
                _test_token=ROOT_AUTHORITY._TEST_TOKEN,
            )
        )
        root_snapshot = root_owner._root_snapshot_for_testing(
            ["home-device", "user100-directory", "sdl-directory"],
            _test_token=ROOT_AUTHORITY._TEST_TOKEN,
        )
        stable = root_owner.issue_stable_evidence(root_snapshot)
        authorization = root_owner.build_authorization(
            authorization_id="legacy-root-authorization-factory-consumer",
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
        return coordinator.issue_factory_port_once()

    def consume(
        self,
        port: COORDINATOR.SealedProtectedCoordinatorFactoryPort,
    ) -> CONSUMER.SealedProtectedProductionFactoryResult:
        with mock.patch.object(
            RESOURCE_REPLAY,
            "_effect_wall_now",
            return_value=LIVE_SUPPORT.ISSUED + timedelta(seconds=1),
        ), mock.patch.object(
            RESOURCE_REPLAY,
            "_effect_monotonic_ns",
            return_value=2_000_000_000,
        ):
            return CONSUMER.consume_protected_production_factory_once(port)

    def assert_no_legacy_factory_objects(
        self,
        before_plans: int,
        before_owners: int,
    ) -> None:
        self.assertEqual(len(LEGACY._LEGACY_EFFECT_PLAN_BINDINGS), before_plans)
        self.assertEqual(
            len(LEGACY._LEGACY_EFFECT_OWNER_BINDINGS),
            before_owners,
        )

    def test_projection_is_closed_and_non_authorizing(self) -> None:
        document = self.valid_projection()
        self.assertEqual(
            CONSUMER.validate_protected_production_factory_result(document),
            document,
        )
        self.assertFalse(
            document["authority"]["thirteen_field_projection_authorizes"]
        )
        self.assertFalse(document["output"]["legacy_effect_plan_created"])
        for section, field, replacement in (
            ("authority", "legacy_factory_calls", False),
            ("authority", "parallel_owner_created", True),
            ("output", "physical_effect_possible", True),
            ("legacy_factory_binding", "factory_invoked", True),
            ("uncertain_boundary", "second_qsub", True),
        ):
            with self.subTest(section=section, field=field):
                changed = copy.deepcopy(document)
                changed[section][field] = replacement
                changed["payload_sha256"] = CONSUMER._payload(changed)
                changed["result_id"] = CONSUMER._result_id(changed)
                with self.assertRaises(
                    CONSUMER.ProtectedProductionFactoryConsumerError
                ):
                    CONSUMER.validate_protected_production_factory_result(
                        changed
                    )

    def test_exact_chain_produces_only_owner_sealed_result(self) -> None:
        port = self.make_port()
        before_plans = len(LEGACY._LEGACY_EFFECT_PLAN_BINDINGS)
        before_owners = len(LEGACY._LEGACY_EFFECT_OWNER_BINDINGS)
        with mock.patch.object(
            LEGACY.LegacyTransportAdapter,
            "invoke_reserved_once",
        ) as adapter, mock.patch.object(
            LEGACY,
            "run",
        ) as runner, mock.patch.object(
            Path,
            "write_bytes",
        ) as write_bytes, mock.patch.object(
            Path,
            "write_text",
        ) as write_text:
            result = self.consume(port)
        result.assert_owner_sealed()
        claim = result.exact_owner_objects()
        self.assertIs(
            type(claim),
            COORDINATOR.ClaimedProtectedCoordinatorFactoryPort,
        )
        document = result.document()
        self.assertEqual(
            document["identity"]["project"],
            claim.legacy_plan_inputs.project,
        )
        self.assertEqual(
            document["predecessors"]["runtime_uncertain_receipt_id"],
            claim.uncertain_receipt.document()["receipt_id"],
        )
        self.assertFalse(claim.root_lease.remote_effect_authorized)
        self.assertFalse(
            claim.resource_replay.exact_scope()["authorizes_qsub"]
        )
        adapter.assert_not_called()
        runner.assert_not_called()
        write_bytes.assert_not_called()
        write_text.assert_not_called()
        self.assert_no_legacy_factory_objects(before_plans, before_owners)

    def test_missing_foreign_and_spliced_ports_stop_before_claim(self) -> None:
        before_plans = len(LEGACY._LEGACY_EFFECT_PLAN_BINDINGS)
        before_owners = len(LEGACY._LEGACY_EFFECT_OWNER_BINDINGS)
        registry = self.registry_identity_snapshot()
        for value in ({}, types.SimpleNamespace()):
            with self.subTest(value=type(value).__name__):
                with self.assertRaisesRegex(
                    CONSUMER.ProtectedProductionFactoryConsumerError,
                    "exact coordinator factory port",
                ):
                    CONSUMER.consume_protected_production_factory_once(value)
        port = self.make_port()
        object.__setattr__(port, "_document", b"{}")
        with self.assertRaises(Exception):
            CONSUMER.consume_protected_production_factory_once(port)
        self.assertFalse(port._claimed)
        self.assertEqual(self.registry_identity_snapshot(), registry)
        self.assert_no_legacy_factory_objects(before_plans, before_owners)

    def test_already_consumed_port_and_partial_claim_failure_are_terminal(
        self,
    ) -> None:
        before_plans = len(LEGACY._LEGACY_EFFECT_PLAN_BINDINGS)
        before_owners = len(LEGACY._LEGACY_EFFECT_OWNER_BINDINGS)
        port = self.make_port()
        self.consume(port)
        registry = self.registry_identity_snapshot()
        with self.assertRaises(Exception):
            CONSUMER.consume_protected_production_factory_once(port)
        self.assertTrue(port._claimed)
        self.assertEqual(self.registry_identity_snapshot(), registry)
        self.assert_no_legacy_factory_objects(before_plans, before_owners)

        failed = self.make_port()
        with mock.patch.object(
            RESOURCE_REPLAY,
            "_effect_wall_now",
            return_value=LIVE_SUPPORT.ISSUED + timedelta(seconds=1),
        ), mock.patch.object(
            RESOURCE_REPLAY,
            "_effect_monotonic_ns",
            return_value=2_000_000_000,
        ), mock.patch(
            "live_approval_effect_time_replay."
            "PreQsubLiveApprovalReplayCapability.replay_once",
            side_effect=RuntimeError("synthetic replay failure"),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "synthetic replay failure",
            ):
                CONSUMER.consume_protected_production_factory_once(failed)
        self.assertTrue(failed._claimed)
        with self.assertRaises(Exception):
            CONSUMER.consume_protected_production_factory_once(failed)
        self.assertEqual(self.registry_identity_snapshot(), registry)
        self.assert_no_legacy_factory_objects(before_plans, before_owners)

    def test_concurrent_consumers_produce_exactly_one_result(self) -> None:
        port = self.make_port()
        barrier = threading.Barrier(2)

        def consume(_index: int) -> object:
            barrier.wait()
            try:
                return CONSUMER.consume_protected_production_factory_once(
                    port
                )
            except Exception as exc:
                return exc

        with mock.patch.object(
            RESOURCE_REPLAY,
            "_effect_wall_now",
            return_value=LIVE_SUPPORT.ISSUED + timedelta(seconds=1),
        ), mock.patch.object(
            RESOURCE_REPLAY,
            "_effect_monotonic_ns",
            return_value=2_000_000_000,
        ), ThreadPoolExecutor(max_workers=2) as pool:
            values = list(pool.map(consume, range(2)))
        results = [
            value
            for value in values
            if type(value)
            is CONSUMER.SealedProtectedProductionFactoryResult
        ]
        failures = [value for value in values if isinstance(value, Exception)]
        self.assertEqual(len(results), 1)
        self.assertEqual(len(failures), 1)
        results[0].assert_owner_sealed()

    def test_result_is_owner_issued_noncopyable_and_nonserializable(
        self,
    ) -> None:
        with self.assertRaises(TypeError):
            CONSUMER.SealedProtectedProductionFactoryResult()
        result = self.consume(self.make_port())
        registry = self.registry_identity_snapshot()
        state = CONSUMER._RESULT_REGISTRY[result]
        for operation in (copy.copy, copy.deepcopy, pickle.dumps):
            with self.subTest(operation=operation.__name__):
                with self.assertRaises(Exception):
                    operation(result)
                self.assertEqual(
                    self.registry_identity_snapshot(),
                    registry,
                )
                self.assertTrue(state.coordinator_port._claimed)
                result.assert_owner_sealed()

    def test_module_factory_or_class_replacement_fails_before_claim(
        self,
    ) -> None:
        port = self.make_port()
        before_plans = len(LEGACY._LEGACY_EFFECT_PLAN_BINDINGS)
        before_owners = len(LEGACY._LEGACY_EFFECT_OWNER_BINDINGS)
        with mock.patch.object(
            LEGACY,
            "_legacy_effect_plan_from_transaction",
            mock.Mock(),
        ):
            with self.assertRaisesRegex(
                CONSUMER.ProtectedProductionFactoryConsumerError,
                "legacy class or factory identity",
            ):
                CONSUMER.consume_protected_production_factory_once(port)
        self.assertFalse(port._claimed)
        self.assert_no_legacy_factory_objects(before_plans, before_owners)

        original = sys.modules[CONSUMER.MODULE_NAME]
        foreign = types.ModuleType(CONSUMER.MODULE_NAME)
        foreign.__file__ = str(Path(CONSUMER.__file__).resolve())
        sys.modules[CONSUMER.MODULE_NAME] = foreign
        try:
            with self.assertRaisesRegex(
                CONSUMER.ProtectedProductionFactoryConsumerError,
                "canonical production factory consumer module identity",
            ):
                CONSUMER.consume_protected_production_factory_once(port)
        finally:
            sys.modules[CONSUMER.MODULE_NAME] = original
        self.assertFalse(port._claimed)

    def test_root_lease_authorization_scope_splice_invalidates_result(
        self,
    ) -> None:
        result = self.consume(self.make_port())
        claim = result.exact_owner_objects()
        original = claim.root_lease.authorization_scope_sha256
        object.__setattr__(
            claim.root_lease,
            "authorization_scope_sha256",
            "f" * 64,
        )
        try:
            with self.assertRaisesRegex(
                CONSUMER.ProtectedProductionFactoryConsumerError,
                "legacy root authorization scope",
            ):
                result.assert_owner_sealed()
        finally:
            object.__setattr__(
                claim.root_lease,
                "authorization_scope_sha256",
                original,
            )

    def test_rehashed_coordinator_id_replacement_is_not_owner_sealed(
        self,
    ) -> None:
        result = self.consume(self.make_port())
        state = CONSUMER._RESULT_REGISTRY[result]
        registry = self.registry_identity_snapshot()
        original = result._canonical_document
        changed = result.document()
        changed["predecessors"]["coordinator_id"] = (
            "protected-job-runtime-coordinator-" + "f" * 64
        )
        changed["payload_sha256"] = CONSUMER._payload(changed)
        changed["result_id"] = CONSUMER._result_id(changed)
        object.__setattr__(
            result,
            "_canonical_document",
            CONSUMER.canonical_bytes(changed),
        )
        try:
            with self.assertRaises(
                CONSUMER.ProtectedProductionFactoryConsumerError
            ):
                result.assert_owner_sealed()
            self.assertEqual(self.registry_identity_snapshot(), registry)
            self.assertIs(CONSUMER._RESULT_REGISTRY[result], state)
            self.assertTrue(state.coordinator_port._claimed)
        finally:
            object.__setattr__(result, "_canonical_document", original)
        result.assert_owner_sealed()

    def test_private_slot_replacement_and_foreign_shape_fail_closed(
        self,
    ) -> None:
        result = self.consume(self.make_port())
        state = CONSUMER._RESULT_REGISTRY[result]
        registry = self.registry_identity_snapshot()
        for name, replacement in (
            ("_canonical_document", b"{}"),
            ("_claim", object()),
            ("_seal", object()),
        ):
            with self.subTest(slot=name):
                original = getattr(result, name)
                object.__setattr__(result, name, replacement)
                try:
                    with self.assertRaises(
                        CONSUMER.ProtectedProductionFactoryConsumerError
                    ):
                        result.assert_owner_sealed()
                    self.assertEqual(
                        self.registry_identity_snapshot(),
                        registry,
                    )
                    self.assertIs(CONSUMER._RESULT_REGISTRY[result], state)
                    self.assertTrue(state.coordinator_port._claimed)
                finally:
                    object.__setattr__(result, name, original)
                result.assert_owner_sealed()

        foreign = object.__new__(
            CONSUMER.SealedProtectedProductionFactoryResult
        )
        for name in ("_canonical_document", "_claim", "_seal"):
            object.__setattr__(foreign, name, getattr(result, name))
        with self.assertRaisesRegex(
            CONSUMER.ProtectedProductionFactoryConsumerError,
            "owner-registered|seal differs",
        ):
            foreign.assert_owner_sealed()
        self.assertEqual(self.registry_identity_snapshot(), registry)
        self.assertNotIn(foreign, CONSUMER._RESULT_REGISTRY)
        self.assertTrue(state.coordinator_port._claimed)
        result.assert_owner_sealed()

    def test_exact_coordinator_port_object_and_document_are_registry_bound(
        self,
    ) -> None:
        result = self.consume(self.make_port())
        state = CONSUMER._RESULT_REGISTRY[result]
        registry = self.registry_identity_snapshot()
        changed_bytes = memoryview(
            state.coordinator_document_bytes
        ).tobytes()
        self.assertIsNot(changed_bytes, state.coordinator_document_bytes)
        for target, name, replacement in (
            (state.coordinator_port, "_coordinator", object()),
            (state.coordinator_port, "_document", changed_bytes),
            (state.coordinator, "_document", changed_bytes),
        ):
            with self.subTest(
                target=type(target).__name__,
                slot=name,
            ):
                original = getattr(target, name)
                object.__setattr__(target, name, replacement)
                try:
                    with self.assertRaises(
                        CONSUMER.ProtectedProductionFactoryConsumerError
                    ):
                        result.assert_owner_sealed()
                    self.assertEqual(
                        self.registry_identity_snapshot(),
                        registry,
                    )
                    self.assertTrue(state.coordinator_port._claimed)
                finally:
                    object.__setattr__(target, name, original)
                result.assert_owner_sealed()

    def test_coordinator_method_replacement_stops_before_claim(
        self,
    ) -> None:
        before_plans = len(LEGACY._LEGACY_EFFECT_PLAN_BINDINGS)
        before_owners = len(LEGACY._LEGACY_EFFECT_OWNER_BINDINGS)
        registry = self.registry_identity_snapshot()
        bindings = (
            (
                COORDINATOR.SealedProtectedCoordinatorFactoryPort,
                "document",
            ),
            (
                COORDINATOR.SealedProtectedCoordinatorFactoryPort,
                "assert_owner_sealed",
            ),
            (
                COORDINATOR.SealedProtectedCoordinatorFactoryPort,
                "claim_once",
            ),
            (
                COORDINATOR.ClaimedProtectedCoordinatorFactoryPort,
                "assert_owner_sealed",
            ),
            (
                COORDINATOR.SealedProtectedJobRuntimeCoordinator,
                "document",
            ),
            (
                COORDINATOR.SealedProtectedJobRuntimeCoordinator,
                "assert_current",
            ),
            (
                COORDINATOR.SealedProtectedJobRuntimeCoordinator,
                "_claim_factory_inputs_once",
            ),
        )
        for coordinator_type, method_name in bindings:
            with self.subTest(
                coordinator_type=coordinator_type.__name__,
                method=method_name,
            ):
                port = self.make_port()
                original = getattr(coordinator_type, method_name)

                def wrapper(
                    *args: object,
                    _original: object = original,
                    **kwargs: object,
                ) -> object:
                    return _original(*args, **kwargs)

                with mock.patch.object(
                    coordinator_type,
                    method_name,
                    wrapper,
                ):
                    with self.assertRaisesRegex(
                        CONSUMER.ProtectedProductionFactoryConsumerError,
                        "coordinator method identity",
                    ):
                        CONSUMER.consume_protected_production_factory_once(
                            port
                        )
                self.assertFalse(port._claimed)
                self.assertEqual(
                    self.registry_identity_snapshot(),
                    registry,
                )
                self.assert_no_legacy_factory_objects(
                    before_plans,
                    before_owners,
                )

    def test_source_has_no_factory_raw_owner_adapter_runner_or_write_call(
        self,
    ) -> None:
        source = (
            ROOT / "scripts/protected_production_factory_consumer.py"
        ).read_text(encoding="utf-8")
        tree = ast.parse(source)

        def dotted(node: ast.AST) -> str:
            parts = []
            while isinstance(node, ast.Attribute):
                parts.append(node.attr)
                node = node.value
            if isinstance(node, ast.Name):
                parts.append(node.id)
            return ".".join(reversed(parts))

        calls = {
            dotted(node.func)
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
        }
        for forbidden in (
            "LEGACY._legacy_effect_plan_from_transaction",
            "LEGACY._legacy_raw_effect_owner_from_plan",
            "LEGACY.LegacyTransportAdapter",
            "LEGACY.run",
            "Path.write_bytes",
            "Path.write_text",
            "os.write",
        ):
            self.assertNotIn(forbidden, calls)

    def test_repository_has_one_production_factory_consumer_entrypoint(
        self,
    ) -> None:
        matches = []
        for path in sorted((ROOT / "scripts").glob("*.py")):
            source = path.read_text(encoding="utf-8")
            if "factory_port.claim_once()" in source:
                matches.append(path.relative_to(ROOT).as_posix())
        self.assertEqual(
            matches,
            ["scripts/protected_production_factory_consumer.py"],
        )


if __name__ == "__main__":
    unittest.main()
