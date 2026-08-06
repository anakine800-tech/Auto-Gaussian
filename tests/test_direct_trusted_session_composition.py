#!/usr/bin/env python3
"""Offline hostile tests for the fixed trusted server-local session seam."""

from __future__ import annotations

import array
import ast
import copy
import fcntl
import hashlib
import json
import multiprocessing
import os
import pickle
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import types
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from tests import test_live_approval_effect_time_replay as LIVE_SUPPORT


ROOT = Path(__file__).parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(ROOT / "skills" / "auto-g16-rtwin-pbs" / "scripts"))

import direct_durable_submission_journal as W2  # noqa: E402
import direct_effect_time_replay_ingress as W3  # noqa: E402
import direct_root_fixed_mutation_consumer as W4  # noqa: E402
import direct_root_fixed_mutation_helper as HELPER  # noqa: E402
import direct_root_mutation_boundary as SYNTHETIC_ROOT  # noqa: E402
import direct_root_owner_contract as W1  # noqa: E402
import direct_ssh_pbs_offline as DIRECT  # noqa: E402
import direct_trusted_session_composition as SESSION  # noqa: E402
import direct_one_hop_transport as W5  # noqa: E402
import live_approval_effect_time_replay as LIVE  # noqa: E402
import resource_effect_time_replay_owner as RESOURCE_REPLAY  # noqa: E402
import resource_efficiency as RESOURCE  # noqa: E402
import skill_package as SKILL_PACKAGE  # noqa: E402


ISSUED = LIVE_SUPPORT.ISSUED
RESERVED = ISSUED - timedelta(seconds=30)


def _fork_assert(capability: object, queue: object) -> None:
    try:
        capability.assert_current()  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001 - exact child failure is reported
        queue.put(("rejected", type(exc).__name__, str(exc)))
    else:
        queue.put(("accepted", "", ""))


class PortableSessionFixture:
    def __init__(self, temporary: Path) -> None:
        self.live = LIVE_SUPPORT.LiveApprovalEffectTimeReplayTests("runTest")
        self.live.setUp()
        self.root = temporary / "reviewed-root"
        self.state = temporary / "durable-state"
        self.root.mkdir()
        self.state.mkdir(mode=0o700)
        protected = self.live.fixture.local.lifecycle.invocation.local.protected
        self.protected = protected
        approval = json.loads(self.live.approval_path.read_text(encoding="utf-8"))
        execution = approval["scope"]["execution"]
        resource = execution["resource_binding"]
        payload = protected.input_path.read_bytes()
        pbs_script = (
            "#!/bin/sh\nset -eu\n"
            f"test \"${{AUTO_G16_ALLOWED_ROOT:-}}\" = \"{self.root}\"\n"
            "test \"$PBS_O_WORKDIR\" = \"$(pwd -P)\"\n"
            "test -d scratch && test ! -L scratch\n"
            f"exec g16 {W5.INPUT_BASENAME}\n"
        ).encode("utf-8")
        pbs_review = {
            "schema": W5.PBS_REVIEW_SCHEMA,
            "review_id": "synthetic-reviewed-direct-pbs",
            "script": {
                "basename": W5.PBS_BASENAME,
                "sha256": hashlib.sha256(pbs_script).hexdigest(),
                "size_bytes": str(len(pbs_script)),
            },
            "workspace": {
                "allowed_root": str(self.root),
                "project": approval["scope"]["project"],
                "working_directory_check": "pbs_o_workdir_equals_submission_directory",
                "scratch_policy": "project_relative_scratch",
                "scratch_basename": "scratch",
            },
            "input": {
                "source_sha256": hashlib.sha256(payload).hexdigest(),
                "uploaded_basename": W5.INPUT_BASENAME,
                "route_bytes_unchanged": True,
            },
            "resources": {
                "tier": resource["resource_tier"],
                "cores": str(resource["cores"]),
                "memory_gb": str(resource["memory_gb"]),
                "walltime_seconds": str(resource["walltime_seconds"]),
            },
            "gaussian": {
                "executable": "g16",
                "invocation": "filename_argument",
                "input_basename": W5.INPUT_BASENAME,
                "scientific_route_owned_by_input": True,
            },
            "safety": {
                "set_eu": True,
                "allowed_root_checked": True,
                "project_workdir_checked": True,
                "scratch_identity_checked": True,
                "nested_ssh": False,
                "legacy_transport_called": False,
            },
            "review_payload_sha256": "",
        }
        pbs_review["review_payload_sha256"] = W5.digest(pbs_review)
        pbs_review_raw = W5.canonical_bytes(pbs_review)
        ssh_system_policy_evidence = W5.canonical_bytes(
            {
                "schema": "auto-g16-ssh-configuration-files-disabled-evidence/1",
                "ssh_executable_sha256": "d" * 64,
                "fixed_option": ["-F", "none"],
                "configuration_files_read": False,
                "global_known_hosts_file": "none",
                "user_known_hosts_file": "/etc/auto-g16/direct_known_hosts",
                "strict_host_key_checking": True,
                "known_hosts_command": "none",
                "verify_host_key_dns": False,
                "update_host_keys": False,
                "default_identity_files": "disabled_by_IdentityFile_none",
                "identity_agent": "none",
                "certificate_file": "none",
                "pkcs11_provider": "none",
                "security_key_provider": "none",
                "portable_evidence_authorizes_effect": False,
            }
        )

        transport_profile = {
            "schema": W5.TRANSPORT_PROFILE_SCHEMA,
            "profile_id": "direct-trusted-session-transport",
            "backend_kind": W5.BACKEND_KIND,
            "topology": W5.TOPOLOGY,
            "scheduler_dialect": W5.SCHEDULER_DIALECT,
            "ssh": {
                "executable": W5.SSH_EXECUTABLE,
                "executable_sha256": "d" * 64,
                "configuration_files": "disabled_by_F_none",
                "system_policy_evidence_sha256": hashlib.sha256(ssh_system_policy_evidence).hexdigest(),
                "host": "pbs.example.invalid",
                "user": "auto_g16",
                "port": "22",
                "identity_file": "/etc/auto-g16/direct_identity",
                "known_hosts_file": "/etc/auto-g16/direct_known_hosts",
                "batch_mode": True,
                "identities_only": True,
                "strict_host_key_checking": True,
                "subsystem": W5.SSH_SUBSYSTEM,
            },
            "server": {
                "python_executable": str(SESSION._FIXED_EXECUTABLE.path),
                "python_executable_sha256": SESSION._FIXED_EXECUTABLE.sha256,
                "isolated_flags": ["-I", "-S"],
                "working_directory": "/",
                "environment": copy.deepcopy(W5.FIXED_ENVIRONMENT),
                "allowed_root": str(self.root),
                "entrypoint_source_sha256": W5._EXECUTED_SOURCE_SHA256,
            },
            "qsub": {
                "executable": W5.QSUB_EXECUTABLE,
                "executable_sha256": "f" * 64,
                "argv": list(W5.QSUB_ARGV),
                "working_directory": "already_open_project_fd",
                "stdout_grammar": "independent_pbs_job_id_v1",
            },
            "pbs_artifact": {
                "basename": W5.PBS_BASENAME,
                "sha256": hashlib.sha256(pbs_script).hexdigest(),
                "size_bytes": str(len(pbs_script)),
                "review_payload_sha256": pbs_review["review_payload_sha256"],
                "owner": "reviewed_direct_pbs_artifact_owner",
            },
            "safety": copy.deepcopy(W5.POLICY),
            "profile_payload_sha256": "",
        }
        transport_profile["profile_payload_sha256"] = W5.digest(transport_profile)
        transport_profile = W5.validate_transport_profile(transport_profile)
        transport_profile_raw = W5.canonical_bytes(transport_profile)

        review_owner = W1.DirectRootOwnerContractOwner.for_posix_backend()
        policy = W1.build_profile_policy(
            profile_id="direct-trusted-session-reviewed",
            declared_allowed_root=str(self.root),
            transport_identity_binding_sha256=transport_profile["profile_payload_sha256"],
            gaussian_runtime_binding_sha256="b" * 64,
            resource_catalog_sha256="c" * 64,
        )
        evidence = review_owner.issue_stable_evidence_from_reviewed_profile(policy)
        profile = W1.build_direct_execution_profile(policy, evidence)
        authorization = W1.build_direct_execution_authorization(
            authorization_id="direct-trusted-session-authorization",
            profile=profile,
            stable_evidence=evidence,
            project=approval["scope"]["project"],
            input_basename=protected.input_path.name,
            input_sha256=approval["scope"]["input_sha256"],
            input_size_bytes=len(payload),
            tier=resource["resource_tier"],
            cores=resource["cores"],
            memory_gb=resource["memory_gb"],
            walltime_seconds=resource["walltime_seconds"],
            scientific_task_id=execution["scientific_task_id"],
            attempt_id=execution["attempt_id"],
            idempotency_key=execution["idempotency_key"],
            approved_at="2030-01-01T12:01:00.000000Z",
            not_before="2030-01-01T12:02:00.000000Z",
            expires_at="2030-01-01T12:10:00.000000Z",
            maximum_receipt_age_seconds=60,
        )

        def artifact(document: dict[str, object]) -> bytes:
            return (json.dumps(document, sort_keys=True) + "\n").encode("utf-8")

        self.artifacts = SESSION.DirectServerSessionArtifacts(
            profile_policy=W1.canonical_bytes(policy),
            stable_evidence=W1.canonical_bytes(evidence.document()),
            profile=W1.canonical_bytes(profile),
            authorization=W1.canonical_bytes(authorization),
            transport_profile=transport_profile_raw,
            ssh_system_policy_evidence=ssh_system_policy_evidence,
            pbs_script=pbs_script,
            pbs_review=pbs_review_raw,
            input_bytes=payload,
            resource_ledger=protected.ledger_path.read_bytes(),
            resource_policy=artifact(protected.policy),
            resource_gate=artifact(protected.gate),
            scheduler_snapshot=artifact(protected.scheduler),
            live_approval=self.live.approval_path.read_bytes(),
        )

    def owner(self) -> SESSION.FixedTrustedServerLocalSessionOwner:
        return SESSION.FixedTrustedServerLocalSessionOwner._for_fake_local_testing(
            durable_state_root=self.state,
            _test_token=SESSION._TEST_TOKEN,
        )

    def clocks(self) -> object:
        return mock.patch.multiple(
            "direct_trusted_session_composition",
            _utc_now=mock.Mock(return_value=RESERVED),
        )

    def compose(self) -> SESSION.TrustedServerLocalSessionCapability:
        with mock.patch.object(W1, "_system_utc_now", return_value=ISSUED), \
                mock.patch.object(LIVE, "_system_wall_clock", return_value=ISSUED), \
                mock.patch.object(LIVE, "_system_monotonic_ns", return_value=1_000_000_000), \
                mock.patch.object(RESOURCE_REPLAY, "_effect_wall_now", return_value=ISSUED), \
                mock.patch.object(RESOURCE_REPLAY, "_effect_monotonic_ns", return_value=1_000_000_000), \
                mock.patch.object(SESSION, "_utc_now", return_value=RESERVED):
            return self.owner().compose_once(self.artifacts)

    def close(self) -> None:
        self.live.tearDown()


