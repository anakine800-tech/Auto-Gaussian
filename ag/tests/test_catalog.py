"""T119: synthetic water studies only; no configuration or network access."""
from concurrent.futures import ProcessPoolExecutor
from hashlib import sha256
import fcntl
import json
import multiprocessing
import os
from pathlib import Path

import pytest

from ag import catalog, cli


QUOTE = '  验证用，非研究结论\n保持逐字引用。  '


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')


def files(root):
    return {str(p.relative_to(root)): (p.read_bytes(), p.stat().st_mtime_ns)
            for p in root.rglob('*') if p.is_file()}


def make_attempt(root, suffix, route='# HF/STO-3G SP', *, status='fetched',
                 review='pass', template='gaussian', parents=(), **science):
    identity = f'{root.name}-{suffix}'
    path = root / 'attempts' / identity
    path.mkdir()
    write_json(path / 'manifest.json', dict(schema='ag-attempt/1', study_id=root.name,
               attempt_id=identity, template=template, parents=list(parents),
               science=dict(route=route, **science)))
    # Legacy PBS records avoid synthetic submission hashes unrelated to catalog.
    write_json(path / 'status.json', dict(state=status, job_id='1.fixture'))
    write_json(path / 'facts.json', dict(schema='ag-facts/1', units={'energy': 'Hartree'},
               route=route, freq_step_review=review, energies=dict(scf=-76.5, zpe=0.02, g=-76.48)))
    (path / 'review.md').write_text('Synthetic water review; no research acceptance.\n')
    return identity


