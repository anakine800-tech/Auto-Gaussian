"""Summarize saved conformer evidence without selecting or accepting candidates."""

from datetime import datetime, timezone
from hashlib import sha256
import json
import math
from pathlib import Path
import re
import sys
import tomllib

from ag import coverage, geometry as geo
from ag.dedup import descriptor_definitions, frame_descriptors
from ag.facts import ag_provenance, resolve_attempt
from ag.fragments import _write_outputs
from ag.study import identifier, local_path


def _number(value):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('Expected a finite numeric value or null')
    return value


def _positive(value):
    if type(value) is not int or value < 1:
        raise ValueError('Expected a positive frame/candidate number')
    return value


def _root(merged, study):
    if study:
        root = Path(study).expanduser().absolute()
        local_path(Path(root.anchor), root)
        if not root.is_dir():
            identifier(study)
            with (Path.home() / '.config/ag/config.toml').open('rb') as stream:
                root = Path(tomllib.load(stream)['local']['studies_root']).expanduser() / study
    else:
        path = Path(merged).expanduser().absolute()
        local_path(Path(path.anchor), path)
        analyses = next((p for p in path.parents if p.name == 'analyses'), None)
        if analyses is None:
            raise ValueError('Supply --study or a merged path under study analyses/')
        root = analyses.parent
    root = local_path(root, root)
    if not local_path(root, root / 'study.md').is_file():
        raise ValueError('Expected a study directory with study.md')
    identifier(root.name)
    return root


def _path(root, value):
    path = Path(value).expanduser()
    return local_path(root, path if path.is_absolute() else root / path)


class _Evidence:
    """Bind bytes and reject changes during collection instead of mixing revisions."""

    def __init__(self, root):
        self.root, self.saved = root, {}

    def read(self, path):
        path = local_path(self.root, path)
        raw = path.read_bytes()
        if path in self.saved and self.saved[path] != raw:
            raise ValueError('Evidence changed during collection')
        self.saved[path] = raw
        return raw

    def json(self, path):
        return json.loads(self.read(path))

    def reference(self, path):
        return {'path': path.relative_to(self.root).as_posix(),
                'sha256': sha256(self.saved[path]).hexdigest()}

    def verify(self):
        for path, raw in self.saved.items():
            if local_path(self.root, path).read_bytes() != raw:
                raise ValueError('Evidence changed during collection')


def _attempt(evidence, value):
    identifier(value)  # IDs only: never let resolve_attempt probe an external directory.
    path = local_path(evidence.root, evidence.root / 'attempts' / value)
    manifest = evidence.json(path / 'manifest.json')
    if resolve_attempt(str(path), str(evidence.root)) != path:
        raise ValueError('Attempt resolution differs from study path')
    return path, manifest


def _geometry(evidence, path, manifest):
    for item in manifest['inputs']:
        name = item['name']
        if not isinstance(name, str) or Path(name).name != name or name in {'.', '..'}:
            raise ValueError('Input must be a plain filename')
        if Path(name).suffix.lower() in {'.gjf', '.com'}:
            evidence.read(path / 'inputs' / name)
    return coverage.input_geometry(path)


def _frame_hashes(raw):
    lines, cursor, hashes = raw.splitlines(keepends=True), 0, []
    while cursor < len(lines):
        if not lines[cursor].strip():
            cursor += 1
            continue
        count = int(lines[cursor])
        if count < 1 or cursor + count + 2 > len(lines):
            raise ValueError('Empty or truncated XYZ frame')
        hashes.append(sha256(b''.join(lines[cursor + 2:cursor + 2 + count])).hexdigest())
        cursor += count + 2
    return hashes


def _route_members(payload):
    # dedup's relative_energy_kcal is null in geometry-only mode and global in
    # lowest mode. Rebase saved member energies separately within each route.
    members = [m for r in payload['kept'] for m in r['members']]
    minima, units = {}, {}
    for row in members + payload.get('excluded', []):
        routes = [row['route']] if 'route' in row else row.get('sources', [])
        energy = _number(row.get('energy'))
        for route in routes:
            if route not in payload['routes']:
                raise ValueError('Member route is absent from merged routes')
            if energy is None:
                continue
            unit = row['energy_unit']
            if unit not in {'hartree', 'kcal/mol'} or units.get(route, unit) != unit:
                raise ValueError('Inconsistent energy units within a route')
            units[route] = unit
            minima[route] = min(minima.get(route, energy), energy)
    result = []
    for record in payload['kept']:
        rows = []
        for member in record['members']:
            route, energy = member['route'], _number(member.get('energy'))
            relative = None if energy is None else (energy - minima[route]) * (
                geo.HARTREE_TO_KCAL if units[route] == 'hartree' else 1)
            rows.append({'route': route, 'member': _positive(member['source_frame']),
                         'relative_kcal_within_route': _number(relative)})
        if not rows or set(record['sources']) != {r['route'] for r in rows}:
            raise ValueError('Candidate sources and route members differ')
        result.append(rows)
    return result


