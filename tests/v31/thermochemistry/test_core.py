"""Offline contract tests for the V31 thermochemistry foundation."""

from __future__ import annotations

import ast
import copy
from dataclasses import dataclass, is_dataclass
import hashlib
import importlib
import math
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import auto_g16.thermochemistry as thermochemistry
from auto_g16.conformer.models import ConformerEnsemble
from auto_g16.thermochemistry._goodvibes import _THERMO_OPTION_FIELDS, _goodvibes_observation
from auto_g16.thermochemistry._service import (
    _GAS_CONSTANT_HARTREE_PER_MOL_K,
    _build_thermodynamic_ensemble,
)
from auto_g16.thermochemistry.models import ThermodynamicEnsemble


ROOT = Path(__file__).parents[3]


class ThermochemistryFoundationTests(unittest.TestCase):
    def policy(self, *, temperature: float = 298.15, standard_state: str = "1atm") -> dict[str, object]:
        return {
            "engine_identity": "GoodVibes",
            "engine_version": "4.3.0",
            "engine_artifact": "goodvibes-4.3.0-py3-none-any.whl",
            "engine_artifact_sha256": "06476db73ee456c1fc941590374f2a30182baaf043f6b60dbef85ee77db93997",
            "adapter_identity": "auto-g16-goodvibes-programmatic-adapter",
            "adapter_version": "1",
            "temperature_k": temperature,
            "standard_state": standard_state,
            "qrrho_entropy_method": "grimme",
            "qrrho_enthalpy_treatment": "head_gordon",
            "entropy_frequency_cutoff_cm_1": 100.0,
            "enthalpy_frequency_cutoff_cm_1": 100.0,
            "frequency_scaling_factor": 0.99,
            "zpe_scaling_factor": 0.98,
            "symmetry_treatment": "gaussian_output_required",
            "goodvibes_symm": False,
            "moment_of_inertia_treatment": "global_grimme_bav",
            "solvent_free_space_correction": "none",
            "spc_file_discovery": "forbidden",
            "imaginary_frequency_inversion": "forbidden",
            "automatic_scale_factor_lookup": False,
        }

    def method(self, suffix: str = "common") -> dict[str, str]:
        return {
            "geometry_level_identity": f"geometry-{suffix}",
            "frequency_level_identity": f"frequency-{suffix}",
            "electronic_energy_level_identity": f"electronic-{suffix}",
            "electronic_correction_identity": "none",
            "solvent_environment_identity": "gas-phase",
            "reference_state_identity": "closed-shell-singlet",
            "basis_model_identity": f"model-{suffix}",
            "symmetry_number_convention": "gaussian_output_required",
            "result_contract_identity": "closed-synthetic-result-fixture-v1",
        }

    def ensemble(self, member_ids: tuple[str, ...] = ("member-a", "member-b")) -> ConformerEnsemble:
        profile = SimpleNamespace(
            sampling_profile_id="synthetic-profile-id",
            payload_sha256="a" * 64,
            species_binding={"fixture": "synthetic-only"},
            stereochemistry_binding={"fixture": "synthetic-only"},
        )
        return ConformerEnsemble._create(
            project_id="synthetic-project",
            calculation_plan_id="synthetic-plan",
            calculation_plan_revision=1,
            profile=profile,
            sampling_observations=[],
            audit_evidence=[],
            negative_evidence=[],
            dedup_decisions=[],
            independent_review_blockers=[],
            clusters=[],
            members=[{"member_id": member_id, "fixture": "synthetic-only"} for member_id in member_ids],
            coverage={"status": "synthetic-reviewed-later-state"},
            thermodynamic_eligible_members=member_ids,
            ts_seed_members=[],
        )

    def observation(
        self,
        member_id: str,
        *,
        gibbs: float = -100.0,
        degeneracy: object = 1,
        policy: dict[str, object] | None = None,
        method: dict[str, str] | None = None,
    ) -> dict[str, object]:
        selected_policy = copy.deepcopy(policy or self.policy())
        temperature = float(selected_policy["temperature_k"])
        raw_entropy = 0.00011
        treated_entropy = 0.00010
        raw_gibbs = gibbs + 0.001
        raw_log_sha256 = hashlib.sha256(f"log-{member_id}".encode()).hexdigest()
        return {
            "member_id": member_id,
            "source_provenance": {
                "source_result_id": f"synthetic-result-{member_id}",
                "source_result_payload_sha256": hashlib.sha256(f"result-{member_id}".encode()).hexdigest(),
                "source_gaussian_log_sha256": raw_log_sha256,
                "result_contract_identity": "closed-synthetic-result-fixture-v1",
                "evidence_disposition": "closed_synthetic_contract_fixture",
                "output_reported_point_group": "C1",
                "symmetry_provenance": {
                    "symmetry_policy": {
                        "mode": "gaussian_output_required",
                        "external_detection": "disabled",
                    },
                    "goodvibes_symm": False,
                    "reported_rotational_symmetry_number": 1,
                    "explicit_symmetry_observation_count": 1,
                    "raw_gaussian_log_sha256": raw_log_sha256,
                    "goodvibes_parsed_symmno": 1,
                },
            },
            "method_compatibility_binding": copy.deepcopy(method or self.method()),
            "temperature_k": temperature,
            "standard_state": selected_policy["standard_state"],
            "thermochemistry_policy": selected_policy,
            "raw_rrho": {
                "electronic_energy_hartree": gibbs - 0.02,
                "zero_point_energy_hartree": 0.02,
                "enthalpy_hartree": raw_gibbs + temperature * raw_entropy,
                "entropy_hartree_per_kelvin": raw_entropy,
                "gibbs_free_energy_hartree": raw_gibbs,
            },
            "treated_qrrho": {
                "enthalpy_hartree": gibbs + temperature * treated_entropy,
                "entropy_hartree_per_kelvin": treated_entropy,
                "gibbs_free_energy_hartree": gibbs,
                "entropy_treatment": selected_policy["qrrho_entropy_method"],
                "enthalpy_treatment": selected_policy["qrrho_enthalpy_treatment"],
            },
            "degeneracy": degeneracy,
            "degeneracy_rationale": "explicit reviewed synthetic fixture value",
        }

    def build(self, observations: list[dict[str, object]], member_ids: tuple[str, ...] = ("member-a", "member-b")) -> ThermodynamicEnsemble:
        return _build_thermodynamic_ensemble(self.ensemble(member_ids), observations)

    def adapter_observation(
        self,
        raw_gaussian_log: bytes,
        *,
        parsed_symmno: object,
        policy: dict[str, object] | None = None,
    ) -> tuple[dict[str, object], dict[str, object]]:
        captured: dict[str, object] = {}

        @dataclass
        class FakeOptions:
            QS: object = None
            QH: object = None
            s_freq_cutoff: object = None
            h_freq_cutoff: object = None
            temperature: object = None
            concentration: object = None
            freq_scale_factor: object = None
            zpe_scale_factor: object = None
            solv: object = None
            spc: object = None
            invert: object = None
            symm: object = None
            mm_freq_scale_factor: object = None
            inertia: object = None

            def __post_init__(self) -> None:
                captured.update(vars(self))

        class FakeCalc:
            @classmethod
            def from_options(cls, qcdata: object, options: object) -> object:
                del cls, qcdata, options
                return SimpleNamespace(
                    scf_energy=-100.1,
                    zpe=0.02,
                    enthalpy=-100.0 + 298.15 * 0.00011,
                    qh_enthalpy=-100.0 + 298.15 * 0.00010,
                    entropy=0.00011,
                    qh_entropy=0.00010,
                    gibbs_free_energy=-100.0,
                    qh_gibbs_free_energy=-100.0,
                    point_group="C2v",
                )

        qcdata = SimpleNamespace(file="synthetic-preparsed-qcdata", symmno=parsed_symmno)
        source_hash = hashlib.sha256(raw_gaussian_log).hexdigest()
        with patch(
            "auto_g16.thermochemistry._goodvibes._load_goodvibes_api",
            return_value=("4.3.0", FakeOptions, FakeCalc),
        ):
            observation = _goodvibes_observation(
                member_id="member-a",
                qcdata=qcdata,
                source_result_id="synthetic-result",
                source_result_payload_sha256="a" * 64,
                raw_gaussian_log=raw_gaussian_log,
                source_gaussian_log_sha256=source_hash,
                result_contract_identity="closed-synthetic-result-fixture-v1",
                evidence_disposition="closed_synthetic_contract_fixture",
                method_compatibility_binding=self.method(),
                degeneracy=1,
                degeneracy_rationale="explicit synthetic",
                thermochemistry_policy=policy or self.policy(),
            )
        return dict(observation), captured

    def test_01_public_exports_exactly_thermodynamic_ensemble(self) -> None:
        self.assertEqual(thermochemistry.__all__, ["ThermodynamicEnsemble"])
        self.assertIs(thermochemistry.ThermodynamicEnsemble, ThermodynamicEnsemble)

    def test_02_empty_thermodynamic_eligible_set_rejects(self) -> None:
        with self.assertRaisesRegex(ValueError, "eligible member set is empty"):
            _build_thermodynamic_ensemble(self.ensemble(()), [])

    def test_03_missing_eligible_member_rejects(self) -> None:
        with self.assertRaisesRegex(ValueError, "missing eligible"):
            self.build([self.observation("member-a")])

    def test_04_extra_member_rejects(self) -> None:
        with self.assertRaisesRegex(ValueError, "extra thermochemistry"):
            self.build([
                self.observation("member-a"), self.observation("member-b"), self.observation("member-c")
            ])

    def test_05_duplicate_member_rejects(self) -> None:
        with self.assertRaisesRegex(ValueError, "duplicate thermochemistry"):
            self.build([
                self.observation("member-a"), self.observation("member-a"), self.observation("member-b")
            ])

    def test_06_mixed_temperature_rejects(self) -> None:
        hotter = self.policy(temperature=310.0)
        with self.assertRaisesRegex(ValueError, "mixed temperature"):
            self.build([self.observation("member-a"), self.observation("member-b", policy=hotter)])

    def test_07_mixed_standard_state_rejects(self) -> None:
        molar = self.policy(standard_state="1M")
        with self.assertRaisesRegex(ValueError, "mixed standard-state"):
            self.build([self.observation("member-a"), self.observation("member-b", policy=molar)])
        result = self.build([
            self.observation("member-a", policy=molar), self.observation("member-b", policy=molar)
        ])
        self.assertEqual(result.standard_state_binding["concentration_mol_per_l"], 1.0)

    def test_08_mixed_method_rejects(self) -> None:
        with self.assertRaisesRegex(ValueError, "mixed method"):
            self.build([
                self.observation("member-a"), self.observation("member-b", method=self.method("other"))
            ])

    def test_09_mixed_qrrho_policy_rejects(self) -> None:
        changed = self.policy()
        changed["entropy_frequency_cutoff_cm_1"] = 75.0
        with self.assertRaisesRegex(ValueError, "mixed qRRHO"):
            self.build([self.observation("member-a"), self.observation("member-b", policy=changed)])
        changed_implementation = self.policy()
        changed_implementation["adapter_version"] = "2"
        with self.assertRaisesRegex(ValueError, "adapter_version is unsupported"):
            self.build([
                self.observation("member-a"),
                self.observation("member-b", policy=changed_implementation),
            ])

    def test_10_raw_rrho_is_retained_distinctly_from_treated_qrrho(self) -> None:
        result = self.build([self.observation("member-a"), self.observation("member-b", gibbs=-99.9)])
        member = result.member_observations[0]
        self.assertIn("raw_rrho", member)
        self.assertIn("treated_qrrho", member)
        self.assertNotEqual(member["raw_rrho"]["gibbs_free_energy_hartree"], member["treated_qrrho"]["gibbs_free_energy_hartree"])

    def test_11_implicit_goodvibes_defaults_are_never_sufficient_provenance(self) -> None:
        incomplete = self.observation("member-a")
        del incomplete["thermochemistry_policy"]["zpe_scaling_factor"]
        with self.assertRaisesRegex(ValueError, "must contain exactly"):
            self.build([incomplete, self.observation("member-b")])

        observation, captured = self.adapter_observation(
            b" Rotational symmetry number  1.\n",
            parsed_symmno=1,
        )
        self.assertEqual(set(captured), set(_THERMO_OPTION_FIELDS))
        self.assertAlmostEqual(captured["concentration"], 101.325 / (8.3144621 * 298.15))
        self.assertFalse(captured["symm"])
        self.assertIsNone(captured["spc"])
        self.assertIsNone(captured["invert"])
        self.assertIn("raw_rrho", observation)
        self.assertIn("treated_qrrho", observation)

    def test_12_bool_and_float_degeneracy_reject(self) -> None:
        for value in (True, 1.0):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "exact positive integer"):
                self.build([self.observation("member-a", degeneracy=value), self.observation("member-b")])

    def test_13_populations_are_deterministic_independent_of_input_order(self) -> None:
        observations = [self.observation("member-a", gibbs=-100.0), self.observation("member-b", gibbs=-99.99)]
        forward = self.build(observations)
        reverse = self.build(list(reversed(observations)))
        self.assertEqual(forward.thermodynamic_ensemble_id, reverse.thermodynamic_ensemble_id)
        self.assertEqual(forward.member_observations, reverse.member_observations)

    def test_14_equal_energy_degeneracy_ratio_sets_population_ratio(self) -> None:
        result = self.build([
            self.observation("member-a", degeneracy=1), self.observation("member-b", degeneracy=3)
        ])
        populations = {item["member_id"]: item["normalized_population"] for item in result.member_observations}
        self.assertAlmostEqual(populations["member-a"], 0.25)
        self.assertAlmostEqual(populations["member-b"], 0.75)

    def test_15_extreme_delta_g_and_large_degeneracy_do_not_overflow(self) -> None:
        result = self.build([
            self.observation("member-a", gibbs=-1000.0),
            self.observation("member-b", gibbs=1000.0, degeneracy=10**400),
        ])
        self.assertTrue(math.isfinite(result.ensemble_treated_free_energy_hartree))
        self.assertTrue(all(math.isfinite(item["normalized_population"]) for item in result.member_observations))

    def test_16_population_sum_reproduces_one(self) -> None:
        result = self.build([
            self.observation("member-a", gibbs=-100.0), self.observation("member-b", gibbs=-99.997)
        ])
        self.assertAlmostEqual(math.fsum(item["normalized_population"] for item in result.member_observations), 1.0, places=14)
        self.assertEqual(result.population_normalization["status"], "normalized")

    def test_17_ensemble_free_energy_independently_recomputes(self) -> None:
        observations = [
            self.observation("member-a", gibbs=-100.0, degeneracy=2),
            self.observation("member-b", gibbs=-99.998, degeneracy=5),
        ]
        result = self.build(observations)
        temperature = float(result.temperature_k)
        rt = _GAS_CONSTANT_HARTREE_PER_MOL_K * temperature
        reference = min(float(item["treated_qrrho"]["gibbs_free_energy_hartree"]) for item in observations)
        partition = math.fsum(
            int(item["degeneracy"]) * math.exp(-(float(item["treated_qrrho"]["gibbs_free_energy_hartree"]) - reference) / rt)
            for item in observations
        )
        self.assertAlmostEqual(result.ensemble_treated_free_energy_hartree, reference - rt * math.log(partition), places=14)

    def test_18_goodvibes_does_not_own_aggregation_selection_or_dedup(self) -> None:
        adapter = (ROOT / "auto_g16/thermochemistry/_goodvibes.py").read_text(encoding="utf-8")
        tree = ast.parse(adapter)
        imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        self.assertNotIn("goodvibes.pes", imports)
        self.assertNotIn("goodvibes.selectivity", imports)
        self.assertNotIn("goodvibes.boltz", imports)
        self.assertIn("calc_bbe", adapter)
        self.assertIn("from_options", adapter)

    def test_19_product_package_has_no_process_network_or_execution_import(self) -> None:
        forbidden = {"subprocess", "socket", "requests", "urllib", "http", "auto_g16.execution"}
        for path in (ROOT / "auto_g16/thermochemistry").glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            imports: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports.update(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    imports.add(node.module or "")
            self.assertFalse(any(any(name == item or name.startswith(item + ".") for item in forbidden) for name in imports), path)

    def test_20_no_public_extra_thermochemistry_records(self) -> None:
        public_records = []
        for module_name in ("auto_g16.thermochemistry", "auto_g16.thermochemistry.models"):
            module = importlib.import_module(module_name)
            for name, value in vars(module).items():
                if not name.startswith("_") and isinstance(value, type) and is_dataclass(value):
                    public_records.append((name, value))
        self.assertEqual({name for name, _value in public_records}, {"ThermodynamicEnsemble"})

    def test_21_explicit_symmetry_one_and_goodvibes_one_accept(self) -> None:
        for newline in (b"\n", b"\r\n", b"\r"):
            with self.subTest(newline=newline):
                observation, captured = self.adapter_observation(
                    b" Gaussian diagnostic" + newline + b" Rotational symmetry number  1." + newline,
                    parsed_symmno=1,
                )
                symmetry = observation["source_provenance"]["symmetry_provenance"]
                self.assertEqual(symmetry["reported_rotational_symmetry_number"], 1)
                self.assertEqual(symmetry["explicit_symmetry_observation_count"], 1)
                self.assertEqual(symmetry["goodvibes_parsed_symmno"], 1)
                self.assertEqual(
                    symmetry["symmetry_policy"],
                    {"mode": "gaussian_output_required", "external_detection": "disabled"},
                )
                self.assertFalse(symmetry["goodvibes_symm"])
                self.assertFalse(captured["symm"])

    def test_22_explicit_symmetry_two_and_goodvibes_two_accept(self) -> None:
        observation, _captured = self.adapter_observation(
            b" Rotational symmetry number  2.\n Full point group C2v\n",
            parsed_symmno=2,
        )
        symmetry = observation["source_provenance"]["symmetry_provenance"]
        self.assertEqual(symmetry["reported_rotational_symmetry_number"], 2)
        self.assertEqual(symmetry["goodvibes_parsed_symmno"], 2)

    def test_23_missing_symmetry_marker_rejects_even_if_goodvibes_defaults_one(self) -> None:
        false_markers = (
            b" Full point group C2v\n",
            b"junk\x0bRotational symmetry number  1.\n",
            b"junk\x0cRotational symmetry number  1.\n",
            "junk\u0085Rotational symmetry number  1.\n".encode(),
            "junk\u2028Rotational symmetry number  1.\n".encode(),
        )
        for raw_log in false_markers:
            with self.subTest(raw_log=raw_log), self.assertRaisesRegex(
                RuntimeError,
                "lacks an explicit rotational symmetry number",
            ):
                self.adapter_observation(raw_log, parsed_symmno=1)

    def test_24_explicit_two_and_goodvibes_one_rejects_without_mutation(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "disagrees with the explicit raw Gaussian log"):
            self.adapter_observation(b" Rotational symmetry number  2.\n", parsed_symmno=1)

    def test_25_conflicting_explicit_symmetry_values_reject(self) -> None:
        raw_log = b" Rotational symmetry number  1.\n Rotational symmetry number  2.\n"
        with self.assertRaisesRegex(RuntimeError, "conflicting rotational symmetry numbers"):
            self.adapter_observation(raw_log, parsed_symmno=2)

    def test_26_identical_repeated_explicit_symmetry_values_accept(self) -> None:
        raw_log = b" Rotational symmetry number  2.\n Rotational symmetry number  2.\n"
        observation, _captured = self.adapter_observation(raw_log, parsed_symmno=2)
        symmetry = observation["source_provenance"]["symmetry_provenance"]
        self.assertEqual(symmetry["reported_rotational_symmetry_number"], 2)
        self.assertEqual(symmetry["explicit_symmetry_observation_count"], 2)

    def test_27_malformed_zero_negative_and_hash_drift_reject(self) -> None:
        cases = (
            (b" Rotational symmetry number  zero.\n", "marker is malformed"),
            (b" Rotational symmetry number  0.\n", "must be positive"),
            (b" Rotational symmetry number  -2.\n", "must be positive"),
        )
        for raw_log, reason in cases:
            with self.subTest(raw_log=raw_log), self.assertRaisesRegex(RuntimeError, reason):
                self.adapter_observation(raw_log, parsed_symmno=1)
        with self.assertRaisesRegex(RuntimeError, "SHA-256 does not match"):
            _goodvibes_observation(
                member_id="member-a",
                qcdata=SimpleNamespace(file="synthetic", symmno=1),
                source_result_id="synthetic-result",
                source_result_payload_sha256="a" * 64,
                raw_gaussian_log=b" Rotational symmetry number  1.\n",
                source_gaussian_log_sha256="b" * 64,
                result_contract_identity="closed-synthetic-result-fixture-v1",
                evidence_disposition="closed_synthetic_contract_fixture",
                method_compatibility_binding=self.method(),
                degeneracy=1,
                degeneracy_rationale="explicit synthetic",
                thermochemistry_policy=self.policy(),
            )

    def test_28_goodvibes_symm_true_policy_rejects(self) -> None:
        policy = self.policy()
        policy["goodvibes_symm"] = True
        with self.assertRaisesRegex(ValueError, "goodvibes_symm is unsupported"):
            self.build([self.observation("member-a", policy=policy), self.observation("member-b")])

    def test_29_pymsym_availability_cannot_change_result(self) -> None:
        raw_log = b" Rotational symmetry number  2.\n"
        with patch.dict(sys.modules, {"pymsym": None}):
            absent, absent_options = self.adapter_observation(raw_log, parsed_symmno=2)
        with patch.dict(sys.modules, {"pymsym": SimpleNamespace(available=True)}):
            present, present_options = self.adapter_observation(raw_log, parsed_symmno=2)
        self.assertEqual(absent, present)
        self.assertFalse(absent_options["symm"])
        self.assertFalse(present_options["symm"])


if __name__ == "__main__":
    unittest.main()
