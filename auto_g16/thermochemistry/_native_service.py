"""Private native normalization; callers must retain complete source replay."""
from auto_g16.conformer.models import ConformerEnsemble
from auto_g16.conformer.refinement import (
    _closed_ensemble, _closed_profile, _sampling_observation_by_member,
    _audit_and_deduplicate,
)
from auto_g16.conformer.service import _association_semantics_complete, _audit_observation
from auto_g16.result._successor import payload_hash
from . import _goodvibes
from ._successor_facts import _METHOD, _SCHEMA, _MINIMUM_KEYS, _FREQUENCY_KEYS
from ._service import (
    _closed, _require, _text, _finite, _normalize_policy, _validate_nonlinear_domain,
    _standard_state_binding, _finish_thermodynamic_ensemble,
)
from .models import _freeze_mapping, _identified_payload

_REQUEST_KEYS = {
    'schema', 'purpose', 'source_ensemble', 'sampling_profile', 'source_member_ids',
    'coverage_scope', 'method_binding', 'thermochemistry_policy', 'member_policies',
}
_OBLIGATIONS = {
    'minimum_observations_met', 'minimum_valid_met', 'maximum_observations_respected',
    'fragment_association_semantics_complete', 'independent_review_resolved',
}
_PRESERVED = (
    'schema_version', 'project_id', 'calculation_plan_id', 'calculation_plan_revision',
    'sampling_profile_id', 'sampling_profile_payload_sha256', 'species_binding',
    'stereochemistry_binding', 'sampling_observations', 'negative_evidence',
    'dedup_decisions', 'independent_review_blockers', 'clusters', 'members', 'coverage',
    'ts_seed_members',
)


def _source_binding(ensemble):
    return {'conformer_ensemble_id': ensemble.conformer_ensemble_id,
            'payload_sha256': ensemble.payload_sha256, 'revision': ensemble.revision}


def _profile_binding(profile):
    return {'sampling_profile_id': profile.sampling_profile_id, 'payload_sha256': profile.payload_sha256}


def _normalize_request(value):
    supplied = dict(_closed(value, _REQUEST_KEYS, 'native thermochemistry request'))
    _require(supplied['schema'] == 'auto-g16-native-thermochemistry-request/1'
             and supplied['purpose'] == 'bounded_workflow_validation', 'native request domain differs')
    source = _closed(supplied['source_ensemble'], {'conformer_ensemble_id', 'payload_sha256', 'revision'}, 'source ensemble')
    _require(type(source['revision']) is int and source['revision'] > 0, 'source revision is not exact')
    for name in ('conformer_ensemble_id', 'payload_sha256'):
        _text(source[name], name)
    profile = _closed(supplied['sampling_profile'], {'sampling_profile_id', 'payload_sha256'}, 'sampling profile')
    for name in profile:
        _text(profile[name], name)
    ids = supplied['source_member_ids']
    _require(type(ids) is tuple and len(ids) == 2, 'native request requires exactly two canonical members')
    for mid in ids:
        _text(mid, 'member_id')
    _require(len(set(ids)) == 2, 'native request member ids repeat')
    scope = _closed(supplied['coverage_scope'], {'kind', 'rationale'}, 'coverage scope')
    _require(scope['kind'] == 'frozen_profile_nonexhaustive_scope', 'unsupported coverage scope')
    _text(scope['rationale'], 'coverage rationale')
    method = _closed(supplied['method_binding'], set(_METHOD), 'native method')
    _require(all(type(method[k]) is type(v) and method[k] == v for k, v in _METHOD.items()), 'native method differs')
    supplied['thermochemistry_policy'] = _normalize_policy(supplied['thermochemistry_policy'])
    policies = supplied['member_policies']
    _require(type(policies) is tuple and len(policies) == 2, 'member policies must cover both members')
    for row, mid in zip(policies, ids):
        row = _closed(row, {'member_id', 'degeneracy', 'degeneracy_rationale', 'symmetry_rationale'}, 'member policy')
        _require(row['member_id'] == mid, 'member policy order differs')
        _require(type(row['degeneracy']) is int and row['degeneracy'] > 0, 'degeneracy must be an exact positive integer')
        _text(row['degeneracy_rationale'], 'degeneracy rationale')
        _text(row['symmetry_rationale'], 'symmetry rationale')
    return _freeze_mapping(supplied, 'native thermochemistry request')


