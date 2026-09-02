"""Private, zero-effect V31 authority for two-stage conformer DFT lineage."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
from fractions import Fraction
from hashlib import sha256
from math import isfinite
import re

from auto_g16.core import CalculationPlan, SQLiteRuntimeStore
from auto_g16.execution import PreparedInputBinding
from auto_g16.result import InputBinding, OutputEnvelope, ParseOutcome
from auto_g16.review import ReviewAcceptanceState, ReviewBundle, build_review_bundle
from auto_g16.scientific_validation import (
    MinimumValidationClassification,
    SQLiteScientificValidationStore,
)

from .models import ConformerEnsemble, _freeze_mapping, _identified_payload, _payload_sha256


_METHOD_KEYS = {
    "program", "method", "basis", "dispersion", "solvent", "reference",
    "charge", "multiplicity", "integration_grid", "scf_policy",
    "route_contract_version",
}
_SOURCE_KEYS = {
    "conformer_ensemble_id", "conformer_ensemble_payload_sha256",
    "sampling_profile_id", "sampling_profile_payload_sha256", "member_id",
    "member_payload_sha256", "canonical_atom_order_sha256",
    "source_atom_map_sha256", "source_geometry_sha256",
    "species_binding_sha256", "stereochemistry_binding_sha256",
}
_INPUT_KEYS = {"input_format", "logical_name", "sha256", "size_bytes"}
_SUPPORTED_RESULT_TUPLES = {
    ("auto-g16-v3-gaussian-job", "1.0.0", "gaussian-job-facts"),
    ("auto-g16-v3-gaussian-job", "1.1.0", "gaussian-job-facts"),
}
_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9+*()._-]*$")
_REFERENCE_METHOD = re.compile(r"^(RO|R|U)(HF|B3LYP)$")
_ELEMENTS = (
    "H", "He", "Li", "Be", "B", "C", "N", "O", "F", "Ne", "Na", "Mg",
    "Al", "Si", "P", "S", "Cl", "Ar", "K", "Ca", "Sc", "Ti", "V", "Cr",
    "Mn", "Fe", "Co", "Ni", "Cu", "Zn", "Ga", "Ge", "As", "Se", "Br", "Kr",
    "Rb", "Sr", "Y", "Zr", "Nb", "Mo", "Tc", "Ru", "Rh", "Pd", "Ag", "Cd",
    "In", "Sn", "Sb", "Te", "I", "Xe", "Cs", "Ba", "La", "Ce", "Pr", "Nd",
    "Pm", "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er", "Tm", "Yb", "Lu", "Hf",
    "Ta", "W", "Re", "Os", "Ir", "Pt", "Au", "Hg", "Tl", "Pb", "Bi", "Po",
    "At", "Rn", "Fr", "Ra", "Ac", "Th", "Pa", "U", "Np", "Pu", "Am", "Cm",
    "Bk", "Cf", "Es", "Fm", "Md", "No", "Lr", "Rf", "Db", "Sg", "Bh", "Hs",
    "Mt", "Ds", "Rg", "Cn", "Nh", "Fl", "Mc", "Lv", "Ts", "Og",
)
_ATOMIC_NUMBER = {symbol: index for index, symbol in enumerate(_ELEMENTS, 1)}


class RefinementAuthorityError(ValueError):
    """The supplied private two-stage authority is incomplete or spliced."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RefinementAuthorityError(message)


def _text(value: object, name: str) -> str:
    _require(isinstance(value, str) and bool(value) and value == value.strip(), f"{name} must be canonical text")
    return value


def _exact_keys(value: object, keys: set[str], name: str) -> Mapping[str, object]:
    _require(isinstance(value, Mapping) and set(value) == keys, f"{name} has a non-closed field set")
    return value


def _ensemble_closed(ensemble: ConformerEnsemble) -> None:
    _require(type(ensemble) is ConformerEnsemble, "ensemble must be a ConformerEnsemble")
    identity, payload = _identified_payload("conformer-ensemble", ensemble._identity_payload())
    _require(identity == ensemble.conformer_ensemble_id and payload == ensemble.payload_sha256, "ensemble identity is stale")


