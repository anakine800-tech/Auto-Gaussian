"""Balanced reaction free-energy profiles from local species ensembles."""
from collections import Counter
import json
import math
from pathlib import Path
import re

from ag._profile_sources import (DEFAULT_SETTINGS, finite, integer, load_species,
                                 nonempty, read_json, require)
from ag.thermo import HARTREE_TO_KCAL, R_HARTREE

R_KCAL = R_HARTREE * HARTREE_TO_KCAL
R_L_ATM = 0.082057366080960
SPAN_DOI = '10.1021/ar1000956'
FORMULAS = {
    'ensemble': 'G_s = -RT ln sum_i d_i exp(-G_si/RT); never sum_i p_i G_si',
    'composite': 'G_si = E_SP,si + (G_qh,freq,si - E_freq,si)',
    'standard_state': 'G_s(target) = G_s(source) + RT ln(C_target/C_source); C_1atm = 1/(R_L_atm T)',
    'explicit_solvent': 'G_s(c) = G_s(target) + RT ln(c_s/C_target)',
    'state': 'G_state = sum_s nu_s G_s; DeltaG_state = G_state - G_reference',
    'forward': 'DeltaG_forward = G_TS - G_reactant',
    'reverse': 'DeltaG_reverse = G_TS - G_product',
    'reaction': 'DeltaG_reaction = G_product - G_reactant',
    'span': 'deltaE = max_ij [G_TS_i - G_I_j + (DeltaG_cycle if TS_i precedes I_j else 0)]; DeltaG_cycle = G_end - G_start',
}


def energetic_span(states):
    """Kozuch–Shaik eq 9: ordered, one-turnover profile, terminal replica excluded.

    Include all co-maximal pairs instead of arbitrarily declaring a single
    rate-controlling state when two contributions are equal within rounding.
    """
    reaction = states[-1]['relative_G_kcal'] - states[0]['relative_G_kcal']
    pairs = []
    for i, ts in enumerate(states[:-1]):
        if ts['kind'] != 'ts':
            continue
        for j, intermediate in enumerate(states[:-1]):
            if intermediate['kind'] != 'minimum':
                continue
            correction = reaction if i < j else 0.0
            pairs.append({'TDTS': ts['id'], 'TDI': intermediate['id'],
                          'cycle_correction_kcal': correction,
                          'delta_E_kcal': ts['relative_G_kcal'] - intermediate['relative_G_kcal'] + correction})
    require(bool(pairs), 'A catalytic cycle needs intermediates and transition states')
    maximum = max(p['delta_E_kcal'] for p in pairs)
    dominant = [p for p in pairs if math.isclose(p['delta_E_kcal'], maximum, rel_tol=0, abs_tol=1e-8)]
    return {'delta_E_kcal': maximum, 'TDTS': sorted({p['TDTS'] for p in dominant}),
            'TDI': sorted({p['TDI'] for p in dominant}), 'determining_pairs': dominant,
            'pairs': pairs, 'reaction_G_kcal': reaction, 'doi': SPAN_DOI,
            'formula': FORMULAS['span'],
            'note': 'Forward-cycle energetic-span approximation, not a full microkinetic model or proof of mechanism. '
                    'For non-exergonic cycles this is a formal span, not a forward TOF estimate.'}


def step_table(states):
    return [{'reactant': a['id'], 'ts': ts['id'], 'product': b['id'],
             'forward_barrier_kcal': ts['relative_G_kcal'] - a['relative_G_kcal'],
             'reverse_barrier_kcal': ts['relative_G_kcal'] - b['relative_G_kcal'],
             'reaction_G_kcal': b['relative_G_kcal'] - a['relative_G_kcal'],
             'formulas': {'forward': f"G({ts['id']}) - G({a['id']})",
                          'reverse': f"G({ts['id']}) - G({b['id']})",
                          'reaction': f"G({b['id']}) - G({a['id']})"}}
            for a, ts, b in zip(states[::2], states[1::2], states[2::2])]


