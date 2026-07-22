#!/usr/bin/env python3
"""Ordinary synthetic offline tests for the v2.6 legacy backend extraction."""

from __future__ import annotations

import hashlib
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).parents[1]
SCRIPTS = ROOT / "skills" / "auto-g16-rtwin-pbs" / "scripts"
FIXTURE = ROOT / "tests" / "fixtures" / "rtwin_pbs" / "legacy_v2_5_4_input.gjf"
sys.path.insert(0, str(SCRIPTS))

import execution_facade as facade  # noqa: E402
from execution_authorization_state import (  # noqa: E402
    AuthorizationStateError,
    ConsumptionRequest,
    TrustedAuthorizationStateOwner,
)
from execution_models import (  # noqa: E402
    AttestationBoundaryPlan,
    ExactResourceTuple,
    ModelError,
    RuntimeBinding,
    ValidatedAttestationOperation,
    WorkspacePaths,
)
import legacy_rtwin_pbs as legacy  # noqa: E402


def digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def consumption_request(label: str = "one") -> ConsumptionRequest:
    return ConsumptionRequest(
        authorization_id=f"authorization-{label}",
        authorization_sha256=digest(f"authorization-{label}"),
        readiness_sha256=digest(f"readiness-{label}"),
        attempt_id=f"qsub-attempt-{digest(f'attempt-{label}')}",
        idempotency_key_sha256=digest(f"idempotency-{label}"),
        attestation_nonces=(digest(f"nonce-first-{label}"), digest(f"nonce-nested-{label}")),
        consumed_at="2030-01-01T12:00:00Z",
    )


