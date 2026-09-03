"""Offline acceptance tests for private V31 final ensemble composition."""

from __future__ import annotations

from dataclasses import fields
import math
import unittest

import auto_g16.conformer as conformer
import auto_g16.thermochemistry as thermochemistry
from auto_g16.conformer.final_integration import (
    _FinalIntegrationError,
    _validate_final_ensemble_integration,
)
from auto_g16.conformer.models import ConformerEnsemble, SamplingProfile
from auto_g16.thermochemistry.models import (
    ThermodynamicEnsemble,
    _identified_payload,
)


def _profile() -> SamplingProfile:
    return SamplingProfile._create(
        revision=1,
        supersedes_sampling_profile_id=None,
        species_binding={"species_id": "species-1"},
        stereochemistry_binding={"stereochemistry_id": "stereo-1"},
        bond_change_policy="forbid",
        geometry_legality_policy={"finite_coordinates": True},
        crest_imtd_gc_profile={"configuration_id": "crest-config-1"},
        rmsd_policy={"metric": "mapped"},
        clustering_policy={"method": "complete-linkage"},
        descriptor_policy=({"descriptor": "mapped-rmsd"},),
        coverage_policy={"statuses": ["sufficient", "uncertain", "insufficient"]},
        thermodynamic_eligibility_policy={"require_validated_minimum": True},
        ts_seed_projection_policy={"source": "reviewed_relevance"},
    )


def _conformer(
    profile: SamplingProfile,
    *,
    coverage_status: str = "sufficient",
    fragment_complete: bool = True,
    thermodynamic_members: tuple[str, ...] = ("member-a", "member-b"),
    ts_seed_members: tuple[str, ...] = ("member-b", "member-c"),
) -> ConformerEnsemble:
    members = tuple(
        {
            "member_id": member_id,
            "coordinates_sha256": character * 64,
            "post_dft_status": "validated_minimum",
            "relevance_tags": ("ts_seed",) if member_id in ts_seed_members else (),
        }
        for member_id, character in (("member-a", "a"), ("member-b", "b"), ("member-c", "c"))
    )
    return ConformerEnsemble._create(
        project_id="project-1",
        calculation_plan_id="plan-1",
        calculation_plan_revision=3,
        profile=profile,
        sampling_observations=({"observation_id": "sampling-1"},),
        audit_evidence=({"audit_id": "audit-1", "status": "complete"},),
        negative_evidence=({"candidate_id": "rejected-1", "reason": "stereo_drift"},),
        dedup_decisions=({"decision_id": "dedup-1", "status": "distinct"},),
        independent_review_blockers=(),
        clusters=({"cluster_id": "cluster-1", "member_ids": ("member-a",)},),
        members=members,
        coverage={
            "status": coverage_status,
            "fragment_association_semantics_complete": fragment_complete,
            "adequacy_claim": "bounded_only",
        },
        thermodynamic_eligible_members=thermodynamic_members,
        ts_seed_members=ts_seed_members,
        revision=2,
        supersedes_conformer_ensemble_id="conformer-ensemble-predecessor",
    )


