"""Adversarial persistence and reader tests for auto_g16.result."""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from auto_g16.core import (
    Attempt,
    AttemptState,
    CalculationPlan,
    Observation,
    Project,
    RecordConflictError,
    Result,
    SQLiteRuntimeStore,
    Task,
    WorkflowRun,
)
from auto_g16.result import (
    INPUT_BINDING_OBSERVATION,
    OUTPUT_ENVELOPE_OBSERVATION,
    PARSED_RESULT_TYPE,
    CaptureCompleteness,
    GaussianLogParser,
    InputBinding,
    MalformedEnvelopeError,
    OutputArtifact,
    OutputEnvelope,
    ParseOutcome,
    ParseStatus,
    ProvenanceConflictError,
    ResultProvenanceService,
    ResultViewState,
)


SYNTHETIC_LOG = (
    b"SCF Done:  E(RHF) =  -75.000000 A.U.\n"
    b"Optimization completed.\n"
    b"Stationary point found.\n"
    b"Frequencies -- 100.0 200.0 300.0\n"
    b"Thermal correction to Gibbs Free Energy= 0.010000\n"
    b"Normal termination of Gaussian 16\n"
)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def binding(attempt_id: str = "attempt-1", **changes: object) -> InputBinding:
    values: dict[str, object] = {
        "attempt_id": attempt_id,
        "calculation_plan_id": "plan-1" if attempt_id == "attempt-1" else "plan-2",
        "calculation_plan_revision": 1,
        "prepared_input_binding_id": "prepared-1",
        "execution_snapshot_id": "snapshot-1",
        "input_format": "gaussian-input",
        "logical_name": "job.gjf",
        "sha256": "a" * 64,
        "size_bytes": 20,
    }
    values.update(changes)
    return InputBinding(**values)


def output_envelope(
    input_binding: InputBinding,
    *,
    data: bytes = SYNTHETIC_LOG,
    source: str = "capture-1",
    sequence: int = 1,
    completeness: CaptureCompleteness = CaptureCompleteness.COMPLETE,
    manifest_sha: str = "b" * 64,
) -> OutputEnvelope:
    return OutputEnvelope(
        attempt_id=input_binding.attempt_id,
        input_binding_observation_id=input_binding.observation_id,
        execution_snapshot_id=input_binding.execution_snapshot_id,
        capture_source_id=source,
        capture_sequence=sequence,
        capture_status="captured",
        capture_completeness=completeness,
        artifacts=(
            OutputArtifact(
                artifact_kind="gaussian-log",
                logical_name="job.log",
                sha256=sha(data),
                size_bytes=len(data),
            ),
        ),
        capture_manifest_sha256=manifest_sha,
        captured_at_utc=f"2026-08-17T00:00:{sequence:02d}Z",
    )


def outcome(
    envelope: OutputEnvelope,
    *,
    version: str = "1",
    status: ParseStatus = ParseStatus.PARSED,
    facts: dict[str, object] | None = None,
) -> ParseOutcome:
    return ParseOutcome(
        attempt_id=envelope.attempt_id,
        envelope_observation_id=envelope.observation_id,
        parser_name="fixture-parser",
        parser_version=version,
        result_kind="gaussian-facts",
        parse_status=status,
        facts={} if facts is None else facts,
    )


def initialized_store(database: str | Path = ":memory:") -> SQLiteRuntimeStore:
    store = SQLiteRuntimeStore(database)
    store.store_project(Project(project_id="project-1"))
    store.store_workflow_run(
        WorkflowRun(
            workflow_run_id="run-1",
            project_id="project-1",
            workflow_name="offline-result-test",
        )
    )
    for number in (1, 2):
        store.store_task(
            Task(
                task_id=f"task-{number}",
                workflow_run_id="run-1",
                task_kind="gaussian",
            )
        )
        store.store_calculation_plan(
            CalculationPlan(
                calculation_plan_id=f"plan-{number}",
                task_id=f"task-{number}",
                revision=1,
                intent={"fixture": number},
            )
        )
        store.create_attempt(
            Attempt(
                attempt_id=f"attempt-{number}",
                task_id=f"task-{number}",
                ordinal=1,
            )
        )
    return store


