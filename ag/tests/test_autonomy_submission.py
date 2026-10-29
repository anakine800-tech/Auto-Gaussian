"""Existing evidence audit uses synthetic studies and fixed recording fakes."""
import json

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
