"""Private Core-owned runtime composition for successor xTB/CREST effects."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256

from auto_g16.core import (
    AttemptState,
    Observation,
    ReconciliationResolution,
    RuntimeStoreError,
    SQLiteRuntimeStore,
    SubmissionIntentClaim,
    SubmissionOutcome,
)
from auto_g16.transport import program as _transport
from auto_g16.transport._canonical import TransportBoundaryError, canonical_bytes

from .program import ProgramExecutionSnapshot


_RECEIPT_FIELDS = {
    "schema", "protocol", "attempt_id", "program_execution_snapshot_id",
    "effect_intent_id", "effect_sequence", "operation", "request_sha256",
    "request", "outcome", "response",
}


def _snapshot_binding(
    snapshot: ProgramExecutionSnapshot,
    program_transport_store: _transport._ProgramTransportStore,
    driver: _transport._ProgramEffectDriver,
) -> dict[str, object]:
    if type(snapshot) is not ProgramExecutionSnapshot:
        raise TransportBoundaryError("successor composition requires exact ProgramExecutionSnapshot")
    if type(program_transport_store) is not _transport._ProgramTransportStore:
        raise TransportBoundaryError(
            "successor composition requires exact _ProgramTransportStore"
        )
    program_transport_store._attest()
    closed_driver = _transport._require_driver(driver)
    try:
        snapshot.assert_identity_closed()
    except Exception as exc:
        raise TransportBoundaryError("successor snapshot authority is not closed") from exc
    cwd = _transport._exact_keys(
        snapshot.cwd_binding, {"location_kind", "path"}, "successor cwd binding"
    )
    remote_workspace = snapshot.workspace_binding.remote_attempt_dir
    if cwd["location_kind"] != "server" or cwd["path"] != remote_workspace:
        raise TransportBoundaryError("successor cwd differs from its exact workspace")
    runtime_attestation_id = program_transport_store.attest_runtime(
        program_execution_snapshot_id=snapshot.program_execution_snapshot_id,
        resolved_server_profile_id=(
            snapshot.resolved_server_profile.resolved_server_profile_id
        ),
        qualification=closed_driver.runtime_qualification,
    )
    binding = {
        "program_transport_store_id": (
            program_transport_store.program_transport_store_id
        ),
        "store_instance_id": program_transport_store.store_instance_id,
        "runtime_attestation_id": runtime_attestation_id,
        "attempt_id": snapshot.attempt_id,
        "program_execution_snapshot_id": snapshot.program_execution_snapshot_id,
        "effect_intent_id": snapshot.effect_intent_id,
        "program_execution_spec_id": snapshot.program_execution_spec_id,
        "project_physical_binding_id": snapshot.project_physical_binding_id,
        "workspace_binding_id": snapshot.workspace_binding.workspace_binding_id,
        "resolved_server_profile_id": snapshot.resolved_server_profile.resolved_server_profile_id,
        "remote_workspace": remote_workspace,
    }
    _transport._validate_binding(binding)
    return binding


def _stage_material(
    snapshot: ProgramExecutionSnapshot,
    *,
    input_bytes: Mapping[str, bytes],
    scheduler_artifact_bytes: Mapping[str, bytes],
) -> tuple[tuple[dict[str, object], bytes], ...]:
    if not isinstance(input_bytes, Mapping) or not isinstance(scheduler_artifact_bytes, Mapping):
        raise TransportBoundaryError("successor stage bytes must be exact mappings")
    inputs = snapshot.program_execution_spec.exact_inputs
    schedulers = snapshot.scheduler_artifacts
    input_names = tuple(str(item["portable_name"]) for item in inputs)
    scheduler_names = tuple(str(item["portable_name"]) for item in schedulers)
    if set(input_bytes) != set(input_names) or len(input_bytes) != len(input_names):
        raise TransportBoundaryError("program input bytes differ from exact declarations")
    if set(scheduler_artifact_bytes) != set(scheduler_names) or len(scheduler_artifact_bytes) != len(scheduler_names):
        raise TransportBoundaryError("scheduler bytes differ from exact declarations")
    material: list[tuple[dict[str, object], bytes]] = []
    for declaration in inputs:
        name = _transport._portable(declaration["portable_name"], "program input name")
        content = input_bytes[name]
        if type(content) is not bytes or len(content) != declaration["size_bytes"] or sha256(content).hexdigest() != declaration["sha256"]:
            raise TransportBoundaryError("program input bytes differ from exact declaration")
        material.append(({
            "artifact_kind": "program-input",
            "logical_role": declaration["logical_role"],
            "portable_name": name,
            "format": declaration["format"],
            "sha256": declaration["sha256"],
            "size_bytes": declaration["size_bytes"],
        }, content))
    for declaration in schedulers:
        name = _transport._portable(declaration["portable_name"], "scheduler artifact name")
        content = scheduler_artifact_bytes[name]
        expected = str(declaration["content_utf8"]).encode("utf-8")
        if type(content) is not bytes or content != expected or len(content) != declaration["size_bytes"] or sha256(content).hexdigest() != declaration["sha256"]:
            raise TransportBoundaryError("scheduler bytes differ from exact snapshot artifact")
        material.append(({
            "artifact_kind": "scheduler-script",
            "logical_role": declaration["logical_role"],
            "portable_name": name,
            "format": declaration["format"],
            "sha256": declaration["sha256"],
            "size_bytes": declaration["size_bytes"],
        }, content))
    return tuple(material)


def _receipt_payload(
    snapshot: ProgramExecutionSnapshot, *, sequence: int, operation: str,
    request: Mapping[str, object], outcome: str, response: Mapping[str, object],
) -> dict[str, object]:
    _transport._positive(sequence, "effect_sequence")
    if operation not in _transport._OPERATIONS or outcome not in {"SUCCEEDED", "FAILED", "UNKNOWN"}:
        raise TransportBoundaryError("successor receipt vocabulary is invalid")
    payload = {
        "schema": _transport._RECEIPT_TYPE,
        "protocol": _transport._PROTOCOL,
        "attempt_id": snapshot.attempt_id,
        "program_execution_snapshot_id": snapshot.program_execution_snapshot_id,
        "effect_intent_id": snapshot.effect_intent_id,
        "effect_sequence": sequence,
        "operation": operation,
        "request_sha256": _transport._digest(request),
        "request": dict(request),
        "outcome": outcome,
        "response": dict(response),
    }
    canonical_bytes(payload)
    return payload


def _load_receipts(
    store: SQLiteRuntimeStore,
    snapshot: ProgramExecutionSnapshot,
    program_transport_store: _transport._ProgramTransportStore | None = None,
    current_binding: Mapping[str, object] | None = None,
) -> tuple[Observation, ...]:
    records = tuple(
        item for item in store.observations_for_attempt(snapshot.attempt_id)
        if item.observation_type == _transport._RECEIPT_TYPE
    )
    prior_receipts: list[Observation] = []
    for expected_sequence, record in enumerate(records, 1):
        payload = _transport._exact_keys(record.data, _RECEIPT_FIELDS, "successor receipt")
        if (
            payload["schema"] != _transport._RECEIPT_TYPE
            or payload["protocol"] != _transport._PROTOCOL
            or payload["attempt_id"] != snapshot.attempt_id
            or payload["program_execution_snapshot_id"] != snapshot.program_execution_snapshot_id
            or payload["effect_intent_id"] != snapshot.effect_intent_id
            or payload["effect_sequence"] != expected_sequence
            or payload["operation"] not in _transport._OPERATIONS
            or payload["outcome"] not in {"SUCCEEDED", "FAILED", "UNKNOWN"}
            or not isinstance(payload["request"], Mapping)
            or not isinstance(payload["response"], Mapping)
            or payload["request_sha256"] != _transport._digest(payload["request"])
            or record.observation_id != _transport._identity("effect-receipt", dict(payload))
        ):
            raise TransportBoundaryError("persisted successor receipt is malformed")
        if program_transport_store is not None or current_binding is not None:
            if (
                type(program_transport_store) is not _transport._ProgramTransportStore
                or current_binding is None
                or not isinstance(payload["request"], Mapping)
            ):
                raise TransportBoundaryError(
                    "dual-source successor receipt closure is incomplete"
                )
            expected_request = _reconstruct_expected_request(
                store,
                snapshot,
                program_transport_store,
                current_binding,
                payload,
                tuple(prior_receipts),
            )
            if dict(payload["request"]) != expected_request:
                raise TransportBoundaryError(
                    "persisted successor request does not re-close to predecessor authority"
                )
            _transport._validate_program_effect_request(
                payload["request"], expected_request["binding"]
            )
            _reclose_receipt_response(snapshot, payload, expected_request)
            job_id = _receipt_job_id(payload)
            program_transport_store.require_matching_effect(
                binding=expected_request["binding"],
                request=payload["request"],
                classification=str(payload["outcome"]),
                response=payload["response"],
                job_id=job_id,
            )
        else:
            _reclose_receipt_response(snapshot, payload, payload["request"])
        prior_receipts.append(record)
    return records


def _receipt_job_id(payload: Mapping[str, object]) -> str | None:
    if (
        payload.get("outcome") == "SUCCEEDED"
        and payload.get("operation")
        in {"SUBMIT_QSUB_ONCE", "RECONCILE_SUBMISSION"}
        and isinstance(payload.get("response"), Mapping)
    ):
        response = payload["response"]
        assert isinstance(response, Mapping)
        if "job_id" in response:
            return _transport._job_id(response["job_id"])
    return None


def _declared_stage_payload(
    snapshot: ProgramExecutionSnapshot,
    candidate: Mapping[str, object],
) -> dict[str, object]:
    declared = tuple(
        {
            "artifact_kind": "program-input",
            "logical_role": item["logical_role"],
            "portable_name": item["portable_name"],
            "format": item["format"],
            "sha256": item["sha256"],
            "size_bytes": item["size_bytes"],
        }
        for item in snapshot.program_execution_spec.exact_inputs
    ) + tuple(
        {
            "artifact_kind": "scheduler-script",
            "logical_role": item["logical_role"],
            "portable_name": item["portable_name"],
            "format": item["format"],
            "sha256": item["sha256"],
            "size_bytes": item["size_bytes"],
        }
        for item in snapshot.scheduler_artifacts
    )
    matched = tuple(item for item in declared if item == dict(candidate))
    if len(matched) != 1:
        raise TransportBoundaryError(
            "persisted staged artifact is not uniquely snapshot-declared"
        )
    return matched[0]


def _declared_output(
    snapshot: ProgramExecutionSnapshot,
    candidate: Mapping[str, object],
) -> Mapping[str, object]:
    declarations = (
        *snapshot.program_execution_spec.required_outputs,
        *snapshot.program_execution_spec.optional_outputs,
    )
    matched = tuple(
        item
        for item in declarations
        if all(
            candidate.get(key) == item[key]
            for key in ("logical_role", "portable_name", "format")
        )
    )
    if len(matched) != 1:
        raise TransportBoundaryError(
            "persisted output request is not uniquely spec-declared"
        )
    return matched[0]


def _reconstruct_workspace_authority(
    snapshot: ProgramExecutionSnapshot,
    program_transport_store: _transport._ProgramTransportStore,
    prior_receipts: tuple[Observation, ...],
) -> dict[str, object]:
    matched = tuple(
        item
        for item in prior_receipts
        if item.data["operation"] == "ALLOCATE_WORKSPACE"
        and item.data["outcome"] == "SUCCEEDED"
    )
    if len(matched) != 1:
        raise TransportBoundaryError(
            "one successful dual-source ALLOCATE predecessor is required"
        )
    return _workspace_authority(snapshot, matched[0], program_transport_store)


def _reconstruct_staged_authorities(
    snapshot: ProgramExecutionSnapshot,
    program_transport_store: _transport._ProgramTransportStore,
    prior_receipts: tuple[Observation, ...],
) -> tuple[dict[str, object], ...]:
    return tuple(
        _artifact_authority(snapshot, item, program_transport_store)
        for item in prior_receipts
        if item.data["operation"] == "STAGE_EXACT_FILE"
        and item.data["outcome"] == "SUCCEEDED"
    )


def _reconstruct_submit_request(
    snapshot: ProgramExecutionSnapshot,
    program_transport_store: _transport._ProgramTransportStore,
    base: Mapping[str, object],
    prior_receipts: tuple[Observation, ...],
) -> Mapping[str, object]:
    workspace = _reconstruct_workspace_authority(
        snapshot, program_transport_store, prior_receipts
    )
    authorities = _reconstruct_staged_authorities(
        snapshot, program_transport_store, prior_receipts
    )
    expected_inputs: list[str] = []
    for declaration in snapshot.program_execution_spec.exact_inputs:
        matched = tuple(
            item
            for item in authorities
            if item["artifact_kind"] == "program-input"
            and all(
                item[key] == declaration[key]
                for key in (
                    "logical_role", "portable_name", "format", "sha256",
                    "size_bytes",
                )
            )
        )
        if len(matched) != 1:
            raise TransportBoundaryError(
                "submit requires one authority for every exact program input"
            )
        expected_inputs.append(str(matched[0]["artifact_authority_id"]))
    scheduler = snapshot.scheduler_artifacts[0]
    matched_schedulers = tuple(
        item
        for item in authorities
        if item["artifact_kind"] == "scheduler-script"
        and all(
            item[key] == scheduler[key]
            for key in (
                "logical_role", "portable_name", "format", "sha256",
                "size_bytes",
            )
        )
    )
    if len(matched_schedulers) != 1 or len(authorities) != len(expected_inputs) + 1:
        raise TransportBoundaryError(
            "submit staged predecessor authority set is not exact"
        )
    return _transport._submit_request(
        base,
        workspace,
        scheduler_portable_name=str(scheduler["portable_name"]),
        scheduler_artifact_authority_id=str(
            matched_schedulers[0]["artifact_authority_id"]
        ),
        program_input_artifact_authority_ids=tuple(expected_inputs),
    )


def _assert_effect_intent_replay(
    store: SQLiteRuntimeStore,
    snapshot: ProgramExecutionSnapshot,
) -> None:
    if store.attempt_state(snapshot.attempt_id) is AttemptState.PLANNED:
        raise TransportBoundaryError(
            "successor authority cannot claim a PLANNED effect intent"
        )
    try:
        claim = store.record_submission_intent(
            snapshot.attempt_id, snapshot.effect_intent_id
        )
    except RuntimeStoreError as exc:
        raise TransportBoundaryError(
            "successor effect intent does not replay through public Core"
        ) from exc
    if claim is not SubmissionIntentClaim.REPLAY:
        raise TransportBoundaryError(
            "successor effect intent requires exact public Core REPLAY"
        )


def _reconstruct_ambiguous_submit(
    store: SQLiteRuntimeStore,
    snapshot: ProgramExecutionSnapshot,
    program_transport_store: _transport._ProgramTransportStore,
    base: Mapping[str, object],
    prior_receipts: tuple[Observation, ...],
) -> Observation:
    _assert_effect_intent_replay(store, snapshot)
    matched = tuple(
        item
        for item in prior_receipts
        if item.data["operation"] == "SUBMIT_QSUB_ONCE"
        and item.data["outcome"] == "UNKNOWN"
    )
    if len(matched) != 1:
        raise TransportBoundaryError(
            "reconciliation requires one exact Core UNKNOWN submit predecessor"
        )
    receipt = matched[0]
    prefix = prior_receipts[: prior_receipts.index(receipt)]
    expected_request = _reconstruct_submit_request(
        snapshot, program_transport_store, base, prefix
    )
    request = receipt.data["request"]
    assert isinstance(request, Mapping)
    if request != expected_request:
        raise TransportBoundaryError(
            "ambiguous submit request does not re-close to prior authorities"
        )
    program_transport_store.require_matching_effect(
        binding=expected_request["binding"],
        request=expected_request,
        classification="UNKNOWN",
        response=receipt.data["response"],
    )
    return receipt


def _reconstruct_job_authority_from_receipts(
    store: SQLiteRuntimeStore,
    snapshot: ProgramExecutionSnapshot,
    program_transport_store: _transport._ProgramTransportStore,
    base: Mapping[str, object],
    receipts: tuple[Observation, ...],
) -> dict[str, object]:
    current_state = store.attempt_state(snapshot.attempt_id)
    if current_state not in {
        AttemptState.SUBMITTED,
        AttemptState.RUNNING,
        AttemptState.SUCCEEDED,
        AttemptState.FAILED,
    }:
        raise TransportBoundaryError(
            "successor job authority requires a submitted-compatible Core state"
        )
    _assert_effect_intent_replay(store, snapshot)
    establishing = tuple(
        item
        for item in receipts
        if item.data["operation"]
        in {"SUBMIT_QSUB_ONCE", "RECONCILE_SUBMISSION"}
        and item.data["outcome"] == "SUCCEEDED"
        and _receipt_job_id(item.data) is not None
    )
    if len(establishing) != 1:
        raise TransportBoundaryError(
            "exact persisted successor job-establishing receipt is required"
        )
    receipt = establishing[0]
    prefix = receipts[: receipts.index(receipt)]
    job_id = _receipt_job_id(receipt.data)
    assert job_id is not None
    if receipt.data["operation"] == "SUBMIT_QSUB_ONCE":
        expected_request = _reconstruct_submit_request(
            snapshot, program_transport_store, base, prefix
        )
    else:
        try:
            replayed_state = store.reconcile_unknown(
                snapshot.attempt_id,
                receipt.observation_id,
                ReconciliationResolution.SUBMITTED,
            )
        except RuntimeStoreError as exc:
            raise TransportBoundaryError(
                "Core SUBMITTED reconciliation does not replay for the job receipt"
            ) from exc
        if replayed_state is not current_state:
            raise TransportBoundaryError(
                "Core reconciliation replay changed successor Attempt state"
            )
        ambiguous = _reconstruct_ambiguous_submit(
            store, snapshot, program_transport_store, base, prefix
        )
        expected_request = _transport._reconciliation_request(
            base, submit_receipt_id=ambiguous.observation_id
        )
    request = receipt.data["request"]
    if request != expected_request:
        raise TransportBoundaryError(
            "job-establishing request does not re-close to prior authorities"
        )
    physical_id = program_transport_store.require_matching_effect(
        binding=expected_request["binding"],
        request=expected_request,
        classification="SUCCEEDED",
        response=receipt.data["response"],
        job_id=job_id,
    )
    payload = {
        "program_execution_snapshot_id": snapshot.program_execution_snapshot_id,
        "effect_intent_id": snapshot.effect_intent_id,
        "establishing_operation": receipt.data["operation"],
        "establishing_receipt_id": receipt.observation_id,
        "physical_effect_authority_id": physical_id,
        "program_transport_store_id": (
            program_transport_store.program_transport_store_id
        ),
        "store_instance_id": program_transport_store.store_instance_id,
        "runtime_attestation_id": base["runtime_attestation_id"],
        "job_id": job_id,
        "remote_workspace": snapshot.workspace_binding.remote_attempt_dir,
        "resolved_server_profile_id": (
            snapshot.resolved_server_profile.resolved_server_profile_id
        ),
    }
    return {
        **payload,
        "job_authority_id": _transport._identity("job-authority", payload),
    }


def _reconstruct_stat_authority(
    snapshot: ProgramExecutionSnapshot,
    declaration: Mapping[str, object],
    prior_receipts: tuple[Observation, ...],
) -> tuple[Observation, int, str]:
    matched = tuple(
        item
        for item in prior_receipts
        if item.data["operation"] == "STAT_EXACT_FILE"
        and item.data["outcome"] == "SUCCEEDED"
        and isinstance(item.data["request"], Mapping)
        and isinstance(item.data["request"]["payload"], Mapping)
        and all(
            item.data["request"]["payload"].get(key) == declaration[key]
            for key in ("logical_role", "portable_name", "format")
        )
    )
    if len(matched) != 1:
        raise TransportBoundaryError(
            "fetch requires one exact successful STAT predecessor"
        )
    response, size = _transport._stat_response(
        matched[0].data["response"],
        name=str(declaration["portable_name"]),
        max_size_bytes=int(declaration["max_size_bytes"]),
    )
    if size is None:
        raise TransportBoundaryError("fetch cannot consume an absent STAT authority")
    return matched[0], size, str(response["file_physical_token"])


def _reconstruct_expected_request(
    store: SQLiteRuntimeStore,
    snapshot: ProgramExecutionSnapshot,
    program_transport_store: _transport._ProgramTransportStore,
    base: Mapping[str, object],
    receipt_payload: Mapping[str, object],
    prior_receipts: tuple[Observation, ...],
) -> Mapping[str, object]:
    request = receipt_payload["request"]
    assert isinstance(request, Mapping)
    candidate_payload = request.get("payload")
    if not isinstance(candidate_payload, Mapping):
        raise TransportBoundaryError("successor receipt request payload is malformed")
    operation = str(receipt_payload["operation"])
    if request.get("operation") != operation:
        raise TransportBoundaryError(
            "successor receipt operation differs from its exact request"
        )
    if operation == "ALLOCATE_WORKSPACE":
        return _transport._request(operation, base, {})
    if operation == "STAGE_EXACT_FILE":
        workspace = _reconstruct_workspace_authority(
            snapshot, program_transport_store, prior_receipts
        )
        return _transport._stage_request(
            base, workspace, _declared_stage_payload(snapshot, candidate_payload)
        )
    if operation == "SUBMIT_QSUB_ONCE":
        return _reconstruct_submit_request(
            snapshot, program_transport_store, base, prior_receipts
        )
    if operation == "RECONCILE_SUBMISSION":
        ambiguous = _reconstruct_ambiguous_submit(
            store, snapshot, program_transport_store, base, prior_receipts
        )
        return _transport._reconciliation_request(
            base, submit_receipt_id=ambiguous.observation_id
        )
    job = _reconstruct_job_authority_from_receipts(
        store, snapshot, program_transport_store, base, prior_receipts
    )
    if operation == "QUERY_SCHEDULER":
        return _transport._scheduler_request(
            base,
            job_authority_id=str(job["job_authority_id"]),
            job_id=str(job["job_id"]),
        )
    declaration = _declared_output(snapshot, candidate_payload)
    if operation == "STAT_EXACT_FILE":
        return _transport._stat_request(
            base,
            job_authority_id=str(job["job_authority_id"]),
            declaration=declaration,
        )
    stat_receipt, size, token = _reconstruct_stat_authority(
        snapshot, declaration, prior_receipts
    )
    return _transport._fetch_request(
        base,
        job_authority_id=str(job["job_authority_id"]),
        declaration=declaration,
        announced_size=size,
        file_physical_token=token,
        stat_receipt_id=stat_receipt.observation_id,
    )


def _reclose_receipt_response(
    snapshot: ProgramExecutionSnapshot,
    payload: Mapping[str, object],
    expected_request: Mapping[str, object],
) -> None:
    response = payload["response"]
    assert isinstance(response, Mapping)
    operation = str(payload["operation"])
    request_payload = expected_request["payload"]
    assert isinstance(request_payload, Mapping)
    if operation == "ALLOCATE_WORKSPACE" and payload["outcome"] == "SUCCEEDED":
        _transport._workspace_response(
            response, snapshot.workspace_binding.remote_attempt_dir
        )
    elif operation == "STAGE_EXACT_FILE" and payload["outcome"] == "SUCCEEDED":
        _transport._stage_response(response, request_payload)
    elif operation == "SUBMIT_QSUB_ONCE" and payload["outcome"] == "SUCCEEDED":
        _transport._submit_response(response)
    elif operation == "QUERY_SCHEDULER" and payload["outcome"] == "SUCCEEDED":
        _transport._scheduler_response(
            response, _transport._job_id(request_payload["job_id"])
        )
    elif operation == "RECONCILE_SUBMISSION":
        _transport._reconciliation_response(response)
    elif operation == "STAT_EXACT_FILE" and payload["outcome"] == "SUCCEEDED":
        declaration = _declared_output(snapshot, request_payload)
        _transport._stat_response(
            response,
            name=str(declaration["portable_name"]),
            max_size_bytes=int(declaration["max_size_bytes"]),
        )
    elif operation == "FETCH_EXACT_FILE" and payload["outcome"] == "SUCCEEDED":
        closed = _transport._exact_keys(
            response,
            {"portable_name", "sha256", "size_bytes", "file_physical_token"},
            "persisted fetch response",
        )
        if (
            closed["portable_name"] != request_payload["portable_name"]
            or closed["size_bytes"] != request_payload["expected_size_bytes"]
            or closed["file_physical_token"]
            != request_payload["expected_file_physical_token"]
            or not isinstance(closed["sha256"], str)
            or _transport._SHA256.fullmatch(closed["sha256"]) is None
        ):
            raise TransportBoundaryError(
                "persisted fetch response differs from exact request"
            )


def _append_receipt(
    store: SQLiteRuntimeStore,
    snapshot: ProgramExecutionSnapshot,
    *,
    program_transport_store: _transport._ProgramTransportStore,
    current_binding: Mapping[str, object],
    operation: str,
    request: Mapping[str, object],
    outcome: str,
    response: Mapping[str, object],
    job_id: str | None = None,
) -> Observation:
    payload = _receipt_payload(
        snapshot,
        sequence=len(
            _load_receipts(
                store, snapshot, program_transport_store, current_binding
            )
        )
        + 1,
        operation=operation, request=request, outcome=outcome, response=response,
    )
    program_transport_store.require_matching_effect(
        binding=request["binding"],
        request=request,
        classification=outcome,
        response=response,
        job_id=job_id,
    )
    record = Observation(
        observation_id=_transport._identity("effect-receipt", payload),
        attempt_id=snapshot.attempt_id,
        observation_type=_transport._RECEIPT_TYPE,
        data=payload,
    )
    store.append_observation(record)
    loaded = _load_receipts(
        store, snapshot, program_transport_store, current_binding
    )
    if not loaded or loaded[-1] != record:
        raise TransportBoundaryError("successor receipt did not persist exactly")
    return loaded[-1]


def _workspace_authority(
    snapshot: ProgramExecutionSnapshot,
    receipt: Observation,
    program_transport_store: _transport._ProgramTransportStore,
) -> dict[str, object]:
    payload = receipt.data
    response = _transport._workspace_response(
        payload["response"], snapshot.workspace_binding.remote_attempt_dir
    )
    if payload["operation"] != "ALLOCATE_WORKSPACE" or payload["outcome"] != "SUCCEEDED":
        raise TransportBoundaryError("workspace authority does not close to snapshot")
    token = _transport._text(response["workspace_physical_token"], "workspace physical token")
    authority_payload = {
        "program_execution_snapshot_id": snapshot.program_execution_snapshot_id,
        "effect_intent_id": snapshot.effect_intent_id,
        "receipt_id": receipt.observation_id,
        "remote_workspace": response["remote_workspace"],
        "workspace_physical_token": token,
        "physical_effect_authority_id": (
            program_transport_store.require_matching_effect(
                binding=payload["request"]["binding"],
                request=payload["request"],
                classification="SUCCEEDED",
                response=payload["response"],
            )
        ),
    }
    return {
        "workspace_authority_id": _transport._identity("workspace-authority", authority_payload),
        "workspace_receipt_id": receipt.observation_id,
        "workspace_physical_token": token,
    }


def _artifact_authority(
    snapshot: ProgramExecutionSnapshot,
    receipt: Observation,
    program_transport_store: _transport._ProgramTransportStore,
) -> dict[str, object]:
    payload = receipt.data
    request = payload["request"]
    if not isinstance(request, Mapping) or not isinstance(request.get("payload"), Mapping):
        raise TransportBoundaryError("stage receipt request is malformed")
    expected = dict(request["payload"])
    response = _transport._stage_response(payload["response"], expected)
    if payload["operation"] != "STAGE_EXACT_FILE" or payload["outcome"] != "SUCCEEDED":
        raise TransportBoundaryError("staged artifact authority is inconsistent")
    _transport._text(response["artifact_physical_token"], "artifact physical token")
    authority_payload = {
        "program_execution_snapshot_id": snapshot.program_execution_snapshot_id,
        "effect_intent_id": snapshot.effect_intent_id,
        "receipt_id": receipt.observation_id,
        **dict(response),
        "physical_effect_authority_id": (
            program_transport_store.require_matching_effect(
                binding=request["binding"],
                request=request,
                classification="SUCCEEDED",
                response=payload["response"],
            )
        ),
    }
    return {
        **dict(response), "artifact_receipt_id": receipt.observation_id,
        "artifact_authority_id": _transport._identity("artifact-authority", authority_payload),
    }


def _job_authority(
    store: SQLiteRuntimeStore,
    snapshot: ProgramExecutionSnapshot,
    program_transport_store: _transport._ProgramTransportStore,
    driver: _transport._ProgramEffectDriver,
) -> dict[str, object]:
    base = _snapshot_binding(snapshot, program_transport_store, driver)
    receipts = _load_receipts(
        store, snapshot, program_transport_store, base
    )
    return _reconstruct_job_authority_from_receipts(
        store, snapshot, program_transport_store, base, receipts
    )


def _assert_program_output_capture_authority(
    store: SQLiteRuntimeStore,
    *,
    snapshot: ProgramExecutionSnapshot,
    program_transport_store: _transport._ProgramTransportStore,
    driver: _transport._ProgramEffectDriver,
    capture: _transport._ProgramOutputCapture,
) -> Mapping[str, object]:
    """Re-attest one capture from persisted Core and physical-effect authority."""

    if type(store) is not SQLiteRuntimeStore:
        raise TransportBoundaryError(
            "capture re-attestation requires the exact Core store"
        )
    if type(capture) is not _transport._ProgramOutputCapture:
        raise TransportBoundaryError(
            "capture re-attestation requires the exact output capture type"
        )
    closed_driver = _transport._require_driver(driver)
    expected_job = _job_authority(
        store, snapshot, program_transport_store, closed_driver
    )
    current_binding = _snapshot_binding(
        snapshot, program_transport_store, closed_driver
    )
    receipts = _load_receipts(
        store, snapshot, program_transport_store, current_binding
    )
    expected_job_id = str(expected_job["job_authority_id"])
    if (
        capture.program_execution_snapshot_id
        != snapshot.program_execution_snapshot_id
        or capture.effect_intent_id != snapshot.effect_intent_id
        or capture.job_authority_id != expected_job_id
    ):
        raise TransportBoundaryError(
            "output capture differs from the exact execution snapshot or replayed job authority"
        )
    if type(capture.artifacts) is not tuple:
        raise TransportBoundaryError("output capture artifacts must be an exact tuple")

    declared = tuple(
        (item, True) for item in snapshot.program_execution_spec.required_outputs
    ) + tuple(
        (item, False) for item in snapshot.program_execution_spec.optional_outputs
    )
    declared_keys = tuple(
        (
            str(item["logical_role"]),
            str(item["portable_name"]),
            str(item["format"]),
        )
        for item, _required in declared
    )
    if (
        len(declared_keys) != len(set(declared_keys))
        or len(capture.artifacts) != len(declared)
    ):
        raise TransportBoundaryError(
            "output capture does not have one artifact per unique declaration"
        )

    seen_declarations: set[tuple[str, str, str]] = set()
    seen_fetch_receipts: set[str] = set()
    for artifact in capture.artifacts:
        if type(artifact) is not _transport._ProgramOutputArtifact:
            raise TransportBoundaryError(
                "output capture contains a non-canonical artifact"
            )
        key = (
            _transport._text(artifact.logical_role, "captured output logical role"),
            _transport._portable(
                artifact.portable_name, "captured output portable name"
            ),
            _transport._text(artifact.format, "captured output format"),
        )
        declaration = _declared_output(
            snapshot,
            {
                "logical_role": key[0],
                "portable_name": key[1],
                "format": key[2],
            },
        )
        if key in seen_declarations:
            raise TransportBoundaryError("output capture repeats a declaration")
        seen_declarations.add(key)
        required = any(
            item is declaration and is_required
            for item, is_required in declared
        )
        if (
            artifact.program_execution_snapshot_id
            != snapshot.program_execution_snapshot_id
            or artifact.effect_intent_id != snapshot.effect_intent_id
            or artifact.job_authority_id != expected_job_id
        ):
            raise TransportBoundaryError(
                "captured artifact differs from replayed snapshot or job authority"
            )
        if artifact.presence not in {"present", "absent"}:
            raise TransportBoundaryError(
                "captured artifact presence is outside the closed set"
            )

        matching_stats = tuple(
            receipt
            for receipt in receipts
            if receipt.data["operation"] == "STAT_EXACT_FILE"
            and receipt.data["outcome"] == "SUCCEEDED"
            and isinstance(receipt.data["request"], Mapping)
            and isinstance(receipt.data["request"].get("payload"), Mapping)
            and all(
                receipt.data["request"]["payload"].get(name)
                == declaration[name]
                for name in ("logical_role", "portable_name", "format")
            )
        )
        if len(matching_stats) != 1:
            raise TransportBoundaryError(
                "captured artifact requires one exact persisted STAT authority"
            )
        stat_receipt = matching_stats[0]
        stat_response, announced_size = _transport._stat_response(
            stat_receipt.data["response"],
            name=str(declaration["portable_name"]),
            max_size_bytes=int(declaration["max_size_bytes"]),
        )

        if artifact.presence == "absent":
            if (
                required
                or announced_size is not None
                or artifact.sha256 is not None
                or artifact.size_bytes is not None
                or artifact.fetch_receipt_id is not None
                or artifact.content is not None
            ):
                raise TransportBoundaryError(
                    "only an optional output with exact absent STAT authority may be absent"
                )
            continue

        if announced_size is None:
            raise TransportBoundaryError(
                "present captured artifact has an absent STAT authority"
            )
        if (
            not isinstance(artifact.sha256, str)
            or _transport._SHA256.fullmatch(artifact.sha256) is None
            or isinstance(artifact.size_bytes, bool)
            or not isinstance(artifact.size_bytes, int)
            or artifact.size_bytes < 0
            or type(artifact.content) is not bytes
            or not isinstance(artifact.fetch_receipt_id, str)
            or not artifact.fetch_receipt_id
            or artifact.fetch_receipt_id in seen_fetch_receipts
        ):
            raise TransportBoundaryError(
                "present captured artifact authority is malformed"
            )
        seen_fetch_receipts.add(artifact.fetch_receipt_id)
        content = artifact.content
        assert isinstance(content, bytes)
        if (
            len(content) != artifact.size_bytes
            or sha256(content).hexdigest() != artifact.sha256
            or artifact.size_bytes != announced_size
        ):
            raise TransportBoundaryError(
                "captured output bytes differ from their exact authority"
            )
        matching_fetches = tuple(
            receipt
            for receipt in receipts
            if receipt.observation_id == artifact.fetch_receipt_id
            and receipt.data["operation"] == "FETCH_EXACT_FILE"
            and receipt.data["outcome"] == "SUCCEEDED"
        )
        if len(matching_fetches) != 1:
            raise TransportBoundaryError(
                "captured output requires its exact successful FETCH receipt"
            )
        fetch_receipt = matching_fetches[0]
        fetch_index = receipts.index(fetch_receipt)
        if stat_receipt not in receipts[:fetch_index]:
            raise TransportBoundaryError(
                "captured FETCH authority lacks its exact preceding STAT"
            )
        fetch_request = fetch_receipt.data["request"]
        if not isinstance(fetch_request, Mapping) or not isinstance(
            fetch_request.get("payload"), Mapping
        ):
            raise TransportBoundaryError("persisted FETCH request is malformed")
        fetch_payload = fetch_request["payload"]
        fetch_binding = fetch_request.get("binding")
        if not isinstance(fetch_binding, Mapping) or (
            fetch_binding.get("job_authority_id") != expected_job_id
            or fetch_payload.get("logical_role") != declaration["logical_role"]
            or fetch_payload.get("portable_name") != declaration["portable_name"]
            or fetch_payload.get("format") != declaration["format"]
            or fetch_payload.get("stat_receipt_id")
            != stat_receipt.observation_id
        ):
            raise TransportBoundaryError(
                "persisted FETCH request differs from captured output authority"
            )
        fetch_response = _transport._exact_keys(
            fetch_receipt.data["response"],
            {"portable_name", "sha256", "size_bytes", "file_physical_token"},
            "persisted fetch response",
        )
        if (
            fetch_response["portable_name"] != artifact.portable_name
            or fetch_response["sha256"] != artifact.sha256
            or fetch_response["size_bytes"] != artifact.size_bytes
            or fetch_response["file_physical_token"]
            != stat_response["file_physical_token"]
        ):
            raise TransportBoundaryError(
                "captured output differs from persisted FETCH authority"
            )

    if seen_declarations != set(declared_keys):
        raise TransportBoundaryError(
            "output capture is missing a declared output artifact"
        )
    payload = {
        "program_execution_snapshot_id": capture.program_execution_snapshot_id,
        "effect_intent_id": capture.effect_intent_id,
        "job_authority_id": capture.job_authority_id,
        "artifacts": tuple(item.identity_payload() for item in capture.artifacts),
    }
    if capture.capture_authority_id != _transport._identity(
        "output-capture", payload
    ):
        raise TransportBoundaryError("output capture authority self-identity is stale")
    return expected_job


@dataclass(frozen=True, slots=True)
class _ProgramExecutionResult:
    claim: SubmissionIntentClaim
    outcome: str
    job_authority: Mapping[str, object] | None
    receipts: tuple[Observation, ...]


def _execute_program_once(
    store: SQLiteRuntimeStore, *, snapshot: ProgramExecutionSnapshot,
    program_transport_store: _transport._ProgramTransportStore,
    input_bytes: Mapping[str, bytes],
    scheduler_artifact_bytes: Mapping[str, bytes], driver: _transport._ProgramEffectDriver,
) -> _ProgramExecutionResult:
    if type(store) is not SQLiteRuntimeStore:
        raise TransportBoundaryError("successor execution requires exact SQLiteRuntimeStore")
    closed_driver = _transport._require_driver(driver)
    base = _snapshot_binding(snapshot, program_transport_store, closed_driver)
    material = _stage_material(
        snapshot, input_bytes=input_bytes,
        scheduler_artifact_bytes=scheduler_artifact_bytes,
    )
    prepared = _transport._prepare_program_effect_requests(base, material)
    prepared.assert_closed()
    claim = store.record_submission_intent(snapshot.attempt_id, snapshot.effect_intent_id)
    if claim is SubmissionIntentClaim.REPLAY:
        receipts = _load_receipts(
            store, snapshot, program_transport_store, base
        )
        try:
            job = _job_authority(
                store, snapshot, program_transport_store, closed_driver
            )
        except TransportBoundaryError:
            job = None
        outcome = "SUCCEEDED" if job is not None else (str(receipts[-1].data["outcome"]) if receipts else "FAILED")
        return _ProgramExecutionResult(claim, outcome, job, receipts)

    current_operation = "ALLOCATE_WORKSPACE"
    current_request = prepared.allocate_request
    physical_recorded = False
    try:
        workspace_map = _transport._workspace_response(
            _transport._call(closed_driver.allocate_workspace, current_request),
            snapshot.workspace_binding.remote_attempt_dir,
        )
        program_transport_store.record_effect(
            binding=current_request["binding"], request=current_request,
            classification="SUCCEEDED", response=workspace_map,
        )
        physical_recorded = True
        receipt = _append_receipt(
            store, snapshot, program_transport_store=program_transport_store,
            current_binding=base, operation=current_operation,
            request=current_request, outcome="SUCCEEDED", response=workspace_map,
        )
        physical_recorded = False
        workspace = _workspace_authority(
            snapshot, receipt, program_transport_store
        )

        authorities: list[dict[str, object]] = []
        for payload, content in prepared.material:
            current_operation = "STAGE_EXACT_FILE"
            current_request = _transport._stage_request(base, workspace, payload)
            response_map = _transport._stage_response(
                _transport._call(
                    closed_driver.stage_exact_file, current_request, content
                ),
                payload,
            )
            program_transport_store.record_effect(
                binding=current_request["binding"], request=current_request,
                classification="SUCCEEDED", response=response_map,
            )
            physical_recorded = True
            receipt = _append_receipt(
                store, snapshot,
                program_transport_store=program_transport_store,
                current_binding=base, operation=current_operation,
                request=current_request, outcome="SUCCEEDED",
                response=response_map,
            )
            physical_recorded = False
            authorities.append(
                _artifact_authority(snapshot, receipt, program_transport_store)
            )
        schedulers = tuple(item for item in authorities if item["artifact_kind"] == "scheduler-script")
        program_inputs = tuple(item for item in authorities if item["artifact_kind"] == "program-input")
        if len(schedulers) != 1 or len(program_inputs) != len(snapshot.program_execution_spec.exact_inputs):
            raise TransportBoundaryError("successor staged authority is incomplete")
        current_operation = "SUBMIT_QSUB_ONCE"
        current_request = _transport._submit_request(
            base, workspace,
            scheduler_portable_name=prepared.scheduler_portable_name,
            scheduler_artifact_authority_id=str(
                schedulers[0]["artifact_authority_id"]
            ),
            program_input_artifact_authority_ids=tuple(
                str(item["artifact_authority_id"]) for item in program_inputs
            ),
        )
        submit_map = _transport._submit_response(
            _transport._call(closed_driver.submit_qsub_once, current_request)
        )
        job_id = _transport._job_id(submit_map["job_id"])
        program_transport_store.record_effect(
            binding=current_request["binding"], request=current_request,
            classification="SUCCEEDED", response=submit_map, job_id=job_id,
        )
        physical_recorded = True
        _append_receipt(
            store, snapshot, program_transport_store=program_transport_store,
            current_binding=base, operation=current_operation,
            request=current_request, outcome="SUCCEEDED", response=submit_map,
            job_id=job_id,
        )
        physical_recorded = False
        store.record_submission_outcome(snapshot.attempt_id, snapshot.effect_intent_id, SubmissionOutcome.SUBMITTED)
        job = _job_authority(
            store, snapshot, program_transport_store, closed_driver
        )
        return _ProgramExecutionResult(
            claim, "SUCCEEDED", job,
            _load_receipts(store, snapshot, program_transport_store, base),
        )
    except _transport._ProgramConfirmedFailure as exc:
        if physical_recorded:
            raise
        response = {
            "reason": _transport._text(str(exc), "confirmed failure reason")
        }
        program_transport_store.record_effect(
            binding=current_request["binding"], request=current_request,
            classification="FAILED", response=response,
        )
        _append_receipt(
            store, snapshot, program_transport_store=program_transport_store,
            current_binding=base, operation=current_operation,
            request=current_request, outcome="FAILED", response=response,
        )
        return _ProgramExecutionResult(
            claim, "FAILED", None,
            _load_receipts(store, snapshot, program_transport_store, base),
        )
    except Exception:
        if physical_recorded:
            raise
        response = {"reason": "ambiguous-operation-outcome"}
        program_transport_store.record_effect(
            binding=current_request["binding"], request=current_request,
            classification="UNKNOWN", response=response,
        )
        _append_receipt(
            store, snapshot, program_transport_store=program_transport_store,
            current_binding=base, operation=current_operation,
            request=current_request, outcome="UNKNOWN", response=response,
        )
        store.record_submission_outcome(snapshot.attempt_id, snapshot.effect_intent_id, SubmissionOutcome.UNKNOWN)
        return _ProgramExecutionResult(
            claim, "UNKNOWN", None,
            _load_receipts(store, snapshot, program_transport_store, base),
        )


def _query_program_scheduler(
    store: SQLiteRuntimeStore, *, snapshot: ProgramExecutionSnapshot,
    program_transport_store: _transport._ProgramTransportStore,
    driver: _transport._ProgramEffectDriver,
) -> Mapping[str, object]:
    closed_driver = _transport._require_driver(driver)
    base = _snapshot_binding(snapshot, program_transport_store, closed_driver)
    job = _job_authority(
        store, snapshot, program_transport_store, closed_driver
    )
    request = _transport._scheduler_request(
        base, job_authority_id=str(job["job_authority_id"]),
        job_id=str(job["job_id"]),
    )
    try:
        result = _transport._scheduler_response(
            _transport._call(closed_driver.query_scheduler, request),
            str(job["job_id"]),
        )
        program_transport_store.record_effect(
            binding=request["binding"], request=request,
            classification="SUCCEEDED", response=result,
        )
        _append_receipt(
            store, snapshot, program_transport_store=program_transport_store,
            current_binding=base, operation="QUERY_SCHEDULER",
            request=request, outcome="SUCCEEDED", response=result,
        )
        return dict(result)
    except Exception:
        response = {"reason": "ambiguous-scheduler-read"}
        program_transport_store.record_effect(
            binding=request["binding"], request=request,
            classification="UNKNOWN", response=response,
        )
        _append_receipt(
            store, snapshot, program_transport_store=program_transport_store,
            current_binding=base, operation="QUERY_SCHEDULER",
            request=request, outcome="UNKNOWN", response=response,
        )
        return {"job_id": job["job_id"], "state": "unknown"}


def _reconcile_program_submission(
    store: SQLiteRuntimeStore, *, snapshot: ProgramExecutionSnapshot,
    program_transport_store: _transport._ProgramTransportStore,
    driver: _transport._ProgramEffectDriver,
) -> Mapping[str, object]:
    if store.attempt_state(snapshot.attempt_id) is not AttemptState.UNKNOWN:
        raise TransportBoundaryError("successor reconciliation requires UNKNOWN")
    closed_driver = _transport._require_driver(driver)
    base = _snapshot_binding(snapshot, program_transport_store, closed_driver)
    submit_receipts = tuple(
        item
        for item in _load_receipts(
            store, snapshot, program_transport_store, base
        )
        if item.data["operation"] == "SUBMIT_QSUB_ONCE"
    )
    if len(submit_receipts) != 1:
        raise TransportBoundaryError("reconciliation requires one persisted submit receipt")
    request = _transport._reconciliation_request(
        base, submit_receipt_id=submit_receipts[0].observation_id
    )
    try:
        response = _transport._reconciliation_response(
            _transport._call(closed_driver.reconcile_submission, request)
        )
    except Exception:
        response = {"outcome": "UNKNOWN"}
    outcome = str(response["outcome"])
    resolution = {
        "UNKNOWN": ReconciliationResolution.UNRESOLVED,
        "FAILED": ReconciliationResolution.NOT_SUBMITTED,
        "SUCCEEDED": ReconciliationResolution.SUBMITTED,
    }[outcome]
    job_id = (
        _transport._job_id(response["job_id"])
        if resolution is ReconciliationResolution.SUBMITTED
        else None
    )
    program_transport_store.record_effect(
        binding=request["binding"], request=request,
        classification=outcome, response=response, job_id=job_id,
    )
    receipt = _append_receipt(
        store, snapshot, program_transport_store=program_transport_store,
        current_binding=base, operation="RECONCILE_SUBMISSION",
        request=request, outcome=outcome, response=response, job_id=job_id,
    )
    state = store.reconcile_unknown(
        snapshot.attempt_id, receipt.observation_id, resolution
    )
    if state is AttemptState.SUBMITTED:
        _job_authority(
            store, snapshot, program_transport_store, closed_driver
        )
    return dict(response)


def _capture_program_outputs(
    store: SQLiteRuntimeStore, *, snapshot: ProgramExecutionSnapshot,
    program_transport_store: _transport._ProgramTransportStore,
    driver: _transport._ProgramEffectDriver,
) -> _transport._ProgramOutputCapture:
    closed_driver = _transport._require_driver(driver)
    base = _snapshot_binding(snapshot, program_transport_store, closed_driver)
    job = _job_authority(
        store, snapshot, program_transport_store, closed_driver
    )
    declarations = (
        *((item, True) for item in snapshot.program_execution_spec.required_outputs),
        *((item, False) for item in snapshot.program_execution_spec.optional_outputs),
    )
    artifacts: list[_transport._ProgramOutputArtifact] = []
    for declaration, required in declarations:
        name = _transport._portable(declaration["portable_name"], "declared output name")
        stat_request = _transport._stat_request(
            base, job_authority_id=str(job["job_authority_id"]),
            declaration=declaration,
        )
        stat_response, announced_size = _transport._stat_response(
            _transport._call(closed_driver.stat_exact_file, stat_request),
            name=name, max_size_bytes=declaration["max_size_bytes"],
        )
        if announced_size is None:
            program_transport_store.record_effect(
                binding=stat_request["binding"], request=stat_request,
                classification="SUCCEEDED", response=stat_response,
            )
            _append_receipt(
                store, snapshot,
                program_transport_store=program_transport_store,
                current_binding=base, operation="STAT_EXACT_FILE",
                request=stat_request, outcome="SUCCEEDED",
                response=stat_response,
            )
            if required:
                raise TransportBoundaryError("required successor output is absent")
            artifacts.append(_transport._ProgramOutputArtifact(
                str(declaration["logical_role"]), name, str(declaration["format"]),
                "absent", None, None, snapshot.program_execution_snapshot_id,
                snapshot.effect_intent_id, str(job["job_authority_id"]), None, None,
            ))
            continue
        token = str(stat_response["file_physical_token"])
        program_transport_store.record_effect(
            binding=stat_request["binding"], request=stat_request,
            classification="SUCCEEDED", response=stat_response,
        )
        stat_receipt = _append_receipt(
            store, snapshot, program_transport_store=program_transport_store,
            current_binding=base, operation="STAT_EXACT_FILE",
            request=stat_request, outcome="SUCCEEDED", response=stat_response,
        )
        fetch_request = _transport._fetch_request(
            base, job_authority_id=str(job["job_authority_id"]),
            declaration=declaration, announced_size=announced_size,
            file_physical_token=token,
            stat_receipt_id=stat_receipt.observation_id,
        )
        _fetch_map, content, digest, size = _transport._fetch_response(
            _transport._call(closed_driver.fetch_exact_file, fetch_request),
            name=name, token=token, announced_size=announced_size,
            max_size_bytes=declaration["max_size_bytes"],
        )
        receipt_response = {"portable_name": name, "sha256": digest, "size_bytes": size, "file_physical_token": token}
        program_transport_store.record_effect(
            binding=fetch_request["binding"], request=fetch_request,
            classification="SUCCEEDED", response=receipt_response,
        )
        fetch_receipt = _append_receipt(
            store, snapshot, program_transport_store=program_transport_store,
            current_binding=base, operation="FETCH_EXACT_FILE",
            request=fetch_request, outcome="SUCCEEDED",
            response=receipt_response,
        )
        artifacts.append(_transport._ProgramOutputArtifact(
            str(declaration["logical_role"]), name, str(declaration["format"]),
            "present", digest, size, snapshot.program_execution_snapshot_id,
            snapshot.effect_intent_id, str(job["job_authority_id"]),
            fetch_receipt.observation_id, content,
        ))
    payload = {
        "program_execution_snapshot_id": snapshot.program_execution_snapshot_id,
        "effect_intent_id": snapshot.effect_intent_id,
        "job_authority_id": job["job_authority_id"],
        "artifacts": tuple(item.identity_payload() for item in artifacts),
    }
    return _transport._ProgramOutputCapture(
        _transport._identity("output-capture", payload),
        snapshot.program_execution_snapshot_id, snapshot.effect_intent_id,
        str(job["job_authority_id"]), tuple(artifacts),
    )


__all__: tuple[str, ...] = ()
