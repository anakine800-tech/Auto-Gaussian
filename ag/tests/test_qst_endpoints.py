"""T134: fictional fetched minima and synthetic coordinates; no remote access."""
from dataclasses import replace
from hashlib import sha256
import json

import numpy as np
import pytest

from ag import catalog, catalog_v2 as v2, cli, gaussian_input, geometry as geo, qst_endpoints as qst
from test_catalog import files, make_attempt, write_json

ROUTE = '# HF/STO-3G Opt=(QST2,CalcFC)'
REACTANT = geo.Frame(('C', 'Cl', 'Cl', 'H', 'H', 'H'),
    ((0, 0, 0), (-4, 0, 0), (1.8, 0, 0), (-.36, 1.02, 0),
     (-.36, -.51, .883346), (-.36, -.51, -.883346)))
PRODUCT = replace(REACTANT, coordinates=((0, 0, 0), (-1.8, 0, 0), (4, 0, 0),
                  (.36, 1.02, 0), (.36, -.51, .883346), (.36, -.51, -.883346)))


def make_endpoint(root, suffix, frame, charge=-1):
    xyz = geo.xyz_text([frame])
    identity = make_attempt(root, suffix, '# HF/STO-3G Opt Freq', charge=charge,
                            multiplicity=1, geometry='\n'.join(xyz.splitlines()[2:]))
    path = root / 'attempts' / identity
    write_json(path / 'facts.json', dict(schema='ag-facts/1', opt_converged=True, n_imag=0))
    (path / 'final.xyz').write_text(xyz)
    return identity


