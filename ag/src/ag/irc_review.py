"""Local per-direction IRC evidence checks; scientific review remains human."""

from hashlib import sha256
import json
import math
from pathlib import Path
import re

from ag import __version__, geometry as geo
from ag._irc import parse_irc_points
from ag._parse_outputs import _route_has, xyz_text
from ag._profile_sources import finite, protocol, require
from ag.asm import _attempt, _file, _geometry, _json, _path, _root, _xyz
from ag.ensemble import _Evidence
from ag.fragments import _write_outputs
from ag.irc_compare import MATCH, MISMATCH
from ag.scan_peak import ENERGY_JUMP_KCAL, RMSD_JUMP_ANGSTROM, aligned_rmsd
from ag.study import local_path
from ag.topology import _pair

NOTICE = '工具只核对和汇总；仍需人工审阅 SCF/电子态连续性和逐点几何，以及端点化学身份。'
READY = '工具核对完成，待人工审阅'
INCOMPLETE = 'IRC 未完成'


def _load(evidence, value, *, final=False):
    directory = _attempt(evidence.root, str(value))
    manifest = _json(evidence, directory / 'manifest.json')
    require(manifest.get('template') == 'gaussian', 'Expected a Gaussian Attempt')
    facts = _json(evidence, directory / 'facts.json')
    frame, science = _geometry(evidence, directory, manifest)
    require(protocol(facts.get('route')) == protocol(science['route']),
            f'{directory.name}: facts/input method protocol differs')
    result = dict(directory=directory, manifest=manifest, facts=facts, input=frame,
                  protocol=protocol(science['route']))
    if final:
        path = _file(directory, facts.get('final_geometry'))
        result.update(frame=_xyz(evidence, path), geometry_source=evidence.reference(path))
    return result


def _log_path(evidence, source):
    names = [item['name'] for item in source['manifest']['inputs'] if Path(item['name']).suffix.lower() in ('.gjf', '.com')]
    require(len(names) == 1, 'Expected one Gaussian input/log')
    return local_path(evidence.root, source['directory'] / 'outputs' / (Path(names[0]).stem + '.log'))


def _same_atoms(ts, frame):
    require(ts.symbols == frame.symbols, 'Atom count/element order differs from TS')


def _frame(text):
    lines = text.splitlines()
    rows = [line.split() for line in lines[2:]]
    require(len(rows) == int(lines[0]) and all(len(row) == 4 for row in rows), 'Invalid parsed IRC geometry')
    return geo.Frame(tuple(row[0] for row in rows), tuple(tuple(geo.finite_number(x) for x in row[1:]) for row in rows))


def _reference(evidence, value):
    if value is None:
        return None
    path = _path(evidence.root, value)
    if path.suffix.lower() == '.xyz':
        return dict(frame=_xyz(evidence, path), source=evidence.reference(path), identity=path)
    source = _load(evidence, value, final=True)
    return dict(frame=source['frame'], source=source['geometry_source'], identity=source['directory'])


def _distances(frame, pairs):
    return {f'{a}-{b}': math.dist(frame.coordinates[a - 1], frame.coordinates[b - 1]) for a, b in pairs}


def _fact(evidence, source, field):
    path = source['directory'] / 'facts.json'
    text = evidence.saved[path].decode()
    token = json.dumps(field) + ':'
    offset = text.find(token)
    return dict(value=source['facts'].get(field), source=evidence.reference(path), field=field,
                line=text.count('\n', 0, offset) + 1 if offset >= 0 else None)


def _identity_path(evidence, value):
    require(isinstance(value, str), 'irc-compare source is missing')
    return _path(evidence.root, value) if Path(value).suffix.lower() == '.xyz' else _attempt(evidence.root, value)


