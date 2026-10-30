"""Local submission evidence and globally reconciled autonomous ownership.

Manual audit remains read-only. Autonomous reservations require both the
immutable global record and verified study consumption; neither a mutable
lifecycle label nor a selector receipt alone proves an action is authorized.
"""
from hashlib import sha256
from contextlib import contextmanager, ExitStack
from contextvars import ContextVar
from copy import deepcopy
from datetime import datetime, timezone
import fcntl
import json
import math
import os
from pathlib import Path
import re
import stat

from ag import approval, attempt, state, study, submission
from ag import _autonomy_store as disk
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
    return _audit(path, _authorization)


def _audit(path, validate_authorization, *, allow_prepared_claim=False):
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
        data = (_read_file(target) if _CAPTURE_READS.get() is not None else target.read_bytes())
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
        # Repeated status/fetch publications keep one terminal episode. Only
        # a return to an active/unknown state starts a new absence window.
        for event in reversed([item for item in events if item['action'] == 'state']):
            if event['result'] not in ('finished', 'fetched', 'cancelled', 'interrupted'):
                break
            result['terminal_since'] = approval.timestamp(event['ts']).timestamp()
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
        authorization = validate_authorization(summary['authorization'])
        if (len(authorizations) != 1 or authorizations[0]['result'] != 'ok'
                or authorizations[0]['detail'] != dict(authorization, summary_file='submission-summary.json')):
            raise ValueError('Summary and authorization journal disagree')
        if ((current['state'] == 'prepared' and not allow_prepared_claim)
                or (current['state'] != 'prepared' and 'submitting' not in states)):
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
        allowed_states = ('submitting', 'unknown', 'failed_presubmit') + (('prepared',) if allow_prepared_claim else ())
        if current.get('job_id') is not None or current['state'] not in allowed_states:
            raise ValueError('Missing immutable scheduler binding')
        # Existing state/journal contain no immutable dispatch/result record.
        # They cannot prove absence at the scheduler, even for failed_presubmit.
        return dict(result, classification='reserved', outcome='unresolved',
                    authorization=authorization, retained_cores=manifest['cores'])
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ValueError(f'Attempt {path.name}: submission evidence audit refused ({exc})') from exc


# Fixed per-user location: another config file must not create a fresh budget.
RESERVATION_SCHEMA = 'ag-autonomy-reservation/1'
_CONTEXT_KEYS = {'round_id', 'run_id', 'object_id', 'failure_class', 'max_attempts',
                 'plan_sha256', 'rule_sha256', 'routing_sha256', 'policy_name',
                 'quote', 'summary', 'selection', 'remedy_source'}
_RECORD_KEYS = _CONTEXT_KEYS | {'schema', 'study_id', 'attempt_id', 'studies_root',
    'config_path', 'account_sha256', 'manifest_sha256', 'bundle_sha256', 'inputs',
    'study_key', 'study_device', 'study_inode'}
_CONSUME_KEYS = {'attempt_id', 'object_id', 'failure_class', 'round_id', 'run_id',
                 'plan_sha256', 'rule_sha256', 'max_attempts'}
_INPUT_KEYS = {'config_sha256', 'request', 'snapshots', 'placements', 'wakeups', 'selected_at'}
_REQUEST_KEYS = {'template', 'job_class', 'walltime', 'study_id', 'study_key', 'round_id', 'run_id',
                 'object_id', 'waiting_since', 'parent_cluster'}
_FAILURE_CLASSES = {'presubmit', 'gaussian-scf', 'gaussian-opt-steps',
                    'gaussian-irc-corrector', 'gaussian-ts-curvature', 'gaussian-error', 'program-exit', 'walltime',
                    'interrupted'}
_REMEDY_KEYS = {'failure_class', 'source_attempt', 'source_ownership_sha256',
                'status_sha256', 'outputs', 'completion'}
_SCIENTIFIC_REVIEW = 'autonomy-scientific-review.json'
_SCIENTIFIC_KEYS = {'schema', 'study_id', 'study_key', 'study_device', 'study_inode',
    'attempt_id', 'object_id', 'round_id', 'ownership_sha256', 'manifest_sha256',
    'submission_sha256', 'source_plan_sha256', 'review_plan_sha256', 'review_run_id',
    'reviewed_at', 'outcome', 'reason', 'failure_class', 'scientific_judgment',
    'facts_sha256', 'outputs', 'mode_review'}


def _require(ok, message):
    if not ok:
        raise ValueError(message)


def _object_require(ok, message):
    if not ok:
        from ag.autonomy import ObjectRefused
        raise ObjectRefused(message)


def _fields(value, keys, label):
    _require(isinstance(value, dict) and set(value) == keys, 'Invalid ' + label)


@contextmanager
def _machine_directory(*, create=False):
    """Open the fixed registry root without following a path component."""
    fd = disk.directory(Path.home())
    try:
        for name in ('.config', 'ag'):
            if create:
                try:
                    os.mkdir(name, mode=0o700, dir_fd=fd)
                    os.fsync(fd)
                except FileExistsError:
                    pass
            child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        yield disk.Store(fd)
    finally:
        os.close(fd)


@contextmanager
def machine_lock(*, create=True):
    """The autonomous submission mutex at one fixed per-user location.

    Wait for any legacy configuration mutex first, then acquire this before
    the study lock. Keep only short local decisions inside, never remote IO.
    """
    with _machine_directory(create=create) as store:
        # Keep the descriptor used for no-follow validation through flock and
        # unlock. Reopening by pathname would permit locking a substituted file.
        fd = store.open('autonomy-submit.lock', os.O_RDWR | (os.O_CREAT if create else 0))
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            def verify():
                current_root = disk.directory(Path.home() / '.config' / 'ag')
                try:
                    opened, named = os.fstat(store.fd), os.fstat(current_root)
                    _require((opened.st_dev, opened.st_ino) == (named.st_dev, named.st_ino),
                             'Machine submission directory was replaced')
                finally:
                    os.close(current_root)
                current = os.stat('autonomy-submit.lock', dir_fd=store.fd, follow_symlinks=False)
                held = os.fstat(fd)
                _require(stat.S_ISREG(current.st_mode) and current.st_nlink == 1
                         and stat.S_ISREG(held.st_mode) and held.st_nlink == 1
                         and (held.st_dev, held.st_ino) == (current.st_dev, current.st_ino),
                         'Machine submission mutex was replaced')
            verify()
            yield
            verify()
        finally:
            os.close(fd)


@contextmanager
def _registry(name, *, create=False):
    with _machine_directory(create=create) as root:
        if create:
            try:
                os.mkdir(name, mode=0o700, dir_fd=root.fd)
                os.fsync(root.fd)
            except FileExistsError:
                pass
        fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root.fd)
        try:
            yield disk.Store(fd)
        finally:
            os.close(fd)


_CAPTURE_READS = ContextVar('autonomy_evidence_reads', default=None)


