"""T53 synthetic butane evidence; no cluster or research data."""
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path

import pytest
from rdkit import Chem
from rdkit.Chem import AllChem, rdMolTransforms

from ag import ensemble, geometry as geo
from ag.cli import main


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False))


def attempt(root, frame, name, energy=-157.0, route='B3LYP/6-31G(d) SP', **facts):
    path = root / 'attempts' / name
    (path / 'inputs').mkdir(parents=True)
    rows = '\n'.join(geo.xyz_text([frame]).splitlines()[2:])
    raw = f'%nprocshared=1\n%mem=1GB\n# {route}\n\nSynthetic butane\n\n0 1\n{rows}\n\n'.encode()
    (path / 'inputs' / 'input.gjf').write_bytes(raw)
    write_json(path / 'manifest.json', {'template': 'gaussian', 'cores': 1, 'mem_gb': 2,
        'inputs': [{'name': 'input.gjf', 'sha256': sha256(raw).hexdigest()}]})
    write_json(path / 'facts.json', {'program': 'gaussian', 'termination': 'normal', 'n_imag': 0,
        'units': {'energy': 'Hartree'}, 'energies': {'scf': energy}, **facts})
    return path


@pytest.fixture
def sample(tmp_path, capsys):
    root = tmp_path / 'synthetic-study'
    group = root / 'analyses' / 'group'
    group.mkdir(parents=True)
    (root / 'study.md').write_text('# Synthetic study\n')
    molecule = Chem.AddHs(Chem.MolFromSmiles('CCCC'))
    assert AllChem.EmbedMolecule(molecule, randomSeed=53) == 0
    frames = []
    for i, angle in enumerate((-170, -110, -50, 20, 80, 140)):
        rdMolTransforms.SetDihedralDeg(molecule.GetConformer(), 0, 1, 2, 3, angle)
        frames.append(geo.Frame(tuple(a.GetSymbol() for a in molecule.GetAtoms()),
            tuple(tuple(p) for p in molecule.GetConformer().GetPositions()), energy=-157 + i * .001))
    args = ['dedup', '--charge', '0', '--hydrogens', 'all', '--rmsd', '0.01', '--out', str(group), '--json']
    for label, indices in [('crest', range(6)), ('mdopt', range(0, 6, 2)), ('directed', range(1, 6, 2))]:
        source = group / f'{label}.xyz'
        geo.write_xyz(source, [frames[i] for i in indices])
        args += ['--source', f'{label}={source}']
    assert main(args) == 0
    merged = Path(json.loads(capsys.readouterr().out)['output'])
    payload = json.loads(merged.read_text())
    assert len(payload['kept']) == 6
    out = group / 'ensemble.json'
    return root, merged, out, geo.read_xyz(group / payload['xyz_file'])


def build(sample, **kwargs):
    root, merged, out, _ = sample
    return ensemble.build(merged, out, study=str(root), **kwargs)


def table(sample, rows):
    path = sample[0] / 'analyses' / 'thermo.json'
    write_json(path, {'schema': 'ag-thermo/1', 'units': {
        'energy': 'Hartree', 'relative_G': 'kcal/mol', 'population': 'fraction'}, 'rows': rows})
    return path


