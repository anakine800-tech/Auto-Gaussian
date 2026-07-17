#!/usr/bin/env python3
"""Offline owner-replay audit for future reaction thermochemistry comparison.

This tool emits only structured readiness blockers.  It does not calculate a
barrier, validate a method or path, modify maturity, or authorize submission.
"""

from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import os
import secrets
import sys
from datetime import datetime
from pathlib import Path, PurePath
from typing import Any

import reaction_workflow as rw


REQUEST_SCHEMA = "gaussian-reaction-thermochemistry-readiness-request/1"
AUDIT_SCHEMA = "gaussian-reaction-thermochemistry-readiness-audit/1"

ROLE_SCHEMAS = {
    "minimum_evidence": "gaussian-scientific-maturity-gate/1",
    "ts_attempt": "gaussian-calculation-attempt-link/1",
    "ts_path_acceptance": "gaussian-ts-irc-path-acceptance/1",
    "energy_lineage": "gaussian-energy-lineage/1",
}
VALIDATOR_IMPLEMENTATIONS = {
    "gaussian-scientific-maturity-gate/1": "scientific_maturity.validate_gate",
    "gaussian-calculation-attempt-link/1": "calculation_artifacts.validate_artifact",
    "gaussian-ts-irc-path-acceptance/1": "ts_irc.validate_path_acceptance_artifact",
    "gaussian-energy-lineage/1": "calculation_artifacts.validate_artifact",
}

REQUEST_KEYS = {
    "schema", "audit_id", "study_id", "owner_artifacts", "reviewer",
    "reviewed_at", "review_notes", "calculation_ready",
    "no_submission_authorization", "payload_sha256",
}
SOURCE_KEYS = {"source_id", "role", "artifact"}
REF_KEYS = {"path", "sha256", "size_bytes", "schema", "payload_sha256"}


def _exact(value: Any, keys: set[str], label: str) -> dict[str, Any]:
    rw.require(isinstance(value, dict), f"{label} must be an object")
    rw.require(set(value) == keys, f"{label} has unknown or missing fields: {sorted(set(value) ^ keys)}")
    return value


def _safe_root(path: Path) -> Path:
    root = path.expanduser().absolute()
    rw.require(root.is_dir() and not root.is_symlink(), f"package root is missing, not a directory, or a symlink: {root}")
    return root.resolve()


def _safe_relative_path(root: Path, value: str, label: str, *, must_exist: bool = True) -> Path:
    rw.require(isinstance(value, str) and value, f"{label} must be a non-empty string")
    raw = Path(value)
    rw.require(not raw.is_absolute(), f"{label} must be package-relative, not absolute")
    rw.require(".." not in PurePath(value).parts, f"{label} contains parent traversal")
    candidate = (root / raw).absolute()
    rw.require(candidate == root or root in candidate.parents, f"{label} escapes the package root")
    current = root
    for part in raw.parts:
        current /= part
        if current.exists() or current.is_symlink():
            rw.require(not current.is_symlink(), f"{label} contains a symlink: {current}")
    if must_exist:
        rw.require(candidate.is_file(), f"{label} is missing or not a regular file: {candidate}")
    return candidate


def _relative(root: Path, path: Path, label: str) -> str:
    absolute = path.expanduser().absolute()
    try:
        return absolute.relative_to(root).as_posix()
    except ValueError as exc:
        raise rw.OfflineError(f"{label} must remain below the package root") from exc


def _resolve_transitive_ref(root: Path, owner_path: Path, ref: dict[str, Any], label: str) -> Path:
    value = ref.get("path")
    rw.require(isinstance(value, str) and value, f"{label}.path must be a non-empty string")
    raw = Path(value)
    rw.require(not raw.is_absolute(), f"{label} must be package-relative, not absolute")
    rw.require(".." not in PurePath(value).parts, f"{label} contains parent traversal")
    # Readiness packages use one unambiguous namespace: every persisted ref is
    # relative to the explicit package root, including owner-transitive refs.
    path = (root / raw).absolute()
    rw.require(path == root or root in path.parents, f"{label} escapes the package root")
    current = root
    for part in path.relative_to(root).parts:
        current /= part
        if current.exists() or current.is_symlink():
            rw.require(not current.is_symlink(), f"{label} contains a symlink: {current}")
    rw.require(path.is_file(), f"{label} is missing or not a regular file")
    rw.require(ref.get("sha256") == rw.sha256_file(path), f"{label} hash drift")
    return path


