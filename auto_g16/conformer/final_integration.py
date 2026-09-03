"""Private record-level closure for the final V31 ensemble view."""

from __future__ import annotations

from collections.abc import Mapping
import math

from auto_g16.thermochemistry.models import (
    ThermodynamicEnsemble,
    _identified_payload as _thermodynamic_identified_payload,
)
from auto_g16.thermochemistry._service import (
    _POPULATION_TOLERANCE as _THERMOCHEMISTRY_POPULATION_TOLERANCE,
)

from .models import (
    ConformerEnsemble,
    _identified_payload as _conformer_identified_payload,
)


_OBSERVATION_KEYS = {
    "member_id",
    "source_refined_conformer_ensemble_id",
    "source_refined_conformer_ensemble_revision",
    "two_stage_minimum_authority_id",
    "method_compatibility_id",
    "method_compatibility_binding",
    "source_provenance",
    "temperature_k",
    "standard_state",
    "raw_rrho",
    "treated_qrrho",
    "degeneracy",
    "degeneracy_rationale",
    "inclusion_status",
    "relative_statistical_weight",
    "normalized_population",
}
_PARTITION_KEYS = {
    "reference_member_id",
    "reference_gibbs_hartree",
    "representation",
    "log_scale",
    "scaled_relative_partition_function",
    "log_relative_partition_function",
}
_NORMALIZATION_KEYS = {
    "population_sum",
    "absolute_error",
    "numeric_tolerance",
    "status",
    "tolerance_purpose",
}
_GAS_CONSTANT_KEYS = {
    "gas_constant_j_per_mol_k",
    "joule_per_hartree_mol",
    "gas_constant_hartree_per_mol_k",
    "unit_convention",
}