def _member(ensemble: ConformerEnsemble, member_id: str) -> Mapping[str, object]:
    _ensemble_closed(ensemble)
    _text(member_id, "member_id")
    matches = tuple(item for item in ensemble.members if item.get("member_id") == member_id)
    _require(len(matches) == 1, "member_id must resolve exactly once inside the ensemble")
    return matches[0]


def _source(ensemble: ConformerEnsemble, member: Mapping[str, object]) -> Mapping[str, object]:
    species = ensemble.species_binding
    coordinates = member.get("coordinates_angstrom")
    _require(isinstance(coordinates, tuple), "member coordinates are unavailable")
    source = {
        "conformer_ensemble_id": ensemble.conformer_ensemble_id,
        "conformer_ensemble_payload_sha256": ensemble.payload_sha256,
        "sampling_profile_id": ensemble.sampling_profile_id,
        "sampling_profile_payload_sha256": ensemble.sampling_profile_payload_sha256,
        "member_id": member["member_id"],
        "member_payload_sha256": _payload_sha256(member),
        "canonical_atom_order_sha256": _payload_sha256(species["atom_order"]),
        "source_atom_map_sha256": _payload_sha256(species["atom_mapping"]),
        "source_geometry_sha256": _payload_sha256(coordinates),
        "species_binding_sha256": _payload_sha256(species),
        "stereochemistry_binding_sha256": _payload_sha256(ensemble.stereochemistry_binding),
    }
    return source


def _method(ensemble: ConformerEnsemble, supplied: Mapping[str, object]) -> tuple[Mapping[str, object], str]:
    value = _exact_keys(supplied, _METHOD_KEYS, "method_binding")
    for key in ("program", "method", "basis", "dispersion", "solvent", "reference", "integration_grid", "scf_policy", "route_contract_version"):
        token = _text(value[key], f"method_binding.{key}")
        _require(bool(_TOKEN.fullmatch(token)), f"method_binding.{key} is not a closed token")
    species = ensemble.species_binding
    _require(value["program"] == "gaussian16", "program must be gaussian16")
    _require(value["dispersion"] == "none", "dispersion must be explicit none")
    _require(value["solvent"] == "gas", "solvent must be explicit gas")
    _require(value["reference"] == "restricted_closed_shell", "reference must be restricted_closed_shell")
    _require(value["route_contract_version"] == "auto_g16_v31_conformer_dft_route_1", "route contract version is unsupported")
    _require(type(value["charge"]) is int and value["charge"] == species["formal_charge"], "method charge does not match species")
    _require(type(value["multiplicity"]) is int and value["multiplicity"] == 1 and species["multiplicity"] == 1, "only exact singlet multiplicity is supported")
    _require(species["electronic_state_family"] == "reviewed_closed_shell_singlet", "only reviewed closed-shell singlets are supported")
    match = _REFERENCE_METHOD.fullmatch(value["method"])
    reference_family = (
        {"R": "restricted", "U": "unrestricted", "RO": "restricted-open-shell"}[match.group(1)]
        if match is not None
        else "unknown"
    )
    _require(reference_family == "restricted", "route method reference family is not restricted")
    return value, _payload_sha256({
        "domain": "v31-conformer-dft-method/1",
        "method": value,
        "reference_family": reference_family,
    })


def _coordinates_from_member(ensemble: ConformerEnsemble, member: Mapping[str, object]) -> tuple[tuple[object, object, object], ...]:
    coordinates = member["coordinates_angstrom"]
    elements = ensemble.species_binding["elements"]
    _require(isinstance(coordinates, tuple) and isinstance(elements, tuple) and len(coordinates) == len(elements), "source coordinates do not match atom inventory")
    answer = []
    for point in coordinates:
        _require(isinstance(point, tuple) and len(point) == 3 and all(type(item) in {int, float} and isfinite(item) for item in point), "source coordinates must be finite Cartesian triples")
        answer.append(tuple(point))
    return tuple(answer)  # type: ignore[return-value]


