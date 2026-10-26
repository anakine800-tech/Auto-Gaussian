"""Local candidate integrity, geometry and channel diagnostics (T137)."""
from collections import Counter
from copy import deepcopy
from hashlib import sha256
import json
import math
from pathlib import Path
import re
import sys

from ag import attempt, catalog, catalog_v2 as v2, gaussian_input, geometry as geo, study
from ag.irc_compare import _pairs

NOTICE = 'G0 是本地诊断，不是门禁；不替代 DFT 验收；clean 只表示未发现问题。'
ORDER_NOTICE = '顺序只是建议，提交与否由负责人决定。'
ORDER_LIMIT = '只比较元素序列；同种元素原子互换无法检出，原子映射仍需人审。'
# Fixed conservative damage/clash criteria; never submission checks.
MIN_DISTANCE = 0.5
COVALENT_FACTOR = 0.5
VDW_FACTOR = 0.75
MAX_DIAGNOSIS_BYTES = 65536


def _frame(rows):
    symbols = gaussian_input.cartesian(rows, first_line=1)
    if not symbols:
        raise ValueError('Missing Cartesian geometry')
    return geo.Frame(tuple(symbols), tuple(tuple(float(x) for x in row.split()[1:]) for row in rows))


def _xyz_frame(data):
    count, _ = v2.xyz(data)
    return _frame(data.decode('utf-8').splitlines()[2:count + 2])


def _manifest_frame(root, identity, *, stereo=False):
    """Use manifest_info's sources; first QST group for element order.

    The stereo producer uses the explicit third TS guess for QST3 input.
    xTB/CREST geometries come from the hash-bound declared input XYZ.
    """
    path = study.local_path(root, root / 'attempts' / study.identifier(identity))
    raw = v2.read_bytes(path / 'manifest.json', 1024 * 1024)
    manifest = attempt.read_manifest(path)
    if json.loads(raw) != manifest:
        raise ValueError('Reference manifest changed while reading; run diagnosis again')
    source = dict(attempt=identity, manifest_sha256=sha256(raw).hexdigest())
    science = manifest.get('science') or {}
    if manifest.get('template') in ('xtb', 'crest'):
        inputs = [i for i in manifest.get('inputs', []) if Path(i['name']).suffix.lower() == '.xyz']
        if len(inputs) != 1:
            return None, source, '参考 Attempt 未声明唯一输入 XYZ'
        item = inputs[0]
        data = v2.read_bytes(path / 'inputs' / attempt.filename(item['name']), 1024 * 1024)
        if sha256(data).hexdigest() != item['sha256'] or len(data) != item['size']:
            raise ValueError('Reference input XYZ hash/size differs from manifest; requires manual handling')
        v2.xyz(data, ensemble=True)
        count = int(data.splitlines()[0])
        source.update(input_sha256=item['sha256'], geometry_frame=1)
        return _frame(data.decode('utf-8').splitlines()[2:count + 2]), source, None
    groups = science.get('structures')
    if groups is not None:
        if not isinstance(groups, list) or not groups or any(not isinstance(g, dict) for g in groups):
            return None, source, '参考 Attempt 的 QST structures 缺失或无效'
        index = 2 if stereo and len(groups) == 3 else 0
        geometry = groups[index].get('geometry')
        source['json_pointer'] = f'/science/structures/{index}/geometry'
    else:
        geometry = science.get('geometry')
        source['json_pointer'] = '/science/geometry'
    if not isinstance(geometry, str) or not geometry.strip():
        return None, source, '参考 Attempt 未提供输入几何'
    return _frame(geometry.splitlines()), source, None


