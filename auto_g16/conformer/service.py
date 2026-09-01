"""Deterministic, offline-only builders for the closed V31 conformer core."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from math import isfinite
import re

from ._geometry import minimum_pair_distance, pair_distance, union_clusters
from .models import ConformerEnsemble, ConformerError, SamplingProfile, _payload_sha256, _plain_value


_SOURCE_KEYS = {
    "sampling_profile_id", "provider", "mode", "sampling_configuration_identity",
    "source_run_id", "source_set_id", "source_member_index", "source_geometry_identity",
    "source_artifact_identity", "seed", "replica_index",
}
_OBSERVATION_KEYS = {
    "member_id", "atom_order", "atom_correspondence", "elements", "explicit_hydrogens",
    "fragment_ids", "bonds", "formal_charge", "multiplicity", "electronic_state_family",
    "stereochemistry_binding", "coordinates_angstrom", "source_binding", "sampling_energy",
    "descriptors", "relevance_tags",
}
_STATE_CHANGE_REASONS = {
    "atom_map_or_order_drift", "element_inventory_changed", "explicit_hydrogen_identity_changed",
    "fragment_membership_changed", "component_count_changed", "formal_charge_changed",
    "multiplicity_changed", "electronic_state_family_changed", "covalent_graph_changed",
    "stereochemistry_drift",
}
_COVERAGE_STATUSES = {"sufficient", "uncertain", "insufficient"}


@dataclass(frozen=True, slots=True)
class _AuditedMember:
    member_id: str
    observation: Mapping[str, object]
    status: str
    reasons: tuple[str, ...]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ConformerError(message)


def _keys(value: object, expected: set[str], label: str) -> Mapping[str, object]:
    _require(isinstance(value, Mapping), f"{label} must be a mapping")
    assert isinstance(value, Mapping)
    _require(set(value) == expected, f"{label} must contain exactly {sorted(expected)}")
    return value


def _text(value: object, label: str) -> str:
    _require(
        isinstance(value, str) and bool(value) and value == value.strip() and "\x00" not in value,
        f"{label} must be a non-empty canonical string",
    )
    assert isinstance(value, str)
    return value


def _semantic_value(value: object, label: str) -> str:
    result = _text(value, label)
    lowered = result.lower()
    executable_suffixes = (".exe", ".com", ".bat", ".cmd", ".sh", ".bin", ".py")
    path_like = (
        "/" in result
        or "\\" in result
        or ":" in result
        or any(character.isspace() for character in result)
        or any(token in result for token in ("$", "%", "~", ";"))
        or result.startswith(".")
        or result.endswith(".")
        or ".." in result
        or lowered.endswith(executable_suffixes)
        or lowered in {"path", "$path", "%path%"}
        or re.fullmatch(r"[a-zA-Z]:.*", result) is not None
    )
    _require(not path_like, f"{label} must be semantic data, never a filesystem/executable/PATH-like identity")
    _require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", result) is not None, f"{label} has unsupported semantic identity syntax")
    return result


def _semantic_identity(value: object, label: str) -> str:
    result = _semantic_value(value, label)
    _require(result.lower() not in {"crest", "xtb", "python", "python3"}, f"{label} cannot be a bare executable name")
    _require(any(separator in result for separator in ("-", "_", ".")), f"{label} must be an explicit semantic identity")
    return result


def _semantic_version(value: object, label: str) -> str:
    result = _text(value, label)
    lowered = result.lower()
    executable_suffixes = (".exe", ".com", ".bat", ".cmd", ".sh", ".bin", ".py")
    path_like = (
        "/" in result
        or "\\" in result
        or ":" in result
        or any(character.isspace() for character in result)
        or any(token in result for token in ("$", "%", "~", ";"))
        or result.startswith(".")
        or result.endswith(".")
        or ".." in result
        or lowered.endswith(executable_suffixes)
        or "path" in re.split(r"[.+-]", lowered)
    )
    _require(not path_like, f"{label} must be semantic version data, never a filesystem/executable/PATH-like identity")
    _require(
        re.fullmatch(
            r"(?:0|[1-9][0-9]*)\."
            r"(?:0|[1-9][0-9]*)\."
            r"(?:0|[1-9][0-9]*)"
            r"(?:-(?:0|[1-9][0-9]*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*)"
            r"(?:\.(?:0|[1-9][0-9]*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*))*)?"
            r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?",
            result,
        )
        is not None,
        f"{label} must be an exact semantic version, never an executable identity",
    )
    return result


def _positive_integer(value: object, label: str) -> int:
    _require(type(value) is int and value > 0, f"{label} must be a positive integer")
    assert isinstance(value, int)
    return value


def _nonnegative_integer(value: object, label: str) -> int:
    _require(type(value) is int and value >= 0, f"{label} must be a non-negative integer")
    assert isinstance(value, int)
    return value


def _finite(value: object, label: str, *, positive: bool = False, nonnegative: bool = False) -> float:
    _require(type(value) in {int, float} and isfinite(value), f"{label} must be finite")
    result = float(value)
    if positive:
        _require(result > 0.0, f"{label} must be positive")
    if nonnegative:
        _require(result >= 0.0, f"{label} must be non-negative")
    return result


def _string_tuple(value: object, label: str, *, allow_empty: bool = False, unique: bool = True) -> tuple[str, ...]:
    _require(isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)), f"{label} must be a sequence")
    assert isinstance(value, Sequence)
    result = tuple(_text(item, f"{label}[{index}]") for index, item in enumerate(value))
    _require(allow_empty or bool(result), f"{label} must not be empty")
    if unique:
        _require(len(result) == len(set(result)), f"{label} must not contain duplicates")
    return result


def _tagged_parameter(value: object, label: str, *, unit: str, positive: bool = False, nonnegative: bool = False) -> Mapping[str, object]:
    parameter = _keys(value, {"disposition", "value", "unit"}, label)
    _require(parameter["disposition"] == "applicable", f"{label}.disposition must be applicable")
    _require(parameter["unit"] == unit, f"{label}.unit must be {unit!r}")
    _finite(parameter["value"], f"{label}.value", positive=positive, nonnegative=nonnegative)
    return parameter


def _normalized_bonds(value: object, atom_order: Sequence[object]) -> tuple[tuple[str, str, float], ...] | None:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return None
    normalized: list[tuple[str, str, float]] = []
    for bond in value:
        if not isinstance(bond, Sequence) or isinstance(bond, (str, bytes, bytearray)) or len(bond) != 3:
            return None
        left, right, order = bond
        if (
            not isinstance(left, str) or not isinstance(right, str) or left not in atom_order
            or right not in atom_order or left == right or type(order) not in {int, float}
            or not isfinite(order) or order <= 0.0
        ):
            return None
        normalized.append((min(left, right), max(left, right), float(order)))
    if len(normalized) != len(set(normalized)):
        return None
    return tuple(sorted(normalized))


def _graph_components(atom_order: Sequence[str], bonds: Sequence[tuple[str, str, float]]) -> tuple[frozenset[str], ...]:
    neighbors = {atom: set() for atom in atom_order}
    for left, right, _order in bonds:
        neighbors[left].add(right)
        neighbors[right].add(left)
    unseen = set(atom_order)
    components: list[frozenset[str]] = []
    while unseen:
        pending = [min(unseen)]
        found: set[str] = set()
        while pending:
            atom = pending.pop()
            if atom in found:
                continue
            found.add(atom)
            pending.extend(sorted(neighbors[atom] - found, reverse=True))
        unseen -= found
        components.append(frozenset(found))
    return tuple(sorted(components, key=lambda item: sorted(item)))


def _validate_species_binding(value: Mapping[str, object]) -> None:
    binding = _keys(
        value,
        {"graph_identity", "atom_order", "atom_mapping", "elements", "explicit_hydrogens",
         "fragment_ids", "component_count", "bonds", "formal_charge", "multiplicity",
         "electronic_state_family"},
        "species_binding",
    )
    _text(binding["graph_identity"], "species_binding.graph_identity")
    atom_order = _string_tuple(binding["atom_order"], "species_binding.atom_order")
    elements = _string_tuple(binding["elements"], "species_binding.elements", unique=False)
    fragments = _string_tuple(binding["fragment_ids"], "species_binding.fragment_ids", unique=False)
    hydrogens = binding["explicit_hydrogens"]
    _require(
        isinstance(hydrogens, Sequence) and not isinstance(hydrogens, (str, bytes, bytearray))
        and all(type(item) is bool for item in hydrogens),
        "species_binding.explicit_hydrogens must be a boolean sequence",
    )
    _require(len(atom_order) == len(elements) == len(fragments) == len(hydrogens), "species_binding atom-scoped fields must have identical lengths")
    mapping = binding["atom_mapping"]
    _require(isinstance(mapping, Mapping) and set(mapping) == set(atom_order), "atom_mapping must cover exact atom_order")
    assert isinstance(mapping, Mapping)
    sources = tuple(_text(mapping[atom], f"atom_mapping[{atom!r}]") for atom in atom_order)
    _require(len(sources) == len(set(sources)), "atom_mapping source atoms must form a bijection")
    bonds = _normalized_bonds(binding["bonds"], atom_order)
    _require(bonds is not None, "species_binding.bonds are invalid")
    assert bonds is not None
    component_count = _positive_integer(binding["component_count"], "species_binding.component_count")
    fragment_components = {
        frozenset(atom for atom, fragment in zip(atom_order, fragments) if fragment == fragment_id)
        for fragment_id in set(fragments)
    }
    _require(len(fragment_components) == component_count, "component_count must equal exact fragment count")
    _require(set(_graph_components(atom_order, bonds)) == fragment_components, "bonds and fragment membership must define identical components")
    _require(type(binding["formal_charge"]) is int, "species_binding.formal_charge must be an integer")
    _positive_integer(binding["multiplicity"], "species_binding.multiplicity")
    _text(binding["electronic_state_family"], "species_binding.electronic_state_family")


def _validate_stereochemistry_binding(value: Mapping[str, object]) -> None:
    binding = _keys(value, {"scope", "assignments", "binding_modes"}, "stereochemistry_binding")
    _require(binding["scope"] in {"locked", "none"}, "stereochemistry_binding.scope is unsupported")
    _require(isinstance(binding["assignments"], Mapping), "stereochemistry assignments must be a mapping")
    _require(isinstance(binding["binding_modes"], Mapping), "stereochemistry binding_modes must be a mapping")
    if binding["scope"] == "none":
        _require(not binding["assignments"] and not binding["binding_modes"], "stereochemistry scope none cannot carry assignments")


def _validate_geometry_policy(value: Mapping[str, object], species: Mapping[str, object]) -> None:
    policy = _keys(value, {"minimum_pair_distance", "reference_bond_maximum_distances", "fragment_association_constraints"}, "geometry_legality_policy")
    _tagged_parameter(policy["minimum_pair_distance"], "geometry_legality_policy.minimum_pair_distance", unit="angstrom", positive=True)
    atom_order = tuple(species["atom_order"])
    bonds = _normalized_bonds(species["bonds"], atom_order)
    assert bonds is not None
    expected_pairs = {(left, right) for left, right, _order in bonds}
    limits = policy["reference_bond_maximum_distances"]
    _require(isinstance(limits, Sequence) and not isinstance(limits, (str, bytes, bytearray)), "reference_bond_maximum_distances must be a sequence")
    observed_pairs: set[tuple[str, str]] = set()
    for index, item in enumerate(limits):
        record = _keys(item, {"atom_ids", "maximum", "unit"}, f"reference_bond_maximum_distances[{index}]")
        pair = _string_tuple(record["atom_ids"], f"reference_bond_maximum_distances[{index}].atom_ids")
        _require(len(pair) == 2 and pair[0] != pair[1], "reference bond atom_ids must name two distinct atoms")
        normalized = tuple(sorted(pair))
        _require(normalized in expected_pairs, "reference bond limit must bind an exact reference bond")
        _require(normalized not in observed_pairs, "reference bond limits must not duplicate a bond")
        observed_pairs.add(normalized)
        _require(record["unit"] == "angstrom", "reference bond maximum unit must be angstrom")
        _finite(record["maximum"], "reference bond maximum", positive=True)
    _require(observed_pairs == expected_pairs, "every reference bond must have one explicit maximum distance")
    fragment_by_atom = dict(zip(atom_order, species["fragment_ids"]))
    constraints = policy["fragment_association_constraints"]
    _require(isinstance(constraints, Sequence) and not isinstance(constraints, (str, bytes, bytearray)), "fragment_association_constraints must be a sequence")
    seen: set[tuple[str, str, str, str]] = set()
    for index, item in enumerate(constraints):
        record = _keys(item, {"fragment_ids", "atom_ids", "minimum", "maximum", "unit"}, f"fragment_association_constraints[{index}]")
        fragments = _string_tuple(record["fragment_ids"], f"fragment_association_constraints[{index}].fragment_ids")
        atoms = _string_tuple(record["atom_ids"], f"fragment_association_constraints[{index}].atom_ids")
        _require(len(fragments) == len(atoms) == 2, "association constraint must bind one atom from each of two fragments")
        _require(fragments[0] != fragments[1] and atoms[0] != atoms[1], "association constraint endpoints must differ")
        _require(all(atom in fragment_by_atom for atom in atoms), "association constraint atom is outside the species")
        _require(tuple(fragment_by_atom[atom] for atom in atoms) == fragments, "association atom ownership must match exact fragments")
        identity = (fragments[0], fragments[1], atoms[0], atoms[1])
        _require(identity not in seen, "association constraints must not duplicate an endpoint identity")
        seen.add(identity)
        _require(record["unit"] == "angstrom", "association constraint unit must be angstrom")
        minimum = _finite(record["minimum"], "association minimum", nonnegative=True)
        maximum = _finite(record["maximum"], "association maximum", positive=True)
        _require(minimum < maximum, "association constraint minimum must be below maximum")


def _validate_crest_profile(value: Mapping[str, object]) -> None:
    route = _keys(
        value,
        {"provider", "mode", "engine", "adapter", "sampling_method", "seed_policy",
         "replica_policy", "budget", "termination", "sampling_energy", "imtd_gc_controls"},
        "crest_imtd_gc_profile",
    )
    _require(route["provider"] == "crest", "initial provider must be exactly crest")
    _require(route["mode"] == "imtd-gc", "initial sampling mode must be exactly imtd-gc")
    engine = _keys(route["engine"], {"semantic_identity", "version"}, "crest_imtd_gc_profile.engine")
    _semantic_identity(engine["semantic_identity"], "crest_imtd_gc_profile.engine.semantic_identity")
    _semantic_version(engine["version"], "crest_imtd_gc_profile.engine.version")
    adapter = _keys(route["adapter"], {"semantic_identity", "version"}, "crest_imtd_gc_profile.adapter")
    _semantic_identity(adapter["semantic_identity"], "crest_imtd_gc_profile.adapter.semantic_identity")
    _semantic_version(adapter["version"], "crest_imtd_gc_profile.adapter.version")
    method = _keys(route["sampling_method"], {"semantic_identity", "profile_identity"}, "crest_imtd_gc_profile.sampling_method")
    _semantic_identity(method["semantic_identity"], "crest_imtd_gc_profile.sampling_method.semantic_identity")
    _semantic_identity(method["profile_identity"], "crest_imtd_gc_profile.sampling_method.profile_identity")
    seed_policy = _keys(route["seed_policy"], {"mode", "values"}, "crest_imtd_gc_profile.seed_policy")
    _require(seed_policy["mode"] == "explicit", "seed policy must be explicit")
    seeds = seed_policy["values"]
    _require(
        isinstance(seeds, Sequence) and not isinstance(seeds, (str, bytes, bytearray)) and bool(seeds)
        and all(type(seed) is int for seed in seeds) and len(seeds) == len(set(seeds)),
        "seed values must be a non-empty unique integer sequence",
    )
    replica = _keys(route["replica_policy"], {"replica_count", "member_index_origin"}, "crest_imtd_gc_profile.replica_policy")
    replica_count = _positive_integer(replica["replica_count"], "replica_count")
    _require(replica["member_index_origin"] == 0, "member_index_origin must be zero")
    budget = _keys(route["budget"], {"minimum_observations", "minimum_valid", "maximum_observations"}, "crest_imtd_gc_profile.budget")
    minimum_observations = _nonnegative_integer(budget["minimum_observations"], "minimum_observations")
    minimum_valid = _nonnegative_integer(budget["minimum_valid"], "minimum_valid")
    maximum = _positive_integer(budget["maximum_observations"], "maximum_observations")
    _require(minimum_valid <= minimum_observations <= maximum <= replica_count, "CREST budget ordering is invalid")
    termination = _keys(route["termination"], {"criterion", "maximum_steps"}, "crest_imtd_gc_profile.termination")
    _require(termination["criterion"] == "bounded_steps", "termination criterion must be bounded_steps")
    _positive_integer(termination["maximum_steps"], "termination.maximum_steps")
    energy = _keys(route["sampling_energy"], {"unit", "admission_window"}, "crest_imtd_gc_profile.sampling_energy")
    unit = _text(energy["unit"], "crest_imtd_gc_profile.sampling_energy.unit")
    _tagged_parameter(energy["admission_window"], "sampling_energy.admission_window", unit=unit, nonnegative=True)
    controls = _keys(route["imtd_gc_controls"], {"metadynamics_temperature_kelvin", "metadynamics_time_ps", "rmsd_threshold_angstrom", "rotamer_search"}, "crest_imtd_gc_profile.imtd_gc_controls")
    _finite(controls["metadynamics_temperature_kelvin"], "metadynamics_temperature_kelvin", positive=True)
    _finite(controls["metadynamics_time_ps"], "metadynamics_time_ps", positive=True)
    _finite(controls["rmsd_threshold_angstrom"], "rmsd_threshold_angstrom", positive=True)
    _require(type(controls["rotamer_search"]) is bool, "rotamer_search must be boolean")


def _validate_rmsd_policy(value: Mapping[str, object], atom_count: int) -> None:
    rmsd = _keys(value, {"atom_selection", "alignment", "atom_correspondence", "symmetry_mapping", "duplicate_threshold", "review_band"}, "rmsd_policy")
    _require(rmsd["atom_selection"] in {"all", "heavy"}, "RMSD atom selection is unsupported")
    _require(rmsd["alignment"] == "quaternion_rigid", "RMSD alignment must be quaternion_rigid")
    _require(rmsd["atom_correspondence"] == "source_to_canonical_bijection", "RMSD correspondence must use the reviewed bijection")
    mapping = rmsd["symmetry_mapping"]
    _require(isinstance(mapping, Sequence) and not isinstance(mapping, (str, bytes, bytearray)) and tuple(mapping) == tuple(range(atom_count)), "only the identity symmetry mapping is permitted")
    threshold = _tagged_parameter(rmsd["duplicate_threshold"], "rmsd_policy.duplicate_threshold", unit="angstrom", positive=True)
    band = _keys(rmsd["review_band"], {"minimum", "maximum", "unit"}, "rmsd_policy.review_band")
    _require(band["unit"] == "angstrom", "review band unit must be angstrom")
    minimum = _finite(band["minimum"], "review_band.minimum", positive=True)
    maximum = _finite(band["maximum"], "review_band.maximum", positive=True)
    _require(float(threshold["value"]) <= minimum < maximum, "review band must begin at or above the duplicate threshold")


def _validate_clustering_policy(value: Mapping[str, object]) -> None:
    clustering = _keys(value, {"linkage", "composite_merge_threshold", "mapped_rmsd_weight", "medoid_tie_breaker"}, "clustering_policy")
    _require(clustering["linkage"] == "single", "only deterministic single linkage is supported")
    _tagged_parameter(clustering["composite_merge_threshold"], "clustering_policy.composite_merge_threshold", unit="weighted_distance", positive=True)
    _finite(clustering["mapped_rmsd_weight"], "clustering_policy.mapped_rmsd_weight", nonnegative=True)
    _require(clustering["medoid_tie_breaker"] == "member_id", "medoid tie-breaker must be member_id")


def _validate_descriptor_policy(value: Sequence[Mapping[str, object]]) -> None:
    names: set[str] = set()
    for index, item in enumerate(value):
        policy = _keys(item, {"name", "kind", "unit", "weight", "compatibility_threshold", "applicability"}, f"descriptor_policy[{index}]")
        name = _text(policy["name"], f"descriptor_policy[{index}].name")
        _require(name not in names, "descriptor names must be unique")
        names.add(name)
        kind = policy["kind"]
        _require(kind in {"scalar", "periodic_degrees", "categorical_set"}, "descriptor kind is unsupported")
        unit = _text(policy["unit"], f"descriptor_policy[{index}].unit")
        _finite(policy["weight"], f"descriptor_policy[{index}].weight", nonnegative=True)
        applicability = _keys(policy["applicability"], {"status"}, f"descriptor_policy[{index}].applicability")
        _require(applicability["status"] == "required", "initial active descriptors must be required")
        threshold_unit = "fraction" if kind == "categorical_set" else unit
        _tagged_parameter(policy["compatibility_threshold"], f"descriptor_policy[{index}].compatibility_threshold", unit=threshold_unit, nonnegative=True)


def create_sampling_profile(
    *,
    revision: int,
    supersedes_sampling_profile_id: str | None,
    species_binding: Mapping[str, object],
    stereochemistry_binding: Mapping[str, object],
    bond_change_policy: str,
    geometry_legality_policy: Mapping[str, object],
    crest_imtd_gc_profile: Mapping[str, object],
    rmsd_policy: Mapping[str, object],
    clustering_policy: Mapping[str, object],
    descriptor_policy: Sequence[Mapping[str, object]],
    coverage_policy: Mapping[str, object],
    thermodynamic_eligibility_policy: Mapping[str, object],
    ts_seed_projection_policy: Mapping[str, object],
) -> SamplingProfile:
    """Freeze the one closed CREST iMTD-GC sampling policy."""

    _positive_integer(revision, "revision")
    if revision == 1:
        _require(supersedes_sampling_profile_id is None, "revision 1 cannot supersede a profile")
    else:
        _text(supersedes_sampling_profile_id, "supersedes_sampling_profile_id")
    _validate_species_binding(species_binding)
    _validate_stereochemistry_binding(stereochemistry_binding)
    _require(bond_change_policy == "forbid", "initial bond_change_policy must be forbid")
    _validate_geometry_policy(geometry_legality_policy, species_binding)
    _validate_crest_profile(crest_imtd_gc_profile)
    _validate_rmsd_policy(rmsd_policy, len(species_binding["atom_order"]))
    _validate_clustering_policy(clustering_policy)
    _validate_descriptor_policy(descriptor_policy)
    coverage = _keys(coverage_policy, {"met_status", "unmet_status", "invalid_observation_effect", "global_claim_allowed"}, "coverage_policy")
    _require(coverage["met_status"] == "sufficient", "met coverage status must be sufficient")
    _require(coverage["unmet_status"] == "insufficient", "unmet coverage status must be insufficient")
    _require(coverage["invalid_observation_effect"] == "uncertain", "invalid observations must make coverage uncertain")
    _require(coverage["global_claim_allowed"] is False, "coverage may never claim global completeness")
    thermo = _keys(
        thermodynamic_eligibility_policy,
        {"require_post_dft_minimum", "required_coverage_statuses"},
        "thermodynamic_eligibility_policy",
    )
    _require(thermo["require_post_dft_minimum"] is True, "thermodynamic eligibility must require accepted post-DFT minimum evidence")
    thermo_statuses = set(_string_tuple(thermo["required_coverage_statuses"], "thermodynamic required coverage statuses"))
    _require(thermo_statuses <= _COVERAGE_STATUSES, "thermodynamic coverage status is unsupported")
    ts_policy = _keys(
        ts_seed_projection_policy,
        {"require_post_dft_minimum", "required_coverage_statuses", "allowed_relevance_tags"},
        "ts_seed_projection_policy",
    )
    _require(ts_policy["require_post_dft_minimum"] is True, "TS-seed eligibility must require accepted post-DFT minimum evidence")
    ts_statuses = set(_string_tuple(ts_policy["required_coverage_statuses"], "TS-seed required coverage statuses"))
    _require(ts_statuses <= _COVERAGE_STATUSES, "TS-seed coverage status is unsupported")
    _string_tuple(ts_policy["allowed_relevance_tags"], "ts_seed_projection_policy.allowed_relevance_tags")
    try:
        return SamplingProfile._create(
            revision=revision,
            supersedes_sampling_profile_id=supersedes_sampling_profile_id,
            species_binding=species_binding,
            stereochemistry_binding=stereochemistry_binding,
            bond_change_policy=bond_change_policy,
            geometry_legality_policy=geometry_legality_policy,
            crest_imtd_gc_profile=crest_imtd_gc_profile,
            rmsd_policy=rmsd_policy,
            clustering_policy=clustering_policy,
            descriptor_policy=descriptor_policy,
            coverage_policy=coverage_policy,
            thermodynamic_eligibility_policy=thermodynamic_eligibility_policy,
            ts_seed_projection_policy=ts_seed_projection_policy,
        )
    except ValueError as exc:
        raise ConformerError(str(exc)) from exc


def _audit_correspondence(profile: SamplingProfile, value: object) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return ["atom_correspondence_not_a_bijection"]
    atom_order = tuple(profile.species_binding["atom_order"])
    source_by_canonical = profile.species_binding["atom_mapping"]
    elements_by_canonical = dict(zip(atom_order, profile.species_binding["elements"]))
    if len(value) != len(atom_order):
        return ["atom_correspondence_not_a_bijection"]
    sources: list[str] = []
    canonicals: list[str] = []
    for item in value:
        if not isinstance(item, Mapping) or set(item) != {"source_atom_id", "canonical_map_id", "element"}:
            return ["atom_correspondence_not_a_bijection"]
        source, canonical, element = item["source_atom_id"], item["canonical_map_id"], item["element"]
        if not isinstance(source, str) or not isinstance(canonical, str) or canonical not in source_by_canonical or source_by_canonical[canonical] != source or elements_by_canonical[canonical] != element:
            return ["atom_correspondence_not_a_bijection"]
        sources.append(source)
        canonicals.append(canonical)
    if len(sources) != len(set(sources)) or len(canonicals) != len(set(canonicals)) or set(sources) != set(source_by_canonical.values()) or set(canonicals) != set(atom_order):
        return ["atom_correspondence_not_a_bijection"]
    return []


def _audit_source(profile: SamplingProfile, observation: Mapping[str, object]) -> list[str]:
    source = observation.get("source_binding")
    if not isinstance(source, Mapping):
        return ["source_binding_missing_or_malformed"]
    if set(source) != _SOURCE_KEYS:
        return ["source_binding_inventory_mismatch"]
    route = profile.crest_imtd_gc_profile
    reasons: list[str] = []
    expected = {
        "sampling_profile_id": profile.sampling_profile_id,
        "provider": route["provider"],
        "mode": route["mode"],
        "sampling_configuration_identity": _payload_sha256(route),
    }
    for key, value in expected.items():
        if source[key] != value:
            reasons.append(f"source_{key}_mismatch")
    for key in ("source_run_id", "source_set_id", "source_geometry_identity", "source_artifact_identity"):
        if not isinstance(source[key], str) or not source[key] or source[key] != source[key].strip():
            reasons.append(f"{key}_malformed")
    if type(source["source_member_index"]) is not int or source["source_member_index"] < 0:
        reasons.append("source_member_index_out_of_range")
    if type(source["seed"]) is not int or source["seed"] not in route["seed_policy"]["values"]:
        reasons.append("source_seed_mismatch")
    replica_count = int(route["replica_policy"]["replica_count"])
    if type(source["replica_index"]) is not int or not 0 <= source["replica_index"] < replica_count:
        reasons.append("source_replica_index_out_of_range")
    return reasons


def _audit_descriptors(profile: SamplingProfile, value: object) -> list[str]:
    if not isinstance(value, Mapping):
        return ["descriptor_inventory_mismatch"]
    required = {policy["name"]: policy for policy in profile.descriptor_policy}
    if set(value) != set(required):
        reasons = ["descriptor_inventory_mismatch"]
        reasons.extend(f"missing_required_descriptor:{name}" for name in sorted(set(required) - set(value)))
        return reasons
    reasons: list[str] = []
    for name, policy in required.items():
        record = value[name]
        if not isinstance(record, Mapping) or set(record) != {"value", "unit"}:
            reasons.append(f"descriptor_record_malformed:{name}")
            continue
        if record["unit"] != policy["unit"]:
            reasons.append(f"descriptor_unit_mismatch:{name}")
            continue
        observed = record["value"]
        if policy["kind"] in {"scalar", "periodic_degrees"}:
            if type(observed) not in {int, float} or not isfinite(observed):
                reasons.append(f"descriptor_value_malformed:{name}")
        elif not isinstance(observed, Sequence) or isinstance(observed, (str, bytes, bytearray)) or not all(isinstance(item, str) and item for item in observed) or len(observed) != len(set(observed)):
            reasons.append(f"descriptor_value_malformed:{name}")
    return reasons


def _coordinates(value: object, atom_count: int) -> bool:
    return (
        isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)) and len(value) == atom_count
        and all(isinstance(point, Sequence) and not isinstance(point, (str, bytes, bytearray)) and len(point) == 3 and all(type(item) in {int, float} and isfinite(item) for item in point) for point in value)
    )


def _distance(coordinates: Sequence[Sequence[float]], left: int, right: int) -> float:
    return sum((float(a) - float(b)) ** 2 for a, b in zip(coordinates[left], coordinates[right])) ** 0.5


def _audit_geometry(profile: SamplingProfile, coordinates: Sequence[Sequence[float]]) -> list[str]:
    policy = profile.geometry_legality_policy
    reasons: list[str] = []
    if minimum_pair_distance(coordinates) < float(policy["minimum_pair_distance"]["value"]):
        reasons.append("atom_collision")
    atom_indices = {atom: index for index, atom in enumerate(profile.species_binding["atom_order"])}
    for limit in policy["reference_bond_maximum_distances"]:
        left, right = limit["atom_ids"]
        if _distance(coordinates, atom_indices[left], atom_indices[right]) > float(limit["maximum"]):
            reasons.append(f"required_bond_distance_exceeded:{left}:{right}")
    for constraint in policy["fragment_association_constraints"]:
        left, right = constraint["atom_ids"]
        observed = _distance(coordinates, atom_indices[left], atom_indices[right])
        if not float(constraint["minimum"]) <= observed <= float(constraint["maximum"]):
            reasons.append(f"fragment_association_constraint_violated:{left}:{right}")
    return reasons


def _audit_observation(profile: SamplingProfile, observation: Mapping[str, object]) -> _AuditedMember:
    member_id = _text(observation.get("member_id"), "sampling observation.member_id")
    reasons: list[str] = []
    if set(observation) != _OBSERVATION_KEYS:
        reasons.append("observation_inventory_mismatch")
    species = profile.species_binding
    for field, reason in (
        ("atom_order", "atom_map_or_order_drift"), ("elements", "element_inventory_changed"),
        ("explicit_hydrogens", "explicit_hydrogen_identity_changed"), ("fragment_ids", "fragment_membership_changed"),
        ("formal_charge", "formal_charge_changed"), ("multiplicity", "multiplicity_changed"),
        ("electronic_state_family", "electronic_state_family_changed"),
    ):
        if _plain_value(observation.get(field)) != _plain_value(species[field]):
            reasons.append(reason)
    observed_bonds = _normalized_bonds(observation.get("bonds"), species["atom_order"])
    reference_bonds = _normalized_bonds(species["bonds"], species["atom_order"])
    if observed_bonds != reference_bonds:
        reasons.append("covalent_graph_changed")
        if observed_bonds is not None and len(_graph_components(tuple(species["atom_order"]), observed_bonds)) != species["component_count"]:
            reasons.append("component_count_changed")
    if _plain_value(observation.get("stereochemistry_binding")) != _plain_value(profile.stereochemistry_binding):
        reasons.append("stereochemistry_drift")
    reasons.extend(_audit_correspondence(profile, observation.get("atom_correspondence")))
    coordinates = observation.get("coordinates_angstrom")
    if not _coordinates(coordinates, len(species["atom_order"])):
        reasons.append("nonfinite_or_malformed_geometry")
    else:
        assert isinstance(coordinates, Sequence)
        reasons.extend(_audit_geometry(profile, coordinates))
    reasons.extend(_audit_source(profile, observation))
    reasons.extend(_audit_descriptors(profile, observation.get("descriptors")))
    relevance_tags = observation.get("relevance_tags")
    if (
        not isinstance(relevance_tags, Sequence)
        or isinstance(relevance_tags, (str, bytes, bytearray))
        or not all(isinstance(tag, str) and tag and tag == tag.strip() for tag in relevance_tags)
        or len(relevance_tags) != len(set(relevance_tags))
    ):
        reasons.append("relevance_tags_malformed")
    energy = observation.get("sampling_energy")
    energy_policy = profile.crest_imtd_gc_profile["sampling_energy"]
    if not isinstance(energy, Mapping) or set(energy) != {"value", "unit", "formal_thermodynamics_allowed"}:
        reasons.append("sampling_energy_missing_or_malformed")
    else:
        if type(energy["value"]) not in {int, float} or not isfinite(energy["value"]):
            reasons.append("sampling_energy_nonfinite")
        if energy["unit"] != energy_policy["unit"]:
            reasons.append("sampling_energy_unit_mismatch")
        if energy["formal_thermodynamics_allowed"] is not False:
            reasons.append("sampling_energy_formal_use_forbidden")
    unique_reasons = tuple(sorted(set(reasons)))
    state_changed = any(reason in _STATE_CHANGE_REASONS or reason.startswith("required_bond_distance_exceeded:") or reason.startswith("fragment_association_constraint_violated:") for reason in unique_reasons)
    status = "state_changed" if state_changed else ("valid" if not unique_reasons else "invalid")
    return _AuditedMember(member_id, observation, status, unique_reasons)


def _record_value(value: object) -> object:
    if type(value) is float and not isfinite(value):
        classification = "nan" if value != value else ("positive_infinity" if value > 0.0 else "negative_infinity")
        return {"invalid_numeric_observation": classification}
    if isinstance(value, Mapping):
        return {key: _record_value(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(_record_value(item) for item in value)
    return value


def _atom_indices(profile: SamplingProfile) -> tuple[int, ...]:
    if profile.rmsd_policy["atom_selection"] == "all":
        return tuple(range(len(profile.species_binding["atom_order"])))
    return tuple(index for index, element in enumerate(profile.species_binding["elements"]) if element != "H")


def _comparison_digest(profile: SamplingProfile, member_ids: tuple[str, str], components: Mapping[str, object]) -> str:
    return _payload_sha256({"domain": "v31-conformer-comparison-v1", "sampling_profile_id": profile.sampling_profile_id, "member_ids": member_ids, "components": components})


def _association_semantics_complete(profile: SamplingProfile) -> bool:
    fragments = set(profile.species_binding["fragment_ids"])
    if len(fragments) == 1:
        return True
    edges: dict[str, set[str]] = {fragment: set() for fragment in fragments}
    for constraint in profile.geometry_legality_policy["fragment_association_constraints"]:
        left, right = constraint["fragment_ids"]
        edges[left].add(right)
        edges[right].add(left)
    reached: set[str] = set()
    pending = [min(fragments)]
    while pending:
        fragment = pending.pop()
        if fragment in reached:
            continue
        reached.add(fragment)
        pending.extend(sorted(edges[fragment] - reached, reverse=True))
    return reached == fragments


def build_conformer_ensemble(
    *, project_id: str, calculation_plan_id: str, calculation_plan_revision: int,
    profile: SamplingProfile, observations: Sequence[Mapping[str, object]],
) -> ConformerEnsemble:
    """Audit observations and produce blockers, never review evidence."""

    _text(project_id, "project_id")
    _text(calculation_plan_id, "calculation_plan_id")
    _positive_integer(calculation_plan_revision, "calculation_plan_revision")
    _require(bool(observations), "sampling observations must not be empty")
    audited = [_audit_observation(profile, observation) for observation in observations]
    ids = [item.member_id for item in audited]
    _require(len(ids) == len(set(ids)), "sampling observation member IDs must be unique")
    locators: dict[tuple[object, ...], list[str]] = {}
    for item in audited:
        source = item.observation.get("source_binding")
        if isinstance(source, Mapping) and set(source) == _SOURCE_KEYS:
            locator = (source["sampling_profile_id"], source["source_run_id"], source["source_set_id"], source["source_member_index"], source["source_artifact_identity"])
            locators.setdefault(locator, []).append(item.member_id)
    duplicate_locators = {member for members in locators.values() if len(members) > 1 for member in members}
    audited = [replace(item, status="invalid", reasons=tuple(sorted((*item.reasons, "duplicate_source_locator")))) if item.member_id in duplicate_locators else item for item in audited]
    admission_candidates = [
        item
        for item in audited
        if item.status == "valid" and isinstance(item.observation["sampling_energy"], Mapping)
    ]
    if admission_candidates:
        minimum_energy = min(float(item.observation["sampling_energy"]["value"]) for item in admission_candidates)
        admission_window = float(profile.crest_imtd_gc_profile["sampling_energy"]["admission_window"]["value"])
        audited = [
            replace(
                item,
                status="not_admitted",
                reasons=("sampling_energy_outside_admission_window",),
            )
            if item.status == "valid"
            and float(item.observation["sampling_energy"]["value"]) - minimum_energy > admission_window
            else item
            for item in audited
        ]
    audited.sort(key=lambda item: item.member_id)
    valid = [item for item in audited if item.status == "valid"]
    valid_by_id = {item.member_id: item for item in valid}

    atom_indices = _atom_indices(profile)
    _require(bool(atom_indices), "RMSD atom selection must not be empty")
    duplicate_threshold = float(profile.rmsd_policy["duplicate_threshold"]["value"])
    review_minimum = float(profile.rmsd_policy["review_band"]["minimum"])
    review_maximum = float(profile.rmsd_policy["review_band"]["maximum"])
    composite_threshold = float(profile.clustering_policy["composite_merge_threshold"]["value"])
    comparisons: list[dict[str, object]] = []
    blockers: list[dict[str, object]] = []
    for left_index, left in enumerate(valid):
        for right in valid[left_index + 1:]:
            member_ids = (left.member_id, right.member_id)
            distance = pair_distance(left.observation, right.observation, atom_indices=atom_indices, mapped_rmsd_weight=float(profile.clustering_policy["mapped_rmsd_weight"]), descriptor_policy=profile.descriptor_policy)
            rmsd = float(distance["components"]["mapped_rmsd"])
            reasons: list[str] = []
            if review_minimum <= rmsd <= review_maximum:
                reasons.append("boundary_band")
            if rmsd <= duplicate_threshold:
                for policy in profile.descriptor_policy:
                    component = float(distance["components"][f"descriptor:{policy['name']}"])
                    tolerance = float(policy["compatibility_threshold"]["value"])
                    if component > tolerance:
                        reasons.append("descriptor_conflict")
                        break
            digest = _comparison_digest(profile, member_ids, distance["components"])
            if reasons:
                decision = "pending_independent_review"
                for reason in sorted(set(reasons)):
                    blockers.append({"member_ids": member_ids, "comparison_digest": digest, "reason": reason, "status": "pending_independent_review"})
            else:
                decision = "duplicate" if rmsd <= duplicate_threshold and float(distance["composite_distance"]) <= composite_threshold else "independent"
            comparisons.append({"member_ids": member_ids, **distance, "comparison_digest": digest, "decision": decision})

    clusters_raw = union_clusters([item.member_id for item in valid], comparisons)
    distances = {tuple(item["member_ids"]): float(item["composite_distance"]) for item in comparisons}
    clusters: list[dict[str, object]] = []
    for index, member_ids in enumerate(clusters_raw, 1):
        def score(member_id: str) -> tuple[float, str]:
            return (sum(distances.get(tuple(sorted((member_id, other))), 0.0) for other in member_ids if other != member_id), member_id)
        medoid = min(member_ids, key=score)
        clusters.append({"cluster_id": f"cluster-{index:04d}", "member_ids": tuple(member_ids), "medoid_member_id": medoid, "medoid_total_distance": score(medoid)[0], "tie_breaker": "member_id"})
    cluster_by_member = {
        member_id: cluster
        for cluster in clusters
        for member_id in cluster["member_ids"]
    }
    members = [
        {
            "member_id": item.member_id,
            "cluster_id": cluster_by_member[item.member_id]["cluster_id"],
            "cluster_medoid_member_id": cluster_by_member[item.member_id]["medoid_member_id"],
            "coordinates_angstrom": item.observation["coordinates_angstrom"],
            "source_binding": item.observation["source_binding"],
            "sampling_energy": item.observation["sampling_energy"],
            "relevance_tags": item.observation["relevance_tags"],
            "post_dft_minimum_evidence_available": False,
        }
        for item in valid
    ]
    audit_evidence = [{"member_id": item.member_id, "status": item.status, "reasons": item.reasons, "retained_as_negative_evidence": item.status != "valid"} for item in audited]
    negative = [item for item in audit_evidence if item["retained_as_negative_evidence"]]
    budget = profile.crest_imtd_gc_profile["budget"]
    obligations = {
        "minimum_observations_met": len(audited) >= budget["minimum_observations"],
        "minimum_valid_met": len(valid) >= budget["minimum_valid"],
        "maximum_observations_respected": len(audited) <= budget["maximum_observations"],
        "fragment_association_semantics_complete": _association_semantics_complete(profile),
        "independent_review_resolved": not blockers,
    }
    budget_complete = all(
        obligations[key]
        for key in ("minimum_observations_met", "minimum_valid_met", "maximum_observations_respected")
    )
    if not budget_complete or not obligations["fragment_association_semantics_complete"]:
        coverage_status = "insufficient"
    elif negative or blockers:
        coverage_status = "uncertain"
    else:
        coverage_status = "sufficient"
    coverage = {"status": coverage_status, "scope": "closed-crest-imtd-gc-profile", "global_minimum_claim": False, "exhaustive_coverage_claim": False, "obligations": obligations, "observed_count": len(audited), "valid_count": len(valid)}
    canonical_member_ids = tuple(member["member_id"] for member in members)
    projection_unblocked = not blockers and obligations["fragment_association_semantics_complete"]
    thermo_policy = profile.thermodynamic_eligibility_policy
    thermodynamic_eligible_members = tuple(
        member_id
        for member_id in canonical_member_ids
        if projection_unblocked
        and coverage_status in thermo_policy["required_coverage_statuses"]
        and next(member for member in members if member["member_id"] == member_id)["post_dft_minimum_evidence_available"]
    )
    ts_policy = profile.ts_seed_projection_policy
    allowed_tags = set(ts_policy["allowed_relevance_tags"])
    ts_seed_members = tuple(
        member_id
        for member_id in canonical_member_ids
        if projection_unblocked
        and coverage_status in ts_policy["required_coverage_statuses"]
        and next(member for member in members if member["member_id"] == member_id)["post_dft_minimum_evidence_available"]
        and allowed_tags.intersection(next(member for member in members if member["member_id"] == member_id)["relevance_tags"])
    )
    try:
        return ConformerEnsemble._create(
            project_id=project_id, calculation_plan_id=calculation_plan_id,
            calculation_plan_revision=calculation_plan_revision, profile=profile,
            sampling_observations=[_record_value(item.observation) for item in audited],
            audit_evidence=audit_evidence, negative_evidence=negative,
            dedup_decisions=comparisons, independent_review_blockers=blockers,
            clusters=clusters, members=members, coverage=coverage,
            thermodynamic_eligible_members=thermodynamic_eligible_members,
            ts_seed_members=ts_seed_members,
        )
    except ValueError as exc:
        raise ConformerError(str(exc)) from exc
