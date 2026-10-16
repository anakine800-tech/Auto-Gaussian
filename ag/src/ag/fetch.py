"""Verified output collection and exclusive supplemental fetches."""
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
import re
import sys
import time
import fcntl
from ag import attempt, journal, state, study, remote, status, submission, slurm, __version__
from ag.config import for_manifest
from ag.transport import TransportError, SSHTransport, bound_transport, require_ok
from ag.submit import metadata


def _facts_reason(exc, path, *, conflict=False):
    """Keep one bounded diagnostic without exposing local absolute paths."""
    message = str(exc).splitlines()[0] if str(exc) else ''
    root = path.parent.parent
    # SSH redaction needs connection configuration; automatic facts is local.
    # Replace study paths first (including quoted paths with spaces), then
    # discard any other absolute path and the remainder of its diagnostic.
    for prefix in sorted({str(root.absolute()), str(root.resolve())}, key=len, reverse=True):
        message = message.replace(prefix + os.sep, '')
        message = message.replace(prefix, '.')
    message = re.sub(r'(?<![\w./])(?:/|[A-Za-z]:[\\/]|\\\\).*', '[path omitted]', message)
    return (message if conflict else f'{type(exc).__name__}: {message}')[:300]


def auto_facts(path, *, skip=None):
    """Best-effort local parsing after a successful CLI fetch; never refresh."""
    path = Path(path)
    if skip is not None:
        result = dict(status='skipped', reason=skip)
    else:
        try:
            from ag.facts import FactsConflictError, build_facts
            existed = (path / 'facts.json').exists()
            build_facts(path, refresh=False)
            result = dict(status='unchanged' if existed else 'written')
        except ImportError:
            result = dict(status='skipped', reason='dependency-unavailable')
        except Exception as exc:
            conflict = isinstance(exc, FactsConflictError)
            result = dict(status='conflict' if conflict else 'failed',
                          reason=_facts_reason(exc, path, conflict=conflict))
    if result['status'] == 'conflict':
        print('取回已成功；facts 与已有证据冲突，未覆盖；请人工核对后使用 ag facts --refresh。', file=sys.stderr)
    elif result['status'] == 'failed':
        print('取回已成功；自动 facts 解析失败，请核对 facts.reason 后手动运行 ag facts。', file=sys.stderr)
    try:
        journal.append(path.parent.parent, 'facts', path.name, 'auto', result)
    except Exception:
        # A full/unwritable journal must not turn a completed fetch into failure.
        print('取回已成功；自动 facts 的 journal 记录写入失败，请保留本次输出并人工核对。', file=sys.stderr)
    return result


class _IncompleteSSHTransport(SSHTransport):
    """Keep read-only enforcement, but fail T47 on the first connection error.

    A recovered retry must not hide the uncertainty that T47 requires reporting.
    Ordinary fetch/status retain the existing transport and retry behavior.
    """
    def __init__(self, cfg):
        super().__init__(cfg, read_only=True)

    def _perform(self, operation):
        return operation()


def fetch(cfg, path, transport, *, add_missing=False, incomplete=False):
    cfg = for_manifest(cfg, attempt.read_manifest(path))
    transport = bound_transport(transport, cfg)
    if incomplete and add_missing:
        raise ValueError('--incomplete and --add-missing are mutually exclusive')
    if list(path.glob('fetch-incomplete-*.json')):
        raise FileExistsError('Incomplete fetch record already exists; outputs cannot be overwritten or supplemented')
    if incomplete:
        if isinstance(transport, SSHTransport):
            transport = _IncompleteSSHTransport(cfg)
        if hasattr(transport, 'record_to'):
            transport.record_to([])
        return _incomplete(cfg, path, transport)
    if add_missing:
        # Supplement records must not rewrite status or the original journal,
        # including the transport's usual SSH failure annotations.
        if hasattr(transport, 'record_to'):
            transport.record_to([])
        return _add_missing(cfg, path, transport)
    if hasattr(transport, 'record_to'):
        transport.record_to([path])
    m = attempt.read_manifest(path)
    journal.append(path.parent.parent, 'fetch', path.name, 'requested')
    if state.read(path)['state'] != 'finished':
        raise ValueError('Only a finished Attempt can be fetched')
    names = remote.output_names(m)
    output = study.local_path(Path(cfg['local']['studies_root']), path / 'outputs')
    for name in names:
        if (output / name).exists() or (output / name).is_symlink():
            raise FileExistsError('Output already exists; fetch will not overwrite')
    partial = study.local_path(Path(cfg['local']['studies_root']), output / '.partial')
    partial.mkdir(exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='fetch-', dir=partial))
    # Retain partial evidence on error. Do not publish any file until all verify.
    for name in names:
        before = metadata(transport, cfg, m, name)
        transport.download(m, name, stage / name)
        data = (stage / name).read_bytes()
        if before != (len(data), sha256(data).hexdigest()) or before != metadata(transport, cfg, m, name):
            raise ValueError('Downloaded file hash/size mismatch or remote output changed; stop')
    for name in names:
        os.link(stage / name, output / name)
    result = state.write(path, 'fetched', exit_status=state.read(path).get('exit_status'))
    journal.append(path.parent.parent, 'fetch', path.name, detail={'files': names})
    reminder = None
    if result.get('scheduler_residue'):
        reminder = (f'结果已取回；最近状态观察仍有 PBS 调度器残留。先用 ag status {path.name} 核查；'
                    f'若仍残留，可以用 ag cancel {path.name} 清理。'
                    '需人明确授权并亲手点击 Mac 系统对话框，只取消 status.json 中记录的确切作业号；不会自动取消。')
    return dict(attempt_id=path.name, files=names, cleanup_hint=reminder, **result)


