"""Offline acceptance tests for private V31 final ensemble composition."""

from __future__ import annotations

from dataclasses import fields
import math
from pathlib import Path
import subprocess
import sys
import unittest

import auto_g16.conformer as conformer
import auto_g16.thermochemistry as thermochemistry
from auto_g16.conformer.final_integration import (
    _FinalIntegrationError,
    _validate_final_ensemble_integration,
)
from auto_g16.conformer.models import (
    ConformerEnsemble,
    SamplingProfile,
    _identified_payload as _conformer_identified_payload,
    _payload_sha256 as _conformer_payload_sha256,
)
from auto_g16.thermochemistry.models import (
    ThermodynamicEnsemble,
    _identified_payload,
)


def _profile() -> SamplingProfile:
    return SamplingProfile._create(
        revision=1,
        supersedes_sampling_profile_id=None,
        species_binding={
            "species_id": "species-1",
            "atom_order": ("atom-1", "atom-2", "atom-3"),
            "atom_mapping": (1, 2, 3),
        },
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


def _frequency_result(member_id: str) -> dict[str, object]:
    character = {"member-a": "a", "member-b": "b", "member-c": "c"}[member_id]
    artifact = {
        "envelope_observation_id": f"envelope-{member_id}",
        "artifact_kind": "gaussian-log",
        "logical_name": f"{member_id}.log",
        "sha256": character * 64,
        "size_bytes": 1000,
    }
    return {
        "result_id": f"result-{member_id}",
        "result_payload_sha256": character * 64,
        "source_artifact": artifact,
        "job_section": {**artifact, "start": 10, "end": 900},
        "frequency_blocks": ({
            "source_span": {**artifact, "start": 100, "end": 200},
            "frequencies_cm-1": (100.0, 200.0, 300.0),
        },),
        "frequencies_cm1": (100.0, 200.0, 300.0),
        "mode_count": 3,
        "v30_outcome": {
            "minimum_validation_outcome_id": f"outcome-{member_id}",
            "classification": "INCOMPLETE",
            "reason_code": "incomplete-marker-pair",
        },
    }


def _conformer(
    profile: SamplingProfile,
    *,
    predecessor: ConformerEnsemble | None = None,
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
            "two_stage_minimum_authority": {
                "two_stage_minimum_authority_id": f"minimum-{member_id}",
                "frequency": {"result": _frequency_result(member_id)},
            },
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
        supersedes_conformer_ensemble_id=(predecessor or _predecessor(profile)).conformer_ensemble_id,
    )


def _predecessor(profile: SamplingProfile) -> ConformerEnsemble:
    members = tuple({
        "member_id": member_id,
        "coordinates_angstrom": ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, float(index), 0.0)),
    } for index, member_id in enumerate(("member-a", "member-b", "member-c"), start=1))
    return ConformerEnsemble._create(
        project_id="project-1", calculation_plan_id="plan-1", calculation_plan_revision=3,
        profile=profile, members=members, sampling_observations=(), audit_evidence=(),
        negative_evidence=(), dedup_decisions=(), independent_review_blockers=(), clusters=(),
        coverage={"status": "sufficient"}, thermodynamic_eligible_members=(), ts_seed_members=(),
        revision=1, supersedes_conformer_ensemble_id=None,
    )


def _source_provenance(
    member_id: str,
    ensemble: ConformerEnsemble,
) -> dict[str, object]:
    frequency_result = _frequency_result(member_id)
    member = next(item for item in ensemble.members if item["member_id"] == member_id)
    predecessor_id = ensemble.conformer_ensemble_id
    predecessor_sha = ensemble.payload_sha256
    return {
        "predecessor_lineage": {
            "conformer_ensemble_id": predecessor_id,
            "conformer_ensemble_payload_sha256": predecessor_sha,
            "member_source": {
                "conformer_ensemble_id": predecessor_id,
                "conformer_ensemble_payload_sha256": predecessor_sha,
                "sampling_profile_id": ensemble.sampling_profile_id,
                "sampling_profile_payload_sha256": ensemble.sampling_profile_payload_sha256,
                "member_id": member_id,
                "member_payload_sha256": _conformer_payload_sha256(member),
                "canonical_atom_order_sha256": _conformer_payload_sha256(
                    ensemble.species_binding["atom_order"]
                ),
                "source_atom_map_sha256": _conformer_payload_sha256(
                    ensemble.species_binding["atom_mapping"]
                ),
                "source_geometry_sha256": _conformer_payload_sha256(member["coordinates_angstrom"]),
                "species_binding_sha256": _conformer_payload_sha256(
                    ensemble.species_binding
                ),
                "stereochemistry_binding_sha256": _conformer_payload_sha256(
                    ensemble.stereochemistry_binding
                ),
            },
        },
        "source_result_id": frequency_result["result_id"],
        "source_result_payload_sha256": frequency_result["result_payload_sha256"],
        "source_artifact": frequency_result["source_artifact"],
        "job_section": frequency_result["job_section"],
        "gaussian_thermo_facts": {
            "molecular_mass_amu": 44.01,
            "rotational_symmetry_number": 1,
            "rotational_symmetry_observation_count": 1,
            "rotational_temperatures_kelvin": (1.0, 2.0, 3.0),
            "point_group_diagnostic": "C1",
        },
    }


