from __future__ import annotations

import base64
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import auto_g16.transport as transport
from auto_g16.transport._bridge import (
    _SERVER_AGENT_BYTES,
    _outer_command,
    _validate_request,
)
from auto_g16.transport._driver import (
    _Invocation,
    _Operation,
    _SubprocessRTWinDriver,
    _operation,
)

from ._fixtures import TransportFixture


class _PipeProcess:
    def __init__(
        self,
        command: tuple[str, ...],
        *,
        stdout: object,
        stderr: object,
        stdin: object,
        stdout_bytes: bytes = b"",
        stderr_bytes: bytes = b"",
        binary_bytes: bytes = b"",
        returncode: int = 0,
        **kwargs: object,
    ) -> None:
        self.command = command
        self.kwargs = kwargs
        self.pid = 999_999_998
        self.returncode = returncode
        stdout_read, stdout_write = os.pipe()
        stderr_read, stderr_write = os.pipe()
        os.write(stdout_write, stdout_bytes)
        os.write(stderr_write, stderr_bytes)
        os.close(stdout_write)
        os.close(stderr_write)
        self.stdout = os.fdopen(stdout_read, "rb", buffering=0)
        self.stderr = os.fdopen(stderr_read, "rb", buffering=0)
        self._stdin_read = -1
        if stdin == __import__("subprocess").PIPE:
            self._stdin_read, stdin_write = os.pipe()
            self.stdin = os.fdopen(stdin_write, "wb", buffering=0)
        else:
            self.stdin = None
        if "--result-fd" in command:
            index = command.index("--result-fd")
            child_result = os.dup(int(command[index + 1]))
            os.write(child_result, binary_bytes)
            os.close(child_result)

    def wait(self, timeout: float | None = None) -> int:
        return self.returncode

    def kill(self) -> None:
        self.returncode = -9


class BoundedDriverTests(TransportFixture):
    def _invocation(self, operation: _Operation) -> _Invocation:
        return _Invocation(
            operation=operation,
            argv=("-f", "123.server"),
            cwd="/home/user100/SDL/project-1/attempt-1",
        )

    def test_stream_cap_is_enforced_while_reading_and_kills_group(self) -> None:
        snapshot, _profile = self.transport_snapshot()
        operation = _Operation(
            name="qstat",
            token="qstat",
            timeout_seconds=30,
            stdout_cap=3,
            stderr_cap=3,
        )
        created: list[_PipeProcess] = []

        def factory(command: tuple[str, ...], **kwargs: object) -> _PipeProcess:
            process = _PipeProcess(command, stdout_bytes=b"four", **kwargs)
            created.append(process)
            return process

        with patch("subprocess.Popen", side_effect=factory), patch.object(
            _SubprocessRTWinDriver,
            "_kill",
            side_effect=lambda process: process.kill(),
        ):
            result = _SubprocessRTWinDriver().invoke_text(
                snapshot, self._invocation(operation)
            )
        self.assertEqual(result.completion_status, "transport-error")
        self.assertEqual(result.stdout, b"")
        self.assertEqual(created[0].returncode, -9)

    def test_fetch_uses_dedicated_bounded_result_fd_and_never_stdout(self) -> None:
        snapshot, _profile = self.transport_snapshot()
        content = b"Normal termination\n"
        digest = sha256(content).hexdigest()
        frame = (
            f"AUTO-G16-FETCH/1\nidentity=1:2:33152:3\nsize={len(content)}\n"
            f"sha256={digest}\n\n"
        ).encode("ascii") + content
        invocation = _Invocation(
            operation=_operation("fetch"),
            argv=("input.log",),
            cwd=snapshot.workspace_binding.remote_attempt_dir,
        )
        created: list[_PipeProcess] = []

        def factory(command: tuple[str, ...], **kwargs: object) -> _PipeProcess:
            process = _PipeProcess(command, binary_bytes=frame, **kwargs)
            created.append(process)
            return process

        with patch("subprocess.Popen", side_effect=factory):
            result = _SubprocessRTWinDriver().invoke_fetch(snapshot, invocation)
        self.assertEqual(result.status, "found")
        self.assertEqual(result.content, content)
        self.assertIn("--result-fd", created[0].command)
        self.assertEqual(invocation.operation.stdout_cap, 0)

        with patch(
            "subprocess.Popen",
            side_effect=lambda command, **kwargs: _PipeProcess(
                command, stdout_bytes=b"x", binary_bytes=frame, **kwargs
            ),
        ), patch.object(
            _SubprocessRTWinDriver,
            "_kill",
            side_effect=lambda process: process.kill(),
        ):
            rejected = _SubprocessRTWinDriver().invoke_fetch(snapshot, invocation)
        self.assertEqual(rejected.status, "transport-error")


