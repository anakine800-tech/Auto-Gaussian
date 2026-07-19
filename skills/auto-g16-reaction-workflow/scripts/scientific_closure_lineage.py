#!/usr/bin/env python3
"""Build immutable, package-relative minimum result and structure lineage.

Offline only: this module never submits, fetches, cancels, cleans up, retries,
or treats a structure-selection receipt as calculation authority.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any

SCHEMA = "gaussian-minimum-lineage-handoff/1"
REVIEW_SCHEMA = "gaussian-minimum-lineage-review/1"
SELECTION_SCHEMA = "gaussian-conformer-selection-receipt/1"
HASH_RE = re.compile(r"^[a-f0-9]{64}$")


class LineageError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise LineageError(message)


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def payload_sha256(value: dict[str, Any]) -> str:
    payload = dict(value)
    payload.pop("payload_sha256", None)
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            require(key not in result, f"{path}: duplicate JSON key: {key}")
            result[key] = value
        return result
    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs, parse_constant=lambda token: (_ for _ in ()).throw(LineageError(f"non-standard JSON constant: {token}")))
    require(isinstance(value, dict), f"JSON root must be an object: {path}")
    return value


def exact(value: Any, keys: set[str], label: str) -> dict[str, Any]:
    require(isinstance(value, dict) and set(value) == keys, f"{label} fields are invalid")
    return value


def safe_file(root: Path, relative: str, label: str) -> Path:
    raw = Path(relative)
    require(not raw.is_absolute() and ".." not in raw.parts and str(raw) not in {"", "."}, f"{label} path must be package-root relative")
    candidate = root / raw
    require(not candidate.is_symlink() and candidate.is_file(), f"{label} must be an existing non-symlink file")
    resolved = candidate.resolve()
    require(resolved.is_relative_to(root), f"{label} escapes package root")
    return resolved


def reference(path: Path, root: Path, *, json_document: dict[str, Any] | None = None) -> dict[str, Any]:
    resolved = path.resolve()
    require(resolved.is_file() and not resolved.is_symlink() and resolved.is_relative_to(root), f"source must be a non-symlink file inside package root: {path}")
    result: dict[str, Any] = {"path": resolved.relative_to(root).as_posix(), "sha256": file_sha256(resolved), "size_bytes": resolved.stat().st_size}
    if json_document is not None:
        result["schema"] = json_document.get("schema")
        result["payload_sha256"] = json_document.get("payload_sha256")
    return result


def resolve_reference(ref: dict[str, Any], root: Path, label: str, *, json_source: bool = False) -> tuple[Path, dict[str, Any] | None]:
    keys = {"path", "sha256", "size_bytes"} | ({"schema", "payload_sha256"} if json_source else set())
    exact(ref, keys, label)
    path = safe_file(root, ref["path"], label)
    require(ref["sha256"] == file_sha256(path) and ref["size_bytes"] == path.stat().st_size, f"{label} file binding changed")
    if not json_source:
        return path, None
    document = load_json(path)
    require(ref["schema"] == document.get("schema") and ref["payload_sha256"] == document.get("payload_sha256"), f"{label} schema or payload binding changed")
    return path, document


def load_owner(relative: tuple[str, ...], name: str) -> Any:
    skills = Path(__file__).resolve().parents[2]
    path = skills.joinpath(*relative)
    require(path.is_file(), f"owner validator unavailable: {path}")
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, f"owner validator cannot be loaded: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def owners() -> dict[str, Any]:
    return {
        "log": load_owner(("auto-g16-rtwin-pbs", "scripts", "gaussian_log.py"), "closure_gaussian_log"),
        "approval": load_owner(("auto-g16-rtwin-pbs", "scripts", "gaussian_rtwin_pbs.py"), "closure_input_approval"),
        "input": load_owner(("auto-g16-ts-irc", "scripts", "ts_irc.py"), "closure_ts_input"),
    }


def validate_timestamp(value: Any) -> str:
    require(isinstance(value, str) and value.strip(), "reviewed_at must be a non-empty ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise LineageError("reviewed_at must be an ISO-8601 timestamp") from exc
    require(parsed.tzinfo is not None and parsed.utcoffset() is not None, "reviewed_at must include a timezone")
    return value


def formula(elements: list[str]) -> str:
    counts: dict[str, int] = {}
    for element in elements:
        counts[element] = counts.get(element, 0) + 1
    order = (["C"] if "C" in counts else []) + (["H"] if "H" in counts else []) + sorted(item for item in counts if item not in {"C", "H"})
    return "".join(item + (str(counts[item]) if counts[item] != 1 else "") for item in order)


def parse_xyz(path: Path) -> list[dict[str, Any]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    require(lines and lines[0].strip().isdigit(), "optimized coordinates must be XYZ with an atom count")
    count = int(lines[0].strip())
    require(len(lines) >= count + 2, "optimized XYZ is truncated")
    records = []
    for index, line in enumerate(lines[2:2 + count], start=1):
        fields = line.split()
        require(len(fields) == 4 and re.fullmatch(r"[A-Z][a-z]?", fields[0]) is not None, "optimized XYZ row is invalid")
        values = [float(value.replace("D", "E").replace("d", "e")) for value in fields[1:]]
        require(all(math.isfinite(value) for value in values), "optimized XYZ contains non-finite coordinates")
        records.append({"index": index, "element": fields[0], "x": values[0], "y": values[1], "z": values[2]})
    return records


def validate_selection_receipt(path: Path) -> dict[str, Any]:
    data = load_json(path)
    require(data.get("schema") == SELECTION_SCHEMA, f"conformer selection must use {SELECTION_SCHEMA}")
    require(data.get("candidate_only") is True and data.get("calculation_ready") is False and data.get("no_submission_authorization") is True, "conformer selection authority boundary changed")
    require(data.get("selection_is_not_authorization") is True, "conformer selection must explicitly remain non-authorizing")
    expected_states = {"human_selected": True, "input_draft_generated": True, "exact_input_approved": False, "submission_authorized": False, "result_accepted": False}
    require(data.get("workflow_states") == expected_states, "conformer selection conflates selection, approval, submission, or result acceptance")
    root = path.parent.resolve()
    for field, hash_field, size_field in (("gaussian_input", "gaussian_input_sha256", "gaussian_input_size_bytes"), ("xyz_coordinates", "xyz_sha256", "xyz_size_bytes")):
        source = safe_file(root, data.get(field), f"selection {field}")
        require(data.get(hash_field) == file_sha256(source) and data.get(size_field) == source.stat().st_size, f"selection {field} binding changed")
    ensemble = safe_file(root, data.get("selection", {}).get("ensemble"), "selection source ensemble")
    require(data["selection"].get("ensemble_sha256") == file_sha256(ensemble) and data["selection"].get("ensemble_size_bytes") == ensemble.stat().st_size, "selection ensemble binding changed")
    return data


def normalize_review(data: dict[str, Any]) -> dict[str, Any]:
    exact(data, {"schema", "lineage_id", "minimum_id", "state_id", "workflow_settings", "stable_atom_ids", "atom_mapping", "structure_review", "decision", "explicit_human_review", "reviewer", "rationale", "reviewed_at"}, "minimum lineage review")
    require(data["schema"] == REVIEW_SCHEMA, f"review schema must be {REVIEW_SCHEMA}")
    settings = exact(data["workflow_settings"], {"temperature_k", "standard_state", "expected_stages"}, "workflow settings")
    require(isinstance(settings["temperature_k"], (int, float)) and not isinstance(settings["temperature_k"], bool) and math.isfinite(float(settings["temperature_k"])) and float(settings["temperature_k"]) > 0, "temperature must be positive")
    require(settings["standard_state"] in {"1atm", "1M"} and isinstance(settings["expected_stages"], int) and settings["expected_stages"] >= 2, "workflow settings are invalid")
    atom_ids = data["stable_atom_ids"]
    require(isinstance(atom_ids, list) and atom_ids and len(set(atom_ids)) == len(atom_ids) and all(isinstance(value, str) and value for value in atom_ids), "stable_atom_ids must be non-empty and unique")
    mapping = data["atom_mapping"]
    require(isinstance(mapping, list) and len(mapping) == len(atom_ids), "atom mapping must cover every stable atom ID")
    required_mapping = {"atom_id", "candidate_index", "input_index", "result_index", "element"}
    for item in mapping:
        exact(item, required_mapping, "atom mapping record")
    require([item["atom_id"] for item in mapping] == atom_ids, "atom mapping order must equal stable_atom_ids")
    for key in ("candidate_index", "input_index", "result_index"):
        require([item[key] for item in mapping] == list(range(1, len(mapping) + 1)), f"{key} mapping must be contiguous, one-based, and order-compatible")
    structure = exact(data["structure_review"], {"identity_label", "formula", "connectivity", "stereochemistry", "connectivity_reviewed", "stereochemistry_reviewed"}, "structure review")
    require(all(isinstance(structure[key], str) and structure[key].strip() for key in ("identity_label", "formula")), "structure identity and formula are required")
    require(isinstance(structure["connectivity"], list) and isinstance(structure["stereochemistry"], list), "connectivity and stereochemistry must be arrays")
    require(structure["connectivity_reviewed"] is True and structure["stereochemistry_reviewed"] is True, "connectivity and stereochemistry require explicit review")
    require(data["decision"] == "accepted" and data["explicit_human_review"] is True, "minimum lineage requires explicit human acceptance")
    require(all(isinstance(data[key], str) and data[key].strip() for key in ("lineage_id", "minimum_id", "state_id", "reviewer", "rationale")), "minimum lineage identifiers, reviewer, and rationale are required")
    validate_timestamp(data["reviewed_at"])
    return data


def replay_minimum_sources(root: Path, artifact: dict[str, Any]) -> dict[str, Any]:
    source_fields = {"selection", "input_approval", "input", "job", "result", "raw_log", "checkpoint", "optimized_coordinates"}
    sources = exact(artifact["sources"], source_fields, "minimum lineage sources")
    selection_path, selection_json = resolve_reference(sources["selection"], root, "selection receipt", json_source=True)
    selection = validate_selection_receipt(selection_path)
    require(selection == selection_json, "selection replay returned different content")
    approval_path, approval = resolve_reference(sources["input_approval"], root, "input approval", json_source=True)
    input_path, _ = resolve_reference(sources["input"], root, "exact Gaussian input")
    job_path, job = resolve_reference(sources["job"], root, "job record", json_source=True)
    result_path, result = resolve_reference(sources["result"], root, "minimum result", json_source=True)
    log_path, _ = resolve_reference(sources["raw_log"], root, "raw Gaussian log")
    checkpoint_path, _ = resolve_reference(sources["checkpoint"], root, "minimum checkpoint")
    xyz_path, _ = resolve_reference(sources["optimized_coordinates"], root, "optimized coordinates")
    require(checkpoint_path.stat().st_size > 0, "minimum checkpoint is empty")
    owner = owners()
    parsed_input = owner["input"].parse_cartesian_input(input_path)
    owner["approval"].validate_input_approval_receipt(approval_path, input_path=input_path, work_kind="minimum")
    require(approval.get("input", {}).get("sha256") == file_sha256(input_path), "input approval does not bind the exact minimum input")
    require(job.get("schema") == "gaussian-rtwin-pbs/1" and job.get("status") == "completed" and job.get("results_fetched") is True, "minimum job must be completed and fetched")
    require(job.get("input_sha256") == file_sha256(input_path), "minimum job input hash differs from exact input approval")
    settings = artifact["workflow_settings"]
    replay = owner["log"].analyze_workflow_log_text(log_path.read_text(encoding="utf-8", errors="replace"), temperature_k=float(settings["temperature_k"]), standard_state=settings["standard_state"], expected_stages=settings["expected_stages"])
    compare = {
        "schema", "status", "normal_termination", "normal_termination_count", "error_termination",
        "error_termination_count", "optimization_completed", "stationary_point_found", "optimization_success",
        "final_energy_hartree", "frequency_count", "expected_frequency_count", "frequency_parse_complete",
        "frequency_parse_diagnostics", "imaginary_frequency_count", "frequencies_cm-1", "final_coordinate_count",
        "final_coordinates", "linearity", "parser", "execution_complete", "frequency_complete", "minimum_validated",
        "workflow_success", "thermochemistry",
    }
    for key in compare:
        require(result.get(key) == replay.get(key), f"minimum result differs from raw-log parser replay: {key}")
    require(replay["frequency_parse_complete"] is True and replay["expected_frequency_count"] is not None and replay["frequency_count"] == replay["expected_frequency_count"], "minimum frequency evidence is truncated, damaged, or incomplete")
    require(replay["minimum_validated"] is True and replay["imaginary_frequency_count"] == 0 and replay["workflow_success"] is True, "minimum result is not a completed zero-imaginary stationary minimum")
    mapping = artifact["atom_mapping"]
    candidate_elements = selection.get("candidate_atom_elements")
    input_elements = [item["element"] for item in parsed_input["atoms"]]
    result_elements = [item.get("element") for item in replay["final_coordinates"]]
    mapped_elements = [item["element"] for item in mapping]
    require(candidate_elements == input_elements == result_elements == mapped_elements, "candidate, input, result, or stable atom mapping element order differs")
    require(artifact["stable_atom_ids"] == [item["atom_id"] for item in mapping], "stable atom ID mapping changed")
    require(artifact["formula"] == formula(result_elements), "minimum formula differs from exact result composition")
    require(parsed_input["charge"] == artifact["charge"] and parsed_input["multiplicity"] == artifact["multiplicity"], "minimum input charge or multiplicity differs from lineage")
    coordinates = parse_xyz(xyz_path)
    expected_xyz = [{"index": item.get("center", item.get("index")), "element": item.get("element"), "x": item.get("x"), "y": item.get("y"), "z": item.get("z")} for item in replay["final_coordinates"]]
    require(coordinates == expected_xyz, "optimized coordinates differ from the raw-log-replayed result")
    return {"selection": selection, "approval": approval, "input": parsed_input, "job": job, "result": result, "replay": replay}


def validate_artifact(path: Path) -> dict[str, Any]:
    artifact = load_json(path)
    required = {"schema", "lineage_id", "minimum_id", "state_id", "sources", "workflow_settings", "stable_atom_ids", "atom_mapping", "formula", "charge", "multiplicity", "structure_review", "review", "workflow_states", "acceptance", "migration_policy", "immutability", "calculation_ready", "no_submission_authorization", "payload_sha256"}
    exact(artifact, required, "minimum lineage handoff")
    require(artifact["schema"] == SCHEMA and artifact["payload_sha256"] == payload_sha256(artifact), "minimum lineage schema or payload hash is invalid")
    require(artifact["immutability"] == "append_only_new_revision" and artifact["calculation_ready"] is False and artifact["no_submission_authorization"] is True, "minimum lineage authority or immutability boundary changed")
    expected_states = {"human_selected": True, "input_draft_generated": True, "exact_input_approved": True, "job_observed": True, "submission_authorized_by_this_artifact": False, "result_accepted": True}
    require(artifact["workflow_states"] == expected_states, "minimum lineage workflow states are invalid")
    require(artifact["acceptance"] == {"status": "minimum_accepted", "raw_log_replayed": True, "complete_frequency_gate_passed": True, "zero_imaginary_frequencies": True, "identity_connectivity_stereochemistry_reviewed": True}, "minimum acceptance facts changed")
    require(artifact["migration_policy"] == {"new_bindings": "package_root_relative_only", "absolute_paths": "rejected", "legacy_absolute_artifacts": "owner_controlled_rebuild_or_reviewed_repackage_required", "in_place_rewrite": False}, "minimum lineage migration policy changed")
    review = artifact["review"]
    exact(review, {"decision", "explicit_human_review", "reviewer", "rationale", "reviewed_at"}, "minimum lineage review projection")
    require(review["decision"] == "accepted" and review["explicit_human_review"] is True, "minimum lineage review is not accepted")
    validate_timestamp(review["reviewed_at"])
    replay_minimum_sources(path.parent.resolve(), artifact)
    return artifact


def build(root: Path, paths: dict[str, Path], review_path: Path, output: Path) -> dict[str, Any]:
    root = root.resolve()
    require(root.is_dir() and not root.is_symlink(), "package root must be an existing non-symlink directory")
    require(output.parent.resolve() == root and not output.exists(), "output must be a new file directly inside package root")
    review = normalize_review(load_json(review_path))
    selection = validate_selection_receipt(paths["selection"])
    parsed_input = owners()["input"].parse_cartesian_input(paths["input"])
    sources: dict[str, Any] = {}
    for key, path in paths.items():
        document = load_json(path) if key in {"selection", "input_approval", "job", "result"} else None
        sources[key] = reference(path, root, json_document=document)
    result = load_json(paths["result"])
    artifact = {
        "schema": SCHEMA, "lineage_id": review["lineage_id"], "minimum_id": review["minimum_id"], "state_id": review["state_id"],
        "sources": sources, "workflow_settings": review["workflow_settings"], "stable_atom_ids": review["stable_atom_ids"], "atom_mapping": review["atom_mapping"],
        "formula": review["structure_review"]["formula"], "charge": parsed_input["charge"], "multiplicity": parsed_input["multiplicity"],
        "structure_review": review["structure_review"],
        "review": {key: review[key] for key in ("decision", "explicit_human_review", "reviewer", "rationale", "reviewed_at")},
        "workflow_states": {"human_selected": True, "input_draft_generated": True, "exact_input_approved": True, "job_observed": True, "submission_authorized_by_this_artifact": False, "result_accepted": True},
        "acceptance": {"status": "minimum_accepted", "raw_log_replayed": True, "complete_frequency_gate_passed": True, "zero_imaginary_frequencies": True, "identity_connectivity_stereochemistry_reviewed": True},
        "migration_policy": {"new_bindings": "package_root_relative_only", "absolute_paths": "rejected", "legacy_absolute_artifacts": "owner_controlled_rebuild_or_reviewed_repackage_required", "in_place_rewrite": False},
        "immutability": "append_only_new_revision", "calculation_ready": False, "no_submission_authorization": True, "payload_sha256": None,
    }
    require(selection.get("formula") == artifact["formula"], "selected conformer formula differs from minimum review")
    require(result.get("parser", {}).get("schema") == "auto-g16-gaussian-log-parser/2", "minimum result must record parser schema/version")
    artifact["payload_sha256"] = payload_sha256(artifact)
    replay_minimum_sources(root, artifact)
    try:
        with output.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n")
    except FileExistsError as exc:
        raise LineageError("refusing to overwrite existing minimum lineage output") from exc
    try:
        return validate_artifact(output)
    except Exception:
        output.unlink(missing_ok=True)
        raise


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    build_parser = commands.add_parser("build")
    build_parser.add_argument("--root", type=Path, required=True)
    for name in ("selection", "input-approval", "input", "job", "result", "raw-log", "checkpoint", "optimized-coordinates", "review", "output"):
        build_parser.add_argument(f"--{name}", type=Path, required=True)
    validate_parser = commands.add_parser("validate")
    validate_parser.add_argument("artifact", type=Path)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "validate":
            artifact = validate_artifact(args.artifact)
        else:
            paths = {"selection": args.selection, "input_approval": args.input_approval, "input": args.input, "job": args.job, "result": args.result, "raw_log": args.raw_log, "checkpoint": args.checkpoint, "optimized_coordinates": args.optimized_coordinates}
            artifact = build(args.root, paths, args.review, args.output)
        print(json.dumps({"schema": artifact["schema"], "minimum_id": artifact["minimum_id"], "payload_sha256": artifact["payload_sha256"], "live_actions": False}, ensure_ascii=False))
        return 0
    except (LineageError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
