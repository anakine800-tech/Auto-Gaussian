"""Pure ReviewBundle construction and deterministic rendering."""

from __future__ import annotations

from collections.abc import Mapping
import json

from auto_g16.core import SQLiteRuntimeStore
from auto_g16.result import (
    INPUT_BINDING_OBSERVATION,
    OUTPUT_ENVELOPE_OBSERVATION,
    PARSED_RESULT_TYPE,
    InputBinding,
    OutputEnvelope,
    ParseOutcome,
)
from auto_g16.scientific_validation import (
    MinimumValidationClassification,
    MinimumValidationOutcome,
    SQLiteScientificValidationStore,
    ScientificAcceptance,
)

from ._canonical import plain_value
from .models import ReviewAcceptanceState, ReviewBundle, ReviewBundleError


def _input_binding_projection(value: InputBinding) -> Mapping[str, object]:
    replay = InputBinding.from_payload(value.payload())
    if replay.observation_id != value.observation_id or replay != value:
        raise ReviewBundleError("InputBinding derived identity does not replay")
    return {
        "schema_version": value.schema_version,
        "observation_id": value.observation_id,
        "attempt_id": value.attempt_id,
        "calculation_plan_id": value.calculation_plan_id,
        "calculation_plan_revision": value.calculation_plan_revision,
        "prepared_input_binding_id": value.prepared_input_binding_id,
        "execution_snapshot_id": value.execution_snapshot_id,
        "input_format": value.input_format,
        "logical_name": value.logical_name,
        "sha256": value.sha256,
        "size_bytes": value.size_bytes,
    }


def _output_envelope_projection(value: OutputEnvelope) -> Mapping[str, object]:
    replay = OutputEnvelope.from_payload(value.payload())
    if replay.observation_id != value.observation_id or replay != value:
        raise ReviewBundleError("OutputEnvelope derived identity does not replay")
    return {
        "schema_version": value.schema_version,
        "observation_id": value.observation_id,
        "attempt_id": value.attempt_id,
        "input_binding_observation_id": value.input_binding_observation_id,
        "execution_snapshot_id": value.execution_snapshot_id,
        "capture_source_id": value.capture_source_id,
        "capture_sequence": value.capture_sequence,
        "capture_status": value.capture_status.value,
        "capture_completeness": value.capture_completeness.value,
        "artifacts": tuple(item.payload() for item in value.artifacts),
        "capture_manifest_sha256": value.capture_manifest_sha256,
        "captured_at_utc": value.captured_at_utc,
    }


def _parse_outcome_projection(value: ParseOutcome) -> Mapping[str, object]:
    replay = ParseOutcome.from_payload(value.payload())
    if replay.result_id != value.result_id or replay != value:
        raise ReviewBundleError("ParseOutcome derived identity does not replay")
    return {
        "schema_version": value.schema_version,
        "result_id": value.result_id,
        "attempt_id": value.attempt_id,
        "envelope_observation_id": value.envelope_observation_id,
        "parser_name": value.parser_name,
        "parser_version": value.parser_version,
        "result_kind": value.result_kind,
        "parse_status": value.parse_status.value,
        "facts": value.facts,
        "diagnostics": value.diagnostics,
    }


def _minimum_validation_projection(value: MinimumValidationOutcome) -> Mapping[str, object]:
    return {
        "schema_version": value.schema_version,
        "minimum_validation_outcome_id": value.minimum_validation_outcome_id,
        "validation_policy_id": value.validation_policy_id,
        "validation_policy_version": value.validation_policy_version,
        "calculation_plan_id": value.calculation_plan_id,
        "calculation_plan_revision": value.calculation_plan_revision,
        "attempt_id": value.attempt_id,
        "input_binding_observation_id": value.input_binding_observation_id,
        "envelope_observation_id": value.envelope_observation_id,
        "parse_result_id": value.parse_result_id,
        "parser_name": value.parser_name,
        "parser_version": value.parser_version,
        "result_kind": value.result_kind,
        "source_artifact": value.source_artifact,
        "job_section": value.job_section,
        "accepted_optimization_span": value.accepted_optimization_span,
        "accepted_stationary_span": value.accepted_stationary_span,
        "selected_geometry_block": value.selected_geometry_block,
        "selected_frequency_blocks": value.selected_frequency_blocks,
        "selected_frequencies_cm1": value.selected_frequencies_cm1,
        "classification": value.classification.value,
        "reason_code": value.reason_code,
    }


def _scientific_acceptance_projection(value: ScientificAcceptance) -> Mapping[str, object]:
    return {
        "schema_version": value.schema_version,
        "scientific_acceptance_id": value.scientific_acceptance_id,
        "minimum_validation_outcome_id": value.minimum_validation_outcome_id,
        "validation_policy_id": value.validation_policy_id,
        "validation_policy_version": value.validation_policy_version,
        "calculation_plan_id": value.calculation_plan_id,
        "calculation_plan_revision": value.calculation_plan_revision,
        "attempt_id": value.attempt_id,
        "parse_result_id": value.parse_result_id,
        "classification": value.classification.value,
        "reviewer_id": value.reviewer_id,
        "review_evidence": value.review_evidence,
    }


