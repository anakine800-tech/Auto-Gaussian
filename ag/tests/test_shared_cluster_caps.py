"""T101: same-login queue entries cannot bypass the shared committed cap."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path

import pytest

from ag import attempt, budget, config, doctor, fetch, monitor, state, status, submission, submit
from ag.transport import Result
from test_core import cfg, INPUT, allow, write_config
from test_slurm import multi, prepare, SlurmFake, submitted


@pytest.fixture
def shared(multi):
    entry = multi['clusters']['batch']
    entry['resources']['max_cores'] = 64
    entry['resources']['max_committed_cores'] = 128
    multi['clusters']['trial'] = deepcopy(entry)
    multi['clusters']['trial'].update(partition='trial', account='trial', qos='trial')
    return multi


def reserve(raw, tmp_path, name='batch', *, cores=24, job=None):
    raw['clusters'][name]['resources']['tiers']['simple']['cores'] = cores
    source = tmp_path / 'water.gjf'
    from ag import study
    if not (Path(raw['local']['studies_root']) / 'water').exists():
        study.init(raw, 'water')
    source.write_text(INPUT.replace('nprocshared=8', f'nprocshared={cores}'))
    m = attempt.prepare(raw, study_name='water', template='gaussian', input_path=source,
                        tier='simple', walltime='01:30:00', label='held', cluster=name,
                        method_basis='兜底方法：合成测试')
    path = attempt.find(raw, m['attempt_id'])
    selected = config.select_cluster(raw, name)
    ledger = budget.read(selected)
    budget.reserve(selected, m, ledger)
    (path / '.submit-claim').touch()
    state.write(path, 'submitting')
    if job:
        submission.record(path, m, job)
        state.write(path, 'submitted', job_id=name + ':' + job)
    else:
        state.write(path, 'unknown')
    return path, m


def row(m, job='123', cores=None):
    return f"{job}|{m['attempt_id']}|fixture|RUNNING|{cores or m['cores']}|00:01|fixture\n"


@pytest.mark.parametrize('job', [None, '123'])
def test_peer_unobserved_and_unknown_refuse_before_dialog(shared, tmp_path, monkeypatch, job):
    for entry in shared['clusters'].values():
        entry['resources']['max_committed_cores'] = 32
    reserve(shared, tmp_path, job=job)
    target, _ = prepare(shared, tmp_path, 'trial', 'next')
    # 24 + 8 == 32 is allowed; one external core makes it exceed the cap.
    fake = SlurmFake(config.select_cluster(shared, 'trial'))
    fake.queue = Result(stdout='999|external|fixture|PENDING|1|00:00|other\n')
    monkeypatch.setattr('ag.confirm.confirm', lambda _: pytest.fail('must refuse before confirmation'))
    with pytest.raises(ValueError, match='25 occupied.*32 cap'):
        submit.submit(shared, [target.name], fake)
    assert not (target / '.submit-claim').exists()
    assert 'submit' not in fake.operations()


def test_exact_24_plus_16_over_32(shared, tmp_path, monkeypatch):
    reserve(shared, tmp_path)
    shared['clusters']['trial']['resources']['tiers']['simple']['cores'] = 16
    source = tmp_path / 'candidate.gjf'
    source.write_text(INPUT.replace('nprocshared=8', 'nprocshared=16'))
    m = attempt.prepare(shared, study_name='water', template='gaussian', input_path=source,
                        tier='simple', walltime='00:30:00', label='next', cluster='trial', method_basis='兜底方法')
    shared['clusters']['trial']['resources']['max_committed_cores'] = 32
    fake = SlurmFake(config.select_cluster(shared, 'trial'))
    monkeypatch.setattr('ag.confirm.confirm', lambda _: pytest.fail('must refuse'))
    with pytest.raises(ValueError, match='24 occupied.*16 requested / 32 cap'):
        submit.submit(shared, [m['attempt_id']], fake)


def test_visible_peer_counted_once_with_bound_identity(shared, tmp_path, monkeypatch, capsys):
    _, m = reserve(shared, tmp_path, job='123')
    shared['clusters']['trial']['resources']['max_committed_cores'] = 32
    target, candidate = prepare(shared, tmp_path, 'trial', 'next')
    fake = SlurmFake(config.select_cluster(shared, 'trial'))
    fake.queue = Result(stdout=row(m))
    monkeypatch.setattr('ag.confirm.confirm', lambda _: False)
    with pytest.raises(submit.UserCancelled):
        submit.submit(shared, [target.name], fake)
    text = capsys.readouterr().err
    assert '当前占用 24 核' in text and '提交后合计 32 / 上限 32 核' in text
    assert 'Partition: trial' in text
    assert 'batch=128, trial=32' in text
    assert 'Partition: trial' in attempt.summary(shared, candidate)
    # A same-number scheduler row with the wrong full name cannot release cores.
    fake.queue = Result(stdout=row(dict(m, attempt_id='foreign-job')))
    with pytest.raises(ValueError, match='identity mismatch'):
        submit.submit(shared, [target.name], fake)


def test_two_independent_submits_and_batch_readback_lag(shared, tmp_path, monkeypatch):
    shared['clusters']['trial']['resources']['max_committed_cores'] = 16
    first, _ = prepare(shared, tmp_path, 'batch', 'one')
    second, _ = prepare(shared, tmp_path, 'trial', 'two')
    third, _ = prepare(shared, tmp_path, 'trial', 'three')
    allow(monkeypatch)
    fake_a = SlurmFake(config.select_cluster(shared, 'batch'))
    fake_b = SlurmFake(config.select_cluster(shared, 'trial'))
    fake_b.qsub = Result(stdout='124\n')
    submit.submit(shared, [first.name], fake_a)
    submit.submit(shared, [second.name], fake_b)
    with pytest.raises(ValueError, match='16 occupied'):
        submit.submit(shared, [third.name], fake_b)
    assert fake_a.operations().count('submit') == fake_b.operations().count('submit') == 1
    assert budget.totals(fake_a.cfg) == budget.totals(fake_b.cfg) == (0, 12 * 3600)


def test_confirmation_recheck_includes_peer_and_new_remote_cores(shared, tmp_path, monkeypatch):
    reserve(shared, tmp_path, cores=24)
    shared['clusters']['trial']['resources']['max_committed_cores'] = 32
    target, _ = prepare(shared, tmp_path, 'trial', 'next')
    fake = SlurmFake(config.select_cluster(shared, 'trial'))
    def confirm(_):
        fake.queue = Result(stdout='999|external|fixture|SUSPENDED|1|00:00|other\n')
        return True
    monkeypatch.setattr('ag.confirm.confirm', confirm)
    with pytest.raises(ValueError, match='Core limit changed'):
        submit.submit(shared, [target.name], fake)
    assert state.read(target)['state'] == 'failed_presubmit'
    assert not set(fake.operations()) & {'submit', 'create_attempt', 'upload'}
    assert budget.totals(fake.cfg) == (0, 0)


def test_batch_earlier_job_still_reserved(shared, tmp_path, monkeypatch):
    shared['clusters']['trial']['resources']['max_committed_cores'] = 24
    reserve(shared, tmp_path, cores=8)
    paths = [prepare(shared, tmp_path, 'trial', label)[0] for label in ('one', 'two')]
    class Lag(SlurmFake):
        def run(self, command):
            if command.operation == 'submit':
                self.queue = Result(stdout='999|external|fixture|PENDING|1|00:00|other\n')
            return super().run(command)
    fake = Lag(config.select_cluster(shared, 'trial'))
    allow(monkeypatch)
    with pytest.raises(ValueError, match='Core limit changed'):
        submit.submit(shared, [p.name for p in paths], fake)
    assert fake.operations().count('submit') == 1
    assert state.read(paths[0])['state'] == 'submitted'
    assert state.read(paths[1])['state'] == 'failed_presubmit'


def test_shared_submit_lock_serializes_different_entries(shared, tmp_path, monkeypatch):
    shared['clusters']['trial']['resources']['max_committed_cores'] = 8
    paths = [(name, prepare(shared, tmp_path, name, name)[0]) for name in ('batch', 'trial')]
    allow(monkeypatch)
    def one(item):
        name, path = item
        fake = SlurmFake(config.select_cluster(shared, name))
        try:
            submit.submit(shared, [path.name], fake)
            return 'submitted'
        except ValueError as exc:
            assert 'Core limit exceeded' in str(exc)
            assert 'submit' not in fake.operations()
            return 'refused'
    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(one, paths)) == ['refused', 'submitted']


@pytest.mark.parametrize('difference', ['host', 'config_file', 'scheduler'])
def test_group_identity_and_foreign_ledger_isolation(shared, tmp_path, difference):
    trial = shared['clusters']['trial']
    if difference == 'host':
        trial['ssh']['host'] = 'distinct-alias'
    elif difference == 'config_file':
        other = tmp_path / 'other-ssh'; other.touch()
        trial['ssh']['config_file'] = str(other)
    else:
        trial['scheduler'] = {'queue': 'trial'}
    selected = config.select_cluster(shared, 'batch')
    Path(selected['_config_dir'], 'budget-trial.json').write_text('broken')
    assert list(config.shared_clusters(selected)) == ['batch']
    assert list(budget.shared_ledgers(selected)) == ['batch']
    assert config.committed_cap(selected) == 128


def test_normalized_ssh_file_and_minimum_limit(shared, tmp_path):
    link = tmp_path / 'ssh-link'
    link.symlink_to(shared['clusters']['batch']['ssh']['config_file'])
    shared['clusters']['trial']['ssh']['config_file'] = str(link)
    shared['clusters']['trial']['resources']['max_committed_cores'] = 256
    for name in ('batch', 'trial'):
        selected = config.select_cluster(shared, name)
        assert config.committed_cap(selected) == 128
        assert 'batch=128, trial=256' in config.shared_cap_summary(selected)


def test_missing_ledgers_without_submission_traces_stay_in_memory(shared, tmp_path, monkeypatch):
    peer, _ = prepare(shared, tmp_path, 'batch', 'unused')
    target, _ = prepare(shared, tmp_path, 'trial', 'next')
    selected = config.select_cluster(shared, 'trial')
    peer_ledger = budget.ledger_path(config.select_cluster(shared, 'batch'))
    target_ledger = budget.ledger_path(selected)
    before = {name: (peer / name).read_bytes() for name in ('manifest.json', 'status.json')}
    ledgers = budget.shared_ledgers(selected)
    assert ledgers == {name: dict(cluster=name, attempts={}) for name in ('batch', 'trial')}
    assert not peer_ledger.exists() and not target_ledger.exists()
    allow(monkeypatch)
    assert submit.submit(shared, [target.name], SlurmFake(selected))[0]['state'] == 'submitted'
    assert not peer_ledger.exists()
    assert list(budget.read(selected)['attempts']) == [target.name]
    assert before == {name: (peer / name).read_bytes() for name in before}


@pytest.mark.parametrize('trace', ['claim', 'submission', 'submitting', 'unknown',
                                  'submitted', 'running', 'awaiting_second_observation',
                                  'stalled', 'interrupted', 'finished', 'fetched',
                                  'cancelled', 'failed_presubmit'])
def test_missing_peer_ledger_with_trace_in_another_study_refuses(shared, tmp_path, monkeypatch, trace):
    from ag import study
    target, _ = prepare(shared, tmp_path, 'trial', 'next')
    study.init(shared, 'another-study')
    m = attempt.prepare(shared, study_name='another-study', template='gaussian',
                        input_path=tmp_path / 'water.gjf', tier='simple', walltime='01:30:00',
                        label='prior', cluster='batch', method_basis='兜底方法：合成测试')
    peer = attempt.find(shared, m['attempt_id'])
    if trace == 'claim':
        (peer / '.submit-claim').touch()
    elif trace == 'submission':
        submission.record(peer, m, '123')
    else:
        # Even a status-only trace with lost claim/binding must fail closed.
        current = state.read(peer)
        (peer / 'status.json').write_text(json.dumps(dict(current, state=trace)))
    selected = config.select_cluster(shared, 'trial')
    peer_ledger = budget.ledger_path(config.select_cluster(shared, 'batch'))
    fake = SlurmFake(selected)
    monkeypatch.setattr('ag.confirm.confirm', lambda _: pytest.fail('must refuse before confirmation'))
    with pytest.raises(ValueError, match='Cluster batch.*budget-batch.json.*another-study') as error:
        submit.submit(shared, [target.name], fake)
    assert '从备份或原配置目录找回该入口的台账；找不到则停止并交给负责人核对' in str(error.value)
    assert str(tmp_path) not in str(error.value)
    assert not peer_ledger.exists() and not budget.ledger_path(selected).exists()
    assert not (target / '.submit-claim').exists() and 'submit' not in fake.operations()


@pytest.mark.parametrize('scenario', ['relocated_config', 'missing_binding', 'unreadable_status'])
def test_missing_ledger_recovery_direction_without_private_details(shared, tmp_path, monkeypatch, scenario):
    peer, _ = reserve(shared, tmp_path, job='123')
    target, _ = prepare(shared, tmp_path, 'trial', 'next')
    original_ledger = budget.ledger_path(config.select_cluster(shared, 'batch'))
    original_bytes = original_ledger.read_bytes()
    if scenario == 'relocated_config':
        directory = tmp_path / 'relocated-config'
        directory.mkdir()
        shared['_config_dir'] = str(directory)
    else:
        original_ledger.unlink()
        (peer / '.submit-claim').unlink()
        if scenario == 'missing_binding':
            (peer / 'submission.json').unlink()
        else:
            ssh = shared['clusters']['batch']['ssh']
            Path(ssh['config_file']).write_text('Host batch-fixture\n HostName private-host-marker\n User private-user-marker\n')
            original = Path.read_text
            def read_text(path, *args, **kwargs):
                if path == peer / 'status.json':
                    raise PermissionError(f'private-user-marker@private-host-marker: {path}')
                return original(path, *args, **kwargs)
            monkeypatch.setattr(Path, 'read_text', read_text)
    selected = config.select_cluster(shared, 'trial')
    fake = SlurmFake(selected)
    monkeypatch.setattr('ag.confirm.confirm', lambda _: pytest.fail('must refuse before confirmation'))
    with pytest.raises(ValueError, match='Cluster batch.*budget-batch.json') as error:
        submit.submit(shared, [target.name], fake)
    text = str(error.value)
    assert '从备份或原配置目录找回该入口的台账；找不到则停止并交给负责人核对' in text
    assert all(secret not in text for secret in (str(tmp_path), 'private-user-marker', 'private-host-marker', 'batch-fixture'))
    assert not budget.ledger_path(config.select_cluster(shared, 'batch')).exists()
    assert not budget.ledger_path(selected).exists() and not (target / '.submit-claim').exists()
    assert not fake.calls
    if scenario == 'relocated_config':
        assert original_ledger.read_bytes() == original_bytes


@pytest.mark.parametrize('damage', ['json', 'schema', 'unreadable'])
def test_existing_bad_peer_ledger_is_never_initialized_empty(shared, tmp_path, monkeypatch, damage):
    target, _ = prepare(shared, tmp_path, 'trial', 'next')
    selected = config.select_cluster(shared, 'trial')
    peer_ledger = budget.ledger_path(config.select_cluster(shared, 'batch'))
    contents = b'{' if damage == 'json' else b'{}'
    peer_ledger.write_bytes(contents)
    if damage == 'unreadable':
        original = Path.read_text
        def read_text(path, *args, **kwargs):
            if path == peer_ledger:
                raise PermissionError('fixture ledger unreadable')
            return original(path, *args, **kwargs)
        monkeypatch.setattr(Path, 'read_text', read_text)
    fake = SlurmFake(selected)
    monkeypatch.setattr('ag.confirm.confirm', lambda _: pytest.fail('must refuse before confirmation'))
    with pytest.raises(ValueError, match='Cluster batch.*budget-batch.json'):
        submit.submit(shared, [target.name], fake)
    assert peer_ledger.read_bytes() == contents
    assert not budget.ledger_path(selected).exists()
    assert not (target / '.submit-claim').exists() and 'submit' not in fake.operations()


@pytest.mark.parametrize('damage', ['missing', 'json', 'cluster', 'binding', 'bundle'])
def test_bad_peer_ledger_or_binding_refuses(shared, tmp_path, monkeypatch, damage):
    path, m = reserve(shared, tmp_path, job='123')
    selected = config.select_cluster(shared, 'batch')
    ledger_path = budget.ledger_path(selected)
    if damage == 'missing':
        ledger_path.unlink()
    elif damage == 'json':
        ledger_path.write_text('{')
    elif damage == 'binding':
        (path / 'submission.json').write_text('{}')
    else:
        ledger = budget.read(selected)
        if damage == 'cluster':
            ledger['cluster'] = 'trial'
        else:
            ledger['attempts'][m['attempt_id']]['bundle_sha256'] = '0' * 64
        budget.write(selected, ledger)
    target, _ = prepare(shared, tmp_path, 'trial', 'next')
    fake = SlurmFake(config.select_cluster(shared, 'trial'))
    monkeypatch.setattr('ag.confirm.confirm', lambda _: pytest.fail('bad ledger must refuse'))
    with pytest.raises(ValueError, match='Cluster batch.*budget-batch.json'):
        submit.submit(shared, [target.name], fake)
    assert not (target / '.submit-claim').exists()


@pytest.mark.parametrize('allowed', [None, ['crest']])
def test_prepare_template_allowlist_and_no_retroactive_check(shared, tmp_path, allowed):
    old, old_m = prepare(shared, tmp_path, 'trial', 'old')
    before = {name: (old / name).read_bytes() for name in ('manifest.json', 'inputs/job.slurm')}
    if allowed is not None:
        shared['clusters']['trial']['allowed_templates'] = allowed
        with pytest.raises(ValueError, match='Cluster trial.*allowed_templates: crest'):
            prepare(shared, tmp_path, 'trial', 'new')
    else:
        prepare(shared, tmp_path, 'trial', 'new')
    source = tmp_path / 'water.xyz'; source.write_text('3\nwater\nO 0 0 0\nH 0 0 1\nH 0 1 0\n')
    m = attempt.prepare(shared, study_name='water', template='crest', input_path=source,
                        tier='simple', walltime='00:30:00', label='crest', cluster='trial', method_basis='兜底方法')
    assert m['template'] == 'crest'
    attempt.verified_files(shared, old, old_m)
    assert before == {name: (old / name).read_bytes() for name in before}


def test_existing_attempt_status_fetch_preserves_bundle(shared, tmp_path, monkeypatch):
    path, m, fake = submitted(shared, tmp_path, monkeypatch)
    before = {name: (path / name).read_bytes() for name in ('manifest.json', 'submission.json', 'inputs/job.slurm')}
    shared['clusters']['batch']['allowed_templates'] = ['crest']
    assert status.check(shared, path, fake)['state'] == 'finished'
    fake.files.update({'water.log': b'fixture', 'water.chk': b'checkpoint fixture',
                       'job.slurm.out': b'', 'job.slurm.err': b''})
    fetch.fetch(shared, path, fake)
    assert state.read(path)['state'] == 'fetched'
    assert before == {name: (path / name).read_bytes() for name in before}


@pytest.mark.parametrize('value', ['crest', [1], ['unknown'], True])
def test_invalid_template_allowlist(shared, value):
    shared['clusters']['trial']['allowed_templates'] = value
    with pytest.raises(ValueError, match='allowed_templates'):
        config.load_config(write_config(shared))


@pytest.mark.parametrize('value', [[], ['crest'], ['gaussian', 'xtb', 'crest', 'multiwfn']])
def test_valid_template_allowlists(shared, value):
    shared['clusters']['trial']['allowed_templates'] = value
    assert config.load_config(write_config(shared))['clusters']['trial']['allowed_templates'] == value


def test_implicit_default_preserves_allowlist(cfg, multi, tmp_path):
    cfg['clusters'] = {'batch': multi['clusters']['batch']}
    path = write_config(cfg)
    path.write_text('allowed_templates = []\n' + path.read_text())
    loaded = config.load_config(path)
    with pytest.raises(ValueError, match='Cluster default.*allowed_templates: .*none'):
        prepare(loaded, tmp_path, 'default')


def test_foreign_same_job_number_never_releases_local_reservation(shared, tmp_path):
    shared['clusters']['trial']['ssh']['host'] = 'distinct-alias'
    reserve(shared, tmp_path, 'batch', job='123')
    _, m = reserve(shared, tmp_path, 'trial', job='123')
    trial = config.select_cluster(shared, 'trial')
    assert budget.shared_unobserved_cores(trial, [], budget.shared_ledgers(trial)) == 24
    from ag.slurm import parse_queue
    assert budget.shared_unobserved_cores(trial, parse_queue(row(m)), budget.shared_ledgers(trial)) == 0


@pytest.mark.parametrize('different', ['host', 'config_file'])
def test_doctor_prompts_only_and_no_private_identity(shared, tmp_path, capsys, monkeypatch, different):
    monkeypatch.setattr(config.subprocess, 'run', lambda *a, **k:
                        Result(stdout='hostname synthetic.invalid\nport 22\nuser fixture\n'))
    selected = config.select_cluster(shared, 'batch')
    baseline = doctor.doctor(selected, SlurmFake(selected))
    if different == 'host':
        shared['clusters']['trial']['ssh']['host'] = 'private-host-marker'
    else:
        other = tmp_path / 'private-ssh-marker'; other.touch()
        shared['clusters']['trial']['ssh']['config_file'] = str(other)
    selected['resources']['budget_core_hours'] = 1
    result = doctor.doctor(selected, SlurmFake(selected))
    text = capsys.readouterr().err
    assert 'budget_core_hours 已不参与提交检查，可删除' in text
    assert '未合并' in text and 'batch, trial' in text
    assert 'private-host-marker' not in text and 'private-ssh-marker' not in text and str(tmp_path) not in text
    baseline.pop('inventory_seconds'); result.pop('inventory_seconds')
    assert result == baseline


@pytest.mark.parametrize('failed,old_cache', [(False, False), (True, False), (True, True)])
def test_monitor_all_paths_shared_caps(shared, monkeypatch, failed, old_cache):
    shared['clusters']['trial']['resources']['max_committed_cores'] = 256
    monkeypatch.setattr(monitor, 'ssh_identity', lambda _: ('fixture', 22, 'fixture'))
    for name, peer in [('batch', 'trial'), ('trial', 'batch')]:
        selected = config.select_cluster(shared, name)
        fake = SlurmFake(selected)
        if old_cache:
            previous = monitor.sample(selected, fake)
            previous['own'].pop('committed_cap'); previous['own'].pop('shared_with')
            previous['cluster']['budget'] = dict(core_hours=1, used=2, reserved=3)
            (monitor.cache_dir(selected) / 'latest.json').write_text(json.dumps(previous))
        if failed:
            fake.queue = Result(255)
        result = monitor.sample(selected, fake)
        assert result['ok'] is not failed
        assert result['own']['committed_cap'] == 128
        assert result['own']['core_cap'] == 64
        assert result['own']['shared_with'] == [peer]
        assert result['cluster']['budget'] is None


def test_monitor_over_cap_includes_peer_reservation_without_changing_remote_fields(shared, tmp_path):
    reserve(shared, tmp_path, cores=24)
    shared['clusters']['trial']['resources']['max_committed_cores'] = 32
    selected = config.select_cluster(shared, 'trial')
    fake = SlurmFake(selected)
    fake.queue = Result(stdout='999|external|fixture|RUNNING|16|00:00|other\n')
    result = monitor.observation(selected, fake, 'fixture')
    assert result['own']['cores_in_use'] == result['own']['cores_running'] == 16
    assert result['own']['cores_queued'] == 0
    assert any(w['kind'] == 'over-cap' and '预留 24 核' in w['detail'] for w in result['warnings'])


def test_failed_monitor_refreshes_changed_caps_and_membership(shared, monkeypatch):
    monkeypatch.setattr(monitor, 'ssh_identity', lambda _: ('fixture', 22, 'fixture'))
    selected = config.select_cluster(shared, 'trial')
    fake = SlurmFake(selected)
    first = monitor.sample(selected, fake)
    assert first['own']['committed_cap'] == 128
    shared['clusters']['batch']['resources']['max_committed_cores'] = 64
    fake.queue = Result(255)
    failed = monitor.sample(selected, fake)
    assert not failed['ok'] and failed['own']['committed_cap'] == 64
    assert failed['own']['core_cap'] == 64
    shared['clusters']['batch']['ssh']['host'] = 'distinct-alias'
    failed = monitor.sample(selected, fake)
    assert failed['own']['committed_cap'] == 128 and 'shared_with' not in failed['own']