def _fingerprint(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


def _file_metadata(path):
    path = Path(path).absolute()
    fd = disk.directory(path.parent)
    try:
        info = os.stat(path.name, dir_fd=fd, follow_symlinks=False)
        _require(stat.S_ISREG(info.st_mode), 'Evidence must remain a regular file')
        return _fingerprint(info)
    finally:
        os.close(fd)


class _EvidenceReads:
    """Internal read receipt: hashes are computed outside publication locks."""
    def __init__(self):
        self.files = {}
        self.directories = {}
        self.identities = {}
        self.journals = {}

    def remember(self, path, before, after, data=None):
        path = Path(path).absolute()
        _require(before == after and self.files.get(path, before) == before,
                 'Evidence changed while preparing its read receipt')
        self.files[path] = after
        if path.name == 'journal.jsonl' and data is not None:
            self.journals[path] = data

    def directory(self, path):
        path = Path(path).absolute()
        fd = disk.directory(path)
        try:
            identity = _fingerprint(os.fstat(fd))
        finally:
            os.close(fd)
        _require(self.directories.get(path, identity) == identity, 'Evidence directory changed during reading')
        self.directories[path] = identity

    def verify(self, *, skip=()):
        for path, expected in self.identities.items():
            fd = disk.directory(path)
            try:
                info = os.fstat(fd)
                _require((info.st_dev, info.st_ino) == expected, 'Evidence study directory changed')
            finally:
                os.close(fd)
        for path, expected in self.directories.items():
            fd = disk.directory(path)
            try:
                _require(_fingerprint(os.fstat(fd)) == expected, 'Evidence directory changed before publication')
            finally:
                os.close(fd)
        for path, expected in self.files.items():
            if path not in skip:
                _require(_file_metadata(path) == expected, 'Evidence file changed before publication')


@contextmanager
def _capture_reads():
    captured = _EvidenceReads()
    token = _CAPTURE_READS.set(captured)
    try:
        yield captured
        captured.verify()
    finally:
        _CAPTURE_READS.reset(token)


def _read_file(path):
    path = Path(path).absolute()
    captured = _CAPTURE_READS.get()
    before = _file_metadata(path) if captured is not None else None
    fd = disk.directory(path.parent)
    try:
        data = disk.Store(fd).read(path.name)
    finally:
        os.close(fd)
    if captured is not None:
        captured.remember(path, before, _file_metadata(path), data)
    return data


def _entries(cfg):
    from ag.config import select_cluster
    if '_cluster_entries' in cfg:
        source = dict(clusters=cfg['_cluster_entries'], local=cfg['local'], _config_dir=cfg['_config_dir'])
    else:
        source = cfg
    names = source.get('clusters', {source.get('_cluster', 'default'): source})
    return {name: select_cluster(source, name) for name in names}


def account_identity(selected):
    """Hash local SSH expansion, never a remote probe or an alias alone."""
    from ag.config import ssh_identity, scheduler_kind
    identity = ssh_identity(selected)
    _require(identity is not None, 'Cannot verify local scheduler/account identity')
    return approval.digest({'scheduler': scheduler_kind(selected), 'ssh': list(identity)})


def _filename(path):
    path = Path(path).absolute()
    return path.name + '-' + sha256(str(path).encode()).hexdigest() + '.json'


def study_identity(path):
    """Bind lexical safe location and directory identity; never follow a link."""
    path = Path(path).absolute()
    fd = disk.directory(path)
    try:
        info = os.fstat(fd)
        captured = _CAPTURE_READS.get()
        if captured is not None:
            identity = (info.st_dev, info.st_ino)
            _require(captured.identities.get(path, identity) == identity,
                     'Study directory changed during evidence reading')
            captured.identities[path] = identity
        return dict(study_key=sha256(str(path).encode()).hexdigest(),
                    study_device=info.st_dev, study_inode=info.st_ino)
    finally:
        os.close(fd)


def _register_study(path):
    path = Path(path).absolute()
    identity = study_identity(path)
    value = dict(schema='ag-autonomy-study-location/1', study_path=str(path), **identity)
    raw = disk.encode(value)
    with _registry('autonomy-studies', create=True) as store:
        filename = identity['study_key'] + '.json'
        try:
            existing = store.read(filename)
        except FileNotFoundError:
            store.exclusive(filename, raw)
        else:
            _require(existing == raw, 'Registered study location or directory identity changed')


def _registered_studies():
    result = {}
    with ExitStack() as stack:
        try:
            store = stack.enter_context(_registry('autonomy-studies'))
        except FileNotFoundError:
            return result
        for name in os.listdir(store.fd):
            raw = _read_file(Path.home() / '.config/ag/autonomy-studies' / name)
            value = _json(raw)
            _fields(value, {'schema', 'study_path', 'study_key', 'study_device', 'study_inode'},
                    'registered study location')
            _require(isinstance(value['study_path'], str) and Path(value['study_path']).is_absolute(),
                     'Invalid registered study path')
            identity = study_identity(value['study_path'])
            _require(value['schema'] == 'ag-autonomy-study-location/1'
                     and name == identity['study_key'] + '.json' and raw == disk.encode(value)
                     and all(type(value.get(k)) is type(v) and value[k] == v for k, v in identity.items()),
                     'Registered study was moved, copied or replaced')
            result[identity['study_key']] = Path(value['study_path'])
    return result


def _context(record):
    from ag.autonomy_policy import integer, text, digest
    for key in ('round_id', 'run_id', 'object_id'):
        study.identifier(record[key])
    source = record['remedy_source']
    if source is None:
        _require(record['failure_class'] is None, 'Remedy requires its source evidence')
    else:
        _require(record['failure_class'] is None or
                 isinstance(record['failure_class'], str) and record['failure_class'] in _FAILURE_CLASSES,
                 'Unsupported remedy failure class')
        _fields(source, _REMEDY_KEYS, 'remedy source')
        _require(source['failure_class'] == record['failure_class'], 'Remedy classification mismatch')
        study.identifier(source['source_attempt'])
        for key in ('source_ownership_sha256', 'status_sha256'):
            digest(source[key], key)
        _require(isinstance(source['outputs'], list) and isinstance(source['completion'], dict),
                 'Invalid remedy evidence')
        if record['failure_class'] is None:
            _require(source['completion'].get('source') == 'human-resolution'
                     and source['completion'].get('manual_resolution', {}).get('kind') == 'unknown',
                     'Unknown continuation requires explicit human resolution')
        for output in source['outputs']:
            _fields(output, {'name', 'size', 'sha256'}, 'remedy output')
            _require(isinstance(output['name'], str) and Path(output['name']).name == output['name']
                     and output['name'] not in ('', '.', '..')
                     and type(output['size']) is int and output['size'] >= 0 and _hash(output['sha256']),
                     'Invalid remedy output identity')
    integer(record['max_attempts'], 'max_attempts')
    for key in ('plan_sha256', 'rule_sha256', 'routing_sha256'):
        digest(record[key], key)
    cluster_name(record['policy_name'])
    text(record['quote'], 'quote')
    text(record['summary'], 'summary')
    _selection(record['selection'])


def _selection(selection):
    _fields(selection, {'input', 'result'}, 'selection envelope')
    original, result = selection['input'], selection['result']
    _fields(original, _INPUT_KEYS, 'original selection input')
    _require(isinstance(result, dict) and result.get('schema') in
             ('ag-routing-ladder/1', 'ag-routing-legacy/1'), 'Unsupported selection result schema')
    legacy = result['schema'] == 'ag-routing-legacy/1'
    keys = _REQUEST_KEYS | ({'tier'} if legacy else set())
    request = original['request']
    _fields(request, keys, 'original selection request')
    if legacy:
        _require(original['request']['template'] in ('crest', 'xtb'), 'Legacy selector only supports CREST/xTB')
    _require(_hash(original['config_sha256']), 'Invalid selection config hash')
    approval.timestamp(original['selected_at'])
    _require(isinstance(original['snapshots'], dict) and isinstance(original['placements'], list)
             and isinstance(original['wakeups'], list) and isinstance(result, dict),
             'Incomplete original selection evidence')
    _require(result.get('evidence', {}).get('input_sha256') == approval.digest(original)
             and result['evidence'].get('config_sha256') == original['config_sha256'],
             'Selection result/input digest mismatch')
    _require(_hash(original['request']['study_key']), 'Invalid selection study key')
    for key in ('study_id', 'study_key', 'round_id', 'run_id', 'object_id', 'template', 'job_class', 'walltime', 'parent_cluster'):
        _require(result.get(key) == original['request'][key], 'Selection request/result mismatch')


def verify_selection(cfg, selection, *, batch_inputs=None):
    """Replay the reviewed selector; the caller supplies verified batch inputs."""
    from ag import route
    _selection(selection)
    selector = route.select_legacy if selection['result']['schema'] == 'ag-routing-legacy/1' else route.select_ladder
    original = selection['input']
    _require(original['config_sha256'] == route.ladder_config_identity(cfg),
             'Routing configuration changed')
    result = selector(cfg, original['snapshots'], **original['request'],
        placements=original['placements'], wakeups=original['wakeups'],
        batch_inputs=batch_inputs or {}, now=approval.timestamp(original['selected_at']))
    _require(result == selection['result'], 'Selection cannot be replayed from original evidence')
    return result


def consume(record, digest):
    _require(_hash(digest), 'Invalid ownership SHA-256')
    return {**{key: record[key] for key in _CONSUME_KEYS}, 'ownership_sha256': digest}


def authorization(record, digest):
    """Derive the same immutable identity for summary and recovered binding."""
    _require(_hash(digest), 'Invalid ownership SHA-256')
    return dict(method='autonomy-policy', approval_id=None,
        **{key: record[key] for key in ('policy_name', 'quote', 'rule_sha256', 'plan_sha256',
                                      'round_id', 'run_id', 'object_id', 'failure_class')},
        ownership_sha256=digest)


def _manifest_bytes(path):
    raw = _read_file(Path(path) / 'manifest.json')
    manifest = _json(raw)
    _require(manifest.get('attempt_id') == Path(path).name
             and manifest.get('study_id') == Path(path).parent.parent.name, 'Reservation Attempt identity mismatch')
    inputs = Path(path) / 'inputs'
    fd = disk.directory(inputs)
    try:
        captured = _CAPTURE_READS.get()
        if captured is not None:
            captured.directory(inputs)
        files = {name: _read_file(inputs / name) for name in os.listdir(fd)}
    finally:
        os.close(fd)
    records, bundle = attempt.bundle(files)
    _require(records == sorted(manifest['inputs'], key=lambda i: i['name'])
             and bundle == manifest['bundle_sha256'], 'Reservation input bundle mismatch')
    return raw, manifest


def write_reservation(cfg, path, record, *, batch_inputs=None, verified_state, validate_consume=None,
                      prepared_remedy=None):
    """Exclusive durable ownership; caller holds machine + current study locks.

    Call only after freshly reconciling all reservations, selecting from that
    evidence, and checking the plan/rule/lease. This function replays selection
    and freezes actual manifest/input identities; it does not grant authority.
    A crash before the matching T184 consume remains a blocking orphan.
    """
    _fields(record, _CONTEXT_KEYS, 'reservation context')
    _context(record)
    source = verify_remedy_evidence(cfg, verified_state, record['object_id'], prepared_remedy)
    _require(source == record['remedy_source'], 'Remedy source differs from verified previous consumption')
    path = study.local_path(Path(cfg['local']['studies_root']), Path(path).absolute())
    _require(path.parent.name == 'attempts' and path.parent.parent.parent == Path(cfg['local']['studies_root']).absolute(),
             'Reservation must belong to configured studies root')
    _require(not (path / '.submit-claim').exists(), 'Attempt already consumed')
    _require(audit(path)['classification'] == 'unconsumed', 'Attempt already consumed')
    raw, manifest = _manifest_bytes(path)
    _reject_disabled_evidence(path, manifest)
    _require(not _has_cancellation(path, verified_state),
             'Cancelled Attempts cannot be submitted again; human review is required')
    config_path = Path(cfg['_config_path']).absolute()
    _read_file(config_path)  # Reject absent, redirected or special config paths.
    entry = _entries(cfg)[manifest.get('cluster', 'default')]
    result = verify_selection(cfg, record['selection'], batch_inputs=batch_inputs)
    choice = result.get('recommendation')
    _require(isinstance(choice, dict), 'Reservation requires a selected position')
    request = record['selection']['input']['request']
    identity = study_identity(path.parent.parent)
    for key in ('round_id', 'run_id', 'object_id'):
        _require(record[key] == request[key], 'Reservation selection ownership mismatch')
    _require(request['study_key'] == identity['study_key']
             and request['study_id'] == manifest['study_id'] and request['template'] == manifest['template']
             and request['walltime'] == manifest['walltime'], 'Reservation selection/Attempt mismatch')
    _require(request['parent_cluster'] == manifest.get('parent_chk', {}).get('cluster'),
             'Reservation parent cluster mismatch')
    for key in ('cluster', 'tier', 'cores', 'mem_gb'):
        _require(choice.get(key) == manifest.get(key, 'default' if key == 'cluster' else None),
                 'Selected resource differs from frozen Attempt')
    _require(choice.get('target_node') == manifest.get('node_target', {}).get('name')
             and choice.get('node_fraction') == manifest.get('node_target', {}).get('fraction'),
             'Selected node differs from frozen Attempt')
    _require(record['routing_sha256'] == record['selection']['input']['config_sha256'], 'Reservation routing hash mismatch')
    value = dict(deepcopy(record), **identity, schema=RESERVATION_SCHEMA, study_id=manifest['study_id'],
        attempt_id=manifest['attempt_id'], studies_root=str(path.parent.parent.parent),
        config_path=str(config_path), account_sha256=account_identity(entry),
        manifest_sha256=sha256(raw).hexdigest(), bundle_sha256=manifest['bundle_sha256'],
        inputs=deepcopy(manifest['inputs']))
    data = disk.encode(value)
    digest = sha256(data).hexdigest()
    filename = _filename(path)
    if validate_consume is not None:
        validate_consume(consume(value, digest))
    _register_study(path.parent.parent)
    with _registry('autonomy-reservations', create=True) as store:
        store.exclusive(filename, data)
    return dict(record=value, sha256=digest, filename=filename,
                consume=consume(value, digest), authorization=authorization(value, digest))


def _record_path(record):
    for key in ('studies_root', 'config_path'):
        value = record[key]
        _require(isinstance(value, str) and Path(value).is_absolute() and '..' not in Path(value).parts,
                 'Invalid private reservation location')
    study.identifier(record['study_id'])
    study.identifier(record['attempt_id'])
    path = Path(record['studies_root']) / record['study_id'] / 'attempts' / record['attempt_id']
    identity = study_identity(path.parent.parent)
    _require(all(type(record.get(key)) is type(value) and record[key] == value for key, value in identity.items()),
             'Study directory was moved, copied or replaced')
    return path


def _read_global_records():
    records = []
    with ExitStack() as stack:
        try:
            store = stack.enter_context(_registry('autonomy-reservations'))
        except FileNotFoundError:
            # Absence is accepted only after the reverse scan below proves
            # that no study claims a consumed autonomous Attempt.
            return []
        else:
            for name in sorted(os.listdir(store.fd)):
                raw = _read_file(Path.home() / '.config/ag/autonomy-reservations' / name)
                value = _json(raw)
                _fields(value, _RECORD_KEYS, 'reservation record')
                _context(value)
                _require(value['schema'] == RESERVATION_SCHEMA and name == _filename(_record_path(value)),
                         'Reservation filename/schema mismatch')
                _require(raw == disk.encode(value), 'Reservation encoding was changed')
                for key in ('account_sha256', 'manifest_sha256', 'bundle_sha256'):
                    _require(_hash(value[key]), 'Invalid reservation evidence hash')
                records.append(dict(record=value, sha256=sha256(raw).hexdigest(), filename=name))
    return records


def _study_paths(root):
    """Enumerate one studies root without following directory redirects."""
    root = Path(root).absolute()
    try:
        fd = disk.directory(root)
    except FileNotFoundError:
        return []
    result = []
    try:
        for name in os.listdir(fd):
            if name.startswith('.'):
                continue
            info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            _require(not stat.S_ISLNK(info.st_mode), 'Redirected study directory')
            if not stat.S_ISDIR(info.st_mode):
                continue
            child = root / name
            if (child / 'attempts').exists() or (child / 'autonomy').exists():
                study.identifier(name)
                directory = disk.directory(child)
                os.close(directory)
                result.append(child)
    finally:
        os.close(fd)
    return result


def _load_state(path, supplied):
    from ag import autonomy
    key = str(path.absolute())
    if key in supplied:
        return supplied[key]
    if not (path / 'autonomy').exists():
        return None
    cfg = {'local': {'studies_root': str(path.parent)}}
    with disk.locked(cfg, path.name) as store:
        snapshot, _ = autonomy.load(store)
        return snapshot['state']


def _owned_audit(path, record, digest):
    expected = authorization(record, digest)
    def check(value):
        _require(value == expected, 'Autonomous summary authorization differs from reservation')
        return value
    report = _audit(path, check, allow_prepared_claim=True)
    summary = _json(_read_file(Path(path) / 'submission-summary.json'))
    _require(report['manifest_sha256'] == record['manifest_sha256']
             and report['bundle_sha256'] == record['bundle_sha256'], 'Reservation and frozen bytes disagree')
    _require(summary['summary'] == record['summary'], 'Archived summary differs from immutable reservation')
    _reject_disabled_evidence(path, _json(_read_file(Path(path) / 'manifest.json')))
    return report


def _check_consumption(record, digest, current):
    _require(isinstance(current, dict), 'Missing study autonomy state for reservation')
    item = current.get('submissions', {}).get(record['attempt_id'])
    _require(isinstance(item, dict) and all(item.get(k) == v for k, v in consume(record, digest).items()),
             'Reservation and immutable consumption disagree')
    plan = current['plans'][item['plan_id']]
    run = current['runs'][record['run_id']]
    _require(plan['sha256'] == record['plan_sha256'] and plan['confirmation'] is not None
             and run['round_id'] == record['round_id'] and run['plan_id'] == item['plan_id']
             and record['round_id'] in current['rounds'], 'Reservation plan/run/round ownership mismatch')
    return item


def _completion(path, manifest, report):
    """Verify exact-job terminal evidence, not just the local state label."""
    from ag import slurm
    raw = _read_file(Path(path) / 'status.json')
    current = _json(raw)
    _require(current['state'] in ('finished', 'fetched') and report['job_id'] is not None,
             'Attempt has no confirmed terminal evidence')
    job = submission.raw_job(manifest, report['job_id'])
    _require(submission.raw_job(manifest, current['job_id']) == job,
             'Terminal evidence job identity differs from submission')
    _require(type(current.get('exit_status')) is int, 'Missing terminal return code')
    source = current.get('completion_source')
    if manifest.get('scheduler') == 'slurm':
        _require(source == 'sacct' and current.get('scheduler_state') in slurm.TERMINAL
                 and all(type(current.get(key)) is int and current[key] >= 0
                         for key in ('exit_code', 'exit_signal', 'allocated_cpus'))
                 and current.get('exit_status') == current['exit_code']
                 and isinstance(current.get('elapsed'), str) and bool(current['elapsed']),
                 'Missing exact Slurm terminal accounting evidence')
        completion = {key: current[key] for key in
                      ('scheduler_state', 'exit_code', 'exit_signal', 'allocated_cpus', 'elapsed')}
    else:
        receipt = current.get('receipts', {}).get('exit')
        _require(source == 'ag-exit.json' and isinstance(receipt, dict)
                 and receipt.get('PBS_JOBID') == job
                 and type(receipt.get('returncode')) is int and 0 <= receipt['returncode'] <= 255
                 and current.get('exit_status') == receipt['returncode']
                 and current.get('observation', {}).get('job_id') == job,
                 'Missing exact PBS program exit receipt')
        approval.timestamp(receipt.get('finished_at'))
        completion = dict(receipt=deepcopy(receipt))
    observed = current.get('scheduler_observed_at')
    _require(type(observed) in (int, float) and observed >= 0,
             'Missing terminal observation time')
    return dict(source=source, job_id=report['job_id'], observed_at=observed, **completion), sha256(raw).hexdigest()


def _interrupted_completion(path, manifest, report, consumed):
    raw = _read_file(path / 'status.json')
    current = _json(raw)
    _object_require(manifest.get('scheduler', 'pbs') == 'pbs' and report['state'] == 'interrupted',
                    'Interrupted remedy needs ordinary PBS end evidence')
    job = submission.raw_job(manifest, report['job_id'])
    _require(current.get('observation', {}).get('job_id') == job
             and current.get('receipts', {}).get('exit') is None,
             'Interrupted status lacks exact-job observation')
    observed = current.get('scheduler_observed_at')
    _require(type(observed) in (int, float) and math.isfinite(observed) and observed >= consumed['at'],
             'Interrupted observation time is invalid')
    start = current.get('receipts', {}).get('start')
    if start is not None:
        _require(isinstance(start, dict) and start.get('PBS_JOBID') == job,
                 'Interrupted start receipt job differs')
        _require(approval.timestamp(start['started_at']).timestamp() <= observed,
                 'Interrupted start receipt is from the future')
    return dict(source='interrupted', job_id=report['job_id'], observed_at=observed,
                start=deepcopy(start), submitted_at=consumed['at'],
                inactive_observations=deepcopy(current.get('incomplete_observations', [])),
                walltime_seconds=approval.walltime_seconds(manifest['walltime'])), sha256(raw).hexdigest()


def _reject_disabled_evidence(path, manifest):
    # Old experimental origins and reroute manifests cannot authorize the
    # ordinary submission path after those capabilities have been removed.
    _require('reroute_source' not in manifest
             and not any(os.path.lexists(Path(path) / name) for name in
                         ('slurm-origin-probe.json', 'slurm-origin-claim.json', 'slurm-origin.json')),
             'Autonomous probe and reroute evidence are disabled; human review is required')
    if (Path(path) / 'submission.json').exists():
        binding = _json(_read_file(Path(path) / 'submission.json'))
        _require('scheduler_probe_sha256' not in binding,
                 'Autonomous probe evidence is disabled; human review is required')


def _has_cancellation(path, current=None):
    # Acceptance or a legacy stop file does not prove ordinary completion.
    # Do not parse disabled cancellation proofs or use them to release a slot.
    return (Path(path).name in (current or {}).get('cancellations', {})
            or Path(path).name in (current or {}).get('cancellation_results', {})
            or any(os.path.lexists(Path(path) / name) for name in
                   ('.cancel-claim', 'autonomy-cancel-request.json',
                    'autonomy-cancel-response.json', 'autonomy-cancel-stopped.json')))


def _terminal_absence(cfg, manifest, report, *, account_sha256, cluster=None, since=0):
    """Two consecutive, fresh complete monitor samples for resource accounting.

    This is neither a cancellation receipt nor permission to retry UNKNOWN.
    Stable metadata across both reads rejects an in-progress cache rotation.
    """
    from ag import autonomy
    if report['state'] not in ('finished', 'fetched', 'cancelled', 'interrupted') or not report['job_id']:
        return None
    if report.get('terminal_since') is None:
        return None
    since = max(since, report['terminal_since'])
    name = cluster or manifest.get('cluster', 'default')
    root = Path(cfg['local']['studies_root']) / '.ag-monitor'
    named, legacy = root / name, root
    folder = named if 'clusters' in cfg or name != 'default' else legacy
    paths = [folder / 'previous.json', folder / 'latest.json']
    try:
        _require(account_identity(_entries(cfg)[name]) == account_sha256,
                 'Monitor entry no longer belongs to the reservation account')
        _require(not (name == 'default' and (named / 'latest.json').exists()
                      and (legacy / 'latest.json').exists()), 'Ambiguous monitor snapshots')
        before = [_file_metadata(path) for path in paths]
        raws = [_read_file(path) for path in paths]
        _require(before == [_file_metadata(path) for path in paths], 'Monitor pair changed during reading')
        scheduler = manifest.get('scheduler', 'pbs')
        expected_job = submission.raw_job(manifest, report['job_id'])
        expected_name = manifest['attempt_id'] if scheduler == 'slurm' else manifest['pbs_job_name']
        now, samples, times = autonomy.now(), [], []
        for raw in raws:
            value = _json(raw)
            interval = value['interval_seconds']
            at = approval.timestamp(value['sampled_at']).timestamp()
            _require(value['schema'] == 'ag-monitor/1' and value['ok'] is True
                     and not value.get('error') and not value.get('config_removed')
                     and not value.get('config_warning')
                     and type(interval) is int and 30 <= interval <= 600
                     and 0 <= now - at <= 3 * interval and at >= since,
                     'Monitor absence sample is not fresh and successful')
            _require(value['cluster'].get('name', name) == name
                     and value['cluster']['scheduler'] == scheduler
                     and value.get('account_sha256') == account_sha256
                     and isinstance(value['own']['jobs'], list), 'Monitor account snapshot differs')
            for job in value['own']['jobs']:
                identity = job['job_id']
                _require(isinstance(identity, str) and isinstance(job['name'], str),
                         'Monitor job identity missing')
                if ':' in identity:
                    alias, identity = identity.split(':', 1)
                    _require(alias == name, 'Monitor job belongs to another entry')
                elif name != 'default' or scheduler != 'pbs':
                    raise ValueError('Monitor job identity is not qualified')
                from ag import remote
                (remote.slurm_job_id if scheduler == 'slurm' else remote.job_id)(identity)
                _require(identity != expected_job and job['name'] != expected_name,
                         'Bound job remains in the account snapshot')
            times.append(at)
            samples.append(dict(sampled_at=value['sampled_at'], sha256=sha256(raw).hexdigest()))
        _require(times[0] < times[1], 'Monitor samples are not strictly consecutive in time')
        return dict(source='two-monitor-absences', cluster=name, scheduler=scheduler,
                    account_sha256=account_sha256, job_id=report['job_id'], samples=samples,
                    fresh_until=min(at + 3 * _json(raw)['interval_seconds'] for at, raw in zip(times, raws)))
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def _placement_state(path, manifest, report, *, current=None, absence=None):
    local = report['state']
    if local == 'unknown':
        return 'unknown'
    if absence is not None:
        return 'finished'
    if local == 'cancelled' or _has_cancellation(path, current):
        return 'queued'
    if local in ('finished', 'fetched'):
        completion, _ = _completion(path, manifest, report)
        if completion.get('scheduler_state') == 'CANCELLED':
            return 'queued'
        return 'finished'
    if local in ('running', 'stalled'):
        return 'running'
    return 'queued' if report['job_id'] else 'reserved'


def _manual_terminal_accounting(path):
    """Historical terminal manual jobs need no local in-flight reservation.

    Global ownership and the reverse consumption scan run first. Preserve the
    orphan-autonomous rejection, but do not require old manual jobs to acquire
    newer authorization summaries or program-exit receipts retroactively.
    Actual scheduler jobs still count through the complete account inventory.
    """
    current = _json(_read_file(path / 'status.json'))
    _require(isinstance(current, dict), 'Invalid manual status record')
    if current.get('state') not in ('finished', 'fetched', 'cancelled', 'interrupted', 'failed_presubmit'):
        return None
    for name in ('submission-summary.json', 'submission.json'):
        target = path / name
        if not os.path.lexists(target):
            continue
        raw = _read_file(target)  # Redirected/special files remain an integrity error.
        try:
            value = _json(raw)
        except ValueError:
            continue  # Historical manual audit damage is a warning, not usage.
        authorization = value.get('authorization') if isinstance(value, dict) else None
        _require(not isinstance(authorization, dict) or authorization.get('method') != 'autonomy-policy',
                 'Autonomous summary is missing its global reservation')
    return dict(kind='manual_terminal_excluded', study_key=study_identity(path.parent.parent)['study_key'],
                study_id=path.parent.parent.name,
                attempt_id=path.name, state=current['state'])


def _resolution_source(cfg, current, attempt_id):
    consumed = current.get('submissions', {}).get(attempt_id)
    _require(isinstance(consumed, dict), 'Resolution requires an actual autonomous consumption')
    matches = [item for item in _read_global_records() if item['sha256'] == consumed['ownership_sha256']]
    _require(len(matches) == 1, 'Resolution source reservation is missing')
    saved = matches[0]
    path = _record_path(saved['record'])
    _require(path.name == attempt_id and path.parent.parent.parent == Path(cfg['local']['studies_root']).absolute(),
             'Resolution source belongs to another study location')
    _check_consumption(saved['record'], saved['sha256'], current)
    report = _owned_audit(path, saved['record'], saved['sha256'])
    _, manifest = _manifest_bytes(path)
    return saved, path, manifest, report, consumed


class PreparedResolution:
    """Local read receipt for a later explicit human resolution event."""
    def __init__(self, root, previous, data, reads, fresh_until):
        self.root, self.previous, self.data = root, previous, data
        self.reads, self.fresh_until = reads, fresh_until


def _resolution_kind(path, report, status, current):
    if report['state'] == 'unknown':
        return 'unknown'
    if report['state'] in ('cancelled', 'finished', 'fetched', 'interrupted') and (
            report['state'] == 'cancelled' or status.get('scheduler_state') == 'CANCELLED'
            or _has_cancellation(path, current)):
        return 'cancelled'
    return None


def _resolution_observation(cfg, record, manifest, report, consumed, raw, kind):
    from ag import autonomy
    current = _json(raw)
    _object_require(kind in ('cancelled', 'unknown'), 'Only cancelled or UNKNOWN Attempts need human resolution')
    if kind == 'cancelled':
        entries = _entries(cfg)
        aliases = [name for name, entry in entries.items() if account_identity(entry) == record['account_sha256']]
        _require(bool(aliases), 'Resolution source account is not configured')
        name = manifest.get('cluster', 'default')
        evidence = _terminal_absence(cfg, manifest, report,
            account_sha256=record['account_sha256'], cluster=name if name in aliases else aliases[0], since=consumed['at'])
        _object_require(evidence is not None, 'Cancelled resolution requires two fresh absent monitor samples')
        return evidence, evidence['fresh_until']
    evidence = current.get('unknown_reconciliation')
    _object_require(isinstance(evidence, dict), 'UNKNOWN resolution requires a formal read-only observation')
    _object_require('account_sha256' in evidence, 'UNKNOWN observation needs fresh account-bound status evidence')
    _fields(evidence, {'schema', 'observed_at', 'scheduler', 'job_name', 'matches', 'start_absent', 'account_sha256'},
            'UNKNOWN observation')
    aliases = [entry for entry in _entries(cfg).values() if account_identity(entry) == record['account_sha256']]
    _require(bool(aliases) and evidence['account_sha256'] == record['account_sha256'],
             'UNKNOWN observation belongs to another account')
    at = evidence['observed_at']
    expected_name = manifest['attempt_id'] if manifest.get('scheduler') == 'slurm' else manifest['pbs_job_name']
    _require(evidence['schema'] == 'ag-unknown-observation/1'
             and evidence['scheduler'] == manifest.get('scheduler', 'pbs')
             and evidence['job_name'] == expected_name,
             'UNKNOWN observation identity mismatch')
    _object_require(report['job_id'] is None, 'UNKNOWN now has an exact scheduler binding')
    _object_require(evidence['matches'] == [] and evidence['start_absent'] is True,
                    'UNKNOWN still has scheduler or start-receipt evidence')
    _require(type(at) in (int, float) and math.isfinite(at) and at >= consumed['at'], 'UNKNOWN observation time is invalid')
    _object_require(0 <= autonomy.now() - at <= 600, 'UNKNOWN observation is stale or from the future')
    return evidence, at + 600


def prepare_resolution_evidence(cfg, verified_state, attempt_id):
    with _capture_reads() as reads:
        saved, path, manifest, report, consumed = _resolution_source(cfg, verified_state, attempt_id)
        raw = _read_file(path / 'status.json')
        kind = _resolution_kind(path, report, _json(raw), verified_state)
        evidence, fresh_until = _resolution_observation(cfg, saved['record'], manifest, report, consumed, raw, kind)
        data = dict(attempt_id=attempt_id, object_id=consumed['object_id'],
            ownership_sha256=saved['sha256'], status_sha256=sha256(raw).hexdigest(),
            evidence_sha256=approval.digest(evidence), kind=kind)
    return PreparedResolution(str(Path(cfg['local']['studies_root']).absolute()),
        _remedy_signature(consumed), data, reads, fresh_until)


def verify_resolution_evidence(cfg, verified_state, prepared):
    from ag import autonomy
    _require(type(prepared) is PreparedResolution, 'Resolution requires internal verified evidence')
    _require(prepared.root == str(Path(cfg['local']['studies_root']).absolute())
             and _remedy_signature(verified_state.get('submissions', {}).get(prepared.data['attempt_id'])) == prepared.previous,
             'Resolution consumption changed during review')
    prepared.reads.verify()
    _object_require(autonomy.now() <= prepared.fresh_until, 'Resolution observation expired during review')
    return deepcopy(prepared.data)


def _manual_resolution(current, path, digest):
    value = current.get('manual_resolutions', {}).get(path.name)
    if value is None:
        return None
    _fields(value, {'attempt_id', 'object_id', 'ownership_sha256', 'status_sha256', 'evidence_sha256',
                    'kind', 'quote', 'at'}, 'manual resolution')
    consumed = current['submissions'][path.name]
    _require(value['attempt_id'] == path.name and value['ownership_sha256'] == digest
             and value['object_id'] == consumed['object_id'] and _hash(value['evidence_sha256'])
             and _hash(value['status_sha256'])
             and value['kind'] in ('cancelled', 'unknown') and isinstance(value['quote'], str)
             and bool(value['quote'].strip()) and type(value['at']) in (int, float)
             and math.isfinite(value['at']) and value['at'] >= consumed['at'],
             'Manual resolution ownership differs')
    return deepcopy(value)


def _fetched_outputs(path, manifest):
    """Read published outputs; ordinary fetch keeps a staging hard link."""
    from ag.remote import output_names
    names = output_names(manifest)
    events = [_json(line) for line in _read_file(path.parent.parent / 'journal.jsonl').splitlines()]
    _require(any(event['attempt_id'] == path.name and event['action'] == 'fetch'
                 and event['result'] == 'ok' and event['detail'] == {'files': names} for event in events),
             'Remedy requires a successful fetch journal record')
    _object_require(not any(event['attempt_id'] == path.name and event['action'] == 'facts'
                     and isinstance(event['detail'], dict) and event['detail'].get('status') == 'conflict'
                     for event in events), 'Conflicting facts require human review')
    files = {}
    fd = disk.directory(path / 'outputs')
    try:
        captured = _CAPTURE_READS.get()
        if captured is not None:
            captured.directory(path / 'outputs')
        for name in names:
            handle = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
            with os.fdopen(handle, 'rb') as stream:
                info = os.fstat(stream.fileno())
                _require(stat.S_ISREG(info.st_mode), 'Fetched output must be a regular file')
                data = stream.read()
                after = os.fstat(stream.fileno())
                named = os.stat(name, dir_fd=fd, follow_symlinks=False)
                _require((info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
                         == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
                         and (named.st_dev, named.st_ino) == (info.st_dev, info.st_ino),
                         'Fetched output changed during remedy validation')
                if captured is not None:
                    captured.remember(path / 'outputs' / name, _fingerprint(info), _fingerprint(after))
                files[name] = data
    finally:
        os.close(fd)
    return files


def _published_bytes(path):
    """Read a published fetch artifact, which may retain its staging hard link."""
    path = Path(path).absolute()
    fd = disk.directory(path.parent)
    try:
        handle = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        with os.fdopen(handle, 'rb') as stream:
            before = _fingerprint(os.fstat(stream.fileno()))
            _require(stat.S_ISREG(before[2]), 'Published evidence must be a regular file')
            data = stream.read()
            after = _fingerprint(os.fstat(stream.fileno()))
        _require(before == after == _file_metadata(path), 'Published evidence changed during reading')
        captured = _CAPTURE_READS.get()
        if captured is not None:
            captured.remember(path, before, after)
        return data
    finally:
        os.close(fd)


def _incomplete_remedy_outputs(path, manifest, completion):
    """Verify a formal incomplete receipt outside submission locks."""
    from ag import fetch
    from ag.remote import output_names
    paths = list(path.glob('fetch-incomplete-*.json'))
    _require(len(paths) == 1, 'Remedy requires one complete incomplete-fetch receipt')
    raw = _published_bytes(paths[0])
    record = _json(raw)
    _fields(record, {'complete', 'attempt_id', 'created_at', 'ag_version', 'manifest_sha256',
                     'cluster', 'scheduler', 'job_id', 'outputs', 'missing', 'end_evidence'},
            'incomplete-fetch receipt')
    approval.timestamp(record['created_at'])
    _require(isinstance(record['outputs'], dict) and isinstance(record['missing'], list)
             and len(record['missing']) == len(set(record['missing'])), 'Invalid incomplete output set')
    names = set(output_names(manifest))
    _require(set(record['outputs']) | set(record['missing']) == names
             and not set(record['outputs']) & set(record['missing']), 'Incomplete output set differs from manifest')
    reads = _CAPTURE_READS.get() or _EvidenceReads()
    reads.directory(path / 'outputs')
    for name, info in record['outputs'].items():
        _fields(info, {'size', 'sha256', 'mtime'}, 'incomplete output identity')
        _require(type(info['size']) is int and info['size'] >= 0 and _hash(info['sha256'])
                 and isinstance(info['mtime'], str) and bool(info['mtime']), 'Invalid incomplete output identity')
        metadata = _file_metadata(path / 'outputs' / name)
        reads.remember(path / 'outputs' / name, metadata, metadata)
    official = fetch.incomplete_record(path)
    _require(official == (paths[0].name, record), 'Formal incomplete-fetch receipt verification disagrees')
    reads.verify()
    end = record['end_evidence']
    _require(isinstance(end, dict), 'Invalid incomplete end evidence')
    if manifest.get('scheduler', 'pbs') == 'pbs':
        observations = end.get('observations') if isinstance(end, dict) else None
        job = submission.raw_job(manifest, completion['job_id'])
        _require(end.get('scheduler') == 'pbs' and completion['source'] == 'interrupted'
                 and isinstance(observations, list) and len(observations) == 2
                 and observations == completion['inactive_observations'],
                 'Incomplete PBS receipt differs from interrupted observations')
        _require(all(type(row.get('at')) in (int, float) and math.isfinite(row['at'])
                     and row['at'] >= completion['submitted_at'] and row.get('job_id') == job
                     and row.get('scheduler_state') in (None, 'C') and row.get('exit_receipt') is None
                     for row in observations)
                 and observations[1]['at'] - observations[0]['at'] >= 300
                 and observations[0]['outputs'] == observations[1]['outputs']
                 and type(end.get('verified_at')) in (int, float) and math.isfinite(end['verified_at'])
                 and end['verified_at'] >= completion['observed_at'] >= observations[1]['at'],
                 'Incomplete PBS receipt lacks exact stable inactive observations')
        start = completion['start']
        completion['walltime_reached'] = False
        if start is not None and manifest['template'] in ('gaussian', 'gaussian-cp'):
            log_name = output_names(manifest)[0]
            observed = observations[0]['outputs'].get(log_name)
            fetched = record['outputs'].get(log_name)
            # Late polling cannot date an earlier crash. Only the stable log
            # metadata also bound to the fetched bytes may date the last write.
            if (isinstance(observed, dict) and fetched is not None
                    and observed.get('size') == fetched['size']
                    and observed.get('mtime') == fetched['mtime']
                    and re.fullmatch(r'\d{4}-\d\d-\d\d \d\d:\d\d:\d\d(?:\.\d+)? [+-]\d{4}', fetched['mtime'])):
                try:
                    modified = datetime.fromisoformat(fetched['mtime'].replace(' ', 'T', 1).replace(' ', '')).timestamp()
                except (ValueError, OverflowError, OSError):
                    pass  # An unreadable timestamp cannot establish walltime.
                else:
                    started = approval.timestamp(start['started_at']).timestamp()
                    completion['walltime_reached'] = (started <= modified <= observations[0]['at']
                        and modified >= started + completion['walltime_seconds'] - 600)
    else:
        _require(isinstance(end, dict) and end.get('scheduler') == 'slurm'
                 and end.get('queue_absent') is True and type(end.get('at')) in (int, float)
                 and math.isfinite(end['at']) and end['at'] >= completion['observed_at'],
                 'Incomplete fetch lacks an exact later stopped-job observation')
        account = end.get('accounting')
        expected = dict(job_id=submission.raw_job(manifest, completion['job_id']),
            state=completion['scheduler_state'], exit_code=completion['exit_code'],
            exit_signal=completion['exit_signal'], elapsed=completion['elapsed'],
            allocated_cpus=completion['allocated_cpus'])
        _require(account == expected and account['state'] in
                 ('TIMEOUT', 'FAILED', 'OUT_OF_MEMORY', 'NODE_FAIL', 'COMPLETED'),
                 'Incomplete fetch end evidence conflicts with terminal accounting or is cancellation')
    if end.get('scheduler_cluster') is not None:
        binding = _json(_read_file(path / 'submission.json'))
        _require(end['scheduler_cluster'] == binding.get('scheduler_cluster'),
                 'Incomplete fetch scheduler target differs from known submission')
    outputs = [dict(name=name, size=info['size'], sha256=info['sha256'])
               for name, info in sorted(record['outputs'].items())]
    reference = dict(record=paths[0].name, sha256=sha256(raw).hexdigest(), receipt=record)
    # Only the program log needs parsing; the formal API verified every other
    # output's bytes against the receipt without retaining a large checkpoint.
    first = output_names(manifest)[0]
    files = {first: _published_bytes(path / 'outputs' / first)} if first in record['outputs'] else {}
    return files, outputs, reference


def _scientific_material(path, manifest, outcome, mode_path, *, reparse):
    """Bind a model's TS judgment to current fetched facts and mode evidence."""
    from ag import facts, mode_review
    from ag.autonomy_policy import _route_options
    from ag.remote import output_names
    _require(manifest['template'] == 'gaussian', 'Scientific TS review requires Gaussian')
    options = _route_options(manifest['science']['route'])
    _require(bool({'ts', 'qst2', 'qst3'} & set(options.get('opt', []))),
             'Scientific TS review requires a frozen TS optimization input')
    _require(outcome in ('ts_zero_imaginary', 'ts_wrong_mode'), 'Unsupported scientific review outcome')
    files = _fetched_outputs(path, manifest)
    raw_facts = _read_file(path / 'facts.json')
    value = _json(raw_facts)
    _require(isinstance(value, dict) and value.get('schema') == 'ag-facts/1'
             and value.get('program') == 'gaussian' and value.get('termination') == 'normal'
             and type(value.get('n_imag')) is int and value['n_imag'] >= 0
             and value.get('vibrational_modes_complete') is True,
             'Scientific review requires complete normally terminated frequency facts')
    if reparse:
        parsed, _ = facts.parse_facts(path)
        canonical = lambda row: disk.encode({key: item for key, item in row.items() if key != 'ag_provenance'})
        _require(canonical(parsed) == canonical(value), 'Fetched facts differ from current output parsing')
    log_name = output_names(manifest)[0]
    section, block = mode_review.frequency_section(files[log_name])
    evidence = None
    if outcome == 'ts_zero_imaginary':
        _require(value['n_imag'] == 0 and mode_path is None,
                 'Zero-imaginary review needs zero modes and no invented imaginary-mode report')
    else:
        _require(value['n_imag'] > 0 and mode_path is not None,
                 'Wrong-mode review needs a current imaginary-mode report')
        root = path.parent.parent
        candidate = Path(mode_path)
        target = study.local_path(root / 'analyses', candidate if candidate.is_absolute() else root / candidate)
        _require(target.suffix == '.json', 'Expected an analyses mode-review JSON file')
        raw_mode = _read_file(target)
        mode = _json(raw_mode)
        expected = dict(log=(path / 'outputs' / log_name).relative_to(root).as_posix(),
                        log_sha256=sha256(files[log_name]).hexdigest(), section=section,
                        section_sha256=sha256(block).hexdigest())
        _require(isinstance(mode, dict) and mode.get('attempt') == path.name
                 and mode.get('source') == expected and type(mode.get('frequency')) in (int, float)
                 and mode['frequency'] < 0 and mode['frequency'] in value.get('frequencies_low', [])
                 and isinstance(mode.get('pairs'), list) and bool(mode['pairs'])
                 and type(mode.get('mode')) is int and mode['mode'] >= 1,
                 'Mode review is not bound to the current imaginary frequency section')
        geometries = {}
        for side in ('plus', 'minus'):
            filename = target.with_suffix('.' + side + '.xyz').name
            _require(mode.get('geometries', {}).get(side) == filename,
                     'Mode geometry filename differs from its report')
            geometry = target.with_name(filename)
            data = _read_file(geometry)
            geometries[side] = dict(path=geometry.relative_to(root).as_posix(), sha256=sha256(data).hexdigest())
        evidence = dict(path=target.relative_to(root).as_posix(), sha256=sha256(raw_mode).hexdigest(),
                        geometries=geometries)
    return dict(facts_sha256=sha256(raw_facts).hexdigest(),
                outputs=[dict(name=name, size=len(data), sha256=sha256(data).hexdigest())
                         for name, data in sorted(files.items())], mode_review=evidence)


def _scientific_reservation(path):
    with _registry('autonomy-reservations') as store:
        raw = _read_file(Path.home() / '.config/ag/autonomy-reservations' / _filename(path))
    record = _json(raw)
    _fields(record, _RECORD_KEYS, 'reservation record')
    _context(record)
    _require(record['schema'] == RESERVATION_SCHEMA and _record_path(record) == path
             and raw == disk.encode(record), 'Invalid scientific-review ownership record')
    _require(_registered_studies().get(record['study_key']) == path.parent.parent,
             'Missing scientific-review study registration')
    return record, sha256(raw).hexdigest()


def _latest_object_consumption(history):
    latest = max(item['at'] for item in history)
    candidates = [item for item in history if item['at'] == latest]
    _require(len(candidates) == 1, 'Ambiguous latest object consumption')
    return candidates[0]


def write_scientific_review(cfg, path, *, run_id, token, plan_sha256, object_id,
                            outcome, reason, mode_review=None):
    """Preserve a pending model judgment; never certify a scientific conclusion.

    Parsing stays outside the short publication guard. The current owner then
    rechecks source identities and metadata before writing one review.
    Both supported TS outcomes share the existing curvature remedy category.
    """
    from ag import autonomy
    path = study.local_path(Path(cfg['local']['studies_root']), Path(path).absolute())
    study.identifier(object_id)
    _require(isinstance(reason, str) and bool(reason.strip()), 'Scientific review requires a reason')
    with _capture_reads() as captured:
        record, digest = _scientific_reservation(path)
        _require(record['object_id'] == object_id, 'Scientific review object differs from actual consumption')
        report = _owned_audit(path, record, digest)
        _require(report['state'] == 'fetched', 'Scientific review requires fetched outputs')
        _, manifest = _manifest_bytes(path)
        _completion(path, manifest, report)
        material = _scientific_material(path, manifest, outcome, mode_review, reparse=True)
        submission_hash = sha256(_read_file(path / 'submission.json')).hexdigest()
    with autonomy.observation_publication_guard(cfg, path.parent.parent.name, run_id, token,
            action='organize', plan_sha256=plan_sha256) as current:
        consumed = _check_consumption(record, digest, current)
        _require(current['current_round'] == record['round_id']
                 and consumed.get('dispatch_started') is not None
                 and consumed.get('aborted_before_dispatch') is None,
                 'Scientific review needs a dispatched Attempt from the current round')
        same_object = [item for item in current.get('submissions', {}).values()
                       if item['round_id'] == record['round_id'] and item['object_id'] == object_id]
        _require(same_object and _latest_object_consumption(same_object)['attempt_id'] == path.name,
                 'Scientific review must use the latest actual Attempt for this object')
        captured.verify()
        current_versions = autonomy.versions()
        at = autonomy.now()
        autonomy.eligible(current, run_id, sha256(token.encode()).hexdigest(), current_versions,
                          at, 'organize', plan_sha256)
        value = dict(schema='ag-autonomy-scientific-review/1', **study_identity(path.parent.parent),
            study_id=record['study_id'], attempt_id=path.name, object_id=object_id,
            round_id=record['round_id'], ownership_sha256=digest,
            manifest_sha256=record['manifest_sha256'], submission_sha256=submission_hash,
            source_plan_sha256=record['plan_sha256'], review_plan_sha256=plan_sha256, review_run_id=run_id,
            reviewed_at=at, outcome=outcome, reason=reason, failure_class='gaussian-ts-curvature',
            scientific_judgment='pending_human_confirmation', **material)
        fd = disk.directory(path)
        try:
            disk.Store(fd).exclusive(_SCIENTIFIC_REVIEW, disk.encode(value))
        finally:
            os.close(fd)
    return dict(record=_SCIENTIFIC_REVIEW, sha256=sha256(disk.encode(value)).hexdigest(),
                failure_class=value['failure_class'], scientific_judgment=value['scientific_judgment'])


def _read_scientific_review(path, record, digest, current, manifest):
    try:
        raw = _read_file(path / _SCIENTIFIC_REVIEW)
    except FileNotFoundError as exc:
        from ag.autonomy import ObjectRefused
        raise ObjectRefused('Normal Gaussian result requires an immutable scientific review') from exc
    value = _json(raw)
    _fields(value, _SCIENTIFIC_KEYS, 'scientific review')
    identity = study_identity(path.parent.parent)
    binding = dict(schema='ag-autonomy-scientific-review/1', **identity,
        study_id=record['study_id'], attempt_id=path.name, object_id=record['object_id'],
        round_id=record['round_id'], ownership_sha256=digest,
        manifest_sha256=record['manifest_sha256'], source_plan_sha256=record['plan_sha256'],
        submission_sha256=sha256(_read_file(path / 'submission.json')).hexdigest(),
        failure_class='gaussian-ts-curvature', scientific_judgment='pending_human_confirmation')
    _require(raw == disk.encode(value) and all(value.get(key) == item for key, item in binding.items())
             and isinstance(value['reason'], str) and bool(value['reason'].strip()),
             'Scientific review ownership or pending judgment changed')
    run = current['runs'].get(value['review_run_id'])
    plan = current['plans'].get(run['plan_id']) if run else None
    _require(run is not None and run['round_id'] == record['round_id']
             and plan is not None and plan['sha256'] == value['review_plan_sha256'] and plan['confirmation']
             and type(value['reviewed_at']) in (int, float)
             and run['started_at'] <= value['reviewed_at'] < run['started_at'] + 3600
             and (run.get('ended_at') is None or value['reviewed_at'] <= run['ended_at']),
             'Scientific review was not bound to a confirmed current wake')
    mode_path = value['mode_review']['path'] if isinstance(value['mode_review'], dict) else None
    material = _scientific_material(path, manifest, value['outcome'], mode_path, reparse=False)
    _require(all(value[key] == item for key, item in material.items()), 'Scientific review evidence bytes changed')
    return dict(record=_SCIENTIFIC_REVIEW, sha256=sha256(raw).hexdigest(),
                outcome=value['outcome'], reason=value['reason'],
                scientific_judgment=value['scientific_judgment'])


def _walltime_failure(completion):
    # A program log mentioning a walltime limit is only a hint. This path has
    # already verified exact-job sacct terminal evidence through _completion.
    return ((completion['source'] == 'sacct' and completion.get('scheduler_state') == 'TIMEOUT')
            or completion['source'] == 'interrupted' and completion.get('walltime_reached') is True)


def _presubmit_classification(current, record, digest):
    """An upload failure cannot erase a scientific remedy's original class."""
    seen, previous = set(), None
    while True:
        _require(digest not in seen, 'Cyclic immutable remedy ownership')
        seen.add(digest)
        if previous is not None:
            _require(record['attempt_id'] == previous['source_attempt']
                     and record['object_id'] == object_id, 'Presubmit remedy lineage differs')
            _check_consumption(record, digest, current)
            _owned_audit(_record_path(record), record, digest)
        object_id = record['object_id']
        classification = record['failure_class']
        if classification not in (None, 'presubmit'):
            return classification
        previous = record['remedy_source']
        if previous is None:
            return 'presubmit'
        matches = [item for item in _read_global_records()
                   if item['sha256'] == previous['source_ownership_sha256']]
        _require(len(matches) == 1, 'Presubmit source lost its immutable ownership')
        record, digest = matches[0]['record'], matches[0]['sha256']


def _remedy_previous(current, object_id, exclude_attempt):
    _require(isinstance(current, dict), 'Remedy requires verified autonomy state')
    study.identifier(object_id)
    history = [item for key, item in current.get('submissions', {}).items()
               if key != exclude_attempt and item['round_id'] == current.get('current_round')
               and item['object_id'] == object_id]
    return _latest_object_consumption(history) if history else None


def _remedy_signature(previous):
    if previous is None:
        return None
    # Public snapshots deliberately omit the internal owner token. The actual
    # consumption identity and dispatch/abort outcomes remain fully bound.
    keys = _CONSUME_KEYS | {'ownership_sha256', 'plan_id', 'at',
                            'dispatch_started', 'aborted_before_dispatch'}
    return {key: deepcopy(previous.get(key)) for key in keys}


class PreparedRemedy:
    """Process-local evidence receipt, never accepted as CLI/JSON authority."""
    def __init__(self, root, round_id, object_id, previous, evidence, reads, source_path):
        self.root, self.round_id, self.object_id = root, round_id, object_id
        self.previous, self.evidence = previous, evidence
        self.reads, self.source_path = reads, source_path


def prepare_remedy_evidence(cfg, verified_state, object_id, *, exclude_attempt=None):
    """Parse and hash remedy evidence outside every submission/publication lock."""
    previous = _remedy_previous(verified_state, object_id, exclude_attempt)
    with _capture_reads() as reads:
        evidence = remedy_evidence(cfg, verified_state, object_id, exclude_attempt=exclude_attempt)
    sources = [path.parent for path in reads.files if path.name == 'status.json'
               and evidence is not None and path.parent.name == evidence['source_attempt']]
    _require(len(sources) == (1 if evidence is not None else 0), 'Ambiguous prepared remedy source')
    prepared = PreparedRemedy(str(Path(cfg['local']['studies_root']).absolute()),
        verified_state.get('current_round'), object_id, _remedy_signature(previous), evidence,
        reads, sources[0] if sources else None)
    return prepared


def _prepared_remedy_binding(cfg, current, object_id, prepared, exclude_attempt):
    previous = _remedy_previous(current, object_id, exclude_attempt)
    _require(type(prepared) is PreparedRemedy, 'Remedy requires an internal prepared evidence receipt')
    _require(prepared.root == str(Path(cfg['local']['studies_root']).absolute())
             and prepared.round_id == current.get('current_round') and prepared.object_id == object_id
             and prepared.previous == _remedy_signature(previous),
             'Latest actual remedy consumption changed after evidence preparation')
    resolution = (prepared.evidence or {}).get('completion', {}).get('manual_resolution')
    if resolution is not None:
        _require(current.get('manual_resolutions', {}).get(prepared.source_path.name) == resolution,
                 'Human source resolution changed during evidence review')
        from ag import autonomy
        _object_require(autonomy.now() <= prepared.evidence['completion']['fresh_until'],
                        'Resolved source observation expired')
    else:
        _object_require(prepared.source_path is None or not _has_cancellation(prepared.source_path, current),
                        'Cancelled jobs cannot be remedy sources; human review is required')


def verify_remedy_evidence(cfg, verified_state, object_id, prepared, *, exclude_attempt=None):
    """Under the short lock, verify state and metadata only; never read outputs."""
    if prepared is None:
        # Compatibility for existing initial-submission callers. A missing
        # receipt must never trigger expensive parsing inside this transaction.
        _require(_remedy_previous(verified_state, object_id, exclude_attempt) is None,
                 'Existing remedy source requires evidence prepared outside the submission lock')
        return None
    _prepared_remedy_binding(cfg, verified_state, object_id, prepared, exclude_attempt)
    prepared.reads.verify()
    return deepcopy(prepared.evidence)


def refresh_remedy_evidence(cfg, verified_state, object_id, prepared, *, exclude_attempt=None):
    """Outside locks, accept proven journal appends without rehashing outputs.

    Every heavy source must retain its exact file metadata. A journal's old
    bytes must remain an unchanged prefix; new source-result events require a
    new review instead of silently changing the prepared scientific evidence.
    """
    _prepared_remedy_binding(cfg, verified_state, object_id, prepared, exclude_attempt)
    reads = prepared.reads
    status_path = prepared.source_path / 'status.json' if prepared.source_path else None
    skipped = set(reads.journals) | ({status_path} if status_path is not None else set())
    reads.verify(skip=skipped)
    updated = _EvidenceReads()
    updated.files, updated.directories = dict(reads.files), dict(reads.directories)
    updated.identities, updated.journals = dict(reads.identities), dict(reads.journals)
    if status_path is not None:
        before = _file_metadata(status_path)
        raw = _read_file(status_path)
        _require(sha256(raw).hexdigest() == prepared.evidence['status_sha256'],
                 'Remedy terminal status changed after evidence preparation')
        updated.files[status_path] = before
        _require(_file_metadata(status_path) == before, 'Remedy status changed during refresh')
    for path, old in reads.journals.items():
        before = _file_metadata(path)
        _require(before[:4] == reads.files[path][:4], 'Remedy journal was replaced')
        raw = _read_file(path)
        _require(raw.startswith(old) and old.endswith(b'\n') and raw.endswith(b'\n'),
                 'Remedy journal history changed or was truncated')
        for line in raw[len(old):].splitlines():
            event = _json(line)
            _fields(event, {'ts', 'action', 'attempt_id', 'result', 'detail'}, 'appended remedy journal event')
            approval.timestamp(event['ts'])
            if prepared.source_path is not None and event['attempt_id'] == prepared.source_path.name:
                _require(event['action'] == 'status' and event['result'] == 'query',
                         'New source result or facts event requires fresh remedy evidence')
        _require(_file_metadata(path) == before, 'Remedy journal changed during refresh')
        updated.files[path], updated.journals[path] = before, raw
    updated.verify()
    refreshed = PreparedRemedy(prepared.root, prepared.round_id, prepared.object_id,
        deepcopy(prepared.previous), deepcopy(prepared.evidence), updated, prepared.source_path)
    return refreshed


def remedy_evidence(cfg, verified_state, object_id, *, exclude_attempt=None):
    """Derive the next remedy only from the latest actual consumption.

    This full parser runs outside submission/publication locks on a copied
    verified state. Action boundaries use PreparedRemedy metadata checks, never
    this parser. A caller assertion cannot rename failure or turn success into
    a retry; different scientific stages use their planned object identity.
    """
    previous = _remedy_previous(verified_state, object_id, exclude_attempt)
    if previous is None:
        return None
    matches = [saved for saved in _read_global_records()
               if saved['sha256'] == previous['ownership_sha256']]
    _require(len(matches) == 1, 'Previous remedy source is missing its global reservation')
    saved = matches[0]
    record, digest = saved['record'], saved['sha256']
    path = _record_path(record)
    _require(path.parent.parent.parent == Path(cfg['local']['studies_root']).absolute()
             and _registered_studies().get(record['study_key']) == path.parent.parent,
             'Remedy source study location changed')
    consumed = _check_consumption(record, digest, verified_state)
    report = _owned_audit(path, record, digest)
    _, manifest = _manifest_bytes(path)
    events = [_json(line) for line in _read_file(path.parent.parent / 'journal.jsonl').splitlines()]
    _object_require(not any(event['attempt_id'] == path.name and event['action'] == 'facts'
                     and isinstance(event.get('detail'), dict) and event['detail'].get('status') == 'conflict'
                     for event in events), 'Conflicting facts require human review before a remedy')
    resolution = _manual_resolution(verified_state, path, digest)
    status_raw = _read_file(path / 'status.json')
    if resolution is not None:
        kind = _resolution_kind(path, report, _json(status_raw), verified_state)
        _object_require(kind == resolution['kind'], 'Resolved source now has different scheduler evidence')
        evidence, fresh_until = _resolution_observation(cfg, record, manifest, report, consumed, status_raw, kind)
        return dict(failure_class=None if kind == 'unknown' else 'interrupted',
            source_attempt=path.name, source_ownership_sha256=digest, status_sha256=sha256(status_raw).hexdigest(),
            outputs=[], completion=dict(source='human-resolution', manual_resolution=resolution,
                                        current_observation=evidence, fresh_until=fresh_until))
    _object_require(not _has_cancellation(path, verified_state),
                    'Cancelled jobs cannot be remedy sources; human review is required')
    outputs = []
    if consumed.get('aborted_before_dispatch') is not None:
        _require(consumed.get('dispatch_started') is None and report['job_id'] is None
                 and report['state'] in ('prepared', 'submitting', 'failed_presubmit'),
                 'Aborted remedy source contradicts dispatch evidence')
        classification = _presubmit_classification(verified_state, record, digest)
        completion = dict(source='aborted-before-dispatch', evidence=deepcopy(consumed['aborted_before_dispatch']))
        status_hash = sha256(_read_file(path / 'status.json')).hexdigest()
    else:
        incomplete = bool(list(path.glob('fetch-incomplete-*.json')))
        interrupted = report['state'] == 'interrupted'
        _object_require(report['state'] == ('finished' if incomplete else 'fetched') or interrupted and incomplete,
                        'Remedy requires confirmed completion and fetched outputs')
        completion, status_hash = (_interrupted_completion(path, manifest, report, consumed) if interrupted else
                                   _completion(path, manifest, report))
        _object_require(completion.get('scheduler_state') != 'CANCELLED',
                        'Cancelled jobs cannot be remedy sources; human review is required')
        if incomplete:
            files, outputs, reference = _incomplete_remedy_outputs(path, manifest, completion)
            completion['incomplete_fetch'] = reference
        else:
            files = _fetched_outputs(path, manifest)
            outputs = [dict(name=name, size=len(data), sha256=sha256(data).hexdigest())
                       for name, data in sorted(files.items())]
        if _walltime_failure(completion):
            classification = 'walltime'
        elif interrupted:
            classification = 'interrupted'
        elif manifest['template'] in ('gaussian', 'gaussian-cp'):
            from ag._parse_outputs import gaussian_job_sections, gaussian_section_text, termination
            from ag.remote import output_names
            log_name = output_names(manifest)[0]
            if incomplete and log_name not in files:
                _object_require(completion['exit_code'] != 0 or completion['exit_signal'] != 0,
                         'Missing Gaussian log does not prove program failure')
                classification = 'program-exit'
                return dict(failure_class=classification, source_attempt=path.name, source_ownership_sha256=digest,
                    status_sha256=status_hash, outputs=outputs, completion=completion)
            text = files[log_name].decode('utf-8', errors='replace')
            sections, warnings = gaussian_job_sections(text)
            _object_require(not warnings, 'Latest Gaussian job has ambiguous sections')
            if all(section['termination'] == 'normal' for section in sections):
                _object_require(not incomplete, 'Incomplete normally terminated Gaussian result is not a remedy source')
                completion['scientific_review'] = _read_scientific_review(path, record, digest, verified_state, manifest)
                classification = 'gaussian-ts-curvature'
            else:
                if incomplete and sections[-1]['termination'] != 'error':
                    _object_require(completion['exit_code'] != 0 or completion['exit_signal'] != 0,
                             'Incomplete Gaussian log does not prove program failure')
                    return dict(failure_class='program-exit', source_attempt=path.name, source_ownership_sha256=digest,
                        status_sha256=status_hash, outputs=outputs, completion=completion)
                _object_require(sections[-1]['termination'] == 'error', 'Latest Gaussian job is not a verified failed section')
                failed = gaussian_section_text(text, sections[-1])
                parsed = termination(failed, 'Normal termination of Gaussian')
                hint = parsed['error_hint'] or ''
                classification = 'gaussian-error'
                for label, category in (('SCF 不收敛', 'gaussian-scf'), ('优化步数用完', 'gaussian-opt-steps'),
                                        ('IRC 校正失败', 'gaussian-irc-corrector'),
                                        ('TS 曲率不符', 'gaussian-ts-curvature')):
                    if label in hint:
                        classification = category
                        break
        else:
            code = completion.get('receipt', {}).get('returncode', completion.get('exit_code'))
            signal = completion.get('exit_signal', 0)
            _object_require(code != 0 or signal != 0, 'Successful program exit is not a remedy source')
            classification = 'program-exit'
    return dict(failure_class=classification, source_attempt=path.name, source_ownership_sha256=digest,
                status_sha256=status_hash, outputs=outputs, completion=completion)


def read_reservations(cfg, *, states=None):
    """Cross-check both sides of all local ownership before returning placements.

    Caller holds machine_lock. states maps absolute study directories to raw,
    verified T184 state already held under the caller's study lock. No dict
    supplied from a CLI/LLM may enter that argument. UNKNOWN/undispatched claims
    remain reserved; a missing or truncated side is an error, never zero.
    """
    records = _read_global_records()
    registered = _registered_studies()
    for saved in records:
        record = saved['record']
        _require(registered.get(record['study_key']) == _record_path(record).parent.parent,
                 'Reservation is missing its global study registration')
    supplied = {str(Path(key).absolute()): value for key, value in (states or {}).items()}
    roots = {Path(cfg['local']['studies_root']).absolute()}
    roots.update(Path(item['record']['studies_root']) for item in records)
    roots.update(path.parent for path in registered.values())
    studies = {path for root in roots for path in _study_paths(root)}
    studies.update(_record_path(item['record']).parent.parent for item in records)
    current_states = {str(path): _load_state(path, supplied) for path in studies}
    by_path = {str(_record_path(item['record'])): item for item in records}
    _require(len(by_path) == len(records), 'Duplicate reservation path')
    # Reverse check catches deletion of a global record, including a wholly
    # missing registry, while never reconstructing consumed counts from intent.
    for path, current in current_states.items():
        for attempt_id, item in (current or {}).get('submissions', {}).items():
            target = str(Path(path) / 'attempts' / attempt_id)
            _require(target in by_path and by_path[target]['sha256'] == item.get('ownership_sha256'),
                     'Consumed Attempt is missing its global reservation')
    entries = _entries(cfg)
    identities = {name: account_identity(entry) for name, entry in entries.items()}
    from ag.config import cluster_identity, scheduler_kind
    grouped = {}
    for name, identity in identities.items():
        explicit = cluster_identity(entries[name])
        _require(identity not in grouped or grouped[identity] == explicit,
                 'Equivalent accounts use unmerged cluster identities; use one verified SSH identity')
        grouped[identity] = explicit
    placements, batch_inputs, warnings = [], {}, []
    for saved in records:
        record, digest = saved['record'], saved['sha256']
        path = _record_path(record)
        raw, manifest = _manifest_bytes(path)
        _require(sha256(raw).hexdigest() == record['manifest_sha256'] and manifest['inputs'] == record['inputs'],
                 'Reservation manifest/input hashes changed')
        consumed = _check_consumption(record, digest, current_states.get(str(path.parent.parent)))
        report = _owned_audit(path, record, digest)
        _require(report['job_id'] is None or consumed.get('dispatch_started') is not None,
                 'Scheduler binding has no recorded dispatch boundary')
        aborted = consumed.get('aborted_before_dispatch')
        if aborted is not None:
            _require(consumed.get('dispatch_started') is None and report['job_id'] is None
                     and report['state'] in ('prepared', 'submitting', 'failed_presubmit'),
                     'Aborted reservation contradicts scheduler binding or dispatch')
            saved['outcome'] = 'aborted_before_dispatch'
            continue
        aliases = [name for name, identity in identities.items() if identity == record['account_sha256']]
        _require(bool(aliases), 'Active reservation account is not mapped by current configuration')
        name = manifest.get('cluster', 'default')
        name = name if name in aliases else sorted(aliases)[0]
        original = record['selection']['input']
        request = original['request']
        choice = record['selection']['result']['recommendation']
        _require(isinstance(choice, dict), 'Reservation lost its selected position')
        expected = dict(study_id=record['study_id'], study_key=record['study_key'], round_id=record['round_id'], run_id=record['run_id'],
                        object_id=record['object_id'], template=manifest['template'], walltime=manifest['walltime'])
        _require(all(request.get(k) == v for k, v in expected.items()), 'Reservation selection ownership changed')
        bound_job = submission.raw_job(manifest, report['job_id']) if report['job_id'] else None
        current = current_states.get(str(path.parent.parent))
        absence = _terminal_absence(cfg, manifest, report, account_sha256=record['account_sha256'],
                                    cluster=name, since=consumed['at'])
        resolution = _manual_resolution(current, path, digest)
        resolved = False
        raw_status = _read_file(path / 'status.json') if resolution is not None else None
        kind = _resolution_kind(path, report, _json(raw_status), current) if raw_status is not None else None
        if resolution is not None and resolution['kind'] == kind:
            from ag.autonomy import ObjectRefused
            try:
                _resolution_observation(cfg, record, manifest, report, consumed, raw_status, kind)
            except ObjectRefused:
                pass  # Lost negative evidence retains the reservation.
            else:
                resolved = True
        placement_state = ('finished' if resolved else
            _placement_state(path, manifest, report, current=current, absence=absence))
        placement = dict(study_id=record['study_id'], study_key=record['study_key'], attempt_id=record['attempt_id'], cluster=name,
            scheduler_job_name=manifest['attempt_id'] if manifest.get('scheduler') == 'slurm' else manifest['pbs_job_name'],
            state=placement_state, cores=manifest['cores'], mem_gb=manifest['mem_gb'], job_id=bound_job,
            manifest_sha256=record['manifest_sha256'], record_sha256=digest,
            round_id=record['round_id'], run_id=record['run_id'], object_id=record['object_id'],
            cell_id=choice['cell_id'], capacity_node=choice['capacity_node'], target_node=choice.get('target_node'),
            config_sha256=record['routing_sha256'], selected_at=original['selected_at'],
            batch_input_sha256=choice['batch_input_sha256'])
        placements.append(placement)
        key = record['selection']['result']['evidence']['input_sha256']
        _require(key not in batch_inputs or batch_inputs[key] == original, 'Conflicting original batch inputs')
        batch_inputs[key] = deepcopy(original)
        saved['outcome'] = 'retained'
    # Manual local reservations count towards cores, never autonomous job caps.
    for root in roots:
        for path in _study_paths(root):
            attempts = path / 'attempts'
            fd = disk.directory(attempts)
            try:
                names = os.listdir(fd)
            finally:
                os.close(fd)
            for name in names:
                if name.startswith('.'):
                    continue
                target = attempts / name
                if str(target) in by_path:
                    continue
                directory = disk.directory(target)
                os.close(directory)
                warning = _manual_terminal_accounting(target)
                if warning is not None:
                    warnings.append(warning)
                    continue
                unverified_manual = False
                try:
                    report = audit(target)
                except ValueError:
                    current = _json(_read_file(target / 'status.json'))
                    _require(current.get('state') in ('submitted', 'running', 'stalled',
                             'awaiting_second_observation', 'unknown'),
                             'Unverified manual reservation has no nonterminal status')
                    # Missing historical authorization must retain usage, but
                    # an autonomous origin must never become a manual fallback.
                    for filename in ('submission-summary.json', 'submission.json'):
                        if os.path.lexists(target / filename):
                            value = _json(_read_file(target / filename))
                            authorization = value.get('authorization') if isinstance(value, dict) else None
                            _require(not isinstance(authorization, dict)
                                     or authorization.get('method') != 'autonomy-policy',
                                     'Autonomous summary is missing its global reservation')
                    for line in _read_file(path / 'journal.jsonl').splitlines():
                        event = _json(line)
                        detail = event.get('detail')
                        _require(not (event.get('attempt_id') == name
                                 and event.get('action') == 'submit_authorization'
                                 and isinstance(detail, dict) and detail.get('method') == 'autonomy-policy'),
                                 'Autonomous authorization is missing its global reservation')
                    report = dict(classification='reserved', state=current['state'], job_id=None)
                    unverified_manual = True
                if report['classification'] == 'unconsumed':
                    continue
                raw, manifest = _manifest_bytes(target)
                _require(root == Path(cfg['local']['studies_root']).absolute(),
                         'Unmapped historical manual reservation requires reconciliation')
                cluster = manifest.get('cluster', 'default')
                _require(cluster in entries, 'Manual reservation cluster is not configured')
                if unverified_manual:
                    _require(type(manifest['cores']) is int and manifest['cores'] > 0
                             and type(manifest['mem_gb']) in (int, float)
                             and math.isfinite(manifest['mem_gb']) and manifest['mem_gb'] > 0
                             and manifest.get('scheduler', 'pbs') == scheduler_kind(entries[cluster]),
                             'Unverified manual reservation resources or scheduler are invalid')
                    report['evidence_sha256'] = {'manifest.json': sha256(raw).hexdigest()}
                    warnings.append(dict(kind='manual_unverified_reserved',
                        study_key=study_identity(path)['study_key'], study_id=manifest['study_id'],
                        attempt_id=name, state=report['state'], cores=manifest['cores']))
                raw_job = submission.raw_job(manifest, report['job_id']) if report['job_id'] else None
                placement_state = 'reserved' if unverified_manual else _placement_state(target, manifest, report)
                placements.append(dict(study_id=manifest['study_id'], study_key=study_identity(path)['study_key'], attempt_id=name, cluster=cluster,
                    scheduler_job_name=manifest['attempt_id'] if manifest.get('scheduler') == 'slurm' else manifest['pbs_job_name'],
                    state=placement_state, cores=manifest['cores'], mem_gb=manifest['mem_gb'], job_id=raw_job,
                    manifest_sha256=sha256(raw).hexdigest(), record_sha256=approval.digest(report['evidence_sha256']),
                    target_node=manifest.get('node_target', {}).get('name'), round_id=None, run_id=None))
    return dict(records=records, placements=placements, batch_inputs=batch_inputs, warnings=warnings)


def write_waiting(cfg, study_id, selection, *, batch_inputs=None):
    """Store a no-position decision; caller binds its digest with guard.waiting."""
    study.identifier(study_id)
    result = verify_selection(cfg, selection, batch_inputs=batch_inputs)
    request = selection['input']['request']
    _require(request['study_id'] == study_id and result.get('recommendation') is None,
             'Waiting evidence must be an unselected decision for this study')
    identity = study_identity(Path(cfg['local']['studies_root']) / study_id)
    _require(request['study_key'] == identity['study_key'], 'Waiting study key mismatch')
    value = dict(schema='ag-autonomy-waiting/1', studies_root=str(Path(cfg['local']['studies_root']).absolute()),
                 study_id=study_id, **identity, selection=deepcopy(selection))
    raw = disk.encode(value)
    digest = sha256(raw).hexdigest()
    _register_study(Path(cfg['local']['studies_root']) / study_id)
    with _registry('autonomy-waiting', create=True) as store:
        store.exclusive(digest + '.json', raw)
    return digest


def waiting_history(cfg, current, study_id, object_id):
    """Join immutable no-position evidence to later real starts for one object."""
    study.identifier(study_id)
    study.identifier(object_id)
    round_id = current['current_round']
    events = [e for e in current.get('waiting', [])
              if e['round_id'] == round_id and e['object_id'] == object_id]
    if not events:
        return None, []
    verified = []
    with _registry('autonomy-waiting') as store:
        for event in events:
            digest = event['record_sha256']
            _require(_hash(digest), 'Invalid waiting evidence hash')
            raw = store.read(digest + '.json')
            value = _json(raw)
            _fields(value, {'schema', 'studies_root', 'study_id', 'study_key', 'study_device', 'study_inode', 'selection'}, 'waiting record')
            identity = study_identity(Path(cfg['local']['studies_root']) / study_id)
            _require(sha256(raw).hexdigest() == digest and raw == disk.encode(value)
                     and value['schema'] == 'ag-autonomy-waiting/1'
                     and value['study_id'] == study_id
                     and all(value[key] == item for key, item in identity.items())
                     and value['studies_root'] == str(Path(cfg['local']['studies_root']).absolute()),
                     'Waiting record identity/hash mismatch')
            _selection(value['selection'])
            original = value['selection']['input']
            request = original['request']
            _require(value['selection']['result'].get('recommendation') is None
                     and all(request[k] == event[k] for k in ('round_id', 'run_id', 'object_id'))
                     and request['study_id'] == study_id and request['study_key'] == identity['study_key'],
                     'Waiting decision and event disagree')
            plan = current['plans'][event['plan_id']]
            run = current['runs'][event['run_id']]
            _require(plan['sha256'] == event['plan_sha256'] and plan['confirmation'] is not None
                     and run['round_id'] == round_id and run['plan_id'] == event['plan_id']
                     and not run.get('observe_only', False), 'Unverified waiting plan or run')
            selected = approval.timestamp(original['selected_at']).timestamp()
            _require(run['started_at'] <= selected <= event['at'], 'Waiting decision time is outside its run')
            verified.append(event['at'])
    since = min(verified)
    wakeups = [dict(study_id=study_id, study_key=identity['study_key'], round_id=round_id, run_id=run_id, object_id=object_id,
                    started_at=datetime.fromtimestamp(run['started_at'], timezone.utc).isoformat())
               for run_id, run in current['runs'].items()
               if run['round_id'] == round_id and run['started_at'] > since and not run.get('observe_only', False)]
    return datetime.fromtimestamp(since, timezone.utc).isoformat(), wakeups


def verified_authorization(path, value, *, verified_state=None):
    """Recover only authorization already bound before scheduler dispatch.

    This does not authorize a new submission, repair a record or consume again.
    It deliberately avoids submission.verified_job to keep recovery acyclic.
    """
    path = Path(path).absolute()
    with _registry('autonomy-reservations') as store:
        raw = store.read(_filename(path))
    record = _json(raw)
    _fields(record, _RECORD_KEYS, 'reservation record')
    _context(record)
    _require(record['schema'] == RESERVATION_SCHEMA and _record_path(record) == path
             and raw == disk.encode(record), 'Invalid immutable reservation encoding/identity')
    _require(_registered_studies().get(record['study_key']) == path.parent.parent,
             'Missing global study registration')
    digest = sha256(raw).hexdigest()
    expected = authorization(record, digest)
    _require(value == expected, 'Authorization is not the exact reserved ownership')
    # A status publication already holds the study mutex. Only its freshly
    # verified raw state may be supplied here; no CLI accepts this argument.
    supplied = {} if verified_state is None else {str(path.parent.parent): verified_state}
    current = _load_state(path.parent.parent, supplied)
    consumed = _check_consumption(record, digest, current)
    _require(consumed.get('dispatch_started') is not None
             and consumed.get('aborted_before_dispatch') is None,
             'Scheduler binding requires a recorded dispatch boundary')
    _owned_audit(path, record, digest)
    return deepcopy(expected)
