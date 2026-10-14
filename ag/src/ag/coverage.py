"""Report route overlap in an explicitly supplied DFT energy window, locally only."""

import hashlib
import json
import math
from pathlib import Path
import re
import sys

from . import geometry as geo
from .facts import resolve_attempt
from .gaussian_input import validate


TOLERANCE = 1e-4  # Angstrom; fixed atom order, no alignment or renaming heuristic.


def input_geometry(directory):
    manifest = json.loads((directory / 'manifest.json').read_text())
    if manifest['template'] != 'gaussian':
        raise ValueError('Expected a Gaussian Attempt')
    inputs = [item for item in manifest['inputs'] if Path(item['name']).suffix.lower() in {'.gjf', '.com'}]
    if len(inputs) != 1:
        raise ValueError('Expected exactly one Cartesian Gaussian input')
    item = inputs[0]
    if Path(item['name']).name != item['name']:
        raise ValueError('Input must be a plain filename')
    data = (directory / 'inputs' / item['name']).read_bytes()
    if hashlib.sha256(data).hexdigest() != item['sha256']:
        raise ValueError('Input hash differs from manifest')
    science = validate(data.decode(), manifest['cores'], manifest['mem_gb'],
                       parent_chk=manifest.get('parent_chk') is not None)
    if science.get('qst_mode') or re.search(r'\bunits\b', science['route'], re.I):
        raise ValueError('Requires one input geometry in default Angstrom units')
    from rdkit import Chem
    periodic = Chem.GetPeriodicTable()
    symbols, coordinates = [], []
    for row in science['geometry'].splitlines():
        atom, *xyz = row.split()
        symbols.append(periodic.GetElementSymbol(int(atom)) if atom.isdigit() else atom)
        coordinates.append(tuple(geo.finite_number(value) for value in xyz))
    return geo.Frame(tuple(symbols), tuple(coordinates)), science


def same_geometry(left, right):
    return left.symbols == right.symbols and all(
        math.dist(a, b) <= TOLERANCE for a, b in zip(left.coordinates, right.coordinates))


def energy_rows(values, study=None):
    """Accept Attempt arguments, a JSON list of them, or native ag-thermo JSON."""
    basis, table = 'scf', None
    if len(values) == 1 and Path(values[0]).is_file():
        path = Path(values[0])
        payload = json.loads(path.read_text())
        if isinstance(payload, list) and all(isinstance(v, str) for v in payload):
            # List paths are relative to the list, not the caller's working directory.
            values = [str(path.parent / v) if (path.parent / v).is_dir() else v for v in payload]
        elif isinstance(payload, dict) and payload.get('schema') == 'ag-thermo/1':
            if payload.get('units', {}).get('energy') != 'Hartree':
                raise ValueError('Thermochemistry table must use Hartree')
            basis, table = 'qh_G', payload['rows']
            values = [r['attempt_id'] for r in table]
            if study is None and path.parent.name == 'analyses':
                study = str(path.parent.parent)
        else:
            raise ValueError('--energies expects Attempt directories, a JSON list, or ag-thermo/1 JSON')
    rows, unmatched = [], []
    seen = set()
    for index, value in enumerate(values):
        try:
            directory = resolve_attempt(value, study)
            if directory in seen:
                raise ValueError('Duplicate energy Attempt')
            seen.add(directory)
            frame, science = input_geometry(directory)
            if table is not None:
                energy = geo.finite_number(table[index]['qh_G'])
            else:
                facts = json.loads((directory / 'facts.json').read_text())
                if facts.get('program') != 'gaussian' or facts.get('termination') != 'normal':
                    raise ValueError('Requires normally terminated Gaussian facts')
                if facts.get('units', {}).get('energy') != 'Hartree':
                    raise ValueError('SCF facts must use Hartree')
                # Optimization/IRC energies belong to output geometries, not the input being matched.
                if re.search(r'\b(?:opt|irc|scan|force|freq)\b', science['route'], re.I):
                    raise ValueError('Attempt list requires single points; use a thermochemistry table for qh_G')
                energy = geo.finite_number(facts['energies']['scf'])
            rows.append({'attempt': str(value), 'energy_hartree': energy, 'geometry': frame})
        except (ValueError, OSError, KeyError, TypeError, RuntimeError) as exc:
            unmatched.append({'attempt': str(value), 'reason': str(exc)})
    return basis, rows, unmatched


