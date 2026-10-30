"""Pure checks for plan-bound rules; deliberately not a submission authority.

These checks cannot establish a live lease, replay a round's consumption, or
certify routing evidence. The eventual T184/T185 adapter must do those checks
atomically at each action boundary. No transport, dialog or state writer lives
here, and a successful return must never be used as a reusable authorization.
"""
from copy import deepcopy
from datetime import datetime, timezone
import math
import re

from ag import approval, attempt, gaussian_input, render, study
from ag.config import cluster_name
from ag.node_targeting import node_name

SCHEMA = 'ag-autonomy-policy/1'
SUPPORTED = {'gaussian', 'gaussian-cp', 'crest', 'xtb', 'multiwfn'}
PROTOCOL_KEYS = {'method', 'basis', 'basis_function_type', 'dispersion',
                 'solvent_model', 'solvent', 'integration_grid'}
CONVERGENCE = {'normal': 0, 'tight': 1, 'verytight': 2}
PLAN_BOUND_KEYS = {'templates', 'clusters', 'max_cores_per_job', 'max_walltime',
                   'methods', 'routing_sha256', 'allow_relaxed'}
POLICY_KEYS = {'schema', 'study_id', 'study_key', 'round_id', 'plan_sha256', 'templates',
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
    require(value['scf_convergence'] >= 8, 'SCF convergence floor must be >= 8')
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
    if template in ('gaussian', 'gaussian-cp'):
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
    elif template == 'crest':
        require(bool({'--gfn2', '--gfnff'} & params.keys()), 'Autonomous CREST requires explicit method')
    else:
        require(set(params) == {'--analysis', '--grid'}, 'Multiwfn requires explicit analysis and grid')


def validate_plan_bounds(value):
    """Validate only the machine-readable submission limits in a plan.

    Keeping these limits inside the confirmed plan prevents a later local rule
    from adding an unapproved method, node or route. Identity and confirmation
    are checked by the store/adapter; attempt_limit and valid_until remain in
    the existing plan spec rather than creating contradictory duplicate limits.
    """
    fields(value, PLAN_BOUND_KEYS, 'plan submission policy')
    digest(value['routing_sha256'], 'routing_sha256')
    names(value['templates'], render.declaration, 'templates')
    require(set(value['templates']) <= SUPPORTED, 'Template has no autonomous method verifier')
    integer(value['max_cores_per_job'], 'max_cores_per_job')
    approval.walltime_seconds(value['max_walltime'])
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
        require(limit['max_queued_cores'] <= limit['max_committed_cores'],
                'Contradictory queued/committed core limits')
    fields(value['methods'], set(value['templates']), 'template methods')
    for template, methods in value['methods'].items():
        require(isinstance(methods, list) and bool(methods), 'Explicit method list required')
        for method in methods:
            template_method(template, method)
    return deepcopy(value)


def validate_policy(value):
    """Validate config only. Expiry is checked separately for every action."""
    fields(value, POLICY_KEYS, 'autonomous policy')
    require(value['schema'] == SCHEMA, 'Unsupported autonomous policy schema')
    study.identifier(value['study_id'])
    digest(value['study_key'], 'study_key')
    study.identifier(value['round_id'])
    digest(value['plan_sha256'], 'plan_sha256')
    integer(value['max_attempts'], 'max_attempts')
    text(value['quote'], 'quote')
    require(approval.timestamp(value['set_at']) < approval.timestamp(value['expires_at']),
            'Policy expiry must follow set_at')
    validate_plan_bounds({key: value[key] for key in PLAN_BOUND_KEYS})
    return deepcopy(value)


def check_plan_bounds(policy, spec):
    """Reject rules wider than the trusted, confirmed plan's submission limits.

    The caller must obtain spec from T184's verified store at the current action
    boundary, then separately check plan/round identity, expiry, lease and usage.
    This comparison neither authenticates a dict nor grants a submission permit.
    Old text-only plans remain readable but cannot pass this submission check.
    """
    validate_policy(policy)
    require(isinstance(spec, dict) and 'submission_policy' in spec,
            'Plan has no machine-readable submission policy')
    planned = validate_plan_bounds(spec['submission_policy'])
    integer(spec.get('attempt_limit'), 'plan attempt_limit')
    valid_until = spec.get('valid_until')
    require(type(valid_until) in (int, float) and math.isfinite(valid_until) and valid_until > 0,
            'Plan valid_until must be a positive finite timestamp')
    require(policy['max_attempts'] <= spec['attempt_limit'], 'Rule exceeds plan Attempt limit')
    require(approval.timestamp(policy['expires_at']).timestamp() <= valid_until,
            'Rule expiry exceeds plan validity')
    require(policy['routing_sha256'] == planned['routing_sha256'], 'Rule changes plan routing identity')
    require(not policy['allow_relaxed'] or planned['allow_relaxed'],
            'Rule enables relaxed input outside plan')
    require(set(policy['templates']) <= set(planned['templates']), 'Rule adds a template outside plan')
    require(set(policy['clusters']) <= set(planned['clusters']), 'Rule adds a cluster outside plan')
    require(policy['max_cores_per_job'] <= planned['max_cores_per_job'],
            'Rule exceeds plan per-job cores')
    require(approval.walltime_seconds(policy['max_walltime']) <= approval.walltime_seconds(planned['max_walltime']),
            'Rule exceeds plan walltime')
    for name, limit in policy['clusters'].items():
        ceiling = planned['clusters'][name]
        # An untargeted request can land on any scheduler-selected node; it is
        # not a narrower version of an explicit node allowlist (or vice versa).
        require(bool(limit['nodes']) == bool(ceiling['nodes'])
                and set(limit['nodes']) <= set(ceiling['nodes']),
                'Rule changes plan node scope')
        for key in ('max_committed_cores', 'max_queued_cores', 'max_jobs'):
            require(limit[key] <= ceiling[key], 'Rule exceeds plan ' + key)
    for template, methods in policy['methods'].items():
        for method in methods:
            if template in ('gaussian', 'gaussian-cp'):
                # One complete planned method must cover both floors. Taking
                # the weakest value from separate entries invents a new method.
                matches = [approved for approved in planned['methods'][template]
                           if all(method[key] == approved[key] for key in PROTOCOL_KEYS)
                           and CONVERGENCE[method['opt_convergence']] >= CONVERGENCE[approved['opt_convergence']]
                           and method['scf_convergence'] >= approved['scf_convergence']]
                require(bool(matches), 'Rule method/grid/convergence is outside plan')
            else:
                require(method in planned['methods'][template], 'Rule template parameters are outside plan')


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


def check_binding(policy, *, study_id, study_key, round_id, plan_sha256, routing_sha256, now=None):
    """Compare identifiers, not the truth of caller-provided plan/lease data."""
    validate_policy(policy)
    now = datetime.now(timezone.utc) if now is None else now
    require(isinstance(now, datetime) and now.tzinfo is not None and now.utcoffset() is not None,
            'Current time requires timezone')
    require(approval.timestamp(policy['set_at']) <= now < approval.timestamp(policy['expires_at']),
            'Autonomous policy expired or not yet valid')
    expected = dict(study_id=study_id, study_key=study_key, round_id=round_id, plan_sha256=plan_sha256,
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
        key = {'integral': 'int', 'em': 'empiricaldispersion', 'population': 'pop'}.get(key, key)
        require(key in {'opt', 'freq', 'sp', 'scf', 'int', 'scrf', 'empiricaldispersion',
                        '5d', '6d', '7f', '10f', 'nosymm', 'guess', 'geom', 'irc',
                        'counterpoise', 'pop', 'gfinput', 'gfprint', 'density'},
                'Cannot verify effect of route keyword on method/grid/convergence: ' + key)
        require(key not in parsed, 'Duplicate autonomous route keyword: ' + key)
        if key in {'5d', '6d', '7f', '10f', 'sp', 'nosymm'}:
            require(token == key, 'Unsupported autonomous flag spelling')
        if key == 'empiricaldispersion':
            # protocol() only proves the equals spelling for this keyword.
            require(re.fullmatch(r'(?:em|empiricaldispersion)=(?:\([^()]+\)|[a-z0-9]+)', token),
                    'Explicit equals spelling required for dispersion')
        parsed[key] = _options(token)
        # Output/analysis options do not require a different approved method or
        # the relaxed-input path. Checkpoint density is deliberately excluded:
        # it implies ChkBasis/Guess=Only and would bypass the explicit method.
        printing = {'pop': {'none', 'minimal', 'min', 'regular', 'reg', 'full'},
                    'gfinput': {'jnormalization', 'aonormalization', 'rawnormalization'},
                    'gfprint': set(), 'density': {'current', 'scf', 'hf', 'all'}}
        if key in printing:
            require(set(parsed[key]) <= printing[key], 'Unsupported analysis/output option')
        if key == 'counterpoise':
            require(parsed[key] == ['2'], 'Unsupported Counterpoise mode')
    return parsed


def _convergence(route, method, *, template='gaussian'):
    opts = _route_options(route)
    require('counterpoise' not in opts or template == 'gaussian-cp',
            'Counterpoise requires the gaussian-cp fragment verifier')
    # A model-supplied final/preoptimization label is intentionally not read.
    if 'opt' in opts:
        options = opts['opt']
        flags = {'normal', 'tight', 'verytight', 'calcfc', 'calcall', 'readfc', 'rcfc',
                 'ts', 'qst2', 'qst3', 'noeigentest', 'cartesian', 'modredundant',
                 'gdiis', 'gediis', 'rfo', 'notrust'}
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
            require(option in {'xqc', 'qc', 'yqc', 'tight', 'verytight', 'novaracc', 'fermi',
                               'noincfock', 'damp', 'nodiis'}
                    or re.fullmatch(r'(?:maxcycle|maxcycles)=[1-9][0-9]*', option)
                    or re.fullmatch(r'vshift=[0-9]+', option),
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
    from ag.autonomy_submission import study_identity
    root = study.locate(cfg, path.parent.parent)
    require(root.name == policy['study_id'], 'Policy study mismatch')
    identity = study_identity(root)  # Descriptor walk refuses symlinks before hashing the absolute path.
    require(identity['study_key'] == policy['study_key'], 'Policy study directory identity mismatch')
    manifest = attempt.read_manifest(path)
    require(manifest['study_id'] == policy['study_id'], 'Policy study mismatch')
    template = manifest['template']
    require(template in policy['templates'], 'Policy template mismatch')
    cluster = manifest.get('cluster', 'default')
    require(cluster in policy['clusters'], 'Policy cluster mismatch')
    require(type(manifest['cores']) is int and 0 < manifest['cores'] <= policy['max_cores_per_job'],
            'Policy per-job cores exceeded')
    require(manifest['cores'] <= policy['clusters'][cluster]['max_queued_cores'],
            'Requested cores exceed target policy capacity')
    require(approval.walltime_seconds(manifest['walltime']) <= approval.walltime_seconds(policy['max_walltime']),
            'Policy walltime exceeded')
    nodes = policy['clusters'][cluster]['nodes']
    if 'node_target' in manifest:
        require(manifest['node_target']['name'] in nodes, 'Node is not explicitly allowed by autonomous policy')
    else:
        require(not nodes, 'Autonomous policy requires an explicit node target')
    require(not any(key in manifest for key in ('relaxed_input', 'allow_relaxed', 'skipped_checks')),
            'Unsupported relaxed-input marker')
    relaxed = manifest.get('input_validation')
    if relaxed is not None:
        require(policy['allow_relaxed'] and hasattr(attempt, 'prepared_bundle')
                and hasattr(attempt, 'program_input_name'),
                'Relaxed-input submission is not implemented or not allowed')
    files = attempt.verified_files(cfg, path, manifest)
    if relaxed is not None:
        require(set(relaxed) == {'mode', 'skipped_checks', 'method_verified'}
                and relaxed['mode'] == 'relaxed' and relaxed['method_verified'] is False
                and isinstance(relaxed['skipped_checks'], list) and relaxed['skipped_checks'],
                'Invalid frozen relaxed-input evidence')
        from ag.gaussian_relaxed import _route
        sections = manifest['science'].get('sections')
        require(isinstance(sections, list) and sections, 'Missing frozen Link1 section evidence')
        methods = policy['methods'][template]
        # An unverified method cannot select a more permissive candidate. Take
        # only the strictest convergence floors across the complete allowed
        # methods; this does not combine or verify their scientific protocols.
        floor = dict(opt_convergence=max((m['opt_convergence'] for m in methods), key=CONVERGENCE.get),
                     scf_convergence=max(m['scf_convergence'] for m in methods))
        for section in sections:
            _, options = _route(section['route'])
            require('stable' not in options, 'Stable is outside the autonomous method policy')
            # General basis/ECP and additional-section semantics remain
            # unverified. The explicit input exception cannot relax convergence
            # in any Link1 section, including a model-labelled preliminary one.
            convergence = '# HF/STO-3G ' + ' '.join(
                key + ('=(' + options[key].replace('numerical', 'numer') + ')' if options[key] else '')
                for key in ('opt', 'freq', 'scf') if key in options)
            try:
                _convergence(convergence, floor, template=template)
            except ValueError as exc:
                raise ValueError('Relaxed-input convergence is below the approved floor: ' + str(exc)) from exc
        # T188's verified_files re-parses the actual primary input and compares
        # the exact frozen input-validation.json and attachment list. Permission
        # to use that exception never turns an unverified method into a match.
        return dict(attempt_id=manifest['attempt_id'], bundle_sha256=manifest['bundle_sha256'],
                    inputs=deepcopy(manifest['inputs']), method=None, method_verified=False,
                    skipped_checks=deepcopy(relaxed['skipped_checks']))
    if template in ('gaussian', 'gaussian-cp'):
        from ag._profile_sources import protocol, integration_grid
        inputs = ([attempt.program_input_name(manifest)] if hasattr(attempt, 'program_input_name')
                  else [name for name in files if name.endswith('.gjf')])
        require(len(inputs) == 1, 'Expected exactly one frozen Gaussian input')
        if template == 'gaussian-cp':
            fragments = manifest['science']['counterpoise']['file']
            _, science = gaussian_input.counterpoise_input(files[inputs[0]].decode(), files[fragments],
                manifest['cores'], manifest['mem_gb'], prepared=True)
        else:
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
                _convergence(science['route'], method, template=template)
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


def check_budget(policy, *, plan_spec, round_attempts, requested_attempts, occupancy):
    """Pure rejection check. Caller MUST supply replayed counts and live totals.

    occupancy is grouped by real scheduler/account and already deduplicated:
    each group contains all configured peer entry names, actual + unobserved
    cores/jobs, and the requested additions. No rule name/run ID keys the count.
    This function cannot certify those data, reserve capacity or write a pause.
    """
    check_plan_bounds(policy, plan_spec)
    planned = plan_spec['submission_policy']
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
        # Removing an allowed target must not remove the stricter ceiling of a
        # peer on the same actual account from the confirmed plan.
        limits.extend(planned['clusters'][name] for name in group['clusters']
                      if name in planned['clusters'])
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
