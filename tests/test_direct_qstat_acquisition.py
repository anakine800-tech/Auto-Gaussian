#!/usr/bin/env python3
"""Offline hostile tests for exact Q1 qstat acquisition and final /3."""

from __future__ import annotations

import copy
import gc
import hashlib
import json
import os
import pickle
import re
import signal
import stat
import subprocess
import struct
import sys
import tempfile
import threading
import time
import types
import unittest
import weakref
from pathlib import Path
from unittest import mock

from tests.test_direct_trusted_session_composition import PortableSessionFixture


ROOT = Path(__file__).parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import direct_qstat_acquisition as Q1  # noqa: E402
import direct_existing_job_lineage as LINEAGE  # noqa: E402
import direct_one_hop_transport as W5  # noqa: E402
import direct_read_only_evidence as W6C0  # noqa: E402
import direct_reviewed_read_profile as READ_PROFILE  # noqa: E402
import direct_shared_fixed_ssh_channel as CHANNEL  # noqa: E402
import direct_trusted_session_composition as SESSION  # noqa: E402


class DirectQstatAcquisitionTests(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="auto-g16-qstat-acquisition-")
        self.fixture = PortableSessionFixture(Path(self.temporary.name).resolve())
        capability = self.fixture.compose()
        seam = SESSION.consume_w5_operation_seam_once(capability.consume_for_w5_once())
        self.receipt = W5._consume_with_test_driver_once(
            seam,
            W5._test_driver(stdout=b"731.master\n"),
            _test_token=W5._TEST_DRIVER_TOKEN,
        ).portable_projection()
        self.receipt_raw = W5.canonical_bytes(self.receipt)
        transport = CHANNEL.load_transport_profile(self.fixture.artifacts.transport_profile)
        self.read_profile = {
            "schema": CHANNEL.READ_PROFILE_SCHEMA,
            "profile_id": "q1-offline-fixture",
            "transport_binding": {
                "schema": "exact_w5_transport_profile_bytes/1",
                "transport_profile_bytes_sha256": hashlib.sha256(
                    self.fixture.artifacts.transport_profile
                ).hexdigest(),
                "transport_profile_payload_sha256": transport["profile_payload_sha256"],
            },
            "server_read": {
                "source_sha256": CHANNEL._EXECUTED_SOURCE_SHA256,
                "qstat": {
                    "executable": "/usr/bin/qstat",
                    "executable_sha256": "a" * 64,
                    "executable_owner_uid": "0",
                    "executable_mode": "0755",
                    "max_stdout_bytes": str(Q1.MAX_QSTAT_STREAM_BYTES),
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
        self.read_profile["read_profile_payload_sha256"] = CHANNEL.digest(
            self.read_profile
        )
        self.read_profile_raw = CHANNEL.canonical_bytes(self.read_profile)
        self.requested_at = "2026-08-06T01:02:03.000000Z"
        self.collected_at = "2026-08-06T01:02:04.000000Z"
        self.received_at = "2026-08-06T01:02:05.000000Z"

    def tearDown(self) -> None:
        self.fixture.close()
        self.temporary.cleanup()

    def observation(
        self,
        *,
        stdout: bytes,
        stderr: bytes = b"",
        returncode: int | None = 0,
        timed_out: bool = False,
        eof_complete: bool = True,
        child_exit_code: int | None = 0,
        failure_reason: str | None = None,
    ) -> Q1._QstatObservation:
        return Q1._QstatObservation(
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
            timed_out=timed_out,
            eof_complete=eof_complete,
            child_exit_code=child_exit_code,
            requested_at=self.requested_at,
            collected_at=self.collected_at,
            executable_identity_sha256="b" * 64,
            failure_reason=failure_reason,
        )

    def acquire(
        self,
        observation: Q1._QstatObservation,
        *,
        received_at: str | None = None,
    ) -> tuple[Q1.ExactQstatAcquisitionResult, Q1._FakeQstatDriver, Q1._FakeQueryTransport]:
        driver = Q1._FakeQstatDriver(observation)
        server_profile_owner = READ_PROFILE.DirectReviewedReadProfileOwner._for_fake_local_testing(
            profile_raw=self.read_profile_raw,
            _test_token=READ_PROFILE._TEST_OWNER_TOKEN,
        )
        server = Q1.DirectQstatServerOwner._for_fake_local_testing(
            durable_state_root=self.fixture.state,
            driver=driver,
            read_profile_owner=server_profile_owner,
            _test_token=Q1._TEST_OWNER_TOKEN,
        )
        transport = Q1._FakeQueryTransport(server)
        controller_profile = self.controller_profile_capability()
        result = Q1._acquire_with_fake_transport_once(
            self.receipt_raw,
            self.fixture.artifacts,
            controller_profile,
            transport,
            received_at=self.received_at if received_at is None else received_at,
            _test_token=Q1._TEST_OWNER_TOKEN,
        )
        return result, driver, transport

    def controller_profile_capability(self) -> READ_PROFILE.DirectReviewedReadProfileCapability:
        return READ_PROFILE.DirectReviewedReadProfileOwner._for_fake_local_testing(
            profile_raw=self.read_profile_raw,
            _test_token=READ_PROFILE._TEST_OWNER_TOKEN,
        ).issue_once(self.fixture.artifacts.transport_profile)

    def prepare_controller(self) -> tuple[object, dict[str, object], bytes, object, object]:
        return Q1._prepare_controller_request(
            self.receipt_raw,
            self.fixture.artifacts,
            self.controller_profile_capability(),
        )

    @staticmethod
    def present(job_id: str = "731.master", project: str = "testjob") -> bytes:
        return (
            f"Job Id: {job_id}\n"
            f"    Job_Name = {project}\n"
            "    job_state = R\n"
        ).encode("ascii")

    def test_server_l1_lease_to_fixed_qstat_and_final_v3_success(self) -> None:
        result, driver, transport = self.acquire(
            self.observation(stdout=self.present(project=self.receipt["project"]))
        )
        result.assert_current()
        projection = result.portable_projection()
        self.assertEqual(projection, Q1.validate_acquisition_projection(projection))
        self.assertEqual(projection["lineage"]["job_id"], self.receipt["qsub"]["job_id"])
        self.assertEqual(
            projection["qstat"]["argv"],
            ["/usr/bin/qstat", "-f", self.receipt["qsub"]["job_id"]],
        )
        self.assertEqual(driver.calls, 1)
        self.assertEqual(transport.calls, 1)
        self.assertFalse(projection["authority"]["authorizes_effect"])
        self.assertFalse(projection["authority"]["qsub"])
        self.assertFalse(projection["authority"]["qdel"])
        for operation in (copy.copy, copy.deepcopy, pickle.dumps):
            with self.assertRaises(TypeError):
                operation(result)
        inspection = Q1.build_final_scheduler_inspection_once(result).document()
        self.assertEqual(inspection, Q1.validate_final_inspection(inspection))
        self.assertEqual(inspection["schema"], "gaussian-job-inspection/3")
        self.assertEqual(inspection["scheduler"]["status"], "present")
        self.assertEqual(inspection["scheduler"]["state"], "running")
        self.assertFalse(inspection["scheduler"]["pbs_terminal_is_gaussian_completion"])
        self.assertFalse(inspection["authority"]["scientific_acceptance"])
        with self.assertRaises(Q1.DirectQstatAcquisitionError):
            result.assert_current()
        with self.assertRaises(Q1.DirectQstatAcquisitionError):
            Q1.build_final_scheduler_inspection_once(result)

    def test_only_exact_unknown_job_line_is_absent(self) -> None:
        exact = self.observation(
            stdout=b"",
            stderr=b"qstat: Unknown Job Id 731.master\n",
            returncode=153,
            child_exit_code=153,
        )
        result, _, _ = self.acquire(exact)
        inspection = Q1.build_final_scheduler_inspection_once(result).document()
        self.assertEqual(inspection["scheduler"]["status"], "absent")
        self.assertEqual(inspection["scheduler"]["state"], "absent")

    def test_malformed_timeout_invalid_utf8_and_nonzero_are_unknown(self) -> None:
        cases = (
            self.observation(stdout=b"malformed\n"),
            self.observation(
                stdout=b"",
                returncode=None,
                timed_out=True,
                eof_complete=False,
                child_exit_code=None,
                failure_reason="timeout",
            ),
            self.observation(stdout=b"\xff\n"),
            self.observation(stdout=b"", stderr=b"qstat failed\n", returncode=2, child_exit_code=2),
        )
        for observation in cases:
            with self.subTest(observation=observation):
                # Every case needs a fresh completed W5/L1 fixture because the
                # exact lineage and server owners are deliberately single-use.
                self.tearDown()
                self.setUp()
                result, driver, transport = self.acquire(observation)
                inspection = Q1.build_final_scheduler_inspection_once(result).document()
                self.assertEqual(inspection["scheduler"]["status"], "unknown")
                self.assertEqual(inspection["scheduler"]["state"], "unknown")
                self.assertEqual(driver.calls, 1)
                self.assertEqual(transport.calls, 1)
                self.assertFalse(inspection["authority"]["qsub"])
                self.assertFalse(inspection["authority"]["qdel"])

    def test_caller_job_id_request_and_portable_upgrade_are_rejected(self) -> None:
        operation, request, _frame, _join, profile_lease = Q1._prepare_controller_request(
            self.receipt_raw,
            self.fixture.artifacts,
            self.controller_profile_capability(),
        )
        try:
            hostile = copy.deepcopy(request)
            hostile["expected_job_id"] = "999.master"
            hostile["request_id"] = Q1._request_id(
                hostile["artifact_sha256"],
                self.receipt_raw,
                self.read_profile_raw,
                hostile["operation_id"],
                hostile["expected_job_id"],
            )
            hostile["request_payload_sha256"] = ""
            hostile["request_payload_sha256"] = Q1.digest(hostile)
            with self.assertRaisesRegex(Q1.DirectQstatAcquisitionError, "receipt job"):
                Q1.validate_request(hostile)
        finally:
            CHANNEL._finish_operation(operation)
            profile_lease.close_once()

        binding = W6C0.DirectJobBinding(
            project=self.receipt["project"],
            job_id=self.receipt["qsub"]["job_id"],
            attempt_id=self.receipt["attempt_id"],
            input_sha256=self.receipt["input_sha256"],
            direct_binding_sha256=self.receipt["result_payload_sha256"],
        )
        provisional = W6C0.build_qstat_evidence(
            binding,
            W6C0.QstatObservation(
                returncode=0,
                stdout=self.present(project=self.receipt["project"]),
                stderr=b"",
                timed_out=False,
                eof_complete=True,
                requested_at=self.requested_at,
                collected_at=self.collected_at,
                received_at=self.received_at,
            ),
        )
        with self.assertRaisesRegex(Q1.DirectQstatAcquisitionError, "exact qstat acquisition"):
            Q1.build_final_scheduler_inspection_once(provisional)  # type: ignore[arg-type]
        with self.assertRaisesRegex(Q1.DirectQstatAcquisitionError, "exact qstat acquisition"):
            Q1.build_final_scheduler_inspection_once(provisional.document())  # type: ignore[arg-type]

    def test_result_fork_child_is_revoked_parent_remains_current(self) -> None:
        result, _, _ = self.acquire(
            self.observation(stdout=self.present(project=self.receipt["project"]))
        )
        read_fd, write_fd = os.pipe()
        pid = os.fork()
        if pid == 0:  # pragma: no cover - result reported to parent
            os.close(read_fd)
            try:
                result.assert_current()
            except BaseException:
                os.write(write_fd, b"rejected")
            else:
                os.write(write_fd, b"accepted")
            os.close(write_fd)
            os._exit(0)
        os.close(write_fd)
        child = os.read(read_fd, 64)
        os.close(read_fd)
        waited, status = os.waitpid(pid, 0)
        self.assertEqual(waited, pid)
        self.assertEqual(os.waitstatus_to_exitcode(status), 0)
        self.assertEqual(child, b"rejected")
        result.assert_current()
        Q1.build_final_scheduler_inspection_once(result)

    def test_result_owner_rejects_duplicate_raw_hash_size_and_time_splices(self) -> None:
        stdout = self.present(project=self.receipt["project"])
        result, _, _ = self.acquire(self.observation(stdout=stdout))
        projection = result.portable_projection()
        with self.assertRaisesRegex(Q1.DirectQstatAcquisitionError, "duplicate"):
            Q1._RESULT_ISSUE(projection, stdout, b"")

        hostile_bytes = copy.deepcopy(projection)
        hostile_bytes["collection"]["received_at"] = "2026-08-06T01:02:06.000000Z"
        hostile_bytes["collection"]["age_seconds"] = "2"
        hostile_bytes["acquisition_id"] = "direct-qstat-acquisition-" + Q1.digest(
            {
                "schema": "auto-g16-direct-qstat-acquisition-id/1",
                "lineage_id": hostile_bytes["lineage"]["lineage_id"],
                "operation_id": hostile_bytes["channel"]["operation_id"],
                "request_id": hostile_bytes["channel"]["request_id"],
                "response_payload_sha256": hostile_bytes["channel"]["response_payload_sha256"],
                "received_at": hostile_bytes["collection"]["received_at"],
            }
        )
        hostile_bytes["acquisition_payload_sha256"] = ""
        hostile_bytes["acquisition_payload_sha256"] = Q1.digest(hostile_bytes)
        with self.assertRaisesRegex(Q1.DirectQstatAcquisitionError, "private bytes"):
            Q1._RESULT_ISSUE(hostile_bytes, b"caller splice", b"")

        for field, value in (
            ("stdout_sha256", hashlib.sha256(b"caller splice").hexdigest()),
            ("stdout_size_bytes", str(len(stdout) + 1)),
        ):
            with self.subTest(field=field):
                hostile = copy.deepcopy(hostile_bytes)
                hostile["qstat"][field] = value
                hostile["acquisition_payload_sha256"] = ""
                hostile["acquisition_payload_sha256"] = Q1.digest(hostile)
                with self.assertRaisesRegex(
                    Q1.DirectQstatAcquisitionError,
                    "private bytes",
                ):
                    Q1._RESULT_ISSUE(hostile, stdout, b"")

        timestamp_splice = copy.deepcopy(projection)
        timestamp_splice["collection"]["received_at"] = "2026-08-06T01:03:05.000000Z"
        timestamp_splice["acquisition_payload_sha256"] = ""
        timestamp_splice["acquisition_payload_sha256"] = Q1.digest(timestamp_splice)
        with self.assertRaisesRegex(Q1.DirectQstatAcquisitionError, "freshness"):
            Q1.validate_acquisition_projection(timestamp_splice)

        inspection = Q1.build_final_scheduler_inspection_once(result).document()
        stale_upgrade = copy.deepcopy(inspection)
        stale_upgrade["scheduler"]["freshness"] = "stale"
        stale_upgrade["evidence_sha256"] = ""
        stale_upgrade["evidence_sha256"] = Q1.digest(stale_upgrade)
        with self.assertRaisesRegex(Q1.DirectQstatAcquisitionError, "present"):
            Q1.validate_final_inspection(stale_upgrade)

    def test_counterexample_raw_self_signed_read_profile_is_not_authority(self) -> None:
        # A controller-provided self-hashed document must not be sufficient to
        # select the production qstat executable hash, limits or timeout.
        hostile = copy.deepcopy(self.read_profile)
        hostile["server_read"]["qstat"]["executable_sha256"] = "f" * 64
        hostile["server_read"]["qstat"]["timeout_seconds"] = "299"
        hostile["read_profile_payload_sha256"] = ""
        hostile["read_profile_payload_sha256"] = CHANNEL.digest(hostile)
        hostile_raw = CHANNEL.canonical_bytes(hostile)
        with self.assertRaises((TypeError, Q1.DirectQstatAcquisitionError)):
            Q1._prepare_controller_request(
                self.receipt_raw,
                self.fixture.artifacts,
                hostile_raw,
            )

    def test_counterexample_generic_raw_job_id_issuer_is_not_production_reachable(self) -> None:
        self.assertNotIn("issue_query_exact_job_operation", CHANNEL.__all__)
        with self.assertRaises((TypeError, CHANNEL.SharedFixedSSHChannelError)):
            CHANNEL.issue_query_exact_job_operation(  # type: ignore[attr-defined]
                self.fixture.artifacts.transport_profile,
                self.read_profile_raw,
                "999.master",
            )

    def test_counterexample_join_registry_records_are_immutable(self) -> None:
        operation, _request, _frame, join, profile_lease = Q1._prepare_controller_request(
            self.receipt_raw,
            self.fixture.artifacts,
            self.controller_profile_capability(),
        )
        try:
            records: list[object] = []
            for cell in Q1._ISSUE_CONTROLLER_JOIN.__closure__ or ():
                value = cell.cell_contents
                if isinstance(value, weakref.WeakKeyDictionary):
                    records.extend(value.values())
            self.assertTrue(records)
            self.assertTrue(all(not isinstance(record, dict) for record in records))
            with self.assertRaises(AttributeError):
                join.status = "issued"  # type: ignore[attr-defined]
        finally:
            CHANNEL._finish_operation(operation)
            profile_lease.close_once()

    def test_counterexample_inconsistent_failure_cannot_upgrade_to_present(self) -> None:
        inconsistent = self.observation(
            stdout=self.present(project=self.receipt["project"]),
            returncode=0,
            child_exit_code=0,
            eof_complete=True,
            failure_reason="incomplete_eof",
        )
        with self.assertRaises(Q1.DirectQstatAcquisitionError):
            self.acquire(inconsistent)

    def test_counterexample_critical_rebinds_break_currentness(self) -> None:
        critical = (
            "_timestamp",
            "_utc_now_text",
            "_freshness",
            "_canonical_frame",
            "_decode_canonical_frame",
            "_production_qstat_once",
            "_open_reviewed_qstat",
            "_assert_qstat_descriptor_current",
            "_read_qstat_streams_until",
            "_prepare_controller_request",
            "acquire_qstat_once",
            "_acquisition_projection",
            "build_final_scheduler_inspection_once",
            "_read_stdin_frame_once",
            "_server_subsystem_main",
            "main",
            "_assert_shared_channel_query_issuance_authority",
            "_assert_shared_channel_query_authority",
            "_assert_exact_lineage_consumer_join",
        )
        for name in critical:
            with self.subTest(name=name):
                original = getattr(Q1, name)
                try:
                    setattr(Q1, name, lambda *_args, **_kwargs: None)
                    with self.assertRaises(Q1.DirectQstatAcquisitionError):
                        Q1._assert_module_binding()
                finally:
                    setattr(Q1, name, original)

        resolver_cases = (
            (
                CHANNEL, "_QSTAT_ISSUANCE_BINDING",
                CHANNEL._resolve_qstat_query_issuance_owner,
                "_assert_shared_channel_query_issuance_authority",
            ),
            (
                CHANNEL, "_QSTAT_OWNER_BINDING",
                CHANNEL._resolve_qstat_query_authority_owner,
                "_assert_shared_channel_query_authority",
            ),
            (
                LINEAGE, "_QSTAT_SUCCESSOR_BINDING",
                LINEAGE._resolve_qstat_successor_owner,
                "_assert_exact_lineage_consumer_join",
            ),
        )
        for owner_module, binding_name, resolver, wrapper_name in resolver_cases:
            with self.subTest(pre_first_resolution=wrapper_name):
                original_binding = getattr(owner_module, binding_name)
                original_wrapper = getattr(Q1, wrapper_name)
                try:
                    setattr(owner_module, binding_name, None)
                    setattr(Q1, wrapper_name, lambda *_args, **_kwargs: "999.master")
                    with self.assertRaises(Q1.DirectQstatAcquisitionError):
                        resolver()
                finally:
                    setattr(Q1, wrapper_name, original_wrapper)
                    setattr(owner_module, binding_name, original_binding)

        predecessor_rebinds = (
            (Q1.EVIDENCE, "classify_qstat_bytes"),
            (Q1.CHANNEL, "_pipe_cloexec"),
            (Q1.CHANNEL, "_wait_child_until"),
            (Q1.LINEAGE, "_consume_for_exact_qstat_once"),
        )
        for module, name in predecessor_rebinds:
            with self.subTest(module=module.__name__, name=name):
                original = getattr(module, name)
                try:
                    setattr(module, name, lambda *_args, **_kwargs: None)
                    with self.assertRaises(Q1.DirectQstatAcquisitionError):
                        Q1._assert_module_binding()
                finally:
                    setattr(module, name, original)

    def test_server_owner_composes_under_fixed_clean_exec_without_effect(self) -> None:
        module_path = SCRIPTS / "direct_qstat_acquisition.py"
        code = f"""
import importlib.util
import pathlib
import sys
path = pathlib.Path({str(module_path)!r})
spec = importlib.util.spec_from_file_location('direct_qstat_acquisition', path)
module = importlib.util.module_from_spec(spec)
sys.modules['direct_qstat_acquisition'] = module
spec.loader.exec_module(module)
owner = module.DirectQstatServerOwner.production()
assert type(owner) is module.DirectQstatServerOwner
assert owner._used is False
print('q1-clean-exec-owner-ok')
"""
        checked = subprocess.run(
            [sys.executable, "-I", "-S", "-c", code],
            cwd="/",
            env={"LANG": "C", "LC_ALL": "C"},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            text=True,
            timeout=30,
        )
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertEqual(checked.stdout, "q1-clean-exec-owner-ok\n")

    def test_review_profile_owner_capability_hash_single_use_and_no_override(self) -> None:
        owner = READ_PROFILE.DirectReviewedReadProfileOwner._for_fake_local_testing(
            profile_raw=self.read_profile_raw,
            _test_token=READ_PROFILE._TEST_OWNER_TOKEN,
        )
        capability = owner.issue_once(self.fixture.artifacts.transport_profile)
        projection = capability.portable_projection()
        self.assertEqual(projection, READ_PROFILE.validate_capability_projection(projection))
        self.assertEqual(projection["qstat_executable"], "/usr/bin/qstat")
        self.assertEqual(projection["qstat_max_stdout_bytes"], "65536")
        self.assertFalse(projection["authority"]["caller_profile_override"])
        for transform in (copy.copy, copy.deepcopy, pickle.dumps):
            with self.assertRaises(TypeError):
                transform(capability)
        with self.assertRaises(READ_PROFILE.DirectReviewedReadProfileError):
            owner.issue_once(self.fixture.artifacts.transport_profile)

        hostile = copy.deepcopy(projection)
        hostile["capability_id"] = "direct-reviewed-read-profile-" + "f" * 64
        hostile["projection_payload_sha256"] = ""
        hostile["projection_payload_sha256"] = READ_PROFILE.digest(hostile)
        with self.assertRaisesRegex(
            READ_PROFILE.DirectReviewedReadProfileError,
            "capability id",
        ):
            READ_PROFILE.validate_capability_projection(hostile)

        lease, raw, consumed_projection = READ_PROFILE._consume_for_q1_once(capability)
        try:
            self.assertEqual(raw, self.read_profile_raw)
            self.assertEqual(consumed_projection, projection)
            with self.assertRaises(READ_PROFILE.DirectReviewedReadProfileError):
                capability.assert_current()
        finally:
            lease.close_once()
        with self.assertRaises(READ_PROFILE.DirectReviewedReadProfileError):
            lease.assert_current()

    @unittest.skipUnless(hasattr(os, "fork"), "fork hostile check requires POSIX")
    def test_review_profile_capability_fork_child_is_revoked(self) -> None:
        capability = self.controller_profile_capability()
        read_fd, write_fd = os.pipe()
        pid = os.fork()
        if pid == 0:  # pragma: no cover - assertion returned through pipe
            os.close(read_fd)
            try:
                capability.assert_current()
            except BaseException:
                os.write(write_fd, b"rejected")
            else:
                os.write(write_fd, b"accepted")
            os.close(write_fd)
            os._exit(0)
        os.close(write_fd)
        child = os.read(read_fd, 32)
        os.close(read_fd)
        self.assertEqual(os.waitpid(pid, 0)[0], pid)
        self.assertEqual(child, b"rejected")
        lease, _raw, _projection = READ_PROFILE._consume_for_q1_once(capability)
        lease.close_once()

    def test_abandoned_review_profile_capability_is_not_kept_alive_by_registry(self) -> None:
        capability = self.controller_profile_capability()
        capability_ref = weakref.ref(capability)
        del capability
        for _index in range(3):
            gc.collect()
        self.assertIsNone(capability_ref())

    def test_abandoned_production_profile_capability_finalizer_closes_source_fd(self) -> None:
        profile_path = Path(self.temporary.name) / "profile-source.json"
        profile_path.write_bytes(self.read_profile_raw)
        descriptor = os.open(profile_path, os.O_RDONLY)
        identity = READ_PROFILE._file_identity(os.fstat(descriptor))
        projection = READ_PROFILE._projection(
            self.read_profile_raw,
            self.read_profile,
            self.fixture.artifacts.transport_profile,
            source="fixed_backend_file",
            source_identity_sha256="c" * 64,
            issuance_nonce_sha256="d" * 64,
        )
        with mock.patch.object(READ_PROFILE, "_assert_fixed_source_current"):
            capability = READ_PROFILE._CAP_ISSUE(
                self.read_profile_raw,
                projection,
                descriptor,
                identity,
            )
        capability_ref = weakref.ref(capability)
        del capability
        for _index in range(3):
            gc.collect()
        self.assertIsNone(capability_ref())
        with self.assertRaises(OSError):
            os.fstat(descriptor)

    def test_abandoned_q1_weak_keys_collect_and_result_id_becomes_terminal(self) -> None:
        issuance = Q1._ISSUE_QUERY_ISSUANCE_JOIN(
            self.receipt["qsub"]["job_id"],
            self.fixture.artifacts.transport_profile,
            self.read_profile_raw,
            "direct-reviewed-read-profile-" + "c" * 64,
            hashlib.sha256(self.receipt_raw).hexdigest(),
        )
        issuance_ref = weakref.ref(issuance)
        del issuance

        lineage_capability = LINEAGE.DirectExistingJobLineageOwner._for_fake_local_testing(
            durable_state_root=self.fixture.state,
            _test_token=LINEAGE._TEST_OWNER_TOKEN,
        ).issue_once(self.receipt_raw, self.fixture.artifacts)
        lineage_join = Q1._ISSUE_LINEAGE_JOIN(lineage_capability)
        lineage_ref = weakref.ref(lineage_join)
        del lineage_join

        operation, _request, _frame, controller_join, profile_lease = self.prepare_controller()
        controller_ref = weakref.ref(controller_join)
        del controller_join
        CHANNEL._finish_operation(operation)
        profile_lease.close_once()

        for _index in range(3):
            gc.collect()
        self.assertIsNone(issuance_ref())
        self.assertIsNone(lineage_ref())
        self.assertIsNone(controller_ref())

        # L1 deliberately forbids replaying the same lineage ID in one
        # process.  Use a fresh artifact-root fixture for the independent
        # abandoned-result policy check.
        del lineage_capability
        self.tearDown()
        self.setUp()

        stdout = self.present(project=self.receipt["project"])
        result, _, _ = self.acquire(self.observation(stdout=stdout))
        projection = result.portable_projection()
        result_ref = weakref.ref(result)
        del result
        for _index in range(3):
            gc.collect()
        self.assertIsNone(result_ref())
        with self.assertRaisesRegex(Q1.DirectQstatAcquisitionError, "duplicate"):
            Q1._RESULT_ISSUE(projection, stdout, b"")

    def test_request_receipt_artifact_job_auth_and_profile_splices_fail_closed(self) -> None:
        operation, request, _frame, _join, profile_lease = Q1._prepare_controller_request(
            self.receipt_raw,
            self.fixture.artifacts,
            self.controller_profile_capability(),
        )
        try:
            hostile_cases: list[dict[str, object]] = []

            job_splice = copy.deepcopy(request)
            job_splice["expected_job_id"] = "999.master"
            job_splice["request_id"] = Q1._request_id(
                job_splice["artifact_sha256"],
                self.receipt_raw,
                self.read_profile_raw,
                job_splice["operation_id"],
                job_splice["expected_job_id"],
            )
            hostile_cases.append(job_splice)

            artifact_splice = copy.deepcopy(request)
            artifact_splice["artifact_sha256"]["authorization"] = "f" * 64
            hostile_cases.append(artifact_splice)

            auth_splice = copy.deepcopy(request)
            auth_raw = bytearray(
                Q1._unb64(
                    auth_splice["artifacts"]["authorization"],
                    "authorization",
                    Q1.MAX_REQUEST_BYTES,
                )
            )
            auth_raw[-1] ^= 1
            auth_splice["artifacts"]["authorization"] = Q1._b64(bytes(auth_raw))
            auth_splice["artifact_sha256"]["authorization"] = hashlib.sha256(auth_raw).hexdigest()
            hostile_cases.append(auth_splice)

            profile_splice = copy.deepcopy(request)
            hostile_profile = copy.deepcopy(self.read_profile)
            hostile_profile["server_read"]["qstat"]["executable_sha256"] = "f" * 64
            hostile_profile["read_profile_payload_sha256"] = ""
            hostile_profile["read_profile_payload_sha256"] = CHANNEL.digest(hostile_profile)
            hostile_profile_raw = CHANNEL.canonical_bytes(hostile_profile)
            profile_splice["read_profile_base64"] = Q1._b64(hostile_profile_raw)
            profile_splice["read_profile_bytes_sha256"] = hashlib.sha256(hostile_profile_raw).hexdigest()
            profile_splice["read_profile_payload_sha256"] = hostile_profile["read_profile_payload_sha256"]
            profile_splice["request_id"] = Q1._request_id(
                profile_splice["artifact_sha256"],
                self.receipt_raw,
                hostile_profile_raw,
                profile_splice["operation_id"],
                profile_splice["expected_job_id"],
            )
            hostile_cases.append(profile_splice)

            receipt_splice = copy.deepcopy(request)
            receipt_bytes = bytearray(self.receipt_raw)
            receipt_bytes[-2] ^= 1
            receipt_splice["portable_receipt_base64"] = Q1._b64(bytes(receipt_bytes))
            receipt_splice["portable_receipt_bytes_sha256"] = hashlib.sha256(receipt_bytes).hexdigest()
            hostile_cases.append(receipt_splice)

            for hostile in hostile_cases:
                hostile["request_payload_sha256"] = ""
                hostile["request_payload_sha256"] = Q1.digest(hostile)
                with self.subTest(case=hostile_cases.index(hostile)):
                    with self.assertRaises((Q1.DirectQstatAcquisitionError, ValueError)):
                        Q1.validate_request(hostile)
        finally:
            CHANNEL._finish_operation(operation)
            profile_lease.close_once()

    def test_closed_outcome_sum_type_rejects_all_cross_field_conflicts(self) -> None:
        conflicts = (
            self.observation(stdout=b"", timed_out=True, eof_complete=False, returncode=0, child_exit_code=0, failure_reason="timeout"),
            self.observation(stdout=b"", eof_complete=True, returncode=None, child_exit_code=None, failure_reason="incomplete_eof"),
            self.observation(stdout=b"", eof_complete=True, returncode=None, child_exit_code=None, failure_reason="output_too_large"),
            self.observation(stdout=b"", eof_complete=False, returncode=None, child_exit_code=None, failure_reason="child_exit_ambiguous"),
            self.observation(stdout=self.present(project=self.receipt["project"]), returncode=0, child_exit_code=1),
        )
        for observation in conflicts:
            with self.subTest(reason=observation.failure_reason, rc=observation.returncode):
                with self.assertRaisesRegex(Q1.DirectQstatAcquisitionError, "contradictory"):
                    Q1._normalize_observation(
                        self.receipt["qsub"]["job_id"],
                        self.receipt["project"],
                        observation,
                    )

    def test_stale_present_bytes_are_effectively_unknown(self) -> None:
        result, driver, transport = self.acquire(
            self.observation(stdout=self.present(project=self.receipt["project"])),
            received_at="2026-08-06T01:20:05.000000Z",
        )
        inspection = Q1.build_final_scheduler_inspection_once(result).document()
        self.assertEqual(inspection["scheduler"]["freshness"], "stale")
        self.assertEqual(inspection["scheduler"]["status"], "unknown")
        self.assertEqual(inspection["scheduler"]["reason"], "stale_or_invalid_freshness")
        self.assertEqual(driver.calls, 1)
        self.assertEqual(transport.calls, 1)

    def test_qstat_descriptor_policy_rejects_hash_mode_link_and_path_fallback(self) -> None:
        executable = Path(self.temporary.name) / "fake-qstat"
        executable.write_bytes(b"#!/bin/sh\nexit 0\n")
        executable.chmod(0o755)
        profile = copy.deepcopy(self.read_profile)
        qstat = profile["server_read"]["qstat"]
        qstat["executable"] = str(executable)
        qstat["executable_sha256"] = hashlib.sha256(executable.read_bytes()).hexdigest()
        qstat["executable_owner_uid"] = "0"
        qstat["executable_mode"] = "0755"

        actual = executable.stat()

        def synthetic_info(*, mode: int = 0o755, nlink: int = 1, ino: int | None = None) -> object:
            return types.SimpleNamespace(
                st_dev=actual.st_dev,
                st_ino=actual.st_ino if ino is None else ino,
                st_uid=0,
                st_gid=0,
                st_mode=stat.S_IFREG | mode,
                st_nlink=nlink,
                st_size=len(executable.read_bytes()),
                st_mtime_ns=actual.st_mtime_ns,
                st_ctime_ns=actual.st_ctime_ns,
            )

        frozen = synthetic_info()
        with mock.patch.object(Q1, "QSTAT_EXECUTABLE", str(executable)):
            # The real local file is not root-owned and must never be accepted
            # merely because a caller profile names its uid.
            with self.assertRaisesRegex(Q1.DirectQstatAcquisitionError, "runtime owner"):
                Q1._open_reviewed_qstat(profile)

            with mock.patch.object(Q1.os, "fstat", return_value=frozen), \
                    mock.patch.object(Q1.os, "stat", return_value=frozen):
                descriptor, identity_sha256, identity = Q1._open_reviewed_qstat(profile)
            try:
                self.assertRegex(identity_sha256, r"^[a-f0-9]{64}$")
                # Reproduce the old P1: same open descriptor and synthetic
                # inode identity, but bytes changed after initial open/hash.
                executable.write_bytes(b"#!/bin/sh\nexit 9\n")
                with mock.patch.object(Q1.os, "fstat", return_value=frozen), \
                        mock.patch.object(Q1.os, "stat", return_value=frozen), \
                        mock.patch.object(CHANNEL, "_descriptor_execve") as executor:
                    with self.assertRaisesRegex(
                        Q1.DirectQstatAcquisitionError,
                        "effect-immediate identity or hash",
                    ):
                        Q1._exec_reviewed_qstat_child_once(
                            descriptor,
                            identity,
                            qstat["executable_sha256"],
                            (str(executable), "-f", "731.master"),
                        )
                    executor.assert_not_called()

                for hostile_info in (
                    synthetic_info(mode=0o775),
                    synthetic_info(nlink=2),
                ):
                    hostile_identity = Q1._executable_identity(hostile_info)
                    with mock.patch.object(Q1.os, "fstat", return_value=hostile_info), \
                            mock.patch.object(Q1.os, "stat", return_value=hostile_info):
                        with self.assertRaisesRegex(
                            Q1.DirectQstatAcquisitionError,
                            "runtime owner",
                        ):
                            Q1._assert_qstat_descriptor_current(
                                descriptor,
                                hostile_identity,
                                hashlib.sha256(executable.read_bytes()).hexdigest(),
                            )

                replacement = synthetic_info(ino=actual.st_ino + 1)
                with mock.patch.object(Q1.os, "fstat", return_value=frozen), \
                        mock.patch.object(Q1.os, "stat", return_value=replacement):
                    with self.assertRaisesRegex(
                        Q1.DirectQstatAcquisitionError,
                        "effect-immediate identity",
                    ):
                        Q1._assert_qstat_descriptor_current(
                            descriptor,
                            identity,
                            hashlib.sha256(executable.read_bytes()).hexdigest(),
                        )
            finally:
                os.close(descriptor)

        with mock.patch.object(Q1.os, "open", side_effect=FileNotFoundError("missing")) as opener:
            with self.assertRaises(FileNotFoundError):
                Q1._open_reviewed_qstat(self.read_profile)
        opener.assert_called_once_with(
            "/usr/bin/qstat",
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
        )

    def test_qstat_constants_and_os_primitives_are_currentness_bound(self) -> None:
        original_executable = Q1.QSTAT_EXECUTABLE
        try:
            Q1.QSTAT_EXECUTABLE = "/tmp/caller-qstat"
            with self.assertRaises(Q1.DirectQstatAcquisitionError):
                Q1._assert_module_binding()
        finally:
            Q1.QSTAT_EXECUTABLE = original_executable
        with mock.patch.object(Q1.os, "open", lambda *_args, **_kwargs: -1):
            with self.assertRaises(Q1.DirectQstatAcquisitionError):
                Q1._assert_module_binding()

        mutations = (
            ("AUTHORITY", "authorizes_effect", True, Q1.validate_request),
            ("FINAL_AUTHORITY", "scheduler_evidence_only", False, Q1.validate_final_inspection),
        )
        for name, field, hostile, validator in mutations:
            with self.subTest(name=name, field=field):
                value = getattr(Q1, name)
                original = value[field]
                try:
                    value[field] = hostile
                    with self.assertRaises(Q1.DirectQstatAcquisitionError):
                        Q1._assert_module_binding()
                    with self.assertRaisesRegex(
                        Q1.DirectQstatAcquisitionError,
                        "source, module, predecessor, or owner binding",
                    ):
                        validator({})
                finally:
                    value[field] = original
        for name, hostile, validator in (
            ("MAX_FRESH_AGE_SECONDS", 999999, Q1.validate_acquisition_projection),
            ("TIMESTAMP_RE", re.compile(r".*"), Q1.validate_acquisition_projection),
            ("ACQUISITION_ID_RE", re.compile(r".*"), Q1.validate_acquisition_projection),
            ("SHA_RE", re.compile(r".*"), Q1.validate_final_inspection),
        ):
            with self.subTest(name=name):
                original = getattr(Q1, name)
                try:
                    setattr(Q1, name, hostile)
                    with self.assertRaises(Q1.DirectQstatAcquisitionError):
                        Q1._assert_module_binding()
                    with self.assertRaisesRegex(
                        Q1.DirectQstatAcquisitionError,
                        "source, module, predecessor, or owner binding",
                    ):
                        validator({})
                finally:
                    setattr(Q1, name, original)

        for name, hostile in (
            ("finalize", lambda *_args, **_kwargs: None),
            ("WeakKeyDictionary", dict),
        ):
            with self.subTest(weakref_runtime=name):
                original = getattr(Q1.weakref, name)
                try:
                    setattr(Q1.weakref, name, hostile)
                    with self.assertRaises(Q1.DirectQstatAcquisitionError):
                        Q1._assert_module_binding()
                    with self.assertRaises(READ_PROFILE.DirectReviewedReadProfileError):
                        READ_PROFILE._assert_module_binding()
                finally:
                    setattr(Q1.weakref, name, original)

    def test_controller_query_runner_uses_one_absolute_deadline(self) -> None:
        operation, _request, frame, join, profile_lease = self.prepare_controller()
        child_handle = object.__new__(CHANNEL._QueryChildHandle)
        try:
            response = {"offline": "response"}
            with mock.patch.object(CHANNEL, "_assert_production_binding"), \
                    mock.patch.object(
                        CHANNEL,
                        "_resolve_qstat_query_authority_owner",
                        return_value=(
                            Q1._assert_shared_channel_query_authority,
                            Q1._ControllerQueryJoin,
                        ),
                    ), \
                    mock.patch.object(CHANNEL, "_require_descriptor_exec_available"), \
                    mock.patch.object(CHANNEL, "_open_reviewed_executable", return_value=50), \
                    mock.patch.object(CHANNEL, "_pipe_cloexec", side_effect=[(10, 11), (12, 13), (14, 15)]), \
                    mock.patch.object(
                        CHANNEL,
                        "_fork_query_child_for_operation",
                        return_value=(999, child_handle),
                    ), \
                    mock.patch.object(CHANNEL, "_close_quiet"), \
                    mock.patch.object(CHANNEL.time, "monotonic", return_value=100.0) as monotonic, \
                    mock.patch.object(CHANNEL, "_send_frame_until") as sender, \
                    mock.patch.object(CHANNEL, "_read_query_transport_until", return_value=response) as reader, \
                    mock.patch.object(CHANNEL, "_wait_query_child_until", return_value=0) as waiter, \
                    mock.patch.object(CHANNEL, "_retire_query_child_bounded") as retirer:
                self.assertEqual(CHANNEL.run_query_channel_once(operation, frame, join), response)
            monotonic.assert_called_once_with()
            sender.assert_called_once_with(11, frame, 165.0)
            reader.assert_called_once_with(12, 14, 165.0)
            waiter.assert_called_once_with(child_handle, 165.0)
            retirer.assert_not_called()
        finally:
            profile_lease.close_once()

    def test_controller_partial_read_stderr_and_child_ambiguity_are_terminal_no_retry(self) -> None:
        failures = ("write", "read", "wait")
        for failure in failures:
            with self.subTest(failure=failure):
                operation, _request, frame, join, profile_lease = self.prepare_controller()
                child_handle = object.__new__(CHANNEL._QueryChildHandle)
                try:
                    write_effect = RuntimeError("partial write") if failure == "write" else None
                    read_effect = RuntimeError("stderr or incomplete response") if failure == "read" else None
                    wait_effect = RuntimeError("child retirement ambiguity") if failure == "wait" else None
                    with mock.patch.object(CHANNEL, "_assert_production_binding"), \
                            mock.patch.object(
                                CHANNEL,
                                "_resolve_qstat_query_authority_owner",
                                return_value=(
                                    Q1._assert_shared_channel_query_authority,
                                    Q1._ControllerQueryJoin,
                                ),
                            ), \
                            mock.patch.object(CHANNEL, "_require_descriptor_exec_available"), \
                            mock.patch.object(CHANNEL, "_open_reviewed_executable", return_value=50), \
                            mock.patch.object(CHANNEL, "_pipe_cloexec", side_effect=[(10, 11), (12, 13), (14, 15)]), \
                            mock.patch.object(
                                CHANNEL,
                                "_fork_query_child_for_operation",
                                return_value=(999, child_handle),
                            ), \
                            mock.patch.object(CHANNEL, "_close_quiet"), \
                            mock.patch.object(CHANNEL.time, "monotonic", return_value=100.0), \
                            mock.patch.object(CHANNEL, "_send_frame_until", side_effect=write_effect), \
                            mock.patch.object(CHANNEL, "_read_query_transport_until", return_value={"offline": "response"}, side_effect=read_effect), \
                            mock.patch.object(CHANNEL, "_wait_query_child_until", return_value=0, side_effect=wait_effect), \
                            mock.patch.object(CHANNEL, "_retire_query_child_bounded") as retirer:
                        with self.assertRaises(CHANNEL.ControllerTransportUnknown):
                            CHANNEL.run_query_channel_once(operation, frame, join)
                        retirer.assert_called_once_with(child_handle)
                        with self.assertRaisesRegex(CHANNEL.SharedFixedSSHChannelError, "terminal"):
                            CHANNEL.run_query_channel_once(operation, frame, join)
                finally:
                    profile_lease.close_once()

    def test_query_child_retirement_signals_only_exact_pid_and_reaps(self) -> None:
        self.assertFalse(hasattr(CHANNEL, "_issue_query_child_handle"))

        def cleanup_child(pid: int) -> None:
            try:
                waited, _status = os.waitpid(pid, os.WNOHANG)
            except ChildProcessError:
                return
            if waited == 0:
                os.kill(pid, signal.SIGKILL)
                os.waitpid(pid, 0)

        def fork_bound_child() -> tuple[CHANNEL.QueryExactJobOperation, int, object]:
            operation = CHANNEL._issue_query_exact_job_operation_for_testing(
                self.fixture.artifacts.transport_profile,
                self.read_profile_raw,
                self.receipt["qsub"]["job_id"],
                _test_token=CHANNEL._QUERY_CODEC_TEST_TOKEN,
            )
            CHANNEL._claim_query_operation(operation)
            ready_read, ready_write = os.pipe()
            pid, handle = CHANNEL._fork_query_child_for_operation(operation)
            if pid == 0:  # pragma: no cover - parent audits exact handle
                os.close(ready_read)
                signal.signal(signal.SIGTERM, signal.SIG_IGN)
                os.write(ready_write, b"ready")
                os.close(ready_write)
                time.sleep(30)
                os._exit(0)
            os.close(ready_write)
            try:
                self.assertEqual(os.read(ready_read, 5), b"ready")
            finally:
                os.close(ready_read)
            self.assertIsNotNone(handle)
            return operation, pid, handle

        sibling_read, sibling_write = os.pipe()
        sibling_pid = os.fork()
        if sibling_pid == 0:  # pragma: no cover - parent proves no authority
            os.close(sibling_read)
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            os.write(sibling_write, b"ready")
            os.close(sibling_write)
            time.sleep(30)
            os._exit(0)
        os.close(sibling_write)
        try:
            self.assertEqual(os.read(sibling_read, 5), b"ready")
            with mock.patch.object(CHANNEL.os, "kill") as killer:
                self.assertFalse(CHANNEL._retire_query_child_bounded(sibling_pid))
            killer.assert_not_called()
            self.assertEqual(os.waitpid(sibling_pid, os.WNOHANG), (0, 0))
        finally:
            os.close(sibling_read)
            cleanup_child(sibling_pid)

        operation, foreign_pid, foreign = fork_bound_child()
        try:
            with mock.patch.object(CHANNEL, "_assert_production_binding"), \
                    mock.patch.object(CHANNEL.os, "waitpid", side_effect=ChildProcessError("foreign")), \
                    mock.patch.object(CHANNEL.os, "kill") as killer:
                self.assertFalse(CHANNEL._retire_query_child_bounded(foreign))
            killer.assert_not_called()
        finally:
            CHANNEL._finish_operation(operation)
            cleanup_child(foreign_pid)

        operation, missing_pid, missing = fork_bound_child()
        try:
            with mock.patch.object(CHANNEL, "_assert_production_binding"), \
                    mock.patch.object(CHANNEL.os, "waitpid", return_value=(0, 0)), \
                    mock.patch.object(CHANNEL.os, "kill", side_effect=ProcessLookupError("gone")) as killer:
                self.assertFalse(CHANNEL._retire_query_child_bounded(missing))
            killer.assert_called_once_with(missing_pid, signal.SIGTERM)
        finally:
            CHANNEL._finish_operation(operation)
            cleanup_child(missing_pid)

        operation, pid, handle = fork_bound_child()
        try:
            self.assertTrue(CHANNEL._retire_query_child_bounded(handle))
            with self.assertRaises(ChildProcessError):
                os.waitpid(pid, os.WNOHANG)
        finally:
            CHANNEL._finish_operation(operation)
            cleanup_child(pid)

    def test_query_fork_transition_failure_is_unknown_and_operation_terminal(self) -> None:
        operation, _request, frame, join, profile_lease = self.prepare_controller()
        try:
            with mock.patch.object(CHANNEL, "_assert_production_binding"), \
                    mock.patch.object(
                        CHANNEL,
                        "_resolve_qstat_query_authority_owner",
                        return_value=(
                            Q1._assert_shared_channel_query_authority,
                            Q1._ControllerQueryJoin,
                        ),
                    ), \
                    mock.patch.object(CHANNEL, "_require_descriptor_exec_available"), \
                    mock.patch.object(CHANNEL, "_open_reviewed_executable", return_value=50), \
                    mock.patch.object(CHANNEL, "_pipe_cloexec", side_effect=[(10, 11), (12, 13), (14, 15)]), \
                    mock.patch.object(CHANNEL, "_close_quiet"), \
                    mock.patch.object(
                        CHANNEL,
                        "_fork_query_child_for_operation",
                        side_effect=RuntimeError("atomic query fork failed"),
                    ), \
                    mock.patch.object(CHANNEL.os, "kill") as killer:
                with self.assertRaisesRegex(
                    CHANNEL.ControllerTransportUnknown,
                    "fork/registration is unknown; no retry",
                ) as raised:
                    CHANNEL.run_query_channel_once(operation, frame, join)
            self.assertIsInstance(raised.exception.__cause__, RuntimeError)
            killer.assert_not_called()
            with self.assertRaisesRegex(CHANNEL.SharedFixedSSHChannelError, "terminal"):
                CHANNEL.run_query_channel_once(operation, frame, join)
        finally:
            profile_lease.close_once()

    def test_query_atomic_postfork_registration_failure_reaps_own_child(self) -> None:
        operation = CHANNEL._issue_query_exact_job_operation_for_testing(
            self.fixture.artifacts.transport_profile,
            self.read_profile_raw,
            self.receipt["qsub"]["job_id"],
            _test_token=CHANNEL._QUERY_CODEC_TEST_TOKEN,
        )
        CHANNEL._claim_query_operation(operation)
        observed_parent_pids: list[int] = []
        real_fork = CHANNEL._FROZEN_FORK

        def captured_fork() -> int:
            pid = real_fork()
            if pid > 0:
                observed_parent_pids.append(pid)
            return pid

        try:
            with mock.patch.object(CHANNEL, "_assert_production_binding"), \
                    mock.patch.object(CHANNEL, "_FROZEN_FORK", side_effect=captured_fork), \
                    mock.patch.object(
                        CHANNEL,
                        "_QueryChildRecord",
                        side_effect=RuntimeError("postfork registration failed"),
                    ):
                try:
                    pid, _handle = CHANNEL._fork_query_child_for_operation(operation)
                except RuntimeError as exc:
                    self.assertIn("postfork registration failed", str(exc))
                else:
                    if pid == 0:  # pragma: no cover - owner parent reaps this child
                        os._exit(0)
                    self.fail("postfork registration failure was not propagated")
            self.assertEqual(len(observed_parent_pids), 1)
            with self.assertRaises(ChildProcessError):
                os.waitpid(observed_parent_pids[0], os.WNOHANG)
        finally:
            CHANNEL._finish_operation(operation)
            for pid in observed_parent_pids:
                try:
                    waited, _status = os.waitpid(pid, os.WNOHANG)
                except ChildProcessError:
                    continue
                if waited == 0:
                    os.kill(pid, signal.SIGKILL)
                    os.waitpid(pid, 0)

    def test_query_child_raw_numeric_handle_issuance_is_absent(self) -> None:
        with mock.patch.object(CHANNEL.os, "kill") as killer:
            self.assertFalse(CHANNEL._retire_query_child_bounded(424242))
        killer.assert_not_called()

    def test_controller_transport_reader_rejects_zero_oversize_truncated_extra_second_and_stderr(self) -> None:
        frame = Q1._canonical_frame({"offline": "response"}, Q1.MAX_RESPONSE_BYTES)

        def read_pair(response_bytes: bytes, stderr_bytes: bytes = b"") -> dict[str, object]:
            response_read, response_write = os.pipe()
            stderr_read, stderr_write = os.pipe()
            try:
                os.write(response_write, response_bytes)
                os.close(response_write)
                response_write = -1
                if stderr_bytes:
                    os.write(stderr_write, stderr_bytes)
                os.close(stderr_write)
                stderr_write = -1
                return CHANNEL._read_query_transport_until(
                    response_read,
                    stderr_read,
                    time.monotonic() + 1.0,
                )
            finally:
                os.close(response_read)
                os.close(stderr_read)
                if response_write >= 0:
                    os.close(response_write)
                if stderr_write >= 0:
                    os.close(stderr_write)

        self.assertEqual(read_pair(frame), {"offline": "response"})
        hostile_frames = (
            struct.pack("!I", 0),
            struct.pack("!I", CHANNEL.MAX_CONTROL_FRAME_BYTES + 1),
            frame[:-1],
            frame + b"x",
            frame + frame,
            struct.pack("!I", 1) + b"\xff",
        )
        for hostile in hostile_frames:
            with self.subTest(size=len(hostile)):
                with self.assertRaises(CHANNEL.SharedFixedSSHChannelError):
                    read_pair(hostile)
        with self.assertRaisesRegex(CHANNEL.SharedFixedSSHChannelError, "stderr"):
            read_pair(frame, b"ssh warning\n")

        response_read, response_write = os.pipe()
        stderr_read, stderr_write = os.pipe()

        def write_oversized_response() -> None:
            remaining = CHANNEL.MAX_QUERY_RESPONSE_FRAME_BYTES + 5
            try:
                while remaining:
                    chunk = b"x" * min(65536, remaining)
                    os.write(response_write, chunk)
                    remaining -= len(chunk)
            except BrokenPipeError:
                pass
            finally:
                os.close(response_write)

        writer = threading.Thread(target=write_oversized_response)
        writer.start()
        os.close(stderr_write)
        try:
            with self.assertRaisesRegex(CHANNEL.SharedFixedSSHChannelError, "exceeds"):
                CHANNEL._read_query_transport_until(
                    response_read,
                    stderr_read,
                    time.monotonic() + 1.0,
                )
        finally:
            os.close(response_read)
            os.close(stderr_read)
            writer.join(timeout=1.0)
        self.assertFalse(writer.is_alive())

        response_read, response_write = os.pipe()
        stderr_read, stderr_write = os.pipe()
        try:
            with self.assertRaises(CHANNEL.ControllerTransportUnknown):
                CHANNEL._read_query_transport_until(
                    response_read,
                    stderr_read,
                    time.monotonic() + 0.01,
                )
        finally:
            for descriptor in (response_read, response_write, stderr_read, stderr_write):
                os.close(descriptor)

    def test_fake_observation_cannot_exceed_production_combined_stream_cap(self) -> None:
        with self.assertRaisesRegex(Q1.DirectQstatAcquisitionError, "combined streams"):
            self.observation(
                stdout=b"x" * Q1.MAX_QSTAT_STREAM_BYTES,
                stderr=b"y",
            )

    def test_reviewed_profile_descriptor_rejects_named_file_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            profile_path = Path(temporary_directory) / "reviewed-profile.json"
            replacement_path = Path(temporary_directory) / "replacement.json"
            profile_path.write_bytes(self.read_profile_raw)
            descriptor = os.open(profile_path, os.O_RDONLY)
            try:
                identity = READ_PROFILE._file_identity(os.fstat(descriptor))
                with mock.patch.object(
                    READ_PROFILE,
                    "FIXED_PRODUCTION_READ_PROFILE_PATH",
                    profile_path,
                ):
                    READ_PROFILE._assert_fixed_source_current(
                        descriptor,
                        identity,
                        self.read_profile_raw,
                    )
                    replacement_path.write_bytes(self.read_profile_raw)
                    os.replace(replacement_path, profile_path)
                    with self.assertRaisesRegex(
                        READ_PROFILE.DirectReviewedReadProfileError,
                        "drifted",
                    ):
                        READ_PROFILE._assert_fixed_source_current(
                            descriptor,
                            identity,
                            self.read_profile_raw,
                        )
            finally:
                os.close(descriptor)


if __name__ == "__main__":
    unittest.main()
