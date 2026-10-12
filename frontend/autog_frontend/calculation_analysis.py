"""Offline display extraction. Never a scientific validator or execution owner.

Only complete geometry + SCF + convergence-table cycles become optimization
points. Other SCF records remain observations; Link1/restarts never join curves.
"""
import math
import re
from hashlib import sha256

SCHEMA = 'autog-calculation-analysis/1'
NUM = r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[DEde][+-]?\d+)?'
LABELS = ('Maximum Force', 'RMS Force', 'Maximum Displacement', 'RMS Displacement')
ERRORS = (
    ('scf-convergence', r'Convergence failure|SCF has not converged', 'SCF 未收敛', '检查电子态、初始猜测与 SCF 设置；先准备新的输入方案。'),
    ('optimization-limit', r'Number of steps exceeded|Optimization stopped', '优化停止或达到步数上限', '查看优化轨迹及最后结构，再决定续算方案。'),
    ('memory', r'(?i)not enough memory|out of memory|galloc:.*failed', '内存分配失败', '核对 Gaussian 内存设置与申请资源。'),
    ('disk', r'(?i)No space left on device|Erroneous write|FileIO operation on non-existent file', '文件或磁盘 I/O 错误', '核对原始错误上下文和工作目录状态。'),
    ('input', r'QPErr|End of file in ZSymb|Unrecognized atomic symbol', '输入读取错误', '检查关键词、坐标、电荷与多重度。'),
    ('termination', r'Error termination', 'Gaussian 错误终止', '查看前文；终止标记本身不能确定根因。'),
)


def extract(raw, name):
    if len(raw) > 32 * 1024 * 1024:
        raise ValueError('log too large')
    lines = raw.decode('utf-8').splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line.encode('utf-8')))
    source = dict(artifact_kind='gaussian-log', envelope_observation_id='local-file-' + sha256(raw).hexdigest(),
                  logical_name=name, sha256=sha256(raw).hexdigest(), size_bytes=len(raw))
    def span(a, b):
        return dict(source, start=offsets[a], end=offsets[b])
    def number(s):
        n = float(s.replace('D', 'E').replace('d', 'e'))
        if not math.isfinite(n):
            raise ValueError('non-finite number')
        return n
    segments, errors = [], []
    current = None
    geometry = energy = None
    step_number = None
    def segment(reason):
        value = dict(index=len(segments) + 1, reason=reason, points=[], scf_observations=[])
        segments.append(value)
        return value
    i = 0
    while i < len(lines):
        line = lines[i]
        if re.search(r'Entering Gaussian System|Proceeding to internal job step|^\s*--Link1--', line):
            current = segment('job-boundary')
            geometry = energy = None
            step_number = None
        if current is None:
            current = segment('log-start')
        step = re.search(r'Step number\s+(\d+)\s+out of', line)
        if step:
            new_step = int(step[1])
            if step_number is not None and new_step != step_number + 1:
                # A repeated step starts a fresh series, never bridge a restart.
                current = segment('step-number-discontinuity')
                geometry = energy = None
            step_number = new_step
        if re.fullmatch(r'\s*(?:Standard|Input) orientation:\s*', line):
            # Clear earlier geometry even when the new block is truncated.
            geometry = None
            j = i + 1
            separators = 0
            while j < min(len(lines), i + 7):
                if re.fullmatch(r'\s*-{5,}\s*', lines[j]):
                    separators += 1
                    if separators == 2:
                        break
                j += 1
            if separators == 2:
                atoms = []
                j += 1
                while j < len(lines) and len(atoms) < 2000:
                    m = re.fullmatch(r'\s*(\d+)\s+(\d+)\s+[-+]?\d+\s+(' + NUM + r')\s+(' + NUM + r')\s+(' + NUM + r')\s*', lines[j])
                    if not m:
                        break
                    if int(m[1]) != len(atoms) + 1 or not 1 <= int(m[2]) <= 118:
                        atoms = []
                        break
                    atoms.append(dict(center=int(m[1]), atomic_number=int(m[2]), x=number(m[3]), y=number(m[4]), z=number(m[5])))
                    j += 1
                if atoms and j < len(lines) and re.fullmatch(r'\s*-{5,}\s*', lines[j]):
                    geometry = dict(atoms=atoms, units='angstrom', source_span=span(i, j + 1))
        if 'SCF Done:' in line:
            energy = None
        scf = re.search(r'SCF Done:\s+E\(([^)]+)\)\s*=\s*(' + NUM + r')\s+A\.U\.', line)
        if scf:
            energy = dict(energy_hartree=number(scf[2]), energy_kind='SCF E(' + scf[1] + ')', source_span=span(i, i + 1))
            current['scf_observations'].append(energy)
        if re.fullmatch(r'\s*Item\s+Value\s+Threshold\s+Converged\?\s*', line):
            metrics = []
            for n, label in enumerate(LABELS, 1):
                m = re.fullmatch(r'\s*' + r'\s+'.join(label.split()) + r'\s+(' + NUM + r')\s+(' + NUM + r')\s+(YES|NO)\s*', lines[i+n]) if i+n < len(lines) else None
                if not m:
                    break
                metrics.append(dict(label=label, value=number(m[1]), threshold=number(m[2]), converged=m[3] == 'YES', source_span=span(i+n, i+n+1)))
            if len(metrics) == 4 and energy and geometry:
                if current['points']:
                    previous = current['points'][-1]
                    if (previous['energy']['energy_kind'] != energy['energy_kind'] or
                            [a['atomic_number'] for a in previous['geometry']['atoms']] != [a['atomic_number'] for a in geometry['atoms']]):
                        current = segment('method-or-atom-sequence-change')
                current['points'].append(dict(index=len(current['points']) + 1, printed_step=step_number,
                    energy=energy, geometry=geometry, metrics=metrics, source_span=span(i, i+5)))
            elif current['points']:
                current = segment('incomplete-optimization-cycle')
            # A missing cycle must not reuse a previous cycle's coordinates/energy.
            geometry = energy = None
        for code, pattern, title, suggestion in ERRORS:
            if re.search(pattern, line):
                errors.append(dict(code=code, title=title, suggestion=suggestion, excerpt=line.strip()[:500],
                                   source_span=span(i, i+1), line=i+1, segment=current['index']))
        if re.search(r'(?:Normal|Error) termination', line):
            geometry = energy = None
            step_number = None
            current = None
        i += 1
    segments = [s for s in segments if s['points'] or s['scf_observations']]
    return dict(schema=SCHEMA, parser_version='1.0.0', source=source, segments=segments, errors=errors,
                scope='display-observations-not-scientific-validation')


