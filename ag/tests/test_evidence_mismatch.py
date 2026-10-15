"""T45: deliberately spliced synthetic evidence, through current local APIs.

Legacy inspiration only: archive/tests/v3/result/test_service.py and
archive/tests/v31/conformer/test_thermochemistry_readonly.py. No legacy imports.
Cross-job frequency borrowing is already covered by test_gaussian_sections.py::
test_frequency_truncated_never_uses_partial_results and
test_extra_frequency_job_does_not_reuse_completed_frequency.
"""
from datetime import datetime, timezone
from hashlib import sha256
import json

import pytest

from ag import cli, review
from ag import _review_manifest as inventory
from ag.facts import build_facts
from ag.thermo import calculate_thermo
from test_facts import attempt
from test_profile import dump
from test_thermo import sp_input


def peroxide(tmp_path, name='peroxide', *, twisted=False):
    """Invented HOOH geometries, energies and modes; no real calculation log."""
    directory = attempt(tmp_path, name, fixture=None)
    last_h = '1.4 0.0 1.0' if twisted else '1.4 1.0 0.0'
    text = f""" Entering Gaussian System
 Gaussian, Inc.
 Gaussian 16, Revision A.03,
 ------------------------------
 #p HF/3-21G Freq
 ------------------------------
 Synthetic HOOH parser fixture; invented values.
 Charge = 0 Multiplicity = 1
 NAtoms=    4
 Input orientation:
 ---------------------------------------------------------------------
 Center     Atomic      Atomic             Coordinates (Angstroms)
 Number     Number       Type             X           Y           Z
 ---------------------------------------------------------------------
      1          8           0        0.0 0.0 0.0
      2          8           0        1.4 0.0 0.0
      3          1           0        0.0 1.0 0.0
      4          1           0        {last_h}
 ---------------------------------------------------------------------
 SCF Done:  E(RHF) =  -150.0000000000     A.U. after    1 cycles
 Harmonic frequencies (cm**-1)
                      1                      2                      3
                      A                      A                      A
 Frequencies --   200.0000               400.0000               800.0000
                      4                      5                      6
                      A                      A                      A
 Frequencies --  1000.0000              3000.0000              3200.0000

 - Thermochemistry -
 Temperature   298.150 Kelvin.  Pressure   1.00000 Atm.
 Molecular mass:    34.00000 amu.
 Rotational symmetry number  1.0000
 Rotational constants (GHZ):    100.00000     20.00000     18.00000
 Rotational temperatures (Kelvin)      5.00000     1.00000     0.90000
 Zero-point correction=                           0.020000 (Hartree/Particle)
 Sum of electronic and thermal Energies=              -149.975000
 Sum of electronic and thermal Enthalpies=            -149.974000
 Sum of electronic and thermal Free Energies=          -150.010000
 Normal termination of Gaussian
"""
    (directory / 'outputs/input.log').write_text(text)
    return directory


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(cli, 'load_config', lambda **kw: pytest.fail('must not load real configuration'))
    monkeypatch.setattr('ag.transport.SSHTransport', lambda *a, **kw: pytest.fail('must not connect'))


def test_sp_frequency_conformer_mismatch_is_rejected(tmp_path, capsys):
    # Prevent another conformer's SP input from borrowing this frequency correction.
    frequency = peroxide(tmp_path)
    other = peroxide(tmp_path, 'twisted', twisted=True)
    sp = attempt(tmp_path, 'sp', fixture=None)
    log = (other / 'outputs/input.log').read_text().split(' Harmonic frequencies')[0]
    (sp / 'outputs/input.log').write_text(log.replace(' Freq', ' SP') +
                                       ' Normal termination of Gaussian\n')
    sp_input(sp, other)
    # Establish that the synthetic records are usable before crossing identities.
    assert calculate_thermo([other], spc={str(other): str(sp)})['rows'][0]['pairing_evidence']['rmsd_angstrom'] < 1e-10
    assert cli.main(['thermo', str(frequency), '--spc', f'{frequency}={sp}', '--json']) == 1
    assert 'SPC pairing RMSD' in capsys.readouterr().err
    assert not list((tmp_path / 'analyses').glob('*'))


@pytest.mark.parametrize('alias', [False, True])
def test_thermo_duplicate_attempt_is_rejected(tmp_path, capsys, alias):
    # Prevent one conformer being counted twice, including ID/path aliases.
    directory = peroxide(tmp_path)
    second = directory.name if alias else str(directory)
    assert cli.main(['thermo', str(directory), second, '--study', str(tmp_path), '--json']) == 1
    assert 'duplicates double-count populations' in capsys.readouterr().err
    assert not list((tmp_path / 'analyses').glob('*'))


