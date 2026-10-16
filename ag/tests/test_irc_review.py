"""Synthetic water motions; no private logs or live configuration."""

from hashlib import sha256
import json
from pathlib import Path

import pytest

from ag import cli, geometry as geo, irc_review as ir
from ag._irc import parse_irc, parse_irc_points
from ag.facts import parse_facts
from test_asm import attempt, update_json, write_json
from test_irc import irc_attempt, irc_log


def rows(a=1.5, b=1.5):
    return ('O 0 0 0', f'H {a:.6f} 0 0', f'H 0 {b:.6f} 0')


def table(coords, current=False):
    head = ' CURRENT STRUCTURE\n Cartesian Coordinates (Ang):' if current else ' Standard orientation:'
    body = []
    for i, (symbol, *xyz) in enumerate((row.split() for row in coords), 1):
        body.append(f' {i} {8 if symbol == "O" else 1} ' + ('' if current else '0 ') + ' '.join(xyz))
    return head + '\n --------------------\n Center Atomic Coordinates\n Number Number X Y Z\n --------------------\n' + '\n'.join(body) + '\n --------------------\n'


def log(direction='forward', drop=6., ending='completed', missing=None, rise=False, jump=None):
    text = f' #p HF/STO-3G IRC=({direction},CalcFC,MaxPoints=4)\n --------------------\n'
    text += ' Charge = 0 Multiplicity = 1\n INPUT DATA FOR L123\n Maximum points per path = 4\n'
    for i in range(5):
        offset = i * .1 * (1 if direction == 'forward' else -1)
        coords = rows(1.5 - offset, 1.5 + offset)
        if jump == 'rmsd' and i == 3:
            coords = rows(5, 1.5)
        # Trial geometry deliberately differs from the accepted CURRENT STRUCTURE.
        text += table(rows(9, 9) if i else coords)
        if missing != ('energy', i):
            energy = -75 - drop / geo.HARTREE_TO_KCAL * i / 4
            if rise and i == 3:
                energy = -75.
            if jump == 'energy' and i == 3:
                energy = -76.
            text += f' SCF Done: E(RHF) = {energy:.12f} A.U.\n'
        text += f' Point Number: {i} Path Number: 1\n'
        if i:
            text += table(coords, current=True) if missing != ('geometry', i) else ' CURRENT STRUCTURE\n truncated\n'
    if ending == 'failure':
        text += table(rows(8, 8)) + ' SCF Done: E(RHF) = -76.0 A.U.\n Maximum number of corrector steps exceded.\n Error termination\n'
    elif ending == 'completed':
        text += f' Calculation of {direction.upper()} path complete.\n Normal termination of Gaussian\n'
    elif ending == 'maxpoints':
        text += ' Maximum number of points reached\n Normal termination of Gaussian\n'
    return text


@pytest.fixture
def sample(tmp_path, monkeypatch):
    root = tmp_path / 'study'
    (root / 'analyses').mkdir(parents=True)
    (root / 'study.md').write_text('# Synthetic water motion\n')
    monkeypatch.setattr(cli, 'load_config', lambda **kw: pytest.fail('no remote configuration'))
    monkeypatch.setattr('ag.transport.SSHTransport', lambda *a, **kw: pytest.fail('no SSH'))
    attempt(root, 'ts', rows(), -75., route='#p HF/STO-3G Opt=(TS,CalcFC) Freq')
    for direction, end, ref in [('forward', rows(1.1, 1.9), rows(1., 2.)), ('reverse', rows(1.9, 1.1), rows(2., 1.))]:
        d = attempt(root, direction, rows(), -75., route=f'#p HF/STO-3G IRC=({direction},CalcFC,MaxPoints=4)')
        (d / 'outputs').mkdir()
        (d / 'outputs/input.log').write_text(log(direction))
        d = attempt(root, direction + '-opt', end, -75.1, route='#p HF/STO-3G Opt Freq')
        update_json(d / 'facts.json', opt_converged=True, freq_step_converged=True, n_imag=0,
                    vibrational_modes_complete=True, n_vibrational_modes=3, expected_vibrational_modes=3)
        attempt(root, direction + '-ref', ref, -75.1, route='#p HF/STO-3G Opt Freq')
    report = dict(status='匹配', assignment={'forward': 'product', 'reverse': 'reactant'}, input_issues=[],
                  sources={key: {'source': value} for key, value in [('ts', 'ts'), ('forward', 'forward-opt'),
                           ('reverse', 'reverse-opt'), ('reactant', 'reverse-ref'), ('product', 'forward-ref')]},
                  comparisons={'forward': {'product': {'status': '匹配'}}, 'reverse': {'reactant': {'status': '匹配'}}})
    write_json(root / 'analyses/compare.json', report)
    return root


