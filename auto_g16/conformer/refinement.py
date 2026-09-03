"""Private, zero-effect post-DFT refinement of a V31 conformer ensemble."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from math import isfinite

from ._geometry import mapped_rmsd, union_clusters
from .models import ConformerEnsemble, SamplingProfile, _identified_payload, _payload_sha256
from .refinement_authority import (
    RefinementAuthorityError,
    _authority_id,
    _coordinates_from_geometry,
    _source,
    _validate_current_optimization_geometry_authority,
    _validate_current_two_stage_minimum_authority,
    validate_negative_frequency_authority,
    validate_negative_optimization_authority,
)
from .service import _audit_observation


_OPT_KEYS = {
    "authority_schema", "optimization_geometry_authority_id", "source", "method_id",
    "calculation_plan", "prepared_input", "result", "selected_geometry",
    "recovered_atom_map", "v30_outcome",
}
_MINIMUM_KEYS = {
    "authority_schema", "two_stage_minimum_authority_id", "source", "method_id",
    "optimization", "frequency", "classification",
}
_NEGATIVE_COMMON_KEYS = {
    "authority_schema", "stage", "source", "method_id", "calculation_plan",
    "prepared_input", "review", "result", "output_capture", "v30_outcome",
    "disposition", "failure_class", "failure_evidence",
}
_NEGATIVE_OPT_KEYS = _NEGATIVE_COMMON_KEYS | {"negative_optimization_authority_id"}
_NEGATIVE_FREQ_KEYS = _NEGATIVE_COMMON_KEYS | {
    "negative_frequency_authority_id", "optimization",
}
_NEGATIVE_OPT_FAILURES = {
    "capture_failure", "parse_failure", "program_failure",
    "optimization_not_completed", "stationary_point_not_closed",
    "final_geometry_unavailable", "output_atom_inventory_mismatch",
    "unsupported_result_semantics",
}
_NEGATIVE_FREQ_FAILURES = {
    "capture_failure", "parse_failure", "program_failure",
    "frequency_mode_count_invalid", "not_minimum",
    "frequency_result_semantics_invalid",
}
_OPT_INPUT_KEYS = {
    "calculation_plan", "prepared_input_binding", "prepared_input_bytes",
    "core_store", "validation_store", "input_binding", "output_envelope",
    "parse_outcome", "minimum_validation_outcome_id",
}
_FREQ_INPUT_KEYS = {
    "optimization_plan", "optimization_prepared_input_binding",
    "optimization_prepared_input_bytes", "optimization_core_store",
    "optimization_validation_store", "optimization_input_binding",
    "optimization_output_envelope", "optimization_parse_outcome",
    "optimization_minimum_validation_outcome_id", "frequency_plan",
    "frequency_prepared_input_binding", "frequency_prepared_input_bytes",
    "frequency_core_store", "frequency_validation_store",
    "frequency_input_binding", "frequency_output_envelope",
    "frequency_parse_outcome", "frequency_minimum_validation_outcome_id",
}


class RefinementError(ValueError):
    """The supplied refinement evidence cannot form a closed revision."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RefinementError(message)


def _closed_profile(profile: SamplingProfile) -> None:
    _require(type(profile) is SamplingProfile, "profile must be a SamplingProfile")
    identity, payload_hash = _identified_payload("sampling-profile", profile._identity_payload())
    _require(
        identity == profile.sampling_profile_id and payload_hash == profile.payload_sha256,
        "SamplingProfile identity is stale",
    )


def _closed_ensemble(ensemble: ConformerEnsemble) -> None:
    _require(type(ensemble) is ConformerEnsemble, "prior ensemble must be a ConformerEnsemble")
    identity, payload_hash = _identified_payload("conformer-ensemble", ensemble._identity_payload())
    _require(
        identity == ensemble.conformer_ensemble_id and payload_hash == ensemble.payload_sha256,
        "prior ConformerEnsemble identity is stale",
    )


def _member_id(authority: Mapping[str, object], name: str) -> str:
    source = authority.get("source")
    _require(isinstance(source, Mapping), f"{name}.source must be a mapping")
    member_id = source.get("member_id")
    _require(
        isinstance(member_id, str) and bool(member_id) and member_id == member_id.strip(),
        f"{name} has no canonical member_id",
    )
    return member_id


