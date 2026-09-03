"""Adversarial tests for private CREST 3.0.2 XYZ-trajectory ingestion."""

from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import inspect
from pathlib import Path
import unittest

import auto_g16.core as core
import auto_g16.conformer as conformer
from auto_g16.conformer.ingest import (
    _CrestOutputArtifactBinding,
    _ingest_crest_conformers_xyz,
)
from auto_g16.conformer.models import ConformerError, _payload_sha256
from auto_g16.conformer.service import build_conformer_ensemble, create_sampling_profile
from auto_g16.execution._identity import semantic_sha256
from auto_g16.execution.program import _prepare_program_execution_spec
from tests.v3.execution.test_v31_lane_a import CREST_EXECUTABLE_BYTES, LaneAFixture


ROOT = Path(__file__).parents[3]


class CrestIngestTests(LaneAFixture):
    def profile(
        self,
        *,
        energy_unit: str = "kcal_per_mol_sampling_only",
        c_o_bond_order: float = 1.0,
        stereo_assignment: str = "R",
    ):
        species = {
            "graph_identity": "cco-graph-v1",
            "atom_order": ["map_c1", "map_o1", "map_h1"],
            "atom_mapping": {
                "map_c1": "source_atom_1",
                "map_o1": "source_atom_2",
                "map_h1": "source_atom_3",
            },
            "elements": ["C", "O", "H"],
            "explicit_hydrogens": [False, False, True],
            "fragment_ids": ["fragment_1", "fragment_1", "fragment_1"],
            "component_count": 1,
            "bonds": [["map_c1", "map_o1", c_o_bond_order], ["map_o1", "map_h1", 1.0]],
            "formal_charge": 0,
            "multiplicity": 1,
            "electronic_state_family": "reviewed_closed_shell_singlet",
        }
        crest = {
            "provider": "crest",
            "mode": "imtd-gc",
            "engine": {"semantic_identity": "crest-engine-release-3.0.2", "version": "3.0.2"},
            "adapter": {"semantic_identity": "auto-g16-v31-crest", "contract_version": 2},
            "sampling_method": {
                "semantic_identity": "crest-imtd-gc-method-v1",
                "profile_identity": "reviewed-profile-v1",
            },
            "runtype_selector": "-v3",
            "seed_policy": {
                "mode": "engine_managed_stochastic",
                "seed": None,
                "replay_semantics": "configuration_replay_not_bitwise_trajectory_replay",
            },
            "replica_policy": {"mode": "single_run", "replica_count": 1, "member_index_origin": 0},
            "budget": {"minimum_observations": 1, "minimum_valid": 1, "maximum_observations": 20},
            "sampling_energy": {
                "unit": energy_unit,
                "admission_window": {"disposition": "applicable", "value": 6.0, "unit": energy_unit},
            },
            "imtd_gc_controls": {
                "model": "gfn2",
                "charge": 0,
                "unpaired_electrons": 0,
                "metadynamics_length_ps": 5.0,
                "cregen_rmsd_threshold_angstrom": 0.5,
                "cregen_temperature_kelvin": 298.15,
                "normal_md_temperature_kelvin": 300.0,
            },
        }
        return create_sampling_profile(
            revision=1,
            supersedes_sampling_profile_id=None,
            species_binding=species,
            stereochemistry_binding={"scope": "locked", "assignments": {"map_c1": stereo_assignment}, "binding_modes": {}},
            bond_change_policy="forbid",
            geometry_legality_policy={
                "minimum_pair_distance": {"disposition": "applicable", "value": 0.4, "unit": "angstrom"},
                "reference_bond_maximum_distances": [
                    {"atom_ids": ["map_c1", "map_o1"], "maximum": 2.0, "unit": "angstrom"},
                    {"atom_ids": ["map_o1", "map_h1"], "maximum": 2.0, "unit": "angstrom"},
                ],
                "fragment_association_constraints": [],
            },
            crest_imtd_gc_profile=crest,
            rmsd_policy={
                "atom_selection": "all",
                "alignment": "quaternion_rigid",
                "atom_correspondence": "source_to_canonical_bijection",
                "symmetry_mapping": [0, 1, 2],
                "duplicate_threshold": {"disposition": "applicable", "value": 0.05, "unit": "angstrom"},
                "review_band": {"minimum": 0.10, "maximum": 0.20, "unit": "angstrom"},
            },
            clustering_policy={
                "linkage": "single",
                "composite_merge_threshold": {"disposition": "applicable", "value": 0.05, "unit": "weighted_distance"},
                "mapped_rmsd_weight": 1.0,
                "medoid_tie_breaker": "member_id",
            },
            descriptor_policy=[{
                "name": "c_o_distance",
                "kind": "scalar",
                "unit": "angstrom",
                "weight": 0.0,
                "compatibility_threshold": {"disposition": "applicable", "value": 0.2, "unit": "angstrom"},
                "applicability": {"status": "required"},
            }],
            coverage_policy={
                "met_status": "sufficient",
                "unmet_status": "insufficient",
                "invalid_observation_effect": "uncertain",
                "global_claim_allowed": False,
            },
            thermodynamic_eligibility_policy={
                "require_post_dft_minimum": True,
                "required_coverage_statuses": ["sufficient"],
            },
            ts_seed_projection_policy={
                "require_post_dft_minimum": True,
                "required_coverage_statuses": ["sufficient"],
                "allowed_relevance_tags": ["ts_seed"],
            },
        )

    def spec(self, profile):
        route = profile.crest_imtd_gc_profile
        controls = route["imtd_gc_controls"]
        return _prepare_program_execution_spec(
            program_kind="crest",
            executable_path="/opt/auto-g16-fixtures/bin/crest",
            executable_size_bytes=len(CREST_EXECUTABLE_BYTES),
            executable_sha256=sha256(CREST_EXECUTABLE_BYTES).hexdigest(),
            input_name="seed.xyz",
            input_bytes=b"3\nseed\nC 0 0 0\nO 1.2 0 0\nH 2.1 0 0\n",
            program_data={
                "provider": "crest",
                "sampling_mode": "imtd-gc",
                "engine_version": "3.0.2",
                "runtype_selector": "-v3",
                "model": controls["model"],
                "charge": controls["charge"],
                "unpaired_electrons": controls["unpaired_electrons"],
                "metadynamics_length_millipicoseconds": 5000,
                "cregen_energy_window_millikcal_per_mol": 6000,
                "cregen_rmsd_threshold_milliangstrom": 500,
                "cregen_temperature_millikelvin": 298150,
                "normal_md_temperature_millikelvin": 300000,
                "stochastic_policy": dict(route["seed_policy"]),
                "sampling_configuration_identity": _payload_sha256(route),
            },
        )

    @staticmethod
    def frame(energy: float, coordinates=None, elements=("C", "O", "H")) -> bytes:
        selected = coordinates or ((0.0, 0.0, 0.0), (1.2, 0.0, 0.0), (2.1, 0.1, 0.0))
        lines = ["  3", f"  {energy:18.8f}"]
        lines.extend(
            f" {element:<2} {x:20.10f}{y:20.10f}{z:20.10f}"
            for element, (x, y, z) in zip(elements, selected)
        )
        return ("\n".join(lines) + "\n").encode("ascii")

    @staticmethod
    def plan_intent(profile, spec, **changes):
        value = {
            "schema": "v31-crest-sampling-plan/1",
            "sampling_profile_id": profile.sampling_profile_id,
            "sampling_profile_payload_sha256": profile.payload_sha256,
            "program_execution_spec_id": spec.program_execution_spec_id,
            "program_execution_spec_payload_sha256": semantic_sha256(spec.semantic_payload()),
        }
        value.update(changes)
        return value

    def snapshot(self, *, profile, spec, plan_id="plan-y-1", revision=1, intent=None):
        self.store.store_calculation_plan(
            core.CalculationPlan(
                calculation_plan_id=plan_id,
                task_id="task-1",
                revision=revision,
                intent=self.plan_intent(profile, spec) if intent is None else intent,
            )
        )
        return self.snapshot_service.prepare(
            self.store,
            attempt_id="attempt-1",
            calculation_plan_id=plan_id,
            resource_spec_id="resource-1",
            program_execution_spec=spec,
            project_physical_binding=self.physical_binding(),
            resolved_resource_request=self.resources(),
            resolved_server_profile=self.resolved(),
            workspace_binding=self.workspace(),
        )

    @staticmethod
    def artifact(snapshot, raw: bytes, **changes):
        values = {
            "program_execution_snapshot_id": snapshot.program_execution_snapshot_id,
            "effect_intent_id": snapshot.effect_intent_id,
            "program_execution_spec_id": snapshot.program_execution_spec_id,
            "logical_role": "conformer-ensemble",
            "portable_name": "crest_conformers.xyz",
            "format": "xyz-trajectory",
            "sha256": sha256(raw).hexdigest(),
            "size_bytes": len(raw),
        }
        values.update(changes)
        return _CrestOutputArtifactBinding(**values)

    def ingest(
        self,
        raw: bytes,
        *,
        profile=None,
        spec=None,
        snapshot=None,
        artifact=None,
        descriptors=None,
        relevance=None,
        plan_id="plan-y-1",
        plan_revision=1,
        intent=None,
    ):
        selected_profile = profile or self.profile()
        selected_spec = spec or self.spec(selected_profile)
        selected_snapshot = snapshot or self.snapshot(
            profile=selected_profile,
            spec=selected_spec,
            plan_id=plan_id,
            revision=plan_revision,
            intent=intent,
        )
        selected_artifact = artifact or self.artifact(selected_snapshot, raw)
        return _ingest_crest_conformers_xyz(
            profile=selected_profile,
            program_execution_snapshot=selected_snapshot,
            core_store=self.store,
            artifact_binding=selected_artifact,
            artifact_bytes=raw,
            descriptors_by_member_index=descriptors,
            relevance_tags_by_member_index=relevance,
        )

    def test_exact_multiframe_artifact_builds_closed_observations(self) -> None:
        raw = self.frame(-100.0) + self.frame(-99.999)
        profile = self.profile()
        spec = self.spec(profile)
        snapshot = self.snapshot(profile=profile, spec=spec)
        descriptors = {
            0: {"c_o_distance": {"value": 1.2, "unit": "angstrom"}},
            1: {"c_o_distance": {"value": 1.2, "unit": "angstrom"}},
        }
        observations = self.ingest(
            raw,
            profile=profile,
            spec=spec,
            snapshot=snapshot,
            descriptors=descriptors,
            relevance={1: ("ts_seed",)},
        )
        self.assertEqual(len(observations), 2)
        self.assertEqual([item["source_binding"]["source_member_index"] for item in observations], [0, 1])
        self.assertEqual([item["sampling_energy"]["value"] for item in observations], [0.0, 0.627509541])
        self.assertEqual(
            {item["source_binding"]["source_run_id"] for item in observations},
            {snapshot.program_execution_snapshot_id},
        )
        self.assertEqual(
            len({item["source_binding"]["source_artifact_identity"] for item in observations}),
            1,
        )
        self.assertEqual(
            observations[0]["source_binding"]["source_geometry_identity"],
            observations[1]["source_binding"]["source_geometry_identity"],
        )
        ensemble = build_conformer_ensemble(
            project_id="project-y",
            calculation_plan_id=snapshot.calculation_plan_id,
            calculation_plan_revision=1,
            profile=profile,
            observations=observations,
        )
        self.assertEqual(len(ensemble.members), 2)
        self.assertEqual(ensemble.thermodynamic_eligible_members, ())
        self.assertEqual(ensemble.ts_seed_members, ())

    def test_same_exact_inputs_are_deterministic_and_immutable(self) -> None:
        raw = self.frame(-1.0)
        supplied = {0: {"c_o_distance": {"value": 1.2, "unit": "angstrom"}}}
        first = self.ingest(raw, descriptors=supplied)
        second = self.ingest(raw, descriptors=supplied)
        supplied[0]["c_o_distance"]["value"] = 99.0
        self.assertEqual(first, second)
        self.assertEqual(first[0]["descriptors"]["c_o_distance"]["value"], 1.2)
        with self.assertRaises(TypeError):
            first[0]["member_id"] = "changed"

    def test_ordered_and_equal_energies_use_frame_zero_and_preserve_order(self) -> None:
        observations = self.ingest(
            self.frame(-100.0) + self.frame(-100.0) + self.frame(-99.999),
            descriptors=None,
        )
        self.assertEqual(
            [item["sampling_energy"]["value"] for item in observations],
            [0.0, 0.0, 0.627509541],
        )
        self.assertEqual(
            [item["source_binding"]["source_member_index"] for item in observations],
            [0, 1, 2],
        )

    def test_any_descending_energy_pair_rejects_the_whole_artifact(self) -> None:
        cases = (
            self.frame(-99.999) + self.frame(-100.0),
            self.frame(-100.0) + self.frame(-99.998) + self.frame(-99.999),
            self.frame(-99.999) + self.frame(-100.0) + self.frame(-99.998),
        )
        for index, raw in enumerate(cases):
            with self.subTest(index=index), self.assertRaisesRegex(
                ConformerError, "not nondecreasing"
            ):
                self.ingest(raw, descriptors=None, plan_id=f"plan-order-{index}")

    def test_production_contains_no_energy_sort_or_global_minimum(self) -> None:
        source = (ROOT / "auto_g16" / "conformer" / "ingest.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("sorted(", source)
        self.assertNotIn(".sort(", source)
        self.assertNotIn("min(frame", source)

    def test_missing_descriptor_is_not_fabricated_and_blocks_member(self) -> None:
        profile = self.profile()
        observations = self.ingest(self.frame(-1.0), profile=profile, spec=self.spec(profile), descriptors=None)
        self.assertEqual(dict(observations[0]["descriptors"]), {})
        ensemble = build_conformer_ensemble(
            project_id="project-y", calculation_plan_id="plan-y", calculation_plan_revision=1,
            profile=profile, observations=observations,
        )
        self.assertEqual(ensemble.members, ())
        self.assertIn("missing_required_descriptor:c_o_distance", ensemble.negative_evidence[0]["reasons"])

    def test_artifact_sha_size_and_immutable_byte_type_are_exact(self) -> None:
        raw = self.frame(-1.0)
        profile = self.profile()
        spec = self.spec(profile)
        snapshot = self.snapshot(profile=profile, spec=spec, plan_id="plan-artifact")
        valid = self.artifact(snapshot, raw)
        cases = (
            replace(valid, sha256="0" * 64),
            replace(valid, sha256="A" * 64),
            replace(valid, size_bytes=len(raw) + 1),
            replace(valid, size_bytes=True),
        )
        for artifact in cases:
            with self.subTest(artifact=artifact), self.assertRaises(ConformerError):
                self.ingest(
                    raw,
                    profile=profile,
                    spec=spec,
                    snapshot=snapshot,
                    artifact=artifact,
                    descriptors=None,
                )
        with self.assertRaises(ConformerError):
            _ingest_crest_conformers_xyz(
                profile=profile,
                program_execution_snapshot=snapshot,
                core_store=self.store,
                artifact_binding=valid,
                artifact_bytes=bytearray(raw),
                descriptors_by_member_index=None,
            )

    def test_profile_and_snapshot_identities_are_closed(self) -> None:
        profile = self.profile()
        wrong_profile = self.profile()
        object.__setattr__(wrong_profile, "sampling_profile_id", "forged")
        with self.assertRaises(ConformerError):
            self.ingest(
                self.frame(-1.0),
                profile=wrong_profile,
                spec=self.spec(profile),
                descriptors=None,
                plan_id="plan-identity-profile",
            )
        for index, (field, value) in enumerate((
            ("adapter_contract_version", 1),
            ("required_outputs", ()),
        )):
            spec = self.spec(profile)
            snapshot = self.snapshot(
                profile=profile,
                spec=spec,
                plan_id=f"plan-identity-spec-{index}",
            )
            object.__setattr__(spec, field, value)
            with self.subTest(field=field), self.assertRaises(ConformerError):
                self.ingest(
                    self.frame(-1.0),
                    profile=profile,
                    spec=spec,
                    snapshot=snapshot,
                    artifact=self.artifact(snapshot, self.frame(-1.0)),
                    descriptors=None,
                )

    def test_profile_graph_and_stereo_cross_splice_reject_before_observations(self) -> None:
        profile_a = self.profile()
        spec = self.spec(profile_a)
        snapshot = self.snapshot(profile=profile_a, spec=spec, plan_id="plan-cross-a")
        for profile_b in (
            self.profile(c_o_bond_order=2.0),
            self.profile(stereo_assignment="S"),
        ):
            with self.subTest(profile=profile_b.sampling_profile_id), self.assertRaisesRegex(
                ConformerError, "different SamplingProfile"
            ):
                self.ingest(
                    self.frame(-1.0),
                    profile=profile_b,
                    spec=spec,
                    snapshot=snapshot,
                    descriptors=None,
                )

    def test_plan_bound_to_other_profile_or_spec_rejects(self) -> None:
        profile = self.profile()
        spec = self.spec(profile)
        cases = (
            self.plan_intent(
                profile,
                spec,
                sampling_profile_id="sampling-profile-" + "0" * 64,
            ),
            self.plan_intent(
                profile,
                spec,
                sampling_profile_payload_sha256="0" * 64,
            ),
            self.plan_intent(
                profile,
                spec,
                program_execution_spec_id="other-program-execution-spec",
            ),
            self.plan_intent(
                profile,
                spec,
                program_execution_spec_payload_sha256="0" * 64,
            ),
        )
        for index, intent in enumerate(cases):
            with self.subTest(index=index), self.assertRaises(ConformerError):
                self.ingest(
                    self.frame(-1.0),
                    profile=profile,
                    spec=spec,
                    descriptors=None,
                    plan_id=f"plan-cross-{index}",
                    intent=intent,
                )

    def test_plan_intent_schema_and_exact_field_set_are_closed(self) -> None:
        profile = self.profile()
        spec = self.spec(profile)
        valid = self.plan_intent(profile, spec)
        cases = (
            {"program": "crest"},
            {**valid, "schema": "v31-crest-sampling-plan/2"},
            {key: value for key, value in valid.items() if key != "sampling_profile_id"},
            {**valid, "caller_options": "forbidden"},
        )
        for index, intent in enumerate(cases):
            with self.subTest(index=index), self.assertRaisesRegex(
                ConformerError, "closed CREST sampling contract"
            ):
                self.ingest(
                    self.frame(-1.0),
                    profile=profile,
                    spec=spec,
                    descriptors=None,
                    plan_id=f"plan-intent-{index}",
                    intent=intent,
                )

    def test_snapshot_plan_id_revision_and_payload_are_closed(self) -> None:
        profile = self.profile()
        spec = self.spec(profile)
        raw = self.frame(-1.0)
        for field, value in (
            ("calculation_plan_id", "other-plan"),
            ("calculation_plan_revision", 2),
            ("program_execution_spec_payload_sha256", "0" * 64),
            ("program_execution_snapshot_id", "forged-snapshot"),
        ):
            snapshot = self.snapshot(
                profile=profile,
                spec=spec,
                plan_id=f"plan-snapshot-{field}",
            )
            object.__setattr__(snapshot, field, value)
            with self.subTest(field=field), self.assertRaises(ConformerError):
                self.ingest(
                    raw,
                    profile=profile,
                    spec=spec,
                    snapshot=snapshot,
                    artifact=self.artifact(snapshot, raw),
                    descriptors=None,
                )

    def test_output_declaration_missing_duplicate_optional_or_malformed_rejects(self) -> None:
        profile = self.profile()
        raw = self.frame(-1.0)
        transformations = (
            lambda required, optional: (required[:1], optional),
            lambda required, optional: (required + (required[1],), optional),
            lambda required, optional: (required[:1], optional + (required[1],)),
            lambda required, optional: (
                required[:1] + ({**dict(required[1]), "portable_name": "other.xyz"},),
                optional,
            ),
            lambda required, optional: (
                required[:1] + ({**dict(required[1]), "format": "text"},), optional
            ),
            lambda required, optional: (
                required[:1]
                + ({**dict(required[1]), "logical_role": "other-role"},),
                optional,
            ),
        )
        for index, transform in enumerate(transformations):
            spec = self.spec(profile)
            snapshot = self.snapshot(
                profile=profile,
                spec=spec,
                plan_id=f"plan-output-{index}",
            )
            required, optional = transform(spec.required_outputs, spec.optional_outputs)
            object.__setattr__(spec, "required_outputs", required)
            object.__setattr__(spec, "optional_outputs", optional)
            with self.subTest(index=index), self.assertRaises(ConformerError):
                self.ingest(
                    raw,
                    profile=profile,
                    spec=spec,
                    snapshot=snapshot,
                    artifact=self.artifact(snapshot, raw),
                    descriptors=None,
                )

    def test_artifact_binding_closes_snapshot_effect_spec_and_declaration(self) -> None:
        profile = self.profile()
        spec = self.spec(profile)
        raw = self.frame(-1.0)
        snapshot = self.snapshot(profile=profile, spec=spec, plan_id="plan-artifact-link")
        valid = self.artifact(snapshot, raw)
        cases = (
            replace(valid, program_execution_snapshot_id="other-snapshot"),
            replace(valid, effect_intent_id="other-effect"),
            replace(valid, program_execution_spec_id="other-spec"),
            replace(valid, logical_role="other-role"),
            replace(valid, portable_name="other.xyz"),
            replace(valid, format="text"),
        )
        for artifact in cases:
            with self.subTest(artifact=artifact), self.assertRaises(ConformerError):
                self.ingest(
                    raw,
                    profile=profile,
                    spec=spec,
                    snapshot=snapshot,
                    artifact=artifact,
                    descriptors=None,
                )

    def test_ingest_has_no_caller_supplied_run_or_spec_parameter(self) -> None:
        parameters = inspect.signature(_ingest_crest_conformers_xyz).parameters
        self.assertNotIn("source_run_id", parameters)
        self.assertNotIn("program_execution_spec", parameters)
        self.assertIn("program_execution_snapshot", parameters)
        self.assertIn("core_store", parameters)
        self.assertIn("artifact_binding", parameters)

    def test_unsupported_sampling_energy_unit_fails_closed(self) -> None:
        profile = self.profile(energy_unit="hartree")
        with self.assertRaisesRegex(ConformerError, "frozen sampling-energy unit"):
            self.ingest(self.frame(-1.0), profile=profile, spec=self.spec(profile), descriptors=None)

    def test_lf_termination_and_boundaries_are_exact(self) -> None:
        valid = self.frame(-1.0)
        cases = (
            valid[:-1],
            valid.replace(b"\n", b"\r\n"),
            valid + b"junk\n",
            valid + b"\n",
            valid.replace(b"  3\n", b"3\n", 1),
            valid.replace(b"  3\n", b"  03\n", 1),
            valid.replace(b"  3\n", b"  4\n", 1),
        )
        for raw in cases:
            with self.subTest(raw=raw), self.assertRaises(ConformerError):
                self.ingest(raw, descriptors=None)

    def test_energy_comment_uses_only_exact_crest_writer_grammar(self) -> None:
        valid = self.frame(-1.0)
        comment = valid.splitlines()[1]
        cases = (
            valid.replace(comment, b" -1.00000000"),
            valid.replace(comment, b"       -1.0000000"),
            valid.replace(comment, b"       -1.00000000 extra"),
            valid.replace(comment, b"               NaN"),
            valid.replace(comment, b"          Infinity"),
            valid.replace(comment, b"     -1.00000000\t"),
            valid.replace(comment, b"        +1.00000000"),
        )
        for raw in cases:
            with self.subTest(raw=raw), self.assertRaises(ConformerError):
                self.ingest(raw, descriptors=None)

    def test_atom_inventory_and_order_are_exact(self) -> None:
        for elements in (("O", "C", "H"), ("C", "N", "H"), ("C", "O")):
            raw = self.frame(-1.0, elements=elements)
            with self.subTest(elements=elements), self.assertRaises(ConformerError):
                self.ingest(raw, descriptors=None)

    def test_coordinate_triplets_width_precision_and_finiteness_are_exact(self) -> None:
        valid = self.frame(-1.0)
        first_atom = valid.splitlines()[2]
        cases = (
            valid.replace(first_atom, b" C          0.0000000000        0.0000000000"),
            valid.replace(first_atom, first_atom.replace(b"0.0000000000", b"0.000000000", 1)),
            valid.replace(first_atom, first_atom.replace(b"        0.0000000000", b"                 NaN", 1)),
            valid.replace(first_atom, first_atom.replace(b"        0.0000000000", b"            Infinity", 1)),
            valid.replace(first_atom, first_atom.replace(b"        0.0000000000", b"       +0.0000000000", 1)),
            valid.replace(first_atom, first_atom + b" "),
        )
        for raw in cases:
            with self.subTest(raw=raw), self.assertRaises(ConformerError):
                self.ingest(raw, descriptors=None)

    def test_descriptor_and_relevance_index_domains_are_exact(self) -> None:
        raw = self.frame(-1.0)
        for descriptors, relevance in (({1: {}}, None), ({True: {}}, None), (None, {-1: ()}), (None, {1: ()})):
            with self.subTest(descriptors=descriptors, relevance=relevance), self.assertRaises(ConformerError):
                self.ingest(raw, descriptors=descriptors, relevance=relevance)

    def test_no_ttconf_live_execution_or_public_export_surface(self) -> None:
        source = (ROOT / "auto_g16" / "conformer" / "ingest.py").read_text(encoding="utf-8")
        lowered = source.lower()
        self.assertNotIn("ttconf", lowered)
        self.assertNotIn("subprocess", lowered)
        self.assertNotIn("paramiko", lowered)
        self.assertEqual(set(conformer.__all__), {"SamplingProfile", "ConformerEnsemble"})
        self.assertNotIn("_ingest_crest_conformers_xyz", conformer.__all__)
        self.assertEqual(tuple(inspect.signature(conformer.SamplingProfile).parameters), ())


if __name__ == "__main__":
    unittest.main()
