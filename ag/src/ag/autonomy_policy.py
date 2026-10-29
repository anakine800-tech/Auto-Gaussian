"""Pure checks for plan-bound rules; deliberately not a submission authority.

These checks cannot establish a live lease, replay a round's consumption, or
certify routing evidence. The eventual T184/T185 adapter must do those checks
atomically at each action boundary. No transport, dialog or state writer lives
here, and a successful return must never be used as a reusable authorization.
"""
from copy import deepcopy
from datetime import datetime, timezone
import re

from ag import approval, attempt, gaussian_input, render, study
from ag.config import cluster_name
from ag.node_targeting import node_name

SCHEMA = 'ag-autonomy-policy/1'
SUPPORTED = {'gaussian', 'crest', 'xtb'}
PROTOCOL_KEYS = {'method', 'basis', 'basis_function_type', 'dispersion',
                 'solvent_model', 'solvent', 'integration_grid'}
CONVERGENCE = {'normal': 0, 'tight': 1, 'verytight': 2}
POLICY_KEYS = {'schema', 'study_id', 'round_id', 'plan_sha256', 'templates',
               'clusters', 'max_cores_per_job', 'max_walltime', 'max_attempts',
               'expires_at', 'quote', 'set_at', 'methods', 'routing_sha256',
               'allow_relaxed'}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def fields(value, keys, label):
    require(isinstance(value, dict) and set(value) == keys, f'Invalid {label} fields')


def integer(value, label, minimum=1):
    require(type(value) is int and value >= minimum, f'{label} must be an integer >= {minimum}')
    return value


def text(value, label):
    require(isinstance(value, str) and bool(value.strip()), f'{label} must not be blank')
    return value


def digest(value, label):
    require(isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value),
            f'{label} requires SHA-256')
    return value


def names(values, validator, label, *, empty=False):
    require(isinstance(values, list) and (bool(values) or empty)
            and all(isinstance(x, str) for x in values), f'Invalid {label} list')
    require(len(values) == len(set(values)), f'Duplicate {label}')
    for value in values:
        validator(value)


def gaussian_method(value):
    """Require canonical protocol values, including an explicit grid policy."""
    from ag._profile_sources import protocol, integration_grid
    fields(value, PROTOCOL_KEYS | {'opt_convergence', 'scf_convergence'}, 'Gaussian method')
    for key in PROTOCOL_KEYS:
        text(value[key], key)
    require(isinstance(value['opt_convergence'], str) and value['opt_convergence'] in CONVERGENCE,
            'Unsupported Opt convergence floor')
    integer(value['scf_convergence'], 'SCF convergence')
    require(8 <= value['scf_convergence'] <= 12, 'SCF convergence floor must be 8..12')
    # Reconstruct only the method settings for validation, never a job input.
    # Canonical comparison rejects spelling that the shared parser cannot prove.
    route = '# ' + value['method'] + '/' + value['basis']
    if value['basis_function_type'] != 'basis_default':
        route += ' ' + value['basis_function_type']
    if value['dispersion'] != 'method_default':
        route += ' EmpiricalDispersion=' + value['dispersion']
    if value['solvent_model'] != 'none' or value['solvent'] != 'none':
        route += f" SCRF=({value['solvent_model']},Solvent={value['solvent']})"
    if value['integration_grid'] != 'program_default':
        grid = value['integration_grid']
        require(bool(re.fullmatch(r'[a-z0-9=,]+', grid)), 'Unsupported integration grid')
        route += ' Int=(' + grid + ')'
    parsed = protocol(route, 1)
    require(_restricted(parsed['method']), 'Autonomous method verifier requires closed-shell method')
    parsed['integration_grid'] = integration_grid(route)
    require(parsed == {k: value[k] for k in PROTOCOL_KEYS}, 'Method must use canonical protocol values')


def _restricted(method):
    from ag._profile_sources import SCF_ENERGY_METHODS
    # R + OPBE is ROPBE, which must not be mistaken for a RO spin prefix.
    return method.startswith('r') and method[1:].replace('-', '') in {
        name.replace('-', '') for name in SCF_ENERGY_METHODS}


def template_method(template, value):
    if template == 'gaussian':
        gaussian_method(value)
        return
    fields(value, {'parameters'}, 'template method')
    params = value['parameters']
    require(isinstance(params, dict) and all(isinstance(k, str) and isinstance(v, str)
                                            for k, v in params.items()),
            'Template parameters must be strings')
    render.parameters(template, params)
    if template == 'xtb':
        require(params.get('--gfn') == '2', 'Autonomous xTB requires explicit --gfn 2')
    else:
        require(bool({'--gfn2', '--gfnff'} & params.keys()), 'Autonomous CREST requires explicit method')


