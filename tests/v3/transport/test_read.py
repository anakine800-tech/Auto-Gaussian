from __future__ import annotations

from dataclasses import replace
import unittest

import auto_g16.transport as transport
from auto_g16.transport._driver import _FetchResult, _TextResult

from ._fixtures import FakeDriver, NOW, TransportFixture, found, success


class SchedulerReadTests(TransportFixture):
    def test_closed_scheduler_state_table_and_exact_invocation(self) -> None:
        snapshot, profile = self.transport_snapshot()
        binding = self.persisted_binding(snapshot, profile)
        for raw, expected in {
            "Q": "queued",
            "W": "queued",
            "R": "running",
            "B": "running",
            "H": "held",
            "S": "held",
            "E": "exiting",
            "T": "exiting",
            "C": "terminal",
            "F": "terminal",
            "X": "terminal",
            "Z": "unknown",
        }.items():
            with self.subTest(raw=raw):
                driver = FakeDriver(
                    text_results=(
                        success(
                            f"Job Id: 123.server\n    job_state = {raw}\n".encode("ascii")
                        ),
                    )
                )
                evidence = self.read_adapter(driver).read_scheduler(
                    snapshot, binding, profile
                )
                self.assertEqual(evidence.state, expected)
                self.assertEqual(evidence.freshness, "fresh")
                call = driver.text_calls[0][1]
                self.assertEqual(call.operation.name, "qstat")
                self.assertEqual(call.argv, ("-f", "123.server"))
                self.assertEqual(call.cwd, binding.remote_workspace)

    def test_exact_absent_and_all_ambiguity_remain_non_authoritative(self) -> None:
        snapshot, profile = self.transport_snapshot()
        binding = self.persisted_binding(snapshot, profile)
        absent = _TextResult(
            stdout=b"",
            stderr=b"qstat: Unknown Job Id 123.server\n",
            returncode=153,
            eof_stdout=True,
            eof_stderr=True,
            completion_status="completed",
        )
        malformed = success(
            b"Job Id: 123.server\n    job_state = R\n    job_state = C\n"
        )
        timeout = _TextResult(
            stdout=b"partial",
            stderr=b"",
            returncode=None,
            eof_stdout=False,
            eof_stderr=False,
            completion_status="timeout",
        )
        for result, state, freshness in (
            (absent, "absent", "fresh"),
            (malformed, "unknown", "unknown"),
            (timeout, "unknown", "unknown"),
        ):
            with self.subTest(result=result):
                evidence = self.read_adapter(
                    FakeDriver(text_results=(result,))
                ).read_scheduler(snapshot, binding, profile)
                self.assertEqual((evidence.state, evidence.freshness), (state, freshness))

    def test_malformed_private_qstat_result_cannot_become_fresh(self) -> None:
        snapshot, profile = self.transport_snapshot()
        binding = self.persisted_binding(snapshot, profile)
        forged = object.__new__(_TextResult)
        for name, value in {
            "stdout": b"Job Id: 123.server\n    job_state = R\n",
            "stderr": b"",
            "returncode": False,
            "eof_stdout": 1,
            "eof_stderr": 1,
            "completion_status": "completed",
        }.items():
            object.__setattr__(forged, name, value)
        evidence = self.read_adapter(
            FakeDriver(text_results=(forged,))
        ).read_scheduler(snapshot, binding, profile)
        self.assertEqual((evidence.state, evidence.freshness), ("unknown", "unknown"))

    def test_binding_or_profile_splice_rejects_before_qstat(self) -> None:
        snapshot, profile = self.transport_snapshot()
        binding = self.persisted_binding(snapshot, profile)
        spliced = object.__new__(transport.ExactRemoteJobBinding)
        for name in (
            "attempt_id",
            "execution_snapshot_id",
            "submission_intent_id",
            "remote_effect_receipt_id",
            "remote_workspace",
            "job_id",
        ):
            object.__setattr__(spliced, name, getattr(binding, name))
        object.__setattr__(spliced, "remote_workspace", "/home/user100/SDL/other/attempt-1")
        driver = FakeDriver(text_results=(success(),))
        with self.assertRaises(transport.TransportBoundaryError):
            self.read_adapter(driver).read_scheduler(snapshot, spliced, profile)
        self.assertEqual(driver.text_calls, [])
        drifted = self.profile(wrapper=b"drifted")
        with self.assertRaises(transport.TransportBoundaryError):
            self.read_adapter(driver).read_scheduler(snapshot, binding, drifted)
        self.assertEqual(driver.text_calls, [])

    def test_unpersisted_forged_binding_rejects_before_qstat(self) -> None:
        snapshot, profile = self.transport_snapshot()
        persisted = self.persisted_binding(snapshot, profile)
        forged = object.__new__(transport.ExactRemoteJobBinding)
        for name in (
            "attempt_id",
            "execution_snapshot_id",
            "submission_intent_id",
            "remote_effect_receipt_id",
            "remote_workspace",
            "job_id",
        ):
            object.__setattr__(forged, name, getattr(persisted, name))
        driver = FakeDriver(text_results=(success(),))
        with self.assertRaises(transport.TransportBoundaryError):
            self.read_adapter(driver).read_scheduler(snapshot, forged, profile)
        self.assertEqual(driver.text_calls, [])


