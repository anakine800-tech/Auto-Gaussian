"""Explicit, separately confirmed cancellation of a recorded exact job ID."""
from ag import attempt, confirm, journal, remote, state
from ag.locks import claim, submission_lock
from ag.submit import UserCancelled
from ag.transport import require_ok


def cancel(cfg, path, transport):
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
        job = remote.job_id(current['job_id'])
        text = (f"{path.name}\nJob: {job}\n{m['template']} | {m['tier']} {m['cores']} cores | "
                f"{m['walltime']} | SHA256 {m['bundle_sha256'][:12]}\n取消此确切作业？")
        if not confirm.confirm(text, '取消作业'):
            journal.append(path.parent.parent, 'cancel', path.name, 'user_cancelled')
            raise UserCancelled('Cancellation declined')
        if state.read(path) != current:
            raise ValueError('Status changed during confirmation; no cancellation issued')
        # qdel may succeed before SSH drops; an exclusive local claim prevents
        # a later manual invocation from issuing it again after ambiguity.
        claim(path / '.cancel-claim')
        try:
            result = transport.run(remote.cancel(job))
            require_ok(result, 'qdel')
        except BaseException:
            journal.append(path.parent.parent, 'cancel', path.name, 'failed_or_unknown', 'No automatic retry')
            raise
        journal.append(path.parent.parent, 'cancel', path.name, 'succeeded', {'job_id': job})
        if residue:
            return state.write(path, current['state'], exit_status=current.get('exit_status'),
                               note='Scheduler cleanup qdel accepted; removal not yet verified',
                               cleanup_status='qdel_accepted')
        return state.write(path, 'cancelled', note='Confirmed exact-job qdel succeeded')
