"""Synthetic wake journals and monitor caches; no live network or configuration."""
from datetime import datetime, timezone
import json

import pytest

from ag import autonomy as a
from test_autonomy import env, ready, change  # noqa: F401


def snapshots(env, *, relay=False, direct=True):
    cfg, root, clock = env
    cfg['clusters'] = {'relay-a': {'relay_group': 'relay'}, 'direct-a': {}}
    for name, success in [('relay-a', relay), ('direct-a', direct)]:
        directory = root.parent / '.ag-monitor' / name
        directory.mkdir(parents=True, exist_ok=True)
        (directory / 'latest.json').write_text(json.dumps(dict(schema='ag-monitor/1',
            sampled_at=datetime.fromtimestamp(clock[0], timezone.utc).isoformat(),
            last_ok_at=datetime.fromtimestamp(clock[0], timezone.utc).isoformat() if success else None,
            interval_seconds=60, ok=success, error=None if success else 'synthetic transport failure',
            own=dict(cores_in_use=0, core_cap=44, jobs=[]), warnings=[],
            cluster=dict(cores_total=0, cores_used=0, nodes=[], queues=[]))))


def start(env, **settings):
    snapshots(env)
    cfg, root, _ = env
    cfg['autonomy'] = settings
    plan = ready(env)
    run = a.start(cfg, root.name, plan['plan_id'], 'synthetic-owner')
    return plan, run


def retest(env, plan, run):
    cfg, root, _ = env
    return a.link_recheck(cfg, root.name, run['run_id'], run['token'], plan_sha256=plan['sha256'])


def failure(env, plan, run, obj):
    cfg, root, _ = env
    return a.record_presubmit_failure(cfg, root.name, run['run_id'], run['token'],
        object_id=obj, attempt_id=None, plan_sha256=plan['sha256'], reason='synthetic SSH failure')


def test_default_recheck_stays_in_original_lease_and_does_not_retry_objects(env):
    plan, run = start(env)
    assert run['link_health']['status'] == 'relay_outage'
    assert run['link_recheck']['next_at'] == 2800
    cfg, root, clock = env
    failure(env, plan, run, 'water')
    clock[0] = 2799
    assert not retest(env, plan, run)['rechecked']
    clock[0] = 2800
    snapshots(env)
    result = retest(env, plan, run)
    assert result['rechecked']
    assert result['link_recheck']['attempts'] == 1
    assert result['link_recheck']['reason'] == 'lease_deadline'
    assert result['link_recheck']['next_at'] is None
    assert result['state']['lease']['run_until'] == 4600
    assert result['state']['lease']['expires_at'] == 6400
    with pytest.raises(a.PresubmitDeferred):
        a.check_presubmit_retry(result['state'], 'water')
    assert result['state']['totals']['attempt'] == 0
    assert not result['state'].get('submissions')
    clock[0] = 4600
    with pytest.raises(ValueError, match='60 minute'):
        retest(env, plan, run)
    journal = (root / 'autonomy/journal.jsonl').read_text()
    assert journal.count('"op":"link_recheck"') == 1


def test_two_is_a_cap_not_a_new_lease_or_unbounded_loop(env):
    plan, run = start(env, link_recheck_interval_minutes=10)
    _, _, clock = env
    for due in (1600, 2200):
        clock[0] = due
        snapshots(env)
        result = retest(env, plan, run)
        assert result['rechecked']
    assert result['link_recheck']['attempts'] == 2
    assert result['link_recheck']['reason'] == 'exhausted'
    clock[0] = 2800
    snapshots(env, relay=True)
    assert not retest(env, plan, run)['rechecked']


def test_stale_retest_is_unknown_and_never_old_success_recovery(env):
    plan, run = start(env)
    _, _, clock = env
    clock[0] = 2800
    result = retest(env, plan, run)
    assert result['link_health']['status'] == 'unknown'
    assert all(e['status'] == 'unknown' and e['reason'] == 'stale' for e in result['link_health']['entries'])
    assert result['state']['runs'][run['run_id']]['ssh_pause_exempt']