class SourceControlledBridgeTests(TransportFixture):
    def _packet(self) -> dict[str, object]:
        snapshot, _profile = self.transport_snapshot()
        invocation = _Invocation(
            operation=_operation("qstat"),
            argv=("-f", "123.server"),
            cwd=snapshot.workspace_binding.remote_attempt_dir,
        )
        command = _SubprocessRTWinDriver()._command(snapshot, invocation)
        return json.loads(command[2])

    def test_bridge_protocol_is_closed_and_builds_one_fixed_rtwin_hop(self) -> None:
        packet = self._packet()
        self.assertIs(_validate_request(packet), packet)
        command = _outer_command(packet)
        self.assertEqual(command[0], packet["platform_paths"]["mac_ssh_executable"])
        self.assertIn("powershell.exe", command)
        self.assertNotIn("shell", command)
        changed = dict(packet)
        changed["operation"] = "qdel"
        with self.assertRaises(ValueError):
            _validate_request(changed)
        changed = json.loads(json.dumps(packet))
        changed["runtime_identities"]["rtwin-pbs-v1"]["sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            _validate_request(changed)

    def _agent_namespace(self) -> dict[str, object]:
        namespace: dict[str, object] = {"__name__": "transport_agent_test"}
        exec(_SERVER_AGENT_BYTES, namespace)
        return namespace

    @staticmethod
    def _agent_packet(root: Path, operation: str, argv: list[str]) -> str:
        executables = {}
        for name in ("server-python", "server-qsub", "server-qstat"):
            path = root / name
            if not path.exists():
                path.write_bytes((name + " bytes").encode("ascii"))
                path.chmod(0o700)
            content = path.read_bytes()
            executables[name] = {
                "path": str(path),
                "identity": {
                    "sha256": sha256(content).hexdigest(),
                    "size_bytes": len(content),
                },
            }
        packet = {
            "schema": "auto-g16-rtwin-server-agent/1",
            "operation": operation,
            "argv": argv,
            "remote_root": str(root),
            "cwd": str(root / "project-1" / "attempt-1"),
            "server_python_executable": executables["server-python"]["path"],
            "server_qsub_executable": executables["server-qsub"]["path"],
            "server_qstat_executable": executables["server-qstat"]["path"],
            "runtime_identities": {
                name: executables[name]["identity"]
                for name in ("server-python", "server-qsub", "server-qstat")
            },
        }
        return base64.urlsafe_b64encode(
            json.dumps(packet, sort_keys=True, separators=(",", ":")).encode()
        ).decode("ascii")

    def _run_agent(
        self,
        namespace: dict[str, object],
        encoded: str,
        *,
        stdin_bytes: bytes = b"",
    ) -> tuple[bytes, bytes]:
        input_file = tempfile.TemporaryFile(mode="w+b")
        output_file = tempfile.TemporaryFile(mode="w+b")
        error_file = tempfile.TemporaryFile(mode="w+b")
        input_file.write(stdin_bytes)
        input_file.seek(0)
        fake_sys = SimpleNamespace(
            argv=["agent", encoded],
            executable=json.loads(
                base64.urlsafe_b64decode(encoded.encode("ascii")).decode("utf-8")
            )["server_python_executable"],
            stdin=input_file,
            stdout=SimpleNamespace(buffer=output_file),
            stderr=SimpleNamespace(buffer=error_file),
        )
        original = namespace["sys"]
        namespace["sys"] = fake_sys
        try:
            namespace["main"]()
        finally:
            namespace["sys"] = original
        output_file.seek(0)
        error_file.seek(0)
        return output_file.read(), error_file.read()

    def test_agent_allocate_stage_and_stable_fetch_are_no_follow(self) -> None:
        namespace = self._agent_namespace()
        root = self.temporary / "remote-root"
        root.mkdir()
        (root / "project-1").mkdir()
        allocate = self._agent_packet(root, "mkdir-attempt", [])
        self._run_agent(namespace, allocate)
        attempt = root / "project-1" / "attempt-1"
        self.assertTrue(attempt.is_dir())
        with self.assertRaises(SystemExit) as exists:
            self._run_agent(namespace, allocate)
        self.assertEqual(exists.exception.code, 17)

        content = b"Normal termination\n"
        stage = self._agent_packet(
            root,
            "stage-exact-bytes",
            ["input.log", sha256(content).hexdigest(), str(len(content))],
        )
        self._run_agent(namespace, stage, stdin_bytes=content)
        self.assertEqual((attempt / "input.log").read_bytes(), content)

        fetch = self._agent_packet(root, "fetch-exact-bytes", ["input.log"])
        output, error = self._run_agent(namespace, fetch)
        self.assertEqual(error, b"")
        self.assertTrue(output.startswith(b"AUTO-G16-FETCH/1\nidentity="))
        self.assertTrue(output.endswith(content))

    def test_agent_rejects_parent_symlink_and_fetch_replacement(self) -> None:
        namespace = self._agent_namespace()
        root = self.temporary / "remote-root"
        escape = self.temporary / "escape"
        root.mkdir()
        escape.mkdir()
        (root / "project-1").symlink_to(escape, target_is_directory=True)
        allocate = self._agent_packet(root, "mkdir-attempt", [])
        with self.assertRaises(OSError):
            self._run_agent(namespace, allocate)
        self.assertFalse((escape / "attempt-1").exists())

        (root / "project-1").unlink()
        (root / "project-1").mkdir()
        self._run_agent(namespace, allocate)
        attempt = root / "project-1" / "attempt-1"
        source = attempt / "input.log"
        source.write_bytes(b"safe")
        outside = escape / "outside.log"
        outside.write_bytes(b"outside")
        original = namespace["read_exact"]
        calls = 0

        def replacing_read(fd: int, size: int) -> bytes:
            nonlocal calls
            value = original(fd, size)
            calls += 1
            if calls == 2:
                source.unlink()
                source.symlink_to(outside)
            return value

        namespace["read_exact"] = replacing_read
        fetch = self._agent_packet(root, "fetch-exact-bytes", ["input.log"])
        with self.assertRaises(SystemExit):
            self._run_agent(namespace, fetch)
        self.assertEqual(outside.read_bytes(), b"outside")


if __name__ == "__main__":
    unittest.main()
