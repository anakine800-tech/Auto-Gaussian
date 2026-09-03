"""Offline adversarial tests for V31 functional-kernel thermochemistry."""

from __future__ import annotations

import ast
import copy
from dataclasses import is_dataclass
from hashlib import sha256
import math
from pathlib import Path
from unittest.mock import patch
import unittest

import auto_g16.thermochemistry as thermochemistry
from auto_g16.conformer.models import (
    ConformerEnsemble,
    SamplingProfile,
    _plain_value as conformer_plain,
    _payload_sha256 as conformer_hash,
)
from auto_g16.conformer.refinement_authority import _source
from auto_g16.result import OutputArtifact, OutputEnvelope, ParseOutcome
from auto_g16.thermochemistry._gaussian_thermo_facts import (
    GaussianThermoFactsError,
    extract_gaussian_thermo_facts,
)
from auto_g16.thermochemistry._service import ThermochemistryError, _build_thermodynamic_ensemble
from auto_g16.thermochemistry.models import ThermodynamicEnsemble, _payload_sha256
from tests.v3.scientific_validation._fixtures import attributed_facts
from tests.v31.conformer.test_core import ConformerCoreTests


ROOT = Path(__file__).parents[3]


def _fake_kernels():
    gas_constant = 8.3144621

    def trans_energy(temperature):
        return 1.5 * gas_constant * temperature

    def rot_energy(temperature, monatomic=False, linear=False):
        assert not monatomic and not linear
        return 1.5 * gas_constant * temperature

    def vib_energy(temperature, frequencies, scale=1.0, fract=None):
        del temperature, fract
        return math.fsum(frequencies) * scale

    def zpe(frequencies, scale=1.0, fract=None):
        del fract
        return 0.5 * math.fsum(frequencies) * scale

    def trans_entropy(mass, concentration, temperature, solvent=None):
        assert solvent is None
        return math.log(mass * temperature / concentration)

    def electronic_entropy(multiplicity):
        return gas_constant * math.log(multiplicity)

    def rotational_entropy(temperature, rotemps, symmno=1, monatomic=False, linear=False):
        assert not monatomic and not linear
        return math.log(temperature ** 3 / math.prod(rotemps) / symmno)

    def rrho_entropy(temperature, frequencies, scale=1.0, fract=None):
        del temperature, fract
        return [scale / frequency for frequency in frequencies]

    def freerot_entropy(temperature, frequencies, bav=1e-44, scale=1.0, fract=None):
        del temperature, bav, fract
        return [2.0 * scale / frequency for frequency in frequencies]

    def qrrho_energy(temperature, frequencies, scale=1.0):
        del temperature
        return [frequency * scale for frequency in frequencies]

    def damp(frequencies, cutoff):
        return [1.0 / (1.0 + (cutoff / frequency) ** 4) for frequency in frequencies]

    return ({
        "calc_translational_energy": trans_energy,
        "calc_rotational_energy": rot_energy,
        "calc_vibrational_energy": vib_energy,
        "calc_zeropoint_energy": zpe,
        "calc_translational_entropy": trans_entropy,
        "calc_electronic_entropy": electronic_entropy,
        "calc_rotational_entropy": rotational_entropy,
        "calc_rrho_entropy": rrho_entropy,
        "calc_freerot_entropy": freerot_entropy,
        "calc_qRRHO_energy": qrrho_energy,
        "calc_damp": damp,
    }, {"GAS_CONSTANT": gas_constant, "J_TO_AU": 2625499.919544, "GRIMME_BAV": 1e-44})


