#!/usr/bin/env python3
"""Offline tests for the PR4N non-executable typed handoff."""

from __future__ import annotations

import builtins
import copy
import dataclasses
import hashlib
import importlib.util
import inspect
import json
import os
import pickle
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).parents[1]
ROOT_SCRIPTS = ROOT / "scripts"
SKILL_SCRIPTS = ROOT / "skills" / "auto-g16-rtwin-pbs" / "scripts"
TEST_TEMP_PARENT = Path(tempfile.gettempdir()).resolve()
if TEST_TEMP_PARENT == ROOT or ROOT in TEST_TEMP_PARENT.parents:
    raise RuntimeError("PR4N tests require a system temporary root")
RUNTIME_PLACEHOLDER = (
    TEST_TEMP_PARENT
    / "auto-g16-pr4n-runtime-config-does-not-exist.json"
)
os.environ["AUTO_G16_RUNTIME_CONFIG"] = str(RUNTIME_PLACEHOLDER)
sys.path.insert(0, str(ROOT_SCRIPTS))
sys.path.insert(0, str(SKILL_SCRIPTS))

import execution_facade as FACADE  # noqa: E402
import legacy_rtwin_pbs as LEGACY  # noqa: E402
import skill_package  # noqa: E402
from tests import test_protected_local_materialization as SUPPORT  # noqa: E402
from tests import test_protected_submit_contract as PR4D_SUPPORT  # noqa: E402
import protected_legacy_effect_handoff as HANDOFF  # noqa: E402


FIXTURE_PATH = (
    ROOT
    / "tests/fixtures/rtwin_pbs/"
    "protected_legacy_effect_handoff.json"
)
FIXED_CONSTRAINT_SUCCESSOR_PATH = (
    ROOT
    / "tests/fixtures/rtwin_pbs/"
    "legacy_rtwin_pbs_fixed_constraint_successor.json"
)


class ProtectedLegacyEffectHandoffTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(
            prefix="auto-g16-protected-legacy-handoff-",
            dir=TEST_TEMP_PARENT,
        )
        self.root = Path(self.temporary.name).resolve()
        self.fixture = SUPPORT.ProtectedLocalMaterializationFixture(
            self.root
        )

    def tearDown(self) -> None:
        self.fixture.close()
        self.temporary.cleanup()

    def materialize(self) -> object:
        with FACADE._exact_protected_local_materialization() as owner_module:
            owner = (
                owner_module.ProtectedLocalMaterializationOwner
                ._for_testing_with_clock(
                    self.fixture.state_root,
                    lambda: PR4D_SUPPORT.parse_utc(PR4D_SUPPORT.NOW),
                    _test_token=owner_module._TEST_OWNER_TOKEN,
                )
            )
            return owner.materialize_once(self.fixture.evidence)

    def handoff(self) -> object:
        return FACADE.seal_protected_legacy_effect_handoff(
            materialization=self.materialize()
        )

    def test_exact_handoff_binds_pr4l_and_pr4m_without_effects(self) -> None:
        materialization = self.materialize()
        with FACADE._exact_legacy_implementation() as legacy:
            registry_sizes = (
                len(legacy._LEGACY_EFFECT_PLAN_BINDINGS),
                len(legacy._LEGACY_EFFECT_OWNER_BINDINGS),
            )
            with (
                mock.patch.object(
                    legacy,
                    "_legacy_effect_plan_from_transaction",
                ) as effect_plan,
                mock.patch.object(
                    legacy,
                    "_legacy_raw_effect_owner_from_plan",
                ) as raw_owner,
                mock.patch.object(
                    legacy,
                    "_legacy_transaction_once",
                ) as transaction,
                mock.patch.object(legacy, "run") as runner,
                mock.patch.object(
                    legacy.LegacyTransportAdapter,
                    "invoke_reserved_once",
                ) as adapter,
            ):
                sealed = FACADE.seal_protected_legacy_effect_handoff(
                    materialization=materialization
                )
            effect_plan.assert_not_called()
            raw_owner.assert_not_called()
            transaction.assert_not_called()
            runner.assert_not_called()
            adapter.assert_not_called()
            self.assertEqual(
                registry_sizes,
                (
                    len(legacy._LEGACY_EFFECT_PLAN_BINDINGS),
                    len(legacy._LEGACY_EFFECT_OWNER_BINDINGS),
                ),
            )
        sealed.assert_owner_sealed()
        sealed.assert_current()
        document = sealed.document()
        self.assertEqual(document["schema"], HANDOFF.SCHEMA)
        self.assertEqual(document["scope"], HANDOFF.SCOPE)
        self.assertEqual(document["status"], HANDOFF.STATUS)
        self.assertEqual(document["policy"], HANDOFF.POLICY)
        self.assertEqual(
            document["materialization"]["materialization_id"],
            materialization.materialization_id,
        )
        self.assertFalse(document["status"]["effects_performed"])
        self.assertFalse(document["status"]["adapter_connected"])
        self.assertFalse(document["status"]["qsub_invocation_started"])
        self.assertFalse(
            document["status"]["runtime_transport_binding_complete"]
        )

    def test_facade_accepts_only_the_bound_materialization_type(self) -> None:
        for value in ({}, object(), self.materialize().document()):
            with self.subTest(value=type(value).__name__):
                with self.assertRaises(TypeError):
                    FACADE.seal_protected_legacy_effect_handoff(
                        materialization=value
                    )

        foreign_name = "foreign_protected_local_materialization"
        path = ROOT / "scripts/protected_local_materialization.py"
        spec = importlib.util.spec_from_file_location(foreign_name, path)
        assert spec is not None and spec.loader is not None
        foreign = importlib.util.module_from_spec(spec)
        sys.modules[foreign_name] = foreign
        try:
            spec.loader.exec_module(foreign)
            foreign_root = self.root / "foreign"
            foreign_root.mkdir()
            foreign_fixture = SUPPORT.ProtectedLocalMaterializationFixture(
                foreign_root
            )
            try:
                owner = (
                    foreign.ProtectedLocalMaterializationOwner
                    ._for_testing_with_clock(
                        foreign_fixture.state_root,
                        lambda: PR4D_SUPPORT.parse_utc(PR4D_SUPPORT.NOW),
                        _test_token=foreign._TEST_OWNER_TOKEN,
                    )
                )
                foreign_materialization = owner.materialize_once(
                    foreign_fixture.evidence
                )
                with self.assertRaises(TypeError):
                    FACADE.seal_protected_legacy_effect_handoff(
                        materialization=foreign_materialization
                    )
            finally:
                foreign_fixture.close()
        finally:
            sys.modules.pop(foreign_name, None)

    def test_three_local_loaders_compile_one_snapshot_and_recheck_file(
        self,
    ) -> None:
        expected = {
            str(FACADE._protected_local_materialization_path()): (
                FACADE._protected_local_materialization_path().read_bytes()
            ),
            str(FACADE._legacy_implementation_path()): (
                FACADE._legacy_implementation_path().read_bytes()
            ),
            str(FACADE._protected_legacy_handoff_path()): (
                FACADE._protected_legacy_handoff_path().read_bytes()
            ),
        }
        compiled: dict[str, bytes] = {}
        original_compile = builtins.compile
        previous_materialization = (
            FACADE._PROTECTED_LOCAL_MATERIALIZATION_BOUND_MODULE,
            FACADE._PROTECTED_LOCAL_MATERIALIZATION_SOURCE_SHA256,
        )
        previous_legacy = (
            FACADE._LEGACY_IMPLEMENTATION_BOUND_MODULE,
            FACADE._LEGACY_IMPLEMENTATION_SOURCE_SHA256,
        )

        def capture_compile(
            source: object,
            filename: str,
            mode: str,
            *args: object,
            **kwargs: object,
        ) -> object:
            if filename in expected:
                self.assertIs(type(source), bytes)
                compiled[filename] = source
            return original_compile(
                source,
                filename,
                mode,
                *args,
                **kwargs,
            )

        FACADE._PROTECTED_LOCAL_MATERIALIZATION_BOUND_MODULE = None
        FACADE._PROTECTED_LOCAL_MATERIALIZATION_SOURCE_SHA256 = None
        FACADE._LEGACY_IMPLEMENTATION_BOUND_MODULE = None
        FACADE._LEGACY_IMPLEMENTATION_SOURCE_SHA256 = None
        try:
            with mock.patch("builtins.compile", side_effect=capture_compile):
                with (
                    FACADE._exact_protected_local_materialization(),
                    FACADE._exact_legacy_implementation(),
                    FACADE._exact_protected_legacy_handoff(),
                ):
                    pass
        finally:
            (
                FACADE._PROTECTED_LOCAL_MATERIALIZATION_BOUND_MODULE,
                FACADE._PROTECTED_LOCAL_MATERIALIZATION_SOURCE_SHA256,
            ) = previous_materialization
            (
                FACADE._LEGACY_IMPLEMENTATION_BOUND_MODULE,
                FACADE._LEGACY_IMPLEMENTATION_SOURCE_SHA256,
            ) = previous_legacy
        self.assertEqual(compiled, expected)

        changing_path = self.root / "changing_local_owner.py"
        changing_path.write_text(
            "from pathlib import Path\n"
            "Path(__file__).write_text('VALUE = 2\\n', encoding='utf-8')\n"
            "VALUE = 1\n",
            encoding="utf-8",
        )
        changing_name = "auto_g16_pr4n_changing_local_owner"
        try:
            with self.assertRaisesRegex(
                ImportError,
                "changed during exact load",
            ):
                FACADE._load_exact_source_module(
                    changing_name,
                    changing_path,
                    label="changing local owner",
                )
        finally:
            sys.modules.pop(changing_name, None)

        document = self.handoff().document()
        for projection, expected in (
            (document["scope"], HANDOFF.SCOPE),
            (document["status"], HANDOFF.STATUS),
            (document["policy"], HANDOFF.POLICY),
        ):
            for field, expected_value in expected.items():
                if expected_value is False:
                    self.assertIs(projection[field], False)
        self.assertNotIn(
            True,
            document["lifecycle_readiness"]["status"].values(),
        )
        self.assertNotIn(
            True,
            document["lifecycle_readiness"]["policy"].values(),
        )

    def test_handoff_owner_is_single_use_under_concurrency(self) -> None:
        materialization = self.materialize()
        with (
            FACADE._exact_protected_local_materialization(),
            FACADE._exact_legacy_implementation(),
            FACADE._exact_protected_legacy_handoff() as module,
        ):
            owner = module.ProtectedLegacyEffectHandoffOwner.production()
            start = threading.Barrier(3)

            def seal() -> tuple[str, object]:
                start.wait(timeout=5)
                try:
                    return ("sealed", owner.seal(materialization))
                except BaseException as exc:
                    return ("error", exc)

            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(seal) for _ in range(2)]
                start.wait(timeout=5)
                outcomes = [future.result(timeout=30) for future in futures]
        self.assertEqual(
            sorted(kind for kind, _value in outcomes),
            ["error", "sealed"],
        )
        sealed = next(
            value for kind, value in outcomes if kind == "sealed"
        )
        failure = next(
            value for kind, value in outcomes if kind == "error"
        )
        self.assertIsInstance(failure, ValueError)
        self.assertIn(
            "single-use",
            str(failure),
        )
        sealed.assert_current()

    def test_sealed_handoff_rejects_copy_pickle_and_file_drift(self) -> None:
        sealed = self.handoff()
        with self.assertRaises(TypeError):
            copy.copy(sealed)
        with self.assertRaises(TypeError):
            copy.deepcopy(sealed)
        with self.assertRaises(TypeError):
            pickle.dumps(sealed)
        sealed.assert_current()
        artifact = sealed.materialization.local_dir / (
            sealed.materialization.document()["stage_plan"]["artifacts"][0][
                "relative_name"
            ]
        )
        original = artifact.read_bytes()
        artifact.write_bytes(original + b"drift")
        with self.assertRaises(ValueError):
            sealed.assert_current()

    def test_sealed_handoff_rejects_owner_source_snapshot_drift(self) -> None:
        sealed = self.handoff()
        globals_dict = type(sealed).assert_current.__globals__
        original = globals_dict["_stable_owner_snapshot"]
        handoff_path = globals_dict["_handoff_owner_path"]()
        expected = globals_dict["_HANDOFF_OWNER_SNAPSHOT"]

        def drift(path: Path) -> object:
            snapshot = original(path)
            if path == handoff_path:
                return dataclasses.replace(
                    snapshot,
                    sha256="f" * 64,
                )
            return snapshot

        globals_dict["_stable_owner_snapshot"] = drift
        try:
            with self.assertRaisesRegex(
                ValueError,
                "handoff owner identity differs",
            ):
                sealed.assert_current()
        finally:
            globals_dict["_stable_owner_snapshot"] = original
        self.assertEqual(original(handoff_path), expected)
        sealed.assert_current()

    def test_validator_rejects_self_rehashed_flag_and_binding_splices(
        self,
    ) -> None:
        document = self.handoff().document()
        cases = []
        changed = copy.deepcopy(document)
        changed["status"]["effects_performed"] = True
        cases.append(changed)
        changed = copy.deepcopy(document)
        changed["scope"]["create_raw_effect_owner"] = True
        cases.append(changed)
        changed = copy.deepcopy(document)
        changed["policy"]["automatic_retry"] = True
        cases.append(changed)
        changed = copy.deepcopy(document)
        changed["owner_bindings"]["legacy_owner_source_sha256"] = "f" * 64
        changed["handoff_payload_sha256"] = HANDOFF._payload_sha256(changed)
        changed["handoff_id"] = (
            "protected-legacy-effect-handoff-"
            + HANDOFF.digest(
                {
                    "schema": (
                        "auto-g16-protected-legacy-effect-handoff-id/1"
                    ),
                    "materialization_id": changed["materialization"][
                        "materialization_id"
                    ],
                    "witness_payload_sha256": changed[
                        "lifecycle_readiness"
                    ]["witness_payload_sha256"],
                    "handoff_payload_sha256": changed[
                        "handoff_payload_sha256"
                    ],
                }
            )
        )
        cases.append(changed)
        for index, changed in enumerate(cases):
            with self.subTest(index=index):
                if index < 3:
                    with self.assertRaises(
                        HANDOFF.ProtectedLegacyEffectHandoffError
                    ):
                        HANDOFF.validate_protected_legacy_effect_handoff(
                            changed
                        )
                else:
                    normalized = (
                        HANDOFF.validate_protected_legacy_effect_handoff(
                            changed
                        )
                    )
                    self.assertEqual(normalized, changed)
                    self.assertNotEqual(normalized, document)

    def test_facade_surface_is_seal_only_and_old_adapter_is_unchanged(
        self,
    ) -> None:
        self.assertEqual(
            tuple(
                inspect.signature(
                    FACADE.seal_protected_legacy_effect_handoff
                ).parameters
            ),
            ("materialization",),
        )
        source = inspect.getsource(
            FACADE.seal_protected_legacy_effect_handoff
        )
        self.assertIn("_exact_protected_legacy_handoff()", source)
        self.assertIn("owner.seal(materialization)", source)
        self.assertNotIn("integrate_successor_once", source)
        self.assertNotIn("invoke_reserved_once", source)
        adapter_source = inspect.getsource(
            LEGACY.LegacyTransportAdapter.invoke_reserved_once
        )
        self.assertIn("actual adapter invocation", adapter_source)

    def test_legacy_witness_is_read_only_and_module_issued(self) -> None:
        with FACADE._exact_legacy_implementation() as legacy:
            before = (
                len(legacy._LEGACY_EFFECT_PLAN_BINDINGS),
                len(legacy._LEGACY_EFFECT_OWNER_BINDINGS),
            )
            with mock.patch.object(legacy, "run") as runner:
                witness = (
                    legacy
                    ._issue_legacy_effect_lifecycle_readiness_witness()
                )
            runner.assert_not_called()
            self.assertEqual(
                before,
                (
                    len(legacy._LEGACY_EFFECT_PLAN_BINDINGS),
                    len(legacy._LEGACY_EFFECT_OWNER_BINDINGS),
                ),
            )
            witness.assert_owner_sealed()
            with self.assertRaises(TypeError):
                legacy._LegacyEffectLifecycleReadinessWitness()
            with self.assertRaises(TypeError):
                pickle.dumps(witness)
            self.assertFalse(
                witness.document()["status"]["raw_effect_owner_created"]
            )

    def test_package_and_git_free_owner_relocation(self) -> None:
        package = skill_package.package_files(
            ROOT,
            "auto-g16-rtwin-pbs",
        )
        expected = {
            Path("scripts/protected_legacy_effect_handoff.py"): (
                ROOT / "scripts/protected_legacy_effect_handoff.py"
            ),
            Path(
                "contracts/execution/"
                "protected-legacy-effect-handoff.schema.json"
            ): (
                ROOT
                / "contracts/execution/"
                "protected-legacy-effect-handoff.schema.json"
            ),
            Path("references/protected-legacy-effect-handoff.md"): (
                ROOT
                / "skills/auto-g16-rtwin-pbs/references/"
                "protected-legacy-effect-handoff.md"
            ),
        }
        for target, source in expected.items():
            self.assertEqual(package[target], source)
        installed = self.root / "installed"
        for target, source in package.items():
            destination = installed / target
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(source.read_bytes())
        script = (
            "import os,sys\n"
            "from pathlib import Path\n"
            "root=Path(sys.argv[1])\n"
            "scripts=root/'scripts'\n"
            "sys.path[:0]=[str(scripts)]\n"
            "import protected_submit_contract\n"
            "import local_state_binding\n"
            "import protected_invocation_contract\n"
            "import protected_lifecycle_contract\n"
            "import protected_local_materialization\n"
            "import legacy_rtwin_pbs\n"
            "import protected_legacy_effect_handoff as h\n"
            "assert h._materialization_owner_path()=="
            "scripts/'protected_local_materialization.py'\n"
            "assert h._legacy_owner_path()==scripts/'legacy_rtwin_pbs.py'\n"
        )
        result = __import__("subprocess").run(
            [sys.executable, "-c", script, str(installed)],
            cwd=installed,
            env={
                **os.environ,
                "AUTO_G16_RUNTIME_CONFIG": str(RUNTIME_PLACEHOLDER),
            },
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_fixture_binds_base_and_additive_candidate_files(self) -> None:
        fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        successor = json.loads(
            FIXED_CONSTRAINT_SUCCESSOR_PATH.read_text(encoding="utf-8")
        )
        self.assertEqual(
            fixture["schema"],
            "auto-g16-protected-legacy-effect-handoff-fixture/1",
        )
        self.assertEqual(
            fixture["base_commit"],
            "ab9530bcd6c9ec96e2bd37f7e9022314532a85bb",
        )
        self.assertEqual(
            fixture["base_tree"],
            "e887bdd294285ea35bf6fe98b4d58853dcdf69f2",
        )
        self.assertEqual(
            successor["schema"],
            "auto-g16-legacy-rtwin-pbs-fixed-constraint-successor-fixture/1",
        )
        self.assertEqual(
            successor["base_commit"],
            "5b18af0dfc5c35f4de8e90730e50cd166de4d39c",
        )
        self.assertEqual(
            successor["base_tree"],
            "07eec0ccb056d3d7e06ee238c76ce52eb47d68df",
        )
        self.assertEqual(
            successor["base_parents"],
            [
                "f59ed8a121387902d877b6a4b7b20f47bb08c296",
                "e9ff2c58c903aea1eee5e1cf56f037606cb3cf9d",
            ],
        )
        for relative, binding in fixture["files"].items():
            with self.subTest(path=relative):
                current_sha256 = binding["sha256"]
                if relative in successor["files"]:
                    successor_binding = successor["files"][relative]
                    self.assertEqual(
                        successor_binding["before_sha256"],
                        current_sha256,
                    )
                    current_sha256 = successor_binding["sha256"]
                self.assertEqual(
                    hashlib.sha256((ROOT / relative).read_bytes()).hexdigest(),
                    current_sha256,
                )
        for relative, binding in successor["files"].items():
            with self.subTest(successor_path=relative):
                self.assertEqual(
                    hashlib.sha256((ROOT / relative).read_bytes()).hexdigest(),
                    binding["sha256"],
                )
        self.assertFalse(fixture["remaining_gates"]["adapter_connected"])
        self.assertFalse(
            fixture["remaining_gates"][
                "runtime_transport_binding_complete"
            ]
        )


if __name__ == "__main__":
    unittest.main()
