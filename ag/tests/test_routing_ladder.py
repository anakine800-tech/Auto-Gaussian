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


def synthetic_study_key(label='smoke'):
    # Fixture convenience only. Production must bind the canonical study path;
    # deriving identity from a display name would recreate cross-root collisions.
    return sha256(('synthetic-study-location/' + label).encode()).hexdigest()


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
    args.setdefault('study_key', synthetic_study_key(args['study_id']))
    return route.select_ladder(raw, snaps, **args)


def selected(result):
    return result['recommendation']


def placement(ladder, *, cluster='compute', node_name='alpha', state='queued', job='1',
              aid='water-a', cores=48, run='run-a', cid='empty-alpha', study_id='smoke', study_key=None, **kw):
    raw, snaps = ladder
    study_key = synthetic_study_key(study_id) if study_key is None else study_key
    job_name = ('ag' + sha256(aid.encode()).hexdigest()[:12]
                if config.scheduler_kind(raw['clusters'][cluster]) == 'pbs' else aid)
    result = dict(study_key=study_key, study_id=study_id, cluster=cluster, attempt_id=aid,
                  job_id=cluster+':'+job if job is not None else None,
                  scheduler_job_name=job_name, state=state,
                  cores=cores, mem_gb=cores*2, round_id='round-a' if run else None, run_id=run, object_id=aid,
                  cell_id=cid, target_node=node_name, capacity_node=node_name,
                  manifest_sha256='a'*64, record_sha256='b'*64,
                  config_sha256=route.ladder_config_identity(raw), selected_at=NOW.isoformat(),
                  batch_snapshot_sha256=route._digest(snaps[cluster]),
                  batch_input_sha256=choose(ladder, study_key=study_key, study_id=study_id, object_id='water-a')['evidence']['input_sha256'])
    return dict(result, **kw)



def batch_proof(ladder, *, study_id='smoke', study_key=None):
    raw, snaps = ladder
    study_key = synthetic_study_key(study_id) if study_key is None else study_key
    request = dict(study_key=study_key, study_id=study_id, template='gaussian', job_class='main', walltime='01:00:00', round_id='round-a', run_id='run-a',
                   object_id='water-a', waiting_since=None, parent_cluster=None)
    proof = dict(snapshots=deepcopy(snaps), request=request, placements=[], wakeups=[],
                 selected_at=NOW.isoformat())
    digest = choose(ladder, study_key=study_key, study_id=study_id, object_id='water-a')['evidence']['input_sha256']
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


@pytest.mark.parametrize('shortage', ['cpu', 'memory'])
def test_relaxed_ladder_labels_and_thresholds_still_require_full_capacity(ladder, shortage):
    raw, snaps = ladder
    raw['routing']['ladder'] = [cell('free: position / ' + 'x'*70, 'default', 'max',
        classes=['main', 'main'], condition='free', min_free_cores=0)]
    config.validate_routing(raw)
    assert selected(choose(ladder))
    n = snaps['default']['cluster']['nodes'][0]
    if shortage == 'cpu':
        n['cores_used'] = 1
    else:
        n['mem_assigned_bytes'] = 1
    assert selected(choose(ladder)) is None  # The full 44-core/88-GB request must fit.


def test_small_four_place_batch_uses_real_remaining_capacity(ladder):
    raw, _ = ladder
    raw['routing']['ladder'] = [cell('quarters', tier='general', nodes=['alpha'],
        classes=['small'], condition='free', min_free_cores=0, node_fraction='1/4', max_placements=4)]
    config.validate_routing(raw)
    ps = [placement(ladder, aid='quarter-'+str(i), job=str(i+1), cores=24, cid='quarters')
          for i in range(4)]
    choice = selected(choose(ladder, job_class='small', placements=ps[:3]))
    assert choice and choice['capacity']['cores_available'] == 24
    assert selected(choose(ladder, job_class='small', placements=ps)) is None


