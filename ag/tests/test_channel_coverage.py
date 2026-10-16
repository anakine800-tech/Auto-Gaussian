"""Synthetic saved manifests only: no study data, configuration or cluster."""

import csv
from hashlib import sha256
import json

import pytest

from ag import channel_coverage as coverage, cli
from ag import _review_manifest as inventory


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')


def layer(energy, ambiguous=False):
    return dict(attempts=['synthetic-attempt'], ambiguous=ambiguous,
                energy_hartree=energy, relative_kcal=None)


def candidate(number, sp=None, opt=None, thermo=None, sources=None):
    return dict(candidate=number, xyz_frame=number, geometry_sha256='a' * 64,
                sources=sources or ['crest'], route_members=[], xtb_relative_kcal=float(number - 1),
                sp=sp, opt=opt, thermo=thermo, missing=[], notes=[])


def manifest(root, name, candidates, **overrides):
    path = root / 'analyses' / name
    payload = dict(schema='ag-ensemble/1', study_id=root.name, label='Synthetic candidates',
                   inputs={}, charge=0, hydrogens='all', energy_basis='shared_hartree',
                   units=dict(energy='Hartree', relative='kcal/mol', population='fraction'),
                   routes=[dict(label=r, attempts=[]) for r in ('crest', 'directed', 'unused')],
                   references=dict(xtb=None, sp=None, opt=None), warnings=[],
                   candidates=candidates, unmatched_attempts=[])
    payload.update(overrides)
    write_json(path, payload)
    return path


def channels(root, rows):
    path = root / 'analyses/channels.csv'
    with path.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.writer(stream)
        writer.writerow(['channel_id', 'product_branch', 'ensemble_manifests', 'note'])
        writer.writerows(rows)
    return path


@pytest.fixture
def sample(tmp_path, monkeypatch):
    root = tmp_path / 'synthetic-study'
    (root / 'analyses').mkdir(parents=True)
    (root / 'study.md').write_text('# Synthetic study\n')
    monkeypatch.setattr(cli, 'load_config', lambda **kw: pytest.fail('no configuration'))
    monkeypatch.setattr('ag.transport.SSHTransport', lambda *a, **kw: pytest.fail('no SSH'))
    for name, count, nsp, nopt in [('a', 8, 6, 4), ('b', 4, 2, 2), ('c', 2, 1, 1), ('d', 1, 0, 0)]:
        rows = [candidate(i + 1, sp=layer(-20 - i) if i < nsp else None,
                          opt=layer(-10 - i) if i < nopt else None,
                          sources=['crest', 'directed'] if i == 0 else ['crest']) for i in range(count)]
        manifest(root, name + '.json', rows)
    table = channels(root, [(c, branch, f'analyses/{c}.json', '')
                            for c, branch in [('a', 'R'), ('b', 'R'), ('c', 'S'), ('d', 'S')]])
    return root, table, root / 'analyses/coverage.json'


def build(sample, **kw):
    root, table, out = sample
    return coverage.build(table, out, study=str(root), **kw)


def test_four_channels_two_branches_and_ratio(sample):
    root, _, out = sample
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in root.rglob('*') if p.is_file()}
    result = build(sample)
    assert result['schema'] == 'ag-channel-coverage/1'
    a, b, c, d = result['channels']
    assert (a['manifest_count'], a['candidate_count'], a['sp_count'], a['opt_count']) == (1, 8, 6, 4)
    assert a['by_route'] == {'crest': 8, 'directed': 1, 'unused': 0}
    assert not a['imbalances']
    assert {i['metric'] for i in b['imbalances']} == {'sp_count'}  # equality does not flag
    assert {i['metric'] for i in d['imbalances']} == set(coverage.METRICS)
    r, s = result['product_branches']
    assert (r['manifest_count'], r['candidate_count'], r['sp_count'], r['opt_count']) == (2, 12, 8, 6)
    assert (s['candidate_count'], s['sp_count'], s['opt_count']) == (3, 1, 1)
    assert len(s['imbalances']) == 3
    assert r['lowest']['candidate'] == 4 and r['lowest']['layer'] == 'opt'
    relaxed = coverage.build(sample[1], root / 'analyses/relaxed.json', imbalance_ratio=0.1)
    assert not relaxed['product_branches'][1]['imbalances']
    assert {i['metric'] for i in relaxed['channels'][3]['imbalances']} == {'sp_count', 'opt_count'}
    disabled = coverage.build(sample[1], root / 'analyses/disabled.json', imbalance_ratio=0)
    assert all(not r['imbalances'] for r in disabled['channels'] + disabled['product_branches'])
    assert before == {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in before}
    assert json.loads(out.read_text()) == result
    text = out.with_suffix('.md').read_text()
    assert 'candidate_count: 1 &lt; 4.0' in text and '产物分支' in text and '最低候选' in text
    assert str(root) not in text + out.read_text()


