"""T133: synthetic peroxide scans, local files/catalog only, never a calculation."""
from hashlib import sha256
import json

import pytest

from ag import attempt, catalog, cli, gaussian_input
from ag.facts import build_facts
from ag.geometry import read_xyz, xyz_text
from test_catalog import files, make_attempt, write_json
from test_scan import (ENERGIES, GEOMETRY, GRID_ORDERS, definition, frame_at,
                       gaussian_log, grid_definition, grid_log, xtb_stdout)

ROUTE = '#p B3LYP/6-31G(d) Opt=(TS,CalcFC,NoEigenTest) Freq'


def make_scan(tmp_path, program='xtb', *, grid=False):
    root = tmp_path / 'scan-smoke'
    (root / 'attempts').mkdir(parents=True)
    (root / 'study.md').write_text('# Synthetic peroxide validation\n')
    identity = make_attempt(root, '001-scan', template=program, geometry=GEOMETRY,
                            charge=0, multiplicity=1,
                            scan=grid_definition() if grid else definition())
    path = root / 'attempts' / identity
    outputs = path / 'outputs'
    outputs.mkdir()
    if program == 'xtb':
        (outputs / 'xtbscan.log').write_text(xyz_text([frame_at(i, e) for i, e in enumerate(ENERGIES)]))
        (outputs / 'xtb.out').write_text(xtb_stdout([True] * len(ENERGIES)) + 'normal termination of xtb\n')
        (path / 'inputs').mkdir()
        data = xyz_text([frame_at(0)]).encode()
        (path / 'inputs/input.xyz').write_bytes(data)
        manifest = attempt.read_manifest(path)
        manifest['inputs'] = [dict(name='input.xyz', size=len(data), sha256=sha256(data).hexdigest())]
        manifest['template_params'] = {'--chrg': '0', '--uhf': '0'}
        # Exercise xTB parameter conversion, without a science-state fallback.
        manifest['science'].pop('charge')
        manifest['science'].pop('multiplicity')
        write_json(path / 'manifest.json', manifest)
    else:
        (outputs / 'peroxide.log').write_text(grid_log(GRID_ORDERS[2]) if grid else
                                             gaussian_log(ENERGIES, [True] * len(ENERGIES)))
    # Existing placeholder facts in make_attempt are not scan evidence.
    (path / 'facts.json').unlink()
    build_facts(path)
    return root, path