def _thermodynamic(
    ensemble: ConformerEnsemble,
    *,
    temperature_k: float = 298.15,
    policy_name: str = "explicit-policy-a",
) -> ThermodynamicEnsemble:
    gas_constant_hartree = 3.166811563e-6
    log_weights = (0.0, math.log(1.0 / 3.0))
    scaled_partition = math.fsum(math.exp(value) for value in log_weights)
    log_partition = math.log(scaled_partition)
    populations = tuple(math.exp(value - log_partition) for value in log_weights)
    reference_gibbs = -100.0
    treated_gibbs = (
        reference_gibbs,
        reference_gibbs + gas_constant_hartree * temperature_k * math.log(3.0),
    )
    policy = {"name": policy_name, "temperature_k": temperature_k, "standard_state": "1M"}
    policy_id, policy_hash = _identified_payload("thermochemistry-policy", policy)
    implementation = {"adapter": "qualified-functional-kernel", "version": 2}
    implementation_id, _implementation_hash = _identified_payload(
        "functional-kernel-implementation", implementation
    )
    method = {"method": "RB3LYP", "basis": "def2-SVP", "solvent": "SMD"}
    method_id, _method_hash = _identified_payload("thermochemistry-method", method)
    observations = tuple(
        {
            "member_id": member_id,
            "source_refined_conformer_ensemble_id": ensemble.conformer_ensemble_id,
            "source_refined_conformer_ensemble_revision": ensemble.revision,
            "two_stage_minimum_authority_id": f"minimum-{member_id}",
            "method_compatibility_id": method_id,
            "method_compatibility_binding": method,
            "source_provenance": {"source_result_id": f"result-{member_id}"},
            "temperature_k": temperature_k,
            "standard_state": "1M",
            "raw_rrho": {"gibbs_free_energy_hartree": gibbs - 0.001},
            "treated_qrrho": {"gibbs_free_energy_hartree": gibbs},
            "degeneracy": 1,
            "degeneracy_rationale": "explicit synthetic degeneracy",
            "inclusion_status": "included_thermodynamic_eligible",
            "relative_statistical_weight": {
                "log_value": log_weight,
                "representation": "natural_log_relative_to_reference_gibbs",
            },
            "normalized_population": population,
        }
        for member_id, gibbs, log_weight, population in zip(
            ensemble.thermodynamic_eligible_members,
            treated_gibbs,
            log_weights,
            populations,
            strict=True,
        )
    )
    population_sum = math.fsum(populations)
    return ThermodynamicEnsemble._create(
        conformer_ensemble_id=ensemble.conformer_ensemble_id,
        conformer_ensemble_payload_sha256=ensemble.payload_sha256,
        conformer_ensemble_revision=ensemble.revision,
        source_member_ids=ensemble.thermodynamic_eligible_members,
        temperature_k=temperature_k,
        standard_state="1M",
        standard_state_binding={"kind": "1M", "temperature_k": temperature_k},
        gas_constant_binding={
            "gas_constant_j_per_mol_k": 8.31446261815324,
            "joule_per_hartree_mol": 2625499.6394799,
            "gas_constant_hartree_per_mol_k": gas_constant_hartree,
            "unit_convention": "per_mole_hartree_kelvin",
        },
        thermochemistry_policy_id=policy_id,
        thermochemistry_policy_payload_sha256=policy_hash,
        thermochemistry_policy=policy,
        functional_kernel_implementation_id=implementation_id,
        functional_kernel_implementation_binding=implementation,
        low_frequency_treatment={"scheme": "explicit-qualified-synthetic"},
        method_compatibility_id=method_id,
        method_compatibility_binding=method,
        member_observations=observations,
        partition_evidence={
            "reference_member_id": "member-a",
            "reference_gibbs_hartree": reference_gibbs,
            "representation": "stable_logsumexp",
            "log_scale": 0.0,
            "scaled_relative_partition_function": scaled_partition,
            "log_relative_partition_function": log_partition,
        },
        population_normalization={
            "population_sum": population_sum,
            "absolute_error": abs(population_sum - 1.0),
            "numeric_tolerance": 1.0e-12,
            "status": "normalized",
            "tolerance_purpose": "floating_point_normalization_only_not_scientific_selection",
        },
        ensemble_treated_free_energy_hartree=(
            reference_gibbs - gas_constant_hartree * temperature_k * log_partition
        ),
    )


def _clone_thermodynamic(
    source: ThermodynamicEnsemble,
    **overrides: object,
) -> ThermodynamicEnsemble:
    values = {
        item.name: getattr(source, item.name)
        for item in fields(ThermodynamicEnsemble)
        if item.name not in {"schema_version", "thermodynamic_ensemble_id", "payload_sha256"}
    }
    values.update(overrides)
    return ThermodynamicEnsemble._create(**values)