def _persisted_result_chain(
    core_store: SQLiteRuntimeStore,
    input_binding: InputBinding,
    output_envelope: OutputEnvelope,
    parse_outcome: ParseOutcome,
) -> None:
    observations = core_store.observations_for_attempt(input_binding.attempt_id)
    matching_binding = tuple(
        record
        for record in observations
        if record.observation_type == INPUT_BINDING_OBSERVATION
        and record.observation_id == input_binding.observation_id
    )
    matching_envelope = tuple(
        record
        for record in observations
        if record.observation_type == OUTPUT_ENVELOPE_OBSERVATION
        and record.observation_id == output_envelope.observation_id
    )
    if len(matching_binding) != 1 or len(matching_envelope) != 1:
        raise ReviewBundleError("exact persisted Result observations were not found")
    stored_binding = InputBinding.from_payload(matching_binding[0].data)
    stored_envelope = OutputEnvelope.from_payload(matching_envelope[0].data)
    if (
        matching_binding[0].attempt_id != stored_binding.attempt_id
        or matching_envelope[0].attempt_id != stored_envelope.attempt_id
        or stored_binding != input_binding
        or stored_envelope != output_envelope
        or stored_binding.observation_id != matching_binding[0].observation_id
        or stored_envelope.observation_id != matching_envelope[0].observation_id
    ):
        raise ReviewBundleError("persisted Result observation authority is spliced")

    matching_results = tuple(
        record
        for record in core_store.results_for_attempt(input_binding.attempt_id)
        if record.result_type == PARSED_RESULT_TYPE
        and record.result_id == parse_outcome.result_id
    )
    if len(matching_results) != 1:
        raise ReviewBundleError("exact persisted ParseOutcome was not found")
    stored_parse = ParseOutcome.from_payload(matching_results[0].data)
    if (
        matching_results[0].attempt_id != stored_parse.attempt_id
        or stored_parse != parse_outcome
        or stored_parse.result_id != matching_results[0].result_id
    ):
        raise ReviewBundleError("persisted ParseOutcome authority is spliced")


def _acceptance_closes(
    acceptance: ScientificAcceptance, outcome: MinimumValidationOutcome
) -> bool:
    return (
        acceptance.minimum_validation_outcome_id == outcome.minimum_validation_outcome_id
        and acceptance.validation_policy_id == outcome.validation_policy_id
        and acceptance.validation_policy_version == outcome.validation_policy_version
        and acceptance.calculation_plan_id == outcome.calculation_plan_id
        and acceptance.calculation_plan_revision == outcome.calculation_plan_revision
        and acceptance.attempt_id == outcome.attempt_id
        and acceptance.parse_result_id == outcome.parse_result_id
        and acceptance.classification == outcome.classification
    )