def _check_coverage(source, profile, ids):
    policy = profile.thermodynamic_eligibility_policy
    _require(policy['require_post_dft_minimum'] is True, 'profile requires post-DFT minima')
    coverage = _closed(source.coverage, {
        'status', 'scope', 'global_minimum_claim', 'exhaustive_coverage_claim',
        'obligations', 'observed_count', 'valid_count',
    }, 'native coverage')
    _require(coverage['status'] == 'sufficient' and coverage['status'] in policy['required_coverage_statuses']
             and coverage['scope'] == 'closed-crest-imtd-gc-profile'
             and coverage['global_minimum_claim'] is False and coverage['exhaustive_coverage_claim'] is False,
             'coverage scope/status is unsupported')
    obligations = _closed(coverage['obligations'], _OBLIGATIONS, 'coverage obligations')
    _require(all(value is True for value in obligations.values()), 'coverage obligations are not all true')
    _require(all(type(coverage[k]) is int and coverage[k] == 2 for k in ('observed_count', 'valid_count')),
             'coverage counts must be exact two')
    observations = _sampling_observation_by_member(source)
    _require(len(source.sampling_observations) == 2 and set(observations) == set(ids), 'sampling observation coverage differs')
    _require(all(_audit_observation(profile, observations[mid]).status == 'valid' for mid in ids),
             'sampling identity audit is unresolved')
    budget = profile.crest_imtd_gc_profile['budget']
    _require(budget['minimum_observations'] <= 2 <= budget['maximum_observations']
             and budget['minimum_valid'] <= 2 and _association_semantics_complete(profile)
             and not source.independent_review_blockers, 'profile coverage obligations do not hold')
    rejected, comparisons, blockers, _clusters, _reps, survivors = _audit_and_deduplicate(
        source, profile, observations, {m['member_id']: m['coordinates_angstrom'] for m in source.members},
    )
    _require(not rejected and not blockers and survivors == ids, 'post-DFT identity or deduplication is unresolved')
    _require(all(row in source.dedup_decisions for row in comparisons), 'post-DFT comparisons are not retained')


def _check_member(member, row, request):
    row = _closed(row, {'member_id', 'minimum_authority', 'native_source', 'native_result', 'thermo_facts'}, 'native facts member')
    mid = member['member_id']
    _require(row['member_id'] == mid and member.get('post_dft_status') == 'validated_minimum'
             and member.get('post_dft_minimum_evidence_available') is True
             and member.get('negative_optimization_authority') is None
             and member.get('negative_frequency_authority') is None
             and member.get('post_dft_duplicate_of_member_id') is None, 'native member is not independently eligible')
    minimum = _closed(row['minimum_authority'], _MINIMUM_KEYS, 'native minimum')
    _require(minimum == member.get('two_stage_minimum_authority')
             and minimum['source']['member_id'] == mid
             and minimum['optimization'] == member.get('optimization_geometry_authority'), 'native minimum/member source differs')
    payload = {k: v for k, v in minimum.items() if k != 'two_stage_minimum_authority_id'}
    _require(minimum['authority_schema'] == _SCHEMA
             and minimum['two_stage_minimum_authority_id'] == payload_hash({'domain': _SCHEMA, 'payload': payload})
             and minimum['assessment']['classification'] == 'VALIDATED_TWO_STAGE_MINIMUM', 'native minimum identity differs')
    _require(minimum['method_binding'] == request['method_binding']
             and minimum['method_id'] == payload_hash({'domain': 'v31-successor-stage-independent-method/1', 'method': _METHOD}),
             'native minimum method differs')
    frequency = _closed(minimum['frequency'], _FREQUENCY_KEYS, 'native frequency')
    source = _closed(row['native_source'], {'observation_id', 'payload_sha256'}, 'native source')
    result = _closed(row['native_result'], {'result_id', 'payload_sha256', 'parser_name', 'parser_version', 'result_kind'}, 'native result')
    _require(source == frequency['result_source']
             and {k: result[k] for k in ('result_id', 'payload_sha256')} == frequency['parsed_result']
             and result['parser_name'] == 'auto-g16-v3-gaussian-job' and result['parser_version'] == '1.2.0'
             and result['result_kind'] == 'gaussian-job-facts', 'native frequency source/result differs')
    facts = _closed(row['thermo_facts'], {
        'source_artifact', 'job_section', 'electronic_energy_hartree', 'frequency_blocks', 'frequencies_cm1',
        'molecular_mass_amu', 'rotational_symmetry_number', 'rotational_temperatures_kelvin',
        'point_group_diagnostic', 'gaussian_reported_thermochemistry',
    }, 'native thermo facts')
    values = facts['frequencies_cm1']
    _require(type(values) is tuple and len(values) == 36
             and values == frequency['frequencies_cm1'] and type(frequency['mode_count']) is int
             and frequency['mode_count'] == 36 and facts['frequency_blocks'] == frequency['frequency_blocks'],
             'native frequencies differ')
    for value in values:
        _finite(value, 'native frequency', positive=True)
    _finite(facts['electronic_energy_hartree']['value'], 'native energy')
    _finite(facts['molecular_mass_amu']['value'], 'native mass', positive=True)
    sigma = facts['rotational_symmetry_number']['value']
    _require(type(sigma) is int and sigma > 0, 'native symmetry number is invalid')
    rotations = facts['rotational_temperatures_kelvin']['value']
    _require(type(rotations) is tuple and len(rotations) == 3, 'native rotational temperatures are invalid')
    for value in rotations:
        _finite(value, 'native rotational temperature', positive=True)


