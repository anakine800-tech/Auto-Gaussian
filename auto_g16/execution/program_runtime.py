"""Private Core-owned runtime composition for successor xTB/CREST effects."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from types import MappingProxyType
from functools import wraps
from contextvars import ContextVar

from auto_g16.core import (
    AttemptState,
    Observation,
    ReconciliationResolution,
    RuntimeStoreError,
    SQLiteRuntimeStore,
    SubmissionIntentClaim,
    SubmissionOutcome,
    Result,
)
from auto_g16.transport import program as _transport
from auto_g16.transport._canonical import TransportBoundaryError, canonical_bytes

from .program import ProgramExecutionSnapshot, _uses_completion_receipt
from ._identity import semantic_id, semantic_sha256, freeze_mapping
from . import _program_completion as _completion


_RECEIPT_FIELDS = {
    "schema", "protocol", "attempt_id", "program_execution_snapshot_id",
    "effect_intent_id", "effect_sequence", "operation", "request_sha256",
    "request", "outcome", "response",
}

# Only the bounded Controller/Execution call holds this local checkpoint. It is
# never passed to Transport and is not a persistent permission or claim token.
_COLLECTION_CHECKPOINT = ContextVar("collection_checkpoint", default=None)
_READONLY_RECEIPT_SOURCE = ContextVar("readonly_receipt_source", default=None)


def _completion_owned(function):
    @wraps(function)
    def guarded(store, *, snapshot, program_transport_store, _completion_token=None, **kwargs):
        if not _uses_completion_receipt(snapshot.program_execution_spec):
            return function(store, snapshot=snapshot, program_transport_store=program_transport_store, **kwargs)
        if _completion_token is not None:
            program_transport_store._require_completion_guard(_completion_token)
            return function(store, snapshot=snapshot, program_transport_store=program_transport_store, _completion_token=_completion_token, **kwargs)
        with program_transport_store._completion_guard() as token:
            return function(store, snapshot=snapshot, program_transport_store=program_transport_store, _completion_token=token, **kwargs)
    return guarded


def _completion_checkpoint(snapshot, program_transport_store):
    if _uses_completion_receipt(snapshot.program_execution_spec):
        if type(program_transport_store) is not _transport._ProgramTransportStore:
            raise TransportBoundaryError("completion checkpoint requires its exact store")
        program_transport_store._require_current_completion_owner()
        recovery = _COLLECTION_CHECKPOINT.get()
        if recovery is not None:
            owner_snapshot, owner_store, check = recovery
            if owner_snapshot != snapshot or owner_store is not program_transport_store:
                raise TransportBoundaryError("collection checkpoint scope differs")
            check()


def _publisher_completion_checkpoint(snapshot, driver):
    if snapshot.program_execution_spec.invocation["executable_identity"]["absolute_path"] in {"/opt/auto-g16-fixtures/bin/xtb", "/opt/auto-g16-fixtures/bin/crest"}:
        return
    from auto_g16.transport._program_rtwin import _RTWinProgramEffectDriver
    if type(driver) is not _RTWinProgramEffectDriver or driver._snapshot != snapshot:
        raise TransportBoundaryError("publisher-not-qualified")
    driver._authority()


def _snapshot_binding(
    snapshot: ProgramExecutionSnapshot,
    program_transport_store: _transport._ProgramTransportStore,
    driver: _transport._ProgramEffectDriver,
    *, persist: bool = False,
) -> dict[str, object]:
    if type(snapshot) is not ProgramExecutionSnapshot:
        raise TransportBoundaryError("successor composition requires exact ProgramExecutionSnapshot")
    if type(program_transport_store) is not _transport._ProgramTransportStore:
        raise TransportBoundaryError(
            "successor composition requires exact _ProgramTransportStore"
        )
    program_transport_store._attest()
    receipt_mode = _uses_completion_receipt(snapshot.program_execution_spec)
    if receipt_mode != (program_transport_store._version == 2):
        raise TransportBoundaryError("completion-store-not-qualified" if receipt_mode else "strict requires a version-1 program store")
    if receipt_mode:
        material = snapshot._completion_material()
        synthetic = (snapshot.program_execution_spec.invocation["executable_identity"]["absolute_path"] in {"/opt/auto-g16-fixtures/bin/xtb", "/opt/auto-g16-fixtures/bin/crest"} and driver.runtime_qualification.get("bootstrap_protocol") == "synthetic-v31-program-effect/1")
        if not synthetic:
            from auto_g16.transport._program_rtwin import _RTWinProgramEffectDriver
            if material["schema"] not in {_completion._PILOT_MATERIAL_SCHEMA, _completion._crest._MATERIAL_SCHEMA, _completion._startup._MATERIAL_SCHEMA} or type(driver) is not _RTWinProgramEffectDriver:
                raise TransportBoundaryError("publisher-not-qualified")
            driver._authority()
    closed_driver = _transport._require_driver(driver)
    try:
        snapshot.assert_identity_closed()
    except Exception as exc:
        raise TransportBoundaryError("successor snapshot authority is not closed") from exc
    if not str(snapshot.program_execution_spec.invocation["executable_identity"]["absolute_path"]).startswith("/opt/auto-g16-fixtures/"):
        from auto_g16.transport._program_rtwin import _RTWinProgramEffectDriver
        if type(closed_driver) is not _RTWinProgramEffectDriver or closed_driver._snapshot != snapshot or closed_driver._store is not program_transport_store:
            raise TransportBoundaryError("real executables require the exact production RTwin driver")
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
        persist=persist,
    )
    return _program_store_binding(snapshot, program_transport_store, runtime_attestation_id)


def _program_store_binding(snapshot, program_transport_store, runtime_attestation_id):
    remote_workspace = snapshot.workspace_binding.remote_attempt_dir
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


def _invoke_program_driver(
    store: SQLiteRuntimeStore, snapshot: ProgramExecutionSnapshot,
    program_transport_store: _transport._ProgramTransportStore,
    driver_call: object, request: Mapping[str, object], *args: object,
) -> Mapping[str, object]:
    """Execution owns state and dual-source closure; Transport receives mechanics."""
    from auto_g16.transport._program_rtwin import _RTWinProgramEffectDriver
    _completion_checkpoint(snapshot, program_transport_store)
    driver = getattr(driver_call, "__self__", None)
    if type(driver) is not _RTWinProgramEffectDriver:
        return _transport._call(driver_call, request, *args)
    base = _snapshot_binding(snapshot, program_transport_store, driver)
    receipts = _load_receipts(store, snapshot, program_transport_store, base)
    _assert_effect_intent_replay(store, snapshot)
    expected = _reconstruct_expected_request(
        store, snapshot, program_transport_store, base,
        {"operation": request["operation"], "request": request}, receipts,
    )
    if request != expected:
        raise TransportBoundaryError("production request differs from current predecessor closure")
    if request["operation"] in {"ALLOCATE_WORKSPACE", "STAGE_EXACT_FILE", "SUBMIT_QSUB_ONCE"} and store.attempt_state(snapshot.attempt_id) is not AttemptState.SUBMISSION_INTENT_RECORDED:
        raise TransportBoundaryError("production mutations require the Execution WINNER state")
    return driver._invoke_owned(request, tuple(item.data for item in receipts), *args)


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
            "artifact_kind": declaration["logical_role"],
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
            if payload["operation"] == "RECONCILE_SUBMISSION" and payload["request"]["payload"].get("schema") == "v31-exact-observed-job-reconciliation-request/1":
                from . import _submission_recovery as recovery
                recovery.validate_proof(store, snapshot, tuple(prior_receipts), expected_request, payload["response"])
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
            "artifact_kind": item["logical_role"],
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
    if _uses_completion_receipt(snapshot.program_execution_spec):
        declarations += (_completion._METADATA_DECLARATION,)
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
    payload_ids = []
    for declaration in snapshot.scheduler_artifacts[1:]:
        matches = [item for item in authorities if item["artifact_kind"] == "startup-payload" and all(item[key] == declaration[key] for key in ("logical_role", "portable_name", "format", "sha256", "size_bytes"))]
        if len(matches) != 1:
            raise TransportBoundaryError("submit requires exact startup payload authority")
        payload_ids.append(str(matches[0]["artifact_authority_id"]))
    if len(matched_schedulers) != 1 or len(authorities) != len(expected_inputs) + 1 + len(payload_ids):
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
        startup_payload_artifact_authority_ids=tuple(payload_ids),
    )


def _assert_effect_intent_replay(
    store: SQLiteRuntimeStore,
    snapshot: ProgramExecutionSnapshot,
) -> None:
    if store.attempt_state(snapshot.attempt_id) is AttemptState.PLANNED:
        raise TransportBoundaryError(
            "successor authority cannot claim a PLANNED effect intent"
        )
    if _READONLY_RECEIPT_SOURCE.get() is store:
        # Historical proof must not enter the public claim transaction, even
        # its replay branch. Check only the existing unique native record.
        rows = store._connection.execute(
            "SELECT attempt_id,intent_id FROM submission_intents WHERE attempt_id=? OR intent_id=?",
            (snapshot.attempt_id, snapshot.effect_intent_id)).fetchall()
        if [tuple(row) for row in rows] != [(snapshot.attempt_id, snapshot.effect_intent_id)]:
            raise TransportBoundaryError("historical source lacks the exact recorded intent")
        return
    try:
        from .runtime import _replay_submission_intent
        claim = _replay_submission_intent(store, snapshot.attempt_id, snapshot.effect_intent_id)
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
            _completion_checkpoint(snapshot, program_transport_store)
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
        if receipt.data["request"]["payload"].get("schema") == "v31-exact-observed-job-reconciliation-request/1":
            from . import _submission_recovery as recovery
            expected_request = recovery.request(snapshot, base, ambiguous)
        else:
            expected_request = _transport._reconciliation_request(base, submit_receipt_id=ambiguous.observation_id)
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
    stat_receipt_id: object = None,
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
    if _uses_completion_receipt(snapshot.program_execution_spec) and matched:
        matched = (matched[-1],) if matched[-1].observation_id == stat_receipt_id else ()
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
        if candidate_payload.get("schema") == "v31-exact-observed-job-reconciliation-request/1":
            from . import _submission_recovery as recovery
            return recovery.request(snapshot, base, ambiguous)
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
        snapshot, declaration, prior_receipts, candidate_payload.get("stat_receipt_id")
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
    _completion_checkpoint(snapshot, program_transport_store)
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


def _assert_program_terminal_success_authority(
    store: SQLiteRuntimeStore,
    *,
    snapshot: ProgramExecutionSnapshot,
    program_transport_store: _transport._ProgramTransportStore,
    driver: _transport._ProgramEffectDriver,
    capture: _transport._ProgramOutputCapture,
) -> Mapping[str, object]:
    """Re-attest terminal program success before promoting captured outputs."""

    if _uses_completion_receipt(snapshot.program_execution_spec):
        raise TransportBoundaryError("receipt completion requires private /2 authority; strict consumer is unsupported")

    expected_job = _assert_program_output_capture_authority(
        store,
        snapshot=snapshot,
        program_transport_store=program_transport_store,
        driver=driver,
        capture=capture,
    )
    if store.attempt_state(snapshot.attempt_id) is not AttemptState.SUCCEEDED:
        raise TransportBoundaryError(
            "program terminal-success authority requires Core SUCCEEDED"
        )

    closed_driver = _transport._require_driver(driver)
    current_binding = _snapshot_binding(
        snapshot, program_transport_store, closed_driver
    )
    receipts = _load_receipts(
        store, snapshot, program_transport_store, current_binding
    )
    expected_job_authority_id = str(expected_job["job_authority_id"])
    evidence_indexes: list[int] = []
    for artifact in capture.artifacts:
        stat_receipt_id: object | None = None
        if artifact.presence == "present":
            matching_fetches = tuple(
                (index, receipt)
                for index, receipt in enumerate(receipts)
                if receipt.observation_id == artifact.fetch_receipt_id
                and receipt.data["operation"] == "FETCH_EXACT_FILE"
                and receipt.data["outcome"] == "SUCCEEDED"
            )
            if len(matching_fetches) != 1:
                raise TransportBoundaryError(
                    "terminal-success ordering requires the exact capture FETCH receipt"
            )
            fetch_index, fetch_receipt = matching_fetches[0]
            fetch_request = fetch_receipt.data["request"]
            fetch_payload = (
                fetch_request.get("payload")
                if isinstance(fetch_request, Mapping)
                else None
            )
            if not isinstance(fetch_payload, Mapping):
                raise TransportBoundaryError(
                    "terminal-success capture FETCH request is malformed"
                )
            stat_receipt_id = fetch_payload.get("stat_receipt_id")
            evidence_indexes.append(fetch_index)
        matching_stats = tuple(
            (index, receipt)
            for index, receipt in enumerate(receipts)
            if receipt.data["operation"] == "STAT_EXACT_FILE"
            and receipt.data["outcome"] == "SUCCEEDED"
            and (
                stat_receipt_id is None
                or receipt.observation_id == stat_receipt_id
            )
            and isinstance(receipt.data["request"], Mapping)
            and isinstance(receipt.data["request"].get("payload"), Mapping)
            and all(
                receipt.data["request"]["payload"].get(name)
                == getattr(artifact, name)
                for name in ("logical_role", "portable_name", "format")
            )
        )
        if len(matching_stats) != 1:
            raise TransportBoundaryError(
                "terminal-success ordering requires one exact capture STAT receipt"
            )
        stat_index, _stat_receipt = matching_stats[0]
        evidence_indexes.append(stat_index)

    if not evidence_indexes:
        raise TransportBoundaryError(
            "program terminal-success authority requires capture observation evidence"
        )
    capture_boundary = min(evidence_indexes)
    scheduler_receipts = tuple(
        (index, receipt)
        for index, receipt in enumerate(receipts[:capture_boundary])
        if receipt.data["operation"] == "QUERY_SCHEDULER"
    )
    if not scheduler_receipts:
        raise TransportBoundaryError(
            "program terminal-success authority requires a pre-capture scheduler receipt"
        )
    terminal_index, terminal_receipt = scheduler_receipts[-1]
    terminal_response = terminal_receipt.data["response"]
    if not isinstance(terminal_response, Mapping):
        raise TransportBoundaryError("terminal scheduler response is malformed")
    if (
        terminal_receipt.data["outcome"] != "SUCCEEDED"
        or terminal_response.get("job_id") != expected_job["job_id"]
        or terminal_response.get("state") != "terminal"
        or type(terminal_response.get("exit_status")) is not int
        or terminal_response["exit_status"] != 0
    ):
        raise TransportBoundaryError(
            "last pre-capture scheduler receipt is not exact terminal evidence"
        )
    if any(index <= terminal_index for index in evidence_indexes):
        raise TransportBoundaryError(
            "all capture STAT and FETCH evidence must follow terminal scheduler evidence"
        )

    payload = {
        "schema": "program-terminal-success-authority/1",
        "program_execution_snapshot_id": snapshot.program_execution_snapshot_id,
        "effect_intent_id": snapshot.effect_intent_id,
        "attempt_id": snapshot.attempt_id,
        "job_authority_id": expected_job_authority_id,
        "job_id": expected_job["job_id"],
        "terminal_scheduler_receipt_id": terminal_receipt.observation_id,
        "terminal_scheduler_state": "terminal",
        "core_attempt_state": AttemptState.SUCCEEDED.value,
        "program_transport_store_id": expected_job["program_transport_store_id"],
        "store_instance_id": expected_job["store_instance_id"],
        "runtime_attestation_id": expected_job["runtime_attestation_id"],
        "resolved_server_profile_id": expected_job["resolved_server_profile_id"],
        "remote_workspace": expected_job["remote_workspace"],
    }
    return MappingProxyType(
        {
            **payload,
            "program_terminal_success_authority_id": _transport._identity(
                "program-terminal-success-authority", payload
            ),
        }
    )


@dataclass(frozen=True, slots=True)
class _ProgramExecutionResult:
    claim: SubmissionIntentClaim
    outcome: str
    job_authority: Mapping[str, object] | None
    receipts: tuple[Observation, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class _ProgramExecutionPort:
    """Private generation-specific mechanics, never an approval or claim owner."""

    snapshot: ProgramExecutionSnapshot
    program_transport_store: _transport._ProgramTransportStore
    driver: _transport._ProgramEffectDriver

    def _execute_winner(self, store: SQLiteRuntimeStore, prepared: _transport._PreparedProgramEffects, continuation: object) -> None:
        _execute_claimed_program(
            store, snapshot=self.snapshot, program_transport_store=self.program_transport_store,
            prepared=prepared, driver=self.driver,
            claim=SubmissionIntentClaim.WINNER, continuation=continuation,
        )


def _prepare_program_port(
    store: SQLiteRuntimeStore, *, port: object, snapshot: ProgramExecutionSnapshot,
    prepared_input_bytes: bytes, pbs_template_bytes: bytes,
) -> _transport._PreparedProgramEffects:
    if type(port) is not _ProgramExecutionPort or port.snapshot is not snapshot:
        raise TransportBoundaryError("successor execution requires its exact private generation port")
    if type(prepared_input_bytes) is not bytes or type(pbs_template_bytes) is not bytes:
        raise TransportBoundaryError("successor input and scheduler must be exact bytes")
    snapshot.assert_identity_closed()
    inputs, schedulers = snapshot.program_execution_spec.exact_inputs, snapshot.scheduler_artifacts
    if len(inputs) != 1 or len(schedulers) not in {1, 2}:
        raise TransportBoundaryError("the common entrypoint requires one exact input and scheduler")
    prepared = _prepare_program_execution(
        store, snapshot=snapshot, program_transport_store=port.program_transport_store,
        input_bytes={str(inputs[0]["portable_name"]): prepared_input_bytes},
        scheduler_artifact_bytes={str(schedulers[0]["portable_name"]): pbs_template_bytes, **{str(item["portable_name"]): item["content_utf8"].encode("utf-8") for item in schedulers[1:]}},
        driver=port.driver,
    )
    spec = snapshot.program_execution_spec
    if spec.program_kind == "crest" and spec.adapter_contract_version == 3:
        synthetic = (spec.invocation["executable_identity"]["absolute_path"] == "/opt/auto-g16-fixtures/bin/crest"
                     and port.driver.runtime_qualification.get("bootstrap_protocol") == "synthetic-v31-program-effect/1")
        if not synthetic:
            from ._crest_seed_handoff import _assert_fixed_receipt_submission
            _assert_fixed_receipt_submission(store, snapshot, prepared_input_bytes)
    return prepared


@_completion_owned
def _read_program_execution_result(
    store: SQLiteRuntimeStore, *, snapshot: ProgramExecutionSnapshot,
    program_transport_store: _transport._ProgramTransportStore,
    driver: _transport._ProgramEffectDriver, claim: SubmissionIntentClaim,
    _completion_token: object = None,
) -> _ProgramExecutionResult:
    """Reconstruct private successor detail from its persisted dual-source authority."""
    _assert_effect_intent_replay(store, snapshot)
    base = _snapshot_binding(snapshot, program_transport_store, driver)
    receipts = _load_receipts(store, snapshot, program_transport_store, base)
    try:
        job = _job_authority(store, snapshot, program_transport_store, driver)
    except TransportBoundaryError:
        job = None
    outcome = "SUCCEEDED" if job is not None else (str(receipts[-1].data["outcome"]) if receipts else "FAILED")
    return _ProgramExecutionResult(claim, outcome, job, receipts)


def _prepare_program_execution(
    store: SQLiteRuntimeStore, *, snapshot: ProgramExecutionSnapshot,
    program_transport_store: _transport._ProgramTransportStore,
    input_bytes: Mapping[str, bytes],
    scheduler_artifact_bytes: Mapping[str, bytes], driver: _transport._ProgramEffectDriver,
) -> _transport._PreparedProgramEffects:
    if type(store) is not SQLiteRuntimeStore:
        raise TransportBoundaryError("successor execution requires exact SQLiteRuntimeStore")
    try:
        snapshot._assert_current_core(store)
    except Exception as exc:
        raise TransportBoundaryError("successor snapshot/Core authority is not closed") from exc
    closed_driver = _transport._require_driver(driver)
    base = _snapshot_binding(snapshot, program_transport_store, closed_driver)
    material = _stage_material(
        snapshot, input_bytes=input_bytes,
        scheduler_artifact_bytes=scheduler_artifact_bytes,
    )
    prepared = _transport._prepare_program_effect_requests(base, material)
    prepared.assert_closed()
    return prepared


@_completion_owned
def _execute_claimed_program(
    store: SQLiteRuntimeStore, *, snapshot: ProgramExecutionSnapshot,
    program_transport_store: _transport._ProgramTransportStore,
    prepared: _transport._PreparedProgramEffects, driver: _transport._ProgramEffectDriver,
    claim: SubmissionIntentClaim,
    continuation: object = None,
    _completion_token: object = None,
) -> _ProgramExecutionResult:
    """Private continuation of execute_once; it cannot acquire a Core WINNER."""
    closed_driver = _transport._require_driver(driver)
    base = prepared.binding
    if claim is SubmissionIntentClaim.REPLAY:
        return _read_program_execution_result(store, snapshot=snapshot, program_transport_store=program_transport_store, driver=closed_driver, claim=claim, _completion_token=_completion_token)

    from .runtime import _consume_program_continuation
    try:
        _consume_program_continuation(continuation, store, snapshot, prepared)
    except Exception as exc:
        raise TransportBoundaryError("successor continuation requires the one-use Execution WINNER transfer") from exc
    if claim is not SubmissionIntentClaim.WINNER or store.attempt_state(snapshot.attempt_id) is not AttemptState.SUBMISSION_INTENT_RECORDED:
        raise TransportBoundaryError("program effects require the sole Execution WINNER")
    _assert_effect_intent_replay(store, snapshot)
    if _snapshot_binding(snapshot, program_transport_store, closed_driver, persist=True) != base:
        raise TransportBoundaryError("successor runtime changed after claim")

    current_operation = "ALLOCATE_WORKSPACE"
    current_request = prepared.allocate_request
    physical_recorded = False
    try:
        workspace_map = _transport._workspace_response(
            _invoke_program_driver(store, snapshot, program_transport_store, closed_driver.allocate_workspace, current_request),
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
                _invoke_program_driver(store, snapshot, program_transport_store,
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
        payloads = tuple(item for item in authorities if item["artifact_kind"] == "startup-payload")
        if len(schedulers) != 1 or len(program_inputs) != len(snapshot.program_execution_spec.exact_inputs) or len(payloads) != len(snapshot.scheduler_artifacts) - 1:
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
            startup_payload_artifact_authority_ids=tuple(str(item["artifact_authority_id"]) for item in payloads),
        )
        submit_map = _transport._submit_response(
            _invoke_program_driver(store, snapshot, program_transport_store, closed_driver.submit_qsub_once, current_request)
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
        _completion_checkpoint(snapshot, program_transport_store)
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
        _completion_checkpoint(snapshot, program_transport_store)
        store.record_submission_outcome(snapshot.attempt_id, snapshot.effect_intent_id, SubmissionOutcome.UNKNOWN)
        return _ProgramExecutionResult(
            claim, "UNKNOWN", None,
            _load_receipts(store, snapshot, program_transport_store, base),
        )


@_completion_owned
def _query_program_scheduler(
    store: SQLiteRuntimeStore, *, snapshot: ProgramExecutionSnapshot,
    program_transport_store: _transport._ProgramTransportStore,
    driver: _transport._ProgramEffectDriver,
    _completion_token: object = None,
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
            _invoke_program_driver(store, snapshot, program_transport_store, closed_driver.query_scheduler, request),
            str(job["job_id"]),
        )
    except Exception:
        response = {"reason": "ambiguous-scheduler-read"}
        _completion_checkpoint(snapshot, program_transport_store)
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


    _completion_checkpoint(snapshot, program_transport_store)
    program_transport_store.record_effect(
        binding=request["binding"], request=request,
        classification="SUCCEEDED", response=result,
    )
    _append_receipt(
        store, snapshot, program_transport_store=program_transport_store,
        current_binding=base, operation="QUERY_SCHEDULER",
        request=request, outcome="SUCCEEDED", response=result,
    )
    _apply_program_scheduler_disposition(store, snapshot, result, program_transport_store)
    return dict(result)


def _apply_program_scheduler_disposition(store: SQLiteRuntimeStore, snapshot: ProgramExecutionSnapshot, result: Mapping[str, object], program_transport_store=None) -> None:
    _completion_checkpoint(snapshot, program_transport_store)
    if _uses_completion_receipt(snapshot.program_execution_spec):
        if result["state"] == "running" and store.attempt_state(snapshot.attempt_id) is AttemptState.SUBMITTED:
            _completion_checkpoint(snapshot, program_transport_store)
            store.advance_attempt(snapshot.attempt_id, AttemptState.RUNNING)
        return
    disposition = None
    if result["state"] == "running":
        disposition = AttemptState.RUNNING
    elif result["state"] == "terminal" and type(result.get("exit_status")) is int:
        disposition = AttemptState.SUCCEEDED if result["exit_status"] == 0 else AttemptState.FAILED
    if disposition is not None:
        store.advance_attempt(snapshot.attempt_id, disposition)


@_completion_owned
def _reconcile_program_submission(
    store: SQLiteRuntimeStore, *, snapshot: ProgramExecutionSnapshot,
    program_transport_store: _transport._ProgramTransportStore,
    driver: _transport._ProgramEffectDriver,
    _completion_token: object = None,
) -> Mapping[str, object]:
    from auto_g16.transport._program_rtwin import _RTWinProgramEffectDriver
    if type(driver) is _RTWinProgramEffectDriver and driver._recovery_only:
        from . import _submission_recovery as recovery
        return recovery.reconcile(store, snapshot, program_transport_store, driver)
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
            _invoke_program_driver(store, snapshot, program_transport_store, closed_driver.reconcile_submission, request)
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
    _completion_checkpoint(snapshot, program_transport_store)
    state = store.reconcile_unknown(
        snapshot.attempt_id, receipt.observation_id, resolution
    )
    if state is AttemptState.SUBMITTED:
        _job_authority(
            store, snapshot, program_transport_store, closed_driver
        )
    return dict(response)


def _require_pre_capture_success(
    store: SQLiteRuntimeStore, snapshot: ProgramExecutionSnapshot,
    program_transport_store: _transport._ProgramTransportStore,
    base: Mapping[str, object], job: Mapping[str, object],
) -> None:
    if store.attempt_state(snapshot.attempt_id) is not AttemptState.SUCCEEDED:
        raise TransportBoundaryError("capture requires exact terminal success")
    receipts = _load_receipts(store, snapshot, program_transport_store, base)
    scheduler = tuple(item for item in receipts if item.data["operation"] == "QUERY_SCHEDULER")
    if not scheduler:
        raise TransportBoundaryError("capture requires a persisted scheduler success receipt")
    latest = scheduler[-1].data
    response = latest["response"]
    if latest["outcome"] != "SUCCEEDED" or response.get("job_id") != job["job_id"] or response.get("state") != "terminal" or type(response.get("exit_status")) is not int or response["exit_status"] != 0:
        raise TransportBoundaryError("capture requires same-job terminal exit status zero")


def _capture_program_outputs(
    store: SQLiteRuntimeStore, *, snapshot: ProgramExecutionSnapshot,
    program_transport_store: _transport._ProgramTransportStore,
    driver: _transport._ProgramEffectDriver,
) -> _transport._ProgramOutputCapture:
    if _uses_completion_receipt(snapshot.program_execution_spec):
        raise TransportBoundaryError("receipt mode requires the absence/evidence collector")
    closed_driver = _transport._require_driver(driver)
    base = _snapshot_binding(snapshot, program_transport_store, closed_driver)
    job = _job_authority(
        store, snapshot, program_transport_store, closed_driver
    )
    _require_pre_capture_success(store, snapshot, program_transport_store, base, job)
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
            _invoke_program_driver(store, snapshot, program_transport_store, closed_driver.stat_exact_file, stat_request),
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
            _invoke_program_driver(store, snapshot, program_transport_store, closed_driver.fetch_exact_file, fetch_request),
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


_COMPLETION_ASSESSMENT = "program-completion-assessment/1"
_COMPLETION_EVIDENCE = "program-completion-evidence/1"
_COMPLETION_BINDING_KEYS = ("attempt_id", "program_execution_snapshot_id", "effect_intent_id", "job_authority_id")
_COMPLETION_DIAGNOSTICS = frozenset({"evidence-conflict", "scheduler-active", "acquisition-unknown", "awaiting-absence", "receipt-missing", "receipt-invalid", "program-nonzero", "program-signaled", "output-incomplete", "output-invalid", "completed"})
_COMPLETION_ASSESSMENT_KEYS = frozenset({"schema", *_COMPLETION_BINDING_KEYS, "completion_mode", "epoch_id", "evidence_observation_ids", "evidence_result_id", "observation_prefix_sha256", "verdict", "diagnostic", "capture_authority_id", "receipt_sha256"})


class _CompletionIdentityConflict(TransportBoundaryError):
    """An acquired identity contradicts its exact predecessor."""


def _completion_context(store, snapshot, program_transport_store, driver):
    if not _uses_completion_receipt(snapshot.program_execution_spec):
        raise TransportBoundaryError("completion collector requires explicit receipt mode")
    base = _snapshot_binding(snapshot, program_transport_store, driver)
    receipts = _load_receipts(store, snapshot, program_transport_store, base)
    job = _reconstruct_job_authority_from_receipts(store, snapshot, program_transport_store, base, receipts)
    workspace = _reconstruct_workspace_authority(snapshot, program_transport_store, receipts)
    return base, receipts, job, workspace


def _completion_binding(snapshot, job):
    return {"attempt_id": snapshot.attempt_id, "program_execution_snapshot_id": snapshot.program_execution_snapshot_id, "effect_intent_id": snapshot.effect_intent_id, "job_authority_id": job["job_authority_id"]}


def _observation_prefix(observations):
    return semantic_sha256(tuple({"observation_id": item.observation_id, "attempt_id": item.attempt_id, "observation_type": item.observation_type, "data": item.data} for item in observations))


def _completion_epoch(snapshot, job, opening):
    return semantic_id("program-completion-epoch", {**_completion_binding(snapshot, job), "initial_absence_observation_id": opening.observation_id})


def _scheduler_diagnostic(observations, expected_exit=None):
    terminal = None
    accepted = False
    latest = None
    for observation in observations:
        data = observation.data
        if observation.observation_type == _COMPLETION_ASSESSMENT:
            if data.get("diagnostic") == "evidence-conflict":
                return "evidence-conflict"
            accepted |= data.get("verdict") in {"SUCCEEDED", "FAILED"}
        if observation.observation_type != _transport._RECEIPT_TYPE or data.get("operation") != "QUERY_SCHEDULER":
            continue
        response = data["response"]
        latest = response.get("state") if data["outcome"] == "SUCCEEDED" else "unknown"
        if latest == "terminal":
            code = response.get("exit_status")
            if type(code) is not int or (terminal is not None and terminal != code) or (expected_exit is not None and code != expected_exit):
                return "evidence-conflict"
            terminal = code
        if latest in {"queued", "running", "held", "exiting"} and (terminal is not None or accepted):
            return "evidence-conflict"
    if latest in {"queued", "running", "held", "exiting"}:
        return "scheduler-active"
    if latest == "terminal":
        return "awaiting-absence"
    if latest != "absent":
        return "acquisition-unknown"
    return None


def _completion_inputs(snapshot, receipts, input_bytes):
    declarations = snapshot.program_execution_spec.exact_inputs
    if not isinstance(input_bytes, Mapping) or set(input_bytes) != {item["portable_name"] for item in declarations}:
        raise _completion._CompletionValueError("missing input bytes")
    members = []
    for declaration in declarations:
        name = declaration["portable_name"]
        content = input_bytes[name]
        if type(content) is not bytes or len(content) > 64 * 1024 * 1024 or len(content) != declaration["size_bytes"] or sha256(content).hexdigest() != declaration["sha256"]:
            raise _completion._CompletionValueError("input bytes differ")
        matches = [item for item in receipts if item.data["operation"] == "STAGE_EXACT_FILE" and item.data["outcome"] == "SUCCEEDED" and item.data["request"]["payload"].get("artifact_kind") == "program-input" and all(item.data["request"]["payload"].get(key) == value for key, value in declaration.items())]
        if len(matches) != 1:
            raise TransportBoundaryError("input STAGE provenance is not unique")
        members.append({**declaration, "content_base64": _completion.base64.b64encode(content).decode("ascii"), "stage_observation_id": matches[0].observation_id})
    return tuple(members)


def _completion_file_effect(store, snapshot, program_transport_store, driver, base, job, declaration, stat=None):
    name = str(declaration["portable_name"])
    if stat is None:
        request = _transport._stat_request(base, job_authority_id=str(job["job_authority_id"]), declaration=declaration)
        response, _size = _transport._stat_response(_invoke_program_driver(store, snapshot, program_transport_store, driver.stat_exact_file, request), name=name, max_size_bytes=declaration["max_size_bytes"])
        content = None
    else:
        size = stat.data["response"]["size_bytes"]
        token = str(stat.data["response"]["file_physical_token"])
        request = _transport._fetch_request(base, job_authority_id=str(job["job_authority_id"]), declaration=declaration, announced_size=size, file_physical_token=token, stat_receipt_id=stat.observation_id)
        acquired = _invoke_program_driver(store, snapshot, program_transport_store, driver.fetch_exact_file, request)
        if isinstance(acquired, Mapping) and (("file_physical_token" in acquired and acquired["file_physical_token"] != token) or (type(acquired.get("content")) is bytes and acquired.get("sha256") != sha256(acquired["content"]).hexdigest())):
            raise _CompletionIdentityConflict("fetched identity contradicts its predecessor")
        _response, content, digest, size = _transport._fetch_response(acquired, name=name, token=token, announced_size=size, max_size_bytes=declaration["max_size_bytes"])
        response = {"portable_name": name, "sha256": digest, "size_bytes": size, "file_physical_token": token}
    _completion_checkpoint(snapshot, program_transport_store)
    program_transport_store.record_effect(binding=request["binding"], request=request, classification="SUCCEEDED", response=response)
    observation = _append_receipt(store, snapshot, program_transport_store=program_transport_store, current_binding=base, operation=request["operation"], request=request, outcome="SUCCEEDED", response=response)
    return observation, content


def _interrupted_present_stat(snapshot, observations, receipts):
    """Select the sole collection-owned present STAT without a FETCH consumer."""
    positions = {item.observation_id: index for index, item in enumerate(observations)}
    starts = [
        positions[item.observation_id]
        for item in observations
        if item.observation_type == _COLLECTION_START
    ]
    if not starts:
        return None
    first_start = min(starts)
    consumed = set()
    malformed = False
    for item in receipts:
        if item.data["operation"] != "FETCH_EXACT_FILE":
            continue
        request = item.data.get("request")
        payload = request.get("payload") if isinstance(request, Mapping) else None
        stat_id = payload.get("stat_receipt_id") if isinstance(payload, Mapping) else None
        if type(stat_id) is not str or not stat_id:
            malformed = True
        elif item.data["outcome"] == "SUCCEEDED":
            consumed.add(stat_id)
        else:
            malformed = True
    candidates = []
    for item in receipts:
        if (
            item.data["operation"] != "STAT_EXACT_FILE"
            or item.data["outcome"] != "SUCCEEDED"
            or positions.get(item.observation_id, -1) <= first_start
            or item.observation_id in consumed
        ):
            continue
        request = item.data.get("request")
        payload = request.get("payload") if isinstance(request, Mapping) else None
        response = item.data.get("response")
        if not isinstance(payload, Mapping) or not isinstance(response, Mapping):
            malformed = True
            continue
        try:
            declaration = _declared_output(snapshot, payload)
            closed, size = _transport._stat_response(
                response,
                name=str(declaration["portable_name"]),
                max_size_bytes=int(declaration["max_size_bytes"]),
            )
        except Exception:
            malformed = True
            continue
        if size is None or closed["presence"] != "present":
            continue
        candidates.append(item)
    if malformed or len(candidates) > 1:
        raise TransportBoundaryError(
            "interrupted collection prefix is malformed or ambiguous"
        )
    return candidates[0] if candidates else None


def _repair_interrupted_completion_prefix(
    store, snapshot, program_transport_store, driver, base, job
):
    """Finish one exact abandoned STAT/FETCH pair before a clean new epoch."""
    observations = store.observations_for_attempt(snapshot.attempt_id)
    receipts = _load_receipts(store, snapshot, program_transport_store, base)
    stat = _interrupted_present_stat(snapshot, observations, receipts)
    if stat is None:
        return
    request = stat.data["request"]
    assert isinstance(request, Mapping)
    declaration = _declared_output(snapshot, request["payload"])
    _receipt, content = _completion_file_effect(
        store,
        snapshot,
        program_transport_store,
        driver,
        base,
        job,
        declaration,
        stat=stat,
    )
    if type(content) is not bytes:
        raise TransportBoundaryError("interrupted collection repair returned no bytes")


def _validate_completion_bundle(record, snapshot, job, workspace, receipts, observations):
    data = _completion._closed(record.data, frozenset({"schema", *_COMPLETION_BINDING_KEYS, "epoch_id", "inputs", "captured_files"}), "completion bundle")
    if record.result_type != _COMPLETION_EVIDENCE or record.attempt_id != snapshot.attempt_id or data["schema"] != _COMPLETION_EVIDENCE or record.result_id != semantic_id("program-completion-evidence", data) or any(data[key] != value for key, value in _completion_binding(snapshot, job).items()):
        raise TransportBoundaryError("completion bundle identity differs")
    if len(_completion._receipt_json(data)) > 384 * 1024 * 1024:
        raise TransportBoundaryError("completion evidence bundle exceeds cap")
    by_id = {item.observation_id: item for item in receipts}
    positions = {item.observation_id: index for index, item in enumerate(observations)}
    openings = [item for item in receipts if item.data["operation"] == "QUERY_SCHEDULER" and item.data["outcome"] == "SUCCEEDED" and item.data["response"]["state"] == "absent" and _completion_epoch(snapshot, job, item) == data["epoch_id"]]
    if len(openings) != 1:
        raise TransportBoundaryError("completion epoch opening is not unique")
    opening = openings[0]
    specs = snapshot.program_execution_spec.exact_inputs
    if not isinstance(data["inputs"], tuple) or len(data["inputs"]) != len(specs):
        raise TransportBoundaryError("completion input inventory differs")
    input_bytes = {}
    for member, declaration in zip(data["inputs"], specs):
        _completion._closed(member, _completion._INPUT_FIELDS | {"content_base64", "stage_observation_id"}, "captured input")
        _completion._integer(member["size_bytes"], 1, 64 * 1024 * 1024, "captured input size")
        if any(member[key] != value for key, value in declaration.items()):
            raise TransportBoundaryError("captured input identity differs")
        input_bytes[declaration["portable_name"]] = _completion._unbase64(member["content_base64"], 64 * 1024 * 1024)
        if member["stage_observation_id"] not in positions or positions[member["stage_observation_id"]] >= positions[opening.observation_id]:
            raise TransportBoundaryError("captured input STAGE order differs")
    if freeze_mapping({"inputs": _completion_inputs(snapshot, receipts, input_bytes)}, "inputs")["inputs"] != data["inputs"]:
        raise TransportBoundaryError("captured input STAGE source differs")
    declarations = (_completion._METADATA_DECLARATION, *snapshot.program_execution_spec.required_outputs, *snapshot.program_execution_spec.optional_outputs)
    files = data["captured_files"]
    if not isinstance(files, tuple) or len(files) != len(declarations):
        raise TransportBoundaryError("captured file inventory differs")
    seen = []
    restats = []
    content_map = {}
    artifacts = []
    for index, (member, declaration) in enumerate(zip(files, declarations)):
        _completion._closed(member, _completion._OUTPUT_FIELDS | {"content_base64", "stat_observation_id", "fetch_observation_id", "restat_observation_id"}, "captured file")
        if any(member[key] != declaration[key] for key in ("logical_role", "portable_name", "format")):
            raise TransportBoundaryError("captured file declaration differs")
        first, last = (by_id.get(member[key]) for key in ("stat_observation_id", "restat_observation_id"))
        if first is None or last is None or any(item.data["operation"] != "STAT_EXACT_FILE" or item.data["outcome"] != "SUCCEEDED" for item in (first, last)):
            raise TransportBoundaryError("captured STAT sources are missing")
        if first.data["request"]["payload"] != last.data["request"]["payload"] or first.data["response"] != last.data["response"] or first.data["response"]["portable_name"] != member["portable_name"] or first.data["response"]["presence"] != member["presence"]:
            raise TransportBoundaryError("captured file drifted across STAT")
        seen.append(first.observation_id)
        restats.append(last.observation_id)
        if member["presence"] == "absent":
            if index == 0 or any(member[key] is not None for key in ("size_bytes", "sha256", "content_base64", "fetch_observation_id")):
                raise TransportBoundaryError("absent captured file carries bytes or is receipt")
            content = None
        elif member["presence"] == "present":
            _completion._integer(member["size_bytes"], 0, min(declaration["max_size_bytes"], 64 * 1024 * 1024), "captured file size")
            _completion.require_sha256(member["sha256"], "captured file digest")
            content = _completion._unbase64(member["content_base64"], min(declaration["max_size_bytes"], 64 * 1024 * 1024))
            fetch = by_id.get(member["fetch_observation_id"])
            if fetch is None or fetch.data["operation"] != "FETCH_EXACT_FILE" or fetch.data["outcome"] != "SUCCEEDED" or fetch.data["request"]["payload"]["stat_receipt_id"] != first.observation_id:
                raise TransportBoundaryError("captured FETCH source differs")
            response = fetch.data["response"]
            if len(content) != member["size_bytes"] or sha256(content).hexdigest() != member["sha256"] or any(response[key] != member[key] for key in ("portable_name", "size_bytes", "sha256")) or response["file_physical_token"] != first.data["response"]["file_physical_token"] or response["size_bytes"] != first.data["response"]["size_bytes"]:
                raise TransportBoundaryError("captured bytes differ from persisted FETCH")
            seen.append(fetch.observation_id)
        else:
            raise TransportBoundaryError("captured file presence is invalid")
        content_map[member["portable_name"]] = content
        if index:
            artifacts.append(_transport._ProgramOutputArtifact(str(member["logical_role"]), str(member["portable_name"]), str(member["format"]), str(member["presence"]), member["sha256"], member["size_bytes"], snapshot.program_execution_snapshot_id, snapshot.effect_intent_id, str(job["job_authority_id"]), member["fetch_observation_id"], content))
    ordered = [opening.observation_id, *seen, *restats]
    if len(set(ordered)) != len(ordered) or [positions[item] for item in ordered] != sorted(positions[item] for item in ordered):
        raise TransportBoundaryError("captured evidence order is not exact")
    closing_candidates = [item for item in receipts if item.data["operation"] == "QUERY_SCHEDULER" and positions[item.observation_id] > positions[restats[-1]]]
    if not closing_candidates:
        raise TransportBoundaryError("missing final absence")
    closing = closing_candidates[0]
    if closing.data["outcome"] != "SUCCEEDED" or closing.data["response"]["state"] != "absent":
        raise TransportBoundaryError("final observation is not exact absence")
    ordered.append(closing.observation_id)
    actual = [item.observation_id for item in receipts if positions[opening.observation_id] <= positions[item.observation_id] <= positions[closing.observation_id]]
    if actual != ordered:
        raise TransportBoundaryError("foreign or interleaved completion epoch evidence")
    raw = content_map.pop("v31-completion.json")
    receipt = _completion._bound_receipt(raw, snapshot, str(job["job_id"]), str(workspace["workspace_physical_token"]))
    if receipt["outputs"] != tuple(freeze_mapping({key: member[key] for key in _completion._OUTPUT_FIELDS}, "captured metadata") for member in files[1:]):
        raise TransportBoundaryError("receipt outputs differ from captured outputs")
    # Later physical observations cannot reuse an older capture after drift.
    for later in receipts:
        if positions[later.observation_id] <= positions[closing.observation_id] or later.data["operation"] not in {"STAT_EXACT_FILE", "FETCH_EXACT_FILE"}:
            continue
        member = next((item for item in files if item["portable_name"] == later.data["request"]["payload"].get("portable_name")), None)
        if later.data["outcome"] != "SUCCEEDED" or member is None:
            raise TransportBoundaryError("later capture evidence is unknown")
        predecessor = by_id[member["restat_observation_id"] if later.data["operation"] == "STAT_EXACT_FILE" else member["fetch_observation_id"]] if later.data["operation"] == "STAT_EXACT_FILE" or member["fetch_observation_id"] is not None else None
        if predecessor is None or later.data["response"] != predecessor.data["response"]:
            raise TransportBoundaryError("later captured file identity changed")
    payload = {"program_execution_snapshot_id": snapshot.program_execution_snapshot_id, "effect_intent_id": snapshot.effect_intent_id, "job_authority_id": job["job_authority_id"], "artifacts": tuple(item.identity_payload() for item in artifacts)}
    capture = _transport._ProgramOutputCapture(_transport._identity("output-capture", payload), snapshot.program_execution_snapshot_id, snapshot.effect_intent_id, str(job["job_authority_id"]), tuple(artifacts))
    term = receipt["termination"]
    code = term["returncode"] if term["kind"] == "exited" else 128 + term["signal"]
    diagnostic = _scheduler_diagnostic(observations, code)
    if diagnostic is None:
        diagnostic = "program-signaled" if term["kind"] == "signaled" else "program-nonzero" if code else (_completion._crest._output_closure(next(iter(input_bytes.values())), content_map) if snapshot.program_execution_spec.program_kind == "crest" else _completion._output_closure(str(snapshot.program_execution_spec.program_data["task"]), next(iter(input_bytes.values())), content_map)) or "completed"
    return diagnostic, capture, sha256(raw).hexdigest(), opening.observation_id, closing.observation_id


def _completion_verdict(diagnostic):
    if diagnostic == "completed":
        return "SUCCEEDED"
    if diagnostic in {"program-nonzero", "program-signaled", "output-incomplete", "output-invalid"}:
        return "FAILED"
    return "UNKNOWN"


def _verify_completion_assessments(observations, snapshot, job):
    for index, item in enumerate(observations):
        if item.observation_type != _COMPLETION_ASSESSMENT:
            continue
        data = _completion._closed(item.data, _COMPLETION_ASSESSMENT_KEYS, "completion assessment")
        prefix = observations[:index]
        ids = tuple(member.observation_id for member in prefix)
        selected = data["evidence_observation_ids"]
        expected_ids = tuple(member.observation_id for member in prefix if member.observation_type == _transport._RECEIPT_TYPE)
        if selected != expected_ids:
            raise TransportBoundaryError("completion assessment omits exact evidence sources")
        _completion.require_sha256(data["observation_prefix_sha256"], "completion prefix digest")
        for key in ("epoch_id", "evidence_result_id", "capture_authority_id"):
            if data[key] is not None:
                _completion.require_text(data[key], key)
        if data["receipt_sha256"] is not None:
            _completion.require_sha256(data["receipt_sha256"], "completion receipt digest")
        if data["schema"] != _COMPLETION_ASSESSMENT or data["completion_mode"] != _completion._MODE or any(data[key] != value for key, value in _completion_binding(snapshot, job).items()) or item.observation_id != semantic_id("program-completion-assessment", data) or data["observation_prefix_sha256"] != _observation_prefix(prefix) or not isinstance(selected, tuple) or len(set(selected)) != len(selected) or any(key not in ids for key in selected) or tuple(key for key in ids if key in selected) != selected or data["diagnostic"] not in _COMPLETION_DIAGNOSTICS or data["verdict"] != _completion_verdict(data["diagnostic"]):
            raise TransportBoundaryError("completion assessment or prefix is corrupt")
        if data["verdict"] != "UNKNOWN" and any(data[key] is None for key in ("epoch_id", "evidence_result_id", "capture_authority_id", "receipt_sha256")):
            raise TransportBoundaryError("terminal completion assessment lacks captured provenance")


def _persist_completion_assessment(store, snapshot, program_transport_store, base, job, diagnostic, *, driver=None, epoch_id=None, record=None, capture=None, receipt_sha256=None):
    observations = store.observations_for_attempt(snapshot.attempt_id)
    receipts = _load_receipts(store, snapshot, program_transport_store, base)
    _verify_completion_assessments(observations, snapshot, job)
    if diagnostic != "evidence-conflict":
        workspace = _reconstruct_workspace_authority(snapshot, program_transport_store, receipts)
        try:
            _validate_completion_history(store, snapshot, job, workspace, receipts, observations)
        except Exception:
            diagnostic, record, capture, receipt_sha256 = "evidence-conflict", None, None, None
    data = freeze_mapping({
        "schema": _COMPLETION_ASSESSMENT, **_completion_binding(snapshot, job),
        "completion_mode": _completion._MODE, "epoch_id": epoch_id,
        "evidence_observation_ids": tuple(item.observation_id for item in receipts),
        "evidence_result_id": record.result_id if record else None,
        "observation_prefix_sha256": _observation_prefix(observations),
        "verdict": _completion_verdict(diagnostic), "diagnostic": diagnostic,
        "capture_authority_id": capture.capture_authority_id if capture else None,
        "receipt_sha256": receipt_sha256,
    }, "completion assessment")
    assessment = Observation(observation_id=semantic_id("program-completion-assessment", data), attempt_id=snapshot.attempt_id, observation_type=_COMPLETION_ASSESSMENT, data=data)
    _publisher_completion_checkpoint(snapshot, driver)
    _completion_checkpoint(snapshot, program_transport_store)
    store.append_observation(assessment)
    current = store.observations_for_attempt(snapshot.attempt_id)
    if current != (*observations, assessment):
        raise TransportBoundaryError("completion prefix changed during persistence")
    _verify_completion_assessments(current, snapshot, job)
    _advance_completion(store, snapshot, assessment, program_transport_store, driver)
    return assessment


def _advance_completion(store, snapshot, assessment, program_transport_store, driver=None):
    _publisher_completion_checkpoint(snapshot, driver)
    _completion_checkpoint(snapshot, program_transport_store)
    if assessment.data["verdict"] == "UNKNOWN":
        return
    expected = AttemptState[assessment.data["verdict"]]
    current = store.attempt_state(snapshot.attempt_id)
    if current in {AttemptState.SUBMITTED, AttemptState.RUNNING}:
        _publisher_completion_checkpoint(snapshot, driver)
        _completion_checkpoint(snapshot, program_transport_store)
        store.advance_attempt(snapshot.attempt_id, expected)
    elif current is not expected:
        raise TransportBoundaryError("completion cannot replace an earlier terminal state")


def _completion_stored_record(store, snapshot, result_id):
    matches = [item for item in store.results_for_attempt(snapshot.attempt_id) if item.result_id == result_id]
    if len(matches) != 1:
        raise TransportBoundaryError("completion durable bytes are missing")
    return matches[0]


def _validate_completion_history(store, snapshot, job, workspace, receipts, observations):
    """An intervening UNKNOWN or a new epoch cannot discard accepted bytes."""
    for accepted in observations:
        if accepted.observation_type != _COMPLETION_ASSESSMENT or accepted.data["verdict"] == "UNKNOWN":
            continue
        prefix = observations[:observations.index(accepted)]
        original = _completion_stored_record(store, snapshot, accepted.data["evidence_result_id"])
        original_receipts = tuple(item for item in receipts if item in prefix)
        diagnostic, capture, digest, _a, _b = _validate_completion_bundle(original, snapshot, job, workspace, original_receipts, prefix)
        if (diagnostic, capture.capture_authority_id, digest, original.data["epoch_id"]) != (accepted.data["diagnostic"], accepted.data["capture_authority_id"], accepted.data["receipt_sha256"], accepted.data["epoch_id"]):
            raise TransportBoundaryError("saved assessment differs from source evidence")
        current, _capture, _digest, _a, _b = _validate_completion_bundle(original, snapshot, job, workspace, receipts, observations)
        if current == "evidence-conflict":
            raise TransportBoundaryError("accepted completion history was contradicted")


@_completion_owned
def _collect_program_completion(store, *, snapshot, program_transport_store, driver, input_bytes, _completion_token=None):
    """One explicitly requested absence epoch. No polling or automatic retry."""
    base, receipts, job, workspace = _completion_context(store, snapshot, program_transport_store, driver)
    observations = store.observations_for_attempt(snapshot.attempt_id)
    _verify_completion_assessments(observations, snapshot, job)
    # Previously accepted/conflicting evidence must be re-attested before new reads.
    if any(item.observation_type == _COMPLETION_ASSESSMENT and item.data["verdict"] != "UNKNOWN" for item in observations):
        prior = _replay_program_completion(store, snapshot=snapshot, program_transport_store=program_transport_store, driver=driver, _completion_token=_completion_token)
        if prior.data["diagnostic"] == "evidence-conflict":
            return prior
    try:
        inputs = _completion_inputs(snapshot, receipts, input_bytes)
    except _completion._CompletionValueError:
        missing = not isinstance(input_bytes, Mapping) or any(item["portable_name"] not in input_bytes for item in snapshot.program_execution_spec.exact_inputs)
        return _persist_completion_assessment(store, snapshot, program_transport_store, base, job, "acquisition-unknown" if missing else "evidence-conflict", driver=driver)
    _query_program_scheduler(store, snapshot=snapshot, program_transport_store=program_transport_store, driver=driver, _completion_token=_completion_token)
    observations = store.observations_for_attempt(snapshot.attempt_id)
    diagnostic = _scheduler_diagnostic(observations)
    if diagnostic:
        return _persist_completion_assessment(store, snapshot, program_transport_store, base, job, diagnostic, driver=driver)
    receipts = _load_receipts(store, snapshot, program_transport_store, base)
    opening = receipts[-1]
    epoch_id = _completion_epoch(snapshot, job, opening)
    files = []
    declarations = (_completion._METADATA_DECLARATION, *snapshot.program_execution_spec.required_outputs, *snapshot.program_execution_spec.optional_outputs)
    try:
        for index, declaration in enumerate(declarations):
            stat, _ = _completion_file_effect(store, snapshot, program_transport_store, driver, base, job, declaration)
            member = {key: declaration[key] for key in ("logical_role", "portable_name", "format")}
            member.update(presence=stat.data["response"]["presence"], size_bytes=None, sha256=None, content_base64=None, stat_observation_id=stat.observation_id, fetch_observation_id=None, restat_observation_id=None)
            if member["presence"] == "absent":
                if index == 0:
                    return _persist_completion_assessment(store, snapshot, program_transport_store, base, job, "receipt-missing", driver=driver, epoch_id=epoch_id)
            else:
                fetch, content = _completion_file_effect(store, snapshot, program_transport_store, driver, base, job, declaration, stat=stat)
                member.update(size_bytes=len(content), sha256=sha256(content).hexdigest(), content_base64=_completion.base64.b64encode(content).decode("ascii"), fetch_observation_id=fetch.observation_id)
                if index == 0:
                    try:
                        trusted_receipt = _completion._bound_receipt(content, snapshot, str(job["job_id"]), str(workspace["workspace_physical_token"]))
                    except _completion._CompletionValueError:
                        return _persist_completion_assessment(store, snapshot, program_transport_store, base, job, "receipt-invalid", driver=driver, epoch_id=epoch_id)
            files.append(member)
        for member, declaration in zip(files, declarations):
            restat, _ = _completion_file_effect(store, snapshot, program_transport_store, driver, base, job, declaration)
            member["restat_observation_id"] = restat.observation_id
    except _CompletionIdentityConflict:
        return _persist_completion_assessment(store, snapshot, program_transport_store, base, job, "evidence-conflict", driver=driver, epoch_id=epoch_id)
    except Exception:
        return _persist_completion_assessment(store, snapshot, program_transport_store, base, job, "acquisition-unknown", driver=driver, epoch_id=epoch_id)
    _query_program_scheduler(store, snapshot=snapshot, program_transport_store=program_transport_store, driver=driver, _completion_token=_completion_token)
    observations = store.observations_for_attempt(snapshot.attempt_id)
    receipts = _load_receipts(store, snapshot, program_transport_store, base)
    term = trusted_receipt["termination"]
    expected_exit = term["returncode"] if term["kind"] == "exited" else 128 + term["signal"]
    diagnostic = _scheduler_diagnostic(observations, expected_exit)
    # Identity conflicts take priority even if the closing query is active/unknown.
    by_id = {item.observation_id: item for item in receipts}
    if any(by_id[item["stat_observation_id"]].data["response"] != by_id[item["restat_observation_id"]].data["response"] for item in files):
        diagnostic = "evidence-conflict"
    if diagnostic:
        return _persist_completion_assessment(store, snapshot, program_transport_store, base, job, diagnostic, driver=driver, epoch_id=epoch_id)
    data = freeze_mapping({"schema": _COMPLETION_EVIDENCE, **_completion_binding(snapshot, job), "epoch_id": epoch_id, "inputs": inputs, "captured_files": tuple(files)}, "completion evidence")
    record = Result(result_id=semantic_id("program-completion-evidence", data), attempt_id=snapshot.attempt_id, result_type=_COMPLETION_EVIDENCE, data=data)
    try:
        diagnostic, capture, receipt_digest, _opening, _closing = _validate_completion_bundle(record, snapshot, job, workspace, receipts, observations)
        _publisher_completion_checkpoint(snapshot, driver)
        _completion_checkpoint(snapshot, program_transport_store)
        store.append_result(record)
        persisted = _completion_stored_record(store, snapshot, record.result_id)
        if persisted != record:
            raise TransportBoundaryError("stored completion bytes differ")
        diagnostic, capture, receipt_digest, _opening, _closing = _validate_completion_bundle(persisted, snapshot, job, workspace, receipts, observations)
    except Exception:
        return _persist_completion_assessment(store, snapshot, program_transport_store, base, job, "evidence-conflict", driver=driver, epoch_id=epoch_id)
    return _persist_completion_assessment(store, snapshot, program_transport_store, base, job, diagnostic, driver=driver, epoch_id=epoch_id, record=persisted, capture=capture, receipt_sha256=receipt_digest)


def _completion_replay_selection(store, snapshot, observations):
    """Shared non-mutating selection; never probe via write-capable replay."""
    assessments = [item for item in observations if item.observation_type == _COMPLETION_ASSESSMENT]
    latest = assessments[-1] if assessments else None
    records = [item for item in store.results_for_attempt(snapshot.attempt_id) if item.result_type == _COMPLETION_EVIDENCE]
    result_id = latest.data["evidence_result_id"] if latest else (records[-1].result_id if records else None)
    referenced = {item.data["evidence_result_id"] for item in assessments}
    positions = {item.observation_id: index for index, item in enumerate(observations)}
    unassessed = [record for record in records if record.result_id not in referenced and any(positions.get(member.get("restat_observation_id"), -1) > (positions[latest.observation_id] if latest else -1) for member in record.data.get("captured_files", ()) if isinstance(member, Mapping))]
    if len(unassessed) > 1:
        raise TransportBoundaryError("multiple unassessed completion bundles")
    return latest, unassessed[0].result_id if unassessed else result_id


_COLLECTION_START = "auto-g16-v31-collection-start/1"
_COLLECTION_START_KEYS = {"schema", "continuation_sha256", "attempt_id", "program_execution_snapshot_id", "effect_intent_id", "job_id", "collector_source_sha256", "observation_prefix_sha256"}


def _validate_collection_audits(observations, snapshot, job, continuation_sha256, collector_source_sha256):
    seen = set()
    for index, record in enumerate(observations):
        if record.observation_type != _COLLECTION_START:
            continue
        data = _transport._exact_keys(record.data, _COLLECTION_START_KEYS, "collection audit")
        for field in ("continuation_sha256", "collector_source_sha256", "observation_prefix_sha256"):
            _completion.require_sha256(data[field], field)
        expected = {"schema": _COLLECTION_START, "attempt_id": snapshot.attempt_id,
                    "program_execution_snapshot_id": snapshot.program_execution_snapshot_id,
                    "effect_intent_id": snapshot.effect_intent_id, "job_id": job["job_id"],
                    "observation_prefix_sha256": _observation_prefix(observations[:index])}
        if record.attempt_id != snapshot.attempt_id or any(data[k] != v for k, v in expected.items()) or record.observation_id != semantic_id("program-collection-continuation-start", data) or data["continuation_sha256"] in seen:
            raise TransportBoundaryError("collection audit/history is conflicting")
        if data["continuation_sha256"] == continuation_sha256 and data["collector_source_sha256"] != collector_source_sha256:
            raise TransportBoundaryError("collection audit source differs")
        seen.add(data["continuation_sha256"])
    return continuation_sha256 in seen


def _resume_program_collection(store, *, snapshot, program_transport_store, driver, input_bytes,
                               continuation, continuation_sha256, checkpoint, _completion_token):
    """Bounded Controller composition, reusing the original collector and reducer."""
    program_transport_store._require_completion_guard(_completion_token)
    if _COLLECTION_CHECKPOINT.get() is not None:
        raise TransportBoundaryError("nested collection recovery is forbidden")
    history = {}
    def checked_checkpoint():
        checkpoint()
        if history:
            current = store.observations_for_attempt(snapshot.attempt_id)
            previous = history["observations"]
            if current[:len(previous)] != previous:
                raise TransportBoundaryError("collection observation prefix changed")
            audits = tuple(record for record in current if record.observation_type == _COLLECTION_START)
            if audits != history["audits"]:
                raise TransportBoundaryError("collection audit history changed")
            _validate_collection_audits(current, snapshot, history["job"], continuation_sha256, history["source"])
            history["observations"] = current
    scope = _COLLECTION_CHECKPOINT.set((snapshot, program_transport_store, checked_checkpoint))
    try:
        _completion_checkpoint(snapshot, program_transport_store)
        base, receipts, job, workspace = _completion_context(store, snapshot, program_transport_store, driver)
        recovered = (continuation["schema"] == "auto-g16-v31-exact-job-recovery-continuation/1"
                     and job["establishing_operation"] == "RECONCILE_SUBMISSION"
                     and any(r.data["operation"] == "RECONCILE_SUBMISSION" and r.data["outcome"] == "SUCCEEDED"
                             and r.data["response"].get("schema") == "v31-exact-observed-job-reconciliation-proof/1" for r in receipts))
        if (job["establishing_operation"] != "SUBMIT_QSUB_ONCE" and not recovered) or job["job_id"] != continuation["original"]["job_id"]:
            raise TransportBoundaryError("collection requires the original successful submission")
        observations = store.observations_for_attempt(snapshot.attempt_id)
        _verify_completion_assessments(observations, snapshot, job)
        source_digest = semantic_sha256(freeze_mapping(continuation["collector_source"], "collector source"))
        consumed = _validate_collection_audits(observations, snapshot, job, continuation_sha256, source_digest)
        history.update(observations=observations, audits=tuple(record for record in observations if record.observation_type == _COLLECTION_START), job=job, source=source_digest)
        _validate_completion_history(store, snapshot, job, workspace, receipts, observations)
        _latest, result_id = _completion_replay_selection(store, snapshot, observations)
        if result_id is not None:
            record = _completion_stored_record(store, snapshot, result_id)
            diagnostic, _capture, _digest, _opening, _closing = _validate_completion_bundle(record, snapshot, job, workspace, receipts, observations)
            if diagnostic == "evidence-conflict":
                raise TransportBoundaryError("collection bundle is contradictory")
            return _replay_program_completion(store, snapshot=snapshot, program_transport_store=program_transport_store, driver=driver, _completion_token=_completion_token)
        if store.attempt_state(snapshot.attempt_id) not in {AttemptState.SUBMITTED, AttemptState.RUNNING}:
            raise TransportBoundaryError("terminal collection replay lacks a native bundle")
        if consumed:
            raise TransportBoundaryError("collection epoch already consumed; local bundle incomplete")
        _completion_inputs(snapshot, receipts, input_bytes)
        data = freeze_mapping({"schema": _COLLECTION_START, "continuation_sha256": continuation_sha256,
                               "attempt_id": snapshot.attempt_id, "program_execution_snapshot_id": snapshot.program_execution_snapshot_id,
                               "effect_intent_id": snapshot.effect_intent_id, "job_id": job["job_id"],
                               "collector_source_sha256": source_digest, "observation_prefix_sha256": _observation_prefix(observations)}, "collection start")
        audit = Observation(observation_id=semantic_id("program-collection-continuation-start", data),
                            attempt_id=snapshot.attempt_id, observation_type=_COLLECTION_START, data=data)
        _completion_checkpoint(snapshot, program_transport_store)
        store.append_observation(audit)
        current = store.observations_for_attempt(snapshot.attempt_id)
        if current != (*observations, audit):
            raise TransportBoundaryError("collection audit prefix changed")
        _validate_collection_audits(current, snapshot, job, continuation_sha256, source_digest)
        history.update(observations=current, audits=(*history["audits"], audit))
        _repair_interrupted_completion_prefix(
            store, snapshot, program_transport_store, driver, base, job
        )
        return _collect_program_completion(store, snapshot=snapshot, program_transport_store=program_transport_store,
                                           driver=driver, input_bytes=input_bytes, _completion_token=_completion_token)
    finally:
        _COLLECTION_CHECKPOINT.reset(scope)


@_completion_owned
def _replay_program_completion(store, *, snapshot, program_transport_store, driver, _completion_token=None):
    """Reclose local persisted bytes only; never recollect or call a driver."""
    base, receipts, job, workspace = _completion_context(store, snapshot, program_transport_store, driver)
    observations = store.observations_for_attempt(snapshot.attempt_id)
    _verify_completion_assessments(observations, snapshot, job)
    assessments = [item for item in observations if item.observation_type == _COMPLETION_ASSESSMENT]
    latest = assessments[-1] if assessments else None
    try:
        _validate_completion_history(store, snapshot, job, workspace, receipts, observations)
    except Exception:
        if latest is not None and observations[-1] == latest and latest.data["diagnostic"] == "evidence-conflict":
            return latest
        return _persist_completion_assessment(store, snapshot, program_transport_store, base, job, "evidence-conflict", driver=driver)
    try:
        latest, result_id = _completion_replay_selection(store, snapshot, observations)
    except TransportBoundaryError:
        return _persist_completion_assessment(store, snapshot, program_transport_store, base, job, "evidence-conflict", driver=driver)
    if result_id is None:
        if latest is not None and observations[-1] == latest:
            return latest
        return _persist_completion_assessment(store, snapshot, program_transport_store, base, job, _scheduler_diagnostic(observations) or "acquisition-unknown", driver=driver)
    try:
        record = _completion_stored_record(store, snapshot, result_id)
        diagnostic, capture, receipt_digest, opening, closing = _validate_completion_bundle(record, snapshot, job, workspace, receipts, observations)
        if latest is not None and observations[-1] == latest and (diagnostic, capture.capture_authority_id, receipt_digest, record.data["epoch_id"]) == (latest.data["diagnostic"], latest.data["capture_authority_id"], latest.data["receipt_sha256"], latest.data["epoch_id"]):
            _advance_completion(store, snapshot, latest, program_transport_store, driver)
            return latest
    except Exception:
        return _persist_completion_assessment(store, snapshot, program_transport_store, base, job, "evidence-conflict", driver=driver)
    return _persist_completion_assessment(store, snapshot, program_transport_store, base, job, diagnostic, driver=driver, epoch_id=record.data["epoch_id"], record=record, capture=capture, receipt_sha256=receipt_digest)


@_completion_owned
def _assert_program_receipt_success_authority(store, *, snapshot, program_transport_store, driver, _completion_token=None):
    assessment = _replay_program_completion(store, snapshot=snapshot, program_transport_store=program_transport_store, driver=driver, _completion_token=_completion_token)
    if assessment.data["verdict"] != "SUCCEEDED" or store.attempt_state(snapshot.attempt_id) is not AttemptState.SUCCEEDED:
        raise TransportBoundaryError("receipt completion has no current terminal success authority")
    base, receipts, job, workspace = _completion_context(store, snapshot, program_transport_store, driver)
    record = _completion_stored_record(store, snapshot, assessment.data["evidence_result_id"])
    diagnostic, _capture, _digest, opening, closing = _validate_completion_bundle(record, snapshot, job, workspace, receipts, store.observations_for_attempt(snapshot.attempt_id))
    if diagnostic != "completed":
        raise TransportBoundaryError("receipt completion was invalidated")
    keys = (*_COMPLETION_BINDING_KEYS, "completion_mode", "epoch_id", "evidence_result_id", "capture_authority_id", "receipt_sha256", "observation_prefix_sha256")
    payload = {"schema": "program-terminal-success-authority/2", **{key: assessment.data[key] for key in keys}, "assessment_observation_id": assessment.observation_id, "initial_absence_observation_id": opening, "final_absence_observation_id": closing}
    _publisher_completion_checkpoint(snapshot, driver)
    _completion_checkpoint(snapshot, program_transport_store)
    return freeze_mapping({**payload, "program_terminal_success_authority_id": semantic_id("program-terminal-success-authority", payload)}, "receipt terminal success authority")


@_completion_owned
def _read_program_receipt_success_authority(store, *, snapshot, program_transport_store, driver=None, _completion_token=None):
    """Historical evidence only, independent of any current live installation."""
    from ._receipt_source import _source_qualification
    if type(store) is not SQLiteRuntimeStore or type(program_transport_store) is not _transport._ProgramTransportStore:
        raise TransportBoundaryError("read-only source requires exact native stores")
    snapshot.assert_identity_closed()
    _completion_checkpoint(snapshot, program_transport_store)
    with _source_qualification(store, snapshot, program_transport_store, driver) as (source_store, qualification):
        snapshot._assert_current_core(source_store)
        runtime_id = program_transport_store._require_recorded_runtime(
            program_execution_snapshot_id=snapshot.program_execution_snapshot_id,
            resolved_server_profile_id=snapshot.resolved_server_profile.resolved_server_profile_id,
            qualification=qualification)
        base = _program_store_binding(snapshot, program_transport_store, runtime_id)
        token = _READONLY_RECEIPT_SOURCE.set(source_store)
        try:
            receipts = _load_receipts(source_store, snapshot, program_transport_store, base)
            job = _reconstruct_job_authority_from_receipts(source_store, snapshot, program_transport_store, base, receipts)
            workspace = _reconstruct_workspace_authority(snapshot, program_transport_store, receipts)
            return _read_receipt_success_bundle(source_store, snapshot, program_transport_store, receipts, job, workspace)
        finally:
            _READONLY_RECEIPT_SOURCE.reset(token)


def _read_receipt_success_bundle(store, snapshot, program_transport_store, receipts, job, workspace):
    observations = store.observations_for_attempt(snapshot.attempt_id)
    _verify_completion_assessments(observations, snapshot, job)
    _validate_completion_history(store, snapshot, job, workspace, receipts, observations)
    assessment, result_id = _completion_replay_selection(store, snapshot, observations)
    if assessment is None or result_id is None or assessment.data["verdict"] != "SUCCEEDED" or store.attempt_state(snapshot.attempt_id) is not AttemptState.SUCCEEDED:
        raise TransportBoundaryError("read-only receipt proof requires persisted success")
    record = _completion_stored_record(store, snapshot, result_id)
    diagnostic, capture, digest, opening, closing = _validate_completion_bundle(record, snapshot, job, workspace, receipts, observations)
    if diagnostic != "completed" or (diagnostic, capture.capture_authority_id, digest, record.data["epoch_id"]) != (assessment.data["diagnostic"], assessment.data["capture_authority_id"], assessment.data["receipt_sha256"], assessment.data["epoch_id"]):
        raise TransportBoundaryError("read-only receipt proof was invalidated")
    keys = (*_COMPLETION_BINDING_KEYS, "completion_mode", "epoch_id", "evidence_result_id", "capture_authority_id", "receipt_sha256", "observation_prefix_sha256")
    payload = {"schema": "program-terminal-success-authority/2", **{key: assessment.data[key] for key in keys}, "assessment_observation_id": assessment.observation_id, "initial_absence_observation_id": opening, "final_absence_observation_id": closing}
    _completion_checkpoint(snapshot, program_transport_store)
    return freeze_mapping({**payload, "program_terminal_success_authority_id": semantic_id("program-terminal-success-authority", payload)}, "read-only receipt success"), capture