def _relative(candidates, layer):
    rows = [r for r in candidates if r[layer] is not None and not r[layer]['ambiguous']
            and r[layer]['energy_hartree'] is not None]
    if not rows:
        return None
    reference = min(rows, key=lambda r: (r[layer]['energy_hartree'], r['candidate']))
    for row in rows:
        row[layer]['relative_kcal'] = _number((row[layer]['energy_hartree'] -
                                              reference[layer]['energy_hartree']) * geo.HARTREE_TO_KCAL)
    return reference['candidate']


def _layer(evidence, values, layer, frames, payload, candidates, unmatched):
    matches = [[] for _ in candidates]
    for value in dict.fromkeys(values):
        path, manifest = _attempt(evidence, value)
        # Reject links before diagnostic handling can turn an unsafe path into a note.
        local_path(evidence.root, path / 'facts.json')
        for item in manifest['inputs']:
            local_path(evidence.root, path / 'inputs' / item['name'])
        try:
            frame, science = _geometry(evidence, path, manifest)
            indices = [i for i, candidate in enumerate(frames) if coverage.same_geometry(
                candidate, frame, payload['hydrogens'], payload['charge'])]
        except (ValueError, RuntimeError, KeyError, TypeError, OSError):
            unmatched.append({'layer': layer, 'attempt': value, 'reason': '输入几何不可读取或比较'})
            continue
        if len(indices) != 1:
            unmatched.append({'layer': layer, 'attempt': value,
                              'reason': '未匹配候选' if not indices else '匹配多个候选'})
            continue
        index = indices[0]
        facts = None
        try:
            facts = evidence.json(path / 'facts.json')
            if not isinstance(facts, dict):
                facts = None
        except (ValueError, OSError):
            pass
        matches[index].append((value, facts, science))
    for candidate, entries in zip(candidates, matches):
        if not entries:
            continue
        ambiguous = len(entries) > 1
        result = {'attempts': [v for v, _, _ in entries], 'ambiguous': ambiguous,
                  'energy_hartree': None, 'relative_kcal': None}
        if layer == 'opt':
            result.update(termination=None, n_imaginary=None)
        valid = []
        for value, facts, science in entries:
            try:
                if facts is None:
                    raise ValueError('缺少可读取的已保存 facts')
                if layer == 'sp' and (facts.get('program') != 'gaussian' or
                        facts.get('termination') != 'normal' or
                        re.search(r'\b(?:opt|irc|scan|force|freq)\b', science['route'], re.I)):
                    raise ValueError('需要正常结束的 Gaussian 单点，route 不得包含 opt/irc/scan/force/freq')
                energy = _number((facts.get('energies') or {}).get('scf'))
                if energy is not None and facts.get('units', {}).get('energy') != 'Hartree':
                    raise ValueError('SCF 能量单位必须为 Hartree')
                if layer == 'sp' and energy is None:
                    raise ValueError('缺少 SCF 能量')
                item = {'energy_hartree': energy}
                if layer == 'opt':
                    termination, imaginary = facts.get('termination'), facts.get('n_imag')
                    if termination not in {None, 'normal', 'error', 'incomplete'}:
                        raise ValueError('未知 termination 值')
                    if imaginary is not None and (type(imaginary) is not int or imaginary < 0):
                        raise ValueError('无效虚频数')
                    item.update(termination=termination, n_imaginary=imaginary)
                valid.append(item)
            except (ValueError, TypeError, AttributeError) as exc:
                # Only our fixed diagnostic text is copied; never parser paths.
                reason = str(exc) if type(exc) is ValueError else 'facts 字段格式无效'
                candidate['notes'].append(f'{layer} {value}: {reason}')
        if ambiguous:
            candidate['notes'].append(f'{layer}: 多个 Attempt 匹配，不选择能量')
        elif valid:
            result.update(valid[0])
        candidate[layer] = result if ambiguous or valid else None


