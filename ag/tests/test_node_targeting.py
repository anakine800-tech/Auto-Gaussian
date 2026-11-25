"""Synthetic PBS only. Never connect to a real scheduler."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import subprocess

import pytest
from ag import approval, attempt, capacity, config, confirm, monitor, node_targeting as nt, render, state, status, study, submit
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
    source.write_text('%nprocshared=24\n%mem=40GB\n# HF/STO-3G SP\n\nSynthetic water\n\n0 1\nO 0.0 0.0 0.0\nH 0.0 0.0 1.0\nH 0.0 1.0 0.0\n\n')
    args = dict(study_name='target-demo', template='gaussian', input_path=source,
                tier='general', walltime='01:00:00', label='target', method_basis='Synthetic fallback',
                target_node='compute-a')
    return cfg, args


def prepared(targeted):
    cfg, args = targeted
    m = attempt.prepare(cfg, **args)
    return cfg, attempt.find(cfg, m['attempt_id']), m


@pytest.mark.parametrize('fraction,tier,cores,memory', [('1/2', 'general', 24, 40), ('1/4', 'mini', 12, 20),
                                                       ('1', 'max', 48, 81)])
def test_auto_cores_use_explicit_node_fraction_tier(targeted, fraction, tier, cores, memory):
    cfg, args = targeted
    source = args['input_path']
    data = source.read_bytes().replace(b'%nprocshared=24\n%mem=40GB\n', b'')
    source.write_bytes(data)
    m = attempt.prepare(cfg, **(args | dict(node_fraction=fraction, tier=tier)))
    path = attempt.find(cfg, m['attempt_id'])
    assert m['cores'] == m['auto_nprocshared'] == cores
    assert m['node_target']['fraction'] == fraction
    assert attempt.verified_files(cfg, path, m)['water.gjf'] == (
        f'%nprocshared={cores}\n%mem={memory}GB\n'.encode() + data)
    assert source.read_bytes() == data


@pytest.mark.parametrize('change', [dict(target_node='not-listed'), dict(tier='simple'),
                                  dict(node_fraction='1/4'), dict(walltime='invalid')])
def test_auto_cores_do_not_bypass_node_or_walltime_checks(targeted, change):
    cfg, args = targeted
    source = args['input_path']
    source.write_bytes(source.read_bytes().replace(b'%nprocshared=24\n', b''))
    with pytest.raises(ValueError):
        attempt.prepare(cfg, **(args | change))
    assert list((Path(cfg['local']['studies_root']) / 'target-demo/attempts').iterdir()) == []


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
                                                (64,'1/4',16),(96,'1/2',48),(96,'1/4',24),
                                                (48,'1',48),(64,'1',64),(96,'1',96)])
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
    assert [n['order'] for n in c['nodes']] == list(range(1,7))
    assert [n['priority_group'] for n in c['nodes']] == [1,1,2,3,4,None]
    assert c['nodes'][-1]['status'] == 'forbidden'
    assert c['nodes'][3]['status'] == 'restricted'
    assert m['node_target'] == dict(name='compute-a', fraction='1/2', slots=48, queue='batch')
    script = (path/'inputs/job.pbs').read_text()
    assert '#PBS -l nodes=compute-a:ppn=24' in script and 'nodes=1:' not in script
    assert 'Target node: compute-a' in attempt.summary(cfg,m)
    assert 'PBS_NODEFILE' in script
    assert script.index('Named-node launch guard') < script.index('mkdir -- "$scratch"')
    assert attempt.verified_files(cfg,path,m)


def test_priority_groups_and_member_order_are_preserved(targeted):
    cfg, _ = targeted
    cfg['node_targeting'] = dict(allowed_nodes=list('ABCDEFGH'), denied_nodes=['I'],
                                priority=[list('ABC'), ['D'], ['E'], list('FG'), ['H']],
                                restricted_nodes=['G'])
    rows = [dict(nt.strict_nodes(nodes(), [])[0], name=name) for name in 'ABCDEFGHI']
    snapshot(cfg, rows)
    result = nt.candidates(cfg)['nodes']
    assert [r['name'] for r in result] == list('ABCDEFGHI')
    assert [r['priority_group'] for r in result] == [1,1,1,2,3,4,4,5,None]
    assert [r['order'] for r in result] == list(range(1,10))
    assert all(r['priority'] == r['order'] for r in result)
    assert result[6]['status'] == 'restricted'
    assert result[7]['status'] == 'available' and result[8]['status'] == 'forbidden'
    # Denying an allowlisted member retains its original group, but deny wins.
    cfg['node_targeting']['denied_nodes'].append('B')
    denied = nt.candidates(cfg)['nodes'][1]
    assert denied['priority_group'] == 1 and denied['status'] == 'forbidden'


def test_strict_monitor_failure_keeps_readonly_nodes_but_blocks_targeting(targeted, monkeypatch):
    cfg, path, m = prepared(targeted)
    fake = TargetFake(cfg)
    baseline, baseline_hardware = monitor.pbs_hardware(
        {k:v for k,v in cfg.items() if k != 'node_targeting'}, fake, [])
    before = (path/'manifest.json').read_bytes()

    def inconsistent(*args):
        raise ValueError('Synthetic strict evidence failure')

    monkeypatch.setattr(nt, 'strict_nodes', inconsistent)
    start = len(fake.calls)
    rows, hardware = monitor.pbs_hardware(cfg, fake, [])
    assert rows == [r | dict(targeting_consistent=False) for r in baseline]
    assert {k:v for k,v in hardware.items() if k != 'notes'} == {
        k:v for k,v in baseline_hardware.items() if k != 'notes'}
    assert any('targeting unavailable' in note for note in hardware['notes'])
    assert [c.operation for c in fake.calls[start:]] == ['nodes']
    snapshot(cfg, rows)
    assert nt.candidates(cfg)['nodes'][1]['status'] == 'unknown'
    monkeypatch.setattr(confirm, 'confirm', lambda _: True)
    with pytest.raises(ValueError, match='strict evidence'):
        submit.submit(cfg, [m['attempt_id']], fake)
    assert (path/'manifest.json').read_bytes() == before
    assert not (path/'.submit-claim').exists() and 'submit' not in fake.operations()


def test_duplicate_node_identity_invalidates_hardware_and_fails_closed(targeted):
    cfg, _ = targeted
    fake = TargetFake(cfg)
    fake.node_text = nodes() + nodes()
    rows, hardware = monitor.pbs_hardware(cfg, fake, [])
    assert rows == [] and hardware['cores_total'] is None
    assert 'duplicate' in hardware['error'] and 'compute-a' not in hardware['error']
    snapshot(cfg, rows)
    assert nt.candidates(cfg)['nodes'][1]['status'] == 'unknown'
    with pytest.raises(ValueError, match='duplicate'):
        nt.strict_nodes(fake.node_text, [])


def test_memory_alias_does_not_relax_exact_targeting_identity(targeted):
    cfg, args = targeted
    fake = TargetFake(cfg)
    fake.node_text = nodes(extra='    jobs = 0-3/901.fixture\n')
    jobs = [dict(job_id='901.fixture', job_state='R', exec_host='compute-a.example/0-3',
                 **{'Resource_List.mem': '12gb'})]
    rows, hardware = monitor.pbs_hardware(cfg, fake, jobs)
    assert rows[0]['name'] == 'compute-a' and rows[0]['cores_used'] == 4 and rows[0]['jobs'] == 1
    assert rows[0]['mem_assigned_gb'] == hardware['mem_allocated_gb'] == 12
    assert rows[0]['targeting_consistent'] is False
    snapshot(cfg, rows)
    assert nt.candidates(cfg)['nodes'][1]['status'] == 'unknown'
    with pytest.raises(ValueError, match='unavailable'):
        attempt.prepare(cfg, **args)
    assert not list(Path(cfg['local']['studies_root']).rglob('manifest.json'))


@pytest.mark.parametrize('age,ok', [(181,True),(0,False),(-5,True)])
def test_stale_blocks_prepare_without_artifacts(targeted, age, ok):
    cfg, args = targeted
    snapshot(cfg, age=age, ok=ok)
    assert nt.candidates(cfg)['nodes'][1]['status'] == 'stale'
    with pytest.raises(ValueError, match='unavailable'):
        attempt.prepare(cfg, **args)
    assert not list(Path(cfg['local']['studies_root']).rglob('manifest.json'))


@pytest.mark.parametrize('change,status_', [({'cores_used':1},'occupied'),({'jobs':1},'occupied'),
    ({'state':'offline'},'occupied'),({'mem_total_gb':None,'mem_total_bytes':None},'unknown'),
    ({'mem_total_gb':1,'mem_total_bytes':1024**3},'insufficient'),
    ({'targeting_consistent':False},'unknown'),({'targeting_reserved':True},'occupied'),
    ({'cores_used':48},'occupied')])
def test_snapshot_fail_closed(targeted, change, status_):
    cfg,_ = targeted
    row = nt.strict_nodes(nodes(),[])[0] | change
    snapshot(cfg,[row])
    assert nt.candidates(cfg)['nodes'][1]['status'] == status_


def test_node_job_conflicts_and_pending_competitor():
    jobs = [dict(job_id='7.fixture', Job_Owner='peer@fixture', job_state='R', exec_host='compute-a/0')]
    for raw in (nodes(extra='    jobs = 0/8.fixture\n'), nodes(extra='    resources_assigned.ncpus = 0\n')):
        assert nt.idle(nt.strict_nodes(raw,jobs)[0])[0] == 'unknown'
    assert nt.idle(nt.strict_nodes(nodes(), jobs)[0])[0] == 'occupied'
    assert nt.idle(nt.strict_nodes(nodes(), [dict(job_id='8.fixture',job_state='R')])[0])[0] == 'unknown'
    queued = [dict(job_id='9.fixture', Job_Owner='peer@fixture', job_state='Q', **{'Resource_List.nodes':'compute-a:ppn=24'})]
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
    with pytest.raises(ValueError, match='after confirmation.*absent from qstat'):
        submit.submit(cfg,[m['attempt_id']],fake)
    for p,data in before.items():
        assert (path/p).read_bytes() == data
    assert not (path/'.submit-claim').exists()
    assert not {'create_attempt','upload','submit'} & set(fake.operations())


def test_explicit_approval_not_consumed_on_insufficient_total_memory(targeted):
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


@pytest.mark.parametrize('job_state,placement,expected', [('Q','', 'pending'),('Q','compute-a/0-23','pending'),
    ('R','compute-a/0-23','verified'),('R','compute-b/0-23','mismatch'),
    ('R','compute-a/0-11+compute-b/0-11','mismatch'),('R','compute-a/0-47','mismatch')])
def test_post_acceptance_placement(targeted, monkeypatch, job_state, placement, expected):
    cfg,path,m = prepared(targeted); fake=TargetFake(cfg)
    before = (path/'manifest.json').read_bytes()
    fake.job=Result(stdout=f"Job Id: 123.fixture\n    Job_Name = {m['pbs_job_name']}\n    job_state = {job_state}\n"+
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
    assert (path/'manifest.json').read_bytes() == before
    assert attempt.verified_files(cfg,path,m)
    assert fake.operations().count('submit')==1 and 'cancel' not in fake.operations()


@pytest.mark.parametrize('job_state', ['Q','H','W','T'])
@pytest.mark.parametrize('hosts', ['', 'compute-a/0-23', 'compute-b/0-23', 'malformed'])
def test_nonrunning_placement_is_pending_even_with_exec_host(job_state, hosts):
    m = dict(node_target=dict(name='compute-a'), cores=24)
    assert nt.placement(m, dict(job_state=job_state, exec_host=hosts))['state'] == 'pending'


@pytest.mark.parametrize('job_state', ['R','E','S','C'])
@pytest.mark.parametrize('hosts,expected', [('', 'unverified'), ('compute-a/0-23','verified'),
    ('compute-b/0-23','mismatch'), ('compute-a/0-22','mismatch'), ('malformed','mismatch'),
    ('compute-a/0-11+compute-a/0-11','mismatch')])
def test_running_and_completed_placement_requires_exact_evidence(job_state, hosts, expected):
    m = dict(node_target=dict(name='compute-a'), cores=24)
    assert nt.placement(m, dict(job_state=job_state, exec_host=hosts))['state'] == expected


@pytest.mark.parametrize('job_state', [None, '', 'X', 'r', ' R', 0])
def test_missing_or_abnormal_scheduler_state_never_verifies(job_state):
    m = dict(node_target=dict(name='compute-a'), cores=24)
    job = dict(exec_host='compute-a/0-23')
    if job_state is not None:
        job['job_state'] = job_state
    assert nt.placement(m, job)['state'] == 'unverified'


@pytest.mark.parametrize('job', [{}, dict(job_state='X',exec_host='compute-a/0-23')])
def test_invalid_observation_does_not_retain_verified_as_current(targeted, job):
    _,path,m = prepared(targeted)
    state.write(path,'submitting');state.write(path,'submitted',job_id='123.fixture')
    nt.retain_placement(path,m,dict(job_state='R',exec_host='compute-a/0-23'))
    with pytest.raises(ValueError,match='not verified'):
        nt.retain_placement(path,m,job)
    assert state.read(path)['state'] == 'submitted'
    assert state.read(path)['node_placement']['state'] == 'unverified'


def test_second_computer_named_request_allows_queueing(targeted, monkeypatch):
    cfg,path,m=prepared(targeted); fake=TargetFake(cfg)
    # A scheduler-visible named request is not an exclusive reservation.
    def competing(_):
        fake.qstat=Result(stdout='Job Id: 999.fixture\n    Job_Name = other\n    Job_Owner = peer@fixture\n    job_state = Q\n    Resource_List.nodes = compute-a:ppn=24\n')
        return True
    monkeypatch.setattr(confirm,'confirm',competing)
    submit.submit(cfg,[m['attempt_id']],fake)
    assert (path/'.submit-claim').exists() and (path/'submission.json').exists()
    assert fake.operations().count('nodes') == 2
    assert fake.operations().count('submit') == 1 and 'cancel' not in fake.operations()


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
    with pytest.raises(ValueError,match='contradictory'):
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
    assert nt.placement(m,dict(job_state='R',exec_host='compute-a/0-11+compute-a/0-11'))['state']=='mismatch'


def test_cli_discovery_local_only_and_no_implicit_target(targeted,monkeypatch,capsys):
    from ag import cli, clusters
    cfg,args=targeted
    monkeypatch.setattr(cli,'load_config',lambda **_:cfg)
    assert cli.main(['nodes','--json'])==0
    result=json.loads(capsys.readouterr().out)
    assert result['schema']=='ag-node-targets/1' and result['valid_until']
    assert clusters.describe(cfg)['clusters'][0]['node_targeting']==dict(default_fraction='1/2',fractions=['1/2','1/4','1'])
    with pytest.raises(ValueError):attempt.prepare(cfg,**(args|dict(node_fraction='1/4')))


def test_explicit_quarter_uses_existing_tier(targeted):
    cfg,args=targeted
    args['input_path'].write_text(args['input_path'].read_text().replace('24','12').replace('40GB','20GB'))
    m=attempt.prepare(cfg,**(args|dict(node_fraction='1/4',tier='mini')))
    assert m['node_target']['fraction']=='1/4' and m['cores']==12 and m['mem_gb']==24


def test_whole_node_uses_exact_tier_and_existing_named_render(targeted):
    cfg, args = targeted
    source = args['input_path']
    source.write_bytes(source.read_bytes().replace(b'%nprocshared=24\n%mem=40GB\n', b''))
    m = attempt.prepare(cfg, **(args | dict(node_fraction='1', tier='max')))
    path = attempt.find(cfg, m['attempt_id'])
    assert m['node_target'] == dict(name='compute-a', fraction='1', slots=48, queue='batch')
    assert m['cores'] == 48 and m['mem_gb'] == 96
    files = attempt.verified_files(cfg, path, m)
    assert b'#PBS -l nodes=compute-a:ppn=48\n' in files['job.pbs']
    assert b'#PBS -l mem=96gb\n' in files['job.pbs']
    assert b'# AG target fraction=1 slots=48\n' in files['job.pbs']
    assert nt.placement(m, dict(job_state='R', exec_host='compute-a/0-47'))['state'] == 'verified'
    assert nt.placement(m, dict(job_state='R', exec_host='compute-a/0-23'))['state'] == 'mismatch'


@pytest.mark.parametrize('failure', ['max_cores', 'tier', 'memory', 'memory_unknown', 'walltime'])
def test_whole_node_never_bypasses_resource_or_time_limits(targeted, failure):
    cfg, args = targeted
    source = args['input_path']
    source.write_bytes(source.read_bytes().replace(b'%nprocshared=24\n%mem=40GB\n', b''))
    if failure == 'max_cores':
        cfg['resources']['max_cores'] = 44
        assert nt.options(cfg, 48)[-1]['tier'] is None
    elif failure == 'tier':
        cfg['resources']['tiers']['max']['mem_gb'] = 95
        assert nt.options(cfg, 48)[-1]['tier'] is None
    elif failure == 'memory':
        snapshot(cfg, nt.strict_nodes(nodes(memory='98303mb'), []))
    elif failure == 'memory_unknown':
        row = nt.strict_nodes(nodes(), [])[0]
        row['mem_total_bytes'] = None
        snapshot(cfg, [row])
    else:
        cfg['resources']['max_walltime'] = '00:30:00'
    with pytest.raises(ValueError):
        attempt.prepare(cfg, **(args | dict(node_fraction='1', tier='max')))
    assert not list(Path(cfg['local']['studies_root']).rglob('manifest.json'))


def test_whole_node_can_queue_on_shared_node_without_claiming_idle(targeted):
    cfg, args = targeted
    raw, qstat = shared_observation()
    snapshot(cfg, nt.strict_nodes(raw, status.parse_jobs(qstat)))
    option = nt.candidates(cfg)['nodes'][1]['options'][-1]
    assert option['fraction'] == '1' and option['selectable']
    assert option['capacity']['availability'] == 'queue'
    source = args['input_path']
    source.write_bytes(source.read_bytes().replace(b'%nprocshared=24\n%mem=40GB\n', b''))
    m = attempt.prepare(cfg, **(args | dict(node_fraction='1', tier='max')))
    fake = TargetFake(cfg)
    fake.node_text, fake.qstat = raw, Result(stdout=qstat)
    nt.fresh_check(config.select_cluster(cfg), m, fake)
    assert fake.operations() == ['jobs', 'nodes']


@pytest.mark.parametrize('fraction,tier,cores,digest', [
    ('1/2', 'general', 24, 'a581cf5ab92de201bf5966fdaf7f8391931dac7e7664cb7569f46dd064ae22e9'),
    ('1/4', 'mini', 12, '51c0165ea5e159ebe48543f291ccaba4b19991c803fca9a07a745a0ee5b5c958')])
def test_half_quarter_render_bytes_stay_compatible(targeted, fraction, tier, cores, digest):
    # Digests were recorded before adding whole-node support. Fixed synthetic
    # paths keep the complete rendered script reproducible across test roots.
    cfg, _ = targeted
    cfg = deepcopy(cfg)
    cfg['remote'] = dict(allowed_root='/fixture', ag_root='/fixture/ag')
    cfg['programs']['gaussian']['g16root'] = '/fixture/programs'
    m = dict(cluster='default', scheduler='pbs', template='gaussian', template_params={},
             node_target=dict(name='compute-a', fraction=fraction, slots=48, queue='batch'),
             tier=tier, cores=cores, mem_gb=cores*2, walltime='01:00:00',
             attempt_id='001-synthetic', study_id='smoke', pbs_job_name='agsynthetic',
             remote_dir='smoke/001-synthetic')
    assert sha256(render.render(cfg, m, 'water.gjf').encode()).hexdigest() == digest


def shared_observation(*, used=16, memory='16gb', owners=('fixture', 'peer'), node_state='free'):
    """Two synthetic allocations and a named queued request on one node."""
    jobs, slots = [], []
    for i, owner in enumerate(owners):
        slot = f'{i * used // 2}-{(i + 1) * used // 2 - 1}'
        job = (f'Job Id: {901+i}.fixture\n    Job_Name = synthetic\n'
               f'    Job_Owner = {owner}@fixture\n    job_state = R\n'
               f'    exec_host = compute-a/{slot}\n'
               f'    Resource_List.nodes = compute-a:ppn={used // 2}\n')
        if memory is not None:
            job += f'    Resource_List.mem = {memory}\n'
        jobs.append(job)
        slots.append(f'{slot}/{901+i}.fixture')
    jobs.append('Job Id: 903.fixture\n    Job_Name = synthetic-queued\n'
                '    Job_Owner = peer@fixture\n    job_state = Q\n'
                '    Resource_List.nodes = compute-a:ppn=24\n')
    raw = nodes(extra='    jobs = ' + ', '.join(slots) + '\n')
    return raw.replace('state = free', 'state = ' + node_state), ''.join(jobs)


@pytest.mark.parametrize('owners', [('fixture', 'fixture'), ('peer', 'peer'), ('fixture', 'peer')])
@pytest.mark.parametrize('used,memory,expected', [(16, '16gb', 'enough'), (40, '50gb', 'queue'),
                                                (16, None, 'unknown')])
def test_shared_candidates_prepare_and_capacity_agree(targeted, owners, used, memory, expected):
    cfg, args = targeted
    raw, qstat = shared_observation(used=used, memory=memory, owners=owners)
    rows = nt.strict_nodes(raw, status.parse_jobs(qstat))
    snapshot(cfg, rows)
    candidate = nt.candidates(cfg)['nodes'][1]
    assert candidate['status'] == 'occupied' and candidate['selectable'] is True
    assert candidate['selectable_reason']
    assert [o['cores'] for o in candidate['options']] == [24, 12, 48]
    option = candidate['options'][0]
    assert option['selectable'] is True and option['capacity']['availability'] == expected
    assert option['capacity'] == capacity.evaluate_node(rows[0], 24, 48, scheduler='pbs')
    assert capacity.assess(cfg, 'default', 'general', 'compute-a')['availability'] == expected
    m = attempt.prepare(cfg, **args)
    assert m['cores'] == 24 and m['mem_gb'] == 48 and m['node_target']['slots'] == 48
    fake = TargetFake(cfg)
    fake.node_text, fake.qstat = raw, Result(stdout=qstat)
    nt.fresh_check(config.select_cluster(cfg), m, fake)


@pytest.mark.parametrize('node_state', ['free', 'job-busy', 'job-exclusive'])
def test_supported_occupied_states_are_selectable(targeted, node_state):
    cfg, args = targeted
    raw, qstat = shared_observation(node_state=node_state)
    snapshot(cfg, nt.strict_nodes(raw, status.parse_jobs(qstat)))
    candidate = nt.candidates(cfg)['nodes'][1]
    assert candidate['status'] == 'occupied' and candidate['selectable'] is True
    assert candidate['options'][0]['capacity']['availability'] == ('enough' if node_state == 'free' else 'queue')
    m = attempt.prepare(cfg, **args)
    fake = TargetFake(cfg); fake.node_text, fake.qstat = raw, Result(stdout=qstat)
    nt.fresh_check(config.select_cluster(cfg), m, fake)


@pytest.mark.parametrize('node_state', ['offline', 'down', 'unknown', 'state-unknown', 'busy',
    'free,offline', 'job-busy,down', 'free,job-busy', 'reserve', 'time-shared'])
def test_bad_or_unsupported_states_never_admit(targeted, node_state):
    cfg, args = targeted
    raw, qstat = shared_observation(node_state=node_state)
    snapshot(cfg, nt.strict_nodes(raw, status.parse_jobs(qstat)))
    candidate = nt.candidates(cfg)['nodes'][1]
    assert candidate['status'] == 'occupied' and candidate['selectable'] is False
    assert 'state' in candidate['selectable_reason']
    with pytest.raises(ValueError, match='unavailable'):
        attempt.prepare(cfg, **args)
    assert not list(Path(cfg['local']['studies_root']).rglob('manifest.json'))


@pytest.mark.parametrize('change', [dict(targeting_consistent=False), dict(capacity_cpu_consistent=False),
    dict(cores_used=49), dict(cores_used=-1), dict(jobs=None), dict(targeting_reserved=None),
    dict(mem_total_bytes=None), dict(mem_total_bytes=48*1024**3-1),
    dict(mem_assigned_bytes=129*1024**3), dict(mem_assigned_bytes=-1),
    dict(mem_assigned_bytes=True), dict(capacity_error='Synthetic conflicting evidence')])
def test_occupied_node_conflicts_and_missing_totals_do_not_admit(targeted, change):
    cfg, args = targeted
    raw, qstat = shared_observation()
    row = nt.strict_nodes(raw, status.parse_jobs(qstat))[0] | change
    snapshot(cfg, [row])
    candidate = nt.candidates(cfg)['nodes'][1]
    assert not candidate['options'][0]['selectable']
    # The quarter may still fit a genuinely smaller total; it cannot silently
    # replace the requested half-node allocation.
    with pytest.raises(ValueError):
        attempt.prepare(cfg, **args)


@pytest.mark.parametrize('missing', ['mem_assigned_bytes', 'mem_assigned_gb', 'both'])
def test_missing_assigned_memory_is_only_capacity_advice(targeted, missing):
    cfg, args = targeted
    raw, qstat = shared_observation()
    row = nt.strict_nodes(raw, status.parse_jobs(qstat))[0]
    for key in ('mem_assigned_bytes', 'mem_assigned_gb'):
        if missing in (key, 'both'):
            row.pop(key)
    snapshot(cfg, [row])
    candidate = nt.candidates(cfg)['nodes'][1]
    assert candidate['selectable'] is True
    assert candidate['options'][0]['capacity']['availability'] == (
        'enough' if missing == 'mem_assigned_gb' else 'unknown')
    assert attempt.prepare(cfg, **args)['cores'] == 24


@pytest.mark.parametrize('memory', ['1b', '0.1gb'])
def test_positive_assigned_memory_without_allocations_is_contradictory(targeted, memory):
    cfg, args = targeted
    # Either exact bytes or the legacy display can establish the contradiction;
    # fractional bytes are unknown, not permission to discard the old check.
    raw = nodes(extra=f'    resources_assigned.mem = {memory}\n')
    row = nt.strict_nodes(raw, [])[0]
    assert row['mem_assigned_gb'] == (0 if memory == '1b' else 0.1)
    assert row['mem_assigned_bytes'] == (1 if memory == '1b' else None)
    snapshot(cfg, [row])
    assert nt.candidates(cfg)['nodes'][1]['selectable'] is False
    with pytest.raises(ValueError, match='unavailable'):
        attempt.prepare(cfg, **args)


def test_old_targeting_cache_keeps_display_tiers_but_unknown_admission(targeted):
    cfg, args = targeted
    row = nt.strict_nodes(nodes(), [])[0]
    for key in ('capacity_cpu_consistent', 'mem_total_bytes', 'mem_assigned_bytes'):
        row.pop(key)
    snapshot(cfg, [row])
    candidate = nt.candidates(cfg)['nodes'][1]
    assert nt.idle(row)[0] == candidate['status'] == 'available'
    assert [o['tier'] for o in candidate['options']] == ['general', 'mini', 'max']
    assert not candidate['selectable'] and 'unknown' in candidate['selectable_reason']
    for option in candidate['options']:
        assert option['capacity']['fits_total'] is None
        assert option['capacity']['availability'] == 'unknown'
        assert not option['selectable'] and 'No configured tier' not in option['selectable_reason']
    with pytest.raises(ValueError, match='unknown'):
        attempt.prepare(cfg, **args)
    assert not list(Path(cfg['local']['studies_root']).rglob('manifest.json'))


def test_exact_memory_rejection_does_not_rewrite_legacy_display_mapping(targeted):
    cfg, args = targeted
    snapshot(cfg, nt.strict_nodes(nodes(memory='49151mb'), []))
    candidate = nt.candidates(cfg)['nodes'][1]
    assert candidate['status'] == 'available'
    half, quarter, whole = candidate['options']
    assert half['tier'] == 'general' and quarter['tier'] == 'mini'
    assert half['capacity']['fits_total'] is False and not half['selectable']
    assert quarter['selectable'] is True
    assert not whole['selectable']
    with pytest.raises(ValueError, match='match target slots'):
        attempt.prepare(cfg, **args)


@pytest.mark.parametrize('when', ['confirmation', 'upload'])
@pytest.mark.parametrize('used,memory', [(16, '16gb'), (40, '50gb'), (16, None)])
def test_new_occupation_during_submit_runs_both_checks_once(targeted, monkeypatch, when, used, memory):
    cfg, path, m = prepared(targeted)
    fake = TargetFake(cfg)
    immutable = {p: p.read_bytes() for p in [path/'manifest.json', *(path/'inputs').iterdir()]}
    checks = []
    original_check, original_upload = nt.fresh_check, fake.upload
    def check(*args):
        checks.append((len(fake.calls), (path/'.submit-claim').exists()))
        return original_check(*args)
    def occupy():
        raw, jobs = shared_observation(used=used, memory=memory)
        fake.node_text, fake.qstat = raw, Result(stdout=jobs)
    def confirmation(_):
        if when == 'confirmation':
            occupy()
        return True
    def upload(*args):
        original_upload(*args)
        if when == 'upload':
            occupy()
    monkeypatch.setattr(nt, 'fresh_check', check)
    monkeypatch.setattr(confirm, 'confirm', confirmation)
    fake.upload = upload
    submit.submit(cfg, [m['attempt_id']], fake)
    assert len(checks) == 2 and [claimed for _, claimed in checks] == [False, True]
    operations = fake.operations()
    assert operations.count('nodes') == 2 and operations.count('submit') == 1 and 'cancel' not in operations
    assert checks[0][0] < operations.index('create_attempt') < checks[1][0] < operations.index('submit')
    assert max(i for i, op in enumerate(operations) if op == 'metadata') < checks[1][0]
    assert (path/'submission.json').exists() and state.read(path)['state'] == 'submitted'
    assert all(p.read_bytes() == data for p, data in immutable.items())
    assert attempt.verified_files(cfg, path, m)
    before = len(fake.calls)
    with pytest.raises(ValueError, match='consumed'):
        submit.submit(cfg, [m['attempt_id']], fake)
    assert len(fake.calls) == before


@pytest.mark.parametrize('when', ['confirmation', 'upload'])
@pytest.mark.parametrize('bad', ['slots', 'memory', 'missing', 'duplicate', 'offline'])
def test_spec_or_identity_change_still_stops_submit(targeted, monkeypatch, when, bad):
    cfg, path, m = prepared(targeted)
    fake = TargetFake(cfg)
    original_upload = fake.upload
    def change():
        fake.node_text = dict(slots=nodes(slots=64), memory=nodes(memory='49151mb'),
                             missing='', duplicate=nodes()+nodes(),
                             offline=nodes().replace('state = free', 'state = offline'))[bad]
    def confirmation(_):
        if when == 'confirmation': change()
        return True
    def upload(*args):
        original_upload(*args)
        if when == 'upload': change()
    fake.upload = upload
    monkeypatch.setattr(confirm, 'confirm', confirmation)
    with pytest.raises(ValueError):
        submit.submit(cfg, [m['attempt_id']], fake)
    assert 'submit' not in fake.operations() and 'cancel' not in fake.operations()
    assert (path/'.submit-claim').exists() is (when == 'upload')
    assert state.read(path)['state'] == ('failed_presubmit' if when == 'upload' else 'prepared')
    assert attempt.verified_files(cfg, path, m)


@pytest.mark.parametrize('cap', ['max_committed_cores', 'max_queued_cores'])
def test_shared_node_does_not_bypass_account_caps(targeted, monkeypatch, cap):
    cfg, path, m = prepared(targeted)
    cfg['resources'][cap] = 48 if cap == 'max_committed_cores' else 24
    fake = TargetFake(cfg)
    fake.node_text, jobs = shared_observation(used=40, owners=('fixture', 'fixture'))
    if cap == 'max_queued_cores':
        jobs = jobs.replace('Job_Owner = peer@fixture', 'Job_Owner = fixture@fixture')
    fake.qstat = Result(stdout=jobs)
    monkeypatch.setattr(confirm, 'confirm', lambda _: pytest.fail('Must reject before confirmation'))
    with pytest.raises(ValueError, match='[Cc]ore limit'):
        submit.submit(cfg, [m['attempt_id']], fake)
    assert not (path/'.submit-claim').exists() and 'submit' not in fake.operations()


def test_targeted_shared_entry_uses_smallest_account_cap(targeted, monkeypatch):
    cfg, path, m = prepared(targeted)
    entry = {k: deepcopy(v) for k, v in cfg.items() if k not in ('local', '_config_dir')}
    peer = deepcopy(entry)
    peer['resources']['max_committed_cores'] = 48
    combined = dict(local=cfg['local'], _config_dir=cfg['_config_dir'],
                    clusters=dict(default=entry, peer=peer))
    fake = TargetFake(combined)
    fake.node_text, jobs = shared_observation(used=40, owners=('fixture', 'fixture'))
    fake.qstat = Result(stdout=jobs)
    monkeypatch.setattr(confirm, 'confirm', lambda _: pytest.fail('Must reject shared cap before confirmation'))
    with pytest.raises(ValueError, match='Core limit'):
        submit.submit(combined, [m['attempt_id']], fake)
    assert not (path/'.submit-claim').exists() and 'submit' not in fake.operations()


@pytest.mark.parametrize('failure', ['hash', 'confirmation', 'denied', 'restricted'])
def test_sharing_preserves_hash_approval_and_policy_checks(targeted, monkeypatch, failure):
    cfg, path, m = prepared(targeted)
    fake = TargetFake(cfg)
    fake.node_text, jobs = shared_observation()
    fake.qstat = Result(stdout=jobs)
    if failure == 'hash': fake.upload_corrupt = True
    def confirmation(_):
        if failure == 'denied': cfg['node_targeting']['denied_nodes'].append('compute-a')
        if failure == 'restricted': cfg['node_targeting']['restricted_nodes'].append('compute-a')
        return failure != 'confirmation'
    monkeypatch.setattr(confirm, 'confirm', confirmation)
    with pytest.raises(ValueError):
        submit.submit(cfg, [m['attempt_id']], fake)
    assert 'submit' not in fake.operations() and 'cancel' not in fake.operations()
    assert (path/'.submit-claim').exists() is (failure == 'hash')


def test_explicit_approval_still_binds_and_consumes_once_for_sharing(targeted):
    cfg, path, m = prepared(targeted)
    record = approval.create(cfg, 'target-demo', [m['attempt_id']], 'Approve synthetic target only', 1)
    fake = TargetFake(cfg)
    fake.node_text, jobs = shared_observation(used=40, memory=None)
    fake.qstat = Result(stdout=jobs)
    submit.submit(cfg, [m['attempt_id']], fake, approval_id=record['id'])
    assert (path.parent.parent/'approvals'/f"{record['id']}.used").exists()
    binding = json.loads((path/'submission.json').read_text())
    assert binding['authorization']['method'] == 'approval'
    assert fake.operations().count('nodes') == 2 and fake.operations().count('submit') == 1


def test_hidden_occupation_across_nodes_preserves_independent_empty_target(targeted):
    cfg, args = targeted
    names = ['maple', 'ash', 'elm', 'willow']
    cfg['node_targeting'] = dict(allowed_nodes=names, denied_nodes=[], restricted_nodes=[],
                                 priority=[names])
    raw = ''.join(nodes(extra=extra).replace('compute-a', name) for name, extra in zip(names, [
        '    jobs = 0-23/301.fixture\n', '    jobs = 0-47/302.fixture\n',
        '    jobs = 0-15/303.fixture\n', '']))
    qstat = ('Job Id: 303.fixture\n    Job_Owner = fixture@fixture\n    job_state = R\n'
             '    exec_host = elm/0-15\n    Resource_List.mem = 32gb\n')
    rows = nt.strict_nodes(raw, status.parse_jobs(qstat))
    snapshot(cfg, rows)
    candidates = nt.candidates(cfg)['nodes']
    assert [r['cores_used'] for r in rows] == [24, 48, 16, 0]
    assert [r['mem_assigned_bytes'] for r in rows] == [None, None, 32 * 1024**3, 0]
    assert [r['selectable'] for r in candidates] == [False, False, True, True]
    for candidate in candidates[:2]:
        assert candidate['status'] == 'occupied'
        reason = candidate['selectable_reason']
        assert 'absent from qstat' in reason and 'ownership' in reason
        option = candidate['options'][0]['capacity']
        assert option['fits_total'] and option['availability'] == 'unknown'
        with pytest.raises(ValueError, match='absent from qstat'):
            attempt.prepare(cfg, **(args | dict(target_node=candidate['name'])))
    assert not list(Path(cfg['local']['studies_root']).rglob('manifest.json'))
    assert attempt.prepare(cfg, **(args | dict(target_node='willow')))['node_target']['name'] == 'willow'


@pytest.mark.parametrize('listed,hosts,owner,issue', [
    ('4-7/301.fixture', 'maple/7+maple/4-6', 'peer@fixture', None),
    ('4-7/301.fixture', 'maple/0-3', 'peer@fixture', 'conflicting_allocation'),
    ('4-5/301.fixture,4-5/301.fixture', 'maple/4-7', 'peer@fixture', 'conflicting_allocation'),
    ('4-7/301.fixture', 'maple/4-5+maple/4-5', 'peer@fixture', 'conflicting_allocation'),
    ('48/301.fixture', 'maple/48', 'peer@fixture', 'conflicting_allocation'),
    ('4-7/301.fixture', 'maple/4-7', '', 'ambiguous_jobs'),
    ('4-7/301.fixture', 'maple/4-7', '@fixture', 'ambiguous_jobs'),
    ('4-7/301.fixture,7/302.fixture', 'maple/4-7', 'peer@fixture', 'conflicting_allocation'),
    ('4-7/301.fixture,8/302.fixture', 'maple/4-7', 'peer@fixture', 'unseen_node_jobs'),
])
def test_per_job_slot_ownership_even_at_equal_counts(listed, hosts, owner, issue):
    raw = nodes(extra=f'    jobs = {listed}\n').replace('compute-a', 'maple')
    jobs = [dict(job_id='301.fixture', job_state='R', exec_host=hosts, Job_Owner=owner,
                 **{'Resource_List.mem': '16gb'})]
    node = nt.strict_nodes(raw, jobs)[0]
    assert node['targeting_issue'] == issue
    decision = nt.admission(node, 24, 48)
    assert decision['selectable'] is (issue is None)
    assert decision['capacity']['availability'] == ('enough' if issue is None else 'unknown')


def test_occupied_cache_without_per_job_checks_needs_new_observation(targeted):
    cfg, args = targeted
    raw, qstat = shared_observation()
    row = nt.strict_nodes(raw, status.parse_jobs(qstat))[0]
    del row['targeting_issue']
    snapshot(cfg, [row])
    assert not nt.candidates(cfg)['nodes'][1]['selectable']
    assert capacity.assess(cfg, 'default', 'general')['availability'] == 'unknown'
    with pytest.raises(ValueError, match='Older snapshot'):
        attempt.prepare(cfg, **args)


def test_job_disappears_from_detail_after_upload_does_not_dispatch(targeted, monkeypatch):
    cfg, path, manifest = prepared(targeted)
    fake = TargetFake(cfg)
    fake.node_text, detail = shared_observation(owners=('peer', 'peer'))
    fake.qstat = Result(stdout=detail)
    original_upload = fake.upload
    def upload(*args):
        original_upload(*args)
        fake.qstat = Result()
    fake.upload = upload
    monkeypatch.setattr(confirm, 'confirm', lambda _: True)
    with pytest.raises(ValueError, match='after upload, before qsub.*ownership is unknown'):
        submit.submit(cfg, [manifest['attempt_id']], fake)
    assert (path/'.submit-claim').exists() and not (path/'submission.json').exists()
    assert state.read(path)['state'] == 'failed_presubmit'
    assert fake.operations().count('nodes') == 2 and 'submit' not in fake.operations()

@pytest.mark.parametrize('assigned,expected', [(None, 'unknown'), ('8gb', 'enough'), ('120gb', 'queue')])
def test_explicit_node_memory_is_independent_of_missing_owner(assigned, expected):
    raw = nodes(extra='    jobs = 0-7/312.fixture\n')
    if assigned is not None:
        raw += f'    resources_assigned.mem = {assigned}\n'
    node = nt.strict_nodes(raw, [])[0]
    decision = nt.admission(node, 24, 48)
    assert node['cores_used'] == 8 and not decision['selectable']
    assert decision['capacity']['fits_total'] and decision['capacity']['availability'] == expected


def queue_site(cfg):
    cfg['node_targeting']['occupied_policy'] = dict(
        server='fixture', queue='batch', queue_nodes=['compute-a'], empty_only=['compute-b'])


class OwnListFake(TargetFake):
    def __init__(self, cfg):
        super().__init__(cfg)
        self.node_text = nodes(extra='    jobs = 0-3/833.fixture,4-11/834.fixture\n')
        self.qstat = Result(stdout='Job Id: 833.fixture\n    Job_Owner = fixture@fixture\n'
                            '    Job_Name = synthetic\n    job_state = R\n    queue = batch\n'
                            '    Resource_List.nodes = compute-a:ppn=4\n    exec_host = compute-a/0-3\n')
        self.account = Result(stdout='AG_OWNER fixture\n833.fixture\nAG_END\n')
        self.queue_text = 'Queue Tot Que Run\nbatch 3 1 2\n'

    def run(self, command):
        from ag import remote
        if command == remote.pbs_own_jobs():
            self.calls.append(command)
            return self.account
        if command == remote.queues():
            self.calls.append(command)
            return Result(stdout=self.queue_text)
        return super().run(command)


def test_site_permitted_queue_with_restricted_details_full_submission(targeted, monkeypatch):
    from ag import autonomy_submission, remote, route
    cfg, args = targeted
    queue_site(cfg)
    cfg['resources']['max_committed_cores'] = 28
    # Existing machine registry, no real SSH or account settings.
    with autonomy_submission.machine_lock():
        pass
    monkeypatch.setattr(config, 'ssh_identity', lambda _: ('fixture', 22, 'fixture'))
    fake = OwnListFake(cfg)
    sample = monitor.observation(cfg, fake, 'fixture')
    assert sample['cluster']['job_summary']['others_queued_jobs'] is None
    snapshot(cfg, sample['cluster']['nodes'])
    cached = Path(cfg['local']['studies_root']) / '.ag-monitor/latest.json'
    data = json.loads(cached.read_text())
    data.update(sample)
    cached.write_text(json.dumps(data))
    cfg['routing'] = dict(gaussian=['default'])
    option = nt.candidates(cfg)['nodes'][1]['options'][0]
    assert option['selectable'] and option['capacity']['availability'] == 'unknown'
    suggestion = route.suggest(cfg, 'gaussian', 'general')
    assert suggestion['recommendation']['needs_queue']
    assert suggestion['clusters'][0]['specification_allowed']
    m = attempt.prepare(cfg, **args)
    fake.job = Result(stdout=f"Job Id: 123.fixture\n    Job_Name = {m['pbs_job_name']}\n    job_state = Q\n")
    monkeypatch.setattr(confirm, 'confirm', lambda _: True)
    submit.submit(cfg, [m['attempt_id']], fake)
    assert fake.calls.count(remote.pbs_own_jobs()) == 3  # sample and both fresh checks
    assert fake.calls.count(remote.queues()) == 1  # queue-permitted target needs no empty-queue proof
    assert fake.operations().count('submit') == 1 and 'cancel' not in fake.operations()
    path = attempt.find(cfg, m['attempt_id'])
    assert state.read(path)['state'] == 'submitted' and state.read(path)['node_placement']['state'] == 'pending'
    assert attempt.verified_files(cfg, path, m)


@pytest.mark.parametrize('reply', [
    Result(1, '', 'unavailable'), Result(stdout=''), Result(stdout='AG_OWNER another\nAG_END\n'),
    Result(stdout='AG_OWNER fixture\n833.fixture\n'), Result(stdout='AG_OWNER fixture\nAG_END\n'),
    Result(stdout='AG_OWNER fixture\n833.fixture\n833.fixture\nAG_END\n'),
    Result(stdout='AG_OWNER fixture\n833.fixture\n834.fixture\nAG_END\n'),
    Result(stdout='AG_OWNER fixture\n833[]\nAG_END\n'),
    Result(stdout='AG_OWNER fixture\n833.fixt\nAG_END\n'),
])
def test_partial_failed_or_conflicting_owner_proof_blocks_hidden_queue(targeted, reply):
    cfg, args = targeted
    queue_site(cfg)
    fake = OwnListFake(cfg)
    fake.account = reply
    rows = monitor.observation(cfg, fake, 'fixture')['cluster']['nodes']
    snapshot(cfg, rows)
    assert not nt.candidates(cfg)['nodes'][1]['selectable']
    with pytest.raises(ValueError, match='login-account'):
        attempt.prepare(cfg, **args)


def test_fixed_pbs_selector_uses_only_actual_login(tmp_path):
    from ag import remote
    from ag.transport import READ_OPERATIONS
    cmd = remote.pbs_own_jobs()
    assert cmd.operation == 'jobs' and cmd.operation in READ_OPERATIONS
    assert cmd.text == ('ag_user=$(id -un) && case "$ag_user" in ""|-*|*[!A-Za-z0-9_.-]*) exit 1;; esac && '
                        'printf "AG_OWNER %s\\n" "$ag_user" && qselect -u "$ag_user" && printf "AG_END\\n"')
    with pytest.raises(TypeError):
        remote.pbs_own_jobs('another')
    script = tmp_path / 'qselect'
    script.write_text('#!/bin/sh\ntest "$#" -eq 2 && test "$1" = -u && test "$2" = "$(id -un)"\n')
    script.chmod(0o700)
    result = subprocess.run(['/bin/sh', '-c', cmd.text], capture_output=True, text=True,
                            env={'PATH': f'{tmp_path}:/usr/bin:/bin'})
    assert result.returncode == 0 and result.stdout.splitlines()[-1] == 'AG_END'


@pytest.mark.parametrize('bad', ['queue', 'server', 'duplicate', 'unknown', 'overlap'])
def test_occupied_site_policy_requires_exact_queue_and_nodes(targeted, bad):
    cfg, _ = targeted
    queue_site(cfg)
    site = cfg['node_targeting']['occupied_policy']
    site.update(dict(queue=dict(queue='other'), server=dict(server='bad..suffix'),
                     duplicate=dict(queue_nodes=['compute-a']*2), unknown=dict(empty_only=['elsewhere']),
                     overlap=dict(empty_only=['compute-a']))[bad])
    with pytest.raises(ValueError, match='policy'):
        nt.validate_policy(cfg)


def test_named_config_normalizes_queue_for_occupied_policy(targeted):
    cfg, _ = targeted
    queue_site(cfg)
    cfg.update(scheduler='pbs', queue='batch')
    config.validate_cluster(cfg)
    assert cfg['scheduler'] == dict(queue='batch')


@pytest.mark.parametrize('bad', ['abbreviated', 'array', 'other-server', 'same-sequence'])
def test_unseen_ids_cannot_be_aliases_or_arrays(targeted, bad):
    cfg, _ = targeted
    queue_site(cfg)
    fake = OwnListFake(cfg)
    fake.node_text = fake.node_text.replace('834.fixture', {
        'abbreviated':'834', 'array':'834[2].fixture', 'other-server':'834.another',
        'same-sequence':'833.another'}[bad])
    rows = monitor.observation(cfg, fake, 'fixture')['cluster']['nodes']
    assert rows[0]['targeting_issue'] == 'ambiguous_jobs'
    assert not nt.admission(rows[0], 24, 48, cfg)['selectable']


def test_site_empty_only_still_offers_empty_allowed_node(targeted, monkeypatch):
    from ag import autonomy_submission
    cfg, _ = targeted
    queue_site(cfg)
    with autonomy_submission.machine_lock():
        pass
    monkeypatch.setattr(config, 'ssh_identity', lambda _: ('fixture', 22, 'fixture'))
    fake = OwnListFake(cfg)
    fake.node_text += (nodes(extra='    jobs = 0-1/835.fixture\n').replace('compute-a', 'compute-b')
                       + nodes().replace('compute-a', 'compute-c'))
    snapshot(cfg, monitor.observation(cfg, fake, 'fixture')['cluster']['nodes'])
    restricted, _, empty = nt.candidates(cfg)['nodes'][:3]
    assert not restricted['selectable'] and 'empty node' in restricted['selectable_reason']
    assert empty['selectable']


@pytest.mark.parametrize('when', ['confirmation', 'upload'])
def test_own_job_appearing_during_submission_rechecks_shared_caps(targeted, monkeypatch, when):
    from ag import remote
    cfg, path, m = prepared(targeted)
    queue_site(cfg)
    monkeypatch.setattr(config, 'ssh_identity', lambda _: ('fixture', 22, 'fixture'))
    cfg['resources']['max_queued_cores'] = 24
    fake = OwnListFake(cfg)
    def add_waiter():
        fake.qstat = Result(stdout=fake.qstat.stdout +
            'Job Id: 835.fixture\n    Job_Owner = fixture@fixture\n    job_state = H\n'
            '    Job_Name = synthetic\n    Resource_List.nodes = 1:ppn=1\n')
        fake.account = Result(stdout='AG_OWNER fixture\n833.fixture\n835.fixture\nAG_END\n')
    def confirm_request(_):
        if when == 'confirmation':
            add_waiter()
        return True
    original_upload = fake.upload
    def upload(*args):
        original_upload(*args)
        if when == 'upload' and '835.fixture' not in fake.account.stdout:
            add_waiter()
    fake.upload = upload
    monkeypatch.setattr(confirm, 'confirm', confirm_request)
    with pytest.raises(ValueError, match='queued core limit exceeded'):
        submit.submit(cfg, [m['attempt_id']], fake)
    assert fake.calls.count(remote.pbs_own_jobs()) == (2 if when == 'upload' else 1)
    assert ('upload' in fake.operations()) is (when == 'upload')
    assert (path/'.submit-claim').exists() is (when == 'upload')
    assert 'submit' not in fake.operations()


def test_hidden_queue_counts_other_entry_unobserved_reservation(targeted, monkeypatch):
    from ag import remote
    cfg, args = targeted
    # Create a real local synthetic binding under a second entry, on the same
    # account. Hold it even when both scheduler queries omit that job.
    entry = {k: deepcopy(v) for k, v in cfg.items() if k not in ('local', '_config_dir')}
    del entry['node_targeting']
    combined = dict(local=cfg['local'], _config_dir=cfg['_config_dir'], clusters=dict(
        default=entry, peer=deepcopy(entry)))
    app = args | dict(cluster='peer', target_node=None)
    peer = attempt.prepare(combined, **app)
    monkeypatch.setattr(confirm, 'confirm', lambda _: True)
    submit.submit(combined, [peer['attempt_id']], Fake(combined))
    entry['node_targeting'] = policy()
    queue_site(entry)
    combined['clusters']['peer']['resources']['max_committed_cores'] = 48
    selected = config.select_cluster(combined)
    monkeypatch.setattr(config, 'ssh_identity', lambda _: ('fixture', 22, 'fixture'))
    fake = OwnListFake(selected)
    result = monitor.observation(selected, fake, 'fixture')
    occupied = result['cluster']['nodes'][0]
    assert occupied['occupied_queue_account']['committed'] == 4 + 24
    assert occupied['occupied_queue_account']['queued'] == 24
    assert fake.calls.count(remote.pbs_own_jobs()) == 1
    assert not nt.admission(occupied, 24, 48, selected)['selectable']
    assert nt.admission(occupied, 12, 24, selected)['selectable']


@pytest.mark.parametrize('issue', ['missing-detail', 'requested-vs-allocated', 'another-node'])
@pytest.mark.parametrize('phase', ['prepare', 'confirmation', 'upload'])
def test_account_conflicts_reject_even_empty_target(targeted, monkeypatch, issue, phase):
    from ag import autonomy_submission
    cfg, args = targeted
    queue_site(cfg)
    with autonomy_submission.machine_lock():
        pass
    monkeypatch.setattr(config, 'ssh_identity', lambda _: ('fixture', 22, 'fixture'))
    cfg['resources']['max_committed_cores'] = 28
    fake = OwnListFake(cfg)
    fake.queue_text = 'Queue Tot Que Run\nbatch 2 0 2\n'
    fake.node_text += nodes().replace('compute-a', 'compute-b')
    args = args | dict(target_node='compute-b')
    def conflict():
        if issue == 'missing-detail':
            fake.account = Result(stdout='AG_OWNER fixture\n833.fixture\n834.fixture\nAG_END\n')
        elif issue == 'requested-vs-allocated':
            fake.node_text = fake.node_text.replace('0-3/833.fixture,4-11', '0-15/833.fixture,16-23')
            fake.qstat = Result(stdout=fake.qstat.stdout.replace('compute-a/0-3', 'compute-a/0-15'))
        else:
            fake.node_text += nodes(extra='    jobs = 0-7/833.fixture\n').replace('compute-a', 'compute-c')
    if phase == 'prepare':
        conflict()
    snapshot(cfg, monitor.observation(cfg, fake, 'fixture')['cluster']['nodes'])
    if phase == 'prepare':
        with pytest.raises(ValueError, match='login-account'):
            attempt.prepare(cfg, **args)
    else:
        manifest = attempt.prepare(cfg, **args)
        def clicked(_):
            if phase == 'confirmation':
                conflict()
            return True
        monkeypatch.setattr(confirm, 'confirm', clicked)
        upload = fake.upload
        def transfer(*args):
            upload(*args)
            if phase == 'upload' and fake.operations().count('upload') == 1:
                conflict()
        fake.upload = transfer
        stage = 'after confirmation' if phase == 'confirmation' else 'after upload, before qsub'
        with pytest.raises(ValueError, match=stage + '.*login-account'):
            submit.submit(cfg, [manifest['attempt_id']], fake)
        path = attempt.find(cfg, manifest['attempt_id'])
        assert state.read(path)['state'] == ('prepared' if phase == 'confirmation' else 'failed_presubmit')
        assert (path / '.submit-claim').exists() is (phase == 'upload')
    assert fake.operations().count('submit') == 0


def test_peer_completed_array_outside_target_does_not_block_queue(targeted, monkeypatch):
    from ag import autonomy_submission
    cfg, args = targeted
    queue_site(cfg)
    with autonomy_submission.machine_lock():
        pass
    monkeypatch.setattr(config, 'ssh_identity', lambda _: ('fixture', 22, 'fixture'))
    fake = OwnListFake(cfg)
    fake.qstat = Result(stdout=fake.qstat.stdout +
        'Job Id: 999[5].fixture\n    Job_Owner = peer@fixture\n    Job_Name = old\n    job_state = C\n')
    snapshot(cfg, monitor.observation(cfg, fake, 'fixture')['cluster']['nodes'])
    manifest = attempt.prepare(cfg, **args)
    fake.job = Result(stdout=f"Job Id: 123.fixture\n    Job_Name = {manifest['pbs_job_name']}\n    job_state = Q\n")
    monkeypatch.setattr(confirm, 'confirm', lambda _: True)
    submit.submit(cfg, [manifest['attempt_id']], fake)
    assert fake.operations().count('submit') == 1
    fake.node_text = fake.node_text.replace('834.fixture', '999[5].fixture')
    assert not nt.admission(monitor.observation(cfg, fake, 'fixture')['cluster']['nodes'][0], 24, 48, cfg)['selectable']
    fake.qstat = Result(stdout=fake.qstat.stdout.replace('peer@fixture', 'fixture@fixture'))
    with pytest.raises(ValueError, match='数组'):
        monitor.observation(cfg, fake, 'fixture')


@pytest.mark.parametrize('phase', ['prepare', 'confirmation', 'upload'])
def test_closed_manual_writer_in_other_root_retains_accepted_cores(targeted, monkeypatch, tmp_path, phase):
    cfg, args = targeted
    queue_site(cfg)
    cfg['resources']['max_committed_cores'] = 48
    monkeypatch.setattr(config, 'ssh_identity', lambda _: ('fixture', 22, 'fixture'))
    other = deepcopy(cfg)
    del other['node_targeting']
    other['local']['studies_root'] = str(tmp_path / 'other-studies')
    other['_config_dir'] = str(tmp_path / 'other-config')
    Path(other['_config_dir']).mkdir()
    study.init(other, 'peer-study')
    peer = attempt.prepare(other, **(args | dict(study_name='peer-study', target_node=None)))
    fake = OwnListFake(cfg)
    def observe():
        row, = monitor.observation(cfg, fake, 'fixture')['cluster']['nodes']
        snapshot(cfg, [row])
        return row
    # A closed prepare writer has no consumed submission.
    row = observe()
    assert row['occupied_queue_account']['committed'] == 4 and nt.admission(row, 24, 48, cfg)['selectable']
    def accept_peer():
        otherfake = Fake(other)
        otherfake.qsub = Result(stdout='567.fixture\n')
        with monkeypatch.context() as patch:
            patch.setattr(confirm, 'confirm', lambda _: True)
            submit.submit(other, [peer['attempt_id']], otherfake)
        assert otherfake.operations().count('submit') == 1
        assert state.read(attempt.find(other, peer['attempt_id']))['state'] == 'submitted'
    if phase == 'prepare':
        accept_peer()
        row = observe()
        assert row['occupied_queue_account']['committed'] == 28
        assert nt.admission(row, 12, 24, cfg)['selectable']
        with pytest.raises(ValueError, match='core limit exceeded'):
            attempt.prepare(cfg, **args)
    else:
        manifest = attempt.prepare(cfg, **args)
        def clicked(_):
            if phase == 'confirmation':
                accept_peer()
            return True
        monkeypatch.setattr(confirm, 'confirm', clicked)
        upload = fake.upload
        def transfer(*args):
            upload(*args)
            if phase == 'upload' and fake.operations().count('upload') == 1:
                accept_peer()
        fake.upload = transfer
        stage = 'after confirmation' if phase == 'confirmation' else 'after upload, before qsub'
        with pytest.raises(ValueError, match=stage + '.*core limit exceeded'):
            submit.submit(cfg, [manifest['attempt_id']], fake)
        path = attempt.find(cfg, manifest['attempt_id'])
        assert state.read(path)['state'] == ('prepared' if phase == 'confirmation' else 'failed_presubmit')
        assert (path / '.submit-claim').exists() is (phase == 'upload')
    assert fake.operations().count('submit') == 0


def test_visible_allocation_conflict_on_different_node_without_site_policy(targeted):
    cfg, args = targeted
    fake = OwnListFake(cfg)
    fake.node_text += nodes().replace('compute-a', 'compute-b')
    fake.qstat = Result(stdout=fake.qstat.stdout.replace('ppn=4', 'ppn=1'))
    snapshot(cfg, monitor.observation(cfg, fake, 'fixture')['cluster']['nodes'])
    with pytest.raises(ValueError, match='allocated slots disagree'):
        attempt.prepare(cfg, **(args | dict(target_node='compute-b')))
    assert fake.operations().count('submit') == 0


def test_generic_peer_cannot_bypass_own_inventory_conflict(targeted, monkeypatch):
    cfg, args = targeted
    queue_site(cfg)
    entry = {k: deepcopy(v) for k, v in cfg.items() if k not in ('local', '_config_dir')}
    peer = {k: deepcopy(v) for k, v in entry.items() if k != 'node_targeting'}
    combined = dict(local=cfg['local'], _config_dir=cfg['_config_dir'], clusters=dict(default=entry, peer=peer))
    m = attempt.prepare(combined, **(args | dict(cluster='peer', target_node=None)))
    selected = config.select_cluster(combined, 'peer')
    fake = OwnListFake(selected)
    fake.account = Result(stdout='AG_OWNER fixture\n833.fixture\n834.fixture\nAG_END\n')
    monkeypatch.setattr(confirm, 'confirm', lambda _: True)
    with pytest.raises(ValueError, match='after confirmation.*login-account'):
        submit.submit(combined, [m['attempt_id']], fake)
    assert fake.operations().count('submit') == 0


@pytest.mark.parametrize('case', ['over-cap', 'at-cap', 'unverifiable-at-dialog', 'redirected-sibling', 'wrong-registered-root',
                                  'remount-at-cap', 'remount-confirmation', 'remount-upload', 'remount-parent'])
def test_known_manual_root_includes_pre_registry_siblings(targeted, monkeypatch, tmp_path, case):
    from contextlib import nullcontext
    from ag import autonomy, autonomy_submission as records
    cfg, args = targeted
    queue_site(cfg)
    monkeypatch.setattr(config, 'ssh_identity', lambda _: ('fixture', 22, 'fixture'))
    monkeypatch.setattr(confirm, 'confirm', lambda _: True)
    remount = case.startswith('remount-')
    cfg['resources']['max_committed_cores'] = 52 if remount or case in ('at-cap', 'unverifiable-at-dialog') else 48
    cfg['resources']['max_queued_cores'] = 48
    other = deepcopy(cfg)
    del other['node_targeting']
    root = tmp_path / 'other-studies'
    other['local']['studies_root'] = str(root)
    other['_config_dir'] = str(tmp_path / 'other-config')
    Path(other['_config_dir']).mkdir()
    study.init(other, 'registered')
    stable = ['a' * 64]
    if remount:
        foreign_inode = (root / 'registered').stat().st_ino
        monkeypatch.setattr(records._study_directory, 'apfs_object_digest', lambda fd, ino: stable[0] if ino == foreign_inode else f'{ino:064x}')
    with autonomy.manual_write_guard(other, 'registered', action='prepare'):
        pass
    # Reproduce the durable pre-registry layout with the real Attempt, claim,
    # summary and scheduler binding. No writer record existed on that version.
    study.init(other, 'older')
    with monkeypatch.context() as legacy:
        legacy.setattr(autonomy, 'manual_write_guard', lambda *args, **kwargs: nullcontext())
        m = attempt.prepare(other, **(args | dict(study_name='older', target_node=None)))
        accepted = Fake(other)
        accepted.qsub = Result(stdout='567.fixture\n')
        submit.submit(other, [m['attempt_id']], accepted)
    path = attempt.find(other, m['attempt_id'])
    assert records.audit(path)['job_id'] == 'default:567.fixture'
    writers = Path.home() / '.config/ag/manual-writers'
    assert not (writers / records.study_identity(root / 'older')['study_key']).exists()
    if remount:
        actual = records.study_identity
        def current(path, *, apfs=False):
            identity = actual(path, apfs=apfs)
            if Path(path) == root / 'registered':
                identity['study_device'] += 1
            return identity
        monkeypatch.setattr(records, 'study_identity', current)
    if case == 'remount-parent':
        previous = root.with_name('previous-root')
        root.rename(previous)
        root.mkdir()
        (previous / 'registered').rename(root / 'registered')
        assert records.audit(previous / 'older' / 'attempts' / m['attempt_id'])['retained_cores'] == 24
    if case == 'redirected-sibling':
        (root / 'redirect').symlink_to(tmp_path, target_is_directory=True)
    elif case == 'wrong-registered-root':
        location = writers / records.study_identity(root / 'registered')['study_key']
        claim_path, = location.glob('*.claim.json')
        claim = json.loads(claim_path.read_bytes())
        claim['study_path'] = str(root / 'older')
        claim_path.write_bytes(records.disk.encode(claim))
    fake = OwnListFake(cfg)
    fake.queue_text = 'Queue Tot Que Run\nbatch 2 0 2\n'
    fake.node_text += nodes().replace('compute-a', 'compute-b')
    rows = monitor.observation(cfg, fake, 'fixture')['cluster']['nodes']
    snapshot(cfg, rows)
    requested = args | dict(target_node='compute-b')
    if case in ('redirected-sibling', 'wrong-registered-root', 'remount-parent'):
        with pytest.raises(ValueError, match='reservations could not be verified'):
            attempt.prepare(cfg, **requested)
    else:
        assert rows[1]['occupied_queue_account']['committed'] == 28
        if remount or case in ('at-cap', 'unverifiable-at-dialog'):
            target = attempt.prepare(cfg, **requested)
            fake.job = Result(stdout=f"Job Id: 123.fixture\n    Job_Name = {target['pbs_job_name']}\n    job_state = Q\n")
            dialogs = []
            def click(text):
                dialogs.append(text)
                if case == 'remount-confirmation':
                    stable[0] = 'b' * 64
                return True
            monkeypatch.setattr(confirm, 'confirm', click)
            if case == 'remount-upload':
                upload = fake.upload
                def transfer(*args):
                    upload(*args)
                    stable[0] = 'b' * 64
                fake.upload = transfer
            if case in ('remount-confirmation', 'remount-upload'):
                stage = 'after confirmation' if case == 'remount-confirmation' else 'after upload, before qsub'
                with pytest.raises(ValueError, match=stage + '.*reservations could not be verified'):
                    submit.submit(cfg, [target['attempt_id']], fake)
            elif case in ('at-cap', 'remount-at-cap'):
                submit.submit(cfg, [target['attempt_id']], fake)
                assert state.read(attempt.find(cfg, target['attempt_id']))['node_placement']['state'] == 'pending'
            else:
                (root / 'redirect').symlink_to(tmp_path, target_is_directory=True)
                with pytest.raises(ValueError, match='after confirmation.*reservations could not be verified'):
                    submit.submit(cfg, [target['attempt_id']], fake)
            text, = dialogs
            assert '已观测本人作业 4 核（运行 4、排队 0）' in text and '本次申请 24 核' in text
            assert '提交后合计 28' not in text and '最多 28 核' not in text
            if remount or case == 'at-cap':
                assert '未回显预留 24 核' in text and '小计 52 / 上限 52 核' in text
                assert '小计 48 / 排队上限 48 核' in text
            else:
                assert '未回显预留尚待核验' in text and '小计 28 / 上限 52 核' in text
                assert '完整账号占用尚待核验' in text and '未回显预留 0 核' not in text
        else:
            with pytest.raises(ValueError, match='shared-account core limit exceeded'):
                attempt.prepare(cfg, **requested)
    assert fake.operations().count('submit') == (1 if case in ('at-cap', 'remount-at-cap') else 0)


@pytest.mark.parametrize('phase', ['prepare', 'confirmation', 'upload', 'empty', 'queue-permitted'])
def test_empty_only_honors_existing_named_waiter(targeted, monkeypatch, phase):
    from ag import autonomy_submission
    cfg, args = targeted
    queue_site(cfg)
    with autonomy_submission.machine_lock():
        pass
    monkeypatch.setattr(config, 'ssh_identity', lambda _: ('fixture', 22, 'fixture'))
    fake = OwnListFake(cfg)
    fake.queue_text = 'Queue Tot Que Run\nbatch 2 0 2\n'
    fake.node_text += nodes().replace('compute-a', 'compute-b')
    name = 'compute-a' if phase == 'queue-permitted' else 'compute-b'
    def enqueue():
        fake.queue_text = 'Queue Tot Que Run\nbatch 3 1 2\n'
        fake.qstat = Result(stdout=fake.qstat.stdout + 'Job Id: 893.fixture\n    Job_Owner = peer@fixture\n'
            f'    Job_Name = waiting\n    job_state = Q\n    Resource_List.nodes = {name}:ppn=12\n    queue = batch\n')
    if phase in ('prepare', 'queue-permitted'):
        enqueue()
    snapshot(cfg, monitor.observation(cfg, fake, 'fixture')['cluster']['nodes'])
    candidate = next(n for n in nt.candidates(cfg)['nodes'] if n['name'] == name)
    assert candidate['selectable'] is (phase != 'prepare')
    if phase == 'prepare':
        assert candidate['status'] == 'occupied'
        with pytest.raises(ValueError, match='only to an empty node'):
            attempt.prepare(cfg, **(args | dict(target_node=name)))
    else:
        m = attempt.prepare(cfg, **(args | dict(target_node=name)))
        fake.job = Result(stdout=f"Job Id: 123.fixture\n    Job_Name = {m['pbs_job_name']}\n    job_state = Q\n")
        def click(_):
            if phase == 'confirmation':
                enqueue()
            return True
        monkeypatch.setattr(confirm, 'confirm', click)
        upload = fake.upload
        def transfer(*args):
            upload(*args)
            if phase == 'upload' and fake.operations().count('upload') == 1:
                enqueue()
        fake.upload = transfer
        if phase in ('confirmation', 'upload'):
            stage = 'after confirmation' if phase == 'confirmation' else 'after upload, before qsub'
            with pytest.raises(ValueError, match=stage + '.*only to an empty node'):
                submit.submit(cfg, [m['attempt_id']], fake)
            path = attempt.find(cfg, m['attempt_id'])
            assert state.read(path)['state'] == ('prepared' if phase == 'confirmation' else 'failed_presubmit')
        else:
            submit.submit(cfg, [m['attempt_id']], fake)
    assert fake.operations().count('submit') == (1 if phase in ('empty', 'queue-permitted') else 0)


@pytest.mark.parametrize('phase', ['prepare', 'confirmation', 'upload', 'elsewhere', 'other-queue'])
def test_empty_only_rechecks_visibility_of_target_queue_waiters(targeted, monkeypatch, phase):
    from ag import autonomy_submission, remote
    cfg, args = targeted
    queue_site(cfg)
    with autonomy_submission.machine_lock():
        pass
    monkeypatch.setattr(config, 'ssh_identity', lambda _: ('fixture', 22, 'fixture'))
    fake = OwnListFake(cfg)
    fake.node_text += nodes().replace('compute-a', 'compute-b')
    hidden = fake.queue_text
    if phase != 'prepare':
        fake.queue_text = 'Queue Tot Que Run\nbatch 2 0 2\n'
    if phase == 'elsewhere':
        fake.queue_text = hidden
        fake.qstat = Result(stdout=fake.qstat.stdout + 'Job Id: 893.fixture\n    Job_Owner = peer@fixture\n'
            '    job_state = Q\n    Resource_List.nodes = compute-a:ppn=12\n    queue = batch\n')
    if phase == 'other-queue':
        fake.queue_text += 'alternate 1 1 0\n'
    rows = monitor.observation(cfg, fake, 'fixture')['cluster']['nodes']
    snapshot(cfg, rows)
    requested = args | dict(target_node='compute-b')
    target = nt.candidates(cfg)['nodes'][0]
    assert target['options'][0]['capacity']['availability'] == 'enough'
    if phase == 'prepare':
        assert target['status'] == 'unknown' and not target['selectable']
        with pytest.raises(ValueError, match='queue waiting requests'):
            attempt.prepare(cfg, **requested)
    else:
        assert target['status'] == 'available' and target['selectable']
        m = attempt.prepare(cfg, **requested)
        fake.job = Result(stdout=f"Job Id: 123.fixture\n    Job_Name = {m['pbs_job_name']}\n    job_state = Q\n")
        def click(_):
            if phase == 'confirmation':
                fake.queue_text = hidden
            return True
        monkeypatch.setattr(confirm, 'confirm', click)
        upload = fake.upload
        def transfer(*args):
            upload(*args)
            if phase == 'upload':
                fake.queue_text = hidden
        fake.upload = transfer
        if phase in ('confirmation', 'upload'):
            stage = 'after confirmation' if phase == 'confirmation' else 'after upload, before qsub'
            with pytest.raises(ValueError, match=stage + '.*queue waiting requests'):
                submit.submit(cfg, [m['attempt_id']], fake)
            path = attempt.find(cfg, m['attempt_id'])
            assert state.read(path)['state'] == ('prepared' if phase == 'confirmation' else 'failed_presubmit')
            assert (path / '.submit-claim').exists() is (phase == 'upload')
        else:
            submit.submit(cfg, [m['attempt_id']], fake)
        assert fake.calls.count(remote.queues()) == (2 if phase == 'confirmation' else 3)
    assert fake.operations().count('submit') == (1 if phase in ('elsewhere', 'other-queue') else 0)


@pytest.mark.parametrize('queue_text,requests,proved', [
    ('batch 3 0 2 1 0 0 0', [], False),
    ('batch 3 0 2 1 0 0 0', [('H', 'compute-a:ppn=2')], True),
    ('batch 3 0 2 0 0 0 1', [], True),  # Hidden exiting job, no waiters.
    ('batch 3 0 2 0 0 0 0', [], False),  # Contradictory total.
    ('batch 3 1 2 0 0 0 0', [('Q', '')], False),
    ('batch 3 1 2 0 0 0 0', [('Q', 'compute-b.example:ppn=2')], False),
    ('batch 3 1 2 0 0 0 0', [('Q', '1:feature:ppn=2')], False),
    ('another 0 0 0 0 0 0 0', [], False),
])
def test_empty_only_queue_state_and_request_evidence(queue_text, requests, proved):
    from ag import pbs
    site = dict(queue='batch', server='fixture', empty_only=['compute-b'])
    jobs = [dict(job_id='8.fixture', queue='batch', job_state=state, **{'Resource_List.nodes': request})
            for state, request in requests]
    row = dict(name='compute-b')
    queues = monitor.parse_queues('Queue Tot Que Run Hld Wat Trn Ext\n' + queue_text,
                                  include_total=True, include_waiting=True)
    pbs.observe_empty_queue(site, [row], queues, jobs)
    assert (row['empty_only_waiters_checked'] == 'batch') is proved


@pytest.mark.parametrize('alternate', ['neednodes', 'host', 'select'])
def test_empty_only_waiting_job_has_competing_resource_identity(alternate):
    from ag import pbs
    row = dict(name='compute-b')
    job = dict(job_id='8.fixture', queue='batch', job_state='Q',
               **{'Resource_List.nodes': 'compute-a:ppn=2', 'Resource_List.' + alternate: 'compute-b'})
    pbs.observe_empty_queue(dict(queue='batch', server='fixture', empty_only=['compute-b']),
                            [row], [dict(name='batch', running=0, queued=1, total=1)], [job])
    assert row['empty_only_waiters_checked'] is None


def test_ambiguous_queue_columns_leave_empty_only_waiting_unverified():
    from ag import pbs
    row = dict(name='compute-b')
    queues = monitor.parse_queues('Queue Tot Que Run Que\nbatch 0 0 0 1',
                                  include_total=True, include_waiting=True)
    pbs.observe_empty_queue(dict(queue='batch', server='fixture', empty_only=['compute-b']), [row], queues, [])
    assert row['empty_only_waiters_checked'] is None