def test_each_main_cell_can_be_selected(ladder):
    raw, _ = ladder
    all_cells = deepcopy(raw['routing']['ladder'])
    for c in all_cells:
        raw['routing']['ladder'] = [c]
        r = selected(choose(ladder, waiting_since=(NOW-timedelta(hours=2)).isoformat(),
                            wakeups=[dict(study_key=synthetic_study_key(), study_id='smoke', round_id='round-a', run_id='run-a', object_id='water-b', started_at=NOW.isoformat())]))
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
    wakes = [dict(study_key=synthetic_study_key(), study_id='smoke', round_id='round-a', run_id='run-a', object_id='water-b', started_at=NOW.isoformat())]
    assert selected(choose(ladder, waiting_since=wait)) is None
    assert selected(choose(ladder, wakeups=wakes)) is None
    assert selected(choose(ladder, waiting_since=NOW.isoformat(), wakeups=wakes)) is None
    kw = dict(waiting_since=wait, wakeups=wakes)
    ps = [placement(ladder, cluster='batch', node_name=None, aid='other-'+str(i), job=str(i+1),
                    cores=44, cid='batch-jobs') for i in range(4)]
    assert selected(choose(ladder, placements=ps[:3], **kw))
    assert selected(choose(ladder, placements=ps, **kw)) is None
    assert selected(choose(ladder, wakeups=wakes+wakes, waiting_since=wait))['cell_id'] == 'batch-jobs'
    conflicting = dict(wakes[0], started_at=(NOW-timedelta(hours=4)).isoformat())
    with pytest.raises(ValueError, match='Conflicting wakeup'):
        choose(ladder, wakeups=[conflicting, *wakes], waiting_since=wait)


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


def test_cli_ladder_rejects_incomplete_autonomous_context_without_side_effects(ladder, monkeypatch, capsys, tmp_path):
    from ag.transport import SSHTransport
    monkeypatch.setattr(SSHTransport, '__init__', lambda *a, **kw: pytest.fail('SSH construction'))
    monkeypatch.setattr(SSHTransport, 'run', lambda *a, **kw: pytest.fail('network'))
    monkeypatch.setattr(route, 'load_config', lambda: ladder[0])
    synthetic_home = tmp_path / 'synthetic-home'
    synthetic_home.mkdir()
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: synthetic_home))
    root = Path(ladder[0]['local']['studies_root'])
    assert not root.exists()
    assert not (synthetic_home / '.config').exists()
    code = cli.main(['route', '--template', 'gaussian', '--job-class', 'main', '--study', 'smoke',
                     '--round-id', 'round-a', '--run-id', 'run-a', '--object-id', 'water-b', '--walltime', '01:00:00', '--json'])
    assert code == 1
    # T185 alone blocks on the missing adapter; T186 blocks earlier on the
    # absent policy/token/plan context. Neither arbitrary errors nor success
    # demonstrate this refusal boundary.
    assert json.loads(capsys.readouterr().out)['error'] in {
        'Ladder runtime evidence integration pending: verified submissions and waiting wakeups required',
        'Trusted routing requires --study, --round-id, --run-id, --object-id, '
        '--walltime, --autonomous-policy, --token and --plan-sha256',
    }
    assert not root.exists()
    # The fixed machine registries and mutex live below ~/.config/ag.
    assert not (synthetic_home / '.config').exists()
    assert list(synthetic_home.iterdir()) == []


def test_order_skips_each_unqualified_cell(ladder):
    _, snaps = ladder
    kw = dict(waiting_since=(NOW-timedelta(hours=1)).isoformat(),
              wakeups=[dict(study_key=synthetic_study_key(), study_id='smoke', round_id='round-a', run_id='run-a', object_id='water-b', started_at=NOW.isoformat())])
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


@pytest.mark.parametrize('kind', ['stale', 'failed-node-sampling'])
@pytest.mark.parametrize('unknown_entry,expected', [('batch', 'empty-alpha'), ('compute', None)])
def test_r33_main_unknown_only_blocks_a_candidate_after_it(ladder, kind, unknown_entry, expected):
    _, snaps = ladder
    if kind == 'stale':
        snaps[unknown_entry]['sampled_at'] = (NOW-timedelta(minutes=4)).isoformat()
    else:
        snaps[unknown_entry]['cluster']['nodes_error'] = 'synthetic sampling failure'
    choice = selected(choose(ladder))
    assert (choice['cell_id'] if choice else None) == expected


