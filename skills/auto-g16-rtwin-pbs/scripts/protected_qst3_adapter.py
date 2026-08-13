#!/usr/bin/env python3
"""Hash-bound protected QST3 input/live successor for the sole legacy owner.

The adapter closes the specialist evidence for one formal or exact
84-atom endpoint-anchored candidate closed-shell QST3+Freq input.  It owns no
transport or qsub surface.  The separately
versioned legacy successor remains the only production effect owner and may
consume the exact receipt/live projections exposed here.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import math
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


INPUT_SCHEMA = "gaussian-input-approval-receipt/5"
LIVE_SCHEMA = "auto-g16-live-submission-approval/13"
MATURITY_ACTION_SCHEMA = "gaussian-scientific-maturity-action/2"
ACTION_AUTHORIZATION_SCHEMA = "gaussian-scientific-action-authorization/2"
WORKFLOW = "protected_qst3_ts_freq_input_v1"
FIXED_REMOTE_ROOT = "/home/user100/SDL"
ENDPOINT_ANCHORED_TS_CANDIDATE = "endpoint_anchored_ts_candidate"
QST3_WORK_KINDS = {"formal_ts", ENDPOINT_ANCHORED_TS_CANDIDATE}
PROJECT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,14}$")
SHA_RE = re.compile(r"^[a-f0-9]{64}$")
COORDINATE_EQUIVALENCE = {
    "scheme": "absolute_cartesian_tolerance/1",
    "unit": "angstrom",
    "absolute_tolerance": 1e-8,
    "relative_tolerance": 0.0,
}


class ProtectedQST3Error(ValueError):
    """The exact specialist chain cannot be proved."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ProtectedQST3Error(message)


def _load_module(name: str, path: Path) -> Any:
    _require(path.is_file() and not path.is_symlink(), f"exact owner source is unavailable: {path}")
    spec = importlib.util.spec_from_file_location(name, path)
    _require(spec is not None and spec.loader is not None, f"exact owner cannot be loaded: {path}")
    module = importlib.util.module_from_spec(spec)
    owner_dir = str(path.parent)
    added = owner_dir not in sys.path
    if added:
        sys.path.insert(0, owner_dir)
    try:
        spec.loader.exec_module(module)
    finally:
        if added:
            sys.path.remove(owner_dir)
    _require(Path(module.__file__).resolve() == path.resolve(), f"owner origin changed: {path}")
    return module


def _owner_paths() -> tuple[Path, Path, Path]:
    source = Path(__file__).resolve()
    skill_root = source.parent.parent
    repository_root = source.parents[3]
    repository_skills = source.parents[2]
    dependency_skills = skill_root / "dependencies" / "skills"

    repository_marker = repository_root / "scripts" / "skill_package.py"
    repository_paths = (
        source.with_name("legacy_rtwin_pbs.py"),
        repository_skills / "auto-g16-ts-irc" / "scripts" / "ts_irc.py",
        repository_skills
        / "auto-g16-reaction-workflow"
        / "scripts"
        / "scientific_maturity_v2.py",
    )
    packaged_paths = (
        source.with_name("legacy_rtwin_pbs.py"),
        dependency_skills / "auto-g16-ts-irc" / "scripts" / "ts_irc.py",
        dependency_skills
        / "auto-g16-reaction-workflow"
        / "scripts"
        / "scientific_maturity_v2.py",
    )
    repository_present = repository_marker.exists()
    packaged_present = (skill_root / "dependencies").exists()
    for candidate in (
        source,
        skill_root,
        repository_marker,
        dependency_skills,
        *repository_paths,
        *packaged_paths,
    ):
        if os.path.lexists(candidate) and candidate.is_symlink():
            raise ProtectedQST3Error(
                "protected QST3 owner layout contains a symlink"
            )
    repository_complete = repository_present and all(
        path.is_file() for path in repository_paths
    )
    packaged_complete = packaged_present and all(
        path.is_file() for path in packaged_paths
    )
    _require(
        not (repository_present and not repository_complete),
        "protected QST3 repository owner layout is partial",
    )
    _require(
        not (packaged_present and not packaged_complete),
        "protected QST3 named-Skill dependency layout is partial",
    )
    _require(
        repository_complete != packaged_complete,
        "protected QST3 requires exactly one repository or named-Skill owner layout",
    )
    return repository_paths if repository_complete else packaged_paths


