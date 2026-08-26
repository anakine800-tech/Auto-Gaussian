from __future__ import annotations

from dataclasses import replace
import base64
from hashlib import sha256
import json
import os
import unittest
from unittest.mock import patch

import auto_g16.transport as transport
from auto_g16.transport._bridge import (
    _BOOTSTRAP_SOURCE,
    _RTWIN_LAUNCHER_SHA256,
    _RTWIN_LAUNCHER_SIZE,
    _RTWIN_LAUNCHER_SOURCE,
    _build_rtwin_command,
    _crt_quote,
    _posix_quote_v1,
    _powershell_quote_fixed_launcher_v1,
    _render_inner_rtwin_arguments,
)
from auto_g16.transport._canonical import canonical_json_bytes
from auto_g16.transport._driver import (
    _MANIFEST_NAME,
    _RESOURCE_DESCRIPTOR_NAME,
    _Invocation,
    _ResourceEnactment,
    _SubprocessRTWinDriver,
    _TORQUE_RESOURCE_DIALECT,
    _assert_deployment_snapshot,
    _attest_local,
    _attest_local_effect_file,
    _operation,
    _parse_deployment_manifest,
    _parse_resource_descriptor,
    _render_qsub_argv,
    _resolve_deployment_authority,
    _resource_enactment,
)

from ._fixtures import RESOURCE_DESCRIPTOR_BYTES, TORQUE_RESOURCE_DESCRIPTOR_BYTES, TransportFixture


