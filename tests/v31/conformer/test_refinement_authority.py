"""Offline adversarial coverage for private V31 two-stage DFT lineage."""

from __future__ import annotations

from copy import copy
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import tempfile
import unittest

import auto_g16.conformer as conformer
from auto_g16.conformer.service import create_sampling_profile
from auto_g16.core import Attempt, Project, SQLiteRuntimeStore, Task, WorkflowRun
from auto_g16.execution import PreparedInputBinding
from auto_g16.result import InputBinding, OutputArtifact, OutputEnvelope, ParseOutcome, ResultProvenanceService
from auto_g16.review import build_review_bundle
from auto_g16.scientific_validation import SQLiteScientificValidationStore, record_minimum_validation, validate_minimum
from auto_g16.conformer.refinement_authority import (
    RefinementAuthorityError,
    _expected_frequency_mode_count,
    build_dft_stage,
    validate_optimization_geometry_authority,
    validate_two_stage_minimum_authority,
)
from tests.v3.scientific_validation._fixtures import attributed_facts
from tests.v31.conformer.test_core import ConformerCoreTests


ROOT = Path(__file__).parents[3]
_ATOMIC_NUMBERS = {"H": 1, "C": 6, "O": 8}


class RefinementAuthorityTests(unittest.TestCase):
    def setUp(self) -> None:
        fixture = ConformerCoreTests()
        self.profile = fixture.profile()
        self.ensemble = fixture.ensemble(self.profile, [fixture.observation(self.profile, "member-a")])
        self.method = {
            "program": "gaussian16", "method": "RB3LYP", "basis": "6-31G(d)",
            "dispersion": "none", "solvent": "gas", "reference": "restricted_closed_shell",
            "charge": 0, "multiplicity": 1, "integration_grid": "ultrafine",
            "scf_policy": "tight", "route_contract_version": "auto_g16_v31_conformer_dft_route_1",
        }
        self.opt_plan, self.opt_prepared, self.opt_bytes = build_dft_stage(
            self.ensemble, "member-a", stage="opt", calculation_plan_id="opt-plan", calculation_plan_revision=1,
            task_id="opt-task", attempt_id="opt-attempt", logical_name="opt.gjf", method_binding=self.method,
        )
        self.resources: list[tuple[SQLiteRuntimeStore, SQLiteScientificValidationStore, tempfile.TemporaryDirectory[str]]] = []
        self.opt_chain = self.chain(
            self.opt_plan, self.opt_prepared, self.opt_bytes,
            frequencies=(), optimization_spans=((100, 110),), stationary_spans=((120, 130),),
        )
        self.opt_review = self.opt_chain["review"]
        self.opt_authority = validate_optimization_geometry_authority(
            self.ensemble, "member-a", calculation_plan=self.opt_plan,
            prepared_input_binding=self.opt_prepared, prepared_input_bytes=self.opt_bytes,
            **self.persisted_args(self.opt_chain),
        )
        self.freq_plan, self.freq_prepared, self.freq_bytes = build_dft_stage(
            self.ensemble, "member-a", stage="freq", calculation_plan_id="freq-plan", calculation_plan_revision=1,
            task_id="freq-task", attempt_id="freq-attempt", logical_name="freq.gjf", method_binding=self.method,
            optimization_geometry_authority=self.opt_authority,
        )
        self.freq_chain = self.chain(
            self.freq_plan, self.freq_prepared, self.freq_bytes,
            frequencies=(0.0, 50.0, 100.0, 150.0, 200.0, 250.0),
            optimization_spans=(), stationary_spans=(),
        )
        self.freq_review = self.freq_chain["review"]

    def tearDown(self) -> None:
        for core, validation, temporary in self.resources:
            validation.close(); core.close(); temporary.cleanup()

    def chain(
        self, plan, prepared, prepared_bytes, *, frequencies,
        optimization_spans, stationary_spans, atom_numbers=(6, 6, 8, 1),
        geometry_specs=None, frequency_specs=None, geometry_coordinates=None,
        capture_status="captured", ensemble=None,
    ):
        selected_ensemble = self.ensemble if ensemble is None else ensemble
        temporary = tempfile.TemporaryDirectory()
        core = SQLiteRuntimeStore(":memory:")
        core.store_project(Project(project_id=selected_ensemble.project_id))
        core.store_workflow_run(WorkflowRun(workflow_run_id=f"run-{plan.task_id}", project_id=selected_ensemble.project_id, workflow_name="fixture"))
        core.store_task(Task(task_id=plan.task_id, workflow_run_id=f"run-{plan.task_id}", task_kind="gaussian"))
        core.store_calculation_plan(plan)
        core.create_attempt(Attempt(attempt_id=prepared.attempt_id, task_id=plan.task_id, ordinal=1))
        binding = InputBinding(
            attempt_id=prepared.attempt_id, calculation_plan_id=plan.calculation_plan_id,
            calculation_plan_revision=plan.revision, prepared_input_binding_id=prepared.prepared_input_binding_id,
            execution_snapshot_id=f"snapshot-{prepared.attempt_id}", input_format=prepared.input_format,
            logical_name=prepared.logical_name, sha256=prepared.sha256, size_bytes=prepared.size_bytes,
        )
        envelope = OutputEnvelope(
            attempt_id=prepared.attempt_id, input_binding_observation_id=binding.observation_id,
            execution_snapshot_id=binding.execution_snapshot_id, capture_source_id=f"capture-{prepared.attempt_id}",
            capture_sequence=1, capture_status=capture_status, capture_completeness="complete",
            artifacts=(OutputArtifact(artifact_kind="gaussian-log", logical_name=f"{prepared.attempt_id}.log", sha256=sha256(prepared_bytes + b"-log").hexdigest(), size_bytes=1000),),
            capture_manifest_sha256=sha256(prepared_bytes + b"-manifest").hexdigest(), captured_at_utc="2026-09-02T00:00:00Z",
        )
        facts = attributed_facts(
            envelope, frequencies=frequencies, atom_numbers=atom_numbers,
            optimization_spans=optimization_spans, stationary_spans=stationary_spans,
            geometry_specs=geometry_specs, frequency_specs=frequency_specs,
        )
        if facts["geometry_blocks"]:
            selected_coordinates = geometry_coordinates or tuple(
                (float(index), float(index >= 3), 0.0)
                for index in range(1, len(atom_numbers) + 1)
            )
            facts = dict(facts)
            geometry_blocks = []
            for block in facts["geometry_blocks"]:
                changed_block = dict(block)
                changed_block["atoms"] = tuple(
                    {
                        **dict(atom),
                        "x": float(selected_coordinates[index][0]),
                        "y": float(selected_coordinates[index][1]),
                        "z": float(selected_coordinates[index][2]),
                    }
                    for index, atom in enumerate(block["atoms"])
                )
                geometry_blocks.append(changed_block)
            facts["geometry_blocks"] = tuple(geometry_blocks)
        parsed = ParseOutcome(
            attempt_id=prepared.attempt_id, envelope_observation_id=envelope.observation_id,
            parser_name="auto-g16-v3-gaussian-job", parser_version="1.0.0",
            result_kind="gaussian-job-facts", parse_status="parsed", facts=facts,
        )
        service = ResultProvenanceService(core)
        service.record_input_binding(binding); service.record_output_envelope(envelope); service.record_parse_outcome(parsed)
        validation = SQLiteScientificValidationStore.create_new(Path(temporary.name) / "validation.sqlite3")
        outcome = record_minimum_validation(validation, validate_minimum(core, binding, envelope, parsed))
        review = build_review_bundle(
            core, validation, input_binding=binding, output_envelope=envelope, parse_outcome=parsed,
            minimum_validation_outcome_id=outcome.minimum_validation_outcome_id,
        )
        self.resources.append((core, validation, temporary))
        return {
            "review": review, "core_store": core, "validation_store": validation,
            "input_binding": binding, "output_envelope": envelope,
            "parse_outcome": parsed,
            "minimum_validation_outcome_id": outcome.minimum_validation_outcome_id,
        }

    @staticmethod
    def persisted_args(chain):
        return {key: chain[key] for key in (
            "core_store", "validation_store", "input_binding", "output_envelope",
            "parse_outcome", "minimum_validation_outcome_id",
        )}

    def validate(self, **changes):
        values = {
            "ensemble": self.ensemble, "member_id": "member-a", "optimization_plan": self.opt_plan,
            "optimization_prepared_input_binding": self.opt_prepared, "optimization_prepared_input_bytes": self.opt_bytes,
            "optimization_core_store": self.opt_chain["core_store"],
            "optimization_validation_store": self.opt_chain["validation_store"],
            "optimization_input_binding": self.opt_chain["input_binding"],
            "optimization_output_envelope": self.opt_chain["output_envelope"],
            "optimization_parse_outcome": self.opt_chain["parse_outcome"],
            "optimization_minimum_validation_outcome_id": self.opt_chain["minimum_validation_outcome_id"],
            "frequency_plan": self.freq_plan,
            "frequency_prepared_input_binding": self.freq_prepared, "frequency_prepared_input_bytes": self.freq_bytes,
            "frequency_core_store": self.freq_chain["core_store"],
            "frequency_validation_store": self.freq_chain["validation_store"],
            "frequency_input_binding": self.freq_chain["input_binding"],
            "frequency_output_envelope": self.freq_chain["output_envelope"],
            "frequency_parse_outcome": self.freq_chain["parse_outcome"],
            "frequency_minimum_validation_outcome_id": self.freq_chain["minimum_validation_outcome_id"],
        }
        values.update(changes)
        return validate_two_stage_minimum_authority(**values)

    def three_atom_ensemble(self, formula, coordinates):
        if formula == "CO2":
            atom_order = ["map_o1", "map_c1", "map_o2"]
            elements = ["O", "C", "O"]
            bonds = [["map_o1", "map_c1", 2.0], ["map_c1", "map_o2", 2.0]]
        else:
            atom_order = ["map_o1", "map_h1", "map_h2"]
            elements = ["O", "H", "H"]
            bonds = [["map_o1", "map_h1", 1.0], ["map_o1", "map_h2", 1.0]]
        species = {
            "graph_identity": f"synthetic-{formula.lower()}-graph-v1",
            "atom_order": atom_order,
            "atom_mapping": {atom: f"source_atom_{index}" for index, atom in enumerate(atom_order, 1)},
            "elements": elements,
            "explicit_hydrogens": [element == "H" for element in elements],
            "fragment_ids": ["fragment_1"] * 3,
            "component_count": 1,
            "bonds": bonds,
            "formal_charge": 0,
            "multiplicity": 1,
            "electronic_state_family": "reviewed_closed_shell_singlet",
        }
        stereochemistry = {"scope": "none", "assignments": {}, "binding_modes": {}}
        rmsd_policy = dict(self.profile.rmsd_policy)
        rmsd_policy["atom_selection"] = "all"
        rmsd_policy["symmetry_mapping"] = [0, 1, 2]
        profile = create_sampling_profile(
            revision=1,
            supersedes_sampling_profile_id=None,
            species_binding=species,
            stereochemistry_binding=stereochemistry,
            bond_change_policy="forbid",
            geometry_legality_policy={
                "minimum_pair_distance": {"disposition": "applicable", "value": 0.4, "unit": "angstrom"},
                "reference_bond_maximum_distances": [
                    {"atom_ids": bond[:2], "maximum": 2.5, "unit": "angstrom"}
                    for bond in bonds
                ],
                "fragment_association_constraints": [],
            },
            crest_imtd_gc_profile=self.profile.crest_imtd_gc_profile,
            rmsd_policy=rmsd_policy,
            clustering_policy=self.profile.clustering_policy,
            descriptor_policy=self.profile.descriptor_policy,
            coverage_policy=self.profile.coverage_policy,
            thermodynamic_eligibility_policy=self.profile.thermodynamic_eligibility_policy,
            ts_seed_projection_policy=self.profile.ts_seed_projection_policy,
        )
        fixture = ConformerCoreTests()
        observation = fixture.observation(
            profile,
            f"member-{formula.lower()}",
            coordinates=[list(point) for point in coordinates],
        )
        observation["stereochemistry_binding"] = stereochemistry
        return fixture.ensemble(profile, [observation])

    def validate_three_atom(self, formula, coordinates, frequencies):
        ensemble = self.three_atom_ensemble(formula, coordinates)
        member_id = f"member-{formula.lower()}"
        atom_numbers = tuple(_ATOMIC_NUMBERS[element] for element in ensemble.species_binding["elements"])
        opt_plan, opt_prepared, opt_bytes = build_dft_stage(
            ensemble, member_id, stage="opt", calculation_plan_id=f"opt-{formula}", calculation_plan_revision=1,
            task_id=f"opt-task-{formula}", attempt_id=f"opt-attempt-{formula}", logical_name="opt.gjf", method_binding=self.method,
        )
        opt_chain = self.chain(
            opt_plan, opt_prepared, opt_bytes, frequencies=(),
            optimization_spans=((100, 110),), stationary_spans=((120, 130),),
            atom_numbers=atom_numbers, geometry_coordinates=coordinates, ensemble=ensemble,
        )
        opt_authority = validate_optimization_geometry_authority(
            ensemble, member_id, calculation_plan=opt_plan,
            prepared_input_binding=opt_prepared, prepared_input_bytes=opt_bytes,
            **self.persisted_args(opt_chain),
        )
        freq_plan, freq_prepared, freq_bytes = build_dft_stage(
            ensemble, member_id, stage="freq", calculation_plan_id=f"freq-{formula}", calculation_plan_revision=1,
            task_id=f"freq-task-{formula}", attempt_id=f"freq-attempt-{formula}", logical_name="freq.gjf",
            method_binding=self.method, optimization_geometry_authority=opt_authority,
        )
        freq_chain = self.chain(
            freq_plan, freq_prepared, freq_bytes, frequencies=frequencies,
            optimization_spans=(), stationary_spans=(), atom_numbers=atom_numbers,
            geometry_coordinates=coordinates, ensemble=ensemble,
        )
        return validate_two_stage_minimum_authority(
            ensemble, member_id,
            optimization_plan=opt_plan,
            optimization_prepared_input_binding=opt_prepared,
            optimization_prepared_input_bytes=opt_bytes,
            optimization_core_store=opt_chain["core_store"],
            optimization_validation_store=opt_chain["validation_store"],
            optimization_input_binding=opt_chain["input_binding"],
            optimization_output_envelope=opt_chain["output_envelope"],
            optimization_parse_outcome=opt_chain["parse_outcome"],
            optimization_minimum_validation_outcome_id=opt_chain["minimum_validation_outcome_id"],
            frequency_plan=freq_plan,
            frequency_prepared_input_binding=freq_prepared,
            frequency_prepared_input_bytes=freq_bytes,
            frequency_core_store=freq_chain["core_store"],
            frequency_validation_store=freq_chain["validation_store"],
            frequency_input_binding=freq_chain["input_binding"],
            frequency_output_envelope=freq_chain["output_envelope"],
            frequency_parse_outcome=freq_chain["parse_outcome"],
            frequency_minimum_validation_outcome_id=freq_chain["minimum_validation_outcome_id"],
        )

    def test_01_deterministic_closed_two_stage_authority(self):
        first, second = self.validate(), self.validate()
        self.assertEqual(first, second)
        self.assertEqual(first["classification"], "VALIDATED_TWO_STAGE_MINIMUM")
        self.assertEqual(first["frequency"]["result"]["mode_count"], 6)
        self.assertEqual(
            first["optimization"]["recovered_atom_map"][0],
            {"center": 1, "source_atom_id": "source_atom_1", "canonical_map_id": "map_c1", "atomic_number": 6},
        )

    def test_02_public_exports_unchanged(self):
        self.assertEqual(conformer.__all__, ["ConformerEnsemble", "SamplingProfile"])
        self.assertFalse(hasattr(conformer, "RefinementAuthority"))

    def test_03_builder_resolves_member_and_rejects_missing(self):
        with self.assertRaises(RefinementAuthorityError):
            build_dft_stage(self.ensemble, "missing", stage="opt", calculation_plan_id="p", calculation_plan_revision=1, task_id="t", attempt_id="a", logical_name="x.gjf", method_binding=self.method)

    def test_04_renderer_is_exact_and_has_no_arbitrary_route(self):
        self.assertIn(b"#p RB3LYP/6-31G(d) opt integral=ultrafine scf=tight\n", self.opt_bytes)
        self.assertNotIn(b"--Link1--", self.opt_bytes)
        self.opt_prepared.verify_bytes(self.opt_bytes)

    def test_05_generic_intent_is_ineligible(self):
        generic = replace(self.opt_plan, intent={"operation": "opt"})
        with self.assertRaises(RefinementAuthorityError):
            validate_optimization_geometry_authority(self.ensemble, "member-a", calculation_plan=generic, prepared_input_binding=self.opt_prepared, prepared_input_bytes=self.opt_bytes, **self.persisted_args(self.opt_chain))

    def test_06_extra_intent_key_rejects(self):
        intent = dict(self.opt_plan.intent); intent["extra"] = "forbidden"
        with self.assertRaises(RefinementAuthorityError):
            validate_optimization_geometry_authority(self.ensemble, "member-a", calculation_plan=replace(self.opt_plan, intent=intent), prepared_input_binding=self.opt_prepared, prepared_input_bytes=self.opt_bytes, **self.persisted_args(self.opt_chain))

    def test_07_prepared_bytes_and_identity_are_exact(self):
        with self.assertRaises(RefinementAuthorityError):
            self.validate(optimization_prepared_input_bytes=self.opt_bytes + b" ")

    def test_08_wrong_plan_revision_rejects(self):
        with self.assertRaises(RefinementAuthorityError):
            self.validate(optimization_plan=replace(self.opt_plan, revision=2))

    def test_09_result_attempt_splice_rejects(self):
        forged = replace(self.freq_chain["input_binding"], attempt_id="other")
        with self.assertRaises(RefinementAuthorityError): self.validate(frequency_input_binding=forged)

    def test_10_same_element_cross_member_splice_rejects(self):
        fixture = ConformerCoreTests()
        other = fixture.ensemble(self.profile, [fixture.observation(self.profile, "member-b")])
        with self.assertRaises(RefinementAuthorityError): self.validate(ensemble=other, member_id="member-b")

    def test_11_method_field_changes_identity(self):
        changed = dict(self.method); changed["integration_grid"] = "superfine"
        plan, _binding, _bytes = build_dft_stage(self.ensemble, "member-a", stage="opt", calculation_plan_id="other", calculation_plan_revision=1, task_id="other", attempt_id="other", logical_name="other.gjf", method_binding=changed)
        self.assertNotEqual(plan.intent["method_id"], self.opt_plan.intent["method_id"])

    def test_12_method_injection_and_wrong_state_reject(self):
        for injected in ("B3LYP opt", "B3LYP,Opt", "B3LYP", "UHF", "UB3LYP", "ROHF", "ROB3LYP", "RNOTREAL"):
            changed = dict(self.method); changed["method"] = injected
            with self.subTest(injected=injected), self.assertRaises(RefinementAuthorityError):
                build_dft_stage(self.ensemble, "member-a", stage="opt", calculation_plan_id="p", calculation_plan_revision=1, task_id="t", attempt_id="a", logical_name="x.gjf", method_binding=changed)

    def test_13_opt_freq_method_mismatch_rejects(self):
        object.__setattr__(self.freq_plan, "intent", {**dict(self.freq_plan.intent), "method_id": "wrong"})
        with self.assertRaises(RefinementAuthorityError): self.validate()

    def test_14_negative_frequency_rejects_and_zero_accepts(self):
        chain = self.chain(self.freq_plan, self.freq_prepared, self.freq_bytes, frequencies=(-0.000001, 50.0, 100.0, 150.0, 200.0, 250.0), optimization_spans=(), stationary_spans=())
        changes = {"frequency_" + key: value for key, value in self.persisted_args(chain).items()}
        with self.assertRaises(RefinementAuthorityError): self.validate(**changes)
        self.assertEqual(self.validate()["classification"], "VALIDATED_TWO_STAGE_MINIMUM")

    def test_15_wrong_mode_count_rejects(self):
        chain = self.chain(self.freq_plan, self.freq_prepared, self.freq_bytes, frequencies=(1.0, 2.0, 3.0), optimization_spans=(), stationary_spans=())
        changes = {"frequency_" + key: value for key, value in self.persisted_args(chain).items()}
        with self.assertRaises(RefinementAuthorityError): self.validate(**changes)

    def test_16_wrong_atomic_number_rejects_opt_map_recovery(self):
        chain = self.chain(self.opt_plan, self.opt_prepared, self.opt_bytes, frequencies=(), optimization_spans=((100, 110),), stationary_spans=((120, 130),), atom_numbers=(1, 6, 8, 1))
        changes = {"optimization_" + key: value for key, value in self.persisted_args(chain).items()}
        with self.assertRaises(RefinementAuthorityError): self.validate(**changes)

    def test_17_freq_input_is_exact_opt_geometry_not_caller_coordinates(self):
        self.assertIn(b"C 1.0 0.0 0.0", self.freq_bytes)
        self.assertNotIn(b"C 0.0 0.0 0.0", self.freq_bytes)
        with self.assertRaises(RefinementAuthorityError):
            build_dft_stage(self.ensemble, "member-a", stage="freq", calculation_plan_id="p", calculation_plan_revision=1, task_id="t", attempt_id="a", logical_name="x.gjf", method_binding=self.method, optimization_geometry_authority={})

    def test_18_opt_and_freq_v30_outcomes_remain_truthful(self):
        self.assertEqual(self.opt_review.primary_reason_code, "incomplete-mode-count")
        self.assertEqual(self.freq_review.primary_reason_code, "incomplete-marker-pair")
        self.assertEqual(self.opt_authority["v30_outcome"]["classification"], "INCOMPLETE")

    def test_19_no_live_or_external_execution_surface(self):
        text = (ROOT / "auto_g16/conformer/refinement_authority.py").read_text(encoding="utf-8")
        for forbidden in ("subprocess", "socket", "paramiko", "qsub", "ssh ", "os.system"):
            self.assertNotIn(forbidden, text)

    def test_20_missing_opt_geometry_rejects(self):
        chain = self.chain(self.opt_plan, self.opt_prepared, self.opt_bytes, frequencies=(), optimization_spans=((100, 110),), stationary_spans=((120, 130),), geometry_specs=())
        changes = {"optimization_" + key: value for key, value in self.persisted_args(chain).items()}
        with self.assertRaises(RefinementAuthorityError): self.validate(**changes)

    def test_21_forged_result_id_rejects_persisted_replay(self):
        forged = copy(self.freq_chain["parse_outcome"])
        object.__setattr__(forged, "envelope_observation_id", "forged-envelope")
        with self.assertRaises(RefinementAuthorityError): self.validate(frequency_parse_outcome=forged)

    def test_22_wrong_input_binding_id_rejects(self):
        forged = replace(self.freq_chain["input_binding"], prepared_input_binding_id="forged")
        with self.assertRaises(RefinementAuthorityError): self.validate(frequency_input_binding=forged)

    def test_23_unsupported_program_rejects(self):
        changed = dict(self.method); changed["program"] = "orca"
        with self.assertRaises(RefinementAuthorityError): self._build(changed)

    def test_24_non_none_dispersion_rejects(self):
        changed = dict(self.method); changed["dispersion"] = "gd3bj"
        with self.assertRaises(RefinementAuthorityError): self._build(changed)

    def test_25_non_gas_solvent_rejects(self):
        changed = dict(self.method); changed["solvent"] = "water"
        with self.assertRaises(RefinementAuthorityError): self._build(changed)

    def test_26_unrestricted_reference_rejects(self):
        changed = dict(self.method); changed["reference"] = "unrestricted"
        with self.assertRaises(RefinementAuthorityError): self._build(changed)

    def test_27_charge_mismatch_rejects(self):
        changed = dict(self.method); changed["charge"] = 1
        with self.assertRaises(RefinementAuthorityError): self._build(changed)

    def test_28_multiplicity_bool_and_triplet_reject(self):
        for multiplicity in (True, 3):
            changed = dict(self.method); changed["multiplicity"] = multiplicity
            with self.subTest(multiplicity=multiplicity), self.assertRaises(RefinementAuthorityError): self._build(changed)

    def test_29_route_version_mismatch_rejects(self):
        changed = dict(self.method); changed["route_contract_version"] = "other"
        with self.assertRaises(RefinementAuthorityError): self._build(changed)

    def test_30_method_binding_extra_key_rejects(self):
        changed = dict(self.method); changed["options"] = {}
        with self.assertRaises(RefinementAuthorityError): self._build(changed)

    def test_31_returned_authorities_are_deeply_immutable(self):
        authority = self.validate()
        with self.assertRaises(TypeError): authority["classification"] = "changed"
        with self.assertRaises(TypeError): authority["source"]["member_id"] = "changed"

    def test_32_freq_with_opt_markers_is_not_the_frozen_freq_only_gate(self):
        for optimization_spans, stationary_spans in ((((100, 110),), ((120, 130),)), (((100, 110),), ())):
            chain = self.chain(self.freq_plan, self.freq_prepared, self.freq_bytes, frequencies=(1.0, 2.0, 3.0, 4.0, 5.0, 6.0), optimization_spans=optimization_spans, stationary_spans=stationary_spans)
            changes = {"frequency_" + key: value for key, value in self.persisted_args(chain).items()}
            with self.subTest(optimization_spans=optimization_spans, stationary_spans=stationary_spans), self.assertRaises(RefinementAuthorityError):
                self.validate(**changes)

    def test_33_opt_with_modes_cannot_masquerade_as_geometry_gate(self):
        for frequencies, frequency_specs in (((1.0, 2.0, 3.0, 4.0, 5.0, 6.0), None), ((1.0, 2.0, 3.0), ((60, 70, (1.0, 2.0, 3.0)),))):
            chain = self.chain(self.opt_plan, self.opt_prepared, self.opt_bytes, frequencies=frequencies, optimization_spans=((100, 110),), stationary_spans=((120, 130),), frequency_specs=frequency_specs)
            changes = {"optimization_" + key: value for key, value in self.persisted_args(chain).items()}
            with self.subTest(frequencies=frequencies), self.assertRaises(RefinementAuthorityError):
                self.validate(**changes)

    def test_34_every_method_field_participates_in_identity(self):
        alternatives = {"method": "RHF", "basis": "STO-3G", "integration_grid": "superfine", "scf_policy": "verytight"}
        for field, alternative in alternatives.items():
            changed = dict(self.method); changed[field] = alternative
            plan, _binding, _bytes = self._build(changed)
            with self.subTest(field=field): self.assertNotEqual(plan.intent["method_id"], self.opt_plan.intent["method_id"])

    def test_35_prepared_binding_plan_id_splice_rejects(self):
        forged = PreparedInputBinding(attempt_id=self.opt_prepared.attempt_id, calculation_plan_id="other", calculation_plan_revision=1, input_format="gaussian-gjf", logical_name="opt.gjf", prepared_bytes=self.opt_bytes)
        with self.assertRaises(RefinementAuthorityError): self.validate(optimization_prepared_input_binding=forged)

    def test_36_wrong_opt_authority_cannot_build_freq(self):
        forged = dict(self.opt_authority); forged["method_id"] = "forged"
        with self.assertRaises(RefinementAuthorityError):
            build_dft_stage(self.ensemble, "member-a", stage="freq", calculation_plan_id="p", calculation_plan_revision=1, task_id="t", attempt_id="a", logical_name="x.gjf", method_binding=self.method, optimization_geometry_authority=forged)

    def test_37_private_contract_adds_no_store_or_public_record(self):
        source = (ROOT / "auto_g16/conformer/refinement_authority.py").read_text(encoding="utf-8")
        self.assertNotIn("@dataclass", source)
        self.assertNotIn("class DFT", source)

    def test_38_exact_plan_intent_hash_is_retained(self):
        authority = self.validate()
        self.assertEqual(authority["optimization"]["calculation_plan"]["intent_sha256"], self.opt_authority["calculation_plan"]["intent_sha256"])

    def test_39_freq_source_binds_opt_result_and_artifact(self):
        source = self.freq_plan.intent["optimization_source"]
        self.assertEqual(source["optimization_result_id"], self.opt_review.parse_outcome["result_id"])
        self.assertEqual(source["optimization_source_artifact_sha256"], self.opt_review.parse_outcome["facts"]["source_artifact"]["sha256"])
        forged_source = dict(source); forged_source["extra"] = "forbidden"
        forged_plan = replace(self.freq_plan, intent={**dict(self.freq_plan.intent), "optimization_source": forged_source})
        with self.assertRaises(RefinementAuthorityError):
            self.validate(frequency_plan=forged_plan)

    def test_40_route_method_owns_closed_reference_family(self):
        for method_name in ("RHF", "RB3LYP"):
            changed = dict(self.method); changed["method"] = method_name
            with self.subTest(method_name=method_name):
                plan, _prepared, prepared_bytes = self._build(changed)
                self.assertIn(f"#p {method_name}/".encode("ascii"), prepared_bytes)
                self.assertNotEqual(plan.intent["method_id"], "")
        for method_name in ("UHF", "UB3LYP", "ROHF", "ROB3LYP", "B3LYP", "RNOTREAL"):
            changed = dict(self.method); changed["method"] = method_name
            with self.subTest(method_name=method_name), self.assertRaises(RefinementAuthorityError):
                self._build(changed)

    def test_41_exact_selected_geometry_linearity_owns_mode_count(self):
        monatomic = {"atoms": ({"center": 1, "atomic_number": 1, "x": 0.0, "y": 0.0, "z": 0.0},)}
        diatomic = {"atoms": (
            {"center": 1, "atomic_number": 1, "x": 0.0, "y": 0.0, "z": 0.0},
            {"center": 2, "atomic_number": 1, "x": 1.0, "y": 0.0, "z": 0.0},
        )}
        self.assertEqual(_expected_frequency_mode_count(monatomic, ("H",)), 0)
        self.assertEqual(_expected_frequency_mode_count(diatomic, ("H", "H")), 1)
        linear = ((-1.0, 0.0, 0.0), (0.0, 0.0, 0.0), (1.0, 0.0, 0.0))
        nonlinear = ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0))
        with self.assertRaises(RefinementAuthorityError):
            self.validate_three_atom("CO2", linear, (100.0, 200.0, 300.0))
        self.assertEqual(
            self.validate_three_atom("CO2", linear, (100.0, 200.0, 300.0, 400.0))["frequency"]["result"]["mode_count"],
            4,
        )
        self.assertEqual(
            self.validate_three_atom("H2O", nonlinear, (100.0, 200.0, 300.0))["frequency"]["result"]["mode_count"],
            3,
        )
        degenerate = {"atoms": tuple(
            {"center": index, "atomic_number": atomic_number, "x": 0.0, "y": 0.0, "z": 0.0}
            for index, atomic_number in enumerate((8, 6, 8), 1)
        )}
        with self.assertRaises(RefinementAuthorityError):
            _expected_frequency_mode_count(degenerate, ("O", "C", "O"))

    def test_42_capture_status_and_completeness_are_jointly_required(self):
        self.assertEqual(self.validate()["classification"], "VALIDATED_TWO_STAGE_MINIMUM")
        chain = self.chain(
            self.freq_plan, self.freq_prepared, self.freq_bytes,
            frequencies=(0.0, 50.0, 100.0, 150.0, 200.0, 250.0),
            optimization_spans=(), stationary_spans=(), capture_status="capture-error",
        )
        changes = {"frequency_" + key: value for key, value in self.persisted_args(chain).items()}
        with self.assertRaises(RefinementAuthorityError):
            self.validate(**changes)

    def _build(self, method):
        return build_dft_stage(self.ensemble, "member-a", stage="opt", calculation_plan_id="p", calculation_plan_revision=1, task_id="t", attempt_id="a", logical_name="x.gjf", method_binding=method)


if __name__ == "__main__":
    unittest.main()
