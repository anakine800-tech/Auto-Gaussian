"""Hand-built geometries/vectors only; no real logs or research fixtures."""
from hashlib import sha256
import json
import os
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from ag import cli, mode_review as mr


XYZ = [[0., 0., 0.], [4., 0., 0.], [0., 3., 0.]]
VECTORS = [[[1., 0., 0.], [-1., 0., 0.], [0., 0., 0.]]]


def orientation(kind='Standard', xyz=XYZ):
    return (f' {kind} orientation:\n'
            ' ---------------------------------------------------------------------\n'
            ' Center     Atomic      Atomic             Coordinates (Angstroms)\n'
            ' Number     Number       Type             X           Y           Z\n'
            ' ---------------------------------------------------------------------\n' + ''.join(
                f'{i:7d}{1:11d}{0:12d}{x:16.6f}{y:12.6f}{z:12.6f}\n'
                for i, (x, y, z) in enumerate(xyz, 1)) +
            ' ---------------------------------------------------------------------\n')


def synthetic_log(kind='Standard', route='# freq', end=' Normal termination of Gaussian\n'):
    return (' Entering Gaussian System\n Gaussian, Inc.\n -----\n'
            f' {route}\n -----\n NAtoms=    3\n' + orientation(kind) +
            ' Harmonic frequencies (cm**-1)\n'
            '                      1\n'
            '                      A\n'
            ' Frequencies --   -100.0000\n'
            ' Red. masses --      1.0000\n'
            ' Frc consts  --      1.0000\n'
            ' IR Inten    --      1.0000\n'
            '  Atom  AN      X      Y      Z\n'
            '     1   1     1.00   0.00   0.00\n'
            '     2   1    -1.00   0.00   0.00\n'
            '     3   1     0.00   0.00   0.00\n\n' + end)


@pytest.fixture
def sections():
    if not hasattr(mr.outputs, 'gaussian_job_sections'):
        pytest.skip('T42 job-section parser not yet in this development base')


@pytest.fixture
def study(tmp_path):
    root = tmp_path / 'study'
    attempt = root / 'attempts' / 'demo-001-freq'
    (attempt / 'outputs').mkdir(parents=True)
    (root / 'analyses').mkdir()
    (attempt / 'manifest.json').write_text(json.dumps(dict(template='gaussian', inputs=[dict(name='job.gjf')])))
    (attempt / 'outputs' / 'job.log').write_text(synthetic_log())
    (attempt / 'facts.json').write_text('{"existing": true}\n')
    return root, attempt


def test_arithmetic_long_pair_ranking_and_amplitude():
    result, plus, minus = mr.displace(['H'] * 3, XYZ, [-100], VECTORS, [(1, 2), (1, 3), (3, 2)])
    pair = result['pairs'][0]
    assert pair['distance'] == 4  # deliberately beyond the legacy 3.5 A cutoff
    assert pair['plus_distance'] == pytest.approx(3.4)
    assert pair['minus_distance'] == pytest.approx(4.6)
    assert pair['distance_change_rate'] == -2
    assert pair['absolute_rate_rank'] == 1
    assert pair['shortened_sides'] == ['plus']
    assert (pair['plus_change_sign'], pair['minus_change_sign']) == (-1, 1)
    transverse = result['pairs'][1]
    assert transverse['distance_change_rate'] == 0
    assert transverse['shortened_sides'] == []
    assert transverse['plus_distance'] == pytest.approx(np.sqrt(9.09))
    assert result['pairs'][2]['distance_change_rate'] == pytest.approx(-0.8)
    assert result['pairs'][2]['absolute_rate_rank'] == 2
    for displaced in (plus, minus):
        assert np.max(np.linalg.norm(np.array(displaced) - XYZ, axis=1)) == pytest.approx(0.3)
    assert result['total_pairs'] == 3


def test_frequency_sort_sign_arbitrariness_and_scaling():
    vectors = [VECTORS[0], (-np.array(VECTORS[0]) * 7).tolist()]
    result, plus, minus = mr.displace(['H'] * 3, XYZ, [200, -100], vectors, [(2, 1)])
    assert result['source_mode_index'] == 2
    assert result['frequency'] == -100
    assert result['pairs'][0]['shortened_sides'] == ['minus']
    assert result['pairs'][0]['distance_change_rate'] == 14
    assert plus[0][0] == pytest.approx(-0.3)
    second, _, _ = mr.displace(['H'] * 3, XYZ, [200, -100], vectors, [(1, 2)], mode=2)
    assert second['frequency'] == 200


@pytest.mark.parametrize('changes', [dict(mode=0), dict(mode=2), dict(amplitude=0),
    dict(amplitude=-1), dict(amplitude=float('nan')), dict(amplitude=float('inf')),
    dict(pairs=[(0, 1)]), dict(pairs=[(1, 4)]), dict(pairs=[(2, 2)]), dict(pairs=[]),
    dict(coordinates=[[0, 0, 0]] * 3), dict(displacements=[[[0, 0, 0]] * 3]),
    dict(frequencies=[float('nan')]), dict(displacements=[[[1, 0, 0]]])])
