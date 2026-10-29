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
_OPTIONAL_CONTEXT_KEYS = {'slurm_probe', 'reroute_source'}
_CONSUME_KEYS = {'attempt_id', 'object_id', 'failure_class', 'round_id', 'run_id',
                 'plan_sha256', 'rule_sha256', 'max_attempts'}
_INPUT_KEYS = {'config_sha256', 'request', 'snapshots', 'placements', 'wakeups', 'selected_at'}
_REQUEST_KEYS = {'template', 'job_class', 'walltime', 'study_id', 'study_key', 'round_id', 'run_id',
                 'object_id', 'waiting_since', 'parent_cluster'}
_FAILURE_CLASSES = {'presubmit', 'gaussian-scf', 'gaussian-opt-steps',
                    'gaussian-irc-corrector', 'gaussian-ts-curvature', 'gaussian-error', 'program-exit', 'walltime', 'no-progress'}
_REROUTE_KEYS = {'study_key', 'attempt_id', 'record_sha256', 'stopped_sha256',
                 'manifest_sha256', 'bundle_sha256', 'round_id', 'plan_sha256', 'object_id', 'cell_id'}
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


def _fields(value, keys, label):
    _require(isinstance(value, dict) and set(value) == keys, 'Invalid ' + label)


def _reservation_fields(value, keys, label):
    _require(isinstance(value, dict) and keys <= set(value)
             and set(value) <= keys | _OPTIONAL_CONTEXT_KEYS, 'Invalid ' + label)


def _slurm_probe(value):
    """Validate frozen probe observations without granting origin eligibility."""
    from ag import remote, slurm
    _fields(value, {'record', 'sha256'}, 'Slurm probe envelope')
    record = value['record']
    _require(_hash(value['sha256']) and sha256(disk.encode(record)).hexdigest() == value['sha256'],
             'Slurm probe hash mismatch')
    keys = {'schema', 'binding', 'queries', 'versions', 'scheduler_cluster', 'capture_started_at',
            'capture_finished_at', 'format_candidate', 'origin_available', 'reroute_authorized', 'reason'}
    execution = isinstance(record, dict) and 'execution_versions' in record
    if execution:
        keys |= {'execution_versions', 'bound_submit_format_candidate',
                 'instance_cancel_format_candidate', 'live_validated'}
    _require(isinstance(record, dict) and keys <= set(record) and set(record) <= keys | {'unavailable'},
             'Invalid Slurm probe record')
    _require(record['schema'] == 'ag-slurm-submission-probe/1'
             and type(record['format_candidate']) is bool
             and record['origin_available'] is False and record['reroute_authorized'] is False
             and isinstance(record['reason'], str) and bool(record['reason'].strip()),
             'Slurm probe cannot assert original-instance or reroute authority')
    if execution:
        _require(record['live_validated'] is False
                 and type(record['bound_submit_format_candidate']) is bool
                 and type(record['instance_cancel_format_candidate']) is bool,
                 'Execution-format probe cannot assert live validation')
    _fields(record['binding'], {'attempt_id', 'study_id', 'cluster', 'scheduler',
                               'manifest_sha256', 'bundle_sha256'}, 'Slurm probe binding')
    _require(record['binding']['scheduler'] == 'slurm', 'Probe must bind a Slurm Attempt')
    for key in ('attempt_id', 'study_id'):
        study.identifier(record['binding'][key])
    cluster_name(record['binding']['cluster'])
    _require(all(_hash(record['binding'][key]) for key in ('manifest_sha256', 'bundle_sha256')),
             'Invalid Slurm probe bound hashes')
    def timestamp(value):
        _require(type(value) in (int, float) and math.isfinite(value) and value >= 0,
                 'Invalid Slurm probe timestamp')
        return value
    previous = timestamp(record['capture_started_at'])
    finished = timestamp(record['capture_finished_at'])
    missing_config = record.get('unavailable') in ('config_tool_missing', 'config_option_unsupported')
    _require(isinstance(record['queries'], list) and len(record['queries']) == (1 if missing_config else 5 if execution else 3),
             'Slurm probe requires complete controller/client observations')
    expected = [('config', remote.slurm_evidence_config()),
                ('scontrol-version', remote.slurm_evidence_version('scontrol')),
                ('sacct-version', remote.slurm_evidence_version('sacct'))]
    if execution:
        expected.extend((program + '-version', remote.slurm_evidence_version(program))
                        for program in ('sbatch', 'scancel'))
    for query, (label, command) in zip(record['queries'], expected):
        _fields(query, {'label', 'command', 'operation', 'started_at', 'finished_at', 'returncode',
                        'stdout', 'stderr', 'stdout_sha256', 'stderr_sha256'}, 'Slurm probe query')
        _require(query['label'] == label and query['command'] == command.text
                 and query['operation'] == command.operation
                 and type(query['returncode']) is int and query['returncode'] >= 0
                 and query['returncode'] != 255,
                 'Slurm probe query identity or result mismatch')
        _require(previous <= timestamp(query['started_at']) <= timestamp(query['finished_at']) <= finished,
                 'Slurm probe query time is inconsistent')
        previous = query['finished_at']
        for stream in ('stdout', 'stderr'):
            _require(isinstance(query[stream], str) and _hash(query[stream + '_sha256'])
                     and sha256(query[stream].encode()).hexdigest() == query[stream + '_sha256'],
                     'Slurm probe response hash mismatch')
        _require(query['returncode'] != 0 or not query['stderr'].strip(),
                 'Slurm probe contains unexpected diagnostics')
    config_query = record['queries'][0]
    if missing_config:
        _require(config_query['returncode'] == (127 if record['unavailable'] == 'config_tool_missing' else 1)
                 and not config_query['stdout'].strip() and bool(config_query['stderr'].strip())
                 and record['scheduler_cluster'] is None and record['versions'] == {}
                 and record['format_candidate'] is False,
                 'Unavailable controller probe cannot assert an actual cluster or format eligibility')
        if execution:
            _require(record['execution_versions'] == {key: dict(raw=None, parsed=None) for key in ('sbatch', 'scancel')}
                     and not record['bound_submit_format_candidate']
                     and not record['instance_cancel_format_candidate'],
                     'Unavailable controller cannot qualify an execution format')
        # The formal collector classified this negative observation. Keeping
        # its bytes proves no positive fact about a cluster or original job.
        return record
    _require(config_query['returncode'] == 0, 'Slurm probe controller query did not succeed')
    controller = slurm.parse_evidence_config(record['queries'][0]['stdout'], strict_version=False)
    _require(record['scheduler_cluster'] == controller['cluster'], 'Slurm probe actual cluster mismatch')
    _fields(record['versions'], {'controller', 'scontrol', 'sacct'}, 'Slurm probe versions')
    raw_versions = {'controller': controller['server_version'],
                    'scontrol': record['queries'][1]['stdout'], 'sacct': record['queries'][2]['stdout']}
    for program, raw in raw_versions.items():
        _fields(record['versions'][program], {'raw', 'parsed'}, 'Slurm probe version')
        query = record['queries'][1 if program == 'scontrol' else 2] if program != 'controller' else None
        parsed = None
        if query is None or query['returncode'] == 0:
            try:
                parsed = slurm.parse_evidence_version('slurm ' + (raw or '') if program == 'controller' else raw)
            except ValueError:
                pass
        _require(record['versions'][program] == dict(raw=raw, parsed=parsed),
                 'Slurm probe version differs from original response')
    if execution:
        _fields(record['execution_versions'], {'sbatch', 'scancel'}, 'Slurm execution versions')
        for index, program in enumerate(('sbatch', 'scancel'), 3):
            query = record['queries'][index]
            raw, parsed = query['stdout'], None
            if query['returncode'] == 0:
                try:
                    parsed = slurm.parse_evidence_version(raw)
                except ValueError:
                    pass
            _require(record['execution_versions'][program] == dict(raw=raw, parsed=parsed),
                     'Slurm execution version differs from original response')
    candidate = all(item['parsed'] == '26.05.5' for item in record['versions'].values())
    _require(record['format_candidate'] is candidate
             and ((candidate and 'unavailable' not in record)
                  or (not candidate and record.get('unavailable') == 'evidence_version_unsupported')),
             'Slurm probe format observation mismatch')
    if execution:
        bound = (all(record['versions'][program]['parsed'] == '26.05.5'
                     for program in ('controller', 'scontrol'))
                 and record['execution_versions']['sbatch']['parsed'] == '26.05.5')
        instance = candidate and record['execution_versions']['scancel']['parsed'] == '26.05.5'
        _require(record['bound_submit_format_candidate'] is bound
                 and record['instance_cancel_format_candidate'] is instance,
                 'Slurm execution-format observation mismatch')
    return record


