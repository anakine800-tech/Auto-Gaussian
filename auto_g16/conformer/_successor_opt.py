"""Private offline composition of native Gaussian source and Opt member evidence."""
from collections.abc import Mapping
from dataclasses import fields
from math import isfinite
import re

from auto_g16.core import SQLiteRuntimeStore
from auto_g16.execution._gaussian_result_source import gaussian_result_source, reject_legacy_generation
from auto_g16.result._successor import parse_source, require_pair, payload_hash, SOURCE, PARSED
from auto_g16.scientific_validation._successor_opt import assess_opt
from .models import _freeze_mapping
from .refinement_authority import (
    _require, _ensemble_closed, _member, _source, _coordinates_from_geometry,
    _ATOMIC_NUMBER, RefinementAuthorityError,
)

SCHEMA = "v31-conformer-successor-opt-authority/1"
METHOD = {
    "program": "gaussian16", "method": "wB97XD", "basis": "Def2SVP",
    "dispersion": "intrinsic_wB97XD", "solvent": "gas", "reference": "restricted_closed_shell",
    "charge": 0, "multiplicity": 1, "integration_grid": "UltraFine",
    "scf_policy": "Tight_MaxCycle128", "route_contract_version": "auto_g16_v31_successor_opt_route_1",
}
ROUTE = '#p wB97XD/Def2SVP Opt=(MaxCycles=128) SCF=(Tight,MaxCycle=128) Integral=UltraFine NoSymm'


def _record_payload(record):
    return {field.name: getattr(record, field.name) for field in fields(record)}


def _ownership(store, snapshot):
    snapshot._assert_current_core(store)
    attempt = store.load_attempt(snapshot.attempt_id)
    task = store.load_task(attempt.task_id)
    workflow = store.load_workflow_run(task.workflow_run_id)
    records = (store.load_project(workflow.project_id), workflow, task, attempt,
               store.load_calculation_plan(snapshot.calculation_plan_id),
               store.load_resource_spec(snapshot.resolved_resource_request.resource_spec_id))
    return tuple(_record_payload(record) for record in records) + (
        None if task.batch_id is None else _record_payload(store.load_batch(task.batch_id)),
        store.load_submission_intent(snapshot.attempt_id),
    )


def _same_destination(source, destination, snapshot):
    _require(type(destination) is SQLiteRuntimeStore, 'destination must be the native Core store')
    _require(destination is not source and destination._connection is not source._connection,
             'source cannot be its own destination')
    _require(_ownership(source, snapshot) == _ownership(destination, snapshot),
             'destination full Project/Task/Attempt/plan/resource ownership differs')
    reject_legacy_generation(destination, snapshot.attempt_id)
    # The destination is an explicitly selected retained snapshot, never a
    # manufactured execution history. Compare every original row before append.
    for original, retained, kind in (
        (source.observations_for_attempt(snapshot.attempt_id),
         destination.observations_for_attempt(snapshot.attempt_id), 'observation'),
        (source.results_for_attempt(snapshot.attempt_id),
         destination.results_for_attempt(snapshot.attempt_id), 'result'),
    ):
        _require(all(item in retained for item in original), f'destination lost original {kind} lineage')
        extras = tuple(item for item in retained if item not in original)
        _require(all((item.observation_type if kind == 'observation' else item.result_type)
                     == (SOURCE if kind == 'observation' else PARSED) for item in extras),
                 'destination has unrelated or mixed-generation lineage')