def test_recovered_retest_keeps_exemption_and_original_attempt_budget(env):
    plan, run = start(env)
    _, _, clock = env
    clock[0] = 2800
    snapshots(env, relay=True)
    result = retest(env, plan, run)
    assert result['link_health']['status'] == 'healthy'
    assert result['link_recheck']['reason'] == 'not_needed'
    assert result['state']['runs'][run['run_id']]['ssh_pause_exempt']
    assert result['state']['totals'] == run['state']['totals']


def test_exempt_wakes_do_not_pause_but_object_limit_is_retained(env):
    plan, run = start(env)
    cfg, root, clock = env
    result = failure(env, plan, run, 'water')
    assert result['state']['runs'][run['run_id']]['ssh_failed_exempt']
    assert not result['state']['paused']
    change(env, run, 'finish', reason='synthetic finish')
    clock[0] += 10
    snapshots(env)
    second = a.start(cfg, root.name, plan['plan_id'], 'second-owner')
    result = failure(env, plan, second, 'water')
    assert not result['state']['paused']
    with pytest.raises(a.ObjectRefused, match='two actual presubmit'):
        a.check_presubmit_retry(result['state'], 'water')
    assert len(result['state']['presubmit_failures']) == 2


def test_nonrelay_failures_still_pause_on_two_wakes_and_other_stops_remain(env):
    plan, run = start(env)
    cfg, root, clock = env
    change(env, run, 'finish', reason='end exempt wake')
    for i in range(2):
        clock[0] += 10
        snapshots(env, relay=True)
        current = a.start(cfg, root.name, plan['plan_id'], f'owner-{i}')
        result = failure(env, plan, current, f'water-{i}')
        assert result['state']['paused'] is (i == 1)
        if i == 0:
            change(env, current, 'finish', reason='first ordinary failure')
    with pytest.raises(ValueError, match='paused'):
        a.check(cfg, root.name, current['run_id'], current['token'], action='submit', plan_sha256=plan['sha256'])


@pytest.mark.parametrize('exempt_count', [1, 3])
def test_ssh_streak_spans_exempt_wakes_without_counting_them_as_success(env, exempt_count):
    cfg, root, clock = env
    snapshots(env, relay=True)
    plan = ready(env)
    first = a.start(cfg, root.name, plan['plan_id'], 'first-ordinary-owner')
    assert not failure(env, plan, first, 'water-first')['state']['paused']
    change(env, first, 'finish', reason='First ordinary SSH failure')

    for index in range(exempt_count):
        clock[0] += 10
        snapshots(env)
        exempt = a.start(cfg, root.name, plan['plan_id'], f'exempt-owner-{index}')
        result = failure(env, plan, exempt, f'water-exempt-{index}')
        assert result['state']['runs'][exempt['run_id']]['ssh_pause_exempt']
        assert result['state']['runs'][exempt['run_id']]['ssh_failed_exempt']
        assert not result['state']['paused']
        change(env, exempt, 'finish', reason='Exempt relay outage does not prove success')

    clock[0] += 10
    snapshots(env, relay=True)
    last = a.start(cfg, root.name, plan['plan_id'], 'last-ordinary-owner')
    result = failure(env, plan, last, 'water-last')
    assert result['state']['paused']
    replay = a.status(cfg, root.name)['state']
    assert replay['paused'] and replay['phase'] == 'paused'
    assert len(replay['presubmit_failures']) == exempt_count + 2
    assert not replay.get('submissions') and replay['totals']['attempt'] == 0


def test_ssh_streak_resets_only_after_nonexempt_successful_wake(env):
    cfg, root, clock = env
    snapshots(env, relay=True)
    plan = ready(env)
    first = a.start(cfg, root.name, plan['plan_id'], 'first-ordinary-owner')
    assert not failure(env, plan, first, 'water-first')['state']['paused']
    change(env, first, 'finish', reason='First ordinary SSH failure')

    clock[0] += 10
    snapshots(env)
    exempt = a.start(cfg, root.name, plan['plan_id'], 'exempt-owner')
    result = failure(env, plan, exempt, 'water-exempt')
    assert result['state']['runs'][exempt['run_id']]['ssh_pause_exempt']
    assert not result['state']['paused']
    change(env, exempt, 'finish', reason='Exempt relay outage')

    clock[0] += 10
    snapshots(env, relay=True)
    success = a.start(cfg, root.name, plan['plan_id'], 'successful-ordinary-owner')
    assert not success['state']['runs'][success['run_id']].get('ssh_pause_exempt')
    change(env, success, 'finish', reason='Ordinary wake completed without SSH failure')

    clock[0] += 10
    snapshots(env, relay=True)
    last = a.start(cfg, root.name, plan['plan_id'], 'last-ordinary-owner')
    result = failure(env, plan, last, 'water-last')
    assert not result['state']['paused']
    replay = a.status(cfg, root.name)['state']
    assert not replay['paused'] and replay['phase'] == 'running'
    assert len(replay['presubmit_failures']) == 3
    assert not replay.get('submissions') and replay['totals']['attempt'] == 0