@pytest.mark.parametrize('highest', coverage.LAYERS)
def test_energy_hierarchy_and_provenance(sample, highest):
    root, _, _ = sample
    rows = [candidate(7, sources=['crest', 'directed']), candidate(3)]
    # Deliberately make lower layers more negative: do not compare across layers.
    for layer_name in coverage.LAYERS[coverage.LAYERS.index(highest):]:
        for i, row in enumerate(rows):
            if layer_name == 'thermo':
                row['thermo'] = dict(attempt='synthetic', qh_G=-1 - i, relative_G_kcal=None, population=None)
            elif layer_name in ('opt', 'sp'):
                row[layer_name] = layer(-100 - i)
            else:
                row['xtb_relative_kcal'] = 1 - i
    manifest(root, 'a.json', rows)
    result = build(sample)['channels'][0]
    minimum = result['lowest']
    assert minimum['layer'] == highest and minimum['candidate'] == 3
    assert minimum['manifest']['path'] == 'analyses/a.json'
    assert minimum['manifest']['sha256'] == sha256((root / 'analyses/a.json').read_bytes()).hexdigest()
    assert minimum['routes'] == ['crest'] and minimum['channel_id'] == 'a'


def test_multiple_manifests_ambiguity_and_unknown_energy(sample):
    root, _, _ = sample
    ambiguous = candidate(9, sp=layer(None, True), opt=layer(None, True))
    unknown = candidate(10, opt=layer(None), thermo=dict(qh_G=None))
    manifest(root, 'extra.json', [ambiguous, unknown], energy_basis='per_source_not_comparable',
             warnings=['Saved warning'], unmatched_attempts=[dict(layer='thermo', attempt='extra', reason='unmatched')])
    channels(root, [('a', 'R', 'analyses/a.json; analyses/extra.json', 'two manifests')])
    row = build(sample)['channels'][0]
    assert (row['manifest_count'], row['candidate_count'], row['sp_count'], row['opt_count'],
            row['thermo_count'], row['ambiguous_count'], row['unmatched_attempts_count']) == (2, 10, 7, 6, 1, 1, 1)
    assert row['lowest']['layer'] == 'opt' and row['lowest']['candidate'] == 4
    assert row['lowest_by_manifest'][1]['lowest'] is None
    assert any('per_source_not_comparable' in w['message'] for w in row['warnings'])
    assert any(w['message'] == 'Saved warning' for w in row['warnings'])


def test_xtb_zeros_cannot_be_compared_across_manifests(sample):
    root, _, _ = sample
    manifest(root, 'a.json', [candidate(4), candidate(1)])
    manifest(root, 'b.json', [candidate(2), candidate(1)])
    channels(root, [('a', 'R', 'analyses/a.json;analyses/b.json', '')])
    row = build(sample)['channels'][0]
    assert row['lowest'] is None
    assert row['lowest_unavailable_reason'] == 'xtb_relative_energies_have_different_manifest_zeros'
    assert [m['lowest']['candidate'] for m in row['lowest_by_manifest']] == [1, 1]


