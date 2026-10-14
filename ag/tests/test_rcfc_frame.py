"""T25: synthetic water logs and local prepare only; no research/remote data."""
import json

import pytest

from ag import attempt, state, study, submission
from ag.facts import build_facts
from ag._parse_outputs import gaussian_orientation
from test_core import INPUT, cfg


INITIAL = 'O 0 0 0\nH 0 0 1\nH 0 1 0'
INPUT_FRAME = 'O 0 0 0\nH 0 0 0.95\nH 0.92 0.2 0'
STANDARD_FRAME = 'O 0 0 0\nH 0 0 0.95\nH -0.2 0.92 0'


def orientation(kind, geometry):
    rows = []
    for i, line in enumerate(geometry.splitlines(), 1):
        element, *xyz = line.split()
        rows.append(f" {i:6d} {8 if element == 'O' else 1:10d} 0 "
                    + ' '.join(f'{float(x):12.6f}' for x in xyz))
    return (f' {kind} orientation:\n'
            ' ---------------------------------------------------------------------\n'
            ' Center     Atomic      Atomic             Coordinates (Angstroms)\n'
            ' Number     Number       Type             X           Y           Z\n'
            ' ---------------------------------------------------------------------\n'
            + '\n'.join(rows)
            + '\n ---------------------------------------------------------------------\n')


def synthetic_log(*, nosymm=False, input_only=False):
    text = (' Entering Gaussian System\n Gaussian, Inc.\n Gaussian 16, Revision A.03,\n'
            ' ------------------------------\n #p HF/STO-3G opt freq'
            + (' nosymm' if nosymm else '') +
            '\n ------------------------------\n Synthetic water orientation fixture.\n'
            ' Charge = 0 Multiplicity = 1\n NAtoms=    3\n')
    for geometry in (INITIAL, INPUT_FRAME):
        text += orientation('Input', geometry)
        if not input_only:
            text += orientation('Standard', geometry if nosymm else STANDARD_FRAME)
        text += ' SCF Done:  E(RHF) =  -75.0000000000     A.U. after    1 cycles\n'
    return text + ' Normal termination of Gaussian\n'


def make_parent(cfg, tmp_path, *, nosymm=False, input_only=False):
    study.init(cfg, 'smoke')
    source = tmp_path / 'water.gjf'
    source.write_text(INPUT.replace(' SP', ' opt freq' + (' NoSymm' if nosymm else '')))
    m = attempt.prepare(cfg, study_name='smoke', template='gaussian', input_path=source,
                        tier='simple', walltime='00:30:00', label='parent')
    path = attempt.find(cfg, m['attempt_id'])
    state.write(path, 'submitting')
    submission.record(path, m, '42.fixture')
    state.write(path, 'submitted', job_id=submission.qualified(m, '42.fixture'))
    state.write(path, 'finished')
    (path / 'outputs/water.log').write_text(synthetic_log(nosymm=nosymm, input_only=input_only))
    facts = build_facts(path)
    return path, facts


def prepare_child(cfg, tmp_path, path, geometry, route='irc=(rcfc,forward)'):
    source = tmp_path / 'child.gjf'
    source.write_text('%oldchk=parent.chk\n' + INPUT.replace(' SP', ' ' + route)
                      .replace(INITIAL, geometry))
    return attempt.prepare(
        cfg, study_name='smoke', template='gaussian', input_path=source, tier='simple',
        walltime='00:30:00', label='child',
        parents=[dict(attempt_id=path.name, relation='irc_from')],
        parent_chk=path.name + ':water.chk')


def coordinates(path):
    return '\n'.join(path.read_text().splitlines()[2:])


def test_facts_export_final_input_and_standard_frames(cfg, tmp_path):
    path, facts = make_parent(cfg, tmp_path)
    assert facts['final_input_geometry'] == 'final_input.xyz'
    assert facts['final_input_geometry_orientation'] == 'input'
    assert facts['final_geometry'] == 'final.xyz'
    assert facts['final_geometry_orientation'] == 'standard'
    assert (path / 'final_input.xyz').read_text() == gaussian_orientation(synthetic_log(), 'Input')
    assert (path / 'final.xyz').read_text() == gaussian_orientation(synthetic_log(), 'Standard')
    assert (path / 'final.xyz').read_bytes() != (path / 'final_input.xyz').read_bytes()
    originals = {name: ((path / name).read_bytes(), (path / name).stat().st_mtime_ns)
                 for name in ('final.xyz', 'final_input.xyz')}
    assert build_facts(path) == facts
    for name, (content, mtime) in originals.items():
        assert (path / name).read_bytes() == content
        assert (path / name).stat().st_mtime_ns == mtime


@pytest.mark.parametrize('name', ['final_input.xyz', 'final.xyz'])
@pytest.mark.parametrize('problem', ['different', 'symlink', 'directory'])
def test_facts_never_overwrites_geometry(cfg, tmp_path, name, problem):
    path, _ = make_parent(cfg, tmp_path)
    target = path / name
    target.unlink()
    if problem == 'different':
        target.write_text('retained review geometry\n')
    elif problem == 'symlink':
        other = tmp_path / 'retained.xyz'
        other.write_text(gaussian_orientation(synthetic_log(), 'Input' if 'input' in name else 'Standard'))
        target.symlink_to(other)
    else:
        target.mkdir()
    facts_before = (path / 'facts.json').read_bytes()
    with pytest.raises(ValueError, match=name):
        build_facts(path)
    assert (path / 'facts.json').read_bytes() == facts_before
    if problem == 'different':
        assert target.read_text() == 'retained review geometry\n'
    elif problem == 'symlink':
        assert target.is_symlink()
    else:
        assert target.is_dir()