def build_review_bundle(
    core_store: SQLiteRuntimeStore,
    validation_store: SQLiteScientificValidationStore,
    *,
    input_binding: InputBinding,
    output_envelope: OutputEnvelope,
    parse_outcome: ParseOutcome,
    minimum_validation_outcome_id: str,
    scientific_acceptance_ids: tuple[str, ...] = (),
) -> ReviewBundle:
    """Build one non-authorizing projection from exact persisted public records."""

    try:
        if not isinstance(core_store, SQLiteRuntimeStore):
            raise ReviewBundleError("core_store must be a SQLiteRuntimeStore")
        if not isinstance(validation_store, SQLiteScientificValidationStore):
            raise ReviewBundleError(
                "validation_store must be a SQLiteScientificValidationStore"
            )
        if not isinstance(input_binding, InputBinding):
            raise ReviewBundleError("input_binding must be an InputBinding")
        if not isinstance(output_envelope, OutputEnvelope):
            raise ReviewBundleError("output_envelope must be an OutputEnvelope")
        if not isinstance(parse_outcome, ParseOutcome):
            raise ReviewBundleError("parse_outcome must be a ParseOutcome")
        if not isinstance(minimum_validation_outcome_id, str) or not minimum_validation_outcome_id:
            raise ReviewBundleError("minimum_validation_outcome_id must be non-empty")
        if not isinstance(scientific_acceptance_ids, tuple) or not all(
            isinstance(item, str) and item for item in scientific_acceptance_ids
        ):
            raise ReviewBundleError("scientific_acceptance_ids must be a tuple of IDs")
        if len(scientific_acceptance_ids) != len(set(scientific_acceptance_ids)):
            raise ReviewBundleError("scientific_acceptance_ids must be distinct")

        plan = core_store.load_calculation_plan(input_binding.calculation_plan_id)
        attempt = core_store.load_attempt(input_binding.attempt_id)
        _persisted_result_chain(core_store, input_binding, output_envelope, parse_outcome)
        outcome = validation_store.load_minimum_validation(
            minimum_validation_outcome_id
        )
        acceptances = tuple(
            validation_store.load_scientific_acceptance(item)
            for item in scientific_acceptance_ids
        )

        if (
            plan.task_id != attempt.task_id
            or plan.calculation_plan_id != input_binding.calculation_plan_id
            or plan.revision != input_binding.calculation_plan_revision
            or attempt.attempt_id != input_binding.attempt_id
            or output_envelope.attempt_id != attempt.attempt_id
            or output_envelope.input_binding_observation_id != input_binding.observation_id
            or output_envelope.execution_snapshot_id != input_binding.execution_snapshot_id
            or parse_outcome.attempt_id != attempt.attempt_id
            or parse_outcome.envelope_observation_id != output_envelope.observation_id
            or outcome.calculation_plan_id != plan.calculation_plan_id
            or outcome.calculation_plan_revision != plan.revision
            or outcome.attempt_id != attempt.attempt_id
            or outcome.input_binding_observation_id != input_binding.observation_id
            or outcome.envelope_observation_id != output_envelope.observation_id
            or outcome.parse_result_id != parse_outcome.result_id
            or outcome.parser_name != parse_outcome.parser_name
            or outcome.parser_version != parse_outcome.parser_version
            or outcome.result_kind != parse_outcome.result_kind
        ):
            raise ReviewBundleError("ReviewBundle authority chain does not close")
        if any(not _acceptance_closes(item, outcome) for item in acceptances):
            raise ReviewBundleError("ScientificAcceptance does not bind the exact outcome")

        ordered_acceptances = tuple(
            sorted(acceptances, key=lambda item: item.scientific_acceptance_id)
        )
        if outcome.classification is MinimumValidationClassification.VALIDATED_MINIMUM:
            acceptance_state = (
                ReviewAcceptanceState.ACCEPTED
                if ordered_acceptances
                else ReviewAcceptanceState.ELIGIBLE_UNACCEPTED
            )
        else:
            if ordered_acceptances:
                raise ReviewBundleError(
                    "non-VALIDATED_MINIMUM outcome cannot project acceptances"
                )
            acceptance_state = ReviewAcceptanceState.INELIGIBLE

        return ReviewBundle._create(
            calculation_plan={
                "calculation_plan_id": plan.calculation_plan_id,
                "task_id": plan.task_id,
                "revision": plan.revision,
                "intent": plan.intent,
            },
            attempt={
                "attempt_id": attempt.attempt_id,
                "task_id": attempt.task_id,
                "ordinal": attempt.ordinal,
            },
            input_binding=_input_binding_projection(input_binding),
            execution_snapshot_id=input_binding.execution_snapshot_id,
            output_envelope=_output_envelope_projection(output_envelope),
            parse_outcome=_parse_outcome_projection(parse_outcome),
            selected_final_geometry=outcome.selected_geometry_block,
            selected_frequency_blocks=outcome.selected_frequency_blocks,
            selected_frequencies_cm1=outcome.selected_frequencies_cm1,
            minimum_validation_outcome=_minimum_validation_projection(outcome),
            minimum_validation_classification=outcome.classification,
            primary_reason_code=outcome.reason_code,
            scientific_acceptance_state=acceptance_state,
            scientific_acceptances=tuple(
                _scientific_acceptance_projection(item)
                for item in ordered_acceptances
            ),
        )
    except ReviewBundleError:
        raise
    except Exception as exc:
        raise ReviewBundleError("ReviewBundle construction failed closed") from exc


def render_review_bundle_json(bundle: ReviewBundle) -> str:
    """Render the exact complete public ReviewBundle as deterministic JSON."""

    try:
        if not isinstance(bundle, ReviewBundle):
            raise ReviewBundleError("bundle must be a ReviewBundle")
        bundle._assert_identity()
        payload = {
            "schema_version": bundle.schema_version,
            "review_bundle_id": bundle.review_bundle_id,
            "calculation_plan": bundle.calculation_plan,
            "attempt": bundle.attempt,
            "input_binding": bundle.input_binding,
            "execution_snapshot_id": bundle.execution_snapshot_id,
            "output_envelope": bundle.output_envelope,
            "parse_outcome": bundle.parse_outcome,
            "selected_final_geometry": bundle.selected_final_geometry,
            "selected_frequency_blocks": bundle.selected_frequency_blocks,
            "selected_frequencies_cm1": bundle.selected_frequencies_cm1,
            "minimum_validation_outcome": bundle.minimum_validation_outcome,
            "minimum_validation_classification": bundle.minimum_validation_classification,
            "primary_reason_code": bundle.primary_reason_code,
            "scientific_acceptance_state": bundle.scientific_acceptance_state,
            "scientific_acceptances": bundle.scientific_acceptances,
        }
        return json.dumps(
            plain_value(payload),
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
            separators=(",", ": "),
        ) + "\n"
    except ReviewBundleError:
        raise
    except Exception as exc:
        raise ReviewBundleError("ReviewBundle rendering failed closed") from exc
