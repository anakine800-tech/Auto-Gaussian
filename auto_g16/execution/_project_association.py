"""Closed associated Project identities. Pure decoding never grants authority."""
from collections.abc import Mapping
from ._identity import ExecutionValueError, freeze_mapping, semantic_id, semantic_sha256

VERSION = 'v31-project-profile-associated-binding/1'
SCHEMA = 'project-profile-association/1'
DOMAIN = 'project-profile-associated-binding/1'
Q7 = 'v31-gaussian-publisher-qualification-v7.json'
Q8 = 'v31-gaussian-publisher-qualification-v8.json'
BOOT = 'v31-gaussian-freq-resource-bootstrap-v4.py'
BINDING_FIELDS = frozenset({'project_physical_binding_id','project_id','provisioning_contract_version',
    'transport_kind','resolved_server_profile_id','resolved_target_identity','provisioning_authority_id','locations'})


def require(ok, message):
    if not ok:
        raise ExecutionValueError('Project association: ' + message)


def closed(value, fields):
    require(isinstance(value, Mapping) and set(value) == set(fields), 'closed fields differ')
    return value


def associated(binding):
    return binding.provisioning_contract_version == VERSION


def decode_binding(data):
    from .project_provisioning import ProjectPhysicalBinding
    require(isinstance(data, Mapping), 'binding must be a mapping')
    fields = BINDING_FIELDS | ({'project_profile_association'} if data.get('provisioning_contract_version') == VERSION else set())
    closed(data, fields)
    binding = object.__new__(ProjectPhysicalBinding)
    data = freeze_mapping(dict(data), 'persisted Project binding')
    for key, item in data.items():
        object.__setattr__(binding, key, item)
    object.__setattr__(binding, '_identity_payload', freeze_mapping({k:v for k,v in data.items() if k != 'project_physical_binding_id'}, 'Project identity'))
    binding.assert_identity_closed()
    return binding


def profile_delta(old, new):
    """Compare full resolved identities, including ordered config digests."""
    old.assert_identity_closed(); new.assert_identity_closed()
    a, b = dict(old._identity_payload), dict(new._identity_payload)
    require(type(new.profile_revision) is int and new.profile_revision > old.profile_revision, 'profile revision')
    ar, br = dict(a.pop('runtime_identities')), dict(b.pop('runtime_identities'))
    a.pop('profile_revision'); b.pop('profile_revision')
    # This derived digest covers revision and runtime as well as configuration.
    # assert_identity_closed above recomputes it; compare all its other inputs.
    a.pop('effective_config_sha256'); b.pop('effective_config_sha256')
    require(a == b, 'target/config/root/runtime policy changed')
    require(Q7 in ar and Q8 not in ar and BOOT not in ar and Q8 in br and Q7 not in br and BOOT in br, 'not Q7 to Q8')
    removed = {Q7:ar.pop(Q7)}; added = {name:br.pop(name) for name in (Q8, BOOT)}
    require(ar == br, 'existing runtime bytes changed')
    from auto_g16.transport._gaussian_freq_submit import source_bytes
    from hashlib import sha256
    raw = source_bytes()
    require(added[BOOT] == {'sha256':sha256(raw).hexdigest(),'size_bytes':len(raw)}, 'Freq bootstrap differs')
    return freeze_mapping({'contract_version':'gaussian-opt-q7-to-freq-q8/1',
        'old_revision':old.profile_revision,'new_revision':new.profile_revision,
        'removed_runtime':removed,'added_runtime':added}, 'profile delta')


def profile_payload(target):
    return freeze_mapping({**target.semantic_payload(),'identity_payload':target._identity_payload}, 'association profile')


def decode_profile(value):
    from .models import ResolvedServerProfile
    fields = {'resolved_server_profile_id','server_profile_id','profile_revision','effective_config_sha256',
        'transport_kind','target_identity','remote_user','remote_root','platform_paths','runtime_identities','identity_payload'}
    closed(value, fields)
    target = ResolvedServerProfile._from_resolved(**{k:v for k,v in value.items() if k != 'identity_payload'}, identity_payload=value['identity_payload'])
    target.assert_identity_closed()
    return target


