"""Private, fail-closed V31 thermochemistry normalization and aggregation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import math
import re

from auto_g16.conformer import ConformerEnsemble

from .models import (
    ThermodynamicEnsemble,
    _freeze_mapping,
    _identified_payload,
    _payload_sha256,
)


_GAS_CONSTANT_J_PER_MOL_K = 8.3144621
_J_PER_HARTREE_MOL = 4.184 * 627.509541 * 1000.0
_GAS_CONSTANT_HARTREE_PER_MOL_K = _GAS_CONSTANT_J_PER_MOL_K / _J_PER_HARTREE_MOL
_STANDARD_PRESSURE_KPA = 101.325
_POPULATION_TOLERANCE = 1.0e-12
_SHA256 = re.compile(r"[0-9a-f]{64}")

_POLICY_KEYS = {
    "adapter_identity",
    "adapter_version",
    "automatic_scale_factor_lookup",
    "engine_artifact",
    "engine_artifact_sha256",
    "engine_identity",
    "engine_version",
    "enthalpy_frequency_cutoff_cm_1",
    "entropy_frequency_cutoff_cm_1",
    "frequency_scaling_factor",
    "goodvibes_symm",
    "imaginary_frequency_inversion",
    "moment_of_inertia_treatment",
    "qrrho_enthalpy_treatment",
    "qrrho_entropy_method",
    "solvent_free_space_correction",
    "spc_file_discovery",
    "standard_state",
    "symmetry_treatment",
    "temperature_k",
    "zpe_scaling_factor",
}
_OBSERVATION_KEYS = {
    "degeneracy",
    "degeneracy_rationale",
    "member_id",
    "method_compatibility_binding",
    "raw_rrho",
    "source_provenance",
    "standard_state",
    "temperature_k",
    "thermochemistry_policy",
    "treated_qrrho",
}
_METHOD_KEYS = {
    "basis_model_identity",
    "electronic_correction_identity",
    "electronic_energy_level_identity",
    "frequency_level_identity",
    "geometry_level_identity",
    "reference_state_identity",
    "result_contract_identity",
    "solvent_environment_identity",
    "symmetry_number_convention",
}
_PROVENANCE_KEYS = {
    "evidence_disposition",
    "output_reported_point_group",
    "result_contract_identity",
    "source_gaussian_log_sha256",
    "source_result_id",
    "source_result_payload_sha256",
    "symmetry_provenance",
}
_SYMMETRY_PROVENANCE_KEYS = {
    "explicit_symmetry_observation_count",
    "goodvibes_parsed_symmno",
    "goodvibes_symm",
    "raw_gaussian_log_sha256",
    "reported_rotational_symmetry_number",
    "symmetry_policy",
}
_SYMMETRY_POLICY_KEYS = {"external_detection", "mode"}
_RAW_KEYS = {
    "electronic_energy_hartree",
    "enthalpy_hartree",
    "entropy_hartree_per_kelvin",
    "gibbs_free_energy_hartree",
    "zero_point_energy_hartree",
}
_TREATED_KEYS = {
    "enthalpy_hartree",
    "enthalpy_treatment",
    "entropy_hartree_per_kelvin",
    "entropy_treatment",
    "gibbs_free_energy_hartree",
}


class _ThermochemistryError(ValueError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise _ThermochemistryError(message)


def _closed_mapping(value: object, keys: set[str], label: str) -> Mapping[str, object]:
    _require(isinstance(value, Mapping), f"{label} must be a mapping")
    assert isinstance(value, Mapping)
    _require(set(value) == keys, f"{label} must contain exactly {sorted(keys)}")
    return value


def _string(value: object, label: str) -> str:
    _require(isinstance(value, str) and bool(value) and value == value.strip(), f"{label} is invalid")
    assert isinstance(value, str)
    return value


def _finite(value: object, label: str, *, positive: bool = False, nonnegative: bool = False) -> float:
    _require(type(value) in {int, float}, f"{label} must be a finite number")
    number = float(value)
    _require(math.isfinite(number), f"{label} must be a finite number")
    if positive:
        _require(number > 0.0, f"{label} must be positive")
    if nonnegative:
        _require(number >= 0.0, f"{label} must be nonnegative")
    return number


def _sha256(value: object, label: str) -> str:
    text = _string(value, label)
    _require(_SHA256.fullmatch(text) is not None, f"{label} must be lowercase SHA-256")
    return text


def _normalize_policy(value: object) -> Mapping[str, object]:
    supplied = _closed_mapping(value, _POLICY_KEYS, "thermochemistry_policy")
    policy = dict(supplied)
    exact = {
        "engine_identity": "GoodVibes",
        "engine_version": "4.3.0",
        "engine_artifact": "goodvibes-4.3.0-py3-none-any.whl",
        "engine_artifact_sha256": "06476db73ee456c1fc941590374f2a30182baaf043f6b60dbef85ee77db93997",
        "adapter_identity": "auto-g16-goodvibes-programmatic-adapter",
        "adapter_version": "1",
        "symmetry_treatment": "gaussian_output_required",
        "goodvibes_symm": False,
        "moment_of_inertia_treatment": "global_grimme_bav",
        "solvent_free_space_correction": "none",
        "spc_file_discovery": "forbidden",
        "imaginary_frequency_inversion": "forbidden",
        "automatic_scale_factor_lookup": False,
    }
    for key, expected in exact.items():
        _require(policy[key] == expected and type(policy[key]) is type(expected), f"{key} is unsupported")
    _require(policy["standard_state"] in {"1atm", "1M"}, "standard_state is unsupported")
    _require(policy["qrrho_entropy_method"] in {"grimme", "truhlar"}, "qrrho_entropy_method is unsupported")
    _require(
        policy["qrrho_enthalpy_treatment"] in {"head_gordon", "rrho_enthalpy"},
        "qrrho_enthalpy_treatment is unsupported",
    )
    policy["temperature_k"] = _finite(policy["temperature_k"], "temperature_k", positive=True)
    for name in ("entropy_frequency_cutoff_cm_1", "enthalpy_frequency_cutoff_cm_1"):
        policy[name] = _finite(policy[name], name, nonnegative=True)
    for name in ("frequency_scaling_factor", "zpe_scaling_factor"):
        policy[name] = _finite(policy[name], name, positive=True)
    return _freeze_mapping(policy, "thermochemistry_policy")


def _policy_identity(policy: Mapping[str, object]) -> tuple[str, str]:
    return _identified_payload("thermochemistry-policy", policy)


def _implementation_binding(policy: Mapping[str, object]) -> tuple[str, Mapping[str, object]]:
    binding = {
        "adapter_identity": policy["adapter_identity"],
        "adapter_version": policy["adapter_version"],
        "engine_artifact": policy["engine_artifact"],
        "engine_artifact_sha256": policy["engine_artifact_sha256"],
        "engine_identity": policy["engine_identity"],
        "engine_version": policy["engine_version"],
    }
    identity, _payload_hash = _identified_payload("goodvibes-implementation", binding)
    return identity, _freeze_mapping(binding, "goodvibes_implementation_binding")


def _standard_state_binding(policy: Mapping[str, object]) -> Mapping[str, object]:
    temperature = float(policy["temperature_k"])
    if policy["standard_state"] == "1atm":
        return _freeze_mapping(
            {
                "conversion": "ideal_gas_c_equals_p_over_rt",
                "derived_concentration_mol_per_l": (
                    _STANDARD_PRESSURE_KPA / (_GAS_CONSTANT_J_PER_MOL_K * temperature)
                ),
                "gas_constant_j_per_mol_k": _GAS_CONSTANT_J_PER_MOL_K,
                "kind": "1atm",
                "pressure_kpa": _STANDARD_PRESSURE_KPA,
                "temperature_k": temperature,
            },
            "standard_state_binding",
        )
    return _freeze_mapping(
        {
            "concentration_mol_per_l": 1.0,
            "conversion": "exact_molar_concentration",
            "kind": "1M",
            "temperature_k": temperature,
        },
        "standard_state_binding",
    )


def _normalize_method(value: object) -> tuple[str, Mapping[str, object]]:
    supplied = _closed_mapping(value, _METHOD_KEYS, "method_compatibility_binding")
    normalized = {key: _string(supplied[key], f"method_compatibility_binding.{key}") for key in supplied}
    _require(
        normalized["symmetry_number_convention"]
        == "gaussian_output_required",
        "method symmetry convention conflicts with the closed policy",
    )
    frozen = _freeze_mapping(normalized, "method_compatibility_binding")
    identity, _payload_hash = _identified_payload("thermochemistry-method", frozen)
    return identity, frozen


def _normalize_provenance(value: object) -> Mapping[str, object]:
    supplied = _closed_mapping(value, _PROVENANCE_KEYS, "source_provenance")
    raw_log_sha256 = _sha256(
        supplied["source_gaussian_log_sha256"], "source_gaussian_log_sha256"
    )
    supplied_symmetry = _closed_mapping(
        supplied["symmetry_provenance"],
        _SYMMETRY_PROVENANCE_KEYS,
        "symmetry_provenance",
    )
    symmetry_policy = _closed_mapping(
        supplied_symmetry["symmetry_policy"],
        _SYMMETRY_POLICY_KEYS,
        "symmetry_provenance.symmetry_policy",
    )
    _require(
        symmetry_policy["mode"] == "gaussian_output_required"
        and type(symmetry_policy["mode"]) is str,
        "symmetry policy mode is unsupported",
    )
    _require(
        symmetry_policy["external_detection"] == "disabled"
        and type(symmetry_policy["external_detection"]) is str,
        "external symmetry detection must be disabled",
    )
    _require(
        supplied_symmetry["goodvibes_symm"] is False,
        "GoodVibes external symmetry detection must be disabled",
    )
    reported_symmetry_number = supplied_symmetry["reported_rotational_symmetry_number"]
    parsed_symmetry_number = supplied_symmetry["goodvibes_parsed_symmno"]
    observation_count = supplied_symmetry["explicit_symmetry_observation_count"]
    _require(
        type(reported_symmetry_number) is int and reported_symmetry_number >= 1,
        "reported symmetry number is invalid",
    )
    _require(
        type(parsed_symmetry_number) is int and parsed_symmetry_number == reported_symmetry_number,
        "GoodVibes parsed symmetry number does not match reported symmetry",
    )
    _require(
        type(observation_count) is int and observation_count >= 1,
        "explicit symmetry observation count is invalid",
    )
    _require(
        supplied_symmetry["raw_gaussian_log_sha256"] == raw_log_sha256,
        "symmetry provenance raw Gaussian log SHA-256 mismatch",
    )
    normalized = {
        "source_result_id": _string(supplied["source_result_id"], "source_result_id"),
        "source_result_payload_sha256": _sha256(
            supplied["source_result_payload_sha256"], "source_result_payload_sha256"
        ),
        "source_gaussian_log_sha256": raw_log_sha256,
        "result_contract_identity": _string(
            supplied["result_contract_identity"], "result_contract_identity"
        ),
        "evidence_disposition": supplied["evidence_disposition"],
        "output_reported_point_group": _string(
            supplied["output_reported_point_group"], "output_reported_point_group"
        ),
        "symmetry_provenance": {
            "symmetry_policy": dict(symmetry_policy),
            "goodvibes_symm": False,
            "reported_rotational_symmetry_number": reported_symmetry_number,
            "explicit_symmetry_observation_count": observation_count,
            "raw_gaussian_log_sha256": raw_log_sha256,
            "goodvibes_parsed_symmno": parsed_symmetry_number,
        },
    }
    _require(
        normalized["evidence_disposition"]
        in {"closed_synthetic_contract_fixture", "persisted_result_contract"},
        "evidence_disposition is unsupported",
    )
    return _freeze_mapping(normalized, "source_provenance")


def _normalize_components(
    value: object,
    keys: set[str],
    label: str,
    temperature: float,
    policy: Mapping[str, object],
) -> Mapping[str, object]:
    supplied = _closed_mapping(value, keys, label)
    normalized = dict(supplied)
    for key in keys:
        if key.endswith("_hartree") or key.endswith("_per_kelvin"):
            normalized[key] = _finite(supplied[key], f"{label}.{key}")
    if label == "treated_qrrho":
        _require(
            normalized["entropy_treatment"] == policy["qrrho_entropy_method"],
            "treated entropy does not match policy",
        )
        _require(
            normalized["enthalpy_treatment"] == policy["qrrho_enthalpy_treatment"],
            "treated enthalpy does not match policy",
        )
    expected_gibbs = normalized["enthalpy_hartree"] - temperature * normalized["entropy_hartree_per_kelvin"]
    _require(
        math.isclose(expected_gibbs, normalized["gibbs_free_energy_hartree"], rel_tol=1e-12, abs_tol=1e-12),
        f"{label} Gibbs components are inconsistent",
    )
    return _freeze_mapping(normalized, label)


def _normalize_observation(value: object) -> Mapping[str, object]:
    supplied = _closed_mapping(value, _OBSERVATION_KEYS, "thermochemistry observation")
    policy = _normalize_policy(supplied["thermochemistry_policy"])
    temperature = _finite(supplied["temperature_k"], "observation temperature_k", positive=True)
    _require(temperature == policy["temperature_k"], "observation temperature does not match policy")
    _require(supplied["standard_state"] == policy["standard_state"], "observation standard state does not match policy")
    method_id, method = _normalize_method(supplied["method_compatibility_binding"])
    provenance = _normalize_provenance(supplied["source_provenance"])
    _require(
        provenance["result_contract_identity"] == method["result_contract_identity"],
        "source Result contract does not match method binding",
    )
    degeneracy = supplied["degeneracy"]
    _require(type(degeneracy) is int and degeneracy >= 1, "degeneracy must be an exact positive integer")
    policy_id, policy_hash = _policy_identity(policy)
    implementation_id, _binding = _implementation_binding(policy)
    return _freeze_mapping(
        {
            "degeneracy": degeneracy,
            "degeneracy_rationale": _string(supplied["degeneracy_rationale"], "degeneracy_rationale"),
            "goodvibes_implementation_id": implementation_id,
            "member_id": _string(supplied["member_id"], "member_id"),
            "method_compatibility_binding": method,
            "method_compatibility_id": method_id,
            "raw_rrho": _normalize_components(
                supplied["raw_rrho"], _RAW_KEYS, "raw_rrho", temperature, policy
            ),
            "source_provenance": provenance,
            "standard_state": supplied["standard_state"],
            "temperature_k": temperature,
            "thermochemistry_policy": policy,
            "thermochemistry_policy_id": policy_id,
            "thermochemistry_policy_payload_sha256": policy_hash,
            "treated_qrrho": _normalize_components(
                supplied["treated_qrrho"], _TREATED_KEYS, "treated_qrrho", temperature, policy
            ),
        },
        "thermochemistry observation",
    )


def _validate_conformer_ensemble(value: object) -> ConformerEnsemble:
    _require(isinstance(value, ConformerEnsemble), "conformer_ensemble must be a ConformerEnsemble")
    assert isinstance(value, ConformerEnsemble)
    expected_id, expected_hash = _identified_payload("conformer-ensemble", value._identity_payload())
    _require(value.conformer_ensemble_id == expected_id, "ConformerEnsemble identity drift")
    _require(value.payload_sha256 == expected_hash, "ConformerEnsemble payload drift")
    return value


def _log_positive_integer(value: int) -> float:
    bits = value.bit_length()
    if bits <= 53:
        return math.log(value)
    shift = bits - 53
    leading = value >> shift
    return math.log(leading) + shift * math.log(2.0)


def _build_thermodynamic_ensemble(
    conformer_ensemble: ConformerEnsemble,
    observations: Sequence[Mapping[str, object]],
) -> ThermodynamicEnsemble:
    ensemble = _validate_conformer_ensemble(conformer_ensemble)
    eligible = ensemble.thermodynamic_eligible_members
    _require(bool(eligible), "thermodynamic eligible member set is empty")
    _require(
        all(isinstance(member_id, str) and bool(member_id) and member_id == member_id.strip() for member_id in eligible),
        "thermodynamic eligible member identifiers are invalid",
    )
    _require(len(eligible) == len(set(eligible)), "thermodynamic eligible member set contains duplicates")
    ensemble_member_ids = tuple(member.get("member_id") for member in ensemble.members)
    _require(
        all(isinstance(member_id, str) and bool(member_id) for member_id in ensemble_member_ids),
        "ConformerEnsemble member identifiers are invalid",
    )
    _require(len(ensemble_member_ids) == len(set(ensemble_member_ids)), "ConformerEnsemble members contain duplicates")
    _require(
        set(eligible).issubset(set(ensemble_member_ids)),
        "thermodynamic eligible member is absent from ConformerEnsemble members",
    )
    _require(
        isinstance(observations, Sequence) and not isinstance(observations, (str, bytes, bytearray)),
        "observations must be a finite sequence",
    )
    normalized = tuple(_normalize_observation(item) for item in observations)
    member_ids = tuple(item["member_id"] for item in normalized)
    _require(len(member_ids) == len(set(member_ids)), "duplicate thermochemistry observation")
    supplied = set(member_ids)
    expected = set(eligible)
    missing = tuple(member_id for member_id in eligible if member_id not in supplied)
    extra = tuple(sorted(supplied - expected))
    _require(not missing, f"missing eligible thermochemistry members: {missing}")
    _require(not extra, f"extra thermochemistry members: {extra}")
    by_member = {item["member_id"]: item for item in normalized}
    ordered = tuple(by_member[member_id] for member_id in eligible)
    first = ordered[0]
    for item in ordered[1:]:
        _require(item["temperature_k"] == first["temperature_k"], "mixed temperature observations")
        _require(item["standard_state"] == first["standard_state"], "mixed standard-state observations")
        _require(
            item["method_compatibility_id"] == first["method_compatibility_id"],
            "mixed method observations",
        )
        _require(
            item["thermochemistry_policy_id"] == first["thermochemistry_policy_id"],
            "mixed qRRHO or GoodVibes policy observations",
        )
        _require(
            item["goodvibes_implementation_id"] == first["goodvibes_implementation_id"],
            "mixed GoodVibes implementation observations",
        )
    temperature = float(first["temperature_k"])
    rt = _GAS_CONSTANT_HARTREE_PER_MOL_K * temperature
    gibbs = {item["member_id"]: float(item["treated_qrrho"]["gibbs_free_energy_hartree"]) for item in ordered}
    reference_member = min(eligible, key=lambda member_id: (gibbs[member_id], member_id))
    reference_gibbs = gibbs[reference_member]
    log_weights = {
        item["member_id"]: _log_positive_integer(item["degeneracy"])
        - (gibbs[item["member_id"]] - reference_gibbs) / rt
        for item in ordered
    }
    maximum_log_weight = max(log_weights.values())
    scaled_partition = math.fsum(
        math.exp(log_weights[member_id] - maximum_log_weight) for member_id in eligible
    )
    log_partition = maximum_log_weight + math.log(scaled_partition)
    populations = {
        member_id: math.exp(log_weights[member_id] - log_partition) for member_id in eligible
    }
    population_sum = math.fsum(populations.values())
    normalization_error = abs(population_sum - 1.0)
    _require(
        normalization_error <= _POPULATION_TOLERANCE,
        "population normalization exceeded the numeric-only tolerance",
    )
    ensemble_gibbs = reference_gibbs - rt * log_partition
    _require(math.isfinite(ensemble_gibbs), "ensemble treated free energy is non-finite")
    public_members = []
    for item in ordered:
        member_id = item["member_id"]
        public_members.append(
            {
                "degeneracy": item["degeneracy"],
                "degeneracy_rationale": item["degeneracy_rationale"],
                "goodvibes_implementation_id": item["goodvibes_implementation_id"],
                "member_id": member_id,
                "method_compatibility_id": item["method_compatibility_id"],
                "normalized_population": populations[member_id],
                "raw_rrho": item["raw_rrho"],
                "relative_statistical_weight": {
                    "log_value": log_weights[member_id],
                    "representation": "natural_log_relative_to_reference_gibbs",
                },
                "source_provenance": item["source_provenance"],
                "standard_state": item["standard_state"],
                "temperature_k": item["temperature_k"],
                "thermochemistry_policy_id": item["thermochemistry_policy_id"],
                "treated_qrrho": item["treated_qrrho"],
            }
        )
    policy = first["thermochemistry_policy"]
    implementation_id, implementation = _implementation_binding(policy)
    standard_state_binding = _standard_state_binding(policy)
    return ThermodynamicEnsemble._create(
        conformer_ensemble_id=ensemble.conformer_ensemble_id,
        conformer_ensemble_payload_sha256=ensemble.payload_sha256,
        source_member_ids=eligible,
        temperature_k=temperature,
        standard_state=first["standard_state"],
        standard_state_binding=standard_state_binding,
        gas_constant_binding={
            "gas_constant_hartree_per_mol_k": _GAS_CONSTANT_HARTREE_PER_MOL_K,
            "gas_constant_j_per_mol_k": _GAS_CONSTANT_J_PER_MOL_K,
            "joule_per_hartree_mol": _J_PER_HARTREE_MOL,
            "unit_convention": "per_mole_hartree_kelvin",
        },
        thermochemistry_policy_id=first["thermochemistry_policy_id"],
        thermochemistry_policy_payload_sha256=first["thermochemistry_policy_payload_sha256"],
        thermochemistry_policy=policy,
        goodvibes_implementation_id=implementation_id,
        goodvibes_implementation_binding=implementation,
        low_frequency_treatment={
            "enthalpy_frequency_cutoff_cm_1": policy["enthalpy_frequency_cutoff_cm_1"],
            "enthalpy_treatment": policy["qrrho_enthalpy_treatment"],
            "entropy_frequency_cutoff_cm_1": policy["entropy_frequency_cutoff_cm_1"],
            "entropy_method": policy["qrrho_entropy_method"],
            "frequency_scaling_factor": policy["frequency_scaling_factor"],
            "moment_of_inertia_treatment": policy["moment_of_inertia_treatment"],
            "scheme_identity": "goodvibes-4.3.0-qrrho",
            "symmetry_treatment": policy["symmetry_treatment"],
            "zpe_scaling_factor": policy["zpe_scaling_factor"],
        },
        method_compatibility_id=first["method_compatibility_id"],
        method_compatibility_binding=first["method_compatibility_binding"],
        member_observations=public_members,
        partition_evidence={
            "log_relative_partition_function": log_partition,
            "log_scale": maximum_log_weight,
            "reference_gibbs_hartree": reference_gibbs,
            "reference_member_id": reference_member,
            "representation": "stable_logsumexp",
            "scaled_relative_partition_function": scaled_partition,
        },
        population_normalization={
            "absolute_error": normalization_error,
            "numeric_tolerance": _POPULATION_TOLERANCE,
            "population_sum": population_sum,
            "status": "normalized",
            "tolerance_purpose": "floating_point_normalization_only_not_scientific_selection",
        },
        ensemble_treated_free_energy_hartree=ensemble_gibbs,
    )