def test_normal_layers_references_and_exact_thermo(sample):
    root, merged, out, frames = sample
    payload = json.loads(merged.read_text())
    payload['energy_basis'] = 'shared_hartree'
    write_json(merged, payload)
    for i in (0, 2):
        attempt(root, frames[i], f'sp-{i}', -158 - i * .001)
        attempt(root, frames[i], f'opt-{i}', -157 - i * .001, 'B3LYP/6-31G(d) Opt Freq',
                termination='error' if i else 'normal', n_imag=i)
    attempt(root, frames[0], 'sampling')
    rows = [{'attempt_id': f'opt-{i}', 'qh_G': -156.01234567890123 - i,
             'relative_G_kcal': .123456789012345 + i, 'population': .12345678901234567 + i / 10}
            for i in (0, 2)]
    path = table(sample, rows + [dict(rows[0], attempt_id='extra')])
    before = {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}
    result = build(sample, sp=['sp-0', 'sp-2'], opt=['opt-0', 'opt-2'], thermo=path,
                   routes=['crest=sampling'], label='Synthetic butane')
    assert result['references'] == {'xtb': 1, 'sp': 3, 'opt': 3}
    assert result['candidates'][0]['sp']['relative_kcal'] == pytest.approx(.002 * geo.HARTREE_TO_KCAL)
    for i, row in zip((0, 2), rows):
        candidate = result['candidates'][i]
        assert candidate['thermo'] == {'attempt': row['attempt_id'], **{k: row[k] for k in ('qh_G', 'relative_G_kcal', 'population')}}
        assert candidate['missing'] == []
        assert candidate['opt']['n_imaginary'] == i
    assert result['candidates'][2]['opt']['termination'] == 'error'
    assert result['candidates'][1]['missing'] == ['sp', 'opt_freq', 'thermo']
    assert result['unmatched_attempts'] == [{'layer': 'thermo', 'attempt': 'extra', 'reason': '无唯一对应的 Opt 候选'}]
    assert result['routes'][0] == {'label': 'crest', 'attempts': ['sampling']}
    assert all(p.read_bytes() == raw for p, raw in before.items())
    assert json.loads(out.read_text()) == result
    text = out.with_suffix('.md').read_text()
    assert 'extra' in text and 'error / 2' in text
    assert str(root) not in out.read_text() + text


def test_incomparable_routes_and_default_missing(sample):
    result = build(sample)
    assert result['warnings'] == ['各路线 xTB 能量不可直接比较']
    assert result['references'] == {'xtb': None, 'sp': None, 'opt': None}
    for c in result['candidates']:
        assert c['xtb_relative_kcal'] is None
        assert c['missing'] == ['sp', 'opt_freq', 'thermo']
        assert c['sp'] is c['opt'] is c['thermo'] is None
        for m in c['route_members']:
            assert set(m) == {'route', 'member', 'relative_kcal_within_route'}
    # Directed starts at the second global frame; its local first frame is zero.
    member = next(m for m in result['candidates'][1]['route_members'] if m['route'] == 'directed')
    assert member == {'route': 'directed', 'member': 1, 'relative_kcal_within_route': 0.0}
    assert 'thermo' not in result['inputs']


def test_unmatched_and_same_layer_ambiguity(sample):
    root, _, _, frames = sample
    moved = replace(frames[0], coordinates=tuple((x + 10, y, z) for x, y, z in frames[0].coordinates))
    for name, frame in [('sp-a', frames[0]), ('sp-b', frames[0]), ('sp-low', frames[1]), ('sp-out', moved)]:
        attempt(root, frame, name, -160 if name != 'sp-low' else -159)
    for name in ('opt-a', 'opt-b'):
        attempt(root, frames[0], name, route='B3LYP/6-31G(d) Opt Freq')
    path = table(sample, [{'attempt_id': 'opt-a', 'qh_G': -150, 'relative_G_kcal': 0, 'population': 1}])
    result = build(sample, sp=['sp-a', 'sp-b', 'sp-low', 'sp-out'], opt=['opt-a', 'opt-b'], thermo=path)
    c = result['candidates'][0]
    for layer in ('sp', 'opt'):
        assert c[layer]['ambiguous'] is True
        assert c[layer]['energy_hartree'] is c[layer]['relative_kcal'] is None
        assert c[layer]['attempts'] == [f'{layer}-a', f'{layer}-b']
    assert c['opt']['termination'] is c['opt']['n_imaginary'] is None
    assert c['missing'] == ['sp', 'opt_freq', 'thermo']
    assert result['references']['sp'] == 2
    assert [r['attempt'] for r in result['unmatched_attempts']] == ['sp-out', 'opt-a']


