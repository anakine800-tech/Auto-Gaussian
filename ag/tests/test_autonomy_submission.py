"""Existing evidence audit uses synthetic studies and fixed recording fakes."""
import json
from copy import deepcopy
from pathlib import Path

import pytest

from ag import approval, autonomy_submission, state, submission, submit
from ag.transport import Result
from test_core import cfg, prepared, Fake


def authorized(cfg, path):
    return approval.create(cfg, path.parent.parent.name, [path.name], 'Approve synthetic water validation.')['id']


def tree(path):
    return {str(item.relative_to(path)): item.read_bytes() for item in path.rglob('*') if item.is_file()}


def test_prepared_is_unconsumed_without_writes(cfg, prepared):
    path, _ = prepared
    before = tree(path.parent.parent)
    result = autonomy_submission.audit(path)
    assert result['classification'] == 'unconsumed'
    assert result['retained_cores'] == 0
    assert result['autonomous_ownership_verified'] is False
    assert result['round_id'] is result['run_id'] is None
    assert tree(path.parent.parent) == before


def test_known_submission_keeps_exact_binding_and_cores(cfg, prepared):
    path, _ = prepared
    fake = Fake(cfg)
    submit.submit(cfg, [path.name], fake, approval_id=authorized(cfg, path))
    before = tree(path.parent.parent)
    result = autonomy_submission.audit(path)
    assert result['classification'] == 'existing_manual'
    assert result['job_id'] == 'default:123.fixture'
    assert result['retained_cores'] == 8
    assert not result['autonomous_ownership_verified']
    state.write(path, 'finished')
    assert autonomy_submission.audit(path)['retained_cores'] == 8
    # The audit itself has no writes or transport capability.
    after_finish = tree(path.parent.parent)
    autonomy_submission.audit(path)
    assert tree(path.parent.parent) == after_finish
    assert before['attempts/' + path.name + '/submission.json'] == after_finish['attempts/' + path.name + '/submission.json']


@pytest.mark.parametrize('reply', [Result(255, '', 'Synthetic reply loss'), Result(1, '', 'qsub: Synthetic rejection')])
def test_unknown_and_mutable_failure_labels_do_not_release(cfg, prepared, reply):
    path, _ = prepared
    fake = Fake(cfg)
    fake.qsub = reply
    with pytest.raises((ValueError, submit.UnknownSubmission)):
        submit.submit(cfg, [path.name], fake, approval_id=authorized(cfg, path))
    before = tree(path.parent.parent)
    result = autonomy_submission.audit(path)
    assert result['classification'] == 'reserved'
    assert result['outcome'] == 'unresolved'
    assert result['retained_cores'] == 8
    assert tree(path.parent.parent) == before


def test_readonly_unknown_recovery_does_not_create_second_consumption(cfg, prepared):
    path, manifest = prepared
    fake = Fake(cfg)
    fake.qsub = Result(255, '', 'Synthetic reply loss')
    with pytest.raises(submit.UnknownSubmission):
        submit.submit(cfg, [path.name], fake, approval_id=authorized(cfg, path))
    reserved = autonomy_submission.audit(path)
    submission.record(path, manifest, '123.fixture')
    state.write(path, 'submitted', job_id='default:123.fixture')
    result = autonomy_submission.audit(path)
    assert reserved['retained_cores'] == result['retained_cores'] == 8
    assert result['authorization'] == reserved['authorization']
    assert result['outcome'] == 'submitted'
    assert fake.operations().count('submit') == 1


@pytest.mark.parametrize('name', ['.submit-claim', 'submission-summary.json', 'submission.json', 'manifest.json', 'status.json'])
@pytest.mark.parametrize('damage', ['missing', 'truncated'])
def test_missing_or_truncated_evidence_never_becomes_zero(cfg, prepared, name, damage):
    path, _ = prepared
    submit.submit(cfg, [path.name], Fake(cfg), approval_id=authorized(cfg, path))
    target = path / name
    if damage == 'missing':
        target.unlink()
    else:
        target.write_bytes(target.read_bytes()[:5])
    before = tree(path.parent.parent)
    with pytest.raises(ValueError, match='audit refused'):
        autonomy_submission.audit(path)
    assert tree(path.parent.parent) == before


@pytest.mark.parametrize('damage', ['missing_auth', 'duplicate_auth', 'truncated', 'status_only', 'summary_auth', 'binding_auth', 'job', 'input', 'claim_symlink'])
def test_conflicting_evidence_refuses(cfg, prepared, damage):
    path, _ = prepared
    submit.submit(cfg, [path.name], Fake(cfg), approval_id=authorized(cfg, path))
    journal_path = path.parent.parent / 'journal.jsonl'
    events = [json.loads(line) for line in journal_path.read_text().splitlines()]
    if damage == 'missing_auth':
        events = [event for event in events if event['action'] != 'submit_authorization']
        journal_path.write_text(''.join(json.dumps(event) + '\n' for event in events))
    elif damage == 'duplicate_auth':
        event = next(event for event in events if event['action'] == 'submit_authorization')
        with journal_path.open('a') as handle:
            handle.write(json.dumps(event) + '\n')
    elif damage == 'truncated':
        with journal_path.open('ab') as handle:
            handle.write(b'{"action":')
    elif damage == 'status_only':
        value = state.read(path)
        value.update(state='failed_presubmit', job_id=None)
        (path / 'status.json').write_text(json.dumps(value))
    elif damage in ('summary_auth', 'binding_auth'):
        target = path / ('submission-summary.json' if damage == 'summary_auth' else 'submission.json')
        value = json.loads(target.read_text())
        value['authorization']['quote'] = 'different quote'
        target.write_text(json.dumps(value))
    elif damage == 'job':
        target = path / 'submission.json'
        value = json.loads(target.read_text())
        value['job_id'] = 'default:124.fixture'
        target.write_text(json.dumps(value))
    elif damage == 'input':
        with (path / 'inputs/water.gjf').open('ab') as handle:
            handle.write(b'\n')
    else:
        target = path / '.submit-claim'
        raw = target.read_bytes()
        target.unlink()
        alternate = path / 'alternate-claim'
        alternate.write_bytes(raw)
        target.symlink_to(alternate)
    with pytest.raises(ValueError, match='audit refused'):
        autonomy_submission.audit(path)


@pytest.mark.parametrize('damage', ['status_job_missing', 'duplicate_key', 'unknown_authorization', 'summary_manifest', 'journal_missing'])
def test_unsupported_or_incomplete_identity_is_not_adopted(cfg, prepared, damage):
    path, _ = prepared
    submit.submit(cfg, [path.name], Fake(cfg), approval_id=authorized(cfg, path))
    if damage == 'status_job_missing':
        value = state.read(path)
        value['job_id'] = None
        (path / 'status.json').write_text(json.dumps(value))
    elif damage == 'journal_missing':
        (path.parent.parent / 'journal.jsonl').unlink()
    else:
        target = path / 'submission-summary.json'
        value = json.loads(target.read_text())
        if damage == 'duplicate_key':
            target.write_text('{"schema":"invalid",' + json.dumps(value)[1:])
        else:
            if damage == 'unknown_authorization':
                value['authorization']['method'] = 'autonomous'
                value['authorization']['round_id'] = 'invented-round'
            else:
                value['manifest_sha256'] = '0' * 64
            target.write_text(json.dumps(value))
    with pytest.raises(ValueError, match='audit refused'):
        autonomy_submission.audit(path)


def test_manifest_input_order_does_not_imply_primary_input(cfg, prepared):
    path, manifest = prepared
    manifest['inputs'].reverse()
    (path / 'manifest.json').write_text(json.dumps(manifest))
    report = autonomy_submission.audit(path)
    assert report['classification'] == 'unconsumed'
    assert report['bundle_sha256'] == manifest['bundle_sha256']
    assert not report['autonomous_ownership_verified']


def test_duplicate_input_entry_still_refused(cfg, prepared):
    path, manifest = prepared
    manifest['inputs'].append(manifest['inputs'][0])
    (path / 'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='bundle'):
        autonomy_submission.audit(path)


@pytest.mark.parametrize('field,value', [('size', True), ('size', 1.0), ('size', -1), ('sha256', 'bad')])
def test_input_manifest_types_cannot_compare_equal_to_valid_records(cfg, prepared, field, value):
    path, manifest = prepared
    manifest['inputs'][0][field] = value
    (path / 'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='input file manifest'):
        autonomy_submission.audit(path)


@pytest.fixture
def selector(cfg, tmp_path, monkeypatch):
    """Fixed, recording selector substitute; no second routing algorithm."""
    from ag import config, route
    cfg['_config_path'] = str(tmp_path / 'synthetic-config.toml')
    Path(cfg['_config_path']).write_text('# Synthetic local test config\n')
    monkeypatch.setattr(config, 'ssh_identity', lambda selected: ('synthetic-host', 22, 'synthetic-user'))
    monkeypatch.setattr(route, 'ladder_config_identity', lambda value: 'b' * 64, raising=False)
    calls = []
    def select(value, snapshots, *, placements, wakeups, batch_inputs, now, **request):
        original = dict(config_sha256='b' * 64, request=request, snapshots=snapshots,
                        placements=placements, wakeups=wakeups, selected_at=now.isoformat())
        digest = approval.digest(original)
        choice = None
        if snapshots['selected']:
            choice = dict(cell_id='first', cluster='default', tier='simple', cores=8, mem_gb=12,
                          target_node=None, node_fraction=None, capacity_node='node-a',
                          batch_input_sha256=digest)
        result = dict(schema='ag-routing-ladder/1', **request,
                      evidence=dict(config_sha256='b' * 64, input_sha256=digest),
                      recommendation=choice, candidates=[], reason='selected' if choice else 'no_eligible_cell')
        calls.append(original)
        return result
    monkeypatch.setattr(route, 'select_ladder', select, raising=False)
    return select, calls


def selection_for(cfg, path, selector, *, selected=True, round_id='round-one', run_id='run-one', object_id='water'):
    from datetime import datetime, timezone
    request = dict(template=json.loads((path / 'manifest.json').read_text())['template'], job_class='main', walltime='00:30:00',
        study_id=path.parent.parent.name,
        study_key=autonomy_submission.study_identity(path.parent.parent)['study_key'],
        round_id=round_id, run_id=run_id, object_id=object_id, waiting_since=None, parent_cluster=None)
    now = datetime.fromtimestamp(1000, timezone.utc)
    original = dict(config_sha256='b' * 64, request=request, snapshots={'selected': selected},
                    placements=[], wakeups=[], selected_at=now.isoformat())
    result = selector(cfg, original['snapshots'], **request, placements=[], wakeups=[], batch_inputs={}, now=now)
    return dict(input=original, result=result)


def reservation_context(cfg, path, selector, **changes):
    value = dict(round_id='round-one', run_id='run-one', object_id='water', failure_class=None,
                 remedy_source=None,
                 max_attempts=10, plan_sha256='a' * 64, rule_sha256='c' * 64,
                 routing_sha256='b' * 64, policy_name='bounded', quote='Synthetic bounded authorization.',
                 summary='Complete synthetic geometry, method, route, resources and hashes.',
                 selection=selection_for(cfg, path, selector))
    value.update(changes)
    return value


def install_owned(cfg, path, selector):
    from ag.locks import claim
    with autonomy_submission.machine_lock():
        saved = autonomy_submission.write_reservation(cfg, path, reservation_context(cfg, path, selector), verified_state={})
        claim(path / '.submit-claim')
        approval.archive(path, saved['authorization'], saved['record']['summary'])
    current = dict(current_round='round-one', current_plan='plan-one',
        plans={'plan-one': {'sha256': 'a' * 64, 'confirmation': {'quote': 'Synthetic confirmation'}}},
        runs={'run-one': {'round_id': 'round-one', 'plan_id': 'plan-one', 'started_at': 1000}},
        rounds={'round-one': {}},
        submissions={path.name: {**saved['consume'], 'plan_id': 'plan-one', 'at': 1001,
                                'dispatch_started': None, 'aborted_before_dispatch': None}})
    return saved, current


def supplied(path, current):
    return {str(path.parent.parent): current}


def reservation_path(saved):
    return Path.home() / '.config' / 'ag' / 'autonomy-reservations' / saved['filename']


def test_durable_reservation_is_global_and_undispatched_retained(cfg, prepared, selector, tmp_path):
    path, manifest = prepared
    choose, calls = selector
    saved, current = install_owned(cfg, path, choose)
    before = reservation_path(saved).read_bytes()
    result = autonomy_submission.read_reservations(cfg, states=supplied(path, current))
    placement = result['placements'][0]
    assert placement['state'] == 'reserved' and placement['job_id'] is None
    assert placement['round_id'] == 'round-one'
    assert placement['cores'] == manifest['cores']
    assert placement['scheduler_job_name'] == manifest['pbs_job_name']
    assert placement['study_key'] == saved['record']['study_key']
    assert result['batch_inputs'][placement['batch_input_sha256']] == saved['record']['selection']['input']
    # A different configuration directory sees exactly the same immutable file.
    alternate = deepcopy(cfg)
    alternate['_config_dir'] = str(tmp_path / 'another-config')
    assert autonomy_submission.read_reservations(alternate, states=supplied(path, current))['placements'] == result['placements']
    assert reservation_path(saved).read_bytes() == before
    assert len(calls) == 2  # Selection plus replay at write, never remote IO.
    with pytest.raises(ValueError, match='consumed'):
        autonomy_submission.write_reservation(cfg, path, reservation_context(cfg, path, choose), verified_state={})


@pytest.mark.parametrize('damage', ['record', 'claim', 'summary', 'consumption', 'manifest', 'input', 'journal'])
def test_reservation_missing_side_never_becomes_zero(cfg, prepared, selector, damage):
    path, _ = prepared
    saved, current = install_owned(cfg, path, selector[0])
    if damage == 'record':
        reservation_path(saved).unlink()
    elif damage == 'consumption':
        current['submissions'].clear()
    else:
        target = {'claim': path / '.submit-claim', 'summary': path / 'submission-summary.json',
                  'manifest': path / 'manifest.json', 'input': path / 'inputs' / 'water.gjf',
                  'journal': path.parent.parent / 'journal.jsonl'}[damage]
        target.unlink()
    with pytest.raises((ValueError, OSError)):
        autonomy_submission.read_reservations(cfg, states=supplied(path, current))


@pytest.mark.parametrize('damage', ['truncated', 'symlink', 'hardlink', 'inode'])
def test_global_reservation_integrity_and_directory_identity(cfg, prepared, selector, damage, tmp_path):
    path, _ = prepared
    saved, current = install_owned(cfg, path, selector[0])
    target = reservation_path(saved)
    if damage == 'truncated':
        target.write_bytes(target.read_bytes()[:10])
    elif damage in ('symlink', 'hardlink'):
        original = tmp_path / 'original-reservation'
        original.write_bytes(target.read_bytes())
        target.unlink()
        if damage == 'symlink':
            target.symlink_to(original)
        else:
            target.hardlink_to(original)
    else:
        import shutil
        original = path.parent.parent
        moved = original.with_name('moved-study')
        original.rename(moved)
        shutil.copytree(moved, original)
    with pytest.raises((ValueError, OSError)):
        autonomy_submission.read_reservations(cfg, states=supplied(path, current))


def test_pending_orphan_blocks_instead_of_reconstructing_consumption(cfg, prepared, selector):
    path, _ = prepared
    saved = autonomy_submission.write_reservation(cfg, path, reservation_context(cfg, path, selector[0]), verified_state={})
    assert reservation_path(saved).is_file()
    with pytest.raises(ValueError, match='Missing study autonomy state'):
        autonomy_submission.read_reservations(cfg)
    assert reservation_path(saved).is_file()


def test_unknown_is_retained_and_verified_abort_is_separate(cfg, prepared, selector):
    path, _ = prepared
    saved, current = install_owned(cfg, path, selector[0])
    state.write(path, 'submitting')
    state.write(path, 'unknown')
    result = autonomy_submission.read_reservations(cfg, states=supplied(path, current))
    assert result['placements'][0]['state'] == 'unknown'
    assert result['records'][0]['outcome'] == 'retained'
    current['submissions'][path.name]['aborted_before_dispatch'] = {'at': 1002, 'reason': 'Proven not dispatched'}
    with pytest.raises(ValueError, match='contradicts'):
        autonomy_submission.read_reservations(cfg, states=supplied(path, current))
    current['submissions'][path.name]['dispatch_started'] = {'at': 1001}
    with pytest.raises(ValueError, match='contradicts'):
        autonomy_submission.read_reservations(cfg, states=supplied(path, current))
    assert reservation_path(saved).is_file()


def test_verified_abort_before_dispatch_releases_only_resource_reservation(cfg, prepared, selector):
    path, _ = prepared
    saved, current = install_owned(cfg, path, selector[0])
    current['submissions'][path.name]['aborted_before_dispatch'] = {'at': 1002, 'reason': 'No dispatch began'}
    result = autonomy_submission.read_reservations(cfg, states=supplied(path, current))
    assert not result['placements']
    assert result['records'][0]['outcome'] == 'aborted_before_dispatch'
    assert len(current['submissions']) == 1 and reservation_path(saved).is_file()


def test_unmapped_account_is_not_silently_ignored(cfg, prepared, selector, monkeypatch):
    from ag import config
    path, _ = prepared
    _, current = install_owned(cfg, path, selector[0])
    monkeypatch.setattr(config, 'ssh_identity', lambda value: ('different-synthetic-host', 22, 'synthetic-user'))
    with pytest.raises(ValueError, match='not mapped'):
        autonomy_submission.read_reservations(cfg, states=supplied(path, current))


@pytest.mark.parametrize('damage', ['result', 'input_digest', 'resource', 'study_key'])
def test_forged_selection_is_rejected_before_global_write(cfg, prepared, selector, damage):
    path, _ = prepared
    value = reservation_context(cfg, path, selector[0])
    if damage == 'result':
        value['selection']['result']['reason'] = 'invented'
    elif damage == 'input_digest':
        value['selection']['result']['evidence']['input_sha256'] = 'f' * 64
    elif damage == 'resource':
        value['selection']['result']['recommendation']['cores'] = 4
    else:
        value['selection']['input']['request']['study_key'] = 'f' * 64
    with pytest.raises(ValueError):
        autonomy_submission.write_reservation(cfg, path, value, verified_state={})
    assert not (Path.home() / '.config' / 'ag' / 'autonomy-reservations').exists()


def test_unknown_authorization_recovery_needs_exact_owned_dispatch(cfg, prepared, selector, monkeypatch):
    path, manifest = prepared
    saved, current = install_owned(cfg, path, selector[0])
    monkeypatch.setattr(autonomy_submission, '_load_state', lambda path, supplied: current)
    state.write(path, 'submitting')
    with pytest.raises(ValueError, match='dispatch boundary'):
        autonomy_submission.verified_authorization(path, saved['authorization'])
    current['submissions'][path.name]['dispatch_started'] = {'at': 1002}
    state.write(path, 'unknown')
    assert autonomy_submission.verified_authorization(path, saved['authorization']) == saved['authorization']
    changed = dict(saved['authorization'], round_id='invented-round')
    with pytest.raises(ValueError, match='exact reserved'):
        autonomy_submission.verified_authorization(path, changed)
    # A later read-only scheduler reconciliation preserves the original bytes
    # and ownership instead of producing a new reservation/consumption.
    submission.record(path, manifest, '123.fixture', authorization=saved['authorization'])
    state.write(path, 'submitted', job_id='default:123.fixture')
    result = autonomy_submission.read_reservations(cfg, states=supplied(path, current))
    assert result['placements'][0]['job_id'] == '123.fixture'
    assert len(result['records']) == len(current['submissions']) == 1


def test_waiting_binds_real_later_wakeups_without_reusing_lease_expiry(cfg, prepared, selector):
    path, _ = prepared
    selection = selection_for(cfg, path, selector[0], selected=False)
    digest = autonomy_submission.write_waiting(cfg, path.parent.parent.name, selection)
    current = dict(current_round='round-one',
        plans={'plan-one': {'sha256': 'a' * 64, 'confirmation': {'quote': 'Synthetic'}}},
        runs={'run-one': {'round_id': 'round-one', 'plan_id': 'plan-one', 'started_at': 1000},
              'run-two': {'round_id': 'round-one', 'plan_id': 'plan-one', 'started_at': 1000 + 5 * 3600},
              'observer': {'round_id': 'round-one', 'plan_id': 'plan-one', 'started_at': 9000, 'observe_only': True}},
        waiting=[dict(object_id='water', record_sha256=digest, round_id='round-one', run_id='run-one',
                      plan_id='plan-one', plan_sha256='a' * 64, at=1001)])
    since, wakeups = autonomy_submission.waiting_history(cfg, current, path.parent.parent.name, 'water')
    assert since.endswith('+00:00')
    assert [wake['run_id'] for wake in wakeups] == ['run-two']
    assert wakeups[0]['study_key'] == selection['input']['request']['study_key']
    assert autonomy_submission.waiting_history(cfg, current, path.parent.parent.name, 'other') == (None, [])
    current['waiting'][0]['run_id'] = 'run-two'
    with pytest.raises(ValueError, match='event disagree'):
        autonomy_submission.waiting_history(cfg, current, path.parent.parent.name, 'water')


def test_selected_result_cannot_be_recorded_as_waiting(cfg, prepared, selector):
    path, _ = prepared
    with pytest.raises(ValueError, match='unselected'):
        autonomy_submission.write_waiting(cfg, path.parent.parent.name, selection_for(cfg, path, selector[0]))
    assert not (Path.home() / '.config' / 'ag' / 'autonomy-waiting').exists()


def test_machine_lock_rejects_redirected_lock(tmp_path):
    with autonomy_submission.machine_lock():
        pass
    lock = Path.home() / '.config' / 'ag' / 'autonomy-submit.lock'
    lock.unlink()
    target = tmp_path / 'redirected-lock'
    target.touch()
    lock.symlink_to(target)
    with pytest.raises((ValueError, OSError)):
        with autonomy_submission.machine_lock():
            pytest.fail('Redirected mutex must not be acquired')


def test_machine_lock_readonly_never_initializes():
    root = Path.home() / '.config' / 'ag'
    with pytest.raises(FileNotFoundError):
        with autonomy_submission.machine_lock(create=False):
            pytest.fail('Missing read-only lock must not create state')
    assert not root.exists()
    with autonomy_submission.machine_lock():
        pass
    before = tree(root)
    with autonomy_submission.machine_lock(create=False):
        pass
    assert tree(root) == before


def test_machine_lock_uses_verified_descriptor_and_rejects_replacement(monkeypatch):
    import os
    with autonomy_submission.machine_lock():
        pass
    lock = Path.home() / '.config' / 'ag' / 'autonomy-submit.lock'
    original_inode = lock.stat().st_ino
    real_flock = autonomy_submission.fcntl.flock
    seen = []
    def replace_after_open(fd, operation):
        seen.append(os.fstat(fd).st_ino)
        lock.rename(lock.with_name('previous-lock'))
        lock.touch()
        # The actual locked descriptor is still the originally validated one.
        real_flock(fd, operation)
    monkeypatch.setattr(autonomy_submission.fcntl, 'flock', replace_after_open)
    with pytest.raises(ValueError, match='mutex was replaced'):
        with autonomy_submission.machine_lock(create=False):
            pytest.fail('A replacement inode must not pass verification')
    assert seen == [original_inode]


def test_single_exclusive_reservation_under_two_competing_writers(cfg, prepared, selector):
    from concurrent.futures import ThreadPoolExecutor
    path, _ = prepared
    context = reservation_context(cfg, path, selector[0])
    def reserve():
        try:
            with autonomy_submission.machine_lock():
                return autonomy_submission.write_reservation(cfg, path, context, verified_state={})['sha256']
        except FileExistsError:
            return 'already-reserved'
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: reserve(), range(2)))
    assert results.count('already-reserved') == 1
    assert len(list((Path.home() / '.config/ag/autonomy-reservations').iterdir())) == 1


