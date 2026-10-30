"""T186 pure rule checks. No leases, routing authorization or live transport."""
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

import pytest

from ag import approval, attempt, autonomy_policy as policy, config, study, submit
from test_core import cfg, prepared, Fake, INPUT
from test_approval import policy as manual_policy

NOW = datetime(2026, 10, 29, tzinfo=timezone.utc)
ROUTE = '# B3LYP/6-31G(d) Opt=Tight Freq Int=UltraFine SCF=(XQC,Conver=8)'


@pytest.fixture(autouse=True)
def isolated_machine_registry(tmp_path, monkeypatch):
    home = tmp_path / 'synthetic-home'
    home.mkdir()
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: home))


def rule(cfg=None):
    key = (sha256(str(Path(cfg['local']['studies_root']).absolute() / 'smoke').encode()).hexdigest()
           if cfg is not None else 'e' * 64)
    return dict(schema=policy.SCHEMA, study_id='smoke', study_key=key, round_id='round-1',
                plan_sha256='a' * 64, routing_sha256='b' * 64,
                templates=['gaussian'], max_cores_per_job=8, max_walltime='01:00:00',
                max_attempts=10, expires_at='2026-10-30T00:00:00+00:00',
                quote='  本轮授权原话。\n保留全部空白。  ', set_at='2026-10-28T00:00:00+00:00',
                allow_relaxed=False,
                clusters={'default': dict(nodes=[], max_committed_cores=32,
                                          max_queued_cores=16, max_jobs=4)},
                methods={'gaussian': [dict(method='rb3lyp', basis='6-31g(d)',
                    basis_function_type='basis_default', dispersion='method_default',
                    solvent_model='none', solvent='none', integration_grid='ultrafine',
                    opt_convergence='tight', scf_convergence=8)]})


def binding(value):
    return {k: value[k] for k in ('study_id', 'study_key', 'round_id', 'plan_sha256', 'routing_sha256')}


def make(cfg, tmp_path, route=ROUTE, **kwargs):
    if not (tmp_path / 'studies' / 'smoke').exists():
        study.init(cfg, 'smoke')
    source = tmp_path / 'autonomy-water.gjf'
    source.write_text(INPUT.replace('# B3LYP/6-31G(d) SP', route))
    manifest = attempt.prepare(cfg, study_name='smoke', template='gaussian', input_path=source,
        tier='simple', walltime='00:30:00', label='optfreq', method_basis='合成水分子方法检查', **kwargs)
    return attempt.find(cfg, manifest['attempt_id']), manifest


def occupancy(**changes):
    value = dict(clusters=['default'], committed_cores=0, queued_cores=0,
                 jobs=0, requested_cores=8, requested_jobs=1)
    value.update(changes)
    return [value]


def test_namespace_and_hash(cfg):
    manual_policy(cfg)
    value = rule(cfg)
    cfg['approval']['autonomous_policies'] = {'validation': value}
    config.validate_approval(cfg)
    assert policy.read_policy(cfg, 'validation') == value
    assert policy.check_binding(value, **binding(value), now=NOW) == approval.digest(value)
    assert policy.read_policy(cfg, 'validation')['quote'] == value['quote']
    for key in value:
        changed = deepcopy(value)
        # Every byte-level field is included, including quote/set_at/expiry.
        changed[key] = None
        assert approval.digest(changed) != approval.digest(value)
    del cfg['approval']['autonomous_policies']
    with pytest.raises(ValueError, match='Plan-bound'):
        policy.read_policy(cfg, 'validation')


@pytest.mark.parametrize('field', sorted(policy.POLICY_KEYS))
def test_each_required_field(cfg, field):
    value = rule(cfg)
    del value[field]
    cfg['approval'] = {'autonomous_policies': {'bounded': value}}
    with pytest.raises(config.ConfigError):
        config.validate_approval(cfg)


@pytest.mark.parametrize('key,value', [
    ('schema', 'ag-approval/1'), ('study_id', '*'), ('round_id', ' '),
    ('study_key', 'a' * 63), ('study_key', 'A' * 64), ('study_key', False),
    ('study_key', ''), ('study_key', 'synthetic/study'),
    ('plan_sha256', 'a' * 63), ('routing_sha256', 'x' * 64),
    ('templates', []),
    ('templates', ['gaussian*']), ('templates', ['multiwfn']),
    ('max_cores_per_job', True), ('max_cores_per_job', 0),
    ('max_walltime', '00:00:00'), ('max_walltime', float('inf')),
    ('max_attempts', True), ('max_attempts', 0), ('max_attempts', float('nan')),
    ('expires_at', '2026-10-27T00:00:00+00:00'), ('expires_at', '2026-10-30'),
    ('set_at', 5), ('quote', ' \n'), ('allow_relaxed', 1),
    ('clusters', {}), ('methods', {}),
])
def test_bad_top_fields(key, value):
    data = rule()
    data[key] = value
    with pytest.raises(ValueError):
        policy.validate_policy(data)


