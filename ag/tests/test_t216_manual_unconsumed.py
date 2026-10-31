"""T216 synthetic historical records; the test plugin isolates every HOME."""
import json
import os

import pytest

from ag import autonomy_submission as accounting
from test_core import cfg, prepared
from test_autonomy_submission import install_owned, selector, supplied, tree


def historical_journal(path):
    # An old prepare event lacks the newer state-event chain and exact fields.
    event = dict(action='prepare', attempt_id=path.name, result='ok', legacy=True)
    (path.parent.parent / 'journal.jsonl').write_text(json.dumps(event) + '\n')


@pytest.mark.parametrize('journal', ['legacy', 'missing', 'no_newline', 'bad_json', 'duplicate_key', 'nonobject'])
def test_unclaimed_prepared_uses_hard_evidence_not_new_journal(cfg, prepared, selector, journal):
    path, _ = prepared
    historical_journal(path)
    log = path.parent.parent / 'journal.jsonl'
    if journal == 'missing':
        log.unlink()
    elif journal == 'no_newline':
        log.write_bytes(log.read_bytes().rstrip(b'\n'))
    elif journal in ('bad_json', 'duplicate_key', 'nonobject'):
        log.write_text({'bad_json': '{', 'duplicate_key': '{"action":"submit_authorization","action":"prepare"}\n',
                        'nonobject': '[]\n'}[journal])
    before = tree(path.parent.parent)
    with pytest.raises(ValueError, match='audit refused'):
        accounting.audit(path)
    report = accounting.read_reservations(cfg)
    assert report['placements'] == []
    assert report['warnings'][0]['kind'] == 'manual_unconsumed_excluded'
    assert report['warnings'][0]['attempt_id'] == path.name
    if journal in ('bad_json', 'duplicate_key', 'nonobject'):
        assert 'unparseable or non-object' in report['warnings'][0]['journal_warning']
    assert tree(path.parent.parent) == before


def test_current_prepared_also_returns_exclusion_warning(cfg, prepared, selector):
    path, _ = prepared
    report = accounting.read_reservations(cfg)
    assert report['placements'] == []
    assert report['warnings'][0]['kind'] == 'manual_unconsumed_excluded'
    assert report['warnings'][0]['state'] == 'prepared'


@pytest.mark.parametrize('damage', [
    'claim', 'submission', 'summary', 'job', 'empty_job', 'false_job', 'bad_state',
    'bad_status', 'duplicate_status', 'bad_manifest', 'duplicate_manifest',
    'journal_authorization',
    'journal_autonomy', 'journal_submission', 'autonomy_review', 'cancel', 'probe',
])
def test_conflicting_or_damaged_prepared_evidence_refuses(cfg, prepared, selector, damage):
    path, manifest = prepared
    historical_journal(path)
    status = path / 'status.json'
    journal = path.parent.parent / 'journal.jsonl'
    if damage == 'claim':
        (path / '.submit-claim').write_bytes(accounting._CLAIM)
    elif damage in ('submission', 'summary'):
        (path / ('submission.json' if damage == 'submission' else 'submission-summary.json')).write_text('{}')
    elif damage in ('job', 'empty_job', 'false_job', 'bad_state'):
        value = json.loads(status.read_text())
        value['state' if damage == 'bad_state' else 'job_id'] = {
            'job': 'default:123.fixture', 'empty_job': '', 'false_job': False,
            'bad_state': 'invalid',
        }[damage]
        status.write_text(json.dumps(value))
    elif damage == 'bad_status':
        status.write_text('{')
    elif damage == 'duplicate_status':
        status.write_text('{"state":"submitted","state":"prepared"}')
    elif damage == 'bad_manifest':
        (path / 'manifest.json').write_text('{')
    elif damage == 'duplicate_manifest':
        (path / 'manifest.json').write_text('{"attempt_id":"other",' + json.dumps(manifest)[1:])
    elif damage in ('journal_authorization', 'journal_autonomy', 'journal_submission'):
        event = dict(attempt_id=path.name, action='submit_authorization', result='ok',
                     detail={'method': 'autonomy-policy' if damage == 'journal_autonomy' else 'dialog'})
        if damage == 'journal_submission':
            event.update(action='state', result='submitted')
        journal.write_text(json.dumps(event) + '\n')
    else:
        name = {'autonomy_review': 'autonomy-scientific-review.json',
                'cancel': '.cancel-claim', 'probe': 'slurm-origin-probe.json'}[damage]
        (path / name).write_text('{}')
    before = tree(path.parent.parent)
    with pytest.raises((ValueError, OSError)):
        accounting.read_reservations(cfg)
    assert tree(path.parent.parent) == before


@pytest.mark.parametrize('conflict', ['authorization', 'autonomy', 'submitted'])
@pytest.mark.parametrize('damaged_first', [True, False])
def test_damaged_journal_line_cannot_hide_a_readable_conflict(cfg, prepared, selector, conflict, damaged_first):
    path, _ = prepared
    event = dict(attempt_id=path.name, action='submit_authorization', result='ok',
                 detail={'method': 'autonomy-policy' if conflict == 'autonomy' else 'dialog'})
    if conflict == 'submitted':
        event.update(action='state', result='submitted')
    valid = json.dumps(event) + '\n'
    damaged = '{\n[]\n{"action":"prepare","action":"prepare"}\n'
    (path.parent.parent / 'journal.jsonl').write_text(damaged + valid if damaged_first else valid + damaged)
    before = tree(path.parent.parent)
    with pytest.raises(ValueError, match='contradicts journal submission evidence'):
        accounting.read_reservations(cfg)
    assert tree(path.parent.parent) == before


