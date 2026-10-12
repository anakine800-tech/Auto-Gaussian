"""Independent public-record expectations for one explicit Result context.

Read only. Output stays private. Never parses files, executes, or accepts science.
"""
import argparse
import hashlib
import json
from pathlib import Path
from auto_g16.core import SQLiteRuntimeStore
from auto_g16.result import ResultProvenanceService


def export(profile, attempt_id, output):
    profile=json.loads(profile.read_text());db=Path(profile['database'])
    def fingerprint():
        s=db.stat()
        return (hashlib.sha256(db.read_bytes()).hexdigest(),s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
    before=fingerprint()
    with SQLiteRuntimeStore.read_snapshot(db) as store:
        a=store.load_attempt(attempt_id);t=store.load_task(a.task_id);w=store.load_workflow_run(t.workflow_run_id)
        p=store.load_project(w.project_id);v=ResultProvenanceService(store).current_view(attempt_id)
        plan=store.load_calculation_plan(v.input_binding.calculation_plan_id)
        assert plan.intent['schema']=='auto-g16-v30-a-calculation-plan-intent/1'
        expected=dict(project_id=p.project_id,workflow_run_id=w.workflow_run_id,workflow_name=w.workflow_name,
            task_id=t.task_id,attempt_id=a.attempt_id,calculation_plan_id=plan.calculation_plan_id,revision=plan.revision,
            input_sha256=v.input_binding.sha256,input_binding_observation_id=v.input_binding.observation_id,
            conditions=dict(method=plan.intent['method']['electronic_structure_method'],basis=plan.intent['method']['basis'],
                environment=plan.intent['method']['environment'],charge=plan.intent['molecule']['charge'],
                multiplicity=plan.intent['molecule']['multiplicity'],dispersion=plan.intent['method']['dispersion']))
    if before!=fingerprint():raise ValueError('source changed')
    with output.open('x') as stream:json.dump(expected,stream,indent=2)
    print('Public-record expectations saved; original database unchanged.')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--profile',type=Path,required=True);p.add_argument('--attempt',required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();export(a.profile,a.attempt,a.output)