def test_same_named_studies_in_distinct_roots_remain_distinct_global_reservations(cfg, prepared, selector, tmp_path):
    from ag import attempt, study
    path, _ = prepared
    saved, current = install_owned(cfg, path, selector[0])
    other_cfg = deepcopy(cfg)
    other_cfg['local']['studies_root'] = str(tmp_path / 'other-studies')
    other_cfg['_config_dir'] = str(tmp_path / 'other-config')
    Path(other_cfg['_config_dir']).mkdir()
    other_cfg['_config_path'] = str(Path(other_cfg['_config_dir']) / 'config.toml')
    Path(other_cfg['_config_path']).write_text('# Synthetic second local configuration\n')
    study.init(other_cfg, 'smoke')
    manifest = attempt.prepare(other_cfg, study_name='smoke', template='gaussian', input_path=tmp_path / 'water.gjf',
        tier='simple', walltime='00:30:00', label='sp', method_basis='Synthetic water method')
    other_path = attempt.find(other_cfg, manifest['attempt_id'])
    other_saved, other_state = install_owned(other_cfg, other_path, selector[0])
    states = {**supplied(path, current), **supplied(other_path, other_state)}
    result = autonomy_submission.read_reservations(other_cfg, states=states)
    assert len(result['placements']) == 2
    assert path.name == other_path.name
    assert saved['filename'] != other_saved['filename']
    assert {p['study_key'] for p in result['placements']} == {
        saved['record']['study_key'], other_saved['record']['study_key']}
    # The separate immutable location registration retains the old root even
    # after its sole reservation disappears and the active config root changes.
    reservation_path(saved).unlink()
    with pytest.raises(ValueError, match='missing its global reservation'):
        autonomy_submission.read_reservations(other_cfg, states=states)


def test_reservation_cannot_outlive_missing_study_registration(cfg, prepared, selector):
    path, _ = prepared
    saved, current = install_owned(cfg, path, selector[0])
    registration = Path.home() / '.config/ag/autonomy-studies' / (saved['record']['study_key'] + '.json')
    registration.unlink()
    with pytest.raises(ValueError, match='missing its global study registration'):
        autonomy_submission.read_reservations(cfg, states=supplied(path, current))


def test_same_account_aliases_must_share_one_explicit_identity(cfg, prepared, selector):
    path, _ = prepared
    _, current = install_owned(cfg, path, selector[0])
    entries = {'default': deepcopy(cfg), 'second': deepcopy(cfg)}
    cfg['_cluster_entries'] = entries
    # Two queue/resource entries with the same exact SSH identity are safe.
    assert len(autonomy_submission.read_reservations(cfg, states=supplied(path, current))['placements']) == 1
    entries['second']['ssh']['host'] = 'different-alias-same-account'
    with pytest.raises(ValueError, match='unmerged cluster identities'):
        autonomy_submission.read_reservations(cfg, states=supplied(path, current))


def test_legacy_selection_replays_only_reviewed_legacy_function(cfg, prepared, selector, monkeypatch):
    from ag import route
    path, _ = prepared
    selection = selection_for(cfg, path, selector[0])
    original = selection['input']
    original['request'].update(template='xtb', tier='simple')
    result = deepcopy(selection['result'])
    result.update(schema='ag-routing-legacy/1', **original['request'])
    result['evidence']['input_sha256'] = approval.digest(original)
    selection['result'] = result
    calls = []
    def legacy(value, snapshots, **options):
        calls.append(options)
        return deepcopy(result)
    monkeypatch.setattr(route, 'select_legacy', legacy, raising=False)
    assert autonomy_submission.verify_selection(cfg, selection) == result
    assert calls[0]['tier'] == 'simple'
    original['request']['template'] = 'gaussian'
    with pytest.raises(ValueError, match='only supports CREST/xTB'):
        autonomy_submission.verify_selection(cfg, selection)


def bound_owned(cfg, path, selector, monkeypatch):
    saved, current = install_owned(cfg, path, selector)
    current['submissions'][path.name]['dispatch_started'] = {'at': 1002}
    monkeypatch.setattr(autonomy_submission, '_load_state', lambda path, supplied: current)
    manifest = json.loads((path / 'manifest.json').read_text())
    state.write(path, 'submitting')
    submission.record(path, manifest, '123.fixture', authorization=saved['authorization'])
    state.write(path, 'submitted', job_id='default:123.fixture')
    return saved, current, manifest


def finish_owned(path, manifest, text, *, returncode=1):
    from ag import journal, remote
    receipt = dict(PBS_JOBID='123.fixture', returncode=returncode,
                   finished_at='2026-01-01T00:00:00+00:00')
    state.write(path, 'finished', exit_status=returncode, completion_source='ag-exit.json',
                receipts={'start': None, 'exit': receipt}, observation={'job_id': '123.fixture'},
                scheduler_observed_at=1003)
    names = remote.output_names(manifest)
    for name in names:
        (path / 'outputs' / name).write_text(text if name == names[0] else 'Synthetic scheduler output\n')
    state.write(path, 'fetched', exit_status=returncode)
    journal.append(path.parent.parent, 'fetch', path.name, detail={'files': names})


def test_finished_label_alone_never_releases_owned_placement(cfg, prepared, selector, monkeypatch):
    path, _ = prepared
    _, current, _ = bound_owned(cfg, path, selector[0], monkeypatch)
    state.write(path, 'finished')
    with pytest.raises(ValueError, match='terminal return code'):
        autonomy_submission.read_reservations(cfg, states=supplied(path, current))


def test_manual_terminal_is_excluded_only_from_local_reservations(cfg, prepared, selector):
    path, _ = prepared
    submit.submit(cfg, [path.name], Fake(cfg), approval_id=authorized(cfg, path))
    state.write(path, 'finished')
    result = autonomy_submission.read_reservations(cfg)
    assert result['placements'] == []
    assert result['warnings'][0]['state'] == 'finished'
    assert autonomy_submission.audit(path)['retained_cores'] == 8


@pytest.mark.parametrize('history', ['pre_t111', 'legacy_marker', 'cancelled', 'interrupted', 'incomplete_fetch', 'old_slurm'])
def test_historical_manual_terminal_record_does_not_block_accounting(cfg, prepared, selector, tmp_path, history):
    from ag import attempt
    from ag.locks import claim
    path, manifest = prepared
    if history == 'old_slurm':
        cfg.update(scheduler='slurm', partition='fixture')
        manifest = attempt.prepare(cfg, study_name='smoke', template='gaussian', input_path=tmp_path / 'water.gjf',
            tier='simple', walltime='00:30:00', label='old-slurm', method_basis='Synthetic historical record')
        path = attempt.find(cfg, manifest['attempt_id'])
    claim(path / '.submit-claim')
    state.write(path, 'submitting')
    job = '123' if history == 'old_slurm' else '123.fixture'
    submission.record(path, manifest, job)  # Pre-T111 binding has no authorization summary.
    state.write(path, 'submitted', job_id='default:' + job)
    terminal = history if history in ('cancelled', 'interrupted') else 'finished'
    if history == 'incomplete_fetch':
        terminal = 'interrupted'
        (path / 'fetch-incomplete-legacy.json').write_text('{"complete": false}\n')
    state.write(path, terminal, **({'completion_source': 'legacy-marker-stable-scheduler-absent'}
                                 if history == 'legacy_marker' else {}))
    if history == 'old_slurm':
        state.write(path, 'fetched')
    before = tree(path.parent.parent)
    result = autonomy_submission.read_reservations(cfg)
    assert result['placements'] == []
    warnings = result['warnings']
    if history == 'old_slurm':
        unconsumed = [item for item in warnings if item['kind'] == 'manual_unconsumed_excluded']
        assert len(unconsumed) == 1 and unconsumed[0]['attempt_id'] == prepared[0].name
        warnings = [item for item in warnings if item['kind'] != 'manual_unconsumed_excluded']
    assert warnings == [dict(kind='manual_terminal_excluded',
        study_key=autonomy_submission.study_identity(path.parent.parent)['study_key'],
        study_id='smoke', attempt_id=path.name, state='fetched' if history == 'old_slurm' else terminal)]
    assert tree(path.parent.parent) == before


@pytest.mark.parametrize('local_state', [
    'submitted', 'running', 'stalled', 'awaiting_second_observation', 'unknown',
])
def test_pre_t111_nonterminal_manual_keeps_conservative_cores(cfg, prepared, selector, local_state):
    from ag.locks import claim
    path, manifest = prepared
    claim(path / '.submit-claim')
    state.write(path, 'submitting')
    if local_state == 'unknown':
        state.write(path, 'unknown')
    else:
        submission.record(path, manifest, '123.fixture')
        state.write(path, 'submitted', job_id='default:123.fixture')
        if local_state != 'submitted':
            state.write(path, local_state)
    assert not (path / 'submission-summary.json').exists()
    before = tree(path.parent.parent)
    result = autonomy_submission.read_reservations(cfg)
    assert result['records'] == [] and result['batch_inputs'] == {}
    assert len(result['placements']) == 1
    placement = result['placements'][0]
    assert placement['state'] == 'reserved' and placement['cores'] == manifest['cores']
    assert placement['job_id'] is None
    assert placement['round_id'] is placement['run_id'] is None
    assert result['warnings'] == [dict(kind='manual_unverified_reserved',
        study_key=placement['study_key'], study_id='smoke', attempt_id=path.name,
        state=local_state, cores=manifest['cores'])]
    assert tree(path.parent.parent) == before


