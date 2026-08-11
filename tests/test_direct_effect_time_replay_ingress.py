#!/usr/bin/env python3
"""Hostile offline tests for the direct resource/live replay ingress."""

from __future__ import annotations

import ast
import copy
import hashlib
import inspect
import json
import pickle
import sys
import tempfile
import threading
import types
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from typing import NamedTuple
from unittest import mock


ROOT = Path(__file__).parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(ROOT / "skills" / "auto-g16-rtwin-pbs" / "scripts"))

import direct_root_mutation_boundary as ROOT_BOUNDARY  # noqa: E402
import direct_root_owner_contract as ROOT_OWNER  # noqa: E402
import direct_ssh_pbs_offline as DIRECT  # noqa: E402
import resource_efficiency as RESOURCE  # noqa: E402
import resource_effect_time_replay_owner as RESOURCE_REPLAY  # noqa: E402
import skill_package as SKILL_PACKAGE  # noqa: E402
from tests.test_direct_root_owner_contract import DirectRootFixture  # noqa: E402
from tests import test_live_approval_effect_time_replay as LIVE_SUPPORT  # noqa: E402
import live_approval_effect_time_replay as LIVE  # noqa: E402
import direct_effect_time_replay_ingress as INGRESS  # noqa: E402


class DirectReplayIngressFixture:
    def __init__(self, *, project: str = "safejob") -> None:
        self.live_case = LIVE_SUPPORT.LiveApprovalEffectTimeReplayTests("runTest")
        self.live_case.setUp()
        self.live = self.live_case.capability()
        self.protected = (
            self.live_case.fixture.local.lifecycle.invocation.local.protected
        )
        self.approval = json.loads(self.live_case.approval_path.read_text(encoding="utf-8"))
        self.execution = self.approval["scope"]["execution"]
        self.resource = self._resource_capability()
        self.direct_fixture = DirectRootFixture(successor=True)
        self.direct_fixture.clock.value = LIVE_SUPPORT.ISSUED
        input_path = self.protected.input_path
        self.payload = input_path.read_bytes()
        scope = self.approval["scope"]
        resource = self.execution["resource_binding"]
        self.direct_fixture.authorization = ROOT_OWNER.build_direct_execution_authorization(
            authorization_id="direct-authorization-replay-ingress",
            profile=self.direct_fixture.profile,
            stable_evidence=self.direct_fixture.evidence,
            project=project,
            input_basename=input_path.name,
            input_sha256=scope["input_sha256"],
            input_size_bytes=len(self.payload),
            tier=resource["resource_tier"],
            cores=resource["cores"],
            memory_gb=resource["memory_gb"],
            walltime_seconds=resource["walltime_seconds"],
            scientific_task_id=self.execution["scientific_task_id"],
            attempt_id=self.execution["attempt_id"],
            idempotency_key=self.execution["idempotency_key"],
            approved_at="2030-01-01T12:01:00.000000Z",
            not_before="2030-01-01T12:02:00.000000Z",
            expires_at="2030-01-01T12:10:00.000000Z",
            maximum_receipt_age_seconds=60,
        )
        direct_owner = self.direct_fixture.new_owner()
        observation = self.direct_fixture.snapshot(direct_owner, project=project)
        self.root_capability = direct_owner.issue_fresh_capability_once(
            profile=self.direct_fixture.profile,
            stable_evidence=self.direct_fixture.evidence,
            authorization=self.direct_fixture.authorization,
            observation=observation,
        )
        root_owner = ROOT_BOUNDARY.DirectRootMutationBoundaryOwner._for_testing(
            _test_token=ROOT_BOUNDARY._TEST_TOKEN
        )
        root_transaction = root_owner.issue_synthetic_transaction_once(
            root_capability=self.root_capability,
            helper=root_owner._synthetic_helper_for_testing(
                _test_token=ROOT_BOUNDARY._TEST_TOKEN
            ),
        )
        self.transaction = DIRECT.SyntheticTransaction(
            root_capability=self.root_capability,
            root_transaction=root_transaction,
            immutable_input=DIRECT.ImmutableInput(input_path.name, self.payload),
            transport=DIRECT.ClosedFakeTransport(),
        )

    def _artifact(self, name: str, document: dict) -> tuple[Path, str, int]:
        path = self.live_case.root / name
        path.write_text(json.dumps(document, sort_keys=True) + "\n", encoding="utf-8")
        raw = path.read_bytes()
        return path, hashlib.sha256(raw).hexdigest(), len(raw)

    def _resource_capability(self) -> RESOURCE_REPLAY.ResourceEffectTimeReplayCapability:
        ledger_path = self.protected.ledger_path
        task = RESOURCE.validate_ledger(RESOURCE.load(ledger_path))["tasks"][0]
        policy_path, _, _ = self._artifact("direct-ingress-policy.json", self.protected.policy)
        gate_path, _, _ = self._artifact("direct-ingress-gate.json", self.protected.gate)
        scheduler_path, scheduler_sha256, scheduler_size = self._artifact(
            "direct-ingress-scheduler.json",
            self.protected.scheduler,
        )
        reservation = RESOURCE.reserve_attempt_capability(
            ledger_path,
            task["scientific_task_id"],
            identity=task["identity"],
            idempotency_key=self.execution["idempotency_key"],
            project="safejob",
            remote_workdir="/home/user100/SDL/safejob",
            input_sha256=self.approval["scope"]["input_sha256"],
            live_approval_id=self.approval["approval_id"],
            live_approval_sha256=hashlib.sha256(
                self.live_case.approval_path.read_bytes()
            ).hexdigest(),
            estimated_core_hours_evidence=self.execution[
                "estimated_core_hours_evidence"
            ],
            reserved_at="2030-01-01T12:02:30Z",
            audit_reason="offline direct replay ingress fixture",
            policy=self.protected.policy,
            gate=self.protected.gate,
            scheduler_snapshot=self.protected.scheduler,
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
            return RESOURCE_REPLAY.issue_resource_effect_time_replay_capability(
                reservation_capability=reservation,
                ledger_path=ledger_path,
                policy_path=policy_path,
                gate_path=gate_path,
                scheduler_path=scheduler_path,
            )

    def ingress(self) -> INGRESS.DirectEffectTimeReplayIngressCapability:
        return INGRESS.DirectEffectTimeReplayIngressOwner.production().seal_once(
            direct_transaction=self.transaction,
            resource_replay=self.resource,
            live_approval_replay=self.live,
        )

    def consume(
        self,
        ingress: INGRESS.DirectEffectTimeReplayIngressCapability,
        *,
        seconds: int = 1,
    ) -> INGRESS.ClaimedDirectEffectTimeReplayIngress:
        with mock.patch.object(
            RESOURCE_REPLAY,
            "_effect_wall_now",
            return_value=LIVE_SUPPORT.ISSUED + timedelta(seconds=seconds),
        ), mock.patch.object(
            RESOURCE_REPLAY,
            "_effect_monotonic_ns",
            return_value=1_000_000_000 + seconds * 1_000_000_000,
        ):
            return ingress.consume_once()

    def consume_predecessors(self) -> tuple[object, object]:
        with mock.patch.object(
            RESOURCE_REPLAY,
            "_effect_wall_now",
            return_value=LIVE_SUPPORT.REPLAYED,
        ), mock.patch.object(
            RESOURCE_REPLAY,
            "_effect_monotonic_ns",
            return_value=2_000_000_000,
        ):
            resource_claim = self.resource.consume_once()
        return resource_claim, self.live.replay_once()

    def close(self) -> None:
        self.direct_fixture.close()
        self.live_case.tearDown()


class DirectEffectTimeReplayIngressTests(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        self._fixture: DirectReplayIngressFixture | None = None

    @property
    def fixture(self) -> DirectReplayIngressFixture:
        if self._fixture is None:
            self._fixture = DirectReplayIngressFixture()
        return self._fixture

    def tearDown(self) -> None:
        if self._fixture is not None:
            self._fixture.close()

    def test_exact_direct_resource_live_join_and_effect_time_consumption(self) -> None:
        capability = self.fixture.ingress()
        document = capability.document()
        claim = self.fixture.consume(capability)
        result = claim.document()

        self.assertEqual(document["direct"]["profile"]["schema"], "auto-g16-execution-profile/4")
        self.assertEqual(
            document["direct"]["authorization"]["schema"],
            "auto-g16-execution-authorization/4",
        )
        self.assertEqual(document["direct"]["workspace"]["project"], "safejob")
        self.assertEqual(document["direct"]["input"]["sha256"], hashlib.sha256(self.fixture.payload).hexdigest())
        self.assertEqual(document["direct"]["resources"]["cores"], 8)
        self.assertEqual(document["effect_time"], INGRESS.EFFECT_TIME)
        self.assertEqual(document["policy"], INGRESS.POLICY)
        self.assertFalse(document["policy"]["arbitrary_same_process_reflection_isolated"])
        self.assertFalse(document["policy"]["production_closure"])
        self.assertEqual(result["status"], "exact_owner_replays_consumed")
        self.assertIs(type(claim.resource_replay), RESOURCE_REPLAY.ClaimedResourceEffectTimeReplay)
        self.assertIs(type(claim.live_approval_replay), LIVE.CompletedPreQsubLiveApprovalReplay)
        claim.assert_owner_sealed()
        self.assertFalse(result["authority"]["transport_connected"])
        self.assertFalse(result["authority"]["backend_supported"])
        self.assertFalse(result["authority"]["live_ready"])
        self.assertFalse(result["authority"]["qsub_authorized"])
        self.assertEqual(result["authority"]["qsub_calls"], 0)
        hostile_result = copy.deepcopy(result)
        hostile_result["authority"]["qsub_calls"] = False
        projection = copy.deepcopy(hostile_result)
        projection["result_payload_sha256"] = ""
        hostile_result["result_payload_sha256"] = INGRESS.digest(projection)
        with self.assertRaises(INGRESS.DirectEffectTimeReplayIngressError):
            INGRESS.validate_direct_effect_time_replay_ingress_result(hostile_result)

    def test_identity_type_forgery_and_portable_documents_fail_closed(self) -> None:
        owner = INGRESS.DirectEffectTimeReplayIngressOwner.production()
        with self.assertRaisesRegex(INGRESS.DirectEffectTimeReplayIngressError, "exact resource"):
            owner.seal_once(
                direct_transaction=self.fixture.transaction,
                resource_replay=self.fixture.resource.portable_projection(),
                live_approval_replay=self.fixture.live,
            )
        for issued_type in (
            INGRESS.DirectEffectTimeReplayIngressCapability,
            INGRESS.ClaimedDirectEffectTimeReplayIngress,
        ):
            with self.subTest(issued_type=issued_type.__name__):
                with self.assertRaises(TypeError):
                    issued_type()
        forged = object.__new__(INGRESS.DirectEffectTimeReplayIngressCapability)
        object.__setattr__(forged, "ingress_id", "forged")
        object.__setattr__(forged, "_seal", object())
        with self.assertRaises(INGRESS.DirectEffectTimeReplayIngressError):
            forged.assert_current()
        forged_resource = object.__new__(
            RESOURCE_REPLAY.ResourceEffectTimeReplayCapability
        )
        object.__setattr__(
            forged_resource,
            "_ResourceEffectTimeReplayCapability__document",
            self.fixture.resource.portable_projection(),
        )
        forged_ingress = (
            INGRESS.DirectEffectTimeReplayIngressOwner.production().seal_once(
                direct_transaction=self.fixture.transaction,
                resource_replay=forged_resource,
                live_approval_replay=self.fixture.live,
            )
        )
        with self.assertRaisesRegex(
            RESOURCE_REPLAY.ResourceError,
            "absent from the owner-private registry",
        ):
            self.fixture.consume(forged_ingress)
        with self.assertRaisesRegex(
            INGRESS.DirectEffectTimeReplayIngressError,
            "already used",
        ):
            self.fixture.consume(forged_ingress)

    def test_registered_live_ingress_id_drift_is_terminal_before_owner_consumption(self) -> None:
        cases = [
            (self.fixture, "assert_current"),
            (DirectReplayIngressFixture(), "consume_once"),
        ]
        try:
            for fixture, operation in cases:
                with self.subTest(operation=operation):
                    capability = fixture.ingress()
                    canonical_id = capability.document()["ingress_id"]
                    object.__setattr__(capability, "ingress_id", "forged-ingress-id")
                    self.assertNotEqual(capability.ingress_id, canonical_id)
                    with self.assertRaisesRegex(
                        INGRESS.DirectEffectTimeReplayIngressError,
                        "live capability id differs",
                    ):
                        if operation == "assert_current":
                            capability.assert_current()
                        else:
                            fixture.consume(capability)
                    with self.assertRaisesRegex(
                        INGRESS.DirectEffectTimeReplayIngressError,
                        "unavailable or already used",
                    ):
                        fixture.consume(capability)
                    resource_claim, live_result = fixture.consume_predecessors()
                    self.assertIs(
                        type(resource_claim),
                        RESOURCE_REPLAY.ClaimedResourceEffectTimeReplay,
                    )
                    self.assertIs(
                        type(live_result),
                        LIVE.CompletedPreQsubLiveApprovalReplay,
                    )
        finally:
            cases[1][0].close()

    def test_equal_and_synchronized_fake_global_records_fail_terminal(self) -> None:
        class FakeIngressRecord(NamedTuple):
            registered_capability: object
            transaction: object
            root: object
            resource: object
            live: object
            document_bytes: bytes
            lock: object
            status: object
            token: object

        for name in (
            "_CAPABILITY_REGISTRY",
            "_REGISTRY_LOCK",
            "_IngressState",
            "_IngressRecord",
        ):
            self.assertFalse(hasattr(INGRESS, name))
        cases = [
            (self.fixture, False, "assert_current"),
            (DirectReplayIngressFixture(), True, "consume_once"),
        ]
        try:
            for fixture, synchronize, operation in cases:
                with self.subTest(synchronize=synchronize, operation=operation):
                    capability = fixture.ingress()
                    document = capability.document()
                    if synchronize:
                        object.__setattr__(capability, "ingress_id", "forged-ingress-id")
                        document["ingress_id"] = capability.ingress_id
                    fake = FakeIngressRecord(
                        registered_capability=capability,
                        transaction=fixture.transaction,
                        root=fixture.root_capability,
                        resource=fixture.resource,
                        live=fixture.live,
                        document_bytes=INGRESS.canonical_bytes(document),
                        lock=threading.Lock(),
                        status="issued",
                        token=object(),
                    )
                    with mock.patch.object(
                        INGRESS,
                        "_CAPABILITY_REGISTRY",
                        {capability: fake},
                        create=True,
                    ), mock.patch.object(
                        INGRESS,
                        "_IngressState",
                        FakeIngressRecord,
                        create=True,
                    ):
                        with self.assertRaisesRegex(
                            INGRESS.DirectEffectTimeReplayIngressError,
                            "forged module-global owner storage",
                        ):
                            if operation == "assert_current":
                                capability.assert_current()
                            else:
                                fixture.consume(capability)
                    with self.assertRaisesRegex(
                        INGRESS.DirectEffectTimeReplayIngressError,
                        "unavailable or already used",
                    ):
                        fixture.consume(capability)
                    resource_claim, live_result = fixture.consume_predecessors()
                    self.assertIs(
                        type(resource_claim),
                        RESOURCE_REPLAY.ClaimedResourceEffectTimeReplay,
                    )
                    self.assertIs(type(live_result), LIVE.CompletedPreQsubLiveApprovalReplay)
        finally:
            cases[1][0].close()

    def test_module_function_and_method_rebinding_fail_original_owner_entry(self) -> None:
        cases = [
            (self.fixture, "module_function"),
            (DirectReplayIngressFixture(), "class_method"),
        ]
        try:
            for fixture, replacement in cases:
                with self.subTest(replacement=replacement):
                    capability = fixture.ingress()
                    if replacement == "module_function":
                        context = mock.patch.object(
                            INGRESS,
                            "_build_document",
                            lambda *_args: ({}, object()),
                        )
                        expected = "module function identity differs"
                        operation = capability.assert_current
                    else:
                        operation = capability.assert_current
                        context = mock.patch.object(
                            INGRESS.DirectEffectTimeReplayIngressCapability,
                            "assert_current",
                            lambda _self: _self,
                        )
                        expected = "method identity differs"
                    with context:
                        with self.assertRaisesRegex(
                            INGRESS.DirectEffectTimeReplayIngressError,
                            expected,
                        ):
                            operation()
                    with self.assertRaisesRegex(
                        INGRESS.DirectEffectTimeReplayIngressError,
                        "unavailable or already used",
                    ):
                        fixture.consume(capability)
                    resource_claim, live_result = fixture.consume_predecessors()
                    self.assertIs(
                        type(resource_claim),
                        RESOURCE_REPLAY.ClaimedResourceEffectTimeReplay,
                    )
                    self.assertIs(type(live_result), LIVE.CompletedPreQsubLiveApprovalReplay)
        finally:
            cases[1][0].close()

    def test_disclosed_p3_same_process_reflection_can_replace_closure_records(self) -> None:
        capability = self.fixture.ingress()
        installed_assert = type(capability).__dict__["assert_current"]
        assert_vars = inspect.getclosurevars(installed_assert)
        capability_record = assert_vars.nonlocals["capability_record"]
        record_vars = inspect.getclosurevars(capability_record)
        registry = record_vars.nonlocals["capability_registry"]
        anchors = record_vars.nonlocals["capability_identity_anchors"]
        original = registry[capability]
        replacement = original._replace()

        self.assertIsNot(replacement, original)
        self.assertEqual(replacement, original)
        self.assertFalse(INGRESS.POLICY["arbitrary_same_process_reflection_isolated"])
        self.assertEqual(
            INGRESS.POLICY["unisolated_reflection_mechanisms"],
            [
                "inspect.getclosurevars",
                "function.__closure__",
                "cell-contained mutable objects",
                "ctypes",
                "native code",
            ],
        )
        self.assertFalse(INGRESS.POLICY["untrusted_arbitrary_same_process_code_allowed"])
        self.assertTrue(INGRESS.POLICY["w4_process_isolation_required"])
        self.assertFalse(INGRESS.POLICY["production_closure"])
        try:
            registry[capability] = replacement
            with self.assertRaisesRegex(
                INGRESS.DirectEffectTimeReplayIngressError,
                "canonical state identity differs",
            ):
                capability.assert_current()
            registry[capability] = original

            registry[capability] = replacement
            anchors[capability] = replacement
            self.assertIs(capability.assert_current(), capability)
        finally:
            registry[capability] = original
            anchors[capability] = original

        self.assertIs(capability.assert_current(), capability)
        documentation = (
            ROOT / "docs/v2.7-direct-effect-time-replay-ingress.md"
        ).read_text(encoding="utf-8")
        self.assertIn("arbitrary_same_process_reflection_isolated=false", documentation)
        self.assertIn("expected disclosed P3 limitation", documentation)
        self.assertIn("W4 process isolation", documentation)

    def test_capability_and_claim_are_noncopyable_nonserializable(self) -> None:
        capability = self.fixture.ingress()
        claim = self.fixture.consume(capability)
        for value in (capability, claim):
            for operation in (copy.copy, copy.deepcopy, pickle.dumps):
                with self.subTest(value=type(value).__name__, operation=operation.__name__):
                    with self.assertRaises(Exception):
                        operation(value)
        object.__setattr__(claim, "ingress_id", "forged-claimed-ingress-id")
        with self.assertRaisesRegex(
            INGRESS.DirectEffectTimeReplayIngressError,
            "claim id differs",
        ):
            claim.assert_owner_sealed()

    def test_replay_and_concurrent_consumption_have_one_winner(self) -> None:
        capability = self.fixture.ingress()

        def consume(_: int) -> object:
            try:
                return self.fixture.consume(capability)
            except INGRESS.DirectEffectTimeReplayIngressError as exc:
                return str(exc)

        with ThreadPoolExecutor(max_workers=8) as pool:
            values = list(pool.map(consume, range(16)))
        self.assertEqual(
            sum(type(value) is INGRESS.ClaimedDirectEffectTimeReplayIngress for value in values),
            1,
        )
        self.assertEqual(
            sum("unavailable or already used" in value for value in values if type(value) is str),
            15,
        )
        with self.assertRaisesRegex(INGRESS.DirectEffectTimeReplayIngressError, "already used"):
            self.fixture.consume(capability)

    def test_resource_expiry_is_terminal_and_live_is_not_replayed(self) -> None:
        capability = self.fixture.ingress()
        with self.assertRaisesRegex(RESOURCE_REPLAY.ResourceError, "expired"):
            self.fixture.consume(capability, seconds=31)
        self.assertEqual(self.fixture.live.document()["replay"]["replay_count"], 0)
        with self.assertRaisesRegex(INGRESS.DirectEffectTimeReplayIngressError, "already used"):
            self.fixture.consume(capability)

    def test_live_expiry_after_resource_consume_is_terminal_without_retry(self) -> None:
        capability = self.fixture.ingress()
        self.fixture.live_case.set_replay_clock(
            self.fixture.live,
            LIVE_SUPPORT.ISSUED + timedelta(minutes=2),
            121_000_000_000,
        )
        with self.assertRaises(LIVE.LiveApprovalEffectTimeReplayError):
            self.fixture.consume(capability)
        with self.assertRaisesRegex(RESOURCE_REPLAY.ResourceError, "already been consumed"):
            self.fixture.resource.consume_once()
        with self.assertRaisesRegex(INGRESS.DirectEffectTimeReplayIngressError, "already used"):
            self.fixture.consume(capability)

    def test_scope_drift_rejected_before_any_predecessor_consumption(self) -> None:
        mismatched = DirectReplayIngressFixture(project="otherjob")
        try:
            with self.assertRaisesRegex(INGRESS.DirectEffectTimeReplayIngressError, "scope differs: project"):
                mismatched.ingress()
            # Both original sole-owner capabilities remain unused after the seal-time join fails.
            with mock.patch.object(
                RESOURCE_REPLAY,
                "_effect_wall_now",
                return_value=LIVE_SUPPORT.REPLAYED,
            ), mock.patch.object(
                RESOURCE_REPLAY,
                "_effect_monotonic_ns",
                return_value=2_000_000_000,
            ):
                self.assertIs(
                    type(mismatched.resource.consume_once()),
                    RESOURCE_REPLAY.ClaimedResourceEffectTimeReplay,
                )
            self.assertIs(
                type(mismatched.live.replay_once()),
                LIVE.CompletedPreQsubLiveApprovalReplay,
            )
        finally:
            mismatched.close()

    def test_bool_as_int_and_rehashed_projection_splices_are_rejected(self) -> None:
        baseline = self.fixture.ingress().document()
        cases = []
        changed = copy.deepcopy(baseline)
        changed["direct"]["resources"]["cores"] = True
        cases.append(changed)
        changed = copy.deepcopy(baseline)
        changed["effect_time"]["resource_consume_order"] = True
        cases.append(changed)
        changed = copy.deepcopy(baseline)
        changed["authority"]["qsub_calls"] = False
        cases.append(changed)
        changed = copy.deepcopy(baseline)
        changed["policy"]["arbitrary_same_process_reflection_isolated"] = True
        cases.append(changed)
        for document in cases:
            projection = copy.deepcopy(document)
            projection["ingress_id"] = ""
            projection["ingress_payload_sha256"] = ""
            document["ingress_payload_sha256"] = INGRESS.digest(projection)
            document["ingress_id"] = "direct-effect-time-replay-ingress-" + INGRESS.digest(
                {
                    "schema": INGRESS.SCHEMA,
                    "binding_payload_sha256": document["direct"]["binding_payload_sha256"],
                    "resource_capability_id": document["predecessors"]["resource_effect_time_replay"]["capability_id"],
                    "live_capability_id": document["predecessors"]["live_approval_effect_time_replay"]["capability_id"],
                    "ingress_payload_sha256": document["ingress_payload_sha256"],
                }
            )
            with self.subTest(document=document):
                with self.assertRaises(INGRESS.DirectEffectTimeReplayIngressError):
                    INGRESS.validate_direct_effect_time_replay_ingress(document)

    def test_owner_module_source_and_class_replacement_fail_closed(self) -> None:
        with mock.patch.object(
            RESOURCE_REPLAY,
            "ResourceEffectTimeReplayCapability",
            type("ForeignResourceReplay", (), {}),
        ):
            with self.assertRaisesRegex(INGRESS.DirectEffectTimeReplayIngressError, "class identity"):
                INGRESS.DirectEffectTimeReplayIngressOwner.production()
        original = sys.modules[INGRESS.MODULE_NAME]
        foreign = types.ModuleType(INGRESS.MODULE_NAME)
        foreign.__file__ = str(Path(INGRESS.__file__).resolve())
        sys.modules[INGRESS.MODULE_NAME] = foreign
        try:
            with self.assertRaisesRegex(INGRESS.DirectEffectTimeReplayIngressError, "module identity"):
                INGRESS.DirectEffectTimeReplayIngressOwner.production()
        finally:
            sys.modules[INGRESS.MODULE_NAME] = original

    def test_unknown_or_legacy_inputs_have_no_fallback(self) -> None:
        owner = INGRESS.DirectEffectTimeReplayIngressOwner.production()
        with self.assertRaisesRegex(INGRESS.DirectEffectTimeReplayIngressError, "exact direct transaction"):
            owner.seal_once(
                direct_transaction={},
                resource_replay={},
                live_approval_replay={},
            )
        tree = ast.parse((SCRIPTS / "direct_effect_time_replay_ingress.py").read_text(encoding="utf-8"))
        imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        for forbidden in (
            "legacy_rtwin_pbs",
            "execution_facade",
            "protected_job_runtime_coordinator",
            "subprocess",
            "socket",
        ):
            self.assertNotIn(forbidden, imports)

    def test_named_skill_package_supplement_is_additive(self) -> None:
        package = SKILL_PACKAGE.package_files_with_supplements(ROOT, "auto-g16-rtwin-pbs")
        self.assertEqual(
            package[Path("scripts/direct_effect_time_replay_ingress.py")],
            SCRIPTS / "direct_effect_time_replay_ingress.py",
        )
        self.assertEqual(
            package[Path("contracts/rtwin-pbs/direct-effect-time-replay-ingress.schema.json")],
            ROOT / "contracts/direct-execution/direct-effect-time-replay-ingress.schema.json",
        )
        self.assertEqual(
            package[Path("references/direct-effect-time-replay-ingress.md")],
            ROOT / "docs/v2.7-direct-effect-time-replay-ingress.md",
        )
        self.assertFalse(
            (ROOT / "skills/auto-g16-rtwin-pbs/scripts/direct_effect_time_replay_ingress.py").exists()
        )


if __name__ == "__main__":
    unittest.main()
