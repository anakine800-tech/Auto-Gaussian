"""Synthetic ladder evidence only; no runtime adapter, scheduler or real config."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import json
from pathlib import Path

import pytest

from ag import cli, config, route
from test_core import cfg

NOW = datetime(2026, 10, 29, 8, tzinfo=timezone.utc)
GIB = 1024**3


def node(name, total=96, used=0, memory=None):
    memory = total * 2 if memory is None else memory
    return dict(name=name, cores_total=total, cores_used=used, cores_idle=total-used,
                cores_other=0, mem_total_gb=memory, mem_assigned_gb=used*2,
                mem_total_bytes=memory*GIB, mem_assigned_bytes=used*2*GIB,
                jobs=int(used > 0), state='free', capacity_cpu_consistent=True,
                targeting_consistent=True, targeting_reserved=False)


def snapshot(name, nodes, scheduler='pbs'):
    return dict(schema='ag-monitor/1', ok=True, sampled_at=NOW.isoformat(), interval_seconds=60,
                own=dict(cores_in_use=0, cores_running=0, cores_queued=0, jobs=[]),
                cluster=dict(name=name, scheduler=scheduler, nodes=nodes,
                             job_summary=dict(others_queued_jobs=0)))


def cell(cid, cluster='compute', tier='max', nodes=None, condition='empty', **kw):
    result = dict(id=cid, cluster=cluster, tier=tier, classes=['main'],
                  condition=condition, max_placements=2 if condition == 'empty' else 1)
    if nodes is not None:
        result.update(nodes=nodes, node_fraction='1/2')
    return dict(result, **kw)


@pytest.fixture
def ladder(cfg):
    entries = {name: deepcopy(cfg) for name in ('compute', 'pool', 'default', 'batch', 'batch-test')}
    for name, entry in entries.items():
        entry['ssh']['host'] = 'synthetic-' + name
        entry['resources'] = dict(max_cores=48, max_committed_cores=384, max_walltime='12:00:00',
                                  tiers={t: dict(cores=c, mem_gb=c*2) for t, c in
                                         zip(config.RESOURCE_TIERS, (12, 16, 24, 32, 44, 48))})
    entries['compute']['node_targeting'] = dict(allowed_nodes=['alpha', 'bravo', 'charlie', 'delta', 'echo'],
        denied_nodes=[], restricted_nodes=[], priority=[['alpha'], ['bravo'], ['charlie', 'delta'], ['echo']])
    for name in ('batch', 'batch-test'):
        entries[name].update(scheduler='slurm', partition='synthetic')
        entries[name]['ssh']['host'] = 'synthetic-shared'
    entries['batch-test']['allowed_templates'] = ['crest']
    cells = [cell('empty-alpha', tier='ultra', nodes=['alpha']),
             cell('whole-bravo', tier='ultra', nodes=['bravo'], node_fraction='1', max_placements=1),
             cell('empty-middle', tier='complex', nodes=['charlie', 'delta']),
             cell('empty-pool', 'pool', 'ultra'),
             cell('empty-echo', tier='ultra', nodes=['echo']),
             cell('fits-default', 'default', 'max', condition='free', min_free_cores=44),
             cell('free-large', tier='ultra', nodes=['alpha', 'echo'], condition='free', min_free_cores=48),
             cell('free-middle', tier='complex', nodes=['charlie', 'delta'], condition='free', min_free_cores=32),
             cell('free-pool', 'pool', 'ultra', condition='free', min_free_cores=48),
             cell('batch-jobs', 'batch', 'max', condition='jobs', max_jobs=4),
             cell('queue-alpha', tier='ultra', nodes=['alpha'], condition='queue'),
             cell('queue-bravo', tier='ultra', nodes=['bravo'], condition='queue', node_fraction='1')]
    raw = dict(local=cfg['local'], _config_dir=cfg['_config_dir'], clusters=entries,
               routing=dict(gaussian=['compute', 'pool', 'default', 'batch'], ladder=cells))
    snaps = dict(compute=snapshot('compute', [node('alpha'), node('bravo', 48), node('charlie', 64),
                                            node('delta', 64), node('echo')]),
                 pool=snapshot('pool', [node('pool-a')]),
                 default=snapshot('default', [node('default-a', 44)]))
    for name in ('batch', 'batch-test'):
        n = node('batch-a')
        n.update(state='idle', partition='synthetic', partition_state='up')
        snaps[name] = snapshot(name, [n], 'slurm')
    return raw, snaps


def choose(ladder, **kw):
    raw, snaps = ladder
    args = dict(study_id='smoke', template='gaussian', job_class='main', walltime='01:00:00', round_id='round-a', run_id='run-a',
                object_id='water-b', placements=[], wakeups=[], now=NOW)
    args.update(kw)
    return route.select_ladder(raw, snaps, **args)


def selected(result):
    return result['recommendation']


def placement(ladder, *, cluster='compute', node_name='alpha', state='queued', job='1',
              aid='water-a', cores=48, run='run-a', cid='empty-alpha', study_id='smoke', **kw):
    raw, snaps = ladder
    job_name = ('ag' + sha256(aid.encode()).hexdigest()[:12]
                if config.scheduler_kind(raw['clusters'][cluster]) == 'pbs' else aid)
    result = dict(study_id=study_id, cluster=cluster, attempt_id=aid,
                  job_id=cluster+':'+job if job is not None else None,
                  scheduler_job_name=job_name, state=state,
                  cores=cores, mem_gb=cores*2, round_id='round-a' if run else None, run_id=run, object_id=aid,
                  cell_id=cid, target_node=node_name, capacity_node=node_name,
                  manifest_sha256='a'*64, record_sha256='b'*64,
                  config_sha256=route.ladder_config_identity(raw), selected_at=NOW.isoformat(),
                  batch_snapshot_sha256=route._digest(snaps[cluster]),
                  batch_input_sha256=choose(ladder, study_id=study_id, object_id='water-a')['evidence']['input_sha256'])
    return dict(result, **kw)



def batch_proof(ladder):
    raw, snaps = ladder
    request = dict(study_id='smoke', template='gaussian', job_class='main', walltime='01:00:00', round_id='round-a', run_id='run-a',
                   object_id='water-a', waiting_since=None, parent_cluster=None)
    proof = dict(snapshots=deepcopy(snaps), request=request, placements=[], wakeups=[],
                 selected_at=NOW.isoformat())
    digest = choose(ladder, object_id='water-a')['evidence']['input_sha256']
    return {digest: proof}


def observe(snaps, p, *, running=True, entry=None):
    name = entry or p['cluster']
    data = snaps[name]
    raw = p['job_id'].split(':')[-1]
    data['own']['jobs'].append(dict(job_id=name+':'+raw, name=p['scheduler_job_name'], state=('R' if running else 'Q') if data['cluster']['scheduler'] == 'pbs'
        else ('RUNNING' if running else 'PENDING')))
    key = 'cores_running' if running else 'cores_queued'
    data['own'][key] += p['cores']
    data['own']['cores_in_use'] += p['cores']
    if running:
        target = p['target_node'] or data['cluster']['nodes'][0]['name']
        n = next(n for n in data['cluster']['nodes'] if n['name'] == target)
        n.update(cores_used=n['cores_used']+p['cores'], jobs=n['jobs']+1,
                 mem_assigned_bytes=n['mem_assigned_bytes']+p['mem_gb']*GIB,
                 mem_assigned_gb=n['mem_assigned_gb']+p['mem_gb'],
                 cores_idle=n['cores_idle']-p['cores'])
        if data['cluster']['scheduler'] == 'slurm':
            n['state'] = 'mixed'


def test_each_main_cell_can_be_selected(ladder):
    raw, _ = ladder
    all_cells = deepcopy(raw['routing']['ladder'])
    for c in all_cells:
        raw['routing']['ladder'] = [c]
        r = selected(choose(ladder, waiting_since=(NOW-timedelta(hours=2)).isoformat(),
                            wakeups=[dict(study_id='smoke', round_id='round-a', run_id='run-a', object_id='water-b', started_at=NOW.isoformat())]))
        assert r is not None and r['cell_id'] == c['id']


@pytest.mark.parametrize('readback', ['absent', 'queued', 'running'])
def test_second_half_uses_qualified_origin_and_current_remaining(ladder, readback):
    raw, snaps = ladder
    raw['routing']['ladder'] = [raw['routing']['ladder'][0]]
    batches = batch_proof(ladder)
    p = placement(ladder)
    if readback != 'absent':
        observe(snaps, p, running=readback == 'running')
    kw = dict(placements=[p], batch_inputs=batches)
    choice = selected(choose(ladder, **kw))
    assert choice and choice['capacity_node'] == 'alpha'
    assert choice['capacity']['cores_available'] == 48
    # A foreign allocation makes the second half unsafe, even with a valid origin.
    n = snaps['compute']['cluster']['nodes'][0]
    n['cores_used'] += 1
    n['mem_assigned_bytes'] += 2*GIB
    assert selected(choose(ladder, **kw)) is None


def test_repeat_command_does_not_consume_or_place_twice(ladder):
    raw, snaps = ladder
    raw['routing']['ladder'] = [raw['routing']['ladder'][0]]
    batches = batch_proof(ladder)
    p = placement(ladder)
    kw = dict(placements=[p, deepcopy(p)], batch_inputs=batches)
    first = choose(ladder, **kw)
    assert first == choose(ladder, **kw)
    assert selected(first)
    assert choose(ladder, object_id='water-a', **kw)['reason'] == 'object_already_placed_in_run'
    p2 = placement(ladder, aid='water-c', job='2')
    assert selected(choose(ladder, placements=[p, p2], batch_inputs=kw['batch_inputs'])) is None


@pytest.mark.parametrize('kind', ['missing', 'changed', 'nonempty', 'expired'])
def test_initial_batch_proof_cannot_be_inferred_from_current_usage(ladder, kind):
    raw, snaps = ladder
    raw['routing']['ladder'] = [raw['routing']['ladder'][0]]
    p = placement(ladder)
    batches = batch_proof(ladder)
    origin = next(iter(batches.values()))['snapshots']['compute']
    if kind == 'nonempty':
        origin['cluster']['nodes'][0]['jobs'] = 1
        p['batch_snapshot_sha256'] = route._digest(origin)
    if kind == 'expired':
        p['selected_at'] = (NOW+timedelta(seconds=181)).isoformat()
    if kind == 'changed':
        p['config_sha256'] = 'c'*64
    if kind == 'missing': batches = {}
    assert selected(choose(ladder, placements=[p], batch_inputs=batches)) is None


@pytest.mark.parametrize('kind', ['failed', 'expired', 'future', 'interval', 'memory', 'cpu',
                                  'split', 'exact', 'offline', 'duplicate', 'account', 'walltime'])
def test_unknown_or_inapplicable_never_falls_through_to_queue(ladder, kind):
    raw, snaps = ladder
    raw['routing']['ladder'] = [cell('free', 'default', 'max', condition='free', min_free_cores=44),
                                cell('queue', 'default', 'max', condition='queue')]
    data = snaps['default']
    n = data['cluster']['nodes'][0]
    if kind == 'failed': data['ok'] = False
    elif kind == 'expired': data['sampled_at'] = (NOW-timedelta(seconds=181)).isoformat()
    elif kind == 'future': data['sampled_at'] = (NOW+timedelta(seconds=1)).isoformat()
    elif kind == 'interval': data['interval_seconds'] = None
    elif kind == 'memory': n['mem_assigned_bytes'] = None
    elif kind == 'cpu': n['capacity_cpu_consistent'] = False
    elif kind == 'exact': n['mem_total_bytes'] = 88*GIB-1
    elif kind == 'offline': n['state'] = 'offline'
    elif kind == 'duplicate': data['cluster']['nodes'].append(deepcopy(n))
    elif kind == 'account': data['own']['cores_queued'] = None
    elif kind == 'walltime': raw['clusters']['default']['resources']['max_walltime'] = '00:59:59'
    elif kind == 'split':
        n['mem_total_bytes'] = 40*GIB
        data['cluster']['nodes'].append(node('other', 22, memory=100))
    assert selected(choose(ladder)) is None


def test_fresh_boundary_and_exact_memory(ladder):
    raw, snaps = ladder
    raw['routing']['ladder'] = [raw['routing']['ladder'][5]]
    snaps['default']['sampled_at'] = (NOW-timedelta(seconds=180)).isoformat()
    assert selected(choose(ladder))['cluster'] == 'default'


def test_shared_account_caps_and_readback_dedup(ladder):
    raw, snaps = ladder
    raw['routing']['ladder'] = [cell('batch-free', 'batch', 'max', condition='free', min_free_cores=44)]
    raw['clusters']['batch-test']['resources']['max_committed_cores'] = 88
    p = placement(ladder, cluster='batch-test', node_name=None, cores=44, cid='old', run=None)
    assert selected(choose(ladder, placements=[p]))
    observe(snaps, p, running=True, entry='batch-test')
    observe(snaps, p, running=True, entry='batch')
    assert selected(choose(ladder, placements=[p, p]))
    p2 = placement(ladder, cluster='batch-test', node_name=None, cores=12, aid='other', job='2', run=None)
    assert selected(choose(ladder, placements=[p, p2])) is None
    raw['clusters']['batch-test']['resources']['max_queued_cores'] = 43
    assert selected(choose(ladder, placements=[p])) is None


def test_parent_binding_and_capability_filters(ladder):
    raw, snaps = ladder
    raw['routing']['ladder'].append(cell('queue-pool', 'pool', 'ultra', condition='queue'))
    snaps['pool']['cluster']['nodes'][0].update(cores_used=96, mem_assigned_bytes=192*GIB, jobs=2)
    r = selected(choose(ladder, parent_cluster='pool'))
    assert r and r['cluster'] == 'pool' and r['needs_queue']
    raw['clusters']['pool']['allowed_templates'] = []
    assert selected(choose(ladder, parent_cluster='pool')) is None
    for c in raw['routing']['ladder']: c['classes'] = ['small']
    assert selected(choose(ladder, job_class='small', template='gaussian-cp'))['cluster'] == 'default'
    raw['clusters']['default']['programs']['multiwfn'] = {'root': '/synthetic/program'}
    assert selected(choose(ladder, job_class='small', template='multiwfn'))['cluster'] == 'default'
    raw['clusters']['default']['allowed_templates'] = ['gaussian']
    assert selected(choose(ladder, job_class='small', template='multiwfn')) is None


def test_small_prefers_occupied_node_across_different_quarter_tiers(ladder):
    raw, snaps = ladder
    raw['routing']['ladder'] = [cell('small-alpha', tier='general', nodes=['alpha'], classes=['small'],
                                    node_fraction='1/4', condition='free', min_free_cores=24),
                               cell('small-middle', tier='simple', nodes=['charlie'], classes=['small'],
                                    node_fraction='1/4', condition='free', min_free_cores=16)]
    snaps['compute']['cluster']['nodes'][2] = node('charlie', 64, 8)
    assert selected(choose(ladder, job_class='small'))['capacity_node'] == 'charlie'


def test_jobs_need_actual_waiting_event_and_count_all_active_autonomous_records(ladder):
    raw, snaps = ladder
    raw['routing']['ladder'] = [raw['routing']['ladder'][9]]
    wait = (NOW-timedelta(hours=3)).isoformat()
    wakes = [dict(study_id='smoke', round_id='round-a', run_id='run-a', object_id='water-b', started_at=NOW.isoformat())]
    assert selected(choose(ladder, waiting_since=wait)) is None
    assert selected(choose(ladder, wakeups=wakes)) is None
    assert selected(choose(ladder, waiting_since=NOW.isoformat(), wakeups=wakes)) is None
    kw = dict(waiting_since=wait, wakeups=wakes)
    ps = [placement(ladder, cluster='batch', node_name=None, aid='other-'+str(i), job=str(i+1),
                    cores=44, cid='batch-jobs') for i in range(4)]
    assert selected(choose(ladder, placements=ps[:3], **kw))
    assert selected(choose(ladder, placements=ps, **kw)) is None
    with pytest.raises(ValueError, match='Duplicate wakeup'):
        choose(ladder, wakeups=wakes+wakes, waiting_since=wait)


def test_fallback_one_per_physical_resource_and_two_global(ladder):
    raw, snaps = ladder
    raw['routing']['ladder'] = [cell('queue-batch', 'batch', 'max', condition='queue'),
                                cell('queue-pool', 'pool', 'ultra', condition='queue')]
    p = placement(ladder, cluster='batch-test', node_name=None, aid='one', cores=44)
    assert selected(choose(ladder, placements=[p]))['cluster'] == 'pool'
    p2 = placement(ladder, cluster='compute', aid='two', job='2')
    assert selected(choose(ladder, placements=[p, p2])) is None


def test_pure_selection_does_not_mutate_inputs_or_touch_transport(ladder, monkeypatch):
    from ag.transport import SSHTransport
    monkeypatch.setattr(SSHTransport, 'run', lambda *a: pytest.fail('network'))
    before = deepcopy(ladder)
    a = choose(ladder)
    assert ladder == before
    assert a == choose(ladder)
    assert a['evidence']['config_sha256'] == route.ladder_config_identity(ladder[0])
    assert selected(a)['batch_snapshot_sha256'] == a['evidence']['snapshots']['compute']


def test_cli_ladder_is_fail_closed_without_trusted_t184_adapter(ladder, monkeypatch, capsys):
    from ag.transport import SSHTransport
    monkeypatch.setattr(SSHTransport, 'run', lambda *a: pytest.fail('network'))
    monkeypatch.setattr(route, 'load_config', lambda: ladder[0])
    root = Path(ladder[0]['local']['studies_root'])
    assert not root.exists()
    code = cli.main(['route', '--template', 'gaussian', '--job-class', 'main', '--study', 'smoke',
                     '--round-id', 'round-a', '--run-id', 'run-a', '--object-id', 'water-b', '--walltime', '01:00:00', '--json'])
    assert code == 1 and 'integration pending' in json.loads(capsys.readouterr().out)['error']
    assert not root.exists()


def test_order_skips_each_unqualified_cell(ladder):
    _, snaps = ladder
    kw = dict(waiting_since=(NOW-timedelta(hours=1)).isoformat(),
              wakeups=[dict(study_id='smoke', round_id='round-a', run_id='run-a', object_id='water-b', started_at=NOW.isoformat())])
    def pick():
        return selected(choose(ladder, **kw))['cell_id']
    def occupy(entry, name, used):
        nodes = snaps[entry]['cluster']['nodes']
        i = next(i for i, n in enumerate(nodes) if n['name'] == name)
        nodes[i] = node(name, nodes[i]['cores_total'], used)
    assert pick() == 'empty-alpha'
    occupy('compute', 'alpha', 1)
    assert pick() == 'whole-bravo'
    occupy('compute', 'bravo', 48)
    assert pick() == 'empty-middle'
    occupy('compute', 'charlie', 1)
    assert selected(choose(ladder, **kw))['capacity_node'] == 'delta'
    occupy('compute', 'delta', 1)
    assert pick() == 'empty-pool'
    occupy('pool', 'pool-a', 1)
    assert pick() == 'empty-echo'
    occupy('compute', 'echo', 1)
    assert pick() == 'fits-default'
    occupy('default', 'default-a', 44)
    assert pick() == 'free-large'
    occupy('compute', 'alpha', 49)
    occupy('compute', 'echo', 49)
    assert pick() == 'free-middle'
    occupy('compute', 'charlie', 33)
    occupy('compute', 'delta', 33)
    assert pick() == 'free-pool'
    occupy('pool', 'pool-a', 49)
    assert pick() == 'batch-jobs'
    assert selected(choose(ladder))['cell_id'] == 'queue-alpha'


@pytest.mark.parametrize('kind', ['stale', 'failed-node-sampling'])
def test_unknown_first_entry_blocks_lower_priority_but_parent_excludes_it(ladder, kind):
    _, snaps = ladder
    if kind == 'stale':
        snaps['compute']['sampled_at'] = (NOW-timedelta(minutes=4)).isoformat()
    else:
        snaps['compute']['cluster']['nodes_error'] = 'synthetic sampling failure'
    assert selected(choose(ladder)) is None
    assert selected(choose(ladder, parent_cluster='pool'))['cluster'] == 'pool'


@pytest.mark.parametrize('mode', ['jobs', 'queue'])
def test_locally_finished_scheduler_residue_keeps_job_and_queue_slots(ladder, mode):
    raw, snaps = ladder
    raw['routing']['ladder'] = [cell('only', 'batch', 'max', condition=mode,
                                    **({'max_jobs': 1} if mode == 'jobs' else {}))]
    p = placement(ladder, cluster='batch', node_name=None, state='finished', cores=44)
    observe(snaps, p, running=False)
    kw = dict(placements=[p], waiting_since=(NOW-timedelta(hours=1)).isoformat(),
              wakeups=[dict(study_id='smoke', round_id='round-a', run_id='run-a', object_id='water-b', started_at=NOW.isoformat())])
    assert selected(choose(ladder, **kw)) is None
    snaps['batch']['own'].update(cores_in_use=0, cores_queued=0, jobs=[])
    assert selected(choose(ladder, **kw))


@pytest.mark.parametrize('bad_origin', ['offline', 'queue', 'quota', 'earlier-cell'])
def test_batch_replay_requires_original_full_ladder_admission(ladder, bad_origin):
    raw, snaps = ladder
    raw['routing']['ladder'] = [raw['routing']['ladder'][0]]
    n = snaps['compute']['cluster']['nodes'][0]
    if bad_origin == 'offline': n['state'] = 'offline'
    elif bad_origin == 'queue': snaps['compute']['cluster']['job_summary']['others_queued_jobs'] = 1
    elif bad_origin == 'quota': snaps['compute']['own'].update(cores_in_use=384, cores_running=384)
    else:
        raw['routing']['ladder'].insert(0, cell('earlier', 'pool', 'ultra'))
    batches = batch_proof(ladder)
    p = placement(ladder)
    # The origin has a correct input hash, but was not an eligible first batch.
    n['state'] = 'free'
    snaps['compute']['cluster']['job_summary']['others_queued_jobs'] = 0
    snaps['compute']['own'].update(cores_in_use=0, cores_running=0)
    observe(snaps, p, running=True)
    result = choose(ladder, placements=[p], batch_inputs=batches)
    ours = [r for r in result['candidates'] if r['cell_id'] == 'empty-alpha']
    assert ours and not ours[0]['eligible'] and 'batch_origin_unverified' in ours[0]['reasons']


def test_single_account_running_metadata_does_not_block_ladder(ladder):
    raw, _ = ladder
    raw['clusters']['compute']['resources']['scheduler_max_running_cores'] = 1
    assert selected(choose(ladder))


@pytest.mark.parametrize('change', ['invalid-state', 'conflicting-job', 'conflicting-attempt'])
def test_ambiguous_local_evidence_rejected(ladder, change):
    p = placement(ladder)
    ps = [p]
    if change == 'invalid-state': p['state'] = 'invalid-state'
    elif change == 'conflicting-job': ps.append(dict(p, attempt_id='different'))
    else: ps.append(dict(p, job_id='compute:99'))
    with pytest.raises(ValueError):
        choose(ladder, placements=ps)


def test_new_wakeup_preserves_round_job_and_queue_limits(ladder):
    raw, _ = ladder
    raw['routing']['ladder'] = [cell('jobs', 'batch', 'max', condition='jobs', max_jobs=1)]
    p = placement(ladder, cluster='batch', node_name=None, cores=44, run='previous-wakeup')
    kw = dict(placements=[p], run_id='next-wakeup', waiting_since=(NOW-timedelta(hours=1)).isoformat(),
              wakeups=[dict(study_id='smoke', round_id='round-a', run_id='next-wakeup', object_id='water-b', started_at=NOW.isoformat())])
    assert selected(choose(ladder, **kw)) is None
    raw['routing']['ladder'] = [cell('queue', 'batch', 'max', condition='queue')]
    assert selected(choose(ladder, **kw)) is None
    # Another round's active job still consumes the shared account core quota.
    p['round_id'] = 'older-round'
    raw['clusters']['batch-test']['resources']['max_committed_cores'] = 48
    assert selected(choose(ladder, **kw)) is None


def test_next_wakeup_cannot_duplicate_an_active_object(ladder):
    p = placement(ladder)
    r = choose(ladder, run_id='next-wakeup', object_id='water-a', placements=[p])
    assert r['reason'] == 'object_already_active_in_round'


def test_batch_manifest_resources_must_match_original_selection(ladder):
    raw, _ = ladder
    raw['routing']['ladder'] = [raw['routing']['ladder'][0]]
    p = placement(ladder, cores=12)
    assert selected(choose(ladder, placements=[p], batch_inputs=batch_proof(ladder))) is None


def test_shared_snapshot_entry_local_links_are_not_scheduler_conflicts(ladder):
    raw, snaps = ladder
    raw['routing']['ladder'] = [cell('only', 'batch', 'max', condition='free', min_free_cores=44)]
    p = placement(ladder, cluster='batch-test', node_name=None, cores=44, run=None)
    for name in ('batch', 'batch-test'):
        observe(snaps, p, entry=name)
    snaps['batch']['own']['jobs'][0].update(study=None, attempt=None, mem_gb=None, mem_source=None)
    snaps['batch-test']['own']['jobs'][0].update(study='smoke', attempt=p['attempt_id'],
                                               mem_gb=88, mem_source='manifest')
    assert selected(choose(ladder, placements=[p]))
    snaps['batch-test']['own']['cores_running'] += 1
    snaps['batch-test']['own']['cores_in_use'] += 1
    assert selected(choose(ladder, placements=[p])) is None


def waiting_request(*, study_id='smoke', round_id='round-a', run_id='run-a', object_id='water-b'):
    return dict(waiting_since=(NOW-timedelta(hours=1)).isoformat(), wakeups=[dict(
        study_id=study_id, round_id=round_id, run_id=run_id, object_id=object_id,
        started_at=NOW.isoformat())])


def test_actual_pbs_job_name_is_required_for_observed_binding(ladder):
    raw, snaps = ladder
    raw['routing']['ladder'] = [cell('free-alpha', tier='ultra', nodes=['alpha'],
                                    condition='free', min_free_cores=48)]
    p = placement(ladder)
    assert p['scheduler_job_name'] == 'ag' + sha256(p['attempt_id'].encode()).hexdigest()[:12]
    observe(snaps, p)
    assert selected(choose(ladder, placements=[p]))
    # PBS displays the manifest's short scheduler name, not the Attempt ID.
    snaps['compute']['own']['jobs'][0]['name'] = p['attempt_id']
    result = choose(ladder, placements=[p])
    assert selected(result) is None
    assert 'account_or_reservation_evidence_unknown' in result['candidates'][0]['reasons']


@pytest.mark.parametrize('field', ['study_id', 'scheduler_job_name', 'run_id', 'round_id'])
def test_placement_requires_verifiable_study_and_scheduler_identity(ladder, field):
    p = placement(ladder, run=None)
    del p[field]
    with pytest.raises((KeyError, ValueError)):
        choose(ladder, placements=[p])


def test_same_object_and_batch_names_in_other_study_are_independent(ladder):
    raw, _ = ladder
    raw['routing']['ladder'] = [cell('free-alpha', tier='ultra', nodes=['alpha'],
                                    condition='free', min_free_cores=48)]
    p = placement(ladder, study_id='other-study', cid='free-alpha')
    result = choose(ladder, object_id='water-a', placements=[p])
    assert selected(result) and selected(result)['capacity']['cores_available'] == 48
    # The foreign submission counts toward physical resources but neither
    # consumes this study's one-place batch nor duplicates its object.
    p['study_id'] = 'smoke'
    assert choose(ladder, object_id='water-a', placements=[p])['reason'] == 'object_already_placed_in_run'


@pytest.mark.parametrize('field,value', [('study_id', 'other-study'),
    ('round_id', 'older-round'), ('run_id', 'previous-wakeup')])
def test_qualified_batch_origin_is_bound_to_study_round_and_run(ladder, field, value):
    raw, snaps = ladder
    raw['routing']['ladder'] = [raw['routing']['ladder'][0]]
    p = placement(ladder)
    proof = next(iter(batch_proof(ladder).values()))
    proof['request'][field] = value
    origin = route.select_ladder(raw, proof['snapshots'], **proof['request'],
                                placements=[], wakeups=[], now=NOW)
    digest = origin['evidence']['input_sha256']
    p['batch_input_sha256'] = digest
    observe(snaps, p)
    result = choose(ladder, placements=[p], batch_inputs={digest: proof})
    assert selected(result) is None
    assert 'batch_origin_unverified' in result['candidates'][0]['reasons']


def test_wakeup_identity_includes_study_round_and_object(ladder):
    raw, _ = ladder
    raw['routing']['ladder'] = [cell('jobs', 'batch', 'max', condition='jobs', max_jobs=4)]
    kw = waiting_request(study_id='other-study')
    assert selected(choose(ladder, **kw)) is None
    # Identical run names from different studies are distinct records. Only
    # the matching study/object waiting history can satisfy this request.
    kw['wakeups'] += waiting_request()['wakeups']
    assert selected(choose(ladder, **kw))
    kw = waiting_request(object_id='another-object')
    assert selected(choose(ladder, **kw)) is None
    kw = waiting_request(round_id='older-round')
    assert selected(choose(ladder, **kw)) is None


@pytest.mark.parametrize('state,job', [('reserved', None), ('unknown', None),
    ('unknown', '1'), ('running', '1'), ('queued', '1')])
def test_global_job_cap_includes_other_studies_rounds_and_unobserved_states(ladder, state, job):
    raw, _ = ladder
    raw['routing']['ladder'] = [cell('jobs', 'batch', 'max', condition='jobs', max_jobs=4)]
    ps = [placement(ladder, cluster='batch-test', node_name=None, cores=44,
                    aid='other-'+str(i), job=None if job is None else str(i+1), state=state,
                    study_id='other-study-'+str(i), round_id='older-round', run='previous-wakeup')
          for i in range(4)]
    assert selected(choose(ladder, placements=ps[:3], **waiting_request()))
    result = choose(ladder, placements=ps, **waiting_request())
    assert selected(result) is None
    assert 'autonomous_job_limit' in result['candidates'][0]['reasons']


def test_shared_alias_reads_do_not_create_additional_autonomous_jobs(ladder):
    raw, _ = ladder
    raw['routing']['ladder'] = [cell('jobs', 'batch', 'max', condition='jobs', max_jobs=4)]
    ps = [placement(ladder, cluster='batch', node_name=None, cores=44,
                    aid='other-'+str(i), job=str(i+1), study_id='other-study', round_id='older-round')
          for i in range(3)]
    alias = dict(ps[0], cluster='batch-test', job_id='batch-test:1')
    assert selected(choose(ladder, placements=ps+[alias], **waiting_request()))
    fourth = placement(ladder, cluster='batch', node_name=None, cores=44, aid='fourth', job='4')
    assert selected(choose(ladder, placements=ps+[alias, fourth], **waiting_request())) is None


def test_shared_pbs_alias_second_half_is_order_independent(ladder):
    raw, snaps = ladder
    raw['routing']['ladder'] = [raw['routing']['ladder'][0]]
    raw['clusters']['compute-peer'] = deepcopy(raw['clusters']['compute'])
    snaps['compute-peer'] = deepcopy(snaps['compute'])
    snaps['compute-peer']['cluster']['name'] = 'compute-peer'
    proof = batch_proof(ladder)
    p = placement(ladder)
    alias = dict(p, cluster='compute-peer', job_id='compute-peer:1')
    a = choose(ladder, placements=[p, alias], batch_inputs=proof)
    b = choose(ladder, placements=[alias, p], batch_inputs=proof)
    assert a == b
    assert selected(a) and selected(a)['capacity_node'] == 'alpha'
    assert selected(a)['capacity']['cores_available'] == 48


@pytest.mark.parametrize('field,value', [('study_id', 'another-study'),
    ('attempt_id', 'another-attempt'), ('object_id', 'another-object'), ('cores', 12)])
def test_same_physical_job_cannot_claim_conflicting_ownership(ladder, field, value):
    p = placement(ladder, cluster='batch', node_name=None, cores=44)
    other = dict(p, cluster='batch-test', job_id='batch-test:1')
    other[field] = value
    with pytest.raises(ValueError):
        choose(ladder, placements=[p, other])


def test_unsubmitted_reservations_use_study_and_attempt_identity(ladder):
    raw, _ = ladder
    raw['routing']['ladder'] = [cell('jobs', 'batch', 'max', condition='jobs', max_jobs=2)]
    p = placement(ladder, cluster='batch', node_name=None, cores=44, state='reserved', job=None)
    assert selected(choose(ladder, placements=[p, deepcopy(p)], **waiting_request()))
    other_study = dict(p, study_id='another-study')
    result = choose(ladder, placements=[p, other_study], **waiting_request())
    assert selected(result) is None
    assert 'autonomous_job_limit' in result['candidates'][0]['reasons']


@pytest.mark.parametrize('state', ['running', 'unknown'])
def test_unobserved_active_state_holds_global_queue_slot_until_running_readback(ladder, state):
    raw, snaps = ladder
    raw['routing']['ladder'] = [cell('queue', 'pool', 'ultra', condition='queue')]
    p = placement(ladder, cluster='batch', node_name=None, cores=44, state=state,
                  study_id='other-study', round_id='older-round')
    other = placement(ladder, aid='other', job=None, state='reserved', study_id='third-study')
    result = choose(ladder, placements=[p, other])
    assert selected(result) is None
    assert 'global_queue_limit' in result['candidates'][0]['reasons']
    for name in ('batch', 'batch-test'):
        observe(snaps, p, entry=name)
    assert selected(choose(ladder, placements=[p, other]))


def test_unknown_without_job_and_shared_alias_hold_one_queue_slot(ladder):
    raw, _ = ladder
    raw['routing']['ladder'] = [cell('queue-batch', 'batch', 'max', condition='queue'),
                                cell('queue-pool', 'pool', 'ultra', condition='queue')]
    p = placement(ladder, cluster='batch', node_name=None, cores=44, state='unknown', job=None,
                  study_id='other-study', round_id='older-round')
    alias = dict(p, cluster='batch-test')
    result = choose(ladder, placements=[p, alias])
    assert selected(result)['cluster'] == 'pool'
    other = placement(ladder, aid='other', job=None, state='unknown', study_id='third-study')
    assert selected(choose(ladder, placements=[p, alias, other])) is None


@pytest.mark.parametrize('mode', ['jobs', 'queue'])
def test_manual_and_unlinked_snapshot_jobs_only_consume_account_cores(ladder, mode):
    raw, snaps = ladder
    raw['routing']['ladder'] = [cell('only', 'batch', 'max', condition=mode,
                                    **({'max_jobs': 4} if mode == 'jobs' else {}))]
    manual = [placement(ladder, cluster='batch', node_name=None, aid='manual-'+str(i),
                        job=str(i+1), cores=8, run=None, study_id='manual-study') for i in range(4)]
    for p in manual:
        for name in ('batch', 'batch-test'):
            observe(snaps, p, running=False, entry=name)
    for records in ([], manual):
        assert selected(choose(ladder, placements=records, **waiting_request()))
    raw['clusters']['batch-test']['resources']['max_committed_cores'] = 64
    assert selected(choose(ladder, placements=manual, **waiting_request())) is None


@pytest.mark.parametrize('mode', ['jobs', 'queue'])
def test_local_submission_lock_requires_recompute_before_claiming_last_slot(ladder, mode):
    from ag.locks import submission_lock
    raw, _ = ladder
    if mode == 'jobs':
        raw['routing']['ladder'] = [cell('only', 'batch', 'max', condition='jobs', max_jobs=4)]
        records = [placement(ladder, cluster='batch', node_name=None, cores=44,
                             aid='existing-'+str(i), job=str(i+1), study_id='other-study',
                             round_id='older-round') for i in range(3)]
        cluster, cores = 'batch', 44
    else:
        raw['routing']['ladder'] = [cell('only', 'pool', 'ultra', condition='queue')]
        records = [placement(ladder, cluster='batch', node_name=None, cores=44,
                             aid='existing', study_id='other-study', round_id='older-round')]
        cluster, cores = 'pool', 48
    barrier = Barrier(2)

    def contender(index):
        object_id = 'candidate-'+str(index)
        kw = waiting_request(object_id=object_id)
        stale_choice = selected(choose(ladder, object_id=object_id, placements=deepcopy(records), **kw))
        barrier.wait(timeout=10)
        with submission_lock(raw):
            current = choose(ladder, object_id=object_id, placements=deepcopy(records), **kw)
            if selected(current):
                records.append(placement(ladder, cluster=cluster, node_name=None, cores=cores,
                    aid=object_id, job=None, state='reserved', cid='only'))
        return stale_choice is not None, selected(current) is not None

    # This exercises the existing local flock plus kernel recomputation. It is
    # not evidence that the production submit/T186 path has been connected.
    with ThreadPoolExecutor(max_workers=2) as workers:
        futures = [workers.submit(contender, i) for i in range(2)]
        outcomes = [future.result(timeout=15) for future in futures]
    assert all(stale for stale, _ in outcomes)
    assert sum(accepted for _, accepted in outcomes) == 1
    assert len(records) == (4 if mode == 'jobs' else 2)
    assert selected(choose(ladder, placements=records, **waiting_request())) is None
