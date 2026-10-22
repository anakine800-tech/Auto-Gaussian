"""GoodVibes thermochemistry and explicit finite-ensemble Boltzmann weighting."""

from datetime import datetime, timezone
from collections import Counter
from importlib.metadata import version
from hashlib import sha256
import json
import math
import re
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

from ag.facts import parse_facts, gaussian_log, resolve_attempt

HARTREE_TO_KCAL = 627.509541
R_HARTREE = 8.3144621 / (HARTREE_TO_KCAL * 4184)
SPECIES_REVIEW_NOTE = '分子式相同不等于同一物种，是否属于同一物种的构象集合仍由人审阅。'


def boltzmann(energies, degeneracies, temperature):
    """Return populations, arithmetic mean G and ensemble G in Hartree."""
    if (not energies or len(energies) != len(degeneracies)
            or not math.isfinite(temperature) or temperature <= 0
            or any(not math.isfinite(g) for g in energies)
            or any(not math.isfinite(d) or d <= 0 for d in degeneracies)):
        raise ValueError('Finite energies, positive temperature and degeneracies are required')
    minimum = min(energies)
    logs = [math.log(d) - (g-minimum)/(R_HARTREE*temperature)
            for g, d in zip(energies, degeneracies)]
    offset = max(logs)
    weights = [math.exp(w-offset) for w in logs]
    total = math.fsum(weights)
    populations = [w/total for w in weights]
    # Reuse shifted log weights: exponentiating absolute molecular G overflows.
    ensemble = minimum - R_HARTREE*temperature*(offset + math.log(total))
    return populations, math.fsum(p*g for p, g in zip(populations, energies)), ensemble


def _positive(value, name):
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f'{name} must be positive and finite')


def _mappings(values, cast):
    result = {}
    for value in values:
        try:
            key, item = value.split('=', 1)
            if not key or not item or key in result:
                raise ValueError
            result[key] = cast(item)
        except ValueError as exc:
            raise ValueError(f'Expected unique attempt=value mapping: {value}') from exc
    return result


def _geometry_sha256(frame):
    """Hash ordered elements and unaligned Å coordinates, independent of XYZ comments."""
    payload = {'elements': frame.symbols, 'coordinates_angstrom': frame.coordinates}
    return sha256(json.dumps(payload, sort_keys=True, separators=(',', ':'),
                             allow_nan=False).encode('utf-8')).hexdigest()


def _frequency_evidence(facts, attempt_id):
    """Reject unverified frequency thermochemistry, including standalone Freq.

    Normal termination and zero imaginary modes do not establish stationarity
    or a complete vibrational spectrum. Atomic species only waive the latter.
    """
    monatomic = facts.get('n_atoms') == 1
    required = ['freq_step_converged']
    if not monatomic:
        required.append('vibrational_modes_complete')
    missing = [key for key in required if key not in facts]
    if missing:
        raise ValueError(f'{attempt_id}: missing frequency evidence {", ".join(missing)}; '
                         'run ag facts <attempt> --refresh after reviewing the original log')
    if facts['freq_step_converged'] is not True:
        table = json.dumps(facts.get('freq_step_convergence'), ensure_ascii=False)
        raise ValueError(f'{attempt_id}: requires freq_step_converged is True; '
                         f"got {facts['freq_step_converged']!r}; freq_step_convergence={table}")
    if not monatomic and facts['vibrational_modes_complete'] is not True:
        raise ValueError(f'{attempt_id}: requires vibrational_modes_complete is True; '
                         f"got {facts['vibrational_modes_complete']!r}; "
                         f"n_vibrational_modes={facts.get('n_vibrational_modes')}, "
                         f"expected_vibrational_modes={facts.get('expected_vibrational_modes')}")
    return {key: facts.get(key) for key in
            ('freq_step_converged', 'freq_step_convergence', 'vibrational_modes_complete',
             'n_vibrational_modes', 'expected_vibrational_modes')} | {
                 'note': '单原子无振动模式；不要求模式完整性。' if monatomic else None}


