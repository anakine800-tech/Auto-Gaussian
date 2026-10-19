"""Explicit, separately confirmed cancellation of a recorded exact job ID."""
from ag import attempt, confirm, journal, remote, state, submission
from ag.config import for_manifest, scheduler_kind
from ag.transport import bound_transport
from ag.locks import claim, submission_lock
from ag.submit import UserCancelled
from ag.transport import require_ok


def cancel(cfg, path, transport):
    cfg = for_manifest(cfg, attempt.read_manifest(path))
    transport = bound_transport(transport, cfg)
    is_slurm = scheduler_kind(cfg) == 'slurm'
    if hasattr(transport, 'record_to'):
        transport.record_to([path])
    with submission_lock(cfg):
        m, current = attempt.read_manifest(path), state.read(path)
        residue = current['state'] in ('finished', 'fetched') and current.get('scheduler_residue')
        active = current['state'] in ('submitted', 'running', 'stalled')
        if not (active or residue) or not current.get('job_id'):
            raise ValueError('Cancellation requires an active job or scheduler residue and recorded job ID')
        if (path / '.cancel-claim').exists():
            raise ValueError('Exact-job cancellation already attempted; no retry')
        job = submission.verified_job(path, m, current)
        text = (f"{path.name}\nCluster: {cfg['_cluster']}\nJob: {current['job_id']}\n{m['template']} | {m['tier']} {m['cores']} cores | "
                f"{m['walltime']} | SHA256 {m['bundle_sha256'][:12]}\n"
                f"点「终止作业」将停止 {cfg['_cluster']}:{job}，不会自动重提；"
                "点「保留作业」或按回车保持运行。")
        if not confirm.confirm(text, '取消作业'):
            journal.append(path.parent.parent, 'cancel', path.name, 'user_cancelled')
            raise UserCancelled('Cancellation declined')
        if state.read(path) != current or attempt.read_manifest(path) != m or submission.verified_job(path, m, current) != job:
            raise ValueError('Status changed during confirmation; no cancellation issued')
        # qdel may succeed before SSH drops; an exclusive local claim prevents
        # a later manual invocation from issuing it again after ambiguity.
        claim(path / '.cancel-claim')
        try:
            result = transport.run(remote.slurm_cancel(job) if is_slurm else remote.cancel(job))
            require_ok(result, 'scancel' if is_slurm else 'qdel')
        except BaseException:
            journal.append(path.parent.parent, 'cancel', path.name, 'failed_or_unknown', 'No automatic retry')
            raise
        journal.append(path.parent.parent, 'cancel', path.name, 'succeeded', {'job_id': current['job_id']})
        if is_slurm:
            if residue:
                return state.write(path, current['state'], exit_status=current.get('exit_status'),
                                   note='Confirmed exact-job scancel accepted', cleanup_status='scancel_accepted')
            return state.write(path, 'cancelled', note='Confirmed exact-job scancel accepted')
        if residue:
            return state.write(path, current['state'], exit_status=current.get('exit_status'),
                               note='Scheduler cleanup qdel accepted; removal not yet verified',
                               cleanup_status='qdel_accepted')
        return state.write(path, 'cancelled', note='Confirmed exact-job qdel succeeded')
