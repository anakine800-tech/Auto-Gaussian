#!/usr/bin/env python3
"""Offline hostile tests for the terminal fetch grant composition owner."""

from __future__ import annotations

import copy
import ast
import dataclasses
import hashlib
import inspect
import json
import os
import pathlib
import pickle
import socket
import stat
import struct
import sys
import time
import unittest
from unittest import mock

import tests.test_direct_qstat_acquisition as Q1_TESTS


ROOT = pathlib.Path(__file__).parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import direct_minimum_production_closure as CLOSURE  # noqa: E402
import direct_existing_job_lineage as LINEAGE  # noqa: E402
import direct_fetch_acquisition as FETCH  # noqa: E402
import direct_local_fetch_materializer as MATERIALIZER  # noqa: E402
import direct_qstat_acquisition as Q1  # noqa: E402
import direct_shared_fixed_ssh_channel as CHANNEL  # noqa: E402


class DirectMinimumProductionClosureTests(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        self.q1 = Q1_TESTS.DirectQstatAcquisitionTests(methodName="runTest")
        self.q1.setUp()

    def tearDown(self) -> None:
        self.q1.tearDown()

    def inspection(self, state: str = "C", *, received_at: str | None = None):
        stdout = (
            f"Job Id: {self.q1.receipt['qsub']['job_id']}\n"
            f"    Job_Name = {self.q1.receipt['project']}\n"
            f"    job_state = {state}\n"
        ).encode("ascii")
        result, _driver, _transport = self.q1.acquire(
            self.q1.observation(stdout=stdout), received_at=received_at,
        )
        return Q1.build_final_scheduler_inspection_once(result)

    def target(self, suffix: str = "target"):
        root = pathlib.Path(self.q1.temporary.name) / suffix
        root.mkdir(mode=0o700)
        owner = MATERIALIZER._issue_offline_target_owner_for_tests(
            target_root=str(root.resolve()),
            review_id="local-fetch-target-review-" + "d" * 64,
        )
        return owner.issue_target_once(
            project=self.q1.receipt["project"],
            attempt_id=self.q1.receipt["attempt_id"],
            job_id=self.q1.receipt["qsub"]["job_id"],
            w5_receipt_sha256=hashlib.sha256(self.q1.receipt_raw).hexdigest(),
            read_profile_sha256=self.q1.read_profile[
                "read_profile_payload_sha256"
            ],
        )

    def test_fresh_terminal_c_f_and_exact_absent_each_issue_once(self) -> None:
        for case in ("C", "F", "absent"):
            with self.subTest(case=case):
                if case != "C":
                    self.tearDown()
                    self.setUp()
                if case == "absent":
                    result, _driver, _transport = self.q1.acquire(
                        self.q1.observation(
                            stdout=b"",
                            stderr=(
                                "qstat: Unknown Job Id "
                                + self.q1.receipt["qsub"]["job_id"] + "\n"
                            ).encode("ascii"),
                            returncode=153,
                            child_exit_code=153,
                        )
                    )
                    inspection = Q1.build_final_scheduler_inspection_once(result)
                else:
                    inspection = self.inspection(case)
                grant = CLOSURE.issue_terminal_fetch_grant_once(inspection)
                grant.assert_current()
                projection = grant.portable_projection()
                self.assertEqual(
                    projection,
                    CLOSURE.validate_terminal_fetch_grant_projection(projection),
                )
                self.assertTrue(projection["classification"]["terminal_fetch_allowed"])
                self.assertFalse(projection["authority"]["authorizes_effect"])
                self.assertFalse(projection["authority"]["authorizes_fetch_transition"])
                self.assertFalse(projection["authority"]["retry"])
                self.assertFalse(projection["authority"]["qsub"])
                self.assertFalse(projection["authority"]["qdel"])
                with self.assertRaises(Q1.DirectQstatAcquisitionError):
                    inspection.assert_current()

    def test_nonterminal_unknown_and_stale_never_issue_fetch(self) -> None:
        cases = ("Q", "R", "H", "E", "unknown", "stale")
        for case in cases:
            with self.subTest(case=case):
                if case != "Q":
                    self.tearDown()
                    self.setUp()
                if case == "unknown":
                    result, _, _ = self.q1.acquire(
                        self.q1.observation(stdout=b"malformed\n")
                    )
                    inspection = Q1.build_final_scheduler_inspection_once(result)
                elif case == "stale":
                    inspection = self.inspection(
                        "C", received_at="2026-08-06T01:10:05.000000Z"
                    )
                else:
                    inspection = self.inspection(case)
                with self.assertRaisesRegex(
                    CLOSURE.DirectMinimumProductionClosureError,
                    "not fresh terminal",
                ):
                    CLOSURE.issue_terminal_fetch_grant_once(inspection)
                with self.assertRaises(Q1.DirectQstatAcquisitionError):
                    inspection.assert_current()

    def test_exact_grant_consumes_to_one_fixed_f1_operation(self) -> None:
        grant = CLOSURE.issue_terminal_fetch_grant_once(self.inspection("C"))
        read_capability = self.q1.controller_profile_capability()
        target = self.target()
        projection, authority, client_join, lease, read_raw = CLOSURE._GRANT_CONSUME_FOR_F1(
            grant, self.q1.receipt_raw, self.q1.fixture.artifacts, read_capability,
            target,
        )
        operation = CHANNEL.issue_fetch_terminal_minimum_bundle_operation(
            self.q1.fixture.artifacts.transport_profile, read_raw, authority,
        )
        try:
            self.assertIs(type(operation), CHANNEL.FetchTerminalMinimumBundleOperation)
            request = CHANNEL.project_fetch_request_frame_for_review(operation)
            self.assertIn(projection["binding"]["job_id"].encode("ascii"), request)
            receipt_raw, artifacts, legacy_request, grant_sha256 = (
                FETCH._decode_dispatched_fetch_request_once(request)
            )
            self.assertEqual(receipt_raw, self.q1.receipt_raw)
            self.assertEqual(artifacts, self.q1.fixture.artifacts)
            self.assertNotIn(b'"evidence"', legacy_request)
            self.assertEqual(
                grant_sha256, projection["grant_payload_sha256"],
            )
            self.assertEqual(read_raw, self.q1.read_profile_raw)
            with self.assertRaises(CLOSURE.DirectMinimumProductionClosureError):
                grant.assert_current()
            self.assertEqual(
                operation.portable_projection()["operation"],
                "fetch_terminal_minimum_bundle",
            )
            join_source = inspect.getsource(
                CLOSURE._build_fetch_client_join_owner
            )
            self.assertIn("record.grant_payload_sha256", join_source)
            self.assertIn(
                'acquisition["controller_grant_payload_sha256"]',
                join_source,
            )
        finally:
            CHANNEL._finish_operation(operation)
            lease.close_once()

    def test_capability_identity_copy_pickle_fork_and_forgery_fail_closed(self) -> None:
        inspection = self.inspection("C")
        forged = object.__new__(Q1.GaussianJobInspection3)
        forged._key = id(forged)
        forged._seal = object()
        with self.assertRaises(Q1.DirectQstatAcquisitionError):
            CLOSURE.issue_terminal_fetch_grant_once(forged)
        grant = CLOSURE.issue_terminal_fetch_grant_once(inspection)
        for operation in (copy.copy, copy.deepcopy, pickle.dumps):
            with self.assertRaises(TypeError):
                operation(grant)
        read_fd, write_fd = os.pipe()
        pid = os.fork()
        if pid == 0:  # pragma: no cover - child assertion
            os.close(read_fd)
            try:
                grant.assert_current()
                os.write(write_fd, b"CURRENT")
            except BaseException:
                os.write(write_fd, b"REVOKED")
            finally:
                os.close(write_fd)
                os._exit(0)
        os.close(write_fd)
        child = os.read(read_fd, 32)
        os.close(read_fd)
        os.waitpid(pid, 0)
        self.assertEqual(child, b"REVOKED")
        grant.assert_current()

    def test_process_isolated_terminal_c_fetch_and_manifest_last_e2e(self) -> None:
        project = self.q1.fixture.root / self.q1.receipt["project"]
        log_raw = b"Normal termination of Gaussian 16\n"
        (project / "approved-input.log").write_bytes(log_raw)
        for basename in MATERIALIZER.ARTIFACT_BASENAMES:
            os.chmod(project / basename, 0o600)
        inspection = self.inspection("C")
        inspection_document, grant = CLOSURE._ROUTE_INSPECTION_ONCE(inspection)
        self.assertIs(type(grant), CLOSURE.TerminalFetchGrant)
        local_root = pathlib.Path(self.q1.temporary.name) / "materialized"
        target = self.target("materialized")
        MATERIALIZER._target_record(target).production_integration = True
        grant_projection, authority, client_join, profile_lease, read_profile_raw = (
            CLOSURE._GRANT_CONSUME_FOR_F1(
                grant,
                self.q1.receipt_raw,
                self.q1.fixture.artifacts,
                self.q1.controller_profile_capability(),
                target,
            )
        )
        operation = CHANNEL.issue_fetch_terminal_minimum_bundle_operation(
            self.q1.fixture.artifacts.transport_profile,
            read_profile_raw,
            authority,
        )
        projection_read, projection_write = os.pipe()
        projection_pid = os.fork()
        if projection_pid == 0:  # pragma: no cover - isolated server owner
            os.close(projection_read)
            try:
                capability = LINEAGE.DirectExistingJobLineageOwner._for_fake_local_testing(
                    durable_state_root=self.q1.fixture.state,
                    _test_token=LINEAGE._TEST_OWNER_TOKEN,
                ).issue_once(self.q1.receipt_raw, self.q1.fixture.artifacts)
                raw = LINEAGE.canonical_bytes(capability.portable_projection())
                os.write(projection_write, len(raw).to_bytes(4, "big") + raw)
            finally:
                os.close(projection_write)
                os._exit(0)
        os.close(projection_write)
        size = int.from_bytes(os.read(projection_read, 4), "big")
        projection_raw = b""
        while len(projection_raw) < size:
            projection_raw += os.read(projection_read, size - len(projection_raw))
        os.close(projection_read)
        self.assertEqual(os.waitpid(projection_pid, 0)[1], 0)
        expected_lineage = LINEAGE.validate_lineage_projection(
            json.loads(projection_raw.decode("utf-8"))
        )
        self.assertEqual(
            expected_lineage["lineage_id"],
            grant_projection["binding"]["lineage_id"],
        )

        request = CHANNEL.project_fetch_request_frame_for_review(operation)
        request_document = json.loads(request[4:].decode("utf-8"))
        server_socket, controller_socket = socket.socketpair()
        writer_pid = os.fork()
        if writer_pid == 0:  # pragma: no cover - isolated fake server transport
            controller_socket.close()
            try:
                lineage = LINEAGE.DirectExistingJobLineageOwner._for_fake_local_testing(
                    durable_state_root=self.q1.fixture.state,
                    _test_token=LINEAGE._TEST_OWNER_TOKEN,
                ).issue_once(self.q1.receipt_raw, self.q1.fixture.artifacts)
                server = FETCH._issue_server_fetch_acquisition_for_tests_once(
                    lineage.consume_once(),
                    read_profile_raw,
                    _test_token=FETCH._TEST_TOKEN,
                )
                projection = server.portable_projection()
                server.abandon_once()
                binding = expected_lineage["binding"]
                timestamp = "2026-08-07T00:00:00.000000Z"
                stdout = (
                    f"Job Id: {binding['job_id']}\n"
                    f"    Job_Name = {binding['project']}\n"
                    "    job_state = C\n"
                ).encode("ascii")
                evidence = Q1.EVIDENCE.build_qstat_evidence(
                    Q1.EVIDENCE.DirectJobBinding(
                        project=binding["project"],
                        job_id=binding["job_id"],
                        attempt_id=binding["attempt_id"],
                        input_sha256=binding["input_sha256"],
                        direct_binding_sha256=expected_lineage[
                            "result_payload_sha256"
                        ],
                    ),
                    Q1.EVIDENCE.QstatObservation(
                        returncode=0,
                        stdout=stdout,
                        stderr=b"",
                        timed_out=False,
                        eof_complete=True,
                        requested_at=timestamp,
                        collected_at=timestamp,
                        received_at=timestamp,
                    ),
                ).document()
                projection["controller_grant_payload_sha256"] = (
                    grant_projection["grant_payload_sha256"]
                )
                projection["server_terminal_eligibility"] = evidence
                projection["authority"]["production_stream_seam"] = True
                projection["authority"]["required_production_predecessor"] = (
                    "terminal_fetch_grant_exact_controller_join"
                )
                projection["acquisition_id"] = (
                    "direct-fetch-acquisition-" + FETCH.digest({
                        "lineage_id": projection["lineage_id"],
                        "read_profile_payload_sha256": projection[
                            "read_profile_payload_sha256"
                        ],
                        "controller_grant_payload_sha256": projection[
                            "controller_grant_payload_sha256"
                        ],
                        "server_qstat_evidence_sha256": evidence[
                            "qstat_evidence_sha256"
                        ],
                        "files": projection["files"],
                    })
                )
                projection["result_payload_sha256"] = ""
                projection["result_payload_sha256"] = FETCH.digest(projection)
                projection = FETCH.validate_acquisition_projection(projection)
                payloads = tuple(
                    (project / basename).read_bytes()
                    for basename in MATERIALIZER.ARTIFACT_BASENAMES
                )
                bundle = FETCH._bundle_bytes(projection, payloads)
                limits = CHANNEL.load_read_profile(
                    read_profile_raw,
                    self.q1.fixture.artifacts.transport_profile,
                )["server_read"]["fetch"]
                max_chunk = int(limits["max_chunk_bytes"], 10)
                chunks = tuple(
                    bundle[offset:offset + max_chunk]
                    for offset in range(0, len(bundle), max_chunk)
                )
                outer_header = {
                    "protocol": CHANNEL.READ_PROTOCOL,
                    "status": "streaming_terminal_minimum_bundle",
                    "operation_id": request_document["operation_id"],
                    "job_id": request_document["job_id"],
                    "chunk_count": str(len(chunks)),
                    "total_size_bytes": str(len(bundle)),
                    "bundle_commitment_sha256": (
                        FETCH._bundle_commitment_sha256(projection)
                    ),
                    "authority": {"authorizes_effect": False, "qsub_calls": "0"},
                }
                trailer = {
                    **outer_header,
                    "status": "completed",
                    "bundle_sha256": hashlib.sha256(bundle).hexdigest(),
                    "trailer_payload_sha256": "",
                }
                trailer["trailer_payload_sha256"] = CHANNEL.digest(trailer)
                wire = bytearray(CHANNEL._canonical_frame(outer_header))
                for chunk in chunks:
                    wire.extend(struct.pack("!I", len(chunk)))
                    wire.extend(chunk)
                wire.extend(CHANNEL._canonical_frame(trailer))
                offset = 0
                while offset < len(wire):
                    offset += os.write(server_socket.fileno(), wire[offset:])
            finally:
                server_socket.close()
                os._exit(0)
        server_socket.close()
        try:
            channel_result = CHANNEL._FETCH_STREAM_BEGIN(
                controller_socket.fileno(),
                operation,
                time.monotonic() + 60.0,
            )
            stream = FETCH.acquire_controller_fetch_stream_once(
                target,
                operation,
                channel_result,
                client_join,
            )
        finally:
            controller_socket.close()
            profile_lease.close_once()
        self.assertEqual(os.waitpid(writer_pid, 0)[1], 0)
        lease = MATERIALIZER.issue_closed_fetch_stream_lease_once(target, stream)
        manifest = MATERIALIZER.materialize_direct_fetch_once(target, lease)
        leaf = local_root / manifest["target"]["leaf_basename"]
        self.assertEqual(
            [item["basename"] for item in manifest["files"]],
            list(MATERIALIZER.ARTIFACT_BASENAMES),
        )
        self.assertEqual((leaf / "approved-input.log").read_bytes(), log_raw)
        self.assertEqual(
            (leaf / MATERIALIZER.MANIFEST_BASENAME).read_bytes(),
            MATERIALIZER.canonical_bytes(manifest),
        )
        self.assertEqual(self.q1.receipt["qsub"]["calls"], "1")
        self.assertFalse(manifest["authority"]["authorizes_effect"])
        self.assertFalse(manifest["authority"]["scientific_acceptance"])
        self.assertFalse(manifest["safety"]["automatic_retry"])
        self.assertEqual(stat.S_IMODE(leaf.stat().st_mode), 0o700)
        resume_result = CLOSURE._resume_result(
            self.q1.receipt_raw,
            self.q1.receipt,
            "materialized",
            inspection_document,
            grant_projection,
            manifest,
        )
        self.assertEqual(
            CLOSURE.validate_minimum_resume_result(resume_result),
            resume_result,
        )
        spliced = copy.deepcopy(resume_result)
        spliced_grant = spliced["terminal_fetch_grant"]
        spliced_grant["binding"]["final_inspection_id"] = (
            "direct-scheduler-inspection-" + "f" * 64
        )
        spliced_grant["grant_id"] = (
            "direct-terminal-fetch-grant-" + CLOSURE.digest({
                "schema": "auto-g16-direct-terminal-fetch-grant-id/1",
                "classification": spliced_grant["classification"],
                "binding": spliced_grant["binding"],
                "qstat": spliced_grant["qstat"],
                "successor": spliced_grant["successor"],
            })
        )
        spliced_grant["grant_payload_sha256"] = ""
        spliced_grant["grant_payload_sha256"] = CLOSURE.digest(spliced_grant)
        spliced["result_payload_sha256"] = ""
        spliced["result_payload_sha256"] = CLOSURE.digest(spliced)
        with self.assertRaisesRegex(
            CLOSURE.DirectMinimumProductionClosureError,
            "spliced",
        ):
            CLOSURE.validate_minimum_resume_result(spliced)

    def test_offline_manifest_cannot_claim_materialized_production_result(self) -> None:
        inspection_document, grant = CLOSURE._ROUTE_INSPECTION_ONCE(
            self.inspection("C")
        )
        self.assertIs(type(grant), CLOSURE.TerminalFetchGrant)
        target = self.target("offline-manifest")
        payloads = (
            b"%chk=approved-input.chk\n# opt freq\n",
            b"#!/bin/sh\n# synthetic only\n",
            b"1" * 64 + b"  approved-input.gjf\n",
            b'{"schema":"synthetic-submission-receipt/1"}\n',
            b" Synthetic Gaussian log bytes only.\n",
        )
        lease = MATERIALIZER.issue_offline_synthetic_stream_lease_once(
            target, payloads,
        )
        manifest = MATERIALIZER.materialize_direct_fetch_once(target, lease)
        self.assertFalse(manifest["integration"]["production_integration"])
        self.assertFalse(manifest["authority"]["remote_fetch_performed"])
        with self.assertRaisesRegex(
            CLOSURE.DirectMinimumProductionClosureError,
            "spliced",
        ):
            CLOSURE._resume_result(
                self.q1.receipt_raw,
                self.q1.receipt,
                "materialized",
                inspection_document,
                grant.portable_projection(),
                manifest,
            )

    def test_public_entry_has_no_override_surface(self) -> None:
        signature = inspect.signature(CLOSURE.issue_terminal_fetch_grant_once)
        self.assertEqual(tuple(signature.parameters), ("inspection",))
        forbidden = {
            "job_id", "root", "host", "profile", "command", "timeout",
            "retry", "cancel", "inspect", "path", "target",
        }
        self.assertTrue(forbidden.isdisjoint(signature.parameters))
        coordinator = inspect.signature(
            CLOSURE.resume_minimum_once
        )
        self.assertEqual(
            tuple(coordinator.parameters),
            ("portable_receipt_bytes", "artifacts"),
        )
        submitter = inspect.signature(CLOSURE.submit_minimum_once)
        self.assertEqual(tuple(submitter.parameters), ("artifacts",))
        self.assertNotIn("run_minimum_production_closure_once", CLOSURE.__all__)
        self.assertNotIn("submit_minimum_production_once", CLOSURE.__all__)
        encoder = inspect.signature(
            CLOSURE.canonical_completed_receipt_bytes
        )
        self.assertEqual(tuple(encoder.parameters), ("receipt",))
        self.assertEqual(
            CLOSURE.canonical_completed_receipt_bytes(self.q1.receipt),
            self.q1.receipt_raw,
        )
        source = inspect.getsource(CLOSURE.resume_minimum_once)
        self.assertIn("target.abandon_once()", source)
        self.assertIn("stream.abandon_once()", source)
        self.assertIn("_FETCH_STREAM_ABANDON", source)
        names = {
            node.id for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Name)
        }
        attributes = {
            node.attr for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Attribute)
        }
        forbidden_production = {
            "_for_tests", "_fake", "_TEST_TOKEN",
            "_issue_fetch_terminal_minimum_bundle_operation_for_testing",
        }
        self.assertTrue(forbidden_production.isdisjoint(names | attributes))
        self.assertNotIn("run_controller_once", attributes)
        self.assertNotIn("issue_submit_operation", attributes)
        production_chain = (
            CLOSURE.resume_minimum_once,
            CHANNEL.run_fetch_channel_once,
            FETCH.acquire_controller_fetch_stream_once,
            MATERIALIZER.issue_closed_fetch_stream_lease_once,
            MATERIALIZER.materialize_direct_fetch_once,
        )
        chain_source = "\n".join(inspect.getsource(item) for item in production_chain)
        for forbidden_text in (
            "_for_tests", "_fake", "_TEST_TOKEN",
            "_issue_fetch_terminal_minimum_bundle_operation_for_testing",
        ):
            self.assertNotIn(forbidden_text, chain_source)

    def test_submit_phase_returns_exact_receipt_bytes_and_resume_transport_unknown_is_closed(self) -> None:
        with mock.patch.object(
            CLOSURE, "_assert_module_binding",
        ), mock.patch.object(
            CLOSURE.W5, "run_controller_once", return_value=self.q1.receipt,
        ) as submit:
            receipt_raw = CLOSURE.submit_minimum_once(self.q1.fixture.artifacts)
        submit.assert_called_once_with(self.q1.fixture.artifacts)
        self.assertEqual(receipt_raw, self.q1.receipt_raw)

        profile_owner = mock.Mock()
        profile_owner.issue_once.return_value = self.q1.controller_profile_capability()
        with mock.patch.object(
            CLOSURE, "_assert_module_binding",
        ), mock.patch.object(
            CLOSURE.READ_PROFILE.DirectReviewedReadProfileOwner,
            "production", return_value=profile_owner,
        ), mock.patch.object(
            CLOSURE.Q1, "acquire_qstat_once",
            side_effect=Q1.DirectQstatTransportUnknown("unknown"),
        ), mock.patch.object(
            CLOSURE.W5, "run_controller_once",
            side_effect=AssertionError("resume entered qsub"),
        ) as second_submit:
            result = CLOSURE.resume_minimum_once(
                receipt_raw, self.q1.fixture.artifacts,
            )
        second_submit.assert_not_called()
        self.assertEqual(result["status"], "query_transport_unknown")
        self.assertIsNone(result["query"]["inspection"])
        self.assertFalse(result["authority"]["fetch_performed"])
        self.assertEqual(
            CLOSURE.validate_minimum_resume_result(result), result,
        )

    def test_nonterminal_resume_returns_query_only_and_never_enters_submit(self) -> None:
        for state in ("Q", "R"):
            with self.subTest(state=state):
                if state != "Q":
                    self.tearDown()
                    self.setUp()
                inspection = self.inspection(state)
                profile_owner = mock.Mock()
                profile_owner.issue_once.return_value = (
                    self.q1.controller_profile_capability()
                )
                with mock.patch.object(
                    CLOSURE, "_assert_module_binding"
                ), mock.patch.object(
                    CLOSURE.Q1, "_assert_module_binding"
                ), mock.patch.object(
                    CLOSURE.READ_PROFILE.DirectReviewedReadProfileOwner,
                    "production",
                    return_value=profile_owner,
                ), mock.patch.object(
                    CLOSURE.Q1, "acquire_qstat_once", return_value=object(),
                ), mock.patch.object(
                    CLOSURE.Q1,
                    "build_final_scheduler_inspection_once",
                    return_value=inspection,
                ), mock.patch.object(
                    CLOSURE.W5,
                    "run_controller_once",
                    side_effect=AssertionError("resume entered qsub"),
                ) as submit:
                    result = CLOSURE.resume_minimum_once(
                        self.q1.receipt_raw, self.q1.fixture.artifacts,
                    )
                submit.assert_not_called()
                self.assertEqual(
                    result["status"], "query_nonterminal",
                )
                self.assertEqual(
                    result["authority"]["this_call_qsub_calls"], "0",
                )
                self.assertFalse(
                    result["authority"]["fetch_performed"]
                )
                self.assertEqual(
                    result["authority"]["explicit_future_query_required"],
                    True,
                )
                switched = copy.deepcopy(result)
                switched["status"] = "query_unknown"
                switched["result_payload_sha256"] = ""
                switched["result_payload_sha256"] = CLOSURE.digest(switched)
                with self.assertRaisesRegex(
                    CLOSURE.DirectMinimumProductionClosureError,
                    "query-unknown",
                ):
                    CLOSURE.validate_minimum_resume_result(switched)
                with self.assertRaises(Q1.DirectQstatAcquisitionError):
                    inspection.assert_current()

    def test_receipt_artifact_and_profile_splice_issue_no_fetch_operation(self) -> None:
        grant = CLOSURE.issue_terminal_fetch_grant_once(self.inspection("C"))
        hostile_artifacts = dataclasses.replace(
            self.q1.fixture.artifacts, authorization=b"{}",
        )
        target = self.target()
        with self.assertRaises(CLOSURE.SESSION.W1.DirectRootOwnerError):
            CLOSURE._GRANT_CONSUME_FOR_F1(
                grant,
                self.q1.receipt_raw,
                hostile_artifacts,
                self.q1.controller_profile_capability(),
                target,
            )
        with self.assertRaises(CLOSURE.DirectMinimumProductionClosureError):
            grant.assert_current()
        with self.assertRaises(MATERIALIZER.DirectLocalFetchMaterializerError):
            target.assert_current()
        retry_target = self.target("retry-target")
        with self.assertRaisesRegex(
            CLOSURE.DirectMinimumProductionClosureError,
            "terminal",
        ):
            CLOSURE._GRANT_CONSUME_FOR_F1(
                grant,
                self.q1.receipt_raw,
                self.q1.fixture.artifacts,
                self.q1.controller_profile_capability(),
                retry_target,
            )
        retry_target.assert_current()
        retry_target.abandon_once()


if __name__ == "__main__":
    unittest.main()
