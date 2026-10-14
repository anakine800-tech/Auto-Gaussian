"""Local source checks for profile; never changes Attempts or thermo outputs.

Formula parsing is adapted from the pure _parse_formula function in
archive/skills/auto-g16-reaction-workflow/scripts/reaction_workflow.py.
No historical workflow, gates, hashes or approval machinery is used.
"""
from collections import Counter
from importlib.metadata import version
import json
import math
from pathlib import Path
import re

from ag.geometry import read_xyz
from ag.thermo import boltzmann

DEFAULT_SETTINGS = {
    'temperature_K': 298.15, 'concentration_mol_L': 1.0, 'qs': 'grimme',
    'qh': 'head_gordon', 's_cutoff_cm1': 100.0, 'h_cutoff_cm1': 100.0,
    'frequency_scale': 1.0, 'zpe_scale': 1.0,
    'rotational_symmetry': 'from_output', 'inertia': 'global',
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def finite(value, label, positive=False):
    require(isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and (not positive or value > 0),
            f'{label}: expected a finite {"positive " if positive else ""}number')
    return float(value)


def integer(value, label, positive=False):
    require(type(value) is int and (not positive or value > 0),
            f'{label}: expected a {"positive " if positive else ""}integer')
    return value


def nonempty(value, label):
    require(isinstance(value, str) and bool(value.strip()), f'{label}: missing text')
    return value


def read_json(path):
    # Duplicate names can silently drop a species or change stoichiometry.
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, f'Duplicate JSON key: {key}')
            result[key] = value
        return result
    value = json.loads(Path(path).read_text(), object_pairs_hook=pairs)
    require(isinstance(value, dict), f'{Path(path).name}: expected a JSON object')
    return value


def parse_formula(value):
    formula = nonempty(value, 'formula')
    position, counts = 0, Counter()
    for match in re.finditer(r'([A-Z][a-z]?)(\d*)', formula):
        require(match.start() == position, f'Unsupported formula: {formula}')
        count = int(match[2] or '1')
        require(count > 0, 'Non-positive element count')
        counts[match[1]] += count
        position = match.end()
    require(position == len(formula) and counts, f'Unsupported formula: {formula}')
    return dict(counts)


def local_path(study, base, value):
    path = (base / nonempty(value, 'local path')).resolve()
    require(path.is_relative_to(study), 'Profile sources must be local to this study')
    require(path.exists(), f'Missing source: {value}')
    return path


def protocol(route):
    """Conservative Gaussian route extraction; ambiguous/custom protocols fail.

    Do not guess Gen/GenECP contents or SCRF=Read dielectric/basis data. Job
    keywords (Opt/Freq/SP) do not distinguish the electronic method layers.
    """
    route = nonempty(route, 'Gaussian route').lower()
    route = re.sub(r'\s*([=,/])\s*', r'\1', route)
    # Preserve whitespace outside parentheses: dropping it joins a basis like
    # 6-31+G(d) to the following Opt/Freq keyword and falsely changes protocol.
    route = re.sub(r'\(\s*', '(', route)
    route = re.sub(r'\s*\)', ')', route)
    pairs = re.findall(r'(?<!\S)([a-z0-9+_()\-]+)/([^\s]+)', route)
    require(len(pairs) == 1, 'Expected one explicit method/basis in Gaussian route')
    method, basis = pairs[0]
    require(basis not in {'gen', 'genecp', 'chkbasis'} and 'extrabasis' not in route
            and 'pseudo' not in route and 'iop' not in route,
            'Custom basis/ECP/IOp protocol is not supported by profile')
    dispersion = re.findall(r'\b(?:empiricaldispersion|em)=(\([^)]*\)|[^\s]+)', route)
    require(len(dispersion) <= 1, 'Ambiguous dispersion settings')
    model, solvent = 'none', 'none'
    scrf = re.findall(r'\bscrf(?:=)?(\([^)]*\)|[^\s]*)', route)
    require(len(scrf) <= 1, 'Ambiguous solvent settings')
    if scrf:
        options = scrf[0].strip('()').split(',')
        models = [x for x in options if x in {'smd', 'pcm', 'iefpcm', 'cpcm', 'dipole', 'ipcm', 'scipcm'}]
        solvents = [x.split('=', 1)[1] for x in options if x.startswith('solvent=')]
        require(len(models) == len(solvents) == 1 and len(options) == 2,
                'SCRF needs explicit model and solvent; custom/read options are unsupported')
        model, solvent = models[0], solvents[0]
    return {'method': method, 'basis': basis,
            'dispersion': dispersion[0] if dispersion else 'method_default',
            'solvent_model': model, 'solvent': solvent}


