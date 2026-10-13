"""Private same-intent exact-job recovery; no submission/prepare entrypoint."""
from auto_g16 import core
from auto_g16.transport import _program_rtwin as rtwin, program as transport
from auto_g16.transport import _submission_recovery as evidence
from auto_g16.transport._canonical import strict_canonical_json
from ._identity import semantic_id


def document(snapshot):
    installed = rtwin._FIXED_COLLECTION_INSTALLATION
    evidence.require(type(installed) is rtwin._FixedCollectionInstallation, "no fixed recovery installation")
    pin = rtwin._PinnedPublisherFile(installed.continuation, 1024 * 1024)
    try:
        value = strict_canonical_json(pin.raw, "exact recovery continuation")
        evidence.require(value.get("schema") == evidence.SCHEMA, "not a recovery continuation")
        digest = installed.continuation.sha256
        prior = value["reconciliation"]["prior_recovery_authority"]
        if prior is not None:
            evidence.closed(prior, {"sha256", "size_bytes"})
            bindings = [b for b in installed.evidence if b.sha256 == prior["sha256"] and b.size_bytes == prior["size_bytes"]]
            evidence.require(len(bindings) == 1, "original recovery authority not pinned")
            historical_pin = rtwin._PinnedPublisherFile(bindings[0], 1024 * 1024)
            try:
                historical = strict_canonical_json(historical_pin.raw, "historical recovery authority")
                evidence.require(historical.get("schema") == evidence.SCHEMA and historical["reconciliation"]["prior_recovery_authority"] is None, "recovery authority chain forbidden")
                for key in ("original", "original_source", "stores"):
                    evidence.require(historical[key] == value[key], "historical recovery binding differs")
                expected_rec = dict(value["reconciliation"], prior_recovery_authority=None)
                evidence.require(historical["reconciliation"] == expected_rec, "historical recovery identity differs")
                historical_pin._read_and_check()
                value, digest = historical, bindings[0].sha256
            finally:
                historical_pin.close()
        original = value["original"]
        evidence.require((original["attempt_id"], original["snapshot_id"], original["effect_intent_id"]) ==
                         (snapshot.attempt_id, snapshot.program_execution_snapshot_id, snapshot.effect_intent_id), "continuation original identity")
        pin._read_and_check()
        return value, digest
    finally:
        pin.close()


def request(snapshot, base, ambiguous):
    value, digest = document(snapshot)
    evidence.require(value["reconciliation"]["submit_receipt_id"] == ambiguous.observation_id, "ambiguous predecessor differs")
    return transport._request("RECONCILE_SUBMISSION", base, {"schema": evidence.REQUEST,
        "submit_receipt_id": ambiguous.observation_id, "observed_job_id": value["original"]["job_id"], "continuation_sha256": digest})


def _observation(snapshot, kind, data):
    return core.Observation(observation_id=semantic_id(kind, data), attempt_id=snapshot.attempt_id, observation_type=kind, data=data)


def validate_proof(store, snapshot, prior_receipts, request_value, proof):
    from . import program_runtime as runtime
    value, digest = document(snapshot)
    expected = evidence.expected_evidence(snapshot, prior_receipts, value)
    evidence.require(proof.get("schema") == evidence.PROOF and proof["request"] == request_value and rtwin._plain(proof["expected"]) == rtwin._plain(expected),
                     "proof does not reconstruct from predecessors")
    observations = store.observations_for_attempt(snapshot.attempt_id)
    starts = [o for o in observations if o.observation_type == evidence.START]
    raws = [o for o in observations if o.observation_type == evidence.RAW]
    evidence.require(len(starts) == len(raws) == 1, "one start and raw record required")
    start, raw = starts[0], raws[0]
    index = observations.index(start)
    data = {"schema": evidence.START, "continuation_sha256": digest, "request": request_value,
            "observation_prefix_sha256": runtime._observation_prefix(observations[:index])}
    evidence.require(start == _observation(snapshot, evidence.START, data), "consumption prefix changed")
    raw_data = {"schema": evidence.RAW, "started_observation_id": start.observation_id, "request": request_value, "raw": proof["raw"]}
    evidence.require(raw == _observation(snapshot, evidence.RAW, raw_data) and raw.observation_id == proof["raw_observation_id"]
                     and observations.index(raw) == index + 1, "raw evidence identity/order")
    # Rejected raw cannot be promoted merely by changing its outcome field.
    try:
        job_id = evidence.interpret(proof["raw"], expected)
    except (ValueError, TypeError, KeyError, transport.TransportBoundaryError):
        job_id = None
    evidence.require((proof["outcome"], proof["job_id"]) == (("SUCCEEDED", job_id) if job_id else ("UNKNOWN", None)), "proof verdict differs from raw evidence")
    transport._reconciliation_response(proof)