def _input_member(ensemble, member, raw):
    species = ensemble.species_binding
    _require(species['formal_charge'] == 0 and species['multiplicity'] == 1
             and species['electronic_state_family'] == 'reviewed_closed_shell_singlet',
             'method requires the reviewed neutral closed-shell singlet')
    _require(sum(_ATOMIC_NUMBER[element] for element in species['elements']) % 2 == 0,
             'closed-shell input electron count is odd')
    lines = raw.decode('utf-8').splitlines()
    route = next((i for i, line in enumerate(lines) if line.startswith('#')), None)
    _require(route is not None and lines[route] == ROUTE, 'input route differs from accepted method')
    body = '\n'.join(lines[route:]).split('\n\n')
    _require(len(body) >= 3 and body[0] == ROUTE and body[1].strip(), 'input sections differ')
    rows = body[2].splitlines()
    _require(rows and rows[0] == '0 1', 'input charge/multiplicity differs')
    atoms = [row.split() for row in rows[1:]]
    _require(len(atoms) == len(species['elements']), 'input atom count differs from selected member')
    for row, element, point in zip(atoms, species['elements'], member['coordinates_angstrom']):
        _require(len(row) == 4 and row[0] == element, 'input atom order differs from selected member')
        coordinates = tuple(float(value.replace('D', 'E').replace('d', 'e')) for value in row[1:])
        _require(all(isfinite(value) for value in coordinates) and coordinates == tuple(point),
                 'input geometry differs from selected member')


def _output_method(log, parsed):
    # Source bytes and complete parser facts are already replayed. Compare
    # recognized echo/SCF lines rather than changing the public parser grammar.
    from auto_g16.result.gaussian_job import P
    charge_lines = [line for line in log.splitlines() if P['charge'].fullmatch(line)]
    _require(charge_lines and all(re.fullmatch(rb'\s+Charge\s+=\s+0\s+Multiplicity\s+=\s+1\s*', line)
                                 for line in charge_lines), 'output charge/spin differs')
    scfs = parsed.facts.get('scf_calculations', ())
    _require(bool(scfs), 'output method lacks SCF evidence')
    for scf in scfs:
        span = scf['source_span']
        raw = log[span['start']:span['end']]
        _require(re.search(rb'SCF Done:\s+E\(RwB97XD\)\s*=', raw) is not None,
                 'output SCF reference/method differs')


def read_opt_authority(ensemble, member_id, *, source_store, snapshot, transport_store,
                       destination, validation_driver=None, parser_version="1.1.0"):
    """Reopen original proof, replay full parsing/SV and read the retained pair."""
    _ensemble_closed(ensemble)
    member = _member(ensemble, member_id)
    with gaussian_result_source(source_store, snapshot=snapshot, transport_store=transport_store,
                                validation_driver=validation_driver) as (source, payload, inp, log):
        _same_destination(source, destination, snapshot)
        source_record, result, envelope, parsed = parse_source(payload, log, parser_version=parser_version)
        require_pair(destination, source_record, result)
        _input_member(ensemble, member, inp)
        geometry, assessment = assess_opt(envelope, parsed)
        recovered = None
        if geometry is not None:
            _output_method(log, parsed)
            try:
                _coordinates_from_geometry(geometry, ensemble.species_binding['elements'])
            except RefinementAuthorityError:
                geometry = None
                assessment = {**assessment, 'geometry_disposition': 'rejected_opt_geometry'}
            else:
                recovered = ensemble.species_binding['atom_mapping']
        plan = source.load_calculation_plan(snapshot.calculation_plan_id)
        result_payload = {
            'authority_schema': SCHEMA, 'source': _source(ensemble, member),
            'method_binding': METHOD,
            'method_id': payload_hash({'domain': 'v31-conformer-successor-opt-method/1', 'method': METHOD}),
            'calculation_plan': {'calculation_plan_id': plan.calculation_plan_id, 'revision': plan.revision,
                                 'payload_sha256': payload_hash(_record_payload(plan))},
            'input': payload['input'],
            'result_source': {'observation_id': source_record.observation_id, 'payload_sha256': payload_hash(source_record.data)},
            'parsed_result': {'result_id': result.result_id, 'payload_sha256': payload_hash(result.data)},
            'selected_geometry': geometry, 'recovered_atom_map': recovered, 'assessment': assessment,
        }
        return _freeze_mapping({**result_payload, 'optimization_geometry_authority_id':
                                payload_hash({'domain': SCHEMA, 'payload': result_payload})}, 'successor Opt authority')


