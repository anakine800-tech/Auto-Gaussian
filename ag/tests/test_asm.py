"""Synthetic water-pair bookkeeping; no private data, configuration or cluster."""

from hashlib import sha256
import json
from pathlib import Path

import pytest

from ag import asm, cli, geometry as geo
from ag import _review_manifest as inventory


ROUTE = '#p HF/STO-3G SP SCRF=(SMD,Solvent=Water)'
WATER = ('O 0 0 0', 'H 0.96 0 0', 'H -0.24 0.93 0')


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')


def update_json(path, **changes):
    data = json.loads(path.read_text())
    data.update(changes)
    write_json(path, data)


def attempt(root, name, rows, energy, route=ROUTE, charge=0):
    directory = root / 'attempts' / name
    (directory / 'inputs').mkdir(parents=True)
    text = '%nprocshared=1\n%mem=1GB\n' + route + '\n\nSynthetic water\n\n'
    text += f'{charge} 1\n' + '\n'.join(rows) + '\n\n'
    (directory / 'inputs/input.gjf').write_text(text)
    manifest = dict(template='gaussian', cores=1, mem_gb=2, inputs=[
        dict(name='input.gjf', sha256=sha256(text.encode()).hexdigest())])
    write_json(directory / 'manifest.json', manifest)
    xyz = f'{len(rows)}\nSynthetic water\n' + '\n'.join(rows) + '\n'
    (directory / 'final_input.xyz').write_text(xyz)
    (directory / 'final.xyz').write_text(xyz)
    facts = dict(schema='ag-facts/1', program='gaussian', termination='normal',
                 units=dict(energy='Hartree'), n_atoms=len(rows), charge=charge, multiplicity=1,
                 energies=dict(scf=energy, g=-999., zpe=99.), route=route,
                 program_version='Gaussian 16 Revision C.01',
                 final_input_geometry='final_input.xyz', final_geometry='final.xyz',
                 job_sections=[dict(index=1, route=route, termination='normal', start_kind='launch',
                                    internal_step=None)],
                 fact_sources={'energies.scf': 1, 'route': 1, 'final_input_geometry': 1, 'final_geometry': 1})
    write_json(directory / 'facts.json', facts)
    return directory


@pytest.fixture
def sample(tmp_path, monkeypatch):
    root = tmp_path / 'synthetic-study'
    (root / 'analyses').mkdir(parents=True)
    (root / 'study.md').write_text('# Synthetic study\n')
    monkeypatch.chdir(root)
    monkeypatch.setattr(cli, 'load_config', lambda **kw: pytest.fail('no configuration'))
    monkeypatch.setattr('ag.transport.SSHTransport', lambda *a, **kw: pytest.fail('no SSH'))
    systems = []
    for label, offset, energies in [('a', 3., (-150., -75., -74.9)),
                                    ('b', 4., (-149.97, -74.98, -74.88))]:
        second = tuple(f'{s} {float(x) + offset} {y} {z}' for s, x, y, z in (r.split() for r in WATER))
        # Interleaved fragments require explicit mapping, not contiguous slicing.
        rows = tuple(r for pair in zip(WATER, second) for r in pair)
        for suffix, coords, energy in zip(('complex', 'first', 'second'), (rows, WATER, second), energies):
            attempt(root, label + '-' + suffix, coords, energy)
        systems.append(dict(label=label, complex_attempt=label + '-complex', complex_geometry='input',
                            fragments=[dict(name=name, atoms=indices, charge=0, multiplicity=1,
                                            attempt=label + '-' + name)
                                       for name, indices in [('first', '5,1,3'), ('second', '2,4,6')]]))
    data = dict(schema='ag-asm-definition/1', systems=systems, comparisons=[dict(a='a', b='b')])
    write_json(root / 'analyses/definition.json', data)
    return root, data


def build(sample):
    root, data = sample
    write_json(root / 'analyses/definition.json', data)
    return asm.summary('analyses/definition.json', 'analyses/asm.json', study=str(root))


def snapshot(root):
    return {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in root.rglob('*') if p.is_file()}


