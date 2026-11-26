"""Run the named PBS diagnostic through the CLI with isolated local evidence."""
from contextlib import nullcontext
from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil

import pytest

from ag import attempt, autonomy, autonomy_submission as accounting, cli, config, route, study, submit
from test_core import Fake, allow, cfg, prepared
from test_t216_reservation_audit import forbid_writes_and_locks, snapshot


@pytest.fixture
def inspect_pbs(cfg, monkeypatch, capsys):
    monkeypatch.setattr(config, 'load_config', lambda: cfg)
    monkeypatch.setattr(config, 'ssh_identity', lambda _: ('fixture', 22, 'fixture'))

    def inspect(entry='default'):
        code = cli.main(['autonomy', 'audit-reservations', '--cluster', entry, '--json'])
        result = json.loads(capsys.readouterr().out)
        assert code == int(not result['ok'])
        assert result['action_permitted'] is False and result['pbs']['scheduler_queried'] is False
        return result

    return inspect


def other_config(cfg, root):
    other = deepcopy(cfg)
    other['local']['studies_root'] = str(root)
    return other


def register(cfg, name, count=1):
    study.init(cfg, name)
    for _ in range(count):
        with autonomy.manual_write_guard(cfg, name):
            pass
    return Path(cfg['local']['studies_root']) / name


def test_missing_groups_show_their_roots_and_never_a_partial_balance(
        cfg, prepared, tmp_path, monkeypatch, inspect_pbs):
    _, manifest = prepared
    allow(monkeypatch)
    submit.submit(cfg, [manifest['attempt_id']], Fake(cfg))
    detached = []
    for count in (7, 1):
        root = tmp_path / f'old-studies-{count}'
        path = register(other_config(cfg, root), 'snapshot', count)
        key = sha256(str(path).encode()).hexdigest()
        detached.append((path, key, count))
        root.rename(root.with_suffix('.parked'))
    ledger = Path.home() / '.config/ag/manual-writers'
    before = snapshot(ledger)
    forbid_writes_and_locks(monkeypatch)
    result = inspect_pbs()
    assert not result['ok'] and not result['coverage']['complete']
    assert result['pbs']['local_placements'] is None
    refused = {r['registration_group']: r for r in result['records']
               if r['source'] == 'manual_writer_group' and r['classification'] == 'refused'}
    assert set(refused) == {key for _, key, _ in detached}
    for path, key, count in detached:
        row = refused[key]
        assert (row['stage'], row['claim_count']) == ('study_identity', count)
        assert row['claimed_study_path'] == str(path)
        assert row['required_studies_root'] == str(path.parent)
        assert (ledger / key / row['seed_claim']).is_file() and row['reasons']
    assert any('sibling' in error['reason'] for error in result['coverage']['errors'])
    assert snapshot(ledger) == before

    # The original directory objects include all their contents and siblings.
    for path, _, _ in detached:
        path.parent.with_suffix('.parked').rename(path.parent)
    restored = inspect_pbs()
    assert restored['ok'] and restored['coverage']['complete']
    placement, = restored['pbs']['local_placements']
    assert placement['account_binding'] == 'configured'
    assert (placement['attempt_id'], placement['cores']) == (manifest['attempt_id'], manifest['cores'])
    assert snapshot(ledger) == before


def test_unregistered_older_sibling_is_reported_even_without_account_binding(
        cfg, prepared, tmp_path, monkeypatch, inspect_pbs):
    other = other_config(cfg, tmp_path / 'historical-studies')
    register(other, 'anchor')
    study.init(other, 'older')
    with monkeypatch.context() as old:
        # Simulate the writer used before global manual registrations existed.
        old.setattr(autonomy, 'manual_write_guard', lambda *a, **k: nullcontext())
        manifest = attempt.prepare(other, method_basis='synthetic', study_name='older', template='gaussian',
                                   input_path=tmp_path / 'water.gjf', tier='simple', walltime='00:30:00', label='sp')
        allow(old)
        submit.submit(other, [manifest['attempt_id']], Fake(other))
    strict, = accounting.read_pbs_reservations(cfg)['placements']
    assert strict['unmapped_manual_account'] is True
    forbid_writes_and_locks(monkeypatch)
    result = inspect_pbs()
    assert result['ok']
    placement, = result['pbs']['local_placements']
    assert placement['account_binding'] == 'unmapped'
    assert all(placement[field] == strict[field] for field in ('study_key', 'attempt_id', 'state', 'cores', 'job_id'))
    assert placement['cores'] == manifest['cores']


def test_same_named_copy_is_still_blocked(cfg, prepared, tmp_path, monkeypatch, inspect_pbs):
    root = tmp_path / 'old-studies'
    register(other_config(cfg, root), 'snapshot')
    saved = root.with_suffix('.original')
    root.rename(saved)
    shutil.copytree(saved, root)
    forbid_writes_and_locks(monkeypatch)
    result = inspect_pbs()
    assert not result['ok'] and result['pbs']['local_placements'] is None
    refused, = [row for row in result['records']
                if row['source'] == 'manual_writer_group' and row['classification'] == 'refused']
    assert refused['stage'] == 'writer_evidence' and refused['required_studies_root'] == str(root)