def _owners() -> tuple[Any, Any, Any]:
    legacy_path, ts_path, maturity_path = _owner_paths()
    legacy = _load_module(
        "auto_g16_qst3_frozen_legacy_owner",
        legacy_path,
    )
    ts = _load_module(
        "auto_g16_qst3_ts_owner",
        ts_path,
    )
    maturity = _load_module(
        "auto_g16_qst3_maturity_owner",
        maturity_path,
    )
    return legacy, ts, maturity


def _load(path: Path) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8")
    return json.loads(raw, parse_constant=lambda token: (_ for _ in ()).throw(ProtectedQST3Error(f"non-finite JSON token: {token}")), object_pairs_hook=_closed_object)


def _closed_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        _require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _exact(value: Any, fields: set[str], label: str) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == fields, f"{label} fields differ")
    return value


def _source(path: Path, root: Path, schema: str, payload_sha256: str, legacy: Any) -> dict[str, Any]:
    lexical = Path(os.path.abspath(path))
    try:
        relative = lexical.relative_to(root)
    except ValueError:
        raise ProtectedQST3Error(f"{schema} source escapes the artifact root") from None
    _require(not relative.is_absolute() and ".." not in relative.parts, f"{schema} source path is not portable")
    resolved = legacy._resolve_portable_binding_path(
        relative.as_posix(), root / ".qst3-receipt-owner", schema
    )
    _require(resolved.is_file(), f"{schema} source is missing")
    return {
        "path": relative.as_posix(),
        "sha256": legacy.sha256(resolved),
        "size_bytes": resolved.stat().st_size,
        "schema": schema,
        "payload_sha256": payload_sha256,
    }


def _resolve(binding: Any, owner_path: Path, schema: str, legacy: Any) -> tuple[Path, dict[str, Any]]:
    value = _exact(binding, {"path", "sha256", "size_bytes", "schema", "payload_sha256"}, schema)
    _require(value["schema"] == schema, f"{schema} binding schema differs")
    path = legacy._resolve_portable_binding_path(value["path"], owner_path, schema)
    document = _load(path)
    _require(
        legacy.sha256(path) == value["sha256"]
        and path.stat().st_size == value["size_bytes"],
        f"{schema} bytes changed",
    )
    return path, document


def _bind_mechanism_atom_identity(
    endpoint_lineages: dict[str, Any], declared_atom_map: Any,
) -> dict[str, Any]:
    reactant_ids = endpoint_lineages["reactant"]["stable_atom_ids"]
    product_ids = endpoint_lineages["product"]["stable_atom_ids"]
    _require(
        isinstance(declared_atom_map, list)
        and len(declared_atom_map) == len(reactant_ids)
        and sorted(declared_atom_map) == list(range(1, len(declared_atom_map) + 1)),
        "QST3 declared atom map is not a complete one-to-one index map",
    )
    mechanism_mapping = endpoint_lineages.get("atom_mapping")
    _require(
        isinstance(mechanism_mapping, list) and mechanism_mapping,
        "maturity endpoint projection lacks the mechanism atom map",
    )
    mapping_dict = {
        item.get("from_atom_id"): item.get("to_atom_id")
        for item in mechanism_mapping
        if isinstance(item, dict)
    }
    index_bindings: list[dict[str, Any]] = []
    for reactant_index, product_index in enumerate(declared_atom_map, start=1):
        reactant_atom_id = reactant_ids[reactant_index - 1]
        product_atom_id = product_ids[product_index - 1]
        mechanism_to_atom_id = mapping_dict.get(reactant_atom_id)
        _require(
            mechanism_to_atom_id == product_atom_id,
            "QST3 atom-index map differs from the exact mechanism edge atom identity mapping",
        )
        index_bindings.append({
            "reactant_index": reactant_index,
            "reactant_stable_atom_id": reactant_atom_id,
            "product_index": product_index,
            "product_stable_atom_id": product_atom_id,
            "mechanism_to_atom_id": mechanism_to_atom_id,
        })
    return {
        "schema": "gaussian-qst3-mechanism-atom-identity/1",
        "declared_atom_map": copy.deepcopy(declared_atom_map),
        "reviewed_guess_index_basis": "reactant",
        "index_bindings": index_bindings,
    }


