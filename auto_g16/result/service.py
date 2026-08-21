"""Append-only persistence and deterministic views for v3 result provenance."""

from __future__ import annotations

from typing import Protocol

from auto_g16.core import (
    Attempt,
    CalculationPlan,
    Observation,
    Result,
)

from .models import (
    INPUT_BINDING_OBSERVATION,
    OUTPUT_ENVELOPE_OBSERVATION,
    PARSED_RESULT_TYPE,
    AttemptResultView,
    CaptureCompleteness,
    InputBinding,
    OutputEnvelope,
    ParseOutcome,
    ParseStatus,
    ProvenanceConflictError,
    ResultViewState,
)


class ResultStore(Protocol):
    """The public Core store surface consumed by the result package."""

    def load_attempt(self, attempt_id: str) -> Attempt: ...

    def load_calculation_plan(self, calculation_plan_id: str) -> CalculationPlan: ...

    def append_observation(self, record: Observation) -> None: ...

    def observations_for_attempt(self, attempt_id: str) -> tuple[Observation, ...]: ...

    def append_result(self, record: Result) -> None: ...

    def results_for_attempt(self, attempt_id: str) -> tuple[Result, ...]: ...


class ResultProvenanceService:
    """Materialize only exact, same-Attempt, append-only provenance records."""

    def __init__(self, store: ResultStore) -> None:
        self._store = store

    def record_input_binding(self, binding: InputBinding) -> Observation:
        self._validate_input_relationship(binding)
        existing = self._input_bindings(binding.attempt_id)
        if len(existing) > 1:
            raise ProvenanceConflictError(
                "an Attempt already has multiple input bindings"
            )
        if existing and existing[0].observation_id != binding.observation_id:
            raise ProvenanceConflictError(
                "an Attempt cannot acquire a second distinct input binding"
            )
        record = Observation(
            observation_id=binding.observation_id,
            attempt_id=binding.attempt_id,
            observation_type=INPUT_BINDING_OBSERVATION,
            data=binding.payload(),
        )
        self._store.append_observation(record)
        return record

    def record_output_envelope(self, envelope: OutputEnvelope) -> Observation:
        self._store.load_attempt(envelope.attempt_id)
        bindings = self._input_bindings(envelope.attempt_id)
        if len(bindings) > 1:
            raise ProvenanceConflictError(
                "an Attempt has multiple distinct input bindings"
            )
        binding = next(
            (
                item
                for item in bindings
                if item.observation_id == envelope.input_binding_observation_id
            ),
            None,
        )
        if binding is None:
            raise ProvenanceConflictError(
                "output envelope must bind a stored same-Attempt input observation"
            )
        if binding.execution_snapshot_id != envelope.execution_snapshot_id:
            raise ProvenanceConflictError(
                "output envelope execution snapshot differs from its input binding"
            )
        existing = self._output_envelopes(envelope.attempt_id)
        replay = next(
            (item for item in existing if item.observation_id == envelope.observation_id),
            None,
        )
        if replay is None and existing and envelope.capture_sequence <= max(
            item.capture_sequence for item in existing
        ):
            raise ProvenanceConflictError(
                "a new capture_sequence must follow all stored captures"
            )
        record = Observation(
            observation_id=envelope.observation_id,
            attempt_id=envelope.attempt_id,
            observation_type=OUTPUT_ENVELOPE_OBSERVATION,
            data=envelope.payload(),
        )
        self._store.append_observation(record)
        return record

    def record_parse_outcome(self, outcome: ParseOutcome) -> Result:
        self._store.load_attempt(outcome.attempt_id)
        envelopes = self._output_envelopes(outcome.attempt_id)
        envelope = next(
            (
                item
                for item in envelopes
                if item.observation_id == outcome.envelope_observation_id
            ),
            None,
        )
        if envelope is None:
            raise ProvenanceConflictError(
                "parse outcome must bind a stored same-Attempt output envelope"
            )
        self._validate_attributed_result(outcome, envelope)
        if (
            envelope.capture_completeness is CaptureCompleteness.PARTIAL
            and outcome.parse_status is not ParseStatus.PARTIAL
        ):
            raise ProvenanceConflictError(
                "a partial capture can only produce a partial parse outcome"
            )
        record = Result(
            result_id=outcome.result_id,
            attempt_id=outcome.attempt_id,
            result_type=PARSED_RESULT_TYPE,
            data=outcome.payload(),
        )
        self._store.append_result(record)
        return record

    def current_view(self, attempt_id: str) -> AttemptResultView:
        self._store.load_attempt(attempt_id)
        bindings = self._input_bindings(attempt_id)
        if len(bindings) > 1:
            raise ProvenanceConflictError(
                "an Attempt has multiple distinct input bindings"
            )
        envelopes = self._output_envelopes(attempt_id)
        outcomes = self._parse_outcomes(attempt_id)
        envelope_ids = {item.observation_id for item in envelopes}
        if any(item.envelope_observation_id not in envelope_ids for item in outcomes):
            raise ProvenanceConflictError(
                "a Result binds an unknown or cross-Attempt output envelope"
            )
        by_id = {item.observation_id: item for item in envelopes}
        for outcome in outcomes:
            self._validate_attributed_result(
                outcome, by_id[outcome.envelope_observation_id]
            )
        if any(
            by_id[item.envelope_observation_id].capture_completeness
            is CaptureCompleteness.PARTIAL
            and item.parse_status is not ParseStatus.PARTIAL
            for item in outcomes
        ):
            raise ProvenanceConflictError(
                "a stored Result promotes a partial capture"
            )
        if not bindings:
            if envelopes or outcomes:
                raise ProvenanceConflictError(
                    "capture or Result exists without an input binding"
                )
            return AttemptResultView(
                attempt_id=attempt_id,
                state=ResultViewState.AWAITING_INPUT_BINDING,
                input_binding=None,
                envelopes=(),
                results=(),
                selected_envelope_id=None,
                selected_results=(),
                incomplete=True,
                selection_reason="no input-binding Observation is stored",
            )
        binding = bindings[0]
        if any(
            item.input_binding_observation_id != binding.observation_id
            for item in envelopes
        ):
            raise ProvenanceConflictError(
                "an envelope binds another input Observation"
            )
        if any(
            item.execution_snapshot_id != binding.execution_snapshot_id
            for item in envelopes
        ):
            raise ProvenanceConflictError(
                "an envelope binds another execution snapshot"
            )
        sequences = [item.capture_sequence for item in envelopes]
        if sequences != sorted(sequences) or len(sequences) != len(set(sequences)):
            raise ProvenanceConflictError(
                "capture_sequence must be unique and follow Core insertion order"
            )
        if not envelopes:
            return AttemptResultView(
                attempt_id=attempt_id,
                state=ResultViewState.AWAITING_CAPTURE,
                input_binding=binding,
                envelopes=(),
                results=outcomes,
                selected_envelope_id=None,
                selected_results=(),
                incomplete=True,
                selection_reason="input is bound but no output envelope is stored",
            )
        complete = [
            item
            for item in envelopes
            if item.capture_completeness is CaptureCompleteness.COMPLETE
        ]
        selected = complete[-1] if complete else envelopes[-1]
        selected_results = tuple(
            item
            for item in outcomes
            if item.envelope_observation_id == selected.observation_id
        )
        if selected.capture_completeness is CaptureCompleteness.PARTIAL:
            state = ResultViewState.CAPTURE_INCOMPLETE
            incomplete = True
            reason = "no complete capture exists; selected latest partial by Core order"
        elif not selected_results:
            state = ResultViewState.AWAITING_PARSE
            incomplete = True
            reason = "selected latest complete capture; no parse outcome is stored"
        else:
            latest = selected_results[-1]
            if latest.parse_status is ParseStatus.PARSED:
                state = ResultViewState.PARSED
                incomplete = False
            elif latest.parse_status is ParseStatus.UNPARSEABLE:
                state = ResultViewState.UNPARSEABLE
                incomplete = False
            elif latest.parse_status is ParseStatus.UNSUPPORTED:
                state = ResultViewState.UNSUPPORTED
                incomplete = False
            else:
                state = ResultViewState.AWAITING_PARSE
                incomplete = True
            reason = (
                "selected latest complete capture and latest bound parser outcome "
                "by Core order; all history remains exposed"
            )
        return AttemptResultView(
            attempt_id=attempt_id,
            state=state,
            input_binding=binding,
            envelopes=envelopes,
            results=outcomes,
            selected_envelope_id=selected.observation_id,
            selected_results=selected_results,
            incomplete=incomplete,
            selection_reason=reason,
        )

    def _input_bindings(self, attempt_id: str) -> tuple[InputBinding, ...]:
        found: list[InputBinding] = []
        for record in self._store.observations_for_attempt(attempt_id):
            if record.observation_type != INPUT_BINDING_OBSERVATION:
                continue
            binding = InputBinding.from_payload(record.data)
            if (
                binding.attempt_id != attempt_id
                or binding.observation_id != record.observation_id
            ):
                raise ProvenanceConflictError(
                    "stored input binding identity or Attempt does not match its payload"
                )
            self._validate_input_relationship(binding)
            found.append(binding)
        return tuple(found)

    def _output_envelopes(self, attempt_id: str) -> tuple[OutputEnvelope, ...]:
        found: list[OutputEnvelope] = []
        for record in self._store.observations_for_attempt(attempt_id):
            if record.observation_type != OUTPUT_ENVELOPE_OBSERVATION:
                continue
            envelope = OutputEnvelope.from_payload(record.data)
            if (
                envelope.attempt_id != attempt_id
                or envelope.observation_id != record.observation_id
            ):
                raise ProvenanceConflictError(
                    "stored envelope identity or Attempt does not match its payload"
                )
            found.append(envelope)
        return tuple(found)

    def _validate_input_relationship(self, binding: InputBinding) -> None:
        attempt = self._store.load_attempt(binding.attempt_id)
        plan = self._store.load_calculation_plan(binding.calculation_plan_id)
        if attempt.task_id != plan.task_id:
            raise ProvenanceConflictError(
                "CalculationPlan and Attempt must belong to the same Task"
            )
        if plan.revision != binding.calculation_plan_revision:
            raise ProvenanceConflictError(
                "input binding must name the exact CalculationPlan revision"
            )

    @staticmethod
    def _validate_attributed_result(
        outcome: ParseOutcome, envelope: OutputEnvelope
    ) -> None:
        if outcome.result_kind != "gaussian-job-facts" or not outcome.facts:
            return
        source = outcome.facts["source_artifact"]
        if source["envelope_observation_id"] != envelope.observation_id:
            raise ProvenanceConflictError(
                "attributed Result source binds another output envelope"
            )
        artifact = next(
            (
                item
                for item in envelope.artifacts
                if item.logical_name == source["logical_name"]
            ),
            None,
        )
        if artifact is None or artifact.payload() != {
            key: source[key]
            for key in ("artifact_kind", "logical_name", "sha256", "size_bytes")
        }:
            raise ProvenanceConflictError(
                "attributed Result source does not equal its envelope artifact"
            )

    def _parse_outcomes(self, attempt_id: str) -> tuple[ParseOutcome, ...]:
        found: list[ParseOutcome] = []
        for record in self._store.results_for_attempt(attempt_id):
            if record.result_type != PARSED_RESULT_TYPE:
                continue
            outcome = ParseOutcome.from_payload(record.data)
            if outcome.attempt_id != attempt_id or outcome.result_id != record.result_id:
                raise ProvenanceConflictError(
                    "stored Result identity or Attempt does not match its payload"
                )
            found.append(outcome)
        return tuple(found)