def _validate_source(source, profile, native_facts, request):
    _closed_ensemble(source)
    _closed_profile(profile)
    _require(source.sampling_profile_id == profile.sampling_profile_id
             and source.sampling_profile_payload_sha256 == profile.payload_sha256
             and source.species_binding == profile.species_binding
             and source.stereochemistry_binding == profile.stereochemistry_binding, 'source profile differs')
    _require(not source.thermodynamic_eligible_members and not source.ts_seed_members, 'source projection is not empty')
    ids = tuple(m['member_id'] for m in source.members)
    _require(ids == request['source_member_ids'], 'source canonical members differ')
    facts = _closed(native_facts, {'schema', 'source_ensemble', 'sampling_profile', 'members'}, 'native input facts')
    _require(facts['schema'] == 'auto-g16-native-thermo-input-facts/1'
             and facts['source_ensemble'] == request['source_ensemble'] == _source_binding(source)
             and facts['sampling_profile'] == request['sampling_profile'] == _profile_binding(profile),
             'native facts source/profile differs')
    _require(type(facts['members']) is tuple and len(facts['members']) == 2, 'native facts member coverage differs')
    _check_coverage(source, profile, ids)
    for member, row in zip(source.members, facts['members']):
        _validate_nonlinear_domain(source, member)
        _check_member(member, row, request)
    return ids


def _eligibility_audit(request):
    identity, digest = _identified_payload('native-thermochemistry-request', request)
    return {
        'stage': 'native_thermochemistry_eligibility', 'source_ensemble': request['source_ensemble'],
        'sampling_profile': request['sampling_profile'], 'request_id': identity,
        'request_payload_sha256': digest, 'request_payload': request,
        'derived_member_ids': request['source_member_ids'], 'purpose': request['purpose'],
    }


def _qualify_ensemble(source, profile, native_facts, request):
    request = _normalize_request(request)
    ids = _validate_source(source, profile, native_facts, request)
    return ConformerEnsemble._create(
        project_id=source.project_id, calculation_plan_id=source.calculation_plan_id,
        calculation_plan_revision=source.calculation_plan_revision, profile=profile,
        sampling_observations=source.sampling_observations,
        audit_evidence=(*source.audit_evidence, _eligibility_audit(request)),
        negative_evidence=source.negative_evidence, dedup_decisions=source.dedup_decisions,
        independent_review_blockers=source.independent_review_blockers, clusters=source.clusters,
        members=source.members, coverage=source.coverage, thermodynamic_eligible_members=ids,
        ts_seed_members=source.ts_seed_members, revision=source.revision + 1,
        supersedes_conformer_ensemble_id=source.conformer_ensemble_id,
    )


