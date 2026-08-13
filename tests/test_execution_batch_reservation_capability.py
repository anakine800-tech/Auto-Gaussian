#!/usr/bin/env python3
"""Offline adversarial tests for the execution-batch /3 reservation capability."""

from __future__ import annotations

import ast
import copy
import hashlib
import json
import pickle
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from tests import qst3_package_integration_lineage as QST3_LINEAGE
from tests import test_resource_monitor_efficiency as PACKAGE4


ROOT = Path(__file__).parents[1]
RESOURCE = PACKAGE4.RESOURCE
BATCH = PACKAGE4.BATCH
SCHEMA_VALIDATOR = PACKAGE4.SCHEMA_VALIDATOR
SCHEMA_PATH = (
    ROOT
    / "contracts/execution-batch-reservation"
    / "execution-batch-v3-reservation-capability.schema.json"
)
FIXED_BOOL_INTEGER_FIELDS = {
    "reservation": {
        "ledger_write_durable": True,
        "physical_attempt_count": 1,
        "second_physical_attempt_permanently_forbidden": True,
    },
    "authority": {
        "owner_private_registry_required": True,
        "single_consumption": True,
        "schema_valid_is_capability": False,
        "portable_projection_authorizes": False,
        "raw_reservation_json_is_authority": False,
        "raw_reservation_sha256_is_authority": False,
        "capability_authorizes_runner": False,
        "capability_authorizes_transport": False,
        "capability_authorizes_qsub": False,
    },
    "failure_policy": {
        "automatic_retry": False,
        "second_physical_attempt": False,
        "second_qsub": False,
    },
}


class ReservationCapabilityFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.helper = PACKAGE4.ResourceMonitorEfficiencyTests("runTest")
        self.ledger_path, self.task_id = self.helper.make_ledger(root)
        self.policy = self.helper.policy()
        self.scheduler = self.helper.snapshot_artifact(root)
        self.gate = self.helper.gate(
            self.ledger_path,
            self.policy,
            self.scheduler,
        )

    def kwargs(
        self,
        *,
        key: str = "key-1",
        gate: dict | None = None,
        scheduler: tuple | None = None,
    ) -> dict:
        selected_scheduler = scheduler or self.scheduler
        return {
            "identity": PACKAGE4.identity("5" * 64),
            "idempotency_key": key,
            "project": "safejob",
            "remote_workdir": "/home/user100/SDL/safejob",
            "input_sha256": "5" * 64,
            "live_approval_id": f"approval-{key}",
            "live_approval_sha256": hashlib.sha256(
                f"approval-{key}".encode("utf-8")
            ).hexdigest(),
            "estimated_core_hours_evidence": {
                "source": "synthetic reservation capability fixture",
                "sha256": "b" * 64,
            },
            "reserved_at": "2026-01-01T00:06:00Z",
            "audit_reason": "offline reservation capability fixture",
            "policy": self.policy,
            "gate": gate or self.gate,
            "scheduler_snapshot": selected_scheduler[0],
            "scheduler_artifact_sha256": selected_scheduler[1],
            "scheduler_artifact_size": selected_scheduler[2],
        }

    def capability(self):
        return RESOURCE.reserve_attempt_capability(
            self.ledger_path,
            self.task_id,
            **self.kwargs(),
        )