def _coordinates_from_geometry(geometry: Mapping[str, object], elements: Sequence[object]) -> tuple[tuple[float, float, float], ...]:
    atoms = geometry.get("atoms")
    _require(isinstance(atoms, tuple) and len(atoms) == len(elements), "selected geometry atom inventory differs")
    result = []
    for index, (atom, element) in enumerate(zip(atoms, elements), 1):
        _require(isinstance(atom, Mapping) and set(atom) == {"center", "atomic_number", "x", "y", "z"}, "selected geometry atom shape is not exact")
        _require(atom["center"] == index and _ATOMIC_NUMBER.get(element) == atom["atomic_number"], "selected geometry cannot recover the exact source atom order")
        xyz = (atom["x"], atom["y"], atom["z"])
        _require(all(type(item) is float and isfinite(item) for item in xyz), "selected geometry contains invalid coordinates")
        result.append(xyz)
    return tuple(result)  # type: ignore[return-value]


def _expected_frequency_mode_count(
    geometry: Mapping[str, object],
    elements: Sequence[object],
) -> int:
    coordinates = _coordinates_from_geometry(geometry, elements)
    atom_count = len(coordinates)
    _require(atom_count >= 3, "initial V31 composite minimum authority supports only N>=3 ordinary nonlinear geometries")
    points = tuple(
        tuple(Fraction(Decimal(repr(component))) for component in point)
        for point in coordinates
    )
    _require(len(set(points)) == atom_count, "selected geometry is degenerate and cannot prove linearity")
    origin = points[0]
    direction = tuple(points[1][axis] - origin[axis] for axis in range(3))
    _require(any(component != 0 for component in direction), "selected geometry cannot prove a linear direction")
    linear = True
    for point in points[2:]:
        offset = tuple(point[axis] - origin[axis] for axis in range(3))
        cross = (
            direction[1] * offset[2] - direction[2] * offset[1],
            direction[2] * offset[0] - direction[0] * offset[2],
            direction[0] * offset[1] - direction[1] * offset[0],
        )
        if any(component != 0 for component in cross):
            linear = False
            break
    _require(not linear, "linear geometry is unsupported by initial V31 composite minimum authority")
    return 3 * atom_count - 6


def _render(stage: str, elements: Sequence[object], coordinates: Sequence[Sequence[object]], method: Mapping[str, object]) -> bytes:
    keyword = "opt" if stage == "opt" else "freq"
    route = f"#p {method['method']}/{method['basis']} {keyword} integral={method['integration_grid']} scf={method['scf_policy']}"
    lines = [route, "", f"Auto-G16 V31 conformer DFT {stage}", "", f"{method['charge']} {method['multiplicity']}"]
    for element, point in zip(elements, coordinates):
        _require(element in _ATOMIC_NUMBER, "source element is unsupported")
        lines.append(f"{element} {repr(point[0])} {repr(point[1])} {repr(point[2])}")
    return ("\n".join(lines) + "\n\n").encode("ascii")


def _authority_id(domain: str, payload: Mapping[str, object]) -> str:
    return f"{domain}-{_payload_sha256({'domain': domain, 'payload': payload})}"