def test_hand_calculated_summary_without_references(sample):
    root, _ = sample
    before = snapshot(root / 'attempts')
    result = build(sample)
    a, b = result['systems']
    comparison, = result['comparisons']
    assert a['E_int']['hartree'] == pytest.approx(-0.1)
    assert b['E_int']['hartree'] == pytest.approx(-0.11)
    assert comparison['ddE_complex']['hartree'] == pytest.approx(0.03)
    assert comparison['ddE_int']['hartree'] == pytest.approx(-0.01)
    assert [r['ddE_dist']['hartree'] for r in comparison['fragments']] == pytest.approx([0.02, 0.02])
    assert abs(comparison['sum_residual_hartree']) < 1e-8
    assert a['E_int']['kcal_mol'] == pytest.approx(-0.1 * result['hartree_to_kcal_mol'])
    assert a['fragments'][0]['original_atoms'] == [1, 3, 5]
    assert all(s['E_dist_total'] is None and s['delta_E'] is None for s in (a, b))
    assert all(r['E_dist'] is None and r['reference'] is None for r in a['fragments'])
    assert before == snapshot(root / 'attempts')
    out = root / 'analyses/asm.json'
    assert json.loads(out.read_text()) == result
    md = out.with_suffix('.md').read_text()
    assert md.count('| 项目 | Hartree | kcal/mol |') == 3
    assert asm.NOTICE in md and 'b − a' in md
    assert str(root) not in out.read_text() + md
    assert all(not Path(r['path']).is_absolute() for r in result['sources'])


@pytest.mark.parametrize('count', [1, 2])
def test_partial_and_complete_references(sample, count):
    root, data = sample
    attempt(root, 'ref', tuple(reversed(WATER)), -75.1)  # Atom order need not match.
    for system in data['systems']:
        for fragment in system['fragments'][:count]:
            fragment['reference_attempt'] = 'ref'
    result = build(sample)
    a, b = result['systems']
    assert a['fragments'][0]['E_dist']['hartree'] == pytest.approx(0.1)
    if count == 2:
        assert a['E_dist_total']['hartree'] == pytest.approx(0.3)
        assert a['delta_E']['hartree'] == pytest.approx(0.2)
        assert b['E_dist_total']['hartree'] == pytest.approx(0.34)
        assert b['delta_E']['hartree'] == pytest.approx(0.23)
    else:
        assert a['E_dist_total'] is None and a['delta_E'] is None
        assert a['fragments'][1]['E_dist'] is None


def test_comparison_uses_fragment_energies_even_with_different_reference_energies(sample):
    root, data = sample
    for label, energy in [('a', -75.1), ('b', -75.2)]:
        attempt(root, label + '-ref', WATER, energy)
    for system in data['systems']:
        system['fragments'][0]['reference_attempt'] = system['label'] + '-ref'
    comparison = build(sample)['comparisons'][0]
    assert comparison['fragments'][0]['ddE_dist']['hartree'] == pytest.approx(0.02)


@pytest.mark.parametrize('geometry', ['input', 'final'])
def test_split_mapping_and_explicit_geometry(sample, geometry):
    root, _ = sample
    before = snapshot(root / 'attempts')
    if geometry == 'final':
        path = root / 'attempts/a-complex/final_input.xyz'
        path.write_text(path.read_text().replace('O 0 0 0', 'O 0 1 0'))
        before = snapshot(root / 'attempts')
    assert cli.main(['asm', 'split', 'a-complex', '--geometry', geometry, '--atoms', '5,1,3',
                     '--name', 'water', '--out', 'analyses/fragment.xyz', '--study', str(root)]) == 0
    frame, = geo.read_xyz(root / 'analyses/fragment.xyz')
    assert frame.symbols == ('O', 'H', 'H')
    assert frame.coordinates[0] == (0., float(geometry == 'final'), 0.)
    assert 'source=a-complex' in frame.comment and f'geometry={geometry}' in frame.comment
    assert 'fragment="water"' in frame.comment and 'original_atoms=1,3,5' in frame.comment
    assert 'charge' not in frame.comment and 'multiplicity' not in frame.comment
    assert before == snapshot(root / 'attempts')