def _integrity(root, obj, candidate, frame, reference):
    expected = obj['expected']
    actual_formula = v2.hill(Counter(frame.symbols))
    wanted = expected['formula']['value']
    checks = {'atom_count_and_formula': dict(
        status=('pass' if wanted == actual_formula else 'reject') if wanted is not None else 'unchecked',
        expected=expected['formula'], actual=dict(formula=actual_formula, n_atoms=len(frame.symbols)),
        reason='按候选所属对象的 expected.formula 核对组成和原子数' if wanted is not None else '对象期望组成未提供或未知')}
    values, unavailable, ref, provenance, missing = {}, {}, None, None, '没有参考 Attempt'
    if reference:
        ref, provenance, missing = _manifest_frame(root, reference)
        values, unavailable = v2.manifest_info(root, reference)
    checks['atom_order'] = dict(
        status=('pass' if frame.symbols == ref.symbols else 'reject') if ref else 'unchecked',
        actual=list(frame.symbols), expected=list(ref.symbols) if ref else None,
        reason=ORDER_LIMIT if ref else missing, limitation=ORDER_LIMIT)
    charge, mult = expected['charge']['value'], obj['multiplicity']
    parity = dict(status='unchecked', reason='对象期望电荷或多重度未提供/未知')
    if charge is not None and mult is not None:
        try:
            gaussian_input.check_electrons(frame.symbols, charge, mult, location='object expectation')
            parity = dict(status='pass', reason='对象期望值与候选元素组成的电子数奇偶相容')
        except ValueError as exc:
            parity = dict(status='reject', reason=str(exc))
    for key, value in (('charge', charge), ('multiplicity', mult)):
        comparison = ('unchecked' if value is None or key not in values else
                      'pass' if value == values[key] else 'reject')
        states = [comparison, parity['status'] if value is not None else 'unchecked']
        status = 'reject' if 'reject' in states else 'unchecked' if 'unchecked' in states else 'pass'
        checks[key] = dict(status=status, expected=value, reference_value=values.get(key),
                           manifest_comparison=comparison, electron_parity=dict(parity),
                           reason=('对象期望值未提供或未知' if value is None else
                                   unavailable.get(key, '没有参考 Attempt') if key not in values else
                                   '对象期望值与参考 Attempt manifest 核对；XYZ 本身不携带电荷或多重度'))
    return checks, provenance


def _geometry(frame, reaction_pairs=()):
    try:
        from rdkit import Chem
    except ImportError as exc:
        raise ValueError('G0 geometry diagnostics require RDKit') from exc
    table = Chem.GetPeriodicTable()
    # Applicable human distance windows identify reaction pairs. Never infer
    # them from a bond-state cutoff or exempt them from either damage check.
    reaction_pairs = {tuple(sorted(atoms)) for atoms in reaction_pairs}
    damage, clashes, reaction_center_pairs = [], [], []
    for atoms, pair in _pairs(frame, Chem).items():
        elements = [frame.symbols[i - 1] for i in atoms]
        distance = pair['distance']
        covalent = COVALENT_FACTOR * sum(table.GetRcovalent(e) for e in elements)
        vdw = VDW_FACTOR * sum(table.GetRvdw(e) for e in elements)
        entry = dict(atoms=list(atoms), elements=elements, distance_angstrom=distance,
                     bond_state=pair['state'])
        if atoms in reaction_pairs:
            reaction_center_pairs.append(entry)
        criteria = []
        if distance < MIN_DISTANCE:
            criteria.append('distance_below_0.5_angstrom')
        if distance < covalent:
            criteria.append('distance_below_half_covalent_sum')
        if criteria:
            damage.append(dict(entry, criteria=criteria, covalent_threshold_angstrom=covalent))
        if ('H' not in elements and pair['state'] != 'bonded' and distance < vdw and
                atoms not in reaction_pairs):
            clashes.append(dict(entry, threshold_angstrom=vdw,
                                recommendation='先核对是否为未声明的反应中心；仅确认普通空间冲突后，'
                                               '再考虑保持反应坐标的受限松弛'))
    return dict(damage=damage, clashes=clashes, reaction_center_pairs=reaction_center_pairs,
                thresholds=dict(min_distance_angstrom=MIN_DISTANCE,
                                covalent_sum_factor=COVALENT_FACTOR, vdw_sum_factor=VDW_FACTOR))


