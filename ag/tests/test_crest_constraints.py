"""Offline constraint validation, bundle integrity and CLI regression checks."""
from hashlib import sha256
import json
import subprocess

import pytest

from ag import attempt, cli, confirm, crest_input, render, study, submit
from test_core import Fake, cfg


XYZ = '4\nhydrogen peroxide\nO 0 0 0\nO 1.45 0 0\nH -0.4 0.8 0\nH 1.85 0 0.8\n'
CONSTRAINTS = b'$constrain\r\n  force constant=0.5\r\n  distance: 1, 2, auto\r\n$end\r\n'


@pytest.fixture
def inputs(cfg, tmp_path):
    study.init(cfg, 'smoke')
    source = tmp_path / 'peroxide.xyz'
    source.write_text(XYZ)
    constraints = tmp_path / 'user-chosen-name.inp'
    constraints.write_bytes(CONSTRAINTS)
    return source, constraints


def prepare(cfg, inputs, **overrides):
    args = dict(study_name='smoke', template='crest', input_path=inputs[0],
                constraints=inputs[1], tier='simple', walltime='00:30:00',
                label='crest', params={'--gfn2': '', '--quick': ''})
    args.update(overrides)
    return attempt.prepare(cfg, **args)


@pytest.mark.parametrize('entry', [
    'force constant=0.5', 'force constant = 5e-1',
    'atoms: 1, 2,4', 'atoms: 1-3,4',
    'distance: 1,2,auto', 'distance: 1,2,1.45',
    'angle: 1,2,3,auto', 'angle: 1,2,3,109.5',
    'dihedral: 3,1,2,4,auto', 'dihedral: 3,1,2,4,-60',
])
def test_allowed_constraints(entry):
    crest_input.validate(f'\n$constrain\n  {entry}\n$end\n', 4)


@pytest.mark.parametrize('text', [
    '$write\n$end', '$external\n$end', '$set\n$end',
    '$constrain\n$write\n$end', '$constrain\n$external\n$end',
    '$constrain\n$set\n$end', '$constrain\n$fix\n$end',
    '$constrain\n$metadyn\n$end', '$constrain\n$constrain\n$end',
    '$constrain\n$end\n$constrain\n$end', '$constrain\n$end\n$write',
    '$constrain\n$end\n$external\n$end', '$constrain\n$end\n$set\n$end',
    '$constrain\nreference=other.xyz\n$end',
    '$constrain\ndistance: 1,2,auto; $external\n$end',
    '$constrain\nforce constant=1 $write\n$end',
    '$constrain\natoms: 1,2 # comment\n$end',
    '$constrain\ndistance: 1,2,auto\x00\n$end',
    '$constrain\ndistance: 1,2,auto\x0b$external\n$end',
    'distance: 1,2,auto', '$constrain\ndistance: 1,2,auto',
    '$end', '',
])
def test_reject_directives_and_malformed_blocks(cfg, inputs, text):
    inputs[1].write_text(text)
    with pytest.raises(ValueError):
        prepare(cfg, inputs)
    assert list((study.locate(cfg, 'smoke') / 'attempts').iterdir()) == []


@pytest.mark.parametrize('entry', [
    'atoms: 0', 'atoms: -1', 'atoms: 5', 'atoms: 1-5', 'atoms: 0-3',
    'distance: 1,5,auto', 'distance: 0,2,1.4',
    'angle: 1,2,5,auto', 'dihedral: 1,2,3,5,60',
])
def test_atom_indices_are_checked_against_xyz(cfg, inputs, entry):
    inputs[1].write_text(f'$constrain\n{entry}\n$end\n')
    with pytest.raises(ValueError, match='atom index'):
        prepare(cfg, inputs)


@pytest.mark.parametrize('entry', [
    'distance: 1,2', 'distance: 1,2,3,auto', 'angle: 1,2,auto',
    'dihedral: 1,2,3,auto', 'distance: 1.5,2,auto', 'atoms: 3-1',
    'atoms:', 'atoms: 1,', 'atoms: 1-2-3', 'atoms: all',
    'force constant=nan', 'force constant=inf', 'force constant=1e999',
    'distance: 1,2,nan', 'angle: 1,2,3,inf', 'dihedral: 1,2,3,4,1e999',
])
def test_reject_invalid_values(entry):
    with pytest.raises(ValueError):
        crest_input.validate(f'$constrain\n{entry}\n$end\n', 4)