@pytest.mark.parametrize('key,value', [('nodes', ['*']), ('nodes', [' ']),
    ('max_committed_cores', 8),
    ('max_queued_cores', 33), ('max_queued_cores', True), ('max_jobs', 0), ('extra', 1)])
def test_bad_cluster_fields(key, value):
    data = rule()
    data['clusters']['default'][key] = value
    with pytest.raises(ValueError):
        policy.validate_policy(data)


@pytest.mark.parametrize('key', sorted(policy.PROTOCOL_KEYS | {'opt_convergence', 'scf_convergence'}))
def test_bad_method_fields(key):
    data = rule()
    data['methods']['gaussian'][0][key] = ' '
    with pytest.raises(ValueError):
        policy.validate_policy(data)


@pytest.mark.parametrize('location', ['policy', 'cluster', 'method'])
def test_unknown_fields(location):
    data = rule()
    target = {'policy': data, 'cluster': data['clusters']['default'],
              'method': data['methods']['gaussian'][0]}[location]
    target['typo'] = True
    with pytest.raises(ValueError):
        policy.validate_policy(data)


@pytest.mark.parametrize('key', ['study_id', 'study_key', 'round_id', 'plan_sha256', 'routing_sha256'])
def test_changed_binding(key):
    value = rule()
    args = binding(value)
    args[key] = 'changed'
    with pytest.raises(ValueError, match='binding mismatch'):
        policy.check_binding(value, **args, now=NOW)


@pytest.mark.parametrize('date', [datetime(2026, 10, 27, tzinfo=timezone.utc),
                                  datetime(2026, 10, 30, tzinfo=timezone.utc)])
def test_time_boundary(date):
    value = rule()
    with pytest.raises(ValueError, match='expired or not yet'):
        policy.check_binding(value, **binding(value), now=date)


def test_no_manual_policy_fallback(cfg, prepared):
    path, _ = prepared
    cfg['approval'] = {'autonomous_policies': {'bounded': rule(cfg)}}
    fake = Fake(cfg)
    with pytest.raises(ValueError, match='policy does not exist'):
        submit.submit(cfg, [path.name], fake, policy_name='bounded')
    assert not fake.calls
    assert not (path / '.submit-claim').exists()


@pytest.mark.parametrize('route', [ROUTE,
    ROUTE.replace('Opt=Tight', 'Opt=(VeryTight,CalcFC,MaxCycles=100)'),
    ROUTE.replace('SCF=(XQC,Conver=8)', 'SCF=(QC,Conver=9,MaxCycle=200)'),
    ROUTE.replace('Conver=8', 'Conver=13'),
    ROUTE.replace('Opt=Tight', 'Opt(Tight)'),
    ROUTE.replace('Int=UltraFine', 'Integral=(UltraFine)'),
])
def test_frozen_method_and_allowed_adjustments(cfg, tmp_path, route):
    path, manifest = make(cfg, tmp_path, route)
    before = (path / 'manifest.json').read_bytes()
    value = rule(cfg)
    if 'Conver=13' in route:
        value['methods']['gaussian'][0]['scf_convergence'] = 13
        value['templates'] *= 2
        value['methods']['gaussian'] *= 2
    result = policy.check_attempt(cfg, path, value)
    assert result['method_verified'] and result['bundle_sha256'] == manifest['bundle_sha256']
    assert result['inputs'] == manifest['inputs']
    assert (path / 'manifest.json').read_bytes() == before
    assert not (path / '.submit-claim').exists()


@pytest.mark.parametrize('route', [
    ROUTE.replace('B3LYP', 'PBE0'), ROUTE.replace('6-31G(d)', '6-31+G(d)'),
    ROUTE + ' 5D', ROUTE + ' EmpiricalDispersion=GD3BJ',
    ROUTE + ' SCRF=(SMD,Solvent=Water)', ROUTE.replace('UltraFine', 'FineGrid'),
    ROUTE.replace(' Int=UltraFine', ''), ROUTE.replace('Opt=Tight', 'Opt'),
    ROUTE.replace('Opt=Tight', 'Opt=Loose'), ROUTE.replace('Opt=Tight', 'Opt=(Tight,Conver=4)'),
    ROUTE.replace('Conver=8', 'Conver=6'), ROUTE.replace('Freq', 'Freq=(Numer,Step=100)'),
    ROUTE + ' Integral=UltraFine', ROUTE + ' SCF=Loose', ROUTE + ' BLYP',
])
def test_method_grid_or_convergence_change_rejected(cfg, tmp_path, route):
    path, _ = make(cfg, tmp_path, route)
    # A label cannot let a relaxed final calculation pretend to be preliminary.
    m = json.loads((path / 'manifest.json').read_text())
    m['label'] = 'preoptimization'
    (path / 'manifest.json').write_text(json.dumps(m))
    with pytest.raises(ValueError):
        policy.check_attempt(cfg, path, rule(cfg))
    assert not (path / '.submit-claim').exists()


