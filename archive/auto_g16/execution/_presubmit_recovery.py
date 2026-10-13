"""Native local reconciliation of a proven stopped staging prefix.

No remote call, child creation, retry or submit entry point. The original
completion guard excludes the producer while both persisted histories close.
"""
from collections.abc import Mapping

from auto_g16 import core
from auto_g16.transport import program as transport
from . import program_runtime as runtime
from ._identity import semantic_id
from .program import _uses_completion_receipt


PROOF = "v31-presubmit-reconciliation/1"


def _require(condition, message):
    if not condition:
        raise transport.TransportBoundaryError(message)


@runtime._completion_owned
def reconcile(store, *, snapshot, program_transport_store, driver,
              stopped_receipt_id, decision, apply=True, _completion_token=None):
    """Explicit, exact local proof; preserve UNKNOWN on any incomplete evidence."""
    _require(_uses_completion_receipt(snapshot.program_execution_spec), "receipt completion required")
    _require(type(apply) is bool, "apply must be explicit boolean")
    program_transport_store._require_current_completion_owner()
    _require(isinstance(decision, Mapping) and set(decision) == {"reviewer_id", "evidence", "attempt_id", "snapshot_id", "decision"}, "exact recovery decision required")
    _require(decision["decision"] == "reconcile-not-submitted" and
             decision["attempt_id"] == snapshot.attempt_id and
             decision["snapshot_id"] == snapshot.program_execution_snapshot_id and
             all(type(decision[k]) is str and decision[k].strip() for k in ("reviewer_id", "evidence")), "recovery decision scope differs")
    _require(store.attempt_state(snapshot.attempt_id) in {core.AttemptState.UNKNOWN, core.AttemptState.NOT_SUBMITTED}, "UNKNOWN or exact terminal replay required")
    snapshot._assert_current_core(store)
    runtime._assert_effect_intent_replay(store, snapshot)
    _require(not store.results_for_attempt(snapshot.attempt_id), "pre-submit recovery cannot have results")
    base = runtime._snapshot_binding(snapshot, program_transport_store, driver)
    receipts = runtime._load_receipts(store, snapshot, program_transport_store, base)
    _require(len(receipts) >= 2 and receipts[0].data["operation"] == "ALLOCATE_WORKSPACE" and
             receipts[0].data["outcome"] == "SUCCEEDED", "successful allocation predecessor required")
    stages = receipts[1:]
    declarations = (*snapshot.program_execution_spec.exact_inputs, *snapshot.scheduler_artifacts)
    _require(len(stages) <= len(declarations), "extra stage history")
    for index, record in enumerate(stages):
        data = record.data
        _require(data["operation"] == "STAGE_EXACT_FILE" and
                 data["outcome"] == ("UNKNOWN" if index == len(stages)-1 else "SUCCEEDED"), "one final UNKNOWN stage required; submission cannot reconcile here")
        _require(data["request"]["payload"]["portable_name"] == declarations[index]["portable_name"], "stage order differs from producer")
    _require(stages[-1].observation_id == stopped_receipt_id, "stopped receipt differs")
    program_transport_store._require_complete_effect_history(base, tuple(r.data for r in receipts))
    observations = store.observations_for_attempt(snapshot.attempt_id)
    proofs = [o for o in observations if o.observation_type == PROOF]
    _require(len(proofs) <= 1, "multiple reconciliation proofs")
    prior = observations[:observations.index(proofs[0])] if proofs else observations
    _require(tuple(o for o in prior if o.observation_type == transport._RECEIPT_TYPE) == receipts, "receipt prefix changed after proof")
    data = {"schema": PROOF, "attempt_id": snapshot.attempt_id,
            "snapshot_id": snapshot.program_execution_snapshot_id,
            "effect_intent_id": snapshot.effect_intent_id,
            "stopped_receipt_id": stopped_receipt_id,
            "receipt_ids": [r.observation_id for r in receipts],
            "observation_prefix_sha256": runtime._observation_prefix(prior),
            "decision": dict(decision), "resolution": "NOT_SUBMITTED",
            "scope": "qsub-not-reached; staged bytes may exist"}
    proof = core.Observation(observation_id=semantic_id(PROOF, data), attempt_id=snapshot.attempt_id, observation_type=PROOF, data=data)
    if proofs:
        _require(proofs == [proof], "recovery proof or decision drift")
        _require(observations == (*prior, proof), "history appended after reconciliation proof")
    else:
        _require(store.attempt_state(snapshot.attempt_id) is core.AttemptState.UNKNOWN, "terminal state lacks original proof")
    runtime._completion_checkpoint(snapshot, program_transport_store)
    _require(store.observations_for_attempt(snapshot.attempt_id) == observations, "history changed before reconciliation")
    if not apply:
        return proof
    if not proofs:
        store.append_observation(proof)
    state = store.reconcile_unknown(snapshot.attempt_id, proof.observation_id, core.ReconciliationResolution.NOT_SUBMITTED)
    _require(state is core.AttemptState.NOT_SUBMITTED, "unexpected Core reconciliation")
    return proof