class LegacyBackendTests(unittest.TestCase):
    maxDiff = None

    def test_wrapper_and_auto_dispatch_have_one_implementation_owner(self) -> None:
        wrapper = (SCRIPTS / "gaussian_rtwin_pbs.py").read_text(encoding="utf-8")
        auto = (SCRIPTS / "gaussian_auto.py").read_text(encoding="utf-8")
        implementation = (SCRIPTS / "legacy_rtwin_pbs.py").read_text(encoding="utf-8")
        self.assertIn("legacy_rtwin_pbs.py", wrapper)
        self.assertNotIn("job_id=$(qsub", wrapper)
        self.assertIn("import execution_facade", auto)
        self.assertIn("execution_facade.bind_current()", auto)
        self.assertEqual(implementation.count("job_id=$(qsub"), 1)
        self.assertNotIn("--backend", wrapper + auto + implementation)
        self.assertNotIn("AUTO_G16_BACKEND", wrapper + auto + implementation)
        self.assertEqual(facade.backend().backend_kind, "legacy_rtwin_pbs")

    def test_typed_runtime_and_fixed_renderer_match_legacy_bytes(self) -> None:
        audit = legacy.parse_gaussian(FIXTURE)
        resources = ExactResourceTuple.from_owner("simple", 8, 12, 86400)
        backend = legacy.LegacyRTWinPBSBackend()
        workspace = backend.workspace.derive("goldenjob")
        plan = backend.runtime.validate_binding(audit, resources, workspace)
        actual = backend.scheduler.render(plan)
        expected = legacy.pbs_text(
            "goldenjob", FIXTURE.name, 8,
            mem_gb=12, walltime_seconds=86400, resource_tier="simple",
        ).encode("utf-8")
        self.assertEqual(actual, expected)
        self.assertEqual(plan.runtime_binding.invocation_mode, "legacy_stdin")
        self.assertEqual(plan.workspace_paths.remote_workdir, "/home/user100/SDL/goldenjob")

    def test_typed_objects_reject_unvalidated_construction_and_invalid_input_component(self) -> None:
        with self.assertRaises(TypeError):
            WorkspacePaths()  # type: ignore[call-arg]
        with self.assertRaises(TypeError):
            RuntimeBinding()  # type: ignore[call-arg]
        audit = legacy.parse_gaussian(FIXTURE)
        audit["input"] = "invalid input.gjf"
        backend = legacy.LegacyRTWinPBSBackend()
        with self.assertRaises(ModelError):
            backend.runtime.validate_binding(
                audit,
                ExactResourceTuple.from_owner("simple", 8, 12, 86400),
                backend.workspace.derive("goldenjob"),
            )
        audit["input"] = "nested/legacy.gjf"
        with self.assertRaisesRegex(ModelError, "exact basename"):
            backend.runtime.validate_binding(
                audit,
                ExactResourceTuple.from_owner("simple", 8, 12, 86400),
                backend.workspace.derive("goldenjob"),
            )

    def test_identity_attestation_is_a_non_executable_boundary_plan(self) -> None:
        base = {
            "operation": "attest_first_hop_once",
            "operation_version": "first-hop-identity-attestation/1",
            "request_nonce": digest("first-nonce"),
            "not_before": "2030-01-01T11:59:00Z",
            "expires_at": "2030-01-01T12:05:00Z",
            "allowed_read_only_side_effects": ["read_local_identity_sources", "network_identity_handshake"],
            "read_only": True,
            "automatic_retry": False,
            "mutation_allowed": False,
        }
        operation = ValidatedAttestationOperation.from_owner(
            base,
            profile_sha256=digest("profile"),
            identity_binding_sha256=digest("binding"),
        )
        plan = legacy.LegacyTransportAdapter().attest_first_hop_once(operation)
        self.assertIsInstance(plan, AttestationBoundaryPlan)
        self.assertFalse(plan.executable)
        self.assertFalse(plan.network_performed)
        self.assertFalse(plan.automatic_retry)
        self.assertNotEqual(plan.request_nonce_sha256, base["request_nonce"])

    def test_production_submit_rejects_legacy_authority_and_stops_at_live_boundary(self) -> None:
        from tests.test_execution_authorization import ExecutionAuthorizationTests

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            old_approval = root / "old-approval.json"
            old_approval.write_text('{"schema":"auto-g16-live-submission-approval/9"}\n', encoding="utf-8")
            old_args = legacy.build_parser().parse_args([
                "submit", str(FIXTURE), "--project", "safejob",
                "--local-dir", str(root / "old"), "--work-kind", "ordinary",
                "--approval-record", str(old_approval), "--confirmed",
            ])
            with mock.patch.object(legacy, "run", side_effect=AssertionError("network boundary crossed")):
                with self.assertRaisesRegex(SystemExit, "2"):
                    legacy.LegacyCLICompatibilityAdapter().dispatch(old_args)

        helper = ExecutionAuthorizationTests("test_exact_synthetic_happy_path_is_only_closure_valid_offline")
        helper.setUp()
        try:
            args = legacy.build_parser().parse_args([
                "submit", str(helper.fixture["input_path"]), "--project", "safejob",
                "--local-dir", str(helper.root / "new"), "--work-kind", "minimum",
                "--approval-record", str(helper.fixture["authorization_path"]), "--confirmed",
            ])
            with mock.patch.object(legacy, "utc_now", return_value=helper.now), mock.patch.object(
                legacy, "run", side_effect=AssertionError("network boundary crossed")
            ):
                with self.assertRaisesRegex(SystemExit, "2"):
                    legacy.LegacyCLICompatibilityAdapter().dispatch(args)
            self.assertFalse((helper.root / "new").exists())
        finally:
            helper.tearDown()

    def test_atomic_consumption_is_single_use_and_idempotency_aware(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            owner = TrustedAuthorizationStateOwner.for_testing(Path(raw) / "state")
            request = consumption_request()
            receipt = owner.consume_after_replay(
                request,
                lambda snapshot: request.readiness_sha256,
            )
            self.assertTrue(receipt.consumed)
            self.assertEqual(receipt.submission_state, "submission_uncertain")
            with self.assertRaisesRegex(AuthorizationStateError, "already consumed"):
                owner.consume_after_replay(request, lambda snapshot: request.readiness_sha256)
            snapshot = owner.snapshot()
            self.assertEqual(snapshot["consumed_authorization_ids"], (request.authorization_id,))
            self.assertEqual(set(snapshot["known_attestation_nonces"]), set(request.attestation_nonces))

    def test_concurrent_consumption_has_one_winner(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "state"
            request = consumption_request("race")
            barrier = threading.Barrier(6)

            def attempt() -> str:
                barrier.wait()
                owner = TrustedAuthorizationStateOwner.for_testing(root)
                try:
                    owner.consume_after_replay(request, lambda snapshot: request.readiness_sha256)
                except AuthorizationStateError:
                    return "blocked"
                return "consumed"

            with ThreadPoolExecutor(max_workers=6) as pool:
                outcomes = list(pool.map(lambda _: attempt(), range(6)))
            self.assertEqual(outcomes.count("consumed"), 1)
            self.assertEqual(outcomes.count("blocked"), 5)

    def test_crash_before_publish_is_retained_as_incomplete_state(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            owner = TrustedAuthorizationStateOwner.for_testing(Path(raw) / "state")
            request = consumption_request("crash")
            with self.assertRaisesRegex(RuntimeError, "synthetic crash"):
                owner.consume_after_replay(
                    request,
                    lambda snapshot: request.readiness_sha256,
                    _crash_before_publish=True,
                )
            with self.assertRaisesRegex(AuthorizationStateError, "requires reconciliation"):
                owner.snapshot()


if __name__ == "__main__":
    unittest.main()