def test_input_bytes_not_model_route(cfg, tmp_path):
    path, _ = make(cfg, tmp_path)
    file = path / 'inputs' / 'autonomy-water.gjf'
    file.write_text(file.read_text().replace('B3LYP', 'PBE0'))
    with pytest.raises(ValueError, match='bundle'):
        policy.check_attempt(cfg, path, rule(cfg))


@pytest.mark.parametrize('marker', [None, 'input_validation', 'relaxed_input', 'allow_relaxed', 'skipped_checks'])
def test_allow_relaxed_is_not_a_bypass(cfg, tmp_path, marker):
    path, _ = make(cfg, tmp_path, ROUTE.replace('B3LYP', 'PBE0'))
    value = rule(cfg)
    value['allow_relaxed'] = True
    if marker:
        m = json.loads((path / 'manifest.json').read_text())
        m[marker] = True
        (path / 'manifest.json').write_text(json.dumps(m))
    with pytest.raises(ValueError):
        policy.check_attempt(cfg, path, value)


@pytest.mark.parametrize('key,value', [('study_id', 'elsewhere'), ('templates', ['xtb']),
    ('max_cores_per_job', 4), ('max_walltime', '00:15:00'), ('clusters', {'other': {}})])
def test_attempt_scope_rejected(cfg, tmp_path, key, value):
    path, _ = make(cfg, tmp_path)
    data = rule(cfg)
    if key == 'clusters':
        value = {'other': data['clusters']['default']}
    elif key == 'templates':
        data['methods'] = {'xtb': [{'parameters': {'--gfn': '2'}}]}
    data[key] = value
    with pytest.raises(ValueError):
        policy.check_attempt(cfg, path, data)


def test_node_list_not_wildcard(cfg, tmp_path):
    path, _ = make(cfg, tmp_path)
    value = rule(cfg)
    value['clusters']['default']['nodes'] = ['node-a']
    with pytest.raises(ValueError, match='explicit node target'):
        policy.check_attempt(cfg, path, value)
    m = json.loads((path / 'manifest.json').read_text())
    m['node_target'] = {'name': 'node-b'}
    (path / 'manifest.json').write_text(json.dumps(m))
    with pytest.raises(ValueError, match='not explicitly allowed'):
        policy.check_attempt(cfg, path, value)


@pytest.mark.parametrize('template,params', [('xtb', {'--gfn': '2', '--opt': 'tight'}),
                                          ('crest', {'--gfn2': '', '--alpb': 'water'})])
def test_non_gaussian_uses_frozen_template(cfg, tmp_path, template, params):
    study.init(cfg, 'smoke')
    source = tmp_path / 'water.xyz'
    source.write_text('3\nWater\nO 0 0 0\nH 0 0 1\nH 0 1 0\n')
    manifest = attempt.prepare(cfg, study_name='smoke', template=template, input_path=source,
        tier='simple', walltime='00:30:00', label='pre', method_basis='合成方法检查', params=params)
    path = attempt.find(cfg, manifest['attempt_id'])
    value = rule(cfg)
    value['templates'] = [template]
    value['methods'] = {template: [{'parameters': params}]}
    assert policy.check_attempt(cfg, path, value)['method'] == {'parameters': params}
    value['methods'][template][0]['parameters'] = {**params, '--chrg': '1'}
    with pytest.raises(ValueError, match='template parameters'):
        policy.check_attempt(cfg, path, value)


def test_round_budget_does_not_key_on_rule_name_run_or_revision():
    value = rule()
    assert not checked_budget(value, round_attempts=7, requested_attempts=1,
                                   occupancy=occupancy())['pause_after_consumption']
    assert checked_budget(value, round_attempts=8, requested_attempts=1,
                               occupancy=occupancy())['pause_after_consumption']
    value['plan_sha256'] = 'c' * 64
    value['quote'] = '修订计划仍保留本轮消费'
    with pytest.raises(ValueError, match='90%'):
        checked_budget(value, round_attempts=9, requested_attempts=1, occupancy=occupancy())
    with pytest.raises(ValueError, match='90%'):
        checked_budget(value, round_attempts=8, requested_attempts=2,
                            occupancy=occupancy(requested_jobs=2))


