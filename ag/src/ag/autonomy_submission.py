"""Read-only audit of existing submission evidence, not autonomous authority.

Existing manual records do not bind an authorization round or wake lease. This
module deliberately cannot produce a routing placement or prove autonomous
ownership. Missing or inconsistent evidence fails closed; an unknown reply (or
a mutable ``failed_presubmit`` label) never releases a reservation here.
"""
from hashlib import sha256
import json
from pathlib import Path
import re

from ag import approval, attempt, state, study, submission
from ag.config import cluster_name


_CLAIM = b'Claimed permanently; never resubmit this Attempt.\n'


def _object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('Duplicate evidence JSON key')
        value[key] = item
    return value


def _json(data):
    def invalid(value):
        raise ValueError('Non-finite evidence JSON value')
    return json.loads(data, object_pairs_hook=_object, parse_constant=invalid)


def _hash(value):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value)


def _authorization(value):
    keys = {'method', 'approval_id', 'policy_name', 'quote', 'rule_sha256'}
    if not isinstance(value, dict):
        raise ValueError('Invalid archived authorization')
    method = value.get('method')
    if method == 'approval':
        keys.add('record_sha256')
    if set(value) != keys or method not in ('dialog', 'approval', 'policy'):
        raise ValueError('Only existing manual authorization formats are auditable')
    if method == 'dialog':
        if any(value[key] is not None for key in keys - {'method'}):
            raise ValueError('Invalid dialog authorization')
    else:
        if not isinstance(value['quote'], str) or not value['quote'].strip():
            raise ValueError('Missing archived authorization quote')
        if method == 'approval':
            study.identifier(value['approval_id'])
            if (value['policy_name'] is not None or value['rule_sha256'] is not None
                    or not _hash(value['record_sha256'])):
                raise ValueError('Invalid approval authorization identity')
        else:
            cluster_name(value['policy_name'])
            if value['approval_id'] is not None or not _hash(value['rule_sha256']):
                raise ValueError('Invalid policy authorization identity')
    return value


