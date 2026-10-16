"""Local, atom-index-preserving IRC endpoint comparison; never IRC acceptance.

Directional assignment and electronic-state continuity adapt the pure checks
in archive/skills/auto-g16-main-group-open-shell/scripts/open_shell_ts_irc.py
(build_irc_acceptance). Distance evidence is inspired by
archive/skills/auto-g16-ts-irc/scripts/ts_irc.py (propose_endpoint_components).
No archive imports, execution, review contracts, or remote operations.
"""

import json
import math
from pathlib import Path
import re
import sys
import tomllib

from ag import geometry as geo
from ag.facts import resolve_attempt

MATCH, MISMATCH, UNKNOWN = '匹配', '不匹配', '无法确定'


def _attempt(value, study=None):
    try:
        return resolve_attempt(value, study)
    except ValueError:
        if study or Path(value).parent != Path('.'):
            raise
    # Bare IDs also work outside a study, without loading SSH configuration.
    with (Path.home() / '.config/ag/config.toml').open('rb') as handle:
        root = Path(tomllib.load(handle)['local']['studies_root']).expanduser()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', value):
        raise ValueError('Invalid Attempt ID')
    matches = list(root.glob(f'*/attempts/{value}/manifest.json'))
    if len(matches) != 1:
        raise ValueError('Attempt ID missing or ambiguous')
    return matches[0].parent


def load_source(value, study=None, *, allow_xyz=False):
    path = Path(value).expanduser()
    facts = {}
    if allow_xyz and path.is_file():
        kind = 'irc_endpoint' if path.name == 'irc_end.xyz' else 'xyz'
    else:
        path = _attempt(value, study)
        facts = json.loads((path / 'facts.json').read_text())
        irc = facts.get('irc')
        kind = 'irc_endpoint' if irc is not None else 'optimized' if facts.get('opt_converged') is True else 'unverified'
        name = irc.get('end_geometry') if irc is not None else facts.get('final_geometry')
        if not isinstance(name, str) or Path(name).name != name or name in {'.', '..'}:
            raise ValueError(f'{path.name}: missing or invalid geometry in facts.json; run ag facts first')
        path /= name
    frames = geo.read_xyz(path)
    if len(frames) != 1:
        raise ValueError('Each endpoint must contain exactly one XYZ frame')
    note = {'irc_endpoint': '未再优化', 'optimized': '已报告优化收敛；极小值仍需频率与人工审阅',
            'xyz': 'XYZ 未提供再优化证据', 'unverified': '未提供优化收敛证据'}[kind]
    return {'frame': frames[0], 'facts': facts, 'source': str(value),
            'geometry_kind': kind, 'optimization_note': note}


def _pairs(frame, chem):
    table = chem.GetPeriodicTable()
    radii = [table.GetRcovalent(symbol) for symbol in frame.symbols]
    pairs = {}
    for i in range(len(radii)):
        for j in range(i + 1, len(radii)):
            distance = math.dist(frame.coordinates[i], frame.coordinates[j])
            ratio = distance / (radii[i] + radii[j])
            # A single cutoff can falsely identify a stretched IRC bond as
            # broken. Keep a conservative uncertainty band, including clashes.
            state = 'uncertain' if ratio < 0.6 or 1.2 <= ratio <= 1.5 else 'bonded' if ratio < 1.2 else 'separated'
            pairs[i + 1, j + 1] = {'distance': distance, 'state': state}
    return pairs


def _bond_orders(mol):
    return {tuple(sorted((b.GetBeginAtomIdx() + 1, b.GetEndAtomIdx() + 1))): b.GetBondTypeAsDouble()
            for b in mol.GetBonds()}


def _stereo(mol, chem):
    return dict((index + 1, tag) for index, tag in
                chem.FindMolChiralCenters(mol, includeUnassigned=True, useLegacyImplementation=False))