def _probe_binding(probe, raw, manifest):
    expected = dict(attempt_id=manifest['attempt_id'], study_id=manifest['study_id'],
        cluster=manifest.get('cluster', 'default'), scheduler=manifest.get('scheduler', 'pbs'),
        manifest_sha256=sha256(raw).hexdigest(), bundle_sha256=manifest['bundle_sha256'])
    _require(probe['binding'] == expected and expected['scheduler'] == 'slurm',
             'Slurm probe differs from frozen Attempt identity or bytes')


def _probe_time(probe, run, at):
    _require(isinstance(run, dict) and run['started_at'] <= probe['capture_started_at']
             <= probe['capture_finished_at'] <= at
             and probe['capture_finished_at'] < run['started_at'] + 3600
             and (run.get('ended_at') is None or probe['capture_finished_at'] <= run['ended_at']),
             'Slurm probe was not captured during its consuming wake')


def _regular(store, name):
    return _json(store.read(name))


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
    if record['failure_class'] is None:
        _require(source is None, 'Initial submission cannot declare a remedy source')
    else:
        _require(isinstance(record['failure_class'], str) and record['failure_class'] in _FAILURE_CLASSES,
                 'Unsupported remedy failure class')
        _fields(source, _REMEDY_KEYS, 'remedy source')
        _require(source['failure_class'] == record['failure_class'], 'Remedy classification mismatch')
        study.identifier(source['source_attempt'])
        for key in ('source_ownership_sha256', 'status_sha256'):
            digest(source[key], key)
        _require(isinstance(source['outputs'], list) and isinstance(source['completion'], dict),
                 'Invalid remedy evidence')
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
    if 'slurm_probe' in record:
        _slurm_probe(record['slurm_probe'])
    if 'reroute_source' in record:
        _reroute_source(record['reroute_source'])
        _require(record['failure_class'] is None and record['remedy_source'] is None,
                 'Reroute cannot also declare a failed-program remedy')
        _require(all(record['reroute_source'][key] == record[key]
                     for key in ('round_id', 'plan_sha256', 'object_id')),
                 'Reroute successor changed its original round, plan or object')


def _reroute_source(source):
    _fields(source, _REROUTE_KEYS, 'reroute source')
    for key in ('study_key', 'record_sha256', 'stopped_sha256', 'manifest_sha256',
                'bundle_sha256', 'plan_sha256'):
        _require(_hash(source[key]), 'Invalid reroute source hash')
    for key in ('attempt_id', 'round_id', 'object_id'):
        study.identifier(source[key])
    cluster_name(source['cell_id'])


