"""Explicit, separately confirmed cancellation of a recorded exact job ID."""
from ag import attempt, autonomy, confirm, journal, remote, state, submission
from ag.config import for_manifest, scheduler_kind
from ag.transport import bound_transport
from ag.locks import claim, submission_lock
from ag.submit import UserCancelled
from ag.transport import require_ok


def cancel(cfg, path, transport):
    m = attempt.read_manifest(path)
    cfg = for_manifest(cfg, m)
    transport = bound_transport(transport, cfg)
    is_slurm = scheduler_kind(cfg) == 'slurm'
    if hasattr(transport, 'record_to'):
        # Transport callbacks must not publish status/journal during network IO.
        transport.record_to([])

    def publication():
        return autonomy.manual_publication_guard(cfg, path.parent.parent.name)

    def bound_status():
        current = state.read(path)
        if attempt.read_manifest(path) != m or submission.verified_job(path, m, current) != job:
            raise ValueError('Submission binding changed during cancellation')
        return current

    with submission_lock(cfg):
        with publication():
            current = state.read(path)
            if attempt.read_manifest(path) != m:
                raise ValueError('Submission binding changed before cancellation')
            residue = current['state'] in ('finished', 'fetched') and current.get('scheduler_residue')
            active = current['state'] in ('submitted', 'running', 'stalled')
            if not (active or residue) or not current.get('job_id'):
                raise ValueError('Cancellation requires an active job or scheduler residue and recorded job ID')
            if (path / '.cancel-claim').exists():
                raise ValueError('Exact-job cancellation already attempted; no retry')
            job = submission.verified_job(path, m, current)
        command = remote.slurm_cancel(job) if is_slurm else remote.cancel(job)
        text = (f"{path.name}\nCluster: {cfg['_cluster']}\nJob: {current['job_id']}\n{m['template']} | {m['tier']} {m['cores']} cores | "
                f"{m['walltime']} | SHA256 {m['bundle_sha256'][:12]}\n"
                f"点「终止作业」将停止 {cfg['_cluster']}:{job}，不会自动重提；"
                "点「保留作业」或按回车保持运行。")
        if not confirm.confirm(text, '取消作业'):
            with publication():
                bound_status()
                journal.append(path.parent.parent, 'cancel', path.name, 'user_cancelled')
            raise UserCancelled('Cancellation declined')
        with publication():
            if bound_status() != current:
                raise ValueError('Status changed during confirmation; no cancellation issued')
            # qdel may succeed before SSH drops. Serialize the permanent claim
            # with owner observations, but release short locks before dispatch.
            claim(path / '.cancel-claim')
        try:
            result = transport.run(command)
            require_ok(result, 'scancel' if is_slurm else 'qdel')
        except BaseException:
            with publication():
                bound_status()
                journal.append(path.parent.parent, 'cancel', path.name, 'failed_or_unknown', 'No automatic retry')
            raise
        with publication():
            current = bound_status()
            journal.append(path.parent.parent, 'cancel', path.name, 'succeeded', {'job_id': current['job_id']})
            if current['state'] not in ('submitted', 'running', 'stalled'):
                # A status/fetch publication can complete while qdel/scancel is
                # in flight. Keep that newer observation and its exit status.
                return state.write(path, current['state'], exit_status=current.get('exit_status'),
                                   note=('Confirmed exact-job scancel accepted' if is_slurm else
                                         'Scheduler cleanup qdel accepted; removal not yet verified'),
                                   cleanup_status='scancel_accepted' if is_slurm else 'qdel_accepted')
            return state.write(path, 'cancelled', note=('Confirmed exact-job scancel accepted' if is_slurm else
                                                       'Confirmed exact-job qdel succeeded'))
