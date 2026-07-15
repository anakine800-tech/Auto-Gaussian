#!/usr/bin/env python3
"""Offline adapters between reviewed candidates, inputs, results, and targets.

This module is deliberately local and non-operational.  It never parses a raw
Gaussian log, contacts SSH/PBS, creates a server directory, or authorizes a
submission.  Candidate, protocol, Gaussian-input, and TS semantics remain
owned by their specialist modules and are called through narrow validators.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import math
import os
import re
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
SCRIPT_DIR = Path(__file__).resolve().parent
RTWIN_SCRIPTS = ROOT / "skills" / "auto-g16-rtwin-pbs" / "scripts"
TS_SCRIPTS = ROOT / "skills" / "auto-g16-ts-irc" / "scripts"
ASYM_SCRIPT = ROOT / "skills" / "auto-g16-asymmetric-catalysis" / "scripts" / "asymmetric_catalysis.py"
ASYM_VALIDATOR = ROOT / "scripts" / "validate_asymmetric_contract.py"

for directory in (SCRIPT_DIR, RTWIN_SCRIPTS, TS_SCRIPTS):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

import reaction_workflow as rw  # noqa: E402
import protocol_selection as protocol  # noqa: E402
import gaussian_rtwin_pbs as rtwin  # noqa: E402
import ts_irc as ts_irc  # noqa: E402


def _load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load specialist module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


asym = _load_module("calculation_artifact_asymmetric", ASYM_SCRIPT)
asym_contract = _load_module("calculation_artifact_asymmetric_contract", ASYM_VALIDATOR)


TARGET_IMPORT_SCHEMA = "gaussian-candidate-target-import/1"
INPUT_REVIEW_SCHEMA = "gaussian-input-draft-review/1"
INPUT_HANDOFF_SCHEMA = "gaussian-candidate-input-handoff/1"
ENERGY_REVIEW_SCHEMA = "gaussian-energy-review/1"
ENERGY_RECORD_SCHEMA = "gaussian-reviewed-energy-record/1"
ENERGY_LINEAGE_SCHEMA = "gaussian-energy-lineage/1"
SANITIZED_JOB_SCHEMA = "gaussian-sanitized-job-observation/1"
ATTEMPT_LINK_SCHEMA = "gaussian-calculation-attempt-link/1"
V1_WORKFLOW = "closed_shell_main_group_single_guess_ts_freq"
V1_ATOMIC_NUMBERS = {
    "H": 1, "B": 5, "C": 6, "N": 7, "O": 8, "F": 9,
    "Si": 14, "P": 15, "S": 16, "Cl": 17, "Br": 35, "I": 53,
}
V1_ELEMENTS = set(V1_ATOMIC_NUMBERS)
ID_RE = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
SHA_RE = re.compile(r"^[a-f0-9]{64}$")
EXTERNAL_KEY_RE = re.compile(r"^[a-z][a-z0-9_.:-]{2,255}$")
CHECKPOINT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*\.chk$")
ADAPTER_SCHEMA_PATHS = {
    TARGET_IMPORT_SCHEMA: ROOT / "contracts" / "reaction-workflow" / "candidate-target-import.schema.json",
    INPUT_REVIEW_SCHEMA: ROOT / "contracts" / "reaction-workflow" / "input-draft-review.schema.json",
    INPUT_HANDOFF_SCHEMA: ROOT / "contracts" / "reaction-workflow" / "candidate-input-handoff.schema.json",
    ENERGY_REVIEW_SCHEMA: ROOT / "contracts" / "reaction-workflow" / "energy-review.schema.json",
    ENERGY_RECORD_SCHEMA: ROOT / "contracts" / "reaction-workflow" / "reviewed-energy-record.schema.json",
    ENERGY_LINEAGE_SCHEMA: ROOT / "contracts" / "reaction-workflow" / "energy-lineage.schema.json",
    SANITIZED_JOB_SCHEMA: ROOT / "contracts" / "reaction-workflow" / "sanitized-job-observation.schema.json",
    ATTEMPT_LINK_SCHEMA: ROOT / "contracts" / "reaction-workflow" / "calculation-attempt-link.schema.json",
}


class AdapterError(rw.OfflineError):
    """A calculation-artifact adapter contract was violated."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AdapterError(message)


def _exact_keys(value: Any, keys: set[str], label: str) -> dict[str, Any]:
    require(isinstance(value, dict), f"{label} must be an object")
    unknown = sorted(set(value) - keys)
    missing = sorted(keys - set(value))
    require(not unknown, f"{label} contains unknown fields: {', '.join(unknown)}")
    require(not missing, f"{label} is missing required fields: {', '.join(missing)}")
    return value


def _id(value: Any, label: str) -> str:
    require(isinstance(value, str) and ID_RE.fullmatch(value) is not None, f"invalid {label}")
    return value


def _hash(value: Any, label: str) -> str:
    require(isinstance(value, str) and SHA_RE.fullmatch(value) is not None, f"invalid {label}")
    return value


def _nonempty(value: Any, label: str) -> str:
    require(isinstance(value, str) and bool(value.strip()), f"{label} must be a non-empty string")
    return value


def _file(path: Path, label: str) -> Path:
    expanded = path.expanduser()
    require(".." not in expanded.parts, f"{label} path must not contain lexical parent traversal")
    require(expanded.exists(), f"{label} does not exist: {expanded}")
    absolute = expanded if expanded.is_absolute() else Path.cwd() / expanded
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current = current / part
        require(not current.is_symlink(), f"{label} path component must not be a symlink: {current}")
    require(expanded.is_file(), f"{label} must be a regular file: {expanded}")
    return expanded.resolve()


def _reject_output_symlink_ancestors(path: Path, label: str) -> None:
    absolute = path if path.is_absolute() else Path.cwd() / path
    current = Path(absolute.anchor)
    for part in absolute.parts[1:-1]:
        current = current / part
        require(not current.is_symlink(), f"{label} ancestor must not be a symlink: {current}")


def _output_path(path: Path, label: str) -> Path:
    expanded = path.expanduser()
    require(".." not in expanded.parts, f"{label} path must not escape its lexical root")
    require(not expanded.exists() and not expanded.is_symlink(), f"refusing to overwrite existing {label}: {expanded}")
    _reject_output_symlink_ancestors(expanded, label)
    expanded.parent.mkdir(parents=True, exist_ok=True)
    _reject_output_symlink_ancestors(expanded, label)
    require(not expanded.parent.is_symlink(), f"{label} parent must not be a symlink: {expanded.parent}")
    if not expanded.is_absolute():
        require(expanded.resolve().is_relative_to(Path.cwd().resolve()), f"{label} path escaped the invocation root")
    return expanded.resolve()


def _load_json(path: Path, label: str) -> tuple[Path, dict[str, Any]]:
    resolved = _file(path, label)
    return resolved, rw.load_json(resolved)


def _write_new_json(path: Path, document: dict[str, Any]) -> None:
    """Write canonical JSON with an exclusive create, including under a race."""
    try:
        with path.open("xb") as handle:
            handle.write(rw.canonical_bytes(document))
    except FileExistsError as exc:
        raise AdapterError(f"refusing to overwrite existing artifact: {path}") from exc


def _portable(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(ROOT.resolve()))
    except ValueError:
        return str(resolved)


def _declared_payload(data: dict[str, Any]) -> str | None:
    schema_owned_fields = {
        **{schema: "payload_sha256" for schema in ADAPTER_SCHEMA_PATHS},
        "gaussian-protocol-options/1": "proposal_payload_sha256",
        "gaussian-protocol-selection/1": "selection_payload_sha256",
    }
    owned_field = schema_owned_fields.get(data.get("schema"))
    if owned_field is None:
        return None
    require(owned_field in data, f"artifact schema {data.get('schema')} is missing its owned payload SHA-256")
    return _hash(data[owned_field], "artifact payload SHA-256")


def _validate_adapter_document(document: dict[str, Any]) -> None:
    schema_id = document.get("schema")
    schema_path = ADAPTER_SCHEMA_PATHS.get(schema_id)
    require(schema_path is not None, "unsupported calculation-artifact schema")
    try:
        schema = asym_contract.load_json(schema_path)
        asym_contract.validate_schema_document(schema)
        asym_contract._validate_schema_instance(document, schema, schema)  # repository validator
    except (ValueError, OSError) as exc:
        raise AdapterError(f"calculation-artifact schema rejected {schema_id}: {exc}") from exc


def artifact_ref(
    path: Path,
    data: dict[str, Any] | None = None,
    *,
    schema: str | None = None,
    display_path: str | None = None,
) -> dict[str, Any]:
    resolved = _file(path, "artifact")
    if data is None and resolved.suffix.lower() == ".json":
        data = rw.load_json(resolved)
    resolved_schema = schema if schema is not None else data.get("schema") if data else None
    require(resolved_schema is None or isinstance(resolved_schema, str), "artifact schema must be a string or null")
    return {
        "path": display_path if display_path is not None else _portable(resolved),
        "sha256": rw.sha256_file(resolved),
        "size_bytes": resolved.stat().st_size,
        "schema": resolved_schema,
        "payload_sha256": _declared_payload(data) if data else None,
    }


def _bytes_artifact_ref(path: Path, content: bytes, schema: str) -> dict[str, Any]:
    return {
        "path": _portable(path),
        "sha256": hashlib.sha256(content).hexdigest(),
        "size_bytes": len(content),
        "schema": schema,
        "payload_sha256": None,
    }


def _json_artifact_ref(path: Path, document: dict[str, Any]) -> dict[str, Any]:
    content = rw.canonical_bytes(document)
    reference = _bytes_artifact_ref(path, content, str(document["schema"]))
    reference["payload_sha256"] = _declared_payload(document)
    return reference


def _validate_ref(
    reference: Any,
    path: Path,
    data: dict[str, Any] | None,
    label: str,
    *,
    schema: str | None = None,
    owner: Path | None = None,
) -> None:
    _exact_keys(reference, {"path", "sha256", "size_bytes", "schema", "payload_sha256"}, label)
    raw = _nonempty(reference["path"], f"{label}.path")
    require("://" not in raw, f"{label}.path must be local")
    declared = Path(raw).expanduser()
    candidates = [declared] if declared.is_absolute() else [ROOT / declared]
    if owner is not None and not declared.is_absolute():
        candidates.append(owner.parent / declared)
    resolved_candidates: list[Path] = []
    for candidate in candidates:
        if candidate.exists() or candidate.is_symlink():
            resolved_candidates.append(_file(candidate, f"{label}.path"))
    require(path.resolve() in resolved_candidates, f"{label} path differs from the supplied artifact")
    expected = artifact_ref(path, data, schema=schema, display_path=reference["path"])
    require(reference == expected, f"{label} artifact reference drift")


