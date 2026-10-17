"""Synthetic water motions; no private logs or live configuration."""

from contextlib import contextmanager
from hashlib import sha256
import json
from pathlib import Path

import pytest

from ag import cli, fragments, geometry as geo, irc_review as ir
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


@pytest.mark.parametrize('missing', [None, ('geometry', 2)])
def test_path_hashes_bind_pending_and_written_xyz_bytes(sample, monkeypatch, missing):
    change_log(sample, missing=missing)
    writer = ir._write_outputs
    pending_hashes = {}

    def check_before_write(parent, payloads):
        assert len(payloads) == 4
        assert all(not (parent / name).exists() for name in payloads)
        report = json.loads(payloads['review.json'])
        for direction, item in report['directions'].items():
            path = item['path_geometry']
            pending_hashes[direction] = sha256(payloads[path['path']]).hexdigest()
            assert path['sha256'] == pending_hashes[direction]
        writer(parent, payloads)

    monkeypatch.setattr(ir, '_write_outputs', check_before_write)
    result = build(sample)
    assert json.loads((sample / 'analyses/review.json').read_bytes()) == result
    for direction, item in result['directions'].items():
        path = item['path_geometry']
        actual = sha256((sample / 'analyses' / path['path']).read_bytes()).hexdigest()
        assert path['sha256'] == pending_hashes[direction] == actual


@pytest.mark.parametrize('case,json_hash,md_hash,forward_hash', [
    ('complete', '4a0ae374a82491eed8606f67751802fa99d5be607bba9825fecb334cca68546b',
     '8f35802df6477fb215629861b80ed6e6aad959fc684e4d245e179a477b5cb459',
     'c7749aed2d8b7e4640bfdd2e15171e4261c9c50ce1b571becfb94e885c4c6ea6'),
    ('failure', '112371df6a9b445b21298724d7f0ca57781be14e476bc4a19775ab8b8887994a',
     '0efd5119c8321ff91e3613ede60fc06912129fd82e641534572e32ac5122aa6b',
     'c7749aed2d8b7e4640bfdd2e15171e4261c9c50ce1b571becfb94e885c4c6ea6'),
    ('missing_geometry', '52c748461444d8e90fe2d20153af8bdfaf34440135fd4c06e9a341c76d9bdcb4',
     '28db495f99d2559279c3f27e653d3868c3b56f2648b60aeaa2c8caaa03d04a34',
     '107f66cdc975bb0d338a69d72fd4769fe9b05da521c37a341547af30c9646a8a'),
])
def test_outputs_match_main_bytes_except_path_hashes_and_spin_prefix(sample, monkeypatch, case, json_hash, md_hash, forward_hash):
    # Captured from unmodified main 0cccf9598e4d751138144dc43b39e1742547c45f.
    # Pin release metadata and platform-dependent SVD rounding in this byte test.
    monkeypatch.setattr(ir, '__version__', '4.2.2')
    monkeypatch.setattr(ir, 'aligned_rmsd', lambda a, b: 0.0)
    if case == 'failure':
        change_log(sample, ending='failure')
    elif case == 'missing_geometry':
        change_log(sample, missing=('geometry', 2))
    build(sample)
    directory = sample / 'analyses'
    raw = (directory / 'review.json').read_bytes()
    report = json.loads(raw)
    # T99 completes the implicit singlet prefix; only that label may change.
    assert report['protocol']['method'] == 'rhf'
    assert raw.count(b'"method": "rhf"') == 1
    raw = raw.replace(b'"method": "rhf"', b'"method": "hf"', 1)
    # Remove only the two new field lines; preserve all other JSON bytes.
    for item in report['directions'].values():
        digest = item['path_geometry']['sha256']
        field = f',\n        "sha256": "{digest}"'.encode()
        assert raw.count(field) == 1
        raw = raw.replace(field, b'', 1)
    assert sha256(raw).hexdigest() == json_hash
    for suffix, expected in [('md', md_hash), ('forward.xyz', forward_hash),
                             ('reverse.xyz', '9ea94164f0c54e6f07d0f15a76350d1b772baf4925faf41bfba219a950cf1b91')]:
        assert sha256((directory / ('review.' + suffix)).read_bytes()).hexdigest() == expected