def _bin_summary(candidates):
    groups = {}
    for candidate in candidates:
        groups.setdefault(tuple(candidate['local']['bins']), []).append(candidate)
    summary = []
    for bins, rows in groups.items():
        lowest, lowest_layer = None, None
        # Compare only within the highest available layer in this group. Never
        # compare a thermo energy against an electronic energy from another layer.
        for layer, key in [('thermo', 'qh_G'), ('opt', 'energy_hartree'),
                           ('sp', 'energy_hartree'), ('xtb', 'xtb_relative_kcal')]:
            values = []
            for row in rows:
                if layer == 'xtb':
                    energy = row[key]
                else:
                    data = row[layer] or {}
                    energy = None if data.get('ambiguous') else data.get(key)
                if energy is not None:
                    values.append((energy, row['candidate']))
            if values:
                lowest, lowest_layer = min(values)[1], layer
                break
        summary.append({'bins': list(bins), 'count': len(rows),
                        'lowest_candidate': lowest, 'lowest_layer': lowest_layer})
    return summary


def build(merged, out, *, study=None, label=None, routes=(), sp=(), opt=(), thermo=None,
          dihedral_bins=(), report_distance=()):
    definitions = descriptor_definitions(dihedral_bins, report_distance)
    root = _root(merged, study)
    # Explicit --study makes relative file arguments study-relative; otherwise
    # the merged argument is relative to the invoking working directory.
    merged = _path(root, merged if study else Path(merged).expanduser().absolute())
    out = _path(root, out)
    local_path(root / 'analyses', out)
    if out.suffix != '.json' or out.parent != merged.parent:
        raise ValueError('--out must be .json in the merged directory under analyses/')
    for target in (out, out.with_suffix('.md')):
        local_path(root, target)
        if target.exists():
            raise FileExistsError(f'Output already exists: {target.name}')
    if label is not None and (not isinstance(label, str) or len(label) > 80):
        raise ValueError('--label must be at most 80 characters')
    evidence = _Evidence(root)
    payload = evidence.json(merged)
    if type(payload['charge']) is not int or payload['hydrogens'] not in {'heavy', 'polar', 'all'}:
        raise ValueError('Invalid charge or hydrogen mode')
    if payload['energy_basis'] not in {'shared_hartree', 'per_source_not_comparable'}:
        raise ValueError('Expected dedup --source energy_basis')
    route_labels = payload['routes']
    if (not isinstance(route_labels, list) or not route_labels or
            any(not isinstance(r, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]*', r)
                for r in route_labels) or len(set(route_labels)) != len(route_labels)):
        raise ValueError('Invalid dedup route labels')
    name = payload['xyz_file']
    if not isinstance(name, str) or Path(name).name != name or Path(name).suffix != '.xyz':
        raise ValueError('xyz_file must be a plain XYZ filename')
    xyz = local_path(root, merged.parent / name)
    raw = evidence.read(xyz)
    if sha256(raw).hexdigest() != payload['xyz_sha256']:
        raise ValueError('Dedup XYZ hash differs from source provenance')
    frames, hashes = geo.read_xyz(xyz), _frame_hashes(raw)
    records = payload['kept']
    if len(records) != len(frames) or any(r['xyz_frame'] != i for i, r in enumerate(records, 1)):
        raise ValueError('Dedup records and XYZ frame ordering differ')
    if len({_positive(r['index']) for r in records}) != len(records):
        raise ValueError('Duplicate candidate numbers')
    route_members = _route_members(payload)
    route_attempts = {r: [] for r in route_labels}
    for specification in routes:
        route, separator, ids = specification.partition('=')
        if not separator or route not in route_attempts:
            raise ValueError('--route LABEL must occur in merged routes')
        for value in ids.split(','):
            _attempt(evidence, value)
            if value not in route_attempts[route]:
                route_attempts[route].append(value)
    candidates = [dict(candidate=r['index'], xyz_frame=r['xyz_frame'], geometry_sha256=h,
                       sources=list(r['sources']), route_members=m, xtb_relative_kcal=None,
                       sp=None, opt=None, thermo=None, missing=[], notes=[])
                  for r, h, m in zip(records, hashes, route_members)]
    if definitions is not None:
        for index, (candidate, frame) in enumerate(zip(candidates, frames)):
            local = frame_descriptors(frame, definitions, index)
            candidate['local'] = {key: local[key] for key in
                                  ('dihedrals', 'bins', 'near_boundary', 'distances')}
            candidate['local']['bins'] = [definition['names'][number - 1]
                for definition, number in zip(definitions['dihedral_bins'], local['bins'])]
    references = {'xtb': None, 'sp': None, 'opt': None}
    warnings = []
    if payload['energy_basis'] == 'shared_hartree':
        energies = [_number(r['energy']) for r in records]
        if any(e is None or r['energy_unit'] != 'hartree' for e, r in zip(energies, records)):
            raise ValueError('shared_hartree requires finite Hartree energies')
        minimum = min(energies)
        references['xtb'] = min(r['index'] for r, e in zip(records, energies) if e == minimum)
        for candidate, energy in zip(candidates, energies):
            candidate['xtb_relative_kcal'] = _number((energy - minimum) * geo.HARTREE_TO_KCAL)
    else:
        warnings.append('各路线 xTB 能量不可直接比较')
    if len(sp) == 1 and Path(sp[0]).suffix.lower() == '.json':
        sp = evidence.json(_path(root, sp[0]))
        if not isinstance(sp, list) or not all(isinstance(v, str) for v in sp):
            raise ValueError('--sp JSON must be a list of Attempt IDs')
    unmatched = []
    _layer(evidence, sp, 'sp', frames, payload, candidates, unmatched)
    _layer(evidence, opt, 'opt', frames, payload, candidates, unmatched)
    for layer in ('sp', 'opt'):
        references[layer] = _relative(candidates, layer)
    inputs = {'merged': evidence.reference(merged), 'xyz': {**evidence.reference(xyz), 'file': name}}
    if thermo:
        table_path = _path(root, thermo)
        table = evidence.json(table_path)
        if table['schema'] != 'ag-thermo/1' or any(table['units'].get(k) != v for k, v in
                [('energy', 'Hartree'), ('relative_G', 'kcal/mol'), ('population', 'fraction')]):
            raise ValueError('Expected ag-thermo/1 with Hartree, kcal/mol and fraction units')
        inputs['thermo'] = evidence.reference(table_path)
        linked = {c['candidate']: [] for c in candidates}
        for row in table['rows']:
            value = identifier(row['attempt_id'])
            matches = [c for c in candidates if c['opt'] and value in c['opt']['attempts']]
            if len(matches) != 1 or matches[0]['opt']['ambiguous']:
                unmatched.append({'layer': 'thermo', 'attempt': value, 'reason': '无唯一对应的 Opt 候选'})
            else:
                linked[matches[0]['candidate']].append(row)
        for candidate in candidates:
            rows = linked[candidate['candidate']]
            if len(rows) > 1:
                candidate['notes'].append('thermo: 多行对应同一候选，不选择热化学值')
                unmatched.extend({'layer': 'thermo', 'attempt': r['attempt_id'],
                                  'reason': '多行对应同一候选'} for r in rows)
            elif rows:
                row = rows[0]
                candidate['thermo'] = {'attempt': row['attempt_id'], **{
                    k: _number(row[k]) for k in ('qh_G', 'relative_G_kcal', 'population')}}
    for candidate in candidates:
        candidate['missing'] = [name for key, name in [('sp', 'sp'), ('opt', 'opt_freq'), ('thermo', 'thermo')]
                                if candidate[key] is None or candidate[key].get('ambiguous', False)]
    result = dict(schema='ag-ensemble/1', created_at=datetime.now(timezone.utc).isoformat(),
                  ag=ag_provenance(), study_id=root.name, label=label, inputs=inputs,
                  charge=payload['charge'], hydrogens=payload['hydrogens'], energy_basis=payload['energy_basis'],
                  units={'energy': 'Hartree', 'relative': 'kcal/mol', 'population': 'fraction'},
                  routes=[{'label': r, 'attempts': ids} for r, ids in route_attempts.items()],
                  references=references, warnings=warnings, candidates=candidates, unmatched_attempts=unmatched)
    if definitions is not None:
        result['descriptors'] = {key: definitions[key] for key in ('dihedral_bins', 'distance_pairs')}
        result['bin_summary'] = _bin_summary(candidates)
    content = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    evidence.verify()
    _write_outputs(out.parent, {out.name: content.encode(), out.with_suffix('.md').name: markdown(result).encode()})
    return result