def _clone_conformer(
    source: ConformerEnsemble,
    profile: SamplingProfile,
    **overrides: object,
) -> ConformerEnsemble:
    values = {
        "project_id": source.project_id,
        "calculation_plan_id": source.calculation_plan_id,
        "calculation_plan_revision": source.calculation_plan_revision,
        "profile": profile,
        "sampling_observations": source.sampling_observations,
        "audit_evidence": source.audit_evidence,
        "negative_evidence": source.negative_evidence,
        "dedup_decisions": source.dedup_decisions,
        "independent_review_blockers": source.independent_review_blockers,
        "clusters": source.clusters,
        "members": source.members,
        "coverage": source.coverage,
        "thermodynamic_eligible_members": source.thermodynamic_eligible_members,
        "ts_seed_members": source.ts_seed_members,
        "revision": source.revision,
        "supersedes_conformer_ensemble_id": source.supersedes_conformer_ensemble_id,
    }
    values.update(overrides)
    return ConformerEnsemble._create(**values)


def _rebind_thermodynamic(
    source: ThermodynamicEnsemble,
    ensemble: ConformerEnsemble,
) -> ThermodynamicEnsemble:
    observations = tuple(
        {
            **item,
            "source_refined_conformer_ensemble_id": ensemble.conformer_ensemble_id,
            "source_refined_conformer_ensemble_revision": ensemble.revision,
        }
        for item in source.member_observations
    )
    return _clone_thermodynamic(
        source,
        conformer_ensemble_id=ensemble.conformer_ensemble_id,
        conformer_ensemble_payload_sha256=ensemble.payload_sha256,
        conformer_ensemble_revision=ensemble.revision,
        source_member_ids=ensemble.thermodynamic_eligible_members,
        member_observations=observations,
    )


class FinalEnsembleIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = _profile()
        self.refined = _conformer(self.profile)
        self.thermodynamic = _thermodynamic(self.refined)

    def assert_rejected(self, ensemble: ConformerEnsemble, thermo: ThermodynamicEnsemble) -> None:
        with self.assertRaises(_FinalIntegrationError):
            _validate_final_ensemble_integration(ensemble, thermo)

    def test_exact_pair_preserves_independent_projections_and_authoritative_records(self) -> None:
        result = _validate_final_ensemble_integration(self.refined, self.thermodynamic)

        self.assertIs(result[0], self.refined)
        self.assertIs(result[1], self.thermodynamic)
        self.assertEqual(result[2], ("member-b", "member-c"))
        self.assertEqual(result[1].source_member_ids, ("member-a", "member-b"))
        self.assertEqual(result[0].negative_evidence, self.refined.negative_evidence)
        self.assertAlmostEqual(result[1].member_observations[0]["normalized_population"], 0.75)
        self.assertAlmostEqual(result[1].member_observations[1]["normalized_population"], 0.25)

    def test_direct_conformer_binding_must_match_id_payload_and_revision(self) -> None:
        for overrides in (
            {"conformer_ensemble_id": "conformer-ensemble-" + "0" * 64},
            {"conformer_ensemble_payload_sha256": "0" * 64},
            {"conformer_ensemble_revision": self.refined.revision + 1},
        ):
            with self.subTest(overrides=overrides):
                self.assert_rejected(
                    self.refined,
                    _clone_thermodynamic(self.thermodynamic, **overrides),
                )

    def test_tampered_record_identities_reject(self) -> None:
        object.__setattr__(self.refined, "payload_sha256", "0" * 64)
        self.assert_rejected(self.refined, self.thermodynamic)

        refined = _conformer(self.profile)
        thermo = _thermodynamic(refined)
        object.__setattr__(refined, "conformer_ensemble_id", "conformer-ensemble-" + "0" * 64)
        self.assert_rejected(refined, thermo)

        refined = _conformer(self.profile)
        thermo = _thermodynamic(refined)
        object.__setattr__(thermo, "thermodynamic_ensemble_id", "thermodynamic-ensemble-" + "0" * 64)
        self.assert_rejected(refined, thermo)

    def test_ordered_thermodynamic_member_set_is_exact(self) -> None:
        for source_ids in (
            ("member-a",),
            ("member-a", "member-b", "member-c"),
            ("member-b", "member-a"),
        ):
            with self.subTest(source_ids=source_ids):
                self.assert_rejected(
                    self.refined,
                    _clone_thermodynamic(self.thermodynamic, source_member_ids=source_ids),
                )

    def test_member_observations_are_complete_unique_and_have_no_extras(self) -> None:
        first, second = self.thermodynamic.member_observations
        extra = {**second, "member_id": "member-c"}
        for observations in ((first,), (first, second, extra), (first, first)):
            with self.subTest(member_ids=tuple(item["member_id"] for item in observations)):
                self.assert_rejected(
                    self.refined,
                    _clone_thermodynamic(self.thermodynamic, member_observations=observations),
                )

    def test_ts_seed_must_resolve_once_but_need_not_be_thermodynamic(self) -> None:
        invalid = _clone_conformer(
            self.refined,
            self.profile,
            ts_seed_members=("member-b", "missing-member"),
        )
        self.assert_rejected(invalid, _rebind_thermodynamic(self.thermodynamic, invalid))

        result = _validate_final_ensemble_integration(self.refined, self.thermodynamic)
        self.assertIn("member-c", result[2])
        self.assertNotIn("member-c", result[1].source_member_ids)
        self.assertNotIn("member-a", result[2])

    def test_population_and_partition_inconsistency_reject_without_renormalizing(self) -> None:
        first, second = self.thermodynamic.member_observations
        bad_observations = (first, {**second, "normalized_population": 0.20})
        self.assert_rejected(
            self.refined,
            _clone_thermodynamic(self.thermodynamic, member_observations=bad_observations),
        )

        bad_partition = {
            **self.thermodynamic.partition_evidence,
            "scaled_relative_partition_function": 2.0,
        }
        self.assert_rejected(
            self.refined,
            _clone_thermodynamic(self.thermodynamic, partition_evidence=bad_partition),
        )

    def test_coverage_and_fragment_adequacy_are_preserved_without_promotion(self) -> None:
        refined = _clone_conformer(
            self.refined,
            self.profile,
            coverage={
                "status": "insufficient",
                "fragment_association_semantics_complete": False,
                "adequacy_claim": "bounded_only",
            },
        )
        thermo = _rebind_thermodynamic(self.thermodynamic, refined)

        result = _validate_final_ensemble_integration(refined, thermo)

        self.assertIs(result[0], refined)
        self.assertEqual(result[0].coverage["status"], "insufficient")
        self.assertIs(result[0].coverage["fragment_association_semantics_complete"], False)

    def test_explicit_alternative_temperature_and_policy_remain_valid(self) -> None:
        alternative = _thermodynamic(
            self.refined,
            temperature_k=310.0,
            policy_name="explicit-policy-b",
        )

        result = _validate_final_ensemble_integration(self.refined, alternative)

        self.assertIs(result[1], alternative)
        self.assertEqual(result[1].temperature_k, 310.0)
        self.assertEqual(result[1].thermochemistry_policy["name"], "explicit-policy-b")

    def test_same_exact_inputs_produce_the_same_private_view(self) -> None:
        first = _validate_final_ensemble_integration(self.refined, self.thermodynamic)
        second = _validate_final_ensemble_integration(self.refined, self.thermodynamic)
        self.assertEqual(first, second)
        self.assertIs(first[0], second[0])
        self.assertIs(first[1], second[1])

    def test_public_scientific_record_surface_is_unchanged(self) -> None:
        self.assertEqual(conformer.__all__, ["ConformerEnsemble", "SamplingProfile"])
        self.assertEqual(thermochemistry.__all__, ["ThermodynamicEnsemble"])
        self.assertFalse(hasattr(conformer, "FinalEnsemble"))
        self.assertFalse(hasattr(conformer, "TSSeedRecord"))
        self.assertFalse(hasattr(conformer, "_validate_final_ensemble_integration"))


if __name__ == "__main__":
    unittest.main()
