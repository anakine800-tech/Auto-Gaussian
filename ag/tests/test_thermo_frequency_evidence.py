"""Frequency acceptance checks; synthetic evidence only, no live calculations."""
import json

import pytest

from ag._profile_sources import DEFAULT_SETTINGS, load_species
from ag.thermo import _frequency_evidence, calculate_thermo
from test_facts import attempt
from test_profile import source


@pytest.mark.parametrize('consumer', ['thermo', 'profile'])
@pytest.mark.parametrize('fixture', ['water_opt_freq.log', 'butane_anti_freq.log'])
def test_zero_imaginary_modes_do_not_override_failed_frequency_convergence(
        tmp_path, consumer, fixture):
    # Water is Opt+Freq; butane is a standalone Freq job.
    directory = attempt(tmp_path, fixture=fixture)
    log = directory / 'outputs/input.log'
    text = log.read_text()
    prefix, table = text.rsplit('         Item               Value     Threshold  Converged?', 1)
    text = prefix + '         Item               Value     Threshold  Converged?' + table.replace('YES', 'NO', 1)
    log.write_text(text)
    with pytest.raises(ValueError, match='freq_step_converged.*freq_step_convergence=.*maximum_force'):
        if consumer == 'thermo':
            calculate_thermo([directory])
        else:
            load_species('water', {'attempts': [{'attempt_id': 'water'}],
                                  'single_conformer_reason': 'synthetic rigid water'},
                         tmp_path, tmp_path / 'analyses', DEFAULT_SETTINGS)
    assert not (directory / 'facts.json').exists()


@pytest.mark.parametrize('field,missing', [
    ('freq_step_converged', False), ('freq_step_converged', True),
    ('vibrational_modes_complete', False), ('vibrational_modes_complete', True),
])
def test_cached_profile_requires_frequency_evidence(tmp_path, field, missing):
    # source() explicitly uses standalone Freq, without an Opt keyword.
    spec = source(tmp_path, 'water', 0)
    path = tmp_path / 'attempts/water-0/facts.json'
    facts = json.loads(path.read_text())
    if missing:
        del facts[field]
    else:
        facts[field] = False
        facts.update(n_vibrational_modes=2, expected_vibrational_modes=3)
    path.write_text(json.dumps(facts))
    before = path.read_bytes()
    message = 'ag facts.*--refresh' if missing else field
    with pytest.raises(ValueError, match=message):
        load_species('water', spec, tmp_path, tmp_path / 'analyses', DEFAULT_SETTINGS)
    assert path.read_bytes() == before


@pytest.mark.parametrize('state', [False, None, 1, 'true'])
def test_frequency_flags_must_be_actual_true(state):
    facts = {'n_atoms': 3, 'freq_step_converged': True,
             'vibrational_modes_complete': state,
             'n_vibrational_modes': 2, 'expected_vibrational_modes': 3}
    with pytest.raises(ValueError, match='n_vibrational_modes=2, expected_vibrational_modes=3'):
        _frequency_evidence(facts, 'water')


def test_monatomic_exemption_only_applies_to_mode_completeness():
    facts = {'n_atoms': 1, 'freq_step_converged': True}
    assert '单原子无振动模式' in _frequency_evidence(facts, 'atom')['note']
    facts['freq_step_converged'] = None
    with pytest.raises(ValueError, match='freq_step_converged is True'):
        _frequency_evidence(facts, 'atom')