@pytest.mark.parametrize('unknown_entry,expected', [('compute', 'free-pool'), ('pool', None)])
def test_r33_small_unknown_uses_queue_priority_before_entry_order(ladder, unknown_entry, expected):
    raw, snaps = ladder
    raw['routing']['ladder'] = [
        cell('queue-compute', tier='general', nodes=['alpha'], classes=['small'],
             condition='queue', node_fraction='1/4'),
        cell('free-pool', 'pool', 'simple', classes=['small'], condition='free', min_free_cores=16)]
    snaps[unknown_entry]['sampled_at'] = (NOW-timedelta(minutes=4)).isoformat()
    choice = selected(choose(ladder, job_class='small'))
    # A queued cell sorts after a non-queue cell, even at the earlier entry.
    assert (choice['cell_id'] if choice else None) == expected


@pytest.mark.parametrize('unknown_entry,expected', [('compute', 'free-pool'), ('pool', None)])
def test_r33_small_unknown_uses_entry_order_before_cell_index(ladder, unknown_entry, expected):
    raw, snaps = ladder
    raw['routing']['ladder'] = [
        cell('queue-pool', 'pool', 'simple', classes=['small'], condition='queue'),
        cell('free-compute', tier='general', nodes=['alpha'], classes=['small'],
             condition='free', node_fraction='1/4', min_free_cores=24),
        cell('free-pool', 'pool', 'simple', classes=['small'], condition='free', min_free_cores=16)]
    snaps[unknown_entry]['sampled_at'] = (NOW-timedelta(minutes=4)).isoformat()
    choice = selected(choose(ladder, job_class='small'))
    # The first pool cell establishes entry order. Its later free cell outranks
    # the earlier-declared free cell at the second entry.
    assert (choice['cell_id'] if choice else None) == expected


def test_r33_later_unknown_does_not_release_shared_account_reservations(ladder):
    raw, snaps = ladder
    raw['routing']['ladder'] = [
        cell('first', 'batch', 'max', condition='free', min_free_cores=44),
        cell('later', 'pool', 'ultra', condition='free', min_free_cores=48)]
    raw['clusters']['batch-test']['resources']['max_committed_cores'] = 48
    snaps['pool']['sampled_at'] = (NOW-timedelta(minutes=4)).isoformat()
    p = placement(ladder, cluster='batch-test', node_name=None, cores=12,
                  run=None, state='reserved', job=None)
    assert selected(choose(ladder, placements=[p])) is None  # 12 + 44 exceeds the shared 48-core cap.


def test_r33_parent_binding_excludes_unknown_other_entries_without_crossing_cluster(ladder):
    _, snaps = ladder
    for name in ('compute', 'batch'):
        snaps[name]['sampled_at'] = (NOW-timedelta(minutes=4)).isoformat()
    assert selected(choose(ladder, parent_cluster='pool'))['cluster'] == 'pool'
    snaps['pool']['cluster']['nodes'][0] = node('pool-a', used=96)
    assert selected(choose(ladder, parent_cluster='pool')) is None


@pytest.mark.parametrize('mode', ['jobs', 'queue'])
def test_locally_finished_scheduler_residue_keeps_job_and_queue_slots(ladder, mode):
    raw, snaps = ladder
    raw['routing']['ladder'] = [cell('only', 'batch', 'max', condition=mode,
                                    **({'max_jobs': 1} if mode == 'jobs' else {}))]
    p = placement(ladder, cluster='batch', node_name=None, state='finished', cores=44)
    observe(snaps, p, running=False)
    kw = dict(placements=[p], waiting_since=(NOW-timedelta(hours=1)).isoformat(),
              wakeups=[dict(study_key=synthetic_study_key(), study_id='smoke', round_id='round-a', run_id='run-a', object_id='water-b', started_at=NOW.isoformat())])
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
              wakeups=[dict(study_key=synthetic_study_key(), study_id='smoke', round_id='round-a', run_id='next-wakeup', object_id='water-b', started_at=NOW.isoformat())])
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