def _finalize(document: dict[str, Any]) -> dict[str, Any]:
    require("payload_sha256" not in document, "payload SHA-256 must not be supplied by a builder")
    finalized = rw.finalize_artifact(document)
    _validate_adapter_document(finalized)
    return finalized


def _validate_payload(document: dict[str, Any]) -> None:
    try:
        rw.validate_payload_hash(document)
    except rw.OfflineError as exc:
        raise AdapterError(f"calculation-artifact payload validation failed: {exc}") from exc


def _resolve_reference(reference: dict[str, Any], owner: Path, label: str) -> tuple[Path, dict[str, Any] | None]:
    _exact_keys(reference, {"path", "sha256", "size_bytes", "schema", "payload_sha256"}, label)
    raw = _nonempty(reference["path"], f"{label}.path")
    require("://" not in raw, f"{label}.path must be local")
    path = Path(raw)
    require(".." not in path.parts, f"{label}.path must not contain lexical parent traversal")
    if not path.is_absolute():
        candidates = [ROOT / path, owner.parent / path]
        path = next((candidate for candidate in candidates if candidate.exists()), candidates[0])
    resolved = _file(path, label)
    declared_schema = reference["schema"]
    is_json = resolved.suffix.lower() == ".json" or (
        isinstance(declared_schema, str)
        and declared_schema not in {
            "chemical/x-xyz",
            "chemical/x-gaussian-input",
            "gaussian-input-explicit-cartesian-ts-freq/1",
        }
    )
    data = rw.load_json(resolved) if is_json else None
    _validate_ref(reference, resolved, data, label, schema=None if data else reference["schema"], owner=owner)
    return resolved, data


def _candidate_geometry(
    candidate: dict[str, Any],
    candidate_path: Path,
    *,
    require_v1_elements: bool = True,
) -> tuple[Path, list[str], list[tuple[float, float, float]]]:
    geometry = candidate.get("geometry", {})
    require(geometry.get("format") == "xyz", "V1 input handoff requires an XYZ candidate geometry")
    reference = geometry.get("artifact")
    require(isinstance(reference, dict), "candidate geometry artifact is missing")
    raw = _nonempty(reference.get("path"), "candidate geometry path")
    require("://" not in raw, "candidate geometry must be a local file")
    path = Path(raw)
    if not path.is_absolute():
        path = candidate_path.parent / path
    geometry_path = _file(path, "candidate geometry")
    require(reference.get("sha256") == rw.sha256_file(geometry_path), "candidate geometry SHA-256 drift")
    try:
        elements, coordinates = asym.parse_xyz(geometry_path)
    except (ValueError, OSError) as exc:
        raise AdapterError(f"specialist XYZ parser rejected candidate geometry: {exc}") from exc
    require(elements and len(elements) == len(coordinates), "candidate XYZ is empty or inconsistent")
    if require_v1_elements:
        require(all(element in V1_ELEMENTS for element in elements), "candidate XYZ contains an unsupported V1 element")
    require(all(all(math.isfinite(value) for value in xyz) for xyz in coordinates), "candidate XYZ contains NaN or infinity")
    return geometry_path, elements, coordinates


def _hill_formula(elements: list[str]) -> tuple[str, dict[str, int]]:
    counts = Counter(elements)
    order: list[str] = []
    if "C" in counts:
        order.append("C")
        if "H" in counts:
            order.append("H")
    order.extend(sorted(element for element in counts if element not in order))
    formula = "".join(element + (str(counts[element]) if counts[element] != 1 else "") for element in order)
    return formula, dict(sorted(counts.items()))


def _validate_candidate_identity(candidate: dict[str, Any], elements: list[str]) -> None:
    atom_map = candidate.get("atom_map")
    require(isinstance(atom_map, list) and atom_map, "candidate atom map is missing")
    require([item.get("index") for item in atom_map] == list(range(1, len(atom_map) + 1)), "candidate atom map must be contiguous and one-based")
    mapped_elements = [item.get("element") for item in atom_map]
    require(mapped_elements == elements, "candidate atom order differs from XYZ")
    inventory = candidate.get("atom_inventory", {})
    formula, counts = _hill_formula(elements)
    require(inventory.get("atom_count") == len(elements), "candidate atom count differs from XYZ")
    require(inventory.get("formula") == formula, "candidate formula differs from XYZ")
    require(inventory.get("element_counts") == counts, "candidate element counts differ from XYZ")
    chemical = candidate.get("chemical_state", {})
    electronic = candidate.get("electronic_state", {})
    require(chemical.get("charge") == electronic.get("charge"), "candidate chemical/electronic charge mismatch")
    require(chemical.get("multiplicity") == electronic.get("multiplicity"), "candidate chemical/electronic multiplicity mismatch")


def _load_candidate(study_path: Path, candidate_path: Path, *, require_promoted: bool) -> tuple[dict[str, Any], dict[str, Any], Path, list[str], list[tuple[float, float, float]]]:
    study_path, study = _load_json(study_path, "study")
    candidate_path, candidate = _load_json(candidate_path, "candidate")
    try:
        asym_contract.validate_study(study)
        asym_contract.validate_candidate(candidate, study, study_path)
    except (ValueError, OSError) as exc:
        raise AdapterError(f"asymmetric-catalysis specialist validator rejected candidate: {exc}") from exc
    geometry_path, elements, coordinates = _candidate_geometry(candidate, candidate_path)
    _validate_candidate_identity(candidate, elements)
    if require_promoted:
        require(candidate.get("support_status") == "supported_main_group_closed_shell", "input handoff refuses unsupported candidates")
        require(candidate.get("review_status") == "promoted_offline", "input handoff requires a promoted_offline candidate")
        require(candidate.get("review", {}).get("decision") == "promoted_offline", "candidate promotion decision is absent")
        require(candidate.get("geometry", {}).get("stereochemistry_reviewed") is True, "candidate stereochemistry is not reviewed")
        require(candidate.get("geometry", {}).get("clash_reviewed") is True, "candidate clash review is absent")
        require(not candidate.get("warnings"), "candidate has unresolved warnings")
        electronic = candidate["electronic_state"]
        require(electronic.get("multiplicity") == 1, "V1 input handoff supports only closed-shell singlets")
        require(electronic.get("broken_symmetry") in {"not_applicable", "not_requested"}, "V1 input handoff refuses broken-symmetry cases")
        require(electronic.get("multireference_concern") == "none_identified", "V1 input handoff refuses unresolved multireference cases")
    return study, candidate, geometry_path, elements, coordinates


def _entry_external_key(study_id: str, candidate_id: str) -> str:
    value = f"asymmetric_candidate:{study_id}:{candidate_id}"
    require(EXTERNAL_KEY_RE.fullmatch(value) is not None, "generated external target key is invalid")
    return value


def _bounded_derived_id(prefix: str, source_id: str) -> str:
    candidate = f"{prefix}_{source_id}"
    if ID_RE.fullmatch(candidate) is not None:
        return candidate
    return f"{prefix}_{hashlib.sha256(source_id.encode('utf-8')).hexdigest()[:20]}"