def _pairing_evidence(directory, facts, sp_directory, sp_facts, geometry):
    import numpy as np
    from ag.gaussian_input import validate
    from ag.geometry import Frame
    from ag._scan import input_geometry

    # Read the manifest-bound SP input: its final output could belong to a
    # different optimized conformer, and mutable science metadata is not evidence.
    manifest = json.loads((sp_directory / 'manifest.json').read_text())
    inputs = [item for item in manifest['inputs']
              if Path(item['name']).suffix.lower() in {'.gjf', '.com'}]
    if manifest['template'] != 'gaussian' or len(inputs) != 1:
        raise ValueError(f'{sp_directory.name}: requires one Gaussian SPC input')
    item = inputs[0]
    if Path(item['name']).name != item['name']:
        raise ValueError('SPC input must be a plain filename')
    data = (sp_directory / 'inputs' / item['name']).read_bytes()
    if sha256(data).hexdigest() != item.get('sha256'):
        raise ValueError(f'{sp_directory.name}: SPC input hash differs from manifest')
    science = validate(data.decode(), manifest['cores'], manifest['mem_gb'],
                       parent_chk=manifest.get('parent_chk') is not None)
    if science.get('qst_mode') or re.search(r'\b(?:opt|irc|scan)\b', science['route'], re.I):
        raise ValueError(f'{sp_directory.name}: SPC requires a single-point input, not optimization/IRC/scan')
    if re.search(r'\bunits?\b', science['route'], re.I):
        raise ValueError(f'{sp_directory.name}: SPC pairing requires default angstrom input units')
    for key in ('n_atoms', 'charge', 'multiplicity'):
        if facts.get(key) is None or science[key] != facts[key] or sp_facts.get(key) != facts[key]:
            raise ValueError(f'{sp_directory.name}: SPC {key} differs from frequency geometry/state')
    symbols, coordinates = input_geometry(science['geometry'])
    moving = Frame(tuple(symbols), tuple(tuple(x) for x in coordinates))
    if not geometry:
        raise ValueError(f'{directory.name}: frequency final geometry is missing')
    symbols, coordinates = input_geometry('\n'.join(geometry.splitlines()[2:]))
    reference = Frame(tuple(symbols), tuple(tuple(x) for x in coordinates))
    if len(reference.symbols) != facts['n_atoms']:
        raise ValueError(f'{directory.name}: requires one complete frequency final geometry')
    if moving.symbols != reference.symbols:
        raise ValueError(f'{sp_directory.name}: SPC element sequence differs; atom reordering is forbidden')
    try:
        with np.errstate(over='raise', invalid='raise'):
            a, b = [np.array(f.coordinates, dtype=float) for f in (moving, reference)]
            a, b = a - a.mean(axis=0), b - b.mean(axis=0)
            u, _, vt = np.linalg.svd(a.T @ b)
            correction = np.eye(3)
            correction[-1, -1] = 1 if np.linalg.det(u @ vt) >= 0 else -1
            rmsd = float(np.sqrt(np.mean(np.sum((a @ (u @ correction @ vt) - b)**2, axis=1))))
    except (FloatingPointError, np.linalg.LinAlgError) as exc:
        raise ValueError(f'{sp_directory.name}: SPC geometry cannot be aligned numerically') from exc
    if not math.isfinite(rmsd) or rmsd > 1e-3:
        raise ValueError(f'{sp_directory.name}: SPC pairing RMSD {rmsd:.8g} angstrom exceeds 0.001')
    return {'rmsd_angstrom': rmsd, 'threshold_angstrom': 1e-3,
            'alignment': 'proper Kabsch; all atoms; fixed row order; no reflection or permutation',
            'sp_input_geometry_sha256': _geometry_sha256(moving),
            'frequency_final_geometry_sha256': _geometry_sha256(reference),
            'sp_input_file': item['name'], 'frequency_final_geometry_file': gaussian_log(directory).name,
            'frequency_final_geometry_source': 'parsed in memory from frequency log',
            'geometry_hash_format': 'SHA-256 of UTF-8 compact sorted-key JSON: '
                                    '{coordinates_angstrom: [[x,y,z],...], elements: [symbol,...]}; '
                                    'parsed floating-point coordinates before alignment'}