def _endpoint(evidence, endpoint, irc, last, comparison, direction, reference):
    if endpoint is None:
        return dict(status='unknown', reasons=['未提供末点 Opt+Freq Attempt'])
    require(last is not None and last['frame'] is not None,
            'Cannot associate endpoint optimization with a missing accepted path geometry')
    displacement = max(math.dist(a, b) for a, b in zip(endpoint['input'].coordinates, last['frame'].coordinates))
    parents = endpoint['manifest'].get('parents', [])
    graph_match = any(p.get('attempt_id') == irc['directory'].name and p.get('relation') == 'endpoint_of'
                      for p in parents)
    # A declared parent can be wrong; it cannot excuse a different structure.
    # Fixed-row rigid alignment permits a changed coordinate frame only.
    rmsd = aligned_rmsd(endpoint['input'], last['frame'])
    coordinate_match = displacement <= 1e-4
    require(coordinate_match or (graph_match and rmsd <= 1e-3),
            'Endpoint input geometry differs from last accepted point; require displacement <= 1e-4 Å '
            'or endpoint_of provenance AND aligned RMSD <= 1e-3 Å '
            f'(displacement={displacement:.6g} Å, aligned RMSD={rmsd:.6g} Å)')
    fields = ('termination', 'opt_converged', 'freq_step_converged',
              'vibrational_modes_complete', 'n_vibrational_modes', 'expected_vibrational_modes', 'n_imag')
    facts = endpoint['facts']
    require(_route_has(facts['route'], 'opt') and _route_has(facts['route'], 'freq'),
            'Endpoint must be an independent Opt+Freq Attempt')
    checks = [_fact(evidence, endpoint, key) for key in fields]
    expected = {'termination': 'normal', 'opt_converged': True, 'freq_step_converged': True,
                'vibrational_modes_complete': True, 'n_imag': 0}
    failed = [key for key, value in expected.items() if facts.get(key) is not None
              and (facts[key] != value or type(facts[key]) is not type(value))]
    missing = [key for key in fields if facts.get(key) is None]
    counts = [facts.get(key) for key in ('n_vibrational_modes', 'expected_vibrational_modes')]
    if not any(value is None for value in counts) and (
            any(type(value) is not int or value < 0 for value in counts) or counts[0] != counts[1]):
        failed.append('mode_count')
    identity = dict(status='unknown', reason='未提供 irc-compare 报告')
    if comparison is not None:
        data, source = comparison
        referenced = _identity_path(evidence, data.get('sources', {}).get(direction, {}).get('source'))
        require(referenced == endpoint['directory'], 'irc-compare references a different endpoint Attempt')
        assignment = data.get('assignment') or {}
        side = assignment.get(direction)
        status = (data.get('comparisons', {}).get(direction, {}).get(side, {}).get('status')
                  if side in ('reactant', 'product') else None)
        # A positive comparison against another hypothesis cannot support this reference.
        if side is not None and reference is not None:
            expected_source = _identity_path(evidence, data.get('sources', {}).get(side, {}).get('source'))
            require(expected_source == reference['identity'], 'irc-compare reference differs from the expected endpoint reference')
        if data.get('input_issues'):
            status = MISMATCH
        if status is None and data.get('status') == MISMATCH:
            status = MISMATCH
        identity = dict(status='met' if status == MATCH else 'not_met' if status == MISMATCH else 'unknown',
                        reported_status=status, side=side, source=source,
                        field=f'comparisons.{direction}.{side}.status')
    log = _log_path(evidence, endpoint)
    log_source, log_lines = None, {}
    if log.is_file():
        text = evidence.read(log).decode(errors='replace')
        log_source = evidence.reference(log)
        # Lookup anchors only; the existing section-aware facts own the verdict.
        patterns = {'termination': r'^\s*(?:Normal termination of Gaussian|Error termination)',
                    'optimization': r'^\s*(?:Optimization completed|Stationary point found)',
                    'frequency': r'^\s*(?:Harmonic frequencies|Frequencies\s+--)'}
        log_lines = {key: [i for i, line in enumerate(text.splitlines(), 1) if re.search(pattern, line)]
                     for key, pattern in patterns.items()}
    status = ('not_met' if failed or identity['status'] == 'not_met' else
              'unknown' if missing or identity['status'] == 'unknown' else 'met')
    return dict(status=status, facts=checks, failed_fields=failed, missing_fields=missing, identity=identity,
                log=log_source, log_lines=log_lines, frequency_convergence=_fact(evidence, endpoint, 'freq_step_convergence'),
                fact_sources=facts.get('fact_sources'), job_sections=facts.get('job_sections'),
                input_max_displacement_angstrom=displacement, input_aligned_rmsd_angstrom=rmsd,
                provenance='coordinates' if coordinate_match else 'endpoint_of_and_alignment',
                provenance_note='坐标一致' if coordinate_match else '来源关系加对齐核对',
                manifest=evidence.reference(endpoint['directory'] / 'manifest.json'),
                reasons=failed + [f'缺少 {key}' for key in missing] + ([] if identity['status'] == 'met' else ['端点身份未确认']))


