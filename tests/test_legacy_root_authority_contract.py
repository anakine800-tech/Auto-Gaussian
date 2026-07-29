#!/usr/bin/env python3
"""Offline adversarial tests for the fixed legacy root authority owner."""

from __future__ import annotations

import ast
import copy
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
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).parents[1]
ROOT_SCRIPTS = ROOT / "scripts"
SKILL_SCRIPTS = ROOT / "skills" / "auto-g16-rtwin-pbs" / "scripts"
TEMP_PARENT = Path(tempfile.gettempdir()).resolve()
if TEMP_PARENT == ROOT or ROOT in TEMP_PARENT.parents:
    raise RuntimeError("legacy-root tests require a system temporary root")
sys.path.insert(0, str(ROOT_SCRIPTS))
sys.path.insert(0, str(SKILL_SCRIPTS))

import legacy_rtwin_pbs as LEGACY  # noqa: E402
import execution_facade as FACADE  # noqa: E402
from tests.test_protected_runtime_state_contract import RuntimeStateFixture  # noqa: E402
import protected_owner_consumer_contract as CONSUMER  # noqa: E402
import protected_production_ingress_contract as INGRESS  # noqa: E402
import legacy_root_authority_contract as ROOT_AUTHORITY  # noqa: E402
import skill_package as SKILL_PACKAGE  # noqa: E402


SHA_A = "a" * 64
NONCE = "b" * 32


class MutableClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 7, 29, 6, 0, 0, tzinfo=timezone.utc)
        self.lock = threading.Lock()

    def __call__(self) -> datetime:
        with self.lock:
            return self.value

    def advance(self, seconds: int) -> None:
        with self.lock:
            self.value += timedelta(seconds=seconds)


class LegacyRootFixture:
    def __init__(self, root: Path) -> None:
        self.runtime = RuntimeStateFixture(root)
        runtime = self.runtime.owner().seal(self.runtime.handoff())
        predecessor = (
            CONSUMER.ProtectedOwnerConsumerContractOwner.production()
            .prepare_once(runtime)
        )
        self.ingress = (
            INGRESS.ProtectedProductionIngressContractOwner.production()
            .seal_once(predecessor)
        )
        self.clock = MutableClock()
        self.owner = self.new_owner()
        self.root_snapshot = self.owner._root_snapshot_for_testing(
            ["home-device", "user100-directory", "sdl-directory"],
            _test_token=ROOT_AUTHORITY._TEST_TOKEN,
        )
        self.evidence = self.owner.issue_stable_evidence(self.root_snapshot)
        self.authorization = self.owner.build_authorization(
            authorization_id="legacy-root-authorization-001",
            profile_id="legacy-primary",
            profile_payload_sha256=SHA_A,
            stable_evidence=self.evidence,
            protected_production_ingress=self.ingress,
            approved_at="2026-07-29T05:59:00.000000Z",
            not_before="2026-07-29T06:00:00.000000Z",
            expires_at="2026-07-29T07:00:00.000000Z",
            maximum_receipt_age_seconds=60,
        )

    def close(self) -> None:
        self.runtime.close()

    def new_owner(self) -> ROOT_AUTHORITY.LegacyRootAuthorityContractOwner:
        return ROOT_AUTHORITY.LegacyRootAuthorityContractOwner._for_testing(
            clock=self.clock,
            nonce_source=lambda: NONCE,
            _test_token=ROOT_AUTHORITY._TEST_TOKEN,
        )

    def observation(
        self,
        owner: ROOT_AUTHORITY.LegacyRootAuthorityContractOwner,
        **changes: bool,
    ) -> object:
        return owner._workspace_observation_for_testing(
            root=self.root_snapshot,
            project=self.ingress.document()["identity"]["project"],
            _test_token=ROOT_AUTHORITY._TEST_TOKEN,
            **changes,
        )

    def capability(
        self,
    ) -> ROOT_AUTHORITY.SingleUseLegacyWorkspaceDescriptorCapability:
        owner = self.new_owner()
        return owner.issue_fresh_capability_once(
            stable_evidence=self.evidence,
            authorization=self.authorization,
            protected_production_ingress=self.ingress,
            observation=self.observation(owner),
        )


class LegacyRootAuthorityContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(
            prefix="auto-g16-legacy-root-",
            dir=TEMP_PARENT,
        )
        self.fixture = LegacyRootFixture(Path(self.temporary.name).resolve())

    def tearDown(self) -> None:
        self.fixture.close()
        self.temporary.cleanup()

    def test_gap_matrix_closes_fixed_root_stable_fresh_and_owner_consumption(self) -> None:
        evidence = self.fixture.evidence.document()
        authorization = self.fixture.authorization
        capability = self.fixture.capability()
        receipt = capability.portable_receipt()
        self.assertEqual(
            evidence["fixed_root_policy"],
            {
                "backend_kind": "legacy_rtwin_pbs",
                "allowed_root": "/home/user100/SDL",
                "remote_root_override_allowed": False,
                "cli_override_allowed": False,
                "environment_override_allowed": False,
                "runtime_override_allowed": False,
                "caller_override_allowed": False,
            },
        )
        self.assertEqual(
            authorization["stable_root_evidence"]["evidence_payload_sha256"],
            evidence["evidence_payload_sha256"],
        )
        self.assertEqual(
            receipt["stable_root_evidence"]["evidence_payload_sha256"],
            evidence["evidence_payload_sha256"],
        )
        self.assertEqual(
            receipt["protected_production_ingress"]["contract_id"],
            self.fixture.ingress.document()["contract_id"],
        )
        lease = capability.consume_once()
        self.assertIs(
            type(lease),
            ROOT_AUTHORITY.ConsumedLegacyWorkspaceDescriptorLease,
        )
        self.assertFalse(lease.remote_effect_authorized)
        self.assertFalse(lease.path_reopen_allowed)
        lease.assert_current()

    def test_stable_evidence_is_deterministic_and_excludes_fresh_values(self) -> None:
        other = self.fixture.owner.issue_stable_evidence(
            self.fixture.root_snapshot
        )
        self.assertEqual(other.document(), self.fixture.evidence.document())
        raw = ROOT_AUTHORITY.canonical_bytes(other.document())
        for forbidden in (
            b'"observed_at"',
            b'"expires_at"',
            b'"nonce"',
            b'"receipt_id"',
            b'"project"',
            b'"attempt_id"',
            b'"input_sha256"',
        ):
            self.assertNotIn(forbidden, raw)

    def test_exact_ingress_is_replayed_without_claiming_factory_port(self) -> None:
        before_claimed = self.fixture.ingress._claimed
        before_plans = len(LEGACY._LEGACY_EFFECT_PLAN_BINDINGS)
        before_owners = len(LEGACY._LEGACY_EFFECT_OWNER_BINDINGS)
        capability = self.fixture.capability()
        capability.consume_once().assert_current()
        self.assertEqual(self.fixture.ingress._claimed, before_claimed)
        self.assertEqual(len(LEGACY._LEGACY_EFFECT_PLAN_BINDINGS), before_plans)
        self.assertEqual(len(LEGACY._LEGACY_EFFECT_OWNER_BINDINGS), before_owners)

    def test_portable_and_synthetic_evidence_never_authorize_remote_effect(self) -> None:
        capability = self.fixture.capability()
        receipt = capability.portable_receipt()
        self.assertEqual(receipt["authority"], ROOT_AUTHORITY.AUTHORITY)
        self.assertFalse(
            receipt["authority"]["portable_evidence_authorizes_remote_effect"]
        )
        self.assertFalse(
            receipt["authority"]["synthetic_observation_authorizes_remote_effect"]
        )
        self.assertFalse(receipt["authority"]["remote_effect_performed"])
        with self.assertRaises(TypeError):
            ROOT_AUTHORITY.LegacyFreshRootObservationReceipt(receipt)
        with self.assertRaises(TypeError):
            ROOT_AUTHORITY.SingleUseLegacyWorkspaceDescriptorCapability(receipt)

    def test_exact_types_are_noncopyable_nonserializable_and_unforgeable(self) -> None:
        capability = self.fixture.capability()
        for value in (
            self.fixture.evidence,
            capability.receipt,
            capability,
        ):
            with self.subTest(value=type(value).__name__):
                with self.assertRaises(TypeError):
                    copy.copy(value)
                with self.assertRaises(TypeError):
                    copy.deepcopy(value)
                with self.assertRaises(TypeError):
                    pickle.dumps(value)
        lease = capability.consume_once()
        with self.assertRaises(TypeError):
            copy.copy(lease)
        with self.assertRaises(TypeError):
            ROOT_AUTHORITY.ConsumedLegacyWorkspaceDescriptorLease()

    def test_single_consumption_is_atomic_under_concurrency(self) -> None:
        capability = self.fixture.capability()

        def consume(_: int) -> object:
            try:
                return capability.consume_once()
            except ROOT_AUTHORITY.LegacyRootAuthorityError as exc:
                return str(exc)

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(consume, range(16)))
        leases = [
            item
            for item in results
            if type(item)
            is ROOT_AUTHORITY.ConsumedLegacyWorkspaceDescriptorLease
        ]
        self.assertEqual(len(leases), 1)
        self.assertEqual(
            sum(
                item
                == "legacy workspace descriptor capability is already consumed"
                for item in results
            ),
            15,
        )

    def test_expiry_and_clock_rollback_fail_before_consumption(self) -> None:
        capability = self.fixture.capability()
        self.fixture.clock.advance(61)
        with self.assertRaisesRegex(
            ROOT_AUTHORITY.LegacyRootAuthorityError,
            "fresh receipt is outside",
        ):
            capability.consume_once()
        self.fixture.clock.value = datetime(
            2026, 7, 29, 6, 0, 1, tzinfo=timezone.utc
        )
        with self.assertRaisesRegex(
            ROOT_AUTHORITY.LegacyRootAuthorityError,
            "trusted clock moved backward",
        ):
            capability.consume_once()

    def test_symlink_reparse_escape_identity_and_freshness_fail_closed(self) -> None:
        cases = (
            {"fresh_project": False},
            {"containment_verified": False},
            {"symlink_detected": True},
            {"reparse_point_detected": True},
            {"root_escape_detected": True},
        )
        for changes in cases:
            with self.subTest(changes=changes):
                owner = self.fixture.new_owner()
                observation = self.fixture.observation(owner, **changes)
                with self.assertRaisesRegex(
                    ROOT_AUTHORITY.LegacyRootAuthorityError,
                    "safety checks failed",
                ):
                    owner.issue_fresh_capability_once(
                        stable_evidence=self.fixture.evidence,
                        authorization=self.fixture.authorization,
                        protected_production_ingress=self.fixture.ingress,
                        observation=observation,
                    )
        owner = self.fixture.new_owner()
        drifted = owner._root_snapshot_for_testing(
            ["home-drift", "user100-directory", "sdl-directory"],
            _test_token=ROOT_AUTHORITY._TEST_TOKEN,
        )
        observation = owner._workspace_observation_for_testing(
            root=drifted,
            project=self.fixture.ingress.document()["identity"]["project"],
            _test_token=ROOT_AUTHORITY._TEST_TOKEN,
        )
        with self.assertRaisesRegex(
            ROOT_AUTHORITY.LegacyRootAuthorityError,
            "root identity drifted",
        ):
            owner.issue_fresh_capability_once(
                stable_evidence=self.fixture.evidence,
                authorization=self.fixture.authorization,
                protected_production_ingress=self.fixture.ingress,
                observation=observation,
            )

    def test_descriptor_and_ingress_replacement_fail_closed(self) -> None:
        capability = self.fixture.capability()
        foreign = self.fixture.capability()
        object.__setattr__(
            capability,
            "_descriptor_set",
            foreign._descriptor_set,
        )
        with self.assertRaisesRegex(
            ROOT_AUTHORITY.LegacyRootAuthorityError,
            "snapshot differs",
        ):
            capability.consume_once()
        capability = self.fixture.capability()
        object.__setattr__(
            capability,
            "_ingress_identity",
            object(),
        )
        with self.assertRaisesRegex(
            ROOT_AUTHORITY.LegacyRootAuthorityError,
            "snapshot differs",
        ):
            capability.consume_once()

    def test_module_class_and_source_identity_are_replayed(self) -> None:
        capability = self.fixture.capability()
        canonical = sys.modules[ROOT_AUTHORITY.MODULE_NAME]
        sys.modules[ROOT_AUTHORITY.MODULE_NAME] = mock.Mock()
        try:
            with self.assertRaisesRegex(
                ROOT_AUTHORITY.LegacyRootAuthorityError,
                "module/source identity differs",
            ):
                capability.assert_current()
        finally:
            sys.modules[ROOT_AUTHORITY.MODULE_NAME] = canonical
        original = ROOT_AUTHORITY.LegacyFreshRootObservationReceipt
        ROOT_AUTHORITY.LegacyFreshRootObservationReceipt = type(  # type: ignore[misc]
            "LegacyFreshRootObservationReceipt",
            (),
            {},
        )
        try:
            with self.assertRaisesRegex(
                ROOT_AUTHORITY.LegacyRootAuthorityError,
                "class identity differs",
            ):
                capability.assert_current()
        finally:
            ROOT_AUTHORITY.LegacyFreshRootObservationReceipt = original  # type: ignore[misc]
        drifted = replace(
            ROOT_AUTHORITY._INGRESS_BINDING,
            source=replace(
                ROOT_AUTHORITY._INGRESS_BINDING.source,
                sha256="0" * 64,
            ),
        )
        with mock.patch.object(ROOT_AUTHORITY, "_INGRESS_BINDING", drifted):
            with self.assertRaises(
                ROOT_AUTHORITY.LegacyRootAuthorityError
            ):
                capability.assert_current()

    def test_authorization_hash_root_and_ingress_tampering_fail(self) -> None:
        cases = []
        changed = copy.deepcopy(self.fixture.authorization)
        changed["fixed_root_policy"]["allowed_root"] = "/tmp"
        cases.append(changed)
        changed = copy.deepcopy(self.fixture.authorization)
        changed["protected_production_ingress"]["contract_payload_sha256"] = (
            "c" * 64
        )
        cases.append(changed)
        changed = copy.deepcopy(self.fixture.authorization)
        changed["scope"]["maximum_receipt_age_seconds"] = "301"
        cases.append(changed)
        changed = copy.deepcopy(self.fixture.authorization)
        changed["authority"]["path_reopen_allowed"] = True
        cases.append(changed)
        for document in cases:
            with self.subTest(document=document):
                with self.assertRaises(
                    ROOT_AUTHORITY.LegacyRootAuthorityError
                ):
                    ROOT_AUTHORITY.validate_legacy_root_authority_authorization(
                        document
                    )

    def test_rehashed_authorization_ingress_identity_splices_fail_issuance(
        self,
    ) -> None:
        cases = {
            "project": "OtherProject",
            "attempt_id": f"qsub-attempt-{'c' * 64}",
            "input_sha256": "d" * 64,
        }
        for field, replacement in cases.items():
            with self.subTest(field=field):
                changed = copy.deepcopy(self.fixture.authorization)
                changed["protected_production_ingress"][field] = replacement
                changed["scope"]["authorization_scope_sha256"] = (
                    ROOT_AUTHORITY.digest(
                        ROOT_AUTHORITY._authorization_scope_projection(changed)
                    )
                )
                changed = ROOT_AUTHORITY._finalize(
                    changed,
                    "authorization_payload_sha256",
                )
                owner = self.fixture.new_owner()
                with self.assertRaisesRegex(
                    ROOT_AUTHORITY.LegacyRootAuthorityError,
                    "predecessor replay differs",
                ):
                    owner.issue_fresh_capability_once(
                        stable_evidence=self.fixture.evidence,
                        authorization=changed,
                        protected_production_ingress=self.fixture.ingress,
                        observation=self.fixture.observation(owner),
                    )

    def test_rehashed_portable_receipt_ingress_project_splice_fails(self) -> None:
        receipt = self.fixture.capability().portable_receipt()
        receipt["protected_production_ingress"]["project"] = "OtherProject"
        receipt = ROOT_AUTHORITY._finalize(
            receipt,
            "receipt_payload_sha256",
        )
        with self.assertRaisesRegex(
            ROOT_AUTHORITY.LegacyRootAuthorityError,
            "cross-field identity differs",
        ):
            ROOT_AUTHORITY.validate_legacy_fresh_root_observation_receipt(
                receipt
            )

    def test_no_transport_or_effect_api_is_present(self) -> None:
        source = (
            ROOT / "scripts/legacy_root_authority_contract.py"
        ).read_text(encoding="utf-8")
        tree = ast.parse(source)
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
        methods = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        for forbidden in (
            "submit",
            "upload",
            "fetch",
            "cancel",
            "qsub",
            "qdel",
            "cleanup",
            "delete",
            "run",
        ):
            self.assertNotIn(forbidden, methods)

    def test_package_supplement_maps_only_new_owner_schemas_and_reference(self) -> None:
        package = SKILL_PACKAGE.package_files_with_supplements(
            ROOT,
            "auto-g16-rtwin-pbs",
        )
        self.assertEqual(
            package[Path("scripts/legacy_root_authority_contract.py")],
            ROOT / "scripts/legacy_root_authority_contract.py",
        )
        for name in (
            "legacy-stable-root-identity-evidence.schema.json",
            "legacy-root-authority-authorization.schema.json",
            "legacy-fresh-root-observation-receipt.schema.json",
        ):
            target = Path("contracts/legacy-root-authority") / name
            self.assertEqual(package[target], ROOT / target)
        self.assertFalse(
            (
                ROOT
                / "skills/auto-g16-rtwin-pbs/scripts/"
                "legacy_root_authority_contract.py"
            ).exists()
        )

    def test_actual_supplemented_package_imports_exact_owner_chain(self) -> None:
        installed = (
            Path(self.temporary.name).resolve()
            / "installed-auto-g16-rtwin-pbs"
        )
        installed.mkdir()
        for relative, source in SKILL_PACKAGE.package_files_with_supplements(
            ROOT,
            "auto-g16-rtwin-pbs",
        ).items():
            target = installed / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        self.assertFalse((installed / ".git").exists())
        script = textwrap.dedent(
            f"""
            import json
            import sys
            from pathlib import Path

            installed = Path({str(installed)!r})
            sys.path.insert(0, str(installed / "scripts"))
            import legacy_rtwin_pbs
            import execution_facade
            import protected_lifecycle_contract
            import protected_local_materialization
            import protected_legacy_effect_handoff
            import protected_runtime_state_contract
            import protected_owner_consumer_contract
            import protected_production_ingress_contract
            import legacy_root_authority_contract as root

            source_path = Path(root.__file__).resolve()
            source_raw = source_path.read_bytes()
            source_path.write_bytes(source_raw + b"\\n")
            try:
                root._assert_bindings_current()
            except root.LegacyRootAuthorityError:
                source_drift_rejected = True
            else:
                source_drift_rejected = False
            finally:
                source_path.write_bytes(source_raw)

            print(json.dumps({{
                "canonical_module": sys.modules[root.MODULE_NAME] is root,
                "ingress_bound": (
                    root._INGRESS_BINDING.module
                    is protected_production_ingress_contract
                ),
                "source_drift_rejected": source_drift_rejected,
                "fixed_backend": root.BACKEND_KIND == "legacy_rtwin_pbs",
                "fixed_root": root.FIXED_REMOTE_ROOT == "/home/user100/SDL",
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
                    / "auto-g16-legacy-root-installed-placeholder.json"
                ),
            },
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertTrue(output["canonical_module"])
        self.assertTrue(output["ingress_bound"])
        self.assertTrue(output["source_drift_rejected"])
        self.assertTrue(output["fixed_backend"])
        self.assertTrue(output["fixed_root"])


if __name__ == "__main__":
    unittest.main()
