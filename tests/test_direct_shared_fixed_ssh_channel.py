#!/usr/bin/env python3
"""Offline hostile tests for the sole shared fixed-SSH channel owner."""

from __future__ import annotations

import ast
import base64
import copy
import dataclasses
import gc
import hashlib
import importlib
import json
import os
import pickle
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import weakref
from pathlib import Path
from unittest import mock

from tests.test_direct_trusted_session_composition import PortableSessionFixture


ROOT = Path(__file__).parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import direct_one_hop_transport as W5  # noqa: E402
import direct_shared_fixed_ssh_channel as CHANNEL  # noqa: E402


def buffered_fetch_response(descriptor, operation, deadline):
    return CHANNEL._read_fetch_response_buffered_for_tests_until(
        descriptor,
        operation,
        deadline,
        _test_token=CHANNEL._FETCH_BUFFER_TEST_TOKEN,
    )


class DirectSharedFixedSSHChannelTests(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="auto-g16-shared-channel-")
        self.fixture = PortableSessionFixture(Path(self.temporary.name).resolve())
        self.transport_raw = self.fixture.artifacts.transport_profile
        self.transport = CHANNEL.load_transport_profile(self.transport_raw)
        self.read_profile = {
            "schema": CHANNEL.READ_PROFILE_SCHEMA,
            "profile_id": "fixture-read-profile",
            "transport_binding": {
                "schema": "exact_w5_transport_profile_bytes/1",
                "transport_profile_bytes_sha256": hashlib.sha256(self.transport_raw).hexdigest(),
                "transport_profile_payload_sha256": self.transport["profile_payload_sha256"],
            },
            "server_read": {
                "source_sha256": CHANNEL._EXECUTED_SOURCE_SHA256,
                "qstat": {
                    "executable": "/usr/bin/qstat",
                    "executable_sha256": "a" * 64,
                    "executable_owner_uid": "0",
                    "executable_mode": "0755",
                    "max_stdout_bytes": "65536",
                    "timeout_seconds": "30",
                },
                "fetch": {
                    "max_total_bytes": "1048576",
                    "max_chunk_bytes": "65536",
                    "max_chunks": "64",
                    "timeout_seconds": "30",
                },
            },
            "safety": copy.deepcopy(CHANNEL.READ_POLICY),
            "read_profile_payload_sha256": "",
        }
        self.read_profile["read_profile_payload_sha256"] = CHANNEL.digest(self.read_profile)
        self.read_profile_raw = CHANNEL.canonical_bytes(self.read_profile)

    def tearDown(self) -> None:
        self.fixture.close()
        self.temporary.cleanup()

    @staticmethod
    def framed(value: dict[str, object]) -> bytes:
        payload = CHANNEL.canonical_bytes(value)
        return struct.pack("!I", len(payload)) + payload

    def submit_operation(self) -> CHANNEL.SubmitChannelOperation:
        operation, _frame = self.submit_operation_with_frame()
        return operation

    def submit_operation_with_frame(self) -> tuple[CHANNEL.SubmitChannelOperation, bytes]:
        join = W5._issue_controller_request_join(self.fixture.artifacts)
        try:
            frame = W5._artifact_frame(self.fixture.artifacts, join)
            return CHANNEL.issue_submit_channel_operation(self.transport_raw, join, frame), frame
        finally:
            W5._retire_controller_request_join(join)

    def query_operation(self, job_id: str = "123.master") -> CHANNEL.QueryExactJobOperation:
        return CHANNEL._issue_query_exact_job_operation_for_testing(
            self.transport_raw,
            self.read_profile_raw,
            job_id,
            _test_token=CHANNEL._QUERY_CODEC_TEST_TOKEN,
        )

    @staticmethod
    def through_pipe(payload: bytes, reader: object) -> object:
        read_fd, write_fd = os.pipe()
        try:
            os.write(write_fd, payload)
            os.close(write_fd)
            write_fd = -1
            return reader(read_fd)
        finally:
            os.close(read_fd)
            if write_fd >= 0:
                os.close(write_fd)

    def query_response(self, operation: CHANNEL.QueryExactJobOperation, raw: bytes = b"123.master\n R queue\n") -> dict[str, object]:
        value: dict[str, object] = {
            "protocol": CHANNEL.READ_PROTOCOL,
            "status": "completed",
            "operation_id": operation.operation_id,
            "job_id": "123.master",
            "qstat_stdout_base64": base64.b64encode(raw).decode("ascii"),
            "qstat_stdout_sha256": hashlib.sha256(raw).hexdigest(),
            "authority": {"authorizes_effect": False, "qsub_calls": "0"},
            "response_payload_sha256": "",
        }
        value["response_payload_sha256"] = CHANNEL.digest(value)
        return value

    def fetch_stream(self, operation: CHANNEL.FetchTerminalMinimumBundleOperation, chunks: tuple[bytes, ...]) -> bytes:
        bundle = b"".join(chunks)
        header = {
            "protocol": CHANNEL.READ_PROTOCOL,
            "status": "streaming_terminal_minimum_bundle",
            "operation_id": operation.operation_id,
            "job_id": "123.master",
            "chunk_count": str(len(chunks)),
            "total_size_bytes": str(len(bundle)),
            "bundle_commitment_sha256": hashlib.sha256(
                b"commitment:" + bundle
            ).hexdigest(),
            "authority": {"authorizes_effect": False, "qsub_calls": "0"},
        }
        trailer: dict[str, object] = {
            "protocol": CHANNEL.READ_PROTOCOL,
            "status": "completed",
            "operation_id": operation.operation_id,
            "job_id": "123.master",
            "chunk_count": str(len(chunks)),
            "total_size_bytes": str(len(bundle)),
            "bundle_commitment_sha256": header[
                "bundle_commitment_sha256"
            ],
            "bundle_sha256": hashlib.sha256(bundle).hexdigest(),
            "authority": {"authorizes_effect": False, "qsub_calls": "0"},
            "trailer_payload_sha256": "",
        }
        trailer["trailer_payload_sha256"] = CHANNEL.digest(trailer)
        return self.framed(header) + b"".join(struct.pack("!I", len(chunk)) + chunk for chunk in chunks) + self.framed(trailer)

    def test_profiles_bind_exact_w5_bytes_without_copying_transport_identity(self) -> None:
        validated = CHANNEL.load_read_profile(self.read_profile_raw, self.transport_raw)
        self.assertEqual(validated, self.read_profile)
        text = self.read_profile_raw.decode("utf-8")
        for forbidden in (
            self.transport["ssh"]["host"],
            self.transport["ssh"]["user"],
            self.transport["ssh"]["identity_file"],
            self.transport["ssh"]["known_hosts_file"],
        ):
            self.assertNotIn(forbidden, text)

        hostile_transport = copy.deepcopy(self.transport)
        hostile_transport["profile_id"] += "-other"
        hostile_transport["profile_payload_sha256"] = ""
        hostile_transport["profile_payload_sha256"] = CHANNEL.digest(hostile_transport)
        hostile_raw = CHANNEL.canonical_bytes(hostile_transport)
        with self.assertRaisesRegex(CHANNEL.SharedFixedSSHChannelError, "exact W5 transport-profile bytes"):
            CHANNEL.load_read_profile(self.read_profile_raw, hostile_raw)

        for path, value in (
            (("server_read", "source_sha256"), "b" * 64),
            (("server_read", "qstat", "executable_owner_uid"), "501"),
            (("server_read", "qstat", "executable_mode"), "0555"),
            (("server_read", "qstat", "max_stdout_bytes"), "0"),
            (("server_read", "fetch", "max_chunk_bytes"), "4194305"),
            (("server_read", "fetch", "max_total_bytes"), "1092943960"),
            (("safety", "authorizes_effect"), True),
        ):
            with self.subTest(path=path):
                hostile = copy.deepcopy(self.read_profile)
                target: object = hostile
                for component in path[:-1]:
                    target = target[component]  # type: ignore[index]
                target[path[-1]] = value  # type: ignore[index]
                hostile["read_profile_payload_sha256"] = ""
                hostile["read_profile_payload_sha256"] = CHANNEL.digest(hostile)
                with self.assertRaises(CHANNEL.SharedFixedSSHChannelError):
                    CHANNEL.validate_read_profile(hostile, self.transport_raw)

    def test_operations_are_exact_sealed_nonportable_and_cross_splice_closed(self) -> None:
        submit = self.submit_operation()
        query = self.query_operation()
        fetch = CHANNEL._issue_fetch_terminal_minimum_bundle_operation_for_testing(self.transport_raw, self.read_profile_raw, "123.master")
        self.assertIs(type(submit), CHANNEL.SubmitChannelOperation)
        self.assertIs(type(query), CHANNEL.QueryExactJobOperation)
        self.assertIs(type(fetch), CHANNEL.FetchTerminalMinimumBundleOperation)
        for operation in (submit, query, fetch):
            operation.assert_owner_sealed()
            projection = operation.portable_projection()
            self.assertFalse(projection["authority"]["authorizes_effect"])
            for transform in (copy.copy, copy.deepcopy, pickle.dumps):
                with self.assertRaises(TypeError):
                    transform(operation)
        submit_projection = submit.portable_projection()
        self.assertRegex(
            submit_projection["submit_request_id"],
            r"^direct-controller-request-[a-f0-9]{64}$",
        )
        self.assertRegex(submit_projection["submit_request_frame_sha256"], r"^[a-f0-9]{64}$")

        forged = object.__new__(CHANNEL.QueryExactJobOperation)
        forged.operation_id = query.operation_id
        forged._seal = query._seal
        with self.assertRaisesRegex(CHANNEL.SharedFixedSSHChannelError, "foreign, forged"):
            forged.assert_owner_sealed()
        with self.assertRaises(CHANNEL.SharedFixedSSHChannelError):
            CHANNEL.issue_submit_channel_operation(self.transport_raw, object(), self.framed({"invalid": True}))
        driver = W5._test_driver(stdout=b"999.master\n")
        with self.assertRaises(CHANNEL.SharedFixedSSHChannelError):
            CHANNEL.issue_submit_channel_operation(
                self.transport_raw,
                submit.portable_projection(),
                self.framed({"invalid": True}),
            )
        self.assertEqual(driver.calls, 0)

        one_use_join = W5._issue_controller_request_join(self.fixture.artifacts)
        one_use_frame = W5._artifact_frame(self.fixture.artifacts, one_use_join)
        try:
            CHANNEL.issue_submit_channel_operation(self.transport_raw, one_use_join, one_use_frame)
            with self.assertRaisesRegex(CHANNEL.SharedFixedSSHChannelError, "stale, foreign, or cross-spliced"):
                CHANNEL.issue_submit_channel_operation(self.transport_raw, one_use_join, one_use_frame)
        finally:
            W5._retire_controller_request_join(one_use_join)
        with self.assertRaises(CHANNEL.SharedFixedSSHChannelError):
            CHANNEL.issue_submit_channel_operation(self.transport_raw, one_use_join, one_use_frame)

        other_transport = copy.deepcopy(self.transport)
        other_transport["profile_id"] += "-foreign-artifact"
        other_transport["profile_payload_sha256"] = ""
        other_transport["profile_payload_sha256"] = CHANNEL.digest(other_transport)
        foreign_artifacts = W5.SESSION.DirectServerSessionArtifacts(
            **{
                **{
                    name: getattr(self.fixture.artifacts, name)
                    for name in self.fixture.artifacts.__dataclass_fields__
                },
                "transport_profile": CHANNEL.canonical_bytes(other_transport),
            }
        )
        foreign_join = W5._issue_controller_request_join(foreign_artifacts)
        foreign_frame = W5._artifact_frame(foreign_artifacts, foreign_join)
        try:
            with self.assertRaisesRegex(CHANNEL.SharedFixedSSHChannelError, "cross-spliced"):
                CHANNEL.issue_submit_channel_operation(self.transport_raw, foreign_join, foreign_frame)
        finally:
            W5._retire_controller_request_join(foreign_join)
        query_argv = CHANNEL.build_controller_argv(self.transport_raw, query)
        self.assertEqual(query_argv[-1], CHANNEL.READ_SUBSYSTEM)
        with self.assertRaisesRegex(CHANNEL.SharedFixedSSHChannelError, "exact SubmitChannelOperation"):
            CHANNEL.run_submit_channel_once(query, b"not-a-frame")  # type: ignore[arg-type]

        other = copy.deepcopy(self.transport)
        other["profile_id"] += "-cross-splice"
        other["profile_payload_sha256"] = ""
        other["profile_payload_sha256"] = CHANNEL.digest(other)
        with self.assertRaisesRegex(CHANNEL.SharedFixedSSHChannelError, "cross-splice"):
            CHANNEL.build_controller_argv(CHANNEL.canonical_bytes(other), submit)

        self.assertEqual(query.portable_projection()["authority"]["qsub_calls"], "0")
        self.assertEqual(fetch.portable_projection()["authority"]["qsub_calls"], "0")
        query_projection = CHANNEL.project_query_request_frame_for_review(query)
        fetch_projection = CHANNEL.project_fetch_request_frame_for_review(fetch)
        self.assertEqual(query_projection, CHANNEL.project_query_request_frame_for_review(query))
        self.assertEqual(fetch_projection, CHANNEL.project_fetch_request_frame_for_review(fetch))
        self.assertNotIn("qsub", query_projection.decode("utf-8").replace('"qsub_calls"', ""))
        self.assertNotIn("qsub", fetch_projection.decode("utf-8").replace('"qsub_calls"', ""))

    def test_generic_submit_bypass_and_live_mutable_record_are_absent(self) -> None:
        self.assertFalse(hasattr(CHANNEL, "_issue_operation"))
        self.assertFalse(hasattr(CHANNEL, "_operation_record"))
        self.assertFalse(hasattr(CHANNEL, "_OPERATION_REGISTRY"))
        source = (SCRIPTS / "direct_shared_fixed_ssh_channel.py").read_text(encoding="utf-8")
        definitions = {
            node.name
            for node in ast.walk(ast.parse(source))
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        self.assertNotIn("_issue_operation", definitions)

        operation, approved_frame = self.submit_operation_with_frame()
        alternate_owner = CHANNEL._make_operation_owner()
        direct_submit_issuer = alternate_owner[0]
        driver = W5._test_driver(stdout=b"999.master\n")
        with self.assertRaises(CHANNEL.SharedFixedSSHChannelError):
            direct_submit_issuer(
                self.transport_raw,
                operation.portable_projection(),
                approved_frame,
            )
        self.assertEqual(driver.calls, 0)

        query = self.query_operation()
        original = query.portable_projection()
        hostile = query.portable_projection()
        hostile["submit_request_frame_sha256"] = "f" * 64
        hostile["status"] = "running"
        hostile["job_id"] = "999.master"
        hostile["read_profile_payload_sha256"] = "e" * 64
        hostile["transport_profile_bytes_sha256"] = "d" * 64
        self.assertEqual(query.portable_projection(), original)
        self.assertNotIn("status", query.portable_projection())
        self.assertNotIn("transport_profile_raw", query.portable_projection())
        self.assertNotIn("read_profile_raw", query.portable_projection())
        projected = json.loads(
            CHANNEL.project_query_request_frame_for_review(query)[4:].decode("utf-8")
        )
        self.assertEqual(projected["job_id"], "123.master")

        snapshot = CHANNEL._operation_snapshot(
            query,
            CHANNEL.QueryExactJobOperation,
            {"issued"},
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            snapshot.job_id = "999.master"  # type: ignore[misc]
        object.__setattr__(snapshot, "job_id", "999.master")
        self.assertEqual(
            json.loads(CHANNEL.project_query_request_frame_for_review(query)[4:])["job_id"],
            "123.master",
        )

    def test_query_fetch_exact_type_gates_are_before_io_and_old_builders_are_absent(self) -> None:
        query = self.query_operation()
        fetch = CHANNEL._issue_fetch_terminal_minimum_bundle_operation_for_testing(
            self.transport_raw,
            self.read_profile_raw,
            "123.master",
        )
        self.assertFalse(hasattr(CHANNEL, "build_query_request_frame"))
        self.assertFalse(hasattr(CHANNEL, "build_fetch_request_frame"))
        self.assertFalse(hasattr(CHANNEL, "validate_query_response"))
        with self.assertRaisesRegex(CHANNEL.SharedFixedSSHChannelError, "exact Query"):
            CHANNEL.project_query_request_frame_for_review(fetch)  # type: ignore[arg-type]
        with self.assertRaisesRegex(CHANNEL.SharedFixedSSHChannelError, "exact Fetch"):
            CHANNEL.project_fetch_request_frame_for_review(query)  # type: ignore[arg-type]

        query_payload = self.framed(self.query_response(query))
        query_read, query_write = os.pipe()
        try:
            os.write(query_write, query_payload)
            os.close(query_write)
            query_write = -1
            with self.assertRaisesRegex(CHANNEL.SharedFixedSSHChannelError, "exact Query"):
                CHANNEL.read_query_response_until(
                    query_read,
                    fetch,  # type: ignore[arg-type]
                    time.monotonic() + 1.0,
                )
            self.assertEqual(os.read(query_read, len(query_payload)), query_payload)
        finally:
            os.close(query_read)
            if query_write >= 0:
                os.close(query_write)

        fetch_payload = self.fetch_stream(fetch, (b"x",))
        fetch_read, fetch_write = os.pipe()
        try:
            os.write(fetch_write, fetch_payload)
            os.close(fetch_write)
            fetch_write = -1
            with self.assertRaisesRegex(CHANNEL.SharedFixedSSHChannelError, "exact Fetch"):
                buffered_fetch_response(
                    fetch_read,
                    query,  # type: ignore[arg-type]
                    time.monotonic() + 1.0,
                )
            self.assertEqual(os.read(fetch_read, len(fetch_payload)), fetch_payload)
        finally:
            os.close(fetch_read)
            if fetch_write >= 0:
                os.close(fetch_write)

    def test_submit_descriptor_and_fork_failures_are_terminal_without_effect(self) -> None:
        operation, frame = self.submit_operation_with_frame()
        driver = W5._test_driver(stdout=b"999.master\n")
        with mock.patch.object(CHANNEL, "_assert_production_binding"), \
                mock.patch.object(
                    CHANNEL,
                    "_require_descriptor_exec_available",
                    side_effect=CHANNEL.SharedFixedSSHChannelError("descriptor unavailable"),
                ) as descriptor_check, \
                mock.patch.object(CHANNEL, "_FROZEN_FORK") as fork:
            with self.assertRaisesRegex(CHANNEL.SharedFixedSSHChannelError, "descriptor unavailable"):
                CHANNEL.run_submit_channel_once(operation, frame)
            with self.assertRaisesRegex(CHANNEL.SharedFixedSSHChannelError, "terminal"):
                CHANNEL.run_submit_channel_once(operation, frame)
        descriptor_check.assert_called_once_with()
        fork.assert_not_called()
        self.assertEqual(driver.calls, 0)

        fork_operation, fork_frame = self.submit_operation_with_frame()
        with mock.patch.object(CHANNEL, "_assert_production_binding"), \
                mock.patch.object(CHANNEL, "_require_descriptor_exec_available"), \
                mock.patch.object(CHANNEL, "build_controller_argv", return_value=(CHANNEL.SSH_EXECUTABLE,)), \
                mock.patch.object(CHANNEL, "_open_reviewed_executable", return_value=50), \
                mock.patch.object(CHANNEL, "_pipe_cloexec", side_effect=[(10, 11), (12, 13)]), \
                mock.patch.object(CHANNEL, "_FROZEN_FORK", side_effect=OSError("fork failed")), \
                mock.patch.object(CHANNEL, "_close_quiet"):
            with self.assertRaisesRegex(OSError, "fork failed"):
                CHANNEL.run_submit_channel_once(fork_operation, fork_frame)
            with self.assertRaisesRegex(CHANNEL.SharedFixedSSHChannelError, "terminal"):
                CHANNEL.run_submit_channel_once(fork_operation, fork_frame)
        self.assertEqual(driver.calls, 0)

    def test_submit_operation_rejects_cross_request_and_cross_artifact_frames_before_fork(self) -> None:
        _operation, approved_frame = self.submit_operation_with_frame()
        second_join = W5._issue_controller_request_join(self.fixture.artifacts)
        try:
            same_profile_different_nonce = W5._artifact_frame(self.fixture.artifacts, second_join)
        finally:
            W5._retire_controller_request_join(second_join)
        self.assertNotEqual(approved_frame, same_profile_different_nonce)

        different_artifacts = W5.SESSION.DirectServerSessionArtifacts(
            **{
                **{
                    name: getattr(self.fixture.artifacts, name)
                    for name in self.fixture.artifacts.__dataclass_fields__
                },
                "pbs_script": self.fixture.artifacts.pbs_script + b"\n# cross-artifact",
            }
        )
        foreign_join = W5._issue_controller_request_join(different_artifacts)
        try:
            cross_artifact_frame = W5._artifact_frame(different_artifacts, foreign_join)
        finally:
            W5._retire_controller_request_join(foreign_join)

        decoded = json.loads(approved_frame[4:].decode("utf-8"))
        decoded["request_id"] = "direct-controller-request-" + "f" * 64
        recomputed_canonical_frame = self.framed(decoded)
        driver = W5._test_driver(stdout=b"999.master\n")
        attempts = [
            (*self.submit_operation_with_frame(), hostile_frame)
            for hostile_frame in (
                same_profile_different_nonce,
                cross_artifact_frame,
                recomputed_canonical_frame,
            )
        ]
        with mock.patch.object(CHANNEL, "_assert_production_binding"), \
                mock.patch.object(CHANNEL, "_require_descriptor_exec_available") as descriptor_check, \
                mock.patch.object(CHANNEL, "_FROZEN_FORK") as fork:
            for operation, exact_frame, hostile_frame in attempts:
                with self.subTest(frame_sha256=hashlib.sha256(hostile_frame).hexdigest()):
                    with self.assertRaisesRegex(
                        CHANNEL.SharedFixedSSHChannelError,
                        "foreign or cross-spliced",
                    ):
                        CHANNEL.run_submit_channel_once(operation, hostile_frame)
                    with self.assertRaisesRegex(
                        CHANNEL.SharedFixedSSHChannelError,
                        "terminal",
                    ):
                        CHANNEL.run_submit_channel_once(operation, exact_frame)
        descriptor_check.assert_not_called()
        fork.assert_not_called()
        self.assertEqual(driver.calls, 0)

    @unittest.skipUnless(hasattr(os, "fork"), "fork hostile check requires POSIX")
    def test_fork_and_reload_invalidate_existing_operation_identity(self) -> None:
        operation = self.query_operation()
        read_fd, write_fd = os.pipe()
        pid = os.fork()
        if pid == 0:  # pragma: no cover - assertion returned through pipe
            os.close(read_fd)
            try:
                operation.assert_owner_sealed()
                result = b"accepted"
            except BaseException:
                result = b"rejected"
            os.write(write_fd, result)
            os.close(write_fd)
            os._exit(0)
        os.close(write_fd)
        self.assertEqual(os.read(read_fd, 32), b"rejected")
        os.close(read_fd)
        self.assertEqual(os.waitpid(pid, 0)[0], pid)

        encoded_transport = base64.b64encode(self.transport_raw).decode("ascii")
        encoded_read = base64.b64encode(self.read_profile_raw).decode("ascii")
        code = f"""
import base64, importlib, pathlib, sys
sys.path.insert(0, str(pathlib.Path.cwd()))
sys.path.insert(0, str(pathlib.Path.cwd() / 'scripts'))
import direct_shared_fixed_ssh_channel as channel
operation = channel._issue_query_exact_job_operation_for_testing(base64.b64decode('{encoded_transport}'), base64.b64decode('{encoded_read}'), '123.master', _test_token=channel._QUERY_CODEC_TEST_TOKEN)
importlib.reload(channel)
try:
    operation.assert_owner_sealed()
except BaseException:
    raise SystemExit(0)
raise SystemExit(9)
"""
        completed = subprocess.run(
            [sys.executable, "-I", "-S", "-c", code],
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=10,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr.decode("utf-8", "replace"))

        artifacts_payload = json.dumps(
            {
                name: base64.b64encode(getattr(self.fixture.artifacts, name)).decode("ascii")
                for name in self.fixture.artifacts.__dataclass_fields__
            },
            sort_keys=True,
        ).encode("utf-8")
        w5_reload_code = """
import base64, importlib, json, pathlib, sys
sys.path.insert(0, str(pathlib.Path.cwd()))
sys.path.insert(0, str(pathlib.Path.cwd() / 'scripts'))
import direct_one_hop_transport as w5
import direct_shared_fixed_ssh_channel as channel
encoded = json.loads(sys.stdin.buffer.read())
artifacts = w5.SESSION.DirectServerSessionArtifacts(**{name: base64.b64decode(value) for name, value in encoded.items()})
first = w5._issue_controller_request_join(artifacts)
second = w5._issue_controller_request_join(artifacts)
first_frame = w5._artifact_frame(artifacts, first)
second_frame = w5._artifact_frame(artifacts, second)
channel.issue_submit_channel_operation(artifacts.transport_profile, first, first_frame)
importlib.reload(w5)
try:
    channel.issue_submit_channel_operation(artifacts.transport_profile, second, second_frame)
except BaseException:
    raise SystemExit(0)
raise SystemExit(9)
"""
        completed = subprocess.run(
            [sys.executable, "-I", "-S", "-c", w5_reload_code],
            cwd=ROOT,
            input=artifacts_payload,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=30,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr.decode("utf-8", "replace"))

    def test_w5_uses_owner_and_preserves_canonical_submit_wire_and_qsub_contract(self) -> None:
        join = W5._issue_controller_request_join(self.fixture.artifacts)
        try:
            frame = W5._artifact_frame(self.fixture.artifacts, join)
            payload = {
                "protocol": W5.PROTOCOL,
                "operation": "compose_and_submit_once",
                "request_nonce": W5._CONTROLLER_REQUEST_REGISTRY[join]["request_nonce"],
                "request_id": join.request_id,
                "artifacts": {
                    name: base64.b64encode(getattr(self.fixture.artifacts, name)).decode("ascii")
                    for name in self.fixture.artifacts.__dataclass_fields__
                },
            }
            self.assertEqual(frame, struct.pack("!I", len(CHANNEL.canonical_bytes(payload))) + CHANNEL.canonical_bytes(payload))
        finally:
            W5._retire_controller_request_join(join)

        source = (SCRIPTS / "direct_one_hop_transport.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        definitions = {node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
        for moved in (
            "validate_transport_profile", "load_transport_profile", "_pipe_cloexec",
            "_open_reviewed_executable", "_descriptor_execve", "_write_controller_frame_until",
            "_send_controller_request", "_retire_controller_child_bounded",
        ):
            self.assertNotIn(moved, definitions)
        self.assertIn("CHANNEL.issue_submit_channel_operation", source)
        self.assertIn("CHANNEL.run_submit_channel_once", source)
        profile = W5.load_transport_profile(self.fixture.artifacts.transport_profile)
        self.assertEqual(
            profile["qsub"]["argv"],
            [profile["qsub"]["executable"], "--", "auto-g16-job.pbs"],
        )
        self.assertIs(W5.validate_transport_profile, CHANNEL.validate_transport_profile)

        operation, request_frame = self.submit_operation_with_frame()
        with mock.patch.object(CHANNEL, "_assert_production_binding"), \
                mock.patch.object(CHANNEL, "_require_descriptor_exec_available"), \
                mock.patch.object(CHANNEL, "build_controller_argv", return_value=(CHANNEL.SSH_EXECUTABLE,)), \
                mock.patch.object(CHANNEL, "_open_reviewed_executable", return_value=50), \
                mock.patch.object(CHANNEL, "_pipe_cloexec", side_effect=[(10, 11), (12, 13)]), \
                mock.patch.object(CHANNEL, "_FROZEN_FORK", return_value=999), \
                mock.patch.object(CHANNEL, "_close_quiet"), \
                mock.patch.object(CHANNEL.time, "monotonic", side_effect=[100.0, 101.0, 102.0, 103.0]), \
                mock.patch.object(CHANNEL, "_send_frame_until") as sender, \
                mock.patch.object(CHANNEL, "read_single_response_until", return_value={"response": "fixture"}) as reader, \
                mock.patch.object(CHANNEL, "_wait_child_until", return_value=0) as waiter:
            response = CHANNEL.run_submit_channel_once(operation, request_frame)
        self.assertEqual(response, {"response": "fixture"})
        sender.assert_called_once_with(11, request_frame, 131.0)
        reader.assert_called_once_with(12, 132.0)
        waiter.assert_called_once_with(999, 108.0)

    def test_query_is_one_canonical_response_and_all_malformed_boundaries_close(self) -> None:
        operation = self.query_operation()
        response = self.query_response(operation)
        frame = self.framed(response)
        parsed = self.through_pipe(
            frame,
            lambda descriptor: CHANNEL.read_query_response_until(descriptor, operation, time.monotonic() + 1.0),
        )
        self.assertEqual(parsed, response)

        duplicate_read, duplicate_write = os.pipe()
        try:
            os.write(duplicate_write, frame)
            os.close(duplicate_write)
            duplicate_write = -1
            with self.assertRaisesRegex(CHANNEL.SharedFixedSSHChannelError, "terminal"):
                CHANNEL.read_query_response_until(
                    duplicate_read,
                    operation,
                    time.monotonic() + 1.0,
                )
            self.assertEqual(os.read(duplicate_read, len(frame)), frame)
        finally:
            os.close(duplicate_read)
            if duplicate_write >= 0:
                os.close(duplicate_write)

        failed_operation: CHANNEL.QueryExactJobOperation | None = None
        for label in ("zero", "oversize", "truncated", "extra", "second"):
            hostile_operation = self.query_operation()
            hostile_frame = self.framed(self.query_response(hostile_operation))
            hostile = {
                "zero": struct.pack("!I", 0),
                "oversize": struct.pack("!I", CHANNEL.MAX_CONTROL_FRAME_BYTES + 1),
                "truncated": hostile_frame[:-1],
                "extra": hostile_frame + b"x",
                "second": hostile_frame + hostile_frame,
            }[label]
            with self.subTest(label=label, size=len(hostile)):
                with self.assertRaises((CHANNEL.SharedFixedSSHChannelError, CHANNEL.ControllerTransportUnknown)):
                    self.through_pipe(
                        hostile,
                        lambda descriptor: CHANNEL.read_query_response_until(
                            descriptor,
                            hostile_operation,
                            time.monotonic() + 0.5,
                        ),
                    )
            if label == "truncated":
                failed_operation = hostile_operation

        self.assertIsNotNone(failed_operation)
        valid_after_failure = self.framed(self.query_response(failed_operation))
        retry_read, retry_write = os.pipe()
        try:
            os.write(retry_write, valid_after_failure)
            os.close(retry_write)
            retry_write = -1
            with self.assertRaisesRegex(CHANNEL.SharedFixedSSHChannelError, "terminal"):
                CHANNEL.read_query_response_until(
                    retry_read,
                    failed_operation,
                    time.monotonic() + 1.0,
                )
            self.assertEqual(os.read(retry_read, len(valid_after_failure)), valid_after_failure)
        finally:
            os.close(retry_read)
            if retry_write >= 0:
                os.close(retry_write)

        oversized_operation = self.query_operation()
        oversized = self.framed(
            self.query_response(
                oversized_operation,
                b"x" * (int(self.read_profile["server_read"]["qstat"]["max_stdout_bytes"]) + 1),
            )
        )
        with tempfile.TemporaryFile() as oversized_stream:
            oversized_stream.write(oversized)
            oversized_stream.seek(0)
            with self.assertRaises(CHANNEL.SharedFixedSSHChannelError):
                CHANNEL.read_query_response_until(
                    oversized_stream.fileno(),
                    oversized_operation,
                    time.monotonic() + 0.5,
                )

        timeout_operation = self.query_operation()
        timeout_read, timeout_write = os.pipe()
        try:
            with self.assertRaises(CHANNEL.ControllerTransportUnknown):
                CHANNEL.read_query_response_until(
                    timeout_read,
                    timeout_operation,
                    time.monotonic() + 0.01,
                )
        finally:
            os.close(timeout_read)
            os.close(timeout_write)
        timeout_valid = self.framed(self.query_response(timeout_operation))
        timeout_retry_read, timeout_retry_write = os.pipe()
        try:
            os.write(timeout_retry_write, timeout_valid)
            os.close(timeout_retry_write)
            timeout_retry_write = -1
            with self.assertRaisesRegex(CHANNEL.SharedFixedSSHChannelError, "terminal"):
                CHANNEL.read_query_response_until(
                    timeout_retry_read,
                    timeout_operation,
                    time.monotonic() + 1.0,
                )
            self.assertEqual(os.read(timeout_retry_read, len(timeout_valid)), timeout_valid)
        finally:
            os.close(timeout_retry_read)
            if timeout_retry_write >= 0:
                os.close(timeout_retry_write)

        foreign_operation = self.query_operation()
        spliced_operation = self.query_operation()
        foreign_frame = self.framed(self.query_response(foreign_operation))
        with self.assertRaises(CHANNEL.SharedFixedSSHChannelError):
            self.through_pipe(
                foreign_frame,
                lambda descriptor: CHANNEL.read_query_response_until(
                    descriptor,
                    spliced_operation,
                    time.monotonic() + 0.5,
                ),
            )
        foreign_operation.assert_owner_sealed()

    def test_fetch_state_machine_bounds_chunks_trailer_eof_and_single_deadline(self) -> None:
        operation = CHANNEL._issue_fetch_terminal_minimum_bundle_operation_for_testing(self.transport_raw, self.read_profile_raw, "123.master")
        stream = self.fetch_stream(operation, (b"alpha", b"beta"))
        header, bundle, trailer = self.through_pipe(
            stream,
            lambda descriptor: buffered_fetch_response(descriptor, operation, time.monotonic() + 1.0),
        )
        self.assertEqual(bundle, b"alphabeta")
        self.assertEqual(header["chunk_count"], "2")
        self.assertEqual(trailer["bundle_sha256"], hashlib.sha256(bundle).hexdigest())

        direct_operation = CHANNEL._issue_fetch_terminal_minimum_bundle_operation_for_testing(
            self.transport_raw, self.read_profile_raw, "123.master",
        )
        direct_bundle = b"alphabetagamma"
        direct_stream = self.fetch_stream(
            direct_operation, (b"alpha", b"beta", b"gamma"),
        )

        def consume_direct(descriptor):
            session, direct_header = CHANNEL._FETCH_STREAM_BEGIN(
                descriptor, direct_operation, time.monotonic() + 1.0,
            )
            self.assertIs(type(session), CHANNEL._FetchResponseStreamSession)
            first = CHANNEL._FETCH_STREAM_READ_EXACT(session, 7)
            second = CHANNEL._FETCH_STREAM_READ_EXACT(
                session, len(direct_bundle) - len(first),
            )
            direct_trailer = CHANNEL._FETCH_STREAM_FINISH(session)
            return direct_header, first + second, direct_trailer

        direct_header, observed, direct_trailer = self.through_pipe(
            direct_stream, consume_direct,
        )
        self.assertEqual(observed, direct_bundle)
        self.assertEqual(
            direct_header["bundle_commitment_sha256"],
            hashlib.sha256(b"commitment:" + direct_bundle).hexdigest(),
        )
        self.assertEqual(
            direct_trailer["bundle_commitment_sha256"],
            direct_header["bundle_commitment_sha256"],
        )

        duplicate_stream = self.fetch_stream(operation, (b"x",))
        duplicate_read, duplicate_write = os.pipe()
        try:
            os.write(duplicate_write, duplicate_stream)
            os.close(duplicate_write)
            duplicate_write = -1
            with self.assertRaisesRegex(CHANNEL.SharedFixedSSHChannelError, "terminal"):
                buffered_fetch_response(
                    duplicate_read,
                    operation,
                    time.monotonic() + 1.0,
                )
            self.assertEqual(os.read(duplicate_read, len(duplicate_stream)), duplicate_stream)
        finally:
            os.close(duplicate_read)
            if duplicate_write >= 0:
                os.close(duplicate_write)

        failed_operation: CHANNEL.FetchTerminalMinimumBundleOperation | None = None
        for label in ("zero", "truncated", "extra", "second"):
            hostile_operation = CHANNEL._issue_fetch_terminal_minimum_bundle_operation_for_testing(
                self.transport_raw,
                self.read_profile_raw,
                "123.master",
            )
            valid_stream = self.fetch_stream(hostile_operation, (b"x",))
            zero_header = {
                "protocol": CHANNEL.READ_PROTOCOL,
                "status": "streaming_terminal_minimum_bundle",
                "operation_id": hostile_operation.operation_id,
                "job_id": "123.master",
                "chunk_count": "0",
                "total_size_bytes": "0",
                "bundle_commitment_sha256": hashlib.sha256(
                    b"commitment:"
                ).hexdigest(),
                "authority": {"authorizes_effect": False, "qsub_calls": "0"},
            }
            hostile = {
                "zero": self.framed(zero_header),
                "truncated": valid_stream[:-1],
                "extra": valid_stream + b"extra",
                "second": valid_stream + self.fetch_stream(hostile_operation, (b"y",)),
            }[label]
            with self.subTest(label=label, size=len(hostile)):
                with self.assertRaises((CHANNEL.SharedFixedSSHChannelError, CHANNEL.ControllerTransportUnknown)):
                    self.through_pipe(
                        hostile,
                        lambda descriptor: buffered_fetch_response(
                            descriptor,
                            hostile_operation,
                            time.monotonic() + 0.5,
                        ),
                    )
            if label == "truncated":
                failed_operation = hostile_operation

        self.assertIsNotNone(failed_operation)
        valid_after_failure = self.fetch_stream(failed_operation, (b"valid",))
        retry_read, retry_write = os.pipe()
        try:
            os.write(retry_write, valid_after_failure)
            os.close(retry_write)
            retry_write = -1
            with self.assertRaisesRegex(CHANNEL.SharedFixedSSHChannelError, "terminal"):
                buffered_fetch_response(
                    retry_read,
                    failed_operation,
                    time.monotonic() + 1.0,
                )
            self.assertEqual(os.read(retry_read, len(valid_after_failure)), valid_after_failure)
        finally:
            os.close(retry_read)
            if retry_write >= 0:
                os.close(retry_write)

        oversize_operation = CHANNEL._issue_fetch_terminal_minimum_bundle_operation_for_testing(
            self.transport_raw,
            self.read_profile_raw,
            "123.master",
        )
        valid = self.fetch_stream(oversize_operation, (b"x",))
        header_size = struct.unpack("!I", valid[:4])[0]
        header = json.loads(valid[4:4 + header_size])
        header_raw = CHANNEL.canonical_bytes(header)
        oversize = struct.pack("!I", len(header_raw)) + header_raw + struct.pack("!I", 65537)
        with self.assertRaises(CHANNEL.SharedFixedSSHChannelError):
            self.through_pipe(
                oversize,
                lambda descriptor: buffered_fetch_response(
                    descriptor,
                    oversize_operation,
                    time.monotonic() + 0.5,
                ),
            )

        read_fd, write_fd = os.pipe()
        partial_operation = CHANNEL._issue_fetch_terminal_minimum_bundle_operation_for_testing(
            self.transport_raw,
            self.read_profile_raw,
            "123.master",
        )
        first = self.fetch_stream(partial_operation, (b"abcd",))

        def partial_writer() -> None:
            try:
                for byte in first:
                    os.write(write_fd, bytes((byte,)))
                    threading.Event().wait(0.005)
            except OSError:
                pass
            finally:
                try:
                    os.close(write_fd)
                except OSError:
                    pass

        thread = threading.Thread(target=partial_writer)
        thread.start()
        started = time.monotonic()
        try:
            with self.assertRaises(CHANNEL.ControllerTransportUnknown):
                buffered_fetch_response(read_fd, partial_operation, started + 0.03)
        finally:
            os.close(read_fd)
            thread.join(timeout=1)
        self.assertLess(time.monotonic() - started, 1.0)
        partial_valid = self.fetch_stream(partial_operation, (b"after-partial",))
        partial_retry_read, partial_retry_write = os.pipe()
        try:
            os.write(partial_retry_write, partial_valid)
            os.close(partial_retry_write)
            partial_retry_write = -1
            with self.assertRaisesRegex(CHANNEL.SharedFixedSSHChannelError, "terminal"):
                buffered_fetch_response(
                    partial_retry_read,
                    partial_operation,
                    time.monotonic() + 1.0,
                )
            self.assertEqual(
                os.read(partial_retry_read, len(partial_valid)),
                partial_valid,
            )
        finally:
            os.close(partial_retry_read)
            if partial_retry_write >= 0:
                os.close(partial_retry_write)

        foreign_operation = CHANNEL._issue_fetch_terminal_minimum_bundle_operation_for_testing(
            self.transport_raw,
            self.read_profile_raw,
            "123.master",
        )
        spliced_operation = CHANNEL._issue_fetch_terminal_minimum_bundle_operation_for_testing(
            self.transport_raw,
            self.read_profile_raw,
            "123.master",
        )
        foreign_stream = self.fetch_stream(foreign_operation, (b"foreign",))
        with self.assertRaises(CHANNEL.SharedFixedSSHChannelError):
            self.through_pipe(
                foreign_stream,
                lambda descriptor: buffered_fetch_response(
                    descriptor,
                    spliced_operation,
                    time.monotonic() + 0.5,
                ),
            )
        foreign_operation.assert_owner_sealed()

    def test_terminal_records_are_bounded_abandoned_records_are_weak_and_ids_do_not_reuse(self) -> None:
        operations: list[CHANNEL.QueryExactJobOperation] = []
        for _index in range(CHANNEL.MAX_TERMINAL_OPERATION_RECORDS + 2):
            operation = self.query_operation()
            operations.append(operation)
            payload = self.framed(self.query_response(operation))
            self.through_pipe(
                payload,
                lambda descriptor, current=operation: CHANNEL.read_query_response_until(
                    descriptor,
                    current,
                    time.monotonic() + 1.0,
                ),
            )
        operation_ids = [operation.operation_id for operation in operations]
        self.assertEqual(len(operation_ids), len(set(operation_ids)))
        with self.assertRaisesRegex(CHANNEL.SharedFixedSSHChannelError, "reclaimed"):
            operations[0].portable_projection()
        self.assertEqual(
            operations[-1].portable_projection()["operation_id"],
            operations[-1].operation_id,
        )
        with self.assertRaisesRegex(CHANNEL.SharedFixedSSHChannelError, "terminal"):
            operations[-1].assert_owner_sealed()

        abandoned = self.query_operation()
        abandoned_ref = weakref.ref(abandoned)
        del abandoned
        gc.collect()
        self.assertIsNone(abandoned_ref())

    def test_source_function_executable_options_and_fake_surfaces_fail_closed(self) -> None:
        CHANNEL._assert_production_binding()
        for attribute, hostile in (
            ("SSH_EXECUTABLE", "/tmp/hostile-ssh"),
            ("SSH_FIXED_OPTIONS", ("-F", "/tmp/hostile")),
            ("FIXED_ENVIRONMENT", {"LANG": "hostile"}),
            ("READ_SUBSYSTEM", "caller-selected"),
            ("run_submit_channel_once", lambda *_args: {}),
            ("_require", lambda *_args: None),
            ("_text", lambda *_args: "/usr/bin/true"),
            ("_absolute_file", lambda *_args: "/usr/bin/true"),
            ("PBS_BASENAME", "hostile-job.pbs"),
            ("_open_reviewed_executable", lambda *_args: -1),
            ("_descriptor_execve", lambda *_args: None),
            ("_operation_snapshot", lambda *_args: None),
            ("_claim_submit_operation", lambda *_args: None),
            ("_claim_query_operation", lambda *_args: None),
            ("_claim_fetch_operation", lambda *_args: None),
            ("_finish_operation", lambda *_args: None),
            ("project_query_request_frame_for_review", lambda *_args: b"hostile"),
            ("project_fetch_request_frame_for_review", lambda *_args: b"hostile"),
        ):
            with self.subTest(attribute=attribute), mock.patch.object(CHANNEL, attribute, hostile):
                with self.assertRaisesRegex(CHANNEL.SharedFixedSSHChannelError, "production source, function, executable, or option binding"):
                    CHANNEL._assert_production_binding()
        join = W5._issue_controller_request_join(self.fixture.artifacts)
        frame = W5._artifact_frame(self.fixture.artifacts, join)
        try:
            with mock.patch.object(W5, "_assert_shared_channel_request_authority", lambda *_args: None):
                with self.assertRaisesRegex(W5.DirectOneHopTransportError, "production transport source"):
                    CHANNEL.issue_submit_channel_operation(self.transport_raw, join, frame)
        finally:
            W5._retire_controller_request_join(join)
        source = (SCRIPTS / "direct_shared_fixed_ssh_channel.py").read_text(encoding="utf-8")
        self.assertNotIn("import subprocess", source)
        self.assertNotIn("import socket", source)
        argv = CHANNEL.build_controller_argv(self.transport_raw, self.submit_operation())
        self.assertIn("ProxyJump=none", argv)
        self.assertNotIn("driver", str(__import__("inspect").signature(CHANNEL.run_submit_channel_once)))
        public = set(CHANNEL.__all__)
        self.assertNotIn("run_query", public)
        self.assertNotIn("run_fetch", public)
        self.assertNotIn("build_query_request_frame", public)
        self.assertNotIn("build_fetch_request_frame", public)


if __name__ == "__main__":
    unittest.main()