def _midpoint(ts, last, reference, pairs):
    if reference is None:
        return dict(status='unknown', reasons=['未提供预期端点 reference'], pairs=[])
    rows = []
    ts_distances = _distances(ts, pairs)
    expected = _distances(reference['frame'], pairs)
    actual = _distances(last['frame'], pairs) if last is not None and last['frame'] is not None else {}
    for pair, distance in ts_distances.items():
        target, end = expected[pair], actual.get(pair)
        middle = (distance + target) / 2
        forming = target < distance
        status = ('unknown' if abs(target - distance) < .05 or end is None else
                  'met' if (end < middle if forming else end > middle) else 'not_met')
        rows.append(dict(pair=pair, ts_angstrom=distance, last_angstrom=end, reference_angstrom=target,
                         midpoint_angstrom=middle, change='forming' if forming else 'breaking', status=status,
                         reason='预期与 TS 相差小于 0.05 Å，不能区分' if abs(target - distance) < .05 else
                         '缺少末点几何' if end is None else '按严格中点不等式核对'))
    status = 'not_met' if any(r['status'] == 'not_met' for r in rows) else 'unknown' if any(r['status'] == 'unknown' for r in rows) else 'met'
    return dict(status=status, pairs=rows, reference=reference['source'])


def _continuity(parsed, points, noise):
    facts, lines = parsed['facts'], parsed['evidence_lines']
    failures, missing, steps = [], [], []
    if facts['corrector_failed']:
        failures.append('corrector_failed')
    if lines['error_termination']:
        failures.append('error_termination')
    complete = facts['path_complete_reported'] or facts['reached_max_points'] is True
    if not complete or not lines['normal_termination']:
        missing.append('输出截断或缺少路径完成/MaxPoints 与正常结束证据')
    if len(points) <= 1:
        missing.append('没有已接受的非零路径点')
    for point in points:
        if point['energy_hartree'] is None or point['frame'] is None:
            missing.append(f"点 {point['point']} 缺少能量或几何")
    if [p['point'] for p in points] != list(range(len(points))):
        missing.append('路径点号不连续')
    for left, right in zip(points, points[1:]):
        delta = ((right['energy_hartree'] - left['energy_hartree']) * geo.HARTREE_TO_KCAL
                 if left['energy_hartree'] is not None and right['energy_hartree'] is not None else None)
        rmsd = aligned_rmsd(left['frame'], right['frame']) if left['frame'] is not None and right['frame'] is not None else None
        row = dict(points=[left['point'], right['point']], energy_change_kcal_mol=delta,
                   rmsd_angstrom=rmsd, energy_lines=[left['energy_line'], right['energy_line']],
                   geometry_lines=[left['geometry_line'], right['geometry_line']])
        steps.append(row)
        if delta is not None and delta > noise:
            failures.append(f"点 {left['point']}→{right['point']} 能量回升")
        if (delta is not None and abs(delta) > ENERGY_JUMP_KCAL) or (rmsd is not None and rmsd > RMSD_JUMP_ANGSTROM):
            failures.append(f"点 {left['point']}→{right['point']} 能量或 RMSD 跳变")
    return dict(status='not_met' if failures else 'unknown' if missing else 'tool_checks_passed',
                reasons=failures + missing, manual_review=NOTICE, steps=steps, evidence_lines=lines,
                corrector_failed=facts['corrector_failed'], path_complete_reported=facts['path_complete_reported'],
                reached_max_points=facts['reached_max_points'], max_points=facts['max_points'])


