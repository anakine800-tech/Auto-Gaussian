"""MAC-DIRECT-UNMANAGED-V1 (OD-46): offline route, process-owner and chain tests.

No test creates a process or contacts a network: ``subprocess.Popen`` is either
replaced by a recording double or forbidden outright.
"""

from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

import auto_g16.execution as execution
from auto_g16._managed_native import service as managed_service
from auto_g16.transport import _bridge, _direct, _driver, _program_rtwin as bridge
from auto_g16.transport._canonical import TransportBoundaryError, canonical_json_bytes
from auto_g16.transport._recovery_process import _RecoveryProcessOwner
from tests.v3.execution import test_v31_lane_a as lane
from tests.v3.transport import _fixtures as v30
from tests.v31.transport import test_rtwin_successor_bridge as base

ALIAS = "direct-server"
UNMANAGED = ("mac-unmanaged-direct-ssh-config", "mac-unmanaged-direct-known-hosts", "mac-unmanaged-direct-public-key")
UNMANAGED_PATHS = ("mac_unmanaged_direct_ssh_config_path", "mac_unmanaged_direct_known_hosts_path", "mac_unmanaged_direct_public_key_path")
EXTRA_FIXED = "    CanonicalizeHostname no\n    ControlMaster no\n    ControlPath none\n    ControlPersist no\n    ConnectionAttempts 1\n"


def direct_config_bytes(option1_config: bytes) -> bytes:
    """Final-server block of the Option-1 fixture, rewritten to the Direct grammar."""
    old = option1_config.decode()
    comments = "\n".join(old.splitlines()[:2]).replace("AutoG16Final", "AutoG16Direct")
    final = ("Host " + old.rsplit("\nHost ", 1)[1]).replace("auto-g16-option1-final-server-v1", ALIAS)
    final = final.replace("    ProxyJump auto-g16-option1-rtwin-v1\n", "")
    return (comments + "\n" + final + EXTRA_FIXED).encode()


def unmanaged_profile(raw: execution.ServerProfile, *, config: bytes | None = None) -> execution.ServerProfile:
    files = dict(raw.config_files)
    config = direct_config_bytes(files["mac-proxyjump-ssh-config"]) if config is None else config
    path = Path(raw.platform_paths["mac_proxyjump_ssh_config_path"]).with_name("unmanaged-direct-config")
    path.write_bytes(config)
    paths = {key: value for key, value in raw.platform_paths.items() if not key.startswith("mac_") and key != "rtwin_root"}
    paths.update(zip(UNMANAGED_PATHS, (str(path), raw.platform_paths["mac_final_known_hosts_path"], raw.platform_paths["mac_final_public_key_path"])))
    return replace(raw, server_profile_id="synthetic-unmanaged-direct", jump_topology=[], platform_paths=paths,
                   config_files=list(zip(UNMANAGED, (config, files["mac-final-known-hosts"], files["mac-final-public-key"]))))


def successor_runtime(raw: execution.ServerProfile, *, mac_ssh: tuple[str, int, str] | None = None) -> execution.ServerProfile:
    """The exact successor runtime set the production bridge tests use."""
    manifest = json.loads(raw.runtime_contents["transport-deployment-manifest-v2.json"])
    manifest.update(schema="auto-g16-v3-transport-deployment-manifest/3", bootstrap_protocol=_bridge._PROGRAM_BOOTSTRAP_PROTOCOL)
    manifest["trust_roots"] = {key: value for key, value in manifest["trust_roots"].items() if key in {"mac_ssh", "server_remote_shell", "server_python", "server_qsub", "server_qstat"}}
    if mac_ssh is not None:
        manifest["trust_roots"]["mac_ssh"].update(path=mac_ssh[0], expected_size_bytes=mac_ssh[1], expected_sha256=mac_ssh[2])
    return replace(raw,
        platform_paths={**raw.platform_paths, "xtb_executable_path": "/opt/xtb/6.7.1/bin/xtb", "crest_executable_path": "/opt/crest/3.0.2/bin/crest", "xtb_data_path": "/opt/xtb/6.7.1/share/xtb"},
        runtime_contents={_driver._TABLE_NAME: _driver._OPERATION_TABLE_BYTES, _driver._RESOURCE_DESCRIPTOR_NAME: v30.TORQUE_RESOURCE_DESCRIPTOR_BYTES,
                          "transport-deployment-manifest-v3.json": canonical_json_bytes(manifest), _bridge._PROGRAM_BOOTSTRAP_SOURCE_NAME: _bridge._PROGRAM_BOOTSTRAP_SOURCE_BYTES,
                          "xtb": b"offline exact binary image A", "crest": b"offline exact binary image B", lane.XTB_RUNTIME_DATA_MANIFEST_NAME: lane.xtb_runtime_data_manifest_bytes()})