def build(root, **changes):
    args = dict(ts='ts', forward='forward', reverse='reverse', pairs=['1-2', '1-3'],
                forward_reference='forward-ref', reverse_reference='reverse-ref',
                forward_endpoint='forward-opt', reverse_endpoint='reverse-opt',
                irc_compare='analyses/compare.json', study=str(root), out='analyses/review.json')
    args.update(changes)
    return ir.review(**args)


def change_log(root, **kwargs):
    (root / 'attempts/forward/outputs/input.log').write_text(log(**kwargs))


def snapshot(root):
    return {p.relative_to(root).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns) for p in root.rglob('*') if p.is_file()}


def test_complete_two_directions_readonly_hashes_frames_and_lines(sample):
    before = snapshot(sample)
    result = build(sample)
    assert result['schema'] == 'ag-irc-review/1'
    assert [d['summary'] for d in result['directions'].values()] == [ir.READY, ir.READY]
    for direction, d in result['directions'].items():
        assert [c['status'] for c in d['criteria'].values()] == ['tool_checks_passed', 'met', 'met', 'met']
        assert d['criteria']['energy_drop']['drop_kcal_mol'] == pytest.approx(6)
        frames = geo.read_xyz(sample / 'analyses' / d['path_geometry']['path'])
        assert len(frames) == 5 and frames[0].coordinates[1][0] == 1.5
        for point in d['points']:
            assert point['geometry_frame'] == point['point']
            assert point['distances_angstrom']['1-2'] == pytest.approx(math_distance(frames[point['geometry_frame']], 0, 1))
            text = (sample / d['log']['path']).read_text().splitlines()
            assert 'Point Number:' in text[point['point_line'] - 1]
            assert 'SCF Done:' in text[point['energy_line'] - 1]
            assert 'CURRENT STRUCTURE' in text[point['geometry_line'] - 1] if point['point'] else 'orientation' in text[point['geometry_line'] - 1]
        assert {p['change'] for p in d['criteria']['midpoint']['pairs']} == {'forming', 'breaking'}
    for source in result['inputs']:
        assert sha256((sample / source['path']).read_bytes()).hexdigest() == source['sha256']
    after = snapshot(sample)
    for name in ('review.json', 'review.md', 'review.forward.xyz', 'review.reverse.xyz'):
        after.pop('analyses/' + name)
    assert after == before
    assert str(sample) not in json.dumps(result)
    assert '已验证' not in (sample / 'analyses/review.md').read_text()


def math_distance(frame, i, j):
    import math
    return math.dist(frame.coordinates[i], frame.coordinates[j])


@pytest.mark.parametrize('case,status', [('supported', 'met_by_endpoint_optimization'), ('identity', 'not_met'),
                                        ('midpoint', 'not_met'), ('zero', 'not_met'), ('uphill', 'not_met')])