def _resolve_current_authorities(
    ensemble: ConformerEnsemble,
    inputs: Sequence[Mapping[str, object]],
    *,
    name: str,
    expected_keys: set[str],
    validator,
) -> dict[str, Mapping[str, object]]:
    _require(
        isinstance(inputs, Sequence)
        and not isinstance(inputs, (str, bytes, bytearray)),
        f"{name} must be a finite sequence",
    )
    resolved: dict[str, Mapping[str, object]] = {}
    for item in inputs:
        _require(
            isinstance(item, Mapping) and set(item) == expected_keys | {"member_id"},
            f"{name} input fields are not exact",
        )
        member_id = item["member_id"]
        _require(
            isinstance(member_id, str)
            and bool(member_id)
            and member_id == member_id.strip(),
            f"{name} has no canonical member_id",
        )
        _require(member_id not in resolved, f"{name} contains duplicate member disposition")
        kwargs = {key: item[key] for key in expected_keys}
        try:
            authority = validator(ensemble, member_id, **kwargs)
        except RefinementAuthorityError as exc:
            raise RefinementError(str(exc)) from exc
        _require(
            _member_id(authority, name) == member_id,
            f"{name} validator returned another member",
        )
        resolved[member_id] = authority
    return resolved


def _closed_optimization_authority(
    authority: Mapping[str, object],
    ensemble: ConformerEnsemble,
    member: Mapping[str, object],
) -> tuple[tuple[float, float, float], ...]:
    _require(set(authority) == _OPT_KEYS, "optimization authority fields are not exact")
    payload = {key: authority[key] for key in authority if key != "optimization_geometry_authority_id"}
    _require(
        authority["optimization_geometry_authority_id"]
        == _authority_id("v31-opt-geometry-authority", payload),
        "optimization authority identity is stale",
    )
    _require(
        authority["authority_schema"] == "v31-conformer-optimization-geometry-authority/1",
        "optimization authority schema is unsupported",
    )
    _require(authority["source"] == _source(ensemble, member), "optimization authority source is spliced")
    _require(
        isinstance(authority["method_id"], str) and bool(authority["method_id"]),
        "optimization authority method identity is missing",
    )
    geometry = authority["selected_geometry"]
    _require(isinstance(geometry, Mapping), "optimization authority selected geometry is missing")
    try:
        return _coordinates_from_geometry(geometry, ensemble.species_binding["elements"])
    except RefinementAuthorityError as exc:
        raise RefinementError(str(exc)) from exc


def _closed_negative_authority(
    authority: Mapping[str, object],
    ensemble: ConformerEnsemble,
    member: Mapping[str, object],
    *,
    stage: str,
) -> None:
    if stage == "opt":
        expected_keys = _NEGATIVE_OPT_KEYS
        schema = "v31-conformer-negative-optimization-authority/1"
        identity_key = "negative_optimization_authority_id"
        identity_domain = "v31-negative-opt-authority"
        allowed_failures = _NEGATIVE_OPT_FAILURES
    else:
        expected_keys = _NEGATIVE_FREQ_KEYS
        schema = "v31-conformer-negative-frequency-authority/1"
        identity_key = "negative_frequency_authority_id"
        identity_domain = "v31-negative-freq-authority"
        allowed_failures = _NEGATIVE_FREQ_FAILURES
    _require(set(authority) == expected_keys, f"negative {stage} authority fields are not exact")
    payload = {key: authority[key] for key in authority if key != identity_key}
    _require(
        authority[identity_key] == _authority_id(identity_domain, payload),
        f"negative {stage} authority identity is stale",
    )
    _require(
        authority["authority_schema"] == schema
        and authority["stage"] == stage
        and authority["disposition"] == "negative",
        f"negative {stage} authority contract is unsupported",
    )
    _require(authority["source"] == _source(ensemble, member), f"negative {stage} source is spliced")
    _require(
        isinstance(authority["method_id"], str) and bool(authority["method_id"]),
        f"negative {stage} method identity is missing",
    )
    _require(authority["failure_class"] in allowed_failures, f"negative {stage} failure class is unsupported")
    outcome = authority["v30_outcome"]
    review = authority["review"]
    result = authority["result"]
    _require(
        isinstance(outcome, Mapping)
        and set(outcome) == {"minimum_validation_outcome_id", "classification", "reason_code"}
        and outcome["reason_code"] != "incomplete-provenance",
        f"negative {stage} authority does not close trusted provenance",
    )
    _require(
        isinstance(review, Mapping)
        and set(review) == {"review_bundle_id", "review_payload_sha256"},
        f"negative {stage} Review authority is malformed",
    )
    _require(
        isinstance(result, Mapping)
        and set(result) == {
            "result_id", "result_payload_sha256", "attempt_id",
            "envelope_observation_id", "parser", "parse_status", "diagnostics",
            "source_artifact", "job_section",
        },
        f"negative {stage} Result authority is malformed",
    )