def _selection(selection):
    _fields(selection, {'input', 'result'}, 'selection envelope')
    original, result = selection['input'], selection['result']
    _fields(original, _INPUT_KEYS, 'original selection input')
    _require(isinstance(result, dict) and result.get('schema') in
             ('ag-routing-ladder/1', 'ag-routing-legacy/1'), 'Unsupported selection result schema')
    legacy = result['schema'] == 'ag-routing-legacy/1'
    keys = _REQUEST_KEYS | ({'tier'} if legacy else set())
    request = original['request']
    _require(isinstance(request, dict) and keys <= set(request)
             and set(request) <= keys | (set() if legacy else {'evaluate_from'}),
             'Invalid original selection request')
    if 'evaluate_from' in request:
        _fields(request['evaluate_from'], {'study_key', 'attempt_id', 'record_sha256'}, 'reroute selection source')
        _require(_hash(request['evaluate_from']['study_key']) and _hash(request['evaluate_from']['record_sha256']),
                 'Invalid reroute selection source hash')
        study.identifier(request['evaluate_from']['attempt_id'])
        _require(result.get('evaluation_only') is True and result.get('evaluate_from') == request['evaluate_from'],
                 'Reroute evaluation source/result mismatch')
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
    function = 'select_legacy' if selection['result']['schema'] == 'ag-routing-legacy/1' else 'select_ladder'
    _require(hasattr(route, function) and hasattr(route, 'ladder_config_identity'),
             'Reviewed routing selector is not available')
    original = selection['input']
    _require(original['config_sha256'] == route.ladder_config_identity(cfg),
             'Routing configuration changed')
    result = getattr(route, function)(cfg, original['snapshots'], **original['request'],
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
                      prepared_remedy=None, prepared_reroute=None):
    """Exclusive durable ownership; caller holds machine + current study locks.

    Call only after freshly reconciling all reservations, selecting from that
    evidence, and checking the plan/rule/lease. This function replays selection
    and freezes actual manifest/input identities; it does not grant authority.
    A crash before the matching T184 consume remains a blocking orphan.
    """
    _reservation_fields(record, _CONTEXT_KEYS, 'reservation context')
    _context(record)
    if 'reroute_source' in record:
        source = verify_reroute_evidence(cfg, verified_state, record['object_id'], prepared_reroute)
        _require(source == record['reroute_source'], 'Reroute source differs from verified stopped consumption')
    else:
        _require(prepared_reroute is None, 'Prepared reroute lacks its frozen source')
        source = verify_remedy_evidence(cfg, verified_state, record['object_id'], prepared_remedy)
        _require(source == record['remedy_source'], 'Remedy source differs from verified previous consumption')
    path = study.local_path(Path(cfg['local']['studies_root']), Path(path).absolute())
    _require(path.parent.name == 'attempts' and path.parent.parent.parent == Path(cfg['local']['studies_root']).absolute(),
             'Reservation must belong to configured studies root')
    _require(not (path / '.submit-claim').exists(), 'Attempt already consumed')
    _require(audit(path)['classification'] == 'unconsumed', 'Attempt already consumed')
    raw, manifest = _manifest_bytes(path)
    _require(manifest.get('reroute_source') == record.get('reroute_source'),
             'Frozen Attempt reroute lineage differs from reservation')
    if 'slurm_probe' in record:
        from ag import autonomy
        probe = record['slurm_probe']['record']
        _probe_binding(probe, raw, manifest)
        _probe_time(probe, verified_state.get('runs', {}).get(record['run_id']), autonomy.now())
    config_path = Path(cfg['_config_path']).absolute()
    _read_file(config_path)  # Reject absent, redirected or special config paths.
    entry = _entries(cfg)[manifest.get('cluster', 'default')]
    result = verify_selection(cfg, record['selection'], batch_inputs=batch_inputs)
    choice = result.get('recommendation')
    _require(isinstance(choice, dict), 'Reservation requires a selected position')
    request = record['selection']['input']['request']
    expected_from = ({key: record['reroute_source'][key] for key in
                     ('study_key', 'attempt_id', 'record_sha256')} if 'reroute_source' in record else None)
    _require(request.get('evaluate_from') == expected_from, 'Selection does not use its verified reroute source')
    if prepared_reroute is not None:
        _require(request['job_class'] == prepared_reroute.job_class,
                 'Reroute successor changed the original job class')
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
                _reservation_fields(value, _RECORD_KEYS, 'reservation record')
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
    if 'slurm_probe' in record:
        raw, manifest = _manifest_bytes(path)
        _probe_binding(_slurm_probe(record['slurm_probe']), raw, manifest)
        probe_bytes = _read_file(Path(path) / 'slurm-origin-probe.json')
        _require(probe_bytes == disk.encode(record['slurm_probe']['record'])
                 and sha256(probe_bytes).hexdigest() == record['slurm_probe']['sha256'],
                 'Slurm probe side record differs from immutable reservation')
    else:
        _require(not os.path.lexists(Path(path) / 'slurm-origin-probe.json'),
                 'Unreserved Slurm probe cannot become original-instance evidence')
    if (Path(path) / 'submission.json').exists():
        binding = _json(_read_file(Path(path) / 'submission.json'))
        _require(binding.get('scheduler_probe_sha256') == record.get('slurm_probe', {}).get('sha256'),
                 'Submission original probe reference differs from reservation')
        probe = record.get('slurm_probe', {}).get('record', {})
        if probe.get('bound_submit_format_candidate') is True:
            _require(binding.get('scheduler_cluster') == probe['scheduler_cluster'],
                     'Known scheduler cluster differs from the original bound target')
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
    if 'slurm_probe' in record:
        _probe_time(record['slurm_probe']['record'], run, item['at'])
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


