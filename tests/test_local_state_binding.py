#!/usr/bin/env python3
"""Placeholder-only offline tests for deterministic local-state ownership."""

from __future__ import annotations

import copy
import hashlib
import inspect
import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
import unicodedata
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).parents[1]
ROOT_SCRIPTS = ROOT / "scripts"
SKILL_SCRIPTS = ROOT / "skills" / "auto-g16-rtwin-pbs" / "scripts"
TEST_TEMP_PARENT = Path(tempfile.gettempdir()).resolve()
if TEST_TEMP_PARENT == ROOT or ROOT in TEST_TEMP_PARENT.parents:
    raise RuntimeError("local-state placeholder tests require a temp root outside the repository")
sys.path.insert(0, str(ROOT_SCRIPTS))
sys.path.insert(0, str(SKILL_SCRIPTS))

import execution_facade as FACADE  # noqa: E402
import local_state_binding as LOCAL  # noqa: E402
import skill_package  # noqa: E402
from tests import test_protected_submit_contract as SUPPORT  # noqa: E402


class LocalStateFixture:
    """Build only placeholder roots and existing reviewed owner artifacts."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.protected_root = root / "protected"
        self.protected_root.mkdir()
        original_temporary_directory = tempfile.TemporaryDirectory

        def task_temporary_directory(*args: object, **kwargs: object) -> object:
            requested_parent = kwargs.get("dir")
            if (
                requested_parent is not None
                and Path(requested_parent).resolve() == ROOT.resolve()
            ):
                kwargs["dir"] = self.root
            return original_temporary_directory(*args, **kwargs)

        authorization_tests = SUPPORT.CLOSURE_TESTS.AUTH_TESTS
        with mock.patch.object(
            authorization_tests.tempfile,
            "TemporaryDirectory",
            new=task_temporary_directory,
        ):
            self.protected = SUPPORT.ProtectedSubmitFixture(self.protected_root)
        self.workspace_root = root / "workspace"
        self.workspace_root.mkdir()
        self.local_dir = (
            self.workspace_root
            / LOCAL.OUTPUTS_COMPONENT
            / "safejob"
            / self.protected.attempt_id
        )
        self.local_dir.mkdir(parents=True)
        self.ledger_path = self.local_dir / LOCAL.LEDGER_BASENAME
        self.ledger_path.write_bytes(self.protected.ledger_path.read_bytes())
        self.evidence = LOCAL.LocalStateBindingEvidence(
            workspace_root=self.workspace_root,
            ledger_path=self.ledger_path,
            protected_submit_evidence=self.protected.evidence(),
        )

    def owner(self) -> LOCAL.LocalStateBindingOwner:
        return LOCAL.LocalStateBindingOwner._for_testing_with_clock(
            SUPPORT.PrivateTestClock(SUPPORT.NOW),
            _test_token=LOCAL._TEST_OWNER_TOKEN,
        )

    def close(self) -> None:
        self.protected.transport.tearDown()


class LocalStateBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(
            prefix="auto-g16-local-state-test-",
            dir=TEST_TEMP_PARENT,
        )
        self.root = Path(self.temporary.name).resolve()
        self.fixture = LocalStateFixture(self.root)

    def tearDown(self) -> None:
        self.fixture.close()
        self.temporary.cleanup()

    def seal(self) -> LOCAL.SealedLocalStateBinding:
        return self.fixture.owner().seal(self.fixture.evidence)

    def test_placeholder_temp_roots_never_touch_repository(self) -> None:
        authorization_root = self.fixture.protected.transport.helper.root
        self.assertTrue(self.root.is_relative_to(TEST_TEMP_PARENT))
        self.assertTrue(authorization_root.is_relative_to(self.root))
        self.assertFalse(self.root.is_relative_to(ROOT))
        self.assertFalse(authorization_root.is_relative_to(ROOT))
        self.assertFalse((ROOT / authorization_root.name).exists())

    def test_derived_layout_positive_is_read_only_and_portable(self) -> None:
        before_ledger = self.fixture.ledger_path.read_bytes()
        before_mode = self.fixture.local_dir.stat().st_mode
        binding = self.seal()
        binding.assert_owner_sealed()
        binding.assert_current()
        document = binding.document()
        expected_relative = (
            f"outputs/safejob/{self.fixture.protected.attempt_id}"
        )
        self.assertEqual(
            document["layout"]["relative_local_dir"],
            expected_relative,
        )
        self.assertEqual(
            set(document["layout"]),
            {"schema", "relative_local_dir", "ledger_basename"},
        )
        self.assertNotIn("relative_ledger_path", document["layout"])
        self.assertEqual(
            binding.paths.ledger_path.relative_to(
                binding.paths.workspace_root
            ).as_posix(),
            expected_relative + "/" + document["layout"]["ledger_basename"],
        )
        self.assertNotIn(str(self.fixture.workspace_root), json.dumps(document))
        self.assertNotIn("batch_id", document["ledger"])
        self.assertRegex(
            document["ledger"]["batch_id_sha256"],
            r"^[a-f0-9]{64}$",
        )
        self.assertEqual(binding.paths.workspace_root, self.fixture.workspace_root)
        self.assertEqual(binding.paths.local_dir, self.fixture.local_dir)
        self.assertEqual(binding.paths.ledger_path, self.fixture.ledger_path)
        self.assertEqual(self.fixture.ledger_path.read_bytes(), before_ledger)
        self.assertEqual(self.fixture.local_dir.stat().st_mode, before_mode)
        self.assertEqual(
            sorted(path.name for path in self.fixture.local_dir.iterdir()),
            [LOCAL.LEDGER_BASENAME],
        )
        self.assertFalse(
            (self.fixture.ledger_path.with_name(
                self.fixture.ledger_path.name + ".lock"
            )).exists()
        )
        self.assertTrue(document["policy"]["no_execution_authorization"])
        self.assertFalse(
            document["policy"]["local_state_directory_creation_performed"]
        )
        self.assertFalse(
            document["policy"]["local_state_permissions_changed"]
        )
        self.assertFalse(document["policy"]["ledger_write_performed"])
        self.assertFalse(document["policy"]["ledger_lock_acquired"])

    def test_caller_local_dir_is_impossible_and_seals_are_not_constructible(self) -> None:
        self.assertEqual(
            tuple(LOCAL.LocalStateBindingEvidence.__dataclass_fields__),
            ("workspace_root", "ledger_path", "protected_submit_evidence"),
        )
        self.assertNotIn(
            "local_dir",
            inspect.signature(LOCAL.LocalStateBindingEvidence).parameters,
        )
        with self.assertRaises(TypeError):
            self.fixture.owner().seal(
                LOCAL.LocalStateBindingEvidence(
                    str(self.fixture.workspace_root),  # type: ignore[arg-type]
                    self.fixture.ledger_path,
                    self.fixture.protected.evidence(),
                )
            )
        with self.assertRaises(TypeError):
            LOCAL.LocalStatePaths()
        with self.assertRaises(TypeError):
            LOCAL.SealedLocalStateBinding()
        paths = self.fixture.owner().derive(self.fixture.evidence)
        paths.assert_owner_sealed()
        self.assertFalse(
            any(
                token in name
                for name in dir(paths)
                for token in ("command", "callback", "backend", "adapter")
            )
        )

    def test_wrong_ledger_path_basename_outside_root_and_cross_root_fail(self) -> None:
        wrong_basename = self.fixture.local_dir / "ledger.json"
        wrong_basename.write_bytes(self.fixture.ledger_path.read_bytes())
        for path in (
            wrong_basename,
            self.fixture.protected.ledger_path,
        ):
            with self.subTest(path=path):
                evidence = LOCAL.LocalStateBindingEvidence(
                    workspace_root=self.fixture.workspace_root,
                    ledger_path=path,
                    protected_submit_evidence=self.fixture.protected.evidence(),
                )
                with self.assertRaisesRegex(
                    LOCAL.LocalStateBindingError,
                    "owner-derived fixed layout",
                ):
                    self.fixture.owner().seal(evidence)
        other_root = self.root / "other-workspace"
        other_root.mkdir()
        cross_root = LOCAL.LocalStateBindingEvidence(
            workspace_root=other_root,
            ledger_path=self.fixture.ledger_path,
            protected_submit_evidence=self.fixture.protected.evidence(),
        )
        with self.assertRaises(LOCAL.LocalStateBindingError):
            self.fixture.owner().seal(cross_root)

        traversal_root = (
            self.fixture.workspace_root
            / ".."
            / self.fixture.workspace_root.name
        )
        traversal = LOCAL.LocalStateBindingEvidence(
            workspace_root=traversal_root,
            ledger_path=(
                traversal_root
                / "outputs"
                / "safejob"
                / self.fixture.protected.attempt_id
                / LOCAL.LEDGER_BASENAME
            ),
            protected_submit_evidence=self.fixture.protected.evidence(),
        )
        with self.assertRaisesRegex(
            LOCAL.LocalStateBindingError,
            "canonical absolute NFC",
        ):
            self.fixture.owner().seal(traversal)

    def test_symlink_workspace_ancestor_and_ledger_leaf_fail(self) -> None:
        linked_root = self.root / "linked-workspace"
        linked_root.symlink_to(self.fixture.workspace_root, target_is_directory=True)
        linked = LOCAL.LocalStateBindingEvidence(
            workspace_root=linked_root,
            ledger_path=(
                linked_root
                / "outputs"
                / "safejob"
                / self.fixture.protected.attempt_id
                / LOCAL.LEDGER_BASENAME
            ),
            protected_submit_evidence=self.fixture.protected.evidence(),
        )
        with self.assertRaisesRegex(
            LOCAL.LocalStateBindingError,
            "drift|symlink",
        ):
            self.fixture.owner().seal(linked)

        outputs = self.fixture.workspace_root / "outputs"
        outputs_target = self.root / "outputs-target"
        outputs.rename(outputs_target)
        outputs.symlink_to(outputs_target, target_is_directory=True)
        try:
            with self.assertRaisesRegex(
                LOCAL.LocalStateBindingError,
                "drift|symlink",
            ):
                self.fixture.owner().seal(self.fixture.evidence)
        finally:
            outputs.unlink()
            outputs_target.rename(outputs)

        data = self.fixture.ledger_path.read_bytes()
        target = self.root / "ledger-target.json"
        target.write_bytes(data)
        self.fixture.ledger_path.unlink()
        self.fixture.ledger_path.symlink_to(target)
        with self.assertRaisesRegex(
            LOCAL.LocalStateBindingError,
            "fixed layout|drift|symlink",
        ):
            self.fixture.owner().seal(self.fixture.evidence)

    def test_duplicate_json_and_typed_ledger_drift_fail_closed(self) -> None:
        original = self.fixture.ledger_path.read_text(encoding="utf-8")
        duplicate = original.replace(
            '"schema":',
            '"schema":"gaussian-execution-batch/3","schema":',
            1,
        )
        self.fixture.ledger_path.write_text(duplicate, encoding="utf-8")
        with self.assertRaisesRegex(
            LOCAL.LocalStateBindingError,
            "duplicate|owner rejected",
        ):
            self.fixture.owner().seal(self.fixture.evidence)

        self.fixture.ledger_path.write_text(original, encoding="utf-8")
        changed = copy.deepcopy(self.fixture.protected.ledger)
        changed["revision"] += 1
        changed["ledger_sha256"] = SUPPORT.BATCH.digest_value(
            {
                key: value
                for key, value in changed.items()
                if key != "ledger_sha256"
            }
        )
        drifted_protected = self.fixture.protected.evidence()
        object.__setattr__(drifted_protected, "execution_ledger", changed)
        evidence = LOCAL.LocalStateBindingEvidence(
            self.fixture.workspace_root,
            self.fixture.ledger_path,
            drifted_protected,
        )
        with self.assertRaises(LOCAL.LocalStateBindingError):
            self.fixture.owner().seal(evidence)

    def test_wrong_owner_and_noncanonical_unicode_component_fail(self) -> None:
        actual_uid = os.getuid()
        with mock.patch.object(LOCAL.os, "getuid", return_value=actual_uid + 1):
            with self.assertRaisesRegex(
                LOCAL.LocalStateBindingError,
                "owned by the current user",
            ):
                self.fixture.owner().seal(self.fixture.evidence)
        decomposed = "e\u0301"
        self.assertNotEqual(unicodedata.normalize("NFC", decomposed), decomposed)
        with self.assertRaisesRegex(
            LOCAL.LocalStateBindingError,
            "canonical absolute NFC",
        ):
            LOCAL._require_canonical_path(
                Path("/private/tmp") / decomposed,
                "synthetic noncanonical path",
            )
        exact_case = self.root / "CaseComponent"
        exact_case.mkdir()
        case_alias = self.root / "casecomponent"
        with self.assertRaises(LOCAL.LocalStateBindingError):
            descriptor, _ = LOCAL._open_exact_directory(
                case_alias,
                "synthetic case alias",
                require_current_owner=True,
            )
            os.close(descriptor)

    def test_preexisting_protected_and_unrelated_state_fail_closed(self) -> None:
        names = (
            "job.json",
            "job.events.jsonl",
            "submission-intent.json",
            "submission-receipt.json",
            "safejob.pbs",
            "checksums.sha256",
            "minimum.gjf",
            "execution-batch-v3.json.lock",
            "unrelated.txt",
        )
        for name in names:
            with self.subTest(name=name):
                path = self.fixture.local_dir / name
                path.write_text("placeholder protected state\n", encoding="utf-8")
                try:
                    with self.assertRaisesRegex(
                        LOCAL.LocalStateBindingError,
                        "must contain only",
                    ):
                        self.fixture.owner().seal(self.fixture.evidence)
                finally:
                    path.unlink()

    def test_replay_rejects_content_drift_and_same_byte_inode_replace(self) -> None:
        binding = self.seal()
        original = self.fixture.ledger_path.read_bytes()
        self.fixture.ledger_path.write_bytes(original + b"\n")
        with self.assertRaises(LOCAL.LocalStateBindingError):
            binding.assert_current()

        self.fixture.ledger_path.write_bytes(original)
        replacement = self.fixture.local_dir / ".replacement"
        replacement.write_bytes(original)
        os.replace(replacement, self.fixture.ledger_path)
        with self.assertRaisesRegex(
            LOCAL.LocalStateBindingError,
            "identity changed",
        ):
            binding.assert_current()

    def test_concurrent_replay_is_read_only_and_restores_file_descriptors(self) -> None:
        binding = self.seal()
        before = (
            len(os.listdir("/dev/fd"))
            if Path("/dev/fd").is_dir()
            else None
        )
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(
                pool.map(
                    lambda _: binding.assert_current().binding_payload_sha256,
                    range(24),
                )
            )
        self.assertEqual(
            results,
            [binding.binding_payload_sha256] * 24,
        )
        if before is not None:
            self.assertEqual(len(os.listdir("/dev/fd")), before)

    def test_exception_restores_module_cache_environment_and_no_lock(self) -> None:
        original_environment = os.environ.get("AUTO_G16_RUNTIME_CONFIG")
        os.environ["AUTO_G16_RUNTIME_CONFIG"] = (
            "placeholder-local-state-runtime-config"
        )
        fake = types.ModuleType("protected_submit_contract")
        previous = sys.modules.get("protected_submit_contract")
        sys.modules["protected_submit_contract"] = fake
        extra = self.fixture.local_dir / "job.json"
        extra.write_text("placeholder\n", encoding="utf-8")
        try:
            with self.assertRaises(LOCAL.LocalStateBindingError):
                self.fixture.owner().seal(self.fixture.evidence)
            self.assertIs(sys.modules["protected_submit_contract"], fake)
            self.assertEqual(
                os.environ["AUTO_G16_RUNTIME_CONFIG"],
                "placeholder-local-state-runtime-config",
            )
            self.assertFalse(
                (self.fixture.ledger_path.with_name(
                    self.fixture.ledger_path.name + ".lock"
                )).exists()
            )
        finally:
            extra.unlink()
            if previous is None:
                sys.modules.pop("protected_submit_contract", None)
            else:
                sys.modules["protected_submit_contract"] = previous
            if original_environment is None:
                os.environ.pop("AUTO_G16_RUNTIME_CONFIG", None)
            else:
                os.environ["AUTO_G16_RUNTIME_CONFIG"] = original_environment

    def test_owner_semantics_close_component_and_self_hash_mismatches(self) -> None:
        document = self.seal().document()
        invalid_project = copy.deepcopy(document)
        invalid_project["identity"]["project"] = "bad/name"
        with self.assertRaises(LOCAL.LocalStateBindingError):
            LOCAL.validate_local_state_binding(invalid_project)

        invalid_attempt = copy.deepcopy(document)
        invalid_attempt["identity"]["attempt_id"] = "caller-attempt"
        with self.assertRaises(LOCAL.LocalStateBindingError):
            LOCAL.validate_local_state_binding(invalid_attempt)

        mismatched_layout = copy.deepcopy(document)
        mismatched_layout["layout"]["relative_local_dir"] = (
            f"outputs/other/{self.fixture.protected.attempt_id}"
        )
        mismatched_layout["binding_payload_sha256"] = LOCAL.digest(
            {
                key: value
                for key, value in mismatched_layout.items()
                if key != "binding_payload_sha256"
            }
        )
        with self.assertRaisesRegex(
            LOCAL.LocalStateBindingError,
            "owner-derived identity",
        ):
            LOCAL.validate_local_state_binding(mismatched_layout)

        self.assertEqual(LOCAL.finalize(document), document)

    def test_public_facade_surface_has_only_typed_derive_and_seal(self) -> None:
        self.assertEqual(
            tuple(inspect.signature(FACADE.derive_local_state_paths).parameters),
            ("evidence",),
        )
        self.assertEqual(
            tuple(inspect.signature(FACADE.seal_local_state_binding).parameters),
            ("evidence",),
        )
        self.assertEqual(
            sorted(
                name
                for name in dir(FACADE)
                if "local_state" in name and not name.startswith("_")
            ),
            ["derive_local_state_paths", "seal_local_state_binding"],
        )
        source = inspect.getsource(FACADE.seal_local_state_binding)
        self.assertIn("_exact_local_state_contract()", source)
        self.assertIn("_local_state_evidence_for_exact_owner", source)
        self.assertIn("owner.seal(exact_evidence)", source)
        facade_source = (
            SKILL_SCRIPTS / "execution_facade.py"
        ).read_text(encoding="utf-8")
        section = facade_source[
            facade_source.index("def _local_state_owner") :
        ]
        for forbidden in (
            "LegacyTransportAdapter",
            "legacy_adapter_integration",
            "reserve_once",
            "submit_once",
        ):
            self.assertNotIn(forbidden, section)

    def test_predecessor_hashes_freeze_and_stage_extraction_is_explicit(self) -> None:
        manifest = json.loads(
            (
                ROOT
                / "tests/fixtures/rtwin_pbs/protected_submit_legacy_hashes.json"
            ).read_text(encoding="utf-8")
        )
        extractions = [
            json.loads(
                (
                    ROOT
                    / "tests/fixtures/rtwin_pbs"
                    / name
                ).read_text(encoding="utf-8")
            )
            for name in (
                "protected_invocation_mechanical_extraction.json",
                "legacy_transaction_owner_mechanical_extraction.json",
                "legacy_effect_owner_mechanical_extraction.json",
                "legacy_effect_owner_concurrency_fix.json",
            )
        ]
        for relative, expected in manifest["files"].items():
            with self.subTest(path=relative):
                actual = hashlib.sha256(
                    (ROOT / relative).read_bytes()
                ).hexdigest()
                current = expected
                records = [
                    extraction["files"][relative]
                    for extraction in extractions
                    if relative in extraction["files"]
                ]
                for record in records:
                    self.assertEqual(record["before_sha256"], current)
                    self.assertFalse(record["legacy_semantics_changed"])
                    current = record["after_sha256"]
                self.assertEqual(actual, current)

    def test_package_and_source_relocation_preserve_exact_origin(self) -> None:
        package = skill_package.package_files(ROOT, "auto-g16-rtwin-pbs")
        self.assertEqual(
            package[Path("scripts/local_state_binding.py")].read_bytes(),
            (ROOT / "scripts/local_state_binding.py").read_bytes(),
        )
        self.assertEqual(
            package[
                Path("contracts/execution/local-state-binding.schema.json")
            ].read_bytes(),
            (
                ROOT
                / "contracts/execution/local-state-binding.schema.json"
            ).read_bytes(),
        )
        evidence = self.fixture.protected.evidence()
        portable_evidence = {
            "input_path": str(evidence.input_path),
            "input_approval_path": str(evidence.input_approval_path),
            "live_approval_path": str(evidence.live_approval_path),
            "execution_ledger": evidence.execution_ledger,
            "resource_policy": evidence.resource_policy,
            "resource_gate": evidence.resource_gate,
            "scheduler_snapshot": evidence.scheduler_snapshot,
            "scheduler_snapshot_artifact_hex": (
                evidence.scheduler_snapshot_artifact.hex()
            ),
            "project": evidence.project,
            "scientific_task_id": evidence.scientific_task_id,
            "idempotency_key": evidence.idempotency_key,
            "estimated_core_hours_evidence": (
                evidence.estimated_core_hours_evidence
            ),
            "work_kind": evidence.work_kind,
            "transport_artifacts": evidence.transport_artifacts,
        }
        expected_document = self.seal().document()
        with tempfile.TemporaryDirectory(
            prefix="auto-g16-local-state-package-test-",
            dir=TEST_TEMP_PARENT,
        ) as temporary:
            temporary_root = Path(temporary).resolve()
            installed = temporary_root / "auto-g16-rtwin-pbs"
            for destination_name, source in package.items():
                destination = installed / destination_name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
            evidence_path = temporary_root / "evidence.json"
            evidence_path.write_text(
                json.dumps(portable_evidence, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            expected_path = temporary_root / "expected.json"
            expected_path.write_text(
                json.dumps(expected_document, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            script = (
                "import json\n"
                "from datetime import datetime, timezone\n"
                "from pathlib import Path\n"
                "import execution_facade as facade\n"
                "import local_state_binding as local\n"
                "import protected_submit_contract as protected\n"
                f"raw=json.loads(Path({str(evidence_path)!r}).read_text())\n"
                "raw['input_path']=Path(raw['input_path'])\n"
                "raw['input_approval_path']=Path(raw['input_approval_path'])\n"
                "raw['live_approval_path']=Path(raw['live_approval_path'])\n"
                "raw['scheduler_snapshot_artifact']=bytes.fromhex("
                "raw.pop('scheduler_snapshot_artifact_hex'))\n"
                "protected_evidence=protected.ProtectedSubmitEvidence(**raw)\n"
                f"evidence=local.LocalStateBindingEvidence("
                f"Path({str(self.fixture.workspace_root)!r}),"
                f"Path({str(self.fixture.ledger_path)!r}),"
                "protected_evidence)\n"
                "clock=lambda: datetime(2030,1,1,12,2,tzinfo=timezone.utc)\n"
                "owner=local.LocalStateBindingOwner._for_testing_with_clock("
                "clock,_test_token=local._TEST_OWNER_TOKEN)\n"
                "document=owner.seal(evidence).document()\n"
                f"expected=json.loads(Path({str(expected_path)!r}).read_text())\n"
                "assert document==expected\n"
                "facade_owner=facade._local_state_owner()\n"
                "expected_origin=Path(facade.__file__).resolve().with_name("
                "'local_state_binding.py')\n"
                "assert Path(facade_owner.__class__.__init__.__code__."
                "co_filename).resolve()==expected_origin\n"
                "assert tuple(__import__('inspect').signature("
                "facade.seal_local_state_binding).parameters)==('evidence',)\n"
            )
            completed = subprocess.run(
                [sys.executable, "-c", script],
                cwd=installed,
                env={
                    "PATH": os.environ.get("PATH", ""),
                    "PYTHONPATH": str(installed / "scripts"),
                    "AUTO_G16_RUNTIME_CONFIG": str(
                        temporary_root / "intentionally-absent-runtime.json"
                    ),
                },
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )
            self.assertEqual(
                completed.returncode,
                0,
                completed.stdout + completed.stderr,
            )

    def test_facade_rejects_shadow_cache_and_cross_origin_local_evidence(self) -> None:
        package = skill_package.package_files(ROOT, "auto-g16-rtwin-pbs")
        with tempfile.TemporaryDirectory(
            prefix="auto-g16-local-state-origin-test-",
            dir=TEST_TEMP_PARENT,
        ) as temporary:
            temporary_root = Path(temporary).resolve()
            layouts = {
                "root": temporary_root / "root-layout",
                "package": temporary_root / "package-layout",
            }
            for installed in layouts.values():
                for destination_name, source in package.items():
                    destination = installed / destination_name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, destination)
            shadow = temporary_root / "caller-shadow"
            shadow.mkdir()
            (shadow / "local_state_binding.py").write_text(
                "raise AssertionError('caller-path shadow was imported')\n",
                encoding="utf-8",
            )
            script = (
                "import importlib.util, sys, types\n"
                "from pathlib import Path\n"
                f"root_scripts=Path({str(layouts['root'] / 'scripts')!r})\n"
                f"package_scripts=Path({str(layouts['package'] / 'scripts')!r})\n"
                f"shadow=Path({str(shadow)!r})\n"
                "sys.path[:0]=[str(shadow),str(root_scripts),str(package_scripts)]\n"
                "unrelated=types.ModuleType('unrelated_local_state_cache')\n"
                "sys.modules['unrelated_local_state_cache']=unrelated\n"
                "def load(name,path):\n"
                " spec=importlib.util.spec_from_file_location(name,path)\n"
                " assert spec and spec.loader\n"
                " module=importlib.util.module_from_spec(spec)\n"
                " sys.modules[name]=module\n"
                " spec.loader.exec_module(module)\n"
                " return module\n"
                "root_cached=load('local_state_binding',"
                "root_scripts/'local_state_binding.py')\n"
                "package_facade=load('package_execution_facade',"
                "package_scripts/'execution_facade.py')\n"
                "owner=package_facade._local_state_owner()\n"
                "assert Path(owner.__class__.__init__.__code__.co_filename).resolve()=="
                "(package_scripts/'local_state_binding.py').resolve()\n"
                "assert sys.modules['local_state_binding'] is root_cached\n"
                "package_cached=load('local_state_binding',"
                "package_scripts/'local_state_binding.py')\n"
                "def evidence(module):\n"
                " return module.LocalStateBindingEvidence("
                "Path('/placeholder/root'),Path('/placeholder/ledger'),object())\n"
                "package_evidence=evidence(package_cached)\n"
                "root_evidence=evidence(root_cached)\n"
                "with package_facade._exact_local_state_contract() as exact:\n"
                " rebound=package_facade._local_state_evidence_for_exact_owner("
                "exact,package_evidence)\n"
                " assert isinstance(rebound,exact.LocalStateBindingEvidence)\n"
                " try:\n"
                "  package_facade._local_state_evidence_for_exact_owner("
                "exact,root_evidence)\n"
                " except TypeError:\n"
                "  pass\n"
                " else:\n"
                "  raise AssertionError('cross-origin evidence was accepted')\n"
                "root_facade=load('root_execution_facade',"
                "root_scripts/'execution_facade.py')\n"
                "owner=root_facade._local_state_owner()\n"
                "assert Path(owner.__class__.__init__.__code__.co_filename).resolve()=="
                "(root_scripts/'local_state_binding.py').resolve()\n"
                "assert sys.modules['local_state_binding'] is package_cached\n"
                "sys.modules.pop('local_state_binding')\n"
                "fake=types.ModuleType('local_state_binding')\n"
                "fake.__file__=str(shadow/'local_state_binding.py')\n"
                "sys.modules['local_state_binding']=fake\n"
                "owner=package_facade._local_state_owner()\n"
                "assert Path(owner.__class__.__init__.__code__.co_filename).resolve()=="
                "(package_scripts/'local_state_binding.py').resolve()\n"
                "assert sys.modules['local_state_binding'] is fake\n"
                "assert sys.modules['unrelated_local_state_cache'] is unrelated\n"
            )
            completed = subprocess.run(
                [sys.executable, "-c", script],
                cwd=temporary_root,
                env={"PATH": os.environ.get("PATH", "")},
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )
            self.assertEqual(
                completed.returncode,
                0,
                completed.stdout + completed.stderr,
            )


if __name__ == "__main__":
    unittest.main()