def _audit_transitive_refs(
    root: Path,
    owner_path: Path,
    document: Any,
    *,
    visited: set[Path] | None = None,
    location: str = "$",
) -> None:
    """Reject unsafe refs anywhere in an owner tree, then recurse into JSON refs."""
    visited = set() if visited is None else visited
    if isinstance(document, dict):
        if isinstance(document.get("path"), str) and isinstance(document.get("sha256"), str):
            path = _resolve_transitive_ref(root, owner_path, document, f"transitive owner ref {location}")
            if (
                isinstance(document.get("schema"), str)
                and isinstance(document.get("payload_sha256"), str)
                and path not in visited
            ):
                visited.add(path)
                child = rw.load_json(path)
                rw.require(child.get("schema") == document["schema"], f"transitive owner ref {location} schema mismatch")
                if "payload_sha256" in child:
                    rw.validate_payload_hash(child)
                _audit_transitive_refs(root, path, child, visited=visited, location=f"{location}->${path.name}")
            return
        for key, value in document.items():
            _audit_transitive_refs(root, owner_path, value, visited=visited, location=f"{location}/{key}")
    elif isinstance(document, list):
        for index, value in enumerate(document):
            _audit_transitive_refs(root, owner_path, value, visited=visited, location=f"{location}/{index}")