@pytest.fixture
def water(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('catalog must not load credentials or create a remote transport')
    monkeypatch.setattr(catalog, 'load_config', forbidden)
    from ag.transport import SSHTransport
    monkeypatch.setattr(SSHTransport, '__init__', forbidden)
    root = tmp_path / 'water'
    root.mkdir()
    (root / 'attempts').mkdir()
    (root / 'analyses').mkdir()
    (root / 'study.md').write_text('# Synthetic water validation\n')
    return root


def obj(root, **kw):
    return catalog.change(root, 'object', id='water-a', name='Water A', **kw)


def adopt(root, identity, role='sp', **kw):
    return catalog.change(root, 'adopt', object='water-a', attempt=identity,
                          role=role, quote=QUOTE, **kw)


def test_lifecycle_chain_values_and_existing_files_unchanged(water):
    opt = make_attempt(water, '001-optfreq', '# HF/STO-3G Opt Freq')
    sp = make_attempt(water, '002-sp')
    before = files(water)
    obj(water, state_label='S0', multiplicity=1, conformer='A', note='water')
    catalog.change(water, 'member', object='water-a', attempt=opt, role='auto')
    adopt(water, opt, 'opt')
    adopt(water, opt, 'freq')
    result = adopt(water, sp)
    assert [e['op'] for e in result['events']] == ['member', 'adopt']
    data, events, _ = catalog.read_journal(water)
    assert len(events) == 6  # object + member + 3 adoptions + automatic SP member
    previous = None
    for seq, line in enumerate(data.splitlines(keepends=True), 1):
        event = json.loads(line)
        assert event['seq'] == seq and event['prev_sha256'] == previous
        previous = sha256(line).hexdigest()
    value, warnings = catalog.show(water)
    assert not warnings and value['journal_sha256'] == sha256(data).hexdigest()
    actual = value['objects'][0]
    assert actual['status'] == 'adopted' and actual['multiplicity'] == 1
    assert actual['adopted']['sp']['quote'] == QUOTE
    assert actual['values'] == dict(scf_h=-76.5, freq_scf_h=-76.5, zpe_h=0.02, g_h=-76.48,
                                   source=dict(scf_h=sp, freq_scf_h=opt, zpe_h=opt, g_h=opt))
    assert {k: files(water)[k] for k in before} == before
    assert value == json.loads((water / 'catalog/state.json').read_text())
    original_journal = data
    catalog.change(water, 'retire', object='water-a', reason='Validation complete')
    assert catalog.show(water)[0]['objects'][0]['status'] == 'retired'
    catalog.change(water, 'object', id='water-a', name='Renamed', update=True)
    retired = catalog.show(water)[0]['objects'][0]
    assert retired['name'] == 'Renamed' and retired['multiplicity'] == 1
    assert retired['status'] == 'retired' and retired['adopted']['sp']['attempt'] == sp
    assert (water / 'catalog/journal.jsonl').read_bytes().startswith(original_journal)


@pytest.mark.parametrize('freq_scf,unit,expected', [
    (-76.25, 'Hartree', -76.25),
    (None, 'Hartree', None),
    (float('nan'), 'Hartree', None),
    (-76.25, 'eV', None),
])
def test_freq_values_copy_their_own_source_without_sp_fallback(water, freq_scf, unit, expected):
    freq = make_attempt(water, '001-freq', '# HF/STO-3G Freq')
    sp = make_attempt(water, '002-sp', '# B3LYP/6-31G(d) SP')
    write_json(water / 'attempts' / freq / 'facts.json',
               dict(schema='ag-facts/1', units={'energy': unit}, freq_step_review='pass',
                    energies=dict(scf=freq_scf, zpe=0.02, g=-76.23)))
    before = files(water)
    obj(water)
    adopt(water, freq, 'freq')
    values = catalog.show(water)[0]['objects'][0]['values']
    assert values['scf_h'] is None and values['source']['scf_h'] is None
    adopt(water, sp)
    values = catalog.show(water)[0]['objects'][0]['values']
    assert values == dict(scf_h=-76.5, freq_scf_h=expected,
                          zpe_h=0.02 if unit == 'Hartree' else None,
                          g_h=-76.23 if unit == 'Hartree' else None,
                          source=dict(scf_h=sp, freq_scf_h=freq if expected is not None else None,
                                      zpe_h=freq if unit == 'Hartree' else None,
                                      g_h=freq if unit == 'Hartree' else None))
    assert {k: files(water)[k] for k in before} == before


@pytest.mark.parametrize('route,role,member_role', [
    ('# HF/STO-3G Opt Freq', 'freq', 'freq'),
    ('# HF/STO-3G Opt=(TS,CalcFC) Freq', 'freq', 'freq'),
    ('# HF/STO-3G Opt=(TS,CalcFC) Freq', 'opt', 'ts'),
])
def test_automatic_member_prefers_adoption_role(water, route, role, member_role):
    identity = make_attempt(water, '001-optfreq', route)
    obj(water)
    before = files(water)
    dry_run = adopt(water, identity, role, dry_run=True)
    assert dry_run['events'][0]['role'] == member_role and files(water) == before
    result = adopt(water, identity, role)
    assert [event['op'] for event in result['events']] == ['member', 'adopt']
    assert result['events'][0]['role'] == member_role
    assert catalog.show(water)[0]['objects'][0]['members'] == [dict(attempt=identity, role=member_role)]


def test_dry_run_all_operations_and_read_only_cli(water, capsys):
    identity = make_attempt(water, '001-sp')
    report = water / 'analyses/report.html'
    report.write_text('<p>Water</p>')
    before = files(water)
    assert cli.main(['catalog', 'object', str(water), '--id', 'water-a', '--name', 'Water', '--dry-run']) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['dry_run'] and result['checks']['study_exists']
    assert not (water / 'catalog').exists()
    assert cli.main(['catalog', 'show', str(water), '--json']) == 0
    assert json.loads(capsys.readouterr().out)['objects'] == []
    assert cli.main(['catalog', 'suggest', str(water)]) == 0
    assert 'ag catalog member' in capsys.readouterr().out
    assert files(water) == before
    obj(water)
    before = files(water)
    for op, fields in [('object', dict(id='water-a', name='Changed', update=True)),
                       ('member', dict(object='water-a', attempt=identity, role='auto')),
                       ('adopt', dict(object='water-a', attempt=identity, role='sp', quote=QUOTE)),
                       ('retire', dict(object='water-a', reason='Done')),
                       ('report-kind', dict(report='report.html', kind='formal'))]:
        assert catalog.change(water, op, dry_run=True, **fields)['events']
        assert files(water) == before
    assert cli.main(['catalog', 'show', str(water), '--json']) == 0
    assert json.loads(capsys.readouterr().out) == json.loads((water / 'catalog/state.json').read_text())
    assert cli.main(['catalog', 'show', str(water)]) == 0
    assert 'candidate' in capsys.readouterr().out
    assert files(water) == before


@pytest.mark.parametrize('status,route,review,role,message', [
    ('prepared', '# HF/STO-3G SP', 'pass', 'sp', 'fetched'),
    ('finished', '# HF/STO-3G SP', 'pass', 'sp', 'fetched'),
    ('fetched', '# HF/STO-3G Freq', 'fail', 'freq', 'freq_step_review=fail'),
    ('fetched', '# HF/STO-3G Opt', 'pass', 'sp', 'does not match'),
    ('fetched', '# HF/STO-3G Freq', 'pass', 'opt', 'does not match'),
    ('fetched', '# HF/STO-3G Opt Freq', 'pass', 'sp', 'does not match'),
])
def test_adopt_checks_are_before_any_events(water, status, route, review, role, message):
    identity = make_attempt(water, '001-calc', route, status=status, review=review)
    obj(water)
    before = files(water)
    with pytest.raises(ValueError, match=message):
        adopt(water, identity, role)
    assert files(water) == before


@pytest.mark.parametrize('quote', ['', ' \n ', '字' * 2001])
def test_quote_rejected_without_append(water, quote):
    identity = make_attempt(water, '001-sp')
    obj(water)
    before = files(water)
    with pytest.raises(ValueError, match='quote'):
        catalog.change(water, 'adopt', object='water-a', attempt=identity, role='sp', quote=quote)
    assert files(water) == before


def test_manual_review_and_ts_adoption(water, capsys):
    identity = make_attempt(water, '001-tsfreq', '# HF/STO-3G Opt=(TS,CalcFC) Freq', review='manual_review')
    obj(water)
    adopt(water, identity, 'opt')
    assert cli.main(['catalog', 'adopt', str(water), '--object', 'water-a', '--role', 'freq',
                     '--attempt', identity, '--quote', QUOTE]) == 0
    output = capsys.readouterr()
    assert 'WARNING' in output.err and 'manual_review' in output.err
    event = json.loads(output.out)['events'][0]
    assert event['checks']['freq_review'] == 'manual_review' and event['quote'] == QUOTE


@pytest.mark.parametrize('damage', ['missing', 'json', 'array', 'schema'])
def test_facts_must_be_readable(water, damage):
    identity = make_attempt(water, '001-sp')
    path = water / 'attempts' / identity / 'facts.json'
    if damage == 'missing':
        path.unlink()
    else:
        path.write_text({'json': '{', 'array': '[]', 'schema': '{}'}[damage])
    obj(water)
    with pytest.raises(ValueError, match='facts not readable'):
        adopt(water, identity)


def test_exact_identity_study_membership_and_object_updates(water, tmp_path):
    identity = make_attempt(water, '001-sp')
    obj(water)
    for bad in ['001', identity[:8], '../water-001-sp', 'other-001-sp']:
        with pytest.raises(ValueError):
            catalog.change(water, 'member', object='water-a', attempt=bad, role='auto')
    other = tmp_path / 'other'
    other.mkdir()
    (other / 'attempts').mkdir()
    other_id = make_attempt(other, '001-sp')
    with pytest.raises(ValueError, match='does not exist in this study'):
        adopt(water, other_id)
    path = water / 'attempts' / identity / 'manifest.json'
    data = json.loads(path.read_text())
    data['study_id'] = 'other'
    write_json(path, data)
    with pytest.raises(ValueError, match='invalid manifest'):
        adopt(water, identity)
    with pytest.raises(ValueError, match='already exists'):
        obj(water)
    with pytest.raises(ValueError, match='update ID missing'):
        catalog.change(water, 'object', id='absent', name='Absent', update=True)
    with pytest.raises(ValueError, match='positive integer'):
        catalog.change(water, 'object', id='second', name='Second', multiplicity=0)


@pytest.mark.parametrize('route,expected', [
    ('# HF/STO-3G Opt Freq', ['opt', 'freq']),
    ('#p HF/STO-3G OPT = (TS, CalcFC) FREQ', ['ts', 'freq']),
    ('# HF/STO-3G opt(qst2)', ['ts']),
    ('# HF/STO-3G Freq', ['freq']),
    ('# HF/STO-3G Stable=Opt', ['stable']),
    ('# HF/STO-3G IRC=(Forward,CalcFC)', ['irc']),
    ('# HF/STO-3G Scan', ['scan']),
    ('# HF/STO-3G', ['sp']),
    ('# HF/STO-3G Opt SP', ['opt']),
    ('', []),
])
def test_inferred_gaussian_roles(route, expected):
    assert catalog.infer_roles(dict(template='gaussian', science=dict(route=route))) == expected


def test_member_inference_and_force_cannot_bypass_adoption(water):
    identity = make_attempt(water, '001-opt', '# HF/STO-3G Opt Freq')
    obj(water)
    with pytest.raises(ValueError, match='force-role'):
        catalog.change(water, 'member', object='water-a', attempt=identity, role='sp')
    result = catalog.change(water, 'member', object='water-a', attempt=identity, role='sp', force_role=True)
    assert result['events'][0]['force_role'] is True
    with pytest.raises(ValueError, match='does not match'):
        adopt(water, identity)
    catalog.change(water, 'member', object='water-a', attempt=identity, role='freq')
    assert catalog.show(water)[0]['objects'][0]['members'] == [dict(attempt=identity, role='freq')]
    unknown = make_attempt(water, '002-other', template='multiwfn')
    with pytest.raises(ValueError, match='Cannot infer role'):
        catalog.change(water, 'member', object='water-a', attempt=unknown, role='auto')
    catalog.change(water, 'member', object='water-a', attempt=unknown, role='other')
    for template, params, science, expected in [
        ('crest', {}, {}, ['crest']), ('xtb', {}, {}, ['sp']),
        ('xtb', {'--opt': 'tight'}, {}, ['opt']),
        ('xtb', {}, {'scan': {'points': 3}}, ['scan']),
        ('gaussian', {}, {'scan': {'points': 3}}, ['scan'])]:
        assert catalog.infer_roles(dict(template=template, template_params=params, science=science)) == expected


@pytest.mark.parametrize('damage', ['seq', 'hash', 'partial', 'blank', 'op'])
def test_corruption_blocks_writes_and_show_without_repair(water, damage):
    obj(water)
    catalog.change(water, 'retire', object='water-a', reason='Done')
    path = water / 'catalog/journal.jsonl'
    lines = path.read_bytes().splitlines(keepends=True)
    value = json.loads(lines[-1])
    if damage == 'seq':
        value['seq'] += 1
    elif damage == 'hash':
        value['prev_sha256'] = '0' * 64
    elif damage == 'op':
        value['op'] = 'delete'
    lines[-1] = catalog.encode(value)
    data = b''.join(lines)
    path.write_bytes(data[:-1] if damage == 'partial' else data + b'\n' if damage == 'blank' else data)
    before = files(water)
    for action in [lambda: obj(water, update=True), lambda: catalog.show(water), lambda: catalog.suggest(water)]:
        with pytest.raises(ValueError, match='journal damaged'):
            action()
    assert files(water) == before


def test_report_boundaries_normalization_and_adoption(water, tmp_path):
    report = water / 'analyses' / 'report.html'
    report.write_text('<p>Water</p>')
    (water / 'analyses/sub').mkdir()
    (water / 'analyses/link').symlink_to(water / 'study.md')
    obj(water)
    for bad in ['../study.md', str(water / 'study.md'), 'missing.html', '.', 'link']:
        with pytest.raises(ValueError):
            catalog.change(water, 'report-kind', report=bad, kind='formal')
    catalog.change(water, 'report-kind', report='analyses/sub/../report.html', kind='formal')
    assert catalog.show(water)[0]['report_kinds'] == {'report.html': 'formal'}
    identity = make_attempt(water, '001-sp')
    with pytest.raises(ValueError):
        adopt(water, identity, report='../study.md')
    adopt(water, identity, report='analyses/report.html')
    assert catalog.show(water)[0]['objects'][0]['adopted']['sp']['report'] == 'report.html'


@pytest.mark.parametrize('location', ['catalog', 'lock', 'journal', 'state', 'attempt', 'facts'])
def test_symlinks_never_followed(water, tmp_path, location):
    identity = make_attempt(water, '001-sp')
    obj(water)
    outside = tmp_path / 'outside'
    outside.write_text('unchanged')
    path = {'catalog': water / 'catalog', 'lock': water / 'catalog/catalog.lock',
            'journal': water / 'catalog/journal.jsonl', 'state': water / 'catalog/state.json',
            'attempt': water / 'attempts' / identity,
            'facts': water / 'attempts' / identity / 'facts.json'}[location]
    path.rename(path.with_name(path.name + '-old'))
    path.symlink_to(outside)
    with pytest.raises(ValueError, match='[Ss]ymbolic links'):
        adopt(water, identity)
    assert outside.read_text() == 'unchanged'


def test_suggest_connected_components_and_no_writes(water):
    first = make_attempt(water, '001-opt', '# HF/STO-3G Opt')
    second = make_attempt(water, '002-freq', '# HF/STO-3G Freq',
                          parents=[dict(attempt_id=first, relation='freq-from-opt')])
    third = make_attempt(water, '003-sp', parents=[dict(attempt_id=first, relation='sp-from-opt')])
    orphan = make_attempt(water, '004-sp', parents=[dict(attempt_id='missing', relation='sp-from-opt')])
    before = files(water)
    result = catalog.suggest(water)
    assert result['suggestions'][0]['members'] == [first, second, third]
    assert len(result['suggestions'][0]['parents']) == 2
    assert result['suggestions'][1]['members'] == [orphan]
    assert result['missing_parents'] == [dict(parent='missing', child=orphan)]
    assert files(water) == before and not (water / 'catalog').exists()
    catalog.change(water, 'object', id='object-1', name='Assigned')
    catalog.change(water, 'member', object='object-1', attempt=first, role='auto')
    result = catalog.suggest(water)
    assert all(s['id'] != 'object-1' and first not in s['members'] for s in result['suggestions'])
    # Synthetic cycle is displayed once as one component, without recursion.
    path = water / 'attempts' / second / 'manifest.json'
    manifest = json.loads(path.read_text())
    manifest['parents'] = [dict(attempt_id=third, relation='test')]
    write_json(path, manifest)
    path = water / 'attempts' / third / 'manifest.json'
    manifest = json.loads(path.read_text())
    manifest['parents'] = [dict(attempt_id=second, relation='test')]
    write_json(path, manifest)
    assert catalog.suggest(water)['suggestions'][0]['members'] == [second, third]


def process_object(root, number):
    return catalog.change(Path(root), 'object', id=f'water-{number}', name=f'Water {number}')


def test_two_processes_serialize(water):
    with ProcessPoolExecutor(max_workers=2, mp_context=multiprocessing.get_context('spawn')) as pool:
        results = list(pool.map(process_object, [str(water)] * 12, range(12)))
    assert len(results) == 12
    _, events, _ = catalog.read_journal(water)
    assert [e['seq'] for e in events] == list(range(1, 13))
    assert len(catalog.show(water)[0]['objects']) == 12


def test_state_publication_failure_preserves_journal_and_warns(water, monkeypatch):
    obj(water)
    path = water / 'catalog/state.json'
    saved = path.read_bytes()
    def fail(*args):
        raise OSError('synthetic disk failure')
    monkeypatch.setattr(os, 'replace', fail)
    with pytest.raises(OSError, match='journal appended'):
        catalog.change(water, 'retire', object='water-a', reason='Done')
    assert path.read_bytes() == saved
    assert len(catalog.read_journal(water)[1]) == 2
    value, warnings = catalog.show(water)
    assert value['objects'][0]['status'] == 'candidate' and 'stale' in warnings[0]


def test_no_opt_energy_fallback_missing_values_and_latest_adoption(water):
    opt = make_attempt(water, '001-opt', '# HF/STO-3G Opt')
    first, second = make_attempt(water, '002-sp'), make_attempt(water, '003-sp')
    obj(water)
    adopt(water, opt, 'opt')
    assert catalog.show(water)[0]['objects'][0]['values']['scf_h'] is None
    adopt(water, first)
    path = water / 'attempts' / second / 'facts.json'
    write_json(path, dict(schema='ag-facts/1', units={'energy': 'Hartree'}, energies={'scf': None}))
    adopt(water, second)
    value = catalog.show(water)[0]['objects'][0]
    assert value['adopted']['sp']['attempt'] == second
    assert value['values']['scf_h'] is None and value['values']['source']['scf_h'] is None
    assert sum(e['op'] == 'adopt' for e in catalog.read_journal(water)[1]) == 3


def test_study_name_uses_only_local_config(water, monkeypatch):
    calls = []
    def config(**kwargs):
        calls.append(kwargs)
        return {'local': {'studies_root': str(water.parent)}}
    monkeypatch.setattr(catalog, 'load_config', config)
    assert catalog.show('water')[0]['objects'] == []
    assert calls == [dict(local_only=True)]
    with pytest.raises(ValueError, match='Study must exist'):
        catalog.show(water.parent / 'absent')


@pytest.mark.parametrize('kind', ['coverage', 'ts', 'nci'])
def test_new_report_kinds_accept_cli_and_preserve_old_events(water, capsys, kind):
    (water / 'analyses/old.html').write_text('<p>Water</p>')
    (water / 'analyses/new.html').write_text('<p>Water</p>')
    catalog.change(water, 'report-kind', report='old.html', kind='formal')
    old_data, old_events, _ = catalog.read_journal(water)
    assert cli.main(['catalog', 'report-kind', str(water), '--report', 'new.html', '--kind', kind]) == 0
    assert json.loads(capsys.readouterr().out)['events'][0]['kind'] == kind
    data, events, _ = catalog.read_journal(water)
    assert data.startswith(old_data) and events[:-1] == old_events
    assert catalog.replay(events)[1] == {'old.html': 'formal', 'new.html': kind}
    assert catalog.show(water)[0]['report_kinds'] == {'old.html': 'formal', 'new.html': kind}


def test_catalog_reads_and_writes_lock_same_file_and_ignore_legacy(water, monkeypatch):
    directory = water / 'catalog'
    directory.mkdir()
    legacy = directory / 'submit.lock'
    legacy.write_text('legacy lock retained')
    before = legacy.read_bytes(), legacy.stat().st_mtime_ns
    calls = []
    real_flock = fcntl.flock
    # Check exclusion after the real lock is acquired.
    def checked_flock(handle, operation):
        real_flock(handle, operation)
        if operation != fcntl.LOCK_UN:
            calls.append((Path(handle.name).name, operation))
            with (directory / 'catalog.lock').open('rb') as contender:
                with pytest.raises(BlockingIOError):
                    real_flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)
    monkeypatch.setattr(catalog.fcntl, 'flock', checked_flock)
    # A held legacy lock neither blocks nor gets read by the new implementation.
    with legacy.open('rb') as old:
        real_flock(old, fcntl.LOCK_EX | fcntl.LOCK_NB)
        obj(water)
        catalog.show(water)
        catalog.suggest(water)
        obj(water, update=True, dry_run=True)
    assert calls == [('catalog.lock', fcntl.LOCK_EX)] + [('catalog.lock', fcntl.LOCK_SH)] * 3
    assert (legacy.read_bytes(), legacy.stat().st_mtime_ns) == before
    assert (directory / 'catalog.lock').exists()