def _rrho(gibbs: float, temperature: float, *, treated: bool) -> dict[str, object]:
    entropy = 0.0001 if treated else 0.00012
    values: dict[str, object] = {
        "enthalpy_hartree": gibbs + temperature * entropy,
        "entropy_hartree_per_kelvin": entropy,
        "gibbs_free_energy_hartree": gibbs,
    }
    if treated:
        values.update(
            entropy_treatment="grimme",
            enthalpy_treatment="head_gordon",
        )
    else:
        values.update(
            electronic_energy_hartree=gibbs - 0.05,
            zero_point_energy_hartree=0.04,
        )
    return values


def _thermodynamic(
    ensemble: ConformerEnsemble,
    *,
    predecessor: ConformerEnsemble,
    temperature_k: float = 298.15,
    policy_name: str = "explicit-policy-a",
    standard_state: str = "1M",
) -> ThermodynamicEnsemble:
    gas_constant_hartree = 3.166811563e-6
    reference_gibbs = -100.0
    treated_gibbs = (
        reference_gibbs,
        reference_gibbs + gas_constant_hartree * temperature_k * math.log(3.0),
    )
    log_weights = tuple(
        -(gibbs - reference_gibbs) / (gas_constant_hartree * temperature_k)
        for gibbs in treated_gibbs
    )
    log_scale = max(log_weights)
    scaled_partition = math.fsum(math.exp(value - log_scale) for value in log_weights)
    log_partition = log_scale + math.log(scaled_partition)
    populations = tuple(math.exp(value - log_partition) for value in log_weights)
    policy = {
        "name": policy_name,
        "temperature_k": temperature_k,
        "standard_state": standard_state,
    }
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
            "source_provenance": _source_provenance(member_id, predecessor),
            "temperature_k": temperature_k,
            "standard_state": standard_state,
            "raw_rrho": _rrho(gibbs - 0.001, temperature_k, treated=False),
            "treated_qrrho": _rrho(gibbs, temperature_k, treated=True),
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
    if standard_state == "1atm":
        standard_state_binding = {
            "kind": "1atm",
            "pressure_kpa": 101.325,
            "temperature_k": temperature_k,
            "conversion": "ideal_gas_c_equals_p_over_rt",
            "concentration_mol_per_l": 101.325 / (8.31446261815324 * temperature_k),
        }
    else:
        standard_state_binding = {
            "kind": "1M",
            "temperature_k": temperature_k,
            "conversion": "exact_molar_concentration",
            "concentration_mol_per_l": 1.0,
        }
    return ThermodynamicEnsemble._create(
        conformer_ensemble_id=ensemble.conformer_ensemble_id,
        conformer_ensemble_payload_sha256=ensemble.payload_sha256,
        conformer_ensemble_revision=ensemble.revision,
        source_member_ids=ensemble.thermodynamic_eligible_members,
        temperature_k=temperature_k,
        standard_state=standard_state,
        standard_state_binding=standard_state_binding,
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
            "log_scale": log_scale,
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


def _replace_observation(
    source: ThermodynamicEnsemble,
    member_id: str,
    transform: object,
) -> ThermodynamicEnsemble:
    assert callable(transform)
    observations = tuple(
        transform(dict(item)) if item["member_id"] == member_id else item
        for item in source.member_observations
    )
    return _clone_thermodynamic(source, member_observations=observations)


def _replace_provenance(
    source: ThermodynamicEnsemble,
    member_id: str,
    transform: object,
) -> ThermodynamicEnsemble:
    assert callable(transform)

    def replace(item: dict[str, object]) -> dict[str, object]:
        return {
            **item,
            "source_provenance": transform(dict(item["source_provenance"])),
        }

    return _replace_observation(source, member_id, replace)


def _replace_policy(
    source: ThermodynamicEnsemble,
    policy: dict[str, object],
) -> ThermodynamicEnsemble:
    policy_id, policy_sha = _identified_payload("thermochemistry-policy", policy)
    return _clone_thermodynamic(
        source,
        thermochemistry_policy=policy,
        thermochemistry_policy_id=policy_id,
        thermochemistry_policy_payload_sha256=policy_sha,
    )


class FinalEnsembleIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = _profile()
        self.predecessor = _predecessor(self.profile)
        self.refined = _conformer(self.profile, predecessor=self.predecessor)
        self.thermodynamic = _thermodynamic(self.refined, predecessor=self.predecessor)

    def assert_rejected(self, ensemble: ConformerEnsemble, thermo: ThermodynamicEnsemble) -> None:
        with self.assertRaises(_FinalIntegrationError):
            _validate_final_ensemble_integration(ensemble, thermo, predecessor_ensemble=self.predecessor)

    def assert_conformer_identity(self, ensemble: ConformerEnsemble) -> None:
        identity, payload = _conformer_identified_payload(
            "conformer-ensemble", ensemble._identity_payload()
        )
        self.assertEqual((ensemble.conformer_ensemble_id, ensemble.payload_sha256), (identity, payload))

    def test_predecessor_is_required_keyword_only_authority(self) -> None:
        with self.assertRaises(TypeError):
            _validate_final_ensemble_integration(self.refined, self.thermodynamic)
        with self.assertRaises(TypeError):
            _validate_final_ensemble_integration(self.refined, self.thermodynamic, self.predecessor)
        with self.assertRaises(_FinalIntegrationError):
            _validate_final_ensemble_integration(
                self.refined, self.thermodynamic, predecessor_ensemble=None
            )

    def test_A_B_C_E_F_reidentified_refined_inheritance_attacks_reject(self) -> None:
        attacks = {
            "A_foreign_plan": {"calculation_plan_id": "foreign-refined-plan"},
            "B_foreign_plan_revision": {"calculation_plan_revision": 4},
            "C_foreign_project": {"project_id": "foreign-project"},
            "E_non_immediate_revision": {"revision": 3},
            "F_wrong_supersedes": {"supersedes_conformer_ensemble_id": "another-predecessor"},
        }
        for case, updates in attacks.items():
            with self.subTest(case=case):
                forged = _clone_conformer(self.refined, self.profile, **updates)
                self.assert_conformer_identity(forged)
                thermo = _rebind_thermodynamic(self.thermodynamic, forged)
                self.assertNotEqual(thermo.payload_sha256, self.thermodynamic.payload_sha256)
                self.assert_rejected(forged, thermo)

    def test_all_seven_inherited_domains_are_individually_closed(self) -> None:
        attacks = {
            "project_id": "foreign-project", "calculation_plan_id": "foreign-plan",
            "calculation_plan_revision": 4, "sampling_profile_id": "foreign-profile",
            "sampling_profile_payload_sha256": "8" * 64,
            "species_binding": {**self.refined.species_binding, "species_id": "foreign"},
            "stereochemistry_binding": {"stereochemistry_id": "foreign"},
        }
        for name, value in attacks.items():
            with self.subTest(field=name):
                forged = _clone_conformer(self.refined, self.profile)
                object.__setattr__(forged, name, value)
                identity, payload = _conformer_identified_payload(
                    "conformer-ensemble", forged._identity_payload()
                )
                object.__setattr__(forged, "conformer_ensemble_id", identity)
                object.__setattr__(forged, "payload_sha256", payload)
                self.assert_conformer_identity(forged)
                with self.assertRaisesRegex(_FinalIntegrationError, "inherited " + name):
                    _validate_final_ensemble_integration(
                        forged, _rebind_thermodynamic(self.thermodynamic, forged),
                        predecessor_ensemble=self.predecessor,
                    )

    def test_D_wrong_and_L_stale_predecessor_reject(self) -> None:
        wrong = _clone_conformer(self.predecessor, self.profile, calculation_plan_id="other-plan")
        self.assert_conformer_identity(wrong)
        with self.assertRaisesRegex(_FinalIntegrationError, "immediate predecessor"):
            _validate_final_ensemble_integration(
                self.refined, self.thermodynamic, predecessor_ensemble=wrong
            )
        for field, value in (
            ("conformer_ensemble_id", "other-predecessor"),
            ("payload_sha256", "8" * 64),
            ("calculation_plan_id", "tampered-plan"),
        ):
            with self.subTest(field=field):
                stale = _clone_conformer(self.predecessor, self.profile)
                object.__setattr__(stale, field, value)
                with self.assertRaisesRegex(_FinalIntegrationError, "predecessor.*identity is stale"):
                    _validate_final_ensemble_integration(
                        self.refined, self.thermodynamic, predecessor_ensemble=stale
                    )

    def test_G_H_I_J_K_reidentified_predecessor_provenance_attacks_reject(self) -> None:
        original = self.thermodynamic.member_observations[0]["source_provenance"]["predecessor_lineage"]
        other = self.thermodynamic.member_observations[1]["source_provenance"]["predecessor_lineage"]["member_source"]
        attacks = {
            "G_other_id": {"conformer_ensemble_id": "another-predecessor", "member_source": {
                **original["member_source"], "conformer_ensemble_id": "another-predecessor"}},
            "H_other_hash": {"conformer_ensemble_payload_sha256": "8" * 64, "member_source": {
                **original["member_source"], "conformer_ensemble_payload_sha256": "8" * 64}},
            "I_other_member": {"member_source": other},
            "J_member_payload": {"member_source": {
                **original["member_source"], "member_payload_sha256": other["member_payload_sha256"]}},
            "K_refined_geometry": {"member_source": {
                **original["member_source"], "source_geometry_sha256": self.refined.members[0]["coordinates_sha256"]}},
        }
        for case, updates in attacks.items():
            with self.subTest(case=case):
                forged = _replace_provenance(self.thermodynamic, "member-a", lambda provenance: {
                    **provenance, "predecessor_lineage": {**original, **updates},
                })
                identity, payload = _identified_payload("thermodynamic-ensemble", forged._identity_payload())
                self.assertEqual((forged.thermodynamic_ensemble_id, forged.payload_sha256), (identity, payload))
                self.assert_rejected(self.refined, forged)

    def test_predecessor_member_must_resolve_exactly_once(self) -> None:
        for members in (self.predecessor.members[1:], (*self.predecessor.members, self.predecessor.members[0])):
            with self.subTest(count=len(members)):
                predecessor = _clone_conformer(self.predecessor, self.profile, members=members)
                refined = _clone_conformer(self.refined, self.profile,
                    supersedes_conformer_ensemble_id=predecessor.conformer_ensemble_id)
                thermo = _rebind_thermodynamic(self.thermodynamic, refined)
                observations = []
                for item in thermo.member_observations:
                    provenance = item["source_provenance"]
                    lineage = provenance["predecessor_lineage"]
                    observations.append({**item, "source_provenance": {**provenance,
                        "predecessor_lineage": {**lineage,
                            "conformer_ensemble_id": predecessor.conformer_ensemble_id,
                            "conformer_ensemble_payload_sha256": predecessor.payload_sha256}}})
                thermo = _clone_thermodynamic(thermo, member_observations=tuple(observations))
                with self.assertRaisesRegex(_FinalIntegrationError, "resolve exactly once.*predecessor"):
                    _validate_final_ensemble_integration(refined, thermo, predecessor_ensemble=predecessor)

    def test_same_foreign_plan_record_rejects_at_normal_builder_and_final_integration(self) -> None:
        from tests.v31.thermochemistry import test_core as thermo_tests

        fixture = thermo_tests.ThermochemistryCoreTests()
        fixture.setUp()
        thermo = fixture.build()
        _validate_final_ensemble_integration(
            fixture.refined, thermo, predecessor_ensemble=fixture.prior
        )
        for updates in ({"calculation_plan_id": "foreign-refined-plan"}, {"calculation_plan_revision": 99}):
            with self.subTest(updates=updates):
                forged = _clone_conformer(fixture.refined, fixture.profile, **updates)
                self.assert_conformer_identity(forged)
                rebound = _rebind_thermodynamic(thermo, forged)
                with self.assertRaisesRegex(thermo_tests.ThermochemistryError, "inherited domain bindings"):
                    fixture.build(ensemble=forged)
                with self.assertRaisesRegex(_FinalIntegrationError, "inherited calculation_plan"):
                    _validate_final_ensemble_integration(forged, rebound, predecessor_ensemble=fixture.prior)

    def test_exact_trio_preserves_independent_projections_and_authoritative_records(self) -> None:
        result = _validate_final_ensemble_integration(self.refined, self.thermodynamic, predecessor_ensemble=self.predecessor)

        self.assertIs(result[0], self.refined)
        self.assertIs(result[1], self.thermodynamic)
        self.assertEqual(result[2], ("member-b", "member-c"))
        self.assertEqual(result[1].source_member_ids, ("member-a", "member-b"))
        self.assertEqual(result[0].negative_evidence, self.refined.negative_evidence)
        self.assertAlmostEqual(result[1].member_observations[0]["normalized_population"], 0.75)
        self.assertAlmostEqual(result[1].member_observations[1]["normalized_population"], 0.25)

    def test_exact_trio_binds_all_four_frequency_provenance_fields(self) -> None:
        for observation in self.thermodynamic.member_observations:
            member = next(
                member for member in self.refined.members
                if member["member_id"] == observation["member_id"]
            )
            frequency_result = member["two_stage_minimum_authority"]["frequency"]["result"]
            provenance = observation["source_provenance"]
            for source_key, result_key in (
                ("source_result_id", "result_id"),
                ("source_result_payload_sha256", "result_payload_sha256"),
                ("source_artifact", "source_artifact"),
                ("job_section", "job_section"),
            ):
                with self.subTest(member=member["member_id"], field=source_key):
                    self.assertEqual(provenance[source_key], frequency_result[result_key])
        result = _validate_final_ensemble_integration(self.refined, self.thermodynamic, predecessor_ensemble=self.predecessor)
        self.assertIs(result[1], self.thermodynamic)

    def test_self_identified_frequency_provenance_splices_reject(self) -> None:
        first, second = self.thermodynamic.member_observations
        source = first["source_provenance"]
        other = second["source_provenance"]
        fields = ("source_result_id", "source_result_payload_sha256",
                  "source_artifact", "job_section")
        for field in fields:
            self.assertNotEqual(source[field], other[field])
        attacks = {
            "A_other_real_result_id": {fields[0]: other[fields[0]]},
            "B_other_real_result_hash": {fields[1]: other[fields[1]]},
            "C_other_id_and_hash": {key: other[key] for key in fields[:2]},
            "D_other_artifact_and_section": {key: other[key] for key in fields[2:]},
            "E_other_complete_tuple": {key: other[key] for key in fields},
            "F_same_artifact_different_valid_span": {
                "job_section": {**source["job_section"], "start": 20, "end": 800},
            },
            "G_valid_format_false_hash": {"source_result_payload_sha256": "0" * 64},
        }
        for label, updates in attacks.items():
            with self.subTest(attack=label):
                forged = _replace_provenance(
                    self.thermodynamic, "member-a",
                    lambda provenance: {**provenance, **updates},
                )
                identity, payload = _identified_payload(
                    "thermodynamic-ensemble", forged._identity_payload()
                )
                self.assertEqual(forged.thermodynamic_ensemble_id, identity)
                self.assertEqual(forged.payload_sha256, payload)
                self.assertNotEqual(forged.payload_sha256, self.thermodynamic.payload_sha256)
                with self.assertRaisesRegex(_FinalIntegrationError, "differs from.*Freq Result"):
                    _validate_final_ensemble_integration(self.refined, forged, predecessor_ensemble=self.predecessor)

    def test_missing_and_malformed_frequency_provenance_reject(self) -> None:
        for field, malformed in (
            ("source_result_id", " "),
            ("source_result_payload_sha256", "bad-hash"),
            ("source_artifact", {}),
            ("job_section", {}),
        ):
            for missing in (False, True):
                with self.subTest(field=field, missing=missing):
                    def alter(provenance: dict[str, object]) -> dict[str, object]:
                        if missing:
                            provenance.pop(field)
                        else:
                            provenance[field] = malformed
                        return provenance

                    forged = _replace_provenance(self.thermodynamic, "member-a", alter)
                    identity, payload = _identified_payload(
                        "thermodynamic-ensemble", forged._identity_payload()
                    )
                    self.assertEqual(forged.thermodynamic_ensemble_id, identity)
                    self.assertEqual(forged.payload_sha256, payload)
                    self.assert_rejected(self.refined, forged)

    def test_refined_minimum_requires_existing_exact_frequency_result_shape(self) -> None:
        first, *rest = self.refined.members
        minimum = first["two_stage_minimum_authority"]
        result = minimum["frequency"]["result"]
        malformed = [None, {}, {**result, "extra": "forbidden"}]
        malformed.extend({key: value for key, value in result.items() if key != missing}
                         for missing in result)
        frequencies = [None, {}, {"result": None}]
        frequencies.extend({"result": value} for value in malformed)
        for frequency in frequencies:
            with self.subTest(frequency=frequency):
                refined = _clone_conformer(
                    self.refined, self.profile,
                    members=({**first, "two_stage_minimum_authority": {
                        **minimum, "frequency": frequency,
                    }}, *rest),
                )
                thermo = _rebind_thermodynamic(self.thermodynamic, refined)
                self.assert_rejected(refined, thermo)

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
        thermo = _thermodynamic(refined, predecessor=self.predecessor)
        object.__setattr__(refined, "conformer_ensemble_id", "conformer-ensemble-" + "0" * 64)
        self.assert_rejected(refined, thermo)

        refined = _conformer(self.profile)
        thermo = _thermodynamic(refined, predecessor=self.predecessor)
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

        result = _validate_final_ensemble_integration(self.refined, self.thermodynamic, predecessor_ensemble=self.predecessor)
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
        self.assert_rejected(
            self.refined,
            _clone_thermodynamic(
                self.thermodynamic,
                population_normalization={
                    **self.thermodynamic.population_normalization,
                    "numeric_tolerance": 1.0e-6,
                },
            ),
        )

    def test_log_weight_must_follow_treated_gibbs_and_degeneracy(self) -> None:
        altered_weight = _replace_observation(
            self.thermodynamic,
            "member-b",
            lambda item: {
                **item,
                "relative_statistical_weight": {
                    **item["relative_statistical_weight"],
                    "log_value": item["relative_statistical_weight"]["log_value"] + 0.1,
                },
            },
        )
        self.assert_rejected(self.refined, altered_weight)

        altered_degeneracy = _replace_observation(
            self.thermodynamic,
            "member-b",
            lambda item: {**item, "degeneracy": 2},
        )
        self.assert_rejected(self.refined, altered_degeneracy)

        def alter_treated_gibbs(item: dict[str, object]) -> dict[str, object]:
            treated = dict(item["treated_qrrho"])
            treated["enthalpy_hartree"] += 1.0
            treated["gibbs_free_energy_hartree"] += 1.0
            return {**item, "treated_qrrho": treated}

        altered_gibbs = _replace_observation(
            self.thermodynamic,
            "member-b",
            alter_treated_gibbs,
        )
        self.assert_rejected(self.refined, altered_gibbs)

    def test_normalized_but_formula_inconsistent_populations_reject(self) -> None:
        first, second = self.thermodynamic.member_observations
        forged = (
            {**first, "normalized_population": 0.25},
            {**second, "normalized_population": 0.75},
        )
        self.assert_rejected(
            self.refined,
            _clone_thermodynamic(self.thermodynamic, member_observations=forged),
        )

    def test_reference_partition_and_ensemble_free_energy_are_formula_closed(self) -> None:
        second_gibbs = self.thermodynamic.member_observations[1]["treated_qrrho"][
            "gibbs_free_energy_hartree"
        ]
        for partition in (
            {
                **self.thermodynamic.partition_evidence,
                "reference_member_id": "member-b",
                "reference_gibbs_hartree": second_gibbs,
            },
            {
                **self.thermodynamic.partition_evidence,
                "reference_gibbs_hartree": (
                    self.thermodynamic.partition_evidence["reference_gibbs_hartree"] + 0.01
                ),
            },
            {
                **self.thermodynamic.partition_evidence,
                "log_relative_partition_function": (
                    self.thermodynamic.partition_evidence["log_relative_partition_function"] + 0.01
                ),
            },
        ):
            with self.subTest(partition=partition):
                self.assert_rejected(
                    self.refined,
                    _clone_thermodynamic(self.thermodynamic, partition_evidence=partition),
                )
        self.assert_rejected(
            self.refined,
            _clone_thermodynamic(
                self.thermodynamic,
                ensemble_treated_free_energy_hartree=(
                    self.thermodynamic.ensemble_treated_free_energy_hartree + 0.01
                ),
            ),
        )

    def test_member_thermochemistry_evidence_must_have_exact_nonempty_shapes(self) -> None:
        def replace_nested(name: str, value: object) -> ThermodynamicEnsemble:
            return _replace_observation(
                self.thermodynamic,
                "member-a",
                lambda item: {**item, name: value},
            )

        for name in ("source_provenance", "raw_rrho", "treated_qrrho"):
            with self.subTest(name=name):
                self.assert_rejected(self.refined, replace_nested(name, {}))

        provenance = self.thermodynamic.member_observations[0]["source_provenance"]
        for name in (
            "predecessor_lineage",
            "source_artifact",
            "job_section",
            "gaussian_thermo_facts",
        ):
            with self.subTest(name=name):
                self.assert_rejected(
                    self.refined,
                    replace_nested("source_provenance", {**provenance, name: {}}),
                )
        self.assert_rejected(
            self.refined,
            replace_nested(
                "source_provenance",
                {
                    **provenance,
                    "predecessor_lineage": {
                        **provenance["predecessor_lineage"],
                        "member_source": {},
                    },
                },
            ),
        )

    def test_rrho_missing_nonfinite_and_h_minus_ts_inconsistency_reject(self) -> None:
        raw = dict(self.thermodynamic.member_observations[0]["raw_rrho"])
        raw.pop("zero_point_energy_hartree")
        missing = _replace_observation(
            self.thermodynamic,
            "member-a",
            lambda item: {**item, "raw_rrho": raw},
        )
        self.assert_rejected(self.refined, missing)

        raw = dict(self.thermodynamic.member_observations[0]["raw_rrho"])
        raw["gibbs_free_energy_hartree"] += 0.01
        inconsistent_raw = _replace_observation(
            self.thermodynamic,
            "member-a",
            lambda item: {**item, "raw_rrho": raw},
        )
        self.assert_rejected(self.refined, inconsistent_raw)

        treated = dict(self.thermodynamic.member_observations[0]["treated_qrrho"])
        treated["gibbs_free_energy_hartree"] += 0.01
        inconsistent_treated = _replace_observation(
            self.thermodynamic,
            "member-a",
            lambda item: {**item, "treated_qrrho": treated},
        )
        self.assert_rejected(self.refined, inconsistent_treated)

        for nonfinite in (math.nan, math.inf):
            with self.subTest(nonfinite=nonfinite):
                forged = _clone_thermodynamic(self.thermodynamic)
                first, second = forged.member_observations
                object.__setattr__(
                    forged,
                    "member_observations",
                    (
                        {
                            **first,
                            "raw_rrho": {
                                **first["raw_rrho"],
                                "enthalpy_hartree": nonfinite,
                            },
                        },
                        second,
                    ),
                )
                with self.assertRaises(ValueError):
                    _validate_final_ensemble_integration(self.refined, forged, predecessor_ensemble=self.predecessor)

    def test_combined_self_identified_forgery_still_rejects(self) -> None:
        first, second = self.thermodynamic.member_observations
        treated = dict(second["treated_qrrho"])
        treated["enthalpy_hartree"] += 0.5
        treated["gibbs_free_energy_hartree"] += 0.5
        forged = _clone_thermodynamic(
            self.thermodynamic,
            member_observations=(
                first,
                {
                    **second,
                    "treated_qrrho": treated,
                    "degeneracy": 4,
                    "relative_statistical_weight": {
                        **second["relative_statistical_weight"],
                        "log_value": second["relative_statistical_weight"]["log_value"] + 0.2,
                    },
                    "source_provenance": {},
                    "raw_rrho": {},
                },
            ),
        )
        identity, payload = _identified_payload(
            "thermodynamic-ensemble",
            forged._identity_payload(),
        )
        self.assertEqual(forged.thermodynamic_ensemble_id, identity)
        self.assertEqual(forged.payload_sha256, payload)
        self.assert_rejected(self.refined, forged)

    def test_import_is_record_only_and_does_not_load_scientific_pipeline(self) -> None:
        root = Path(__file__).resolve().parents[3]
        forbidden = (
            "auto_g16.thermochemistry._service",
            "auto_g16.thermochemistry._goodvibes",
            "auto_g16.thermochemistry._gaussian_thermo_facts",
            "auto_g16.result",
            "auto_g16.conformer.refinement",
            "auto_g16.conformer.refinement_authority",
        )
        program = """
import importlib.abc
import sys

root = sys.argv[1]
forbidden = set(sys.argv[2:])

class Blocked(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in forbidden:
            raise RuntimeError(f"forbidden import: {fullname}")
        return None

sys.meta_path.insert(0, Blocked())
sys.path.insert(0, root)
import auto_g16.conformer.final_integration
loaded = sorted(forbidden.intersection(sys.modules))
if loaded:
    raise SystemExit("loaded forbidden modules: " + ",".join(loaded))
"""
        result = subprocess.run(
            [sys.executable, "-I", "-c", program, str(root), *forbidden],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_member_minimum_and_predecessor_are_cross_record_bound(self) -> None:
        wrong_minimum = _replace_observation(
            self.thermodynamic,
            "member-a",
            lambda item: {
                **item,
                "two_stage_minimum_authority_id": "minimum-member-b",
            },
        )
        self.assert_rejected(self.refined, wrong_minimum)

        def replace_predecessor(
            provenance: dict[str, object],
            *,
            outer_id: str | None = None,
            outer_sha: str | None = None,
            member_updates: dict[str, object] | None = None,
        ) -> dict[str, object]:
            predecessor = dict(provenance["predecessor_lineage"])
            member_source = dict(predecessor["member_source"])
            if outer_id is not None:
                predecessor["conformer_ensemble_id"] = outer_id
            if outer_sha is not None:
                predecessor["conformer_ensemble_payload_sha256"] = outer_sha
            member_source.update(member_updates or {})
            predecessor["member_source"] = member_source
            return {**provenance, "predecessor_lineage": predecessor}

        internally_consistent_other_predecessor = _replace_provenance(
            self.thermodynamic,
            "member-a",
            lambda provenance: replace_predecessor(
                provenance,
                outer_id="another-predecessor",
                member_updates={"conformer_ensemble_id": "another-predecessor"},
            ),
        )
        self.assert_rejected(self.refined, internally_consistent_other_predecessor)

        nested_id_splice = _replace_provenance(
            self.thermodynamic,
            "member-a",
            lambda provenance: replace_predecessor(
                provenance,
                member_updates={"conformer_ensemble_id": "nested-predecessor"},
            ),
        )
        self.assert_rejected(self.refined, nested_id_splice)

        nested_sha_splice = _replace_provenance(
            self.thermodynamic,
            "member-a",
            lambda provenance: replace_predecessor(
                provenance,
                member_updates={"conformer_ensemble_payload_sha256": "8" * 64},
            ),
        )
        self.assert_rejected(self.refined, nested_sha_splice)

    def test_profile_species_stereo_and_member_source_cross_bindings_reject_splices(self) -> None:
        def replace_member_source(
            provenance: dict[str, object],
            **updates: object,
        ) -> dict[str, object]:
            predecessor = dict(provenance["predecessor_lineage"])
            predecessor["member_source"] = {
                **predecessor["member_source"],
                **updates,
            }
            return {**provenance, "predecessor_lineage": predecessor}

        attacks = (
            {"sampling_profile_id": "sampling-profile-splice"},
            {"sampling_profile_payload_sha256": "8" * 64},
            {"species_binding_sha256": "8" * 64},
            {"stereochemistry_binding_sha256": "8" * 64},
            {"canonical_atom_order_sha256": "8" * 64},
            {"source_atom_map_sha256": "8" * 64},
            {"member_id": "member-b"},
        )
        for attack in attacks:
            with self.subTest(attack=attack):
                forged = _replace_provenance(
                    self.thermodynamic,
                    "member-a",
                    lambda provenance, attack=attack: replace_member_source(
                        provenance,
                        **attack,
                    ),
                )
                self.assert_rejected(self.refined, forged)

    def test_historical_predecessor_geometry_is_not_compared_to_refined_geometry(self) -> None:
        source = self.thermodynamic.member_observations[0]["source_provenance"][
            "predecessor_lineage"
        ]["member_source"]
        refined_member = self.refined.members[0]
        self.assertNotEqual(
            source["source_geometry_sha256"],
            refined_member["coordinates_sha256"],
        )
        result = _validate_final_ensemble_integration(self.refined, self.thermodynamic, predecessor_ensemble=self.predecessor)
        self.assertIs(result[0], self.refined)

    def test_gas_constant_representations_must_agree(self) -> None:
        for replacement in (
            {
                **self.thermodynamic.gas_constant_binding,
                "gas_constant_hartree_per_mol_k": 0.001,
            },
            {
                **self.thermodynamic.gas_constant_binding,
                "joule_per_hartree_mol": 456.0,
            },
        ):
            with self.subTest(replacement=replacement):
                self.assert_rejected(
                    self.refined,
                    _clone_thermodynamic(
                        self.thermodynamic,
                        gas_constant_binding=replacement,
                    ),
                )

    def test_policy_identity_and_top_level_conditions_are_closed(self) -> None:
        policy = dict(self.thermodynamic.thermochemistry_policy)
        for changed in (
            {**policy, "temperature_k": 777.0},
            {**policy, "standard_state": "1atm"},
        ):
            with self.subTest(changed=changed):
                self.assert_rejected(
                    self.refined,
                    _replace_policy(self.thermodynamic, changed),
                )

        other_policy = {**policy, "name": "another-policy"}
        other_id, other_sha = _identified_payload("thermochemistry-policy", other_policy)
        self.assert_rejected(
            self.refined,
            _clone_thermodynamic(
                self.thermodynamic,
                thermochemistry_policy_id=other_id,
                thermochemistry_policy_payload_sha256=other_sha,
            ),
        )

    def test_one_atmosphere_standard_state_binding_is_formula_closed(self) -> None:
        one_atmosphere = _thermodynamic(self.refined, predecessor=self.predecessor, standard_state="1atm")
        result = _validate_final_ensemble_integration(self.refined, one_atmosphere, predecessor_ensemble=self.predecessor)
        self.assertIs(result[1], one_atmosphere)
        binding = one_atmosphere.standard_state_binding
        attacks = (
            {**binding, "temperature_k": 310.0},
            {**binding, "pressure_kpa": 100.0},
            {**binding, "concentration_mol_per_l": 0.5},
            {**binding, "conversion": "forged-conversion"},
            {
                "kind": "1M",
                "temperature_k": one_atmosphere.temperature_k,
                "conversion": "exact_molar_concentration",
                "concentration_mol_per_l": 1.0,
            },
        )
        for attack in attacks:
            with self.subTest(attack=attack):
                self.assert_rejected(
                    self.refined,
                    _clone_thermodynamic(
                        one_atmosphere,
                        standard_state_binding=attack,
                    ),
                )

    def test_one_molar_standard_state_binding_is_closed(self) -> None:
        binding = self.thermodynamic.standard_state_binding
        for attack in (
            {**binding, "concentration_mol_per_l": 0.99},
            {**binding, "temperature_k": 310.0},
        ):
            with self.subTest(attack=attack):
                self.assert_rejected(
                    self.refined,
                    _clone_thermodynamic(
                        self.thermodynamic,
                        standard_state_binding=attack,
                    ),
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

        result = _validate_final_ensemble_integration(refined, thermo, predecessor_ensemble=self.predecessor)

        self.assertIs(result[0], refined)
        self.assertEqual(result[0].coverage["status"], "insufficient")
        self.assertIs(result[0].coverage["fragment_association_semantics_complete"], False)

    def test_explicit_alternative_temperature_and_policy_remain_valid(self) -> None:
        alternative = _thermodynamic(
            self.refined, predecessor=self.predecessor,
            temperature_k=310.0,
            policy_name="explicit-policy-b",
        )

        result = _validate_final_ensemble_integration(self.refined, alternative, predecessor_ensemble=self.predecessor)

        self.assertIs(result[1], alternative)
        self.assertEqual(result[1].temperature_k, 310.0)
        self.assertEqual(result[1].thermochemistry_policy["name"], "explicit-policy-b")

    def test_same_exact_inputs_produce_the_same_private_view(self) -> None:
        first = _validate_final_ensemble_integration(self.refined, self.thermodynamic, predecessor_ensemble=self.predecessor)
        second = _validate_final_ensemble_integration(self.refined, self.thermodynamic, predecessor_ensemble=self.predecessor)
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
