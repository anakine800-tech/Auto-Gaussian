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
    elif 'cluster' in manifest:
        raise ValueError('Cluster-qualified job identity required')
    validate = remote.slurm_job_id if manifest.get('scheduler') == 'slurm' else remote.job_id
    return validate(value)


def record(path, manifest, job, *, scheduler_cluster=None):
    value = dict(schema='ag-submission/1', attempt_id=manifest['attempt_id'],
                 cluster=manifest.get('cluster', 'default'), job_id=qualified(manifest, job),
                 manifest_sha256=sha256((path / 'manifest.json').read_bytes()).hexdigest(),
                 scheduler_cluster=scheduler_cluster)
    target = study.local_path(path.parent.parent, path / 'submission.json')
    if target.exists():
        existing = json.loads(target.read_text())
        if any(existing.get(k) != value[k] for k in ('schema', 'attempt_id', 'cluster', 'job_id', 'manifest_sha256')):
            raise ValueError('Submission manifest identity mismatch')
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
    job = raw_job(manifest, status['job_id'])
    if 'cluster' not in manifest:  # pre-T16 PBS, never a current default lookup
        return job
    target = study.local_path(path.parent.parent, path / 'submission.json')
    value = json.loads(target.read_text())
    expected = dict(schema='ag-submission/1', attempt_id=manifest['attempt_id'],
                    cluster=manifest['cluster'], job_id=qualified(manifest, job),
                    manifest_sha256=sha256((path / 'manifest.json').read_bytes()).hexdigest())
    if any(value.get(k) != v for k, v in expected.items()):
        raise ValueError('Submission manifest/status/cluster mismatch')
    return job
