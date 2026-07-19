#!/usr/bin/env python3
"""Validate the non-authorizing Auto-G16 v2.5 cross-Skill approval chain.

This overlay replays the five owning validators and closes only these links:
method evidence -> explicit human method decision -> closure hard gates;
TS-seed portfolio -> closure initial-guess evidence; and selected closure
calculation nodes -> one reviewed execution-batch ledger.  It never creates an
input, reserves an attempt, submits work, or grants live authority.
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
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any


SCHEMA = "gaussian-v25-integration-review/1"
METHOD_BRIEF = "auto-g16-method-evidence-brief/1"
DISCUSSION = "gaussian-mechanism-discussion/1"
CLOSURE_PLAN = "gaussian-closure-priority-plan/1"
TS_PORTFOLIO = "gaussian-ts-seed-portfolio/1"
EXECUTION_REVIEW = "gaussian-execution-batch-review/1"
EXECUTION_LEDGER = "gaussian-execution-batch/1"
CALCULATION_STAGE_KINDS = {"ts_freq", "irc_forward", "irc_reverse", "endpoint_opt_freq"}
SHA_RE = re.compile(r"^[a-f0-9]{64}$")
ID_RE = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
AUTHORITY = {
    "calculation_ready": False,
    "executable": False,
    "no_submission_authorization": True,
    "no_automatic_promotion": True,
    "live_actions": False,
    "separate_input_review_required": True,
    "fresh_live_approval_required_per_attempt": True,
}


class IntegrationError(ValueError):
    """The v2.5 owner chain is incomplete or stale."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise IntegrationError(message)


def exact(value: Any, keys: set[str], label: str) -> dict[str, Any]:
    require(isinstance(value, dict), f"{label} must be an object")
    require(set(value) == keys, f"{label} fields differ: missing={sorted(keys - set(value))}, unknown={sorted(set(value) - keys)}")
    return value


def text(value: Any, label: str) -> str:
    require(isinstance(value, str) and value.strip() == value and bool(value), f"{label} must be a non-empty trimmed string")
    return value


def identifier(value: Any, label: str) -> str:
    require(isinstance(value, str) and ID_RE.fullmatch(value) is not None, f"{label} must be a stable lowercase ID")
    return value


def sha(value: Any, label: str) -> str:
    require(isinstance(value, str) and SHA_RE.fullmatch(value) is not None, f"{label} must be a lowercase SHA-256")
    return value