def resolve(profile: execution.ServerProfile, *, successor: bool = True) -> _driver._DeploymentAuthority:
    try:
        target = execution.resolve_server_profile(profile)
    except Exception as exc:  # a profile the resolver refuses is equally rejected
        raise TransportBoundaryError("profile rejected before Transport") from exc
    return _driver._resolve_closed_profile_authority(target, profile, target.resolved_server_profile_id, successor=successor)


class _Fixture(TestCase):
    def setUp(self) -> None:
        self.fixture = v30.TransportFixture()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.option1 = self.fixture.proxyjump_profile(resource_descriptor=v30.TORQUE_RESOURCE_DESCRIPTOR_BYTES)
        self.profile = successor_runtime(unmanaged_profile(self.option1))

    def with_config(self, transform) -> execution.ServerProfile:
        config = transform(dict(self.profile.config_files)[UNMANAGED[0]].decode()).encode()
        return successor_runtime(unmanaged_profile(self.option1, config=config))


class RouteSelectionTests(_Fixture):
    def test_exact_inventory_selects_unmanaged_route_only(self) -> None:
        authority = resolve(self.profile)
        effect = authority.ssh_effect
        self.assertIs(type(effect), _direct._MacUnmanagedDirectEffectAuthority)
        self.assertIsNot(type(effect), _direct._MacDirectEffectAuthority)
        self.assertEqual(effect.route, "mac-openssh-direct-unmanaged-v1")
        self.assertEqual((effect.final_target.alias, effect.final_target.host, effect.final_target.port, effect.final_target.user),
                         (ALIAS, "198.51.100.20", 22, "server-user"))
        self.assertTrue(bridge._is_option1_process_route(authority))

    def test_other_routes_keep_their_own_authority(self) -> None:
        self.assertIs(type(resolve(successor_runtime(self.option1)).ssh_effect), _driver._MacProxyJumpEffectAuthority)
        from tests.v3.managed_native.test_service import direct_profile
        managed = resolve(successor_runtime(direct_profile(self.option1)))
        self.assertIs(type(managed.ssh_effect), _direct._MacDirectEffectAuthority)
        self.assertEqual(managed.ssh_effect.route, "mac-openssh-direct-v1")
        self.assertFalse(bridge._is_option1_process_route(managed))

    def test_requires_program_successor_manifest(self) -> None:
        legacy = replace(unmanaged_profile(self.option1))
        with self.assertRaises(TransportBoundaryError):
            resolve(legacy, successor=False)

    def test_mixed_missing_or_extra_inventory_rejects(self) -> None:
        files = dict(self.profile.config_files)
        option1_files = dict(self.option1.config_files)
        cases = {
            "managed artifact added": replace(self.profile, config_files=[*self.profile.config_files, ("mac-direct-public-key", files[UNMANAGED[2]])]),
            "managed path added": replace(self.profile, platform_paths={**self.profile.platform_paths, "mac_direct_ssh_config_path": "/tmp/other"}),
            "option1 path added": replace(self.profile, platform_paths={**self.profile.platform_paths, "mac_final_known_hosts_path": "/tmp/other"}),
            "option1 artifact added": replace(self.profile, config_files=[*self.profile.config_files, ("mac-rtwin-known-hosts", option1_files["mac-rtwin-known-hosts"])]),
            "rtwin path added": replace(self.profile, platform_paths={**self.profile.platform_paths, "rtwin_root": r"C:\RTWIN"}),
            "artifact missing": replace(self.profile, config_files=self.profile.config_files[:2]),
            "path missing": replace(self.profile, platform_paths={k: v for k, v in self.profile.platform_paths.items() if k != UNMANAGED_PATHS[1]}),
            "paths not distinct": replace(self.profile, platform_paths={**self.profile.platform_paths, UNMANAGED_PATHS[1]: self.profile.platform_paths[UNMANAGED_PATHS[2]]}),
            "jump topology": replace(self.profile, jump_topology=[("192.0.2.10", 22, "jump-user")]),
        }
        for name, profile in cases.items():
            with self.subTest(name), self.assertRaises(TransportBoundaryError):
                resolve(profile)

    def test_closed_directive_grammar_rejects_route_and_security_changes(self) -> None:
        cases = {
            "ProxyJump": lambda c: c.replace("    Port 22\n", "    Port 22\n    ProxyJump auto-g16-option1-rtwin-v1\n"),
            "ProxyCommand": lambda c: c.replace("    Port 22\n", "    Port 22\n    ProxyCommand nc\n"),
            "host key checking": lambda c: c.replace("StrictHostKeyChecking yes", "StrictHostKeyChecking no"),
            "password": lambda c: c.replace("PasswordAuthentication no", "PasswordAuthentication yes"),
            "agent forwarding": lambda c: c.replace("ForwardAgent no", "ForwardAgent yes"),
            "missing fixed directive": lambda c: c.replace("    ConnectionAttempts 1\n", ""),
            "target host": lambda c: c.replace("HostName 198.51.100.20", "HostName 198.51.100.21"),
            "target user": lambda c: c.replace("User server-user", "User other-user"),
            "fingerprint": lambda c: c.replace("# AutoG16DirectIdentityFingerprint SHA256:", "# AutoG16DirectIdentityFingerprint SHA256:A"),
            "second host block": lambda c: c + "Host extra\n",
        }
        self.assertEqual(type(resolve(self.profile).ssh_effect), _direct._MacUnmanagedDirectEffectAuthority)
        for name, transform in cases.items():
            with self.subTest(name), self.assertRaises(TransportBoundaryError):
                resolve(self.with_config(transform))

    def test_requires_option1_qualified_openssh_identity(self) -> None:
        drifted = successor_runtime(unmanaged_profile(self.option1), mac_ssh=(_driver._OPTION1_MAC_SSH[0], _driver._OPTION1_MAC_SSH[1], "0" * 64))
        with self.assertRaises(TransportBoundaryError):
            resolve(drifted)


