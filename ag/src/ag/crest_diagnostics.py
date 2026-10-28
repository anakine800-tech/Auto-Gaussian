"""Bounded, local CREST evidence extraction; never infer a scientific root cause."""
from hashlib import sha256
import os
from pathlib import Path
import re
import stat

# Keep pathological lines and repeated BLAS warnings out of facts and memory.
MAX_LINE_BYTES = 4096
MAX_SUMMARY_CHARS = 300
LOG_NAMES = ('crest.out', 'job.pbs.out', 'job.slurm.out', 'job.slurm.err')
DATA_NAMES = ('crest_conformers.xyz', 'crest.energies', 'crest_best.xyz',
              'crest_ensemble.xyz', 'ensemble_energies.log')
# Specific evidence first; a bare "error", "killed", exit code or nonempty stderr
# is deliberately not a failure rule. Labels never copy identifying log text.
RULES = (
    ('scheduler_time_limit', 'error', '发现调度器超时终止证据',
     r'^(?:PBS:.*(?:job killed|job terminated).*walltime.*(?:exceed|limit)|'
     r'slurmstepd:.*(?:CANCELLED|TERMINATED).*DUE TO TIME LIMIT)'),
    ('scheduler_oom', 'error', '发现调度器内存终止证据',
     r'^(?:slurmstepd:.*(?:Detected \d+ oom[_-]kill event|Exceeded .*memory limit)|'
     r'PBS:.*(?:job killed|job terminated).*memory.*(?:exceed|limit))'),
    ('scheduler_kill', 'error', '发现调度器终止作业证据',
     r'^(?:PBS:.*(?:job killed|job terminated)|slurmstepd:.*\*\*\*.*(?:JOB|STEP) .*CANCELLED)'),
    ('runtime_error', 'error', '发现运行时错误证据',
     r'^(?:Fortran runtime error:|Program received signal SIG(?:SEGV|ABRT|FPE)\b|'
     r'ERROR STOP(?:\s|$)|Segmentation fault(?:\s|$))'),
    ('program_error', 'error', '发现程序明确报错',
     r'^(?:CREST terminated abnormally\.|\[ERROR\]|(?:CREST\s+)?(?:fatal error|error termination|abnormal termination)\b)'),
    ('normal_termination', 'info', '发现 CREST 正常终止标记',
     r'^CREST terminated normally\.\s*$'),
    ('warning', 'warning', '发现警告信息（不作为错误）',
     r'^(?:\[WARNING\]|WARNING\b|OpenBLAS\s*:\s*Warning\b|OMP:\s*Warning\b)'),
)
COMPILED = tuple((rule, level, label, re.compile(pattern, re.I))
                 for rule, level, label, pattern in RULES)
MAX_FINDINGS = len(RULES) * len(LOG_NAMES) + len(LOG_NAMES)


class IntegrityError(ValueError):
    """A source changed or is unsafe; never downgrade this into diagnostic facts."""


