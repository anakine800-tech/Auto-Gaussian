"""Private, read-only Gaussian source projection from original receipt owners."""
from contextlib import contextmanager

from auto_g16.core import SQLiteRuntimeStore
from auto_g16.transport._canonical import TransportBoundaryError
from ._identity import semantic_sha256
from .program import ProgramExecutionSnapshot
from ._receipt_source import _source_qualification
from .program_runtime import _read_program_receipt_success_authority
from . import _program_completion as completion
from .models import RECEIPT_OBSERVATION_TYPE


def reject_legacy_generation(store, attempt_id):
    if any(item.observation_type == RECEIPT_OBSERVATION_TYPE
           or item.observation_type.startswith("v30-result-")
           for item in store.observations_for_attempt(attempt_id)) or any(
               item.result_type.startswith("v30-result-") for item in store.results_for_attempt(attempt_id)):
        raise TransportBoundaryError("mixed V30/successor execution or Result generation")


@contextmanager
def gaussian_result_source(store, *, snapshot, transport_store, validation_driver=None):
    if type(store) is not SQLiteRuntimeStore or type(snapshot) is not ProgramExecutionSnapshot:
        raise TransportBoundaryError("Gaussian source requires exact native owners")
    spec = snapshot.program_execution_spec
    if (spec.program_kind, spec.adapter_id, spec.adapter_contract_version) not in {
        ("gaussian", "auto-g16-v31-gaussian", version) for version in (3, 4, 5, 6)
    } or spec.program_data["stage"] != "opt":
        raise TransportBoundaryError("Gaussian source requires a supported pure Opt adapter")
    with _source_qualification(store, snapshot, transport_store, validation_driver) as (source, _qualification):
        reject_legacy_generation(source, snapshot.attempt_id)
        proof, capture = _read_program_receipt_success_authority(
            store, snapshot=snapshot, program_transport_store=transport_store, driver=validation_driver,
        )
        records = [item for item in source.results_for_attempt(snapshot.attempt_id)
                   if item.result_id == proof["evidence_result_id"]]
        if len(records) != 1:
            raise TransportBoundaryError("Gaussian completion source is not unique")
        record = records[0]
        inputs = record.data["inputs"]
        logs = [item for item in record.data["captured_files"] if item["portable_name"] == "gaussian.log"]
        if len(inputs) != 1 or len(logs) != 1 or logs[0]["presence"] != "present":
            raise TransportBoundaryError("Gaussian source input/log inventory differs")
        inp, log = inputs[0], logs[0]
        fields = ("logical_role", "portable_name", "format", "sha256", "size_bytes")
        payload = {
            "schema": "v31-gaussian-result-source/1", "attempt_id": snapshot.attempt_id,
            "calculation_plan_id": snapshot.calculation_plan_id,
            "calculation_plan_revision": snapshot.calculation_plan_revision,
            "program_execution_snapshot_id": snapshot.program_execution_snapshot_id,
            "snapshot_payload_sha256": semantic_sha256(snapshot.semantic_payload()),
            "effect_intent_id": snapshot.effect_intent_id,
            "program_execution_spec_id": spec.program_execution_spec_id,
            "spec_payload_sha256": semantic_sha256(spec.semantic_payload()),
            "terminal_success_authority_id": proof["program_terminal_success_authority_id"],
            "completion_result_id": record.result_id,
            "completion_result_payload_sha256": semantic_sha256(record.data),
            "capture_authority_id": capture.capture_authority_id,
            "assessment_observation_id": proof["assessment_observation_id"],
            "receipt_sha256": proof["receipt_sha256"], "epoch_id": proof["epoch_id"],
            "input": {**{key: inp[key] for key in fields}, "stage_observation_id": inp["stage_observation_id"]},
            "log": {**{key: log[key] for key in fields}, "fetch_observation_id": log["fetch_observation_id"]},
        }
        input_bytes = completion._unbase64(inp["content_base64"], 64 * 1024 * 1024)
        log_bytes = completion._unbase64(log["content_base64"], 64 * 1024 * 1024)
        yield source, payload, input_bytes, log_bytes
