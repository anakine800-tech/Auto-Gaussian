"""Offline population calculation from an exactly replayed saved native pair."""
import math

from .models import _freeze_mapping, _identified_payload
from ._service import _require, _finite
from auto_g16.conformer import thermochemistry_readonly as pair_owner
from auto_g16.conformer import populations_readonly as saved


def _scheme(energies, degeneracies, reference, rt, conversion):
    _require(len(energies) == len(degeneracies) == 2 and type(reference) is int
             and reference in (0, 1), 'invalid scheme membership')
    _finite(rt, 'RT', positive=True)
    _finite(conversion, 'conversion', positive=True)
    for energy, g in zip(energies, degeneracies):
        _finite(energy, 'Gibbs energy')
        saved._integer(g, 'degeneracy')
    delta = [g - energies[reference] for g in energies]
    logs = [math.log(g) - dg / rt for g, dg in zip(degeneracies, delta)]
    _require(all(math.isfinite(x) for x in logs), 'nonfinite relative weight')
    scale = max(logs)
    weights = [math.exp(x - scale) for x in logs]
    total = math.fsum(weights)
    rows = [dict(gibbs_free_energy_hartree=g, delta_g_hartree=dg, delta_g_kcal_per_mol=dg * conversion,
                 log_relative_weight=log, normalized_population=weight / total)
            for g, dg, log, weight in zip(energies, delta, logs, weights)]
    population_sum = math.fsum(row['normalized_population'] for row in rows)
    error = abs(population_sum - 1)
    _require(error <= saved._TOLERANCE, 'population normalization failed')
    return rows, dict(population_sum=population_sum, absolute_error=error, numeric_tolerance=saved._TOLERANCE)


def build_native_populations(readout, *, reference_member_id):
    with pair_owner._replayed_native_pair(readout) as pair:
        q, t = pair
        ids = t.source_member_ids
        _require(type(reference_member_id) is str and len(ids) == 2 and len(set(ids)) == 2
                 and reference_member_id in ids, 'invalid population reference')
        payload = saved._source_payload(pair, readout.artifact.sha256)
        payload['reference_member_id'] = reference_member_id
        policies = q.audit_evidence[-1]['request_payload']['member_policies']
        members = [saved._source_member(row, policy) for row, policy in zip(t.member_observations, policies)]
        rt = t.gas_constant_binding['gas_constant_hartree_per_mol_k'] * t.temperature_k
        normalization = {}
        for scheme, key in (('rrho', 'raw_rrho'), ('qrrho', 'treated_qrrho')):
            rows, normalization[scheme] = _scheme(
                [row[key]['gibbs_free_energy_hartree'] for row in t.member_observations],
                [row['degeneracy'] for row in t.member_observations], ids.index(reference_member_id), rt,
                payload['hartree_to_kcal_per_mol'])
            for member, row in zip(members, rows):
                member[scheme] = row
        payload.update(members=members, normalization=normalization)
        identity, digest = _identified_payload('native-populations', payload)
        artifact = dict(schema=saved._SCHEMA, artifact_id=identity, payload_sha256=digest, payload=payload)
        saved._validate_source(artifact, pair, readout.artifact.sha256)
        result = _freeze_mapping(artifact, 'population artifact')
    return result


encode_native_populations = saved.encode_native_populations
save_native_populations = saved.save_native_populations