def validate_policy(value):
    """Validate config only. Expiry is checked separately for every action."""
    fields(value, POLICY_KEYS, 'autonomous policy')
    require(value['schema'] == SCHEMA, 'Unsupported autonomous policy schema')
    study.identifier(value['study_id'])
    study.identifier(value['round_id'])
    digest(value['plan_sha256'], 'plan_sha256')
    digest(value['routing_sha256'], 'routing_sha256')
    names(value['templates'], render.declaration, 'templates')
    require(set(value['templates']) <= SUPPORTED, 'Template has no autonomous method verifier')
    integer(value['max_cores_per_job'], 'max_cores_per_job')
    integer(value['max_attempts'], 'max_attempts')
    approval.walltime_seconds(value['max_walltime'])
    text(value['quote'], 'quote')
    require(approval.timestamp(value['set_at']) < approval.timestamp(value['expires_at']),
            'Policy expiry must follow set_at')
    require(type(value['allow_relaxed']) is bool, 'allow_relaxed must be boolean')
    clusters = value['clusters']
    require(isinstance(clusters, dict) and bool(clusters), 'Explicit cluster limits required')
    for name, limit in clusters.items():
        cluster_name(name)
        fields(limit, {'nodes', 'max_committed_cores', 'max_queued_cores', 'max_jobs'}, 'cluster limit')
        # [] means ONLY untargeted submission, never a wildcard for PBS nodes.
        names(limit['nodes'], node_name, 'nodes', empty=True)
        for key in ('max_committed_cores', 'max_queued_cores', 'max_jobs'):
            integer(limit[key], key)
        require(value['max_cores_per_job'] <= limit['max_queued_cores'] <= limit['max_committed_cores'],
                'Contradictory per-job/queued/committed core limits')
    fields(value['methods'], set(value['templates']), 'template methods')
    for template, methods in value['methods'].items():
        require(isinstance(methods, list) and bool(methods), 'Explicit method list required')
        for method in methods:
            template_method(template, method)
        hashes = [approval.digest(method) for method in methods]
        require(len(set(hashes)) == len(hashes), 'Duplicate method')
    return deepcopy(value)


def validate_policies(policies):
    require(isinstance(policies, dict), 'Expected autonomous_policies table')
    for name, policy in policies.items():
        cluster_name(name)
        validate_policy(policy)


def read_policy(cfg, name):
    """No legacy fallback, even if the manual namespace has the same name."""
    cluster_name(name)
    policies = cfg.get('approval', {}).get('autonomous_policies', {})
    require(name in policies, 'Plan-bound autonomous policy does not exist')
    return validate_policy(policies[name])


def check_binding(policy, *, study_id, round_id, plan_sha256, routing_sha256, now=None):
    """Compare identifiers, not the truth of caller-provided plan/lease data."""
    validate_policy(policy)
    now = now or datetime.now(timezone.utc)
    require(isinstance(now, datetime) and now.tzinfo is not None and now.utcoffset() is not None,
            'Current time requires timezone')
    require(approval.timestamp(policy['set_at']) <= now < approval.timestamp(policy['expires_at']),
            'Autonomous policy expired or not yet valid')
    expected = dict(study_id=study_id, round_id=round_id, plan_sha256=plan_sha256,
                    routing_sha256=routing_sha256)
    require(all(policy[k] == v for k, v in expected.items()), 'Autonomous policy binding mismatch')
    return approval.digest(policy)


def _options(token):
    raw = ''
    # Also support bare flags and Gaussian's keyword(options) spelling.
    if '(' in token:
        raw = token[token.index('(') + 1:-1]
    elif '=' in token:
        raw = token.split('=', 1)[1]
    return raw.split(',') if raw else []