@pytest.fixture
def endpoints(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('QST endpoints must not read credentials or create a remote transport')
    monkeypatch.setattr(catalog, 'load_config', forbidden)
    from ag.transport import SSHTransport
    monkeypatch.setattr(SSHTransport, '__init__', forbidden)
    root = tmp_path / 'synthetic-endpoints'
    (root / 'attempts').mkdir(parents=True)
    (root / 'study.md').write_text('# Synthetic validation only\n')
    r = make_endpoint(root, 'reactant', REACTANT)
    # Independently numbered, translated and rotated product.
    order = [4, 2, 0, 5, 1, 3]
    rotation = np.array([[0, 1, 0], [-1, 0, 0], [0, 0, 1]])
    points = np.array(PRODUCT.coordinates)[order] @ rotation + [3, 4, 5]
    p = make_endpoint(root, 'product', replace(PRODUCT,
        symbols=tuple(PRODUCT.symbols[i] for i in order), coordinates=tuple(map(tuple, points))))
    mapping = root.parent / 'mapping.json'
    write_json(mapping, dict(product_to_reactant=[[i + 1, j + 1] for i, j in enumerate(order)]))
    return root, r, p, mapping, root.parent / 'draft.gjf'


def command(data, *extra):
    root, r, p, mapping, out = data
    return ['qst-endpoints', str(root), '--reactant', r, '--product', p,
            '--mapping', str(mapping), '--route', ROUTE, '--out', str(out), '--json', *extra]


def run(data, capsys, *extra):
    code = cli.main(command(data, *extra))
    return code, json.loads(capsys.readouterr().out)


def draft(data):
    return gaussian_input.validate('%nprocshared=1\n%mem=1GB\n' + data[-1].read_text(), 1, 2)


def test_sn2_complete_mapping_draft_and_sources_untouched(endpoints, capsys):
    root, r, p, mapping, out = endpoints
    before = files(root)
    code, report = run(endpoints, capsys)
    assert code == 0 and files(root) == before and not (root / 'catalog').exists()
    parsed = draft(endpoints)
    assert parsed['qst_mode'] == 'QST2'
    assert [s['elements'] for s in parsed['structures']] == [list(REACTANT.symbols)] * 2
    assert [s['title'] for s in parsed['structures']] == [f'QST2 reactant {r}', f'QST2 product {p}']
    assert report['mapping_sha256'] == sha256(mapping.read_bytes()).hexdigest()
    for key, identity in [('reactant', r), ('product', p)]:
        assert report[key]['geometry_file'] == 'final.xyz'
        assert report[key]['geometry_sha256'] == sha256((root / 'attempts' / identity / 'final.xyz').read_bytes()).hexdigest()
    assert report['checked_equivalent_mappings'] == dict(reactant=5, product=5)
    assert not report['better_swaps'] and not report['warnings']
    assert report['rotation_determinant'] == pytest.approx(1)
    assert len(report['largest_displacements']) == 6
    assert report['align_rmsd'] == pytest.approx(.8228946199578384)
    assert report['gaussian_qst2']['sha256'] == sha256(out.read_bytes()).hexdigest()
    assert not out.read_text().startswith('%') and out.read_bytes().endswith(b'\n\n')


def test_core_endpoint_prefers_input_and_warns_unknown_imag(endpoints):
    root, r, *_ = endpoints
    path = root / 'attempts' / r
    raw = geo.xyz_text([replace(REACTANT, comment='Input orientation')]).encode()
    (path / 'final_input.xyz').write_bytes(raw)
    write_json(path / 'facts.json', dict(schema='ag-facts/1', opt_converged=True))
    frame, info, source, warnings = qst.endpoint(root, r)
    assert frame.symbols == REACTANT.symbols and info['charge'] == -1
    assert source['geometry_file'] == 'final_input.xyz' and source['geometry_sha256'] == sha256(raw).hexdigest()
    assert warnings and 'n_imag unknown' in warnings[0]


@pytest.mark.parametrize('damage,error', [
    ('not-fetched', 'must be fetched'), ('facts-broken', 'facts not readable'),
    ('facts-list', 'facts not readable'), ('unconverged', 'not converged'),
    ('imaginary', 'n_imag'), ('charge', 'charge unavailable'), ('multiplicity', 'multiplicity unavailable'),
    ('missing-geometry', 'No such file'), ('multi-frame', 'exactly one'),
    ('symlink', 'Symbolic links'), ('wrong-manifest-id', 'invalid manifest'),
])
def test_core_endpoint_rejections(endpoints, damage, error):
    root, r, *_ = endpoints
    path = root / 'attempts' / r
    if damage == 'not-fetched':
        write_json(path / 'status.json', dict(state='finished', job_id='1.fixture'))
    elif damage == 'facts-broken':
        (path / 'facts.json').write_text('{broken')
    elif damage == 'facts-list':
        write_json(path / 'facts.json', [])
    elif damage in ('unconverged', 'imaginary'):
        write_json(path / 'facts.json', dict(schema='ag-facts/1', opt_converged=damage != 'unconverged',
                                            n_imag=1 if damage == 'imaginary' else 0))
    elif damage in ('charge', 'multiplicity', 'wrong-manifest-id'):
        manifest = json.loads((path / 'manifest.json').read_text())
        if damage == 'wrong-manifest-id':
            manifest['attempt_id'] = 'wrong'
        else:
            del manifest['science'][damage]
        write_json(path / 'manifest.json', manifest)
    elif damage == 'missing-geometry':
        (path / 'final.xyz').unlink()
    elif damage == 'multi-frame':
        (path / 'final.xyz').write_text(geo.xyz_text([REACTANT, REACTANT]))
    elif damage == 'symlink':
        (path / 'final_input.xyz').symlink_to(path / 'final.xyz')
    with pytest.raises((ValueError, OSError), match=error):
        qst.endpoint(root, r)


def test_core_endpoint_exact_id_and_same_study(endpoints):
    root, r, *_ = endpoints
    for value in (r[:-1], str(root / 'attempts' / r), '../' + r, 'another-study-opt'):
        with pytest.raises(ValueError):
            qst.endpoint(root, value)


@pytest.mark.parametrize('pairs,error', [
    ([[1, 1]], 'cover every atom'),
    ([[1, 1], [1, 2], [3, 3], [4, 4], [5, 5], [6, 6]], 'duplicate'),
    ([[1, 1], [2, 1], [3, 3], [4, 4], [5, 5], [6, 6]], 'duplicate'),
    ([[1, 2], [2, 1], [3, 3], [4, 4], [5, 5], [6, 6]], 'elements differ'),
    ([[True, 1], [2, 2], [3, 3], [4, 4], [5, 5], [6, 6]], 'integer'),
    ([[0, 1], [2, 2], [3, 3], [4, 4], [5, 5], [6, 6]], 'integer'),
    ([[7, 1], [2, 2], [3, 3], [4, 4], [5, 5], [6, 6]], 'integer'),
])
def test_core_invalid_mapping(pairs, error):
    with pytest.raises(ValueError, match=error):
        qst.mapping(json.dumps(dict(product_to_reactant=pairs)), REACTANT, PRODUCT)


def test_core_mapping_count_and_reorder():
    with pytest.raises(ValueError, match='counts differ'):
        qst.mapping('{}', REACTANT, replace(PRODUCT, symbols=PRODUCT.symbols[:-1]))
    order = [4, 2, 0, 5, 1, 3]
    changed = replace(PRODUCT, symbols=tuple(PRODUCT.symbols[i] for i in order),
                      coordinates=tuple(PRODUCT.coordinates[i] for i in order))
    pairs = [[i + 1, j + 1] for i, j in enumerate(order)]
    assert qst.mapping(json.dumps(dict(product_to_reactant=pairs)), REACTANT, changed) == PRODUCT


@pytest.mark.parametrize('value', ['', '0', '7', '2-1', '1,1', '1-3,3', '1.5', 'all'])
def test_core_alignment_atom_validation(value):
    with pytest.raises(ValueError, match='--align-atoms'):
        qst.align_indices(value, 6)


def test_core_alignment_subset_and_better_swaps():
    assert qst.align_indices(None, 6) == list(range(6))
    assert qst.align_indices('1,4-6', 6) == [0, 3, 4, 5]
    _, report = qst.align_endpoints(REACTANT, PRODUCT, -1, [3, 4, 5])
    assert report['align_rmsd'] < 1e-8 and report['all_atoms_rmsd'] > .8
    wrong = replace(REACTANT, coordinates=tuple(REACTANT.coordinates[i] for i in [0, 1, 2, 4, 3, 5]))
    _, report = qst.align_endpoints(REACTANT, wrong, -1, list(range(6)))
    assert report['align_rmsd'] > .5
    assert {swap['endpoint'] for swap in report['better_swaps']} == {'reactant', 'product'}
    assert min(swap['rmsd_angstrom'] for swap in report['better_swaps']) < 1e-8
    assert any([4, 5] in swap['atom_pairs'] for swap in report['better_swaps'])


def test_core_graph_failure_uncertain_and_mapping_limit(monkeypatch):
    monkeypatch.setattr(geo, 'RMS_MAX_MAPPINGS', 1)
    with pytest.raises(ValueError, match='no truncation'):
        qst.equivalent_maps(REACTANT, -1, 'reactant')
    uncertain = geo.Frame(('H', 'H'), ((0, 0, 0), (.8, 0, 0)))
    with pytest.raises(ValueError, match='uncertain bonding'):
        qst.equivalent_maps(uncertain, 0, 'product')
    def fail(*args):
        raise RuntimeError('Synthetic graph failure')
    monkeypatch.setattr(geo, 'infer_molecule', fail)
    with pytest.raises(ValueError, match='graph inference failed'):
        qst.equivalent_maps(REACTANT, -1, 'product')


def test_core_mirror_chirality_uses_proper_rotation():
    # Synthetic SiHBrClF tetrahedron, outside the bond-uncertainty band.
    directions = np.array([[1, 1, 1], [1, -1, -1], [-1, 1, -1], [-1, -1, 1]]) / np.sqrt(3)
    points = np.vstack(([0, 0, 0], directions * np.array([1.48, 2.2, 2.07, 1.6])[:, None]))
    left = geo.Frame(('Si', 'H', 'Br', 'Cl', 'F'), tuple(map(tuple, points)))
    right = replace(left, coordinates=tuple(map(tuple, points * [-1, 1, 1])))
    _, report = qst.align_endpoints(left, right, 0, list(range(5)))
    assert report['rotation_determinant'] == pytest.approx(1)
    assert report['align_rmsd'] > .5
    assert report['checked_equivalent_mappings'] == dict(reactant=0, product=0)


@pytest.mark.parametrize('field,value', [('charge', 1), ('multiplicity', 3)])
def test_endpoint_state_mismatch(endpoints, capsys, field, value):
    root, _, p, *_ = endpoints
    path = root / 'attempts' / p / 'manifest.json'
    manifest = json.loads(path.read_text())
    manifest['science'][field] = value
    write_json(path, manifest)
    code, report = run(endpoints, capsys)
    assert code == 1 and 'charge or multiplicity differs' in report['error']
    assert not endpoints[-1].exists()


def test_wrong_h_mapping_refused_then_keep_reason_archived(endpoints, capsys):
    root, r, p, mapping, out = endpoints
    wrong = replace(REACTANT, coordinates=tuple(REACTANT.coordinates[i] for i in [0, 1, 2, 4, 3, 5]))
    (root / 'attempts' / p / 'final.xyz').write_text(geo.xyz_text([wrong]))
    write_json(mapping, dict(product_to_reactant=[[i, i] for i in range(1, 7)]))
    code, report = run(endpoints, capsys)
    assert code == 1 and report['better_swaps'] and not out.exists()
    assert report['skipped_better_swaps'] == []
    catalog.change(root, 'object', id='synthetic-object', name='Synthetic SN2')
    before = files(root)
    reason = 'Preserve the human-reviewed path atom identities'
    code, report = run(endpoints, capsys, '--keep-mapping', '--reason', reason,
                       '--register-candidate', '--object', 'synthetic-object', '--candidate-id', 'guess',
                       '--upgrade-catalog')
    assert code == 0 and report['keep_mapping_reason'] == reason
    event = report['candidate']['events'][0]
    assert event['origin'] == 'qst' and event['parent']['attempt'] == r
    transform = event['transform']
    assert transform['type'] == 'qst2_endpoints'
    assert transform['keep_mapping_reason'] == reason
    assert transform['skipped_better_swaps'] == report['better_swaps']
    for key in ('reactant', 'product', 'mapping_sha256', 'align_atoms', 'align_rmsd'):
        assert transform[key] == report[key]
    raw = (root / event['file']).read_bytes()
    assert sha256(raw).hexdigest() == event['sha256']
    assert not (root / event['file']).stat().st_mode & 0o222
    frame = geo.read_xyz(root / event['file'])[0]
    rows = draft(endpoints)['structures'][1]['geometry'].splitlines()
    assert frame.symbols == tuple(row.split()[0] for row in rows)
    assert np.array(frame.coordinates) == pytest.approx(np.array([row.split()[1:] for row in rows], float))
    assert {k: files(root)[k] for k in before if not k.startswith('catalog/')} == {
        k: v for k, v in before.items() if not k.startswith('catalog/')}
    assert cli.main(['catalog', 'ledger', str(root), '--object', 'synthetic-object', '--json']) == 0
    assert 'guess' in capsys.readouterr().out


@pytest.mark.parametrize('extra,error', [
    (['--keep-mapping'], 'nonempty --reason'), (['--reason', 'x'], 'nonempty --reason'),
    (['--keep-mapping', '--reason', ' '], 'nonempty --reason'),
    (['--register-candidate'], 'requires --object'), (['--object', 'unused'], 'require --register-candidate'),
    (['--title-product', ''], 'title'), (['--title-reactant', 'line\nbreak'], 'title'),
])
def test_invalid_options_no_output(endpoints, capsys, extra, error):
    code, report = run(endpoints, capsys, *extra)
    assert code == 1 and error in report['error'] and not endpoints[-1].exists()


@pytest.mark.parametrize('route', ['# HF/STO-3G Opt', '# HF/STO-3G Opt=QST3',
    '# HF/STO-3G Opt=(QST2,QST3)', '# HF/STO-3G QST2 Opt=CalcFC',
    *[f'# HF/STO-3G Opt=(QST2,{option})' for option in
      ('ModRedundant', 'ReadOpt', 'Scan', 'AddGIC', 'Freeze', 'RCFC', 'ReadFC', 'ReadCartesianFC')]])
def test_route_rejection(endpoints, capsys, route):
    code, report = run(endpoints, capsys, '--route', route)
    assert code == 1 and report['error'] and not endpoints[-1].exists()


@pytest.mark.parametrize('option', ['opt=qst2', 'OPT = (QST2, CALCFC)', 'Opt(QST2,CalcFC)'])
def test_route_variants_custom_titles_and_subset(endpoints, capsys, option):
    code, report = run(endpoints, capsys, '--route', '# HF/STO-3G ' + option,
                       '--title-reactant', 'Reactant title', '--title-product', 'Product title',
                       '--align-atoms', '4-6')
    assert code == 0 and report['align_rmsd'] < 1e-8 and report['all_atoms_rmsd'] > .8
    assert report['align_atoms'] == [4, 5, 6]
    assert [s['title'] for s in draft(endpoints)['structures']] == ['Reactant title', 'Product title']


@pytest.mark.parametrize('case', ['upgrade', 'missing-object', 'missing-channel', 'dry-run'])
def test_registration_errors_preserve_draft_and_dry_run_no_catalog_write(endpoints, capsys, case):
    root = endpoints[0]
    catalog.change(root, 'object', id='synthetic-object', name='Synthetic SN2')
    before = files(root)
    extra = ['--register-candidate', '--object', 'synthetic-object', '--candidate-id', 'guess']
    if case == 'missing-object':
        extra += ['--object', 'missing', '--upgrade-catalog']
    elif case == 'missing-channel':
        extra += ['--target-channel', 'missing', '--upgrade-catalog']
    elif case == 'dry-run':
        extra += ['--dry-run']
    code, report = run(endpoints, capsys, *extra)
    assert code == (0 if case == 'dry-run' else 1)
    assert files(root) == before and endpoints[-1].exists()
    if case == 'upgrade':
        assert '--upgrade-catalog' in report['error']
    if case == 'dry-run':
        assert report['candidate']['dry_run']


def test_existing_output_is_never_overwritten(endpoints, capsys):
    endpoints[-1].write_bytes(b'preserve existing bytes')
    code, report = run(endpoints, capsys)
    assert code == 1 and 'already exists' in report['error']
    assert endpoints[-1].read_bytes() == b'preserve existing bytes'


def test_renderer_is_shared_t133_function(endpoints, monkeypatch, capsys):
    original = gaussian_input.render_input
    calls = []
    def observe(route, titles, sections):
        calls.append((route, titles, sections))
        return original(route, titles, sections)
    monkeypatch.setattr(gaussian_input, 'render_input', observe)
    assert run(endpoints, capsys)[0] == 0
    assert len(calls) == 1 and len(calls[0][1]) == len(calls[0][2]) == 2


def test_registered_subset_without_override_and_plain_report(endpoints, capsys):
    root = endpoints[0]
    catalog.change(root, 'object', id='synthetic-object', name='Synthetic SN2')
    catalog.change(root, 'channel', object='synthetic-object', id='fictional-channel',
                   name='Synthetic channel', definition='Test only', upgrade_catalog=True)
    args = command(endpoints, '--align-atoms', '4-6', '--register-candidate',
                   '--object', 'synthetic-object', '--candidate-id', 'guess',
                   '--target-channel', 'fictional-channel')
    args.remove('--json')
    assert cli.main(args) == 0
    text = capsys.readouterr().out
    assert 'SHA-256' in text and 'all atoms' in text and 'QST2 draft' in text
    event = catalog.read_journal(root)[1][-1]
    assert event['target_channel'] == 'fictional-channel'
    assert event['transform']['align_atoms'] == [4, 5, 6]
    assert event['transform']['keep_mapping_reason'] is None
    assert event['transform']['skipped_better_swaps'] == []


def test_minimum_warning_in_cli_report(endpoints, capsys):
    path = endpoints[0] / 'attempts' / endpoints[1] / 'facts.json'
    write_json(path, dict(schema='ag-facts/1', opt_converged=True, n_imag=None))
    code, report = run(endpoints, capsys)
    assert code == 0 and 'n_imag unknown' in report['warnings'][0]


def test_core_xtb_charge_and_spin_from_manifest(endpoints):
    root, r, *_ = endpoints
    path = root / 'attempts' / r / 'manifest.json'
    manifest = json.loads(path.read_text())
    manifest['template'] = 'xtb'
    manifest['science'] = {}
    manifest['template_params'] = {'--chrg': '-1', '--uhf': '0', '--opt': None}
    write_json(path, manifest)
    assert qst.endpoint(root, r)[1] == dict(charge=-1, multiplicity=1)
