#!/usr/bin/env python3
"""Offline adversarial tests for the fixed one-hop W5 effect consumer."""

from __future__ import annotations

import ast
import copy
import json
import os
import pickle
import struct
import subprocess
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

from tests.test_direct_trusted_session_composition import PortableSessionFixture


ROOT = Path(__file__).parents[1]
SCRIPTS = ROOT / "scripts"

import sys

sys.path.insert(0, str(SCRIPTS))

import direct_durable_submission_journal as W2  # noqa: E402
import direct_one_hop_transport as W5  # noqa: E402
import direct_trusted_session_composition as SESSION  # noqa: E402


class DirectOneHopTransportTests(unittest.TestCase):
    maxDiff = None

    @staticmethod
    def rederive_receipt(document: dict[str, object]) -> dict[str, object]:
        value = copy.deepcopy(document)
        value["receipt_id"] = "direct-submission-receipt-" + W5.digest(
            {key: item for key, item in value.items() if key not in {"receipt_id", "result_payload_sha256"}}
        )
        value["result_payload_sha256"] = W5.digest({**value, "result_payload_sha256": ""})
        return value

    @staticmethod
    def different_sha(value: str) -> str:
        replacement = "a" if value[0] != "a" else "b"
        return replacement * 64

    def seam(self, fixture: PortableSessionFixture) -> SESSION.TrustedW5OperationSeam:
        capability = fixture.compose()
        lease = capability.consume_for_w5_once()
        return SESSION.consume_w5_operation_seam_once(lease)

    def test_success_issues_exact_nonportable_receipt_and_closes_completed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="auto-g16-w5-success-") as raw:
            fixture = PortableSessionFixture(Path(raw).resolve())
            try:
                seam = self.seam(fixture)
                binding = seam.direct_binding
                journal_id = seam.durable_claim.journal_id
                driver = W5._test_driver(stdout=b"12345.master\n")
                receipt = W5._consume_with_test_driver_once(
                    seam,
                    driver,
                    _test_token=W5._TEST_DRIVER_TOKEN,
                )
                receipt.assert_owner_sealed()
                self.assertEqual(driver.calls, 1)
                projection = receipt.portable_projection()
                self.assertFalse(projection["authority"]["authorizes_effect"])
                self.assertFalse(projection["qsub"]["raw_stdout_included"])
                self.assertEqual(projection["qsub"]["calls"], "1")
                self.assertEqual(projection["invocation"]["call_count"], "1")
                self.assertEqual(projection["outcome"]["returncode"], "0")
                self.assertTrue(all(item["size_bytes"].isdigit() for item in projection["uploaded"]))
                self.assertEqual(projection["qsub"]["job_id"], "12345.master")
                self.assertFalse(projection["outcome"]["raw_stdout_retained"])
                self.assertNotIn("raw_stdout", projection["outcome"])
                self.assertEqual(projection["attempt_id"], binding.document()["scope"]["attempt_id"])
                self.assertEqual(
                    projection["transport_profile_payload_sha256"],
                    W5.load_transport_profile(fixture.artifacts.transport_profile)["profile_payload_sha256"],
                )
                for operation in (copy.copy, copy.deepcopy, pickle.dumps):
                    with self.assertRaises(TypeError):
                        operation(receipt)
                project = fixture.root / binding.document()["workspace"]["project"]
                self.assertEqual(set(item.name for item in project.iterdir()), set(W5.ALLOWLIST) | {"scratch"})
                self.assertEqual((project / W5.INPUT_BASENAME).read_bytes(), fixture.artifacts.input_bytes)
                self.assertEqual((project / W5.PBS_BASENAME).read_bytes(), fixture.artifacts.pbs_script)
                self.assertEqual(
                    (project / W5.SUBMISSION_RECEIPT_BASENAME).read_bytes(),
                    W5.canonical_bytes(projection),
                )
                snapshot = W2.reconcile_read_only(fixture.state, journal_id, binding).document()
                self.assertEqual(snapshot["effective_outcome"], "completed")
                self.assertFalse(snapshot["reconciliation"]["second_effect_allowed"])
            finally:
                fixture.close()

    def test_receipt_id_and_controller_reject_rederived_stale_or_foreign_results(self) -> None:
        with tempfile.TemporaryDirectory(prefix="auto-g16-w5-receipt-join-") as raw:
            fixture = PortableSessionFixture(Path(raw).resolve())
            request_join = None
            replay_join = None
            try:
                capability = fixture.compose()
                readiness = SESSION._session_ready_document(capability)
                lease = capability.consume_for_w5_once()
                seam = SESSION.consume_w5_operation_seam_once(lease)
                receipt = W5._consume_with_test_driver_once(
                    seam,
                    W5._test_driver(stdout=b"12345.master\n"),
                    _test_token=W5._TEST_DRIVER_TOKEN,
                ).portable_projection()
                profile = W5._validate_controller_artifact_join(fixture.artifacts)
                request_join = W5._issue_controller_request_join(fixture.artifacts)
                response = W5._build_controller_completed_response(
                    request_join.request_id,
                    readiness,
                    receipt,
                )
                self.assertEqual(
                    receipt,
                    W5._validate_controller_response(response, fixture.artifacts, profile, request_join),
                )

                mutations = {
                    "binding_payload_sha256": self.different_sha(receipt["binding_payload_sha256"]),
                    "journal_id": "direct-durable-submission-journal-"
                    + self.different_sha(receipt["journal_id"].rsplit("-", 1)[-1]),
                    "attempt_id": "qsub-attempt-"
                    + self.different_sha(receipt["attempt_id"].rsplit("-", 1)[-1]),
                    "project": receipt["project"] + "-foreign",
                    "input_sha256": self.different_sha(receipt["input_sha256"]),
                    "authorization_payload_sha256": self.different_sha(
                        receipt["authorization_payload_sha256"]
                    ),
                }
                for field, replacement in mutations.items():
                    with self.subTest(field=field):
                        stale_id = copy.deepcopy(receipt)
                        stale_id[field] = replacement
                        stale_id["result_payload_sha256"] = W5.digest(
                            {**stale_id, "result_payload_sha256": ""}
                        )
                        with self.assertRaisesRegex(
                            W5.DirectOneHopTransportError,
                            "receipt id derivation",
                        ):
                            W5.validate_submission_receipt(stale_id)

                        hostile = self.rederive_receipt(stale_id)
                        self.assertEqual(hostile, W5.validate_submission_receipt(hostile))
                        hostile_response = copy.deepcopy(response)
                        hostile_response["receipt"] = hostile
                        hostile_response["response_payload_sha256"] = W5.digest(
                            {**hostile_response, "response_payload_sha256": ""}
                        )
                        with self.assertRaisesRegex(
                            W5.DirectOneHopTransportError,
                            "stale, foreign, or unbound",
                        ):
                            W5._validate_controller_response(
                                hostile_response,
                                fixture.artifacts,
                                profile,
                                request_join,
                            )

                combined = copy.deepcopy(receipt)
                combined.update(mutations)
                combined = self.rederive_receipt(combined)
                self.assertEqual(combined, W5.validate_submission_receipt(combined))
                combined_response = copy.deepcopy(response)
                combined_response["receipt"] = combined
                combined_response["response_payload_sha256"] = W5.digest(
                    {**combined_response, "response_payload_sha256": ""}
                )
                with self.assertRaisesRegex(
                    W5.DirectOneHopTransportError,
                    "stale, foreign, or unbound",
                ):
                    W5._validate_controller_response(
                        combined_response,
                        fixture.artifacts,
                        profile,
                        request_join,
                    )

                for field in ("binding_payload_sha256", "journal_id"):
                    owner_hostile = copy.deepcopy(receipt)
                    owner_hostile[field] = mutations[field]
                    owner_hostile = self.rederive_receipt(owner_hostile)
                    with self.assertRaisesRegex(
                        W5.DirectOneHopTransportError,
                        "server owner session/result join",
                    ):
                        W5._build_controller_completed_response(
                            request_join.request_id,
                            readiness,
                            owner_hostile,
                        )

                replay_join = W5._issue_controller_request_join(fixture.artifacts)
                self.assertNotEqual(request_join.request_id, replay_join.request_id)
                with self.assertRaisesRegex(
                    W5.DirectOneHopTransportError,
                    "request/result commitment",
                ):
                    W5._validate_controller_response(
                        response,
                        fixture.artifacts,
                        profile,
                        replay_join,
                    )

                unknown = copy.deepcopy(response)
                unknown["status"] = "unknown"
                unknown["response_payload_sha256"] = W5.digest(
                    {**unknown, "response_payload_sha256": ""}
                )
                with self.assertRaisesRegex(
                    W5.DirectOneHopTransportError,
                    "request/result commitment",
                ):
                    W5._validate_controller_response(
                        unknown,
                        fixture.artifacts,
                        profile,
                        request_join,
                    )
            finally:
                if request_join is not None:
                    W5._retire_controller_request_join(request_join)
                if replay_join is not None:
                    W5._retire_controller_request_join(replay_join)
                fixture.close()

    def test_controller_request_join_is_typed_artifact_bound_and_one_use(self) -> None:
        with tempfile.TemporaryDirectory(prefix="auto-g16-w5-request-join-") as raw:
            fixture = PortableSessionFixture(Path(raw).resolve())
            join = W5._issue_controller_request_join(fixture.artifacts)
            try:
                for operation in (copy.copy, copy.deepcopy, pickle.dumps):
                    with self.assertRaises(TypeError):
                        operation(join)
                frame = W5._artifact_frame(fixture.artifacts, join)
                size = struct.unpack("!I", frame[:4])[0]
                self.assertEqual(size, len(frame) - 4)
                request = json.loads(frame[4:])
                decoded, request_id = W5._decode_controller_request(request)
                self.assertEqual(request_id, join.request_id)
                self.assertEqual(
                    W5._artifact_hashes(decoded),
                    W5._artifact_hashes(fixture.artifacts),
                )

                hostile = copy.deepcopy(request)
                hostile["artifacts"]["input_bytes"] = hostile["artifacts"]["pbs_script"]
                with self.assertRaisesRegex(
                    W5.DirectOneHopTransportError,
                    "request commitment",
                ):
                    W5._decode_controller_request(hostile)
            finally:
                W5._retire_controller_request_join(join)
                fixture.close()
            with self.assertRaisesRegex(
                W5.DirectOneHopTransportError,
                "foreign, forked, or terminal",
            ):
                join.assert_owner_sealed()

    def test_effect_possible_precedes_invoke_and_every_ambiguous_path_is_unknown(self) -> None:
        cases = (
            ("invoke_raises", W5._test_driver(stdout=b"", raise_inside=True), None),
            ("timeout", W5._test_driver(stdout=b"", uncertain=True), None),
            ("eof", W5._test_driver(stdout=b"", returncode=None, uncertain=True), None),
            ("malformed", W5._test_driver(stdout=b"not-a-job\n"), None),
            ("injection", W5._test_driver(stdout=b"1.master\nSECOND\n"), None),
            ("stderr", W5._test_driver(stdout=b"1.master\n", stderr=b"warning"), None),
            ("after_call_crash", W5._test_driver(stdout=b"1.master\n"), RuntimeError("after-call")),
        )
        for label, driver, after_call in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory(prefix=f"auto-g16-w5-{label}-") as raw:
                fixture = PortableSessionFixture(Path(raw).resolve())
                try:
                    seam = self.seam(fixture)
                    binding = seam.direct_binding
                    journal_id = seam.durable_claim.journal_id
                    context = (
                        mock.patch.object(W5, "_job_id", side_effect=after_call)
                        if after_call is not None
                        else mock.patch.object(W5, "_job_id", wraps=W5._job_id)
                    )
                    with context:
                        with self.assertRaises(W5.SubmissionOutcomeUnknown):
                            W5._consume_with_test_driver_once(
                                seam,
                                driver,
                                _test_token=W5._TEST_DRIVER_TOKEN,
                            )
                    self.assertEqual(driver.calls, 1)
                    snapshot = W2.reconcile_read_only(fixture.state, journal_id, binding).document()
                    self.assertEqual(snapshot["effective_outcome"], "unknown")
                    self.assertEqual(snapshot["state"], "submission_uncertain")
                    self.assertFalse(snapshot["reconciliation"]["second_effect_allowed"])
                finally:
                    fixture.close()

    def test_profile_owns_ssh_subsystem_and_has_no_remote_shell_or_override(self) -> None:
        with tempfile.TemporaryDirectory(prefix="auto-g16-w5-profile-") as raw:
            fixture = PortableSessionFixture(Path(raw).resolve())
            try:
                argv = W5.build_controller_argv(fixture.artifacts.transport_profile)
                with mock.patch.dict(os.environ, {"HOME": "/tmp/poison-home", "SSH_CONFIG": "/tmp/poison-config"}):
                    self.assertEqual(argv, W5.build_controller_argv(fixture.artifacts.transport_profile))
                self.assertEqual(argv[0], W5.SSH_EXECUTABLE)
                self.assertIn("-s", argv)
                self.assertIn("-F", argv)
                self.assertIn("none", argv)
                self.assertNotIn("/dev/null", argv)
                self.assertEqual(argv[-1], W5.SSH_SUBSYSTEM)
                self.assertNotIn("sh", argv)
                self.assertNotIn("-c", argv)
                for option in (
                    "IdentityFile=none", "IdentityAgent=none", "CertificateFile=none",
                    "PKCS11Provider=none", "SecurityKeyProvider=none",
                    "GlobalKnownHostsFile=none", "KnownHostsCommand=none",
                    "VerifyHostKeyDNS=no", "UpdateHostKeys=no",
                    "ProxyCommand=none", "ProxyJump=none", "PermitLocalCommand=no",
                    "ControlMaster=no", "ControlPath=none", "ForwardAgent=no",
                    "ForwardX11=no", "ClearAllForwardings=yes", "RequestTTY=no",
                ):
                    self.assertIn(option, argv)
                profile = W5.load_transport_profile(fixture.artifacts.transport_profile)

                identity_path = Path(raw) / "synthetic-reviewed-identity"
                known_hosts_path = Path(raw) / "synthetic-reviewed-known-hosts"
                identity_path.write_bytes(b"offline-static-identity-placeholder\n")
                identity_path.chmod(0o600)
                known_hosts_path.write_bytes(b"offline-static-known-hosts-placeholder\n")
                static_profile = copy.deepcopy(profile)
                static_profile["ssh"]["identity_file"] = str(identity_path)
                static_profile["ssh"]["known_hosts_file"] = str(known_hosts_path)
                static_profile["profile_payload_sha256"] = ""
                static_profile["profile_payload_sha256"] = W5.digest(static_profile)
                static_argv = W5.build_controller_argv(W5.canonical_bytes(static_profile))
                expanded = subprocess.run(
                    [static_argv[0], "-G", *static_argv[1:]],
                    cwd="/",
                    env={
                        "LANG": "C",
                        "LC_ALL": "C",
                        "HOME": str(Path(raw) / "poison-home"),
                        "SSH_AUTH_SOCK": str(Path(raw) / "poison-agent"),
                        "SSH_SK_PROVIDER": str(Path(raw) / "poison-sk-provider"),
                    },
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                self.assertEqual(expanded.returncode, 0, expanded.stderr)
                self.assertEqual(expanded.stderr, "")
                effective: dict[str, list[str]] = {}
                for line in expanded.stdout.splitlines():
                    key, separator, value = line.partition(" ")
                    if separator:
                        effective.setdefault(key, []).append(value)
                self.assertEqual(effective["globalknownhostsfile"], ["none"])
                self.assertEqual(effective["userknownhostsfile"], [str(known_hosts_path)])
                self.assertEqual(effective["stricthostkeychecking"], ["true"])
                self.assertEqual(effective["verifyhostkeydns"], ["false"])
                self.assertEqual(effective["updatehostkeys"], ["false"])
                self.assertEqual(effective["identityagent"], ["none"])
                self.assertEqual(effective["identityfile"], ["none", str(identity_path)])
                self.assertEqual(effective["certificatefile"], ["none"])
                self.assertNotIn("knownhostscommand", effective)
                self.assertNotIn("pkcs11provider", effective)
                self.assertNotIn("securitykeyprovider", effective)
                self.assertNotIn("/etc/ssh/ssh_known_hosts", expanded.stdout)
                self.assertNotIn("~/.ssh/id_", expanded.stdout)

                for field, replacement in (
                    (("ssh", "host"), "other.invalid"),
                    (("ssh", "user"), "other"),
                    (("ssh", "port"), "2222"),
                    (("ssh", "subsystem"), "other"),
                    (("server", "allowed_root"), "/home/user100/SDL"),
                ):
                    hostile = copy.deepcopy(profile)
                    hostile[field[0]][field[1]] = replacement
                    with self.assertRaises(W5.DirectOneHopTransportError):
                        W5.validate_transport_profile(hostile)

                extra_source = copy.deepcopy(profile)
                extra_source["ssh"]["global_known_hosts_file"] = "/etc/ssh/ssh_known_hosts"
                extra_source["profile_payload_sha256"] = ""
                extra_source["profile_payload_sha256"] = W5.digest(extra_source)
                with self.assertRaisesRegex(W5.DirectOneHopTransportError, "SSH profile fields differ"):
                    W5.validate_transport_profile(extra_source)

                poison = copy.deepcopy(profile)
                poison["ssh"]["host"] = "proxy-poison.invalid"
                poison["profile_payload_sha256"] = ""
                poison["profile_payload_sha256"] = W5.digest(poison)
                hostile_artifacts = SESSION.DirectServerSessionArtifacts(
                    **{
                        **{name: getattr(fixture.artifacts, name) for name in fixture.artifacts.__dataclass_fields__},
                        "transport_profile": W5.canonical_bytes(poison),
                    }
                )
                with self.assertRaisesRegex(W5.DirectOneHopTransportError, "transport identity"):
                    W5._validate_controller_artifact_join(hostile_artifacts)

                poisoned_evidence = json.loads(fixture.artifacts.ssh_system_policy_evidence)
                for field, replacement in (
                    ("configuration_files_read", True),
                    ("global_known_hosts_file", "/etc/ssh/ssh_known_hosts"),
                    ("user_known_hosts_file", "/tmp/caller-known-hosts"),
                    ("identity_agent", "SSH_AUTH_SOCK"),
                ):
                    with self.subTest(evidence_field=field):
                        hostile_evidence = copy.deepcopy(poisoned_evidence)
                        hostile_evidence[field] = replacement
                        evidence_artifacts = SESSION.DirectServerSessionArtifacts(
                            **{
                                **{
                                    name: getattr(fixture.artifacts, name)
                                    for name in fixture.artifacts.__dataclass_fields__
                                },
                                "ssh_system_policy_evidence": W5.canonical_bytes(hostile_evidence),
                            }
                        )
                        with self.assertRaisesRegex(
                            W5.DirectOneHopTransportError,
                            "system-policy evidence|configuration-file",
                        ):
                            W5._validate_controller_artifact_join(evidence_artifacts)
            finally:
                fixture.close()

    def test_reviewed_pbs_bytes_are_uploaded_without_generation_or_legacy_call(self) -> None:
        source = (SCRIPTS / "direct_one_hop_transport.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        self.assertFalse(any(isinstance(node, ast.FunctionDef) and node.name == "_pbs_bytes" for node in ast.walk(tree)))
        self.assertNotIn("legacy_rtwin_pbs", source)
        self.assertNotIn("rtwin_sha256", source)
        with tempfile.TemporaryDirectory(prefix="auto-g16-w5-pbs-review-") as raw:
            fixture = PortableSessionFixture(Path(raw).resolve())
            try:
                hostile_review = json.loads(fixture.artifacts.pbs_review)
                hostile_review["workspace"]["allowed_root"] = "/home/user100/SDL"
                hostile_review["review_payload_sha256"] = "f" * 64
                fixture.artifacts = SESSION.DirectServerSessionArtifacts(
                    **{
                        **{
                            name: getattr(fixture.artifacts, name)
                            for name in fixture.artifacts.__dataclass_fields__
                        },
                        "pbs_review": W5.canonical_bytes(hostile_review),
                    }
                )
                seam = self.seam(fixture)
                binding = seam.direct_binding
                journal_id = seam.durable_claim.journal_id
                driver = W5._test_driver(stdout=b"1.master\n")
                with self.assertRaises(W5.DirectOneHopTransportError):
                    W5._consume_with_test_driver_once(seam, driver, _test_token=W5._TEST_DRIVER_TOKEN)
                self.assertEqual(driver.calls, 0)
                snapshot = W2.reconcile_read_only(fixture.state, journal_id, binding).document()
                self.assertEqual(snapshot["effective_outcome"], "unknown")
            finally:
                fixture.close()

    def test_descriptor_relative_upload_partial_preexist_symlink_and_fd_drift(self) -> None:
        with tempfile.TemporaryDirectory(prefix="auto-g16-w5-upload-") as raw:
            root = Path(raw)
            descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                original_write = os.write

                def partial(fd: int, data: bytes) -> int:
                    return original_write(fd, data[: max(1, len(data) // 3)])

                with mock.patch.object(W5.os, "write", side_effect=partial):
                    W5._write_new_file(descriptor, W5.INPUT_BASENAME, b"exact-reviewed-input")
                self.assertEqual((root / W5.INPUT_BASENAME).read_bytes(), b"exact-reviewed-input")
                before = (root / W5.INPUT_BASENAME).read_bytes()
                with self.assertRaises(FileExistsError):
                    W5._write_new_file(descriptor, W5.INPUT_BASENAME, b"replacement")
                self.assertEqual((root / W5.INPUT_BASENAME).read_bytes(), before)

                (root / W5.PBS_BASENAME).symlink_to(root / W5.INPUT_BASENAME)
                with self.assertRaises(FileExistsError):
                    W5._write_new_file(descriptor, W5.PBS_BASENAME, b"script")
                self.assertTrue((root / W5.PBS_BASENAME).is_symlink())

                identities = [W5._fd_identity(descriptor), (999,) * 5]
                with mock.patch.object(W5, "_fd_identity", side_effect=identities):
                    with self.assertRaisesRegex(W5.DirectOneHopTransportError, "FD identity drifted"):
                        W5._write_new_file(descriptor, W5.CHECKSUMS_BASENAME, b"checksum")
            finally:
                os.close(descriptor)

    def test_fake_driver_and_module_rebinding_cannot_become_production_authority(self) -> None:
        driver = W5._test_driver(stdout=b"1.master\n")
        with self.assertRaises(W5.DirectOneHopTransportError):
            W5.consume_production_once(driver)  # type: ignore[arg-type]
        with mock.patch.object(W5, "_production_qsub_once", return_value=driver._observation):
            with self.assertRaisesRegex(W5.DirectOneHopTransportError, "production transport source"):
                W5.consume_production_once(object())  # type: ignore[arg-type]
        with mock.patch.object(W5, "_validate_controller_response", return_value={}):
            with self.assertRaisesRegex(W5.DirectOneHopTransportError, "production transport source"):
                W5.run_controller_once(object())  # type: ignore[arg-type]
        with mock.patch.object(W5, "_write_controller_frame_until", return_value=None):
            with self.assertRaisesRegex(W5.DirectOneHopTransportError, "production transport source"):
                W5.run_controller_once(object())  # type: ignore[arg-type]
        with mock.patch.object(W5, "CONTROLLER_WRITE_TIMEOUT_SECONDS", 0.01):
            with self.assertRaisesRegex(W5.DirectOneHopTransportError, "production transport source"):
                W5.run_controller_once(object())  # type: ignore[arg-type]
        with mock.patch.object(W5.SESSION, "validate_trusted_session_result", return_value={}):
            with self.assertRaisesRegex(W5.DirectOneHopTransportError, "production transport source"):
                W5.run_controller_once(object())  # type: ignore[arg-type]
        self.assertEqual(driver.calls, 0)

    def test_concurrent_duplicate_and_restart_are_reconciliation_only_with_at_most_one_call(self) -> None:
        with tempfile.TemporaryDirectory(prefix="auto-g16-w5-concurrent-") as raw:
            fixture = PortableSessionFixture(Path(raw).resolve())
            try:
                seam = self.seam(fixture)
                binding = seam.direct_binding
                journal_id = seam.durable_claim.journal_id
                driver = W5._test_driver(stdout=b"991.master\n")

                def consume() -> object:
                    try:
                        return W5._consume_with_test_driver_once(
                            seam,
                            driver,
                            _test_token=W5._TEST_DRIVER_TOKEN,
                        )
                    except BaseException as exc:
                        return exc

                with ThreadPoolExecutor(max_workers=2) as pool:
                    outcomes = list(pool.map(lambda _index: consume(), range(2)))
                self.assertLessEqual(driver.calls, 1)
                self.assertTrue(any(isinstance(item, BaseException) for item in outcomes))
                snapshot = W2.reconcile_read_only(fixture.state, journal_id, binding).document()
                self.assertIn(snapshot["effective_outcome"], {"completed", "unknown"})
                self.assertFalse(snapshot["reconciliation"]["second_effect_allowed"])

                restart_driver = W5._test_driver(stdout=b"992.master\n")
                with self.assertRaises(BaseException):
                    W5._consume_with_test_driver_once(
                        seam,
                        restart_driver,
                        _test_token=W5._TEST_DRIVER_TOKEN,
                    )
                self.assertEqual(restart_driver.calls, 0)
            finally:
                fixture.close()

    def test_reviewed_executable_fd_hash_identity_replacement_and_no_path_exec_fallback(self) -> None:
        with tempfile.TemporaryDirectory(prefix="auto-g16-w5-executable-") as raw:
            path = Path(raw) / "fake-ssh"
            path.write_bytes(b"#!/bin/false\nreviewed\n")
            path.chmod(0o700)
            expected = __import__("hashlib").sha256(path.read_bytes()).hexdigest()
            descriptor = W5._open_reviewed_executable(str(path), expected)
            try:
                self.assertFalse(os.get_inheritable(descriptor))
                W5._assert_reviewed_executable_descriptor(descriptor, str(path), expected)
                replacement = Path(raw) / "replacement"
                replacement.write_bytes(b"#!/bin/false\nreplacement\n")
                replacement.chmod(0o700)
                os.replace(replacement, path)
                with self.assertRaisesRegex(W5.DirectOneHopTransportError, "identity or hash differs"):
                    W5._assert_reviewed_executable_descriptor(descriptor, str(path), expected)
            finally:
                os.close(descriptor)
        source = (SCRIPTS / "direct_one_hop_transport.py").read_text(encoding="utf-8")
        self.assertNotIn("_FROZEN_EXECVE(SSH_EXECUTABLE", source)
        self.assertNotIn("_FROZEN_EXECVE(QSUB_EXECUTABLE", source)
        if os.execve not in os.supports_fd and not Path("/proc/self/fd").is_dir():
            with self.assertRaisesRegex(W5.DirectOneHopTransportError, "path fallback forbidden"):
                W5._require_descriptor_exec_available()
        read_fd, write_fd = W5._pipe_cloexec()
        try:
            self.assertFalse(os.get_inheritable(read_fd))
            self.assertFalse(os.get_inheritable(write_fd))
        finally:
            os.close(read_fd)
            os.close(write_fd)

    def test_qsub_parent_fault_and_oversize_use_nonblocking_observation_without_kill(self) -> None:
        with tempfile.TemporaryDirectory(prefix="auto-g16-w5-qsub-parent-") as raw:
            descriptor = os.open(raw, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                fake_executable = os.open("/bin/sh", os.O_RDONLY)
                with mock.patch.object(W5, "_require_descriptor_exec_available", return_value=None), \
                        mock.patch.object(W5, "_open_reviewed_executable", return_value=fake_executable), \
                        mock.patch.object(W5, "_FROZEN_FORK", return_value=424242), \
                        mock.patch.object(W5.select, "select", side_effect=OSError("parent read failed")), \
                        mock.patch.object(W5.os, "waitpid", return_value=(0, 0)) as waitpid, \
                        mock.patch.object(W5.os, "kill") as kill:
                    observation = W5._production_qsub_once(descriptor, "a" * 64)
                self.assertTrue(observation.uncertain)
                self.assertIsNone(observation.returncode)
                waitpid.assert_called_once_with(424242, os.WNOHANG)
                kill.assert_not_called()
            finally:
                os.close(descriptor)

    def test_controller_frame_deadline_extra_bytes_partial_close_and_bounded_exit(self) -> None:
        payload = W5.canonical_bytes({"protocol": W5.PROTOCOL, "status": "fixture"})
        frame = struct.pack("!I", len(payload)) + payload

        read_fd, write_fd = os.pipe()
        try:
            os.write(write_fd, frame + b"x")
            os.close(write_fd)
            write_fd = -1
            with self.assertRaisesRegex(W5.DirectOneHopTransportError, "extra bytes|second frame"):
                W5._read_framed_descriptor(read_fd, 0.5)
        finally:
            os.close(read_fd)
            if write_fd >= 0:
                os.close(write_fd)

        read_fd, write_fd = os.pipe()
        failures: list[BaseException] = []

        def slow_writer() -> None:
            try:
                for byte in frame:
                    os.write(write_fd, bytes((byte,)))
                    threading.Event().wait(0.01)
            except BaseException as exc:  # deterministic broken pipe after timeout
                failures.append(exc)
            finally:
                try:
                    os.close(write_fd)
                except OSError:
                    pass

        thread = threading.Thread(target=slow_writer)
        thread.start()
        try:
            with self.assertRaises(W5.ControllerTransportUnknown):
                W5._read_framed_descriptor(read_fd, 0.03)
        finally:
            os.close(read_fd)
            thread.join(timeout=1)
        self.assertFalse(thread.is_alive())

        with mock.patch.object(W5.CHANNEL, "_write_frame_until") as writer, \
                mock.patch.object(W5.os, "close", side_effect=OSError("close after full frame")):
            with self.assertRaises(W5.ControllerTransportUnknown):
                W5._send_controller_request(91, frame, 123.0)
        writer.assert_called_once_with(91, frame, 123.0)

        with mock.patch.object(W5.os, "waitpid", side_effect=[(0, 0), (777, 0)]) as waitpid, \
                mock.patch.object(W5.select, "select", return_value=([], [], [])):
            self.assertEqual(W5._wait_child_bounded(777, 0.5), 0)
        self.assertEqual(waitpid.call_count, 2)

    def test_controller_request_write_is_nonblocking_single_deadline_and_no_signal(self) -> None:
        payload = b"x" * (1024 * 1024)

        read_fd, write_fd = os.pipe()
        started = time.monotonic()
        try:
            with mock.patch.object(W5.os, "kill") as kill:
                with self.assertRaises(W5.ControllerTransportUnknown):
                    W5._send_controller_request(write_fd, payload, started + 0.15)
                kill.assert_not_called()
        finally:
            if write_fd >= 0:
                os.close(write_fd)
            os.close(read_fd)
        self.assertLess(time.monotonic() - started, 1.0)

        read_fd, write_fd = os.pipe()
        made_partial_progress = threading.Event()

        def read_once() -> None:
            os.read(read_fd, 4096)
            made_partial_progress.set()

        thread = threading.Thread(target=read_once)
        thread.start()
        started = time.monotonic()
        try:
            with self.assertRaises(W5.ControllerTransportUnknown):
                W5._send_controller_request(write_fd, payload, started + 0.15)
        finally:
            if write_fd >= 0:
                os.close(write_fd)
            os.close(read_fd)
            thread.join(timeout=1)
        self.assertTrue(made_partial_progress.is_set())
        self.assertFalse(thread.is_alive())
        self.assertLess(time.monotonic() - started, 1.0)

        read_fd, write_fd = os.pipe()
        os.close(read_fd)
        try:
            with self.assertRaises(W5.ControllerTransportUnknown):
                W5._send_controller_request(write_fd, b"peer-close", time.monotonic() + 0.5)
        finally:
            if write_fd >= 0:
                os.close(write_fd)

        read_fd, write_fd = os.pipe()
        received = bytearray()

        def drain() -> None:
            while True:
                chunk = os.read(read_fd, 65536)
                if not chunk:
                    return
                received.extend(chunk)

        thread = threading.Thread(target=drain)
        thread.start()
        try:
            W5._send_controller_request(write_fd, payload, time.monotonic() + 1.0)
            write_fd = -1
            thread.join(timeout=1)
        finally:
            if write_fd >= 0:
                os.close(write_fd)
            os.close(read_fd)
        self.assertFalse(thread.is_alive())
        self.assertEqual(bytes(received), payload)

        observed_timeouts: list[float] = []

        def always_writable(
            _readers: list[int], writers: list[int], _exceptional: list[int], timeout: float
        ) -> tuple[list[int], list[int], list[int]]:
            observed_timeouts.append(timeout)
            return [], writers, []

        with mock.patch.object(W5.fcntl, "fcntl", side_effect=[0, None, os.O_NONBLOCK]), \
                mock.patch.object(W5.time, "monotonic", side_effect=[1.0, 2.0, 3.0, 4.0]), \
                mock.patch.object(W5.select, "select", side_effect=always_writable), \
                mock.patch.object(W5.os, "write", return_value=1):
            with self.assertRaisesRegex(W5.ControllerTransportUnknown, "timed out"):
                W5._write_controller_frame_until(91, b"four", 3.5)
        self.assertEqual(observed_timeouts, [2.5, 1.5, 0.5])

        with mock.patch.object(
            W5.CHANNEL,
            "_wait_child_until",
            side_effect=W5.ControllerTransportUnknown("still running"),
        ) as waiter, mock.patch.object(W5.os, "kill") as kill:
            self.assertFalse(W5._retire_controller_child_bounded(777))
        waiter.assert_called_once()
        self.assertEqual(waiter.call_args.args[0], 777)
        kill.assert_not_called()

        artifacts = object.__new__(SESSION.DirectServerSessionArtifacts)
        object.__setattr__(artifacts, "transport_profile", b"fixture")
        profile = {"profile_payload_sha256": "a" * 64}
        operation = object()
        with mock.patch.object(W5, "_assert_production_binding"), \
                mock.patch.object(W5, "_validate_controller_artifact_join", return_value=profile), \
                mock.patch.object(W5, "_issue_controller_request_join", return_value=object()), \
                mock.patch.object(W5, "_artifact_frame", return_value=b"frame"), \
                mock.patch.object(W5.CHANNEL, "issue_submit_channel_operation", return_value=operation) as issue, \
                mock.patch.object(W5.CHANNEL, "run_submit_channel_once", side_effect=W5.ControllerTransportUnknown("reconciliation only")) as run, \
                mock.patch.object(W5, "_retire_controller_request_join") as retire_join:
            with self.assertRaisesRegex(W5.ControllerTransportUnknown, "reconciliation only"):
                W5.run_controller_once(artifacts)
        issue.assert_called_once_with(b"fixture", mock.ANY, b"frame")
        run.assert_called_once_with(operation, b"frame")
        retire_join.assert_called_once()


if __name__ == "__main__":
    unittest.main()