def _symmetry_evidence(result, log, source=None):
    # xyz is the QCData object calc_bbe actually used for rotational entropy.
    sigma = result.xyz.symmno
    if not isinstance(sigma, int) or isinstance(sigma, bool) or sigma < 1:
        raise ValueError('GoodVibes rotational symmetry number must be a positive integer')
    reported = [(i, line.strip()) for i, line in enumerate(log.read_text().splitlines(), 1)
                if (source is None or source['start_line'] <= i <= source['end_line'])
                if line.strip().startswith('Rotational symmetry number')]
    return {'rotational_symmetry_number': sigma,
            'rotational_symmetry_source': {'kind': 'gaussian_output' if reported else 'goodvibes_default',
                'file': log.name, 'line': reported[-1][0] if reported else None,
                'reported_text': reported[-1][1] if reported else None,
                'note': 'GoodVibes 4.3.0 QCData.symmno; symm=False; missing output defaults to 1'}}


def _frequency_input(directory, facts, source):
    """Read only the selected section; no geometry/energy from adjacent jobs."""
    from ag._parse_outputs import (gaussian_job_sections, gaussian_section_text,
                                   _parse_gaussian_section)
    log = gaussian_log(directory)
    text = log.read_text(errors='replace')
    sections, _ = gaussian_job_sections(text)
    selected = [s for s in sections if s['index'] == source['section_index']]
    if (len(selected) != 1 or any(selected[0][key] != source[key]
            for key in ('route', 'start_line', 'end_line'))):
        raise ValueError(f'{directory.name}: frequency section differs from facts; regenerate ag facts')
    section = selected[0]
    block = gaussian_section_text(text, section)
    scoped, geometry = _parse_gaussian_section(block, internal=section['start_kind'] == 'internal')
    if scoped['termination'] != 'normal':
        raise ValueError(f'{directory.name}: non-normal frequency section termination')
    for key in ('n_atoms', 'charge', 'multiplicity', 'n_imag', 'freq_step_converged',
                'vibrational_modes_complete'):
        if scoped.get(key) != facts.get(key):
            raise ValueError(f'{directory.name}: frequency section {key} differs from facts')
    _frequency_evidence(scoped, directory.name)
    return block, geometry


def _frequency_thermo(block, options, program_version):
    """Use GoodVibes' unchanged calculation on one Gaussian section.

    Its whole-file parser can otherwise take monatomic energy/symmetry from a
    trailing SP. Temporary input is outside the study and is never an output.
    """
    from goodvibes.io import parse_gaussian_thermo
    from goodvibes.thermo import calc_bbe
    # Internal job steps omit the launch banner. GoodVibes needs that banner
    # even with its Gaussian-specific parser. Reuse only the already checked
    # log-wide program version, never another section's route or numeric data.
    if not re.search(r'Gaussian[^\n]*Revision', block):
        match = re.fullmatch(r'Gaussian (\d{2}) Rev ([A-Z]\.\d{2})', program_version)
        if match is None:
            raise ValueError('Cannot identify Gaussian version for frequency section')
        block = f' Gaussian {match[1]}, Revision {match[2]},\n' + block
    with TemporaryDirectory(prefix='ag-thermo-section-') as temp:
        path = Path(temp) / 'frequency.log'
        path.write_text(block)
        return calc_bbe.from_options(parse_gaussian_thermo(str(path)), options)


def _ensemble_consistency(rows):
    """List incompatible layers/states instead of weighting unrelated energies."""
    baseline = rows[0]
    differences = []
    for row in rows[1:]:
        for key, expected in baseline['comparability'].items():
            actual = row['comparability'][key]
            if actual != expected:
                differences.append(f"{row['attempt_id']}: {key}={actual!r}; "
                                   f"{baseline['attempt_id']} has {expected!r}")
    if differences:
        raise ValueError('Incomparable thermo ensemble:\n' + '\n'.join(differences))