@pytest.mark.parametrize('origin', ['submission-summary.json', 'submission.json', 'journal'])
def test_unverified_manual_fallback_never_downgrades_autonomous_origin(cfg, prepared, selector, origin):
    from ag import journal
    from ag.locks import claim
    path, _ = prepared
    claim(path / '.submit-claim')
    state.write(path, 'submitting')
    state.write(path, 'unknown')
    if origin == 'journal':
        journal.append(path.parent.parent, 'submit_authorization', path.name, 'ok',
                       {'method': 'autonomy-policy'})
    else:
        (path / origin).write_text(json.dumps({'authorization': {'method': 'autonomy-policy'}}))
    before = tree(path.parent.parent)
    with pytest.raises(ValueError, match='Autonomous.*missing its global reservation'):
        autonomy_submission.read_reservations(cfg)
    assert tree(path.parent.parent) == before


@pytest.mark.parametrize('damage', ['identity', 'bundle', 'zero_cores', 'bool_cores', 'string_cores',
                                    'invalid_mem', 'scheduler', 'cluster', 'symlink'])
def test_unverified_manual_fallback_requires_trustworthy_manifest(cfg, prepared, selector, tmp_path, damage):
    from ag.locks import claim
    path, manifest = prepared
    claim(path / '.submit-claim')
    state.write(path, 'submitting')
    state.write(path, 'unknown')
    target = path / 'manifest.json'
    if damage == 'symlink':
        external = tmp_path / 'redirected-manifest.json'
        external.write_bytes(target.read_bytes())
        target.unlink()
        target.symlink_to(external)
    else:
        key, value = {
            'identity': ('study_id', 'other'), 'bundle': ('bundle_sha256', 'f' * 64),
            'zero_cores': ('cores', 0), 'bool_cores': ('cores', True), 'string_cores': ('cores', '8'),
            'invalid_mem': ('mem_gb', -1), 'scheduler': ('scheduler', 'slurm'),
            'cluster': ('cluster', 'unconfigured'),
        }[damage]
        manifest[key] = value
        target.write_text(json.dumps(manifest))
    before = tree(path.parent.parent)
    with pytest.raises((ValueError, OSError)):
        autonomy_submission.read_reservations(cfg)
    assert tree(path.parent.parent) == before


@pytest.mark.parametrize('terminal', ['interrupted', 'cancelled'])
def test_terminal_owned_usage_releases_only_after_two_fresh_absent_samples(
        cfg, prepared, selector, monkeypatch, terminal):
    from datetime import datetime, timezone
    from ag import autonomy, monitor
    path, _ = prepared
    saved, current, _ = bound_owned(cfg, path, selector[0], monkeypatch)
    state.write(path, terminal, scheduler_observed_at=1003)
    clock = [approval.timestamp(state.read(path)['updated_at']).timestamp() + 1]
    monkeypatch.setattr(autonomy, 'now', lambda: clock[0])
    cache = monitor.cache_dir(cfg)
    for index in range(2):
        sample = monitor.empty_snapshot(cfg, interval=60)
        stamp = datetime.fromtimestamp(clock[0], timezone.utc).isoformat()
        sample.update(sampled_at=stamp, ok=True, error=None, last_ok_at=stamp,
                      account_sha256=saved['record']['account_sha256'])
        sample['own']['jobs'] = []
        monitor.publish(cache, sample)
        result = autonomy_submission.read_reservations(cfg, states=supplied(path, current))
        assert result['placements'][0]['state'] == ('queued' if index == 0 else 'finished')
        clock[0] += 60
    assert state.read(path)['state'] == terminal
    assert len(current['submissions']) == 1


def publish_owned_absences(cfg, saved, monkeypatch):
    from datetime import datetime, timezone
    from ag import autonomy, monitor
    path = autonomy_submission._record_path(saved['record'])
    terminal = approval.timestamp(state.read(path)['updated_at']).timestamp()
    clock = [terminal + 61]
    monkeypatch.setattr(autonomy, 'now', lambda: clock[0])
    cache = monitor.cache_dir(cfg)
    for at in (terminal + 1, terminal + 61):
        sample = monitor.empty_snapshot(cfg, interval=60)
        stamp = datetime.fromtimestamp(at, timezone.utc).isoformat()
        sample.update(sampled_at=stamp, ok=True, error=None, last_ok_at=stamp,
                      account_sha256=saved['record']['account_sha256'])
        monitor.publish(cache, sample)
    return cache, clock


def test_absence_pair_belongs_to_latest_continuous_terminal_episode(cfg, prepared, selector, monkeypatch):
    from datetime import datetime, timezone
    from ag import autonomy, journal, monitor
    path, _ = prepared
    clock = [1002.0]
    stamp = lambda: datetime.fromtimestamp(clock[0], timezone.utc).isoformat()
    monkeypatch.setattr(autonomy, 'now', lambda: clock[0])
    monkeypatch.setattr(journal, 'now', stamp)
    saved, current, _ = bound_owned(cfg, path, selector[0], monkeypatch)
    cache = monitor.cache_dir(cfg)

    def sample(at):
        clock[0] = at
        value = monitor.empty_snapshot(cfg, interval=60)
        value.update(sampled_at=stamp(), ok=True, error=None, last_ok_at=stamp(),
                     account_sha256=saved['record']['account_sha256'])
        monitor.publish(cache, value)

    def placement():
        return autonomy_submission.read_reservations(cfg, states=supplied(path, current))['placements'][0]['state']

    # Fresh queue invisibility during submission is not evidence for a later stop.
    sample(1010)
    sample(1070)
    clock[0] = 1080
    state.write(path, 'interrupted', scheduler_observed_at=clock[0])
    assert placement() == 'queued'
    sample(1090)
    assert placement() == 'queued'
    sample(1150)
    assert placement() == 'finished'
    clock[0] = 1151
    state.write(path, 'interrupted', scheduler_observed_at=clock[0])
    assert placement() == 'finished'  # A synonymous status refresh preserves the episode.
    clock[0] = 1152
    state.write(path, 'running')
    clock[0] = 1153
    state.write(path, 'interrupted', scheduler_observed_at=clock[0])
    assert placement() == 'queued'
    sample(1160)
    assert placement() == 'queued'
    sample(1220)
    assert placement() == 'finished'


@pytest.mark.parametrize('damage', ['missing', 'failed', 'duplicate', 'stale', 'future',
                                  'missing_account', 'other_account', 'job', 'name', 'rotation', 'unknown'])
def test_terminal_accounting_never_infers_two_absences_from_partial_or_conflicting_cache(
        cfg, prepared, selector, monkeypatch, damage):
    path, _ = prepared
    saved, current, manifest = bound_owned(cfg, path, selector[0], monkeypatch)
    state.write(path, 'interrupted', scheduler_observed_at=1003)
    cache, clock = publish_owned_absences(cfg, saved, monkeypatch)
    previous, latest = cache / 'previous.json', cache / 'latest.json'
    value = json.loads(previous.read_text())
    if damage == 'missing':
        previous.unlink()
    elif damage == 'stale':
        clock[0] += 181
    elif damage == 'unknown':
        state.write(path, 'unknown')
    elif damage == 'rotation':
        read = autonomy_submission._read_file
        def rotate(target):
            raw = read(target)
            if Path(target) == previous:
                following = latest.read_bytes()
                latest.unlink()
                latest.write_bytes(following)
            return raw
        monkeypatch.setattr(autonomy_submission, '_read_file', rotate)
    else:
        if damage == 'failed':
            value.update(ok=False, error='Synthetic sampling failure')
        elif damage == 'duplicate':
            value['sampled_at'] = json.loads(latest.read_text())['sampled_at']
        elif damage == 'future':
            value['sampled_at'] = '2030-01-01T00:00:00+00:00'
        elif damage == 'missing_account':
            value.pop('account_sha256')
        elif damage == 'other_account':
            value['account_sha256'] = 'd' * 64
        else:
            value['own']['jobs'] = [dict(job_id='default:123.fixture' if damage == 'job' else 'default:999.fixture',
                name=manifest['pbs_job_name'] if damage == 'name' else 'another-job')]
        previous.write_text(json.dumps(value))
    result = autonomy_submission.read_reservations(cfg, states=supplied(path, current))
    assert result['placements'][0]['state'] == ('unknown' if damage == 'unknown' else 'queued')
    assert len(current['submissions']) == 1


@pytest.mark.parametrize('terminal', ['finished', 'fetched'])
def test_slurm_cancelled_accounting_still_requires_explicit_resolution_before_new_source(
        ordinary_slurm_owned_case, monkeypatch, terminal):
    from ag import autonomy
    cfg, path, current, saved = ordinary_slurm_owned_case()
    manifest = json.loads((path / 'manifest.json').read_text())
    submission.record(path, manifest, '123', authorization=saved['authorization'], autonomy_state=current)
    state.write(path, 'submitted', job_id='default:123')
    state.write(path, 'finished', exit_status=1, completion_source='sacct', scheduler_state='CANCELLED',
                exit_code=1, exit_signal=9, allocated_cpus=8, elapsed='00:01:00', scheduler_observed_at=1003)
    if terminal == 'fetched':
        state.write(path, 'fetched', exit_status=1)
    _, clock = publish_owned_absences(cfg, saved, monkeypatch)
    with pytest.raises(autonomy.ObjectRefused):
        autonomy_submission.prepare_remedy_evidence(cfg, current, 'water')
    prepared = autonomy_submission.prepare_resolution_evidence(cfg, current, path.name)
    data = autonomy_submission.verify_resolution_evidence(cfg, current, prepared)
    assert data['kind'] == 'cancelled'
    current['manual_resolutions'] = {path.name: dict(data, quote='Synthetic explicit cancellation resolution', at=clock[0])}
    source = autonomy_submission.prepare_remedy_evidence(cfg, current, 'water').evidence
    assert source['failure_class'] == 'interrupted'
    assert source['completion']['manual_resolution']['kind'] == 'cancelled'


@pytest.fixture
def actual_unknown_resolution(cfg, prepared, selector, monkeypatch):
    from ag import autonomy
    from ag.locks import claim
    from test_autonomy import VERSIONS, spec
    path, manifest = prepared
    clock = [1000.0]
    monkeypatch.setattr(autonomy, 'now', lambda: clock[0])
    monkeypatch.setattr(autonomy, 'versions', lambda: deepcopy(VERSIONS))
    autonomy.initialize(cfg, 'smoke')
    plan = autonomy.create_plan(cfg, 'smoke', spec())
    autonomy.confirm(cfg, 'smoke', plan['plan_id'], plan['sha256'], 'Synthetic confirmed plan')
    begun = autonomy.begin(cfg, 'smoke', plan['plan_id'], 'Synthetic confirmed round')
    run = autonomy.start(cfg, 'smoke', plan['plan_id'], 'fixture-owner')
    context = reservation_context(cfg, path, selector[0], round_id=begun['state']['current_round'],
        run_id=run['run_id'], plan_sha256=plan['sha256'],
        selection=selection_for(cfg, path, selector[0], round_id=begun['state']['current_round'], run_id=run['run_id']))
    with autonomy_submission.machine_lock(), autonomy.submission_guard(cfg, 'smoke', run['run_id'], run['token'],
                                                                       plan_sha256=plan['sha256']) as guard:
        saved = autonomy_submission.write_reservation(cfg, path, context, verified_state=guard.snapshot)
        claim(path / '.submit-claim')
        approval.archive(path, saved['authorization'], saved['record']['summary'])
        guard.consume(saved['consume'])
        guard.dispatch_started(path.name)
    state.write(path, 'submitting')
    clock[0] += 1
    negative = dict(schema='ag-unknown-observation/1', observed_at=clock[0], scheduler='pbs',
                    job_name=manifest['pbs_job_name'], matches=[], start_absent=True,
                    account_sha256=saved['record']['account_sha256'])
    state.write(path, 'unknown', unknown_reconciliation=negative)
    autonomy.pause(cfg, 'smoke', 'Synthetic unknown submission')
    return cfg, path, manifest, saved, clock, negative


@pytest.mark.parametrize('later', ['same_negative', 'cleared', 'start_present', 'binding'])
def test_actual_unknown_resolution_survives_only_equivalent_fresh_observation(actual_unknown_resolution, later):
    from ag import autonomy
    cfg, path, manifest, saved, clock, negative = actual_unknown_resolution
    before = tree(path)
    result = autonomy.resolve_attempt(cfg, 'smoke', path.name, '  Synthetic explicit human resolution.\n')
    current = result['state']
    row = current['manual_resolutions'][path.name]
    assert row['quote'] == '  Synthetic explicit human resolution.\n'
    assert current['phase'] == 'paused' and len(current['submissions']) == 1
    assert tree(path) == before
    first = autonomy_submission.prepare_remedy_evidence(cfg, current, 'water').evidence
    assert first['failure_class'] is None and first['completion']['manual_resolution'] == row
    assert first['source_attempt'] == path.name
    clock[0] += 1
    if later == 'binding':
        submission.record(path, manifest, '123.fixture', authorization=saved['authorization'], autonomy_state=current)
        state.write(path, 'submitted', job_id='default:123.fixture')
    else:
        updated = (None if later == 'cleared' else
                   dict(negative, observed_at=clock[0], start_absent=later != 'start_present'))
        state.write(path, 'unknown', unknown_reconciliation=updated)
    if later == 'same_negative':
        refreshed = autonomy_submission.prepare_remedy_evidence(cfg, current, 'water').evidence
        assert refreshed['status_sha256'] != first['status_sha256']
        assert refreshed['completion']['manual_resolution'] == row
        assert refreshed['failure_class'] is None
    else:
        with pytest.raises(autonomy.ObjectRefused):
            autonomy_submission.prepare_remedy_evidence(cfg, current, 'water')
    assert len(autonomy.status(cfg, 'smoke')['state']['submissions']) == 1
    assert (path / '.submit-claim').read_bytes() == before['.submit-claim']


@pytest.mark.parametrize('account', [None, 'd' * 64])
def test_unknown_resolution_requires_current_account_bound_negative(actual_unknown_resolution, account):
    from ag import autonomy
    cfg, path, _, _, _, negative = actual_unknown_resolution
    changed = deepcopy(negative)
    if account is None:
        changed.pop('account_sha256')
    else:
        changed['account_sha256'] = account
    state.write(path, 'unknown', unknown_reconciliation=changed)
    before = tree(path.parent.parent)
    with pytest.raises(ValueError) as error:
        autonomy.resolve_attempt(cfg, 'smoke', path.name, 'Synthetic explicit human resolution.')
    assert isinstance(error.value, autonomy.ObjectRefused) is (account is None)
    assert not autonomy.status(cfg, 'smoke')['state'].get('manual_resolutions')
    assert tree(path.parent.parent) == before


@pytest.mark.parametrize('damage', ['status', 'expired', 'consumption', 'blank_quote'])
def test_human_resolution_rechecks_metadata_time_and_exact_consumption(actual_unknown_resolution, damage):
    from ag import autonomy
    cfg, path, _, _, clock, _ = actual_unknown_resolution
    current = autonomy.status(cfg, 'smoke')['state']
    before = tree(path.parent.parent)
    prepared = autonomy_submission.prepare_resolution_evidence(cfg, current, path.name)
    if damage == 'status':
        target = path / 'status.json'
        raw = target.read_bytes()
        target.unlink()
        target.write_bytes(raw)
    elif damage == 'expired':
        clock[0] += 601
    elif damage == 'consumption':
        current['submissions'][path.name]['ownership_sha256'] = 'd' * 64
    else:
        with pytest.raises(ValueError):
            autonomy.resolve_attempt(cfg, 'smoke', path.name, ' \n')
        assert tree(path.parent.parent) == before
        return
    with pytest.raises(ValueError):
        autonomy_submission.verify_resolution_evidence(cfg, current, prepared)
    assert not autonomy.status(cfg, 'smoke')['state'].get('manual_resolutions')


