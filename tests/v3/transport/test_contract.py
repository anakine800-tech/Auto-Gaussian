from __future__ import annotations

from dataclasses import fields, is_dataclass
import ast
from hashlib import sha256
import inspect
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import auto_g16.transport as transport
from auto_g16.transport._driver import (
    _Invocation,
    _OPERATION_TABLE_BYTES,
    _OPERATION_TABLE_SHA256,
    _SubprocessRTWinDriver,
    _operation,
)

from ._fixtures import TransportFixture


class TransportContractTests(unittest.TestCase):
    def test_public_inventory_is_exact(self) -> None:
        self.assertEqual(
            tuple(transport.__all__),
            (
                "TransportBoundaryError",
                "ExactRemoteJobBinding",
                "SchedulerReadEvidence",
                "ExactArtifactRequest",
                "FetchedArtifact",
                "FetchedOutputCapture",
                "RTWinExecutionAdapter",
                "RTWinReadAdapter",
            ),
        )
        self.assertTrue(issubclass(transport.TransportBoundaryError, ValueError))

    def test_public_record_fields_and_signatures_are_frozen(self) -> None:
        expected_fields = {
            transport.ExactRemoteJobBinding: (
                "attempt_id",
                "execution_snapshot_id",
                "submission_intent_id",
                "remote_effect_receipt_id",
                "remote_workspace",
                "job_id",
            ),
            transport.SchedulerReadEvidence: (
                "binding",
                "source_identity",
                "observed_at_utc",
                "freshness",
                "state",
                "evidence_sha256",
                "evidence_size_bytes",
                "schema_version",
                "source_kind",
                "progress_position",
            ),
            transport.ExactArtifactRequest: (
                "artifact_kind",
                "logical_name",
                "remote_relative_name",
                "required",
            ),
            transport.FetchedArtifact: ("request", "content", "sha256", "size_bytes"),
            transport.FetchedOutputCapture: (
                "binding",
                "input_binding_observation_id",
                "capture_source_id",
                "capture_sequence",
                "capture_status",
                "capture_completeness",
                "requests",
                "artifacts",
                "missing_requests",
                "capture_manifest_sha256",
                "captured_at_utc",
                "schema_version",
            ),
        }
        for record, names in expected_fields.items():
            with self.subTest(record=record.__name__):
                self.assertTrue(is_dataclass(record))
                self.assertEqual(tuple(item.name for item in fields(record)), names)
                self.assertTrue(record.__dataclass_params__.frozen)
                self.assertTrue(hasattr(record, "__slots__"))
        self.assertEqual(
            tuple(inspect.signature(transport.ExactRemoteJobBinding.from_persisted_receipt).parameters),
            ("snapshot", "journal", "remote_effect_receipt_id", "current_profile"),
        )
        self.assertEqual(
            tuple(inspect.signature(transport.RTWinReadAdapter.read_scheduler).parameters),
            ("self", "snapshot", "binding", "current_profile"),
        )
        self.assertEqual(
            tuple(inspect.signature(transport.RTWinReadAdapter.fetch_exact_output).parameters),
            (
                "self",
                "snapshot",
                "binding",
                "current_profile",
                "input_binding_observation_id",
                "requests",
                "capture_sequence",
            ),
        )

    def test_operation_table_matches_frozen_vector(self) -> None:
        self.assertEqual(len(_OPERATION_TABLE_BYTES), 1040)
        self.assertEqual(sha256(_OPERATION_TABLE_BYTES).hexdigest(), _OPERATION_TABLE_SHA256)
        self.assertEqual(
            _OPERATION_TABLE_SHA256,
            "3502638017454526cdbfee01de47a543a9870c9c57697e4373732cb7909a71d1",
        )

    def test_public_adapter_construction_is_non_effectful(self) -> None:
        with patch("subprocess.Popen") as popen:
            execution = transport.RTWinExecutionAdapter()
            reading = transport.RTWinReadAdapter()
        popen.assert_not_called()
        self.assertEqual(execution.contract_version, "rtwin-pbs-v1")
        self.assertIsInstance(reading, transport.RTWinReadAdapter)
        self.assertEqual(tuple(inspect.signature(transport.RTWinExecutionAdapter).parameters), ())
        self.assertEqual(tuple(inspect.signature(transport.RTWinReadAdapter).parameters), ())

    def test_transport_has_no_upstream_or_legacy_authority_import(self) -> None:
        package = Path(transport.__file__).resolve().parent
        forbidden = {
            "auto_g16.approval",
            "auto_g16.core",
            "auto_g16.observe",
            "auto_g16.result",
            "auto_g16.review",
            "auto_g16.scientific_validation",
            "auto_g16.workflow",
            "legacy_rtwin_pbs",
        }
        for path in package.glob("*.py"):
            imports: set[str] = set()
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports.update(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imports.add(node.module)
            with self.subTest(path=path.name):
                self.assertTrue(imports.isdisjoint(forbidden))


class _CompletedFakeProcess:
    def __init__(self, *args: object, stdout: object, stderr: object, stdin: object, **kwargs: object) -> None:
        self.args = args
        self.kwargs = kwargs
        self.pid = 999_999_999
        stdout_read, stdout_write = os.pipe()
        stderr_read, stderr_write = os.pipe()
        os.close(stdout_write)
        os.close(stderr_write)
        self.stdout = os.fdopen(stdout_read, "rb", buffering=0)
        self.stderr = os.fdopen(stderr_read, "rb", buffering=0)
        self.stdin = None
        self.returncode = 0
        self.executed_bytes = b""
        executable = kwargs.get("executable")
        if isinstance(executable, str) and executable.startswith("/dev/fd/"):
            descriptor = int(executable.rsplit("/", 1)[1])
            position = os.lseek(descriptor, 0, os.SEEK_CUR)
            os.lseek(descriptor, 0, os.SEEK_SET)
            self.executed_bytes = os.read(descriptor, 1_000_000)
            os.lseek(descriptor, position, os.SEEK_SET)

    def wait(self, timeout: float | None = None) -> int:
        return self.returncode

    def kill(self) -> None:
        self.returncode = -9


class DescriptorReplayTests(TransportFixture):
    def test_bridge_exec_uses_attested_no_follow_descriptor(self) -> None:
        from auto_g16.transport._bridge import _BRIDGE_LAUNCHER_BYTES

        snapshot, _profile = self.transport_snapshot()
        invocation = _Invocation(
            operation=_operation("qstat"),
            argv=("-f", "123.server"),
            cwd=snapshot.workspace_binding.remote_attempt_dir,
        )
        created: list[_CompletedFakeProcess] = []

        def factory(*args: object, **kwargs: object) -> _CompletedFakeProcess:
            process = _CompletedFakeProcess(*args, **kwargs)
            created.append(process)
            return process

        with patch("subprocess.Popen", side_effect=factory) as popen:
            _SubprocessRTWinDriver().invoke_text(snapshot, invocation)
        executable = popen.call_args.kwargs["executable"]
        descriptors = popen.call_args.kwargs["pass_fds"]
        self.assertRegex(executable, r"^/dev/fd/[0-9]+$")
        self.assertEqual(len(descriptors), 1)
        self.assertFalse(popen.call_args.kwargs["shell"])
        self.assertEqual(created[0].executed_bytes, _BRIDGE_LAUNCHER_BYTES)

    def test_in_place_bridge_mutation_cannot_change_executed_bytes(self) -> None:
        from auto_g16.transport._bridge import _BRIDGE_LAUNCHER_BYTES

        snapshot, _profile = self.transport_snapshot()
        bridge = Path(snapshot.resolved_server_profile.platform_paths["rtwin_bridge_executable"])
        invocation = _Invocation(
            operation=_operation("qstat"),
            argv=("-f", "123.server"),
            cwd=snapshot.workspace_binding.remote_attempt_dir,
        )
        created: list[_CompletedFakeProcess] = []

        def factory(*args: object, **kwargs: object) -> _CompletedFakeProcess:
            bridge.write_bytes(b"X" * len(_BRIDGE_LAUNCHER_BYTES))
            process = _CompletedFakeProcess(*args, **kwargs)
            created.append(process)
            return process

        with patch("subprocess.Popen", side_effect=factory):
            _SubprocessRTWinDriver().invoke_text(snapshot, invocation)
        self.assertEqual(created[0].executed_bytes, _BRIDGE_LAUNCHER_BYTES)
        self.assertNotEqual(bridge.read_bytes(), _BRIDGE_LAUNCHER_BYTES)

    def test_terminal_bridge_symlink_rejects_before_subprocess(self) -> None:
        profile = self.profile()
        target = self.temporary / "real-bridge"
        target.write_bytes(profile.runtime_contents["rtwin-bridge"])
        alias = self.temporary / "bridge-alias"
        alias.symlink_to(target)
        profile.platform_paths["rtwin_bridge_executable"] = str(alias)
        snapshot, _profile = self.transport_snapshot(profile=profile)
        invocation = _Invocation(
            operation=_operation("qstat"),
            argv=("-f", "123.server"),
            cwd=snapshot.workspace_binding.remote_attempt_dir,
        )
        with patch("subprocess.Popen") as popen, self.assertRaises(
            transport.TransportBoundaryError
        ):
            _SubprocessRTWinDriver().invoke_text(snapshot, invocation)
        popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