def _closed_minimum_authority(
    authority: Mapping[str, object],
    ensemble: ConformerEnsemble,
    member: Mapping[str, object],
    optimization: Mapping[str, object],
) -> None:
    _require(set(authority) == _MINIMUM_KEYS, "minimum authority fields are not exact")
    payload = {key: authority[key] for key in authority if key != "two_stage_minimum_authority_id"}
    _require(
        authority["two_stage_minimum_authority_id"]
        == _authority_id("v31-two-stage-minimum-authority", payload),
        "minimum authority identity is stale",
    )
    _require(
        authority["authority_schema"] == "v31-conformer-two-stage-minimum-authority/1"
        and authority["classification"] == "VALIDATED_TWO_STAGE_MINIMUM",
        "minimum authority is not a validated V31 two-stage minimum",
    )
    _require(authority["source"] == _source(ensemble, member), "minimum authority source is spliced")
    _require(authority["optimization"] == optimization, "minimum authority names another optimization authority")
    _require(authority["method_id"] == optimization["method_id"], "minimum authority method is incompatible")


def _sampling_observation_by_member(prior: ConformerEnsemble) -> dict[str, Mapping[str, object]]:
    observations: dict[str, Mapping[str, object]] = {}
    duplicates: set[str] = set()
    for observation in prior.sampling_observations:
        member_id = observation.get("member_id")
        if isinstance(member_id, str):
            if member_id in observations:
                duplicates.add(member_id)
            observations[member_id] = observation
    for member_id in duplicates:
        observations.pop(member_id)
    return observations


def _negative_projection(
    member_id: str, authority: Mapping[str, object], *, stage: str,
) -> Mapping[str, object]:
    identity_key = (
        "negative_optimization_authority_id"
        if stage == "opt"
        else "negative_frequency_authority_id"
    )
    result = authority["result"]
    review = authority["review"]
    assert isinstance(result, Mapping) and isinstance(review, Mapping)
    return {
        "member_id": member_id,
        "stage": stage,
        "status": "negative_refinement_authority",
        "retained_as_negative_evidence": True,
        "negative_refinement_authority_id": authority[identity_key],
        "failure_class": authority["failure_class"],
        "result_id": result["result_id"],
        "review_bundle_id": review["review_bundle_id"],
    }


