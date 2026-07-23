#!/usr/bin/env python3
"""Placeholder-only tests for the PR4F invocation successor."""

from __future__ import annotations

import copy
import contextlib
import dataclasses
import hashlib
import inspect
import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).parents[1]
ROOT_SCRIPTS = ROOT / "scripts"
SKILL_SCRIPTS = ROOT / "skills" / "auto-g16-rtwin-pbs" / "scripts"
TEST_TEMP_PARENT = Path(tempfile.gettempdir()).resolve()
if TEST_TEMP_PARENT == ROOT or ROOT in TEST_TEMP_PARENT.parents:
    raise RuntimeError(
        "protected-invocation tests require a system temp root"
    )
sys.path.insert(0, str(ROOT_SCRIPTS))
sys.path.insert(0, str(SKILL_SCRIPTS))

import execution_facade as FACADE  # noqa: E402
import gaussian_rtwin_pbs as LEGACY  # noqa: E402
import local_state_binding as LOCAL  # noqa: E402
import protected_invocation_contract as INVOCATION  # noqa: E402
import skill_package  # noqa: E402
from tests import test_local_state_binding as LOCAL_SUPPORT  # noqa: E402
from tests import test_protected_submit_contract as PROTECTED_SUPPORT  # noqa: E402


class ProtectedInvocationFixture:
    def __init__(self, root: Path) -> None:
        self.local = LOCAL_SUPPORT.LocalStateFixture(root)
        self.protected_evidence = (
            self.local.evidence.protected_submit_evidence
        )
        self.evidence = INVOCATION.ProtectedInvocationEvidence(
            protected_submit_evidence=self.protected_evidence,
            local_state_evidence=self.local.evidence,
        )

    def owner(self) -> INVOCATION.ProtectedInvocationContractOwner:
        return (
            INVOCATION.ProtectedInvocationContractOwner
            ._for_testing_with_clock(
                PROTECTED_SUPPORT.PrivateTestClock(
                    PROTECTED_SUPPORT.NOW
                ),
                _test_token=INVOCATION._TEST_OWNER_TOKEN,
            )
        )

    def close(self) -> None:
        self.local.close()


class ProtectedInvocationContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(
            prefix="auto-g16-protected-invocation-",
            dir=TEST_TEMP_PARENT,
        )
        self.root = Path(self.temporary.name).resolve()
        self.fixture = ProtectedInvocationFixture(self.root)

    def tearDown(self) -> None:
        self.fixture.close()
        self.temporary.cleanup()

    def seal(self) -> INVOCATION.SealedProtectedInvocationBundle:
        return self.fixture.owner().seal(self.fixture.evidence)

    def assert_current(
        self,
        sealed: INVOCATION.SealedProtectedInvocationBundle,
    ) -> None:
        with mock.patch.object(
            INVOCATION,
            "_utc_now",
            return_value=PROTECTED_SUPPORT.parse_utc(
                PROTECTED_SUPPORT.NOW
            ),
        ):
            sealed.assert_current()

    def test_positive_closure_is_portable_replayable_and_non_executable(
        self,
    ) -> None:
        before = sorted(
            path.relative_to(self.root)
            for path in self.root.rglob("*")
        )
        sealed = self.seal()
        sealed.assert_owner_sealed()
        self.assert_current(sealed)
        after = sorted(
            path.relative_to(self.root)
            for path in self.root.rglob("*")
        )
        self.assertEqual(after, before)
        document = sealed.document()
        self.assertEqual(
            document["schema"],
            "auto-g16-protected-invocation-bundle/1",
        )
        self.assertEqual(
            document["local_state"]["relative_local_dir"],
            (
                "outputs/safejob/"
                f"{self.fixture.local.protected.attempt_id}"
            ),
        )
        self.assertEqual(
            [item["role"] for item in document["stage_plan"]["artifacts"]],
            ["gaussian_input", "pbs_script", "checksums_manifest"],
        )
        self.assertTrue(document["scope"]["seal"])
        self.assertTrue(document["scope"]["read_only_replay"])
        self.assertFalse(any(
            document["scope"][name]
            for name in (
                "reserve",
                "stage",
                "submit",
                "status",
                "fetch",
                "cancel",
                "cleanup",
                "delete",
                "arbitrary_command",
            )
        ))
        portable = json.dumps(document, sort_keys=True)
        self.assertNotIn(str(self.root), portable)
        keys: set[str] = set()

        def visit(value: object) -> None:
            if isinstance(value, dict):
                keys.update(value)
                for item in value.values():
                    visit(item)
            elif isinstance(value, list):
                for item in value:
                    visit(item)

        visit(document)
        self.assertTrue(
            {
                "argv",
                "command",
                "shell",
                "callback",
                "backend",
                "config",
                "credential",
                "executable",
                "absolute_path",
            }.isdisjoint(keys)
        )
        self.assertFalse(
            any(
                name.startswith(
                    (
                        "invoke",
                        "execute",
                        "reserve",
                        "submit",
                        "stage",
                        "fetch",
                        "cancel",
                    )
                )
                and callable(getattr(sealed, name, None))
                for name in dir(sealed)
            )
        )

    def test_public_input_has_no_free_path_stage_or_effect_surface(self) -> None:
        self.assertEqual(
            tuple(
                inspect.signature(
                    FACADE.seal_protected_invocation_bundle
                ).parameters
            ),
            ("evidence",),
        )
        self.assertEqual(
            tuple(
                INVOCATION.ProtectedInvocationEvidence
                .__dataclass_fields__
            ),
            ("protected_submit_evidence", "local_state_evidence"),
        )
        for constructor in (
            INVOCATION.SealedLegacyStagePlan,
            INVOCATION.SealedProtectedInvocationBundle,
        ):
            with self.assertRaises(TypeError):
                constructor()
        source = inspect.getsource(
            FACADE.seal_protected_invocation_bundle
        )
        self.assertIn("_exact_protected_invocation_contract()", source)
        for forbidden in (
            "LegacyTransportAdapter",
            "integrate_successor_once",
            "reserve_once",
            "backend(",
        ):
            self.assertNotIn(forbidden, source)

    def test_same_call_requires_one_exact_pr4d_evidence_object(self) -> None:
        other = self.fixture.local.protected.evidence()
        mismatched_local = LOCAL.LocalStateBindingEvidence(
            workspace_root=self.fixture.local.workspace_root,
            ledger_path=self.fixture.local.ledger_path,
            protected_submit_evidence=other,
        )
        evidence = INVOCATION.ProtectedInvocationEvidence(
            protected_submit_evidence=self.fixture.protected_evidence,
            local_state_evidence=mismatched_local,
        )
        with self.assertRaisesRegex(
            INVOCATION.ProtectedInvocationError,
            "exact same PR4D evidence",
        ):
            self.fixture.owner().seal(evidence)

    def test_replay_fails_when_predecessor_authority_is_not_current(
        self,
    ) -> None:
        sealed = self.seal()
        with mock.patch.object(
            INVOCATION,
            "_utc_now",
            return_value=PROTECTED_SUPPORT.parse_utc(
                PROTECTED_SUPPORT.EXPIRES_AT
            ),
        ):
            with self.assertRaisesRegex(
                INVOCATION.ProtectedInvocationError,
                "authority/evidence replay failed closed",
            ):
                sealed.assert_current()

    def test_predecessor_evidence_replacement_and_drift_fail_closed(
        self,
    ) -> None:
        approval = self.fixture.protected_evidence.live_approval_path
        original = approval.read_bytes()
        sealed = self.seal()
        replacement = approval.with_name("replacement-live-approval.json")
        replacement.write_bytes(original)
        os.replace(replacement, approval)
        with self.assertRaisesRegex(
            INVOCATION.ProtectedInvocationError,
            "predecessor file identity differs",
        ):
            self.assert_current(sealed)

        resealed = self.seal()
        approval.write_bytes(original + b" ")
        with self.assertRaisesRegex(
            INVOCATION.ProtectedInvocationError,
            "authority/evidence replay failed closed|complete identity differs",
        ):
            self.assert_current(resealed)

    def test_wrong_project_input_idempotency_resource_and_cross_root_fail(
        self,
    ) -> None:
        base = self.fixture.protected_evidence
        wrong_transport = copy.deepcopy(base.transport_artifacts)
        wrong_transport["successor_authorization"]["project"] = "other"
        mutations = {
            "project": dataclasses.replace(base, project="other"),
            "idempotency": dataclasses.replace(
                base,
                idempotency_key="other-placeholder-key",
            ),
            "task": dataclasses.replace(
                base,
                scientific_task_id="scientific-task-" + ("f" * 64),
            ),
            "resource": dataclasses.replace(
                base,
                resource_gate={
                    **base.resource_gate,
                    "status": "blocked",
                },
            ),
            "transport": dataclasses.replace(
                base,
                transport_artifacts=wrong_transport,
            ),
        }
        for label, changed in mutations.items():
            with self.subTest(case=label):
                local = LOCAL.LocalStateBindingEvidence(
                    workspace_root=self.fixture.local.workspace_root,
                    ledger_path=self.fixture.local.ledger_path,
                    protected_submit_evidence=changed,
                )
                with self.assertRaises(
                    INVOCATION.ProtectedInvocationError
                ):
                    self.fixture.owner().seal(
                        INVOCATION.ProtectedInvocationEvidence(
                            protected_submit_evidence=changed,
                            local_state_evidence=local,
                        )
                    )

        other_root = self.root / "other-workspace"
        other_root.mkdir()
        local = LOCAL.LocalStateBindingEvidence(
            workspace_root=other_root,
            ledger_path=self.fixture.local.ledger_path,
            protected_submit_evidence=base,
        )
        with self.assertRaises(INVOCATION.ProtectedInvocationError):
            self.fixture.owner().seal(
                INVOCATION.ProtectedInvocationEvidence(base, local)
            )

        self.fixture.local.protected.input_path.write_text(
            self.fixture.local.protected.input_path.read_text(
                encoding="utf-8"
            ).replace("placeholder minimum", "changed minimum"),
            encoding="utf-8",
        )
        with self.assertRaises(INVOCATION.ProtectedInvocationError):
            self.seal()

    def test_ledger_duplicate_extra_replace_and_drift_fail_closed(self) -> None:
        sealed = self.seal()
        ledger = self.fixture.local.ledger_path
        original = ledger.read_bytes()
        ledger.write_bytes(original + b" ")
        with self.assertRaises(Exception):
            self.assert_current(sealed)

        ledger.write_bytes(original)
        same_bytes = self.fixture.local.local_dir / "replacement.json"
        same_bytes.write_bytes(original)
        os.replace(same_bytes, ledger)
        with self.assertRaises(Exception):
            self.assert_current(sealed)

        ledger.write_text(
            '{"schema":"gaussian-execution-batch/3",'
            '"schema":"gaussian-execution-batch/3"}',
            encoding="utf-8",
        )
        with self.assertRaises(INVOCATION.ProtectedInvocationError):
            self.seal()

    def test_unapproved_local_state_extra_and_symlink_fail_closed(self) -> None:
        extra = self.fixture.local.local_dir / "job.json"
        extra.write_text("{}", encoding="utf-8")
        with self.assertRaises(INVOCATION.ProtectedInvocationError):
            self.seal()
        extra.unlink()
        real = self.fixture.local.ledger_path
        moved = self.fixture.local.local_dir / "ledger-real.json"
        real.rename(moved)
        real.symlink_to(moved)
        with self.assertRaises(INVOCATION.ProtectedInvocationError):
            self.seal()

    def test_stage_companion_drift_and_same_byte_replace_fail_closed(
        self,
    ) -> None:
        companion = (
            self.fixture.local.protected.input_path.with_suffix(".xyz")
        )
        companion.write_text("1\nplaceholder\nH 0 0 0\n", encoding="utf-8")
        sealed = self.seal()
        roles = [
            artifact.role for artifact in sealed.stage_plan.artifacts
        ]
        self.assertEqual(
            roles,
            [
                "gaussian_input",
                "companion_xyz",
                "pbs_script",
                "checksums_manifest",
            ],
        )
        original = companion.read_bytes()
        companion.write_bytes(original + b" ")
        with self.assertRaises(INVOCATION.ProtectedInvocationError):
            self.assert_current(sealed)
        companion.write_bytes(original)
        replacement = companion.with_name("replacement.xyz")
        replacement.write_bytes(original)
        os.replace(replacement, companion)
        with self.assertRaises(INVOCATION.ProtectedInvocationError):
            self.assert_current(sealed)

    def test_large_companion_uses_private_read_only_snapshot(self) -> None:
        companion = (
            self.fixture.local.protected.input_path.with_suffix(".xyz")
        )
        with companion.open("wb") as handle:
            handle.write(b"0\nplaceholder\n")
            handle.truncate(16 * 1024 * 1024 + 4096)
        before = {
            path.relative_to(self.root)
            for path in self.root.rglob("*")
        }
        sealed = self.seal()
        large = next(
            artifact
            for artifact in sealed.stage_plan.artifacts
            if artifact.role == "companion_xyz"
        )
        self.assertIsNone(large.data)
        self.assertIsNotNone(large.private_snapshot)
        self.assertEqual(large.size_bytes, companion.stat().st_size)
        self.assert_current(sealed)
        after = {
            path.relative_to(self.root)
            for path in self.root.rglob("*")
        }
        self.assertEqual(after, before)

    def test_unique_stage_planner_covers_companions_checkpoint_and_order(
        self,
    ) -> None:
        stage_root = self.root / "stage-plan"
        stage_root.mkdir()
        input_path = stage_root / "job.gjf"
        input_path.write_text(
            "%chk=job.chk\n"
            "%oldchk=old.chk\n"
            "%mem=12GB\n"
            "%nprocshared=8\n"
            "#p hf/sto-3g geom=allcheck guess=read\n\n",
            encoding="utf-8",
        )
        checkpoint = stage_root / "old.chk"
        checkpoint.write_bytes(b"placeholder checkpoint bytes")
        manifest = {
            "schema": "gaussian-allcheck-input-manifest/1",
            "geometry_source": "geom_allcheck_from_reviewed_checkpoint",
            "no_explicit_molecule_specification": True,
            "input_sha256": hashlib.sha256(
                input_path.read_bytes()
            ).hexdigest(),
            "checkpoint_file": "old.chk",
            "checkpoint_sha256": hashlib.sha256(
                checkpoint.read_bytes()
            ).hexdigest(),
            "charge": 0,
            "multiplicity": 1,
            "atom_count": 1,
            "atom_order": [
                {"index": 1, "element": "H", "atomic_number": 1}
            ],
            "warnings": [],
        }
        input_path.with_suffix(".json").write_text(
            json.dumps(manifest),
            encoding="utf-8",
        )
        input_path.with_suffix(".xyz").write_text(
            "1\nplaceholder\nH 0 0 0\n",
            encoding="utf-8",
        )
        audit = LEGACY.parse_gaussian(input_path)
        sources = LEGACY._legacy_stage_source_paths(input_path, audit)
        resources = {
            "policy_id": "placeholder-policy",
            "policy_sha256": "a" * 64,
            "gate_id": "placeholder-gate",
            "gate_sha256": "b" * 64,
            "resource_tier": "simple",
            "cores": 8,
            "memory_gb": 12,
            "walltime_seconds": 3600,
        }
        plan = LEGACY.plan_legacy_stage_bytes(
            project="stagejob",
            audit=audit,
            source_paths=sources,
            resource_binding=resources,
        )
        roles = [item["role"] for item in plan["artifacts"]]
        self.assertEqual(
            roles,
            [
                "gaussian_input",
                "companion_json",
                "companion_xyz",
                "old_checkpoint",
                "pbs_script",
                "checksums_manifest",
            ],
        )
        checksums = plan["artifacts"][-1]["bytes"].decode("utf-8")
        self.assertEqual(len(checksums.splitlines()), 5)
        before = plan["manifest_sha256"]
        checkpoint.write_bytes(b"changed checkpoint bytes")
        manifest["checkpoint_sha256"] = hashlib.sha256(
            checkpoint.read_bytes()
        ).hexdigest()
        input_path.with_suffix(".json").write_text(
            json.dumps(manifest),
            encoding="utf-8",
        )
        audit = LEGACY.parse_gaussian(input_path)
        changed = LEGACY.plan_legacy_stage_bytes(
            project="stagejob",
            audit=audit,
            source_paths=LEGACY._legacy_stage_source_paths(
                input_path,
                audit,
            ),
            resource_binding=resources,
        )
        self.assertNotEqual(changed["manifest_sha256"], before)
        real_checkpoint = stage_root / "real-old.chk"
        real_checkpoint.write_bytes(checkpoint.read_bytes())
        checkpoint.unlink()
        checkpoint.symlink_to(real_checkpoint)
        with self.assertRaises(SystemExit):
            LEGACY.parse_gaussian(input_path)

    def test_stage_consumes_the_same_plan_bytes_without_a_second_engine(
        self,
    ) -> None:
        input_path = self.fixture.local.protected.input_path
        audit = LEGACY.parse_gaussian(input_path)
        resources = copy.deepcopy(
            self.fixture.local.protected.gate["requested_resources"]
        )
        resources.pop("estimated_core_hours")
        resources.update(
            {
                "policy_id": self.fixture.local.protected.policy[
                    "policy_id"
                ],
                "policy_sha256": self.fixture.local.protected.policy[
                    "payload_sha256"
                ],
                "gate_id": self.fixture.local.protected.gate["gate_id"],
                "gate_sha256": self.fixture.local.protected.gate[
                    "gate_sha256"
                ],
            }
        )
        before = {
            path.relative_to(input_path.parent)
            for path in input_path.parent.rglob("*")
        }
        plan = LEGACY.plan_legacy_stage_bytes(
            project="stagecopy",
            audit=audit,
            source_paths=LEGACY._legacy_stage_source_paths(
                input_path,
                audit,
            ),
            resource_binding=resources,
        )
        after_plan = {
            path.relative_to(input_path.parent)
            for path in input_path.parent.rglob("*")
        }
        self.assertEqual(after_plan, before)
        target = self.root / "planned-stage"
        _, files = LEGACY.stage(
            input_path,
            "stagecopy",
            target,
            resources,
        )
        self.assertEqual(
            [path.name for path in files],
            [item["basename"] for item in plan["artifacts"]],
        )
        self.assertEqual(
            [path.read_bytes() for path in files],
            [item["bytes"] for item in plan["artifacts"]],
        )

    def test_portable_stage_order_hash_size_and_basename_are_closed(
        self,
    ) -> None:
        document = self.seal().document()
        cases = {
            "order": ("order", 9),
            "hash": ("sha256", "f" * 64),
            "size": ("size_bytes", 999),
            "basename": ("relative_name", "../escape"),
            "role": ("role", "command"),
        }
        for label, (field, value) in cases.items():
            with self.subTest(case=label):
                changed = copy.deepcopy(document)
                changed["stage_plan"]["artifacts"][0][field] = value
                with self.assertRaises(
                    INVOCATION.ProtectedInvocationError
                ):
                    INVOCATION.validate_protected_invocation_bundle(
                        changed
                    )

    def test_cross_origin_or_sealed_predecessor_objects_cannot_be_spliced(
        self,
    ) -> None:
        sealed_protected = self.fixture.local.protected.evidence()
        fake = types.SimpleNamespace(
            snapshot=lambda: sealed_protected.snapshot()
        )
        local = LOCAL.LocalStateBindingEvidence(
            workspace_root=self.fixture.local.workspace_root,
            ledger_path=self.fixture.local.ledger_path,
            protected_submit_evidence=fake,
        )
        with self.assertRaises((TypeError, INVOCATION.ProtectedInvocationError)):
            self.fixture.owner().seal(
                INVOCATION.ProtectedInvocationEvidence(fake, local)
            )
        with self.assertRaises(INVOCATION.ProtectedInvocationError):
            self.fixture.owner().seal(
                INVOCATION.ProtectedInvocationEvidence(
                    self.seal().protected_submit_bundle,
                    self.fixture.local.evidence,
                )
            )

    def test_concurrent_replay_and_exception_restore_cache_environment(
        self,
    ) -> None:
        names = (
            "protected_submit_contract",
            "local_state_binding",
        )
        previous = {
            name: sys.modules.get(name)
            for name in names
        }
        shadows = {}
        for name in names:
            fake = types.ModuleType(name)
            fake.__file__ = f"/private/tmp/{name}-shadow.py"
            fake.__spec__ = types.SimpleNamespace(origin=fake.__file__)
            shadows[name] = fake
            sys.modules[name] = fake
        environment_names = (
            "AUTO_G16_RUNTIME_CONFIG",
            "AUTO_G16_RTWIN_SSH_CONFIG",
            "GAUSSIAN_RTWIN_SSH_CONFIG",
            "AUTO_G16_WINDOWS_PROJECT_ROOT",
            "AUTO_G16_WINDOWS_SERVER_CONFIG",
        )
        saved_environment = {
            name: os.environ.get(name)
            for name in environment_names
        }
        try:
            for name in environment_names:
                os.environ[name] = f"placeholder-{name.lower()}"
            with ThreadPoolExecutor(max_workers=4) as pool:
                sealed = list(
                    pool.map(
                        lambda _: self.fixture.owner().seal(
                            self.fixture.evidence
                        ),
                        range(4),
                    )
                )
            self.assertEqual(
                len({item.invocation_id for item in sealed}),
                1,
            )
            for name in names:
                self.assertIs(sys.modules[name], shadows[name])
            for name in environment_names:
                self.assertEqual(
                    os.environ[name],
                    f"placeholder-{name.lower()}",
                )
            with self.assertRaisesRegex(RuntimeError, "placeholder"):
                with INVOCATION._exact_adjacent(
                    "protected_submit_contract"
                ):
                    raise RuntimeError("placeholder exception")
            self.assertIs(
                sys.modules["protected_submit_contract"],
                shadows["protected_submit_contract"],
            )
        finally:
            for name, value in previous.items():
                if value is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = value
            for name, value in saved_environment.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value

    def test_package_relocation_and_shadow_cache_keep_exact_origin(self) -> None:
        self.assertEqual(
            FACADE._protected_invocation_contract_path(),
            (ROOT / "scripts/protected_invocation_contract.py").resolve(),
        )
        @contextlib.contextmanager
        def current_checkout_owner():
            with mock.patch.object(
                INVOCATION,
                "_utc_now",
                return_value=PROTECTED_SUPPORT.parse_utc(
                    PROTECTED_SUPPORT.NOW
                ),
            ):
                yield INVOCATION

        with mock.patch.object(
            FACADE,
            "_exact_protected_invocation_contract",
            current_checkout_owner,
        ), mock.patch.object(
            INVOCATION.ProtectedInvocationContractOwner,
            "production",
            return_value=self.fixture.owner(),
        ):
            facade_sealed = FACADE.seal_protected_invocation_bundle(
                evidence=self.fixture.evidence,
            )
        self.assertEqual(
            facade_sealed.document()["schema"],
            "auto-g16-protected-invocation-bundle/1",
        )
        previous_invocation = sys.modules.get(
            "protected_invocation_contract"
        )
        invocation_shadow = types.ModuleType(
            "protected_invocation_contract"
        )
        invocation_shadow.__file__ = "/private/tmp/invocation-shadow.py"
        invocation_shadow.__spec__ = types.SimpleNamespace(
            origin=invocation_shadow.__file__
        )
        sys.modules["protected_invocation_contract"] = invocation_shadow

        def exact_origin(_: int) -> Path:
            with FACADE._exact_protected_invocation_contract() as module:
                return Path(module.__file__).resolve()

        try:
            with ThreadPoolExecutor(max_workers=4) as pool:
                origins = list(pool.map(exact_origin, range(4)))
            self.assertIs(
                sys.modules["protected_invocation_contract"],
                invocation_shadow,
            )
            with self.assertRaisesRegex(
                RuntimeError,
                "placeholder facade loader exception",
            ):
                with FACADE._exact_protected_invocation_contract():
                    raise RuntimeError(
                        "placeholder facade loader exception"
                    )
            self.assertIs(
                sys.modules["protected_invocation_contract"],
                invocation_shadow,
            )
        finally:
            if previous_invocation is None:
                sys.modules.pop("protected_invocation_contract", None)
            else:
                sys.modules[
                    "protected_invocation_contract"
                ] = previous_invocation
        self.assertEqual(
            origins,
            [(ROOT / "scripts/protected_invocation_contract.py").resolve()]
            * 4,
        )
        package = skill_package.package_files(
            ROOT,
            "auto-g16-rtwin-pbs",
        )
        self.assertEqual(
            package[
                Path("scripts/protected_invocation_contract.py")
            ].read_bytes(),
            (
                ROOT / "scripts/protected_invocation_contract.py"
            ).read_bytes(),
        )
        relocated = self.root / "relocated"
        for relative, source in package.items():
            target = relocated / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        script = (
            "import sys,types\n"
            f"p={str(relocated / 'scripts')!r}\n"
            "sys.path.insert(0,p)\n"
            "fake=types.ModuleType('protected_invocation_contract')\n"
            "fake.__file__='/private/tmp/shadow.py'\n"
            "fake.__spec__=types.SimpleNamespace(origin=fake.__file__)\n"
            "sys.modules['protected_invocation_contract']=fake\n"
            "import execution_facade as f\n"
            "with f._exact_protected_invocation_contract() as m:\n"
            " print(m.__file__)\n"
            "assert sys.modules['protected_invocation_contract'] is fake\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=TEST_TEMP_PARENT,
            text=True,
            capture_output=True,
            env={
                **os.environ,
                "AUTO_G16_RUNTIME_CONFIG": str(
                    self.root / "absent-placeholder-runtime.json"
                ),
            },
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            Path(result.stdout.strip()).resolve(),
            (
                relocated
                / "scripts"
                / "protected_invocation_contract.py"
            ).resolve(),
        )
        source_root = self.root / "source-relocated"
        source_scripts = source_root / "scripts"
        source_scripts.mkdir(parents=True)
        for name in (
            "protected_invocation_contract.py",
            "protected_submit_contract.py",
            "local_state_binding.py",
        ):
            shutil.copy2(ROOT / "scripts" / name, source_scripts / name)
        source_script = (
            "import sys\n"
            f"p={str(source_scripts)!r}\n"
            "sys.path.insert(0,p)\n"
            "import protected_invocation_contract as i\n"
            "with i._exact_adjacent('protected_submit_contract') as pmod:\n"
            " print(pmod.__file__)\n"
            "with i._exact_adjacent('local_state_binding') as lmod:\n"
            " print(lmod.__file__)\n"
        )
        source_result = subprocess.run(
            [sys.executable, "-c", source_script],
            cwd=TEST_TEMP_PARENT,
            text=True,
            capture_output=True,
            env={
                **os.environ,
                "AUTO_G16_RUNTIME_CONFIG": str(
                    self.root / "absent-source-placeholder-runtime.json"
                ),
            },
        )
        self.assertEqual(
            source_result.returncode,
            0,
            source_result.stderr,
        )
        self.assertEqual(
            [
                Path(line).resolve()
                for line in source_result.stdout.splitlines()
            ],
            [
                (source_scripts / "protected_submit_contract.py").resolve(),
                (source_scripts / "local_state_binding.py").resolve(),
            ],
        )
        caller_shadow = self.root / "caller-shadow"
        caller_shadow.mkdir()
        (caller_shadow / "protected_invocation_contract.py").write_text(
            "raise RuntimeError('caller shadow must not load')\n",
            encoding="utf-8",
        )
        for paths in (
            [caller_shadow, ROOT_SCRIPTS, SKILL_SCRIPTS],
            [caller_shadow, SKILL_SCRIPTS, ROOT_SCRIPTS],
        ):
            with self.subTest(combined=[str(item) for item in paths]):
                combined_script = (
                    "import sys,types\n"
                    f"sys.path[:0]={[str(item) for item in paths]!r}\n"
                    "fake=types.ModuleType('protected_invocation_contract')\n"
                    "fake.__file__='/private/tmp/preloaded-shadow.py'\n"
                    "fake.__spec__=types.SimpleNamespace(origin=fake.__file__)\n"
                    "sys.modules['protected_invocation_contract']=fake\n"
                    "import execution_facade as f\n"
                    "with f._exact_protected_invocation_contract() as m:\n"
                    " print(m.__file__)\n"
                    "assert sys.modules['protected_invocation_contract'] is fake\n"
                )
                combined_result = subprocess.run(
                    [sys.executable, "-c", combined_script],
                    cwd=caller_shadow,
                    text=True,
                    capture_output=True,
                    env={
                        **os.environ,
                        "AUTO_G16_RUNTIME_CONFIG": str(
                            self.root
                            / "absent-combined-placeholder-runtime.json"
                        ),
                    },
                )
                self.assertEqual(
                    combined_result.returncode,
                    0,
                    combined_result.stderr,
                )
                self.assertEqual(
                    Path(combined_result.stdout.strip()).resolve(),
                    (
                        ROOT
                        / "scripts/protected_invocation_contract.py"
                    ).resolve(),
                )

    def test_predecessor_contract_hashes_remain_frozen(self) -> None:
        expected = {
            "scripts/protected_submit_contract.py": (
                "60f0da3b9306f19eb54efe9de94593b1f428c066dda919d4ac384289dd450c2a"
            ),
            "contracts/execution/protected-submit-bundle.schema.json": (
                "eb88ae46acc4f8a17166ffb2d124430782e8bb563817eba50fa34a80e8851ac4"
            ),
            "scripts/local_state_binding.py": (
                "6a23eb9307fdf930d4055589dd08baff8dea9275470db7ea9154f6ffa324b6b5"
            ),
            "contracts/execution/local-state-binding.schema.json": (
                "1fbafcbefeba67115e33a9ad5402dc19e0ac426945f51c995fea3c560132e270"
            ),
        }
        for relative, expected_hash in expected.items():
            with self.subTest(path=relative):
                self.assertEqual(
                    hashlib.sha256((ROOT / relative).read_bytes()).hexdigest(),
                    expected_hash,
                )


if __name__ == "__main__":
    unittest.main()