def test_empty_manifests_and_equal_energy_ties(sample):
    root, _, _ = sample
    manifest(root, 'a.json', [])
    manifest(root, 'b.json', [candidate(8, sp=layer(-5)), candidate(2, sp=layer(-5))])
    manifest(root, 'c.json', [candidate(1, sp=layer(-5))])
    result = build(sample)
    assert result['channels'][0]['lowest'] is None
    assert result['channels'][1]['lowest']['candidate'] == 2
    assert result['channels'][0]['by_route']['unused'] == 0
    # Branch tie is stable by manifest path, then candidate number.
    assert result['product_branches'][0]['lowest']['manifest']['path'] == 'analyses/b.json'


@pytest.mark.parametrize('text,line', [
    ('channel_id,product_branch\na,R\n', 1),
    ('channel_id,product_branch,ensemble_manifests\na,,analyses/a.json\n', 2),
    ('channel_id,product_branch,ensemble_manifests\na,R,\n', 2),
    ('channel_id,product_branch,ensemble_manifests\na,R,analyses/a.json;\n', 2),
    ('channel_id,product_branch,ensemble_manifests\n', 2),
    ('channel_id,product_branch,ensemble_manifests\n\n', 2),
    ('channel_id,product_branch,ensemble_manifests\na,R\n', 2),
    ('channel_id,product_branch,ensemble_manifests\na,R,analyses/a.json,extra\n', 2),
    ('channel_id,product_branch,ensemble_manifests\na,R,analyses/a.json\na,S,analyses/b.json\n', 3),
    ('channel_id,product_branch,ensemble_manifests,channel_id\n', 1),
    ('channel_id,product_branch,ensemble_manifests\na,R,"unterminated\n', 2),
])
def test_csv_errors_include_row(sample, text, line):
    sample[1].write_text(text)
    with pytest.raises(ValueError, match=f'CSV row {line}:'):
        build(sample)
    assert not sample[2].exists()


def test_optional_note_bom_and_multiline_row_number(sample):
    sample[1].write_text('\ufeffchannel_id,product_branch,ensemble_manifests\na,R,analyses/a.json\n')
    assert build(sample)['channels'][0]['note'] == ''
    sample[1].write_text('channel_id,product_branch,ensemble_manifests,note\na,R,analyses/a.json,"first\nsecond"\nb,,analyses/b.json,bad\n')
    with pytest.raises(ValueError, match='CSV row 4:'):
        coverage.build(sample[1], sample[2].with_name('other.json'))


@pytest.mark.parametrize('paths', [('analyses/a.json', 'analyses/a.json'),
                                    ('analyses/a.json;analyses/a.json', 'analyses/b.json')])
def test_duplicate_manifest_rejected(sample, paths):
    channels(sample[0], [('a', 'R', paths[0], ''), ('b', 'S', paths[1], '')])
    with pytest.raises(ValueError, match='Duplicate manifest'):
        build(sample)


@pytest.mark.parametrize('change,match', [
    ({'schema': 'other/1'}, 'schema'), ({'study_id': 'different-study'}, 'study_id'),
    ({'energy_basis': 'unknown'}, 'energy_basis'), ({'candidates': {}}, 'lists'),
    ({'units': {'energy': 'eV'}}, 'units'), ({'warnings': None}, 'warnings'),
])
def test_invalid_manifest(sample, change, match):
    path = sample[0] / 'analyses/a.json'
    value = json.loads(path.read_text())
    value.update(change)
    write_json(path, value)
    with pytest.raises(ValueError, match=match):
        build(sample)
    assert not sample[2].exists()


@pytest.mark.parametrize('kind', ['missing', 'link', 'parent-link', 'escape', 'absolute'])
def test_unsafe_or_missing_manifest_paths(sample, kind, tmp_path):
    root, _, _ = sample
    outside = tmp_path / 'outside.json'
    outside.write_text('must never be read')
    value = 'analyses/missing.json'
    if kind == 'link':
        (root / value).symlink_to(outside)
    elif kind == 'parent-link':
        (root / 'analyses/link').symlink_to(tmp_path, target_is_directory=True)
        value = 'analyses/link/outside.json'
    elif kind == 'escape':
        value = '../outside.json'
    elif kind == 'absolute':
        value = str(root / 'analyses/a.json')
    channels(root, [('a', 'R', value, '')])
    with pytest.raises(ValueError, match='CSV row 2:'):
        build(sample)
    assert not sample[2].exists()