def _window(value):
    if not isinstance(value, dict) or set(value) - {'atoms', 'min', 'max', 'label'}:
        raise ValueError('Invalid distance window fields')
    atoms = value.get('atoms')
    if (not isinstance(atoms, list) or len(atoms) != 2 or
            any(type(a) is not int or a < 1 for a in atoms) or atoms[0] == atoms[1]):
        raise ValueError('Window atoms must be two distinct positive 1-based indices')
    low, high = value.get('min'), value.get('max')
    if (any(type(v) not in (int, float) or not math.isfinite(v) for v in (low, high)) or
            low < 0 or high < low):
        raise ValueError('Window requires finite 0 <= min <= max')
    label = value.get('label', '')
    if not isinstance(label, str):
        raise ValueError('Window label must be text')
    return dict(atoms=atoms, min=low, max=high, label=label)


def window_argument(value):
    match = re.fullmatch(r'([1-9][0-9]*)-([1-9][0-9]*):([^:]+):([^:]+)', value)
    if not match:
        raise ValueError('Expected --window i-j:min:max')
    return _window(dict(atoms=[int(match[1]), int(match[2])], min=float(match[3]), max=float(match[4])))


def _windows(root, filename, extra):
    config, source = dict(channels={}, all=[]), None
    if filename:
        path = Path(filename).expanduser()
        if not path.is_absolute():
            path = root / path
        path = study.local_path(root / 'analyses', path)
        raw = v2.read_bytes(path, 1024 * 1024)
        config = json.loads(raw)
        if not isinstance(config, dict):
            raise ValueError('Windows file must be a JSON object')
        if set(config) - {'channels', 'all', 'reaction_coordinates'}:
            raise ValueError('Unknown windows file fields; allowed: channels, all, reaction_coordinates')
        # T138 owns reaction_coordinates. Allow its key without consuming or
        # validating the contents; reject other keys to catch misspellings.
        source = dict(file=str(path.relative_to(root)), sha256=sha256(raw).hexdigest())
    channels, common = config.get('channels', {}), config.get('all', [])
    if not isinstance(channels, dict) or not isinstance(common, list):
        raise ValueError('Windows channels must be an object and all must be a list')
    parsed = {}
    for key, rows in channels.items():
        study.identifier(key)
        if not isinstance(rows, list):
            raise ValueError('Channel windows must be a list')
        parsed[key] = [_window(w) for w in rows]
    return dict(source=source, all=[_window(w) for w in common], channels=parsed,
                extra=[window_argument(w) if isinstance(w, str) else _window(w) for w in extra])


def _window_report(frame, candidate, windows):
    rows = ([(w, 'all') for w in windows['all']] +
            [(w, 'target_channel') for w in windows['channels'].get(candidate['target_channel'], [])] +
            [(w, 'command_line') for w in windows['extra']])
    used = []
    for window, source in rows:
        if max(window['atoms']) > len(frame.symbols):
            raise ValueError('Window atom index exceeds candidate atom count')
        distance = geo.atom_distance(frame.coordinates, window['atoms'])
        used.append(dict(window, source=source, distance_angstrom=distance,
                         status='pass' if window['min'] <= distance <= window['max'] else 'outside'))
    return dict(source=windows['source'], used=used, status='checked' if used else 'unset')


def _same_geometry(left, right):
    return left.symbols == right.symbols and all(
        abs(a - b) <= 1e-4 for xyz, ref in zip(left.coordinates, right.coordinates) for a, b in zip(xyz, ref))