def canonical_sha(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def timestamp(value: Any, label: str) -> str:
    raw = text(value, label)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise IntegrationError(f"{label} must be an ISO-8601 timestamp") from exc
    require(parsed.tzinfo is not None and parsed.utcoffset() is not None, f"{label} must include a timezone")
    return raw


def payload_sha(value: dict[str, Any]) -> str:
    document = copy.deepcopy(value)
    document.pop("payload_sha256", None)
    return canonical_sha(document)


def objective_sha(plan_payload_sha256: str, node_id: str, stage_kind: str) -> str:
    """Return the exact execution identity for one selected closure node."""

    return canonical_sha({
        "closure_plan_payload_sha256": sha(plan_payload_sha256, "closure plan payload"),
        "node_id": identifier(node_id, "closure node_id"),
        "stage_kind": text(stage_kind, "closure stage_kind"),
    })


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


@lru_cache(maxsize=1)
def owners() -> dict[str, Any]:
    skill_root = Path(__file__).resolve().parents[2]
    return {
        "method": _load_module("auto_g16_v25_method_owner", skill_root / "auto-g16-knowledge-base" / "scripts" / "method_evidence.py"),
        "decision": _load_module("auto_g16_v25_decision_owner", Path(__file__).with_name("human_scientific_decision.py")),
        "closure": _load_module("auto_g16_v25_closure_owner", Path(__file__).with_name("closure_priority.py")),
        "seed": _load_module("auto_g16_v25_seed_owner", skill_root / "auto-g16-ts-seed" / "scripts" / "ts_seed_core.py"),
        "batch": _load_module("auto_g16_v25_batch_owner", skill_root / "auto-g16-rtwin-pbs" / "scripts" / "execution_batch.py"),
    }


def load_json(path: Path) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            require(key not in result, f"duplicate JSON key is not permitted: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=lambda raw: (_ for _ in ()).throw(IntegrationError(f"non-finite JSON value: {raw}")),
            object_pairs_hook=reject_duplicates,
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise IntegrationError(f"cannot read JSON {path}: {exc}") from exc
    require(isinstance(value, dict), f"top-level JSON must be an object: {path}")
    return value


def strict_file(root: Path, relative_text: str, label: str) -> Path:
    relative = Path(text(relative_text, f"{label}.path"))
    require(not relative.is_absolute() and ".." not in relative.parts, f"{label}.path must be portable and relative")
    resolved_root = root.resolve(strict=True)
    require(resolved_root.is_dir() and not root.is_symlink(), "integration root must be a real directory")
    current = resolved_root
    for part in relative.parts:
        current = current / part
        try:
            mode = os.lstat(current).st_mode
        except FileNotFoundError as exc:
            raise IntegrationError(f"{label} is unavailable: {relative}") from exc
        require(not stat.S_ISLNK(mode), f"{label} path contains a symlink")
    resolved = current.resolve(strict=True)
    require(resolved.is_file() and resolved.is_relative_to(resolved_root), f"{label} must remain a regular file below the integration root")
    return resolved


def artifact_digest(document: dict[str, Any]) -> str:
    if document.get("schema") == EXECUTION_LEDGER:
        return sha(document.get("ledger_sha256"), "ledger_sha256")
    return sha(document.get("payload_sha256"), "payload_sha256")


def resolve_binding(root: Path, value: Any, expected_schema: str, label: str) -> tuple[dict[str, Any], Path]:
    binding = exact(value, {"path", "sha256", "size_bytes", "schema", "artifact_sha256"}, label)
    require(binding["schema"] == expected_schema, f"{label}.schema must be {expected_schema}")
    path = strict_file(root, binding["path"], label)
    require(isinstance(binding["size_bytes"], int) and binding["size_bytes"] >= 0, f"{label}.size_bytes is invalid")
    require(path.stat().st_size == binding["size_bytes"], f"{label} size changed")
    require(hashlib.sha256(path.read_bytes()).hexdigest() == sha(binding["sha256"], f"{label}.sha256"), f"{label} file hash changed")
    document = load_json(path)
    require(document.get("schema") == expected_schema, f"{label} schema changed")
    require(artifact_digest(document) == sha(binding["artifact_sha256"], f"{label}.artifact_sha256"), f"{label} artifact hash changed")
    return document, path


def make_binding(path: Path, root: Path) -> dict[str, Any]:
    resolved_root = root.resolve(strict=True)
    resolved = path.resolve(strict=True)
    require(resolved.is_file() and resolved.is_relative_to(resolved_root), "bound artifact must be below the integration root")
    document = load_json(resolved)
    return {
        "path": resolved.relative_to(resolved_root).as_posix(),
        "sha256": hashlib.sha256(resolved.read_bytes()).hexdigest(),
        "size_bytes": resolved.stat().st_size,
        "schema": text(document.get("schema"), "bound artifact schema"),
        "artifact_sha256": artifact_digest(document),
    }


def _validate_owner_documents(root: Path, artifacts: dict[str, Any]) -> dict[str, tuple[dict[str, Any], Path]]:
    expected = {
        "method_evidence_brief": METHOD_BRIEF,
        "mechanism_discussion": DISCUSSION,
        "closure_priority_plan": CLOSURE_PLAN,
        "ts_seed_portfolios": None,
        "execution_batch_review": EXECUTION_REVIEW,
        "execution_batch_ledger": EXECUTION_LEDGER,
    }
    exact(artifacts, set(expected), "artifacts")
    resolved: dict[str, tuple[dict[str, Any], Path]] = {}
    for key, schema_name in expected.items():
        if key == "ts_seed_portfolios":
            continue
        resolved[key] = resolve_binding(root, artifacts[key], schema_name, f"artifacts.{key}")
    portfolios = artifacts["ts_seed_portfolios"]
    require(isinstance(portfolios, list) and portfolios, "artifacts.ts_seed_portfolios must be non-empty")
    for index, binding in enumerate(portfolios):
        resolved[f"ts_seed_portfolios[{index}]"] = resolve_binding(root, binding, TS_PORTFOLIO, f"artifacts.ts_seed_portfolios[{index}]")

    method, _ = resolved["method_evidence_brief"]
    discussion, _ = resolved["mechanism_discussion"]
    plan, _ = resolved["closure_priority_plan"]
    review, _ = resolved["execution_batch_review"]
    ledger, _ = resolved["execution_batch_ledger"]
    owner = owners()
    owner["method"].validate_brief(method)
    owner["decision"].validate_discussion(root, discussion)
    owner["closure"].validate_plan_document(plan)
    for key, (portfolio, path) in resolved.items():
        if key.startswith("ts_seed_portfolios["):
            owner["seed"].validate_portfolio(portfolio, path)
    owner["batch"].validate_review(review)
    owner["batch"].validate_ledger(ledger)
    return resolved


def validate_document(root: Path, document: dict[str, Any], *, require_hash: bool = True) -> dict[str, Any]:
    exact(document, {"schema", "integration_id", "study_id", "artifacts", "method_decision", "route_bindings", "review", "authority", "payload_sha256"}, "integration review")
    require(document["schema"] == SCHEMA, f"integration review schema must be {SCHEMA}")
    identifier(document["integration_id"], "integration_id")
    identifier(document["study_id"], "study_id")
    if require_hash:
        require(document["payload_sha256"] == payload_sha(document), "integration review payload hash is invalid")
    else:
        require(document["payload_sha256"] is None, "integration draft payload_sha256 must be null")
    require(document["authority"] == AUTHORITY, "integration authority boundary changed")
    review_meta = exact(document["review"], {"status", "reviewer", "reviewed_at", "notes"}, "review")
    require(review_meta["status"] == "reviewed_non_authorizing", "integration review status is invalid")
    text(review_meta["reviewer"], "review.reviewer")
    timestamp(review_meta["reviewed_at"], "review.reviewed_at")
    require(isinstance(review_meta["notes"], list) and review_meta["notes"], "review.notes must be non-empty")
    for index, note in enumerate(review_meta["notes"]):
        text(note, f"review.notes[{index}]")

    resolved = _validate_owner_documents(root, document["artifacts"])
    method, _ = resolved["method_evidence_brief"]
    discussion, _ = resolved["mechanism_discussion"]
    plan, _ = resolved["closure_priority_plan"]
    execution_review, _ = resolved["execution_batch_review"]
    ledger, _ = resolved["execution_batch_ledger"]
    portfolios = {item[0]["payload_sha256"]: item[0] for key, item in resolved.items() if key.startswith("ts_seed_portfolios[")}
    require(len(portfolios) == len(document["artifacts"]["ts_seed_portfolios"]), "TS-seed portfolio bindings must be unique")

    require(document["study_id"] == discussion["study_id"] == plan["study_id"], "study IDs differ across decision and closure owners")
    decision = exact(document["method_decision"], {"claim_id", "alternative_id", "method_protocol_sha256"}, "method_decision")
    identifier(decision["claim_id"], "method_decision.claim_id")
    identifier(decision["alternative_id"], "method_decision.alternative_id")
    method_protocol = sha(decision["method_protocol_sha256"], "method_decision.method_protocol_sha256")
    confirmed = discussion["user_decision"]
    require(confirmed["decision"] == "confirm_selected", "method routing requires a current explicit user confirmation")
    require(any(
        claim["claim_type"] == "method" and claim["claim_id"] == decision["claim_id"] and claim["alternative_id"] == decision["alternative_id"]
        for claim in confirmed["confirmed_claims"]
    ), "method brief is not followed by the declared explicit human method decision")
    require(any(
        item["schema"] == METHOD_BRIEF and item["payload_sha256"] == method["payload_sha256"]
        for item in discussion["sources"]["evidence"]
    ), "mechanism discussion does not bind the exact method-evidence brief")

    route_bindings = document["route_bindings"]
    require(isinstance(route_bindings, list) and route_bindings, "route_bindings must be non-empty")
    by_route: dict[str, dict[str, Any]] = {}
    mapped_tasks: dict[str, tuple[str, str]] = {}
    for index, raw in enumerate(route_bindings):
        item = exact(raw, {"route_id", "mechanism_discussion_payload_sha256", "method_evidence_brief_payload_sha256", "ts_seed_portfolio_payload_sha256", "node_task_bindings"}, f"route_bindings[{index}]")
        route_id = identifier(item["route_id"], f"route_bindings[{index}].route_id")
        require(route_id not in by_route, "route bindings contain duplicate route IDs")
        require(item["mechanism_discussion_payload_sha256"] == discussion["payload_sha256"], f"{route_id}: mechanism-discussion binding is stale")
        require(item["method_evidence_brief_payload_sha256"] == method["payload_sha256"], f"{route_id}: method-evidence binding is stale")
        portfolio_sha = sha(item["ts_seed_portfolio_payload_sha256"], f"{route_id}.ts_seed_portfolio_payload_sha256")
        require(portfolio_sha in portfolios, f"{route_id}: TS-seed portfolio is not in the owner set")
        portfolio = portfolios[portfolio_sha]
        require(portfolio["target_id"] == route_id, f"{route_id}: TS-seed portfolio target_id must equal the closure route_id")
        node_bindings = item["node_task_bindings"]
        require(isinstance(node_bindings, list) and node_bindings, f"{route_id}: node_task_bindings must be non-empty")
        normalized_nodes: dict[str, str] = {}
        for mapping in node_bindings:
            pair = exact(mapping, {"node_id", "scientific_task_id"}, f"{route_id}.node_task_binding")
            node_id = identifier(pair["node_id"], f"{route_id}.node_id")
            task_id = text(pair["scientific_task_id"], f"{route_id}.scientific_task_id")
            require(node_id not in normalized_nodes and task_id not in mapped_tasks, "closure node/task mappings must be one-to-one")
            normalized_nodes[node_id] = task_id
            mapped_tasks[task_id] = (route_id, node_id)
        item = copy.deepcopy(item)
        item["node_task_bindings"] = normalized_nodes
        item["portfolio"] = portfolio
        by_route[route_id] = item

    selected_routes = {route["route_id"]: route for route in plan["routes"] if route["selected"] is True}
    require(set(by_route) == set(selected_routes), "integration route bindings must cover exactly the selected closure routes")
    method_token = f"{METHOD_BRIEF}:{method['payload_sha256']}"
    discussion_token = f"{DISCUSSION}:{discussion['payload_sha256']}"
    for route_id, route in selected_routes.items():
        binding = by_route[route_id]
        require(all(gate["status"] == "pass" for gate in route["hard_gates"].values()), f"{route_id}: every closure hard gate must pass")
        require(discussion_token in route["hard_gates"]["reviewed_mechanism_and_active_state"]["evidence_refs"], f"{route_id}: mechanism hard gate lacks the exact discussion")
        require(discussion_token in route["hard_gates"]["user_confirmation"]["evidence_refs"], f"{route_id}: user-confirmation hard gate lacks the exact discussion")
        method_refs = route["hard_gates"]["method_evidence_and_explicit_method_decision"]["evidence_refs"]
        require(method_token in method_refs and discussion_token in method_refs, f"{route_id}: method hard gate must bind both evidence brief and explicit decision")
        portfolio_token = f"{TS_PORTFOLIO}:{binding['portfolio']['payload_sha256']}"
        require(route["dimensions"]["initial_guess_quality"]["calibration"]["provenance"] == portfolio_token, f"{route_id}: initial-guess evidence is not the exact TS-seed portfolio")
        expected_nodes = {
            stage["node_id"]: stage["stage_kind"]
            for stage in route["bundle"]["stages"]
            if stage["stage_kind"] in CALCULATION_STAGE_KINDS
        }
        require(set(binding["node_task_bindings"]) == set(expected_nodes), f"{route_id}: execution mapping must cover every selected calculation node exactly once")

    review_tasks = {task["scientific_task_id"]: task for task in execution_review["tasks"]}
    ledger_tasks = {task["scientific_task_id"]: task for task in ledger["tasks"]}
    require(len(review_tasks) <= owners()["batch"].MAX_DISTINCT_TASKS, "execution batch exceeds the ten-task cap")
    require(set(mapped_tasks) == set(review_tasks) == set(ledger_tasks), "execution review and ledger must contain exactly the selected closure tasks")
    require(ledger["batch"]["review_sha256"] == execution_review["payload_sha256"], "execution ledger is not bound to the exact immutable review")
    for task_id, (route_id, node_id) in mapped_tasks.items():
        route = selected_routes[route_id]
        stage = next(stage for stage in route["bundle"]["stages"] if stage["node_id"] == node_id)
        identity = review_tasks[task_id]["identity"]
        require(identity["chemical_hypothesis_sha256"] == discussion["confirmation_scope_sha256"], f"{node_id}: chemical hypothesis is not the explicit discussion scope")
        require(identity["method_protocol_sha256"] == method_protocol, f"{node_id}: method protocol differs from the explicit method decision")
        require(identity["calculation_objective_sha256"] == objective_sha(plan["payload_sha256"], node_id, stage["stage_kind"]), f"{node_id}: calculation objective is not bound to the closure node")
        if stage["stage_kind"] == "ts_freq":
            primary = next(entry for entry in by_route[route_id]["portfolio"]["entries"] if entry["role"] == "primary")
            require(identity["structure_sha256"] == primary["geometry_sha256"], f"{node_id}: TS task structure is not the primary seed geometry")
        require(ledger_tasks[task_id]["identity"] == identity, f"{node_id}: ledger identity differs from immutable execution review")

    return {
        "valid": True,
        "schema": SCHEMA,
        "payload_sha256": document.get("payload_sha256"),
        "selected_route_count": len(selected_routes),
        "selected_task_count": len(mapped_tasks),
        "max_distinct_scientific_tasks": owners()["batch"].MAX_DISTINCT_TASKS,
        "live_actions": False,
        "no_submission_authorization": True,
    }


def finalize(root: Path, draft_path: Path, output_path: Path) -> dict[str, Any]:
    require(not output_path.is_absolute() and ".." not in output_path.parts, "output path must be portable and relative")
    document = load_json(strict_file(root, draft_path.as_posix(), "integration draft"))
    validate_document(root, document, require_hash=False)
    finalized = copy.deepcopy(document)
    finalized["payload_sha256"] = payload_sha(finalized)
    validate_document(root, finalized)
    output = root.resolve(strict=True) / output_path
    require(not output.exists() and not output.is_symlink(), f"refusing to overwrite output: {output_path}")
    require(output.parent.is_dir() and not output.parent.is_symlink() and output.resolve().parent.is_relative_to(root.resolve(strict=True)), "output parent must remain below the integration root")
    with output.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(finalized, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n")
    return finalized


def parser() -> argparse.ArgumentParser:
    main = argparse.ArgumentParser(description=__doc__)
    sub = main.add_subparsers(dest="command", required=True)
    finalize_parser = sub.add_parser("finalize", help="finalize one reviewed non-authorizing integration draft")
    finalize_parser.add_argument("--root", type=Path, required=True)
    finalize_parser.add_argument("draft", type=Path)
    finalize_parser.add_argument("--output", type=Path, required=True)
    validate_parser = sub.add_parser("validate", help="replay one finalized integration review")
    validate_parser.add_argument("--root", type=Path, required=True)
    validate_parser.add_argument("artifact", type=Path)
    return main


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        root = args.root.resolve(strict=True)
        if args.command == "finalize":
            result = finalize(root, args.draft, args.output)
            summary = validate_document(root, result)
        else:
            path = strict_file(root, args.artifact.as_posix(), "integration artifact")
            summary = validate_document(root, load_json(path))
    except (IntegrationError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
