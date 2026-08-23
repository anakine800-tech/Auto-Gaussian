from __future__ import annotations

from dataclasses import replace
import os
import unittest
from unittest.mock import patch

import auto_g16.transport as transport
from auto_g16.transport._bridge import _build_rtwin_command
from auto_g16.transport._driver import (
    _MANIFEST_NAME,
    _SubprocessRTWinDriver,
    _attest_local,
    _operation,
    _parse_deployment_manifest,
    _resolve_deployment_authority,
)

from ._fixtures import TransportFixture


class ManifestAndCommandTests(TransportFixture):
    def test_manifest_closes_exact_nine_roots(self) -> None:
        profile = self.profile()
        manifest = _parse_deployment_manifest(profile.runtime_contents[_MANIFEST_NAME])
        self.assertEqual(set(manifest.trust_roots), {
            "mac_ssh", "mac_scp", "rtwin_ssh", "rtwin_scp", "rtwin_remote_shell",
            "server_remote_shell", "server_python", "server_qsub", "server_qstat",
        })
        self.assertEqual(manifest.bootstrap_protocol, "auto-g16-v3-rtwin-bootstrap/1")
        self.assertEqual(manifest.trust_roots["rtwin_remote_shell"].shell_grammar, "powershell-v1")

    def test_noncanonical_manifest_and_root_inventory_reject(self) -> None:
        profile = self.profile()
        raw = profile.runtime_contents[_MANIFEST_NAME]
        with self.assertRaises(transport.TransportBoundaryError):
            _parse_deployment_manifest(b" " + raw)
        with self.assertRaises(transport.TransportBoundaryError):
            _parse_deployment_manifest(raw.replace(b'"mac_scp":', b'"extra":'))

    def test_current_profile_and_runtime_drift_reject(self) -> None:
        profile = self.profile()
        snapshot, _ = self.transport_snapshot(profile=profile)
        _resolve_deployment_authority(snapshot, profile)
        drifted = self.profile(deployment_id="different-deployment")
        with self.assertRaises(transport.TransportBoundaryError):
            _resolve_deployment_authority(snapshot, drifted)
        object.__setattr__(snapshot.resolved_resource_request, "cores", 99)
        with self.assertRaises(transport.TransportBoundaryError):
            _resolve_deployment_authority(snapshot, profile)

    def test_local_executable_attestation_rejects_symlink_and_mutation(self) -> None:
        profile = self.profile()
        manifest = _parse_deployment_manifest(profile.runtime_contents[_MANIFEST_NAME])
        root = manifest.trust_roots["mac_ssh"]
        _attest_local(root)
        os.chmod(root.path, 0o600)
        with self.assertRaises(transport.TransportBoundaryError):
            _attest_local(root)
        os.chmod(root.path, 0o700)
        with open(root.path, "ab") as stream:
            stream.write(b"drift")
        with self.assertRaises(transport.TransportBoundaryError):
            _attest_local(root)

    def test_powershell_command_uses_fixed_paths_and_no_dynamic_operation(self) -> None:
        profile = self.profile()
        snapshot, _ = self.transport_snapshot(profile=profile)
        authority = _resolve_deployment_authority(snapshot, profile)
        command = _build_rtwin_command(snapshot, authority.manifest)
        self.assertEqual(command[0], authority.manifest.trust_roots["mac_ssh"].path)
        self.assertIn("UseShellExecute=$false", command[-1])
        self.assertIn("Get-FileHash", command[-1])
        self.assertNotIn("qsub", command[:-1])

    def test_cmd_manifest_fails_before_any_process(self) -> None:
        profile = self.profile(windows_grammar="cmd-v1")
        snapshot, _ = self.transport_snapshot(profile=profile)
        authority = _resolve_deployment_authority(snapshot, profile)
        with patch("subprocess.Popen") as popen, self.assertRaises(transport.TransportBoundaryError):
            _build_rtwin_command(snapshot, authority.manifest)
        popen.assert_not_called()


class DriverBoundaryTests(TransportFixture):
    def test_stream_cap_is_enforced_during_read(self) -> None:
        class Process:
            def __init__(self) -> None:
                stdin_read, stdin_write = os.pipe()
                stdout_read, stdout_write = os.pipe()
                stderr_read, stderr_write = os.pipe()
                self._stdin_read = stdin_read
                self.stdin = os.fdopen(stdin_write, "wb", buffering=0)
                self.stdout = os.fdopen(stdout_read, "rb", buffering=0)
                self.stderr = os.fdopen(stderr_read, "rb", buffering=0)
                os.write(stdout_write, b"x" * 32)
                os.close(stdout_write)
                os.close(stderr_write)
                self.pid = 999_999_999
                self.returncode = 0
                self.killed = False
            def wait(self, timeout=None):
                return self.returncode
            def kill(self) -> None:
                self.killed = True
            def close(self) -> None:
                os.close(self._stdin_read)

        process = Process()
        operation = replace(_operation("ALLOCATE_WORKSPACE"), stdout_cap=8)
        result = _SubprocessRTWinDriver()._communicate_bounded(process, b"request", operation)
        process.close()
        self.assertEqual(result[3], "transport-error")
        self.assertTrue(process.killed)

    def test_unknown_operation_is_closed(self) -> None:
        with self.assertRaises(transport.TransportBoundaryError):
            _operation("DELETE_WORKSPACE")

    def test_preflight_drift_returns_zero_process_call(self) -> None:
        profile = self.profile()
        snapshot, _ = self.transport_snapshot(profile=profile)
        authority = _resolve_deployment_authority(snapshot, profile)
        root = authority.manifest.trust_roots["mac_ssh"]
        os.chmod(root.path, 0o600)
        invocation = type("Invocation", (), {
            "operation": _operation("ALLOCATE_WORKSPACE"),
            "request": {"binding": {}, "operation": "ALLOCATE_WORKSPACE", "payload": {}, "protocol": "auto-g16-v3-rtwin-bootstrap/1"},
            "authority": authority,
        })()
        with patch("subprocess.Popen") as popen, self.assertRaises(transport.TransportBoundaryError):
            _SubprocessRTWinDriver().invoke_text(snapshot, invocation)
        popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
