"""Private record-level closure for the final V31 ensemble view."""

from __future__ import annotations

from collections.abc import Mapping
import math

from auto_g16.thermochemistry.models import (
    ThermodynamicEnsemble,
    _identified_payload as _thermodynamic_identified_payload,
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
_RAW_RRHO_KEYS = {
    "electronic_energy_hartree",
    "zero_point_energy_hartree",
    "enthalpy_hartree",
    "entropy_hartree_per_kelvin",
    "gibbs_free_energy_hartree",
}
_TREATED_QRRHO_KEYS = {
    "enthalpy_hartree",
    "entropy_hartree_per_kelvin",
    "gibbs_free_energy_hartree",
    "entropy_treatment",
    "enthalpy_treatment",
}
_SOURCE_PROVENANCE_KEYS = {
    "predecessor_lineage",
    "source_result_id",
    "source_result_payload_sha256",
    "source_artifact",
    "job_section",
    "gaussian_thermo_facts",
}
_PREDECESSOR_LINEAGE_KEYS = {
    "conformer_ensemble_id",
    "conformer_ensemble_payload_sha256",
    "member_source",
}
_MEMBER_SOURCE_KEYS = {
    "conformer_ensemble_id",
    "conformer_ensemble_payload_sha256",
    "sampling_profile_id",
    "sampling_profile_payload_sha256",
    "member_id",
    "member_payload_sha256",
    "canonical_atom_order_sha256",
    "source_atom_map_sha256",
    "source_geometry_sha256",
    "species_binding_sha256",
    "stereochemistry_binding_sha256",
}
_SOURCE_ARTIFACT_KEYS = {
    "envelope_observation_id",
    "artifact_kind",
    "logical_name",
    "sha256",
    "size_bytes",
}
_JOB_SECTION_KEYS = _SOURCE_ARTIFACT_KEYS | {"start", "end"}
_GAUSSIAN_THERMO_FACT_KEYS = {
    "molecular_mass_amu",
    "rotational_symmetry_number",
    "rotational_symmetry_observation_count",
    "rotational_temperatures_kelvin",
    "point_group_diagnostic",
}
_NUMERIC_REPLAY_TOLERANCE = 1.0e-12


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
    _require(
        type(value) in {int, float} and math.isfinite(float(value)),
        f"{name} must be finite",
    )
    result = float(value)
    if positive:
        _require(result > 0.0, f"{name} must be positive")
    return result


def _sha256(value: object, name: str) -> str:
    text = _text(value, name)
    _require(
        len(text) == 64 and all(character in "0123456789abcdef" for character in text),
        f"{name} is not an exact lowercase SHA-256",
    )
    return text


def _within(left: float, right: float) -> bool:
    return abs(left - right) <= _NUMERIC_REPLAY_TOLERANCE


def _log_positive_integer(value: int) -> float:
    bits = value.bit_length()
    if bits <= 53:
        return math.log(value)
    shift = bits - 53
    return math.log(value >> shift) + shift * math.log(2.0)


def _close_source_provenance(value: object, member_id: str) -> None:
    provenance = _closed(value, _SOURCE_PROVENANCE_KEYS, "source provenance")
    predecessor = _closed(
        provenance["predecessor_lineage"],
        _PREDECESSOR_LINEAGE_KEYS,
        "predecessor lineage",
    )
    predecessor_id = _text(
        predecessor["conformer_ensemble_id"],
        "predecessor conformer ensemble ID",
    )
    predecessor_sha = _sha256(
        predecessor["conformer_ensemble_payload_sha256"],
        "predecessor conformer ensemble payload SHA-256",
    )
    member_source = _closed(
        predecessor["member_source"],
        _MEMBER_SOURCE_KEYS,
        "predecessor member source",
    )
    _require(
        member_source["conformer_ensemble_id"] == predecessor_id
        and member_source["conformer_ensemble_payload_sha256"] == predecessor_sha,
        "member source does not bind its predecessor ensemble",
    )
    _text(member_source["sampling_profile_id"], "member source sampling profile ID")
    _require(
        member_source["member_id"] == member_id,
        "member source does not bind the thermodynamic member",
    )
    for name in _MEMBER_SOURCE_KEYS - {
        "conformer_ensemble_id",
        "sampling_profile_id",
        "member_id",
    }:
        _sha256(member_source[name], f"member source {name}")

    _text(provenance["source_result_id"], "source Result ID")
    _sha256(provenance["source_result_payload_sha256"], "source Result payload SHA-256")
    source_artifact = _closed(
        provenance["source_artifact"],
        _SOURCE_ARTIFACT_KEYS,
        "source artifact",
    )
    for name in ("envelope_observation_id", "artifact_kind", "logical_name"):
        _text(source_artifact[name], f"source artifact {name}")
    _sha256(source_artifact["sha256"], "source artifact SHA-256")
    _require(
        type(source_artifact["size_bytes"]) is int and source_artifact["size_bytes"] > 0,
        "source artifact size must be an exact positive integer",
    )

    section = _closed(provenance["job_section"], _JOB_SECTION_KEYS, "job section")
    _require(
        all(section[name] == source_artifact[name] for name in _SOURCE_ARTIFACT_KEYS),
        "job section does not bind the exact source artifact",
    )
    _require(
        type(section["start"]) is int
        and type(section["end"]) is int
        and 0 <= section["start"] < section["end"] <= source_artifact["size_bytes"],
        "job section span is invalid",
    )

    facts = _closed(
        provenance["gaussian_thermo_facts"],
        _GAUSSIAN_THERMO_FACT_KEYS,
        "Gaussian thermochemistry facts",
    )
    _finite(facts["molecular_mass_amu"], "molecular mass", positive=True)
    _require(
        type(facts["rotational_symmetry_number"]) is int
        and facts["rotational_symmetry_number"] >= 1,
        "rotational symmetry number must be an exact positive integer",
    )
    _require(
        type(facts["rotational_symmetry_observation_count"]) is int
        and facts["rotational_symmetry_observation_count"] >= 1,
        "rotational symmetry observation count must be an exact positive integer",
    )
    temperatures = facts["rotational_temperatures_kelvin"]
    _require(
        type(temperatures) is tuple and len(temperatures) == 3,
        "rotational temperatures must be an exact three-value tuple",
    )
    for temperature in temperatures:
        _finite(temperature, "rotational temperature", positive=True)
    if facts["point_group_diagnostic"] is not None:
        _text(facts["point_group_diagnostic"], "point-group diagnostic")


def _close_rrho(value: object, temperature: float, *, treated: bool) -> float:
    keys = _TREATED_QRRHO_KEYS if treated else _RAW_RRHO_KEYS
    label = "treated qRRHO" if treated else "raw RRHO"
    record = _closed(value, keys, label)
    if treated:
        _require(
            record["entropy_treatment"] == "grimme"
            and record["enthalpy_treatment"] == "head_gordon",
            "treated qRRHO policy is unsupported",
        )
    enthalpy = _finite(record["enthalpy_hartree"], f"{label} enthalpy")
    entropy = _finite(record["entropy_hartree_per_kelvin"], f"{label} entropy")
    gibbs = _finite(record["gibbs_free_energy_hartree"], f"{label} Gibbs free energy")
    for name in keys - {
        "enthalpy_hartree",
        "entropy_hartree_per_kelvin",
        "gibbs_free_energy_hartree",
        "entropy_treatment",
        "enthalpy_treatment",
    }:
        _finite(record[name], f"{label} {name}")
    _require(_within(gibbs, enthalpy - temperature * entropy), f"{label} H-TS identity is inconsistent")
    return gibbs


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
    temperature = _finite(
        thermodynamics.temperature_k,
        "thermodynamic temperature",
        positive=True,
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
    for name in (
        "gas_constant_j_per_mol_k",
        "joule_per_hartree_mol",
        "gas_constant_hartree_per_mol_k",
    ):
        _finite(gas_constant[name], f"gas constant binding {name}", positive=True)
    gas_constant_hartree = _finite(
        gas_constant["gas_constant_hartree_per_mol_k"],
        "gas constant in hartree per mole kelvin",
        positive=True,
    )
    rt = gas_constant_hartree * temperature
    _require(math.isfinite(rt) and rt > 0.0, "thermodynamic RT must be finite and positive")

    treated_gibbs: dict[str, float] = {}
    degeneracies: dict[str, int] = {}
    recorded_log_weights: dict[str, float] = {}
    recorded_populations: dict[str, float] = {}
    observation_ids: list[str] = []
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
        _close_source_provenance(item["source_provenance"], member_id)
        _close_rrho(item["raw_rrho"], temperature, treated=False)
        treated_gibbs[member_id] = _close_rrho(
            item["treated_qrrho"],
            temperature,
            treated=True,
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
        degeneracies[member_id] = item["degeneracy"]
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
        recorded_log_weights[member_id] = _finite(weight["log_value"], "relative log weight")
        population = _finite(item["normalized_population"], "normalized population")
        _require(0.0 <= population <= 1.0, "normalized population is outside [0, 1]")
        recorded_populations[member_id] = population

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
    expected_log_weights = {
        member_id: _log_positive_integer(degeneracies[member_id])
        - (treated_gibbs[member_id] - reference_gibbs) / rt
        for member_id in thermodynamics.source_member_ids
    }
    for member_id in thermodynamics.source_member_ids:
        _require(
            _within(recorded_log_weights[member_id], expected_log_weights[member_id]),
            "stored member log weight does not follow Gibbs and degeneracy",
        )

    expected_log_scale = max(expected_log_weights.values())
    expected_scaled_partition = math.fsum(
        math.exp(expected_log_weights[member_id] - expected_log_scale)
        for member_id in thermodynamics.source_member_ids
    )
    expected_log_partition = expected_log_scale + math.log(expected_scaled_partition)
    recorded_log_scale = _finite(partition["log_scale"], "partition log scale")
    recorded_scaled_partition = _finite(
        partition["scaled_relative_partition_function"],
        "scaled relative partition function",
        positive=True,
    )
    recorded_log_partition = _finite(
        partition["log_relative_partition_function"],
        "log relative partition function",
    )
    _require(
        _within(recorded_log_scale, expected_log_scale),
        "partition log scale is inconsistent",
    )
    _require(
        _within(recorded_scaled_partition, expected_scaled_partition),
        "scaled relative partition function is inconsistent",
    )
    _require(
        _within(recorded_log_partition, expected_log_partition),
        "log relative partition function is inconsistent",
    )

    expected_populations = {
        member_id: math.exp(expected_log_weights[member_id] - expected_log_partition)
        for member_id in thermodynamics.source_member_ids
    }
    for member_id in thermodynamics.source_member_ids:
        _require(
            _within(recorded_populations[member_id], expected_populations[member_id]),
            "stored member population does not follow Gibbs and degeneracy",
        )

    normalization = _closed(
        thermodynamics.population_normalization,
        _NORMALIZATION_KEYS,
        "population normalization",
    )
    population_sum = math.fsum(expected_populations.values())
    absolute_error = abs(population_sum - 1.0)
    _require(
        normalization["numeric_tolerance"] == _NUMERIC_REPLAY_TOLERANCE
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
        _within(_finite(normalization["population_sum"], "stored population sum"), population_sum)
        and _within(_finite(normalization["absolute_error"], "stored population error"), absolute_error)
        and absolute_error <= _NUMERIC_REPLAY_TOLERANCE,
        "stored populations do not close without renormalization",
    )
    expected_ensemble_gibbs = reference_gibbs - rt * expected_log_partition
    ensemble_gibbs = _finite(
        thermodynamics.ensemble_treated_free_energy_hartree,
        "ensemble treated Gibbs free energy",
    )
    _require(
        _within(expected_ensemble_gibbs, ensemble_gibbs),
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
