#!/usr/bin/env python3
"""Build and validate an offline reaction calculation plan and resume index.

This module is deliberately standard-library-only.  It never renders a
Gaussian input, selects a protocol, contacts a host, or authorizes execution.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import heapq
import json
import os
import re
import stat
import sys
from pathlib import Path
from typing import Any, Iterable

import mechanism_network as mechanism
import mechanism_support
import reaction_workflow as rw
import ts_precedent_map as ts_precedent
import calculation_artifacts


REVIEW_SCHEMA = "gaussian-reaction-calculation-plan-review/1"
PLAN_SCHEMA = "gaussian-reaction-calculation-plan/1"
INDEX_SCHEMA = "gaussian-reaction-study-index/1"
SUPPORT_SCHEMA = "gaussian-reaction-mechanism-support/1"
PRECEDENT_SCHEMA = "gaussian-ts-precedent-map/1"
TARGET_IMPORT_SCHEMA = "gaussian-candidate-target-import/1"
MAPPING_REVIEW_SCHEMA = "gaussian-reaction-calculation-target-mapping-review/1"
NODE_UPDATE_SCHEMA = "gaussian-reaction-calculation-node-update/1"

SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
NODE_KINDS = (
    "minimum",
    "conformer",
    "complex",
    "ts_candidate",
    "ts_freq",
    "irc_forward",
    "irc_reverse",
    "endpoint",
    "single_point",
    "thermochemistry",
    "sensitivity",
)
STRUCTURAL_KINDS = {"minimum", "conformer", "complex"}
PATH_KINDS = {"ts_candidate", "ts_freq", "irc_forward", "irc_reverse", "endpoint"}
GEOMETRY_KINDS = STRUCTURAL_KINDS | PATH_KINDS | {"single_point"}
MAX_SUPERSEDED_PLAN_DEPTH = 128
ALLOWED_PREDECESSORS = {
    "minimum": STRUCTURAL_KINDS,
    "conformer": STRUCTURAL_KINDS,
    "complex": STRUCTURAL_KINDS,
    "ts_candidate": STRUCTURAL_KINDS,
    "ts_freq": {"ts_candidate"},
    "irc_forward": {"ts_freq"},
    "irc_reverse": {"ts_freq"},
    "endpoint": {"irc_forward", "irc_reverse"},
    "single_point": {"minimum", "ts_freq", "endpoint"},
    "thermochemistry": {"minimum", "ts_freq", "endpoint", "single_point"},
    "sensitivity": {"single_point", "thermochemistry"},
}
REQUIRES_DEPENDENCY = set(NODE_KINDS) - STRUCTURAL_KINDS

REVIEW_KEYS = {
    "schema",
    "study_id",
    "plan_id",
    "intake_payload_sha256",
    "species_registry_payload_sha256",
    "condition_model_payload_sha256",
    "mechanism_network_payload_sha256",
    "mechanism_support_payload_sha256",
    "ts_precedent_map_payload_sha256",
    "superseded_plan_payload_sha256s",
    "nodes",
    "alternative_groups",
    "supersessions",
    "review_decision",
    "review_notes",
    "payload_sha256",
}
PLAN_KEYS = {
    "schema",
    "study_id",
    "plan_id",
    "intake",
    "species_registry",
    "condition_model",
    "mechanism_network",
    "mechanism_support",
    "ts_precedent_map",
    "review_source",
    "superseded_plans",
    "nodes",
    "alternative_groups",
    "supersessions",
    "topological_order",
    "coverage",
    "blockers",
    "review",
    "gate_status",
    "calculation_ready",
    "no_submission_authorization",
    "payload_sha256",
}
INDEX_KEYS = {
    "schema",
    "study_id",
    "plan_id",
    "calculation_plan",
    "artifacts",
    "superseded_artifacts",
    "stage_gates",
    "last_accepted_stage",
    "next_blockers",
    "next_safe_offline_action",
    "node_resume",
    "coverage",
    "read_only",
    "calculation_ready",
    "no_submission_authorization",
    "payload_sha256",
}
MAPPING_REVIEW_KEYS = {
    "schema", "update_id", "target_plan", "target_import", "external_target_key",
    "locator", "expected_node_kind", "update_kind", "artifact_role",
    "supersedes", "review_decision", "reviewer", "reviewed_at",
    "review_notes", "calculation_ready", "no_submission_authorization",
    "payload_sha256",
}
NODE_UPDATE_KEYS = {
    "schema", "update_id", "locator", "expected_node_kind", "target_plan",
    "review_source", "update_kind", "artifact_role", "artifact",
    "external_target", "supersedes", "review", "calculation_ready",
    "no_submission_authorization", "payload_sha256",
}
EXTERNAL_TARGET_KEY_RE = re.compile(r"^[a-z][a-z0-9_.:-]{2,255}$")


class ContractError(ValueError):
    """The offline calculation-planning contract was violated."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def _reject_constant(value: str) -> None:
    raise ContractError(f"non-standard JSON numeric constant is forbidden: {value}")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON object key is forbidden: {key}")
        result[key] = value
    return result


def _reject_absolute_symlink_chain(path: Path, label: str) -> Path:
    """Reject caller-controlled symlinks while accepting an OS anchor alias.

    macOS normally exposes canonical roots such as ``/private/var`` through a
    root-owned first-component alias (``/var``).  That ambient alias is outside
    the artifact contract.  It is resolved once; every deeper component is
    checked with ``lstat`` and must be a real directory or leaf.
    """

    absolute = path.absolute()
    current = Path(absolute.anchor)
    for depth, part in enumerate(absolute.parts[1:], start=1):
        current = current / part
        try:
            mode = os.lstat(current).st_mode
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise ContractError(f"could not inspect {label} path component {current}: {exc}") from exc
        if stat.S_ISLNK(mode) and depth == 1:
            try:
                current = current.resolve(strict=True)
            except OSError as exc:
                raise ContractError(f"could not resolve trusted OS path alias {current}: {exc}") from exc
            continue
        require(not stat.S_ISLNK(mode), f"{label} path contains a symlink: {current}")
    return absolute


def load_json(path: Path) -> dict[str, Any]:
    absolute = _reject_absolute_symlink_chain(path, "JSON artifact")
    require(absolute.is_file(), f"JSON artifact is missing: {absolute}")
    try:
        raw = absolute.read_bytes()
        value = json.loads(
            raw.decode("utf-8"),
            parse_constant=_reject_constant,
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"could not read JSON {path}: {exc}") from exc
    require(isinstance(value, dict), f"{path}: top-level JSON must be an object")
    return value