def test_multiple_candidate_match(sample):
    root, merged, _, frames = sample
    payload = json.loads(merged.read_text())
    xyz = merged.parent / payload['xyz_file']
    geo.write_xyz(xyz.with_name('duplicate.xyz'), [frames[0], frames[0], *frames[2:]])
    payload['xyz_file'] = 'duplicate.xyz'
    payload['xyz_sha256'] = sha256(xyz.with_name('duplicate.xyz').read_bytes()).hexdigest()
    write_json(merged, payload)
    attempt(root, frames[0], 'sp')
    result = build(sample, sp=['sp'])
    assert result['unmatched_attempts'] == [{'layer': 'sp', 'attempt': 'sp', 'reason': '匹配多个候选'}]
    assert all(c['sp'] is None for c in result['candidates'])


@pytest.mark.parametrize('route,facts', [
    ('B3LYP/6-31G(d) SP', {'termination': 'error'}),
    ('B3LYP/6-31G(d) Freq', {}), ('B3LYP/6-31G(d) Opt', {}),
    ('B3LYP/6-31G(d) SP', {'program': 'xtb'}),
    ('B3LYP/6-31G(d) SP', {'energies': {'scf': None}}),
    ('B3LYP/6-31G(d) SP', {'energies': {'scf': float('nan')}}),
])
def test_invalid_sp_is_missing_with_note(sample, route, facts):
    root, _, _, frames = sample
    attempt(root, frames[0], 'bad-sp', route=route, **facts)
    c = build(sample, sp=['bad-sp'])['candidates'][0]
    assert c['sp'] is None and 'sp' in c['missing']
    assert 'bad-sp' in c['notes'][0]


def test_xyz_hash_and_frame_hash_raw_bytes(sample):
    root, merged, out, _ = sample
    payload = json.loads(merged.read_text())
    xyz = merged.parent / payload['xyz_file']
    raw = xyz.read_bytes().replace(b'\n', b'\r\n')
    xyz.write_bytes(raw)
    with pytest.raises(ValueError, match='hash'):
        build(sample)
    assert not out.exists()
    payload['xyz_sha256'] = sha256(raw).hexdigest()
    write_json(merged, payload)
    result = build(sample)
    rows = raw.splitlines(keepends=True)
    expected = sha256(b''.join(rows[2:2 + int(rows[0])])).hexdigest()
    assert result['candidates'][0]['geometry_sha256'] == expected


@pytest.mark.parametrize('suffix', ['.json', '.md'])
def test_existing_output_never_changed(sample, suffix):
    existing = sample[2].with_suffix(suffix)
    existing.write_bytes(b'preserve')
    with pytest.raises(FileExistsError):
        build(sample)
    assert existing.read_bytes() == b'preserve'
    assert not sample[2].with_suffix('.md' if suffix == '.json' else '.json').exists()


@pytest.mark.parametrize('target', ['analyses/elsewhere.json', 'outside.json', 'analyses/group/report.txt'])
def test_output_location(sample, target):
    with pytest.raises(ValueError):
        ensemble.build(sample[1], target, study=str(sample[0]))
    assert not (sample[0] / target).exists()


@pytest.mark.parametrize('target', ['xyz', 'merged', 'facts', 'input', 'manifest', 'attempt', 'thermo', 'sp-list'])
def test_symlinks_refused(sample, target):
    root, merged, out, frames = sample
    path = attempt(root, frames[0], 'sp')
    kwargs = {'sp': ['sp']}
    payload = json.loads(merged.read_text())
    paths = {'xyz': merged.parent / payload['xyz_file'], 'merged': merged,
             'facts': path / 'facts.json', 'input': path / 'inputs/input.gjf',
             'manifest': path / 'manifest.json', 'attempt': path}
    if target == 'thermo':
        paths[target] = table(sample, [])
        kwargs['thermo'] = paths[target]
    if target == 'sp-list':
        paths[target] = root / 'analyses/ids.json'
        write_json(paths[target], ['sp'])
        kwargs['sp'] = [str(paths[target])]
    original = paths[target]
    moved = original.with_name(original.name + '.saved')
    original.rename(moved)
    original.symlink_to(moved, target_is_directory=moved.is_dir())
    with pytest.raises(ValueError, match='Symbolic'):
        build(sample, **kwargs)
    assert not out.exists()