def sensitivity(states, perturb, cycle):
    def determining(rows):
        if cycle:
            span = energetic_span(rows)
            return {'pairs': [[p['TDTS'], p['TDI']] for p in span['determining_pairs']],
                    'delta_E_kcal': span['delta_E_kcal']}
        steps = step_table(rows)
        highest = max(s['forward_barrier_kcal'] for s in steps)
        return {'highest_local_barrier_TS': [s['ts'] for s in steps if math.isclose(
            s['forward_barrier_kcal'], highest, rel_tol=0, abs_tol=1e-8)],
                'barrier_kcal': highest}
    baseline = determining(states)
    key = 'pairs' if cycle else 'highest_local_barrier_TS'
    variants = []
    for index, state in enumerate(states):
        if state['kind'] != 'ts':
            continue
        for sign in (-1, 1):
            shifted = [dict(s) for s in states]
            shifted[index]['relative_G_kcal'] += sign * perturb
            result = determining(shifted)
            variants.append({'perturbed_TS': state['id'], 'shift_kcal': sign * perturb,
                             **result, 'changed': result[key] != baseline[key]})
    return {'perturb_kcal': perturb, 'baseline': baseline, 'variants': variants,
            'any_changed': any(v['changed'] for v in variants),
            'scope': 'One TS state at a time, +/- x kcal/mol; not simultaneous independent errors. '
                     'For non-cycles only the highest local forward barrier is compared, not a kinetic RDS.'}


