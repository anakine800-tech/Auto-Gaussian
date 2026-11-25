"""Admission of the requested size on a named PBS node with remaining resources."""
import json
from pathlib import Path

import pytest

from ag import attempt, autonomy_submission, config, confirm, monitor, node_targeting, remote, route, state, submit
from ag.transport import Result
from test_core import cfg
from test_node_targeting import OwnListFake, nodes, queue_site, snapshot, targeted


@pytest.fixture
def remaining(targeted, monkeypatch):
    cfg, args = targeted
    queue_site(cfg)
    cfg['node_targeting']['occupied_policy'].update(queue_nodes=['compute-c'], remaining_nodes=['compute-a'])
    cfg['routing'] = dict(gaussian=['default'])
    with autonomy_submission.machine_lock():
        pass
    monkeypatch.setattr(config, 'ssh_identity', lambda _: ('fixture', 22, 'fixture'))
    return cfg, args, OwnListFake(cfg)


def allocation(fake, total, used, owner='hidden', assigned=None):
    slots = f'0-{used-1}'
    fake.node_text = nodes(total, extra=f'    jobs = {slots}/834.fixture\n')
    if assigned is not None:
        fake.node_text += f'    resources_assigned.mem = {assigned}\n'
    details = (f'Job Id: 834.fixture\n    Job_Name = synthetic\n    Job_Owner = {owner}@fixture\n'
               f'    job_state = R\n    queue = batch\n    Resource_List.nodes = compute-a:ppn={used}\n'
               f'    exec_host = compute-a/{slots}\n')
    fake.qstat = Result(stdout='' if owner == 'hidden' else details)
    ids = '834.fixture\n' if owner == 'fixture' else ''
    fake.account = Result(stdout='AG_OWNER fixture\n' + ids + 'AG_END\n')
    fake.queue_text = 'Queue Tot Que Run\nbatch 1 0 1\n'


def publish(cfg, fake):
    observed = monitor.observation(cfg, fake, 'fixture')
    snapshot(cfg, observed['cluster']['nodes'])
    cache = Path(cfg['local']['studies_root']) / '.ag-monitor/latest.json'
    cache.write_text(json.dumps(json.loads(cache.read_bytes()) | observed))


@pytest.mark.parametrize('total,used,owner,fraction,tier,assigned,reason', [
    (96, 15, 'hidden', '1/2', 'max', None, None),
    (96, 15, 'peer', '1/4', 'general', None, None),
    (96, 87, 'hidden', '1/4', 'general', None, 'Only 9 CPU slots remain on this node; request requires 24'),
    (96, 87, 'peer', '1/2', 'max', None, 'Only 9 CPU slots remain on this node; request requires 48'),
    (96, 87, 'fixture', '1/4', 'general', '8gb', 'Only 9 CPU slots remain'),
    (64, 32, 'hidden', '1/2', 'complex', '64gb', None),
    (64, 32, 'peer', '1/2', 'complex', str(64*1024**3+1) + 'b', 'Insufficient remaining memory'),
])
def test_remaining_slots_admission_and_routing(remaining, monkeypatch, total, used, owner, fraction, tier, assigned, reason):
    cfg, args, fake = remaining
    allocation(fake, total, used, owner, assigned)
    publish(cfg, fake)
    requested = cfg['resources']['tiers'][tier]['cores']
    candidate = next(n for n in node_targeting.candidates(cfg)['nodes'] if n['name'] == 'compute-a')
    option = next(o for o in candidate['options'] if o['fraction'] == fraction)
    assert option['cores'] == requested and option['capacity']['cores_available'] == total - used
    assert option['selectable'] is (reason is None)
    advice = route.suggest(cfg, 'gaussian', tier)
    assert advice['clusters'][0]['specification_allowed'] is (reason is None)
    assert (advice['recommendation'] is None) is (reason is not None)
    source = args['input_path']
    source.write_bytes(source.read_bytes().replace(b'%nprocshared=24', f'%nprocshared={requested}'.encode()))
    args = args | dict(tier=tier, node_fraction=fraction)
    if reason:
        assert reason in option['selectable_reason']
        assert any(reason in text for text in advice['clusters'][0]['reasons'])
        with pytest.raises(ValueError, match=reason):
            attempt.prepare(cfg, **args)
        assert not list(Path(cfg['local']['studies_root']).rglob('manifest.json'))
        return
    assert 'Local policy allows request' in option['selectable_reason']
    if assigned is None:
        assert 'available memory unknown' in option['selectable_reason']
        assert option['capacity']['availability'] == 'unknown' and advice['recommendation']['needs_queue']
    m = attempt.prepare(cfg, **args)
    path = attempt.find(cfg, m['attempt_id'])
    original = attempt.verified_files(cfg, path, m)
    assert m['cores'] == requested and f'nodes=compute-a:ppn={requested}'.encode() in original['job.pbs']
    fake.job = Result(stdout=f"Job Id: 123.fixture\n    Job_Name = {m['pbs_job_name']}\n    job_state = Q\n")
    monkeypatch.setattr(confirm, 'confirm', lambda _: True)
    submit.submit(cfg, [m['attempt_id']], fake)
    assert fake.calls.count(remote.pbs_own_jobs()) == 3  # one sample and both fresh checks
    assert fake.operations().count('submit') == 1 and state.read(path)['node_placement']['state'] == 'pending'
    assert attempt.read_manifest(path) == m and attempt.verified_files(cfg, path, m) == original