def runtime_identity(target):
    """Historical identity derivation, without importing or invoking the driver."""
    from auto_g16.transport.program import _identity
    name = BOOT if Q8 in target.runtime_identities else 'v31-gaussian-resource-bootstrap-v3.py'
    return _identity('project-runtime', {'profile':target.resolved_server_profile_id,
        'manifest':target.runtime_identities['transport-deployment-manifest-v3.json']['sha256'],
        'bootstrap':target.runtime_identities[name]['sha256']})


def validate(envelope):
    closed(envelope, {'schema','association_id','payload_sha256','payload'})
    p = closed(envelope['payload'], {'project_id','source','old_profile','new_profile','allowed_delta','observation','issuer'})
    require(envelope['schema'] == SCHEMA and envelope['payload_sha256'] == semantic_sha256(p)
            and envelope['association_id'] == semantic_id(SCHEMA, p), 'proof identity differs')
    source = closed(p['source'], {'journal','intent','creation_result','original_binding'})
    original = decode_binding(source['original_binding'])
    require(not associated(original) and original.project_id == p['project_id'], 'original binding is not creation lineage')
    profiles = []
    for name in ('old_profile','new_profile'):
        row = closed(p[name], {'profile_file','resolved_profile_payload','runtime_authority_id','provisioning_authority_id'})
        target = decode_profile(row['resolved_profile_payload'])
        require(row['runtime_authority_id'] == runtime_identity(target), 'runtime identity differs')
        require(row['provisioning_authority_id'] == semantic_id('project-provisioning-authority', {
            'journal_identity':source['journal']['journal_identity'],'runtime_identity':row['runtime_authority_id']}), 'provisioning identity differs')
        profiles.append(target)
    old, new = profiles
    require(original.resolved_server_profile_id == old.resolved_server_profile_id
            and original.provisioning_authority_id == p['old_profile']['provisioning_authority_id'], 'old authority differs')
    require(profile_delta(old,new) == p['allowed_delta'], 'profile delta differs')
    issuer = closed(p['issuer'], {'owner_schema','source_commit','source_tree','installed_source_manifest','target_runtime_authority_id'})
    require(issuer['owner_schema'] == 'project-profile-association-owner/1'
            and issuer['target_runtime_authority_id'] == runtime_identity(new), 'issuer differs')
    obs = closed(p['observation'], {'request','capture','decoded_result','observed_window'})
    result = closed(obs['decoded_result'], {'state','parent_physical_identity','project_physical_identity'})
    require(result == {'state':'EXISTING','parent_physical_identity':original.parent_physical_identity,
                       'project_physical_identity':original.project_physical_identity}, 'observed physical identity differs')
    return original, new


def binding_payload(envelope):
    original, new = validate(envelope)
    p = dict(original._identity_payload)
    location = dict(original.locations[0])
    location.update(provisioning_disposition='PROFILE_ASSOCIATED', evidence_identity=envelope['association_id'])
    p.update(provisioning_contract_version=VERSION, resolved_server_profile_id=new.resolved_server_profile_id,
        resolved_target_identity=new.target_identity, provisioning_authority_id=envelope['payload']['new_profile']['provisioning_authority_id'],
        locations=(location,), project_profile_association=envelope)
    return freeze_mapping(p, 'associated Project binding')


def make_binding(envelope):
    p = binding_payload(envelope)
    return decode_binding({'project_physical_binding_id':semantic_id(DOMAIN,p), **p})


def assert_binding(binding):
    p = binding_payload(binding.project_profile_association)
    require(p == binding._identity_payload and semantic_id(DOMAIN,p) == binding.project_physical_binding_id, 'associated binding identity differs')
    require(all(getattr(binding,k) == v for k,v in p.items()), 'associated binding attributes differ')
