#!/usr/bin/env python3
"""Offline tests for the additive PR4 owner-consumer contract."""

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
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).parents[1]
ROOT_SCRIPTS = ROOT / "scripts"
SKILL_SCRIPTS = ROOT / "skills" / "auto-g16-rtwin-pbs" / "scripts"
TEMP_PARENT = Path(tempfile.gettempdir()).resolve()
if TEMP_PARENT == ROOT or ROOT in TEMP_PARENT.parents:
    raise RuntimeError("owner-consumer tests require a system temporary root")
os.environ["AUTO_G16_RUNTIME_CONFIG"] = str(
    TEMP_PARENT / "auto-g16-owner-consumer-placeholder-absent.json"
)
sys.path.insert(0, str(ROOT_SCRIPTS))
sys.path.insert(0, str(SKILL_SCRIPTS))

import legacy_rtwin_pbs as LEGACY  # noqa: E402
from tests.test_protected_runtime_state_contract import (  # noqa: E402
    RuntimeStateFixture,
)
import protected_runtime_state_contract as STATE  # noqa: E402
import protected_owner_consumer_contract as CONSUMER  # noqa: E402
import skill_package as SKILL_PACKAGE  # noqa: E402


class ProtectedOwnerConsumerContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(
            prefix="auto-g16-protected-owner-consumer-",
            dir=TEMP_PARENT,
        )
        self.root = Path(self.temporary.name).resolve()
        self.fixture = RuntimeStateFixture(self.root)

    def tearDown(self) -> None:
        self.fixture.close()
        self.temporary.cleanup()

    def runtime(self) -> STATE.SealedProtectedRuntimeStateContract:
        return self.fixture.owner().seal(self.fixture.handoff())

    def prepared(
        self,
    ) -> CONSUMER.SealedProtectedOwnerConsumerContract:
        return (
            CONSUMER.ProtectedOwnerConsumerContractOwner.production()
            .prepare_once(self.runtime())
        )

    def foreign_identical_consumer_module(self) -> object:
        canonical = sys.modules[CONSUMER.MODULE_NAME]
        runtime_module = CONSUMER._RUNTIME_BINDING.module
        registration = CONSUMER._REGISTRATION_ATTRIBUTE
        registered = getattr(runtime_module, registration)
        source = ROOT / "scripts/protected_owner_consumer_contract.py"
        spec = importlib.util.spec_from_file_location(
            CONSUMER.MODULE_NAME,
            source,
        )
        assert spec is not None and spec.loader is not None
        foreign = importlib.util.module_from_spec(spec)
        delattr(runtime_module, registration)
        sys.modules[CONSUMER.MODULE_NAME] = foreign
        try:
            spec.loader.exec_module(foreign)
        finally:
            sys.modules[CONSUMER.MODULE_NAME] = canonical
            setattr(runtime_module, registration, registered)
        return foreign

    def test_exact_upload_bytes_authority_matrix_and_no_effects(self) -> None:
        runtime = self.runtime()
        predecessor_dir = runtime.handoff.materialization.local_dir
        predecessor_before = {
            path.name: path.read_bytes()
            for path in predecessor_dir.iterdir()
        }
        with (
            mock.patch.object(
                LEGACY, "_legacy_effect_plan_from_transaction"
            ) as effect_plan,
            mock.patch.object(
                LEGACY, "_legacy_raw_effect_owner_from_plan"
            ) as raw_owner,
            mock.patch.object(
                LEGACY, "_legacy_effect_owner_lifecycle_from_owner"
            ) as lifecycle,
            mock.patch.object(LEGACY, "run") as runner,
            mock.patch.object(
                LEGACY.LegacyTransportAdapter, "invoke_reserved_once"
            ) as adapter,
        ):
            sealed = (
                CONSUMER.ProtectedOwnerConsumerContractOwner.production()
                .prepare_once(runtime)
            )
            plan_inputs = sealed.claim_effect_plan_inputs_once()
        for forbidden in (
            effect_plan,
            raw_owner,
            lifecycle,
            runner,
            adapter,
        ):
            forbidden.assert_not_called()
        self.assertEqual(
            predecessor_before,
            {
                path.name: path.read_bytes()
                for path in predecessor_dir.iterdir()
            },
        )
        document = sealed.document()
        self.assertEqual(document["scope"], CONSUMER.SCOPE)
        self.assertEqual(document["policy"], CONSUMER.POLICY)
        self.assertFalse(
            document["intent"]["protected_authority"][
                "legacy_execution_batch_reservation_present"
            ]
        )
        self.assertFalse(
            document["intent"]["protected_authority"][
                "legacy_ledger_is_authority"
            ]
        )
        names = [
            item["relative_name"]
            for item in document["upload_bundle"]["artifacts"]
        ]
        predecessor_artifacts = runtime.handoff.materialization.document()[
            "materialized_files"
        ]
        expected_names = [
            item["relative_name"]
            for item in predecessor_artifacts
            if item["role"] != "checksums_manifest"
        ] + [CONSUMER.INTENT_BASENAME, CONSUMER.CHECKSUM_BASENAME]
        self.assertEqual(names, expected_names)
        self.assertEqual(
            [path.name for path in plan_inputs.files],
            expected_names,
        )
        checksums = (
            sealed.upload_path / CONSUMER.CHECKSUM_BASENAME
        ).read_text(encoding="utf-8")
        expected_lines = "".join(
            f"{item['sha256']}  {item['relative_name']}\n"
            for item in document["upload_bundle"]["artifacts"][:-1]
        )
        self.assertEqual(checksums, expected_lines)
        self.assertNotIn("checksums.sha256\n", checksums)
        self.assertEqual(
            runtime.current_receipt.document()["state"],
            "effect_started_outcome_uncertain",
        )
        sealed.assert_current()

    def test_order_is_bytes_then_consumption_then_uncertain(self) -> None:
        runtime = self.runtime()
        events: list[str] = []
        original_materialize = CONSUMER._materialize_bundle
        original_consume = runtime.consume_for_effect_once
        original_boundary = runtime.prepare_effect_boundary_once

        def materialize(value: object) -> object:
            result = original_materialize(value)
            events.append("bundle_fsync_and_replay")
            return result

        def consume() -> object:
            events.append("consume_not_started")
            return original_consume()

        def boundary(receipt: object) -> object:
            events.append("persist_uncertain")
            return original_boundary(receipt)

        with (
            mock.patch.object(
                CONSUMER,
                "_materialize_bundle",
                side_effect=materialize,
            ),
            mock.patch.object(
                STATE.SealedProtectedRuntimeStateContract,
                "consume_for_effect_once",
                autospec=True,
                side_effect=lambda _self: consume(),
            ),
            mock.patch.object(
                STATE.SealedProtectedRuntimeStateContract,
                "prepare_effect_boundary_once",
                autospec=True,
                side_effect=lambda _self, receipt: boundary(receipt),
            ),
        ):
            sealed = (
                CONSUMER.ProtectedOwnerConsumerContractOwner.production()
                .prepare_once(runtime)
            )
        self.assertEqual(
            events,
            [
                "bundle_fsync_and_replay",
                "consume_not_started",
                "persist_uncertain",
            ],
        )
        sealed.assert_current()

    def test_copy_pickle_mutation_and_hostile_structures_fail_closed(self) -> None:
        sealed = self.prepared()
        inputs = sealed.claim_effect_plan_inputs_once()
        for value in (sealed, inputs):
            with self.subTest(value=type(value).__name__):
                with self.assertRaises(TypeError):
                    copy.copy(value)
                with self.assertRaises(TypeError):
                    copy.deepcopy(value)
                with self.assertRaises(TypeError):
                    pickle.dumps(value)
        contract = sealed.document()
        for field in CONSUMER.SCOPE:
            changed = copy.deepcopy(contract)
            changed["scope"][field] = int(CONSUMER.SCOPE[field])
            with self.assertRaises(CONSUMER.ProtectedOwnerConsumerError):
                CONSUMER.validate_protected_owner_consumer_contract(changed)
        changed = sealed.document()
        changed["upload_bundle"]["artifacts"][-2]["relative_name"] = (
            "forged-intent.json"
        )
        changed["upload_bundle"]["expected_bindings_sha256"] = (
            CONSUMER.digest(
                [
                    (item["relative_name"], item["sha256"])
                    for item in changed["upload_bundle"]["artifacts"]
                ]
            )
        )
        with self.assertRaises(CONSUMER.ProtectedOwnerConsumerError):
            CONSUMER.validate_protected_owner_consumer_contract(changed)

        class Hostile(dict):
            def __eq__(self, other: object) -> bool:
                raise AssertionError("hostile equality must not run")

        with self.assertRaises(CONSUMER.ProtectedOwnerConsumerError):
            CONSUMER.validate_protected_owner_consumer_contract(
                Hostile(sealed.document())
            )

    def test_single_claim_and_concurrent_owner_consumption(self) -> None:
        sealed = self.prepared()
        barrier = threading.Barrier(8)

        def claim(_: int) -> object:
            barrier.wait()
            try:
                return sealed.claim_effect_plan_inputs_once()
            except CONSUMER.ProtectedOwnerConsumerError:
                return None

        with ThreadPoolExecutor(max_workers=8) as pool:
            claims = list(pool.map(claim, range(8)))
        self.assertEqual(sum(item is not None for item in claims), 1)

        other_root = self.root / "concurrent"
        other_root.mkdir()
        other_fixture = RuntimeStateFixture(other_root)
        try:
            runtime = other_fixture.owner().seal(other_fixture.handoff())
            owner_barrier = threading.Barrier(6)

            def prepare(_: int) -> object:
                owner_barrier.wait()
                try:
                    return (
                        CONSUMER.ProtectedOwnerConsumerContractOwner
                        .production()
                        .prepare_once(runtime)
                    )
                except (
                    CONSUMER.ProtectedOwnerConsumerError,
                    STATE.ProtectedRuntimeStateError,
                ):
                    return None

            with ThreadPoolExecutor(max_workers=6) as pool:
                results = list(pool.map(prepare, range(6)))
            self.assertEqual(sum(item is not None for item in results), 1)
            self.assertEqual(
                runtime.current_receipt.document()["state"],
                "effect_started_outcome_uncertain",
            )
        finally:
            other_fixture.close()

    def test_complete_pre_effect_recovery_and_partial_fail_closed(self) -> None:
        runtime = self.runtime()
        path, identities, portable = CONSUMER._materialize_bundle(runtime)
        recovered = (
            CONSUMER.ProtectedOwnerConsumerContractOwner.production()
            .recover_before_effect_once(runtime)
        )
        self.assertEqual(recovered.upload_path, path)
        self.assertEqual(
            runtime.current_receipt.document()["state"],
            "effect_started_outcome_uncertain",
        )
        recovered.assert_current()
        self.assertEqual(set(identities), {item["relative_name"] for item in portable})

        other_root = self.root / "partial"
        other_root.mkdir()
        other_fixture = RuntimeStateFixture(other_root)
        try:
            other_runtime = other_fixture.owner().seal(
                other_fixture.handoff()
            )
            partial = CONSUMER._consumer_path(other_runtime)
            partial.parent.mkdir(mode=0o700)
            partial.mkdir(mode=0o700)
            (partial / "partial").write_bytes(b"x")
            ready_before = other_runtime.current_receipt.document()
            with self.assertRaises(CONSUMER.ProtectedOwnerConsumerError):
                (
                    CONSUMER.ProtectedOwnerConsumerContractOwner
                    .production()
                    .recover_before_effect_once(other_runtime)
                )
            self.assertEqual(
                other_runtime.current_receipt.document(),
                ready_before,
            )
            self.assertEqual((partial / "partial").read_bytes(), b"x")
        finally:
            other_fixture.close()

    def test_uncertain_recovery_exposes_read_only_inputs_only(self) -> None:
        sealed = self.prepared()
        runtime = sealed.runtime_state
        inputs = (
            CONSUMER.ProtectedOwnerConsumerContractOwner.production()
            .read_only_reconciliation_inputs(runtime)
        )
        self.assertEqual(
            inputs,
            sealed.read_only_reconciliation_inputs(),
        )
        self.assertFalse(inputs["observation_acquired"])
        self.assertFalse(inputs["remote_read_performed"])
        self.assertFalse(inputs["automatic_effect_authorized"])
        self.assertFalse(inputs["automatic_retry"])
        with self.assertRaises(CONSUMER.ProtectedOwnerConsumerError):
            (
                CONSUMER.ProtectedOwnerConsumerContractOwner.production()
                .recover_before_effect_once(runtime)
            )

    def test_runtime_legacy_module_and_class_identity_fail_closed(self) -> None:
        runtime = self.runtime()
        original_runtime = sys.modules[CONSUMER.RUNTIME_MODULE_NAME]
        sys.modules[CONSUMER.RUNTIME_MODULE_NAME] = mock.Mock()
        try:
            with self.assertRaises(CONSUMER.ProtectedOwnerConsumerError):
                (
                    CONSUMER.ProtectedOwnerConsumerContractOwner.production()
                    .prepare_once(runtime)
                )
        finally:
            sys.modules[CONSUMER.RUNTIME_MODULE_NAME] = original_runtime
        self.assertEqual(
            runtime.current_receipt.document()["state"],
            "ready",
        )
        self.assertFalse(CONSUMER._consumer_path(runtime).exists())

        original_plan = LEGACY._LegacyEffectPlan
        LEGACY._LegacyEffectPlan = mock.Mock()
        try:
            with self.assertRaises(CONSUMER.ProtectedOwnerConsumerError):
                (
                    CONSUMER.ProtectedOwnerConsumerContractOwner.production()
                    .prepare_once(runtime)
                )
        finally:
            LEGACY._LegacyEffectPlan = original_plan
        self.assertEqual(
            runtime.current_receipt.document()["state"],
            "ready",
        )

        source = ROOT / "scripts/protected_owner_consumer_contract.py"
        spec = importlib.util.spec_from_file_location(
            "foreign_protected_owner_consumer_contract",
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

    def test_owner_created_before_foreign_identical_consumer_rejects_zero_change(
        self,
    ) -> None:
        runtime = self.runtime()
        owner_type = CONSUMER.ProtectedOwnerConsumerContractOwner
        owner = owner_type.production()
        before = runtime.current_receipt.document()
        bundle = CONSUMER._consumer_path(runtime)
        foreign = self.foreign_identical_consumer_module()
        canonical = sys.modules[CONSUMER.MODULE_NAME]
        self.assertIsNot(
            foreign.ProtectedOwnerConsumerContractOwner,
            owner_type,
        )
        self.assertIsNot(
            foreign.SealedProtectedOwnerConsumerContract,
            CONSUMER.SealedProtectedOwnerConsumerContract,
        )
        self.assertIsNot(
            foreign.ProtectedLegacyEffectPlanInputs,
            CONSUMER.ProtectedLegacyEffectPlanInputs,
        )

        sys.modules[CONSUMER.MODULE_NAME] = foreign
        try:
            with self.assertRaisesRegex(
                CONSUMER.ProtectedOwnerConsumerError,
                "owner module or class identity differs",
            ):
                owner.prepare_once(runtime)
        finally:
            sys.modules[CONSUMER.MODULE_NAME] = canonical
        self.assertEqual(runtime.current_receipt.document(), before)
        self.assertFalse(bundle.exists())
        self.assertFalse(owner._used)

        for attribute in (
            "ProtectedOwnerConsumerContractOwner",
            "SealedProtectedOwnerConsumerContract",
            "ProtectedLegacyEffectPlanInputs",
        ):
            with self.subTest(attribute=attribute):
                exact = getattr(CONSUMER, attribute)
                candidate = owner_type.production()
                setattr(CONSUMER, attribute, getattr(foreign, attribute))
                try:
                    with self.assertRaisesRegex(
                        CONSUMER.ProtectedOwnerConsumerError,
                        "owner module or class identity differs",
                    ):
                        candidate.prepare_once(runtime)
                finally:
                    setattr(CONSUMER, attribute, exact)
                self.assertEqual(runtime.current_receipt.document(), before)
                self.assertFalse(bundle.exists())
                self.assertFalse(candidate._used)

    def test_module_lock_closes_identity_check_to_first_mutation_window(
        self,
    ) -> None:
        runtime = self.runtime()
        owner = CONSUMER.ProtectedOwnerConsumerContractOwner.production()
        canonical = sys.modules[CONSUMER.MODULE_NAME]
        foreign = self.foreign_identical_consumer_module()
        identity_checked = threading.Event()
        replacement_attempted = threading.Event()
        replacement_completed = threading.Event()
        original_assert = CONSUMER._assert_bindings_current_locked
        original_materialize = CONSUMER._materialize_bundle

        def checked() -> None:
            original_assert()
            identity_checked.set()

        def replace_cache() -> None:
            replacement_attempted.set()
            with CONSUMER._MODULE_LOCK:
                sys.modules[CONSUMER.MODULE_NAME] = foreign
                replacement_completed.set()

        def materialize_guarded(
            candidate: object,
        ) -> tuple[Path, dict[str, object], list[dict[str, object]]]:
            self.assertTrue(replacement_attempted.wait(timeout=5))
            self.assertFalse(replacement_completed.is_set())
            self.assertIs(sys.modules[CONSUMER.MODULE_NAME], canonical)
            return original_materialize(candidate)

        try:
            with (
                mock.patch.object(
                    CONSUMER,
                    "_assert_bindings_current_locked",
                    side_effect=checked,
                ),
                mock.patch.object(
                    CONSUMER,
                    "_materialize_bundle",
                    side_effect=materialize_guarded,
                ),
                ThreadPoolExecutor(max_workers=2) as pool,
            ):
                prepared = pool.submit(owner.prepare_once, runtime)
                self.assertTrue(identity_checked.wait(timeout=5))
                replacement = pool.submit(replace_cache)
                sealed = prepared.result(timeout=30)
                replacement.result(timeout=30)
        finally:
            sys.modules[CONSUMER.MODULE_NAME] = canonical
        self.assertTrue(replacement_completed.is_set())
        self.assertEqual(
            runtime.current_receipt.document()["state"],
            "effect_started_outcome_uncertain",
        )
        sealed.assert_current()

    def test_materialized_mutation_rejects_claim_before_any_effect(self) -> None:
        sealed = self.prepared()
        target = sealed.upload_path / sealed.document()["upload_bundle"][
            "artifacts"
        ][0]["relative_name"]
        raw = target.read_bytes()
        target.unlink()
        target.write_bytes(raw)
        with (
            mock.patch.object(
                LEGACY, "_legacy_effect_plan_from_transaction"
            ) as effect_plan,
            mock.patch.object(LEGACY, "run") as runner,
        ):
            with self.assertRaises(CONSUMER.ProtectedOwnerConsumerError):
                sealed.claim_effect_plan_inputs_once()
        effect_plan.assert_not_called()
        runner.assert_not_called()

    def test_source_has_no_effect_transport_or_adapter_call(self) -> None:
        source_path = ROOT / "scripts/protected_owner_consumer_contract.py"
        source = source_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
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
        for forbidden in (
            "_legacy_effect_plan_from_transaction(",
            "_legacy_raw_effect_owner_from_plan(",
            "invoke_reserved_once(",
            "qsub(",
            "qstat(",
            "qdel(",
        ):
            self.assertNotIn(forbidden, source)

    def test_frozen_predecessors_and_actual_named_package(self) -> None:
        fixture = json.loads(
            (
                ROOT
                / "tests/fixtures/rtwin_pbs/"
                "protected_owner_consumer_contract.json"
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
                ROOT / "skills/auto-g16-rtwin-pbs/deployment-package.json"
            ).read_text(encoding="utf-8")
        )
        self.assertIn(
            "scripts/protected_owner_consumer_contract.py",
            {item["source"] for item in package["include"]},
        )
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
            import protected_runtime_state_contract
            import protected_owner_consumer_contract as consumer

            print(json.dumps({{
                "module": consumer.__name__,
                "origin": str(Path(consumer.__file__).resolve()),
                "runtime_bound": (
                    consumer._RUNTIME_BINDING.module
                    is protected_runtime_state_contract
                ),
                "legacy_bound": (
                    consumer._LEGACY_BINDING.module is legacy_rtwin_pbs
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
                    TEMP_PARENT
                    / "auto-g16-owner-consumer-installed-placeholder.json"
                ),
            },
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output["module"], CONSUMER.MODULE_NAME)
        self.assertTrue(output["runtime_bound"])
        self.assertTrue(output["legacy_bound"])


if __name__ == "__main__":
    unittest.main()
