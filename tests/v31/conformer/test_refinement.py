"""Offline adversarial tests for post-DFT ConformerEnsemble refinement."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from hashlib import sha256
from pathlib import Path
import unittest

import auto_g16.conformer as conformer
from auto_g16.conformer.models import ConformerEnsemble
from auto_g16.conformer.refinement import RefinementError, build_refined_conformer_ensemble
from auto_g16.conformer.refinement_authority import (
    RefinementAuthorityError,
    _validate_current_optimization_geometry_authority,
    _validate_current_two_stage_minimum_authority,
    build_dft_stage,
    validate_negative_frequency_authority,
    validate_negative_optimization_authority,
)
from auto_g16.conformer.service import create_sampling_profile
from auto_g16.result import OutputArtifact, OutputEnvelope, ResultProvenanceService
from tests.v31.conformer import test_refinement_authority as z0_fixtures
from tests.v31.conformer.test_core import ConformerCoreTests


class RefinementTests(unittest.TestCase):
    def setUp(self) -> None:
        self.core_fixture = ConformerCoreTests()
        self.profile = self.core_fixture.profile()
        self.source_coordinates = {
            "member-a": (
                (0.0, 0.0, 0.0),
                (1.5, 0.0, 0.0),
                (2.5, 1.0, 0.0),
                (3.5, 1.0, 0.0),
            ),
            "member-b": (
                (0.0, 0.0, 0.0),
                (1.5, 0.0, 0.0),
                (2.5, 1.7, 0.0),
                (3.5, 1.0, 0.0),
            ),
        }
        observations = [
            self.core_fixture.observation(
                self.profile,
                member_id,
                member_index=index,
                coordinates=[list(point) for point in self.source_coordinates[member_id]],
                relevance_tags=["ts_seed"] if member_id == "member-a" else [],
            )
            for index, member_id in enumerate(("member-a", "member-b"))
        ]
        self.prior = self.core_fixture.ensemble(self.profile, observations)
        self.z0 = z0_fixtures.RefinementAuthorityTests(
            "test_01_deterministic_closed_two_stage_authority"
        )
        self.z0.setUp()
        self.pipelines = self._pipelines(self.source_coordinates)

    def tearDown(self) -> None:
        self.z0.tearDown()

    @staticmethod
    def _opt_input(member_id, plan, prepared, prepared_bytes, chain):
        return {
            "member_id": member_id,
            "calculation_plan": plan,
            "prepared_input_binding": prepared,
            "prepared_input_bytes": prepared_bytes,
            **z0_fixtures.RefinementAuthorityTests.persisted_args(chain),
        }

    @staticmethod
    def _freq_input(member_id, opt_input, freq_plan, freq_prepared, freq_bytes, freq_chain):
        opt_names = {
            "calculation_plan": "optimization_plan",
            "prepared_input_binding": "optimization_prepared_input_binding",
            "prepared_input_bytes": "optimization_prepared_input_bytes",
            "core_store": "optimization_core_store",
            "validation_store": "optimization_validation_store",
            "input_binding": "optimization_input_binding",
            "output_envelope": "optimization_output_envelope",
            "parse_outcome": "optimization_parse_outcome",
            "minimum_validation_outcome_id": "optimization_minimum_validation_outcome_id",
        }
        return {
            "member_id": member_id,
            **{
                opt_names[key]: value
                for key, value in opt_input.items()
                if key != "member_id"
            },
            "frequency_plan": freq_plan,
            "frequency_prepared_input_binding": freq_prepared,
            "frequency_prepared_input_bytes": freq_bytes,
            **{
                "frequency_" + key: value
                for key, value in z0_fixtures.RefinementAuthorityTests.persisted_args(
                    freq_chain
                ).items()
            },
        }

    def _pipelines(self, coordinates_by_member, *, method_by_member=None):
        pipelines = {}
        methods = {} if method_by_member is None else method_by_member
        for member_id in ("member-a", "member-b"):
            suffix = member_id.removeprefix("member-")
            method = methods.get(member_id, self.z0.method)
            coordinates = coordinates_by_member[member_id]
            opt_plan, opt_prepared, opt_bytes = build_dft_stage(
                self.prior,
                member_id,
                stage="opt",
                calculation_plan_id=f"opt-plan-{suffix}-{method['basis']}",
                calculation_plan_revision=1,
                task_id=f"opt-task-{suffix}-{method['basis']}",
                attempt_id=f"opt-attempt-{suffix}-{method['basis']}",
                logical_name=f"opt-{suffix}.gjf",
                method_binding=method,
            )
            opt_chain = self.z0.chain(
                opt_plan,
                opt_prepared,
                opt_bytes,
                frequencies=(),
                optimization_spans=((100, 110),),
                stationary_spans=((120, 130),),
                atom_numbers=(6, 6, 8, 1),
                geometry_coordinates=coordinates,
                ensemble=self.prior,
            )
            opt_input = self._opt_input(
                member_id, opt_plan, opt_prepared, opt_bytes, opt_chain
            )
            optimization = _validate_current_optimization_geometry_authority(
                self.prior,
                member_id,
                **{key: value for key, value in opt_input.items() if key != "member_id"},
            )
            freq_plan, freq_prepared, freq_bytes = build_dft_stage(
                self.prior,
                member_id,
                stage="freq",
                calculation_plan_id=f"freq-plan-{suffix}-{method['basis']}",
                calculation_plan_revision=1,
                task_id=f"freq-task-{suffix}-{method['basis']}",
                attempt_id=f"freq-attempt-{suffix}-{method['basis']}",
                logical_name=f"freq-{suffix}.gjf",
                method_binding=method,
                optimization_geometry_authority=optimization,
            )
            freq_chain = self.z0.chain(
                freq_plan,
                freq_prepared,
                freq_bytes,
                frequencies=(0.0, 50.0, 100.0, 150.0, 200.0, 250.0),
                optimization_spans=(),
                stationary_spans=(),
                atom_numbers=(6, 6, 8, 1),
                geometry_coordinates=coordinates,
                ensemble=self.prior,
            )
            freq_input = self._freq_input(
                member_id, opt_input, freq_plan, freq_prepared, freq_bytes, freq_chain
            )
            minimum = _validate_current_two_stage_minimum_authority(
                self.prior,
                member_id,
                **{key: value for key, value in freq_input.items() if key != "member_id"},
            )
            pipelines[member_id] = {
                "opt_input": opt_input,
                "optimization": optimization,
                "opt_chain": opt_chain,
                "freq_input": freq_input,
                "minimum": minimum,
                "freq_chain": freq_chain,
            }
        return pipelines

    def _negative_opt_input(self, member_id, *, method=None):
        suffix = member_id.removeprefix("member-")
        method_binding = self.z0.method if method is None else method
        plan, prepared, prepared_bytes = build_dft_stage(
            self.prior,
            member_id,
            stage="opt",
            calculation_plan_id=f"negative-opt-plan-{suffix}-{method_binding['basis']}",
            calculation_plan_revision=1,
            task_id=f"negative-opt-task-{suffix}-{method_binding['basis']}",
            attempt_id=f"negative-opt-attempt-{suffix}-{method_binding['basis']}",
            logical_name=f"negative-opt-{suffix}.gjf",
            method_binding=method_binding,
        )
        chain = self.z0.chain(
            plan,
            prepared,
            prepared_bytes,
            frequencies=(),
            optimization_spans=(),
            stationary_spans=(),
            program_status="error-termination",
            atom_numbers=(6, 6, 8, 1),
            ensemble=self.prior,
        )
        value = self._opt_input(member_id, plan, prepared, prepared_bytes, chain)
        authority = validate_negative_optimization_authority(
            self.prior,
            member_id,
            **{key: item for key, item in value.items() if key != "member_id"},
        )
        return value, authority

    def _negative_freq_input(self, member_id):
        pipeline = self.pipelines[member_id]
        suffix = member_id.removeprefix("member-")
        plan, prepared, prepared_bytes = build_dft_stage(
            self.prior,
            member_id,
            stage="freq",
            calculation_plan_id=f"negative-freq-plan-{suffix}",
            calculation_plan_revision=1,
            task_id=f"negative-freq-task-{suffix}",
            attempt_id=f"negative-freq-attempt-{suffix}",
            logical_name=f"negative-freq-{suffix}.gjf",
            method_binding=self.z0.method,
            optimization_geometry_authority=pipeline["optimization"],
        )
        chain = self.z0.chain(
            plan,
            prepared,
            prepared_bytes,
            frequencies=(-1.0, 50.0, 100.0, 150.0, 200.0, 250.0),
            optimization_spans=(),
            stationary_spans=(),
            atom_numbers=(6, 6, 8, 1),
            geometry_coordinates=self.source_coordinates[member_id],
            ensemble=self.prior,
        )
        value = self._freq_input(
            member_id, pipeline["opt_input"], plan, prepared, prepared_bytes, chain
        )
        authority = validate_negative_frequency_authority(
            self.prior,
            member_id,
            **{key: item for key, item in value.items() if key != "member_id"},
        )
        return value, authority

    def _use_multifragment_profile(
        self,
        *,
        associations,
        thermodynamic_statuses=("sufficient", "insufficient"),
        ts_statuses=("sufficient", "insufficient"),
    ):
        species = self.core_fixture.species_binding(multifragment=True)
        base = self.core_fixture.profile(species=species, associations=associations)
        self.profile = create_sampling_profile(
            revision=base.revision,
            supersedes_sampling_profile_id=base.supersedes_sampling_profile_id,
            species_binding=base.species_binding,
            stereochemistry_binding=base.stereochemistry_binding,
            bond_change_policy=base.bond_change_policy,
            geometry_legality_policy=base.geometry_legality_policy,
            crest_imtd_gc_profile=base.crest_imtd_gc_profile,
            rmsd_policy=base.rmsd_policy,
            clustering_policy=base.clustering_policy,
            descriptor_policy=base.descriptor_policy,
            coverage_policy=base.coverage_policy,
            thermodynamic_eligibility_policy={
                "require_post_dft_minimum": True,
                "required_coverage_statuses": list(thermodynamic_statuses),
            },
            ts_seed_projection_policy={
                "require_post_dft_minimum": True,
                "required_coverage_statuses": list(ts_statuses),
                "allowed_relevance_tags": ["ts_seed"],
            },
        )
        observations = [
            self.core_fixture.observation(
                self.profile,
                member_id,
                member_index=index,
                coordinates=[list(point) for point in self.source_coordinates[member_id]],
                relevance_tags=["ts_seed"] if member_id == "member-a" else [],
            )
            for index, member_id in enumerate(("member-a", "member-b"))
        ]
        self.prior = self.core_fixture.ensemble(self.profile, observations)
        self.pipelines = self._pipelines(self.source_coordinates)

    def _replace_prior_coverage(self, coverage):
        self.prior = ConformerEnsemble._create(
            project_id=self.prior.project_id,
            calculation_plan_id=self.prior.calculation_plan_id,
            calculation_plan_revision=self.prior.calculation_plan_revision,
            profile=self.profile,
            sampling_observations=self.prior.sampling_observations,
            audit_evidence=self.prior.audit_evidence,
            negative_evidence=self.prior.negative_evidence,
            dedup_decisions=self.prior.dedup_decisions,
            independent_review_blockers=self.prior.independent_review_blockers,
            clusters=self.prior.clusters,
            members=self.prior.members,
            coverage=coverage,
            thermodynamic_eligible_members=self.prior.thermodynamic_eligible_members,
            ts_seed_members=self.prior.ts_seed_members,
        )
        self.pipelines = self._pipelines(self.source_coordinates)

    def build(
        self,
        *,
        positive_opt=None,
        negative_opt=(),
        positive_freq=None,
        negative_freq=(),
    ):
        selected_opt = (
            tuple(item["opt_input"] for item in self.pipelines.values())
            if positive_opt is None
            else tuple(positive_opt)
        )
        selected_freq = (
            tuple(item["freq_input"] for item in self.pipelines.values())
            if positive_freq is None
            else tuple(positive_freq)
        )
        return build_refined_conformer_ensemble(
            self.prior,
            self.profile,
            positive_optimization_inputs=selected_opt,
            negative_optimization_inputs=tuple(negative_opt),
            positive_frequency_inputs=selected_freq,
            negative_frequency_inputs=tuple(negative_freq),
        )

    @staticmethod
    def _append_complete_capture(stage_input, sequence=2):
        binding = stage_input.get(
            "input_binding", stage_input.get("frequency_input_binding")
        )
        core_store = stage_input.get(
            "core_store", stage_input.get("frequency_core_store")
        )
        envelope = OutputEnvelope(
            attempt_id=binding.attempt_id,
            input_binding_observation_id=binding.observation_id,
            execution_snapshot_id=binding.execution_snapshot_id,
            capture_source_id=f"new-capture-{binding.attempt_id}-{sequence}",
            capture_sequence=sequence,
            capture_status="captured",
            capture_completeness="complete",
            artifacts=(OutputArtifact(
                artifact_kind="gaussian-log",
                logical_name=f"new-{sequence}.log",
                sha256=sha256(f"new-{binding.attempt_id}-{sequence}".encode()).hexdigest(),
                size_bytes=1000,
            ),),
            capture_manifest_sha256=sha256(
                f"manifest-{binding.attempt_id}-{sequence}".encode()
            ).hexdigest(),
            captured_at_utc=f"2026-09-03T00:00:{sequence:02d}Z",
        )
        ResultProvenanceService(core_store).record_output_envelope(envelope)

    def test_revision_is_deterministic_and_supersedes_exact_immutable_prior(self):
        prior_payload = self.prior._identity_payload()
        first = self.build()
        second = self.build(
            positive_opt=reversed(tuple(item["opt_input"] for item in self.pipelines.values())),
            positive_freq=reversed(tuple(item["freq_input"] for item in self.pipelines.values())),
        )
        self.assertEqual(first, second)
        self.assertEqual(first.revision, self.prior.revision + 1)
        self.assertEqual(first.supersedes_conformer_ensemble_id, self.prior.conformer_ensemble_id)
        self.assertEqual(first.sampling_profile_id, self.prior.sampling_profile_id)
        self.assertEqual(first.species_binding, self.prior.species_binding)
        self.assertEqual(first.stereochemistry_binding, self.prior.stereochemistry_binding)
        self.assertEqual(self.prior._identity_payload(), prior_payload)
        with self.assertRaises(FrozenInstanceError):
            self.prior.revision = 2

    def test_opt_disposition_set_requires_exactly_one_current_terminal_per_member(self):
        inputs = [item["opt_input"] for item in self.pipelines.values()]
        with self.assertRaisesRegex(RefinementError, "complete prior member set"):
            self.build(positive_opt=inputs[:1], positive_freq=(self.pipelines["member-a"]["freq_input"],))
        with self.assertRaisesRegex(RefinementError, "duplicate member disposition"):
            self.build(positive_opt=(*inputs, inputs[0]))
        negative, _authority = self._negative_opt_input("member-a")
        with self.assertRaisesRegex(RefinementError, "both positive and negative Opt"):
            self.build(negative_opt=(negative,))
        forged_extra = {**inputs[0], "member_id": "member-extra"}
        with self.assertRaises(RefinementError):
            self.build(positive_opt=(*inputs, forged_extra))

    def test_negative_opt_is_retained_and_never_requires_frequency(self):
        negative_input, negative = self._negative_opt_input("member-b")
        refined = self.build(
            positive_opt=(self.pipelines["member-a"]["opt_input"],),
            negative_opt=(negative_input,),
            positive_freq=(self.pipelines["member-a"]["freq_input"],),
        )
        self.assertEqual(refined.thermodynamic_eligible_members, ("member-a",))
        evidence = next(item for item in refined.negative_evidence if item.get("member_id") == "member-b")
        self.assertEqual(evidence["stage"], "opt")
        self.assertEqual(evidence["negative_refinement_authority_id"], negative["negative_optimization_authority_id"])
        self.assertEqual(evidence["result_id"], negative["result"]["result_id"])
        self.assertEqual(evidence["review_bundle_id"], negative["review"]["review_bundle_id"])

    def test_stale_positive_opt_input_fails_closed(self):
        self._append_complete_capture(self.pipelines["member-a"]["opt_input"])
        with self.assertRaisesRegex(RefinementError, "current selected capture"):
            self.build()

    def test_stale_negative_opt_input_fails_closed(self):
        negative_input, _authority = self._negative_opt_input("member-b")
        self._append_complete_capture(negative_input)
        with self.assertRaisesRegex(RefinementError, "selected current capture"):
            self.build(
                positive_opt=(self.pipelines["member-a"]["opt_input"],),
                negative_opt=(negative_input,),
                positive_freq=(self.pipelines["member-a"]["freq_input"],),
            )

    def test_positive_optimizations_require_one_exact_method_identity(self):
        changed = dict(self.z0.method)
        changed["basis"] = "def2-SVP"
        pipelines = self._pipelines(self.source_coordinates, method_by_member={"member-b": changed})
        with self.assertRaisesRegex(RefinementError, "one exact method identity"):
            self.build(
                positive_opt=tuple(item["opt_input"] for item in pipelines.values()),
                positive_freq=(),
            )

    def test_negative_opt_disposition_cannot_hide_a_method_mismatch(self):
        changed = dict(self.z0.method)
        changed["basis"] = "def2-SVP"
        negative, _authority = self._negative_opt_input("member-b", method=changed)
        with self.assertRaisesRegex(RefinementError, "one exact method identity"):
            self.build(
                positive_opt=(self.pipelines["member-a"]["opt_input"],),
                negative_opt=(negative,),
                positive_freq=(self.pipelines["member-a"]["freq_input"],),
            )

    def test_wrong_member_or_originating_ensemble_lineage_rejects(self):
        forged_member = {
            **self.pipelines["member-a"]["opt_input"],
            "member_id": "member-b",
        }
        with self.assertRaisesRegex(RefinementError, "source authority is spliced"):
            self.build(positive_opt=(forged_member,))

        other_prior = ConformerEnsemble._create(
            project_id=self.prior.project_id,
            calculation_plan_id="another-sampling-plan",
            calculation_plan_revision=self.prior.calculation_plan_revision,
            profile=self.profile,
            sampling_observations=self.prior.sampling_observations,
            audit_evidence=self.prior.audit_evidence,
            negative_evidence=self.prior.negative_evidence,
            dedup_decisions=self.prior.dedup_decisions,
            independent_review_blockers=self.prior.independent_review_blockers,
            clusters=self.prior.clusters,
            members=self.prior.members,
            coverage=self.prior.coverage,
            thermodynamic_eligible_members=self.prior.thermodynamic_eligible_members,
            ts_seed_members=self.prior.ts_seed_members,
        )
        with self.assertRaisesRegex(RefinementError, "source authority is spliced"):
            build_refined_conformer_ensemble(
                other_prior,
                self.profile,
                positive_optimization_inputs=tuple(
                    item["opt_input"] for item in self.pipelines.values()
                ),
                negative_optimization_inputs=(),
                positive_frequency_inputs=tuple(
                    item["freq_input"] for item in self.pipelines.values()
                ),
                negative_frequency_inputs=(),
            )

    def test_post_opt_identity_audit_rejects_drift_without_discarding_authority(self):
        drifted = dict(self.source_coordinates)
        drifted["member-b"] = (
            (0.0, 0.0, 0.0), (10.0, 0.0, 0.0),
            (20.0, 1.0, 0.0), (30.0, 1.0, 0.0),
        )
        pipelines = self._pipelines(drifted)
        refined = self.build(
            positive_opt=tuple(item["opt_input"] for item in pipelines.values()),
            positive_freq=(pipelines["member-a"]["freq_input"],),
        )
        self.assertEqual(refined.thermodynamic_eligible_members, ("member-a",))
        evidence = next(item for item in refined.negative_evidence if item.get("stage") == "post_dft_identity_audit")
        self.assertEqual(evidence["optimization_geometry_authority_id"], pipelines["member-b"]["optimization"]["optimization_geometry_authority_id"])
        self.assertIn("required_bond_distance_exceeded:map_c1:map_c2", evidence["reasons"])
        member = next(item for item in refined.members if item["member_id"] == "member-b")
        self.assertEqual(member["coordinates_angstrom"], self.prior.members[1]["coordinates_angstrom"])

    def test_post_opt_duplicates_collapse_in_prior_member_order(self):
        duplicate_coordinates = {
            "member-a": self.source_coordinates["member-a"],
            "member-b": self.source_coordinates["member-a"],
        }
        pipelines = self._pipelines(duplicate_coordinates)
        refined = self.build(
            positive_opt=tuple(item["opt_input"] for item in pipelines.values()),
            positive_freq=(pipelines["member-a"]["freq_input"],),
        )
        decision = next(item for item in refined.dedup_decisions if item.get("stage") == "post_dft_optimization_geometry")
        self.assertEqual(decision["decision"], "duplicate")
        self.assertEqual(decision["mapped_rmsd_angstrom"], 0.0)
        self.assertEqual(refined.thermodynamic_eligible_members, ("member-a",))
        evidence = next(item for item in refined.negative_evidence if item.get("stage") == "post_dft_dedup")
        self.assertEqual(evidence["member_id"], "member-b")
        self.assertEqual(evidence["duplicate_of_member_id"], "member-a")

    def test_just_over_threshold_and_full_precision_do_not_round_to_duplicate(self):
        near_threshold = dict(self.source_coordinates)
        near_threshold["member-b"] = (
            (0.0, 0.0, 0.0), (1.5, 0.0, 0.0),
            (2.5, 1.243, 0.0), (3.5, 1.0, 0.0),
        )
        pipelines = self._pipelines(near_threshold)
        refined = self.build(
            positive_opt=tuple(item["opt_input"] for item in pipelines.values()),
            positive_freq=tuple(item["freq_input"] for item in pipelines.values()),
        )
        decision = next(item for item in refined.dedup_decisions if item.get("stage") == "post_dft_optimization_geometry")
        self.assertGreater(decision["mapped_rmsd_angstrom"], 0.08)
        self.assertEqual(round(decision["mapped_rmsd_angstrom"], 2), 0.08)
        self.assertEqual(decision["decision"], "independent")
        self.assertEqual(refined.thermodynamic_eligible_members, ("member-a", "member-b"))

    def test_freq_disposition_set_is_exact_and_mutually_exclusive(self):
        negative_input, _authority = self._negative_freq_input("member-b")
        with self.assertRaisesRegex(RefinementError, "both positive and negative Freq"):
            self.build(negative_freq=(negative_input,))
        with self.assertRaisesRegex(RefinementError, "complete post-Opt survivor set"):
            self.build(positive_freq=(self.pipelines["member-a"]["freq_input"],))
        with self.assertRaisesRegex(RefinementError, "duplicate member disposition"):
            self.build(
                positive_freq=(
                    self.pipelines["member-a"]["freq_input"],
                    self.pipelines["member-a"]["freq_input"],
                    self.pipelines["member-b"]["freq_input"],
                )
            )

    def test_negative_frequency_is_retained_and_excluded_from_both_projections(self):
        negative_input, negative = self._negative_freq_input("member-b")
        refined = self.build(
            positive_freq=(self.pipelines["member-a"]["freq_input"],),
            negative_freq=(negative_input,),
        )
        self.assertEqual(refined.thermodynamic_eligible_members, ("member-a",))
        self.assertEqual(refined.ts_seed_members, ("member-a",))
        evidence = next(item for item in refined.negative_evidence if item.get("stage") == "freq")
        self.assertEqual(evidence["negative_refinement_authority_id"], negative["negative_frequency_authority_id"])
        self.assertEqual(evidence["failure_class"], "not_minimum")

    def test_stale_positive_frequency_input_fails_closed(self):
        self._append_complete_capture(self.pipelines["member-a"]["freq_input"])
        with self.assertRaisesRegex(RefinementError, "current selected capture"):
            self.build()

    def test_stale_negative_frequency_input_fails_closed(self):
        negative_input, _authority = self._negative_freq_input("member-b")
        self._append_complete_capture({
            "input_binding": negative_input["frequency_input_binding"],
            "core_store": negative_input["frequency_core_store"],
        })
        with self.assertRaisesRegex(RefinementError, "selected current capture"):
            self.build(
                positive_freq=(self.pipelines["member-a"]["freq_input"],),
                negative_freq=(negative_input,),
            )

    def test_duplicate_cannot_reenter_through_frequency_authority(self):
        duplicate_coordinates = {
            "member-a": self.source_coordinates["member-a"],
            "member-b": self.source_coordinates["member-a"],
        }
        pipelines = self._pipelines(duplicate_coordinates)
        with self.assertRaisesRegex(RefinementError, "complete post-Opt survivor set"):
            self.build(
                positive_opt=tuple(item["opt_input"] for item in pipelines.values()),
                positive_freq=tuple(item["freq_input"] for item in pipelines.values()),
            )

    def test_review_band_blocks_all_downstream_projection_without_fallback(self):
        ambiguous = dict(self.source_coordinates)
        ambiguous["member-b"] = (
            (0.0, 0.0, 0.0), (1.5, 0.0, 0.0),
            (2.5, 1.4, 0.0), (3.5, 1.0, 0.0),
        )
        pipelines = self._pipelines(ambiguous)
        refined = self.build(
            positive_opt=tuple(item["opt_input"] for item in pipelines.values()),
            positive_freq=tuple(item["freq_input"] for item in pipelines.values()),
        )
        self.assertEqual(refined.thermodynamic_eligible_members, ())
        self.assertEqual(refined.ts_seed_members, ())
        self.assertTrue(any(item.get("reason") == "post_opt_rmsd_review_band" for item in refined.independent_review_blockers))

    def test_incomplete_fragment_association_cannot_regain_eligibility(self):
        self._use_multifragment_profile(associations=[])
        self.assertEqual(self.prior.coverage["status"], "insufficient")
        self.assertFalse(
            self.prior.coverage["obligations"][
                "fragment_association_semantics_complete"
            ]
        )
        self.assertEqual(self.prior.thermodynamic_eligible_members, ())

        refined = self.build()

        self.assertEqual(refined.coverage, self.prior.coverage)
        self.assertEqual(refined.thermodynamic_eligible_members, ())
        self.assertEqual(refined.ts_seed_members, ())

    def test_complete_fragment_association_only_removes_that_gate(self):
        self._use_multifragment_profile(associations=[{
            "fragment_ids": ["fragment_1", "fragment_2"],
            "atom_ids": ["map_c2", "map_o1"],
            "minimum": 0.5,
            "maximum": 3.0,
            "unit": "angstrom",
        }])
        self.assertEqual(self.prior.coverage["status"], "sufficient")
        self.assertTrue(
            self.prior.coverage["obligations"][
                "fragment_association_semantics_complete"
            ]
        )

        refined = self.build()

        self.assertEqual(refined.coverage, self.prior.coverage)
        self.assertEqual(
            refined.thermodynamic_eligible_members,
            ("member-a", "member-b"),
        )
        self.assertEqual(refined.ts_seed_members, ("member-a",))

    def test_thermo_and_ts_coverage_policies_remain_independent(self):
        complete_association = [{
            "fragment_ids": ["fragment_1", "fragment_2"],
            "atom_ids": ["map_c2", "map_o1"],
            "minimum": 0.5,
            "maximum": 3.0,
            "unit": "angstrom",
        }]
        self._use_multifragment_profile(
            associations=complete_association,
            thermodynamic_statuses=("insufficient",),
            ts_statuses=("sufficient",),
        )
        association_complete = self.build()
        self.assertEqual(association_complete.thermodynamic_eligible_members, ())
        self.assertEqual(association_complete.ts_seed_members, ("member-a",))

        self._use_multifragment_profile(
            associations=[],
            thermodynamic_statuses=("sufficient",),
            ts_statuses=("insufficient",),
        )
        association_incomplete = self.build()
        self.assertEqual(association_incomplete.thermodynamic_eligible_members, ())
        self.assertEqual(association_incomplete.ts_seed_members, ())

    def test_fragment_association_obligation_missing_or_malformed_fails_closed(self):
        for malformed in (None, "yes"):
            with self.subTest(malformed=malformed):
                self._use_multifragment_profile(associations=[])
                coverage = dict(self.prior.coverage)
                obligations = dict(coverage["obligations"])
                if malformed is None:
                    obligations.pop("fragment_association_semantics_complete")
                else:
                    obligations["fragment_association_semantics_complete"] = malformed
                coverage["obligations"] = obligations
                self._replace_prior_coverage(coverage)
                with self.assertRaisesRegex(
                    RefinementError,
                    "fragment-association obligation is missing or malformed",
                ):
                    self.build()

    def test_sampling_evidence_member_identity_and_coverage_are_retained(self):
        refined = self.build()
        self.assertEqual(refined.sampling_observations, self.prior.sampling_observations)
        self.assertEqual(refined.audit_evidence[:len(self.prior.audit_evidence)], self.prior.audit_evidence)
        self.assertEqual(refined.negative_evidence[:len(self.prior.negative_evidence)], self.prior.negative_evidence)
        self.assertEqual(refined.coverage, self.prior.coverage)
        self.assertEqual(tuple(item["member_id"] for item in refined.members), tuple(item["member_id"] for item in self.prior.members))

    def test_every_eligible_member_retains_current_two_stage_lineage(self):
        refined = self.build()
        self.assertEqual(refined.thermodynamic_eligible_members, ("member-a", "member-b"))
        for member_id in refined.thermodynamic_eligible_members:
            member = next(item for item in refined.members if item["member_id"] == member_id)
            self.assertEqual(member["optimization_geometry_authority"], self.pipelines[member_id]["optimization"])
            self.assertEqual(member["two_stage_minimum_authority"], self.pipelines[member_id]["minimum"])
            self.assertEqual(member["two_stage_minimum_authority"]["source"]["member_id"], member_id)

    def test_ts_seed_is_a_distinct_relevance_projection_of_eligible_minima(self):
        refined = self.build()
        self.assertEqual(refined.thermodynamic_eligible_members, ("member-a", "member-b"))
        self.assertEqual(refined.ts_seed_members, ("member-a",))
        member = next(item for item in refined.members if item["member_id"] == "member-a")
        self.assertIn("ts_seed", member["relevance_tags"])
        self.assertNotIn("transition_state", member)

    def test_non_linear_small_molecule_support_is_not_added(self):
        with self.assertRaisesRegex(RefinementAuthorityError, "linear geometry is unsupported"):
            self.z0.validate_geometry(
                "CO2",
                ((-1.16, 0.0, 0.0), (0.0, 0.0, 0.0), (1.16, 0.0, 0.0)),
                (-100.0, 100.0, 200.0, 300.0),
            )

    def test_private_factory_revision_rules_and_public_exports_are_unchanged(self):
        with self.assertRaisesRegex(ValueError, "successor"):
            ConformerEnsemble._create(
                project_id=self.prior.project_id,
                calculation_plan_id=self.prior.calculation_plan_id,
                calculation_plan_revision=self.prior.calculation_plan_revision,
                profile=self.profile,
                sampling_observations=self.prior.sampling_observations,
                audit_evidence=self.prior.audit_evidence,
                negative_evidence=self.prior.negative_evidence,
                dedup_decisions=self.prior.dedup_decisions,
                independent_review_blockers=self.prior.independent_review_blockers,
                clusters=self.prior.clusters,
                members=self.prior.members,
                coverage=self.prior.coverage,
                thermodynamic_eligible_members=(),
                ts_seed_members=(),
                revision=2,
                supersedes_conformer_ensemble_id=None,
            )
        self.assertEqual(conformer.__all__, ["ConformerEnsemble", "SamplingProfile"])
        self.assertFalse(hasattr(conformer, "build_refined_conformer_ensemble"))
        source = (
            Path(__file__).parents[3] / "auto_g16/conformer/refinement.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("ResultProvenanceService", source)
        self.assertNotIn("current_view(", source)


if __name__ == "__main__":
    unittest.main()