class ExecutionBatchReservationCapabilityTests(unittest.TestCase):
    def test_locked_owner_issues_exact_non_authorizing_projection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ReservationCapabilityFixture(Path(temporary))
            capability = fixture.capability()
            document = capability.portable_projection()
            ledger = RESOURCE.validate_ledger(
                RESOURCE.load(fixture.ledger_path)
            )
            RESOURCE.validate_reservation_capability_document(document)
            schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
            SCHEMA_VALIDATOR._validate_schema_instance(
                document,
                schema,
                schema,
            )

            attempt = ledger["attempts"][0]
            self.assertEqual(attempt["state"], "submission_uncertain")
            self.assertEqual(
                document["identity"]["attempt_id"],
                attempt["attempt_id"],
            )
            self.assertEqual(
                document["identity"]["idempotency_key_sha256"],
                hashlib.sha256(b"key-1").hexdigest(),
            )
            self.assertEqual(
                document["ledger"]["resource_state_revision"],
                ledger["resource_state_revision"],
            )
            self.assertEqual(
                document["ledger"]["resource_state_sha256"],
                ledger["resource_state_sha256"],
            )
            self.assertTrue(document["reservation"]["ledger_write_durable"])
            self.assertFalse(
                document["authority"]["portable_projection_authorizes"]
            )
            self.assertFalse(
                document["authority"]["raw_reservation_json_is_authority"]
            )
            self.assertFalse(
                document["authority"]["raw_reservation_sha256_is_authority"]
            )
            self.assertTrue(
                any(
                    event["event_type"] == "reservation_capability_issued"
                    and event["details"]["capability_id"]
                    == document["capability_id"]
                    for event in ledger["events"]
                )
            )

    def test_all_fifteen_fixed_bool_integer_fields_reject_semantic_splices(
        self,
    ) -> None:
        self.assertEqual(
            sum(len(fields) for fields in FIXED_BOOL_INTEGER_FIELDS.values()),
            15,
        )
        with tempfile.TemporaryDirectory() as temporary:
            document = ReservationCapabilityFixture(
                Path(temporary)
            ).capability().portable_projection()
            for section, fields in FIXED_BOOL_INTEGER_FIELDS.items():
                for field, expected in fields.items():
                    replacements = (
                        (0, 1)
                        if type(expected) is bool
                        else (False, True)
                    )
                    for replacement in replacements:
                        with self.subTest(
                            section=section,
                            field=field,
                            replacement=replacement,
                        ):
                            changed = copy.deepcopy(document)
                            changed[section][field] = replacement
                            changed["payload_sha256"] = RESOURCE._payload(
                                changed
                            )
                            with self.assertRaisesRegex(
                                RESOURCE.ResourceError,
                                "must be exact builtin",
                            ):
                                RESOURCE.validate_reservation_capability_document(
                                    changed
                                )

    def test_capability_and_claim_are_noncopyable_single_use(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            capability = ReservationCapabilityFixture(
                Path(temporary)
            ).capability()
            for operation in (
                copy.copy,
                copy.deepcopy,
                pickle.dumps,
            ):
                with self.subTest(operation=operation.__name__):
                    with self.assertRaises(TypeError):
                        operation(capability)

            claim = capability.claim_once()
            scope = claim.exact_scope()
            self.assertEqual(scope["submission_state"], "submission_uncertain")
            self.assertFalse(scope["authorizes_external_effect"])
            self.assertTrue(
                scope["second_physical_attempt_permanently_forbidden"]
            )
            for operation in (
                copy.copy,
                copy.deepcopy,
                pickle.dumps,
            ):
                with self.subTest(claim_operation=operation.__name__):
                    with self.assertRaises(TypeError):
                        operation(claim)
            with self.assertRaisesRegex(
                RESOURCE.ResourceError,
                "already been claimed",
            ):
                capability.claim_once()

    def test_concurrent_claim_has_exactly_one_success(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            capability = ReservationCapabilityFixture(
                Path(temporary)
            ).capability()

            def claim() -> str:
                try:
                    capability.claim_once()
                except RESOURCE.ResourceError:
                    return "blocked"
                return "claimed"

            with ThreadPoolExecutor(max_workers=16) as executor:
                outcomes = list(executor.map(lambda _index: claim(), range(64)))
            self.assertEqual(outcomes.count("claimed"), 1)
            self.assertEqual(outcomes.count("blocked"), 63)

    def test_concurrent_reservation_issues_exactly_one_capability(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ReservationCapabilityFixture(Path(temporary))

            def reserve() -> str:
                try:
                    fixture.capability()
                except (RESOURCE.ResourceError, BATCH.BatchError):
                    return "blocked"
                return "issued"

            with ThreadPoolExecutor(max_workers=16) as executor:
                outcomes = list(
                    executor.map(lambda _index: reserve(), range(32))
                )
            self.assertEqual(outcomes.count("issued"), 1)
            self.assertEqual(outcomes.count("blocked"), 31)
            ledger = RESOURCE.validate_ledger(
                RESOURCE.load(fixture.ledger_path)
            )
            self.assertEqual(len(ledger["attempts"]), 1)
            self.assertEqual(
                sum(
                    event["event_type"]
                    == "reservation_capability_issued"
                    for event in ledger["events"]
                ),
                1,
            )

    def test_forged_or_projection_only_objects_are_not_capabilities(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            capability = ReservationCapabilityFixture(
                Path(temporary)
            ).capability()
            projection = capability.portable_projection()
            RESOURCE.validate_reservation_capability_document(projection)
            with self.assertRaises(TypeError):
                RESOURCE.ExecutionBatchReservationCapability(projection)

            forged = object.__new__(
                RESOURCE.ExecutionBatchReservationCapability
            )
            object.__setattr__(
                forged,
                "_ExecutionBatchReservationCapability__document",
                projection,
            )
            with self.assertRaisesRegex(
                RESOURCE.ResourceError,
                "owner-private registry",
            ):
                forged.claim_once()

    def test_durable_marker_blocks_second_attempt_after_reconciliation_and_reload(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = ReservationCapabilityFixture(root)
            capability = fixture.capability()
            attempt_id = capability.portable_projection()["identity"][
                "attempt_id"
            ]
            RESOURCE.reconcile_attempt(
                fixture.ledger_path,
                attempt_id,
                state="reconciled_not_submitted",
                observed_at="2026-01-01T00:07:00Z",
                reason="synthetic read-only absence proof",
                scheduler_reference=None,
                reconciliation_evidence={
                    "source": "synthetic read-only proof",
                    "sha256": "c" * 64,
                },
            )
            scheduler = fixture.helper.snapshot_artifact(root)
            ledger = RESOURCE.validate_ledger(
                RESOURCE.load(fixture.ledger_path)
            )
            key = "key-2"
            gate = RESOURCE.evaluate_gate(
                ledger,
                fixture.policy,
                scheduler[0],
                gate_id="gate-2",
                evaluated_at="2026-01-01T00:08:00Z",
                scientific_task_id=fixture.task_id,
                attempt_id=BATCH.attempt_id_for(
                    ledger["batch"]["batch_id"],
                    key,
                ),
                project="safejob",
                input_sha256="5" * 64,
                resource_tier="simple",
                cores=8,
                memory_gb=12,
                walltime_seconds=3600,
                estimated_core_hours=4,
                scheduler_artifact_sha256=scheduler[1],
                scheduler_artifact_size=scheduler[2],
            )
            reloaded = PACKAGE4.load(
                "package4_resource_capability_reload",
                "resource_efficiency.py",
            )
            with self.assertRaisesRegex(
                reloaded.ResourceError,
                "permanently forbids",
            ):
                reloaded.reserve_attempt(
                    fixture.ledger_path,
                    fixture.task_id,
                    **fixture.kwargs(
                        key=key,
                        gate=gate,
                        scheduler=scheduler,
                    ),
                )
            final_ledger = RESOURCE.load(fixture.ledger_path)
            self.assertEqual(len(final_ledger["attempts"]), 1)
            self.assertEqual(
                final_ledger["attempts"][0]["state"],
                "reconciled_not_submitted",
            )

    def test_source_has_no_effect_api_and_frozen_predecessors_match(self) -> None:
        source_path = (
            ROOT
            / "skills/auto-g16-rtwin-pbs/scripts/resource_efficiency.py"
        )
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
        class_methods = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name
            in {
                "runner",
                "transport",
                "qsub",
                "submit",
                "upload",
                "cancel",
                "cleanup",
                "delete",
            }
        }
        self.assertEqual(class_methods, set())

        frozen = {
            "contracts/rtwin-pbs/execution-batch-v3.schema.json": "9716eead155775cd266d1621378925510070f626ef4ea3e7c628846c39c5b7ff",
            "tests/fixtures/rtwin_pbs/execution_batch_review.template.json": "0ed5a0b26041923a046a4a159edb1c94fafa53666c58fef4c597f9eb27be24c8",
            "skills/auto-g16-rtwin-pbs/scripts/legacy_rtwin_pbs.py": "fb72f8aa5ba8063f14d7ef41eddf0b96a783cc69a6294ab04854457c47c158b1",
            "skills/auto-g16-rtwin-pbs/scripts/execution_facade.py": "e7a3127b4729ee1db99fa9691c0d0b7f00cd953e179d750f3af5ee99cd4dcdc3",
            "skills/auto-g16-rtwin-pbs/scripts/gaussian_rtwin_pbs.py": "3a978dbfbf6d5111d50c087c3c2df775fd15d5cd3924ea063e5ae674bafc0cdb",
            "scripts/protected_owner_consumer_contract.py": "01fe0e30fdbd155e982962d8c4258d4d773d9d0de0b1323e119a6ab3573cd899",
            "scripts/protected_runtime_state_contract.py": "3c8a5b523c695b9ecba3345af5ab56a85fd4d578cfbd00832c07751e97d86d9f",
            "scripts/protected_production_ingress_contract.py": "0cb8d84271968dbc5641a2a2f625d3f3a950a793952104f773c73f71ff45e2df",
        }
        lineage = QST3_LINEAGE.load(ROOT)
        for relative, expected in frozen.items():
            with self.subTest(relative=relative):
                if relative in lineage.records:
                    expected = lineage.candidate_from_git_predecessor(relative)
                self.assertEqual(
                    hashlib.sha256((ROOT / relative).read_bytes()).hexdigest(),
                    expected,
                )

    def test_named_skill_package_includes_additive_reference_and_schema(
        self,
    ) -> None:
        from scripts import skill_package

        package = skill_package.package_files_with_supplements(
            ROOT,
            "auto-g16-rtwin-pbs",
        )
        self.assertEqual(
            package[
                Path(
                    "references/execution-batch-v3-reservation-capability.md"
                )
            ],
            ROOT
            / "docs/v2.6-execution-batch-v3-reservation-capability.md",
        )
        self.assertEqual(
            package[
                Path(
                    "contracts/rtwin-pbs/"
                    "execution-batch-v3-reservation-capability.schema.json"
                )
            ],
            SCHEMA_PATH,
        )


if __name__ == "__main__":
    unittest.main()