def _verified_stopped(path, current):
    """Replay T187's exact-instance proof and its real cancellation ledger."""
    from ag import autonomy, autonomy_cancel, cancel, autonomy_submission
    if _CAPTURE_READS.get() is None:
        with _capture_reads():
            return _verified_stopped(path, current)
    filename = 'autonomy-cancel-stopped.json'
    raw = _read_file(path / filename)
    value = _json(raw)
    _require(raw == disk.encode(value) and value.get('schema') == 'ag-autonomy-cancel-stopped/1',
             'Invalid canonical stopping proof')
    # T187 reads these files itself. Capture their identities before replay so
    # a short publication check need not parse scheduler output again.
    documents = [value]
    for name in ('autonomy-cancel-request.json', 'autonomy-cancel-response.json',
                 'slurm-origin-probe.json', 'slurm-origin-claim.json', 'slurm-origin.json'):
        documents.append(_json(_read_file(path / name)))
    _read_file(path / '.cancel-claim')
    references = set()
    def references_in(item):
        if isinstance(item, dict):
            reference = item.get('observation')
            if reference is not None:
                _require(isinstance(reference, str)
                         and re.fullmatch(r'scheduler-observations/\d{8}T\d{12}Z', reference),
                         'Invalid stopping observation reference')
                references.add(reference)
            for child in item.values():
                references_in(child)
        elif isinstance(item, list):
            for child in item:
                references_in(child)
    for document in documents:
        references_in(document)
    for reference in sorted(references):
        directory = path / reference
        fd = disk.directory(directory)
        try:
            reads = _CAPTURE_READS.get()
            if reads is not None:
                reads.directory(directory)
            for name in os.listdir(fd):
                _read_file(directory / name)
        finally:
            os.close(fd)
    accepted = cancel._accepted_cancellation(path, autonomy_submission, _CAPTURE_READS.get())
    cancel._check_accepted_cancellation(path, current, autonomy_submission, accepted)
    proof = autonomy_cancel.verify_slurm_stopped(path,
        ownership_sha256=accepted['ownership_sha256'],
        observation=value.get('slurm_instance', {}).get('current_observation'),
        cancel_response=dict(response='autonomy-cancel-response.json', response_sha256=accepted['response_sha256']))
    _require(value == dict(schema='ag-autonomy-cancel-stopped/1', **proof,
                          verified_run_id=value.get('verified_run_id'),
                          verified_plan_sha256=value.get('verified_plan_sha256'),
                          recorded_at=value.get('recorded_at')),
             'Stopping proof differs from its original scheduler evidence')
    run = current.get('runs', {}).get(value['verified_run_id'])
    plan = current.get('plans', {}).get(run.get('plan_id')) if isinstance(run, dict) else None
    _require(isinstance(plan, dict) and plan['sha256'] == value['verified_plan_sha256']
             and run['round_id'] == accepted['request']['round_id']
             and value['verified_plan_sha256'] == accepted['request']['plan_sha256']
             and proof['consumption_sha256'] == accepted['consumption_sha256']
             and type(value['recorded_at']) in (int, float) and math.isfinite(value['recorded_at'])
             and proof['slurm_instance']['current_observation']['capture_finished_at']
                 <= value['recorded_at'] <= autonomy.now(),
             'Stopping proof differs from the actual cancellation run or consumption')
    if proof['kind'] == 'reroute':
        digest = accepted['ownership_sha256']
        _require(accepted['request'].get('lineage_sha256') == digest
                 and current.get('cancellations', {}).get(path.name, {}).get('lineage_sha256') == digest
                 and current.get('reroute_lineages', {}).get(digest) == path.name,
                 'Reroute cancellation lacks its actual one-time lineage consumption')
    return dict(record=value, sha256=sha256(raw).hexdigest())


class PreparedStoppedReservations:
    """Process-local replay receipts for globally registered stopped jobs."""
    def __init__(self, receipts):
        self.receipts = receipts


def prepare_stopped_reservations(cfg, *, states=None):
    """Parse scheduler stopping proofs before acquiring the machine mutex."""
    supplied = {str(Path(key).absolute()): value for key, value in (states or {}).items()}
    receipts = {}
    for saved in _read_global_records():
        record, digest = saved['record'], saved['sha256']
        path = _record_path(record)
        if not os.path.lexists(path / 'autonomy-cancel-stopped.json'):
            continue
        current = _load_state(path.parent.parent, supplied)
        with _capture_reads() as reads:
            stopped = _verified_stopped(path, current)
        receipts[str(path)] = dict(record=record, digest=digest, stopped=stopped, reads=reads,
            consumption=_remedy_signature(_check_consumption(record, digest, current)),
            cancellation=_cancellation_signature(current, path.name))
    return PreparedStoppedReservations(receipts)


def _check_prepared_stop(path, current, prepared):
    _require(type(prepared) is PreparedStoppedReservations,
             'Stopping evidence must be prepared outside the machine lock')
    receipt = prepared.receipts.get(str(Path(path).absolute()))
    _require(receipt is not None, 'New stopping evidence requires preparation outside the machine lock')
    consumed = _check_consumption(receipt['record'], receipt['digest'], current)
    _require(receipt['consumption'] == _remedy_signature(consumed)
             and receipt['cancellation'] == _cancellation_signature(current, path.name),
             'Stopping ownership or cancellation changed after evidence preparation')
    if receipt['stopped']['record']['kind'] == 'reroute':
        _require(current.get('reroute_lineages', {}).get(receipt['digest']) == path.name,
                 'Stopped reroute lineage consumption changed')
    receipt['reads'].verify()


def _placement_state(path, manifest, report, *, current=None, prepared_stops=None):
    local = report['state']
    if current is not None and local in ('cancelled', 'finished', 'fetched'):
        if os.path.lexists(path / 'autonomy-cancel-stopped.json'):
            _check_prepared_stop(path, current, prepared_stops)
            return 'finished'
        if path.name in current.get('cancellations', {}):
            # Acceptance or a later numeric-ID status alone cannot discharge
            # an exact-instance cancellation reservation.
            return 'queued'
    if local in ('finished', 'fetched'):
        _completion(path, manifest, report)
        return 'finished'
    if local == 'unknown':
        return 'unknown'
    if local in ('running', 'stalled'):
        return 'running'
    return 'queued' if report['job_id'] else 'reserved'


