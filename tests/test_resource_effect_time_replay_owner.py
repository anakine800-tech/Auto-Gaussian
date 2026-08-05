#!/usr/bin/env python3
"""Offline adversarial tests for the package-4 effect-time replay owner."""

from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import json
import pickle
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).parents[1]
ROOT_SCRIPTS = ROOT / "scripts"
SKILL_SCRIPTS = ROOT / "skills" / "auto-g16-rtwin-pbs" / "scripts"
sys.path.insert(0, str(SKILL_SCRIPTS))
sys.path.insert(0, str(ROOT_SCRIPTS))

import resource_efficiency as RESOURCE  # noqa: E402
import resource_effect_time_replay_owner as REPLAY  # noqa: E402
from tests import test_resource_monitor_efficiency as PACKAGE4  # noqa: E402
from tests import (  # noqa: E402
    test_execution_batch_reservation_capability as RESERVATION,
)

PACKAGE4.RESOURCE = RESOURCE
RESERVATION.RESOURCE = RESOURCE
PACKAGE4 = RESERVATION.PACKAGE4
SCHEMA_VALIDATOR = RESERVATION.SCHEMA_VALIDATOR
SCHEMA_PATH = (
    ROOT
    / "contracts/resource-effect-time-replay"
    / "resource-effect-time-replay-capability.schema.json"
)


def wall(second: int) -> datetime:
    return datetime(2026, 1, 1, 0, 6, second, tzinfo=timezone.utc)


class ResourceEffectReplayFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.reservation = RESERVATION.ReservationCapabilityFixture(root)
        self.capability = self.reservation.capability()
        self.policy_path = root / "policy.json"
        self.gate_path = root / "gate.json"
        self.policy_path.write_text(
            json.dumps(self.reservation.policy, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        self.gate_path.write_text(
            json.dumps(self.reservation.gate, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def issue(
        self,
        *,
        issue_wall: datetime | None = None,
        issue_monotonic_ns: int = 1_000_000_000,
    ):
        with mock.patch.object(
            REPLAY,
            "_effect_wall_now",
            return_value=issue_wall or wall(1),
        ), mock.patch.object(
            REPLAY,
            "_effect_monotonic_ns",
            return_value=issue_monotonic_ns,
        ):
            return REPLAY.issue_resource_effect_time_replay_capability(
                reservation_capability=self.capability,
                ledger_path=self.reservation.ledger_path,
                policy_path=self.policy_path,
                gate_path=self.gate_path,
                scheduler_path=self.reservation.scheduler[3],
            )


class ResourceEffectTimeReplayOwnerTests(unittest.TestCase):
    def consume_at(
        self,
        capability,
        *,
        consume_wall: datetime = wall(2),
        consume_monotonic_ns: int = 2_000_000_000,
    ):
        with mock.patch.object(
            REPLAY,
            "_effect_wall_now",
            return_value=consume_wall,
        ), mock.patch.object(
            REPLAY,
            "_effect_monotonic_ns",
            return_value=consume_monotonic_ns,
        ):
            return capability.consume_once()

    def test_positive_issuance_and_consume_replay_exact_owner_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ResourceEffectReplayFixture(Path(temporary))
            capability = fixture.issue()
            document = capability.portable_projection()
            REPLAY.validate_resource_effect_time_replay_capability_document(
                document
            )
            schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
            SCHEMA_VALIDATOR._validate_schema_instance(
                document,
                schema,
                schema,
            )
            claim = self.consume_at(capability)
            scope = claim.exact_scope()
            self.assertTrue(scope["resource_replay_passed"])
            self.assertEqual(
                scope["reservation_capability"]["capability_id"],
                fixture.capability.portable_projection()["capability_id"],
            )
            self.assertEqual(
                scope["current_resource_state"]["attempt_state"],
                "submission_uncertain",
            )
            self.assertEqual(
                scope["identity"]["resource_tier"],
                "simple",
            )
            self.assertFalse(scope["authorizes_runner"])
            self.assertFalse(scope["authorizes_transport"])
            self.assertFalse(scope["authorizes_qsub"])
            self.assertFalse(scope["production_port_wired"])

    def test_resource_artifact_hash_and_document_share_one_fd_snapshot(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ResourceEffectReplayFixture(Path(temporary))
            with mock.patch.object(
                RESOURCE,
                "load",
                side_effect=AssertionError("second path read is forbidden"),
            ):
                document, digest, size = REPLAY.load_artifact(
                    fixture.policy_path
                )
            self.assertEqual(document, fixture.reservation.policy)
            data = fixture.policy_path.read_bytes()
            self.assertEqual(digest, hashlib.sha256(data).hexdigest())
            self.assertEqual(size, len(data))

    def test_capability_and_claim_are_noncopyable_single_use(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ResourceEffectReplayFixture(Path(temporary))
            capability = fixture.issue()
            for operation in (copy.copy, copy.deepcopy, pickle.dumps):
                with self.subTest(operation=operation.__name__):
                    with self.assertRaises(TypeError):
                        operation(capability)
            claim = self.consume_at(capability)
            for operation in (copy.copy, copy.deepcopy, pickle.dumps):
                with self.subTest(claim_operation=operation.__name__):
                    with self.assertRaises(TypeError):
                        operation(claim)
            with self.assertRaisesRegex(
                REPLAY.ResourceError,
                "already been consumed",
            ):
                capability.consume_once()

    def test_concurrent_consumption_succeeds_exactly_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ResourceEffectReplayFixture(Path(temporary))
            capability = fixture.issue()

            def consume() -> str:
                try:
                    self.consume_at(capability)
                except REPLAY.ResourceError:
                    return "blocked"
                return "consumed"

            with ThreadPoolExecutor(max_workers=16) as executor:
                results = list(executor.map(lambda _index: consume(), range(64)))
            self.assertEqual(results.count("consumed"), 1)
            self.assertEqual(results.count("blocked"), 63)

    def test_registered_claim_scope_slot_replacement_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ResourceEffectReplayFixture(Path(temporary))
            claim = self.consume_at(fixture.issue())
            owner_scope = claim.exact_scope()
            cases = (
                (
                    "capability_id",
                    lambda scope: scope.__setitem__(
                        "capability_id",
                        "resource-effect-replay-capability-" + "f" * 64,
                    ),
                ),
                (
                    "identity",
                    lambda scope: scope["identity"].__setitem__(
                        "project",
                        "otherjob",
                    ),
                ),
                (
                    "resource",
                    lambda scope: scope["identity"].__setitem__(
                        "cores",
                        22,
                    ),
                ),
                (
                    "reservation",
                    lambda scope: scope["reservation_capability"].__setitem__(
                        "capability_id",
                        "reservation-capability-" + "d" * 64,
                    ),
                ),
                (
                    "policy",
                    lambda scope: scope["resource_policy"].__setitem__(
                        "policy_revision_id",
                        "replacement-policy",
                    ),
                ),
                (
                    "gate",
                    lambda scope: scope["resource_gate"].__setitem__(
                        "gate_id",
                        "replacement-gate",
                    ),
                ),
                (
                    "state",
                    lambda scope: scope["current_resource_state"].__setitem__(
                        "batch_id",
                        "replacement-batch",
                    ),
                ),
            )
            for label, replace in cases:
                with self.subTest(label=label):
                    replacement = copy.deepcopy(owner_scope)
                    replace(replacement)
                    object.__setattr__(
                        claim,
                        "_ClaimedResourceEffectTimeReplay__scope",
                        replacement,
                    )
                    with self.assertRaisesRegex(
                        REPLAY.ResourceError,
                        "registered owner scope differs",
                    ):
                        claim.exact_scope()
                    object.__setattr__(
                        claim,
                        "_ClaimedResourceEffectTimeReplay__scope",
                        copy.deepcopy(owner_scope),
                    )
                    self.assertEqual(claim.exact_scope(), owner_scope)

            self.assertEqual(claim.exact_scope(), owner_scope)
            forged = object.__new__(REPLAY.ClaimedResourceEffectTimeReplay)
            object.__setattr__(
                forged,
                "_ClaimedResourceEffectTimeReplay__scope",
                copy.deepcopy(owner_scope),
            )
            with self.assertRaisesRegex(
                REPLAY.ResourceError,
                "absent from the owner-private registry",
            ):
                forged.exact_scope()

    def test_registered_capability_slot_replacement_fails_without_consuming(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ResourceEffectReplayFixture(Path(temporary))
            capability = fixture.issue()
            owner_document = capability.portable_projection()
            cases = (
                (
                    "capability_id",
                    lambda document: document.__setitem__(
                        "capability_id",
                        "resource-effect-replay-capability-" + "f" * 64,
                    ),
                ),
                (
                    "identity",
                    lambda document: document["identity"].__setitem__(
                        "project",
                        "otherjob",
                    ),
                ),
                (
                    "reservation",
                    lambda document: document[
                        "reservation_capability"
                    ].__setitem__(
                        "capability_id",
                        "reservation-capability-" + "d" * 64,
                    ),
                ),
                (
                    "policy",
                    lambda document: document["resource_policy"].__setitem__(
                        "policy_revision_id",
                        "replacement-policy",
                    ),
                ),
                (
                    "gate",
                    lambda document: document["resource_gate"].__setitem__(
                        "gate_id",
                        "replacement-gate",
                    ),
                ),
                (
                    "state",
                    lambda document: document[
                        "current_resource_state"
                    ].__setitem__(
                        "batch_id",
                        "replacement-batch",
                    ),
                ),
            )
            for label, replace in cases:
                with self.subTest(label=label):
                    replacement = copy.deepcopy(owner_document)
                    replace(replacement)
                    replacement["payload_sha256"] = RESOURCE._payload(
                        replacement
                    )
                    REPLAY.validate_resource_effect_time_replay_capability_document(
                        replacement
                    )
                    object.__setattr__(
                        capability,
                        "_ResourceEffectTimeReplayCapability__document",
                        replacement,
                    )
                    with self.assertRaisesRegex(
                        REPLAY.ResourceError,
                        "registered owner document differs",
                    ):
                        self.consume_at(capability)
                    object.__setattr__(
                        capability,
                        "_ResourceEffectTimeReplayCapability__document",
                        copy.deepcopy(owner_document),
                    )
            scope = self.consume_at(capability).exact_scope()
            self.assertEqual(
                scope["capability_id"],
                owner_document["capability_id"],
            )
            self.assertEqual(
                scope["identity"],
                owner_document["identity"],
            )
            with self.assertRaisesRegex(
                REPLAY.ResourceError,
                "already been consumed",
            ):
                capability.consume_once()

    def test_policy_gate_scheduler_and_resource_state_drift_fail_closed(
        self,
    ) -> None:
        cases = ("policy", "gate", "scheduler", "resource_state")
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                fixture = ResourceEffectReplayFixture(Path(temporary))
                capability = fixture.issue()
                if case == "policy":
                    changed = copy.deepcopy(fixture.reservation.policy)
                    changed["reviewer"] = "drifted"
                    changed = RESOURCE.finalize_policy(changed)
                    fixture.policy_path.write_text(
                        json.dumps(changed, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
                elif case == "gate":
                    changed = copy.deepcopy(fixture.reservation.gate)
                    changed["gate_id"] = "drifted-gate"
                    changed["gate_sha256"] = PACKAGE4.BATCH.digest_value(
                        {
                            key: value
                            for key, value in changed.items()
                            if key != "gate_sha256"
                        }
                    )
                    fixture.gate_path.write_text(
                        json.dumps(changed, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
                elif case == "scheduler":
                    changed = copy.deepcopy(fixture.reservation.scheduler[0])
                    changed["snapshot_id"] = "drifted-snapshot"
                    changed = RESOURCE.finalize_scheduler_snapshot(changed)
                    fixture.reservation.scheduler[3].write_text(
                        json.dumps(changed, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
                else:
                    attempt_id = capability.portable_projection()["identity"][
                        "attempt_id"
                    ]
                    RESOURCE.reconcile_attempt(
                        fixture.reservation.ledger_path,
                        attempt_id,
                        state="reconciled_not_submitted",
                        observed_at="2026-01-01T00:06:02Z",
                        reason="synthetic read-only state drift",
                        scheduler_reference=None,
                        reconciliation_evidence={
                            "source": "synthetic absence proof",
                            "sha256": "c" * 64,
                        },
                    )
                with self.assertRaises(REPLAY.ResourceError):
                    self.consume_at(capability)
                with self.assertRaisesRegex(
                    REPLAY.ResourceError,
                    "already been consumed",
                ):
                    capability.consume_once()

    def test_tier_cores_memory_splices_reject_even_when_rehashed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            document = ResourceEffectReplayFixture(
                Path(temporary)
            ).issue().portable_projection()
            for field, value in (
                ("resource_tier", "general"),
                ("cores", 22),
                ("memory_gb", 50),
            ):
                with self.subTest(field=field):
                    changed = copy.deepcopy(document)
                    changed["identity"][field] = value
                    changed["payload_sha256"] = RESOURCE._payload(changed)
                    with self.assertRaises(REPLAY.ResourceError):
                        REPLAY.validate_resource_effect_time_replay_capability_document(
                            changed
                        )

    def test_identity_and_reservation_splices_never_become_authority(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            document = ResourceEffectReplayFixture(
                Path(temporary)
            ).issue().portable_projection()
            cases = (
                ("scientific_task_id", "scientific-task-" + "a" * 64),
                ("attempt_id", "qsub-attempt-" + "b" * 64),
                ("project", "otherjob"),
                ("input_sha256", "c" * 64),
            )
            for field, value in cases:
                with self.subTest(field=field):
                    changed = copy.deepcopy(document)
                    changed["identity"][field] = value
                    changed["payload_sha256"] = RESOURCE._payload(changed)
                    REPLAY.validate_resource_effect_time_replay_capability_document(
                        changed
                    )
                    forged = object.__new__(
                        REPLAY.ResourceEffectTimeReplayCapability
                    )
                    object.__setattr__(
                        forged,
                        "_ResourceEffectTimeReplayCapability__document",
                        changed,
                    )
                    with self.assertRaisesRegex(
                        REPLAY.ResourceError,
                        "owner-private registry",
                    ):
                        forged.consume_once()
            changed = copy.deepcopy(document)
            changed["reservation_capability"][
                "capability_id"
            ] = "reservation-capability-" + "d" * 64
            changed["payload_sha256"] = RESOURCE._payload(changed)
            REPLAY.validate_resource_effect_time_replay_capability_document(
                changed
            )
            forged = object.__new__(REPLAY.ResourceEffectTimeReplayCapability)
            object.__setattr__(
                forged,
                "_ResourceEffectTimeReplayCapability__document",
                changed,
            )
            with self.assertRaisesRegex(
                REPLAY.ResourceError,
                "owner-private registry",
            ):
                forged.consume_once()

    def test_expiry_wall_and_monotonic_clock_anomalies_fail_terminal(self) -> None:
        cases = (
            ("expired", wall(32), 32_000_000_000),
            (
                "wall_regression",
                datetime(2026, 1, 1, 0, 5, 54, tzinfo=timezone.utc),
                2_000_000_000,
            ),
            ("monotonic_regression", wall(2), 500_000_000),
            ("clock_divergence", wall(12), 2_000_000_000),
        )
        for label, consume_wall, monotonic_ns in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                capability = ResourceEffectReplayFixture(
                    Path(temporary)
                ).issue()
                with self.assertRaises(REPLAY.ResourceError):
                    self.consume_at(
                        capability,
                        consume_wall=consume_wall,
                        consume_monotonic_ns=monotonic_ns,
                    )
                with self.assertRaisesRegex(
                    REPLAY.ResourceError,
                    "already been consumed",
                ):
                    capability.consume_once()

    def test_schema_valid_projection_is_not_sealed_capability(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            document = ResourceEffectReplayFixture(
                Path(temporary)
            ).issue().portable_projection()
            schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
            SCHEMA_VALIDATOR._validate_schema_instance(
                document,
                schema,
                schema,
            )
            forged = object.__new__(REPLAY.ResourceEffectTimeReplayCapability)
            object.__setattr__(
                forged,
                "_ResourceEffectTimeReplayCapability__document",
                document,
            )
            with self.assertRaisesRegex(
                REPLAY.ResourceError,
                "owner-private registry",
            ):
                forged.consume_once()

    def test_foreign_module_and_cache_replacement_cannot_claim_owner_identity(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ResourceEffectReplayFixture(Path(temporary))
            spec = importlib.util.spec_from_file_location(
                "foreign_resource_effect_time_replay_owner",
                ROOT_SCRIPTS / "resource_effect_time_replay_owner.py",
            )
            assert spec is not None and spec.loader is not None
            foreign = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(foreign)
            previous = sys.modules.get(REPLAY.__name__)
            sys.modules[REPLAY.__name__] = foreign
            try:
                with self.assertRaisesRegex(
                    REPLAY.ResourceError,
                    "replay owner module cache identity changed",
                ):
                    REPLAY.issue_resource_effect_time_replay_capability(
                        reservation_capability=fixture.capability,
                        ledger_path=fixture.reservation.ledger_path,
                        policy_path=fixture.policy_path,
                        gate_path=fixture.gate_path,
                        scheduler_path=fixture.reservation.scheduler[3],
                    )
                with self.assertRaisesRegex(
                    REPLAY.ResourceError,
                    "replay owner module cache identity changed",
                ):
                    foreign.issue_resource_effect_time_replay_capability(
                        reservation_capability=fixture.capability,
                        ledger_path=fixture.reservation.ledger_path,
                        policy_path=fixture.policy_path,
                        gate_path=fixture.gate_path,
                        scheduler_path=fixture.reservation.scheduler[3],
                    )
            finally:
                if previous is None:
                    sys.modules.pop(REPLAY.__name__, None)
                else:
                    sys.modules[REPLAY.__name__] = previous
            canonical = fixture.issue()
            self.assertTrue(
                self.consume_at(canonical).exact_scope()[
                    "resource_replay_passed"
                ]
            )
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ResourceEffectReplayFixture(Path(temporary))
            capability = fixture.issue()
            foreign = PACKAGE4.load(
                "mid_replay_foreign_resource_owner",
                "resource_efficiency.py",
            )
            previous = sys.modules.get(RESOURCE.__name__)
            real_load = REPLAY.load_artifact
            replaced = False

            def replace_during_replay(path: Path):
                nonlocal replaced
                if not replaced:
                    replaced = True
                    sys.modules[RESOURCE.__name__] = foreign
                return real_load(path)

            try:
                with mock.patch.object(
                    REPLAY,
                    "load_artifact",
                    side_effect=replace_during_replay,
                ), self.assertRaisesRegex(
                    REPLAY.ResourceError,
                    "resource owner module cache identity changed",
                ):
                    self.consume_at(capability)
            finally:
                if previous is None:
                    sys.modules.pop(RESOURCE.__name__, None)
                else:
                    sys.modules[RESOURCE.__name__] = previous
            with self.assertRaisesRegex(
                REPLAY.ResourceError,
                "already been consumed",
            ):
                capability.consume_once()

    def test_no_effect_surface_frozen_predecessors_and_package_supplement(
        self,
    ) -> None:
        source_path = ROOT_SCRIPTS / "resource_effect_time_replay_owner.py"
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        for forbidden in (
            "subprocess",
            "socket",
            "paramiko",
            "legacy_rtwin_pbs",
            "execution_facade",
        ):
            self.assertNotIn(forbidden, imports)
        forbidden_functions = {
            "runner",
            "transport",
            "qsub",
            "submit",
            "upload",
            "cancel",
            "cleanup",
            "delete",
        }
        self.assertFalse(
            {
                node.name
                for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            & forbidden_functions
        )
        frozen = {
            "skills/auto-g16-rtwin-pbs/scripts/legacy_rtwin_pbs.py": "3471014b9358380938e98839aaacb9cd3f9f20146fc79c1a9738483021c2cb8e",
            "skills/auto-g16-rtwin-pbs/scripts/execution_facade.py": "e7a3127b4729ee1db99fa9691c0d0b7f00cd953e179d750f3af5ee99cd4dcdc3",
            "skills/auto-g16-rtwin-pbs/scripts/gaussian_rtwin_pbs.py": "3a978dbfbf6d5111d50c087c3c2df775fd15d5cd3924ea063e5ae674bafc0cdb",
            "scripts/protected_owner_consumer_contract.py": "01fe0e30fdbd155e982962d8c4258d4d773d9d0de0b1323e119a6ab3573cd899",
            "scripts/protected_runtime_state_contract.py": "3c8a5b523c695b9ecba3345af5ab56a85fd4d578cfbd00832c07751e97d86d9f",
            "scripts/protected_production_ingress_contract.py": "0cb8d84271968dbc5641a2a2f625d3f3a950a793952104f773c73f71ff45e2df",
            "contracts/rtwin-pbs/execution-batch-v3.schema.json": "9716eead155775cd266d1621378925510070f626ef4ea3e7c628846c39c5b7ff",
            "tests/fixtures/rtwin_pbs/execution_batch_review.template.json": "0ed5a0b26041923a046a4a159edb1c94fafa53666c58fef4c597f9eb27be24c8",
            ".github/workflows/offline-tests.yml": "4c8b90301f82e6afae553ae8b6ce8e88dd8bcfa439467fbaf915a25f89db1886",
            "scripts/audit_python_contract.py": "4fc49831bd0edbed3ec3b4260d2cf2801b80a70153f046b9d1773c5c97611a1f",
            "skills/auto-g16-rtwin-pbs/SKILL.md": "d5107598c2a5dac5c6cf875cd474d502621996282b3116729b7546bed63e2280",
            "skills/auto-g16-rtwin-pbs/scripts/resource_efficiency.py": "2cb86711a748cdd1d4929e5d8c52bf601b80221deab70b3eb5c80a3d4db9cb9b",
        }
        release_successor = json.loads(
            (
                ROOT
                / "tests/fixtures/rtwin_pbs/"
                "release_2_7_ci_contract_successor.json"
            ).read_text(encoding="utf-8")
        )["files"]
        direct_replay_successor_document = json.loads(
            (
                ROOT
                / "tests/fixtures/rtwin_pbs/"
                "direct_effect_time_replay_ingress_ci_successor.json"
            ).read_text(encoding="utf-8")
        )
        direct_replay_successor = direct_replay_successor_document["files"]
        foundation_successor_document = json.loads(
            (
                ROOT
                / "tests/fixtures/rtwin_pbs/"
                "v2_7_production_foundation_integration_successor.json"
            ).read_text(encoding="utf-8")
        )
        foundation_successor = foundation_successor_document["files"]

        def apply_foundation_successor(relative: str, expected: str) -> str:
            if relative not in foundation_successor:
                return expected
            binding = foundation_successor[relative]
            self.assertEqual(binding["before_sha256"], expected)
            return binding["sha256"]
        for relative, expected in frozen.items():
            with self.subTest(relative=relative):
                if relative in release_successor:
                    successor_binding = release_successor[relative]
                    self.assertEqual(
                        successor_binding["before_sha256"],
                        expected,
                    )
                    expected = successor_binding["sha256"]
                if relative in direct_replay_successor:
                    successor_binding = direct_replay_successor[relative]
                    self.assertEqual(
                        successor_binding["before_sha256"],
                        expected,
                    )
                    expected = successor_binding["sha256"]
                expected = apply_foundation_successor(relative, expected)
                self.assertEqual(
                    hashlib.sha256((ROOT / relative).read_bytes()).hexdigest(),
                    expected,
                )
        self.assertEqual(
            direct_replay_successor_document["schema"],
            "auto-g16-direct-effect-time-replay-ingress-ci-successor/1",
        )
        self.assertFalse(
            direct_replay_successor_document["scope"][
                "legacy_runtime_semantics_changed"
            ]
        )
        self.assertEqual(
            foundation_successor_document["schema"],
            "auto-g16-v2.7-production-foundation-integration-successor/1",
        )
        self.assertFalse(foundation_successor_document["scope"]["production_closure"])
        from scripts import skill_package

        package = skill_package.package_files_with_supplements(
            ROOT,
            "auto-g16-rtwin-pbs",
        )
        self.assertEqual(
            package[Path("scripts/resource_effect_time_replay_owner.py")],
            ROOT_SCRIPTS / "resource_effect_time_replay_owner.py",
        )
        self.assertEqual(
            package[
                Path(
                    "contracts/rtwin-pbs/"
                    "resource-effect-time-replay-capability.schema.json"
                )
            ],
            SCHEMA_PATH,
        )
        self.assertEqual(
            package[Path("references/resource-effect-time-replay-owner.md")],
            ROOT / "docs/v2.6-resource-effect-time-replay-owner.md",
        )


if __name__ == "__main__":
    unittest.main()
