"""Summarize explicitly assigned channel evidence; never judge sampling sufficiency."""

import csv
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import sys

from ag.ensemble import _Evidence, _number, _path, _positive, _root
from ag.facts import ag_provenance
from ag.fragments import _write_outputs
from ag.study import local_path


LAYERS = ('thermo', 'opt', 'sp', 'xtb')
METRICS = ('opt_count', 'sp_count', 'candidate_count')


def _channels(raw):
    reader = csv.reader(io.StringIO(raw.decode('utf-8-sig'), newline=''), strict=True)
    required = {'channel_id', 'product_branch', 'ensemble_manifests'}
    try:
        header = next(reader, [])
        if not required.issubset(header) or len(set(header)) != len(header):
            raise ValueError('CSV row 1: missing required columns or duplicate headers')
        rows, seen = [], set()
        while True:
            line = reader.line_num + 1
            values = next(reader, None)
            if values is None:
                break
            if len(values) != len(header):
                raise ValueError(f'CSV row {line}: field count differs from header')
            row = dict(zip(header, (v.strip() for v in values)))
            if any(not row[key] for key in required):
                raise ValueError(f'CSV row {line}: empty required value')
            if row['channel_id'] in seen:
                raise ValueError(f'CSV row {line}: duplicate channel_id')
            seen.add(row['channel_id'])
            paths = [p.strip() for p in row['ensemble_manifests'].split(';')]
            if not all(paths):
                raise ValueError(f'CSV row {line}: empty ensemble manifest path')
            rows.append(dict(channel_id=row['channel_id'], product_branch=row['product_branch'],
                             note=row.get('note', ''), paths=paths, line=line))
        if not rows:
            raise ValueError('CSV row 2: expected at least one channel')
        return rows
    except csv.Error as exc:
        raise ValueError(f'CSV row {reader.line_num}: invalid CSV') from exc


def _validate(payload, study_id):
    # Malformed or ambiguous evidence must not silently turn into zero coverage
    # or a numeric minimum. Validate only fields consumed by this report.
    if not isinstance(payload, dict) or payload.get('schema') != 'ag-ensemble/1':
        raise ValueError('Expected schema ag-ensemble/1')
    if payload.get('study_id') != study_id:
        raise ValueError('Manifest study_id differs from current study')
    if payload['energy_basis'] not in {'shared_hartree', 'per_source_not_comparable'}:
        raise ValueError('Invalid energy_basis')
    if any(payload['units'].get(k) != v for k, v in
           [('energy', 'Hartree'), ('relative', 'kcal/mol')]):
        raise ValueError('Expected Hartree and kcal/mol units')
    routes = [r['label'] for r in payload['routes']]
    if (any(not isinstance(r, str) or not r for r in routes) or
            len(set(routes)) != len(routes)):
        raise ValueError('Invalid route labels')
    if not isinstance(payload['warnings'], list) or any(
            not isinstance(w, str) for w in payload['warnings']):
        raise ValueError('Expected warnings list')
    if not isinstance(payload['unmatched_attempts'], list) or not isinstance(payload['candidates'], list):
        raise ValueError('Expected candidates and unmatched_attempts lists')
    seen = set()
    for candidate in payload['candidates']:
        number = _positive(candidate['candidate'])
        if number in seen:
            raise ValueError('Duplicate candidate number within manifest')
        seen.add(number)
        sources = candidate['sources']
        if (not isinstance(sources, list) or not sources or
                any(not isinstance(s, str) or s not in routes for s in sources) or
                len(set(sources)) != len(sources)):
            raise ValueError('Invalid candidate sources')
        _number(candidate['xtb_relative_kcal'])
        for layer in ('sp', 'opt'):
            entry = candidate[layer]
            if entry is not None:
                if not isinstance(entry, dict) or type(entry['ambiguous']) is not bool:
                    raise ValueError('Invalid layer ambiguity flag')
                _number(entry['energy_hartree'])
        if candidate['thermo'] is not None:
            _number(candidate['thermo']['qh_G'])


def _energy(candidate, layer, payload):
    if layer == 'xtb':
        return candidate['xtb_relative_kcal'] if payload['energy_basis'] == 'shared_hartree' else None
    entry = candidate[layer]
    if entry is None or entry.get('ambiguous', False):
        return None
    return entry['qh_G' if layer == 'thermo' else 'energy_hartree']


