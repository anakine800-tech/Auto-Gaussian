"""Offline closure of the real V31 xTB-to-TS-projection product chain."""

from __future__ import annotations

from copy import copy
from dataclasses import replace
from hashlib import sha256
from importlib import metadata
from pathlib import Path
import tempfile
import unittest

import auto_g16.core as core
import auto_g16.execution as execution
from auto_g16.conformer.final_integration import (
    _FinalIntegrationError,
    _validate_final_ensemble_integration,
)
from auto_g16.conformer.ingest import (
    _CrestOutputArtifactBinding,
    _ingest_preoptimized_crest_conformers_xyz,
)
from auto_g16.conformer.models import ConformerError
from auto_g16.conformer.refinement import (
    RefinementError,
    build_refined_conformer_ensemble,
)
from auto_g16.conformer.refinement_authority import (
    _validate_current_optimization_geometry_authority,
    build_dft_stage,
    validate_negative_frequency_authority,
    validate_negative_optimization_authority,
)
from auto_g16.conformer.service import build_conformer_ensemble
from auto_g16.execution.program_runtime import (
    _assert_program_output_capture_authority,
    _assert_program_terminal_success_authority,
)
from auto_g16.result import (
    InputBinding,
    OutputArtifact,
    OutputEnvelope,
    ParseOutcome,
    ResultProvenanceService,
)
from auto_g16.review import build_review_bundle
from auto_g16.scientific_validation import (
    SQLiteScientificValidationStore,
    record_minimum_validation,
    validate_minimum,
)
from auto_g16.thermochemistry._goodvibes import FunctionalKernelError
from auto_g16.thermochemistry._service import (
    ThermochemistryError,
    _build_thermodynamic_ensemble,
)
from auto_g16.transport._canonical import TransportBoundaryError
from tests.v3.scientific_validation._fixtures import attributed_facts
from tests.v31.conformer import test_final_integration as final_fixtures
from tests.v31.conformer import test_ingest as ingest_fixtures
from tests.v31.conformer import test_xtb_crest_handoff as handoff_fixtures


_METHOD = {
    "program": "gaussian16",
    "method": "RB3LYP",
    "basis": "6-31G(d)",
    "dispersion": "none",
    "solvent": "gas",
    "reference": "restricted_closed_shell",
    "charge": 0,
    "multiplicity": 1,
    "integration_grid": "ultrafine",
    "scf_policy": "tight",
    "route_contract_version": "auto_g16_v31_conformer_dft_route_1",
}

_THERMOCHEMISTRY_POLICY = {
    "adapter_identity": "auto-g16-goodvibes-functional-kernel-adapter",
    "adapter_version": 2,
    "engine_artifact": "goodvibes-4.3.0-py3-none-any.whl",
    "engine_artifact_sha256": (
        "06476db73ee456c1fc941590374f2a30182baaf043f6b60dbef85ee77db93997"
    ),
    "goodvibes_version": "4.3.0",
    "temperature_k": 298.15,
    "standard_state": "1atm",
    "qrrho_entropy_method": "grimme",
    "entropy_frequency_cutoff_cm1": 100.0,
    "entropy_damping_function": "goodvibes_calc_damp_alpha_4",
    "qrrho_enthalpy_method": "head_gordon",
    "enthalpy_frequency_cutoff_cm1": 100.0,
    "enthalpy_damping_function": "goodvibes_calc_damp_alpha_4",
    "frequency_scaling_factor": 0.99,
    "zpe_scaling_factor": 0.98,
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

_SAMPLING_COORDINATES = (
    ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0)),
    ((0.0, 0.0, 0.0), (1.2, 0.0, 0.0), (1.2, 1.6, 0.0)),
    ((0.0, 0.0, 0.0), (1.4, 0.0, 0.0), (2.0, 0.8, 0.0)),
    ((0.0, 0.0, 0.0), (1.6, 0.0, 0.0), (1.6, 0.6, 0.0)),
    ((0.0, 0.0, 0.0), (1.8, 0.0, 0.0), (0.8, 1.2, 0.0)),
)

_POST_OPT_COORDINATES = {
    "a": ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0)),
    "b": ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0)),
    "c": ((0.0, 0.0, 0.0), (1.8, 0.0, 0.0), (0.8, 1.2, 0.0)),
    "d": ((0.0, 0.0, 0.0), (1.4, 0.0, 0.0), (2.0, 0.8, 0.0)),
}


