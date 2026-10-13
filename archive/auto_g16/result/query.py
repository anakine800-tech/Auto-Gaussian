"""Read-only JSON projection of persisted, attributed Gaussian Result facts.

The caller owns coherent snapshot acquisition and physical source qualification.
This module never opens a store, reads log bytes, or grants execution authority.
"""

from __future__ import annotations

from hashlib import sha256
import re
from typing import Protocol

from auto_g16.core import Attempt, CalculationPlan, Observation, RecordNotFoundError, Result

from .models import (
    INPUT_BINDING_OBSERVATION, OUTPUT_ENVELOPE_OBSERVATION, PARSED_RESULT_TYPE,
    CaptureCompleteness, InputBinding, ParseStatus, ResultBoundaryError,
)
from .service import ResultProvenanceService


_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_COMPLETION = "program-completion-evidence/1"
_SUCCESSOR_OBSERVATIONS = frozenset({
    "v31-program-effect-receipt/1", "program-completion-assessment/1",
    "auto-g16-v31-collection-start/1",
})
_KNOWN_TYPES = {
    "result": frozenset({PARSED_RESULT_TYPE, _COMPLETION}),
    "observation": frozenset({
        INPUT_BINDING_OBSERVATION, OUTPUT_ENVELOPE_OBSERVATION,
        *_SUCCESSOR_OBSERVATIONS,
        # Inventory labels only; no payload decoding or imported authority.
        "auto-g16-v3-attempt-observation", "v3.remote-effect-receipt",
    }),
}
_GRAMMARS = {
    ("auto-g16-v3-gaussian-job", "1.0.0", "gaussian-job-facts"):
        "auto-g16-v3-gaussian-job-grammar/1",
    ("auto-g16-v3-gaussian-job", "1.1.0", "gaussian-job-facts"):
        "auto-g16-v3-gaussian-job-grammar/2",
}


class ResultReadStore(Protocol):
    """Caller-owned coherent read view; opening and snapshot lifetime are external."""

    def load_attempt(self, attempt_id: str) -> Attempt: ...
    def load_calculation_plan(self, calculation_plan_id: str) -> CalculationPlan: ...
    def observations_for_attempt(self, attempt_id: str) -> tuple[Observation, ...]: ...
    def results_for_attempt(self, attempt_id: str) -> tuple[Result, ...]: ...


class _ProjectionConflict(Exception):
    pass