class CommandAndProcessOwnerTests(_Fixture):
    def setUp(self) -> None:
        super().setUp()
        self.authority = resolve(self.profile)
        self.target = execution.resolve_server_profile(self.profile)
        managed_entry = patch.object(managed_service, "run_direct", side_effect=AssertionError("managed entry must not be reached"))
        self.managed = managed_entry.start()
        self.addCleanup(managed_entry.stop)

    def invocation(self, operation: str = "OBSERVE_PROJECT") -> bridge._ProgramRTWinInvocation:
        request = {"protocol": _bridge._PROGRAM_BOOTSTRAP_PROTOCOL, "operation": operation,
                   "binding": bridge._wire_binding(self.target, self.target.resolved_server_profile_id, "/home/user100/SDL/project-1"), "payload": {}}
        return bridge._ProgramRTWinInvocation(_driver._operation(operation) if operation in _driver._OPERATIONS else bridge._project_operation(operation),
                                              self.authority, self.profile, request, self.target.resolved_server_profile_id)

    def test_command_is_option1_shape_with_identical_server_command(self) -> None:
        command, frame = bridge._prepare_program_invocation(self.target, self.invocation())
        self.assertEqual(command[:5], ("/usr/bin/ssh", "-F", self.authority.ssh_effect.config.path, "--", ALIAS))
        self.assertEqual(command[-1], _bridge._render_program_server_command(self.authority, _bridge._PROGRAM_BOOTSTRAP_SOURCE_BYTES))
        self.assertNotIn("-J", command)
        self.assertNotIn("ProxyJump", " ".join(command[:-1]))
        self.assertTrue(frame.startswith(b"AGV3"))
        option1 = resolve(successor_runtime(self.option1))
        self.assertEqual(command[-1], _bridge._render_program_server_command(option1, _bridge._PROGRAM_BOOTSTRAP_SOURCE_BYTES))

    def _run(self, owner, invocation, *, attestations, communicate=None):
        process = type("Process", (), {"pid": 999_999_999, "poll": lambda self: 0, "wait": lambda self, timeout=None: 0})()
        calls = []

        def attest(authority):
            self.assertIs(authority, invocation.authority)
            calls.append("attest")
            value = attestations.pop(0)
            if isinstance(value, BaseException):
                raise value
            return value

        def bounded(_process, request, operation):
            calls.append("communicate")
            self.assertTrue(request.startswith(b"AGV3"))
            return communicate or (b"response", b"", 0, "completed", True, True)

        with (patch.object(_direct, "_attest_direct_local", side_effect=attest),
              patch.object(_driver, "_attest_direct_local", side_effect=attest),
              patch.object(_driver, "_attest_local", side_effect=AssertionError("Option-1 per-file attestation not used")),
              patch.object(_driver.subprocess, "Popen", return_value=process) as popen,
              patch.object(owner, "_communicate_bounded", side_effect=bounded),
              patch.object(owner, "_kill")):
            result = owner._run(self.target, invocation)
        return result, popen, calls

    def test_driver_uses_one_fixed_popen_with_attestation_before_and_after(self) -> None:
        invocation = self.invocation()
        result, popen, calls = self._run(_driver._SubprocessRTWinDriver(), invocation, attestations=[{"same": 1}, {"same": 1}])
        self.assertEqual(result, (b"response", b"", 0, "completed", True, True))
        self.assertEqual(calls, ["attest", "communicate", "attest"])
        popen.assert_called_once()
        self.assertEqual(popen.call_args.args[0], bridge._prepare_program_invocation(self.target, invocation)[0])
        self.assertIs(popen.call_args.kwargs["shell"], False)
        self.assertIs(popen.call_args.kwargs["start_new_session"], True)
        self.assertEqual(popen.call_args.kwargs["env"], dict(_driver._FIXED_ENV))
        self.managed.assert_not_called()

    def test_attestation_drift_after_process_is_transport_error_without_output(self) -> None:
        result, popen, _calls = self._run(_driver._SubprocessRTWinDriver(), self.invocation(), attestations=[{"x": 1}, {"x": 2}])
        # Project operations keep their existing bounded diagnostic, never success.
        self.assertEqual(result, (b"response", b"", None, "transport-error", False, False))
        popen.assert_called_once()

    def test_attestation_failure_before_process_creates_no_process(self) -> None:
        with self.assertRaises(TransportBoundaryError):
            self._run(_driver._SubprocessRTWinDriver(), self.invocation(), attestations=[TransportBoundaryError("drift")])

    def test_recovery_owner_uses_same_route_and_reports_identity_drift(self) -> None:
        invocation = self.invocation("RECONCILE_SUBMISSION")
        with patch.object(bridge, "_prepare_program_invocation", return_value=(("/usr/bin/ssh", "-F", self.authority.ssh_effect.config.path, "--", ALIAS, "cmd"), b"AGV3 frame")):
            ok, popen, calls = self._run(_RecoveryProcessOwner(), invocation, attestations=[{"a": 1}, {"a": 1}])
            self.assertEqual(ok[3], "completed")
            self.assertEqual(calls, ["attest", "communicate", "attest"])
            self.assertIs(popen.call_args.kwargs["shell"], False)
            drift, _popen, _calls = self._run(_RecoveryProcessOwner(), invocation, attestations=[{"a": 1}, {"a": 2}])
            self.assertEqual(drift[3], "identity-drift")
        self.managed.assert_not_called()

    def test_real_attestation_never_opens_private_identity(self) -> None:
        opened = []
        real_open = _direct.os.open

        def tracking(path, flags, *args, **kwargs):
            opened.append(path)
            return real_open(path, flags, *args, **kwargs)

        private_leaf = Path(self.authority.ssh_effect.final_target.identity_file).name
        with patch.object(_direct.os, "open", side_effect=tracking):
            try:
                _direct._attest_direct_local(self.authority)
            except TransportBoundaryError as exc:
                # The synthetic manifest pins /usr/bin/ssh, absent or different here;
                # the type gate itself must have admitted the unmanaged authority.
                self.assertNotIn("requires exact authority", str(exc))
        self.assertNotIn(private_leaf, opened)
        self.assertIn(Path(self.authority.ssh_effect.config.path).name, opened)