def build_target_import(study_path: Path, ledger_path: Path, output: Path, import_id: str) -> dict[str, Any]:
    output = _output_path(output, "target import")
    study_path, study = _load_json(study_path, "study")
    ledger_path, ledger = _load_json(ledger_path, "candidate ledger")
    _id(import_id, "import_id")
    try:
        asym_contract.validate_study(study)
        asym_contract.validate_ledger(ledger, study, study_path)
    except (ValueError, OSError) as exc:
        raise AdapterError(f"asymmetric-catalysis specialist validator rejected ledger: {exc}") from exc

    entries = ledger.get("entries", [])
    require(isinstance(entries, list), "candidate ledger entries must be an array")
    candidate_ids = [entry.get("candidate_id") for entry in entries]
    require(len(candidate_ids) == len(set(candidate_ids)), "candidate ledger contains duplicate IDs")
    known_ids = set(candidate_ids)
    targets: list[dict[str, Any]] = []
    ledger_reference = artifact_ref(ledger_path, ledger)
    study_reference = artifact_ref(study_path, study)
    for entry in entries:
        candidate_id = _id(entry.get("candidate_id"), "ledger candidate_id")
        external_key = _entry_external_key(study["study_id"], candidate_id)
        status = entry.get("status")
        blockers: list[str] = []
        roles = [
            {"role": "candidate_ledger", "artifact": ledger_reference},
            {"role": "study", "artifact": study_reference},
        ]
        candidate: dict[str, Any] | None = None
        candidate_path: Path | None = None
        geometry_path: Path | None = None
        if entry.get("candidate_artifact") is not None:
            raw_reference = entry["candidate_artifact"]
            raw = _nonempty(raw_reference.get("path"), f"ledger {candidate_id} candidate path")
            require("://" not in raw, f"ledger {candidate_id} candidate artifact must be local")
            candidate_path = Path(raw)
            if not candidate_path.is_absolute():
                candidate_path = ledger_path.parent / candidate_path
            candidate_path, candidate = _load_json(candidate_path, f"candidate {candidate_id}")
            require(raw_reference.get("sha256") == rw.sha256_file(candidate_path), f"ledger {candidate_id} candidate hash drift")
            try:
                asym_contract.validate_candidate(candidate, study, study_path)
            except (ValueError, OSError) as exc:
                raise AdapterError(f"candidate {candidate_id} failed specialist validation: {exc}") from exc
            require(candidate.get("candidate_id") == candidate_id, f"ledger candidate identity mismatch: {candidate_id}")
            geometry_path, elements, _coordinates = _candidate_geometry(
                candidate, candidate_path, require_v1_elements=False
            )
            _validate_candidate_identity(candidate, elements)
            roles.extend(
                [
                    {"role": "candidate", "artifact": artifact_ref(candidate_path, candidate)},
                    {"role": "geometry", "artifact": artifact_ref(geometry_path, schema="chemical/x-xyz")},
                ]
            )

        supported = bool(candidate and candidate.get("support_status") == "supported_main_group_closed_shell")
        promoted = bool(candidate and candidate.get("review_status") == "promoted_offline" and candidate.get("review", {}).get("decision") == "promoted_offline")
        exact_geometry = bool(candidate and geometry_path is not None)
        electronic = candidate.get("electronic_state", {}) if candidate else {}
        chemical = candidate.get("chemical_state", {}) if candidate else {}
        closed_shell_singlet = bool(
            candidate and electronic.get("multiplicity") == 1 and chemical.get("multiplicity") == 1
        )
        wavefunction_scope_supported = bool(
            candidate
            and electronic.get("broken_symmetry") in {"not_applicable", "not_requested"}
            and electronic.get("multireference_concern") == "none_identified"
        )
        geometry_reviews_complete = bool(
            candidate
            and candidate.get("geometry", {}).get("stereochemistry_reviewed") is True
            and candidate.get("geometry", {}).get("clash_reviewed") is True
        )
        v1_elements_supported = bool(
            candidate
            and all(atom.get("element") in V1_ELEMENTS for atom in candidate.get("atom_map", []))
        )
        eligible = bool(
            status == "materialized_unique"
            and supported
            and promoted
            and exact_geometry
            and closed_shell_singlet
            and wavefunction_scope_supported
            and geometry_reviews_complete
            and v1_elements_supported
            and not candidate.get("warnings", [])  # type: ignore[union-attr]
        )
        if status != "materialized_unique":
            blockers.append(f"ledger_status:{status}")
        if candidate is None:
            blockers.append("candidate_artifact_absent")
        else:
            if not supported:
                blockers.append(f"candidate_support:{candidate.get('support_status')}")
            if not promoted:
                blockers.append(f"candidate_review:{candidate.get('review_status')}")
            if candidate.get("warnings"):
                blockers.append("candidate_warnings_present")
            if not closed_shell_singlet:
                blockers.append("candidate_not_closed_shell_singlet")
            if not wavefunction_scope_supported:
                blockers.append("candidate_wavefunction_scope_unsupported")
            if not geometry_reviews_complete:
                blockers.append("candidate_geometry_reviews_incomplete")
            if not v1_elements_supported:
                blockers.append("candidate_elements_outside_v1")
        dependencies: list[str] = []
        duplicate_of = entry.get("duplicate_of")
        if duplicate_of is not None:
            require(duplicate_of in known_ids, f"candidate {candidate_id} duplicate target is absent")
            dependencies.append(_entry_external_key(study["study_id"], duplicate_of))
        targets.append(
            {
                "external_target_key": external_key,
                "source_entry_sha256": rw.sha256_data(entry),
                "source_disposition": status,
                "candidate_id": candidate_id,
                "candidate_support_status": candidate.get("support_status") if candidate else None,
                "candidate_review_status": candidate.get("review_status") if candidate else None,
                "duplicate_of_external_key": dependencies[0] if dependencies else None,
                "artifact_roles": sorted(roles, key=lambda item: item["role"]),
                "dependency_external_keys": dependencies,
                "readiness_facts": {
                    "materialized": candidate is not None,
                    "supported_main_group_closed_shell": supported,
                    "promoted_offline": promoted,
                    "exact_geometry_bound": exact_geometry,
                    "closed_shell_singlet": closed_shell_singlet,
                    "wavefunction_scope_supported": wavefunction_scope_supported,
                    "geometry_reviews_complete": geometry_reviews_complete,
                    "v1_elements_supported": v1_elements_supported,
                    "eligible_for_later_input_review": eligible,
                    "blockers": sorted(set(blockers)),
                },
                "source_diagnostics": list(entry.get("diagnostics", [])),
            }
        )
    targets.sort(key=lambda item: item["external_target_key"])
    disposition_names = ("unmaterialized", "duplicate_logical", "materialized_unique", "duplicate_geometry")
    dispositions = Counter(target["source_disposition"] for target in targets)
    retained_exclusions: list[dict[str, Any]] = []
    for source_index, exclusion in enumerate(ledger.get("excluded_combinations", [])):
        require(isinstance(exclusion, dict), f"candidate ledger exclusion {source_index} must be an object")
        retained_exclusions.append(
            {
                "source_index": source_index,
                "source_record_sha256": rw.sha256_data(exclusion),
                "source_record_canonical_json": rw.canonical_bytes(exclusion).decode("utf-8"),
            }
        )
    document = _finalize(
        {
            "schema": TARGET_IMPORT_SCHEMA,
            "import_id": import_id,
            "study_id": study["study_id"],
            "comparison_group_id": ledger["comparison_group_id"],
            "study_source": study_reference,
            "ledger_source": ledger_reference,
            "targets": targets,
            "excluded_combinations": retained_exclusions,
            "counts": {
                "targets": len(targets),
                "eligible_for_later_input_review": sum(target["readiness_facts"]["eligible_for_later_input_review"] for target in targets),
                "excluded_combinations": len(ledger.get("excluded_combinations", [])),
                "by_source_disposition": {name: dispositions.get(name, 0) for name in disposition_names},
            },
            "calculation_ready": False,
            "no_submission_authorization": True,
        }
    )
    _write_new_json(output, document)
    return document


def _validate_input_review(review: dict[str, Any], review_path: Path) -> None:
    _validate_adapter_document(review)
    keys = {
        "schema", "review_id", "workflow_kind", "candidate_id", "protocol_id", "sources",
        "identity", "link0", "route", "resources", "title", "trailing_sections",
        "expected_input_sha256", "decision", "calculation_ready", "no_submission_authorization",
        "payload_sha256",
    }
    _exact_keys(review, keys, "input review")
    require(review["schema"] == INPUT_REVIEW_SCHEMA, "unrecognized input-review schema")
    _id(review["review_id"], "input review_id")
    _id(review["candidate_id"], "input candidate_id")
    _id(review["protocol_id"], "input protocol_id")
    require(review["workflow_kind"] == V1_WORKFLOW, "unsupported input-review workflow kind")
    require(review["calculation_ready"] is False and review["no_submission_authorization"] is True, "input review widened the authority boundary")
    _validate_payload(review)
    sources = _exact_keys(review["sources"], {"study", "candidate", "geometry", "protocol_options", "protocol_selection"}, "input review sources")
    for name, reference in sources.items():
        _exact_keys(reference, {"path", "sha256", "size_bytes", "schema", "payload_sha256"}, f"input review source {name}")
    identity = _exact_keys(review["identity"], {"formula", "element_counts", "atom_count", "atom_order", "charge", "multiplicity"}, "input review identity")
    _nonempty(identity["formula"], "input review formula")
    require(isinstance(identity["element_counts"], dict) and identity["element_counts"], "input review element counts are missing")
    require(isinstance(identity["atom_count"], int) and identity["atom_count"] > 0, "input review atom count is invalid")
    require(isinstance(identity["charge"], int) and not isinstance(identity["charge"], bool), "input review charge is invalid")
    require(identity["multiplicity"] == 1, "V1 input review supports only multiplicity 1")
    atom_order = identity["atom_order"]
    require(isinstance(atom_order, list) and len(atom_order) == identity["atom_count"], "input review atom order/count mismatch")
    for index, atom in enumerate(atom_order, start=1):
        _exact_keys(atom, {"index", "element", "source_atom_id"}, f"input review atom {index}")
        require(atom["index"] == index and atom["element"] in V1_ELEMENTS, "input review atom order is invalid")
        _nonempty(atom["source_atom_id"], f"input review atom {index} source_atom_id")
    link0 = _exact_keys(review["link0"], {"chk", "mem", "nprocshared"}, "input review link0")
    require(isinstance(link0["chk"], str) and CHECKPOINT_RE.fullmatch(link0["chk"]) is not None and Path(link0["chk"]).name == link0["chk"], "input review checkpoint must be a safe .chk basename")
    _nonempty(link0["mem"], "input review memory")
    require(isinstance(link0["nprocshared"], int) and 1 <= link0["nprocshared"] <= 44, "input review nprocshared must be 1..44")
    route = _nonempty(review["route"], "input review route")
    require("\n" not in route and "\r" not in route and route.startswith("#"), "V1 route must be one canonical reviewed route line")
    lowered = re.sub(r"\s+", " ", route.lower())
    forbidden = {
        "--link1--": r"--link1--",
        "QST2/QST3": r"\bqst[23]\b",
        "IRC": r"\birc\b",
        "Geom=Check/AllCheck": r"\bgeom\s*=\s*(?:\(\s*)?(?:allcheck|check)\b",
        "Guess=Read": r"\bguess\s*=\s*(?:\(\s*)?read\b",
        "ONIOM": r"\boni[o]?m\b",
        "general basis/ECP trailing input": r"\b(?:gen|genecp|pseudo)\b",
        "scan/ModRedundant": r"\b(?:scan|modredundant)\b",
    }
    for label, pattern in forbidden.items():
        require(re.search(pattern, lowered, re.I) is None, f"V1 input review refuses {label}")
    require(re.search(r"\bopt\b", lowered) is not None and re.search(r"\bts\b", lowered) is not None and re.search(r"\bfreq\b", lowered) is not None, "V1 route must be an explicit single-guess TS Opt/Freq route")
    resources = _exact_keys(review["resources"], {"resource_tier", "memory_gb", "cores", "expected_stage_count"}, "input review resources")
    require(resources["resource_tier"] in {"simple", "general", "complex", "custom_reviewed"}, "input review resource tier is invalid")
    require(isinstance(resources["memory_gb"], (int, float)) and not isinstance(resources["memory_gb"], bool) and math.isfinite(float(resources["memory_gb"])) and resources["memory_gb"] > 0, "input review memory_gb is invalid")
    require(resources["cores"] == link0["nprocshared"] and resources["expected_stage_count"] == 1, "input review resource fields are inconsistent")
    title = _nonempty(review["title"], "input review title")
    require("\n" not in title and "\r" not in title, "input review title must be one line")
    require(review["trailing_sections"] == [], "V1 input review requires an explicitly empty trailing-section list")
    _hash(review["expected_input_sha256"], "expected input SHA-256")
    decision = _exact_keys(review["decision"], {"status", "reviewer", "reviewed_on", "explicit_confirmation", "notes"}, "input review decision")
    require(decision["status"] == "accepted_exact_draft" and decision["explicit_confirmation"] is True, "input review is not explicitly accepted")
    _nonempty(decision["reviewer"], "input review reviewer")
    require(re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(decision["reviewed_on"])) is not None, "input review date must use YYYY-MM-DD")
    require(isinstance(decision["notes"], list) and all(isinstance(item, str) and item.strip() for item in decision["notes"]), "input review notes are invalid")


def _render_input(review: dict[str, Any], elements: list[str], coordinates: list[tuple[float, float, float]]) -> bytes:
    link0 = review["link0"]
    lines = [
        f"%chk={link0['chk']}",
        f"%mem={link0['mem']}",
        f"%nprocshared={link0['nprocshared']}",
        review["route"].strip(),
        "",
        review["title"],
        "",
        f"{review['identity']['charge']} {review['identity']['multiplicity']}",
    ]
    lines.extend(
        f"{element} {x:.8f} {y:.8f} {z:.8f}"
        for element, (x, y, z) in zip(elements, coordinates)
    )
    lines.extend(["", ""])
    return "\n".join(lines).encode("utf-8")