def build_dft_stage(
    ensemble: ConformerEnsemble,
    member_id: str,
    *,
    stage: str,
    calculation_plan_id: str,
    calculation_plan_revision: int,
    task_id: str,
    attempt_id: str,
    logical_name: str,
    method_binding: Mapping[str, object],
    optimization_geometry_authority: Mapping[str, object] | None = None,
) -> tuple[CalculationPlan, PreparedInputBinding, bytes]:
    """Build inert exact V30 plan/input values; it grants no execution authority."""

    _require(stage in {"opt", "freq"}, "stage must be opt or freq")
    member = _member(ensemble, member_id)
    source = _source(ensemble, member)
    method, method_id = _method(ensemble, method_binding)
    elements = ensemble.species_binding["elements"]
    if stage == "opt":
        _require(optimization_geometry_authority is None, "opt must not consume an optimization authority")
        coordinates = _coordinates_from_member(ensemble, member)
        predecessor = None
        schema = "v31-conformer-dft-opt/1"
    else:
        authority = _exact_keys(optimization_geometry_authority, {
            "authority_schema", "optimization_geometry_authority_id", "source", "method_id",
            "calculation_plan", "prepared_input", "result", "selected_geometry",
            "recovered_atom_map", "v30_outcome",
        }, "optimization_geometry_authority")
        payload = {key: authority[key] for key in authority if key != "optimization_geometry_authority_id"}
        _require(authority["optimization_geometry_authority_id"] == _authority_id("v31-opt-geometry-authority", payload), "optimization authority identity is stale")
        _require(authority["source"] == source and authority["method_id"] == method_id, "frequency source differs from optimization authority")
        geometry = authority["selected_geometry"]
        _require(isinstance(geometry, Mapping), "optimization selected geometry is absent")
        coordinates = _coordinates_from_geometry(geometry, elements)  # type: ignore[arg-type]
        result = _exact_keys(authority["result"], {
            "result_id", "result_payload_sha256", "source_artifact", "job_section",
            "accepted_optimization_span", "accepted_stationary_span",
        }, "optimization_geometry_authority.result")
        source_artifact = _exact_keys(result["source_artifact"], {
            "envelope_observation_id", "artifact_kind", "logical_name", "sha256",
            "size_bytes",
        }, "optimization_geometry_authority.result.source_artifact")
        predecessor = {
            "optimization_geometry_authority_id": authority["optimization_geometry_authority_id"],
            "optimization_geometry_sha256": _payload_sha256(geometry),
            "optimization_result_id": result["result_id"],
            "optimization_source_artifact_sha256": source_artifact["sha256"],
            "optimization_selected_geometry_span_sha256": _payload_sha256(geometry["source_span"]),
        }
        schema = "v31-conformer-dft-freq/1"
    prepared_bytes = _render(stage, elements, coordinates, method)  # type: ignore[arg-type]
    input_authority = {"input_format": "gaussian-gjf", "logical_name": _text(logical_name, "logical_name"), "sha256": sha256(prepared_bytes).hexdigest(), "size_bytes": len(prepared_bytes)}
    intent = {"schema": schema, "source": source, "method_binding": method, "method_id": method_id, "input": input_authority}
    if predecessor is not None:
        intent["optimization_source"] = predecessor
    plan = CalculationPlan(calculation_plan_id=_text(calculation_plan_id, "calculation_plan_id"), task_id=_text(task_id, "task_id"), revision=calculation_plan_revision, intent=intent)
    prepared = PreparedInputBinding(attempt_id=_text(attempt_id, "attempt_id"), calculation_plan_id=plan.calculation_plan_id, calculation_plan_revision=plan.revision, input_format="gaussian-gjf", logical_name=logical_name, prepared_bytes=prepared_bytes)
    return plan, prepared, prepared_bytes


def _check_plan_and_input(ensemble: ConformerEnsemble, member: Mapping[str, object], stage: str, plan: CalculationPlan, prepared: PreparedInputBinding, prepared_bytes: bytes) -> tuple[Mapping[str, object], str]:
    expected_keys = {"schema", "source", "method_binding", "method_id", "input"} | ({"optimization_source"} if stage == "freq" else set())
    intent = _exact_keys(plan.intent, expected_keys, "CalculationPlan.intent")
    _require(intent["schema"] == f"v31-conformer-dft-{stage}/1", "CalculationPlan intent schema is ineligible")
    _require(intent["source"] == _source(ensemble, member), "CalculationPlan source authority is spliced")
    method, method_id = _method(ensemble, intent["method_binding"])  # type: ignore[arg-type]
    _require(intent["method_id"] == method_id, "method identity is stale")
    try:
        prepared.assert_identity_closed()
        prepared.verify_bytes(prepared_bytes)
    except Exception as exc:
        raise RefinementAuthorityError("PreparedInputBinding identity or bytes do not close") from exc
    _require(prepared.calculation_plan_id == plan.calculation_plan_id and prepared.calculation_plan_revision == plan.revision, "PreparedInputBinding names another plan")
    expected_input = {"input_format": prepared.input_format, "logical_name": prepared.logical_name, "sha256": prepared.sha256, "size_bytes": prepared.size_bytes}
    _require(intent["input"] == expected_input, "CalculationPlan input authority is spliced")
    return method, method_id