class _DirectWire(base._Wire):
    """Offline wire peer requiring the unmanaged Direct argv shape."""

    def __init__(self) -> None:
        super().__init__()
        self.commands = []

    def run(self, scope, invocation):
        command, frame = bridge._prepare_program_invocation(scope, invocation)
        assert type(invocation.authority.ssh_effect) is _direct._MacUnmanagedDirectEffectAuthority
        assert command[:5] == ("/usr/bin/ssh", "-F", invocation.authority.ssh_effect.config.path, "--", ALIAS)
        self.commands.append(command)
        # The shared peer validates the Option-1 alias; the bytes after it are equal.
        shaped = (*command[:4], "auto-g16-option1-final-server-v1", *command[5:])
        with patch.object(bridge, "_prepare_program_invocation", return_value=(shaped, frame)):
            return super().run(scope, invocation)


class UnmanagedDirectProductionChainTests(base.ProductionBridgeTests):
    """Every production bridge scenario, re-run over the unmanaged Direct profile.

    The real Project service, snapshot owner, Program driver, approvals, Core
    store and Transport store run unchanged; only the wire peer is offline.
    """

    def setUp(self) -> None:
        lane.LaneAFixture.setUp(self)
        fixture = v30.TransportFixture()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        raw = fixture.proxyjump_profile(resource_descriptor=v30.TORQUE_RESOURCE_DESCRIPTOR_BYTES)
        self.current_profile = successor_runtime(unmanaged_profile(raw))
        self.target = execution.resolve_server_profile(self.current_profile)
        root = self.root / "bridge"
        root.mkdir()
        self.journal_path = root / "projects.sqlite3"
        self.journal = base._ProductionProvisioningJournal.create_new(self.journal_path, approved_root=root)
        self.addCleanup(self.journal.close)
        self.program_store = base.program._ProgramTransportStore.create_new(root / "program.sqlite3", approved_root=root)
        self.addCleanup(self.program_store.close)
        self.wire = _DirectWire()
        self.process_spy = patch.object(_driver.subprocess, "Popen", side_effect=AssertionError("offline tests prohibit processes")).start()
        self.addCleanup(patch.stopall)
        patch.object(managed_service, "run_direct", side_effect=AssertionError("managed entry must not be reached")).start()
        self.run_patch = patch.object(_driver._SubprocessRTWinDriver, "_run", side_effect=self.wire.run)
        self.run_spy = self.run_patch.start()
        self.service = base._ProjectProvisioningService._from_project_attestor(attestor=bridge._RTWinProjectAttestor(current_profile=self.current_profile, target=self.target), target=self.target, journal=self.journal)

    def test_unmanaged_chain_submits_once_and_replays_without_wire(self) -> None:
        self.prepare()
        self.assertIs(type(self.driver._authority().ssh_effect), _direct._MacUnmanagedDirectEffectAuthority)
        self.execute()
        operations = [op for op, _request in self.wire.calls]
        self.assertEqual(operations.count("SUBMIT_QSUB_ONCE"), 1)
        self.assertTrue(all(command[4] == ALIAS for command in self.wire.commands))
        before = len(self.wire.calls)
        self.query()
        self.capture()
        self.assertEqual(sum(op == "SUBMIT_QSUB_ONCE" for op, _ in self.wire.calls), 1)
        self.assertGreater(len(self.wire.calls), before)


if __name__ == "__main__":
    import unittest

    unittest.main()