@pytest.mark.parametrize('fail_at', [1, 2, 3, 4])
def test_output_write_failure_rolls_back_all_four_files(sample, monkeypatch, fail_at):
    before = snapshot(sample)
    fdopen = fragments.os.fdopen
    count = 0

    class BrokenWriter:
        def write(self, content):
            raise OSError('synthetic disk failure')

    @contextmanager
    def fail(fd, *args, **kwargs):
        nonlocal count
        count += 1
        with fdopen(fd, *args, **kwargs) as handle:
            yield BrokenWriter() if count == fail_at else handle

    monkeypatch.setattr(fragments.os, 'fdopen', fail)
    with pytest.raises(OSError, match='synthetic disk failure'):
        build(sample)
    assert snapshot(sample) == before


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


@pytest.mark.parametrize('parent', ['forward', 'reverse', None])
def test_rotated_endpoint_requires_matching_provenance_and_records_rmsd(sample, parent):
    original = rows(1.1, 1.9)
    rotated = [f'{symbol} {3 - float(y):.6f} {-2 + float(x):.6f} {float(z) + 1:.6f}'
               for symbol, x, y, z in (row.split() for row in original)]
    edit_input(sample, 'forward-opt', lambda s: s.replace('\n'.join(original), '\n'.join(rotated)))
    if parent is not None:
        update_json(sample / 'attempts/forward-opt/manifest.json',
                    parents=[{'attempt_id': parent, 'relation': 'endpoint_of'}])
    if parent != 'forward':
        with pytest.raises(ValueError, match='Endpoint input geometry'):
            build(sample)
        return
    result = build(sample)
    endpoint = result['directions']['forward']['criteria']['endpoint']
    assert endpoint['status'] == 'met'
    assert endpoint['input_max_displacement_angstrom'] > 1
    assert endpoint['input_aligned_rmsd_angstrom'] < 1e-12
    assert endpoint['provenance'] == 'endpoint_of_and_alignment'
    assert endpoint['provenance_note'] == '来源关系加对齐核对'
    assert result['thresholds']['endpoint_aligned_rmsd_angstrom'] == 1e-3
    markdown = (sample / 'analyses/review.md').read_text()
    assert 'input_aligned_rmsd_angstrom' in markdown and '来源关系加对齐核对' in markdown


@pytest.mark.parametrize('change', ['bond_length', 'row_swap'])
def test_endpoint_provenance_cannot_excuse_a_different_structure_or_mapping(sample, change):
    original = rows(1.1, 1.9)
    replacement = rows(1.2, 1.9) if change == 'bond_length' else (original[0], original[2], original[1])
    edit_input(sample, 'forward-opt', lambda s: s.replace('\n'.join(original), '\n'.join(replacement)))
    update_json(sample / 'attempts/forward-opt/manifest.json', parents=[{'attempt_id': 'forward', 'relation': 'endpoint_of'}])
    with pytest.raises(ValueError, match='aligned RMSD <= 1e-3'):
        build(sample)
    assert not (sample / 'analyses/review.json').exists()


def test_endpoint_direct_coordinate_path_is_reported_without_provenance(sample):
    endpoint = build(sample)['directions']['forward']['criteria']['endpoint']
    assert endpoint['provenance'] == 'coordinates'
    assert endpoint['provenance_note'] == '坐标一致'
    assert endpoint['input_max_displacement_angstrom'] == 0
    assert endpoint['input_aligned_rmsd_angstrom'] < 1e-12


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
        # T99 adds parser metadata and warns that this unframed synthetic
        # route has unknown type. Preserve the old byte baseline for all
        # scientific fields and IRC geometry after checking those exact deltas.
        from ag import __version__
        facts = values[1][0]
        assert facts.pop('parser') == {'ag_version': __version__, 'rules': 'route-join-v1'}
        assert facts['job_sections'][0]['route'] is None
        warning = 'Unexpected or unrecognized job section 1 at line 1; '
        assert facts['parser_warning'].startswith(warning)
        facts['parser_warning'] = facts['parser_warning'].removeprefix(warning)
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