def _stereo(root, frame, filename, identity, expected):
    if filename is None:
        return dict(status='not_requested')
    raw = v2.read_bytes(filename, 1024 * 1024)
    data = json.loads(raw)
    error = 'labels.json structure differs from ts_stereo_label.py; stop for manual review'
    if (not isinstance(data, dict) or data.get('atom_index_base') != 1 or
            data.get('geometry') not in ('input', 'final') or not isinstance(data.get('attempts'), list)):
        raise ValueError(error)
    ids = []
    for item in data['attempts']:
        if (not isinstance(item, dict) or not isinstance(item.get('attempt'), str) or
                not isinstance(item.get('product_configuration'), str) or
                not isinstance(item.get('geometry_source'), dict)):
            raise ValueError(error)
        ids.append(item['attempt'])
        for key in ('product_centers', 'catalyst_centers'):
            centers = item.get(key)
            if not isinstance(centers, list) or any(
                    not isinstance(c, dict) or c.get('label') not in ('R', 'S', 'unknown', 'needs_review') or
                    not isinstance(c.get('element'), str) or type(c.get('reference_atom')) is not int
                    for c in centers):
                raise ValueError(error)
        configuration = ';'.join(f"{c['element']}{c['reference_atom']}:{c['label']}" for c in item['product_centers'])
        if item['product_configuration'] != configuration:
            raise ValueError(error + '; product_configuration disagrees with center labels')
    if len(ids) != len(set(ids)) or identity not in ids:
        raise ValueError(error + '; need a unique matching Attempt entry')
    item = data['attempts'][ids.index(identity)]
    reference, provenance, _ = _manifest_frame(root, identity, stereo=True)
    if reference is None or not _same_geometry(frame, reference):
        raise ValueError('Stereo Attempt input geometry differs from candidate; labels are not for this candidate')
    # The producer defaults to final geometry. Bind that source too, otherwise
    # labels from an optimized geometry could be attached to a different input.
    source = item['geometry_source']
    relative = f'attempts/{identity}/' + ('manifest.json' if data['geometry'] == 'input' else 'final_input.xyz')
    pointer = provenance.get('json_pointer') if data['geometry'] == 'input' else None
    if source.get('path') != relative or source.get('json_pointer') != pointer:
        raise ValueError(error + '; unexpected geometry_source')
    source_raw = v2.read_bytes(study.local_path(root, root / relative), 1024 * 1024)
    if sha256(source_raw).hexdigest() != source.get('sha256'):
        raise ValueError('Stereo geometry source hash mismatch; requires manual handling')
    if data['geometry'] == 'final' and not _same_geometry(frame, _xyz_frame(source_raw)):
        raise ValueError('Stereo labels use a different final geometry; labels are not for this candidate')
    centers = item['product_centers'] + item['catalyst_centers']
    actual = item['product_configuration']
    unresolved = (not item['product_centers'] or not actual.strip() or
                  len({c['reference_atom'] for c in item['product_centers']}) != len(item['product_centers']) or
                  any(c['label'] in ('unknown', 'needs_review') for c in centers))
    status = 'pending' if unresolved else 'match' if actual == expected else 'other_channel'
    return dict(status=status, attempt=identity, labels_sha256=sha256(raw).hexdigest(),
                geometry_source=source, expected_label=expected, product_configuration=actual,
                reason={'pending': '待判', 'match': '立体标签一致',
                        'other_channel': '可能属于其他通道'}[status])