@pytest.mark.parametrize('start_at,log_at,first_at,expected', [
    pytest.param(1000, 2690, 2700, 'walltime', id='log-near-walltime'),
    pytest.param(1000, 1100, 4000, 'interrupted', id='early-crash-observed-late'),
    pytest.param(None, 2690, 4000, 'interrupted', id='missing-start'),
    pytest.param(1000, 2200, 4000, 'walltime', id='ten-minute-boundary'),
    pytest.param(1000, 2199, 4000, 'interrupted', id='before-ten-minute-boundary'),
    pytest.param(1000, '1970-01-01 08:36:40.000000000 +0800', 4000, 'walltime', id='explicit-offset'),
    pytest.param(1000, '1970-99-01 00:44:50.000000000 +0000', 4000, 'interrupted', id='invalid-calendar'),
    pytest.param(1000, 4001, 4000, 'interrupted', id='future-log-mtime'),
    pytest.param(1000, 999, 4000, 'interrupted', id='log-before-start'),
    pytest.param(1000, None, 4000, 'interrupted', id='missing-log'),
])
def test_formal_pbs_interrupted_fetch_supports_bounded_failure(
        cfg, prepared, selector, monkeypatch, start_at, log_at, first_at, expected):
    from datetime import datetime, timezone
    from ag import fetch, remote, status
    from test_incomplete_fetch import IncompleteFake
    path, _ = prepared
    _, current, manifest = bound_owned(cfg, path, selector[0], monkeypatch)
    mtime = (log_at if isinstance(log_at, str) else
             datetime.fromtimestamp(log_at or 0, timezone.utc).strftime('%Y-%m-%d %H:%M:%S.000000000 %z'))
    monkeypatch.setattr('test_incomplete_fetch.MTIME', mtime)
    fake = IncompleteFake(manifest, files={} if log_at is None else None)
    outputs = status.outputs(cfg, manifest, fake)
    observations = [dict(at=at, job_id='123.fixture', scheduler_state=None, outputs=outputs, exit_receipt=None)
                    for at in (first_at, first_at + 300)]
    start = (None if start_at is None else dict(PBS_JOBID='123.fixture',
             started_at=datetime.fromtimestamp(start_at, timezone.utc).isoformat()))
    state.write(path, 'interrupted', observation={'job_id': '123.fixture'},
        receipts={'start': start, 'exit': None}, incomplete_observations=observations,
        scheduler_observed_at=first_at + 300)
    monkeypatch.setattr(status.time, 'time', lambda: first_at + 301)
    fetched = fetch.fetch(cfg, path, fake, incomplete=True)
    source = autonomy_submission.prepare_remedy_evidence(cfg, current, 'water')
    evidence = autonomy_submission.verify_remedy_evidence(cfg, current, 'water', source)
    assert evidence['failure_class'] == expected
    assert evidence['completion']['source'] == 'interrupted'
    assert evidence['completion']['incomplete_fetch']['record'] == fetched['record']
    assert not any(command.operation in ('submit', 'cancel') for command in fake.calls)
    assert state.read(path)['state'] == 'interrupted'


@pytest.mark.parametrize('legacy_bridge', [False, True])
def test_presubmit_chain_preserves_scientific_class_through_prepare_verify_and_refresh(
        cfg, prepared, selector, tmp_path, monkeypatch, legacy_bridge):
    from ag import attempt, journal
    from ag.locks import claim
    path, _ = prepared
    _, current, manifest = bound_owned(cfg, path, selector[0], monkeypatch)
    finish_owned(path, manifest, '-----\n# B3LYP/6-31G(d) Opt\n-----\nConvergence failure\nError termination\n')
    ancestor = None
    for index in range(2 if legacy_bridge else 1):
        child = attempt.prepare(cfg, study_name='smoke', template='gaussian', input_path=tmp_path / 'water.gjf',
            tier='simple', walltime='00:30:00', label='aborted-' + str(index), method_basis='Synthetic retry')
        target = attempt.find(cfg, child['attempt_id'])
        prepared_source = autonomy_submission.prepare_remedy_evidence(cfg, current, 'water')
        source = deepcopy(prepared_source.evidence)
        # Reproduce the old persisted presubmit bridge. The live API below
        # still validates every ordinary write using its real source receipt.
        if index:
            source['failure_class'] = 'presubmit'
        context = reservation_context(cfg, target, selector[0],
            failure_class=source['failure_class'], remedy_source=source)
        with monkeypatch.context() as old_version:
            if index:
                old_version.setattr(autonomy_submission, 'verify_remedy_evidence', lambda *a, **k: deepcopy(source))
            saved = autonomy_submission.write_reservation(cfg, target, context, verified_state=current,
                                                           prepared_remedy=prepared_source)
        claim(target / '.submit-claim')
        approval.archive(target, saved['authorization'], saved['record']['summary'])
        at = 1004 + index * 3
        current['submissions'][target.name] = dict(saved['consume'], plan_id='plan-one', at=at,
            dispatch_started=None, aborted_before_dispatch={'at': at + 1, 'reason': 'Synthetic upload failure'})
        state.write(target, 'submitting')
        state.write(target, 'failed_presubmit')
        ancestor, path = path, target
    evidence = autonomy_submission.prepare_remedy_evidence(cfg, current, 'water')
    checked = autonomy_submission.verify_remedy_evidence(cfg, current, 'water', evidence)
    assert checked['source_attempt'] == path.name and checked['failure_class'] == 'gaussian-scf'
    journal.append(path.parent.parent, 'state', 'smoke-099-another', 'prepared')
    refreshed = autonomy_submission.refresh_remedy_evidence(cfg, current, 'water', evidence)
    assert autonomy_submission.verify_remedy_evidence(cfg, current, 'water', refreshed) == checked
    if legacy_bridge:
        status_path = ancestor / 'status.json'
        raw = status_path.read_bytes()
        status_path.unlink()
        status_path.write_bytes(raw)
        with pytest.raises(ValueError, match='Evidence file changed'):
            autonomy_submission.verify_remedy_evidence(cfg, current, 'water', refreshed)


@pytest.mark.parametrize('cause,expected', [
    ('Convergence failure', 'gaussian-scf'),
    ('Number of steps exceeded', 'gaussian-opt-steps'),
    ('Maximum number of corrector steps exceeded', 'gaussian-irc-corrector'),
    ('Wrong number of Negative eigenvalues', 'gaussian-ts-curvature'),
    ('Unclassified synthetic failure', 'gaussian-error'),
])
def test_remedy_class_comes_from_failed_fetched_section(cfg, prepared, selector, monkeypatch, cause, expected):
    path, _ = prepared
    saved, current, manifest = bound_owned(cfg, path, selector[0], monkeypatch)
    text = '-----\n# B3LYP/6-31G(d) Opt\n-----\n' + cause + '\nError termination\n'
    finish_owned(path, manifest, text)
    result = autonomy_submission.remedy_evidence(cfg, current, 'water')
    assert result['failure_class'] == expected
    assert result['source_attempt'] == path.name
    assert result['source_ownership_sha256'] == saved['sha256']
    assert result['outputs'][0]['sha256']
    assert autonomy_submission.remedy_evidence(cfg, current, 'other') is None
    assert autonomy_submission.remedy_evidence(cfg, current, 'water', exclude_attempt=path.name) is None
    assert autonomy_submission.read_reservations(cfg, states=supplied(path, current))['placements'][0]['state'] == 'finished'


@pytest.mark.parametrize('damage', ['unknown', 'finished', 'success', 'later_job', 'receipt_job', 'missing_fetch', 'facts_conflict'])
def test_remedy_rejects_uncertain_successful_or_conflicting_source(cfg, prepared, selector, monkeypatch, damage):
    from ag import journal
    path, _ = prepared
    _, current, manifest = bound_owned(cfg, path, selector[0], monkeypatch)
    if damage == 'unknown':
        state.write(path, 'unknown')
    elif damage == 'finished':
        state.write(path, 'finished')
    else:
        text = '-----\n# B3LYP/6-31G(d) Opt\n-----\nConvergence failure\nError termination\n'
        if damage == 'success':
            text = '-----\n# B3LYP/6-31G(d) Opt\n-----\nNormal termination of Gaussian\n'
        if damage == 'later_job':
            text += '\nEntering Gaussian System\n-----\n# B3LYP/6-31G(d) SP\n-----\nIncomplete later job\n'
        finish_owned(path, manifest, text)
        if damage == 'receipt_job':
            value = state.read(path)
            value['receipts']['exit']['PBS_JOBID'] = '124.fixture'
            (path / 'status.json').write_text(json.dumps(value))
        if damage == 'missing_fetch':
            target = path.parent.parent / 'journal.jsonl'
            events = [json.loads(line) for line in target.read_text().splitlines()]
            target.write_text(''.join(json.dumps(event) + '\n' for event in events if event['action'] != 'fetch'))
        if damage == 'facts_conflict':
            journal.append(path.parent.parent, 'facts', path.name, 'auto', {'status': 'conflict'})
    with pytest.raises(ValueError):
        autonomy_submission.remedy_evidence(cfg, current, 'water')


def test_remedy_abort_is_canonical_and_cannot_be_omitted(cfg, prepared, selector):
    path, _ = prepared
    saved, current = install_owned(cfg, path, selector[0])
    current['submissions'][path.name]['aborted_before_dispatch'] = {'at': 1002, 'reason': 'No dispatch began'}
    source = autonomy_submission.remedy_evidence(cfg, current, 'water')
    assert source['failure_class'] == 'presubmit'
    assert not source['outputs']
    prepared_source = autonomy_submission.prepare_remedy_evidence(cfg, current, 'water')
    with pytest.raises(ValueError, match='Remedy source differs'):
        autonomy_submission.write_reservation(cfg, path, reservation_context(cfg, path, selector[0]),
            verified_state=current, prepared_remedy=prepared_source)
    value = reservation_context(cfg, path, selector[0], failure_class='renamed', remedy_source=source)
    with pytest.raises(ValueError, match='Unsupported remedy failure class'):
        autonomy_submission.write_reservation(cfg, path, value, verified_state=current)


def test_remedy_source_frozen_into_next_attempt_and_tampering_refused(cfg, prepared, selector, tmp_path):
    from ag import attempt
    path, _ = prepared
    saved, current = install_owned(cfg, path, selector[0])
    current['submissions'][path.name]['aborted_before_dispatch'] = {'at': 1002, 'reason': 'No dispatch began'}
    source = autonomy_submission.remedy_evidence(cfg, current, 'water')
    manifest = attempt.prepare(cfg, study_name='smoke', template='gaussian', input_path=tmp_path / 'water.gjf',
        tier='simple', walltime='00:30:00', label='remedy', method_basis='Synthetic water method')
    next_path = attempt.find(cfg, manifest['attempt_id'])
    prepared_source = autonomy_submission.prepare_remedy_evidence(cfg, current, 'water')
    context = reservation_context(cfg, next_path, selector[0], failure_class='presubmit', remedy_source=source)
    context['remedy_source']['status_sha256'] = 'e' * 64
    with pytest.raises(ValueError, match='Remedy source differs'):
        autonomy_submission.write_reservation(cfg, next_path, context, verified_state=current,
                                             prepared_remedy=prepared_source)
    context['remedy_source'] = autonomy_submission.remedy_evidence(cfg, current, 'water')
    next_saved = autonomy_submission.write_reservation(cfg, next_path, context, verified_state=current,
                                                     prepared_remedy=prepared_source)
    assert next_saved['record']['remedy_source']['source_ownership_sha256'] == saved['sha256']
    assert next_saved['consume']['failure_class'] == 'presubmit'


def test_archived_summary_text_must_match_global_record(cfg, prepared, selector):
    path, _ = prepared
    _, current = install_owned(cfg, path, selector[0])
    target = path / 'submission-summary.json'
    value = json.loads(target.read_text())
    value['summary'] = 'Different method and bytes allegedly approved.'
    target.write_text(json.dumps(value))
    with pytest.raises(ValueError, match='Archived summary differs'):
        autonomy_submission.read_reservations(cfg, states=supplied(path, current))


@pytest.mark.parametrize('template', ['crest', 'xtb'])
@pytest.mark.parametrize('returncode', [0, 2])
def test_non_gaussian_remedy_requires_confirmed_nonzero_exit(cfg, prepared, selector, monkeypatch, tmp_path, returncode, template):
    from ag import attempt, autonomy
    xyz = tmp_path / 'water.xyz'
    xyz.write_text('3\nwater\nO 0 0 0\nH 0 0 1\nH 0 1 0\n')
    manifest = attempt.prepare(cfg, study_name='smoke', template=template, input_path=xyz,
        tier='simple', walltime='00:30:00', label=template, method_basis='Synthetic water method')
    path = attempt.find(cfg, manifest['attempt_id'])
    _, current, manifest = bound_owned(cfg, path, selector[0], monkeypatch)
    finish_owned(path, manifest, 'Synthetic program output\n', returncode=returncode)
    if returncode:
        source = autonomy_submission.remedy_evidence(cfg, current, 'water')
        assert source['failure_class'] == 'program-exit'
    else:
        with pytest.raises(autonomy.ObjectRefused, match='Successful program exit'):
            autonomy_submission.remedy_evidence(cfg, current, 'water')


@pytest.fixture
def t186_driver_factory(cfg, tmp_path, monkeypatch):
    """Actual T184/185/186 integration; only clock, config IO and transport fake."""
    from datetime import datetime, timezone
    from ag import attempt, autonomy, autonomy_policy, config, route, study
    from test_core import INPUT
    from test_autonomy import VERSIONS, spec
    from test_autonomy_policy import rule, ROUTE
    if not all(hasattr(route, name) for name in ('select_ladder', 'ladder_config_identity', '_ladder_usage')):
        pytest.skip('Requires the reviewed T185 selector in the T184/T185/T186 combination checkout')
    at = [datetime(2026, 10, 29, tzinfo=timezone.utc).timestamp()]
    monkeypatch.setattr(autonomy, 'now', lambda: at[0])
    monkeypatch.setattr(autonomy, 'versions', lambda: deepcopy(VERSIONS))
    monkeypatch.setattr(config, 'ssh_identity', lambda selected: ('fixture', 22, 'fixture'))
    configurations = {}
    def load(path=None, **kwargs):
        return deepcopy(configurations[str(Path(path).absolute())])
    monkeypatch.setattr(config, 'load_config', load)
    def create(name, *, relay_group=None):
        local = deepcopy(cfg)
        if relay_group is not None:
            local['relay_group'] = relay_group
        root = tmp_path / name
        root.mkdir()
        directory = root / 'config'
        directory.mkdir()
        local['_config_dir'] = str(directory)
        local['local']['studies_root'] = str(root / 'studies')
        local['resources'].update(max_committed_cores=128, max_walltime='12:00:00')
        local['routing'] = dict(gaussian=['default'], crest=['default'], ladder=[
            dict(id='small-default', cluster='default', tier='simple', classes=['main', 'small'],
                 condition='free', min_free_cores=8, max_placements=1)])
        config_path = directory / 'config.toml'
        config_path.write_text('Synthetic config parsed by a fixed local test loader\n')
        local['_config_path'] = str(config_path)
        configurations[str(config_path)] = local
        study.init(local, 'smoke')
        source = root / 'water.gjf'
        source.write_text(INPUT.replace('# B3LYP/6-31G(d) SP', ROUTE))
        manifest = attempt.prepare(local, study_name='smoke', template='gaussian', input_path=source,
            tier='simple', walltime='00:30:00', label='optfreq', method_basis='Synthetic fixture')
        path = attempt.find(local, manifest['attempt_id'])
        policy = rule(local)
        policy['routing_sha256'] = route.ladder_config_identity(local)
        policy['clusters']['default'].update(max_committed_cores=128, max_queued_cores=128, max_jobs=4)
        bounds = {key: deepcopy(policy[key]) for key in autonomy_policy.PLAN_BOUND_KEYS}
        autonomy.initialize(local, 'smoke')
        plan = autonomy.create_plan(local, 'smoke', spec(valid_until=at[0] + 86400, submission_policy=bounds))
        autonomy.confirm(local, 'smoke', plan['plan_id'], plan['sha256'], 'Synthetic plan confirmation')
        begun = autonomy.begin(local, 'smoke', plan['plan_id'], 'Synthetic round confirmation')
        run = autonomy.start(local, 'smoke', plan['plan_id'], 'fixture-session')
        policy.update(round_id=begun['state']['current_round'], plan_sha256=plan['sha256'])
        local['approval'] = {'autonomous_policies': {'bounded': policy}}
        snapshot = dict(schema='ag-monitor/1', ok=True, error=None, warnings=[],
            sampled_at=datetime.fromtimestamp(at[0], timezone.utc).isoformat(), interval_seconds=60,
            last_ok_at=datetime.fromtimestamp(at[0], timezone.utc).isoformat(),
            own=dict(cores_in_use=0, core_cap=local['resources']['max_cores'],
                     cores_running=0, cores_queued=0, jobs=[]),
            cluster=dict(name='default', scheduler='pbs', job_summary=dict(others_queued_jobs=0),
                cores_total=44, cores_used=0, queues=[],
                nodes=[dict(name='fixture-node', cores_total=44, cores_used=0, cores_idle=44, cores_other=0,
                    mem_total_bytes=120 * 1024**3, mem_assigned_bytes=0, jobs=0, state='free',
                    capacity_cpu_consistent=True, targeting_consistent=True, targeting_reserved=False)]))
        cache = Path(local['local']['studies_root']) / '.ag-monitor'
        cache.mkdir()
        (cache / 'latest.json').write_text(json.dumps(snapshot))
        context = dict(policy_name='bounded', run_id=run['run_id'], token=run['token'],
                       plan_sha256=plan['sha256'], object_id='water', job_class='small')
        return local, path, manifest, context, at, policy
    return create


