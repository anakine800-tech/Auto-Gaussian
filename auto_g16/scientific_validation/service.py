"""Pure minimum classification and explicit human acceptance services."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from auto_g16.core import SQLiteRuntimeStore
from auto_g16.result import (
    INPUT_BINDING_OBSERVATION,
    OUTPUT_ENVELOPE_OBSERVATION,
    PARSED_RESULT_TYPE,
    CaptureCompleteness,
    InputBinding,
    OutputEnvelope,
    ParseOutcome,
    ParseStatus,
)

from .models import (
    MinimumValidationClassification,
    MinimumValidationOutcome,
    ScientificAcceptance,
    ScientificValidationError,
    _assert_minimum_validation_semantics,
)
from .store import SQLiteScientificValidationStore


_SUPPORTED_RESULT_TUPLE = (
    "auto-g16-v3-gaussian-job",
    "1.0.0",
    "gaussian-job-facts",
)


def _same_semantics(left: Mapping[str, object], right: Mapping[str, object]) -> bool:
    return left == right


def _provenance_is_closed(
    core_store: SQLiteRuntimeStore,
    input_binding: InputBinding,
    envelope: OutputEnvelope,
    parse_outcome: ParseOutcome,
) -> bool:
    try:
        attempt = core_store.load_attempt(input_binding.attempt_id)
        plan = core_store.load_calculation_plan(input_binding.calculation_plan_id)
        if (
            attempt.task_id != plan.task_id
            or plan.revision != input_binding.calculation_plan_revision
            or envelope.attempt_id != input_binding.attempt_id
            or envelope.input_binding_observation_id != input_binding.observation_id
            or envelope.execution_snapshot_id != input_binding.execution_snapshot_id
            or parse_outcome.attempt_id != input_binding.attempt_id
            or parse_outcome.envelope_observation_id != envelope.observation_id
        ):
            return False

        observed_bindings: list[InputBinding] = []
        observed_envelopes: list[OutputEnvelope] = []
        for record in core_store.observations_for_attempt(input_binding.attempt_id):
            if record.observation_type == INPUT_BINDING_OBSERVATION:
                decoded = InputBinding.from_payload(record.data)
                if (
                    decoded.observation_id != record.observation_id
                    or decoded.attempt_id != record.attempt_id
                ):
                    return False
                observed_bindings.append(decoded)
            elif record.observation_type == OUTPUT_ENVELOPE_OBSERVATION:
                decoded_envelope = OutputEnvelope.from_payload(record.data)
                if (
                    decoded_envelope.observation_id != record.observation_id
                    or decoded_envelope.attempt_id != record.attempt_id
                ):
                    return False
                observed_envelopes.append(decoded_envelope)
        if len(observed_bindings) != 1 or not _same_semantics(
            observed_bindings[0].payload(), input_binding.payload()
        ):
            return False
        exact_envelopes = [
            item
            for item in observed_envelopes
            if item.observation_id == envelope.observation_id
        ]
        if len(exact_envelopes) != 1 or not _same_semantics(
            exact_envelopes[0].payload(), envelope.payload()
        ):
            return False

        exact_results: list[ParseOutcome] = []
        for record in core_store.results_for_attempt(input_binding.attempt_id):
            if record.result_type != PARSED_RESULT_TYPE:
                continue
            decoded_result = ParseOutcome.from_payload(record.data)
            if (
                decoded_result.result_id != record.result_id
                or decoded_result.attempt_id != record.attempt_id
            ):
                return False
            if decoded_result.result_id == parse_outcome.result_id:
                exact_results.append(decoded_result)
        if len(exact_results) != 1 or not _same_semantics(
            exact_results[0].payload(), parse_outcome.payload()
        ):
            return False
        if parse_outcome.result_kind == "gaussian-job-facts" and parse_outcome.facts:
            source = parse_outcome.facts.get("source_artifact")
            gaussian_logs = tuple(
                item
                for item in envelope.artifacts
                if item.artifact_kind == "gaussian-log"
            )
            if not isinstance(source, Mapping) or len(gaussian_logs) != 1:
                return False
            if source.get("envelope_observation_id") != envelope.observation_id:
                return False
            if {
                key: source.get(key)
                for key in ("artifact_kind", "logical_name", "sha256", "size_bytes")
            } != gaussian_logs[0].payload():
                return False
        return True
    except Exception:
        return False


def _span_bounds(span: Mapping[str, object]) -> tuple[int, int]:
    start = span["start"]
    end = span["end"]
    if (
        isinstance(start, bool)
        or not isinstance(start, int)
        or isinstance(end, bool)
        or not isinstance(end, int)
    ):
        raise ScientificValidationError("Result source span is malformed")
    return start, end


def _outcome(
    input_binding: InputBinding,
    envelope: OutputEnvelope,
    parse_outcome: ParseOutcome,
    *,
    classification: MinimumValidationClassification,
    reason_code: str,
    source_artifact: Mapping[str, object] | None = None,
    job_section: Mapping[str, object] | None = None,
    accepted_optimization_span: Mapping[str, object] | None = None,
    accepted_stationary_span: Mapping[str, object] | None = None,
    selected_geometry_block: Mapping[str, object] | None = None,
    selected_frequency_blocks: Sequence[Mapping[str, object]] = (),
    selected_frequencies_cm1: Sequence[float] = (),
) -> MinimumValidationOutcome:
    return MinimumValidationOutcome._create(
        calculation_plan_id=input_binding.calculation_plan_id,
        calculation_plan_revision=input_binding.calculation_plan_revision,
        attempt_id=input_binding.attempt_id,
        input_binding_observation_id=input_binding.observation_id,
        envelope_observation_id=envelope.observation_id,
        parse_result_id=parse_outcome.result_id,
        parser_name=parse_outcome.parser_name,
        parser_version=parse_outcome.parser_version,
        result_kind=parse_outcome.result_kind,
        source_artifact=source_artifact,
        job_section=job_section,
        accepted_optimization_span=accepted_optimization_span,
        accepted_stationary_span=accepted_stationary_span,
        selected_geometry_block=selected_geometry_block,
        selected_frequency_blocks=selected_frequency_blocks,
        selected_frequencies_cm1=selected_frequencies_cm1,
        classification=classification,
        reason_code=reason_code,
    )


def validate_minimum(
    core_store: SQLiteRuntimeStore,
    input_binding: InputBinding,
    envelope: OutputEnvelope,
    parse_outcome: ParseOutcome,
) -> MinimumValidationOutcome:
    """Classify one exact persisted attributed Result without reading artifacts."""

    if not isinstance(core_store, SQLiteRuntimeStore):
        raise ScientificValidationError("core_store must be a SQLiteRuntimeStore")
    if not isinstance(input_binding, InputBinding):
        raise ScientificValidationError("input_binding must be an InputBinding")
    if not isinstance(envelope, OutputEnvelope):
        raise ScientificValidationError("envelope must be an OutputEnvelope")
    if not isinstance(parse_outcome, ParseOutcome):
        raise ScientificValidationError("parse_outcome must be a ParseOutcome")

    # Frozen first-applicable reason order begins here.
    if not _provenance_is_closed(core_store, input_binding, envelope, parse_outcome):
        return _outcome(
            input_binding,
            envelope,
            parse_outcome,
            classification=MinimumValidationClassification.INCOMPLETE,
            reason_code="incomplete-provenance",
        )
    if envelope.capture_completeness is not CaptureCompleteness.COMPLETE:
        return _outcome(
            input_binding,
            envelope,
            parse_outcome,
            classification=MinimumValidationClassification.INCOMPLETE,
            reason_code="incomplete-capture",
        )
    parser_tuple = (
        parse_outcome.parser_name,
        parse_outcome.parser_version,
        parse_outcome.result_kind,
    )
    if parser_tuple != _SUPPORTED_RESULT_TUPLE:
        return _outcome(
            input_binding,
            envelope,
            parse_outcome,
            classification=MinimumValidationClassification.UNSUPPORTED,
            reason_code="unsupported-result-tuple",
        )
    if parse_outcome.parse_status is ParseStatus.UNSUPPORTED:
        return _outcome(
            input_binding,
            envelope,
            parse_outcome,
            classification=MinimumValidationClassification.UNSUPPORTED,
            reason_code="unsupported-parse-status",
        )
    if parse_outcome.parse_status is not ParseStatus.PARSED or not parse_outcome.facts:
        return _outcome(
            input_binding,
            envelope,
            parse_outcome,
            classification=MinimumValidationClassification.INCOMPLETE,
            reason_code="incomplete-parse",
        )

    facts = parse_outcome.facts
    source_artifact = facts["source_artifact"]
    job_section = facts["job_section"]
    if not isinstance(source_artifact, Mapping) or not isinstance(job_section, Mapping):
        raise ScientificValidationError("parsed Result source authority is malformed")
    if facts["program_status"] == "error-termination":
        return _outcome(
            input_binding,
            envelope,
            parse_outcome,
            source_artifact=source_artifact,
            job_section=job_section,
            classification=MinimumValidationClassification.INCOMPLETE,
            reason_code="incomplete-error-termination",
        )
    terminal = facts["termination_evidence"]
    if (
        facts["program_status"] != "normal-termination"
        or facts["normal_termination_count"] != 1
        or facts["error_termination_count"] != 0
        or not isinstance(terminal, tuple)
        or len(terminal) != 1
        or terminal[0]["kind"] != "normal-termination"  # type: ignore[index]
    ):
        return _outcome(
            input_binding,
            envelope,
            parse_outcome,
            source_artifact=source_artifact,
            job_section=job_section,
            classification=MinimumValidationClassification.INCOMPLETE,
            reason_code="incomplete-terminal-evidence",
        )

    optimization = facts["optimization_completed_evidence"]
    stationary = facts["stationary_point_evidence"]
    pair_closed = (
        isinstance(optimization, tuple)
        and isinstance(stationary, tuple)
        and bool(optimization)
        and len(optimization) == len(stationary)
    )
    if pair_closed:
        try:
            for index, (opt_span, stat_span) in enumerate(zip(optimization, stationary)):
                if not isinstance(opt_span, Mapping) or not isinstance(stat_span, Mapping):
                    pair_closed = False
                    break
                if _span_bounds(opt_span)[1] > _span_bounds(stat_span)[0]:
                    pair_closed = False
                    break
                if index + 1 < len(optimization):
                    next_opt = optimization[index + 1]
                    if (
                        not isinstance(next_opt, Mapping)
                        or _span_bounds(stat_span)[1] > _span_bounds(next_opt)[0]
                    ):
                        pair_closed = False
                        break
        except (KeyError, ScientificValidationError):
            pair_closed = False
    if not pair_closed:
        return _outcome(
            input_binding,
            envelope,
            parse_outcome,
            source_artifact=source_artifact,
            job_section=job_section,
            classification=MinimumValidationClassification.INCOMPLETE,
            reason_code="incomplete-marker-pair",
        )
    accepted_optimization = optimization[-1]
    accepted_stationary = stationary[-1]
    assert isinstance(accepted_optimization, Mapping)
    assert isinstance(accepted_stationary, Mapping)

    geometries = facts["geometry_blocks"]
    eligible_geometries: list[Mapping[str, object]] = []
    if isinstance(geometries, tuple):
        for geometry in geometries:
            if not isinstance(geometry, Mapping):
                continue
            span = geometry.get("source_span")
            if isinstance(span, Mapping) and _span_bounds(span)[1] <= _span_bounds(
                accepted_optimization
            )[0]:
                eligible_geometries.append(geometry)
    unique_geometry = False
    selected_geometry: Mapping[str, object] | None = None
    if eligible_geometries:
        rightmost_end = max(
            _span_bounds(item["source_span"])[1]  # type: ignore[arg-type]
            for item in eligible_geometries
        )
        rightmost = [
            item
            for item in eligible_geometries
            if _span_bounds(item["source_span"])[1] == rightmost_end  # type: ignore[arg-type]
        ]
        if len(rightmost) == 1:
            unique_geometry = True
            selected_geometry = rightmost[0]
    if not unique_geometry or selected_geometry is None:
        return _outcome(
            input_binding,
            envelope,
            parse_outcome,
            source_artifact=source_artifact,
            job_section=job_section,
            accepted_optimization_span=accepted_optimization,
            accepted_stationary_span=accepted_stationary,
            classification=MinimumValidationClassification.INCOMPLETE,
            reason_code="incomplete-final-geometry",
        )

    frequency_blocks = facts["frequency_blocks"]
    selected_blocks: tuple[Mapping[str, object], ...] = ()
    if isinstance(frequency_blocks, tuple):
        selected_blocks = tuple(
            block
            for block in frequency_blocks
            if isinstance(block, Mapping)
            and isinstance(block.get("source_span"), Mapping)
            and _span_bounds(block["source_span"])[0]  # type: ignore[arg-type]
            >= _span_bounds(accepted_stationary)[1]
        )
    selected_frequencies = tuple(
        frequency
        for block in selected_blocks
        for frequency in block["frequencies_cm-1"]  # type: ignore[union-attr]
    )
    atoms = selected_geometry["atoms"]
    if not isinstance(atoms, tuple):
        raise ScientificValidationError("selected Result geometry atoms are malformed")
    common = {
        "source_artifact": source_artifact,
        "job_section": job_section,
        "accepted_optimization_span": accepted_optimization,
        "accepted_stationary_span": accepted_stationary,
        "selected_geometry_block": selected_geometry,
        "selected_frequency_blocks": selected_blocks,
        "selected_frequencies_cm1": selected_frequencies,
    }
    if len(atoms) < 3:
        return _outcome(
            input_binding,
            envelope,
            parse_outcome,
            **common,
            classification=MinimumValidationClassification.UNSUPPORTED,
            reason_code="unsupported-atom-cardinality",
        )
    if any(atom["atomic_number"] == 0 for atom in atoms):  # type: ignore[index]
        return _outcome(
            input_binding,
            envelope,
            parse_outcome,
            **common,
            classification=MinimumValidationClassification.UNSUPPORTED,
            reason_code="unsupported-dummy-center",
        )
    expected_modes = 3 * len(atoms) - 6
    if len(selected_frequencies) < expected_modes:
        return _outcome(
            input_binding,
            envelope,
            parse_outcome,
            **common,
            classification=MinimumValidationClassification.INCOMPLETE,
            reason_code="incomplete-mode-count",
        )
    if len(selected_frequencies) > expected_modes:
        return _outcome(
            input_binding,
            envelope,
            parse_outcome,
            **common,
            classification=MinimumValidationClassification.UNSUPPORTED,
            reason_code="unsupported-mode-count",
        )
    if any(frequency < 0.0 for frequency in selected_frequencies):
        return _outcome(
            input_binding,
            envelope,
            parse_outcome,
            **common,
            classification=MinimumValidationClassification.NOT_MINIMUM,
            reason_code="negative-frequency",
        )
    return _outcome(
        input_binding,
        envelope,
        parse_outcome,
        **common,
        classification=MinimumValidationClassification.VALIDATED_MINIMUM,
        reason_code="validated-minimum",
    )


def record_minimum_validation(
    store: SQLiteScientificValidationStore,
    outcome: MinimumValidationOutcome,
) -> MinimumValidationOutcome:
    if not isinstance(store, SQLiteScientificValidationStore):
        raise ScientificValidationError(
            "store must be a SQLiteScientificValidationStore"
        )
    if not isinstance(outcome, MinimumValidationOutcome):
        raise ScientificValidationError("outcome must be a MinimumValidationOutcome")
    store._record_minimum_validation(outcome)
    return store.load_minimum_validation(outcome.minimum_validation_outcome_id)


def record_scientific_acceptance(
    store: SQLiteScientificValidationStore,
    *,
    minimum_validation_outcome_id: str,
    reviewer_id: str,
    review_evidence: Mapping[str, object],
) -> ScientificAcceptance:
    if not isinstance(store, SQLiteScientificValidationStore):
        raise ScientificValidationError(
            "store must be a SQLiteScientificValidationStore"
        )
    outcome = store.load_minimum_validation(minimum_validation_outcome_id)
    _assert_minimum_validation_semantics(outcome)
    if outcome.classification is not MinimumValidationClassification.VALIDATED_MINIMUM:
        raise ScientificValidationError(
            "ScientificAcceptance requires a persisted VALIDATED_MINIMUM"
        )
    acceptance = ScientificAcceptance._from_outcome(
        outcome,
        reviewer_id=reviewer_id,
        review_evidence=review_evidence,
    )
    store._record_scientific_acceptance(acceptance)
    return store.load_scientific_acceptance(acceptance.scientific_acceptance_id)


def require_scientific_acceptance(
    store: SQLiteScientificValidationStore,
    *,
    minimum_validation_outcome_id: str,
    scientific_acceptance_id: str,
) -> tuple[MinimumValidationOutcome, ScientificAcceptance]:
    if not isinstance(store, SQLiteScientificValidationStore):
        raise ScientificValidationError(
            "store must be a SQLiteScientificValidationStore"
        )
    outcome = store.load_minimum_validation(minimum_validation_outcome_id)
    _assert_minimum_validation_semantics(outcome)
    acceptance = store.load_scientific_acceptance(scientific_acceptance_id)
    expected = (
        outcome.minimum_validation_outcome_id,
        outcome.validation_policy_id,
        outcome.validation_policy_version,
        outcome.calculation_plan_id,
        outcome.calculation_plan_revision,
        outcome.attempt_id,
        outcome.parse_result_id,
        outcome.classification,
    )
    observed = (
        acceptance.minimum_validation_outcome_id,
        acceptance.validation_policy_id,
        acceptance.validation_policy_version,
        acceptance.calculation_plan_id,
        acceptance.calculation_plan_revision,
        acceptance.attempt_id,
        acceptance.parse_result_id,
        acceptance.classification,
    )
    if (
        outcome.classification is not MinimumValidationClassification.VALIDATED_MINIMUM
        or observed != expected
    ):
        raise ScientificValidationError(
            "ScientificAcceptance does not bind the exact eligible outcome"
        )
    return outcome, acceptance
