#!/usr/bin/env python3
"""Offline tests for the additive PR4 runtime/state successor."""

from __future__ import annotations

import ast
import copy
import hashlib
import json
import os
import pickle
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).parents[1]
ROOT_SCRIPTS = ROOT / "scripts"
SKILL_SCRIPTS = ROOT / "skills" / "auto-g16-rtwin-pbs" / "scripts"
TEST_TEMP_PARENT = Path(tempfile.gettempdir()).resolve()
if TEST_TEMP_PARENT == ROOT or ROOT in TEST_TEMP_PARENT.parents:
    raise RuntimeError("runtime/state tests require a system temporary root")
os.environ["AUTO_G16_RUNTIME_CONFIG"] = str(
    TEST_TEMP_PARENT / "auto-g16-runtime-state-placeholder-absent.json"
)
sys.path.insert(0, str(ROOT_SCRIPTS))
sys.path.insert(0, str(SKILL_SCRIPTS))

import legacy_rtwin_pbs as LEGACY  # noqa: E402
from tests import test_protected_local_materialization as SUPPORT  # noqa: E402
from tests import test_protected_submit_contract as PR4D_SUPPORT  # noqa: E402
import protected_legacy_effect_handoff as HANDOFF  # noqa: E402
import protected_runtime_state_contract as STATE  # noqa: E402


NOW = datetime(2030, 1, 1, 12, 3, 0, tzinfo=timezone.utc)
TRANSPORT_FIXTURE = (
    ROOT / "tests/fixtures/rtwin_pbs/transport_authority_closure.json"
)


class RuntimeStateFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.ssh_config = root / "synthetic-rtwin-ssh-config"
        self.ssh_config.write_text(
            "Host rtwin-placeholder\n  HostName example.invalid\n",
            encoding="utf-8",
        )
        self.second_hop = r"C:\Users\placeholder\.ssh\config"
        first_hash = STATE._adapter_reference_sha256(
            "first_hop", str(self.ssh_config)
        )
        second_hash = STATE._adapter_reference_sha256(
            "second_hop", self.second_hop
        )
        fixture_document = json.loads(
            TRANSPORT_FIXTURE.read_text(encoding="utf-8")
        )
        fixture_document["first_hop_adapter_config_ref_sha256"] = first_hash
        fixture_document["second_hop_adapter_config_ref_sha256"] = second_hash
        fixture_raw = json.dumps(fixture_document, indent=2) + "\n"
        original_read_text = Path.read_text

        def read_text(path: Path, *args: object, **kwargs: object) -> str:
            if path.resolve() == TRANSPORT_FIXTURE.resolve():
                return fixture_raw
            return original_read_text(path, *args, **kwargs)

        with mock.patch.object(Path, "read_text", read_text):
            self.local = SUPPORT.ProtectedLocalMaterializationFixture(root)
        self.runtime_config = root / "runtime.json"
        self.runtime_config.write_text(
            json.dumps(
                {
                    "rtwin_ssh_config": str(self.ssh_config),
                    "windows_target": "rtwin-placeholder",
                    "windows_project_root": r"C:\GaussianProjects",
                    "windows_server_config": self.second_hop,
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

    def close(self) -> None:
        self.local.close()

    def materialize(self) -> object:
        return self.local.owner().materialize_once(self.local.evidence)

    def handoff(self) -> object:
        return (
            HANDOFF.ProtectedLegacyEffectHandoffOwner.production()
            .seal(self.materialize())
        )

    def owner(self) -> STATE.ProtectedRuntimeStateContractOwner:
        return (
            STATE.ProtectedRuntimeStateContractOwner
            ._for_testing_with_clock(
                self.runtime_config,
                lambda: NOW,
                _test_token=STATE._TEST_OWNER_TOKEN,
            )
        )


class ProtectedRuntimeStateContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(
            prefix="auto-g16-protected-runtime-state-",
            dir=TEST_TEMP_PARENT,
        )
        self.root = Path(self.temporary.name).resolve()
        self.fixture = RuntimeStateFixture(self.root)

    def tearDown(self) -> None:
        self.fixture.close()
        self.temporary.cleanup()

    def sealed(self) -> STATE.SealedProtectedRuntimeStateContract:
        return self.fixture.owner().seal(self.fixture.handoff())

    def test_exact_runtime_binding_and_four_state_chain_are_effect_free(
        self,
    ) -> None:
        with (
            mock.patch.object(
                LEGACY, "_legacy_effect_plan_from_transaction"
            ) as effect_plan,
            mock.patch.object(
                LEGACY, "_legacy_raw_effect_owner_from_plan"
            ) as raw_owner,
            mock.patch.object(LEGACY, "run") as runner,
            mock.patch.object(
                LEGACY.LegacyTransportAdapter, "invoke_reserved_once"
            ) as adapter,
        ):
            sealed = self.sealed()
            ready = sealed.current_receipt
            not_started = sealed.consume_for_effect_once()
            uncertain = sealed.prepare_effect_boundary_once(not_started)
            evidence = STATE.ProtectedReadOnlyReconciliationEvidence(
                classification="submitted_unique",
                job_ids=("123.placeholder",),
                evidence_sha256=hashlib.sha256(
                    b"synthetic read-only evidence"
                ).hexdigest(),
                observed_at="2030-01-01T12:03:00Z",
            )
            reconciliation = (
                STATE.ProtectedReadOnlyReconciliationHandoffOwner.production()
                .seal(uncertain_receipt=uncertain, evidence=evidence)
            )
            terminal = sealed.accept_reconciliation_once(
                uncertain_receipt=uncertain,
                reconciliation=reconciliation,
            )
        effect_plan.assert_not_called()
        raw_owner.assert_not_called()
        runner.assert_not_called()
        adapter.assert_not_called()
        self.assertEqual(
            [
                ready.document()["state"],
                not_started.document()["state"],
                uncertain.document()["state"],
                terminal.document()["state"],
            ],
            list(STATE.STATES),
        )
        sealed.assert_current()
        document = sealed.document()
        self.assertEqual(document["scope"], STATE.SCOPE)
        self.assertEqual(document["policy"], STATE.POLICY)
        self.assertEqual(
            document["workspace"]["remote_root"], "/home/user100/SDL"
        )
        self.assertFalse(
            document["workspace"]["remote_root_override_allowed"]
        )
        serialized = STATE.canonical_bytes(document).decode("utf-8")
        self.assertNotIn(str(self.fixture.ssh_config), serialized)
        self.assertNotIn(r"C:\GaussianProjects", serialized)
        self.assertNotIn(self.fixture.second_hop, serialized)
        self.assertEqual(
            sorted(path.name for path in sealed.journal_path.iterdir()),
            sorted(STATE.RECEIPT_BASENAMES),
        )
        self.assertEqual(
            sorted(os.listdir(sealed.handoff.materialization.local_dir)),
            sorted(
                sealed.handoff.materialization.document()[
                    "directory_topology"
                ]
            ),
        )

    def test_transport_reference_mismatch_and_unsafe_windows_paths_stop_cleanly(
        self,
    ) -> None:
        handoff = self.fixture.handoff()
        original = json.loads(self.fixture.runtime_config.read_text())
        cases = (
            ("rtwin_ssh_config", str(self.root / "different-config")),
            ("windows_server_config", r"C:\different\config"),
            ("windows_project_root", r"C:\GaussianProjects\..\escape"),
            ("windows_project_root", "C:/GaussianProjects"),
            ("windows_project_root", "C:\\Gaussian'Projects"),
        )
        for index, (field, value) in enumerate(cases):
            with self.subTest(field=field, value=value):
                changed = copy.deepcopy(original)
                changed[field] = value
                if field == "rtwin_ssh_config":
                    Path(value).write_text("synthetic\n", encoding="utf-8")
                self.fixture.runtime_config.write_text(
                    json.dumps(changed) + "\n",
                    encoding="utf-8",
                )
                owner = self.fixture.owner()
                with self.assertRaises(STATE.ProtectedRuntimeStateError):
                    owner.seal(handoff)
                journal = STATE._journal_path(
                    handoff,
                    handoff.document()["materialization"]["attempt_id"],
                )
                self.assertFalse(journal.exists(), index)
        self.fixture.runtime_config.write_text(
            json.dumps(original) + "\n",
            encoding="utf-8",
        )
        linked = self.root / "linked-ssh-config"
        linked.symlink_to(self.fixture.ssh_config)
        changed = copy.deepcopy(original)
        changed["rtwin_ssh_config"] = str(linked)
        self.fixture.runtime_config.write_text(
            json.dumps(changed) + "\n",
            encoding="utf-8",
        )
        with self.assertRaises(STATE.ProtectedRuntimeStateError):
            self.fixture.owner().seal(handoff)
        self.assertFalse(
            STATE._journal_path(
                handoff,
                handoff.document()["materialization"]["attempt_id"],
            ).exists()
        )

    def test_final_current_replay_precedes_single_consumption_and_uncertainty(
        self,
    ) -> None:
        sealed = self.sealed()
        events: list[str] = []
        original_assert = sealed.assert_current
        original_append = sealed._append

        def asserted() -> object:
            events.append("assert_current")
            return original_assert()

        def appended(*args: object, **kwargs: object) -> object:
            events.append(f"append:{kwargs['sequence']}")
            return original_append(*args, **kwargs)

        with (
            mock.patch.object(
                STATE.SealedProtectedRuntimeStateContract,
                "assert_current",
                autospec=True,
                side_effect=lambda _self: asserted(),
            ),
            mock.patch.object(
                STATE.SealedProtectedRuntimeStateContract,
                "_append",
                autospec=True,
                side_effect=lambda _self, **kwargs: appended(**kwargs),
            ),
        ):
            not_started = sealed.consume_for_effect_once()
        self.assertEqual(events, ["assert_current", "append:1"])
        with self.assertRaises(STATE.ProtectedRuntimeStateError):
            sealed.consume_for_effect_once()
        uncertain = sealed.prepare_effect_boundary_once(not_started)
        self.assertEqual(
            uncertain.document()["state"],
            "effect_started_outcome_uncertain",
        )
        with self.assertRaises(STATE.ProtectedRuntimeStateError):
            sealed.prepare_effect_boundary_once(not_started)

    def test_recovery_replays_append_only_state_without_reconsumption(
        self,
    ) -> None:
        handoff = self.fixture.handoff()
        sealed = self.fixture.owner().seal(handoff)
        sealed.consume_for_effect_once()
        recovered = self.fixture.owner().recover(handoff)
        self.assertEqual(
            recovered.current_receipt.document()["state"],
            "effect_not_started",
        )
        with self.assertRaises(STATE.ProtectedRuntimeStateError):
            recovered.consume_for_effect_once()
        uncertain = recovered.prepare_effect_boundary_once(
            recovered.current_receipt
        )
        recovered_again = self.fixture.owner().recover(handoff)
        self.assertEqual(
            recovered_again.current_receipt.document()[
                "receipt_payload_sha256"
            ],
            uncertain.document()["receipt_payload_sha256"],
        )
        with self.assertRaises(STATE.ProtectedRuntimeStateError):
            recovered_again.prepare_effect_boundary_once(
                recovered_again.current_receipt
            )

    def test_concurrency_allows_one_consumption_and_one_boundary(self) -> None:
        sealed = self.sealed()
        barrier = threading.Barrier(8)

        def consume(_: int) -> object:
            barrier.wait()
            try:
                return sealed.consume_for_effect_once()
            except STATE.ProtectedRuntimeStateError:
                return None

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(consume, range(8)))
        successes = [item for item in results if item is not None]
        self.assertEqual(len(successes), 1)
        not_started = successes[0]
        assert isinstance(
            not_started, STATE.SealedProtectedRuntimeStateReceipt
        )
        with ThreadPoolExecutor(max_workers=8) as pool:
            boundary_results = list(
                pool.map(
                    lambda _: _try_boundary(sealed, not_started),
                    range(8),
                )
            )
        self.assertEqual(sum(item is not None for item in boundary_results), 1)

    def test_copy_pickle_mutation_splice_and_bool_integer_fail_closed(
        self,
    ) -> None:
        sealed = self.sealed()
        receipt = sealed.current_receipt
        for value in (sealed, receipt):
            with self.subTest(value=type(value).__name__):
                with self.assertRaises(TypeError):
                    copy.copy(value)
                with self.assertRaises(TypeError):
                    copy.deepcopy(value)
                with self.assertRaises(TypeError):
                    pickle.dumps(value)
        contract = sealed.document()
        for field in STATE.SCOPE:
            changed = copy.deepcopy(contract)
            changed["scope"][field] = int(STATE.SCOPE[field])
            with self.assertRaises(STATE.ProtectedRuntimeStateError):
                STATE.validate_protected_runtime_state_contract(changed)
        changed_receipt = receipt.document()
        changed_receipt["state"] = "accepted_terminal"
        changed_receipt["receipt_payload_sha256"] = STATE._payload_sha256(
            changed_receipt,
            id_field="receipt_id",
            payload_field="receipt_payload_sha256",
        )
        with self.assertRaises(STATE.ProtectedRuntimeStateError):
            STATE.validate_protected_runtime_state_receipt(changed_receipt)

    def test_runtime_and_receipt_path_replacement_fail_current_replay(
        self,
    ) -> None:
        sealed = self.sealed()
        self.fixture.runtime_config.write_text(
            self.fixture.runtime_config.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        with self.assertRaises(STATE.ProtectedRuntimeStateError):
            sealed.assert_current()

        # Build a fresh fixture for independent receipt replacement evidence.
        other_root = self.root / "other"
        other_root.mkdir()
        other = RuntimeStateFixture(other_root)
        try:
            other_sealed = other.owner().seal(other.handoff())
            receipt_path = (
                other_sealed.journal_path / STATE.RECEIPT_BASENAMES[0]
            )
            raw = receipt_path.read_bytes()
            receipt_path.unlink()
            receipt_path.write_bytes(raw)
            with self.assertRaises(STATE.ProtectedRuntimeStateError):
                other_sealed.assert_current()
        finally:
            other.close()

    def test_module_cache_drift_and_journal_splice_fail_closed(self) -> None:
        sealed = self.sealed()
        original = sys.modules[STATE.HANDOFF_MODULE_NAME]
        sys.modules[STATE.HANDOFF_MODULE_NAME] = mock.Mock()
        try:
            with self.assertRaises(STATE.ProtectedRuntimeStateError):
                sealed.assert_current()
        finally:
            sys.modules[STATE.HANDOFF_MODULE_NAME] = original
        foreign = sealed.journal_path / "foreign.json"
        foreign.write_text("{}\n", encoding="utf-8")
        with self.assertRaises(STATE.ProtectedRuntimeStateError):
            sealed.assert_current()

    def test_reconciliation_semantics_and_splice_are_owner_checked(self) -> None:
        sealed = self.sealed()
        not_started = sealed.consume_for_effect_once()
        uncertain = sealed.prepare_effect_boundary_once(not_started)
        cases = (
            ("submitted_unique", ()),
            ("definitely_not_submitted", ("123.placeholder",)),
            ("still_uncertain_zero", ()),
            ("submitted_unique", ("bad job",)),
        )
        for classification, jobs in cases:
            with self.subTest(classification=classification, jobs=jobs):
                owner = (
                    STATE.ProtectedReadOnlyReconciliationHandoffOwner
                    .production()
                )
                with self.assertRaises(STATE.ProtectedRuntimeStateError):
                    owner.seal(
                        uncertain_receipt=uncertain,
                        evidence=STATE.ProtectedReadOnlyReconciliationEvidence(
                            classification=classification,
                            job_ids=jobs,
                            evidence_sha256="a" * 64,
                            observed_at="2030-01-01T12:03:00Z",
                        ),
                    )
        other_root = self.root / "spliced"
        other_root.mkdir()
        other = RuntimeStateFixture(other_root)
        try:
            other_sealed = other.owner().seal(other.handoff())
            other_not_started = other_sealed.consume_for_effect_once()
            other_uncertain = other_sealed.prepare_effect_boundary_once(
                other_not_started
            )
            reconciliation = (
                STATE.ProtectedReadOnlyReconciliationHandoffOwner.production()
                .seal(
                    uncertain_receipt=other_uncertain,
                    evidence=STATE.ProtectedReadOnlyReconciliationEvidence(
                        classification="definitely_not_submitted",
                        job_ids=(),
                        evidence_sha256="b" * 64,
                        observed_at="2030-01-01T12:03:00Z",
                    ),
                )
            )
            with self.assertRaises(STATE.ProtectedRuntimeStateError):
                sealed.accept_reconciliation_once(
                    uncertain_receipt=uncertain,
                    reconciliation=reconciliation,
                )
        finally:
            other.close()

    def test_source_has_no_effect_or_adapter_dependency(self) -> None:
        source_path = ROOT / "scripts/protected_runtime_state_contract.py"
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        imported = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        for forbidden in (
            "legacy_rtwin_pbs",
            "legacy_adapter_integration",
            "subprocess",
            "socket",
        ):
            self.assertNotIn(forbidden, imported)
        source = source_path.read_text(encoding="utf-8")
        for forbidden in (
            "invoke_reserved_once(",
            "_legacy_raw_effect_owner_from_plan(",
            "_legacy_effect_plan_from_transaction(",
            "qsub(",
            "qdel(",
        ):
            self.assertNotIn(forbidden, source)

    def test_frozen_predecessor_bytes_and_new_package_entries(self) -> None:
        fixture = json.loads(
            (
                ROOT
                / "tests/fixtures/rtwin_pbs/"
                "protected_runtime_state_contract.json"
            ).read_text(encoding="utf-8")
        )
        for relative, expected in fixture["frozen_predecessors"].items():
            self.assertEqual(
                hashlib.sha256((ROOT / relative).read_bytes()).hexdigest(),
                expected,
                relative,
            )
        package = json.loads(
            (
                ROOT
                / "skills/auto-g16-rtwin-pbs/deployment-package.json"
            ).read_text(encoding="utf-8")
        )
        sources = {item["source"] for item in package["include"]}
        self.assertIn(
            "scripts/protected_runtime_state_contract.py", sources
        )
        self.assertIn(
            "skills/auto-g16-rtwin-pbs/references/"
            "protected-runtime-state-contract.md",
            fixture["new_files"],
        )


def _try_boundary(
    sealed: STATE.SealedProtectedRuntimeStateContract,
    receipt: STATE.SealedProtectedRuntimeStateReceipt,
) -> object:
    try:
        return sealed.prepare_effect_boundary_once(receipt)
    except STATE.ProtectedRuntimeStateError:
        return None


if __name__ == "__main__":
    unittest.main()