class ThermochemistryCoreTests(unittest.TestCase):
    def setUp(self) -> None:
        fixture = ConformerCoreTests()
        self.fixture = fixture
        self.profile = fixture.profile()
        observations = [
            fixture.observation(self.profile, member_id, member_index=index)
            for index, member_id in enumerate(("member-a", "member-b"))
        ]
        self.prior = fixture.ensemble(self.profile, observations)
        self.method = {
            "program": "gaussian16", "method": "RB3LYP", "basis": "6-31G(d)",
            "dispersion": "none", "solvent": "gas", "reference": "restricted_closed_shell",
            "charge": 0, "multiplicity": 1, "integration_grid": "ultrafine",
            "scf_policy": "tight", "route_contract_version": "auto_g16_v31_conformer_dft_route_1",
        }
        self.policy = {
            "adapter_identity": "auto-g16-goodvibes-functional-kernel-adapter",
            "adapter_version": 2,
            "engine_artifact": "goodvibes-4.3.0-py3-none-any.whl",
            "engine_artifact_sha256": "06476db73ee456c1fc941590374f2a30182baaf043f6b60dbef85ee77db93997",
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
        self.raw_by_member = {}
        self.result_by_member = {}
        self.minimum_by_member = {}
        for index, member_id in enumerate(("member-a", "member-b")):
            raw, result = self._result(member_id, energy=-100.0 + index * 0.01)
            minimum, optimization = self._minimum(member_id, result)
            self.raw_by_member[member_id] = raw
            self.result_by_member[member_id] = result
            self.minimum_by_member[member_id] = (minimum, optimization)
        members = []
        for member in self.prior.members:
            minimum, optimization = self.minimum_by_member[member["member_id"]]
            members.append({
                **dict(member),
                "post_dft_status": "validated_minimum",
                "post_dft_duplicate_of_member_id": None,
                "optimization_geometry_authority": optimization,
                "negative_optimization_authority": None,
                "two_stage_minimum_authority": minimum,
                "negative_frequency_authority": None,
            })
        self.refined = self._refined(members, ("member-a", "member-b"))

    def _raw(self, *, mass=True, rotations="three", symmetry="one", point_group="C2"):
        lines = []
        if mass:
            lines.append(b" Molecular mass:    44.00000 amu.\n")
        if symmetry == "one":
            lines.append(b" Rotational symmetry number  2.\n")
        elif symmetry == "conflict":
            lines.extend((b" Rotational symmetry number  1.\n", b" Rotational symmetry number  2.\n"))
        if point_group:
            lines.append(f" Full point group                 {point_group}     NOp   2\n".encode())
        if rotations == "three":
            lines.append(b" Rotational temperatures (Kelvin)      3.0     2.0     1.0\n")
        elif rotations == "two":
            lines.append(b" Rotational temperatures (Kelvin)      3.0     2.0\n")
        selected = b"".join(lines)
        return selected + b" " * (900 - len(selected)) + b" OUTSIDE Rotational symmetry number  99.\n".ljust(100, b" ")

    def _result(self, member_id, *, energy, raw=None):
        selected_raw = self._raw() if raw is None else raw
        artifact = OutputArtifact(
            artifact_kind="gaussian-log", logical_name=f"{member_id}.log",
            sha256=sha256(selected_raw).hexdigest(), size_bytes=len(selected_raw),
        )
        envelope = OutputEnvelope(
            attempt_id=f"attempt-{member_id}", input_binding_observation_id=f"input-{member_id}",
            execution_snapshot_id=f"snapshot-{member_id}", capture_source_id=f"capture-{member_id}",
            capture_sequence=1, capture_status="captured", capture_completeness="complete",
            artifacts=(artifact,), capture_manifest_sha256="c" * 64,
            captured_at_utc="2026-09-03T00:00:00Z",
        )
        facts = attributed_facts(
            envelope, frequencies=(25.0, 100.0, 250.0, 400.0, 600.0, 800.0),
            atom_numbers=(6, 6, 8, 1), optimization_spans=(), stationary_spans=(),
        )
        source = facts["source_artifact"]
        facts["scf_calculation_count"] = 1
        facts["scf_calculations"] = ({
            "energy_hartree": float(energy),
            "source_span": {**source, "start": 70, "end": 80},
        },)
        facts["final_energy_hartree"] = float(energy)
        return selected_raw, ParseOutcome(
            attempt_id=envelope.attempt_id, envelope_observation_id=envelope.observation_id,
            parser_name="auto-g16-v3-gaussian-job", parser_version="1.0.0",
            result_kind="gaussian-job-facts", parse_status="parsed", facts=facts,
        )

    def _minimum(
        self,
        member_id,
        result,
        *,
        source_ensemble=None,
        job_section=None,
        result_id=None,
        result_hash=None,
    ):
        ensemble = self.prior if source_ensemble is None else source_ensemble
        member = next(item for item in ensemble.members if item["member_id"] == member_id)
        source = _source(ensemble, member)
        method_id = conformer_hash({
            "domain": "v31-conformer-dft-method/1", "method": self.method,
            "reference_family": "restricted",
        })
        optimization_payload = {
            "authority_schema": "v31-conformer-optimization-geometry-authority/1",
            "source": source, "method_id": method_id,
            "calculation_plan": {"calculation_plan_id": f"opt-{member_id}"},
            "prepared_input": {"sha256": "a" * 64},
            "result": {"result_id": f"opt-result-{member_id}"},
            "selected_geometry": {"atoms": ()}, "recovered_atom_map": (),
            "v30_outcome": {"classification": "INCOMPLETE"},
        }
        optimization = {
            **optimization_payload,
            "optimization_geometry_authority_id": "v31-opt-geometry-authority-" + _payload_sha256({
                "domain": "v31-opt-geometry-authority", "payload": optimization_payload,
            }),
        }
        facts = result.facts
        frequency_result = {
            "result_id": result.result_id if result_id is None else result_id,
            "result_payload_sha256": _payload_sha256(result.payload()) if result_hash is None else result_hash,
            "source_artifact": facts["source_artifact"],
            "job_section": facts["job_section"] if job_section is None else job_section,
            "frequency_blocks": facts["frequency_blocks"],
            "frequencies_cm1": facts["frequencies_cm-1"],
            "mode_count": facts["frequency_count"],
            "v30_outcome": {"classification": "INCOMPLETE", "reason_code": "incomplete-marker-pair"},
        }
        payload = {
            "authority_schema": "v31-conformer-two-stage-minimum-authority/1",
            "source": source, "method_id": method_id, "optimization": optimization,
            "frequency": {
                "calculation_plan": {"calculation_plan_id": f"freq-{member_id}", "revision": 1, "intent_sha256": "d" * 64},
                "prepared_input": {"sha256": "e" * 64}, "result": frequency_result,
            },
            "classification": "VALIDATED_TWO_STAGE_MINIMUM",
        }
        return ({
            **payload,
            "two_stage_minimum_authority_id": "v31-two-stage-minimum-authority-" + _payload_sha256({
                "domain": "v31-two-stage-minimum-authority", "payload": payload,
            }),
        }, optimization)

    def _refined(self, members, eligible, *, profile=None, predecessor=None):
        selected_profile = self.profile if profile is None else profile
        selected_predecessor = self.prior if predecessor is None else predecessor
        return ConformerEnsemble._create(
            project_id=self.prior.project_id,
            calculation_plan_id=self.prior.calculation_plan_id,
            calculation_plan_revision=self.prior.calculation_plan_revision,
            profile=selected_profile,
            sampling_observations=self.prior.sampling_observations,
            audit_evidence=self.prior.audit_evidence,
            negative_evidence=self.prior.negative_evidence,
            dedup_decisions=self.prior.dedup_decisions,
            independent_review_blockers=(), clusters=self.prior.clusters,
            members=members, coverage=self.prior.coverage,
            thermodynamic_eligible_members=eligible, ts_seed_members=(),
            revision=selected_predecessor.revision + 1,
            supersedes_conformer_ensemble_id=selected_predecessor.conformer_ensemble_id,
        )

    def _profile_variant(self, *, species=None, stereochemistry=None, crest=None):
        profile = self.profile
        return SamplingProfile._create(
            revision=profile.revision,
            supersedes_sampling_profile_id=profile.supersedes_sampling_profile_id,
            species_binding=profile.species_binding if species is None else species,
            stereochemistry_binding=(
                profile.stereochemistry_binding
                if stereochemistry is None
                else stereochemistry
            ),
            bond_change_policy=profile.bond_change_policy,
            geometry_legality_policy=profile.geometry_legality_policy,
            crest_imtd_gc_profile=profile.crest_imtd_gc_profile if crest is None else crest,
            rmsd_policy=profile.rmsd_policy,
            clustering_policy=profile.clustering_policy,
            descriptor_policy=profile.descriptor_policy,
            coverage_policy=profile.coverage_policy,
            thermodynamic_eligibility_policy=profile.thermodynamic_eligibility_policy,
            ts_seed_projection_policy=profile.ts_seed_projection_policy,
        )

    def _sampling_ensemble(self, profile=None, *, translate_x=0.0):
        selected_profile = self.profile if profile is None else profile
        observations = []
        for index, member_id in enumerate(("member-a", "member-b")):
            observation = self.fixture.observation(
                selected_profile, member_id, member_index=index
            )
            if translate_x:
                for point in observation["coordinates_angstrom"]:
                    point[0] += translate_x
            observation["stereochemistry_binding"] = conformer_plain(
                selected_profile.stereochemistry_binding
            )
            observations.append(observation)
        return self.fixture.ensemble(selected_profile, observations)

    def _ensemble_from_profile(self, profile):
        return ConformerEnsemble._create(
            project_id=self.prior.project_id,
            calculation_plan_id=self.prior.calculation_plan_id,
            calculation_plan_revision=self.prior.calculation_plan_revision,
            profile=profile,
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

    def _members_with_authority(self, member_id, minimum, optimization):
        return [
            {
                **dict(member),
                **(
                    {
                        "optimization_geometry_authority": optimization,
                        "two_stage_minimum_authority": minimum,
                    }
                    if member["member_id"] == member_id
                    else {}
                ),
            }
            for member in self.refined.members
        ]

    def inputs(self, *, degeneracy_b=1):
        return [{
            "member_id": member_id,
            "source_result": self.result_by_member[member_id],
            "raw_gaussian_bytes": self.raw_by_member[member_id],
            "method_binding": copy.deepcopy(self.method),
            "degeneracy": degeneracy_b if member_id == "member-b" else 1,
            "degeneracy_rationale": "explicit reviewed unique-state count",
        } for member_id in ("member-a", "member-b")]

    def build(self, inputs=None, policy=None, ensemble=None, predecessor=None):
        with patch(
            "auto_g16.thermochemistry._goodvibes._load_goodvibes_kernels",
            side_effect=_fake_kernels,
        ):
            return _build_thermodynamic_ensemble(
                ensemble or self.refined,
                predecessor or self.prior,
                self.inputs() if inputs is None else inputs,
                self.policy if policy is None else policy,
            )

    def replace_member(self, member_id, **changes):
        members = []
        for member in self.refined.members:
            members.append({**dict(member), **changes} if member["member_id"] == member_id else dict(member))
        return self._refined(members, self.refined.thermodynamic_eligible_members)

    def test_01_public_surface_has_one_record(self):
        self.assertEqual(thermochemistry.__all__, ["ThermodynamicEnsemble"])
        self.assertTrue(is_dataclass(ThermodynamicEnsemble))

    def test_02_deterministic_ensemble_identity(self):
        first = self.build()
        second = self.build(list(reversed(self.inputs())))
        self.assertEqual(first, second)
        self.assertEqual(first.thermodynamic_ensemble_id, second.thermodynamic_ensemble_id)

    def test_03_wrong_raw_sha_rejects(self):
        inputs = self.inputs()
        inputs[0]["raw_gaussian_bytes"] = inputs[0]["raw_gaussian_bytes"][:-1] + b"X"
        with self.assertRaisesRegex(GaussianThermoFactsError, "SHA-256"):
            self.build(inputs)

    def test_04_wrong_raw_size_rejects(self):
        inputs = self.inputs()
        inputs[0]["raw_gaussian_bytes"] += b"X"
        with self.assertRaisesRegex(GaussianThermoFactsError, "size"):
            self.build(inputs)

    def test_05_wrong_job_section_rejects(self):
        result = self.result_by_member["member-a"]
        wrong = {**result.facts["job_section"], "start": 1}
        minimum, _optimization = self._minimum("member-a", result, job_section=wrong)
        with self.assertRaisesRegex(GaussianThermoFactsError, "job section differs"):
            extract_gaussian_thermo_facts(
                raw_gaussian_bytes=self.raw_by_member["member-a"], source_result=result,
                minimum_authority=minimum,
            )

    def test_06_stale_result_lineage_rejects(self):
        result = self.result_by_member["member-a"]
        minimum, _optimization = self._minimum("member-a", result, result_hash="0" * 64)
        with self.assertRaisesRegex(GaussianThermoFactsError, "payload differs"):
            extract_gaussian_thermo_facts(
                raw_gaussian_bytes=self.raw_by_member["member-a"], source_result=result,
                minimum_authority=minimum,
            )

    def test_07_stale_minimum_identity_rejects(self):
        minimum = dict(self.minimum_by_member["member-a"][0])
        minimum["two_stage_minimum_authority_id"] = "stale"
        with self.assertRaisesRegex(GaussianThermoFactsError, "identity is stale"):
            extract_gaussian_thermo_facts(
                raw_gaussian_bytes=self.raw_by_member["member-a"],
                source_result=self.result_by_member["member-a"], minimum_authority=minimum,
            )

    def test_08_missing_mass_rejects(self):
        raw = self._raw(mass=False)
        result_raw, result = self._result("member-a", energy=-100.0, raw=raw)
        minimum, _optimization = self._minimum("member-a", result)
        with self.assertRaisesRegex(GaussianThermoFactsError, "one molecular mass"):
            extract_gaussian_thermo_facts(raw_gaussian_bytes=result_raw, source_result=result, minimum_authority=minimum)

    def test_09_missing_rotational_temperatures_rejects(self):
        raw = self._raw(rotations="none")
        result_raw, result = self._result("member-a", energy=-100.0, raw=raw)
        minimum, _optimization = self._minimum("member-a", result)
        with self.assertRaisesRegex(GaussianThermoFactsError, "one three-value"):
            extract_gaussian_thermo_facts(raw_gaussian_bytes=result_raw, source_result=result, minimum_authority=minimum)

    def test_10_not_exactly_three_rotational_temperatures_rejects(self):
        raw = self._raw(rotations="two")
        result_raw, result = self._result("member-a", energy=-100.0, raw=raw)
        minimum, _optimization = self._minimum("member-a", result)
        with self.assertRaisesRegex(GaussianThermoFactsError, "malformed"):
            extract_gaussian_thermo_facts(raw_gaussian_bytes=result_raw, source_result=result, minimum_authority=minimum)

    def test_11_missing_symmetry_rejects(self):
        raw = self._raw(symmetry="none")
        result_raw, result = self._result("member-a", energy=-100.0, raw=raw)
        minimum, _optimization = self._minimum("member-a", result)
        with self.assertRaisesRegex(GaussianThermoFactsError, "lacks a rotational symmetry"):
            extract_gaussian_thermo_facts(raw_gaussian_bytes=result_raw, source_result=result, minimum_authority=minimum)

    def test_12_conflicting_symmetry_rejects(self):
        raw = self._raw(symmetry="conflict")
        result_raw, result = self._result("member-a", energy=-100.0, raw=raw)
        minimum, _optimization = self._minimum("member-a", result)
        with self.assertRaisesRegex(GaussianThermoFactsError, "conflicting symmetry"):
            extract_gaussian_thermo_facts(raw_gaussian_bytes=result_raw, source_result=result, minimum_authority=minimum)

    def test_13_linear_molecule_rejects(self):
        ensemble = self.replace_member("member-a", coordinates_angstrom=((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0), (3.0, 0.0, 0.0)))
        with self.assertRaisesRegex(ThermochemistryError, "linear"):
            self.build(ensemble=ensemble)

    def test_14_open_shell_rejects(self):
        method_inputs = self.inputs()
        method_inputs[0]["method_binding"]["reference"] = "unrestricted"
        method_inputs[0]["method_binding"]["method"] = "UB3LYP"
        with self.assertRaisesRegex(ThermochemistryError, "restricted"):
            self.build(method_inputs)

    def test_15_mixed_method_rejects(self):
        inputs = self.inputs()
        inputs[1]["method_binding"]["basis"] = "def2-SVP"
        with self.assertRaisesRegex(ThermochemistryError, "differs from current minimum"):
            self.build(inputs)

    def test_16_mixed_temperature_is_unrepresentable_and_rejects(self):
        inputs = self.inputs()
        inputs[0]["temperature_k"] = 310.0
        with self.assertRaisesRegex(ThermochemistryError, "fields are not exact"):
            self.build(inputs)

    def test_17_mixed_standard_state_is_unrepresentable_and_rejects(self):
        inputs = self.inputs()
        inputs[1]["standard_state"] = "1M"
        with self.assertRaisesRegex(ThermochemistryError, "fields are not exact"):
            self.build(inputs)

    def test_18_non_eligible_member_rejects(self):
        with self.assertRaisesRegex(ThermochemistryError, "complete thermodynamic eligible set"):
            self.build(self.inputs()[:1])

    def test_19_duplicate_member_input_rejects(self):
        inputs = self.inputs()
        inputs[1]["member_id"] = "member-a"
        with self.assertRaisesRegex(ThermochemistryError, "duplicate member input"):
            self.build(inputs)

    def test_20_negative_frequency_member_cannot_enter(self):
        ensemble = self.replace_member("member-a", post_dft_status="frequency_failed", negative_frequency_authority={"disposition": "negative"})
        with self.assertRaisesRegex(ThermochemistryError, "current validated minimum"):
            self.build(ensemble=ensemble)

    def test_21_duplicate_member_cannot_enter(self):
        ensemble = self.replace_member("member-a", post_dft_status="deduplicated_after_optimization", post_dft_duplicate_of_member_id="member-b")
        with self.assertRaisesRegex(ThermochemistryError, "current validated minimum"):
            self.build(ensemble=ensemble)

    def test_22_degeneracy_weighting_and_population_normalization(self):
        result = self.build(self.inputs(degeneracy_b=3))
        populations = {item["member_id"]: item["normalized_population"] for item in result.member_observations}
        self.assertAlmostEqual(math.fsum(populations.values()), 1.0, places=14)
        self.assertGreater(populations["member-a"], populations["member-b"])
        self.assertEqual(result.population_normalization["status"], "normalized")

    def test_23_invalid_degeneracy_rejects(self):
        inputs = self.inputs()
        inputs[0]["degeneracy"] = True
        with self.assertRaisesRegex(ThermochemistryError, "positive integer"):
            self.build(inputs)

    def test_24_raw_and_treated_values_are_distinct(self):
        result = self.build()
        member = result.member_observations[0]
        self.assertNotEqual(member["raw_rrho"]["entropy_hartree_per_kelvin"], member["treated_qrrho"]["entropy_hartree_per_kelvin"])
        self.assertIn("zero_point_energy_hartree", member["raw_rrho"])

    def test_25_one_molar_standard_state_is_explicit(self):
        policy = copy.deepcopy(self.policy)
        policy["standard_state"] = "1M"
        result = self.build(policy=policy)
        self.assertEqual(result.standard_state_binding["concentration_mol_per_l"], 1.0)

    def test_26_no_duplicate_conformational_entropy(self):
        result = self.build()
        self.assertNotIn("conformational_entropy", repr(result._identity_payload()))

    def test_27_product_has_no_forbidden_goodvibes_api_or_filesystem_seam(self):
        product = ROOT / "auto_g16/thermochemistry"
        forbidden_text = ("parse_qcdata", "parse_gaussian_thermo", "parse_data", "compute_thermo", "calc_bbe", "ThermoOptions", "tempfile", "monkeypatch")
        forbidden_imports = {"pathlib", "os", "tempfile", "shutil"}
        for path in product.glob("*.py"):
            source = path.read_text(encoding="utf-8")
            self.assertFalse(any(token in source for token in forbidden_text), path)
            tree = ast.parse(source)
            imports = {
                alias.name
                for node in ast.walk(tree)
                if isinstance(node, (ast.Import, ast.ImportFrom))
                for alias in node.names
            }
            self.assertFalse(imports & forbidden_imports, path)

    def test_28_only_allowed_goodvibes_imports_exist(self):
        source = (ROOT / "auto_g16/thermochemistry/_goodvibes.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module == "goodvibes.thermo"
            for alias in node.names
        }
        self.assertEqual(imported, set(_fake_kernels()[0]) | {"GAS_CONSTANT", "J_TO_AU", "GRIMME_BAV"})

    def test_29_outside_section_thermo_markers_do_not_participate(self):
        facts = extract_gaussian_thermo_facts(
            raw_gaussian_bytes=self.raw_by_member["member-a"],
            source_result=self.result_by_member["member-a"],
            minimum_authority=self.minimum_by_member["member-a"][0],
        )
        self.assertEqual(facts["rotational_symmetry_number"], 2)
        self.assertEqual(facts["rotational_symmetry_observation_count"], 1)

    def test_30_non_lf_byte_separators_cannot_create_facts(self):
        raw = self._raw(symmetry="none")
        raw = b"junk\x0bRotational symmetry number  2.\n" + raw
        raw = raw[:1000]
        result_raw, result = self._result("member-a", energy=-100.0, raw=raw)
        minimum, _optimization = self._minimum("member-a", result)
        with self.assertRaisesRegex(GaussianThermoFactsError, "lacks a rotational symmetry"):
            extract_gaussian_thermo_facts(
                raw_gaussian_bytes=result_raw, source_result=result,
                minimum_authority=minimum,
            )

    def test_31_unrelated_predecessor_with_self_consistent_minimum_rejects(self):
        unrelated = self._sampling_ensemble(translate_x=0.5)
        minimum, optimization = self._minimum(
            "member-a",
            self.result_by_member["member-a"],
            source_ensemble=unrelated,
        )
        attacked = self._refined(
            self._members_with_authority("member-a", minimum, optimization),
            self.refined.thermodynamic_eligible_members,
        )
        with self.assertRaisesRegex(ThermochemistryError, "exact immediate predecessor"):
            self.build(ensemble=attacked, predecessor=unrelated)

    def test_32_same_id_different_predecessor_payload_rejects(self):
        drifted = self._sampling_ensemble()
        self.assertEqual(drifted.conformer_ensemble_id, self.prior.conformer_ensemble_id)
        object.__setattr__(
            drifted,
            "coverage",
            {**dict(drifted.coverage), "status": "attacker_payload_drift"},
        )
        with self.assertRaisesRegex(ThermochemistryError, "predecessor ensemble identity is stale"):
            self.build(predecessor=drifted)

    def test_33_sampling_profile_splice_rejects(self):
        crest = conformer_plain(self.profile.crest_imtd_gc_profile)
        crest["budget"]["maximum_observations"] += 1
        spliced_profile = self._profile_variant(crest=crest)
        predecessor = self._sampling_ensemble(spliced_profile)
        refined = self._refined(
            self.refined.members,
            self.refined.thermodynamic_eligible_members,
            predecessor=predecessor,
        )
        with self.assertRaisesRegex(ThermochemistryError, "inherited domain bindings"):
            self.build(ensemble=refined, predecessor=predecessor)

    def test_34_species_binding_splice_rejects(self):
        species = conformer_plain(self.profile.species_binding)
        species["bonds"][0][2] = 2.0
        spliced_profile = self._profile_variant(species=species)
        object.__setattr__(
            spliced_profile, "sampling_profile_id", self.profile.sampling_profile_id
        )
        object.__setattr__(spliced_profile, "payload_sha256", self.profile.payload_sha256)
        predecessor = self._ensemble_from_profile(spliced_profile)
        self.assertEqual(predecessor.sampling_profile_id, self.prior.sampling_profile_id)
        self.assertNotEqual(predecessor.species_binding, self.prior.species_binding)
        refined = self._refined(
            self.refined.members,
            self.refined.thermodynamic_eligible_members,
            predecessor=predecessor,
        )
        with self.assertRaisesRegex(ThermochemistryError, "inherited domain bindings"):
            self.build(ensemble=refined, predecessor=predecessor)

    def test_35_stereochemistry_binding_splice_rejects(self):
        stereochemistry = conformer_plain(self.profile.stereochemistry_binding)
        stereochemistry["assignments"]["map_c2"] = "S"
        spliced_profile = self._profile_variant(stereochemistry=stereochemistry)
        object.__setattr__(
            spliced_profile, "sampling_profile_id", self.profile.sampling_profile_id
        )
        object.__setattr__(spliced_profile, "payload_sha256", self.profile.payload_sha256)
        predecessor = self._ensemble_from_profile(spliced_profile)
        self.assertEqual(predecessor.sampling_profile_id, self.prior.sampling_profile_id)
        self.assertNotEqual(
            predecessor.stereochemistry_binding,
            self.prior.stereochemistry_binding,
        )
        refined = self._refined(
            self.refined.members,
            self.refined.thermodynamic_eligible_members,
            predecessor=predecessor,
        )
        with self.assertRaisesRegex(ThermochemistryError, "inherited domain bindings"):
            self.build(ensemble=refined, predecessor=predecessor)

    def test_36_predecessor_member_payload_and_geometry_splice_rejects(self):
        unrelated = self._sampling_ensemble(translate_x=0.5)
        original_member = next(
            member for member in self.prior.members
            if member["member_id"] == "member-a"
        )
        altered_member = next(
            member for member in unrelated.members
            if member["member_id"] == "member-a"
        )
        original_source = _source(self.prior, original_member)
        altered_source = _source(unrelated, altered_member)
        self.assertNotEqual(
            original_source["member_payload_sha256"],
            altered_source["member_payload_sha256"],
        )
        self.assertNotEqual(
            original_source["source_geometry_sha256"],
            altered_source["source_geometry_sha256"],
        )
        minimum, optimization = self._minimum(
            "member-a",
            self.result_by_member["member-a"],
            source_ensemble=unrelated,
        )
        attacked = self._refined(
            self._members_with_authority("member-a", minimum, optimization),
            self.refined.thermodynamic_eligible_members,
        )
        with self.assertRaisesRegex(ThermochemistryError, "exact immediate predecessor"):
            self.build(ensemble=attacked, predecessor=unrelated)

    def test_37_sibling_member_minimum_cannot_substitute(self):
        minimum, optimization = self.minimum_by_member["member-b"]
        attacked = self._refined(
            self._members_with_authority("member-a", minimum, optimization),
            ("member-a",),
        )
        with self.assertRaisesRegex(ThermochemistryError, "exact predecessor member"):
            self.build(
                inputs=self.inputs()[:1],
                ensemble=attacked,
                predecessor=self.prior,
            )

    def test_38_non_immediate_ancestor_minimum_rejects(self):
        immediate_predecessor = self._refined(
            self.prior.members,
            (),
            predecessor=self.prior,
        )
        refined_revision_three = self._refined(
            self.refined.members,
            self.refined.thermodynamic_eligible_members,
            predecessor=immediate_predecessor,
        )
        with self.assertRaisesRegex(ThermochemistryError, "exact predecessor member"):
            self.build(
                ensemble=refined_revision_three,
                predecessor=immediate_predecessor,
            )

    def test_39_exact_predecessor_chain_succeeds_and_binds_member_identity(self):
        result = self.build(predecessor=self.prior)
        for observation in result.member_observations:
            member_id = observation["member_id"]
            predecessor_member = next(
                member for member in self.prior.members
                if member["member_id"] == member_id
            )
            lineage = observation["source_provenance"]["predecessor_lineage"]
            self.assertEqual(
                lineage["conformer_ensemble_id"],
                self.prior.conformer_ensemble_id,
            )
            self.assertEqual(
                lineage["conformer_ensemble_payload_sha256"],
                self.prior.payload_sha256,
            )
            self.assertEqual(lineage["member_source"], _source(self.prior, predecessor_member))
            self.assertEqual(
                observation["two_stage_minimum_authority_id"],
                self.minimum_by_member[member_id][0]["two_stage_minimum_authority_id"],
            )


if __name__ == "__main__":
    unittest.main()