def _coordinate_atoms(value: Any, label: str) -> list[tuple[Any, ...]]:
    _require(isinstance(value, list) and value, f"{label} atoms are missing")
    result: list[tuple[Any, ...]] = []
    for atom in value:
        _require(isinstance(atom, dict), f"{label} atom is malformed")
        element = atom.get("element")
        coordinates = (atom.get("x"), atom.get("y"), atom.get("z"))
        _require(
            isinstance(element, str)
            and element != ""
            and all(
                isinstance(coordinate, (int, float))
                and not isinstance(coordinate, bool)
                for coordinate in coordinates
            ),
            f"{label} atom element or coordinates are malformed",
        )
        result.append(
            (
                element,
                float(coordinates[0]),
                float(coordinates[1]),
                float(coordinates[2]),
            )
        )
    return result


def _coordinates_equivalent(left: Any, right: Any, label: str) -> bool:
    left_atoms = _coordinate_atoms(left, f"QST3 {label}")
    right_atoms = _coordinate_atoms(right, f"minimum {label}")
    if len(left_atoms) != len(right_atoms):
        return False
    tolerance = COORDINATE_EQUIVALENCE["absolute_tolerance"]
    return all(
        left_atom[0] == right_atom[0]
        and all(
            math.isclose(
                left_atom[index], right_atom[index],
                rel_tol=0.0, abs_tol=tolerance,
            )
            for index in (1, 2, 3)
        )
        for left_atom, right_atom in zip(left_atoms, right_atoms)
    )


def _expected_raw_endpoint_rows(
    endpoint_lineages: dict[str, Any], role: str,
    declared_atom_map: list[int],
) -> list[dict[str, Any]]:
    coordinates = endpoint_lineages[role]["coordinates"]
    if role == "reactant":
        return coordinates
    _require(role == "product", "QST3 endpoint role is unsupported")
    return [coordinates[index - 1] for index in declared_atom_map]


def _require_raw_endpoint_row_order(
    audited: dict[str, Any], endpoint_lineages: dict[str, Any],
    role: str, declared_atom_map: list[int],
) -> None:
    endpoint = endpoint_lineages[role]
    expected_rows = _expected_raw_endpoint_rows(
        endpoint_lineages, role, declared_atom_map
    )
    _require(
        audited["charge"] == endpoint["charge"]
        and audited["multiplicity"] == endpoint["multiplicity"]
        and _coordinates_equivalent(audited["atoms"], expected_rows, role),
        f"QST3 {role} raw row order/coordinates are not equivalent to the accepted maturity /2 minimum lineage under the declared atom map and 1e-8 angstrom absolute tolerance",
    )