def _fetched_outputs(path, manifest):
    """Read published outputs; ordinary fetch keeps a staging hard link."""
    from ag.remote import output_names
    names = output_names(manifest)
    events = [_json(line) for line in _read_file(path.parent.parent / 'journal.jsonl').splitlines()]
    _require(any(event['attempt_id'] == path.name and event['action'] == 'fetch'
                 and event['result'] == 'ok' and event['detail'] == {'files': names} for event in events),
             'Remedy requires a successful fetch journal record')
    _require(not any(event['attempt_id'] == path.name and event['action'] == 'facts'
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


def _incomplete_remedy_outputs(path, manifest, ownership, completion, *, stopped=None):
    """Verify a formal incomplete receipt outside submission locks."""
    from ag import fetch
    from ag.remote import output_names
    _require(manifest.get('scheduler') == 'slurm',
             'Incomplete PBS diagnostics do not prove a stopped failed program')
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
    _require(isinstance(end, dict) and end.get('scheduler') == 'slurm'
             and end.get('queue_absent') is True and type(end.get('at')) in (int, float)
             and math.isfinite(end['at']) and end['at'] >= completion['observed_at'],
             'Incomplete fetch lacks an exact later stopped-job observation')
    account = end.get('accounting')
    if stopped is None:
        expected = dict(job_id=submission.raw_job(manifest, completion['job_id']),
            state=completion['scheduler_state'], exit_code=completion['exit_code'],
            exit_signal=completion['exit_signal'], elapsed=completion['elapsed'],
            allocated_cpus=completion['allocated_cpus'])
        _require(account == expected and account['state'] in
                 ('TIMEOUT', 'FAILED', 'OUT_OF_MEMORY', 'NODE_FAIL', 'COMPLETED'),
                 'Incomplete fetch stop evidence conflicts with exact terminal accounting or is cancellation')
    else:
        _fields(account, {'job_id', 'state', 'exit_code', 'exit_signal', 'elapsed', 'allocated_cpus'},
                'cancelled incomplete accounting')
        _require(account['job_id'] == stopped['binding']['job_id'] and account['state'] == 'CANCELLED'
                 and all(type(account[key]) is int and account[key] >= 0
                         for key in ('exit_code', 'exit_signal', 'allocated_cpus'))
                 and isinstance(account['elapsed'], str) and bool(account['elapsed']),
                 'Incomplete fetch conflicts with the exact cancelled instance')
    probe = ownership.get('slurm_probe', {}).get('record', {})
    binding = _json(_read_file(path / 'submission.json'))
    if probe.get('bound_submit_format_candidate') is True:
        _require(end.get('scheduler_cluster') == binding.get('scheduler_cluster') == probe['scheduler_cluster'],
                 'Incomplete fetch did not verify the original bound scheduler target')
    elif end.get('scheduler_cluster') is not None:
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
    _reservation_fields(record, _RECORD_KEYS, 'reservation record')
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
        raise ValueError('Normal Gaussian result requires an immutable scientific review') from exc
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
    return completion['source'] == 'sacct' and completion.get('scheduler_state') == 'TIMEOUT'


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
        self.cancellation = None


def prepare_remedy_evidence(cfg, verified_state, object_id, *, exclude_attempt=None):
    """Parse and hash remedy evidence outside every submission/publication lock."""
    previous = _remedy_previous(verified_state, object_id, exclude_attempt)
    with _capture_reads() as reads:
        evidence = remedy_evidence(cfg, verified_state, object_id, exclude_attempt=exclude_attempt)
    sources = [path.parent for path in reads.files if path.name == 'status.json']
    _require(len(sources) == (1 if evidence is not None else 0), 'Ambiguous prepared remedy source')
    prepared = PreparedRemedy(str(Path(cfg['local']['studies_root']).absolute()),
        verified_state.get('current_round'), object_id, _remedy_signature(previous), evidence,
        reads, sources[0] if sources else None)
    if evidence is not None and 'cancel_stopped' in evidence['completion']:
        prepared.cancellation = _cancellation_signature(verified_state, evidence['source_attempt'])
    return prepared


def _prepared_remedy_binding(cfg, current, object_id, prepared, exclude_attempt):
    previous = _remedy_previous(current, object_id, exclude_attempt)
    _require(type(prepared) is PreparedRemedy, 'Remedy requires an internal prepared evidence receipt')
    _require(prepared.root == str(Path(cfg['local']['studies_root']).absolute())
             and prepared.round_id == current.get('current_round') and prepared.object_id == object_id
             and prepared.previous == _remedy_signature(previous),
             'Latest actual remedy consumption changed after evidence preparation')
    if prepared.cancellation is not None:
        _require(prepared.cancellation == _cancellation_signature(current, prepared.evidence['source_attempt']),
                 'Accepted cancellation changed after remedy evidence preparation')


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
    refreshed.cancellation = deepcopy(prepared.cancellation)
    return refreshed


def _cancellation_signature(current, attempt_id):
    signature = {key: deepcopy(current.get(key, {}).get(attempt_id))
                 for key in ('cancellations', 'cancellation_results')}
    if isinstance(signature['cancellations'], dict):
        # Public replay hides this secret. The unchanged consumption digest
        # still binds the complete original event, including its owner token.
        signature['cancellations'].pop('token_sha256', None)
    return signature


class PreparedReroute:
    """Verified stopped-source bytes; not serializable execution permission."""
    def __init__(self, remedy, source, manifest, files, cancellation, job_class):
        self._remedy, self.source = remedy, deepcopy(source)
        self.source_manifest, self.source_files = deepcopy(manifest), dict(files)
        self.scientific_identity = attempt.reroute_input_identity(manifest, files)
        self._cancellation = deepcopy(cancellation)
        self.job_class = job_class


def _reroute_binding(cfg, current, object_id, prepared, exclude_attempt):
    _require(type(prepared) is PreparedReroute, 'Reroute requires an internal stopped-source receipt')
    _prepared_remedy_binding(cfg, current, object_id, prepared._remedy, exclude_attempt)
    source = prepared.source
    plan = current.get('plans', {}).get(current.get('current_plan'))
    _require(isinstance(plan, dict) and plan['sha256'] == source['plan_sha256']
             and current.get('current_round') == source['round_id']
             and source['object_id'] == object_id
             and _cancellation_signature(current, source['attempt_id']) == prepared._cancellation,
             'Reroute source plan, round, object or accepted cancellation changed')


def _unique_reroute_successor(source, exclude_attempt):
    for saved in _read_global_records():
        record = saved['record']
        prior = record.get('reroute_source')
        if prior is None or (exclude_attempt is not None and record['study_key'] == source['study_key']
                             and record['attempt_id'] == exclude_attempt):
            continue
        _require((prior['study_key'], prior['attempt_id']) != (source['study_key'], source['attempt_id']),
                 'Stopped source already has an immutable reroute successor')


def _reroute_local_outputs(path, manifest):
    """Reject known product evidence; local absence is not a remote observation."""
    from ag import fetch, remote
    reads = _CAPTURE_READS.get()
    _require(reads is not None, 'Reroute output evidence must be prepared outside locks')
    reads.directory(path)
    reads.directory(path / 'outputs')
    _require(not any(os.path.lexists(path / 'outputs' / name) for name in remote.output_names(manifest)),
             'Reroute source already has declared output evidence')
    events = [_json(line) for line in _read_file(path.parent.parent / 'journal.jsonl').splitlines()]
    _require(not any(event['attempt_id'] == path.name and event['action'] == 'fetch'
                     and event['result'] == 'ok' for event in events),
             'Reroute source has a successful output fetch')
    paths = list(path.glob('fetch-incomplete-*.json'))
    _require(len(paths) <= 1, 'Ambiguous reroute incomplete-fetch evidence')
    if paths:
        receipt = _json(_published_bytes(paths[0]))
        _require(not receipt.get('outputs'), 'Reroute source has positive incomplete-fetch output evidence')
        _require(fetch.incomplete_record(path) == (paths[0].name, receipt),
                 'Reroute incomplete receipt differs from its formal bytes')


def prepare_reroute_evidence(cfg, verified_state, object_id, source_attempt, *, exclude_attempt=None):
    """Reparse the official stopped-instance evidence before taking action locks."""
    study.identifier(source_attempt)
    previous = _remedy_previous(verified_state, object_id, exclude_attempt)
    _require(previous is not None and previous['attempt_id'] == source_attempt,
             'Reroute source must be the unique latest actual object submission')
    with _capture_reads() as reads:
        matches = [saved for saved in _read_global_records()
                   if saved['sha256'] == previous['ownership_sha256']]
        _require(len(matches) == 1, 'Reroute source lacks its unique global ownership')
        saved = matches[0]
        record, digest = saved['record'], saved['sha256']
        path = _record_path(record)
        _require(path.parent.parent.parent == Path(cfg['local']['studies_root']).absolute()
                 and _registered_studies().get(record['study_key']) == path.parent.parent,
                 'Reroute source study location changed')
        _require('reroute_source' not in record, 'An already rerouted job cannot be rerouted again')
        _require(record['selection']['result']['schema'] == 'ag-routing-ladder/1',
                 'Reroute requires the reviewed ladder selector')
        consumed = _check_consumption(record, digest, verified_state)
        _require(consumed.get('dispatch_started') is not None
                 and consumed.get('aborted_before_dispatch') is None,
                 'Reroute requires a real dispatched source')
        report = _owned_audit(path, record, digest)
        _require(report['state'] in ('cancelled', 'finished', 'fetched'),
                 'Reroute source is not stopped')
        raw, manifest = _manifest_bytes(path)
        _reroute_local_outputs(path, manifest)
        if report['state'] != 'cancelled':
            completion, _ = _completion(path, manifest, report)
            _require(completion.get('scheduler_state') == 'CANCELLED',
                     'Reroute terminal status conflicts with the exact cancelled instance')
        stopped = _verified_stopped(path, verified_state)
        _require(stopped['record']['kind'] == 'reroute', 'Reroute requires its formal never-started stopping proof')
        _require(stopped['record']['ownership_sha256'] == digest,
                 'Reroute stopped evidence belongs to another submission')
        request = _json(_read_file(path / 'autonomy-cancel-request.json'))
        source_key = {key: record[key] for key in ('study_key', 'attempt_id')}
        source_key['record_sha256'] = digest
        selection = request.get('routing_selection')
        batches = {item['record']['selection']['result']['evidence']['input_sha256']:
                   item['record']['selection']['input'] for item in _read_global_records()}
        result = verify_selection(cfg, selection, batch_inputs=batches)
        choice = result.get('recommendation')
        _require(selection['input']['request'].get('evaluate_from') == source_key
                 and selection['input']['request']['job_class'] == record['selection']['input']['request']['job_class']
                 and result.get('evaluation_only') is True and result.get('evaluate_from') == source_key
                 and isinstance(choice, dict) and choice.get('eligible') is True
                 and choice.get('needs_queue') is False and choice.get('capacity', {}).get('availability') == 'enough'
                 and choice.get('cell_id') != record['selection']['result']['recommendation']['cell_id'],
                 'Reroute cancellation lacks its replayable higher immediate candidate')
        source = dict(study_key=record['study_key'], attempt_id=source_attempt, record_sha256=digest,
            stopped_sha256=stopped['sha256'], manifest_sha256=sha256(raw).hexdigest(),
            bundle_sha256=manifest['bundle_sha256'], round_id=record['round_id'],
            plan_sha256=record['plan_sha256'], object_id=record['object_id'],
            cell_id=record['selection']['result']['recommendation']['cell_id'])
        _reroute_source(source)
        files = {item['name']: _read_file(path / 'inputs' / item['name']) for item in manifest['inputs']}
        status_hash = sha256(_read_file(path / 'status.json')).hexdigest()
        proxy = PreparedRemedy(str(Path(cfg['local']['studies_root']).absolute()),
            verified_state.get('current_round'), object_id, _remedy_signature(previous),
            {'status_sha256': status_hash}, reads, path)
        prepared = PreparedReroute(proxy, source, manifest, files,
                                  _cancellation_signature(verified_state, source_attempt),
                                  record['selection']['input']['request']['job_class'])
        _reroute_binding(cfg, verified_state, object_id, prepared, exclude_attempt)
        _unique_reroute_successor(source, exclude_attempt)
    return prepared


def verify_reroute_evidence(cfg, verified_state, object_id, prepared, *, exclude_attempt=None):
    """Inside the transaction, check unchanged metadata and unique lineage."""
    _reroute_binding(cfg, verified_state, object_id, prepared, exclude_attempt)
    prepared._remedy.reads.verify()
    _unique_reroute_successor(prepared.source, exclude_attempt)
    return deepcopy(prepared.source)


def refresh_reroute_evidence(cfg, verified_state, object_id, prepared, *, exclude_attempt=None):
    """Refresh bounded local receipts outside locks without reparsing outputs."""
    _reroute_binding(cfg, verified_state, object_id, prepared, exclude_attempt)
    proxy = refresh_remedy_evidence(cfg, verified_state, object_id, prepared._remedy,
                                    exclude_attempt=exclude_attempt)
    return PreparedReroute(proxy, prepared.source, prepared.source_manifest, prepared.source_files,
                          prepared._cancellation, prepared.job_class)


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
    _require(not any(event['attempt_id'] == path.name and event['action'] == 'facts'
                     and isinstance(event.get('detail'), dict) and event['detail'].get('status') == 'conflict'
                     for event in events), 'Conflicting facts require human review before a remedy')
    outputs = []
    if consumed.get('aborted_before_dispatch') is not None:
        _require(consumed.get('dispatch_started') is None and report['job_id'] is None
                 and report['state'] in ('prepared', 'submitting', 'failed_presubmit'),
                 'Aborted remedy source contradicts dispatch evidence')
        classification = 'presubmit'
        completion = dict(source='aborted-before-dispatch', evidence=deepcopy(consumed['aborted_before_dispatch']))
        status_hash = sha256(_read_file(path / 'status.json')).hexdigest()
    else:
        incomplete = bool(list(path.glob('fetch-incomplete-*.json')))
        if os.path.lexists(path / 'autonomy-cancel-stopped.json'):
            stopped = _verified_stopped(path, verified_state)
            _require(stopped['record']['kind'] == 'no_progress',
                     'A stopped reroute requires its explicit reroute successor')
            _require(report['state'] in ('cancelled', 'finished', 'fetched'),
                     'No-progress remedy requires a formally stopped source')
            status_hash = sha256(_read_file(path / 'status.json')).hexdigest()
            completion = dict(source='slurm-cancel-stopped', job_id=report['job_id'],
                observed_at=stopped['record']['slurm_instance']['current_observation']['capture_finished_at'],
                cancel_stopped=stopped)
            if incomplete:
                _, outputs, reference = _incomplete_remedy_outputs(path, manifest, record, completion,
                                                                 stopped=stopped['record'])
                completion['incomplete_fetch'] = reference
            else:
                _require(report['state'] == 'fetched', 'No-progress remedy requires fetched outputs')
                terminal, status_hash = _completion(path, manifest, report)
                _require(terminal.get('scheduler_state') == 'CANCELLED',
                         'Fetched terminal status conflicts with the exact cancelled instance')
                completion['terminal'] = terminal
                files = _fetched_outputs(path, manifest)
                outputs = [dict(name=name, size=len(data), sha256=sha256(data).hexdigest())
                           for name, data in sorted(files.items())]
            return dict(failure_class='no-progress', source_attempt=path.name, source_ownership_sha256=digest,
                        status_sha256=status_hash, outputs=outputs, completion=completion)
        _require(report['state'] == ('finished' if incomplete else 'fetched'),
                 'Remedy requires confirmed completion and fetched outputs')
        completion, status_hash = _completion(path, manifest, report)
        if incomplete:
            files, outputs, reference = _incomplete_remedy_outputs(path, manifest, record, completion)
            completion['incomplete_fetch'] = reference
        else:
            files = _fetched_outputs(path, manifest)
            outputs = [dict(name=name, size=len(data), sha256=sha256(data).hexdigest())
                       for name, data in sorted(files.items())]
        if _walltime_failure(completion):
            classification = 'walltime'
        elif manifest['template'] in ('gaussian', 'gaussian-cp'):
            from ag._parse_outputs import gaussian_job_sections, gaussian_section_text, termination
            from ag.remote import output_names
            log_name = output_names(manifest)[0]
            if incomplete and log_name not in files:
                _require(completion['exit_code'] != 0 or completion['exit_signal'] != 0,
                         'Missing Gaussian log does not prove program failure')
                classification = 'program-exit'
                return dict(failure_class=classification, source_attempt=path.name, source_ownership_sha256=digest,
                    status_sha256=status_hash, outputs=outputs, completion=completion)
            text = files[log_name].decode('utf-8', errors='replace')
            sections, warnings = gaussian_job_sections(text)
            _require(not warnings, 'Latest Gaussian job has ambiguous sections')
            if all(section['termination'] == 'normal' for section in sections):
                _require(not incomplete, 'Incomplete normally terminated Gaussian result is not a remedy source')
                completion['scientific_review'] = _read_scientific_review(path, record, digest, verified_state, manifest)
                classification = 'gaussian-ts-curvature'
            else:
                if incomplete and sections[-1]['termination'] != 'error':
                    _require(completion['exit_code'] != 0 or completion['exit_signal'] != 0,
                             'Incomplete Gaussian log does not prove program failure')
                    return dict(failure_class='program-exit', source_attempt=path.name, source_ownership_sha256=digest,
                        status_sha256=status_hash, outputs=outputs, completion=completion)
                _require(sections[-1]['termination'] == 'error', 'Latest Gaussian job is not a verified failed section')
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
            _require(code != 0 or signal != 0, 'Successful program exit is not a remedy source')
            classification = 'program-exit'
    return dict(failure_class=classification, source_attempt=path.name, source_ownership_sha256=digest,
                status_sha256=status_hash, outputs=outputs, completion=completion)


def read_reservations(cfg, *, states=None, prepared_stops=None):
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
    from ag.config import cluster_identity
    grouped = {}
    for name, identity in identities.items():
        explicit = cluster_identity(entries[name])
        _require(identity not in grouped or grouped[identity] == explicit,
                 'Equivalent accounts use unmerged cluster identities; use one verified SSH identity')
        grouped[identity] = explicit
    placements, batch_inputs = [], {}
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
        placement_state = _placement_state(path, manifest, report,
                                           current=current_states.get(str(path.parent.parent)),
                                           prepared_stops=prepared_stops)
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
                report = audit(target)  # Autonomous summaries with no record fail here.
                if report['classification'] == 'unconsumed':
                    continue
                raw, manifest = _manifest_bytes(target)
                _require(root == Path(cfg['local']['studies_root']).absolute(),
                         'Unmapped historical manual reservation requires reconciliation')
                cluster = manifest.get('cluster', 'default')
                _require(cluster in entries, 'Manual reservation cluster is not configured')
                raw_job = submission.raw_job(manifest, report['job_id']) if report['job_id'] else None
                placement_state = _placement_state(target, manifest, report)
                placements.append(dict(study_id=manifest['study_id'], study_key=study_identity(path)['study_key'], attempt_id=name, cluster=cluster,
                    scheduler_job_name=manifest['attempt_id'] if manifest.get('scheduler') == 'slurm' else manifest['pbs_job_name'],
                    state=placement_state, cores=manifest['cores'], mem_gb=manifest['mem_gb'], job_id=raw_job,
                    manifest_sha256=sha256(raw).hexdigest(), record_sha256=approval.digest(report['evidence_sha256']),
                    target_node=manifest.get('node_target', {}).get('name'), round_id=None, run_id=None))
    return dict(records=records, placements=placements, batch_inputs=batch_inputs)


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


def verified_reservation(path, *, verified_state):
    """Read consumed immutable ownership; this result grants no action permit.

    The caller supplies its freshly replayed state while holding the study
    mutex. No present-day observation is added to the original reservation.
    """
    path = Path(path).absolute()
    record, digest = _scientific_reservation(path)
    _check_consumption(record, digest, verified_state)
    _owned_audit(path, record, digest)
    return dict(record=deepcopy(record), sha256=digest)


def bound_scheduler_cluster(path):
    """Read the original autonomous query target; never repair old bindings.

    Call outside publication guards: authorization verification loads the study
    state itself. A missing or downgraded probe cannot select a default target.
    """
    path = Path(path).absolute()
    side_exists = os.path.lexists(path / 'slurm-origin-probe.json')
    global_path = Path.home() / '.config/ag/autonomy-reservations' / _filename(path)
    summary_path = path / 'submission-summary.json'
    if not side_exists and not os.path.lexists(global_path) and not os.path.lexists(summary_path):
        return None
    archived = _json(_read_file(summary_path))
    auth = archived.get('authorization') if isinstance(archived, dict) else None
    autonomous = isinstance(auth, dict) and auth.get('method') == 'autonomy-policy'
    if not side_exists and not os.path.lexists(global_path) and not autonomous:
        return None
    _require(autonomous, 'Slurm query target requires archived autonomous ownership')
    record, digest = _scientific_reservation(path)
    _require(auth == authorization(record, digest), 'Slurm query target ownership differs from reservation')
    if not side_exists and 'slurm_probe' not in record:
        return None
    verified_authorization(path, auth)
    probe = record.get('slurm_probe', {}).get('record', {})
    if probe.get('bound_submit_format_candidate') is not True:
        return None
    target = probe['scheduler_cluster']
    _require(isinstance(target, str) and bool(target), 'Bound Slurm query target is missing')
    if os.path.lexists(path / 'submission.json'):
        binding = _json(_read_file(path / 'submission.json'))
        actual = binding.get('scheduler_cluster')
        _require(actual is None or actual == target,
                 'Known scheduler cluster differs from the original bound target')
    return target


def verified_authorization(path, value, *, verified_state=None):
    """Recover only authorization already bound before scheduler dispatch.

    This does not authorize a new submission, repair a record or consume again.
    It deliberately avoids submission.verified_job to keep recovery acyclic.
    """
    path = Path(path).absolute()
    with _registry('autonomy-reservations') as store:
        raw = store.read(_filename(path))
    record = _json(raw)
    _reservation_fields(record, _RECORD_KEYS, 'reservation record')
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