@pytest.fixture(autouse=True)
def no_remote_or_prepare(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('scan-peak must not prepare, load credentials or contact a cluster')
    from ag.transport import SSHTransport
    monkeypatch.setattr(SSHTransport, '__init__', forbidden)
    monkeypatch.setattr(cli, 'load_config', forbidden)
    monkeypatch.setattr(catalog, 'load_config', forbidden)
    monkeypatch.setattr(attempt, 'prepare', forbidden)


def command(path, *, stem='guess', route=ROUTE):
    return ['scan-peak', str(path), '--out', str(path.parent.parent / (stem + '.xyz')),
            '--gaussian-ts', str(path.parent.parent / (stem + '.gjf')), '--route', route, '--json']


def candidate_options(*extra):
    return ['--register-candidate', '--object', 'peroxide', '--candidate-id', 'peak-a', *extra]


def object_entry(root, *, channel=False):
    catalog.change(root, 'object', id='peroxide', name='Synthetic peroxide')
    if channel:
        catalog.change(root, 'channel', object='peroxide', id='a', name='A',
                       definition='Synthetic approach', upgrade_catalog=True)


@pytest.mark.parametrize('program', ['gaussian', 'xtb'])
def test_default_peak_draft_manifest_and_unchanged_evidence(tmp_path, capsys, program):
    root, path = make_scan(tmp_path, program)
    before = files(path)
    assert cli.main(command(path)) == 0
    report = json.loads(capsys.readouterr().out)
    body = (root / 'guess.gjf').read_bytes()
    info = gaussian_input.validate('%nprocshared=1\n%mem=1GB\n' + body.decode(), 1, 2)
    assert report['peak']['point'] == 4
    assert report['gaussian_ts'] == dict(path=str(root / 'guess.gjf'), route=ROUTE, charge=0, multiplicity=1,
        title=f'TS guess from scan {path.name} point 4', sha256=sha256(body).hexdigest())
    assert body.startswith(b'#p ') and body.endswith(b'\n\n') and b'%' not in body
    assert info['geometry'].splitlines() == (root / 'guess.xyz').read_text().splitlines()[2:]
    assert read_xyz(root / 'guess.xyz')[0].coordinates == read_xyz(path / 'scan_points.xyz')[3].coordinates
    assert files(path) == before and not (root / 'catalog').exists() and 'candidate' not in report


def test_charged_xtb_uhf_and_custom_title(tmp_path, capsys):
    root, path = make_scan(tmp_path)
    manifest = attempt.read_manifest(path)
    manifest['template_params'] = {'--chrg': '-1', '--uhf': '1'}
    write_json(path / 'manifest.json', manifest)
    assert cli.main(command(path) + ['--title', 'Reviewed synthetic guess']) == 0
    info = json.loads(capsys.readouterr().out)['gaussian_ts']
    assert (info['charge'], info['multiplicity'], info['title']) == (-1, 2, 'Reviewed synthetic guess')
    assert '\n-1 2\n' in (root / 'guess.gjf').read_text()


@pytest.mark.parametrize('field', ['charge', 'multiplicity'])
@pytest.mark.parametrize('program', ['gaussian', 'xtb'])
def test_missing_manifest_state_has_no_defaults(tmp_path, capsys, field, program):
    root, path = make_scan(tmp_path, program)
    manifest = attempt.read_manifest(path)
    if program == 'gaussian':
        manifest['science'].pop(field)
    else:
        manifest['template_params'].pop('--chrg' if field == 'charge' else '--uhf')
    write_json(path / 'manifest.json', manifest)
    assert cli.main(command(path)) == 1
    assert field in json.loads(capsys.readouterr().out)['error']
    assert not (root / 'guess.gjf').exists() and not (root / 'guess.xyz').exists()


@pytest.mark.parametrize('damage,error', [('parity', 'incompatible parity'), ('conflict', 'differs from science')])
def test_bad_electronic_state_refused(tmp_path, capsys, damage, error):
    root, path = make_scan(tmp_path)
    manifest = attempt.read_manifest(path)
    if damage == 'parity':
        manifest['template_params']['--uhf'] = '1'
    else:
        manifest['science']['charge'] = 1
    write_json(path / 'manifest.json', manifest)
    assert cli.main(command(path)) == 1
    assert error in json.loads(capsys.readouterr().out)['error']
    assert not (root / 'guess.gjf').exists() and not (root / 'guess.xyz').exists()


@pytest.mark.parametrize('route,error', [('# HF/STO-3G Opt', 'requires Opt=TS'),
    ('# HF/STO-3G Opt=(TS,ModRedundant)', 'scan/freeze'),
    ('# HF/STO-3G Opt=(TS,RCFC)', 'prepare --parent-chk'),
    ('# HF/STO-3G Opt=(TS,ReadFC)', 'prepare --parent-chk'),
    ('# HF/STO-3G Opt=TS Geom=AllCheck', 'Geom=Check'),
    ('# HF/STO-3G Opt=TS External=program', 'External'),
])
def test_invalid_routes_do_not_export(tmp_path, capsys, route, error):
    root, path = make_scan(tmp_path)
    assert cli.main(command(path, route=route)) == 1
    assert error in json.loads(capsys.readouterr().out)['error']
    assert not (root / 'guess.gjf').exists() and not (root / 'guess.xyz').exists()


@pytest.mark.parametrize('kind', ['gjf', 'xyz', 'symlink', 'same'])
def test_output_collisions_never_overwrite(tmp_path, capsys, kind):
    root, path = make_scan(tmp_path)
    args = command(path)
    if kind == 'same':
        args[args.index('--gaussian-ts') + 1] = str(root / 'guess.xyz')
    elif kind == 'symlink':
        (root / 'guess.gjf').symlink_to(root / 'absent')
    else:
        (root / ('guess.' + kind)).write_bytes(b'keep these bytes')
    assert cli.main(args) == 1
    error = json.loads(capsys.readouterr().out)['error']
    assert ('different new files' if kind == 'same' else 'already exists') in error
    if kind in ('gjf', 'xyz'):
        assert (root / ('guess.' + kind)).read_bytes() == b'keep these bytes'
    assert not (root / 'absent').exists()


@pytest.mark.parametrize('explicit', [False, True])
def test_registration_upgrade_hash_and_ledger(tmp_path, capsys, explicit):
    root, path = make_scan(tmp_path)
    object_entry(root)
    old = (root / 'catalog/journal.jsonl').read_bytes()
    args = command(path) + candidate_options('--upgrade-catalog')
    if explicit:
        args += ['--point', '4']
    assert cli.main(args) == 0
    report = json.loads(capsys.readouterr().out)
    event = report['candidate']['events'][0]
    assert event['origin'] == 'scan' and event['parent'] == dict(attempt=path.name, file=None)
    data = (root / 'guess.xyz').read_bytes()
    assert event['sha256'] == sha256(data).hexdigest()
    assert (root / event['file']).read_bytes() == data and (root / event['file']).stat().st_mode & 0o222 == 0
    assert (root / 'catalog/journal.jsonl').read_bytes().startswith(old)
    transform = event['transform']
    assert set(transform) == {'type', 'point', 'coordinate_value', 'energy_hartree',
        'relative_energy_kcal_mol', 'neighbors', 'scan_points_sha256', 'selection', 'warnings', 'path_diagnostics'}
    assert transform['path_diagnostics'] == report['path_diagnostics']
    assert transform['type'] == 'scan_peak' and transform['point'] == 4
    assert transform['coordinate_value'] == report['peak']['coordinate_value']
    assert transform['energy_hartree'] == report['peak']['energy_hartree']
    assert transform['relative_energy_kcal_mol'] == report['local_maxima'][0]['relative_energy_kcal_mol']
    assert transform['neighbors'] == report['neighbors_before'] + report['neighbors_after']
    assert transform['warnings'] == report['warnings']
    assert transform['selection'] == ('explicit_point' if explicit else 'default_highest')
    assert transform['scan_points_sha256'] == sha256((path / 'scan_points.xyz').read_bytes()).hexdigest()
    assert cli.main(['catalog', 'ledger', str(root), '--object', 'peroxide', '--json']) == 0
    assert json.loads(capsys.readouterr().out)['unassigned'][0]['id'] == 'peak-a'


@pytest.mark.parametrize('failure,error', [('upgrade', '--upgrade-catalog'), ('object', 'Unknown object'),
                                         ('channel', 'Unknown channel'), ('duplicate', 'already exists')])
def test_registration_failure_preserves_exports_and_catalog(tmp_path, capsys, failure, error):
    root, path = make_scan(tmp_path)
    if failure != 'object':
        object_entry(root)
    options = candidate_options()
    if failure != 'upgrade':
        options += ['--upgrade-catalog']
    if failure == 'channel':
        options += ['--target-channel', 'missing']
    if failure == 'duplicate':
        assert cli.main(command(path, stem='first') + options) == 0
        capsys.readouterr()
    before = files(root / 'catalog')
    assert cli.main(command(path) + options) == 1
    report = json.loads(capsys.readouterr().out)
    assert error in report['candidate']['error'] and report['exit_code'] == 1
    assert 'exported files retained; no retry' in report['candidate']['error']
    assert (root / 'guess.xyz').exists() and (root / 'guess.gjf').exists()
    assert files(root / 'catalog') == before


@pytest.mark.parametrize('upgraded', [False, True])
def test_registration_dry_run_only_writes_exports(tmp_path, capsys, upgraded):
    root, path = make_scan(tmp_path)
    object_entry(root, channel=upgraded)
    before = files(root / 'catalog')
    options = candidate_options('--dry-run')
    if upgraded:
        options += ['--target-channel', 'a']
    assert cli.main(command(path) + options) == 0
    report = json.loads(capsys.readouterr().out)
    assert report['candidate']['dry_run'] is True
    assert files(root / 'catalog') == before and not (root / 'catalog/candidates').exists()
    assert (root / 'guess.xyz').exists() and (root / 'guess.gjf').exists()
    assert report['candidate']['events'][0]['target_channel'] == ('a' if upgraded else None)


def test_2d_still_requires_explicit_point_and_records_coordinates(tmp_path, capsys):
    root, path = make_scan(tmp_path, 'gaussian', grid=True)
    object_entry(root, channel=True)
    assert cli.main(command(path)) == 1
    assert 'requires --point i,j' in json.loads(capsys.readouterr().out)['error']
    assert not (root / 'guess.xyz').exists() and not (root / 'guess.gjf').exists()
    assert cli.main(command(path) + ['--point', '2,2'] + candidate_options('--target-channel', 'a')) == 0
    report = json.loads(capsys.readouterr().out)
    transform = report['candidate']['events'][0]['transform']
    assert transform['point'] == [2, 2] and transform['selection'] == 'explicit_point'
    assert transform['coordinate_value'] == report['peak']['coordinate_values']
    assert len(transform['neighbors']) == 4 and report['gaussian_ts']['title'].endswith('point 2,2')
    assert cli.main(['catalog', 'ledger', str(root), '--object', 'peroxide', '--channel', 'a', '--json']) == 0
    assert json.loads(capsys.readouterr().out)['channels'][0]['candidates'][0]['id'] == 'peak-a'


def test_in_memory_registration_matches_t131_file_path(tmp_path, monkeypatch):
    root, path = make_scan(tmp_path)
    object_entry(root)
    source = root / 'peak.xyz'
    source.write_text(xyz_text([frame_at(3)]))
    transform = {'type': 'scan_peak', 'point': 4}
    definition_file = root / 'transform.json'
    write_json(definition_file, transform)
    monkeypatch.setattr(catalog, 'now', lambda: '2026-01-01T00:00:00+00:00')
    expected = catalog.change(root, 'candidate', object='peroxide', id='peak-a', xyz=str(source),
                             origin='scan', parent_attempt=path.name, transform_json=str(definition_file), dry_run=True)
    actual = catalog.register_candidate(root, object='peroxide', id='peak-a', xyz_bytes=source.read_bytes(),
                                        source=str(source), origin='scan', parent_attempt=path.name,
                                        transform=transform, dry_run=True)
    assert actual == expected


@pytest.mark.parametrize('options,error', [
    (['--gaussian-ts', 'new.gjf'], 'requires --route'),
    (['--route', ROUTE], 'require --gaussian-ts'),
    (['--title', 'title'], 'require --gaussian-ts'),
    (['--register-candidate'], 'requires --object and --candidate-id'),
    (['--object', 'peroxide'], 'require --register-candidate'),
    (['--candidate-id', 'peak-a'], 'require --register-candidate'),
    (['--target-channel', 'a'], 'require --register-candidate'),
    (['--dry-run'], 'require --register-candidate'),
    (['--upgrade-catalog'], 'require --register-candidate'),
])
def test_option_dependencies_fail_before_output(tmp_path, capsys, options, error):
    root, path = make_scan(tmp_path)
    assert cli.main(['scan-peak', str(path), '--out', str(root / 'guess.xyz'), '--json', *options]) == 1
    assert error in json.loads(capsys.readouterr().out)['error']
    assert not (root / 'guess.xyz').exists() and not (root / 'catalog').exists()


def test_registration_can_accompany_xyz_only(tmp_path, capsys):
    root, path = make_scan(tmp_path)
    object_entry(root)
    assert cli.main(['scan-peak', str(path), '--out', str(root / 'guess.xyz'),
                     *candidate_options('--upgrade-catalog')]) == 0
    assert 'candidate' in capsys.readouterr().out and not (root / 'guess.gjf').exists()