def refine_opt_ensemble(prior, profile, *, inputs):
    """Retain partial Opt progress; never invoke the two-stage minimum branch."""
    from .models import ConformerEnsemble
    from .refinement import (_closed_ensemble, _closed_profile, _sampling_observation_by_member,
                             _audit_and_deduplicate)
    _closed_ensemble(prior)
    _closed_profile(profile)
    _require(prior.sampling_profile_id == profile.sampling_profile_id
             and prior.sampling_profile_payload_sha256 == profile.payload_sha256
             and prior.species_binding == profile.species_binding
             and prior.stereochemistry_binding == profile.stereochemistry_binding,
             'profile differs from prior ensemble')
    _require(isinstance(inputs, (tuple, list)) and bool(inputs), 'select at least one Opt member')
    authorities = {}
    coordinates = {}
    attempts = set()
    for item in inputs:
        _require(isinstance(item, Mapping) and {'member_id', 'source_store', 'snapshot', 'transport_store', 'destination'} <= set(item)
                 <= {'member_id', 'source_store', 'snapshot', 'transport_store', 'destination',
                     'validation_driver', 'parser_version'}, 'Opt source input fields differ')
        member_id = item['member_id']
        _require(member_id not in authorities, 'duplicate Opt member disposition')
        attempt_id = item['snapshot'].attempt_id
        _require(attempt_id not in attempts, 'one Attempt cannot refine two selected members')
        attempts.add(attempt_id)
        authority = read_opt_authority(prior, **item)
        authorities[member_id] = authority
        if authority['assessment']['geometry_disposition'] == 'accepted_opt_geometry':
            coordinates[member_id] = _coordinates_from_geometry(authority['selected_geometry'], prior.species_binding['elements'])
    _require(len({authority['method_id'] for authority in authorities.values()}) == 1,
             'Opt method identities differ')
    rejected, comparisons, blockers, clusters, representatives, _survivors = _audit_and_deduplicate(
        prior, profile, _sampling_observation_by_member(prior), coordinates,
    )
    # Cluster names are revision-local; never collide with retained history.
    clusters = [{**cluster, 'cluster_id': f'successor-opt-r{prior.revision + 1}-' + cluster['cluster_id']}
                for cluster in clusters]
    members, audit, negative = [], [], []
    for old in prior.members:
        member_id = old['member_id']
        authority = authorities.get(member_id)
        representative = representatives.get(member_id)
        duplicate = representative is not None and representative != member_id
        if authority is None and 'post_dft_status' in old:
            # A serial gauche update must not erase anti's prior retained proof.
            # Retained evidence is not re-promoted to current authority or used
            # in this revision's dedup without explicit source replay.
            members.append(dict(old))
            audit.append({'member_id': member_id, 'stage': 'successor_opt_refinement',
                          'status': 'retained_prior_disposition',
                          'prior_conformer_ensemble_id': prior.conformer_ensemble_id,
                          'member_payload_sha256': payload_hash(old)})
            continue
        if authority is None:
            status = 'optimization_pending'
        elif member_id not in coordinates:
            status = 'optimization_failed'
        elif member_id in rejected:
            status = 'post_opt_identity_rejected'
        elif duplicate:
            status = 'deduplicated_after_optimization'
        else:
            status = 'optimized_frequency_pending'
        member = {**old, 'post_dft_status': status, 'post_dft_minimum_evidence_available': False,
                  'two_stage_minimum_authority': None, 'negative_frequency_authority': None,
                  'optimization_geometry_authority': authority if member_id in coordinates else None,
                  'negative_optimization_authority': authority if authority is not None and member_id not in coordinates else None,
                  'post_dft_cluster_id': next((cluster['cluster_id'] for cluster in clusters if member_id in cluster['member_ids']), None),
                  'post_dft_representative_member_id': representative,
                  'post_dft_duplicate_of_member_id': representative if duplicate else None}
        if member_id in coordinates and member_id not in rejected:
            member['coordinates_angstrom'] = coordinates[member_id]
        members.append(member)
        entry = {'member_id': member_id, 'stage': 'successor_opt_refinement', 'status': status,
                 'optimization_geometry_authority_id': None if authority is None else authority['optimization_geometry_authority_id'],
                 'result_source': None if authority is None else authority['result_source'],
                 'parsed_result': None if authority is None else authority['parsed_result']}
        audit.append(entry)
        if status in {'optimization_failed', 'post_opt_identity_rejected', 'deduplicated_after_optimization'}:
            negative.append({**entry, 'retained_as_negative_evidence': True,
                             'reasons': rejected.get(member_id, authority['assessment']['reason_codes']),
                             'duplicate_of_member_id': representative if duplicate else None})
    return ConformerEnsemble._create(
        project_id=prior.project_id, calculation_plan_id=prior.calculation_plan_id,
        calculation_plan_revision=prior.calculation_plan_revision, profile=profile,
        sampling_observations=prior.sampling_observations, audit_evidence=(*prior.audit_evidence, *audit),
        negative_evidence=(*prior.negative_evidence, *negative),
        dedup_decisions=(*prior.dedup_decisions, *comparisons),
        independent_review_blockers=(*prior.independent_review_blockers, *blockers),
        clusters=(*prior.clusters, *clusters), members=members, coverage=prior.coverage,
        thermodynamic_eligible_members=(), ts_seed_members=(), revision=prior.revision + 1,
        supersedes_conformer_ensemble_id=prior.conformer_ensemble_id,
    )