def _identifier(value: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise _ProjectionConflict("unsafe-identifier")
    return value


class _ReadView:
    """Materialize each public history once; this is not a database transaction."""

    def __init__(self, reader: ResultReadStore, attempt: Attempt):
        self.attempt = attempt
        self.observations = tuple(reader.observations_for_attempt(attempt.attempt_id))
        self.results = tuple(reader.results_for_attempt(attempt.attempt_id))
        self.plans: dict[str, CalculationPlan] = {}
        for records, key in ((self.observations, "observation_id"), (self.results, "result_id")):
            ids = [getattr(record, key) for record in records]
            if len(ids) != len(set(ids)):
                raise _ProjectionConflict("duplicate-record-identity")
            for record in records:
                _identifier(getattr(record, key))
                if record.attempt_id != attempt.attempt_id:
                    raise _ProjectionConflict("cross-attempt-record")
        for record in self.observations:
            if record.observation_type == INPUT_BINDING_OBSERVATION:
                try:
                    binding = InputBinding.from_payload(record.data)
                except (ValueError, TypeError, KeyError) as exc:
                    raise _ProjectionConflict("provenance-conflict") from exc
                plan_id = binding.calculation_plan_id
                if plan_id not in self.plans:
                    plan = reader.load_calculation_plan(plan_id)
                    if plan.calculation_plan_id != plan_id:
                        raise _ProjectionConflict("plan-identity-conflict")
                    self.plans[plan_id] = plan

    def load_attempt(self, attempt_id):
        if attempt_id != self.attempt.attempt_id:
            raise _ProjectionConflict("cross-attempt-record")
        return self.attempt

    def load_calculation_plan(self, calculation_plan_id):
        return self.plans[calculation_plan_id]

    def observations_for_attempt(self, attempt_id):
        self.load_attempt(attempt_id)
        return self.observations

    def results_for_attempt(self, attempt_id):
        self.load_attempt(attempt_id)
        return self.results


def _inventory(view):
    return [
        {"record_kind": kind, "record_id": _identifier(getattr(record, id_key)),
         "source_type": record_type if record_type in _KNOWN_TYPES[kind] else "unknown",
         "source_type_sha256": sha256(record_type.encode("utf-8")).hexdigest()}
        for kind, records, id_key, type_key in (
            ("observation", view.observations, "observation_id", "observation_type"),
            ("result", view.results, "result_id", "result_type"),
        )
        for record in records
        for record_type in (getattr(record, type_key),)
    ]


def _parser(outcome):
    key = (outcome.parser_name, outcome.parser_version, outcome.result_kind)
    # Legacy parser names/versions are unconstrained historical text; do not echo.
    return {"qualification": "attributed" if key in _GRAMMARS else "legacy",
            "name": key[0] if key in _GRAMMARS else None,
            "version": key[1] if key in _GRAMMARS else None,
            "kind": outcome.result_kind, "grammar_id": _GRAMMARS.get(key),
            "parse_status": outcome.parse_status.value}


def _source(view, selected, outcome):
    binding = view.input_binding
    if binding is None:
        return None
    return {
        "protocol": PARSED_RESULT_TYPE,
        "input_binding_id": _identifier(binding.observation_id),
        "prepared_input_binding_id": _identifier(binding.prepared_input_binding_id),
        "calculation_plan_id": _identifier(binding.calculation_plan_id),
        "calculation_plan_revision": binding.calculation_plan_revision,
        "execution_snapshot_id": _identifier(binding.execution_snapshot_id),
        "input": {"sha256": binding.sha256, "size_bytes": binding.size_bytes},
        "envelope_id": _identifier(selected.observation_id) if selected else None,
        "capture_source_id": _identifier(selected.capture_source_id) if selected else None,
        "capture_manifest_sha256": selected.capture_manifest_sha256 if selected else None,
        "capture_completeness": selected.capture_completeness.value if selected else None,
        "capture_status": selected.capture_status.value if selected else None,
        "outputs": [{"artifact_kind": item.artifact_kind, "sha256": item.sha256,
                     "size_bytes": item.size_bytes} for item in selected.artifacts] if selected else [],
        "result_id": _identifier(outcome.result_id) if outcome else None,
        "parser": _parser(outcome) if outcome else None,
    }


def _summary(facts):
    has_frequency = facts["frequency_count"] > 0
    return {
        "termination": {"status": facts["program_status"],
                        "normal_count": facts["normal_termination_count"],
                        "error_count": facts["error_termination_count"]},
        "final_energy_hartree": facts["final_energy_hartree"],
        "optimization": {"completed_marker": facts["optimization_completed_marker"],
                         "stationary_point_marker": facts["stationary_point_marker"]},
        "frequency": {"availability": "available" if has_frequency else "missing",
                      "count": facts["frequency_count"] if has_frequency else None,
                      "imaginary_count": facts["imaginary_frequency_count"] if has_frequency else None},
    }


class GaussianResultQuery:
    """Project one stored chain, never collect, parse, repair, or accept science.

    The caller must keep one coherent read snapshot for the entire call. Passing
    a writable Store does not qualify its opening or prove physical read safety.
    Optional digests compare caller expectations to declarations, not raw bytes.
    """

    def __init__(self, reader: ResultReadStore):
        self._reader = reader

    def get_summary(self, attempt_id: str, *, expected_input_sha256: str | None = None,
                    expected_log_sha256: str | None = None) -> dict[str, object]:
        dto = {"schema": "gaussian-result-summary/1", "attempt_id": None,
               "availability": "missing", "reasons": [], "source": None,
               "summary": None, "record_inventory": [], "history": []}
        try:
            dto["attempt_id"] = _identifier(attempt_id)
            for pin in (expected_input_sha256, expected_log_sha256):
                if pin is not None and (not isinstance(pin, str) or _SHA.fullmatch(pin) is None):
                    raise _ProjectionConflict("invalid-digest-pin")
            try:
                attempt = self._reader.load_attempt(attempt_id)
            except RecordNotFoundError:
                dto["reasons"] = ["attempt-not-found"]
                return dto
            if attempt.attempt_id != attempt_id:
                raise _ProjectionConflict("cross-attempt-record")
            frozen = _ReadView(self._reader, attempt)
            # Only pure in-memory decoding is normalized here. Operational
            # exceptions from the caller-owned reader remain visible to its owner.
            try:
                dto["record_inventory"] = _inventory(frozen)
                view = ResultProvenanceService(frozen).current_view(attempt_id)
            except (ValueError, TypeError, KeyError) as exc:
                raise _ProjectionConflict("provenance-conflict") from exc
            successor = any(item.result_type == _COMPLETION for item in frozen.results) or any(
                item.observation_type in _SUCCESSOR_OBSERVATIONS for item in frozen.observations)
            if successor:
                if view.input_binding or view.envelopes or view.results:
                    raise _ProjectionConflict("mixed-execution-generations")
                dto.update(availability="unsupported", reasons=["v31-gaussian-source-not-qualified"])
                return dto
            if view.input_binding and view.input_binding.input_format not in {"gaussian-gjf", "gaussian-input"}:
                dto.update(availability="unsupported", reasons=["unsupported-input-format"])
                return dto
            selected = next((item for item in view.envelopes
                             if item.observation_id == view.selected_envelope_id), None)
            outcome = view.selected_results[-1] if view.selected_results else None
            dto["history"] = [
                {"envelope_id": _identifier(item.observation_id),
                 "capture_source_id": _identifier(item.capture_source_id),
                 "capture_sequence": item.capture_sequence,
                 "capture_completeness": item.capture_completeness.value,
                 "selected": item.observation_id == view.selected_envelope_id,
                 "results": [{"result_id": _identifier(result.result_id), "parser": _parser(result)}
                             for result in view.results if result.envelope_observation_id == item.observation_id]}
                for item in view.envelopes]
            source = _source(view, selected, outcome)
            if source and expected_input_sha256 is not None and source["input"]["sha256"] != expected_input_sha256:
                raise _ProjectionConflict("input-digest-mismatch")
            logs = [item for item in selected.artifacts if item.artifact_kind == "gaussian-log"] if selected else []
            if len(logs) == 1 and expected_log_sha256 is not None and logs[0].sha256 != expected_log_sha256:
                raise _ProjectionConflict("output-digest-mismatch")
            dto["source"] = source
            if any(item["source_type"] == "unknown" for item in dto["record_inventory"]):
                dto.update(availability="unsupported", reasons=["unsupported-records-present"])
            elif selected is None:
                dto["reasons"] = [view.state.value]
            elif selected.capture_completeness is CaptureCompleteness.PARTIAL:
                dto.update(availability="partial", reasons=["capture-partial"])
            elif outcome is None:
                dto["reasons"] = ["awaiting-parse"]
            elif _parser(outcome)["qualification"] != "attributed":
                dto.update(availability="unsupported", reasons=["legacy-parser-not-qualified"])
            elif outcome.parse_status is ParseStatus.PARSED:
                dto.update(availability="available", summary=_summary(outcome.facts))
                if not outcome.facts["frequency_count"]:
                    dto["reasons"].append("frequency-missing")
                if outcome.facts["final_energy_hartree"] is None:
                    dto["reasons"].append("energy-missing")
            else:
                dto.update(availability="partial" if outcome.parse_status is ParseStatus.PARTIAL else "unsupported",
                           reasons=["parse-" + outcome.parse_status.value])
            return dto
        except (ResultBoundaryError, RecordNotFoundError, _ProjectionConflict) as exc:
            reason = str(exc) if isinstance(exc, _ProjectionConflict) else "provenance-conflict"
            dto.update(availability="conflict", reasons=[reason], source=None, summary=None, history=[])
            return dto