def _load_external_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    rw.require(spec is not None and spec.loader is not None, f"owner validator implementation is unavailable: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _owner_validate(path: Path, schema: str) -> dict[str, Any]:
    if schema == "gaussian-scientific-maturity-gate/1":
        import scientific_maturity
        return scientific_maturity.validate_gate(path)
    if schema in {"gaussian-calculation-attempt-link/1", "gaussian-energy-lineage/1"}:
        import calculation_artifacts
        calculation_artifacts.validate_artifact(path)
        return rw.load_json(path)
    if schema == "gaussian-ts-irc-path-acceptance/1":
        ts_path = Path(__file__).resolve().parents[2] / "auto-g16-ts-irc/scripts/ts_irc.py"
        ts_owner = _load_external_module("thermochemistry_readiness_ts_owner", ts_path)
        return ts_owner.validate_path_acceptance_artifact(path)
    raise rw.OfflineError(f"no public owner validator is registered for schema {schema}")


def _load_top_ref(root: Path, raw: Any, label: str) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    ref = _exact(raw, REF_KEYS, label)
    path = _safe_relative_path(root, ref["path"], f"{label}.path")
    rw.require(ref["sha256"] == rw.sha256_file(path), f"{label} file hash drift")
    rw.require(ref["size_bytes"] == path.stat().st_size, f"{label} byte-size drift")
    document = rw.load_json(path)
    rw.require(document.get("schema") == ref["schema"], f"{label} schema mismatch")
    rw.validate_payload_hash(document)
    rw.require(document["payload_sha256"] == ref["payload_sha256"], f"{label} payload hash drift")
    return path, document, copy.deepcopy(ref)


def _timestamp(value: Any, label: str) -> str:
    rw.require(isinstance(value, str) and value, f"{label} must be a non-empty string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise rw.OfflineError(f"{label} must be an ISO-8601 timestamp") from exc
    rw.require(parsed.tzinfo is not None, f"{label} must include a timezone")
    return value


def _blocker(code: str, category: str, source_ids: list[str], message: str, required: str) -> dict[str, Any]:
    return {
        "code": code,
        "category": category,
        "source_ids": sorted(source_ids),
        "message": message,
        "required_owner_contract": required,
    }


def _exact_ts_result_blocker(
    root: Path,
    attempt_source: dict[str, Any],
    path_source: dict[str, Any],
) -> dict[str, Any] | None:
    attempt_ref = attempt_source["document"]["artifacts"]["parsed_result"]
    path_ref = path_source["document"]["ts_result"]
    attempt_result = _resolve_transitive_ref(root, attempt_source["path"], attempt_ref, "attempt parsed TS result")
    path_result = _resolve_transitive_ref(root, path_source["path"], path_ref, "path-acceptance TS result")
    if rw.sha256_file(attempt_result) == rw.sha256_file(path_result):
        return None
    ids = [attempt_source["source_id"], path_source["source_id"]]
    return _blocker(
        "ts_result_hash_mismatch", "ts_evidence", ids,
        "Attempt and path-acceptance owners do not bind the exact same TS result.",
        "one exact owner-validated TS result hash shared by both chains",
    )


def _ts_readiness_blockers(root: Path, roles: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    attempt = roles.get("ts_attempt")
    path_acceptance = roles.get("ts_path_acceptance")
    if attempt is None and path_acceptance is None:
        return [_blocker("ts_owner_chain_missing", "ts_evidence", [], "No exact attempt plus TS/Freq/mode/bidirectional-IRC owner chain was supplied.", "calculation attempt link plus TS-IRC path acceptance")]
    if attempt is None:
        return [_blocker("ts_attempt_missing", "ts_evidence", [path_acceptance["source_id"]], "Path acceptance is not bound to a supplied calculation attempt.", "calculation attempt link sharing the exact TS result")]
    if path_acceptance is None:
        return [_blocker("attempt_link_only_ts", "ts_evidence", [attempt["source_id"]], "Attempt-link-only TS evidence is insufficient.", "ts_irc.validate_path_acceptance_artifact owner chain")]
    mismatch = _exact_ts_result_blocker(root, attempt, path_acceptance)
    return [] if mismatch is None else [mismatch]


def _derive(root: Path, request_path: Path, request: dict[str, Any]) -> dict[str, Any]:
    _exact(request, REQUEST_KEYS, "readiness request")
    rw.require(request["schema"] == REQUEST_SCHEMA, "wrong readiness request schema")
    rw.validate_payload_hash(request)
    audit_id = rw._require_id(request["audit_id"], "audit_id")
    study_id = rw._require_id(request["study_id"], "study_id")
    rw.require(request["calculation_ready"] is False and request["no_submission_authorization"] is True, "request safety flags are invalid")
    reviewer = rw._require_string(request["reviewer"], "reviewer")
    reviewed_at = _timestamp(request["reviewed_at"], "reviewed_at")
    notes = rw._string_list(request["review_notes"], "review_notes", nonempty=True)
    rw.require(isinstance(request["owner_artifacts"], list), "owner_artifacts must be an array")

    sources: dict[str, dict[str, Any]] = {}
    roles: dict[str, dict[str, Any]] = {}
    replayed: list[dict[str, Any]] = []
    normalized_sources: list[dict[str, Any]] = []
    for index, raw in enumerate(request["owner_artifacts"]):
        item = _exact(raw, SOURCE_KEYS, f"owner_artifacts[{index}]")
        source_id = rw._require_id(item["source_id"], f"owner_artifacts[{index}].source_id")
        role = item["role"]
        rw.require(role in ROLE_SCHEMAS, f"unknown owner role: {role}")
        rw.require(source_id not in sources and role not in roles, f"duplicate source_id or owner role: {source_id}/{role}")
        path, document, artifact_ref = _load_top_ref(root, item["artifact"], f"owner artifact {source_id}")
        expected_schema = ROLE_SCHEMAS[role]
        rw.require(document["schema"] == expected_schema, f"role {role} cannot consume owner schema {document['schema']}")
        _audit_transitive_refs(root, path, document, visited={path})
        validated = _owner_validate(path, expected_schema)
        source = {"source_id": source_id, "role": role, "path": path, "document": validated, "artifact": artifact_ref}
        sources[source_id] = source
        roles[role] = source
        normalized_sources.append({"source_id": source_id, "role": role, "artifact": artifact_ref})
        replayed.append({
            "source_id": source_id,
            "role": role,
            "schema": expected_schema,
            "artifact_sha256": artifact_ref["sha256"],
            "validator_implementation": VALIDATOR_IMPLEMENTATIONS[expected_schema],
            "replay_status": "accepted_by_owner_validator",
        })

    blockers: list[dict[str, Any]] = []
    if "minimum_evidence" not in roles:
        blockers.append(_blocker("minimum_owner_evidence_missing", "minimum_evidence", [], "No owner-validated minimum evidence was supplied.", "owner-evidence scientific-maturity gate /2"))
    else:
        blockers.append(_blocker("minimum_owner_evidence_v2_required", "minimum_evidence", [roles["minimum_evidence"]["source_id"]], "Scientific-maturity gate /1 does not close conformer and electronic-state ownership for formal thermochemistry.", "owner-evidence scientific-maturity gate /2"))

    blockers.extend(_ts_readiness_blockers(root, roles))

    if "energy_lineage" not in roles:
        blockers.append(_blocker("energy_lineage_missing", "quantity_lineage", [], "No owner-validated energy lineage was supplied.", "complete owner energy lineage with all formal quantities and contexts"))
    else:
        blockers.append(_blocker("energy_lineage_quantities_incomplete", "quantity_lineage", [roles["energy_lineage"]["source_id"]], "Energy-lineage /1 is electronic-only and does not owner-prove ZPE, thermal, enthalpy, raw Gibbs and full quantity context.", "complete quantity identity/unit/temperature/1M/solvent/SP//geometry lineage"))

    blockers.extend([
        _blocker("low_frequency_application_owner_unavailable", "treated_gibbs", [], "No current public owner schema validates an approved exact per-species low-frequency application record.", "reviewed policy plus exact per-species application owner"),
        _blocker("comparison_inventory_owner_unavailable", "reference_inventory", [], "No current owner chain closes one exact component inventory and catalyst-regeneration relation for formal comparison.", "owner-validated component identity and catalyst relation"),
        _blocker("formal_conformer_coverage_owner_unavailable", "coverage", [], "No current owner chain closes selected minima, TS and component/free-species coverage for every barrier term.", "owner-validated selected coverage for every formal term"),
    ])

    request_ref = {
        "path": _relative(root, request_path, "request source"),
        "sha256": rw.sha256_file(request_path),
        "size_bytes": request_path.stat().st_size,
        "schema": request["schema"],
        "payload_sha256": request["payload_sha256"],
    }
    artifact = {
        "schema": AUDIT_SCHEMA,
        "audit_id": audit_id,
        "study_id": study_id,
        "request_source": request_ref,
        "owner_artifacts": sorted(normalized_sources, key=lambda item: item["source_id"]),
        "owner_replays": sorted(replayed, key=lambda item: item["source_id"]),
        "blockers": sorted(blockers, key=lambda item: item["code"]),
        "formal_comparison_ready": False,
        "formal_barrier_available": False,
        "arithmetic_performed": False,
        "scientific_nonclaims": {
            "method_validated": False,
            "path_accepted_by_audit": False,
            "scientific_maturity_modified": False,
            "submission_authorized": False,
        },
        "reviewer": reviewer,
        "reviewed_at": reviewed_at,
        "review_notes": notes,
        "calculation_ready": False,
        "no_submission_authorization": True,
    }
    return rw.finalize_artifact(artifact)


def _input_path(root: Path, path: Path, label: str) -> Path:
    value = _relative(root, path, label) if path.is_absolute() else path.as_posix()
    return _safe_relative_path(root, value, label)


def _output_path(root: Path, path: Path) -> Path:
    value = _relative(root, path, "audit output") if path.is_absolute() else path.as_posix()
    output = _safe_relative_path(root, value, "audit output", must_exist=False)
    rw.require(output.parent.is_dir() and not output.parent.is_symlink(), "audit output parent must already exist and cannot be a symlink")
    return output


def _publish_json(path: Path, document: dict[str, Any]) -> None:
    """Atomically publish a new immutable file without a check-then-write race."""
    content = (json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    temporary = path.parent / f".{path.name}.{secrets.token_hex(12)}.tmp"
    try:
        with temporary.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError as exc:
            raise rw.OfflineError(f"refusing to overwrite existing artifact: {path}") from exc
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def build(root: Path, request_path: Path, output_path: Path) -> dict[str, Any]:
    root = _safe_root(root)
    request_path = _input_path(root, request_path, "readiness request")
    artifact = _derive(root, request_path, rw.load_json(request_path))
    _publish_json(_output_path(root, output_path), artifact)
    return artifact


def validate(root: Path, artifact_path: Path) -> dict[str, Any]:
    root = _safe_root(root)
    artifact_path = _input_path(root, artifact_path, "readiness audit")
    artifact = rw.load_json(artifact_path)
    rw.require(artifact.get("schema") == AUDIT_SCHEMA, "wrong readiness audit schema")
    rw.validate_payload_hash(artifact)
    request_path, request, request_ref = _load_top_ref(root, artifact.get("request_source"), "request_source")
    rw.require(request_ref["schema"] == REQUEST_SCHEMA, "wrong readiness request source schema")
    expected = _derive(root, request_path, request)
    rw.require(artifact == expected, "readiness audit differs from deterministic owner replay")
    return artifact


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Offline Auto-G16 thermochemistry readiness audit; no barrier arithmetic or live action")
    sub = parser.add_subparsers(dest="command", required=True)
    build_cmd = sub.add_parser("build", help="build an immutable blocker audit")
    build_cmd.add_argument("request")
    build_cmd.add_argument("--root", required=True)
    build_cmd.add_argument("--output", required=True)
    validate_cmd = sub.add_parser("validate", help="replay an immutable blocker audit")
    validate_cmd.add_argument("artifact")
    validate_cmd.add_argument("--root", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "build":
            artifact = build(Path(args.root), Path(args.request), Path(args.output))
        else:
            artifact = validate(Path(args.root), Path(args.artifact))
        print(json.dumps({
            "schema": artifact["schema"],
            "audit_id": artifact["audit_id"],
            "blocker_count": len(artifact["blockers"]),
            "formal_comparison_ready": False,
            "formal_barrier_available": False,
            "calculation_ready": False,
            "no_submission_authorization": True,
            "live_actions": False,
        }, sort_keys=True, ensure_ascii=False))
        return 0
    except (rw.OfflineError, OSError, ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