@pytest.mark.parametrize('used,requested', [(10, 1), (9, 2), (0, 11), (True, 1), (1, False)])
def test_invalid_attempt_consumption(used, requested):
    with pytest.raises(ValueError):
        checked_budget(rule(), round_attempts=used, requested_attempts=requested,
                            occupancy=occupancy(requested_jobs=requested))


@pytest.mark.parametrize('changes', [dict(committed_cores=25), dict(queued_cores=9, committed_cores=9),
    dict(jobs=4), dict(jobs=True), dict(committed_cores=float('nan')),
    dict(queued_cores=1), dict(requested_jobs=2)])
def test_account_refusals(changes):
    with pytest.raises(ValueError):
        checked_budget(rule(), round_attempts=0, requested_attempts=1, occupancy=occupancy(**changes))


def test_shared_entry_minimum_and_no_duplicate_groups():
    value = rule()
    value['clusters']['peer'] = {**value['clusters']['default'], 'max_jobs': 2}
    group = occupancy(clusters=['default', 'peer', 'peer'], jobs=2)
    with pytest.raises(ValueError, match='max_jobs'):
        checked_budget(value, round_attempts=0, requested_attempts=1, occupancy=group)
    with pytest.raises(ValueError, match='more than once'):
        checked_budget(value, round_attempts=0, requested_attempts=2, occupancy=occupancy() * 2)


@pytest.mark.parametrize('functional', ['OPBE', 'OLYP', 'O3LYP'])
def test_restricted_o_functionals_not_misread_as_ro(cfg, tmp_path, functional):
    path, _ = make(cfg, tmp_path, ROUTE.replace('B3LYP', functional))
    data = rule(cfg)
    data['methods']['gaussian'][0]['method'] = 'r' + functional.lower()
    assert policy.check_attempt(cfg, path, data)['method_verified']


def test_explicit_basis_type(cfg, tmp_path):
    path, _ = make(cfg, tmp_path, ROUTE + ' 5D 7F')
    data = rule(cfg)
    data['methods']['gaussian'][0]['basis_function_type'] = '5D 7F'
    assert policy.check_attempt(cfg, path, data)['method_verified']


@pytest.mark.parametrize('template,params', [('crest', {}), ('crest', {'--gfn2': True}),
    ('xtb', {}), ('xtb', {'--gfn': '1'}), ('xtb', {'--gfn': '2', '--extra': ''})])
def test_bad_non_gaussian_method(template, params):
    data = rule()
    data['templates'] = [template]
    data['methods'] = {template: [{'parameters': params}]}
    with pytest.raises(ValueError):
        policy.validate_policy(data)


@pytest.mark.parametrize('extra', ['EmpiricalDispersion(GD3BJ)', 'Em(GD3BJ)',
    'EmpiricalDispersion', 'SCF=(Conver=4)/foo', '5D=foo'])
def test_unparsed_method_options_never_claim_verified(cfg, tmp_path, extra):
    path, _ = make(cfg, tmp_path, ROUTE.replace(' SCF=(XQC,Conver=8)', '') + ' ' + extra)
    with pytest.raises(ValueError):
        policy.check_attempt(cfg, path, rule(cfg))


@pytest.mark.parametrize('keyword', ['Opt=Loose(Tight)', 'SCF=Conver=4(Tight)',
    'SCF=Loose(Tight)', 'Freq=', 'Freq=()', 'Opt=(Tight', 'SCF=Tight)'])
def test_malformed_route_options_fail_closed(cfg, tmp_path, keyword):
    path, _ = make(cfg, tmp_path, '# B3LYP/6-31G(d) Int=UltraFine ' + keyword)
    with pytest.raises(ValueError):
        policy.check_attempt(cfg, path, rule(cfg))


@pytest.mark.parametrize('cores,jobs', [(1, 2), (9, 1)])
def test_requested_cores_cannot_contradict_jobs(cores, jobs):
    with pytest.raises(ValueError, match='per-job'):
        checked_budget(rule(), round_attempts=0, requested_attempts=jobs,
                            occupancy=occupancy(requested_cores=cores, requested_jobs=jobs))


def plan_spec(value=None):
    value = value or rule()
    return dict(method_policy='Human explanation is not machine authorization',
                submission_policy={key: deepcopy(value[key]) for key in policy.PLAN_BOUND_KEYS},
                attempt_limit=value['max_attempts'],
                valid_until=approval.timestamp(value['expires_at']).timestamp())


def test_plan_bounds_exact_match_and_no_mutation():
    value = rule()
    value['clusters']['default']['nodes'] = ['node-a', 'node-a']
    spec = plan_spec(value)
    before = deepcopy(spec)
    assert policy.check_plan_bounds(value, spec) is None
    assert spec == before
    assert policy.validate_plan_bounds(spec['submission_policy']) == spec['submission_policy']
    # The validation result cannot mutate the immutable plan bytes through a
    # shared nested dictionary reference.
    copy = policy.validate_plan_bounds(spec['submission_policy'])
    copy['clusters']['default']['max_jobs'] = 1
    assert spec == before