def markdown(result):
    def cell(value):
        if value is None:
            return '—'
        return str(value).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('|', '&#124;').replace('\n', ' ').replace('\r', ' ').replace('`', '&#96;')

    lines = ['# 构象集合清单', '', f"集合：{cell(result['label'])}",
             f"能量基准：{result['energy_basis']}；相对能 kcal/mol；布居 fraction。",
             '参考候选：' + '；'.join(f'{k}={cell(v)}' for k, v in result['references'].items()),
             '热化学相对值和布居沿用输入表的参考与全集，不按本清单重新归一化。',
             *('警告：' + cell(w) for w in result['warnings']), '',
             '| 编号 | 来源路线 | xTB 相对能（或路线内） | SP 相对能 | Opt 状态 / 虚频数 | qh_G 相对值 | 布居 | 缺失层 | 备注 |',
             '| --- | --- | --- | --- | --- | --- | --- | --- | --- |']
    if 'descriptors' in result:
        lines[-2] += ' 分组 | 近边界 | 距离（Å） |'
        lines[-1] += ' --- | --- | --- |'
    for row in result['candidates']:
        xtb = row['xtb_relative_kcal']
        if result['energy_basis'] == 'per_source_not_comparable':
            xtb = '; '.join(f"{m['route']}[{m['member']}]={cell(m['relative_kcal_within_route'])}" for m in row['route_members'])
        opt, sp, thermo = row['opt'] or {}, row['sp'] or {}, row['thermo'] or {}
        status = 'ambiguous' if opt.get('ambiguous') else f"{cell(opt.get('termination'))} / {cell(opt.get('n_imaginary'))}"
        values = [row['candidate'], ', '.join(row['sources']), xtb, sp.get('relative_kcal'), status,
                  thermo.get('relative_G_kcal'), thermo.get('population'), ', '.join(row['missing']), '; '.join(row['notes'])]
        if 'descriptors' in result:
            local = row['local']
            values += [', '.join(local['bins']), local['near_boundary'],
                       ', '.join(str(v) for v in local['distances'])]
        lines.append('| ' + ' | '.join(cell(v) for v in values) + ' |')
    if 'descriptors' in result:
        lines += ['', '## 分组汇总', '', '| 分组 | 候选数 | 最低能候选 | 能量层 |',
                  '| --- | --- | --- | --- |']
        for row in result['bin_summary']:
            values = [', '.join(row['bins']), row['count'], row['lowest_candidate'], row['lowest_layer']]
            lines.append('| ' + ' | '.join(cell(v) for v in values) + ' |')
    lines += ['', '未匹配 Attempt：', '']
    lines += [f"- {cell(r['layer'])} {cell(r['attempt'])}: {cell(r['reason'])}" for r in result['unmatched_attempts']] or ['- 无']
    return '\n'.join(lines) + '\n'