@pytest.mark.parametrize('route', [
    'irc=(rcfc,forward)', 'IRC = (\n RCFC,Reverse)', 'opt=(ts,rcfc) freq',
    'Opt=(TS,ReadFC) Freq', 'opt=readfc', 'irc=(ReadCartesianFC,forward)',
])
def test_force_constants_require_input_frame(cfg, tmp_path, route):
    path, _ = make_parent(cfg, tmp_path)
    before = set(path.parent.iterdir())
    with pytest.raises(ValueError, match='rcfc 读到的力常数是父作业输入取向下的'):
        prepare_child(cfg, tmp_path, path, coordinates(path / 'final.xyz'), route)
    assert set(path.parent.iterdir()) == before
    m = prepare_child(cfg, tmp_path, path, coordinates(path / 'final_input.xyz'), route)
    assert m['parent_chk']['attempt_id'] == path.name


@pytest.mark.parametrize('input_only', [False, True])
@pytest.mark.parametrize('filename', ['final.xyz', 'final_input.xyz'])
def test_nosymm_either_frame(cfg, tmp_path, input_only, filename):
    path, facts = make_parent(cfg, tmp_path, nosymm=True, input_only=input_only)
    assert facts['final_geometry_orientation'] == ('input' if input_only else 'standard')
    assert (path / 'final.xyz').read_bytes() == (path / 'final_input.xyz').read_bytes()
    prepare_child(cfg, tmp_path, path, coordinates(path / filename))
    # NoSymm allows either export, not arbitrary geometry or atom reordering.
    with pytest.raises(ValueError, match='请改用 final_input.xyz'):
        prepare_child(cfg, tmp_path, path, STANDARD_FRAME)
    if filename == 'final.xyz':
        (path / 'final_input.xyz').unlink()
        prepare_child(cfg, tmp_path, path, coordinates(path / filename))


@pytest.mark.parametrize('delta,allowed', [(0.000099, True), (0.0001, True), (0.000101, False)])
def test_fixed_row_tolerance(cfg, tmp_path, delta, allowed):
    path, _ = make_parent(cfg, tmp_path)
    changed = INPUT_FRAME.replace('O 0 0 0', f'O {delta} 0 0')
    if allowed:
        prepare_child(cfg, tmp_path, path, changed)
    else:
        with pytest.raises(ValueError, match='请改用 final_input.xyz'):
            prepare_child(cfg, tmp_path, path, changed)


@pytest.mark.parametrize('geometry', [
    'H 0 0 0.95\nO 0 0 0\nH 0.92 0.2 0',
    'O 0 0 0\nH 0.92 0.2 0\nH 0 0 0.95',
    INPUT_FRAME + '\nH 1 1 1', 'O 0 0 0\nH 0 0 0.95',
    INPUT_FRAME.replace('O 0 0 0', 'O 1e999 0 0'),
])
def test_atom_mapping_and_finite_coordinates(cfg, tmp_path, geometry):
    path, _ = make_parent(cfg, tmp_path)
    with pytest.raises(ValueError):
        prepare_child(cfg, tmp_path, path, geometry)


def test_atomic_numbers_and_units(cfg, tmp_path):
    path, _ = make_parent(cfg, tmp_path)
    prepare_child(cfg, tmp_path, path, INPUT_FRAME.replace('O', '8').replace('H', '1'))
    with pytest.raises(ValueError, match='默认 Å'):
        prepare_child(cfg, tmp_path, path, INPUT_FRAME, 'irc=rcfc units=bohr')


@pytest.mark.parametrize('problem', ['missing', 'truncated', 'multiple', 'symlink'])
def test_parent_input_frame_must_be_available(cfg, tmp_path, problem):
    path, _ = make_parent(cfg, tmp_path)
    target = path / 'final_input.xyz'
    if problem == 'truncated':
        target.write_text('3\ntruncated\nO 0 0 0\n')
    elif problem == 'multiple':
        target.write_text(target.read_text() * 2)
    else:
        target.unlink()
        if problem == 'symlink':
            target.symlink_to(path / 'final.xyz')
    with pytest.raises(ValueError):
        prepare_child(cfg, tmp_path, path, INPUT_FRAME)
    # CalcFC does not consult the frame even when it is absent or unusable.
    prepare_child(cfg, tmp_path, path, STANDARD_FRAME, 'guess=read irc=(calcfc,forward)')


def test_missing_or_truncated_input_is_not_invented(cfg, tmp_path):
    path, _ = make_parent(cfg, tmp_path)
    target = path / 'outputs/water.log'
    original = target.read_text()
    (path / 'final_input.xyz').unlink()
    target.write_text(original + ' Input orientation:\n --------\n truncated\n')
    facts = build_facts(path)
    assert facts['final_input_geometry'] is None
    assert not (path / 'final_input.xyz').exists()
    assert gaussian_orientation(original.replace('Input orientation:', 'Other orientation:'), 'Input') is None
    assert json.loads((path / 'facts.json').read_text())['final_input_geometry_orientation'] is None