def compare_endpoint(endpoint, reference, charge):
    from rdkit import Chem
    from rdkit.Chem import rdDetermineBonds

    result = {'status': UNKNOWN, 'reasons': [], 'bond_differences': [],
              'ambiguous_bonds': [], 'proton_differences': [], 'stereo_differences': [],
              'resonance_equivalent': False, 'bond_differences_resonance_equivalent': False,
              'resonance_check': {'executed': False, 'status': 'not_checked',
                  'reason': '前置连接、电荷或推断检查尚未通过。',
                  'enumerated': {'endpoint': 0, 'reference': 0},
                  'limit': geo.RESONANCE_MAX_STRUCTURES, 'limit_reached': False}}
    left, right = endpoint['frame'], reference['frame']
    if left.symbols != right.symbols:
        result.update(status=MISMATCH, reasons=['元素序列或原子数不同，不能沿用原子编号映射'])
        return result
    for field in ('charge', 'multiplicity'):
        a, b = endpoint['facts'].get(field), reference['facts'].get(field)
        if a is not None and b is not None and a != b:
            result.update(status=MISMATCH, reasons=[f'{field} 不同：{a} / {b}'])
            return result
    try:
        pairs_a, pairs_b = _pairs(left, Chem), _pairs(right, Chem)
    except (ValueError, RuntimeError):
        result['reasons'].append('无法取得元素的共价半径，不能从 XYZ 推断连接')
        return result
    molecules = None
    if charge is not None:
        try:
            molecules = [geo.infer_molecule(f, charge, Chem, rdDetermineBonds) for f in (left, right)]
        except (ValueError, RuntimeError):
            pass
    def nonbonded_contact(pair):
        # Substituents of the same tetrahedral center can be within the
        # uncertainty band. A known 1-3 nonbonded contact in *both* graphs is
        # not a candidate bond; stretched reference bonds remain uncertain.
        if molecules is None:
            return False
        i, j = (index - 1 for index in pair)
        return all(mol.GetBondBetweenAtoms(i, j) is None and any(
            atom.GetAtomicNum() != 1 and mol.GetBondBetweenAtoms(atom.GetIdx(), j) is not None
            for atom in mol.GetAtomWithIdx(i).GetNeighbors()) for mol in molecules)
    for pair in pairs_a:
        a, b = pairs_a[pair], pairs_b[pair]
        item = {'atoms': list(pair), 'elements': [left.symbols[i - 1] for i in pair],
                'endpoint_distance': a['distance'], 'reference_distance': b['distance'],
                'endpoint_state': a['state'], 'reference_state': b['state']}
        if 'uncertain' in (a['state'], b['state']):
            if not nonbonded_contact(pair):
                result['ambiguous_bonds'].append(item)
        elif a['state'] != b['state']:
            result['bond_differences'].append(item)
    for i, symbol in enumerate(left.symbols, 1):
        if symbol != 'H':
            continue
        owners = []
        for pairs in (pairs_a, pairs_b):
            owners.append(sorted(j if i == k else k for (k, j), p in pairs.items()
                                 if i in (k, j) and p['state'] == 'bonded'
                                 and left.symbols[(j if i == k else k) - 1] != 'H'))
        if owners[0] != owners[1]:
            result['proton_differences'].append({'hydrogen': i, 'endpoint_owners': owners[0],
                                                'reference_owners': owners[1]})
    if result['bond_differences']:
        result.update(status=MISMATCH, reasons=['按原子编号比较的连接关系不同（见键长和质子归属）'])
        return result
    if result['ambiguous_bonds']:
        result['reasons'].append('存在拉长键或过近接触，XYZ 距离不能确定成键；保留候选连接')
        return result
    if charge is None:
        result['reasons'].append('缺少总电荷，无法可靠推断键级及立体身份')
        return result
    if molecules is None:
        result['reasons'].append('RDKit 无法从 XYZ 唯一推断价态/连接；需要结构审阅')
        return result
    a, b = molecules
    bonds_a, bonds_b = _bond_orders(a), _bond_orders(b)
    for pair in sorted(bonds_a.keys() | bonds_b.keys()):
        if bonds_a.get(pair) != bonds_b.get(pair):
            result['bond_differences'].append({'atoms': list(pair),
                'endpoint_order': bonds_a.get(pair), 'reference_order': bonds_b.get(pair),
                'endpoint_distance': pairs_a[pair]['distance'], 'reference_distance': pairs_b[pair]['distance']})
    stereo_a, stereo_b = _stereo(a, Chem), _stereo(b, Chem)
    for atom in sorted(stereo_a.keys() | stereo_b.keys()):
        if stereo_a.get(atom) != stereo_b.get(atom) or stereo_a.get(atom) == '?':
            result['stereo_differences'].append({'atom': atom, 'endpoint': stereo_a.get(atom),
                                                 'reference': stereo_b.get(atom)})
    result['graph_keys'] = {'endpoint': geo.graph_key(a, Chem), 'reference': geo.graph_key(b, Chem)}
    result['stereo_keys'] = {'endpoint': geo.stereo_key(a, Chem), 'reference': geo.stereo_key(b, Chem)}
    check = result['resonance_check'] = geo.resonance_equivalence(a, b, Chem)
    equivalent = check['status'] == 'equivalent'
    result['resonance_equivalent'] = equivalent
    result['bond_differences_resonance_equivalent'] = equivalent and bool(result['bond_differences'])
    stereo_differences = result['stereo_differences']
    stereo_key_mismatch = result['stereo_keys']['endpoint'] != result['stereo_keys']['reference']
    if equivalent:
        # Isomeric SMILES also contains localized bond orders/charges. Compare
        # both geometries in EACH proven representation so this difference
        # cannot masquerade as stereo, nor hide a center or E/Z double bond
        # present in only one representation. Raw keys remain in the report.
        normalized = []
        try:
            for label, template in (('endpoint', a), ('reference', b)):
                copies = []
                for original in (a, b):
                    mol = Chem.Mol(template)
                    mol.RemoveAllConformers()
                    mol.AddConformer(Chem.Conformer(original.GetConformer()))
                    Chem.RemoveStereochemistry(mol)
                    Chem.AssignStereochemistryFrom3D(mol, replaceExistingTags=True)
                    copies.append(mol)
                centers_a, centers_b = (_stereo(mol, Chem) for mol in copies)
                differences = [dict(atom=atom, endpoint=centers_a.get(atom), reference=centers_b.get(atom))
                    for atom in sorted(centers_a.keys() | centers_b.keys())
                    if centers_a.get(atom) != centers_b.get(atom) or centers_a.get(atom) == '?']
                normalized.append(dict(representation=label, stereo_differences=differences,
                    stereo_keys=dict(zip(('endpoint', 'reference'), (geo.stereo_key(mol, Chem) for mol in copies)))))
        except (ValueError, RuntimeError):
            result['resonance_stereo_check'] = dict(status='unknown', representations=normalized)
            result['reasons'].extend([check['reason'], '共振表示下的立体比较失败，不能确认构型一致。'])
            return result
        result['resonance_stereo_check'] = dict(status='evaluated', representations=normalized)
        stereo_differences = [row for item in normalized for row in item['stereo_differences']]
        stereo_key_mismatch = any(item['stereo_keys']['endpoint'] != item['stereo_keys']['reference']
                                  for item in normalized)
    representation_differs = (result['bond_differences'] or
        result['graph_keys']['endpoint'] != result['graph_keys']['reference'] or
        check['status'] == 'not_equivalent')
    if check['status'] == 'unknown':
        result['reasons'].append(check['reason'])
    elif representation_differs and not equivalent:
        result.update(status=MISMATCH, reasons=['推断的连接、键级或形式电荷不同'])
    elif any(item['endpoint'] in (None, '?') or item['reference'] in (None, '?') for item in stereo_differences):
        result['reasons'].append('至少一个立体中心无法指派，不能确认构型一致')
    elif stereo_differences or stereo_key_mismatch:
        result.update(status=MISMATCH, reasons=['立体中心或双键立体构型不同'])
    else:
        result.update(status=MATCH, reasons=['元素、按编号连接/键级、质子归属与可指派立体身份一致'])
    if equivalent:
        result['reasons'].append(check['reason'])
    return result


