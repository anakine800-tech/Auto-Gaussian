#!/usr/bin/env python3
"""Placeholder-only offline tests for PR4B legacy adapter wiring."""

from __future__ import annotations

import copy
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).parents[1]
SCRIPTS = ROOT / "skills" / "auto-g16-rtwin-pbs" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import execution_facade as facade  # noqa: E402
import legacy_adapter_integration as integration  # noqa: E402
import legacy_rtwin_pbs as legacy  # noqa: E402
import skill_package  # noqa: E402
from execution_authorization_state import AuthorizationStateError  # noqa: E402
from tests import test_transport_authority_closure as closure_tests  # noqa: E402


def digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


class RecordingAdapter:
    def __init__(
        self,
        *,
        events: list[str] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.calls = 0
        self.requests: list[integration.ReservedLegacyAttempt] = []
        self.events = events
        self.error = error
        self._lock = threading.Lock()

    def invoke_reserved_once(
        self,
        request: integration.ReservedLegacyAttempt,
    ) -> object:
        with self._lock:
            self.calls += 1
            self.requests.append(request)
            if self.events is not None:
                self.events.append("adapter")
        if self.error is not None:
            raise self.error
        return {
            "classification": "placeholder_adapter_result",
            "actual_operation_performed": False,
        }


class LegacyAdapterIntegrationTests(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        self.helper = closure_tests.TransportAuthorityClosureTests(
            "test_request_authorization_and_actual_receipt_chain_close_offline"
        )
        self.helper.setUp()
        self.temporary = tempfile.TemporaryDirectory()
        self.state_root = Path(self.temporary.name) / "state"

    def tearDown(self) -> None:
        self.temporary.cleanup()
        self.helper.tearDown()

    def artifacts(self, **changes: object) -> integration.SuccessorAuthorityArtifacts:
        values: dict[str, object] = {
            "successor_request": self.helper.request_v2,
            "successor_authorization": self.helper.authorization_v2,
            "base_request": self.helper.base_request,
            "base_authorization": self.helper.base_authorization,
            "profile_v1": self.helper.profile_v1,
            "profile_v2": self.helper.profile_v2,
            "identity_binding": self.helper.binding,
            "first_hop_request": self.helper.first_request,
            "first_hop_receipt": self.helper.first_receipt,
            "nested_hop_request": self.helper.nested_request,
            "nested_hop_receipt": self.helper.nested_receipt,
            "handshake_request": self.helper.handshake_request,
            "handshake_observation": self.helper.observation,
            "handshake_receipt": self.helper.handshake_receipt,
        }
        values.update(changes)
        return integration.SuccessorAuthorityArtifacts(**values)  # type: ignore[arg-type]

    def attempt(self, label: str = "one") -> integration.LegacyAttemptBinding:
        return integration.LegacyAttemptBinding(
            attempt_id=f"qsub-attempt-{digest(f'attempt-{label}')}",
            idempotency_key_sha256=digest(f"idempotency-{label}"),
            consumed_at=self.helper.now,
        )

    def test_complete_owner_replay_precedes_reservation_and_one_adapter_call(self) -> None:
        events: list[str] = []
        adapter = RecordingAdapter(events=events)
        integrator = integration.LegacyAdapterIntegrator.for_testing(
            self.state_root,
        )
        original_replay = integration.replay_successor_readiness
        original_consume = integrator._state_owner.consume_after_replay

        def replay_spy(*args: object, **kwargs: object) -> object:
            events.append("owner_replay")
            return original_replay(*args, **kwargs)

        def consume_spy(*args: object, **kwargs: object) -> object:
            result = original_consume(*args, **kwargs)
            events.append("reserved")
            return result

        with mock.patch.object(
            integration,
            "replay_successor_readiness",
            side_effect=replay_spy,
        ), mock.patch.object(
            integrator._state_owner,
            "consume_after_replay",
            side_effect=consume_spy,
        ), mock.patch.object(
            legacy.LegacyTransportAdapter,
            "invoke_reserved_once",
            side_effect=adapter.invoke_reserved_once,
        ):
            result = integrator.invoke_once(
                artifacts=self.artifacts(),
                attempt=self.attempt(),
                now=self.helper.now,
            )

        self.assertEqual(events, ["owner_replay", "owner_replay", "reserved", "adapter"])
        self.assertEqual(adapter.calls, 1)
        self.assertIs(result.adapter_result["actual_operation_performed"], False)
        result.reservation.assert_owner_sealed()
        self.assertEqual(result.reservation.submission_state, "submission_uncertain")
        self.assertFalse(result.reservation.automatic_retry)
        self.assertTrue(result.reservation.reconcile_only_if_uncertain)
        self.assertEqual(len(result.reservation.attestation_nonces), 3)

    def test_incomplete_or_mismatched_chain_stops_before_reservation_and_adapter(self) -> None:
        adapter = RecordingAdapter()
        integrator = integration.LegacyAdapterIntegrator.for_testing(
            self.state_root,
        )
        changed_receipt = copy.deepcopy(self.helper.handshake_receipt)
        changed_receipt["first_hop_receipt_sha256"] = digest("unrelated-placeholder")
        cases = (
            self.artifacts(successor_request={}),
            self.artifacts(handshake_receipt=changed_receipt),
        )
        with mock.patch.object(
            legacy.LegacyTransportAdapter,
            "invoke_reserved_once",
            side_effect=adapter.invoke_reserved_once,
        ):
            for artifacts in cases:
                with self.subTest(case=artifacts), self.assertRaises(Exception):
                    integrator.invoke_once(
                        artifacts=artifacts,
                        attempt=self.attempt(),
                        now=self.helper.now,
                    )
                self.assertEqual(adapter.calls, 0)
                self.assertFalse(self.state_root.exists())

    def test_concurrent_duplicate_has_one_reservation_and_one_adapter_call(self) -> None:
        adapter = RecordingAdapter()
        barrier = threading.Barrier(6)

        def invoke(_: int) -> str:
            barrier.wait()
            candidate = integration.LegacyAdapterIntegrator.for_testing(
                self.state_root,
            )
            try:
                candidate.invoke_once(
                    artifacts=self.artifacts(),
                    attempt=self.attempt("race"),
                    now=self.helper.now,
                )
            except AuthorizationStateError:
                return "blocked"
            return "called"

        with mock.patch.object(
            legacy.LegacyTransportAdapter,
            "invoke_reserved_once",
            side_effect=adapter.invoke_reserved_once,
        ), ThreadPoolExecutor(max_workers=6) as pool:
            outcomes = list(pool.map(invoke, range(6)))
        self.assertEqual(outcomes.count("called"), 1)
        self.assertEqual(outcomes.count("blocked"), 5)
        self.assertEqual(adapter.calls, 1)

    def test_adapter_exception_is_not_retried_and_uncertain_state_is_retained(self) -> None:
        adapter = RecordingAdapter(error=RuntimeError("placeholder adapter failure"))
        integrator = integration.LegacyAdapterIntegrator.for_testing(
            self.state_root,
        )
        with mock.patch.object(
            legacy.LegacyTransportAdapter,
            "invoke_reserved_once",
            side_effect=adapter.invoke_reserved_once,
        ), self.assertRaises(integration.LegacyAdapterInvocationUncertain) as caught:
            integrator.invoke_once(
                artifacts=self.artifacts(),
                attempt=self.attempt("error"),
                now=self.helper.now,
            )
        self.assertEqual(adapter.calls, 1)
        caught.exception.reservation.assert_owner_sealed()
        self.assertEqual(
            caught.exception.reservation.submission_state,
            "submission_uncertain",
        )
        snapshot = integrator._state_owner.snapshot()
        self.assertEqual(
            snapshot["consumed_authorization_ids"],
            (self.helper.authorization_v2["authorization_id"],),
        )
        with mock.patch.object(
            legacy.LegacyTransportAdapter,
            "invoke_reserved_once",
            side_effect=adapter.invoke_reserved_once,
        ), self.assertRaises(AuthorizationStateError):
            integrator.invoke_once(
                artifacts=self.artifacts(),
                attempt=self.attempt("error"),
                now=self.helper.now,
            )
        self.assertEqual(adapter.calls, 1)

    def test_fixed_facade_has_no_backend_selector_and_routes_to_legacy_adapter(self) -> None:
        signature = str(__import__("inspect").signature(facade.integrate_successor_once))
        self.assertNotIn("backend", signature)
        adapter_result = {
            "classification": "placeholder_adapter_result",
            "actual_operation_performed": False,
        }
        test_owner = integration.TrustedAuthorizationStateOwner.for_testing(
            self.state_root
        )
        with mock.patch.object(
            integration,
            "TrustedAuthorizationStateOwner",
            return_value=test_owner,
        ), mock.patch.object(
            legacy.LegacyTransportAdapter,
            "invoke_reserved_once",
            return_value=adapter_result,
        ) as invoked:
            result = facade.integrate_successor_once(
                artifacts=self.artifacts(),
                attempt=self.attempt("facade"),
                now=self.helper.now,
            )
        self.assertEqual(result.adapter_result, adapter_result)
        invoked.assert_called_once()
        source = (SCRIPTS / "execution_facade.py").read_text(encoding="utf-8")
        self.assertNotIn("--backend", source)
        self.assertNotIn("AUTO_G16_BACKEND", source)

    def test_real_adapter_remains_fail_closed_after_one_retained_reservation(self) -> None:
        integrator = integration.LegacyAdapterIntegrator.for_testing(
            self.state_root,
        )
        with self.assertRaisesRegex(
            integration.LegacyAdapterInvocationUncertain,
            "reconciliation",
        ) as caught:
            integrator.invoke_once(
                artifacts=self.artifacts(),
                attempt=self.attempt("real-placeholder"),
                now=self.helper.now,
            )
        self.assertEqual(
            caught.exception.reservation.submission_state,
            "submission_uncertain",
        )
        self.assertEqual(
            integrator._state_owner.snapshot()["consumed_authorization_ids"],
            (self.helper.authorization_v2["authorization_id"],),
        )

    def test_old_cli_shape_is_unchanged_and_historical_submit_still_stops(self) -> None:
        parser = legacy.build_parser()
        submit = next(
            action
            for action in parser._actions
            if action.dest == "command"
        ).choices["submit"]
        options = {option for action in submit._actions for option in action.option_strings}
        for forbidden in (
            "--backend",
            "--successor-request",
            "--first-hop-receipt",
            "--nested-hop-receipt",
            "--handshake-receipt",
        ):
            self.assertNotIn(forbidden, options)
        self.assertNotIn(
            "integrate_successor_once",
            (SCRIPTS / "legacy_rtwin_pbs.py").read_text(encoding="utf-8")[
                : (SCRIPTS / "legacy_rtwin_pbs.py").read_text(encoding="utf-8").find(
                    "class LegacyTransportAdapter"
                )
            ],
        )

    def test_named_skill_package_and_source_relocation_include_the_wiring(self) -> None:
        package = skill_package.package_files(ROOT, "auto-g16-rtwin-pbs")
        target = Path("scripts/legacy_adapter_integration.py")
        self.assertIn(target, package)
        with tempfile.TemporaryDirectory() as raw:
            installed = Path(raw) / "auto-g16-rtwin-pbs"
            for destination_name, source in package.items():
                destination = installed / destination_name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
            script = (
                "from pathlib import Path\n"
                "import execution_models, legacy_adapter_integration\n"
                "base=Path(legacy_adapter_integration.__file__).resolve().parent\n"
                "assert Path(execution_models.__file__).resolve().parent == base\n"
                "assert legacy_adapter_integration.LegacyAdapterIntegrator.__module__ "
                "== 'legacy_adapter_integration'\n"
            )
            environment = {
                "PATH": os.environ.get("PATH", ""),
                "PYTHONPATH": str(installed / "scripts"),
                "AUTO_G16_RUNTIME_CONFIG": str(
                    Path(raw) / "placeholder-runtime-config-does-not-exist.json"
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