def _load_json_bytes(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            raw.decode("utf-8"),
            parse_constant=_reject_constant,
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"could not read {label} JSON: {exc}") from exc
    require(isinstance(value, dict), f"{label}: top-level JSON must be an object")
    return value


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def payload_sha256(value: dict[str, Any]) -> str:
    payload = copy.deepcopy(value)
    payload.pop("payload_sha256", None)
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def finalize(value: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(value)
    result["payload_sha256"] = payload_sha256(result)
    return result


def validate_payload(value: dict[str, Any], label: str) -> None:
    digest = value.get("payload_sha256")
    require(isinstance(digest, str) and SHA256_RE.fullmatch(digest) is not None, f"{label} payload_sha256 is invalid")
    require(digest == payload_sha256(value), f"{label} payload SHA-256 mismatch")


def _new_output_path(path: Path) -> Path:
    """Validate an immutable output path without creating any parent directory."""

    absolute = path.absolute()
    parent = _reject_absolute_symlink_chain(absolute.parent, "output artifact")
    require(parent.exists() and parent.is_dir(), "output artifact parent must already exist as a real directory")
    if os.path.lexists(absolute):
        raise ContractError(f"refusing to overwrite existing artifact: {absolute}")
    return absolute


def write_json(path: Path, value: dict[str, Any]) -> None:
    target = _new_output_path(path)
    try:
        with target.open("xb") as handle:
            handle.write(canonical_bytes(value))
    except FileExistsError:
        raise ContractError(f"refusing to overwrite existing artifact: {target}") from None


def _exact(value: Any, keys: set[str], label: str) -> dict[str, Any]:
    require(isinstance(value, dict), f"{label} must be an object")
    unknown = sorted(set(value) - keys)
    missing = sorted(keys - set(value))
    require(not unknown, f"{label} contains unknown fields: {', '.join(unknown)}")
    require(not missing, f"{label} is missing required fields: {', '.join(missing)}")
    return value


def _identifier(value: Any, label: str) -> str:
    require(isinstance(value, str) and rw.ID_RE.fullmatch(value) is not None, f"{label} must be a stable lowercase ID")
    return value


def _string(value: Any, label: str, *, allow_empty: bool = False) -> str:
    require(isinstance(value, str), f"{label} must be a string")
    require(allow_empty or bool(value.strip()), f"{label} must not be empty")
    return value


def _string_list(value: Any, label: str, *, ids: bool = False) -> list[str]:
    require(isinstance(value, list), f"{label} must be an array")
    result: list[str] = []
    for index, item in enumerate(value):
        result.append(_identifier(item, f"{label}[{index}]") if ids else _string(item, f"{label}[{index}]"))
    require(len(result) == len(set(result)), f"{label} contains duplicates")
    return result


def _sha256(value: Any, label: str, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    require(isinstance(value, str) and SHA256_RE.fullmatch(value) is not None, f"{label} must be a SHA-256 digest")
    return value


def _integer(value: Any, label: str, *, positive: bool = False, nullable: bool = False) -> int | None:
    if value is None and nullable:
        return None
    require(isinstance(value, int) and not isinstance(value, bool), f"{label} must be an integer")
    require(not positive or value > 0, f"{label} must be positive")
    return value


def _derived_id(prefix: str, suffix: str) -> str:
    candidate = f"{prefix}_{suffix}"
    if len(candidate) <= 64 and rw.ID_RE.fullmatch(candidate):
        return candidate
    digest = hashlib.sha256(candidate.encode("utf-8")).hexdigest()[:20]
    return f"dag_{digest}_{suffix[:20]}"


def _blocker(blocker_id: str, scope: str, description: str, required_for: Iterable[str]) -> dict[str, Any]:
    normalized_required_for = sorted(set(_string(item, "blocker required_for") for item in required_for))
    require(bool(normalized_required_for), "blocker required_for must contain at least one gate or stage")
    return {
        "blocker_id": _identifier(blocker_id, "blocker_id"),
        "scope": _string(scope, "blocker scope"),
        "description": _string(description, "blocker description"),
        "required_for": normalized_required_for,
    }


def _normalize_blocker(value: Any, label: str) -> dict[str, Any]:
    data = _exact(value, {"blocker_id", "scope", "description", "required_for"}, label)
    return _blocker(
        _identifier(data["blocker_id"], f"{label}.blocker_id"),
        _string(data["scope"], f"{label}.scope"),
        _string(data["description"], f"{label}.description"),
        _string_list(data["required_for"], f"{label}.required_for"),
    )


def _sort_blockers(blockers: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for blocker in blockers:
        blocker_id = blocker["blocker_id"]
        if blocker_id in index:
            require(index[blocker_id] == blocker, f"duplicate blocker_id has conflicting definitions: {blocker_id}")
        index[blocker_id] = blocker
    return [index[key] for key in sorted(index)]


def _reject_symlink_chain(root: Path, candidate: Path, label: str) -> None:
    require(root.exists() and root.is_dir(), f"{label} artifact root is missing")
    _reject_absolute_symlink_chain(root, f"{label} artifact root")
    try:
        relative = candidate.relative_to(root)
    except ValueError:
        raise ContractError(f"{label} escapes artifact root") from None
    current = root
    for part in relative.parts:
        current = current / part
        try:
            mode = os.lstat(current).st_mode
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise ContractError(f"could not inspect {label} path component {current}: {exc}") from exc
        require(not stat.S_ISLNK(mode), f"{label} path contains a symlink: {current}")


def _portable_path(path: Path, root: Path, label: str) -> tuple[Path, str]:
    root_abs = root.absolute()
    candidate_abs = path.absolute()
    _reject_symlink_chain(root_abs, candidate_abs, label)
    require(candidate_abs.is_file(), f"{label} is missing: {candidate_abs}")
    resolved_root = root_abs.resolve()
    resolved = candidate_abs.resolve()
    require(resolved.is_relative_to(resolved_root), f"{label} escapes artifact root")
    relative = resolved.relative_to(resolved_root)
    require(not relative.is_absolute() and ".." not in relative.parts, f"{label} path must be portable and relative")
    return resolved, relative.as_posix()


def _binding_from_path(path: Path, root: Path, expected_schema: str, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    resolved, display = _portable_path(path, root, label)
    raw = resolved.read_bytes()
    data = _load_json_bytes(raw, label)
    require(data.get("schema") == expected_schema, f"{label} schema mismatch")
    validate_payload(data, label)
    binding = {
        "path": display,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "size_bytes": len(raw),
        "schema": expected_schema,
        "payload_sha256": data["payload_sha256"],
    }
    return data, binding


def _resolve_binding(
    binding: Any,
    owner_path: Path,
    expected_schema: str | None,
    label: str,
) -> tuple[dict[str, Any], Path]:
    data = _exact(binding, {"path", "sha256", "size_bytes", "schema", "payload_sha256"}, f"{label} binding")
    relative = Path(_string(data["path"], f"{label}.path"))
    require(not relative.is_absolute(), f"{label} path must be portable and relative")
    require(".." not in relative.parts, f"{label} path must not contain parent traversal")
    _sha256(data["sha256"], f"{label}.sha256")
    _integer(data["size_bytes"], f"{label}.size_bytes")
    schema = _string(data["schema"], f"{label}.schema")
    _sha256(data["payload_sha256"], f"{label}.payload_sha256")
    require(expected_schema is None or schema == expected_schema, f"{label} binding schema mismatch")
    root = owner_path.parent.absolute()
    candidate = root / relative
    _reject_symlink_chain(root, candidate, label)
    require(candidate.is_file(), f"{label} artifact is missing: {candidate}")
    resolved = candidate.resolve()
    require(resolved.is_relative_to(root.resolve()), f"{label} artifact escapes artifact root")
    raw = resolved.read_bytes()
    require(len(raw) == data["size_bytes"], f"{label} artifact size drift")
    require(hashlib.sha256(raw).hexdigest() == data["sha256"], f"{label} artifact file hash drift")
    artifact = _load_json_bytes(raw, label)
    require(artifact.get("schema") == schema, f"{label} artifact schema mismatch")
    require(artifact.get("payload_sha256") == data["payload_sha256"], f"{label} artifact payload binding mismatch")
    validate_payload(artifact, label)
    return artifact, resolved


def _normalize_atom_ref(value: Any, label: str) -> dict[str, str]:
    data = _exact(value, {"state_id", "atom_id"}, label)
    return {
        "state_id": _identifier(data["state_id"], f"{label}.state_id"),
        "atom_id": _identifier(data["atom_id"], f"{label}.atom_id"),
    }


def _normalize_target(value: Any, label: str) -> dict[str, Any]:
    data = _exact(value, {"state_ids", "edge_ids", "network_ids", "reference_basin_ids", "atom_refs"}, label)
    atom_refs_raw = data["atom_refs"]
    require(isinstance(atom_refs_raw, list), f"{label}.atom_refs must be an array")
    atom_refs = [_normalize_atom_ref(item, f"{label}.atom_refs[{index}]") for index, item in enumerate(atom_refs_raw)]
    pairs = [(item["state_id"], item["atom_id"]) for item in atom_refs]
    require(len(pairs) == len(set(pairs)), f"{label}.atom_refs contains duplicates")
    return {
        "state_ids": sorted(_string_list(data["state_ids"], f"{label}.state_ids", ids=True)),
        "edge_ids": sorted(_string_list(data["edge_ids"], f"{label}.edge_ids", ids=True)),
        "network_ids": sorted(_string_list(data["network_ids"], f"{label}.network_ids", ids=True)),
        "reference_basin_ids": sorted(_string_list(data["reference_basin_ids"], f"{label}.reference_basin_ids", ids=True)),
        "atom_refs": sorted(atom_refs, key=lambda item: (item["state_id"], item["atom_id"])),
    }


def _normalize_chemical_state(value: Any, label: str) -> dict[str, Any]:
    data = _exact(value, {"formal_charge", "multiplicity", "atom_order"}, label)
    atom_order: list[dict[str, str]] | None
    if data["atom_order"] is None:
        atom_order = None
    else:
        require(isinstance(data["atom_order"], list), f"{label}.atom_order must be an array or null")
        atom_order = [_normalize_atom_ref(item, f"{label}.atom_order[{index}]") for index, item in enumerate(data["atom_order"])]
        pairs = [(item["state_id"], item["atom_id"]) for item in atom_order]
        require(len(pairs) == len(set(pairs)), f"{label}.atom_order contains duplicates")
    return {
        "formal_charge": _integer(data["formal_charge"], f"{label}.formal_charge", nullable=True),
        "multiplicity": _integer(data["multiplicity"], f"{label}.multiplicity", positive=True, nullable=True),
        "atom_order": atom_order,
    }


def _normalize_input(value: Any, label: str) -> dict[str, Any]:
    data = _exact(value, {"slot_id", "artifact_role", "source_node_id", "required", "description"}, label)
    source = data["source_node_id"]
    require(source is None or isinstance(source, str), f"{label}.source_node_id must be an ID or null")
    require(isinstance(data["required"], bool), f"{label}.required must be a boolean")
    return {
        "slot_id": _identifier(data["slot_id"], f"{label}.slot_id"),
        "artifact_role": _identifier(data["artifact_role"], f"{label}.artifact_role"),
        "source_node_id": None if source is None else _identifier(source, f"{label}.source_node_id"),
        "required": data["required"],
        "description": _string(data["description"], f"{label}.description"),
    }


def _normalize_output(value: Any, label: str) -> dict[str, Any]:
    data = _exact(value, {"slot_id", "artifact_role", "description"}, label)
    return {
        "slot_id": _identifier(data["slot_id"], f"{label}.slot_id"),
        "artifact_role": _identifier(data["artifact_role"], f"{label}.artifact_role"),
        "description": _string(data["description"], f"{label}.description"),
    }


def _normalize_node(value: Any, index: int) -> dict[str, Any]:
    label = f"nodes[{index}]"
    keys = {
        "node_id", "label", "node_kind", "target", "chemical_state", "inputs", "outputs",
        "depends_on", "alternative_group_id", "disposition", "execution_state",
        "evidence_acceptance", "review_blockers", "notes",
    }
    data = _exact(value, keys, label)
    node_id = _identifier(data["node_id"], f"{label}.node_id")
    kind = data["node_kind"]
    require(kind in NODE_KINDS, f"node {node_id} uses unsupported node kind: {kind}")
    inputs_raw = data["inputs"]
    outputs_raw = data["outputs"]
    blockers_raw = data["review_blockers"]
    require(isinstance(inputs_raw, list), f"node {node_id}.inputs must be an array")
    require(isinstance(outputs_raw, list) and outputs_raw, f"node {node_id}.outputs must be a non-empty array")
    require(isinstance(blockers_raw, list), f"node {node_id}.review_blockers must be an array")
    inputs = [_normalize_input(item, f"node {node_id}.inputs[{offset}]") for offset, item in enumerate(inputs_raw)]
    outputs = [_normalize_output(item, f"node {node_id}.outputs[{offset}]") for offset, item in enumerate(outputs_raw)]
    require(len({item["slot_id"] for item in inputs}) == len(inputs), f"node {node_id} has duplicate input slot IDs")
    require(len({item["slot_id"] for item in outputs}) == len(outputs), f"node {node_id} has duplicate output slot IDs")
    require(len({item["artifact_role"] for item in outputs}) == len(outputs), f"node {node_id} has duplicate output artifact roles")
    review_blockers = [_normalize_blocker(item, f"node {node_id}.review_blockers[{offset}]") for offset, item in enumerate(blockers_raw)]
    for blocker in review_blockers:
        require(blocker["scope"] == node_id, f"node {node_id} review blocker scope must equal its node_id")
    alternative_group_id = data["alternative_group_id"]
    require(alternative_group_id is None or isinstance(alternative_group_id, str), f"node {node_id}.alternative_group_id must be an ID or null")
    disposition = data["disposition"]
    execution = data["execution_state"]
    evidence = data["evidence_acceptance"]
    require(disposition in {"planned", "retained", "skipped", "superseded"}, f"node {node_id} disposition is invalid")
    require(execution in {"not_started", "succeeded", "failed", "cancelled", "not_applicable"}, f"node {node_id} execution_state is invalid")
    require(evidence in {"not_available", "pending_review", "accepted", "rejected", "inconclusive", "not_applicable"}, f"node {node_id} evidence_acceptance is invalid")
    return {
        "node_id": node_id,
        "label": _string(data["label"], f"node {node_id}.label"),
        "node_kind": kind,
        "target": _normalize_target(data["target"], f"node {node_id}.target"),
        "chemical_state": _normalize_chemical_state(data["chemical_state"], f"node {node_id}.chemical_state"),
        "inputs": sorted(inputs, key=lambda item: item["slot_id"]),
        "outputs": sorted(outputs, key=lambda item: item["slot_id"]),
        "depends_on": sorted(_string_list(data["depends_on"], f"node {node_id}.depends_on", ids=True)),
        "alternative_group_id": None if alternative_group_id is None else _identifier(alternative_group_id, f"node {node_id}.alternative_group_id"),
        "disposition": disposition,
        "execution_state": execution,
        "evidence_acceptance": evidence,
        "review_blockers": _sort_blockers(review_blockers),
        "notes": _string_list(data["notes"], f"node {node_id}.notes"),
    }


def _normalize_alternative(value: Any, index: int) -> dict[str, Any]:
    label = f"alternative_groups[{index}]"
    data = _exact(value, {"group_id", "label", "node_ids", "selection_policy", "selected_node_ids", "review_status", "rationale"}, label)
    group_id = _identifier(data["group_id"], f"{label}.group_id")
    policy = data["selection_policy"]
    status = data["review_status"]
    require(policy in {"retain_all", "select_one", "select_zero_or_one"}, f"alternative group {group_id} selection_policy is invalid")
    require(status in {"reviewed", "blocked"}, f"alternative group {group_id} review_status is invalid")
    return {
        "group_id": group_id,
        "label": _string(data["label"], f"alternative group {group_id}.label"),
        "node_ids": sorted(_string_list(data["node_ids"], f"alternative group {group_id}.node_ids", ids=True)),
        "selection_policy": policy,
        "selected_node_ids": sorted(_string_list(data["selected_node_ids"], f"alternative group {group_id}.selected_node_ids", ids=True)),
        "review_status": status,
        "rationale": _string(data["rationale"], f"alternative group {group_id}.rationale"),
    }


def _normalize_supersession(value: Any, index: int) -> dict[str, Any]:
    label = f"supersessions[{index}]"
    data = _exact(value, {"supersession_id", "superseding_node_id", "superseded_node_ids", "rationale"}, label)
    supersession_id = _identifier(data["supersession_id"], f"{label}.supersession_id")
    return {
        "supersession_id": supersession_id,
        "superseding_node_id": _identifier(data["superseding_node_id"], f"supersession {supersession_id}.superseding_node_id"),
        "superseded_node_ids": sorted(_string_list(data["superseded_node_ids"], f"supersession {supersession_id}.superseded_node_ids", ids=True)),
        "rationale": _string(data["rationale"], f"supersession {supersession_id}.rationale"),
    }


def normalize_review(value: dict[str, Any], *, require_hash: bool) -> dict[str, Any]:
    data = _exact(value, REVIEW_KEYS, "calculation-plan review")
    require(data["schema"] == REVIEW_SCHEMA, "unrecognized calculation-plan review schema")
    review_hash = data["payload_sha256"]
    if require_hash:
        validate_payload(data, "calculation-plan review")
    else:
        require(review_hash is None, "review draft payload_sha256 must be null before finalization")
    nodes_raw = data["nodes"]
    alternatives_raw = data["alternative_groups"]
    supersessions_raw = data["supersessions"]
    require(isinstance(nodes_raw, list) and nodes_raw, "calculation-plan review nodes must be a non-empty array")
    require(isinstance(alternatives_raw, list), "calculation-plan review alternative_groups must be an array")
    require(isinstance(supersessions_raw, list), "calculation-plan review supersessions must be an array")
    nodes = [_normalize_node(item, index) for index, item in enumerate(nodes_raw)]
    alternatives = [_normalize_alternative(item, index) for index, item in enumerate(alternatives_raw)]
    supersessions = [_normalize_supersession(item, index) for index, item in enumerate(supersessions_raw)]
    for label, items, key in (
        ("node", nodes, "node_id"),
        ("alternative group", alternatives, "group_id"),
        ("supersession", supersessions, "supersession_id"),
    ):
        identifiers = [item[key] for item in items]
        require(len(identifiers) == len(set(identifiers)), f"duplicate {label} IDs are forbidden")
    decision = data["review_decision"]
    require(decision in {"accepted", "accepted_with_blockers", "blocked"}, "calculation-plan review_decision is invalid")
    superseded_hashes = _string_list(data["superseded_plan_payload_sha256s"], "superseded_plan_payload_sha256s")
    for index, digest in enumerate(superseded_hashes):
        _sha256(digest, f"superseded_plan_payload_sha256s[{index}]")
    normalized = {
        "schema": REVIEW_SCHEMA,
        "study_id": _identifier(data["study_id"], "review study_id"),
        "plan_id": _identifier(data["plan_id"], "review plan_id"),
        "intake_payload_sha256": _sha256(data["intake_payload_sha256"], "review intake payload"),
        "species_registry_payload_sha256": _sha256(data["species_registry_payload_sha256"], "review species-registry payload"),
        "condition_model_payload_sha256": _sha256(data["condition_model_payload_sha256"], "review condition-model payload"),
        "mechanism_network_payload_sha256": _sha256(data["mechanism_network_payload_sha256"], "review mechanism-network payload"),
        "mechanism_support_payload_sha256": _sha256(data["mechanism_support_payload_sha256"], "review mechanism-support payload", nullable=True),
        "ts_precedent_map_payload_sha256": _sha256(data["ts_precedent_map_payload_sha256"], "review TS-precedent payload", nullable=True),
        "superseded_plan_payload_sha256s": sorted(superseded_hashes),
        "nodes": sorted(nodes, key=lambda item: item["node_id"]),
        "alternative_groups": sorted(alternatives, key=lambda item: item["group_id"]),
        "supersessions": sorted(supersessions, key=lambda item: item["supersession_id"]),
        "review_decision": decision,
        "review_notes": _string_list(data["review_notes"], "review_notes"),
        "payload_sha256": review_hash,
    }
    if require_hash:
        require(normalized == data, "calculation-plan review is not in deterministic normalized form")
    return normalized


def finalize_review(draft_path: Path, output: Path) -> dict[str, Any]:
    draft = load_json(draft_path)
    normalized = normalize_review(draft, require_hash=False)
    artifact = finalize(normalized)
    write_json(output, artifact)
    return {
        "schema": "gaussian-reaction-calculation-plan-review-finalization/1",
        "study_id": artifact["study_id"],
        "plan_id": artifact["plan_id"],
        "payload_sha256": artifact["payload_sha256"],
        "calculation_ready": False,
        "no_submission_authorization": True,
        "live_actions": False,
    }


def _index_by(items: list[dict[str, Any]], key: str, label: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in items:
        identifier = item[key]
        require(identifier not in result, f"duplicate {label} ID: {identifier}")
        result[identifier] = item
    return result


def _target_signature(node: dict[str, Any]) -> bytes:
    return canonical_bytes({"node_kind": node["node_kind"], "target": node["target"]})


def _topological_order(nodes: dict[str, dict[str, Any]]) -> list[str]:
    indegree = {node_id: 0 for node_id in nodes}
    children: dict[str, list[str]] = {node_id: [] for node_id in nodes}
    for node_id, node in nodes.items():
        for dependency in node["depends_on"]:
            require(dependency in nodes, f"node {node_id} depends on missing node: {dependency}")
            require(dependency != node_id, f"node {node_id} has a self dependency")
            indegree[node_id] += 1
            children[dependency].append(node_id)
    queue = [node_id for node_id, degree in indegree.items() if degree == 0]
    heapq.heapify(queue)
    order: list[str] = []
    while queue:
        node_id = heapq.heappop(queue)
        order.append(node_id)
        for child in sorted(children[node_id]):
            indegree[child] -= 1
            if indegree[child] == 0:
                heapq.heappush(queue, child)
    require(len(order) == len(nodes), "calculation DAG contains a dependency cycle")
    return order


def _validate_graph_relations(
    nodes: dict[str, dict[str, Any]],
    alternatives: list[dict[str, Any]],
    supersessions: list[dict[str, Any]],
) -> list[str]:
    for node_id, node in nodes.items():
        dependencies = node["depends_on"]
        if node["node_kind"] in REQUIRES_DEPENDENCY:
            require(bool(dependencies), f"orphan {node['node_kind']} node lacks a required predecessor: {node_id}")
        for dependency in dependencies:
            require(dependency in nodes, f"node {node_id} depends on missing node: {dependency}")
            predecessor_kind = nodes[dependency]["node_kind"]
            require(
                predecessor_kind in ALLOWED_PREDECESSORS[node["node_kind"]],
                f"illegal stage ordering: {predecessor_kind} cannot precede {node['node_kind']} for node {node_id}",
            )
            if node["node_kind"] == "single_point":
                state_target = bool(node["target"]["state_ids"]) and not node["target"]["edge_ids"]
                edge_target = bool(node["target"]["edge_ids"]) and not node["target"]["state_ids"]
                if state_target:
                    require(predecessor_kind in {"minimum", "endpoint"}, f"single_point state target {node_id} requires a minimum or endpoint predecessor")
                elif edge_target:
                    require(predecessor_kind == "ts_freq", f"single_point edge target {node_id} requires a ts_freq predecessor")
        input_sources = {item["source_node_id"] for item in node["inputs"] if item["source_node_id"] is not None}
        require(input_sources == set(dependencies), f"node {node_id} dependencies must exactly equal its source-node input bindings")
        for item in node["inputs"]:
            source = item["source_node_id"]
            require(not (item["required"] and source is None), f"node {node_id} required input {item['slot_id']} must bind an exact source node or producer")
            if source is None:
                continue
            require(source in nodes, f"node {node_id} input references missing source node: {source}")
            roles = {output["artifact_role"] for output in nodes[source]["outputs"]}
            require(item["artifact_role"] in roles, f"node {node_id} input role {item['artifact_role']} is not produced by {source}")

    group_index = _index_by(alternatives, "group_id", "alternative group")
    membership: dict[str, str] = {}
    for group in alternatives:
        members = group["node_ids"]
        selected = group["selected_node_ids"]
        require(len(members) >= 2, f"alternative group {group['group_id']} must contain at least two nodes")
        require(set(selected).issubset(members), f"alternative group {group['group_id']} selects a non-member node")
        if group["selection_policy"] == "retain_all":
            require(set(selected) == set(members), f"retain_all alternative group {group['group_id']} must select every member")
        elif group["selection_policy"] == "select_one":
            require(len(selected) == 1, f"select_one alternative group {group['group_id']} must select exactly one member")
        else:
            require(len(selected) <= 1, f"select_zero_or_one alternative group {group['group_id']} selects too many members")
        signatures: set[bytes] = set()
        for node_id in members:
            require(node_id in nodes, f"alternative group {group['group_id']} references missing node: {node_id}")
            require(node_id not in membership, f"node {node_id} belongs to multiple alternative groups")
            membership[node_id] = group["group_id"]
            signatures.add(_target_signature(nodes[node_id]))
            require(not set(nodes[node_id]["depends_on"]).intersection(members), f"alternative group {group['group_id']} members cannot depend on each other")
        require(len(signatures) == 1, f"alternative group {group['group_id']} mixes node kinds or mechanism targets")
        for node_id in members:
            if node_id in selected:
                require(nodes[node_id]["disposition"] in {"planned", "retained"}, f"alternative group {group['group_id']} selects inactive node {node_id}")
            else:
                require(nodes[node_id]["disposition"] in {"skipped", "superseded"}, f"unselected alternative node {node_id} must be retained as inactive history")
    for node_id, node in nodes.items():
        declared = node["alternative_group_id"]
        require((declared is None and node_id not in membership) or membership.get(node_id) == declared, f"node {node_id} alternative_group_id is inconsistent")
        if declared is not None:
            require(declared in group_index, f"node {node_id} references missing alternative group: {declared}")

    superseded_once: dict[str, str] = {}
    for record in supersessions:
        new_id = record["superseding_node_id"]
        old_ids = record["superseded_node_ids"]
        require(new_id in nodes, f"supersession {record['supersession_id']} references missing superseding node")
        require(old_ids, f"supersession {record['supersession_id']} must name at least one superseded node")
        require(nodes[new_id]["disposition"] in {"planned", "retained", "superseded"}, f"superseding node {new_id} must remain in a valid supersession chain")
        for old_id in old_ids:
            require(old_id in nodes, f"supersession {record['supersession_id']} references missing node: {old_id}")
            require(old_id != new_id, f"supersession {record['supersession_id']} contains a self edge")
            require(old_id not in superseded_once, f"superseded node {old_id} has multiple active replacements")
            require(nodes[old_id]["disposition"] == "superseded", f"superseded node {old_id} must have disposition superseded")
            require(_target_signature(nodes[old_id]) == _target_signature(nodes[new_id]), f"supersession {record['supersession_id']} changes node kind or mechanism target")
            superseded_once[old_id] = new_id
    declared_superseded = {node_id for node_id, node in nodes.items() if node["disposition"] == "superseded"}
    require(declared_superseded == set(superseded_once), "every superseded node must appear exactly once in supersessions")
    terminal_by_node: dict[str, str] = {}
    for node_id in sorted(declared_superseded):
        current = node_id
        path: list[str] = []
        in_path: set[str] = set()
        while current in superseded_once and current not in terminal_by_node:
            require(current not in in_path, "calculation DAG contains a supersession cycle")
            in_path.add(current)
            path.append(current)
            current = superseded_once[current]
        terminal = terminal_by_node.get(current, current)
        require(nodes[terminal]["disposition"] in {"planned", "retained"}, f"supersession chain for {node_id} does not terminate at an active node")
        for historical_node_id in path:
            terminal_by_node[historical_node_id] = terminal
    return _topological_order(nodes)


def _validate_target(
    node: dict[str, Any],
    states: dict[str, dict[str, Any]],
    edges: dict[str, dict[str, Any]],
    networks: dict[str, dict[str, Any]],
    basins: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    node_id = node["node_id"]
    kind = node["node_kind"]
    target = node["target"]
    require(target["network_ids"], f"node {node_id} must reference at least one mechanism network")
    require(target["reference_basin_ids"], f"node {node_id} must reference at least one reference basin")
    for state_id in target["state_ids"]:
        require(state_id in states, f"node {node_id} references unknown mechanism state: {state_id}")
    for edge_id in target["edge_ids"]:
        require(edge_id in edges, f"node {node_id} references unknown mechanism edge: {edge_id}")
    for network_id in target["network_ids"]:
        require(network_id in networks, f"node {node_id} references unknown mechanism network: {network_id}")
    for basin_id in target["reference_basin_ids"]:
        require(basin_id in basins, f"node {node_id} references unknown reference basin: {basin_id}")
    require(target["state_ids"] or target["edge_ids"], f"node {node_id} has no mechanism state or edge target")

    if kind in STRUCTURAL_KINDS:
        require(len(target["state_ids"]) == 1 and not target["edge_ids"], f"{kind} node {node_id} must target exactly one state and no edge")
    elif kind in PATH_KINDS:
        require(len(target["edge_ids"]) == 1, f"{kind} node {node_id} must target exactly one mechanism edge")
        edge = edges[target["edge_ids"][0]]
        endpoints = {edge["from_state_id"], edge["to_state_id"]}
        if kind == "endpoint":
            require(len(target["state_ids"]) == 1 and set(target["state_ids"]).issubset(endpoints), f"endpoint node {node_id} must identify exactly one endpoint state")
        else:
            require(set(target["state_ids"]).issubset(endpoints), f"{kind} node {node_id} state refs must be edge endpoints")
    elif kind == "single_point":
        require(
            (len(target["state_ids"]) == 1 and not target["edge_ids"])
            or (not target["state_ids"] and len(target["edge_ids"]) == 1),
            f"single_point node {node_id} must target exactly one state or exactly one edge",
        )

    for network_id in target["network_ids"]:
        network = networks[network_id]
        require(set(target["state_ids"]).issubset(network["state_ids"]), f"node {node_id} state references mismatch network {network_id}")
        require(set(target["edge_ids"]).issubset(network["edge_ids"]), f"node {node_id} edge references mismatch network {network_id}")
    for basin_id in target["reference_basin_ids"]:
        basin = basins[basin_id]
        require(set(target["network_ids"]).issubset(basin["network_ids"]), f"node {node_id} network refs mismatch reference basin {basin_id}")
        require(set(target["edge_ids"]).issubset(basin["edge_ids"]), f"node {node_id} edge refs mismatch reference basin {basin_id}")

    allowed_atom_ref_states = set(target["state_ids"])
    for edge_id in target["edge_ids"]:
        allowed_atom_ref_states.update({edges[edge_id]["from_state_id"], edges[edge_id]["to_state_id"]})
    for atom_ref in target["atom_refs"]:
        state_id = atom_ref["state_id"]
        require(state_id in allowed_atom_ref_states, f"node {node_id} atom ref state is absent from its target states or edge endpoints: {state_id}")
        atom_ids = {item["atom_id"] for item in states[state_id]["atoms"]}
        require(atom_ref["atom_id"] in atom_ids, f"node {node_id} references unknown atom {atom_ref['atom_id']} in {state_id}")

    candidate_states: list[dict[str, Any]] = []
    if len(target["state_ids"]) == 1 and not target["edge_ids"]:
        candidate_states = [states[target["state_ids"][0]]]
    elif kind == "endpoint":
        candidate_states = [states[target["state_ids"][0]]]
    elif target["edge_ids"]:
        edge = edges[target["edge_ids"][0]]
        candidate_states = [states[edge["from_state_id"]], states[edge["to_state_id"]]]
    blockers: list[dict[str, Any]] = []
    if kind in GEOMETRY_KINDS:
        chemical = node["chemical_state"]
        charges = {item["formal_charge"] for item in candidate_states}
        multiplicities = {item["multiplicity"] for item in candidate_states}
        if chemical["formal_charge"] is None:
            blockers.append(_blocker(_derived_id(node_id, "charge_missing"), node_id, "Exact formal charge is required before this stage can enter input review.", ("scientific_readiness", "input_review")))
        else:
            require(chemical["formal_charge"] in charges and len(charges) == 1, f"node {node_id} formal charge mismatches its mechanism target")
        if chemical["multiplicity"] is None:
            blockers.append(_blocker(_derived_id(node_id, "multiplicity_missing"), node_id, "Exact multiplicity is required before this stage can enter input review.", ("scientific_readiness", "input_review")))
        elif len(multiplicities) == 1:
            require(chemical["multiplicity"] in multiplicities, f"node {node_id} multiplicity mismatches its mechanism target")
        else:
            require(chemical["multiplicity"] in multiplicities, f"node {node_id} multiplicity is absent from its mechanism endpoints")
            blockers.append(_blocker(_derived_id(node_id, "spin_surface_review"), node_id, "Mechanism endpoints have different multiplicities; a separate reviewed spin-surface model is required.", ("scientific_readiness", "input_review")))
        atom_order = chemical["atom_order"]
        if atom_order is None:
            blockers.append(_blocker(_derived_id(node_id, "atom_order_missing"), node_id, "A complete explicit atom order is required before this stage can enter input review.", ("scientific_readiness", "input_review")))
        else:
            order_states = {item["state_id"] for item in atom_order}
            require(len(order_states) == 1, f"node {node_id} atom_order must use one complete mechanism state")
            order_state_id = next(iter(order_states))
            allowed_ids = {item["state_id"] for item in candidate_states}
            require(order_state_id in allowed_ids, f"node {node_id} atom_order state mismatches its mechanism target")
            expected = {item["atom_id"] for item in states[order_state_id]["atoms"]}
            actual = [item["atom_id"] for item in atom_order]
            require(len(actual) == len(expected) and set(actual) == expected, f"node {node_id} atom_order must cover every target atom exactly once")
    else:
        chemical = node["chemical_state"]
        require(chemical == {"formal_charge": None, "multiplicity": None, "atom_order": None}, f"node {node_id} chemical_state must be null-valued for {kind}")
    return candidate_states, blockers


def _target_state_footprint(node: dict[str, Any], edges: dict[str, dict[str, Any]]) -> set[str]:
    target = node["target"]
    result = set(target["state_ids"])
    if node["node_kind"] == "endpoint":
        return result
    for edge_id in target["edge_ids"]:
        edge = edges[edge_id]
        result.update((edge["from_state_id"], edge["to_state_id"]))
    return result


def _validate_dependency_target_continuity(
    nodes: dict[str, dict[str, Any]],
    edges: dict[str, dict[str, Any]],
) -> None:
    for node_id, node in nodes.items():
        target = node["target"]
        for dependency in node["depends_on"]:
            source_target = nodes[dependency]["target"]
            require(
                set(source_target["network_ids"]) == set(target["network_ids"]),
                f"dependency target network mismatch between {dependency} and {node_id}",
            )
            require(
                set(source_target["reference_basin_ids"]) == set(target["reference_basin_ids"]),
                f"dependency target reference-basin mismatch between {dependency} and {node_id}",
            )
            source_edges = set(source_target["edge_ids"])
            target_edges = set(target["edge_ids"])
            if source_edges and target_edges:
                require(source_edges == target_edges, f"dependency target edge mismatch between {dependency} and {node_id}")
            source_states = _target_state_footprint(nodes[dependency], edges)
            target_states = _target_state_footprint(node, edges)
            require(
                bool(source_states.intersection(target_states)),
                f"dependency target state continuity is absent between {dependency} and {node_id}",
            )


def _assemble_nodes(
    review: dict[str, Any],
    mechanism_artifact: dict[str, Any],
    support_state: str,
    precedent_eligible_edges: set[str] | None,
    upstream_blockers: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str], dict[str, Any], list[dict[str, Any]]]:
    reviewed_nodes = _index_by(review["nodes"], "node_id", "node")
    alternatives = review["alternative_groups"]
    supersessions = review["supersessions"]
    order = _validate_graph_relations(reviewed_nodes, alternatives, supersessions)
    states = _index_by(mechanism_artifact["states"], "state_id", "mechanism state")
    edges = _index_by(mechanism_artifact["edges"], "edge_id", "mechanism edge")
    networks = _index_by(mechanism_artifact["networks"], "network_id", "mechanism network")
    basins = _index_by(mechanism_artifact["reference_basins"], "basin_id", "reference basin")
    alternative_index = _index_by(alternatives, "group_id", "alternative group")

    global_blockers = list(upstream_blockers)
    require(support_state in {"missing", "not_promotable", "reviewed"}, "invalid mechanism-support integration state")
    if support_state == "missing":
        support_blocker_id = "mechanism_support_missing"
        global_blockers.append(_blocker(
            support_blocker_id,
            "study",
            f"Required {SUPPORT_SCHEMA} is not bound; mechanism hypotheses cannot become calculation-ready.",
            ("scientific_readiness", "calculation_dag"),
        ))
    elif support_state == "not_promotable":
        support_blocker_id = "mechanism_support_not_promotable"
        require(any(item["blocker_id"] == support_blocker_id for item in global_blockers), "non-promotable mechanism support lacks its normalized plan blocker")
    else:
        support_blocker_id = "mechanism_support_channel_mapping_missing"
        global_blockers.append(_blocker(
            support_blocker_id,
            "study",
            f"Bound {SUPPORT_SCHEMA} passed its owner validator and acceptable gate checks, but this DAG review has no explicit reviewed edge-plus-stereochemical-channel mapping; edge-only targets cannot promote readiness.",
            ("scientific_readiness", "calculation_dag"),
        ))
    active_edge_ids = {
        edge_id
        for node in reviewed_nodes.values()
        if node["disposition"] in {"planned", "retained"}
        for edge_id in node["target"]["edge_ids"]
    }
    uncovered_precedent_edges = (
        active_edge_ids
        if precedent_eligible_edges is None
        else active_edge_ids - precedent_eligible_edges
    )
    precedent_blocker_id: str | None = None
    if precedent_eligible_edges is None:
        precedent_blocker_id = "ts_precedent_map_missing"
        global_blockers.append(_blocker(
            precedent_blocker_id,
            "study",
            f"Required {PRECEDENT_SCHEMA} is not bound; every edge-targeted node remains blocked.",
            ("edge_targeted_nodes", "scientific_readiness"),
        ))
    elif uncovered_precedent_edges:
        precedent_blocker_id = "ts_precedent_coverage_incomplete"
        global_blockers.append(_blocker(
            precedent_blocker_id,
            "study",
            "The validated TS-precedent map has no locally accepted, promotion-complete record for active mechanism edges: "
            + ", ".join(sorted(uncovered_precedent_edges))
            + ".",
            ("edge_targeted_nodes", "scientific_readiness"),
        ))
    review_blocker_id: str | None = None
    if review["review_decision"] == "blocked":
        review_blocker_id = "calculation_plan_review_blocked"
        global_blockers.append(_blocker(review_blocker_id, "study", "The human calculation-plan review is explicitly blocked.", ("scientific_readiness", "input_review")))
    elif review["review_decision"] == "accepted_with_blockers":
        review_blocker_id = "calculation_plan_review_has_blockers"
        global_blockers.append(_blocker(review_blocker_id, "study", "The human calculation-plan review remains accepted only with unresolved blockers.", ("scientific_readiness", "input_review")))
    global_blockers.append(_blocker("offline_no_live_authority", "study", "This offline planning slice cannot grant live approval or execution authority.", ("live_approval", "execution")))

    node_specific: dict[str, list[dict[str, Any]]] = {}
    for node_id in order:
        node = reviewed_nodes[node_id]
        _, target_blockers = _validate_target(node, states, edges, networks, basins)
        blockers = list(target_blockers) + node["review_blockers"]
        for input_slot in node["inputs"]:
            if input_slot["required"] and input_slot["source_node_id"] is None:
                blockers.append(_blocker(
                    _derived_id(node_id, f"required_{input_slot['slot_id']}_unbound"),
                    node_id,
                    f"Required input slot {input_slot['slot_id']} has no exact source node or producer.",
                    ("scientific_readiness", "input_review"),
                ))
        alternative_group_id = node["alternative_group_id"]
        if alternative_group_id is not None and alternative_index[alternative_group_id]["review_status"] == "blocked":
            blockers.append(_blocker(_derived_id(node_id, "alternative_review_blocked"), node_id, f"Alternative group {alternative_group_id} remains blocked by review.", ("scientific_readiness", "input_review")))
        for state_id in node["target"]["state_ids"]:
            state = states[state_id]
            if state["review_status"] == "blocked" or state["blockers"]:
                blockers.append(_blocker(_derived_id(node_id, f"state_{state_id}_blocked"), node_id, f"Referenced mechanism state {state_id} remains blocked.", ("scientific_readiness",)))
        for edge_id in node["target"]["edge_ids"]:
            edge = edges[edge_id]
            if edge["review_status"] == "blocked" or edge["blockers"]:
                blockers.append(_blocker(_derived_id(node_id, f"edge_{edge_id}_blocked"), node_id, f"Referenced mechanism edge {edge_id} remains blocked.", ("scientific_readiness",)))
        for network_id in node["target"]["network_ids"]:
            network = networks[network_id]
            if network["review_status"] == "blocked" or network["blockers"]:
                blockers.append(_blocker(_derived_id(node_id, f"network_{network_id}_blocked"), node_id, f"Referenced mechanism network {network_id} remains blocked.", ("scientific_readiness",)))
        for basin_id in node["target"]["reference_basin_ids"]:
            basin = basins[basin_id]
            if basin["review_status"] == "blocked" or basin["blockers"]:
                blockers.append(_blocker(_derived_id(node_id, f"basin_{basin_id}_blocked"), node_id, f"Referenced reference basin {basin_id} remains blocked.", ("scientific_readiness",)))
        node_specific[node_id] = blockers

    _validate_dependency_target_continuity(reviewed_nodes, edges)

    assembled: dict[str, dict[str, Any]] = {}
    all_blockers = list(global_blockers)
    study_scientific_ids = [item["blocker_id"] for item in upstream_blockers]
    if support_blocker_id not in study_scientific_ids:
        study_scientific_ids.append(support_blocker_id)
    if review_blocker_id is not None:
        study_scientific_ids.append(review_blocker_id)
    for node_id in order:
        source = reviewed_nodes[node_id]
        inactive = source["disposition"] in {"skipped", "superseded"}
        scientific_ids: list[str] = []
        if not inactive:
            scientific_ids.extend(study_scientific_ids)
            if precedent_blocker_id is not None and set(source["target"]["edge_ids"]).intersection(uncovered_precedent_edges):
                scientific_ids.append(precedent_blocker_id)
            scientific_ids.extend(item["blocker_id"] for item in node_specific[node_id])
            blocked_dependencies = [dependency for dependency in source["depends_on"] if assembled[dependency]["readiness"]["scientific"]["status"] != "ready"]
            if blocked_dependencies:
                dependency_blocker = _blocker(_derived_id(node_id, "dependency_blocked"), node_id, "One or more predecessor nodes are not scientifically ready: " + ", ".join(sorted(blocked_dependencies)), ("scientific_readiness", "input_review"))
                node_specific[node_id].append(dependency_blocker)
                scientific_ids.append(dependency_blocker["blocker_id"])
        scientific_ids = sorted(set(scientific_ids))
        if inactive:
            scientific_status = "not_applicable"
            input_status = "not_applicable"
            live_status = "not_applicable"
            input_ids: list[str] = []
            live_ids: list[str] = []
        else:
            scientific_status = "blocked" if scientific_ids else "ready"
            input_status = "blocked" if scientific_ids else "ready_for_review"
            live_status = "not_ready"
            input_ids = list(scientific_ids)
            live_ids = ["offline_no_live_authority"]
        result = copy.deepcopy(source)
        result["readiness"] = {
            "scientific": {"status": scientific_status, "blocker_ids": scientific_ids},
            "input_review": {"status": input_status, "blocker_ids": input_ids},
            "live_approval": {"status": live_status, "blocker_ids": live_ids},
        }
        result["executable"] = False
        assembled[node_id] = result
        if not inactive:
            all_blockers.extend(node_specific[node_id])

    kind_counts = {kind: 0 for kind in NODE_KINDS}
    state_ids: set[str] = set()
    edge_ids: set[str] = set()
    network_ids: set[str] = set()
    basin_ids: set[str] = set()
    active_ids: list[str] = []
    historical_ids: list[str] = []
    for node_id in sorted(assembled):
        node = assembled[node_id]
        kind_counts[node["node_kind"]] += 1
        state_ids.update(node["target"]["state_ids"])
        edge_ids.update(node["target"]["edge_ids"])
        network_ids.update(node["target"]["network_ids"])
        basin_ids.update(node["target"]["reference_basin_ids"])
        historical = (
            node["disposition"] in {"skipped", "superseded"}
            or node["execution_state"] in {"failed", "cancelled"}
            or node["evidence_acceptance"] in {"rejected", "inconclusive"}
        )
        (historical_ids if historical else active_ids).append(node_id)
    coverage = {
        "node_count": len(assembled),
        "kind_counts": kind_counts,
        "state_ids": sorted(state_ids),
        "edge_ids": sorted(edge_ids),
        "network_ids": sorted(network_ids),
        "reference_basin_ids": sorted(basin_ids),
        "active_node_ids": active_ids,
        "historical_node_ids": historical_ids,
    }
    if not active_ids:
        all_blockers.append(_blocker(
            "no_active_calculation_nodes",
            "study",
            "The reviewed plan contains no active calculation node; no input-review progression exists.",
            ("calculation_dag", "input_review"),
        ))
    return [assembled[node_id] for node_id in sorted(assembled)], order, coverage, _sort_blockers(all_blockers)


def _check_study_and_safety(artifact: dict[str, Any], study_id: str, label: str) -> None:
    require(artifact.get("study_id") == study_id, f"{label} study_id mismatch")
    require(artifact.get("calculation_ready") is False, f"{label} must retain calculation_ready: false")
    require(artifact.get("no_submission_authorization") is True, f"{label} must retain no_submission_authorization: true")


def _normalized_upstream_gate_blockers(label: str, artifact: dict[str, Any]) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    raw_blockers = artifact.get("blockers", [])
    require(isinstance(raw_blockers, list), f"upstream {label} blockers must be an array")
    for index, raw in enumerate(raw_blockers):
        normalized = _normalize_blocker(raw, f"upstream {label}.blockers[{index}]")
        blockers.append(_blocker(
            _derived_id(f"upstream_{label}", normalized["blocker_id"]),
            label,
            f"Upstream {label} remains unresolved: {normalized['description']}",
            tuple(normalized["required_for"]) + ("scientific_readiness", "calculation_dag"),
        ))
    if artifact.get("gate_status") in {"reviewed_with_blockers", "blocked"} and not raw_blockers:
        blockers.append(_blocker(
            _derived_id(f"upstream_{label}", "gate_unresolved"),
            label,
            f"Upstream {label} gate is {artifact.get('gate_status')} without a promotable acceptance record.",
            ("scientific_readiness", "calculation_dag"),
        ))
    return blockers


def _upstream_gate_blockers(artifacts: list[tuple[str, dict[str, Any]]]) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    for label, artifact in artifacts:
        blockers.extend(_normalized_upstream_gate_blockers(label, artifact))
    return blockers


def _require_reference_matches_binding(reference: Any, binding: dict[str, Any], label: str) -> None:
    require(isinstance(reference, dict), f"{label} reference is missing")
    require(reference.get("sha256") == binding["sha256"], f"{label} file SHA-256 does not match the selected immutable artifact")
    require(reference.get("payload_sha256") == binding["payload_sha256"], f"{label} payload SHA-256 does not match the selected immutable artifact")


def _assemble_plan(
    *,
    review: dict[str, Any],
    intake: dict[str, Any],
    registry: dict[str, Any],
    condition: dict[str, Any],
    mechanism_artifact: dict[str, Any],
    intake_binding: dict[str, Any],
    registry_binding: dict[str, Any],
    condition_binding: dict[str, Any],
    mechanism_binding: dict[str, Any],
    support_binding: dict[str, Any] | None,
    support_promotable: bool | None,
    support_gate_blockers: list[dict[str, Any]],
    precedent_binding: dict[str, Any] | None,
    precedent_eligible_edges: set[str] | None,
    review_binding: dict[str, Any],
    superseded_bindings: list[dict[str, Any]],
) -> dict[str, Any]:
    study_id = review["study_id"]
    for label, artifact in (
        ("reaction intake", intake),
        ("species registry", registry),
        ("condition model", condition),
        ("mechanism network", mechanism_artifact),
    ):
        _check_study_and_safety(artifact, study_id, label)
    require(review["intake_payload_sha256"] == intake["payload_sha256"], "review intake payload hash mismatch")
    require(review["species_registry_payload_sha256"] == registry["payload_sha256"], "review species-registry payload hash mismatch")
    require(review["condition_model_payload_sha256"] == condition["payload_sha256"], "review condition-model payload hash mismatch")
    require(review["mechanism_network_payload_sha256"] == mechanism_artifact["payload_sha256"], "review mechanism-network payload hash mismatch")
    _require_reference_matches_binding(registry.get("intake"), intake_binding, "species-registry intake")
    _require_reference_matches_binding(condition.get("intake"), intake_binding, "condition-model intake")
    _require_reference_matches_binding(condition.get("species_registry"), registry_binding, "condition-model species registry")
    _require_reference_matches_binding(mechanism_artifact.get("intake"), intake_binding, "mechanism-network intake")
    _require_reference_matches_binding(mechanism_artifact.get("species_registry"), registry_binding, "mechanism-network species registry")
    _require_reference_matches_binding(mechanism_artifact.get("condition_model"), condition_binding, "mechanism-network condition model")
    support_hash = None if support_binding is None else support_binding["payload_sha256"]
    precedent_hash = None if precedent_binding is None else precedent_binding["payload_sha256"]
    require(
        (precedent_binding is None) == (precedent_eligible_edges is None),
        "TS-precedent binding and validated eligibility assessment must be supplied together",
    )
    require(review["mechanism_support_payload_sha256"] == support_hash, "review mechanism-support payload hash mismatch")
    require(review["ts_precedent_map_payload_sha256"] == precedent_hash, "review TS-precedent payload hash mismatch")
    require(review["superseded_plan_payload_sha256s"] == sorted(item["payload_sha256"] for item in superseded_bindings), "review superseded-plan hash set mismatch")
    require((support_binding is None) == (support_promotable is None), "mechanism-support binding and owner gate assessment must be supplied together")
    require(not support_gate_blockers or support_binding is not None, "mechanism-support gate blockers require a bound artifact")

    upstream_blockers = _upstream_gate_blockers([
        ("reaction_intake", intake),
        ("species_registry", registry),
        ("condition_model", condition),
        ("mechanism_network", mechanism_artifact),
    ])
    upstream_blockers.extend(support_gate_blockers)
    if support_promotable is True:
        deferred_support_id = _derived_id("upstream_mechanism_network", "mechanism_support_unavailable")
        upstream_blockers = [item for item in upstream_blockers if item["blocker_id"] != deferred_support_id]
    nodes, order, coverage, blockers = _assemble_nodes(
        review,
        mechanism_artifact,
        "missing" if support_binding is None else ("reviewed" if support_promotable else "not_promotable"),
        precedent_eligible_edges,
        upstream_blockers,
    )
    gate_status = "blocked" if review["review_decision"] == "blocked" else ("reviewed_with_blockers" if blockers else "reviewed")
    return finalize({
        "schema": PLAN_SCHEMA,
        "study_id": study_id,
        "plan_id": review["plan_id"],
        "intake": intake_binding,
        "species_registry": registry_binding,
        "condition_model": condition_binding,
        "mechanism_network": mechanism_binding,
        "mechanism_support": support_binding,
        "ts_precedent_map": precedent_binding,
        "review_source": review_binding,
        "superseded_plans": sorted(superseded_bindings, key=lambda item: item["payload_sha256"]),
        "nodes": nodes,
        "alternative_groups": review["alternative_groups"],
        "supersessions": review["supersessions"],
        "topological_order": order,
        "coverage": coverage,
        "blockers": blockers,
        "review": {"decision": review["review_decision"], "notes": review["review_notes"]},
        "gate_status": gate_status,
        "calculation_ready": False,
        "no_submission_authorization": True,
    })


def _validated_upstream(path: Path, validator: Any, label: str) -> None:
    try:
        validator(path)
    except (rw.OfflineError, ValueError, OSError, AssertionError) as exc:
        raise ContractError(f"{label} validation failed: {exc}") from exc


def _require_exact_selected_parents(
    artifact: dict[str, Any],
    artifact_path: Path,
    selected_parents: tuple[tuple[str, Path, dict[str, Any]], ...],
    label: str,
) -> None:
    for field, selected_path, binding in selected_parents:
        reference = artifact.get(field)
        _require_reference_matches_binding(reference, binding, f"{label} {field}")
        require(reference.get("size_bytes") == binding["size_bytes"], f"{label} {field} byte size does not match the selected immutable artifact")
        reference_path = Path(_string(reference.get("path"), f"{label} {field}.path"))
        candidate = reference_path if reference_path.is_absolute() else artifact_path.parent / reference_path
        _reject_absolute_symlink_chain(candidate, f"{label} {field}")
        require(
            candidate.resolve() == selected_path.resolve(),
            f"{label} {field} does not reference the exact selected artifact path",
        )


def _validate_mechanism_support(
    artifact: dict[str, Any],
    artifact_path: Path,
    study_id: str,
    selected_parents: tuple[tuple[str, Path, dict[str, Any]], ...],
) -> bool:
    """Validate origin/main evidence-gate /1 without edge-level promotion.

    The owner contract is scoped by both mechanism edge and stereochemical
    channel.  Calculation-plan review /1 has only edge IDs, so this bridge may
    authenticate the artifact and its exact parents but must retain a channel-
    mapping blocker until a later reviewed contract supplies that dimension.
    """

    _validated_upstream(artifact_path, mechanism_support.validate, "mechanism support")
    _check_study_and_safety(artifact, study_id, "mechanism support")
    require(artifact.get("mechanism_claim_validation_present") is False, "mechanism support cannot validate a mechanism claim")
    _require_exact_selected_parents(artifact, artifact_path, selected_parents, "mechanism-support")
    review = artifact.get("review")
    blockers = artifact.get("blockers")
    require(isinstance(review, dict), "mechanism-support review summary is missing")
    require(isinstance(blockers, list), "mechanism-support blockers must be an array")
    return (
        review.get("decision") == "accepted"
        and artifact.get("gate_status") == "reviewed"
        and not blockers
    )


def _mechanism_support_gate_blockers(
    artifact: dict[str, Any], promotable: bool,
) -> list[dict[str, Any]]:
    if promotable:
        return []
    records = _normalized_upstream_gate_blockers("mechanism_support", artifact)
    review = artifact.get("review", {})
    records.append(_blocker(
        "mechanism_support_not_promotable",
        "mechanism_support",
        "The exact owner-validated mechanism-support artifact is not promotable: "
        f"review decision={review.get('decision')!s}, gate_status={artifact.get('gate_status')!s}. "
        "Resolve its owner blockers before adding a DAG edge/channel mapping.",
        ("mechanism_support", "scientific_readiness", "calculation_dag"),
    ))
    return _sort_blockers(records)


def _validated_ts_precedent_edges(
    artifact: dict[str, Any],
    artifact_path: Path,
    study_id: str,
    selected_parents: tuple[tuple[str, Path, dict[str, Any]], ...],
) -> set[str]:
    """Return only owner-validated, locally accepted edge coverage.

    This assessment clears only the separate TS-precedent-availability blocker
    for an exactly matching owner-eligible edge.  It cannot clear the DAG's
    missing edge-plus-channel mapping, make a node executable, or grant live
    authority.
    """

    _validated_upstream(artifact_path, ts_precedent.validate, "TS precedent map")
    _check_study_and_safety(artifact, study_id, "TS precedent map")
    _require_exact_selected_parents(artifact, artifact_path, selected_parents, "TS-precedent")

    review = artifact.get("review")
    require(isinstance(review, dict), "TS-precedent review summary is missing")
    if review.get("decision") != "accepted":
        return set()
    records = artifact.get("records")
    de_novo = artifact.get("de_novo_seed_plans")
    require(isinstance(records, list), "TS-precedent records must be an array")
    require(isinstance(de_novo, list), "TS-precedent de_novo_seed_plans must be an array")
    eligible: set[str] = set()
    for record in [*records, *de_novo]:
        require(isinstance(record, dict), "TS-precedent record must be an object")
        disposition = record.get("disposition")
        target = record.get("target")
        if not isinstance(disposition, dict) or not isinstance(target, dict):
            continue
        if disposition.get("status") != "accepted_for_candidate_construction":
            continue
        require(record.get("promotion_requirements_complete") is True, "accepted TS-precedent record lacks complete local promotion requirements")
        require(record.get("candidate_construction_gate") == "candidate_construction_eligible", "accepted TS-precedent record has an unexpected owner gate")
        eligible.add(_identifier(target.get("edge_id"), "accepted TS-precedent edge_id"))
    return eligible


def build_plan(
    intake_path: Path,
    registry_path: Path,
    condition_path: Path,
    mechanism_path: Path,
    review_path: Path,
    output: Path,
    support_path: Path | None,
    precedent_path: Path | None,
    superseded_paths: list[Path],
) -> dict[str, Any]:
    root = output.parent.absolute()
    require(root.exists() and root.is_dir(), "output artifact root must already exist")
    _validated_upstream(intake_path, rw.validate_artifact, "reaction intake")
    _validated_upstream(registry_path, rw.validate_artifact, "species registry")
    _validated_upstream(condition_path, rw.validate_artifact, "condition model")
    _validated_upstream(mechanism_path, mechanism.validate, "mechanism network")
    intake, intake_binding = _binding_from_path(intake_path, root, rw.INTAKE_SCHEMA, "reaction intake")
    registry, registry_binding = _binding_from_path(registry_path, root, rw.REGISTRY_SCHEMA, "species registry")
    condition, condition_binding = _binding_from_path(condition_path, root, rw.CONDITION_SCHEMA, "condition model")
    mechanism_artifact, mechanism_binding = _binding_from_path(mechanism_path, root, mechanism.OUTPUT_SCHEMA, "mechanism network")
    review, review_binding = _binding_from_path(review_path, root, REVIEW_SCHEMA, "calculation-plan review source")
    review = normalize_review(review, require_hash=True)
    support_binding = None
    support = None
    support_promotable = None
    support_gate_blockers: list[dict[str, Any]] = []
    if support_path is not None:
        support, support_binding = _binding_from_path(support_path, root, SUPPORT_SCHEMA, "mechanism support")
        support_promotable = _validate_mechanism_support(
            support,
            support_path,
            review["study_id"],
            (
                ("reaction_intake", intake_path, intake_binding),
                ("species_registry", registry_path, registry_binding),
                ("condition_model", condition_path, condition_binding),
                ("mechanism_network", mechanism_path, mechanism_binding),
            ),
        )
        support_gate_blockers = _mechanism_support_gate_blockers(support, support_promotable)
    precedent_binding = None
    precedent_eligible_edges = None
    if precedent_path is not None:
        require(support_path is not None and support_binding is not None and support is not None, "TS precedent map requires the exact selected mechanism-support artifact")
        precedent, precedent_binding = _binding_from_path(precedent_path, root, PRECEDENT_SCHEMA, "TS precedent map")
        precedent_eligible_edges = _validated_ts_precedent_edges(
            precedent,
            precedent_path,
            review["study_id"],
            (
                ("reaction_intake", intake_path, intake_binding),
                ("species_registry", registry_path, registry_binding),
                ("condition_model", condition_path, condition_binding),
                ("mechanism_network", mechanism_path, mechanism_binding),
                ("mechanism_support", support_path, support_binding),
            ),
        )
    superseded_bindings: list[dict[str, Any]] = []
    for index, path in enumerate(superseded_paths):
        old, binding = _binding_from_path(path, root, PLAN_SCHEMA, f"superseded plan {index}")
        # Reserve the not-yet-written output as the first ancestry frame so a
        # builder cannot create a plan that its validator would immediately
        # reject at the documented depth boundary.
        _validate_plan_internal(path, {output.absolute()})
        require(old["study_id"] == review["study_id"] and old["plan_id"] == review["plan_id"], "superseded plan must preserve study_id and plan_id")
        superseded_bindings.append(binding)
    require(len({item["payload_sha256"] for item in superseded_bindings}) == len(superseded_bindings), "duplicate superseded plan bindings are forbidden")
    artifact = _assemble_plan(
        review=review,
        intake=intake,
        registry=registry,
        condition=condition,
        mechanism_artifact=mechanism_artifact,
        intake_binding=intake_binding,
        registry_binding=registry_binding,
        condition_binding=condition_binding,
        mechanism_binding=mechanism_binding,
        support_binding=support_binding,
        support_promotable=support_promotable,
        support_gate_blockers=support_gate_blockers,
        precedent_binding=precedent_binding,
        precedent_eligible_edges=precedent_eligible_edges,
        review_binding=review_binding,
        superseded_bindings=superseded_bindings,
    )
    write_json(output, artifact)
    return artifact


def _validate_plan_internal(path: Path, stack: set[Path]) -> tuple[dict[str, Any], dict[str, Any]]:
    require(
        len(stack) < MAX_SUPERSEDED_PLAN_DEPTH,
        f"calculation-plan supersession ancestry exceeds supported depth {MAX_SUPERSEDED_PLAN_DEPTH}",
    )
    absolute = path.absolute()
    require(absolute not in stack, "calculation-plan supersession chain contains a cycle")
    stack.add(absolute)
    try:
        artifact = load_json(path)
        _exact(artifact, PLAN_KEYS, "calculation-plan artifact")
        require(artifact["schema"] == PLAN_SCHEMA, "unrecognized calculation-plan artifact schema")
        validate_payload(artifact, "calculation-plan artifact")
        require(artifact["calculation_ready"] is False and artifact["no_submission_authorization"] is True, "calculation-plan artifact violates offline safety flags")
        intake, intake_path = _resolve_binding(artifact["intake"], path, rw.INTAKE_SCHEMA, "reaction intake")
        registry, registry_path = _resolve_binding(artifact["species_registry"], path, rw.REGISTRY_SCHEMA, "species registry")
        condition, condition_path = _resolve_binding(artifact["condition_model"], path, rw.CONDITION_SCHEMA, "condition model")
        mechanism_artifact, mechanism_path = _resolve_binding(artifact["mechanism_network"], path, mechanism.OUTPUT_SCHEMA, "mechanism network")
        _validated_upstream(intake_path, rw.validate_artifact, "reaction intake")
        _validated_upstream(registry_path, rw.validate_artifact, "species registry")
        _validated_upstream(condition_path, rw.validate_artifact, "condition model")
        _validated_upstream(mechanism_path, mechanism.validate, "mechanism network")
        review, _review_path = _resolve_binding(artifact["review_source"], path, REVIEW_SCHEMA, "calculation-plan review source")
        review = normalize_review(review, require_hash=True)
        support_binding = artifact["mechanism_support"]
        support_path: Path | None = None
        support: dict[str, Any] | None = None
        support_promotable: bool | None = None
        support_gate_blockers: list[dict[str, Any]] = []
        if support_binding is not None:
            support, support_path = _resolve_binding(support_binding, path, SUPPORT_SCHEMA, "mechanism support")
            support_promotable = _validate_mechanism_support(
                support,
                support_path,
                artifact["study_id"],
                (
                    ("reaction_intake", intake_path, artifact["intake"]),
                    ("species_registry", registry_path, artifact["species_registry"]),
                    ("condition_model", condition_path, artifact["condition_model"]),
                    ("mechanism_network", mechanism_path, artifact["mechanism_network"]),
                ),
            )
            support_gate_blockers = _mechanism_support_gate_blockers(support, support_promotable)
        precedent_binding = artifact["ts_precedent_map"]
        precedent_eligible_edges = None
        if precedent_binding is not None:
            require(support_binding is not None and support_path is not None, "TS precedent map requires the exact selected mechanism-support artifact")
            precedent, precedent_path = _resolve_binding(precedent_binding, path, PRECEDENT_SCHEMA, "TS precedent map")
            precedent_eligible_edges = _validated_ts_precedent_edges(
                precedent,
                precedent_path,
                artifact["study_id"],
                (
                    ("reaction_intake", intake_path, artifact["intake"]),
                    ("species_registry", registry_path, artifact["species_registry"]),
                    ("condition_model", condition_path, artifact["condition_model"]),
                    ("mechanism_network", mechanism_path, artifact["mechanism_network"]),
                    ("mechanism_support", support_path, support_binding),
                ),
            )
        require(isinstance(artifact["superseded_plans"], list), "superseded_plans must be an array")
        prior_bindings: list[dict[str, Any]] = []
        history_by_payload: dict[str, dict[str, Any]] = {}
        for index, binding in enumerate(artifact["superseded_plans"]):
            prior, prior_path = _resolve_binding(binding, path, PLAN_SCHEMA, f"superseded plan {index}")
            validated_prior, prior_chain = _validate_plan_internal(prior_path, stack)
            require(prior == validated_prior, f"superseded plan {index} changed during recursive validation")
            require(prior["study_id"] == artifact["study_id"] and prior["plan_id"] == artifact["plan_id"], "superseded plan must preserve study_id and plan_id")
            prior_bindings.append(binding)
            rebased_history = [binding]
            for ancestor_index, ancestor_binding in enumerate(prior_chain["superseded_plan_bindings"]):
                _ancestor, ancestor_path = _resolve_binding(
                    ancestor_binding,
                    prior_path,
                    PLAN_SCHEMA,
                    f"superseded plan {index} ancestor {ancestor_index}",
                )
                current_root = path.parent.absolute()
                try:
                    ancestor_relative = ancestor_path.relative_to(current_root.resolve())
                except ValueError:
                    raise ContractError(f"superseded plan {index} ancestor {ancestor_index} escapes artifact root") from None
                _ancestor, rebased_binding = _binding_from_path(
                    current_root / ancestor_relative,
                    current_root,
                    PLAN_SCHEMA,
                    f"superseded plan {index} ancestor {ancestor_index}",
                )
                rebased_history.append(rebased_binding)
            for historical_binding in rebased_history:
                digest = historical_binding["payload_sha256"]
                if digest in history_by_payload:
                    require(history_by_payload[digest] == historical_binding, f"conflicting exact bindings for superseded plan payload {digest}")
                history_by_payload[digest] = historical_binding
        expected = _assemble_plan(
            review=review,
            intake=intake,
            registry=registry,
            condition=condition,
            mechanism_artifact=mechanism_artifact,
            intake_binding=artifact["intake"],
            registry_binding=artifact["species_registry"],
            condition_binding=artifact["condition_model"],
            mechanism_binding=artifact["mechanism_network"],
            support_binding=support_binding,
            support_promotable=support_promotable,
            support_gate_blockers=support_gate_blockers,
            precedent_binding=precedent_binding,
            precedent_eligible_edges=precedent_eligible_edges,
            review_binding=artifact["review_source"],
            superseded_bindings=prior_bindings,
        )
        require(artifact == expected, "calculation-plan artifact differs from independent deterministic recomputation/reconstruction")
        return artifact, {
            "intake": intake,
            "registry": registry,
            "condition": condition,
            "mechanism": mechanism_artifact,
            "support": support,
            "superseded_plan_bindings": [history_by_payload[key] for key in sorted(history_by_payload)],
        }
    finally:
        stack.remove(absolute)


def validate_plan(path: Path) -> dict[str, Any]:
    artifact, _ = _validate_plan_internal(path, set())
    return {
        "schema": "gaussian-reaction-calculation-plan-validation/1",
        "artifact_schema": PLAN_SCHEMA,
        "study_id": artifact["study_id"],
        "plan_id": artifact["plan_id"],
        "gate_status": artifact["gate_status"],
        "node_count": artifact["coverage"]["node_count"],
        "blocker_count": len(artifact["blockers"]),
        "payload_sha256": artifact["payload_sha256"],
        "live_actions": False,
    }


def _derive_index(plan: dict[str, Any], plan_binding: dict[str, Any], chain: dict[str, Any]) -> dict[str, Any]:
    superseded_bindings = chain["superseded_plan_bindings"]
    artifacts: list[dict[str, Any]] = [
        {"role": "reaction_intake", "status": "current", "artifact": plan["intake"]},
        {"role": "species_registry", "status": "current", "artifact": plan["species_registry"]},
        {"role": "condition_model", "status": "current", "artifact": plan["condition_model"]},
        {"role": "mechanism_network", "status": "current", "artifact": plan["mechanism_network"]},
        {"role": "mechanism_support", "status": "missing" if plan["mechanism_support"] is None else "current", "artifact": plan["mechanism_support"]},
        {"role": "ts_precedent_map", "status": "missing" if plan["ts_precedent_map"] is None else "current", "artifact": plan["ts_precedent_map"]},
        {"role": "calculation_plan_review", "status": "current", "artifact": plan["review_source"]},
        {"role": "calculation_plan", "status": "current", "artifact": plan_binding},
    ]
    for binding in superseded_bindings:
        artifacts.append({"role": "calculation_plan", "status": "superseded", "artifact": binding})
    artifacts.sort(key=lambda item: (item["role"], item["status"], "" if item["artifact"] is None else item["artifact"]["payload_sha256"]))

    plan_blockers = {item["blocker_id"]: item for item in plan["blockers"]}
    stage_specs: list[tuple[str, str | None, str, list[str]]] = []

    def upstream_stage(stage_id: str, role: str, key: str, *, excluded_blocker_ids: set[str] | None = None) -> None:
        source = chain[key]
        records = _normalized_upstream_gate_blockers(stage_id, source)
        excluded = (excluded_blocker_ids or set()) if source["gate_status"] != "blocked" else set()
        records = [item for item in records if item["blocker_id"] not in excluded]
        for record in records:
            require(plan_blockers.get(record["blocker_id"]) == record, f"study-index stage blocker differs from normalized plan blocker: {record['blocker_id']}")
        if source["gate_status"] == "blocked":
            status = "blocked"
        else:
            status = "accepted_with_blockers" if records else "accepted"
        stage_specs.append((stage_id, role, status, [item["blocker_id"] for item in records]))

    upstream_stage("reaction_intake", "reaction_intake", "intake")
    upstream_stage("species_registry", "species_registry", "registry")
    upstream_stage("condition_model", "condition_model", "condition")
    deferred_support_id = _derived_id("upstream_mechanism_network", "mechanism_support_unavailable")
    upstream_stage(
        "mechanism_network",
        "mechanism_network",
        "mechanism",
        excluded_blocker_ids={deferred_support_id},
    )

    support_artifact = chain.get("support")
    if plan["mechanism_support"] is None:
        support_ids = ["mechanism_support_missing"]
        if deferred_support_id in plan_blockers:
            support_ids.append(deferred_support_id)
        stage_specs.append(("mechanism_support", "mechanism_support", "missing", support_ids))
    else:
        require(isinstance(support_artifact, dict), "bound mechanism support is absent from validated plan chain")
        support_promotable = (
            support_artifact.get("review", {}).get("decision") == "accepted"
            and support_artifact.get("gate_status") == "reviewed"
            and support_artifact.get("blockers") == []
        )
        if support_promotable:
            support_ids = ["mechanism_support_channel_mapping_missing"]
            support_status = "blocked"
        else:
            normalized_support = _mechanism_support_gate_blockers(support_artifact, False)
            for record in normalized_support:
                require(plan_blockers.get(record["blocker_id"]) == record, f"study-index mechanism-support blocker differs from normalized plan blocker: {record['blocker_id']}")
            support_ids = [item["blocker_id"] for item in normalized_support]
            if deferred_support_id in plan_blockers:
                support_ids.append(deferred_support_id)
            support_status = "blocked" if support_artifact.get("gate_status") == "blocked" else "accepted_with_blockers"
        stage_specs.append(("mechanism_support", "mechanism_support", support_status, sorted(set(support_ids))))
    if plan["ts_precedent_map"] is None:
        stage_specs.append(("ts_precedent_map", "ts_precedent_map", "missing", ["ts_precedent_map_missing"]))
    elif "ts_precedent_coverage_incomplete" in plan_blockers:
        stage_specs.append(("ts_precedent_map", "ts_precedent_map", "accepted_with_blockers", ["ts_precedent_coverage_incomplete"]))
    else:
        stage_specs.append(("ts_precedent_map", "ts_precedent_map", "accepted", []))
    non_live_blockers = [item["blocker_id"] for item in plan["blockers"] if item["blocker_id"] != "offline_no_live_authority"]
    plan_status = "blocked" if plan["review"]["decision"] == "blocked" else ("accepted_with_blockers" if non_live_blockers else "accepted")
    stage_specs.append(("calculation_plan", "calculation_plan", plan_status, non_live_blockers))
    active_nodes = [node for node in plan["nodes"] if node["node_id"] in plan["coverage"]["active_node_ids"]]
    input_ids = sorted({blocker for node in active_nodes for blocker in node["readiness"]["input_review"]["blocker_ids"]})
    input_status = "accepted" if active_nodes and not input_ids else "accepted_with_blockers"
    stage_specs.append(("input_review", None, input_status, input_ids))
    stage_specs.append(("live_approval", None, "blocked", ["offline_no_live_authority"]))
    for stage_id, _role, _status, blocker_ids in stage_specs:
        for blocker_id in blocker_ids:
            require(blocker_id in plan_blockers, f"study-index stage {stage_id} references blocker absent from calculation plan: {blocker_id}")

    stages: list[dict[str, Any]] = []
    progression_open = True
    last_accepted: str | None = None
    next_ids: list[str] = []
    for stage_id, role, raw_status, blocker_ids in stage_specs:
        status = raw_status if progression_open else "not_reached"
        ids = sorted(set(blocker_ids)) if progression_open else []
        stages.append({"stage_id": stage_id, "status": status, "artifact_role": role, "blocker_ids": ids})
        if progression_open and status == "accepted":
            last_accepted = stage_id
        elif progression_open:
            progression_open = False
            next_ids = ids

    next_blockers = _sort_blockers(plan_blockers[blocker_id] for blocker_id in next_ids)
    if "mechanism_support_not_promotable" in next_ids:
        next_action = "review_mechanism_support_owner_blockers"
    elif "mechanism_support_channel_mapping_missing" in next_ids:
        next_action = "add_reviewed_edge_channel_mapping"
    elif "mechanism_support_missing" in next_ids or "mechanism_support_unavailable" in next_ids:
        next_action = "bind_reviewed_mechanism_support"
    elif "ts_precedent_validation_unavailable" in next_ids:
        next_action = "await_ts_precedent_owner_validator"
    elif "ts_precedent_map_missing" in next_ids:
        next_action = "bind_reviewed_ts_precedent_map"
    elif next_ids == ["offline_no_live_authority"]:
        next_action = "stop_offline_no_live_authority"
    elif next_ids:
        next_action = "review_current_stage_blockers"
    else:
        next_action = "no_safe_progression_recorded"

    resume: list[dict[str, Any]] = []
    for node in sorted(plan["nodes"], key=lambda item: item["node_id"]):
        readiness = node["readiness"]
        next_node_ids = sorted(set(readiness["scientific"]["blocker_ids"] + readiness["input_review"]["blocker_ids"] + readiness["live_approval"]["blocker_ids"]))
        resume.append({
            "locator": {"study_id": plan["study_id"], "plan_id": plan["plan_id"], "node_id": node["node_id"]},
            "node_kind": node["node_kind"],
            "disposition": node["disposition"],
            "scientific_readiness": readiness["scientific"]["status"],
            "input_review_readiness": readiness["input_review"]["status"],
            "live_approval_readiness": readiness["live_approval"]["status"],
            "execution_state": node["execution_state"],
            "evidence_acceptance": node["evidence_acceptance"],
            "next_blocker_ids": next_node_ids,
        })
    return finalize({
        "schema": INDEX_SCHEMA,
        "study_id": plan["study_id"],
        "plan_id": plan["plan_id"],
        "calculation_plan": plan_binding,
        "artifacts": artifacts,
        "superseded_artifacts": superseded_bindings,
        "stage_gates": stages,
        "last_accepted_stage": last_accepted,
        "next_blockers": next_blockers,
        "next_safe_offline_action": next_action,
        "node_resume": resume,
        "coverage": plan["coverage"],
        "read_only": True,
        "calculation_ready": False,
        "no_submission_authorization": True,
    })


def build_index(plan_path: Path, output: Path) -> dict[str, Any]:
    require(output.parent.absolute().resolve() == plan_path.parent.absolute().resolve(), "study index and calculation plan must share one artifact root")
    plan, chain = _validate_plan_internal(plan_path, set())
    bound_plan, plan_binding = _binding_from_path(plan_path, output.parent.absolute(), PLAN_SCHEMA, "calculation plan")
    require(bound_plan == plan, "calculation plan changed while building study index")
    artifact = _derive_index(plan, plan_binding, chain)
    write_json(output, artifact)
    return artifact


def validate_index(path: Path) -> dict[str, Any]:
    artifact = load_json(path)
    _exact(artifact, INDEX_KEYS, "study-index artifact")
    require(artifact["schema"] == INDEX_SCHEMA, "unrecognized study-index artifact schema")
    validate_payload(artifact, "study-index artifact")
    require(artifact["read_only"] is True, "study index must be read_only")
    require(artifact["calculation_ready"] is False and artifact["no_submission_authorization"] is True, "study index violates offline safety flags")
    plan, plan_path = _resolve_binding(artifact["calculation_plan"], path, PLAN_SCHEMA, "calculation plan")
    validated_plan, chain = _validate_plan_internal(plan_path, set())
    require(plan == validated_plan, "study-index plan changed during validation")
    expected = _derive_index(plan, artifact["calculation_plan"], chain)
    require(artifact == expected, "study-index artifact differs from independent deterministic recomputation/reconstruction")
    return {
        "schema": "gaussian-reaction-study-index-validation/1",
        "artifact_schema": INDEX_SCHEMA,
        "study_id": artifact["study_id"],
        "plan_id": artifact["plan_id"],
        "last_accepted_stage": artifact["last_accepted_stage"],
        "next_blocker_count": len(artifact["next_blockers"]),
        "payload_sha256": artifact["payload_sha256"],
        "live_actions": False,
    }


def _normalize_literal_binding(value: Any, expected_schema: str, label: str) -> dict[str, Any]:
    data = _exact(value, {"path", "sha256", "size_bytes", "schema", "payload_sha256"}, label)
    relative = Path(_string(data["path"], f"{label}.path"))
    require(not relative.is_absolute(), f"{label}.path must be DAG-local and relative")
    require(".." not in relative.parts, f"{label}.path must not contain parent traversal")
    require(_string(data["schema"], f"{label}.schema") == expected_schema, f"{label}.schema mismatch")
    return {
        "path": relative.as_posix(),
        "sha256": _sha256(data["sha256"], f"{label}.sha256"),
        "size_bytes": _integer(data["size_bytes"], f"{label}.size_bytes"),
        "schema": expected_schema,
        "payload_sha256": _sha256(data["payload_sha256"], f"{label}.payload_sha256"),
    }


def _normalize_locator(value: Any, label: str) -> dict[str, str]:
    data = _exact(value, {"study_id", "plan_id", "node_id"}, label)
    return {
        "study_id": _identifier(data["study_id"], f"{label}.study_id"),
        "plan_id": _identifier(data["plan_id"], f"{label}.plan_id"),
        "node_id": _identifier(data["node_id"], f"{label}.node_id"),
    }


def normalize_mapping_review(value: dict[str, Any], *, require_hash: bool) -> dict[str, Any]:
    data = _exact(value, MAPPING_REVIEW_KEYS, "calculation target-mapping review")
    require(data["schema"] == MAPPING_REVIEW_SCHEMA, "unrecognized calculation target-mapping review schema")
    review_hash = data["payload_sha256"]
    if require_hash:
        validate_payload(data, "calculation target-mapping review")
    else:
        require(review_hash is None, "target-mapping review draft payload_sha256 must be null before finalization")
    external_key = _string(data["external_target_key"], "target-mapping external_target_key")
    require(EXTERNAL_TARGET_KEY_RE.fullmatch(external_key) is not None, "target-mapping external_target_key is invalid")
    expected_kind = _string(data["expected_node_kind"], "target-mapping expected_node_kind")
    require(expected_kind == "ts_candidate", "target-mapping review /1 supports only expected_node_kind ts_candidate")
    require(data["update_kind"] == "candidate_inventory", "target-mapping review /1 supports only candidate_inventory")
    require(data["artifact_role"] == "candidate_target_import", "target-mapping review /1 requires candidate_target_import")
    require(data["review_decision"] in {"accepted", "blocked"}, "target-mapping review_decision is invalid")
    require(data["calculation_ready"] is False and data["no_submission_authorization"] is True, "target-mapping review violates offline safety constants")
    supersedes_raw = data["supersedes"]
    require(isinstance(supersedes_raw, list), "target-mapping supersedes must be an array")
    supersedes = [
        _normalize_literal_binding(item, NODE_UPDATE_SCHEMA, f"target-mapping supersedes[{index}]")
        for index, item in enumerate(supersedes_raw)
    ]
    require(len({item["payload_sha256"] for item in supersedes}) == len(supersedes), "target-mapping supersedes contains duplicate updates")
    normalized = {
        "schema": MAPPING_REVIEW_SCHEMA,
        "update_id": _identifier(data["update_id"], "target-mapping update_id"),
        "target_plan": _normalize_literal_binding(data["target_plan"], PLAN_SCHEMA, "target-mapping target_plan"),
        "target_import": _normalize_literal_binding(data["target_import"], TARGET_IMPORT_SCHEMA, "target-mapping target_import"),
        "external_target_key": external_key,
        "locator": _normalize_locator(data["locator"], "target-mapping locator"),
        "expected_node_kind": expected_kind,
        "update_kind": "candidate_inventory",
        "artifact_role": "candidate_target_import",
        "supersedes": sorted(supersedes, key=lambda item: item["payload_sha256"]),
        "review_decision": data["review_decision"],
        "reviewer": _string(data["reviewer"], "target-mapping reviewer"),
        "reviewed_at": _string(data["reviewed_at"], "target-mapping reviewed_at"),
        "review_notes": _string_list(data["review_notes"], "target-mapping review_notes"),
        "calculation_ready": False,
        "no_submission_authorization": True,
        "payload_sha256": review_hash,
    }
    if require_hash:
        require(normalized == data, "calculation target-mapping review is not in deterministic normalized form")
    return normalized


def finalize_mapping_review(draft_path: Path, output: Path) -> dict[str, Any]:
    require(output.parent.absolute().resolve() == draft_path.parent.absolute().resolve(), "target-mapping draft and finalized review must share one artifact root")
    draft = normalize_mapping_review(load_json(draft_path), require_hash=False)
    finalized = finalize({key: value for key, value in draft.items() if key != "payload_sha256"})
    # Prove every reference is exact before freezing the human decision.
    _validate_mapping_review_semantics(finalized, output)
    write_json(output, finalized)
    return finalized


def _selected_external_target(target_import: dict[str, Any], external_key: str) -> dict[str, Any]:
    targets = target_import.get("targets")
    require(isinstance(targets, list), "candidate target import targets must be an array")
    matches = [item for item in targets if isinstance(item, dict) and item.get("external_target_key") == external_key]
    require(len(matches) == 1, "reviewed external_target_key must resolve to exactly one imported target")
    return matches[0]


def _validate_mapping_review_semantics(
    review: dict[str, Any], owner_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    plan, plan_path = _resolve_binding(review["target_plan"], owner_path, PLAN_SCHEMA, "target-mapping target plan")
    validated_plan, _chain = _validate_plan_internal(plan_path, set())
    require(plan == validated_plan, "target-mapping target plan changed during validation")
    target_import, target_import_path = _resolve_binding(review["target_import"], owner_path, TARGET_IMPORT_SCHEMA, "target-mapping target import")
    _validated_upstream(target_import_path, calculation_artifacts.validate_artifact, "candidate target import")
    _selected_external_target(target_import, review["external_target_key"])
    locator = review["locator"]
    require(locator["study_id"] == plan["study_id"] and locator["plan_id"] == plan["plan_id"], "target-mapping locator does not identify the exact target plan")
    matching_nodes = [node for node in plan["nodes"] if node["node_id"] == locator["node_id"]]
    require(len(matching_nodes) == 1, "target-mapping node_id must resolve to exactly one plan node")
    require(matching_nodes[0]["node_kind"] == review["expected_node_kind"], "target-mapping expected_node_kind differs from the plan node")
    for index, binding in enumerate(review["supersedes"]):
        previous, previous_path = _resolve_binding(binding, owner_path, NODE_UPDATE_SCHEMA, f"target-mapping supersedes[{index}]")
        validated_previous = _validate_node_update_internal(previous_path, set())
        require(previous == validated_previous, f"target-mapping supersedes[{index}] changed during validation")
        require(previous["locator"] == locator, "superseded node update locator mismatch")
        require(previous["update_kind"] == review["update_kind"], "superseded node update kind mismatch")
    return plan, target_import


def validate_mapping_review(path: Path) -> dict[str, Any]:
    review = normalize_mapping_review(load_json(path), require_hash=True)
    _validate_mapping_review_semantics(review, path)
    return {
        "schema": "gaussian-reaction-calculation-target-mapping-review-validation/1",
        "artifact_schema": MAPPING_REVIEW_SCHEMA,
        "update_id": review["update_id"],
        "locator": review["locator"],
        "review_decision": review["review_decision"],
        "payload_sha256": review["payload_sha256"],
        "live_actions": False,
    }


def _assemble_node_update(
    review: dict[str, Any],
    review_binding: dict[str, Any],
    plan: dict[str, Any],
    target_import: dict[str, Any],
) -> dict[str, Any]:
    require(review["review_decision"] == "accepted", "blocked target-mapping review cannot create a node update")
    locator = review["locator"]
    require(locator["study_id"] == plan["study_id"] and locator["plan_id"] == plan["plan_id"], "target-mapping locator does not identify the exact target plan")
    matching_nodes = [node for node in plan["nodes"] if node["node_id"] == locator["node_id"]]
    require(len(matching_nodes) == 1, "target-mapping node_id must resolve to exactly one plan node")
    node = matching_nodes[0]
    require(node["node_kind"] == review["expected_node_kind"], "target-mapping expected_node_kind differs from the plan node")
    require(node["node_kind"] == "ts_candidate", "candidate target import /1 may bind only a ts_candidate node")
    selected = _selected_external_target(target_import, review["external_target_key"])
    readiness = selected.get("readiness_facts")
    require(isinstance(readiness, dict) and isinstance(readiness.get("eligible_for_later_input_review"), bool), "selected external target lacks closed readiness facts")
    return finalize({
        "schema": NODE_UPDATE_SCHEMA,
        "update_id": review["update_id"],
        "locator": locator,
        "expected_node_kind": review["expected_node_kind"],
        "target_plan": review["target_plan"],
        "review_source": review_binding,
        "update_kind": review["update_kind"],
        "artifact_role": review["artifact_role"],
        "artifact": review["target_import"],
        "external_target": {
            "external_target_key": selected["external_target_key"],
            "source_entry_sha256": _sha256(selected.get("source_entry_sha256"), "selected external target source_entry_sha256"),
            "candidate_id": _identifier(selected.get("candidate_id"), "selected external target candidate_id"),
            "source_disposition": _string(selected.get("source_disposition"), "selected external target source_disposition"),
            "eligible_for_later_input_review": readiness["eligible_for_later_input_review"],
        },
        "supersedes": review["supersedes"],
        "review": {
            "decision": review["review_decision"],
            "reviewer": review["reviewer"],
            "reviewed_at": review["reviewed_at"],
            "notes": review["review_notes"],
        },
        "calculation_ready": False,
        "no_submission_authorization": True,
    })


def build_node_update(mapping_review_path: Path, output: Path) -> dict[str, Any]:
    require(output.parent.absolute().resolve() == mapping_review_path.parent.absolute().resolve(), "node update and mapping review must share one artifact root")
    review, review_binding = _binding_from_path(mapping_review_path, output.parent.absolute(), MAPPING_REVIEW_SCHEMA, "target-mapping review")
    review = normalize_mapping_review(review, require_hash=True)
    plan, target_import = _validate_mapping_review_semantics(review, mapping_review_path)
    artifact = _assemble_node_update(review, review_binding, plan, target_import)
    write_json(output, artifact)
    return artifact


def _validate_node_update_internal(path: Path, stack: set[Path]) -> dict[str, Any]:
    absolute = path.absolute()
    require(len(stack) < MAX_SUPERSEDED_PLAN_DEPTH, f"node-update supersession ancestry exceeds supported depth {MAX_SUPERSEDED_PLAN_DEPTH}")
    require(absolute not in stack, "node-update supersession chain contains a cycle")
    stack.add(absolute)
    try:
        artifact = load_json(path)
        _exact(artifact, NODE_UPDATE_KEYS, "calculation node update")
        require(artifact["schema"] == NODE_UPDATE_SCHEMA, "unrecognized calculation node-update schema")
        validate_payload(artifact, "calculation node update")
        require(artifact["calculation_ready"] is False and artifact["no_submission_authorization"] is True, "calculation node update violates offline safety constants")
        review, review_path = _resolve_binding(artifact["review_source"], path, MAPPING_REVIEW_SCHEMA, "node-update mapping review")
        require(
            review_path.parent.resolve() == path.parent.absolute().resolve(),
            "node update and mapping review must share one artifact root",
        )
        review = normalize_mapping_review(review, require_hash=True)
        reviewed_plan, reviewed_target_import = _validate_mapping_review_semantics(review, review_path)
        require(artifact["target_plan"] == review["target_plan"], "node-update target_plan differs from its reviewed mapping")
        require(artifact["artifact"] == review["target_import"], "node-update artifact differs from its reviewed target import")
        require(artifact["supersedes"] == review["supersedes"], "node-update supersedes differs from its reviewed mapping")
        plan, plan_path = _resolve_binding(artifact["target_plan"], path, PLAN_SCHEMA, "node-update target plan")
        validated_plan, _chain = _validate_plan_internal(plan_path, set())
        require(plan == validated_plan, "node-update target plan changed during validation")
        require(plan == reviewed_plan, "node-update target plan differs from mapping-review-root validation")
        target_import, target_import_path = _resolve_binding(artifact["artifact"], path, TARGET_IMPORT_SCHEMA, "node-update candidate target import")
        _validated_upstream(target_import_path, calculation_artifacts.validate_artifact, "candidate target import")
        require(target_import == reviewed_target_import, "node-update target import differs from mapping-review-root validation")
        for index, binding in enumerate(artifact["supersedes"]):
            previous, previous_path = _resolve_binding(binding, path, NODE_UPDATE_SCHEMA, f"node-update supersedes[{index}]")
            validated_previous = _validate_node_update_internal(previous_path, stack)
            require(previous == validated_previous, f"node-update supersedes[{index}] changed during validation")
            require(previous["locator"] == review["locator"], "superseded node update locator mismatch")
            require(previous["update_kind"] == review["update_kind"], "superseded node update kind mismatch")
        expected = _assemble_node_update(review, artifact["review_source"], plan, target_import)
        require(artifact == expected, "calculation node update differs from deterministic reviewed-source reconstruction")
        return artifact
    finally:
        stack.remove(absolute)


def validate_node_update(path: Path) -> dict[str, Any]:
    artifact = _validate_node_update_internal(path, set())
    return {
        "schema": "gaussian-reaction-calculation-node-update-validation/1",
        "artifact_schema": NODE_UPDATE_SCHEMA,
        "update_id": artifact["update_id"],
        "locator": artifact["locator"],
        "update_kind": artifact["update_kind"],
        "payload_sha256": artifact["payload_sha256"],
        "live_actions": False,
    }


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)

    finalize_parser = commands.add_parser("finalize-review", help="normalize and hash one reviewed calculation-plan draft")
    finalize_parser.add_argument("draft", type=Path)
    finalize_parser.add_argument("--output", type=Path, required=True)

    build_parser = commands.add_parser("build-plan", help="build one immutable offline calculation-plan artifact")
    build_parser.add_argument("intake", type=Path)
    build_parser.add_argument("registry", type=Path)
    build_parser.add_argument("condition_model", type=Path)
    build_parser.add_argument("mechanism_network", type=Path)
    build_parser.add_argument("--review", type=Path, required=True)
    build_parser.add_argument("--mechanism-support", type=Path)
    build_parser.add_argument("--ts-precedent-map", type=Path)
    build_parser.add_argument("--supersedes-plan", type=Path, action="append", default=[])
    build_parser.add_argument("--output", type=Path, required=True)

    validate_plan_parser = commands.add_parser("validate-plan", help="validate and independently rebuild one calculation plan")
    validate_plan_parser.add_argument("artifact", type=Path)

    index_parser = commands.add_parser("build-index", help="derive one immutable read-only study resume index")
    index_parser.add_argument("plan", type=Path)
    index_parser.add_argument("--output", type=Path, required=True)

    validate_index_parser = commands.add_parser("validate-index", help="validate and independently rebuild one study index")
    validate_index_parser.add_argument("artifact", type=Path)

    finalize_mapping_parser = commands.add_parser(
        "finalize-target-mapping-review",
        help="normalize, validate exact local bindings, and hash one human-reviewed external-target mapping",
    )
    finalize_mapping_parser.add_argument("draft", type=Path)
    finalize_mapping_parser.add_argument("--output", type=Path, required=True)

    validate_mapping_parser = commands.add_parser(
        "validate-target-mapping-review",
        help="validate exact bindings and semantics of one finalized target-mapping review",
    )
    validate_mapping_parser.add_argument("artifact", type=Path)

    build_update_parser = commands.add_parser(
        "build-node-update",
        help="build one append-only DAG-owned external-target mapping update",
    )
    build_update_parser.add_argument("mapping_review", type=Path)
    build_update_parser.add_argument("--output", type=Path, required=True)

    validate_update_parser = commands.add_parser(
        "validate-node-update",
        help="validate and independently rebuild one append-only DAG node update",
    )
    validate_update_parser.add_argument("artifact", type=Path)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "finalize-review":
            result = finalize_review(args.draft, args.output)
        elif args.command == "build-plan":
            artifact = build_plan(
                args.intake,
                args.registry,
                args.condition_model,
                args.mechanism_network,
                args.review,
                args.output,
                args.mechanism_support,
                args.ts_precedent_map,
                args.supersedes_plan,
            )
            result = {
                "schema": "gaussian-reaction-calculation-plan-build/1",
                "study_id": artifact["study_id"],
                "plan_id": artifact["plan_id"],
                "gate_status": artifact["gate_status"],
                "node_count": artifact["coverage"]["node_count"],
                "blocker_count": len(artifact["blockers"]),
                "payload_sha256": artifact["payload_sha256"],
                "live_actions": False,
            }
        elif args.command == "validate-plan":
            result = validate_plan(args.artifact)
        elif args.command == "build-index":
            artifact = build_index(args.plan, args.output)
            result = {
                "schema": "gaussian-reaction-study-index-build/1",
                "study_id": artifact["study_id"],
                "plan_id": artifact["plan_id"],
                "last_accepted_stage": artifact["last_accepted_stage"],
                "payload_sha256": artifact["payload_sha256"],
                "live_actions": False,
            }
        elif args.command == "validate-index":
            result = validate_index(args.artifact)
        elif args.command == "finalize-target-mapping-review":
            review = finalize_mapping_review(args.draft, args.output)
            result = {
                "schema": "gaussian-reaction-calculation-target-mapping-review-finalization/1",
                "update_id": review["update_id"],
                "locator": review["locator"],
                "payload_sha256": review["payload_sha256"],
                "live_actions": False,
            }
        elif args.command == "validate-target-mapping-review":
            result = validate_mapping_review(args.artifact)
        elif args.command == "build-node-update":
            artifact = build_node_update(args.mapping_review, args.output)
            result = {
                "schema": "gaussian-reaction-calculation-node-update-build/1",
                "update_id": artifact["update_id"],
                "locator": artifact["locator"],
                "payload_sha256": artifact["payload_sha256"],
                "live_actions": False,
            }
        else:
            result = validate_node_update(args.artifact)
    except (ContractError, rw.OfflineError, OSError, ValueError, AssertionError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
