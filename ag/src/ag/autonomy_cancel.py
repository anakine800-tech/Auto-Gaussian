"""Local cancellation-evidence checks; no cancellation or reroute permission.

T186 ownership and T185 routing are not integrated yet. Formal log captures
can be reviewed here without inventing either interface or accepting a model
supplied boolean as provenance. Scientific no-progress judgments remain the
reviewer's responsibility; these checks establish which bytes were reviewed.
"""
from datetime import datetime
from hashlib import sha256
import os
from pathlib import Path
import re
import sys

from ag import autonomy, remote, snapshot, state, study, submission
from ag import _autonomy_store as disk
from ag.config import cluster_name


def _checkpoint_free_route(route, multiplicity):
    """Positive syntax proof, not a blacklist of known checkpoint readers.

    Unknown options (including abbreviated readers and IOp) cannot establish
    absence of a dependency. This only narrows automatic reroute eligibility;
    prepare and scientific method selection keep their existing behavior.
    """
    from ag._profile_sources import protocol
    compact = re.sub(r'\s*([=,/])\s*', r'\1', route.lower())
    compact = re.sub(r'\(\s*', '(', compact)
    compact = re.sub(r'\s*\)', ')', compact)
    method = protocol(compact, multiplicity)
    if not re.fullmatch(
            r'(?:sto-[36]g|[346]-[23]11?\+{0,2}g(?:\*{1,2}|\([0-9dpf,]+\))?'
            r'|def2(?:svp|svpd|tzvp|tzvpp|tzvpd|tzvppd|qzvp|qzvpp|qzvpd|qzvppd)'
            r'|(?:aug-)?cc-pv[dtq]z)', method['basis']):
        raise ValueError('Unknown basis syntax cannot prove absence of a checkpoint dependency')
    body = re.sub(r'^#[pnt]?\s*', '', compact)
    matches = list(re.finditer(r'(?:[^()\s]+|\([^()]*\))+', body))
    end = 0
    tokens = []
    for match in matches:
        if body[end:match.start()].strip():
            raise ValueError('Unrecognized Gaussian route syntax')
        tokens.append(match[0])
        end = match.end()
    if body[end:].strip() or sum('/' in token for token in tokens) != 1:
        raise ValueError('Unrecognized Gaussian route syntax')
    bare = {'sp', 'opt', 'freq', 'nosymm', 'nosymmetry', '5d', '6d', '7f', '10f'}
    options = {
        'opt': {'ts', 'qst2', 'qst3', 'tight', 'verytight', 'calcfc', 'calcall',
                'noeigentest', 'cartesian', 'modredundant'},
        'freq': {'noraman', 'raman', 'hpmodes'},
        'scf': {'tight', 'verytight', 'xqc', 'qc', 'novaracc', 'fermi', 'diis', 'nodiis'},
        'int': {'ultrafine', 'superfinegrid', 'finegrid', 'sg1grid'},
        'empiricaldispersion': {'gd2', 'gd3', 'gd3bj'},
    }
    numeric = {'opt': r'(?:maxcycles|maxstep)=[1-9][0-9]*',
               'scf': r'(?:maxcycle|maxcycles|conver)=[1-9][0-9]*'}
    seen = set()
    for token in tokens:
        if '/' in token:
            continue  # protocol() already requires one recognized method/basis.
        if token in bare:
            key = token
        else:
            match = re.fullmatch(r'([a-z]+)(?:=([^()]+)|=?\(([^()]+)\))', token)
            if not match:
                raise ValueError('Unknown Gaussian option cannot prove checkpoint independence')
            key = {'integral': 'int', 'em': 'empiricaldispersion'}.get(match[1], match[1])
            values = (match[2] or match[3]).split(',')
            if key == 'scrf':
                # protocol() extracts a comparison label; it is not a complete
                # lexer and may retain whitespace inside a solvent value.
                models = {'smd', 'pcm', 'iefpcm', 'cpcm', 'dipole', 'ipcm', 'scipcm'}
                solvents = {'water', 'methanol', 'ethanol', 'acetone', 'acetonitrile',
                            'benzene', 'toluene', 'dichloromethane', 'chloroform',
                            'tetrahydrofuran', 'dimethylsulfoxide', 'diethylether',
                            'n-hexane', 'cyclohexane'}
                if (len(values) != 2 or sum(value in models for value in values) != 1
                        or sum(value in {'solvent=' + s for s in solvents} for value in values) != 1):
                    raise ValueError('Unrecognized SCRF options')
            elif key == 'counterpoise' and values == ['2']:
                pass
            elif key not in options or any(
                    value not in options[key] and not re.fullmatch(numeric.get(key, r'(?!)'), value)
                    for value in values):
                raise ValueError('Unknown or checkpoint-reading Gaussian option; reroute refused')
        if key in seen:
            raise ValueError('Duplicate Gaussian option cannot prove checkpoint independence')
        seen.add(key)


def _verify_input_records(records, declared):
    """Compare frozen file records by unique name, preserving strict fields."""
    if not isinstance(declared, list):
        raise ValueError('Input manifest records must be a list')
    expected = {}
    for item in declared:
        if (not isinstance(item, dict) or set(item) != {'name', 'sha256', 'size'}
                or not isinstance(item['name'], str) or item['name'] in expected
                or type(item['size']) is not int or item['size'] < 0):
            raise ValueError('Invalid or duplicate input manifest record')
        _hash(item['sha256'])
        expected[remote.filename(item['name'])] = item
    if {item['name']: item for item in records} != expected:
        raise ValueError('Frozen input records differ from manifest')