def reconcile(store, snapshot, transport_store, driver):
    """Called under the original native completion guard, one durable epoch."""
    from . import program_runtime as runtime
    evidence.require(type(driver) is rtwin._RTWinProgramEffectDriver and driver._recovery_only, "recovery owner required")
    transport_store._require_current_completion_owner()
    base = runtime._snapshot_binding(snapshot, transport_store, driver)
    receipts = runtime._load_receipts(store, snapshot, transport_store, base)
    existing = [o for o in receipts if o.data["operation"] == "RECONCILE_SUBMISSION"]
    if existing:
        evidence.require(len(existing) == 1 and existing[0].data["response"].get("schema") == evidence.PROOF, "recovery history conflict")
        response = existing[0].data["response"]
        resolution = core.ReconciliationResolution.SUBMITTED if response["outcome"] == "SUCCEEDED" else core.ReconciliationResolution.UNRESOLVED
        store.reconcile_unknown(snapshot.attempt_id, existing[0].observation_id, resolution)
        return dict(response)
    evidence.require(store.attempt_state(snapshot.attempt_id) is core.AttemptState.UNKNOWN, "UNKNOWN required")
    observations = store.observations_for_attempt(snapshot.attempt_id)
    evidence.require(not any(o.observation_type in {evidence.START, evidence.RAW} for o in observations), "one-read scope already consumed; no retry")
    ambiguous = runtime._reconstruct_ambiguous_submit(store, snapshot, transport_store, base, receipts)
    value, digest = document(snapshot)
    req = request(snapshot, base, ambiguous)
    expected = evidence.expected_evidence(snapshot, receipts, value)
    start = _observation(snapshot, evidence.START, {"schema": evidence.START, "continuation_sha256": digest,
        "request": req, "observation_prefix_sha256": runtime._observation_prefix(observations)})
    store.append_observation(start)  # Commit happens before any wire invocation.
    prefix = store.observations_for_attempt(snapshot.attempt_id)
    raw = runtime._invoke_program_driver(store, snapshot, transport_store, driver.reconcile_submission, req)
    unchanged = store.observations_for_attempt(snapshot.attempt_id) == prefix
    raw_record = _observation(snapshot, evidence.RAW, {"schema": evidence.RAW, "started_observation_id": start.observation_id, "request": req, "raw": raw})
    store.append_observation(raw_record)  # Durable raw, before parsing/promotion.
    evidence.require(unchanged, "history changed during recovery wire; raw retained")
    try:
        job_id = evidence.interpret(raw, expected)
    except (ValueError, TypeError, KeyError, transport.TransportBoundaryError):
        job_id = None
    response = {"schema": evidence.PROOF, "outcome": "SUCCEEDED" if job_id else "UNKNOWN", "job_id": job_id,
                "request": req, "expected": expected, "raw_observation_id": raw_record.observation_id, "raw": raw}
    validate_proof(store, snapshot, receipts, req, response)
    driver._authority()
    runtime._completion_checkpoint(snapshot, transport_store)
    transport_store.record_effect(binding=req["binding"], request=req, classification=response["outcome"], response=response, job_id=job_id)
    receipt = runtime._append_receipt(store, snapshot, program_transport_store=transport_store, current_binding=base,
        operation="RECONCILE_SUBMISSION", request=req, outcome=response["outcome"], response=response, job_id=job_id)
    runtime._completion_checkpoint(snapshot, transport_store)
    store.reconcile_unknown(snapshot.attempt_id, receipt.observation_id,
        core.ReconciliationResolution.SUBMITTED if job_id else core.ReconciliationResolution.UNRESOLVED)
    if job_id:
        runtime._job_authority(store, snapshot, transport_store, driver)
    return response