def test_split_infers_study_from_attempt_directory(sample, tmp_path, monkeypatch):
    root, _ = sample
    monkeypatch.chdir(tmp_path)
    assert asm.split(str(root / 'attempts/a-complex'), geometry='input', atom_list='6,1-3',
                     name='custom', out='analyses/custom.xyz') == 'analyses/custom.xyz'
    assert 'original_atoms=1,2,3,6' in (root / 'analyses/custom.xyz').read_text()


@pytest.mark.parametrize('value', ['0', '-1', '7', '1-7', '3-1', '1,1', '1-3,3-5', '1,,2', '', '1.5', '1-', '01'])
def test_split_invalid_atoms(sample, value):
    with pytest.raises(ValueError, match='atoms'):
        asm.split('a-complex', geometry='input', atom_list=value, name='water', out='analyses/frag.xyz')
    assert not (sample[0] / 'analyses/frag.xyz').exists()


@pytest.mark.parametrize(('change', 'message'), [
    ('missing', 'cover all atoms'), ('overlap', 'fragment second: overlapping'),
    ('charge', 'charge sum'), ('declared_charge', 'fragment first: declared charge'),
    ('multiplicity', 'fragment first: declared charge/multiplicity'),
    ('geometry', 'fragment first: fragment input geometry'), ('names', 'fragment names differ'),
    ('identity', 'fragment first: identity mismatch'), ('duplicate', 'duplicate label')])
def test_definition_rejections(sample, change, message):
    root, data = sample
    first = data['systems'][0]['fragments'][0]
    if change == 'missing':
        data['systems'][0]['fragments'].pop()
    elif change == 'overlap':
        data['systems'][0]['fragments'][1]['atoms'] = '1,2,4,6'
    elif change == 'charge':
        update_json(root / 'attempts/a-complex/facts.json', charge=1)
        attempt_charge(root / 'attempts/a-complex', 1)
    elif change == 'declared_charge':
        first['charge'] = 1
    elif change == 'multiplicity':
        first['multiplicity'] = 3
    elif change == 'geometry':
        first['atoms'] = '2,4,6'
    elif change == 'names':
        data['systems'][1]['fragments'][0]['name'] = 'different'
    elif change == 'identity':
        for name, charge in [('b-first', 1), ('b-second', -1)]:
            update_json(root / f'attempts/{name}/facts.json', charge=charge)
            attempt_charge(root / 'attempts' / name, charge)
        for fragment, charge in zip(data['systems'][1]['fragments'], [1, -1]):
            fragment['charge'] = charge
    else:
        data['systems'][1]['label'] = 'a'
    with pytest.raises(ValueError, match=message):
        build(sample)
    assert not (root / 'analyses/asm.json').exists()


def attempt_charge(directory, charge):
    input_file = directory / 'inputs/input.gjf'
    input_file.write_text(input_file.read_text().replace('\n0 1\n', f'\n{charge} 1\n'))
    update_json(directory / 'manifest.json', inputs=[
        dict(name='input.gjf', sha256=sha256(input_file.read_bytes()).hexdigest())])


@pytest.mark.parametrize(('key', 'value', 'message'), [
    ('termination', 'error', 'normally terminated'), ('termination', 'incomplete', 'normally terminated'),
    ('program', 'xtb', 'Gaussian'), ('multiplicity', 3, 'Only singlets'),
    ('program_version', 'Gaussian 09 Revision D.01', 'program version mismatch'),
    ('program_version', None, 'program version'), ('energies', {'scf': None, 'g': -75.}, 'energies.scf'),
    ('energies', {'scf': float('nan')}, 'energies.scf'), ('energies', {'scf': True}, 'energies.scf'),
    ('units', {'energy': 'kcal/mol'}, 'unit Hartree'), ('n_atoms', 2, 'atom count'),
    ('fact_sources', {}, 'energy source'), ('job_sections', [], 'section evidence')])
def test_facts_rejections_identify_system_and_fragment(sample, key, value, message):
    root, _ = sample
    update_json(root / 'attempts/a-first/facts.json', **{key: value})
    with pytest.raises(ValueError, match=f'system a / fragment first: .*{message}'):
        build(sample)


