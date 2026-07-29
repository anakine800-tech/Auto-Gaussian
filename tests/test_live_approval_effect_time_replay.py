#!/usr/bin/env python3
"""Offline tests for the live-approval effect-time replay predecessor."""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import pickle
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).parents[1]
ROOT_SCRIPTS = ROOT / "scripts"
SKILL_SCRIPTS = ROOT / "skills" / "auto-g16-rtwin-pbs" / "scripts"
TEMP_PARENT = Path(tempfile.gettempdir()).resolve()
if TEMP_PARENT == ROOT or ROOT in TEMP_PARENT.parents:
    raise RuntimeError("effect-time replay tests require a system temporary root")
os.environ["AUTO_G16_RUNTIME_CONFIG"] = str(
    TEMP_PARENT / "auto-g16-effect-time-replay-placeholder-absent.json"
)
sys.path.insert(0, str(ROOT_SCRIPTS))
sys.path.insert(0, str(SKILL_SCRIPTS))

import execution_facade as FACADE  # noqa: E402
import legacy_rtwin_pbs as LEGACY  # noqa: E402
import skill_package as SKILL_PACKAGE  # noqa: E402
from tests.test_protected_runtime_state_contract import (  # noqa: E402
    RuntimeStateFixture,
)
from tests import test_protected_owner_consumer_contract as _OWNER_SUPPORT  # noqa: E402,F401
import protected_owner_consumer_contract as CONSUMER  # noqa: E402
import protected_production_ingress_contract as INGRESS  # noqa: E402
import live_approval_effect_time_replay as REPLAY  # noqa: E402


ISSUED = datetime(2030, 1, 1, 12, 3, 0, tzinfo=timezone.utc)
REPLAYED = ISSUED + timedelta(seconds=1)