def test_subthreshold_requires_all_other_criteria(sample, case, status):
    change_log(sample, drop=0 if case == 'zero' else -1 if case == 'uphill' else 1.5)
    if case == 'identity':
        path = sample / 'analyses/compare.json'; data = json.loads(path.read_text())
        data['comparisons']['forward']['product']['status'] = '不匹配'; write_json(path, data)
    if case == 'midpoint':
        (sample / 'attempts/forward-ref/final.xyz').write_text('3\nSynthetic\n' + '\n'.join(rows(.5, 2.5)) + '\n')
    d = build(sample)['directions']['forward']
    assert d['criteria']['energy_drop']['status'] == status
    assert d['summary'] == (ir.READY if case == 'supported' else ir.INCOMPLETE)
    assert d['criteria']['energy_drop']['threshold_kcal_mol'] == 3.


@pytest.mark.parametrize('kwargs,status', [({'ending': 'failure'}, 'not_met'), ({'ending': 'truncated'}, 'unknown'),
    ({'rise': True}, 'not_met'), ({'jump': 'energy'}, 'not_met'), ({'jump': 'rmsd'}, 'not_met'),
    ({'missing': ('energy', 2)}, 'unknown'), ({'missing': ('geometry', 2)}, 'unknown'), ({'ending': 'maxpoints'}, 'tool_checks_passed')])
def test_continuity_failures_missing_data_and_maxpoints(sample, kwargs, status):
    change_log(sample, **kwargs)
    d = build(sample)['directions']['forward']
    assert d['criteria']['continuity']['status'] == status
    assert d['last_accepted_point'] == 4
    if kwargs.get('ending') == 'failure':
        assert d['stop_reason'] == 'corrector_failed'
        assert d['points'][-1]['energy_hartree'] > -76
    if kwargs.get('missing') == ('geometry', 2):
        assert d['points'][2]['geometry_frame'] is None
        assert d['points'][3]['geometry_frame'] == 2


@pytest.mark.parametrize('missing', ['reference', 'endpoint', 'irc_compare', 'frequency'])
def test_missing_support_is_unknown(sample, missing):
    options = {}
    if missing == 'frequency':
        update_json(sample / 'attempts/forward-opt/facts.json', freq_step_converged=None)
    else:
        options['irc_compare' if missing == 'irc_compare' else 'forward_' + missing] = None
    d = build(sample, **options)['directions']['forward']
    assert d['criteria']['midpoint' if missing == 'reference' else 'endpoint']['status'] == 'unknown'
    assert d['summary'] == ir.INCOMPLETE


def test_indistinguishable_pair(sample):
    (sample / 'attempts/forward-ref/final.xyz').write_text('3\nSynthetic\n' + '\n'.join(rows(1.49, 2)) + '\n')
    d = build(sample)['directions']['forward']
    assert d['criteria']['midpoint']['status'] == 'unknown'
    assert d['criteria']['midpoint']['pairs'][0]['status'] == 'unknown'


@pytest.mark.parametrize('field,value', [('termination', 'error'), ('opt_converged', False),
    ('freq_step_converged', False), ('vibrational_modes_complete', False), ('n_imag', 1), ('n_vibrational_modes', 2)])
def test_endpoint_minimum_requirements(sample, field, value):
    update_json(sample / 'attempts/forward-opt/facts.json', **{field: value})
    assert build(sample)['directions']['forward']['criteria']['endpoint']['status'] == 'not_met'


def edit_input(root, name, transform):
    directory = root / 'attempts' / name
    path = directory / 'inputs/input.gjf'
    path.write_text(transform(path.read_text()))
    update_json(directory / 'manifest.json', inputs=[dict(name='input.gjf', sha256=sha256(path.read_bytes()).hexdigest())])


@pytest.mark.parametrize('case,message', [('geometry', 'Endpoint input geometry'), ('report', 'different endpoint'),
    ('protocol', 'protocol differs'), ('atoms', 'Atom count/element order'), ('both', 'direction: both'),
    ('same', 'independent Attempts'), ('report_ts', 'different TS'), ('reference', 'reference differs')])