def report(merged, values, window=3.0, top=5, study=None):
    window = geo.nonnegative(window)
    if top < 1:
        raise ValueError('--top must be positive')
    merged = Path(merged)
    payload = json.loads(merged.read_text())
    records = payload['kept']
    xyz_path = merged.parent / payload['xyz_file']
    # Without this binding a replaced XYZ could silently retain another ensemble's routes.
    if hashlib.sha256(xyz_path.read_bytes()).hexdigest() != payload.get('xyz_sha256'):
        raise ValueError('Dedup XYZ hash differs from source provenance')
    frames = geo.read_xyz(xyz_path)
    if len(records) != len(frames) or any(r['xyz_frame'] != i + 1 for i, r in enumerate(records)):
        raise ValueError('Dedup records and XYZ frame ordering differ')
    if any(not isinstance(r.get('sources'), list) or not r['sources'] or
           any(not isinstance(s, str) or not s for s in r['sources']) for r in records):
        raise ValueError('Coverage requires dedup --source provenance for every candidate')
    basis, rows, unmatched = energy_rows(values, study)
    matches = {i: [] for i in range(len(frames))}
    for row in rows:
        indices = [i for i, frame in enumerate(frames) if same_geometry(frame, row['geometry'])]
        entry = {k: v for k, v in row.items() if k != 'geometry'}
        if len(indices) != 1:
            unmatched.append({**entry, 'reason': 'geometry_unmatched' if not indices else 'geometry_ambiguous',
                              'candidate_indices': [records[i]['index'] for i in indices]})
        else:
            matches[indices[0]].append(entry)
    candidates, missing = [], []
    for i, entries in matches.items():
        row = records[i]
        if len(entries) != 1:
            reason = 'no_matching_energy' if not entries else 'multiple_matching_energies'
            missing.append({'index': row['index'], 'sources': row['sources'], 'reason': reason})
            unmatched.extend({**entry, 'reason': reason, 'candidate_indices': [row['index']]} for entry in entries)
        else:
            candidates.append({'index': row['index'], 'sources': sorted(set(row['sources'])), **entries[0]})
    candidates.sort(key=lambda r: (r['energy_hartree'], r['index']))
    minimum = candidates[0]['energy_hartree'] if candidates else None
    for row in candidates:
        row['relative_energy_kcal'] = (row['energy_hartree'] - minimum) * geo.HARTREE_TO_KCAL
    inside = [r for r in candidates if r['relative_energy_kcal'] <= window]
    routes = sorted(set(payload.get('routes', [])) | {s for r in records for s in r['sources']})
    counts = {route: sum(route in r['sources'] for r in inside) for route in routes}
    exclusive = [r for r in inside if len(r['sources']) == 1]
    warnings = []
    # Include ties for the minimum: choosing one arbitrary tied index would hide a warning.
    lowest = [r for r in candidates if abs(r['energy_hartree'] - minimum) <= 1e-12]
    if any(len(r['sources']) == 1 for r in lowest):
        warnings.append('采样可能不足：最低能构象只被一条路线找到。')
    for route in routes:
        if sum(r['sources'] == [route] for r in inside) > len(inside) / 2:
            warnings.append(f'采样可能不足：窗口内一半以上构象仅由 {route} 找到。')
    return {'energy_basis': basis, 'energy_unit': 'hartree', 'window_kcal': window,
            'geometry_tolerance_angstrom': TOLERANCE, 'matching': 'input coordinates; fixed atom order; no alignment',
            'n_candidates': len(records), 'n_matched': len(candidates), 'n_in_window': len(inside),
            'route_counts': counts, 'top_n': top, 'lowest': candidates[:top],
            'in_window': inside, 'single_route_low_energy': exclusive,
            'unmatched_attempts': unmatched, 'unmatched_candidates': missing, 'warnings': warnings,
            'note': '覆盖报告不能证明采样已经完备；仅统计已提供且唯一匹配的能量，不代替科学审阅或自动扩大采样。'}


def markdown(result):
    lines = ['# 构象采样覆盖报告', '',
             f"能量：{result['energy_basis']} (Hartree)；窗口 ≤ {result['window_kcal']:g} kcal/mol。",
             f"候选 {result['n_candidates']}；唯一能量匹配 {result['n_matched']}；窗口内 {result['n_in_window']}。",
             '', '路线计数（同一构象可计入多条路线）：']
    lines += [f'- {route}: {count}' for route, count in result['route_counts'].items()]
    for title, key in [(f"最低的 {result['top_n']} 个构象", 'lowest'), ('窗口内单路线独有构象', 'single_route_low_energy')]:
        lines += ['', title, '', '| 候选 | ΔE/ΔG (kcal/mol) | 路线 |', '|---|---:|---|']
        lines += [f"| {r['index']} | {r['relative_energy_kcal']:.6f} | {', '.join(r['sources'])} |" for r in result[key]]
    for title, key in [('未匹配 Attempt', 'unmatched_attempts'), ('未匹配候选', 'unmatched_candidates')]:
        lines += ['', title + '：']
        lines += ['- ' + json.dumps(row, ensure_ascii=False) for row in result[key]] or ['- 无']
    lines += ['', '警告：', *('- ' + w for w in result['warnings'])]
    if not result['warnings']:
        lines.append('- 未触发规则（不表示采样充分）。')
    lines += ['', result['note'], '']
    return '\n'.join(lines)


def run(args):
    try:
        result = report(args.merged, args.energies, args.window, args.top, args.study)
        content = json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + '\n' if args.json else markdown(result)
        with args.out.open('x') as stream:
            stream.write(content)
        print(content, end='')
        return 0
    except ImportError:
        print('coverage requires RDKit in the selected Python environment', file=sys.stderr)
        return 2
    except (ValueError, OSError, KeyError, TypeError, RuntimeError) as exc:
        print(f'coverage: {exc}', file=sys.stderr)
        return 1


def register(subparsers):
    parser = subparsers.add_parser('coverage', description=__doc__)
    parser.add_argument('--merged', type=Path, required=True, help='dedup --source JSON output')
    parser.add_argument('--energies', nargs='+', required=True, help='SP Attempt directories/IDs, JSON list, or ag thermo JSON')
    parser.add_argument('--study', help='Study directory or configured ID for resolving Attempt IDs')
    parser.add_argument('--window', type=float, default=3.0, help='kcal/mol above the lowest matched energy, inclusive')
    parser.add_argument('--top', type=int, default=5, help='Number of lowest-energy candidates to list')
    parser.add_argument('--out', type=Path, required=True, help='New report file; existing files are refused')
    parser.add_argument('--json', action='store_true', help='Write and print JSON instead of Markdown')
    parser.set_defaults(func=run)
