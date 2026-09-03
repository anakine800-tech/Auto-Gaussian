"""Private, fail-closed V31 thermochemistry normalization and aggregation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import math
import re

from auto_g16.conformer import ConformerEnsemble
from auto_g16.conformer.refinement_authority import _source
from auto_g16.result import ParseOutcome

from . import _goodvibes
from ._gaussian_thermo_facts import extract_gaussian_thermo_facts
from .models import ThermodynamicEnsemble, _freeze_mapping, _identified_payload, _payload_sha256


_STANDARD_PRESSURE_KPA = 101.325
_POPULATION_TOLERANCE = 1.0e-12
_REFERENCE_METHOD = re.compile(r"^(RO|R|U)(HF|B3LYP)$")
_POLICY_KEYS = {
    "adapter_identity", "adapter_version", "automatic_scaling_factor_lookup",
    "degeneracy_excludes_rotational_symmetry", "degeneracy_policy",
    "engine_artifact", "engine_artifact_sha256",
    "goodvibes_symmetry_detection", "goodvibes_version",
    "entropy_damping_function", "entropy_frequency_cutoff_cm1",
    "enthalpy_damping_function", "enthalpy_frequency_cutoff_cm1",
    "frequency_inversion", "frequency_scaling_factor", "moment_of_inertia",
    "oniom_frequency_blending", "qrrho_enthalpy_method", "qrrho_entropy_method",
    "solvent_free_space_correction", "spc_discovery", "standard_state",
    "symmetry_policy", "temperature_k", "zpe_scaling_factor",
}
_INPUT_KEYS = {
    "member_id", "source_result", "raw_gaussian_bytes", "method_binding",
    "degeneracy", "degeneracy_rationale",
}
_METHOD_KEYS = {
    "program", "method", "basis", "dispersion", "solvent", "reference",
    "charge", "multiplicity", "integration_grid", "scf_policy",
    "route_contract_version",
}
_MINIMUM_KEYS = {
    "authority_schema", "two_stage_minimum_authority_id", "source", "method_id",
    "optimization", "frequency", "classification",
}
_OPTIMIZATION_KEYS = {
    "authority_schema", "optimization_geometry_authority_id", "source", "method_id",
    "calculation_plan", "prepared_input", "result", "selected_geometry",
    "recovered_atom_map", "v30_outcome",
}


class ThermochemistryError(ValueError):
    """The supplied exact V31 thermochemistry evidence does not close."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ThermochemistryError(message)


def _closed(value: object, keys: set[str], name: str) -> Mapping[str, object]:
    _require(isinstance(value, Mapping) and set(value) == keys, f"{name} fields are not exact")
    assert isinstance(value, Mapping)
    return value


def _text(value: object, name: str) -> str:
    _require(isinstance(value, str) and bool(value) and value == value.strip(), f"{name} is not canonical text")
    assert isinstance(value, str)
    return value


def _finite(value: object, name: str, *, positive: bool = False) -> float:
    _require(type(value) in {int, float} and math.isfinite(float(value)), f"{name} must be finite")
    result = float(value)
    if positive:
        _require(result > 0.0, f"{name} must be positive")
    return result


def _normalize_policy(value: object) -> Mapping[str, object]:
    supplied = dict(_closed(value, _POLICY_KEYS, "thermochemistry policy"))
    exact = {
        "adapter_identity": "auto-g16-goodvibes-functional-kernel-adapter",
        "adapter_version": 2,
        "engine_artifact": "goodvibes-4.3.0-py3-none-any.whl",
        "engine_artifact_sha256": "06476db73ee456c1fc941590374f2a30182baaf043f6b60dbef85ee77db93997",
        "goodvibes_version": "4.3.0",
        "qrrho_entropy_method": "grimme",
        "entropy_damping_function": "goodvibes_calc_damp_alpha_4",
        "qrrho_enthalpy_method": "head_gordon",
        "enthalpy_damping_function": "goodvibes_calc_damp_alpha_4",
        "symmetry_policy": "gaussian_rotational_symmetry_number_required",
        "goodvibes_symmetry_detection": False,
        "moment_of_inertia": "global_grimme_bav",
        "frequency_inversion": "forbidden",
        "spc_discovery": "forbidden",
        "solvent_free_space_correction": "none",
        "automatic_scaling_factor_lookup": False,
        "oniom_frequency_blending": "forbidden",
        "degeneracy_policy": "explicit_positive_integer_with_rationale",
        "degeneracy_excludes_rotational_symmetry": True,
    }
    for name, expected in exact.items():
        _require(supplied[name] == expected and type(supplied[name]) is type(expected), f"{name} is unsupported")
    _require(supplied["standard_state"] in {"1atm", "1M"}, "standard_state is unsupported")
    supplied["temperature_k"] = _finite(supplied["temperature_k"], "temperature_k", positive=True)
    for name in (
        "entropy_frequency_cutoff_cm1", "enthalpy_frequency_cutoff_cm1",
        "frequency_scaling_factor", "zpe_scaling_factor",
    ):
        supplied[name] = _finite(supplied[name], name, positive=True)
    return _freeze_mapping(supplied, "thermochemistry_policy")