def _direction(evidence, ts, irc, endpoint, reference, comparison, direction, pairs, threshold, noise, xyz_name):
    log = _log_path(evidence, irc)
    parsed = parse_irc_points(evidence.read(log).decode(errors='replace'))
    require(parsed is not None, 'Not an IRC log')
    require(parsed['facts']['direction'] != 'both', 'direction: both; use independent forward/reverse Attempts')
    require(parsed['facts']['direction'] == direction, f'IRC log direction does not match {direction}')
    require(len({point['path'] for point in parsed['points']}) <= 1, 'Multiple IRC paths in one log; use independent Attempts')
    log_source = evidence.reference(log)
    points = parsed['points']
    if not points or points[0]['point'] != 0:
        points.insert(0, dict(point=0, path=None, point_line=None, energy_hartree=None, energy_line=None,
                              energy_kind=None, geometry=None, geometry_line=None, geometry_kind=None))
    frames = []
    for point in points:
        frame = _frame(point.pop('geometry')) if point['geometry'] is not None else None
        if point['point'] == 0 and frame is None:
            # RCFC can start from checkpoint energy without an orientation table.
            frame = irc['input']
            point['geometry_kind'] = 'irc_input'
        if frame is not None:
            _same_atoms(ts['frame'], frame)
        point['frame'] = frame
        point['geometry_frame'] = len(frames) if frame is not None else None
        if frame is not None:
            frames.append(frame)
        point['distances_angstrom'] = _distances(frame, pairs) if frame else None
    start = points[0]['energy_hartree']
    ts_energy = ts['facts'].get('energies', {}).get('scf')
    if ts_energy is not None:
        ts_energy = finite(ts_energy, 'TS electronic energy')
    warnings = []
    if start is not None and ts_energy is not None and abs(start - ts_energy) > 1e-5:
        warnings.append('IRC 第 0 点与 TS facts 电子能相差超过 1e-5 Hartree；降能以各侧第 0 点为准')
    for point in points:
        point['relative_energy_kcal_mol'] = ((point['energy_hartree'] - start) * geo.HARTREE_TO_KCAL
                                            if start is not None and point['energy_hartree'] is not None else None)
    last = points[-1] if len(points) > 1 else None
    continuity = _continuity(parsed, points, noise)
    midpoint = _midpoint(ts['frame'], last, reference, pairs)
    midpoint.update(ts=ts['geometry_source'], last_point_line=last['geometry_line'] if last else None, log=log_source)
    endpoint_check = _endpoint(evidence, endpoint, irc, last, comparison, direction, reference)
    drop = -last['relative_energy_kcal_mol'] if last and last['relative_energy_kcal_mol'] is not None else None
    energy_status = ('unknown' if drop is None else 'met' if drop >= threshold else
                     'met_by_endpoint_optimization' if drop > 0 and continuity['status'] == 'tool_checks_passed'
                     and midpoint['status'] == endpoint_check['status'] == 'met' else 'not_met')
    energy = dict(status=energy_status, drop_kcal_mol=drop, threshold_kcal_mol=threshold,
                  start_energy_hartree=start, last_energy_hartree=last['energy_hartree'] if last else None,
                  energy_lines=[points[0]['energy_line'], last['energy_line'] if last else None], log=log_source,
                  reason='由端点优化补证；阈值未调低' if energy_status == 'met_by_endpoint_optimization' else '按实际路径末点电子能降幅核对')
    criteria = dict(continuity=continuity, energy_drop=energy, midpoint=midpoint, endpoint=endpoint_check)
    unresolved = [key for key, value in criteria.items() if value['status'] not in ('tool_checks_passed', 'met', 'met_by_endpoint_optimization')]
    facts = parsed['facts']
    reason = ('corrector_failed' if facts['corrector_failed'] else
              'truncated' if not parsed['evidence_lines']['normal_termination'] or parsed['evidence_lines']['error_termination'] else
              'max_points' if facts['reached_max_points'] else 'completed' if facts['path_complete_reported'] else 'truncated')
    exported = [{k: v for k, v in point.items() if k not in ('frame', 'geometry')} for point in points]
    return dict(attempt=irc['directory'].name, log=log_source, criteria=criteria, points=exported,
                stop_reason=reason, last_accepted_point=last['point'] if last else None,
                summary=INCOMPLETE if unresolved else READY, unresolved=unresolved, warnings=warnings,
                ts_reference=dict(irc_point_zero_hartree=start, ts_facts_hartree=ts_energy,
                                  difference_hartree=start - ts_energy if start is not None and ts_energy is not None else None,
                                  ts_facts=evidence.reference(ts['directory'] / 'facts.json')),
                path_geometry=dict(path=xyz_name, frame_index_base=0, frame_count=len(frames))), frames