@pytest.mark.parametrize('state', ['submitted', 'running', 'stalled', 'unknown'])
def test_nonprepared_never_uses_unconsumed_compatibility(cfg, prepared, selector, state):
    path, manifest = prepared
    historical_journal(path)
    (path / 'status.json').write_text(json.dumps({'state': state, 'job_id': None}))
    report = accounting.read_reservations(cfg)
    assert report['placements'][0]['cores'] == manifest['cores']
    assert report['placements'][0]['state'] == 'reserved'
    assert report['warnings'][0]['kind'] == 'manual_unverified_reserved'


@pytest.mark.parametrize('name', ['status.json', 'manifest.json', 'journal.jsonl',
                                 '.submit-claim', 'submission.json', 'submission-summary.json'])
def test_symlinks_never_qualify_as_absent_or_trusted_evidence(cfg, prepared, selector, tmp_path, name):
    path, _ = prepared
    historical_journal(path)
    target = path.parent.parent / name if name == 'journal.jsonl' else path / name
    other = tmp_path / 'redirected'
    if target.exists():
        other.write_bytes(target.read_bytes())
        target.unlink()
    target.symlink_to(other)
    with pytest.raises((ValueError, OSError)):
        accounting.read_reservations(cfg)


def test_same_byte_status_replacement_refuses(cfg, prepared, selector, monkeypatch):
    path, _ = prepared
    historical_journal(path)
    original = accounting.disk.Store.read
    changed = False

    def replacing(store, name):
        nonlocal changed
        raw = original(store, name)
        if name == 'status.json' and accounting._CAPTURE_READS.get() is not None and not changed:
            changed = True
            temporary = path / 'replacement-status'
            temporary.write_bytes(raw)
            os.replace(temporary, path / name)
        return raw

    monkeypatch.setattr(accounting.disk.Store, 'read', replacing)
    with pytest.raises(ValueError, match='Evidence changed'):
        accounting.read_reservations(cfg)
    assert changed


def test_new_summary_after_absence_check_refuses(cfg, prepared, selector, monkeypatch):
    path, _ = prepared
    historical_journal(path)
    original = accounting._manifest_bytes

    def inserting(target):
        result = original(target)
        (target / 'submission-summary.json').write_text('{}')
        return result

    monkeypatch.setattr(accounting, '_manifest_bytes', inserting)
    with pytest.raises(ValueError, match='Evidence directory changed'):
        accounting.read_reservations(cfg)


def test_owned_prepared_never_downgrades_to_manual(cfg, prepared, selector):
    path, _ = prepared
    saved, current = install_owned(cfg, path, selector[0])
    (path / '.submit-claim').unlink()
    (path / 'submission-summary.json').unlink()
    historical_journal(path)
    with pytest.raises((ValueError, OSError)):
        accounting.read_reservations(cfg, states=supplied(path, current))
    assert saved['record']['attempt_id'] == path.name


def test_consumption_missing_global_record_cannot_use_compatibility(cfg, prepared, selector):
    path, _ = prepared
    historical_journal(path)
    current = {'submissions': {path.name: {'ownership_sha256': 'a' * 64}}}
    with pytest.raises(ValueError, match='missing its global reservation'):
        accounting.read_reservations(cfg, states=supplied(path, current))


@pytest.mark.parametrize('damage', [
    'empty', 'size_bool', 'size_negative', 'size_string', 'missing_field',
    'extra_field', 'bad_hash', 'nonstring_name', 'not_list', 'nondict_item',
])
def test_unconsumed_preserves_input_manifest_shape_checks(cfg, prepared, selector, damage):
    path, manifest = prepared
    historical_journal(path)
    # One byte makes bool True compare equal to an actual size of 1 unless
    # the exact integer check from the regular audit is retained.
    for source in (path / 'inputs').iterdir():
        source.unlink()
    files = {} if damage == 'empty' else {'synthetic.dat': b'x'}
    for name, raw in files.items():
        (path / 'inputs' / name).write_bytes(raw)
    manifest['inputs'], manifest['bundle_sha256'] = accounting.attempt.bundle(files)
    if damage.startswith('size_'):
        manifest['inputs'][0]['size'] = {'size_bool': True, 'size_negative': -1, 'size_string': '1'}[damage]
    elif damage == 'missing_field':
        del manifest['inputs'][0]['sha256']
    elif damage == 'extra_field':
        manifest['inputs'][0]['unrecognized'] = True
    elif damage == 'bad_hash':
        manifest['inputs'][0]['sha256'] = 'invalid'
    elif damage == 'nonstring_name':
        manifest['inputs'][0]['name'] = 1
    elif damage == 'not_list':
        manifest['inputs'] = {}
    elif damage == 'nondict_item':
        manifest['inputs'] = [None]
    (path / 'manifest.json').write_text(json.dumps(manifest))
    before = tree(path.parent.parent)
    with pytest.raises(ValueError, match='Invalid input file manifest'):
        accounting.read_reservations(cfg)
    assert tree(path.parent.parent) == before