def _native_method(request):
    return _freeze_mapping({
        'schema': 'auto-g16-native-thermochemistry-method/1', 'method': request['method_binding'],
        'minimum_authority_schema': _SCHEMA, 'parser_name': 'auto-g16-v3-gaussian-job',
        'parser_version': '1.2.0', 'energy_source': 'frequency_result_final_scf',
        'symmetry_source': 'gaussian_reported_rotational_symmetry_number',
    }, 'native method compatibility')


def _native_member_binding(qualified, row, member_policy, request):
    """Pure source association shared with persisted-result verification."""
    method = _native_method(request)
    method_id, _ = _identified_payload('native-thermochemistry-method', method)
    request_id, request_hash = _identified_payload('native-thermochemistry-request', request)
    policy = request['thermochemistry_policy']
    return {
        'member_id': row['member_id'], 'source_refined_conformer_ensemble_id': qualified.conformer_ensemble_id,
        'source_refined_conformer_ensemble_revision': qualified.revision,
        'two_stage_minimum_authority_id': row['minimum_authority']['two_stage_minimum_authority_id'],
        'method_compatibility_id': method_id, 'method_compatibility_binding': method,
        'source_provenance': {
            'schema': 'auto-g16-native-thermochemistry-provenance/1', 'source_ensemble': request['source_ensemble'],
            'sampling_profile': request['sampling_profile'], 'native_source': row['native_source'],
            'native_result': row['native_result'], 'minimum_authority': row['minimum_authority'],
            'thermo_facts': row['thermo_facts'], 'request_id': request_id, 'request_payload_sha256': request_hash,
        },
        'temperature_k': policy['temperature_k'], 'standard_state': policy['standard_state'],
        'degeneracy': member_policy['degeneracy'], 'degeneracy_rationale': member_policy['degeneracy_rationale'],
        'inclusion_status': 'included_thermodynamic_eligible',
    }


def _build_native_thermodynamic_ensemble(*, source_ensemble, qualified_ensemble, profile, native_facts, request):
    request = _normalize_request(request)
    ids = _validate_source(source_ensemble, profile, native_facts, request)
    _closed_ensemble(qualified_ensemble)
    _require(qualified_ensemble.revision == source_ensemble.revision + 1
             and qualified_ensemble.supersedes_conformer_ensemble_id == source_ensemble.conformer_ensemble_id
             and all(getattr(qualified_ensemble, key) == getattr(source_ensemble, key) for key in _PRESERVED)
             and qualified_ensemble.audit_evidence == (*source_ensemble.audit_evidence, _eligibility_audit(request))
             and qualified_ensemble.thermodynamic_eligible_members == ids, 'qualified ensemble is not the exact eligibility revision')
    # Every source, request and qualification check above precedes kernel loading or consumption.
    policy = request['thermochemistry_policy']
    _, constants = _goodvibes._load_goodvibes_kernels()
    standard_state = _standard_state_binding(policy, constants['GAS_CONSTANT'])
    normalized = []
    for row, member_policy in zip(native_facts['members'], request['member_policies']):
        facts = row['thermo_facts']
        computed = _goodvibes.functional_thermochemistry(
            electronic_energy_hartree=facts['electronic_energy_hartree']['value'],
            frequencies_cm1=facts['frequencies_cm1'], molecular_mass_amu=facts['molecular_mass_amu']['value'],
            rotational_symmetry_number=facts['rotational_symmetry_number']['value'],
            rotational_temperatures_kelvin=facts['rotational_temperatures_kelvin']['value'],
            temperature_k=policy['temperature_k'], concentration_mol_per_l=standard_state['concentration_mol_per_l'],
            entropy_frequency_cutoff_cm1=policy['entropy_frequency_cutoff_cm1'],
            enthalpy_frequency_cutoff_cm1=policy['enthalpy_frequency_cutoff_cm1'],
            frequency_scaling_factor=policy['frequency_scaling_factor'], zpe_scaling_factor=policy['zpe_scaling_factor'],
        )
        normalized.append({
            **_native_member_binding(qualified_ensemble, row, member_policy, request),
            'raw_rrho': computed['raw_rrho'], 'treated_qrrho': computed['treated_qrrho'],
        })
    return _finish_thermodynamic_ensemble(
        ensemble=qualified_ensemble, policy=policy, standard_state=standard_state,
        normalized_members=normalized, gas_constant=constants['GAS_CONSTANT'], joule_to_au=constants['J_TO_AU'],
    )