def _check_review(plan: CalculationPlan, prepared: PreparedInputBinding, review: ReviewBundle) -> tuple[Mapping[str, object], Mapping[str, object], Mapping[str, object]]:
    _require(type(review) is ReviewBundle, "review must be a ReviewBundle")
    review._assert_identity()
    _require(review.calculation_plan == {"calculation_plan_id": plan.calculation_plan_id, "task_id": plan.task_id, "revision": plan.revision, "intent": plan.intent}, "ReviewBundle names another CalculationPlan")
    _require(review.attempt["attempt_id"] == prepared.attempt_id and review.attempt["task_id"] == plan.task_id, "ReviewBundle Attempt is spliced")
    expected_input = prepared.semantic_payload()
    _require(review.input_binding["observation_id"] and all(review.input_binding[key] == expected_input[key] for key in expected_input), "Result InputBinding differs from PreparedInputBinding")
    _require(review.output_envelope["input_binding_observation_id"] == review.input_binding["observation_id"], "OutputEnvelope input authority is spliced")
    _require(review.output_envelope["capture_status"] == "captured" and review.output_envelope["capture_completeness"] == "complete", "Result capture is not captured and complete")
    parsed = review.parse_outcome
    _require(parsed["attempt_id"] == prepared.attempt_id and parsed["envelope_observation_id"] == review.output_envelope["observation_id"], "ParseOutcome provenance is spliced")
    _require(parsed["parse_status"] == "parsed" and (parsed["parser_name"], parsed["parser_version"], parsed["result_kind"]) in _SUPPORTED_RESULT_TUPLES, "ParseOutcome is not a supported parsed Gaussian result")
    facts = parsed["facts"]
    _require(isinstance(facts, Mapping), "ParseOutcome facts are missing")
    source = facts["source_artifact"]
    artifacts = tuple(item for item in review.output_envelope["artifacts"] if item["artifact_kind"] == "gaussian-log")  # type: ignore[index]
    _require(len(artifacts) == 1 and all(source[key] == artifacts[0][key] for key in ("artifact_kind", "logical_name", "sha256", "size_bytes")) and source["envelope_observation_id"] == review.output_envelope["observation_id"], "Gaussian source artifact is spliced")
    return parsed, facts, source


def _persisted_review(
    core_store: SQLiteRuntimeStore,
    validation_store: SQLiteScientificValidationStore,
    *,
    input_binding: InputBinding,
    output_envelope: OutputEnvelope,
    parse_outcome: ParseOutcome,
    minimum_validation_outcome_id: str,
) -> ReviewBundle:
    try:
        return build_review_bundle(
            core_store,
            validation_store,
            input_binding=input_binding,
            output_envelope=output_envelope,
            parse_outcome=parse_outcome,
            minimum_validation_outcome_id=minimum_validation_outcome_id,
        )
    except Exception as exc:
        raise RefinementAuthorityError("persisted Result/SV/Review chain does not close") from exc