def test_no_external_reads(sample, tmp_path):
    external = tmp_path / 'external.json'
    write_json(external, ['sp'])
    with pytest.raises(ValueError, match='escapes'):
        build(sample, sp=[str(external)])
    with pytest.raises(ValueError, match='IDs'):
        build(sample, sp=[str(tmp_path)])
    with pytest.raises(ValueError, match='route'):
        build(sample, routes=['unknown=sp'])


def test_sp_list_cli_no_config_and_study_inference(sample, monkeypatch, capsys):
    root, merged, out, frames = sample
    attempt(root, frames[0], 'sp')
    ids = root / 'analyses/ids.json'
    write_json(ids, ['sp'])
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: pytest.fail('no config needed')))
    assert main(['ensemble', '--merged', str(merged), '--out', str(out), '--sp', str(ids)]) == 0
    assert json.loads(out.read_text())['candidates'][0]['sp']['attempts'] == ['sp']
    assert '构象集合' in capsys.readouterr().out


def test_thermo_duplicates_do_not_choose(sample):
    root, _, _, frames = sample
    attempt(root, frames[0], 'opt', route='B3LYP/6-31G(d) Opt Freq')
    row = {'attempt_id': 'opt', 'qh_G': -150, 'relative_G_kcal': 0, 'population': .5}
    result = build(sample, opt=['opt'], thermo=table(sample, [row, row]))
    assert result['candidates'][0]['thermo'] is None
    assert len(result['unmatched_attempts']) == 2


def test_review_manifest_collects_references(sample, capsys):
    root, merged, out, frames = sample
    attempt(root, frames[0], 'opt', route='B3LYP/6-31G(d) Opt Freq')
    thermo = table(sample, [{'attempt_id': 'opt', 'qh_G': -150, 'relative_G_kcal': 0, 'population': 1}])
    result = build(sample, opt=['opt'], thermo=thermo)
    (root / 'study.md').write_text(f"# Synthetic\n\n`{out.relative_to(root)}`\n")
    assert main(['review', 'manifest', '--study', str(root), '--json']) == 0
    capsys.readouterr()
    manifests = list((root / 'analyses').glob('review-manifest-*.json'))
    files = {r['path']: r for r in json.loads(manifests[0].read_text())['files']}
    for item in result['inputs'].values():
        assert files[item['path']]['sha256'] == item['sha256']