def calculate_thermo(attempts, *, study=None, temp=298.15, conc=1.0, qs='grimme',
                     s_cutoff=100.0, h_cutoff=100.0, degeneracy=None, spc=None):
    """Compute a table from local logs. Does not write the analysis output."""
    # Imported on command execution, never while CLI/help is registered.
    from goodvibes.thermo import ThermoOptions
    from ag._profile_sources import section_source, integration_grid, grid_warnings, integer, nonempty

    if version('goodvibes') != '4.3.0':
        raise ValueError('ag thermo requires GoodVibes 4.3.0')
    for name, value in [('temperature', temp), ('concentration', conc),
                        ('entropy cutoff', s_cutoff), ('enthalpy cutoff', h_cutoff)]:
        _positive(value, name)
    if qs not in {'grimme', 'truhlar'}:
        raise ValueError('Unknown entropy treatment')
    directories = [resolve_attempt(str(a), study) for a in attempts]
    if not directories or len(set(directories)) != len(directories):
        raise ValueError('Provide at least one distinct Attempt; duplicates double-count populations')
    if len({d.parent for d in directories}) != 1:
        raise ValueError('Thermo inputs must belong to the same study')
    deg = {resolve_attempt(str(k), study): v for k, v in (degeneracy or {}).items()}
    sp = {resolve_attempt(str(k), study): resolve_attempt(str(v), study)
          for k, v in (spc or {}).items()}
    from ag.cp_report import reject_cp
    for source in set(directories) | set(sp.values()):
        reject_cp(source)
    if (set(deg) | set(sp)) - set(directories):
        raise ValueError('A degeneracy/SPC mapping does not match an input Attempt')
    if sp and len(sp) != len(directories):
        raise ValueError('SPC must be present for all conformers or none; '
                         f"with SPC: {', '.join(d.name for d in directories if d in sp)}; "
                         f"without SPC: {', '.join(d.name for d in directories if d not in sp)}")
    options = ThermoOptions(QS=qs, QH=True, s_freq_cutoff=s_cutoff, h_freq_cutoff=h_cutoff,
                            temperature=temp, concentration=conc,
                            freq_scale_factor=1.0, zpe_scale_factor=1.0)
    rows = []
    grids = []
    for directory in directories:
        facts, _ = parse_facts(directory)
        if facts['termination'] != 'normal' or facts.get('n_imag') != 0:
            raise ValueError(f'{directory.name}: requires normal termination and frequencies with n_imag = 0')
        if facts['program'] != 'gaussian':
            raise ValueError(f'{directory.name}: Gaussian frequency output is required')
        frequency_evidence = _frequency_evidence(facts, directory.name)
        frequency_source = section_source(facts, directory.name, directory=directory)
        frequency_protocol = frequency_source['protocol']
        block, geometry = _frequency_input(directory, facts, frequency_source)
        frequency_version = nonempty(facts.get('program_version'), f'{directory.name}: program version')
        if not geometry:
            raise ValueError(f'{directory.name}: missing frequency final geometry')
        elements = dict(Counter(line.split()[0] for line in geometry.splitlines()[2:] if line.strip()))
        if sum(elements.values()) != facts.get('n_atoms'):
            raise ValueError(f'{directory.name}: atom count mismatch')
        comparability = {'elements': elements,
                         'charge': integer(facts.get('charge'), f'{directory.name} charge'),
                         'multiplicity': integer(facts.get('multiplicity'), f'{directory.name} multiplicity', positive=True),
                         'frequency_protocol': frequency_protocol, 'frequency_program_version': frequency_version,
                         'single_point_protocol': None, 'single_point_program_version': None}
        frequency_grid = integration_grid(frequency_source['route'])
        grids.append((f'{directory.name}/frequency', frequency_grid))
        sp_grid = None
        weight = deg.get(directory, 1)
        if not isinstance(weight, int) or isinstance(weight, bool) or weight <= 0:
            raise ValueError(f'{directory.name}: degeneracy must be a positive integer')
        result = _frequency_thermo(block, options, frequency_version)
        needed = ('scf_energy', 'zpe', 'enthalpy', 'qh_enthalpy', 'qh_gibbs_free_energy',
                  'entropy', 'qh_entropy', 'gibbs_free_energy')
        if any(not isinstance(getattr(result, key, None), (float, int))
               or not math.isfinite(getattr(result, key)) for key in needed):
            raise ValueError(f'{directory.name}: GoodVibes could not calculate complete thermochemistry')
        delta = 0.0
        electronic = result.scf_energy
        electronic_source = frequency_source
        sp_id = None
        pairing = None
        if directory in sp:
            sp_facts, _ = parse_facts(sp[directory])
            if sp_facts['termination'] != 'normal' or sp_facts.get('n_imag') not in (0, None):
                raise ValueError(f'{sp[directory].name}: SPC requires normal termination and no imaginary frequencies')
            electronic_source = section_source(sp_facts, sp[directory].name,
                                               frequency=False, directory=sp[directory])
            comparability.update(single_point_protocol=electronic_source['protocol'],
                single_point_program_version=nonempty(sp_facts.get('program_version'), f'{sp[directory].name}: program version'))
            sp_grid = integration_grid(electronic_source['route'])
            grids.append((f'{sp[directory].name}/single_point', sp_grid))
            electronic = sp_facts.get('energies', {}).get('scf')
            if electronic is None:
                raise ValueError(f'{sp[directory].name}: SPC electronic energy is missing')
            pairing = _pairing_evidence(directory, facts, sp[directory], sp_facts,
                                        geometry)
            delta = electronic - result.scf_energy
            sp_id = sp[directory].name
        # GoodVibes already applies the requested concentration in translation.
        # These are audit terms, not extra corrections to qh_G.
        standard_state = R_HARTREE * temp * math.log(8.3144621 * temp / 101.325)
        concentration = R_HARTREE * temp * math.log(conc)
        rows.append({'attempt_id': directory.name, 'degeneracy': weight,
                     'frequency_evidence': frequency_evidence,
                     'frequency_source': frequency_source, 'electronic_energy_source': electronic_source,
                     'comparability': comparability,
                     'integration_grid': {'frequency': frequency_grid, 'single_point': sp_grid},
                     'degeneracy_source': 'explicit --degeneracy/API mapping' if directory in deg else 'default 1',
                     **_symmetry_evidence(result, gaussian_log(directory), frequency_source),
                     'E': electronic, 'frequency_E': result.scf_energy,
                     'ZPE': result.zpe, 'H': result.enthalpy + delta,
                     'S': result.entropy, 'G': result.gibbs_free_energy + delta,
                     'qh_H': result.qh_enthalpy + delta, 'qh_S': result.qh_entropy,
                     'frequency_rrho': {'H': result.enthalpy, 'S': result.entropy,
                                        'G': result.gibbs_free_energy},
                     'frequency_rrho_G_1atm': result.gibbs_free_energy - standard_state - concentration,
                     'low_frequency_correction': result.qh_gibbs_free_energy - result.gibbs_free_energy,
                     'standard_state_correction': standard_state,
                     'concentration_correction': concentration,
                     'pairing_evidence': pairing,
                     'qh_G': result.qh_gibbs_free_energy + delta,
                     'spc_attempt_id': sp_id, 'spc_correction': delta})
    _ensemble_consistency(rows)
    populations, average, ensemble = boltzmann(
        [r['qh_G'] for r in rows], [r['degeneracy'] for r in rows], temp)
    minimum = min(r['qh_G'] for r in rows)
    for row, population in zip(rows, populations):
        row.update(relative_G_kcal=(row['qh_G']-minimum)*HARTREE_TO_KCAL, population=population)
    return {'schema': 'ag-thermo/1', 'goodvibes_version': '4.3.0',
            'settings': {'temperature_K': temp, 'concentration_mol_L': conc, 'qs': qs,
                         'qh': 'head_gordon', 's_cutoff_cm1': s_cutoff, 'h_cutoff_cm1': h_cutoff,
                         'frequency_scale': 1.0, 'zpe_scale': 1.0,
                         'rotational_symmetry': 'from_output', 'inertia': 'global'},
            'units': {'energy': 'Hartree', 'entropy': 'Hartree/K', 'pairing_rmsd': 'angstrom', 'relative_G': 'kcal/mol', 'population': 'fraction'},
            'rows': rows, 'weighted_mean_G': average, 'ensemble_G': ensemble,
            'warnings': grid_warnings(grids), 'species_review_note': SPECIES_REVIEW_NOTE,
            'note': 'H/S/G are RRHO; qh_H/qh_S/qh_G are qRRHO, all at the requested T and concentration, '
                    'with SPC replacing electronic energy in H/G only. frequency_rrho retains frequency-level RRHO. '
                    'qh_G = frequency_rrho_G_1atm + spc_correction + low_frequency_correction '
                    '+ standard_state_correction + concentration_correction. '
                    'standard_state_correction is 1 atm to 1 mol/L, already included; '
                    'concentration_correction is 1 mol/L to the requested concentration. '
                    'Reaction path multiplicity must be recorded separately; it is not conformer degeneracy '
                    'or rotational symmetry. SMD H/S components are not experimental solution enthalpy/entropy. '
                    'Successful execution alone does not establish pairing; review pairing_evidence. '
                    'Populations are normalized only over the supplied conformers. '
                    'weighted_mean_G = sum(p_i * qh_G_i) is the arithmetic population-weighted mean. '
                    'ensemble_G = -RT ln sum(d_i * exp(-qh_G_i / RT)) is the conformer ensemble '
                    'free energy, including conformational mixing and degeneracy. Both are in Hartree.'}


