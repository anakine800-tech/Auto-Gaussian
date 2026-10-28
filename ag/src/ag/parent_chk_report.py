"""Local checkpoint provenance report; never inspect checkpoint contents or submit.

Keep execution evidence, historical byte linkage and scientific suitability separate.
The local collector prevents mixed revisions and the paired writer prevents partial
publication; neither adds a submission requirement.
"""
from contextlib import ExitStack, contextmanager
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re
import stat
import sys

from ag import __version__, attempt, gaussian_input
from ag._parse_outputs import expected_vibrational_modes, gaussian_job_sections, gaussian_orientation
from ag.geometry import Frame, finite_number
from ag.mode_review import read_modes
from ag.study import identifier, local_path

NOTICE = '内部力常数未核验；正常 Freq、坐标吻合和历史复制记录均不证明当前 chk 内含可用力常数。'
IDENTITY = 'unknown：固定原子行比较不能证明化学身份；同元素交换、对称或相同位置可能无法区分。'
TOLERANCE = 1e-4  # Existing parent_chk fixed-row Euclidean distance, in angstrom.


def _require(condition, message):
    if not condition:
        raise ValueError(message)


@contextmanager
def _directory(path):
    # Descriptor traversal also rejects an ancestor replaced by a symlink.
    with ExitStack() as stack:
        fd = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY)
        stack.callback(os.close, fd)
        for part in path.parts[1:]:
            fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            stack.callback(os.close, fd)
        yield fd


class _Sources:
    def __init__(self, root):
        self.root, self.saved = root, {}

    def read(self, path, *, optional=False):
        path = local_path(self.root, path)
        try:
            with _directory(path.parent) as directory:
                fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
                with os.fdopen(fd, 'rb') as handle:
                    _require(stat.S_ISREG(os.fstat(handle.fileno()).st_mode), 'Source must be a regular file')
                    raw = handle.read()
        except FileNotFoundError:
            if not optional:
                raise
            raw = None
        if path in self.saved:
            _require(self.saved[path] == raw, 'Source changed during report collection')
        self.saved[path] = raw
        return raw

    def json(self, path, *, optional=False):
        raw = self.read(path, optional=optional)
        if raw is None:
            return None
        value = json.loads(raw)
        _require(isinstance(value, dict), 'Expected a JSON object')
        return value

    def ref(self, path, **location):
        raw = self.saved[path]
        return dict(path=path.relative_to(self.root).as_posix(),
                    sha256=sha256(raw).hexdigest() if raw is not None else None,
                    size=len(raw) if raw is not None else None,
                    status='local_bytes_read' if raw is not None else 'missing', **location)

    def verify(self):
        for path in list(self.saved):
            self.read(path, optional=self.saved[path] is None)


