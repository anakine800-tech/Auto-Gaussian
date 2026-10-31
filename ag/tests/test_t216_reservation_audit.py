"""Whole-scan diagnostics use isolated synthetic records and local fakes."""
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil

import pytest

from ag import autonomy, autonomy_submission as accounting, config
from ag import _autonomy_store as disk
from test_core import cfg, prepared
from test_autonomy_submission import selector, install_owned, supplied


def snapshot(root):
    result = {}
    for path in [root, *sorted(root.rglob('*'))]:
        info = path.lstat()
        result[str(path.relative_to(root))] = (info.st_mode, info.st_size, info.st_mtime_ns,
            path.read_bytes() if path.is_file() and not path.is_symlink() else None)
    return result


def clone(path, name, *, root=None, study_name=None):
    target = (root or path.parent.parent.parent) / (study_name or path.parent.parent.name) / 'attempts' / name
    shutil.copytree(path, target)
    value = json.loads((target / 'manifest.json').read_text())
    value.update(study_id=target.parent.parent.name, attempt_id=name)
    (target / 'manifest.json').write_text(json.dumps(value))
    return target


def attempts(result):
    return {row['attempt_id']: row for row in result['records'] if row['source'] == 'attempt'}


def forbid_writes_and_locks(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('Diagnostic attempted a write or lock')
    monkeypatch.setattr(accounting, 'machine_lock', forbidden)
    monkeypatch.setattr(disk, 'locked', forbidden)
    monkeypatch.setattr(accounting.fcntl, 'flock', forbidden)
    for name in ('exclusive', 'append', 'publish', 'commit'):
        monkeypatch.setattr(disk.Store, name, forbidden)


def test_multiple_errors_keep_later_success_and_available_metadata(cfg, prepared, selector, monkeypatch):
    path, manifest = prepared
    bad_status = clone(path, 'bad-status')
    bad_summary = clone(path, 'bad-summary')
    later = clone(path, 'zz-valid')
    (bad_status / 'status.json').write_text('{"state":"prepared","state":"unknown"}')
    (bad_summary / 'submission-summary.json').write_text('{}')
    before = snapshot(Path(cfg['local']['studies_root']))
    home_before = snapshot(Path.home())
    forbid_writes_and_locks(monkeypatch)
    result = accounting.audit_reservations(cfg)
    rows = attempts(result)
    assert result['ok'] is False and result['coverage']['complete'] is True
    assert rows[bad_status.name]['classification'] == 'refused'
    assert rows[bad_summary.name]['classification'] == 'refused'
    assert rows[later.name]['classification'] == 'manual_unconsumed_excluded'
    assert rows[bad_status.name]['state'] is None
    assert rows[bad_status.name]['cores'] == manifest['cores']
    assert rows[bad_summary.name]['state'] == 'prepared'
    assert rows[later.name]['tier'] == manifest['tier']
    assert rows[later.name]['warnings']
    assert snapshot(Path(cfg['local']['studies_root'])) == before
    assert snapshot(Path.home()) == home_before
    assert result['action_permitted'] is False


def test_bad_registry_entries_do_not_hide_cross_root_or_current_attempts(cfg, prepared, selector, tmp_path):
    path, _ = prepared
    other = clone(path, 'external-water', root=tmp_path / 'other-studies', study_name='other-water')
    accounting._register_study(other.parent.parent)
    directory = Path.home() / '.config/ag/autonomy-studies'
    (directory / 'a-bad.json').write_text('{')
    (directory / 'b-bad.json').write_text('[]')
    reservations = directory.parent / 'autonomy-reservations'
    reservations.mkdir()
    (reservations / 'a-bad.json').write_text('{"study_id":"water","attempt_id":"broken"}')
    result = accounting.audit_reservations(cfg)
    assert not result['ok'] and not result['coverage']['complete']
    rows = attempts(result)
    assert rows[path.name]['classification'] == 'manual_unconsumed_excluded'
    assert rows[other.name]['classification'] == 'manual_unconsumed_excluded'
    errors = [row for row in result['records'] if row['classification'] == 'refused']
    assert len(errors) == 3
    assert any(row['attempt_id'] == 'broken' for row in errors)


@pytest.mark.parametrize('broken', ['study-link', 'attempt-link', 'attempts-link', 'missing-root'])
def test_enumeration_failures_report_coverage_and_continue(cfg, prepared, selector, tmp_path, broken):
    path, _ = prepared
    later = clone(path, 'later', study_name='zz-later')
    root = Path(cfg['local']['studies_root'])
    if broken == 'study-link':
        (root / 'a-link').symlink_to(tmp_path / 'absent')
    elif broken == 'attempt-link':
        (path.parent / 'a-link').symlink_to(tmp_path / 'absent')
    elif broken == 'attempts-link':
        bad_study = root / 'a-study'
        bad_study.mkdir()
        (bad_study / 'attempts').symlink_to(tmp_path / 'absent')
    else:
        accounting._register_study(path.parent.parent)
        cfg = dict(cfg, local={'studies_root': str(tmp_path / 'missing')})
    result = accounting.audit_reservations(cfg)
    assert not result['ok']
    assert result['coverage']['complete'] is (broken == 'attempt-link')
    assert attempts(result)[later.name]['classification'] == 'manual_unconsumed_excluded'


def test_bad_study_state_refuses_all_its_attempts_but_keeps_other_study(cfg, prepared, selector):
    path, _ = prepared
    broken = path.parent.parent / 'autonomy'
    broken.mkdir()
    (broken / 'journal.jsonl').write_text('{')
    sibling = clone(path, 'sibling')
    later = clone(path, 'later', study_name='zz-water')
    result = accounting.audit_reservations(cfg)
    rows = attempts(result)
    assert not result['coverage']['complete']
    assert rows[path.name]['classification'] == rows[sibling.name]['classification'] == 'refused'
    assert rows[later.name]['classification'] == 'manual_unconsumed_excluded'


@pytest.mark.parametrize('damage', ['missing', 'symlink', 'hardlink'])
def test_state_replay_refuses_bad_lock_without_acquiring_or_recreating_it(cfg, prepared, selector, monkeypatch, damage):
    path, _ = prepared
    autonomy.initialize(cfg, path.parent.parent.name)
    lock = path.parent.parent / 'autonomy/store.lock'
    if damage == 'hardlink':
        os.link(lock, lock.with_name('alias'))
    else:
        lock.unlink()
        if damage == 'symlink':
            lock.symlink_to('state.json')
    before = snapshot(path.parent.parent)
    forbid_writes_and_locks(monkeypatch)
    result = accounting.audit_reservations(cfg)
    assert not result['ok'] and not result['coverage']['complete']
    assert snapshot(path.parent.parent) == before


def test_owned_classification_matches_submission_and_retains_failed_later_records(
        cfg, prepared, selector, monkeypatch):
    path, _ = prepared
    saved, current = install_owned(cfg, path, selector[0])
    # Synthetic replay result; ownership checks below still validate both sides.
    location = path.parent.parent / 'autonomy'
    location.mkdir()
    (location / 'store.lock').write_bytes(b'Synthetic persistent mutex\n')
    monkeypatch.setattr(autonomy, 'load', lambda store: ({'state': deepcopy(current)}, False))
    strict = accounting.read_reservations(cfg, states=supplied(path, current))
    before = snapshot(Path.home())
    forbid_writes_and_locks(monkeypatch)
    result = accounting.audit_reservations(cfg)
    row = attempts(result)[path.name]
    assert result['ok'], result
    assert row['classification'] == strict['records'][0]['outcome'] == 'retained'
    assert row['accounting_state'] == strict['placements'][0]['state'] == 'reserved'
    assert row['cores'] == strict['placements'][0]['cores']
    assert snapshot(Path.home()) == before
    current['submissions'][path.name]['ownership_sha256'] = '0' * 64
    result = accounting.audit_reservations(cfg)
    assert not result['ok']
    assert attempts(result)[path.name]['classification'] == 'refused'


def test_missing_configuration_still_scans_registered_studies(cfg, prepared, selector):
    path, _ = prepared
    accounting._register_study(path.parent.parent)
    result = accounting.audit_reservations(None, configuration_error='Synthetic missing configuration')
    assert not result['ok'] and not result['coverage']['complete']
    assert attempts(result)[path.name]['classification'] == 'manual_unconsumed_excluded'


@pytest.mark.parametrize('mutation', ['same_bytes', 'new_attempt', 'new_registry', 'new_autonomy'])
def test_end_of_scan_revalidation_detects_changes(cfg, prepared, selector, monkeypatch, mutation):
    path, _ = prepared
    original = accounting._manual_accounting
    def change(*args):
        result = original(*args)
        if mutation == 'same_bytes':
            target = path / 'status.json'
            replacement = path / 'replacement'
            replacement.write_bytes(target.read_bytes())
            replacement.replace(target)
        elif mutation == 'new_attempt':
            (path.parent / 'new-attempt').mkdir()
        elif mutation == 'new_registry':
            accounting._register_study(path.parent.parent)
        else:
            (path.parent.parent / 'autonomy').mkdir()
        return result
    monkeypatch.setattr(accounting, '_manual_accounting', change)
    result = accounting.audit_reservations(cfg)
    assert not result['ok'] and not result['coverage']['complete']
    assert any(row['source'] == 'consistency' for row in result['records'] if row['classification'] == 'refused')


def test_local_account_expansion_is_only_permitted_process(cfg, prepared, monkeypatch):
    calls = []
    def local_expansion(command, **kwargs):
        calls.append(command)
        assert command == ['ssh', '-G', '-F', cfg['ssh']['config_file'], cfg['ssh']['host']]
        class Result:
            returncode = 0
            stdout = 'hostname synthetic.invalid\nport 22\nuser synthetic\n'
        return Result()
    monkeypatch.setattr(config.subprocess, 'run', local_expansion)
    result = accounting.audit_reservations(cfg)
    assert result['ok'], result
    assert len(calls) == 1
