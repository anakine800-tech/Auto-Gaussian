"""Synthetic PBS only. Never connect to a real scheduler."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
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
    source.write_text('%nprocshared=24\n%mem=40GB\n# HF/STO-3G SP\n\nSynthetic water\n\n0 1\nO 0 0 0\nH 0 0 1\nH 0 1 0\n\n')
    args = dict(study_name='target-demo', template='gaussian', input_path=source,
                tier='general', walltime='01:00:00', label='target', method_basis='Synthetic fallback',
                target_node='compute-a')
    return cfg, args


def prepared(targeted):
    cfg, args = targeted
    m = attempt.prepare(cfg, **args)
    return cfg, attempt.find(cfg, m['attempt_id']), m


@pytest.mark.parametrize('fraction,tier,cores,memory', [('1/2', 'general', 24, 40), ('1/4', 'mini', 12, 20)])
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
    with pytest.raises(ValueError,match='contradictory'):
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
    assert clusters.describe(cfg)['clusters'][0]['node_targeting']==dict(default_fraction='1/2',fractions=['1/2','1/4'])
    with pytest.raises(ValueError):attempt.prepare(cfg,**(args|dict(node_fraction='1/4')))


def test_explicit_quarter_uses_existing_tier(targeted):
    cfg,args=targeted
    args['input_path'].write_text(args['input_path'].read_text().replace('24','12').replace('40GB','20GB'))
    m=attempt.prepare(cfg,**(args|dict(node_fraction='1/4',tier='mini')))
    assert m['node_target']['fraction']=='1/4' and m['cores']==12 and m['mem_gb']==24


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
    assert [o['cores'] for o in candidate['options']] == [24, 12]
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


def test_positive_assigned_memory_without_allocations_is_contradictory(targeted):
    cfg, args = targeted
    # Less than the display rounding threshold still contradicts no jobs.
    row = nt.strict_nodes(nodes(extra='    resources_assigned.mem = 1b\n'), [])[0]
    assert row['mem_assigned_gb'] == 0
    snapshot(cfg, [row])
    assert nt.candidates(cfg)['nodes'][1]['selectable'] is False
    with pytest.raises(ValueError, match='unavailable'):
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