def waiting_request(*, study_id='smoke', study_key=None, round_id='round-a', run_id='run-a', object_id='water-b'):
    return dict(waiting_since=(NOW-timedelta(hours=1)).isoformat(), wakeups=[dict(
        study_key=synthetic_study_key(study_id) if study_key is None else study_key,
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


@pytest.mark.parametrize('field', ['study_key', 'study_id', 'scheduler_job_name', 'run_id', 'round_id'])
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
    p.update(study_id='smoke', study_key=synthetic_study_key())
    assert choose(ladder, object_id='water-a', placements=[p])['reason'] == 'object_already_placed_in_run'


@pytest.mark.parametrize('field,value', [('study_id', 'other-study'),
    ('round_id', 'older-round'), ('run_id', 'previous-wakeup')])
def test_qualified_batch_origin_is_bound_to_study_round_and_run(ladder, field, value):
    raw, snaps = ladder
    raw['routing']['ladder'] = [raw['routing']['ladder'][0]]
    p = placement(ladder)
    proof = next(iter(batch_proof(ladder).values()))
    proof['request'][field] = value
    if field == 'study_id':
        proof['request']['study_key'] = synthetic_study_key(value)
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
    ('study_key', 'c'*64), ('attempt_id', 'another-attempt'), ('object_id', 'another-object'), ('cores', 12)])
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
    other_study = dict(p, study_id='another-study', study_key=synthetic_study_key('another-study'))
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


def separate_study_keys(tmp_path):
    paths = [tmp_path / root / 'smoke' for root in ('first-root', 'second-root')]
    for path in paths:
        path.mkdir(parents=True)
    # These are synthetic directories. This simulates the adapter's bound
    # location identity, without claiming the production adapter is connected.
    return [sha256(str(path.resolve(strict=True)).encode()).hexdigest() for path in paths]


@pytest.mark.parametrize('state,bound', [('queued', True), ('reserved', False), ('unknown', False)])
def test_same_named_studies_and_attempts_in_different_roots_count_separately(ladder, tmp_path, state, bound):
    raw, _ = ladder
    raw['routing']['ladder'] = [cell('jobs', 'batch', 'max', condition='jobs', max_jobs=2)]
    keys = separate_study_keys(tmp_path)
    records = [placement(ladder, cluster='batch', node_name=None, cores=44,
                         study_id='smoke', study_key=key, aid='same-attempt',
                         state=state, job=str(i+1) if bound else None)
               for i, key in enumerate(keys)]
    assert records[0]['study_id'] == records[1]['study_id']
    assert records[0]['attempt_id'] == records[1]['attempt_id']
    assert records[0]['study_key'] != records[1]['study_key']
    assert selected(choose(ladder, placements=records[:1], **waiting_request()))
    result = choose(ladder, placements=records, **waiting_request())
    assert selected(result) is None
    assert 'autonomous_job_limit' in result['candidates'][0]['reasons']


def test_same_named_object_and_batch_limit_are_isolated_by_study_key(ladder, tmp_path):
    raw, _ = ladder
    raw['routing']['ladder'] = [cell('free-alpha', tier='ultra', nodes=['alpha'],
                                    condition='free', min_free_cores=48)]
    first, second = separate_study_keys(tmp_path)
    p = placement(ladder, study_key=first, cid='free-alpha')
    result = choose(ladder, study_key=second, object_id='water-a', placements=[p])
    assert selected(result) and selected(result)['capacity']['cores_available'] == 48
    assert choose(ladder, study_key=first, object_id='water-a', placements=[p])['reason'] == 'object_already_placed_in_run'


def test_same_named_wakeup_is_isolated_by_study_key(ladder, tmp_path):
    raw, _ = ladder
    raw['routing']['ladder'] = [cell('jobs', 'batch', 'max', condition='jobs', max_jobs=4)]
    first, second = separate_study_keys(tmp_path)
    kw = waiting_request(study_key=first)
    assert selected(choose(ladder, study_key=second, **kw)) is None
    kw['wakeups'] += waiting_request(study_key=second)['wakeups']
    assert selected(choose(ladder, study_key=second, **kw))


def test_same_named_study_cannot_borrow_other_root_batch_origin(ladder, tmp_path):
    raw, snaps = ladder
    raw['routing']['ladder'] = [raw['routing']['ladder'][0]]
    first, second = separate_study_keys(tmp_path)
    proof = batch_proof(ladder, study_key=first)
    p = placement(ladder, study_key=second, batch_input_sha256=next(iter(proof)))
    observe(snaps, p)
    result = choose(ladder, study_key=second, placements=[p], batch_inputs=proof)
    assert selected(result) is None
    assert 'batch_origin_unverified' in result['candidates'][0]['reasons']


@pytest.mark.parametrize('source', ['request', 'placement', 'wakeup', 'batch'])
@pytest.mark.parametrize('value', ['missing', None, '', 'g'*64, 'A'*64, 'a'*63, True, ['a'*64]])
def test_missing_or_invalid_study_key_never_allows_selection(ladder, source, value):
    raw, snaps = ladder
    raw['routing']['ladder'] = [raw['routing']['ladder'][0]]
    p = placement(ladder)
    batches = batch_proof(ladder)
    proof = next(iter(batches.values()))
    wait = waiting_request()
    data = {'request': proof['request'], 'batch': proof['request'],
            'placement': p, 'wakeup': wait['wakeups'][0]}[source]
    if value == 'missing':
        del data['study_key']
    else:
        data['study_key'] = value
    if source == 'batch':
        observe(snaps, p)
        result = choose(ladder, placements=[p], batch_inputs=batches)
        assert selected(result) is None
        assert 'batch_origin_unverified' in result['candidates'][0]['reasons']
    else:
        with pytest.raises((KeyError, TypeError, ValueError)):
            if source == 'request':
                route.select_ladder(raw, snaps, **proof['request'], placements=[], wakeups=[], now=NOW)
            elif source == 'placement':
                choose(ladder, placements=[p])
            else:
                choose(ladder, **wait)


@pytest.mark.parametrize('source', ['request-placement', 'placements', 'wakeup', 'batch'])
def test_one_study_key_cannot_carry_conflicting_display_ids(ladder, source):
    p = placement(ladder)
    if source == 'batch':
        raw, snaps = ladder
        raw['routing']['ladder'] = [raw['routing']['ladder'][0]]
        p = placement(ladder)
        proof = batch_proof(ladder, study_id='contradictory-name', study_key=p['study_key'])
        p['batch_input_sha256'] = next(iter(proof))
        observe(snaps, p)
        result = choose(ladder, placements=[p], batch_inputs=proof)
        assert selected(result) is None
        assert 'batch_origin_unverified' in result['candidates'][0]['reasons']
        return
    with pytest.raises(ValueError):
        if source == 'request-placement':
            choose(ladder, study_id='contradictory-name', study_key=p['study_key'], placements=[p])
        elif source == 'placements':
            other = placement(ladder, aid='second', job='2', study_id='contradictory-name',
                              study_key=p['study_key'])
            choose(ladder, placements=[p, other])
        else:
            choose(ladder, **waiting_request(study_id='contradictory-name', study_key=p['study_key']))


def test_wakeup_key_is_required_even_without_waiting_request(ladder):
    wake = waiting_request()['wakeups'][0]
    del wake['study_key']
    with pytest.raises(KeyError):
        choose(ladder, wakeups=[wake])


def evaluation_reference(source):
    return {key: source[key] for key in ('study_key', 'attempt_id', 'record_sha256')}


def evaluation_source(ladder):
    return placement(ladder, cluster='pool', node_name=None, capacity_node='pool-a',
                     cid='source', object_id='water-b', run='previous-wakeup')


@pytest.fixture
def reevaluation(ladder):
    raw, _ = ladder
    raw['routing']['ladder'] = [
        cell('higher', tier='ultra', nodes=['alpha'], condition='free', min_free_cores=48),
        cell('source', 'pool', 'ultra', condition='free', min_free_cores=48),
        cell('lower', 'default', 'max', condition='free', min_free_cores=44)]
    return ladder, evaluation_source(ladder)


@pytest.mark.parametrize('run,reason', [('run-a', 'object_already_placed_in_run'),
                                      ('previous-wakeup', 'object_already_active_in_round')])
def test_evaluation_selects_higher_cell_without_exempting_other_evidence(reevaluation, run, reason):
    ladder, source = reevaluation
    source['run_id'] = run
    ordinary = choose(ladder, placements=[source])
    assert ordinary['reason'] == reason
    assert ordinary == choose(ladder, placements=[source], evaluate_from=None)
    assert 'evaluation_only' not in ordinary and 'evaluate_from' not in ordinary
    ref = evaluation_reference(source)
    result = choose(ladder, placements=[source], evaluate_from=ref)
    assert selected(result)['cell_id'] == 'higher'
    assert result['evaluation_only'] is True and result['evaluate_from'] == ref
    assert result['evidence']['input_sha256'] != ordinary['evidence']['input_sha256']
    # The original job is still part of the exact same occupation evidence.
    for key in ('placements_sha256', 'config_sha256', 'snapshots', 'wakeups_sha256'):
        assert result['evidence'][key] == ordinary['evidence'][key]


@pytest.mark.parametrize('kind', ['stale', 'failed-node-sampling'])
def test_r33_evaluation_source_snapshot_must_remain_known(reevaluation, kind):
    ladder, source = reevaluation
    _, snaps = ladder
    if kind == 'stale':
        snaps['pool']['sampled_at'] = (NOW-timedelta(minutes=4)).isoformat()
    else:
        snaps['pool']['cluster']['nodes_error'] = 'synthetic sampling failure'
    result = choose(ladder, placements=[source], evaluate_from=evaluation_reference(source))
    assert selected(result) is None
    assert result['reason'] == 'snapshot_missing_failed_or_stale'


@pytest.mark.parametrize('kind', ['empty', 'missing-study', 'missing-attempt', 'missing-sha',
    'extra', 'non-dict', 'wrong-study', 'invalid-study', 'wrong-attempt', 'wrong-sha',
    'invalid-sha', 'absent-source'])
def test_evaluation_requires_exact_source_reference(reevaluation, kind):
    ladder, source = reevaluation
    ref, records = evaluation_reference(source), [source]
    if kind == 'empty': ref = {}
    elif kind.startswith('missing-'):
        del ref[{'missing-study': 'study_key', 'missing-attempt': 'attempt_id',
                 'missing-sha': 'record_sha256'}[kind]]
    elif kind == 'extra': ref['approved'] = True
    elif kind == 'non-dict': ref = []
    elif kind == 'wrong-study': ref['study_key'] = synthetic_study_key('another-root')
    elif kind == 'invalid-study': ref['study_key'] = None
    elif kind == 'wrong-attempt': ref['attempt_id'] = 'missing-attempt'
    elif kind == 'wrong-sha': ref['record_sha256'] = 'c'*64
    elif kind == 'invalid-sha': ref['record_sha256'] = 'not-a-hash'
    else: records = []
    with pytest.raises(ValueError):
        choose(ladder, placements=records, evaluate_from=ref)


@pytest.mark.parametrize('kind', ['exact-duplicate', 'alias-duplicate', 'conflict', 'distinct-binding'])
def test_evaluation_source_is_unique_after_verified_alias_normalization(reevaluation, kind):
    ladder, source = reevaluation
    raw, snaps = ladder
    if kind == 'alias-duplicate':
        raw['clusters']['pool-peer'] = deepcopy(raw['clusters']['pool'])
        snaps['pool-peer'] = deepcopy(snaps['pool'])
        snaps['pool-peer']['cluster']['name'] = 'pool-peer'
        source = evaluation_source(ladder)
        other = dict(source, cluster='pool-peer', job_id='pool-peer:1')
    elif kind == 'distinct-binding':
        other = dict(source, cluster='default', job_id='default:2')
    else:
        other = dict(source, **({'mem_gb': 1} if kind == 'conflict' else {}))
    if kind in ('conflict', 'distinct-binding'):
        with pytest.raises(ValueError):
            choose(ladder, placements=[source, other], evaluate_from=evaluation_reference(source))
    else:
        one = choose(ladder, placements=[source], evaluate_from=evaluation_reference(source))
        repeated = choose(ladder, placements=[source, other], evaluate_from=evaluation_reference(source))
        assert repeated == one


@pytest.mark.parametrize('run,reason', [('run-a', 'object_already_placed_in_run'),
                                      ('another-wakeup', 'object_already_active_in_round')])
def test_evaluation_exemption_does_not_hide_another_same_object_record(reevaluation, run, reason):
    ladder, source = reevaluation
    other = placement(ladder, cluster='default', node_name=None, capacity_node='default-a',
                      cores=44, aid='second-attempt', job='2', cid='lower', object_id='water-b', run=run)
    result = choose(ladder, placements=[source, other], evaluate_from=evaluation_reference(source))
    assert selected(result) is None and result['reason'] == reason


@pytest.mark.parametrize('kind', ['config', 'cell', 'class', 'cluster', 'node', 'target',
                                 'cores', 'memory', 'round', 'object', 'manual'])
def test_evaluation_source_cell_and_ownership_must_still_match(reevaluation, kind):
    ladder, source = reevaluation
    raw, _ = ladder
    if kind == 'config': source['config_sha256'] = 'c'*64
    elif kind == 'cell': source['cell_id'] = 'removed-cell'
    elif kind == 'class':
        raw['routing']['ladder'][1]['classes'] = ['small']
        source['config_sha256'] = route.ladder_config_identity(raw)
    elif kind == 'cluster': source.update(cluster='default', job_id='default:1')
    elif kind == 'node': source['capacity_node'] = 'missing-node'
    elif kind == 'target': source['target_node'] = 'pool-a'
    elif kind == 'cores': source['cores'] = 44
    elif kind == 'memory': source['mem_gb'] = 95
    elif kind == 'round': source['round_id'] = 'older-round'
    elif kind == 'object': source['object_id'] = 'different-object'
    else: source.update(run_id=None, round_id=None)
    with pytest.raises(ValueError):
        choose(ladder, placements=[source], evaluate_from=evaluation_reference(source))


def test_evaluation_source_named_fraction_must_match_actual_node(ladder):
    raw, _ = ladder
    raw['routing']['ladder'] = [
        cell('higher', 'pool', 'ultra', condition='free', min_free_cores=48),
        cell('source', tier='ultra', nodes=['alpha'], condition='free',
             min_free_cores=48, node_fraction='1/4')]
    source = placement(ladder, cid='source', object_id='water-b', run='previous-wakeup')
    # A 96-slot node's quarter is 24 cores, not this cell's 48-core tier.
    with pytest.raises(ValueError):
        choose(ladder, placements=[source], evaluate_from=evaluation_reference(source))


@pytest.mark.parametrize('cap,allowed', [(96, True), (88, False)])
def test_evaluation_retains_original_cores_and_node_reservation(ladder, cap, allowed):
    raw, _ = ladder
    raw['routing']['ladder'] = [
        cell('higher', 'pool', 'max', condition='free', min_free_cores=44),
        cell('source', 'pool', 'ultra', condition='free', min_free_cores=48)]
    raw['clusters']['pool']['resources']['max_committed_cores'] = cap
    source = evaluation_source(ladder)
    result = choose(ladder, placements=[source], evaluate_from=evaluation_reference(source))
    if allowed:
        assert selected(result)['cell_id'] == 'higher'
        assert selected(result)['capacity']['cores_available'] == 48
    else:
        assert selected(result) is None
        assert 'account_core_limit' in result['candidates'][0]['reasons']


@pytest.mark.parametrize('others,allowed', [(2, True), (3, False)])
def test_evaluation_retains_original_shared_account_autonomous_job(ladder, others, allowed):
    raw, _ = ladder
    raw['clusters']['batch-test']['allowed_templates'] = ['gaussian']
    raw['routing']['ladder'] = [
        cell('higher', 'batch', 'max', condition='jobs', max_jobs=4),
        cell('source', 'batch-test', 'max', condition='queue')]
    source = placement(ladder, cluster='batch-test', node_name=None, capacity_node='batch-a',
                       cores=44, cid='source', object_id='water-b', run='previous-wakeup')
    records = [source] + [placement(ladder, cluster='batch', node_name=None, cores=44,
        aid='older-'+str(i), job=str(i+2), study_id='other-study', round_id='older-round') for i in range(others)]
    result = choose(ladder, placements=records, evaluate_from=evaluation_reference(source), **waiting_request())
    if allowed:
        assert selected(result)['cell_id'] == 'higher'
    else:
        assert selected(result) is None
        assert 'autonomous_job_limit' in result['candidates'][0]['reasons']


@pytest.mark.parametrize('with_other,allowed', [(False, True), (True, False)])
def test_evaluation_retains_original_and_older_round_global_queue_slots(ladder, with_other, allowed):
    raw, _ = ladder
    raw['routing']['ladder'] = [
        cell('higher', tier='ultra', nodes=['alpha'], condition='queue'),
        cell('source', 'pool', 'ultra', condition='queue')]
    source = evaluation_source(ladder)
    records = [source]
    if with_other:
        records.append(placement(ladder, cluster='batch-test', node_name=None, cores=44,
            aid='older', job=None, state='unknown', study_id='other-study', round_id='older-round'))
    result = choose(ladder, placements=records, evaluate_from=evaluation_reference(source))
    if allowed:
        assert selected(result)['cell_id'] == 'higher' and selected(result)['needs_queue']
    else:
        assert selected(result) is None
        assert 'global_queue_limit' in result['candidates'][0]['reasons']


def test_evaluation_never_selects_same_or_lower_cell(reevaluation):
    ladder, source = reevaluation
    _, snaps = ladder
    snaps['compute']['cluster']['nodes'][0] = node('alpha', used=96)
    result = choose(ladder, placements=[source], evaluate_from=evaluation_reference(source))
    assert selected(result) is None
    for row in result['candidates']:
        if row['cell_id'] in ('source', 'lower'):
            assert 'not_strictly_higher_than_source' in row['reasons']


def test_evaluation_different_node_in_same_cell_is_not_higher(ladder):
    raw, _ = ladder
    raw['routing']['ladder'] = [cell('source', tier='ultra', nodes=['alpha', 'echo'],
                                    condition='free', min_free_cores=48)]
    source = placement(ladder, cid='source', object_id='water-b', run='previous-wakeup')
    result = choose(ladder, placements=[source], evaluate_from=evaluation_reference(source))
    assert selected(result) is None
    assert {r['capacity_node'] for r in result['candidates']} == {'alpha', 'echo'}
    assert all('not_strictly_higher_than_source' in r['reasons'] for r in result['candidates'])


def test_small_evaluation_uses_queue_priority_before_cell_index(ladder):
    raw, _ = ladder
    raw['routing']['ladder'] = [
        cell('source', tier='general', nodes=['alpha'], classes=['small'],
             condition='queue', node_fraction='1/4'),
        cell('higher', tier='simple', nodes=['charlie'], classes=['small'],
             condition='free', min_free_cores=16, node_fraction='1/4')]
    source = placement(ladder, cores=24, cid='source', object_id='water-b', run='previous-wakeup')
    ordinary = choose(ladder, job_class='small', object_id='different-object', placements=[source])
    assert selected(ordinary)['cell_id'] == 'higher'
    result = choose(ladder, job_class='small', placements=[source], evaluate_from=evaluation_reference(source))
    assert selected(result)['cell_id'] == 'higher'
    assert selected(result)['cell_index'] == 1  # Better under the ordinary small-system ordering.


def test_small_evaluation_does_not_replace_occupied_priority_with_cell_index(ladder):
    raw, _ = ladder
    raw['routing']['ladder'] = [
        cell('earlier-empty', tier='general', nodes=['alpha'], classes=['small'],
             condition='free', min_free_cores=24, node_fraction='1/4'),
        cell('source', tier='simple', nodes=['charlie'], classes=['small'],
             condition='free', min_free_cores=16, node_fraction='1/4')]
    source = placement(ladder, node_name='charlie', cores=16, cid='source',
                       object_id='water-b', run='previous-wakeup')
    ordinary = choose(ladder, job_class='small', object_id='different-object', placements=[source])
    assert selected(ordinary)['cell_id'] == 'source'
    result = choose(ladder, job_class='small', placements=[source], evaluate_from=evaluation_reference(source))
    assert selected(result) is None
    assert 'not_strictly_higher_than_source' in result['candidates'][0]['reasons']


def test_evaluation_is_readonly_and_does_not_add_cli_bypass(reevaluation, monkeypatch, capsys):
    from ag.transport import SSHTransport
    ladder, source = reevaluation
    ref = evaluation_reference(source)
    before = deepcopy((ladder, source, ref))
    monkeypatch.setattr(SSHTransport, 'run', lambda *a: pytest.fail('network'))
    result = choose(ladder, placements=[source], evaluate_from=ref)
    assert selected(result) and (ladder, source, ref) == before
    monkeypatch.setattr(route, 'load_config', lambda: pytest.fail('CLI must reject unsupported bypass'))
    with pytest.raises(SystemExit) as error:
        cli.main(['route', '--template', 'gaussian', '--tier', 'general',
                  '--evaluate-from', json.dumps(ref)])
    assert error.value.code == 2 and '--evaluate-from' in capsys.readouterr().err
