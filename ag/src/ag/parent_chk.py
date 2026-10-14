"""Local parent declaration and submit-time checks for the single chk attachment."""
from hashlib import sha256
import re
from ag import attempt, remote, state, submission
from ag.config import for_manifest


def _parent(cfg, parent_id, source_name):
    path = attempt.find(cfg, parent_id)
    manifest = attempt.read_manifest(path)
    current = state.read(path)
    if current['state'] not in ('finished', 'fetched'):
        raise ValueError('Parent chk requires a finished or fetched Attempt')
    if manifest.get('cluster', 'default') != cfg.get('_cluster', 'default'):
        raise ValueError('Parent and child must belong to the same cluster')
    cfg = for_manifest(cfg, manifest)
    job = submission.verified_job(path, manifest, current)
    remote.attempt_dir(cfg, manifest)
    remote.filename(source_name)
    if manifest['template'] != 'gaussian':
        raise ValueError('Parent chk must come from a Gaussian Attempt')
    # Older manifests bind %chk through their hashed Gaussian input, not a
    # separate checkpoint field. Never trust an unbound filename in science.
    inputs = [r for r in manifest['inputs'] if r['name'] not in ('job.pbs', 'job.slurm')]
    if len(inputs) != 1:
        raise ValueError('Expected one declared parent Gaussian input')
    record = inputs[0]
    source = path / 'inputs' / remote.filename(record['name'])
    if source.is_symlink() or not source.is_file():
        raise ValueError('Parent input must be a regular file')
    data = source.read_bytes()
    if (len(data), sha256(data).hexdigest()) != (record['size'], record['sha256']):
        raise ValueError('Parent input differs from its manifest')
    link0 = data.decode().split('#', 1)[0]
    chk = re.findall(r'^%chk\s*=\s*([^\r\n]+)', link0, re.I | re.M)
    if len(chk) != 1 or chk[0].strip() != source_name or not source_name.endswith('.chk'):
        raise ValueError('Source filename differs from parent manifest %chk')
    return manifest, job


def declare(cfg, study, template, parents, value):
    if template != 'gaussian':
        raise ValueError('--parent-chk requires the gaussian template')
    parent_id, separator, name = value.partition(':')
    if not separator or parent_id not in [p['attempt_id'] for p in parents]:
        raise ValueError('--parent-chk must also appear in --parent')
    parent, _ = _parent(cfg, parent_id, name)
    if parent['study_id'] != study.name:
        raise ValueError('Parent must belong to this study')
    return dict(attempt_id=parent_id, source_name=name, target_name='parent.chk',
                cluster=parent.get('cluster', 'default'))


def resolve(cfg, child, jobs=None):
    cfg = for_manifest(cfg, child)
    attachment = child['parent_chk']
    if set(attachment) != {'attempt_id', 'source_name', 'target_name', 'cluster'}:
        raise ValueError('Invalid parent chk declaration')
    if child['template'] != 'gaussian' or attachment['target_name'] != 'parent.chk':
        raise ValueError('Only Gaussian parent.chk attachments are supported')
    if attachment['attempt_id'] not in [p['attempt_id'] for p in child['parents']]:
        raise ValueError('Parent chk must also appear in --parent')
    parent, job = _parent(cfg, attachment['attempt_id'], attachment['source_name'])
    if parent['study_id'] != child['study_id'] or parent['attempt_id'] == child['attempt_id']:
        raise ValueError('Expected a distinct parent in the same study')
    if not (parent.get('cluster', 'default') == child.get('cluster', 'default') == attachment['cluster'] == cfg['_cluster']):
        raise ValueError('Parent and child must belong to the same cluster')
    # Even a retained C record is still present in the scheduler: refuse it.
    if jobs is not None and any(j['job_id'] == job for j in jobs):
        raise ValueError('Parent job is still present in the scheduler')
    return parent


def summary(attachment, observation=None):
    text = (f"Parent chk: {attachment['attempt_id']} | {attachment['source_name']}"
            f" -> {attachment['target_name']}")
    if observation is None:
        return text + ' | size/SHA256 and scheduler absence checked read-only before submit confirmation'
    size, digest = observation
    return text + f' | {size} bytes | SHA256 {digest[:12]}'