def import_opt_result_revision(*, source_store, snapshot, transport_store,
                               destination_path, output_path, approved_root, validation_driver=None, parser_version="1.1.0"):
    """Explicit new immutable destination revision; original databases stay read-only."""
    from auto_g16.core.store import _readonly_database_state
    from auto_g16.result._successor import append_pair
    from auto_g16.result._revision_file import publish_revision
    import os
    destination_path, output_path = os.fspath(destination_path), os.fspath(output_path)
    source_paths = tuple(row[2] for row in source_store._connection.execute('PRAGMA database_list')
                         if row[1] == 'main') + (transport_store._path,)
    _require(len(source_paths) == 2 and all(source_paths), 'source must have original disk locations')
    input_paths = (*source_paths, destination_path)
    _require(len(set(input_paths)) == 3 and output_path not in input_paths, 'source/destination paths alias')
    states = tuple(_readonly_database_state(path) for path in input_paths)
    identities = tuple(state[0][-1] for state in states)
    _require(len(set(identities)) == 3, 'source/destination physical files alias')
    with gaussian_result_source(source_store, snapshot=snapshot, transport_store=transport_store,
                                validation_driver=validation_driver) as (source, payload, _inp, log):
        source_record, result, _envelope, _parsed = parse_source(payload, log, parser_version=parser_version)
        with SQLiteRuntimeStore.read_snapshot(destination_path) as destination:
            _same_destination(source, destination, snapshot)
            require_pair(destination, source_record, result, allow_partial=True)
            cached = destination._connection.serialize()
        # Both appends happen only in an owner-created memory database.
        memory = SQLiteRuntimeStore()
        try:
            memory._connection.deserialize(cached)
            append_pair(memory, source_record, result)
            revision = memory._connection.serialize()
        finally:
            memory.close()
    _require(tuple(_readonly_database_state(path) for path in input_paths) == states,
             'source or destination changed before revision publication')
    receipt = publish_revision(revision, path=output_path, root=approved_root,
                               forbidden_identities=identities)
    _require(tuple(_readonly_database_state(path) for path in input_paths) == states,
             'source or destination changed during revision publication')
    return receipt
