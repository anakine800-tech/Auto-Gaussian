"""Private GoodVibes 4.3.0 functional-kernel adapter, version 2."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from importlib.metadata import PackageNotFoundError, version
import math


_ADAPTER_IDENTITY = "auto-g16-goodvibes-functional-kernel-adapter"
_ADAPTER_VERSION = 2
_GOODVIBES_VERSION = "4.3.0"
_GOODVIBES_ARTIFACT_SHA256 = "06476db73ee456c1fc941590374f2a30182baaf043f6b60dbef85ee77db93997"
_ALLOWED_KERNEL_NAMES = (
    "calc_translational_energy",
    "calc_rotational_energy",
    "calc_vibrational_energy",
    "calc_zeropoint_energy",
    "calc_translational_entropy",
    "calc_electronic_entropy",
    "calc_rotational_entropy",
    "calc_rrho_entropy",
    "calc_freerot_entropy",
    "calc_qRRHO_energy",
    "calc_damp",
)
_ALLOWED_CONSTANT_NAMES = ("GAS_CONSTANT", "J_TO_AU", "GRIMME_BAV")


class FunctionalKernelError(ValueError):
    """The closed kernel input, dependency, or numeric output is unsupported."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise FunctionalKernelError(message)


def _load_goodvibes_kernels() -> tuple[Mapping[str, object], Mapping[str, float]]:
    try:
        installed_version = version("goodvibes")
    except PackageNotFoundError as exc:
        raise FunctionalKernelError("GoodVibes 4.3.0 is unavailable") from exc
    _require(installed_version == _GOODVIBES_VERSION, "installed GoodVibes version is not 4.3.0")
    from goodvibes.thermo import (
        GAS_CONSTANT,
        GRIMME_BAV,
        J_TO_AU,
        calc_damp,
        calc_electronic_entropy,
        calc_freerot_entropy,
        calc_qRRHO_energy,
        calc_rotational_energy,
        calc_rotational_entropy,
        calc_rrho_entropy,
        calc_translational_energy,
        calc_translational_entropy,
        calc_vibrational_energy,
        calc_zeropoint_energy,
    )

    kernels = {
        "calc_translational_energy": calc_translational_energy,
        "calc_rotational_energy": calc_rotational_energy,
        "calc_vibrational_energy": calc_vibrational_energy,
        "calc_zeropoint_energy": calc_zeropoint_energy,
        "calc_translational_entropy": calc_translational_entropy,
        "calc_electronic_entropy": calc_electronic_entropy,
        "calc_rotational_entropy": calc_rotational_entropy,
        "calc_rrho_entropy": calc_rrho_entropy,
        "calc_freerot_entropy": calc_freerot_entropy,
        "calc_qRRHO_energy": calc_qRRHO_energy,
        "calc_damp": calc_damp,
    }
    constants = {
        "GAS_CONSTANT": float(GAS_CONSTANT),
        "J_TO_AU": float(J_TO_AU),
        "GRIMME_BAV": float(GRIMME_BAV),
    }
    _require(tuple(kernels) == _ALLOWED_KERNEL_NAMES, "GoodVibes kernel inventory drifted")
    _require(tuple(constants) == _ALLOWED_CONSTANT_NAMES, "GoodVibes constant inventory drifted")
    _require(constants["GAS_CONSTANT"] == 8.3144621, "GoodVibes gas constant drifted")
    _require(constants["J_TO_AU"] == 4.184 * 627.509541 * 1000.0, "GoodVibes J_TO_AU drifted")
    _require(constants["GRIMME_BAV"] == 1.0e-44, "GoodVibes GRIMME_BAV drifted")
    return kernels, constants


def _finite(value: object, name: str) -> float:
    _require(type(value) in {int, float} and math.isfinite(float(value)), f"{name} is not finite")
    return float(value)


def _finite_sequence(value: object, size: int, name: str) -> tuple[float, ...]:
    _require(
        isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)),
        f"{name} is not a sequence",
    )
    result = tuple(_finite(item, name) for item in value)
    _require(len(result) == size, f"{name} cardinality differs from frequencies")
    return result