def _replay_sources(
    *,
    qst_audit_path: Path,
    family_path: Path,
    input_action_path: Path,
    submission_action_path: Path,
    action_authorization_path: Path,
    input_path: Path,
    report: dict[str, Any],
    resource_tier: str,
    work_kind: str,
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
]:
    _legacy, ts, maturity = _owners()
    audit = ts.validate_qst_raw_audit_artifact(qst_audit_path)
    _require(
        audit.get("audit_status") == "syntax_verified_for_installed_revision"
        and audit.get("syntax_runnable_claim") == "verified_for_installed_revision"
        and audit.get("input_family") == "qst3"
        and audit.get("structure_count") == 3
        and audit.get("qst3_third_structure", {}).get("reviewed_guess_confirmed") is True
        and audit.get("qst3_third_structure", {}).get("minimum_claim_allowed") is False,
        "raw QST3 audit is not installed-revision verified with a reviewed non-minimum guess",
    )
    _require(
        audit["raw_input"]["sha256"] == report["input_sha256"]
        and audit["route"] == report["route"]
        and all(item.get("atom_count") == report["atom_count"] for item in audit["structures"]),
        "raw QST3 audit differs from the exact input",
    )
    family = ts.validate_family_artifact(family_path)
    expected_pilot = work_kind == ENDPOINT_ANCHORED_TS_CANDIDATE
    _require(work_kind in QST3_WORK_KINDS, "protected QST3 work kind is unsupported")
    _require(
        family.get("pilot") is expected_pilot
        and family.get("input_audit", {}).get("entry_mode") == "qst3"
        and family["input_audit"].get("valid") is True
        and family.get("protocol", {}).get("routes", {}).get("ts_freq") == report["route"]
        and family.get("protocol", {}).get("resource_tiers", {}).get("ts_freq") == resource_tier,
        "protected TS-family differs from the exact QST3 route/resource tier",
    )
    _, atom_map = ts.resolve_qst_atom_map_audit(qst_audit_path, audit)
    _require(atom_map == family["input_audit"], "raw QST3 audit and family bind different atom maps")
    input_action = maturity.validate_action(input_action_path)
    submission_action = maturity.validate_action(submission_action_path)
    input_scope = input_action["scope"]
    submission_scope = submission_action["scope"]
    _require(
        input_scope["action"] == "ts_input"
        and submission_scope["action"] == "ts_submission"
        and input_scope["pilot"] is expected_pilot
        and submission_scope["pilot"] is expected_pilot
        and input_scope["edge_id"] == submission_scope["edge_id"] == family["mechanism_edge_id"]
        and input_scope["node_id"] == submission_scope["node_id"] == family["dag_node_id"]
        and input_action["scientific_maturity"] == submission_action["scientific_maturity"] == family["scientific_maturity"],
        "maturity actions differ from the protected TS-family",
    )
    authorization = maturity.validate_action_authorization(
        action_authorization_path,
        maturity_action_path=submission_action_path,
        input_sha256=report["input_sha256"],
        edge_id=submission_scope["edge_id"],
        node_id=submission_scope["node_id"],
        work_kind=work_kind,
        resource_tier=resource_tier,
    )
    input_endpoints = maturity.resolve_ts_endpoint_minimum_lineages(
        input_action_path
    )
    submission_endpoints = maturity.resolve_ts_endpoint_minimum_lineages(
        submission_action_path
    )
    _require(
        input_endpoints == submission_endpoints,
        "TS input/submission actions bind different endpoint minima",
    )

    atom_identity_mapping = _bind_mechanism_atom_identity(
        input_endpoints, atom_map.get("atom_map")
    )
    declared_atom_map = atom_identity_mapping["declared_atom_map"]

    for role in ("reactant", "product"):
        audited = atom_map["structures"][role]
        _require_raw_endpoint_row_order(
            audited, input_endpoints, role, declared_atom_map
        )
    return (
        audit,
        family,
        input_action,
        submission_action,
        authorization,
        input_endpoints,
        atom_identity_mapping,
    )