class ExactFetchTests(TransportFixture):
    def requests(self) -> tuple[transport.ExactArtifactRequest, ...]:
        return (
            transport.ExactArtifactRequest(
                artifact_kind="gaussian-log",
                logical_name="input.log",
                remote_relative_name="input.log",
                required=True,
            ),
            transport.ExactArtifactRequest(
                artifact_kind="stdout",
                logical_name="stdout.txt",
                remote_relative_name="stdout.txt",
                required=False,
            ),
        )

    def test_stable_complete_fetch_is_byte_return_only(self) -> None:
        snapshot, profile = self.transport_snapshot()
        binding = self.persisted_binding(snapshot, profile)
        requests = self.requests()
        before_files = set(self.temporary.rglob("*"))
        driver = FakeDriver(
            fetch_results=(found(b"Normal termination\n"), found(b"stdout\n"))
        )
        capture = self.read_adapter(driver).fetch_exact_output(
            snapshot,
            binding,
            profile,
            input_binding_observation_id="input-observation-1",
            requests=requests,
            capture_sequence=1,
        )
        self.assertEqual(capture.capture_status, "captured")
        self.assertEqual(capture.capture_completeness, "complete")
        self.assertEqual(tuple(item.content for item in capture.artifacts), (b"Normal termination\n", b"stdout\n"))
        self.assertEqual(capture.missing_requests, ())
        self.assertEqual(set(self.temporary.rglob("*")), before_files)
        self.assertEqual(
            tuple(item[1].argv for item in driver.fetch_calls),
            (("input.log",), ("stdout.txt",)),
        )

    def test_zero_byte_stable_file_is_still_one_exact_artifact(self) -> None:
        snapshot, profile = self.transport_snapshot()
        binding = self.persisted_binding(snapshot, profile)
        request = (self.requests()[0],)
        capture = self.read_adapter(
            FakeDriver(fetch_results=(found(b""),))
        ).fetch_exact_output(
            snapshot,
            binding,
            profile,
            input_binding_observation_id="input-observation-1",
            requests=request,
            capture_sequence=1,
        )
        self.assertEqual(len(capture.artifacts), 1)
        self.assertEqual(capture.artifacts[0].content, b"")
        self.assertEqual(capture.artifacts[0].size_bytes, 0)

    def test_missing_suffix_is_exact_partial_and_zero_prefix_rejects(self) -> None:
        snapshot, profile = self.transport_snapshot()
        binding = self.persisted_binding(snapshot, profile)
        requests = self.requests()
        partial = self.read_adapter(
            FakeDriver(fetch_results=(found(b"Normal termination\n"), _FetchResult(status="missing")))
        ).fetch_exact_output(
            snapshot,
            binding,
            profile,
            input_binding_observation_id="input-observation-1",
            requests=requests,
            capture_sequence=2,
        )
        self.assertEqual(partial.capture_status, "capture-in-progress")
        self.assertEqual(partial.capture_completeness, "partial")
        self.assertEqual(partial.missing_requests, (requests[1],))
        with self.assertRaises(transport.TransportBoundaryError):
            self.read_adapter(
                FakeDriver(fetch_results=(_FetchResult(status="missing"),))
            ).fetch_exact_output(
                snapshot,
                binding,
                profile,
                input_binding_observation_id="input-observation-1",
                requests=requests,
                capture_sequence=3,
            )

    def test_unstable_replacement_short_read_and_digest_drift_fail_closed(self) -> None:
        snapshot, profile = self.transport_snapshot()
        binding = self.persisted_binding(snapshot, profile)
        request = (self.requests()[0],)
        stable = found(b"Normal termination\n")
        invalid = (
            replace(stable, after_identity="replaced"),
            replace(stable, after_size=1),
            replace(stable, after_sha256="0" * 64),
            _FetchResult(status="unstable"),
        )
        for result in invalid:
            with self.subTest(result=result), self.assertRaises(transport.TransportBoundaryError):
                self.read_adapter(FakeDriver(fetch_results=(result,))).fetch_exact_output(
                    snapshot,
                    binding,
                    profile,
                    input_binding_observation_id="input-observation-1",
                    requests=request,
                    capture_sequence=1,
                )

    def test_malformed_private_fetch_metadata_fails_closed(self) -> None:
        snapshot, profile = self.transport_snapshot()
        binding = self.persisted_binding(snapshot, profile)
        forged = object.__new__(_FetchResult)
        digest = "0" * 64
        for name, value in {
            "status": "found",
            "content": b"x",
            "before_identity": 123,
            "after_identity": 123,
            "before_size": True,
            "after_size": True,
            "before_sha256": digest,
            "after_sha256": digest,
        }.items():
            object.__setattr__(forged, name, value)
        with self.assertRaises(transport.TransportBoundaryError):
            self.read_adapter(FakeDriver(fetch_results=(forged,))).fetch_exact_output(
                snapshot,
                binding,
                profile,
                input_binding_observation_id="input-observation-1",
                requests=(self.requests()[0],),
                capture_sequence=1,
            )

    def test_hidden_latest_wrong_required_log_and_duplicate_requests_reject_before_fetch(self) -> None:
        snapshot, profile = self.transport_snapshot()
        binding = self.persisted_binding(snapshot, profile)
        invalid = (
            (
                transport.ExactArtifactRequest(
                    artifact_kind="gaussian-log",
                    logical_name="latest.log",
                    remote_relative_name="latest.log",
                    required=True,
                ),
            ),
            (self.requests()[0], self.requests()[0]),
            (
                self.requests()[0],
                transport.ExactArtifactRequest(
                    artifact_kind="gaussian-log",
                    logical_name="other.log",
                    remote_relative_name="other.log",
                    required=False,
                ),
            ),
        )
        for requests in invalid:
            driver = FakeDriver(fetch_results=(found(b"x"),))
            with self.subTest(requests=requests), self.assertRaises(transport.TransportBoundaryError):
                self.read_adapter(driver).fetch_exact_output(
                    snapshot,
                    binding,
                    profile,
                    input_binding_observation_id="input-observation-1",
                    requests=requests,
                    capture_sequence=1,
                )
            self.assertEqual(driver.fetch_calls, [])


if __name__ == "__main__":
    unittest.main()