def diagnose_candidate(root, obj, candidate, *, registration_order, windows,
                       reference_attempt=None, stereo_json=None, stereo_attempt=None, expected_label=None):
    path = study.local_path(root, root / candidate['file'])
    raw = v2.read_bytes(path, 1024 * 1024)
    if sha256(raw).hexdigest() != candidate['sha256']:
        raise ValueError('Candidate archive hash mismatch; data damaged, requires manual handling')
    frame = _xyz_frame(raw)
    reference = reference_attempt or candidate['parent']['attempt']
    integrity, provenance = _integrity(root, obj, candidate, frame, reference)
    distances = _window_report(frame, candidate, windows)
    geometry = _geometry(frame, [row['atoms'] for row in distances['used']])
    stereo = _stereo(root, frame, stereo_json, stereo_attempt, expected_label)
    rejected, flags, unchecked = [], [], []
    for field, check in integrity.items():
        entry = dict(category='input_integrity', field=field, message=check['reason'])
        if check['status'] == 'reject':
            rejected.append(entry)
        elif check['status'] == 'unchecked':
            unchecked.append(field)
            flags.append(dict(entry, message='未核对：' + check['reason']))
    rejected.extend(dict(category='geometry_damage', message='几何损坏', **pair) for pair in geometry['damage'])
    flags.extend(dict(category='ordinary_clash', message='疑似普通冲突；' + pair['recommendation'], **pair)
                 for pair in geometry['clashes'])
    flags.extend(dict(category='distance_window', message='距离超出人设窗口', **row)
                 for row in distances['used'] if row['status'] == 'outside')
    if not distances['used']:
        flags.append(dict(category='distance_window', message='未设窗口'))
    if stereo['status'] in ('pending', 'other_channel'):
        flags.append(dict(category='stereo', message=stereo['reason']))
    return dict(candidate=candidate['id'], object=obj['id'], origin=candidate['origin'],
                target_channel=candidate['target_channel'], candidate_sha256=candidate['sha256'],
                registration_order=registration_order, reference=provenance,
                integrity=integrity, geometry=geometry, windows=distances, stereo=stereo,
                verdict='rejected' if rejected else 'flagged' if flags else 'clean',
                reject_reasons=rejected, flags=flags, unchecked=unchecked,
                counts=dict(reject_reasons=len(rejected), flags=len(flags), unchecked=len(unchecked),
                            geometry_damage=len(geometry['damage']), ordinary_clashes=len(geometry['clashes']),
                            reaction_center_pairs=len(geometry['reaction_center_pairs']),
                            windows=len(distances['used']),
                            outside_windows=sum(w['status'] == 'outside' for w in distances['used'])),
                notice=NOTICE, order_notice=ORDER_NOTICE, atom_order_limitation=ORDER_LIMIT)


def diagnose(root, *, object, candidate=None, all_candidates=False, channel=None,
             reference_attempt=None, windows=None, window=(),
             stereo_json=None, stereo_attempt=None, expected_label=None):
    if sum((candidate is not None, bool(all_candidates), channel is not None)) != 1:
        raise ValueError('Select exactly one of --candidate, --all, --channel')
    stereo_options = [stereo_json, stereo_attempt, expected_label]
    if any(v is not None for v in stereo_options) and not all(v is not None for v in stereo_options):
        raise ValueError('--stereo-json, --stereo-attempt and --expected-label must be supplied together')
    if candidate is None and (reference_attempt is not None or stereo_json is not None):
        raise ValueError('Reference and stereo options require a single --candidate')
    if expected_label is not None and not expected_label.strip():
        raise ValueError('--expected-label must not be empty')
    root = catalog.resolve_study(root)
    window_config = _windows(root, windows, window)
    with catalog.catalog_lock(root):
        raw, events, _ = catalog.read_journal(root)
        objects, _ = catalog.replay(events)
        obj = v2.find(list(objects.values()), object, 'object')
        v2.initialize(obj)
        selected = obj['candidates']
        if candidate:
            selected = [v2.find(selected, candidate, 'candidate')]
        elif channel:
            entry = v2.find(obj['channels'], channel, 'channel')
            selected = [c for c in selected if c['id'] in entry['candidate_ids']]
        order = {c['id']: i for i, c in enumerate(obj['candidates'], 1)}
        results = [diagnose_candidate(root, obj, c, registration_order=order[c['id']], windows=window_config,
                                     reference_attempt=reference_attempt, stereo_json=stereo_json,
                                     stereo_attempt=stereo_attempt, expected_label=expected_label) for c in selected]
    groups = {'rejected': 0, 'flagged': 1, 'clean': 2}
    results.sort(key=lambda c: (groups[c['verdict']], c['counts']['flags'], c['registration_order']))
    return dict(schema='ag-g0/1', object=object, journal_sha256=sha256(raw).hexdigest(),
                candidates=results, order=[c['candidate'] for c in results],
                counts={group: sum(c['verdict'] == group for c in results) for group in groups},
                notice=NOTICE, order_notice=ORDER_NOTICE)


