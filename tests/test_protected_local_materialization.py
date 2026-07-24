#!/usr/bin/env python3
"""Strictly offline tests for the PR4L local materialization successor."""

from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import inspect
import json
import os
import pickle
import stat
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
    raise RuntimeError("PR4L tests require a system temporary root")
sys.path.insert(0, str(ROOT_SCRIPTS))
sys.path.insert(0, str(SKILL_SCRIPTS))

import execution_facade as FACADE  # noqa: E402
import protected_lifecycle_contract as LIFECYCLE  # noqa: E402
import protected_local_materialization as MATERIALIZATION  # noqa: E402
import skill_package  # noqa: E402
from tests import test_protected_lifecycle_contract as SUPPORT  # noqa: E402
from tests import test_protected_submit_contract as PR4D_SUPPORT  # noqa: E402


class ProtectedLocalMaterializationFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.lifecycle = SUPPORT.ProtectedLifecycleFixture(root)
        self.evidence = self.lifecycle.evidence
        self.state_root = root / "trusted-reservation-state"

    def owner(
        self,
    ) -> MATERIALIZATION.ProtectedLocalMaterializationOwner:
        return (
            MATERIALIZATION.ProtectedLocalMaterializationOwner
            ._for_testing_with_clock(
                self.state_root,
                lambda: PR4D_SUPPORT.parse_utc(PR4D_SUPPORT.NOW),
                _test_token=MATERIALIZATION._TEST_OWNER_TOKEN,
            )
        )

    def close(self) -> None:
        self.lifecycle.close()


class ProtectedLocalMaterializationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(
            prefix="auto-g16-protected-local-materialization-",
            dir=TEST_TEMP_PARENT,
        )
        self.root = Path(self.temporary.name).resolve()
        self.fixture = ProtectedLocalMaterializationFixture(self.root)

    def tearDown(self) -> None:
        self.fixture.close()
        self.temporary.cleanup()

    def materialize(
        self,
    ) -> MATERIALIZATION.SealedProtectedLocalMaterialization:
        return self.fixture.owner().materialize_once(
            self.fixture.evidence
        )

    def consumption_records(self) -> list[Path]:
        records = self.fixture.state_root / "consumptions"
        return sorted(records.iterdir()) if records.is_dir() else []

    def load_lifecycle_copy(self, name: str) -> object:
        path = Path(LIFECYCLE.__file__).resolve()
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            sys.modules.pop(name, None)
            raise
        return module

    def test_exact_order_materializes_pr4f_bytes_and_publishes_state_last(
        self,
    ) -> None:
        events = []
        original_seal = MATERIALIZATION._seal_current_lifecycle
        original_reserve = MATERIALIZATION._reserve_protected_submit_once
        original_write = MATERIALIZATION._write_materialized_artifact
        original_publish = MATERIALIZATION._publish_state_record

        def seal(*args: object, **kwargs: object) -> object:
            events.append("seal_pr4k_current")
            return original_seal(*args, **kwargs)

        def reserve(*args: object, **kwargs: object) -> object:
            events.append("reserve_pr4d")
            return original_reserve(*args, **kwargs)

        def write(directory: int, artifact: object) -> object:
            events.append(f"write:{artifact.relative_name}")
            return original_write(directory, artifact)

        def publish(directory: int, raw: bytes) -> object:
            events.append("publish_state")
            return original_publish(directory, raw)

        with (
            mock.patch.object(
                MATERIALIZATION,
                "_seal_current_lifecycle",
                side_effect=seal,
            ),
            mock.patch.object(
                MATERIALIZATION,
                "_reserve_protected_submit_once",
                side_effect=reserve,
            ),
            mock.patch.object(
                MATERIALIZATION,
                "_write_materialized_artifact",
                side_effect=write,
            ),
            mock.patch.object(
                MATERIALIZATION,
                "_publish_state_record",
                side_effect=publish,
            ),
        ):
            sealed = self.materialize()

        self.assertEqual(events[0:2], ["seal_pr4k_current", "reserve_pr4d"])
        self.assertEqual(events[-1], "publish_state")
        self.assertTrue(
            all(item.startswith("write:") for item in events[2:-1])
        )
        sealed.assert_owner_sealed()
        sealed.assert_current()
        document = sealed.document()
        self.assertEqual(document["schema"], MATERIALIZATION.SCHEMA)
        self.assertEqual(document["scope"], MATERIALIZATION.SCOPE)
        self.assertEqual(document["status"], MATERIALIZATION.STATUS)
        self.assertEqual(document["policy"], MATERIALIZATION.POLICY)
        self.assertEqual(
            document["reservation"]["submission_state"],
            "submission_uncertain",
        )
        self.assertFalse(document["status"]["effects_performed"])
        self.assertFalse(document["status"]["qsub_invocation_started"])
        self.assertFalse(
            document["status"]["long_process_owner_lifecycle_gate_open"]
        )
        self.assertEqual(len(self.consumption_records()), 1)

        invocation = sealed.lifecycle.protected_invocation_bundle
        for artifact in invocation.stage_plan.artifacts:
            path = sealed.local_dir / artifact.relative_name
            self.assertTrue(path.is_file())
            self.assertFalse(path.is_symlink())
            self.assertEqual(
                hashlib.sha256(path.read_bytes()).hexdigest(),
                artifact.sha256,
            )
            self.assertEqual(path.stat().st_size, artifact.size_bytes)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        state_path = sealed.local_dir / MATERIALIZATION.STATE_BASENAME
        self.assertEqual(
            state_path.read_bytes(),
            MATERIALIZATION.canonical_bytes(document),
        )
        self.assertEqual(
            document["directory_topology"][-1],
            MATERIALIZATION.STATE_BASENAME,
        )

        with self.assertRaises(LIFECYCLE.ProtectedLifecycleError):
            with mock.patch.object(
                LIFECYCLE,
                "_utc_now",
                return_value=PR4D_SUPPORT.parse_utc(PR4D_SUPPORT.NOW),
            ):
                sealed.lifecycle.assert_current()
        sealed.assert_current()

    def test_only_exact_pr4k_evidence_is_accepted_without_mutation(
        self,
    ) -> None:
        owner = self.fixture.owner()
        for value in (
            {},
            self.fixture.lifecycle.owner().seal(self.fixture.evidence),
            object(),
        ):
            with self.subTest(type=type(value).__name__):
                with self.assertRaises((TypeError, ValueError)):
                    owner.materialize_once(value)
        self.assertEqual(self.consumption_records(), [])
        self.assertEqual(
            os.listdir(self.fixture.lifecycle.invocation.local.local_dir),
            [MATERIALIZATION.LEDGER_BASENAME],
        )

    def test_same_path_second_pr4k_module_is_rejected_before_reservation(
        self,
    ) -> None:
        original = sys.modules[MATERIALIZATION.LIFECYCLE_MODULE_NAME]
        second = self.load_lifecycle_copy(
            MATERIALIZATION.LIFECYCLE_MODULE_NAME
        )
        evidence = second.ProtectedLifecycleEvidence(
            self.fixture.evidence.protected_invocation_evidence
        )
        try:
            with (
                mock.patch.object(
                    MATERIALIZATION,
                    "_reserve_protected_submit_once",
                ) as reserve,
                mock.patch.object(
                    MATERIALIZATION,
                    "_write_materialized_artifact",
                ) as write,
            ):
                with self.assertRaisesRegex(
                    MATERIALIZATION.ProtectedLocalMaterializationError,
                    "module identity differs",
                ):
                    self.fixture.owner().materialize_once(evidence)
                reserve.assert_not_called()
                write.assert_not_called()
        finally:
            sys.modules[MATERIALIZATION.LIFECYCLE_MODULE_NAME] = original
        self.assertEqual(self.consumption_records(), [])
        self.assertEqual(
            os.listdir(self.fixture.lifecycle.invocation.local.local_dir),
            [MATERIALIZATION.LEDGER_BASENAME],
        )

    def test_foreign_cache_and_import_order_mismatches_fail_closed(
        self,
    ) -> None:
        name = MATERIALIZATION.LIFECYCLE_MODULE_NAME
        original = sys.modules[name]
        foreign_name = "foreign_protected_lifecycle_contract"
        foreign = self.load_lifecycle_copy(foreign_name)
        try:
            foreign_evidence = foreign.ProtectedLifecycleEvidence(
                self.fixture.evidence.protected_invocation_evidence
            )
            with self.assertRaisesRegex(
                TypeError,
                "exact bound PR4K evidence",
            ):
                self.fixture.owner().materialize_once(foreign_evidence)

            original_evidence_type = original.ProtectedLifecycleEvidence
            original.ProtectedLifecycleEvidence = (
                foreign.ProtectedLifecycleEvidence
            )
            try:
                with self.assertRaisesRegex(
                    MATERIALIZATION.ProtectedLocalMaterializationError,
                    "class identity differs",
                ):
                    self.fixture.owner().materialize_once(
                        self.fixture.evidence
                    )
            finally:
                original.ProtectedLifecycleEvidence = original_evidence_type
        finally:
            sys.modules.pop(foreign_name, None)

        second = self.load_lifecycle_copy(name)
        try:
            with self.assertRaisesRegex(
                MATERIALIZATION.ProtectedLocalMaterializationError,
                "module identity differs",
            ):
                self.fixture.owner().materialize_once(self.fixture.evidence)
        finally:
            sys.modules[name] = original

        materialization_name = "foreign_protected_local_materialization"
        path = Path(MATERIALIZATION.__file__).resolve()
        spec = importlib.util.spec_from_file_location(
            materialization_name,
            path,
        )
        assert spec is not None and spec.loader is not None
        misplaced = importlib.util.module_from_spec(spec)
        sys.modules[materialization_name] = misplaced
        sys.modules.pop(name, None)
        try:
            with self.assertRaisesRegex(
                ValueError,
                "must be loaded before local materialization",
            ):
                spec.loader.exec_module(misplaced)
        finally:
            sys.modules.pop(materialization_name, None)
            sys.modules[name] = original

        self.assertEqual(self.consumption_records(), [])
        self.assertEqual(
            os.listdir(self.fixture.lifecycle.invocation.local.local_dir),
            [MATERIALIZATION.LEDGER_BASENAME],
        )

    def test_bound_pr4k_source_snapshot_rejects_same_bytes_replacement(
        self,
    ) -> None:
        owner_dir = self.root / "owner-copy"
        owner_dir.mkdir()
        lifecycle_path = owner_dir / "protected_lifecycle_contract.py"
        materialization_path = (
            owner_dir / "protected_local_materialization.py"
        )
        lifecycle_bytes = Path(LIFECYCLE.__file__).read_bytes()
        lifecycle_path.write_bytes(lifecycle_bytes)
        materialization_path.write_bytes(Path(MATERIALIZATION.__file__).read_bytes())

        lifecycle_name = MATERIALIZATION.LIFECYCLE_MODULE_NAME
        original_lifecycle = sys.modules[lifecycle_name]
        copied_lifecycle_spec = importlib.util.spec_from_file_location(
            lifecycle_name,
            lifecycle_path,
        )
        assert (
            copied_lifecycle_spec is not None
            and copied_lifecycle_spec.loader is not None
        )
        copied_lifecycle = importlib.util.module_from_spec(
            copied_lifecycle_spec
        )
        sys.modules[lifecycle_name] = copied_lifecycle
        copied_materialization_name = (
            "copied_protected_local_materialization"
        )
        copied_materialization_spec = importlib.util.spec_from_file_location(
            copied_materialization_name,
            materialization_path,
        )
        assert (
            copied_materialization_spec is not None
            and copied_materialization_spec.loader is not None
        )
        copied_materialization = importlib.util.module_from_spec(
            copied_materialization_spec
        )
        sys.modules[copied_materialization_name] = copied_materialization
        try:
            copied_lifecycle_spec.loader.exec_module(copied_lifecycle)
            copied_materialization_spec.loader.exec_module(
                copied_materialization
            )
            copied_evidence = copied_lifecycle.ProtectedLifecycleEvidence(
                self.fixture.evidence.protected_invocation_evidence
            )
            replacement = owner_dir / "replacement.py"
            replacement.write_bytes(lifecycle_bytes)
            os.replace(replacement, lifecycle_path)
            owner = (
                copied_materialization.ProtectedLocalMaterializationOwner
                ._for_testing_with_clock(
                    self.fixture.state_root,
                    lambda: PR4D_SUPPORT.parse_utc(PR4D_SUPPORT.NOW),
                    _test_token=copied_materialization._TEST_OWNER_TOKEN,
                )
            )
            with self.assertRaisesRegex(
                copied_materialization.ProtectedLocalMaterializationError,
                "identity differs",
            ):
                owner.materialize_once(copied_evidence)
        finally:
            sys.modules.pop(copied_materialization_name, None)
            sys.modules[lifecycle_name] = original_lifecycle

        self.assertEqual(self.consumption_records(), [])
        self.assertEqual(
            os.listdir(self.fixture.lifecycle.invocation.local.local_dir),
            [MATERIALIZATION.LEDGER_BASENAME],
        )

    def test_sealed_state_rechecks_bound_pr4k_module_identity(self) -> None:
        sealed = self.materialize()
        name = MATERIALIZATION.LIFECYCLE_MODULE_NAME
        original = sys.modules[name]
        second = self.load_lifecycle_copy(name)
        try:
            with self.assertRaisesRegex(
                MATERIALIZATION.ProtectedLocalMaterializationError,
                "module identity differs",
            ):
                sealed.assert_current()
        finally:
            self.assertIs(sys.modules[name], second)
            sys.modules[name] = original
        sealed.assert_current()

    def test_sealed_capability_rejects_copy_pickle_and_state_drift(
        self,
    ) -> None:
        sealed = self.materialize()
        with self.assertRaises(TypeError):
            copy.copy(sealed)
        with self.assertRaises(TypeError):
            copy.deepcopy(sealed)
        with self.assertRaises(TypeError):
            pickle.dumps(sealed)

        first = sealed.document()["materialized_files"][0]["relative_name"]
        path = sealed.local_dir / first
        original = path.read_bytes()
        path.write_bytes(original + b"drift")
        with self.assertRaises(
            MATERIALIZATION.ProtectedLocalMaterializationError
        ):
            sealed.assert_current()

    def test_partial_baseexception_is_not_cleaned_or_retried(
        self,
    ) -> None:
        original = MATERIALIZATION._write_materialized_artifact
        written = []

        def fail_after_one(directory: int, artifact: object) -> object:
            if written:
                raise KeyboardInterrupt("synthetic crash")
            result = original(directory, artifact)
            written.append(artifact.relative_name)
            return result

        with mock.patch.object(
            MATERIALIZATION,
            "_write_materialized_artifact",
            side_effect=fail_after_one,
        ):
            with self.assertRaises(KeyboardInterrupt):
                self.materialize()
        local_dir = self.fixture.lifecycle.invocation.local.local_dir
        self.assertTrue((local_dir / written[0]).is_file())
        self.assertFalse(
            (local_dir / MATERIALIZATION.STATE_BASENAME).exists()
        )
        records_before = [path.read_bytes() for path in self.consumption_records()]
        self.assertEqual(len(records_before), 1)

        with self.assertRaises((ValueError, LIFECYCLE.ProtectedLifecycleError)):
            self.materialize()
        self.assertTrue((local_dir / written[0]).is_file())
        self.assertEqual(
            [path.read_bytes() for path in self.consumption_records()],
            records_before,
        )

    def test_post_reservation_conflict_fails_no_clobber_and_stays_uncertain(
        self,
    ) -> None:
        original = MATERIALIZATION._reserve_protected_submit_once

        def reserve_then_conflict(*args: object, **kwargs: object) -> object:
            reserved = original(*args, **kwargs)
            invocation = args[0].protected_invocation_bundle
            target = invocation.local_state_binding.paths.local_dir
            name = invocation.stage_plan.artifacts[0].relative_name
            (target / name).symlink_to(
                invocation.local_state_binding.paths.ledger_path.name
            )
            return reserved

        with mock.patch.object(
            MATERIALIZATION,
            "_reserve_protected_submit_once",
            side_effect=reserve_then_conflict,
        ):
            with self.assertRaises(
                MATERIALIZATION.ProtectedLocalMaterializationError
            ):
                self.materialize()
        local_dir = self.fixture.lifecycle.invocation.local.local_dir
        self.assertTrue(
            (local_dir / self.fixture.lifecycle.invocation.evidence
             .protected_submit_evidence.input_path.name).is_symlink()
        )
        self.assertFalse(
            (local_dir / MATERIALIZATION.STATE_BASENAME).exists()
        )
        self.assertEqual(len(self.consumption_records()), 1)

    def test_concurrent_calls_allow_one_complete_materialization(self) -> None:
        barrier = threading.Barrier(2)

        def run() -> object:
            barrier.wait()
            try:
                return self.materialize()
            except Exception as exc:
                return exc

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: run(), range(2)))
        successes = [
            result
            for result in results
            if isinstance(
                result,
                MATERIALIZATION.SealedProtectedLocalMaterialization,
            )
        ]
        failures = [
            result for result in results if isinstance(result, Exception)
        ]
        self.assertEqual(len(successes), 1)
        self.assertEqual(len(failures), 1)
        successes[0].assert_current()
        self.assertEqual(len(self.consumption_records()), 1)

    def test_large_private_snapshot_materializes_without_source_reread(
        self,
    ) -> None:
        companion = (
            self.fixture.lifecycle.invocation.local.protected.input_path
            .with_suffix(".xyz")
        )
        with companion.open("wb") as handle:
            handle.write(b"0\nplaceholder\n")
            handle.truncate(16 * 1024 * 1024 + 4096)
        sealed = self.materialize()
        large = next(
            artifact
            for artifact in sealed.lifecycle.protected_invocation_bundle
            .stage_plan.artifacts
            if artifact.role == "companion_xyz"
        )
        self.assertIsNone(large.data)
        self.assertIsNotNone(large.private_snapshot)
        materialized = sealed.local_dir / large.relative_name
        self.assertEqual(materialized.stat().st_size, large.size_bytes)
        self.assertEqual(
            hashlib.sha256(materialized.read_bytes()).hexdigest(),
            large.sha256,
        )
        sealed.assert_current()

    def test_no_effect_surface_and_forbidden_dependencies(self) -> None:
        source = inspect.getsource(MATERIALIZATION)
        tree = ast.parse(source)
        imported = {
            alias.name.split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imported.update(
            node.module.split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        )
        self.assertTrue(
            {
                "subprocess",
                "socket",
                "paramiko",
                "requests",
            }.isdisjoint(imported)
        )
        public_methods = {
            name
            for name, value in inspect.getmembers(
                MATERIALIZATION.ProtectedLocalMaterializationOwner,
                inspect.isfunction,
            )
            if not name.startswith("_")
        }
        self.assertEqual(public_methods, {"materialize_once"})
        sealed_methods = {
            name
            for name, value in inspect.getmembers(
                MATERIALIZATION.SealedProtectedLocalMaterialization,
                inspect.isfunction,
            )
            if not name.startswith("_")
        }
        self.assertEqual(
            sealed_methods,
            {"assert_current", "assert_owner_sealed", "document"},
        )
        for forbidden in (
            "invoke_adapter",
            "qsub",
            "qdel",
            "ssh",
            "runner",
            "command",
            "cleanup",
            "rollback",
            "retry_once",
        ):
            self.assertNotIn(forbidden, public_methods)
            self.assertNotIn(forbidden, sealed_methods)

    def test_facade_and_named_package_expose_only_the_bounded_owner(
        self,
    ) -> None:
        self.assertEqual(
            tuple(
                inspect.signature(
                    FACADE.materialize_protected_lifecycle_once
                ).parameters
            ),
            ("evidence",),
        )
        facade_source = inspect.getsource(
            FACADE.materialize_protected_lifecycle_once
        )
        self.assertIn(
            "_exact_protected_local_materialization()",
            facade_source,
        )
        self.assertIn("owner.materialize_once(evidence)", facade_source)
        source_path = FACADE._protected_local_materialization_path()
        self.assertEqual(
            source_path,
            ROOT / "scripts/protected_local_materialization.py",
        )
        package = skill_package.package_files(
            ROOT,
            "auto-g16-rtwin-pbs",
        )
        expected = {
            Path("scripts/protected_local_materialization.py"): (
                ROOT / "scripts/protected_local_materialization.py"
            ),
            Path(
                "contracts/execution/"
                "protected-local-materialization.schema.json"
            ): (
                ROOT
                / "contracts/execution/"
                "protected-local-materialization.schema.json"
            ),
            Path("references/protected-local-materialization.md"): (
                ROOT
                / "skills/auto-g16-rtwin-pbs/references/"
                "protected-local-materialization.md"
            ),
        }
        for target, source in expected.items():
            self.assertEqual(package[target], source)
        self.assertEqual(len(package), 81)

    def test_predecessor_and_effect_owner_bytes_remain_frozen(self) -> None:
        expected = {
            "scripts/protected_submit_contract.py": (
                "60f0da3b9306f19eb54efe9de94593b1f428c066dda919d4ac384289dd450c2a"
            ),
            "scripts/local_state_binding.py": (
                "6a23eb9307fdf930d4055589dd08baff8dea9275470db7ea9154f6ffa324b6b5"
            ),
            "scripts/protected_invocation_contract.py": (
                "da1343fd0638183b171bd0404e52ed1a960530eb62f909abec5d9bed2a83de28"
            ),
            "scripts/protected_lifecycle_contract.py": (
                "166e8b398922682eb94c9705e8ee1ccf0ed13546a75c49010090f7d7182fbafb"
            ),
            "skills/auto-g16-rtwin-pbs/scripts/legacy_rtwin_pbs.py": (
                "259c6679fd9b2436b9c7e133fc4b19482e6fed5ea7bbd9f94a86ddac5e7aa8cb"
            ),
        }
        for relative, expected_sha256 in expected.items():
            with self.subTest(path=relative):
                self.assertEqual(
                    hashlib.sha256((ROOT / relative).read_bytes()).hexdigest(),
                    expected_sha256,
                )

    def test_state_validator_rejects_owner_semantic_splices(self) -> None:
        document = self.materialize().document()
        cases = []
        changed = copy.deepcopy(document)
        changed["status"]["effects_performed"] = True
        cases.append(changed)
        changed = copy.deepcopy(document)
        changed["policy"]["automatic_retry"] = True
        cases.append(changed)
        changed = copy.deepcopy(document)
        changed["directory_topology"][-1] = "not-state.json"
        cases.append(changed)
        changed = copy.deepcopy(document)
        changed["materialized_files"][0]["sha256"] = "f" * 64
        cases.append(changed)
        for changed in cases:
            with self.subTest(case=len(cases)):
                with self.assertRaises(
                    MATERIALIZATION.ProtectedLocalMaterializationError
                ):
                    MATERIALIZATION.validate_protected_local_materialization_state(
                        changed
                    )

    def test_successor_fixture_binds_exact_base_and_candidate_files(
        self,
    ) -> None:
        fixture_path = (
            ROOT
            / "tests/fixtures/rtwin_pbs/"
            "protected_local_materialization.json"
        )
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        self.assertEqual(
            set(fixture),
            {
                "schema",
                "base_commit",
                "base_tree",
                "base_parent",
                "scope",
                "files",
                "frozen_predecessors",
                "remaining_gates",
            },
        )
        self.assertEqual(
            fixture["schema"],
            "auto-g16-protected-local-materialization-fixture/1",
        )
        self.assertEqual(
            fixture["base_commit"],
            "45c1bb81c8579b4fce4181a76f7559ef8affcc57",
        )
        self.assertEqual(
            fixture["base_tree"],
            "b681eb2c6d0a9bceb2c57964ca06e3a533750ce0",
        )
        for relative, binding in fixture["files"].items():
            with self.subTest(path=relative):
                self.assertEqual(set(binding), {"sha256", "change_class"})
                self.assertEqual(
                    hashlib.sha256(
                        (ROOT / relative).read_bytes()
                    ).hexdigest(),
                    binding["sha256"],
                )
        self.assertFalse(
            fixture["remaining_gates"][
                "long_process_raw_owner_lifecycle_bounded"
            ]
        )
        self.assertFalse(
            fixture["remaining_gates"]["adapter_mapping_proven"]
        )


if __name__ == "__main__":
    unittest.main()