def _policy_identity(policy: Mapping[str, object]) -> tuple[str, str]:
    return _identified_payload("thermochemistry-policy", policy)


def _implementation_binding(policy: Mapping[str, object]) -> tuple[str, Mapping[str, object]]:
    binding = {
        "adapter_identity": policy["adapter_identity"],
        "adapter_version": policy["adapter_version"],
        "engine_artifact": policy["engine_artifact"],
        "engine_artifact_sha256": policy["engine_artifact_sha256"],
        "goodvibes_version": policy["goodvibes_version"],
        "allowed_kernels": _goodvibes._ALLOWED_KERNEL_NAMES,
        "allowed_constants": _goodvibes._ALLOWED_CONSTANT_NAMES,
    }
    identity, _payload_hash = _identified_payload("functional-kernel-implementation", binding)
    return identity, _freeze_mapping(binding, "functional_kernel_implementation_binding")


def _standard_state_binding(policy: Mapping[str, object], gas_constant: float) -> Mapping[str, object]:
    temperature = float(policy["temperature_k"])
    if policy["standard_state"] == "1atm":
        concentration = _STANDARD_PRESSURE_KPA / (gas_constant * temperature)
        binding = {
            "kind": "1atm", "pressure_kpa": _STANDARD_PRESSURE_KPA,
            "temperature_k": temperature, "conversion": "ideal_gas_c_equals_p_over_rt",
            "concentration_mol_per_l": concentration,
        }
    else:
        binding = {
            "kind": "1M", "temperature_k": temperature,
            "conversion": "exact_molar_concentration", "concentration_mol_per_l": 1.0,
        }
    return _freeze_mapping(binding, "standard_state_binding")


def _validate_ensemble(value: object, name: str) -> ConformerEnsemble:
    _require(type(value) is ConformerEnsemble, f"{name} must be a ConformerEnsemble")
    assert isinstance(value, ConformerEnsemble)
    identity, payload_hash = _identified_payload("conformer-ensemble", value._identity_payload())
    _require(
        identity == value.conformer_ensemble_id and payload_hash == value.payload_sha256,
        f"{name} identity is stale",
    )
    return value


def _validate_predecessor_chain(
    refined: ConformerEnsemble,
    predecessor: ConformerEnsemble,
) -> None:
    _require(
        refined.revision == predecessor.revision + 1
        and refined.supersedes_conformer_ensemble_id
        == predecessor.conformer_ensemble_id,
        "refined ensemble does not name the exact immediate predecessor",
    )
    inherited = (
        "project_id",
        "calculation_plan_id",
        "calculation_plan_revision",
        "sampling_profile_id",
        "sampling_profile_payload_sha256",
        "species_binding",
        "stereochemistry_binding",
    )
    _require(
        all(getattr(refined, name) == getattr(predecessor, name) for name in inherited),
        "refined ensemble inherited domain bindings differ from predecessor",
    )