def compare(ts, forward, reverse, reactant, product):
    sources = {'ts': ts, 'forward': forward, 'reverse': reverse, 'reactant': reactant, 'product': product}
    issues = []
    for name, source in sources.items():
        if source['frame'].symbols != ts['frame'].symbols:
            issues.append(f'{name}: 元素序列与 TS 不同')
        for field in ('charge', 'multiplicity'):
            value, expected = source['facts'].get(field), ts['facts'].get(field)
            if value is not None and expected is not None and value != expected:
                issues.append(f'{name}: {field} 与 TS 不同')
    comparisons = {direction: {side: compare_endpoint(sources[direction], sources[side], ts['facts'].get('charge'))
                              for side in ('reactant', 'product')}
                   for direction in ('forward', 'reverse')}
    mappings = [{'forward': 'reactant', 'reverse': 'product'}, {'forward': 'product', 'reverse': 'reactant'}]
    def score(mapping):
        statuses = [comparisons[d][s]['status'] for d, s in mapping.items()]
        return statuses.count(MISMATCH), statuses.count(UNKNOWN)
    best = min(score(mapping) for mapping in mappings)
    selected = [mapping for mapping in mappings if score(mapping) == best]
    status = MISMATCH if issues or best[0] else UNKNOWN if best[1] else MATCH
    def changes(start, end):
        evidence = compare_endpoint(end, start, ts['facts'].get('charge'))
        for bond in evidence['bond_differences']:
            before = bond.get('reference_state', 'bonded' if bond.get('reference_order') else 'separated')
            after = bond.get('endpoint_state', 'bonded' if bond.get('endpoint_order') else 'separated')
            bond['change'] = 'formed' if before == 'separated' else 'broken' if after == 'separated' else 'order_changed'
        return {key: evidence[key] for key in ('bond_differences', 'ambiguous_bonds', 'proton_differences', 'stereo_differences',
            'resonance_check', 'resonance_equivalent', 'bond_differences_resonance_equivalent')}
    reaction_changes = {'reference_reactant_to_product': changes(reactant, product)}
    if len(selected) == 1:
        by_side = {side: sources[direction] for direction, side in selected[0].items()}
        reaction_changes['assigned_reactant_to_product'] = changes(by_side['reactant'], by_side['product'])
    return {'status': status, 'input_issues': issues,
            'assignment': selected[0] if len(selected) == 1 else None,
            'possible_assignments': selected, 'comparisons': comparisons, 'reaction_changes': reaction_changes,
            'sources': {name: {key: value for key, value in source.items() if key not in ('frame', 'facts')}
                        for name, source in sources.items()},
            'path_facts': {d: sources[d]['facts'].get('irc') for d in ('forward', 'reverse')},
            'ts_n_imag': ts['facts'].get('n_imag'),
            'units': {'distance': 'angstrom'},
            'distance_rule': {'bonded_below_covalent_radii_sum_factor': 1.2,
                              'uncertain_up_to_factor': 1.5, 'clash_below_factor': 0.6},
            'limitations': ['逐行原子编号作为映射；同元素原子交换须人工核对，未做原子重排。',
                            'XYZ 缺少电子态元数据时沿用 TS 总电荷推键；这不是电子态确认。',
                            '匹配仅为结构比对，不代表 IRC 验证、极小值确认或科学验收。',
                            '正常终止和路径完成标记不等于到达极小值；须审阅 MaxPoints、校正器、频率和模式。']}


