#!/usr/bin/env python3
"""Normalize reaction energies and derive bounded offline study analyses.

This module consumes reviewed, hash-bound workflow artifacts.  It performs
deterministic thermochemistry aggregation, Eyring comparisons, explicit
selectivity normalization, uncertainty scenarios, and bounded report
rendering.  It never chooses chemistry or a computational method, invokes
Gaussian/SSH/PBS, authorizes submission, or turns synthetic fixtures into
scientific evidence.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import sys
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import mechanism_network as mn  # noqa: E402
import reaction_orchestrator as orchestrator  # noqa: E402
import reaction_workflow as rw  # noqa: E402


ENERGY_REVIEW_SCHEMA = "gaussian-reaction-energy-record-review/1"
ENERGY_SCHEMA = "gaussian-reaction-energy-record/1"
ANALYSIS_REVIEW_SCHEMA = "gaussian-reaction-analysis-review/1"
ANALYSIS_SCHEMA = "gaussian-reaction-analysis/1"
REPORT_REVIEW_SCHEMA = "gaussian-reaction-report-review/1"
REPORT_SCHEMA = "gaussian-reaction-bounded-report/1"
SYNTHETIC_RESULT_SCHEMA = "gaussian-reaction-synthetic-energy-evidence/1"

HARTREE_TO_KCAL_MOL = 627.5094740631
R_KCAL_MOL_K = 0.00198720425864083
KB_OVER_H_K_INV_S_INV = 2.083661912e10
STANDARD_STATES = {"1M", "1atm", "explicit_custom"}
REAL_RESULT_SCHEMAS = {
    "gaussian-opt-freq-sp-result/1",
    "gaussian-asymmetric-ts-result/1",
}
FORMAL_NONCOMPARABLE_ENERGY_SCHEMAS = {
    "gaussian-reviewed-energy-record/1",
    "gaussian-energy-lineage/1",
}

REAL_SOURCE_FIELD_BINDINGS = {
    "gaussian-opt-freq-sp-result/1": {
        "electronic_energy_hartree": "/thermochemistry/single_point_energy_hartree",
        "thermal_gibbs_correction_hartree": "/thermochemistry/thermal_correction_gibbs_hartree",
        "temperature_k": "/thermochemistry/temperature_k",
        "standard_state": "/thermochemistry/standard_state",
        "optimization_success": "/optimization_success",
        "normal_termination": "/normal_termination",
        "imaginary_frequency_count": "/imaginary_frequency_count",
    },
    "gaussian-asymmetric-ts-result/1": {
        "electronic_energy_hartree": "/energies/electronic_energy",
        "thermal_gibbs_correction_hartree": "/energies/thermal_gibbs_correction",
        "temperature_k": "/energies/temperature_k",
        "standard_state": "/energies/standard_state",
        "optimization_success": "/termination/stationary_point",
        "normal_termination": "/termination/normal_termination",
        "imaginary_frequency_count": "/frequency_evidence/raw_imaginary_frequency_count",
    },
}


def _exact(value: Any, keys: set[str], label: str) -> dict[str, Any]:
    rw.require(isinstance(value, dict), f"{label} must be an object")
    rw._require_exact_keys(value, keys, keys, label)
    return value


def _finite(value: Any, label: str) -> float:
    rw.require(rw._finite_number(value), f"{label} must be finite")
    return float(value)


def _nonnegative_integer(value: Any, label: str) -> int:
    rw.require(isinstance(value, int) and not isinstance(value, bool) and value >= 0, f"{label} must be a non-negative integer")
    return value


def _json_pointer(document: Any, pointer: Any, label: str) -> Any:
    pointer_text = rw._require_string(pointer, label)
    rw.require(pointer_text.startswith("/"), f"{label} must be an absolute JSON pointer")
    current = document
    for raw_token in pointer_text[1:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            rw.require(token in current, f"{label} does not resolve: {pointer_text}")
            current = current[token]
        elif isinstance(current, list):
            rw.require(token.isdigit(), f"{label} contains a non-numeric array index")
            index = int(token)
            rw.require(index < len(current), f"{label} array index is out of range")
            current = current[index]
        else:
            raise rw.OfflineError(f"{label} traverses a scalar value")
    return current


def _review_file_ref(reference: Any, owner: Path, label: str) -> tuple[Path, dict[str, Any]]:
    ref = _exact(reference, {"path", "sha256", "size_bytes"}, label)
    path = orchestrator._resolve(ref["path"], owner, label)
    rw.require(ref["sha256"] == rw.sha256_file(path) and ref["size_bytes"] == path.stat().st_size, f"{label} identity mismatch")
    return path, rw.load_json(path)


def _nullable_review_file_ref(reference: Any, owner: Path, label: str) -> tuple[Path | None, dict[str, Any] | None, dict[str, Any] | None]:
    if reference is None:
        return None, None, None
    path, data = _review_file_ref(reference, owner, label)
    return path, data, orchestrator._file_ref(path, data)


def _verify_file_artifact(reference: Any, owner: Path, label: str) -> tuple[Path, dict[str, Any]]:
    ref = _exact(reference, {"path", "sha256", "size_bytes", "schema"}, label)
    path = orchestrator._resolve(ref["path"], owner, label)
    rw.require(ref["sha256"] == rw.sha256_file(path) and ref["size_bytes"] == path.stat().st_size, f"{label} identity mismatch")
    data = rw.load_json(path)
    rw.require(data.get("schema") == ref["schema"], f"{label} schema mismatch")
    return path, data


def _mode_evidence(
    source_path: Path,
    source: dict[str, Any],
    source_schema: str,
    mode_review_raw: Any,
    mode_decision_raw: Any,
    review_path: Path,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, bool]:
    review_file, review, review_ref = _nullable_review_file_ref(mode_review_raw, review_path, "mode review")
    decision_file, decision, decision_ref = _nullable_review_file_ref(mode_decision_raw, review_path, "mode decision")
    rw.require((review is None) == (decision is None), "mode review and mode decision must be supplied together")
    if review is None or decision is None or review_file is None or decision_file is None:
        return None, None, False
    expected_ts_result_sha256 = rw.sha256_file(source_path)
    if source_schema == "gaussian-asymmetric-ts-result/1":
        artifacts = source.get("artifacts")
        rw.require(isinstance(artifacts, dict), "asymmetric TS result lacks its artifact lineage")
        parsed_ref = artifacts.get("parsed_ts_result")
        aggregate_review_ref = artifacts.get("mode_review")
        aggregate_decision_ref = artifacts.get("mode_decision")
        rw.require(isinstance(parsed_ref, dict) and set(parsed_ref) == {"path", "sha256"}, "asymmetric TS result lacks a closed parsed-TS artifact reference")
        parsed_path = orchestrator._resolve(parsed_ref["path"], source_path, "asymmetric parsed TS result")
        rw.require(parsed_ref["sha256"] == rw.sha256_file(parsed_path), "asymmetric parsed TS result hash mismatch")
        expected_ts_result_sha256 = parsed_ref["sha256"]
        rw.require(isinstance(aggregate_review_ref, dict) and aggregate_review_ref.get("sha256") == rw.sha256_file(review_file), "supplied mode review differs from the asymmetric TS result lineage")
        rw.require(isinstance(aggregate_decision_ref, dict) and aggregate_decision_ref.get("sha256") == rw.sha256_file(decision_file), "supplied mode decision differs from the asymmetric TS result lineage")
    rw.require(review.get("schema") == "gaussian-ts-mode-review/1", "unrecognized TS mode-review schema")
    rw.require(review.get("ts_result_sha256") == expected_ts_result_sha256, "mode review is not bound to the source TS result")
    rw.require(decision.get("schema") == "gaussian-ts-mode-decision/1", "unrecognized TS mode-decision schema")
    rw.require(decision.get("ts_result_sha256") == expected_ts_result_sha256, "mode decision is not bound to the source TS result")
    rw.require(decision.get("mode_review_sha256") == rw.sha256_file(review_file), "mode decision is not bound to its mode review")
    accepted = decision.get("decision") == "accepted" and decision.get("confirmed") is True
    return review_ref, decision_ref, accepted


def _validate_real_source_shape(source: dict[str, Any], source_schema: str, target_kind: str, fields: dict[str, Any]) -> None:
    """Fail closed on known parser semantics and canonical energy fields."""

    expected_fields = REAL_SOURCE_FIELD_BINDINGS[source_schema]
    rw.require(fields == expected_fields, "reviewed calculation results must use the canonical source-field bindings for their schema")
    if source_schema == "gaussian-opt-freq-sp-result/1":
        rw.require(target_kind == "state", "Opt/Freq/single-point result records can normalize only mechanism states")
        rw.require(
            source.get("status") == "completed"
            and source.get("execution_complete") is True
            and source.get("frequency_complete") is True
            and source.get("minimum_validated") is True
            and source.get("workflow_success") is True,
            "minimum result does not satisfy the canonical completed-workflow evidence",
        )
    else:
        rw.require(target_kind == "edge", "asymmetric TS result records can normalize only mechanism edges")
        rw.require(
            source.get("validation_level") in {"mode_reviewed", "path_validated"}
            and source.get("comparison_eligibility", {}).get("eligible") is True,
            "TS result is not canonically eligible for energy comparison",
        )
        rw.require(source.get("energies", {}).get("energy_unit") == "hartree", "TS source energies must be expressed in hartree")


def build_energy_record(network_path: Path, dag_path: Path, review_path: Path, output: Path) -> dict[str, Any]:
    """Normalize one reviewed state or transition-state energy observation."""

    network_path = network_path.absolute()
    dag_path = dag_path.absolute()
    review_path = review_path.absolute()
    output = output.absolute()
    mn.validate(network_path)
    orchestrator.validate_dag(dag_path)
    network = rw.load_json(network_path)
    dag = rw.load_json(dag_path)
    rw.require(dag["mechanism_network"]["payload_sha256"] == network["payload_sha256"], "energy-record network/DAG binding mismatch")
    review = rw.load_json(review_path)
    keys = {
        "schema", "study_id", "mechanism_network_payload_sha256", "calculation_dag_payload_sha256",
        "record_id", "target_kind", "target_id", "dag_node_id", "conformer_id", "energy_model_id",
        "source_kind", "source_result", "source_fields", "standard_state_correction_kcal_mol",
        "low_frequency_correction_kcal_mol", "low_frequency_policy", "comparison_energy_definition",
        "degeneracy", "mode_review", "mode_decision", "review_decision", "review_notes",
    }
    _exact(review, keys, "energy-record review")
    rw.require(review["schema"] == ENERGY_REVIEW_SCHEMA, "energy-record review schema mismatch")
    rw.require(review["study_id"] == network["study_id"] == dag["study_id"], "energy-record study_id mismatch")
    rw.require(review["mechanism_network_payload_sha256"] == network["payload_sha256"], "energy-record mechanism-network hash mismatch")
    rw.require(review["calculation_dag_payload_sha256"] == dag["payload_sha256"], "energy-record calculation-DAG hash mismatch")

    record_id = rw._require_id(review["record_id"], "energy-record record_id")
    target_kind = rw._require_string(review["target_kind"], "energy-record target_kind")
    rw.require(target_kind in {"state", "edge"}, "energy-record target_kind is invalid")
    target_id = rw._require_id(review["target_id"], "energy-record target_id")
    known_targets = {item[f"{target_kind}_id"] for item in network[f"{target_kind}s"]}
    rw.require(target_id in known_targets, "energy-record target is absent from the mechanism network")
    dag_node_id = rw._require_id(review["dag_node_id"], "energy-record dag_node_id")
    node = next((item for item in dag["nodes"] if item["node_id"] == dag_node_id), None)
    rw.require(node is not None, "energy-record DAG node is absent")
    rw.require(node["target_kind"] == target_kind and node["target_id"] == target_id, "energy-record target does not match its DAG node")
    permitted_node_types = {"minimum_opt_freq", "single_point"} if target_kind == "state" else {"transition_state_opt_freq", "single_point"}
    rw.require(node["node_type"] in permitted_node_types, "energy-record DAG node type is incompatible with its target")

    conformer_id = rw._require_id(review["conformer_id"], "energy-record conformer_id")
    energy_model_id = rw._require_id(review["energy_model_id"], "energy-record energy_model_id")
    source_kind = rw._require_string(review["source_kind"], "energy-record source_kind")
    rw.require(source_kind in {"synthetic_fixture", "reviewed_calculation_result"}, "energy-record source_kind is invalid")
    source_path, source = _review_file_ref(review["source_result"], review_path, "energy source result")
    source_schema = rw._require_string(source.get("schema"), "energy source schema")
    if source_kind == "synthetic_fixture":
        rw.require(source_schema == SYNTHETIC_RESULT_SCHEMA, "synthetic energy source schema mismatch")
        rw.require(source.get("calculation_ready") is False and source.get("no_submission_authorization") is True, "synthetic energy source changed its authority boundary")
    else:
        if source_schema in FORMAL_NONCOMPARABLE_ENERGY_SCHEMAS:
            if source_schema == "gaussian-energy-lineage/1":
                try:
                    import calculation_artifacts as formal_adapter

                    formal_adapter.validate_artifact(source_path)
                except (rw.OfflineError, OSError, ValueError, KeyError, TypeError) as exc:
                    raise rw.OfflineError(
                        f"formal calculation-artifact energy lineage failed its owning validator: {exc}"
                    ) from exc
            raise rw.OfflineError(
                "formal calculation-artifact energy output is electronic-only and comparison_eligible: false; "
                "it cannot be promoted to a reaction comparison-energy record"
            )
        rw.require(source_schema in REAL_RESULT_SCHEMAS, "reviewed calculation-result schema is unsupported")

    field_keys = {
        "electronic_energy_hartree", "thermal_gibbs_correction_hartree", "temperature_k",
        "standard_state", "optimization_success", "normal_termination", "imaginary_frequency_count",
    }
    fields = _exact(review["source_fields"], field_keys, "energy source_fields")
    if source_kind == "reviewed_calculation_result":
        _validate_real_source_shape(source, source_schema, target_kind, fields)
    electronic = _finite(_json_pointer(source, fields["electronic_energy_hartree"], "electronic-energy pointer"), "source electronic energy")
    thermal = _finite(_json_pointer(source, fields["thermal_gibbs_correction_hartree"], "thermal-correction pointer"), "source thermal Gibbs correction")
    temperature = _finite(_json_pointer(source, fields["temperature_k"], "temperature pointer"), "source temperature")
    rw.require(temperature > 0.0, "energy-record temperature must be positive")
    standard_state = rw._require_string(_json_pointer(source, fields["standard_state"], "standard-state pointer"), "source standard state")
    rw.require(standard_state in STANDARD_STATES, "energy-record standard state is unsupported")
    optimization_success = _json_pointer(source, fields["optimization_success"], "optimization-success pointer")
    normal_termination = _json_pointer(source, fields["normal_termination"], "normal-termination pointer")
    rw.require(type(optimization_success) is bool and type(normal_termination) is bool, "stationary-point status fields must be boolean")
    imaginary_count = _nonnegative_integer(_json_pointer(source, fields["imaginary_frequency_count"], "imaginary-frequency pointer"), "source imaginary-frequency count")

    standard_correction = _finite(review["standard_state_correction_kcal_mol"], "standard-state correction")
    low_frequency_correction = _finite(review["low_frequency_correction_kcal_mol"], "low-frequency correction")
    low_frequency_policy = rw._require_string(review["low_frequency_policy"], "low-frequency policy")
    comparison_definition = rw._require_string(review["comparison_energy_definition"], "comparison-energy definition")
    degeneracy = rw._positive_integer(review["degeneracy"], "energy-record degeneracy")
    total_gibbs_hartree = electronic + thermal + (standard_correction + low_frequency_correction) / HARTREE_TO_KCAL_MOL

    mode_review_ref, mode_decision_ref, mode_accepted = _mode_evidence(
        source_path, source, source_schema, review["mode_review"], review["mode_decision"], review_path
    )
    if target_kind == "state":
        rw.require(mode_review_ref is None and mode_decision_ref is None, "minimum energy records must not carry TS mode evidence")

    evidence_bound = any(item["sha256"] == rw.sha256_file(source_path) for item in node["evidence"])
    limitations: list[str] = []
    if source_kind == "synthetic_fixture":
        limitations.append("Synthetic fixture values are contract-test data and cannot support scientific claims.")
    if node["completion"]["status"] != "terminal_evidence_reviewed":
        limitations.append("The DAG node is not complete with reviewed terminal evidence.")
    if not evidence_bound:
        limitations.append("The source result is not listed as immutable evidence on the DAG node.")
    if node["candidate"] is None:
        limitations.append("The DAG node has no reviewed candidate binding.")
    if node["protocol_selection"] is None:
        limitations.append("The DAG node has no reviewed protocol-selection binding.")
    if not normal_termination or not optimization_success:
        limitations.append("Normal termination and converged stationary-point evidence are incomplete.")
    expected_imaginary_count = 0 if target_kind == "state" else 1
    if imaginary_count != expected_imaginary_count:
        limitations.append(f"The target requires exactly {expected_imaginary_count} imaginary frequencies.")
    if target_kind == "edge" and not mode_accepted:
        limitations.append("The unique imaginary mode lacks an accepted hash-bound scientific review.")

    decision = rw._require_string(review["review_decision"], "energy-record review_decision")
    rw.require(decision in rw.REVIEW_DECISIONS, "energy-record review decision is invalid")
    if decision != "accepted":
        limitations.append("The energy-record scientific review is not unconditionally accepted.")
    scientifically_eligible = source_kind == "reviewed_calculation_result" and not limitations
    artifact = {
        "schema": ENERGY_SCHEMA,
        "study_id": network["study_id"],
        "record_id": record_id,
        "target": {"kind": target_kind, "id": target_id},
        "dag_node_id": dag_node_id,
        "conformer_id": conformer_id,
        "energy_model_id": energy_model_id,
        "mechanism_network": orchestrator._rich_ref(network_path, network),
        "calculation_dag": orchestrator._rich_ref(dag_path, dag),
        "candidate": copy.deepcopy(node["candidate"]),
        "protocol_selection": copy.deepcopy(node["protocol_selection"]),
        "source": {
            "kind": source_kind,
            "result": orchestrator._file_ref(source_path, source),
            "field_bindings": copy.deepcopy(fields),
        },
        "energy_components": {
            "electronic_energy_hartree": electronic,
            "thermal_gibbs_correction_hartree": thermal,
            "standard_state_correction_kcal_mol": standard_correction,
            "low_frequency_correction_kcal_mol": low_frequency_correction,
            "total_gibbs_hartree": total_gibbs_hartree,
            "total_gibbs_kcal_mol": total_gibbs_hartree * HARTREE_TO_KCAL_MOL,
        },
        "temperature_k": temperature,
        "standard_state": standard_state,
        "low_frequency_policy": low_frequency_policy,
        "comparison_energy_definition": comparison_definition,
        "degeneracy": degeneracy,
        "stationary_point_audit": {
            "normal_termination": normal_termination,
            "optimization_success": optimization_success,
            "imaginary_frequency_count": imaginary_count,
            "expected_imaginary_frequency_count": expected_imaginary_count,
            "mode_review": mode_review_ref,
            "mode_decision": mode_decision_ref,
            "intended_mode_accepted": mode_accepted if target_kind == "edge" else None,
        },
        "scientific_claim_eligible": scientifically_eligible,
        "claim_limitations": limitations,
        "record_status": "scientifically_eligible" if scientifically_eligible else "retained_not_claim_eligible",
        "review_source": rw._artifact_ref(review_path),
        "review": {"decision": decision, "notes": rw._string_list(review["review_notes"], "energy-record review_notes")},
        "calculation_ready": False,
        "execution_authorized": False,
        "no_submission_authorization": True,
    }
    rw.finalize_artifact(artifact)
    rw.write_json(output, artifact)
    return artifact


def validate_energy_record(path: Path) -> dict[str, Any]:
    artifact = rw.load_json(path)
    keys = {
        "schema", "study_id", "record_id", "target", "dag_node_id", "conformer_id", "energy_model_id",
        "mechanism_network", "calculation_dag", "candidate", "protocol_selection", "source",
        "energy_components", "temperature_k", "standard_state", "low_frequency_policy",
        "comparison_energy_definition", "degeneracy", "stationary_point_audit", "scientific_claim_eligible",
        "claim_limitations", "record_status", "review_source", "review", "calculation_ready",
        "execution_authorized", "no_submission_authorization", "payload_sha256",
    }
    _exact(artifact, keys, "reaction energy record")
    rw.require(artifact["schema"] == ENERGY_SCHEMA, "reaction energy-record schema mismatch")
    rw.validate_payload_hash(artifact)
    rw.require(artifact["calculation_ready"] is False and artifact["execution_authorized"] is False and artifact["no_submission_authorization"] is True, "energy-record authority boundary changed")
    network_path, _network = orchestrator._verify_ref(artifact["mechanism_network"], path, mn.OUTPUT_SCHEMA)
    dag_path, _dag = orchestrator._verify_ref(artifact["calculation_dag"], path, orchestrator.DAG_SCHEMA)
    review_path = orchestrator._resolve_review_source(artifact, path)
    recomputed = path.parent / f".{path.name}.recomputed"
    rw.require(not recomputed.exists(), "temporary energy-record recomputation path already exists")
    try:
        rebuilt = build_energy_record(network_path, dag_path, review_path, recomputed)
        rw.require(rebuilt == artifact, "energy record differs from independent recomputation")
    finally:
        if recomputed.exists():
            recomputed.unlink()
    return {
        "schema": "gaussian-reaction-energy-record-validation/1",
        "study_id": artifact["study_id"],
        "record_id": artifact["record_id"],
        "scientific_claim_eligible": artifact["scientific_claim_eligible"],
        "payload_sha256": artifact["payload_sha256"],
        "live_actions": False,
    }


def _derived_id(prefix: str, value: str) -> str:
    candidate = f"{prefix}_{value}"
    if len(candidate) <= 64 and rw.ID_RE.fullmatch(candidate):
        return candidate
    return f"{prefix}_{rw.sha256_data(value)[:24]}"


def _ensemble(records: list[dict[str, Any]], temperature: float, offsets: dict[str, float]) -> dict[str, Any]:
    rw.require(records, "cannot aggregate an empty energy ensemble")
    rt = R_KCAL_MOL_K * temperature
    adjusted = [record["energy_components"]["total_gibbs_kcal_mol"] + offsets.get(record["record_id"], 0.0) for record in records]
    minimum = min(adjusted)
    weights = [record["degeneracy"] * math.exp(-(energy - minimum) / rt) for record, energy in zip(records, adjusted, strict=True)]
    partition = sum(weights)
    rw.require(math.isfinite(partition) and partition > 0.0, "ensemble partition function is invalid")
    ensemble_energy = minimum - rt * math.log(partition)
    populations = []
    for record, energy, weight in zip(records, adjusted, weights, strict=True):
        populations.append({
            "record_id": record["record_id"],
            "conformer_id": record["conformer_id"],
            "relative_gibbs_kcal_mol": energy - minimum,
            "degeneracy": record["degeneracy"],
            "population": weight / partition,
        })
    return {
        "record_ids": sorted(record["record_id"] for record in records),
        "minimum_total_gibbs_kcal_mol": minimum,
        "ensemble_total_gibbs_kcal_mol": ensemble_energy,
        "conformer_populations": sorted(populations, key=lambda item: item["record_id"]),
        "all_records_scientifically_eligible": all(record["scientific_claim_eligible"] for record in records),
    }


def _scenario_model(
    network: dict[str, Any],
    records_by_target: dict[tuple[str, str], list[dict[str, Any]]],
    temperature: float,
    reference_state_id: str,
    activity_by_edge: dict[str, float],
    selectivity_groups: list[dict[str, Any]],
    offsets: dict[str, float],
) -> dict[str, Any]:
    state_ensembles = {
        state["state_id"]: _ensemble(records_by_target[("state", state["state_id"])], temperature, offsets)
        for state in network["states"]
        if records_by_target.get(("state", state["state_id"]))
    }
    edge_ensembles = {
        edge["edge_id"]: _ensemble(records_by_target[("edge", edge["edge_id"])], temperature, offsets)
        for edge in network["edges"]
        if records_by_target.get(("edge", edge["edge_id"]))
    }
    reference_energy = state_ensembles.get(reference_state_id, {}).get("ensemble_total_gibbs_kcal_mol")
    states = []
    for state in network["states"]:
        ensemble = state_ensembles.get(state["state_id"])
        states.append({
            "state_id": state["state_id"],
            "component_count": len(state["components"]),
            "ensemble": ensemble,
            "relative_gibbs_kcal_mol": None if ensemble is None or reference_energy is None else ensemble["ensemble_total_gibbs_kcal_mol"] - reference_energy,
        })
    edges = []
    edge_by_id: dict[str, dict[str, Any]] = {}
    for edge in network["edges"]:
        source = state_ensembles.get(edge["from_state_id"])
        target = state_ensembles.get(edge["to_state_id"])
        transition = edge_ensembles.get(edge["edge_id"])
        barrier = None if source is None or transition is None else transition["ensemble_total_gibbs_kcal_mol"] - source["ensemble_total_gibbs_kcal_mol"]
        reaction_delta = None if source is None or target is None else target["ensemble_total_gibbs_kcal_mol"] - source["ensemble_total_gibbs_kcal_mol"]
        activity = activity_by_edge.get(edge["edge_id"])
        rate = None
        kinetics_status = "missing_energy_or_activity"
        if barrier is not None and activity is not None:
            if barrier < 0.0:
                kinetics_status = "negative_barrier_requires_model_review"
            else:
                rate = KB_OVER_H_K_INV_S_INV * temperature * math.exp(-barrier / (R_KCAL_MOL_K * temperature)) * activity
                kinetics_status = "eyring_activity_adjusted"
        row = {
            "edge_id": edge["edge_id"],
            "from_state_id": edge["from_state_id"],
            "to_state_id": edge["to_state_id"],
            "stereochemical_channel": edge["stereochemical_channel"],
            "transition_state_ensemble": transition,
            "barrier_kcal_mol": barrier,
            "reaction_delta_g_kcal_mol": reaction_delta,
            "activity_product": activity,
            "rate_constant_s_inv": rate,
            "kinetics_status": kinetics_status,
        }
        edges.append(row)
        edge_by_id[edge["edge_id"]] = row
    selectivities = []
    for group in selectivity_groups:
        rows = [edge_by_id[edge_id] for edge_id in group["edge_ids"]]
        rates = [row["rate_constant_s_inv"] for row in rows]
        valid = all(value is not None for value in rates)
        total = sum(float(value) for value in rates if value is not None) if valid else None
        fractions = []
        for row in rows:
            value = row["rate_constant_s_inv"]
            fractions.append({
                "edge_id": row["edge_id"],
                "stereochemical_channel": row["stereochemical_channel"],
                "fraction": None if not valid or total is None or total <= 0.0 or value is None else value / total,
            })
        selectivities.append({
            "group_id": group["group_id"],
            "label": group["label"],
            "from_state_id": rows[0]["from_state_id"],
            "edge_ids": list(group["edge_ids"]),
            "fractions": fractions,
            "summed_rate_s_inv": total,
            "status": "computed" if valid and total is not None and total > 0.0 else "blocked",
        })
    return {"states": states, "edges": edges, "selectivities": selectivities}


def build_analysis(
    network_path: Path,
    dag_path: Path,
    energy_paths: list[Path],
    review_path: Path,
    output: Path,
) -> dict[str, Any]:
    """Build a common-reference thermochemistry, kinetics, and uncertainty model."""

    network_path = network_path.absolute()
    dag_path = dag_path.absolute()
    energy_paths = [path.absolute() for path in energy_paths]
    review_path = review_path.absolute()
    output = output.absolute()
    mn.validate(network_path)
    orchestrator.validate_dag(dag_path)
    network = rw.load_json(network_path)
    dag = rw.load_json(dag_path)
    rw.require(dag["mechanism_network"]["payload_sha256"] == network["payload_sha256"], "analysis network/DAG binding mismatch")
    rw.require(energy_paths, "analysis requires at least one energy record")
    records: list[dict[str, Any]] = []
    seen_record_ids: set[str] = set()
    for path in energy_paths:
        validate_energy_record(path)
        record = rw.load_json(path)
        rw.require(record["study_id"] == network["study_id"], "analysis energy-record study mismatch")
        rw.require(record["mechanism_network"]["payload_sha256"] == network["payload_sha256"] and record["calculation_dag"]["payload_sha256"] == dag["payload_sha256"], "analysis energy-record parent mismatch")
        rw.require(record["record_id"] not in seen_record_ids, "analysis contains a duplicate energy record ID")
        seen_record_ids.add(record["record_id"])
        records.append(record)

    review = rw.load_json(review_path)
    keys = {
        "schema", "study_id", "mechanism_network_payload_sha256", "calculation_dag_payload_sha256",
        "energy_record_payload_sha256s", "temperature_k", "standard_state", "energy_model_id",
        "reference_state_id", "activity_factors", "selectivity_groups", "uncertainty_scenarios",
        "review_decision", "review_notes",
    }
    _exact(review, keys, "reaction-analysis review")
    rw.require(review["schema"] == ANALYSIS_REVIEW_SCHEMA, "reaction-analysis review schema mismatch")
    rw.require(review["study_id"] == network["study_id"], "reaction-analysis study_id mismatch")
    rw.require(review["mechanism_network_payload_sha256"] == network["payload_sha256"] and review["calculation_dag_payload_sha256"] == dag["payload_sha256"], "reaction-analysis parent hash mismatch")
    reviewed_hashes = rw._string_list(review["energy_record_payload_sha256s"], "analysis energy-record hashes", nonempty=True)
    rw.require(len(reviewed_hashes) == len(set(reviewed_hashes)) and set(reviewed_hashes) == {item["payload_sha256"] for item in records}, "reaction-analysis review does not bind exactly the supplied energy records")
    temperature = _finite(review["temperature_k"], "analysis temperature")
    rw.require(temperature > 0.0, "analysis temperature must be positive")
    standard_state = rw._require_string(review["standard_state"], "analysis standard_state")
    rw.require(standard_state in STANDARD_STATES, "analysis standard state is unsupported")
    energy_model_id = rw._require_id(review["energy_model_id"], "analysis energy_model_id")
    for record in records:
        rw.require(abs(record["temperature_k"] - temperature) <= 1e-9, "analysis refuses mixed energy-record temperatures")
        rw.require(record["standard_state"] == standard_state, "analysis refuses mixed standard states")
        rw.require(record["energy_model_id"] == energy_model_id, "analysis refuses mixed energy models")
    state_ids = {item["state_id"] for item in network["states"]}
    edge_map = {item["edge_id"]: item for item in network["edges"]}
    reference_state_id = rw._require_id(review["reference_state_id"], "analysis reference_state_id")
    rw.require(reference_state_id in state_ids, "analysis reference state is absent from the mechanism network")

    activity_by_edge: dict[str, float] = {}
    activity_rows: list[dict[str, Any]] = []
    rw.require(isinstance(review["activity_factors"], list), "analysis activity_factors must be an array")
    for index, raw in enumerate(review["activity_factors"]):
        row = _exact(raw, {"edge_id", "activity_product", "rationale"}, f"activity factor {index}")
        edge_id = rw._require_id(row["edge_id"], f"activity factor {index}.edge_id")
        rw.require(edge_id in edge_map and edge_id not in activity_by_edge, "activity factor edge is unknown or duplicated")
        activity = _finite(row["activity_product"], f"activity factor {edge_id}")
        rw.require(activity > 0.0, "activity products must be positive")
        activity_by_edge[edge_id] = activity
        activity_rows.append({"edge_id": edge_id, "activity_product": activity, "rationale": rw._require_string(row["rationale"], f"activity factor {edge_id}.rationale")})

    selectivity_groups: list[dict[str, Any]] = []
    seen_groups: set[str] = set()
    rw.require(isinstance(review["selectivity_groups"], list), "analysis selectivity_groups must be an array")
    for index, raw in enumerate(review["selectivity_groups"]):
        row = _exact(raw, {"group_id", "label", "edge_ids", "rationale"}, f"selectivity group {index}")
        group_id = rw._require_id(row["group_id"], f"selectivity group {index}.group_id")
        rw.require(group_id not in seen_groups, "duplicate selectivity group ID")
        seen_groups.add(group_id)
        edge_ids = rw._string_list(row["edge_ids"], f"selectivity group {group_id}.edge_ids", nonempty=True)
        rw.require(len(edge_ids) >= 2 and len(edge_ids) == len(set(edge_ids)) and set(edge_ids) <= set(edge_map), "selectivity group requires at least two distinct known edges")
        sources = {edge_map[edge_id]["from_state_id"] for edge_id in edge_ids}
        rw.require(len(sources) == 1, "selectivity-group edges must share one source state")
        rw.require(set(edge_ids) <= set(activity_by_edge), "selectivity-group edges require explicit activity products")
        selectivity_groups.append({
            "group_id": group_id,
            "label": rw._require_string(row["label"], f"selectivity group {group_id}.label"),
            "edge_ids": sorted(edge_ids),
            "rationale": rw._require_string(row["rationale"], f"selectivity group {group_id}.rationale"),
        })

    scenarios: list[dict[str, Any]] = []
    scenario_ids = {"baseline"}
    rw.require(isinstance(review["uncertainty_scenarios"], list), "analysis uncertainty_scenarios must be an array")
    for index, raw in enumerate(review["uncertainty_scenarios"]):
        row = _exact(raw, {"scenario_id", "energy_offsets_kcal_mol", "rationale"}, f"uncertainty scenario {index}")
        scenario_id = rw._require_id(row["scenario_id"], f"uncertainty scenario {index}.scenario_id")
        rw.require(scenario_id not in scenario_ids, "duplicate or reserved uncertainty scenario ID")
        scenario_ids.add(scenario_id)
        rw.require(isinstance(row["energy_offsets_kcal_mol"], list) and row["energy_offsets_kcal_mol"], f"uncertainty scenario {scenario_id} requires offsets")
        offsets: dict[str, float] = {}
        for offset_index, raw_offset in enumerate(row["energy_offsets_kcal_mol"]):
            offset_row = _exact(raw_offset, {"record_id", "offset_kcal_mol"}, f"uncertainty offset {scenario_id}[{offset_index}]")
            record_id = rw._require_id(offset_row["record_id"], f"uncertainty offset {scenario_id}.record_id")
            rw.require(record_id in seen_record_ids and record_id not in offsets, "uncertainty offset record is unknown or duplicated")
            offsets[record_id] = _finite(offset_row["offset_kcal_mol"], f"uncertainty offset {scenario_id}/{record_id}")
        scenarios.append({"scenario_id": scenario_id, "offsets": offsets, "rationale": rw._require_string(row["rationale"], f"uncertainty scenario {scenario_id}.rationale")})

    records_by_target: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for record in records:
        key = (record["target"]["kind"], record["target"]["id"])
        records_by_target.setdefault(key, []).append(record)
    baseline = _scenario_model(network, records_by_target, temperature, reference_state_id, activity_by_edge, selectivity_groups, {})
    blockers: list[dict[str, Any]] = []
    for state in baseline["states"]:
        if state["ensemble"] is None:
            blockers.append(rw._blocker(_derived_id("missing", f"{state['state_id']}_energy"), state["state_id"], "The mechanism state has no normalized energy record.", ("thermochemistry", "kinetics", "report")))
    for edge in baseline["edges"]:
        if edge["transition_state_ensemble"] is None:
            blockers.append(rw._blocker(_derived_id("missing", f"{edge['edge_id']}_ts_energy"), edge["edge_id"], "The mechanism edge has no normalized transition-state energy record.", ("kinetics", "selectivity", "report")))
        elif edge["barrier_kcal_mol"] is not None and edge["barrier_kcal_mol"] < 0.0:
            blockers.append(rw._blocker(_derived_id("negative", f"{edge['edge_id']}_barrier"), edge["edge_id"], "The derived barrier is negative; Eyring treatment is withheld pending reference/model review.", ("kinetics", "selectivity")))
    for group in baseline["selectivities"]:
        if group["status"] != "computed":
            blockers.append(rw._blocker(_derived_id("blocked", f"{group['group_id']}_selectivity"), group["group_id"], "The selectivity group lacks complete non-negative barriers and explicit activities.", ("selectivity", "report")))
    scenario_outputs = [{"scenario_id": "baseline", "rationale": "Unshifted reviewed energy records.", "energy_offsets_kcal_mol": [], "model": baseline}]
    for scenario in scenarios:
        model = _scenario_model(network, records_by_target, temperature, reference_state_id, activity_by_edge, selectivity_groups, scenario["offsets"])
        scenario_outputs.append({
            "scenario_id": scenario["scenario_id"],
            "rationale": scenario["rationale"],
            "energy_offsets_kcal_mol": [{"record_id": key, "offset_kcal_mol": value} for key, value in sorted(scenario["offsets"].items())],
            "model": model,
        })
    for scenario in scenario_outputs[1:]:
        scenario_id = scenario["scenario_id"]
        for edge in scenario["model"]["edges"]:
            if edge["barrier_kcal_mol"] is not None and edge["barrier_kcal_mol"] < 0.0:
                blockers.append(rw._blocker(
                    _derived_id("scenario", f"{scenario_id}_{edge['edge_id']}_negative_barrier"),
                    edge["edge_id"],
                    f"Uncertainty scenario {scenario_id} produces a negative barrier; its Eyring result is withheld pending model review.",
                    ("uncertainty", "kinetics", "selectivity", "report"),
                ))
        for group in scenario["model"]["selectivities"]:
            if group["status"] != "computed":
                blockers.append(rw._blocker(
                    _derived_id("scenario", f"{scenario_id}_{group['group_id']}_selectivity"),
                    group["group_id"],
                    f"Uncertainty scenario {scenario_id} cannot produce the reviewed selectivity comparison.",
                    ("uncertainty", "selectivity", "report"),
                ))

    decision = rw._require_string(review["review_decision"], "reaction-analysis review_decision")
    rw.require(decision in rw.REVIEW_DECISIONS, "reaction-analysis review decision is invalid")
    if blockers:
        rw.require(decision != "accepted", "an analysis with derived blockers cannot have an unqualified accepted review decision")
    if decision != "accepted":
        blockers.append(rw._blocker("analysis_review_not_accepted", "study", "The reaction-analysis review is not unconditionally accepted.", ("scientific_comparison", "report")))
    blockers = rw._sort_blockers(blockers)

    edge_range_rows = []
    for edge_id in sorted(edge_map):
        values = [next(item for item in scenario["model"]["edges"] if item["edge_id"] == edge_id)["barrier_kcal_mol"] for scenario in scenario_outputs]
        finite_values = [float(value) for value in values if value is not None]
        edge_range_rows.append({"edge_id": edge_id, "minimum_barrier_kcal_mol": min(finite_values) if finite_values else None, "maximum_barrier_kcal_mol": max(finite_values) if finite_values else None})
    selectivity_range_rows = []
    for group in selectivity_groups:
        for edge_id in group["edge_ids"]:
            values = []
            for scenario in scenario_outputs:
                group_row = next(item for item in scenario["model"]["selectivities"] if item["group_id"] == group["group_id"])
                values.append(next(item for item in group_row["fractions"] if item["edge_id"] == edge_id)["fraction"])
            finite_values = [float(value) for value in values if value is not None]
            selectivity_range_rows.append({
                "group_id": group["group_id"], "edge_id": edge_id,
                "minimum_fraction": min(finite_values) if finite_values else None,
                "maximum_fraction": max(finite_values) if finite_values else None,
            })

    all_eligible = all(record["scientific_claim_eligible"] for record in records)
    has_synthetic_source = any(record["source"]["kind"] == "synthetic_fixture" for record in records)
    if has_synthetic_source:
        claim_ceiling = "contract_fixture_only"
    elif not all_eligible or blockers:
        claim_ceiling = "incomplete_hypothesis_only"
    else:
        claim_ceiling = "bounded_computational_comparison"
    if blockers or claim_ceiling == "incomplete_hypothesis_only":
        analysis_status = "incomplete"
    elif claim_ceiling == "contract_fixture_only":
        analysis_status = "complete_for_contract_fixture"
    else:
        analysis_status = "complete_for_bounded_comparison"
    artifact = {
        "schema": ANALYSIS_SCHEMA,
        "study_id": network["study_id"],
        "mechanism_network": orchestrator._rich_ref(network_path, network),
        "calculation_dag": orchestrator._rich_ref(dag_path, dag),
        "energy_records": sorted((orchestrator._rich_ref(path, record) for path, record in zip(energy_paths, records, strict=True)), key=lambda item: item["payload_sha256"]),
        "analysis_conditions": {"temperature_k": temperature, "standard_state": standard_state, "energy_model_id": energy_model_id, "reference_state_id": reference_state_id},
        "activity_factors": sorted(activity_rows, key=lambda item: item["edge_id"]),
        "selectivity_group_definitions": sorted(selectivity_groups, key=lambda item: item["group_id"]),
        "baseline": baseline,
        "uncertainty": {"scenarios": scenario_outputs, "edge_barrier_ranges": edge_range_rows, "selectivity_ranges": selectivity_range_rows},
        "blockers": blockers,
        "record_limitations": sorted({limitation for record in records for limitation in record["claim_limitations"]}),
        "claim_ceiling": claim_ceiling,
        "scientific_claim_eligible": claim_ceiling == "bounded_computational_comparison",
        "mechanism_proven": False,
        "analysis_status": analysis_status,
        "review_source": rw._artifact_ref(review_path),
        "review": {"decision": decision, "notes": rw._string_list(review["review_notes"], "reaction-analysis review_notes")},
        "calculation_ready": False,
        "execution_authorized": False,
        "no_submission_authorization": True,
    }
    rw.finalize_artifact(artifact)
    rw.write_json(output, artifact)
    return artifact


def validate_analysis(path: Path) -> dict[str, Any]:
    artifact = rw.load_json(path)
    keys = {
        "schema", "study_id", "mechanism_network", "calculation_dag", "energy_records",
        "analysis_conditions", "activity_factors", "selectivity_group_definitions", "baseline",
        "uncertainty", "blockers", "record_limitations", "claim_ceiling", "scientific_claim_eligible",
        "mechanism_proven", "analysis_status", "review_source", "review", "calculation_ready",
        "execution_authorized", "no_submission_authorization", "payload_sha256",
    }
    _exact(artifact, keys, "reaction analysis")
    rw.require(artifact["schema"] == ANALYSIS_SCHEMA, "reaction-analysis schema mismatch")
    rw.validate_payload_hash(artifact)
    rw.require(artifact["mechanism_proven"] is False, "reaction analysis cannot claim mechanism proof")
    rw.require(artifact["calculation_ready"] is False and artifact["execution_authorized"] is False and artifact["no_submission_authorization"] is True, "reaction-analysis authority boundary changed")
    network_path, _network = orchestrator._verify_ref(artifact["mechanism_network"], path, mn.OUTPUT_SCHEMA)
    dag_path, _dag = orchestrator._verify_ref(artifact["calculation_dag"], path, orchestrator.DAG_SCHEMA)
    energy_paths = [orchestrator._verify_ref(reference, path, ENERGY_SCHEMA)[0] for reference in artifact["energy_records"]]
    review_path = orchestrator._resolve_review_source(artifact, path)
    recomputed = path.parent / f".{path.name}.recomputed"
    rw.require(not recomputed.exists(), "temporary reaction-analysis recomputation path already exists")
    try:
        rebuilt = build_analysis(network_path, dag_path, energy_paths, review_path, recomputed)
        rw.require(rebuilt == artifact, "reaction analysis differs from independent recomputation")
    finally:
        if recomputed.exists():
            recomputed.unlink()
    return {
        "schema": "gaussian-reaction-analysis-validation/1",
        "study_id": artifact["study_id"],
        "analysis_status": artifact["analysis_status"],
        "claim_ceiling": artifact["claim_ceiling"],
        "payload_sha256": artifact["payload_sha256"],
        "live_actions": False,
    }


def _display_number(value: Any, digits: int = 3) -> str:
    return "—" if value is None else f"{float(value):.{digits}f}"


def _markdown_cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _render_report(title: str, analysis: dict[str, Any], review_notes: list[str]) -> bytes:
    conditions = analysis["analysis_conditions"]
    lines = [
        f"# {title}", "",
        "> This is a hash-bound offline report. Its claim ceiling is "
        f"`{analysis['claim_ceiling']}`; it does not authorize Gaussian or PBS execution.", "",
        "## Scope and status", "",
        f"- Study: `{analysis['study_id']}`",
        f"- Analysis status: `{analysis['analysis_status']}`",
        f"- Temperature: {_display_number(conditions['temperature_k'], 2)} K",
        f"- Standard state: `{conditions['standard_state']}`",
        f"- Energy model: `{conditions['energy_model_id']}`",
        f"- Common reference state: `{conditions['reference_state_id']}`", "",
        "## State thermochemistry", "",
        "| State | Relative G (kcal/mol) | Ensemble records | Eligible |",
        "|---|---:|---:|---|",
    ]
    for state in analysis["baseline"]["states"]:
        ensemble = state["ensemble"]
        lines.append(
            f"| `{_markdown_cell(state['state_id'])}` | {_display_number(state['relative_gibbs_kcal_mol'])} | "
            f"{0 if ensemble is None else len(ensemble['record_ids'])} | "
            f"{'no data' if ensemble is None else str(ensemble['all_records_scientifically_eligible']).lower()} |"
        )
    lines.extend(["", "## Elementary-step comparison", "", "| Edge | From → to | ΔG‡ (kcal/mol) | ΔG_rxn (kcal/mol) | k (s⁻¹) | Status |", "|---|---|---:|---:|---:|---|"])
    for edge in analysis["baseline"]["edges"]:
        rate = "—" if edge["rate_constant_s_inv"] is None else f"{edge['rate_constant_s_inv']:.6e}"
        lines.append(
            f"| `{_markdown_cell(edge['edge_id'])}` | `{_markdown_cell(edge['from_state_id'])}` → `{_markdown_cell(edge['to_state_id'])}` | "
            f"{_display_number(edge['barrier_kcal_mol'])} | {_display_number(edge['reaction_delta_g_kcal_mol'])} | {rate} | `{edge['kinetics_status']}` |"
        )
    lines.extend(["", "## Selectivity", ""])
    if analysis["baseline"]["selectivities"]:
        lines.extend(["| Group | Edge/channel | Fraction |", "|---|---|---:|"])
        for group in analysis["baseline"]["selectivities"]:
            for fraction in group["fractions"]:
                channel = fraction["stereochemical_channel"] or "unassigned"
                lines.append(f"| `{group['group_id']}` | `{fraction['edge_id']}` / `{_markdown_cell(channel)}` | {_display_number(fraction['fraction'], 6)} |")
    else:
        lines.append("No selectivity group was reviewed.")
    lines.extend(["", "## Uncertainty envelope", "", "| Edge | Minimum ΔG‡ | Maximum ΔG‡ |", "|---|---:|---:|"])
    for row in analysis["uncertainty"]["edge_barrier_ranges"]:
        lines.append(f"| `{row['edge_id']}` | {_display_number(row['minimum_barrier_kcal_mol'])} | {_display_number(row['maximum_barrier_kcal_mol'])} |")
    lines.extend(["", "## Blockers and limitations", ""])
    if analysis["blockers"]:
        lines.extend(f"- `{item['blocker_id']}`: {item['description']}" for item in analysis["blockers"])
    else:
        lines.append("- No analysis-completeness blocker was derived.")
    if analysis["record_limitations"]:
        lines.extend(f"- {item}" for item in analysis["record_limitations"])
    lines.extend(["", "## Explicit non-claims", "",
                  "- The compared network remains a reviewed hypothesis; this report does not prove the mechanism.",
                  "- A frequency count alone never validates a transition state; accepted mode and path evidence remain separate requirements.",
                  "- Synthetic fixture energies, when present, are not scientific results.",
                  "- This report grants no input-rendering, submission, retry, cancellation, overwrite, or deletion authority.",
                  "", "## Review notes", ""])
    lines.extend(f"- {note}" for note in review_notes)
    return ("\n".join(lines) + "\n").encode("utf-8")


def _report_artifact(
    index_path: Path,
    index: dict[str, Any],
    analysis_path: Path,
    analysis: dict[str, Any],
    review_path: Path,
    review: dict[str, Any],
    markdown_path: Path,
) -> dict[str, Any]:
    decision = rw._require_string(review["review_decision"], "report review_decision")
    rw.require(decision in rw.REVIEW_DECISIONS, "report review decision is invalid")
    rw.require(decision == "accepted", "bounded-report rendering requires an accepted report review")
    notes = rw._string_list(review["review_notes"], "report review_notes")
    artifact = {
        "schema": REPORT_SCHEMA,
        "study_id": analysis["study_id"],
        "study_index": orchestrator._rich_ref(index_path, index),
        "analysis": orchestrator._rich_ref(analysis_path, analysis),
        "markdown": {"path": str(markdown_path), "sha256": rw.sha256_file(markdown_path), "size_bytes": markdown_path.stat().st_size, "format": "markdown"},
        "sections": ["scope_and_status", "state_thermochemistry", "elementary_step_comparison", "selectivity", "uncertainty_envelope", "blockers_and_limitations", "explicit_nonclaims", "review_notes"],
        "claim_ceiling": analysis["claim_ceiling"],
        "scientific_claim_eligible": analysis["scientific_claim_eligible"],
        "mechanism_proven": False,
        "report_status": "bounded_complete" if analysis["analysis_status"] != "incomplete" else "bounded_incomplete",
        "blockers": copy.deepcopy(analysis["blockers"]),
        "nonclaims": [
            "mechanism_not_proven",
            "frequency_count_alone_not_ts_validation",
            "synthetic_fixtures_not_scientific_results",
            "no_live_execution_authority",
        ],
        "review_source": rw._artifact_ref(review_path),
        "review": {"decision": decision, "notes": notes},
        "calculation_ready": False,
        "execution_authorized": False,
        "no_submission_authorization": True,
    }
    rw.finalize_artifact(artifact)
    return artifact


def build_report(index_path: Path, analysis_path: Path, review_path: Path, markdown_output: Path, output: Path) -> dict[str, Any]:
    index_path = index_path.absolute()
    analysis_path = analysis_path.absolute()
    review_path = review_path.absolute()
    markdown_output = markdown_output.absolute()
    output = output.absolute()
    orchestrator.validate_index(index_path)
    validate_analysis(analysis_path)
    index = rw.load_json(index_path)
    analysis = rw.load_json(analysis_path)
    rw.require(index["study_id"] == analysis["study_id"], "report index/analysis study mismatch")
    indexed_payloads = {row["role"]: row["artifact"]["payload_sha256"] for row in index["artifacts"] if row["role"] != "candidate"}
    rw.require(indexed_payloads.get("mechanism_network") == analysis["mechanism_network"]["payload_sha256"], "report analysis is not based on the indexed mechanism network")
    rw.require(indexed_payloads.get("calculation_dag") == analysis["calculation_dag"]["payload_sha256"], "report analysis is not based on the indexed calculation DAG")
    review = rw.load_json(review_path)
    keys = {"schema", "study_id", "study_index_payload_sha256", "analysis_payload_sha256", "title", "review_decision", "review_notes"}
    _exact(review, keys, "bounded-report review")
    rw.require(review["schema"] == REPORT_REVIEW_SCHEMA, "bounded-report review schema mismatch")
    rw.require(review["study_id"] == analysis["study_id"], "bounded-report study_id mismatch")
    rw.require(review["study_index_payload_sha256"] == index["payload_sha256"] and review["analysis_payload_sha256"] == analysis["payload_sha256"], "bounded-report parent hash mismatch")
    title = rw._require_string(review["title"], "bounded-report title")
    rw.require("\n" not in title and "\r" not in title and len(title) <= 160, "bounded-report title is invalid")
    notes = rw._string_list(review["review_notes"], "bounded-report review_notes")
    markdown_bytes = _render_report(title, analysis, notes)
    rw.require(not markdown_output.exists() and not output.exists(), "refusing to overwrite bounded-report output")
    markdown_output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with markdown_output.open("xb") as handle:
            handle.write(markdown_bytes)
        artifact = _report_artifact(index_path, index, analysis_path, analysis, review_path, review, markdown_output)
        rw.write_json(output, artifact)
    except Exception:
        if markdown_output.exists() and not output.exists():
            markdown_output.unlink()
        raise
    return artifact


def validate_report(path: Path) -> dict[str, Any]:
    artifact = rw.load_json(path)
    keys = {
        "schema", "study_id", "study_index", "analysis", "markdown", "sections", "claim_ceiling",
        "scientific_claim_eligible", "mechanism_proven", "report_status", "blockers", "nonclaims",
        "review_source", "review", "calculation_ready", "execution_authorized", "no_submission_authorization",
        "payload_sha256",
    }
    _exact(artifact, keys, "bounded reaction report")
    rw.require(artifact["schema"] == REPORT_SCHEMA, "bounded-report schema mismatch")
    rw.validate_payload_hash(artifact)
    rw.require(artifact["mechanism_proven"] is False and artifact["calculation_ready"] is False and artifact["execution_authorized"] is False and artifact["no_submission_authorization"] is True, "bounded-report authority or claim boundary changed")
    index_path, index = orchestrator._verify_ref(artifact["study_index"], path, orchestrator.INDEX_SCHEMA)
    analysis_path, analysis = orchestrator._verify_ref(artifact["analysis"], path, ANALYSIS_SCHEMA)
    orchestrator.validate_index(index_path)
    validate_analysis(analysis_path)
    markdown_ref = _exact(artifact["markdown"], {"path", "sha256", "size_bytes", "format"}, "bounded-report markdown")
    markdown_path = orchestrator._resolve(markdown_ref["path"], path, "bounded-report markdown")
    rw.require(markdown_ref["format"] == "markdown" and markdown_ref["sha256"] == rw.sha256_file(markdown_path) and markdown_ref["size_bytes"] == markdown_path.stat().st_size, "bounded-report markdown identity mismatch")
    review_path = orchestrator._resolve_review_source(artifact, path)
    review = rw.load_json(review_path)
    expected_markdown = _render_report(review["title"], analysis, rw._string_list(review["review_notes"], "bounded-report review_notes"))
    rw.require(markdown_path.read_bytes() == expected_markdown, "bounded-report Markdown differs from deterministic rendering")
    expected = _report_artifact(index_path, index, analysis_path, analysis, review_path, review, markdown_path)
    rw.require(expected == artifact, "bounded-report artifact differs from independent recomputation")
    return {
        "schema": "gaussian-reaction-bounded-report-validation/1",
        "study_id": artifact["study_id"],
        "report_status": artifact["report_status"],
        "claim_ceiling": artifact["claim_ceiling"],
        "payload_sha256": artifact["payload_sha256"],
        "live_actions": False,
    }


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    energy = commands.add_parser("build-energy", help="Normalize one reviewed state or TS energy record")
    energy.add_argument("mechanism_network", type=Path)
    energy.add_argument("calculation_dag", type=Path)
    energy.add_argument("--review", type=Path, required=True)
    energy.add_argument("--output", type=Path, required=True)
    energy_validate = commands.add_parser("validate-energy", help="Validate and recompute one normalized energy record")
    energy_validate.add_argument("artifact", type=Path)
    analysis = commands.add_parser("build-analysis", help="Build common-reference thermochemistry, kinetics, selectivity, and uncertainty")
    analysis.add_argument("mechanism_network", type=Path)
    analysis.add_argument("calculation_dag", type=Path)
    analysis.add_argument("--energy", action="append", type=Path, required=True)
    analysis.add_argument("--review", type=Path, required=True)
    analysis.add_argument("--output", type=Path, required=True)
    analysis_validate = commands.add_parser("validate-analysis", help="Validate and recompute a reaction analysis")
    analysis_validate.add_argument("artifact", type=Path)
    report = commands.add_parser("build-report", help="Render a bounded hash-bound Markdown reaction report")
    report.add_argument("study_index", type=Path)
    report.add_argument("analysis", type=Path)
    report.add_argument("--review", type=Path, required=True)
    report.add_argument("--markdown-output", type=Path, required=True)
    report.add_argument("--output", type=Path, required=True)
    report_validate = commands.add_parser("validate-report", help="Validate a bounded reaction report and its Markdown")
    report_validate.add_argument("artifact", type=Path)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "build-energy":
            result = build_energy_record(args.mechanism_network, args.calculation_dag, args.review, args.output)
        elif args.command == "validate-energy":
            result = validate_energy_record(args.artifact)
        elif args.command == "build-analysis":
            result = build_analysis(args.mechanism_network, args.calculation_dag, args.energy, args.review, args.output)
        elif args.command == "validate-analysis":
            result = validate_analysis(args.artifact)
        elif args.command == "build-report":
            result = build_report(args.study_index, args.analysis, args.review, args.markdown_output, args.output)
        else:
            result = validate_report(args.artifact)
    except (rw.OfflineError, OSError, ValueError, AssertionError, SystemExit) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