def calculate_profile(definition, *, perturb=None):
    path = Path(definition).expanduser().resolve()
    require(path.parent.name == 'analyses', 'Profile definition must be in study/analyses/')
    study, analyses = path.parent.parent, path.parent
    data = read_json(path)
    require(set(data) <= {'species', 'states', 'reference', 'temperature_K', 'standard_state',
                         'explicit_solvent_concentrations_M', 'thermo_settings', 'catalytic_cycle'},
            'Unknown profile field')
    specs, states = data.get('species'), data.get('states')
    require(isinstance(specs, dict) and bool(specs), 'Missing species definitions')
    require(isinstance(states, list) and len(states) >= 3 and len(states) % 2 == 1,
            'Provide ordered minimum/ts/minimum states for each step')
    used, state_ids = set(), []
    for index, state in enumerate(states):
        require(isinstance(state, dict) and set(state) == {'id', 'kind', 'species'},
                'Each state needs id, kind and species')
        sid = nonempty(state['id'], 'state id')
        require(sid not in state_ids, f'Duplicate state: {sid}')
        state_ids.append(sid)
        require(state['kind'] == ('ts' if index % 2 else 'minimum'),
                'States must alternate minimum/ts/minimum in reaction order')
        components = state['species']
        require(isinstance(components, dict) and bool(components), f'{sid}: missing species')
        for name, coefficient in components.items():
            require(name in specs, f'{sid}: missing species {name}')
            integer(coefficient, f'{sid}/{name}: stoichiometry', positive=True)
            used.add(name)
    require(used == set(specs), 'Unused species definitions: remove them or include them in states')
    reference = data.get('reference')
    require(reference in state_ids, 'Reference state is missing')
    cycle = data.get('catalytic_cycle', False)
    require(type(cycle) is bool, 'catalytic_cycle must be boolean')
    if perturb is not None:
        finite(perturb, 'perturb', positive=False)
        require(perturb >= 0, 'perturb must be non-negative')
    direct_settings = dict(DEFAULT_SETTINGS)
    overrides = data.get('thermo_settings', {})
    require(isinstance(overrides, dict) and set(overrides) <= set(DEFAULT_SETTINGS), 'Unknown thermo_settings')
    direct_settings.update(overrides)
    if 'temperature_K' in data:
        if 'temperature_K' in overrides:
            require(data['temperature_K'] == overrides['temperature_K'], 'Conflicting temperature settings')
        direct_settings['temperature_K'] = finite(data['temperature_K'], 'temperature_K', positive=True)
    # Infer optional temperature/settings from a supplied thermo table, so an
    # omitted temperature does not silently mix 298.15 K with another value.
    tables = [spec for spec in specs.values() if isinstance(spec, dict) and 'thermo' in spec]
    if tables and not overrides:
        from ag._profile_sources import local_path, settings_checked
        first = read_json(local_path(study, analyses, tables[0]['thermo']))
        direct_settings = dict(settings_checked(first.get('settings')))
    species = {name: load_species(name, spec, study, analyses, direct_settings)
               for name, spec in specs.items()}
    baseline = next(iter(species.values()))
    for name, item in species.items():
        require(item['settings'] == baseline['settings'], f'{name}: inconsistent temperature/standard state/low-frequency settings')
        require(item['protocol'] == baseline['protocol'], f'{name}: inconsistent method/basis/dispersion/solvent protocol')
    settings = baseline['settings']
    for key, value in overrides.items():
        require(settings[key] == value, f'Requested thermo_settings {key} differs from source')
    temperature = settings['temperature_K']
    if 'temperature_K' in data:
        require(temperature == data['temperature_K'], 'Requested temperature differs from source thermochemistry; recompute it')
    standard_state = data.get('standard_state', '1M')
    require(standard_state in ('1M', '1atm'), 'standard_state must be 1M or 1atm')
    target_c = 1.0 if standard_state == '1M' else 1.0 / (R_L_ATM * temperature)
    concentrations = data.get('explicit_solvent_concentrations_M', {})
    require(isinstance(concentrations, dict) and set(concentrations) <= set(species),
            'Explicit solvent concentration refers to missing species')
    rt = R_KCAL * temperature
    for name, item in species.items():
        standard_correction = rt * math.log(target_c / settings['concentration_mol_L'])
        solvent_correction = 0.0
        if name in concentrations:
            require(item['n_imag'] == 0, 'Explicit solvent must be a minimum species')
            concentration = finite(concentrations[name], f'{name}: concentration', positive=True)
            solvent_correction = rt * math.log(concentration / target_c)
        item['standard_state_correction_kcal'] = standard_correction
        item['concentration_correction_kcal'] = solvent_correction
        item['corrected_G_kcal'] = (item['ensemble_G_hartree'] * HARTREE_TO_KCAL
                                    + standard_correction + solvent_correction)
    rows = []
    for state in states:
        elements, charge, ts_count = Counter(), 0, 0
        for name, coefficient in state['species'].items():
            item = species[name]
            elements.update({e: n * coefficient for e, n in item['elements'].items()})
            charge += item['charge'] * coefficient
            ts_count += item['n_imag'] * coefficient
        require(ts_count == (1 if state['kind'] == 'ts' else 0),
                f"{state['id']}: minimum requires only n_imag=0; ts requires exactly one TS species")
        rows.append({**state, 'elements': dict(elements), 'charge': charge,
                     'G_kcal': math.fsum(species[s]['corrected_G_kcal'] * n for s, n in state['species'].items())})
    ref = rows[state_ids.index(reference)]
    for row in rows:
        require(row['elements'] == ref['elements'], f"{row['id']}: elemental composition is not conserved")
        require(row['charge'] == ref['charge'], f"{row['id']}: total charge is not conserved")
        # Subtract species contributions before summing: spectator species
        # cancel exactly and large absolute molecular energies lose fewer bits.
        row['relative_G_kcal'] = math.fsum((row['species'].get(s, 0) - ref['species'].get(s, 0))
                                         * species[s]['corrected_G_kcal'] for s in species)
    result = {'schema': 'ag-profile/1', 'units': 'kcal/mol', 'reference': reference,
              'temperature_K': temperature, 'standard_state': standard_state,
              'explicit_solvent_concentrations_M': concentrations,
              'species': species, 'states': rows, 'steps': step_table(rows), 'formulas': FORMULAS,
              'catalytic_cycle': cycle,
              'note': 'Finite supplied conformer ensembles; equilibration, mechanism and cycle closure are reviewed scientific assumptions.'}
    if cycle:
        result['energetic_span'] = energetic_span(rows)
    if perturb is not None:
        result['sensitivity'] = sensitivity(rows, perturb, cycle)
    # Check derived numbers as well (e.g. overflow from malformed large input).
    try:
        json.dumps(result, allow_nan=False)
    except ValueError as exc:
        raise ValueError('Profile contains non-finite derived energy') from exc
    return result