@pytest.mark.parametrize('phase', ['confirmation', 'upload'])
@pytest.mark.parametrize('change', ['cpu', 'memory'])
def test_remaining_resources_rechecked_without_resizing(remaining, monkeypatch, phase, change):
    cfg, args, fake = remaining
    allocation(fake, 96, 15)
    publish(cfg, fake)
    m = attempt.prepare(cfg, **(args | dict(node_fraction='1/4')))
    path = attempt.find(cfg, m['attempt_id'])
    original = attempt.verified_files(cfg, path, m)
    def take_resources():
        if change == 'cpu':
            allocation(fake, 96, 87)
        else:
            allocation(fake, 96, 15, assigned='100gb')
    def clicked(_):
        if phase == 'confirmation':
            take_resources()
        return True
    upload = fake.upload
    def transfer(*args):
        upload(*args)
        if phase == 'upload':
            take_resources()
    monkeypatch.setattr(confirm, 'confirm', clicked)
    monkeypatch.setattr(fake, 'upload', transfer)
    stage = 'after confirmation' if phase == 'confirmation' else 'after upload, before qsub'
    reason = 'Only 9 CPU slots remain' if change == 'cpu' else 'Insufficient remaining memory'
    with pytest.raises(ValueError, match=stage + '.*' + reason):
        submit.submit(cfg, [m['attempt_id']], fake)
    assert m['cores'] == 24 and attempt.read_manifest(path) == m and attempt.verified_files(cfg, path, m) == original
    assert fake.operations().count('submit') == 0 and (path/'.submit-claim').exists() is (phase == 'upload')


@pytest.mark.parametrize('bad,reason', [
    ('account', 'login-account'), ('overlap', 'contradictory'), ('offline', 'state'),
    ('denied', 'forbidden'), ('partial-memory', 'Insufficient remaining memory'),
    ('visible-slots-only', 'from visible jobs alone'),
])
def test_remaining_policy_requires_verifiable_evidence(remaining, bad, reason):
    cfg, args, fake = remaining
    allocation(fake, 96, 15)
    if bad == 'account':
        fake.account = Result(stdout='AG_OWNER fixture\n834.fixture\nAG_END\n')
    elif bad == 'overlap':
        fake.node_text = fake.node_text.replace('/834.fixture', '/834.fixture,3-8/855.fixture')
    elif bad == 'offline':
        fake.node_text = fake.node_text.replace('state = free', 'state = offline')
    elif bad == 'denied':
        cfg['node_targeting']['denied_nodes'].append('compute-a')
    elif bad == 'visible-slots-only':
        allocation(fake, 96, 15, 'peer')
        fake.node_text = nodes(96)  # qstat sees 15 slots, but pbsnodes supplies no count for this allocation.
    elif bad == 'partial-memory':
        allocation(fake, 96, 15, 'peer')
        fake.node_text = fake.node_text.replace('/834.fixture', '/834.fixture,15/855.fixture')
        fake.qstat = Result(stdout=fake.qstat.stdout + '    Resource_List.mem = 100gb\n')
    publish(cfg, fake)
    node = next(n for n in node_targeting.candidates(cfg)['nodes'] if n['name'] == 'compute-a')
    option = next(o for o in node['options'] if o['fraction'] == '1/4')
    assert not option['selectable'] and reason in option['selectable_reason']
    with pytest.raises(ValueError):
        attempt.prepare(cfg, **(args | dict(node_fraction='1/4')))
    assert fake.operations().count('submit') == 0


@pytest.mark.parametrize('other', ['empty_only', 'queue_nodes'])
def test_remaining_policy_cannot_overlap_other_modes(remaining, other):
    cfg, _, _ = remaining
    cfg['node_targeting']['occupied_policy'][other].append('compute-a')
    with pytest.raises(ValueError, match='Conflicting occupied-node policy'):
        node_targeting.validate_policy(cfg)


