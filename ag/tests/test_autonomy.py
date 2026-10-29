"""Synthetic local files/processes only; no calculation or live study."""
from copy import deepcopy
from hashlib import sha256
import json
import multiprocessing
import os
from pathlib import Path
import socket

import pytest

from ag import autonomy as a
from ag import _autonomy_store as disk
from ag import cli, transport


VERSIONS = dict(ag_version='test-version', git_commit='a' * 40, dirty=False,
                rdkit='test-rdkit', goodvibes='test-goodvibes')


@pytest.fixture
def env(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    study = root / 'study-demo'
    study.mkdir()
    (study / 'attempts').mkdir()
    (study / 'study.md').write_text('Synthetic unchanged study\n')
    clock = [1000.0]
    monkeypatch.setattr(a, 'now', lambda: clock[0])
    monkeypatch.setattr(a, 'versions', lambda: dict(VERSIONS))
    cfg = {'local': {'studies_root': str(root)}}
    return cfg, study, clock


def spec(**changes):
    result = dict(goal='Compare synthetic water models', comparison_groups=['water-a', 'water-b'],
                  method_policy='Synthetic method only', mechanism_scope='No reaction',
                  system_rules={'main': 'Synthetic main model', 'small': 'Synthetic water model'},
                  estimated_hours=2, attempt_limit=10, valid_until=100000.0)
    result.update(changes)
    return result


def ready(env):
    cfg, study, _ = env
    a.initialize(cfg, study.name)
    plan = a.create_plan(cfg, study.name, spec())
    a.confirm(cfg, study.name, plan['plan_id'], plan['sha256'], 'Synthetic human plan confirmation')
    a.begin(cfg, study.name, plan['plan_id'], 'Explicit synthetic round authorization')
    return plan


def running(env):
    plan = ready(env)
    cfg, study, _ = env
    run = a.start(cfg, study.name, plan['plan_id'], 'session-one')
    return plan, run


def change(env, run, op='update', **fields):
    cfg, study, _ = env
    if op == 'end':
        fields.setdefault('round_id', run['state']['current_round'])
    if op == 'update':
        fields = dict(summary='Collected synthetic result', pending=['Choose model'],
                      objects={'water': {'attempt': 'synthetic-001'}}, **fields)
    return a.change(cfg, study.name, op, run['run_id'], run['token'], **fields)


def count(env, run, request='request-one', **fields):
    data = dict(kind='attempt', request_id=request, object_id='water', failure_class='none',
                evidence='Synthetic local intent only')
    data.update(fields)
    return change(env, run, 'count', **data)


def check(env, plan, run, action='prepare'):
    cfg, study, _ = env
    return a.check(cfg, study.name, run['run_id'], run['token'], action=action, plan_sha256=plan['sha256'])


def image_tree(root):
    return {str(p.relative_to(root)): (p.stat().st_mtime_ns, p.read_bytes())
            for p in root.rglob('*') if p.is_file()}


def test_plan_creation_is_not_confirmation_and_revision_has_new_hash(env):
    cfg, study, _ = env
    a.initialize(cfg, study.name)
    plan = a.create_plan(cfg, study.name, spec())
    assert not plan['confirmed']
    assert plan['plan']['versions'] == VERSIONS
    assert a.status(cfg, study.name)['state']['plans'][plan['plan_id']]['confirmation'] is None
    with pytest.raises(ValueError, match='confirmation'):
        a.begin(cfg, study.name, plan['plan_id'], 'Cannot begin unconfirmed plan')
    with pytest.raises(ValueError, match='hash'):
        a.confirm(cfg, study.name, plan['plan_id'], '0' * 64, 'Synthetic quote')
    old_bytes = (study / 'autonomy' / f"plan-{plan['plan_id']}.json").read_bytes()
    a.confirm(cfg, study.name, plan['plan_id'], plan['sha256'], 'Synthetic quote')
    a.begin(cfg, study.name, plan['plan_id'], 'Explicit synthetic round authorization')
    assert (study / 'autonomy' / f"plan-{plan['plan_id']}.json").read_bytes() == old_bytes
    new = a.create_plan(cfg, study.name, spec(goal='Revised synthetic goal'))
    assert new['sha256'] != plan['sha256']
    with pytest.raises(ValueError, match='confirmation'):
        a.start(cfg, study.name, new['plan_id'], 'session-one')
    assert not (study / 'approvals').exists()
    assert (study / 'study.md').read_text() == 'Synthetic unchanged study\n'


def test_pause_resume_finish_and_readonly_views(env):
    cfg, study, _ = env
    plan, run = running(env)
    old = image_tree(study)
    assert check(env, plan, run)['eligible_now']
    state = a.status(cfg, study.name)
    assert state['state']['plan_sha256'] == plan['sha256']
    assert not state['submission_counts_verified']
    assert 'token_sha256' not in state['state']['lease']
    assert image_tree(study) == old
    a.pause(cfg, study.name, 'Review synthetic evidence')
    for action in ('prepare', 'submit', 'remedy', 'cancel', 'reroute'):
        with pytest.raises(ValueError, match='paused'):
            check(env, plan, run, action)
    for action in ('observe', 'fetch', 'organize'):
        assert check(env, plan, run, action)['eligible_now']
    updated = change(env, run)
    assert updated['state']['objects']['water']['attempt'] == 'synthetic-001'
    change(env, run, 'resume', reason='Explicit synthetic resume')
    assert check(env, plan, run)['eligible_now']
    finished = change(env, run, 'finish', reason='Synthetic wake finished')
    assert finished['state']['phase'] == 'running' and finished['state']['lease'] is None
    with pytest.raises(ValueError, match='owner'):
        check(env, plan, run)


def test_sixty_and_ninety_minute_boundaries_and_old_owner_fenced(env):
    cfg, study, clock = env
    plan, run = running(env)
    clock[0] = 4599.999
    assert check(env, plan, run)['eligible_now']
    clock[0] = 4600
    for op in ('check', 'update', 'finish'):
        with pytest.raises(ValueError, match='60 minute'):
            if op == 'check':
                check(env, plan, run)
            else:
                change(env, run, op, **({'reason': 'Finished'} if op == 'finish' else {}))
    clock[0] = 6399.999
    with pytest.raises(ValueError, match='holds the lease'):
        a.start(cfg, study.name, plan['plan_id'], 'session-two', takeover_reason='Expired owner')
    clock[0] = 6400
    with pytest.raises(ValueError, match='takeover reason'):
        a.start(cfg, study.name, plan['plan_id'], 'session-two')
    new = a.start(cfg, study.name, plan['plan_id'], 'session-two', takeover_reason='Owner stopped responding')
    assert new['token'] != run['token']
    assert new['state']['runs'][run['run_id']]['outcome'] == 'expired-takeover'
    for op in ('update', 'resume', 'finish', 'end', 'count', 'check'):
        with pytest.raises(ValueError, match='owner'):
            if op == 'count':
                count(env, run)
            elif op == 'check':
                check(env, plan, run)
            else:
                change(env, run, op, **({'reason': 'Old holder'} if op != 'update' else {}))
    assert check(env, plan, new)['eligible_now']
    event = json.loads((study / 'autonomy/journal.jsonl').read_text().splitlines()[-1])
    assert event['data']['previous_lease']['run_id'] == run['run_id']
    assert event['data']['previous_lease']['expires_at'] == 6400


def test_takeover_preserves_pause_and_cumulative_counts(env):
    cfg, study, clock = env
    plan, run = running(env)
    count(env, run)
    a.pause(cfg, study.name, 'Human review')
    clock[0] = 6400
    new = a.start(cfg, study.name, plan['plan_id'], 'session-two', takeover_reason='Expired owner')
    assert new['state']['phase'] == 'paused'
    assert new['state']['totals']['attempt'] == 1
    assert new['state']['runs'][run['run_id']]['totals']['attempt'] == 1
    assert new['state']['runs'][new['run_id']]['totals']['attempt'] == 0
    assert new['state']['current_round'] == run['state']['current_round']
    assert new['state']['rounds'][run['state']['current_round']]['totals']['attempt'] == 1
    with pytest.raises(ValueError, match='paused'):
        check(env, plan, new)
    change(env, new, 'resume', reason='Explicit new-holder resume')
    assert check(env, plan, new)['eligible_now']


def test_count_idempotence_limits_and_plan_revision_cannot_reset_round(env):
    cfg, study, _ = env
    plan, run = running(env)
    result = count(env, run)
    original = image_tree(study)
    duplicate = count(env, run)
    assert duplicate['duplicate'] and duplicate['state']['totals'] == result['state']['totals']
    assert image_tree(study) == original
    with pytest.raises(ValueError, match='reused'):
        count(env, run, evidence='Different evidence')
    for kind in ('remedy', 'cancel', 'reroute'):
        count(env, run, 'request-' + kind, kind=kind, failure_class='synthetic-failure')
    state = a.status(cfg, study.name)['state']
    assert state['totals'] == dict.fromkeys(a.COUNTERS, 1)
    round_id = state['current_round']
    assert state['rounds'][round_id]['totals'] == dict.fromkeys(a.COUNTERS, 1)
    assert state['counts']['request-remedy']['round_id'] == round_id
    assert state['counts']['request-remedy']['object_id'] == 'water'
    assert state['counts']['request-remedy']['failure_class'] == 'synthetic-failure'
    change(env, run, 'finish', reason='Finish first wake')
    new_plan = a.create_plan(cfg, study.name, spec(attempt_limit=1))
    a.confirm(cfg, study.name, new_plan['plan_id'], new_plan['sha256'], 'Synthetic revised confirmation')
    new = a.start(cfg, study.name, new_plan['plan_id'], 'session-two')
    assert new['state']['totals']['attempt'] == 1
    assert new['state']['current_round'] == round_id
    assert new['state']['rounds'][round_id]['totals']['attempt'] == 1
    with pytest.raises(ValueError, match='limit'):
        check(env, new_plan, new)
    # The last already-counted Attempt is not barred by an aggregate counter.
    assert check(env, new_plan, new, 'submit')['eligible_now']


def test_two_normal_wakes_continue_one_round_without_counter_reset(env):
    cfg, study, clock = env
    plan, first = running(env)
    round_id = first['state']['current_round']
    count(env, first, 'wake-one-attempt')
    finished = change(env, first, 'finish', reason='First wake completed')
    assert finished['state']['phase'] == 'running'
    assert finished['state']['lease'] is None
    assert finished['state']['current_round'] == round_id
    clock[0] += 4000
    second = a.start(cfg, study.name, plan['plan_id'], 'session-two')
    assert second['run_id'] != first['run_id']
    assert second['state']['current_round'] == round_id
    count(env, second, 'wake-two-attempt')
    second_finished = change(env, second, 'finish', reason='Second wake completed')
    state = second_finished['state']
    assert state['phase'] == 'running' and state['lease'] is None
    assert state['totals']['attempt'] == state['rounds'][round_id]['totals']['attempt'] == 2
    assert state['runs'][first['run_id']]['totals']['attempt'] == 1
    assert state['runs'][second['run_id']]['totals']['attempt'] == 1
    assert state['runs'][first['run_id']]['round_id'] == round_id
    assert state['runs'][second['run_id']]['round_id'] == round_id


def test_end_blocks_automatic_start_until_explicit_new_round_and_preserves_history(env):
    cfg, study, _ = env
    a.initialize(cfg, study.name)
    plan = a.create_plan(cfg, study.name, spec(attempt_limit=1))
    a.confirm(cfg, study.name, plan['plan_id'], plan['sha256'], 'Synthetic limited plan confirmation')
    with pytest.raises(ValueError):
        a.start(cfg, study.name, plan['plan_id'], 'no-implicit-begin')
    a.begin(cfg, study.name, plan['plan_id'], 'Explicit first round authorization')
    first = a.start(cfg, study.name, plan['plan_id'], 'session-one')
    count(env, first, 'round-one-attempt')
    first_round = first['state']['current_round']
    with pytest.raises(ValueError):
        a.change(cfg, study.name, 'end', None, None, round_id=first_round, reason='Cannot end another live wake')
    ended = change(env, first, 'end', reason='Explicitly end the whole round')
    assert ended['state']['phase'] == 'ended' and ended['state']['lease'] is None
    before = image_tree(study)
    with pytest.raises(ValueError):
        a.start(cfg, study.name, plan['plan_id'], 'automatic-later-wake')
    assert image_tree(study) == before
    with pytest.raises(ValueError):
        a.begin(cfg, study.name, plan['plan_id'], '')
    a.begin(cfg, study.name, plan['plan_id'], 'Explicitly authorize a new round budget')
    second = a.start(cfg, study.name, plan['plan_id'], 'session-two')
    second_round = second['state']['current_round']
    assert second_round != first_round
    assert check(env, plan, second)['eligible_now']
    result = count(env, second, 'round-two-attempt')
    assert result['state']['totals']['attempt'] == 2
    assert result['state']['rounds'][first_round]['totals']['attempt'] == 1
    assert result['state']['rounds'][second_round]['totals']['attempt'] == 1
    with pytest.raises(ValueError, match='limit'):
        check(env, plan, second)
    assert result['state']['counts']['round-one-attempt']['round_id'] == first_round
    assert result['state']['counts']['round-two-attempt']['round_id'] == second_round


def test_between_wake_pause_and_end_do_not_require_a_lease(env):
    cfg, study, _ = env
    plan, run = running(env)
    change(env, run, 'finish', reason='Wake completed')
    with pytest.raises(ValueError):
        a.begin(cfg, study.name, plan['plan_id'], 'Cannot reset active round between wakes')
    paused = a.pause(cfg, study.name, 'Pause between wakes')
    assert paused['state']['phase'] == 'paused'
    next_wake = a.start(cfg, study.name, plan['plan_id'], 'paused-next-wake')
    with pytest.raises(ValueError, match='paused'):
        check(env, plan, next_wake)
    paused_finish = change(env, next_wake, 'finish', reason='Observation wake completed')
    assert paused_finish['state']['phase'] == 'paused'
    ended = a.change(cfg, study.name, 'end', None, None, round_id=run['state']['current_round'],
                     reason='Explicit end between wakes')
    assert ended['state']['phase'] == 'ended' and ended['state']['lease'] is None


def test_delayed_tokenless_end_cannot_end_a_new_round(env):
    cfg, study, _ = env
    plan = ready(env)
    first_round = a.status(cfg, study.name)['state']['current_round']
    a.change(cfg, study.name, 'end', None, None, round_id=first_round, reason='End first round')
    second = a.begin(cfg, study.name, plan['plan_id'], 'Explicitly begin second round')
    second_round = second['state']['current_round']
    assert second_round != first_round and second['state']['lease'] is None
    before = image_tree(study)
    with pytest.raises(ValueError, match='round'):
        a.change(cfg, study.name, 'end', None, None, round_id=first_round,
                 reason='Delayed end command originally intended for first round')
    assert image_tree(study) == before
    current = a.status(cfg, study.name)['state']
    assert current['current_round'] == second_round and current['phase'] == 'running'


def test_guard_rechecks_mutex_and_clock_after_version_inspection(env, monkeypatch):
    cfg, study, clock = env
    plan, run = running(env)
    def slow_versions():
        clock[0] = 4600
        return dict(VERSIONS)
    monkeypatch.setattr(a, 'versions', slow_versions)
    with pytest.raises(ValueError, match='60 minute'):
        check(env, plan, run)
    clock[0] = 1000
    def replace_mutex():
        lock = study / 'autonomy/store.lock'
        lock.rename(lock.with_name('old.lock'))
        lock.write_text('Replacement mutex\n')
        return dict(VERSIONS)
    monkeypatch.setattr(a, 'versions', replace_mutex)
    with pytest.raises(ValueError, match='mutex'):
        check(env, plan, run)


def test_only_intact_initial_event_can_recover_missing_initial_snapshot(env, monkeypatch):
    cfg, study, _ = env
    def fail_publish(self, value):
        raise OSError('Synthetic initial state failure')
    with monkeypatch.context() as scoped:
        scoped.setattr(disk.Store, 'publish', fail_publish)
        with pytest.raises(OSError):
            a.initialize(cfg, study.name)
    preserved = (study / 'autonomy/journal.jsonl').read_bytes()
    with pytest.raises(ValueError):
        a.status(cfg, study.name)
    result = a.change(cfg, study.name, 'recover', None, None, reason='Recover intact initial event')
    assert result['state']['totals'] == dict.fromkeys(a.COUNTERS, 0)
    assert (study / 'autonomy/journal.jsonl').read_bytes().startswith(preserved)


def test_versions_plan_validity_and_expected_hash(env, monkeypatch):
    cfg, study, clock = env
    plan, run = running(env)
    with pytest.raises(ValueError, match='hash'):
        a.check(cfg, study.name, run['run_id'], run['token'], action='submit', plan_sha256='0' * 64)
    monkeypatch.setattr(a, 'versions', lambda: dict(VERSIONS, rdkit='changed-rdkit'))
    with pytest.raises(ValueError, match='versions'):
        check(env, plan, run)
    with pytest.raises(ValueError, match='versions'):
        change(env, run)
    # Pausing and safely ending a run do not require the former toolchain.
    a.pause(cfg, study.name, 'Version drift')
    change(env, run, 'finish', reason='Stop changed runtime')
    monkeypatch.setattr(a, 'versions', lambda: dict(VERSIONS))
    clock[0] = 100000
    with pytest.raises(ValueError, match='expired'):
        a.start(cfg, study.name, plan['plan_id'], 'session-two')


@pytest.mark.parametrize('field,value', [('attempt_limit', True), ('estimated_hours', float('nan')),
                                        ('valid_until', 1000), ('comparison_groups', [])])
def test_invalid_plan_rejected_before_writes(env, field, value):
    cfg, study, _ = env
    a.initialize(cfg, study.name)
    original = image_tree(study)
    with pytest.raises(ValueError):
        a.create_plan(cfg, study.name, spec(**{field: value}))
    assert image_tree(study) == original


@pytest.mark.parametrize('target,damage', [('state.json', b'{'), ('journal.jsonl', b'{'),
                                          ('journal.jsonl', b'')])
def test_truncated_or_empty_records_fail_closed(env, target, damage):
    cfg, study, _ = env
    _, run = running(env)
    count(env, run)
    (study / 'autonomy' / target).write_bytes(damage)
    original = image_tree(study)
    for action in (lambda: a.status(cfg, study.name), lambda: count(env, run, 'another'),
                   lambda: change(env, run, 'recover', reason='Cannot repair corruption')):
        with pytest.raises((ValueError, OSError)):
            action()
    assert image_tree(study) == original


@pytest.mark.parametrize('scope', ['global', 'round'])
def test_edited_counter_and_bool_state_cannot_be_recovered(env, scope):
    cfg, study, _ = env
    _, run = running(env)
    count(env, run)
    path = study / 'autonomy/state.json'
    original = json.loads(path.read_text())
    for value in (0, True, -1):
        edited = deepcopy(original)
        target = edited['state'] if scope == 'global' else edited['state']['rounds'][edited['state']['current_round']]
        target['totals']['attempt'] = value
        path.write_bytes(disk.encode(edited))
        before = image_tree(study)
        with pytest.raises(ValueError):
            change(env, run, 'recover', reason='Do not reset counter')
        assert image_tree(study) == before


def test_plan_bytes_tampered_and_journal_prefix_truncated(env):
    cfg, study, _ = env
    plan, run = running(env)
    plan_path = study / 'autonomy' / f"plan-{plan['plan_id']}.json"
    original = plan_path.read_bytes()
    plan_path.write_bytes(original + b' ')
    with pytest.raises(ValueError, match='changed'):
        check(env, plan, run)
    plan_path.write_bytes(original)
    count(env, run)
    journal = study / 'autonomy/journal.jsonl'
    journal.write_bytes(b''.join(journal.read_bytes().splitlines(keepends=True)[:-1]))
    before = image_tree(study)
    with pytest.raises(ValueError):
        change(env, run, 'recover', reason='Cannot drop committed event')
    assert image_tree(study) == before


def test_missing_noninitial_state_is_not_assumed_zero_or_recreated(env):
    cfg, study, _ = env
    _, run = running(env)
    count(env, run)
    (study / 'autonomy/state.json').unlink()
    before = image_tree(study)
    for action in (lambda: a.status(cfg, study.name),
                   lambda: change(env, run, 'recover', reason='Missing snapshot is unverifiable')):
        with pytest.raises(ValueError):
            action()
    assert image_tree(study) == before


def test_append_failure_never_publishes_state_or_discards_partial_log(env, monkeypatch):
    cfg, study, _ = env
    _, run = running(env)
    old = image_tree(study)
    def fail_append(self, data):
        raise OSError('Synthetic append failure')
    monkeypatch.setattr(disk.Store, 'append', fail_append)
    with pytest.raises(OSError, match='append failure'):
        count(env, run)
    assert image_tree(study) == old
    def partial_append(self, data):
        fd = self.open('journal.jsonl', os.O_WRONLY | os.O_APPEND)
        try:
            os.write(fd, data[:12])
            os.fsync(fd)
        finally:
            os.close(fd)
        raise OSError('Synthetic partial append')
    monkeypatch.setattr(disk.Store, 'append', partial_append)
    with pytest.raises(OSError, match='partial append'):
        count(env, run)
    assert (study / 'autonomy/state.json').read_bytes() == old['autonomy/state.json'][1]
    before = image_tree(study)
    with pytest.raises(ValueError):
        change(env, run, 'recover', reason='Do not remove partial log')
    assert image_tree(study) == before


def _start_process(cfg, name, plan_id, gate, output, session):
    gate.wait(10)
    try:
        result = a.start(cfg, name, plan_id, session)
        output.put(('ok', result['run_id']))
    except ValueError as exc:
        output.put(('error', str(exc)))


def _crash_after_event(env, run, op):
    disk.Store.publish = lambda *args: os._exit(73)
    if op == 'count':
        count(env, run)
    elif op == 'end':
        change(env, run, 'end', reason='Explicit end before process crash')
    else:
        cfg, study, _ = env
        a.pause(cfg, study.name, 'Synthetic pause before crash')


def _join(process):
    process.join(15)
    if process.is_alive():
        process.kill()
        process.join(5)
        pytest.fail('Synthetic child process did not complete')


def test_two_real_processes_compete_for_single_lease(env):
    cfg, study, _ = env
    plan = ready(env)
    ctx = multiprocessing.get_context('fork')
    gate, output = ctx.Event(), ctx.Queue()
    processes = [ctx.Process(target=_start_process, args=(cfg, study.name, plan['plan_id'], gate, output, owner))
                 for owner in ('session-a', 'session-b')]
    for process in processes:
        process.start()
    gate.set()
    for process in processes:
        _join(process)
        assert process.exitcode == 0
    results = [output.get(timeout=3) for _ in processes]
    assert sorted(r[0] for r in results) == ['error', 'ok']
    assert len(a.status(cfg, study.name)['state']['runs']) == 1


@pytest.mark.parametrize('op', ['count', 'pause'])
def test_process_crash_after_durable_event_explicit_recovery_preserves_event(env, op):
    cfg, study, _ = env
    plan, run = running(env)
    ctx = multiprocessing.get_context('fork')
    process = ctx.Process(target=_crash_after_event, args=(env, run, op))
    process.start()
    _join(process)
    assert process.exitcode == 73
    journal = study / 'autonomy/journal.jsonl'
    preserved = journal.read_bytes()
    with pytest.raises(ValueError, match='stale'):
        check(env, plan, run)
    result = change(env, run, 'recover', reason='Replay intact durable event')
    assert journal.read_bytes().startswith(preserved)
    if op == 'count':
        assert result['state']['totals']['attempt'] == 1
        assert count(env, run)['duplicate']
    else:
        assert result['state']['paused']
        with pytest.raises(ValueError, match='paused'):
            check(env, plan, run)


def test_expired_takeover_recovers_stale_snapshot_and_keeps_pause(env):
    cfg, study, clock = env
    plan, run = running(env)
    process = multiprocessing.get_context('fork').Process(target=_crash_after_event, args=(env, run, 'pause'))
    process.start()
    _join(process)
    assert process.exitcode == 73
    clock[0] = 6400
    new = a.start(cfg, study.name, plan['plan_id'], 'session-two', takeover_reason='Crashed expired owner', recover=True)
    assert new['state']['paused']
    with pytest.raises(ValueError, match='owner'):
        change(env, run, 'recover', reason='Old owner returns')
    with pytest.raises(ValueError, match='paused'):
        check(env, plan, new)


def test_crash_after_durable_end_recovers_ended_and_refuses_automatic_restart(env):
    cfg, study, _ = env
    plan, run = running(env)
    count(env, run)
    round_id = run['state']['current_round']
    process = multiprocessing.get_context('fork').Process(target=_crash_after_event, args=(env, run, 'end'))
    process.start()
    _join(process)
    assert process.exitcode == 73
    journal = study / 'autonomy/journal.jsonl'
    preserved = journal.read_bytes()
    with pytest.raises(ValueError, match='stale'):
        a.status(cfg, study.name)
    recovered = a.change(cfg, study.name, 'recover', None, None, reason='Recover explicit round end')
    assert journal.read_bytes().startswith(preserved)
    assert recovered['state']['phase'] == 'ended'
    assert recovered['state']['lease'] is None
    assert recovered['state']['rounds'][round_id]['totals']['attempt'] == 1
    assert recovered['state']['totals']['attempt'] == 1
    with pytest.raises(ValueError):
        a.start(cfg, study.name, plan['plan_id'], 'automatic-wake-after-recovery')


def test_expired_plan_does_not_prevent_explicit_lease_retirement(env):
    cfg, study, clock = env
    _, run = running(env)
    count(env, run)
    a.pause(cfg, study.name, 'Human review remains pending')
    clock[0] = 6399.999
    with pytest.raises(ValueError):
        a.change(cfg, study.name, 'recover', None, None, reason='Too early')
    clock[0] = 100000
    recovered = a.change(cfg, study.name, 'recover', None, None, reason='Retire expired lease and expired plan')
    assert recovered['state']['lease'] is None
    assert recovered['state']['phase'] == 'paused'
    assert recovered['state']['paused']
    assert recovered['state']['totals']['attempt'] == 1
    assert recovered['state']['runs'][run['run_id']]['outcome'] == 'expired-recovered'
    plan = a.create_plan(cfg, study.name, spec(valid_until=200000))
    a.confirm(cfg, study.name, plan['plan_id'], plan['sha256'], 'New synthetic plan confirmation')
    new = a.start(cfg, study.name, plan['plan_id'], 'new-session')
    assert new['state']['paused'] and new['state']['totals']['attempt'] == 1


def _returning_owner(env, plan, run, gate, output):
    gate.wait(10)
    a.now = lambda: 6400
    rejected = []
    for op in ('update', 'finish', 'end', 'resume', 'count', 'check'):
        try:
            if op == 'count':
                count(env, run)
            elif op == 'check':
                check(env, plan, run)
            else:
                change(env, run, op, **({'reason': 'Old process returns'} if op != 'update' else {}))
        except ValueError as exc:
            rejected.append((op, 'owner' in str(exc)))
    output.put(rejected)


def test_real_old_process_cannot_write_or_release_new_lease(env):
    cfg, study, clock = env
    plan, run = running(env)
    ctx = multiprocessing.get_context('fork')
    gate, output = ctx.Event(), ctx.Queue()
    process = ctx.Process(target=_returning_owner, args=(env, plan, run, gate, output))
    process.start()
    clock[0] = 6400
    new = a.start(cfg, study.name, plan['plan_id'], 'replacement', takeover_reason='Expired original owner')
    gate.set()
    _join(process)
    assert process.exitcode == 0
    assert output.get(timeout=3) == [(op, True) for op in ('update', 'finish', 'end', 'resume', 'count', 'check')]
    assert a.status(cfg, study.name)['state']['lease']['run_id'] == new['run_id']


def _pause_racer(env, gate, done, output):
    gate.wait(10)
    cfg, study, _ = env
    a.pause(cfg, study.name, 'Concurrent pause')
    done.set()
    output.put('paused')


def test_pause_races_short_guard_then_blocks_next_action_without_waiting_for_run(env):
    cfg, study, _ = env
    plan, run = running(env)
    ctx = multiprocessing.get_context('fork')
    gate, done, output = ctx.Event(), ctx.Event(), ctx.Queue()
    process = ctx.Process(target=_pause_racer, args=(env, gate, done, output))
    process.start()
    with a.action_guard(cfg, study.name, run['run_id'], run['token'], action='prepare', plan_sha256=plan['sha256']):
        gate.set()
        assert not done.wait(0.1)
    assert done.wait(10), 'pause must not wait for the still-active run'
    _join(process)
    assert process.exitcode == 0 and output.get(timeout=3) == 'paused'
    with pytest.raises(ValueError, match='paused'):
        check(env, plan, run)


def test_readonly_missing_state_never_initializes_and_reinit_never_resets(env):
    cfg, study, _ = env
    old = image_tree(study)
    with pytest.raises(OSError):
        a.status(cfg, study.name)
    assert not (study / 'autonomy').exists()
    assert image_tree(study) == old
    _, run = running(env)
    count(env, run)
    old = image_tree(study)
    with pytest.raises(FileExistsError):
        a.initialize(cfg, study.name)
    assert image_tree(study) == old


@pytest.mark.parametrize('target', ['state.json', 'journal.jsonl', 'store.lock', 'plan'])
def test_symlink_record_rejected_without_touching_target(env, target):
    cfg, study, _ = env
    plan, run = running(env)
    if target == 'plan':
        target = f"plan-{plan['plan_id']}.json"
    original = study / 'autonomy' / target
    external = study.parent / 'external-record'
    external.write_bytes(original.read_bytes())
    original.unlink()
    original.symlink_to(external)
    preserved = external.read_bytes()
    with pytest.raises((ValueError, OSError)):
        count(env, run)
    assert external.read_bytes() == preserved


def test_symlink_directory_and_path_escape_rejected(env):
    cfg, study, _ = env
    outside = study.parent / 'outside'
    outside.mkdir()
    (study / 'autonomy').symlink_to(outside, target_is_directory=True)
    with pytest.raises((ValueError, OSError)):
        a.status(cfg, study.name)
    assert not list(outside.iterdir())
    for name in ('../outside', str(study / '..' / 'outside')):
        with pytest.raises(ValueError):
            a.initialize(cfg, name)


def test_hardlinked_state_rejected(env):
    cfg, study, _ = env
    _, run = running(env)
    os.link(study / 'autonomy/state.json', study.parent / 'hardlink')
    with pytest.raises(ValueError, match='regular'):
        count(env, run)


def test_replaced_lock_inode_refuses_further_write(env):
    cfg, study, _ = env
    ready(env)
    path = study / 'autonomy/store.lock'
    with disk.locked(cfg, study.name, write=True) as store:
        saved, _ = a.load(store)
        path.rename(study / 'autonomy/old-store.lock')
        path.write_text('Unexpected replacement lock\n')
        before = image_tree(study)
        with pytest.raises(ValueError, match='mutex|lock'):
            store.commit(saved, 'pause', a.now(), {'reason': 'Invalid lock inode'}, a.apply)
        assert image_tree(study) == before


def test_plan_input_symlink_is_not_followed_by_cli(env, monkeypatch, capsys):
    cfg, study, _ = env
    a.initialize(cfg, study.name)
    monkeypatch.setattr(cli, 'load_config', lambda **kwargs: cfg)
    source = study.parent / 'source-input.json'
    source.write_bytes(disk.encode(spec()))
    link = study.parent / 'linked-input.json'
    link.symlink_to(source)
    before = image_tree(study)
    code = cli.main(['autonomy', 'plan', '--study', study.name, '--input', str(link), '--json'])
    assert code in (1, 2)
    assert 'error' in json.loads(capsys.readouterr().out)
    assert image_tree(study) == before


@pytest.mark.parametrize('override', [{'dirty': True}, {'git_commit': None}, {'rdkit': None}, {'goodvibes': None}])
def test_unverifiable_or_dirty_versions_cannot_create_plan(env, monkeypatch, override):
    cfg, study, _ = env
    a.initialize(cfg, study.name)
    monkeypatch.setattr(a, 'versions', lambda: dict(VERSIONS, **override))
    before = image_tree(study)
    with pytest.raises(ValueError):
        a.create_plan(cfg, study.name, spec())
    assert image_tree(study) == before


def test_cli_lifecycle_is_local_only_and_never_constructs_transport(env, monkeypatch, capsys):
    cfg, study, _ = env
    loads = []
    def local_config(*, local_only=False):
        assert local_only
        loads.append(local_only)
        return cfg
    def forbidden(*args, **kwargs):
        pytest.fail('Autonomy must not construct Transport or use network')
    monkeypatch.setattr(cli, 'load_config', local_config)
    monkeypatch.setattr(transport.SSHTransport, '__init__', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    def command(op, *args, expected=0):
        code = cli.main(['autonomy', op, '--study', study.name, '--json', *args])
        result = json.loads(capsys.readouterr().out)
        assert code == expected
        return result
    command('init')
    input_path = study.parent / 'synthetic-plan.json'
    input_path.write_bytes(disk.encode(spec()))
    plan = command('plan', '--input', str(input_path))
    command('confirm', '--plan', plan['plan_id'], '--sha256', plan['sha256'], '--quote', 'Synthetic confirmation')
    command('begin', '--plan', plan['plan_id'], '--quote', 'Explicit synthetic round authorization')
    run = command('start', '--plan', plan['plan_id'], '--owner', 'synthetic-cli')
    credentials = ('--run', run['run_id'], '--token', run['token'])
    command('check', *credentials, '--for-action', 'prepare', '--sha256', plan['sha256'])
    command('count', *credentials, '--kind', 'attempt', '--request-id', 'cli-intent', '--object-id', 'water',
            '--failure-class', 'none', '--evidence', 'Synthetic intent')
    command('pause', '--reason', 'Synthetic pause')
    command('check', *credentials, '--for-action', 'submit', '--sha256', plan['sha256'], expected=1)
    update_path = study.parent / 'synthetic-update.json'
    update_path.write_bytes(disk.encode(dict(summary='Synthetic result', pending=[], objects={})))
    command('update', *credentials, '--input', str(update_path))
    command('resume', *credentials, '--reason', 'Explicit synthetic resume')
    def fail_publish(self, value):
        raise OSError('Synthetic state publication failure')
    with monkeypatch.context() as scoped:
        scoped.setattr(disk.Store, 'publish', fail_publish)
        command('update', *credentials, '--input', str(update_path), expected=2)
    command('recover', *credentials, '--reason', 'Explicit intact-journal recovery')
    assert command('finish', *credentials, '--reason', 'Synthetic wake complete')['state']['phase'] == 'running'
    command('end', '--round', run['state']['current_round'], '--reason', 'Explicit synthetic round end')
    old = image_tree(study)
    assert command('status')['state']['phase'] == 'ended'
    assert image_tree(study) == old
    assert len(loads) == 16


def _cancel_binding(env, attempt_id='synthetic-001'):
    return dict(study_id=env[1].name, attempt_id=attempt_id, cluster='Synthetic_Cluster',
                scheduler='slurm', job_id='123', manifest_sha256='b' * 64,
                submission_sha256='c' * 64)


def _consume_cancel(env, plan, run, attempt_id='synthetic-001', **changes):
    cfg, study, _ = env
    fields = dict(plan_sha256=plan['sha256'], binding=_cancel_binding(env, attempt_id),
                  ownership_sha256='d' * 64, kind='no_progress',
                  reason='Synthetic two-snapshot judgment', evidence_sha256='e' * 64)
    fields.update(changes)
    return a._consume_cancellation(cfg, study.name, run['run_id'], run['token'], **fields)


def _cancel_result(env, run, receipt, **changes):
    cfg, study, _ = env
    record = receipt['record']
    fields = dict(attempt_id=record['binding']['attempt_id'],
                  consumption_sha256=record['consumption_sha256'], outcome='accepted',
                  reason='Synthetic scheduler acceptance, not termination', evidence_sha256='f' * 64)
    fields.update(changes)
    return a._record_cancellation_result(cfg, study.name, run['run_id'], run['token'], **fields)


def test_cancellation_consumption_is_separate_from_intents_and_never_a_permit(env, monkeypatch):
    cfg, study, _ = env
    plan, run = running(env)
    monkeypatch.setattr(transport.SSHTransport, '__init__', lambda *a, **k: pytest.fail('local only'))
    monkeypatch.setattr(socket, 'create_connection', lambda *a, **k: pytest.fail('local only'))
    count(env, run, kind='cancel')
    before = a.status(cfg, study.name)['state']
    first = _consume_cancel(env, plan, run)
    second = _consume_cancel(env, plan, run, 'synthetic-002')
    assert not first['cancellation_authorized'] and not second['cancellation_authorized']
    assert 'token_sha256' not in first['record'] and not first['duplicate']
    assert first['record']['binding'] == _cancel_binding(env)
    assert first['record']['ownership_sha256'] == 'd' * 64
    assert first['record']['evidence_sha256'] == 'e' * 64
    after = a.status(cfg, study.name)['state']
    for key in ('counts', 'totals', 'rounds', 'runs'):
        assert after[key] == before[key]
    assert all('token_sha256' not in record for record in after['cancellations'].values())
    with pytest.raises(ValueError, match='limit of two'):
        _consume_cancel(env, plan, run, 'synthetic-003')
    with pytest.raises(ValueError, match='already consumed'):
        _consume_cancel(env, plan, run, ownership_sha256='1' * 64)
    result = _cancel_result(env, run, first)
    assert not result['cancellation_authorized'] and result['record']['outcome'] == 'accepted'
    assert not a.status(cfg, study.name)['state']['paused']
    with pytest.raises(ValueError, match='already consumed'):
        _consume_cancel(env, plan, run)


@pytest.mark.parametrize('override', [
    {'ownership_sha256': ''}, {'evidence_sha256': True}, {'plan_sha256': 'bad'},
    {'reason': ' '}, {'kind': 'submit'}, {'kind': 'reroute'},
    {'kind': 'reroute', 'lineage_sha256': 'bad'}, {'lineage_sha256': 'a' * 64},
])
def test_cancellation_rejects_incomplete_evidence_binding_without_mutation(env, override):
    plan, run = running(env)
    before = image_tree(env[1])
    with pytest.raises(ValueError):
        _consume_cancel(env, plan, run, **override)
    assert image_tree(env[1]) == before


@pytest.mark.parametrize('field,value', [
    ('study_id', 'other-study'), ('attempt_id', '../other'), ('cluster', 'other;true'),
    ('scheduler', 'other'), ('job_id', '123,124'), ('manifest_sha256', 'bad'),
    ('submission_sha256', None),
])
def test_cancellation_rejects_invalid_exact_attempt_binding(env, field, value):
    plan, run = running(env)
    binding = dict(_cancel_binding(env), **{field: value})
    before = image_tree(env[1])
    with pytest.raises(ValueError):
        _consume_cancel(env, plan, run, binding=binding)
    assert image_tree(env[1]) == before


@pytest.mark.parametrize('condition', ['paused', 'expired', 'wrong_token', 'wrong_plan', 'version_drift', 'clock_back'])
def test_cancellation_consumption_rechecks_current_eligibility(env, monkeypatch, condition):
    cfg, study, clock = env
    plan, run = running(env)
    if condition == 'paused':
        a.pause(cfg, study.name, 'Synthetic human pause')
    elif condition == 'expired':
        clock[0] += a.RUN_SECONDS
    elif condition == 'wrong_token':
        run = dict(run, token='different-token')
    elif condition == 'wrong_plan':
        plan = dict(plan, sha256='0' * 64)
    elif condition == 'version_drift':
        monkeypatch.setattr(a, 'versions', lambda: dict(VERSIONS, git_commit='0' * 40))
    else:
        clock[0] -= 1
    before = image_tree(study)
    with pytest.raises(ValueError):
        _consume_cancel(env, plan, run)
    assert image_tree(study) == before


def test_cancellation_reads_clock_after_version_inspection(env, monkeypatch):
    _, study, clock = env
    plan, run = running(env)
    def slow_versions():
        clock[0] += a.RUN_SECONDS
        return dict(VERSIONS)
    monkeypatch.setattr(a, 'versions', slow_versions)
    before = image_tree(study)
    with pytest.raises(ValueError, match='60 minute'):
        _consume_cancel(env, plan, run)
    assert image_tree(study) == before


def test_cancellation_and_reroute_consumption_survive_new_plan_run_and_round(env):
    cfg, study, _ = env
    plan, run = running(env)
    first = _consume_cancel(env, plan, run, kind='reroute', lineage_sha256='1' * 64)
    _cancel_result(env, run, first)
    for new_round in (False, True):
        if new_round:
            change(env, run, 'end', reason='Explicit synthetic round end')
        else:
            change(env, run, 'finish', reason='Finished synthetic wake')
        plan = a.create_plan(cfg, study.name, spec(goal='Revised synthetic plan'))
        a.confirm(cfg, study.name, plan['plan_id'], plan['sha256'], 'Synthetic revised confirmation')
        if new_round:
            a.begin(cfg, study.name, plan['plan_id'], 'Explicit synthetic next round')
        run = a.start(cfg, study.name, plan['plan_id'], 'next-owner')
        with pytest.raises(ValueError, match='already consumed for this Attempt'):
            _consume_cancel(env, plan, run, ownership_sha256='2' * 64)
        with pytest.raises(ValueError, match='original lineage'):
            _consume_cancel(env, plan, run, 'replacement-001', kind='reroute', lineage_sha256='1' * 64)
    next_receipt = _consume_cancel(env, plan, run, 'unrelated-001', kind='reroute', lineage_sha256='2' * 64)
    assert not next_receipt['cancellation_authorized']
    state = a.status(cfg, study.name)['state']
    assert state['reroute_lineages'] == {'1' * 64: 'synthetic-001', '2' * 64: 'unrelated-001'}
    assert state['totals']['cancel'] == 0 and state['totals']['reroute'] == 0


def _cancel_consumer(env, plan, run, attempt_id, gate, output):
    gate.wait(10)
    try:
        _consume_cancel(env, plan, run, attempt_id)
        output.put('consumed')
    except ValueError:
        output.put('rejected')


@pytest.mark.parametrize('attempts,accepted', [
    (['synthetic-001', 'synthetic-002', 'synthetic-003'], 2),
    (['synthetic-001', 'synthetic-001', 'synthetic-001'], 1),
])
def test_cancellation_process_races_cannot_exceed_limits(env, attempts, accepted):
    cfg, study, _ = env
    plan, run = running(env)
    ctx = multiprocessing.get_context('fork')
    gate, output = ctx.Event(), ctx.Queue()
    processes = [ctx.Process(target=_cancel_consumer, args=(env, plan, run, item, gate, output))
                 for item in attempts]
    for process in processes:
        process.start()
    gate.set()
    for process in processes:
        _join(process)
        assert process.exitcode == 0
    assert [output.get(timeout=3) for _ in processes].count('consumed') == accepted
    assert len(a.status(cfg, study.name)['state']['cancellations']) == accepted


def test_cancellation_unknown_is_atomic_paused_and_result_ack_is_idempotent(env):
    cfg, study, _ = env
    plan, run = running(env)
    receipt = _consume_cancel(env, plan, run)
    result = _cancel_result(env, run, receipt, outcome='unknown')
    assert not result['cancellation_authorized']
    state = a.status(cfg, study.name)['state']
    assert state['paused'] and state['phase'] == 'paused'
    before = image_tree(study)
    repeated = _cancel_result(env, run, receipt, outcome='unknown')
    assert repeated['duplicate'] and not repeated['cancellation_authorized']
    assert image_tree(study) == before
    for changes in ({'outcome': 'accepted'}, {'evidence_sha256': '0' * 64},
                    {'consumption_sha256': '0' * 64}):
        with pytest.raises(ValueError):
            _cancel_result(env, run, receipt, **changes)
    assert image_tree(study) == before
    with pytest.raises(ValueError, match='paused'):
        _consume_cancel(env, plan, run, 'synthetic-002')


@pytest.mark.parametrize('ended', [False, True])
def test_late_cancellation_result_preserves_new_owner_or_ended_round(env, ended):
    cfg, study, clock = env
    plan, old = running(env)
    receipt = _consume_cancel(env, plan, old)
    clock[0] += a.LEASE_SECONDS
    new = a.start(cfg, study.name, plan['plan_id'], 'replacement', takeover_reason='Expired original owner')
    with pytest.raises(ValueError, match='owner'):
        _consume_cancel(env, plan, old, 'synthetic-002')
    with pytest.raises(ValueError, match='original consumption'):
        _cancel_result(env, new, receipt, outcome='unknown')
    if ended:
        change(env, new, 'end', reason='Explicit synthetic round end')
    before = a.status(cfg, study.name)['state']
    _cancel_result(env, old, receipt, outcome='unknown')
    after = a.status(cfg, study.name)['state']
    assert after['paused'] and after['phase'] == ('ended' if ended else 'paused')
    for key in ('lease', 'current_round', 'current_plan', 'rounds', 'runs'):
        assert after[key] == before[key]
    clock[0] -= 1
    with pytest.raises(ValueError, match='backwards'):
        _cancel_result(env, old, receipt, outcome='unknown')


@pytest.mark.parametrize('stage', ['consume', 'unknown'])
def test_cancellation_durable_event_survives_failed_state_publication(env, monkeypatch, stage):
    cfg, study, _ = env
    plan, run = running(env)
    receipt = _consume_cancel(env, plan, run) if stage == 'unknown' else None
    def fail_publish(*args):
        raise OSError('Synthetic publication crash')
    with monkeypatch.context() as scoped:
        scoped.setattr(disk.Store, 'publish', fail_publish)
        with pytest.raises(OSError, match='publication crash'):
            if stage == 'consume':
                _consume_cancel(env, plan, run)
            else:
                _cancel_result(env, run, receipt, outcome='unknown')
    journal = study / 'autonomy/journal.jsonl'
    preserved = journal.read_bytes()
    with pytest.raises(ValueError, match='stale'):
        _consume_cancel(env, plan, run)
    recovered = change(env, run, 'recover', reason='Recover intact cancellation event')
    assert journal.read_bytes().startswith(preserved)
    assert len(recovered['state']['cancellations']) == 1
    with pytest.raises(ValueError, match='paused|already consumed'):
        _consume_cancel(env, plan, run)
    if stage == 'unknown':
        assert recovered['state']['paused']
        assert _cancel_result(env, run, receipt, outcome='unknown')['duplicate']
