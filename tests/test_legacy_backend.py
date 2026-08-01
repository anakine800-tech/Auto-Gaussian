#!/usr/bin/env python3
"""Ordinary synthetic offline tests for the v2.6 legacy backend extraction."""

from __future__ import annotations

import hashlib
import inspect
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
    PR3AuthorizationReplay,
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
        facade_source = (SCRIPTS / "execution_facade.py").read_text(encoding="utf-8")
        legacy_routing = facade_source[
            facade_source.index("def _implementation") :
        ]
        self.assertNotIn("sys.modules", legacy_routing)
        self.assertNotIn("_BOUND_IMPLEMENTATION", facade_source)
        self.assertNotIn("backend_module", facade_source + wrapper)
        self.assertEqual(tuple(inspect.signature(facade.main).parameters), ("argv",))
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
            ExactResourceTuple("simple", 8, 12, 86400)  # type: ignore[call-arg]
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
        from tests.test_execution_authorization import ExecutionAuthorizationTests

        with self.assertRaises(TypeError):
            ValidatedAttestationOperation()  # type: ignore[call-arg]
        with self.assertRaises(TypeError):
            AttestationBoundaryPlan()  # type: ignore[call-arg]
        helper = ExecutionAuthorizationTests("test_exact_synthetic_happy_path_is_only_closure_valid_offline")
        helper.setUp()
        try:
            replay = PR3AuthorizationReplay.from_pr3_owner(
                helper.fixture["authorization_path"],
                now=helper.now,
            )
            operation = ValidatedAttestationOperation.from_replay(replay, operation_index=0)
            plan = legacy.LegacyTransportAdapter().attest_first_hop_once(operation)
            self.assertIsInstance(plan, AttestationBoundaryPlan)
            plan.assert_owner_sealed()
            self.assertFalse(plan.executable)
            self.assertFalse(plan.network_performed)
            self.assertFalse(plan.automatic_retry)
            self.assertEqual(plan.not_before, "2030-01-01T12:00:00Z")
            self.assertEqual(
                plan.allowed_read_only_side_effects,
                ("read_local_identity_sources", "network_identity_handshake"),
            )
            self.assertNotEqual(
                plan.request_nonce_sha256,
                helper.fixture["authorization"]["identity_attestation"]["operations"][0]["request_nonce"],
            )
        finally:
            helper.tearDown()

    def test_pr3_replay_strictly_decodes_successor_documents(self) -> None:
        from tests.test_execution_authorization import ExecutionAuthorizationTests

        helper = ExecutionAuthorizationTests("test_exact_synthetic_happy_path_is_only_closure_valid_offline")
        helper.setUp()
        try:
            raw = helper.fixture["authorization_path"].read_bytes()
            noncanonical = raw.replace(b'"hop_count":2', b'"hop_count":02')
            self.assertNotEqual(noncanonical, raw)
            invalid = {
                "duplicate": b'{"schema":"auto-g16-execution-authorization/1",' + raw[1:],
                "bom": b"\xef\xbb\xbf" + raw,
                "noncanonical": noncanonical,
            }
            for label, payload in invalid.items():
                with self.subTest(label=label):
                    path = helper.root / f"invalid-{label}.json"
                    path.write_bytes(payload)
                    with self.assertRaisesRegex(ModelError, "PR3 execution authorization owner rejected"):
                        PR3AuthorizationReplay.from_pr3_owner(path, now=helper.now)
        finally:
            helper.tearDown()

    def test_production_submit_routes_one_existing_transaction_plan_through_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            args = legacy.build_parser().parse_args([
                "submit", str(FIXTURE), "--project", "safejob",
                "--local-dir", str(root / "bundle"), "--work-kind", "ordinary",
                "--confirmed",
            ])
            with mock.patch.object(
                legacy.LegacyTransportAdapter,
                "invoke_reserved_once",
            ) as invoked:
                legacy.LegacyCLICompatibilityAdapter().dispatch(args)
            invoked.assert_called_once()
            plan = invoked.call_args.args[0]
            self.assertIs(type(plan), legacy._LegacyTransactionPlan)
            plan._assert_owner_sealed()
            self.assertEqual(plan.project, "safejob")
            self.assertFalse(plan.dry_run)

    def test_atomic_consumption_is_single_use_and_idempotency_aware(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with self.assertRaises(TypeError):
                TrustedAuthorizationStateOwner(Path(raw) / "caller", _test_owner=True)  # type: ignore[call-arg]
            with self.assertRaisesRegex(AuthorizationStateError, "root is fixed"):
                TrustedAuthorizationStateOwner(Path(raw) / "caller")
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