@pytest.mark.parametrize('key', sorted(policy.PLAN_BOUND_KEYS))
def test_plan_bounds_missing_field(key):
    spec = plan_spec()
    del spec['submission_policy'][key]
    with pytest.raises(ValueError, match='plan submission policy'):
        policy.check_plan_bounds(rule(), spec)


@pytest.mark.parametrize('key', ['round_id', 'plan_sha256', 'study_id', 'quote',
                                  'set_at', 'expires_at', 'max_attempts', 'unknown'])
def test_plan_bounds_do_not_accept_context_or_duplicate_limits(key):
    bounds = plan_spec()['submission_policy']
    bounds[key] = 'unbound'
    with pytest.raises(ValueError, match='plan submission policy'):
        policy.validate_plan_bounds(bounds)


@pytest.mark.parametrize('spec', [None, {}, {'method_policy': 'allow all'},
    {'method_policy': json.dumps(rule())}])
def test_old_text_plan_cannot_supply_machine_authority(spec):
    with pytest.raises(ValueError, match='machine-readable'):
        policy.check_plan_bounds(rule(), spec)


@pytest.mark.parametrize('key,value', [('attempt_limit', True), ('attempt_limit', 0),
    ('attempt_limit', 1.5), ('valid_until', True), ('valid_until', float('nan')),
    ('valid_until', float('inf')), ('valid_until', 0), ('valid_until', '2030-01-01')])
def test_plan_existing_limits_are_strict(key, value):
    spec = plan_spec()
    spec[key] = value
    with pytest.raises(ValueError):
        policy.check_plan_bounds(rule(), spec)


def test_rule_can_narrow_all_plan_bounds():
    value = rule()
    value['clusters']['default']['nodes'] = ['node-a']
    spec = plan_spec(value)
    bounds = spec['submission_policy']
    bounds['templates'].append('xtb')
    bounds['methods']['xtb'] = [{'parameters': {'--gfn': '2'}}]
    bounds['clusters']['default'] = dict(nodes=['node-a', 'node-b'],
        max_committed_cores=64, max_queued_cores=32, max_jobs=8)
    bounds['clusters']['other'] = deepcopy(bounds['clusters']['default'])
    bounds['max_cores_per_job'] = 16
    bounds['max_walltime'] = '02:00:00'
    bounds['allow_relaxed'] = True
    bounds['methods']['gaussian'][0]['opt_convergence'] = 'normal'
    bounds['methods']['gaussian'].append({**bounds['methods']['gaussian'][0], 'basis': '6-31+g(d)'})
    value['methods']['gaussian'][0]['scf_convergence'] = 9
    spec['attempt_limit'] = 20
    spec['valid_until'] += 3600
    policy.check_plan_bounds(value, spec)


@pytest.mark.parametrize('key,value', [('max_cores_per_job', 12), ('max_walltime', '02:00:00'),
    ('max_attempts', 11), ('expires_at', '2026-10-31T00:00:00+00:00'),
    ('routing_sha256', 'c' * 64), ('allow_relaxed', True)])
def test_rule_cannot_widen_top_plan_bounds(key, value):
    spec = plan_spec()
    changed = rule()
    changed[key] = value
    policy.validate_policy(changed)
    with pytest.raises(ValueError, match='plan'):
        policy.check_plan_bounds(changed, spec)


@pytest.mark.parametrize('added', ['template', 'cluster'])
def test_rule_cannot_add_plan_destination_or_program(added):
    value = rule()
    spec = plan_spec(value)
    if added == 'template':
        value['templates'].append('xtb')
        value['methods']['xtb'] = [{'parameters': {'--gfn': '2'}}]
    else:
        value['clusters']['other'] = deepcopy(value['clusters']['default'])
    with pytest.raises(ValueError, match='outside plan'):
        policy.check_plan_bounds(value, spec)


@pytest.mark.parametrize('key,value', [('max_committed_cores', 64),
    ('max_queued_cores', 24), ('max_jobs', 5)])
def test_rule_cannot_widen_cluster_limits(key, value):
    spec = plan_spec()
    changed = rule()
    changed['clusters']['default'][key] = value
    policy.validate_policy(changed)
    with pytest.raises(ValueError, match='Rule exceeds plan ' + key):
        policy.check_plan_bounds(changed, spec)


@pytest.mark.parametrize('planned,allowed', [([], ['node-a']), (['node-a'], []),
    (['node-a'], ['node-b']), (['node-a'], ['node-a', 'node-b'])])