def test_reject_wrong_evidence(sample, case, message):
    options = {}
    if case == 'geometry':
        edit_input(sample, 'forward-opt', lambda s: s.replace('1.100000', '1.200000'))
    elif case in ('report', 'report_ts', 'reference'):
        p = sample / 'analyses/compare.json'; data = json.loads(p.read_text())
        data['sources'][{'report': 'forward', 'report_ts': 'ts', 'reference': 'product'}[case]]['source'] = 'reverse-opt'
        write_json(p, data)
    elif case == 'protocol':
        edit_input(sample, 'forward', lambda s: s.replace('STO-3G', '6-31G'))
        update_json(sample / 'attempts/forward/facts.json', route='#p HF/6-31G IRC=Forward')
    elif case == 'atoms':
        p = sample / 'attempts/forward-ref/final.xyz'; p.write_text(p.read_text().replace('O ', 'S '))
    elif case == 'both':
        p = sample / 'attempts/forward/outputs/input.log'; p.write_text(p.read_text() + ' Follow reaction path in both directions\n')
    else:
        options['reverse'] = 'forward'
    with pytest.raises(ValueError, match=message):
        build(sample, **options)
    assert not (sample / 'analyses/review.json').exists()


def test_endpoint_graph_provenance_alternative(sample):
    edit_input(sample, 'forward-opt', lambda s: s.replace('1.100000', '1.200000'))
    update_json(sample / 'attempts/forward-opt/manifest.json', parents=[{'attempt_id': 'forward', 'relation': 'endpoint_of'}])
    assert build(sample)['directions']['forward']['criteria']['endpoint']['provenance'] == 'endpoint_of'


@pytest.mark.parametrize('path', ['attempts/forward/outputs/input.log', 'attempts/forward/inputs/input.gjf',
    'attempts/ts/facts.json', 'attempts/forward-opt/manifest.json', 'attempts/forward-ref/final.xyz', 'analyses/compare.json',
    'attempts/forward', 'analyses'])
def test_symlink_sources_are_refused(sample, path):
    source = sample / path; dest = sample.parent / 'linked'
    source.rename(dest); source.symlink_to(dest, target_is_directory=dest.is_dir())
    with pytest.raises(ValueError, match='Symbolic links'):
        build(sample)


@pytest.mark.parametrize('name', ['review.json', 'review.md', 'review.forward.xyz', 'review.reverse.xyz'])
@pytest.mark.parametrize('kind', ['file', 'symlink'])
def test_all_outputs_exclusive(sample, name, kind):
    path = sample / 'analyses' / name
    if kind == 'file':
        path.write_text('keep')
    else:
        path.symlink_to(sample / 'missing')
    with pytest.raises((ValueError, FileExistsError)):
        build(sample)
    assert sorted(p.name for p in (sample / 'analyses').iterdir()) == sorted(['compare.json', name])


@pytest.mark.parametrize('field,value', [('forward', '../outside'), ('forward_reference', '../outside.xyz'),
    ('forward_endpoint', '/outside/attempts/opt'), ('irc_compare', '../report.json'), ('out', 'review.json')])
def test_study_boundary(sample, field, value):
    with pytest.raises(ValueError):
        build(sample, **{field: value})


def test_external_output_keeps_signed_study_unchanged(sample):
    before = snapshot(sample)
    result = build(sample, out=sample.parent / 'temporary-review.json')
    assert snapshot(sample) == before
    assert result['directions']['forward']['summary'] == ir.READY


def test_zero_point_energy_warning_and_noise_option(sample):
    update_json(sample / 'attempts/ts/facts.json', energies={'scf': -75.1})
    change_log(sample, drop=-.008)
    d = build(sample)['directions']['forward']
    assert d['ts_reference']['irc_point_zero_hartree'] == -75
    assert d['warnings'] and d['criteria']['continuity']['status'] == 'tool_checks_passed'
    d = build(sample, energy_noise=0, out='analyses/strict.json')['directions']['forward']
    assert d['criteria']['continuity']['status'] == 'not_met'


@pytest.mark.parametrize('value', [float('nan'), float('inf'), -1, 0])
def test_bad_threshold(sample, value):
    with pytest.raises(ValueError):
        build(sample, energy_threshold=value)