def _make_receipt(
    options_path: Path,
    selection_path: Path,
    review_path: Path,
    input_path: Path,
    qst_audit_path: Path,
    family_path: Path,
    input_action_path: Path,
    submission_action_path: Path,
    action_authorization_path: Path,
    output_path: Path,
    receipt_id: str,
) -> dict[str, Any]:
    legacy, _ts, _maturity = _owners()
    selection, options, selected = legacy.protocol_selection.load_validated_selection(selection_path, options_path)
    review = legacy.validate_input_review(review_path)
    report = legacy.parse_gaussian(input_path)
    _require(type(receipt_id) is str and receipt_id.strip() != "", "receipt_id is missing")
    _require(review["work_kind"] in QST3_WORK_KINDS, "QST3 receipt /5 work kind is unsupported")
    _require(
        review["protocol_task_types"] == ["transition_state_optimization", "harmonic_frequency"],
        "QST3 receipt requires TS optimization plus harmonic frequency",
    )
    _require(review["approved_input"] == legacy._input_approval_facts(report), "input review differs from exact QST3 input")
    legacy._validate_protocol_consumption(review["protocol_binding"], options_path, selection_path, selection, options, selected)
    legacy._replay_route_profile_mapping(review, selected)
    legacy._assert_protocol_structure_scope(options["request_snapshot"]["structure"], report)
    resources = selected["resources"]
    expected_pilot = review["work_kind"] == ENDPOINT_ANCHORED_TS_CANDIDATE
    _require(
        report["multiplicity"] == 1
        and resources["cores"] == report["nprocshared"]
        and int(float(resources["mem_gb"]) * 1024**3) == legacy.parse_memory(report["mem"]),
        "QST3 input electronic state or resources differ from the selected protocol",
    )
    if expected_pilot:
        _require(
            resources["resource_tier"] == "general"
            and resources["cores"] == 22
            and resources["mem_gb"] == 50
            and report["atom_count"] == 84,
            "endpoint-anchored TS candidate requires exact 84-atom general 22-core/50-GB resources",
        )
    (
        audit,
        family,
        input_action,
        submission_action,
        authorization,
        endpoint_lineages,
        atom_identity_mapping,
    ) = _replay_sources(
        qst_audit_path=qst_audit_path,
        family_path=family_path,
        input_action_path=input_action_path,
        submission_action_path=submission_action_path,
        action_authorization_path=action_authorization_path,
        input_path=input_path,
        report=report,
        resource_tier=resources["resource_tier"],
        work_kind=review["work_kind"],
    )
    candidate_search = authorization.get("candidate_search")
    if expected_pilot:
        _require(
            isinstance(candidate_search, dict)
            and candidate_search.get("schema") == "gaussian-endpoint-anchored-ts-candidate-scope/1"
            and candidate_search.get("endpoint_minimum_ids")
            == [
                endpoint_lineages["reactant"]["minimum_id"],
                endpoint_lineages["product"]["minimum_id"],
            ]
            and candidate_search.get("atom_count") == report["atom_count"] == 84
            and candidate_search.get("resource_tier") == resources["resource_tier"] == "general"
            and candidate_search.get("task_limit") == 1
            and candidate_search.get("automatic_retry") is False
            and candidate_search.get("mechanism_claim_authorized") is False
            and candidate_search.get("accepted_ts_claim_authorized") is False,
            "endpoint-anchored TS candidate claim/resource boundary is incomplete",
        )
    else:
        _require(candidate_search is None, "formal TS receipt must not carry a candidate-search exception")
    root = output_path.parent.resolve(strict=True)
    maturity_projection = {
        "schema": MATURITY_ACTION_SCHEMA,
        "edge_id": submission_action["scope"]["edge_id"],
        "node_id": submission_action["scope"]["node_id"],
        "pilot": expected_pilot,
        "maturity_gate_sha256": submission_action["scientific_maturity"]["sha256"],
        "maturity_gate_payload_sha256": submission_action["scientific_maturity"]["payload_sha256"],
        "scientific_action_authorization_sha256": legacy.sha256(action_authorization_path),
        "scientific_action_authorization_payload_sha256": authorization["payload_sha256"],
    }
    document = {
        "schema": INPUT_SCHEMA,
        "receipt_id": receipt_id,
        "work_kind": review["work_kind"],
        "protocol_task_types": copy.deepcopy(review["protocol_task_types"]),
        "sources": {
            "protocol_options": _source(options_path, root, "gaussian-protocol-options/1", options["proposal_payload_sha256"], legacy),
            "protocol_selection": _source(selection_path, root, "gaussian-protocol-selection/1", selection["selection_payload_sha256"], legacy),
            "input_review": _source(review_path, root, legacy.INPUT_REVIEW_SCHEMA, review["payload_sha256"], legacy),
            "qst_raw_input_audit": _source(qst_audit_path, root, "gaussian-qst-raw-input-syntax-audit/1", audit["audit_payload_sha256"], legacy),
            "ts_family": _source(family_path, root, "gaussian-ts-irc-workflow/2", legacy.canonical_value_sha256(family), legacy),
            "ts_input_action": _source(input_action_path, root, MATURITY_ACTION_SCHEMA, input_action["payload_sha256"], legacy),
            "ts_submission_action": _source(submission_action_path, root, MATURITY_ACTION_SCHEMA, submission_action["payload_sha256"], legacy),
            "scientific_action_authorization": _source(action_authorization_path, root, ACTION_AUTHORIZATION_SCHEMA, authorization["payload_sha256"], legacy),
        },
        "input": legacy._input_blob_binding(input_path, root),
        "protocol_review_binding": {
            "input_review_payload_sha256": review["payload_sha256"],
            "options_payload_sha256": review["protocol_binding"]["options_payload_sha256"],
            "selection_payload_sha256": review["protocol_binding"]["selection_payload_sha256"],
            "selected_option_payload_sha256": review["protocol_binding"]["selected_option"]["option_payload_sha256"],
            "consumed_profile_ids": copy.deepcopy(review["protocol_binding"]["used_profile_ids"]),
            "consumed_task_indices": [item["task_index"] for item in review["protocol_binding"]["used_tasks"]],
            "exact_route": report["route"],
            "route_profile_mapping_sha256": legacy.canonical_value_sha256(review["route_profile_mapping"]),
            "explicit_confirmation": True,
        },
        "specialist_owner_binding": {
            "owner": "auto-g16-ts-irc", "workflow": WORKFLOW,
            "work_kind": review["work_kind"],
            "candidate_search": copy.deepcopy(candidate_search),
            "qst_raw_audit_payload_sha256": audit["audit_payload_sha256"],
            "ts_family_sha256": legacy.sha256(family_path),
            "ts_input_action_payload_sha256": input_action["payload_sha256"],
            "ts_submission_action_payload_sha256": submission_action["payload_sha256"],
            "scientific_action_authorization_sha256": legacy.sha256(action_authorization_path),
            "scientific_action_authorization_payload_sha256": authorization["payload_sha256"],
            "selected_option_payload_sha256": review["protocol_binding"]["selected_option"]["option_payload_sha256"],
            "project": authorization["scope"]["project"],
            "input_sha256": report["input_sha256"], "exact_route": report["route"],
            "input_family": "qst3", "structure_count": 3, "atom_count": report["atom_count"],
            "charge": report["charge"], "multiplicity": report["multiplicity"],
            "scientific_maturity": maturity_projection,
            "endpoint_minimum_lineages": endpoint_lineages,
            "atom_identity_mapping": atom_identity_mapping,
            "coordinate_equivalence": copy.deepcopy(COORDINATE_EQUIVALENCE),
            "authorized_budget": {
                key: authorization["scope"][key]
                for key in (
                    "task_count",
                    "estimated_core_hours",
                    "planned_concurrency",
                )
            },
            "resources": {"resource_tier": resources["resource_tier"], "mem_gb": resources["mem_gb"], "cores": resources["cores"]},
            "owner_replay_passed": True,
        },
        "protocol_family_completion": False,
        "approved_input": legacy._input_approval_facts(report),
        "decision": {"status": "approved_exact_input", "explicit_confirmation": True},
        "single_exact_input_only": True,
        "calculation_ready": False,
        "no_submission_authorization": True,
    }
    document["payload_sha256"] = legacy.contract_payload_sha256(document)
    return document