def bounded_diagnosis(report):
    """Keep verdicts and original counts when pair/window details exceed 64 KiB."""
    result = deepcopy(report)
    if len(catalog.encode(result)) <= MAX_DIAGNOSIS_BYTES:
        return result
    result.update(truncated=True, truncation_note='已截断；结论与各项原始计数保留')
    lists = [result['reject_reasons'], result['flags'], result['geometry']['damage'],
             result['geometry']['clashes'], result['geometry']['reaction_center_pairs'], result['windows']['used']]
    for check in result['integrity'].values():
        lists.extend(v for v in check.values() if isinstance(v, list))
    while len(catalog.encode(result)) > MAX_DIAGNOSIS_BYTES and any(lists):
        largest = max(lists, key=lambda rows: len(catalog.encode(rows)))
        del largest[len(largest) // 2:]
    if len(catalog.encode(result)) > MAX_DIAGNOSIS_BYTES:
        result = {k: result[k] for k in ('candidate', 'object', 'verdict', 'counts', 'candidate_sha256',
                                        'notice', 'order_notice', 'truncated', 'truncation_note')}
        result['integrity_statuses'] = {k: v['status'] for k, v in report['integrity'].items()}
    return result


def run(args):
    if (args.upgrade_catalog or args.dry_run) and not args.record:
        raise ValueError('--upgrade-catalog and --dry-run require --record')
    report = diagnose(args.study, object=args.object, candidate=args.candidate,
                      all_candidates=args.all, channel=args.channel, reference_attempt=args.reference_attempt,
                      windows=args.windows, window=args.window, stereo_json=args.stereo_json,
                      stereo_attempt=args.stereo_attempt, expected_label=args.expected_label)
    code = int(bool(report['counts']['rejected']))
    if args.record:
        try:
            report['record'] = catalog.register_candidate_results(
                args.study, [dict(object=args.object, candidate=c['candidate'], diagnosis=bounded_diagnosis(c))
                             for c in report['candidates']], journal_sha256=report['journal_sha256'],
                dry_run=args.dry_run, upgrade_catalog=args.upgrade_catalog)
        except (ValueError, OSError) as exc:
            # Keep the completed report visible even when recording is refused.
            report['record'] = dict(error=str(exc))
            code = 2
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    else:
        print(NOTICE + '\n' + ORDER_NOTICE + '\n' + ORDER_LIMIT)
        for c in report['candidates']:
            print(f"\n{c['candidate']}: {c['verdict']} (reject={c['counts']['reject_reasons']}, flags={c['counts']['flags']})")
            for field, check in c['integrity'].items():
                print(f"  {field}: " + json.dumps(check, ensure_ascii=False))
            for field in ('reference', 'windows', 'stereo'):
                print(f"  {field}: " + json.dumps(c[field], ensure_ascii=False))
            if c['geometry']['reaction_center_pairs']:
                print('  geometry.reaction_center_pairs: ' +
                      json.dumps(c['geometry']['reaction_center_pairs'], ensure_ascii=False))
            for entry in c['reject_reasons'] + c['flags']:
                print('  ' + json.dumps(entry, ensure_ascii=False))
        print('order: ' + ', '.join(report['order']))
        if args.record:
            print('record: ' + json.dumps(report['record'], ensure_ascii=False))
        if report.get('record', {}).get('error'):
            print(report['record']['error'], file=sys.stderr)
    return code


def register(subparsers):
    parser = subparsers.add_parser('g0', description=__doc__)
    parser.add_argument('study')
    parser.add_argument('--object', required=True)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument('--candidate')
    selection.add_argument('--all', action='store_true')
    selection.add_argument('--channel')
    for option in ('reference-attempt', 'windows', 'stereo-json', 'stereo-attempt', 'expected-label'):
        parser.add_argument('--' + option)
    parser.add_argument('--window', action='append', default=[])
    for option in ('record', 'upgrade-catalog', 'dry-run', 'json'):
        parser.add_argument('--' + option, action='store_true')
    parser.set_defaults(func=run)