class ManifestAndCommandTests(TransportFixture):
    @staticmethod
    def _replace_config(profile,logical_name: str,content: bytes):
        return replace(profile,config_files=[(name,content if name==logical_name else raw) for name,raw in profile.config_files])

    def test_manifest_v2_closes_exact_ten_roots(self) -> None:
        profile = self.profile()
        manifest = _parse_deployment_manifest(profile.runtime_contents[_MANIFEST_NAME])
        self.assertEqual(set(manifest.trust_roots), {
            "mac_ssh", "mac_scp", "rtwin_ssh", "rtwin_scp", "rtwin_remote_shell",
            "rtwin_launcher",
            "server_remote_shell", "server_python", "server_qsub", "server_qstat",
        })
        self.assertEqual(manifest.schema, "auto-g16-v3-transport-deployment-manifest/2")
        self.assertEqual(manifest.bootstrap_protocol, "auto-g16-v3-rtwin-bootstrap/2")
        self.assertEqual(manifest.trust_roots["rtwin_remote_shell"].shell_grammar, "cmd-powershell-launcher-v1")
        launcher=manifest.trust_roots["rtwin_launcher"]
        self.assertEqual((launcher.expected_size_bytes,launcher.expected_sha256),(_RTWIN_LAUNCHER_SIZE,_RTWIN_LAUNCHER_SHA256))
        self.assertEqual((launcher.path,launcher.deployment_identity),(r"C:\AutoG16Runtime\auto-g16-v3-rtwin-launcher-v4.ps1","auto-g16-v3-rtwin-launcher-v4"))

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
        config_drift=self._replace_config(profile,"mac-ssh-config",dict(profile.config_files)["mac-ssh-config"].replace(b"Host rtwin-a\n",b"# changed bytes\nHost rtwin-a\n"))
        with self.assertRaises(transport.TransportBoundaryError):
            _resolve_deployment_authority(snapshot,config_drift)
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

    def test_torque_exact_positive_vectors_cover_minimum_typical_and_full_node(self) -> None:
        for cores, memory_mb, walltime_seconds, expected in (
            (1, 1, 1, "nodes=1:ppn=1,mem=1mb,walltime=1"),
            (22, 51_200, 43_200, "nodes=1:ppn=22,mem=51200mb,walltime=43200"),
            (44, 120_000, 172_800, "nodes=1:ppn=44,mem=120000mb,walltime=172800"),
        ):
            with self.subTest(cores=cores):
                enactment = _ResourceEnactment("snapshot-1", "resources-1", cores, memory_mb, walltime_seconds, "batch", _TORQUE_RESOURCE_DIALECT)
                self.assertEqual(_render_qsub_argv(enactment, "job.pbs"), ("-l", expected, "-q", "batch", "job.pbs"))

    def test_resource_integers_and_renderer_tokens_are_closed(self) -> None:
        for field in ("cores", "memory_mb", "walltime_seconds"):
            for bad in (0, -1, True, 1.0, "1"):
                with self.subTest(field=field, bad=bad):
                    values = {"cores": 8, "memory_mb": 12_288, "walltime_seconds": 3_600}
                    values[field] = bad
                    with self.assertRaises(transport.TransportBoundaryError):
                        _ResourceEnactment("snapshot-1", "resources-1", values["cores"], values["memory_mb"], values["walltime_seconds"], "batch", _TORQUE_RESOURCE_DIALECT)
        for basename in ("../job.pbs", "job pbs", "-job.pbs", "job.pbs;"):
            with self.subTest(basename=basename):
                enactment = _ResourceEnactment("snapshot-1", "resources-1", 8, 12_288, 3_600, "batch", _TORQUE_RESOURCE_DIALECT)
                with self.assertRaises(transport.TransportBoundaryError):
                    _render_qsub_argv(enactment, basename)

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
            for field, changed in (("path", "/opt/drifted"), ("expected_size_bytes", 1), ("expected_sha256", "0" * 64)):
                with self.subTest(root_name=root_name, field=field):
                    profile = self.profile(resource_descriptor=TORQUE_RESOURCE_DESCRIPTOR_BYTES)
                    value = json.loads(profile.runtime_contents[_MANIFEST_NAME])
                    value["trust_roots"][root_name][field] = changed
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

    def test_local_bound_config_attestation_rejects_symlink_and_byte_drift(self) -> None:
        profile=self.profile(); snapshot,_=self.transport_snapshot(profile=profile)
        bound=_resolve_deployment_authority(snapshot,profile).ssh_effect.mac_to_rtwin.config
        _attest_local_effect_file(bound)
        original=self.mac_ssh_config.read_bytes(); replacement=self.temporary/"replacement-config"
        replacement.write_bytes(original); self.mac_ssh_config.unlink(); self.mac_ssh_config.symlink_to(replacement)
        with self.assertRaises(transport.TransportBoundaryError): _attest_local_effect_file(bound)
        self.mac_ssh_config.unlink(); self.mac_ssh_config.write_bytes(original+b"# drift\n")
        with self.assertRaises(transport.TransportBoundaryError): _attest_local_effect_file(bound)

    def test_ssh_effect_config_inventory_is_exact(self) -> None:
        for mutation in (lambda values:values[:-1],lambda values:values+[("extra-config",b"x")]):
            with self.subTest(mutation=mutation):
                profile=self.profile(); changed=replace(profile,config_files=mutation(list(profile.config_files)))
                snapshot,_=self.transport_snapshot(profile=changed)
                with self.assertRaises(transport.TransportBoundaryError): _resolve_deployment_authority(snapshot,changed)

    def test_ssh_config_closed_grammar_rejects_dynamic_directives_and_expansion(self) -> None:
        profile=self.profile(); original=dict(profile.config_files)["mac-ssh-config"]
        variants=(
            original.replace(b"  User rtwin-user\n",b"  User rtwin-user\n  Include /tmp/extra\n"),
            original.replace(b"  User rtwin-user\n",b"  User rtwin-user\n  ProxyCommand arbitrary\n"),
            original.replace(b"  IdentityFile /keys/mac-rtwin\n",b"  IdentityFile ~/.ssh/id_ed25519\n"),
            original.replace(b"  IdentityFile /keys/mac-rtwin\n",b"  IdentityFile /keys/%h/id_ed25519\n"),
            original.replace(b"  IdentityFile /keys/mac-rtwin\n",b"  IdentityFile /keys/${HOME}/id_ed25519\n"),
            original.replace(b"  IdentityFile /keys/mac-rtwin\n",b"  IdentityFile //server/key\n"),
            original.replace(b"  IdentityFile /keys/mac-rtwin\n",b"  IdentityFile /keys//id_ed25519\n"),
            original.replace(b"Host rtwin-a\n",b"Host *\n"),
            original.replace(b"  IdentitiesOnly yes\n",b"  IdentitiesOnly YES\n"),
            original.replace(b"  Port 22\n",b"  Port 22\r\n"),
            original+b"\n",
        )
        for raw in variants:
            with self.subTest(raw=raw):
                changed=self._replace_config(profile,"mac-ssh-config",raw); snapshot,_=self.transport_snapshot(profile=changed)
                with self.assertRaises(transport.TransportBoundaryError): _resolve_deployment_authority(snapshot,changed)

        rtwin=dict(profile.config_files)["rtwin-ssh-config"]
        for path in (r"\\server\share\id",r"C:\Keys\id:ads",r"C:\CON\id",r"C:\Keys\\id",r"%USERPROFILE%\id"):
            with self.subTest(path=path):
                raw=rtwin.replace(b"C:\\Keys\\server",path.encode())
                changed=self._replace_config(profile,"rtwin-ssh-config",raw); snapshot,_=self.transport_snapshot(profile=changed)
                with self.assertRaises(transport.TransportBoundaryError): _resolve_deployment_authority(snapshot,changed)

    def test_ssh_config_target_and_known_hosts_path_must_match_profile(self) -> None:
        profile=self.profile(); original=dict(profile.config_files)["mac-ssh-config"]
        for raw in (
            original.replace(b"HostName 100.64.0.1",b"HostName 100.64.0.2"),
            original.replace(str(self.mac_known_hosts).encode(),b"/tmp/other-known-hosts"),
        ):
            with self.subTest(raw=raw):
                changed=self._replace_config(profile,"mac-ssh-config",raw); snapshot,_=self.transport_snapshot(profile=changed)
                with self.assertRaises(transport.TransportBoundaryError): _resolve_deployment_authority(snapshot,changed)

    def test_cmd_boundary_uses_explicit_powershell_and_attested_launcher(self) -> None:
        profile = self.profile()
        snapshot, _ = self.transport_snapshot(profile=profile)
        authority = _resolve_deployment_authority(snapshot, profile)
        authority = replace(authority, resource_dialect=replace(authority.resource_dialect, live_capable=True))
        command = _build_rtwin_command(snapshot, authority)
        self.assertEqual(command[0], authority.manifest.trust_roots["mac_ssh"].path)
        remote=command[-1]
        self.assertTrue(remote.startswith('"C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe" -NoProfile -NonInteractive -Command "'))
        self.assertIn("[ScriptBlock]::Create($s)",remote)
        self.assertIn(_RTWIN_LAUNCHER_SHA256,remote)
        self.assertEqual(remote.count(r"C:\Config\server-ssh-config"),1)
        self.assertEqual(remote.count(r"C:\Config\server-known"),1)
        self.assertLess(len(remote),4096)
        self.assertNotIn(_BOOTSTRAP_SOURCE,remote)
        self.assertNotIn(authority.manifest.raw_bytes.decode(),remote)
        self.assertNotIn("UseShellExecute=$false",remote)
        self.assertIn("UseShellExecute=$false",_RTWIN_LAUNCHER_SOURCE)
        self.assertIn("System.Diagnostics.Process",_RTWIN_LAUNCHER_SOURCE)
        inner=_render_inner_rtwin_arguments(authority,authority.ssh_effect.rtwin_to_server.target)
        self.assertLess(len(inner),30000)
        self.assertIn(f"-ExpectedInnerLength {len(inner)}",remote)
        self.assertIn(f"-ExpectedInnerSha256 '{sha256(inner.encode('utf-8')).hexdigest()}'",remote)
        self.assertIn("$ArgumentLine.Length-ne$ExpectedInnerLength",_RTWIN_LAUNCHER_SOURCE)
        self.assertIn("$InnerDigest-ne$ExpectedInnerSha256",_RTWIN_LAUNCHER_SOURCE)
        self.assertNotIn("qsub", command[:-1])

    def test_outer_and_inner_ssh_use_exact_bound_aliases_and_closed_options(self) -> None:
        profile = self.profile()
        snapshot, _ = self.transport_snapshot(profile=profile)
        authority = _resolve_deployment_authority(snapshot, profile)
        command = _build_rtwin_command(snapshot, authority)
        expected=[authority.manifest.trust_roots["mac_ssh"].path,"-F",str(self.mac_ssh_config)]
        for option in (
            "BatchMode=yes","IdentitiesOnly=yes","StrictHostKeyChecking=yes",
            f"UserKnownHostsFile={self.mac_known_hosts}",f"GlobalKnownHostsFile={self.mac_known_hosts}",
            "IdentityAgent=none","PreferredAuthentications=publickey","PubkeyAuthentication=yes",
            "PasswordAuthentication=no","KbdInteractiveAuthentication=no","GSSAPIAuthentication=no",
            "HostbasedAuthentication=no","VerifyHostKeyDNS=no","UpdateHostKeys=no",
        ): expected.extend(("-o",option))
        expected.extend(("-p","22","-l","rtwin-user","--","rtwin-a"))
        self.assertEqual(command[:-1],tuple(expected))
        self.assertNotIn("-J",command)
        launcher=_RTWIN_LAUNCHER_SOURCE
        for option in (
            "BatchMode=yes","IdentitiesOnly=yes","StrictHostKeyChecking=yes",
            "IdentityAgent=none","PreferredAuthentications=publickey","PubkeyAuthentication=yes",
            "PasswordAuthentication=no","KbdInteractiveAuthentication=no","GSSAPIAuthentication=no",
            "HostbasedAuthentication=no","VerifyHostKeyDNS=no","UpdateHostKeys=no",
        ):
            self.assertIn(option,launcher)
        self.assertIn("UserKnownHostsFile=",launcher)
        self.assertIn("GlobalKnownHostsFile=",launcher)
        self.assertIn("$KnownHostsPath",launcher)
        self.assertIn("$Process.StartInfo.FileName=$RtwinSsh.path",launcher)
        self.assertIn("$Process.StartInfo.Arguments=$ArgumentLine",launcher)
        self.assertIn("if($ArgumentLine.Length-ge 30000)",launcher)
        self.assertIn("$ServerAlias,$ServerCommand",launcher)
        self.assertNotIn("user100@10.0.0.50",launcher)

    def test_cross_snapshot_profile_and_source_authority_splices_reject_before_process(self) -> None:
        profile=self.profile(resource_descriptor=TORQUE_RESOURCE_DESCRIPTOR_BYTES); snapshot,_=self.transport_snapshot(profile=profile,queue="batch")
        authority=_resolve_deployment_authority(snapshot,profile)
        variants=(
            replace(authority,execution_snapshot_id="different-snapshot"),
            replace(authority,resolved_server_profile_id="different-profile"),
            replace(authority,effective_config_sha256="0"*64),
            replace(authority,bootstrap_source_sha256="0"*64),
        )
        for changed in variants:
            with self.subTest(changed=changed):
                with self.assertRaises(transport.TransportBoundaryError): _assert_deployment_snapshot(snapshot,changed)
                with self.assertRaises(transport.TransportBoundaryError): _build_rtwin_command(snapshot,changed)

    def test_extra_rtwin_hop_rejects_before_process(self) -> None:
        profile=self.profile(jump_topology=[("proxy.example",2201,"proxy-user"),("100.64.0.1",22,"rtwin-user")])
        snapshot,_=self.transport_snapshot(profile=profile)
        with patch("subprocess.Popen") as popen,self.assertRaises(transport.TransportBoundaryError):
            _resolve_deployment_authority(snapshot,profile)
        popen.assert_not_called()

    def test_empty_rtwin_hop_rejects_before_process(self) -> None:
        profile = self.profile(jump_topology=[])
        snapshot, _ = self.transport_snapshot(profile=profile)
        with patch("subprocess.Popen") as popen, self.assertRaises(transport.TransportBoundaryError):
            _resolve_deployment_authority(snapshot, profile)
        popen.assert_not_called()

    def test_legacy_shell_grammar_and_manifest_v1_fail_before_any_process(self) -> None:
        profile = self.profile(windows_grammar="cmd-v1")
        snapshot, _ = self.transport_snapshot(profile=profile)
        with patch("subprocess.Popen") as popen, self.assertRaises(transport.TransportBoundaryError):
            _resolve_deployment_authority(snapshot, profile)
        popen.assert_not_called()
        profile=self.profile(); value=json.loads(profile.runtime_contents[_MANIFEST_NAME]); value["schema"]="auto-g16-v3-transport-deployment-manifest/1"; del value["trust_roots"]["rtwin_launcher"]
        with self.assertRaises(transport.TransportBoundaryError): _parse_deployment_manifest(canonical_json_bytes(value))

    def test_runtime_data_paths_and_launcher_identity_are_closed(self) -> None:
        profile=self.profile()
        for path_key in ("rtwin_bootstrap_source_path","rtwin_deployment_manifest_path"):
            paths=dict(profile.platform_paths); del paths[path_key]
            changed=replace(profile,platform_paths=paths); changed_snapshot,_=self.transport_snapshot(profile=changed)
            with self.subTest(path_key=path_key),self.assertRaises(transport.TransportBoundaryError):
                _resolve_deployment_authority(changed_snapshot,changed)
        value=json.loads(profile.runtime_contents[_MANIFEST_NAME]); value["trust_roots"]["rtwin_launcher"]["expected_sha256"]="0"*64
        contents=dict(profile.runtime_contents); contents[_MANIFEST_NAME]=canonical_json_bytes(value); changed=replace(profile,runtime_contents=contents); changed_snapshot,_=self.transport_snapshot(profile=changed)
        with self.assertRaises(transport.TransportBoundaryError): _resolve_deployment_authority(changed_snapshot,changed)

    def test_cmd_delayed_expansion_marker_rejects_in_bound_windows_paths(self) -> None:
        profile=self.profile(); paths=dict(profile.platform_paths)
        paths["rtwin_bootstrap_source_path"]=r"C:\AutoG16Runtime\!AUTO_G16_EXPAND!\bootstrap.py"
        changed=replace(profile,platform_paths=paths); snapshot,_=self.transport_snapshot(profile=changed)
        with patch("subprocess.Popen") as popen,self.assertRaises(transport.TransportBoundaryError):
            _resolve_deployment_authority(snapshot,changed)
        popen.assert_not_called()

    def test_outer_command_at_or_above_limit_rejects_before_process(self) -> None:
        profile=self.profile(); value=json.loads(profile.runtime_contents[_MANIFEST_NAME]); value["trust_roots"]["rtwin_launcher"]["path"]="C:\\"+("a"*3900)+".ps1"
        contents=dict(profile.runtime_contents); contents[_MANIFEST_NAME]=canonical_json_bytes(value); changed=replace(profile,runtime_contents=contents); snapshot,_=self.transport_snapshot(profile=changed)
        authority=_resolve_deployment_authority(snapshot,changed)
        with patch("subprocess.Popen") as popen,self.assertRaises(transport.TransportBoundaryError): _build_rtwin_command(snapshot,authority)
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

    def test_postlaunch_local_config_replacement_fails_closed(self) -> None:
        profile=self.profile(resource_descriptor=TORQUE_RESOURCE_DESCRIPTOR_BYTES)
        snapshot,_=self.transport_snapshot(profile=profile,queue="batch")
        authority=_resolve_deployment_authority(snapshot,profile)
        invocation=_Invocation(
            operation=_operation("ALLOCATE_WORKSPACE"),argv=(),cwd=snapshot.workspace_binding.remote_attempt_dir,
            request={"binding":{},"operation":"ALLOCATE_WORKSPACE","payload":{},"protocol":"auto-g16-v3-rtwin-bootstrap/2"},authority=authority,
        )
        driver=_SubprocessRTWinDriver()
        def communicate(_process,_request,_operation):
            self.mac_ssh_config.write_bytes(self.mac_ssh_config.read_bytes()+b"# replaced after launch\n")
            return b"",b"",0,"completed",True,True
        process=type("Process",(),{"pid":999_999_999,"kill":lambda self:None,"poll":lambda self:0})()
        with patch("subprocess.Popen",return_value=process) as popen,patch.object(driver,"_communicate_bounded",side_effect=communicate):
            result=driver.invoke_text(snapshot,invocation)
        popen.assert_called_once()
        self.assertEqual(result.completion_status,"transport-error")

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