def build_receipt(**paths: Any) -> dict[str, Any]:
    output = Path(paths.pop("output_path")).expanduser()
    output = output.parent.resolve(strict=True) / output.name
    _require(not output.exists() and not output.is_symlink(), f"refusing to overwrite receipt: {output}")
    normalized = {name: Path(value).expanduser().resolve(strict=True) for name, value in paths.items() if name.endswith("_path")}
    receipt_id = paths["receipt_id"]
    document = _make_receipt(output_path=output, receipt_id=receipt_id, **normalized)
    legacy, _ts, _maturity = _owners()
    legacy.publish_new_json(output, document, validate_receipt)
    return document


def validate_receipt(path: Path) -> dict[str, Any]:
    legacy, _ts, _maturity = _owners()
    document = _load(path)
    _require(document.get("schema") == INPUT_SCHEMA, f"receipt schema must be {INPUT_SCHEMA}")
    sources = document.get("sources", {})
    source_specs = {
        "protocol_options": "gaussian-protocol-options/1", "protocol_selection": "gaussian-protocol-selection/1",
        "input_review": legacy.INPUT_REVIEW_SCHEMA, "qst_raw_input_audit": "gaussian-qst-raw-input-syntax-audit/1",
        "ts_family": "gaussian-ts-irc-workflow/2", "ts_input_action": MATURITY_ACTION_SCHEMA,
        "ts_submission_action": MATURITY_ACTION_SCHEMA, "scientific_action_authorization": ACTION_AUTHORIZATION_SCHEMA,
    }
    _exact(sources, set(source_specs), "receipt sources")
    resolved = {name: _resolve(sources[name], path, schema, legacy)[0] for name, schema in source_specs.items()}
    input_path = legacy._resolve_input_blob(document["input"], path)
    expected = _make_receipt(
        options_path=resolved["protocol_options"], selection_path=resolved["protocol_selection"],
        review_path=resolved["input_review"], input_path=input_path,
        qst_audit_path=resolved["qst_raw_input_audit"], family_path=resolved["ts_family"],
        input_action_path=resolved["ts_input_action"], submission_action_path=resolved["ts_submission_action"],
        action_authorization_path=resolved["scientific_action_authorization"], output_path=path,
        receipt_id=document["receipt_id"],
    )
    _require(document == expected, "receipt differs from deterministic owner reconstruction")
    return document