class LiveApprovalEffectTimeReplayTests(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(
            prefix="auto-g16-live-approval-effect-time-replay-",
            dir=TEMP_PARENT,
        )
        self.root = Path(self.temporary.name).resolve()
        self.fixture = RuntimeStateFixture(self.root)
        runtime = self.fixture.owner().seal(self.fixture.handoff())
        consumer = (
            CONSUMER.ProtectedOwnerConsumerContractOwner.production()
            .prepare_once(runtime)
        )
        self.ingress = (
            INGRESS.ProtectedProductionIngressContractOwner.production()
            .seal_once(consumer)
        )
        self.approval_path = (
            self.fixture.local.lifecycle.invocation.local.protected
            .live_approval_path
        )
        self.clocks: dict[object, dict[str, object]] = {}

    def tearDown(self) -> None:
        self.fixture.close()
        self.temporary.cleanup()

    def owner(
        self,
        *,
        clock: dict[str, object],
    ) -> REPLAY.LiveApprovalEffectTimeReplayOwner:
        return REPLAY.LiveApprovalEffectTimeReplayOwner._for_testing(
            wall_clock=lambda: clock["wall"],  # type: ignore[return-value]
            monotonic_clock=lambda: clock["monotonic_ns"],  # type: ignore[return-value]
            _test_token=REPLAY._TEST_OWNER_TOKEN,
        )

    def capability(
        self,
        *,
        wall: datetime = ISSUED,
        monotonic_ns: int = 100,
    ) -> REPLAY.PreQsubLiveApprovalReplayCapability:
        clock: dict[str, object] = {
            "wall": wall,
            "monotonic_ns": monotonic_ns,
        }
        capability = self.owner(clock=clock).issue_once(
            self.ingress,
            self.approval_path,
        )
        clock["wall"] = REPLAYED
        clock["monotonic_ns"] = monotonic_ns + 1_000_000_000
        self.clocks[capability] = clock
        return capability

    def set_replay_clock(
        self,
        capability: object,
        wall: datetime,
        monotonic_ns: int,
    ) -> None:
        clock = self.clocks[capability]
        clock["wall"] = wall
        clock["monotonic_ns"] = monotonic_ns

    def test_exact_owner_replay_is_single_use_non_authorizing_and_effect_free(
        self,
    ) -> None:
        effect_codes = {
            FACADE.LegacyCLICompatibilityAdapter._submit_new.__code__,
            LEGACY._legacy_effect_plan_from_transaction.__code__,
            LEGACY._legacy_raw_effect_owner_from_plan.__code__,
            LEGACY._LegacyRawEffectOwner.submit_qsub_once.__code__,
        }
        observed_effect_calls: list[object] = []

        def profile(_frame: object, event: str, arg: object) -> None:
            del arg
            if (
                event == "call"
                and getattr(_frame, "f_code", None) in effect_codes
            ):
                observed_effect_calls.append(getattr(_frame, "f_code"))

        previous_profile = sys.getprofile()
        sys.setprofile(profile)
        try:
            with mock.patch.object(LEGACY, "run") as runner, \
                    mock.patch.object(
                        LEGACY.LegacyTransportAdapter,
                        "invoke_reserved_once",
                    ) as adapter:
                before_plan_bindings = len(
                    LEGACY._LEGACY_EFFECT_PLAN_BINDINGS
                )
                before_owner_bindings = len(
                    LEGACY._LEGACY_EFFECT_OWNER_BINDINGS
                )
                capability = self.capability()
                document = capability.document()
                result = capability.replay_once()
        finally:
            sys.setprofile(previous_profile)
        runner.assert_not_called()
        adapter.assert_not_called()
        self.assertEqual(observed_effect_calls, [])
        self.assertEqual(
            len(LEGACY._LEGACY_EFFECT_PLAN_BINDINGS),
            before_plan_bindings,
        )
        self.assertEqual(
            len(LEGACY._LEGACY_EFFECT_OWNER_BINDINGS),
            before_owner_bindings,
        )
        result.assert_owner_sealed()
        replayed = result.document()
        self.assertEqual(
            replayed["status"],
            "approval_replayed_current",
        )
        self.assertTrue(replayed["single_use_consumed"])
        self.assertTrue(replayed["non_authorizing"])
        self.assertEqual(
            {
                replayed["factory_calls"],
                replayed["runner_calls"],
                replayed["qsub_calls"],
                replayed["transport_calls"],
            },
            {0},
        )
        self.assertEqual(
            document["execution_scope"]["attempt_id"],
            self.ingress.document()["identity"]["attempt_id"],
        )
        self.assertEqual(
            document["approval_artifact"]["artifact_sha256"],
            self.ingress.predecessor.document()["intent"][
                "live_approval_artifact_sha256"
            ],
        )
        self.assertEqual(
            document["replay"]["phase"],
            "immediately_before_qsub",
        )
        self.assertFalse(
            document["replay"]["capability_authorizes_effect"]
        )
        with self.assertRaises(
            REPLAY.LiveApprovalEffectTimeReplayError
        ):
            capability.replay_once()

    def test_copy_pickle_forgery_and_concurrent_replay_fail_closed(self) -> None:
        clock: dict[str, object] = {
            "wall": ISSUED,
            "monotonic_ns": 100,
        }
        owners = [self.owner(clock=clock) for _ in range(8)]
        issuance_barrier = threading.Barrier(8)

        def issue(index: int) -> object:
            issuance_barrier.wait()
            try:
                return owners[index].issue_once(
                    self.ingress,
                    self.approval_path,
                )
            except REPLAY.LiveApprovalEffectTimeReplayError:
                return None

        with ThreadPoolExecutor(max_workers=8) as pool:
            issued = list(pool.map(issue, range(8)))
        self.assertEqual(sum(item is not None for item in issued), 1)
        capability = next(item for item in issued if item is not None)
        clock["wall"] = REPLAYED
        clock["monotonic_ns"] = 1_000_000_100
        self.clocks[capability] = clock
        for operation in (
            lambda: copy.copy(capability),
            lambda: copy.deepcopy(capability),
            lambda: pickle.dumps(capability),
        ):
            with self.subTest(operation=operation):
                with self.assertRaises(TypeError):
                    operation()
        original_id = capability.capability_id
        object.__setattr__(capability, "capability_id", "forged")
        with self.assertRaises(
            REPLAY.LiveApprovalEffectTimeReplayError
        ):
            capability.assert_current()
        object.__setattr__(capability, "capability_id", original_id)
        capability.assert_current()

        barrier = threading.Barrier(8)

        def replay(_: int) -> object:
            barrier.wait()
            try:
                return capability.replay_once()
            except REPLAY.LiveApprovalEffectTimeReplayError:
                return None

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(replay, range(8)))
        self.assertEqual(sum(item is not None for item in results), 1)
        result = next(item for item in results if item is not None)
        for operation in (
            lambda: copy.copy(result),
            lambda: copy.deepcopy(result),
            lambda: pickle.dumps(result),
        ):
            with self.subTest(result_operation=operation):
                with self.assertRaises(TypeError):
                    operation()

    def test_file_replacement_revocation_and_failed_replay_are_terminal(
        self,
    ) -> None:
        capability = self.capability()
        approval = json.loads(self.approval_path.read_text(encoding="utf-8"))
        approval["revocation"] = {
            "revoked": True,
            "revoked_at": "2030-01-01T12:03:30Z",
            "reason": "synthetic revocation",
        }
        replacement = self.approval_path.with_name("replacement.json")
        replacement.write_text(
            json.dumps(approval, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(replacement, self.approval_path)
        with self.assertRaisesRegex(
            REPLAY.LiveApprovalEffectTimeReplayError,
            "identity, bytes, or hash drifted",
        ):
            capability.replay_once()
        with self.assertRaisesRegex(
            REPLAY.LiveApprovalEffectTimeReplayError,
            "unavailable or already used",
        ):
            capability.replay_once()

    def test_revoked_approval_is_rejected_at_issue_and_owner_is_terminal(
        self,
    ) -> None:
        approval = json.loads(
            self.approval_path.read_text(encoding="utf-8")
        )
        approval["revocation"] = {
            "revoked": True,
            "revoked_at": "2030-01-01T12:03:30Z",
            "reason": "synthetic revocation",
        }
        self.approval_path.write_text(
            json.dumps(approval, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        revoked_clock: dict[str, object] = {
            "wall": ISSUED,
            "monotonic_ns": 100,
        }
        owner = self.owner(clock=revoked_clock)
        with self.assertRaisesRegex(
            REPLAY.LiveApprovalEffectTimeReplayError,
            "existing live-approval owner rejected",
        ):
            owner.issue_once(self.ingress, self.approval_path)
        with self.assertRaisesRegex(
            REPLAY.LiveApprovalEffectTimeReplayError,
            "owner is single-use",
        ):
            owner.issue_once(self.ingress, self.approval_path)

    def test_expiry_uses_monotonic_lower_bound_and_fails_closed(self) -> None:
        expires = datetime.fromisoformat(
            json.loads(
                self.approval_path.read_text(encoding="utf-8")
            )["expires_at"].replace("Z", "+00:00")
        )
        expired = self.capability()
        self.set_replay_clock(
            expired,
            expires,
            10_000_000_000_000,
        )
        with self.assertRaisesRegex(
            REPLAY.LiveApprovalEffectTimeReplayError,
            "existing live-approval owner rejected",
        ):
            expired.replay_once()

    def test_wall_clock_rollback_fails_closed(self) -> None:
        rollback = self.capability()
        self.set_replay_clock(
            rollback,
            ISSUED - timedelta(seconds=1),
            200,
        )
        with self.assertRaisesRegex(
            REPLAY.LiveApprovalEffectTimeReplayError,
            "wall clock rolled back",
        ):
            rollback.replay_once()

    def test_monotonic_clock_rollback_fails_closed(self) -> None:
        monotonic = self.capability(monotonic_ns=500)
        self.set_replay_clock(monotonic, REPLAYED, 499)
        with self.assertRaisesRegex(
            REPLAY.LiveApprovalEffectTimeReplayError,
            "monotonic clock rolled back",
        ):
            monotonic.replay_once()

    def test_foreign_module_cache_replacement_fails_closed(
        self,
    ) -> None:
        capability = self.capability()
        canonical = sys.modules[REPLAY.MODULE_NAME]
        foreign = importlib.util.module_from_spec(
            importlib.util.spec_from_loader(
                REPLAY.MODULE_NAME,
                loader=None,
            )
        )
        sys.modules[REPLAY.MODULE_NAME] = foreign
        try:
            with self.assertRaisesRegex(
                REPLAY.LiveApprovalEffectTimeReplayError,
                "canonical effect-time replay module was replaced",
            ):
                capability.replay_once()
        finally:
            sys.modules[REPLAY.MODULE_NAME] = canonical

    def test_live_owner_callable_identity_replacement_fails_closed(
        self,
    ) -> None:
        capability = self.capability()
        original = LEGACY.validate_live_approval_binding
        LEGACY.validate_live_approval_binding = lambda *args: ({}, "")
        try:
            with self.assertRaisesRegex(
                REPLAY.LiveApprovalEffectTimeReplayError,
                "live-approval owner identity was replaced",
            ):
                capability.replay_once()
        finally:
            LEGACY.validate_live_approval_binding = original

    def test_live_owner_source_replacement_fails_closed(self) -> None:
        capability = self.capability()
        original_capture = REPLAY._capture_source

        def changed_source(module: object, label: str) -> object:
            captured = original_capture(module, label)
            if module is LEGACY:
                return REPLAY._SourceSnapshot(
                    captured.path,
                    captured.identity,
                    "f" * 64,
                )
            return captured

        with mock.patch.object(
            REPLAY,
            "_capture_source",
            side_effect=changed_source,
        ):
            with self.assertRaisesRegex(
                REPLAY.LiveApprovalEffectTimeReplayError,
                "live-approval owner source was replaced or changed",
            ):
                capability.replay_once()

    def test_structural_validation_never_issues_a_capability(self) -> None:
        capability = self.capability()
        document = capability.document()
        self.assertEqual(
            REPLAY.validate_live_approval_effect_time_replay(document),
            document,
        )
        with self.assertRaises(TypeError):
            REPLAY.PreQsubLiveApprovalReplayCapability()
        changed = copy.deepcopy(document)
        changed["effect_boundary"]["qsub_calls"] = 1
        with self.assertRaises(
            REPLAY.LiveApprovalEffectTimeReplayError
        ):
            REPLAY.validate_live_approval_effect_time_replay(changed)

    def test_package_supplement_maps_owner_schema_and_reference(self) -> None:
        packaged = SKILL_PACKAGE.package_files_with_supplements(
            ROOT,
            "auto-g16-rtwin-pbs",
        )
        self.assertEqual(
            packaged[
                Path("scripts/live_approval_effect_time_replay.py")
            ],
            ROOT / "scripts/live_approval_effect_time_replay.py",
        )
        self.assertEqual(
            packaged[
                Path(
                    "contracts/execution/"
                    "live-approval-effect-time-replay.schema.json"
                )
            ],
            ROOT
            / "contracts/execution/"
            "live-approval-effect-time-replay.schema.json",
        )
        self.assertEqual(
            packaged[
                Path(
                    "references/"
                    "live-approval-effect-time-replay.md"
                )
            ],
            ROOT / "docs/v2.6-live-approval-effect-time-replay.md",
        )
        base = SKILL_PACKAGE.package_files(
            ROOT,
            "auto-g16-rtwin-pbs",
        )
        self.assertNotIn(
            Path("scripts/live_approval_effect_time_replay.py"),
            base,
        )


if __name__ == "__main__":
    unittest.main()