def test_rule_node_scope_cannot_change_targeting_class(planned, allowed):
    value = rule()
    value['clusters']['default']['nodes'] = allowed
    spec = plan_spec()
    spec['submission_policy']['clusters']['default']['nodes'] = planned
    with pytest.raises(ValueError, match='node scope'):
        policy.check_plan_bounds(value, spec)


@pytest.mark.parametrize('changes', [dict(method='rpbe0'), dict(basis='6-31+g(d)'),
    dict(basis_function_type='5D 7F'), dict(dispersion='gd3bj'),
    dict(solvent_model='smd', solvent='water'), dict(integration_grid='finegrid')])
def test_rule_method_and_grid_must_match_a_whole_plan_entry(changes):
    value = rule()
    spec = plan_spec(value)
    value['methods']['gaussian'][0].update(changes)
    policy.validate_policy(value)
    with pytest.raises(ValueError, match='method/grid/convergence'):
        policy.check_plan_bounds(value, spec)


@pytest.mark.parametrize('floor,value', [('opt_convergence', 'verytight'), ('scf_convergence', 9)])
def test_rule_cannot_weaken_plan_convergence(floor, value):
    spec = plan_spec()
    spec['submission_policy']['methods']['gaussian'][0][floor] = value
    with pytest.raises(ValueError, match='method/grid/convergence'):
        policy.check_plan_bounds(rule(), spec)


def test_rule_cannot_combine_weakest_floors_from_different_plan_entries():
    value = rule()
    value['methods']['gaussian'][0]['opt_convergence'] = 'normal'
    spec = plan_spec(value)
    method = spec['submission_policy']['methods']['gaussian'][0]
    spec['submission_policy']['methods']['gaussian'] = [
        {**method, 'opt_convergence': 'normal', 'scf_convergence': 10},
        {**method, 'opt_convergence': 'tight', 'scf_convergence': 8},
    ]
    with pytest.raises(ValueError, match='method/grid/convergence'):
        policy.check_plan_bounds(value, spec)
    value['methods']['gaussian'][0]['scf_convergence'] = 10
    policy.check_plan_bounds(value, spec)


@pytest.mark.parametrize('template,params', [('xtb', {'--gfn': '2'}), ('crest', {'--gfn2': ''})])
def test_rule_non_gaussian_parameters_must_match_plan(template, params):
    value = rule()
    value['templates'] = [template]
    value['methods'] = {template: [{'parameters': params}]}
    spec = plan_spec(value)
    policy.check_plan_bounds(value, spec)
    value['methods'][template][0]['parameters'] = {**params, '--alpb': 'water'}
    with pytest.raises(ValueError, match='parameters are outside plan'):
        policy.check_plan_bounds(value, spec)


@pytest.mark.parametrize('extra', ['Pop=Full', 'Population=Minimal', 'GFPrint',
    'GFInput', 'GFInput=AONormalization', 'Density=Current', 'Density=SCF',
    'Pop=Full GFInput Density=Current'])
def test_printing_options_keep_normal_method_verification(cfg, tmp_path, extra):
    path, _ = make(cfg, tmp_path, ROUTE + ' ' + extra)
    assert policy.check_attempt(cfg, path, rule(cfg))['method_verified']


@pytest.mark.parametrize('extra', ['Density=Checkpoint', 'Density=Check', 'Pop=NBORead'])
def test_analysis_options_that_inherit_or_read_unverified_settings_refuse(cfg, tmp_path, extra):
    path, _ = make(cfg, tmp_path, ROUTE + ' ' + extra)
    with pytest.raises(ValueError):
        policy.check_attempt(cfg, path, rule(cfg))


def test_heterogeneous_entry_caps_do_not_shrink_global_ceiling(cfg, tmp_path):
    value = rule(cfg)
    value['max_cores_per_job'] = 32
    value['clusters']['other'] = dict(nodes=[], max_committed_cores=64,
                                      max_queued_cores=32, max_jobs=2)
    policy.validate_policy(value)
    path, _ = make(cfg, tmp_path)
    assert policy.check_attempt(cfg, path, value)['method_verified']
    value['clusters']['default']['max_queued_cores'] = 4
    with pytest.raises(ValueError, match='target policy capacity'):
        policy.check_attempt(cfg, path, value)


def test_multiwfn_checked_by_its_actual_template_parameters(cfg, tmp_path):
    from test_multiwfn_template import prepare_nci
    study.init(cfg, 'smoke')
    cfg['programs']['multiwfn'] = str(tmp_path / 'Multiwfn')
    path, manifest = prepare_nci(cfg, tmp_path)
    value = rule(cfg)
    value['templates'] = ['multiwfn']
    value['methods'] = {'multiwfn': [{'parameters': {'--analysis': 'igm', '--grid': 'medium'}}]}
    result = policy.check_attempt(cfg, path, value)
    assert result['method'] == {'parameters': manifest['template_params']}
    assert 'basis' not in result['method']
    value['methods']['multiwfn'][0]['parameters']['--grid'] = 'low'
    with pytest.raises(ValueError, match='template parameters'):
        policy.check_attempt(cfg, path, value)