def test_invalid_arithmetic(changes):
    values = dict(elements=['H'] * 3, coordinates=XYZ, frequencies=[-100],
                  displacements=VECTORS, pairs=[(1, 2)])
    with pytest.raises(ValueError):
        mr.displace(**(values | changes))


@pytest.mark.parametrize('pair', ['0-1', '1-1', '1--2', '1.5-2', '1,2', 'x-y'])
def test_bad_pair_syntax(pair):
    with pytest.raises(ValueError):
        mr.pair_argument(pair)


@pytest.mark.parametrize('kind,route,expected', [
    ('Standard', '# freq', 'standard'), ('Input', '# freq nosymm', 'input')])
def test_real_cclib_on_handwritten_modes(kind, route, expected):
    elements, coords, freqs, vectors, frame = mr.read_modes(synthetic_log(kind, route).encode())
    assert elements == ['H'] * 3
    assert np.array_equal(coords, XYZ)
    assert list(freqs) == [-100]
    assert np.array_equal(vectors, VECTORS)
    assert frame == expected


def test_orientation_different_input_is_not_used():
    log = synthetic_log().replace(orientation(), orientation('Input', [[9, 0, 0]] * 3) + orientation())
    _, coords, _, _, frame = mr.read_modes(log.encode())
    assert frame == 'standard'
    assert np.array_equal(coords, XYZ)


@pytest.mark.parametrize('change', ['indices', 'elements', 'stale_standard', 'duplicate_modes'])
def test_misassociated_printed_evidence_refused(change):
    log = synthetic_log()
    if change == 'indices':
        log = log.replace('     2   1    -1.00', '     1   1    -1.00')
    elif change == 'elements':
        log = log.replace('     2   1    -1.00', '     2   8    -1.00')
    elif change == 'stale_standard':
        log = log.replace(' Harmonic frequencies', orientation('Input') + ' Harmonic frequencies')
    else:
        log += log[log.index(' Harmonic frequencies'):]
    with pytest.raises(ValueError, match='numbering|orientation|cannot be matched'):
        mr.read_modes(log.encode())


def test_all_pair_ranking_includes_pairs_outside_requested_list():
    result, _, _ = mr.displace(['H'] * 3, XYZ, [-100], VECTORS, [(1, 3)])
    assert result['pairs'][0]['absolute_rate_rank'] == 3
    assert result['total_pairs'] == 3


def test_tied_rates_share_rank():
    vectors = [[[1, 0, 0]] * 3]
    result, _, _ = mr.displace(['H'] * 3, XYZ, [-100], vectors, [(1, 2), (1, 3), (2, 3)])
    assert [row['absolute_rate_rank'] for row in result['pairs']] == [1, 1, 1]


@pytest.mark.parametrize('change', ['no_frame', 'ambiguous_input', 'later_frame', 'truncated_frame', 'mismatch'])
def test_uncertain_orientation_refused(change, monkeypatch):
    log = synthetic_log()
    if change == 'no_frame':
        log = log.replace(orientation(), '')
    elif change == 'ambiguous_input':
        log = synthetic_log('Input')
    elif change == 'later_frame':
        log += orientation()
    elif change == 'truncated_frame':
        log = log.replace(' Harmonic frequencies', ' Standard orientation:\n incomplete\n Harmonic frequencies')
    elif change == 'mismatch':
        import cclib.io
        monkeypatch.setattr(cclib.io, 'ccread', lambda *a, **kw: SimpleNamespace(
            atomcoords=[[[0, 1, 0]] * 3], atomnos=[1, 1, 1], vibfreqs=[-100], vibdisps=VECTORS))
    with pytest.raises(ValueError, match='orientation|geometry|Geometry'):
        mr.read_modes(log.encode())


def test_requires_t42_without_fallback(monkeypatch):
    monkeypatch.delattr(mr.outputs, 'gaussian_job_sections', raising=False)
    with pytest.raises(ValueError, match='requires T42'):
        mr.frequency_section(synthetic_log().encode())


@pytest.mark.parametrize('ending', ['', ' Error termination\n'])
def test_reject_abnormal_frequency_section(sections, ending):
    with pytest.raises(ValueError, match='did not terminate normally'):
        mr.frequency_section(synthetic_log(end=ending).encode())


def test_opt_freq_uses_only_frequency_section(sections):
    first = ' Entering Gaussian System\n -----\n # opt freq\n -----\n' + orientation(xyz=[[9, 0, 0]] * 3)
    first += ' Normal termination of Gaussian\n'
    freq = synthetic_log().replace(' Entering Gaussian System\n Gaussian, Inc.\n',
        ' Link1:  Proceeding to internal job step number 2.\n')
    raw = (first + freq).replace('\n', '\r\n').encode()
    section, block = mr.frequency_section(raw)
    assert section['index'] == 2
    assert block == freq.replace('\n', '\r\n').encode()
    _, coords, _, _, _ = mr.read_modes(block)
    assert np.array_equal(coords, XYZ)


