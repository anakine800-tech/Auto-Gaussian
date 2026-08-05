#!/usr/bin/env python3
"""Hostile synthetic-filesystem tests for the fixed direct-root helper."""

from __future__ import annotations

import array
import ast
import copy
import fcntl
import inspect
import json
import os
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from tests.test_direct_root_owner_contract import (
    ATTEMPT,
    PROJECT,
    SHA_A,
    SHA_B,
    SHA_C,
    TASK,
    MutableClock,
)


ROOT = Path(__file__).parents[1]
SCRIPTS = ROOT / "scripts"
TEMP_PARENT = Path(tempfile.gettempdir()).resolve()
sys.path.insert(0, str(SCRIPTS))

import direct_root_fixed_mutation_consumer as CONSUMER  # noqa: E402
import direct_root_fixed_mutation_helper as HELPER  # noqa: E402
import direct_root_owner_contract as ROOT_OWNER  # noqa: E402
import skill_package as SKILL_PACKAGE  # noqa: E402


class DirectRootFixedMutationConsumerTests(unittest.TestCase):
    def capability(
        self,
        root: Path,
    ) -> ROOT_OWNER.SingleUseWorkspaceDescriptorCapability:
        clock = MutableClock()
        owner = ROOT_OWNER.DirectRootOwnerContractOwner._for_testing(
            clock=clock,
            nonce_source=lambda: "f" * 32,
            _test_token=ROOT_OWNER._TEST_FACTORY_TOKEN,
        )
        policy = ROOT_OWNER.build_profile_policy(
            profile_id="direct-fixed-helper",
            declared_allowed_root=str(root),
            transport_identity_binding_sha256=SHA_A,
            gaussian_runtime_binding_sha256=SHA_B,
            resource_catalog_sha256=SHA_C,
        )
        evidence = owner.issue_stable_evidence_from_reviewed_profile(policy)
        profile = ROOT_OWNER.build_direct_execution_profile(policy, evidence)
        authorization = ROOT_OWNER.build_direct_execution_authorization(
            authorization_id="direct-fixed-helper-authorization",
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
            idempotency_key="direct-fixed-helper-case",
            approved_at="2026-07-28T23:59:00.000000Z",
            not_before="2026-07-29T00:00:00.000000Z",
            expires_at="2026-07-29T01:00:00.000000Z",
            maximum_receipt_age_seconds=60,
        )
        return owner.issue_fresh_capability_from_reviewed_profile_once(
            profile=profile,
            stable_evidence=evidence,
            authorization=authorization,
        )

    @staticmethod
    def seam(
        capability: ROOT_OWNER.SingleUseWorkspaceDescriptorCapability,
    ) -> CONSUMER.DurableJournalSeamDocument:
        receipt = capability.portable_receipt()
        authorization = json.loads(capability._authorization_bytes)
        return {
            "schema": "auto-g16-direct-durable-journal-claim-seam/1",
            "journal_id": "direct-durable-submission-journal-" + "9" * 64,
            "binding_payload_sha256": "8" * 64,
            "receipt_payload_sha256": receipt["receipt_payload_sha256"],
            "authorization_scope_sha256": authorization["scope"][
                "authorization_scope_sha256"
            ],
            "workspace_binding_sha256": authorization["workspace"][
                "workspace_binding_sha256"
            ],
            "descriptor_set_sha256": receipt["observed_root"][
                "descriptor_set_sha256"
            ],
            "outcome": "started",
            "authorizes_effect": False,
        }

    def transaction(
        self,
        capability: ROOT_OWNER.SingleUseWorkspaceDescriptorCapability,
        seam: dict[str, object] | None = None,
    ) -> CONSUMER.SingleUseDirectRootFixedMutation:
        owner = CONSUMER.DirectRootFixedMutationOwner.for_posix_backend()
        return owner.issue_once(
            root_capability=capability,
            durable_journal_seam=seam or self.seam(capability),
        )

    def spawn_child(self) -> tuple[subprocess.Popen[bytes], socket.socket]:
        parent, child = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        parent.settimeout(CONSUMER.FIXED_TIMEOUT_SECONDS)
        unrelated = os.open("/dev/null", os.O_RDONLY)
        os.set_inheritable(unrelated, True)
        source_fd = os.open(
            SCRIPTS / "direct_root_fixed_mutation_helper.py",
            os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
        )
        process = subprocess.Popen(
            [
                sys.executable,
                f"/dev/fd/{source_fd}",
                HELPER.CHILD_FLAG,
                str(child.fileno()),
                str(source_fd),
            ],
            close_fds=True,
            pass_fds=(child.fileno(), source_fd),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env={},
            cwd="/",
        )
        child.close()
        os.close(source_fd)
        os.close(unrelated)
        self.assertEqual(CONSUMER._recv_frame(parent), HELPER.READY)
        return process, parent

    def send_request(
        self,
        control: socket.socket,
        capability: ROOT_OWNER.SingleUseWorkspaceDescriptorCapability,
        seam: CONSUMER.DurableJournalSeamDocument,
        *,
        changed_request: dict[str, object] | None = None,
    ) -> tuple[bytes, tuple[int, ...], str]:
        request, descriptors, project = CONSUMER._request_from_capability(
            capability,
            seam,
        )
        lease = capability.consume_once()
        self.assertIs(lease._descriptor_set._opaque_handles, descriptors)
        if changed_request is not None:
            request = CONSUMER.canonical_bytes(changed_request)
        CONSUMER._send_request_with_descriptors(control, request, descriptors)
        return request, descriptors, project

    @staticmethod
    def close_capability(
        capability: ROOT_OWNER.SingleUseWorkspaceDescriptorCapability,
    ) -> None:
        ROOT_OWNER._close_descriptor_bundle_once(
            capability._descriptor_set._descriptor_bundle,
            owner="capability",
        )

    def test_fixed_exec_helper_creates_only_project_and_scratch(self) -> None:
        with tempfile.TemporaryDirectory(prefix="auto-g16-fixed-helper-", dir=TEMP_PARENT) as temporary:
            root = Path(temporary).resolve() / "reviewed-root"
            root.mkdir()
            capability = self.capability(root)
            transaction = self.transaction(capability)
            result = transaction.apply_once()
            self.assertEqual(result["outcome"], CONSUMER.COMPLETED)
            self.assertEqual(transaction.outcome(), CONSUMER.COMPLETED)
            self.assertEqual(result["operations_completed"], list(CONSUMER.OPERATIONS))
            self.assertEqual(sorted(path.name for path in root.iterdir()), [PROJECT])
            self.assertEqual(sorted(path.name for path in (root / PROJECT).iterdir()), ["scratch"])
            self.assertTrue((root / PROJECT / "scratch").is_dir())
            self.assertEqual(stat.S_IMODE((root / PROJECT).stat().st_mode), 0o700)
            self.assertEqual(
                stat.S_IMODE((root / PROJECT / "scratch").stat().st_mode),
                0o700,
            )
            self.assertFalse(result["authority"]["remote_effect_authorized"])
            self.assertFalse(result["authority"]["durable_journal_owner_integrated"])
            self.assertFalse(result["authority"]["automatic_retry"])

    def test_concurrent_duplicate_request_has_one_winner_and_no_retry(self) -> None:
        with tempfile.TemporaryDirectory(prefix="auto-g16-fixed-helper-", dir=TEMP_PARENT) as temporary:
            root = Path(temporary).resolve() / "reviewed-root"
            root.mkdir()
            transaction = self.transaction(self.capability(root))

            def apply(_: int) -> object:
                try:
                    return transaction.apply_once()
                except CONSUMER.DirectRootFixedMutationError as exc:
                    return str(exc)

            with ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(apply, range(16)))
            self.assertEqual(sum(type(value) is dict for value in results), 1)
            self.assertEqual(sum("already consumed" in value for value in results if type(value) is str), 15)
            self.assertTrue((root / PROJECT / "scratch").is_dir())

    def test_existing_project_symlink_and_component_drift_never_overwrite(self) -> None:
        for case in ("existing", "symlink", "root-drift"):
            with self.subTest(case=case), tempfile.TemporaryDirectory(
                prefix="auto-g16-fixed-helper-",
                dir=TEMP_PARENT,
            ) as temporary:
                root = Path(temporary).resolve() / "reviewed-root"
                root.mkdir()
                capability = self.capability(root)
                transaction = self.transaction(capability)
                retained: Path | None = None
                if case == "existing":
                    (root / PROJECT).mkdir()
                    sentinel = root / PROJECT / "sentinel"
                    sentinel.write_text("preserve", encoding="utf-8")
                elif case == "symlink":
                    target = root / "target"
                    target.mkdir()
                    (root / PROJECT).symlink_to(target, target_is_directory=True)
                    sentinel = target / "sentinel"
                    sentinel.write_text("preserve", encoding="utf-8")
                else:
                    retained = root.with_name("retained-root")
                    root.rename(retained)
                    root.mkdir()
                    sentinel = retained / "sentinel"
                    sentinel.write_text("preserve", encoding="utf-8")
                result = transaction.apply_once()
                self.assertEqual(
                    result["outcome"],
                    (
                        CONSUMER.ZERO_EFFECT_TERMINAL
                        if case == "root-drift"
                        else CONSUMER.OUTCOME_UNCERTAIN
                    ),
                )
                self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserve")
                self.assertFalse((sentinel.parent / "scratch").exists())
                self.assertFalse((root / PROJECT / "scratch").exists())

    def test_module_and_function_rebinding_fail_before_spawn_or_effect(self) -> None:
        cases = (
            (subprocess, "Popen", lambda *args, **kwargs: None),
            (socket, "socketpair", lambda *args, **kwargs: None),
            (
                ROOT_OWNER.SingleUseWorkspaceDescriptorCapability,
                "consume_once",
                lambda self: None,
            ),
            (HELPER, "PROTOCOL", "foreign-helper-protocol/9"),
            (CONSUMER, "_request_from_capability", lambda *args, **kwargs: None),
            (CONSUMER, "_open_bound_helper_source", lambda *args, **kwargs: 0),
            (
                ROOT_OWNER,
                "validate_direct_execution_authorization",
                lambda *args, **kwargs: {},
            ),
        )
        for target, attribute, replacement in cases:
            with self.subTest(attribute=attribute), tempfile.TemporaryDirectory(
                prefix="auto-g16-fixed-helper-",
                dir=TEMP_PARENT,
            ) as temporary:
                root = Path(temporary).resolve() / "reviewed-root"
                root.mkdir()
                capability = self.capability(root)
                transaction = self.transaction(capability)
                with mock.patch.object(target, attribute, replacement):
                    with self.assertRaisesRegex(
                        CONSUMER.DirectRootFixedMutationError,
                        "module, helper, function, or source binding differs",
                    ):
                        transaction.apply_once()
                self.assertEqual(transaction.outcome(), CONSUMER.ZERO_EFFECT_TERMINAL)
                self.assertFalse((root / PROJECT).exists())
                self.close_capability(capability)

        with tempfile.TemporaryDirectory(prefix="auto-g16-fixed-helper-", dir=TEMP_PARENT) as temporary:
            root = Path(temporary).resolve() / "reviewed-root"
            root.mkdir()
            capability = self.capability(root)
            transaction = self.transaction(capability)
            canonical = sys.modules[CONSUMER.MODULE_NAME]
            sys.modules[CONSUMER.MODULE_NAME] = mock.Mock()
            try:
                with self.assertRaisesRegex(
                    CONSUMER.DirectRootFixedMutationError,
                    "module, helper, function, or source binding differs",
                ):
                    transaction.apply_once()
            finally:
                sys.modules[CONSUMER.MODULE_NAME] = canonical
            self.assertEqual(transaction.outcome(), CONSUMER.ZERO_EFFECT_TERMINAL)
            self.assertFalse((root / PROJECT).exists())
            self.close_capability(capability)

    def test_seam_is_typed_closed_non_authorizing_and_exactly_bound(self) -> None:
        with tempfile.TemporaryDirectory(prefix="auto-g16-fixed-helper-", dir=TEMP_PARENT) as temporary:
            root = Path(temporary).resolve() / "reviewed-root"
            root.mkdir()
            for field, replacement in (
                ("authorizes_effect", 0),
                ("authorizes_effect", True),
                ("outcome", "completed"),
                ("descriptor_set_sha256", "7" * 64),
            ):
                capability = self.capability(root)
                seam = self.seam(capability)
                seam[field] = replacement  # type: ignore[literal-required]
                with self.assertRaises(CONSUMER.DirectRootFixedMutationError):
                    self.transaction(capability, seam)
                self.assertFalse((root / PROJECT).exists())
                self.close_capability(capability)

    def test_child_crash_timeout_and_partial_mutation_are_uncertain_no_cleanup(self) -> None:
        for case in ("crash-after-project", "timeout-after-project"):
            with self.subTest(case=case), tempfile.TemporaryDirectory(
                prefix="auto-g16-fixed-helper-",
                dir=TEMP_PARENT,
            ) as temporary:
                root = Path(temporary).resolve() / "reviewed-root"
                root.mkdir()
                capability = self.capability(root)
                seam = self.seam(capability)
                process, control = self.spawn_child()
                try:
                    self.send_request(control, capability, seam)
                    self.assertEqual(CONSUMER._recv_frame(control), HELPER.VALIDATED)
                    CONSUMER._send_frame(
                        control,
                        {"protocol": HELPER.PROTOCOL, "command": "begin_project"},
                    )
                    self.assertEqual(CONSUMER._recv_frame(control), HELPER.PROJECT_CREATED)
                    if case == "crash-after-project":
                        process.kill()
                        self.assertLess(process.wait(timeout=10), 0)
                    else:
                        self.assertEqual(process.wait(timeout=10), 3)
                        timeout_result = CONSUMER._recv_frame(control)
                        self.assertEqual(timeout_result["state"], "outcome_uncertain")
                finally:
                    try:
                        control.close()
                    except OSError:
                        pass
                    self.close_capability(capability)
                self.assertTrue((root / PROJECT).is_dir())
                self.assertFalse((root / PROJECT / "scratch").exists())

    def test_project_name_replacement_after_open_cannot_redirect_scratch(self) -> None:
        with tempfile.TemporaryDirectory(prefix="auto-g16-fixed-helper-", dir=TEMP_PARENT) as temporary:
            root = Path(temporary).resolve() / "reviewed-root"
            root.mkdir()
            capability = self.capability(root)
            seam = self.seam(capability)
            process, control = self.spawn_child()
            try:
                self.send_request(control, capability, seam)
                self.assertEqual(CONSUMER._recv_frame(control), HELPER.VALIDATED)
                CONSUMER._send_frame(
                    control,
                    {"protocol": HELPER.PROTOCOL, "command": "begin_project"},
                )
                self.assertEqual(CONSUMER._recv_frame(control), HELPER.PROJECT_CREATED)
                retained = root / "retained-project"
                (root / PROJECT).rename(retained)
                replacement = root / "replacement"
                replacement.mkdir()
                (root / PROJECT).symlink_to(replacement, target_is_directory=True)
                CONSUMER._send_frame(
                    control,
                    {"protocol": HELPER.PROTOCOL, "command": "continue_scratch"},
                )
                self.assertEqual(CONSUMER._recv_frame(control), HELPER.COMPLETED)
                self.assertEqual(process.wait(timeout=10), 0)
            finally:
                control.close()
                CONSUMER._terminate_child(process)
                self.close_capability(capability)
            self.assertTrue((retained / "scratch").is_dir())
            self.assertFalse((replacement / "scratch").exists())

    def test_spawn_exec_and_child_crash_before_effect_have_zero_filesystem_effect(self) -> None:
        with tempfile.TemporaryDirectory(prefix="auto-g16-fixed-helper-", dir=TEMP_PARENT) as temporary:
            root = Path(temporary).resolve() / "reviewed-root"
            root.mkdir()
            capability = self.capability(root)
            process, control = self.spawn_child()
            process.kill()
            process.wait(timeout=10)
            control.close()
            self.assertFalse((root / PROJECT).exists())
            for descriptor in capability._descriptor_handles:
                self.assertTrue(stat.S_ISDIR(os.fstat(descriptor).st_mode))
            self.close_capability(capability)

            bad_parent, bad_child = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
            bad_source_fd = os.open(
                SCRIPTS / "direct_root_fixed_mutation_helper.py",
                os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
            )
            bad_process = subprocess.Popen(
                [
                    sys.executable,
                    f"/dev/fd/{bad_source_fd}",
                    "--foreign-entrypoint",
                    str(bad_child.fileno()),
                    str(bad_source_fd),
                ],
                close_fds=True,
                pass_fds=(bad_child.fileno(), bad_source_fd),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env={},
                cwd="/",
            )
            bad_child.close()
            os.close(bad_source_fd)
            self.assertEqual(bad_process.wait(timeout=10), 64)
            bad_parent.close()
            self.assertFalse((root / PROJECT).exists())

            with self.assertRaises(OSError):
                subprocess.Popen(
                    [str(root / "nonexistent-python"), str(SCRIPTS / "direct_root_fixed_mutation_helper.py")],
                    close_fds=True,
                    env={},
                    cwd="/",
                )
            self.assertFalse((root / PROJECT).exists())

    def test_malformed_oversize_bool_as_int_and_duplicate_frames_are_fail_closed(self) -> None:
        mutations = []
        with tempfile.TemporaryDirectory(prefix="auto-g16-fixed-helper-", dir=TEMP_PARENT) as temporary:
            root = Path(temporary).resolve() / "reviewed-root"
            root.mkdir()
            baseline_capability = self.capability(root)
            seam = self.seam(baseline_capability)
            baseline_raw, _descriptors, _project = CONSUMER._request_from_capability(
                baseline_capability,
                seam,
            )
            baseline = json.loads(baseline_raw)
            self.close_capability(baseline_capability)
            hostile = copy.deepcopy(baseline)
            hostile["descriptor_count"] = True
            mutations.append(CONSUMER.canonical_bytes(hostile))
            hostile = copy.deepcopy(baseline)
            hostile["unexpected"] = False
            mutations.append(CONSUMER.canonical_bytes(hostile))
            mutations.append(b"{" + b"x" * HELPER.MAX_FRAME_BYTES + b"}")

        for raw in mutations:
            with self.subTest(size=len(raw)), tempfile.TemporaryDirectory(
                prefix="auto-g16-fixed-helper-",
                dir=TEMP_PARENT,
            ) as temporary:
                root = Path(temporary).resolve() / "reviewed-root"
                root.mkdir()
                capability = self.capability(root)
                seam = self.seam(capability)
                process, control = self.spawn_child()
                try:
                    _request, descriptors, _project = CONSUMER._request_from_capability(capability, seam)
                    capability.consume_once()
                    rights = array.array("i", descriptors)
                    if len(raw) <= HELPER.MAX_FRAME_BYTES:
                        CONSUMER._send_request_with_descriptors(
                            control,
                            raw,
                            descriptors,
                        )
                    else:
                        header = struct.pack("!I", len(raw))
                        sent = control.sendmsg(
                            [header],
                            [(socket.SOL_SOCKET, socket.SCM_RIGHTS, rights.tobytes())],
                        )
                        self.assertEqual(sent, len(header))
                    response = CONSUMER._recv_frame(control)
                    self.assertEqual(response["state"], "rejected_no_effect")
                    process.wait(timeout=10)
                finally:
                    control.close()
                    CONSUMER._terminate_child(process)
                    self.close_capability(capability)
                self.assertFalse((root / PROJECT).exists())

        with tempfile.TemporaryDirectory(prefix="auto-g16-fixed-helper-", dir=TEMP_PARENT) as temporary:
            root = Path(temporary).resolve() / "reviewed-root"
            root.mkdir()
            capability = self.capability(root)
            seam = self.seam(capability)
            process, control = self.spawn_child()
            try:
                request, _descriptors, _project = self.send_request(control, capability, seam)
                self.assertEqual(CONSUMER._recv_frame(control), HELPER.VALIDATED)
                CONSUMER._send_frame(control, json.loads(request))
                response = CONSUMER._recv_frame(control)
                self.assertEqual(response["state"], "rejected_no_effect")
                process.wait(timeout=10)
            finally:
                control.close()
                CONSUMER._terminate_child(process)
                self.close_capability(capability)
            self.assertFalse((root / PROJECT).exists())

    def test_partial_stream_frame_with_scm_rights_preserves_one_fixed_request(self) -> None:
        with tempfile.TemporaryDirectory(prefix="auto-g16-fixed-helper-", dir=TEMP_PARENT) as temporary:
            root = Path(temporary).resolve() / "reviewed-root"
            root.mkdir()
            capability = self.capability(root)
            seam = self.seam(capability)
            process, control = self.spawn_child()
            try:
                request, descriptors, _project = CONSUMER._request_from_capability(
                    capability,
                    seam,
                )
                capability.consume_once()
                header = struct.pack("!I", len(request))
                rights = array.array("i", descriptors)
                self.assertEqual(
                    control.sendmsg(
                        [header[:1]],
                        [(socket.SOL_SOCKET, socket.SCM_RIGHTS, rights.tobytes())],
                    ),
                    1,
                )
                control.sendall(header[1:])
                for offset in range(0, len(request), 17):
                    control.sendall(request[offset : offset + 17])
                self.assertEqual(CONSUMER._recv_frame(control), HELPER.VALIDATED)
                CONSUMER._send_frame(
                    control,
                    {"protocol": HELPER.PROTOCOL, "command": "begin_project"},
                )
                self.assertEqual(CONSUMER._recv_frame(control), HELPER.PROJECT_CREATED)
                CONSUMER._send_frame(
                    control,
                    {"protocol": HELPER.PROTOCOL, "command": "continue_scratch"},
                )
                self.assertEqual(CONSUMER._recv_frame(control), HELPER.COMPLETED)
                self.assertEqual(process.wait(timeout=10), 0)
            finally:
                control.close()
                CONSUMER._terminate_child(process)
                self.close_capability(capability)
            self.assertTrue((root / PROJECT / "scratch").is_dir())

    def test_fd_cloexec_close_ownership_reuse_and_no_unrelated_inheritance(self) -> None:
        with tempfile.TemporaryDirectory(prefix="auto-g16-fixed-helper-", dir=TEMP_PARENT) as temporary:
            root = Path(temporary).resolve() / "reviewed-root"
            root.mkdir()
            capability = self.capability(root)
            handles = capability._descriptor_handles
            result = self.transaction(capability).apply_once()
            self.assertEqual(result["outcome"], CONSUMER.COMPLETED)
            for descriptor in handles:
                with self.assertRaises(OSError):
                    os.fstat(descriptor)
            reused = tuple(os.open("/dev/null", os.O_RDONLY) for _ in handles)
            try:
                self.assertEqual(set(reused), set(handles))
                self.assertTrue(
                    all(fcntl.fcntl(descriptor, fcntl.F_GETFD) & fcntl.FD_CLOEXEC for descriptor in reused)
                )
            finally:
                for descriptor in reused:
                    os.close(descriptor)

    def test_no_command_path_env_root_delete_or_transport_surface_and_package_is_additive(self) -> None:
        issue_parameters = tuple(
            inspect.signature(CONSUMER.DirectRootFixedMutationOwner.issue_once).parameters
        )
        self.assertEqual(
            issue_parameters,
            ("self", "root_capability", "durable_journal_seam"),
        )
        tree = ast.parse((SCRIPTS / "direct_root_fixed_mutation_helper.py").read_text(encoding="utf-8"))
        imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        for forbidden in (
            "argparse",
            "paramiko",
            "shlex",
            "shutil",
            "direct_root_owner_contract",
            "direct_ssh_pbs_offline",
            "legacy_rtwin_pbs",
        ):
            self.assertNotIn(forbidden, imports)
        source = (SCRIPTS / "direct_root_fixed_mutation_helper.py").read_text(encoding="utf-8")
        for forbidden in ("os.remove", "os.unlink", "os.rmdir", "os.rename", "subprocess", "qsub", "qdel"):
            self.assertNotIn(forbidden, source)
        package = SKILL_PACKAGE.package_files_with_supplements(ROOT, "auto-g16-rtwin-pbs")
        self.assertEqual(
            package[Path("scripts/direct_root_fixed_mutation_helper.py")],
            SCRIPTS / "direct_root_fixed_mutation_helper.py",
        )
        self.assertEqual(
            package[Path("scripts/direct_root_fixed_mutation_consumer.py")],
            SCRIPTS / "direct_root_fixed_mutation_consumer.py",
        )
        legacy = (SCRIPTS / "legacy_root_authority_contract.py").read_text(encoding="utf-8")
        self.assertIn('FIXED_REMOTE_ROOT = "/home/user100/SDL"', legacy)


if __name__ == "__main__":
    unittest.main()