def expected_live_scope(
    receipt_path: Path,
    input_path: Path,
    project: str,
    execution: dict[str, Any],
) -> dict[str, Any]:
    legacy, _ts, _maturity = _owners()
    receipt = validate_receipt(receipt_path)
    report = legacy.parse_gaussian(input_path)
    owner = receipt["specialist_owner_binding"]
    _require(PROJECT_RE.fullmatch(project) is not None and owner["project"] == project, "project differs from action authorization")
    _require(receipt["input"]["sha256"] == report["input_sha256"], "receipt input differs from live input")
    _exact(
        execution,
        {
            "batch_id", "review_sha256", "scientific_task_id", "attempt_id",
            "idempotency_key", "estimated_core_hours",
            "estimated_core_hours_evidence", "resource_binding",
        },
        "execution binding",
    )
    _exact(
        execution["estimated_core_hours_evidence"],
        {"source", "sha256"},
        "estimated core-hour evidence",
    )
    resource = _exact(execution["resource_binding"], {"policy_id", "policy_sha256", "gate_id", "gate_sha256", "resource_tier", "cores", "memory_gb", "walltime_seconds"}, "execution resource binding")
    budget = _exact(
        owner["authorized_budget"],
        {"task_count", "estimated_core_hours", "planned_concurrency"},
        "authorized budget",
    )
    _require(
        resource["resource_tier"] == owner["resources"]["resource_tier"]
        and resource["cores"] == owner["resources"]["cores"]
        and resource["memory_gb"] == owner["resources"]["mem_gb"],
        "live resources differ from QST3 receipt",
    )
    _require(
        type(resource["walltime_seconds"]) is int
        and resource["walltime_seconds"] > 0
        and type(execution["estimated_core_hours"]) in {int, float}
        and not isinstance(execution["estimated_core_hours"], bool)
        and float(execution["estimated_core_hours"])
        == float(budget["estimated_core_hours"])
        and budget["task_count"] == 1
        and type(budget["planned_concurrency"]) is int
        and budget["planned_concurrency"] >= 1,
        "live execution differs from the exact action-authorized budget/walltime",
    )
    maturity = owner["scientific_maturity"]
    return {
        "project": project, "remote_workdir": f"{FIXED_REMOTE_ROOT}/{project}",
        "input_sha256": report["input_sha256"], "route": report["route"], "mem": report["mem"],
        "nprocshared": report["nprocshared"], "charge": report["charge"], "multiplicity": report["multiplicity"],
        "work_kind": receipt["work_kind"],
        "input_approval": {"schema": INPUT_SCHEMA, "sha256": legacy.sha256(receipt_path), "payload_sha256": receipt["payload_sha256"], "input_sha256": report["input_sha256"], "work_kind": receipt["work_kind"]},
        "ts_qst_owner": copy.deepcopy(owner),
        "scientific_maturity": {key: maturity[key] for key in ("edge_id", "pilot", "maturity_gate_sha256", "maturity_gate_payload_sha256", "node_id", "scientific_action_authorization_sha256", "scientific_action_authorization_payload_sha256")},
        "operation": "submit", "execution": copy.deepcopy(execution),
    }