def test_gaussian_cp_retains_its_gas_phase_fragment_boundary(cfg, tmp_path):
    from test_counterpoise import WATER, CSV
    study.init(cfg, 'smoke')
    source = tmp_path / 'cp.gjf'
    source.write_text('%nprocshared=8\n%mem=10GB\n# B3LYP/6-31G(d) Counterpoise=2 SP Int=UltraFine SCF=(Conver=8)\n\nWater pair\n\n0 1\n' + WATER + '\n\n')
    fragments = tmp_path / 'cp.csv'
    fragments.write_text(CSV)
    manifest = attempt.prepare(cfg, study_name='smoke', template='gaussian-cp', input_path=source,
        tier='simple', walltime='00:30:00', label='cp', method_basis='合成水二聚体验证', fragments=fragments)
    path = attempt.find(cfg, manifest['attempt_id'])
    value = rule(cfg)
    value['templates'] = ['gaussian-cp']
    value['methods'] = {'gaussian-cp': value['methods']['gaussian']}
    assert policy.check_attempt(cfg, path, value)['method_verified']
    input_path = path / 'inputs' / 'cp.gjf'
    input_path.write_text(input_path.read_text().replace('Fragment=1', 'Fragment=2'))
    with pytest.raises(ValueError, match='bundle'):
        policy.check_attempt(cfg, path, value)


def checked_budget(value, **kwargs):
    return policy.check_budget(value, plan_spec=kwargs.pop('plan_spec', plan_spec(value)), **kwargs)


def test_counterpoise_cannot_use_ordinary_gaussian_policy(cfg, tmp_path):
    path, _ = make(cfg, tmp_path, ROUTE.replace('Opt=Tight Freq', 'Counterpoise=2 SP'))
    with pytest.raises(ValueError, match='gaussian-cp fragment'):
        policy.check_attempt(cfg, path, rule(cfg))


def test_removed_peer_keeps_plan_shared_account_ceiling():
    planned = rule()
    planned['clusters']['peer'] = dict(nodes=[], max_committed_cores=8,
                                      max_queued_cores=8, max_jobs=1)
    value = deepcopy(planned)
    del value['clusters']['peer']
    policy.check_plan_bounds(value, plan_spec(planned))
    with pytest.raises(ValueError, match='Shared-account'):
        checked_budget(value, plan_spec=plan_spec(planned), round_attempts=0,
            requested_attempts=2, occupancy=occupancy(clusters=['default', 'peer'],
                                                     requested_cores=16, requested_jobs=2))


def test_same_named_study_in_another_root_cannot_reuse_policy(cfg, tmp_path):
    import shutil
    from ag.autonomy_submission import study_identity
    path, _ = make(cfg, tmp_path)
    original_policy = rule(cfg)
    assert original_policy['study_key'] == study_identity(path.parent.parent)['study_key']
    other_root = tmp_path / 'other-studies'
    copied = other_root / 'smoke'
    shutil.copytree(path.parent.parent, copied)
    other_cfg = deepcopy(cfg)
    other_cfg['local']['studies_root'] = str(other_root)
    copied_attempt = copied / 'attempts' / path.name
    with pytest.raises(ValueError, match='study directory identity'):
        policy.check_attempt(other_cfg, copied_attempt, original_policy)
    assert policy.check_attempt(other_cfg, copied_attempt, rule(other_cfg))['method_verified']


@pytest.mark.parametrize('level', ['study', 'ancestor'])
def test_study_key_is_never_computed_by_following_symlinks(cfg, tmp_path, level):
    path, _ = make(cfg, tmp_path)
    other_cfg = deepcopy(cfg)
    alias = tmp_path / 'alias-studies'
    if level == 'study':
        alias.mkdir()
        (alias / 'smoke').symlink_to(path.parent.parent, target_is_directory=True)
    else:
        alias.symlink_to(path.parent.parent.parent, target_is_directory=True)
    other_cfg['local']['studies_root'] = str(alias)
    aliased_attempt = alias / 'smoke' / 'attempts' / path.name
    before = (path / 'manifest.json').read_bytes()
    with pytest.raises((ValueError, OSError)):
        policy.check_attempt(other_cfg, aliased_attempt, rule(other_cfg))
    assert (path / 'manifest.json').read_bytes() == before