def checkpoint_free_input(path):
    """Verify the frozen bundle and prove a supported input has no chk reader.

    This is local evidence only. Ownership, routing, never-started, termination,
    resource changes and submission authorization remain separate checks.
    """
    from ag import attempt, crest_input, gaussian_input, render
    path = Path(path)
    binding = bound_attempt(path)
    manifest = disk.decode(read_bytes(path / 'manifest.json'))
    if 'parent_chk' in manifest or 'input_validation' in manifest:
        raise ValueError('Parent checkpoint or relaxed/unknown input validation prevents automatic reroute')
    template = manifest['template']
    if template not in ('gaussian', 'gaussian-cp', 'xtb', 'crest'):
        raise ValueError('Template has no supported checkpoint-independence proof')
    files = _input_files(path / 'inputs')
    if 'input-validation.json' in files:
        raise ValueError('Relaxed input sidecar prevents automatic reroute')
    records, bundle_sha = attempt.bundle(files)
    _verify_input_records(records, manifest.get('inputs'))
    if bundle_sha != manifest['bundle_sha256']:
        raise ValueError('Frozen input bundle hash mismatch')
    script = 'job.slurm' if binding['scheduler'] == 'slurm' else 'job.pbs'
    if script not in files:
        raise ValueError('Missing frozen program script')
    names = set(files) - {script}
    params = manifest['template_params']
    render.parameters(template, params)
    fragment = manifest['science'].get('counterpoise', {}).get('file') if template == 'gaussian-cp' else None
    constraint = {'xtb': '--input', 'crest': '--cinp'}.get(template)
    constrained = constraint and params.get(constraint) == 'constraints.inp'
    if fragment:
        names.discard(fragment)
    if constrained:
        names.discard('constraints.inp')
    if len(names) != 1:
        raise ValueError('Unknown input attachments prevent checkpoint-independence proof')
    name = next(iter(names))
    data = files[name]
    text = data.decode('utf-8')
    if re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', text):
        raise ValueError('Control characters prevent strict input interpretation')
    resource = {key: manifest[key] for key in ('cores', 'mem_gb')}
    if template in ('gaussian', 'gaussian-cp'):
        if Path(name).suffix.lower() != '.gjf':
            raise ValueError('Expected strict Gaussian input')
        if template == 'gaussian-cp':
            if fragment != name + '.fragments.csv' or fragment not in files:
                raise ValueError('Missing or invalid counterpoise fragment binding')
            _, science = gaussian_input.counterpoise_input(text, files[fragment], **resource, prepared=True)
            science['counterpoise']['file'] = fragment
        else:
            science = gaussian_input.validate(text, **resource, parent_chk=False)
        _checkpoint_free_route(science['route'], science['multiplicity'])
        if any(manifest['science'].get(key) != value for key, value in science.items()):
            raise ValueError('Frozen scientific summary differs from input bytes')
    else:
        if Path(name).suffix.lower() != '.xyz':
            raise ValueError('Expected strict XYZ input')
        frames = crest_input.xyz_ensemble(text)
        if len(frames) != 1 and not (template == 'crest' and '--mdopt' in params):
            raise ValueError('Unexpected XYZ ensemble')
        for symbols, rows in frames:
            gaussian_input.cartesian(rows, first_line=3)
            gaussian_input.check_electrons(symbols, int(params.get('--chrg', 0)),
                                           int(params.get('--uhf', 0)) + 1, location='XYZ')
        if constrained:
            crest_input.validate(files['constraints.inp'].decode('utf-8'), len(frames[0][0]),
                                 allow_scan=template == 'xtb')
    if bound_attempt(path) != binding:
        raise ValueError('Attempt binding changed during input verification')
    return dict(binding=binding, bundle_sha256=bundle_sha, input_name=name,
                input_sha256=digest(data), inputs=records, checkpoint_dependency=False,
                proof='strict_frozen_program_input', reroute_authorized=False)


def _read_capture():
    # T187's local proof tools also work before T186 is integrated. An active
    # capture belongs to the already imported T186 module; do not import its
    # ownership machinery merely to run an independent local proof.
    ownership = sys.modules.get('ag.autonomy_submission')
    context = getattr(ownership, '_CAPTURE_READS', None)
    return ownership, context.get() if context is not None else None


def read_bytes(path):
    path = Path(path)
    ownership, captured = _read_capture()
    if captured is not None:
        captured.directory(path.parent)
        data = ownership._read_file(path)
        captured.directory(path.parent)
        return data
    fd = disk.directory(path.parent)
    try:
        return disk.Store(fd).read(path.name)
    finally:
        os.close(fd)


def _input_files(path):
    _, captured = _read_capture()
    if captured is not None:
        captured.directory(path)
    fd = disk.directory(path)
    try:
        files = {remote.filename(name): (read_bytes(path / name) if captured is not None
                 else disk.Store(fd).read(name)) for name in os.listdir(fd)}
    finally:
        os.close(fd)
    if captured is not None:
        captured.directory(path)
    return files


def digest(data):
    return sha256(data).hexdigest()


def bound_attempt(path):
    """Require modern, intact exact-job binding, including for default PBS."""
    manifest_bytes = read_bytes(path / 'manifest.json')
    manifest = disk.decode(manifest_bytes)
    if (not isinstance(manifest, dict) or manifest.get('attempt_id') != path.name
            or manifest.get('study_id') != path.parent.parent.name):
        raise ValueError('Attempt/study identity mismatch')
    current = disk.decode(read_bytes(path / 'status.json'))
    if current.get('state') in ('unknown', 'submitting', 'prepared', 'failed_presubmit'):
        raise ValueError('Uncertain or unsubmitted Attempt cannot supply cancellation evidence')
    # A legacy status-only job is deliberately not sufficient here.
    record_bytes = read_bytes(path / 'submission.json')
    record = disk.decode(record_bytes)
    if not isinstance(record, dict):
        raise ValueError('Invalid submission record')
    job = submission.verified_job(path, manifest, current)
    if (manifest_bytes != read_bytes(path / 'manifest.json')
            or record_bytes != read_bytes(path / 'submission.json')):
        raise ValueError('Attempt binding changed while reading evidence')
    return dict(study_id=manifest['study_id'], attempt_id=manifest['attempt_id'],
                cluster=manifest.get('cluster', 'default'),
                scheduler=manifest.get('scheduler', 'pbs'), job_id=job,
                manifest_sha256=digest(manifest_bytes), submission_sha256=digest(record_bytes))