def _validate_nonlinear_domain(ensemble: ConformerEnsemble, member: Mapping[str, object]) -> None:
    species = ensemble.species_binding
    elements = species.get("elements")
    coordinates = member.get("coordinates_angstrom")
    _require(isinstance(elements, tuple) and len(elements) >= 3, "initial thermochemistry domain requires N >= 3")
    _require(
        species.get("multiplicity") == 1
        and species.get("electronic_state_family") == "reviewed_closed_shell_singlet",
        "initial thermochemistry domain requires a reviewed closed-shell singlet",
    )
    _require(isinstance(coordinates, tuple) and len(coordinates) == len(elements), "current minimum coordinates are unavailable")
    points = []
    for point in coordinates:
        _require(
            isinstance(point, tuple) and len(point) == 3
            and all(type(item) in {int, float} and math.isfinite(float(item)) for item in point),
            "current minimum coordinates are malformed",
        )
        points.append(tuple(float(item) for item in point))
    origin = points[0]
    vectors = [tuple(point[index] - origin[index] for index in range(3)) for point in points[1:]]
    baseline = next((vector for vector in vectors if any(component != 0.0 for component in vector)), None)
    _require(baseline is not None, "degenerate geometry is unsupported")
    nonlinear = any(
        any(component != 0.0 for component in (
            baseline[1] * vector[2] - baseline[2] * vector[1],
            baseline[2] * vector[0] - baseline[0] * vector[2],
            baseline[0] * vector[1] - baseline[1] * vector[0],
        ))
        for vector in vectors
    )
    _require(nonlinear, "linear geometry is unsupported")


def _normalize_method(
    supplied: object,
    *,
    ensemble: ConformerEnsemble,
    minimum: Mapping[str, object],
    result: ParseOutcome,
) -> tuple[str, Mapping[str, object]]:
    method = dict(_closed(supplied, _METHOD_KEYS, "method binding"))
    for name in _METHOD_KEYS - {"charge", "multiplicity"}:
        _text(method[name], f"method_binding.{name}")
    _require(type(method["charge"]) is int and method["charge"] == ensemble.species_binding["formal_charge"], "method charge differs from species")
    _require(type(method["multiplicity"]) is int and method["multiplicity"] == 1, "method multiplicity is not singlet")
    _require(method["program"] == "gaussian16", "method program is not Gaussian 16")
    _require(method["reference"] == "restricted_closed_shell", "method reference is not restricted closed shell")
    match = _REFERENCE_METHOD.fullmatch(method["method"])
    _require(match is not None and match.group(1) == "R", "electronic method is not a restricted reference")
    _require(method["route_contract_version"] == "auto_g16_v31_conformer_dft_route_1", "route/profile semantic version is unsupported")
    method_id = _payload_sha256({
        "domain": "v31-conformer-dft-method/1", "method": method, "reference_family": "restricted",
    })
    _require(minimum["method_id"] == method_id, "method binding differs from current minimum authority")
    result_contract = {
        "parser_name": result.parser_name,
        "parser_version": result.parser_version,
        "result_kind": result.result_kind,
    }
    binding = {**method, "result_contract": result_contract}
    compatibility_id, _payload_hash = _identified_payload("thermochemistry-method", binding)
    return compatibility_id, _freeze_mapping(binding, "method_compatibility_binding")


