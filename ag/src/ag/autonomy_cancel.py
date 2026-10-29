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
    fd = disk.directory(path / 'inputs')
    try:
        files = {remote.filename(name): disk.Store(fd).read(name) for name in os.listdir(fd)}
    finally:
        os.close(fd)
    if 'input-validation.json' in files:
        raise ValueError('Relaxed input sidecar prevents automatic reroute')
    records, bundle_sha = attempt.bundle(files)
    if records != manifest['inputs'] or bundle_sha != manifest['bundle_sha256']:
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


def read_bytes(path):
    fd = disk.directory(path.parent)
    try:
        return disk.Store(fd).read(path.name)
    finally:
        os.close(fd)


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
    previous, paused, count = None, False, 0
    for count, line in enumerate(read_bytes(path.parent.parent / 'autonomy' / 'journal.jsonl')
                                 .splitlines(keepends=True), 1):
        event = disk.decode(line)
        if (not line.endswith(b'\n') or event['seq'] != count
                or event['prev_sha256'] != previous):
            raise ValueError('Autonomy journal changed during evidence review')
        previous = digest(line)
        if count <= started_seq:
            if event['op'] == 'pause':
                paused = True
            elif event['op'] == 'resume':
                paused = False
        elif paused or event['op'] == 'pause':
            raise ValueError('Pause interrupted the pair; need two new consecutive wake captures after resume')
    if count != current['seq'] or previous != current['journal_sha256']:
        raise ValueError('Autonomy journal changed during evidence review')


def review_no_progress(cfg, path, *, run_id, token, plan_sha256, reviews):
    """Verify two consecutive wake captures and explicit per-capture review.

    Each capture was made within its own valid wake. There is no fixed TTL
    across wakes: a confirmed schedule can space them hours apart. The current
    lease must remain valid, and a pause/resume breaks the observation pair.
    """
    root = Path(cfg['local']['studies_root'])
    path = study.local_path(root, Path(path))
    if not isinstance(reviews, list) or len(reviews) != 2:
        raise ValueError('Review exactly two different consecutive wake snapshots')
    with autonomy.action_guard(cfg, path.parent.parent.name, run_id, token,
                               action='cancel', plan_sha256=plan_sha256) as current:
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