def write_analysis(result, study_dir):
    analyses = Path(study_dir) / 'analyses'
    analyses.mkdir(parents=True, exist_ok=True)
    name = 'thermo-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    json_path, md_path = analyses / (name + '.json'), analyses / (name + '.md')
    # Exclusive creation prevents a timestamp collision from replacing an analysis.
    with json_path.open('x') as stream:
        stream.write(json.dumps(result, indent=2, allow_nan=False) + '\n')
    settings = result['settings']
    lines = [f"# Thermochemistry — {settings['temperature_K']} K, {settings['concentration_mol_L']} mol/L",
             '', 'GoodVibes 4.3.0; ' + json.dumps(settings, ensure_ascii=False), '',
             'Energies/corrections in Hartree; S and qh_S in Hartree/K; ΔG in kcal/mol.', '',
             '| Attempt | d_i | σ_i | E | ZPE | H (RRHO) | S (RRHO) | G (RRHO) | qh_H | qh_S | qh-G | ΔG | Population | SPC |',
             '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|']
    for row in result['rows']:
        values = ' | '.join(f"{row[key]:.10f}" for key in ('E', 'ZPE', 'H', 'S', 'G', 'qh_H', 'qh_S', 'qh_G'))
        lines.append(f"| {row['attempt_id']} | {row['degeneracy']} | {row['rotational_symmetry_number']} | "
                     f"{values} | {row['relative_G_kcal']:.6f} | {row['population']:.6%} | {row['spc_attempt_id'] or '—'} |")
    lines += ['', '| Attempt | Frequency RRHO H | Frequency RRHO S | Frequency RRHO G | RRHO G at 1 atm | SPC replacement | Low frequency ΔG | 1 atm → 1 M ΔG | 1 M → requested conc ΔG |',
              '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for row in result['rows']:
        values = [row['frequency_rrho'][key] for key in ('H', 'S', 'G')]
        values += [row[key] for key in ('frequency_rrho_G_1atm', 'spc_correction',
                   'low_frequency_correction', 'standard_state_correction', 'concentration_correction')]
        lines.append('| ' + row['attempt_id'] + ' | ' + ' | '.join(f'{v:.10f}' for v in values) + ' |')
    lines += ['', '| Attempt | d_i source | σ_i source |', '|---|---|---|']
    for row in result['rows']:
        source = row['rotational_symmetry_source']
        lines.append(f"| {row['attempt_id']} | {row['degeneracy_source']} | {source['kind']}; "
                     f"{source['file']}:{source['line'] or '—'}; {source['reported_text'] or source['note']} |")
    for row in result['rows']:
        evidence = row.get('frequency_evidence', {})
        if evidence.get('note'):
            lines += ['', f"{row['attempt_id']}: {evidence['note']}"]
    lines += ['', result.get('species_review_note', SPECIES_REVIEW_NOTE), '',
              '| Attempt | Layer | Protocol | Program version | Integration grid |',
              '|---|---|---|---|---|']
    for row in result['rows']:
        for layer in ('frequency', 'single_point'):
            comparison = row['comparability']
            if comparison[f'{layer}_protocol'] is not None:
                lines.append(f"| {row['attempt_id']} | {layer} | "
                             f"{json.dumps(comparison[f'{layer}_protocol'], ensure_ascii=False)} | "
                             f"{comparison[f'{layer}_program_version']} | {row['integration_grid'][layer]} |")
    lines += ['', *[f'- 警告：{warning}' for warning in result.get('warnings', [])]]
    lines += ['', '| Attempt | Layer | Source attempt | Section | Log lines |',
              '|---|---|---|---:|---|']
    for row in result['rows']:
        for key in ('frequency_source', 'electronic_energy_source'):
            source = row[key]
            lines.append(f"| {row['attempt_id']} | {key} | {source['attempt_id']} | "
                         f"{source['section_index']} | {source['start_line']}–{source['end_line']} |")
    lines += ['', '| Frequency Attempt | SP Attempt | RMSD (Å) | SP input geometry SHA-256 | Frequency final geometry SHA-256 |',
              '|---|---|---:|---|---|']
    for row in result['rows']:
        evidence = row['pairing_evidence']
        if evidence is None:
            lines.append(f"| {row['attempt_id']} | — (no SPC) | — | — | — |")
        else:
            lines.append(f"| {row['attempt_id']} | {row['spc_attempt_id']} | {evidence['rmsd_angstrom']:.10g} | "
                         f"{evidence['sp_input_geometry_sha256']} | {evidence['frequency_final_geometry_sha256']} |")
    lines += ['', f"Weighted mean G (weighted_mean_G): {result['weighted_mean_G']:.10f} Hartree.",
              '', f"Conformer ensemble free energy (ensemble_G): {result['ensemble_G']:.10f} Hartree.",
              '', result['note'], '']
    with md_path.open('x') as stream:
        stream.write('\n'.join(lines))
    return json_path, md_path


def _run(args):
    try:
        result = calculate_thermo(args.attempts, study=args.study, temp=args.temp, conc=args.conc,
                                  qs=args.qs, s_cutoff=args.s_cutoff, h_cutoff=args.h_cutoff,
                                  degeneracy=_mappings(args.degeneracy, int), spc=_mappings(args.spc, str))
        directory = resolve_attempt(args.attempts[0], args.study)
        if directory.parent.name != 'attempts':
            raise ValueError('Thermo requires a study/attempts directory layout')
        paths = write_analysis(result, directory.parent.parent)
        print(json.dumps(result, indent=2) if args.json else paths[1].read_text())
        return 0
    except ImportError as exc:
        print(f'Chemistry dependency unavailable: {exc}', file=sys.stderr)
        return 2
    except (ValueError, OSError, KeyError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


def register(subparsers):
    parser = subparsers.add_parser('thermo', help='GoodVibes qRRHO and conformer populations')
    parser.add_argument('attempts', nargs='+')
    parser.add_argument('--study')
    parser.add_argument('--temp', type=float, default=298.15)
    parser.add_argument('--conc', type=float, default=1.0)
    parser.add_argument('--qs', choices=['grimme', 'truhlar'], default='grimme')
    parser.add_argument('--s-cutoff', type=float, default=100.0)
    parser.add_argument('--h-cutoff', type=float, default=100.0)
    parser.add_argument('--degeneracy', action='append', default=[], metavar='ATTEMPT=N')
    parser.add_argument('--spc', action='append', default=[], metavar='ATTEMPT=SP_ATTEMPT')
    parser.add_argument('--json', action='store_true')
    parser.set_defaults(func=_run)