class DirectTrustedSessionCompositionTests(unittest.TestCase):
    maxDiff = None

    def test_reviewed_legacy_dependency_hash_replacement_and_rebind_fail_closed(self) -> None:
        legacy_index = next(
            index
            for index, (name, _layout, _sha256) in enumerate(SESSION._FIXED_DEPENDENCY_ORDER)
            if name == "legacy_rtwin_pbs"
        )
        current_sha256 = "fb72f8aa5ba8063f14d7ef41eddf0b96a783cc69a6294ab04854457c47c158b1"
        old_sha256 = "3471014b9358380938e98839aaacb9cd3f9f20146fc79c1a9738483021c2cb8e"
        self.assertEqual(
            SESSION._FIXED_DEPENDENCY_ORDER[legacy_index],
            ("legacy_rtwin_pbs", "skill", current_sha256),
        )
        binding = SESSION._FIXED_DEPENDENCY_BINDINGS[legacy_index]
        self.assertEqual(binding[4], current_sha256)

        old_hash_bindings = list(SESSION._FIXED_DEPENDENCY_BINDINGS)
        old_hash_bindings[legacy_index] = (*binding[:4], old_sha256)
        with self.assertRaisesRegex(ImportError, "legacy_rtwin_pbs"):
            SESSION._assert_fixed_dependency_chain(tuple(old_hash_bindings))

        canonical_reader = SESSION._read_fixed_dependency_source

        def replaced_legacy_reader(path: Path) -> tuple[tuple[int, ...], str]:
            identity, source_sha256 = canonical_reader(path)
            if path.name == "legacy_rtwin_pbs.py":
                return identity, old_sha256
            return identity, source_sha256

        with mock.patch.object(
            SESSION,
            "_read_fixed_dependency_source",
            side_effect=replaced_legacy_reader,
        ):
            with self.assertRaisesRegex(ImportError, "legacy_rtwin_pbs"):
                SESSION._assert_fixed_dependency_chain(SESSION._FIXED_DEPENDENCY_BINDINGS)

        replacement = types.ModuleType("legacy_rtwin_pbs")
        with mock.patch.dict(sys.modules, {"legacy_rtwin_pbs": replacement}):
            with self.assertRaisesRegex(ImportError, "legacy_rtwin_pbs"):
                SESSION._assert_fixed_dependency_chain(SESSION._FIXED_DEPENDENCY_BINDINGS)

    def test_clean_caller_direct_imports_in_supported_and_isolated_interpreters(self) -> None:
        probe = r'''
import pathlib, sys
scripts = pathlib.Path(sys.argv[1]).resolve()
sys.path.insert(0, str(scripts))
import direct_trusted_session_composition as session
session._assert_module_binding()
if len(session._FIXED_DEPENDENCY_BINDINGS) != 8:
    raise AssertionError("FIXED_DEPENDENCY_BINDING_COUNT_DIFFERS")
if session.AUTHORITY["external_effects"] != 0 or session.AUTHORITY["qsub_calls"] != 0:
    raise AssertionError("DIRECT_IMPORT_EFFECT_REPORTED")
print("DIRECT_IMPORT_READY_NO_EFFECT")
'''
        for flags in ((), ("-I", "-S")):
            with self.subTest(flags=flags):
                result = subprocess.run(
                    [sys.executable, *flags, "-c", probe, str(SCRIPTS)],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, "DIRECT_IMPORT_READY_NO_EFFECT\n")

    def test_exact_legacy_dependency_reload_invalidates_existing_binding_before_effect(self) -> None:
        probe = r'''
import importlib, pathlib, sys
scripts = pathlib.Path(sys.argv[1]).resolve()
state = pathlib.Path(sys.argv[2]).resolve()
skill_scripts = scripts.parent / "skills" / "auto-g16-rtwin-pbs" / "scripts"
sys.path.insert(0, str(scripts))
import direct_trusted_session_composition as session
legacy = sys.modules["legacy_rtwin_pbs"]
session._assert_module_binding()
legacy_path = (skill_scripts / "legacy_rtwin_pbs.py").resolve()
if session._fixed_dependency_origin(legacy) != (legacy_path, legacy_path):
    raise AssertionError("LEGACY_DEPENDENCY_ORIGIN_DIFFERS")
legacy_sha256 = session._read_fixed_dependency_source(legacy_path)[1]
if legacy_sha256 != (
    "fb72f8aa5ba8063f14d7ef41eddf0b96a783cc69a6294ab04854457c47c158b1"
):
    raise AssertionError("LEGACY_DEPENDENCY_BYTES_DIFFER")
old_plan_type = legacy._LegacyEffectPlan
forbidden_codes = {
    session.FixedTrustedServerLocalSessionOwner.compose_once.__code__,
    session.W2.consume_for_server_session_replay_once.__code__,
    session.W4.DirectRootFixedMutationOwner.issue_session_once.__code__,
}
observed = []
def profile(frame, event, _arg):
    if event == "call" and frame.f_code in forbidden_codes:
        observed.append(frame.f_code)
sys.path.insert(0, str(skill_scripts))
try:
    reloaded = importlib.reload(legacy)
finally:
    sys.path.remove(str(skill_scripts))
if (
    reloaded is not legacy
    or session._fixed_dependency_origin(reloaded) != (legacy_path, legacy_path)
    or legacy._LegacyEffectPlan is old_plan_type
):
    raise AssertionError("EXACT_LEGACY_RELOAD_DID_NOT_REPLACE_OWNER_TYPE")
sys.setprofile(profile)
try:
    for operation in (
        lambda: session._assert_fixed_dependency_chain(session._FIXED_DEPENDENCY_BINDINGS),
        session._assert_module_binding,
    ):
        try:
            operation()
        except Exception as exc:
            if "identity changed" not in str(exc):
                raise
        else:
            raise AssertionError("RELOADED_LEGACY_DEPENDENCY_ACCEPTED")
finally:
    sys.setprofile(None)
if observed:
    raise AssertionError("EFFECT_OWNER_ENTERED_AFTER_LEGACY_RELOAD")
if tuple(state.iterdir()):
    raise AssertionError("STATE_EFFECT_AFTER_LEGACY_RELOAD")
if session.AUTHORITY["external_effects"] != 0 or session.AUTHORITY["qsub_calls"] != 0:
    raise AssertionError("EXTERNAL_EFFECT_REPORTED_AFTER_LEGACY_RELOAD")
print("EXACT_LEGACY_RELOAD_REJECTED_BEFORE_EFFECT")
'''
        with tempfile.TemporaryDirectory(prefix="auto-g16-session-legacy-reload-") as raw:
            result = subprocess.run(
                [sys.executable, "-I", "-S", "-c", probe, str(SCRIPTS), raw],
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                result.stdout,
                "EXACT_LEGACY_RELOAD_REJECTED_BEFORE_EFFECT\n",
            )
            self.assertEqual(tuple(Path(raw).iterdir()), ())

    def test_preloaded_wrong_order_and_fake_dependencies_fail_before_w2_or_effect(self) -> None:
        probe = r'''
import importlib.util, pathlib, sys
scripts = pathlib.Path(sys.argv[1]).resolve()
state = pathlib.Path(sys.argv[2]).resolve()
target = sys.argv[3]
sys.path.insert(0, str(scripts))
if target in {"execution_facade", "legacy_rtwin_pbs"}:
    source = scripts.parent / "skills" / "auto-g16-rtwin-pbs" / "scripts" / (target + ".py")
else:
    source = scripts / (target + ".py")
spec = importlib.util.spec_from_file_location(target, source)
if spec is None:
    raise AssertionError("FAKE_SPEC_UNAVAILABLE")
fake = importlib.util.module_from_spec(spec)
sys.modules[target] = fake
try:
    import direct_trusted_session_composition
except (ImportError, AttributeError, TypeError):
    pass
else:
    raise AssertionError("PRELOADED_FAKE_DEPENDENCY_ACCEPTED")
if "direct_durable_submission_journal" in sys.modules:
    raise AssertionError("W2_LOADED_BEFORE_DEPENDENCY_REJECTION")
if "direct_trusted_session_composition" in sys.modules:
    raise AssertionError("PARTIAL_SESSION_MODULE_RETAINED")
if tuple(state.iterdir()):
    raise AssertionError("SESSION_EFFECT_BEFORE_DEPENDENCY_REJECTION")
print(target + "_REJECTED_BEFORE_W2")
'''
        for target in (
            "execution_facade",
            "legacy_rtwin_pbs",
            "protected_runtime_state_contract",
            "protected_owner_consumer_contract",
        ):
            with self.subTest(target=target), tempfile.TemporaryDirectory(
                prefix="auto-g16-session-bootstrap-hostile-"
            ) as raw:
                result = subprocess.run(
                    [sys.executable, "-I", "-S", "-c", probe, str(SCRIPTS), raw, target],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, target + "_REJECTED_BEFORE_W2\n")
                self.assertEqual(tuple(Path(raw).iterdir()), ())

    def test_named_skill_supplement_maps_only_session_source_schema_and_reference(self) -> None:
        supplement_root = ROOT / "config/deployment-package-supplements/auto-g16-rtwin-pbs"
        w4b = json.loads((supplement_root / "direct-trusted-session-composition.json").read_text(encoding="utf-8"))
        w5 = json.loads((supplement_root / "direct-one-hop-transport.json").read_text(encoding="utf-8"))
        self.assertEqual(
            [item["source"] for item in w4b["include"]],
            [
                "scripts/direct_trusted_session_composition.py",
                "scripts/direct_trusted_session_clean_exec.py",
                "contracts/direct-execution/direct-trusted-session-result.schema.json",
                "docs/v2.7-direct-trusted-session-composition.md",
            ],
        )
        self.assertEqual(
            [item["source"] for item in w5["include"]],
            [
                "scripts/direct_one_hop_transport.py",
                "contracts/direct-execution/direct-one-hop-submission-result.schema.json",
                "contracts/direct-execution/direct-one-hop-transport-profile.schema.json",
                "contracts/direct-execution/reviewed-direct-pbs-script.schema.json",
                "docs/v2.7-direct-one-hop-transport.md",
            ],
        )
        package = SKILL_PACKAGE.package_files_with_supplements(ROOT, "auto-g16-rtwin-pbs")
        expected = {
            Path("scripts/direct_trusted_session_composition.py"): (
                ROOT / "scripts/direct_trusted_session_composition.py"
            ),
            Path("scripts/direct_trusted_session_clean_exec.py"): (
                ROOT / "scripts/direct_trusted_session_clean_exec.py"
            ),
            Path("scripts/direct_one_hop_transport.py"): (
                ROOT / "scripts/direct_one_hop_transport.py"
            ),
            Path("contracts/rtwin-pbs/direct-trusted-session-result.schema.json"): (
                ROOT / "contracts/direct-execution/direct-trusted-session-result.schema.json"
            ),
            Path("contracts/rtwin-pbs/direct-one-hop-submission-result.schema.json"): (
                ROOT / "contracts/direct-execution/direct-one-hop-submission-result.schema.json"
            ),
            Path("contracts/rtwin-pbs/direct-one-hop-transport-profile.schema.json"): (
                ROOT / "contracts/direct-execution/direct-one-hop-transport-profile.schema.json"
            ),
            Path("contracts/rtwin-pbs/reviewed-direct-pbs-script.schema.json"): (
                ROOT / "contracts/direct-execution/reviewed-direct-pbs-script.schema.json"
            ),
            Path("references/direct-trusted-session-composition.md"): (
                ROOT / "docs/v2.7-direct-trusted-session-composition.md"
            ),
            Path("references/direct-one-hop-transport.md"): (
                ROOT / "docs/v2.7-direct-one-hop-transport.md"
            ),
        }
        for target, source in expected.items():
            self.assertEqual(package[target], source)

    def test_production_root_rebind_rejects_before_artifact_write_or_owner_chain(self) -> None:
        forbidden_codes = {
            SESSION._write_exact.__code__,
            W1.DirectRootOwnerContractOwner.issue_server_session_capability_from_exact_artifacts_once.__code__,
            W3.DirectEffectTimeReplayIngressOwner.seal_server_session_once.__code__,
            W2.consume_for_server_session_replay_once.__code__,
            W4.DirectRootFixedMutationOwner.issue_session_once.__code__,
        }
        observed: list[object] = []

        def profile(frame: object, event: str, _arg: object) -> None:
            if event == "call" and getattr(frame, "f_code", None) in forbidden_codes:
                observed.append(getattr(frame, "f_code"))

        with tempfile.TemporaryDirectory(prefix="auto-g16-session-root-rebind-") as raw:
            hostile_root = Path(raw).resolve()
            previous = sys.getprofile()
            sys.setprofile(profile)
            try:
                with mock.patch.object(
                    SESSION,
                    "FIXED_PRODUCTION_DURABLE_STATE_ROOT",
                    hostile_root,
                ):
                    with self.assertRaisesRegex(
                        SESSION.DirectTrustedSessionError,
                        "fixed production state-root binding differs",
                    ):
                        SESSION.FixedTrustedServerLocalSessionOwner.production()
            finally:
                sys.setprofile(previous)
            self.assertEqual(observed, [])
            self.assertEqual(tuple(hostile_root.iterdir()), ())

    def test_actual_fixed_clean_exec_attests_source_entrypoint_argv_env_cwd_and_fds(self) -> None:
        ready = SESSION._probe_fixed_clean_exec_for_testing(
            _test_token=SESSION._TEST_TOKEN,
        )
        self.assertEqual(ready["protocol"], SESSION.CLEAN_EXEC.PROTOCOL)
        self.assertEqual(ready["status"], "ready_no_artifacts_no_effect")
        self.assertEqual(ready["executable"], str(SESSION._FIXED_EXECUTABLE.path))
        self.assertEqual(
            ready["executable_identity"],
            list(SESSION._FIXED_EXECUTABLE.identity),
        )
        self.assertEqual(ready["executable_sha256"], SESSION._FIXED_EXECUTABLE.sha256)
        self.assertEqual(ready["helper_source_sha256"], SESSION._FIXED_HELPER_SOURCE.sha256)
        self.assertEqual(ready["session_source_sha256"], SESSION._FIXED_SESSION_SOURCE.sha256)
        self.assertEqual(ready["w5_source_sha256"], SESSION._FIXED_W5_SOURCE.sha256)
        self.assertEqual(ready["entrypoint"], ready["argv"][0])
        self.assertEqual(ready["argv"][1], SESSION.CLEAN_EXEC.CHILD_FLAG)
        self.assertEqual(ready["environment"], SESSION.FIXED_CLEAN_EXEC_ENVIRONMENT)
        self.assertEqual(ready["cwd"], SESSION.FIXED_CLEAN_EXEC_CWD)
        self.assertEqual(ready["open_fds"][:3], [0, 1, 2])
        self.assertEqual(len(ready["open_fds"]), 4)
        self.assertEqual(ready["interpreter_flags"], ["-I", "-S"])
        self.assertFalse(ready["artifacts_received"])
        self.assertEqual(ready["external_effects"], 0)

        for attribute, hostile in (
            ("FIXED_CLEAN_EXEC_CWD", "/tmp"),
            ("FIXED_CLEAN_EXEC_ENVIRONMENT", {"LANG": "hostile"}),
            ("_FIXED_HELPER_SOURCE", SESSION._FIXED_SESSION_SOURCE),
            ("_FIXED_W5_SOURCE", SESSION._FIXED_SESSION_SOURCE),
            (
                "_FIXED_EXECUTABLE",
                SESSION._ExecutableSnapshot(Path("/hostile/python"), ()),
            ),
        ):
            with self.subTest(attribute=attribute), mock.patch.object(
                SESSION,
                attribute,
                hostile,
            ), mock.patch.object(
                SESSION,
                "_FROZEN_POPEN",
                side_effect=AssertionError("must reject before exec"),
            ):
                with self.assertRaisesRegex(
                    SESSION.DirectTrustedSessionError,
                    "binding differs",
                ):
                    SESSION._probe_fixed_clean_exec_for_testing(
                        _test_token=SESSION._TEST_TOKEN,
                    )

        with mock.patch.object(
            SESSION.CLEAN_EXEC,
            "CHILD_FLAG",
            "--hostile-entrypoint",
        ), mock.patch.object(
            SESSION,
            "_FROZEN_POPEN",
            side_effect=AssertionError("must reject before exec"),
        ):
            with self.assertRaisesRegex(
                SESSION.DirectTrustedSessionError,
                "binding differs",
            ):
                SESSION._probe_fixed_clean_exec_for_testing(
                    _test_token=SESSION._TEST_TOKEN,
                )

        parent, child = socket.socketpair()
        helper_fd = SESSION._open_bound_source(SESSION._FIXED_HELPER_SOURCE)
        session_fd = SESSION._open_bound_source(SESSION._FIXED_SESSION_SOURCE)
        w5_fd = SESSION._open_bound_source(SESSION._FIXED_W5_SOURCE)
        executable_fd = SESSION._open_bound_executable(SESSION._FIXED_EXECUTABLE)
        extra_fd = os.open("/dev/null", os.O_RDONLY)
        child_fd = child.fileno()
        argv = SESSION._expected_child_argv(child_fd, helper_fd, session_fd, w5_fd, executable_fd)
        process = subprocess.Popen(
            [str(SESSION._FIXED_EXECUTABLE.path), *argv],
            close_fds=True,
            pass_fds=(child_fd, helper_fd, session_fd, w5_fd, executable_fd, extra_fd),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=dict(SESSION._FIXED_CLEAN_EXEC_ENVIRONMENT),
            cwd=SESSION._FIXED_CLEAN_EXEC_CWD,
        )
        os.close(helper_fd)
        os.close(session_fd)
        os.close(w5_fd)
        os.close(executable_fd)
        os.close(extra_fd)
        child.close()
        try:
            response = SESSION._recv_clean_exec_frame(parent)
            self.assertEqual(response["status"], "rejected")
            self.assertEqual(process.wait(timeout=10), 2)
        finally:
            parent.close()
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)

    def test_clean_exec_production_call_chain_contains_no_test_or_synthetic_factory(self) -> None:
        session_source = (SCRIPTS / "direct_trusted_session_composition.py").read_text(
            encoding="utf-8"
        )
        helper_source = (SCRIPTS / "direct_trusted_session_clean_exec.py").read_text(
            encoding="utf-8"
        )
        session_tree = ast.parse(session_source)
        helper_tree = ast.parse(helper_source)

        def function_source(source: str, tree: ast.AST, name: str) -> str:
            value = ast.get_source_segment(
                source,
                next(
                    node
                    for node in ast.walk(tree)
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name == name
                ),
            )
            self.assertIsNotNone(value)
            return value or ""

        production = "\n".join(
            (
                function_source(session_source, session_tree, "compose_production_in_fixed_clean_exec_once"),
                function_source(session_source, session_tree, "_spawn_fixed_clean_exec"),
                function_source(session_source, session_tree, "compose_once"),
                function_source(helper_source, helper_tree, "_run_child"),
            )
        )
        self.assertIn("FixedTrustedServerLocalSessionOwner.production()", production)
        self.assertIn('"status": "ready_for_w5"', production)
        self.assertIn("control.settimeout(None)", production)
        self.assertIn(
            "_consume_fixed_child_w5_transition_once",
            function_source(helper_source, helper_tree, "_run_child"),
        )
        self.assertIn(
            "w5_lease.assert_current()",
            function_source(helper_source, helper_tree, "_run_child"),
        )
        self.assertNotIn("consume_no_effect_once", production)
        for forbidden in (
            "_for_testing",
            "ClosedFakeTransport",
            "SyntheticTransaction",
            "issue_synthetic",
            "object.__new__",
        ):
            self.assertNotIn(forbidden, production)

    def test_production_owner_chain_issues_real_transaction_and_never_calls_test_or_synthetic_factories(self) -> None:
        with tempfile.TemporaryDirectory(prefix="auto-g16-session-chain-") as raw:
            fixture = PortableSessionFixture(Path(raw).resolve())
            forbidden_codes = {
                W1.DirectRootOwnerContractOwner._for_testing.__func__.__code__,
                SYNTHETIC_ROOT.DirectRootMutationBoundaryOwner._for_testing.__func__.__code__,
                SYNTHETIC_ROOT.DirectRootMutationBoundaryOwner.issue_synthetic_transaction_once.__code__,
                DIRECT.ClosedFakeTransport.__init__.__code__,
            }
            observed: list[object] = []

            def profile(frame: object, event: str, _arg: object) -> None:
                if event == "call" and getattr(frame, "f_code", None) in forbidden_codes:
                    observed.append(getattr(frame, "f_code"))

            previous = sys.getprofile()
            sys.setprofile(profile)
            try:
                capability = fixture.compose()
            finally:
                sys.setprofile(previous)
                fixture.close()
            self.assertEqual(observed, [])
            record = SESSION._SESSION_REGISTRY[capability]
            self.assertIs(type(record["transaction"]), DIRECT.DirectServerSessionTransaction)
            self.assertEqual(record["transaction"].state(), DIRECT.READY)
            for operation in (
                lambda: copy.copy(record["transaction"]),
                lambda: copy.deepcopy(record["transaction"]),
                lambda: pickle.dumps(record["transaction"]),
            ):
                with self.assertRaises(TypeError):
                    operation()
            with self.assertRaises(TypeError):
                DIRECT.DirectServerSessionTransaction(
                    root_capability=record["transaction"]._root_capability,
                    immutable_input=record["transaction"]._input,
                )
            self.assertEqual(record["journal"].outcome, "started")
            self.assertIs(type(record["project"]), W4.DirectProjectSessionCapability)
            readiness = SESSION._session_ready_document(capability)
            self.assertEqual(readiness["status"], "ready_for_w5")
            lease = capability.consume_for_w5_once()
            lease.assert_current()
            SESSION._retire_w5_lease_for_testing(
                lease,
                _test_token=SESSION._TEST_TOKEN,
            )

    def test_w2_rejects_replacement_w3_module_before_started_publication(self) -> None:
        with tempfile.TemporaryDirectory(prefix="auto-g16-session-w2-w3-forgery-") as raw:
            fixture = PortableSessionFixture(Path(raw).resolve())
            canonical_module = sys.modules[W3.MODULE_NAME]
            forged_module = types.ModuleType(W3.MODULE_NAME)
            forged_module.__file__ = W3.__file__

            class ForgedW3Capability:
                def assert_server_session_pre_w2_current(
                    self,
                    _transaction: object,
                ) -> object:
                    return self

            ForgedW3Capability.__module__ = W3.MODULE_NAME
            forged_module.DirectEffectTimeReplayIngressCapability = ForgedW3Capability
            target = W2.consume_for_server_session_replay_once.__code__

            def profile(frame: object, event: str, _arg: object) -> None:
                if event == "call" and getattr(frame, "f_code", None) is target:
                    sys.setprofile(None)
                    sys.modules[W3.MODULE_NAME] = forged_module

            try:
                sys.setprofile(profile)
                with self.assertRaisesRegex(
                    W2.DirectDurableJournalError,
                    "canonical W3 module, type, exact descriptor code, or source binding differs",
                ):
                    fixture.compose()
            finally:
                sys.setprofile(None)
                sys.modules[W3.MODULE_NAME] = canonical_module
                fixture.close()
            self.assertEqual(list(fixture.state.rglob(W2.STARTED_BASENAME)), [])
            self.assertEqual(tuple(fixture.state.iterdir()), ())

    def test_w2_rejects_replacement_w3_type_before_started_publication(self) -> None:
        with tempfile.TemporaryDirectory(prefix="auto-g16-session-w2-w3-type-") as raw:
            fixture = PortableSessionFixture(Path(raw).resolve())
            canonical_type = W3.DirectEffectTimeReplayIngressCapability
            target = W2.consume_for_server_session_replay_once.__code__
            forged_type = type(
                "DirectEffectTimeReplayIngressCapability",
                (),
                {
                    "__module__": W3.MODULE_NAME,
                    "assert_server_session_pre_w2_current": lambda self, _transaction: self,
                },
            )

            def profile(frame: object, event: str, _arg: object) -> None:
                if event == "call" and getattr(frame, "f_code", None) is target:
                    sys.setprofile(None)
                    W3.DirectEffectTimeReplayIngressCapability = forged_type

            try:
                sys.setprofile(profile)
                with self.assertRaisesRegex(
                    W2.DirectDurableJournalError,
                    "canonical W3 module, type, exact descriptor code, or source binding differs",
                ):
                    fixture.compose()
            finally:
                sys.setprofile(None)
                W3.DirectEffectTimeReplayIngressCapability = canonical_type
                fixture.close()
            self.assertEqual(list(fixture.state.rglob(W2.STARTED_BASENAME)), [])
            self.assertEqual(tuple(fixture.state.iterdir()), ())

    def test_w2_active_w3_import_rejects_first_registration_poisoning(self) -> None:
        with tempfile.TemporaryDirectory(prefix="auto-g16-w2-first-poison-") as raw:
            state = Path(raw).resolve()
            probe = r'''
import pathlib, sys, types
scripts = pathlib.Path(sys.argv[1]).resolve()
state = pathlib.Path(sys.argv[2]).resolve()
sys.path.insert(0, str(scripts))
import direct_ssh_pbs_offline as direct
import direct_durable_submission_journal as w2
w3_name = "direct_effect_time_replay_ingress"
registration = "_auto_g16_direct_effect_time_replay_ingress_owner_registration_v1"
source = scripts / "direct_effect_time_replay_ingress.py"
fake = types.ModuleType(w3_name)
fake.__file__ = str(source)
namespace = {"__name__": w3_name}
exec(compile("def capability_assert_server_session_pre_w2(self, transaction):\n    return self\n", str(source), "exec"), namespace)
forged_assertion = namespace["capability_assert_server_session_pre_w2"]
forged_type = type("DirectEffectTimeReplayIngressCapability", (), {})
forged_type.__module__ = w3_name
setattr(forged_type, "assert_server_session_pre_w2_current", forged_assertion)
fake.DirectEffectTimeReplayIngressCapability = forged_type
fake.MODULE_NAME = w3_name
fake.REGISTRATION_ATTRIBUTE = registration
sys.modules[w3_name] = fake
setattr(direct, registration, fake)
try:
    w2._activate_canonical_w3_owner_once()
except w2.DirectDurableJournalError as exc:
    if "canonical W3 module, type, exact descriptor code, or source binding differs" not in str(exc):
        raise
else:
    raise AssertionError("FIRST_REGISTRATION_POISONING_ACCEPTED")
if tuple(state.iterdir()):
    raise AssertionError("JOURNAL_EFFECT_BEFORE_REJECTION")
print("FIRST_REGISTRATION_POISONING_REJECTED")
print("STARTED_FILES=0")
'''
            result = subprocess.run(
                [sys.executable, "-c", probe, str(SCRIPTS), str(state)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                result.stdout,
                "FIRST_REGISTRATION_POISONING_REJECTED\nSTARTED_FILES=0\n",
            )
            self.assertEqual(tuple(state.iterdir()), ())

    def test_w2_fixed_activation_rejects_meta_path_w3_resolution_before_started(self) -> None:
        with tempfile.TemporaryDirectory(prefix="auto-g16-w2-meta-path-") as raw:
            state = Path(raw).resolve()
            probe = r'''
import pathlib, sys
scripts = pathlib.Path(sys.argv[1]).resolve()
state = pathlib.Path(sys.argv[2]).resolve()
sys.path.insert(0, str(scripts))
import direct_durable_submission_journal as w2

class ForgedW3Finder:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "direct_effect_time_replay_ingress":
            raise AssertionError("META_PATH_FINDER_WAS_CONSULTED")
        return None

finder = ForgedW3Finder()
sys.meta_path.insert(0, finder)
try:
    w2._activate_canonical_w3_owner_once()
except w2.DirectDurableJournalError as exc:
    if "fixed import resolution binding differs" not in str(exc):
        raise
else:
    raise AssertionError("META_PATH_W3_POISONING_ACCEPTED")
if "direct_effect_time_replay_ingress" in sys.modules:
    raise AssertionError("W3_WAS_LOADED_AFTER_META_PATH_DRIFT")
if tuple(state.iterdir()):
    raise AssertionError("JOURNAL_EFFECT_BEFORE_REJECTION")
print("META_PATH_W3_POISONING_REJECTED")
print("STARTED_FILES=0")
'''
            result = subprocess.run(
                [sys.executable, "-c", probe, str(SCRIPTS), str(state)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                result.stdout,
                "META_PATH_W3_POISONING_REJECTED\nSTARTED_FILES=0\n",
            )
            self.assertEqual(tuple(state.iterdir()), ())

    def test_w2_rejects_preimport_meta_path_w3_finder_before_started(self) -> None:
        with tempfile.TemporaryDirectory(prefix="auto-g16-w2-preimport-finder-") as raw:
            state = Path(raw).resolve()
            probe = r'''
import pathlib, sys
scripts = pathlib.Path(sys.argv[1]).resolve()
state = pathlib.Path(sys.argv[2]).resolve()
sys.path.insert(0, str(scripts))

class ForgedW3Finder:
    calls = 0
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "direct_effect_time_replay_ingress":
            self.calls += 1
            raise AssertionError("FORGED_W3_IMPORT_RESOLUTION_USED")
        return None

finder = ForgedW3Finder()
sys.meta_path.insert(0, finder)
import direct_durable_submission_journal as w2
try:
    w2._activate_canonical_w3_owner_once()
except w2.DirectDurableJournalError as exc:
    if "requires isolated import resolution" not in str(exc):
        raise
else:
    raise AssertionError("PREIMPORT_META_PATH_W3_POISONING_ACCEPTED")
if finder.calls:
    raise AssertionError("FORGED_W3_FINDER_WAS_CONSULTED")
if "direct_effect_time_replay_ingress" in sys.modules:
    raise AssertionError("W3_WAS_LOADED_AFTER_PREIMPORT_FINDER")
if tuple(state.iterdir()):
    raise AssertionError("JOURNAL_EFFECT_BEFORE_REJECTION")
print("PREIMPORT_META_PATH_W3_POISONING_REJECTED")
print("STARTED_FILES=0")
'''
            result = subprocess.run(
                [sys.executable, "-c", probe, str(SCRIPTS), str(state)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                result.stdout,
                "PREIMPORT_META_PATH_W3_POISONING_REJECTED\nSTARTED_FILES=0\n",
            )
            self.assertEqual(tuple(state.iterdir()), ())

    def test_w2_and_w3_isolated_import_orders_activate_canonical_binding(self) -> None:
        probe = r'''
import pathlib, sys
scripts = pathlib.Path(sys.argv[1]).resolve()
order = sys.argv[2]
sys.path.insert(0, str(scripts))
from tests import test_live_approval_effect_time_replay as support
if order == "w2-first":
    import direct_durable_submission_journal as w2
    import direct_effect_time_replay_ingress as w3
elif order == "w3-first":
    import direct_effect_time_replay_ingress as w3
    import direct_durable_submission_journal as w2
else:
    raise AssertionError("UNKNOWN_IMPORT_ORDER")
w2._activate_canonical_w3_owner_once()
if sys.modules.get(w3.MODULE_NAME) is not w3:
    raise AssertionError("CANONICAL_W3_IDENTITY_DIFFERS")
if vars(w2.DIRECT).get(w3.REGISTRATION_ATTRIBUTE) is not w3:
    raise AssertionError("CANONICAL_W3_REGISTRATION_DIFFERS")
print(order.upper() + "_CANONICAL_ACTIVE")
'''
        for order in ("w2-first", "w3-first"):
            with self.subTest(order=order):
                result = subprocess.run(
                    [sys.executable, "-c", probe, str(SCRIPTS), order],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(
                    result.stdout,
                    order.upper() + "_CANONICAL_ACTIVE\n",
                )

    def test_w2_rejects_w3_descriptor_replacement_before_started_publication(self) -> None:
        with tempfile.TemporaryDirectory(prefix="auto-g16-session-w2-w3-method-") as raw:
            fixture = PortableSessionFixture(Path(raw).resolve())
            capability_type = W3.DirectEffectTimeReplayIngressCapability
            descriptor_name = "assert_server_session_pre_w2_current"
            canonical_descriptor = vars(capability_type)[descriptor_name]
            target = W2.consume_for_server_session_replay_once.__code__

            def forged_descriptor(self: object, _transaction: object) -> object:
                return self

            def profile(frame: object, event: str, _arg: object) -> None:
                if event == "call" and getattr(frame, "f_code", None) is target:
                    sys.setprofile(None)
                    setattr(capability_type, descriptor_name, forged_descriptor)

            try:
                sys.setprofile(profile)
                with self.assertRaisesRegex(
                    W2.DirectDurableJournalError,
                    "canonical W3 module, type, exact descriptor code, or source binding differs",
                ):
                    fixture.compose()
            finally:
                sys.setprofile(None)
                setattr(capability_type, descriptor_name, canonical_descriptor)
                fixture.close()
            self.assertEqual(list(fixture.state.rglob(W2.STARTED_BASENAME)), [])
            self.assertEqual(tuple(fixture.state.iterdir()), ())

    def test_w2_rejects_foreign_exact_objects_before_started_publication(self) -> None:
        class CapturedHostileProbe(Exception):
            pass

        with tempfile.TemporaryDirectory(prefix="auto-g16-session-w2-cross-") as raw:
            fixture = PortableSessionFixture(Path(raw).resolve())
            target = W2.consume_for_server_session_replay_once.__code__

            def profile(frame: object, event: str, _arg: object) -> None:
                if event == "call" and getattr(frame, "f_code", None) is target:
                    sys.setprofile(None)
                    transaction = frame.f_locals["direct_transaction"]
                    capability = frame.f_locals["w3_capability"]
                    foreign_transaction = object.__new__(
                        DIRECT.DirectServerSessionTransaction
                    )
                    with self.assertRaises(Exception):
                        W2.consume_for_server_session_replay_once(
                            fixture.state,
                            foreign_transaction,
                            capability,
                        )
                    foreign_capability = object.__new__(
                        W3.DirectEffectTimeReplayIngressCapability
                    )
                    with self.assertRaisesRegex(
                        W3.DirectEffectTimeReplayIngressError,
                        "canonical state identity differs",
                    ):
                        W2.consume_for_server_session_replay_once(
                            fixture.state,
                            transaction,
                            foreign_capability,
                        )
                    raise CapturedHostileProbe

            try:
                sys.setprofile(profile)
                with self.assertRaises(CapturedHostileProbe):
                    fixture.compose()
            finally:
                sys.setprofile(None)
                fixture.close()
            self.assertEqual(list(fixture.state.rglob(W2.STARTED_BASENAME)), [])
            self.assertEqual(tuple(fixture.state.iterdir()), ())

    def test_w3_same_module_reload_is_rejected_before_started_publication(self) -> None:
        with tempfile.TemporaryDirectory(prefix="auto-g16-w3-reload-") as raw:
            state = Path(raw).resolve()
            probe = r'''
import importlib, pathlib, sys
scripts = pathlib.Path(sys.argv[1]).resolve()
state = pathlib.Path(sys.argv[2]).resolve()
sys.path.insert(0, str(scripts))
from tests import test_live_approval_effect_time_replay as support
import direct_durable_submission_journal as w2
import direct_effect_time_replay_ingress as w3
w2._activate_canonical_w3_owner_once()
try:
    importlib.reload(w3)
except ImportError as exc:
    if "already executed" not in str(exc):
        raise
else:
    raise AssertionError("W3_RELOAD_ACCEPTED")
if tuple(state.iterdir()):
    raise AssertionError("JOURNAL_EFFECT_BEFORE_RELOAD_REJECTION")
print("W3_RELOAD_REJECTED")
print("STARTED_FILES=0")
'''
            result = subprocess.run(
                [sys.executable, "-c", probe, str(SCRIPTS), str(state)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                result.stdout,
                "W3_RELOAD_REJECTED\nSTARTED_FILES=0\n",
            )
            self.assertEqual(tuple(state.iterdir()), ())

    def test_fixed_child_w5_transition_is_exact_non_authorizing_and_retains_lease(self) -> None:
        with tempfile.TemporaryDirectory(prefix="auto-g16-session-child-w5-") as raw:
            fixture = PortableSessionFixture(Path(raw).resolve())
            try:
                capability = fixture.compose()
                readiness = SESSION._session_ready_document(capability)
                request = SESSION._fixed_w5_transition_request(readiness)
                foreign = {**request, "session_id": "direct-trusted-session-" + "f" * 64}
                with self.assertRaisesRegex(
                    SESSION.DirectTrustedSessionError,
                    "transition frame differs",
                ):
                    SESSION._consume_fixed_child_w5_transition_once(
                        capability,
                        readiness,
                        foreign,
                    )
                capability.assert_current()
                self.assertFalse(
                    (fixture.state / W2.journal_id_for_binding(
                        SESSION._SESSION_REGISTRY[capability]["transaction"]._binding
                    ) / W2.TERMINAL_BASENAME).exists()
                )
                lease, ack = SESSION._consume_fixed_child_w5_transition_once(
                    capability,
                    readiness,
                    request,
                )
                lease.assert_current()
                self.assertEqual(ack["status"], "w5_lease_ready")
                self.assertFalse(ack["authorizes_effect"])
                self.assertFalse(ack["transport_connected"])
                self.assertEqual(ack["external_effects"], 0)
                self.assertEqual(ack["qsub_calls"], 0)
                self.assertFalse(ack["production_closure"])
                self.assertNotIn("lease", ack)
                self.assertFalse(hasattr(lease, "fd"))
                self.assertFalse(hasattr(lease, "path"))
                project = SESSION._SESSION_REGISTRY[capability]["project"]
                project.assert_current()
                self.assertFalse(
                    (fixture.state / SESSION._SESSION_REGISTRY[capability]["journal"].journal_id
                     / W2.TERMINAL_BASENAME).exists()
                )
                SESSION._retire_w5_lease_for_testing(
                    lease,
                    _test_token=SESSION._TEST_TOKEN,
                )
            finally:
                fixture.close()

    def test_parent_handle_sends_one_fixed_transition_and_duplicate_closes_child(self) -> None:
        with tempfile.TemporaryDirectory(prefix="auto-g16-session-parent-w5-") as raw:
            fixture = PortableSessionFixture(Path(raw).resolve())
            capability = fixture.compose()
            readiness = SESSION._session_ready_document(capability)
            parent, child = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
            child_script = r'''
import json, socket, struct, sys
s = socket.socket(fileno=int(sys.argv[1]))
def exact(n):
    value = b""
    while len(value) < n:
        chunk = s.recv(n - len(value))
        if not chunk:
            raise SystemExit(2)
        value += chunk
    return value
size = struct.unpack("!I", exact(4))[0]
request = json.loads(exact(size))
ack = {
    "protocol": request["protocol"],
    "status": "w5_lease_ready",
    "session_id": request["session_id"],
    "readiness_payload_sha256": request["readiness_payload_sha256"],
    "authorizes_effect": False,
    "transport_connected": False,
    "external_effects": 0,
    "qsub_calls": 0,
    "production_closure": False,
}
raw = json.dumps(ack, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode()
s.sendall(struct.pack("!I", len(raw)) + raw)
while s.recv(1):
    pass
raise SystemExit(3)
'''
            process = subprocess.Popen(
                [sys.executable, "-c", child_script, str(child.fileno())],
                close_fds=True,
                pass_fds=(child.fileno(),),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            child.close()
            handle = SESSION._issue_child_session_handle(
                process=process,
                control=parent,
                readiness=readiness,
            )
            try:
                ack = handle.transition_to_w5_once()
                self.assertEqual(ack["status"], "w5_lease_ready")
                self.assertFalse(ack["authorizes_effect"])
                self.assertEqual(handle.readiness(), readiness)
                self.assertEqual(
                    {
                        name
                        for name, value in vars(
                            SESSION.FixedTrustedServerLocalChildSession
                        ).items()
                        if callable(value) and not name.startswith("__")
                    },
            {"readiness", "transition_to_w5_once", "submit_once"},
                )
                self.assertIsNone(process.poll())
                with self.assertRaisesRegex(
                    SESSION.DirectTrustedSessionError,
                    "foreign, forked, exited, or terminal",
                ):
                    handle.transition_to_w5_once()
                self.assertEqual(process.wait(timeout=10), 3)
            finally:
                parent.close()
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=10)
                SESSION._retire_session_unknown_once(
                    capability,
                    "parent-transition-test-retirement",
                )
                fixture.close()

    def test_call_order_is_w2_started_then_w3_consume_then_w4_handoff(self) -> None:
        with tempfile.TemporaryDirectory(prefix="auto-g16-session-order-") as raw:
            fixture = PortableSessionFixture(Path(raw).resolve())
            calls: list[str] = []
            codes = {
                W1.DirectRootOwnerContractOwner.issue_server_session_capability_from_exact_artifacts_once.__code__: "w1_owner_issue",
                DIRECT.DirectServerSessionTransactionOwner.issue_once.__code__: "direct_owner_issue",
                RESOURCE.reserve_attempt_capability.__code__: "resource_owner_issue",
                RESOURCE_REPLAY.issue_resource_effect_time_replay_capability.__code__: "resource_replay_issue",
                LIVE.LiveApprovalEffectTimeReplayOwner.issue_direct_server_session_once.__code__: "live_owner_issue",
                W3.DirectEffectTimeReplayIngressOwner.seal_server_session_once.__code__: "w3_owner_issue",
                W2.consume_for_server_session_replay_once.__code__: "w2_started",
                W3.DirectEffectTimeReplayIngressCapability.consume_once.__code__: "w3_consume",
                W4.SingleUseDirectRootFixedMutation.apply_for_session_once.__code__: "w4_scm_rights",
            }

            def profile(frame: object, event: str, _arg: object) -> None:
                if event == "call":
                    label = codes.get(getattr(frame, "f_code", None))
                    if label is not None:
                        calls.append(label)

            try:
                previous = sys.getprofile()
                sys.setprofile(profile)
                try:
                    capability = fixture.compose()
                finally:
                    sys.setprofile(previous)
                self.assertEqual(
                    calls,
                    [
                        "w1_owner_issue",
                        "direct_owner_issue",
                        "resource_owner_issue",
                        "resource_replay_issue",
                        "live_owner_issue",
                        "w3_owner_issue",
                        "w2_started",
                        "w3_consume",
                        "w4_scm_rights",
                    ],
                )
                readiness = SESSION._session_ready_document(capability)
                self.assertEqual(readiness["durable_terminal_outcome"], "none")
                lease = capability.consume_for_w5_once()
                SESSION._retire_w5_lease_for_testing(
                    lease,
                    _test_token=SESSION._TEST_TOKEN,
                )
            finally:
                fixture.close()

    def test_every_exception_after_w2_started_records_unknown_never_completed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="auto-g16-session-unknown-") as raw:
            fixture = PortableSessionFixture(Path(raw).resolve())
            captured: dict[str, object] = {}

            target_code = W4.DirectRootFixedMutationOwner.issue_session_once.__code__

            def profile(frame: object, event: str, _arg: object) -> None:
                if event == "call" and getattr(frame, "f_code", None) is target_code:
                    captured["claim"] = frame.f_locals["durable_journal_claim"]
                    captured["binding"] = frame.f_locals["direct_binding"]

            try:
                sys.setprofile(profile)
                with mock.patch.object(
                    W4, "_EXECUTE", side_effect=RuntimeError("injected after durable started")
                ), mock.patch.object(W4, "_MODULE_BINDING", W4._capture_module_binding()):
                    with self.assertRaisesRegex(RuntimeError, "injected after durable started"):
                        fixture.compose()
                sys.setprofile(None)
                claim = captured["claim"]
                binding = captured["binding"]
                self.assertIs(type(claim), W2.DurableEffectClaim)
                snapshot = W2.reconcile_read_only(fixture.state, claim.journal_id, binding).document()
                self.assertEqual(snapshot["last_recorded_outcome"], "unknown")
                self.assertEqual(snapshot["effective_outcome"], "unknown")
                terminal = json.loads(
                    (fixture.state / claim.journal_id / W2.TERMINAL_BASENAME).read_text(encoding="utf-8")
                )
                self.assertEqual(terminal["event_type"], "effect_outcome_unknown")
                self.assertNotEqual(terminal["event_type"], "effect_completed")
            finally:
                sys.setprofile(None)
                fixture.close()

    def test_w3_consume_failure_after_w2_started_is_unknown_and_never_reclaimed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="auto-g16-session-w3-after-w2-") as raw:
            fixture = PortableSessionFixture(Path(raw).resolve())
            captured: dict[str, object] = {}
            target_code = W3.DirectEffectTimeReplayIngressCapability.consume_once.__code__

            def profile(frame: object, event: str, _arg: object) -> None:
                if event == "call" and getattr(frame, "f_code", None) is target_code:
                    caller = getattr(frame, "f_back", None)
                    captured["claim"] = caller.f_locals["journal"]
                    captured["binding"] = caller.f_locals["transaction"]._binding
                    sys.setprofile(None)
                    raise RuntimeError("injected exact W3 consume failure after W2 started")

            try:
                sys.setprofile(profile)
                with self.assertRaisesRegex(RuntimeError, "W3 consume failure"):
                    fixture.compose()
                claim = captured["claim"]
                binding = captured["binding"]
                snapshot = W2.reconcile_read_only(
                    fixture.state,
                    claim.journal_id,
                    binding,
                ).document()
                self.assertEqual(snapshot["last_recorded_outcome"], "unknown")
                self.assertEqual(snapshot["effective_outcome"], "unknown")
                with self.assertRaisesRegex(W2.DirectDurableJournalError, "already exists"):
                    W2.consume_for_effect_once(fixture.state, binding)
            finally:
                sys.setprofile(None)
                fixture.close()

    def test_exact_join_single_use_nonportable_no_effect_and_restart_read_only(self) -> None:
        with tempfile.TemporaryDirectory(prefix="auto-g16-session-success-") as raw:
            fixture = PortableSessionFixture(Path(raw).resolve())
            try:
                capability = fixture.compose()
                capability.assert_current()
                result = SESSION._session_ready_document(capability)
                for operation in (
                    lambda: copy.copy(capability),
                    lambda: copy.deepcopy(capability),
                    lambda: pickle.dumps(capability),
                ):
                    with self.assertRaises(TypeError):
                        operation()
                with ThreadPoolExecutor(max_workers=8) as pool:
                    futures = [pool.submit(capability.consume_for_w5_once) for _ in range(8)]
                    values: list[object] = []
                    for future in futures:
                        try:
                            values.append(future.result())
                        except SESSION.DirectTrustedSessionError as exc:
                            values.append(str(exc))
                results = [item for item in values if type(item) is SESSION.TrustedServerLocalW5Lease]
                self.assertEqual(len(results), 1)
                lease = results[0]
                lease.assert_current()
                self.assertEqual(
                    {
                        name
                        for name, value in vars(SESSION.TrustedServerLocalSessionCapability).items()
                        if callable(value) and not name.startswith("__")
                    },
                    {"assert_current", "consume_for_w5_once"},
                )
                self.assertEqual(
                    {
                        name
                        for name, value in vars(SESSION.TrustedServerLocalW5Lease).items()
                        if callable(value) and not name.startswith("__")
                    },
                    {"assert_current"},
                )
                for forbidden in ("project_fd", "project_path", "root_fd", "descriptor"):
                    self.assertFalse(hasattr(lease, forbidden))
                self.assertFalse(result["authority"]["authorizes_effect"])
                self.assertEqual(result["authority"]["qsub_calls"], 0)
                self.assertEqual(result["authority"]["external_effects"], 0)
                self.assertFalse(result["authority"]["transport_connected"])
                self.assertFalse(result["policy"]["production_closure"])
                for section, field, replacement in (
                    ("authority", "qsub_calls", False),
                    ("authority", "external_effects", False),
                    ("policy", "portable_artifacts_are_authority", 0),
                ):
                    hostile = copy.deepcopy(result)
                    hostile[section][field] = replacement
                    hostile["result_payload_sha256"] = ""
                    hostile["result_payload_sha256"] = SESSION.digest(hostile)
                    with self.assertRaises(SESSION.DirectTrustedSessionError):
                        SESSION.validate_trusted_session_result(hostile)
                record = SESSION._SESSION_REGISTRY[capability]
                binding = record["transaction"]._binding
                journal_id = result["journal_id"]
                self.assertFalse((fixture.state / journal_id / W2.TERMINAL_BASENAME).exists())
                with self.assertRaisesRegex(W2.DirectDurableJournalError, "already exists"):
                    W2.consume_for_effect_once(fixture.state, binding)
                SESSION._retire_w5_lease_for_testing(
                    lease,
                    _test_token=SESSION._TEST_TOKEN,
                )
                before = tuple(sorted((fixture.state / journal_id).iterdir()))
                snapshot = W2.reconcile_read_only(fixture.state, journal_id, binding).document()
                after = tuple(sorted((fixture.state / journal_id).iterdir()))
                self.assertEqual(before, after)
                self.assertEqual(snapshot["effective_outcome"], "unknown")
            finally:
                fixture.close()

    def test_project_fd_handoff_identity_fork_close_and_reuse_fail_closed(self) -> None:
        for case in ("path-drift", "fork", "close-reuse"):
            with self.subTest(case=case), tempfile.TemporaryDirectory(prefix="auto-g16-session-fd-") as raw:
                fixture = PortableSessionFixture(Path(raw).resolve())
                try:
                    capability = fixture.compose()
                    project = SESSION._SESSION_REGISTRY[capability]["project"]
                    record = W4._SESSION_REGISTRY[project]
                    descriptor = record["project_fd"]
                    self.assertTrue(stat.S_ISDIR(os.fstat(descriptor).st_mode))
                    self.assertTrue(fcntl.fcntl(descriptor, fcntl.F_GETFD) & fcntl.FD_CLOEXEC)
                    if case == "path-drift":
                        current = fixture.root / "safejob"
                        current.rename(fixture.root / "retained")
                        current.mkdir()
                        with self.assertRaisesRegex(W4.DirectRootFixedMutationError, "drifted"):
                            project.assert_current()
                    elif case == "fork":
                        context = multiprocessing.get_context("fork")
                        queue = context.Queue()
                        process = context.Process(target=_fork_assert, args=(capability, queue))
                        process.start()
                        process.join(timeout=15)
                        self.assertEqual(process.exitcode, 0)
                        self.assertEqual(queue.get(timeout=5)[0], "rejected")
                        capability.assert_current()
                    else:
                        os.close(descriptor)
                        reused = os.open("/dev/null", os.O_RDONLY)
                        try:
                            if reused != descriptor:
                                os.dup2(reused, descriptor)
                            with self.assertRaises((W4.DirectRootFixedMutationError, OSError)):
                                project.assert_current()
                        finally:
                            if reused != descriptor:
                                os.close(reused)
                    try:
                        SESSION._retire_session_unknown_once(
                            capability,
                            "fd-hostile-test-retirement",
                        )
                    except Exception:
                        pass
                    if project in W4._SESSION_REGISTRY:
                        W4._close_project_session_capability(project, expected_status=None)
                finally:
                    fixture.close()

    def test_partial_frame_exactly_one_project_fd_and_extra_missing_rights_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="auto-g16-session-frame-") as raw:
            root = Path(raw).resolve()
            project = root / "safejob"
            project.mkdir(mode=0o700)
            root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            project_fd = os.open(project, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            request = b"fixed-request"
            frame = {
                "protocol": HELPER.PROTOCOL,
                "state": HELPER.SESSION_COMPLETED_STATE,
                "operations_completed": list(W4.OPERATIONS),
                "request_sha256": hashlib.sha256(request).hexdigest(),
                "project_identity": list(W4._directory_identity(os.fstat(project_fd))),
            }
            payload = W4.canonical_bytes(frame)
            for count in (1, 0, 2):
                parent, child = socket.socketpair()
                try:
                    rights = array.array("i", [project_fd] * count)
                    ancillary = [] if count == 0 else [(socket.SOL_SOCKET, socket.SCM_RIGHTS, rights.tobytes())]
                    header = struct.pack("!I", len(payload))
                    self.assertEqual(child.sendmsg([header[:1]], ancillary), 1)
                    child.sendall(header[1:] + payload[:9])
                    child.sendall(payload[9:])
                    if count == 1:
                        value, received_fd, _identity = W4._recv_project_descriptor(
                            parent,
                            request=request,
                            root_descriptor=root_fd,
                            project="safejob",
                        )
                        self.assertEqual(value, frame)
                        os.close(received_fd)
                    else:
                        with self.assertRaisesRegex(
                            W4.DirectRootFixedMutationError,
                            "exactly one native FD integer|exactly one FD and one ancillary",
                        ):
                            W4._recv_project_descriptor(
                                parent,
                                request=request,
                                root_descriptor=root_fd,
                                project="safejob",
                            )
                finally:
                    parent.close()
                    child.close()
            os.close(project_fd)
            os.close(root_fd)

    def test_malformed_ancillary_tail_zero_multiple_and_extra_records_close_every_received_fd(self) -> None:
        class ScriptedControl:
            def __init__(self, header: bytes, ancillary: list[tuple[int, int, bytes]], body: bytes) -> None:
                self.header = header
                self.ancillary = ancillary
                self.body = body

            def recvmsg(self, _size: int, _ancillary_size: int) -> tuple[bytes, list[tuple[int, int, bytes]], int, None]:
                return self.header, self.ancillary, 0, None

            def recv(self, size: int) -> bytes:
                chunk, self.body = self.body[:size], self.body[size:]
                return chunk

        with tempfile.TemporaryDirectory(prefix="auto-g16-session-ancillary-") as raw:
            root = Path(raw).resolve()
            project = root / "safejob"
            project.mkdir(mode=0o700)
            root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            project_fd = os.open(project, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            request = b"fixed-request"
            frame = {
                "protocol": HELPER.PROTOCOL,
                "state": HELPER.SESSION_COMPLETED_STATE,
                "operations_completed": list(W4.OPERATIONS),
                "request_sha256": hashlib.sha256(request).hexdigest(),
                "project_identity": list(W4._directory_identity(os.fstat(project_fd))),
            }
            payload = W4.canonical_bytes(frame)
            header = struct.pack("!I", len(payload))
            cases = (
                "trailing-byte",
                "zero",
                "multiple",
                "extra-record",
                "foreign-before-rights",
            )
            try:
                for case in cases:
                    with self.subTest(case=case):
                        received = [os.dup(project_fd) for _ in range(2 if case in {"multiple", "extra-record"} else 1)]
                        if case == "trailing-byte":
                            ancillary = [
                                (
                                    socket.SOL_SOCKET,
                                    socket.SCM_RIGHTS,
                                    array.array("i", received).tobytes() + b"\x00",
                                )
                            ]
                        elif case == "zero":
                            os.close(received.pop())
                            ancillary = [(socket.SOL_SOCKET, socket.SCM_RIGHTS, b"")]
                        elif case == "multiple":
                            ancillary = [
                                (socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", received).tobytes())
                            ]
                        elif case == "extra-record":
                            ancillary = [
                                (
                                    socket.SOL_SOCKET,
                                    socket.SCM_RIGHTS,
                                    array.array("i", [descriptor]).tobytes(),
                                )
                                for descriptor in received
                            ]
                        else:
                            ancillary = [
                                (999, 999, b"foreign"),
                                (
                                    socket.SOL_SOCKET,
                                    socket.SCM_RIGHTS,
                                    array.array("i", received).tobytes(),
                                ),
                            ]
                        control = ScriptedControl(header, ancillary, payload)
                        with self.assertRaisesRegex(
                            W4.DirectRootFixedMutationError,
                            "exactly one native FD integer|exactly one FD and one ancillary",
                        ):
                            W4._recv_project_descriptor(
                                control,  # type: ignore[arg-type]
                                request=request,
                                root_descriptor=root_fd,
                                project="safejob",
                            )
                        for descriptor in received:
                            with self.assertRaises(OSError):
                                os.fstat(descriptor)
                        self.assertTrue(project.is_dir())
            finally:
                os.close(project_fd)
                os.close(root_fd)

    def test_portable_forgery_drift_expiry_same_process_policy_and_no_fallback(self) -> None:
        self.assertFalse(SESSION.POLICY["portable_artifacts_are_authority"])
        self.assertFalse(SESSION.POLICY["untrusted_arbitrary_same_process_code_allowed"])
        self.assertFalse(SESSION.POLICY["same_process_reflection_is_security_boundary"])
        self.assertFalse(SESSION.POLICY["production_closure"])
        source = (SCRIPTS / "direct_trusted_session_composition.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        self.assertNotIn("direct_root_mutation_boundary", imported)
        self.assertNotIn("legacy_rtwin_pbs", imported)
        self.assertNotIn('outcome="completed"', source)
        compose_source = ast.get_source_segment(
            source,
            next(
                node
                for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == "compose_once"
            ),
        )
        self.assertIsNotNone(compose_source)
        for forbidden in (
            "_for_testing",
            "ClosedFakeTransport",
            "SyntheticTransaction",
            "issue_synthetic",
            "object.__new__",
        ):
            self.assertNotIn(forbidden, compose_source)

        with tempfile.TemporaryDirectory(prefix="auto-g16-session-forgery-") as raw:
            fixture = PortableSessionFixture(Path(raw).resolve())
            try:
                forged = copy.deepcopy(fixture.artifacts)
                authorization = json.loads(forged.authorization)
                authorization["input"]["sha256"] = "f" * 64
                hostile = SESSION.DirectServerSessionArtifacts(
                    **{
                        **{name: getattr(forged, name) for name in forged.__dataclass_fields__},
                        "authorization": W1.canonical_bytes(authorization),
                    }
                )
                with mock.patch.object(W1, "_system_utc_now", return_value=ISSUED):
                    with self.assertRaises(Exception):
                        fixture.owner().compose_once(hostile)
                self.assertEqual(tuple(fixture.state.iterdir()), ())
                self.assertFalse((fixture.root / "safejob").exists())

                policy = json.loads(fixture.artifacts.resource_policy)
                policy["reviewer"] = "portable-forgery"
                drifted = SESSION.DirectServerSessionArtifacts(
                    **{
                        **{
                            name: getattr(fixture.artifacts, name)
                            for name in fixture.artifacts.__dataclass_fields__
                        },
                        "resource_policy": (json.dumps(policy, sort_keys=True) + "\n").encode("utf-8"),
                    }
                )
                with mock.patch.object(W1, "_system_utc_now", return_value=ISSUED):
                    with self.assertRaises(Exception):
                        fixture.owner().compose_once(drifted)
                self.assertEqual(tuple(fixture.state.iterdir()), ())

                expires = datetime.fromisoformat(
                    json.loads(fixture.artifacts.live_approval)["expires_at"].replace("Z", "+00:00")
                )
                with mock.patch.object(W1, "_system_utc_now", return_value=ISSUED), \
                        mock.patch.object(LIVE, "_system_wall_clock", return_value=expires), \
                        mock.patch.object(LIVE, "_system_monotonic_ns", return_value=10**15), \
                        mock.patch.object(RESOURCE_REPLAY, "_effect_wall_now", return_value=ISSUED), \
                        mock.patch.object(RESOURCE_REPLAY, "_effect_monotonic_ns", return_value=1_000_000_000), \
                        mock.patch.object(SESSION, "_utc_now", return_value=RESERVED):
                    with self.assertRaises(Exception):
                        fixture.owner().compose_once(fixture.artifacts)
                self.assertEqual(tuple(fixture.state.iterdir()), ())
            finally:
                fixture.close()

    def test_owner_rebind_and_module_reload_are_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="auto-g16-session-rebind-") as raw:
            fixture = PortableSessionFixture(Path(raw).resolve())
            try:
                with mock.patch.object(
                    W3.DirectEffectTimeReplayIngressOwner,
                    "seal_server_session_once",
                    lambda *_args, **_kwargs: None,
                ):
                    with self.assertRaisesRegex(SESSION.DirectTrustedSessionError, "binding differs"):
                        fixture.owner().compose_once(fixture.artifacts)
                self.assertEqual(tuple(fixture.state.iterdir()), ())
            finally:
                fixture.close()

        reload_probe = """
import importlib
import tempfile
import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd() / 'scripts'))
sys.path.insert(0, str(Path.cwd() / 'skills' / 'auto-g16-rtwin-pbs' / 'scripts'))
from tests.test_direct_trusted_session_composition import PortableSessionFixture
import direct_trusted_session_composition as session
with tempfile.TemporaryDirectory(prefix='auto-g16-session-reload-') as raw:
    fixture = PortableSessionFixture(Path(raw).resolve())
    try:
        capability = fixture.compose()
        importlib.reload(session)
        try:
            capability.assert_current()
        except Exception:
            pass
        else:
            raise SystemExit('reloaded module accepted an old session capability')
    finally:
        fixture.close()
"""
        completed = subprocess.run(
            [sys.executable, "-c", reload_probe],
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=60,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr.decode("utf-8", "replace"))


if __name__ == "__main__":
    unittest.main()
