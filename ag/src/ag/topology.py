"""Report submitted/final topology or declared TS distances without changing evidence."""
from hashlib import sha256
import json
import math
from pathlib import Path
import re

from ag import __version__, geometry as geo
from ag.facts import ag_provenance
from ag.irc_compare import MATCH, MISMATCH, UNKNOWN, _attempt, _pairs, compare_endpoint

NOTICE = '结构比较不代替科学审阅'
DIFFERENCES = ('bond_differences', 'ambiguous_bonds', 'proton_differences', 'stereo_differences')


def _read(path):
    if path.is_symlink():
        raise ValueError(f'{path.name}: expected a regular source file, not a symlink')
    data = path.read_bytes()
    return data, {'file': path.name, 'sha256': sha256(data).hexdigest()}


def _frame(text):
    # Same canonicalization as scan inputs, including Gaussian atomic numbers.
    from ag._scan import input_geometry
    symbols, coordinates = input_geometry(text)
    if not symbols or any(len(row) != 3 for row in coordinates):
        raise ValueError('Missing or invalid submitted Cartesian geometry')
    return geo.Frame(tuple(symbols), tuple(tuple(row) for row in coordinates))


def _ts_route(route):
    options = [word.lower() for match in re.finditer(
        r'\bopt\b\s*(?:=\s*)?(\([^()]*\)|[A-Za-z0-9]+)', route, re.I)
        for word in re.findall(r'\b[A-Za-z][A-Za-z0-9]*\b', match[1])]
    return any(word in options for word in ('ts', 'qst2', 'qst3'))


def _pair(value):
    if not re.fullmatch(r'[1-9]\d*-[1-9]\d*', value):
        raise ValueError('--pair requires two distinct 1-based indices: i-j')
    pair = tuple(map(int, value.split('-')))
    if pair[0] == pair[1]:
        raise ValueError('--pair indices must be distinct')
    return tuple(sorted(pair))


def _contacts(frame):
    from rdkit import Chem
    table = Chem.GetPeriodicTable()
    result = {element: [] for element in ('B', 'N', 'O')}
    for pair, evidence in _pairs(frame, Chem).items():
        elements = [frame.symbols[i - 1] for i in pair]
        ratio = evidence['distance'] / sum(table.GetRcovalent(e) for e in elements)
        if 1.2 <= ratio <= 1.5:
            for element in result.keys() & set(elements):
                result[element].append(dict(atoms=list(pair), elements=elements,
                                            distance=evidence['distance'], covalent_radius_ratio=ratio))
    return result


def compare_minimum(submitted, final, charge):
    result = dict(status='unknown', reasons=[], **{key: [] for key in DIFFERENCES})
    result['bond_order_and_stereo_assessment'] = {
        'status': 'unknown', 'reason': '比较尚未完成；空差异列表不表示已确认一致。'}
    if submitted.symbols != final.symbols:
        result['reasons'].append('元素序列或原子数不同，不能沿用原子编号映射；不做重排。')
        return result
    try:
        evidence = compare_endpoint({'frame': final, 'facts': {}},
                                    {'frame': submitted, 'facts': {}}, charge)
        result.update(evidence)
        result['status'] = {MATCH: 'unchanged', MISMATCH: 'changed', UNKNOWN: 'unknown'}[evidence['status']]
        if 'stereo_keys' in evidence:
            unresolved = any(row['endpoint'] in (None, '?') or row['reference'] in (None, '?')
                             for row in evidence['stereo_differences'])
            result['bond_order_and_stereo_assessment'] = {
                'status': 'unknown' if unresolved else 'evaluated',
                'reason': '存在无法指派的立体中心。' if unresolved else 'RDKit 已推断键级与可指派立体身份；见差异。'}
        else:
            result['bond_order_and_stereo_assessment']['reason'] = (
                '未完成键级/立体身份比较（距离差异、不确定接触、缺电荷或 RDKit 推断失败）；'
                '不能从空列表推断立体不变。' + '；'.join(evidence['reasons']))
        result['uncertain_contacts'] = {'submitted': _contacts(submitted), 'final': _contacts(final)}
    except ImportError:
        result['reasons'].append('RDKit 不可用，不能推断成键、键级及立体身份。')
    except (ValueError, RuntimeError):
        result['status'] = 'unknown'
        result['reasons'].append('RDKit 无法取得共价半径或推断结构；需要人工审阅。')
    return result


