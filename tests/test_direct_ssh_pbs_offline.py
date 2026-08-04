#!/usr/bin/env python3
"""Focused hostile tests for the v2.7 direct SSH/PBS offline backend."""

from __future__ import annotations

import ast
import dataclasses
import hashlib
import inspect
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

from tests.test_direct_root_owner_contract import ATTEMPT, TASK, DirectRootFixture


ROOT = Path(__file__).parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import direct_root_mutation_boundary as ROOT_BOUNDARY  # noqa: E402
import direct_root_owner_contract as ROOT_OWNER  # noqa: E402
import direct_ssh_pbs_offline as OFFLINE  # noqa: E402
import skill_package as SKILL_PACKAGE  # noqa: E402


class DirectSSHPBSOfflineTests(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        self.payload = b"%nprocshared=8\n%mem=12GB\n# synthetic-only\n\n"
        self.fixture = DirectRootFixture()
        self.fixture.authorization = ROOT_OWNER.build_direct_execution_authorization(
            authorization_id="direct-authorization-001",
            profile=self.fixture.profile,
            stable_evidence=self.fixture.evidence,
            project="case_001",
            input_basename="input.gjf",
            input_sha256=hashlib.sha256(self.payload).hexdigest(),
            input_size_bytes=len(self.payload),
            tier="simple",
            cores=8,
            memory_gb=12,
            walltime_seconds=3600,
            scientific_task_id=TASK,
            attempt_id=ATTEMPT,
            idempotency_key="direct-case-001",
            approved_at="2026-07-28T23:59:00.000000Z",
            not_before="2026-07-29T00:00:00.000000Z",
            expires_at="2026-07-29T01:00:00.000000Z",
            maximum_receipt_age_seconds=60,
        )

    def build(
        self,
        *,
        failure_at: OFFLINE.Operation | None = None,
        unknown_at: OFFLINE.Operation | None = None,
        immutable_input: OFFLINE.ImmutableInput | None = None,
    ) -> tuple[OFFLINE.SyntheticTransaction, OFFLINE.ClosedFakeTransport]:
        capability = self.fixture.capability()
        root_owner = ROOT_BOUNDARY.DirectRootMutationBoundaryOwner._for_testing(
            _test_token=ROOT_BOUNDARY._TEST_TOKEN
        )
        root_transaction = root_owner.issue_synthetic_transaction_once(
            root_capability=capability,
            helper=root_owner._synthetic_helper_for_testing(
                _test_token=ROOT_BOUNDARY._TEST_TOKEN
            ),
        )
        transport = OFFLINE.ClosedFakeTransport(
            failure_at=failure_at,
            unknown_at=unknown_at,
        )
        return (
            OFFLINE.SyntheticTransaction(
                root_capability=capability,
                root_transaction=root_transaction,
                immutable_input=immutable_input
                or OFFLINE.ImmutableInput("input.gjf", self.payload),
                transport=transport,
            ),
            transport,
        )

    def test_exact_joins_fixed_topology_gaps_and_non_authority(self) -> None:
        transaction, transport = self.build()
        binding = transaction.binding()
        result = transaction.run_once().document()

        self.assertEqual(
            (binding["backend_kind"], binding["transport_kind"], binding["scheduler_dialect"]),
            ("direct_ssh_pbs", "direct_ssh", "pbs_legacy_v1"),
        )
        self.assertFalse(binding["live_ready"])
        self.assertEqual(
            binding["profile"]["profile_payload_sha256"],
            self.fixture.profile["profile_payload_sha256"],
        )
        self.assertEqual(
            binding["profile"]["stable_root_evidence_sha256"],
            self.fixture.evidence.document()["evidence_payload_sha256"],
        )
        self.assertEqual(
            binding["authorization"]["authorization_payload_sha256"],
            self.fixture.authorization["authorization_payload_sha256"],
        )
        self.assertEqual(binding["workspace"]["project"], "case_001")
        self.assertEqual(binding["input"]["sha256"], hashlib.sha256(self.payload).hexdigest())
        self.assertEqual(binding["resources"]["tier"], "simple")
        self.assertEqual(binding["resources"]["cores"], "8")
        self.assertEqual(binding["scope"]["scientific_task_id"], TASK)
        self.assertEqual(binding["scope"]["attempt_id"], ATTEMPT)
        self.assertEqual(binding["scope"]["idempotency_key"], "direct-case-001")
        self.assertEqual(binding["owner_gaps"], [gap.document() for gap in OFFLINE.OWNER_GAPS])
        self.assertEqual(
            transport.snapshot(),
            (
                OFFLINE.SUBMISSION_UNCERTAIN,
                tuple(operation.value for operation in OFFLINE.MUTATIONS),
                1,
                True,
            ),
        )
        self.assertEqual(transaction.state(), OFFLINE.INTENT_RECORDED)
        self.assertEqual(result["authority"], OFFLINE.AUTHORITY)
        self.assertFalse(result["authority"]["qsub_invoked"])
        self.assertTrue(result["authority"]["qdel_requires_separate_exact_authorization"])

    def test_immutable_transfer_and_read_only_inspect_fetch(self) -> None:
        mutable = bytearray(self.payload)
        immutable = OFFLINE.ImmutableInput("input.gjf", bytes(mutable))
        transaction, transport = self.build(immutable_input=immutable)
        mutable[:] = b"x" * len(mutable)
        transaction.run_once()
        before = transport.snapshot()
        inspection = transaction.inspect()
        fetched = transaction.fetch()
        for _ in range(8):
            self.assertEqual(transaction.inspect(), inspection)
            self.assertEqual(transaction.fetch(), fetched)
        self.assertEqual(transport.snapshot(), before)
        self.assertEqual(inspection.operation, OFFLINE.Operation.INSPECT)
        self.assertTrue(inspection.read_only)
        self.assertFalse(inspection.remote_effect_performed)
        self.assertEqual(fetched.operation, OFFLINE.Operation.FETCH)
        self.assertTrue(fetched.read_only)
        self.assertFalse(fetched.remote_effect_performed)
        self.assertEqual(fetched.payload, self.payload)
        self.assertEqual(fetched.sha256, hashlib.sha256(self.payload).hexdigest())
        with self.assertRaises(dataclasses.FrozenInstanceError):
            immutable.basename = "changed.gjf"  # type: ignore[misc]
        with self.assertRaises(OFFLINE.DirectOfflineError):
            OFFLINE.ImmutableInput("input.gjf", bytearray(self.payload))  # type: ignore[arg-type]

    def test_concurrent_single_winner_and_second_qsub_rejected(self) -> None:
        transaction, transport = self.build()

        def run(_: int) -> object:
            try:
                return transaction.run_once()
            except OFFLINE.DirectOfflineError as exc:
                return str(exc)

        with ThreadPoolExecutor(max_workers=8) as pool:
            values = list(pool.map(run, range(16)))
        self.assertEqual(sum(type(value) is OFFLINE.SyntheticResult for value in values), 1)
        self.assertEqual(sum(value == "transaction already terminal" for value in values), 15)
        self.assertEqual(transport.snapshot()[2], 1)
        with self.assertRaisesRegex(OFFLINE.DirectOfflineError, "second qsub intent"):
            transport.record_qsub_intent(
                transaction._binding,
                {
                    "binding_payload_sha256": transaction._binding.sha256,
                    "remote_effect_performed": False,
                    "payload_sha256": "a" * 64,
                },
            )

    def test_every_failure_and_unknown_is_terminal_uncertain_without_retry(self) -> None:
        for mode in ("failure", "unknown"):
            for operation in OFFLINE.MUTATIONS:
                with self.subTest(mode=mode, operation=operation.value):
                    transaction, transport = self.build(
                        failure_at=operation if mode == "failure" else None,
                        unknown_at=operation if mode == "unknown" else None,
                    )
                    error = RuntimeError if mode == "failure" else OFFLINE.SyntheticOutcomeUnknown
                    with self.assertRaises(error):
                        transaction.run_once()
                    self.assertEqual(transaction.state(), OFFLINE.SUBMISSION_UNCERTAIN)
                    self.assertEqual(transport.snapshot()[0], OFFLINE.SUBMISSION_UNCERTAIN)
                    with self.assertRaisesRegex(OFFLINE.DirectOfflineError, "already terminal"):
                        transaction.run_once()

    def test_wrong_input_topology_foreign_and_unknown_fail_closed(self) -> None:
        with self.assertRaisesRegex(OFFLINE.DirectOfflineError, "immutable input join"):
            self.build(immutable_input=OFFLINE.ImmutableInput("input.gjf", b"wrong"))
        for name, value in (
            ("BACKEND_KIND", "unknown_backend"),
            ("SCHEDULER_DIALECT", "unknown_scheduler"),
        ):
            with self.subTest(name=name):
                with mock.patch.object(OFFLINE, name, value):
                    with self.assertRaisesRegex(OFFLINE.DirectOfflineError, "unsupported direct topology"):
                        self.build()
        with self.assertRaises(OFFLINE.DirectOfflineError):
            OFFLINE.ClosedFakeTransport(failure_at="unknown")  # type: ignore[arg-type]
        with self.assertRaises(OFFLINE.DirectOfflineError):
            OFFLINE.SyntheticTransaction(
                root_capability={},  # type: ignore[arg-type]
                root_transaction={},  # type: ignore[arg-type]
                immutable_input=OFFLINE.ImmutableInput("input.gjf", self.payload),
                transport={},  # type: ignore[arg-type]
            )

    def test_no_command_callback_root_selector_qdel_delete_cleanup_or_fallback(self) -> None:
        self.assertEqual(
            tuple(inspect.signature(OFFLINE.SyntheticTransaction.__init__).parameters),
            ("self", "root_capability", "root_transaction", "immutable_input", "transport"),
        )
        self.assertEqual(tuple(inspect.signature(OFFLINE.SyntheticTransaction.run_once).parameters), ("self",))
        self.assertEqual(
            {operation.value for operation in OFFLINE.Operation},
            {
                "publish_submission_uncertain",
                "record_workspace_claim",
                "transfer_immutable_input",
                "record_synthetic_qsub_intent",
                "inspect_read_only",
                "fetch_read_only",
            },
        )
        public = {
            name
            for cls in (OFFLINE.SyntheticTransaction, OFFLINE.ClosedFakeTransport)
            for name in dir(cls)
            if not name.startswith("_")
        }
        for forbidden in ("command", "argv", "callback", "root", "environment", "qdel", "delete", "cleanup", "cancel"):
            self.assertFalse(any(forbidden in name.lower() for name in public))

        tree = ast.parse((SCRIPTS / "direct_ssh_pbs_offline.py").read_text(encoding="utf-8"))
        imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        for forbidden in (
            "argparse",
            "os",
            "subprocess",
            "socket",
            "paramiko",
            "legacy_rtwin_pbs",
            "execution_facade",
            "protected_production_factory_consumer",
            "resource_effect_time_replay_owner",
            "live_approval_effect_time_replay",
        ):
            self.assertNotIn(forbidden, imports)

    def test_package_is_additive_and_legacy_root_object_is_untouched(self) -> None:
        package = SKILL_PACKAGE.package_files_with_supplements(ROOT, "auto-g16-rtwin-pbs")
        self.assertEqual(
            package[Path("scripts/direct_ssh_pbs_offline.py")],
            SCRIPTS / "direct_ssh_pbs_offline.py",
        )
        self.assertEqual(
            package[Path("references/direct-ssh-pbs-offline-backend.md")],
            ROOT / "docs/v2.7-direct-ssh-pbs-offline-backend.md",
        )
        self.assertFalse(
            (ROOT / "skills/auto-g16-rtwin-pbs/scripts/direct_ssh_pbs_offline.py").exists()
        )
        self.assertEqual(ROOT_OWNER.BACKEND_KIND, "direct_ssh_pbs")
        legacy_tree = ast.parse(
            (SCRIPTS / "legacy_root_authority_contract.py").read_text(
                encoding="utf-8"
            )
        )
        fixed_roots = [
            node.value.value
            for node in legacy_tree.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name)
                and target.id == "FIXED_REMOTE_ROOT"
                for target in node.targets
            )
            and isinstance(node.value, ast.Constant)
        ]
        self.assertEqual(fixed_roots, ["/home/user100/SDL"])


if __name__ == "__main__":
    unittest.main()
