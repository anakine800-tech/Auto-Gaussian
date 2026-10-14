"""Single-use submission. Ambiguous qsub outcomes stop the entire batch."""
from hashlib import sha256
from pathlib import Path
import tempfile
import sys
from ag import attempt, cards, confirm, journal, parent_chk, remote, state, status, slurm, submission, budget
from ag.config import for_manifest, scheduler_kind
from ag.transport import bound_transport
from ag.locks import claim, submission_lock
from ag.pbs import parse_nodes
from ag.transport import require_ok, TransportError


class UnknownSubmission(RuntimeError):
    pass


class UserCancelled(ValueError):
    pass


def metadata(transport, cfg, manifest, name, *, checkpoint=False):
    command = remote.parent_chk_metadata if checkpoint else remote.metadata
    text = require_ok(transport.run(command(cfg, manifest, name)), 'remote file verification')
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
    if scheduler_kind(cfg) == 'slurm':
        return limit, 'Slurm 无硬件保证；运行加排队按 max_cores 严格统计'
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
    manifests = [attempt.read_manifest(attempt.find(cfg, id_)) for id_ in ids]
    if len({m.get('cluster', 'default') for m in manifests}) != 1:
        raise ValueError('Submit one cluster per confirmed batch')
    cfg = for_manifest(cfg, manifests[0])
    transport = bound_transport(transport, cfg)
    is_slurm = scheduler_kind(cfg) == 'slurm'
    scheduler_command = 'sbatch' if is_slurm else 'qsub'
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
        budget_ledger = budget.read(cfg) if is_slurm else None
        username, jobs, used = status.inventory(transport, cfg)
        attachments = {}
        for path, m, _ in prepared:
            if 'parent_chk' in m:
                parent = parent_chk.resolve(cfg, m, jobs)
                observed = metadata(transport, cfg, parent, m['parent_chk']['source_name'], checkpoint=True)
                attachments[path.name] = (parent, observed)
        running, queued = (slurm.core_breakdown(jobs, username) if is_slurm else status.core_breakdown(jobs, username))
        if is_slurm:
            held = budget.unobserved_cores(cfg, jobs, budget_ledger)
            used += held
            queued += held
        cap, reason = capacity(cfg, transport, jobs)
        requested = sum(m['cores'] for _, m, _ in prepared)
        if used + requested > cap:
            raise ValueError(f'Core limit exceeded: {used} occupied + {requested} requested / {cap} cap')
        if is_slurm:
            budget.check(cfg, sum(budget.requested(m) for _, m, _ in prepared), ledger=budget_ledger)
        budget_text = budget.summary(cfg, sum(budget.requested(m) for _, m, _ in prepared)) if is_slurm else None
        text = f"Cluster: {cfg['_cluster']}\n" + '\n'.join(f"{m['attempt_id']} | {m['template']} | {m['tier']} {m['cores']} cores | "
                         f"{m['walltime']} | {cards.label(m)} | SHA256 {m['bundle_sha256'][:12]}\n{attempt.cost_line(m)}" for _, m, _ in prepared)
        for path, m, _ in prepared:
            if path.name in attachments:
                text += '\n' + path.name + ' | ' + parent_chk.summary(m['parent_chk'], attachments[path.name][1])
        text += (f'\n当前占用 {used} 核（运行 {running}、排队 {queued}），'
                 f'提交后合计 {used + requested} / 上限 {cap} 核；集群空闲不足时作业将在 {scheduler_kind(cfg).upper()} 中排队')
        if budget_text:
            text += '\n' + budget_text
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
            if is_slurm:
                budget.reserve(cfg, m, budget_ledger)
            state.write(path, 'submitting')
            qsub_started = False
            try:
                # Other scheduler clients can submit during the confirmation window.
                # Keep the confirmed hardware result for this batch: an intermittent
                # pbsnodes failure must not consume an otherwise valid Attempt.
                if is_slurm:
                    jobs = slurm.parse_queue(require_ok(transport.run(remote.slurm_jobs(user=username)), 'squeue'))
                    fresh_used = sum(slurm.core_breakdown(jobs, username))
                    fresh_used += budget.unobserved_cores(cfg, jobs, budget_ledger, exclude=m['attempt_id'])
                else:
                    jobs = status.parse_jobs(require_ok(transport.run(remote.jobs()), 'qstat'))
                    fresh_used = status.occupied(jobs, username)
                # qstat can lag behind successful qsub. Reserve earlier batch jobs
                # until visible; do not double count them or reserve visible C jobs.
                visible = {job['job_id'] for job in jobs
                           if (job['owner'] if is_slurm else job['Job_Owner'].split('@')[0]) == username}
                if not is_slurm:
                    fresh_used += sum(cores for job_id, cores in submitted.items() if job_id not in visible)
                if fresh_used + m['cores'] > cap:
                    raise ValueError('Core limit changed during confirmation; stop')
                if path.name in attachments:
                    parent, observed = attachments[path.name]
                    if parent_chk.resolve(cfg, m, jobs) != parent:
                        raise ValueError('Parent manifest changed during confirmation')
                require_ok(transport.run(remote.create_attempt(cfg, m)), 'new remote Attempt directory')
                if path.name in attachments:
                    attachment = m['parent_chk']
                    detail = dict(source_attempt=parent['attempt_id'], source_name=attachment['source_name'],
                                  target_attempt=m['attempt_id'], target_name='parent.chk',
                                  size=observed[0], sha256=observed[1])
                    journal.append(path.parent.parent, 'copy_parent_chk', path.name, 'started', detail)
                    try:
                        require_ok(transport.run(remote.copy_parent_chk(cfg, parent, m)), 'parent chk copy')
                        source_result = metadata(transport, cfg, parent, attachment['source_name'], checkpoint=True)
                        target_result = metadata(transport, cfg, m, 'parent.chk', checkpoint=True)
                        if source_result != observed or target_result != observed:
                            raise ValueError('Parent chk hash/size changed after confirmation or copy; stop')
                    except BaseException:
                        journal.append(path.parent.parent, 'copy_parent_chk', path.name, 'failed_presubmit', detail)
                        raise
                    journal.append(path.parent.parent, 'copy_parent_chk', path.name, 'verified', detail)
                with tempfile.TemporaryDirectory(prefix='ag-submit-') as temp:
                    for name, data in files.items():
                        local = Path(temp) / name
                        local.write_bytes(data)
                        transport.upload(local, m, name)
                        size, digest = metadata(transport, cfg, m, name)
                        if (size, digest) != (len(data), sha256(data).hexdigest()):
                            raise ValueError('Uploaded file hash mismatch; stop')
                qsub_started = True
                result = transport.run(remote.slurm_submit(cfg, m) if is_slurm else remote.submit(cfg, m))
                if result.returncode:
                    if not is_slurm and result.returncode != 255 and result.stderr.lstrip().startswith('qsub:'):
                        qsub_started = False  # scheduler explicitly rejected the request
                        raise ValueError(f'{scheduler_command} explicitly rejected submission; do not resubmit this Attempt')
                    # sbatch can print an error after controller acceptance.
                    # Nonzero transport/scheduler replies retain the reservation.
                    raise UnknownSubmission(f'{scheduler_command} outcome unknown; stop and use read-only status')
                try:
                    job, reported_cluster = slurm.parse_submission(result.stdout) if is_slurm else (remote.job_id(result.stdout.strip()), None)
                    submission.record(path, m, job, scheduler_cluster=reported_cluster)
                except ValueError as exc:
                    raise UnknownSubmission(f'Unparseable {scheduler_command} response; stop and use read-only status') from exc
                results.append(dict(attempt_id=path.name, **state.write(path, 'submitted', job_id=submission.qualified(m, job))))
                submitted[job] = m['cores']
            except BaseException as exc:
                if is_slurm and not qsub_started:
                    budget.reject(cfg, m, budget_ledger)
                target = 'unknown' if qsub_started else 'failed_presubmit'
                state.write(path, target, note=str(exc) if isinstance(exc, (ValueError, TransportError, UnknownSubmission)) else 'Submission interrupted')
                if qsub_started:
                    raise UnknownSubmission(f'{scheduler_command} outcome unknown; no further remote writes') from exc
                raise
        return results