def _goodvibes_430_available() -> bool:
    try:
        return metadata.version("goodvibes") == "4.3.0"
    except metadata.PackageNotFoundError:
        return False


def _gaussian_raw() -> bytes:
    selected = b"".join(
        (
            b" Molecular mass:    44.00000 amu.\n",
            b" Rotational symmetry number  2.\n",
            b" Full point group                 C2     NOp   2\n",
            b" Rotational temperatures (Kelvin)      3.0     2.0     1.0\n",
        )
    )
    return selected + b" " * (900 - len(selected)) + b" outside-section\n".ljust(100, b" ")


class V31OfflineEndToEndAcceptanceTests(unittest.TestCase):
    """One owned route that composes existing V31 services without live effects."""

    def setUp(self) -> None:
        self.handoff_fixture = handoff_fixtures.XtbCrestSeedHandoffTests(
            "test_positive_exact_byte_capture_handoff_plan_v2_and_ingest"
        )
        self.handoff_fixture.setUp()
        self.addCleanup(self.handoff_fixture.doCleanups)
        self._scientific_resources: list[
            tuple[
                core.SQLiteRuntimeStore,
                SQLiteScientificValidationStore,
                tempfile.TemporaryDirectory[str],
            ]
        ] = []
        self.addCleanup(self._close_scientific_resources)

    def _close_scientific_resources(self) -> None:
        for core_store, validation_store, temporary in reversed(
            self._scientific_resources
        ):
            validation_store.close()
            core_store.close()
            temporary.cleanup()

    @staticmethod
    def _validation_driver():
        return handoff_fixtures._NoEffectValidationDriver(
            handoff_fixtures._Driver().runtime_qualification
        )

    def _persisted_gaussian_evidence(
        self,
        ensemble,
        plan,
        prepared,
        prepared_bytes: bytes,
        *,
        frequencies: tuple[float, ...],
        optimization_spans: tuple[tuple[int, int], ...],
        stationary_spans: tuple[tuple[int, int], ...],
        coordinates: tuple[tuple[float, float, float], ...] | None = None,
        program_status: str = "normal-termination",
        energy: float | None = None,
    ) -> dict[str, object]:
        raw = _gaussian_raw()
        temporary = tempfile.TemporaryDirectory()
        core_store = core.SQLiteRuntimeStore(":memory:")
        run_id = f"run-{plan.task_id}"
        core_store.store_project(core.Project(project_id=ensemble.project_id))
        core_store.store_workflow_run(
            core.WorkflowRun(
                workflow_run_id=run_id,
                project_id=ensemble.project_id,
                workflow_name="v31-offline-e2e-synthetic-evidence",
            )
        )
        core_store.store_task(
            core.Task(
                task_id=plan.task_id,
                workflow_run_id=run_id,
                task_kind="gaussian",
            )
        )
        core_store.store_calculation_plan(plan)
        core_store.create_attempt(
            core.Attempt(
                attempt_id=prepared.attempt_id,
                task_id=plan.task_id,
                ordinal=1,
            )
        )
        binding = InputBinding(
            attempt_id=prepared.attempt_id,
            calculation_plan_id=plan.calculation_plan_id,
            calculation_plan_revision=plan.revision,
            prepared_input_binding_id=prepared.prepared_input_binding_id,
            execution_snapshot_id=f"snapshot-{prepared.attempt_id}",
            input_format=prepared.input_format,
            logical_name=prepared.logical_name,
            sha256=prepared.sha256,
            size_bytes=prepared.size_bytes,
        )
        artifact = OutputArtifact(
            artifact_kind="gaussian-log",
            logical_name=f"{prepared.attempt_id}.log",
            sha256=sha256(raw).hexdigest(),
            size_bytes=len(raw),
        )
        envelope = OutputEnvelope(
            attempt_id=prepared.attempt_id,
            input_binding_observation_id=binding.observation_id,
            execution_snapshot_id=binding.execution_snapshot_id,
            capture_source_id=f"capture-{prepared.attempt_id}",
            capture_sequence=1,
            capture_status="captured",
            capture_completeness="complete",
            artifacts=(artifact,),
            capture_manifest_sha256=sha256(
                f"manifest-{prepared.attempt_id}".encode("ascii")
            ).hexdigest(),
            captured_at_utc="2026-09-05T00:00:00Z",
        )
        facts = attributed_facts(
            envelope,
            frequencies=frequencies,
            atom_numbers=(6, 8, 1),
            optimization_spans=optimization_spans,
            stationary_spans=stationary_spans,
            program_status=program_status,
        )
        if coordinates is not None and facts.get("geometry_blocks"):
            changed_blocks = []
            for block in facts["geometry_blocks"]:
                changed_block = dict(block)
                changed_block["atoms"] = tuple(
                    {
                        **dict(atom),
                        "x": float(coordinates[index][0]),
                        "y": float(coordinates[index][1]),
                        "z": float(coordinates[index][2]),
                    }
                    for index, atom in enumerate(block["atoms"])
                )
                changed_blocks.append(changed_block)
            facts = {**facts, "geometry_blocks": tuple(changed_blocks)}
        if energy is not None:
            source = facts["source_artifact"]
            facts = {
                **facts,
                "scf_calculation_count": 1,
                "scf_calculations": (
                    {
                        "energy_hartree": float(energy),
                        "source_span": {**source, "start": 70, "end": 80},
                    },
                ),
                "final_energy_hartree": float(energy),
            }
        parsed = ParseOutcome(
            attempt_id=prepared.attempt_id,
            envelope_observation_id=envelope.observation_id,
            parser_name="auto-g16-v3-gaussian-job",
            parser_version="1.0.0",
            result_kind="gaussian-job-facts",
            parse_status="parsed",
            facts=facts,
        )
        result_service = ResultProvenanceService(core_store)
        result_service.record_input_binding(binding)
        result_service.record_output_envelope(envelope)
        result_service.record_parse_outcome(parsed)
        validation_store = SQLiteScientificValidationStore.create_new(
            Path(temporary.name) / "validation.sqlite3"
        )
        outcome = record_minimum_validation(
            validation_store,
            validate_minimum(core_store, binding, envelope, parsed),
        )
        review = build_review_bundle(
            core_store,
            validation_store,
            input_binding=binding,
            output_envelope=envelope,
            parse_outcome=parsed,
            minimum_validation_outcome_id=outcome.minimum_validation_outcome_id,
        )
        self._scientific_resources.append(
            (core_store, validation_store, temporary)
        )
        return {
            "raw_gaussian_bytes": raw,
            "review": review,
            "core_store": core_store,
            "validation_store": validation_store,
            "input_binding": binding,
            "output_envelope": envelope,
            "parse_outcome": parsed,
            "minimum_validation_outcome_id": outcome.minimum_validation_outcome_id,
        }

    @staticmethod
    def _persisted_args(chain: dict[str, object]) -> dict[str, object]:
        return {
            key: chain[key]
            for key in (
                "core_store",
                "validation_store",
                "input_binding",
                "output_envelope",
                "parse_outcome",
                "minimum_validation_outcome_id",
            )
        }

    @classmethod
    def _opt_input(
        cls,
        member_id: str,
        plan,
        prepared,
        prepared_bytes: bytes,
        chain: dict[str, object],
    ) -> dict[str, object]:
        return {
            "member_id": member_id,
            "calculation_plan": plan,
            "prepared_input_binding": prepared,
            "prepared_input_bytes": prepared_bytes,
            **cls._persisted_args(chain),
        }

    @classmethod
    def _freq_input(
        cls,
        member_id: str,
        opt_input: dict[str, object],
        plan,
        prepared,
        prepared_bytes: bytes,
        chain: dict[str, object],
    ) -> dict[str, object]:
        opt_names = {
            "calculation_plan": "optimization_plan",
            "prepared_input_binding": "optimization_prepared_input_binding",
            "prepared_input_bytes": "optimization_prepared_input_bytes",
            "core_store": "optimization_core_store",
            "validation_store": "optimization_validation_store",
            "input_binding": "optimization_input_binding",
            "output_envelope": "optimization_output_envelope",
            "parse_outcome": "optimization_parse_outcome",
            "minimum_validation_outcome_id": (
                "optimization_minimum_validation_outcome_id"
            ),
        }
        return {
            "member_id": member_id,
            **{
                opt_names[key]: value
                for key, value in opt_input.items()
                if key != "member_id"
            },
            "frequency_plan": plan,
            "frequency_prepared_input_binding": prepared,
            "frequency_prepared_input_bytes": prepared_bytes,
            **{
                f"frequency_{key}": value
                for key, value in cls._persisted_args(chain).items()
            },
        }

    def _initial_chain(self) -> dict[str, object]:
        fixture = self.handoff_fixture
        xtb_snapshot, xtb_capture = fixture.capture_xtb()
        profile = fixture.profile()
        crest_spec = fixture.crest_spec(profile)
        validation_driver = self._validation_driver()
        capture_authority = _assert_program_output_capture_authority(
            fixture.store,
            snapshot=xtb_snapshot,
            program_transport_store=fixture.program_transport_store,
            driver=validation_driver,
            capture=xtb_capture,
        )
        terminal_authority = _assert_program_terminal_success_authority(
            fixture.store,
            snapshot=xtb_snapshot,
            program_transport_store=fixture.program_transport_store,
            driver=validation_driver,
            capture=xtb_capture,
        )
        handoff = fixture.handoff(
            xtb_snapshot,
            xtb_capture,
            profile=profile,
            crest_spec=crest_spec,
        )
        crest_snapshot = fixture.crest_snapshot(
            profile=profile,
            spec=crest_spec,
            handoff=handoff,
        )
        raw = b"".join(
            ingest_fixtures.CrestIngestTests.frame(
                -10.0 + index * 0.0005,
                coordinates=coordinates,
            )
            for index, coordinates in enumerate(_SAMPLING_COORDINATES)
        )
        artifact = _CrestOutputArtifactBinding(
            program_execution_snapshot_id=(
                crest_snapshot.program_execution_snapshot_id
            ),
            effect_intent_id=crest_snapshot.effect_intent_id,
            program_execution_spec_id=crest_snapshot.program_execution_spec_id,
            logical_role="conformer-ensemble",
            portable_name="crest_conformers.xyz",
            format="xyz-trajectory",
            sha256=sha256(raw).hexdigest(),
            size_bytes=len(raw),
        )
        descriptors = {
            index: {
                "c_o_distance": {
                    "value": coordinates[1][0],
                    "unit": "angstrom",
                }
            }
            for index, coordinates in enumerate(_SAMPLING_COORDINATES)
        }
        observations = _ingest_preoptimized_crest_conformers_xyz(
            profile=profile,
            program_execution_snapshot=crest_snapshot,
            core_store=fixture.store,
            preoptimization_handoff=handoff,
            xtb_program_execution_snapshot=xtb_snapshot,
            xtb_program_transport_store=fixture.program_transport_store,
            xtb_validation_driver=self._validation_driver(),
            xtb_output_capture=xtb_capture,
            artifact_binding=artifact,
            artifact_bytes=raw,
            descriptors_by_member_index=descriptors,
            relevance_tags_by_member_index={3: ("ts_seed",)},
        )
        initial = build_conformer_ensemble(
            project_id="project-1",
            calculation_plan_id=crest_snapshot.calculation_plan_id,
            calculation_plan_revision=1,
            profile=profile,
            observations=observations,
        )
        return {
            "profile": profile,
            "xtb_snapshot": xtb_snapshot,
            "xtb_capture": xtb_capture,
            "capture_authority": capture_authority,
            "terminal_authority": terminal_authority,
            "crest_spec": crest_spec,
            "handoff": handoff,
            "crest_snapshot": crest_snapshot,
            "crest_raw": raw,
            "crest_artifact": artifact,
            "observations": observations,
            "initial": initial,
        }

    def _refined_chain(self) -> dict[str, object]:
        values = self._initial_chain()
        initial = values["initial"]
        profile = values["profile"]
        observations_by_index = {
            item["source_binding"]["source_member_index"]: item
            for item in values["observations"]
        }
        duplicate_pair = sorted(
            (
                observations_by_index[0]["member_id"],
                observations_by_index[1]["member_id"],
            )
        )
        roles = {
            "a": duplicate_pair[0],
            "b": duplicate_pair[1],
            "c": observations_by_index[2]["member_id"],
            "d": observations_by_index[3]["member_id"],
            "e": observations_by_index[4]["member_id"],
        }
        opt_inputs: dict[str, dict[str, object]] = {}
        opt_authorities: dict[str, object] = {}
        opt_chains: dict[str, dict[str, object]] = {}
        for role in ("a", "b", "c", "d"):
            member_id = roles[role]
            plan, prepared, prepared_bytes = build_dft_stage(
                initial,
                member_id,
                stage="opt",
                calculation_plan_id=f"opt-plan-{role}",
                calculation_plan_revision=1,
                task_id=f"opt-task-{role}",
                attempt_id=f"opt-attempt-{role}",
                logical_name=f"opt-{role}.gjf",
                method_binding=_METHOD,
            )
            chain = self._persisted_gaussian_evidence(
                initial,
                plan,
                prepared,
                prepared_bytes,
                frequencies=(),
                optimization_spans=((100, 110),),
                stationary_spans=((120, 130),),
                coordinates=_POST_OPT_COORDINATES[role],
            )
            stage_input = self._opt_input(
                member_id, plan, prepared, prepared_bytes, chain
            )
            authority = _validate_current_optimization_geometry_authority(
                initial,
                member_id,
                **{key: value for key, value in stage_input.items() if key != "member_id"},
            )
            opt_inputs[role] = stage_input
            opt_authorities[role] = authority
            opt_chains[role] = chain

        member_id = roles["e"]
        plan, prepared, prepared_bytes = build_dft_stage(
            initial,
            member_id,
            stage="opt",
            calculation_plan_id="opt-plan-e",
            calculation_plan_revision=1,
            task_id="opt-task-e",
            attempt_id="opt-attempt-e",
            logical_name="opt-e.gjf",
            method_binding=_METHOD,
        )
        negative_opt_chain = self._persisted_gaussian_evidence(
            initial,
            plan,
            prepared,
            prepared_bytes,
            frequencies=(),
            optimization_spans=(),
            stationary_spans=(),
            program_status="error-termination",
        )
        negative_opt_input = self._opt_input(
            member_id, plan, prepared, prepared_bytes, negative_opt_chain
        )
        negative_opt_authority = validate_negative_optimization_authority(
            initial,
            member_id,
            **{
                key: value
                for key, value in negative_opt_input.items()
                if key != "member_id"
            },
        )

        freq_inputs: dict[str, dict[str, object]] = {}
        freq_chains: dict[str, dict[str, object]] = {}
        for role, frequencies, energy in (
            ("a", (25.0, 100.0, 250.0), -100.0),
            ("c", (-25.0, 100.0, 250.0), -99.98),
            ("d", (25.0, 100.0, 250.0), -99.99),
        ):
            member_id = roles[role]
            plan, prepared, prepared_bytes = build_dft_stage(
                initial,
                member_id,
                stage="freq",
                calculation_plan_id=f"freq-plan-{role}",
                calculation_plan_revision=1,
                task_id=f"freq-task-{role}",
                attempt_id=f"freq-attempt-{role}",
                logical_name=f"freq-{role}.gjf",
                method_binding=_METHOD,
                optimization_geometry_authority=opt_authorities[role],
            )
            chain = self._persisted_gaussian_evidence(
                initial,
                plan,
                prepared,
                prepared_bytes,
                frequencies=frequencies,
                optimization_spans=(),
                stationary_spans=(),
                energy=energy,
            )
            freq_inputs[role] = self._freq_input(
                member_id,
                opt_inputs[role],
                plan,
                prepared,
                prepared_bytes,
                chain,
            )
            freq_chains[role] = chain

        negative_freq_authority = validate_negative_frequency_authority(
            initial,
            roles["c"],
            **{
                key: value
                for key, value in freq_inputs["c"].items()
                if key != "member_id"
            },
        )
        positive_opt = tuple(opt_inputs[role] for role in ("a", "b", "c", "d"))
        positive_freq = tuple(freq_inputs[role] for role in ("a", "d"))
        refined = build_refined_conformer_ensemble(
            initial,
            profile,
            positive_optimization_inputs=positive_opt,
            negative_optimization_inputs=(negative_opt_input,),
            positive_frequency_inputs=positive_freq,
            negative_frequency_inputs=(freq_inputs["c"],),
        )
        values.update(
            roles=roles,
            opt_inputs=opt_inputs,
            opt_authorities=opt_authorities,
            opt_chains=opt_chains,
            negative_opt_input=negative_opt_input,
            negative_opt_authority=negative_opt_authority,
            freq_inputs=freq_inputs,
            freq_chains=freq_chains,
            negative_freq_authority=negative_freq_authority,
            positive_opt_inputs=positive_opt,
            positive_freq_inputs=positive_freq,
            refined=refined,
        )
        return values

    @staticmethod
    def _thermo_inputs(values: dict[str, object]) -> tuple[dict[str, object], ...]:
        roles = values["roles"]
        chains = values["freq_chains"]
        by_member = {
            roles[role]: {
                "member_id": roles[role],
                "source_result": chains[role]["parse_outcome"],
                "raw_gaussian_bytes": chains[role]["raw_gaussian_bytes"],
                "method_binding": _METHOD,
                "degeneracy": 1,
                "degeneracy_rationale": "explicit reviewed unique-state count",
            }
            for role in ("a", "d")
        }
        return tuple(
            by_member[member_id]
            for member_id in values["refined"].thermodynamic_eligible_members
        )

    def _assert_initial_and_refinement_chain(self, values: dict[str, object]) -> None:
        profile = values["profile"]
        capture = values["xtb_capture"]
        handoff = values["handoff"]
        initial = values["initial"]
        refined = values["refined"]
        roles = values["roles"]
        optimized = next(
            item for item in capture.artifacts if item.logical_role == "optimized-geometry"
        )
        self.assertEqual(optimized.content, handoff_fixtures.SEED)
        self.assertEqual(
            values["capture_authority"]["job_authority_id"], capture.job_authority_id
        )
        self.assertEqual(
            values["terminal_authority"]["job_authority_id"], capture.job_authority_id
        )
        self.assertEqual(
            handoff.optimized_geometry_sha256,
            sha256(handoff_fixtures.SEED).hexdigest(),
        )
        self.assertEqual(handoff.crest_exact_input_sha256, handoff.optimized_geometry_sha256)
        self.assertEqual(handoff.sampling_profile_id, profile.sampling_profile_id)
        self.assertEqual(len(values["observations"]), 5)
        self.assertEqual(len(initial.members), 5)
        self.assertEqual(initial.thermodynamic_eligible_members, ())
        self.assertEqual(initial.ts_seed_members, ())
        self.assertEqual(refined.revision, initial.revision + 1)
        self.assertEqual(
            refined.supersedes_conformer_ensemble_id,
            initial.conformer_ensemble_id,
        )
        self.assertEqual(
            refined.thermodynamic_eligible_members,
            tuple(
                member["member_id"]
                for member in refined.members
                if member["member_id"] in {roles["a"], roles["d"]}
            ),
        )
        self.assertEqual(refined.ts_seed_members, (roles["d"],))
        by_id = {member["member_id"]: member for member in refined.members}
        self.assertEqual(
            by_id[roles["b"]]["post_dft_status"],
            "deduplicated_after_optimization",
        )
        self.assertEqual(
            by_id[roles["b"]]["post_dft_duplicate_of_member_id"], roles["a"]
        )
        self.assertEqual(by_id[roles["c"]]["post_dft_status"], "frequency_failed")
        self.assertEqual(by_id[roles["e"]]["post_dft_status"], "optimization_failed")
        rebuilt = build_refined_conformer_ensemble(
            initial,
            profile,
            positive_optimization_inputs=tuple(reversed(values["positive_opt_inputs"])),
            negative_optimization_inputs=(values["negative_opt_input"],),
            positive_frequency_inputs=tuple(reversed(values["positive_freq_inputs"])),
            negative_frequency_inputs=(values["freq_inputs"]["c"],),
        )
        self.assertEqual(rebuilt, refined)

    def _assert_prethermochemistry_adversarial(self, values: dict[str, object]) -> None:
        fixture = self.handoff_fixture
        profile = values["profile"]
        xtb_snapshot = values["xtb_snapshot"]
        xtb_capture = values["xtb_capture"]
        crest_spec = values["crest_spec"]
        handoff = values["handoff"]
        crest_snapshot = values["crest_snapshot"]
        artifact = values["crest_artifact"]
        raw = values["crest_raw"]
        initial = values["initial"]
        wrong_profile = fixture.profile(c_o_bond_order=2.0)

        for index, (scheduler_states, attempt_state) in enumerate(
            (
                ((), core.AttemptState.SUBMITTED),
                (("running",), core.AttemptState.RUNNING),
                (("terminal",), core.AttemptState.FAILED),
            ),
            start=1,
        ):
            snapshot, capture = fixture.capture_xtb(
                attempt_id=f"attempt-bad-state-{index}",
                scheduler_states=scheduler_states,
                attempt_state=attempt_state,
                scheduler_job_id=f"bad-{index}.server",
            )
            with self.subTest(attempt_state=attempt_state), self.assertRaises(
                execution.ExecutionValueError
            ):
                fixture.handoff(snapshot, capture)

        early_snapshot, early_capture = fixture.capture_xtb(
            attempt_id="attempt-early-capture",
            capture_before_scheduler=True,
            scheduler_job_id="early.server",
        )
        with self.assertRaises(execution.ExecutionValueError):
            fixture.handoff(early_snapshot, early_capture)

        foreign_snapshot, foreign_capture = fixture.capture_xtb(
            attempt_id="attempt-foreign",
            scheduler_job_id="foreign.server",
        )
        with self.assertRaises(execution.ExecutionValueError):
            fixture.handoff(xtb_snapshot, foreign_capture)
        foreign_handoff = copy(handoff)
        object.__setattr__(
            foreign_handoff,
            "xtb_program_execution_snapshot_id",
            foreign_snapshot.program_execution_snapshot_id,
        )
        wrong_seed_spec = fixture.crest_spec(
            profile,
            seed=b"3\nwrong\nC 0 0 0\nO 1.2 0 0\nH 2.1 0 0\n",
        )
        with self.assertRaises(execution.ExecutionValueError):
            fixture.handoff(
                xtb_snapshot,
                xtb_capture,
                profile=profile,
                crest_spec=wrong_seed_spec,
            )

        ingest_kwargs = {
            "profile": profile,
            "program_execution_snapshot": crest_snapshot,
            "core_store": fixture.store,
            "preoptimization_handoff": handoff,
            "xtb_program_execution_snapshot": xtb_snapshot,
            "xtb_program_transport_store": fixture.program_transport_store,
            "xtb_validation_driver": self._validation_driver(),
            "xtb_output_capture": xtb_capture,
            "artifact_binding": artifact,
            "artifact_bytes": raw,
            "descriptors_by_member_index": None,
        }
        with self.assertRaises(ConformerError):
            _ingest_preoptimized_crest_conformers_xyz(
                **{**ingest_kwargs, "profile": wrong_profile}
            )
        with self.assertRaises((ConformerError, execution.ExecutionValueError)):
            _ingest_preoptimized_crest_conformers_xyz(
                **{**ingest_kwargs, "preoptimization_handoff": foreign_handoff}
            )
        tampered_spec = copy(crest_snapshot.program_execution_spec)
        object.__setattr__(
            tampered_spec,
            "program_execution_spec_id",
            "spliced-spec",
        )
        tampered_snapshot = copy(crest_snapshot)
        object.__setattr__(tampered_snapshot, "program_execution_spec", tampered_spec)
        with self.assertRaises((ConformerError, execution.ExecutionValueError)):
            _ingest_preoptimized_crest_conformers_xyz(
                **{**ingest_kwargs, "program_execution_snapshot": tampered_snapshot}
            )
        with self.assertRaises(ConformerError):
            _ingest_preoptimized_crest_conformers_xyz(
                **{
                    **ingest_kwargs,
                    "artifact_binding": replace(
                        artifact,
                        program_execution_snapshot_id="foreign-snapshot",
                    ),
                }
            )
        for changed in (
            {"sha256": "0" * 64},
            {"size_bytes": len(raw) + 1},
        ):
            with self.assertRaises(ConformerError):
                _ingest_preoptimized_crest_conformers_xyz(
                    **{
                        **ingest_kwargs,
                        "artifact_binding": replace(artifact, **changed),
                    }
                )

        wrong_initial = build_conformer_ensemble(
            project_id=initial.project_id,
            calculation_plan_id="wrong-initial-plan",
            calculation_plan_revision=initial.calculation_plan_revision,
            profile=profile,
            observations=values["observations"],
        )
        with self.assertRaises(RefinementError):
            build_refined_conformer_ensemble(
                wrong_initial,
                profile,
                positive_optimization_inputs=values["positive_opt_inputs"],
                negative_optimization_inputs=(values["negative_opt_input"],),
                positive_frequency_inputs=values["positive_freq_inputs"],
                negative_frequency_inputs=(values["freq_inputs"]["c"],),
            )
        values["wrong_initial"] = wrong_initial

    def _assert_thermochemistry_and_final(
        self,
        values: dict[str, object],
        member_inputs: tuple[dict[str, object], ...],
    ) -> None:
        refined = values["refined"]
        initial = values["initial"]
        roles = values["roles"]
        thermodynamic = _build_thermodynamic_ensemble(
            refined,
            initial,
            member_inputs,
            _THERMOCHEMISTRY_POLICY,
        )
        replayed = _build_thermodynamic_ensemble(
            refined,
            initial,
            tuple(reversed(member_inputs)),
            _THERMOCHEMISTRY_POLICY,
        )
        self.assertEqual(replayed, thermodynamic)
        self.assertEqual(
            thermodynamic.source_member_ids,
            refined.thermodynamic_eligible_members,
        )
        closed_refined, closed_thermo, ts_projection = (
            _validate_final_ensemble_integration(refined, thermodynamic, predecessor_ensemble=initial)
        )
        self.assertIs(closed_refined, refined)
        self.assertIs(closed_thermo, thermodynamic)
        self.assertEqual(ts_projection, (roles["d"],))
        population_leader = max(
            thermodynamic.member_observations,
            key=lambda item: item["normalized_population"],
        )["member_id"]
        self.assertEqual(population_leader, roles["a"])
        self.assertNotEqual(ts_projection, (population_leader,))

        with self.assertRaises(ThermochemistryError):
            _build_thermodynamic_ensemble(
                refined,
                values["wrong_initial"],
                member_inputs,
                _THERMOCHEMISTRY_POLICY,
            )
        for supplied in (
            member_inputs[:1],
            (member_inputs[0], member_inputs[0]),
            (next(item for item in member_inputs if item["member_id"] == roles["d"]),),
            (
                *member_inputs,
                {**member_inputs[0], "member_id": roles["b"]},
            ),
            (
                *member_inputs,
                {**member_inputs[0], "member_id": roles["c"]},
            ),
            (
                *member_inputs,
                {**member_inputs[0], "member_id": roles["e"]},
            ),
        ):
            with self.assertRaises(ThermochemistryError):
                _build_thermodynamic_ensemble(
                    refined,
                    initial,
                    supplied,
                    _THERMOCHEMISTRY_POLICY,
                )

        stale_refined = copy(refined)
        object.__setattr__(stale_refined, "conformer_ensemble_id", "stale-refined")
        with self.assertRaises(ThermochemistryError):
            _build_thermodynamic_ensemble(
                stale_refined,
                initial,
                member_inputs,
                _THERMOCHEMISTRY_POLICY,
            )
        with self.assertRaises(_FinalIntegrationError):
            _validate_final_ensemble_integration(stale_refined, thermodynamic, predecessor_ensemble=initial)

        wrong_provenance = final_fixtures._replace_provenance(
            thermodynamic,
            roles["a"],
            lambda provenance: {
                **provenance,
                "source_result_id": "foreign-result",
            },
        )
        with self.assertRaises(_FinalIntegrationError):
            _validate_final_ensemble_integration(refined, wrong_provenance, predecessor_ensemble=initial)

        tampered_thermo = copy(thermodynamic)
        object.__setattr__(
            tampered_thermo,
            "thermodynamic_ensemble_id",
            "tampered-thermodynamic",
        )
        with self.assertRaises(_FinalIntegrationError):
            _validate_final_ensemble_integration(refined, tampered_thermo, predecessor_ensemble=initial)

        forged_refined = final_fixtures._clone_conformer(
            refined,
            values["profile"],
            calculation_plan_id="foreign-refined-plan",
        )
        rebound_thermo = final_fixtures._rebind_thermodynamic(
            thermodynamic,
            forged_refined,
        )
        with self.assertRaises(_FinalIntegrationError):
            _validate_final_ensemble_integration(forged_refined, rebound_thermo, predecessor_ensemble=initial)

    def test_real_offline_chain_and_mandatory_splice_matrix(self) -> None:
        values = self._refined_chain()
        self._assert_initial_and_refinement_chain(values)
        self._assert_prethermochemistry_adversarial(values)
        member_inputs = self._thermo_inputs(values)
        if not _goodvibes_430_available():
            with self.assertRaisesRegex(
                FunctionalKernelError,
                "GoodVibes 4.3.0 is unavailable",
            ):
                _build_thermodynamic_ensemble(
                    values["refined"],
                    values["initial"],
                    member_inputs,
                    _THERMOCHEMISTRY_POLICY,
                )
            return
        self._assert_thermochemistry_and_final(values, member_inputs)


if __name__ == "__main__":
    unittest.main()
