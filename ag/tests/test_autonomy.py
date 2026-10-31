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
from test_core import cfg, prepared  # noqa: F401; synthetic recording-fake fixtures
from test_slurm import multi  # noqa: F401; synthetic multi-cluster fixture
from test_autonomy_submission import t186_driver_factory  # noqa: F401; actual driver with local fakes


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


def expiring_run(env):
    cfg, study, _ = env
    a.initialize(cfg, study.name)
    plan = a.create_plan(cfg, study.name, spec(valid_until=1100))
    a.confirm(cfg, study.name, plan['plan_id'], plan['sha256'], 'Synthetic short plan confirmation')
    a.begin(cfg, study.name, plan['plan_id'], 'Explicit synthetic short round')
    return plan, a.start(cfg, study.name, plan['plan_id'], 'session-one')


def test_plan_expiry_preserves_reads_only_with_current_ordinary_lease(env):
    cfg, study, clock = env
    plan, run = expiring_run(env)
    # Default events and replayed snapshots retain their historical shape.
    assert 'observe_only' not in run['state']['lease']
    assert 'observe_only' not in run['state']['runs'][run['run_id']]
    start_event = json.loads((study / 'autonomy/journal.jsonl').read_text().splitlines()[-1])
    assert 'observe_only' not in start_event['data']
    clock[0] = 1100
    before = image_tree(study)
    for action in a.READ_ACTIONS:
        assert check(env, plan, run, action)['eligible_now']
    for action in set(a.ACTIONS) - set(a.READ_ACTIONS):
        with pytest.raises(ValueError, match='expired'):
            check(env, plan, run, action)
    assert image_tree(study) == before
    updated = change(env, run)
    assert updated['state']['objects']['water']['attempt'] == 'synthetic-001'
    clock[0] = 4600
    for action in a.READ_ACTIONS:
        with pytest.raises(ValueError, match='60 minute'):
            check(env, plan, run, action)


def test_observe_only_expired_plan_takeover_preserves_round_and_fences_old_token(env):
    cfg, study, clock = env
    plan, first = expiring_run(env)
    count(env, first)
    clock[0] = 6400 - 0.001
    with pytest.raises(ValueError, match='holds the lease'):
        a.start(cfg, study.name, plan['plan_id'], 'observer', observe_only=True,
                takeover_reason='Expired original wake')
    clock[0] = 6400
    with pytest.raises(ValueError, match='expired'):
        a.start(cfg, study.name, plan['plan_id'], 'ordinary', takeover_reason='Expired original wake')
    with pytest.raises(ValueError, match='takeover reason'):
        a.start(cfg, study.name, plan['plan_id'], 'observer', observe_only=True)
    observer = a.start(cfg, study.name, plan['plan_id'], 'observer', observe_only=True,
                       takeover_reason='Collect already submitted synthetic outputs')
    assert observer['token'] != first['token']
    assert observer['state']['lease']['observe_only'] is True
    assert observer['state']['runs'][observer['run_id']]['observe_only'] is True
    assert observer['state']['current_round'] == first['state']['current_round']
    assert observer['state']['rounds'][first['state']['current_round']]['totals']['attempt'] == 1
    before = image_tree(study)
    for action in a.READ_ACTIONS:
        assert check(env, plan, observer, action)['eligible_now']
    for action in a.ACTIONS:
        with pytest.raises(ValueError, match='owner'):
            check(env, plan, first, action)
    for action in set(a.ACTIONS) - set(a.READ_ACTIONS):
        with pytest.raises(ValueError, match='Observe-only'):
            check(env, plan, observer, action)
    for kind in a.COUNTERS:
        with pytest.raises(ValueError, match='Observe-only'):
            count(env, observer, 'observer-' + kind, kind=kind)
    with pytest.raises(ValueError, match='Observe-only'):
        change(env, observer, 'resume', reason='Cannot turn observation into submission')
    assert image_tree(study) == before
    change(env, observer, 'finish', reason='Observation complete')
    with pytest.raises(ValueError, match='owner'):
        check(env, plan, observer, 'fetch')
    next_observer = a.start(cfg, study.name, plan['plan_id'], 'next-observer', observe_only=True)
    change(env, next_observer, 'end', reason='Explicitly end the synthetic round')
    with pytest.raises(ValueError, match='ended'):
        a.start(cfg, study.name, plan['plan_id'], 'after-end', observe_only=True)


@pytest.mark.parametrize('action', a.READ_ACTIONS)
def test_observe_only_keeps_60_minute_limit(env, action):
    cfg, study, clock = env
    plan, original = expiring_run(env)
    change(env, original, 'finish', reason='End ordinary wake')
    clock[0] = 1100
    observer = a.start(cfg, study.name, plan['plan_id'], 'observer', observe_only=True)
    clock[0] = 4699.999
    assert check(env, plan, observer, action)['eligible_now']
    clock[0] = 4700
    with pytest.raises(ValueError, match='60 minute'):
        check(env, plan, observer, action)


def test_observe_only_cannot_switch_plans_or_create_a_round(env):
    cfg, study, _ = env
    plan = ready(env)
    other = a.create_plan(cfg, study.name, spec(goal='Different synthetic plan'))
    # Even a confirmed alternative may not be adopted through the read path.
    for confirmed in (False, True):
        if confirmed:
            a.confirm(cfg, study.name, other['plan_id'], other['sha256'], 'Synthetic alternative confirmation')
        before = image_tree(study)
        with pytest.raises(ValueError, match='current round and current plan'):
            a.start(cfg, study.name, other['plan_id'], 'observer', observe_only=True)
        assert image_tree(study) == before
    observer = a.start(cfg, study.name, plan['plan_id'], 'observer', observe_only=True)
    a.pause(cfg, study.name, 'Synthetic pause')
    before = image_tree(study)
    with pytest.raises(ValueError, match='Observe-only'):
        change(env, observer, 'resume', reason='Read lease is not resume authority')
    assert image_tree(study) == before


@pytest.mark.parametrize('damage', ['versions', 'plan', 'state', 'confirmation'])
def test_observe_only_still_requires_versions_confirmation_and_integrity(env, monkeypatch, damage):
    cfg, study, clock = env
    plan, original = expiring_run(env)
    change(env, original, 'finish', reason='End ordinary wake')
    clock[0] = 1100
    observer = a.start(cfg, study.name, plan['plan_id'], 'observer', observe_only=True)
    if damage == 'versions':
        monkeypatch.setattr(a, 'versions', lambda: dict(VERSIONS, rdkit='changed'))
    elif damage == 'plan':
        (study / 'autonomy' / ('plan-' + plan['plan_id'] + '.json')).write_bytes(b'{}\n')
    elif damage == 'state':
        (study / 'autonomy/state.json').write_bytes(b'{')
    else:
        target = study / 'autonomy/state.json'
        saved = json.loads(target.read_text())
        saved['state']['plans'][plan['plan_id']]['confirmation'] = None
        target.write_bytes(disk.encode(saved))
    before = image_tree(study)
    for action in a.READ_ACTIONS:
        with pytest.raises((ValueError, OSError)):
            check(env, plan, observer, action)
    assert image_tree(study) == before


