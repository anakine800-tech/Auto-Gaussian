"""T111 authorization tests: synthetic local studies and recording transports only."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from ag import approval, attempt, cancel, cli, config, confirm, state, status, study, submit
from ag.transport import Result
from test_core import cfg, prepared, Fake, job_text, write_config
from test_slurm import multi, prepare, SlurmFake


QUOTE = '  批准本批水分子验证 Attempt。\n保持上述输入与资源。  '


@pytest.fixture(autouse=True)
def no_dialog(monkeypatch):
    monkeypatch.setattr(confirm, 'confirm', lambda *a: pytest.fail('must not open a dialog'))


def record(cfg, path, **kwargs):
    return approval.create(cfg, path.parent.parent.name, [path.name], QUOTE, **kwargs)


def record_path(path, value):
    return path.parent.parent / 'approvals' / (value['id'] + '.json')


def second(cfg, tmp_path):
    m = attempt.prepare(cfg, method_basis='兜底方法：合成测试', study_name='smoke', template='gaussian',
                        input_path=tmp_path / 'water.gjf', tier='simple', walltime='00:30:00', label='second')
    return attempt.find(cfg, m['attempt_id'])


def policy(cfg, **changes):
    value = dict(studies=['smoke'], templates=['gaussian', 'crest'], clusters=['default'],
                 max_cores_per_job=8, max_walltime='00:30:00', quote=QUOTE,
                 set_at='2026-10-23T00:00:00+00:00')
    value.update(changes)
    cfg['approval'] = {'policies': {'validation': value}}
    return value


@pytest.mark.parametrize('batch', [False, True])
def test_approval_submission_and_audit(cfg, prepared, tmp_path, capsys, batch):
    p, m = prepared
    paths = [p, second(cfg, tmp_path)] if batch else [p]
    value = approval.create(cfg, 'smoke', [p.name for p in paths], QUOTE)
    source = record_path(p, value)
    original = source.read_bytes()
    fake = Fake(cfg)
    original_run = fake.run

    def run(command):
        if command.operation == 'create_attempt':
            assert source.with_suffix('.used').exists()
        if command.operation == 'submit':
            fake.qsub = Result(stdout=f'{123 + fake.operations().count("submit")}\n')
        return original_run(command)

    fake.run = run
    results = submit.submit(cfg, [p.name for p in paths], fake, approval_id=value['id'])
    assert all(r['state'] == 'submitted' for r in results)
    assert source.read_bytes() == original and value['quote'] == QUOTE and value['used'] is None
    marker = json.loads(source.with_suffix('.used').read_text())
    assert marker['attempts'] == [p.name for p in paths]
    assert value['total_cores'] == 8 * len(paths)
    stderr = capsys.readouterr().err
    for path in paths:
        saved = json.loads((path / 'submission.json').read_text())['authorization']
        assert saved['method'] == 'approval' and saved['quote'] == QUOTE
        assert saved['approval_id'] == value['id'] and saved['record_sha256'] == approval.digest(value)
        archive = json.loads((path / 'submission-summary.json').read_text())
        assert archive['summary'].strip() == stderr.strip()
        assert archive['authorization'] == saved
        assert path.name in stderr
        assert (path / '.submit-claim').exists()
    events = [json.loads(line) for line in (p.parent.parent / 'journal.jsonl').read_text().splitlines()]
    assert len([e for e in events if e['action'] == 'submit_authorization']) == len(paths)


def test_unused_members_cannot_reuse_consumed_batch(cfg, prepared, tmp_path):
    p, _ = prepared
    other = second(cfg, tmp_path)
    value = approval.create(cfg, 'smoke', [p.name, other.name], QUOTE)
    submit.submit(cfg, [p.name], Fake(cfg), approval_id=value['id'])
    fake = Fake(cfg)
    with pytest.raises(ValueError, match='already used'):
        submit.submit(cfg, [other.name], fake, approval_id=value['id'])
    assert not fake.calls and state.read(other)['state'] == 'prepared'


@pytest.mark.parametrize('field,value', [
    ('schema', 'bad'), ('id', 'other'), ('quote', ' '), ('study_id', 'another-study'),
    ('used', {}), ('total_cores', 9), ('total_cores', True), ('attempts', []),
    ('created_at', 'not-time'), ('created_at', '2020-01-01T00:00:00'),
    ('expires_at', '2000-01-01T00:00:00+00:00'),
    ('expires_at', '2100-01-01T00:00:00+00:00'),
])
def test_bad_approval_never_falls_back(cfg, prepared, field, value):
    p, _ = prepared
    doc = record(cfg, p)
    target = record_path(p, doc)
    doc[field] = value
    target.write_text(json.dumps(doc))
    fake = Fake(cfg)
    with pytest.raises(ValueError):
        submit.submit(cfg, [p.name], fake, approval_id=target.stem)
    assert not fake.calls and not target.with_suffix('.used').exists()
    assert not (p / '.submit-claim').exists()


@pytest.mark.parametrize('field,value', [('attempt_id', 'another-001-sp'), ('bundle_sha256', '0' * 64),
    ('cluster', 'another'), ('cores', 4), ('cores', True)])
def test_mismatched_member_rejects_whole_batch(cfg, prepared, tmp_path, field, value):
    p, _ = prepared
    other = second(cfg, tmp_path)
    doc = approval.create(cfg, 'smoke', [p.name, other.name], QUOTE)
    doc['attempts'][1][field] = value
    doc['total_cores'] = sum(i['cores'] for i in doc['attempts'])
    target = record_path(p, doc)
    target.write_text(json.dumps(doc))
    fake = Fake(cfg)
    with pytest.raises(ValueError):
        submit.submit(cfg, [p.name, other.name], fake, approval_id=doc['id'])
    assert not fake.calls and not target.with_suffix('.used').exists()
    assert all(not (item / '.submit-claim').exists() for item in (p, other))


@pytest.mark.parametrize('quote,hours', [('', 24), (' \n ', 24), (None, 24),
    (QUOTE, 25), (QUOTE, 0), (QUOTE, -1), (QUOTE, float('nan')), (QUOTE, float('inf')), (QUOTE, True)])
def test_invalid_create(cfg, prepared, quote, hours):
    p, _ = prepared
    with pytest.raises(ValueError):
        approval.create(cfg, 'smoke', [p.name], quote, hours)
    assert not (p.parent.parent / 'approvals').exists()


def test_create_refuses_consumed_and_other_study(cfg, prepared):
    p, _ = prepared
    study.init(cfg, 'other')
    with pytest.raises(ValueError, match='study'):
        approval.create(cfg, 'other', [p.name], QUOTE)
    state.write(p, 'submitting')
    with pytest.raises(ValueError, match='prepared'):
        record(cfg, p)


def test_exclusive_record_and_marker(cfg, prepared, monkeypatch):
    p, _ = prepared
    monkeypatch.setattr(approval, 'uuid4', lambda: SimpleNamespace(hex='a' * 32))
    doc = record(cfg, p, hours=1)
    target = record_path(p, doc)
    original = target.read_bytes()
    with pytest.raises(FileExistsError):
        record(cfg, p)
    assert target.read_bytes() == original
    real_open = os.open

    def open_file(path, flags, *args):
        if str(path).endswith('.used'):
            assert flags & os.O_EXCL
            raise PermissionError('Synthetic marker failure')
        return real_open(path, flags, *args)

    monkeypatch.setattr(approval.os, 'open', open_file)
    fake = Fake(cfg)
    with pytest.raises(PermissionError):
        submit.submit(cfg, [p.name], fake, approval_id=doc['id'])
    assert 'create_attempt' not in fake.operations() and 'submit' not in fake.operations()
    assert not (p / '.submit-claim').exists()


def test_concurrent_use_has_one_winner(cfg, prepared, tmp_path):
    p, m = prepared
    other = second(cfg, tmp_path)
    doc = approval.create(cfg, 'smoke', [p.name, other.name], QUOTE)

    def use(path):
        batch = [(path, attempt.read_manifest(path), {})]
        auth = approval.authorize(cfg, batch, approval_id=doc['id'])
        return batch, auth

    candidates = [use(path) for path in (p, other)]

    def consume(candidate):
        try:
            approval.consume(cfg, *candidate)
            return True
        except (ValueError, FileExistsError):
            return False

    with ThreadPoolExecutor(2) as pool:
        assert sum(pool.map(consume, candidates)) == 1


@pytest.mark.parametrize('change', ['inputs', 'approval', 'expiry'])
def test_batch_rechecked_after_inventory(cfg, prepared, tmp_path, change):
    p, _ = prepared
    other = second(cfg, tmp_path)
    doc = approval.create(cfg, 'smoke', [p.name, other.name], QUOTE)
    target = record_path(p, doc)
    fake = Fake(cfg)
    original_run = fake.run

    def run(command):
        if command.operation == 'identity':
            if change == 'inputs':
                (other / 'inputs/water.gjf').write_text('changed')
            else:
                modified = deepcopy(doc)
                if change == 'approval':
                    modified['quote'] = 'different approval'
                else:
                    now = datetime.now(timezone.utc)
                    modified.update(created_at=(now - timedelta(hours=2)).isoformat(),
                                    expires_at=(now - timedelta(hours=1)).isoformat())
                target.write_text(json.dumps(modified))
        return original_run(command)

    fake.run = run
    with pytest.raises(ValueError):
        submit.submit(cfg, [p.name, other.name], fake, approval_id=doc['id'])
    assert 'create_attempt' not in fake.operations()
    assert not target.with_suffix('.used').exists()
    assert not (p / '.submit-claim').exists()


@pytest.mark.parametrize('kind', ['missing', 'malformed', 'linked-file', 'linked-directory', 'linked-marker'])
def test_unsafe_record_paths_fail_closed(cfg, prepared, tmp_path, kind):
    p, _ = prepared
    doc = record(cfg, p)
    target = record_path(p, doc)
    if kind == 'missing':
        target.unlink()
    elif kind == 'malformed':
        target.write_text('[]')
    elif kind == 'linked-marker':
        target.with_suffix('.used').symlink_to(tmp_path / 'missing')
    else:
        moved = tmp_path / 'moved'
        source = target if kind == 'linked-file' else target.parent
        source.rename(moved)
        source.symlink_to(moved, target_is_directory=kind == 'linked-directory')
    fake = Fake(cfg)
    with pytest.raises(ValueError):
        submit.submit(cfg, [p.name], fake, approval_id=doc['id'])
    assert not fake.calls


@pytest.mark.parametrize('mode', ['approval', 'policy'])
def test_second_core_check_without_dialog(cfg, prepared, mode):
    p, _ = prepared
    kwargs = {'approval_id': record(cfg, p)['id']} if mode == 'approval' else {'policy_name': 'validation'}
    if mode == 'policy':
        policy(cfg)
    fake = Fake(cfg)
    original_run = fake.run

    def run(command):
        if command.operation == 'jobs' and fake.operations().count('jobs') == 1:
            fake.qstat = Result(stdout=job_text(cores=44))
        return original_run(command)

    fake.run = run
    with pytest.raises(ValueError, match='Core limit changed'):
        submit.submit(cfg, [p.name], fake, **kwargs)
    assert fake.operations().count('jobs') == 2 and 'create_attempt' not in fake.operations()
    assert state.read(p)['state'] == 'failed_presubmit' and (p / '.submit-claim').exists()


@pytest.mark.parametrize('mode', ['approval', 'policy'])
def test_cancel_still_needs_dialog(cfg, prepared, monkeypatch, mode):
    p, _ = prepared
    rule = policy(cfg)
    fake = Fake(cfg)
    kwargs = (dict(approval_id=record(cfg, p)['id']) if mode == 'approval'
              else dict(policy_name='validation'))
    submit.submit(cfg, [p.name], fake, **kwargs)
    auth = json.loads((p / 'submission.json').read_text())['authorization']
    assert auth['method'] == mode and auth['quote'] == QUOTE
    if mode == 'policy':
        assert auth['policy_name'] == 'validation' and auth['rule_sha256'] == approval.digest(rule)
    seen = []
    monkeypatch.setattr(confirm, 'confirm', lambda *args: seen.append(args) or False)
    with pytest.raises(submit.UserCancelled):
        cancel.cancel(cfg, p, fake)
    assert len(seen) == 1 and seen[0][1] == '取消作业'
    assert 'cancel' not in fake.operations()


@pytest.mark.parametrize('changes', [dict(studies=['other']), dict(templates=['crest']), dict(clusters=['other']),
    dict(max_cores_per_job=4), dict(max_walltime='00:29:59')])
def test_policy_mismatch_has_no_remote_calls(cfg, prepared, changes):
    p, _ = prepared
    policy(cfg, **changes)
    fake = Fake(cfg)
    with pytest.raises(ValueError, match='policy'):
        submit.submit(cfg, [p.name], fake, policy_name='validation')
    assert not fake.calls


@pytest.mark.parametrize('changes', [dict(studies=['sm*']), dict(studies=[]), dict(studies=['smoke', 'smoke']),
    dict(templates=['*']), dict(clusters=['def?ult']), dict(max_cores_per_job=True),
    dict(max_cores_per_job=0), dict(max_walltime='00:00:00'), dict(max_walltime='00:61:00'),
    dict(quote=' '), dict(set_at='2026-10-23'), dict(unrecognized=True)])
def test_invalid_policy_config(cfg, changes):
    policy(cfg, **changes)
    with pytest.raises(config.ConfigError):
        config.load_config(write_config(cfg))


@pytest.mark.parametrize('mode', ['approval', 'policy'])
def test_named_slurm_authorization(multi, tmp_path, mode):
    p, _ = prepare(multi, tmp_path)
    if mode == 'approval':
        kwargs = dict(approval_id=record(multi, p)['id'])
    else:
        policy(multi, studies=['water'], clusters=['batch'], max_walltime='01:30:00')
        kwargs = dict(policy_name='validation')
    selected = config.select_cluster(multi, 'batch')
    fake = SlurmFake(selected)
    assert submit.submit(selected, [p.name], fake, **kwargs)[0]['state'] == 'submitted'
    assert fake.operations().count('slurm_jobs') == 2
    assert json.loads((p / 'submission.json').read_text())['authorization']['method'] == mode


def test_dialog_default_even_with_matching_policy(cfg, prepared, monkeypatch):
    p, _ = prepared
    policy(cfg)
    seen = []
    monkeypatch.setattr(confirm, 'confirm', lambda text: seen.append(text) or True)
    submit.submit(cfg, [p.name], Fake(cfg))
    assert len(seen) == 1
    assert json.loads((p / 'submission.json').read_text())['authorization']['method'] == 'dialog'


def test_cli_approve_is_local_and_doctor_lists_scope(cfg, prepared, monkeypatch, capsys):
    p, _ = prepared
    monkeypatch.setattr(cli, 'load_config', lambda **kwargs: cfg)
    monkeypatch.setattr('ag.transport.SSHTransport', lambda *a, **kw: pytest.fail('approve is local'))
    assert cli.main(['approve', '--study', 'smoke', '--attempt', p.name, '--quote', QUOTE, '--hours', '2']) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc['quote'] == QUOTE and doc['attempts'][0]['attempt_id'] == p.name
    rules = policy(cfg)
    monkeypatch.setattr('ag.transport.SSHTransport', lambda *a, **kw: Fake(cfg))
    assert cli.main(['doctor', '--json']) == 0
    assert json.loads(capsys.readouterr().out)['approval_policies'] == {'validation': rules}


def test_cli_mutual_exclusion_and_cancel_rejects_authorization():
    for args in (['submit', 'smoke-001-sp', '--approval', 'a', '--policy', 'b'],
                 ['cancel', 'smoke-001-sp', '--approval', 'a'],
                 ['cancel', 'smoke-001-sp', '--policy', 'b']):
        with pytest.raises(SystemExit):
            cli.main(args)


@pytest.mark.parametrize('mode', ['approval', 'policy', 'dialog'])
def test_unknown_recovery_preserves_authorization(cfg, prepared, monkeypatch, mode):
    p, m = prepared
    if mode == 'approval':
        kwargs = dict(approval_id=record(cfg, p)['id'])
    elif mode == 'policy':
        policy(cfg)
        kwargs = dict(policy_name='validation')
    else:
        monkeypatch.setattr(confirm, 'confirm', lambda *a: True)
        kwargs = {}
    fake = Fake(cfg)
    fake.qsub = Result(255, '', 'synthetic lost response')
    with pytest.raises(submit.UnknownSubmission):
        submit.submit(cfg, [p.name], fake, **kwargs)
    archived = json.loads((p / 'submission-summary.json').read_text())['authorization']
    assert not (p / 'submission.json').exists()
    fake.calls.clear()
    fake.qstat = Result(stdout=job_text(m))
    assert status.check(cfg, p, fake)['state'] == 'submitted'
    assert json.loads((p / 'submission.json').read_text())['authorization'] == archived
    assert 'submit' not in fake.operations() and 'create_attempt' not in fake.operations()


def test_unknown_recovery_rejects_mismatched_summary(cfg, prepared):
    p, m = prepared
    doc = record(cfg, p)
    fake = Fake(cfg)
    fake.qsub = Result(255, '', 'synthetic lost response')
    with pytest.raises(submit.UnknownSubmission):
        submit.submit(cfg, [p.name], fake, approval_id=doc['id'])
    summary_path = p / 'submission-summary.json'
    summary = json.loads(summary_path.read_text())
    summary['manifest_sha256'] = '0' * 64
    summary_path.write_text(json.dumps(summary))
    fake.qstat = Result(stdout=job_text(m))
    with pytest.raises(ValueError, match='archived submission authorization'):
        status.check(cfg, p, fake)
    assert not (p / 'submission.json').exists()
