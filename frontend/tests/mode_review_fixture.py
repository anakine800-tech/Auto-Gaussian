"""Disposable synthetic TS-shaped record, never a scientific calculation."""
import hashlib
import json
from auto_g16 import core
from auto_g16.result import InputBinding,OutputEnvelope,OutputArtifact,ResultProvenanceService,GaussianJobParser
from autog_frontend.details import full_result
from autog_frontend.vibrations import build_modes
from .result_fixture import INPUT,PREFIX,FREQUENCY
from .test_vibrations import GEOMETRY,VECTORS

ID='synthetic-mode-review'


def reference(path):
    raw=path.read_bytes()
    return dict(path=str(path),sha256=hashlib.sha256(raw).hexdigest(),size_bytes=len(raw))


def add_mode_review_fixture(store,root,intent=None):
    store.store_task(core.Task(task_id=ID,workflow_run_id='gaussian-run',task_kind='synthetic-gaussian'))
    store.store_calculation_plan(core.CalculationPlan(calculation_plan_id=ID,task_id=ID,revision=1,intent={'program':'gaussian'} if intent is None else intent))
    store.create_attempt(core.Attempt(attempt_id=ID,task_id=ID,ordinal=1))
    owner=ResultProvenanceService(store)
    binding=InputBinding(attempt_id=ID,calculation_plan_id=ID,calculation_plan_revision=1,prepared_input_binding_id=ID,execution_snapshot_id=ID,input_format='gaussian-gjf',logical_name='fixture.gjf',sha256=hashlib.sha256(INPUT).hexdigest(),size_bytes=len(INPUT))
    owner.record_input_binding(binding)
    raw=PREFIX+GEOMETRY+FREQUENCY+VECTORS+b' Normal termination of Gaussian 16\n'
    log=root/'mode-review-fixture.log';log.write_bytes(raw)
    envelope=OutputEnvelope(attempt_id=ID,input_binding_observation_id=binding.observation_id,execution_snapshot_id=ID,capture_source_id=ID,capture_sequence=1,capture_status='captured',capture_completeness='complete',artifacts=(OutputArtifact(artifact_kind='gaussian-log',logical_name=log.name,sha256=hashlib.sha256(raw).hexdigest(),size_bytes=len(raw)),),capture_manifest_sha256='b'*64,captured_at_utc='2026-09-25T00:00:00Z')
    owner.record_output_envelope(envelope);outcome=GaussianJobParser().parse(envelope,{log.name:raw});owner.record_parse_outcome(outcome)
    packet=build_modes({'kind':'attempt','id':ID,'result':full_result(outcome)},raw)
    sidecar=root/'mode-review-vectors.json';sidecar.write_text(json.dumps(packet))
    return {'kind':'attempt','id':ID,'log':reference(log),'vibrations':reference(sidecar)}