def test_observe_only_start_cli_is_local_and_does_not_enable_new_actions(env, monkeypatch, capsys):
    cfg, study, clock = env
    plan, original = expiring_run(env)
    change(env, original, 'finish', reason='End ordinary wake')
    clock[0] = 1100
    def local_config(*, local_only=False):
        assert local_only
        return cfg
    def forbidden(*args, **kwargs):
        pytest.fail('Observe-only bookkeeping must not construct transport or use network')
    monkeypatch.setattr(cli, 'load_config', local_config)
    monkeypatch.setattr(transport.SSHTransport, '__init__', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    assert cli.main(['autonomy', 'start', '--study', study.name, '--plan', plan['plan_id'],
                     '--owner', 'synthetic-observer', '--observe-only', '--json']) == 0
    observer = json.loads(capsys.readouterr().out)
    assert observer['state']['lease']['observe_only'] is True
    for action, code in [('fetch', 0), ('submit', 1)]:
        assert cli.main(['autonomy', 'check', '--study', study.name, '--run', observer['run_id'],
                         '--token', observer['token'], '--sha256', plan['sha256'],
                         '--for-action', action, '--json']) == code
        value = json.loads(capsys.readouterr().out)
        assert ('eligible_now' in value) is (code == 0)


def test_optional_structured_submission_plan_is_immutable_and_replayable(env):
    from ag.autonomy_policy import PLAN_BOUND_KEYS
    from test_autonomy_policy import rule
    cfg, study, _ = env
    a.initialize(cfg, study.name)
    bounds = {key: rule()[key] for key in PLAN_BOUND_KEYS}
    plan = a.create_plan(cfg, study.name, spec(submission_policy=bounds))
    saved = (study / 'autonomy' / f"plan-{plan['plan_id']}.json").read_bytes()
    a.confirm(cfg, study.name, plan['plan_id'], plan['sha256'], 'Synthetic bounds confirmed')
    assert a.status(cfg, study.name)['state']['plans'][plan['plan_id']]['body']['spec']['submission_policy'] == bounds
    assert (study / 'autonomy' / f"plan-{plan['plan_id']}.json").read_bytes() == saved
    bounds['routing_sha256'] = 'c' * 64
    revised = a.create_plan(cfg, study.name, spec(submission_policy=bounds))
    assert revised['sha256'] != plan['sha256']


def test_invalid_structured_plan_rejected_before_publication(env):
    cfg, study, _ = env
    a.initialize(cfg, study.name)
    before = image_tree(study)
    with pytest.raises(ValueError, match='plan submission policy'):
        a.create_plan(cfg, study.name, spec(submission_policy={}))
    assert image_tree(study) == before


def consumed_record(plan, run, attempt_id='water-001', *, failure_class=None, object_id='water',
                    max_attempts=10, rule_sha256='b' * 64):
    return dict(attempt_id=attempt_id, object_id=object_id, failure_class=failure_class,
                ownership_sha256=sha256(attempt_id.encode()).hexdigest(),
                round_id=run['state']['current_round'], run_id=run['run_id'],
                plan_sha256=plan['sha256'], rule_sha256=rule_sha256, max_attempts=max_attempts)


@pytest.mark.parametrize('scheduler', ['pbs', 'slurm'])
def test_unknown_formal_absence_is_recorded_without_resolving_or_resubmitting(
        cfg, prepared, multi, tmp_path, monkeypatch, scheduler):
    from ag import approval, config as config_module, state, status
    from test_core import Fake
    from test_slurm import SlurmFake, prepare
    if scheduler == 'slurm':
        path, manifest = prepare(multi, tmp_path)
        config = multi
        from ag.config import select_cluster
        fake = SlurmFake(select_cluster(multi, 'batch'))
    else:
        path, manifest = prepared
        config, fake = cfg, Fake(cfg)
    state.write(path, 'submitting')
    state.write(path, 'unknown')
    (path / '.submit-claim').write_text('Synthetic unchanged claim')
    # This marker requests the extra existing read operation; it grants no
    # authority. The resolution adapter separately audits immutable ownership.
    (path / 'submission-summary.json').write_text(json.dumps(
        {'authorization': {'method': 'autonomy-policy'}}))
    monkeypatch.setattr(status.time, 'time', lambda: 2000.)
    identity = ('fixture-host', 22, 'fixture')
    monkeypatch.setattr(config_module, 'ssh_identity', lambda _: identity)
    result = status.check(config, path, fake)
    assert result['state'] == 'unknown' and result['job_id'] is None
    assert result['unknown_reconciliation'] == dict(schema='ag-unknown-observation/1',
        observed_at=2000., scheduler=scheduler,
        job_name=manifest['pbs_job_name'] if scheduler == 'pbs' else manifest['attempt_id'],
        matches=[], start_absent=True,
        account_sha256=approval.digest({'scheduler': scheduler, 'ssh': list(identity)}))
    assert (path / '.submit-claim').read_text() == 'Synthetic unchanged claim'
    assert 'receipt' in fake.operations()
    assert not {'submit', 'cancel', 'create_attempt'} & set(fake.operations())


def test_manual_resolution_event_is_bound_once_and_does_not_resume_or_reset_budget(env):
    plan, run = running(env)
    cfg, root, clock = env
    record = consumed_record(plan, run)
    consume(env, plan, run, record)
    a.pause(cfg, root.name, 'UNKNOWN requires human review')
    with disk.locked(cfg, root.name) as store:
        snapshot, _ = a.load(store)
    fields = dict(attempt_id=record['attempt_id'], object_id='water',
        ownership_sha256=record['ownership_sha256'], status_sha256='c' * 64,
        evidence_sha256='d' * 64, kind='unknown', quote='Explicit synthetic human resolution')
    after = a.apply(snapshot['state'], dict(op='manual_resolution', at=clock[0], data=fields))
    assert after['paused'] and after['phase'] == 'paused'
    assert after['submissions'] == snapshot['state']['submissions']
    assert after['manual_resolutions'][record['attempt_id']] == dict(fields, at=clock[0])
    with pytest.raises(ValueError, match='already|Duplicate'):
        a.apply(after, dict(op='manual_resolution', at=clock[0], data=fields))
    for key, value in [('ownership_sha256', 'e' * 64), ('object_id', 'other'), ('quote', '')]:
        with pytest.raises(ValueError):
            a.apply(snapshot['state'], dict(op='manual_resolution', at=clock[0],
                data=dict(fields, **{key: value})))


def test_unknown_observation_cannot_overwrite_a_newer_cancel(cfg, prepared):
    from ag import state, status
    from test_core import Fake, seed_submission
    path, manifest = prepared
    state.write(path, 'submitting')
    seed_submission(path)
    fake = Fake(cfg)
    original = fake.run
    def run(command):
        result = original(command)
        if command.operation == 'output_observation':
            state.write(path, 'cancelled', note='Newer explicit manual cancellation')
        return result
    fake.run = run
    with pytest.raises(ValueError, match='changed during observation'):
        status.check(cfg, path, fake)
    assert state.read(path)['state'] == 'cancelled'


def test_slurm_absent_reply_cannot_overwrite_a_newer_cancel(multi, tmp_path, monkeypatch):
    from ag import state, status
    from ag.transport import Result
    from test_slurm import submitted
    path, manifest, fake = submitted(multi, tmp_path, monkeypatch)
    fake.accounting = Result()
    original = fake.run
    def run(command):
        result = original(command)
        if command.operation == 'slurm_accounting':
            state.write(path, 'cancelled', note='Newer explicit manual cancellation')
        return result
    fake.run = run
    with pytest.raises(ValueError, match='changed during observation'):
        status.check(multi, path, fake)
    assert state.read(path)['state'] == 'cancelled'


@pytest.mark.parametrize('later', ['failed-query', 'start-present', 'ambiguous'])
def test_new_unknown_observation_invalidates_previous_absence(cfg, prepared, monkeypatch, later):
    from ag import config, state, status
    from ag.transport import Result, TransportError
    from test_core import Fake, job_text
    monkeypatch.setattr(config, 'ssh_identity', lambda _: ('fixture', 22, 'fixture'))
    path, manifest = prepared
    state.write(path, 'submitting')
    state.write(path, 'unknown')
    (path / 'submission-summary.json').write_text(json.dumps(
        {'authorization': {'method': 'autonomy-policy'}}))
    fake = Fake(cfg)
    assert status.check(cfg, path, fake)['unknown_reconciliation']['start_absent']
    if later == 'failed-query':
        fake.fail = 'jobs'
        with pytest.raises(TransportError):
            status.check(cfg, path, fake)
    else:
        original = fake.run
        if later == 'start-present':
            def run(command):
                if command.operation == 'receipt':
                    return Result(stdout='{"PBS_JOBID":"123.fixture","started_at":"2026-10-30T00:00:00Z"}')
                return original(command)
            fake.run = run
            # This fixture only requests absence collection; it has neither a
            # real claim nor immutable authorization for receipt recovery.
            with pytest.raises((ValueError, OSError)):
                status.check(cfg, path, fake)
        else:
            fake.qstat = Result(stdout=job_text(manifest) + job_text(manifest).replace('123.fixture', '124.fixture'))
            assert status.check(cfg, path, fake)['state'] == 'unknown'
    assert state.read(path)['unknown_reconciliation'] is None


def test_manual_resolution_cli_requires_verbatim_quote():
    import argparse
    parser = argparse.ArgumentParser()
    a.register(parser.add_subparsers(dest='command', required=True))
    args = parser.parse_args(['autonomy', 'resolve-attempt', '--study', 'water',
        '--attempt', 'water-001', '--quote', 'Explicit synthetic human decision'])
    assert args.action == 'resolve-attempt' and args.quote == 'Explicit synthetic human decision'
    with pytest.raises(SystemExit):
        parser.parse_args(['autonomy', 'resolve-attempt', '--study', 'water', '--attempt', 'water-001'])


def test_observation_baseline_is_original_read_not_a_later_read(cfg, prepared, monkeypatch):
    from ag import state, status
    from test_core import Fake, seed_submission
    path, _ = prepared
    state.write(path, 'submitting')
    seed_submission(path)
    original = status._publication_scope
    def scope(target, current, publication):
        state.write(target, 'cancelled', note='Cancellation between initial read and scope')
        return original(target, current, publication)
    monkeypatch.setattr(status, '_publication_scope', scope)
    with pytest.raises(ValueError, match='changed during observation'):
        status.check(cfg, path, Fake(cfg))
    assert state.read(path)['state'] == 'cancelled'


def test_existing_slurm_cancelled_without_accounting_stays_cancelled(multi, tmp_path, monkeypatch):
    from ag import state, status
    from ag.transport import Result
    from test_slurm import submitted
    path, _, fake = submitted(multi, tmp_path, monkeypatch)
    state.write(path, 'cancelled', note='Explicit prior manual cancellation')
    fake.accounting = Result()
    assert status.check(multi, path, fake)['state'] == 'cancelled'


@pytest.mark.parametrize('failure', ['slurm_find', 'receipt'])
def test_slurm_unknown_failed_observation_clears_prior_negative(multi, tmp_path, monkeypatch, failure):
    from ag import config, state, status
    from ag.config import select_cluster
    from ag.transport import TransportError
    from test_slurm import SlurmFake, prepare
    monkeypatch.setattr(config, 'ssh_identity', lambda _: ('fixture', 22, 'fixture'))
    path, _ = prepare(multi, tmp_path)
    state.write(path, 'submitting')
    state.write(path, 'unknown')
    (path / 'submission-summary.json').write_text(json.dumps(
        {'authorization': {'method': 'autonomy-policy'}}))
    fake = SlurmFake(select_cluster(multi, 'batch'))
    assert status.check(multi, path, fake)['unknown_reconciliation']['start_absent']
    original = fake.run
    def run(command):
        if command.operation == failure:
            raise TransportError('Synthetic failed formal observation')
        return original(command)
    fake.run = run
    with pytest.raises(TransportError):
        status.check(multi, path, fake)
    assert state.read(path)['state'] == 'unknown'
    assert state.read(path)['unknown_reconciliation'] is None


def test_unknown_observation_account_change_during_query_is_not_absence(cfg, prepared, monkeypatch):
    from ag import config, state, status
    from test_core import Fake
    path, _ = prepared
    state.write(path, 'submitting')
    state.write(path, 'unknown')
    (path / 'submission-summary.json').write_text(json.dumps(
        {'authorization': {'method': 'autonomy-policy'}}))
    identity = [('original-fixture', 22, 'fixture')]
    monkeypatch.setattr(config, 'ssh_identity', lambda _: identity[0])
    fake = Fake(cfg)
    original = fake.run
    def run(command):
        result = original(command)
        if command.operation == 'receipt':
            identity[0] = ('changed-fixture', 22, 'fixture')
        return result
    fake.run = run
    with pytest.raises(ValueError, match='account changed during query'):
        status.check(cfg, path, fake)
    assert state.read(path)['state'] == 'unknown'
    assert state.read(path)['unknown_reconciliation'] is None


def consume(env, plan, run, record):
    from ag.autonomy_submission import machine_lock
    cfg, study, _ = env
    with machine_lock(), a.submission_guard(cfg, study.name, run['run_id'], run['token'],
                                           plan_sha256=plan['sha256']) as guard:
        return guard.consume(record)


def test_actual_prepare_guard_does_not_spend_legacy_intent_budget(env):
    from ag.autonomy_submission import machine_lock
    cfg, study, _ = env
    plan, run = running(env)
    for number in range(10):
        count(env, run, 'intent-' + str(number))
    current = a.status(cfg, study.name)['state']
    assert current.get('submissions', {}) == {}
    assert current['rounds'][current['current_round']]['totals']['attempt'] == 10
    before = image_tree(study)
    with machine_lock(), a.submission_guard(cfg, study.name, run['run_id'], run['token'],
                                           plan_sha256=plan['sha256']) as guard:
        assert guard.check_current('prepare')['paused'] is False
    assert image_tree(study) == before
    with pytest.raises(ValueError, match='Local Attempt intent limit'):
        count(env, run, 'eleventh-intent')
    assert image_tree(study) == before


def test_actual_prepare_with_full_intent_count_keeps_submission_budget(env, t186_driver_factory):
    from ag import attempt, submit
    from test_core import Fake
    cfg, path, manifest, context, _, _ = t186_driver_factory('full-intent-count')
    for number in range(10):
        a.change(cfg, 'smoke', 'count', context['run_id'], context['token'],
            kind='attempt', request_id='intent-' + str(number), object_id='water',
            failure_class='none', evidence='Synthetic unexecuted intent')
    current = a.status(cfg, 'smoke')['state']
    assert current.get('submissions', {}) == {} and not current['paused']
    source = Path(cfg['local']['studies_root']).parent / 'water.gjf'
    child = attempt.prepare(cfg, study_name='smoke', template='gaussian', input_path=source,
        tier='simple', walltime='00:30:00', label='actual-preparation',
        method_basis='Synthetic fixture', autonomous=context)
    assert child['attempt_id'] != path.name
    assert a.status(cfg, 'smoke')['state'].get('submissions', {}) == {}
    result = submit.submit(cfg, [child['attempt_id']], Fake(cfg), autonomous=context)
    assert result[0]['state'] == 'submitted'
    current = a.status(cfg, 'smoke')['state']
    assert set(current['submissions']) == {child['attempt_id']}
    assert current['rounds'][current['current_round']]['totals']['attempt'] == 10


def test_actual_prepare_still_rejects_consumed_submission_budget(env, t186_driver_factory):
    from ag import attempt, submit
    from test_core import Fake
    cfg, path, _, context, _, policy = t186_driver_factory('spent-submission-budget')
    policy['max_attempts'] = 1
    fake = Fake(cfg)
    with pytest.raises(ValueError, match='paused'):
        submit.submit(cfg, [path.name], fake, autonomous=context)
    current = a.status(cfg, 'smoke')['state']
    assert current['totals']['attempt'] == 0 and len(current['submissions']) == 1
    assert current['submissions'][path.name]['aborted_before_dispatch'] is not None
    assert 'submit' not in fake.operations()
    a.change(cfg, 'smoke', 'resume', context['run_id'], context['token'],
             reason='Synthetic explicit resume without restoring the consumed budget')
    before = sorted(path.parent.iterdir())
    source = Path(cfg['local']['studies_root']).parent / 'water.gjf'
    with pytest.raises(ValueError, match='Round Attempt budget reached 90%'):
        attempt.prepare(cfg, study_name='smoke', template='gaussian', input_path=source,
            tier='simple', walltime='00:30:00', label='over-budget',
            method_basis='Synthetic fixture', autonomous=context)
    assert sorted(path.parent.iterdir()) == before
    current = a.status(cfg, 'smoke')['state']
    assert current['paused'] and len(current['submissions']) == 1
    assert current['totals']['attempt'] == 0


@pytest.mark.parametrize('action', ['submit', 'prepare'])
def test_submission_guard_rechecks_after_local_validation(env, action):
    from ag.autonomy_submission import machine_lock
    cfg, study, clock = env
    plan, run = running(env)
    before = image_tree(study)
    with machine_lock(), a.submission_guard(cfg, study.name, run['run_id'], run['token'],
                                           plan_sha256=plan['sha256']) as guard:
        current = guard.check_current(action=action)
        current['paused'] = True
        assert guard.snapshot['paused'] is False
        clock[0] = run['state']['lease']['run_until']
        with pytest.raises(ValueError, match='60 minute limit'):
            guard.check_current(action=action)
    assert image_tree(study) == before
    with pytest.raises(ValueError, match='closed'):
        guard.check_current(action=action)


@pytest.mark.parametrize('stage', ['create-directory', 'upload'])
def test_driver_local_boundary_validation_cannot_outlive_run(env, t186_driver_factory, monkeypatch, stage):
    from datetime import datetime, timezone
    from ag import autonomy_policy, submit
    from test_core import Fake
    cfg, path, manifest, context, clock, _ = t186_driver_factory('boundary-expiry')
    deadline = a.status(cfg, 'smoke')['state']['lease']['run_until']
    actual_boundary = submit.AutonomousSubmission.boundary
    actual_budget_check = autonomy_policy.check_budget
    current_stage, delayed = [None], []

    def boundary(driver, selected_stage):
        current_stage[0] = selected_stage
        if selected_stage == stage:
            clock[0] = deadline - 1
            monitor_path = Path(cfg['local']['studies_root']) / '.ag-monitor/latest.json'
            monitor = json.loads(monitor_path.read_text())
            monitor['sampled_at'] = datetime.fromtimestamp(clock[0], timezone.utc).isoformat()
            monitor_path.write_text(json.dumps(monitor))
        return actual_boundary(driver, selected_stage)

    def slow_local_check(*args, **kwargs):
        result = actual_budget_check(*args, **kwargs)
        if current_stage[0] == stage:
            assert clock[0] == deadline - 1
            clock[0] += 2
            delayed.append(stage)
        return result

    monkeypatch.setattr(submit.AutonomousSubmission, 'boundary', boundary)
    monkeypatch.setattr(autonomy_policy, 'check_budget', slow_local_check)
    fake = Fake(cfg)
    with pytest.raises(ValueError, match='60 minute limit'):
        submit.submit(cfg, [path.name], fake, autonomous=context)
    assert delayed == [stage]
    assert 'upload' not in fake.operations() and 'submit' not in fake.operations()
    assert fake.operations().count('create_attempt') == (stage == 'upload')
    saved = a.status(cfg, 'smoke')['state']['submissions'][path.name]
    assert saved['dispatch_started'] is None and saved['aborted_before_dispatch'] is not None


def test_submission_consume_is_separate_from_intents_and_never_reusable(env):
    cfg, study, _ = env
    plan, run = running(env)
    count(env, run)
    assert 'submissions' not in a.status(cfg, study.name)['state']
    record = consumed_record(plan, run)
    result = consume(env, plan, run, record)
    saved = result['state']['submissions'][record['attempt_id']]
    assert all(saved[key] == value for key, value in record.items())
    assert saved['dispatch_started'] is saved['aborted_before_dispatch'] is None
    assert result['state']['totals']['attempt'] == 1
    assert len(result['state']['submissions']) == 1
    assert 'owner_token_sha256' not in a.status(cfg, study.name)['state']['submissions'][record['attempt_id']]
    before = image_tree(study)
    with pytest.raises(ValueError, match='already consumed'):
        consume(env, plan, run, record)
    assert image_tree(study) == before


@pytest.mark.parametrize('field,value', [
    ('attempt_id', '../escape'), ('object_id', ''), ('failure_class', ' scf'),
    ('failure_class', ''), ('ownership_sha256', 'bad'), ('rule_sha256', 'bad'),
    ('round_id', 'old-round'), ('run_id', 'old-run'), ('plan_sha256', 'c' * 64),
    ('max_attempts', True), ('max_attempts', 0), ('max_attempts', 11)])
def test_submission_consumption_rejects_mismatched_record(env, field, value):
    cfg, study, _ = env
    plan, run = running(env)
    record = consumed_record(plan, run)
    record[field] = value
    before = image_tree(study)
    with pytest.raises(ValueError):
        consume(env, plan, run, record)
    assert image_tree(study) == before
    assert 'submissions' not in a.status(cfg, study.name)['state']


def test_actual_remedy_limit_survives_new_wake_rule_and_plan_revision(env):
    cfg, study, _ = env
    plan, first = running(env)
    consume(env, plan, first, consumed_record(plan, first, 'water-001', failure_class='scf'))
    change(env, first, 'finish', reason='End first wake')
    second = a.start(cfg, study.name, plan['plan_id'], 'second')
    consume(env, plan, second, consumed_record(plan, second, 'water-002', failure_class='scf', rule_sha256='c' * 64))
    change(env, second, 'finish', reason='End second wake')
    revised = a.create_plan(cfg, study.name, spec(goal='Revised synthetic plan'))
    a.confirm(cfg, study.name, revised['plan_id'], revised['sha256'], 'Explicit synthetic revision')
    third = a.start(cfg, study.name, revised['plan_id'], 'third')
    before = image_tree(study)
    with pytest.raises(ValueError, match='two remedies'):
        consume(env, revised, third, consumed_record(revised, third, 'water-003', failure_class='scf'))
    assert image_tree(study) == before
    assert len(a.status(cfg, study.name)['state']['submissions']) == 2
    consume(env, revised, third, consumed_record(revised, third, 'water-004', failure_class='opt'))
    consume(env, revised, third, consumed_record(revised, third, 'water-005', failure_class='scf', object_id='other'))
    change(env, third, 'end', reason='Explicit round end')
    a.begin(cfg, study.name, revised['plan_id'], 'Explicit new round budget')
    fourth = a.start(cfg, study.name, revised['plan_id'], 'fourth')
    consume(env, revised, fourth, consumed_record(revised, fourth, 'water-006', failure_class='scf'))
    result = a.status(cfg, study.name)['state']['submissions']
    assert len(result) == 5
    assert sum(row['round_id'] == fourth['state']['current_round'] for row in result.values()) == 1


def test_90_percent_pauses_with_consumption_and_current_member_cannot_dispatch(env):
    from ag.autonomy_submission import machine_lock
    cfg, study, _ = env
    plan, run = running(env)
    for number in range(1, 9):
        consume(env, plan, run, consumed_record(plan, run, f'water-{number:03d}'))
    with machine_lock(), a.submission_guard(cfg, study.name, run['run_id'], run['token'],
                                           plan_sha256=plan['sha256']) as guard:
        guard.consume(consumed_record(plan, run, 'water-009'))
        assert guard.snapshot['paused']
        assert guard.snapshot['submission_pause']['attempt_id'] == 'water-009'
        with pytest.raises(ValueError, match='paused'):
            guard.dispatch_started('water-009')
        guard.abort_before_dispatch('water-009', 'Reached 90 percent before dispatch')
        saved = guard.snapshot['submissions']['water-009']
        assert saved['dispatch_started'] is None
        assert saved['aborted_before_dispatch']['reason'] == 'Reached 90 percent before dispatch'
    result = a.status(cfg, study.name)['state']
    assert len(result['submissions']) == 9
    assert result['totals']['attempt'] == 0
    # An explicit resume cannot erase the already consumed quota.
    change(env, run, 'resume', reason='Synthetic resume without new budget')
    with pytest.raises(ValueError, match='90%'):
        consume(env, plan, run, consumed_record(plan, run, 'water-010'))
    assert a.status(cfg, study.name)['state']['paused']
    assert len(a.status(cfg, study.name)['state']['submissions']) == 9


def test_submission_guard_snapshot_is_detached_and_guard_is_not_a_permit(env):
    from ag.autonomy_submission import machine_lock
    cfg, study, _ = env
    plan, run = running(env)
    with machine_lock(), a.submission_guard(cfg, study.name, run['run_id'], run['token'],
                                           plan_sha256=plan['sha256']) as guard:
        copy = guard.snapshot
        copy['paused'] = True
        assert guard.snapshot['paused'] is False
    before = image_tree(study)
    with pytest.raises(ValueError, match='closed'):
        guard.consume(consumed_record(plan, run))
    assert image_tree(study) == before


@pytest.mark.parametrize('change_kind', ['plan_expiry', 'versions', 'lost_owner'])
def test_submission_guard_rechecks_changed_boundary(env, monkeypatch, change_kind):
    from ag.autonomy_submission import machine_lock
    cfg, study, clock = env
    plan, run = expiring_run(env)
    record = consumed_record(plan, run)
    with machine_lock(), a.submission_guard(cfg, study.name, run['run_id'], run['token'],
                                           plan_sha256=plan['sha256']) as guard:
        if change_kind == 'plan_expiry':
            clock[0] = 1100
        elif change_kind == 'versions':
            monkeypatch.setattr(a, 'versions', lambda: dict(VERSIONS, rdkit='changed'))
        else:
            clock[0] = 4600
        with pytest.raises(ValueError):
            guard.consume(record)
    current = a.status(cfg, study.name)['state']
    assert 'submissions' not in current
    assert current['paused'] == (change_kind != 'lost_owner')


def test_waiting_requires_actual_event_and_is_once_per_object_wake(env):
    from ag.autonomy_submission import machine_lock
    cfg, study, _ = env
    plan, first = running(env)
    count(env, first)
    assert 'waiting' not in a.status(cfg, study.name)['state']
    with machine_lock(), a.submission_guard(cfg, study.name, first['run_id'], first['token'],
                                           plan_sha256=plan['sha256']) as guard:
        guard.waiting('water', 'd' * 64)
        assert guard.snapshot['waiting'] == [dict(object_id='water', record_sha256='d' * 64,
            round_id=first['state']['current_round'], run_id=first['run_id'], plan_id=plan['plan_id'],
            plan_sha256=plan['sha256'], at=1000.0)]
        with pytest.raises(ValueError, match='already has a waiting'):
            guard.waiting('water', 'e' * 64)
    change(env, first, 'finish', reason='Wait until next wake')
    second = a.start(cfg, study.name, plan['plan_id'], 'second')
    with machine_lock(), a.submission_guard(cfg, study.name, second['run_id'], second['token'],
                                           plan_sha256=plan['sha256']) as guard:
        guard.waiting('water', 'e' * 64)
    assert len(a.status(cfg, study.name)['state']['waiting']) == 2


@pytest.mark.parametrize('dispatched', [False, True])
def test_boundary_failure_after_lost_lease_requires_original_owner_and_never_releases_dispatch(env, dispatched):
    from ag.autonomy_submission import machine_lock
    cfg, study, clock = env
    plan, first = running(env)
    record = consumed_record(plan, first)
    with machine_lock(), a.submission_guard(cfg, study.name, first['run_id'], first['token'],
                                           plan_sha256=plan['sha256']) as guard:
        guard.consume(record)
        if dispatched:
            guard.dispatch_started(record['attempt_id'])
            with pytest.raises(ValueError, match='already recorded'):
                guard.abort_before_dispatch(record['attempt_id'], 'Cannot release dispatched request')
    clock[0] = 6400
    second = a.start(cfg, study.name, plan['plan_id'], 'second', takeover_reason='First lease expired')
    with machine_lock():
        before = image_tree(study)
        with pytest.raises(ValueError, match='original reservation owner'):
            a.boundary_failure(cfg, study.name, record['attempt_id'], record['ownership_sha256'],
                run_id=second['run_id'], token=second['token'], dispatched=dispatched, reason='Another session')
        with pytest.raises(ValueError, match='durable dispatch'):
            a.boundary_failure(cfg, study.name, record['attempt_id'], record['ownership_sha256'],
                run_id=first['run_id'], token=first['token'], dispatched=not dispatched, reason='Wrong boundary')
        assert image_tree(study) == before
        result = a.boundary_failure(cfg, study.name, record['attempt_id'], record['ownership_sha256'],
            run_id=first['run_id'], token=first['token'], dispatched=dispatched, reason='Synthetic transport failure')
        assert result['state']['paused']
        saved = result['state']['submissions'][record['attempt_id']]
        assert (saved['aborted_before_dispatch'] is None) == dispatched
        assert (saved['dispatch_started'] is not None) == dispatched
        before = image_tree(study)
        a.boundary_failure(cfg, study.name, record['attempt_id'], record['ownership_sha256'],
            run_id=first['run_id'], token=first['token'], dispatched=dispatched, reason='Synthetic transport failure')
        assert image_tree(study) == before
    assert len(a.status(cfg, study.name)['state']['submissions']) == 1


def test_submission_crash_after_journal_retains_consumption_and_never_replays_action(env, monkeypatch):
    cfg, study, _ = env
    plan, run = running(env)
    record = consumed_record(plan, run)
    def fail_publish(self, value):
        raise OSError('Synthetic crash after durable event')
    with monkeypatch.context() as scoped:
        scoped.setattr(disk.Store, 'publish', fail_publish)
        with pytest.raises(OSError):
            consume(env, plan, run, record)
    preserved = (study / 'autonomy/journal.jsonl').read_bytes()
    with pytest.raises(ValueError, match='stale'):
        consume(env, plan, run, record)
    recovered = change(env, run, 'recover', reason='Explicit local evidence replay')
    assert record['attempt_id'] in recovered['state']['submissions']
    assert (study / 'autonomy/journal.jsonl').read_bytes().startswith(preserved)
    with pytest.raises(ValueError, match='already consumed'):
        consume(env, plan, run, record)


def test_manual_guard_requires_pause_and_no_live_lease_preserving_round(env):
    cfg, study, _ = env
    with a.manual_write_guard(cfg, study.name) as writer:
        assert not writer['manual_takeover']
        assert not (study / 'autonomy').exists()
    plan, run = running(env)
    record = consumed_record(plan, run)
    consume(env, plan, run, record)
    with pytest.raises(ValueError, match='Pause the active'):
        with a.manual_write_guard(cfg, study.name):
            pytest.fail('Running round admitted manual writes')
    change(env, run, 'finish', reason='End only the wake')
    with pytest.raises(ValueError, match='Pause the active'):
        with a.manual_write_guard(cfg, study.name):
            pytest.fail('Between-wakes round admitted manual writes')
    a.pause(cfg, study.name, 'Synthetic pause')
    before = image_tree(study)
    with a.manual_write_guard(cfg, study.name) as writer:
        assert not writer['manual_takeover']
        state = a.status(cfg, study.name)['state']
        assert state['phase'] == 'paused' and state['lease'] is None
        assert state['current_round'] == run['state']['current_round']
        assert record['attempt_id'] in state['submissions']
    assert image_tree(study) == before
    a.change(cfg, study.name, 'end', None, None, round_id=run['state']['current_round'], reason='Explicit end')
    with a.manual_write_guard(cfg, study.name):
        assert a.status(cfg, study.name)['state']['phase'] == 'ended'
    (study / 'autonomy/state.json').write_bytes(b'{')
    with pytest.raises(ValueError):
        with a.manual_write_guard(cfg, study.name):
            pytest.fail('Corrupt state admitted manual writes')


def _consume_racer(env, plan, run, attempt_id, gate, output):
    gate.wait(10)
    try:
        consume(env, plan, run, consumed_record(plan, run, attempt_id))
        output.put('consumed')
    except ValueError:
        output.put('refused')


def test_concurrent_actual_consumption_cannot_cross_90_percent(env):
    cfg, study, _ = env
    plan, run = running(env)
    for number in range(1, 9):
        consume(env, plan, run, consumed_record(plan, run, f'water-{number:03d}'))
    ctx = multiprocessing.get_context('fork')
    gate, output = ctx.Event(), ctx.Queue()
    workers = [ctx.Process(target=_consume_racer, args=(env, plan, run, f'water-{number:03d}', gate, output))
               for number in (9, 10)]
    for worker in workers:
        worker.start()
    gate.set()
    for worker in workers:
        _join(worker)
        assert worker.exitcode == 0
    assert sorted(output.get(timeout=3) for _ in workers) == ['consumed', 'refused']
    result = a.status(cfg, study.name)['state']
    assert result['paused'] and len(result['submissions']) == 9


def _begin_racer(env, plan, gate, output):
    gate.wait(10)
    cfg, study, _ = env
    try:
        a.begin(cfg, study.name, plan['plan_id'], 'Explicit round after manual write')
        output.put('began')
    except ValueError as exc:
        output.put(str(exc))


def test_begin_rejects_inflight_manual_writer_without_waiting_for_body(env):
    cfg, study, _ = env
    a.initialize(cfg, study.name)
    plan = a.create_plan(cfg, study.name, spec())
    a.confirm(cfg, study.name, plan['plan_id'], plan['sha256'], 'Synthetic confirmation')
    ctx = multiprocessing.get_context('fork')
    gate, output = ctx.Event(), ctx.Queue()
    process = ctx.Process(target=_begin_racer, args=(env, plan, gate, output))
    process.start()
    with a.manual_write_guard(cfg, study.name):
        gate.set()
        assert 'in-flight manual writer' in output.get(timeout=3)
    _join(process)
    assert process.exitcode == 0
    a.begin(cfg, study.name, plan['plan_id'], 'Explicit round after manual write')
    with pytest.raises(ValueError, match='active autonomous round'):
        with a.manual_write_guard(cfg, study.name):
            pytest.fail('Round began but manual write was admitted')


@pytest.mark.parametrize('elapsed', [0, 3600, 5399])
def test_paused_manual_writer_refuses_entire_live_lease(env, elapsed):
    cfg, study, clock = env
    _, run = running(env)
    a.pause(cfg, study.name, 'Synthetic manual pause')
    clock[0] += elapsed
    before = image_tree(study)
    with pytest.raises(ValueError, match='90 minutes'):
        with a.manual_write_guard(cfg, study.name):
            pytest.fail('Live lease admitted manual writes')
    assert image_tree(study) == before
    assert a.status(cfg, study.name)['state']['lease']['run_id'] == run['run_id']


def test_manual_takeover_after_90_minutes_is_explicit_and_keeps_consumption(env):
    cfg, study, clock = env
    plan, run = running(env)
    record = consumed_record(plan, run)
    consume(env, plan, run, record)
    a.pause(cfg, study.name, 'Synthetic manual pause')
    previous_lease = a.status(cfg, study.name)['state']['lease']
    clock[0] += 5400
    with a.manual_write_guard(cfg, study.name) as writer:
        assert writer['manual_takeover']
        state = a.status(cfg, study.name)['state']
        assert state['lease'] is None and state['paused']
        assert state['current_round'] == run['state']['current_round']
        assert record['attempt_id'] in state['submissions']
        assert state['runs'][run['run_id']]['outcome'] == 'manual-takeover'
        with pytest.raises(ValueError, match='in-flight manual writer'):
            a.start(cfg, study.name, plan['plan_id'], 'Cannot overlap manual writer')
        with pytest.raises(ValueError, match='in-flight manual writer'):
            change(env, run, 'resume', quote='Cannot overlap manual writer')
    last = disk.decode((study / 'autonomy/journal.jsonl').read_bytes().splitlines()[-1])
    assert last['op'] == 'manual_takeover'
    assert last['data']['writer_id'] == writer['writer_id']
    assert last['data']['previous_lease']['run_id'] == previous_lease['run_id']
    with pytest.raises(ValueError):
        check(env, plan, run, action='observe')
    second = a.start(cfg, study.name, plan['plan_id'], 'New observation owner')
    assert second['state']['paused'] and len(second['state']['submissions']) == 1


def test_manual_writers_allow_legacy_parallel_work_but_block_init_and_paused_peer(env):
    cfg, study, _ = env
    with a.manual_write_guard(cfg, study.name) as first:
        with a.manual_write_guard(cfg, study.name) as second:
            assert first['writer_id'] != second['writer_id']
            with pytest.raises(ValueError, match='in-flight manual writer'):
                a.initialize(cfg, study.name)
        assert not (study / 'autonomy').exists()
    _, run = running(env)
    a.pause(cfg, study.name, 'Synthetic pause')
    change(env, run, 'finish', reason='Release wake')
    with a.manual_write_guard(cfg, study.name):
        with pytest.raises(ValueError, match='already owns'):
            with a.manual_write_guard(cfg, study.name):
                pytest.fail('Two manual writers in paused active round')


def test_manual_writer_does_not_hold_machine_or_study_mutex_over_body(env):
    cfg, study, _ = env
    _, run = running(env)
    a.pause(cfg, study.name, 'Synthetic pause')
    change(env, run, 'finish', reason='Release wake')
    other = study.parent / 'other-study'
    other.mkdir()
    (other / 'attempts').mkdir()
    with a.manual_write_guard(cfg, study.name):
        assert a.status(cfg, study.name)['state']['paused']
        a.pause(cfg, study.name, 'Short study IO remains available')
        with a.manual_write_guard(cfg, other.name):
            assert not (other / 'autonomy').exists()
        a.initialize(cfg, other.name)


def _crash_manual_writer(cfg, name, action=None, attempt_ids=None):
    with a.manual_write_guard(cfg, name, action=action, attempt_ids=attempt_ids):
        os._exit(23)


def test_crashed_manual_writer_never_becomes_an_empty_registry(env):
    cfg, study, _ = env
    ctx = multiprocessing.get_context('fork')
    process = ctx.Process(target=_crash_manual_writer, args=(cfg, study.name))
    process.start()
    _join(process)
    assert process.exitcode == 23
    before = image_tree(Path.home())
    for operation in (lambda: a.initialize(cfg, study.name),
                      lambda: a.manual_write_guard(cfg, study.name).__enter__()):
        with pytest.raises(ValueError, match='no live owner'):
            operation()
    assert image_tree(Path.home()) == before
    assert not (study / 'autonomy').exists()


def test_manual_writer_completion_on_exception_and_truncated_evidence_refused(env):
    cfg, study, _ = env
    with pytest.raises(RuntimeError, match='Synthetic operation failure'):
        with a.manual_write_guard(cfg, study.name):
            raise RuntimeError('Synthetic operation failure')
    with a.manual_write_guard(cfg, study.name):
        pass
    records = Path.home() / '.config/ag/manual-writers'
    completion = next(records.rglob('*.complete.json'))
    completion.write_bytes(b'{')
    before = image_tree(Path.home())
    with pytest.raises(ValueError):
        a.initialize(cfg, study.name)
    with pytest.raises(ValueError):
        with a.manual_write_guard(cfg, study.name):
            pytest.fail('Truncated completion admitted a writer')
    assert image_tree(Path.home()) == before


def test_manual_takeover_publish_failure_keeps_claim_and_old_count(env, monkeypatch):
    cfg, study, clock = env
    plan, run = running(env)
    record = consumed_record(plan, run)
    consume(env, plan, run, record)
    a.pause(cfg, study.name, 'Synthetic pause')
    clock[0] += 5400
    with monkeypatch.context() as scoped:
        scoped.setattr(disk.Store, 'publish', lambda *args: (_ for _ in ()).throw(OSError('Synthetic publish failure')))
        with pytest.raises(OSError):
            with a.manual_write_guard(cfg, study.name):
                pytest.fail('Body ran before durable takeover')
    with pytest.raises(ValueError, match='no live owner'):
        a.start(cfg, study.name, plan['plan_id'], 'Cannot recover writer as a lease', takeover_reason='Expired')
    with disk.locked(cfg, study.name) as store:
        snapshot, stale = a.load(store, allow_stale=True)
        assert stale and len(snapshot['state']['submissions']) == 1
        assert snapshot['state']['runs'][run['run_id']]['outcome'] == 'manual-takeover'


def _manual_racer(cfg, name, gate, release, output):
    gate.wait(10)
    try:
        with a.manual_write_guard(cfg, name):
            output.put('entered')
            release.wait(10)
    except ValueError:
        output.put('refused')


@pytest.mark.parametrize('paused', [False, True])
def test_manual_writer_concurrency_is_unique_only_for_paused_active_round(env, paused):
    cfg, study, _ = env
    if paused:
        _, run = running(env)
        a.pause(cfg, study.name, 'Synthetic pause')
        change(env, run, 'finish', reason='Release wake')
    ctx = multiprocessing.get_context('fork')
    gate, release, output = ctx.Event(), ctx.Event(), ctx.Queue()
    processes = [ctx.Process(target=_manual_racer, args=(cfg, study.name, gate, release, output)) for _ in range(2)]
    for process in processes:
        process.start()
    gate.set()
    try:
        results = sorted(output.get(timeout=3) for _ in processes)
        assert results == (['entered', 'refused'] if paused else ['entered', 'entered'])
        with pytest.raises(ValueError, match='in-flight manual writer'):
            a.initialize(cfg, study.name)
    finally:
        release.set()
        for process in processes:
            _join(process)
    assert all(process.exitcode == 0 for process in processes)


@pytest.mark.parametrize('corruption', ['claim-truncated', 'completion-hash', 'registry-symlink'])
def test_manual_writer_damaged_or_linked_records_never_authorize_progression(env, corruption):
    cfg, study, _ = env
    with a.manual_write_guard(cfg, study.name):
        pass
    registry = Path.home() / '.config/ag/manual-writers'
    claim = next(registry.rglob('*.claim.json'))
    completion = next(registry.rglob('*.complete.json'))
    if corruption == 'claim-truncated':
        claim.write_bytes(b'{')
    elif corruption == 'completion-hash':
        data = disk.decode(completion.read_bytes())
        data['claim_sha256'] = 'f' * 64
        completion.write_bytes(disk.encode(data))
    else:
        saved = registry.with_name('saved-writer-evidence')
        registry.rename(saved)
        registry.symlink_to(saved, target_is_directory=True)
    before = image_tree(Path.home())
    for operation in (lambda: a.initialize(cfg, study.name),
                      lambda: a.manual_write_guard(cfg, study.name).__enter__()):
        with pytest.raises((ValueError, OSError)):
            operation()
    assert image_tree(Path.home()) == before


def test_manual_writer_diagnostic_is_readonly_and_exposes_legacy_and_action_evidence(env):
    cfg, study, _ = env
    before = image_tree(Path.home())
    assert a.manual_writers(cfg, study.name)['writers'] == []
    assert image_tree(Path.home()) == before
    assert not (Path.home() / '.config').exists()
    with a.manual_write_guard(cfg, study.name) as legacy:
        before = image_tree(Path.home())
        [row] = a.manual_writers(cfg, study.name)['writers']
        assert row['writer_id'] == legacy['writer_id'] and row['state'] == 'active'
        assert row['action'] is None and row['attempt_ids'] == []
        assert image_tree(Path.home()) == before
    with a.manual_write_guard(cfg, study.name, action='submit', attempt_ids=['water-001']) as current:
        rows = {row['writer_id']: row for row in a.manual_writers(cfg, study.name)['writers']}
        assert rows[legacy['writer_id']]['state'] == 'completed'
        assert rows[current['writer_id']]['action'] == 'submit'
        assert rows[current['writer_id']]['attempt_ids'] == ['water-001']
    claims = [disk.decode(path.read_bytes()) for path in (Path.home() / '.config/ag/manual-writers').rglob('*.claim.json')]
    assert {claim['schema'] for claim in claims} == {'ag-manual-writer/1', 'ag-manual-writer/2'}
    assert 'action' not in next(claim for claim in claims if claim['schema'].endswith('/1'))


@pytest.mark.parametrize('action,ids', [('other', []), ('submit', ['water-001', 'water-001']),
                                     ('fetch', ['../water']), ('cancel', 'water-001'), (None, [])])
def test_manual_writer_action_metadata_rejects_invalid_before_registration(env, action, ids):
    cfg, study, _ = env
    before = image_tree(Path.home())
    with pytest.raises(ValueError):
        with a.manual_write_guard(cfg, study.name, action=action, attempt_ids=ids):
            pytest.fail('Invalid manual action admitted')
    assert image_tree(Path.home()) == before


def test_release_writer_refuses_active_completed_unknown_and_missing_quote(env):
    cfg, study, _ = env
    with a.manual_write_guard(cfg, study.name, action='prepare') as writer:
        for writer_id, quote in [(writer['writer_id'], 'Synthetic release'),
                                 ('0' * 32, 'Synthetic release'), (writer['writer_id'], ' ')]:
            before = image_tree(Path.home())
            with pytest.raises(ValueError):
                a.release_writer(cfg, study.name, writer_id, quote)
            assert image_tree(Path.home()) == before
    with pytest.raises(ValueError, match='Only a stale'):
        a.release_writer(cfg, study.name, writer['writer_id'], 'Synthetic release')


def test_stale_writer_release_is_exact_append_only_and_keeps_unknown_reservation(env):
    cfg, study, _ = env
    plan, run = running(env)
    record = consumed_record(plan, run)
    consume(env, plan, run, record)
    a.pause(cfg, study.name, 'Synthetic UNKNOWN remains reserved')
    change(env, run, 'finish', reason='Release only wake lease')
    attempt = study / 'attempts' / record['attempt_id']
    attempt.mkdir()
    (attempt / '.submit-claim').write_text('Synthetic one-shot claim\n')
    (attempt / 'status.json').write_bytes(disk.encode({'state': 'unknown'}))
    ctx = multiprocessing.get_context('fork')
    process = ctx.Process(target=_crash_manual_writer, args=(cfg, study.name, 'submit', [record['attempt_id']]))
    process.start()
    _join(process)
    assert process.exitcode == 23
    [row] = a.manual_writers(cfg, study.name)['writers']
    assert row['state'] == 'stale' and row['attempt_ids'] == [record['attempt_id']]
    before_study, before_home = image_tree(study), image_tree(Path.home())
    quote = '  Synthetic owner releases only this crashed manual registration.  '
    released = a.release_writer(cfg, study.name, row['writer_id'], quote)
    assert released['claim_sha256'] == row['claim_sha256']
    assert 'UNKNOWN' in released['effect'] and 'resubmission' in released['effect']
    assert image_tree(study) == before_study
    after_home = image_tree(Path.home())
    assert {key: after_home[key] for key in before_home} == before_home
    assert len(set(after_home) - set(before_home)) == 1
    [closed] = a.manual_writers(cfg, study.name)['writers']
    assert closed['state'] == 'released' and closed['quote'] == quote
    before = image_tree(Path.home())
    with pytest.raises(ValueError, match='Only a stale'):
        a.release_writer(cfg, study.name, row['writer_id'], quote)
    assert image_tree(Path.home()) == before
    with a.manual_write_guard(cfg, study.name, action='fetch', attempt_ids=[record['attempt_id']]):
        state = a.status(cfg, study.name)['state']
        assert state['paused'] and state['lease'] is None and len(state['submissions']) == 1
    assert (attempt / '.submit-claim').exists()


def test_released_writer_cannot_late_complete_or_accept_a_conflicting_completion(env, monkeypatch):
    cfg, study, _ = env
    descriptors = []
    original_open = disk.Store.open
    def recording_open(self, name, flags, **kwargs):
        fd = original_open(self, name, flags, **kwargs)
        if name.endswith('.claim.json') and flags == os.O_RDONLY:
            descriptors.append(fd)
        return fd
    monkeypatch.setattr(disk.Store, 'open', recording_open)
    context = a.manual_write_guard(cfg, study.name, action='prepare')
    writer = context.__enter__()
    # Synthetic loss of the owner's private claim lock; no shared mutex is held.
    a.fcntl.flock(descriptors[-1], a.fcntl.LOCK_UN)
    a.release_writer(cfg, study.name, writer['writer_id'], 'Synthetic owner confirms the lost writer is stopped')
    with pytest.raises(ValueError, match='claim changed'):
        context.__exit__(None, None, None)
    registry = Path.home() / '.config/ag/manual-writers' / writer['study_key']
    assert not (registry / (writer['writer_id'] + '.complete.json')).exists()
    claim = registry / (writer['writer_id'] + '.claim.json')
    (registry / (writer['writer_id'] + '.complete.json')).write_bytes(disk.encode(dict(
        schema='ag-manual-writer-complete/1', writer_id=writer['writer_id'],
        claim_sha256=sha256(claim.read_bytes()).hexdigest(), finished_at=1000.0)))
    with pytest.raises(ValueError, match='conflicting completion'):
        a.manual_writers(cfg, study.name)
    with pytest.raises(ValueError, match='conflicting completion'):
        a.initialize(cfg, study.name)


def test_corrupt_stale_claim_cannot_be_released_or_repaired(env):
    cfg, study, _ = env
    ctx = multiprocessing.get_context('fork')
    process = ctx.Process(target=_crash_manual_writer, args=(cfg, study.name))
    process.start()
    _join(process)
    [row] = a.manual_writers(cfg, study.name)['writers']
    claim = next((Path.home() / '.config/ag/manual-writers').rglob('*.claim.json'))
    claim.write_bytes(b'{')
    before = image_tree(Path.home())
    with pytest.raises(ValueError):
        a.release_writer(cfg, study.name, row['writer_id'], 'Synthetic release cannot repair damaged identity')
    assert image_tree(Path.home()) == before


def test_writer_diagnostic_and_release_cli_are_local_only(env, monkeypatch, capsys):
    cfg, study, _ = env
    monkeypatch.setattr(cli, 'load_config', lambda *, local_only=False: cfg if local_only else pytest.fail('Remote config'))
    monkeypatch.setattr(transport.SSHTransport, '__init__', lambda *args, **kwargs: pytest.fail('No transport'))
    assert cli.main(['autonomy', 'manual-writers', '--study', study.name]) == 0
    assert json.loads(capsys.readouterr().out)['writers'] == []
    ctx = multiprocessing.get_context('fork')
    process = ctx.Process(target=_crash_manual_writer, args=(cfg, study.name, 'fetch', ['water-001']))
    process.start()
    _join(process)
    assert cli.main(['autonomy', 'manual-writers', '--study', study.name]) == 0
    [row] = json.loads(capsys.readouterr().out)['writers']
    assert row['state'] == 'stale' and row['action'] == 'fetch'
    assert cli.main(['autonomy', 'release-writer', '--study', study.name, '--writer-id', row['writer_id'],
                     '--quote', 'Synthetic exact writer release']) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['state'] == 'released' and result['writer_id'] == row['writer_id']
    assert 'Does not resume' in result['effect']


@pytest.mark.parametrize('corruption', ['truncated', 'wrong-hash'])
def test_release_evidence_damage_does_not_restore_writer_eligibility(env, corruption):
    cfg, study, _ = env
    ctx = multiprocessing.get_context('fork')
    process = ctx.Process(target=_crash_manual_writer, args=(cfg, study.name))
    process.start()
    _join(process)
    [row] = a.manual_writers(cfg, study.name)['writers']
    a.release_writer(cfg, study.name, row['writer_id'], 'Synthetic release')
    path = next((Path.home() / '.config/ag/manual-writers').rglob('*.release.json'))
    if corruption == 'truncated':
        path.write_bytes(b'{')
    else:
        value = disk.decode(path.read_bytes())
        value['claim_sha256'] = 'f' * 64
        path.write_bytes(disk.encode(value))
    before = image_tree(Path.home())
    with pytest.raises(ValueError):
        a.initialize(cfg, study.name)
    with pytest.raises(ValueError):
        with a.manual_write_guard(cfg, study.name):
            pytest.fail('Damaged release admitted a new writer')
    assert image_tree(Path.home()) == before


@pytest.mark.parametrize('action', a.READ_ACTIONS)
def test_observation_publication_allows_expired_plan_with_current_owner_only(env, action):
    cfg, study, clock = env
    a.initialize(cfg, study.name)
    plan = a.create_plan(cfg, study.name, spec(valid_until=1001))
    a.confirm(cfg, study.name, plan['plan_id'], plan['sha256'], 'Synthetic confirmation')
    a.begin(cfg, study.name, plan['plan_id'], 'Synthetic round')
    run = a.start(cfg, study.name, plan['plan_id'], 'Synthetic observer')
    a.pause(cfg, study.name, 'Keep observing existing work')
    clock[0] = 1002
    with a.observation_publication_guard(cfg, study.name, run['run_id'], run['token'],
                                        action=action, plan_sha256=plan['sha256']) as verified:
        assert verified['current_round'] == run['state']['current_round']
        assert verified['paused'] and 'state' not in verified
        verified['paused'] = False
    assert a.status(cfg, study.name)['state']['paused']


def test_observation_publication_distinguishes_qualification_from_body_errors(env, monkeypatch):
    cfg, study, clock = env
    plan, run = running(env)
    def factory(**changes):
        options = dict(action='observe', plan_sha256=plan['sha256'])
        options.update(changes)
        return a.observation_publication_guard(cfg, study.name, run['run_id'], run['token'], **options)
    for options in ({'action': 'submit'}, {'plan_sha256': 'f' * 64}):
        with pytest.raises(a.PublicationRefused):
            with factory(**options):
                pytest.fail('Unqualified observation published')
    for exception in (OSError('Synthetic disk failure'), ValueError('Synthetic body validation')):
        with pytest.raises(type(exception)) as captured:
            with factory():
                raise exception
        assert captured.value is exception and not isinstance(captured.value, a.PublicationRefused)
    with monkeypatch.context() as scoped:
        scoped.setattr(a, 'versions', lambda: dict(VERSIONS, git_commit='b' * 40))
        with pytest.raises(a.PublicationRefused, match='versions'):
            with factory():
                pytest.fail('Changed runtime published')
    clock[0] += 3600
    with pytest.raises(a.PublicationRefused, match='60 minute'):
        with factory():
            pytest.fail('Expired wake published')


def _publication_context(env, cfg, path):
    context = (cfg, path.parent.parent, env[2])
    plan, run = running(context)
    def factory():
        return a.observation_publication_guard(cfg, path.parent.parent.name, run['run_id'], run['token'],
                                              action='observe', plan_sha256=plan['sha256'])
    return context, plan, run, factory


def _late_observation(context, plan, change_owner):
    cfg, study, clock = context
    # Reading the study here proves remote IO does not hold its mutex.
    a.status(cfg, study.name)
    clock[0] += 5400 if change_owner else 3600
    if change_owner:
        a.start(cfg, study.name, plan['plan_id'], 'New observation owner', takeover_reason='Synthetic lease expiry')


@pytest.mark.parametrize('change_owner', [False, True])
def test_status_late_remote_reply_cannot_publish_status_or_journal(env, cfg, prepared, change_owner):
    from ag import state, status
    from test_core import Fake, seed_submission
    path, _ = prepared
    state.write(path, 'submitting')
    seed_submission(path)
    context, plan, _, publication = _publication_context(env, cfg, path)
    class LateFake(Fake):
        def record_to(self, paths):
            assert paths == []
        def run(self, command):
            result = super().run(command)
            if command.operation == 'output_observation':
                _late_observation(context, plan, change_owner)
            return result
    before = image_tree(path)
    journal = path.parent.parent / 'journal.jsonl'
    before_journal = journal.read_bytes()
    with pytest.raises(a.PublicationRefused):
        status.check(cfg, path, LateFake(cfg), publication=publication)
    assert image_tree(path) == before and journal.read_bytes() == before_journal


@pytest.mark.parametrize('change_owner', [False, True])
def test_unknown_recovery_late_reply_cannot_bind_submission(env, cfg, prepared, change_owner):
    from ag import state, status
    from test_core import Fake
    path, manifest = prepared
    state.write(path, 'submitting')
    context, plan, _, publication = _publication_context(env, cfg, path)
    class LateFake(Fake):
        def run(self, command):
            if command.operation == 'jobs':
                _late_observation(context, plan, change_owner)
                return transport.Result(stdout=(f"Job Id: 123.fixture\n    Job_Name = {manifest['pbs_job_name']}\n"
                    '    Job_Owner = fixture\n    job_state = Q\n    Resource_List.nodes = 1:ppn=8\n'))
            return super().run(command)
    before = image_tree(path)
    with pytest.raises(a.PublicationRefused):
        status.check(cfg, path, LateFake(cfg), publication=publication)
    assert image_tree(path) == before and not (path / 'submission.json').exists()


def test_unknown_recovery_passes_guard_state_to_binding_and_defers_writes(env, cfg, prepared, monkeypatch):
    from ag import state, status, submission
    from test_core import Fake
    path, manifest = prepared
    state.write(path, 'submitting')
    context, _, run, publication = _publication_context(env, cfg, path)
    before_status = (path / 'status.json').read_bytes()
    class ObservingFake(Fake):
        def run(self, command):
            assert (path / 'status.json').read_bytes() == before_status
            a.status(cfg, path.parent.parent.name)
            if command.operation == 'jobs':
                return transport.Result(stdout=(f"Job Id: 123.fixture\n    Job_Name = {manifest['pbs_job_name']}\n"
                    '    Job_Owner = fixture\n    job_state = Q\n    Resource_List.nodes = 1:ppn=8\n'))
            return super().run(command)
    original = submission.record
    seen = []
    def record(path, manifest, job, *, autonomy_state):
        seen.append(autonomy_state)
        return original(path, manifest, job)
    monkeypatch.setattr(submission, 'record', record)
    result = status.check(cfg, path, ObservingFake(cfg), publication=publication)
    assert result['state'] == 'submitted' and (path / 'submission.json').exists()
    assert len(seen) == 1 and seen[0]['lease']['run_id'] == run['run_id']


@pytest.mark.parametrize('change_owner', [False, True])
def test_snapshot_late_remote_reply_cannot_create_snapshot_files(env, cfg, prepared, change_owner):
    from ag import state, snapshot
    from test_core import seed_submission
    from test_snapshot import Fake
    path, _ = prepared
    state.write(path, 'submitting')
    seed_submission(path)
    context, plan, _, publication = _publication_context(env, cfg, path)
    class LateFake(Fake):
        def run(self, command):
            result = super().run(command)
            _late_observation(context, plan, change_owner)
            return result
    before = image_tree(path)
    with pytest.raises(a.PublicationRefused):
        snapshot.capture(cfg, path, LateFake(), publication=publication)
    after = image_tree(path)
    assert {name: value for name, value in after.items()
            if not name.startswith('.snapshot-stage-')} == before
    assert not (path / 'snapshots').exists()
    assert len(list(path.glob('.snapshot-stage-*'))) == 1


def test_snapshot_success_publishes_only_after_remote_read_under_factory(env, cfg, prepared):
    from ag import state, snapshot
    from test_core import seed_submission
    from test_snapshot import Fake
    path, _ = prepared
    state.write(path, 'submitting')
    seed_submission(path)
    _, _, _, publication = _publication_context(env, cfg, path)
    class ObservingFake(Fake):
        def run(self, command):
            a.status(cfg, path.parent.parent.name)
            assert not (path / 'snapshots').exists()
            return super().run(command)
    result = snapshot.capture(cfg, path, ObservingFake(), publication=publication)
    assert (path / result['snapshot'] / result['file']).exists()


@pytest.mark.parametrize('change_owner', [False, True])
@pytest.mark.parametrize('unknown', [False, True])
def test_slurm_late_active_or_unknown_reply_cannot_publish(env, multi, tmp_path, change_owner, unknown):
    from ag import config, state, status, submission
    from test_slurm import prepare, SlurmFake
    path, manifest = prepare(multi, tmp_path)
    state.write(path, 'submitting')
    if not unknown:
        submission.record(path, manifest, '123')
        state.write(path, 'submitted', job_id=submission.qualified(manifest, '123'))
    context, plan, _, publication = _publication_context(env, multi, path)
    class LateFake(SlurmFake):
        def run(self, command):
            if command.operation == 'slurm_jobs':
                if not unknown:
                    _late_observation(context, plan, change_owner)
                return transport.Result(stdout=f'123|{path.name}|fixture|RUNNING|8|00:00:10|fixture\n')
            if command.operation == 'slurm_find':
                _late_observation(context, plan, change_owner)
            return super().run(command)
    before = image_tree(path)
    journal = path.parent.parent / 'journal.jsonl'
    before_journal = journal.read_bytes()
    with pytest.raises(a.PublicationRefused):
        status.check(multi, path, LateFake(config.select_cluster(multi, 'batch')), publication=publication)
    assert image_tree(path) == before and journal.read_bytes() == before_journal


def test_validate_consumption_refuses_known_remedy_limit_without_writes(env):
    from ag.autonomy_submission import machine_lock
    cfg, directory, _ = env
    plan, run = running(env)
    for n in (1, 2):
        consume(env, plan, run, consumed_record(plan, run, f'water-{n:03d}', failure_class='scf'))
    before = image_tree(directory)
    with machine_lock(), a.submission_guard(cfg, directory.name, run['run_id'], run['token'],
                                           plan_sha256=plan['sha256']) as guard:
        with pytest.raises(ValueError, match='two remedies'):
            guard.validate_consume(consumed_record(plan, run, 'water-003', failure_class='scf'))
    assert image_tree(directory) == before


def test_rejected_stale_submission_cannot_pause_a_successor(env):
    cfg, directory, clock = env
    plan, old = running(env)
    clock[0] += a.LEASE_SECONDS
    fresh = a.start(cfg, directory.name, plan['plan_id'], 'new-owner', takeover_reason='Synthetic expiry')
    before = image_tree(directory)
    assert not a.pause_if_current_owner(cfg, directory.name, old['run_id'], old['token'], 'Old failure')
    assert image_tree(directory) == before
    assert a.check(cfg, directory.name, fresh['run_id'], fresh['token'],
                   action='submit', plan_sha256=plan['sha256'])['eligible_now']
    clock[0] += a.RUN_SECONDS
    assert a.pause_if_current_owner(cfg, directory.name, fresh['run_id'], fresh['token'], 'Run time elapsed')
    assert a.status(cfg, directory.name)['state']['paused']


def _reserved_slurm_observation(env, multi, tmp_path):
    from ag import budget, config, state, submission
    from test_slurm import prepare, SlurmFake
    path, manifest = prepare(multi, tmp_path)
    selected = config.select_cluster(multi, 'batch')
    budget.reserve(selected, manifest, budget.read(selected))
    state.write(path, 'submitting')
    submission.record(path, manifest, '123')
    state.write(path, 'submitted', job_id=submission.qualified(manifest, '123'))
    context, plan, run, publication = _publication_context(env, multi, path)
    return path, manifest, selected, SlurmFake(selected), context, plan, run, publication


@pytest.mark.parametrize('change_owner', [False, True])
def test_slurm_settlement_waiting_for_config_lock_rechecks_lease_before_any_write(
        env, multi, tmp_path, monkeypatch, change_owner):
    from contextlib import contextmanager
    from queue import Queue
    from threading import Event, Thread
    from ag import budget, locks, status
    path, _, selected, fake, context, plan, _, publication = _reserved_slurm_observation(env, multi, tmp_path)
    waiting, results, takeover_results = Event(), Queue(), Queue()
    original_lock = locks.submission_lock

    @contextmanager
    def observed_lock(cfg):
        waiting.set()
        with original_lock(cfg):
            yield

    monkeypatch.setattr(locks, 'submission_lock', observed_lock)
    def observe():
        try:
            results.put(status.check(multi, path, fake, publication=publication))
        except BaseException as exc:
            results.put(exc)
    def take_over():
        try:
            takeover_results.put(a.start(multi, path.parent.parent.name, plan['plan_id'], 'New lease owner',
                                         takeover_reason='Synthetic lease expiry while settlement waits'))
        except BaseException as exc:
            takeover_results.put(exc)

    before_attempt = image_tree(path)
    ledger_path = budget.ledger_path(selected)
    before_ledger = ledger_path.read_bytes()
    journal_path = path.parent.parent / 'journal.jsonl'
    before_journal = journal_path.read_bytes()
    worker = Thread(target=observe, daemon=True)
    successor = None
    try:
        with original_lock(selected):
            worker.start()
            assert waiting.wait(3), 'Status did not reach the config mutex'
            assert results.empty()
            context[2][0] += 5400 if change_owner else 3600
            if change_owner:
                successor = Thread(target=take_over, daemon=True)
                successor.start()
                successor.join(3)
                assert not successor.is_alive(), 'Waiting settlement held machine/study locks and blocked takeover'
                assert isinstance(takeover_results.get(timeout=1), dict)
            assert ledger_path.read_bytes() == before_ledger
            assert image_tree(path) == before_attempt
    finally:
        worker.join(5)
        if successor is not None:
            successor.join(5)
    assert not worker.is_alive(), 'Settlement failed to release its short locks'
    assert isinstance(results.get(timeout=1), a.PublicationRefused)
    assert ledger_path.read_bytes() == before_ledger
    assert image_tree(path) == before_attempt and journal_path.read_bytes() == before_journal


def test_slurm_valid_settlement_and_status_use_separate_publication_checks(env, multi, tmp_path):
    from contextlib import contextmanager
    from ag import budget, status
    path, manifest, selected, fake, _, _, _, publication = _reserved_slurm_observation(env, multi, tmp_path)
    calls = []
    @contextmanager
    def observed_publication():
        with publication() as verified:
            calls.append(verified['lease']['run_id'])
            yield verified
    result = status.check(multi, path, fake, publication=observed_publication)
    assert result['state'] == 'finished' and result['completion_source'] == 'sacct'
    row = budget.read(selected)['attempts'][path.name]
    assert row['state'] == 'settled' and row['reserved'] == 0 and row['used'] == manifest['cores'] * 60
    assert len(calls) == 2 and calls[0] == calls[1]


@pytest.mark.parametrize('change_owner', [False, True])
def test_loss_after_legal_settlement_does_not_undo_budget_or_publish_late_status(
        env, multi, tmp_path, change_owner):
    from contextlib import contextmanager
    from ag import budget, status
    path, manifest, selected, fake, context, plan, _, publication = _reserved_slurm_observation(env, multi, tmp_path)
    calls = []
    @contextmanager
    def delayed_second_publication():
        if calls:
            _late_observation(context, plan, change_owner)
        with publication() as verified:
            calls.append(verified['lease']['run_id'])
            yield verified
    before = image_tree(path)
    journal_path = path.parent.parent / 'journal.jsonl'
    before_journal = journal_path.read_bytes()
    with pytest.raises(a.PublicationRefused):
        status.check(multi, path, fake, publication=delayed_second_publication)
    row = budget.read(selected)['attempts'][path.name]
    assert row['state'] == 'settled' and row['reserved'] == 0 and row['used'] == manifest['cores'] * 60
    assert len(calls) == 1
    assert image_tree(path) == before and journal_path.read_bytes() == before_journal


@pytest.mark.parametrize('missing', ['mutex', 'directory'])
def test_observation_publication_does_not_recreate_missing_machine_registration(env, missing):
    cfg, study, _ = env
    plan, run = running(env)
    directory = Path.home() / '.config/ag'
    if missing == 'mutex':
        (directory / 'autonomy-submit.lock').unlink()
    else:
        directory.rename(directory.with_name('preserved-registration'))
    before = image_tree(Path.home())
    with pytest.raises(a.PublicationRefused):
        with a.observation_publication_guard(cfg, study.name, run['run_id'], run['token'],
                                            action='observe', plan_sha256=plan['sha256']):
            pytest.fail('Observation recreated missing machine registration')
    assert image_tree(Path.home()) == before


def _ordinary_observation_cli(cfg, path, command, monkeypatch):
    from test_core import Fake as StatusFake
    from test_snapshot import Fake as SnapshotFake
    fake = StatusFake(cfg) if command == 'status' else SnapshotFake()
    monkeypatch.setattr(cli, 'load_config', lambda: cfg)
    monkeypatch.setattr(transport, 'SSHTransport', lambda *args, **kwargs: fake)
    return fake, [command, path.name, '--json']


@pytest.mark.parametrize('command', ['status', 'snapshot'])
def test_ordinary_observation_cli_refuses_running_round_before_remote_query(
        env, cfg, prepared, monkeypatch, capsys, command):
    from ag import state
    from test_core import seed_submission
    path, _ = prepared
    state.write(path, 'submitting')
    seed_submission(path)
    _publication_context(env, cfg, path)
    fake, argv = _ordinary_observation_cli(cfg, path, command, monkeypatch)
    before = image_tree(path)
    journal_path = path.parent.parent / 'journal.jsonl'
    before_journal = journal_path.read_bytes()
    assert cli.main(argv) == 1
    assert 'Pause the active autonomous round' in json.loads(capsys.readouterr().out)['error']
    assert fake.calls == []
    assert image_tree(path) == before and journal_path.read_bytes() == before_journal


@pytest.mark.parametrize('command', ['status', 'snapshot'])
@pytest.mark.parametrize('lifecycle', ['absent', 'paused', 'ended'])
def test_ordinary_observation_cli_keeps_manual_behavior_and_excludes_new_start_during_io(
        env, cfg, prepared, monkeypatch, capsys, command, lifecycle):
    from ag import state
    from test_core import seed_submission
    path, _ = prepared
    state.write(path, 'submitting')
    seed_submission(path)
    context = (cfg, path.parent.parent, env[2])
    plan = None
    if lifecycle != 'absent':
        plan, run = running(context)
        a.pause(cfg, path.parent.parent.name, 'Synthetic manual observation pause')
        change(context, run, 'finish', reason='Release wake for manual observation')
        if lifecycle == 'ended':
            a.change(cfg, path.parent.parent.name, 'end', None, None,
                     round_id=run['state']['current_round'], reason='End synthetic round')
    fake, argv = _ordinary_observation_cli(cfg, path, command, monkeypatch)
    original_run = fake.run
    seen = []
    def observe(command_):
        # Both local status reads and registration reads complete during IO:
        # the long operation retains only its private writer claim lock.
        if lifecycle != 'absent':
            assert a.status(cfg, path.parent.parent.name)['state']['phase'] == lifecycle
        rows = [row for row in a.manual_writers(cfg, path.parent.parent.name)['writers']
                if row['state'] == 'active']
        assert len(rows) == 1 and rows[0]['action'] == command and rows[0]['attempt_ids'] == [path.name]
        seen.append(rows[0]['writer_id'])
        with pytest.raises(ValueError, match='in-flight manual writer'):
            if lifecycle == 'absent':
                a.initialize(cfg, path.parent.parent.name)
            elif lifecycle == 'ended':
                a.begin(cfg, path.parent.parent.name, plan['plan_id'], 'Cannot race manual observation')
            else:
                a.start(cfg, path.parent.parent.name, plan['plan_id'], 'Cannot race manual observation')
        return original_run(command_)
    fake.run = observe
    assert cli.main(argv) == 0
    result = json.loads(capsys.readouterr().out)
    assert seen and fake.calls
    records = {row['writer_id']: row for row in a.manual_writers(cfg, path.parent.parent.name)['writers']}
    assert records[seen[0]]['state'] == 'completed'
    if command == 'status':
        assert result[0]['attempt_id'] == path.name
    else:
        assert (path / result['snapshot'] / result['file']).is_file()
    if lifecycle == 'absent':
        assert not (path.parent.parent / 'autonomy').exists()


def test_slow_version_check_cannot_admit_publication_after_run_deadline(env, monkeypatch):
    cfg, study, clock = env
    plan, run = running(env)
    clock[0] = run['state']['lease']['run_until'] - 1
    def slow_versions():
        clock[0] += 20
        return dict(VERSIONS)
    monkeypatch.setattr(a, 'versions', slow_versions)
    before = image_tree(study)
    with pytest.raises(a.PublicationRefused, match='60 minute'):
        with a.observation_publication_guard(cfg, study.name, run['run_id'], run['token'],
                                            action='fetch', plan_sha256=plan['sha256']):
            pytest.fail('Publication used time sampled before version verification')
    assert clock[0] > run['state']['lease']['run_until'] and image_tree(study) == before


@pytest.mark.parametrize('failure', ['first-ssh-error', 'lease-expired-on-return'])
def test_cli_incomplete_fetch_keeps_single_ssh_attempt_and_observation_fence(
        env, cfg, prepared, monkeypatch, capsys, failure):
    from ag import fetch, state
    from test_core import seed_submission
    path, _ = prepared
    state.write(path, 'submitting')
    seed_submission(path)
    state.write(path, 'interrupted', note='Synthetic stopped job without full completion evidence')
    context, plan, run, _ = _publication_context(env, cfg, path)
    monkeypatch.setattr(cli, 'load_config', lambda: cfg)
    calls = []
    def local_execute(self, argv, timeout, **kwargs):
        assert isinstance(self, fetch._IncompleteSSHTransport)
        calls.append(argv)
        a.status(cfg, path.parent.parent.name)  # No state mutex spans SSH IO.
        if failure == 'first-ssh-error':
            raise transport.SSHConnectionError('Synthetic first SSH failure')
        context[2][0] += a.RUN_SECONDS
        return transport.Result(stdout='absent\n')
    monkeypatch.setattr(transport.SSHTransport, '_execute', local_execute)
    monkeypatch.setattr(transport.time, 'sleep', lambda *args: pytest.fail('Incomplete SSH failure was retried'))
    before_status = (path / 'status.json').read_bytes()
    code = cli.main(['fetch', path.name, '--incomplete', '--no-facts', '--json',
                     '--run', run['run_id'], '--token', run['token'], '--plan-sha256', plan['sha256']])
    error = json.loads(capsys.readouterr().out)['error']
    assert code == (2 if failure == 'first-ssh-error' else 1)
    assert ('Synthetic first SSH failure' if failure == 'first-ssh-error' else '60 minute') in error
    assert len(calls) == 1 and (path / 'status.json').read_bytes() == before_status
    assert not list(path.glob('fetch-incomplete-*.json')) and not (path / 'facts.json').exists()
    assert {item.name for item in (path / 'outputs').iterdir()} <= {'.partial'}


def _fetched_facts_cli_attempt(prepared):
    from ag import facts, state
    from test_core import seed_submission
    path, _ = prepared
    (path / 'outputs/water.log').write_bytes((Path(__file__).parent / 'fixtures/water_opt_freq.log').read_bytes())
    state.write(path, 'submitting')
    seed_submission(path)
    state.write(path, 'finished')
    state.write(path, 'fetched')
    facts.build_facts(path)
    return path


@pytest.mark.parametrize('mode', [[], ['--refresh'], ['--reparse']])
@pytest.mark.usefixtures("synthetic_cwd")
def test_facts_cli_refuses_running_study_before_parsing(env, cfg, prepared, monkeypatch, capsys, mode):
    from ag import facts
    path = _fetched_facts_cli_attempt(prepared)
    _publication_context(env, cfg, path)
    monkeypatch.setattr(cli, 'load_config', lambda **kwargs: pytest.fail('Facts guard must not load real config'))
    monkeypatch.setattr(facts, 'parse_facts', lambda *args: pytest.fail('Running study parsed before writer qualification'))
    before = image_tree(path.parent.parent)
    assert cli.main(['facts', path.name, '--study', str(path.parent.parent), '--json', *mode]) == 1
    assert 'Pause the active autonomous round' in capsys.readouterr().err
    assert image_tree(path.parent.parent) == before


@pytest.mark.parametrize('mode', [[], ['--refresh'], ['--reparse']])
def test_facts_cli_paused_without_lease_owns_writer_during_actual_parse(
        env, cfg, prepared, monkeypatch, capsys, mode):
    from ag import facts
    path = _fetched_facts_cli_attempt(prepared)
    context, plan, run, _ = _publication_context(env, cfg, path)
    a.pause(cfg, path.parent.parent.name, 'Synthetic facts pause')
    change(context, run, 'finish', reason='Release wake')
    monkeypatch.setattr(cli, 'load_config', lambda **kwargs: pytest.fail('Facts guard must derive only its local root'))
    original = facts.parse_facts
    seen = []
    def parse(directory):
        rows = [row for row in a.manual_writers(cfg, path.parent.parent.name)['writers'] if row['state'] == 'active']
        assert len(rows) == 1 and rows[0]['action'] == 'facts' and rows[0]['attempt_ids'] == [path.name]
        assert a.status(cfg, path.parent.parent.name)['state']['paused']
        with pytest.raises(ValueError, match='in-flight manual writer'):
            a.start(cfg, path.parent.parent.name, plan['plan_id'], 'Cannot race facts parsing')
        seen.append(rows[0]['writer_id'])
        return original(directory)
    monkeypatch.setattr(facts, 'parse_facts', parse)
    assert cli.main(['facts', str(path), '--json', *mode]) == 0
    result = json.loads(capsys.readouterr().out)
    assert ('archive' in result) if mode == ['--reparse'] else result['schema'] == 'ag-facts/1'
    records = {row['writer_id']: row for row in a.manual_writers(cfg, path.parent.parent.name)['writers']}
    assert seen and records[seen[0]]['state'] == 'completed'


def test_facts_cli_running_study_keeps_external_dry_run_available(env, cfg, prepared, tmp_path, monkeypatch, capsys):
    path = _fetched_facts_cli_attempt(prepared)
    _publication_context(env, cfg, path)
    monkeypatch.setattr(cli, 'load_config', lambda **kwargs: pytest.fail('Dry-run must not load config'))
    before_study, before_registration = image_tree(path.parent.parent), image_tree(Path.home())
    output = tmp_path / 'external-facts-preview.json'
    assert cli.main(['facts', str(path), '--reparse', '--dry-run', '--out', str(output), '--json']) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['dry_run'] and output.is_file()
    assert image_tree(path.parent.parent) == before_study and image_tree(Path.home()) == before_registration


@pytest.mark.parametrize('alias', ['symlink', 'noncanonical-study-child'])
@pytest.mark.usefixtures("synthetic_cwd")
def test_facts_cli_path_alias_cannot_escape_existing_autonomy(env, cfg, prepared, tmp_path, monkeypatch, capsys, alias):
    from ag import facts
    path = _fetched_facts_cli_attempt(prepared)
    _publication_context(env, cfg, path)
    monkeypatch.setattr(facts, 'parse_facts', lambda *args: pytest.fail('Aliased autonomous path bypassed writer'))
    if alias == 'symlink':
        shortcut = tmp_path / 'legacy-shortcut'
        shortcut.symlink_to(path, target_is_directory=True)
        argv = ['facts', str(shortcut), '--json']
        expected = 'Pause the active autonomous round'
    else:
        shadow = path.parent.parent / 'analyses/shadow'
        shadow.mkdir(parents=True, exist_ok=True)
        (shadow / 'manifest.json').write_bytes((path / 'manifest.json').read_bytes())
        argv = ['facts', '../analyses/shadow', '--study', str(path.parent.parent), '--json']
        expected = 'canonical Attempt path'
    before = image_tree(path.parent.parent)
    assert cli.main(argv) == 1
    assert expected in capsys.readouterr().err
    assert image_tree(path.parent.parent) == before


def test_facts_cli_without_autonomy_blocks_init_while_legacy_bare_directory_stays_compatible(
        env, cfg, prepared, tmp_path, monkeypatch, capsys):
    from ag import facts
    path = _fetched_facts_cli_attempt(prepared)
    original = facts.parse_facts
    def parse(directory):
        with pytest.raises(ValueError, match='in-flight manual writer'):
            a.initialize(cfg, path.parent.parent.name)
        return original(directory)
    monkeypatch.setattr(facts, 'parse_facts', parse)
    assert cli.main(['facts', str(path), '--json']) == 0
    assert json.loads(capsys.readouterr().out)['schema'] == 'ag-facts/1'
    assert not (path.parent.parent / 'autonomy').exists()
    monkeypatch.setattr(facts, 'parse_facts', original)
    legacy = tmp_path / 'Legacy raw logs'
    (legacy / 'outputs').mkdir(parents=True)
    (legacy / 'manifest.json').write_bytes((path / 'manifest.json').read_bytes())
    (legacy / 'outputs/water.log').write_bytes((path / 'outputs/water.log').read_bytes())
    before = image_tree(Path.home())
    assert cli.main(['facts', str(legacy), '--json']) == 0
    assert json.loads(capsys.readouterr().out)['schema'] == 'ag-facts/1'
    assert (legacy / 'facts.json').is_file() and image_tree(Path.home()) == before


def _watch_large_publication_io(monkeypatch, inside):
    """Observe real payload IO through both ordinary and descriptor streams."""
    original_open, original_fdopen = Path.open, os.fdopen
    seen = []
    class Stream:
        def __init__(self, stream):
            self.stream = stream
        def __getattr__(self, name):
            return getattr(self.stream, name)
        def __enter__(self):
            self.stream.__enter__()
            return self
        def __exit__(self, *args):
            return self.stream.__exit__(*args)
        def read(self, *args):
            result = self.stream.read(*args)
            if len(result) > 1_000_000:
                assert not inside[0], 'Large payload read while holding publication locks'
                seen.append('read')
            return result
        def write(self, content):
            if len(content) > 1_000_000:
                assert not inside[0], 'Large payload write while holding publication locks'
                seen.append('write')
            return self.stream.write(content)
    monkeypatch.setattr(Path, 'open', lambda *args, **kwargs: Stream(original_open(*args, **kwargs)))
    monkeypatch.setattr(os, 'fdopen', lambda *args, **kwargs: Stream(original_fdopen(*args, **kwargs)))
    return seen


@pytest.mark.parametrize('mode', ['new', 'same', 'refresh'])
def test_facts_large_payload_io_finishes_before_publication(env, cfg, prepared, monkeypatch, mode):
    from contextlib import contextmanager
    from ag import facts
    path, _ = prepared
    parsed = dict(schema='ag-facts/1', n_atoms=3, synthetic='x' * 1_100_000)
    geometry = '3\nsynthetic water\nO 0 0 0\nH 0 0 1\nH 0 1 0\n' * 30_000
    monkeypatch.setattr(facts, 'parse_facts', lambda directory: (deepcopy(parsed), {'mdopt.xyz': geometry}))
    monkeypatch.setattr(facts, 'ag_provenance', lambda: {'synthetic': True})
    target = path / 'facts.json'
    old = None
    if mode != 'new':
        old = (json.dumps(dict(parsed, n_atoms=3 if mode == 'same' else 2)) + '\r\n').encode()
        target.write_bytes(old)
        (path / 'mdopt.xyz').write_text(geometry)
        old_mtime = target.stat().st_mtime_ns
    _, _, _, actual = _publication_context(env, cfg, path)
    inside, entered = [False], []
    @contextmanager
    def publication():
        with actual() as current:
            inside[0] = True
            entered.append(True)
            try:
                yield current
            finally:
                inside[0] = False
    seen = _watch_large_publication_io(monkeypatch, inside)
    result = facts.build_facts(path, refresh=mode == 'refresh', publication=publication)
    assert result['n_atoms'] == 3 and entered == [True]
    assert 'read' in seen  # New candidates are read back before the short guard too.
    assert ('write' in seen) == (mode != 'same')
    if mode == 'same':
        assert target.read_bytes() == old and target.stat().st_mtime_ns == old_mtime
    elif mode == 'refresh':
        assert (path / f'facts.{sha256(old).hexdigest()[:12]}.json').read_bytes() == old
    assert not list(path.glob('.facts-stage-*'))


@pytest.mark.parametrize('changed', ['expiry', 'geometry'])
def test_facts_staged_payload_does_not_publish_after_loss_or_source_change(env, cfg, prepared, monkeypatch, changed):
    from contextlib import contextmanager
    from ag import facts
    path, _ = prepared
    geometry = path / 'mdopt.xyz'
    geometry.write_text('synthetic geometry\n')
    monkeypatch.setattr(facts, 'parse_facts', lambda directory: (
        {'schema': 'ag-facts/1', 'n_atoms': 3}, {'mdopt.xyz': 'synthetic geometry\n'}))
    context, _, run, actual = _publication_context(env, cfg, path)
    @contextmanager
    def publication():
        if changed == 'expiry':
            context[2][0] = run['state']['lease']['run_until']
        else:
            previous = geometry.stat()
            geometry.write_text('different geometry\n')
            os.utime(geometry, ns=(previous.st_atime_ns, previous.st_mtime_ns))
        with actual() as current:
            yield current
    with pytest.raises(a.PublicationRefused if changed == 'expiry' else ValueError):
        facts.build_facts(path, publication=publication)
    assert not (path / 'facts.json').exists() and not list(path.glob('facts.*.json'))
    assert list(path.glob('.facts-stage-*'))


def test_snapshot_stages_large_payload_before_guard_and_publishes_complete_group(env, cfg, prepared, monkeypatch):
    from contextlib import contextmanager
    from ag import snapshot, state
    from test_core import seed_submission
    from test_snapshot import Fake
    path, _ = prepared
    state.write(path, 'submitting')
    seed_submission(path)
    _, _, _, actual = _publication_context(env, cfg, path)
    inside = [False]
    @contextmanager
    def publication():
        with actual() as current:
            inside[0] = True
            try:
                yield current
            finally:
                inside[0] = False
    seen = _watch_large_publication_io(monkeypatch, inside)
    original_replace, replacements = os.replace, []
    def replace(source, target):
        assert inside[0]
        assert {item.name for item in Path(source).iterdir()} == {'water.log', 'snapshot.json'}
        assert list(Path(target).iterdir()) == []
        replacements.append(True)
        return original_replace(source, target)
    monkeypatch.setattr(snapshot.os, 'replace', replace)
    payload = b'synthetic water log\n' * 60_000
    result = snapshot.capture(cfg, path, Fake(payload), publication=publication)
    assert 'write' in seen and replacements == [True]
    assert (path / result['snapshot'] / 'water.log').read_bytes() == payload
    assert not list(path.glob('.snapshot-stage-*'))


def test_aborted_scientific_remedy_does_not_consume_scientific_limit(env):
    from ag.autonomy_submission import machine_lock
    cfg, directory, _ = env
    plan, run = running(env)
    first = consumed_record(plan, run, 'water-001', failure_class='scf')
    consume(env, plan, run, first)
    with machine_lock():
        a.boundary_failure(cfg, directory.name, first['attempt_id'], first['ownership_sha256'],
            run_id=run['run_id'], token=run['token'], dispatched=False, reason='failed_presubmit')
    change(env, run, 'resume', reason='Explicit synthetic resume')
    second = consumed_record(plan, run, 'water-002', failure_class='scf')
    consume(env, plan, run, second)
    with machine_lock(), a.submission_guard(cfg, directory.name, run['run_id'], run['token'],
                                           plan_sha256=plan['sha256']) as guard:
        guard.dispatch_started(second['attempt_id'])
    consume(env, plan, run, consumed_record(plan, run, 'water-003', failure_class='scf'))
    assert len(a.status(cfg, directory.name)['state']['submissions']) == 3


def test_two_actual_predispatch_failures_block_only_the_same_object(env):
    from ag.autonomy_submission import machine_lock
    cfg, directory, _ = env
    plan, run = running(env)
    for index in (1, 2):
        record = consumed_record(plan, run, f'water-{index:03d}')
        consume(env, plan, run, record)
        with machine_lock():
            a.boundary_failure(cfg, directory.name, record['attempt_id'], record['ownership_sha256'],
                run_id=run['run_id'], token=run['token'], dispatched=False, reason='failed_presubmit')
        change(env, run, 'resume', reason='Explicit synthetic resume')
    before = image_tree(directory)
    with pytest.raises(a.ObjectRefused, match='presubmit'):
        consume(env, plan, run, consumed_record(plan, run, 'water-003'))
    assert image_tree(directory) == before
    consume(env, plan, run, consumed_record(plan, run, 'water-004', object_id='other'))


def test_ssh_failure_counts_once_per_wake_and_pauses_after_two_consecutive_wakes(env):
    cfg, directory, clock = env
    plan, first = running(env)
    options = dict(object_id='water', attempt_id='water-001', plan_sha256=plan['sha256'],
                   reason='Synthetic SSH failure')
    result = a.record_presubmit_failure(cfg, directory.name, first['run_id'], first['token'], **options)
    assert not result['state']['paused']
    before = image_tree(directory)
    a.record_presubmit_failure(cfg, directory.name, first['run_id'], first['token'], **options)
    assert image_tree(directory) == before
    with pytest.raises(a.PresubmitDeferred):
        a.check_presubmit_retry(result['state'], 'water')
    change(env, first, 'finish', reason='End first failed wake')
    clock[0] += 1
    second = a.start(cfg, directory.name, plan['plan_id'], 'second')
    a.check_presubmit_retry(second['state'], 'water')
    result = a.record_presubmit_failure(cfg, directory.name, second['run_id'], second['token'], **options)
    assert result['state']['paused']
    assert len(result['state']['presubmit_failures']) == 2
    assert 'submissions' not in result['state']


def test_successful_intervening_wake_breaks_ssh_streak_and_late_owner_cannot_pause(env):
    cfg, directory, clock = env
    plan, first = running(env)
    options = dict(object_id='water', attempt_id=None, plan_sha256=plan['sha256'], reason='Synthetic SSH failure')
    a.record_presubmit_failure(cfg, directory.name, first['run_id'], first['token'], **options)
    change(env, first, 'finish', reason='End first wake')
    clock[0] += 1
    middle = a.start(cfg, directory.name, plan['plan_id'], 'middle')
    change(env, middle, 'finish', reason='Wake completed without SSH failure')
    clock[0] += 1
    last = a.start(cfg, directory.name, plan['plan_id'], 'last')
    result = a.record_presubmit_failure(cfg, directory.name, last['run_id'], last['token'], **options)
    assert not result['state']['paused']
    before = image_tree(directory)
    assert a.record_presubmit_failure(cfg, directory.name, first['run_id'], first['token'], **options) is False
    assert image_tree(directory) == before


@pytest.mark.parametrize('dispatched', [False, True])
def test_typed_boundary_ssh_keeps_exact_evidence_and_unknown_pause(env, dispatched):
    from ag.autonomy_submission import machine_lock
    cfg, directory, _ = env
    plan, run = running(env)
    record = consumed_record(plan, run)
    consume(env, plan, run, record)
    with machine_lock(), a.submission_guard(cfg, directory.name, run['run_id'], run['token'],
                                           plan_sha256=plan['sha256']) as guard:
        if dispatched:
            guard.dispatch_started(record['attempt_id'])
    with machine_lock():
        result = a.boundary_failure(cfg, directory.name, record['attempt_id'], record['ownership_sha256'],
            run_id=run['run_id'], token=run['token'], dispatched=dispatched,
            reason='unknown' if dispatched else 'failed_presubmit', failure_kind='ssh')
    assert result['state']['paused'] == dispatched
    saved = result['state']['submissions'][record['attempt_id']]
    assert saved['boundary_failure']['failure_kind'] == 'ssh'
    assert (saved['aborted_before_dispatch'] is None) == dispatched


def test_old_presubmit_consumption_journal_replays_without_new_failure_cap(env):
    from ag.autonomy_submission import machine_lock
    cfg, directory, _ = env
    plan, run = running(env)
    # This is the exact old event shape, not a new driver asking for old rules.
    for index in range(3):
        record = consumed_record(plan, run, f'water-{index + 1:03d}',
                                 failure_class=None if index == 0 else 'presubmit')
        with machine_lock(), disk.locked(cfg, directory.name, write=True) as store:
            snapshot, _ = a.load(store)
            store.commit(snapshot, 'submission_consume', a.now(), dict(record=record,
                token_sha256=sha256(run['token'].encode()).hexdigest(), versions=VERSIONS), a.apply)
        with machine_lock():
            a.boundary_failure(cfg, directory.name, record['attempt_id'], record['ownership_sha256'],
                run_id=run['run_id'], token=run['token'], dispatched=False, reason='failed_presubmit')
        change(env, run, 'resume', reason='Historical explicit resume')
    assert len(a.status(cfg, directory.name)['state']['submissions']) == 3
    before = image_tree(directory)
    with pytest.raises(a.ObjectRefused, match='presubmit'):
        consume(env, plan, run, consumed_record(plan, run, 'water-004', failure_class='presubmit'))
    assert image_tree(directory) == before


def test_no_attempt_failure_cap_survives_a_successful_intervening_wake(env):
    cfg, directory, clock = env
    plan, run = running(env)
    for index in range(3):
        if index != 1:
            a.record_presubmit_failure(cfg, directory.name, run['run_id'], run['token'],
                object_id='water', attempt_id=None, plan_sha256=plan['sha256'], reason='Synthetic install-query SSH failure')
        change(env, run, 'finish', reason='End synthetic wake')
        clock[0] += 1
        run = a.start(cfg, directory.name, plan['plan_id'], 'next-' + str(index))
    current = a.status(cfg, directory.name)['state']
    assert not current['paused'] and 'submissions' not in current
    assert current['totals']['attempt'] == 0
    with pytest.raises(a.ObjectRefused, match='presubmit'):
        a.check_presubmit_retry(current, 'water')
    a.check_presubmit_retry(current, 'other')


def test_old_owner_typed_presubmit_outcome_does_not_pause_successor(env):
    from ag.autonomy_submission import machine_lock
    cfg, directory, clock = env
    plan, old = running(env)
    record = consumed_record(plan, old)
    consume(env, plan, old, record)
    clock[0] += 5401
    new = a.start(cfg, directory.name, plan['plan_id'], 'successor', takeover_reason='Synthetic expired lease')
    with machine_lock():
        result = a.boundary_failure(cfg, directory.name, record['attempt_id'], record['ownership_sha256'],
            run_id=old['run_id'], token=old['token'], dispatched=False,
            reason='failed_presubmit', failure_kind='ssh')
    assert not result['state']['paused'] and result['state']['lease']['run_id'] == new['run_id']
    assert result['state']['submissions'][record['attempt_id']]['aborted_before_dispatch']
    with pytest.raises(ValueError, match='owner'):
        check(env, plan, old)
    assert check(env, plan, new)['eligible_now']


@pytest.mark.parametrize('change_kind', ['lease', 'plan', 'versions'])
def test_ssh_failure_does_not_hide_changed_global_authorization(env, monkeypatch, change_kind):
    cfg, directory, clock = env
    plan, run = expiring_run(env)
    if change_kind == 'lease':
        clock[0] += 3600
    elif change_kind == 'plan':
        clock[0] = plan['plan']['spec']['valid_until']
    else:
        monkeypatch.setattr(a, 'versions', lambda: dict(VERSIONS, rdkit='changed'))
    assert a.record_presubmit_failure(cfg, directory.name, run['run_id'], run['token'],
        object_id='water', attempt_id='water-001', plan_sha256=plan['sha256'], reason='Synthetic SSH failure') is False
    assert a.status(cfg, directory.name)['state']['paused']


def test_object_qualification_aborts_keep_attempt_budget_without_spending_ssh_failure_cap(env):
    from ag.autonomy_submission import machine_lock
    cfg, directory, _ = env
    plan, run = running(env)
    for index in (1, 2):
        record = consumed_record(plan, run, f'water-{index:03d}')
        consume(env, plan, run, record)
        with machine_lock():
            result = a.boundary_failure(cfg, directory.name, record['attempt_id'], record['ownership_sha256'],
                run_id=run['run_id'], token=run['token'], dispatched=False,
                reason='Placement no longer eligible', failure_kind='object')
        assert not result['state']['paused']
        assert result['state']['submissions'][record['attempt_id']]['aborted_before_dispatch']
    current = a.status(cfg, directory.name)['state']
    assert len(current['submissions']) == 2
    assert not current['runs'][run['run_id']].get('ssh_failed')
    assert a._presubmit_failures(current, 'water') == {}
    a.check_presubmit_retry(current, 'water')
    consume(env, plan, run, consumed_record(plan, run, 'water-003'))
    assert len(a.status(cfg, directory.name)['state']['submissions']) == 3
