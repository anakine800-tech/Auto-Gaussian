"""Fixed Controller ingress for explicitly authorized local staging recovery.

No CLI, qsub, remote probe, new Attempt or automatic recovery entrypoint.
"""
from pathlib import Path

from auto_g16 import approval
from auto_g16.execution import _presubmit_recovery as recovery
from auto_g16.execution import program_runtime as runtime
from auto_g16.transport import _program_rtwin as rtwin
from scripts import run_v31_publisher_pilot as controller


def reconcile_fixed(*, stopped_receipt_id, decision, recovery_code_binding, apply=True):
    if recovery_code_binding.path != str(Path(recovery.__file__).resolve()):
        raise rtwin._publisher_failure("recovery source binding differs")
    pin = rtwin._PinnedPublisherFile(recovery_code_binding, 1024 * 1024)
    try:
        with controller._fixed_pilot_context() as (run, stores, deployment, code_pins):
            original = controller._load_current_authorities(run, deployment)
            _, science, batch, confirmation = original
            plan = stores["core"].load_calculation_plan(run.snapshot.calculation_plan_id)
            attempt = stores["core"].load_attempt(run.snapshot.attempt_id)
            science.assert_current(plan, displayed_semantic_meaning=run.displayed_semantic_meaning)
            member = approval.BatchApprovalMember(attempt_id=attempt.attempt_id, task_id=attempt.task_id,
                calculation_plan_id=plan.calculation_plan_id, calculation_plan_revision=plan.revision,
                scientific_approval_id=science.scientific_approval_id)
            if batch.decision is not approval.ApprovalDecision.APPROVED or batch.member_for(attempt.attempt_id) != member:
                raise rtwin._publisher_failure("original recovery Batch differs")
            driver = rtwin._RTWinProgramEffectDriver(snapshot=run.snapshot, current_profile=run.current_profile,
                                                     program_transport_store=stores["transport"])
            try:
                def checkpoint():
                    for code_pin in code_pins:
                        code_pin._read_and_check()
                    pin._read_and_check()
                    if controller._load_current_authorities(run, deployment) != original:
                        raise rtwin._publisher_failure("original recovery approvals changed")
                token = runtime._COLLECTION_CHECKPOINT.set((run.snapshot, stores["transport"], checkpoint))
                try:
                    checkpoint()
                    return recovery.reconcile(stores["core"], snapshot=run.snapshot,
                        program_transport_store=stores["transport"], driver=driver,
                        stopped_receipt_id=stopped_receipt_id, decision=decision, apply=apply)
                finally:
                    runtime._COLLECTION_CHECKPOINT.reset(token)
            finally:
                driver.close()
    finally:
        pin.close()
