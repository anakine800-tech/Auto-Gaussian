"""Value-record and deterministic-identity tests for auto_g16.result."""

from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError
from uuid import UUID

from auto_g16.result import (
    NS_INPUT_BINDING,
    NS_OUTPUT_ENVELOPE,
    NS_PARSED_RESULT,
    CaptureCompleteness,
    CaptureStatus,
    InputBinding,
    MalformedEnvelopeError,
    OutputArtifact,
    OutputEnvelope,
    ParseOutcome,
    ParseStatus,
    ResultBoundaryError,
)


SHA_A = "a" * 64
SHA_B = "b" * 64


def input_binding(**changes: object) -> InputBinding:
    values: dict[str, object] = {
        "attempt_id": "attempt-1",
        "calculation_plan_id": "plan-1",
        "calculation_plan_revision": 1,
        "prepared_input_binding_id": "prepared-input-1",
        "execution_snapshot_id": "snapshot-1",
        "input_format": "gaussian-input",
        "logical_name": "job.gjf",
        "sha256": SHA_A,
        "size_bytes": 12,
    }
    values.update(changes)
    return InputBinding(**values)


def artifact(**changes: object) -> OutputArtifact:
    values: dict[str, object] = {
        "artifact_kind": "gaussian-log",
        "logical_name": "job.log",
        "sha256": SHA_B,
        "size_bytes": 20,
    }
    values.update(changes)
    return OutputArtifact(**values)


def envelope(**changes: object) -> OutputEnvelope:
    values: dict[str, object] = {
        "attempt_id": "attempt-1",
        "input_binding_observation_id": input_binding().observation_id,
        "execution_snapshot_id": "snapshot-1",
        "capture_source_id": "capture-source-1",
        "capture_sequence": 1,
        "capture_status": "captured",
        "capture_completeness": CaptureCompleteness.COMPLETE,
        "artifacts": (artifact(),),
        "capture_manifest_sha256": SHA_A,
        "captured_at_utc": "2026-08-17T00:00:00Z",
    }
    values.update(changes)
    return OutputEnvelope(**values)


class ResultModelTests(unittest.TestCase):
    def test_namespaces_are_source_controlled_and_records_are_immutable(self) -> None:
        self.assertEqual(
            (NS_INPUT_BINDING, NS_OUTPUT_ENVELOPE, NS_PARSED_RESULT),
            tuple(
                UUID(value)
                for value in (
                    "2caa8c92-f020-5326-b999-f591dcde6559",
                    "84c71351-81f8-5143-84b4-12dc8e016c16",
                    "698489ce-1b85-5ab5-8991-d8a953b4b222",
                )
            ),
        )
        with self.assertRaises(FrozenInstanceError):
            input_binding().attempt_id = "changed"  # type: ignore[misc]

    def test_input_binding_identity_uses_only_the_frozen_tuple(self) -> None:
        original = input_binding()
        replay = input_binding(
            input_format="gaussian-com",
            logical_name="other.gjf",
            sha256=SHA_B,
            size_bytes=99,
        )
        self.assertEqual(original.observation_id, replay.observation_id)
        for field, value in (
            ("calculation_plan_revision", 2),
            ("prepared_input_binding_id", "prepared-input-2"),
            ("execution_snapshot_id", "snapshot-2"),
        ):
            with self.subTest(field=field):
                self.assertNotEqual(
                    original.observation_id,
                    input_binding(**{field: value}).observation_id,
                )

    def test_envelope_identity_ignores_time_but_tracks_capture_and_completeness(self) -> None:
        original = envelope()
        self.assertEqual(
            original.observation_id,
            envelope(
                capture_sequence=99,
                capture_status="capture-interrupted",
                captured_at_utc="2026-08-17T01:00:00Z",
            ).observation_id,
        )
        self.assertNotEqual(
            original.observation_id,
            envelope(capture_source_id="capture-source-2").observation_id,
        )
        self.assertNotEqual(
            original.observation_id,
            envelope(capture_completeness=CaptureCompleteness.PARTIAL).observation_id,
        )

    def test_result_identity_tracks_parser_version_without_timestamps(self) -> None:
        first = ParseOutcome(
            attempt_id="attempt-1",
            envelope_observation_id=envelope().observation_id,
            parser_name="parser",
            parser_version="1",
            result_kind="facts",
            parse_status=ParseStatus.PARSED,
            facts={"energy": -1.0},
        )
        replay = ParseOutcome(
            attempt_id="attempt-1",
            envelope_observation_id=envelope().observation_id,
            parser_name="parser",
            parser_version="1",
            result_kind="facts",
            parse_status=ParseStatus.UNPARSEABLE,
        )
        changed = ParseOutcome(
            attempt_id="attempt-1",
            envelope_observation_id=envelope().observation_id,
            parser_name="parser",
            parser_version="2",
            result_kind="facts",
            parse_status=ParseStatus.PARSED,
        )
        self.assertEqual(first.result_id, replay.result_id)
        self.assertNotEqual(first.result_id, changed.result_id)

    def test_artifact_metadata_is_allowlisted_and_portable(self) -> None:
        for changes in (
            {"artifact_kind": "checkpoint"},
            {"logical_name": "/tmp/job.log"},
            {"logical_name": "../job.log"},
            {"sha256": "ABC"},
            {"size_bytes": -1},
        ):
            with self.subTest(changes=changes), self.assertRaises(
                (MalformedEnvelopeError, ResultBoundaryError)
            ):
                artifact(**changes)

    def test_malformed_envelope_metadata_fails_before_persistence(self) -> None:
        with self.assertRaises(MalformedEnvelopeError):
            envelope(artifacts=())
        with self.assertRaises(MalformedEnvelopeError):
            envelope(artifacts=(artifact(), artifact()))
        with self.assertRaises(ResultBoundaryError):
            envelope(captured_at_utc="2026-08-17T00:00:00+08:00")
        with self.assertRaises(MalformedEnvelopeError):
            envelope(capture_status="execution-succeeded")
        self.assertIs(envelope().capture_status, CaptureStatus.CAPTURED)

    def test_facts_cannot_claim_scientific_acceptance(self) -> None:
        for key in (
            "accepted",
            "minimum_validated",
            "scientific_acceptance",
            "workflow_success",
        ):
            with self.subTest(key=key), self.assertRaises(ResultBoundaryError):
                ParseOutcome(
                    attempt_id="attempt-1",
                    envelope_observation_id=envelope().observation_id,
                    parser_name="parser",
                    parser_version="1",
                    result_kind="facts",
                    parse_status=ParseStatus.PARSED,
                    facts={key: True},
                )
        with self.assertRaises(ResultBoundaryError):
            ParseOutcome(
                attempt_id="attempt-1",
                envelope_observation_id=envelope().observation_id,
                parser_name="parser",
                parser_version="1",
                result_kind="facts",
                parse_status=ParseStatus.PARSED,
                facts={"nested": {"scientific_acceptance": True}},
            )

    def test_payloads_fail_closed_on_unknown_fields_and_nonfinite_facts(self) -> None:
        payload = dict(input_binding().payload())
        payload["unreviewed"] = True
        with self.assertRaises(ResultBoundaryError):
            InputBinding.from_payload(payload)
        with self.assertRaises(ResultBoundaryError):
            ParseOutcome(
                attempt_id="attempt-1",
                envelope_observation_id=envelope().observation_id,
                parser_name="parser",
                parser_version="1",
                result_kind="facts",
                parse_status=ParseStatus.PARSED,
                facts={"energy": float("nan")},
            )


if __name__ == "__main__":
    unittest.main()
