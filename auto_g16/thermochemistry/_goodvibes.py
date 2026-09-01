"""Private GoodVibes 4.3.0 programmatic adapter; no process or CLI boundary."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import fields
import hashlib
import io
import math
import re

from ._service import _normalize_policy, _standard_state_binding


_THERMO_OPTION_FIELDS = (
    "QS",
    "QH",
    "s_freq_cutoff",
    "h_freq_cutoff",
    "temperature",
    "concentration",
    "freq_scale_factor",
    "zpe_scale_factor",
    "solv",
    "spc",
    "invert",
    "symm",
    "mm_freq_scale_factor",
    "inertia",
)
_ROTATIONAL_SYMMETRY_MARKER = "Rotational symmetry number"
_ROTATIONAL_SYMMETRY_LINE = re.compile(
    r"\ARotational symmetry number[ \t]+([+-]?[0-9]+)\.[ \t]*\Z"
)


def _iter_goodvibes_text_lines(raw_gaussian_log: bytes) -> Iterator[str]:
    """Iterate exact bytes with GoodVibes 4.3.0 file-line semantics."""

    with io.TextIOWrapper(
        io.BytesIO(raw_gaussian_log),
        encoding="utf-8",
        errors="replace",
        newline=None,
    ) as stream:
        yield from stream


def _reported_rotational_symmetry(
    raw_gaussian_log: bytes,
    source_gaussian_log_sha256: str,
) -> tuple[int, int]:
    if type(raw_gaussian_log) is not bytes:
        raise RuntimeError("raw Gaussian log must be exact bytes")
    if hashlib.sha256(raw_gaussian_log).hexdigest() != source_gaussian_log_sha256:
        raise RuntimeError("raw Gaussian log SHA-256 does not match source provenance")
    values: list[int] = []
    for line in _iter_goodvibes_text_lines(raw_gaussian_log):
        stripped_line = line.strip()
        if stripped_line.startswith(_ROTATIONAL_SYMMETRY_MARKER):
            match = _ROTATIONAL_SYMMETRY_LINE.fullmatch(stripped_line)
            if match is None:
                raise RuntimeError("raw Gaussian rotational symmetry marker is malformed")
            value = int(match.group(1))
            if value < 1:
                raise RuntimeError("raw Gaussian rotational symmetry number must be positive")
            values.append(value)
    if not values:
        raise RuntimeError("raw Gaussian log lacks an explicit rotational symmetry number")
    if len(set(values)) != 1:
        raise RuntimeError("raw Gaussian log contains conflicting rotational symmetry numbers")
    return values[0], len(values)


def _load_goodvibes_api() -> tuple[str, object, object]:
    from goodvibes import __version__
    from goodvibes.thermo import ThermoOptions, calc_bbe

    return __version__, ThermoOptions, calc_bbe


def _goodvibes_observation(
    *,
    member_id: str,
    qcdata: object,
    source_result_id: str,
    source_result_payload_sha256: str,
    raw_gaussian_log: bytes,
    source_gaussian_log_sha256: str,
    result_contract_identity: str,
    evidence_disposition: str,
    method_compatibility_binding: Mapping[str, object],
    degeneracy: int,
    degeneracy_rationale: str,
    thermochemistry_policy: Mapping[str, object],
) -> Mapping[str, object]:
    policy = _normalize_policy(thermochemistry_policy)
    if isinstance(qcdata, (str, bytes, bytearray)) or not hasattr(qcdata, "file"):
        raise RuntimeError("the private adapter requires explicit pre-parsed GoodVibes QCData")
    reported_symmetry_number, symmetry_observation_count = _reported_rotational_symmetry(
        raw_gaussian_log,
        source_gaussian_log_sha256,
    )
    version, thermo_options, calc_bbe = _load_goodvibes_api()
    if version != policy["engine_version"]:
        raise RuntimeError("installed GoodVibes version does not match the closed policy")
    if tuple(field.name for field in fields(thermo_options)) != _THERMO_OPTION_FIELDS:
        raise RuntimeError("GoodVibes ThermoOptions field inventory contradicts the qualified API")
    state = _standard_state_binding(policy)
    concentration = (
        state["derived_concentration_mol_per_l"]
        if state["kind"] == "1atm"
        else state["concentration_mol_per_l"]
    )
    options = thermo_options(
        QS=policy["qrrho_entropy_method"],
        QH=policy["qrrho_enthalpy_treatment"] == "head_gordon",
        s_freq_cutoff=policy["entropy_frequency_cutoff_cm_1"],
        h_freq_cutoff=policy["enthalpy_frequency_cutoff_cm_1"],
        temperature=policy["temperature_k"],
        concentration=concentration,
        freq_scale_factor=policy["frequency_scaling_factor"],
        zpe_scale_factor=policy["zpe_scaling_factor"],
        solv=None,
        spc=None,
        invert=None,
        symm=policy["goodvibes_symm"],
        mm_freq_scale_factor=None,
        inertia="global",
    )
    result = calc_bbe.from_options(qcdata, options)
    numeric = {
        "electronic_energy_hartree": result.scf_energy,
        "zero_point_energy_hartree": result.zpe,
        "raw_enthalpy_hartree": result.enthalpy,
        "treated_enthalpy_hartree": (
            result.qh_enthalpy
            if policy["qrrho_enthalpy_treatment"] == "head_gordon"
            else result.enthalpy
        ),
        "raw_entropy_hartree_per_kelvin": result.entropy,
        "treated_entropy_hartree_per_kelvin": result.qh_entropy,
        "raw_gibbs_free_energy_hartree": result.gibbs_free_energy,
        "treated_gibbs_free_energy_hartree": result.qh_gibbs_free_energy,
    }
    if any(type(value) not in {int, float} or not math.isfinite(float(value)) for value in numeric.values()):
        raise RuntimeError("GoodVibes returned missing or non-finite thermochemistry")
    symmetry_number = getattr(qcdata, "symmno", None)
    if type(symmetry_number) is not int or symmetry_number != reported_symmetry_number:
        raise RuntimeError("GoodVibes QCData symmetry number disagrees with the explicit raw Gaussian log")
    return {
        "member_id": member_id,
        "source_provenance": {
            "source_result_id": source_result_id,
            "source_result_payload_sha256": source_result_payload_sha256,
            "source_gaussian_log_sha256": source_gaussian_log_sha256,
            "result_contract_identity": result_contract_identity,
            "evidence_disposition": evidence_disposition,
            "output_reported_point_group": result.point_group,
            "symmetry_provenance": {
                "symmetry_policy": {
                    "mode": "gaussian_output_required",
                    "external_detection": "disabled",
                },
                "goodvibes_symm": policy["goodvibes_symm"],
                "reported_rotational_symmetry_number": reported_symmetry_number,
                "explicit_symmetry_observation_count": symmetry_observation_count,
                "raw_gaussian_log_sha256": source_gaussian_log_sha256,
                "goodvibes_parsed_symmno": symmetry_number,
            },
        },
        "method_compatibility_binding": method_compatibility_binding,
        "temperature_k": policy["temperature_k"],
        "standard_state": policy["standard_state"],
        "thermochemistry_policy": policy,
        "raw_rrho": {
            "electronic_energy_hartree": numeric["electronic_energy_hartree"],
            "zero_point_energy_hartree": numeric["zero_point_energy_hartree"],
            "enthalpy_hartree": numeric["raw_enthalpy_hartree"],
            "entropy_hartree_per_kelvin": numeric["raw_entropy_hartree_per_kelvin"],
            "gibbs_free_energy_hartree": numeric["raw_gibbs_free_energy_hartree"],
        },
        "treated_qrrho": {
            "enthalpy_hartree": numeric["treated_enthalpy_hartree"],
            "entropy_hartree_per_kelvin": numeric["treated_entropy_hartree_per_kelvin"],
            "gibbs_free_energy_hartree": numeric["treated_gibbs_free_energy_hartree"],
            "entropy_treatment": policy["qrrho_entropy_method"],
            "enthalpy_treatment": policy["qrrho_enthalpy_treatment"],
        },
        "degeneracy": degeneracy,
        "degeneracy_rationale": degeneracy_rationale,
    }