def validate_optimization_geometry_authority(
    ensemble: ConformerEnsemble,
    member_id: str,
    *,
    calculation_plan: CalculationPlan,
    prepared_input_binding: PreparedInputBinding,
    prepared_input_bytes: bytes,
    core_store: SQLiteRuntimeStore,
    validation_store: SQLiteScientificValidationStore,
    input_binding: InputBinding,
    output_envelope: OutputEnvelope,
    parse_outcome: ParseOutcome,
    minimum_validation_outcome_id: str,
) -> Mapping[str, object]:
    member = _member(ensemble, member_id)
    _method_value, method_id = _check_plan_and_input(ensemble, member, "opt", calculation_plan, prepared_input_binding, prepared_input_bytes)
    review_bundle = _persisted_review(
        core_store,
        validation_store,
        input_binding=input_binding,
        output_envelope=output_envelope,
        parse_outcome=parse_outcome,
        minimum_validation_outcome_id=minimum_validation_outcome_id,
    )
    parsed, facts, source = _check_review(calculation_plan, prepared_input_binding, review_bundle)
    _require(facts["program_status"] == "normal-termination" and facts["normal_termination_count"] == 1 and facts["error_termination_count"] == 0, "optimization Result did not close with one exact normal termination")
    _require(review_bundle.minimum_validation_classification is MinimumValidationClassification.INCOMPLETE and review_bundle.primary_reason_code == "incomplete-mode-count", "optimization V30 outcome is not the exact expected incomplete-mode-count")
    outcome = review_bundle.minimum_validation_outcome
    _require(outcome["accepted_optimization_span"] is not None and outcome["accepted_stationary_span"] is not None and review_bundle.selected_final_geometry is not None, "optimization geometry authority is incomplete")
    _require(facts["frequency_count"] == 0 and not facts["frequencies_cm-1"] and not facts["frequency_blocks"] and facts["imaginary_frequency_count"] == 0, "optimization Result must be a pure frequency-free stage")
    _require(not review_bundle.selected_frequency_blocks and not review_bundle.selected_frequencies_cm1 and review_bundle.scientific_acceptance_state is ReviewAcceptanceState.INELIGIBLE and not review_bundle.scientific_acceptances, "optimization authority must not claim a minimum or ScientificAcceptance")
    geometry = review_bundle.selected_final_geometry
    recovered = tuple(
        {
            "center": index,
            "source_atom_id": ensemble.species_binding["atom_mapping"][map_id],
            "canonical_map_id": map_id,
            "atomic_number": _ATOMIC_NUMBER[element],
        }
        for index, (map_id, element) in enumerate(
            zip(ensemble.species_binding["atom_order"], ensemble.species_binding["elements"]),
            1,
        )
    )
    _coordinates_from_geometry(geometry, ensemble.species_binding["elements"])
    result = {"result_id": parsed["result_id"], "result_payload_sha256": _payload_sha256(parsed), "source_artifact": source, "job_section": facts["job_section"], "accepted_optimization_span": outcome["accepted_optimization_span"], "accepted_stationary_span": outcome["accepted_stationary_span"]}
    payload = {"authority_schema": "v31-conformer-optimization-geometry-authority/1", "source": _source(ensemble, member), "method_id": method_id, "calculation_plan": {"calculation_plan_id": calculation_plan.calculation_plan_id, "revision": calculation_plan.revision, "intent_sha256": _payload_sha256(calculation_plan.intent)}, "prepared_input": prepared_input_binding.semantic_payload(), "result": result, "selected_geometry": geometry, "recovered_atom_map": recovered, "v30_outcome": {"minimum_validation_outcome_id": outcome["minimum_validation_outcome_id"], "classification": "INCOMPLETE", "reason_code": "incomplete-mode-count"}}
    identity = _authority_id("v31-opt-geometry-authority", payload)
    return _freeze_mapping({**payload, "optimization_geometry_authority_id": identity}, "optimization_geometry_authority")


