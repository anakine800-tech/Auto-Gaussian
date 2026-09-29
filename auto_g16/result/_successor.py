"""Private deterministic Gaussian successor records; no execution dependencies."""
from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
import json

from auto_g16.core import Observation, Result
from .gaussian_job import GaussianJobParser, _NativeGaussianJobParser
from .models import (
    NS_INPUT_BINDING, NS_PARSED_RESULT, _identity,
    OutputArtifact, OutputEnvelope, CaptureStatus, CaptureCompleteness,
    ProvenanceConflictError,
)

SOURCE = "v31-gaussian-result-source/1"
PARSED = "v31-gaussian-parsed-result/1"
_SOURCE_KEYS = {
    "schema", "attempt_id", "calculation_plan_id", "calculation_plan_revision",
    "program_execution_snapshot_id", "snapshot_payload_sha256", "effect_intent_id",
    "program_execution_spec_id", "spec_payload_sha256", "terminal_success_authority_id",
    "completion_result_id", "completion_result_payload_sha256", "capture_authority_id",
    "assessment_observation_id", "receipt_sha256", "epoch_id", "input", "log",
}
_DESCRIPTOR_KEYS = {"logical_role", "portable_name", "format", "sha256", "size_bytes"}


def _plain(value):
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    return value


def payload_hash(value):
    return sha256(json.dumps(_plain(value), sort_keys=True, ensure_ascii=False,
                            allow_nan=False, separators=(",", ":")).encode()).hexdigest()


def _require(condition, message):
    if not condition:
        raise ProvenanceConflictError(message)


def parse_source(payload, log_bytes, *, parser_version="1.1.0"):
    """Reconstruct records from owning proof, never from a stored facts claim."""
    _require(isinstance(payload, Mapping) and set(payload) == _SOURCE_KEYS,
             "successor source fields are not closed")
    _require(payload["schema"] == SOURCE, "successor source schema differs")
    for field, identity in (("input", "stage_observation_id"), ("log", "fetch_observation_id")):
        descriptor = payload[field]
        _require(isinstance(descriptor, Mapping) and set(descriptor) == _DESCRIPTOR_KEYS | {identity},
                 "successor artifact fields are not closed")
        _require(isinstance(descriptor[identity], str) and bool(descriptor[identity]), "artifact observation missing")
        _require(type(descriptor["size_bytes"]) is int and descriptor["size_bytes"] > 0,
                 "artifact size must be positive")
    _require(payload["input"]["logical_role"] == "gaussian-input" and payload["input"]["format"] == "gaussian-gjf",
             "source input is not Gaussian")
    log = payload["log"]
    _require(log["format"] == "text" and log["logical_role"] == "program-log" and log["portable_name"] == "gaussian.log",
             "source log declaration differs")
    _require(type(log_bytes) is bytes and len(log_bytes) == log["size_bytes"]
             and sha256(log_bytes).hexdigest() == log["sha256"], "source log bytes differ")
    source_id = _identity(NS_INPUT_BINDING, ("v31-gaussian-result-source", payload_hash(payload)))
    source = Observation(observation_id=source_id, attempt_id=payload["attempt_id"], observation_type=SOURCE, data=payload)
    # This carrier is never persisted and carries no V30 provenance authority.
    envelope = OutputEnvelope(
        attempt_id=source.attempt_id, input_binding_observation_id=source_id,
        execution_snapshot_id=payload["program_execution_snapshot_id"],
        capture_source_id=source_id, capture_sequence=1, capture_status=CaptureStatus.CAPTURED,
        capture_completeness=CaptureCompleteness.COMPLETE,
        artifacts=(OutputArtifact(artifact_kind="gaussian-log", logical_name=log["portable_name"],
                                  sha256=log["sha256"], size_bytes=log["size_bytes"]),),
        capture_manifest_sha256=payload_hash(payload), captured_at_utc="1970-01-01T00:00:00Z",
    )
    _require(type(parser_version) is str and parser_version in {"1.1.0", "1.2.0"}, "unsupported successor parser version")
    parser = {"1.1.0": GaussianJobParser, "1.2.0": _NativeGaussianJobParser}[parser_version]()
    parsed = parser.parse(envelope, {log["portable_name"]: log_bytes})
    data = {"schema": PARSED, "attempt_id": source.attempt_id,
            "source_observation_id": source_id, "source_payload_sha256": payload_hash(source.data),
            **{key: parsed.payload()[key] for key in ("parser_name", "parser_version", "result_kind",
                                                     "parse_status", "facts", "diagnostics")}}
    result = Result(result_id=_identity(NS_PARSED_RESULT, ("v31-gaussian-parsed-result", payload_hash(data))),
                    attempt_id=source.attempt_id, result_type=PARSED, data=data)
    return source, result, envelope, parsed


def require_pair(store, source, result, *, allow_partial=False):
    observations = store.observations_for_attempt(source.attempt_id)
    results = store.results_for_attempt(source.attempt_id)
    _require(not any((item.observation_type.startswith("v30-result-") or item.observation_type == "v3.remote-effect-receipt") for item in observations)
             and not any(item.result_type.startswith("v30-result-") for item in results),
             "mixed V30/successor Result generation")
    sources = tuple(item for item in observations if item.observation_type == SOURCE)
    parsed = tuple(item for item in results if item.result_type == PARSED)
    _require(sources in ((), (source,)) and parsed in ((), (result,)),
             "stored successor source or parsed facts conflict with original-byte replay")
    _require(not parsed or sources, "orphan successor Result")
    if not allow_partial:
        _require(sources == (source,) and parsed == (result,), "successor pair is incomplete")
    return bool(sources), bool(parsed)


def append_pair(store, source, result):
    """Explicit append after the composition owner closes destination and source."""
    have_source, have_result = require_pair(store, source, result, allow_partial=True)
    if not have_source:
        store.append_observation(source)
    if not have_result:
        store.append_result(result)
    require_pair(store, source, result)
    return source, result


def project_opt_facts(payload, result, parsed):
    """Pure fact projection; the composition owner must replay source and pair."""
    facts = parsed.facts
    return _plain({
        'source': 'Result:' + result.result_id,
        'provenance': {'source_observation_id': result.data['source_observation_id'],
            'source_payload_sha256': result.data['source_payload_sha256'],
            'parsed_result_id': result.result_id, 'parsed_payload_sha256': payload_hash(result.data),
            'parser_name': parsed.parser_name, 'parser_version': parsed.parser_version,
            'input': payload['input'], 'log': payload['log']},
        'energy': facts['final_energy_hartree'], 'geometry': facts['geometry_blocks'],
        'frequencies': facts['frequency_blocks'],
        'optimization': {'completed_marker': facts['optimization_completed_marker'],
                         'stationary_point_marker': facts['stationary_point_marker'],
                         'optimization_evidence': facts['optimization_completed_evidence'],
                         'stationary_point_evidence': facts['stationary_point_evidence'],
                         'termination_evidence': facts['termination_evidence'],
                         'scope': 'Opt geometry only; frequency validation pending'},
    })