def _remote_metadata(transport, cfg, manifest, name):
    try:
        return metadata(transport, cfg, manifest, name)
    except (TransportError, ValueError) as exc:
        # A failed test/stat cannot distinguish absence, permissions or a
        # rejected symlink; do not report an SSH failure as an absent file.
        raise type(exc)(f'Cannot verify declared remote output {name} '
                        f'(missing, unreadable or failed verification): {exc}') from exc


def _local_matches(root, output, name, expected):
    target = study.local_path(root, output / name)
    data = target.read_bytes()
    actual = len(data), sha256(data).hexdigest()
    if actual != expected:
        raise ValueError(f'Existing output mismatch: {name}; '
                         f'local size={actual[0]} sha256={actual[1]}; '
                         f'remote size={expected[0]} sha256={expected[1]}')


def _add_missing(cfg, path, transport):
    current = state.read(path)
    if current['state'] != 'fetched':
        raise ValueError('--add-missing requires a fetched Attempt')
    manifest = attempt.read_manifest(path)
    names = remote.output_names(manifest)
    root = Path(cfg['local']['studies_root'])
    output = study.local_path(root, path / 'outputs')
    # Preflight every remote file and every existing local file before download.
    expected = {name: _remote_metadata(transport, cfg, manifest, name) for name in names}
    missing, existing = [], []
    for name in names:
        target = study.local_path(root, output / name)
        if target.exists():
            _local_matches(root, output, name, expected[name])
            existing.append(name)
        else:
            missing.append(name)
    if not missing:
        return dict(attempt_id=path.name, files=[], message='没有可补取的文件', **current)

    partial = study.local_path(root, output / '.partial')
    partial.mkdir(exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='fetch-add-missing-', dir=partial))
    for name in missing:
        transport.download(manifest, name, stage / name)
        data = (stage / name).read_bytes()
        if (len(data), sha256(data).hexdigest()) != expected[name]:
            raise ValueError(f'Downloaded file hash/size mismatch: {name}; stop')
    # Do not publish a supplement against evidence changed during download.
    for name in names:
        if _remote_metadata(transport, cfg, manifest, name) != expected[name]:
            raise ValueError(f'Remote output changed during fetch: {name}; stop')
    for name in existing:
        _local_matches(root, output, name, expected[name])

    now = datetime.now(timezone.utc)
    record_name = 'fetch-add-missing-' + now.strftime('%Y%m%dT%H%M%S%fZ') + '.json'
    record = dict(attempt_id=path.name, created_at=now.isoformat(), files=missing,
                  outputs={name: dict(size=size, sha256=digest)
                           for name, (size, digest) in expected.items()})
    # xb uses O_CREAT | O_EXCL, for both results and the separate record.
    # Reserve the record before publishing: a collision cannot alter old data.
    # On I/O failure retain all evidence; an empty record is not a success.
    with study.local_path(root, path / record_name).open('xb') as handle:
        for name in missing:
            target = study.local_path(root, output / name)
            with target.open('xb') as destination:
                destination.write((stage / name).read_bytes())
                destination.flush()
                os.fsync(destination.fileno())
            _local_matches(root, output, name, expected[name])
        handle.write((json.dumps(record, ensure_ascii=False, indent=2) + '\n').encode())
        handle.flush()
        os.fsync(handle.fileno())
    return dict(attempt_id=path.name, files=missing, record=record_name, **current)


