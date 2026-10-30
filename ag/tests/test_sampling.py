"""Synthetic butane route overlap and representative regression cases."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

from ag import geometry as geo
from ag.cli import main
from ag.cluster import select
from ag.coverage import report, same_geometry
from ag.render import parameters

DATA = Path(__file__).parent / 'data' / 'butane.xyz'


def merge(tmp_path, capsys, routes=None):
    frames = geo.read_xyz(DATA)
    routes = routes or {'crest': frames, 'etkdg': frames}
    args = ['dedup', '--charge', '0', '--out', str(tmp_path), '--json']
    for name, group in routes.items():
        path = tmp_path / (name + '.xyz')
        geo.write_xyz(path, group)
        args += ['--source', f'{name}={path}']
    assert main(args) == 0
    return json.loads(capsys.readouterr().out)


def attempt(tmp_path, frame, label, energy=-157.0, route='B3LYP/6-31G(d) SP'):
    directory = tmp_path / 'attempts' / label
    (directory / 'inputs').mkdir(parents=True)
    atoms = geo.xyz_text([frame]).splitlines()[2:]
    data = f'%nprocshared=1\n%mem=1GB\n# {route}\n\nSynthetic butane\n\n0 1\n' + '\n'.join(atoms) + '\n\n'
    (directory / 'inputs' / 'arbitrary.gjf').write_text(data)
    (directory / 'manifest.json').write_text(json.dumps({'template': 'gaussian', 'cores': 1, 'mem_gb': 2,
        'inputs': [{'name': 'arbitrary.gjf', 'sha256': hashlib.sha256(data.encode()).hexdigest()}]}))
    (directory / 'facts.json').write_text(json.dumps({'program': 'gaussian', 'termination': 'normal',
        'units': {'energy': 'Hartree'}, 'energies': {'scf': energy}}))
    return directory


def attempts(tmp_path, frames):
    return [str(attempt(tmp_path, f, f'unrelated-label-{i}', -157 + i / geo.HARTREE_TO_KCAL))
            for i, f in enumerate(frames)]


def test_nci_allowlist():
    assert parameters('crest', {'--nci': '', '--ewin': '6'}) == '--nci --ewin 6'
    for template, values in [('xtb', {'--nci': ''}), ('crest', {'--nci': 'true'}),
                             ('crest', {'--nci;echo': ''}), ('crest', {'--nci': '', '--wscal': '1'})]:
        with pytest.raises(ValueError):
            parameters(template, values)


def test_multi_source_preserves_every_route_and_energy(tmp_path, capsys):
    frames = geo.read_xyz(DATA)
    ff = [replace(f, energy=100 + i, energy_unit='kcal/mol') for i, f in enumerate(frames)]
    result = merge(tmp_path, capsys, {'crest': frames, 'etkdg': ff, 'directed': [frames[0], frames[0]]})
    assert len(result['kept']) == 3
    assert result['kept'][0]['sources'] == ['crest', 'directed', 'etkdg']
    assert len(result['kept'][0]['members']) == 4
    assert result['kept'][1]['sources'] == ['crest', 'etkdg']
    assert result['kept'][1]['members'][1]['energy_unit'] == 'kcal/mol'
    assert result['window_kcal'] is None
    # Refuse to interpret unlike method energies as one ranked ensemble.
    assert main(['cluster', result['output']]) == 1
    assert 'not comparable' in capsys.readouterr().err
    assert main(['cluster', result['output'], '--representative', 'medoid', '--json']) == 0
    assert json.loads(capsys.readouterr().out)['representative_method'] == 'medoid'


def test_two_routes_agree_and_no_overwrite(tmp_path, capsys):
    merged = merge(tmp_path, capsys)
    energies = attempts(tmp_path, geo.read_xyz(DATA))
    out = tmp_path / 'report.json'
    args = ['coverage', '--merged', merged['output'], '--energies', *energies,
            '--window', '3', '--out', str(out), '--json']
    assert main(args) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['n_in_window'] == 3
    assert result['route_counts'] == {'crest': 3, 'etkdg': 3}
    assert result['warnings'] == []
    assert all(r['sources'] == ['crest', 'etkdg'] for r in result['lowest'])
    assert not result['unmatched_attempts']
    before = out.read_bytes()
    assert main(args) == 1
    capsys.readouterr()
    assert out.read_bytes() == before
    assert main(args[:-1] + ['--top', '2', '--out', str(tmp_path / 'report.md')]) == 0
    assert '最低的 2 个构象' in capsys.readouterr().out
    assert not list(tmp_path.glob('**/final.xyz'))  # No facts regeneration side effects.


def test_lowest_is_exclusive_and_majority_strictly_over_half(tmp_path, capsys):
    frames = geo.read_xyz(DATA)
    merged = merge(tmp_path, capsys, {'crest': frames, 'etkdg': [frames[2]]})
    result = report(merged['output'], attempts(tmp_path, frames))
    assert len(result['warnings']) == 2
    assert result['route_counts'] == {'crest': 3, 'etkdg': 1}
    assert [r['index'] for r in result['single_route_low_energy']] == [1, 2]
    # Two candidates: one exclusive (exactly half), but shared minimum.
    other = tmp_path / 'other'; other.mkdir()
    merged = merge(other, capsys, {'crest': frames[:2], 'etkdg': frames[:1]})
    result = report(merged['output'], attempts(other, frames[:2]))
    assert result['warnings'] == []


def test_unmatched_attempt_and_empty_window(tmp_path, capsys):
    frame = geo.read_xyz(DATA)[0]
    merged = merge(tmp_path, capsys, {'crest': [frame], 'etkdg': [frame]})
    translated = replace(frame, coordinates=tuple((x + 1, y, z) for x, y, z in frame.coordinates))
    path = attempt(tmp_path, translated, 'named-like-candidate-1')
    result = report(merged['output'], [str(path)])
    assert result['n_in_window'] == 0
    assert result['lowest'] == [] and result['warnings'] == []
    assert result['unmatched_attempts'][0]['reason'] == 'geometry_unmatched'
    assert result['unmatched_candidates'][0]['reason'] == 'no_matching_energy'
    assert result['route_counts'] == {'crest': 0, 'etkdg': 0}


def test_coordinate_tolerance_and_atom_order():
    frame = geo.read_xyz(DATA)[0]
    def shifted(amount):
        return replace(frame, coordinates=tuple((x + amount, y, z) for x, y, z in frame.coordinates))
    assert same_geometry(frame, shifted(0.000099))
    assert not same_geometry(frame, shifted(0.000101))
    assert not same_geometry(frame, replace(frame, symbols=frame.symbols[::-1], coordinates=frame.coordinates[::-1]))


def test_ambiguous_energies_not_silently_selected(tmp_path, capsys):
    frame = geo.read_xyz(DATA)[0]
    merged = merge(tmp_path, capsys, {'crest': [frame], 'etkdg': [frame]})
    paths = [str(attempt(tmp_path, frame, name, energy)) for name, energy in [('one', -157), ('two', -158)]]
    result = report(merged['output'], paths)
    assert result['n_matched'] == 0
    assert len(result['unmatched_attempts']) == 2
    assert result['unmatched_candidates'][0]['reason'] == 'multiple_matching_energies'


@pytest.mark.usefixtures("synthetic_cwd")
def test_native_thermo_table_and_attempt_json_list(tmp_path, capsys):
    merged = merge(tmp_path, capsys)
    paths = attempts(tmp_path, geo.read_xyz(DATA))
    table = {'schema': 'ag-thermo/1', 'units': {'energy': 'Hartree'},
             'rows': [{'attempt_id': Path(p).name, 'qh_G': -156 + i / geo.HARTREE_TO_KCAL}
                      for i, p in enumerate(paths)]}
    (tmp_path / 'analyses').mkdir()
    table_path = tmp_path / 'analyses' / 'thermo.json'
    table_path.write_text(json.dumps(table))
    result = report(merged['output'], [str(table_path)], window=1.1)
    assert result['energy_basis'] == 'qh_G' and result['n_in_window'] == 2
    list_path = tmp_path / 'attempt-list.json'
    list_path.write_text(json.dumps([str(Path(p).relative_to(tmp_path)) for p in paths]))
    assert report(merged['output'], [str(list_path)])['n_in_window'] == 3
    table['rows'] = []
    table_path.write_text(json.dumps(table))
    assert report(merged['output'], [str(table_path)])['n_in_window'] == 0


def test_bad_energy_inputs_reported(tmp_path, capsys):
    merged = merge(tmp_path, capsys)
    frame = geo.read_xyz(DATA)[0]
    paths = [str(attempt(tmp_path, frame, 'opt', route='B3LYP/6-31G(d) opt')),
             str(attempt(tmp_path, frame, 'nonfinite', energy=float('nan')))]
    bad_hash = attempt(tmp_path, frame, 'bad-hash')
    with (bad_hash / 'inputs/arbitrary.gjf').open('a') as stream:
        stream.write('\n')
    paths += [str(bad_hash), str(tmp_path / 'missing')]
    result = report(merged['output'], paths)
    assert result['n_in_window'] == 0
    assert len(result['unmatched_attempts']) == 4


def test_required_out_and_invalid_options(tmp_path, capsys):
    with pytest.raises(SystemExit):
        main(['coverage', '--merged', 'merged.json', '--energies', 'attempt'])
    capsys.readouterr()
    merged = merge(tmp_path, capsys)
    with pytest.raises(ValueError, match='positive'):
        report(merged['output'], [], top=0)
    with pytest.raises(ValueError, match='nonnegative'):
        report(merged['output'], [], window=-1)
    with pytest.raises(ValueError, match='finite'):
        report(merged['output'], [], window=float('nan'))
    assert main(['dedup', '--source', f'crest={DATA}', '--window', '3', '--charge', '0', '--out', str(tmp_path)]) == 1
    assert 'geometry-only' in capsys.readouterr().err


def test_medoid_and_lowest_preserves_existing_membership(tmp_path):
    from rdkit import Chem
    from rdkit.Chem import rdDetermineBonds, rdMolAlign, rdMolTransforms
    frame = geo.read_xyz(DATA)[0]
    mol = geo.infer_molecule(frame, 0, Chem, rdDetermineBonds)
    frames = []
    for i, angle in enumerate([80, 100, 120]):
        rdMolTransforms.SetDihedralDeg(mol.GetConformer(), 0, 1, 2, 3, angle)
        frames.append(replace(frame, coordinates=tuple(tuple(p) for p in mol.GetConformer().GetPositions()), energy=-157 + i*0.001))
    records = [geo.record(f, i, i) for i, f in enumerate(frames)]
    args = (frames, records, 0, 20, 2.0, False, Chem, rdDetermineBonds, rdMolAlign)
    default, _, default_frames = select(*args)
    explicit, _, _ = select(*args, representative='lowest')
    medoid, _, chosen = select(*args, representative='medoid')
    assert default == explicit and default[0]['index'] == 1
    assert medoid[0]['index'] == 2
    assert chosen == [frames[1]] and default_frames == [frames[0]]
    assert medoid[0]['members'] == default[0]['members']
    assert medoid[0]['cluster_seed_index'] == 1
    assert medoid[0]['medoid_rmsd_sum'] > 0


def test_stale_merged_xyz_refused(tmp_path, capsys):
    merged = merge(tmp_path, capsys)
    path = tmp_path / merged['xyz_file']
    with path.open('a') as stream:
        stream.write('\n')
    with pytest.raises(ValueError, match='hash differs'):
        report(merged['output'], [])


def test_report_ties_window_boundary_and_no_energy_sources(tmp_path, capsys):
    frames = geo.read_xyz(DATA)[:2]
    frames = [replace(f, energy=None, comment='unranked') for f in frames]
    merged = merge(tmp_path, capsys, {'crest': frames, 'directed': frames[:1]})
    paths = [str(attempt(tmp_path, frame, f'tie-{i}')) for i, frame in enumerate(frames)]
    result = report(merged['output'], paths, window=0)
    assert result['n_in_window'] == 2
    assert result['lowest'][0]['sources'] == ['crest', 'directed']
    assert len(result['warnings']) == 1  # Second tied minimum is exclusive, exactly half is not majority.
    assert main(['cluster', merged['output'], '--representative', 'medoid', '--json']) == 0
    capsys.readouterr()


def test_no_coordinate_match_does_not_shift_window_zero(tmp_path, capsys):
    frame = geo.read_xyz(DATA)[0]
    merged = merge(tmp_path, capsys, {'crest': [frame], 'etkdg': [frame]})
    other = replace(frame, coordinates=tuple((x + 1, y, z) for x, y, z in frame.coordinates))
    paths = [str(attempt(tmp_path, frame, 'matches', -157)), str(attempt(tmp_path, other, 'lower-unmatched', -158))]
    result = report(merged['output'], paths, window=0)
    assert result['n_in_window'] == 1
    assert result['lowest'][0]['relative_energy_kcal'] == 0
    assert result['unmatched_attempts'][0]['reason'] == 'geometry_unmatched'
