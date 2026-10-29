"""Write-once submission manifest binds a scheduler job to prepared bytes.

A mutable status file or same-number job on another cluster must never retarget
cancellation. Legacy PBS Attempts retain their original status-only handling.
"""
from hashlib import sha256
import json
import os
from ag import remote, study
from ag.config import cluster_name


def qualified(manifest, job):
    cluster = cluster_name(manifest.get('cluster', 'default'))
    validate = remote.slurm_job_id if manifest.get('scheduler') == 'slurm' else remote.job_id
    return cluster + ':' + validate(job)


def raw_job(manifest, value):
    if not isinstance(value, str):
        raise ValueError('Missing recorded job identity')
    if ':' in value:
        cluster, value = value.split(':', 1)
        if cluster != manifest.get('cluster', 'default'):
            raise ValueError('Recorded job belongs to a different cluster')
    elif manifest.get('cluster', 'default') != 'default' or manifest.get('scheduler', 'pbs') != 'pbs':
        raise ValueError('Unqualified job identity belongs to default PBS only')
    validate = remote.slurm_job_id if manifest.get('scheduler') == 'slurm' else remote.job_id
    return validate(value)


def record(path, manifest, job, *, scheduler_cluster=None, authorization=None, autonomy_state=None):
    value = dict(schema='ag-submission/1', attempt_id=manifest['attempt_id'],
                 cluster=manifest.get('cluster', 'default'), job_id=qualified(manifest, job),
                 manifest_sha256=sha256((path / 'manifest.json').read_bytes()).hexdigest(),
                 scheduler_cluster=scheduler_cluster)
    # A lost scheduler reply may create the binding later via read-only status.
    # Preserve the authorization saved before submission, without reauthorizing.
    summary_path = study.local_path(path.parent.parent, path / 'submission-summary.json')
    if authorization is None and summary_path.exists():
        summary = json.loads(summary_path.read_text(encoding='utf-8'))
        if (not isinstance(summary, dict) or summary.get('schema') != 'ag-submission-summary/1'
                or summary.get('attempt_id') != value['attempt_id']
                or summary.get('manifest_sha256') != value['manifest_sha256']
                or not isinstance(summary.get('authorization'), dict)
                or summary['authorization'].get('method') not in ('approval', 'policy', 'dialog', 'autonomy-policy')):
            raise ValueError('Invalid archived submission authorization')
        authorization = summary['authorization']
    if authorization is not None and authorization.get('method') == 'autonomy-policy':
        from ag.autonomy_submission import verified_authorization
        # Read-only scheduler recovery may bind a late reply, but cannot invent
        # ownership or consume another authorization after UNKNOWN.
        authorization = verified_authorization(path, authorization, verified_state=autonomy_state)
        probe_path = study.local_path(path.parent.parent, path / 'slurm-origin-probe.json')
        if probe_path.exists():
            # verified_authorization cross-checks these exact bytes against the
            # consumed global reservation. This reference does not turn an
            # unreported scheduler cluster into a verified original instance.
            value['scheduler_probe_sha256'] = sha256(probe_path.read_bytes()).hexdigest()
    if authorization is not None:
        value['authorization'] = authorization
    target = study.local_path(path.parent.parent, path / 'submission.json')
    if target.exists():
        existing = json.loads(target.read_text())
        if any(existing.get(k) != value[k] for k in ('schema', 'attempt_id', 'cluster', 'job_id', 'manifest_sha256')):
            raise ValueError('Submission manifest identity mismatch')
        if authorization is not None and existing.get('authorization') != authorization:
            raise ValueError('Submission authorization mismatch')
        if (existing.get('scheduler_cluster') is not None and scheduler_cluster is not None
                and existing['scheduler_cluster'] != scheduler_cluster):
            raise ValueError('Submission scheduler cluster mismatch')
        if existing.get('scheduler_probe_sha256') != value.get('scheduler_probe_sha256'):
            raise ValueError('Submission original probe reference mismatch')
        return existing
    # O_EXCL prevents racing writers from assigning two identities. A partial
    # record fails closed; it is never replaced or automatically repaired.
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as handle:
        json.dump(value, handle, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    directory = os.open(path, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    return value


def verified_job(path, manifest, status):
    try:
        job = raw_job(manifest, status['job_id'])
        target = study.local_path(path.parent.parent, path / 'submission.json')
        if 'cluster' not in manifest and not target.exists():  # pre-T16 PBS
            return job
        value = json.loads(target.read_text())
        expected = dict(schema='ag-submission/1', attempt_id=manifest['attempt_id'],
                        cluster=manifest.get('cluster', 'default'), job_id=qualified(manifest, job),
                        manifest_sha256=sha256((path / 'manifest.json').read_bytes()).hexdigest())
        if any(value.get(k) != v for k, v in expected.items()):
            raise ValueError('Submission manifest/status/cluster mismatch')
        return job
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError(f'Attempt {path.name}: invalid submission binding ({exc})') from exc