def _minimum(entries):
    """Use a single highest available layer; xTB zeros are manifest-local."""
    for layer in LAYERS:
        available = []
        for channel_id, reference, payload in entries:
            for candidate in payload['candidates']:
                energy = _energy(candidate, layer, payload)
                if energy is not None:
                    available.append(dict(channel_id=channel_id, manifest=reference,
                                          candidate=candidate['candidate'], routes=candidate['sources'],
                                          layer=layer, energy=energy,
                                          unit='kcal/mol' if layer == 'xtb' else 'Hartree'))
        if available:
            if layer == 'xtb' and len({r['manifest']['path'] for r in available}) > 1:
                return None, 'xtb_relative_energies_have_different_manifest_zeros'
            return min(available, key=lambda r: (r['energy'], r['manifest']['path'], r['candidate'])), None
    return None, 'no_usable_energy'


def _summary(entries):
    counts = dict(manifest_count=len(entries), candidate_count=0, by_route={}, sp_count=0,
                  opt_count=0, thermo_count=0, ambiguous_count=0, unmatched_attempts_count=0)
    warnings, minima = [], []
    for channel_id, reference, payload in entries:
        counts['candidate_count'] += len(payload['candidates'])
        counts['unmatched_attempts_count'] += len(payload['unmatched_attempts'])
        for route in payload['routes']:
            counts['by_route'].setdefault(route['label'], 0)
        for candidate in payload['candidates']:
            for route in candidate['sources']:
                counts['by_route'][route] += 1
            for layer in ('sp', 'opt', 'thermo'):
                counts[f'{layer}_count'] += int(candidate[layer] is not None)
            counts['ambiguous_count'] += int(any(
                (candidate[layer] or {}).get('ambiguous', False) for layer in ('sp', 'opt')))
        messages = list(payload['warnings'])
        if payload['energy_basis'] == 'per_source_not_comparable':
            messages.append('energy_basis=per_source_not_comparable; xTB 路线之间不可比较')
        warnings.extend({'manifest': reference, 'message': w} for w in dict.fromkeys(messages))
        minimum, reason = _minimum([(channel_id, reference, payload)])
        minima.append(dict(manifest=reference, lowest=minimum, unavailable_reason=reason))
    lowest, reason = _minimum(entries)
    if reason:
        warnings.append({'message': reason})
    if len(entries) > 1:
        warnings.append({'message': '跨清单只比较保存的同层绝对能；方法、体系及热化学条件的可比性须人工审阅。'})
    return dict(**counts, lowest=lowest, lowest_unavailable_reason=reason,
                lowest_by_manifest=minima, warnings=warnings, imbalances=[])


def _imbalances(rows, ratio):
    for metric in METRICS:
        maximum = max(r[metric] for r in rows)
        for row in rows:
            if row[metric] < maximum * ratio:
                row['imbalances'].append(dict(metric=metric, count=row[metric],
                                               maximum=maximum, threshold=maximum * ratio))


def build(channels, out, *, study=None, imbalance_ratio=0.5):
    ratio = _number(imbalance_ratio)
    if ratio is None or not 0 <= ratio <= 1:
        raise ValueError('--imbalance-ratio must be finite and between 0 and 1')
    root = _root(channels, study)
    channels = _path(root, channels if study else Path(channels).expanduser().absolute())
    local_path(root / 'analyses', channels)
    out = _path(root, out)
    local_path(root / 'analyses', out)
    if channels.suffix.lower() != '.csv' or out.suffix != '.json':
        raise ValueError('--channels must be .csv and --out must be .json under analyses/')
    for target in (out, out.with_suffix('.md')):
        local_path(root, target)
        if target.exists():
            raise FileExistsError(f'Output already exists: {target.name}')
    evidence = _Evidence(root)
    rows = _channels(evidence.read(channels))
    used, channel_rows, branches = set(), [], {}
    for row in rows:
        entries = []
        for value in row['paths']:
            if Path(value).is_absolute():
                raise ValueError(f"CSV row {row['line']}: manifest paths must be study-relative")
            try:
                path = local_path(root, root / value)
                if path in used:
                    raise ValueError('Duplicate manifest (within or across channels)')
                used.add(path)
                payload = evidence.json(path)
                _validate(payload, root.name)
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
                # Do not copy filesystem diagnostics containing absolute paths.
                detail = str(exc) if type(exc) is ValueError else type(exc).__name__
                raise ValueError(f"CSV row {row['line']}: invalid ensemble manifest: {detail}") from exc
            entries.append((row['channel_id'], evidence.reference(path), payload))
        channel_rows.append(dict(channel_id=row['channel_id'], product_branch=row['product_branch'],
                                 note=row['note'], manifests=[e[1] for e in entries], **_summary(entries)))
        branches.setdefault(row['product_branch'], []).extend(entries)
    branch_rows = [dict(product_branch=name, channel_ids=list(dict.fromkeys(e[0] for e in entries)),
                        manifests=[e[1] for e in entries], **_summary(entries))
                   for name, entries in branches.items()]
    _imbalances(channel_rows, ratio)
    _imbalances(branch_rows, ratio)
    result = dict(schema='ag-channel-coverage/1', created_at=datetime.now(timezone.utc).isoformat(),
                  ag=ag_provenance(), study_id=root.name, inputs={'channels': evidence.reference(channels)},
                  imbalance_ratio=ratio, channels=channel_rows, product_branches=branch_rows)
    content = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    evidence.verify()
    _write_outputs(out.parent, {out.name: content.encode('utf-8'),
                               out.with_suffix('.md').name: markdown(result).encode('utf-8')})
    return result


