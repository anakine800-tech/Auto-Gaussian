#!/usr/bin/env python3
"""Offline tests for the additive PR4 runtime/state successor."""

from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import json
import os
import pickle
import shutil
import subprocess
import sys
import tempfile
import threading
import textwrap
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
import skill_package as SKILL_PACKAGE  # noqa: E402


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
        self.second_hop = r"C:\Synthetic\.ssh\config"
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

    def test_successor_module_and_issued_class_identity_fail_closed(
        self,
    ) -> None:
        sealed = self.sealed()
        original_module = sys.modules[STATE.MODULE_NAME]
        self.assertIs(
            vars(HANDOFF)[STATE.OWNER_REGISTRATION_ATTRIBUTE],
            original_module,
        )
        sys.modules[STATE.MODULE_NAME] = mock.Mock()
        try:
            with self.assertRaises(STATE.ProtectedRuntimeStateError):
                sealed.assert_current()
        finally:
            sys.modules[STATE.MODULE_NAME] = original_module

        original_type = STATE.SealedProtectedRuntimeStateContract
        STATE.SealedProtectedRuntimeStateContract = mock.Mock()
        try:
            with self.assertRaises(STATE.ProtectedRuntimeStateError):
                sealed.current_receipt.assert_current()
        finally:
            STATE.SealedProtectedRuntimeStateContract = original_type

        source = ROOT / "scripts/protected_runtime_state_contract.py"
        spec = importlib.util.spec_from_file_location(
            "foreign_protected_runtime_state_contract",
            source,
        )
        assert spec is not None and spec.loader is not None
        foreign = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = foreign
        try:
            with self.assertRaises(ImportError):
                spec.loader.exec_module(foreign)
        finally:
            sys.modules.pop(spec.name, None)

        same_name_spec = importlib.util.spec_from_file_location(
            STATE.MODULE_NAME,
            source,
        )
        assert (
            same_name_spec is not None
            and same_name_spec.loader is not None
        )
        same_name_foreign = importlib.util.module_from_spec(same_name_spec)
        other_root = self.root / "installed-replacement"
        other_root.mkdir()
        other = RuntimeStateFixture(other_root)
        original_receipts = {
            path.name: path.read_bytes()
            for path in sealed.journal_path.iterdir()
        }
        other_handoff = other.handoff()
        other_journal = STATE._journal_path(
            other_handoff,
            other_handoff.document()["materialization"]["attempt_id"],
        )
        sys.modules[STATE.MODULE_NAME] = same_name_foreign
        try:
            with self.assertRaisesRegex(
                ImportError,
                "owner is already registered",
            ):
                same_name_spec.loader.exec_module(same_name_foreign)
            self.assertIsNone(
                same_name_foreign._OWNER_MODULE_BINDING
            )
            for action, runtime_config, handoff in (
                ("seal", other.runtime_config, other_handoff),
                ("recover", self.fixture.runtime_config, sealed.handoff),
            ):
                with self.subTest(replacement_action=action):
                    with self.assertRaisesRegex(
                        same_name_foreign.ProtectedRuntimeStateError,
                        "owner module is not registered",
                    ):
                        replacement_owner = (
                            same_name_foreign
                            .ProtectedRuntimeStateContractOwner
                            ._for_testing_with_clock(
                                runtime_config,
                                lambda: NOW,
                                _test_token=(
                                    same_name_foreign._TEST_OWNER_TOKEN
                                ),
                            )
                        )
                        getattr(replacement_owner, action)(handoff)
            with self.assertRaises(STATE.ProtectedRuntimeStateError):
                sealed.assert_current()
            self.assertFalse(other_journal.exists())
            self.assertEqual(
                {
                    path.name: path.read_bytes()
                    for path in sealed.journal_path.iterdir()
                },
                original_receipts,
            )
        finally:
            sys.modules[STATE.MODULE_NAME] = original_module
            other.close()
        self.assertIs(
            vars(HANDOFF)[STATE.OWNER_REGISTRATION_ATTRIBUTE],
            original_module,
        )
        sealed.assert_current()

        original_binding = STATE._OWNER_MODULE_BINDING
        original_types = tuple(
            getattr(STATE, name)
            for name in STATE._OWNER_ISSUED_TYPE_NAMES
        )
        with self.assertRaisesRegex(
            ImportError,
            "module has already executed",
        ):
            importlib.reload(STATE)
        self.assertIs(STATE._OWNER_MODULE_BINDING, original_binding)
        self.assertEqual(
            tuple(
                getattr(STATE, name)
                for name in STATE._OWNER_ISSUED_TYPE_NAMES
            ),
            original_types,
        )
        self.assertIs(
            vars(HANDOFF)[STATE.OWNER_REGISTRATION_ATTRIBUTE],
            original_module,
        )
        sealed.assert_current()

    def test_ready_initialization_failures_are_explicitly_recoverable(
        self,
    ) -> None:
        def new_fixture(label: str) -> RuntimeStateFixture:
            root = self.root / label
            root.mkdir()
            return RuntimeStateFixture(root)

        cases = ("clock", "zero-write", "short-write", "staged-fsync")
        for label in cases:
            with self.subTest(label=label):
                fixture = new_fixture(label)
                try:
                    handoff = fixture.handoff()
                    path = fixture.owner()._prepare(handoff)[-1]
                    owner = fixture.owner()
                    if label == "clock":
                        owner = (
                            STATE.ProtectedRuntimeStateContractOwner
                            ._for_testing_with_clock(
                                fixture.runtime_config,
                                lambda: (_ for _ in ()).throw(
                                    RuntimeError("clock failure")
                                ),
                                _test_token=STATE._TEST_OWNER_TOKEN,
                            )
                        )
                        with self.assertRaises(RuntimeError):
                            owner.seal(handoff)
                    elif label == "zero-write":
                        context = mock.patch.object(
                            STATE.os,
                            "write",
                            return_value=0,
                        )
                    elif label == "short-write":
                        real_write = os.write
                        calls = 0

                        def short_then_zero(
                            descriptor: int,
                            raw: bytes,
                        ) -> int:
                            nonlocal calls
                            calls += 1
                            if calls == 1:
                                return real_write(descriptor, raw[:7])
                            return 0

                        context = mock.patch.object(
                            STATE.os,
                            "write",
                            side_effect=short_then_zero,
                        )
                    else:
                        context = mock.patch.object(
                            STATE.os,
                            "fsync",
                            side_effect=OSError("staged fsync failure"),
                        )
                    if label != "clock":
                        with context:
                            with self.assertRaises(
                                STATE.ProtectedRuntimeStateError
                            ):
                                owner.seal(handoff)
                    self.assertFalse(path.exists())
                    recovered = fixture.owner().recover(handoff)
                    self.assertEqual(
                        recovered.current_receipt.document()["state"],
                        "ready",
                    )
                finally:
                    fixture.close()

    def test_post_link_fsync_failure_empty_recovery_and_partial_fail_closed(
        self,
    ) -> None:
        handoff = self.fixture.handoff()
        path = self.fixture.owner()._prepare(handoff)[-1]
        real_fsync = os.fsync
        calls = 0

        def fail_after_link(descriptor: int) -> None:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("journal fsync failure")
            real_fsync(descriptor)

        with mock.patch.object(
            STATE.os,
            "fsync",
            side_effect=fail_after_link,
        ):
            with self.assertRaises(STATE.ProtectedRuntimeStateError):
                self.fixture.owner().seal(handoff)
        self.assertTrue(
            (path / STATE.RECEIPT_BASENAMES[0]).is_file()
        )
        recovered = self.fixture.owner().recover(handoff)
        self.assertEqual(
            recovered.current_receipt.document()["state"],
            "ready",
        )

        other_root = self.root / "empty-and-partial"
        other_root.mkdir()
        other = RuntimeStateFixture(other_root)
        try:
            other_handoff = other.handoff()
            other_path = other.owner()._prepare(other_handoff)[-1]
            container = STATE._open_state_container(
                other_path,
                create=True,
            )
            try:
                os.mkdir(other_path.name, mode=0o700, dir_fd=container)
            finally:
                os.close(container)
            recovered_empty = other.owner().recover(other_handoff)
            self.assertEqual(
                recovered_empty.current_receipt.document()["state"],
                "ready",
            )
        finally:
            other.close()

        partial_root = self.root / "partial"
        partial_root.mkdir()
        partial = RuntimeStateFixture(partial_root)
        try:
            partial_handoff = partial.handoff()
            partial_path = partial.owner()._prepare(partial_handoff)[-1]
            container = STATE._open_state_container(
                partial_path,
                create=True,
            )
            try:
                os.mkdir(partial_path.name, mode=0o700, dir_fd=container)
            finally:
                os.close(container)
            partial_ready = partial_path / STATE.RECEIPT_BASENAMES[0]
            partial_ready.write_bytes(b"{")
            with self.assertRaises(STATE.ProtectedRuntimeStateError):
                partial.owner().recover(partial_handoff)
            self.assertEqual(partial_ready.read_bytes(), b"{")
        finally:
            partial.close()

    def test_concurrent_initial_seal_and_recovery_publish_one_ready(
        self,
    ) -> None:
        handoff = self.fixture.handoff()
        barrier = threading.Barrier(6)

        def initialize(index: int) -> object:
            barrier.wait()
            owner = self.fixture.owner()
            try:
                sealed = (
                    owner.seal(handoff)
                    if index == 0
                    else owner.recover(handoff)
                )
                return sealed.current_receipt.document()
            except STATE.ProtectedRuntimeStateError:
                return None

        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(initialize, range(6)))
        successes = [item for item in results if item is not None]
        self.assertGreaterEqual(len(successes), 1)
        self.assertTrue(
            all(item == successes[0] for item in successes)
        )
        recovered = self.fixture.owner().recover(handoff)
        self.assertEqual(
            recovered.current_receipt.document(),
            successes[0],
        )
        self.assertEqual(
            sorted(path.name for path in recovered.journal_path.iterdir()),
            [STATE.RECEIPT_BASENAMES[0]],
        )

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

    def test_actual_copied_named_package_imports_canonical_owner(
        self,
    ) -> None:
        installed = self.root / "installed-auto-g16-rtwin-pbs"
        installed.mkdir()
        for relative, source in SKILL_PACKAGE.package_files(
            ROOT,
            "auto-g16-rtwin-pbs",
        ).items():
            target = installed / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        script = textwrap.dedent(
            f"""
            import json
            import sys
            from pathlib import Path

            installed = Path({str(installed)!r})
            sys.path.insert(0, str(installed / "scripts"))
            import legacy_rtwin_pbs
            import protected_lifecycle_contract
            import protected_local_materialization
            import protected_legacy_effect_handoff
            import protected_runtime_state_contract as state

            print(json.dumps({{
                "module": state.__name__,
                "origin": str(Path(state.__file__).resolve()),
                "bound": (
                    state._OWNER_MODULE_BINDING.module is state
                    and state._owner_issued_type(
                        "ProtectedRuntimeStateContractOwner"
                    )
                    is state.ProtectedRuntimeStateContractOwner
                ),
            }}))
            """
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=installed,
            text=True,
            capture_output=True,
            env={
                **os.environ,
                "PYTHONDONTWRITEBYTECODE": "1",
                "AUTO_G16_RUNTIME_CONFIG": str(
                    TEST_TEMP_PARENT
                    / "auto-g16-copied-package-placeholder.json"
                ),
            },
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output["module"], STATE.MODULE_NAME)
        self.assertEqual(
            output["origin"],
            str(
                (
                    installed
                    / "scripts/protected_runtime_state_contract.py"
                ).resolve()
            ),
        )
        self.assertTrue(output["bound"])


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