@pytest.mark.parametrize('route', [ROUTE.replace('HF', 'B3LYP'), ROUTE.replace('STO-3G', '6-31G'),
                                   ROUTE.replace('Water', 'Acetonitrile'), ROUTE.replace('SMD', 'PCM'),
                                   ROUTE + ' EmpiricalDispersion=GD3BJ'])
def test_protocol_mismatch(sample, route):
    root, _ = sample
    path = root / 'attempts/a-first/facts.json'
    facts = json.loads(path.read_text())
    facts['route'] = facts['job_sections'][0]['route'] = route
    write_json(path, facts)
    input_file = path.parent / 'inputs/input.gjf'
    input_file.write_text(input_file.read_text().replace(ROUTE, route))
    update_json(path.parent / 'manifest.json', inputs=[
        dict(name='input.gjf', sha256=sha256(input_file.read_bytes()).hexdigest())])
    with pytest.raises(ValueError, match='fragment first: method protocol mismatch'):
        build(sample)


@pytest.mark.parametrize(('offset', 'ok'), [(0.000099, True), (0.0001, True), (0.000101, False)])
def test_coordinate_tolerance_without_alignment(sample, offset, ok):
    root, _ = sample
    path = root / 'attempts/a-first/inputs/input.gjf'
    path.write_text(path.read_text().replace('O 0 0 0', f'O {offset} 0 0'))
    update_json(path.parent.parent / 'manifest.json', inputs=[dict(name=path.name, sha256=sha256(path.read_bytes()).hexdigest())])
    if ok:
        build(sample)
    else:
        with pytest.raises(ValueError, match='geometry mismatch'):
            build(sample)


def test_same_count_wrong_elements_rejected(sample):
    root, _ = sample
    path = root / 'attempts/a-first/inputs/input.gjf'
    path.write_text(path.read_text().replace('O 0 0 0', 'S 0 0 0'))
    update_json(path.parent.parent / 'manifest.json', inputs=[dict(name=path.name, sha256=sha256(path.read_bytes()).hexdigest())])
    with pytest.raises(ValueError, match='geometry mismatch'):
        build(sample)


@pytest.mark.parametrize('field', ['elements', 'charge', 'multiplicity', 'protocol', 'version'])
def test_reference_rejections(sample, field):
    root, data = sample
    directory = attempt(root, 'ref', WATER, -75.1)
    data['systems'][0]['fragments'][0]['reference_attempt'] = 'ref'
    if field == 'elements':
        (directory / 'final.xyz').write_text('3\nwrong elements\nS 0 0 0\nH 1 0 0\nH 0 1 0\n')
    elif field == 'charge':
        update_json(directory / 'facts.json', charge=1)
    elif field == 'multiplicity':
        update_json(directory / 'facts.json', multiplicity=3)
    elif field == 'version':
        update_json(directory / 'facts.json', program_version='Gaussian 09 Revision D.01')
    else:
        facts = json.loads((directory / 'facts.json').read_text())
        facts['route'] = facts['job_sections'][0]['route'] = ROUTE.replace('STO-3G', '6-31G')
        write_json(directory / 'facts.json', facts)
    with pytest.raises(ValueError, match='system a / fragment first.*reference'):
        build(sample)


@pytest.mark.parametrize('internal_freq', [False, True])
def test_final_geometry_uses_final_energy_including_internal_optfreq(sample, internal_freq):
    root, data = sample
    data['systems'][0]['complex_geometry'] = 'final'
    path = root / 'attempts/a-complex/facts.json'
    facts = json.loads(path.read_text())
    facts['route'] = facts['job_sections'][0]['route'] = ROUTE.replace('SP', 'Opt Freq' if internal_freq else 'Opt')
    if internal_freq:
        facts['job_sections'].append(dict(index=2, route=ROUTE.replace('SP', 'Freq'), termination='normal',
                                         start_kind='internal', internal_step=2))
        facts['fact_sources']['energies.scf'] = 2
    write_json(path, facts)
    # Input no longer matches the final geometry; it must not be used.
    (path.parent / 'inputs/input.gjf').write_text('deliberately not the selected geometry')
    assert build(sample)['systems'][0]['E_int']['hartree'] == pytest.approx(-0.1)


