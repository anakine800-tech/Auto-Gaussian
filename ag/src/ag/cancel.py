"""Explicit, separately confirmed cancellation of a recorded exact job ID."""
from ag import attempt, confirm, journal, remote, state
from ag.locks import submission_lock
from ag.submit import UserCancelled
from ag.transport import require_ok


def cancel(cfg, path, transport):
    with submission_lock(cfg):
        m, current = attempt.read_manifest(path), state.read(path)
        if current['state'] != 'submitted' or not current.get('job_id'):
            raise ValueError('Cancellation requires submitted state and recorded job ID')
        job = remote.job_id(current['job_id'])
        text = (f"{path.name}\nJob: {job}\n{m['template']} | {m['tier']} {m['cores']} cores | "
                f"{m['walltime']} | SHA256 {m['bundle_sha256'][:12]}\n取消此确切作业？")
        if not confirm.confirm(text, '取消作业'):
            journal.append(path.parent.parent, 'cancel', path.name, 'user_cancelled')
            raise UserCancelled('Cancellation declined')
        if state.read(path) != current:
            raise ValueError('Status changed during confirmation; no cancellation issued')
        try:
            result = transport.run(remote.cancel(job))
            require_ok(result, 'qdel')
        except BaseException:
            journal.append(path.parent.parent, 'cancel', path.name, 'failed_or_unknown', 'No automatic retry')
            raise
        journal.append(path.parent.parent, 'cancel', path.name, 'succeeded', {'job_id': job})
        return state.write(path, 'cancelled', note='Confirmed exact-job qdel succeeded')
