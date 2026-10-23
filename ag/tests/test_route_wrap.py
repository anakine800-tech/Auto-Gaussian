"""T99 route/termination regressions; all logs below are synthetic water snippets."""
import pytest

from ag import __version__
from ag._parse_outputs import _route_has, parse_gaussian

TABLE = '''         Item               Value     Threshold  Converged?
 Maximum Force            0.000010     0.000450     YES
 RMS     Force            0.000002     0.000300     YES
 Maximum Displacement     0.000100     0.001800     YES
 RMS     Displacement     0.000050     0.001200     YES
'''
END = ' Normal termination of Gaussian\n'
FREQUENCIES = ''' Harmonic frequencies (cm**-1), IR intensities (KM/Mole)
 Frequencies --   1000.0  1500.0  3000.0

'''


def section(route, *, step=None, body='', ending=END, explicit=False):
    header = (' --Link1--\nGaussian, Inc.\n' if explicit else
              f' Link1: Proceeding to internal job step number {step}.\n' if step else
              ' Entering Gaussian System\nGaussian, Inc.\n')
    return (header + ' --------------------\n' + route + '\n --------------------\n'
            + body + ending)


def opt_freq():
    return (section(' #p HF/STO-3G Opt Fre\n q',
                    body=' Step number 1\n' + TABLE + ' Optimization completed.\n'
                         ' SCF Done: E(RHF) = -75.0 A.U.\n')
            + section(' #p HF/STO-3G Fr\n eq', step=2,
                      body=' SCF Done: E(RHF) = -75.0 A.U.\n' + FREQUENCIES + TABLE
                           + ' Zero-point correction= 0.01\n'
                           + ' Sum of electronic and thermal Energies= -74.98\n'
                           + ' Sum of electronic and thermal Enthalpies= -74.97\n'
                           + ' Sum of electronic and thermal Free Energies= -75.02\n'))


def parse(tmp_path, text):
    path = tmp_path / 'synthetic-water.log'
    path.write_text(text)
    return parse_gaussian(path)[0]


@pytest.mark.parametrize('newline', ['\n', '\r\n'])
@pytest.mark.parametrize('route,expected', [
    (' #p HF/STO-3G Fre\n q', '#p HF/STO-3G Freq'),
    (' #p HF/STO-3G Fr\n eq', '#p HF/STO-3G Freq'),
    (' #p HF/STO-3G Op\n t', '#p HF/STO-3G Opt'),
    (' #p HF/STO-3G Opt \n Freq', '#p HF/STO-3G Opt Freq'),
    (' #p HF/STO-3G Opt\n  Freq', '#p HF/STO-3G Opt Freq'),
    (' #p HF/STO-3G Op\n t Fre\n q SCF=Ti\n ght', '#p HF/STO-3G Opt Freq SCF=Tight'),
])
def test_wrapped_route_preserves_real_spaces_only(tmp_path, newline, route, expected):
    facts = parse(tmp_path, section(route).replace('\n', newline))
    assert facts['route'] == facts['job_sections'][0]['route'] == expected
    assert facts['parser_warning'] is None
    assert facts['termination'] == 'normal'
    assert facts['parser'] == {'ag_version': __version__, 'rules': 'route-join-v2'}


@pytest.mark.parametrize('explicit', [False, True])
def test_second_and_third_link1_routes(tmp_path, explicit):
    text = section(' #p HF/STO-3G Op\n t Fre\n q')
    text += section(' #p HF/STO-3G Fre\n q', step=2, explicit=explicit)
    text += section(' #p HF/STO-3G Fr\n eq', step=3, explicit=explicit)
    facts = parse(tmp_path, text)
    assert len(facts['job_sections']) == 3
    assert all(_route_has(s['route'], 'freq') for s in facts['job_sections'])
    assert _route_has(facts['job_sections'][0]['route'], 'opt')
    assert facts['termination'] == 'normal' and facts['parser_warning'] is None


@pytest.mark.parametrize('text', [
    section(' #p HF/STO-3G Opt Freq') + section(' #p HF/STO-3G Freq', step=2, ending=''),
    section(' #p HF/STO-3G Opt Freq', ending=''),
    section(' #p HF/STO-3G Opt Freq', ending=' Error termination\n'),
    section(' #p HF/STO-3G Opt Freq') + END,
    section(' #p HF/STO-3G Opt', ending='') + section(' #p HF/STO-3G Freq', step=2),
    section(' #p HF/STO-3G SP', body=' quoted Normal termination of Gaussian\n'),
])
def test_missing_error_or_surplus_endings_never_pass(tmp_path, text):
    assert parse(tmp_path, text)['termination'] != 'normal'


@pytest.mark.parametrize('text', [
    section(' #p UnknownTask'),
    'Gaussian, Inc.\n Unrecognized task body\n' + END,
    section(' #p HF/STO-3G SP') + 'Gaussian, Inc.\n Unknown task body\n' + END,
])
def test_unknown_task_warns_without_changing_complete_termination(tmp_path, text):
    facts = parse(tmp_path, text)
    assert facts['termination'] == 'normal'
    assert 'unrecognized job section' in facts['parser_warning']


def test_wrapping_does_not_change_energy_frequency_or_convergence(tmp_path):
    wrapped = opt_freq()
    flat = wrapped.replace('Fre\n q', 'Freq').replace('Fr\n eq', 'Freq')
    before, after = parse(tmp_path, flat), parse(tmp_path, wrapped)
    # Ignore line positions: adding physical route lines shifts evidence lines.
    for key in ('energies', 'n_imag', 'frequencies_low', 'opt_converged',
                'freq_step_converged', 'n_vibrational_modes', 'vibrational_modes_complete'):
        assert after[key] == before[key]
    assert after['energies']['scf'] == pytest.approx(-75.0)
    assert after['n_imag'] == 0 and after['freq_step_converged'] is True
    assert after['parser_warning'] is None


def test_thermo_passes_repaired_termination_gate_only(tmp_path, monkeypatch):
    from ag import thermo
    directory = tmp_path / 'attempts' / 'water'
    directory.mkdir(parents=True)
    (directory / 'manifest.json').write_text('{}')
    repaired = parse(tmp_path, opt_freq())
    repaired['program'] = 'gaussian'
    previous = dict(repaired, termination='incomplete')
    monkeypatch.setattr(thermo, 'parse_facts', lambda path: (previous, {}))
    with pytest.raises(ValueError, match='requires normal termination'):
        thermo.calculate_thermo([directory])
    # Stop at the very next gate: this test claims no thermochemical acceptance.
    class ReachedFrequencyGate(Exception):
        pass
    def next_gate(*args):
        raise ReachedFrequencyGate
    monkeypatch.setattr(thermo, '_frequency_evidence', next_gate)
    monkeypatch.setattr(thermo, 'parse_facts', lambda path: (repaired, {}))
    with pytest.raises(ReachedFrequencyGate):
        thermo.calculate_thermo([directory])