@pytest.mark.parametrize('target', ['csv', 'output', 'md', 'output-parent', 'root'])
def test_other_symlinks_rejected(sample, target, tmp_path):
    root, table, out = sample
    if target == 'csv':
        table.rename(root / 'analyses/real.csv')
        table.symlink_to(root / 'analyses/real.csv')
    elif target == 'output-parent':
        (root / 'analyses/link').symlink_to(tmp_path, target_is_directory=True)
        out = root / 'analyses/link/report.json'
    elif target == 'root':
        link = tmp_path / 'linked-study'
        link.symlink_to(root, target_is_directory=True)
        root = link
    else:
        (out if target == 'output' else out.with_suffix('.md')).symlink_to(tmp_path / 'missing')
    with pytest.raises(ValueError, match='Symbolic links'):
        coverage.build(table, out, study=str(root))


@pytest.mark.parametrize('ratio', [-1, 1.1, float('nan'), float('inf'), None, True])
def test_invalid_ratio(sample, ratio):
    with pytest.raises(ValueError):
        build(sample, imbalance_ratio=ratio)


@pytest.mark.parametrize('suffix', ['.json', '.md'])
def test_outputs_never_overwritten(sample, suffix):
    existing = sample[2].with_suffix(suffix)
    existing.write_bytes(b'preserve me')
    with pytest.raises(FileExistsError):
        build(sample)
    assert existing.read_bytes() == b'preserve me'
    assert not sample[2].with_suffix('.md' if suffix == '.json' else '.json').exists()


def test_collision_during_publication_leaves_no_partial_json(sample, monkeypatch):
    writer = coverage._write_outputs
    def raced(parent, payloads):
        sample[2].with_suffix('.md').write_text('concurrent output')
        writer(parent, payloads)
    monkeypatch.setattr(coverage, '_write_outputs', raced)
    with pytest.raises(FileExistsError):
        build(sample)
    assert not sample[2].exists()
    assert sample[2].with_suffix('.md').read_text() == 'concurrent output'


def test_changed_evidence_rejected(sample, monkeypatch):
    summary = coverage._summary
    def change(entries):
        sample[1].write_text('changed')
        return summary(entries)
    monkeypatch.setattr(coverage, '_summary', change)
    with pytest.raises(ValueError, match='Evidence changed'):
        build(sample)
    assert not sample[2].exists()


def test_cli_and_review_manifest_transitive_hashes(sample, capsys, monkeypatch):
    root, table, out = sample
    monkeypatch.chdir(root)
    assert cli.main(['channel-coverage', '--channels', 'analyses/channels.csv',
                     '--out', 'analyses/coverage.json']) == 0
    assert '通道采样覆盖' in capsys.readouterr().out
    (root / 'study.md').write_text('`analyses/coverage.json`\n')
    assert cli.main(['review', 'manifest', '--study', str(root), '--json']) == 0
    result = json.loads(capsys.readouterr().out)
    saved = json.loads((root / result['manifest']).read_text())
    included = {entry['path']: entry['sha256'] for entry in saved['files']}
    for path in (table, out, *(root / 'analyses' / f'{c}.json' for c in 'abcd')):
        assert included[path.relative_to(root).as_posix()] == sha256(path.read_bytes()).hexdigest()
    assert not saved.get('unresolved_references')
    assert cli.main(['channel-coverage', '--study', str(root), '--channels', 'analyses/channels.csv',
                     '--out', 'analyses/coverage.json']) == 1
    assert 'already exists' in capsys.readouterr().err


def test_cli_reports_malformed_manifest_without_traceback(sample, capsys):
    (sample[0] / 'analyses/a.json').write_text('[]')
    assert cli.main(['channel-coverage', '--channels', str(sample[1]), '--out', str(sample[2])]) == 1
    assert 'ag-ensemble/1' in capsys.readouterr().err