def _signature(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _read(path, visit=None):
    """Hash every byte, with bounded lines; reject links, special files and races."""
    from ag.study import local_path
    path = Path(path).absolute()
    local_path(path.parent, path)
    try:
        before = path.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(before.st_mode):
        raise IntegrityError('CREST source must be a regular file')
    digest = sha256()
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as stream:
        if _signature(os.fstat(stream.fileno())) != _signature(before):
            raise IntegrityError('CREST source changed before read')
        if visit is None:
            while chunk := stream.read(65536):
                digest.update(chunk)
        else:
            index = 0
            while chunk := stream.readline(MAX_LINE_BYTES + 1):
                index += 1
                digest.update(chunk)
                oversized = len(chunk) > MAX_LINE_BYTES
                if oversized:
                    while not chunk.endswith(b'\n'):
                        chunk = stream.readline(MAX_LINE_BYTES + 1)
                        if not chunk:
                            break
                        digest.update(chunk)
                    visit(index, None)
                else:
                    visit(index, chunk.decode('utf-8', errors='replace').strip())
        if _signature(os.fstat(stream.fileno())) != _signature(before):
            raise IntegrityError('CREST source changed during read')
    try:
        after = path.lstat()
    except FileNotFoundError:
        raise IntegrityError('CREST source disappeared during read') from None
    if _signature(after) != _signature(before):
        raise IntegrityError('CREST source changed during read')
    return dict(file=path.name, sha256=digest.hexdigest(), size=before.st_size)


def source_snapshot(outputs, names):
    if not set(names) <= set(LOG_NAMES + DATA_NAMES):
        raise IntegrityError('Unsupported CREST source name')
    return {name: _read(outputs / name) for name in names}


def diagnose(outputs, scheduler='pbs'):
    """Read only fixed output names; findings carry hashes/lines, never raw text."""
    if scheduler not in ('pbs', 'slurm'):
        raise ValueError('Unsupported CREST scheduler')
    names = ('crest.out', 'job.slurm.out', 'job.slurm.err') if scheduler == 'slurm' else ('crest.out', 'job.pbs.out')
    findings, files, missing = [], [], []
    truncated = False
    for name in names:
        hits = {}
        last_line = None

        def visit(index, line):
            nonlocal truncated, last_line
            if line is None:
                truncated = True
                return
            if not line or line == last_line:
                return
            last_line = line
            for rule, level, label, pattern in COMPILED:
                if rule.startswith('scheduler_') and name == 'crest.out':
                    continue
                if rule == 'normal_termination' and name != 'crest.out':
                    continue
                if pattern.search(line):
                    hits.setdefault(rule, (level, label, index))
                    return
            # Unclassified error-stream text is a review cue, not error evidence.
            if (name in ('job.pbs.out', 'job.slurm.err')
                    or re.search(r'\b(?:error|failed|aborted|killed)\b', line, re.I)):
                hits.setdefault('unclassified', ('unknown', '存在尚未识别的错误相关输出', index))

        info = _read(outputs / name, visit)
        if info is None:
            missing.append(name)
            continue
        files.append(info)
        for rule, (level, label, index) in hits.items():
            findings.append(dict(rule=rule, level=level, message=label,
                                 source=dict(file=name, sha256=info['sha256'],
                                             line_start=index, line_end=index)))
    errors = [f for f in findings if f['level'] == 'error']
    normal = any(f['rule'] == 'normal_termination' for f in findings)
    unknown = any(f['level'] == 'unknown' for f in findings)
    status = ('identified' if errors else 'unavailable' if missing else
              'unresolved' if truncated or unknown or not normal else 'none')
    summary = ('；'.join(dict.fromkeys(f['message'] for f in errors)) + '；尚不能据此证明根因' if errors else
               '输出来源缺失，无法完整诊断' if missing else
               '未识别出明确错误，需人工核对' if status == 'unresolved' else
               '未发现明确错误证据')
    if any(name != 'crest.out' for name in missing):
        summary += '；错误输出未取回／来源缺失'
    if errors and normal:
        summary += '；与正常终止标记并存，按错误证据报告'
    if truncated:
        summary += '；超长行未解析'
    shortened = len(summary) > MAX_SUMMARY_CHARS
    return dict(summary=(summary[:MAX_SUMMARY_CHARS - 1] + '…' if shortened else summary),
                status=status, sources=[f['source'] for f in findings],
                findings=[dict(rule=f['rule'], level=f['level'], message=f['message'], source_index=i)
                          for i, f in enumerate(findings)],
                files=files, missing_sources=missing, scan_truncated=truncated,
                summary_truncated=shortened, parse_status='complete', parse_error=None)


def termination(diagnostics):
    errors = [f for f in diagnostics['findings'] if f['level'] == 'error']
    normal = any(f['rule'] == 'normal_termination' for f in diagnostics['findings'])
    return dict(termination='error' if errors else 'normal' if normal else 'incomplete',
                error_hint='；'.join(dict.fromkeys(f['message'] for f in errors)) or None)


def parse_outputs(outputs, manifest):
    """Keep collection integrity outside the recoverable conformer parse path."""
    from ag._parse_outputs import parse_crest, parse_crest_mdopt
    mdopt = '--mdopt' in manifest.get('template_params', {})
    data_names = ('crest_ensemble.xyz', 'ensemble_energies.log') if mdopt else DATA_NAMES[:3]
    scheduler = manifest.get('scheduler', 'pbs')
    log_names = ('crest.out', 'job.slurm.out', 'job.slurm.err') if scheduler == 'slurm' else ('crest.out', 'job.pbs.out')
    before = source_snapshot(outputs, log_names + data_names)
    diagnostics = diagnose(outputs, scheduler)
    if any(before[info['file']] != info for info in diagnostics['files']):
        raise IntegrityError('CREST source changed during diagnosis')
    geometry = ensemble = None
    try:
        if mdopt:
            facts, geometry, ensemble = parse_crest_mdopt(
                outputs, manifest.get('science', {}).get('n_frames'), diagnostics=diagnostics)
        else:
            facts, geometry = parse_crest(outputs, diagnostics=diagnostics)
    except (ValueError, IndexError, FileNotFoundError) as exc:
        # Geometry errors may contain raw XYZ comments or paths. Retain only a
        # stable category, then require all sources still match before publishing.
        if isinstance(exc, IntegrityError):
            raise
        message = ('缺少 CREST 程序日志或构象／能量文件' if isinstance(exc, FileNotFoundError)
                   else 'CREST 构象／能量解析或一致性校验失败')
        # These messages are generated entirely by the parser, not log text.
        known = ('CREST energy/geometry counts differ', 'CREST conformer ensemble is empty',
                 'CREST mdopt input/output frame counts differ',
                 'CREST mdopt atom counts or element sequences differ',
                 'CREST mdopt requires a finite Hartree energy in every XYZ comment')
        detail = str(exc)
        if detail in known or re.fullmatch(
                r'CREST mdopt contains failed optimizations in frames \(1-based\): '
                r'\d+(?:, \d+)*; review before dedup', detail):
            message = detail[:MAX_SUMMARY_CHARS - 1] + '…' if len(detail) > MAX_SUMMARY_CHARS else detail
        diagnostics.update(parse_status='incomplete', parse_error=message)
        if diagnostics['status'] == 'none':
            diagnostics['status'] = 'unresolved'
        diagnostics['summary'] = '解析未完成；' + diagnostics['summary']
        diagnostics['summary_truncated'] |= len(diagnostics['summary']) > MAX_SUMMARY_CHARS
        if diagnostics['summary_truncated']:
            diagnostics['summary'] = diagnostics['summary'][:MAX_SUMMARY_CHARS - 1] + '…'
        facts = dict(**termination(diagnostics), n_atoms=None, n_conformers=None,
                     best_energy=None, relative_energies_kcal=[], parser_warning=message)
        if mdopt:
            facts.update(mode='mdopt', conformer_energies_hartree=[])
    if before != source_snapshot(outputs, log_names + data_names):
        raise IntegrityError('CREST source changed during parsing')
    # Hashes of even empty/no-hit files make replacement visible to facts conflict
    # handling; do not manufacture line ranges for them.
    facts['crest_diagnostics'] = diagnostics
    return facts, geometry, ensemble
