"""GoodVibes thermochemistry and explicit finite-ensemble Boltzmann weighting."""

from datetime import datetime, timezone
from importlib.metadata import version
import json
import math
from pathlib import Path
import sys

from ag.facts import build_facts, gaussian_log, resolve_attempt

HARTREE_TO_KCAL = 627.509541
R_HARTREE = 8.3144621 / (HARTREE_TO_KCAL * 4184)


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


def calculate_thermo(attempts, *, study=None, temp=298.15, conc=1.0, qs='grimme',
                     s_cutoff=100.0, h_cutoff=100.0, degeneracy=None, spc=None):
    """Compute a table from local logs. Does not write the analysis output."""
    # Imported on command execution, never while CLI/help is registered.
    from goodvibes.thermo import ThermoOptions, calc_bbe

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
    if (set(deg) | set(sp)) - set(directories):
        raise ValueError('A degeneracy/SPC mapping does not match an input Attempt')
    options = ThermoOptions(QS=qs, QH=True, s_freq_cutoff=s_cutoff, h_freq_cutoff=h_cutoff,
                            temperature=temp, concentration=conc,
                            freq_scale_factor=1.0, zpe_scale_factor=1.0)
    rows = []
    for directory in directories:
        facts = build_facts(directory)
        if facts['termination'] != 'normal' or facts.get('n_imag') != 0:
            raise ValueError(f'{directory.name}: requires normal termination and frequencies with n_imag = 0')
        if facts['program'] != 'gaussian':
            raise ValueError(f'{directory.name}: Gaussian frequency output is required')
        weight = deg.get(directory, 1)
        if not isinstance(weight, int) or isinstance(weight, bool) or weight <= 0:
            raise ValueError(f'{directory.name}: degeneracy must be a positive integer')
        result = calc_bbe.from_options(str(gaussian_log(directory)), options)
        needed = ('scf_energy', 'zpe', 'enthalpy', 'qh_enthalpy', 'qh_gibbs_free_energy')
        if any(not isinstance(getattr(result, key, None), (float, int))
               or not math.isfinite(getattr(result, key)) for key in needed):
            raise ValueError(f'{directory.name}: GoodVibes could not calculate complete thermochemistry')
        delta = 0.0
        electronic = result.scf_energy
        sp_id = None
        if directory in sp:
            sp_facts = build_facts(sp[directory])
            if sp_facts['termination'] != 'normal' or sp_facts.get('n_imag') not in (0, None):
                raise ValueError(f'{sp[directory].name}: SPC requires normal termination and no imaginary frequencies')
            electronic = sp_facts.get('energies', {}).get('scf')
            if electronic is None:
                raise ValueError(f'{sp[directory].name}: SPC electronic energy is missing')
            # Avoid applying a correction from a different system by mistake.
            for key in ('n_atoms', 'charge', 'multiplicity'):
                if sp_facts[key] != facts[key]:
                    raise ValueError(f'{sp[directory].name}: SPC {key} differs from frequency input')
            delta = electronic - result.scf_energy
            sp_id = sp[directory].name
        rows.append({'attempt_id': directory.name, 'degeneracy': weight,
                     'E': electronic, 'frequency_E': result.scf_energy,
                     'ZPE': result.zpe, 'H': result.enthalpy + delta,
                     'qh_H': result.qh_enthalpy + delta,
                     'qh_G': result.qh_gibbs_free_energy + delta,
                     'spc_attempt_id': sp_id, 'spc_correction': delta})
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
            'units': {'energy': 'Hartree', 'relative_G': 'kcal/mol', 'population': 'fraction'},
            'rows': rows, 'weighted_mean_G': average, 'ensemble_G': ensemble,
            'note': 'Populations are normalized only over the supplied conformers. '
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
             'E, ZPE, H and qh-G in Hartree; ΔG in kcal/mol.', '',
             '| Attempt | Degeneracy | E | ZPE | H | qh-G | ΔG | Population | SPC |',
             '|---|---:|---:|---:|---:|---:|---:|---:|---|']
    for row in result['rows']:
        lines.append(f"| {row['attempt_id']} | {row['degeneracy']} | {row['E']:.10f} | "
                     f"{row['ZPE']:.10f} | {row['H']:.10f} | {row['qh_G']:.10f} | "
                     f"{row['relative_G_kcal']:.6f} | {row['population']:.6%} | {row['spc_attempt_id'] or '—'} |")
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