@pytest.fixture
def t186_driver(t186_driver_factory):
    return t186_driver_factory('driver')


def test_driver_claim_dispatch_and_late_binding(t186_driver):
    from ag import autonomy
    cfg, path, manifest, context, at, policy = t186_driver
    fake = Fake(cfg)
    result = submit.submit(cfg, [path.name], fake, autonomous=context)
    assert result[0]['state'] == 'submitted'
    assert fake.operations().count('submit') == 1
    consumed = autonomy.status(cfg, 'smoke')['state']['submissions'][path.name]
    assert consumed['dispatch_started'] is not None
    with autonomy_submission.machine_lock(create=False):
        records = autonomy_submission.read_reservations(cfg)
    assert len(records['records']) == len(records['placements']) == 1
    assert records['placements'][0]['run_id'] == context['run_id']
    assert json.loads((path / 'submission.json').read_text())['authorization']['method'] == 'autonomy-policy'
    with pytest.raises(ValueError):
        submit.submit(cfg, [path.name], fake, autonomous=context)
    assert fake.operations().count('submit') == 1


@pytest.mark.parametrize('operation', ['prepare', 'submit'])
def test_driver_link_failure_blocks_before_claim_or_remote_io(t186_driver_factory, operation):
    from ag import attempt, autonomy
    cfg, path, manifest, context, _, _ = t186_driver_factory('link-refused', relay_group='bridge')
    cache = Path(cfg['local']['studies_root']) / '.ag-monitor' / 'latest.json'
    sample = json.loads(cache.read_text())
    sample.update(ok=False, error='Synthetic link failure')
    cache.write_text(json.dumps(sample))
    before = sorted(item.name for item in path.parent.iterdir())
    fake = Fake(cfg)
    with pytest.raises(autonomy.PresubmitDeferred):
        if operation == 'submit':
            submit.submit(cfg, [path.name], fake, autonomous=context)
        else:
            attempt.prepare(cfg, study_name='smoke', template='gaussian',
                input_path=Path(cfg['local']['studies_root']).parent / 'water.gjf',
                tier='simple', walltime='00:30:00', label='link-wait',
                method_basis='Synthetic fixture', autonomous=context, transport=fake)
    current = autonomy.status(cfg, 'smoke')['state']
    assert not current['paused'] and not current.get('submissions')
    assert not current.get('presubmit_failures')
    assert not (path / '.submit-claim').exists()
    assert state.read(path)['state'] == 'prepared'
    assert sorted(item.name for item in path.parent.iterdir()) == before
    assert fake.operations() == []


def test_driver_link_failure_during_upload_retains_consumption_without_dispatch(t186_driver_factory):
    from ag import autonomy
    cfg, path, _, context, _, _ = t186_driver_factory('link-upload', relay_group='bridge')
    cache = Path(cfg['local']['studies_root']) / '.ag-monitor' / 'latest.json'
    class LoseLink(Fake):
        def upload(self, local, manifest, name):
            super().upload(local, manifest, name)
            sample = json.loads(cache.read_text())
            sample.update(ok=False, error='Synthetic link failure')
            cache.write_text(json.dumps(sample))
    fake = LoseLink(cfg)
    with pytest.raises(autonomy.PresubmitDeferred):
        submit.submit(cfg, [path.name], fake, autonomous=context)
    current = autonomy.status(cfg, 'smoke')['state']
    consumed = current['submissions'][path.name]
    assert not current['paused']
    assert len(current['submissions']) == 1
    assert consumed['aborted_before_dispatch'] is not None
    assert consumed['dispatch_started'] is None
    assert (path / '.submit-claim').exists()
    assert state.read(path)['state'] == 'failed_presubmit'
    assert fake.operations().count('upload') == 1
    assert 'submit' not in fake.operations()
    with pytest.raises(ValueError, match='already consumed'):
        submit.submit(cfg, [path.name], fake, autonomous=context)
    assert fake.operations().count('upload') == 1


def test_driver_pause_during_upload_stops_before_next_remote_effect(t186_driver):
    from ag import autonomy
    cfg, path, manifest, context, at, policy = t186_driver
    class PauseUpload(Fake):
        def upload(self, local, manifest, name):
            super().upload(local, manifest, name)
            autonomy.pause(cfg, 'smoke', 'Synthetic pause during upload')
    fake = PauseUpload(cfg)
    with pytest.raises(ValueError, match='paused'):
        submit.submit(cfg, [path.name], fake, autonomous=context)
    assert fake.operations().count('upload') == 1
    assert 'submit' not in fake.operations()
    row = autonomy.status(cfg, 'smoke')['state']['submissions'][path.name]
    assert row['dispatch_started'] is None
    assert row['aborted_before_dispatch'] is not None


def test_driver_unknown_never_releases_or_retries(t186_driver):
    from ag import autonomy
    cfg, path, manifest, context, at, policy = t186_driver
    fake = Fake(cfg)
    fake.qsub = Result(255, '', 'Synthetic lost reply')
    with pytest.raises(submit.UnknownSubmission):
        submit.submit(cfg, [path.name], fake, autonomous=context)
    assert state.read(path)['state'] == 'unknown'
    row = autonomy.status(cfg, 'smoke')['state']['submissions'][path.name]
    assert row['dispatch_started'] and row['aborted_before_dispatch'] is None
    with autonomy_submission.machine_lock(create=False):
        assert autonomy_submission.read_reservations(cfg)['placements'][0]['state'] == 'unknown'
    with pytest.raises(ValueError):
        submit.submit(cfg, [path.name], fake, autonomous=context)
    assert fake.operations().count('submit') == 1


def test_driver_expiry_during_upload_refuses_dispatch(t186_driver):
    from datetime import datetime, timezone
    cfg, path, manifest, context, at, policy = t186_driver
    class ExpireUpload(Fake):
        def upload(self, local, manifest, name):
            super().upload(local, manifest, name)
            policy['expires_at'] = datetime.fromtimestamp(at[0] + 1, timezone.utc).isoformat()
            at[0] += 2
    fake = ExpireUpload(cfg)
    with pytest.raises(ValueError):
        submit.submit(cfg, [path.name], fake, autonomous=context)
    assert fake.operations().count('upload') == 1 and 'submit' not in fake.operations()


def test_driver_fresh_inventory_enforces_stricter_policy(t186_driver):
    cfg, path, manifest, context, at, policy = t186_driver
    policy['clusters']['default'].update(max_committed_cores=32, max_queued_cores=32)
    fake = Fake(cfg)
    fake.qstat = Result(stdout='Job Id: 77.fixture\n    Job_Name = outside\n'
        '    Job_Owner = fixture@fixture\n    job_state = R\n    Resource_List.nodes = 1:ppn=40\n')
    with pytest.raises(ValueError, match='autonomous limit'):
        submit.submit(cfg, [path.name], fake, autonomous=context)
    assert not {'create_attempt', 'upload', 'submit'} & set(fake.operations())
    assert not (path / '.submit-claim').exists()


def test_driver_cross_root_competitors_reserve_only_fourth_global_job(t186_driver_factory):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from ag import autonomy
    previous = [t186_driver_factory('previous-' + str(index)) for index in range(3)]
    for index, (cfg, path, manifest, context, at, policy) in enumerate(previous):
        fake = Fake(cfg)
        fake.qsub = Result(stdout=str(100 + index) + '.fixture\n')
        assert submit.submit(cfg, [path.name], fake, autonomous=context)[0]['state'] == 'submitted'
        # Ending a round does not release jobs missing from later readback.
        autonomy.change(cfg, 'smoke', 'end', context['run_id'], context['token'],
            round_id=policy['round_id'], reason='Synthetic ended authorization round')
    contenders = [t186_driver_factory('contender-' + str(index)) for index in range(2)]
    barrier = Barrier(2, timeout=15)
    class SimultaneousInventory(Fake):
        def run(self, command):
            if command.operation == 'identity' and not getattr(self, 'initial_inventory_seen', False):
                self.initial_inventory_seen = True
                # Reaching inventory means the actual submit preflight and
                # first guarded T186 policy/routing check already passed.
                with autonomy_submission.machine_lock(create=False):
                    observed = autonomy_submission.read_reservations(self.cfg)
                assert len(observed['placements']) == 3
                assert len({p['study_key'] for p in observed['placements']}) == 3
                barrier.wait()
            return super().run(command)
    fakes = [SimultaneousInventory(case[0]) for case in contenders]
    for index, fake in enumerate(fakes):
        fake.qsub = Result(stdout=str(200 + index) + '.fixture\n')
    def run(index):
        cfg, path, _, context, _, _ = contenders[index]
        try:
            result = submit.submit(cfg, [path.name], fakes[index], autonomous=context)
        except ValueError as exc:
            return ('refused', str(exc))
        return ('submitted', result[0]['state'])
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, range(2)))
    assert sorted(result[0] for result in results) == ['refused', 'submitted']
    assert all(fake.initial_inventory_seen for fake in fakes)
    winner = next(index for index, result in enumerate(results) if result[0] == 'submitted')
    loser = 1 - winner
    assert 'autonomous limit' in results[loser][1]
    assert fakes[winner].operations().count('submit') == 1
    assert not {'create_attempt', 'upload', 'submit'} & set(fakes[loser].operations())
    loser_cfg, loser_path, _, _, _, _ = contenders[loser]
    assert not (loser_path / '.submit-claim').exists()
    assert not autonomy.status(loser_cfg, 'smoke')['state'].get('submissions')
    with autonomy_submission.machine_lock(create=False):
        evidence = autonomy_submission.read_reservations(loser_cfg)
    assert len(evidence['records']) == len(evidence['placements']) == 4
    assert len({row['study_key'] for row in evidence['placements']}) == 4
    assert sum(fake.operations().count('submit') for fake in fakes) == 1


def test_two_actual_presubmit_failures_reject_before_another_attempt(t186_driver):
    from ag import attempt, autonomy
    from ag.transport import TransportError
    cfg, path, manifest, context, at, policy = t186_driver
    source = Path(cfg['local']['studies_root']).parent / 'water.gjf'
    for index in range(2):
        if index:
            manifest = attempt.prepare(cfg, study_name='smoke', template='gaussian', input_path=source,
                tier='simple', walltime='00:30:00', label='retry' + str(index),
                method_basis='Synthetic fixture', autonomous=context)
            path = attempt.find(cfg, manifest['attempt_id'])
        fake = Fake(cfg)
        fake.fail = 'create_attempt'
        with pytest.raises(TransportError):
            submit.submit(cfg, [path.name], fake, autonomous=context)
        current = autonomy.status(cfg, 'smoke')['state']
        row = current['submissions'][path.name]
        assert row['failure_class'] == (None if index == 0 else 'presubmit')
        assert row['aborted_before_dispatch'] is not None
        assert 'submit' not in fake.operations()
        assert current['phase'] == ('running' if index == 0 else 'paused')
        at[0] += 1
        finished = autonomy.change(cfg, 'smoke', 'finish', context['run_id'], context['token'], reason='Synthetic wake finish')
        run = autonomy.start(cfg, 'smoke', finished['state']['current_plan'], 'fixture-next-wake')
        context.update(run_id=run['run_id'], token=run['token'])
    autonomy.change(cfg, 'smoke', 'resume', context['run_id'], context['token'], reason='Synthetic explicit resume')
    registry = Path.home() / '.config/ag/autonomy-reservations'
    before = tree(registry)
    attempts_before = sorted(item.name for item in path.parent.iterdir())
    with pytest.raises(autonomy.ObjectRefused, match='two actual presubmit failures'):
        attempt.prepare(cfg, study_name='smoke', template='gaussian', input_path=source,
            tier='simple', walltime='00:30:00', label='retry3', method_basis='Synthetic fixture', autonomous=context)
    assert sorted(item.name for item in path.parent.iterdir()) == attempts_before
    assert tree(registry) == before
    with autonomy_submission.machine_lock(create=False):
        evidence = autonomy_submission.read_reservations(cfg)
    assert len(evidence['records']) == 2
    assert evidence['placements'] == []


@pytest.fixture
def t186_observation_owner(cfg, prepared, monkeypatch):
    """Real T184 publication guard, independent of the T185 combination."""
    from contextlib import contextmanager
    from ag import autonomy
    from test_autonomy import VERSIONS, spec
    path, manifest = prepared
    clock = [1000.0]
    monkeypatch.setattr(autonomy, 'now', lambda: clock[0])
    monkeypatch.setattr(autonomy, 'versions', lambda: deepcopy(VERSIONS))
    autonomy.initialize(cfg, 'smoke')
    plan = autonomy.create_plan(cfg, 'smoke', spec())
    autonomy.confirm(cfg, 'smoke', plan['plan_id'], plan['sha256'], 'Synthetic observation plan')
    autonomy.begin(cfg, 'smoke', plan['plan_id'], 'Synthetic observation round')
    run = autonomy.start(cfg, 'smoke', plan['plan_id'], 'observer-one')
    locked = [False]
    def factory(action='fetch'):
        @contextmanager
        def publish():
            with autonomy.observation_publication_guard(cfg, 'smoke', run['run_id'], run['token'],
                    action=action, plan_sha256=plan['sha256']) as current:
                assert not locked[0]
                locked[0] = True
                try:
                    yield current
                finally:
                    locked[0] = False
        return publish
    def lose(kind):
        assert not locked[0], 'Downloads and parsing must stay outside the publication guard'
        if clock[0] != 1000:
            return
        clock[0] += 3601 if kind == 'expired' else 5401
        if kind == 'takeover':
            autonomy.start(cfg, 'smoke', plan['plan_id'], 'observer-two',
                           takeover_reason='Synthetic stale-owner handover')
    return cfg, path, manifest, clock, locked, factory, lose


@pytest.mark.parametrize('loss', ['expired', 'takeover'])
@pytest.mark.parametrize('mode', ['ordinary', 'add_missing', 'incomplete'])
def test_fetch_publication_refuses_owner_lost_during_download(t186_observation_owner, monkeypatch, loss, mode):
    from ag import autonomy, fetch, remote
    from test_core import finish, seed_submission
    from test_fetch import ReadOnlyFake
    from test_incomplete_fetch import IncompleteFake, MTIME
    cfg, path, manifest, clock, locked, factory, lose = t186_observation_owner
    if mode == 'incomplete':
        state.write(path, 'submitting')
        seed_submission(path)
        fake = IncompleteFake(manifest)
        observed = {name: (dict(size=len(fake.files[name]), mtime=MTIME) if name in fake.files else None)
                    for name in remote.output_names(manifest)}
        evidence = [dict(at=at, job_id='123.fixture', scheduler_state=None,
                         outputs=observed, exit_receipt=None) for at in (100, 400)]
        state.write(path, 'interrupted', incomplete_observations=evidence)
        monkeypatch.setattr(fetch.time, 'time', lambda: clock[0])
    else:
        finish(path)
        fake = ReadOnlyFake({'water.log': b'Synthetic complete log', 'job.pbs.out': b'Synthetic scheduler output'})
        if mode == 'add_missing':
            (path / 'outputs/water.log').write_bytes(fake.files['water.log'])
            state.write(path, 'fetched', exit_status=0)
    before_status = (path / 'status.json').read_bytes()
    before_files = {p.name: p.read_bytes() for p in (path / 'outputs').iterdir() if p.is_file()}
    fake.after_download = lambda: lose(loss)
    original_run = fake.run
    def outside_guard(command):
        assert not locked[0], 'Remote metadata must stay outside the publication guard'
        return original_run(command)
    fake.run = outside_guard
    with pytest.raises(autonomy.PublicationRefused):
        fetch.fetch(cfg, path, fake, add_missing=mode == 'add_missing', incomplete=mode == 'incomplete',
                    publication=factory())
    assert fake.downloaded
    assert (path / 'status.json').read_bytes() == before_status
    assert {p.name: p.read_bytes() for p in (path / 'outputs').iterdir() if p.is_file()} == before_files
    assert not list(path.glob('fetch-add-missing-*.json'))
    assert not list(path.glob('fetch-incomplete-*.json'))
    events = [json.loads(line) for line in (path.parent.parent / 'journal.jsonl').read_text().splitlines()]
    assert not [e for e in events if e['action'] == 'fetch' and e['result'] == 'ok']
    if mode == 'ordinary':
        assert fake.record_paths == []