class _FinalIntegrationError(ValueError):
    """The two authoritative V31 records do not compose exactly."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise _FinalIntegrationError(message)


def _closed(value: object, keys: set[str], name: str) -> Mapping[str, object]:
    _require(isinstance(value, Mapping) and set(value) == keys, f"{name} fields are not exact")
    assert isinstance(value, Mapping)
    return value


def _text(value: object, name: str) -> str:
    _require(
        isinstance(value, str) and bool(value) and value == value.strip(),
        f"{name} is not canonical text",
    )
    assert isinstance(value, str)
    return value


def _finite(value: object, name: str, *, positive: bool = False) -> float:
    _require(type(value) is float and math.isfinite(value), f"{name} must be a finite float")
    assert isinstance(value, float)
    if positive:
        _require(value > 0.0, f"{name} must be positive")
    return value


def _close_conformer_identity(ensemble: object) -> ConformerEnsemble:
    _require(type(ensemble) is ConformerEnsemble, "refined ensemble must be a ConformerEnsemble")
    assert isinstance(ensemble, ConformerEnsemble)
    identity, payload_sha256 = _conformer_identified_payload(
        "conformer-ensemble", ensemble._identity_payload()
    )
    _require(
        identity == ensemble.conformer_ensemble_id
        and payload_sha256 == ensemble.payload_sha256,
        "refined ConformerEnsemble identity is stale",
    )
    return ensemble


def _close_thermodynamic_identity(ensemble: object) -> ThermodynamicEnsemble:
    _require(
        type(ensemble) is ThermodynamicEnsemble,
        "thermodynamic ensemble must be a ThermodynamicEnsemble",
    )
    assert isinstance(ensemble, ThermodynamicEnsemble)
    identity, payload_sha256 = _thermodynamic_identified_payload(
        "thermodynamic-ensemble", ensemble._identity_payload()
    )
    _require(
        identity == ensemble.thermodynamic_ensemble_id
        and payload_sha256 == ensemble.payload_sha256,
        "ThermodynamicEnsemble identity is stale",
    )
    return ensemble


def _close_named_binding(
    domain: str,
    binding: Mapping[str, object],
    expected_identity: object,
    name: str,
) -> None:
    identity, _payload_sha256 = _thermodynamic_identified_payload(domain, binding)
    _require(identity == expected_identity, f"{name} identity is stale")


def _member_ids(ensemble: ConformerEnsemble) -> tuple[str, ...]:
    identifiers = []
    for member in ensemble.members:
        _require(isinstance(member, Mapping), "refined member must be a mapping")
        identifiers.append(_text(member.get("member_id"), "refined member_id"))
    return tuple(identifiers)


def _close_population(
    ensemble: ConformerEnsemble,
    thermodynamics: ThermodynamicEnsemble,
) -> None:
    observations = thermodynamics.member_observations
    _require(type(observations) is tuple, "thermodynamic member observations must be an exact tuple")
    normalized = []
    log_weights = []
    treated_gibbs: dict[str, float] = {}
    observation_ids = []
    for observation in observations:
        item = _closed(observation, _OBSERVATION_KEYS, "thermodynamic member observation")
        member_id = _text(item["member_id"], "thermodynamic member_id")
        observation_ids.append(member_id)
        _require(
            item["source_refined_conformer_ensemble_id"] == ensemble.conformer_ensemble_id
            and item["source_refined_conformer_ensemble_revision"] == ensemble.revision,
            "thermodynamic member lineage does not bind the refined ensemble",
        )
        _text(item["two_stage_minimum_authority_id"], "two-stage minimum authority ID")
        _require(
            item["method_compatibility_id"] == thermodynamics.method_compatibility_id
            and item["method_compatibility_binding"]
            == thermodynamics.method_compatibility_binding,
            "thermodynamic member method lineage differs from the ensemble binding",
        )
        _require(isinstance(item["source_provenance"], Mapping), "source provenance is unavailable")
        _require(isinstance(item["raw_rrho"], Mapping), "raw RRHO evidence is unavailable")
        treated = item["treated_qrrho"]
        _require(isinstance(treated, Mapping), "treated qRRHO evidence is unavailable")
        treated_gibbs[member_id] = _finite(
            treated.get("gibbs_free_energy_hartree"),
            "treated qRRHO Gibbs free energy",
        )
        _require(
            item["temperature_k"] == thermodynamics.temperature_k
            and item["standard_state"] == thermodynamics.standard_state,
            "thermodynamic member conditions differ from the ensemble",
        )
        _require(
            type(item["degeneracy"]) is int and item["degeneracy"] >= 1,
            "thermodynamic member degeneracy must be a positive integer",
        )
        _text(item["degeneracy_rationale"], "degeneracy rationale")
        _require(
            item["inclusion_status"] == "included_thermodynamic_eligible",
            "thermodynamic member inclusion status is not closed",
        )
        weight = _closed(
            item["relative_statistical_weight"],
            {"log_value", "representation"},
            "relative statistical weight",
        )
        _require(
            weight["representation"] == "natural_log_relative_to_reference_gibbs",
            "relative statistical weight representation is unsupported",
        )
        log_weights.append(_finite(weight["log_value"], "relative log weight"))
        population = _finite(item["normalized_population"], "normalized population")
        _require(0.0 <= population <= 1.0, "normalized population is outside [0, 1]")
        normalized.append(population)

    _require(
        tuple(observation_ids) == thermodynamics.source_member_ids,
        "thermodynamic observations do not exactly follow the ordered source member set",
    )
    _require(
        len(observation_ids) == len(set(observation_ids)),
        "duplicate thermodynamic member observation",
    )

    partition = _closed(
        thermodynamics.partition_evidence,
        _PARTITION_KEYS,
        "partition evidence",
    )
    _require(
        partition["representation"] == "stable_logsumexp",
        "partition representation is unsupported",
    )
    reference_member = _text(partition["reference_member_id"], "reference member ID")
    _require(reference_member in treated_gibbs, "partition reference member is unavailable")
    _require(
        reference_member
        == min(
            thermodynamics.source_member_ids,
            key=lambda member_id: (treated_gibbs[member_id], member_id),
        ),
        "partition reference member is not the deterministic treated-Gibbs reference",
    )
    reference_gibbs = _finite(partition["reference_gibbs_hartree"], "reference Gibbs free energy")
    _require(
        reference_gibbs == treated_gibbs[reference_member],
        "partition reference Gibbs free energy differs from its member observation",
    )
    log_scale = _finite(partition["log_scale"], "partition log scale")
    scaled_partition = _finite(
        partition["scaled_relative_partition_function"],
        "scaled relative partition function",
        positive=True,
    )
    log_partition = _finite(
        partition["log_relative_partition_function"],
        "log relative partition function",
    )
    _require(log_scale == max(log_weights), "partition log scale does not match member weights")
    reconstructed_scaled = math.fsum(math.exp(value - log_scale) for value in log_weights)
    _require(
        abs(reconstructed_scaled - scaled_partition) <= _THERMOCHEMISTRY_POPULATION_TOLERANCE,
        "scaled relative partition function is inconsistent",
    )
    _require(
        abs(log_scale + math.log(scaled_partition) - log_partition)
        <= _THERMOCHEMISTRY_POPULATION_TOLERANCE,
        "log relative partition function is inconsistent",
    )
    for population, log_weight in zip(normalized, log_weights, strict=True):
        _require(
            abs(math.exp(log_weight - log_partition) - population)
            <= _THERMOCHEMISTRY_POPULATION_TOLERANCE,
            "stored member population is inconsistent with partition evidence",
        )

    normalization = _closed(
        thermodynamics.population_normalization,
        _NORMALIZATION_KEYS,
        "population normalization",
    )
    population_sum = math.fsum(normalized)
    absolute_error = abs(population_sum - 1.0)
    _require(
        normalization["numeric_tolerance"] == _THERMOCHEMISTRY_POPULATION_TOLERANCE
        and type(normalization["numeric_tolerance"]) is float,
        "population normalization tolerance differs from frozen thermochemistry",
    )
    _require(
        normalization["status"] == "normalized"
        and normalization["tolerance_purpose"]
        == "floating_point_normalization_only_not_scientific_selection",
        "population normalization disposition is not closed",
    )
    _require(
        normalization["population_sum"] == population_sum
        and normalization["absolute_error"] == absolute_error
        and absolute_error <= _THERMOCHEMISTRY_POPULATION_TOLERANCE,
        "stored populations do not close without renormalization",
    )

    gas_constant = _closed(
        thermodynamics.gas_constant_binding,
        _GAS_CONSTANT_KEYS,
        "gas constant binding",
    )
    _require(
        gas_constant["unit_convention"] == "per_mole_hartree_kelvin",
        "gas constant unit convention is unsupported",
    )
    gas_constant_hartree = _finite(
        gas_constant["gas_constant_hartree_per_mol_k"],
        "gas constant in hartree per mole kelvin",
        positive=True,
    )
    temperature = _finite(thermodynamics.temperature_k, "thermodynamic temperature", positive=True)
    expected_ensemble_gibbs = reference_gibbs - gas_constant_hartree * temperature * log_partition
    ensemble_gibbs = _finite(
        thermodynamics.ensemble_treated_free_energy_hartree,
        "ensemble treated Gibbs free energy",
    )
    _require(
        abs(expected_ensemble_gibbs - ensemble_gibbs)
        <= _THERMOCHEMISTRY_POPULATION_TOLERANCE,
        "ensemble treated free energy is inconsistent with partition evidence",
    )


def _validate_final_ensemble_integration(
    refined_ensemble: ConformerEnsemble,
    thermodynamic_ensemble: ThermodynamicEnsemble,
) -> tuple[ConformerEnsemble, ThermodynamicEnsemble, tuple[str, ...]]:
    """Return the exact authoritative records and TS projection after closure."""

    ensemble = _close_conformer_identity(refined_ensemble)
    thermodynamics = _close_thermodynamic_identity(thermodynamic_ensemble)
    _require(
        thermodynamics.conformer_ensemble_id == ensemble.conformer_ensemble_id
        and thermodynamics.conformer_ensemble_payload_sha256 == ensemble.payload_sha256
        and thermodynamics.conformer_ensemble_revision == ensemble.revision,
        "ThermodynamicEnsemble does not bind the exact refined ConformerEnsemble",
    )

    eligible = ensemble.thermodynamic_eligible_members
    source_members = thermodynamics.source_member_ids
    _require(type(eligible) is tuple and type(source_members) is tuple, "member projections must be exact tuples")
    for member_id in (*eligible, *source_members):
        _text(member_id, "thermodynamic member ID")
    _require(len(eligible) == len(set(eligible)), "thermodynamic eligibility contains duplicates")
    _require(
        source_members == eligible,
        "thermodynamic source members do not equal the ordered eligibility projection",
    )
    _require(bool(source_members), "thermodynamic source member set is empty")

    member_ids = _member_ids(ensemble)
    _require(len(member_ids) == len(set(member_ids)), "refined ensemble contains duplicate member IDs")
    _require(
        all(member_ids.count(member_id) == 1 for member_id in source_members),
        "thermodynamic member does not resolve exactly once in the refined ensemble",
    )

    ts_seeds = ensemble.ts_seed_members
    _require(type(ts_seeds) is tuple, "TS-seed projection must be an exact tuple")
    for member_id in ts_seeds:
        _text(member_id, "TS-seed member ID")
        _require(
            member_ids.count(member_id) == 1,
            "TS-seed member does not resolve exactly once in the refined ensemble",
        )
    _require(len(ts_seeds) == len(set(ts_seeds)), "TS-seed projection contains duplicates")

    _close_named_binding(
        "thermochemistry-policy",
        thermodynamics.thermochemistry_policy,
        thermodynamics.thermochemistry_policy_id,
        "thermochemistry policy",
    )
    _require(
        _thermodynamic_identified_payload(
            "thermochemistry-policy", thermodynamics.thermochemistry_policy
        )[1]
        == thermodynamics.thermochemistry_policy_payload_sha256,
        "thermochemistry policy payload hash is stale",
    )
    _close_named_binding(
        "functional-kernel-implementation",
        thermodynamics.functional_kernel_implementation_binding,
        thermodynamics.functional_kernel_implementation_id,
        "functional-kernel implementation",
    )
    _close_named_binding(
        "thermochemistry-method",
        thermodynamics.method_compatibility_binding,
        thermodynamics.method_compatibility_id,
        "thermochemistry method",
    )
    _close_population(ensemble, thermodynamics)

    return ensemble, thermodynamics, ts_seeds
