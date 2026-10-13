#!/usr/bin/env python3
"""Build and audit a hash-bound, non-executable main-group open-shell network."""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
import re
import sys
from pathlib import Path
from typing import Any


REVIEW_SCHEMA = "gaussian-reaction-open-shell-network-review/1"
OUTPUT_SCHEMA = "gaussian-reaction-open-shell-network/1"
STATE_REVIEW_SCHEMA = "auto-g16-main-group-open-shell-review/1"
ID_RE = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
SUPPORTED_FAMILIES = {"doublet_ground_state", "high_spin_triplet_ground_state", "triplet_carbene"}
SUPPORTED_MULTIPLICITIES = {2, 3}


class ContractError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n").encode()


def payload_sha256(value: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_bytes({k: v for k, v in value.items() if k != "payload_sha256"})).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(token: str) -> None:
    raise ContractError(f"non-finite JSON value is forbidden: {token}")


def _input_path(value: str | Path, label: str) -> Path:
    path = Path(os.path.abspath(Path(value).expanduser()))
    for component in (path, *path.parents):
        require(not component.is_symlink(), f"{label} path contains a symlink")
    require(path.is_file(), f"{label} must be an existing file")
    return path.resolve()


def load_json(value: str | Path, label: str, *, canonical: bool = False) -> tuple[Path, dict[str, Any]]:
    path = _input_path(value, label)
    raw = path.read_bytes()
    try:
        data = json.loads(raw.decode(), object_pairs_hook=_pairs, parse_constant=_reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot parse {label}: {exc}") from exc
    require(isinstance(data, dict), f"{label} root must be an object")
    if canonical:
        require(raw == canonical_bytes(data), f"{label} must use canonical JSON")
    return path, data


def _exact(value: Any, fields: set[str], label: str) -> dict[str, Any]:
    require(isinstance(value, dict), f"{label} must be an object")
    require(set(value) == fields, f"{label} fields mismatch; missing={sorted(fields-set(value))} unknown={sorted(set(value)-fields)}")
    return value


def _id(value: Any, label: str) -> str:
    require(isinstance(value, str) and ID_RE.fullmatch(value) is not None, f"{label} is invalid")
    return value


def _text(value: Any, label: str) -> str:
    require(isinstance(value, str) and value.strip(), f"{label} must be non-empty")
    return value.strip()


def _integer(value: Any, label: str, *, positive: bool = False) -> int:
    require(isinstance(value, int) and not isinstance(value, bool), f"{label} must be an integer")
    require(not positive or value > 0, f"{label} must be positive")
    return value


def _binding(value: Any, root: Path, schema: str, label: str) -> tuple[dict[str, Any], dict[str, Any], Path]:
    binding = _exact(value, {"path", "sha256", "size_bytes", "schema", "payload_sha256"}, label)
    relative = Path(_text(binding["path"], f"{label}.path"))
    require(not relative.is_absolute() and ".." not in relative.parts, f"{label}.path must be portable and relative")
    path = _input_path(root / relative, label)
    require(path.is_relative_to(root.resolve()), f"{label} escapes the artifact root")
    require(binding["schema"] == schema, f"{label}.schema mismatch")
    require(binding["sha256"] == file_sha256(path), f"{label} file hash drift")
    require(binding["size_bytes"] == path.stat().st_size, f"{label} size drift")
    _, artifact = load_json(path, label, canonical=True)
    require(artifact.get("schema") == schema, f"{label} artifact schema mismatch")
    if "payload_sha256" in artifact:
        bound_payload = artifact["payload_sha256"]
        require(bound_payload == payload_sha256(artifact), f"{label} payload hash drift")
    elif schema == "gaussian-protocol-selection/1":
        bound_payload = artifact.get("selection_payload_sha256")
        require(SHA_RE.fullmatch(str(bound_payload)) is not None, f"{label} selection payload hash is invalid")
    else:
        bound_payload = hashlib.sha256(canonical_bytes(artifact)).hexdigest()
    require(binding["payload_sha256"] == bound_payload, f"{label} payload binding drift")
    return copy.deepcopy(binding), artifact, path


def _load_open_shell_owner() -> Any:
    path = Path(__file__).resolve().parents[2] / "auto-g16-main-group-open-shell" / "scripts" / "open_shell_state.py"
    spec = importlib.util.spec_from_file_location("auto_g16_open_shell_owner", path)
    require(spec is not None and spec.loader is not None, "open-shell owner validator is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_protocol_owner() -> Any:
    path = Path(__file__).resolve().parents[2] / "auto-g16-rtwin-pbs" / "scripts" / "protocol_selection.py"
    spec = importlib.util.spec_from_file_location("auto_g16_protocol_owner", path)
    require(spec is not None and spec.loader is not None, "protocol owner validator is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _normalize_review(review: dict[str, Any], root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    fields = {"schema", "study_id", "network_id", "surface_review", "protocol_lineages", "states", "edges", "nodes", "review_decision", "reviewer", "reviewed_at", "review_notes", "calculation_ready", "no_submission_authorization"}
    _exact(review, fields, "open-shell network review")
    require(review["schema"] == REVIEW_SCHEMA, "review schema mismatch")
    study_id, network_id = _id(review["study_id"], "study_id"), _id(review["network_id"], "network_id")
    require(review["review_decision"] == "accepted", "network review must be explicitly accepted")
    require(review["calculation_ready"] is False and review["no_submission_authorization"] is True, "review authority boundary changed")
    require(isinstance(review["review_notes"], list) and all(isinstance(item, str) for item in review["review_notes"]), "review_notes must be an array of strings")
    surface = _exact(review["surface_review"], {"multiplicity", "state_family", "electronic_scope", "crossing_excluded", "reviewer", "rationale"}, "surface_review")
    multiplicity = _integer(surface["multiplicity"], "surface multiplicity", positive=True)
    require(multiplicity in SUPPORTED_MULTIPLICITIES, "V1 supports only doublet or high-spin triplet surfaces")
    require(surface["state_family"] in SUPPORTED_FAMILIES, "surface state family is outside V1")
    require(surface["electronic_scope"] == "single_reference_ground_state", "surface must be reviewed single-reference ground state")
    require(surface["crossing_excluded"] is True, "spin crossing and MECP must be explicitly excluded")
    _text(surface["reviewer"], "surface reviewer"); _text(surface["rationale"], "surface rationale")

    protocols: dict[str, dict[str, Any]] = {}
    protocol_owner = _load_protocol_owner()
    require(isinstance(review["protocol_lineages"], list) and review["protocol_lineages"], "protocol_lineages must be a non-empty array")
    for index, raw in enumerate(review["protocol_lineages"]):
        item = _exact(raw, {"lineage_id", "protocol_selection", "candidate_id", "state_review_payload_sha256", "status", "reviewer", "rationale"}, f"protocol_lineages[{index}]")
        lineage_id = _id(item["lineage_id"], "lineage_id")
        require(lineage_id not in protocols, "duplicate protocol lineage")
        require(item["status"] in {"reviewed", "unresolved"}, "protocol lineage status is invalid")
        if item["status"] == "reviewed":
            require(item["protocol_selection"] is not None, "reviewed protocol lineage requires an exact artifact")
        else:
            require(item["protocol_selection"] is None, "unresolved protocol lineage cannot bind an artifact")
        if item["protocol_selection"] is not None:
            _, selection, selection_path = _binding(item["protocol_selection"], root, "gaussian-protocol-selection/1", f"protocol lineage {lineage_id}")
            protocol_owner.load_validated_selection(selection_path)
            require(selection["scope_binding"].get("electronic_state_review_payload_sha256") == item["state_review_payload_sha256"], f"protocol lineage {lineage_id} does not bind the exact electronic-state review")
        _id(item["candidate_id"], "protocol candidate_id")
        require(SHA_RE.fullmatch(str(item["state_review_payload_sha256"])) is not None, "protocol state-review hash is invalid")
        _text(item["reviewer"], "protocol reviewer"); _text(item["rationale"], "protocol rationale")
        protocols[lineage_id] = copy.deepcopy(item)

    owner = _load_open_shell_owner()
    states: dict[str, dict[str, Any]] = {}
    diagnostics: list[dict[str, Any]] = []
    require(isinstance(review["states"], list) and len(review["states"]) >= 2, "states must contain at least two reviewed states")
    for index, raw in enumerate(review["states"]):
        item = _exact(raw, {"state_id", "structure", "candidate", "state_review", "atom_ids", "fragment_spin_coupling", "protocol_lineage_id"}, f"states[{index}]")
        state_id = _id(item["state_id"], "state_id")
        require(state_id not in states, "duplicate state_id")
        structure = _exact(item["structure"], {"path", "sha256"}, f"state {state_id}.structure")
        structure_path = _input_path(root / Path(_text(structure["path"], "structure.path")), "structure")
        require(structure_path.is_relative_to(root.resolve()), "structure escapes artifact root")
        require(structure["sha256"] == file_sha256(structure_path), f"state {state_id} structure hash drift")
        candidate_binding, candidate, _ = _binding(item["candidate"], root, "auto-g16-main-group-open-shell-candidate/1", f"state {state_id}.candidate")
        state_binding, state_review, _ = _binding(item["state_review"], root, STATE_REVIEW_SCHEMA, f"state {state_id}.state_review")
        owner.validate_review(state_review, check_sources=True)
        require(state_review["status"] == "accepted" and state_review["conclusion"]["decision"] == "accepted_for_v1_protocol_gate", f"state {state_id} review is not V1 accepted")
        require(state_review["candidate_snapshot"] == candidate, f"state {state_id} candidate/review drift")
        require(all(atom["element"] in owner.MAIN_GROUP_SYMBOLS for atom in candidate["atoms"]), f"state {state_id} contains a metal or non-main-group element")
        require(candidate["structure_sha256"] == structure["sha256"], f"state {state_id} structure/candidate hash drift")
        require(candidate["multiplicity"] == multiplicity and candidate["state_family"] == surface["state_family"], f"state {state_id} is on a different electronic-state surface")
        require(candidate["electronic_scope"] == "single_reference_ground_state", f"state {state_id} is not single-reference")
        require(candidate["multiplicity"] in SUPPORTED_MULTIPLICITIES, f"state {state_id} multiplicity is outside V1")
        atom_ids = item["atom_ids"]
        require(isinstance(atom_ids, list) and len(atom_ids) == len(candidate["atoms"]), f"state {state_id} atom_ids must cover the candidate")
        require(len(set(atom_ids)) == len(atom_ids) and all(ID_RE.fullmatch(str(v)) for v in atom_ids), f"state {state_id} atom_ids are invalid")
        coupling = _exact(item["fragment_spin_coupling"], {"status", "total_multiplicity", "fragments", "coupling_model", "reviewer", "rationale"}, f"state {state_id}.fragment_spin_coupling")
        require(coupling["status"] == "reviewed", f"state {state_id} fragment spin coupling is unresolved")
        require(coupling["total_multiplicity"] == multiplicity, f"state {state_id} reviewed total multiplicity drift")
        require(isinstance(coupling["fragments"], list) and coupling["fragments"], f"state {state_id} fragments are missing")
        covered: list[str] = []
        for fragment in coupling["fragments"]:
            _exact(fragment, {"fragment_id", "atom_ids", "multiplicity"}, "fragment")
            _id(fragment["fragment_id"], "fragment_id"); _integer(fragment["multiplicity"], "fragment multiplicity", positive=True)
            require(isinstance(fragment["atom_ids"], list) and fragment["atom_ids"], "fragment atom_ids are missing")
            covered.extend(fragment["atom_ids"])
        require(sorted(covered) == sorted(atom_ids) and len(covered) == len(set(covered)), f"state {state_id} fragments must partition atoms exactly")
        _text(coupling["coupling_model"], "coupling model"); _text(coupling["reviewer"], "coupling reviewer"); _text(coupling["rationale"], "coupling rationale")
        lineage_id = _id(item["protocol_lineage_id"], "protocol_lineage_id")
        require(lineage_id in protocols, f"state {state_id} references unknown protocol lineage")
        lineage = protocols[lineage_id]
        require(lineage["candidate_id"] == candidate["candidate_id"] and lineage["state_review_payload_sha256"] == state_review["payload_sha256"], f"state {state_id} protocol lineage drift")
        atoms = [{"atom_id": atom_id, "index": atom["index"], "element": atom["element"]} for atom_id, atom in zip(atom_ids, candidate["atoms"])]
        states[state_id] = {"state_id": state_id, "structure": copy.deepcopy(structure), "candidate": candidate_binding, "state_review": state_binding, "candidate_id": candidate["candidate_id"], "formal_charge": candidate["charge"], "multiplicity": candidate["multiplicity"], "state_family": candidate["state_family"], "electronic_scope": candidate["electronic_scope"], "atoms": atoms, "electron_count": state_review["electron_accounting"]["electron_count"], "fragment_spin_coupling": copy.deepcopy(coupling), "protocol_lineage_id": lineage_id}
        diagnostics.append({"state_id": state_id, "candidate_hash_bound": True, "structure_hash_bound": True, "state_review_hash_bound": True, "electron_parity_consistent": state_review["electron_accounting"]["multiplicity_parity_consistent"], "surface_consistent": True, "coupling_human_reviewed": True})

    edges: dict[str, dict[str, Any]] = {}
    edge_diagnostics: list[dict[str, Any]] = []
    require(isinstance(review["edges"], list) and review["edges"], "edges must be a non-empty array")
    for index, raw in enumerate(review["edges"]):
        item = _exact(raw, {"edge_id", "from_state_id", "to_state_id", "atom_mapping", "total_multiplicity_review", "fragment_spin_coupling_review", "candidate_lineage", "protocol_lineage_ids"}, f"edges[{index}]")
        edge_id = _id(item["edge_id"], "edge_id")
        require(edge_id not in edges, "duplicate edge_id")
        source, target = states.get(item["from_state_id"]), states.get(item["to_state_id"])
        require(source is not None and target is not None and source is not target, f"edge {edge_id} states are invalid")
        mapping = item["atom_mapping"]
        require(isinstance(mapping, list) and mapping, f"edge {edge_id} atom mapping is missing")
        forward: dict[str, str] = {}
        source_elements = {a["atom_id"]: a["element"] for a in source["atoms"]}; target_elements = {a["atom_id"]: a["element"] for a in target["atoms"]}
        for pair in mapping:
            _exact(pair, {"from_atom_id", "to_atom_id"}, "atom mapping")
            require(pair["from_atom_id"] not in forward and pair["to_atom_id"] not in forward.values(), f"edge {edge_id} atom mapping is not one-to-one")
            require(source_elements.get(pair["from_atom_id"]) == target_elements.get(pair["to_atom_id"]) and source_elements.get(pair["from_atom_id"]) is not None, f"edge {edge_id} atom mapping changes element identity")
            forward[pair["from_atom_id"]] = pair["to_atom_id"]
        require(set(forward) == set(source_elements) and set(forward.values()) == set(target_elements), f"edge {edge_id} atom mapping must be complete")
        total_review = _exact(item["total_multiplicity_review"], {"status", "multiplicity", "reviewer", "rationale"}, "total multiplicity review")
        require(total_review["status"] == "reviewed" and total_review["multiplicity"] == multiplicity, f"edge {edge_id} total multiplicity must be human reviewed on the common surface")
        coupling_review = _exact(item["fragment_spin_coupling_review"], {"status", "reviewer", "rationale"}, "edge coupling review")
        require(coupling_review["status"] == "reviewed", f"edge {edge_id} fragment coupling is unresolved")
        _text(coupling_review["reviewer"], "edge coupling reviewer"); _text(coupling_review["rationale"], "edge coupling rationale")
        lineage = _exact(item["candidate_lineage"], {"from_candidate_id", "to_candidate_id"}, "candidate lineage")
        require(lineage == {"from_candidate_id": source["candidate_id"], "to_candidate_id": target["candidate_id"]}, f"edge {edge_id} candidate lineage drift")
        protocol_ids = item["protocol_lineage_ids"]
        require(isinstance(protocol_ids, list) and sorted(protocol_ids) == sorted({source["protocol_lineage_id"], target["protocol_lineage_id"]}), f"edge {edge_id} protocol lineage drift")
        element_conserved = sorted(source_elements.values()) == sorted(target_elements.values())
        charge_conserved = source["formal_charge"] == target["formal_charge"]
        electrons_conserved = source["electron_count"] == target["electron_count"]
        require(element_conserved, f"edge {edge_id} does not conserve elements")
        require(charge_conserved, f"edge {edge_id} does not conserve total charge")
        require(electrons_conserved, f"edge {edge_id} does not conserve electron count")
        edges[edge_id] = copy.deepcopy(item)
        edge_diagnostics.append({"edge_id": edge_id, "atom_mapping_complete": True, "elements_conserved": True, "charge_conserved": True, "electron_count_conserved": True, "same_reviewed_surface": True, "total_multiplicity_human_reviewed": True, "fragment_coupling_human_reviewed": True})

    nodes: dict[str, dict[str, Any]] = {}
    require(isinstance(review["nodes"], list) and review["nodes"], "nodes must be a non-empty array")
    for index, raw in enumerate(review["nodes"]):
        item = _exact(raw, {"node_id", "node_kind", "state_ids", "edge_ids", "candidate_bindings", "state_review_bindings", "protocol_lineage_ids", "depends_on", "executable"}, f"nodes[{index}]")
        node_id = _id(item["node_id"], "node_id")
        require(node_id not in nodes and item["node_kind"] in {"minimum", "complex", "ts_candidate", "ts_freq", "irc_forward", "irc_reverse", "endpoint", "single_point", "thermochemistry", "sensitivity"}, "node identity or kind invalid")
        require(item["executable"] is False, "all open-shell DAG nodes must be non-executable")
        require(isinstance(item["state_ids"], list) and item["state_ids"] and set(item["state_ids"]) <= set(states), f"node {node_id} state targets are invalid")
        require(isinstance(item["edge_ids"], list) and set(item["edge_ids"]) <= set(edges), f"node {node_id} edge targets are invalid")
        expected_candidates = sorted(states[v]["candidate_id"] for v in item["state_ids"])
        expected_reviews = sorted(states[v]["state_review"]["payload_sha256"] for v in item["state_ids"])
        expected_protocols = sorted({states[v]["protocol_lineage_id"] for v in item["state_ids"]})
        require(sorted(item["candidate_bindings"]) == expected_candidates, f"node {node_id} candidate bindings drift")
        require(sorted(item["state_review_bindings"]) == expected_reviews, f"node {node_id} state review bindings drift")
        require(sorted(item["protocol_lineage_ids"]) == expected_protocols, f"node {node_id} protocol lineage drift")
        require(isinstance(item["depends_on"], list) and len(item["depends_on"]) == len(set(item["depends_on"])), f"node {node_id} dependencies are invalid")
        nodes[node_id] = copy.deepcopy(item)
    for node_id, item in nodes.items():
        require(set(item["depends_on"]) <= set(nodes) and node_id not in item["depends_on"], f"node {node_id} dependency is invalid")
    pending, done = set(nodes), set()
    order: list[str] = []
    while pending:
        ready = sorted(node for node in pending if set(nodes[node]["depends_on"]) <= done)
        require(ready, "calculation nodes contain a cycle")
        order.extend(ready); done.update(ready); pending.difference_update(ready)

    normalized = {"schema": REVIEW_SCHEMA, "study_id": study_id, "network_id": network_id, "surface_review": copy.deepcopy(surface), "protocol_lineages": [protocols[k] for k in sorted(protocols)], "states": [states[k] for k in sorted(states)], "edges": [edges[k] for k in sorted(edges)], "nodes": [nodes[k] for k in sorted(nodes)], "topological_order": order, "review_decision": "accepted", "reviewer": _text(review["reviewer"], "reviewer"), "reviewed_at": _text(review["reviewed_at"], "reviewed_at"), "review_notes": review["review_notes"], "calculation_ready": False, "no_submission_authorization": True}
    return normalized, [{"states": diagnostics, "edges": edge_diagnostics}]


def build(review_path: str | Path) -> dict[str, Any]:
    path, review = load_json(review_path, "open-shell network review")
    normalized, packed = _normalize_review(review, path.parent)
    artifact = copy.deepcopy(normalized)
    artifact["schema"] = OUTPUT_SCHEMA
    artifact["review_source"] = {"path": path.name, "sha256": file_sha256(path), "size_bytes": path.stat().st_size}
    artifact["diagnostics"] = packed[0]
    artifact["handoff"] = {"kind": "hash_bound_non_executable_calculation_dag", "ts_authorized": False, "irc_authorized": False, "execution_authorized": False, "energy_ranking_authorized": False}
    artifact["payload_sha256"] = payload_sha256(artifact)
    return artifact


def validate(path_value: str | Path) -> dict[str, Any]:
    path, artifact = load_json(path_value, "open-shell network artifact", canonical=True)
    require(artifact.get("schema") == OUTPUT_SCHEMA, "artifact schema mismatch")
    require(artifact.get("payload_sha256") == payload_sha256(artifact), "artifact payload hash drift")
    review_source = _exact(artifact.get("review_source"), {"path", "sha256", "size_bytes"}, "review_source")
    review_path = _input_path(path.parent / review_source["path"], "review source")
    require(review_path.parent == path.parent and review_source["sha256"] == file_sha256(review_path) and review_source["size_bytes"] == review_path.stat().st_size, "review source drift")
    rebuilt = build(review_path)
    require(rebuilt == artifact, "artifact differs from deterministic owner-backed reconstruction")
    return {"schema": "gaussian-reaction-open-shell-network-validation/1", "artifact_schema": OUTPUT_SCHEMA, "study_id": artifact["study_id"], "network_id": artifact["network_id"], "state_count": len(artifact["states"]), "edge_count": len(artifact["edges"]), "node_count": len(artifact["nodes"]), "payload_sha256": artifact["payload_sha256"], "live_actions": False}


def write_new(path_value: str | Path, value: dict[str, Any]) -> None:
    path = Path(os.path.abspath(Path(path_value)))
    require(not path.exists() and not path.is_symlink(), f"refusing to overwrite output: {path}")
    require(path.parent.is_dir() and not path.parent.is_symlink(), "output parent must be an existing real directory")
    with path.open("xb") as handle:
        handle.write(canonical_bytes(value))


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    build_parser = commands.add_parser("build", help="build the audited non-executable open-shell network")
    build_parser.add_argument("review"); build_parser.add_argument("--output", required=True)
    validate_parser = commands.add_parser("validate", help="replay and validate an open-shell network artifact")
    validate_parser.add_argument("artifact")
    return root


def main(argv: list[str] | None = None) -> int:
    try:
        args = parser().parse_args(argv)
        if args.command == "build":
            review_path = _input_path(args.review, "open-shell network review")
            require(Path(os.path.abspath(args.output)).parent.resolve() == review_path.parent, "output and review must share one portable artifact root")
            artifact = build(args.review); write_new(args.output, artifact)
            result = {"schema": "gaussian-reaction-open-shell-network-build/1", "output": str(Path(args.output).resolve()), "payload_sha256": artifact["payload_sha256"], "live_actions": False}
        else:
            result = validate(args.artifact)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (ContractError, OSError, TypeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