def audit(path):
    """Audit one existing Attempt without writes, configuration changes or SSH.

    ``retained_cores`` is conservative local evidence, NOT aggregate account
    usage: even a completed local job may still be present in the scheduler.
    Callers must not sum it with scheduler usage without exact-job deduplication.
    No result is an action permit; an eventual adapter must serialize and
    reconcile these files again at each action boundary.
    """
    path = Path(path).absolute()
    root = path.parent.parent
    evidence = {}

    def read(file):
        target = study.local_path(root, file)
        if not target.is_file():
            raise ValueError('Missing regular submission evidence: ' + target.name)
        data = target.read_bytes()
        evidence[str(target.relative_to(root))] = sha256(data).hexdigest()
        return data

    try:
        study.local_path(root, path)
        raw_manifest = read(path / 'manifest.json')
        manifest = _json(raw_manifest)
        if (manifest['attempt_id'] != path.name or manifest['study_id'] != root.name
                or type(manifest['cores']) is not int or manifest['cores'] < 1):
            raise ValueError('Invalid Attempt identity or cores')
        study.identifier(manifest['attempt_id'])
        study.identifier(manifest['study_id'])
        cluster_name(manifest.get('cluster', 'default'))
        if manifest.get('scheduler', 'pbs') not in ('pbs', 'slurm'):
            raise ValueError('Invalid Attempt scheduler')
        inputs = study.local_path(root, path / 'inputs')
        files = {item.name: read(item) for item in inputs.iterdir()}
        records, bundle_hash = attempt.bundle(files)
        declared = manifest['inputs']
        if (not isinstance(declared, list) or any(not isinstance(item, dict) or set(item) != {
                'name', 'size', 'sha256'} or not isinstance(item['name'], str)
                or type(item['size']) is not int or item['size'] < 0
                or not _hash(item['sha256']) for item in declared)):
            raise ValueError('Invalid input file manifest')
        # File ordering may identify a primary input for program-specific
        # consumers. Audit only the exact file map and canonical bundle hash;
        # it must not infer a main input from order or a .gjf suffix.
        if not files or records != sorted(declared, key=lambda item: item['name']) or bundle_hash != manifest['bundle_sha256']:
            raise ValueError('Input bundle differs from immutable manifest')
        current = _json(read(path / 'status.json'))
        if current['state'] not in state.TRANSITIONS:
            raise ValueError('Invalid local state')
        raw_journal = read(root / 'journal.jsonl')
        events = []
        for line in raw_journal.splitlines(keepends=True):
            item = _json(line)
            if (not line.endswith(b'\n') or not isinstance(item, dict)
                    or set(item) != {'ts', 'action', 'attempt_id', 'result', 'detail'}):
                raise ValueError('Incomplete or invalid study journal')
            approval.timestamp(item['ts'])
            if item['attempt_id'] == path.name:
                events.append(item)
        states = [item['result'] for item in events if item['action'] == 'state']
        if not states or states[0] != 'prepared' or states[-1] != current['state']:
            raise ValueError('Status and journal disagree')
        for previous, following in zip(states, states[1:]):
            if following != previous and following not in state.TRANSITIONS.get(previous, ()):
                raise ValueError('Invalid journal state transition')
        claim_path = study.local_path(root, path / '.submit-claim')
        summary_path = study.local_path(root, path / 'submission-summary.json')
        binding_path = study.local_path(root, path / 'submission.json')
        authorizations = [item for item in events if item['action'] == 'submit_authorization']
        result = dict(attempt_id=path.name, cluster=manifest.get('cluster', 'default'),
                      state=current['state'], manifest_sha256=sha256(raw_manifest).hexdigest(),
                      bundle_sha256=bundle_hash, autonomous_ownership_verified=False,
                      round_id=None, run_id=None, job_id=None, evidence_sha256=evidence)
        if not claim_path.exists():
            if (set(states) != {'prepared'} or current.get('job_id') is not None
                    or summary_path.exists() or binding_path.exists() or authorizations):
                raise ValueError('Missing submission claim contradicts existing evidence')
            return dict(result, classification='unconsumed', outcome='not_started', retained_cores=0)
        if read(claim_path) != _CLAIM:
            raise ValueError('Incomplete or unknown submission claim')
        summary = _json(read(summary_path))
        if (not isinstance(summary, dict) or set(summary) != {
                'schema', 'attempt_id', 'manifest_sha256', 'authorization', 'summary'}
                or summary['schema'] != 'ag-submission-summary/1'
                or summary['attempt_id'] != path.name
                or summary['manifest_sha256'] != result['manifest_sha256']
                or not isinstance(summary['summary'], str) or not summary['summary'].strip()):
            raise ValueError('Invalid archived submission summary')
        authorization = _authorization(summary['authorization'])
        if (len(authorizations) != 1 or authorizations[0]['result'] != 'ok'
                or authorizations[0]['detail'] != dict(authorization, summary_file='submission-summary.json')):
            raise ValueError('Summary and authorization journal disagree')
        if current['state'] == 'prepared' or 'submitting' not in states:
            raise ValueError('Claim and submission lifecycle disagree')
        if binding_path.exists():
            binding = _json(read(binding_path))
            expected = dict(schema='ag-submission/1', attempt_id=path.name,
                            cluster=result['cluster'], manifest_sha256=result['manifest_sha256'],
                            authorization=authorization)
            if not isinstance(binding, dict) or any(binding.get(k) != v for k, v in expected.items()):
                raise ValueError('Submission binding and summary disagree')
            job = submission.raw_job(manifest, binding['job_id'])
            if binding['job_id'] != submission.qualified(manifest, job):
                raise ValueError('Submission job identity must be cluster qualified')
            if current.get('job_id') is not None and submission.raw_job(manifest, current['job_id']) != job:
                raise ValueError('Submission binding and status job disagree')
            if current['state'] == 'failed_presubmit':
                raise ValueError('Failed-presubmit status contradicts scheduler binding')
            if current['state'] not in ('submitting', 'unknown') and current.get('job_id') is None:
                raise ValueError('Known submission state is missing its exact job identity')
            return dict(result, classification='existing_manual', outcome='submitted',
                        job_id=binding['job_id'], authorization=authorization,
                        retained_cores=manifest['cores'])
        if current.get('job_id') is not None or current['state'] not in ('submitting', 'unknown', 'failed_presubmit'):
            raise ValueError('Missing immutable scheduler binding')
        # Existing state/journal contain no immutable dispatch/result record.
        # They cannot prove absence at the scheduler, even for failed_presubmit.
        return dict(result, classification='reserved', outcome='unresolved',
                    authorization=authorization, retained_cores=manifest['cores'])
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ValueError(f'Attempt {path.name}: submission evidence audit refused ({exc})') from exc