def functional_thermochemistry(
    *,
    electronic_energy_hartree: float,
    frequencies_cm1: tuple[float, ...],
    molecular_mass_amu: float,
    rotational_symmetry_number: int,
    rotational_temperatures_kelvin: tuple[float, float, float],
    temperature_k: float,
    concentration_mol_per_l: float,
    entropy_frequency_cutoff_cm1: float,
    enthalpy_frequency_cutoff_cm1: float,
    frequency_scaling_factor: float,
    zpe_scaling_factor: float,
) -> Mapping[str, object]:
    """Compose raw RRHO and frozen Grimme/Head-Gordon qRRHO from allowed kernels."""

    energy = _finite(electronic_energy_hartree, "electronic energy")
    temperature = _finite(temperature_k, "temperature")
    concentration = _finite(concentration_mol_per_l, "concentration")
    mass = _finite(molecular_mass_amu, "molecular mass")
    entropy_cutoff = _finite(entropy_frequency_cutoff_cm1, "entropy cutoff")
    enthalpy_cutoff = _finite(enthalpy_frequency_cutoff_cm1, "enthalpy cutoff")
    frequency_scale = _finite(frequency_scaling_factor, "frequency scaling factor")
    zpe_scale = _finite(zpe_scaling_factor, "ZPE scaling factor")
    _require(
        temperature > 0.0 and concentration > 0.0 and mass > 0.0
        and entropy_cutoff > 0.0 and enthalpy_cutoff > 0.0
        and frequency_scale > 0.0 and zpe_scale > 0.0,
        "functional-kernel positive inputs are required",
    )
    _require(
        type(rotational_symmetry_number) is int and rotational_symmetry_number >= 1,
        "rotational symmetry number must be a positive integer",
    )
    _require(
        type(frequencies_cm1) is tuple
        and bool(frequencies_cm1)
        and all(type(item) is float and math.isfinite(item) and item > 0.0 for item in frequencies_cm1),
        "frequencies must be a non-empty exact positive float tuple",
    )
    _require(
        type(rotational_temperatures_kelvin) is tuple
        and len(rotational_temperatures_kelvin) == 3
        and all(type(item) is float and math.isfinite(item) and item > 0.0 for item in rotational_temperatures_kelvin),
        "three positive rotational temperatures are required",
    )
    kernels, constants = _load_goodvibes_kernels()
    trans_energy = _finite(kernels["calc_translational_energy"](temperature), "translational energy")  # type: ignore[operator]
    rot_energy = _finite(kernels["calc_rotational_energy"](temperature, monatomic=False, linear=False), "rotational energy")  # type: ignore[operator]
    vib_energy = _finite(kernels["calc_vibrational_energy"](temperature, frequencies_cm1, frequency_scale, None), "vibrational energy")  # type: ignore[operator]
    zpe = _finite(kernels["calc_zeropoint_energy"](frequencies_cm1, zpe_scale, None), "zero-point energy")  # type: ignore[operator]
    trans_entropy = _finite(kernels["calc_translational_entropy"](mass, concentration, temperature, None), "translational entropy")  # type: ignore[operator]
    electronic_entropy = _finite(kernels["calc_electronic_entropy"](1), "electronic entropy")  # type: ignore[operator]
    rotational_entropy = _finite(kernels["calc_rotational_entropy"](temperature, rotational_temperatures_kelvin, symmno=rotational_symmetry_number, monatomic=False, linear=False), "rotational entropy")  # type: ignore[operator]
    rrho_entropy_modes = _finite_sequence(
        kernels["calc_rrho_entropy"](temperature, frequencies_cm1, frequency_scale, None),  # type: ignore[operator]
        len(frequencies_cm1),
        "RRHO entropy modes",
    )
    freerot_entropy_modes = _finite_sequence(
        kernels["calc_freerot_entropy"](temperature, frequencies_cm1, constants["GRIMME_BAV"], frequency_scale, None),  # type: ignore[operator]
        len(frequencies_cm1),
        "free-rotor entropy modes",
    )
    entropy_damping = _finite_sequence(
        kernels["calc_damp"](frequencies_cm1, entropy_cutoff),  # type: ignore[operator]
        len(frequencies_cm1),
        "entropy damping",
    )
    qrrho_energy_modes = _finite_sequence(
        kernels["calc_qRRHO_energy"](temperature, frequencies_cm1, frequency_scale),  # type: ignore[operator]
        len(frequencies_cm1),
        "qRRHO energy modes",
    )
    enthalpy_damping = _finite_sequence(
        kernels["calc_damp"](frequencies_cm1, enthalpy_cutoff),  # type: ignore[operator]
        len(frequencies_cm1),
        "enthalpy damping",
    )
    _require(
        all(0.0 <= item <= 1.0 for item in (*entropy_damping, *enthalpy_damping)),
        "GoodVibes damping output is outside [0,1]",
    )
    treated_vib_entropy = math.fsum(
        damping * rrho + (1.0 - damping) * freerot
        for damping, rrho, freerot in zip(
            entropy_damping, rrho_entropy_modes, freerot_entropy_modes
        )
    )
    treated_vib_energy = math.fsum(
        damping * qrrho + (1.0 - damping) * 0.5 * constants["GAS_CONSTANT"] * temperature
        for damping, qrrho in zip(enthalpy_damping, qrrho_energy_modes)
    )
    raw_vib_entropy = math.fsum(rrho_entropy_modes)
    raw_enthalpy = energy + (
        trans_energy + rot_energy + vib_energy + constants["GAS_CONSTANT"] * temperature
    ) / constants["J_TO_AU"]
    treated_enthalpy = energy + (
        trans_energy + rot_energy + treated_vib_energy + constants["GAS_CONSTANT"] * temperature
    ) / constants["J_TO_AU"]
    raw_entropy = (
        trans_entropy + rotational_entropy + raw_vib_entropy + electronic_entropy
    ) / constants["J_TO_AU"]
    treated_entropy = (
        trans_entropy + rotational_entropy + treated_vib_entropy + electronic_entropy
    ) / constants["J_TO_AU"]
    raw_gibbs = raw_enthalpy - temperature * raw_entropy
    treated_gibbs = treated_enthalpy - temperature * treated_entropy
    outputs = {
        "raw_rrho": {
            "electronic_energy_hartree": energy,
            "zero_point_energy_hartree": zpe / constants["J_TO_AU"],
            "enthalpy_hartree": raw_enthalpy,
            "entropy_hartree_per_kelvin": raw_entropy,
            "gibbs_free_energy_hartree": raw_gibbs,
        },
        "treated_qrrho": {
            "enthalpy_hartree": treated_enthalpy,
            "entropy_hartree_per_kelvin": treated_entropy,
            "gibbs_free_energy_hartree": treated_gibbs,
            "entropy_treatment": "grimme",
            "enthalpy_treatment": "head_gordon",
        },
    }
    _require(
        all(math.isfinite(float(value)) for group in outputs.values() for value in group.values() if type(value) in {int, float}),
        "functional-kernel result is non-finite",
    )
    return outputs