def validate_live_approval(path: Path, expected_scope: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    legacy, _ts, _maturity = _owners()
    document = _load(path)
    _exact(document, {"schema", "approval_id", "approver_identity", "approved_at", "expires_at", "decision", "explicit_confirmation", "scope", "revocation", "consumption", "authorizations"}, "live approval /13")
    _require(document["schema"] == LIVE_SCHEMA and document["decision"] == "approved" and document["explicit_confirmation"] is True, "live approval /13 decision differs")
    _require(
        type(document["approval_id"]) is str and document["approval_id"] != ""
        and type(document["approver_identity"]) is str and document["approver_identity"] != "",
        "live approval /13 identity is missing",
    )
    _require(document["scope"] == expected_scope, "live approval /13 scope differs from exact preflight")
    _require(document["revocation"] == {"revoked": False, "revoked_at": None, "reason": None}, "live approval /13 is revoked or malformed")
    _require(document["consumption"] == {"single_use": True, "consumed": False}, "live approval /13 consumption differs")
    _require(document["authorizations"] == {"create_server_directory": True, "submit": True, "retry": False, "cancel": False, "cleanup": False, "delete_server_data": False}, "live approval /13 authority differs")
    current = now or datetime.now(timezone.utc)
    try:
        approved = legacy.execution_batch.parse_time(document["approved_at"])
        expires = legacy.execution_batch.parse_time(document["expires_at"])
    except Exception as exc:
        raise ProtectedQST3Error(f"live approval /13 timestamp is invalid: {exc}") from exc
    _require(approved <= current < expires, "live approval /13 is outside its active time window")
    return document


def production_effect_status() -> dict[str, Any]:
    """Report that this module owns evidence, never the physical effect."""

    return {
        "schema": "auto-g16-protected-qst3-production-effect-status/1",
        "input_receipt_schema": INPUT_SCHEMA,
        "live_approval_schema": LIVE_SCHEMA,
        "historical_legacy_fixture_rewritten": False,
        "parallel_effect_owner_created": False,
        "production_submit_wired": False,
        "production_effect_owner": None,
        "qsub_calls": 0,
        "live_actions_performed": False,
        "blocker": "protected_qst3_production_entry_not_connected",
    }


def submit_once(*_args: Any, **_kwargs: Any) -> None:
    raise ProtectedQST3Error(
        "the QST3 adapter owns no qsub surface; use the separately reviewed sole legacy production entry"
    )
