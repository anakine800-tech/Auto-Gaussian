"""Immutable public ReviewBundle projection records."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum

from auto_g16.scientific_validation import MinimumValidationClassification

from ._canonical import bundle_identity, freeze_mapping, freeze_value


class ReviewBundleError(ValueError):
    """The supplied authority cannot form one exact ReviewBundle."""


class ReviewAcceptanceState(str, Enum):
    INELIGIBLE = "ineligible"
    ELIGIBLE_UNACCEPTED = "eligible-unaccepted"
    ACCEPTED = "accepted"


@dataclass(frozen=True, slots=True, kw_only=True, init=False)
class ReviewBundle:
    schema_version: int
    review_bundle_id: str = field(init=False)
    calculation_plan: Mapping[str, object]
    attempt: Mapping[str, object]
    input_binding: Mapping[str, object]
    execution_snapshot_id: str
    output_envelope: Mapping[str, object]
    parse_outcome: Mapping[str, object]
    selected_final_geometry: Mapping[str, object] | None
    selected_frequency_blocks: tuple[Mapping[str, object], ...]
    selected_frequencies_cm1: tuple[float, ...]
    minimum_validation_outcome: Mapping[str, object]
    minimum_validation_classification: MinimumValidationClassification
    primary_reason_code: str
    scientific_acceptance_state: ReviewAcceptanceState
    scientific_acceptances: tuple[Mapping[str, object], ...]

    def __init__(self) -> None:
        raise TypeError("ReviewBundle is service-created")

    @classmethod
    def _create(
        cls,
        *,
        calculation_plan: Mapping[str, object],
        attempt: Mapping[str, object],
        input_binding: Mapping[str, object],
        execution_snapshot_id: str,
        output_envelope: Mapping[str, object],
        parse_outcome: Mapping[str, object],
        selected_final_geometry: Mapping[str, object] | None,
        selected_frequency_blocks: Sequence[Mapping[str, object]],
        selected_frequencies_cm1: Sequence[float],
        minimum_validation_outcome: Mapping[str, object],
        minimum_validation_classification: MinimumValidationClassification,
        primary_reason_code: str,
        scientific_acceptance_state: ReviewAcceptanceState,
        scientific_acceptances: Sequence[Mapping[str, object]],
    ) -> ReviewBundle:
        value = object.__new__(cls)
        object.__setattr__(value, "schema_version", 1)
        object.__setattr__(value, "calculation_plan", freeze_mapping(calculation_plan, "calculation_plan"))
        object.__setattr__(value, "attempt", freeze_mapping(attempt, "attempt"))
        object.__setattr__(value, "input_binding", freeze_mapping(input_binding, "input_binding"))
        if not isinstance(execution_snapshot_id, str) or not execution_snapshot_id:
            raise ValueError("execution_snapshot_id must be a non-empty string")
        object.__setattr__(value, "execution_snapshot_id", execution_snapshot_id)
        object.__setattr__(value, "output_envelope", freeze_mapping(output_envelope, "output_envelope"))
        object.__setattr__(value, "parse_outcome", freeze_mapping(parse_outcome, "parse_outcome"))
        object.__setattr__(
            value,
            "selected_final_geometry",
            None if selected_final_geometry is None else freeze_mapping(selected_final_geometry, "selected_final_geometry"),
        )
        blocks = tuple(
            freeze_mapping(item, f"selected_frequency_blocks[{index}]")
            for index, item in enumerate(selected_frequency_blocks)
        )
        object.__setattr__(value, "selected_frequency_blocks", blocks)
        frequencies = freeze_value(tuple(selected_frequencies_cm1), "selected_frequencies_cm1")
        assert isinstance(frequencies, tuple)
        if any(type(item) is not float for item in frequencies):
            raise ValueError("selected_frequencies_cm1 must contain only finite floats")
        object.__setattr__(value, "selected_frequencies_cm1", frequencies)
        object.__setattr__(
            value,
            "minimum_validation_outcome",
            freeze_mapping(minimum_validation_outcome, "minimum_validation_outcome"),
        )
        try:
            classification = MinimumValidationClassification(minimum_validation_classification)
            acceptance_state = ReviewAcceptanceState(scientific_acceptance_state)
        except ValueError as exc:
            raise ValueError("ReviewBundle enum value is not frozen") from exc
        object.__setattr__(value, "minimum_validation_classification", classification)
        if not isinstance(primary_reason_code, str) or not primary_reason_code:
            raise ValueError("primary_reason_code must be a non-empty string")
        object.__setattr__(value, "primary_reason_code", primary_reason_code)
        object.__setattr__(value, "scientific_acceptance_state", acceptance_state)
        acceptances = tuple(
            freeze_mapping(item, f"scientific_acceptances[{index}]")
            for index, item in enumerate(scientific_acceptances)
        )
        object.__setattr__(value, "scientific_acceptances", acceptances)
        object.__setattr__(value, "review_bundle_id", bundle_identity(value._identity_payload()))
        return value

    def _identity_payload(self) -> Mapping[str, object]:
        return {
            "schema_version": self.schema_version,
            "calculation_plan": self.calculation_plan,
            "attempt": self.attempt,
            "input_binding": self.input_binding,
            "execution_snapshot_id": self.execution_snapshot_id,
            "output_envelope": self.output_envelope,
            "parse_outcome": self.parse_outcome,
            "selected_final_geometry": self.selected_final_geometry,
            "selected_frequency_blocks": self.selected_frequency_blocks,
            "selected_frequencies_cm1": self.selected_frequencies_cm1,
            "minimum_validation_outcome": self.minimum_validation_outcome,
            "minimum_validation_classification": self.minimum_validation_classification.value,
            "primary_reason_code": self.primary_reason_code,
            "scientific_acceptance_state": self.scientific_acceptance_state.value,
            "scientific_acceptances": self.scientific_acceptances,
        }

    def _assert_identity(self) -> None:
        if self.review_bundle_id != bundle_identity(self._identity_payload()):
            raise ReviewBundleError("ReviewBundle identity does not close over its payload")