def _route_options(route):
    """Fail closed on unhandled spelling that could hide a changed method.

    This does not lock the entire route: reviewed SCF/Opt iteration/algorithm
    changes are allowed. Profile's broader analysis parser remains unchanged.
    """
    route = re.sub(r'\s*([=,/])\s*', r'\1', route.lower())
    route = re.sub(r'\([^()]*\)', lambda m: re.sub(r'\s+', '', m[0]), route)
    tokens = route.split()
    parsed = {}
    for token in tokens:
        if token in ('#', '#p', '#n', '#t'):
            continue
        if '/' in token:
            require(re.fullmatch(r'[a-z][a-z0-9+_()-]*/[a-z0-9+*(),_.-]+', token),
                    'Unsupported autonomous method/basis token')
            continue
        match = re.fullmatch(r'([a-z][a-z0-9]*|5d|6d|7f|10f)'
                             r'(?:=(?:[^()\s]+|\([^()]+\))|\([^()]+\))?', token)
        require(match is not None, 'Unsupported autonomous route spelling')
        key = match[1]
        key = {'integral': 'int', 'em': 'empiricaldispersion'}.get(key, key)
        require(key in {'opt', 'freq', 'sp', 'scf', 'int', 'scrf', 'empiricaldispersion',
                        '5d', '6d', '7f', '10f', 'nosymm', 'guess', 'geom', 'irc'},
                'Unsupported autonomous route keyword: ' + key)
        require(key not in parsed, 'Duplicate autonomous route keyword: ' + key)
        if key in {'5d', '6d', '7f', '10f', 'sp', 'nosymm'}:
            require(token == key, 'Unsupported autonomous flag spelling')
        if key == 'empiricaldispersion':
            # protocol() only proves the equals spelling for this keyword.
            require(re.fullmatch(r'(?:em|empiricaldispersion)=(?:\([^()]+\)|[a-z0-9]+)', token),
                    'Explicit equals spelling required for dispersion')
        parsed[key] = _options(token)
    return parsed


def _convergence(route, method):
    opts = _route_options(route)
    # A model-supplied final/preoptimization label is intentionally not read.
    if 'opt' in opts:
        options = opts['opt']
        flags = {'normal', 'tight', 'verytight', 'calcfc', 'calcall', 'readfc', 'rcfc',
                 'ts', 'qst2', 'qst3', 'noeigentest', 'cartesian', 'modredundant'}
        for option in options:
            require(option in flags or re.fullmatch(r'(?:maxcycles|maxcycle|maxstep|recalcfc)=[1-9][0-9]*', option),
                    'Unsupported or relaxed Opt option')
        levels = set(options) & CONVERGENCE.keys()
        require(len(levels) <= 1, 'Ambiguous Opt convergence')
        level = next(iter(levels), 'normal')
        require(CONVERGENCE[level] >= CONVERGENCE[method['opt_convergence']],
                'Opt convergence below policy floor')
    if 'freq' in opts:
        require(all(o in {'raman', 'noraman', 'hpmodes', 'savenormalmodes', 'numer', 'analytic'}
                    for o in opts['freq']), 'Unsupported or relaxed Freq option')
    explicit = []
    for option in opts.get('scf', []):
        if re.fullmatch(r'(?:conver|convergence)=[0-9]+', option):
            explicit.append(int(option.split('=')[1]))
        else:
            require(option in {'xqc', 'qc', 'yqc', 'tight', 'verytight', 'novaracc', 'fermi'}
                    or re.fullmatch(r'(?:maxcycle|maxcycles)=[1-9][0-9]*', option),
                    'Unsupported or relaxed SCF option')
    require(len(explicit) <= 1, 'Ambiguous SCF convergence')
    # Do not assert that an absent setting equals an explicit tighter floor.
    # For SP, require the approved floor explicitly (Gaussian SP defaults vary).
    if explicit:
        require(explicit[0] >= method['scf_convergence'], 'SCF convergence below policy floor')
    else:
        require(method['scf_convergence'] == 8 and ('opt' in opts or 'freq' in opts
                or {'tight', 'verytight'} & set(opts.get('scf', []))),
                'Explicit SCF convergence required for this policy')