def test_unrecognized_tail_refused(sections):
    with pytest.raises(ValueError, match='Ambiguous'):
        mr.frequency_section((synthetic_log() + ' unexplained tail\n').encode())


def test_cli_exports_and_leaves_attempt_untouched(sections, study, monkeypatch, capsys):
    root, attempt = study
    before = {p: p.read_bytes() for p in attempt.rglob('*') if p.is_file()}
    monkeypatch.setattr(cli, 'load_config', lambda **kw: pytest.fail('local command loaded config'))
    assert cli.main(['mode-review', attempt.name, '--study', str(root), '--pair', '1-2',
                     '--out', 'analyses/check.json', '--json']) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['source']['section']['index'] == 1
    raw = (attempt / 'outputs/job.log').read_bytes()
    assert result['source']['section_sha256'] == sha256(raw).hexdigest()
    assert result['source']['log_sha256'] == sha256(raw).hexdigest()
    assert 'git_commit' in result['ag_provenance']
    assert result['ag_version']
    assert mr.NOTICE in result['note']
    for side in ('plus', 'minus'):
        xyz = root / 'analyses' / result['geometries'][side]
        assert f'Attempt {attempt.name}; mode 1;' in xyz.read_text()
        assert 'max displacement 0.3 angstrom' in xyz.read_text()
    assert before == {p: p.read_bytes() for p in attempt.rglob('*') if p.is_file()}


@pytest.mark.parametrize('suffix', ['.json', '.plus.xyz', '.minus.xyz'])
def test_existing_output_is_never_overwritten(study, suffix):
    root, attempt = study
    existing = root / 'analyses' / ('check' + suffix)
    existing.write_text('preserve')
    with pytest.raises(FileExistsError):
        mr.create(attempt.name, root, [(1, 2)], 'analyses/check.json')
    assert list((root / 'analyses').iterdir()) == [existing]
    assert existing.read_text() == 'preserve'


@pytest.mark.parametrize('path', ['../escape.json', 'attempts/report.json', 'analyses/../escape.json', 'analyses/bad.xyz'])
def test_output_must_stay_in_analyses(study, path):
    root, attempt = study
    with pytest.raises(ValueError):
        mr.create(attempt.name, root, [(1, 2)], path)


@pytest.mark.parametrize('side', ['check.json', 'check.plus.xyz', 'check.minus.xyz'])
def test_output_symlink_refused(study, side):
    root, attempt = study
    (root / 'analyses' / side).symlink_to(root / 'absent')
    with pytest.raises(ValueError, match='Symbolic'):
        mr.create(attempt.name, root, [(1, 2)], 'analyses/check.json')


def test_each_output_is_exclusively_created(sections, study, monkeypatch):
    root, attempt = study
    linked = []
    original = os.link
    def capture(source, target, **kw):
        linked.append((target.name, kw))
        return original(source, target, **kw)
    monkeypatch.setattr(os, 'link', capture)
    mr.create(attempt.name, root, [(1, 2)], 'analyses/check.json')
    assert linked == [(name, {'follow_symlinks': False}) for name in
                      ('check.json', 'check.plus.xyz', 'check.minus.xyz')]


def test_creation_race_cannot_replace_existing_bytes(sections, study, monkeypatch):
    root, attempt = study
    original = os.link
    target = root / 'analyses/check.plus.xyz'
    def race(source, destination, **kw):
        if destination == target:
            target.write_text('concurrent writer')
        return original(source, destination, **kw)
    monkeypatch.setattr(os, 'link', race)
    with pytest.raises(FileExistsError):
        mr.create(attempt.name, root, [(1, 2)], 'analyses/check.json')
    assert target.read_text() == 'concurrent writer'
    assert json.loads((root / 'analyses/check.json').read_bytes())['attempt'] == attempt.name
    assert len(list((root / 'analyses').glob('.mode-review-stage-*'))) == 3


@pytest.mark.parametrize('change', ['pair', 'frequency', 'orientation', 'program'])
def test_rejections_leave_no_outputs(sections, study, change):
    root, attempt = study
    pairs = [(1, 4)] if change == 'pair' else [(1, 2)]
    log = attempt / 'outputs/job.log'
    if change == 'frequency':
        log.write_text(synthetic_log(end=''))
    elif change == 'orientation':
        log.write_text(synthetic_log('Input'))
    elif change == 'program':
        (attempt / 'manifest.json').write_text('{"template": "xtb"}')
    with pytest.raises(ValueError):
        mr.create(attempt.name, root, pairs, 'analyses/check.json')
    assert list((root / 'analyses').iterdir()) == []