@pytest.mark.parametrize('loss', ['expired', 'takeover'])
@pytest.mark.parametrize('refresh', [False, True])
def test_facts_publication_refuses_owner_lost_during_parse(t186_observation_owner, monkeypatch, loss, refresh):
    from ag import autonomy, facts
    cfg, path, manifest, clock, locked, factory, lose = t186_observation_owner
    previous = b'{"schema":"ag-facts/1","energy":-74}\n'
    if refresh:
        (path / 'facts.json').write_bytes(previous)
    def parse(directory):
        assert not locked[0]
        lose(loss)
        return {'schema': 'ag-facts/1', 'energy': -75}, {'final.xyz': '1\nSynthetic\nH 0 0 0\n'}
    monkeypatch.setattr(facts, 'parse_facts', parse)
    monkeypatch.setattr(facts, 'ag_provenance', lambda: {})
    with pytest.raises(autonomy.PublicationRefused):
        facts.build_facts(path, refresh=refresh, publication=factory('organize'))
    assert not (path / 'final.xyz').exists()
    assert not list(path.glob('facts.*.json'))
    if refresh:
        assert (path / 'facts.json').read_bytes() == previous
    else:
        assert not (path / 'facts.json').exists()


@pytest.mark.parametrize('loss', ['expired', 'takeover'])
@pytest.mark.parametrize('outcome', ['error', 'dependency', 'conflict', 'skip', 'publication'])
def test_auto_facts_never_swallows_owner_loss_or_writes_error_journal(t186_observation_owner, monkeypatch, loss, outcome):
    from ag import autonomy, facts, fetch
    cfg, path, manifest, clock, locked, factory, lose = t186_observation_owner
    before = (path.parent.parent / 'journal.jsonl').read_bytes()
    def parse(directory):
        lose(loss)
        error = {'error': ValueError, 'dependency': ImportError, 'conflict': facts.FactsConflictError,
                 'publication': autonomy.PublicationRefused}[outcome]
        raise error('Synthetic parse interruption')
    monkeypatch.setattr(facts, 'parse_facts', parse)
    if outcome == 'skip':
        lose(loss)
    with pytest.raises(autonomy.PublicationRefused):
        fetch.auto_facts(path, skip='Synthetic explicit skip' if outcome == 'skip' else None,
                         publication=factory('organize'))
    assert (path.parent.parent / 'journal.jsonl').read_bytes() == before
    assert not (path / 'facts.json').exists()


def test_current_observer_publishes_fetch_and_facts_only_inside_guard(t186_observation_owner, monkeypatch):
    from ag import facts, fetch, journal
    from test_core import finish
    from test_fetch import ReadOnlyFake
    cfg, path, manifest, clock, locked, factory, lose = t186_observation_owner
    finish(path)
    fake = ReadOnlyFake({'water.log': b'Synthetic complete log', 'job.pbs.out': b'Synthetic scheduler output'})
    original_append = journal.append
    writes = []
    def append(root, action, attempt_id=None, result='ok', detail=None):
        assert locked[0], 'Every fetch/facts journal publication must hold its guard'
        writes.append((action, result))
        return original_append(root, action, attempt_id, result, detail)
    monkeypatch.setattr(journal, 'append', append)
    fake.after_download = lambda: pytest.fail('Download must be outside guard') if locked[0] else None
    assert fetch.fetch(cfg, path, fake, publication=factory())['state'] == 'fetched'
    def parse(directory):
        assert not locked[0]
        return {'schema': 'ag-facts/1', 'termination': 'normal'}, {'final.xyz': '1\nSynthetic\nH 0 0 0\n'}
    monkeypatch.setattr(facts, 'parse_facts', parse)
    monkeypatch.setattr(facts, 'ag_provenance', lambda: {})
    assert fetch.auto_facts(path, publication=factory('organize'))['status'] == 'written'
    assert (path / 'facts.json').is_file() and (path / 'final.xyz').is_file()
    assert writes == [('fetch', 'requested'), ('state', 'fetched'), ('fetch', 'ok'), ('facts', 'auto')]


@pytest.mark.parametrize('transition', ['submitting', 'submitted', 'failed_presubmit', 'unknown'])
def test_driver_status_and_journal_publish_as_one_global_audit(t186_driver, monkeypatch, transition):
    import threading
    from ag import journal
    from ag.transport import TransportError
    cfg, path, manifest, context, at, policy = t186_driver
    original = journal.append
    observations, workers = [], []
    attempted, completed = threading.Event(), threading.Event()
    def read_global():
        attempted.set()
        try:
            with autonomy_submission.machine_lock(create=False):
                observations.append(autonomy_submission.read_reservations(cfg))
        except BaseException as exc:
            observations.append(exc)
        finally:
            completed.set()
    def intercept(root, action, attempt_id=None, result='ok', detail=None):
        if action == 'state' and attempt_id == path.name and result == transition and not workers:
            worker = threading.Thread(target=read_global)
            workers.append(worker)
            worker.start()
            assert attempted.wait(3)
            # status.json is already replaced, but its journal append has not
            # happened. A separate reader must wait at the common mutex.
            assert not completed.wait(0.1)
        return original(root, action, attempt_id, result, detail)
    monkeypatch.setattr(journal, 'append', intercept)
    fake = Fake(cfg)
    if transition == 'failed_presubmit':
        fake.fail = 'create_attempt'
        expected = TransportError
    elif transition == 'unknown':
        fake.qsub = Result(255, '', 'Synthetic lost reply')
        expected = submit.UnknownSubmission
    else:
        expected = None
    if expected is None:
        submit.submit(cfg, [path.name], fake, autonomous=context)
    else:
        with pytest.raises(expected):
            submit.submit(cfg, [path.name], fake, autonomous=context)
    assert len(workers) == 1
    workers[0].join(3)
    assert completed.is_set()
    assert observations and not any(isinstance(row, BaseException) for row in observations), observations


def test_driver_network_never_holds_machine_mutex_or_writes_attempt_callbacks(t186_driver):
    import threading
    cfg, path, manifest, context, at, policy = t186_driver
    class UnlockedNetwork(Fake):
        def record_to(self, paths):
            assert paths == []
            self.recorded_paths = paths
        def check_unlocked(self):
            acquired = threading.Event()
            def take():
                with autonomy_submission.machine_lock(create=False):
                    acquired.set()
            worker = threading.Thread(target=take)
            worker.start()
            available = acquired.wait(3)
            worker.join(3)
            assert available, 'Network IO must not hold the all-study mutex'
        def run(self, command):
            self.check_unlocked()
            return super().run(command)
        def upload(self, local, manifest, name):
            self.check_unlocked()
            return super().upload(local, manifest, name)
    fake = UnlockedNetwork(cfg)
    assert submit.submit(cfg, [path.name], fake, autonomous=context)[0]['state'] == 'submitted'
    assert fake.recorded_paths == []


@pytest.fixture
def scientific_review_case(cfg, selector, tmp_path, monkeypatch):
    """Real reservation/consume/review publication with synthetic parsed facts."""
    from ag import attempt, autonomy, facts, journal, mode_review, remote, study
    from ag.locks import claim
    from test_core import INPUT
    from test_autonomy import VERSIONS, spec
    clock = [1000.0]
    monkeypatch.setattr(autonomy, 'now', lambda: clock[0])
    monkeypatch.setattr(autonomy, 'versions', lambda: deepcopy(VERSIONS))
    def create(outcome='ts_zero_imaginary', *, scheduler='pbs', terminal='TIMEOUT'):
        if scheduler == 'slurm':
            cfg.update(scheduler='slurm', partition='fixture')
        study.init(cfg, 'smoke')
        source = tmp_path / 'water.gjf'
        route = '# B3LYP/6-31G(d) Opt=(TS,Tight) Freq Int=UltraFine SCF=(XQC,Conver=8)'
        source.write_text(INPUT.replace('# B3LYP/6-31G(d) SP', route))
        manifest = attempt.prepare(cfg, study_name='smoke', template='gaussian', input_path=source,
            tier='simple', walltime='00:30:00', label='ts', method_basis='Synthetic TS fixture')
        path = attempt.find(cfg, manifest['attempt_id'])
        autonomy.initialize(cfg, 'smoke')
        plan = autonomy.create_plan(cfg, 'smoke', spec())
        autonomy.confirm(cfg, 'smoke', plan['plan_id'], plan['sha256'], 'Synthetic plan confirmation')
        begun = autonomy.begin(cfg, 'smoke', plan['plan_id'], 'Synthetic round confirmation')
        run = autonomy.start(cfg, 'smoke', plan['plan_id'], 'scientific-reviewer')
        round_id = begun['state']['current_round']
        selected = selection_for(cfg, path, selector[0], round_id=round_id, run_id=run['run_id'])
        context = reservation_context(cfg, path, selector[0], selection=selected, round_id=round_id,
            run_id=run['run_id'], plan_sha256=plan['sha256'])
        with autonomy_submission.machine_lock(), autonomy.submission_guard(cfg, 'smoke', run['run_id'], run['token'],
                plan_sha256=plan['sha256']) as guard:
            saved = autonomy_submission.write_reservation(cfg, path, context, verified_state=guard.snapshot)
            claim(path / '.submit-claim')
            approval.archive(path, saved['authorization'], context['summary'])
            guard.consume(saved['consume'])
            state.write(path, 'submitting')
            guard.dispatch_started(path.name)
        job = '123' if scheduler == 'slurm' else '123.fixture'
        submission.record(path, manifest, job, authorization=saved['authorization'])
        state.write(path, 'submitted', job_id='default:' + job)
        if scheduler == 'slurm':
            state.write(path, 'finished', exit_status=1, completion_source='sacct', scheduler_state=terminal,
                exit_code=1, exit_signal=0, allocated_cpus=8, elapsed='00:30:00', scheduler_observed_at=1001)
        else:
            state.write(path, 'finished', exit_status=0, completion_source='ag-exit.json',
                receipts={'exit': dict(PBS_JOBID=job, returncode=0, finished_at='2026-01-01T00:00:00+00:00')},
                observation={'job_id': job}, scheduler_observed_at=1001)
        log = '-----\n' + route + '\n-----\nSynthetic frequency calculation\nNormal termination of Gaussian\n'
        for name in remote.output_names(manifest):
            (path / 'outputs' / name).write_text(log if name.endswith('.log') else 'Synthetic scheduler output\n')
        state.write(path, 'fetched', exit_status=1 if scheduler == 'slurm' else 0)
        journal.append(path.parent.parent, 'fetch', path.name, detail={'files': remote.output_names(manifest)})
        frequencies = [-20.0, 100.0, 300.0] if outcome == 'ts_wrong_mode' else [20.0, 100.0, 300.0]
        parsed = dict(schema='ag-facts/1', program='gaussian', termination='normal',
            n_imag=1 if outcome == 'ts_wrong_mode' else 0, vibrational_modes_complete=True,
            n_vibrational_modes=3, expected_vibrational_modes=3, frequencies_low=frequencies)
        monkeypatch.setattr(facts, 'parse_facts', lambda directory: (deepcopy(parsed), {}))
        monkeypatch.setattr(facts, 'ag_provenance', lambda: {})
        facts.build_facts(path)
        mode_path = None
        if outcome == 'ts_wrong_mode':
            frame = (['O', 'H', 'H'], [[0, 0, 0], [0, 0, 1], [0, 1, 0]], frequencies,
                     [[[0, 0, 0], [0.1, 0, 0], [0, 0.1, 0]]] * 3, 'standard')
            monkeypatch.setattr(mode_review, 'read_modes', lambda block: frame)
            mode_path = 'analyses/mode.json'
            mode_review.create(path.name, path.parent.parent, [(1, 2)], mode_path,
                               run_id=run['run_id'], token=run['token'], plan_sha256=plan['sha256'])
        arguments = dict(run_id=run['run_id'], token=run['token'], plan_sha256=plan['sha256'], object_id='water',
            outcome=outcome, reason='Synthetic model judgment; pending human confirmation.', mode_review=mode_path)
        return cfg, path, manifest, arguments, parsed, clock
    return create


@pytest.mark.parametrize('outcome', ['ts_zero_imaginary', 'ts_wrong_mode'])
def test_normal_ts_review_is_bound_pending_and_uses_same_failure_class(scientific_review_case, outcome):
    cfg, path, manifest, arguments, parsed, clock = scientific_review_case(outcome)
    saved = autonomy_submission.write_scientific_review(cfg, path, **arguments)
    current = autonomy_submission._load_state(path.parent.parent, {})
    source = autonomy_submission.remedy_evidence(cfg, current, 'water')
    assert source['failure_class'] == saved['failure_class'] == 'gaussian-ts-curvature'
    review = source['completion']['scientific_review']
    assert review['sha256'] == saved['sha256']
    assert review['outcome'] == outcome and review['reason'] == arguments['reason']
    assert review['scientific_judgment'] == 'pending_human_confirmation'
    with pytest.raises(FileExistsError):
        autonomy_submission.write_scientific_review(cfg, path, **arguments)


@pytest.mark.parametrize('damage', ['facts', 'mode', 'geometry', 'review', 'log'])
def test_scientific_remedy_rejects_changed_source_bytes(scientific_review_case, damage):
    cfg, path, manifest, arguments, parsed, clock = scientific_review_case('ts_wrong_mode')
    autonomy_submission.write_scientific_review(cfg, path, **arguments)
    target = {'facts': path / 'facts.json', 'mode': path.parent.parent / 'analyses/mode.json',
              'geometry': path.parent.parent / 'analyses/mode.plus.xyz',
              'review': path / 'autonomy-scientific-review.json', 'log': path / 'outputs/water.log'}[damage]
    with target.open('ab') as handle:
        handle.write(b'\nChanged synthetic source\n')
    current = autonomy_submission._load_state(path.parent.parent, {})
    with pytest.raises((ValueError, KeyError)):
        autonomy_submission.remedy_evidence(cfg, current, 'water')


@pytest.mark.parametrize('damage', ['object', 'reason', 'missing_mode', 'wrong_mode_source', 'stale_facts', 'expired'])
def test_scientific_review_refuses_invalid_binding_before_exclusive_write(scientific_review_case, monkeypatch, damage):
    from ag import facts
    cfg, path, manifest, arguments, parsed, clock = scientific_review_case('ts_wrong_mode')
    if damage == 'object':
        arguments['object_id'] = 'invented-object'
    elif damage == 'reason':
        arguments['reason'] = '  '
    elif damage == 'missing_mode':
        arguments['mode_review'] = None
    elif damage == 'wrong_mode_source':
        target = path.parent.parent / arguments['mode_review']
        value = json.loads(target.read_text())
        value['source']['log_sha256'] = 'f' * 64
        target.write_text(json.dumps(value))
    elif damage == 'stale_facts':
        monkeypatch.setattr(facts, 'parse_facts', lambda directory: (dict(parsed, n_imag=2), {}))
    else:
        clock[0] += 3601
    with pytest.raises(ValueError):
        autonomy_submission.write_scientific_review(cfg, path, **arguments)
    assert not (path / 'autonomy-scientific-review.json').exists()