def test_schema_field_shapes(sample):
    """Appendix A contract, without introducing a runtime schema dependency."""
    root, _, _, frames = sample
    attempt(root, frames[0], 'sp')
    attempt(root, frames[0], 'opt', route='B3LYP/6-31G(d) Opt Freq')
    result = build(sample, sp=['sp'], opt=['opt'], thermo=table(sample, [
        {'attempt_id': 'opt', 'qh_G': -150, 'relative_G_kcal': 0, 'population': .42}]))
    assert set(result) == {'schema', 'created_at', 'ag', 'study_id', 'label', 'inputs', 'charge',
        'hydrogens', 'energy_basis', 'units', 'routes', 'references', 'warnings', 'candidates', 'unmatched_attempts'}
    assert result['schema'] == 'ag-ensemble/1'
    assert result['units'] == {'energy': 'Hartree', 'relative': 'kcal/mol', 'population': 'fraction'}
    assert set(result['inputs']) == {'merged', 'xyz', 'thermo'}
    for key, item in result['inputs'].items():
        assert set(item) == ({'path', 'sha256', 'file'} if key == 'xyz' else {'path', 'sha256'})
        assert not Path(item['path']).is_absolute()
        assert len(item['sha256']) == 64
    for r in result['routes']:
        assert set(r) == {'label', 'attempts'} and isinstance(r['attempts'], list)
    for c in result['candidates']:
        assert set(c) == {'candidate', 'xyz_frame', 'geometry_sha256', 'sources', 'route_members',
            'xtb_relative_kcal', 'sp', 'opt', 'thermo', 'missing', 'notes'}
        assert type(c['candidate']) is int and c['candidate'] > 0
        assert type(c['xyz_frame']) is int and c['xyz_frame'] > 0
        assert len(c['geometry_sha256']) == 64
        for key in ('sp', 'opt'):
            if c[key] is not None:
                assert set(c[key]) == {'attempts', 'ambiguous', 'energy_hartree', 'relative_kcal'} | (
                    {'termination', 'n_imaginary'} if key == 'opt' else set())
                assert type(c[key]['ambiguous']) is bool
        if c['thermo'] is not None:
            assert set(c['thermo']) == {'attempt', 'qh_G', 'relative_G_kcal', 'population'}
    def check(value):
        if isinstance(value, dict):
            assert 'source' not in value
            for child in value.values():
                check(child)
        elif isinstance(value, list):
            for child in value:
                check(child)
        elif isinstance(value, str):
            assert not Path(value).is_absolute()
    check(result)
    json.dumps(result, allow_nan=False)


def test_evidence_changed_during_collection_refused(sample, monkeypatch):
    original = ensemble.ag_provenance
    def change():
        sample[1].write_text(sample[1].read_text() + '\n')
        return original()
    monkeypatch.setattr(ensemble, 'ag_provenance', change)
    with pytest.raises(ValueError, match='changed'):
        build(sample)
    assert not sample[2].exists()


def test_default_output_hash(sample, monkeypatch):
    """Baseline from main 36e6c1f; freeze only time, provenance and fixture paths."""
    from datetime import datetime, timezone

    class FixedTime:
        @staticmethod
        def now(tz):
            return datetime(2026, 10, 16, tzinfo=timezone.utc)

    monkeypatch.setattr(ensemble, 'datetime', FixedTime)
    monkeypatch.setattr(ensemble, 'ag_provenance', lambda: {'version': 'fixture', 'commit': 'fixture', 'dirty': False})
    root, merged, out, _ = sample
    payload = json.loads(merged.read_text().replace(str(root), 'synthetic-study'))
    (merged.parent / payload['xyz_file']).rename(merged.parent / 'merged.xyz')
    payload['xyz_file'] = 'merged.xyz'
    merged = merged.with_name('merged.json')
    write_json(merged, payload)
    result = ensemble.build(merged, out, study=str(root))
    assert 'descriptors' not in result and 'bin_summary' not in result
    assert all('local' not in c for c in result['candidates'])
    assert sha256(out.read_bytes()).hexdigest() == '35f3d76921a6135db44c3b7594a9e8f0ca032cf1e06c5045a7f67446248ddb5d'
    assert sha256(out.with_suffix('.md').read_bytes()).hexdigest() == '979d92878924ca134d14da7f0d5c0494902842d8819fb1d204875abd535055b8'