def _specialist_input_audit(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Delegate family and final syntax checks; intentionally no raw parsing here."""
    try:
        parsed_ts = ts_irc.parse_cartesian_input(path)
        family = ts_irc.validate_input_family(
            "single_guess", {"ts": parsed_ts}, list(range(1, len(parsed_ts["atoms"]) + 1))
        )
        require(family.get("valid") is True and not family.get("diagnostics"), "TS specialist rejected single-guess atom mapping")
        final = rtwin.parse_gaussian(path)
    except SystemExit as exc:
        raise AdapterError("RTwin-PBS specialist validator rejected the rendered input") from exc
    except (ValueError, OSError) as exc:
        raise AdapterError(f"specialist input validator rejected the rendered input: {exc}") from exc
    return family, final


def build_input_handoff(
    study_path: Path,
    candidate_path: Path,
    options_path: Path,
    selection_path: Path,
    review_path: Path,
    output_input: Path,
    output_manifest: Path,
) -> tuple[bytes, dict[str, Any]]:
    output_input = _output_path(output_input, "Gaussian input")
    output_manifest = _output_path(output_manifest, "input handoff manifest")
    require(output_input.suffix.lower() == ".gjf", "V1 Gaussian output must end in .gjf")
    require(output_manifest.name == output_input.stem + ".handoff.json", "handoff companion must use <input-stem>.handoff.json")
    study_path = _file(study_path, "study")
    candidate_path = _file(candidate_path, "candidate")
    options_path = _file(options_path, "protocol options")
    selection_path = _file(selection_path, "protocol selection")
    review_path, review = _load_json(review_path, "input review")
    _validate_input_review(review, review_path)
    study, candidate, geometry_path, elements, coordinates = _load_candidate(study_path, candidate_path, require_promoted=True)

    try:
        selection, options, selected = protocol.load_validated_selection(selection_path, options_path)
    except (protocol.ContractError, OSError, json.JSONDecodeError) as exc:
        raise AdapterError(f"protocol-selection specialist validator rejected selection: {exc}") from exc

    sources = review["sources"]
    source_map = {
        "study": (study_path, study),
        "candidate": (candidate_path, candidate),
        "geometry": (geometry_path, None),
        "protocol_options": (options_path, options),
        "protocol_selection": (selection_path, selection),
    }
    for name, (path, data) in source_map.items():
        _validate_ref(
            sources[name], path, data, f"input review {name}",
            schema="chemical/x-xyz" if name == "geometry" else None,
            owner=review_path,
        )

    require(review["candidate_id"] == candidate["candidate_id"], "input review candidate ID mismatch")
    require(review["protocol_id"] == candidate["protocol_id"], "input review/candidate protocol ID mismatch")
    identity = review["identity"]
    expected_identity = {
        "formula": candidate["atom_inventory"]["formula"],
        "element_counts": candidate["atom_inventory"]["element_counts"],
        "atom_count": candidate["atom_inventory"]["atom_count"],
        "atom_order": [
            {"index": atom["index"], "element": atom["element"], "source_atom_id": atom["source_atom_id"]}
            for atom in candidate["atom_map"]
        ],
        "charge": candidate["chemical_state"]["charge"],
        "multiplicity": candidate["chemical_state"]["multiplicity"],
    }
    require(identity == expected_identity, "input review identity differs from promoted candidate")
    request = options["request_snapshot"]
    structure = request["structure"]
    require(selection["scope_binding"]["structure_sha256"] == rw.sha256_file(geometry_path), "protocol selection structure hash differs from candidate XYZ")
    require(structure["sha256"] == rw.sha256_file(geometry_path), "protocol request structure hash differs from candidate XYZ")
    require(structure["formula"] == identity["formula"], "protocol request formula differs from candidate")
    require(structure["atom_count"] == identity["atom_count"], "protocol request atom count differs from candidate")
    require(set(structure["elements"]) == set(identity["element_counts"]), "protocol request elements differ from candidate")
    require(structure["charge"] == identity["charge"] and structure["multiplicity"] == identity["multiplicity"], "protocol request charge/multiplicity differs from candidate")
    require(request.get("system_class") == "main_group_closed_shell" and request.get("support_status") == "supported", "protocol request is outside V1 support")
    require(request.get("task_types") == ["transition_state_optimization", "harmonic_frequency"], "protocol request task family differs from V1")
    require(
        len(selected.get("task_plan", [])) == 1
        and selected["task_plan"][0].get("stage_type") == "single_guess_ts_opt_freq"
        and selected["resources"].get("job_count") == 1,
        "V1 requires one selected single-guess TS/Freq task and one job",
    )
    require(
        selected.get("method_profiles")
        and all(profile.get("scf", {}).get("reference") == "restricted_closed_shell" for profile in selected["method_profiles"]),
        "V1 refuses protocol profiles that are not restricted closed-shell",
    )
    require(all(record.get("ecp") is None for profile in selected.get("method_profiles", []) for record in profile.get("basis_stack", [])), "V1 refuses ECP/general-basis trailing sections")
    resources = review["resources"]
    selected_resources = selected["resources"]
    require(resources["resource_tier"] == selected_resources["resource_tier"], "input review resource tier differs from selected option")
    require(float(resources["memory_gb"]) == float(selected_resources["mem_gb"]), "input review memory differs from selected option")
    require(resources["cores"] == selected_resources["cores"], "input review cores differ from selected option")
    require(candidate.get("resource_tier_proposal") == resources["resource_tier"], "candidate resource-tier proposal differs from selected option")
    try:
        memory_bytes = rtwin.parse_memory(review["link0"]["mem"])
    except SystemExit as exc:
        raise AdapterError("RTwin-PBS specialist rejected reviewed memory") from exc
    require(memory_bytes == int(float(resources["memory_gb"]) * 1024**3), "Link0 memory differs from reviewed resources")

    input_bytes = _render_input(review, elements, coordinates)
    input_sha = hashlib.sha256(input_bytes).hexdigest()
    require(input_sha == review["expected_input_sha256"], "rendered input SHA-256 differs from exact input review")
    with tempfile.TemporaryDirectory(prefix="auto-g16-input-audit-") as temporary:
        temporary_input = Path(temporary) / output_input.name
        temporary_input.write_bytes(input_bytes)
        family_audit, final_audit = _specialist_input_audit(temporary_input)
    require(final_audit["input_sha256"] == input_sha, "RTwin-PBS audit input hash mismatch")
    require(final_audit["route"] == review["route"].strip(), "RTwin-PBS audited route differs from exact review")
    require(final_audit["mem"] == review["link0"]["mem"] and final_audit["nprocshared"] == review["link0"]["nprocshared"], "RTwin-PBS audited resources differ from exact review")
    require(final_audit["charge"] == identity["charge"] and final_audit["multiplicity"] == identity["multiplicity"], "RTwin-PBS audited charge/multiplicity differs from exact review")
    require(final_audit["atom_count"] == identity["atom_count"] and final_audit["elements"] == identity["element_counts"], "RTwin-PBS audited atom inventory differs from exact review")
    require(final_audit["geometry_source"] == "explicit_cartesian" and final_audit["oldcheckpoint"] is None, "RTwin-PBS audit observed an unsupported geometry source")

    input_reference = _bytes_artifact_ref(
        output_input, input_bytes, "gaussian-input-explicit-cartesian-ts-freq/1"
    )
    document = _finalize(
        {
            "schema": INPUT_HANDOFF_SCHEMA,
            "handoff_id": _bounded_derived_id("handoff", review["review_id"]),
            "external_target_key": _entry_external_key(candidate["study_id"], candidate["candidate_id"]),
            "workflow_kind": V1_WORKFLOW,
            "sources": {
                **{name: copy.deepcopy(reference) for name, reference in sources.items()},
                "input_review": artifact_ref(review_path, review),
            },
            "input": input_reference,
            "identity": copy.deepcopy(identity),
            "input_audit": {
                "specialist_validators": [
                    "auto-g16-ts-irc.validate_input_family(single_guess)",
                    "auto-g16-rtwin-pbs.parse_gaussian",
                ],
                "entry_mode": family_audit["entry_mode"],
                "route": final_audit["route"],
                "checkpoint_basename": final_audit["checkpoint"],
                "memory": final_audit["mem"],
                "memory_bytes": final_audit["memory_bytes"],
                "nprocshared": final_audit["nprocshared"],
                "charge": final_audit["charge"],
                "multiplicity": final_audit["multiplicity"],
                "atom_count": final_audit["atom_count"],
                "element_counts": final_audit["elements"],
                "geometry_source": final_audit["geometry_source"],
                "trailing_blank_line": final_audit["trailing_blank_line"],
            },
            "gate_separation": {
                "candidate_construction": "reviewed_promoted_offline",
                "protocol_choice": "validated_explicit_selection",
                "input_draft_review": "accepted_exact_draft",
                "live_approval": "absent",
                "execution_status": "not_started",
                "scientific_acceptance": "not_assessed",
            },
            "calculation_ready": False,
            "no_submission_authorization": True,
            "non_authorizations": [
                "No staging, transfer, server-directory creation, PBS submission, retry, cancellation, cleanup, or deployment is authorized.",
                "Input handoff readiness is an offline artifact state and is not a live calculation approval.",
            ],
        }
    )
    with output_input.open("xb") as handle:
        handle.write(input_bytes)
    _write_new_json(output_manifest, document)
    return input_bytes, document


def _validate_energy_review(review: dict[str, Any]) -> None:
    _validate_adapter_document(review)
    _exact_keys(
        review,
        {
            "schema", "review_id", "candidate_id", "sources", "decision", "allowed_projection_fields",
            "comparison_policy", "reviewer", "reviewed_on", "notes", "calculation_ready",
            "no_submission_authorization", "payload_sha256",
        },
        "energy review",
    )
    require(review["schema"] == ENERGY_REVIEW_SCHEMA, "unrecognized energy-review schema")
    _id(review["review_id"], "energy review_id")
    _id(review["candidate_id"], "energy candidate_id")
    require(review["decision"] in {"accept_electronic_only", "blocked_insufficient_evidence"}, "invalid energy review decision")
    require(review["allowed_projection_fields"] in ([], ["final_energy_hartree"]), "energy review may project only final_energy_hartree in V1")
    policy = _exact_keys(review["comparison_policy"], {"temperature_k", "standard_state", "low_frequency_policy", "common_reference", "comparison_authorized"}, "energy comparison policy")
    require(policy["comparison_authorized"] is False, "V1 energy review cannot authorize a comparison energy")
    require(policy["temperature_k"] is None and policy["standard_state"] is None and policy["low_frequency_policy"] is None and policy["common_reference"] is None, "V1 electronic-only review must not invent thermochemical policy")
    sources = _exact_keys(review["sources"], {"candidate", "parsed_result", "mode_review", "scientific_decision"}, "energy review sources")
    for name in ("candidate", "parsed_result"):
        _exact_keys(sources[name], {"path", "sha256", "size_bytes", "schema", "payload_sha256"}, f"energy review {name}")
    for name in ("mode_review", "scientific_decision"):
        require(sources[name] is None or isinstance(sources[name], dict), f"energy review {name} must be an artifact or null")
        if sources[name] is not None:
            _exact_keys(sources[name], {"path", "sha256", "size_bytes", "schema", "payload_sha256"}, f"energy review {name}")
    require(
        (sources["mode_review"] is None) == (sources["scientific_decision"] is None),
        "energy review mode review and scientific decision must be supplied together",
    )
    _nonempty(review["reviewer"], "energy reviewer")
    require(re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(review["reviewed_on"])) is not None, "energy review date must use YYYY-MM-DD")
    require(isinstance(review["notes"], list) and all(isinstance(item, str) and item.strip() for item in review["notes"]), "energy review notes are invalid")
    require(review["calculation_ready"] is False and review["no_submission_authorization"] is True, "energy review widened the authority boundary")
    _validate_payload(review)


def _finite_number(value: Any, label: str, *, nullable: bool = False) -> float | None:
    if value is None and nullable:
        return None
    require(
        isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)),
        f"{label} must be a finite number" + (" or null" if nullable else ""),
    )
    return float(value)


def _validate_displacements(rows: Any, label: str, *, require_nonempty: bool = True) -> None:
    require(isinstance(rows, list), f"{label} must be an array")
    if require_nonempty:
        require(bool(rows), f"{label} must not be empty")
    for index, row in enumerate(rows, start=1):
        _exact_keys(row, {"index", "atomic_number", "x", "y", "z"}, f"{label} row {index}")
        require(row["index"] == index, f"{label} indices must be contiguous and one-based")
        require(isinstance(row["atomic_number"], int) and row["atomic_number"] > 0, f"{label} atomic number is invalid")
        for axis in ("x", "y", "z"):
            _finite_number(row[axis], f"{label} {axis}")


def _validate_specialist_ts_result(result: dict[str, Any]) -> None:
    _exact_keys(
        result,
        {
            "schema", "status", "g16_revision", "normal_termination_count", "error_termination_count",
            "optimization_completed", "stationary_point_found", "final_energy_hartree", "frequency_count",
            "frequencies_cm-1", "raw_imaginary_frequency_count", "imaginary_modes", "final_coordinates",
            "first_order_saddle_candidate", "mode_review_status", "diagnostics", "log_sha256",
        },
        "specialist TS/Freq result",
    )
    require(result["schema"] == "gaussian-ts-freq-result/1", "unrecognized specialist TS/Freq result schema")
    require(result["status"] in {"completed", "failed", "incomplete"}, "specialist TS/Freq status is invalid")
    require(result["g16_revision"] is None or isinstance(result["g16_revision"], str), "specialist G16 revision is invalid")
    for name in ("normal_termination_count", "error_termination_count", "frequency_count", "raw_imaginary_frequency_count"):
        require(isinstance(result[name], int) and not isinstance(result[name], bool) and result[name] >= 0, f"specialist {name} is invalid")
    for name in ("optimization_completed", "stationary_point_found", "first_order_saddle_candidate"):
        require(isinstance(result[name], bool), f"specialist {name} is invalid")
    _finite_number(result["final_energy_hartree"], "specialist final electronic energy", nullable=True)
    frequencies = result["frequencies_cm-1"]
    require(isinstance(frequencies, list), "specialist frequencies must be an array")
    normalized_frequencies = [_finite_number(value, "specialist frequency") for value in frequencies]
    require(result["frequency_count"] == len(frequencies), "specialist frequency count is internally inconsistent")
    negative_frequencies = [value for value in normalized_frequencies if value is not None and value < 0]
    require(result["raw_imaginary_frequency_count"] == len(negative_frequencies), "specialist imaginary-frequency count is internally inconsistent")
    try:
        specialist_classification = ts_irc.classify_ts_freq_result_facts(result)
    except (KeyError, TypeError, ValueError) as exc:
        raise AdapterError(f"TS specialist rejected parsed-result classification facts: {exc}") from exc
    require(
        result["status"] == specialist_classification["status"],
        "specialist status differs from termination-count semantics",
    )
    require(
        result["first_order_saddle_candidate"]
        == specialist_classification["first_order_saddle_candidate"],
        "specialist first-order-saddle classification differs from parsed scientific facts",
    )
    require(
        result["mode_review_status"] == specialist_classification["mode_review_status"],
        "specialist mode-review status differs from first-order-saddle classification",
    )
    modes = result["imaginary_modes"]
    require(isinstance(modes, list) and len(modes) == len(negative_frequencies), "specialist imaginary-mode table is internally inconsistent")
    for index, (mode, frequency) in enumerate(zip(modes, negative_frequencies), start=1):
        _exact_keys(mode, {"frequency_cm-1", "displacements"}, f"specialist imaginary mode {index}")
        require(_finite_number(mode["frequency_cm-1"], f"specialist imaginary mode {index} frequency") == frequency, "specialist imaginary-mode frequency differs from the frequency list")
        _validate_displacements(
            mode["displacements"],
            f"specialist imaginary mode {index} displacements",
            require_nonempty=False,
        )
    coordinates = result["final_coordinates"]
    require(isinstance(coordinates, list), "specialist final coordinates must be an array")
    for index, row in enumerate(coordinates, start=1):
        _exact_keys(row, {"index", "atomic_number", "element", "x", "y", "z"}, f"specialist final coordinate {index}")
        require(row["index"] == index, "specialist final-coordinate indices must be contiguous and one-based")
        require(isinstance(row["atomic_number"], int) and row["atomic_number"] > 0, "specialist final-coordinate atomic number is invalid")
        element = _nonempty(row["element"], f"specialist final-coordinate element {index}")
        require(element in V1_ATOMIC_NUMBERS, "specialist final-coordinate element is outside the V1 scope")
        require(
            row["atomic_number"] == V1_ATOMIC_NUMBERS[element],
            "specialist final-coordinate element and atomic number differ",
        )
        for axis in ("x", "y", "z"):
            _finite_number(row[axis], f"specialist final coordinate {index} {axis}")
    require(result["mode_review_status"] in {"pending", "not_eligible"}, "specialist mode-review status is invalid")
    require(isinstance(result["diagnostics"], list) and all(isinstance(item, str) for item in result["diagnostics"]), "specialist diagnostics are invalid")
    _hash(result["log_sha256"], "specialist log SHA-256")


def _validate_mode_review(
    review: dict[str, Any], result_path: Path, result: dict[str, Any]
) -> None:
    _exact_keys(
        review,
        {
            "schema", "ts_result_sha256", "imaginary_frequency_cm-1", "amplitude",
            "distance_projections", "displacements", "visualization_artifacts", "scientific_decision",
        },
        "specialist mode review",
    )
    require(review["schema"] == "gaussian-ts-mode-review/1", "energy lineage mode review has the wrong schema")
    require(review["ts_result_sha256"] == rw.sha256_file(result_path), "mode review parsed-result hash mismatch")
    _finite_number(review["imaginary_frequency_cm-1"], "mode-review imaginary frequency")
    _finite_number(review["amplitude"], "mode-review amplitude")
    _validate_displacements(review["displacements"], "mode-review displacements")
    require(isinstance(review["distance_projections"], list), "mode-review distance projections must be an array")
    for index, projection in enumerate(review["distance_projections"], start=1):
        _exact_keys(
            projection,
            {"pair", "equilibrium_angstrom", "plus_angstrom", "minus_angstrom", "plus_minus_change_angstrom"},
            f"mode-review distance projection {index}",
        )
        require(isinstance(projection["pair"], list), "mode-review atom pair must be an array")
        for name in ("equilibrium_angstrom", "plus_angstrom", "minus_angstrom", "plus_minus_change_angstrom"):
            _finite_number(projection[name], f"mode-review {name}")
    try:
        ts_irc.validate_mode_review_geometry(result, review)
    except (KeyError, TypeError, ValueError) as exc:
        raise AdapterError(f"TS specialist mode-review geometry validation failed: {exc}") from exc
    require(isinstance(review["visualization_artifacts"], list) and all(isinstance(item, str) and item for item in review["visualization_artifacts"]), "mode-review visualization artifacts are invalid")
    require(review["scientific_decision"] == "required", "mode review is not pending a scientific decision")


def _validate_mode_decision(
    decision: dict[str, Any], result_path: Path, review_path: Path
) -> None:
    _exact_keys(
        decision,
        {"schema", "mode_review_sha256", "ts_result_sha256", "imaginary_frequency_cm-1", "decision", "confirmed"},
        "specialist mode decision",
    )
    require(decision["schema"] == "gaussian-ts-mode-decision/1", "energy lineage decision has the wrong schema")
    require(decision["ts_result_sha256"] == rw.sha256_file(result_path), "mode decision parsed-result hash mismatch")
    require(decision["mode_review_sha256"] == rw.sha256_file(review_path), "mode decision review hash mismatch")
    _finite_number(decision["imaginary_frequency_cm-1"], "mode-decision imaginary frequency", nullable=True)
    require(decision["decision"] in {"accepted", "rejected", "unclear"}, "mode decision value is invalid")
    require(decision["confirmed"] is True, "mode decision is not explicitly confirmed")


def _validate_candidate_result_identity(
    candidate: dict[str, Any], parsed: dict[str, Any]
) -> None:
    require(candidate.get("schema") == "gaussian-asymmetric-ts-candidate/1", "energy projection requires an asymmetric candidate")
    try:
        asym_contract.validate_structure(candidate, "candidate")
    except ValueError as exc:
        raise AdapterError(f"asymmetric-catalysis specialist validator rejected candidate: {exc}") from exc
    require(parsed.get("schema") == "gaussian-ts-freq-result/1", "V1 energy projection accepts only specialist TS/Freq JSON, never raw logs")
    _validate_specialist_ts_result(parsed)
    atom_map = candidate.get("atom_map")
    require(isinstance(atom_map, list) and atom_map, "energy candidate atom map is missing")
    coordinates = parsed["final_coordinates"]
    require(
        len(coordinates) == len(atom_map)
        and [row.get("index") for row in coordinates] == [row.get("index") for row in atom_map]
        and [row.get("element") for row in coordinates] == [row.get("element") for row in atom_map],
        "parsed final-coordinate atom count, order, or elements differ from the energy candidate",
    )


def _validated_energy_review_chain(
    review: dict[str, Any], review_path: Path
) -> tuple[
    Path,
    dict[str, Any],
    Path,
    dict[str, Any],
    Path | None,
    dict[str, Any] | None,
    Path | None,
    dict[str, Any] | None,
]:
    candidate_path, candidate = _resolve_reference(
        review["sources"]["candidate"], review_path, "energy review candidate"
    )
    parsed_path, parsed = _resolve_reference(
        review["sources"]["parsed_result"], review_path, "energy review parsed result"
    )
    require(candidate is not None and parsed is not None, "energy review candidate and parsed result must be JSON artifacts")
    _validate_candidate_result_identity(candidate, parsed)
    require(review["candidate_id"] == candidate.get("candidate_id"), "energy review candidate ID mismatch")
    mode_path: Path | None = None
    mode_review: dict[str, Any] | None = None
    decision_path: Path | None = None
    decision: dict[str, Any] | None = None
    if review["sources"]["mode_review"] is not None:
        mode_path, mode_review = _resolve_reference(
            review["sources"]["mode_review"], review_path, "energy mode review"
        )
        decision_path, decision = _resolve_reference(
            review["sources"]["scientific_decision"], review_path, "energy scientific decision"
        )
        require(mode_review is not None and decision is not None, "energy scientific-review sources must be JSON artifacts")
        _validate_mode_review(mode_review, parsed_path, parsed)
        _validate_mode_decision(decision, parsed_path, mode_path)
        require(
            decision["imaginary_frequency_cm-1"] == mode_review["imaginary_frequency_cm-1"],
            "mode decision imaginary frequency differs from the reviewed mode",
        )
    return candidate_path, candidate, parsed_path, parsed, mode_path, mode_review, decision_path, decision


def build_energy_projection(
    candidate_path: Path,
    parsed_result_path: Path,
    review_path: Path,
    output_record: Path,
    output_lineage: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    require(
        output_record.expanduser().resolve() != output_lineage.expanduser().resolve(),
        "energy record and lineage outputs must be distinct",
    )
    output_record = _output_path(output_record, "energy record")
    output_lineage = _output_path(output_lineage, "energy lineage")
    candidate_path, candidate = _load_json(candidate_path, "candidate")
    require(
        parsed_result_path.suffix.lower() == ".json",
        "V1 energy projection accepts only specialist TS/Freq JSON, never raw logs",
    )
    parsed_result_path, parsed = _load_json(parsed_result_path, "specialist parsed result")
    review_path, review = _load_json(review_path, "energy review")
    _validate_energy_review(review)
    (
        bound_candidate_path,
        bound_candidate,
        bound_parsed_path,
        bound_parsed,
        mode_review_path,
        mode_review,
        decision_path,
        mode_decision,
    ) = _validated_energy_review_chain(review, review_path)
    require(
        bound_candidate_path == candidate_path and bound_candidate == candidate,
        "energy review candidate differs from the supplied candidate",
    )
    require(
        bound_parsed_path == parsed_result_path and bound_parsed == parsed,
        "energy review parsed result differs from the supplied result",
    )

    value = parsed.get("final_energy_hartree")
    finite_energy = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))
    projection_reviewed = review["decision"] == "accept_electronic_only"
    scientific_review_present = mode_decision is not None and mode_review is not None
    if projection_reviewed:
        require(review["allowed_projection_fields"] == ["final_energy_hartree"], "accepted electronic-only review must enumerate final_energy_hartree")
    status = "electronic_only" if projection_reviewed and finite_energy and scientific_review_present else "blocked"
    blockers = [
        "thermal_gibbs_correction_absent",
        "standard_state_not_reviewed",
        "low_frequency_policy_not_reviewed",
        "common_reference_not_reviewed",
        "comparison_energy_not_authorized",
    ]
    if not finite_energy:
        blockers.append("finite_final_electronic_energy_absent")
    if not projection_reviewed:
        blockers.append("energy_review_blocked")
    if not scientific_review_present:
        blockers.append("scientific_review_artifacts_absent")
    record = _finalize(
        {
            "schema": ENERGY_RECORD_SCHEMA,
            "energy_record_id": _bounded_derived_id("energy", review["review_id"]),
            "candidate_id": candidate["candidate_id"],
            "status": status,
            "energy": {
                "electronic_energy": {"value": float(value) if status == "electronic_only" else None, "unit": "hartree", "source_field": "final_energy_hartree"},
                "thermal_gibbs_correction": None,
                "comparison_free_energy": None,
            },
            "scientific_classification": {
                "parsed_result_schema": parsed["schema"],
                "parsed_status": parsed.get("status"),
                "first_order_saddle_candidate": parsed.get("first_order_saddle_candidate"),
                "mode_decision": mode_decision.get("decision") if mode_decision else None,
            },
            "comparison_eligible": False,
            "blockers": sorted(blockers),
            "calculation_ready": False,
            "no_submission_authorization": True,
        }
    )
    lineage = _finalize(
        {
            "schema": ENERGY_LINEAGE_SCHEMA,
            "lineage_id": _bounded_derived_id("lineage", review["review_id"]),
            "candidate_id": candidate["candidate_id"],
            "sources": {
                "candidate": artifact_ref(candidate_path, candidate),
                "parsed_result": artifact_ref(parsed_result_path, parsed),
                "energy_review": artifact_ref(review_path, review),
                "mode_review": artifact_ref(mode_review_path, mode_review) if mode_review_path and mode_review else None,
                "scientific_decision": artifact_ref(decision_path, mode_decision) if decision_path and mode_decision else None,
                "energy_record": _json_artifact_ref(output_record, record),
            },
            "projected_fields": [
                {
                    "source": "parsed_result.final_energy_hartree",
                    "target": "energy.electronic_energy.value",
                    "unit": "hartree",
                }
            ] if status == "electronic_only" else [],
            "omitted_fields": [
                {"field": "thermal_gibbs_correction", "reason": "not present in gaussian-ts-freq-result/1"},
                {"field": "comparison_free_energy", "reason": "no reviewed thermal policy or common reference"},
            ],
            "specialist_classification_preserved": True,
            "comparison_eligible": False,
            "blockers": sorted(blockers),
            "calculation_ready": False,
            "no_submission_authorization": True,
        }
    )
    _write_new_json(output_record, record)
    _write_new_json(output_lineage, lineage)
    return record, lineage


def _validate_sanitized_job(job: dict[str, Any]) -> None:
    _validate_adapter_document(job)
    _exact_keys(
        job,
        {
            "schema", "observation_id", "source_job_sha256", "input_sha256", "status",
            "last_inspection_state", "redacted_fields", "calculation_ready",
            "no_submission_authorization", "payload_sha256",
        },
        "sanitized job observation",
    )
    require(job["schema"] == SANITIZED_JOB_SCHEMA, "unrecognized sanitized-job schema")
    _id(job["observation_id"], "job observation_id")
    _hash(job["source_job_sha256"], "source job SHA-256")
    _hash(job["input_sha256"], "job input SHA-256")
    _nonempty(job["status"], "job status")
    require(job["last_inspection_state"] is None or isinstance(job["last_inspection_state"], str), "job last-inspection state is invalid")
    require(isinstance(job["redacted_fields"], list) and {"job_id", "remote_workdir"} <= set(job["redacted_fields"]), "sanitized job must record job_id and remote_workdir redaction")
    require(job["calculation_ready"] is False and job["no_submission_authorization"] is True, "sanitized job widened the authority boundary")
    _validate_payload(job)


def _validate_terminal_intake(intake: dict[str, Any]) -> None:
    _exact_keys(
        intake,
        {
            "schema", "template_id", "template_sha256", "template_payload_sha256", "task_kind",
            "project", "runtime_job_id", "artifacts", "terminal_evidence", "automatic_action_authorized",
            "acceptance_status", "outcome", "scientific_evidence", "path_validated", "next_required_artifacts",
        },
        "specialist terminal intake",
    )
    require(intake["schema"] == "gaussian-terminal-intake/1", "attempt link requires specialist terminal intake")
    _id(intake["template_id"], "terminal intake template_id")
    _hash(intake["template_sha256"], "terminal intake template SHA-256")
    _hash(intake["template_payload_sha256"], "terminal intake template payload SHA-256")
    require(intake["task_kind"] == "ts_freq", "V1 attempt link requires a TS/Freq terminal intake")
    _nonempty(intake["project"], "terminal intake project")
    require(intake["runtime_job_id"] is None or isinstance(intake["runtime_job_id"], (str, int)), "terminal runtime job ID is invalid")
    artifacts = _exact_keys(intake["artifacts"], {"input_sha256", "job_sha256", "log_sha256", "log_size_bytes"}, "terminal intake artifacts")
    for name in ("input_sha256", "job_sha256", "log_sha256"):
        _hash(artifacts[name], f"terminal intake {name}")
    require(isinstance(artifacts["log_size_bytes"], int) and artifacts["log_size_bytes"] > 0, "terminal intake log size is invalid")
    evidence = _exact_keys(
        intake["terminal_evidence"],
        {
            "status", "job_state", "results_fetched", "process_alive", "submission_transport_hashes_verified",
            "normal_termination_count", "error_termination_count",
        },
        "terminal intake evidence",
    )
    require(evidence["status"] == "passed", "terminal evidence status is not passed")
    _nonempty(evidence["job_state"], "terminal evidence job_state")
    require(evidence["results_fetched"] is True, "terminal intake does not record fetched results")
    require(evidence["process_alive"] is None or isinstance(evidence["process_alive"], bool), "terminal process-alive observation is invalid")
    require(evidence["submission_transport_hashes_verified"] is True, "terminal transport hashes were not verified")
    for name in ("normal_termination_count", "error_termination_count"):
        require(isinstance(evidence[name], int) and evidence[name] >= 0, f"terminal evidence {name} is invalid")
    require(intake["automatic_action_authorized"] is False, "terminal intake unexpectedly authorizes an automatic action")
    require(intake["acceptance_status"] in {"manual_review_required", "not_accepted"}, "terminal intake acceptance status is invalid")
    require(
        intake["outcome"] in {
            "error_or_interrupted_termination", "nonstationary_or_incomplete",
            "incomplete_frequency_analysis", "zero_imaginary_modes",
            "multiple_imaginary_modes", "ready_for_manual_mode_review",
        },
        "terminal intake outcome is invalid",
    )
    require(
        (intake["outcome"] == "ready_for_manual_mode_review")
        == (intake["acceptance_status"] == "manual_review_required"),
        "terminal intake outcome/acceptance status is inconsistent",
    )
    scientific = _exact_keys(
        intake["scientific_evidence"],
        {
            "optimization_completed", "stationary_point_found", "atom_count", "expected_atom_count",
            "frequency_count", "expected_frequency_count", "raw_imaginary_frequency_count",
            "imaginary_frequencies_cm-1", "first_order_saddle_candidate", "mode_review_status",
        },
        "terminal scientific evidence",
    )
    for name in ("optimization_completed", "stationary_point_found", "first_order_saddle_candidate"):
        require(isinstance(scientific[name], bool), f"terminal scientific evidence {name} is invalid")
    for name in ("atom_count", "expected_atom_count", "frequency_count", "expected_frequency_count", "raw_imaginary_frequency_count"):
        require(isinstance(scientific[name], int) and scientific[name] >= 0, f"terminal scientific evidence {name} is invalid")
    require(isinstance(scientific["imaginary_frequencies_cm-1"], list), "terminal imaginary frequencies are invalid")
    for value in scientific["imaginary_frequencies_cm-1"]:
        _finite_number(value, "terminal imaginary frequency")
    require(scientific["mode_review_status"] in {"pending", "not_eligible"}, "terminal mode-review status is invalid")
    require(
        len(scientific["imaginary_frequencies_cm-1"]) == scientific["raw_imaginary_frequency_count"]
        and all(value < 0 for value in scientific["imaginary_frequencies_cm-1"]),
        "terminal imaginary-frequency facts are internally inconsistent",
    )
    try:
        specialist_classification = ts_irc.classify_ts_freq_terminal_facts(
            job_state=evidence["job_state"],
            error_termination_count=evidence["error_termination_count"],
            optimization_completed=scientific["optimization_completed"],
            stationary_point_found=scientific["stationary_point_found"],
            atom_count=scientific["atom_count"],
            expected_atom_count=scientific["expected_atom_count"],
            frequency_count=scientific["frequency_count"],
            expected_frequency_count=scientific["expected_frequency_count"],
            raw_imaginary_frequency_count=scientific["raw_imaginary_frequency_count"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise AdapterError(f"TS specialist rejected terminal classification facts: {exc}") from exc
    require(intake["outcome"] == specialist_classification["outcome"], "terminal outcome differs from specialist TS/Freq semantics")
    require(
        intake["acceptance_status"] == specialist_classification["acceptance_status"],
        "terminal acceptance status differs from specialist TS/Freq semantics",
    )
    require(
        scientific["first_order_saddle_candidate"]
        is specialist_classification["first_order_saddle_candidate"]
        and scientific["mode_review_status"] == specialist_classification["mode_review_status"],
        "terminal scientific classification differs from specialist TS/Freq semantics",
    )
    require(intake["path_validated"] is False, "TS/Freq terminal intake cannot claim path validation")
    require(isinstance(intake["next_required_artifacts"], list) and all(isinstance(item, str) and item for item in intake["next_required_artifacts"]), "terminal next-required-artifact list is invalid")
    require(
        intake["next_required_artifacts"] == specialist_classification["next_required_artifacts"],
        "terminal next-required artifacts differ from specialist TS/Freq semantics",
    )


def build_attempt_link(
    external_target_key: str,
    input_handoff_path: Path,
    sanitized_job_path: Path,
    terminal_intake_path: Path,
    parsed_result_path: Path,
    mode_review_path: Path,
    scientific_decision_path: Path,
    output: Path,
    attempt_link_id: str,
) -> dict[str, Any]:
    output = _output_path(output, "attempt link")
    require(EXTERNAL_KEY_RE.fullmatch(external_target_key) is not None, "invalid external_target_key")
    _id(attempt_link_id, "attempt_link_id")
    input_handoff_path, handoff = _load_json(input_handoff_path, "input handoff")
    sanitized_job_path, job = _load_json(sanitized_job_path, "sanitized job observation")
    terminal_intake_path, intake = _load_json(terminal_intake_path, "terminal intake")
    parsed_result_path, parsed = _load_json(parsed_result_path, "specialist parsed result")
    mode_review_path, mode_review = _load_json(mode_review_path, "specialist mode review")
    scientific_decision_path, decision = _load_json(scientific_decision_path, "scientific decision")
    require(handoff.get("schema") == INPUT_HANDOFF_SCHEMA, "attempt link requires a candidate-input handoff")
    _validate_adapter_document(handoff)
    _validate_payload(handoff)
    # A valid hash over a forged derived handoff is not sufficient.  Recheck
    # its exact references and deterministic candidate/protocol/review
    # reconstruction before accepting it as attempt lineage.
    _validate_all_artifact_references(handoff, input_handoff_path, "attempt input-handoff reference")
    _validate_protocol_references(handoff, input_handoff_path)
    _validate_derived_semantics(handoff, input_handoff_path)
    require(handoff.get("external_target_key") == external_target_key, "attempt link target differs from input handoff")
    input_path, _ = _resolve_reference(handoff["input"], input_handoff_path, "input handoff Gaussian input")
    require(input_path.suffix.lower() == ".gjf", "input handoff does not reference a .gjf input")
    _validate_sanitized_job(job)
    _validate_terminal_intake(intake)
    _validate_specialist_ts_result(parsed)
    _validate_mode_review(mode_review, parsed_result_path, parsed)
    _validate_mode_decision(decision, parsed_result_path, mode_review_path)
    require(
        parsed["first_order_saddle_candidate"] is True and len(parsed["imaginary_modes"]) == 1,
        "attempt mode-review artifacts require an eligible first-order-saddle result",
    )
    require(
        mode_review["imaginary_frequency_cm-1"] == parsed["imaginary_modes"][0]["frequency_cm-1"]
        and mode_review["displacements"] == parsed["imaginary_modes"][0]["displacements"],
        "attempt mode review differs from the parsed result",
    )
    input_sha = handoff.get("input", {}).get("sha256")
    require(job["input_sha256"] == input_sha, "sanitized job input hash differs from handoff")
    intake_artifacts = intake.get("artifacts", {})
    require(intake_artifacts.get("input_sha256") == input_sha, "terminal intake input hash differs from handoff")
    require(job["source_job_sha256"] == intake_artifacts.get("job_sha256"), "sanitized job source hash differs from terminal intake")
    require(parsed.get("log_sha256") == intake_artifacts.get("log_sha256"), "parsed result log hash differs from terminal intake")
    terminal = intake["terminal_evidence"]
    scientific = intake["scientific_evidence"]
    require(job["status"] == terminal["job_state"], "sanitized job status differs from terminal intake")
    require(
        terminal["normal_termination_count"] == parsed["normal_termination_count"]
        and terminal["error_termination_count"] == parsed["error_termination_count"],
        "terminal termination counts differ from parsed result",
    )
    require(
        scientific["optimization_completed"] == parsed["optimization_completed"]
        and scientific["stationary_point_found"] == parsed["stationary_point_found"]
        and scientific["frequency_count"] == parsed["frequency_count"]
        and scientific["raw_imaginary_frequency_count"] == parsed["raw_imaginary_frequency_count"]
        and scientific["first_order_saddle_candidate"] == parsed["first_order_saddle_candidate"]
        and scientific["mode_review_status"] == parsed["mode_review_status"],
        "terminal scientific facts differ from parsed result",
    )
    require(
        scientific["atom_count"] == len(parsed["final_coordinates"])
        and scientific["expected_atom_count"] == handoff["identity"]["atom_count"],
        "terminal atom counts differ from parsed result or input handoff",
    )
    require(
        [row["index"] for row in parsed["final_coordinates"]]
        == [row["index"] for row in handoff["identity"]["atom_order"]]
        and [row["element"] for row in parsed["final_coordinates"]]
        == [row["element"] for row in handoff["identity"]["atom_order"]],
        "parsed final-coordinate atom order or elements differ from input handoff",
    )
    require(
        scientific["imaginary_frequencies_cm-1"]
        == [mode["frequency_cm-1"] for mode in parsed["imaginary_modes"]],
        "terminal imaginary frequencies differ from parsed result",
    )
    require(
        intake["outcome"] == "ready_for_manual_mode_review"
        and intake["acceptance_status"] == "manual_review_required"
        and parsed["first_order_saddle_candidate"] is True,
        "scientific decision is not downstream of a review-eligible TS/Freq intake",
    )
    require(
        intake["next_required_artifacts"]
        == ["gaussian-ts-freq-result/1", "gaussian-ts-mode-review/1", "gaussian-ts-mode-decision/1"],
        "terminal next-required-artifact list differs from the specialist TS/Freq contract",
    )
    if parsed["imaginary_modes"]:
        require(
            decision["imaginary_frequency_cm-1"] == parsed["imaginary_modes"][0]["frequency_cm-1"],
            "scientific decision imaginary frequency differs from parsed result",
        )
    document = _finalize(
        {
            "schema": ATTEMPT_LINK_SCHEMA,
            "attempt_link_id": attempt_link_id,
            "external_target_key": external_target_key,
            "artifacts": {
                "input_handoff": artifact_ref(input_handoff_path, handoff),
                "sanitized_job_observation": artifact_ref(sanitized_job_path, job),
                "terminal_intake": artifact_ref(terminal_intake_path, intake),
                "parsed_result": artifact_ref(parsed_result_path, parsed),
                "mode_review": artifact_ref(mode_review_path, mode_review),
                "scientific_decision": artifact_ref(scientific_decision_path, decision),
            },
            "preserved_classifications": {
                "job_status": job["status"],
                "job_last_inspection_state": job["last_inspection_state"],
                "terminal_job_state": intake.get("terminal_evidence", {}).get("job_state"),
                "terminal_acceptance_status": intake.get("acceptance_status"),
                "terminal_outcome": intake.get("outcome"),
                "parsed_result_status": parsed.get("status"),
                "scientific_decision": decision.get("decision"),
            },
            "classification_policy": "specialist_values_preserved_without_reclassification",
            "calculation_ready": False,
            "no_submission_authorization": True,
        }
    )
    _write_new_json(output, document)
    return document


def _validate_referenced_document(document: dict[str, Any], path: Path, label: str) -> None:
    schema = document.get("schema")
    if schema in ADAPTER_SCHEMA_PATHS:
        _validate_adapter_document(document)
        _validate_payload(document)
    elif schema == "gaussian-ts-freq-result/1":
        _validate_specialist_ts_result(document)
    elif schema == "gaussian-asymmetric-catalysis-study/1":
        try:
            asym_contract.validate_study(document)
        except ValueError as exc:
            raise AdapterError(f"{label} failed asymmetric-study validation: {exc}") from exc
    elif schema == "gaussian-asymmetric-candidate-ledger/1":
        try:
            asym_contract.validate_ledger(document)
        except ValueError as exc:
            raise AdapterError(f"{label} failed asymmetric-ledger validation: {exc}") from exc
    elif schema == "gaussian-asymmetric-ts-candidate/1":
        try:
            asym_contract.validate_structure(document, "candidate")
        except ValueError as exc:
            raise AdapterError(f"{label} failed asymmetric-candidate validation: {exc}") from exc


def _validate_all_artifact_references(value: Any, owner: Path, label: str = "artifact") -> None:
    artifact_keys = {"path", "sha256", "size_bytes", "schema", "payload_sha256"}
    if isinstance(value, dict):
        if set(value) == artifact_keys:
            resolved, document = _resolve_reference(value, owner, label)
            if document is not None:
                _validate_referenced_document(document, resolved, label)
            return
        for key, child in value.items():
            _validate_all_artifact_references(child, owner, f"{label}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _validate_all_artifact_references(child, owner, f"{label}[{index}]")


def _validate_protocol_references(document: dict[str, Any], owner: Path) -> None:
    sources = document.get("sources")
    if not isinstance(sources, dict) or "protocol_options" not in sources or "protocol_selection" not in sources:
        return
    options_path, options = _resolve_reference(sources["protocol_options"], owner, "protocol options")
    selection_path, selection = _resolve_reference(sources["protocol_selection"], owner, "protocol selection")
    require(options is not None and selection is not None, "protocol references must be JSON artifacts")
    try:
        loaded_selection, loaded_options, _selected = protocol.load_validated_selection(selection_path, options_path)
    except (protocol.ContractError, OSError, json.JSONDecodeError) as exc:
        raise AdapterError(f"protocol-selection specialist validator rejected referenced artifacts: {exc}") from exc
    require(loaded_options == options and loaded_selection == selection, "protocol references changed during validation")


def _ref_path(reference: dict[str, Any], owner: Path, label: str) -> Path:
    resolved, _document = _resolve_reference(reference, owner, label)
    return resolved


def _ref_json(reference: dict[str, Any], owner: Path, label: str) -> tuple[Path, dict[str, Any]]:
    resolved, document = _resolve_reference(reference, owner, label)
    require(document is not None, f"{label} must be a JSON artifact")
    return resolved, document


def _refinalize(document: dict[str, Any]) -> dict[str, Any]:
    rebuilt = copy.deepcopy(document)
    rebuilt.pop("payload_sha256", None)
    return _finalize(rebuilt)


def _validate_derived_semantics(document: dict[str, Any], owner: Path) -> None:
    schema = document["schema"]
    if schema == TARGET_IMPORT_SCHEMA:
        study_path = _ref_path(document["study_source"], owner, "target-import study")
        ledger_path = _ref_path(document["ledger_source"], owner, "target-import ledger")
        with tempfile.TemporaryDirectory(prefix="auto-g16-target-validation-") as temporary:
            expected = build_target_import(
                study_path,
                ledger_path,
                Path(temporary).resolve() / "target-import.json",
                document["import_id"],
            )
        require(document == expected, "target import differs from deterministic ledger-derived facts")
        return

    if schema == INPUT_HANDOFF_SCHEMA:
        sources = document["sources"]
        study_path = _ref_path(sources["study"], owner, "handoff study")
        candidate_path = _ref_path(sources["candidate"], owner, "handoff candidate")
        options_path = _ref_path(sources["protocol_options"], owner, "handoff protocol options")
        selection_path = _ref_path(sources["protocol_selection"], owner, "handoff protocol selection")
        review_path = _ref_path(sources["input_review"], owner, "handoff input review")
        bound_input_path = _ref_path(document["input"], owner, "handoff exact input")
        require(
            document["input"]["path"] == _portable(bound_input_path),
            "input handoff exact input path is not the canonical repository-bound locator",
        )
        with tempfile.TemporaryDirectory(prefix="auto-g16-handoff-validation-") as temporary:
            temporary_root = Path(temporary).resolve()
            _input_bytes, expected = build_input_handoff(
                study_path,
                candidate_path,
                options_path,
                selection_path,
                review_path,
                temporary_root / "recomputed.gjf",
                temporary_root / "recomputed.handoff.json",
            )
        require(
            {key: value for key, value in expected["input"].items() if key != "path"}
            == {key: value for key, value in document["input"].items() if key != "path"},
            "input handoff exact input facts differ from deterministic reconstruction",
        )
        expected["input"]["path"] = document["input"]["path"]
        expected = _refinalize(expected)
        require(document == expected, "input handoff differs from deterministic reviewed-source reconstruction")
        return

    if schema == ENERGY_REVIEW_SCHEMA:
        _validated_energy_review_chain(document, owner)
        return

    if schema == ENERGY_RECORD_SCHEMA:
        raise AdapterError(
            "a reviewed energy record has no standalone source pointers; validate its gaussian-energy-lineage/1 sidecar"
        )

    if schema == ENERGY_LINEAGE_SCHEMA:
        sources = document["sources"]
        candidate_path = _ref_path(sources["candidate"], owner, "energy-lineage candidate")
        parsed_path = _ref_path(sources["parsed_result"], owner, "energy-lineage parsed result")
        review_path = _ref_path(sources["energy_review"], owner, "energy-lineage review")
        record_path, record = _ref_json(sources["energy_record"], owner, "energy-lineage record")
        require(
            sources["energy_record"]["path"] == _portable(record_path),
            "energy lineage record path is not the canonical repository-bound locator",
        )
        with tempfile.TemporaryDirectory(prefix="auto-g16-energy-validation-") as temporary:
            temporary_root = Path(temporary).resolve()
            expected_record, expected_lineage = build_energy_projection(
                candidate_path,
                parsed_path,
                review_path,
                temporary_root / "energy-record.json",
                temporary_root / "energy-lineage.json",
            )
        require(record == expected_record, "energy record differs from reviewed specialist-result projection")
        require(
            {key: value for key, value in expected_lineage["sources"]["energy_record"].items() if key != "path"}
            == {key: value for key, value in document["sources"]["energy_record"].items() if key != "path"},
            "energy lineage record reference differs from deterministic reconstruction",
        )
        expected_lineage["sources"]["energy_record"]["path"] = document["sources"]["energy_record"]["path"]
        expected_lineage = _refinalize(expected_lineage)
        require(document == expected_lineage, "energy lineage differs from deterministic reviewed-source reconstruction")
        return

    if schema == ATTEMPT_LINK_SCHEMA:
        artifacts = document["artifacts"]
        handoff_path = _ref_path(artifacts["input_handoff"], owner, "attempt input handoff")
        job_path = _ref_path(artifacts["sanitized_job_observation"], owner, "attempt sanitized job")
        intake_path = _ref_path(artifacts["terminal_intake"], owner, "attempt terminal intake")
        parsed_path = _ref_path(artifacts["parsed_result"], owner, "attempt parsed result")
        mode_review_path = _ref_path(artifacts["mode_review"], owner, "attempt mode review")
        decision_path = _ref_path(artifacts["scientific_decision"], owner, "attempt scientific decision")
        with tempfile.TemporaryDirectory(prefix="auto-g16-attempt-validation-") as temporary:
            expected = build_attempt_link(
                document["external_target_key"],
                handoff_path,
                job_path,
                intake_path,
                parsed_path,
                mode_review_path,
                decision_path,
                Path(temporary).resolve() / "attempt-link.json",
                document["attempt_link_id"],
            )
        require(document == expected, "attempt link differs from deterministic observation-derived facts")


def validate_artifact(path: Path) -> dict[str, Any]:
    path, document = _load_json(path, "adapter artifact")
    schema = document.get("schema")
    require(
        schema in {
            TARGET_IMPORT_SCHEMA, INPUT_REVIEW_SCHEMA, INPUT_HANDOFF_SCHEMA, ENERGY_REVIEW_SCHEMA,
            ENERGY_RECORD_SCHEMA, ENERGY_LINEAGE_SCHEMA, SANITIZED_JOB_SCHEMA, ATTEMPT_LINK_SCHEMA,
        },
        "unsupported calculation-artifact schema",
    )
    _validate_adapter_document(document)
    if schema == INPUT_REVIEW_SCHEMA:
        _validate_input_review(document, path)
    elif schema == ENERGY_REVIEW_SCHEMA:
        _validate_energy_review(document)
    elif schema == SANITIZED_JOB_SCHEMA:
        _validate_sanitized_job(document)
    else:
        _validate_payload(document)
    _validate_all_artifact_references(document, path, f"{schema} reference")
    _validate_protocol_references(document, path)
    _validate_derived_semantics(document, path)
    return {"valid": True, "schema": schema, "payload_sha256": document.get("payload_sha256"), "live_actions": False}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    targets = sub.add_parser("export-targets")
    targets.add_argument("ledger")
    targets.add_argument("--study", required=True)
    targets.add_argument("--import-id", required=True)
    targets.add_argument("--output", required=True)
    handoff = sub.add_parser("build-input-handoff")
    handoff.add_argument("candidate")
    handoff.add_argument("--study", required=True)
    handoff.add_argument("--options", required=True)
    handoff.add_argument("--selection", required=True)
    handoff.add_argument("--review", required=True)
    handoff.add_argument("--output-input", required=True)
    handoff.add_argument("--output-manifest", required=True)
    energy = sub.add_parser("project-energy")
    energy.add_argument("candidate")
    energy.add_argument("parsed_result")
    energy.add_argument("--review", required=True)
    energy.add_argument("--output-record", required=True)
    energy.add_argument("--output-lineage", required=True)
    attempt = sub.add_parser("link-attempt")
    attempt.add_argument("--external-target-key", required=True)
    attempt.add_argument("--input-handoff", required=True)
    attempt.add_argument("--sanitized-job", required=True)
    attempt.add_argument("--terminal-intake", required=True)
    attempt.add_argument("--parsed-result", required=True)
    attempt.add_argument("--mode-review", required=True)
    attempt.add_argument("--scientific-decision", required=True)
    attempt.add_argument("--attempt-link-id", required=True)
    attempt.add_argument("--output", required=True)
    validate = sub.add_parser("validate")
    validate.add_argument("artifact")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "export-targets":
            document = build_target_import(Path(args.study), Path(args.ledger), Path(args.output), args.import_id)
            summary = {"schema": document["schema"], "targets": document["counts"]["targets"], "live_actions": False}
        elif args.command == "build-input-handoff":
            input_bytes, document = build_input_handoff(
                Path(args.study), Path(args.candidate), Path(args.options), Path(args.selection),
                Path(args.review), Path(args.output_input), Path(args.output_manifest),
            )
            summary = {"schema": document["schema"], "input_sha256": document["input"]["sha256"], "input_size_bytes": len(input_bytes), "live_actions": False}
        elif args.command == "project-energy":
            record, lineage = build_energy_projection(
                Path(args.candidate), Path(args.parsed_result), Path(args.review),
                Path(args.output_record), Path(args.output_lineage),
            )
            summary = {"schema": record["schema"], "status": record["status"], "lineage_payload_sha256": lineage["payload_sha256"], "live_actions": False}
        elif args.command == "link-attempt":
            document = build_attempt_link(
                args.external_target_key, Path(args.input_handoff), Path(args.sanitized_job),
                Path(args.terminal_intake), Path(args.parsed_result), Path(args.mode_review),
                Path(args.scientific_decision),
                Path(args.output), args.attempt_link_id,
            )
            summary = {"schema": document["schema"], "payload_sha256": document["payload_sha256"], "live_actions": False}
        else:
            summary = validate_artifact(Path(args.artifact))
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    except (AdapterError, rw.OfflineError, protocol.ContractError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