def _validate_member(
    refined_ensemble: ConformerEnsemble,
    predecessor_ensemble: ConformerEnsemble,
    member_id: str,
) -> tuple[Mapping[str, object], Mapping[str, object], Mapping[str, object]]:
    refined_matches = tuple(
        member for member in refined_ensemble.members
        if member.get("member_id") == member_id
    )
    predecessor_matches = tuple(
        member for member in predecessor_ensemble.members
        if member.get("member_id") == member_id
    )
    _require(len(refined_matches) == 1, "eligible member must resolve exactly once in refined ensemble")
    _require(
        len(predecessor_matches) == 1,
        "eligible member must resolve exactly once in predecessor ensemble",
    )
    member = refined_matches[0]
    predecessor_member = predecessor_matches[0]
    _require(member.get("post_dft_status") == "validated_minimum", "eligible member is not a current validated minimum")
    _require(member.get("post_dft_duplicate_of_member_id") is None, "duplicate member cannot enter thermochemistry")
    _require(member.get("negative_frequency_authority") is None, "negative-Freq member cannot enter thermochemistry")
    minimum = _closed(member.get("two_stage_minimum_authority"), _MINIMUM_KEYS, "two-stage minimum authority")
    source = minimum["source"]
    expected_source = _source(predecessor_ensemble, predecessor_member)
    _require(
        source == expected_source,
        "minimum authority source differs from exact predecessor member",
    )
    optimization = _closed(minimum["optimization"], _OPTIMIZATION_KEYS, "optimization authority")
    optimization_payload = {
        key: optimization[key] for key in optimization if key != "optimization_geometry_authority_id"
    }
    _require(
        optimization["optimization_geometry_authority_id"]
        == "v31-opt-geometry-authority-" + _payload_sha256(
            {"domain": "v31-opt-geometry-authority", "payload": optimization_payload}
        ),
        "optimization authority identity is stale",
    )
    _require(
        optimization["authority_schema"] == "v31-conformer-optimization-geometry-authority/1"
        and optimization["source"] == source
        and optimization["method_id"] == minimum["method_id"],
        "minimum and optimization authority lineage differ",
    )
    _require(
        member.get("optimization_geometry_authority") == optimization,
        "refined member does not retain the same optimization authority",
    )
    frequency = _closed(minimum["frequency"], {"calculation_plan", "prepared_input", "result"}, "frequency authority")
    _require(
        isinstance(frequency["calculation_plan"], Mapping)
        and set(frequency["calculation_plan"]) == {"calculation_plan_id", "revision", "intent_sha256"}
        and isinstance(frequency["prepared_input"], Mapping),
        "frequency plan/input lineage is malformed",
    )
    _require(
        minimum["authority_schema"] == "v31-conformer-two-stage-minimum-authority/1"
        and minimum["classification"] == "VALIDATED_TWO_STAGE_MINIMUM",
        "member authority is not a validated two-stage minimum",
    )
    _validate_nonlinear_domain(refined_ensemble, member)
    return member, minimum, expected_source


def _log_positive_integer(value: int) -> float:
    bits = value.bit_length()
    if bits <= 53:
        return math.log(value)
    shift = bits - 53
    return math.log(value >> shift) + shift * math.log(2.0)


