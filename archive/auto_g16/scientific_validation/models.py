"""Immutable records for the frozen ScientificValidation boundary."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
import json
from math import isfinite
from typing import Final, NoReturn
from uuid import UUID, uuid5


_SCHEMA_VERSION: Final = 1
_POLICY_ID: Final = "auto-g16-v3-minimum-validation"
_POLICY_VERSION: Final = "1.0.0"
_NAMESPACE: Final = UUID("f4617d31-5b90-5c79-888a-9b9ccec5e612")
_DOMAINS: Final = frozenset(
    {"minimum-validation-outcome", "scientific-acceptance"}
)


class ScientificValidationError(ValueError):
    """ScientificValidation input or authority is invalid."""


class ScientificValidationConflictError(ScientificValidationError):
    """One immutable identity has conflicting authority content."""


class ScientificValidationPersistenceIntegrityError(ScientificValidationError):
    """ScientificValidation persistence is malformed or unsafe to use."""


class MinimumValidationClassification(str, Enum):
    VALIDATED_MINIMUM = "VALIDATED_MINIMUM"
    NOT_MINIMUM = "NOT_MINIMUM"
    INCOMPLETE = "INCOMPLETE"
    UNSUPPORTED = "UNSUPPORTED"


class _FrozenMapping(Mapping[str, object]):
    __slots__ = ("_items",)

    def __init__(self, items: tuple[tuple[str, object], ...]) -> None:
        self._items = items

    def __getitem__(self, key: str) -> object:
        for item_key, value in self._items:
            if item_key == key:
                return value
        raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        return (key for key, _value in self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __repr__(self) -> str:
        return repr(dict(self._items))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Mapping):
            return False
        try:
            frozen = _freeze_mapping(other, "mapping")
        except ScientificValidationError:
            return False
        return self._items == frozen._items

    def __hash__(self) -> int:
        return hash(self._items)


def _text(value: object, name: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or "\x00" in value
    ):
        raise ScientificValidationError(
            f"{name} must be a non-empty canonical string"
        )
    return value


def _positive_integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ScientificValidationError(f"{name} must be a positive integer")
    return value


def _freeze_value(value: object, path: str, active: set[int]) -> object:
    if value is None or type(value) in {bool, int, str}:
        return value
    if type(value) is float:
        if not isfinite(value):
            raise ScientificValidationError(
                f"{path} must not contain a non-finite float"
            )
        return value
    if isinstance(value, Mapping):
        identity = id(value)
        if identity in active:
            raise ScientificValidationError(f"{path} must not contain a cycle")
        active.add(identity)
        try:
            items: list[tuple[str, object]] = []
            for key, item in value.items():
                if not isinstance(key, str) or not key:
                    raise ScientificValidationError(
                        f"{path} keys must be non-empty strings"
                    )
                items.append((key, _freeze_value(item, f"{path}.{key}", active)))
            return _FrozenMapping(tuple(sorted(items)))
        finally:
            active.remove(identity)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        identity = id(value)
        if identity in active:
            raise ScientificValidationError(f"{path} must not contain a cycle")
        active.add(identity)
        try:
            return tuple(
                _freeze_value(item, f"{path}[{index}]", active)
                for index, item in enumerate(value)
            )
        finally:
            active.remove(identity)
    raise ScientificValidationError(
        f"{path} contains unsupported value type {type(value).__name__}"
    )


def _freeze_mapping(value: Mapping[str, object], name: str) -> _FrozenMapping:
    frozen = _freeze_value(value, name, set())
    if not isinstance(frozen, _FrozenMapping):
        raise ScientificValidationError(f"{name} must be a mapping")
    return frozen


def _optional_mapping(
    value: Mapping[str, object] | None, name: str
) -> _FrozenMapping | None:
    return None if value is None else _freeze_mapping(value, name)


def _plain(value: object) -> object:
    if isinstance(value, MinimumValidationClassification):
        return value.value
    if isinstance(value, Mapping):
        return {key: _plain(value[key]) for key in sorted(value)}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_plain(item) for item in value]
    return value


def _canonical_node(value: object) -> object:
    if value is None:
        return ["null", None]
    if type(value) is bool:
        return ["boolean", value]
    if type(value) is int:
        return ["integer", value]
    if type(value) is float:
        if not isfinite(value):
            raise ScientificValidationError("identity contains a non-finite float")
        return ["float", value]
    if type(value) is str:
        return ["string", value]
    if isinstance(value, Mapping):
        return [
            "mapping",
            [[key, _canonical_node(value[key])] for key in sorted(value)],
        ]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return ["sequence", [_canonical_node(item) for item in value]]
    raise ScientificValidationError(
        f"identity contains unsupported value type {type(value).__name__}"
    )


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        _canonical_node(value),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=False,
    ).encode("utf-8")


def _identity(domain: str, authority: Mapping[str, object]) -> str:
    if domain not in _DOMAINS:
        raise ScientificValidationError(
            f"unsupported ScientificValidation identity domain {domain!r}"
        )
    namespace = uuid5(
        _NAMESPACE,
        f"auto_g16.scientific_validation/v{_SCHEMA_VERSION}/{domain}",
    )
    name = _canonical_bytes(
        {
            "schema_version": _SCHEMA_VERSION,
            "domain": domain,
            "authority": authority,
        }
    ).decode("utf-8")
    return str(uuid5(namespace, name))


@dataclass(frozen=True, slots=True, kw_only=True, init=False)
class MinimumValidationOutcome:
    schema_version: int
    minimum_validation_outcome_id: str = field(init=False)
    validation_policy_id: str
    validation_policy_version: str
    calculation_plan_id: str
    calculation_plan_revision: int
    attempt_id: str
    input_binding_observation_id: str
    envelope_observation_id: str
    parse_result_id: str
    parser_name: str
    parser_version: str
    result_kind: str
    source_artifact: Mapping[str, object] | None
    job_section: Mapping[str, object] | None
    accepted_optimization_span: Mapping[str, object] | None
    accepted_stationary_span: Mapping[str, object] | None
    selected_geometry_block: Mapping[str, object] | None
    selected_frequency_blocks: tuple[Mapping[str, object], ...]
    selected_frequencies_cm1: tuple[float, ...]
    classification: MinimumValidationClassification
    reason_code: str

    def __init__(self) -> None:
        raise TypeError("MinimumValidationOutcome is service-created")

    @classmethod
    def _create(
        cls,
        *,
        calculation_plan_id: str,
        calculation_plan_revision: int,
        attempt_id: str,
        input_binding_observation_id: str,
        envelope_observation_id: str,
        parse_result_id: str,
        parser_name: str,
        parser_version: str,
        result_kind: str,
        source_artifact: Mapping[str, object] | None,
        job_section: Mapping[str, object] | None,
        accepted_optimization_span: Mapping[str, object] | None,
        accepted_stationary_span: Mapping[str, object] | None,
        selected_geometry_block: Mapping[str, object] | None,
        selected_frequency_blocks: Sequence[Mapping[str, object]],
        selected_frequencies_cm1: Sequence[float],
        classification: MinimumValidationClassification,
        reason_code: str,
        expected_id: str | None = None,
    ) -> MinimumValidationOutcome:
        value = object.__new__(cls)
        object.__setattr__(value, "schema_version", _SCHEMA_VERSION)
        object.__setattr__(value, "validation_policy_id", _POLICY_ID)
        object.__setattr__(value, "validation_policy_version", _POLICY_VERSION)
        object.__setattr__(value, "calculation_plan_id", _text(calculation_plan_id, "calculation_plan_id"))
        object.__setattr__(value, "calculation_plan_revision", _positive_integer(calculation_plan_revision, "calculation_plan_revision"))
        object.__setattr__(value, "attempt_id", _text(attempt_id, "attempt_id"))
        object.__setattr__(value, "input_binding_observation_id", _text(input_binding_observation_id, "input_binding_observation_id"))
        object.__setattr__(value, "envelope_observation_id", _text(envelope_observation_id, "envelope_observation_id"))
        object.__setattr__(value, "parse_result_id", _text(parse_result_id, "parse_result_id"))
        object.__setattr__(value, "parser_name", _text(parser_name, "parser_name"))
        object.__setattr__(value, "parser_version", _text(parser_version, "parser_version"))
        object.__setattr__(value, "result_kind", _text(result_kind, "result_kind"))
        object.__setattr__(value, "source_artifact", _optional_mapping(source_artifact, "source_artifact"))
        object.__setattr__(value, "job_section", _optional_mapping(job_section, "job_section"))
        object.__setattr__(value, "accepted_optimization_span", _optional_mapping(accepted_optimization_span, "accepted_optimization_span"))
        object.__setattr__(value, "accepted_stationary_span", _optional_mapping(accepted_stationary_span, "accepted_stationary_span"))
        object.__setattr__(value, "selected_geometry_block", _optional_mapping(selected_geometry_block, "selected_geometry_block"))
        blocks = tuple(
            _freeze_mapping(item, f"selected_frequency_blocks[{index}]")
            for index, item in enumerate(selected_frequency_blocks)
        )
        object.__setattr__(value, "selected_frequency_blocks", blocks)
        frequencies = tuple(selected_frequencies_cm1)
        if any(type(item) is not float or not isfinite(item) for item in frequencies):
            raise ScientificValidationError(
                "selected_frequencies_cm1 must contain only finite floats"
            )
        object.__setattr__(value, "selected_frequencies_cm1", frequencies)
        try:
            normalized_classification = MinimumValidationClassification(classification)
        except ValueError as exc:
            raise ScientificValidationError("classification is not frozen") from exc
        object.__setattr__(value, "classification", normalized_classification)
        object.__setattr__(value, "reason_code", _text(reason_code, "reason_code"))
        identity = _identity("minimum-validation-outcome", value._authority_payload())
        if expected_id is not None and expected_id != identity:
            raise ScientificValidationPersistenceIntegrityError(
                "minimum validation identity does not close over its payload"
            )
        object.__setattr__(value, "minimum_validation_outcome_id", identity)
        return value

    def _authority_payload(self) -> Mapping[str, object]:
        return {
            "schema_version": self.schema_version,
            "validation_policy_id": self.validation_policy_id,
            "validation_policy_version": self.validation_policy_version,
            "calculation_plan_id": self.calculation_plan_id,
            "calculation_plan_revision": self.calculation_plan_revision,
            "attempt_id": self.attempt_id,
            "input_binding_observation_id": self.input_binding_observation_id,
            "envelope_observation_id": self.envelope_observation_id,
            "parse_result_id": self.parse_result_id,
            "parser_name": self.parser_name,
            "parser_version": self.parser_version,
            "result_kind": self.result_kind,
            "source_artifact": _plain(self.source_artifact),
            "job_section": _plain(self.job_section),
            "accepted_optimization_span": _plain(self.accepted_optimization_span),
            "accepted_stationary_span": _plain(self.accepted_stationary_span),
            "selected_geometry_block": _plain(self.selected_geometry_block),
            "selected_frequency_blocks": _plain(self.selected_frequency_blocks),
            "selected_frequencies_cm1": _plain(self.selected_frequencies_cm1),
            "classification": self.classification.value,
            "reason_code": self.reason_code,
        }

    def _payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "minimum_validation_outcome_id": self.minimum_validation_outcome_id,
            "validation_policy_id": self.validation_policy_id,
            "validation_policy_version": self.validation_policy_version,
            "calculation_plan_id": self.calculation_plan_id,
            "calculation_plan_revision": self.calculation_plan_revision,
            "attempt_id": self.attempt_id,
            "input_binding_observation_id": self.input_binding_observation_id,
            "envelope_observation_id": self.envelope_observation_id,
            "parse_result_id": self.parse_result_id,
            "parser_name": self.parser_name,
            "parser_version": self.parser_version,
            "result_kind": self.result_kind,
            "source_artifact": _plain(self.source_artifact),
            "job_section": _plain(self.job_section),
            "accepted_optimization_span": _plain(self.accepted_optimization_span),
            "accepted_stationary_span": _plain(self.accepted_stationary_span),
            "selected_geometry_block": _plain(self.selected_geometry_block),
            "selected_frequency_blocks": _plain(self.selected_frequency_blocks),
            "selected_frequencies_cm1": _plain(self.selected_frequencies_cm1),
            "classification": self.classification.value,
            "reason_code": self.reason_code,
        }

    @classmethod
    def _from_payload(cls, payload: Mapping[str, object]) -> MinimumValidationOutcome:
        expected = set(cls.__dataclass_fields__)
        if set(payload) != expected:
            raise ScientificValidationPersistenceIntegrityError(
                "minimum validation row has an invalid closed field set"
            )
        if (
            type(payload["schema_version"]) is not int
            or payload["schema_version"] != _SCHEMA_VERSION
            or payload["validation_policy_id"] != _POLICY_ID
            or payload["validation_policy_version"] != _POLICY_VERSION
        ):
            raise ScientificValidationPersistenceIntegrityError(
                "minimum validation policy or schema is not exact"
            )
        try:
            return cls._create(
                **{
                    key: payload[key]
                    for key in expected
                    if key
                    not in {
                        "schema_version",
                        "minimum_validation_outcome_id",
                        "validation_policy_id",
                        "validation_policy_version",
                    }
                },
                expected_id=payload["minimum_validation_outcome_id"],
            )  # type: ignore[arg-type]
        except ScientificValidationPersistenceIntegrityError:
            raise
        except (ScientificValidationError, TypeError, ValueError) as exc:
            raise ScientificValidationPersistenceIntegrityError(
                "minimum validation row is malformed"
            ) from exc


@dataclass(frozen=True, slots=True, kw_only=True, init=False)
class ScientificAcceptance:
    schema_version: int
    scientific_acceptance_id: str = field(init=False)
    minimum_validation_outcome_id: str
    validation_policy_id: str
    validation_policy_version: str
    calculation_plan_id: str
    calculation_plan_revision: int
    attempt_id: str
    parse_result_id: str
    classification: MinimumValidationClassification
    reviewer_id: str
    review_evidence: Mapping[str, object]

    def __init__(self) -> None:
        raise TypeError("ScientificAcceptance is service-created")

    @classmethod
    def _from_outcome(
        cls,
        outcome: MinimumValidationOutcome,
        *,
        reviewer_id: str,
        review_evidence: Mapping[str, object],
    ) -> ScientificAcceptance:
        return cls._create(
            minimum_validation_outcome_id=outcome.minimum_validation_outcome_id,
            calculation_plan_id=outcome.calculation_plan_id,
            calculation_plan_revision=outcome.calculation_plan_revision,
            attempt_id=outcome.attempt_id,
            parse_result_id=outcome.parse_result_id,
            classification=outcome.classification,
            reviewer_id=reviewer_id,
            review_evidence=review_evidence,
        )

    @classmethod
    def _create(
        cls,
        *,
        minimum_validation_outcome_id: str,
        calculation_plan_id: str,
        calculation_plan_revision: int,
        attempt_id: str,
        parse_result_id: str,
        classification: MinimumValidationClassification,
        reviewer_id: str,
        review_evidence: Mapping[str, object],
        expected_id: str | None = None,
    ) -> ScientificAcceptance:
        value = object.__new__(cls)
        object.__setattr__(value, "schema_version", _SCHEMA_VERSION)
        object.__setattr__(value, "minimum_validation_outcome_id", _text(minimum_validation_outcome_id, "minimum_validation_outcome_id"))
        object.__setattr__(value, "validation_policy_id", _POLICY_ID)
        object.__setattr__(value, "validation_policy_version", _POLICY_VERSION)
        object.__setattr__(value, "calculation_plan_id", _text(calculation_plan_id, "calculation_plan_id"))
        object.__setattr__(value, "calculation_plan_revision", _positive_integer(calculation_plan_revision, "calculation_plan_revision"))
        object.__setattr__(value, "attempt_id", _text(attempt_id, "attempt_id"))
        object.__setattr__(value, "parse_result_id", _text(parse_result_id, "parse_result_id"))
        try:
            normalized_classification = MinimumValidationClassification(classification)
        except ValueError as exc:
            raise ScientificValidationError("classification is not frozen") from exc
        object.__setattr__(value, "classification", normalized_classification)
        object.__setattr__(value, "reviewer_id", _text(reviewer_id, "reviewer_id"))
        evidence = _freeze_mapping(review_evidence, "review_evidence")
        if not evidence:
            raise ScientificValidationError("review_evidence must not be empty")
        object.__setattr__(value, "review_evidence", evidence)
        identity = _identity("scientific-acceptance", value._authority_payload())
        if expected_id is not None and expected_id != identity:
            raise ScientificValidationPersistenceIntegrityError(
                "scientific acceptance identity does not close over its payload"
            )
        object.__setattr__(value, "scientific_acceptance_id", identity)
        return value

    def _authority_payload(self) -> Mapping[str, object]:
        return {
            "schema_version": self.schema_version,
            "minimum_validation_outcome_id": self.minimum_validation_outcome_id,
            "validation_policy_id": self.validation_policy_id,
            "validation_policy_version": self.validation_policy_version,
            "calculation_plan_id": self.calculation_plan_id,
            "calculation_plan_revision": self.calculation_plan_revision,
            "attempt_id": self.attempt_id,
            "parse_result_id": self.parse_result_id,
            "classification": self.classification.value,
            "reviewer_id": self.reviewer_id,
            "review_evidence": _plain(self.review_evidence),
        }

    def _payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "scientific_acceptance_id": self.scientific_acceptance_id,
            "minimum_validation_outcome_id": self.minimum_validation_outcome_id,
            "validation_policy_id": self.validation_policy_id,
            "validation_policy_version": self.validation_policy_version,
            "calculation_plan_id": self.calculation_plan_id,
            "calculation_plan_revision": self.calculation_plan_revision,
            "attempt_id": self.attempt_id,
            "parse_result_id": self.parse_result_id,
            "classification": self.classification.value,
            "reviewer_id": self.reviewer_id,
            "review_evidence": _plain(self.review_evidence),
        }

    @classmethod
    def _from_payload(cls, payload: Mapping[str, object]) -> ScientificAcceptance:
        expected = set(cls.__dataclass_fields__)
        if set(payload) != expected:
            raise ScientificValidationPersistenceIntegrityError(
                "scientific acceptance row has an invalid closed field set"
            )
        if (
            type(payload["schema_version"]) is not int
            or payload["schema_version"] != _SCHEMA_VERSION
            or payload["validation_policy_id"] != _POLICY_ID
            or payload["validation_policy_version"] != _POLICY_VERSION
        ):
            raise ScientificValidationPersistenceIntegrityError(
                "scientific acceptance policy or schema is not exact"
            )
        try:
            return cls._create(
                **{
                    key: payload[key]
                    for key in expected
                    if key
                    not in {
                        "schema_version",
                        "scientific_acceptance_id",
                        "validation_policy_id",
                        "validation_policy_version",
                    }
                },
                expected_id=payload["scientific_acceptance_id"],
            )  # type: ignore[arg-type]
        except ScientificValidationPersistenceIntegrityError:
            raise
        except (ScientificValidationError, TypeError, ValueError) as exc:
            raise ScientificValidationPersistenceIntegrityError(
                "scientific acceptance row is malformed"
            ) from exc


def _payload_text(record: MinimumValidationOutcome | ScientificAcceptance) -> str:
    return json.dumps(
        record._payload(),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


_SUPPORTED_RESULT_TUPLES: Final = {
    (
        "auto-g16-v3-gaussian-job",
        "1.0.0",
        "gaussian-job-facts",
    ),
    (
        "auto-g16-v3-gaussian-job",
        "1.1.0",
        "gaussian-job-facts",
    ),
}
_REASON_CLASSIFICATIONS: Final = {
    "incomplete-provenance": MinimumValidationClassification.INCOMPLETE,
    "incomplete-capture": MinimumValidationClassification.INCOMPLETE,
    "unsupported-result-tuple": MinimumValidationClassification.UNSUPPORTED,
    "unsupported-parse-status": MinimumValidationClassification.UNSUPPORTED,
    "incomplete-parse": MinimumValidationClassification.INCOMPLETE,
    "incomplete-error-termination": MinimumValidationClassification.INCOMPLETE,
    "incomplete-terminal-evidence": MinimumValidationClassification.INCOMPLETE,
    "incomplete-marker-pair": MinimumValidationClassification.INCOMPLETE,
    "incomplete-final-geometry": MinimumValidationClassification.INCOMPLETE,
    "unsupported-atom-cardinality": MinimumValidationClassification.UNSUPPORTED,
    "unsupported-dummy-center": MinimumValidationClassification.UNSUPPORTED,
    "incomplete-mode-count": MinimumValidationClassification.INCOMPLETE,
    "unsupported-mode-count": MinimumValidationClassification.UNSUPPORTED,
    "negative-frequency": MinimumValidationClassification.NOT_MINIMUM,
    "validated-minimum": MinimumValidationClassification.VALIDATED_MINIMUM,
}
_SOURCE_ARTIFACT_FIELDS: Final = {
    "envelope_observation_id",
    "artifact_kind",
    "logical_name",
    "sha256",
    "size_bytes",
}
_SOURCE_SPAN_FIELDS: Final = _SOURCE_ARTIFACT_FIELDS | {"start", "end"}


def _semantic_integrity(message: str) -> NoReturn:
    raise ScientificValidationPersistenceIntegrityError(message)


def _assert_source_span(
    span: object,
    source: Mapping[str, object],
    *,
    name: str,
) -> tuple[int, int]:
    if not isinstance(span, Mapping) or set(span) != _SOURCE_SPAN_FIELDS:
        _semantic_integrity(f"{name} does not bind the exact source artifact")
    if any(span[key] != value for key, value in source.items()):
        _semantic_integrity(f"{name} source authority is spliced")
    start = span["start"]
    end = span["end"]
    if (
        isinstance(start, bool)
        or not isinstance(start, int)
        or isinstance(end, bool)
        or not isinstance(end, int)
        or start < 0
        or end <= start
        or end > source["size_bytes"]
    ):
        _semantic_integrity(f"{name} has invalid source bounds")
    return start, end


def _assert_source_artifact(
    source: Mapping[str, object],
    *,
    envelope_observation_id: str,
) -> None:
    if set(source) != _SOURCE_ARTIFACT_FIELDS:
        _semantic_integrity("source artifact does not have its exact closed fields")
    if source["envelope_observation_id"] != envelope_observation_id:
        _semantic_integrity("source artifact names a different envelope")
    try:
        _text(source["envelope_observation_id"], "source envelope_observation_id")
        logical_name = _text(source["logical_name"], "source logical_name")
    except ScientificValidationError as exc:
        raise ScientificValidationPersistenceIntegrityError(
            "source artifact text fields are malformed"
        ) from exc
    if source["artifact_kind"] != "gaussian-log":
        _semantic_integrity("source artifact is not a Gaussian log")
    if logical_name in {".", ".."} or "/" in logical_name or "\\" in logical_name:
        _semantic_integrity("source logical name is not a portable leaf")
    digest = source["sha256"]
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        _semantic_integrity("source artifact SHA-256 is malformed")
    size = source["size_bytes"]
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        _semantic_integrity("source artifact size is malformed")


def _assert_minimum_validation_semantics(
    record: MinimumValidationOutcome,
) -> None:
    """Replay policy-v1 semantics that are closed by one persisted outcome."""

    expected_classification = _REASON_CLASSIFICATIONS.get(record.reason_code)
    if expected_classification is None or record.classification is not expected_classification:
        _semantic_integrity(
            "minimum validation classification and primary reason disagree"
        )

    parser_tuple = (record.parser_name, record.parser_version, record.result_kind)
    if record.reason_code == "unsupported-result-tuple":
        if parser_tuple in _SUPPORTED_RESULT_TUPLES:
            _semantic_integrity("unsupported tuple reason names the supported tuple")
    elif record.reason_code not in {"incomplete-provenance", "incomplete-capture"}:
        if parser_tuple not in _SUPPORTED_RESULT_TUPLES:
            _semantic_integrity("supported-policy reason names an unsupported tuple")

    absent_evidence = (
        record.source_artifact is None,
        record.job_section is None,
        record.accepted_optimization_span is None,
        record.accepted_stationary_span is None,
        record.selected_geometry_block is None,
        not record.selected_frequency_blocks,
        not record.selected_frequencies_cm1,
    )
    if record.reason_code in {
        "incomplete-provenance",
        "incomplete-capture",
        "unsupported-result-tuple",
        "unsupported-parse-status",
        "incomplete-parse",
    }:
        if not all(absent_evidence):
            _semantic_integrity("pre-fact outcome contains selected Result evidence")
        return

    source = record.source_artifact
    job_section = record.job_section
    if source is None or job_section is None:
        _semantic_integrity("attributed outcome is missing source authority")
    _assert_source_artifact(
        source,
        envelope_observation_id=record.envelope_observation_id,
    )
    job_start, job_end = _assert_source_span(
        job_section, source, name="job_section"
    )

    if record.reason_code in {
        "incomplete-error-termination",
        "incomplete-terminal-evidence",
        "incomplete-marker-pair",
    }:
        if not all(absent_evidence[2:]):
            _semantic_integrity("pre-pair outcome contains selected Result evidence")
        return

    optimization = record.accepted_optimization_span
    stationary = record.accepted_stationary_span
    if optimization is None or stationary is None:
        _semantic_integrity("post-pair outcome is missing accepted marker spans")
    opt_start, opt_end = _assert_source_span(
        optimization, source, name="accepted_optimization_span"
    )
    stat_start, stat_end = _assert_source_span(
        stationary, source, name="accepted_stationary_span"
    )
    if not (job_start <= opt_start < opt_end <= stat_start < stat_end <= job_end):
        _semantic_integrity("accepted marker pair is not ordered inside job section")

    if record.reason_code == "incomplete-final-geometry":
        if record.selected_geometry_block is not None or not all(absent_evidence[5:]):
            _semantic_integrity("missing-geometry outcome contains selected evidence")
        return

    geometry = record.selected_geometry_block
    if geometry is None:
        _semantic_integrity("classified outcome is missing selected geometry")
    if set(geometry) != {"orientation_kind", "units", "source_span", "atoms"}:
        _semantic_integrity("selected geometry does not have its exact closed fields")
    if geometry["orientation_kind"] not in {
        "input-orientation",
        "standard-orientation",
    } or geometry["units"] != "angstrom":
        _semantic_integrity("selected geometry kind or units are malformed")
    geometry_span = geometry.get("source_span")
    geometry_start, geometry_end = _assert_source_span(
        geometry_span, source, name="selected_geometry_block.source_span"
    )
    if not (job_start <= geometry_start < geometry_end <= opt_start):
        _semantic_integrity("selected geometry is outside its frozen source boundary")
    atoms = geometry.get("atoms")
    if not isinstance(atoms, tuple) or not atoms:
        _semantic_integrity("selected geometry atoms are not an immutable sequence")
    for index, atom in enumerate(atoms, start=1):
        if not isinstance(atom, Mapping) or set(atom) != {
            "center",
            "atomic_number",
            "x",
            "y",
            "z",
        }:
            _semantic_integrity("selected geometry atom has invalid closed fields")
        center = atom["center"]
        atomic_number = atom["atomic_number"]
        if (
            isinstance(center, bool)
            or not isinstance(center, int)
            or center != index
            or isinstance(atomic_number, bool)
            or not isinstance(atomic_number, int)
            or not 0 <= atomic_number <= 118
        ):
            _semantic_integrity("selected geometry center or atomic number is invalid")
        if any(
            type(atom[coordinate]) is not float
            or not isfinite(atom[coordinate])  # type: ignore[arg-type]
            for coordinate in ("x", "y", "z")
        ):
            _semantic_integrity("selected geometry coordinates are malformed")

    frequencies: list[float] = []
    prior_end = stat_end
    for index, block in enumerate(record.selected_frequency_blocks):
        if set(block) != {"source_span", "frequencies_cm-1"}:
            _semantic_integrity("selected frequency block has invalid closed fields")
        span = block.get("source_span")
        start, end = _assert_source_span(
            span, source, name=f"selected_frequency_blocks[{index}].source_span"
        )
        if start < prior_end or end > job_end:
            _semantic_integrity("selected frequency suffix is not ordered after stationary evidence")
        prior_end = end
        values = block.get("frequencies_cm-1")
        if not isinstance(values, tuple) or not 1 <= len(values) <= 3 or any(
            type(item) is not float or not isfinite(item) for item in values
        ):
            _semantic_integrity("selected frequency block values are malformed")
        frequencies.extend(values)
    if tuple(frequencies) != record.selected_frequencies_cm1:
        _semantic_integrity(
            "selected frequency projection contradicts selected frequency blocks"
        )

    atom_count = len(atoms)
    if atom_count < 3:
        expected = (
            MinimumValidationClassification.UNSUPPORTED,
            "unsupported-atom-cardinality",
        )
    elif any(atom["atomic_number"] == 0 for atom in atoms):  # type: ignore[index]
        expected = (
            MinimumValidationClassification.UNSUPPORTED,
            "unsupported-dummy-center",
        )
    else:
        expected_modes = 3 * atom_count - 6
        if len(frequencies) < expected_modes:
            expected = (
                MinimumValidationClassification.INCOMPLETE,
                "incomplete-mode-count",
            )
        elif len(frequencies) > expected_modes:
            expected = (
                MinimumValidationClassification.UNSUPPORTED,
                "unsupported-mode-count",
            )
        elif any(item < 0.0 for item in frequencies):
            expected = (
                MinimumValidationClassification.NOT_MINIMUM,
                "negative-frequency",
            )
        else:
            expected = (
                MinimumValidationClassification.VALIDATED_MINIMUM,
                "validated-minimum",
            )
    if (record.classification, record.reason_code) != expected:
        _semantic_integrity(
            "minimum validation outcome contradicts frozen first-applicable policy"
        )