def review(*, ts, forward, reverse, pairs, out, study=None, forward_reference=None, reverse_reference=None,
           forward_endpoint=None, reverse_endpoint=None, irc_compare=None, energy_threshold=3.0, energy_noise=.01):
    threshold = finite(energy_threshold, 'energy threshold', positive=True)
    noise = finite(energy_noise, 'energy noise')
    require(noise >= 0, 'energy noise must be non-negative')
    root = _root(study, ts)
    evidence = _Evidence(root)
    target = Path(out).expanduser()
    target = target if target.is_absolute() else root / target
    # Normal outputs belong in analyses; external reports support read-only
    # validation of signed studies (T79), never an input escape or study write.
    local_path(Path(target.anchor), target)
    if target.is_relative_to(root):
        local_path(root / 'analyses', target)
    require(target.suffix == '.json', '--out must be a new .json report')
    targets = [target, target.with_suffix('.md'), target.with_suffix('.forward.xyz'), target.with_suffix('.reverse.xyz')]
    for path in targets:
        local_path(Path(path.anchor), path)
        if path.exists():
            raise FileExistsError(f'Output already exists: {path.name}')
    source_ts = _load(evidence, ts, final=True)
    sources = {d: _load(evidence, value) for d, value in [('forward', forward), ('reverse', reverse)]}
    require(len({source_ts['directory'], *(s['directory'] for s in sources.values())}) == 3,
            'TS and both IRC directions must be independent Attempts')
    references = {d: _reference(evidence, value) for d, value in [('forward', forward_reference), ('reverse', reverse_reference)]}
    endpoints = {d: _load(evidence, value, final=True) if value is not None else None
                 for d, value in [('forward', forward_endpoint), ('reverse', reverse_endpoint)]}
    for source in [source_ts, *sources.values(), *(s for s in endpoints.values() if s is not None)]:
        require(source['protocol'] == source_ts['protocol'], 'Method protocol differs from TS')
        _same_atoms(source_ts['frame'], source['input'])
        if 'frame' in source:
            _same_atoms(source_ts['frame'], source['frame'])
    for reference in references.values():
        if reference is not None:
            _same_atoms(source_ts['frame'], reference['frame'])
    pairs = sorted(set(_pair(value) for value in pairs))
    require(pairs and all(b <= len(source_ts['frame'].symbols) for a, b in pairs), 'At least one valid --pair is required')
    comparison = None
    if irc_compare is not None:
        path = local_path(root / 'analyses', _path(root, irc_compare))
        data = _json(evidence, path)
        require(_identity_path(evidence, data.get('sources', {}).get('ts', {}).get('source')) == source_ts['directory'],
                'irc-compare references a different TS Attempt')
        comparison = data, evidence.reference(path)
    directions, payloads = {}, {}
    for direction in ('forward', 'reverse'):
        xyz = target.with_suffix(f'.{direction}.xyz')
        directions[direction], frames = _direction(evidence, source_ts, sources[direction], endpoints[direction], references[direction],
                                                   comparison, direction, pairs, threshold, noise, xyz.name)
        payloads[xyz.name] = ''.join(xyz_text(f.symbols, f.coordinates) for f in frames).encode()
        directions[direction]['path_geometry']['sha256'] = sha256(payloads[xyz.name]).hexdigest()
    result = dict(schema='ag-irc-review/1', ag_version=__version__, notice=NOTICE,
                  ts=source_ts['directory'].name, protocol=source_ts['protocol'], pairs=[list(p) for p in pairs],
                  units=dict(energy='hartree', relative_energy='kcal/mol', distance='angstrom'),
                  thresholds=dict(energy_drop_kcal_mol=threshold, energy_noise_kcal_mol=noise,
                                  energy_jump_kcal_mol=ENERGY_JUMP_KCAL, rmsd_jump_angstrom=RMSD_JUMP_ANGSTROM,
                                  indistinguishable_pair_angstrom=.05, endpoint_input_angstrom=1e-4,
                                  endpoint_aligned_rmsd_angstrom=1e-3),
                  directions=directions, inputs=[evidence.reference(path) for path in sorted(evidence.saved)])
    evidence.verify()
    payloads[target.name] = (json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode()
    payloads[target.with_suffix('.md').name] = markdown(result).encode()
    _write_outputs(target.parent, payloads)
    return result


def markdown(result):
    lines = ['# IRC 逐方向核对', '', result['notice'], '']
    for direction, item in result['directions'].items():
        lines.extend([f'## {direction}: {item["summary"]}', '',
                      f'停止原因：{item["stop_reason"]}；最后已接受点：{item["last_accepted_point"]}', '',
                      '| 判据 | 状态 |', '| --- | --- |'])
        lines.extend(f'| {key} | {value["status"]} |' for key, value in item['criteria'].items())
        lines.extend(['', '未满足或无法确定：' + ', '.join(item['unresolved']), *item['warnings'], '',
                      '数值、来源与行号（日志行号从 1 开始；缺失为 null）：', '```json',
                      json.dumps({key: item[key] for key in ('log', 'ts_reference', 'criteria')}, ensure_ascii=False, indent=2), '```', ''])
    lines.extend(['## 输入文件 SHA-256', '', '```json', json.dumps(result['inputs'], ensure_ascii=False, indent=2), '```'])
    return '\n'.join(lines) + '\n'


def run(args):
    result = review(**{key: getattr(args, key) for key in (
        'ts', 'forward', 'reverse', 'out', 'study', 'forward_reference', 'reverse_reference',
        'forward_endpoint', 'reverse_endpoint', 'irc_compare', 'energy_threshold', 'energy_noise')}, pairs=args.pair)
    for direction, item in result['directions'].items():
        print(f'{direction}: {item["summary"]}')
    print(f'报告：{args.out}')
    return 0


def register(subparsers):
    parser = subparsers.add_parser('irc-review', description=__doc__)
    for key in ('ts', 'forward', 'reverse'):
        parser.add_argument('--' + key, required=True, help='Attempt ID or directory in the same study')
    for direction in ('forward', 'reverse'):
        parser.add_argument(f'--{direction}-reference', help='Expected endpoint Attempt or XYZ in this study')
        parser.add_argument(f'--{direction}-endpoint', help='Independent endpoint Opt+Freq Attempt')
    parser.add_argument('--pair', action='append', required=True, help='1-based target atom pair I-J; repeatable')
    parser.add_argument('--irc-compare', help='Existing irc-compare report under study analyses/')
    parser.add_argument('--energy-threshold', type=float, default=3.0)
    parser.add_argument('--energy-noise', type=float, default=.01, help='Allowed upward numerical noise, kcal/mol')
    parser.add_argument('--out', type=Path, required=True, help='New .json under analyses/ or outside study for read-only validation')
    parser.add_argument('--study', help='Study directory')
    parser.set_defaults(func=run)
