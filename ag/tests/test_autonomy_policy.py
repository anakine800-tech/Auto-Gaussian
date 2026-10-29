"""T186 pure rule checks. No leases, routing authorization or live transport."""
from copy import deepcopy
from datetime import datetime, timezone
import json

import pytest

from ag import approval, attempt, autonomy_policy as policy, config, study, submit
from test_core import cfg, prepared, Fake, INPUT
from test_approval import policy as manual_policy

NOW = datetime(2026, 10, 29, tzinfo=timezone.utc)
ROUTE = '# B3LYP/6-31G(d) Opt=Tight Freq Int=UltraFine SCF=(XQC,Conver=8)'


def rule():
    return dict(schema=policy.SCHEMA, study_id='smoke', round_id='round-1',
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
    return {k: value[k] for k in ('study_id', 'round_id', 'plan_sha256', 'routing_sha256')}


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
    value = rule()
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
    value = rule()
    del value[field]
    cfg['approval'] = {'autonomous_policies': {'bounded': value}}
    with pytest.raises(config.ConfigError):
        config.validate_approval(cfg)


@pytest.mark.parametrize('key,value', [
    ('schema', 'ag-approval/1'), ('study_id', '*'), ('round_id', ' '),
    ('plan_sha256', 'a' * 63), ('routing_sha256', 'x' * 64),
    ('templates', []), ('templates', ['gaussian', 'gaussian']),
    ('templates', ['gaussian*']), ('templates', ['multiwfn']),
    ('max_cores_per_job', True), ('max_cores_per_job', 17),
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
    ('nodes', ['node-a', 'node-a']), ('max_committed_cores', 8),
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


@pytest.mark.parametrize('key', ['study_id', 'round_id', 'plan_sha256', 'routing_sha256'])
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
    cfg['approval'] = {'autonomous_policies': {'bounded': rule()}}
    fake = Fake(cfg)
    with pytest.raises(ValueError, match='policy does not exist'):
        submit.submit(cfg, [path.name], fake, policy_name='bounded')
    assert not fake.calls
    assert not (path / '.submit-claim').exists()


@pytest.mark.parametrize('route', [ROUTE,
    ROUTE.replace('Opt=Tight', 'Opt=(VeryTight,CalcFC,MaxCycles=100)'),
    ROUTE.replace('SCF=(XQC,Conver=8)', 'SCF=(QC,Conver=9,MaxCycle=200)'),
    ROUTE.replace('Opt=Tight', 'Opt(Tight)'),
    ROUTE.replace('Int=UltraFine', 'Integral=(UltraFine)'),
])
def test_frozen_method_and_allowed_adjustments(cfg, tmp_path, route):
    path, manifest = make(cfg, tmp_path, route)
    before = (path / 'manifest.json').read_bytes()
    result = policy.check_attempt(cfg, path, rule())
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
        policy.check_attempt(cfg, path, rule())
    assert not (path / '.submit-claim').exists()


def test_input_bytes_not_model_route(cfg, tmp_path):
    path, _ = make(cfg, tmp_path)
    file = path / 'inputs' / 'autonomy-water.gjf'
    file.write_text(file.read_text().replace('B3LYP', 'PBE0'))
    with pytest.raises(ValueError, match='bundle'):
        policy.check_attempt(cfg, path, rule())


@pytest.mark.parametrize('marker', [None, 'relaxed_input', 'allow_relaxed', 'skipped_checks'])
def test_allow_relaxed_is_not_a_bypass(cfg, tmp_path, marker):
    path, _ = make(cfg, tmp_path, ROUTE.replace('B3LYP', 'PBE0'))
    value = rule()
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
    data = rule()
    if key == 'clusters':
        value = {'other': data['clusters']['default']}
    elif key == 'templates':
        data['methods'] = {'xtb': [{'parameters': {'--gfn': '2'}}]}
    data[key] = value
    with pytest.raises(ValueError):
        policy.check_attempt(cfg, path, data)


def test_node_list_not_wildcard(cfg, tmp_path):
    path, _ = make(cfg, tmp_path)
    value = rule()
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
    value = rule()
    value['templates'] = [template]
    value['methods'] = {template: [{'parameters': params}]}
    assert policy.check_attempt(cfg, path, value)['method'] == {'parameters': params}
    value['methods'][template][0]['parameters'] = {**params, '--chrg': '1'}
    with pytest.raises(ValueError, match='template parameters'):
        policy.check_attempt(cfg, path, value)


def test_round_budget_does_not_key_on_rule_name_run_or_revision():
    value = rule()
    assert not policy.check_budget(value, round_attempts=7, requested_attempts=1,
                                   occupancy=occupancy())['pause_after_consumption']
    assert policy.check_budget(value, round_attempts=8, requested_attempts=1,
                               occupancy=occupancy())['pause_after_consumption']
    value['plan_sha256'] = 'c' * 64
    value['quote'] = '修订计划仍保留本轮消费'
    with pytest.raises(ValueError, match='90%'):
        policy.check_budget(value, round_attempts=9, requested_attempts=1, occupancy=occupancy())
    with pytest.raises(ValueError, match='90%'):
        policy.check_budget(value, round_attempts=8, requested_attempts=2,
                            occupancy=occupancy(requested_jobs=2))


@pytest.mark.parametrize('used,requested', [(10, 1), (9, 2), (0, 11), (True, 1), (1, False)])
def test_invalid_attempt_consumption(used, requested):
    with pytest.raises(ValueError):
        policy.check_budget(rule(), round_attempts=used, requested_attempts=requested,
                            occupancy=occupancy(requested_jobs=requested))


@pytest.mark.parametrize('changes', [dict(committed_cores=25), dict(queued_cores=9, committed_cores=9),
    dict(jobs=4), dict(jobs=True), dict(committed_cores=float('nan')),
    dict(queued_cores=1), dict(requested_jobs=2), dict(clusters=['default', 'default'])])
def test_account_refusals(changes):
    with pytest.raises(ValueError):
        policy.check_budget(rule(), round_attempts=0, requested_attempts=1, occupancy=occupancy(**changes))


def test_shared_entry_minimum_and_no_duplicate_groups():
    value = rule()
    value['clusters']['peer'] = {**value['clusters']['default'], 'max_jobs': 2}
    group = occupancy(clusters=['default', 'peer'], jobs=2)
    with pytest.raises(ValueError, match='max_jobs'):
        policy.check_budget(value, round_attempts=0, requested_attempts=1, occupancy=group)
    with pytest.raises(ValueError, match='more than once'):
        policy.check_budget(value, round_attempts=0, requested_attempts=2, occupancy=occupancy() * 2)


@pytest.mark.parametrize('functional', ['OPBE', 'OLYP', 'O3LYP'])
def test_restricted_o_functionals_not_misread_as_ro(cfg, tmp_path, functional):
    path, _ = make(cfg, tmp_path, ROUTE.replace('B3LYP', functional))
    data = rule()
    data['methods']['gaussian'][0]['method'] = 'r' + functional.lower()
    assert policy.check_attempt(cfg, path, data)['method_verified']


def test_explicit_basis_type(cfg, tmp_path):
    path, _ = make(cfg, tmp_path, ROUTE + ' 5D 7F')
    data = rule()
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
        policy.check_attempt(cfg, path, rule())


@pytest.mark.parametrize('keyword', ['Opt=Loose(Tight)', 'SCF=Conver=4(Tight)',
    'SCF=Loose(Tight)', 'Freq=', 'Freq=()', 'Opt=(Tight', 'SCF=Tight)'])
def test_malformed_route_options_fail_closed(cfg, tmp_path, keyword):
    path, _ = make(cfg, tmp_path, '# B3LYP/6-31G(d) Int=UltraFine ' + keyword)
    with pytest.raises(ValueError):
        policy.check_attempt(cfg, path, rule())


@pytest.mark.parametrize('cores,jobs', [(1, 2), (9, 1)])
def test_requested_cores_cannot_contradict_jobs(cores, jobs):
    with pytest.raises(ValueError, match='per-job'):
        policy.check_budget(rule(), round_attempts=0, requested_attempts=jobs,
                            occupancy=occupancy(requested_cores=cores, requested_jobs=jobs))