def test_profile_duplicate_attempt_is_rejected(tmp_path, capsys):
    # Prevent duplicate attempts in a profile species from inflating its partition sum.
    directory = peroxide(tmp_path)
    path = tmp_path / 'analyses/reaction.json'
    ts = peroxide(tmp_path, 'ts')
    log = ts / 'outputs/input.log'
    log.write_text(log.read_text().replace('200.0000 ', '-200.0000 ', 1))
    (ts / 'review.md').write_text('Synthetic direction check\nprofile_review: pass\nimaginary_mode_matches: true\n')
    data = {'species': {
        'R': {'attempts': [{'attempt_id': directory.name}], 'single_conformer_reason': 'Synthetic test'},
        'TS': {'attempts': [{'attempt_id': ts.name}], 'single_conformer_reason': 'Synthetic test'}},
        'states': [{'id': 'R', 'kind': 'minimum', 'species': {'R': 1}},
                   {'id': 'TS', 'kind': 'ts', 'species': {'TS': 1}},
                   {'id': 'P', 'kind': 'minimum', 'species': {'R': 1}}], 'reference': 'R'}
    dump(path, data)
    from ag.profile import calculate_profile
    assert calculate_profile(path)['species']['R']['conformers'][0]['attempt_id'] == directory.name
    data['species']['R']['attempts'] *= 2
    dump(path, data)
    assert cli.main(['profile', str(path), '--json']) == 1
    assert 'duplicate Attempt' in json.loads(capsys.readouterr().out)['error']
    assert not list(path.parent.glob('*-profile.*'))


def test_facts_refresh_invalidates_existing_review(tmp_path, monkeypatch, capsys):
    # Prevent a review bound to old facts from silently surviving an explicit refresh.
    directory = peroxide(tmp_path / 'study')
    def local_config(*, local_only):
        assert local_only is True
        return {'local': {'studies_root': str(tmp_path)}}
    monkeypatch.setattr(cli, 'load_config', local_config)
    manifest = json.loads((directory / 'manifest.json').read_text())
    manifest.update(attempt_id=directory.name, study_id='study', science={'route': '#p HF/3-21G Freq', 'charge': 0, 'multiplicity': 1},
                    card={'name': 'synthetic', 'git_commit': 'a' * 40, 'dirty': False,
                          'content': '# Synthetic\n\n## 6. 结果判据清单\n\n- 核对结构。\n\n## 7. 常见失败与处理\n'})
    (directory / 'manifest.json').write_text(json.dumps(manifest))
    build_facts(directory)
    old = (directory / 'facts.json').read_bytes()
    review.init(directory)
    review_path = directory / 'review.md'
    review_path.write_text(review_path.read_text().replace(' |  |  |', ' | synthetic evidence | 无法判断 |'))
    original_review = review_path.read_bytes()
    assert review.check(directory)['complete'] and not review.check(directory)['stale']
    log = directory / 'outputs/input.log'
    log.write_text(log.read_text().replace('200.0000 ', '-200.0000 ', 1))
    assert cli.main(['facts', str(directory), '--refresh', '--json']) == 0
    assert json.loads(capsys.readouterr().out)['n_imag'] == 1
    assert (directory / f'facts.{sha256(old).hexdigest()[:12]}.json').read_bytes() == old
    assert cli.main(['review', 'check', directory.name, '--json']) == 1
    result = json.loads(capsys.readouterr().out)
    assert result['complete'] and result['stale']
    assert any('review 可能过期' in warning for warning in result['warnings'])
    assert review_path.read_bytes() == original_review


def test_review_manifest_tracks_changed_referenced_file(tmp_path, monkeypatch, capsys):
    # Prevent a changed referenced analysis file from retaining its signed digest.
    (tmp_path / 'analyses').mkdir()
    (tmp_path / 'study.md').write_text('[Evidence](analyses/result.json)\n')
    target = tmp_path / 'analyses/result.json'
    target.write_text('{"value": 1}\n')
    old = target.read_bytes()
    times = iter([datetime(2026, 1, 1, second=s, tzinfo=timezone.utc) for s in (0, 1)])
    class Clock:
        @staticmethod
        def now(tz):
            return next(times)
    monkeypatch.setattr(inventory, 'datetime', Clock)
    monkeypatch.setattr(inventory, 'ag_provenance', lambda: {'git_commit': 'a' * 40, 'dirty': False})
    def generate():
        assert cli.main(['review', 'manifest', '--study', str(tmp_path), '--json']) == 0
        return json.loads(capsys.readouterr().out)
    first = generate()
    first_bytes = (tmp_path / first['manifest']).read_bytes()
    target.write_text('{"value": 2}\n')
    second = generate()
    before = {entry['path']: entry for entry in first['files']}
    after = {entry['path']: entry for entry in second['files']}
    assert before.keys() == after.keys()
    assert [name for name in before if before[name] != after[name]] == ['analyses/result.json']
    assert before['analyses/result.json']['sha256'] == sha256(old).hexdigest()
    assert after['analyses/result.json']['sha256'] == sha256(target.read_bytes()).hexdigest()
    assert first['sha256'] != second['sha256']
    assert (tmp_path / first['manifest']).read_bytes() == first_bytes