def validate_two_stage_minimum_authority(
    ensemble: ConformerEnsemble,
    member_id: str,
    *,
    optimization_plan: CalculationPlan,
    optimization_prepared_input_binding: PreparedInputBinding,
    optimization_prepared_input_bytes: bytes,
    optimization_core_store: SQLiteRuntimeStore,
    optimization_validation_store: SQLiteScientificValidationStore,
    optimization_input_binding: InputBinding,
    optimization_output_envelope: OutputEnvelope,
    optimization_parse_outcome: ParseOutcome,
    optimization_minimum_validation_outcome_id: str,
    frequency_plan: CalculationPlan,
    frequency_prepared_input_binding: PreparedInputBinding,
    frequency_prepared_input_bytes: bytes,
    frequency_core_store: SQLiteRuntimeStore,
    frequency_validation_store: SQLiteScientificValidationStore,
    frequency_input_binding: InputBinding,
    frequency_output_envelope: OutputEnvelope,
    frequency_parse_outcome: ParseOutcome,
    frequency_minimum_validation_outcome_id: str,
) -> Mapping[str, object]:
    member = _member(ensemble, member_id)
    opt = validate_optimization_geometry_authority(
        ensemble,
        member_id,
        calculation_plan=optimization_plan,
        prepared_input_binding=optimization_prepared_input_binding,
        prepared_input_bytes=optimization_prepared_input_bytes,
        core_store=optimization_core_store,
        validation_store=optimization_validation_store,
        input_binding=optimization_input_binding,
        output_envelope=optimization_output_envelope,
        parse_outcome=optimization_parse_outcome,
        minimum_validation_outcome_id=optimization_minimum_validation_outcome_id,
    )
    _method_value, method_id = _check_plan_and_input(ensemble, member, "freq", frequency_plan, frequency_prepared_input_binding, frequency_prepared_input_bytes)
    _require(frequency_plan.intent["method_id"] == opt["method_id"], "Opt/Freq method identities differ")
    source_link = _exact_keys(frequency_plan.intent["optimization_source"], {
        "optimization_geometry_authority_id", "optimization_geometry_sha256",
        "optimization_result_id", "optimization_source_artifact_sha256",
        "optimization_selected_geometry_span_sha256",
    }, "CalculationPlan.intent.optimization_source")
    expected_source_link = {
        "optimization_geometry_authority_id": opt["optimization_geometry_authority_id"],
        "optimization_geometry_sha256": _payload_sha256(opt["selected_geometry"]),
        "optimization_result_id": opt["result"]["result_id"],
        "optimization_source_artifact_sha256": opt["result"]["source_artifact"]["sha256"],
        "optimization_selected_geometry_span_sha256": _payload_sha256(opt["selected_geometry"]["source_span"]),
    }
    _require(source_link == expected_source_link, "Freq plan does not consume the exact Opt geometry lineage")
    frequency_review_bundle = _persisted_review(
        frequency_core_store,
        frequency_validation_store,
        input_binding=frequency_input_binding,
        output_envelope=frequency_output_envelope,
        parse_outcome=frequency_parse_outcome,
        minimum_validation_outcome_id=frequency_minimum_validation_outcome_id,
    )
    parsed, facts, source = _check_review(frequency_plan, frequency_prepared_input_binding, frequency_review_bundle)
    _require(facts["program_status"] == "normal-termination" and facts["normal_termination_count"] == 1 and facts["error_termination_count"] == 0, "frequency Result did not close with one exact normal termination")
    _require(facts["optimization_completed_marker"] is False and not facts["optimization_completed_evidence"] and facts["stationary_point_marker"] is False and not facts["stationary_point_evidence"], "frequency Result must be a pure frequency-only stage")
    _require(facts["frequency_parse_complete"] is True, "frequency parsing is incomplete")
    blocks = facts["frequency_blocks"]
    frequencies = tuple(value for block in blocks for value in block["frequencies_cm-1"])
    expected_modes = _expected_frequency_mode_count(opt["selected_geometry"], ensemble.species_binding["elements"])
    _require(facts["frequency_count"] == len(frequencies) == expected_modes, "frequency mode count does not match the initial V31 nonlinear domain")
    _require(facts["imaginary_frequency_count"] == sum(value < 0.0 for value in frequencies) == 0, "frequency result is not a minimum")
    _require(frequency_review_bundle.minimum_validation_classification is MinimumValidationClassification.INCOMPLETE and frequency_review_bundle.primary_reason_code == "incomplete-marker-pair", "Freq V30 outcome must truthfully retain incomplete-marker-pair")
    for block in blocks:
        span = block["source_span"]
        _require(all(span[key] == source[key] for key in source) and facts["job_section"]["start"] <= span["start"] < span["end"] <= facts["job_section"]["end"], "frequency block is not source-bound")
    frequency_result = {"result_id": parsed["result_id"], "result_payload_sha256": _payload_sha256(parsed), "source_artifact": source, "job_section": facts["job_section"], "frequency_blocks": blocks, "frequencies_cm1": frequencies, "mode_count": len(frequencies), "v30_outcome": {"minimum_validation_outcome_id": frequency_review_bundle.minimum_validation_outcome["minimum_validation_outcome_id"], "classification": "INCOMPLETE", "reason_code": "incomplete-marker-pair"}}
    payload = {"authority_schema": "v31-conformer-two-stage-minimum-authority/1", "source": _source(ensemble, member), "method_id": method_id, "optimization": opt, "frequency": {"calculation_plan": {"calculation_plan_id": frequency_plan.calculation_plan_id, "revision": frequency_plan.revision, "intent_sha256": _payload_sha256(frequency_plan.intent)}, "prepared_input": frequency_prepared_input_binding.semantic_payload(), "result": frequency_result}, "classification": "VALIDATED_TWO_STAGE_MINIMUM"}
    identity = _authority_id("v31-two-stage-minimum-authority", payload)
    return _freeze_mapping({**payload, "two_stage_minimum_authority_id": identity}, "two_stage_minimum_authority")
