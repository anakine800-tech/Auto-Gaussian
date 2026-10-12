"""Pinned immutable dual-population persistence; never compute populations here."""
from contextlib import ExitStack
from dataclasses import dataclass
from hashlib import sha256

from auto_g16.thermochemistry.models import _identified_payload, _freeze_mapping
from auto_g16.thermochemistry._service import _closed, _finite, _require, _text
from auto_g16.transport._program_rtwin import _PublisherFileBinding
from . import thermochemistry_readonly as pair_owner

_SCHEMA = 'auto-g16-native-populations-artifact/1'
_PAYLOAD_SCHEMA = 'auto-g16-native-populations/1'
_REGISTRATION = 'auto-g16-native-populations-readout-registration/1'
_IMPLEMENTATION = 'auto-g16-native-dual-population/1'
_TOLERANCE = 1e-12
_SCHEMES = {'rrho', 'qrrho'}
_NUMBERS = {'gibbs_free_energy_hartree', 'delta_g_hartree', 'delta_g_kcal_per_mol',
            'log_relative_weight', 'normalized_population'}
_PAIR_FIELDS = {'temperature_k', 'standard_state', 'standard_state_binding', 'gas_constant_binding',
    'thermochemistry_policy_id', 'thermochemistry_policy_payload_sha256', 'functional_kernel_implementation_id'}
_PAYLOAD_KEYS = _PAIR_FIELDS | {'schema', 'source_pair_sha256', 'conformer_ensemble_id',
    'conformer_ensemble_payload_sha256', 'thermodynamic_ensemble_id', 'thermodynamic_ensemble_payload_sha256',
    'reference_member_id', 'source_member_ids', 'hartree_to_kcal_per_mol', 'population_implementation_id',
    'degeneracy_excludes_rotational_symmetry', 'coverage_scope', 'members', 'normalization'}
_MEMBER_KEYS = {'member_id', 'degeneracy', 'degeneracy_rationale', 'symmetry_rationale',
    'reported_rotational_symmetry_number', 'source_provenance', 'rrho', 'qrrho'}


def _integer(value, label):
    _require(type(value) is int and value > 0, label + ' must be a positive integer')


def _shape(artifact):
    row = _closed(artifact, {'schema', 'artifact_id', 'payload_sha256', 'payload'}, 'population envelope')
    _require(row['schema'] == _SCHEMA, 'unsupported population schema')
    p = _closed(row['payload'], _PAYLOAD_KEYS, 'population payload')
    _require(p['schema'] == _PAYLOAD_SCHEMA and p['population_implementation_id'] == _IMPLEMENTATION
             and p['degeneracy_excludes_rotational_symmetry'] is True, 'population policy differs')
    identity, digest = _identified_payload('native-populations', p)
    _require(row['artifact_id'] == identity and row['payload_sha256'] == digest, 'population identity differs')
    for key in ('source_pair_sha256', 'conformer_ensemble_payload_sha256', 'thermodynamic_ensemble_payload_sha256',
                'thermochemistry_policy_payload_sha256'):
        pair_owner._digest(p[key])
    ids = p['source_member_ids']
    _require(type(ids) in (list, tuple) and len(ids) == 2 and all(type(x) is str for x in ids)
             and len(set(ids)) == 2 and p['reference_member_id'] in ids, 'population member/reference differs')
    for key in ('conformer_ensemble_id', 'thermodynamic_ensemble_id', 'reference_member_id',
                'thermochemistry_policy_id', 'functional_kernel_implementation_id'):
        _text(p[key], key)
    _finite(p['temperature_k'], 'temperature', positive=True)
    _finite(p['hartree_to_kcal_per_mol'], 'conversion', positive=True)
    gas = _closed(p['gas_constant_binding'], {'gas_constant_j_per_mol_k', 'joule_per_hartree_mol',
        'gas_constant_hartree_per_mol_k', 'unit_convention'}, 'gas binding')
    for key in set(gas) - {'unit_convention'}:
        _finite(gas[key], key, positive=True)
    _require(gas['unit_convention'] == 'per_mole_hartree_kelvin', 'gas convention differs')
    _require(p['standard_state'] in ('1atm', '1M'), 'invalid standard state')
    coverage = _closed(p['coverage_scope'], {'kind', 'rationale'}, 'coverage')
    _require(coverage['kind'] == 'frozen_profile_nonexhaustive_scope', 'invalid coverage')
    _text(coverage['rationale'], 'coverage rationale')
    members = p['members']
    _require(type(members) in (list, tuple) and len(members) == 2, 'requires two population members')
    for index, member in enumerate(members):
        m = _closed(member, _MEMBER_KEYS, 'population member')
        _require(m['member_id'] == ids[index], 'member order differs')
        _integer(m['degeneracy'], 'degeneracy')
        _integer(m['reported_rotational_symmetry_number'], 'reported sigma')
        for key in ('degeneracy_rationale', 'symmetry_rationale'):
            _text(m[key], key)
        for scheme in _SCHEMES:
            numbers = _closed(m[scheme], _NUMBERS, 'scheme numbers')
            for value in numbers.values():
                _finite(value, 'scheme number')
            _require(0 <= numbers['normalized_population'] <= 1, 'population outside range')
    norm = _closed(p['normalization'], _SCHEMES, 'normalization')
    for scheme in _SCHEMES:
        item = _closed(norm[scheme], {'population_sum', 'absolute_error', 'numeric_tolerance'}, 'normalization row')
        _finite(item['population_sum'], 'population sum', positive=True)
        _finite(item['absolute_error'], 'normalization error')
        pair_owner._same(item['numeric_tolerance'], _TOLERANCE, 'numeric tolerance')
        _require(0 <= item['absolute_error'] <= _TOLERANCE, 'normalization outside tolerance')
    return p