@pytest.mark.parametrize('kind', ['input-opt', 'unrelated-link1', 'wrong-route', 'missing-final', 'scan'])
def test_energy_geometry_binding_rejects_ambiguous_sources(sample, kind):
    root, data = sample
    path = root / 'attempts/a-complex/facts.json'
    facts = json.loads(path.read_text())
    if kind == 'input-opt':
        facts['route'] = facts['job_sections'][0]['route'] = ROUTE.replace('SP', 'Opt')
    else:
        data['systems'][0]['complex_geometry'] = 'final'
        if kind == 'missing-final':
            facts['final_input_geometry'] = None
        elif kind == 'scan':
            facts['scan'] = {'points': []}
        else:
            facts['job_sections'].append(dict(index=2, route=ROUTE if kind == 'unrelated-link1' else
                                              ROUTE.replace('HF', 'B3LYP'), termination='normal',
                                              start_kind='link1', internal_step=None))
            facts['fact_sources']['energies.scf'] = 2
    write_json(path, facts)
    with pytest.raises(ValueError, match='system a:'):
        build(sample)


@pytest.mark.parametrize('name', ['asm.json', 'asm.md', 'fragment.xyz'])
@pytest.mark.parametrize('kind', ['file', 'directory', 'symlink', 'dangling'])
def test_existing_outputs_are_never_overwritten(sample, name, kind):
    root, _ = sample
    path = root / 'analyses' / name
    if kind == 'file':
        path.write_bytes(b'keep')
    elif kind == 'directory':
        path.mkdir()
    else:
        path.symlink_to(root / ('study.md' if kind == 'symlink' else 'missing'))
    with pytest.raises((ValueError, FileExistsError)):
        if name == 'fragment.xyz':
            asm.split('a-complex', geometry='input', atom_list='1-3', name='water', out=path)
        else:
            build(sample)
    assert sorted(p.name for p in (root / 'analyses').iterdir()) == sorted([name, 'definition.json'])
    if kind == 'file':
        assert path.read_bytes() == b'keep'


@pytest.mark.parametrize('name', ['analyses/definition.json', 'attempts/a-first/facts.json',
                                 'attempts/a-first/manifest.json', 'attempts/a-first/inputs/input.gjf',
                                 'attempts/a-complex/final_input.xyz', 'attempts/a-first', 'analyses'])
def test_symlink_sources_and_output_directories_rejected(sample, name):
    root, data = sample
    data['systems'][0]['complex_geometry'] = 'final'
    write_json(root / 'analyses/definition.json', data)
    path = root / name
    destination = root.parent / 'external'
    path.rename(destination)
    path.symlink_to(destination, target_is_directory=destination.is_dir())
    with pytest.raises(ValueError, match='Symbolic links'):
        asm.summary('analyses/definition.json', 'analyses/asm.json', study=str(root))


@pytest.mark.parametrize('value', ['../outside', '/outside/attempt', 'attempts/a-first'])
def test_attempt_escape_rejected(sample, value):
    sample[1]['systems'][0]['fragments'][0]['attempt'] = value
    with pytest.raises(ValueError, match='fragment first'):
        build(sample)


@pytest.mark.parametrize('value', ['asm.json', 'analyses/../escape.json', '../escape.json', 'analyses/asm.xyz'])
def test_output_escape_and_suffix_rejected(sample, value):
    with pytest.raises(ValueError):
        asm.summary('analyses/definition.json', value)


def test_definition_outside_analyses_rejected(sample):
    with pytest.raises(ValueError):
        asm.summary('study.md', 'analyses/asm.json')


def test_input_hash_and_source_change_are_rejected(sample, monkeypatch):
    root, _ = sample
    path = root / 'attempts/a-first/inputs/input.gjf'
    path.write_text(path.read_text() + '\n')
    with pytest.raises(ValueError, match='Input hash'):
        build(sample)
    update_json(path.parent.parent / 'manifest.json', inputs=[dict(name=path.name, sha256=sha256(path.read_bytes()).hexdigest())])
    original = asm._Evidence.verify
    def changed(self):
        path.write_text(path.read_text() + '\n')
        original(self)
    monkeypatch.setattr(asm._Evidence, 'verify', changed)
    with pytest.raises(ValueError, match='Evidence changed'):
        build(sample)
    assert not (root / 'analyses/asm.json').exists()


