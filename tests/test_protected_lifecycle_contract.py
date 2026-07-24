#!/usr/bin/env python3
"""Strictly offline tests for the PR4K protected lifecycle contract."""

from __future__ import annotations

import copy
import dataclasses
import hashlib
import inspect
import importlib.util
import json
import os
import pickle
import shutil
import stat
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import types
import unittest
from collections.abc import Mapping
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).parents[1]
ROOT_SCRIPTS = ROOT / "scripts"
SKILL_SCRIPTS = ROOT / "skills" / "auto-g16-rtwin-pbs" / "scripts"
TEST_TEMP_PARENT = Path(tempfile.gettempdir()).resolve()
if TEST_TEMP_PARENT == ROOT or ROOT in TEST_TEMP_PARENT.parents:
    raise RuntimeError("protected-lifecycle tests require a system temp root")
sys.path.insert(0, str(ROOT_SCRIPTS))
sys.path.insert(0, str(SKILL_SCRIPTS))

import protected_lifecycle_contract as LIFECYCLE  # noqa: E402
import skill_package  # noqa: E402
from tests import test_protected_invocation_contract as SUPPORT  # noqa: E402


RUNTIME_PLACEHOLDER = (
    Path("/private/tmp")
    / "auto-g16-pr4k-runtime-config-does-not-exist.json"
)


class ProtectedLifecycleFixture:
    def __init__(self, root: Path) -> None:
        self.invocation = SUPPORT.ProtectedInvocationFixture(root)
        self.evidence = LIFECYCLE.ProtectedLifecycleEvidence(
            protected_invocation_evidence=self.invocation.evidence,
        )

    def owner(self) -> LIFECYCLE.ProtectedLifecycleContractOwner:
        return (
            LIFECYCLE.ProtectedLifecycleContractOwner
            ._for_testing_with_clock(
                lambda: SUPPORT.PROTECTED_SUPPORT.parse_utc(
                    SUPPORT.PROTECTED_SUPPORT.NOW
                ),
                _test_token=LIFECYCLE._TEST_OWNER_TOKEN,
            )
        )

    def close(self) -> None:
        self.invocation.close()


class ProtectedLifecycleContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(
            prefix="auto-g16-protected-lifecycle-",
            dir=TEST_TEMP_PARENT,
        )
        self.root = Path(self.temporary.name).resolve()
        self.fixture = ProtectedLifecycleFixture(self.root)

    def tearDown(self) -> None:
        self.fixture.close()
        self.temporary.cleanup()

    def seal(self) -> LIFECYCLE.SealedProtectedLifecycleContract:
        return self.fixture.owner().seal(self.fixture.evidence)

    def assert_current(
        self,
        sealed: LIFECYCLE.SealedProtectedLifecycleContract,
    ) -> None:
        with mock.patch.object(
            LIFECYCLE,
            "_utc_now",
            return_value=SUPPORT.PROTECTED_SUPPORT.parse_utc(
                SUPPORT.PROTECTED_SUPPORT.NOW
            ),
        ):
            sealed.assert_current()

    def test_positive_contract_is_read_only_and_non_executable(self) -> None:
        before = {
            path.relative_to(self.root): (
                path.read_bytes() if path.is_file() else None
            )
            for path in self.root.rglob("*")
        }
        sealed = self.seal()
        sealed.assert_owner_sealed()
        portable_before = LIFECYCLE.canonical_bytes(sealed.document())
        self.assert_current(sealed)
        self.assertEqual(
            LIFECYCLE.canonical_bytes(sealed.document()),
            portable_before,
        )
        after = {
            path.relative_to(self.root): (
                path.read_bytes() if path.is_file() else None
            )
            for path in self.root.rglob("*")
        }
        self.assertEqual(after, before)

        document = sealed.document()
        self.assertEqual(document["schema"], LIFECYCLE.SCHEMA)
        self.assertEqual(
            document["validation"],
            LIFECYCLE.VALIDATION_LAYERS,
        )
        self.assertNotIn("protected_invocation", document)
        self.assertNotIn("predecessor", document)
        self.assertNotIn("closure", document)
        self.assertEqual(
            LIFECYCLE.validate_protected_lifecycle_structure(document),
            document,
        )
        self.assertEqual(
            document["protected_submit_order"],
            list(LIFECYCLE.PROTECTED_SUBMIT_ORDER),
        )
        self.assertEqual(
            document["protected_invocation_order"],
            list(LIFECYCLE.PROTECTED_INVOCATION_ORDER),
        )
        self.assertEqual(
            document["legacy_effect_sequence"],
            list(LIFECYCLE.LEGACY_EFFECT_SEQUENCE),
        )
        self.assertEqual(
            document["required_future_implementation_order"],
            list(
                LIFECYCLE.REQUIRED_FUTURE_IMPLEMENTATION_ORDER
            ),
        )
        self.assertIn(
            (
                "reserve_protected_submit_once_and_enter_"
                "submission_uncertain"
            ),
            document["required_future_implementation_order"],
        )
        self.assertNotIn(
            "publish_submission_uncertain_before_effect",
            document["required_future_implementation_order"],
        )
        self.assertIn(
            "reconcile_exact_attempt_once",
            document["required_future_implementation_order"],
        )
        self.assertFalse(document["status"]["reserved"])
        self.assertFalse(document["status"]["effects_performed"])
        self.assertFalse(document["status"]["automatic_retry"])
        self.assertTrue(
            document["legacy_compatibility"][
                "future_long_process_adapter_requires_bounded_owner_lifecycle"
            ]
        )
        self.assertFalse(
            document["legacy_compatibility"][
                "legacy_raw_effect_owner_reusable"
            ]
        )
        self.assertFalse(
            any(
                callable(getattr(sealed, name, None))
                for name in (
                    "reserve",
                    "materialize",
                    "invoke",
                    "submit",
                    "status",
                    "fetch",
                    "cancel",
                    "cleanup",
                    "delete",
                )
            )
        )

    def test_public_input_is_exact_typed_pr4f_evidence_only(self) -> None:
        self.assertEqual(
            tuple(
                LIFECYCLE.ProtectedLifecycleEvidence
                .__dataclass_fields__
            ),
            ("protected_invocation_evidence",),
        )
        with self.assertRaises(TypeError):
            LIFECYCLE.SealedProtectedLifecycleContract()
        for value in (
            {},
            self.fixture.invocation.owner().seal(
                self.fixture.invocation.evidence
            ),
            types.SimpleNamespace(
                protected_invocation_evidence=(
                    self.fixture.invocation.evidence
                ),
                local_dir=self.root,
            ),
        ):
            with self.subTest(value=type(value).__name__):
                with self.assertRaises(
                    LIFECYCLE.ProtectedLifecycleError
                ):
                    self.fixture.owner().seal(value)  # type: ignore[arg-type]
        namespace: dict[str, object] = {}
        exec(
            compile(
                "def snapshot(self):\n    return self\n",
                str(LIFECYCLE._adjacent_invocation_path()),
                "exec",
            ),
            namespace,
        )
        lookalike_type = dataclasses.make_dataclass(
            "ProtectedInvocationEvidence",
            (
                ("protected_submit_evidence", object),
                ("local_state_evidence", object),
            ),
            namespace={
                "snapshot": namespace["snapshot"],
            },
        )
        lookalike_type.__module__ = LIFECYCLE.INVOCATION_OWNER_NAME
        lookalike = lookalike_type(
            self.fixture.invocation.protected_evidence,
            self.fixture.invocation.local.evidence,
        )
        with self.assertRaisesRegex(
            LIFECYCLE.ProtectedLifecycleError,
            "exact adjacent owner",
        ):
            self.fixture.owner().seal(
                LIFECYCLE.ProtectedLifecycleEvidence(lookalike)
            )
        evidence_parameters = tuple(
            inspect.signature(
                LIFECYCLE.ProtectedLifecycleEvidence
            ).parameters
        )
        self.assertEqual(
            evidence_parameters,
            ("protected_invocation_evidence",),
        )
        source = inspect.getsource(
            LIFECYCLE._typed_invocation_evidence
        )
        for forbidden_identity in (
            "__module__",
            "__name__",
            "__qualname__",
            "__dataclass_fields__",
            "co_filename",
        ):
            self.assertNotIn(forbidden_identity, source)
        source = inspect.getsource(LIFECYCLE)
        for forbidden in (
            "import legacy_rtwin_pbs",
            "_legacy_effect_plan_from_transaction(",
            "_legacy_raw_effect_owner_from_plan(",
            "LegacyTransportAdapter(",
            "subprocess.",
            "socket.",
            "write_bytes(",
            "write_text(",
            "os.replace(",
            "os.rename(",
            "os.unlink(",
            "os.environ",
            "os.getenv(",
        ):
            self.assertNotIn(forbidden, source)

    def test_production_clock_is_fresh_and_test_clock_is_private(self) -> None:
        production = (
            LIFECYCLE.ProtectedLifecycleContractOwner.production()
        )
        testing = self.fixture.owner()
        self.assertFalse(production._testing)
        self.assertTrue(testing._testing)
        self.assertIs(production._clock, LIFECYCLE._utc_now)
        self.assertIsNot(testing._clock, LIFECYCLE._utc_now)
        import protected_invocation_contract as invocation

        original = invocation._utc_now
        with self.assertRaisesRegex(RuntimeError, "forced"):
            with LIFECYCLE._bind_invocation_clock(
                invocation,
                SUPPORT.PROTECTED_SUPPORT.parse_utc(
                    SUPPORT.PROTECTED_SUPPORT.NOW
                ),
            ):
                self.assertIsNot(invocation._utc_now, original)
                raise RuntimeError("forced")
        self.assertIs(invocation._utc_now, original)

    def test_unknown_fields_flags_and_orders_fail_closed(self) -> None:
        document = self.seal().document()
        cases = []
        unknown = copy.deepcopy(document)
        unknown["unexpected"] = True
        cases.append(("unknown", unknown))
        reserved = copy.deepcopy(document)
        reserved["status"]["reserved"] = True
        cases.append(("reserved", reserved))
        effect = copy.deepcopy(document)
        effect["status"]["effects_performed"] = True
        cases.append(("effects", effect))
        retry = copy.deepcopy(document)
        retry["status"]["automatic_retry"] = True
        cases.append(("retry", retry))
        order = copy.deepcopy(document)
        order["required_future_implementation_order"][2:4] = reversed(
            order["required_future_implementation_order"][2:4]
        )
        cases.append(("order", order))
        raw_owner = copy.deepcopy(document)
        raw_owner["status"]["raw_effect_owner_created"] = True
        cases.append(("raw-owner", raw_owner))
        for label, draft in cases:
            with self.subTest(label=label):
                with self.assertRaises(
                    LIFECYCLE.ProtectedLifecycleError
                ):
                    LIFECYCLE.validate_protected_lifecycle_structure(draft)

    def test_all_fixed_boolean_fields_reject_integer_zero_and_one(self) -> None:
        document = self.seal().document()
        fixed_mappings = {
            "validation": LIFECYCLE.VALIDATION_LAYERS,
            "scope": LIFECYCLE.SCOPE,
            "status": LIFECYCLE.STATUS,
            "legacy_compatibility": LIFECYCLE.LEGACY_COMPATIBILITY,
        }
        for section, expected in fixed_mappings.items():
            for field in expected:
                for replacement in (0, 1):
                    with self.subTest(
                        section=section,
                        field=field,
                        replacement=replacement,
                    ):
                        draft = copy.deepcopy(document)
                        draft[section][field] = replacement
                        with self.assertRaises(
                            LIFECYCLE.ProtectedLifecycleError
                        ):
                            (
                                LIFECYCLE
                                .validate_protected_lifecycle_structure(
                                    draft
                                )
                            )

    def test_structural_splices_cannot_claim_owner_acceptance(self) -> None:
        sealed = self.seal()
        document = sealed.document()
        cases = []

        identity = copy.deepcopy(document)
        identity["protected_invocation_projection"][
            "invocation_id"
        ] = "protected-invocation-" + "0" * 64
        cases.append(("identity", identity))

        local = copy.deepcopy(document)
        local["protected_invocation_projection"][
            "ledger_identity_sha256"
        ] = "1" * 64
        cases.append(("local-ledger-identity", local))

        stage_hash = copy.deepcopy(document)
        stage_hash["protected_invocation_projection"][
            "stage_manifest_sha256"
        ] = "1" * 64
        cases.append(("stage-hash", stage_hash))

        for label, draft in cases:
            with self.subTest(label=label):
                draft = LIFECYCLE._finalize_owner_projection(draft)
                self.assertEqual(
                    LIFECYCLE.validate_protected_lifecycle_structure(
                        draft
                    ),
                    draft,
                )
                with self.assertRaises(
                    LIFECYCLE.ProtectedLifecycleError
                ):
                    LIFECYCLE._validate_owner_projection(
                        draft,
                        sealed.protected_invocation_bundle.document(),
                    )

    def test_nan_infinity_and_bool_as_integer_fail(self) -> None:
        document = self.seal().document()
        for value in (True, float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=repr(value)):
                draft = copy.deepcopy(document)
                draft["protected_invocation_projection"][
                    "stage_artifact_count"
                ] = value
                with self.assertRaises(
                    LIFECYCLE.ProtectedLifecycleError
                ):
                    LIFECYCLE.validate_protected_lifecycle_structure(
                        draft
                    )

    def test_current_replay_rejects_local_and_stage_drift(self) -> None:
        sealed = self.seal()
        ledger_path = self.fixture.invocation.local.ledger_path
        original_ledger = ledger_path.read_bytes()
        ledger_path.write_bytes(original_ledger + b" ")
        with self.assertRaisesRegex(
            LIFECYCLE.ProtectedLifecycleError,
            "(current replay failed closed|complete replay differs)",
        ):
            self.assert_current(sealed)
        ledger_path.write_bytes(original_ledger)

        resealed = self.seal()
        input_path = self.fixture.invocation.protected_evidence.input_path
        original_input = input_path.read_bytes()
        input_path.write_bytes(original_input + b" ")
        with self.assertRaisesRegex(
            LIFECYCLE.ProtectedLifecycleError,
            "(current replay failed closed|complete replay differs)",
        ):
            self.assert_current(resealed)

    def test_owner_snapshot_isolated_from_caller_nested_mutation(self) -> None:
        sealed = self.seal()
        caller = self.fixture.invocation.evidence
        retained = sealed.protected_invocation_evidence

        def mutable_identities(value: object) -> set[int]:
            result: set[int] = set()
            visited: set[int] = set()

            def visit(item: object) -> None:
                identity = id(item)
                if identity in visited:
                    return
                visited.add(identity)
                if dataclasses.is_dataclass(item):
                    for field in dataclasses.fields(item):
                        visit(getattr(item, field.name))
                elif type(item) is dict:
                    result.add(identity)
                    for key, nested in item.items():
                        visit(key)
                        visit(nested)
                elif type(item) is list:
                    result.add(identity)
                    for nested in item:
                        visit(nested)

            visit(value)
            return result

        self.assertTrue(mutable_identities(caller))
        self.assertTrue(mutable_identities(retained))
        self.assertTrue(
            mutable_identities(caller).isdisjoint(
                mutable_identities(retained)
            )
        )
        self.assertIs(
            retained.protected_submit_evidence,
            retained.local_state_evidence.protected_submit_evidence,
        )
        ledger = (
            self.fixture.invocation.protected_evidence.execution_ledger
        )
        original_revision = ledger["revision"]
        original_review_sha256 = ledger["batch"]["review_sha256"]
        original_document = sealed.document()
        try:
            ledger["revision"] = original_revision + 1
            ledger["batch"]["review_sha256"] = "0" * 64
            self.assertEqual(sealed.document(), original_document)
            self.assert_current(sealed)
        finally:
            ledger["revision"] = original_revision
            ledger["batch"]["review_sha256"] = original_review_sha256

    def test_owner_snapshot_rejects_caller_container_hooks(self) -> None:
        base = self.fixture.invocation.protected_evidence
        hook_calls: list[str] = []

        class HostileHooks:
            def __copy__(self) -> object:
                hook_calls.append("copy")
                raise AssertionError("caller __copy__ must not run")

            def __deepcopy__(self, memo: dict[int, object]) -> object:
                del memo
                hook_calls.append("deepcopy")
                return self

            def __reduce__(self) -> object:
                hook_calls.append("reduce")
                raise AssertionError("caller __reduce__ must not run")

            def __reduce_ex__(self, protocol: int) -> object:
                del protocol
                hook_calls.append("reduce_ex")
                raise AssertionError("caller __reduce_ex__ must not run")

        class HostileMapping(HostileHooks, Mapping):
            def __init__(self, value: dict) -> None:
                self.value = value

            def __getitem__(self, key: object) -> object:
                return self.value[key]

            def __iter__(self):
                return iter(self.value)

            def __len__(self) -> int:
                return len(self.value)

        class HostileDict(HostileHooks, dict):
            pass

        class HostileList(HostileHooks, list):
            pass

        hostile_ledger = HostileMapping(base.execution_ledger)
        hostile_dict = HostileDict(base.execution_ledger)
        nested_list_ledger = copy.deepcopy(base.execution_ledger)
        nested_list_ledger["events"] = HostileList(
            nested_list_ledger["events"]
        )
        for label, ledger in (
            ("mapping", hostile_ledger),
            ("dict-subclass", hostile_dict),
            ("nested-list-subclass", nested_list_ledger),
        ):
            with self.subTest(label=label):
                protected = dataclasses.replace(
                    base,
                    execution_ledger=ledger,
                )
                local = dataclasses.replace(
                    self.fixture.invocation.local.evidence,
                    protected_submit_evidence=protected,
                )
                invocation = dataclasses.replace(
                    self.fixture.invocation.evidence,
                    protected_submit_evidence=protected,
                    local_state_evidence=local,
                )
                with self.assertRaisesRegex(
                    LIFECYCLE.ProtectedLifecycleError,
                    "accepts only exact adjacent owner dataclasses",
                ):
                    self.fixture.owner().seal(
                        LIFECYCLE.ProtectedLifecycleEvidence(invocation)
                    )
        self.assertEqual(hook_calls, [])

    def test_caller_nested_mutation_before_seal_is_owner_rejected(
        self,
    ) -> None:
        ledger = (
            self.fixture.invocation.protected_evidence.execution_ledger
        )
        original_revision = ledger["revision"]
        try:
            ledger["revision"] = original_revision + 1
            with self.assertRaises(
                LIFECYCLE.ProtectedLifecycleError
            ):
                self.seal()
        finally:
            ledger["revision"] = original_revision

    def test_seal_time_nested_mutation_fails_closed_deterministically(
        self,
    ) -> None:
        ledger = (
            self.fixture.invocation.protected_evidence.execution_ledger
        )
        original_revision = ledger["revision"]
        original_rebuild = (
            LIFECYCLE._rebuild_invocation_evidence_graph
        )

        first_rebuilt = threading.Event()
        mutation_done = threading.Event()
        top_level_rebuilds = 0

        def mutate_between_snapshots() -> None:
            if not first_rebuilt.wait(5):
                return
            ledger["revision"] = original_revision + 1
            mutation_done.set()

        def between_snapshots(
            module: types.ModuleType,
            value: object,
        ) -> object:
            nonlocal top_level_rebuilds
            top_level_rebuilds += 1
            result = original_rebuild(module, value)
            if top_level_rebuilds == 1:
                first_rebuilt.set()
                if not mutation_done.wait(5):
                    raise RuntimeError("between-snapshot mutation did not run")
            return result

        worker = threading.Thread(target=mutate_between_snapshots)
        worker.start()
        try:
            with mock.patch.object(
                LIFECYCLE,
                "_rebuild_invocation_evidence_graph",
                side_effect=between_snapshots,
            ):
                with self.assertRaisesRegex(
                    LIFECYCLE.ProtectedLifecycleError,
                    "changed during owner snapshot",
                ):
                    self.seal()
        finally:
            worker.join()
            ledger["revision"] = original_revision
        self.assertTrue(first_rebuilt.is_set())
        self.assertTrue(mutation_done.is_set())

        nested_rebuild_started = threading.Event()
        nested_mutation_done = threading.Event()
        nested_copy_done = threading.Event()
        nested_restore_done = threading.Event()
        nested_intercepted = False
        original_value_rebuild = (
            LIFECYCLE._rebuild_owner_snapshot_value
        )

        def mutate_during_nested_copy() -> None:
            if not nested_rebuild_started.wait(5):
                return
            ledger["revision"] = original_revision + 1
            nested_mutation_done.set()
            if not nested_copy_done.wait(5):
                return
            ledger["revision"] = original_revision
            nested_restore_done.set()

        def during_nested_rebuild(
            value: object,
            dataclass_fields: dict[type, tuple[str, ...]],
            memo: dict[int, object],
            active: set[int],
        ) -> object:
            nonlocal nested_intercepted
            if value is ledger and not nested_intercepted:
                nested_intercepted = True
                nested_rebuild_started.set()
                if not nested_mutation_done.wait(5):
                    raise RuntimeError("nested mutation did not run")
                result = original_value_rebuild(
                    value,
                    dataclass_fields,
                    memo,
                    active,
                )
                nested_copy_done.set()
                if not nested_restore_done.wait(5):
                    raise RuntimeError("nested restore did not run")
                return result
            return original_value_rebuild(
                value,
                dataclass_fields,
                memo,
                active,
            )

        worker = threading.Thread(target=mutate_during_nested_copy)
        worker.start()
        try:
            with mock.patch.object(
                LIFECYCLE,
                "_rebuild_owner_snapshot_value",
                side_effect=during_nested_rebuild,
            ):
                with self.assertRaisesRegex(
                    LIFECYCLE.ProtectedLifecycleError,
                    "changed during owner snapshot",
                ):
                    self.seal()
        finally:
            worker.join()
            ledger["revision"] = original_revision
        self.assertTrue(nested_rebuild_started.is_set())
        self.assertTrue(nested_mutation_done.is_set())
        self.assertTrue(nested_copy_done.is_set())
        self.assertTrue(nested_restore_done.is_set())

        sealed = self.seal()
        self.assert_current(sealed)

    def test_concurrent_caller_mutation_cannot_change_current_replay(
        self,
    ) -> None:
        sealed = self.seal()
        ledger = (
            self.fixture.invocation.protected_evidence.execution_ledger
        )
        original_revision = ledger["revision"]
        stop = threading.Event()

        def mutate() -> None:
            while not stop.is_set():
                ledger["revision"] = original_revision + 1
                ledger["revision"] = original_revision
                time.sleep(0.0001)

        thread = threading.Thread(target=mutate)
        thread.start()
        try:
            self.assert_current(sealed)
        finally:
            stop.set()
            thread.join()
            ledger["revision"] = original_revision

    def test_sealed_capability_rejects_copy_deepcopy_and_pickle(self) -> None:
        sealed = self.seal()
        for clone in (
            lambda: copy.copy(sealed),
            lambda: copy.deepcopy(sealed),
            lambda: pickle.loads(pickle.dumps(sealed)),
        ):
            with self.subTest(clone=clone):
                with self.assertRaises(TypeError):
                    clone()

    def test_foreign_identical_module_and_cache_poisoning_fail(self) -> None:
        path = LIFECYCLE._adjacent_invocation_path()
        spec = importlib.util.spec_from_file_location(
            "foreign_protected_invocation_contract",
            path,
        )
        assert spec is not None and spec.loader is not None
        foreign = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = foreign
        try:
            spec.loader.exec_module(foreign)
            evidence = foreign.ProtectedInvocationEvidence(
                self.fixture.invocation.protected_evidence,
                self.fixture.invocation.local.evidence,
            )
            with self.assertRaisesRegex(
                LIFECYCLE.ProtectedLifecycleError,
                "exact adjacent owner",
            ):
                self.fixture.owner().seal(
                    LIFECYCLE.ProtectedLifecycleEvidence(evidence)
                )
        finally:
            sys.modules.pop(spec.name, None)

        original = sys.modules[LIFECYCLE.INVOCATION_OWNER_NAME]
        fake = types.ModuleType(LIFECYCLE.INVOCATION_OWNER_NAME)
        fake.__file__ = str(path)
        fake.__spec__ = types.SimpleNamespace(origin=str(path))
        sys.modules[LIFECYCLE.INVOCATION_OWNER_NAME] = fake
        try:
            with self.assertRaisesRegex(
                LIFECYCLE.ProtectedLifecycleError,
                (
                    "module identity differs|exact adjacent owner|"
                    "has no attribute"
                ),
            ):
                self.seal()
        finally:
            sys.modules[LIFECYCLE.INVOCATION_OWNER_NAME] = original

    def test_exact_loader_restores_cache_on_success_and_failure(self) -> None:
        fake = types.ModuleType(LIFECYCLE.INVOCATION_OWNER_NAME)
        fake.__file__ = "/private/tmp/preloaded-protected-invocation.py"
        fake.__spec__ = types.SimpleNamespace(origin=fake.__file__)
        previous = sys.modules.get(LIFECYCLE.INVOCATION_OWNER_NAME)
        sys.modules[LIFECYCLE.INVOCATION_OWNER_NAME] = fake
        try:
            with LIFECYCLE._exact_invocation_owner() as module:
                self.assertEqual(
                    Path(module.__file__).resolve(),
                    (
                        ROOT
                        / "scripts/protected_invocation_contract.py"
                    ).resolve(),
                )
                self.assertIsNot(module, fake)
            self.assertIs(
                sys.modules[LIFECYCLE.INVOCATION_OWNER_NAME],
                fake,
            )
            with self.assertRaisesRegex(RuntimeError, "forced"):
                with LIFECYCLE._exact_invocation_owner():
                    raise RuntimeError("forced")
            self.assertIs(
                sys.modules[LIFECYCLE.INVOCATION_OWNER_NAME],
                fake,
            )
        finally:
            if previous is None:
                sys.modules.pop(
                    LIFECYCLE.INVOCATION_OWNER_NAME,
                    None,
                )
            else:
                sys.modules[
                    LIFECYCLE.INVOCATION_OWNER_NAME
                ] = previous

    def test_owner_stable_reads_close_file_descriptors(self) -> None:
        fd_directory = (
            Path("/dev/fd")
            if Path("/dev/fd").is_dir()
            else Path("/proc/self/fd")
        )
        if not fd_directory.is_dir():
            self.skipTest("file-descriptor inventory is unavailable")
        before = len(tuple(fd_directory.iterdir()))
        for _ in range(25):
            snapshot = LIFECYCLE._stable_invocation_owner_snapshot()
            self.assertTrue(stat.S_ISREG(snapshot.mode))
            self.assertEqual(snapshot.size, len(snapshot.source_bytes))
        after = len(tuple(fd_directory.iterdir()))
        self.assertEqual(after, before)

    def test_git_free_relocation_cold_warm_and_import_order(self) -> None:
        archive_root = self.root / "source-archive"
        shutil.copytree(
            ROOT,
            archive_root,
            symlinks=True,
            ignore=shutil.ignore_patterns(
                ".git",
                "__pycache__",
                "*.pyc",
                ".DS_Store",
            ),
        )
        self.assertFalse((archive_root / ".git").exists())
        script = textwrap.dedent(
            f"""
            import json
            import sys
            import tempfile
            from pathlib import Path

            root = Path({str(archive_root)!r})
            sys.path[:0] = [
                str(root),
                str(root / "scripts"),
                str(root / "skills/auto-g16-rtwin-pbs/scripts"),
            ]
            import protected_invocation_contract
            import protected_lifecycle_contract as lifecycle
            from tests import test_protected_lifecycle_contract as support

            results = []
            for _ in range(2):
                with tempfile.TemporaryDirectory(
                    prefix="auto-g16-pr4k-relocated-"
                ) as temporary:
                    fixture = support.ProtectedLifecycleFixture(
                        Path(temporary).resolve()
                    )
                    try:
                        sealed = fixture.owner().seal(fixture.evidence)
                        lifecycle._utc_now = (
                            lambda: support.SUPPORT.PROTECTED_SUPPORT.parse_utc(
                                support.SUPPORT.PROTECTED_SUPPORT.NOW
                            )
                        )
                        sealed.assert_current()
                        results.append(sealed.document()["schema"])
                    finally:
                        fixture.close()
            print(json.dumps(results))
            """
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=archive_root,
            text=True,
            capture_output=True,
            env={
                **os.environ,
                "AUTO_G16_RUNTIME_CONFIG": str(RUNTIME_PLACEHOLDER),
            },
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(result.stdout),
            [LIFECYCLE.SCHEMA, LIFECYCLE.SCHEMA],
        )

    def test_relocated_owner_replacement_and_symlink_fail_closed(self) -> None:
        archive_root = self.root / "owner-replacement-archive"
        shutil.copytree(
            ROOT,
            archive_root,
            symlinks=True,
            ignore=shutil.ignore_patterns(
                ".git",
                "__pycache__",
                "*.pyc",
                ".DS_Store",
            ),
        )
        script = textwrap.dedent(
            f"""
            import os
            import sys
            import tempfile
            from pathlib import Path

            root = Path({str(archive_root)!r})
            sys.path[:0] = [
                str(root),
                str(root / "scripts"),
                str(root / "skills/auto-g16-rtwin-pbs/scripts"),
            ]
            import protected_lifecycle_contract as lifecycle
            from tests import test_protected_lifecycle_contract as support

            owner = root / "scripts/protected_invocation_contract.py"
            pristine = owner.read_bytes()
            rejected = []
            for case in ("replace", "symlink"):
                owner.write_bytes(pristine)
                with tempfile.TemporaryDirectory(
                    prefix="auto-g16-pr4k-owner-drift-"
                ) as temporary:
                    fixture = support.ProtectedLifecycleFixture(
                        Path(temporary).resolve()
                    )
                    try:
                        sealed = fixture.owner().seal(fixture.evidence)
                        lifecycle._utc_now = (
                            lambda: support.SUPPORT.PROTECTED_SUPPORT.parse_utc(
                                support.SUPPORT.PROTECTED_SUPPORT.NOW
                            )
                        )
                        if case == "replace":
                            replacement = owner.with_suffix(".replacement")
                            replacement.write_bytes(pristine)
                            os.replace(replacement, owner)
                        else:
                            real = owner.with_suffix(".real")
                            real.write_bytes(pristine)
                            owner.unlink()
                            owner.symlink_to(real.name)
                        try:
                            sealed.assert_current()
                        except lifecycle.ProtectedLifecycleError:
                            rejected.append(case)
                        else:
                            raise AssertionError(case)
                    finally:
                        fixture.close()
                        if owner.is_symlink():
                            owner.unlink()
                        owner.write_bytes(pristine)
            assert rejected == ["replace", "symlink"], rejected
            """
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=archive_root,
            text=True,
            capture_output=True,
            env={
                **os.environ,
                "AUTO_G16_RUNTIME_CONFIG": str(RUNTIME_PLACEHOLDER),
            },
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_predecessor_and_legacy_bytes_remain_frozen(self) -> None:
        expected = {
            "scripts/protected_invocation_contract.py": (
                "da1343fd0638183b171bd0404e52ed1a960530eb62f909abec5d9bed2a83de28"
            ),
            "contracts/execution/protected-invocation-bundle.schema.json": (
                "77274b93dabba0cbcbd93ff9b1c75b739a9a18c8d68d5a1078fa5b601de62197"
            ),
            "scripts/protected_submit_contract.py": (
                "60f0da3b9306f19eb54efe9de94593b1f428c066dda919d4ac384289dd450c2a"
            ),
            "scripts/local_state_binding.py": (
                "6a23eb9307fdf930d4055589dd08baff8dea9275470db7ea9154f6ffa324b6b5"
            ),
            "skills/auto-g16-rtwin-pbs/scripts/legacy_rtwin_pbs.py": (
                "259c6679fd9b2436b9c7e133fc4b19482e6fed5ea7bbd9f94a86ddac5e7aa8cb"
            ),
            "tests/fixtures/rtwin_pbs/legacy_effect_plan_single_use_fix.json": (
                "237abc518814bb1debab3d6b6aee7d3041ebcc724d3e00718bda0a1e045cba3d"
            ),
        }
        for relative, expected_hash in expected.items():
            with self.subTest(path=relative):
                self.assertEqual(
                    hashlib.sha256((ROOT / relative).read_bytes()).hexdigest(),
                    expected_hash,
                )

    def test_named_skill_package_contains_owner_schema_and_reference(
        self,
    ) -> None:
        package = skill_package.package_files(
            ROOT,
            "auto-g16-rtwin-pbs",
        )
        self.assertEqual(len(package), 78)
        expected = {
            Path("scripts/protected_lifecycle_contract.py"): (
                ROOT / "scripts/protected_lifecycle_contract.py"
            ),
            Path(
                "contracts/execution/"
                "protected-lifecycle-contract.schema.json"
            ): (
                ROOT
                / "contracts/execution/"
                "protected-lifecycle-contract.schema.json"
            ),
            Path("references/protected-lifecycle-contract.md"): (
                ROOT
                / "skills/auto-g16-rtwin-pbs/references/"
                "protected-lifecycle-contract.md"
            ),
        }
        for target, source in expected.items():
            with self.subTest(target=target):
                self.assertEqual(package[target], source)
        installed = self.root / "installed-auto-g16-rtwin-pbs"
        for target, source in package.items():
            destination = installed / target
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(source.read_bytes())
        self.assertEqual(
            skill_package.inventory(installed),
            skill_package.package_inventory(
                ROOT,
                "auto-g16-rtwin-pbs",
            ),
        )

    def test_successor_fixture_binds_baseline_and_candidate_files(self) -> None:
        fixture_path = (
            ROOT
            / "tests/fixtures/rtwin_pbs/"
            "protected_lifecycle_contract.json"
        )
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        self.assertEqual(
            set(fixture),
            {
                "schema",
                "base_branch",
                "base_commit",
                "base_tree",
                "base_parent",
                "scope",
                "files",
                "frozen_predecessors",
                "recovery_gates",
            },
        )
        self.assertEqual(
            fixture["schema"],
            "auto-g16-protected-lifecycle-contract-fixture/1",
        )
        self.assertEqual(
            fixture["base_branch"],
            "codex/v26-legacy-effect-plan-single-use-fix",
        )
        self.assertEqual(
            fixture["base_commit"],
            "477bada8c5b0342ebd8a8faab1acf3d08dc2814e",
        )
        self.assertEqual(
            fixture["base_tree"],
            "fbb6e0ae521fa67601ba54a887facd0c6d57ed7f",
        )
        self.assertEqual(
            fixture["base_parent"],
            "aaa004a88131f244c19e6d39c74eb936e9eb55b6",
        )
        for relative, binding in fixture["files"].items():
            with self.subTest(path=relative):
                self.assertEqual(
                    set(binding),
                    {"sha256", "change_class"},
                )
                self.assertEqual(
                    hashlib.sha256(
                        (ROOT / relative).read_bytes()
                    ).hexdigest(),
                    binding["sha256"],
                )


if __name__ == "__main__":
    unittest.main()
