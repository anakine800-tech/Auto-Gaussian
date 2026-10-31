"""Write-once submission manifest binds a scheduler job to prepared bytes.

A mutable status file or same-number job on another cluster must never retarget
cancellation. Legacy PBS Attempts retain their original status-only handling.
"""
from hashlib import sha256
from contextlib import contextmanager, ExitStack
from copy import deepcopy
import json
import os
from pathlib import Path
from ag import remote, study
from ag.config import cluster_name


@contextmanager
def start_receipt_binding(cfg, path, manifest, transport, receipt, username, identity):
    """Recover from the frozen submission's receipt, not invented history.

    The controlled Attempt directory and reviewed submitted script establish
    provenance. The receipt itself contains no owner/name/queue attestation.
    Keep all local source checks before the existing publication's own writes.
    """
    from ag import approval, attempt, autonomy_submission
    from ag.config import ssh_identity
    from ag.facts import _publication_pin, _publication_unchanged
    scheduler = manifest.get('scheduler')
    if scheduler not in ('pbs', 'slurm') or not manifest.get('completion_receipts'):
        raise ValueError('Start recovery requires a frozen receipt-producing submission')
    if identity is None or identity[2] != username:
        raise ValueError('Start recovery scheduler/account identity differs')
    job = receipt['job_id' if scheduler == 'slurm' else 'PBS_JOBID']
    qualified_job = qualified(manifest, job)
    frozen_cfg = deepcopy(cfg)
    with ExitStack() as handles:
        inputs = path / 'inputs'
        proofs = [_publication_pin(p, handles) for p in (
            path.parent.parent, path.parent, path, path / 'manifest.json',
            path / 'status.json', path / '.submit-claim',
            path / 'submission-summary.json', path / 'submission.json',
            path.parent.parent / 'journal.jsonl')]
        proofs.append(_publication_pin(inputs, handles, contents=True))
        proofs.extend(_publication_pin(p, handles) for p in inputs.iterdir())
        if attempt.read_manifest(path) != manifest:
            raise ValueError('Start recovery manifest changed')
        files = attempt.verified_files(cfg, path, manifest)
        summary = autonomy_submission._json((path / 'submission-summary.json').read_bytes())
        if not isinstance(summary, dict) or not isinstance(summary.get('authorization'), dict):
            raise ValueError('Invalid archived start recovery authorization')
        authorization = summary['authorization']
        account = approval.digest({'scheduler': scheduler, 'ssh': list(identity)})
        if authorization.get('method') == 'autonomy-policy':
            registry = Path.home() / '.config/ag/autonomy-reservations'
            proofs.extend(_publication_pin(p, handles) for p in (
                registry, registry / autonomy_submission._filename(path)))
            verified_authorization = autonomy_submission.verified_authorization
            verified_authorization(path, authorization)
            # Exact immutable reservation only; do not scan other studies.
            record, digest = autonomy_submission._scientific_reservation(path)
            if (digest != authorization['ownership_sha256']
                    or record['account_sha256'] != account):
                raise ValueError('Start recovery differs from reserved scheduler/account')
        else:
            report = autonomy_submission.audit(path)
            if report['outcome'] not in ('unresolved', 'submitted'):
                raise ValueError('Start recovery requires a consumed submission')
        _, current, existing_job = attempt.local_record(path, manifest['cluster'], scheduler)
        if current['state'] not in ('submitting', 'unknown'):
            raise ValueError('Start recovery requires an uncertain submission')
        if existing_job is not None and existing_job != job:
            raise ValueError('Start receipt conflicts with existing submission binding')
        # Manual submission has no immutable per-upload success receipt. Read
        # the exact frozen input names at the bound endpoint again; a local
        # bundle check alone must not be described as remote byte verification.
        from ag.submit import metadata
        for name, data in files.items():
            if metadata(transport, cfg, manifest, name) != (len(data), sha256(data).hexdigest()):
                raise ValueError('Remote input differs from frozen start recovery bytes')

        def verify():
            if cfg != frozen_cfg or ssh_identity(cfg) != identity:
                raise ValueError('Start recovery scheduler/account changed during query')
            for proof in proofs:
                _publication_unchanged(proof)

        verify()
        yield dict(source='frozen-submission+ag-start.json',
                   job_id=qualified_job, cluster=manifest['cluster'], scheduler=scheduler,
                   bundle_sha256=manifest['bundle_sha256'],
                   script_sha256=sha256(files['job.slurm' if scheduler == 'slurm' else 'job.pbs']).hexdigest(),
                   account_sha256=account,
                   account_source=('immutable-reservation' if authorization.get('method') == 'autonomy-policy'
                                   else 'current-ssh-identity'),
                   remote_input_verification='size+sha256',
                   started_at=receipt['started_at']), verify


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