def markdown(result):
    def cell(value):
        return str(value).replace('|', '\\|').replace('\n', ' ')
    lines = ['# Reaction free-energy profile', '',
             f"Reference: {cell(result['reference'])}; {result['temperature_K']} K; {result['standard_state']}; kcal/mol.", '',
             '| State | Kind | Composition | ΔG |', '|---|---|---|---:|']
    for row in result['states']:
        composition = ' + '.join(f'{n} {s}' for s, n in row['species'].items())
        lines.append(f"| {cell(row['id'])} | {row['kind']} | {cell(composition)} | {row['relative_G_kcal']:.6f} |")
    lines += ['', '| Step | Forward barrier | Reverse barrier | Reaction ΔG |', '|---|---:|---:|---:|']
    for step in result['steps']:
        label = f"{step['reactant']} → {step['ts']} → {step['product']}"
        lines.append(f"| {cell(label)} | {step['forward_barrier_kcal']:.6f} | {step['reverse_barrier_kcal']:.6f} | {step['reaction_G_kcal']:.6f} |")
    lines += ['', '| Species | Ensemble G (Hartree) | Standard-state correction | Concentration correction | Single-conformer reason |',
              '|---|---:|---:|---:|---|']
    for name, item in result['species'].items():
        lines.append(f"| {cell(name)} | {item['ensemble_G_hartree']:.10f} | {item['standard_state_correction_kcal']:.6f} | {item['concentration_correction_kcal']:.6f} | {cell(item['single_conformer_reason'] or '—')} |")
    lines += ['', '## Formulas', '']
    lines += [f'- {name}: `{formula}`' for name, formula in result['formulas'].items()]
    for step in result['steps']:
        lines += ['', cell(f"{step['reactant']} → {step['product']}: ") + '; '.join(
            f'{key} = {cell(value)}' for key, value in step['formulas'].items())]
    if 'energetic_span' in result:
        span = result['energetic_span']
        lines += ['', '## Energetic span', '', f"δE = {span['delta_E_kcal']:.6f} kcal/mol; ΔG_cycle = {span['reaction_G_kcal']:.6f} kcal/mol.",
                  '', 'TDTS/TDI pairs: ' + '; '.join(f"{cell(p['TDTS'])} / {cell(p['TDI'])}" for p in span['determining_pairs']),
                  '', f'[Kozuch–Shaik, eq 9](https://doi.org/{SPAN_DOI}). ' + span['note']]
    if 'sensitivity' in result:
        sensitivity_result = result['sensitivity']
        lines += ['', '## TS perturbations', '', sensitivity_result['scope'], '',
                  '| TS | Shift | Determining states / highest local barrier | Changed |', '|---|---:|---|---|']
        for variant in sensitivity_result['variants']:
            controlling = variant.get('pairs', variant.get('highest_local_barrier_TS'))
            lines.append(f"| {cell(variant['perturbed_TS'])} | {variant['shift_kcal']:+.6f} | {cell(json.dumps(controlling, ensure_ascii=False))} | {variant['changed']} |")
    return '\n'.join(lines + ['', result['note'], ''])


def write_profile(result, definition, name=None):
    definition = Path(definition).resolve()
    require(definition.parent.name == 'analyses', 'Output must be in study/analyses/')
    name = name or definition.stem + '-profile'
    require(isinstance(name, str) and re.fullmatch(r'[\w-]+', name), 'Output name must be a plain filename stem')
    paths = [definition.parent / (name + ext) for ext in ('.json', '.md')]
    payloads = [json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + '\n', markdown(result)]
    for path in paths:
        if path.exists() or path.is_symlink():
            raise FileExistsError(f'Output already exists: {path.name}')
    created = []
    try:
        for path, payload in zip(paths, payloads):
            with path.open('x') as stream:
                created.append(path)
                stream.write(payload)
    except BaseException:
        # Only our newly created local files; never an existing analysis.
        for path in created:
            path.unlink()
        raise
    return tuple(paths)


def _run(args):
    try:
        result = calculate_profile(args.definition, perturb=args.perturb)
        paths = write_profile(result, args.definition, args.name)
        print(json.dumps(result, indent=2, ensure_ascii=False) if args.json else paths[1].read_text())
        return 0
    except (ImportError, ValueError, OSError, KeyError, TypeError) as exc:
        # Malformed local sources must not produce a partial profile.
        if args.json:
            print(json.dumps({'error': str(exc), 'exit_code': 1}, ensure_ascii=False))
        else:
            import sys
            print(str(exc), file=sys.stderr)
        return 1


def register(subparsers):
    parser = subparsers.add_parser('profile', help='Check and assemble a local reaction free-energy profile')
    parser.add_argument('definition', help='Profile JSON in study/analyses/')
    parser.add_argument('--perturb', type=float, metavar='KCAL', help='Perturb each TS state separately by +/- KCAL')
    parser.add_argument('--name', help='New output filename stem in analyses/ (never overwrite)')
    parser.add_argument('--json', action='store_true')
    parser.set_defaults(func=_run)