def test_no_points_is_unknown_not_a_minimum(sample):
    change_log(sample)
    path = sample / 'attempts/forward/outputs/input.log'
    text = path.read_text().split(' Point Number: 1')[0]
    text = text[:text.index(' Point Number: 0') + len(' Point Number: 0 Path Number: 1\n')]
    path.write_text(text + ' Maximum number of corrector steps exceded.\n Error termination\n')
    d = build(sample, forward_endpoint=None)['directions']['forward']
    assert d['last_accepted_point'] is None
    assert d['criteria']['energy_drop']['status'] == 'unknown'
    assert d['criteria']['midpoint']['status'] == 'unknown'
    assert d['criteria']['continuity']['status'] == 'not_met'


def test_cli_and_changed_evidence(sample, monkeypatch):
    assert cli.main(['irc-review', '--study', str(sample), '--ts', 'ts', '--forward', 'forward', '--reverse', 'reverse',
                     '--pair', '1-2', '--out', 'analyses/cli.json']) == 0
    verify = ir._Evidence.verify
    def changed(self):
        path = sample / 'attempts/ts/facts.json'; path.write_text(path.read_text() + '\n')
        verify(self)
    monkeypatch.setattr(ir._Evidence, 'verify', changed)
    with pytest.raises(ValueError, match='changed during collection'):
        build(sample)


def test_existing_irc_facts_and_parser_bytes(tmp_path):
    golden = json.loads((Path(__file__).parent / 'fixtures/irc_review_compatibility.json').read_text())
    directory = irc_attempt(tmp_path)
    for ending, expected in golden.items():
        text = irc_log(ending)
        (directory / 'outputs/water.log').write_text(text)
        values = [parse_irc(text), parse_facts(directory)]
        for value, digest in zip(values, expected):
            raw = json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()
            assert sha256(raw).hexdigest() == digest


def test_xyz_reference_and_endpoint_log_evidence(sample):
    p = sample / 'analyses/compare.json'; report = json.loads(p.read_text())
    ref = sample / 'structures/reference.xyz'; ref.parent.mkdir()
    ref.write_bytes((sample / 'attempts/forward-ref/final.xyz').read_bytes())
    report['sources']['product']['source'] = 'structures/reference.xyz'; write_json(p, report)
    d = sample / 'attempts/forward-opt'; (d / 'outputs').mkdir()
    (d / 'outputs/input.log').write_text(' Optimization completed.\n Harmonic frequencies\n Frequencies -- 1 2 3\n Normal termination of Gaussian\n')
    update_json(d / 'facts.json', freq_step_convergence={'frequency_line': 2, 'table_line': None, 'criteria': {}})
    c = build(sample, forward_reference='structures/reference.xyz')['directions']['forward']['criteria']['endpoint']
    assert c['status'] == 'met' and c['log_lines']['termination'] == [4]
    assert c['log_lines']['frequency'] == [2, 3]
    assert c['frequency_convergence']['value']['frequency_line'] == 2


def test_missing_start_energy_and_geometry_do_not_borrow_first_trial(sample):
    path = sample / 'attempts/forward/outputs/input.log'
    text = path.read_text()
    start = text.index(' Standard orientation:')
    end = text.index(' Point Number: 0')
    path.write_text(text[:start] + text[end:])
    d = build(sample)['directions']['forward']
    assert d['points'][0]['energy_hartree'] is None
    assert d['points'][0]['geometry_kind'] == 'irc_input'
    assert d['criteria']['continuity']['status'] == 'unknown'
    assert d['criteria']['energy_drop']['status'] == 'unknown'
    assert all(p['relative_energy_kcal_mol'] is None for p in d['points'])


@pytest.mark.parametrize('pair', ['0-1', '1-1', '1-99', 'a-b', ''])
def test_bad_pairs(sample, pair):
    with pytest.raises(ValueError):
        build(sample, pairs=[pair])
