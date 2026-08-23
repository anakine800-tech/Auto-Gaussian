from __future__ import annotations

import base64
from hashlib import sha256
import unittest

import auto_g16.transport as transport
from auto_g16.transport._driver import _FetchResult, _TextResult

from ._fixtures import FakeDriver, TransportFixture, found, qstat, response


class SchedulerReadTests(TransportFixture):
    def test_closed_scheduler_state_table_and_exact_job_binding(self) -> None:
        snapshot, profile = self.transport_snapshot()
        binding = self.persisted_binding(snapshot, profile)
        for raw, expected in {"Q":"queued", "W":"queued", "R":"running", "B":"running", "H":"held", "S":"held", "E":"exiting", "T":"exiting", "C":"terminal", "F":"terminal", "X":"terminal", "Z":"unknown"}.items():
            with self.subTest(raw=raw):
                driver = FakeDriver(text_results=(qstat(f"Job Id: 123.server\n    job_state = {raw}\n".encode("ascii")),))
                evidence = self.read_adapter(driver).read_scheduler(snapshot, binding, profile)
                self.assertEqual((evidence.state, evidence.freshness), (expected, "fresh"))
                invocation = driver.text_calls[0][1]
                self.assertEqual(invocation.operation.name, "QUERY_SCHEDULER")
                self.assertEqual(invocation.argv, ("-f", "123.server"))
                self.assertEqual(invocation.request["payload"], {"job_id":"123.server"})

    def test_absent_and_ambiguous_scheduler_evidence_remain_explicit(self) -> None:
        snapshot, profile = self.transport_snapshot()
        binding = self.persisted_binding(snapshot, profile)
        cases = (
            (qstat(b"", stderr=b"qstat: Unknown Job Id 123.server\n", returncode=153), ("absent", "fresh")),
            (qstat(b"Job Id: 123.server\n    job_state = R\n    job_state = C\n"), ("unknown", "unknown")),
            (_TextResult(stdout=b"partial", stderr=b"", returncode=None, eof_stdout=False, eof_stderr=False, completion_status="timeout"), ("unknown", "unknown")),
        )
        for result, expected in cases:
            evidence = self.read_adapter(FakeDriver(text_results=(result,))).read_scheduler(snapshot, binding, profile)
            self.assertEqual((evidence.state, evidence.freshness), expected)

    def test_store_profile_or_binding_splice_rejects_before_read(self) -> None:
        snapshot, profile = self.transport_snapshot()
        binding = self.persisted_binding(snapshot, profile)
        object.__setattr__(binding, "remote_workspace", "/home/user100/SDL/other/attempt-1")
        driver = FakeDriver(text_results=(qstat(b""),))
        with self.assertRaises(transport.TransportBoundaryError):
            self.read_adapter(driver).read_scheduler(snapshot, binding, profile)
        self.assertEqual(driver.text_calls, [])


class ExactFetchTests(TransportFixture):
    @staticmethod
    def requests() -> tuple[transport.ExactArtifactRequest, ...]:
        return (
            transport.ExactArtifactRequest(artifact_kind="gaussian-log", logical_name="input.log", remote_relative_name="input.log", required=True),
            transport.ExactArtifactRequest(artifact_kind="stdout", logical_name="stdout.txt", remote_relative_name="stdout.txt", required=False),
        )

    @staticmethod
    def stat_present(name: str, content: bytes):
        return response("STAT_EXACT_FILE", {"presence":"present", "remote_relative_name":name, "size_bytes":len(content), "file_physical_token_base64":base64.b64encode(f"token:{name}".encode()).decode("ascii")})

    def test_stable_complete_fetch_returns_bytes_only(self) -> None:
        snapshot, profile = self.transport_snapshot()
        binding = self.persisted_binding(snapshot, profile)
        log, stdout = b"Normal termination\n", b"stdout\n"
        driver = FakeDriver(text_results=(self.stat_present("input.log", log), self.stat_present("stdout.txt", stdout)), fetch_results=(found(log), found(stdout)))
        before = set(self.temporary.rglob("*"))
        capture = self.read_adapter(driver).fetch_exact_output(snapshot, binding, profile, input_binding_observation_id="input-observation-1", requests=self.requests(), capture_sequence=1)
        self.assertEqual((capture.capture_status, capture.capture_completeness), ("captured", "complete"))
        self.assertEqual(tuple(artifact.content for artifact in capture.artifacts), (log, stdout))
        self.assertEqual(set(self.temporary.rglob("*")), before)
        self.assertEqual(tuple(call[1].operation.name for call in driver.fetch_calls), ("FETCH_EXACT_FILE", "FETCH_EXACT_FILE"))

    def test_missing_suffix_is_exact_partial(self) -> None:
        snapshot, profile = self.transport_snapshot()
        binding = self.persisted_binding(snapshot, profile)
        log = b"Normal termination\n"
        driver = FakeDriver(text_results=(self.stat_present("input.log", log), response("STAT_EXACT_FILE", {"presence":"absent", "remote_relative_name":"stdout.txt"})), fetch_results=(found(log),))
        capture = self.read_adapter(driver).fetch_exact_output(snapshot, binding, profile, input_binding_observation_id="input-observation-1", requests=self.requests(), capture_sequence=2)
        self.assertEqual((capture.capture_status, capture.capture_completeness), ("capture-in-progress", "partial"))
        self.assertEqual(capture.missing_requests, (self.requests()[1],))

    def test_zero_stable_prefix_and_hidden_latest_reject(self) -> None:
        snapshot, profile = self.transport_snapshot()
        binding = self.persisted_binding(snapshot, profile)
        driver = FakeDriver(text_results=(response("STAT_EXACT_FILE", {"presence":"absent", "remote_relative_name":"input.log"}),))
        with self.assertRaises(transport.TransportBoundaryError):
            self.read_adapter(driver).fetch_exact_output(snapshot, binding, profile, input_binding_observation_id="input-observation-1", requests=(self.requests()[0],), capture_sequence=1)
        bad = transport.ExactArtifactRequest(artifact_kind="gaussian-log", logical_name="latest.log", remote_relative_name="latest.log", required=True)
        with self.assertRaises(transport.TransportBoundaryError):
            self.read_adapter(FakeDriver()).fetch_exact_output(snapshot, binding, profile, input_binding_observation_id="input-observation-1", requests=(bad,), capture_sequence=1)

    def test_replacement_or_digest_drift_fails_closed(self) -> None:
        snapshot, profile = self.transport_snapshot()
        binding = self.persisted_binding(snapshot, profile)
        content = b"Normal termination\n"
        unstable = _FetchResult(status="found", content=content, before_identity="one", after_identity="two", before_size=len(content), after_size=len(content), before_sha256=sha256(content).hexdigest(), after_sha256=sha256(content).hexdigest())
        driver = FakeDriver(text_results=(self.stat_present("input.log", content),), fetch_results=(unstable,))
        with self.assertRaises(transport.TransportBoundaryError):
            self.read_adapter(driver).fetch_exact_output(snapshot, binding, profile, input_binding_observation_id="input-observation-1", requests=(self.requests()[0],), capture_sequence=1)


if __name__ == "__main__":
    unittest.main()
