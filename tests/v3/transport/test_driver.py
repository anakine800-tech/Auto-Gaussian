from __future__ import annotations

from dataclasses import replace
import base64
from hashlib import sha256
import json
import os
import unittest
from unittest.mock import patch

import auto_g16.transport as transport
from auto_g16.transport._bridge import _build_rtwin_command
from auto_g16.transport._canonical import canonical_json_bytes
from auto_g16.transport._driver import (
    _MANIFEST_NAME,
    _RESOURCE_DESCRIPTOR_NAME,
    _Invocation,
    _SubprocessRTWinDriver,
    _attest_local,
    _operation,
    _parse_deployment_manifest,
    _parse_resource_descriptor,
    _render_qsub_argv,
    _resolve_deployment_authority,
    _resource_enactment,
)

from ._fixtures import RESOURCE_DESCRIPTOR_BYTES, TORQUE_RESOURCE_DESCRIPTOR_BYTES, TransportFixture


class ManifestAndCommandTests(TransportFixture):
    def test_manifest_closes_exact_nine_roots(self) -> None:
        profile = self.profile()
        manifest = _parse_deployment_manifest(profile.runtime_contents[_MANIFEST_NAME])
        self.assertEqual(set(manifest.trust_roots), {
            "mac_ssh", "mac_scp", "rtwin_ssh", "rtwin_scp", "rtwin_remote_shell",
            "server_remote_shell", "server_python", "server_qsub", "server_qstat",
        })
        self.assertEqual(manifest.bootstrap_protocol, "auto-g16-v3-rtwin-bootstrap/2")
        self.assertEqual(manifest.trust_roots["rtwin_remote_shell"].shell_grammar, "powershell-v1")

    def test_production_qsub_qstat_manifest_evidence_is_exact(self) -> None:
        profile = self.profile()
        value = json.loads(profile.runtime_contents[_MANIFEST_NAME])
        qsub = value["trust_roots"]["server_qsub"]
        qsub.update(path="/usr/local/bin/qsub", expected_size_bytes=418_920, expected_sha256="f950e7d15287ca125e76ad81e115019e903227e5816b9a21c19967945e292c6d", deployment_identity="torque-6.1.0-qsub-preflight")
        qstat = value["trust_roots"]["server_qstat"]
        qstat.update(path="/usr/local/bin/qstat", expected_size_bytes=185_656, expected_sha256="3ecac5943864adef1a4d0b9aa235861a5fa573d8c3c7fd2b615694148ba5f85a", deployment_identity="torque-6.1.0-qstat-preflight")
        manifest = _parse_deployment_manifest(canonical_json_bytes(value))
        self.assertEqual((manifest.trust_roots["server_qsub"].path, manifest.trust_roots["server_qsub"].expected_size_bytes, manifest.trust_roots["server_qsub"].expected_sha256), ("/usr/local/bin/qsub", 418_920, "f950e7d15287ca125e76ad81e115019e903227e5816b9a21c19967945e292c6d"))
        self.assertEqual((manifest.trust_roots["server_qstat"].path, manifest.trust_roots["server_qstat"].expected_size_bytes, manifest.trust_roots["server_qstat"].expected_sha256), ("/usr/local/bin/qstat", 185_656, "3ecac5943864adef1a4d0b9aa235861a5fa573d8c3c7fd2b615694148ba5f85a"))

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

    def test_resource_descriptor_and_exact_synthetic_argv_are_closed(self) -> None:
        profile = self.profile()
        snapshot, _ = self.transport_snapshot(profile=profile)
        dialect = _parse_resource_descriptor(RESOURCE_DESCRIPTOR_BYTES)
        self.assertFalse(dialect.live_capable)
        authority = _resolve_deployment_authority(snapshot, profile)
        enactment = _resource_enactment(snapshot, authority)
        self.assertEqual(enactment.payload(), {
            "execution_snapshot_id": snapshot.execution_snapshot_id,
            "resolved_resource_request_id": snapshot.resolved_resource_request.resolved_resource_request_id,
            "cores": 8, "memory_mb": 12_288, "walltime_seconds": 3_600,
            "queue": "simple",
            "scheduler_dialect_id": "auto-g16-v3-pbs-resource-enactment/synthetic-test/1",
        })
        self.assertEqual(_render_qsub_argv(enactment, "job.pbs"), (
            "--auto-g16-synthetic-cores", "8",
            "--auto-g16-synthetic-memory-mb", "12288",
            "--auto-g16-synthetic-walltime-seconds", "3600",
            "--auto-g16-synthetic-queue", "simple", "job.pbs",
        ))
        with self.assertRaises(transport.TransportBoundaryError):
            _parse_resource_descriptor(RESOURCE_DESCRIPTOR_BYTES.replace(b"synthetic-test", b"unknown-dial"))
        runtime_contents = dict(profile.runtime_contents)
        runtime_contents[_RESOURCE_DESCRIPTOR_NAME] = RESOURCE_DESCRIPTOR_BYTES.replace(b"synthetic-test", b"unknown-dial")
        with self.assertRaises(transport.TransportBoundaryError):
            _resolve_deployment_authority(snapshot, replace(profile, runtime_contents=runtime_contents))

    def test_torque_descriptor_and_exact_production_argv_are_closed(self) -> None:
        profile = self.profile(resource_descriptor=TORQUE_RESOURCE_DESCRIPTOR_BYTES)
        snapshot, _ = self.transport_snapshot(profile=profile, queue="batch")
        dialect = _parse_resource_descriptor(TORQUE_RESOURCE_DESCRIPTOR_BYTES)
        self.assertTrue(dialect.live_capable)
        enactment = _resource_enactment(snapshot, _resolve_deployment_authority(snapshot, profile))
        self.assertEqual(_render_qsub_argv(enactment, "job.pbs"), (
            "-l", "nodes=1:ppn=8,mem=12288mb,walltime=3600",
            "-q", "batch", "job.pbs",
        ))
        self.assertNotIn("/usr/local/bin/qsub", _render_qsub_argv(enactment, "job.pbs"))

    def test_torque_queue_is_mandatory_and_exact(self) -> None:
        for queue in (None, "simple", "batch2"):
            with self.subTest(queue=queue):
                profile = self.profile(resource_descriptor=TORQUE_RESOURCE_DESCRIPTOR_BYTES)
                snapshot, _ = self.transport_snapshot(profile=profile, queue=queue)
                enactment = _resource_enactment(snapshot, _resolve_deployment_authority(snapshot, profile))
                with self.assertRaises(transport.TransportBoundaryError):
                    _render_qsub_argv(enactment, "job.pbs")

    def test_torque_descriptor_rejects_unproved_qsub_or_qstat_identity(self) -> None:
        for root_name in ("server_qsub", "server_qstat"):
            with self.subTest(root_name=root_name):
                profile = self.profile(resource_descriptor=TORQUE_RESOURCE_DESCRIPTOR_BYTES)
                value = json.loads(profile.runtime_contents[_MANIFEST_NAME])
                value["trust_roots"][root_name]["expected_size_bytes"] += 1
                runtime_contents = dict(profile.runtime_contents)
                runtime_contents[_MANIFEST_NAME] = canonical_json_bytes(value)
                drifted = replace(profile, runtime_contents=runtime_contents)
                snapshot, _ = self.transport_snapshot(profile=drifted, queue="batch")
                with self.assertRaises(transport.TransportBoundaryError):
                    _resolve_deployment_authority(snapshot, drifted)
        runtime_contents = dict(profile.runtime_contents)
        del runtime_contents[_RESOURCE_DESCRIPTOR_NAME]
        with self.assertRaises(transport.TransportBoundaryError):
            _resolve_deployment_authority(snapshot, replace(profile, runtime_contents=runtime_contents))

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
        authority = replace(authority, resource_dialect=replace(authority.resource_dialect, live_capable=True))
        command = _build_rtwin_command(snapshot, authority.manifest)
        self.assertEqual(command[0], authority.manifest.trust_roots["mac_ssh"].path)
        self.assertIn("UseShellExecute=$false", command[-1])
        self.assertIn("Get-FileHash", command[-1])
        self.assertNotIn("qsub", command[:-1])

    def test_outer_ssh_targets_final_rtwin_hop_and_only_earlier_hops_proxy(self) -> None:
        profile = self.profile(jump_topology=[
            ("proxy.example", 2201, "proxy-user"),
            ("rtwin.example", 2202, "rtwin-user"),
        ])
        snapshot, _ = self.transport_snapshot(profile=profile)
        authority = _resolve_deployment_authority(snapshot, profile)
        command = _build_rtwin_command(snapshot, authority.manifest)
        self.assertEqual(command[:11], (
            authority.manifest.trust_roots["mac_ssh"].path,
            "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes",
            "-p", "2202", "-J", "proxy-user@proxy.example:2201",
            "--", "rtwin-user@rtwin.example",
        ))
        self.assertIn("-p 22 user100@10.0.0.50", command[-1])

    def test_empty_rtwin_hop_rejects_before_process(self) -> None:
        profile = self.profile(jump_topology=[])
        snapshot, _ = self.transport_snapshot(profile=profile)
        authority = _resolve_deployment_authority(snapshot, profile)
        with patch("subprocess.Popen") as popen, self.assertRaises(transport.TransportBoundaryError):
            _build_rtwin_command(snapshot, authority.manifest)
        popen.assert_not_called()

    def test_cmd_manifest_fails_before_any_process(self) -> None:
        profile = self.profile(windows_grammar="cmd-v1")
        snapshot, _ = self.transport_snapshot(profile=profile)
        authority = _resolve_deployment_authority(snapshot, profile)
        with patch("subprocess.Popen") as popen, self.assertRaises(transport.TransportBoundaryError):
            _build_rtwin_command(snapshot, authority.manifest)
        popen.assert_not_called()