class ResultServiceTests(unittest.TestCase):
    def test_exact_chain_replay_is_idempotent_and_parser_versions_append(self) -> None:
        with initialized_store() as store:
            service = ResultProvenanceService(store)
            item = binding()
            envelope = output_envelope(item)
            first = outcome(envelope, version="1", facts={"energy": -75.0})
            second = outcome(envelope, version="2", facts={"energy": -75.0})
            for _ in range(2):
                service.record_input_binding(item)
                service.record_output_envelope(envelope)
                service.record_parse_outcome(first)
            service.record_parse_outcome(second)
            view = service.current_view("attempt-1")
            self.assertEqual(view.state, ResultViewState.PARSED)
            self.assertEqual(
                tuple(item.parser_version for item in view.selected_results), ("1", "2")
            )
            self.assertEqual(len(view.envelopes), 1)

    def test_same_identity_changed_content_conflicts_in_core(self) -> None:
        with initialized_store() as store:
            service = ResultProvenanceService(store)
            original = binding()
            service.record_input_binding(original)
            with self.assertRaises(RecordConflictError):
                service.record_input_binding(
                    binding(logical_name="changed.gjf", sha256="c" * 64)
                )
            envelope = output_envelope(original)
            service.record_output_envelope(envelope)
            with self.assertRaises(RecordConflictError):
                service.record_output_envelope(
                    output_envelope(original, data=b"different captured bytes")
                )
            service.record_parse_outcome(outcome(envelope, facts={"energy": -1.0}))
            with self.assertRaises(RecordConflictError):
                service.record_parse_outcome(outcome(envelope, facts={"energy": -2.0}))

    def test_plan_revision_and_task_relationships_fail_closed(self) -> None:
        with initialized_store() as store:
            service = ResultProvenanceService(store)
            with self.assertRaisesRegex(ProvenanceConflictError, "exact.*revision"):
                service.record_input_binding(binding(calculation_plan_revision=2))
            with self.assertRaisesRegex(ProvenanceConflictError, "same Task"):
                service.record_input_binding(binding(calculation_plan_id="plan-2"))

    def test_attempt_cannot_acquire_a_second_input_binding(self) -> None:
        with initialized_store() as store:
            service = ResultProvenanceService(store)
            service.record_input_binding(binding())
            with self.assertRaisesRegex(ProvenanceConflictError, "second distinct"):
                service.record_input_binding(
                    binding(prepared_input_binding_id="prepared-2")
                )
            self.assertEqual(len(store.observations_for_attempt("attempt-1")), 1)

    def test_envelope_requires_same_attempt_binding_and_snapshot(self) -> None:
        with initialized_store() as store:
            service = ResultProvenanceService(store)
            item = binding()
            wrong_attempt = binding("attempt-2")
            service.record_input_binding(item)
            service.record_input_binding(wrong_attempt)
            other = output_envelope(wrong_attempt, source="other")
            cross_binding = OutputEnvelope(
                attempt_id="attempt-1",
                input_binding_observation_id=wrong_attempt.observation_id,
                execution_snapshot_id=wrong_attempt.execution_snapshot_id,
                capture_source_id=other.capture_source_id,
                capture_sequence=other.capture_sequence,
                capture_status=other.capture_status,
                capture_completeness=other.capture_completeness,
                artifacts=other.artifacts,
                capture_manifest_sha256=other.capture_manifest_sha256,
                captured_at_utc=other.captured_at_utc,
            )
            with self.assertRaisesRegex(ProvenanceConflictError, "stored same-Attempt"):
                service.record_output_envelope(cross_binding)

            bad_snapshot = OutputEnvelope(
                attempt_id=item.attempt_id,
                input_binding_observation_id=item.observation_id,
                execution_snapshot_id="snapshot-other",
                capture_source_id="capture-bad",
                capture_sequence=1,
                capture_status="captured",
                capture_completeness=CaptureCompleteness.COMPLETE,
                artifacts=output_envelope(item).artifacts,
                capture_manifest_sha256="d" * 64,
                captured_at_utc="2026-08-17T00:00:00Z",
            )
            with self.assertRaisesRegex(ProvenanceConflictError, "snapshot"):
                service.record_output_envelope(bad_snapshot)

    def test_parse_outcome_cannot_cross_attempt_or_promote_partial_capture(self) -> None:
        with initialized_store() as store:
            service = ResultProvenanceService(store)
            first = binding()
            second = binding("attempt-2")
            service.record_input_binding(first)
            service.record_input_binding(second)
            partial = output_envelope(
                first,
                completeness=CaptureCompleteness.PARTIAL,
                manifest_sha="c" * 64,
            )
            service.record_output_envelope(partial)
            with self.assertRaisesRegex(ProvenanceConflictError, "partial capture"):
                service.record_parse_outcome(outcome(partial, status=ParseStatus.PARSED))
            cross = ParseOutcome(
                attempt_id="attempt-2",
                envelope_observation_id=partial.observation_id,
                parser_name="fixture-parser",
                parser_version="1",
                result_kind="gaussian-facts",
                parse_status=ParseStatus.PARTIAL,
            )
            with self.assertRaisesRegex(ProvenanceConflictError, "same-Attempt"):
                service.record_parse_outcome(cross)

    def test_current_view_prefers_latest_complete_not_newer_partial(self) -> None:
        with initialized_store() as store:
            service = ResultProvenanceService(store)
            item = binding()
            service.record_input_binding(item)
            complete_1 = output_envelope(item, source="complete-1", sequence=1)
            complete_2 = output_envelope(
                item, source="complete-2", sequence=2, manifest_sha="c" * 64
            )
            partial_3 = output_envelope(
                item,
                source="partial-3",
                sequence=3,
                completeness=CaptureCompleteness.PARTIAL,
                manifest_sha="d" * 64,
            )
            for envelope in (complete_1, complete_2, partial_3):
                service.record_output_envelope(envelope)
            service.record_parse_outcome(outcome(complete_1, facts={"capture": 1}))
            service.record_parse_outcome(
                outcome(complete_2, version="2", facts={"capture": 2})
            )
            service.record_parse_outcome(
                outcome(partial_3, status=ParseStatus.PARTIAL)
            )
            view = service.current_view("attempt-1")
            self.assertEqual(view.selected_envelope_id, complete_2.observation_id)
            self.assertEqual(view.state, ResultViewState.PARSED)
            self.assertEqual(len(view.envelopes), 3)
            self.assertEqual(len(view.results), 3)

    def test_new_capture_sequence_cannot_move_backwards_or_duplicate(self) -> None:
        with initialized_store() as store:
            service = ResultProvenanceService(store)
            item = binding()
            service.record_input_binding(item)
            service.record_output_envelope(
                output_envelope(item, source="capture-2", sequence=2)
            )
            with self.assertRaisesRegex(ProvenanceConflictError, "capture_sequence"):
                service.record_output_envelope(
                    output_envelope(
                        item,
                        source="capture-1",
                        sequence=1,
                        manifest_sha="c" * 64,
                    )
                )

    def test_durable_incomplete_prefixes_survive_close_and_reopen(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "runtime.sqlite3"
            store = initialized_store(database)
            service = ResultProvenanceService(store)
            self.assertEqual(
                service.current_view("attempt-1").state,
                ResultViewState.AWAITING_INPUT_BINDING,
            )
            item = binding()
            service.record_input_binding(item)
            self.assertEqual(
                service.current_view("attempt-1").state,
                ResultViewState.AWAITING_CAPTURE,
            )
            partial = output_envelope(
                item, completeness=CaptureCompleteness.PARTIAL
            )
            service.record_output_envelope(partial)
            service.record_parse_outcome(outcome(partial, status=ParseStatus.PARTIAL))
            self.assertEqual(
                service.current_view("attempt-1").state,
                ResultViewState.CAPTURE_INCOMPLETE,
            )
            store.close()
            with SQLiteRuntimeStore(database) as reopened:
                view = ResultProvenanceService(reopened).current_view("attempt-1")
                self.assertEqual(view.state, ResultViewState.CAPTURE_INCOMPLETE)
                self.assertTrue(view.incomplete)

    def test_result_operations_never_mutate_attempt_state(self) -> None:
        with initialized_store() as store:
            before = store.attempt_state("attempt-1")
            service = ResultProvenanceService(store)
            item = binding()
            envelope = output_envelope(item)
            service.record_input_binding(item)
            service.record_output_envelope(envelope)
            service.record_parse_outcome(outcome(envelope))
            service.current_view("attempt-1")
            self.assertEqual(before, AttemptState.PLANNED)
            self.assertEqual(store.attempt_state("attempt-1"), before)

    def test_reader_rejects_forged_known_records(self) -> None:
        with initialized_store() as store:
            item = binding()
            store.append_observation(
                Observation(
                    observation_id="forged",
                    attempt_id="attempt-1",
                    observation_type=INPUT_BINDING_OBSERVATION,
                    data=item.payload(),
                )
            )
            with self.assertRaisesRegex(ProvenanceConflictError, "identity"):
                ResultProvenanceService(store).current_view("attempt-1")

    def test_gaussian_parser_distinguishes_parsed_partial_unparseable_unsupported(self) -> None:
        parser = GaussianLogParser()
        item = binding()
        complete = output_envelope(item)
        parsed = parser.parse(complete, {"job.log": SYNTHETIC_LOG})
        self.assertEqual(parsed.parse_status, ParseStatus.PARSED)
        self.assertEqual(parsed.facts["program_status"], "normal-termination")
        self.assertNotIn("scientific_acceptance", parsed.facts)

        partial = output_envelope(
            item,
            data=b"SCF Done: E(RHF) = -1.0 A.U.\n",
            completeness=CaptureCompleteness.PARTIAL,
            manifest_sha="c" * 64,
        )
        self.assertEqual(
            parser.parse(partial, {"job.log": b"SCF Done: E(RHF) = -1.0 A.U.\n"}).parse_status,
            ParseStatus.PARTIAL,
        )
        unknown_bytes = b"not gaussian output\n"
        unparseable = output_envelope(
            item, data=unknown_bytes, source="unknown", manifest_sha="d" * 64
        )
        self.assertEqual(
            parser.parse(unparseable, {"job.log": unknown_bytes}).parse_status,
            ParseStatus.UNPARSEABLE,
        )
        damaged_bytes = (
            b"Frequencies -- 100.0 BROKEN 300.0\n"
            b"Normal termination of Gaussian 16\n"
        )
        damaged = output_envelope(
            item, data=damaged_bytes, source="damaged", manifest_sha="9" * 64
        )
        damaged_result = parser.parse(damaged, {"job.log": damaged_bytes})
        self.assertEqual(damaged_result.parse_status, ParseStatus.PARTIAL)
        self.assertFalse(damaged_result.facts["frequency_parse_complete"])
        stdout = OutputEnvelope(
            attempt_id=item.attempt_id,
            input_binding_observation_id=item.observation_id,
            execution_snapshot_id=item.execution_snapshot_id,
            capture_source_id="stdout-only",
            capture_sequence=4,
            capture_status="captured",
            capture_completeness=CaptureCompleteness.COMPLETE,
            artifacts=(
                OutputArtifact(
                    artifact_kind="stdout",
                    logical_name="stdout.txt",
                    sha256=sha(b"ok\n"),
                    size_bytes=3,
                ),
            ),
            capture_manifest_sha256="e" * 64,
            captured_at_utc="2026-08-17T00:00:04Z",
        )
        self.assertEqual(
            parser.parse(stdout, {"stdout.txt": b"ok\n"}).parse_status,
            ParseStatus.UNSUPPORTED,
        )

    def test_gaussian_parser_rejects_artifact_identity_mismatch(self) -> None:
        parser = GaussianLogParser()
        envelope = output_envelope(binding())
        for artifacts in ({}, {"job.log": b"changed"}, {"extra": b""}):
            with self.subTest(artifacts=artifacts), self.assertRaises(
                MalformedEnvelopeError
            ):
                parser.parse(envelope, artifacts)

    def test_valid_unparseable_envelope_and_outcome_remain_durable(self) -> None:
        with initialized_store() as store:
            service = ResultProvenanceService(store)
            item = binding()
            data = b"synthetic unsupported program bytes\n"
            envelope = output_envelope(
                item, data=data, source="unparseable", manifest_sha="f" * 64
            )
            service.record_input_binding(item)
            service.record_output_envelope(envelope)
            parsed = GaussianLogParser().parse(envelope, {"job.log": data})
            self.assertEqual(parsed.parse_status, ParseStatus.UNPARSEABLE)
            service.record_parse_outcome(parsed)
            view = service.current_view("attempt-1")
            self.assertEqual(view.state, ResultViewState.UNPARSEABLE)
            self.assertEqual(view.selected_envelope_id, envelope.observation_id)
            self.assertEqual(view.selected_results, (parsed,))

    def test_known_result_with_wrong_identity_is_rejected(self) -> None:
        with initialized_store() as store:
            item = binding()
            envelope = output_envelope(item)
            service = ResultProvenanceService(store)
            service.record_input_binding(item)
            service.record_output_envelope(envelope)
            parsed = outcome(envelope)
            store.append_result(
                Result(
                    result_id="forged",
                    attempt_id="attempt-1",
                    result_type=PARSED_RESULT_TYPE,
                    data=parsed.payload(),
                )
            )
            with self.assertRaisesRegex(ProvenanceConflictError, "identity"):
                service.current_view("attempt-1")


if __name__ == "__main__":
    unittest.main()