def test_local_descriptors_and_layer_summary(sample):
    import math

    root, merged, out, frames = sample
    payload = json.loads(merged.read_text())
    payload['energy_basis'] = 'shared_hartree'
    # Candidate numbers deliberately differ from XYZ frame numbers.
    for row in payload['kept']:
        row['index'] *= 10
    write_json(merged, payload)
    sp, opt = [], []
    for i, frame in enumerate(frames):
        sp.append(f'sp-{i}')
        attempt(root, frame, sp[-1], -160 - i * .01)
        if i in (1, 2, 3, 4):
            opt.append(f'opt-{i}')
            attempt(root, frame, opt[-1], -159 - i * .01, 'B3LYP/6-31G(d) Opt Freq')
    thermo = table(sample, [
        {'attempt_id': f'opt-{i}', 'qh_G': -158 - i * .01,
         'relative_G_kcal': 2 - i, 'population': .5} for i in (1, 2)])
    result = build(sample, sp=sp, opt=opt, thermo=thermo,
                   dihedral_bins=['1,2,3,4:-112,-48,132@gauche-,gauche+,trans'],
                   report_distance=['1,4', '5,14'])
    assert result['schema'] == 'ag-ensemble/1'
    assert result['descriptors'] == {
        'dihedral_bins': [{'atoms': [1, 2, 3, 4], 'boundaries': [-112, -48, 132],
                           'names': ['gauche-', 'gauche+', 'trans']}],
        'distance_pairs': [[1, 4], [5, 14]]}
    expected = ['trans', 'gauche-', 'gauche-', 'gauche+', 'gauche+', 'trans']
    for i, (candidate, frame) in enumerate(zip(result['candidates'], frames)):
        local = candidate['local']
        mol = Chem.MolFromXYZBlock(geo.xyz_text([frame]))
        angle = rdMolTransforms.GetDihedralDeg(mol.GetConformer(), 0, 1, 2, 3)
        assert local == {'dihedrals': [pytest.approx(angle)], 'bins': [expected[i]],
                         'near_boundary': i in (1, 2), 'distances': [
                             pytest.approx(math.dist(frame.coordinates[a - 1], frame.coordinates[b - 1]))
                             for a, b in [(1, 4), (5, 14)]]}
    assert result['bin_summary'] == [
        {'bins': ['trans'], 'count': 2, 'lowest_candidate': 60, 'lowest_layer': 'sp'},
        {'bins': ['gauche-'], 'count': 2, 'lowest_candidate': 30, 'lowest_layer': 'thermo'},
        {'bins': ['gauche+'], 'count': 2, 'lowest_candidate': 50, 'lowest_layer': 'opt'}]
    text = out.with_suffix('.md').read_text()
    assert '分组 | 近边界 | 距离（Å）' in text and '## 分组汇总' in text
    assert '| gauche- | 2 | 30 | thermo |' in text
    assert json.loads(out.read_text()) == result


@pytest.mark.parametrize('shared', [False, True])
def test_distance_only_and_xtb_fallback(sample, shared):
    payload = json.loads(sample[1].read_text())
    if shared:
        payload['energy_basis'] = 'shared_hartree'
        # Tie energies; choose candidate number, not encounter order.
        payload['kept'][0]['index'] = 10
        payload['kept'][1]['energy'] = payload['kept'][0]['energy']
        write_json(sample[1], payload)
    result = build(sample, report_distance=['1,4'])
    assert result['descriptors'] == {'dihedral_bins': [], 'distance_pairs': [[1, 4]]}
    for c in result['candidates']:
        assert c['local']['bins'] == c['local']['dihedrals'] == []
        assert c['local']['near_boundary'] is False
    assert result['bin_summary'] == [{'bins': [], 'count': 6,
        'lowest_candidate': 2 if shared else None, 'lowest_layer': 'xtb' if shared else None}]


def test_repeated_definitions_and_escaped_names_cli(sample, capsys):
    _, merged, out, _ = sample
    assert main(['ensemble', '--merged', str(merged), '--out', str(out),
                 '--dihedral-bins', '1,2,3,4:-90,90',
                 '--dihedral-bins', '1,2,3,4:-90,90@<cis>,trans|other',
                 '--report-distance', '1,4', '--report-distance', '2,3']) == 0
    result = json.loads(out.read_text())
    assert [c['local']['bins'] for c in result['candidates']] == [
        ['bin2', 'trans|other'], ['bin2', 'trans|other'], ['bin1', '<cis>'],
        ['bin1', '<cis>'], ['bin1', '<cis>'], ['bin2', 'trans|other']]
    assert [g['count'] for g in result['bin_summary']] == [3, 3]
    text = capsys.readouterr().out
    assert '&lt;cis&gt;' in text and 'trans&#124;other' in text
    assert text == out.with_suffix('.md').read_text()