def test_recheck_requires_current_owner_plan_and_versions(env, monkeypatch):
    plan, run = start(env)
    cfg, root, clock = env
    clock[0] = 2800
    snapshots(env)
    before = (root / 'autonomy/journal.jsonl').read_bytes()
    with pytest.raises(ValueError, match='owner'):
        a.link_recheck(cfg, root.name, run['run_id'], 'wrong', plan_sha256=plan['sha256'])
    with pytest.raises(ValueError, match='hash'):
        a.link_recheck(cfg, root.name, run['run_id'], run['token'], plan_sha256='0' * 64)
    monkeypatch.setattr(a, 'versions', lambda: {})
    with pytest.raises(ValueError, match='versions'):
        retest(env, plan, run)
    assert (root / 'autonomy/journal.jsonl').read_bytes() == before


def test_status_is_readonly_and_replays_recorded_link_fields(env):
    plan, run = start(env)
    cfg, root, _ = env
    before = (root / 'autonomy/journal.jsonl').read_bytes()
    result = a.status(cfg, root.name)
    assert result['link_health'] == run['link_health']
    assert result['link_recheck'] == run['link_recheck']
    assert (root / 'autonomy/journal.jsonl').read_bytes() == before


def test_relay_is_blocked_while_independent_entry_can_keep_its_route(env):
    plan, run = start(env)
    cfg, root, _ = env
    with a.submission_guard(cfg, root.name, run['run_id'], run['token'], plan_sha256=plan['sha256']) as guard:
        assert guard.check_link(cfg, cluster='direct-a')['status'] == 'relay_outage'
        with pytest.raises(a.PresubmitDeferred, match='Relay entry'):
            guard.check_link(cfg, cluster='relay-a')
    snapshots(env, direct=False)
    with a.submission_guard(cfg, root.name, run['run_id'], run['token'], plan_sha256=plan['sha256']) as guard:
        with pytest.raises(a.PresubmitDeferred, match='All monitor entries'):
            guard.check_link(cfg, cluster='direct-a')
    state = a.status(cfg, root.name)['state']
    assert not state['paused']
    assert not state.get('submissions')


@pytest.mark.parametrize('kind', ['link', 'ssh'])
@pytest.mark.parametrize('dispatched', [False, True])
def test_exempt_wake_keeps_consumed_failure_cap_and_unknown_pause(env, kind, dispatched):
    from ag.autonomy_submission import machine_lock
    from test_autonomy import consumed_record, consume
    plan, run = start(env)
    cfg, root, _ = env
    record = consumed_record(plan, run)
    consume(env, plan, run, record)
    if dispatched:
        with machine_lock(), a.submission_guard(cfg, root.name, run['run_id'], run['token'],
                                               plan_sha256=plan['sha256']) as guard:
            guard.dispatch_started(record['attempt_id'])
    with machine_lock():
        result = a.boundary_failure(cfg, root.name, record['attempt_id'], record['ownership_sha256'],
            run_id=run['run_id'], token=run['token'], dispatched=dispatched,
            reason='unknown' if dispatched else 'failed_presubmit', failure_kind=kind)
    state = result['state']
    assert state['paused'] == dispatched
    assert state['runs'][run['run_id']]['ssh_pause_exempt']
    assert not state['runs'][run['run_id']].get('ssh_failed')
    assert len(state['submissions']) == 1
    if not dispatched:
        assert len(a._presubmit_failures(state, record['object_id'])) == 1
        with pytest.raises(a.PresubmitDeferred, match='next wake'):
            a.check_presubmit_retry(state, record['object_id'])
