"""Isolated differential qualification against the exact GoodVibes 4.3.0 wheel."""

from __future__ import annotations

from hashlib import sha256
import os
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest

from auto_g16.thermochemistry._goodvibes import functional_thermochemistry


_EXPECTED_WHEEL_SHA256 = "06476db73ee456c1fc941590374f2a30182baaf043f6b60dbef85ee77db93997"
_TOLERANCE = 1.0e-12


class GoodVibesDifferentialQualification(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        root_text = os.environ.get("AUTO_G16_GOODVIBES_430_QUALIFICATION_ROOT")
        wheel_text = os.environ.get("AUTO_G16_GOODVIBES_430_QUALIFICATION_WHEEL")
        if root_text is None and wheel_text is None:
            raise unittest.SkipTest("exact GoodVibes 4.3.0 qualification environment is not selected")
        if root_text is None or wheel_text is None:
            raise RuntimeError("qualification root and wheel must be selected together")
        root = Path(root_text)
        wheel = Path(wheel_text)
        if not root.is_absolute() or not wheel.is_absolute():
            raise RuntimeError("qualification paths must be absolute")
        if root.is_symlink() or wheel.is_symlink() or not root.is_dir() or not wheel.is_file():
            raise RuntimeError("qualification paths must be existing non-symlink objects")
        if sha256(wheel.read_bytes()).hexdigest() != _EXPECTED_WHEEL_SHA256:
            raise RuntimeError("qualification wheel SHA-256 differs from the frozen artifact")
        if not (root / "goodvibes-4.3.0.dist-info/METADATA").is_file():
            raise RuntimeError("qualification root does not contain the exact GoodVibes 4.3.0 distribution")
        sys.path.insert(0, str(root))
        cls._root = root

    @classmethod
    def tearDownClass(cls) -> None:
        root = getattr(cls, "_root", None)
        if root is not None and sys.path and sys.path[0] == str(root):
            sys.path.pop(0)

    @staticmethod
    def _qcdata(*, name, atoms, frequencies, mass, rotemps, symmetry, energy):
        return SimpleNamespace(
            file=f"closed-goodvibes-qualification-{name}.out",
            atom_types=["C"] * atoms,
            atom_nums=[6] * atoms,
            cartesians=[[float(index), float(index % 2), float(index % 3)] for index in range(atoms)],
            program="Gaussian", version_program="Gaussian 16", solvation_model="gas",
            charge=0, empirical_dispersion="No empirical dispersion detected",
            multiplicity=1, scf_energy=energy, zero_point_corr=0.01,
            job_type="Freq", roconst=[1.0, 2.0, 3.0], point_group="C2",
            cpu=[0, 0, 0, 0, 0], molecular_mass=mass, symmno=symmetry,
            linear_mol=False, rotemp=list(rotemps), linear_warning=False,
            frequency_wn=list(frequencies), im_frequency_wn=[],
        )

    def test_functional_composition_matches_actual_calc_bbe(self) -> None:
        from goodvibes import __version__
        from goodvibes.thermo import ThermoOptions, calc_bbe

        self.assertEqual(__version__, "4.3.0")
        fixtures = (
            self._qcdata(
                name="nonlinear-three-atom", atoms=3,
                frequencies=(25.0, 100.0, 250.0), mass=18.01056,
                rotemps=(37.12617, 20.74054, 13.30673), symmetry=2, energy=-76.4,
            ),
            self._qcdata(
                name="larger-nonlinear-organic", atoms=12,
                frequencies=(12.5, 99.999999, 100.0, 100.000001, 180.0, 275.0, 410.0, 620.0, 880.0, 1100.0, 1400.0, 3100.0),
                mass=86.17536, rotemps=(0.50, 0.35, 0.20), symmetry=3, energy=-234.56789,
            ),
        )
        temperature = 298.15
        concentration = 101.325 / (8.3144621 * temperature)
        options = ThermoOptions(
            QS="grimme", QH=True, s_freq_cutoff=100.0, h_freq_cutoff=100.0,
            temperature=temperature, concentration=concentration,
            freq_scale_factor=0.99, zpe_scale_factor=0.98,
            solv=None, spc=None, invert=None, symm=False,
            mm_freq_scale_factor=None, inertia="global",
        )
        for fixture in fixtures:
            with self.subTest(fixture=fixture.file):
                expected = calc_bbe.from_options(fixture, options)
                actual = functional_thermochemistry(
                    electronic_energy_hartree=fixture.scf_energy,
                    frequencies_cm1=tuple(fixture.frequency_wn),
                    molecular_mass_amu=fixture.molecular_mass,
                    rotational_symmetry_number=fixture.symmno,
                    rotational_temperatures_kelvin=tuple(fixture.rotemp),
                    temperature_k=temperature,
                    concentration_mol_per_l=concentration,
                    entropy_frequency_cutoff_cm1=100.0,
                    enthalpy_frequency_cutoff_cm1=100.0,
                    frequency_scaling_factor=0.99,
                    zpe_scaling_factor=0.98,
                )
                comparisons = {
                    "zpe": (actual["raw_rrho"]["zero_point_energy_hartree"], expected.zpe),
                    "raw H": (actual["raw_rrho"]["enthalpy_hartree"], expected.enthalpy),
                    "raw S": (actual["raw_rrho"]["entropy_hartree_per_kelvin"], expected.entropy),
                    "raw G": (actual["raw_rrho"]["gibbs_free_energy_hartree"], expected.gibbs_free_energy),
                    "treated H": (actual["treated_qrrho"]["enthalpy_hartree"], expected.qh_enthalpy),
                    "treated S": (actual["treated_qrrho"]["entropy_hartree_per_kelvin"], expected.qh_entropy),
                    "treated G": (actual["treated_qrrho"]["gibbs_free_energy_hartree"], expected.qh_gibbs_free_energy),
                }
                for label, (observed, reference) in comparisons.items():
                    with self.subTest(term=label):
                        self.assertLessEqual(abs(observed - reference), _TOLERANCE)


if __name__ == "__main__":
    unittest.main()