def test_damaged_first_claim_keeps_an_independent_location_hint(cfg, prepared, tmp_path, monkeypatch, inspect_pbs):
    root = tmp_path / 'old-studies'
    path = register(other_config(cfg, root), 'snapshot', count=2)
    group = Path.home() / '.config/ag/manual-writers' / sha256(str(path).encode()).hexdigest()
    first, second = sorted(group.glob('*.claim.json'))
    first.write_bytes(b'{')
    root.rename(root.with_suffix('.parked'))
    forbid_writes_and_locks(monkeypatch)
    result = inspect_pbs()
    assert not result['ok'] and result['pbs']['local_placements'] is None
    refused, = [row for row in result['records']
                if row['source'] == 'manual_writer_group' and row['classification'] == 'refused']
    assert refused['seed_claim'] == first.name and refused['location_hint_claim'] == second.name
    assert refused['location_hint_study_path'] == str(path) and refused['required_studies_root'] == str(root)


def test_open_writer_diagnostic_refuses_without_probing_the_lock(cfg, prepared, monkeypatch, inspect_pbs):
    with autonomy.manual_write_guard(cfg, 'smoke'):
        with monkeypatch.context() as readonly:
            forbid_writes_and_locks(readonly)
            result = inspect_pbs()
    assert not result['ok'] and result['pbs']['local_placements'] is None
    assert any('no completion or release' in e['reason'] for e in result['coverage']['errors'])
    assert inspect_pbs()['ok']


def test_group_rotated_after_read_cannot_leak_a_partial_result(cfg, prepared, tmp_path, monkeypatch, inspect_pbs):
    root = tmp_path / 'old-studies'
    register(other_config(cfg, root), 'snapshot')
    normalize = route._placement_records

    def rotate(*args):
        root.rename(tmp_path / 'rotated')
        return normalize(*args)

    monkeypatch.setattr(route, '_placement_records', rotate)
    forbid_writes_and_locks(monkeypatch)
    result = inspect_pbs()
    assert not result['ok'] and not result['coverage']['complete']
    assert result['pbs']['local_placements'] is None
    assert any(row['source'] == 'consistency' for row in result['records'])


@pytest.mark.parametrize('entry,scheduler', [('missing', 'pbs'), ('default', 'slurm')])
def test_wrong_entry_cannot_succeed(cfg, monkeypatch, inspect_pbs, entry, scheduler):
    if scheduler == 'slurm':
        cfg['scheduler'] = 'slurm'
    forbid_writes_and_locks(monkeypatch)
    result = inspect_pbs(entry)
    assert not result['ok'] and result['pbs']['local_placements'] is None


def test_missing_ssh_identity_still_locates_historical_evidence(cfg, prepared, tmp_path, monkeypatch, inspect_pbs):
    root = tmp_path / 'old-studies'
    register(other_config(cfg, root), 'snapshot')
    root.rename(root.with_suffix('.parked'))
    monkeypatch.setattr(config, 'ssh_identity', lambda _: None)
    forbid_writes_and_locks(monkeypatch)
    result = inspect_pbs()
    assert not result['ok'] and result['pbs']['local_placements'] is None
    assert {'pbs_account', 'manual_writer_group'} <= {r['source'] for r in result['coverage']['errors']}


@pytest.mark.parametrize('damage', ['missing', 'link', 'hardlink'])
def test_existing_machine_mutex_is_checked_without_locking_or_repair(prepared, monkeypatch, inspect_pbs, damage):
    lock = Path.home() / '.config/ag/autonomy-submit.lock'
    if damage == 'hardlink':
        os.link(lock, lock.with_suffix('.alias'))
    else:
        saved = lock.with_suffix('.saved')
        lock.rename(saved)
        if damage == 'link':
            lock.symlink_to(saved)
    forbid_writes_and_locks(monkeypatch)
    result = inspect_pbs()
    assert not result['ok'] and result['pbs']['local_placements'] is None
    assert any(r['source'] == 'machine_mutex' for r in result['coverage']['errors'])


def test_configuration_rotation_refuses_placements_from_a_different_account(prepared, monkeypatch, inspect_pbs):
    identities = iter([('fixture', 22, 'first'), ('fixture', 22, 'second')])
    monkeypatch.setattr(config, 'ssh_identity', lambda _: next(identities))
    forbid_writes_and_locks(monkeypatch)
    result = inspect_pbs()
    assert not result['ok'] and result['pbs']['local_placements'] is None
    assert any('account identity changed' in r['reason'] for r in result['coverage']['errors'])


def test_named_entry_shares_verified_peer_jobs_once_and_excludes_other_accounts(
        cfg, prepared, monkeypatch, inspect_pbs):
    _, manifest = prepared
    allow(monkeypatch)
    submit.submit(cfg, [manifest['attempt_id']], Fake(cfg))
    entry = {key: val for key, val in cfg.items() if key not in ('local', '_config_dir')}
    other = deepcopy(entry)
    other['ssh']['host'] = 'synthetic-other'
    cfg['clusters'] = {'default': entry, 'peer': deepcopy(entry), 'other': other}
    monkeypatch.setattr(config, 'ssh_identity', lambda e: (e['ssh']['host'], 22, 'fixture'))
    forbid_writes_and_locks(monkeypatch)
    peer = inspect_pbs('peer')
    assert peer['ok'] and peer['pbs']['shared_entries'] == ['default', 'peer']
    job, = peer['pbs']['local_placements']
    assert job['attempt_id'] == manifest['attempt_id'] and job['cores'] == manifest['cores']
    other = inspect_pbs('other')
    assert other['ok'] and other['pbs']['local_placements'] == []