def test_walltime_uses_exact_terminal_accounting_not_model_or_log_hint(scientific_review_case):
    cfg, path, manifest, arguments, parsed, clock = scientific_review_case(scheduler='slurm')
    # A truncated program log is admissible only because the exact scheduler
    # has confirmed TIMEOUT and ordinary fetch supplied all declared outputs.
    (path / 'outputs/water.log').write_text('Synthetic incomplete calculation\n')
    current = autonomy_submission._load_state(path.parent.parent, {})
    source = autonomy_submission.remedy_evidence(cfg, current, 'water')
    assert source['failure_class'] == 'walltime'
    assert source['completion']['source'] == 'sacct' and source['completion']['scheduler_state'] == 'TIMEOUT'
    status_value = state.read(path)
    status_value['scheduler_state'] = 'RUNNING'
    (path / 'status.json').write_text(json.dumps(status_value))
    with pytest.raises(ValueError, match='terminal accounting'):
        autonomy_submission.remedy_evidence(cfg, current, 'water')


def test_walltime_words_in_completed_pbs_output_do_not_authorize_retry(scientific_review_case):
    from ag import autonomy
    cfg, path, manifest, arguments, parsed, clock = scientific_review_case()
    (path / 'outputs/job.pbs.out').write_text('Synthetic walltime limit exceeded hint\n')
    current = autonomy_submission._load_state(path.parent.parent, {})
    with pytest.raises(autonomy.ObjectRefused, match='immutable scientific review'):
        autonomy_submission.remedy_evidence(cfg, current, 'water')


@pytest.mark.parametrize('order', [
    ['smoke-1000', 'smoke-998', 'smoke-999'],
    ['smoke-999', 'smoke-1000', 'smoke-998'],
])
def test_latest_object_consumption_uses_time_across_attempt_sequence_width(order):
    rows = {name: dict(attempt_id=name, at=float(name.split('-')[1])) for name in order}
    assert autonomy_submission._latest_object_consumption(list(rows.values()))['attempt_id'] == 'smoke-1000'
    rows['smoke-998']['at'] = 1000.0
    with pytest.raises(ValueError, match='Ambiguous latest object consumption'):
        autonomy_submission._latest_object_consumption(list(rows.values()))


@pytest.mark.parametrize('other_time', [999.0, 1000.0, 1001.0])
def test_scientific_review_checks_unique_latest_consumption_before_publication(
        scientific_review_case, monkeypatch, other_time):
    from contextlib import contextmanager
    from ag import autonomy
    cfg, path, manifest, arguments, parsed, clock = scientific_review_case()
    original = autonomy.observation_publication_guard
    @contextmanager
    def reordered_guard(*args, **kwargs):
        with original(*args, **kwargs) as current:
            # JSON key order and Attempt labels are not consumption chronology.
            row = deepcopy(current['submissions'][path.name])
            row.update(attempt_id='smoke-999', at=other_time)
            current['submissions']['smoke-999'] = row
            yield current
    monkeypatch.setattr(autonomy, 'observation_publication_guard', reordered_guard)
    if other_time < 1000.0:
        autonomy_submission.write_scientific_review(cfg, path, **arguments)
        assert (path / 'autonomy-scientific-review.json').exists()
    else:
        with pytest.raises(ValueError, match='Ambiguous latest|latest actual Attempt'):
            autonomy_submission.write_scientific_review(cfg, path, **arguments)
        assert not (path / 'autonomy-scientific-review.json').exists()


@pytest.mark.parametrize('mode', ['success', 'copy-failure', 'lease-expired'])
def test_parent_checkpoint_journal_has_fresh_publication_guard(t186_driver, monkeypatch, mode):
    from contextlib import contextmanager
    from datetime import datetime, timezone
    from hashlib import sha256
    import shlex
    from ag import attempt, autonomy, journal, status
    from ag.transport import TransportError
    from test_core import INPUT, job_text
    from test_autonomy_policy import ROUTE
    cfg, parent_path, parent, context, at, policy = t186_driver
    submit.submit(cfg, [parent_path.name], Fake(cfg), autonomous=context)
    class Completed(Fake):
        def run(self, command):
            if command.operation == 'receipt' and 'ag-exit.json' in command.text:
                return Result(stdout=json.dumps(dict(PBS_JOBID='123.fixture', returncode=0,
                    finished_at=datetime.fromtimestamp(at[0], timezone.utc).isoformat())))
            return super().run(command)
    completed = Completed(cfg)
    completed.job = Result(stdout=job_text(parent))
    def parent_publication():
        return autonomy.observation_publication_guard(cfg, 'smoke', context['run_id'], context['token'],
            action='observe', plan_sha256=context['plan_sha256'])
    assert status.check(cfg, parent_path, completed, publication=parent_publication)['state'] == 'finished'
    plan_id = autonomy.status(cfg, 'smoke')['state']['current_plan']
    autonomy.change(cfg, 'smoke', 'finish', context['run_id'], context['token'], reason='Synthetic next wake')
    at[0] += 1
    new = autonomy.start(cfg, 'smoke', plan_id, 'checkpoint-session')
    context = dict(context, run_id=new['run_id'], token=new['token'], object_id='child-water')
    source = Path(cfg['local']['studies_root']).parent / 'child.gjf'
    source.write_text('%oldchk=parent.chk\n' + INPUT.replace('# B3LYP/6-31G(d) SP', ROUTE + ' Guess=Read'))
    child = attempt.prepare(cfg, study_name='smoke', template='gaussian', input_path=source,
        tier='simple', walltime='00:30:00', label='child', method_basis='Synthetic checkpoint validation',
        parents=[dict(attempt_id=parent_path.name, relation='from_parent')],
        parent_chk=parent_path.name + ':water.chk', autonomous=context)
    path = attempt.find(cfg, child['attempt_id'])
    held = [False]
    actual_publication = submit.AutonomousSubmission.publication
    @contextmanager
    def publication(self):
        with actual_publication(self) as value:
            held[0] = True
            try:
                yield value
            finally:
                held[0] = False
    monkeypatch.setattr(submit.AutonomousSubmission, 'publication', publication)
    original_append = journal.append
    events = []
    def append(root, action, attempt_id=None, result='ok', detail=None):
        if action == 'copy_parent_chk':
            assert held[0]
            events.append(result)
        return original_append(root, action, attempt_id, result, detail)
    monkeypatch.setattr(journal, 'append', append)
    class Checkpoint(Fake):
        def run(self, command):
            assert not held[0], 'Checkpoint network operations must stay outside publication guard'
            if command.operation == 'parent_chk_metadata':
                self.calls.append(command)
                name = shlex.split(command.text)[-2]
                raw = b'synthetic checkpoint'
                return Result(stdout=f'{len(raw)}\n{sha256(raw).hexdigest()}  {name}\n')
            if command.operation == 'copy_parent_chk':
                self.calls.append(command)
                if mode == 'lease-expired':
                    at[0] += 3601
                if mode == 'copy-failure':
                    return Result(1, '', 'Synthetic copy refusal')
                return Result()
            return super().run(command)
    fake = Checkpoint(cfg)
    fake.qsub = Result(stdout='124.fixture\n')
    if mode == 'success':
        assert submit.submit(cfg, [path.name], fake, autonomous=context)[0]['state'] == 'submitted'
        assert events == ['started', 'verified']
        assert fake.operations().count('submit') == 1
    else:
        expected = autonomy.PublicationRefused if mode == 'lease-expired' else TransportError
        with pytest.raises(expected):
            submit.submit(cfg, [path.name], fake, autonomous=context)
        assert events == (['started', 'failed_presubmit'] if mode == 'copy-failure' else ['started'])
        assert 'upload' not in fake.operations() and 'submit' not in fake.operations()
        assert state.read(path)['state'] == 'failed_presubmit'


def test_scientific_review_hashing_and_section_parsing_stay_outside_publication(scientific_review_case, monkeypatch):
    from contextlib import contextmanager
    from ag import autonomy, mode_review
    cfg, path, manifest, arguments, parsed, clock = scientific_review_case('ts_wrong_mode')
    held, calls = [False], []
    original_guard = autonomy.observation_publication_guard
    @contextmanager
    def guard(*args, **kwargs):
        with original_guard(*args, **kwargs) as current:
            held[0] = True
            try:
                yield current
            finally:
                held[0] = False
    monkeypatch.setattr(autonomy, 'observation_publication_guard', guard)
    for module, name in ((autonomy_submission, '_fetched_outputs'),
                         (autonomy_submission, '_owned_audit'),
                         (mode_review, 'frequency_section')):
        original = getattr(module, name)
        def checked(*args, _name=name, _original=original, **kwargs):
            assert not held[0], _name + ' must remain outside publication'
            calls.append(_name)
            return _original(*args, **kwargs)
        monkeypatch.setattr(module, name, checked)
    autonomy_submission.write_scientific_review(cfg, path, **arguments)
    assert calls.count('_fetched_outputs') == calls.count('frequency_section') == 1


@pytest.mark.parametrize('damage', ['bytes_restore_mtime', 'replace_inode', 'facts', 'global_record'])
def test_scientific_publication_metadata_refuses_changes_after_parsing(scientific_review_case, monkeypatch, damage):
    from contextlib import contextmanager
    import os
    from ag import autonomy
    cfg, path, manifest, arguments, parsed, clock = scientific_review_case()
    original_guard = autonomy.observation_publication_guard
    @contextmanager
    def guard(*args, **kwargs):
        with original_guard(*args, **kwargs) as current:
            if damage == 'global_record':
                target = Path.home() / '.config/ag/autonomy-reservations' / autonomy_submission._filename(path)
            else:
                target = path / ('facts.json' if damage == 'facts' else 'outputs/water.log')
            before, raw = target.stat(), target.read_bytes()
            if damage == 'replace_inode':
                target.unlink()
                target.write_bytes(raw)
            else:
                target.write_bytes(b'X' + raw[1:])
            os.utime(target, ns=(before.st_atime_ns, before.st_mtime_ns))
            yield current
    monkeypatch.setattr(autonomy, 'observation_publication_guard', guard)
    with pytest.raises(ValueError, match='Evidence .* changed'):
        autonomy_submission.write_scientific_review(cfg, path, **arguments)
    assert not (path / 'autonomy-scientific-review.json').exists()


def test_remedy_receipt_refresh_reuses_heavy_evidence_and_only_accepts_proven_append(scientific_review_case, monkeypatch):
    from ag import journal
    cfg, path, manifest, arguments, parsed, clock = scientific_review_case()
    autonomy_submission.write_scientific_review(cfg, path, **arguments)
    current = autonomy_submission._load_state(path.parent.parent, {})
    prepared = autonomy_submission.prepare_remedy_evidence(cfg, current, 'water')
    expected = autonomy_submission.verify_remedy_evidence(cfg, current, 'water', prepared)
    def forbidden(*args, **kwargs):
        raise AssertionError('Cached remedy must not reread or parse heavy evidence')
    for name in ('_fetched_outputs', '_scientific_material', '_manifest_bytes', '_owned_audit'):
        monkeypatch.setattr(autonomy_submission, name, forbidden)
    journal.append(path.parent.parent, 'state', 'smoke-002-next', 'prepared')
    with pytest.raises(ValueError, match='Evidence file changed'):
        autonomy_submission.verify_remedy_evidence(cfg, current, 'water', prepared)
    refreshed = autonomy_submission.refresh_remedy_evidence(cfg, current, 'water', prepared)
    assert autonomy_submission.verify_remedy_evidence(cfg, current, 'water', refreshed) == expected
    journal.append(path.parent.parent, 'status', path.name, 'query', 'fetched')
    refreshed = autonomy_submission.refresh_remedy_evidence(cfg, current, 'water', refreshed)
    assert autonomy_submission.verify_remedy_evidence(cfg, current, 'water', refreshed) == expected


@pytest.mark.parametrize('damage', ['old_prefix', 'facts_conflict', 'log_restore_mtime',
                                  'status', 'source_state', 'latest_consumption', 'truncated_append'])
def test_remedy_receipt_refresh_rejects_changed_source(scientific_review_case, damage):
    import os
    from ag import journal
    cfg, path, manifest, arguments, parsed, clock = scientific_review_case()
    autonomy_submission.write_scientific_review(cfg, path, **arguments)
    current = autonomy_submission._load_state(path.parent.parent, {})
    prepared = autonomy_submission.prepare_remedy_evidence(cfg, current, 'water')
    log = path.parent.parent / 'journal.jsonl'
    if damage == 'old_prefix':
        raw = log.read_bytes()
        log.write_bytes(raw.replace(b'prepared', b'replaced', 1))
    elif damage == 'facts_conflict':
        journal.append(path.parent.parent, 'facts', path.name, 'auto', {'status': 'conflict'})
    elif damage == 'source_state':
        journal.append(path.parent.parent, 'state', path.name, 'running')
    elif damage == 'truncated_append':
        with log.open('ab') as stream:
            stream.write(b'{"action":')
    elif damage == 'latest_consumption':
        row = deepcopy(current['submissions'][path.name])
        row.update(attempt_id='smoke-002-next', at=row['at'] + 1)
        current['submissions'][row['attempt_id']] = row
    else:
        target = path / ('status.json' if damage == 'status' else 'outputs/water.log')
        before, raw = target.stat(), target.read_bytes()
        target.write_bytes(b'X' + raw[1:])
        os.utime(target, ns=(before.st_atime_ns, before.st_mtime_ns))
    with pytest.raises(ValueError):
        autonomy_submission.refresh_remedy_evidence(cfg, current, 'water', prepared)


def test_initial_remedy_receipt_cannot_ignore_new_history(cfg, prepared, selector):
    path, manifest = prepared
    empty = dict(current_round='round-one', submissions={})
    receipt = autonomy_submission.prepare_remedy_evidence(cfg, empty, 'water')
    assert autonomy_submission.verify_remedy_evidence(cfg, empty, 'water', receipt) is None
    saved, current = install_owned(cfg, path, selector[0])
    with pytest.raises(ValueError, match='Latest actual remedy consumption changed'):
        autonomy_submission.verify_remedy_evidence(cfg, current, 'water', receipt)
    with pytest.raises(ValueError, match='prepared outside the submission lock'):
        autonomy_submission.verify_remedy_evidence(cfg, current, 'water', None)



@pytest.fixture
def ordinary_slurm_owned_case(cfg, selector, tmp_path, monkeypatch):
    """Existing ordinary Slurm binding; no version probe or cancellation APIs."""
    from ag import attempt, study
    from test_core import INPUT
    def create():
        cfg.update(scheduler='slurm', partition='fixture')
        study.init(cfg, 'smoke')
        source = tmp_path / 'water.gjf'
        source.write_text(INPUT)
        manifest = attempt.prepare(cfg, study_name='smoke', template='gaussian', input_path=source,
            tier='simple', walltime='00:30:00', label='sp', method_basis='Synthetic ordinary Slurm fixture')
        path = attempt.find(cfg, manifest['attempt_id'])
        saved, current = install_owned(cfg, path, selector[0])
        current['submissions'][path.name]['dispatch_started'] = {'at': 1001.0}
        monkeypatch.setattr(autonomy_submission, '_load_state', lambda root, supplied: deepcopy(current))
        state.write(path, 'submitting')
        return cfg, path, current, saved
    return create

@pytest.fixture
def incomplete_remedy_case(ordinary_slurm_owned_case, monkeypatch):
    from ag import fetch, status
    from test_incomplete_fetch import IncompleteFake
    def create(*, scheduler_state='TIMEOUT', files=None, exit_code=1, exit_signal=9):
        cfg, path, current, saved = ordinary_slurm_owned_case()
        manifest = json.loads((path / 'manifest.json').read_text())
        submission.record(path, manifest, '123', authorization=saved['authorization'], autonomy_state=current)
        state.write(path, 'submitted', job_id='default:123')
        state.write(path, 'finished', exit_status=exit_code, completion_source='sacct',
                    scheduler_state=scheduler_state, exit_code=exit_code, exit_signal=exit_signal,
                    allocated_cpus=8, elapsed='00:05:00', scheduler_observed_at=1001.0)
        monkeypatch.setattr(status.time, 'time', lambda: 1002.0)
        fake = IncompleteFake(manifest, files=files)
        fake.accounting_state = scheduler_state
        fake.accounting = Result(stdout=f"123|{path.name}|fixture|{scheduler_state}|{exit_code}:{exit_signal}|00:05:00|8\n")
        result = fetch.fetch(cfg, path, fake, incomplete=True)
        assert state.read(path)['state'] == 'finished'
        return cfg, path, current, saved, result
    return create


