"""Two immutable public records for the V31 conformer sampling core."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import hashlib
import json
from math import isfinite
from types import MappingProxyType


def _freeze(value: object, path: str, active: set[int] | None = None) -> object:
    """Copy supported policy data into an immutable, finite value tree."""

    containers = set() if active is None else active
    if value is None or type(value) in {bool, int, str}:
        return value
    if type(value) is float:
        if not isfinite(value):
            raise ValueError(f"{path} must not contain a non-finite float")
        return value
    if isinstance(value, Mapping):
        identity = id(value)
        if identity in containers:
            raise ValueError(f"{path} must not contain a container cycle")
        containers.add(identity)
        try:
            for key in value:
                if not isinstance(key, str) or not key or key != key.strip():
                    raise ValueError(f"{path} keys must be non-empty canonical strings")
            return MappingProxyType(
                {key: _freeze(value[key], f"{path}.{key}", containers) for key in sorted(value)}
            )
        finally:
            containers.remove(identity)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        identity = id(value)
        if identity in containers:
            raise ValueError(f"{path} must not contain a container cycle")
        containers.add(identity)
        try:
            return tuple(_freeze(item, f"{path}[{index}]", containers) for index, item in enumerate(value))
        finally:
            containers.remove(identity)
    raise ValueError(f"{path} contains unsupported value type {type(value).__name__}")


def _freeze_mapping(value: object, path: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{path} must be a mapping")
    frozen = _freeze(value, path)
    assert isinstance(frozen, Mapping)
    return frozen


def _plain_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _plain_value(value[key]) for key in sorted(value)}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_plain_value(item) for item in value]
    return value


def _payload_sha256(value: object) -> str:
    encoded = json.dumps(
        _plain_value(value),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _identified_payload(domain: str, payload: Mapping[str, object]) -> tuple[str, str]:
    digest = _payload_sha256({"domain": domain, "payload": payload})
    return f"{domain}-{digest}", _payload_sha256(payload)


class ConformerError(ValueError):
    """A profile or observation cannot form a deterministic V31 ensemble."""


@dataclass(frozen=True, slots=True, kw_only=True, init=False)
class SamplingProfile:
    """One exact, observation-independent conformer sampling policy."""

    schema_version: int
    sampling_profile_id: str = field(init=False)
    payload_sha256: str = field(init=False)
    revision: int
    supersedes_sampling_profile_id: str | None
    species_binding: Mapping[str, object]
    stereochemistry_binding: Mapping[str, object]
    bond_change_policy: str
    geometry_legality_policy: Mapping[str, object]
    crest_imtd_gc_profile: Mapping[str, object]
    rmsd_policy: Mapping[str, object]
    clustering_policy: Mapping[str, object]
    descriptor_policy: tuple[Mapping[str, object], ...]
    coverage_policy: Mapping[str, object]
    thermodynamic_eligibility_policy: Mapping[str, object]
    ts_seed_projection_policy: Mapping[str, object]

    def __init__(self) -> None:
        raise TypeError("SamplingProfile is service-created")

    @classmethod
    def _create(
        cls,
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
        value = object.__new__(cls)
        object.__setattr__(value, "schema_version", 1)
        object.__setattr__(value, "revision", revision)
        object.__setattr__(value, "supersedes_sampling_profile_id", supersedes_sampling_profile_id)
        object.__setattr__(value, "bond_change_policy", bond_change_policy)
        for name, supplied in (
            ("species_binding", species_binding),
            ("stereochemistry_binding", stereochemistry_binding),
            ("geometry_legality_policy", geometry_legality_policy),
            ("crest_imtd_gc_profile", crest_imtd_gc_profile),
            ("rmsd_policy", rmsd_policy),
            ("clustering_policy", clustering_policy),
            ("coverage_policy", coverage_policy),
            ("thermodynamic_eligibility_policy", thermodynamic_eligibility_policy),
            ("ts_seed_projection_policy", ts_seed_projection_policy),
        ):
            object.__setattr__(value, name, _freeze_mapping(supplied, name))
        frozen = _freeze(tuple(descriptor_policy), "descriptor_policy")
        assert isinstance(frozen, tuple) and all(isinstance(item, Mapping) for item in frozen)
        object.__setattr__(value, "descriptor_policy", frozen)
        profile_id, payload_hash = _identified_payload("sampling-profile", value._identity_payload())
        object.__setattr__(value, "sampling_profile_id", profile_id)
        object.__setattr__(value, "payload_sha256", payload_hash)
        return value

    def _identity_payload(self) -> Mapping[str, object]:
        return {
            "schema_version": self.schema_version,
            "revision": self.revision,
            "supersedes_sampling_profile_id": self.supersedes_sampling_profile_id,
            "species_binding": self.species_binding,
            "stereochemistry_binding": self.stereochemistry_binding,
            "bond_change_policy": self.bond_change_policy,
            "geometry_legality_policy": self.geometry_legality_policy,
            "crest_imtd_gc_profile": self.crest_imtd_gc_profile,
            "rmsd_policy": self.rmsd_policy,
            "clustering_policy": self.clustering_policy,
            "descriptor_policy": self.descriptor_policy,
            "coverage_policy": self.coverage_policy,
            "thermodynamic_eligibility_policy": self.thermodynamic_eligibility_policy,
            "ts_seed_projection_policy": self.ts_seed_projection_policy,
        }


@dataclass(frozen=True, slots=True, kw_only=True, init=False)
class ConformerEnsemble:
    """One immutable sampling-stage audit and deterministic projection."""

    schema_version: int
    conformer_ensemble_id: str = field(init=False)
    payload_sha256: str = field(init=False)
    revision: int
    supersedes_conformer_ensemble_id: str | None
    project_id: str
    calculation_plan_id: str
    calculation_plan_revision: int
    sampling_profile_id: str
    sampling_profile_payload_sha256: str
    species_binding: Mapping[str, object]
    stereochemistry_binding: Mapping[str, object]
    sampling_observations: tuple[Mapping[str, object], ...]
    audit_evidence: tuple[Mapping[str, object], ...]
    negative_evidence: tuple[Mapping[str, object], ...]
    dedup_decisions: tuple[Mapping[str, object], ...]
    independent_review_blockers: tuple[Mapping[str, object], ...]
    clusters: tuple[Mapping[str, object], ...]
    members: tuple[Mapping[str, object], ...]
    coverage: Mapping[str, object]
    thermodynamic_eligible_members: tuple[str, ...]
    ts_seed_members: tuple[str, ...]

    def __init__(self) -> None:
        raise TypeError("ConformerEnsemble is service-created")

    @classmethod
    def _create(
        cls,
        *,
        project_id: str,
        calculation_plan_id: str,
        calculation_plan_revision: int,
        profile: SamplingProfile,
        sampling_observations: Sequence[Mapping[str, object]],
        audit_evidence: Sequence[Mapping[str, object]],
        negative_evidence: Sequence[Mapping[str, object]],
        dedup_decisions: Sequence[Mapping[str, object]],
        independent_review_blockers: Sequence[Mapping[str, object]],
        clusters: Sequence[Mapping[str, object]],
        members: Sequence[Mapping[str, object]],
        coverage: Mapping[str, object],
        thermodynamic_eligible_members: Sequence[str],
        ts_seed_members: Sequence[str],
        revision: int = 1,
        supersedes_conformer_ensemble_id: str | None = None,
    ) -> ConformerEnsemble:
        if type(revision) is not int or revision < 1:
            raise ValueError("ConformerEnsemble revision must be a positive integer")
        if revision == 1:
            if supersedes_conformer_ensemble_id is not None:
                raise ValueError("ConformerEnsemble revision 1 cannot supersede an ensemble")
        elif (
            not isinstance(supersedes_conformer_ensemble_id, str)
            or not supersedes_conformer_ensemble_id
            or supersedes_conformer_ensemble_id != supersedes_conformer_ensemble_id.strip()
        ):
            raise ValueError("a successor ConformerEnsemble must name its exact predecessor")
        value = object.__new__(cls)
        object.__setattr__(value, "schema_version", 1)
        object.__setattr__(value, "revision", revision)
        object.__setattr__(value, "supersedes_conformer_ensemble_id", supersedes_conformer_ensemble_id)
        object.__setattr__(value, "project_id", project_id)
        object.__setattr__(value, "calculation_plan_id", calculation_plan_id)
        object.__setattr__(value, "calculation_plan_revision", calculation_plan_revision)
        object.__setattr__(value, "sampling_profile_id", profile.sampling_profile_id)
        object.__setattr__(value, "sampling_profile_payload_sha256", profile.payload_sha256)
        object.__setattr__(value, "species_binding", profile.species_binding)
        object.__setattr__(value, "stereochemistry_binding", profile.stereochemistry_binding)
        for name, supplied in (
            ("sampling_observations", sampling_observations),
            ("audit_evidence", audit_evidence),
            ("negative_evidence", negative_evidence),
            ("dedup_decisions", dedup_decisions),
            ("independent_review_blockers", independent_review_blockers),
            ("clusters", clusters),
            ("members", members),
        ):
            frozen = _freeze(tuple(supplied), name)
            assert isinstance(frozen, tuple) and all(isinstance(item, Mapping) for item in frozen)
            object.__setattr__(value, name, frozen)
        object.__setattr__(value, "coverage", _freeze_mapping(coverage, "coverage"))
        object.__setattr__(value, "thermodynamic_eligible_members", tuple(thermodynamic_eligible_members))
        object.__setattr__(value, "ts_seed_members", tuple(ts_seed_members))
        ensemble_id, payload_hash = _identified_payload("conformer-ensemble", value._identity_payload())
        object.__setattr__(value, "conformer_ensemble_id", ensemble_id)
        object.__setattr__(value, "payload_sha256", payload_hash)
        return value

    def _identity_payload(self) -> Mapping[str, object]:
        return {
            "schema_version": self.schema_version,
            "revision": self.revision,
            "supersedes_conformer_ensemble_id": self.supersedes_conformer_ensemble_id,
            "project_id": self.project_id,
            "calculation_plan_id": self.calculation_plan_id,
            "calculation_plan_revision": self.calculation_plan_revision,
            "sampling_profile_id": self.sampling_profile_id,
            "sampling_profile_payload_sha256": self.sampling_profile_payload_sha256,
            "species_binding": self.species_binding,
            "stereochemistry_binding": self.stereochemistry_binding,
            "sampling_observations": self.sampling_observations,
            "audit_evidence": self.audit_evidence,
            "negative_evidence": self.negative_evidence,
            "dedup_decisions": self.dedup_decisions,
            "independent_review_blockers": self.independent_review_blockers,
            "clusters": self.clusters,
            "members": self.members,
            "coverage": self.coverage,
            "thermodynamic_eligible_members": self.thermodynamic_eligible_members,
            "ts_seed_members": self.ts_seed_members,
        }
