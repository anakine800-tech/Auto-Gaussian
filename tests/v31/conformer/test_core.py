"""Offline adversarial tests for the closed V31 conformer core."""

from __future__ import annotations

import ast
import copy
from dataclasses import is_dataclass
import math
from pathlib import Path
import unittest

import auto_g16.conformer as conformer
from auto_g16.conformer import ConformerEnsemble, SamplingProfile
from auto_g16.conformer._geometry import mapped_rmsd
from auto_g16.conformer.models import ConformerError, _payload_sha256
from auto_g16.conformer.service import build_conformer_ensemble, create_sampling_profile


ROOT = Path(__file__).parents[3]


class ConformerCoreTests(unittest.TestCase):
    def species_binding(self, *, multifragment: bool = False) -> dict[str, object]:
        bonds = (
            [["map_c1", "map_c2", 1.0], ["map_o1", "map_h1", 1.0]]
            if multifragment
            else [["map_c1", "map_c2", 1.0], ["map_c2", "map_o1", 1.0], ["map_o1", "map_h1", 1.0]]
        )
        fragments = (
            ["fragment_1", "fragment_1", "fragment_2", "fragment_2"]
            if multifragment
            else ["fragment_1"] * 4
        )
        return {
            "graph_identity": "synthetic-species-graph-v1",
            "atom_order": ["map_c1", "map_c2", "map_o1", "map_h1"],
            "atom_mapping": {
                "map_c1": "source_atom_1",
                "map_c2": "source_atom_2",
                "map_o1": "source_atom_3",
                "map_h1": "source_atom_4",
            },
            "elements": ["C", "C", "O", "H"],
            "explicit_hydrogens": [False, False, False, True],
            "fragment_ids": fragments,
            "component_count": 2 if multifragment else 1,
            "bonds": bonds,
            "formal_charge": 0,
            "multiplicity": 1,
            "electronic_state_family": "reviewed_closed_shell_singlet",
        }

    def stereochemistry_binding(self) -> dict[str, object]:
        return {"scope": "locked", "assignments": {"map_c2": "R"}, "binding_modes": {"alcohol_orientation": "reviewed"}}

    def crest_profile(self, *, seed: int = 11) -> dict[str, object]:
        return {
            "provider": "crest",
            "mode": "imtd-gc",
            "engine": {"semantic_identity": "crest-engine-release-3.0.2", "version": "3.0.2+build.7"},
            "adapter": {"semantic_identity": "auto-g16-conformer-crest-adapter-v1", "version": "1.0.0+adapter.1"},
            "sampling_method": {"semantic_identity": "crest-imtd-gc-method-v1", "profile_identity": "synthetic-reviewed-profile-v1"},
            "seed_policy": {"mode": "explicit", "values": [seed]},
            "replica_policy": {"replica_count": 20, "member_index_origin": 0},
            "budget": {"minimum_observations": 1, "minimum_valid": 1, "maximum_observations": 20},
            "termination": {"criterion": "bounded_steps", "maximum_steps": 200},
            "sampling_energy": {
                "unit": "kcal_per_mol_sampling_only",
                "admission_window": {"disposition": "applicable", "value": 6.0, "unit": "kcal_per_mol_sampling_only"},
            },
            "imtd_gc_controls": {
                "metadynamics_temperature_kelvin": 300.0,
                "metadynamics_time_ps": 5.0,
                "rmsd_threshold_angstrom": 0.5,
                "rotamer_search": True,
            },
        }

    def profile(
        self,
        *,
        species: dict[str, object] | None = None,
        associations: list[dict[str, object]] | None = None,
        duplicate_threshold: float = 0.08,
        review_minimum: float = 0.10,
        review_maximum: float = 0.20,
        descriptor_compatibility: float = 0.15,
        crest: dict[str, object] | None = None,
    ) -> SamplingProfile:
        selected_species = species or self.species_binding()
        bond_limits = [
            {"atom_ids": list(bond[:2]), "maximum": 2.0, "unit": "angstrom"}
            for bond in selected_species["bonds"]
        ]
        return create_sampling_profile(
            revision=1,
            supersedes_sampling_profile_id=None,
            species_binding=selected_species,
            stereochemistry_binding=self.stereochemistry_binding(),
            bond_change_policy="forbid",
            geometry_legality_policy={
                "minimum_pair_distance": {"disposition": "applicable", "value": 0.4, "unit": "angstrom"},
                "reference_bond_maximum_distances": bond_limits,
                "fragment_association_constraints": associations or [],
            },
            crest_imtd_gc_profile=crest or self.crest_profile(),
            rmsd_policy={
                "atom_selection": "heavy",
                "alignment": "quaternion_rigid",
                "atom_correspondence": "source_to_canonical_bijection",
                "symmetry_mapping": [0, 1, 2, 3],
                "duplicate_threshold": {"disposition": "applicable", "value": duplicate_threshold, "unit": "angstrom"},
                "review_band": {"minimum": review_minimum, "maximum": review_maximum, "unit": "angstrom"},
            },
            clustering_policy={
                "linkage": "single",
                "composite_merge_threshold": {"disposition": "applicable", "value": duplicate_threshold, "unit": "weighted_distance"},
                "mapped_rmsd_weight": 1.0,
                "medoid_tie_breaker": "member_id",
            },
            descriptor_policy=[
                {
                    "name": "c_o_distance", "kind": "scalar", "unit": "angstrom", "weight": 0.0,
                    "compatibility_threshold": {"disposition": "applicable", "value": descriptor_compatibility, "unit": "angstrom"},
                    "applicability": {"status": "required"},
                },
                {
                    "name": "central_torsion", "kind": "periodic_degrees", "unit": "degree", "weight": 0.0,
                    "compatibility_threshold": {"disposition": "applicable", "value": 20.0, "unit": "degree"},
                    "applicability": {"status": "required"},
                },
                {
                    "name": "contact_class", "kind": "categorical_set", "unit": "dimensionless", "weight": 0.0,
                    "compatibility_threshold": {"disposition": "applicable", "value": 0.0, "unit": "fraction"},
                    "applicability": {"status": "required"},
                },
            ],
            coverage_policy={
                "met_status": "sufficient", "unmet_status": "insufficient",
                "invalid_observation_effect": "uncertain", "global_claim_allowed": False,
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

    def coordinates(self) -> list[list[float]]:
        return [[0.0, 0.0, 0.0], [1.5, 0.0, 0.0], [2.5, 1.0, 0.0], [3.5, 1.0, 0.0]]

    def correspondence(self, species: dict[str, object]) -> list[dict[str, str]]:
        return [
            {"source_atom_id": species["atom_mapping"][atom], "canonical_map_id": atom, "element": element}
            for atom, element in zip(species["atom_order"], species["elements"])
        ]

    def observation(
        self,
        profile: SamplingProfile,
        member_id: str,
        *,
        coordinates: list[list[float]] | None = None,
        member_index: int = 0,
        replica_index: int = 0,
        energy: float = 0.0,
        relevance_tags: list[str] | None = None,
    ) -> dict[str, object]:
        species = dict(profile.species_binding)
        route = profile.crest_imtd_gc_profile
        return {
            "member_id": member_id,
            "atom_order": list(species["atom_order"]),
            "atom_correspondence": self.correspondence(species),
            "elements": list(species["elements"]),
            "explicit_hydrogens": list(species["explicit_hydrogens"]),
            "fragment_ids": list(species["fragment_ids"]),
            "bonds": [list(bond) for bond in species["bonds"]],
            "formal_charge": species["formal_charge"],
            "multiplicity": species["multiplicity"],
            "electronic_state_family": species["electronic_state_family"],
            "stereochemistry_binding": self.stereochemistry_binding(),
            "coordinates_angstrom": coordinates or self.coordinates(),
            "source_binding": {
                "sampling_profile_id": profile.sampling_profile_id,
                "provider": "crest",
                "mode": "imtd-gc",
                "sampling_configuration_identity": _payload_sha256(route),
                "source_run_id": "crest-run-1",
                "source_set_id": "crest-set-1",
                "source_member_index": member_index,
                "source_geometry_identity": f"geometry-{member_id}",
                "source_artifact_identity": f"artifact-{member_id}",
                "seed": route["seed_policy"]["values"][0],
                "replica_index": replica_index,
            },
            "sampling_energy": {"value": energy, "unit": "kcal_per_mol_sampling_only", "formal_thermodynamics_allowed": False},
            "descriptors": {
                "c_o_distance": {"value": 1.42, "unit": "angstrom"},
                "central_torsion": {"value": 60.0, "unit": "degree"},
                "contact_class": {"value": ["alcohol_contact"], "unit": "dimensionless"},
            },
            "relevance_tags": relevance_tags or [],
        }

    def ensemble(self, profile: SamplingProfile, observations: list[dict[str, object]]) -> ConformerEnsemble:
        return build_conformer_ensemble(
            project_id="project-conformer-fixture",
            calculation_plan_id="plan-conformer-fixture",
            calculation_plan_revision=3,
            profile=profile,
            observations=observations,
        )

    def test_A_1000_angstrom_required_bond_is_state_changed_and_ineligible(self) -> None:
        profile = self.profile()
        stretched = self.observation(profile, "stretched")
        stretched["coordinates_angstrom"][1] = [1000.0, 0.0, 0.0]
        ensemble = self.ensemble(profile, [stretched])
        evidence = ensemble.audit_evidence[0]
        self.assertEqual(evidence["status"], "state_changed")
        self.assertTrue(any(reason.startswith("required_bond_distance_exceeded:") for reason in evidence["reasons"]))
        self.assertEqual(ensemble.members, ())
        self.assertEqual(ensemble.thermodynamic_eligible_members, ())
        self.assertEqual(ensemble.ts_seed_members, ())

    def test_B_changed_covalent_graph_is_negative_evidence(self) -> None:
        profile = self.profile()
        changed = self.observation(profile, "changed")
        changed["bonds"] = changed["bonds"][:-1]
        ensemble = self.ensemble(profile, [changed])
        self.assertEqual(ensemble.negative_evidence[0]["status"], "state_changed")
        self.assertIn("covalent_graph_changed", ensemble.negative_evidence[0]["reasons"])

    def test_C_multifragment_without_association_semantics_blocks_downstream(self) -> None:
        profile = self.profile(species=self.species_binding(multifragment=True))
        candidate = self.observation(profile, "associated")
        ensemble = self.ensemble(profile, [candidate])
        self.assertEqual(ensemble.audit_evidence[0]["status"], "valid")
        self.assertFalse(ensemble.coverage["obligations"]["fragment_association_semantics_complete"])
        self.assertEqual(ensemble.thermodynamic_eligible_members, ())
        self.assertEqual(ensemble.ts_seed_members, ())

    def test_association_constraint_drift_is_state_changed(self) -> None:
        species = self.species_binding(multifragment=True)
        constraints = [{
            "fragment_ids": ["fragment_1", "fragment_2"], "atom_ids": ["map_c2", "map_o1"],
            "minimum": 1.0, "maximum": 3.0, "unit": "angstrom",
        }]
        profile = self.profile(species=species, associations=constraints)
        dissociated = self.observation(profile, "dissociated")
        dissociated["coordinates_angstrom"][2] = [100.0, 0.0, 0.0]
        dissociated["coordinates_angstrom"][3] = [101.0, 0.0, 0.0]
        ensemble = self.ensemble(profile, [dissociated])
        self.assertEqual(ensemble.audit_evidence[0]["status"], "state_changed")
        self.assertTrue(any(reason.startswith("fragment_association_constraint_violated:") for reason in ensemble.audit_evidence[0]["reasons"]))

    def test_partial_multifragment_association_semantics_remain_blocked(self) -> None:
        species = self.species_binding(multifragment=True)
        species["fragment_ids"] = ["fragment_1", "fragment_1", "fragment_2", "fragment_3"]
        species["component_count"] = 3
        species["bonds"] = [["map_c1", "map_c2", 1.0]]
        partial = [{
            "fragment_ids": ["fragment_1", "fragment_2"], "atom_ids": ["map_c2", "map_o1"],
            "minimum": 1.0, "maximum": 3.0, "unit": "angstrom",
        }]
        profile = self.profile(species=species, associations=partial)
        ensemble = self.ensemble(profile, [self.observation(profile, "partial")])
        self.assertEqual(ensemble.audit_evidence[0]["status"], "valid")
        self.assertFalse(ensemble.coverage["obligations"]["fragment_association_semantics_complete"])
        self.assertEqual(ensemble.thermodynamic_eligible_members, ())
        self.assertEqual(ensemble.ts_seed_members, ())

    def test_D_boundary_comparison_blocks_review_and_does_not_merge(self) -> None:
        left_coordinates = self.coordinates()
        right_coordinates = copy.deepcopy(left_coordinates)
        right_coordinates[2][2] = 0.3
        observed = mapped_rmsd(left_coordinates, right_coordinates, [0, 1, 2])
        profile = self.profile(
            duplicate_threshold=observed / 2.0,
            review_minimum=math.nextafter(observed, 0.0),
            review_maximum=math.nextafter(observed, math.inf),
        )
        left = self.observation(profile, "left", coordinates=left_coordinates, member_index=0)
        right = self.observation(profile, "right", coordinates=right_coordinates, member_index=1)
        ensemble = self.ensemble(profile, [left, right])
        self.assertEqual(ensemble.dedup_decisions[0]["decision"], "pending_independent_review")
        self.assertEqual(ensemble.independent_review_blockers[0]["reason"], "boundary_band")
        self.assertEqual(len(ensemble.clusters), 2)

    def test_E_descriptor_conflict_blocks_review_and_does_not_merge(self) -> None:
        profile = self.profile(descriptor_compatibility=0.1)
        left = self.observation(profile, "left", member_index=0)
        right = self.observation(profile, "right", member_index=1)
        right["descriptors"]["c_o_distance"]["value"] = 2.0
        ensemble = self.ensemble(profile, [left, right])
        comparison = ensemble.dedup_decisions[0]
        blocker = ensemble.independent_review_blockers[0]
        self.assertEqual(comparison["decision"], "pending_independent_review")
        self.assertEqual(blocker["reason"], "descriptor_conflict")
        self.assertEqual(blocker["comparison_digest"], comparison["comparison_digest"])
        self.assertEqual(len(ensemble.clusters), 2)

    def test_F_pending_review_cannot_be_bypassed_by_medoid_or_subset(self) -> None:
        profile = self.profile(descriptor_compatibility=0.1)
        left = self.observation(profile, "left", member_index=0)
        right = self.observation(profile, "right", member_index=1)
        right["descriptors"]["contact_class"]["value"] = ["other_contact"]
        ensemble = self.ensemble(profile, [left, right])
        self.assertEqual({member["member_id"] for member in ensemble.members}, {"left", "right"})
        self.assertFalse(ensemble.coverage["obligations"]["independent_review_resolved"])
        self.assertEqual(ensemble.thermodynamic_eligible_members, ())
        self.assertEqual(ensemble.ts_seed_members, ())

    def test_G_open_configuration_or_options_bag_rejects(self) -> None:
        for key in ("configuration", "options", "provider_options", "metadata"):
            crest = self.crest_profile()
            crest[key] = {"arbitrary": True}
            with self.subTest(key=key), self.assertRaisesRegex(ConformerError, "exactly"):
                self.profile(crest=crest)

    def test_G_engine_adapter_and_method_identities_reject_executable_or_path_semantics(self) -> None:
        locations = (
            ("engine", "semantic_identity"),
            ("adapter", "semantic_identity"),
            ("sampling_method", "semantic_identity"),
            ("sampling_method", "profile_identity"),
        )
        forbidden = (
            "../bin/crest",
            "C:/Program Files/CREST/crest.exe",
            r"C:\\Program Files\\CREST\\crest.exe",
            "crest",
            "crest.exe",
            "$PATH",
            "PATH",
            "semantic..identity",
        )
        for container, field in locations:
            for value in forbidden:
                crest = self.crest_profile()
                crest[container][field] = value
                with self.subTest(container=container, field=field, value=value), self.assertRaises(ConformerError):
                    self.profile(crest=crest)
        for container in ("engine", "adapter"):
            for value in forbidden:
                crest = self.crest_profile()
                crest[container]["version"] = value
                with self.subTest(container=container, field="version", value=value), self.assertRaises(ConformerError):
                    self.profile(crest=crest)

    def test_G_versions_accept_exact_semver_build_and_reject_paths_or_invalid_grammar(self) -> None:
        profile = self.profile()
        self.assertEqual(profile.crest_imtd_gc_profile["engine"]["version"], "3.0.2+build.7")
        self.assertEqual(profile.crest_imtd_gc_profile["adapter"]["version"], "1.0.0+adapter.1")
        invalid_versions = (
            "3.0.2/crest",
            r"3.0.2\\crest",
            "C:/Program Files/CREST/crest.exe",
            "3.0.2.exe",
            "3.0.2+PATH",
            "01.0.0",
            "1.0",
            "1.0.0+",
            "1.0.0+build..7",
            "1.0.0_build",
        )
        for container in ("engine", "adapter"):
            for value in invalid_versions:
                crest = self.crest_profile()
                crest[container]["version"] = value
                with self.subTest(container=container, value=value), self.assertRaises(ConformerError):
                    self.profile(crest=crest)

    def test_H_open_candidate_provenance_bag_rejects(self) -> None:
        profile = self.profile()
        candidate = self.observation(profile, "open")
        candidate["source_binding"]["metadata"] = {"arbitrary": True}
        ensemble = self.ensemble(profile, [candidate])
        self.assertIn("source_binding_inventory_mismatch", ensemble.negative_evidence[0]["reasons"])
        self.assertEqual(ensemble.members, ())

    def test_I_unknown_sampling_provider_rejects(self) -> None:
        crest = self.crest_profile()
        crest["provider"] = "xtb-md"
        with self.assertRaisesRegex(ConformerError, "exactly crest"):
            self.profile(crest=crest)

    def test_J_exact_closed_crest_profile_and_source_accept(self) -> None:
        profile = self.profile()
        candidate = self.observation(profile, "accepted")
        ensemble = self.ensemble(profile, [candidate])
        self.assertEqual(profile.crest_imtd_gc_profile["provider"], "crest")
        self.assertEqual(profile.crest_imtd_gc_profile["mode"], "imtd-gc")
        self.assertEqual(ensemble.audit_evidence[0]["status"], "valid")
        self.assertEqual(tuple(member["member_id"] for member in ensemble.members), ("accepted",))
        self.assertFalse(ensemble.members[0]["post_dft_minimum_evidence_available"])
        self.assertEqual(ensemble.thermodynamic_eligible_members, ())
        self.assertEqual(ensemble.ts_seed_members, ())

    def test_source_profile_provider_mode_configuration_seed_and_replica_must_agree(self) -> None:
        profile = self.profile()
        mutations = {
            "profile": ("sampling_profile_id", "other-profile", "source_sampling_profile_id_mismatch"),
            "provider": ("provider", "other", "source_provider_mismatch"),
            "mode": ("mode", "other", "source_mode_mismatch"),
            "configuration": ("sampling_configuration_identity", "0" * 64, "source_sampling_configuration_identity_mismatch"),
            "seed": ("seed", 99, "source_seed_mismatch"),
            "replica": ("replica_index", 99, "source_replica_index_out_of_range"),
        }
        observations = []
        for index, (name, (field, value, _reason)) in enumerate(mutations.items()):
            candidate = self.observation(profile, name, member_index=index)
            candidate["source_binding"][field] = value
            observations.append(candidate)
        ensemble = self.ensemble(profile, observations)
        negative = {item["member_id"]: set(item["reasons"]) for item in ensemble.negative_evidence}
        for name, (_field, _value, reason) in mutations.items():
            self.assertIn(reason, negative[name])

    def test_closed_sampling_energy_admission_window_is_applied(self) -> None:
        profile = self.profile()
        low = self.observation(profile, "low", member_index=0, energy=0.0)
        outside = self.observation(profile, "outside", member_index=1, energy=math.nextafter(6.0, math.inf))
        ensemble = self.ensemble(profile, [low, outside])
        evidence = {item["member_id"]: item for item in ensemble.audit_evidence}
        self.assertEqual(evidence["low"]["status"], "valid")
        self.assertEqual(evidence["outside"]["status"], "not_admitted")
        self.assertIn("sampling_energy_outside_admission_window", evidence["outside"]["reasons"])

    def test_exact_graph_fragment_charge_state_stereo_and_mapping_are_bound(self) -> None:
        profile = self.profile()
        cases: list[tuple[str, str, object]] = [
            ("fragment", "fragment_ids", ["other"] * 4),
            ("charge", "formal_charge", 1),
            ("multiplicity", "multiplicity", 3),
        ]
        observations = []
        for index, (name, field, value) in enumerate(cases):
            candidate = self.observation(profile, name, member_index=index)
            candidate[field] = value
            observations.append(candidate)
        stereo = self.observation(profile, "stereo", member_index=4)
        stereo["stereochemistry_binding"]["assignments"]["map_c2"] = "S"
        observations.append(stereo)
        mapping = self.observation(profile, "mapping", member_index=5)
        mapping["atom_correspondence"] = mapping["atom_correspondence"][:-1]
        observations.append(mapping)
        ensemble = self.ensemble(profile, observations)
        self.assertTrue(all(item["retained_as_negative_evidence"] for item in ensemble.audit_evidence))
        self.assertEqual({item["status"] for item in ensemble.audit_evidence}, {"state_changed", "invalid"})

    def test_profile_and_ensemble_are_immutable_and_input_order_deterministic(self) -> None:
        profile = self.profile()
        first = self.observation(profile, "first", member_index=0)
        second_coordinates = self.coordinates()
        second_coordinates[2] = [1.7, 1.5, 0.8]
        second = self.observation(profile, "second", coordinates=second_coordinates, member_index=1)
        forward = self.ensemble(profile, [first, second])
        reverse = self.ensemble(profile, [second, first])
        self.assertEqual(forward.conformer_ensemble_id, reverse.conformer_ensemble_id)
        with self.assertRaises(TypeError):
            profile.crest_imtd_gc_profile["provider"] = "other"

    def test_public_exports_are_exact_and_no_governance_or_execution_surface_exists(self) -> None:
        self.assertEqual(conformer.__all__, ["ConformerEnsemble", "SamplingProfile"])
        public_records = [getattr(conformer, name) for name in conformer.__all__ if is_dataclass(getattr(conformer, name))]
        self.assertEqual(public_records, [ConformerEnsemble, SamplingProfile])
        for forbidden in ("ConformerCandidate", "IndependentReview", "SamplingProvider", "DFTRefinementEvidence"):
            self.assertFalse(hasattr(conformer, forbidden))
        forbidden_imports = {"asyncio", "http", "requests", "socket", "subprocess", "urllib"}
        imported: set[str] = set()
        for path in sorted((ROOT / "auto_g16" / "conformer").glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module.split(".")[0])
        self.assertTrue(forbidden_imports.isdisjoint(imported), imported & forbidden_imports)

    def test_nonfinite_geometry_is_retained_as_sanitized_negative_evidence(self) -> None:
        profile = self.profile()
        candidate = self.observation(profile, "nonfinite")
        candidate["coordinates_angstrom"][0][0] = float("nan")
        ensemble = self.ensemble(profile, [candidate])
        self.assertIn("nonfinite_or_malformed_geometry", ensemble.negative_evidence[0]["reasons"])
        self.assertEqual(ensemble.sampling_observations[0]["coordinates_angstrom"][0][0]["invalid_numeric_observation"], "nan")


if __name__ == "__main__":
    unittest.main()