def run(args):
    try:
        result = build(args.merged, args.out, study=args.study, label=args.label,
                       routes=args.route, sp=args.sp, opt=args.opt, thermo=args.thermo,
                       dihedral_bins=args.dihedral_bins, report_distance=args.report_distance)
    except ImportError:
        print('ensemble requires RDKit in the selected Python environment', file=sys.stderr)
        return 2
    except (ValueError, OSError, KeyError, TypeError, RuntimeError, AttributeError) as exc:
        print(f'ensemble: {exc}', file=sys.stderr)
        return 1
    print(markdown(result), end='')
    return 0


def register(subparsers):
    parser = subparsers.add_parser('ensemble', description=__doc__)
    parser.add_argument('--merged', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--study', help='Study directory or configured ID; relative file arguments are study-relative')
    parser.add_argument('--label')
    parser.add_argument('--route', action='append', default=[], metavar='LABEL=ATTEMPT_ID[,ATTEMPT_ID...]')
    parser.add_argument('--sp', nargs='+', default=[], help='Attempt IDs or one JSON list file')
    parser.add_argument('--opt', nargs='+', default=[], help='Opt+Freq Attempt IDs')
    parser.add_argument('--thermo', type=Path)
    parser.add_argument('--dihedral-bins', action='append', default=[], metavar='A,B,C,D:b1,b2[@names]',
                        help='Report periodic dihedral bins in degrees (repeatable)')
    parser.add_argument('--report-distance', action='append', default=[], metavar='I,J',
                        help='Report a 1-based XYZ atom-pair distance in angstrom (repeatable)')
    parser.set_defaults(func=run)
