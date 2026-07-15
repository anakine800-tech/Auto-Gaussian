#!/usr/bin/env python3
"""Offline candidate, calculation-DAG, and derived study-index orchestration.

The orchestrator connects reviewed immutable artifacts.  It materializes only
explicitly reviewed Cartesian seeds, plans finite dependency graphs, and
derives current study state from validated files.  It never renders Gaussian
input, submits work, changes chemistry, retries, or performs a live action.
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
SKILLS_DIR = SCRIPT_DIR.parents[1]
LITERATURE_SCRIPTS = SKILLS_DIR / "auto-g16-reaction-literature" / "scripts"
PROTOCOL_SCRIPTS = SKILLS_DIR / "auto-g16-rtwin-pbs" / "scripts"
for directory in (LITERATURE_SCRIPTS, PROTOCOL_SCRIPTS):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

import reaction_workflow as rw  # noqa: E402
import mechanism_network as mn  # noqa: E402
import literature_search as lit  # noqa: E402
import mechanism_support as ms  # noqa: E402
import protocol_selection as protocol  # noqa: E402
import ts_precedent_map as tsp  # noqa: E402


CANDIDATE_REVIEW_SCHEMA = "gaussian-reaction-candidate-construction-review/1"
CANDIDATE_SCHEMA = "gaussian-reaction-candidate-materialization/1"
STATE_CANDIDATE_REVIEW_SCHEMA = "gaussian-reaction-state-candidate-construction-review/1"
STATE_CANDIDATE_SCHEMA = "gaussian-reaction-state-candidate-materialization/1"
DAG_REVIEW_SCHEMA = "gaussian-reaction-calculation-dag-review/1"
DAG_SCHEMA = "gaussian-reaction-calculation-dag/1"
INDEX_SCHEMA = "gaussian-reaction-study-index/1"

COMPUTE_NODE_TYPES = {
    "minimum_opt_freq", "transition_state_opt_freq", "single_point",
    "irc_forward", "irc_reverse", "endpoint_opt_freq",
}
ANALYSIS_NODE_TYPES = {"thermochemistry", "kinetics", "report"}
NODE_TYPES = COMPUTE_NODE_TYPES | ANALYSIS_NODE_TYPES
STATE_NODE_TYPES = {"minimum_opt_freq"}
EDGE_NODE_TYPES = {"transition_state_opt_freq", "irc_forward", "irc_reverse", "endpoint_opt_freq"}
FLEXIBLE_NODE_TYPES = {"single_point"}
TRANSITION_METALS = {
    "Sc", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn",
    "Y", "Zr", "Nb", "Mo", "Tc", "Ru", "Rh", "Pd", "Ag", "Cd",
    "Hf", "Ta", "W", "Re", "Os", "Ir", "Pt", "Au", "Hg",
}
FORMAL_CALCULATION_ARTIFACT_SCHEMAS = {
    "gaussian-candidate-target-import/1",
    "gaussian-input-draft-review/1",
    "gaussian-candidate-input-handoff/1",
    "gaussian-energy-review/1",
    "gaussian-reviewed-energy-record/1",
    "gaussian-energy-lineage/1",
    "gaussian-sanitized-job-observation/1",
    "gaussian-calculation-attempt-link/1",
}


def _exact(value: Any, keys: set[str], label: str) -> dict[str, Any]:
    rw.require(isinstance(value, dict), f"{label} must be an object")
    rw._require_exact_keys(value, keys, keys, label)
    return value


def _resolve(path_text: str, owner: Path, label: str) -> Path:
    rw.require(isinstance(path_text, str) and path_text.strip(), f"{label}.path must be a non-empty string")
    rw.require("://" not in path_text, f"{label}.path must be a local file")
    path = Path(path_text)
    if not path.is_absolute():
        path = owner.parent / path
    rw.require(path.is_file() and not path.is_symlink(), f"{label} is missing or a symlink: {path}")
    return path


def _rich_ref(path: Path, data: dict[str, Any], payload_field: str = "payload_sha256") -> dict[str, Any]:
    payload = data.get(payload_field)
    rw.require(isinstance(payload, str) and rw.SHA256_RE.fullmatch(payload) is not None, f"{path}: invalid {payload_field}")
    return {
        "path": str(path),
        "sha256": rw.sha256_file(path),
        "size_bytes": path.stat().st_size,
        "schema": data["schema"],
        "payload_field": payload_field,
        "payload_sha256": payload,
    }


def _verify_ref(reference: Any, owner: Path, expected_schema: str | None = None) -> tuple[Path, dict[str, Any]]:
    rw.require(isinstance(reference, dict), "bound artifact must be an object")
    allowed = {"path", "sha256", "size_bytes", "schema", "payload_field", "payload_sha256"}
    required = {"path", "sha256", "size_bytes", "schema", "payload_sha256"}
    rw._require_exact_keys(reference, allowed, required, "bound artifact")
    ref = reference
    path = _resolve(ref["path"], owner, "bound artifact")
    rw.require(ref["sha256"] == rw.sha256_file(path) and ref["size_bytes"] == path.stat().st_size, "bound artifact file identity mismatch")
    data = rw.load_json(path)
    if expected_schema is not None:
        rw.require(ref["schema"] == expected_schema, "bound artifact reference schema mismatch")
    rw.require(data.get("schema") == ref["schema"], "bound artifact schema mismatch")
    payload_field = ref.get("payload_field", "payload_sha256")
    rw.require(payload_field in {"payload_sha256", "selection_payload_sha256", "evidence_review_payload_sha256"}, "bound artifact payload field is unsupported")
    if payload_field == "payload_sha256":
        rw.validate_payload_hash(data)
    elif payload_field == "selection_payload_sha256":
        expected = protocol.payload_sha256({key: value for key, value in data.items() if key != payload_field})
        rw.require(data.get(payload_field) == expected, "protocol-selection payload hash mismatch")
    else:
        lit.verify_payload_hash(data, payload_field)
    rw.require(data[payload_field] == ref["payload_sha256"], "bound artifact payload identity mismatch")
    return path, data


def _verify_ts_parent_ref(reference: Any, owner: Path, expected_schema: str) -> tuple[Path, dict[str, Any]]:
    ref = _exact(reference, {"path", "sha256", "size_bytes", "payload_sha256"}, "TS-precedent parent reference")
    parent_path = _resolve(ref["path"], owner, "TS-precedent parent reference")
    rw.require(ref["sha256"] == rw.sha256_file(parent_path) and ref["size_bytes"] == parent_path.stat().st_size, "TS-precedent parent file identity mismatch")
    parent = rw.load_json(parent_path)
    rw.require(parent.get("schema") == expected_schema, "TS-precedent parent schema mismatch")
    rw.validate_payload_hash(parent)
    rw.require(parent["payload_sha256"] == ref["payload_sha256"], "TS-precedent parent payload identity mismatch")
    return parent_path, parent


def _file_ref(path: Path, data: dict[str, Any]) -> dict[str, Any]:
    """Bind an immutable JSON file that does not define an internal payload hash.

    Gaussian result parsers predate the reaction-workflow payload convention.  A
    full-file SHA-256 is therefore the normative identity for such evidence; it
    is not silently converted into, or confused with, a payload-bound artifact.
    """

    schema = rw._require_string(data.get("schema"), f"{path}: evidence schema")
    return {
        "path": str(path),
        "sha256": rw.sha256_file(path),
        "size_bytes": path.stat().st_size,
        "schema": schema,
    }


def _verify_evidence_ref(reference: Any, owner: Path) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    """Validate either a payload-bound artifact or a full-file evidence record."""

    rw.require(isinstance(reference, dict), "calculation evidence reference must be an object")
    if "payload_sha256" in reference:
        path, data = _verify_ref(reference, owner)
        normalized = _rich_ref(path, data, reference.get("payload_field", "payload_sha256"))
    else:
        allowed = {"path", "sha256", "size_bytes", "schema"}
        rw._require_exact_keys(reference, allowed, allowed, "calculation evidence reference")
        path = _resolve(reference["path"], owner, "calculation evidence")
        rw.require(
            reference["sha256"] == rw.sha256_file(path)
            and reference["size_bytes"] == path.stat().st_size,
            "calculation evidence file identity mismatch",
        )
        data = rw.load_json(path)
        rw.require(data.get("schema") == reference["schema"], "calculation evidence schema mismatch")
        normalized = _file_ref(path, data)
    rw.require(data.get("calculation_ready") is not True, "calculation evidence cannot grant calculation readiness")
    rw.require(data.get("no_submission_authorization") is not False, "calculation evidence cannot grant submission authority")
    if data.get("schema") in FORMAL_CALCULATION_ARTIFACT_SCHEMAS:
        try:
            import calculation_artifacts as formal_adapter

            formal_adapter.validate_artifact(path)
        except (rw.OfflineError, OSError, ValueError, KeyError, TypeError) as exc:
            raise rw.OfflineError(
                f"formal calculation-artifact evidence failed its owning validator: {exc}"
            ) from exc
    return path, data, normalized


def _resolve_review_source(artifact: dict[str, Any], artifact_path: Path) -> Path:
    ref = _exact(artifact["review_source"], {"path", "sha256", "size_bytes"}, "review source")
    path = _resolve(ref["path"], artifact_path, "review source")
    rw.require(ref["sha256"] == rw.sha256_file(path) and ref["size_bytes"] == path.stat().st_size, "review source identity mismatch")
    return path


def _format_xyz(atoms: list[dict[str, Any]], comment: str) -> bytes:
    rows = [str(len(atoms)), comment]
    for atom in atoms:
        rows.append(f"{atom['element']:<2} {atom['x']: .10f} {atom['y']: .10f} {atom['z']: .10f}")
    return ("\n".join(rows) + "\n").encode("utf-8")


def _parse_xyz(path: Path) -> list[dict[str, Any]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    rw.require(len(lines) >= 2, f"XYZ coordinate source is incomplete: {path}")
    try:
        count = int(lines[0].strip())
    except ValueError as exc:
        raise rw.OfflineError(f"XYZ coordinate source has an invalid atom count: {path}") from exc
    rw.require(count > 0 and len(lines) == count + 2, f"XYZ coordinate source atom count/rows differ: {path}")
    atoms: list[dict[str, Any]] = []
    for position, line in enumerate(lines[2:], start=1):
        fields = line.split()
        rw.require(len(fields) == 4, f"XYZ coordinate row {position} must contain element and x/y/z")
        element = fields[0]
        valid_element = (
            len(element) == 1 and element.isupper()
        ) or (
            len(element) == 2
            and element[0].isupper()
            and element[1].islower()
        )
        rw.require(valid_element, f"XYZ coordinate row {position} has an invalid element")
        try:
            coordinates = [float(value) for value in fields[1:]]
        except ValueError as exc:
            raise rw.OfflineError(f"XYZ coordinate row {position} has a nonnumeric coordinate") from exc
        rw.require(all(math.isfinite(value) for value in coordinates), f"XYZ coordinate row {position} has a non-finite coordinate")
        atoms.append({"element": element, "x": coordinates[0], "y": coordinates[1], "z": coordinates[2]})
    return atoms


def _distance(left: dict[str, Any], right: dict[str, Any]) -> float:
    return math.sqrt(sum((float(left[key]) - float(right[key])) ** 2 for key in ("x", "y", "z")))


def _validate_materialized_atoms(
    raw_atoms: Any,
    expected_order: list[tuple[str, str]],
    source_path: Path,
    geometry_path: Path,
    label: str,
) -> tuple[list[dict[str, Any]], float | None]:
    rw.require(isinstance(raw_atoms, list) and len(raw_atoms) == len(expected_order), f"{label} atom inventory mismatch")
    source_atoms = _parse_xyz(source_path)
    geometry_atoms = _parse_xyz(geometry_path)
    rw.require(len(source_atoms) == len(geometry_atoms) == len(expected_order), f"{label} coordinate atom count mismatch")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for position, (raw, expected, source_atom, geometry_atom) in enumerate(
        zip(raw_atoms, expected_order, source_atoms, geometry_atoms, strict=True), start=1
    ):
        atom = _exact(raw, {"position", "atom_id", "element", "x", "y", "z"}, f"{label} atom[{position}]")
        rw.require(type(atom["position"]) is int and atom["position"] == position, f"{label} atom positions are not contiguous")
        atom_id = rw._require_id(atom["atom_id"], f"{label} atom_id")
        element = rw._require_string(atom["element"], f"{label} element")
        rw.require((atom_id, element) == expected and atom_id not in seen, f"{label} atom identity/order mismatch")
        rw.require(source_atom["element"] == geometry_atom["element"] == element, f"{label} coordinate element mismatch")
        for key in ("x", "y", "z"):
            rw.require(rw._finite_number(atom[key]), f"{label} {key} coordinate must be finite")
            rw.require(abs(float(source_atom[key]) - float(atom[key])) <= 1e-12, f"{label} atom table differs from its bound source coordinates")
            rw.require(abs(float(geometry_atom[key]) - float(atom[key])) <= 1e-9, f"{label} geometry differs from its atom table")
        seen.add(atom_id)
        normalized.append(atom)
    distances = [_distance(left, right) for index, left in enumerate(normalized) for right in normalized[index + 1:]]
    return normalized, min(distances) if distances else None


def build_candidate(ts_map_path: Path, review_path: Path, xyz_output: Path, output: Path) -> dict[str, Any]:
    ts_map_path = ts_map_path.absolute()
    review_path = review_path.absolute()
    xyz_output = xyz_output.absolute()
    output = output.absolute()
    tsp.validate(ts_map_path)
    ts_map = rw.load_json(ts_map_path)
    review = rw.load_json(review_path)
    keys = {
        "schema", "study_id", "ts_precedent_payload_sha256", "precedent_id",
        "candidate_id", "candidate_kind", "review_decision", "review_notes",
    }
    _exact(review, keys, "candidate-construction review")
    rw.require(review["schema"] == CANDIDATE_REVIEW_SCHEMA, "candidate-construction review schema mismatch")
    rw.require(review["study_id"] == ts_map["study_id"], "candidate-construction study_id mismatch")
    rw.require(review["ts_precedent_payload_sha256"] == ts_map["payload_sha256"], "candidate-construction TS-precedent hash mismatch")
    precedent_id = rw._require_id(review["precedent_id"], "candidate-construction precedent_id")
    matches = [item for item in ts_map["records"] if item["precedent_id"] == precedent_id]
    rw.require(len(matches) == 1, "candidate-construction precedent_id is absent or duplicated")
    precedent = matches[0]
    rw.require(ts_map["candidate_construction_promotable"] is True, "TS-precedent map is not promotable to candidate construction")
    support_gate = precedent.get("mechanism_support_gate")
    rw.require(
        precedent["disposition"]["status"] == "accepted_for_candidate_construction"
        and precedent["candidate_construction_gate"] == "candidate_construction_eligible"
        and isinstance(support_gate, dict)
        and support_gate.get("hypothesis_exploration_eligible") is True
        and support_gate.get("mechanism_claim_validated") is False,
        "TS precedent is not accepted for candidate construction",
    )
    rw.require(precedent["seed_strategy"] == "published_coordinates", "this version materializes only audited published-coordinate seeds")
    coordinate_ref = precedent["source_structure"]["coordinate_provenance"]["source_object"]
    rw.require(coordinate_ref is not None, "accepted TS precedent has no coordinate source")
    review_decision = rw._require_string(review["review_decision"], "candidate-construction review_decision")
    rw.require(review_decision == "accepted", "candidate materialization requires an explicit accepted review decision")
    candidate_id = rw._require_id(review["candidate_id"], "candidate_id")
    candidate_kind = rw._require_string(review["candidate_kind"], "candidate_kind")
    rw.require(candidate_kind == "transition_state_seed", "this version supports transition_state_seed materialization only")

    coordinate_path = _resolve(coordinate_ref["path"], ts_map_path, "TS coordinate source")
    rw.require(coordinate_ref["sha256"] == rw.sha256_file(coordinate_path) and coordinate_ref["size_bytes"] == coordinate_path.stat().st_size, "TS coordinate source identity mismatch")
    source_atoms = _parse_xyz(coordinate_path)
    source_order = sorted(precedent["source_structure"]["source_atoms"], key=lambda item: item["order_index"])
    mapping = {item["source_atom_id"]: item["from_atom_id"] for item in precedent["source_to_target_atom_mapping"]}
    rw.require(len(source_atoms) == len(source_order) == len(mapping), "candidate source coordinate and mapping counts differ")

    network_path, network = _verify_ts_parent_ref(ts_map["mechanism_network"], ts_map_path, mn.OUTPUT_SCHEMA)
    mn.validate(network_path)
    edge = next((item for item in network["edges"] if item["edge_id"] == precedent["target"]["edge_id"]), None)
    rw.require(edge is not None, "candidate precedent edge is absent from its mechanism network")
    state = next(item for item in network["states"] if item["state_id"] == edge["from_state_id"])
    state_elements = {item["atom_id"]: item["element"] for item in state["atoms"]}
    atoms: list[dict[str, Any]] = []
    for position, (source_order_atom, xyz_atom) in enumerate(zip(source_order, source_atoms, strict=True), start=1):
        source_id = source_order_atom["source_atom_id"]
        target_id = mapping[source_id]
        rw.require(source_order_atom["element"] == xyz_atom["element"] == state_elements[target_id], "candidate atom order changes an element")
        atoms.append({
            "position": position,
            "atom_id": target_id,
            "element": xyz_atom["element"],
            "x": xyz_atom["x"],
            "y": xyz_atom["y"],
            "z": xyz_atom["z"],
        })
    rw.require(not ({atom["element"] for atom in atoms} & TRANSITION_METALS), "transition-metal candidate materialization remains unsupported")
    rw.require({atom["atom_id"] for atom in atoms} == set(state_elements), "candidate materialization does not cover the complete source-state atom inventory")
    rw.require(len(atoms) >= 2, "transition-state candidate materialization requires at least two atoms")
    minimum_distance = min((_distance(left, right) for index, left in enumerate(atoms) for right in atoms[index + 1:]), default=math.inf)
    rw.require(minimum_distance >= 0.3, "candidate coordinates contain an impossible sub-0.3 angstrom contact")
    rw.require(not xyz_output.exists() and not output.exists(), "refusing to overwrite candidate output")
    xyz_bytes = _format_xyz(atoms, f"{candidate_id}; reviewed offline seed, not a validated TS")
    xyz_output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with xyz_output.open("xb") as handle:
            handle.write(xyz_bytes)
        geometry_ref = {
            "path": str(xyz_output),
            "sha256": rw.sha256_file(xyz_output),
            "size_bytes": xyz_output.stat().st_size,
            "format": "xyz",
        }
        artifact = {
            "schema": CANDIDATE_SCHEMA,
            "study_id": ts_map["study_id"],
            "candidate_id": candidate_id,
            "candidate_kind": candidate_kind,
            "target": {"edge_id": precedent["target"]["edge_id"], "source_state_id": edge["from_state_id"], "stereochemical_channel": precedent["target"]["stereochemical_channel"]},
            "ts_precedent_map": _rich_ref(ts_map_path, ts_map),
            "precedent_id": precedent_id,
            "coordinate_source": {"path": str(coordinate_path), "sha256": rw.sha256_file(coordinate_path), "size_bytes": coordinate_path.stat().st_size, "format": "xyz"},
            "review_source": rw._artifact_ref(review_path),
            "charge": state["formal_charge"],
            "multiplicity": state["multiplicity"],
            "atoms": atoms,
            "geometry": geometry_ref,
            "minimum_interatomic_distance_angstrom": minimum_distance,
            "geometry_provenance": "audited_published_coordinate_seed",
            "candidate_status": "materialized_for_offline_review",
            "requires_visible_review": True,
            "review": {"decision": review_decision, "notes": rw._string_list(review["review_notes"], "candidate review_notes")},
            "calculation_ready": False,
            "no_input_render_authorization": True,
            "no_submission_authorization": True,
        }
        rw.finalize_artifact(artifact)
        rw.write_json(output, artifact)
    except Exception:
        if xyz_output.exists() and not output.exists():
            xyz_output.unlink()
        raise
    return artifact


def validate_candidate(path: Path) -> dict[str, Any]:
    artifact = rw.load_json(path)
    keys = {
        "schema", "study_id", "candidate_id", "candidate_kind", "target", "ts_precedent_map",
        "precedent_id", "coordinate_source", "review_source", "charge", "multiplicity", "atoms",
        "geometry", "minimum_interatomic_distance_angstrom", "geometry_provenance", "candidate_status",
        "requires_visible_review", "review", "calculation_ready", "no_input_render_authorization",
        "no_submission_authorization", "payload_sha256",
    }
    _exact(artifact, keys, "candidate materialization")
    rw.require(artifact["schema"] == CANDIDATE_SCHEMA, "candidate schema mismatch")
    rw.validate_payload_hash(artifact)
    candidate_id = rw._require_id(artifact["candidate_id"], "candidate_id")
    rw.require(artifact["candidate_kind"] == "transition_state_seed" and artifact["candidate_status"] == "materialized_for_offline_review", "candidate status or kind is unsupported")
    rw.require(artifact["requires_visible_review"] is True, "candidate must retain visible-review requirement")
    rw.require(artifact["calculation_ready"] is False and artifact["no_input_render_authorization"] is True and artifact["no_submission_authorization"] is True, "candidate authority boundary changed")
    ts_path, ts_map = _verify_ref(artifact["ts_precedent_map"], path, tsp.OUTPUT_SCHEMA)
    tsp.validate(ts_path)
    rw.require(artifact["study_id"] == ts_map["study_id"], "candidate study_id differs from its TS-precedent map")
    precedent = next((item for item in ts_map["records"] if item["precedent_id"] == artifact["precedent_id"]), None)
    rw.require(
        ts_map["candidate_construction_promotable"] is True
        and precedent is not None
        and precedent["disposition"]["status"] == "accepted_for_candidate_construction"
        and precedent["candidate_construction_gate"] == "candidate_construction_eligible"
        and precedent["mechanism_support_gate"]["hypothesis_exploration_eligible"] is True
        and precedent["mechanism_support_gate"]["mechanism_claim_validated"] is False,
        "candidate precedent binding mismatch",
    )
    target = _exact(artifact["target"], {"edge_id", "source_state_id", "stereochemical_channel"}, "candidate target")
    network_path, network = _verify_ts_parent_ref(ts_map["mechanism_network"], ts_path, mn.OUTPUT_SCHEMA)
    mn.validate(network_path)
    edge = next((item for item in network["edges"] if item["edge_id"] == precedent["target"]["edge_id"]), None)
    rw.require(edge is not None, "candidate precedent edge is absent from its mechanism network")
    state = next((item for item in network["states"] if item["state_id"] == edge["from_state_id"]), None)
    rw.require(state is not None, "candidate source state is absent from its mechanism network")
    expected_target = {
        "edge_id": precedent["target"]["edge_id"],
        "source_state_id": edge["from_state_id"],
        "stereochemical_channel": precedent["target"]["stereochemical_channel"],
    }
    rw.require(target == expected_target, "candidate target differs from its accepted precedent")
    rw.require(artifact["charge"] == state["formal_charge"] and artifact["multiplicity"] == state["multiplicity"], "candidate charge or multiplicity differs from its source state")
    rw.require(artifact["geometry_provenance"] == "audited_published_coordinate_seed", "candidate geometry provenance changed")

    source_ref = _exact(artifact["coordinate_source"], {"path", "sha256", "size_bytes", "format"}, "candidate coordinate source")
    source_path = _resolve(source_ref["path"], path, "candidate coordinate source")
    rw.require(source_ref["format"] == "xyz" and source_ref["sha256"] == rw.sha256_file(source_path) and source_ref["size_bytes"] == source_path.stat().st_size, "candidate coordinate source mismatch")
    rw.require(precedent["seed_strategy"] == "published_coordinates", "candidate precedent seed strategy changed")
    precedent_source = _exact(precedent["source_structure"]["coordinate_provenance"]["source_object"], {"path", "sha256", "size_bytes"}, "precedent coordinate source")
    precedent_source_path = _resolve(precedent_source["path"], ts_path, "precedent coordinate source")
    rw.require(
        source_path.resolve() == precedent_source_path.resolve()
        and source_ref == {"path": str(source_path), "sha256": precedent_source["sha256"], "size_bytes": precedent_source["size_bytes"], "format": "xyz"},
        "candidate coordinate source differs from its accepted precedent",
    )
    geometry_ref = _exact(artifact["geometry"], {"path", "sha256", "size_bytes", "format"}, "candidate geometry")
    geometry_path = _resolve(geometry_ref["path"], path, "candidate geometry")
    rw.require(geometry_ref["format"] == "xyz" and geometry_ref["sha256"] == rw.sha256_file(geometry_path) and geometry_ref["size_bytes"] == geometry_path.stat().st_size, "candidate geometry identity mismatch")

    mapping = {item["source_atom_id"]: item["from_atom_id"] for item in precedent["source_to_target_atom_mapping"]}
    source_order = sorted(precedent["source_structure"]["source_atoms"], key=lambda item: item["order_index"])
    expected_order = [(mapping[item["source_atom_id"]], item["element"]) for item in source_order]
    state_elements = {item["atom_id"]: item["element"] for item in state["atoms"]}
    rw.require(len(expected_order) >= 2 and {atom_id for atom_id, _ in expected_order} == set(state_elements), "candidate precedent does not cover its complete source state")
    rw.require(all(state_elements[atom_id] == element for atom_id, element in expected_order), "candidate precedent changes source-state elements")
    atoms, computed_minimum = _validate_materialized_atoms(artifact["atoms"], expected_order, source_path, geometry_path, "candidate")
    rw.require(not ({atom["element"] for atom in atoms} & TRANSITION_METALS), "transition-metal candidate materialization remains unsupported")
    rw.require(computed_minimum is not None and computed_minimum >= 0.3, "candidate coordinates contain an impossible contact")
    rw.require(rw._finite_number(artifact["minimum_interatomic_distance_angstrom"]), "candidate minimum-distance diagnostic must be finite")
    rw.require(abs(computed_minimum - float(artifact["minimum_interatomic_distance_angstrom"])) <= 1e-12, "candidate minimum-distance diagnostic mismatch")

    review_path = _resolve_review_source(artifact, path)
    review = rw.load_json(review_path)
    review_keys = {
        "schema", "study_id", "ts_precedent_payload_sha256", "precedent_id",
        "candidate_id", "candidate_kind", "review_decision", "review_notes",
    }
    _exact(review, review_keys, "candidate review source")
    review_notes = rw._string_list(review["review_notes"], "candidate review_notes")
    rw.require(
        review["schema"] == CANDIDATE_REVIEW_SCHEMA
        and review["study_id"] == artifact["study_id"]
        and review["ts_precedent_payload_sha256"] == ts_map["payload_sha256"]
        and review["precedent_id"] == artifact["precedent_id"]
        and review["candidate_id"] == candidate_id
        and review["candidate_kind"] == artifact["candidate_kind"]
        and review["review_decision"] == "accepted",
        "candidate review source binding mismatch",
    )
    artifact_review = _exact(artifact["review"], {"decision", "notes"}, "candidate review")
    rw.require(artifact_review == {"decision": "accepted", "notes": review_notes}, "candidate embedded review differs from its source")
    return {
        "schema": "gaussian-reaction-candidate-materialization-validation/1",
        "study_id": artifact["study_id"],
        "candidate_id": candidate_id,
        "payload_sha256": artifact["payload_sha256"],
        "live_actions": False,
    }


def build_state_candidate(network_path: Path, review_path: Path, xyz_output: Path, output: Path) -> dict[str, Any]:
    network_path = network_path.absolute()
    review_path = review_path.absolute()
    xyz_output = xyz_output.absolute()
    output = output.absolute()
    mn.validate(network_path)
    network = rw.load_json(network_path)
    review = rw.load_json(review_path)
    keys = {
        "schema", "study_id", "mechanism_network_payload_sha256", "state_id",
        "candidate_id", "candidate_kind", "coordinate_source", "atom_order",
        "geometry_provenance", "review_decision", "review_notes",
    }
    _exact(review, keys, "state-candidate review")
    rw.require(review["schema"] == STATE_CANDIDATE_REVIEW_SCHEMA, "state-candidate review schema mismatch")
    rw.require(review["study_id"] == network["study_id"], "state-candidate review study_id mismatch")
    rw.require(review["mechanism_network_payload_sha256"] == network["payload_sha256"], "state-candidate mechanism-network hash mismatch")
    state_id = rw._require_id(review["state_id"], "state-candidate state_id")
    matches = [item for item in network["states"] if item["state_id"] == state_id]
    rw.require(len(matches) == 1, "state-candidate target state is absent or duplicated")
    state = matches[0]
    candidate_id = rw._require_id(review["candidate_id"], "state-candidate candidate_id")
    candidate_kind = rw._require_string(review["candidate_kind"], "state-candidate candidate_kind")
    rw.require(candidate_kind in {"minimum_seed", "complex_seed"}, "state-candidate kind is invalid")
    if candidate_kind == "minimum_seed":
        rw.require(len(state["components"]) == 1, "minimum_seed requires a reviewed single-component mechanism state")
    if candidate_kind == "complex_seed":
        rw.require(len(state["components"]) > 1, "complex_seed requires a reviewed multi-component mechanism state")
    decision = rw._require_string(review["review_decision"], "state-candidate review_decision")
    rw.require(decision == "accepted", "state-candidate materialization requires an accepted review decision")
    provenance = rw._require_string(review["geometry_provenance"], "state-candidate geometry_provenance")
    rw.require(provenance in {"reviewed_structure_coordinates", "explicit_reviewed_complex_coordinates"}, "state-candidate geometry provenance is invalid")
    if candidate_kind == "minimum_seed":
        rw.require(provenance == "reviewed_structure_coordinates", "minimum_seed requires reviewed single-structure coordinate provenance")
    if candidate_kind == "complex_seed":
        rw.require(provenance == "explicit_reviewed_complex_coordinates", "complex_seed requires explicit reviewed complex-coordinate provenance")
    coordinate = _exact(review["coordinate_source"], {"path", "sha256", "size_bytes"}, "state-candidate coordinate_source")
    coordinate_path = _resolve(coordinate["path"], review_path, "state-candidate coordinate_source")
    rw.require(coordinate["sha256"] == rw.sha256_file(coordinate_path) and coordinate["size_bytes"] == coordinate_path.stat().st_size, "state-candidate coordinate source identity mismatch")
    xyz_atoms = _parse_xyz(coordinate_path)
    state_elements = {item["atom_id"]: item["element"] for item in state["atoms"]}
    order_raw = review["atom_order"]
    rw.require(isinstance(order_raw, list) and len(order_raw) == len(xyz_atoms), "state-candidate atom order and coordinate counts differ")
    atoms: list[dict[str, Any]] = []
    seen_atoms: set[str] = set()
    for position, (raw_atom, xyz_atom) in enumerate(zip(order_raw, xyz_atoms, strict=True), start=1):
        atom = _exact(raw_atom, {"atom_id", "element"}, f"state-candidate atom_order[{position}]")
        atom_id = rw._require_id(atom["atom_id"], f"state-candidate atom_order[{position}].atom_id")
        element = rw._require_string(atom["element"], f"state-candidate atom_order[{position}].element")
        rw.require(atom_id in state_elements and atom_id not in seen_atoms, "state-candidate atom order is unknown or duplicated")
        rw.require(element == xyz_atom["element"] == state_elements[atom_id], "state-candidate atom order changes an element")
        seen_atoms.add(atom_id)
        atoms.append({"position": position, "atom_id": atom_id, "element": element, "x": xyz_atom["x"], "y": xyz_atom["y"], "z": xyz_atom["z"]})
    rw.require(seen_atoms == set(state_elements), "state-candidate atom order does not cover the complete state inventory")
    rw.require(not ({atom["element"] for atom in atoms} & TRANSITION_METALS), "transition-metal state/complex materialization remains unsupported")
    distances = [_distance(left, right) for index, left in enumerate(atoms) for right in atoms[index + 1:]]
    minimum_distance = min(distances) if distances else None
    rw.require(minimum_distance is None or minimum_distance >= 0.3, "state-candidate coordinates contain an impossible sub-0.3 angstrom contact")
    rw.require(not xyz_output.exists() and not output.exists(), "refusing to overwrite state-candidate output")
    xyz_bytes = _format_xyz(atoms, f"{candidate_id}; reviewed offline state seed, not an optimized minimum")
    xyz_output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with xyz_output.open("xb") as handle:
            handle.write(xyz_bytes)
        artifact = {
            "schema": STATE_CANDIDATE_SCHEMA,
            "study_id": network["study_id"],
            "candidate_id": candidate_id,
            "candidate_kind": candidate_kind,
            "target": {"state_id": state_id, "component_count": len(state["components"])},
            "mechanism_network": _rich_ref(network_path, network),
            "coordinate_source": {"path": str(coordinate_path), "sha256": rw.sha256_file(coordinate_path), "size_bytes": coordinate_path.stat().st_size, "format": "xyz"},
            "review_source": rw._artifact_ref(review_path),
            "charge": state["formal_charge"],
            "multiplicity": state["multiplicity"],
            "atoms": atoms,
            "geometry": {"path": str(xyz_output), "sha256": rw.sha256_file(xyz_output), "size_bytes": xyz_output.stat().st_size, "format": "xyz"},
            "minimum_interatomic_distance_angstrom": minimum_distance,
            "geometry_provenance": provenance,
            "candidate_status": "materialized_for_offline_review",
            "requires_visible_review": True,
            "review": {"decision": decision, "notes": rw._string_list(review["review_notes"], "state-candidate review_notes")},
            "calculation_ready": False,
            "no_input_render_authorization": True,
            "no_submission_authorization": True,
        }
        rw.finalize_artifact(artifact)
        rw.write_json(output, artifact)
    except Exception:
        if xyz_output.exists() and not output.exists():
            xyz_output.unlink()
        raise
    return artifact


def validate_state_candidate(path: Path) -> dict[str, Any]:
    artifact = rw.load_json(path)
    keys = {
        "schema", "study_id", "candidate_id", "candidate_kind", "target", "mechanism_network",
        "coordinate_source", "review_source", "charge", "multiplicity", "atoms", "geometry",
        "minimum_interatomic_distance_angstrom", "geometry_provenance", "candidate_status",
        "requires_visible_review", "review", "calculation_ready", "no_input_render_authorization",
        "no_submission_authorization", "payload_sha256",
    }
    _exact(artifact, keys, "state-candidate materialization")
    rw.require(artifact["schema"] == STATE_CANDIDATE_SCHEMA, "state-candidate schema mismatch")
    rw.validate_payload_hash(artifact)
    candidate_id = rw._require_id(artifact["candidate_id"], "state-candidate candidate_id")
    candidate_kind = rw._require_string(artifact["candidate_kind"], "state-candidate candidate_kind")
    rw.require(candidate_kind in {"minimum_seed", "complex_seed"} and artifact["candidate_status"] == "materialized_for_offline_review", "state-candidate status or kind is unsupported")
    rw.require(artifact["requires_visible_review"] is True and artifact["calculation_ready"] is False and artifact["no_input_render_authorization"] is True and artifact["no_submission_authorization"] is True, "state-candidate authority boundary changed")
    network_path, network = _verify_ref(artifact["mechanism_network"], path, mn.OUTPUT_SCHEMA)
    mn.validate(network_path)
    rw.require(artifact["study_id"] == network["study_id"], "state-candidate study_id differs from its mechanism network")
    target = _exact(artifact["target"], {"state_id", "component_count"}, "state-candidate target")
    state_id = rw._require_id(target["state_id"], "state-candidate state_id")
    state = next((item for item in network["states"] if item["state_id"] == state_id), None)
    rw.require(state is not None and type(target["component_count"]) is int and len(state["components"]) == target["component_count"], "state-candidate target binding mismatch")
    if candidate_kind == "minimum_seed":
        rw.require(len(state["components"]) == 1 and artifact["geometry_provenance"] == "reviewed_structure_coordinates", "minimum_seed requires a reviewed single-component structure")
    else:
        rw.require(len(state["components"]) > 1 and artifact["geometry_provenance"] == "explicit_reviewed_complex_coordinates", "complex_seed requires explicit reviewed multi-component coordinates")
    rw.require(artifact["charge"] == state["formal_charge"] and artifact["multiplicity"] == state["multiplicity"], "state-candidate charge or multiplicity differs from its target state")

    source_ref = _exact(artifact["coordinate_source"], {"path", "sha256", "size_bytes", "format"}, "state-candidate coordinate source")
    source_path = _resolve(source_ref["path"], path, "state-candidate coordinate source")
    rw.require(source_ref["format"] == "xyz" and source_ref["sha256"] == rw.sha256_file(source_path) and source_ref["size_bytes"] == source_path.stat().st_size, "state-candidate coordinate source mismatch")
    geometry_ref = _exact(artifact["geometry"], {"path", "sha256", "size_bytes", "format"}, "state-candidate geometry")
    geometry_path = _resolve(geometry_ref["path"], path, "state-candidate geometry")
    rw.require(geometry_ref["format"] == "xyz" and geometry_ref["sha256"] == rw.sha256_file(geometry_path) and geometry_ref["size_bytes"] == geometry_path.stat().st_size, "state-candidate geometry mismatch")

    review_path = _resolve_review_source(artifact, path)
    review = rw.load_json(review_path)
    review_keys = {
        "schema", "study_id", "mechanism_network_payload_sha256", "state_id", "candidate_id",
        "candidate_kind", "coordinate_source", "atom_order", "geometry_provenance",
        "review_decision", "review_notes",
    }
    _exact(review, review_keys, "state-candidate review source")
    review_coordinate = _exact(review["coordinate_source"], {"path", "sha256", "size_bytes"}, "state-candidate review coordinate source")
    review_coordinate_path = _resolve(review_coordinate["path"], review_path, "state-candidate review coordinate source")
    rw.require(
        review_coordinate_path.resolve() == source_path.resolve()
        and review_coordinate["sha256"] == source_ref["sha256"]
        and review_coordinate["size_bytes"] == source_ref["size_bytes"],
        "state-candidate coordinate source differs from its accepted review",
    )
    review_notes = rw._string_list(review["review_notes"], "state-candidate review_notes")
    rw.require(
        review["schema"] == STATE_CANDIDATE_REVIEW_SCHEMA
        and review["study_id"] == artifact["study_id"]
        and review["mechanism_network_payload_sha256"] == network["payload_sha256"]
        and review["state_id"] == state_id
        and review["candidate_id"] == candidate_id
        and review["candidate_kind"] == candidate_kind
        and review["geometry_provenance"] == artifact["geometry_provenance"]
        and review["review_decision"] == "accepted",
        "state-candidate review source binding mismatch",
    )
    rw.require(isinstance(review["atom_order"], list), "state-candidate review atom order must be an array")
    expected_order: list[tuple[str, str]] = []
    for position, raw_atom in enumerate(review["atom_order"], start=1):
        atom = _exact(raw_atom, {"atom_id", "element"}, f"state-candidate review atom_order[{position}]")
        expected_order.append((rw._require_id(atom["atom_id"], "state-candidate atom_id"), rw._require_string(atom["element"], "state-candidate element")))
    state_elements = {item["atom_id"]: item["element"] for item in state["atoms"]}
    rw.require(len(expected_order) == len(state_elements) and {atom_id for atom_id, _ in expected_order} == set(state_elements), "state-candidate review atom order does not cover the complete target state")
    rw.require(all(state_elements[atom_id] == element for atom_id, element in expected_order), "state-candidate review atom order changes an element")
    atoms, computed_minimum = _validate_materialized_atoms(artifact["atoms"], expected_order, source_path, geometry_path, "state-candidate")
    rw.require(not ({atom["element"] for atom in atoms} & TRANSITION_METALS), "transition-metal state/complex materialization remains unsupported")
    if computed_minimum is None:
        rw.require(artifact["minimum_interatomic_distance_angstrom"] is None, "single-atom state-candidate minimum-distance diagnostic must be null")
    else:
        rw.require(computed_minimum >= 0.3, "state-candidate coordinates contain an impossible contact")
        rw.require(rw._finite_number(artifact["minimum_interatomic_distance_angstrom"]), "state-candidate minimum-distance diagnostic must be finite")
        rw.require(abs(computed_minimum - float(artifact["minimum_interatomic_distance_angstrom"])) <= 1e-12, "state-candidate minimum-distance diagnostic mismatch")
    artifact_review = _exact(artifact["review"], {"decision", "notes"}, "state-candidate review")
    rw.require(artifact_review == {"decision": "accepted", "notes": review_notes}, "state-candidate embedded review differs from its source")
    return {"schema": "gaussian-reaction-state-candidate-materialization-validation/1", "study_id": artifact["study_id"], "candidate_id": candidate_id, "payload_sha256": artifact["payload_sha256"], "live_actions": False}


def validate_any_candidate(path: Path) -> dict[str, Any]:
    schema = rw.load_json(path).get("schema")
    if schema == CANDIDATE_SCHEMA:
        return validate_candidate(path)
    if schema == STATE_CANDIDATE_SCHEMA:
        return validate_state_candidate(path)
    raise rw.OfflineError(f"unsupported candidate schema: {schema!r}")


def _topological_order(nodes: dict[str, dict[str, Any]]) -> list[str]:
    pending = {node_id: set(node["dependencies"]) for node_id, node in nodes.items()}
    order: list[str] = []
    while pending:
        ready = sorted(node_id for node_id, dependencies in pending.items() if not dependencies)
        rw.require(ready, "calculation DAG contains a dependency cycle")
        for node_id in ready:
            order.append(node_id)
            pending.pop(node_id)
        for dependencies in pending.values():
            dependencies.difference_update(ready)
    return order


def _validate_protocol_reference(reference: dict[str, Any], owner: Path) -> tuple[Path, dict[str, Any]]:
    selection_path, selection = _verify_ref(reference, owner, "gaussian-protocol-selection/1")
    protocol.load_validated_selection(selection_path)
    rw.require(selection["authorizations"]["submit"] is False and selection["authorizations"]["render_input_draft"] is True, "protocol-selection authority boundary changed")
    return selection_path, selection


def build_dag(network_path: Path, ts_map_path: Path, review_path: Path, output: Path) -> dict[str, Any]:
    network_path = network_path.absolute()
    ts_map_path = ts_map_path.absolute()
    review_path = review_path.absolute()
    output = output.absolute()
    mn.validate(network_path)
    tsp.validate(ts_map_path)
    network = rw.load_json(network_path)
    ts_map = rw.load_json(ts_map_path)
    rw.require(ts_map["mechanism_network"]["payload_sha256"] == network["payload_sha256"], "calculation DAG inputs refer to different mechanism networks")
    review = rw.load_json(review_path)
    keys = {"schema", "study_id", "mechanism_network_payload_sha256", "ts_precedent_payload_sha256", "nodes", "review_decision", "review_notes"}
    _exact(review, keys, "calculation-DAG review")
    rw.require(review["schema"] == DAG_REVIEW_SCHEMA, "calculation-DAG review schema mismatch")
    rw.require(review["study_id"] == network["study_id"], "calculation-DAG review study_id mismatch")
    rw.require(review["mechanism_network_payload_sha256"] == network["payload_sha256"] and review["ts_precedent_payload_sha256"] == ts_map["payload_sha256"], "calculation-DAG review parent hash mismatch")
    states = {item["state_id"]: item for item in network["states"]}
    edges = {item["edge_id"]: item for item in network["edges"]}
    nodes_raw = review["nodes"]
    rw.require(isinstance(nodes_raw, list) and nodes_raw, "calculation-DAG review requires nodes")
    nodes: dict[str, dict[str, Any]] = {}
    blockers: list[dict[str, Any]] = []
    node_keys = {
        "node_id", "node_type", "target_kind", "target_id", "candidate",
        "protocol_selection", "dependencies", "required", "completion",
        "evidence", "review_status", "blockers", "notes",
    }
    for index, raw in enumerate(nodes_raw):
        item = _exact(raw, node_keys, f"calculation-DAG node {index}")
        node_id = rw._require_id(item["node_id"], f"calculation-DAG node {index}.node_id")
        rw.require(node_id not in nodes, f"duplicate calculation-DAG node_id: {node_id}")
        node_type = rw._require_string(item["node_type"], f"node {node_id}.node_type")
        rw.require(node_type in NODE_TYPES, f"node {node_id}.node_type is invalid")
        target_kind = rw._require_string(item["target_kind"], f"node {node_id}.target_kind")
        target_id = rw._require_id(item["target_id"], f"node {node_id}.target_id")
        if node_type in STATE_NODE_TYPES:
            rw.require(target_kind == "state" and target_id in states, f"node {node_id} must reference a mechanism state")
        elif node_type in EDGE_NODE_TYPES:
            rw.require(target_kind == "edge" and target_id in edges, f"node {node_id} must reference a mechanism edge")
        elif node_type in FLEXIBLE_NODE_TYPES:
            rw.require((target_kind == "state" and target_id in states) or (target_kind == "edge" and target_id in edges), f"node {node_id} single-point target is invalid")
        else:
            rw.require(target_kind == "study" and target_id == network["study_id"], f"analysis node {node_id} must target the study")
        dependencies = rw._string_list(item["dependencies"], f"node {node_id}.dependencies")
        rw.require(len(dependencies) == len(set(dependencies)) and node_id not in dependencies, f"node {node_id} dependencies are invalid")
        rw.require(type(item["required"]) is bool, f"node {node_id}.required must be boolean")
        review_status = rw._require_string(item["review_status"], f"node {node_id}.review_status")
        rw.require(review_status in {"reviewed_plan", "blocked"}, f"node {node_id}.review_status is invalid")
        explicit_blockers = sorted(rw._string_list(item["blockers"], f"node {node_id}.blockers"))
        candidate_ref = None
        if item["candidate"] is not None:
            candidate_path, candidate = _verify_ref(item["candidate"], review_path)
            validate_any_candidate(candidate_path)
            if candidate["schema"] == CANDIDATE_SCHEMA:
                rw.require(target_kind == "edge" and candidate["target"]["edge_id"] == target_id, f"node {node_id} TS candidate target mismatch")
            else:
                rw.require(target_kind == "state" and candidate["target"]["state_id"] == target_id, f"node {node_id} state candidate target mismatch")
            candidate_ref = _rich_ref(candidate_path, candidate)
        protocol_ref = None
        if item["protocol_selection"] is not None:
            selection_path, selection = _validate_protocol_reference(item["protocol_selection"], review_path)
            protocol_ref = _rich_ref(selection_path, selection, "selection_payload_sha256")
        evidence_refs: list[dict[str, Any]] = []
        formal_evidence_schemas: set[str] = set()
        rw.require(isinstance(item["evidence"], list), f"node {node_id}.evidence must be an array")
        for evidence_position, raw_reference in enumerate(item["evidence"]):
            _evidence_path, evidence, evidence_ref = _verify_evidence_ref(raw_reference, review_path)
            evidence_refs.append(evidence_ref)
            if evidence.get("schema") in FORMAL_CALCULATION_ARTIFACT_SCHEMAS:
                formal_evidence_schemas.add(evidence["schema"])
        completion = _exact(item["completion"], {"status", "rationale"}, f"node {node_id}.completion")
        completion_status = rw._require_string(completion["status"], f"node {node_id}.completion.status")
        rw.require(completion_status in {"not_started", "terminal_evidence_reviewed", "failed_retained", "superseded"}, f"node {node_id}.completion.status is invalid")
        if completion_status in {"terminal_evidence_reviewed", "failed_retained", "superseded"}:
            rw.require(evidence_refs, f"node {node_id} terminal completion requires evidence")
        if formal_evidence_schemas:
            rw.require(
                completion_status == "not_started",
                f"node {node_id} cannot use formal calculation-artifact evidence as completion before a reviewed external-target-to-DAG mapping exists",
            )
            explicit_blockers.append(
                "Validated formal calculation-artifact evidence is retained, but its external target has no reviewed mapping to this DAG node."
            )
            explicit_blockers = sorted(set(explicit_blockers))
        if completion_status == "not_started":
            if node_type in COMPUTE_NODE_TYPES and candidate_ref is None:
                blockers.append(rw._blocker(f"{node_id}_candidate_missing", node_id, "The calculation target has no reviewed candidate materialization.", ("input_draft", "execution")))
            if node_type in COMPUTE_NODE_TYPES and protocol_ref is None:
                blockers.append(rw._blocker(f"{node_id}_protocol_missing", node_id, "The calculation target has no reviewed protocol selection.", ("input_draft", "execution")))
        for position, message in enumerate(explicit_blockers, start=1):
            blockers.append(rw._blocker(f"{node_id}_review_blocker_{position}", node_id, message, ("input_draft", "execution", "downstream_analysis")))
        nodes[node_id] = {
            "node_id": node_id,
            "node_type": node_type,
            "target_kind": target_kind,
            "target_id": target_id,
            "candidate": candidate_ref,
            "protocol_selection": protocol_ref,
            "dependencies": sorted(dependencies),
            "required": item["required"],
            "completion": {"status": completion_status, "rationale": rw._require_string(completion["rationale"], f"node {node_id}.completion.rationale")},
            "evidence": sorted(evidence_refs, key=lambda value: (value["schema"], value["sha256"])),
            "review_status": review_status,
            "blockers": explicit_blockers,
            "notes": rw._string_list(item["notes"], f"node {node_id}.notes"),
            "readiness": "pending_derivation",
        }
    for node_id, node in nodes.items():
        rw.require(set(node["dependencies"]) <= set(nodes), f"node {node_id} references an unknown dependency")
    order = _topological_order(nodes)
    for node_id in order:
        node = nodes[node_id]
        if node["completion"]["status"] == "terminal_evidence_reviewed":
            readiness = "completed_with_reviewed_evidence"
        elif node["completion"]["status"] in {"failed_retained", "superseded"}:
            readiness = node["completion"]["status"]
        elif node["review_status"] == "blocked" or node["blockers"]:
            readiness = "blocked_by_review"
        elif any(nodes[dependency]["completion"]["status"] != "terminal_evidence_reviewed" for dependency in node["dependencies"]):
            readiness = "waiting_for_dependencies"
        elif node["node_type"] in COMPUTE_NODE_TYPES and node["candidate"] is None:
            readiness = "blocked_missing_candidate"
        elif node["node_type"] in COMPUTE_NODE_TYPES and node["protocol_selection"] is None:
            readiness = "blocked_missing_protocol"
        elif node["node_type"] in COMPUTE_NODE_TYPES:
            readiness = "ready_for_exact_input_review"
        else:
            readiness = "ready_for_offline_analysis"
        node["readiness"] = readiness
    ts_nodes = {node["target_id"] for node in nodes.values() if node["node_type"] == "transition_state_opt_freq"}
    for node in nodes.values():
        if node["node_type"] in {"irc_forward", "irc_reverse", "endpoint_opt_freq"}:
            rw.require(node["target_id"] in ts_nodes, f"{node['node_type']} node for {node['target_id']} lacks a TS/Freq node")
    thermochemistry_nodes = {node_id for node_id, node in nodes.items() if node["node_type"] == "thermochemistry"}
    for node in nodes.values():
        if node["node_type"] == "kinetics":
            rw.require(set(node["dependencies"]) & thermochemistry_nodes, "kinetics node must depend on thermochemistry")
    decision = rw._require_string(review["review_decision"], "calculation-DAG review_decision")
    rw.require(decision in rw.REVIEW_DECISIONS, "calculation-DAG review decision is invalid")
    blockers = rw._sort_blockers(blockers)
    artifact = {
        "schema": DAG_SCHEMA,
        "study_id": network["study_id"],
        "mechanism_network": _rich_ref(network_path, network),
        "ts_precedent_map": _rich_ref(ts_map_path, ts_map),
        "review_source": rw._artifact_ref(review_path),
        "nodes": [nodes[node_id] for node_id in sorted(nodes)],
        "topological_order": order,
        "blockers": blockers,
        "review": {"decision": decision, "notes": rw._string_list(review["review_notes"], "calculation-DAG review_notes")},
        "gate_status": rw._gate_status(decision, blockers),
        "ready_for_exact_input_review_node_ids": sorted(node_id for node_id, node in nodes.items() if node["readiness"] == "ready_for_exact_input_review"),
        "execution_authorized": False,
        "calculation_ready": False,
        "no_submission_authorization": True,
    }
    rw.finalize_artifact(artifact)
    rw.write_json(output, artifact)
    return artifact


def validate_dag(path: Path) -> dict[str, Any]:
    artifact = rw.load_json(path)
    rw.require(artifact.get("schema") == DAG_SCHEMA, "calculation-DAG schema mismatch")
    rw.validate_payload_hash(artifact)
    rw.require(artifact.get("execution_authorized") is False and artifact.get("calculation_ready") is False and artifact.get("no_submission_authorization") is True, "calculation-DAG authority boundary changed")
    network_path, _ = _verify_ref(artifact["mechanism_network"], path, mn.OUTPUT_SCHEMA)
    ts_path, _ = _verify_ref(artifact["ts_precedent_map"], path, tsp.OUTPUT_SCHEMA)
    review_path = _resolve_review_source(artifact, path)
    recomputed = path.parent / f".{path.name}.recomputed"
    rw.require(not recomputed.exists(), "temporary DAG recomputation path already exists")
    try:
        rebuilt = build_dag(network_path, ts_path, review_path, recomputed)
        rw.require(rebuilt == artifact, "calculation-DAG artifact differs from independent recomputation")
    finally:
        if recomputed.exists():
            recomputed.unlink()
    return {
        "schema": "gaussian-reaction-calculation-dag-validation/1",
        "study_id": artifact["study_id"],
        "gate_status": artifact["gate_status"],
        "node_count": len(artifact["nodes"]),
        "payload_sha256": artifact["payload_sha256"],
        "live_actions": False,
    }


def build_index(
    network_path: Path,
    support_path: Path,
    ts_map_path: Path,
    dag_path: Path,
    candidate_paths: list[Path],
    output: Path,
) -> dict[str, Any]:
    network_path = network_path.absolute()
    support_path = support_path.absolute()
    ts_map_path = ts_map_path.absolute()
    dag_path = dag_path.absolute()
    candidate_paths = [path.absolute() for path in candidate_paths]
    output = output.absolute()
    mn.validate(network_path)
    ms.validate(support_path)
    tsp.validate(ts_map_path)
    validate_dag(dag_path)
    network = rw.load_json(network_path)
    support = rw.load_json(support_path)
    ts_map = rw.load_json(ts_map_path)
    dag = rw.load_json(dag_path)
    study_ids = {item["study_id"] for item in (network, support, ts_map, dag)}
    rw.require(len(study_ids) == 1, "study-index inputs have different study IDs")
    rw.require(support["mechanism_network"]["payload_sha256"] == network["payload_sha256"], "study-index mechanism/support binding mismatch")
    rw.require(ts_map["mechanism_support"].get("payload_sha256") == support["payload_sha256"], "study-index TS/support binding mismatch")
    rw.require(ts_map["mechanism_network"]["payload_sha256"] == network["payload_sha256"], "study-index TS/network binding mismatch")
    rw.require(dag["ts_precedent_map"]["payload_sha256"] == ts_map["payload_sha256"], "study-index DAG/TS binding mismatch")
    candidates: list[dict[str, Any]] = []
    seen_candidate_ids: set[str] = set()
    for path in candidate_paths:
        validate_any_candidate(path)
        candidate = rw.load_json(path)
        rw.require(candidate["study_id"] in study_ids and candidate["candidate_id"] not in seen_candidate_ids, "study-index candidate study or ID mismatch")
        seen_candidate_ids.add(candidate["candidate_id"])
        candidates.append(candidate)
    artifacts = [
        {"role": "mechanism_support", "artifact": _rich_ref(support_path, support), "gate_status": support["gate_status"], "blocker_count": len(support["blockers"])},
        {"role": "mechanism_network", "artifact": _rich_ref(network_path, network), "gate_status": network["gate_status"], "blocker_count": len(network["blockers"])},
        {"role": "ts_precedent_map", "artifact": _rich_ref(ts_map_path, ts_map), "gate_status": ts_map["gate_status"], "blocker_count": len(ts_map["blockers"])},
        {"role": "calculation_dag", "artifact": _rich_ref(dag_path, dag), "gate_status": dag["gate_status"], "blocker_count": len(dag["blockers"])},
    ]
    artifacts.extend({"role": "candidate", "artifact": _rich_ref(path, candidate), "gate_status": "reviewed", "blocker_count": 0} for path, candidate in zip(candidate_paths, candidates, strict=True))
    next_actions: list[dict[str, str]] = []
    if support["blockers"]:
        next_actions.append({"action": "review_mechanism_support", "reason": "Mechanism-support blockers remain.", "authority": "offline_scientific_review_only"})
    if ts_map["blockers"]:
        next_actions.append({"action": "review_ts_precedents", "reason": "One or more mechanism edges lack an accepted TS precedent.", "authority": "offline_scientific_review_only"})
    accepted_precedents = {
        item["precedent_id"] for item in ts_map["records"]
        if item["candidate_construction_gate"] == "candidate_construction_eligible"
    }
    materialized_precedents = {item["precedent_id"] for item in candidates if item["schema"] == CANDIDATE_SCHEMA}
    if accepted_precedents - materialized_precedents:
        next_actions.append({"action": "materialize_reviewed_candidates", "reason": "Accepted coordinate precedents remain unmaterialized.", "authority": "offline_file_creation_only"})
    eligible_de_novo_plans = {
        item["seed_plan_id"] for item in ts_map["de_novo_seed_plans"]
        if item["candidate_construction_gate"] == "candidate_construction_eligible"
    }
    if eligible_de_novo_plans:
        next_actions.append({"action": "review_de_novo_seed_construction", "reason": "Eligible de novo seed plans require a separately implemented and reviewed construction route.", "authority": "offline_scientific_review_only"})
    missing_protocol = [item["node_id"] for item in dag["nodes"] if item["readiness"] == "blocked_missing_protocol"]
    if missing_protocol:
        next_actions.append({"action": "review_protocol_candidates", "reason": "Calculation targets lack explicit protocol selections.", "authority": "offline_protocol_review_only"})
    if dag["ready_for_exact_input_review_node_ids"]:
        next_actions.append({"action": "review_exact_input_drafts", "reason": "Candidate and protocol gates are satisfied for selected DAG nodes.", "authority": "offline_input_review_only"})
    formal_evidence_schemas: set[str] = set()
    formal_energy_comparison_blocked = False
    for node in dag["nodes"]:
        for reference in node["evidence"]:
            schema = reference["schema"]
            if schema not in FORMAL_CALCULATION_ARTIFACT_SCHEMAS:
                continue
            _evidence_path, evidence, _normalized = _verify_evidence_ref(reference, dag_path)
            formal_evidence_schemas.add(schema)
            if schema == "gaussian-energy-lineage/1" and evidence.get("comparison_eligible") is False:
                formal_energy_comparison_blocked = True
    if "gaussian-candidate-target-import/1" in formal_evidence_schemas:
        next_actions.append({
            "action": "review_external_target_dag_binding",
            "reason": "A validated formal target import is present, but external-target-to-network/DAG mapping requires a separate reviewed contract.",
            "authority": "offline_scientific_review_only",
        })
    if formal_energy_comparison_blocked:
        next_actions.append({
            "action": "review_comparable_thermochemistry",
            "reason": "The formal adapter energy lineage is electronic-only and explicitly not comparison-eligible.",
            "authority": "offline_thermochemistry_review_only",
        })
    if not next_actions:
        next_actions.append({"action": "review_terminal_evidence_or_analysis", "reason": "No earlier offline blocker was derived.", "authority": "offline_review_only"})
    completed = sorted(item["node_id"] for item in dag["nodes"] if item["readiness"] == "completed_with_reviewed_evidence")
    artifact = {
        "schema": INDEX_SCHEMA,
        "study_id": next(iter(study_ids)),
        "artifacts": sorted(artifacts, key=lambda item: (item["role"], item["artifact"]["payload_sha256"])),
        "derived_state": {
            "mechanism_gate": network["gate_status"],
            "ts_precedent_gate": ts_map["gate_status"],
            "dag_gate": dag["gate_status"],
            "candidate_count": len(candidates),
            "dag_node_count": len(dag["nodes"]),
            "completed_node_ids": completed,
            "all_required_nodes_completed": all((not item["required"]) or item["node_id"] in completed for item in dag["nodes"]),
        },
        "next_safe_actions": next_actions,
        "status_is_derived_not_editable": True,
        "execution_authorized": False,
        "calculation_ready": False,
        "no_submission_authorization": True,
    }
    rw.finalize_artifact(artifact)
    rw.write_json(output, artifact)
    return artifact


def validate_index(path: Path) -> dict[str, Any]:
    artifact = rw.load_json(path)
    rw.require(artifact.get("schema") == INDEX_SCHEMA, "study-index schema mismatch")
    rw.validate_payload_hash(artifact)
    rw.require(artifact.get("status_is_derived_not_editable") is True and artifact.get("execution_authorized") is False and artifact.get("calculation_ready") is False and artifact.get("no_submission_authorization") is True, "study-index authority or derivation boundary changed")
    by_role: dict[str, list[tuple[Path, dict[str, Any]]]] = {}
    for row in artifact["artifacts"]:
        path_value, data = _verify_ref(row["artifact"], path)
        by_role.setdefault(row["role"], []).append((path_value, data))
    for role in ("mechanism_network", "mechanism_support", "ts_precedent_map", "calculation_dag"):
        rw.require(len(by_role.get(role, [])) == 1, f"study-index requires exactly one {role} artifact")
    recomputed = path.parent / f".{path.name}.recomputed"
    rw.require(not recomputed.exists(), "temporary index recomputation path already exists")
    try:
        rebuilt = build_index(
            by_role["mechanism_network"][0][0],
            by_role["mechanism_support"][0][0],
            by_role["ts_precedent_map"][0][0],
            by_role["calculation_dag"][0][0],
            [item[0] for item in by_role.get("candidate", [])],
            recomputed,
        )
        rw.require(rebuilt == artifact, "study-index artifact differs from independent recomputation")
    finally:
        if recomputed.exists():
            recomputed.unlink()
    return {"schema": "gaussian-reaction-study-index-validation/1", "study_id": artifact["study_id"], "payload_sha256": artifact["payload_sha256"], "live_actions": False}


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    candidate = commands.add_parser("build-candidate", help="Materialize one reviewed Cartesian TS seed")
    candidate.add_argument("ts_precedent_map", type=Path)
    candidate.add_argument("--review", type=Path, required=True)
    candidate.add_argument("--xyz-output", type=Path, required=True)
    candidate.add_argument("--output", type=Path, required=True)
    candidate_validate = commands.add_parser("validate-candidate", help="Validate a candidate materialization")
    candidate_validate.add_argument("artifact", type=Path)
    state_candidate = commands.add_parser("build-state-candidate", help="Materialize one explicitly reviewed state or complex seed")
    state_candidate.add_argument("mechanism_network", type=Path)
    state_candidate.add_argument("--review", type=Path, required=True)
    state_candidate.add_argument("--xyz-output", type=Path, required=True)
    state_candidate.add_argument("--output", type=Path, required=True)
    dag = commands.add_parser("build-dag", help="Build a finite offline calculation DAG")
    dag.add_argument("mechanism_network", type=Path)
    dag.add_argument("ts_precedent_map", type=Path)
    dag.add_argument("--review", type=Path, required=True)
    dag.add_argument("--output", type=Path, required=True)
    dag_validate = commands.add_parser("validate-dag", help="Validate and independently recompute a calculation DAG")
    dag_validate.add_argument("artifact", type=Path)
    index = commands.add_parser("build-index", help="Derive one immutable read-only study index")
    index.add_argument("mechanism_network", type=Path)
    index.add_argument("mechanism_support", type=Path)
    index.add_argument("ts_precedent_map", type=Path)
    index.add_argument("calculation_dag", type=Path)
    index.add_argument("--candidate", action="append", type=Path, default=[])
    index.add_argument("--output", type=Path, required=True)
    index_validate = commands.add_parser("validate-index", help="Validate and independently recompute a study index")
    index_validate.add_argument("artifact", type=Path)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "build-candidate":
            result = build_candidate(args.ts_precedent_map, args.review, args.xyz_output, args.output)
        elif args.command == "validate-candidate":
            result = validate_any_candidate(args.artifact)
        elif args.command == "build-state-candidate":
            result = build_state_candidate(args.mechanism_network, args.review, args.xyz_output, args.output)
        elif args.command == "build-dag":
            result = build_dag(args.mechanism_network, args.ts_precedent_map, args.review, args.output)
        elif args.command == "validate-dag":
            result = validate_dag(args.artifact)
        elif args.command == "build-index":
            result = build_index(args.mechanism_network, args.mechanism_support, args.ts_precedent_map, args.calculation_dag, args.candidate, args.output)
        else:
            result = validate_index(args.artifact)
    except (rw.OfflineError, protocol.ContractError, OSError, ValueError, AssertionError, SystemExit) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