@pytest.mark.parametrize('mode,selectable', [('queue_nodes', True), ('empty_only', False)])
def test_occupied_node_keeps_existing_queue_modes(remaining, mode, selectable):
    cfg, _, fake = remaining
    policies = cfg['node_targeting']['occupied_policy']
    policies['remaining_nodes'] = []
    policies[mode].append('compute-a')
    allocation(fake, 96, 87, assigned='100gb')
    publish(cfg, fake)
    node = next(n for n in node_targeting.candidates(cfg)['nodes'] if n['name'] == 'compute-a')
    option = next(o for o in node['options'] if o['fraction'] == '1/4')
    assert option['capacity']['cores_available'] == 9
    assert option['selectable'] is selectable
    assert ('Site permits queueing' if selectable else 'only to an empty node') in option['selectable_reason']


KEX_NOTICE = ('** WARNING: connection is not using a post-quantum key exchange algorithm.\n'
              '** This session may be vulnerable to "store now, decrypt later" attacks.\n'
              '** The server may need to be upgraded. See https://openssh.com/pq.html\n')


def ssh_result(cfg, monkeypatch, reply, stderr, code=0):
    """Exercise real SSH result handling and redaction with an inert subprocess."""
    import subprocess
    from ag.transport import SSHTransport
    with monkeypatch.context() as patch:
        patch.setattr(subprocess, 'run', lambda argv, **_: subprocess.CompletedProcess(argv, code, reply, stderr))
        return SSHTransport(cfg)._execute(['ssh', 'synthetic'], 1)


@pytest.mark.parametrize('stderr,stdout,code,ok', [
    (KEX_NOTICE, 'complete', 0, True),
    (KEX_NOTICE + 'qselect: partial job list\n', 'complete', 0, False),
    ('qselect: partial job list\n' + KEX_NOTICE, 'complete', 0, False),
    ('qselect: partial job list\n', 'complete', 0, False),
    (KEX_NOTICE.replace('openssh.com/pq.html', 'other.invalid/help'), 'complete', 0, False),
    (KEX_NOTICE.rstrip() + '?unexpected\n', 'complete', 0, False),
    (KEX_NOTICE[:60], 'complete', 0, False),
    (KEX_NOTICE + '\n', 'complete', 0, False),
    (KEX_NOTICE, 'missing-end', 0, False),
    (KEX_NOTICE, 'missing-id', 0, False),
    (KEX_NOTICE, 'wrong-owner', 0, False),
    (KEX_NOTICE, 'local-error', 0, False),
    (KEX_NOTICE, 'complete', 1, False),
])
def test_owner_proof_with_real_transport_diagnostics(remaining, monkeypatch, stderr, stdout, code, ok):
    cfg, args, fake = remaining
    allocation(fake, 96, 15)
    details, ids = [], []
    for index, cores in enumerate((64, 32, 16)):
        job, node = f'{840 + index}.fixture', f'other-{index}'
        ids.append(job)
        slots = f'0-{cores-1}'
        fake.node_text += nodes(64, extra=f'    jobs = {slots}/{job}\n').replace('compute-a', node)
        details.append(f'Job Id: {job}\n    Job_Name = synthetic-{index}\n    Job_Owner = fixture@fixture\n'
                       f'    job_state = R\n    queue = batch\n    Resource_List.nodes = {node}:ppn={cores}\n'
                       f'    exec_host = {node}/{slots}\n')
    fake.qstat = Result(stdout=''.join(details))
    fake.queue_text = 'Queue Tot Que Run\nbatch 4 0 4\n'
    login = 'another' if stdout == 'wrong-owner' else 'fixture'
    lines = [f'AG_OWNER {login}', *(ids[1:] if stdout == 'missing-id' else ids)]
    if stdout != 'missing-end':
        lines.append('AG_END')
    if stdout == 'local-error':
        monkeypatch.setattr(config, 'ssh_identity', lambda _: None)
    fake.account = ssh_result(cfg, monkeypatch, '\n'.join(lines) + '\n', stderr, code)
    if 'https://' in stderr:
        assert 'https:[path]' in fake.account.stderr and 'openssh.com' not in fake.account.stderr
    publish(cfg, fake)
    observed = json.loads((Path(cfg['local']['studies_root']) / '.ag-monitor/latest.json').read_bytes())
    proof = observed['own']
    assert proof['cores_in_use'] == 112
    if ok:
        assert proof['occupied_queue_account']['committed'] == 112 and proof['occupied_queue_notice']
        assert any(w['kind'] == 'ssh-kex-notice' for w in observed['warnings'])
        m = attempt.prepare(cfg, **(args | dict(node_fraction='1/4')))
        fake.job = Result(stdout=f"Job Id: 123.fixture\n    Job_Name = {m['pbs_job_name']}\n    job_state = Q\n")
        monkeypatch.setattr(confirm, 'confirm', lambda _: True)
        submit.submit(cfg, [m['attempt_id']], fake)
        assert fake.calls.count(remote.pbs_own_jobs()) == 3 and fake.operations().count('submit') == 1
    else:
        assert 'occupied_queue_account' not in proof and 'occupied_queue_error' in proof
        assert bool(proof.get('occupied_queue_notice')) is (stdout == 'local-error')
        with pytest.raises(ValueError, match='reservations' if stdout == 'local-error' else 'login-account'):
            attempt.prepare(cfg, **(args | dict(node_fraction='1/4')))
        assert fake.operations().count('submit') == 0