def test_constraints_bundle_summary_and_upload(cfg, inputs, monkeypatch):
    params = {'--gfn2': '', '--quick': ''}
    m = prepare(cfg, inputs, params=params)
    assert '--cinp' not in params  # Do not alter the caller's parameter dict.
    path = attempt.find(cfg, m['attempt_id'])
    files = attempt.verified_files(cfg, path, m)
    assert set(files) == {'peroxide.xyz', 'constraints.inp', 'job.pbs'}
    assert files['constraints.inp'] == CONSTRAINTS
    record = next(r for r in m['inputs'] if r['name'] == 'constraints.inp')
    assert record == dict(name='constraints.inp', sha256=sha256(CONSTRAINTS).hexdigest(), size=len(CONSTRAINTS))
    assert attempt.bundle(files)[1] == m['bundle_sha256']
    assert attempt.bundle({k: v for k, v in files.items() if k != 'constraints.inp'})[1] != m['bundle_sha256']
    summary = attempt.summary(cfg, m)
    assert f"constraints.inp: {record['sha256']}" in summary
    assert '--cinp constraints.inp' in summary
    script = files['job.pbs'].decode()
    assert 'ag_run crest peroxide.xyz --gfn2 --quick --cinp constraints.inp -T 8 > crest.out' in script
    assert subprocess.run(['sh', '-n'], input=script, text=True).returncode == 0
    # Edits to the original source must not affect the prepared snapshot.
    inputs[1].write_text('$external\n$end\n')
    fake = Fake(cfg)
    dialogs = []
    monkeypatch.setattr(confirm, 'confirm', lambda text: dialogs.append(text) or True)
    result = submit.submit(cfg, [path.name], fake)
    assert result[0]['state'] == 'submitted'
    assert m['bundle_sha256'][:12] in dialogs[0]
    assert fake.files == files
    assert fake.operations().count('metadata') == 3


def test_no_constraints_preserves_existing_behavior(cfg, inputs):
    m = prepare(cfg, inputs, constraints=None)
    files = attempt.verified_files(cfg, attempt.find(cfg, m['attempt_id']), m)
    assert set(files) == {'peroxide.xyz', 'job.pbs'}
    assert m['template_params'] == {'--gfn2': '', '--quick': ''}
    assert m['science']['route'] == '--gfn2 --quick'
    assert files['job.pbs'].decode().endswith('ag_run crest peroxide.xyz --gfn2 --quick -T 8 > crest.out\n')
    assert 'constraints.inp' not in attempt.summary(cfg, m)


@pytest.mark.parametrize('template', ['xtb', 'gaussian'])
def test_constraints_are_crest_only(cfg, inputs, template):
    with pytest.raises(ValueError, match='only supported for the crest'):
        prepare(cfg, inputs, template=template)


@pytest.mark.parametrize('value', ['constraints.inp', 'other.inp', '../other.inp'])
def test_cinp_cannot_bypass_file_validation(cfg, inputs, value):
    with pytest.raises(ValueError, match='Use --constraints'):
        prepare(cfg, inputs, params={'--cinp': value})
    if value != 'constraints.inp':
        with pytest.raises(ValueError):
            render.parameters('crest', {'--cinp': value})


def test_constraint_mutation_during_confirmation_stops_submission(cfg, inputs, monkeypatch):
    m = prepare(cfg, inputs)
    path = attempt.find(cfg, m['attempt_id'])
    fake = Fake(cfg)

    def change_constraints(text):
        (path / 'inputs/constraints.inp').write_bytes(CONSTRAINTS.replace(b'auto', b'1.4'))
        return True

    monkeypatch.setattr(confirm, 'confirm', change_constraints)
    with pytest.raises(ValueError, match='bundle differs'):
        submit.submit(cfg, [path.name], fake)
    assert 'create_attempt' not in fake.operations()
    assert not (path / '.submit-claim').exists()


@pytest.mark.parametrize('change', ['missing', 'extra', 'undeclared', 'directive', 'index'])
def test_bundle_revalidation_rejects_inconsistent_constraints(cfg, inputs, change):
    m = prepare(cfg, inputs)
    path = attempt.find(cfg, m['attempt_id'])
    constraints = path / 'inputs/constraints.inp'
    if change == 'missing':
        constraints.unlink()
    elif change == 'extra':
        (path / 'inputs/extra.inp').write_bytes(CONSTRAINTS)
    elif change == 'undeclared':
        del m['template_params']['--cinp']
    elif change == 'directive':
        constraints.write_text('$constrain\n$external\n$end\n')
    else:
        # Even a changed scientific summary cannot authorize an out-of-range atom.
        m['science']['n_atoms'] = 100
        constraints.write_text('$constrain\ndistance: 1,5,auto\n$end\n')
    files = {p.name: p.read_bytes() for p in (path / 'inputs').iterdir()}
    m['inputs'], m['bundle_sha256'] = attempt.bundle(files)
    with pytest.raises(ValueError):
        attempt.verified_files(cfg, path, m)


@pytest.mark.parametrize('json_output', [False, True])
def test_prepare_cli_with_constraints(cfg, inputs, monkeypatch, capsys, json_output):
    monkeypatch.setattr(cli, 'load_config', lambda: cfg)
    args = ['prepare', '--study', 'smoke', '--template', 'crest', '--input', str(inputs[0]),
            '--constraints', str(inputs[1]), '--tier', 'simple', '--walltime', '00:30:00',
            '--label', 'crest', '--param=--gfn2']
    if json_output:
        args.append('--json')
    assert cli.main(args) == 0
    output = capsys.readouterr().out
    if json_output:
        m = json.loads(output)
        assert m['template_params']['--cinp'] == 'constraints.inp'
        assert 'constraints.inp' in {r['name'] for r in m['inputs']}
    else:
        assert f'constraints.inp: {sha256(CONSTRAINTS).hexdigest()}' in output