class DriverBoundaryTests(TransportFixture):
    def test_fetch_response_must_match_exact_request_identity(self) -> None:
        profile = self.profile()
        snapshot, _ = self.transport_snapshot(profile=profile)
        authority = _resolve_deployment_authority(snapshot, profile)
        content = b"exact bytes"
        result = {
            "remote_relative_name":"input.log",
            "size_bytes":len(content),
            "sha256":sha256(content).hexdigest(),
            "content_base64":base64.b64encode(content).decode("ascii"),
            "file_physical_token_base64":"cmVzcG9uc2UtdG9rZW4=",
            "eof":True,
        }
        envelope = canonical_json_bytes({"operation":"FETCH_EXACT_FILE", "protocol":"auto-g16-v3-rtwin-bootstrap/1", "result":result, "status":"ok"})
        framed = b"AGV3" + len(envelope).to_bytes(8, "big") + envelope
        invocation = _Invocation(
            operation=_operation("FETCH_EXACT_FILE"),
            argv=("input.log",),
            cwd=snapshot.workspace_binding.remote_attempt_dir,
            request={"payload":{
                "remote_relative_name":"input.log",
                "expected_size_bytes":len(content),
                "expected_file_physical_token_base64":"cmVxdWVzdC10b2tlbg==",
            }},
            authority=authority,
        )
        driver = _SubprocessRTWinDriver()
        with patch.object(driver, "_run", return_value=(framed,b"",0,"completed",True,True)):
            self.assertEqual(driver.invoke_fetch(snapshot, invocation).status, "unstable")

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
        authority = replace(authority, resource_dialect=replace(authority.resource_dialect, live_capable=True))
        root = authority.manifest.trust_roots["mac_ssh"]
        os.chmod(root.path, 0o600)
        invocation = type("Invocation", (), {
            "operation": _operation("ALLOCATE_WORKSPACE"),
            "request": {"binding": {}, "operation": "ALLOCATE_WORKSPACE", "payload": {}, "protocol": "auto-g16-v3-rtwin-bootstrap/2"},
            "authority": authority,
        })()
        with patch("subprocess.Popen") as popen, self.assertRaises(transport.TransportBoundaryError):
            _SubprocessRTWinDriver().invoke_text(snapshot, invocation)
        popen.assert_not_called()

    def test_synthetic_resource_dialect_rejects_before_process_creation(self) -> None:
        profile = self.profile()
        snapshot, _ = self.transport_snapshot(profile=profile)
        authority = _resolve_deployment_authority(snapshot, profile)
        invocation = _Invocation(
            operation=_operation("SUBMIT_QSUB_ONCE"), argv=("synthetic",),
            cwd=snapshot.workspace_binding.remote_attempt_dir,
            request={"binding": {}, "operation": "SUBMIT_QSUB_ONCE", "payload": {}, "protocol": "auto-g16-v3-rtwin-bootstrap/2"},
            authority=authority,
        )
        with patch("subprocess.Popen") as popen:
            result = _SubprocessRTWinDriver().invoke_text(snapshot, invocation)
        popen.assert_not_called()
        self.assertEqual(result.completion_status, "transport-error")


if __name__ == "__main__":
    unittest.main()