def analyze(path, pairs=()):
    manifest_bytes, manifest_source = _read(path / 'manifest.json')
    facts_bytes, facts_source = _read(path / 'facts.json')
    manifest, facts = json.loads(manifest_bytes), json.loads(facts_bytes)
    science = manifest.get('science', {})
    charge = science.get('charge')
    if type(charge) is not int:
        charge = None
    route = science.get('route', '')
    mode = 'ts_distances' if facts.get('n_imag') == 1 and _ts_route(route) else 'minimum'
    groups = science.get('structures') or [science]
    if len(groups) not in (1, 2, 3):
        raise ValueError('Expected one submitted geometry or two/three QST groups')
    references = []
    for i, group in enumerate(groups):
        pointer = f'/science/structures/{i}/geometry' if science.get('structures') else '/science/geometry'
        references.append(dict(group=i + 1, geometry_pointer=pointer,
                               role=('reactant', 'product', 'ts_guess')[i] if len(groups) > 1 else 'submitted',
                               frame=_frame(group.get('geometry', ''))))
    final_path = path / 'final_input.xyz'
    fallback = not (final_path.exists() or final_path.is_symlink())
    if fallback:
        final_path = path / 'final.xyz'
    final_bytes, final_source = _read(final_path)
    frames = geo.read_xyz(final_path)
    # Do not attach an old hash if evidence changes while it is being parsed.
    if _read(final_path)[0] != final_bytes:
        raise ValueError('Final geometry changed during reading; no report written')
    if len(frames) != 1:
        raise ValueError('Final geometry must contain exactly one XYZ frame')
    final = frames[0]
    result = dict(status='unknown', mode=mode, reasons=[], **{key: [] for key in DIFFERENCES},
                  attempt=manifest.get('attempt_id', path.name), charge=charge,
                  ag_version=__version__, ag_provenance=ag_provenance(),
                  atom_numbering='1-based; input row order; no atom reordering',
                  units={'distance': 'angstrom'},
                  sources={'submitted': dict(manifest_source, geometries=[
                      {key: value for key, value in item.items() if key != 'frame'} for item in references]),
                      'final': final_source, 'facts': facts_source},
                  orientation_note=('缺少 final_input.xyz，使用 final.xyz；取向可能不同，不影响拓扑判断。'
                                    if fallback else '使用 final_input.xyz；沿用输入原子行序。'),
                  distance_rule={'bonded_below_covalent_radii_sum_factor': 1.2,
                                 'uncertain_up_to_factor': 1.5, 'clash_below_factor': 0.6,
                                 'contact_ratio_inclusive': [1.2, 1.5],
                                 'applied': mode == 'minimum'},
                  field_meanings={'endpoint': 'final geometry', 'reference': 'submitted geometry'},
                  notice=NOTICE,
                  limitations=['同元素原子交换无法由元素序列检测，须人工核对原子映射。',
                               'unchanged 不是极小点确认；仍需频率与科学审阅。'])
    if any(item['frame'].symbols != final.symbols for item in references):
        result['reasons'].append('元素序列或原子数不同，不能沿用原子编号映射；不做重排。')
        return result
    # Prevent interpreting non-angstrom inputs with angstrom radii/distances.
    if re.search(r'\bunits?\b', route, re.I):
        result['reasons'].append('输入声明了 Units；当前比较仅支持默认 Å 坐标，需人工核对单位。')
        return result
    parsed_pairs = sorted(set(_pair(value) for value in pairs))
    if any(max(pair) > len(final.symbols) for pair in parsed_pairs):
        raise ValueError('--pair atom index out of range')
    if mode == 'ts_distances':
        result['pair_distances'] = []
        result['reasons'].append('TS 模式只报告声明原子对的距离，不判定连接关系。')
        if not parsed_pairs:
            result['reasons'].append('需要用 --pair i-j 声明成键或断键原子对。')
        for reference in references:
            for i, j in parsed_pairs:
                before = math.dist(reference['frame'].coordinates[i - 1], reference['frame'].coordinates[j - 1])
                after = math.dist(final.coordinates[i - 1], final.coordinates[j - 1])
                result['pair_distances'].append(dict(atoms=[i, j], elements=[final.symbols[i - 1], final.symbols[j - 1]],
                    submitted_group=reference['group'], submitted_role=reference['role'],
                    submitted_distance=before, final_distance=after, change=after - before))
        result['distance_report_status'] = 'reported' if parsed_pairs else 'unknown'
    elif len(references) != 1:
        result['reasons'].append('QST 有多组提交几何且未满足 TS 模式条件，不能选定唯一极小点参考。')
    else:
        result.update(compare_minimum(references[0]['frame'], final, charge))
    return result


