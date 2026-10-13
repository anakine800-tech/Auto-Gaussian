from __future__ import annotations

from dataclasses import replace
import os
from unittest.mock import patch

import auto_g16.transport as transport
from auto_g16.transport._bridge import _build_mac_proxyjump_command
from auto_g16.transport._driver import (
    _Invocation,
    _MacProxyJumpEffectAuthority,
    _OPTION1_MAC_SSH,
    _SubprocessRTWinDriver,
    _attest_identity_reference,
    _operation,
    _resolve_deployment_authority,
)

from ._fixtures import TORQUE_RESOURCE_DESCRIPTOR_BYTES, TransportFixture


class Option1ProxyJumpContractTests(TransportFixture):
    @staticmethod
    def _replace_config(profile, transform):
        values = dict(profile.config_files)
        values["mac-proxyjump-ssh-config"] = transform(values["mac-proxyjump-ssh-config"])
        return replace(profile, config_files=[(name, values[name]) for name, _raw in profile.config_files])

    def test_profile_resolves_exact_option1_route_and_command(self) -> None:
        profile = self.proxyjump_profile()
        snapshot, _ = self.transport_snapshot(profile=profile)
        authority = _resolve_deployment_authority(snapshot, profile)
        self.assertIsInstance(authority.ssh_effect, _MacProxyJumpEffectAuthority)
        self.assertEqual(authority.ssh_effect.route, "mac-openssh-proxyjump-v1")
        self.assertEqual(
            (
                authority.ssh_effect.rtwin_target.host,
                authority.ssh_effect.rtwin_target.port,
                authority.ssh_effect.rtwin_target.user,
            ),
            ("192.0.2.10", 22, "jump-user"),
        )
        self.assertEqual(
            (
                authority.ssh_effect.final_target.host,
                authority.ssh_effect.final_target.port,
                authority.ssh_effect.final_target.user,
            ),
            ("198.51.100.20", 22, "server-user"),
        )
        command = _build_mac_proxyjump_command(snapshot, authority)
        self.assertEqual(command[:5], (_OPTION1_MAC_SSH[0], "-F", authority.ssh_effect.config.path, "--", "auto-g16-option1-final-server-v1"))
        self.assertIn("'/usr/bin/python3' '-I' '-S' '-B' '-c'", command[-1])
        self.assertNotIn("powershell", " ".join(command).lower())
        self.assertNotIn("rtwin_launcher", " ".join(command))
        self.assertNotIn("-J", command)

    def test_option1_requires_exact_qualified_mac_openssh_identity(self) -> None:
        profile = self.proxyjump_profile()
        raw = profile.runtime_contents["transport-deployment-manifest-v2.json"]
        for old, new in (
            (_OPTION1_MAC_SSH[2].encode(), b"0" * 64),
            (str(_OPTION1_MAC_SSH[1]).encode(), b"1584575"),
            (_OPTION1_MAC_SSH[0].encode(), b"/opt/ssh"),
        ):
            with self.subTest(old=old):
                changed_raw = raw.replace(old, new)
                changed = replace(profile, runtime_contents={**profile.runtime_contents, "transport-deployment-manifest-v2.json": changed_raw})
                snapshot, _ = self.transport_snapshot(profile=changed)
                with self.assertRaises(transport.TransportBoundaryError):
                    _resolve_deployment_authority(snapshot, changed)

    def test_proxyjump_config_closes_security_and_route_directives(self) -> None:
        profile = self.proxyjump_profile()
        original = dict(profile.config_files)["mac-proxyjump-ssh-config"]
        mutations = (
            lambda raw: raw.replace(b"ForwardAgent no", b"ForwardAgent yes", 1),
            lambda raw: raw.replace(b"CertificateFile none\n", b"", 1),
            lambda raw: raw.replace(b"CertificateFile none", b"CertificateFile sibling-cert.pub", 1),
            lambda raw: raw.replace(b"SHA256:", b"SHA256:wrong", 1),
            lambda raw: raw.replace(b"BatchMode yes\n", b"", 1),
            lambda raw: raw.replace(b"ProxyJump auto-g16-option1-rtwin-v1", b"ProxyJump other"),
            lambda raw: raw.replace(b"ProxyJump auto-g16-option1-rtwin-v1", b"ProxyCommand arbitrary"),
            lambda raw: raw.replace(b"IdentityFile ", b"IdentityFile ~/", 1),
            lambda raw: raw.replace(b"UserKnownHostsFile ", b"UserKnownHostsFile /tmp/other", 1),
            lambda raw: raw + b"Host extra\n",
        )
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                changed = self._replace_config(profile, mutate)
                snapshot, _ = self.transport_snapshot(profile=changed)
                with self.assertRaises(transport.TransportBoundaryError):
                    _resolve_deployment_authority(snapshot, changed)
        self.assertIn(b"ForwardAgent no", original)
        self.assertEqual(original.count(b"WarnWeakCrypto no\n"), 2)
        self.assertEqual(original.count(b"CertificateFile none\n"), 2)
        self.assertNotIn(b"ProxyCommand", original)

    def test_proxyjump_config_requires_exact_warning_suppression_on_both_hops(self) -> None:
        profile = self.proxyjump_profile()
        mutations = (
            lambda raw: raw.replace(b"    WarnWeakCrypto no\n", b"", 1),
            lambda raw: raw.replace(b"    WarnWeakCrypto no\n", b"    WarnWeakCrypto yes\n", 1),
            lambda raw: raw.replace(b"    WarnWeakCrypto no\n", b"    WarnWeakCrypto maybe\n", 1),
            lambda raw: raw.replace(
                b"    WarnWeakCrypto no\n",
                b"    WarnWeakCrypto no\n    WarnWeakCrypto no\n",
                1,
            ),
        )
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                changed = self._replace_config(profile, mutate)
                snapshot, _ = self.transport_snapshot(profile=changed)
                with self.assertRaises(transport.TransportBoundaryError):
                    _resolve_deployment_authority(snapshot, changed)

    def test_sibling_certificates_have_no_implicit_authority(self) -> None:
        profile = self.proxyjump_profile()
        for marker in ("option1-rtwin-identity-cert.pub", "option1-final-identity-cert.pub"):
            (self.temporary / marker).write_bytes(b"unbound synthetic certificate")
        snapshot, _ = self.transport_snapshot(profile=profile)
        authority = _resolve_deployment_authority(snapshot, profile)
        self.assertIsInstance(authority.ssh_effect, _MacProxyJumpEffectAuthority)
        config = dict(profile.config_files)["mac-proxyjump-ssh-config"]
        self.assertEqual(config.count(b"CertificateFile none\n"), 2)

    def test_option1_config_inventory_has_no_legacy_fallback(self) -> None:
        profile = self.proxyjump_profile()
        for config_files in (
            profile.config_files[:-1],
            [*profile.config_files, ("mac-ssh-config", b"legacy")],
            [("mac-ssh-config", b"legacy"), *profile.config_files[1:]],
        ):
            with self.subTest(config_files=config_files):
                changed = replace(profile, config_files=config_files)
                snapshot, _ = self.transport_snapshot(profile=changed)
                with self.assertRaises(transport.TransportBoundaryError):
                    _resolve_deployment_authority(snapshot, changed)

    def test_identity_reference_attestation_never_opens_or_reads_key(self) -> None:
        profile = self.proxyjump_profile()
        snapshot, _ = self.transport_snapshot(profile=profile)
        effect = _resolve_deployment_authority(snapshot, profile).ssh_effect
        assert isinstance(effect, _MacProxyJumpEffectAuthority)
        with patch("os.open", side_effect=AssertionError("private identity bytes must not be opened")):
            evidence = _attest_identity_reference(effect.final_target.identity_file,effect.final_identity_file_identity)
        self.assertEqual(len(evidence), 5)
        with self.assertRaises(transport.TransportBoundaryError):
            _attest_identity_reference(effect.final_target.identity_file,(*evidence[:-1],evidence[-1]+1))
        os.chmod(effect.final_target.identity_file, 0o644)
        with self.assertRaises(transport.TransportBoundaryError):
            _attest_identity_reference(effect.final_target.identity_file)

    def test_final_public_key_fingerprint_is_bound_to_exact_artifact(self) -> None:
        profile = self.proxyjump_profile()
        raw = dict(profile.config_files)["mac-final-public-key"]
        changed = replace(profile,config_files=[
            (name,value.replace(b"AAAAIAAB",b"AAAAIAEB",1) if name=="mac-final-public-key" else value)
            for name,value in profile.config_files
        ])
        snapshot, _ = self.transport_snapshot(profile=changed)
        with self.assertRaises(transport.TransportBoundaryError):
            _resolve_deployment_authority(snapshot,changed)
        self.assertTrue(raw.startswith(b"ssh-ed25519 "))

    def test_driver_uses_only_option1_command_and_exact_bounded_request(self) -> None:
        profile = self.proxyjump_profile(resource_descriptor=TORQUE_RESOURCE_DESCRIPTOR_BYTES)
        snapshot, _ = self.transport_snapshot(profile=profile, queue="batch")
        authority = _resolve_deployment_authority(snapshot, profile)
        invocation = _Invocation(
            operation=_operation("ALLOCATE_WORKSPACE"),
            argv=(),
            cwd=snapshot.workspace_binding.remote_attempt_dir,
            request={"binding": {}, "operation": "ALLOCATE_WORKSPACE", "payload": {}, "protocol": "auto-g16-v3-rtwin-bootstrap/2"},
            authority=authority,
        )
        process = type("Process", (), {"pid": 999_999_999, "poll": lambda self: 0})()
        captured: dict[str, object] = {}

        def communicate(_process, request, operation):
            captured["request"] = request
            captured["operation"] = operation
            return b"response", b"", 0, "completed", True, True

        driver = _SubprocessRTWinDriver()
        with (
            patch("auto_g16.transport._driver._attest_local", return_value=(1, 2)),
            patch("auto_g16.transport._driver._attest_local_effect_file", return_value=(3, 4)),
            patch("auto_g16.transport._driver._attest_identity_reference", return_value=(5, 6, 7, 8)),
            patch("subprocess.Popen", return_value=process) as popen,
            patch.object(driver, "_communicate_bounded", side_effect=communicate),
        ):
            result = driver._run(snapshot, invocation)
        self.assertEqual(result, (b"response", b"", 0, "completed", True, True))
        command = popen.call_args.args[0]
        self.assertEqual(command, _build_mac_proxyjump_command(snapshot, authority))
        self.assertIs(popen.call_args.kwargs["shell"], False)
        self.assertEqual(command.count("--"), 1)
        self.assertTrue(captured["request"].startswith(b"AGV3"))


if __name__ == "__main__":
    import unittest

    unittest.main()
