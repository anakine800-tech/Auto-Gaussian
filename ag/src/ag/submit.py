"""Single-use submission. Ambiguous qsub outcomes stop the entire batch."""
from hashlib import sha256
from pathlib import Path
import tempfile
import sys
from ag import attempt, confirm, journal, remote, state, status
from ag.locks import claim, submission_lock
from ag.pbs import parse_nodes
from ag.transport import require_ok, TransportError


class UnknownSubmission(RuntimeError):
    pass


class UserCancelled(ValueError):
    pass


def metadata(transport, cfg, manifest, name):
    text = require_ok(transport.run(remote.metadata(cfg, manifest, name)), 'remote file verification')
    lines = text.splitlines()
    if len(lines) != 2 or not lines[0].isdigit():
        raise ValueError('Invalid remote file metadata')
    digest, _, reported_name = lines[1].partition('  ')
    expected_name = remote.attempt_dir(cfg, manifest) + '/' + remote.filename(name)
    if len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest) or reported_name != expected_name:
        raise ValueError('Invalid remote hash response')
    return int(lines[0]), digest


def capacity(cfg, transport, jobs):
    """Fall back to the strict cap when hardware capacity cannot be verified."""
    limit = cfg['resources']['max_cores']
    reason = None
    try:
        nodes = parse_nodes(require_ok(transport.run(remote.nodes()), 'pbsnodes'), jobs)
        if not nodes or any(node['cores_total'] <= 0 for node in nodes):
            raise ValueError('No positive node capacity')
        total = sum(node['cores_total'] for node in nodes)
        if total > limit:
            reason = f'集群总核数 {total} 超过 max_cores={limit}'
    except (ValueError, TransportError):
        reason = 'pbsnodes 核验失败或无法解析节点核数'
    cap = limit if reason else cfg['resources'].get('max_committed_cores', limit)
    if reason:
        print(f'严格模式：{reason}；排队也计入 {cap} 核上限', file=sys.stderr, flush=True)
    return cap, reason


def submit(cfg, ids, transport):
    if not ids or len(ids) != len(set(ids)):
        raise ValueError('Expected unique Attempt IDs')
    if hasattr(transport, 'record_to'):
        transport.record_to([attempt.find(cfg, id_) for id_ in ids])
    with submission_lock(cfg):
        prepared = []
        for id_ in ids:
            path = attempt.find(cfg, id_)
            m = attempt.read_manifest(path)
            if state.read(path)['state'] != 'prepared' or (path / '.submit-claim').exists():
                raise ValueError('Attempt already consumed or not prepared; submission refused locally')
            if m['cores'] > cfg['resources']['max_cores']:
                raise ValueError('Single job exceeds max_cores')
            files = attempt.verified_files(cfg, path, m)
            prepared.append((path, m, files))
        # Batch confirmation is for a single template and scientific method/card.
        if len({(m['template'], m['science']['route'], m['science']['method_basis']) for _, m, _ in prepared}) != 1:
            raise ValueError('Batch requires the same template, route and method basis')
        username, jobs, used = status.inventory(transport)
        running, queued = status.core_breakdown(jobs, username)
        cap, reason = capacity(cfg, transport, jobs)
        requested = sum(m['cores'] for _, m, _ in prepared)
        if used + requested > cap:
            raise ValueError(f'Core limit exceeded: {used} occupied + {requested} requested / {cap} cap')
        text = '\n'.join(f"{m['attempt_id']} | {m['template']} | {m['tier']} {m['cores']} cores | "
                         f"{m['walltime']} | SHA256 {m['bundle_sha256'][:12]}" for _, m, _ in prepared)
        text += (f'\n当前占用 {used} 核（运行 {running}、排队 {queued}），'
                 f'提交后合计 {used + requested} / 上限 {cap} 核；集群空闲不足时作业将在 PBS 中排队')
        if reason:
            text += f'\n严格模式：{reason}；排队也计入上限'
        # Keep stdout machine-readable for ag submit --json.
        print(text, file=sys.stderr, flush=True)
        if not confirm.confirm(text):
            for path, m, _ in prepared:
                journal.append(path.parent.parent, 'submit', path.name, 'user_cancelled')
            raise UserCancelled('Submission cancelled; Attempts remain prepared')
        results = []
        submitted = {}
        for path, m, files in prepared:
            # Detect changes while the human was reading the dialog. Upload a private
            # snapshot of the exact bytes already hashed, never mutable source paths.
            if attempt.read_manifest(path) != m or attempt.verified_files(cfg, path, m) != files:
                raise ValueError('Inputs changed during confirmation')
            claim(path / '.submit-claim')
            state.write(path, 'submitting')
            qsub_started = False
            try:
                # Other scheduler clients can submit during the confirmation window.
                # Keep the confirmed hardware result for this batch: an intermittent
                # pbsnodes failure must not consume an otherwise valid Attempt.
                jobs = status.parse_jobs(require_ok(transport.run(remote.jobs()), 'qstat'))
                fresh_used = status.occupied(jobs, username)
                # qstat can lag behind successful qsub. Reserve earlier batch jobs
                # until visible; do not double count them or reserve visible C jobs.
                visible = {job['job_id'] for job in jobs
                           if job['Job_Owner'].split('@')[0] == username}
                fresh_used += sum(cores for job_id, cores in submitted.items() if job_id not in visible)
                if fresh_used + m['cores'] > cap:
                    raise ValueError('Core limit changed during confirmation; stop')
                require_ok(transport.run(remote.create_attempt(cfg, m)), 'new remote Attempt directory')
                with tempfile.TemporaryDirectory(prefix='ag-submit-') as temp:
                    for name, data in files.items():
                        local = Path(temp) / name
                        local.write_bytes(data)
                        transport.upload(local, m, name)
                        size, digest = metadata(transport, cfg, m, name)
                        if (size, digest) != (len(data), sha256(data).hexdigest()):
                            raise ValueError('Uploaded file hash mismatch; stop')
                qsub_started = True
                result = transport.run(remote.submit(cfg, m))
                if result.returncode:
                    if result.returncode != 255 and result.stderr.lstrip().startswith('qsub:'):
                        qsub_started = False  # scheduler explicitly rejected the request
                        raise ValueError('qsub explicitly rejected submission; do not resubmit this Attempt')
                    raise UnknownSubmission('qsub outcome unknown; stop and use read-only status')
                try:
                    job = remote.job_id(result.stdout.strip())
                except ValueError as exc:
                    raise UnknownSubmission('Unparseable qsub response; stop and use read-only status') from exc
                results.append(dict(attempt_id=path.name, **state.write(path, 'submitted', job_id=job)))
                submitted[job] = m['cores']
            except BaseException as exc:
                target = 'unknown' if qsub_started else 'failed_presubmit'
                state.write(path, target, note=str(exc) if isinstance(exc, (ValueError, TransportError, UnknownSubmission)) else 'Submission interrupted')
                if qsub_started:
                    raise UnknownSubmission('qsub outcome unknown; no further remote writes') from exc
                raise
        return results