def markdown(result):
    def cell(value):
        return str(value).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace(
            '|', '&#124;').replace('`', '&#96;').replace('\n', ' ').replace('\r', ' ')

    lines = ['# 通道采样覆盖', '', f"不均衡阈值比例：{result['imbalance_ratio']}",
             '仅汇总保存的清单；提示不代表覆盖不足或合格，能量最低值不代表科学验收。',
             'SP/Opt/thermo 数为非空记录数（含歧义/未知能量），不是通过审阅的计算数。', '']
    for title, key, identity in [('通道', 'channels', 'channel_id'),
                                  ('产物分支', 'product_branches', 'product_branch')]:
        lines += [f'## {title}', '',
                  '| 标识 | 清单 | 候选 | SP | Opt | 热化学 | ambiguous | unmatched | 不均衡提示 |',
                  '| --- | --- | --- | --- | --- | --- | --- | --- | --- |']
        for row in result[key]:
            values = [row[identity], *(row[k] for k in ('manifest_count', 'candidate_count', 'sp_count',
                      'opt_count', 'thermo_count', 'ambiguous_count', 'unmatched_attempts_count')),
                      ', '.join(f"{i['metric']}: {i['count']} < {i['threshold']} (max={i['maximum']})"
                                for i in row['imbalances']) or '无']
            lines.append('| ' + ' | '.join(cell(v) for v in values) + ' |')
        for row in result[key]:
            lines += ['', f"### {cell(row[identity])}", '']
            if key == 'channels':
                lines += [f"产物分支：{cell(row['product_branch'])}；备注：{cell(row['note'])}"]
            else:
                lines += ['通道：' + ', '.join(cell(v) for v in row['channel_ids'])]
            lines += ['按路线候选数：' + '; '.join(f'{cell(k)}={v}' for k, v in row['by_route'].items())]
            lowest = row['lowest']
            if lowest:
                lines += [f"最低候选：{cell(lowest['layer'])} {lowest['energy']} {lowest['unit']}；"
                          f"通道 {cell(lowest['channel_id'])}；清单 {cell(lowest['manifest']['path'])}；"
                          f"候选 {lowest['candidate']}；路线 {cell(', '.join(lowest['routes']))}"]
            else:
                lines += [f"最低候选：不可确定（{cell(row['lowest_unavailable_reason'])}）"]
            for item in row['lowest_by_manifest']:
                minimum = item['lowest']
                detail = (f"候选 {minimum['candidate']}, {minimum['layer']}={minimum['energy']} {minimum['unit']}, "
                          f"路线 {', '.join(minimum['routes'])}" if minimum else item['unavailable_reason'])
                lines += [f"- 清单 {cell(item['manifest']['path'])}：{cell(detail)}；SHA-256 {item['manifest']['sha256']}"]
            lines += ['- 警告：' + cell(w.get('manifest', {}).get('path', '')) + ' ' + cell(w['message'])
                      for w in row['warnings']]
    return '\n'.join(lines) + '\n'


def run(args):
    try:
        result = build(args.channels, args.out, study=args.study, imbalance_ratio=args.imbalance_ratio)
    except (ValueError, OSError, KeyError, TypeError, AttributeError) as exc:
        print(f'channel-coverage: {exc}', file=sys.stderr)
        return 1
    print(markdown(result), end='')
    return 0


def register(subparsers):
    parser = subparsers.add_parser('channel-coverage', description=__doc__)
    parser.add_argument('--channels', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--study', help='Study directory or configured ID; relative file arguments are study-relative')
    parser.add_argument('--imbalance-ratio', type=float, default=0.5)
    parser.set_defaults(func=run)
