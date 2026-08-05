#!/usr/bin/env python3
"""Offline adversarial tests for the Auto-G16 PR6A direct-root owner."""

from __future__ import annotations

import ast
import copy
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
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).parents[1]
SCRIPTS = ROOT / "scripts"
TEMP_PARENT = Path(tempfile.gettempdir()).resolve()
if TEMP_PARENT == ROOT or ROOT in TEMP_PARENT.parents:
    raise RuntimeError("direct-root tests require a system temporary root")
sys.path.insert(0, str(SCRIPTS))

import direct_root_owner_contract as DIRECT  # noqa: E402
import skill_package as SKILL_PACKAGE  # noqa: E402


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
TASK = "scientific-task-" + "d" * 64
ATTEMPT = "qsub-attempt-" + "e" * 64
NONCE = "f" * 32
ROOT_PATH = "/srv/auto-g16"
PROJECT = "case_001"


class MutableClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 7, 29, 0, 0, 0, tzinfo=timezone.utc)
        self.lock = threading.Lock()

    def __call__(self) -> datetime:
        with self.lock:
            return self.value

    def advance(self, seconds: int) -> None:
        with self.lock:
            self.value += timedelta(seconds=seconds)


class StepClock:
    def __init__(self, values: list[datetime]) -> None:
        self.values = list(values)
        self.lock = threading.Lock()
        self.calls = 0

    def __call__(self) -> datetime:
        with self.lock:
            index = min(self.calls, len(self.values) - 1)
            self.calls += 1
            return self.values[index]


class DirectRootFixture:
    def __init__(self) -> None:
        self.clock = MutableClock()
        self.owner = self.new_owner()
        self.expected = self.snapshot(self.owner)
        self.policy = DIRECT.build_profile_policy(
            profile_id="direct-primary",
            declared_allowed_root=ROOT_PATH,
            transport_identity_binding_sha256=SHA_A,
            gaussian_runtime_binding_sha256=SHA_B,
            resource_catalog_sha256=SHA_C,
        )
        self.evidence = self.owner.issue_stable_evidence(
            self.policy,
            self.expected,
        )
        self.profile = DIRECT.build_direct_execution_profile(
            self.policy,
            self.evidence,
        )
        self.authorization = DIRECT.build_direct_execution_authorization(
            authorization_id="direct-authorization-001",
            profile=self.profile,
            stable_evidence=self.evidence,
            project=PROJECT,
            input_basename="input.gjf",
            input_sha256=SHA_A,
            input_size_bytes=1024,
            tier="simple",
            cores=8,
            memory_gb=12,
            walltime_seconds=3600,
            scientific_task_id=TASK,
            attempt_id=ATTEMPT,
            idempotency_key="direct-case-001",
            approved_at="2026-07-28T23:59:00.000000Z",
            not_before="2026-07-29T00:00:00.000000Z",
            expires_at="2026-07-29T01:00:00.000000Z",
            maximum_receipt_age_seconds=60,
        )

    def new_owner(self) -> DIRECT.DirectRootOwnerContractOwner:
        return DIRECT.DirectRootOwnerContractOwner._for_testing(
            clock=self.clock,
            nonce_source=lambda: NONCE,
            _test_token=DIRECT._TEST_FACTORY_TOKEN,
        )

    def snapshot(
        self,
        owner: DIRECT.DirectRootOwnerContractOwner,
        *,
        seeds: list[str] | None = None,
        root: str = ROOT_PATH,
        project: str = PROJECT,
        fresh: bool = True,
        contained: bool = True,
        no_symlink: bool = True,
    ) -> object:
        return owner._snapshot_for_testing(
            canonical_root=root,
            component_identity_seeds=seeds or ["srv-identity", "auto-g16-identity"],
            project=project,
            fresh_project=fresh,
            containment_verified=contained,
            no_symlink_verified=no_symlink,
            _test_token=DIRECT._TEST_FACTORY_TOKEN,
        )

    def capability(self) -> DIRECT.SingleUseWorkspaceDescriptorCapability:
        owner = self.new_owner()
        observation = self.snapshot(owner)
        return owner.issue_fresh_capability_once(
            profile=self.profile,
            stable_evidence=self.evidence,
            authorization=self.authorization,
            observation=observation,
        )


class DirectRootOwnerContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = DirectRootFixture()

    def test_acyclic_profile_evidence_successor_and_exact_authorization(self) -> None:
        policy = self.fixture.policy
        evidence = self.fixture.evidence.document()
        profile = self.fixture.profile
        authorization = self.fixture.authorization
        self.assertEqual(
            evidence["profile_policy"]["profile_payload_sha256"],
            policy["profile_payload_sha256"],
        )
        self.assertEqual(
            profile["stable_root_identity_evidence_sha256"],
            evidence["evidence_payload_sha256"],
        )
        self.assertEqual(
            authorization["profile"]["profile_payload_sha256"],
            profile["profile_payload_sha256"],
        )
        self.assertEqual(
            authorization["root_evidence"]["evidence_payload_sha256"],
            evidence["evidence_payload_sha256"],
        )
        self.assertEqual(
            authorization["workspace"]["allowed_root"],
            ROOT_PATH,
        )
        self.assertEqual(authorization["input"]["sha256"], SHA_A)
        self.assertEqual(
            authorization["resources"],
            {
                "tier": "simple",
                "cores": "8",
                "memory_gb": "12",
                "walltime_seconds": "3600",
                "resources_binding_sha256": authorization["resources"][
                    "resources_binding_sha256"
                ],
            },
        )
        self.assertFalse(authorization["live_ready"])
        DIRECT.validate_profile_policy(policy)
        DIRECT.validate_stable_root_identity_evidence(evidence)
        DIRECT.validate_direct_execution_profile(profile)
        DIRECT.validate_direct_execution_authorization(authorization)

    def test_stable_projection_is_deterministic_and_has_no_fresh_values(self) -> None:
        other = self.fixture.owner.issue_stable_evidence(
            self.fixture.policy,
            self.fixture.expected,
        )
        self.assertEqual(
            other.document(),
            self.fixture.evidence.document(),
        )
        raw = DIRECT.canonical_bytes(other.document())
        for forbidden in (
            b'"observed_at"',
            b'"expires_at"',
            b'"nonce"',
            b'"receipt_id"',
            b'"operation"',
            b'"task_id"',
            b'"attempt_id"',
        ):
            self.assertNotIn(forbidden, raw)
        self.assertEqual(
            other.document()["stable_projection"],
            {
                "observation_time_excluded": True,
                "expiry_excluded": True,
                "nonce_excluded": True,
                "receipt_id_excluded": True,
                "per_operation_values_excluded": True,
            },
        )

    def test_fresh_receipt_binds_exact_scope_and_is_non_authorizing(self) -> None:
        capability = self.fixture.capability()
        receipt = capability.portable_receipt()
        self.assertEqual(
            receipt["profile"]["profile_payload_sha256"],
            self.fixture.profile["profile_payload_sha256"],
        )
        self.assertEqual(
            receipt["stable_root_evidence"]["evidence_payload_sha256"],
            self.fixture.evidence.document()["evidence_payload_sha256"],
        )
        self.assertEqual(
            receipt["authorization"]["authorization_scope_sha256"],
            self.fixture.authorization["scope"]["authorization_scope_sha256"],
        )
        self.assertEqual(receipt["operation"]["scientific_task_id"], TASK)
        self.assertEqual(receipt["operation"]["attempt_id"], ATTEMPT)
        self.assertEqual(receipt["operation"]["nonce"], NONCE)
        self.assertEqual(
            receipt["authority"],
            {
                "portable_receipt_authorizes_effect": False,
                "descriptor_capability_required": True,
                "single_consumption_required": True,
                "descriptor_relative_operations_required": True,
                "path_reopen_allowed": False,
                "automatic_retry": False,
                "remote_effect_performed": False,
            },
        )
        copied = copy.deepcopy(receipt)
        self.assertIsInstance(copied, dict)
        with self.assertRaises(TypeError):
            DIRECT.SingleUseWorkspaceDescriptorCapability(copied)
        DIRECT.validate_fresh_root_observation_receipt(
            receipt,
            now=self.fixture.clock(),
        )

    def test_exact_types_are_noncopyable_nonserializable_and_unforgeable(self) -> None:
        capability = self.fixture.capability()
        values = (
            self.fixture.evidence,
            capability.receipt,
            capability,
        )
        for value in values:
            with self.subTest(value=type(value).__name__):
                with self.assertRaises(TypeError):
                    copy.copy(value)
                with self.assertRaises(TypeError):
                    copy.deepcopy(value)
                with self.assertRaises(TypeError):
                    pickle.dumps(value)
        lease = capability.consume_once()
        self.assertIs(type(lease), DIRECT.ConsumedWorkspaceDescriptorLease)
        self.assertFalse(lease.remote_effect_authorized)
        self.assertFalse(lease.path_reopen_allowed)
        lease.assert_owner_sealed()
        with self.assertRaises(TypeError):
            DIRECT.ConsumedWorkspaceDescriptorLease()

    def test_single_use_is_atomic_under_concurrency(self) -> None:
        capability = self.fixture.capability()

        def consume(_: int) -> object:
            try:
                return capability.consume_once()
            except DIRECT.DirectRootOwnerError as exc:
                return str(exc)

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(consume, range(16)))
        leases = [
            value
            for value in results
            if type(value) is DIRECT.ConsumedWorkspaceDescriptorLease
        ]
        self.assertEqual(len(leases), 1)
        self.assertEqual(
            sum(value == "workspace descriptor capability is already consumed" for value in results),
            15,
        )

    def test_capability_field_reset_cannot_reopen_consumption(self) -> None:
        capability = self.fixture.capability()
        capability.consume_once().assert_owner_sealed()
        with self.assertRaises(AttributeError):
            object.__setattr__(capability, "_consumed", False)
        with self.assertRaisesRegex(
            DIRECT.DirectRootOwnerError,
            "already consumed",
        ):
            capability.consume_once()

    def test_capability_clock_replacement_cannot_bypass_expiry(self) -> None:
        capability = self.fixture.capability()
        self.fixture.clock.advance(61)
        with self.assertRaisesRegex(
            DIRECT.DirectRootOwnerError,
            "fresh receipt is outside",
        ):
            capability.consume_once()
        with self.assertRaises(AttributeError):
            object.__setattr__(
                capability,
                "_clock",
                lambda: datetime(
                    2026,
                    7,
                    29,
                    0,
                    0,
                    1,
                    tzinfo=timezone.utc,
                ),
            )
        self.fixture.clock.value = datetime(
            2026,
            7,
            29,
            0,
            0,
            1,
            tzinfo=timezone.utc,
        )
        with self.assertRaisesRegex(
            DIRECT.DirectRootOwnerError,
            "trusted clock moved backward",
        ):
            capability.consume_once()

    def test_expiry_replay_and_owner_reuse_fail_before_consumption(self) -> None:
        owner = self.fixture.new_owner()
        observation = self.fixture.snapshot(owner)
        capability = owner.issue_fresh_capability_once(
            profile=self.fixture.profile,
            stable_evidence=self.fixture.evidence,
            authorization=self.fixture.authorization,
            observation=observation,
        )
        with self.assertRaisesRegex(
            DIRECT.DirectRootOwnerError,
            "fresh issuance is single-use",
        ):
            owner.issue_fresh_capability_once(
                profile=self.fixture.profile,
                stable_evidence=self.fixture.evidence,
                authorization=self.fixture.authorization,
                observation=observation,
            )
        self.fixture.clock.advance(61)
        with self.assertRaisesRegex(
            DIRECT.DirectRootOwnerError,
            "fresh receipt is outside",
        ):
            capability.consume_once()
        self.fixture.clock.value = datetime(
            2026, 7, 29, 0, 0, 1, tzinfo=timezone.utc
        )
        with self.assertRaisesRegex(
            DIRECT.DirectRootOwnerError,
            "trusted clock moved backward",
        ):
            capability.consume_once()

    def test_root_identity_workspace_and_safety_drift_fail_closed(self) -> None:
        cases = (
            {"seeds": ["srv-drift", "auto-g16-identity"]},
            {"project": "other_project"},
            {"fresh": False},
            {"contained": False},
            {"no_symlink": False},
        )
        for changes in cases:
            with self.subTest(changes=changes):
                owner = self.fixture.new_owner()
                observation = self.fixture.snapshot(owner, **changes)
                with self.assertRaises(DIRECT.DirectRootOwnerError):
                    owner.issue_fresh_capability_once(
                        profile=self.fixture.profile,
                        stable_evidence=self.fixture.evidence,
                        authorization=self.fixture.authorization,
                        observation=observation,
                    )

    def test_profile_root_input_resource_and_fresh_rule_tampering_fail(self) -> None:
        documents: list[tuple[dict[str, object], object]] = []
        profile = copy.deepcopy(self.fixture.profile)
        profile["declared_allowed_root"] = "/srv/other"
        documents.append((profile, DIRECT.validate_direct_execution_profile))
        authorization = copy.deepcopy(self.fixture.authorization)
        authorization["input"]["sha256"] = SHA_B
        documents.append((authorization, DIRECT.validate_direct_execution_authorization))
        authorization = copy.deepcopy(self.fixture.authorization)
        authorization["resources"]["cores"] = 9
        documents.append((authorization, DIRECT.validate_direct_execution_authorization))
        authorization = copy.deepcopy(self.fixture.authorization)
        authorization["fresh_observation_rules"]["path_reopen_allowed"] = True
        documents.append((authorization, DIRECT.validate_direct_execution_authorization))
        authorization = copy.deepcopy(self.fixture.authorization)
        authorization["fresh_observation_rules"]["future_receipt_hash_prebound"] = True
        documents.append((authorization, DIRECT.validate_direct_execution_authorization))
        for changed, validator in documents:
            with self.subTest(field=list(changed)):
                with self.assertRaises(DIRECT.DirectRootOwnerError):
                    validator(changed)

    def test_closed_shapes_bools_hashes_times_and_paths_fail(self) -> None:
        evidence = self.fixture.evidence.document()
        cases = []
        extra = copy.deepcopy(evidence)
        extra["unexpected"] = False
        cases.append(extra)
        missing = copy.deepcopy(evidence)
        del missing["derivation"]
        cases.append(missing)
        bool_as_int = copy.deepcopy(evidence)
        bool_as_int["safety"]["no_delete"] = 1
        cases.append(bool_as_int)
        zero_hash = copy.deepcopy(evidence)
        zero_hash["profile_policy"]["profile_payload_sha256"] = "0" * 64
        cases.append(zero_hash)
        unsafe_root = copy.deepcopy(evidence)
        unsafe_root["reviewed_root_policy"]["declared_allowed_root"] = "/srv/../etc"
        cases.append(unsafe_root)
        for changed in cases:
            with self.subTest(changed=changed):
                with self.assertRaises(DIRECT.DirectRootOwnerError):
                    DIRECT.validate_stable_root_identity_evidence(changed)

    def test_exact_module_source_and_class_identity_are_replayed(self) -> None:
        capability = self.fixture.capability()
        canonical = sys.modules[DIRECT.MODULE_NAME]
        sys.modules[DIRECT.MODULE_NAME] = mock.Mock()
        try:
            with self.assertRaisesRegex(
                DIRECT.DirectRootOwnerError,
                "module/source identity differs",
            ):
                capability.assert_current()
        finally:
            sys.modules[DIRECT.MODULE_NAME] = canonical
        original = DIRECT.FreshRootObservationReceipt
        DIRECT.FreshRootObservationReceipt = type(  # type: ignore[misc]
            "FreshRootObservationReceipt",
            (),
            {},
        )
        try:
            with self.assertRaisesRegex(
                DIRECT.DirectRootOwnerError,
                "class identity differs",
            ):
                capability.assert_current()
        finally:
            DIRECT.FreshRootObservationReceipt = original  # type: ignore[misc]
        drifted = replace(
            DIRECT._OWNER_MODULE_BINDING.source,
            sha256="0" * 64,
        )
        with mock.patch.object(
            DIRECT,
            "_stable_file",
            return_value=drifted,
        ):
            with self.assertRaisesRegex(
                DIRECT.DirectRootOwnerError,
                "module/source identity differs",
            ):
                capability.assert_current()

    def test_descriptor_replacement_and_cross_receipt_splice_fail(self) -> None:
        capability = self.fixture.capability()
        foreign = self.fixture.capability()
        object.__setattr__(
            capability,
            "_descriptor_set",
            foreign._descriptor_set,
        )
        with self.assertRaisesRegex(
            DIRECT.DirectRootOwnerError,
            "descriptor set differs",
        ):
            capability.consume_once()
        capability = self.fixture.capability()
        object.__setattr__(capability, "receipt", foreign.receipt)
        with self.assertRaises(DIRECT.DirectRootOwnerError):
            capability.consume_once()

    def test_strict_loader_rejects_symlink_duplicate_float_bom_and_noncanonical(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="auto-g16-direct-root-",
            dir=TEMP_PARENT,
        ) as temporary:
            root = Path(temporary).resolve()
            valid = root / "policy.json"
            valid.write_bytes(DIRECT.canonical_bytes(self.fixture.policy))
            self.assertEqual(
                DIRECT.load_exact_document(
                    valid,
                    DIRECT.validate_profile_policy,
                ),
                self.fixture.policy,
            )
            cases = {
                "duplicate.json": b'{"schema":"x","schema":"y"}\n',
                "float.json": b'{"value":1.0}\n',
                "bom.json": b"\xef\xbb\xbf{}\n",
                "noncanonical.json": json.dumps(
                    self.fixture.policy,
                    indent=2,
                ).encode("utf-8"),
            }
            for name, raw in cases.items():
                path = root / name
                path.write_bytes(raw)
                with self.subTest(name=name):
                    with self.assertRaises(DIRECT.DirectRootOwnerError):
                        DIRECT.load_exact_document(
                            path,
                            DIRECT.validate_profile_policy,
                        )
            linked = root / "linked.json"
            linked.symlink_to(valid)
            with self.assertRaises(DIRECT.DirectRootOwnerError):
                DIRECT.load_exact_document(
                    linked,
                    DIRECT.validate_profile_policy,
                )

    def test_no_transport_effect_api_or_implementation_is_present(self) -> None:
        source = (ROOT / "scripts/direct_root_owner_contract.py").read_text(
            encoding="utf-8"
        )
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
        public_methods = {
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
            "delete",
            "cleanup",
            "run",
        ):
            self.assertNotIn(forbidden, public_methods)
        called_attributes = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "os"
        }
        for forbidden in (
            "mkdir",
            "makedirs",
            "fork",
            "forkpty",
            "unlink",
            "remove",
            "rmdir",
            "rename",
            "replace",
            "symlink",
            "link",
        ):
            self.assertNotIn(forbidden, called_attributes)

    def test_named_skill_package_maps_single_owner_and_all_schemas(self) -> None:
        package = SKILL_PACKAGE.package_files_with_supplements(
            ROOT,
            "auto-g16-rtwin-pbs",
        )
        self.assertEqual(
            package[Path("scripts/direct_root_owner_contract.py")],
            ROOT / "scripts/direct_root_owner_contract.py",
        )
        self.assertEqual(
            package[Path("references/direct-root-owner-contract.md")],
            ROOT / "docs/v2.6-direct-root-owner-contract.md",
        )
        for name in (
            "direct-profile-policy.schema.json",
            "stable-root-identity-evidence.schema.json",
            "execution-profile-v3.schema.json",
            "execution-authorization-v3.schema.json",
            "fresh-root-observation-receipt.schema.json",
        ):
            with self.subTest(name=name):
                target = Path("contracts/direct-execution") / name
                self.assertEqual(
                    package[target],
                    ROOT / target,
                )
        self.assertFalse(
            (
                ROOT
                / "skills/auto-g16-rtwin-pbs/scripts/direct_root_owner_contract.py"
            ).exists()
        )


class DirectRootRealObserverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = MutableClock()

    def owner(self) -> DIRECT.DirectRootOwnerContractOwner:
        return DIRECT.DirectRootOwnerContractOwner._for_testing(
            clock=self.clock,
            nonce_source=lambda: NONCE,
            _test_token=DIRECT._TEST_FACTORY_TOKEN,
        )

    def chain(
        self,
        root: Path,
    ) -> tuple[
        DIRECT.DirectRootOwnerContractOwner,
        dict[str, object],
        DIRECT.StableRootIdentityEvidence,
        dict[str, object],
        dict[str, object],
    ]:
        owner = self.owner()
        policy = DIRECT.build_profile_policy(
            profile_id="direct-real-observer",
            declared_allowed_root=str(root),
            transport_identity_binding_sha256=SHA_A,
            gaussian_runtime_binding_sha256=SHA_B,
            resource_catalog_sha256=SHA_C,
        )
        evidence = owner.issue_stable_evidence_from_reviewed_profile(policy)
        profile = DIRECT.build_direct_execution_profile(policy, evidence)
        authorization = DIRECT.build_direct_execution_authorization(
            authorization_id="direct-real-observer-authorization",
            profile=profile,
            stable_evidence=evidence,
            project=PROJECT,
            input_basename="input.gjf",
            input_sha256=SHA_A,
            input_size_bytes=1024,
            tier="simple",
            cores=8,
            memory_gb=12,
            walltime_seconds=3600,
            scientific_task_id=TASK,
            attempt_id=ATTEMPT,
            idempotency_key="direct-real-observer-case",
            approved_at="2026-07-28T23:59:00.000000Z",
            not_before="2026-07-29T00:00:00.000000Z",
            expires_at="2026-07-29T01:00:00.000000Z",
            maximum_receipt_age_seconds=60,
        )
        return owner, policy, evidence, profile, authorization

    def test_real_observer_retains_same_no_follow_descriptors_once(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="auto-g16-real-root-",
            dir=TEMP_PARENT,
        ) as temporary:
            observed_root = Path(temporary).resolve() / "reviewed-root"
            observed_root.mkdir()
            owner, _policy, evidence, profile, authorization = self.chain(
                observed_root
            )
            owner._clock = lambda: datetime(  # type: ignore[attr-defined]
                2099, 1, 1, tzinfo=timezone.utc
            )
            owner._nonce_source = lambda: "0" * 32  # type: ignore[attr-defined]
            capability = owner.issue_fresh_capability_from_reviewed_profile_once(
                profile=profile,
                stable_evidence=evidence,
                authorization=authorization,
            )
            descriptor_set = capability._descriptor_set
            self.assertEqual(descriptor_set._mode, "posix_nofollow")
            self.assertTrue(
                all(type(handle) is int for handle in descriptor_set._opaque_handles)
            )
            self.assertEqual(
                capability.portable_receipt()["observed_root"][
                    "descriptor_set_sha256"
                ],
                descriptor_set.descriptor_set_sha256,
            )
            self.assertEqual(
                capability.portable_receipt()["window"]["observed_at"],
                "2026-07-29T00:00:00.000000Z",
            )
            self.assertEqual(
                capability.portable_receipt()["operation"]["nonce"],
                NONCE,
            )
            import direct_root_mutation_boundary as synthetic_boundary

            synthetic_owner = (
                synthetic_boundary.DirectRootMutationBoundaryOwner._for_testing(
                    _test_token=synthetic_boundary._TEST_TOKEN
                )
            )
            synthetic_helper = synthetic_owner._synthetic_helper_for_testing(
                _test_token=synthetic_boundary._TEST_TOKEN
            )
            with self.assertRaisesRegex(
                synthetic_boundary.DirectRootMutationBoundaryError,
                "rejects production descriptor capabilities",
            ):
                synthetic_owner.issue_synthetic_transaction_once(
                    root_capability=capability,
                    helper=synthetic_helper,
                )
            lease = capability.consume_once()
            self.assertIs(lease._descriptor_set, descriptor_set)
            self.assertIs(
                capability._descriptor_handles,
                descriptor_set._opaque_handles,
            )
            self.assertFalse(lease.remote_effect_authorized)
            self.assertFalse((observed_root / PROJECT).exists())
            with self.assertRaisesRegex(
                DIRECT.DirectRootOwnerError,
                "already consumed",
            ):
                capability.consume_once()
            stable_raw = DIRECT.canonical_bytes(evidence.document())
            for forbidden in (
                b'"observed_at"',
                b'"expires_at"',
                b'"nonce"',
                b'"receipt_id"',
                b'"operation"',
                b'"attempt_id"',
            ):
                self.assertNotIn(forbidden, stable_raw)
            DIRECT._close_descriptor_bundle_once(
                descriptor_set._descriptor_bundle,
                owner="capability",
            )

    def test_backend_factory_and_observer_have_no_root_override_surface(self) -> None:
        backend_owner = DIRECT.DirectRootOwnerContractOwner.for_posix_backend()
        self.assertIs(type(backend_owner), DIRECT.DirectRootOwnerContractOwner)
        self.assertEqual(
            tuple(inspect.signature(
                DIRECT.DirectRootOwnerContractOwner.for_posix_backend
            ).parameters),
            (),
        )
        stable_parameters = tuple(inspect.signature(
            backend_owner.issue_stable_evidence_from_reviewed_profile
        ).parameters)
        fresh_parameters = tuple(inspect.signature(
            backend_owner.issue_fresh_capability_from_reviewed_profile_once
        ).parameters)
        self.assertEqual(stable_parameters, ("profile_policy",))
        self.assertEqual(
            fresh_parameters,
            ("profile", "stable_evidence", "authorization"),
        )
        for forbidden in ("root", "path", "config", "env", "runtime"):
            self.assertNotIn(forbidden, stable_parameters)
            self.assertNotIn(forbidden, fresh_parameters)
        forged = object.__new__(DIRECT.DirectRootOwnerContractOwner)
        with self.assertRaisesRegex(
            DIRECT.DirectRootOwnerError,
            "owner state is unavailable",
        ):
            forged.issue_stable_evidence_from_reviewed_profile(
                DirectRootFixture().policy
            )
        oversized_root = "/" + "/".join(
            "x" for _ in range(DIRECT.MAX_OBSERVED_ROOT_COMPONENTS + 1)
        )
        with (
            mock.patch.object(os, "open") as open_call,
            self.assertRaisesRegex(
                DIRECT.DirectRootOwnerError,
                "exceeds its component bound",
            ),
        ):
            DIRECT._open_root_components_no_follow(oversized_root)
        open_call.assert_not_called()

    def test_symlink_component_and_existing_project_fail_with_zero_effect(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="auto-g16-real-root-",
            dir=TEMP_PARENT,
        ) as temporary:
            parent = Path(temporary).resolve()
            target = parent / "target"
            target.mkdir()
            linked = parent / "linked"
            linked.symlink_to(target, target_is_directory=True)
            owner = self.owner()
            policy = DIRECT.build_profile_policy(
                profile_id="direct-symlink-observer",
                declared_allowed_root=str(linked),
                transport_identity_binding_sha256=SHA_A,
                gaussian_runtime_binding_sha256=SHA_B,
                resource_catalog_sha256=SHA_C,
            )
            with self.assertRaises(DIRECT.DirectRootOwnerError):
                owner.issue_stable_evidence_from_reviewed_profile(policy)
            self.assertEqual(list(target.iterdir()), [])

            reviewed_root = parent / "reviewed-root"
            reviewed_root.mkdir()
            owner, _policy, evidence, profile, authorization = self.chain(
                reviewed_root
            )
            (reviewed_root / PROJECT).mkdir()
            with self.assertRaisesRegex(
                DIRECT.DirectRootOwnerError,
                "already exists or is not fresh",
            ):
                owner.issue_fresh_capability_from_reviewed_profile_once(
                    profile=profile,
                    stable_evidence=evidence,
                    authorization=authorization,
                )
            self.assertEqual(list((reviewed_root / PROJECT).iterdir()), [])

    def test_identity_drift_before_fresh_observation_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="auto-g16-real-root-",
            dir=TEMP_PARENT,
        ) as temporary:
            observed_root = Path(temporary).resolve() / "reviewed-root"
            observed_root.mkdir()
            owner, _policy, evidence, profile, authorization = self.chain(
                observed_root
            )
            original_mode = stat.S_IMODE(observed_root.stat().st_mode)
            changed_mode = original_mode ^ stat.S_IWGRP
            os.chmod(observed_root, changed_mode)
            try:
                with self.assertRaisesRegex(
                    DIRECT.DirectRootOwnerError,
                    "root identity drifted",
                ):
                    owner.issue_fresh_capability_from_reviewed_profile_once(
                        profile=profile,
                        stable_evidence=evidence,
                        authorization=authorization,
                    )
                self.assertFalse((observed_root / PROJECT).exists())
            finally:
                os.chmod(observed_root, original_mode)

    def test_descriptor_replacement_and_expiry_fail_before_any_effect(self) -> None:
        for case in (
            "identity_drift",
            "replacement",
            "descriptor_field_forgery",
            "expiry",
        ):
            with self.subTest(case=case), tempfile.TemporaryDirectory(
                prefix="auto-g16-real-root-",
                dir=TEMP_PARENT,
            ) as temporary:
                observed_root = Path(temporary).resolve() / "reviewed-root"
                observed_root.mkdir()
                owner, _policy, evidence, profile, authorization = self.chain(
                    observed_root
                )
                capability = (
                    owner.issue_fresh_capability_from_reviewed_profile_once(
                        profile=profile,
                        stable_evidence=evidence,
                        authorization=authorization,
                    )
                )
                descriptor_set = capability._descriptor_set
                original_mode = stat.S_IMODE(observed_root.stat().st_mode)
                if case == "identity_drift":
                    os.chmod(observed_root, original_mode ^ stat.S_IWGRP)
                    pattern = "component identity drifted"
                elif case == "replacement":
                    retained_root = observed_root.with_name("retained-root")
                    observed_root.rename(retained_root)
                    observed_root.mkdir()
                    pattern = "component identity drifted"
                elif case == "descriptor_field_forgery":
                    object.__setattr__(
                        descriptor_set,
                        "_component_names",
                        tuple(reversed(descriptor_set._component_names)),
                    )
                    pattern = "capability descriptor set differs"
                else:
                    self.clock.advance(61)
                    pattern = "fresh receipt is outside"
                try:
                    with self.assertRaisesRegex(
                        DIRECT.DirectRootOwnerError,
                        pattern,
                    ):
                        capability.consume_once()
                    self.assertFalse((observed_root / PROJECT).exists())
                    if case == "replacement":
                        self.assertFalse((retained_root / PROJECT).exists())
                finally:
                    if case == "identity_drift":
                        os.chmod(observed_root, original_mode)
                    with self.assertRaisesRegex(
                        DIRECT.DirectRootOwnerError,
                        "terminally invalidated",
                    ):
                        capability.consume_once()
                    DIRECT._close_descriptor_bundle_once(
                        descriptor_set._descriptor_bundle,
                        owner="capability",
                    )

    def test_step_clock_issuance_failure_closes_descriptor_tuple_once(self) -> None:
        start = datetime(2026, 7, 29, 0, 0, 0, tzinfo=timezone.utc)
        self.clock = StepClock([start, start, start + timedelta(seconds=61)])
        with tempfile.TemporaryDirectory(
            prefix="auto-g16-real-root-",
            dir=TEMP_PARENT,
        ) as temporary:
            observed_root = Path(temporary).resolve() / "reviewed-root"
            observed_root.mkdir()
            owner, _policy, evidence, profile, authorization = self.chain(
                observed_root
            )
            with (
                mock.patch.object(
                    DIRECT,
                    "_close_directory_descriptors",
                    wraps=DIRECT._close_directory_descriptors,
                ) as close_descriptors,
                self.assertRaisesRegex(
                    DIRECT.DirectRootOwnerError,
                    "fresh receipt is outside",
                ),
            ):
                owner.issue_fresh_capability_from_reviewed_profile_once(
                    profile=profile,
                    stable_evidence=evidence,
                    authorization=authorization,
                )
            self.assertEqual(self.clock.calls, 3)
            self.assertEqual(close_descriptors.call_count, 1)
            closed_handles = close_descriptors.call_args.args[0]
            self.assertIs(type(closed_handles), tuple)
            self.assertTrue(all(type(handle) is int for handle in closed_handles))

    def test_pretransfer_step_clock_failure_closes_observer_bundle_once(self) -> None:
        start = datetime(2026, 7, 29, 0, 0, 0, tzinfo=timezone.utc)
        self.clock = StepClock([start, start + timedelta(seconds=3601)])
        with tempfile.TemporaryDirectory(
            prefix="auto-g16-real-root-",
            dir=TEMP_PARENT,
        ) as temporary:
            observed_root = Path(temporary).resolve() / "reviewed-root"
            observed_root.mkdir()
            owner, _policy, evidence, profile, authorization = self.chain(
                observed_root
            )
            with (
                mock.patch.object(
                    DIRECT,
                    "_close_directory_descriptors",
                    wraps=DIRECT._close_directory_descriptors,
                ) as close_descriptors,
                self.assertRaisesRegex(
                    DIRECT.DirectRootOwnerError,
                    "trusted window",
                ),
            ):
                owner.issue_fresh_capability_from_reviewed_profile_once(
                    profile=profile,
                    stable_evidence=evidence,
                    authorization=authorization,
                )
            self.assertEqual(self.clock.calls, 2)
            self.assertEqual(close_descriptors.call_count, 1)

    def test_step_clock_close_reuse_never_closes_unrelated_fd(self) -> None:
        start = datetime(2026, 7, 29, 0, 0, 0, tzinfo=timezone.utc)
        self.clock = StepClock([start, start, start + timedelta(seconds=61)])
        with tempfile.TemporaryDirectory(
            prefix="auto-g16-real-root-",
            dir=TEMP_PARENT,
        ) as temporary:
            observed_root = Path(temporary).resolve() / "reviewed-root"
            observed_root.mkdir()
            owner, _policy, evidence, profile, authorization = self.chain(
                observed_root
            )
            real_close = os.close
            close_counts: dict[int, int] = {}
            unrelated_fds: list[int] = []

            def close_and_reuse_once(descriptor: int) -> None:
                count = close_counts.get(descriptor, 0) + 1
                close_counts[descriptor] = count
                real_close(descriptor)
                if count == 1:
                    unrelated = os.open("/dev/null", os.O_RDONLY)
                    if unrelated != descriptor:
                        real_close(unrelated)
                        raise AssertionError("hostile FD reuse was not exact")
                    unrelated_fds.append(unrelated)

            try:
                with (
                    mock.patch.object(os, "close", side_effect=close_and_reuse_once),
                    self.assertRaisesRegex(
                        DIRECT.DirectRootOwnerError,
                        "fresh receipt is outside",
                    ),
                ):
                    owner.issue_fresh_capability_from_reviewed_profile_once(
                        profile=profile,
                        stable_evidence=evidence,
                        authorization=authorization,
                    )
                self.assertTrue(unrelated_fds)
                self.assertTrue(all(count == 1 for count in close_counts.values()))
                for descriptor in unrelated_fds:
                    self.assertTrue(stat.S_ISCHR(os.fstat(descriptor).st_mode))
            finally:
                for descriptor in unrelated_fds:
                    try:
                        real_close(descriptor)
                    except OSError:
                        pass

    def test_concurrent_expired_consumers_share_one_descriptor_close(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="auto-g16-real-root-",
            dir=TEMP_PARENT,
        ) as temporary:
            observed_root = Path(temporary).resolve() / "reviewed-root"
            observed_root.mkdir()
            owner, _policy, evidence, profile, authorization = self.chain(
                observed_root
            )
            capability = owner.issue_fresh_capability_from_reviewed_profile_once(
                profile=profile,
                stable_evidence=evidence,
                authorization=authorization,
            )
            handle_count = len(capability._descriptor_handles)
            self.clock.advance(61)

            def consume() -> str:
                try:
                    capability.consume_once()
                except DIRECT.DirectRootOwnerError as exc:
                    return str(exc)
                raise AssertionError("expired capability unexpectedly consumed")

            with (
                mock.patch.object(
                    DIRECT,
                    "_close_directory_descriptors",
                    wraps=DIRECT._close_directory_descriptors,
                ) as close_descriptors,
                ThreadPoolExecutor(max_workers=2) as pool,
            ):
                messages = list(pool.map(lambda _index: consume(), range(2)))
            self.assertEqual(close_descriptors.call_count, 1)
            self.assertEqual(
                len(close_descriptors.call_args.args[0]),
                handle_count,
            )
            self.assertTrue(
                any("fresh receipt is outside" in message for message in messages)
            )
            self.assertTrue(
                any("terminally invalidated" in message for message in messages)
            )

    @unittest.skipUnless(
        hasattr(os, "fork") and hasattr(os, "register_at_fork"),
        "requires reviewed POSIX fork semantics",
    )
    def test_forked_capability_fails_closed_without_closing_parent_fds(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="auto-g16-real-root-",
            dir=TEMP_PARENT,
        ) as temporary:
            observed_root = Path(temporary).resolve() / "reviewed-root"
            observed_root.mkdir()
            owner, _policy, evidence, profile, authorization = self.chain(
                observed_root
            )
            capability = owner.issue_fresh_capability_from_reviewed_profile_once(
                profile=profile,
                stable_evidence=evidence,
                authorization=authorization,
            )
            parent_handles = capability._descriptor_handles
            read_fd, write_fd = os.pipe()
            capability_state = DIRECT._capability_state(capability)
            descriptor_bundle = capability._descriptor_set._descriptor_bundle
            bundle_state = DIRECT._descriptor_bundle_state(descriptor_bundle)
            capability_state.lock.acquire()
            bundle_state.lock.acquire()
            try:
                child_pid = os.fork()
            except BaseException:
                bundle_state.lock.release()
                capability_state.lock.release()
                raise
            if child_pid == 0:
                os.close(read_fd)
                try:
                    capability.consume_once()
                except DIRECT.DirectRootOwnerError as exc:
                    message = str(exc).encode("utf-8")
                else:
                    message = b"unexpected child consumption"
                os.write(write_fd, message)
                os.close(write_fd)
                os._exit(0)
            bundle_state.lock.release()
            capability_state.lock.release()
            os.close(write_fd)
            child_message = os.read(read_fd, 4096).decode("utf-8")
            os.close(read_fd)
            waited_pid, status = os.waitpid(child_pid, 0)
            self.assertEqual(waited_pid, child_pid)
            self.assertTrue(os.WIFEXITED(status))
            self.assertEqual(os.WEXITSTATUS(status), 0)
            self.assertIn("process or fork boundary", child_message)
            for descriptor in parent_handles:
                self.assertTrue(stat.S_ISDIR(os.fstat(descriptor).st_mode))
            lease = capability.consume_once()
            self.assertIs(lease._descriptor_set, capability._descriptor_set)
            DIRECT._close_descriptor_bundle_once(
                capability._descriptor_set._descriptor_bundle,
                owner="capability",
            )


if __name__ == "__main__":
    unittest.main()