def test_manifest_binds_reports_and_facts_geometry_hashes_are_recomputable(sample):
    root, _ = sample
    result = build(sample)
    (root / 'study.md').write_text('# Synthetic\n[JSON](analyses/asm.json)\n[Markdown](analyses/asm.md)\n')
    created = inventory.create(root)
    manifest = json.loads((root / created['manifest']).read_text())
    included = {r['path']: r['sha256'] for r in manifest['files']}
    assert {'analyses/asm.json', 'analyses/asm.md', 'analyses/definition.json'}.issubset(included)
    for source in result['sources']:
        assert sha256((root / source['path']).read_bytes()).hexdigest() == source['sha256']
        if source['path'].endswith('/facts.json'):
            assert source['path'] in included
    geometries = [r for r in result['sources'] if r['path'].endswith(('.gjf', '.xyz'))]
    assert geometries and all(r['path'] not in included for r in geometries)
    for source in geometries:
        path = root / source['path']
        original = path.read_bytes()
        path.write_bytes(original + b'\n')
        assert sha256(path.read_bytes()).hexdigest() != source['sha256']
        path.write_bytes(original)


def test_summary_cli_without_configuration(sample, capsys):
    assert cli.main(['asm', 'summary', '--definition', 'analyses/definition.json',
                     '--out', 'analyses/asm.json']) == 0
    assert asm.NOTICE in capsys.readouterr().out
    assert cli.main(['asm', 'summary', '--definition', 'analyses/definition.json',
                     '--out', 'analyses/asm.json']) == 1


def test_duplicate_json_keys_rejected(sample):
    root, _ = sample
    path = root / 'analyses/definition.json'
    path.write_text('{"schema": "ag-asm-definition/1", "schema": "duplicate"}')
    with pytest.raises(ValueError, match='Duplicate JSON key'):
        asm.summary(path, 'analyses/asm.json')


@pytest.mark.parametrize('mismatch', [False, True])
def test_current_facts_parser_optfreq_geometry_and_energy_are_usable(tmp_path, mismatch):
    from ag.facts import parse_facts
    from test_facts import attempt as fixture_attempt

    # Existing reviewed water fixture only; verifies actual parser field ownership.
    directory = fixture_attempt(tmp_path)
    facts, geometries = parse_facts(directory)
    if mismatch:
        facts['job_sections'][1]['route'] = facts['job_sections'][1]['route'].replace('STO-3G', '6-31G')
    write_json(directory / 'facts.json', facts)
    for name, content in geometries.items():
        (directory / name).write_text(content)
    evidence = asm._Evidence(tmp_path)
    if mismatch:
        with pytest.raises(ValueError, match='Energy section protocol differs'):
            asm._load_energy(evidence, 'water', 'final', 'system water')
        return
    row, frame = asm._load_energy(evidence, 'water', 'final', 'system water')
    assert row['energy']['hartree'] == facts['energies']['scf']
    assert frame.symbols == ('O', 'H', 'H')
    assert facts['fact_sources']['energies.scf'] == 2
    assert facts['fact_sources']['final_input_geometry'] == 1
    evidence.verify()


def test_internal_frequency_inherits_explicit_parent_solvent(sample):
    root, data = sample
    data['systems'][0]['complex_geometry'] = 'final'
    path = root / 'attempts/a-complex/facts.json'
    facts = json.loads(path.read_text())
    facts['route'] = facts['job_sections'][0]['route'] = ROUTE.replace('SP', 'Opt Freq')
    facts['job_sections'].append(dict(index=2, route='#p RHF/STO-3G SCRF=Check Freq',
                                     termination='normal', start_kind='internal', internal_step=2))
    facts['fact_sources']['energies.scf'] = 2
    write_json(path, facts)
    assert build(sample)['systems'][0]['complex']['protocol']['solvent'] == 'water'