def _source_payload(pair, source_digest):
    q, t = pair
    request = q.audit_evidence[-1]['request_payload']
    return dict(schema=_PAYLOAD_SCHEMA, source_pair_sha256=source_digest,
        conformer_ensemble_id=q.conformer_ensemble_id, conformer_ensemble_payload_sha256=q.payload_sha256,
        thermodynamic_ensemble_id=t.thermodynamic_ensemble_id, thermodynamic_ensemble_payload_sha256=t.payload_sha256,
        source_member_ids=t.source_member_ids, **{k: getattr(t, k) for k in _PAIR_FIELDS},
        hartree_to_kcal_per_mol=t.gas_constant_binding['joule_per_hartree_mol'] / 4184,
        population_implementation_id=_IMPLEMENTATION, degeneracy_excludes_rotational_symmetry=True,
        coverage_scope=request['coverage_scope'])


def _source_member(row, policy):
    return dict(member_id=row['member_id'], degeneracy=row['degeneracy'],
        degeneracy_rationale=row['degeneracy_rationale'], symmetry_rationale=policy['symmetry_rationale'],
        reported_rotational_symmetry_number=row['source_provenance']['thermo_facts']['rotational_symmetry_number']['value'],
        source_provenance=row['source_provenance'])


def _validate_source(artifact, pair, source_digest):
    p = _shape(artifact)
    expected = _source_payload(pair, source_digest)
    pair_owner._same({k: p[k] for k in expected}, expected, 'population source binding')
    q, t = pair
    policies = q.audit_evidence[-1]['request_payload']['member_policies']
    _require(len(t.source_member_ids) == 2, 'population source must have two members')
    for member, row, policy in zip(p['members'], t.member_observations, policies):
        expected_member = _source_member(row, policy)
        pair_owner._same({k: member[k] for k in expected_member}, expected_member, 'population member source')
        for scheme, source_key in (('rrho', 'raw_rrho'), ('qrrho', 'treated_qrrho')):
            pair_owner._same(member[scheme]['gibbs_free_energy_hartree'],
                             row[source_key]['gibbs_free_energy_hartree'], 'saved Gibbs energy')
        _require(abs(member['qrrho']['normalized_population'] - row['normalized_population']) <= _TOLERANCE,
                 'saved qRRHO population differs')


def encode_native_populations(artifact):
    _shape(artifact)
    raw = pair_owner._canonical(artifact)
    _require(len(raw) <= pair_owner._CAP, 'population artifact exceeds cap')
    return raw


def save_native_populations(readout, *, artifact, expected_sha256, destination):
    raw = encode_native_populations(artifact)
    _require(sha256(raw).hexdigest() == pair_owner._digest(expected_sha256), 'accepted population digest differs')
    candidate = _freeze_mapping(pair_owner._decode(raw, pair_owner._CAP), 'publication snapshot')
    directory = pair_owner._Directory(destination)
    try:
        directory.require_absent('native-populations-' + expected_sha256 + '.json')
        with ExitStack() as pins:
            with pair_owner._replayed_native_pair(readout) as pair:
                _validate_source(candidate, pair, readout.artifact.sha256)
                binding = directory._write_prefixed(raw, expected_sha256, 'native-populations')
                pins.enter_context(pair_owner._pinned(binding))
            directory.check()
        directory.check()
    finally:
        directory.close()
    return binding


@dataclass(frozen=True, kw_only=True)
class NativePopulationReadout:
    thermodynamic_readout: pair_owner.NativeThermodynamicReadout
    artifact: _PublisherFileBinding

    def __post_init__(self):
        _require(type(self.thermodynamic_readout) is pair_owner.NativeThermodynamicReadout
                 and type(self.artifact) is _PublisherFileBinding, 'invalid population registration')

    def read(self):
        with pair_owner._pinned(self.artifact) as pin:
            with pair_owner._replayed_native_pair(self.thermodynamic_readout) as pair:
                artifact = pair_owner._decode(pin.raw, pair_owner._CAP)
                _validate_source(artifact, pair, self.thermodynamic_readout.artifact.sha256)
                result = _freeze_mapping(artifact, 'population artifact')
        return result


def load_native_population_readout(content: bytes, digest: str):
    _require(type(content) is bytes and sha256(content).hexdigest() == pair_owner._digest(digest), 'invalid startup digest')
    data = _closed(pair_owner._decode(content, 1024 * 1024),
                   {'schema', 'thermodynamic_registration', 'artifact'}, 'population startup')
    _require(data['schema'] == _REGISTRATION, 'unsupported population startup schema')
    def binding(value):
        value = _closed(value, pair_owner._BINDING_KEYS, 'startup physical binding')
        _require(type(value['parent_chain']) is list and type(value['file_identity']) is list
                 and all(type(n) is list for n in value['parent_chain']), 'invalid startup physical arrays')
        return _PublisherFileBinding(value['path'], tuple(tuple(n) for n in value['parent_chain']),
            tuple(value['file_identity']), value['sha256'], value['size_bytes'])
    source, artifact = binding(data['thermodynamic_registration']), binding(data['artifact'])
    with pair_owner._pinned(source, 1024 * 1024) as pin:
        thermo = pair_owner.load_native_thermodynamic_readout(pin.raw, source.sha256)
    return NativePopulationReadout(thermodynamic_readout=thermo, artifact=artifact)