def _presence(cfg, manifest, transport):
    observations = {}
    for name in remote.output_names(manifest):
        raw = require_ok(transport.run(remote.incomplete_output_observation(cfg, manifest, name)),
                         f'Cannot verify remote output {name} (无法核实)')
        if raw == 'absent\n':
            observations[name] = None
        else:
            match = re.fullmatch(r'(\d+) (\d{4}-\d\d-\d\d \d\d:\d\d:\d\d(?:\.\d+)? [+-]\d{4})\n', raw)
            if not match:
                raise ValueError(f'Cannot verify remote output {name}: invalid size/mtime')
            observations[name] = dict(size=int(match[1]), mtime=match[2])
    return observations


def _end_evidence(cfg, path, manifest, current, transport):
    job = submission.verified_job(path, manifest, current)
    if manifest.get('scheduler') == 'slurm':
        username = require_ok(transport.run(remote.identity()), 'identity').strip()
        remote.slurm_token(username)
        result = transport.run(remote.slurm_jobs(job))
        # Match status: a purged exact job may produce this diagnostic instead
        # of an empty queue. Only sacct below can establish terminal evidence.
        if result.returncode and result.returncode != 255 and 'Invalid job id specified' in result.stderr:
            active = []
        else:
            active = slurm.parse_queue(require_ok(result, 'squeue exact job'))
        if active:
            raise ValueError('Job still present in squeue; incomplete fetch refused')
        raw = require_ok(transport.run(remote.slurm_accounting(job)), 'sacct exact job')
        rows = slurm.parse_accounting(raw, job, name=manifest['attempt_id'], username=username)
        if len(rows) != 1 or rows[0]['state'] not in {
                'TIMEOUT', 'CANCELLED', 'FAILED', 'OUT_OF_MEMORY', 'NODE_FAIL', 'COMPLETED'}:
            raise ValueError('Incomplete fetch requires a supported sacct terminal state')
        return dict(scheduler='slurm', at=time.time(), queue_absent=True, accounting=rows[0])
    observations = current.get('incomplete_observations', [])
    if len(observations) != 2:
        raise ValueError('PBS requires two inactive status observations at least 300 seconds apart')
    first, last = observations
    now = time.time()
    if (not all(type(o.get('at')) in (int, float) and 0 <= o['at'] <= now
                and o.get('job_id') == job and o.get('scheduler_state') in (None, 'C')
                and 'exit_receipt' in o and o['exit_receipt'] is None for o in observations)
            or last['at'] - first['at'] < 300 or first.get('outputs') != last.get('outputs')):
        raise ValueError('PBS requires unchanged outputs and no exit receipt across 300 seconds')
    result = transport.run(remote.jobs(job))
    if result.returncode == 0:
        jobs = status.parse_jobs(result.stdout)
        if (len(jobs) != 1 or jobs[0]['job_id'] != job
                or jobs[0].get('Job_Name') != manifest['pbs_job_name']
                or jobs[0].get('job_state') != 'C'):
            raise ValueError('PBS job active or identity unverified')
    elif not status.scheduler_absent(result):
        require_ok(result, 'qstat exact job')
    if status.read_receipt(cfg, manifest, transport, 'ag-exit.json', job) is not None:
        raise ValueError('PBS exit receipt exists; use ordinary status/fetch')
    return dict(scheduler='pbs', observations=observations, verified_at=now)


def incomplete_record(path):
    """Load a completed receipt, binding it to this Attempt and its output bytes.

    A filename alone (or an empty record after interrupted publication) must not
    unlock checkpoint reuse or make unverified local bytes into scientific facts.
    """
    records = list(path.glob('fetch-incomplete-*.json'))
    if not records:
        return None
    if len(records) != 1 or records[0].is_symlink() or not records[0].is_file():
        raise ValueError('Invalid incomplete fetch record')
    record = json.loads(records[0].read_text())
    manifest = attempt.read_manifest(path)
    current = state.read(path)
    job = submission.verified_job(path, manifest, current)
    names = set(remote.output_names(manifest))
    if (record.get('complete') is not True or record.get('attempt_id') != path.name
            or record.get('manifest_sha256') != sha256((path / 'manifest.json').read_bytes()).hexdigest()
            or record.get('job_id') != job or record.get('cluster') != manifest.get('cluster', 'default')
            or record.get('scheduler') != manifest.get('scheduler', 'pbs')
            or not isinstance(record.get('outputs'), dict) or not isinstance(record.get('missing'), list)
            or set(record['outputs']) & set(record['missing'])
            or set(record['outputs']) | set(record['missing']) != names
            or not record.get('end_evidence')):
        raise ValueError('Incomplete fetch record binding mismatch')
    for name in names:
        target = path / 'outputs' / name
        if target.is_symlink() or (path / 'outputs').is_symlink():
            raise ValueError('Incomplete output must not be a symbolic link')
        if name in record['outputs']:
            data = target.read_bytes()
            info = record['outputs'][name]
            if (len(data), sha256(data).hexdigest()) != (info['size'], info['sha256']):
                raise ValueError('Incomplete fetched output differs from record')
        elif target.exists():
            raise ValueError('Recorded missing output now exists; manual review required')
    return records[0].name, record