def settings_checked(settings):
    require(isinstance(settings, dict) and set(settings) == set(DEFAULT_SETTINGS),
            'Incomplete or unsupported thermo settings')
    for key in ('temperature_K', 'concentration_mol_L', 's_cutoff_cm1',
                'h_cutoff_cm1', 'frequency_scale', 'zpe_scale'):
        finite(settings[key], key, positive=True)
    require(settings['qs'] in {'grimme', 'truhlar'} and settings['qh'] == 'head_gordon'
            and settings['rotational_symmetry'] == 'from_output'
            and settings['inertia'] == 'global', 'Unsupported low-frequency/symmetry treatment')
    return settings


def attempt_facts(study, attempt_id, *, cached):
    require(isinstance(attempt_id, str) and re.fullmatch(r'[A-Za-z0-9_-]+', attempt_id),
            'Expected a local Attempt ID')
    directory = local_path(study, study / 'attempts', attempt_id)
    if cached:
        facts = read_json(directory / 'facts.json')
        geometry = local_path(study, directory, facts.get('final_geometry'))
        frames = read_xyz(geometry)
        require(len(frames) == 1, f'{attempt_id}: expected one final geometry')
        elements = Counter(frames[0].symbols)
    else:
        from ag._parse_outputs import parse_gaussian
        from ag.facts import gaussian_log
        facts, geometry = parse_gaussian(gaussian_log(directory), directory / 'outputs' / 'job.pbs.out')
        require(geometry is not None, f'{attempt_id}: missing final geometry')
        elements = Counter(line.split()[0] for line in geometry.splitlines()[2:] if line.strip())
    require(facts.get('termination') == 'normal', f'{attempt_id}: non-normal termination')
    require(facts.get('n_atoms') == sum(elements.values()), f'{attempt_id}: atom count mismatch')
    integer(facts.get('charge'), f'{attempt_id} charge')
    integer(facts.get('multiplicity'), f'{attempt_id} multiplicity', positive=True)
    return directory, facts, dict(elements), protocol(facts.get('route'))


def check_review(directory):
    review = (directory / 'review.md').read_text()
    # The existing prose review has no machine-readable verdict. These two
    # explicit result lines avoid interpreting a negated sentence as a pass.
    require(re.findall(r'^profile_review:\s*(\S+)\s*$', review, re.M) == ['pass']
            and re.findall(r'^imaginary_mode_matches:\s*(\S+)\s*$', review, re.M) == ['true'],
            f'{directory.name}: TS review must pass and confirm imaginary-mode direction')