def run(args):
    try:
        # The only write is exclusive creation of --out, after all analysis.
        if args.out.exists() or args.out.is_symlink():
            raise FileExistsError(f'Output already exists: {args.out}')
        sources = {key: load_source(getattr(args, key), args.study, allow_xyz=key in ('reactant', 'product'))
                   for key in ('ts', 'forward', 'reverse', 'reactant', 'product')}
        result = compare(**sources)
        content = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
        with args.out.open('x') as handle:
            handle.write(content)
        if args.json:
            print(content, end='')
        else:
            print(f'端点结构比对：{result["status"]}；报告：{args.out}')
            for mapping in result['possible_assignments']:
                for direction, side in mapping.items():
                    comparison = result['comparisons'][direction][side]
                    print(f'{direction} → {side}: {comparison["status"]}；'
                          f'{sources[direction]["optimization_note"]}；' + '；'.join(comparison['reasons']))
            for issue in result['input_issues']:
                print(issue)
        return 0
    except ImportError as exc:
        print(f'irc-compare requires RDKit: {exc}', file=sys.stderr)
        return 2


def register(subparsers):
    parser = subparsers.add_parser('irc-compare', description=__doc__)
    for key in ('ts', 'forward', 'reverse', 'reactant', 'product'):
        parser.add_argument('--' + key, required=True, help='Attempt ID/directory' + (' or XYZ' if key in ('reactant', 'product') else ''))
    parser.add_argument('--out', type=Path, required=True, help='New JSON report file; existing files are refused')
    parser.add_argument('--study', help='Study directory or configured study ID')
    parser.add_argument('--json', action='store_true')
    parser.set_defaults(func=run)