def _incomplete(cfg, path, transport):
    current = state.read(path)
    manifest = attempt.read_manifest(path)
    required = 'finished' if manifest.get('scheduler') == 'slurm' else 'interrupted'
    if current['state'] != required:
        raise ValueError(f'--incomplete requires {required}; cancelled/unknown/active Attempts are refused')
    root = Path(cfg['local']['studies_root'])
    output = study.local_path(root, path / 'outputs')
    names = remote.output_names(manifest)
    # Keep synchronization artifacts with staging, outside Attempt evidence.
    # Do not unlink a shared flock inode while another fetch may be waiting.
    partial = study.local_path(root, output / '.partial')
    partial.mkdir(exist_ok=True)
    lock_path = study.local_path(root, partial / '.fetch-incomplete.lock')
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'rb') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if list(path.glob('fetch-incomplete-*.json')):
            raise FileExistsError('Incomplete fetch record already exists')
        for name in names:
            if (output / name).exists() or (output / name).is_symlink():
                raise FileExistsError('Output already exists; incomplete fetch will not overwrite')
        stage = Path(tempfile.mkdtemp(prefix='fetch-incomplete-', dir=partial))
        presence = _presence(cfg, manifest, transport)
        # A strict directory/readability check precedes receipt absence checks.
        evidence = _end_evidence(cfg, path, manifest, current, transport)
        if evidence['scheduler'] == 'pbs' and presence != evidence['observations'][-1]['outputs']:
            raise ValueError('Outputs changed since PBS status observations; run status again')
        missing = [name for name, value in presence.items() if value is None]
        if (evidence['scheduler'] == 'slurm' and evidence['accounting']['state'] == 'COMPLETED'
                and not missing):
            raise ValueError('COMPLETED with all declared outputs: use ordinary fetch')
        expected = {}
        for name, value in presence.items():
            if value is None:
                continue
            before = _remote_metadata(transport, cfg, manifest, name)
            if before[0] != value['size']:
                raise ValueError('Remote output changed before download')
            transport.download(manifest, name, stage / name)
            data = (stage / name).read_bytes()
            if before != (len(data), sha256(data).hexdigest()) or before != _remote_metadata(
                    transport, cfg, manifest, name):
                raise ValueError('Downloaded file hash/size mismatch or remote output changed; stop')
            expected[name] = dict(size=before[0], sha256=before[1], mtime=value['mtime'])
        # Recheck all files, including missing ones and files downloaded earlier.
        if _presence(cfg, manifest, transport) != presence:
            raise ValueError('Remote output presence/size/mtime changed during download')
        for name, info in expected.items():
            if _remote_metadata(transport, cfg, manifest, name) != (info['size'], info['sha256']):
                raise ValueError('Remote output changed during download')
        final_evidence = _end_evidence(cfg, path, manifest, current, transport)
        if final_evidence['scheduler'] == 'slurm' and final_evidence['accounting'] != evidence['accounting']:
            raise ValueError('Slurm accounting changed during download')
        if (state.read(path) != current or attempt.read_manifest(path) != manifest):
            raise ValueError('Local Attempt changed during incomplete fetch')
        now = datetime.now(timezone.utc)
        record_name = 'fetch-incomplete-' + now.strftime('%Y%m%dT%H%M%S%fZ') + '.json'
        record = dict(complete=True, attempt_id=path.name, created_at=now.isoformat(),
                      ag_version=__version__, manifest_sha256=sha256((path / 'manifest.json').read_bytes()).hexdigest(),
                      cluster=manifest.get('cluster', 'default'), scheduler=manifest.get('scheduler', 'pbs'),
                      job_id=submission.verified_job(path, manifest, current),
                      outputs=expected, missing=missing, end_evidence=final_evidence)
        staged_record = stage / record_name
        with staged_record.open('xb') as handle:
            handle.write((json.dumps(record, indent=2, ensure_ascii=False) + '\n').encode())
            handle.flush()
            os.fsync(handle.fileno())
        # Exclusive links never overwrite. On a local publication failure remove
        # only our own links; all downloaded evidence remains under .partial.
        published = []
        try:
            for name in expected:
                target = study.local_path(root, output / name)
                os.link(stage / name, target)
                published.append((stage / name, target))
            os.link(staged_record, study.local_path(root, path / record_name))
        except (OSError, ValueError):
            for source, target in reversed(published):
                if not target.is_symlink() and target.exists() and os.path.samestat(source.stat(), target.stat()):
                    target.unlink()
            raise
        return dict(attempt_id=path.name, files=list(expected), missing=missing, record=record_name, **current)