def load_species(name, spec, study, analyses, direct_settings):
    require(isinstance(spec, dict), f'{name}: expected species object')
    require(set(spec) <= {'thermo', 'attempts', 'single_conformer_reason', 'formula', 'charge'},
            f'{name}: unknown species field')
    require(('thermo' in spec) != ('attempts' in spec), f'{name}: choose thermo or attempts')
    cached = 'thermo' in spec
    if cached:
        source = local_path(study, analyses, spec['thermo'])
        data = read_json(source)
        require(data.get('schema') == 'ag-thermo/1' and data.get('goodvibes_version') == '4.3.0'
                and data.get('units', {}).get('energy') == 'Hartree', f'{name}: expected ag thermo output')
        settings = settings_checked(data.get('settings'))
        rows = data.get('rows')
        require(isinstance(rows, list) and rows, f'{name}: empty thermo ensemble')
    else:
        settings = settings_checked(dict(direct_settings))
        rows = spec['attempts']
        require(isinstance(rows, list) and rows, f'{name}: empty Attempt ensemble')
        from goodvibes.thermo import ThermoOptions, calc_bbe
        from ag.facts import gaussian_log
        require(version('goodvibes') == '4.3.0', 'profile requires GoodVibes 4.3.0')
        options = ThermoOptions(QS=settings['qs'], QH=True,
            s_freq_cutoff=settings['s_cutoff_cm1'], h_freq_cutoff=settings['h_cutoff_cm1'],
            temperature=settings['temperature_K'], concentration=settings['concentration_mol_L'],
            freq_scale_factor=settings['frequency_scale'], zpe_scale_factor=settings['zpe_scale'])
    if len(rows) == 1:
        nonempty(spec.get('single_conformer_reason'), f'{name}: single_conformer_reason')
    identities, protocols, energies, degeneracies, ids, program_versions = [], [], [], [], [], []
    for row in rows:
        require(isinstance(row, dict), f'{name}: each Attempt must be an object')
        aid = row.get('attempt_id')
        require(aid not in ids, f'{name}: duplicate Attempt')
        directory, facts, elements, freq_protocol = attempt_facts(study, aid, cached=cached)
        ids.append(aid)
        program_versions.append(nonempty(facts.get('program_version'), f'{aid}: program version missing; regenerate ag facts'))
        n_imag = facts.get('n_imag')
        require(type(n_imag) is int and n_imag in (0, 1), f'{aid}: n_imag must be 0 or 1')
        if n_imag == 1:
            check_review(directory)
        identities.append((elements, facts['charge'], facts['multiplicity'], n_imag))
        sp_protocol, delta = None, 0.0
        sp_id = row.get('spc_attempt_id')
        if sp_id:
            _, sp_facts, sp_elements, sp_protocol = attempt_facts(study, sp_id, cached=cached)
            program_versions.append(nonempty(sp_facts.get('program_version'), f'{sp_id}: program version missing; regenerate ag facts'))
            require((elements, facts['charge'], facts['multiplicity']) ==
                    (sp_elements, sp_facts['charge'], sp_facts['multiplicity']),
                    f'{aid}: SPC identity mismatch')
            delta = finite(sp_facts.get('energies', {}).get('scf'), 'SP energy') - finite(
                facts.get('energies', {}).get('scf'), 'frequency energy')
        protocols.append({'frequency': freq_protocol, 'single_point': sp_protocol})
        if cached:
            energy = finite(row.get('qh_G'), f'{aid}: qh_G')
        else:
            require(set(row) <= {'attempt_id', 'degeneracy', 'spc_attempt_id'}, f'{aid}: unknown Attempt field')
            result = calc_bbe.from_options(str(gaussian_log(directory)), options)
            energy = finite(getattr(result, 'qh_gibbs_free_energy', None), f'{aid}: qh_G') + delta
        energies.append(energy)
        degeneracies.append(integer(row.get('degeneracy', 1), f'{aid}: degeneracy', positive=True))
    require(all(x == identities[0] for x in identities), f'{name}: mixed conformer identities or n_imag')
    # Different revisions can change numerical energies even at the same route.
    require(len(set(program_versions)) == 1, f'{name}: inconsistent program versions within species/SPC')
    require(all(x == protocols[0] for x in protocols), f'{name}: mixed conformer protocols')
    _, _, ensemble = boltzmann(energies, degeneracies, settings['temperature_K'])
    if cached:
        supplied = finite(data.get('ensemble_G'), f'{name}: ensemble_G')
        require(math.isclose(ensemble, supplied, rel_tol=0, abs_tol=1e-9),
                f'{name}: ensemble_G disagrees with conformer partition sum')
        ensemble = supplied
    elements, charge, multiplicity, n_imag = identities[0]
    if 'formula' in spec:
        require(parse_formula(spec['formula']) == elements, f'{name}: declared formula differs from geometry')
    if 'charge' in spec:
        require(integer(spec['charge'], 'declared charge') == charge, f'{name}: declared charge mismatch')
    return {'ensemble_G_hartree': ensemble, 'elements': elements, 'charge': charge,
            'multiplicity': multiplicity, 'n_imag': n_imag, 'settings': settings,
            'protocol': protocols[0], 'attempts': ids, 'program_version': program_versions[0],
            'single_conformer_reason': spec.get('single_conformer_reason')}