def build_refined_conformer_ensemble(
    prior: ConformerEnsemble,
    profile: SamplingProfile,
    *,
    positive_optimization_inputs: Sequence[Mapping[str, object]],
    negative_optimization_inputs: Sequence[Mapping[str, object]],
    positive_frequency_inputs: Sequence[Mapping[str, object]],
    negative_frequency_inputs: Sequence[Mapping[str, object]],
) -> ConformerEnsemble:
    """Compose terminal private authorities into one immutable revision."""

    _closed_ensemble(prior)
    _closed_profile(profile)
    _require(
        prior.sampling_profile_id == profile.sampling_profile_id
        and prior.sampling_profile_payload_sha256 == profile.payload_sha256,
        "SamplingProfile does not match the prior ensemble",
    )
    _require(prior.species_binding == profile.species_binding, "species binding differs from SamplingProfile")
    _require(
        prior.stereochemistry_binding == profile.stereochemistry_binding,
        "stereochemistry binding differs from SamplingProfile",
    )
    members_by_id = {member["member_id"]: member for member in prior.members}
    canonical_member_ids = tuple(member["member_id"] for member in prior.members)
    _require(bool(canonical_member_ids), "the prior ensemble has no members to refine")
    _require(len(members_by_id) == len(canonical_member_ids), "prior member identities are not unique")
    observations_by_id = _sampling_observation_by_member(prior)
    _require(
        set(observations_by_id) >= set(canonical_member_ids),
        "each prior member must retain one exact sampling observation",
    )

    optimizations = _resolve_current_authorities(
        prior,
        positive_optimization_inputs,
        name="positive_optimization_inputs",
        expected_keys=_OPT_INPUT_KEYS,
        validator=_validate_current_optimization_geometry_authority,
    )
    negative_optimizations = _resolve_current_authorities(
        prior,
        negative_optimization_inputs,
        name="negative_optimization_inputs",
        expected_keys=_OPT_INPUT_KEYS,
        validator=validate_negative_optimization_authority,
    )
    _require(
        not (set(optimizations) & set(negative_optimizations)),
        "a member cannot have both positive and negative Opt authority",
    )
    _require(
        set(optimizations) | set(negative_optimizations) == set(canonical_member_ids),
        "Opt disposition set must equal the complete prior member set",
    )

    optimized_coordinates: dict[str, tuple[tuple[float, float, float], ...]] = {}
    for member_id, authority in optimizations.items():
        optimized_coordinates[member_id] = _closed_optimization_authority(
            authority, prior, members_by_id[member_id],
        )
    for member_id, authority in negative_optimizations.items():
        _closed_negative_authority(authority, prior, members_by_id[member_id], stage="opt")
    opt_method_ids = {
        authority["method_id"]
        for authority in (*optimizations.values(), *negative_optimizations.values())
    }
    _require(
        len(opt_method_ids) == 1,
        "Opt dispositions must use one exact method identity",
    )

    post_opt_valid: list[str] = []
    identity_rejections: dict[str, tuple[str, ...]] = {}
    for member_id in canonical_member_ids:
        if member_id not in optimizations:
            continue
        observation = dict(observations_by_id[member_id])
        observation["coordinates_angstrom"] = optimized_coordinates[member_id]
        audited = _audit_observation(profile, observation)
        if audited.status == "valid":
            post_opt_valid.append(member_id)
        else:
            identity_rejections[member_id] = audited.reasons

    atom_count = len(prior.species_binding["atom_order"])
    symmetry_mapping = tuple(profile.rmsd_policy["symmetry_mapping"])
    _require(symmetry_mapping == tuple(range(atom_count)), "post-Opt dedup requires identity-only symmetry")
    if profile.rmsd_policy["atom_selection"] == "all":
        atom_indices = tuple(range(atom_count))
    else:
        atom_indices = tuple(
            index
            for index, explicit_hydrogen in enumerate(prior.species_binding["explicit_hydrogens"])
            if explicit_hydrogen is False
        )
    _require(bool(atom_indices), "post-Opt mapped RMSD atom selection is empty")
    duplicate_threshold = float(profile.rmsd_policy["duplicate_threshold"]["value"])
    review_minimum = float(profile.rmsd_policy["review_band"]["minimum"])
    review_maximum = float(profile.rmsd_policy["review_band"]["maximum"])
    _require(
        all(isfinite(value) for value in (duplicate_threshold, review_minimum, review_maximum)),
        "post-Opt RMSD policy is non-finite",
    )

    comparisons: list[dict[str, object]] = []
    new_blockers: list[dict[str, object]] = []
    for left_index, left_id in enumerate(post_opt_valid):
        for right_id in post_opt_valid[left_index + 1:]:
            rmsd = mapped_rmsd(optimized_coordinates[left_id], optimized_coordinates[right_id], atom_indices)
            pair = (left_id, right_id)
            if review_minimum <= rmsd <= review_maximum:
                decision = "pending_independent_review"
                new_blockers.append({
                    "stage": "post_dft_optimization_geometry", "member_ids": pair,
                    "mapped_rmsd_angstrom": rmsd, "reason": "post_opt_rmsd_review_band",
                    "status": "pending_independent_review",
                })
            else:
                decision = "duplicate" if rmsd <= duplicate_threshold else "independent"
            comparisons.append({
                "stage": "post_dft_optimization_geometry", "member_ids": pair,
                "mapped_rmsd_angstrom": rmsd,
                "duplicate_threshold_angstrom": duplicate_threshold,
                "review_band_angstrom": (review_minimum, review_maximum),
                "atom_indices": atom_indices, "symmetry_mapping": "identity_only",
                "decision": decision,
            })

    canonical_index = {member_id: index for index, member_id in enumerate(canonical_member_ids)}
    clusters_raw = sorted(
        union_clusters(post_opt_valid, comparisons),
        key=lambda members: min(canonical_index[member_id] for member_id in members),
    )
    representative_by_member: dict[str, str] = {}
    new_clusters: list[dict[str, object]] = []
    for index, cluster_members in enumerate(clusters_raw, 1):
        ordered_members = tuple(sorted(cluster_members, key=canonical_index.__getitem__))
        representative = ordered_members[0]
        for member_id in ordered_members:
            representative_by_member[member_id] = representative
        new_clusters.append({
            "cluster_id": f"post-dft-cluster-{index:04d}",
            "stage": "post_dft_optimization_geometry", "member_ids": ordered_members,
            "representative_member_id": representative,
            "tie_breaker": "prior_ensemble_member_order",
        })
    survivors = tuple(
        member_id for member_id in canonical_member_ids
        if representative_by_member.get(member_id) == member_id
    )

    minima = _resolve_current_authorities(
        prior,
        positive_frequency_inputs,
        name="positive_frequency_inputs",
        expected_keys=_FREQ_INPUT_KEYS,
        validator=_validate_current_two_stage_minimum_authority,
    )
    negative_frequencies = _resolve_current_authorities(
        prior,
        negative_frequency_inputs,
        name="negative_frequency_inputs",
        expected_keys=_FREQ_INPUT_KEYS,
        validator=validate_negative_frequency_authority,
    )
    _require(
        not (set(minima) & set(negative_frequencies)),
        "a survivor cannot have both positive and negative Freq authority",
    )
    _require(
        set(minima) | set(negative_frequencies) == set(survivors),
        "Freq disposition set must equal the complete post-Opt survivor set",
    )
    for member_id, minimum in minima.items():
        _closed_minimum_authority(minimum, prior, members_by_id[member_id], optimizations[member_id])
    for member_id, negative in negative_frequencies.items():
        _closed_negative_authority(negative, prior, members_by_id[member_id], stage="freq")
        _require(
            negative["optimization"] == optimizations[member_id],
            "negative Freq authority names another optimization authority",
        )
        _require(
            negative["method_id"] == optimizations[member_id]["method_id"],
            "negative Freq authority method is incompatible",
        )

    post_dft_negative: list[Mapping[str, object]] = []
    for member_id in canonical_member_ids:
        if member_id in negative_optimizations:
            post_dft_negative.append(_negative_projection(member_id, negative_optimizations[member_id], stage="opt"))
        elif member_id in identity_rejections:
            audit_payload = {
                "member_id": member_id, "stage": "post_dft_identity_audit",
                "optimization_geometry_authority_id": optimizations[member_id]["optimization_geometry_authority_id"],
                "reasons": identity_rejections[member_id],
            }
            post_dft_negative.append({
                **audit_payload, "status": "post_dft_identity_rejected",
                "retained_as_negative_evidence": True,
                "audit_decision_id": _payload_sha256({"domain": "v31-post-opt-identity-audit/1", **audit_payload}),
            })
        elif representative_by_member.get(member_id) != member_id:
            representative = representative_by_member[member_id]
            cluster = next(
                item for item in new_clusters if member_id in item["member_ids"]
            )
            duplicate_edges = tuple(
                item
                for item in comparisons
                if item["decision"] == "duplicate"
                and set(item["member_ids"]) <= set(cluster["member_ids"])
            )
            post_dft_negative.append({
                "member_id": member_id, "stage": "post_dft_dedup",
                "status": "post_dft_duplicate", "reasons": ("post_opt_mapped_rmsd_duplicate",),
                "retained_as_negative_evidence": True,
                "duplicate_of_member_id": representative,
                "optimization_geometry_authority_id": optimizations[member_id]["optimization_geometry_authority_id"],
                "dedup_decision_sha256": _payload_sha256({
                    "cluster": cluster,
                    "duplicate_edges": duplicate_edges,
                }),
            })
        elif member_id in negative_frequencies:
            post_dft_negative.append(_negative_projection(member_id, negative_frequencies[member_id], stage="freq"))

    refined_members = []
    post_dft_audit = []
    for member_id in canonical_member_ids:
        member = dict(members_by_id[member_id])
        positive_opt = optimizations.get(member_id)
        negative_opt = negative_optimizations.get(member_id)
        minimum = minima.get(member_id)
        negative_frequency = negative_frequencies.get(member_id)
        identity_rejected = member_id in identity_rejections
        representative = representative_by_member.get(member_id)
        duplicate = representative is not None and representative != member_id
        if positive_opt is not None and not identity_rejected:
            member["coordinates_angstrom"] = optimized_coordinates[member_id]
        if negative_opt is not None:
            status = "optimization_failed"
        elif identity_rejected:
            status = "post_opt_identity_rejected"
        elif duplicate:
            status = "deduplicated_after_optimization"
        elif negative_frequency is not None:
            status = "frequency_failed"
        else:
            status = "validated_minimum"
        member.update({
            "post_dft_cluster_id": next(
                (cluster["cluster_id"] for cluster in new_clusters if member_id in cluster["member_ids"]),
                None,
            ),
            "post_dft_representative_member_id": representative,
            "post_dft_minimum_evidence_available": minimum is not None,
            "optimization_geometry_authority": positive_opt,
            "negative_optimization_authority": negative_opt,
            "two_stage_minimum_authority": minimum,
            "negative_frequency_authority": negative_frequency,
            "post_dft_status": status,
            "post_dft_duplicate_of_member_id": representative if duplicate else None,
        })
        refined_members.append(member)
        post_dft_audit.append({
            "member_id": member_id, "stage": "post_dft_refinement", "status": status,
            "optimization_geometry_authority_id": None if positive_opt is None else positive_opt["optimization_geometry_authority_id"],
            "negative_optimization_authority_id": None if negative_opt is None else negative_opt["negative_optimization_authority_id"],
            "two_stage_minimum_authority_id": None if minimum is None else minimum["two_stage_minimum_authority_id"],
            "negative_frequency_authority_id": None if negative_frequency is None else negative_frequency["negative_frequency_authority_id"],
            "method_id": positive_opt["method_id"] if positive_opt is not None else negative_opt["method_id"],  # type: ignore[index]
        })

    blockers = tuple(prior.independent_review_blockers) + tuple(new_blockers)
    obligations = prior.coverage.get("obligations")
    _require(
        isinstance(obligations, Mapping),
        "source ensemble coverage obligations are missing or malformed",
    )
    fragment_association_complete = obligations.get(
        "fragment_association_semantics_complete"
    )
    _require(
        type(fragment_association_complete) is bool,
        "source ensemble fragment-association obligation is missing or malformed",
    )
    projection_unblocked = not blockers and fragment_association_complete
    coverage_status = prior.coverage["status"]
    thermo_statuses = set(profile.thermodynamic_eligibility_policy["required_coverage_statuses"])
    thermodynamic_eligible_members = tuple(
        member_id for member_id in survivors
        if member_id in minima and projection_unblocked and coverage_status in thermo_statuses
    )
    ts_statuses = set(profile.ts_seed_projection_policy["required_coverage_statuses"])
    allowed_tags = set(profile.ts_seed_projection_policy["allowed_relevance_tags"])
    ts_seed_members = tuple(
        member_id for member_id in survivors
        if member_id in minima
        and projection_unblocked
        and coverage_status in ts_statuses
        and allowed_tags.intersection(members_by_id[member_id]["relevance_tags"])
    )

    try:
        return ConformerEnsemble._create(
            project_id=prior.project_id,
            calculation_plan_id=prior.calculation_plan_id,
            calculation_plan_revision=prior.calculation_plan_revision,
            profile=profile,
            sampling_observations=prior.sampling_observations,
            audit_evidence=tuple(prior.audit_evidence) + tuple(post_dft_audit),
            negative_evidence=tuple(prior.negative_evidence) + tuple(post_dft_negative),
            dedup_decisions=tuple(prior.dedup_decisions) + tuple(comparisons),
            independent_review_blockers=blockers,
            clusters=tuple(prior.clusters) + tuple(new_clusters),
            members=refined_members,
            coverage=prior.coverage,
            thermodynamic_eligible_members=thermodynamic_eligible_members,
            ts_seed_members=ts_seed_members,
            revision=prior.revision + 1,
            supersedes_conformer_ensemble_id=prior.conformer_ensemble_id,
        )
    except ValueError as exc:
        raise RefinementError(str(exc)) from exc