@pytest.mark.parametrize('route_text', [
    '# HF/Gen Opt=Loose Freq SCF=(Conver=8)',
    '# HF/Gen Opt=Tight Freq SCF=(Conver=6)',
])
def test_relaxed_input_cannot_skip_convergence_floor(cfg, tmp_path, route_text):
    if not hasattr(attempt, 'prepared_bundle'):
        pytest.skip('Requires reviewed T188 combination')
    study.init(cfg, 'smoke')
    source = tmp_path / 'relaxed.gjf'
    source.write_text(INPUT.replace('# B3LYP/6-31G(d) SP', route_text) + 'O H 0\nSTO-3G\n****\n')
    manifest = attempt.prepare(cfg, study_name='smoke', template='gaussian', input_path=source,
        tier='simple', walltime='00:30:00', label='relaxed', method_basis='Synthetic validation', relaxed_input=True)
    value = rule(cfg)
    value['allow_relaxed'] = True
    with pytest.raises(ValueError, match='convergence'):
        policy.check_attempt(cfg, attempt.find(cfg, manifest['attempt_id']), value)


def test_relaxed_input_valid_convergence_stays_method_unverified(cfg, tmp_path):
    if not hasattr(attempt, 'prepared_bundle'):
        pytest.skip('Requires reviewed T188 combination')
    study.init(cfg, 'smoke')
    source = tmp_path / 'relaxed.gjf'
    source.write_text(INPUT.replace('# B3LYP/6-31G(d) SP', '# HF/Gen Opt=Tight Freq SCF=(Conver=8)')
                      + 'O H 0\nSTO-3G\n****\n')
    manifest = attempt.prepare(cfg, study_name='smoke', template='gaussian', input_path=source,
        tier='simple', walltime='00:30:00', label='relaxed', method_basis='Synthetic validation', relaxed_input=True)
    value = rule(cfg)
    value['allow_relaxed'] = True
    checked = policy.check_attempt(cfg, attempt.find(cfg, manifest['attempt_id']), value)
    assert checked['method_verified'] is False and checked['method'] is None


def relaxed_convergence_case(cfg, tmp_path, text):
    if not hasattr(attempt, 'prepared_bundle'):
        pytest.skip('Requires reviewed T188 combination')
    study.init(cfg, 'smoke')
    source = tmp_path / 'relaxed.gjf'
    source.write_text(text)
    manifest = attempt.prepare(cfg, study_name='smoke', template='gaussian', input_path=source,
        tier='simple', walltime='00:30:00', label='relaxed', method_basis='Synthetic validation', relaxed_input=True)
    value = rule(cfg)
    value['allow_relaxed'] = True
    stricter = dict(value['methods']['gaussian'][0], method='rhf', basis='sto-3g',
                    integration_grid='program_default', opt_convergence='verytight', scf_convergence=10)
    value['methods']['gaussian'].append(stricter)
    return attempt.find(cfg, manifest['attempt_id']), value


@pytest.mark.parametrize('route_text', [
    '# HF/STO-3G Opt=Tight Freq SCF=(Conver=10)',
    '# HF/STO-3G Opt=VeryTight Freq SCF=(Conver=8)',
])
def test_relaxed_unverified_method_cannot_choose_weaker_candidate_floor(cfg, tmp_path, route_text):
    path, value = relaxed_convergence_case(cfg, tmp_path,
        INPUT.replace('# B3LYP/6-31G(d) SP', route_text))
    with pytest.raises(ValueError, match='convergence'):
        policy.check_attempt(cfg, path, value)


@pytest.mark.parametrize('second_route', [
    '# HF/STO-3G Opt=Loose Freq SCF=(Conver=10)',
    '# HF/STO-3G Opt=VeryTight Freq SCF=(Conver=6)',
])
def test_relaxed_later_link1_section_cannot_lower_convergence(cfg, tmp_path, second_route):
    first = INPUT.replace('# B3LYP/6-31G(d) SP', '# HF/STO-3G Opt=VeryTight Freq SCF=(Conver=10)')
    second = INPUT.replace('# B3LYP/6-31G(d) SP', second_route)
    path, value = relaxed_convergence_case(cfg, tmp_path, first + '--Link1--\n' + second)
    with pytest.raises(ValueError, match='convergence'):
        policy.check_attempt(cfg, path, value)


def test_relaxed_strictest_candidate_floor_does_not_verify_method(cfg, tmp_path):
    section = INPUT.replace('# B3LYP/6-31G(d) SP', '# HF/STO-3G Opt=VeryTight Freq SCF=(Conver=10)')
    path, value = relaxed_convergence_case(cfg, tmp_path, section + '--Link1--\n' + section)
    checked = policy.check_attempt(cfg, path, value)
    assert checked['method_verified'] is False and checked['method'] is None