def markdown(result):
    lines = ['# 优化前后结构比较', '', NOTICE, '',
             f"- 状态：{result['status']}；模式：{result['mode']}",
             f"- ag：{result['ag_version']}；提交：{result['ag_provenance']['git_commit'] or 'unknown'}；"
             f"dirty：{result['ag_provenance']['dirty']}",
             '- 原子编号从 1 开始；不做原子重排。距离单位：Å。',
             '- ' + result['orientation_note'],
             '- endpoint 表示最终几何，reference 表示提交几何。',
             '- 阈值：半径比 < 0.6 为过近接触；[0.6, 1.2) 相连；[1.2, 1.5] 不确定；> 1.5 分离。',
             '- TS 模式不使用上述成键判定阈值。', '', '## 来源与 SHA-256', '']
    for role, source in result['sources'].items():
        lines.append(f"- {role}：`{source['file']}`；SHA-256 `{source['sha256']}`")
    lines.extend(['', '## 判定说明', ''] + ['- ' + item for item in result['reasons'] + result['limitations']])
    # Include complete evidence so the Markdown alone is reviewable.
    for field in ('geometries', *DIFFERENCES, 'bond_order_and_stereo_assessment',
                  'graph_keys', 'stereo_keys', 'uncertain_contacts', 'pair_distances', 'distance_report_status'):
        value = result['sources']['submitted'].get(field) if field == 'geometries' else result.get(field)
        if value is not None:
            lines.extend(['', f'## {field}', '', '```json', json.dumps(value, ensure_ascii=False, indent=2), '```'])
    return '\n'.join(lines) + '\n'


def run(args):
    out = args.out
    if out.suffix.lower() != '.json':
        raise ValueError('--out must name a new .json report')
    summary = out.with_suffix('.md')
    for target in (out, summary):
        if target.exists() or target.is_symlink():
            raise FileExistsError(f'Output already exists: {target}')
    try:
        result = analyze(_attempt(args.attempt, args.study), args.pair)
    except ImportError as exc:
        raise ValueError('topology requires the local chemistry dependencies') from exc
    content = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    # Both handles are exclusively created before writing either report.
    with out.open('x', encoding='utf-8') as json_file, summary.open('x', encoding='utf-8') as md_file:
        json_file.write(content)
        md_file.write(markdown(result))
    if args.json:
        print(content, end='')
    else:
        print(f"结构比较：{result['status']}；报告：{out}；摘要：{summary}。{NOTICE}")
    return 0


def register(subparsers):
    parser = subparsers.add_parser('topology', description=__doc__)
    parser.add_argument('attempt', help='Attempt ID or directory')
    parser.add_argument('--study', help='Study directory or configured study ID')
    parser.add_argument('--out', type=Path, required=True, help='New JSON report; a new .md summary is also created')
    parser.add_argument('--pair', action='extend', nargs='+', default=[], help='1-based atom pairs i-j; repeatable')
    parser.add_argument('--json', action='store_true')
    parser.set_defaults(func=run)