def query_analysis(query, kind, identity):
    from auto_g16.query import QueryError
    from .details import read_json
    try:
        if hasattr(query, 'manager'):
            query = query.manager.queries()[1]
        entry = query._entry(kind, identity)
        if kind == 'archive':
            expected = next(a for a in query.archives.get_archive(identity)['data']['artifacts'] if a['role'] == 'log')
        else:
            result = query.get_details(kind, identity)['result']
            expected = result['source']['artifact'] if result['source'] else None
        if 'analysis' not in entry or expected is None:
            return dict(schema=SCHEMA, kind=kind, id=identity, availability='unavailable', reason='analysis-not-prepared', data=None)
        packet = read_json(entry['analysis'])
        if packet['schema'] != SCHEMA or any(packet['source'][k] != expected[k] for k in ('sha256', 'size_bytes', 'logical_name')):
            raise ValueError('analysis source mismatch')
        # Verify all source spans, including nested geometry/metric observations.
        def check(value):
            if isinstance(value, dict):
                if 'source_span' in value:
                    s = value['source_span']
                    if any(s[k] != packet['source'][k] for k in packet['source']) or not 0 <= s['start'] < s['end'] <= expected['size_bytes']:
                        raise ValueError('analysis span mismatch')
                for v in value.values(): check(v)
            elif isinstance(value, list):
                for v in value: check(v)
        check(packet)
        return dict(schema=SCHEMA, kind=kind, id=identity, availability='available', reason=None, data=packet)
    except QueryError:
        raise
    except (ValueError, KeyError, TypeError, OSError, StopIteration):
        raise QueryError('invalid-evidence') from None