@pytest.mark.parametrize('scheduler_state,files,expected', [
    ('TIMEOUT', None, 'walltime'), ('TIMEOUT', {}, 'walltime'),
    ('FAILED', {}, 'program-exit'),
    ('FAILED', {'water.log': b'-----\n# B3LYP/6-31G(d) Opt\n-----\nConvergence failure\nError termination\n'}, 'gaussian-scf'),
])
def test_formal_incomplete_fetch_is_a_bounded_terminal_remedy(incomplete_remedy_case, scheduler_state, files, expected):
    from hashlib import sha256
    cfg, path, current, saved, result = incomplete_remedy_case(scheduler_state=scheduler_state, files=files)
    prepared = autonomy_submission.prepare_remedy_evidence(cfg, current, 'water')
    evidence = autonomy_submission.verify_remedy_evidence(cfg, current, 'water', prepared)
    assert evidence['failure_class'] == expected
    assert evidence['source_ownership_sha256'] == saved['sha256']
    reference = evidence['completion']['incomplete_fetch']
    assert reference['record'] == result['record']
    assert reference['sha256'] == sha256((path / result['record']).read_bytes()).hexdigest()
    assert reference['receipt']['missing'] == result['missing']


@pytest.mark.parametrize('damage', ['job', 'state', 'time', 'missing', 'output', 'receipt_symlink'])
def test_incomplete_remedy_requires_receipt_stop_target_and_bytes(incomplete_remedy_case, damage):
    cfg, path, current, saved, result = incomplete_remedy_case()
    target = path / result['record']
    value = json.loads(target.read_text())
    if damage == 'job':
        value['end_evidence']['accounting']['job_id'] = '456'
    elif damage == 'state':
        value['end_evidence']['accounting']['state'] = 'RUNNING'
    elif damage == 'time':
        value['end_evidence']['at'] = 999.0
    elif damage == 'missing':
        value['missing'] = []
    elif damage == 'output':
        (path / 'outputs/water.log').write_bytes(b'Changed synthetic bytes\n')
    else:
        target.unlink()
        other = path / 'alternate-incomplete.json'
        other.write_text(json.dumps(value))
        target.symlink_to(other)
    if damage not in ('output', 'receipt_symlink'):
        target.write_text(json.dumps(value))
    with pytest.raises((ValueError, OSError)):
        autonomy_submission.prepare_remedy_evidence(cfg, current, 'water')


def test_incomplete_success_does_not_become_a_failure(incomplete_remedy_case):
    cfg, path, current, saved, result = incomplete_remedy_case(
        scheduler_state='COMPLETED', files={}, exit_code=0, exit_signal=0)
    with pytest.raises(ValueError, match='does not prove program failure'):
        autonomy_submission.prepare_remedy_evidence(cfg, current, 'water')


def test_incomplete_receipt_is_hashed_once_before_short_lock(incomplete_remedy_case, monkeypatch):
    from ag import fetch
    cfg, path, current, saved, result = incomplete_remedy_case()
    prepared = autonomy_submission.prepare_remedy_evidence(cfg, current, 'water')
    monkeypatch.setattr(fetch, 'incomplete_record', lambda *a, **k: pytest.fail('Receipt rehashed inside short lock'))
    monkeypatch.setattr(autonomy_submission, '_published_bytes', lambda *a, **k: pytest.fail('Output read inside short lock'))
    assert autonomy_submission.verify_remedy_evidence(cfg, current, 'water', prepared)['failure_class'] == 'walltime'
    (path / 'outputs/water.log').write_bytes(b'Changed synthetic bytes\n')
    with pytest.raises(ValueError, match='Evidence file changed'):
        autonomy_submission.verify_remedy_evidence(cfg, current, 'water', prepared)


@pytest.mark.parametrize('command', ['prepare', 'submit'])
def test_retired_reroute_cli_option_is_rejected_before_configuration(monkeypatch, capsys, command):
    from ag import cli
    monkeypatch.setattr(cli, 'load_config', lambda *a, **k: pytest.fail('Removed option must not read config'))
    arguments = (['submit', 'smoke-001-sp'] if command == 'submit' else
                 ['prepare', '--study', 'smoke', '--template', 'gaussian', '--input', 'water.gjf',
                  '--walltime', '00:30:00', '--label', 'sp', '--method-basis', 'Synthetic'])
    with pytest.raises(SystemExit) as error:
        cli.main([*arguments, '--reroute-source', 'smoke-000-old'])
    assert error.value.code == 2
    assert 'unrecognized arguments: --reroute-source' in capsys.readouterr().err


@pytest.mark.parametrize('entry', ['prepare', 'submit'])
def test_external_reroute_context_cannot_reopen_disabled_action(cfg, prepared, tmp_path, entry):
    from ag import attempt
    path, _ = prepared
    before = tree(path.parent.parent)
    fake = Fake(cfg)
    with pytest.raises(ValueError, match='需要你看.*Mac.*未启用'):
        if entry == 'submit':
            submit.submit(cfg, [path.name], fake, autonomous={'reroute_source': 'smoke-000-old'})
        else:
            attempt.prepare(cfg, study_name='smoke', template='gaussian', input_path=tmp_path / 'water.gjf',
                tier='simple', walltime='00:30:00', label='old-route', method_basis='Synthetic',
                autonomous={'reroute_source': 'smoke-000-old'})
    assert not fake.operations()
    assert tree(path.parent.parent) == before


@pytest.mark.parametrize('key', ['slurm_probe', 'reroute_source'])
def test_retired_reservation_context_cannot_consume(cfg, prepared, selector, key):
    path, _ = prepared
    value = reservation_context(cfg, path, selector[0], **{key: {}})
    before = tree(path.parent.parent)
    with pytest.raises(ValueError, match='Invalid reservation context'):
        autonomy_submission.write_reservation(cfg, path, value, verified_state={})
    assert tree(path.parent.parent) == before
    assert not (Path.home() / '.config/ag/autonomy-reservations').exists()


@pytest.mark.parametrize('key', ['slurm_probe', 'reroute_source'])
def test_retired_reservation_record_cannot_release_or_authorize_remedy(
        cfg, prepared, selector, monkeypatch, key):
    path, _ = prepared
    saved, current, manifest = bound_owned(cfg, path, selector[0], monkeypatch)
    finish_owned(path, manifest, 'Convergence failure\nError termination\n')
    target = reservation_path(saved)
    value = json.loads(target.read_text())
    value[key] = {'attempt_id': 'smoke-000-old'}
    target.write_text(json.dumps(value))
    before = target.read_bytes(), tree(path.parent.parent)
    with pytest.raises(ValueError, match='Invalid reservation record'):
        autonomy_submission.read_reservations(cfg, states=supplied(path, current))
    with pytest.raises(ValueError, match='Invalid reservation record'):
        autonomy_submission.prepare_remedy_evidence(cfg, current, 'water')
    assert (target.read_bytes(), tree(path.parent.parent)) == before


@pytest.mark.parametrize('legacy', ['reroute_source', 'slurm-origin-probe.json', '.cancel-claim',
                                  'autonomy-cancel-stopped.json'])
def test_old_prepared_reroute_or_cancel_evidence_cannot_be_submitted(t186_driver, legacy):
    from ag import autonomy
    cfg, path, _, context, _, _ = t186_driver
    if legacy == 'reroute_source':
        target = path / 'manifest.json'
        value = json.loads(target.read_text())
        value['reroute_source'] = {'attempt_id': 'smoke-000-old'}
        target.write_text(json.dumps(value))
    else:
        (path / legacy).write_bytes(b'Old disabled evidence, deliberately not parsed\n')
    before = tree(path)
    fake = Fake(cfg)
    with pytest.raises(ValueError, match='disabled|Cancelled Attempts|需要你看.*Mac.*未启用'):
        submit.submit(cfg, [path.name], fake, autonomous=context)
    assert not {'create_attempt', 'upload', 'submit'} & set(fake.operations())
    assert tree(path) == before
    current = autonomy.status(cfg, 'smoke')['state']
    assert not current.get('submissions')
    if legacy != 'reroute_source':
        assert current['phase'] == 'paused'


@pytest.mark.parametrize('legacy', ['cancellations', 'cancellation_results', '.cancel-claim',
                                  'autonomy-cancel-request.json', 'autonomy-cancel-response.json',
                                  'autonomy-cancel-stopped.json'])
@pytest.mark.parametrize('lifecycle', ['fetched', 'unknown'])
def test_old_cancellation_cannot_release_usage_or_authorize_failure_remedy(
        cfg, prepared, selector, monkeypatch, legacy, lifecycle):
    path, _ = prepared
    if lifecycle == 'fetched':
        _, current, manifest = bound_owned(cfg, path, selector[0], monkeypatch)
        finish_owned(path, manifest, '-----\n# B3LYP/6-31G(d) Opt\n-----\nConvergence failure\nError termination\n')
    else:
        _, current = install_owned(cfg, path, selector[0])
        manifest = json.loads((path / 'manifest.json').read_text())
        current['submissions'][path.name]['dispatch_started'] = {'at': 1002}
        monkeypatch.setattr(autonomy_submission, '_load_state', lambda root, supplied: current)
        state.write(path, 'submitting')
        state.write(path, 'unknown')
    if legacy in ('cancellations', 'cancellation_results'):
        current[legacy] = {path.name: {'outcome': 'accepted'}}
    else:
        (path / legacy).write_bytes(b'Untrusted disabled proof; do not interpret as stopped\n')
    before = tree(path.parent.parent)
    evidence = autonomy_submission.read_reservations(cfg, states=supplied(path, current))
    assert evidence['placements'][0]['state'] == ('unknown' if lifecycle == 'unknown' else 'queued')
    assert evidence['placements'][0]['cores'] == manifest['cores']
    with pytest.raises(ValueError, match='Cancelled jobs cannot be remedy sources'):
        autonomy_submission.prepare_remedy_evidence(cfg, current, 'water')
    assert tree(path.parent.parent) == before


def test_cancelled_slurm_accounting_is_not_an_ordinary_failed_remedy(ordinary_slurm_owned_case):
    cfg, path, current, saved = ordinary_slurm_owned_case()
    manifest = json.loads((path / 'manifest.json').read_text())
    submission.record(path, manifest, '123', authorization=saved['authorization'], autonomy_state=current)
    state.write(path, 'submitted', job_id='default:123')
    state.write(path, 'finished', exit_status=1, completion_source='sacct', scheduler_state='CANCELLED',
        exit_code=1, exit_signal=9, allocated_cpus=8, elapsed='00:05:00', scheduler_observed_at=1002)
    evidence = autonomy_submission.read_reservations(cfg, states=supplied(path, current))
    assert evidence['placements'][0]['state'] == 'queued'
    with pytest.raises(ValueError):
        autonomy_submission.prepare_remedy_evidence(cfg, current, 'water')


def test_autonomous_pbs_needs_no_t187_api(t186_driver, monkeypatch):
    from ag import remote, status
    cfg, path, manifest, context, _, _ = t186_driver
    for module, names in ((status, ('slurm_submission_probe', 'capture_slurm_origin')),
                          (remote, ('slurm_submit_bound', 'slurm_evidence_config', 'slurm_evidence_version'))):
        for name in names:
            monkeypatch.delattr(module, name, raising=False)
    fake = Fake(cfg)
    assert submit.submit(cfg, [path.name], fake, autonomous=context)[0]['state'] == 'submitted'
    assert [command for command in fake.calls if command.operation == 'submit'] == [remote.submit(cfg, manifest)]
    assert not list(path.glob('slurm-origin*'))


def test_ended_failed_program_allows_only_two_actual_remedies(t186_driver):
    from ag import attempt, autonomy, journal, remote
    cfg, path, manifest, context, clock, _ = t186_driver
    source = Path(cfg['local']['studies_root']).parent / 'water.gjf'
    for number in range(3):
        if number:
            manifest = attempt.prepare(cfg, study_name='smoke', template='gaussian', input_path=source,
                tier='simple', walltime='00:30:00', label='failed-retry-' + str(number),
                method_basis='Synthetic fixture', autonomous=context)
            path = attempt.find(cfg, manifest['attempt_id'])
        job = str(123 + number) + '.fixture'
        fake = Fake(cfg)
        fake.qsub = Result(stdout=job + '\n')
        assert submit.submit(cfg, [path.name], fake, autonomous=context)[0]['state'] == 'submitted'
        owned = autonomy.status(cfg, 'smoke')['state']['submissions'][path.name]
        assert owned['failure_class'] == (None if number == 0 else 'gaussian-scf')
        receipt = dict(PBS_JOBID=job, returncode=1, finished_at='2026-10-29T00:00:00+00:00')
        state.write(path, 'finished', exit_status=1, completion_source='ag-exit.json',
            receipts={'start': None, 'exit': receipt}, observation={'job_id': job}, scheduler_observed_at=clock[0])
        names = remote.output_names(manifest)
        for name in names:
            (path / 'outputs' / name).write_text('-----\n# B3LYP/6-31G(d) Opt\n-----\nConvergence failure\nError termination\n'
                if name == names[0] else 'Synthetic scheduler output\n')
        state.write(path, 'fetched', exit_status=1)
        journal.append(path.parent.parent, 'fetch', path.name, detail={'files': names})
        clock[0] += 1
        finished = autonomy.change(cfg, 'smoke', 'finish', context['run_id'], context['token'],
                                   reason='Synthetic completed observation wake')
        run = autonomy.start(cfg, 'smoke', finished['state']['current_plan'], 'fixture-next-wake')
        context.update(run_id=run['run_id'], token=run['token'])
    child = attempt.prepare(cfg, study_name='smoke', template='gaussian', input_path=source,
        tier='simple', walltime='00:30:00', label='third-remedy', method_basis='Synthetic fixture', autonomous=context)
    child_path = attempt.find(cfg, child['attempt_id'])
    fake = Fake(cfg)
    with pytest.raises(ValueError, match='two remedies'):
        submit.submit(cfg, [child_path.name], fake, autonomous=context)
    assert not {'create_attempt', 'upload', 'submit'} & set(fake.operations())
    assert not (child_path / '.submit-claim').exists()
    assert len(autonomy.status(cfg, 'smoke')['state']['submissions']) == 3


def test_actual_mode_report_feeds_scientific_review(scientific_review_case, monkeypatch):
    """Real parsers and report files, with only scheduler/clock/identity fixtures."""
    from ag import facts, mode_review
    from test_mode_review import synthetic_log
    parse, modes = facts.parse_facts, mode_review.read_modes
    cfg, path, manifest, arguments, _, clock = scientific_review_case()
    monkeypatch.setattr(facts, 'parse_facts', parse)
    monkeypatch.setattr(mode_review, 'read_modes', modes)
    # Three handwritten modes for a nonlinear synthetic three-atom geometry.
    log = synthetic_log().replace(' NAtoms=    3\n',
        ' NAtoms=    3\n Rotational constants (GHZ): 10 20 30\n')
    log = log.replace('                      1\n', '                      1                      2                      3\n')
    log = log.replace('                      A\n', '                      A                      A                      A\n')
    log = log.replace('Frequencies --   -100.0000', 'Frequencies --   -100.0000 100.0000 300.0000')
    for prefix in ('Red. masses --', 'Frc consts  --', 'IR Inten    --'):
        log = log.replace(prefix + '      1.0000', prefix + '      1.0000 1.0000 1.0000')
    log = log.replace('  Atom  AN      X      Y      Z',
                      '  Atom  AN      X      Y      Z      X      Y      Z      X      Y      Z')
    for row in ('     1   1     1.00   0.00   0.00', '     2   1    -1.00   0.00   0.00',
                '     3   1     0.00   0.00   0.00'):
        log = log.replace(row, row + '   0.00  1.00  0.00   0.00  0.00  1.00')
    (path / 'outputs/water.log').write_text(log)
    # Discard only this test fixture's stub; product code never refreshes it.
    (path / 'facts.json').unlink()
    owner = {key: arguments[key] for key in ('run_id', 'token', 'plan_sha256')}
    parsed = facts.write_facts(path, **owner)
    assert parsed['n_imag'] == 1 and parsed['vibrational_modes_complete']
    report = mode_review.create(path.name, path.parent.parent, [(1, 2)],
                                'analyses/actual-mode.json', **owner)
    assert report['frequency'] == -100
    arguments.update(outcome='ts_wrong_mode', mode_review='analyses/actual-mode.json')
    result = autonomy_submission.write_scientific_review(cfg, path, **arguments)
    assert result['scientific_judgment'] == 'pending_human_confirmation'
    evidence = json.loads((path / result['record']).read_bytes())
    assert evidence['mode_review']['path'] == 'analyses/actual-mode.json'
    assert set(evidence['mode_review']['geometries']) == {'plus', 'minus'}