def capture_slurm_origin(cfg, path, transport, *, probe_sha256, ownership_sha256, publication):
    """Capture one submission-time instance, never retrofit or retry it.

    T186 owns the publication context and supplies its freshly verified raw
    state. The claim precedes all scheduler IO; a failed or interrupted capture
    cannot be replaced by a later observation of a different job instance.
    """
    from contextlib import contextmanager
    from copy import deepcopy
    from ag import attempt, status

    if not callable(publication):
        raise ValueError('Slurm origin requires the T186 publication context')
    _hash(probe_sha256)
    _hash(ownership_sha256)
    path = study.local_path(Path(cfg['local']['studies_root']), Path(path))
    parent = disk.directory(path)
    store = disk.Store(parent)

    def absent(name):
        try:
            os.stat(name, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            return
        raise ValueError('Slurm origin was already claimed or recorded; never retry')

    def sources():
        current = disk.directory(path)
        try:
            opened, actual = os.fstat(parent), os.fstat(current)
            if (opened.st_dev, opened.st_ino) != (actual.st_dev, actual.st_ino):
                raise ValueError('Attempt directory changed during Slurm origin capture')
        finally:
            os.close(current)
        binding = bound_attempt(path)
        manifest = disk.decode(store.read('manifest.json'))
        record = disk.decode(store.read('submission.json'))
        raw = store.read('slurm-origin-probe.json')
        probe = disk.decode(raw)
        if (binding['scheduler'] != 'slurm' or not isinstance(probe, dict)
                or probe.get('schema') != 'ag-slurm-submission-probe/1'
                or disk.encode(probe) != raw or digest(raw) != probe_sha256
                or type(probe.get('format_candidate')) is not bool):
            raise ValueError('Invalid original Slurm probe bytes or schema')
        expected = {key: binding[key] for key in
                    ('study_id', 'attempt_id', 'cluster', 'scheduler', 'manifest_sha256')}
        expected['bundle_sha256'] = manifest['bundle_sha256']
        if (probe.get('binding') != expected
                or record.get('scheduler_probe_sha256') != probe_sha256
                or not isinstance(record.get('authorization'), dict)
                or record['authorization'].get('ownership_sha256') != ownership_sha256):
            raise ValueError('Original probe, submission and ownership binding differ')
        cluster = probe.get('scheduler_cluster')
        if cluster is not None:
            remote.slurm_token(cluster)
            if cluster.lower() == 'all' or record.get('scheduler_cluster') != cluster:
                raise ValueError('Original probe and submission scheduler clusters differ')
        files = _input_files(path / 'inputs')
        records, bundle = attempt.bundle(files)
        _verify_input_records(records, manifest.get('inputs'))
        if bundle != expected['bundle_sha256']:
            raise ValueError('Original Slurm probe input bundle changed')
        started, finished = (autonomy.number(probe[key]) for key in ('capture_started_at', 'capture_finished_at'))
        if started > finished or bound_attempt(path) != binding:
            raise ValueError('Original Slurm probe timing or submission binding changed')
        return dict(binding=binding, probe=probe, bundle_sha256=bundle, scheduler_cluster=cluster)

    def dispatch_state(runtime, original, at):
        try:
            consumed = runtime['submissions'][path.name]
            dispatch = deepcopy({key: consumed[key] for key in
                                 ('ownership_sha256', 'round_id', 'run_id', 'plan_sha256', 'dispatch_started')})
            if (dispatch['ownership_sha256'] != ownership_sha256
                    or runtime['current_round'] != dispatch['round_id']
                    or runtime['lease']['run_id'] != dispatch['run_id']
                    or runtime['plans'][runtime['current_plan']]['sha256'] != dispatch['plan_sha256']):
                raise ValueError('Slurm origin requires the original dispatch owner, round and plan')
            _hash(dispatch['plan_sha256'])
            for key in ('round_id', 'run_id'):
                autonomy.text(dispatch[key], key)
            started = dispatch['dispatch_started']
            if not isinstance(started, dict) or set(started) != {'at'}:
                raise ValueError('Invalid original T186 dispatch-start record')
            dispatched = autonomy.number(started['at'])
            if not original['probe']['capture_finished_at'] <= dispatched <= at:
                raise ValueError('Slurm origin probe must precede the original dispatch')
            return dispatch
        except (KeyError, TypeError) as exc:
            raise ValueError('Missing original T186 dispatch consumption') from exc

    def verify(runtime):
        if sources() != original or dispatch_state(runtime, original, autonomy.now()) != dispatch:
            raise ValueError('Slurm origin sources or original dispatch changed')
        if store.read('slurm-origin-claim.json') != claim_bytes:
            raise ValueError('Slurm origin claim changed')
        absent('slurm-origin.json')

    @contextmanager
    def observation_publication():
        with publication() as runtime:
            verify(runtime)
            yield runtime

    try:
        with publication() as runtime:
            absent('slurm-origin-claim.json')
            absent('slurm-origin.json')
            original = sources()
            at = autonomy.number(autonomy.now())
            dispatch = dispatch_state(runtime, original, at)
            claim = dict(schema='ag-slurm-origin-claim/1', **original['binding'],
                         probe_sha256=probe_sha256, **dispatch, claimed_at=at)
            claim_bytes = disk.encode(claim)
            store.exclusive('slurm-origin-claim.json', claim_bytes)
        result = dict(schema='ag-slurm-origin/1', binding=original['binding'],
                      probe_sha256=probe_sha256, claim_sha256=digest(claim_bytes), **dispatch,
                      bundle_sha256=original['bundle_sha256'], scheduler_cluster=original['scheduler_cluster'],
                      status='unavailable', initial_instance_recorded=False,
                      reroute_authorized=False, live_validated=False)
        observed, capture_failure = None, None
        probe = original['probe']
        versions = probe.get('versions', {})
        candidate = (probe['format_candidate'] and original['scheduler_cluster'] is not None
                     and set(versions) == {'controller', 'scontrol', 'sacct'}
                     and all(isinstance(value, dict) and value.get('parsed') == '26.05.5'
                             for value in versions.values()))
        if not candidate:
            result['reason'] = 'Original probe has no supported evidence format or actual scheduler cluster'
        else:
            try:
                observed = status.capture_slurm_evidence(cfg, path, transport, publication=observation_publication)
            except Exception as exc:
                observed = getattr(exc, 'evidence', None)
                if observed is None:
                    raise
                capture_failure = exc
                result.update(error_type=observed.get('error_type', type(exc).__name__),
                              reason=observed.get('error', str(exc)))
        with publication() as runtime:
            verify(runtime)
            if observed is not None:
                reference = observed['observation']
                if not re.fullmatch(r'scheduler-observations/\d{8}T\d{12}Z', reference):
                    raise ValueError('Invalid freshly captured Slurm observation reference')
                raw = read_bytes(path / reference / 'observation.json')
                saved = disk.decode(raw)
                if (disk.encode(saved) != raw or digest(raw) != observed['observation_sha256']
                        or saved != {k: v for k, v in observed.items() if k != 'observation_sha256'}
                        or saved.get('schema') != 'ag-slurm-observation/1'
                        or saved['binding'] != original['binding']
                        or saved.get('scheduler_cluster') != original['scheduler_cluster']):
                    raise ValueError('Fresh Slurm observation binding or bytes changed')
                if autonomy.number(saved['capture_started_at']) < claim['claimed_at']:
                    raise ValueError('Clock moved backwards between origin claim and observation')
                for query in saved['queries']:
                    for stream in ('stdout', 'stderr'):
                        if stream in query:
                            item = query[stream]
                            data = read_bytes(path / reference / remote.filename(item['file']))
                            if digest(data) != item['sha256'] or len(data) != item['size']:
                                raise ValueError('Fresh Slurm observation response changed')
                result.update(observation=reference, observation_sha256=observed['observation_sha256'])
                if saved['complete'] is True:
                    job = saved['controller']
                    matching = [row for row in saved['history'] if row['db_index'] == saved['matched_db_index']]
                    if (len(matching) == 1 and job['restarts'] == matching[0]['restarts'] == 0
                            and matching[0]['original_sluid'] is not None
                            and matching[0]['original_sluid'] == job['sluid'] == matching[0]['sluid']):
                        result.update(status='recorded', initial_instance_recorded=True,
                                      instance=dict(job, db_index=matching[0]['db_index'],
                                                    original_sluid=matching[0]['original_sluid']),
                                      reason='Initial instance recorded; live validation and reroute authorization are absent')
                    else:
                        result['reason'] = 'Current instance has restarted or lacks a matching original SLUID'
                else:
                    result.setdefault('reason', saved.get('error', 'Initial scheduler observation is incomplete'))
            result['recorded_at'] = autonomy.number(autonomy.now())
            data = disk.encode(result)
            store.exclusive('slurm-origin.json', data)
        if capture_failure is not None:
            capture_failure.origin_evidence = dict(origin='slurm-origin.json', origin_sha256=digest(data),
                                                  record=result)
            raise capture_failure
        return dict(result, origin_sha256=digest(data))
    finally:
        os.close(parent)


def _canonical_slurm_record(path):
    raw = read_bytes(path)
    value = disk.decode(raw)
    if not isinstance(value, dict) or disk.encode(value) != raw:
        raise ValueError('Slurm evidence must retain its canonical original bytes')
    return value, digest(raw)


def _slurm_runtime(text):
    """Read the unique fixed-prefix RunTime, after strict job parsing."""
    values = re.findall(r'(?:^|[ \t])RunTime=([^\s=]+)', text)
    if len(values) != 1:
        raise ValueError('Missing or ambiguous Slurm RunTime evidence')
    match = re.fullmatch(r'(?:(\d+)-)?(\d{2}):([0-5]\d):([0-5]\d)', values[0])
    if match is None or int(match[2]) >= 24:
        raise ValueError('Unrecognized Slurm RunTime evidence')
    return ((int(match[1] or 0) * 24 + int(match[2])) * 60 + int(match[3])) * 60 + int(match[4])


def _slurm_observation(path, reference, expected_sha, binding, cluster, *, cancel_version):
    """Reparse one fixed capture from its original response files."""
    from ag import slurm
    _hash(expected_sha)
    if not isinstance(reference, str) or not re.fullmatch(r'scheduler-observations/\d{8}T\d{12}Z', reference):
        raise ValueError('Expected a formal Slurm observation reference')
    value, sha = _canonical_slurm_record(path / reference / 'observation.json')
    if (sha != expected_sha or value.get('schema') != 'ag-slurm-observation/1'
            or value.get('binding') != binding or value.get('scheduler_cluster') != cluster
            or value.get('observation') != reference or value.get('complete') is not True
            or value.get('reroute_authorized') is not False or 'error_type' in value):
        raise ValueError('Incomplete or mismatched formal Slurm observation')
    commands = [('config', remote.slurm_evidence_config()),
                ('scontrol-version', remote.slurm_evidence_version('scontrol')),
                ('sacct-version', remote.slurm_evidence_version('sacct'))]
    if cancel_version:
        commands.append(('scancel-version', remote.slurm_evidence_version('scancel')))
    commands += [('history', remote.slurm_evidence_history(binding['job_id'], cluster)),
                 ('job', remote.slurm_evidence_job(binding['job_id'], cluster))]
    if not isinstance(value.get('queries'), list) or len(value['queries']) != len(commands):
        raise ValueError('Slurm observation lacks the required fixed queries')
    texts, times = {}, []
    previous = autonomy.number(value['capture_started_at'])
    finished = autonomy.number(value['capture_finished_at'])
    for entry, (label, command) in zip(value['queries'], commands):
        if (entry.get('label') != label or entry.get('command') != command.text
                or entry.get('operation') != command.operation
                or type(entry.get('returncode')) is not int or entry['returncode'] != 0):
            raise ValueError('Slurm query command, order or outcome differs')
        start, end = autonomy.number(entry['started_at']), autonomy.number(entry['finished_at'])
        if not previous <= start <= end <= finished:
            raise ValueError('Slurm observation query times are inconsistent')
        previous = end
        times.append(dict(label=label, started_at=start, finished_at=end))
        for stream in ('stdout', 'stderr'):
            item = entry[stream]
            if (not isinstance(item, dict) or set(item) != {'file', 'sha256', 'size'}
                    or item['file'] != label + '.' + stream + '.txt'
                    or type(item['size']) is not int or item['size'] < 0):
                raise ValueError('Invalid Slurm response file record')
            data = read_bytes(path / reference / item['file'])
            if digest(data) != _hash(item['sha256']) or len(data) != item['size']:
                raise ValueError('Slurm response file hash or size changed')
            text = data.decode('utf-8')
            if stream == 'stderr' and text.strip():
                raise ValueError('Slurm observation contains diagnostics')
            if stream == 'stdout':
                texts[label] = text
    controller = slurm.parse_evidence_config(texts['config'])
    versions = dict(controller=controller['server_version'],
                    scontrol=slurm.parse_evidence_version(texts['scontrol-version']),
                    sacct=slurm.parse_evidence_version(texts['sacct-version']))
    execution = {'scancel': slurm.parse_evidence_version(texts['scancel-version'])} if cancel_version else {}
    if (controller['cluster'] != cluster or set(versions.values()) != {'26.05.5'}
            or value.get('versions') != versions or value.get('execution_versions', {}) != execution
            or cancel_version and execution['scancel'] != '26.05.5'):
        raise ValueError('Slurm observation version or cluster evidence differs')
    identity = dict(job_id=binding['job_id'], cluster=cluster, name=binding['attempt_id'])
    history = slurm.parse_evidence_history(texts['history'], **identity)
    job = slurm.parse_evidence_job(texts['job'], **identity)
    matched = [row for row in history if row['sluid'] == job['sluid']]
    if (len(matched) != 1 or any(row['uid'] != job['uid'] for row in history)
            or any(matched[0][key] != job[key] for key in ('submit', 'restarts', 'state'))
            or value.get('controller') != job or value.get('history') != history
            or value.get('matched_db_index') != matched[0]['db_index']):
        raise ValueError('Slurm parsed instance differs from its original response evidence')
    if any(datetime.fromisoformat(row['submit']).timestamp() > finished for row in [job, *history]):
        raise ValueError('Slurm submit time is in the future')
    instance = dict(job, db_index=matched[0]['db_index'], original_sluid=matched[0]['original_sluid'])
    metadata = dict(observation=reference, observation_sha256=sha,
                    capture_started_at=value['capture_started_at'], capture_finished_at=finished, queries=times,
                    runtime_seconds=_slurm_runtime(texts['job']))
    return instance, history, metadata


def verify_slurm_instance(path, *, ownership_sha256, observation):
    """Reverify immutable origin and a fresh capture; no execution permission."""
    from ag import attempt, slurm
    path = Path(path)
    _hash(ownership_sha256)
    if not isinstance(observation, dict):
        raise ValueError('Expected a freshly captured observation reference and hash')
    binding = bound_attempt(path)
    manifest = disk.decode(read_bytes(path / 'manifest.json'))
    submitted = disk.decode(read_bytes(path / 'submission.json'))
    probe, probe_sha = _canonical_slurm_record(path / 'slurm-origin-probe.json')
    claim, claim_sha = _canonical_slurm_record(path / 'slurm-origin-claim.json')
    origin, origin_sha = _canonical_slurm_record(path / 'slurm-origin.json')
    cluster = submitted.get('scheduler_cluster')
    remote.slurm_token(cluster)
    if cluster.lower() == 'all' or binding['scheduler'] != 'slurm':
        raise ValueError('Slurm instance requires one actual bound scheduler cluster')
    expected = {key: binding[key] for key in ('attempt_id', 'study_id', 'cluster', 'scheduler', 'manifest_sha256')}
    expected['bundle_sha256'] = manifest['bundle_sha256']
    if (probe.get('schema') != 'ag-slurm-submission-probe/1' or probe.get('binding') != expected
            or probe.get('scheduler_cluster') != cluster or probe.get('format_candidate') is not True
            or submitted.get('scheduler_probe_sha256') != probe_sha
            or submitted.get('authorization', {}).get('ownership_sha256') != ownership_sha256
            or origin.get('schema') != 'ag-slurm-origin/1' or origin.get('binding') != binding
            or origin.get('status') != 'recorded' or origin.get('initial_instance_recorded') is not True
            or origin.get('ownership_sha256') != ownership_sha256 or origin.get('probe_sha256') != probe_sha
            or origin.get('claim_sha256') != claim_sha or origin.get('scheduler_cluster') != cluster
            or origin.get('bundle_sha256') != manifest['bundle_sha256']
            or claim.get('schema') != 'ag-slurm-origin-claim/1'
            or any(claim.get(key) != value for key, value in binding.items())
            or claim.get('probe_sha256') != probe_sha):
        raise ValueError('Immutable Slurm origin, submission, probe or ownership binding differs')
    for key in ('ownership_sha256', 'round_id', 'run_id', 'plan_sha256', 'dispatch_started'):
        if claim.get(key) != origin.get(key):
            raise ValueError('Original Slurm dispatch claim differs from its origin')
    _hash(claim['plan_sha256'])
    for key in ('round_id', 'run_id'):
        autonomy.text(claim[key], key)
    if not isinstance(claim.get('dispatch_started'), dict) or set(claim['dispatch_started']) != {'at'}:
        raise ValueError('Invalid original Slurm dispatch timestamp')
    files = _input_files(path / 'inputs')
    records, bundle = attempt.bundle(files)
    _verify_input_records(records, manifest.get('inputs'))
    if bundle != manifest['bundle_sha256']:
        raise ValueError('Slurm origin input bundle changed')
    commands = [('config', remote.slurm_evidence_config())] + [
        (program + '-version', remote.slurm_evidence_version(program))
        for program in ('scontrol', 'sacct', 'sbatch', 'scancel')]
    if not isinstance(probe.get('queries'), list) or len(probe['queries']) != len(commands):
        raise ValueError('Original Slurm probe lacks execution version evidence')
    previous = autonomy.number(probe['capture_started_at'])
    texts = {}
    for entry, (label, command) in zip(probe['queries'], commands):
        if (entry.get('label') != label or entry.get('command') != command.text
                or entry.get('operation') != command.operation or type(entry.get('returncode')) is not int):
            raise ValueError('Original Slurm probe query binding differs')
        start, end = autonomy.number(entry['started_at']), autonomy.number(entry['finished_at'])
        if not previous <= start <= end <= autonomy.number(probe['capture_finished_at']):
            raise ValueError('Original Slurm probe query timing differs')
        previous = end
        for stream in ('stdout', 'stderr'):
            if not isinstance(entry.get(stream), str) or digest(entry[stream].encode()) != _hash(entry[stream + '_sha256']):
                raise ValueError('Original Slurm probe response hash differs')
        texts[label] = entry['stdout']
        if entry['returncode'] or entry['stderr'].strip():
            # Only sbatch may be unavailable without weakening this cancellation
            # format proof; it is not one of the cancellation command's readers.
            diagnostic = entry['stderr'].strip()
            missing = ('env: sbatch: No such file or directory', "env: 'sbatch': No such file or directory",
                       'env: "sbatch": No such file or directory', 'sbatch: command not found', 'sbatch: not found')
            option = "sbatch: unrecognized option '--version'"
            unsupported = (entry['returncode'] == 127 and diagnostic in missing
                           or entry['returncode'] == 1 and diagnostic in
                           (option, option + '\nTry "sbatch --help" for more information'))
            if label != 'sbatch-version' or entry['stdout'].strip() or not unsupported:
                raise ValueError('Original Slurm probe query failed or contains diagnostics')
    controller = slurm.parse_evidence_config(texts['config'])
    versions = dict(controller=dict(raw=controller['server_version'], parsed=controller['server_version']))
    execution = {}
    for program in ('scontrol', 'sacct', 'sbatch', 'scancel'):
        raw = texts[program + '-version']
        try:
            parsed = slurm.parse_evidence_version(raw)
        except ValueError:
            if program != 'sbatch':
                raise
            parsed = None
        (versions if program in ('scontrol', 'sacct') else execution)[program] = dict(raw=raw, parsed=parsed)
    if (controller['cluster'] != cluster or probe.get('versions') != versions
            or set(value['parsed'] for value in versions.values()) != {'26.05.5'}
            or probe.get('execution_versions') != execution or execution['scancel']['parsed'] != '26.05.5'):
        raise ValueError('Original Slurm execution versions cannot support instance cancellation')
    initial, initial_history, initial_meta = _slurm_observation(
        path, origin['observation'], origin['observation_sha256'], binding, cluster, cancel_version=False)
    current, current_history, current_meta = _slurm_observation(
        path, observation['observation'], observation['observation_sha256'], binding, cluster, cancel_version=True)
    if origin.get('instance') != initial or initial['restarts'] != 0 or initial['original_sluid'] != initial['sluid']:
        raise ValueError('Original Slurm instance differs from its recorded raw evidence')
    keys = ('cluster', 'job_id', 'name', 'uid', 'submit', 'sluid', 'db_index', 'restarts', 'original_sluid')
    if any(current[key] != initial[key] for key in keys):
        raise ValueError('Slurm current instance was restarted, replaced or reused')
    if not (autonomy.number(probe['capture_finished_at']) <= autonomy.number(claim['dispatch_started']['at'])
            <= autonomy.number(claim['claimed_at']) <= initial_meta['capture_started_at']
            <= initial_meta['capture_finished_at'] <= autonomy.number(origin['recorded_at'])
            <= current_meta['capture_started_at'] <= current_meta['capture_finished_at'] <= autonomy.now()
            and initial_meta['capture_finished_at'] < current_meta['capture_started_at']):
        raise ValueError('Slurm initial and current observation timing is inconsistent')
    if bound_attempt(path) != binding:
        raise ValueError('Attempt binding changed during Slurm instance verification')
    return dict(binding=binding, ownership_sha256=ownership_sha256, probe_sha256=probe_sha,
                claim_sha256=claim_sha, origin_sha256=origin_sha,
                origin_dispatch={key: claim[key] for key in
                                 ('ownership_sha256', 'round_id', 'run_id', 'plan_sha256', 'dispatch_started')},
                initial_instance=initial, current_instance=current,
                initial_history=initial_history, current_history=current_history,
                initial_observation=initial_meta, current_observation=current_meta,
                probe_execution_versions=execution, cancellation_authorized=False,
                reroute_authorized=False, live_validated=False)


def review_reroute_queue(path, *, ownership_sha256, observation, now=None):
    """Review frozen pending evidence and inputs, without choosing a route."""
    path = Path(path)
    instance = verify_slurm_instance(path, ownership_sha256=ownership_sha256, observation=observation)
    rows = [instance['initial_instance'], instance['current_instance'],
            *instance['initial_history'], *instance['current_history']]
    identity = instance['initial_instance']
    keys = ('cluster', 'job_id', 'name', 'uid', 'submit', 'sluid', 'db_index', 'original_sluid')
    if any(row['state'] != 'PENDING'
           or row['restarts'] != 0 or any(row[key] != identity[key] for key in keys) for row in rows):
        raise ValueError('Reroute requires the same never-started pending instance in all formal evidence')
    if any(row['start'] is not None or row['end'] is not None
           for row in [*instance['initial_history'], *instance['current_history']]):
        raise ValueError('Reroute history contains a start/end time; never-started evidence is absent')
    predicted, predicted_end = {}, {}
    for phase in ('initial', 'current'):
        start = instance[phase + '_instance']['start']
        end = instance[phase + '_instance']['end']
        queried = instance[phase + '_observation']['queries'][-1]['started_at']
        if start is not None and datetime.fromisoformat(start).timestamp() < int(queried):
            raise ValueError('Pending controller has a past start time; never-started evidence is absent')
        if end is not None and (start is None or datetime.fromisoformat(end) < datetime.fromisoformat(start)):
            raise ValueError('Pending controller has an inconsistent predicted end time')
        # A pending controller can expose its planned start. Accounting must
        # still have no actual times. pack_job uses MAX(expected, server now)
        # and prints seconds, so the query's current second can be expected.
        predicted[phase], predicted_end[phase] = start, end
    if any(instance[key]['runtime_seconds'] != 0 for key in ('initial_observation', 'current_observation')):
        raise ValueError('Reroute observation contains positive running time')
    finished = instance['current_observation']['capture_finished_at']
    evaluated = finished if now is None else autonomy.number(now)
    if not finished <= evaluated <= autonomy.now():
        raise ValueError('Reroute review clock predates its observation or lies in the future')
    submitted = autonomy.number(datetime.fromisoformat(identity['submit']).timestamp())
    queued = evaluated - submitted
    if queued < 6 * 60 * 60:
        raise ValueError('Reroute requires at least six hours of observed queue time')
    checkpoint = checkpoint_free_input(path)
    if checkpoint['binding'] != instance['binding']:
        raise ValueError('Reroute input and scheduler evidence bindings differ')
    return dict(binding=instance['binding'], ownership_sha256=ownership_sha256,
                slurm_instance=instance, checkpoint_free_input=checkpoint,
                evaluated_at=evaluated, queued_seconds=queued, never_started_observed=True,
                predicted_start_times=predicted, predicted_end_times=predicted_end,
                reroute_authorized=False, live_validated=False)


def verify_slurm_stopped(path, *, ownership_sha256, observation, cancel_response):
    """Verify an accepted cancellation and a later terminal same-instance read.

    The caller must separately bind the returned consumption hash to the live
    ownership ledger. This local proof neither authorizes a replacement nor
    claims atomic protection against a query-to-cancel start race.
    """
    path = Path(path)
    response_name, request_name = 'autonomy-cancel-response.json', 'autonomy-cancel-request.json'
    if (not isinstance(cancel_response, dict) or cancel_response.get('response') != response_name):
        raise ValueError('Expected the fixed cancellation response reference and hash')
    response, response_sha = _canonical_slurm_record(path / response_name)
    if (response_sha != _hash(cancel_response.get('response_sha256'))
            or response.get('schema') != 'ag-autonomy-cancel-response/1'
            or response.get('outcome') != 'accepted' or response.get('dispatched') is not True
            or type(response.get('returncode')) is not int or response['returncode'] != 0
            or response.get('exception') is not None or response.get('stopped') is not False):
        raise ValueError('Cancellation response does not prove a dispatched accepted command')
    for stream in ('stdout', 'stderr'):
        if (not isinstance(response.get(stream), str)
                or digest(response[stream].encode()) != _hash(response.get(stream + '_sha256'))):
            raise ValueError('Cancellation response stream hash differs')
    if response['stderr'].strip():
        raise ValueError('Cancellation diagnostics leave the result uncertain')
    consumed = _hash(response.get('consumption_sha256'))
    request, request_sha = _canonical_slurm_record(path / request_name)
    current = verify_slurm_instance(path, ownership_sha256=ownership_sha256, observation=observation)
    binding, kind = current['binding'], request.get('kind')
    if (request_sha != _hash(response.get('request_sha256'))
            or request.get('schema') != 'ag-autonomy-cancel-request/1'
            or request.get('binding') != binding or request.get('ownership_sha256') != ownership_sha256
            or kind not in ('no_progress', 'reroute')
            or request.get('round_id') != current['origin_dispatch']['round_id']
            or request.get('plan_sha256') != current['origin_dispatch']['plan_sha256']):
        raise ValueError('Cancellation request differs from the owned instance and original dispatch')
    _hash(request.get('rule_sha256'))
    for key in ('run_id', 'policy_name'):
        study.identifier(request.get(key))
    autonomy.text(request.get('reason'), 'Cancellation reason')
    job = current['current_instance']
    target = dict(scheduler_cluster=job['cluster'], uid=job['uid'], job_name=job['name'],
                  sluid=job['sluid'], purpose=kind)
    command = remote.slurm_cancel_instance(**target)
    if (request.get('target') != target or request.get('command') != command.text
            or request.get('operation') != command.operation or request.get('timeout') != command.timeout):
        raise ValueError('Cancellation command does not target the exact recorded instance')
    if read_bytes(path / '.cancel-claim') != b'Claimed permanently; never retry this exact cancellation.\n':
        raise ValueError('Cancellation lacks its original non-reusable dispatch claim')
    saved_instance = request.get('slurm_instance')
    if not isinstance(saved_instance, dict):
        raise ValueError('Cancellation request lacks its pre-cancel observation')
    before = verify_slurm_instance(path, ownership_sha256=ownership_sha256,
                                   observation=saved_instance.get('current_observation'))
    if before != saved_instance:
        raise ValueError('Cancellation request instance differs from the re-read original evidence')
    started, finished = autonomy.number(response.get('started_at')), autonomy.number(response.get('finished_at'))
    if not (before['current_observation']['capture_finished_at'] <= autonomy.number(request.get('recorded_at'))
            <= started <= finished < current['current_observation']['capture_started_at']):
        raise ValueError('Stop observation must begin after the accepted cancellation finished')
    rows = [job, *current['current_history']]
    identity = current['initial_instance']
    keys = ('cluster', 'job_id', 'name', 'uid', 'submit', 'sluid', 'db_index', 'original_sluid', 'restarts')
    for row in rows:
        if row['state'] != 'CANCELLED' or any(row[key] != identity[key] for key in keys):
            raise ValueError('Stop evidence requires only the same CANCELLED instance, without active or reused history')
        submitted = autonomy.number(datetime.fromisoformat(row['submit']).timestamp())
        end = None if row['end'] is None else autonomy.number(datetime.fromisoformat(row['end']).timestamp())
        start = None if row['start'] is None else autonomy.number(datetime.fromisoformat(row['start']).timestamp())
        if (end is None or not submitted <= end <= current['current_observation']['capture_finished_at']
                or start is not None and not submitted <= start <= end):
            raise ValueError('Cancelled instance lacks a consistent terminal end time')
        # Slurm prints these timestamps to seconds. A previously active read
        # and a terminal end in the same second are possible; an earlier
        # second conflicts with that read rather than describing this stop.
        if end < int(before['current_observation']['queries'][-1]['started_at']):
            raise ValueError('Terminal end time precedes the pre-cancel active observation')
    if any(row['start'] != job['start'] or row['end'] != job['end'] for row in current['current_history']):
        raise ValueError('Controller and accounting terminal times disagree')
    queue = None
    if kind == 'reroute':
        queue = request.get('reroute_queue')
        if not isinstance(queue, dict):
            raise ValueError('Reroute cancellation lacks its complete pre-cancel queue review')
        verified_queue = review_reroute_queue(path, ownership_sha256=ownership_sha256,
            observation=before['current_observation'], now=queue.get('evaluated_at'))
        if (verified_queue != queue or queue['slurm_instance'] != before
                or queue['evaluated_at'] > autonomy.number(request['recorded_at'])):
            raise ValueError('Pre-cancel queue review differs from the re-read immutable evidence')
        if (current['current_observation']['runtime_seconds'] > 0
                or any(row['start'] is not None and row['start'] != row['end'] for row in rows)):
            raise ValueError('Post-cancel evidence records execution; reroute refused')
    elif before['current_instance']['state'] not in ('RUNNING', 'SUSPENDED'):
        raise ValueError('No-progress cancellation lacks a running pre-cancel instance')
    manifest = disk.decode(read_bytes(path / 'manifest.json'))
    if bound_attempt(path) != binding:
        raise ValueError('Attempt binding changed during stop verification')
    return dict(stopped=True, kind=kind, binding=binding, ownership_sha256=ownership_sha256,
                request=request_name, request_sha256=request_sha, response=response_name,
                response_sha256=response_sha, consumption_sha256=consumed,
                slurm_instance=current, pre_cancel_observation=before['current_observation'],
                reroute_queue=queue, input_binding=dict(manifest_sha256=binding['manifest_sha256'],
                    bundle_sha256=manifest['bundle_sha256'], inputs=manifest['inputs']),
                query_cancel_window_not_excluded=kind == 'reroute',
                precision_limitation='second-resolution timestamps cannot exclude execution between the pre-cancel query and cancellation'
                    if kind == 'reroute' else None,
                reroute_authorized=False, live_validated=False)


def _reference(value):
    if not isinstance(value, str) or not re.fullmatch(r'snapshots/\d{8}T\d{12}Z', value):
        raise ValueError('Expected a formal snapshot directory reference')
    return value


def _hash(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value):
        raise ValueError('Expected SHA-256')
    return value


def validate_observation(value, run, at):
    """Validate the replayed capture event, without reading mutable files."""
    binding = value['binding']
    if not isinstance(binding, dict) or set(binding) != {
            'study_id', 'attempt_id', 'cluster', 'scheduler', 'job_id',
            'manifest_sha256', 'submission_sha256'}:
        raise ValueError('Invalid snapshot job binding')
    for key in ('study_id', 'attempt_id'):
        study.identifier(binding[key])
    cluster_name(binding['cluster'])
    if binding['scheduler'] not in ('pbs', 'slurm'):
        raise ValueError('Invalid snapshot scheduler')
    (remote.slurm_job_id if binding['scheduler'] == 'slurm' else remote.job_id)(binding['job_id'])
    for key in ('manifest_sha256', 'submission_sha256'):
        _hash(binding[key])
    _reference(value['snapshot'])
    for key in ('snapshot_sha256', 'log_sha256', 'plan_sha256'):
        _hash(value[key])
    if type(value['capture_started_seq']) is not int:
        raise ValueError('Snapshot requires its capture-start journal position')
    before, captured, after = (autonomy.number(value[k]) for k in
                               ('capture_started_at', 'captured_at', 'capture_finished_at'))
    if not run['started_at'] <= before <= captured <= after <= at < run['started_at'] + autonomy.RUN_SECONDS:
        raise ValueError('Snapshot was not freshly captured inside this wake')


def snapshot_evidence(path, reference, binding):
    """Re-read the exact metadata and log bytes, rejecting redirects/tampering."""
    directory = path / _reference(reference)
    raw = read_bytes(directory / 'snapshot.json')
    value = disk.decode(raw)
    manifest = disk.decode(read_bytes(path / 'manifest.json'))
    if bound_attempt(path) != binding:
        raise ValueError('Snapshot Attempt binding changed')
    expected = dict(schema='ag-log-snapshot/1', attempt_id=binding['attempt_id'],
                    cluster=binding['cluster'], job_id=binding['job_id'], snapshot=reference,
                    file=remote.output_names(manifest)[0], notice=snapshot.NOTICE)
    if not isinstance(value, dict) or any(value.get(k) != v for k, v in expected.items()):
        raise ValueError('Formal snapshot identity/source mismatch')
    data = read_bytes(directory / value['file'])
    if value.get('sha256') != digest(data) or value.get('read_bytes') != len(data):
        raise ValueError('Snapshot log hash or size mismatch')
    size, limit = value['remote_size'], value['max_bytes']
    if (type(size) is not int or size < 0 or type(limit) is not int or limit < 1
            or type(value['truncated']) is not bool or value['truncated'] != (size > limit)
            or len(data) != min(size, limit)
            or value['progress'] != snapshot.progress(data, manifest['template'], truncated=value['truncated'])):
        raise ValueError('Snapshot byte/progress metadata mismatch')
    stamp = datetime.fromisoformat(value['created_at'])
    if stamp.tzinfo is None:
        raise ValueError('Snapshot time needs a timezone')
    if stamp.strftime('%Y%m%dT%H%M%S%fZ') != directory.name:
        raise ValueError('Snapshot directory/time mismatch')
    return dict(snapshot=reference, snapshot_sha256=digest(raw), log_sha256=digest(data),
                captured_at=stamp.timestamp(), latest_status=value['latest_status'])


def _uninterrupted(path, current, started_seq):
    """A pause breaks the observation pair, even if the owner later resumes.

    Compare journal positions, not timestamps: pause/resume and capture can
    share a clock tick. The chain is pinned to the snapshot held by the guard.
    """
    previous, paused, count, replayed = None, False, 0, None
    for count, line in enumerate(read_bytes(path.parent.parent / 'autonomy' / 'journal.jsonl')
                                 .splitlines(keepends=True), 1):
        event = disk.decode(line)
        if (not line.endswith(b'\n') or event['seq'] != count
                or event['prev_sha256'] != previous):
            raise ValueError('Autonomy journal changed during evidence review')
        previous = digest(line)
        replayed = autonomy.apply(replayed, event)
        if count <= started_seq:
            paused = replayed['paused']
        elif paused or replayed['paused']:
            raise ValueError('Pause interrupted the pair; need two new consecutive wake captures after resume')
    if count != current['seq'] or previous != current['journal_sha256']:
        raise ValueError('Autonomy journal changed during evidence review')


def review_no_progress(cfg, path, *, run_id, token, plan_sha256, reviews):
    """Enter the current owner guard, then verify consecutive wake evidence."""
    path = study.local_path(Path(cfg['local']['studies_root']), Path(path))
    with autonomy.action_guard(cfg, path.parent.parent.name, run_id, token,
                               action='cancel', plan_sha256=plan_sha256) as current:
        return _review_no_progress_locked(path, current=current, run_id=run_id,
                                          plan_sha256=plan_sha256, reviews=reviews)


def _review_no_progress_locked(path, *, current, run_id, plan_sha256, reviews):
    """Local evidence checks under the caller's existing action guard.

    ``current`` is that guard's public journal snapshot, including seq/hash.
    Never enter another state lock here or treat the returned evidence as a permit.
    """
    path = Path(path)
    if not isinstance(reviews, list) or len(reviews) != 2:
        raise ValueError('Review exactly two different consecutive wake snapshots')
    binding = bound_attempt(path)
    if state.read(path)['state'] not in ('running', 'stalled'):
        raise ValueError('No-progress review requires a currently running Attempt')
    runtime = current['state']
    # Replay preserves start-event ordering, including equal timestamps.
    runs = [key for key, run in runtime['runs'].items()
            if run['round_id'] == runtime['current_round']]
    if len(runs) < 2 or runs[-1] != run_id:
        raise ValueError('Need the previous wake and the current wake')
    wanted = runs[-2:]
    registered = runtime.get('snapshots', {})
    evidence = []
    for review, wake in zip(reviews, wanted):
        if not isinstance(review, dict) or set(review) != {
                'snapshot', 'snapshot_sha256', 'log_sha256', 'no_progress', 'reason'}:
            raise ValueError('Each snapshot needs its hashes and explicit scientific review reason')
        if review['no_progress'] is not True:
            raise ValueError('Both snapshots must be reviewed as showing no progress')
        autonomy.text(review['reason'], 'Scientific no-progress review reason')
        candidates = [item for item in registered.values()
                      if item['run_id'] == wake and item['binding'] == binding
                      and item['round_id'] == runtime['current_round']
                      and item['plan_sha256'] == plan_sha256]
        if not candidates:
            raise ValueError('No formal snapshot registered for the expected wake and job')
        latest = max(candidates, key=lambda item: item['seq'])
        if any(review[key] != latest[key] for key in ('snapshot', 'snapshot_sha256', 'log_sha256')):
            raise ValueError('Review must use the latest formal snapshot of each consecutive wake')
        actual = snapshot_evidence(path, review['snapshot'], binding)
        if any(actual[key] != latest[key] for key in
               ('snapshot', 'snapshot_sha256', 'log_sha256', 'captured_at')):
            raise ValueError('Registered snapshot bytes changed')
        if actual['latest_status'].get('state') not in ('running', 'stalled'):
            raise ValueError('Snapshot did not observe a locally running Attempt')
        evidence.append(dict(latest, reason=review['reason'], no_progress=True))
    _uninterrupted(path, current, evidence[0]['capture_started_seq'])
    # The guard stays held during local reads; a slow disk can still outlive
    # the lease or plan. Recheck time/version before returning the review.
    versions = autonomy.versions()
    at = autonomy.now()
    lease = runtime['lease']
    if not lease['started_at'] <= at < lease['run_until']:
        raise ValueError('Current wake expired during evidence review')
    autonomy.bound_plan(runtime, runtime['current_plan'], versions, at)
    # Return evidence only. A caller must never treat this as a cached permit.
    return dict(binding=binding, evidence=evidence, no_progress_review_verified=True,
                scientific_judgment='pending_human_confirmation',
                cancellation_authorized=False,
                limitation='T186 immutable autonomous ownership and effective rule checks are not integrated')
