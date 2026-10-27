"""Synthetic PBS only. Never connect to a real scheduler."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess

import pytest
from ag import approval, attempt, config, confirm, node_targeting as nt, render, state, status, study, submit
from ag.transport import Result, TransportError
from test_core import cfg, Fake


def policy():
    return dict(allowed_nodes=['compute-a', 'compute-b', 'compute-c', 'compute-fast', 'compute-last'],
                denied_nodes=['login-a'], priority=[['compute-b', 'compute-a'], ['compute-c'],
                ['compute-fast'], ['compute-last']], restricted_nodes=['compute-fast'])


def nodes(slots=48, memory='128gb', extra=''):
    return f'compute-a\n    state = free\n    np = {slots}\n    status = physmem={memory}\n{extra}'


def snapshot(cfg, rows=None, *, age=0, ok=True):
    root = Path(cfg['local']['studies_root']) / '.ag-monitor'
    root.mkdir(parents=True, exist_ok=True)
    data = dict(schema='ag-monitor/1', sampled_at=(datetime.now(timezone.utc)-timedelta(seconds=age)).isoformat(),
                interval_seconds=60, ok=ok, own={}, cluster=dict(name='default', scheduler='pbs',
                nodes=rows if rows is not None else nt.strict_nodes(nodes(), [])))
    (root / 'latest.json').write_text(json.dumps(data))


@pytest.fixture
def targeted(cfg, tmp_path):
    cfg['node_targeting'] = policy()
    cfg['resources'].update(max_cores=48, max_committed_cores=192,
                            tiers={t:dict(cores=c, mem_gb=c*2) for t,c in
                                   zip(('mini','simple','general','complex','max'),(12,16,24,32,48))})
    study.init(cfg, 'target-demo')
    snapshot(cfg)
    source = tmp_path / 'water.gjf'
    source.write_text('%nprocshared=24\n%mem=40GB\n# HF/STO-3G SP\n\nSynthetic water\n\n0 1\nO 0 0 0\nH 0 0 1\nH 0 1 0\n\n')
    args = dict(study_name='target-demo', template='gaussian', input_path=source,
                tier='general', walltime='01:00:00', label='target', method_basis='Synthetic fallback',
                target_node='compute-a')
    return cfg, args


def prepared(targeted):
    cfg, args = targeted
    m = attempt.prepare(cfg, **args)
    return cfg, attempt.find(cfg, m['attempt_id']), m


class TargetFake(Fake):
    def __init__(self, cfg):
        super().__init__(cfg)
        self.node_text = nodes()

    def run(self, command):
        if command.operation == 'nodes':
            self.calls.append(command)
            return Result(stdout=self.node_text)
        return super().run(command)


@pytest.mark.parametrize('slots,fraction,cores', [(48,'1/2',24),(48,'1/4',12),(64,'1/2',32),
                                                (64,'1/4',16),(96,'1/2',48),(96,'1/4',24)])
def test_fraction(slots, fraction, cores):
    assert nt.resource(slots, fraction) == dict(cores=cores, mem_gb=cores*2)
    assert nt.resource(slots) == nt.resource(slots, '1/2')


@pytest.mark.parametrize('name', ['login-a','not-listed','compute-fast','compute-a:ppn=8','1',
                                 '-n','compute-a+compute-b','a\nb',None,'a..b'])
def test_denied_before_attempt_creation(targeted, name):
    cfg, args = targeted
    before = list(Path(cfg['local']['studies_root']).rglob('manifest.json'))
    with pytest.raises(ValueError):
        attempt.prepare(cfg, **(args | dict(target_node=name)))
    assert list(Path(cfg['local']['studies_root']).rglob('manifest.json')) == before


def test_order_default_binding_and_render(targeted):
    cfg, path, m = prepared(targeted)
    c = nt.candidates(cfg)
    assert [n['name'] for n in c['nodes']] == ['compute-b','compute-a','compute-c','compute-fast','compute-last','login-a']
    assert [n['priority'] for n in c['nodes']] == list(range(1,7))
    assert c['nodes'][-1]['status'] == 'forbidden'
    assert c['nodes'][3]['status'] == 'restricted'
    assert m['node_target'] == dict(name='compute-a', fraction='1/2', slots=48, queue='batch')
    script = (path/'inputs/job.pbs').read_text()
    assert '#PBS -l nodes=compute-a:ppn=24' in script and 'nodes=1:' not in script
    assert 'Target node: compute-a' in attempt.summary(cfg,m)
    assert 'PBS_NODEFILE' in script
    assert script.index('Named-node launch guard') < script.index('mkdir -- "$scratch"')
    assert attempt.verified_files(cfg,path,m)


@pytest.mark.parametrize('age,ok', [(181,True),(0,False),(-5,True)])
def test_stale_blocks_prepare_without_artifacts(targeted, age, ok):
    cfg, args = targeted
    snapshot(cfg, age=age, ok=ok)
    assert nt.candidates(cfg)['nodes'][1]['status'] == 'stale'
    with pytest.raises(ValueError, match='unavailable'):
        attempt.prepare(cfg, **args)
    assert not list(Path(cfg['local']['studies_root']).rglob('manifest.json'))


@pytest.mark.parametrize('change,status_', [({'cores_used':1},'occupied'),({'jobs':1},'occupied'),
    ({'state':'offline'},'occupied'),({'mem_total_gb':None},'unknown'),({'mem_total_gb':1},'insufficient'),
    ({'targeting_consistent':False},'unknown'),({'targeting_reserved':True},'occupied'),
    ({'cores_used':48},'occupied')])
def test_snapshot_fail_closed(targeted, change, status_):
    cfg,_ = targeted
    row = nt.strict_nodes(nodes(),[])[0] | change
    snapshot(cfg,[row])
    assert nt.candidates(cfg)['nodes'][1]['status'] == status_


def test_node_job_conflicts_and_pending_competitor():
    jobs = [dict(job_id='7.fixture',job_state='R',exec_host='compute-a/0')]
    for raw in (nodes(extra='    jobs = 0/8.fixture\n'), nodes(extra='    resources_assigned.ncpus = 0\n')):
        assert nt.idle(nt.strict_nodes(raw,jobs)[0])[0] == 'unknown'
    assert nt.idle(nt.strict_nodes(nodes(), jobs)[0])[0] == 'occupied'
    assert nt.idle(nt.strict_nodes(nodes(), [dict(job_id='8.fixture',job_state='R')])[0])[0] == 'unknown'
    queued = [dict(job_id='9.fixture',job_state='Q',**{'Resource_List.nodes':'compute-a:ppn=24'})]
    assert nt.idle(nt.strict_nodes(nodes(),queued)[0])[0] == 'occupied'
    with pytest.raises(ValueError,match='duplicate'):
        nt.strict_nodes(nodes()+nodes(),[])


def test_target_changes_during_dialog_preserve_approval_claim_manifest(targeted,monkeypatch):
    cfg,path,m = prepared(targeted)
    fake = TargetFake(cfg)
    before = {p.relative_to(path):p.read_bytes() for p in path.rglob('*') if p.is_file()}
    def change(_):
        fake.node_text = nodes(extra='    jobs = 0/9.fixture\n')
        return True
    monkeypatch.setattr(confirm,'confirm',change)
    with pytest.raises(ValueError,match='no longer idle'):
        submit.submit(cfg,[m['attempt_id']],fake)
    for p,data in before.items():
        assert (path/p).read_bytes() == data
    assert not (path/'.submit-claim').exists()
    assert not {'create_attempt','upload','submit'} & set(fake.operations())


def test_explicit_approval_not_consumed_on_occupation(targeted):
    cfg,path,m = prepared(targeted)
    a = approval.create(cfg,'target-demo',[m['attempt_id']],'Approve synthetic target only',1)
    fake = TargetFake(cfg); fake.node_text = nodes(memory='1gb')
    with pytest.raises(ValueError,match='insufficient'):
        submit.submit(cfg,[m['attempt_id']],fake,approval_id=a['id'])
    assert not (path.parent.parent/'approvals'/f"{a['id']}.used").exists()
    assert not (path/'.submit-claim').exists()


def test_standing_policy_missing_target_and_batch_refused(targeted):
    cfg,path,m = prepared(targeted)
    with pytest.raises(ValueError,match='standing policy'):
        submit.submit(cfg,[m['attempt_id']],TargetFake(cfg),policy_name='automatic')
    with pytest.raises(ValueError,match='Explicit target'):
        nt.validate_binding(config.select_cluster(cfg), {k:v for k,v in m.items() if k!='node_target'})
    other = attempt.prepare(cfg,**(targeted[1]|dict(label='second')))
    with pytest.raises(ValueError,match='exactly one'):
        submit.preflight(cfg,[m['attempt_id'],other['attempt_id']])


@pytest.mark.parametrize('mutation', [dict(name='compute-b'),dict(fraction='1/4'),dict(slots=64),dict(queue='other')])
def test_immutable_binding_tamper(targeted, mutation):
    cfg,path,m = prepared(targeted)
    altered = deepcopy(m); altered['node_target'].update(mutation)
    with pytest.raises(ValueError):
        attempt.verified_files(cfg,path,altered)


@pytest.mark.parametrize('placement,expected', [('', 'pending'),('compute-a/0-23','verified'),
    ('compute-b/0-23','mismatch'),('compute-a/0-11+compute-b/0-11','mismatch'),('compute-a/0-47','mismatch')])
def test_post_acceptance_placement(targeted, monkeypatch, placement, expected):
    cfg,path,m = prepared(targeted); fake=TargetFake(cfg)
    fake.job=Result(stdout=f"Job Id: 123.fixture\n    Job_Name = {m['pbs_job_name']}\n    job_state = {'R' if placement else 'Q'}\n"+
                    (f'    exec_host = {placement}\n' if placement else ''))
    monkeypatch.setattr(confirm,'confirm',lambda _:True)
    if expected=='mismatch':
        with pytest.raises(ValueError,match='placement'):
            submit.submit(cfg,[m['attempt_id']],fake)
        prior=len(fake.calls)
        with pytest.raises(ValueError,match='human review'):
            status.check(cfg,path,fake)
        assert len(fake.calls)==prior
    else:
        submit.submit(cfg,[m['attempt_id']],fake)
    assert state.read(path)['node_placement']['state']==expected
    assert state.read(path)['state']=='submitted'
    assert (path/'submission.json').exists() and (path/'.submit-claim').exists()
    assert fake.operations().count('submit')==1 and 'cancel' not in fake.operations()


def test_second_computer_observed_request_blocks_without_claim(targeted, monkeypatch):
    cfg,path,m=prepared(targeted); fake=TargetFake(cfg)
    # Separate client/local lock cannot hide a scheduler-visible named request.
    def competing(_):
        fake.qstat=Result(stdout='Job Id: 999.fixture\n    Job_Name = other\n    Job_Owner = peer@fixture\n    job_state = Q\n    Resource_List.nodes = compute-a:ppn=24\n')
        return True
    monkeypatch.setattr(confirm,'confirm',competing)
    with pytest.raises(ValueError,match='no longer idle'):
        submit.submit(cfg,[m['attempt_id']],fake)
    assert not (path/'.submit-claim').exists() and 'submit' not in fake.operations()


def test_runtime_nodefile_guard(tmp_path):
    from string import Template
    body=Template((render.TEMPLATES/'node-target.pbs').read_text()).substitute(target_node='compute-a',cores=2)
    nodefile=tmp_path/'nodes'; nodefile.write_text('compute-b\ncompute-b\n')
    result=subprocess.run(['sh','-c',body+'\nprintf SHOULD_NOT_RUN'],env={'PBS_NODEFILE':str(nodefile)},capture_output=True)
    assert result.returncode and b'SHOULD_NOT_RUN' not in result.stdout
    nodefile.write_text('compute-a\ncompute-a\n')
    assert subprocess.run(['sh','-c',body],env={'PBS_NODEFILE':str(nodefile)}).returncode==0


def test_policy_validation_and_opt_out(cfg):
    cfg['node_targeting']=policy(); nt.validate_policy(cfg)
    for key,value in [('priority',[['compute-a']]),('allowed_nodes',['a:ppn=4']),('restricted_nodes',['other'])]:
        bad=deepcopy(cfg);bad['node_targeting'][key]=value
        with pytest.raises(ValueError): nt.validate_policy(bad)
    bad=deepcopy(cfg);bad['scheduler']='slurm'
    with pytest.raises(ValueError): nt.validate_policy(bad)
    del cfg['node_targeting']
    assert nt.prepare(cfg,'default','gaussian','simple',None,None) is None
    with pytest.raises(ValueError): nt.prepare(cfg,'default','gaussian','simple','compute-a',None)


def test_second_live_check_before_qsub_stops_after_upload(targeted,monkeypatch):
    cfg,path,m=prepared(targeted);fake=TargetFake(cfg)
    original=fake.upload
    def upload(*args):
        original(*args);fake.node_text=nodes(extra='    resources_assigned.ncpus = 24\n')
    fake.upload=upload
    monkeypatch.setattr(confirm,'confirm',lambda _:True)
    original_manifest=(path/'manifest.json').read_bytes()
    with pytest.raises(ValueError,match='no longer idle'):
        submit.submit(cfg,[m['attempt_id']],fake)
    assert (path/'manifest.json').read_bytes()==original_manifest
    assert (path/'.submit-claim').exists()
    assert state.read(path)['state']=='failed_presubmit'
    assert 'upload' in fake.operations() and 'submit' not in fake.operations()


def test_unknown_qsub_is_once_and_not_placement_success(targeted,monkeypatch):
    cfg,path,m=prepared(targeted);fake=TargetFake(cfg)
    fake.qsub=Result(255,'','Synthetic interruption')
    monkeypatch.setattr(confirm,'confirm',lambda _:True)
    with pytest.raises(submit.UnknownSubmission):submit.submit(cfg,[m['attempt_id']],fake)
    assert state.read(path)['state']=='unknown'
    assert 'node_placement' not in state.read(path)
    before=len(fake.calls)
    with pytest.raises(ValueError):submit.submit(cfg,[m['attempt_id']],fake)
    assert len(fake.calls)==before and fake.operations().count('submit')==1


def test_accepted_job_placement_ssh_failure_retains_binding(targeted,monkeypatch):
    cfg,path,m=prepared(targeted);fake=TargetFake(cfg)
    fake.job=Result(255,'','Synthetic placement connection failure')
    monkeypatch.setattr(confirm,'confirm',lambda _:True)
    with pytest.raises(TransportError):submit.submit(cfg,[m['attempt_id']],fake)
    assert state.read(path)['state']=='submitted'
    assert state.read(path)['node_placement']['state']=='unverified'
    assert (path/'submission.json').exists() and fake.operations().count('submit')==1


def test_pending_then_verified_and_disappeared_evidence_is_retained(targeted):
    cfg,path,m=prepared(targeted)
    state.write(path,'submitting');state.write(path,'submitted',job_id='123.fixture')
    nt.retain_placement(path,m,dict(job_state='Q'))
    assert state.read(path)['node_placement']['state']=='pending'
    nt.retain_placement(path,m,dict(job_state='R',exec_host='compute-a/0-23'))
    prior=state.read(path)
    assert nt.retain_placement(path,m,None)==prior
    assert nt.retain_placement(path,m,dict(job_state='C'))==prior
    assert nt.placement(m,dict(exec_host='compute-a/0-11+compute-a/0-11'))['state']=='mismatch'


def test_cli_discovery_local_only_and_no_implicit_target(targeted,monkeypatch,capsys):
    from ag import cli, clusters
    cfg,args=targeted
    monkeypatch.setattr(cli,'load_config',lambda **_:cfg)
    assert cli.main(['nodes','--json'])==0
    result=json.loads(capsys.readouterr().out)
    assert result['schema']=='ag-node-targets/1' and result['valid_until']
    assert clusters.describe(cfg)['clusters'][0]['node_targeting']==dict(default_fraction='1/2',fractions=['1/2','1/4'])
    with pytest.raises(ValueError):attempt.prepare(cfg,**(args|dict(node_fraction='1/4')))


def test_explicit_quarter_uses_existing_tier(targeted):
    cfg,args=targeted
    args['input_path'].write_text(args['input_path'].read_text().replace('24','12').replace('40GB','20GB'))
    m=attempt.prepare(cfg,**(args|dict(node_fraction='1/4',tier='mini')))
    assert m['node_target']['fraction']=='1/4' and m['cores']==12 and m['mem_gb']==24
