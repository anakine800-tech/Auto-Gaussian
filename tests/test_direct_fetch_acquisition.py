#!/usr/bin/env python3
"""Offline hostile tests for fixed direct fetch acquisition and T4 seam."""

from __future__ import annotations

import ast
import copy
import gc
import hashlib
import importlib
import json
import os
import pathlib
import pickle
import resource
import shutil
import socket
import stat
import struct
import sys
import tempfile
import threading
import time
import tracemalloc
import unittest
from unittest import mock

import tests.test_direct_existing_job_lineage as LINEAGE_FIXTURES


ROOT = pathlib.Path(__file__).parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import direct_existing_job_lineage as LINEAGE  # noqa: E402
import direct_fetch_acquisition as FETCH  # noqa: E402
import direct_local_fetch_materializer as MATERIALIZER  # noqa: E402
import direct_shared_fixed_ssh_channel as CHANNEL  # noqa: E402
import skill_package as SKILL_PACKAGE  # noqa: E402


class DirectFetchAcquisitionTests(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="auto-g16-fetch-acquisition-")
        self.base = pathlib.Path(self.temporary.name).resolve()
        (self.base / "server").mkdir(mode=0o700)
        self.fixture, self.receipt, self.receipt_raw = LINEAGE_FIXTURES.DirectExistingJobLineageTests.completed_fixture(
            str(self.base / "server"), "731.master",
        )
        self.project = self.fixture.root / self.receipt["project"]
        self.payloads = (
            self.fixture.artifacts.input_bytes,
            self.fixture.artifacts.pbs_script,
            (self.project / "checksums.sha256").read_bytes(),
            self.receipt_raw,
            b"Normal termination of Gaussian 16\n",
        )
        (self.project / "approved-input.log").write_bytes(self.payloads[-1])
        for name in MATERIALIZER.ARTIFACT_BASENAMES:
            os.chmod(self.project / name, 0o600)
        self.transport_raw = self.fixture.artifacts.transport_profile
        transport = CHANNEL.load_transport_profile(self.transport_raw)
        self.read_profile = {
            "schema": CHANNEL.READ_PROFILE_SCHEMA,
            "profile_id": "offline-fetch-acquisition-profile",
            "transport_binding": {
                "schema": "exact_w5_transport_profile_bytes/1",
                "transport_profile_bytes_sha256": hashlib.sha256(self.transport_raw).hexdigest(),
                "transport_profile_payload_sha256": transport["profile_payload_sha256"],
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
                    "max_chunk_bytes": "4096",
                    "max_chunks": "256",
                    "timeout_seconds": "30",
                },
            },
            "safety": copy.deepcopy(CHANNEL.READ_POLICY),
            "read_profile_payload_sha256": "",
        }
        self.read_profile["read_profile_payload_sha256"] = CHANNEL.digest(self.read_profile)
        self.read_profile_raw = CHANNEL.canonical_bytes(self.read_profile)
        self.local = self.base / "local"
        self.local.mkdir(mode=0o700)

    def tearDown(self) -> None:
        self.fixture.close()
        self.temporary.cleanup()

    def lineage_lease(self):
        capability = LINEAGE_FIXTURES.DirectExistingJobLineageTests.owner(self.fixture).issue_once(
            self.receipt_raw, self.fixture.artifacts,
        )
        projection = capability.portable_projection()
        return capability.consume_once(), projection

    def target(self, *, suffix: str = "1"):
        owner = MATERIALIZER._issue_offline_target_owner_for_tests(
            target_root=str(self.local),
            review_id="local-fetch-target-review-" + suffix * 64,
        )
        capability = owner.issue_target_once(
            project=self.receipt["project"],
            attempt_id=self.receipt["attempt_id"],
            job_id=self.receipt["qsub"]["job_id"],
            w5_receipt_sha256=hashlib.sha256(self.receipt_raw).hexdigest(),
            read_profile_sha256=self.read_profile["read_profile_payload_sha256"],
        )
        return owner, capability

    def server_capability(self):
        lease, projection = self.lineage_lease()
        capability = FETCH._issue_server_fetch_acquisition_for_tests_once(
            lease,
            self.read_profile_raw,
            _test_token=FETCH._TEST_TOKEN,
        )
        return capability, projection

    @staticmethod
    def through_pipe(raw: bytes, function):
        read_fd, write_fd = os.pipe()
        try:
            os.write(write_fd, raw)
            os.close(write_fd)
            write_fd = -1
            return function(read_fd)
        finally:
            os.close(read_fd)
            if write_fd >= 0:
                os.close(write_fd)

    @staticmethod
    def buffered_response(server, request):
        return FETCH._build_terminal_minimum_response_for_tests_once(
            server, request, _test_token=FETCH._TEST_TOKEN,
        )

    def streaming_closed_stream(self, server, projection, target):
        operation = CHANNEL.issue_fetch_terminal_minimum_bundle_operation(
            self.transport_raw,
            self.read_profile_raw,
            self.receipt["qsub"]["job_id"],
        )
        request = CHANNEL.project_fetch_request_frame_for_review(operation)
        server_socket, controller_socket = socket.socketpair()
        failures: list[BaseException] = []

        def writer():
            try:
                FETCH._write_terminal_minimum_response_for_tests_once(
                    server,
                    request,
                    server_socket.fileno(),
                    _test_token=FETCH._TEST_TOKEN,
                )
            except BaseException as exc:
                failures.append(exc)
            finally:
                server_socket.close()

        thread = threading.Thread(target=writer, daemon=True)
        thread.start()
        try:
            stream = FETCH._acquire_controller_fetch_stream_for_tests_once(
                target,
                operation,
                controller_socket.fileno(),
                projection,
                _test_token=FETCH._TEST_TOKEN,
            )
        finally:
            controller_socket.close()
        return stream, thread, failures

    def response(self):
        server, projection = self.server_capability()
        operation = CHANNEL.issue_fetch_terminal_minimum_bundle_operation(
            self.transport_raw, self.read_profile_raw, self.receipt["qsub"]["job_id"],
        )
        request = CHANNEL.project_fetch_request_frame_for_review(operation)
        response = self.buffered_response(server, request)
        return operation, response, projection

    def closed_stream(self):
        operation, response, projection = self.response()
        _owner, target = self.target()
        capability = self.through_pipe(
            response,
            lambda descriptor: FETCH._acquire_controller_fetch_stream_for_tests_once(
                target, operation, descriptor, projection,
                _test_token=FETCH._TEST_TOKEN,
            ),
        )
        return target, capability

    def test_exact_five_server_read_closed_stream_and_safe_materialization(self) -> None:
        server, lineage = self.server_capability()
        acquisition = server.portable_projection()
        self.assertEqual(FETCH.validate_acquisition_projection(acquisition), acquisition)
        self.assertEqual([item["basename"] for item in acquisition["files"]], list(MATERIALIZER.ARTIFACT_BASENAMES))
        self.assertEqual(acquisition["binding"], lineage["binding"])
        self.assertFalse(acquisition["authority"]["authorizes_effect"])
        self.assertFalse(acquisition["authority"]["production_stream_seam"])
        self.assertEqual(
            acquisition["authority"]["required_production_predecessor"],
            FETCH.REQUIRED_PRODUCTION_PREDECESSOR,
        )
        operation = CHANNEL.issue_fetch_terminal_minimum_bundle_operation(
            self.transport_raw, self.read_profile_raw, self.receipt["qsub"]["job_id"],
        )
        response = self.buffered_response(
            server, CHANNEL.project_fetch_request_frame_for_review(operation),
        )
        _owner, target = self.target()
        stream = self.through_pipe(
            response,
            lambda descriptor: FETCH._acquire_controller_fetch_stream_for_tests_once(
                target, operation, descriptor, lineage,
                _test_token=FETCH._TEST_TOKEN,
            ),
        )
        stream_projection = stream.portable_projection()
        self.assertTrue(stream_projection["authority"]["closed_stream_owner"])
        self.assertFalse(stream_projection["authority"]["production_integration"])
        lease = MATERIALIZER.issue_closed_fetch_stream_lease_once(target, stream)
        self.assertEqual(lease.portable_projection()["stream_mode"], MATERIALIZER.CLOSED_STREAM_MODE)
        manifest = MATERIALIZER.materialize_direct_fetch_once(target, lease)
        leaf = self.local / manifest["target"]["leaf_basename"]
        for name, expected in zip(MATERIALIZER.ARTIFACT_BASENAMES, self.payloads, strict=True):
            self.assertEqual((leaf / name).read_bytes(), expected)
            self.assertEqual(stat.S_IMODE((leaf / name).stat().st_mode), 0o600)
        self.assertFalse(manifest["integration"]["production_integration"])
        self.assertEqual(manifest["stream"]["stream_mode"], MATERIALIZER.CLOSED_STREAM_MODE)

    def test_full_flow_streams_sixteen_mib_with_chunk_bounded_heap(self) -> None:
        large_size = 16 * 1024 * 1024
        large_payload = b"\xc3\xa9" * (large_size // 2)
        log_path = self.project / "approved-input.log"
        log_path.write_bytes(large_payload)
        os.chmod(log_path, 0o600)
        self.read_profile["server_read"]["fetch"].update({
            "max_total_bytes": str(20 * 1024 * 1024),
            "max_chunk_bytes": str(1024 * 1024),
            "max_chunks": "32",
            "timeout_seconds": "300",
        })
        self.read_profile["read_profile_payload_sha256"] = ""
        self.read_profile["read_profile_payload_sha256"] = CHANNEL.digest(
            self.read_profile
        )
        self.read_profile_raw = CHANNEL.canonical_bytes(self.read_profile)
        del large_payload
        gc.collect()
        tracemalloc.start()
        baseline, _ = tracemalloc.get_traced_memory()
        try:
            server, projection = self.server_capability()
            _owner, target = self.target(suffix="8")
            stream, writer_thread, failures = self.streaming_closed_stream(
                server, projection, target,
            )
            lease = MATERIALIZER.issue_closed_fetch_stream_lease_once(
                target, stream,
            )
            manifest = MATERIALIZER.materialize_direct_fetch_once(
                target, lease,
            )
            writer_thread.join(timeout=300)
            self.assertFalse(writer_thread.is_alive())
            self.assertEqual(failures, [])
            current, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertEqual(
            manifest["files"][-1]["size_bytes"], str(large_size),
        )
        leaf = self.local / manifest["target"]["leaf_basename"]
        self.assertEqual((leaf / "approved-input.log").stat().st_size, large_size)
        self.assertLess(
            peak - baseline,
            12 * 1024 * 1024,
            (baseline, current, peak),
        )

    def test_isolated_one_gib_log_is_end_to_end_chunk_bounded_and_manifest_last(self) -> None:
        one_gib = 1024 * 1024 * 1024
        log_path = self.project / "approved-input.log"
        with log_path.open("r+b") as stream:
            stream.truncate(one_gib)
        os.chmod(log_path, 0o600)
        self.read_profile["server_read"]["fetch"].update({
            "max_total_bytes": str(CHANNEL.MAX_FETCH_TOTAL_BYTES),
            "max_chunk_bytes": str(CHANNEL.MAX_FETCH_CHUNK_BYTES),
            "max_chunks": "512",
            "timeout_seconds": "3600",
        })
        self.read_profile["read_profile_payload_sha256"] = ""
        self.read_profile["read_profile_payload_sha256"] = CHANNEL.digest(
            self.read_profile
        )
        self.read_profile_raw = CHANNEL.canonical_bytes(self.read_profile)
        gc.collect()
        rss_before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        started = time.monotonic()
        tracemalloc.start()
        baseline, _ = tracemalloc.get_traced_memory()
        try:
            server, projection = self.server_capability()
            acquisition = server.portable_projection()
            self.assertEqual(
                acquisition["total_size_bytes"],
                str(sum(
                    (self.project / name).stat().st_size
                    for name in MATERIALIZER.ARTIFACT_BASENAMES
                )),
            )
            self.assertLessEqual(
                FETCH._bundle_wire_size(acquisition),
                CHANNEL.MAX_FETCH_TOTAL_BYTES,
            )
            self.assertEqual(acquisition["authority"]["qsub_calls"], "0")
            self.assertEqual(acquisition["authority"]["qdel_calls"], "0")
            self.assertFalse(acquisition["authority"]["automatic_retry"])
            _owner, target = self.target(suffix="9")
            self.assertEqual(tuple(self.local.iterdir()), ())
            stream, writer_thread, failures = self.streaming_closed_stream(
                server, projection, target,
            )
            lease = MATERIALIZER.issue_closed_fetch_stream_lease_once(
                target, stream,
            )
            self.assertEqual(tuple(self.local.iterdir()), ())
            manifest = MATERIALIZER.materialize_direct_fetch_once(
                target, lease,
            )
            writer_thread.join(timeout=3600)
            self.assertFalse(writer_thread.is_alive())
            self.assertEqual(failures, [])
            current, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        elapsed = time.monotonic() - started
        rss_after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        leaf = self.local / manifest["target"]["leaf_basename"]
        self.assertEqual((leaf / "approved-input.log").stat().st_size, one_gib)
        self.assertTrue((leaf / MATERIALIZER.MANIFEST_BASENAME).is_file())
        self.assertEqual(manifest["integration"]["production_integration"], False)
        self.assertLess(peak - baseline, 32 * 1024 * 1024)
        self.assertLess(rss_after - rss_before, 96 * 1024 * 1024)
        print(
            "ONE_GIB_STREAM_METRICS",
            json.dumps({
                "elapsed_seconds": round(elapsed, 3),
                "heap_current_bytes": current,
                "heap_peak_delta_bytes": peak - baseline,
                "ru_maxrss_before": rss_before,
                "ru_maxrss_after": rss_after,
                "wire_cap_bytes": CHANNEL.MAX_FETCH_TOTAL_BYTES,
                "payload_bytes": acquisition["total_size_bytes"],
            }, sort_keys=True),
        )

    def test_capabilities_reject_construction_copy_pickle_fork_and_second_use(self) -> None:
        server, _projection = self.server_capability()
        for operation in (copy.copy, copy.deepcopy, pickle.dumps):
            with self.assertRaises(TypeError):
                operation(server)
        with self.assertRaises(TypeError):
            FETCH.DirectServerFetchAcquisitionCapability()
        read_fd, write_fd = os.pipe()
        pid = os.fork()
        if pid == 0:  # pragma: no cover - child reports one word
            os.close(read_fd)
            try:
                server.assert_current()
            except BaseException:
                os.write(write_fd, b"rejected")
            else:
                os.write(write_fd, b"accepted")
            os.close(write_fd)
            os._exit(0)
        os.close(write_fd)
        self.assertEqual(os.read(read_fd, 32), b"rejected")
        os.close(read_fd)
        os.waitpid(pid, 0)
        operation = CHANNEL.issue_fetch_terminal_minimum_bundle_operation(
            self.transport_raw, self.read_profile_raw, self.receipt["qsub"]["job_id"],
        )
        request = CHANNEL.project_fetch_request_frame_for_review(operation)
        response = self.buffered_response(server, request)
        with self.assertRaises(FETCH.DirectFetchAcquisitionError):
            self.buffered_response(server, request)
        _owner, target = self.target()
        stream = self.through_pipe(
            response,
            lambda descriptor: FETCH._acquire_controller_fetch_stream_for_tests_once(
                target, operation, descriptor, _projection,
                _test_token=FETCH._TEST_TOKEN,
            ),
        )
        for operation_copy in (copy.copy, copy.deepcopy, pickle.dumps):
            with self.assertRaises(TypeError):
                operation_copy(stream)
        read_fd, write_fd = os.pipe()
        pid = os.fork()
        if pid == 0:  # pragma: no cover - child reports one word
            os.close(read_fd)
            try:
                stream.assert_current()
            except BaseException:
                os.write(write_fd, b"rejected")
            else:
                os.write(write_fd, b"accepted")
            os.close(write_fd)
            os._exit(0)
        os.close(write_fd)
        self.assertEqual(os.read(read_fd, 32), b"rejected")
        os.close(read_fd)
        os.waitpid(pid, 0)
        lease = MATERIALIZER.issue_closed_fetch_stream_lease_once(target, stream)
        with self.assertRaises(FETCH.DirectFetchAcquisitionError):
            MATERIALIZER.issue_closed_fetch_stream_lease_once(target, stream)
        MATERIALIZER.materialize_direct_fetch_once(target, lease)

    def test_no_public_raw_profile_or_generic_controller_acquisition_entrypoint_exists(self) -> None:
        self.assertFalse(hasattr(FETCH, "issue_server_fetch_acquisition_once"))
        self.assertFalse(hasattr(FETCH, "acquire_controller_fetch_stream_once"))
        self.assertNotIn("issue_server_fetch_acquisition_once", FETCH.__all__)
        self.assertNotIn("acquire_controller_fetch_stream_once", FETCH.__all__)
        lease, _projection = self.lineage_lease()
        with self.assertRaises(FETCH.DirectFetchAcquisitionError):
            FETCH._issue_server_fetch_acquisition_for_tests_once(
                lease, self.read_profile_raw, _test_token=object(),
            )
        lease.close_once()

    def test_raw_fake_owner_and_l1_handoff_require_exact_private_test_token(self) -> None:
        with self.assertRaises(TypeError):
            FETCH._new_owner(self.read_profile_raw)
        with self.assertRaises(FETCH.DirectFetchAcquisitionError):
            FETCH._new_owner(self.read_profile_raw, _test_token=object())
        lease, _projection = self.lineage_lease()
        owner = FETCH._new_owner(
            self.read_profile_raw,
            _test_token=FETCH._TEST_TOKEN,
        )
        with self.assertRaises(LINEAGE.DirectExistingJobLineageError):
            LINEAGE._CAPABILITY_HANDOFF_FETCH(lease, owner, object())
        lease.assert_current()
        server = LINEAGE._CAPABILITY_HANDOFF_FETCH(
            lease, owner, FETCH._TEST_TOKEN,
        )
        self.assertIs(type(server), FETCH.DirectServerFetchAcquisitionCapability)
        server.abandon_once()

    def test_server_registry_is_closure_private_and_projection_mutation_is_inert(self) -> None:
        self.assertFalse(hasattr(FETCH, "_SERVER_REGISTRY"))
        self.assertFalse(hasattr(FETCH, "_server_record"))
        server, _projection = self.server_capability()
        portable = server.portable_projection()
        portable["authority"]["qdel_calls"] = "1"
        portable["files"][0]["sha256"] = "a" * 64
        server.assert_current()
        replay = server.portable_projection()
        self.assertEqual(replay["authority"]["qdel_calls"], "0")
        self.assertNotEqual(replay["files"][0]["sha256"], "a" * 64)
        server.abandon_once()
        with self.assertRaises(FETCH.DirectFetchAcquisitionError):
            server.assert_current()

    def test_controller_registry_is_closure_private_and_projection_mutation_is_inert(self) -> None:
        self.assertFalse(hasattr(FETCH, "_CONTROLLER_REGISTRY"))
        self.assertFalse(hasattr(FETCH, "_controller_record"))
        target, stream = self.closed_stream()
        portable = stream.portable_projection()
        portable["authority"]["qdel_calls"] = "1"
        portable["files"][0]["sha256"] = "a" * 64
        stream.assert_current()
        replay = stream.portable_projection()
        self.assertEqual(replay["authority"]["qdel_calls"], "0")
        self.assertNotEqual(replay["files"][0]["sha256"], "a" * 64)
        with mock.patch.object(FETCH, "_CONTROLLER_REGISTRY", {}, create=True):
            with self.assertRaises(FETCH.DirectFetchAcquisitionError):
                stream.assert_current()
        stream.assert_current()
        lease = MATERIALIZER.issue_closed_fetch_stream_lease_once(target, stream)
        with self.assertRaises(FETCH.DirectFetchAcquisitionError):
            MATERIALIZER.issue_closed_fetch_stream_lease_once(target, stream)
        MATERIALIZER.materialize_direct_fetch_once(target, lease)

    def test_record_commitments_are_incremental_and_payload_bounded(self) -> None:
        source = (SCRIPTS / "direct_fetch_acquisition.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        functions = {
            node.name: node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
        }
        for name in ("_server_record_commitment", "_controller_record_commitment"):
            calls = {
                node.func.id
                for node in ast.walk(functions[name])
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            }
            self.assertNotIn("repr", calls)
        raw = b"\xff" * (16 * 1024 * 1024)
        declared_sha = hashlib.sha256(raw).hexdigest()
        record = FETCH._ControllerRecord(
            object(),
            os.getpid(),
            object(),
            b"{}",
            object(),
            (("approved-input.log", str(len(raw)), declared_sha),),
            "a" * 64,
            "",
        )
        real_canonical = FETCH.canonical_bytes

        def reject_raw_canonicalization(value):
            self.assertNotIsInstance(value, (bytes, bytearray, memoryview))
            return real_canonical(value)

        tracemalloc.start()
        try:
            with mock.patch.object(
                FETCH,
                "canonical_bytes",
                side_effect=reject_raw_canonicalization,
            ):
                result = FETCH._controller_record_commitment(record)
            _current, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertRegex(result, r"^[a-f0-9]{64}$")
        self.assertLess(peak, 2 * 1024 * 1024)

    def test_require_and_canonical_helper_rebinding_cannot_bypass_stale_file(self) -> None:
        server, _projection = self.server_capability()
        path = self.project / "approved-input.log"
        replacement = self.project / "binding-bypass-replacement.tmp"
        replacement.write_bytes(path.read_bytes())
        os.chmod(replacement, 0o600)
        os.replace(replacement, path)
        with mock.patch.object(FETCH, "_require", lambda *_args: None):
            with self.assertRaises(FETCH.DirectFetchAcquisitionError):
                server.assert_current()
        for field, replacement_helper in (
            ("canonical_bytes", lambda *_args: b"{}"),
            ("digest", lambda *_args: "a" * 64),
            ("_sha", lambda value, *_args, **_kwargs: value),
            ("_exact", lambda value, *_args: value),
            ("_decimal", lambda *_args: 0),
        ):
            with self.subTest(field=field):
                with mock.patch.object(FETCH, field, replacement_helper):
                    with self.assertRaises(FETCH.DirectFetchAcquisitionError):
                        server.assert_current()
        server.abandon_once()

    def test_abandon_is_terminal_and_second_consume_is_rejected(self) -> None:
        server, _projection = self.server_capability()
        server.abandon_once()
        with self.assertRaises(FETCH.DirectFetchAcquisitionError):
            server.assert_current()
        with self.assertRaises(FETCH.DirectFetchAcquisitionError):
            server.abandon_once()

    def test_server_rejects_nonallowlisted_types_links_modes_and_missing_files(self) -> None:
        path = self.project / "approved-input.log"
        original = path.read_bytes()
        project_fd = os.open(
            self.project,
            os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
        )
        project_info = os.fstat(project_fd)
        for label in ("symlink", "fifo", "directory", "hardlink", "mode", "missing"):
            with self.subTest(label=label):
                try:
                    path.unlink()
                    if label == "symlink":
                        path.symlink_to("approved-input.gjf")
                    elif label == "fifo":
                        os.mkfifo(path, 0o600)
                    elif label == "directory":
                        path.mkdir(mode=0o700)
                    elif label == "hardlink":
                        os.link(self.project / "approved-input.gjf", path)
                    elif label == "mode":
                        path.write_bytes(original)
                        os.chmod(path, 0o666)
                    with self.assertRaises((FETCH.DirectFetchAcquisitionError, OSError)):
                        FETCH._observe_file(
                            project_fd, project_info, "approved-input.log",
                            MATERIALIZER.ARTIFACT_CAPS["approved-input.log"],
                            time.monotonic() + 1.0,
                        )
                finally:
                    try:
                        info = os.lstat(path)
                    except FileNotFoundError:
                        pass
                    else:
                        if stat.S_ISDIR(info.st_mode):
                            path.rmdir()
                        else:
                            path.unlink()
                    path.write_bytes(original)
                    os.chmod(path, 0o600)
        path = self.project / "approved-input.log"
        real = os.stat(path, follow_symlinks=False)
        for label, file_type in (("socket", stat.S_IFSOCK), ("device", stat.S_IFCHR)):
            with self.subTest(label=label):
                fields = list(real)
                fields[0] = file_type | 0o600
                hostile = os.stat_result(fields)
                with mock.patch.object(FETCH.os, "stat", return_value=hostile):
                    with self.assertRaises(FETCH.DirectFetchAcquisitionError):
                        FETCH._observe_file(
                            project_fd, project_info, "approved-input.log",
                            MATERIALIZER.ARTIFACT_CAPS["approved-input.log"],
                            time.monotonic() + 1.0,
                        )
        os.close(project_fd)

    def test_descriptor_currentness_rejects_replacement_and_in_read_drift(self) -> None:
        server, _projection = self.server_capability()
        path = self.project / "approved-input.log"
        replacement = self.project / "replacement.tmp"
        replacement.write_bytes(path.read_bytes())
        os.chmod(replacement, 0o600)
        os.replace(replacement, path)
        with self.assertRaises(FETCH.DirectFetchAcquisitionError):
            server.assert_current()
        operation = CHANNEL.issue_fetch_terminal_minimum_bundle_operation(
            self.transport_raw,
            self.read_profile_raw,
            self.receipt["qsub"]["job_id"],
        )
        request = CHANNEL.project_fetch_request_frame_for_review(operation)
        with self.assertRaises(FETCH.DirectFetchAcquisitionError):
            self.buffered_response(server, request)
        with self.assertRaises(FETCH.DirectFetchAcquisitionError):
            server.assert_current()

    def test_named_entry_replacement_during_same_fd_read_rejects(self) -> None:
        project_fd = os.open(
            self.project,
            os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
        )
        observed = FETCH._observe_file(
            project_fd,
            os.fstat(project_fd),
            "approved-input.log",
            MATERIALIZER.ARTIFACT_CAPS["approved-input.log"],
            time.monotonic() + 30.0,
        )
        replacement = self.project / "replacement-during-read.tmp"
        replacement.write_bytes(self.payloads[-1])
        os.chmod(replacement, 0o600)
        real_read = FETCH.os.read
        changed = False

        def drift(descriptor: int, size: int) -> bytes:
            nonlocal changed
            chunk = real_read(descriptor, size)
            if descriptor == observed.descriptor and chunk and not changed:
                os.replace(replacement, self.project / observed.basename)
                changed = True
            return chunk

        with mock.patch.object(FETCH.os, "read", side_effect=drift):
            with self.assertRaisesRegex(FETCH.DirectFetchAcquisitionError, "changed during read"):
                FETCH._read_current_file(
                    project_fd,
                    observed,
                    MATERIALIZER.ARTIFACT_CAPS[observed.basename],
                    time.monotonic() + 30.0,
                )
        os.close(observed.descriptor)
        os.close(project_fd)

    def test_request_rejects_job_operation_authority_extra_and_second_frame(self) -> None:
        variants = []
        operation = CHANNEL.issue_fetch_terminal_minimum_bundle_operation(
            self.transport_raw, self.read_profile_raw, self.receipt["qsub"]["job_id"],
        )
        valid = CHANNEL.project_fetch_request_frame_for_review(operation)
        value = json.loads(valid[4:])
        for field, item in (
            ("job_id", "999.master"),
            ("operation", "query_exact_job"),
            ("authority", {"authorizes_effect": True, "qsub_calls": "0"}),
        ):
            hostile = copy.deepcopy(value)
            hostile[field] = item
            payload = CHANNEL.canonical_bytes(hostile)
            variants.append(struct.pack("!I", len(payload)) + payload)
        variants.extend((valid + b"x", valid + valid))
        for hostile in variants:
            with self.assertRaises(
                (FETCH.DirectFetchAcquisitionError, CHANNEL.SharedFixedSSHChannelError),
            ):
                FETCH._validate_fetch_request(
                    hostile, self.receipt["qsub"]["job_id"],
                )
        server, _projection = self.server_capability()
        with self.assertRaises(
            (FETCH.DirectFetchAcquisitionError, CHANNEL.SharedFixedSSHChannelError),
        ):
            self.buffered_response(server, variants[0])
        with self.assertRaises(FETCH.DirectFetchAcquisitionError):
            server.assert_current()
        with self.assertRaises(FETCH.DirectFetchAcquisitionError):
            self.buffered_response(server, valid)

    def test_expired_server_build_terminalizes_and_never_retries(self) -> None:
        profile = copy.deepcopy(self.read_profile)
        profile["server_read"]["fetch"]["timeout_seconds"] = "1"
        profile["read_profile_payload_sha256"] = ""
        profile["read_profile_payload_sha256"] = CHANNEL.digest(profile)
        profile_raw = CHANNEL.canonical_bytes(profile)
        lease, _projection = self.lineage_lease()
        server = FETCH._issue_server_fetch_acquisition_for_tests_once(
            lease,
            profile_raw,
            _test_token=FETCH._TEST_TOKEN,
        )
        operation = CHANNEL.issue_fetch_terminal_minimum_bundle_operation(
            self.transport_raw,
            profile_raw,
            self.receipt["qsub"]["job_id"],
        )
        request = CHANNEL.project_fetch_request_frame_for_review(operation)
        time.sleep(1.05)
        with self.assertRaises(FETCH.DirectFetchAcquisitionError):
            self.buffered_response(server, request)
        with self.assertRaises(FETCH.DirectFetchAcquisitionError):
            server.assert_current()
        with self.assertRaises(FETCH.DirectFetchAcquisitionError):
            self.buffered_response(server, request)

    def test_bundle_parser_rejects_truncation_extra_invalid_utf8_hash_size_order_and_count(self) -> None:
        server, _projection = self.server_capability()
        raw = FETCH._bundle_bytes(server.portable_projection(), self.payloads)
        server.abandon_once()
        hostiles: dict[str, bytes] = {
            "truncated": raw[:-1],
            "extra": raw + b"x",
        }
        offset = len(FETCH.BUNDLE_MAGIC)
        size = struct.unpack("!I", raw[offset:offset + 4])[0]
        start = offset + 4
        original_header = json.loads(raw[start:start + size])
        hostiles["utf8"] = raw[:start] + b"\xff" + raw[start + 1:]
        for label in ("hash", "size", "order", "count"):
            header = copy.deepcopy(original_header)
            if label == "hash":
                header["files"][0]["sha256"] = "a" * 64
            elif label == "size":
                header["files"][0]["size_bytes"] = "999999999999"
            elif label == "order":
                header["files"][0]["order"] = "2"
            else:
                header["file_count"] = "4"
            encoded = FETCH.canonical_bytes(header)
            hostiles[label] = raw[:offset] + struct.pack("!I", len(encoded)) + encoded + raw[start + size:]
        for label in ("truncated", "extra", "utf8", "hash", "size", "order", "count"):
            with self.subTest(label=label):
                with self.assertRaises(FETCH.DirectFetchAcquisitionError):
                    FETCH._parse_bundle(hostiles[label])

    def test_outer_codec_rejects_partial_extra_second_frame_and_cross_type(self) -> None:
        for index, transform in enumerate((
            lambda response: response[:-1],
            lambda response: response + b"x",
            lambda response: response + response,
        ), 1):
            operation, response, projection = self.response()
            _owner, target = self.target(suffix=str(index + 2))
            hostile = transform(response)
            stream = self.through_pipe(
                hostile,
                lambda descriptor: FETCH._acquire_controller_fetch_stream_for_tests_once(
                    target, operation, descriptor, projection,
                    _test_token=FETCH._TEST_TOKEN,
                ),
            )
            lease = MATERIALIZER.issue_closed_fetch_stream_lease_once(
                target, stream,
            )
            with self.assertRaises((
                FETCH.DirectFetchAcquisitionError,
                FETCH.DirectFetchTransportUnknown,
                CHANNEL.SharedFixedSSHChannelError,
                MATERIALIZER.DirectLocalFetchMaterializerError,
            )):
                MATERIALIZER.materialize_direct_fetch_once(target, lease)
            retained = tuple(self.local.iterdir())
            self.assertTrue(retained)
            self.assertFalse(any(
                (path / MATERIALIZER.MANIFEST_BASENAME).exists()
                for path in retained
            ))
            break  # operation is terminal after the first attempted read
        query = CHANNEL.issue_query_exact_job_operation(
            self.transport_raw, self.read_profile_raw, self.receipt["qsub"]["job_id"],
        )
        with self.assertRaises(FETCH.DirectFetchAcquisitionError):
            FETCH._acquire_controller_fetch_stream_for_tests_once(
                target, query, 0, projection, _test_token=FETCH._TEST_TOKEN,
            )

    def _assert_splice_reject(self, label: str) -> None:
        operation, response, projection = self.response()
        if label == "lineage":
            projection = copy.deepcopy(projection)
            projection["binding"]["project"] = "foreign"
            projection["result_payload_sha256"] = LINEAGE.digest({**projection, "result_payload_sha256": ""})
        _owner, target = self.target()
        if label != "lineage":
            record = MATERIALIZER._target_record(target)
            field = {"job": "job_id", "profile": "read_profile_sha256", "receipt": "w5_receipt_sha256"}[label]
            record.fields[field] = ({"job": "999.master", "profile": "a" * 64, "receipt": "b" * 64}[label])
            object.__setattr__(target, field, record.fields[field])
        with self.assertRaises((FETCH.DirectFetchAcquisitionError, LINEAGE.DirectExistingJobLineageError, MATERIALIZER.DirectLocalFetchMaterializerError)):
            self.through_pipe(
                response,
                lambda descriptor: FETCH._acquire_controller_fetch_stream_for_tests_once(
                    target, operation, descriptor, projection,
                    _test_token=FETCH._TEST_TOKEN,
                ),
            )

    def test_lineage_splice_rejects(self) -> None:
        self._assert_splice_reject("lineage")

    def test_target_job_splice_rejects(self) -> None:
        self._assert_splice_reject("job")

    def test_target_profile_splice_rejects(self) -> None:
        self._assert_splice_reject("profile")

    def test_target_receipt_splice_rejects(self) -> None:
        self._assert_splice_reject("receipt")

    def test_target_stream_splice_and_existing_target_no_clobber(self) -> None:
        target_a, stream = self.closed_stream()
        other_root = self.base / "other-local"
        other_root.mkdir(mode=0o700)
        owner = MATERIALIZER._issue_offline_target_owner_for_tests(
            target_root=str(other_root), review_id="local-fetch-target-review-" + "9" * 64,
        )
        target_b = owner.issue_target_once(
            project=self.receipt["project"], attempt_id=self.receipt["attempt_id"],
            job_id=self.receipt["qsub"]["job_id"],
            w5_receipt_sha256=hashlib.sha256(self.receipt_raw).hexdigest(),
            read_profile_sha256=self.read_profile["read_profile_payload_sha256"],
        )
        with self.assertRaises((FETCH.DirectFetchAcquisitionError, MATERIALIZER.DirectLocalFetchMaterializerError)):
            MATERIALIZER.issue_closed_fetch_stream_lease_once(target_b, stream)
        target_a.assert_current()
        lease = MATERIALIZER.issue_closed_fetch_stream_lease_once(target_a, stream)
        with self.assertRaises(FETCH.DirectFetchAcquisitionError):
            MATERIALIZER.issue_closed_fetch_stream_lease_once(target_a, stream)
        MATERIALIZER.materialize_direct_fetch_once(target_a, lease)

    def test_reload_rebind_and_source_drift_fail_before_transition(self) -> None:
        with self.assertRaises(ImportError):
            importlib.reload(FETCH)
        server, _projection = self.server_capability()
        for field, replacement in (
            ("_read_current_file", lambda *_args: b""),
            ("_observe_file", lambda *_args: None),
            ("BUNDLE_MAGIC", b"hostile"),
        ):
            with self.subTest(field=field):
                with mock.patch.object(FETCH, field, replacement):
                    with self.assertRaises(FETCH.DirectFetchAcquisitionError):
                        server.assert_current()
        with mock.patch.object(FETCH.os, "read", lambda *_args: b""):
            with self.assertRaises(FETCH.DirectFetchAcquisitionError):
                server.assert_current()
        operation = CHANNEL.issue_fetch_terminal_minimum_bundle_operation(
            self.transport_raw, self.read_profile_raw,
            self.receipt["qsub"]["job_id"],
        )
        response = self.buffered_response(
            server, CHANNEL.project_fetch_request_frame_for_review(operation),
        )
        _owner, target = self.target()
        stream = self.through_pipe(
            response,
            lambda descriptor: FETCH._acquire_controller_fetch_stream_for_tests_once(
                target, operation, descriptor, _projection,
                _test_token=FETCH._TEST_TOKEN,
            ),
        )
        with mock.patch.object(FETCH, "_consume_for_materializer_once", lambda *_args: ({}, ())):
            with self.assertRaises((FETCH.DirectFetchAcquisitionError, MATERIALIZER.DirectLocalFetchMaterializerError)):
                MATERIALIZER.issue_closed_fetch_stream_lease_once(target, stream)

    def test_source_has_no_qsub_qdel_delete_cleanup_retry_or_caller_path_surface(self) -> None:
        source = (SCRIPTS / "direct_fetch_acquisition.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        calls = {
            node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
            for node in ast.walk(tree) if isinstance(node, ast.Call)
            and isinstance(node.func, (ast.Attribute, ast.Name))
        }
        self.assertTrue({"unlink", "remove", "rmdir", "qsub", "qdel"}.isdisjoint(calls))
        public = {node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and not node.name.startswith("_")}
        for forbidden in ("path", "basename", "root", "host", "argv", "environment", "subsystem", "retry", "cancel"):
            self.assertNotIn(forbidden, public)

    def test_direct_session_static_path_has_no_whole_bundle_or_spool_fallback(self) -> None:
        source = (SCRIPTS / "direct_fetch_acquisition.py").read_text(
            encoding="utf-8"
        )
        channel_source = (
            SCRIPTS / "direct_shared_fixed_ssh_channel.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("TemporaryFile", source)
        self.assertNotIn("spool", source.lower())
        tree = ast.parse(source)
        functions = {
            node.name: node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        acquire_calls = {
            node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
            for node in ast.walk(
                functions["_acquire_controller_fetch_stream_for_tests_once"]
            )
            if isinstance(node, ast.Call)
            and isinstance(node.func, (ast.Attribute, ast.Name))
        }
        self.assertNotIn(
            "_read_fetch_response_buffered_for_tests_until", acquire_calls,
        )
        self.assertNotIn("_parse_bundle", acquire_calls)
        self.assertNotIn("bytearray", acquire_calls)
        writer_calls = {
            node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
            for node in ast.walk(functions["write_response"])
            if isinstance(node, ast.Call)
            and isinstance(node.func, (ast.Attribute, ast.Name))
        }
        self.assertNotIn("join", writer_calls)
        self.assertNotIn("_read_current_file", writer_calls)
        self.assertEqual(FETCH.MAX_BUFFERED_TEST_BUNDLE_BYTES, 2 * 1024 * 1024)
        self.assertEqual(
            CHANNEL.MAX_BUFFERED_FETCH_TEST_BYTES, 2 * 1024 * 1024,
        )
        self.assertNotIn(
            '"_read_fetch_response_buffered_for_tests_until"',
            channel_source.split("__all__ =", 1)[1],
        )

    def test_buffered_test_helpers_require_exact_token_before_consumption(self) -> None:
        server, _projection = self.server_capability()
        operation = CHANNEL.issue_fetch_terminal_minimum_bundle_operation(
            self.transport_raw,
            self.read_profile_raw,
            self.receipt["qsub"]["job_id"],
        )
        request = CHANNEL.project_fetch_request_frame_for_review(operation)
        with self.assertRaises(FETCH.DirectFetchAcquisitionError):
            FETCH._build_terminal_minimum_response_for_tests_once(
                server, request, _test_token=object(),
            )
        server.assert_current()
        server.abandon_once()
        read_fd, write_fd = os.pipe()
        try:
            with self.assertRaises(CHANNEL.SharedFixedSSHChannelError):
                CHANNEL._read_fetch_response_buffered_for_tests_until(
                    read_fd,
                    operation,
                    time.monotonic() + 1.0,
                    _test_token=object(),
                )
            operation.assert_owner_sealed()
        finally:
            os.close(read_fd)
            os.close(write_fd)

    def test_named_skill_supplement_maps_only_owner_and_reference(self) -> None:
        manifest = json.loads((
            ROOT / "config/deployment-package-supplements/auto-g16-rtwin-pbs/direct-fetch-acquisition.json"
        ).read_text(encoding="utf-8"))
        self.assertEqual(manifest["schema"], "auto-g16-named-skill-package/1")
        self.assertEqual(manifest["skill"], "auto-g16-rtwin-pbs")
        self.assertEqual(
            manifest["include"],
            [
                {
                    "source": "scripts/direct_fetch_acquisition.py",
                    "target": "scripts/direct_fetch_acquisition.py",
                },
                {
                    "source": "docs/v2.7-direct-fetch-acquisition.md",
                    "target": "references/direct-fetch-acquisition.md",
                },
            ],
        )
        package = SKILL_PACKAGE.package_files_with_supplements(
            ROOT, "auto-g16-rtwin-pbs",
        )
        self.assertEqual(
            package[pathlib.Path("scripts/direct_fetch_acquisition.py")],
            ROOT / "scripts/direct_fetch_acquisition.py",
        )
        self.assertEqual(
            package[pathlib.Path("references/direct-fetch-acquisition.md")],
            ROOT / "docs/v2.7-direct-fetch-acquisition.md",
        )


if __name__ == "__main__":
    unittest.main()
