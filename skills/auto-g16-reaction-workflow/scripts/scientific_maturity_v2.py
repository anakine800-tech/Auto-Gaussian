#!/usr/bin/env python3
"""Owner-evidence overlay for Auto-G16 scientific maturity.

Version 2 replays an exact validated maturity gate /1 and the authoritative
calculation-plan, mechanism-support, TS-precedent, conformer, open-shell, and
manual-evidence validators.  It is offline evidence only and never grants
input-generation, calculation, or submission authority.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
import re
import stat
import sys
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable


REVIEW_SCHEMA = "gaussian-scientific-maturity-review/2"
EVIDENCE_RECEIPT_SCHEMA = "gaussian-scientific-evidence-receipt/1"
GATE_SCHEMA = "gaussian-scientific-maturity-gate/2"
ACTION_SCHEMA = "gaussian-scientific-maturity-action/2"
BASE_GATE_SCHEMA = "gaussian-scientific-maturity-gate/1"
PLAN_SCHEMA = "gaussian-reaction-calculation-plan/1"
SUPPORT_SCHEMA = "gaussian-reaction-mechanism-support/1"
PRECEDENT_SCHEMA = "gaussian-ts-precedent-map/1"
CONFORMER_SCHEMA = "gaussian-conformer-candidate-handoff/1"
OPEN_SHELL_SCHEMA = "auto-g16-main-group-open-shell-result-acceptance/1"
MANUAL_SCHEMA = "auto-g16-manual-evidence-receipt/1"
SHA_RE = re.compile(r"^[a-f0-9]{64}$")
ID_RE = re.compile(r"^[a-z][a-z0-9_]{2,95}$")
EDGE_ACTIONS = {"ts_input", "ts_submission", "irc_input", "formal_barrier_reporting"}
MANUAL_USES = {"scientific_context", "syntax_version_context", "electronic_structure_context"}


class EvidenceOverlayError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise EvidenceOverlayError(message)


def _load_module(name: str, path: Path) -> Any:
    require(path.is_file(), f"required owner validator is unavailable: {path}")
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, f"cannot load owner validator: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(path.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


def _skills_root() -> Path:
    return Path(__file__).resolve().parents[2]


@lru_cache(maxsize=1)
def _owners() -> dict[str, Any]:
    root = _skills_root()
    return {
        "base": _load_module("auto_g16_maturity_v1_owner", Path(__file__).with_name("scientific_maturity.py")),
        "plan": _load_module("auto_g16_maturity_v2_plan_owner", Path(__file__).with_name("calculation_dag.py")),
        "support": _load_module("auto_g16_maturity_v2_support_owner", Path(__file__).with_name("mechanism_support.py")),
        "precedent": _load_module("auto_g16_maturity_v2_precedent_owner", Path(__file__).with_name("ts_precedent_map.py")),
        "conformer": _load_module("auto_g16_maturity_v2_conformer_owner", root / "auto-g16-conformer-search" / "scripts" / "conformer_core.py"),
        "open_shell": _load_module("auto_g16_maturity_v2_open_shell_owner", root / "auto-g16-main-group-open-shell" / "scripts" / "open_shell_state.py"),
        "manual": _load_module("auto_g16_maturity_v2_manual_owner", root / "auto-g16-knowledge-base" / "scripts" / "manual_evidence.py"),
    }


def _exact(value: Any, keys: set[str], label: str) -> dict[str, Any]:
    require(isinstance(value, dict), f"{label} must be an object")
    require(set(value) == keys, f"{label} fields differ: missing={sorted(keys - set(value))}, unknown={sorted(set(value) - keys)}")
    return value


def _identifier(value: Any, label: str) -> str:
    require(isinstance(value, str) and ID_RE.fullmatch(value) is not None, f"{label} must be a stable lowercase ID")
    return value


def _text(value: Any, label: str) -> str:
    require(isinstance(value, str) and value.strip() == value and bool(value), f"{label} must be a non-empty trimmed string")
    return value


def _sha(value: Any, label: str) -> str:
    require(isinstance(value, str) and SHA_RE.fullmatch(value) is not None, f"{label} must be a lowercase SHA-256")
    return value


def _strings(value: Any, label: str, *, nonempty: bool = False) -> list[str]:
    require(isinstance(value, list), f"{label} must be an array")
    result = [_text(item, f"{label}[{index}]") for index, item in enumerate(value)]
    require(len(result) == len(set(result)), f"{label} contains duplicates")
    if nonempty:
        require(result, f"{label} must not be empty")
    return result


def _binding_literal(value: Any, expected_schema: str, label: str) -> dict[str, Any]:
    data = _exact(value, {"path", "sha256", "size_bytes", "schema", "payload_sha256"}, label)
    relative = Path(_text(data["path"], f"{label}.path"))
    require(not relative.is_absolute() and ".." not in relative.parts, f"{label}.path must be portable and relative")
    require(data["schema"] == expected_schema, f"{label}.schema must be {expected_schema}")
    _sha(data["sha256"], f"{label}.sha256")
    _sha(data["payload_sha256"], f"{label}.payload_sha256")
    require(isinstance(data["size_bytes"], int) and not isinstance(data["size_bytes"], bool) and data["size_bytes"] >= 0, f"{label}.size_bytes is invalid")
    return dict(data)


def _payload_sha256(value: dict[str, Any]) -> str:
    payload = copy.deepcopy(value)
    payload.pop("payload_sha256", None)
    raw = (json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _finalize(value: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(value)
    result["payload_sha256"] = _payload_sha256(result)
    return result


def _load(path: Path) -> dict[str, Any]:
    return _owners()["base"].load_json(path)


def _write(path: Path, value: dict[str, Any]) -> None:
    require(path.parent.is_dir() and not path.parent.is_symlink(), "output parent must be a real existing directory")
    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    except FileExistsError as exc:
        raise EvidenceOverlayError(f"refusing to overwrite output: {path}") from exc


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_binding(path: Path, root: Path, schema: str) -> tuple[dict[str, Any], dict[str, Any]]:
    resolved = Path(os.path.abspath(path))
    root_absolute = Path(os.path.abspath(root))
    root_resolved = root_absolute.resolve(strict=True)
    try:
        relative = resolved.relative_to(root_absolute)
    except ValueError:
        try:
            relative = resolved.resolve(strict=True).relative_to(root_resolved)
        except ValueError:
            raise EvidenceOverlayError(f"bound artifact escapes the overlay root: {path}") from None
    require(not relative.is_absolute() and ".." not in relative.parts, "bound artifact path must be portable and relative")
    resolved = _strict_resolve(root_resolved, relative, "bound artifact")
    document = _load(resolved)
    require(document.get("schema") == schema, f"bound artifact schema must be {schema}")
    _sha(document.get("payload_sha256"), f"{path} payload_sha256")
    return document, {
        "path": relative.as_posix(), "sha256": _file_sha(resolved), "size_bytes": resolved.stat().st_size,
        "schema": schema, "payload_sha256": document["payload_sha256"],
    }


def _strict_resolve(root: Path, relative: Path, label: str) -> Path:
    """Resolve one portable path without following any artifact-tree symlink."""

    require(not relative.is_absolute() and ".." not in relative.parts, f"{label} path must be portable and relative")
    root_resolved = root.resolve(strict=True)
    require(root_resolved.is_dir(), f"{label} root must be an existing directory")
    current = root_resolved
    for part in relative.parts:
        current = current / part
        try:
            mode = os.lstat(current).st_mode
        except FileNotFoundError as exc:
            raise EvidenceOverlayError(f"{label} is unavailable: {current}") from exc
        require(not stat.S_ISLNK(mode), f"{label} path contains a symlink: {current}")
    resolved = current.resolve(strict=True)
    try:
        resolved.relative_to(root_resolved)
    except ValueError:
        raise EvidenceOverlayError(f"{label} escapes its artifact root: {relative}") from None
    require(resolved.is_file(), f"{label} must resolve to a regular file")
    return resolved


def _resolve(binding: Any, owner: Path, expected_schema: str) -> tuple[dict[str, Any], Path]:
    data = _binding_literal(binding, expected_schema, "artifact binding")
    path = _strict_resolve(owner.parent, Path(data["path"]), "artifact binding")
    document = _load(path)
    require(_file_sha(path) == data["sha256"] and path.stat().st_size == data["size_bytes"], "artifact file binding changed")
    require(document.get("schema") == expected_schema and document.get("payload_sha256") == data["payload_sha256"], "artifact schema or payload binding changed")
    require(_payload_sha256(document) == document["payload_sha256"], "artifact payload hash is invalid")
    return document, path


def _resolve_owner_binding(binding: dict[str, Any], owner_path: Path) -> Path:
    relative = Path(binding["path"])
    require(not relative.is_absolute() and ".." not in relative.parts, "owner binding path must be portable and relative")
    return _strict_resolve(owner_path.parent, relative, "owner binding")


def _normalize_review(value: dict[str, Any], *, require_hash: bool) -> dict[str, Any]:
    data = _exact(value, {
        "schema", "review_id", "study_id", "base_gate_payload_sha256", "edge_evidence",
        "minimum_evidence", "manual_claims", "review_decision", "reviewer", "reviewed_at",
        "review_notes", "calculation_ready", "no_submission_authorization",
        "no_method_selection_authorization", "no_input_generation_authorization", "payload_sha256",
    }, "scientific-maturity review /2")
    require(data["schema"] == REVIEW_SCHEMA, f"review schema must be {REVIEW_SCHEMA}")
    if require_hash:
        require(data["payload_sha256"] == _payload_sha256(data), "scientific-maturity review /2 payload hash is invalid")
    else:
        require(data["payload_sha256"] is None, "review /2 draft payload_sha256 must be null")
    require(data["calculation_ready"] is False and data["no_submission_authorization"] is True, "review /2 safety constants changed")
    require(data["no_method_selection_authorization"] is True and data["no_input_generation_authorization"] is True, "review /2 method/input authority constants changed")

    edges = []
    for index, raw in enumerate(data["edge_evidence"]):
        item = _exact(raw, {"edge_id", "stereochemical_channel", "mechanism_support_record_ids", "candidate_construction"}, f"edge_evidence[{index}]")
        channel = item["stereochemical_channel"]
        require(channel is None or isinstance(channel, str), f"edge_evidence[{index}].stereochemical_channel must be string or null")
        construction = _exact(item["candidate_construction"], {"kind", "source_id"}, f"edge_evidence[{index}].candidate_construction")
        require(construction["kind"] in {"precedent_record", "de_novo_seed_plan"}, "candidate construction kind is invalid")
        edges.append({
            "edge_id": _identifier(item["edge_id"], "edge evidence edge_id"),
            "stereochemical_channel": channel,
            "mechanism_support_record_ids": sorted(_strings(item["mechanism_support_record_ids"], "mechanism support record IDs", nonempty=True)),
            "candidate_construction": {"kind": construction["kind"], "source_id": _identifier(construction["source_id"], "candidate construction source_id")},
        })
    require(edges and len({item["edge_id"] for item in edges}) == len(edges), "edge evidence must be non-empty and unique by edge")

    minima = []
    for index, raw in enumerate(data["minimum_evidence"]):
        item = _exact(raw, {
            "minimum_id", "state_id", "composition_signature", "formal_charge", "multiplicity",
            "conformer_origin", "selected_candidate_id", "conformer_handoff", "open_shell_acceptance",
        }, f"minimum_evidence[{index}]")
        require(isinstance(item["formal_charge"], int) and not isinstance(item["formal_charge"], bool), "minimum formal_charge must be integer")
        require(isinstance(item["multiplicity"], int) and not isinstance(item["multiplicity"], bool) and item["multiplicity"] > 0, "minimum multiplicity must be positive integer")
        open_shell = item["open_shell_acceptance"]
        if open_shell is not None:
            open_shell = _binding_literal(open_shell, OPEN_SHELL_SCHEMA, f"minimum_evidence[{index}].open_shell_acceptance")
        origin = _exact(
            item["conformer_origin"], {"scope", "source_id", "ts_derivation_allowed"},
            f"minimum_evidence[{index}].conformer_origin",
        )
        require(isinstance(origin["ts_derivation_allowed"], bool), "conformer_origin.ts_derivation_allowed must be boolean")
        minima.append({
            "minimum_id": _identifier(item["minimum_id"], "minimum evidence minimum_id"),
            "state_id": _identifier(item["state_id"], "minimum evidence state_id"),
            "composition_signature": _text(item["composition_signature"], "minimum composition_signature"),
            "formal_charge": item["formal_charge"], "multiplicity": item["multiplicity"],
            "conformer_origin": {
                "scope": _text(origin["scope"], "conformer_origin.scope"),
                "source_id": _identifier(origin["source_id"], "conformer_origin.source_id"),
                "ts_derivation_allowed": origin["ts_derivation_allowed"],
            },
            "selected_candidate_id": _identifier(item["selected_candidate_id"], "selected conformer candidate ID"),
            "conformer_handoff": _binding_literal(item["conformer_handoff"], CONFORMER_SCHEMA, f"minimum_evidence[{index}].conformer_handoff"),
            "open_shell_acceptance": open_shell,
        })
    require(minima and len({item["minimum_id"] for item in minima}) == len(minima), "minimum evidence must be non-empty and unique")

    claims = []
    for index, raw in enumerate(data["manual_claims"]):
        item = _exact(raw, {"claim_id", "target_kind", "target_id", "intended_use", "receipt"}, f"manual_claims[{index}]")
        require(item["target_kind"] in {"study", "edge", "minimum"}, "manual claim target_kind is invalid")
        if item["target_kind"] == "study":
            require(item["target_id"] is None, "study manual claim target_id must be null")
            target_id = None
        else:
            target_id = _identifier(item["target_id"], "manual claim target_id")
        require(item["intended_use"] in MANUAL_USES, "manual claim intended_use is invalid")
        claims.append({
            "claim_id": _identifier(item["claim_id"], "manual claim_id"), "target_kind": item["target_kind"],
            "target_id": target_id, "intended_use": item["intended_use"],
            "receipt": _binding_literal(item["receipt"], MANUAL_SCHEMA, f"manual_claims[{index}].receipt"),
        })
    require(len({item["claim_id"] for item in claims}) == len(claims), "manual claim IDs must be unique")
    require(data["review_decision"] in {"accepted", "blocked"}, "review /2 decision must be accepted or blocked")
    normalized = {
        "schema": REVIEW_SCHEMA, "review_id": _identifier(data["review_id"], "review_id"),
        "study_id": _identifier(data["study_id"], "study_id"),
        "base_gate_payload_sha256": _sha(data["base_gate_payload_sha256"], "base gate payload SHA-256"),
        "edge_evidence": sorted(edges, key=lambda item: item["edge_id"]),
        "minimum_evidence": sorted(minima, key=lambda item: item["minimum_id"]),
        "manual_claims": sorted(claims, key=lambda item: item["claim_id"]),
        "review_decision": data["review_decision"], "reviewer": _text(data["reviewer"], "reviewer"),
        "reviewed_at": _text(data["reviewed_at"], "reviewed_at"),
        "review_notes": _strings(data["review_notes"], "review notes"),
        "calculation_ready": False, "no_submission_authorization": True,
        "no_method_selection_authorization": True, "no_input_generation_authorization": True,
        "payload_sha256": data["payload_sha256"],
    }
    if require_hash:
        require(normalized == data, "scientific-maturity review /2 is not deterministically normalized")
    return normalized


def finalize_review(draft: Path, output: Path) -> dict[str, Any]:
    normalized = _normalize_review(_load(draft), require_hash=False)
    artifact = _finalize({key: value for key, value in normalized.items() if key != "payload_sha256"})
    _write(output, artifact)
    return artifact


def _formula(elements: Iterable[str]) -> str:
    counts = Counter(elements)
    if "C" in counts:
        order = ["C"] + (["H"] if "H" in counts else []) + sorted(symbol for symbol in counts if symbol not in {"C", "H"})
    else:
        order = sorted(counts)
    return "".join(symbol + (str(counts[symbol]) if counts[symbol] != 1 else "") for symbol in order)


def _blocker(blocker_id: str, scope: str, description: str) -> dict[str, str]:
    return {"blocker_id": blocker_id, "scope": scope, "description": description}


def _owner_ref_matches(binding: dict[str, Any], expected: dict[str, Any], label: str) -> None:
    for key in ("sha256", "size_bytes", "schema", "payload_sha256"):
        require(binding.get(key) == expected.get(key), f"{label} differs from the exact calculation-plan binding: {key}")


def _plan_edge_blockers(
    plan: dict[str, Any], edge_id: str, *, exact_mechanism_support_projection: bool = False,
) -> list[str]:
    nodes = {node["node_id"]: node for node in plan["nodes"]}
    memo: dict[str, set[str]] = {}

    def unresolved(node_id: str, stack: set[str]) -> set[str]:
        require(node_id not in stack, "calculation plan dependency cycle escaped owner validation")
        if node_id in memo:
            return memo[node_id]
        node = nodes[node_id]
        result: set[str] = set()
        for blocker_id in node["readiness"]["scientific"]["blocker_ids"]:
            if blocker_id == "mechanism_support_channel_mapping_missing" and exact_mechanism_support_projection:
                continue
            expected_dependency = f"{node_id}_dependency_blocked"
            if blocker_id == expected_dependency and node["depends_on"]:
                dependency_blockers = set().union(*(unresolved(parent, stack | {node_id}) for parent in node["depends_on"]))
                if dependency_blockers:
                    result.add(blocker_id)
                    result.update(dependency_blockers)
                continue
            result.add(blocker_id)
        memo[node_id] = result
        return result

    blocker_ids: set[str] = set()
    for node in plan["nodes"]:
        if node["disposition"] in {"planned", "retained"} and edge_id in node["target"]["edge_ids"]:
            blocker_ids.update(unresolved(node["node_id"], set()))
    return sorted(blocker_ids)


def _project_open_shell_evidence(
    item: dict[str, Any], signature: dict[str, Any], selected: str, review_path: Path, owner: Any,
) -> tuple[dict[str, Any] | None, list[str]]:
    """Replay specialist acceptance and project only its exact candidate identity."""

    local: list[str] = []
    projection = None
    all_main_group = all(symbol in owner.MAIN_GROUP_SYMBOLS for symbol in signature["elements"])
    if item["multiplicity"] == 1:
        if item["open_shell_acceptance"] is not None:
            local.append("closed_shell_minimum_must_not_claim_open_shell_acceptance")
    elif all_main_group and item["multiplicity"] in {2, 3}:
        if item["open_shell_acceptance"] is None:
            local.append("main_group_open_shell_acceptance_missing")
        else:
            acceptance_document, acceptance_path = _resolve(item["open_shell_acceptance"], review_path, OPEN_SHELL_SCHEMA)
            acceptance = owner.validate_artifact(acceptance_path)
            require(acceptance == acceptance_document, "open-shell owner validator returned a different accepted artifact")
            owner_review_path, open_review = owner.load_validated_review(acceptance["review_source"]["path"])
            owner_observation_path, observation = owner.load_validated_observation(acceptance["observation_source"]["path"])
            require(owner.file_sha256(owner_review_path) == acceptance["review_source"]["sha256"], "open-shell acceptance review file binding changed")
            require(open_review["payload_sha256"] == acceptance["review_source"]["payload_sha256"], "open-shell acceptance review payload binding changed")
            require(owner.file_sha256(owner_observation_path) == acceptance["observation_source"]["sha256"], "open-shell acceptance observation file binding changed")
            require(observation["payload_sha256"] == acceptance["observation_source"]["payload_sha256"], "open-shell acceptance observation payload binding changed")
            candidate = open_review["candidate_snapshot"]
            if acceptance["status"] != "accepted" or acceptance["decision"] != "accepted_for_v1_minimum_evidence":
                local.append("main_group_open_shell_acceptance_is_blocked")
            if candidate["candidate_id"] != selected:
                local.append("open_shell_candidate_differs_from_selected_conformer")
            if candidate["charge"] != item["formal_charge"] or candidate["multiplicity"] != item["multiplicity"]:
                local.append("open_shell_charge_or_multiplicity_differs_from_minimum")
            if [atom["element"] for atom in candidate["atoms"]] != signature["elements"]:
                local.append("open_shell_candidate_element_order_differs_from_conformer")
            projection = {
                "acceptance_id": acceptance["acceptance_id"], "candidate_id": candidate["candidate_id"],
                "status": acceptance["status"], "decision": acceptance["decision"],
                "payload_sha256": acceptance["payload_sha256"],
                "candidate_structure_sha256": candidate["structure_sha256"],
                "candidate_source_sha256": open_review["candidate_source"]["sha256"],
                "observation_payload_sha256": observation["payload_sha256"],
                "raw_log_sha256": observation["source"]["sha256"],
            }
    else:
        if item["open_shell_acceptance"] is not None:
            local.append("open_shell_acceptance_cannot_promote_outside_v1_specialist_scope")
        local.append("open_shell_minimum_outside_main_group_v1_specialist_scope")
    return projection, sorted(set(local))


def _minimum_candidate_input_result_lineage_blockers() -> list[str]:
    """Current owners do not bind a selected medoid through input approval to the minimum result/log."""

    return ["minimum_candidate_input_result_lineage_unavailable_v2"]


def _owner_manifest(conformer: Any, handoff: dict[str, Any], handoff_path: Path) -> dict[str, Any]:
    manifest_path = conformer.resolve_bound_path(handoff_path, handoff["manifest"]["path"], "bound conformer ensemble manifest")
    return conformer.load_json(manifest_path)


def _build_evidence_receipt(
    base_gate: dict[str, Any], base_gate_binding: dict[str, Any], base_gate_path: Path,
    review: dict[str, Any], review_binding: dict[str, Any], review_path: Path, output: Path,
) -> dict[str, Any]:
    owners = _owners()
    require(base_gate["study_id"] == review["study_id"], "base gate and review /2 study_id differ")
    require(base_gate["payload_sha256"] == review["base_gate_payload_sha256"], "review /2 is not bound to the exact base gate /1")

    plan, plan_path = _resolve(base_gate["calculation_plan"], base_gate_path, PLAN_SCHEMA)
    plan_validation = owners["plan"].validate_plan(plan_path)
    base_review, _ = _resolve(base_gate["review_source"], base_gate_path, "gaussian-scientific-maturity-review/1")
    # Scientific authority comes from the public calculation-plan replay above.
    # This strict resolver only projects the already owner-validated mechanism.
    mechanism, mechanism_path = _resolve(plan["mechanism_network"], plan_path, "gaussian-reaction-mechanism-network/1")
    mechanism_states = {item["state_id"]: item for item in mechanism["states"]}
    mechanism_edges = {item["edge_id"]: item for item in mechanism["edges"]}
    base_minima = {item["minimum_id"]: item for item in base_review["minimum_records"]}
    base_minimum_gates = {item["minimum_id"]: item for item in base_gate["minimum_gates"]}
    base_edges = {item["edge_id"]: item for item in base_review["edge_reviews"]}

    require(plan.get("mechanism_support") is not None, "calculation plan lacks exact mechanism-support owner evidence")
    require(plan.get("ts_precedent_map") is not None, "calculation plan lacks exact TS-precedent owner evidence")
    support_path = _resolve_owner_binding(plan["mechanism_support"], plan_path)
    support, support_binding = _make_binding(support_path, output.parent, SUPPORT_SCHEMA)
    _owner_ref_matches(support_binding, plan["mechanism_support"], "mechanism-support artifact")
    support_validation = owners["support"].validate(support_path)
    precedent_path = _resolve_owner_binding(plan["ts_precedent_map"], plan_path)
    precedent, precedent_binding = _make_binding(precedent_path, output.parent, PRECEDENT_SCHEMA)
    _owner_ref_matches(precedent_binding, plan["ts_precedent_map"], "TS-precedent artifact")
    precedent_validation = owners["precedent"].validate(precedent_path)
    require(precedent["mechanism_support"]["payload_sha256"] == support["payload_sha256"], "TS-precedent map and mechanism support ancestry differ")
    require(support["mechanism_network"]["payload_sha256"] == mechanism["payload_sha256"], "mechanism support and base plan network ancestry differ")
    require(precedent["mechanism_network"]["payload_sha256"] == mechanism["payload_sha256"], "TS-precedent and base plan network ancestry differ")

    review_edges = {item["edge_id"]: item for item in review["edge_evidence"]}
    require(set(review_edges) == set(base_edges), "review /2 edge evidence must exactly cover the base maturity review edges")
    support_summaries = {(item["edge_id"], item["stereochemical_channel"]): item for item in support["edge_channel_summary"]}
    precedent_records = {item["precedent_id"]: item for item in precedent["records"]}
    de_novo_records = {item["seed_plan_id"]: item for item in precedent["de_novo_seed_plans"]}
    edge_results: list[dict[str, Any]] = []
    blockers: list[dict[str, str]] = []
    support_top_ready = support["review"].get("decision") == "accepted" and support["gate_status"] == "reviewed" and not support["blockers"]
    precedent_top_ready = precedent["review"].get("decision") == "accepted" and precedent["gate_status"] == "reviewed" and not precedent["blockers"] and precedent["candidate_construction_promotable"] is True
    for edge_id in sorted(review_edges):
        item = review_edges[edge_id]
        source_edge = mechanism_edges.get(edge_id)
        require(source_edge is not None, f"review /2 edge is absent from mechanism network: {edge_id}")
        require(item["stereochemical_channel"] == source_edge["stereochemical_channel"] == base_edges[edge_id]["stereochemical_channel"], f"edge/channel ancestry mismatch for {edge_id}")
        summary = support_summaries.get((edge_id, item["stereochemical_channel"]))
        require(summary is not None, f"mechanism support lacks exact target edge/channel: {edge_id}")
        require(item["mechanism_support_record_ids"] == summary["support_record_ids"], f"review /2 support-record projection differs for {edge_id}")
        construction = item["candidate_construction"]
        collection = precedent_records if construction["kind"] == "precedent_record" else de_novo_records
        candidate = collection.get(construction["source_id"])
        require(candidate is not None, f"selected candidate-construction source is absent: {construction['source_id']}")
        target = candidate["target"]
        require(target["edge_id"] == edge_id and target["stereochemical_channel"] == item["stereochemical_channel"], f"candidate-construction source targets another edge/channel: {construction['source_id']}")
        plan_blockers = _plan_edge_blockers(plan, edge_id, exact_mechanism_support_projection=True)
        local: list[str] = []
        if not support_top_ready:
            local.append("mechanism_support_owner_gate_not_reviewed_clear_and_accepted")
        if not summary["hypothesis_exploration_eligible"]:
            local.append("mechanism_support_exact_edge_channel_not_exploration_eligible")
        if not precedent_top_ready:
            local.append("ts_precedent_owner_gate_not_reviewed_clear_and_promotable")
        if candidate["candidate_construction_gate"] != "candidate_construction_eligible":
            local.append("candidate_construction_source_not_eligible")
        if candidate["disposition"]["status"] != "accepted_for_candidate_construction":
            local.append("candidate_construction_disposition_not_accepted")
        if candidate["disposition"]["promotion_review"]["status"] != "approved" or candidate["promotion_requirements_complete"] is not True:
            local.append("candidate_construction_promotion_requirements_incomplete")
        if candidate["blockers"]:
            local.append("candidate_construction_source_has_blockers")
        if plan_blockers:
            local.extend(f"calculation_plan_blocker:{blocker_id}" for blocker_id in plan_blockers)
        pilot_ready = not local
        formal_local = list(local)
        if construction["kind"] == "de_novo_seed_plan":
            formal_local.append("de_novo_seed_plan_is_pilot_only")
        if not summary["mechanism_claim_supported"]:
            formal_local.append("mechanism_claim_not_supported_for_exact_edge_channel")
        formal_ready = not formal_local
        edge_results.append({
            "edge_id": edge_id, "stereochemical_channel": item["stereochemical_channel"],
            "mechanism_support_record_ids": item["mechanism_support_record_ids"],
            "mechanism_support_gate_status": support["gate_status"],
            "hypothesis_exploration_eligible": summary["hypothesis_exploration_eligible"],
            "mechanism_claim_supported": summary["mechanism_claim_supported"],
            "candidate_construction": copy.deepcopy(construction),
            "candidate_construction_gate": candidate["candidate_construction_gate"],
            "promotion_requirements_complete": candidate["promotion_requirements_complete"],
            "plan_blockers_after_owner_projection": plan_blockers,
            "pilot_owner_evidence_ready": pilot_ready, "formal_owner_evidence_ready": formal_ready,
            "pilot_blockers": sorted(set(local)), "formal_blockers": sorted(set(formal_local)),
        })
        for code in sorted(set(formal_local)):
            blockers.append(_blocker(f"{edge_id}_{hashlib.sha256(code.encode()).hexdigest()[:16]}", edge_id, code))

    review_minima = {item["minimum_id"]: item for item in review["minimum_evidence"]}
    require(set(review_minima) == set(base_minima), "review /2 minimum evidence must exactly cover the base maturity review minima")
    minimum_results: list[dict[str, Any]] = []
    for minimum_id in sorted(review_minima):
        item = review_minima[minimum_id]
        base = base_minima[minimum_id]
        state = mechanism_states.get(item["state_id"])
        require(state is not None, f"minimum {minimum_id} state is absent from mechanism network")
        require(
            (item["state_id"], item["composition_signature"], item["formal_charge"], item["multiplicity"])
            == (base["state_id"], base["composition_signature"], base["formal_charge"], base["multiplicity"]),
            f"minimum {minimum_id} /2 mapping differs from base review /1",
        )
        require(item["conformer_origin"] == base["conformer_origin"], f"minimum {minimum_id} conformer_origin differs from base review /1")
        handoff, handoff_path = _resolve(item["conformer_handoff"], review_path, CONFORMER_SCHEMA)
        owners["conformer"].validate_handoff(handoff_path)
        manifest = _owner_manifest(owners["conformer"], handoff, handoff_path)
        selected = item["selected_candidate_id"]
        medoids = {cluster["medoid_candidate_id"] for cluster in manifest["clusters"]}
        signature = handoff["state_signature"]
        local: list[str] = []
        if selected not in handoff["selected_candidate_ids"] or selected not in medoids:
            local.append("selected_conformer_is_not_a_reviewed_handoff_medoid")
        expected_atoms = state["atoms"]
        expected_elements = [atom["element"] for atom in expected_atoms]
        expected_order = [atom["atom_id"] for atom in expected_atoms]
        expected_signature = {
            "state_id": state["state_id"], "formal_charge": state["formal_charge"],
            "multiplicity": state["multiplicity"], "component_count": len(state["components"]),
            "atom_order": expected_order, "elements": expected_elements,
        }
        actual_signature = {key: signature[key] for key in expected_signature}
        if actual_signature != expected_signature:
            local.append("conformer_state_signature_differs_from_mechanism_owner")
        if _formula(signature["elements"]) != item["composition_signature"]:
            local.append("conformer_composition_differs_from_minimum_mapping")
        if base_minimum_gates[minimum_id]["accepted"] is not True:
            local.append("base_minimum_owner_log_acceptance_is_blocked")
        if item["conformer_origin"]["scope"] != "minimum_search":
            local.append("base_conformer_origin_scope_is_not_minimum_search")
        if item["conformer_origin"]["source_id"] != selected:
            local.append("base_conformer_origin_source_id_differs_from_selected_candidate")
        open_shell_projection, open_shell_blockers = _project_open_shell_evidence(
            item, signature, selected, review_path, owners["open_shell"],
        )
        local.extend(open_shell_blockers)
        local.extend(_minimum_candidate_input_result_lineage_blockers())
        ready = not local
        minimum_results.append({
            "minimum_id": minimum_id, "state_id": item["state_id"],
            "composition_signature": item["composition_signature"], "formal_charge": item["formal_charge"],
            "multiplicity": item["multiplicity"], "conformer_handoff_payload_sha256": handoff["payload_sha256"],
            "ensemble_manifest_payload_sha256": manifest["payload_sha256"], "selected_candidate_id": selected,
            "conformer_origin": copy.deepcopy(item["conformer_origin"]),
            "selected_candidate_is_reviewed_medoid": selected in handoff["selected_candidate_ids"] and selected in medoids,
            "candidate_input_result_lineage_status": "unavailable_v2_requires_exact_input_approval_and_result_binding",
            "open_shell_acceptance": open_shell_projection, "owner_evidence_ready": ready,
            "blockers": sorted(set(local)),
        })
        for code in sorted(set(local)):
            blockers.append(_blocker(f"{minimum_id}_{hashlib.sha256(code.encode()).hexdigest()[:16]}", minimum_id, code))

    edge_ids = set(review_edges)
    minimum_ids = set(review_minima)
    manual_results: list[dict[str, Any]] = []
    for claim in review["manual_claims"]:
        if claim["target_kind"] == "edge":
            require(claim["target_id"] in edge_ids, f"manual claim targets unknown edge: {claim['target_id']}")
        if claim["target_kind"] == "minimum":
            require(claim["target_id"] in minimum_ids, f"manual claim targets unknown minimum: {claim['target_id']}")
        receipt, receipt_path = _resolve(claim["receipt"], review_path, MANUAL_SCHEMA)
        owners["manual"].validate_receipt(receipt)
        local: list[str] = []
        if receipt["downstream_role"] != "scientific_maturity_supporting_evidence":
            local.append("manual_receipt_downstream_role_mismatch")
        if receipt["applicability"]["decision"] not in {"applicable", "applicable_with_limits"}:
            local.append("manual_receipt_not_positively_applicable")
        if receipt["target_installation"]["major_version"] != "G16":
            local.append("manual_receipt_target_is_not_gaussian_16")
        if claim["intended_use"] == "syntax_version_context" and not (
            receipt["source"]["source_kind"] == "gaussian_program_manual"
            and receipt["source"]["claim_scope"] == "gaussian_syntax_or_version"
        ):
            local.append("manual_receipt_source_scope_incompatible_with_syntax_version_context")
        if claim["intended_use"] == "electronic_structure_context" and receipt["source"]["claim_scope"] not in {
            "gaussian_nonversion_concept", "general_electronic_structure",
        }:
            local.append("manual_receipt_source_scope_incompatible_with_electronic_structure_context")
        manual_results.append({
            "claim_id": claim["claim_id"], "target_kind": claim["target_kind"], "target_id": claim["target_id"],
            "intended_use": claim["intended_use"], "receipt_id": receipt["receipt_id"],
            "receipt_payload_sha256": receipt["payload_sha256"],
            "downstream_role": receipt["downstream_role"],
            "adapter_id": receipt["retrieval"]["adapter_id"],
            "adapter_config_sha256": receipt["retrieval"]["adapter_config_sha256"],
            "canonical_store_digest": receipt["retrieval"]["canonical_store_digest"],
            "retrieval_database_sha256": receipt["retrieval"]["retrieval_database_sha256"],
            "retrieval_query": receipt["retrieval"]["query"],
            "retrieval_result_id": receipt["retrieval"]["result_id"],
            "retrieval_row_sha256": receipt["retrieval"]["retrieval_row_sha256"],
            "retrieved_text_sha256": receipt["retrieval"]["retrieved_text_sha256"],
            "source_record_id": receipt["source"]["record_id"], "source_revision": receipt["source"]["revision"],
            "source_kind": receipt["source"]["source_kind"], "claim_scope": receipt["source"]["claim_scope"],
            "source_payload_sha256": receipt["source"]["payload_sha256"],
            "source_object_sha256": receipt["source"]["object_sha256"],
            "source_program": copy.deepcopy(receipt["source"]["program"]),
            "locator": copy.deepcopy(receipt["source"]["locator"]),
            "text_quality": copy.deepcopy(receipt["source"]["text_quality"]),
            "applicability": copy.deepcopy(receipt["applicability"]),
            "target_installation": copy.deepcopy(receipt["target_installation"]),
            "uncertainties": copy.deepcopy(receipt["uncertainties"]),
            "supporting_only": True, "owner_evidence_ready": not local, "blockers": sorted(set(local)),
        })
        for code in sorted(set(local)):
            scope = claim["target_id"] or review["study_id"]
            blockers.append(_blocker(f"{claim['claim_id']}_{hashlib.sha256(code.encode()).hexdigest()[:16]}", scope, code))
    if review["review_decision"] != "accepted":
        blockers.append(_blocker("scientific_maturity_review_v2_not_accepted", review["study_id"], "scientific maturity review /2 is blocked"))
    blockers = sorted({item["blocker_id"]: item for item in blockers}.values(), key=lambda item: item["blocker_id"])
    plan_document, plan_binding = _make_binding(plan_path, output.parent, PLAN_SCHEMA)
    require(plan_document == plan, "calculation plan changed during evidence reconstruction")
    return _finalize({
        "schema": EVIDENCE_RECEIPT_SCHEMA, "receipt_id": f"{review['review_id']}_owner_evidence", "study_id": review["study_id"],
        "base_gate": base_gate_binding, "review_source": review_binding, "calculation_plan": plan_binding,
        "mechanism_support": support_binding, "ts_precedent_map": precedent_binding,
        "owner_validation_results": {
            "calculation_plan": plan_validation, "mechanism_support": support_validation,
            "ts_precedent_map": precedent_validation,
        },
        "edge_evidence": edge_results, "minimum_evidence": minimum_results, "manual_evidence": manual_results,
        "gate_status": "reviewed" if not blockers else "blocked", "blockers": blockers,
        "manual_evidence_authority": "supporting_only_never_substitutes_for_owner_or_live_gates",
        "calculation_ready": False, "no_submission_authorization": True,
        "no_method_selection_authorization": True, "no_input_generation_authorization": True,
    })


def build_evidence_receipt(base_gate_path: Path, review_path: Path, output: Path) -> dict[str, Any]:
    owners = _owners()
    owners["base"].validate_gate(base_gate_path)
    base_gate, base_binding = _make_binding(base_gate_path, output.parent, BASE_GATE_SCHEMA)
    review, review_binding = _make_binding(review_path, output.parent, REVIEW_SCHEMA)
    review = _normalize_review(review, require_hash=True)
    artifact = _build_evidence_receipt(base_gate, base_binding, base_gate_path, review, review_binding, review_path, output)
    _write(output, artifact)
    return artifact


def validate_evidence_receipt(path: Path) -> dict[str, Any]:
    artifact = _load(path)
    require(artifact.get("schema") == EVIDENCE_RECEIPT_SCHEMA, f"evidence receipt schema must be {EVIDENCE_RECEIPT_SCHEMA}")
    require(artifact.get("payload_sha256") == _payload_sha256(artifact), "evidence receipt payload hash is invalid")
    require(artifact.get("calculation_ready") is False and artifact.get("no_submission_authorization") is True, "evidence receipt safety constants changed")
    base_gate, base_path = _resolve(artifact["base_gate"], path, BASE_GATE_SCHEMA)
    _owners()["base"].validate_gate(base_path)
    review, review_path = _resolve(artifact["review_source"], path, REVIEW_SCHEMA)
    review = _normalize_review(review, require_hash=True)
    expected = _build_evidence_receipt(base_gate, artifact["base_gate"], base_path, review, artifact["review_source"], review_path, path)
    require(artifact == expected, "evidence receipt differs from deterministic owner reconstruction")
    return artifact


def _build_gate(base_gate: dict[str, Any], base_binding: dict[str, Any], receipt: dict[str, Any], receipt_binding: dict[str, Any], review: dict[str, Any], review_binding: dict[str, Any]) -> dict[str, Any]:
    require(base_gate["study_id"] == receipt["study_id"] == review["study_id"], "maturity /2 ancestry study_id differs")
    require(receipt["base_gate"]["payload_sha256"] == base_gate["payload_sha256"], "evidence receipt binds a different base gate")
    require(receipt["review_source"]["payload_sha256"] == review["payload_sha256"], "evidence receipt binds a different review /2")
    minima = {item["minimum_id"]: item for item in receipt["minimum_evidence"]}
    edge_evidence = {item["edge_id"]: item for item in receipt["edge_evidence"]}
    manual_by_scope: dict[tuple[str, str | None], list[str]] = {}
    for item in receipt["manual_evidence"]:
        if not item["owner_evidence_ready"]:
            manual_by_scope.setdefault((item["target_kind"], item["target_id"]), []).extend(item["blockers"])
    minimum_gates = []
    for base_minimum in base_gate["minimum_gates"]:
        evidence = minima[base_minimum["minimum_id"]]
        local = list(evidence["blockers"])
        local.extend(manual_by_scope.get(("minimum", base_minimum["minimum_id"]), []))
        local.extend(manual_by_scope.get(("study", None), []))
        if base_minimum["accepted"] is not True:
            local.append("base_minimum_gate_is_blocked")
        minimum_gates.append({
            "minimum_id": base_minimum["minimum_id"], "state_id": base_minimum["state_id"],
            "owner_evidence_ready": not local, "selected_candidate_id": evidence["selected_candidate_id"],
            "blockers": sorted(set(local)),
        })
    minimum_map = {item["minimum_id"]: item for item in minimum_gates}
    edge_gates = []
    for base_edge in base_gate["edge_gates"]:
        evidence = edge_evidence[base_edge["edge_id"]]
        endpoint_blockers = [
            f"{minimum_id}_owner_evidence_blocked"
            for minimum_id in (base_edge["start_minimum_id"], base_edge["end_minimum_id"])
            if not minimum_map[minimum_id]["owner_evidence_ready"]
        ]
        manual_blockers = manual_by_scope.get(("edge", base_edge["edge_id"]), []) + manual_by_scope.get(("study", None), [])
        pilot_blockers = list(base_edge["pilot_blockers"]) + list(evidence["pilot_blockers"]) + endpoint_blockers + manual_blockers
        formal_blockers = list(base_edge["formal_blockers"]) + list(evidence["formal_blockers"]) + endpoint_blockers + manual_blockers
        if review["review_decision"] != "accepted":
            pilot_blockers.append("scientific_maturity_review_v2_not_accepted")
            formal_blockers.append("scientific_maturity_review_v2_not_accepted")
        edge_gates.append({
            "edge_id": base_edge["edge_id"], "stereochemical_channel": evidence["stereochemical_channel"],
            "start_minimum_id": base_edge["start_minimum_id"], "end_minimum_id": base_edge["end_minimum_id"],
            "pilot_node_ids": base_edge["pilot_node_ids"], "formal_ts_node_ids": base_edge["formal_ts_node_ids"],
            "pilot_scientifically_ready": base_edge["pilot_ts_input_scientifically_ready"] and not pilot_blockers,
            "formal_scientifically_ready": base_edge["formal_ts_input_scientifically_ready"] and not formal_blockers,
            "pilot_blockers": sorted(set(pilot_blockers)), "formal_blockers": sorted(set(formal_blockers)),
            "owner_ts_mode_evidence_valid": base_edge["owner_ts_mode_evidence_valid"],
            "owner_irc_path_evidence_valid": base_edge["owner_irc_path_evidence_valid"],
            "owner_energy_lineage_valid": base_edge["owner_energy_lineage_valid"],
            "ts_mode_accepted": base_edge["ts_mode_accepted"], "bidirectional_irc_accepted": base_edge["bidirectional_irc_accepted"],
            "irc_endpoints_reoptimized_as_expected_minima": base_edge["irc_endpoints_reoptimized_as_expected_minima"],
        })
    summary_blockers = sorted({code for edge in edge_gates for code in edge["formal_blockers"]} | {code for minimum in minimum_gates for code in minimum["blockers"]})
    return _finalize({
        "schema": GATE_SCHEMA, "study_id": review["study_id"], "review_id": review["review_id"],
        "base_gate": base_binding, "evidence_receipt": receipt_binding, "review_source": review_binding,
        "scientific_approval_summary": {
            "maturity": "reviewed" if not summary_blockers else "blocked", "blockers": summary_blockers,
            "calculation_ready": False, "no_submission_authorization": True,
        },
        "minimum_gates": minimum_gates, "edge_gates": edge_gates,
        "manual_evidence_authority": "supporting_only_no_gate_substitution_or_method_selection",
        "consumer_interface": {
            "function": "scientific_maturity_v2.assert_action",
            "actions": sorted(EDGE_ACTIONS), "requires_exact_edge_and_node": True,
            "unsupported_action_blockers": {
                "irc_input": "exact_owner_ts_mode_artifact_v2_required",
                "formal_barrier_reporting": "complete_owner_thermochemistry_evidence_v2_required",
            },
            "live_authority": False,
        },
        "calculation_ready": False, "no_submission_authorization": True,
        "no_method_selection_authorization": True, "no_input_generation_authorization": True,
    })


def build_gate(base_gate_path: Path, receipt_path: Path, review_path: Path, output: Path) -> dict[str, Any]:
    owners = _owners()
    owners["base"].validate_gate(base_gate_path)
    base, base_binding = _make_binding(base_gate_path, output.parent, BASE_GATE_SCHEMA)
    validate_evidence_receipt(receipt_path)
    receipt, receipt_binding = _make_binding(receipt_path, output.parent, EVIDENCE_RECEIPT_SCHEMA)
    review, review_binding = _make_binding(review_path, output.parent, REVIEW_SCHEMA)
    review = _normalize_review(review, require_hash=True)
    artifact = _build_gate(base, base_binding, receipt, receipt_binding, review, review_binding)
    _write(output, artifact)
    return artifact


def validate_gate(path: Path) -> dict[str, Any]:
    artifact = _load(path)
    require(artifact.get("schema") == GATE_SCHEMA, f"gate schema must be {GATE_SCHEMA}")
    require(artifact.get("payload_sha256") == _payload_sha256(artifact), "maturity gate /2 payload hash is invalid")
    base, base_path = _resolve(artifact["base_gate"], path, BASE_GATE_SCHEMA)
    _owners()["base"].validate_gate(base_path)
    receipt, receipt_path = _resolve(artifact["evidence_receipt"], path, EVIDENCE_RECEIPT_SCHEMA)
    validate_evidence_receipt(receipt_path)
    review, _ = _resolve(artifact["review_source"], path, REVIEW_SCHEMA)
    review = _normalize_review(review, require_hash=True)
    expected = _build_gate(base, artifact["base_gate"], receipt, artifact["evidence_receipt"], review, artifact["review_source"])
    require(artifact == expected, "maturity gate /2 differs from deterministic source reconstruction")
    return artifact


def _action_nodes(base_gate: dict[str, Any], edge: dict[str, Any], action: str, pilot: bool) -> dict[str, str]:
    plan, plan_path = _resolve(base_gate["calculation_plan"], Path(base_gate["__path"]), PLAN_SCHEMA)
    _owners()["plan"].validate_plan(plan_path)
    if action in {"ts_input", "ts_submission"}:
        exact_ids = set(edge["pilot_node_ids"] if pilot else edge["formal_ts_node_ids"])
        return {node["node_id"]: node["node_kind"] for node in plan["nodes"] if node["node_id"] in exact_ids}
    allowed_kinds = {"irc_forward", "irc_reverse"} if action == "irc_input" else {"thermochemistry"}
    return {
        node["node_id"]: node["node_kind"] for node in plan["nodes"]
        if node["disposition"] in {"planned", "retained"}
        and node["node_kind"] in allowed_kinds
        and node["target"]["edge_ids"] == [edge["edge_id"]]
        and (action != "formal_barrier_reporting" or any(output["artifact_role"] == "thermochemistry_evidence" for output in node["outputs"]))
    }


def _make_action(gate_path: Path, edge_id: str, node_id: str, action: str, pilot: bool, output: Path | None = None) -> dict[str, Any]:
    require(action in EDGE_ACTIONS, f"unsupported maturity /2 action: {action}")
    require(not pilot or action in {"ts_input", "ts_submission"}, "pilot exception applies only to TS input/submission")
    gate = validate_gate(gate_path)
    edge = next((item for item in gate["edge_gates"] if item["edge_id"] == edge_id), None)
    require(edge is not None, f"maturity gate /2 has no exact edge: {edge_id}")
    base_gate, base_path = _resolve(gate["base_gate"], gate_path, BASE_GATE_SCHEMA)
    base_gate["__path"] = str(base_path)
    allowed_nodes = _action_nodes(base_gate, edge, action, pilot)
    require(node_id in allowed_nodes, f"node {node_id} is not an exact {action} target for edge {edge_id}")
    if action in {"ts_input", "ts_submission"}:
        ready = edge["pilot_scientifically_ready"] if pilot else edge["formal_scientifically_ready"]
        blockers = edge["pilot_blockers"] if pilot else edge["formal_blockers"]
        require(ready, f"{action} is scientifically blocked for {edge_id}: {', '.join(blockers)}")
    elif action == "irc_input":
        raise EvidenceOverlayError("exact_owner_ts_mode_artifact_v2_required")
    else:
        raise EvidenceOverlayError("complete_owner_thermochemistry_evidence_v2_required")
    root = (output.parent if output is not None else gate_path.parent).absolute().resolve()
    _, gate_binding = _make_binding(gate_path, root, GATE_SCHEMA)
    return _finalize({
        "schema": ACTION_SCHEMA, "study_id": gate["study_id"], "scientific_maturity": gate_binding,
        "scope": {"edge_id": edge_id, "node_id": node_id, "node_kind": allowed_nodes[node_id], "action": action, "pilot": pilot},
        "scientific_gate_passed": True,
        "separate_input_review_still_required": action in {"ts_input", "ts_submission", "irc_input"},
        "separate_live_approval_still_required": action == "ts_submission",
        "reporting_scope_only": action == "formal_barrier_reporting",
        "single_exact_scope_only": True, "calculation_ready": False, "no_submission_authorization": True,
        "no_method_selection_authorization": True, "no_input_generation_authorization": True,
    })


def assert_action(gate_path: Path, edge_id: str, node_id: str, action: str, *, pilot: bool = False) -> dict[str, Any]:
    """Public fail-closed science check for later TS/PBS-family consumers."""
    return _make_action(gate_path, edge_id, node_id, action, pilot)


def build_action(gate_path: Path, edge_id: str, node_id: str, action: str, output: Path, *, pilot: bool = False) -> dict[str, Any]:
    artifact = _make_action(gate_path, edge_id, node_id, action, pilot, output)
    _write(output, artifact)
    return artifact


def validate_action(path: Path) -> dict[str, Any]:
    artifact = _load(path)
    require(artifact.get("schema") == ACTION_SCHEMA, f"action schema must be {ACTION_SCHEMA}")
    require(artifact.get("payload_sha256") == _payload_sha256(artifact), "maturity action /2 payload hash is invalid")
    gate, gate_path = _resolve(artifact["scientific_maturity"], path, GATE_SCHEMA)
    validate_gate(gate_path)
    scope = artifact["scope"]
    expected = _make_action(gate_path, scope["edge_id"], scope["node_id"], scope["action"], scope["pilot"], path)
    require(artifact == expected, "maturity action /2 differs from deterministic source reconstruction")
    return artifact


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    finalize_parser = commands.add_parser("finalize-review")
    finalize_parser.add_argument("draft", type=Path); finalize_parser.add_argument("--output", type=Path, required=True)
    receipt_parser = commands.add_parser("build-evidence-receipt")
    receipt_parser.add_argument("base_gate", type=Path); receipt_parser.add_argument("--review", type=Path, required=True); receipt_parser.add_argument("--output", type=Path, required=True)
    validate_receipt_parser = commands.add_parser("validate-evidence-receipt")
    validate_receipt_parser.add_argument("artifact", type=Path)
    gate_parser = commands.add_parser("build-gate")
    gate_parser.add_argument("base_gate", type=Path); gate_parser.add_argument("--evidence-receipt", type=Path, required=True); gate_parser.add_argument("--review", type=Path, required=True); gate_parser.add_argument("--output", type=Path, required=True)
    validate_gate_parser = commands.add_parser("validate-gate")
    validate_gate_parser.add_argument("artifact", type=Path)
    action_parser = commands.add_parser("build-action")
    action_parser.add_argument("gate", type=Path); action_parser.add_argument("--edge-id", required=True); action_parser.add_argument("--node-id", required=True); action_parser.add_argument("--action", choices=sorted(EDGE_ACTIONS), required=True); action_parser.add_argument("--pilot", action="store_true"); action_parser.add_argument("--output", type=Path, required=True)
    validate_action_parser = commands.add_parser("validate-action")
    validate_action_parser.add_argument("artifact", type=Path)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "finalize-review": artifact = finalize_review(args.draft, args.output)
        elif args.command == "build-evidence-receipt": artifact = build_evidence_receipt(args.base_gate, args.review, args.output)
        elif args.command == "validate-evidence-receipt": artifact = validate_evidence_receipt(args.artifact)
        elif args.command == "build-gate": artifact = build_gate(args.base_gate, args.evidence_receipt, args.review, args.output)
        elif args.command == "validate-gate": artifact = validate_gate(args.artifact)
        elif args.command == "build-action": artifact = build_action(args.gate, args.edge_id, args.node_id, args.action, args.output, pilot=args.pilot)
        else: artifact = validate_action(args.artifact)
    except (EvidenceOverlayError, OSError, ValueError, KeyError, TypeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"schema": artifact["schema"], "payload_sha256": artifact["payload_sha256"], "live_actions": False, "no_submission_authorization": True}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