def _filename(name):
    _require(isinstance(name, str) and bool(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', name)),
             'Expected a plain filename')
    return name


def _frame(rows):
    symbols = gaussian_input.cartesian(rows, first_line=1)
    _require(bool(symbols), 'Missing Cartesian geometry')
    return Frame(tuple(symbols), tuple(tuple(finite_number(x) for x in row.split()[1:]) for row in rows))


def _xyz(raw):
    lines = raw.decode('utf-8').splitlines()
    _require(len(lines) >= 3 and lines[0].isdigit() and int(lines[0]) == len(lines) - 2,
             'Expected one complete XYZ geometry')
    return _frame(lines[2:])


def _geometry(frame, source):
    return dict(elements=list(frame.symbols), coordinates=[list(row) for row in frame.coordinates],
                source=source, units='angstrom')


def _compare(left, right):
    result = dict(status='unknown', tolerance_angstrom=TOLERANCE,
                  rule='fixed atom rows; no rotation, translation or permutation',
                  atom_identity=IDENTITY)
    if left is None or right is None:
        return dict(result, reason='缺少可比较的默认 Å 坐标')
    if left['elements'] != right['elements']:
        return dict(result, status='different', reason='原子数或固定行元素不同')
    distances = [math.dist(a, b) for a, b in zip(left['coordinates'], right['coordinates'])]
    _require(all(math.isfinite(value) for value in distances), 'Non-finite coordinate displacement')
    changed = [i for i, value in enumerate(distances, 1) if value > TOLERANCE]
    return dict(result, status='different' if changed else 'matched', different_rows=changed,
                max_displacement_angstrom=max(distances), sources=[left['source'], right['source']])


def _load(sources, value):
    directory = local_path(sources.root, sources.root / 'attempts' / identifier(value))
    manifest_path = directory / 'manifest.json'
    manifest = sources.json(manifest_path)
    _require(manifest.get('attempt_id') == value and manifest.get('study_id') == sources.root.name,
             'Manifest identity differs from the exact study/Attempt')
    _require(manifest.get('template') == 'gaussian', 'Expected an exact Gaussian Attempt')
    records = manifest.get('inputs')
    _require(isinstance(records, list) and bool(records), 'Missing input records')
    files = {}
    for record in records:
        _require(isinstance(record, dict), 'Invalid input record')
        name = _filename(record.get('name'))
        _require(name not in files, 'Duplicate input filename')
        _require(name in ('job.pbs', 'job.slurm') or Path(name).suffix.lower() in ('.gjf', '.com'),
                 'Unsupported Gaussian input attachment; checkpoint binaries are never read')
        files[name] = sources.read(directory / 'inputs' / name)
    actual, digest = attempt.bundle(files)
    _require(actual == records and digest == manifest.get('bundle_sha256'), 'Input bundle/hash mismatch')
    names = [name for name in files if Path(name).suffix.lower() in ('.gjf', '.com')]
    _require(len(names) == 1, 'Expected one Gaussian input')
    name = names[0]
    text = files[name].decode('utf-8')
    science = gaussian_input.validate(text, manifest['cores'], manifest['mem_gb'],
                                       parent_chk='parent_chk' in manifest)
    declared = manifest.get('science', {})
    _require(isinstance(declared, dict), 'Invalid science record')
    _require(all(declared[key] == science[key] for key in science if key in declared),
             'Scientific manifest differs from verified input')
    source = sources.ref(directory / 'inputs' / name, start_line=1, end_line=len(text.splitlines()))
    chk = []
    for i, line in enumerate(text.splitlines(), 1):
        if not line.startswith('%'):
            break
        if match := re.fullmatch(r'%chk\s*=\s*(.+)', line, re.I):
            chk.append(dict(name=match[1].strip(), source=sources.ref(directory / 'inputs' / name, line=i)))
    structures = science.get('structures', [science])
    units_known = not re.search(r'\bunits?\b', science['route'], re.I)
    geometries = [_geometry(_frame(item['geometry'].splitlines()), dict(source, structure=i))
                  for i, item in enumerate(structures, 1)] if units_known else []
    result = dict(attempt=value, manifest=sources.ref(manifest_path, pointer=''), input=source,
                  input_bundle='verified', route=science['route'],
                  method_basis_tokens=re.findall(r'(?<!\S)[^\s#/]+/[^\s]+', science['route']),
                  charge=science['charge'], multiplicity=science['multiplicity'],
                  explicit_geometries=geometries, coordinate_units='angstrom' if units_known else 'not_compared',
                  checkpoint=chk[0] if chk else None,
                  manifest_method_basis=dict(value=declared.get('method_basis'),
                                             source=sources.ref(manifest_path, pointer='/science/method_basis')))
    return directory, manifest, result


def _fetch_records(sources, directory, manifest, log):
    """Only the existing fetch-add-missing / fetch-incomplete layouts are read."""
    rows = []
    with _directory(directory) as fd:
        names = sorted(name for name in os.listdir(fd)
                       if re.fullmatch(r'fetch-(?:add-missing|incomplete)-[^/]+\.json', name))
    for name in names:
        path = directory / name
        record = sources.json(path)
        _require(record.get('attempt_id') == directory.name and isinstance(record.get('outputs'), dict),
                 'Fetch record binding/outputs invalid')
        if name.startswith('fetch-incomplete-'):
            _require(record.get('complete') is True
                     and record.get('manifest_sha256') == sources.ref(directory / 'manifest.json')['sha256']
                     and record.get('cluster') == manifest.get('cluster', 'default')
                     and record.get('scheduler') == manifest.get('scheduler', 'pbs'),
                     'Incomplete fetch manifest binding mismatch')
            missing = record.get('missing')
            _require(isinstance(missing, list) and all(isinstance(item, str) for item in missing)
                     and not set(missing) & record['outputs'].keys(),
                     'Invalid incomplete fetch missing list')
            for item in missing:
                _require(item == log.name or item in ('job.pbs.out', 'job.slurm.out', 'job.slurm.err'),
                         'Unsupported incomplete fetch output name')
                target = directory / 'outputs' / _filename(item)
                _require(sources.read(target, optional=True) is None, 'Recorded missing output now exists')
        info = record['outputs'].get(log.name)
        if info is not None:
            _require(isinstance(info, dict), 'Invalid fetched log hash record')
            raw = sources.read(log)
            _require((len(raw), sha256(raw).hexdigest()) == (info.get('size'), info.get('sha256')),
                     'Log hash/size differs from fetch record')
            rows.append(sources.ref(path, pointer='/outputs/' + log.name))
    return rows


def _printed(block, source):
    patterns = dict(method=r'\s*SCF Done:\s+E\(([^)]+)\)',
                    basis=r'\s*Standard basis:\s*(.+)',
                    charge_multiplicity=r'\s*Charge\s*=\s*(-?\d+)\s+Multiplicity\s*=\s*(\d+)')
    result = {}
    for key, pattern in patterns.items():
        result[key] = [dict(value=list(match.groups()), source=dict(source, line=source['start_line'] + i))
                       for i, line in enumerate(block.splitlines()) if (match := re.match(pattern, line))]
    return result


def _orientation(text, kind, source):
    xyz = gaussian_orientation(text, kind)
    if xyz is None:
        return None
    matches = list(re.finditer(r'(?m)^[ \t]*' + kind + r' orientation:', text))
    line = source['start_line'] + text[:matches[-1].start()].count('\n')
    return _geometry(_xyz(xyz.encode()), dict(source, line=line, orientation=kind.lower()))


def _frequency(sources, directory, manifest, parent):
    name = Path(parent['input']['path']).stem + '.log'
    log = directory / 'outputs' / name
    raw = sources.read(log, optional=True)
    receipts = _fetch_records(sources, directory, manifest, log)
    result = dict(status='source_unverifiable', log=sources.ref(log), historical_hash_records=receipts,
                  hash_note='本次本地字节哈希；无历史取回哈希时不能核对历史远程字节。',
                  sections=[], selected_section=None, input_geometry=None, frequency_geometry=None)
    if raw is None:
        return dict(result, reason='缺少与父输入同名的本地日志')
    text = raw.decode('utf-8').replace('\r\n', '\n').replace('\r', '\n')
    sections, warnings = gaussian_job_sections(text)
    result['section_warnings'] = warnings
    executed = []
    for section in sections:
        block_raw = b''.join(raw.splitlines(keepends=True)[section['start_line'] - 1:section['end_line']])
        block = block_raw.decode('utf-8').replace('\r\n', '\n').replace('\r', '\n')
        ref = dict(sources.ref(log), start_line=section['start_line'], end_line=section['end_line'],
                   section=section['index'], section_sha256=sha256(block_raw).hexdigest())
        anchors = [section['start_line'] + i for i, line in enumerate(block.splitlines())
                   if re.match(r'\s*(?:Harmonic frequencies\b|Frequencies\s+--)', line)]
        row = dict(**section, source=ref, frequency_lines=anchors, printed=_printed(block, ref),
                   last_input_geometry=_orientation(block, 'Input', ref),
                   last_standard_geometry=_orientation(block, 'Standard', ref))
        result['sections'].append(row)
        if anchors:
            executed.append((row, block_raw, block))
    if warnings or len(executed) > 1:
        return dict(result, status='ambiguous_or_incomplete', reason='段边界或多个频率段无法唯一归属')
    if not executed:
        pending = any(re.search(r'\bfreq\b', s['route'] or '', re.I)
                      and s['termination'] != 'normal' for s in sections)
        # A monatomic Freq may print only thermochemistry. This report does not
        # turn that limited format into Cartesian force-constant evidence.
        pending |= bool(re.search(r'(?m)^\s*Zero-point correction=', text))
        return dict(result, status='ambiguous_or_incomplete' if pending else 'not_found',
                    reason='没有实际完成的振动频率块；route 或其他段正常结束不作为执行证明')
    row, block_raw, block = executed[0]
    if row['termination'] != 'normal':
        return dict(result, status='ambiguous_or_incomplete', reason='实际频率段未正常结束')
    # A later pending Freq must not inherit this section's completed evidence.
    if any(s['index'] > row['index'] and re.search(r'\bfreq\b', s['route'] or '', re.I)
           for s in sections):
        return dict(result, status='ambiguous_or_incomplete', reason='存在后续尚无可核验振动块的 Freq 段')
    try:
        elements, coords, frequencies, _, orientation = read_modes(block_raw)
    except ValueError as exc:
        return dict(result, status='ambiguous_or_incomplete', reason=str(exc))
    count = expected_vibrational_modes(len(elements), coords)
    if count is None or len(frequencies) != count:
        return dict(result, status='ambiguous_or_incomplete', reason='振动模式数不完整或无法确定')
    prefix = block[:re.search(r'(?m)^[ \t]*Harmonic frequencies\b', block).start()]
    return dict(result, status='normal_frequency_found', reason='唯一正常结束段的实际振动块和模式数可核验；适用性仍待人审阅',
                selected_section=row['index'], mode_count=count,
                input_geometry=_orientation(prefix, 'Input', row['source']),
                frequency_geometry=_geometry(Frame(tuple(elements), tuple(map(tuple, coords.tolist()))),
                                             dict(row['source'], orientation=orientation)))


def _saved(sources, directory, frequency):
    facts_path = directory / 'facts.json'
    facts = sources.json(facts_path, optional=True)
    result = dict(facts=dict(source=sources.ref(facts_path), role='saved claims only; execution comes from raw log'),
                  geometries={})
    if facts is not None:
        for key, filename in (('final_geometry', 'final.xyz'), ('final_input_geometry', 'final_input.xyz')):
            _require(facts.get(key) in (None, filename), 'Unsupported/unsafe saved geometry reference')
        fields = ('termination', 'route', 'charge', 'multiplicity', 'n_imag', 'fact_sources', 'job_sections',
                  'final_geometry', 'final_input_geometry', 'final_geometry_orientation', 'final_input_geometry_orientation')
        result['facts']['fields'] = {key: dict(value=facts[key], source=sources.ref(facts_path, pointer='/' + key))
                                     for key in fields if key in facts}
        # These are claims for review, not evidence borrowed from a stale cache.
        keys = ('index', 'route', 'start_line', 'end_line', 'termination')
        cached = facts.get('job_sections')
        actual = frequency['sections']
        result['facts']['sections_match_log'] = (
            [{k: s.get(k) for k in keys} for s in cached] == [{k: s[k] for k in keys} for s in actual]
            if isinstance(cached, list) and all(isinstance(s, dict) for s in cached) and actual else None)
    for name, kind in (('final_input.xyz', 'input'), ('final.xyz', 'standard')):
        path = directory / name
        raw = sources.read(path, optional=True)
        if raw is None:
            result['geometries'][name] = dict(status='missing', source=sources.ref(path))
            continue
        geometry = _geometry(_xyz(raw), sources.ref(path, start_line=3, end_line=len(raw.splitlines())))
        matches = [s['index'] for s in frequency['sections']
                   if _compare(geometry, s['last_' + kind + '_geometry'])['status'] == 'matched']
        result['geometries'][name] = dict(status='present', geometry=geometry,
                                        matching_log_sections=matches,
                                        origin='coordinates_match_log' if matches else 'source_unverifiable')
        key = 'final_input_geometry' if kind == 'input' else 'final_geometry'
        claimed = facts.get('fact_sources', {}).get(key) if facts and isinstance(facts.get('fact_sources'), dict) else None
        result['geometries'][name]['saved_source_claim'] = dict(
            section=claimed, agrees_with_coordinates=claimed in matches if claimed is not None else None,
            source=sources.ref(facts_path, pointer='/fact_sources/' + key))
    return result


def _binding(sources, parent_manifest, parent, child_manifest, child):
    if child is None:
        return dict(status='not_requested', relation=None)
    attachment = child_manifest.get('parent_chk')
    source = dict(child['manifest'], pointer='/parent_chk')
    if attachment is None:
        return dict(status='missing', relation=None, source=source)
    _require(isinstance(attachment, dict), 'Invalid parent_chk relation')
    expected = dict(attempt_id=parent['attempt'], source_name=(parent['checkpoint'] or {}).get('name'),
                    target_name='parent.chk', cluster=parent_manifest.get('cluster', 'default'))
    parents = child_manifest.get('parents', [])
    _require(isinstance(parents, list) and all(isinstance(p, dict) for p in parents), 'Invalid parents list')
    differences = [key for key, value in expected.items() if value is None or attachment.get(key) != value]
    if child_manifest.get('cluster', 'default') != expected['cluster']:
        differences.append('child_cluster')
    if not any(p.get('attempt_id') == parent['attempt'] for p in parents):
        differences.append('parents')
    return dict(status='mismatch' if differences else 'matched', relation=attachment, source=source,
                different_fields=differences, parents_source=dict(child['manifest'], pointer='/parents'))


def _copies(sources, parent, child, binding):
    path = sources.root / 'journal.jsonl'
    raw = sources.read(path, optional=True)
    result = dict(status='not_found', records=[], source=sources.ref(path),
                  limitation='verified 仅记录复制当时源和目标共同的 size/SHA-256；未读取当前 chk，也未检查内部记录。')
    if raw is None or child is None:
        return result
    for line, text in enumerate(raw.decode('utf-8').splitlines(), 1):
        if not text.strip():
            continue
        record = json.loads(text)
        _require(isinstance(record, dict), 'Invalid journal row')
        detail = record.get('detail') or {}
        if record.get('action') != 'copy_parent_chk':
            continue
        _require(isinstance(detail, dict), 'Invalid copy journal detail')
        if record.get('attempt_id') != child['attempt'] and detail.get('target_attempt') != child['attempt']:
            continue
        expected = dict(source_attempt=parent['attempt'], source_name=(parent['checkpoint'] or {}).get('name'),
                        target_attempt=child['attempt'], target_name='parent.chk')
        differences = [key for key, value in expected.items() if value is None or detail.get(key) != value]
        if record.get('attempt_id') != child['attempt'] or binding['status'] != 'matched':
            differences.append('child_binding')
        size, digest = detail.get('size'), detail.get('sha256')
        complete = type(size) is int and size > 0 and isinstance(digest, str) and re.fullmatch(r'[a-f0-9]{64}', digest)
        status = ('binding_mismatch' if differences else 'historically_verified' if
                  record.get('result') == 'verified' and complete else 'unverified')
        result['records'].append(dict(status=status, result=record.get('result'), timestamp=record.get('ts'),
                                      detail={k: detail.get(k) for k in (*expected, 'size', 'sha256')},
                                      different_fields=differences, source=sources.ref(path, line=line)))
    rows = result['records']
    hashes = {(r['detail']['size'], r['detail']['sha256']) for r in rows if r['status'] == 'historically_verified'}
    result['status'] = ('binding_mismatch' if any(r['status'] == 'binding_mismatch' for r in rows) else
                        'conflicting_records' if len(hashes) > 1 else 'historically_verified' if hashes else
                        'unverified' if rows else 'not_found')
    return result


def _publish(parent, payloads):
    # Adapted from fragments' exclusive local writer. Roll back only this call's
    # inodes on collision/write failure; never remove or replace older outputs.
    with _directory(parent) as directory:
        created = []
        try:
            with ExitStack() as stack:
                handles = []
                for name, content in payloads.items():
                    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
                    info = os.fstat(fd)
                    created.append((name, info.st_dev, info.st_ino))
                    handles.append((stack.enter_context(os.fdopen(fd, 'wb')), content))
                for handle, content in handles:
                    handle.write(content)
                    handle.flush()
                    os.fsync(handle.fileno())
        except BaseException:
            for name, device, inode in reversed(created):
                try:
                    info = os.stat(name, dir_fd=directory, follow_symlinks=False)
                    if (info.st_dev, info.st_ino) == (device, inode):
                        os.unlink(name, dir_fd=directory)
                except FileNotFoundError:
                    pass
            raise


def markdown(report):
    lines = ['# 父 checkpoint 证据报告', '', NOTICE, '',
             f"报告生成：{report['report_status']}；频率事实：{report['frequency']['status']}。",
             f"父子绑定：{report['checkpoint']['binding']['status']}；历史复制：{report['checkpoint']['copies']['status']}。",
             '', '科学适用性：待人工审阅；本报告不选择方法、不生成 route、不授权提交。', '', IDENTITY]
    for title, key in (('父输入', 'parent'), ('子输入', 'child'), ('频率段与实际打印条件', 'frequency'),
                       ('已存 facts 与几何', 'saved'), ('固定行框架比较', 'frame_comparisons'),
                       ('checkpoint 关联与历史复制', 'checkpoint'), ('审阅差异', 'review_differences'),
                       ('来源清单', 'sources')):
        lines.extend(['', '## ' + title, '', '```json', json.dumps(report[key], ensure_ascii=False, indent=2), '```'])
    return '\n'.join(lines) + '\n'


def create(parent_attempt, study, out, child_attempt=None):
    root = Path(study).expanduser().absolute()
    root = local_path(root, root)
    _require(root.is_dir(), '--study must be an existing local study directory')
    identifier(root.name)
    target = Path(out).expanduser()
    target = local_path(root / 'analyses', target if target.is_absolute() else root / target)
    _require(target.suffix == '.json', '--out must be a new .json under study analyses/')
    for path in (target, target.with_suffix('.md')):
        local_path(root / 'analyses', path)
        if path.exists():
            raise FileExistsError('Output already exists: ' + path.name)
    sources = _Sources(root)
    directory, manifest, parent = _load(sources, parent_attempt)
    child_manifest = child = None
    if child_attempt is not None:
        _require(child_attempt != parent_attempt, 'Child must be distinct from parent')
        _, child_manifest, child = _load(sources, child_attempt)
    frequency = _frequency(sources, directory, manifest, parent)
    saved = _saved(sources, directory, frequency)
    binding = _binding(sources, manifest, parent, child_manifest, child)
    copies = _copies(sources, parent, child, binding)
    comparisons = []
    refs = dict(frequency_input=frequency['input_geometry'], frequency_printed=frequency['frequency_geometry'],
                saved_input=saved['geometries']['final_input.xyz'].get('geometry'),
                saved_final=saved['geometries']['final.xyz'].get('geometry'))
    comparisons.append(dict(left='frequency_input', right='saved_input', **_compare(refs['frequency_input'], refs['saved_input'])))
    if child is not None:
        for i, geometry in enumerate(child['explicit_geometries'] or [None], 1):
            for label, ref in refs.items():
                comparisons.append(dict(left=label, right=f'child_structure_{i}', **_compare(ref, geometry)))
    differences = []
    if child:
        for key in ('method_basis_tokens', 'charge', 'multiplicity'):
            differences.append(dict(field=key, parent=parent[key], child=child[key], equal=parent[key] == child[key]))
    if frequency['selected_section'] is not None:
        selected = frequency['sections'][frequency['selected_section'] - 1]
        differences.append(dict(field='frequency_execution_conditions',
                                parent_input_route=parent['route'], frequency_route=selected['route'],
                                child_input_route=child['route'] if child else None,
                                actual_printed=selected['printed'],
                                note='打印方法/基组/电荷/多重度按各自段来源列示；缺项未知，不从输入或其他段补齐。'))
    report = dict(ag_version=__version__, report_status='complete', parent=parent, child=child,
                  frequency=frequency, saved=saved, frame_comparisons=comparisons,
                  checkpoint=dict(parent_input_chk=parent['checkpoint'], binding=binding, copies=copies,
                                  internal_force_constants='unverified', note=NOTICE),
                  scientific_suitability='requires_human_review', review_differences=differences,
                  frame_note='沿用固定行、逐原子距离 ≤ 1e-4 Å；NoSymm 的 final.xyz 仅列示比较，不作提交准入结论。')
    sources.verify()
    report['sources'] = [sources.ref(path) for path in sources.saved]
    content = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    _publish(target.parent, {target.name: content.encode(), target.with_suffix('.md').name: markdown(report).encode()})
    return report


def run(args):
    try:
        result = create(args.parent_attempt, args.study, args.out, args.child)
    except (TypeError, IndexError, AttributeError) as exc:
        raise ValueError('Invalid local evidence record structure') from exc
    except ImportError:
        print('parent-chk-report requires local chemistry dependencies (cclib/numpy)', file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    else:
        print(f"报告生成完成；频率事实：{result['frequency']['status']}。{NOTICE}")
    return 0


def register(subparsers):
    parser = subparsers.add_parser('parent-chk-report', help='Report local parent checkpoint evidence; no binary inspection')
    parser.add_argument('parent_attempt')
    parser.add_argument('--study', required=True, help='Existing local study directory (no configuration lookup)')
    parser.add_argument('--child', help='Exact child Gaussian Attempt in this study')
    parser.add_argument('--out', required=True, help='New .json under study analyses/; also creates matching .md')
    parser.add_argument('--json', action='store_true')
    parser.set_defaults(func=run)