@pytest.mark.parametrize('option,value', [
    ('--dihedral-bins', '1,2,3:-90,90'),
    ('--dihedral-bins', '1,2,2,4:-90,90'),
    ('--dihedral-bins', '1,2,3,4:90,-90'),
    ('--dihedral-bins', '1,2,3,4:-180,180'),
    ('--dihedral-bins', '1,2,3,4:-90,90@one'),
    ('--dihedral-bins', '1,2,3,4:nan,90'),
    ('--report-distance', '0,2'), ('--report-distance', '1,1'),
    ('--report-distance', '1,2,3'),
])
def test_descriptor_parameter_errors_match_dedup(sample, capsys, option, value):
    from ag.dedup import descriptor_definitions

    kwargs = {option[2:].replace('-', '_'): [value]}
    with pytest.raises(ValueError) as error:
        descriptor_definitions(**kwargs)
    assert main(['ensemble', '--merged', str(sample[1]), '--out', str(sample[2]), option, value]) == 1
    assert capsys.readouterr().err.strip() == f'ensemble: {error.value}'
    assert not sample[2].exists() and not sample[2].with_suffix('.md').exists()


@pytest.mark.parametrize('kind', ['dihedral', 'distance', 'collinear'])
def test_descriptor_frame_errors_match_dedup(sample, kind, capsys):
    from ag.dedup import descriptor_definitions, frame_descriptors

    _, merged, out, frames = sample
    if kind == 'collinear':
        frames[2] = replace(frames[2], coordinates=(
            (0, 0, 0), (1, 0, 0), (2, 0, 0), (3, 0, 0), *frames[2].coordinates[4:]))
        payload = json.loads(merged.read_text())
        xyz = merged.parent / payload['xyz_file']
        xyz.write_text(geo.xyz_text(frames))
        payload['xyz_sha256'] = sha256(xyz.read_bytes()).hexdigest()
        write_json(merged, payload)
    option = '--report-distance' if kind == 'distance' else '--dihedral-bins'
    value = {'distance': '1,99', 'dihedral': '1,2,3,99:-90,90',
             'collinear': '1,2,3,4:-90,90'}[kind]
    definitions = descriptor_definitions(**{option[2:].replace('-', '_'): [value]})
    index = 2 if kind == 'collinear' else 0
    with pytest.raises(ValueError) as error:
        frame_descriptors(frames[index], definitions, index)
    assert main(['ensemble', '--merged', str(merged), '--out', str(out), option, value]) == 1
    assert capsys.readouterr().err.strip() == f'ensemble: {error.value}'
    assert f'frame {index + 1}' in str(error.value)
    assert not out.exists() and not out.with_suffix('.md').exists()


def test_summary_uses_available_same_layer_without_ambiguity(sample):
    root, _, _, frames = sample
    for name in ('sp-a', 'sp-b'):
        attempt(root, frames[0], name, -999)
    attempt(root, frames[1], 'sp', -200)
    attempt(root, frames[2], 'opt', -100, 'B3LYP/6-31G(d) Opt Freq')
    thermo = table(sample, [{'attempt_id': 'opt', 'qh_G': None,
                            'relative_G_kcal': None, 'population': None}])
    result = build(sample, report_distance=['1,4'], sp=['sp-a', 'sp-b', 'sp'],
                   opt=['opt'], thermo=thermo)
    assert result['bin_summary'] == [{'bins': [], 'count': 6,
                                     'lowest_candidate': 3, 'lowest_layer': 'opt'}]


def test_contact_atoms_not_supported(sample):
    with pytest.raises(SystemExit) as error:
        main(['ensemble', '--merged', str(sample[1]), '--out', str(sample[2]), '--contact-atoms', '1,4'])
    assert error.value.code == 2