@pytest.mark.parametrize('extra', ['', 'qstat: incomplete queue rows\n'])
def test_empty_only_queue_verification_with_transport_notice(remaining, monkeypatch, extra):
    cfg, args, fake = remaining
    allocation(fake, 96, 15)
    fake.node_text += nodes().replace('compute-a', 'compute-b')
    queue = ssh_result(cfg, monkeypatch, fake.queue_text, KEX_NOTICE + extra)
    run = fake.run
    def observe(command):
        if command == remote.queues():
            fake.calls.append(command)
            return queue
        return run(command)
    monkeypatch.setattr(fake, 'run', observe)
    publish(cfg, fake)
    request = args | dict(target_node='compute-b')
    if extra:
        with pytest.raises(ValueError, match='waiting requests'):
            attempt.prepare(cfg, **request)
        assert fake.operations().count('submit') == 0
    else:
        m = attempt.prepare(cfg, **request)
        monkeypatch.setattr(confirm, 'confirm', lambda _: True)
        fake.job = Result(stdout=f"Job Id: 123.fixture\n    Job_Name = {m['pbs_job_name']}\n    job_state = Q\n")
        submit.submit(cfg, [m['attempt_id']], fake)
        assert fake.calls.count(remote.queues()) == 3 and fake.operations().count('submit') == 1


@pytest.mark.parametrize('mode,occupied,refusal', [
    ('remaining_nodes', True, 'checked memory lower bound'),
    ('remaining_nodes', False, None),
    ('queue_nodes', True, None),
])
def test_older_snapshot_missing_memory_lower_bound(remaining, mode, occupied, refusal):
    cfg, args, fake = remaining
    policies = cfg['node_targeting']['occupied_policy']
    if mode == 'queue_nodes':
        policies['remaining_nodes'] = []
        policies['queue_nodes'].append('compute-a')
    allocation(fake, 96, 15)
    if not occupied:
        fake.node_text = 'compute-a\n    state = free\n    np = 96\n    resources_available.mem = 128gb\n'
        fake.queue_text = 'Queue Tot Que Run\nbatch 0 0 0\n'
    publish(cfg, fake)
    cache = Path(cfg['local']['studies_root']) / '.ag-monitor/latest.json'
    sample = json.loads(cache.read_bytes())
    row, = sample['cluster']['nodes']
    assert row['mem_assigned_bytes'] is None and row.pop('mem_assigned_min_bytes') == 0
    row.pop('node_slot_count_reported')
    cache.write_text(json.dumps(sample))
    node = next(n for n in node_targeting.candidates(cfg)['nodes'] if n['name'] == 'compute-a')
    option = next(o for o in node['options'] if o['fraction'] == '1/4')
    assert option['selectable'] is (refusal is None)
    assert (route.suggest(cfg, 'gaussian', 'general')['recommendation'] is not None) is (refusal is None)
    if refusal:
        with pytest.raises(ValueError, match=refusal):
            attempt.prepare(cfg, **(args | dict(node_fraction='1/4')))
    else:
        assert attempt.prepare(cfg, **(args | dict(node_fraction='1/4')))['cores'] == 24


def test_redacted_notice_does_not_cover_later_diagnostics(remaining, monkeypatch):
    from ag import pbs
    cfg, _, _ = remaining
    result = ssh_result(cfg, monkeypatch, 'AG_OWNER fixture\nAG_END\n', KEX_NOTICE)
    assert result.openssh_kex_notice and 'https:[path]' in result.stderr
    assert not pbs.query_stderr_ok(Result(stdout=result.stdout, stderr=result.stderr))
    result.stderr += 'qselect: partial job list\n'
    assert not result.openssh_kex_notice and not pbs.query_stderr_ok(result)