def check_attempt(cfg, path, policy):
    """Read and verify current frozen bytes; return facts, never authorization."""
    validate_policy(policy)
    manifest = attempt.read_manifest(path)
    require(manifest['study_id'] == policy['study_id'], 'Policy study mismatch')
    template = manifest['template']
    require(template in policy['templates'], 'Policy template mismatch')
    cluster = manifest.get('cluster', 'default')
    require(cluster in policy['clusters'], 'Policy cluster mismatch')
    require(type(manifest['cores']) is int and 0 < manifest['cores'] <= policy['max_cores_per_job'],
            'Policy per-job cores exceeded')
    require(approval.walltime_seconds(manifest['walltime']) <= approval.walltime_seconds(policy['max_walltime']),
            'Policy walltime exceeded')
    nodes = policy['clusters'][cluster]['nodes']
    if 'node_target' in manifest:
        require(manifest['node_target']['name'] in nodes, 'Node is not explicitly allowed by autonomous policy')
    else:
        require(not nodes, 'Autonomous policy requires an explicit node target')
    # T188 must define immutable markers and skipped-check evidence first.
    # Neither this switch nor any model-authored marker bypasses normal parsing.
    require(not any(key in manifest for key in ('relaxed_input', 'allow_relaxed', 'skipped_checks')),
            'Relaxed-input submission is not implemented')
    files = attempt.verified_files(cfg, path, manifest)
    if template == 'gaussian':
        from ag._profile_sources import protocol, integration_grid
        inputs = [name for name in files if name.endswith('.gjf')]
        require(len(inputs) == 1, 'Expected exactly one frozen Gaussian input')
        science = gaussian_input.validate(files[inputs[0]].decode(), manifest['cores'], manifest['mem_gb'],
                                          parent_chk='parent_chk' in manifest)
        require(science['multiplicity'] == 1, 'Autonomous method verifier requires closed-shell input')
        actual = protocol(science['route'], science['multiplicity'])
        require(_restricted(actual['method']), 'Autonomous method verifier requires closed-shell method')
        actual['integration_grid'] = integration_grid(science['route'])
        matches = [m for m in policy['methods'][template]
                   if actual == {k: m[k] for k in PROTOCOL_KEYS}]
        require(bool(matches), 'Frozen input method/grid differs from autonomous policy')
        errors = []
        for method in matches:
            try:
                _convergence(science['route'], method)
                break
            except ValueError as exc:
                errors.append(str(exc))
        else:
            raise ValueError('; '.join(errors))
    else:
        # verified_files also compares the frozen script to the reviewed
        # template rendered with these parameters, so a model declaration alone
        # cannot change the executable method. No Gaussian protocol is invented.
        actual = {'parameters': manifest['template_params']}
        require(actual in policy['methods'][template], 'Frozen template parameters differ from policy')
    return dict(attempt_id=manifest['attempt_id'], bundle_sha256=manifest['bundle_sha256'],
                inputs=deepcopy(manifest['inputs']), method=actual, method_verified=True)


def check_budget(policy, *, round_attempts, requested_attempts, occupancy):
    """Pure rejection check. Caller MUST supply replayed counts and live totals.

    occupancy is grouped by real scheduler/account and already deduplicated:
    each group contains all configured peer entry names, actual + unobserved
    cores/jobs, and the requested additions. No rule name/run ID keys the count.
    This function cannot certify those data, reserve capacity or write a pause.
    """
    validate_policy(policy)
    integer(round_attempts, 'round_attempts', 0)
    integer(requested_attempts, 'requested_attempts')
    maximum = policy['max_attempts']
    require(round_attempts + requested_attempts <= maximum, 'Round Attempt budget exceeded')
    require(round_attempts * 10 < maximum * 9, 'Round Attempt budget reached 90%; pause required')
    require((round_attempts + requested_attempts - 1) * 10 < maximum * 9,
            'Batch crosses the 90% pause boundary')
    require(isinstance(occupancy, list) and bool(occupancy), 'Verified account occupancy required')
    seen = set()
    requested_jobs = 0
    for group in occupancy:
        fields(group, {'clusters', 'committed_cores', 'queued_cores', 'jobs',
                       'requested_cores', 'requested_jobs'}, 'account occupancy')
        names(group['clusters'], cluster_name, 'account clusters')
        require(not seen.intersection(group['clusters']), 'Account entry counted more than once')
        seen.update(group['clusters'])
        limits = [policy['clusters'][name] for name in group['clusters'] if name in policy['clusters']]
        require(bool(limits), 'Account has no allowed policy entry')
        for key in ('committed_cores', 'queued_cores', 'jobs'):
            integer(group[key], key, 0)
        for key in ('requested_cores', 'requested_jobs'):
            integer(group[key], key)
        require(group['requested_jobs'] <= group['requested_cores']
                <= group['requested_jobs'] * policy['max_cores_per_job'],
                'Requested cores contradict per-job limits')
        requested_jobs += group['requested_jobs']
        require(group['queued_cores'] <= group['committed_cores'], 'Contradictory occupancy')
        for used, delta, cap in (('committed_cores', 'requested_cores', 'max_committed_cores'),
                                ('queued_cores', 'requested_cores', 'max_queued_cores'),
                                ('jobs', 'requested_jobs', 'max_jobs')):
            require(group[used] + group[delta] <= min(limit[cap] for limit in limits),
                    'Shared-account autonomous limit exceeded: ' + cap)
    require(requested_jobs == requested_attempts, 'Requested job/Attempt count mismatch')
    return {'pause_after_consumption': (round_attempts + requested_attempts) * 10 >= maximum * 9}