def _build_thermodynamic_ensemble(
    refined_ensemble: ConformerEnsemble,
    predecessor_ensemble: ConformerEnsemble,
    member_inputs: Sequence[Mapping[str, object]],
    thermochemistry_policy: Mapping[str, object],
) -> ThermodynamicEnsemble:
    """Build the one public ThermodynamicEnsemble from the exact eligible projection."""

    ensemble = _validate_ensemble(refined_ensemble, "refined ensemble")
    predecessor = _validate_ensemble(predecessor_ensemble, "predecessor ensemble")
    _validate_predecessor_chain(ensemble, predecessor)
    policy = _normalize_policy(thermochemistry_policy)
    eligible = ensemble.thermodynamic_eligible_members
    _require(bool(eligible), "thermodynamic eligible member set is empty")
    _require(len(eligible) == len(set(eligible)), "thermodynamic eligible member set has duplicates")
    _require(
        isinstance(member_inputs, Sequence) and not isinstance(member_inputs, (str, bytes, bytearray)),
        "member inputs must be a finite sequence",
    )
    supplied_inputs = tuple(_closed(item, _INPUT_KEYS, "member input") for item in member_inputs)
    supplied_ids = tuple(_text(item["member_id"], "member_id") for item in supplied_inputs)
    _require(len(supplied_ids) == len(set(supplied_ids)), "duplicate member input")
    _require(set(supplied_ids) == set(eligible), "member inputs must equal the complete thermodynamic eligible set")
    by_member = {item["member_id"]: item for item in supplied_inputs}
    _unused, constants = _goodvibes._load_goodvibes_kernels()
    gas_constant = constants["GAS_CONSTANT"]
    joule_to_au = constants["J_TO_AU"]
    standard_state = _standard_state_binding(policy, gas_constant)
    normalized_members = []
    for member_id in eligible:
        item = by_member[member_id]
        _member, minimum, expected_source = _validate_member(
            ensemble, predecessor, member_id
        )
        result = item["source_result"]
        _require(type(result) is ParseOutcome, "member source_result must be an exact ParseOutcome")
        assert isinstance(result, ParseOutcome)
        method_id, method = _normalize_method(
            item["method_binding"], ensemble=ensemble, minimum=minimum, result=result
        )
        thermo_facts = extract_gaussian_thermo_facts(
            raw_gaussian_bytes=item["raw_gaussian_bytes"],
            source_result=result,
            minimum_authority=minimum,
        )
        frequencies = minimum["frequency"]["result"]["frequencies_cm1"]  # type: ignore[index]
        _require(
            type(frequencies) is tuple and bool(frequencies)
            and all(type(value) is float and math.isfinite(value) and value > 0.0 for value in frequencies),
            "minimum frequencies must be exact positive floats",
        )
        electronic_energy = result.facts.get("final_energy_hartree")
        _require(type(electronic_energy) is float and math.isfinite(electronic_energy), "frequency Result final electronic energy is missing")
        degeneracy = item["degeneracy"]
        _require(type(degeneracy) is int and degeneracy >= 1, "degeneracy must be an exact positive integer")
        rationale = _text(item["degeneracy_rationale"], "degeneracy_rationale")
        computed = _goodvibes.functional_thermochemistry(
            electronic_energy_hartree=electronic_energy,
            frequencies_cm1=frequencies,
            molecular_mass_amu=thermo_facts["molecular_mass_amu"],  # type: ignore[arg-type]
            rotational_symmetry_number=thermo_facts["rotational_symmetry_number"],  # type: ignore[arg-type]
            rotational_temperatures_kelvin=thermo_facts["rotational_temperatures_kelvin"],  # type: ignore[arg-type]
            temperature_k=policy["temperature_k"],  # type: ignore[arg-type]
            concentration_mol_per_l=standard_state["concentration_mol_per_l"],  # type: ignore[arg-type]
            entropy_frequency_cutoff_cm1=policy["entropy_frequency_cutoff_cm1"],  # type: ignore[arg-type]
            enthalpy_frequency_cutoff_cm1=policy["enthalpy_frequency_cutoff_cm1"],  # type: ignore[arg-type]
            frequency_scaling_factor=policy["frequency_scaling_factor"],  # type: ignore[arg-type]
            zpe_scaling_factor=policy["zpe_scaling_factor"],  # type: ignore[arg-type]
        )
        normalized_members.append({
            "member_id": member_id,
            "source_refined_conformer_ensemble_id": ensemble.conformer_ensemble_id,
            "source_refined_conformer_ensemble_revision": ensemble.revision,
            "two_stage_minimum_authority_id": minimum["two_stage_minimum_authority_id"],
            "method_compatibility_id": method_id,
            "method_compatibility_binding": method,
            "source_provenance": {
                "predecessor_lineage": {
                    "conformer_ensemble_id": predecessor.conformer_ensemble_id,
                    "conformer_ensemble_payload_sha256": predecessor.payload_sha256,
                    "member_source": expected_source,
                },
                "source_result_id": thermo_facts["source_result_id"],
                "source_result_payload_sha256": thermo_facts["source_result_payload_sha256"],
                "source_artifact": thermo_facts["source_artifact"],
                "job_section": thermo_facts["job_section"],
                "gaussian_thermo_facts": {
                    key: thermo_facts[key]
                    for key in (
                        "molecular_mass_amu", "rotational_symmetry_number",
                        "rotational_symmetry_observation_count",
                        "rotational_temperatures_kelvin", "point_group_diagnostic",
                    )
                },
            },
            "temperature_k": policy["temperature_k"],
            "standard_state": policy["standard_state"],
            "raw_rrho": computed["raw_rrho"],
            "treated_qrrho": computed["treated_qrrho"],
            "degeneracy": degeneracy,
            "degeneracy_rationale": rationale,
            "inclusion_status": "included_thermodynamic_eligible",
        })
    first = normalized_members[0]
    _require(
        all(item["method_compatibility_id"] == first["method_compatibility_id"] for item in normalized_members),
        "mixed method thermochemistry is forbidden",
    )
    temperature = float(policy["temperature_k"])
    rt = gas_constant / joule_to_au * temperature
    gibbs = {
        item["member_id"]: float(item["treated_qrrho"]["gibbs_free_energy_hartree"])  # type: ignore[index]
        for item in normalized_members
    }
    reference_member = min(eligible, key=lambda member_id: (gibbs[member_id], member_id))
    reference_gibbs = gibbs[reference_member]
    log_weights = {
        item["member_id"]: _log_positive_integer(item["degeneracy"])  # type: ignore[arg-type]
        - (gibbs[item["member_id"]] - reference_gibbs) / rt
        for item in normalized_members
    }
    log_scale = max(log_weights.values())
    scaled_partition = math.fsum(math.exp(log_weights[member_id] - log_scale) for member_id in eligible)
    log_partition = log_scale + math.log(scaled_partition)
    populations = {member_id: math.exp(log_weights[member_id] - log_partition) for member_id in eligible}
    population_sum = math.fsum(populations.values())
    normalization_error = abs(population_sum - 1.0)
    _require(normalization_error <= _POPULATION_TOLERANCE, "Boltzmann populations do not normalize")
    ensemble_gibbs = reference_gibbs - rt * log_partition
    _require(math.isfinite(ensemble_gibbs), "ensemble treated free energy is non-finite")
    public_members = tuple({
        **item,
        "relative_statistical_weight": {
            "log_value": log_weights[item["member_id"]],
            "representation": "natural_log_relative_to_reference_gibbs",
        },
        "normalized_population": populations[item["member_id"]],
    } for item in normalized_members)
    policy_id, policy_hash = _policy_identity(policy)
    implementation_id, implementation = _implementation_binding(policy)
    return ThermodynamicEnsemble._create(
        conformer_ensemble_id=ensemble.conformer_ensemble_id,
        conformer_ensemble_payload_sha256=ensemble.payload_sha256,
        conformer_ensemble_revision=ensemble.revision,
        source_member_ids=eligible,
        temperature_k=temperature,
        standard_state=policy["standard_state"],
        standard_state_binding=standard_state,
        gas_constant_binding={
            "gas_constant_j_per_mol_k": gas_constant,
            "joule_per_hartree_mol": joule_to_au,
            "gas_constant_hartree_per_mol_k": gas_constant / joule_to_au,
            "unit_convention": "per_mole_hartree_kelvin",
        },
        thermochemistry_policy_id=policy_id,
        thermochemistry_policy_payload_sha256=policy_hash,
        thermochemistry_policy=policy,
        functional_kernel_implementation_id=implementation_id,
        functional_kernel_implementation_binding=implementation,
        low_frequency_treatment={
            "entropy_method": policy["qrrho_entropy_method"],
            "entropy_frequency_cutoff_cm1": policy["entropy_frequency_cutoff_cm1"],
            "entropy_damping_function": policy["entropy_damping_function"],
            "enthalpy_method": policy["qrrho_enthalpy_method"],
            "enthalpy_frequency_cutoff_cm1": policy["enthalpy_frequency_cutoff_cm1"],
            "enthalpy_damping_function": policy["enthalpy_damping_function"],
            "frequency_scaling_factor": policy["frequency_scaling_factor"],
            "zpe_scaling_factor": policy["zpe_scaling_factor"],
            "moment_of_inertia": policy["moment_of_inertia"],
            "scheme_identity": "goodvibes-4.3.0-functional-grimme-head-gordon",
            "degeneracy_excludes_rotational_symmetry": policy["degeneracy_excludes_rotational_symmetry"],
        },
        method_compatibility_id=first["method_compatibility_id"],
        method_compatibility_binding=first["method_compatibility_binding"],
        member_observations=public_members,
        partition_evidence={
            "reference_member_id": reference_member,
            "reference_gibbs_hartree": reference_gibbs,
            "representation": "stable_logsumexp",
            "log_scale": log_scale,
            "scaled_relative_partition_function": scaled_partition,
            "log_relative_partition_function": log_partition,
        },
        population_normalization={
            "population_sum": population_sum,
            "absolute_error": normalization_error,
            "numeric_tolerance": _POPULATION_TOLERANCE,
            "status": "normalized",
            "tolerance_purpose": "floating_point_normalization_only_not_scientific_selection",
        },
        ensemble_treated_free_energy_hartree=ensemble_gibbs,
    )
