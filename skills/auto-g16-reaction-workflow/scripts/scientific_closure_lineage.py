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
import os
import re
import stat
import sys
import tempfile
import types
from datetime import datetime
from pathlib import Path
from typing import Any

SCHEMA = "gaussian-minimum-lineage-handoff/1"
SCHEMA_V2 = "gaussian-minimum-lineage-handoff/2"
REVIEW_SCHEMA = "gaussian-minimum-lineage-review/1"
SELECTION_SCHEMA = "gaussian-conformer-selection-receipt/1"
PROCESS_RECONCILIATION_SCHEMA = "gaussian-terminal-process-reconciliation/1"
SOURCE_KINDS = {"conformer_selection", "endpoint_structure_review", "reviewed_result"}
HASH_RE = re.compile(r"^[a-f0-9]{64}$")
OWNER_SOURCE_SHA256 = {
    "log": "ae6ce8b5d9da5f7de11c07522fa2dbaf3f8ccbff0f5d71149b17c95f2cee28ca",
    "approval": "3a978dbfbf6d5111d50c087c3c2df775fd15d5cd3924ea063e5ae674bafc0cdb",
    "input": "ce9158f2c8f3e7c86e7b9442a2f390a9c5a2e67d5d69ff4156dd1c1309b39aff",
}


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


def transport_digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


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


def secure_root(root: Path, label: str = "package root") -> Path:
    lexical = Path(os.path.abspath(root))
    try:
        metadata = os.lstat(lexical)
    except OSError as exc:
        raise LineageError(f"{label} must be an existing non-symlink directory: {root}") from exc
    require(not stat.S_ISLNK(metadata.st_mode) and stat.S_ISDIR(metadata.st_mode), f"{label} must be an existing non-symlink directory: {root}")
    return lexical.resolve()


def _file_without_symlink_components(root: Path, relative: Path, label: str) -> Path:
    root = secure_root(root)
    current = root
    for index, part in enumerate(relative.parts):
        current = current / part
        try:
            metadata = os.lstat(current)
        except OSError as exc:
            raise LineageError(f"{label} must be an existing regular file: {relative}") from exc
        require(not stat.S_ISLNK(metadata.st_mode), f"{label} path component must not be a symlink: {current}")
        if index < len(relative.parts) - 1:
            require(stat.S_ISDIR(metadata.st_mode), f"{label} ancestor must be a directory: {current}")
        else:
            require(stat.S_ISREG(metadata.st_mode), f"{label} must be an existing regular file: {relative}")
    resolved = current.resolve()
    require(resolved.is_relative_to(root), f"{label} escapes package root")
    return resolved


def safe_file(root: Path, relative: str, label: str) -> Path:
    raw = Path(relative)
    require(not raw.is_absolute() and ".." not in raw.parts and str(raw) not in {"", "."}, f"{label} path must be package-root relative")
    return _file_without_symlink_components(root, raw, label)


def reference(path: Path, root: Path, *, json_document: dict[str, Any] | None = None) -> dict[str, Any]:
    lexical_root = Path(os.path.abspath(root))
    root = secure_root(lexical_root)
    lexical = Path(os.path.abspath(path))
    try:
        relative = lexical.relative_to(lexical_root)
    except ValueError:
        raise LineageError(f"source must share the lexical package root: {path}") from None
    require(relative.parts and ".." not in relative.parts, f"source must be inside package root: {path}")
    resolved = _file_without_symlink_components(root, relative, "source")
    result: dict[str, Any] = {"path": relative.as_posix(), "sha256": file_sha256(resolved), "size_bytes": resolved.stat().st_size}
    if json_document is not None:
        result["schema"] = json_document.get("schema")
        result["payload_sha256"] = json_document.get("payload_sha256")
    return result


def publish_json_exclusive(output: Path, artifact: dict[str, Any], validator: Any) -> dict[str, Any]:
    """Validate privately, then publish with an atomic no-clobber hard link."""

    parent = secure_root(output.parent, "output parent")
    output = parent / output.name
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{output.name}.", suffix=".tmp", dir=parent)
    temporary = Path(temporary_name)
    try:
        payload = (json.dumps(artifact, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            descriptor = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        validated = validator(temporary)
        try:
            os.link(temporary, output)
        except FileExistsError as exc:
            raise LineageError(f"refusing concurrent or overwrite publication: {output.name}") from exc
        directory_fd = os.open(parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        return validated
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


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


def _plain_directory(path: Path) -> bool:
    return (
        os.path.lexists(path)
        and not path.is_symlink()
        and path.is_dir()
        and path.resolve(strict=True) == path
    )


def _plain_file(path: Path) -> bool:
    return (
        os.path.lexists(path)
        and not path.is_symlink()
        and path.is_file()
        and path.resolve(strict=True) == path
    )


def owner_paths() -> dict[str, Path]:
    """Select one complete repository or named-package owner layout."""

    source = Path(os.path.abspath(__file__))
    require(
        _plain_file(source)
        and source.name == "scientific_closure_lineage.py"
        and source.parent.name == "scripts"
        and source.parent.parent.name == "auto-g16-reaction-workflow"
        and source.parents[2].name == "skills",
        "minimum-lineage owner source path differs",
    )
    repository_shape = source.parents[3].name != "dependencies"
    named_shape = (
        source.parents[3].name == "dependencies"
        and source.parents[4].name == "auto-g16-rtwin-pbs"
    )
    require(
        repository_shape != named_shape,
        "minimum-lineage requires exactly one repository or named-Skill owner layout",
    )

    if repository_shape:
        repository_root = source.parents[3]
        skills = repository_root / "skills"
        directories = (
            repository_root,
            repository_root / "scripts",
            skills,
            skills / "auto-g16-rtwin-pbs",
            skills / "auto-g16-rtwin-pbs" / "scripts",
            skills / "auto-g16-ts-irc",
            skills / "auto-g16-ts-irc" / "scripts",
            source.parent.parent,
            source.parent,
        )
        paths = {
            "log": skills / "auto-g16-rtwin-pbs" / "scripts" / "gaussian_log.py",
            "approval": skills / "auto-g16-rtwin-pbs" / "scripts" / "gaussian_rtwin_pbs.py",
            "input": skills / "auto-g16-ts-irc" / "scripts" / "ts_irc.py",
        }
        marker = repository_root / "scripts" / "skill_package.py"
        require(
            all(_plain_directory(path) for path in directories)
            and _plain_file(marker)
            and all(_plain_file(path) for path in paths.values()),
            "minimum-lineage repository owner layout is partial or path-drifted",
        )
        return paths

    package_root = source.parents[4]
    dependency_skills = package_root / "dependencies" / "skills"
    second_owner_shapes = (
        dependency_skills / "auto-g16-rtwin-pbs",
        package_root / "skills" / "auto-g16-rtwin-pbs",
    )
    require(
        not any(os.path.lexists(path) for path in second_owner_shapes),
        "minimum-lineage named-Skill layout contains a second RTwin owner",
    )
    directories = (
        package_root,
        package_root / "scripts",
        package_root / "dependencies",
        dependency_skills,
        dependency_skills / "auto-g16-ts-irc",
        dependency_skills / "auto-g16-ts-irc" / "scripts",
        source.parent.parent,
        source.parent,
    )
    paths = {
        "log": package_root / "scripts" / "gaussian_log.py",
        "approval": package_root / "scripts" / "gaussian_rtwin_pbs.py",
        "input": dependency_skills / "auto-g16-ts-irc" / "scripts" / "ts_irc.py",
    }
    require(
        all(_plain_directory(path) for path in directories)
        and _plain_file(package_root / "SKILL.md")
        and all(_plain_file(path) for path in paths.values()),
        "minimum-lineage named-Skill owner layout is partial or path-drifted",
    )
    return paths


def _read_owner_source(path: Path) -> tuple[tuple[int, ...], str]:
    descriptor = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
    )
    try:
        before = os.fstat(descriptor)
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 65536)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    identity = (
        before.st_dev,
        before.st_ino,
        before.st_uid,
        before.st_gid,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    )
    require(
        stat.S_ISREG(before.st_mode)
        and identity
        == (
            after.st_dev,
            after.st_ino,
            after.st_uid,
            after.st_gid,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ),
        f"owner validator identity changed while reading: {path}",
    )
    raw = b"".join(chunks)
    require(len(raw) == before.st_size, f"owner validator size changed while reading: {path}")
    return identity, hashlib.sha256(raw).hexdigest()


def _assert_loaded_owner(
    key: str,
    path: Path,
    module: Any,
    *,
    identity: tuple[int, ...],
    source_sha256: str,
    canonical_name: str | None = None,
) -> Any:
    current_identity, current_sha256 = _read_owner_source(path)
    raw_file = getattr(module, "__file__", None)
    raw_origin = getattr(getattr(module, "__spec__", None), "origin", None)
    require(
        type(module) is types.ModuleType
        and type(raw_file) is str
        and type(raw_origin) is str
        and Path(raw_file).resolve(strict=True) == path
        and Path(raw_origin).resolve(strict=True) == path
        and current_identity == identity
        and current_sha256 == source_sha256 == OWNER_SOURCE_SHA256[key]
        and (
            canonical_name is None
            or sys.modules.get(canonical_name) is module
        ),
        f"owner validator origin, identity, or currentness differs: {path}",
    )
    return module


def load_owner(
    key: str,
    path: Path,
    name: str,
    *,
    canonical: bool = False,
) -> Any:
    require(_plain_file(path), f"owner validator unavailable: {path}")
    identity, source_sha256 = _read_owner_source(path)
    require(
        source_sha256 == OWNER_SOURCE_SHA256[key],
        f"reviewed owner validator bytes differ: {path}",
    )
    if canonical:
        existing = sys.modules.get(name)
        if existing is not None:
            return _assert_loaded_owner(
                key,
                path,
                existing,
                identity=identity,
                source_sha256=source_sha256,
                canonical_name=name,
            )
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, f"owner validator cannot be loaded: {path}")
    module = importlib.util.module_from_spec(spec)
    if canonical:
        sys.modules[name] = module
    sys.path.insert(0, str(path.parent))
    try:
        spec.loader.exec_module(module)
    except BaseException:
        if canonical and sys.modules.get(name) is module:
            del sys.modules[name]
        raise
    finally:
        sys.path.pop(0)
    return _assert_loaded_owner(
        key,
        path,
        module,
        identity=identity,
        source_sha256=source_sha256,
        canonical_name=name if canonical else None,
    )


def owners() -> dict[str, Any]:
    paths = owner_paths()
    log = load_owner(
        "log",
        paths["log"],
        "gaussian_log",
        canonical=True,
    )
    approval = load_owner(
        "approval",
        paths["approval"],
        "closure_input_approval",
    )
    require(
        approval.analyze_log_file is log.analyze_log_file
        and approval.analyze_log_text is log.analyze_log_text
        and approval.analyze_workflow_log_file
        is log.analyze_workflow_log_file,
        "input-approval owner uses another gaussian_log module",
    )
    return {
        "log": log,
        "approval": approval,
        "input": load_owner("input", paths["input"], "closure_ts_input"),
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
    require(settings["standard_state"] in {"1atm", "1M"} and isinstance(settings["expected_stages"], int) and settings["expected_stages"] >= 1, "workflow settings are invalid")
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


def parse_process_probe(path: Path, project: str, input_stem: str) -> dict[str, int]:
    lines = path.read_text(encoding="utf-8").splitlines()
    require(lines and lines[0].startswith("COLLECTED_EPOCH\t"), "process probe lacks a collection epoch")
    epoch_fields = lines[0].split("\t")
    require(len(epoch_fields) == 2 and epoch_fields[1].isdigit() and int(epoch_fields[1]) > 0, "process probe collection epoch is invalid")
    summary: list[list[str]] = []
    ignored = 0
    for line in lines[1:]:
        fields = line.split("\t")
        require(fields and fields[0] in {"IGNORED_INFRASTRUCTURE", "SUMMARY"}, "process probe contains an unknown record")
        if fields[0] == "IGNORED_INFRASTRUCTURE":
            require(len(fields) == 5 and fields[1].isdigit() and fields[2] in {"sshd", "sftp-server"} and fields[3:] == ["1", "0"], "process probe infrastructure exclusion is invalid")
            ignored += 1
        else:
            summary.append(fields)
    require(len(summary) == 1, "process probe must contain exactly one target summary")
    fields = summary[0]
    require(len(fields) == 6 and fields[1] == project and fields[2] == input_stem, "process probe target differs from the exact job")
    require(all(value.isdigit() for value in fields[3:]), "process probe summary counts are invalid")
    matches, unresolved, excluded = map(int, fields[3:])
    require(excluded == ignored, "process probe infrastructure count differs from its records")
    return {"collected_epoch": int(epoch_fields[1]), "match_count": matches, "unresolved_count": unresolved, "ignored_infrastructure_count": excluded}


def validate_process_reconciliation(path: Path, root: Path | None = None) -> dict[str, Any]:
    artifact = load_json(path)
    exact(artifact, {"schema", "project", "job_id", "input_stem", "input_sha256", "terminal_inspection_receipt_sha256", "observations", "stable_duration_seconds", "process_evidence_status", "process_alive", "scientific_acceptance", "calculation_ready", "no_submission_authorization", "payload_sha256"}, "terminal process reconciliation")
    require(artifact["schema"] == PROCESS_RECONCILIATION_SCHEMA and artifact["payload_sha256"] == payload_sha256(artifact), "terminal process reconciliation schema or payload hash is invalid")
    require(re.fullmatch(r"[A-Za-z0-9_.-]+", artifact["project"]) is not None and re.fullmatch(r"[0-9]+(?:\.[A-Za-z0-9_.-]+)?", artifact["job_id"]) is not None and re.fullmatch(r"[A-Za-z0-9_.-]+", artifact["input_stem"]) is not None, "terminal process reconciliation identity is invalid")
    require(HASH_RE.fullmatch(artifact["input_sha256"]) is not None and HASH_RE.fullmatch(artifact["terminal_inspection_receipt_sha256"]) is not None, "terminal process reconciliation hashes are invalid")
    require(artifact["process_evidence_status"] == "absent" and artifact["process_alive"] is False, "terminal process reconciliation does not prove process absence")
    require(artifact["scientific_acceptance"] is False and artifact["calculation_ready"] is False and artifact["no_submission_authorization"] is True, "terminal process reconciliation crosses its authority boundary")
    observations = artifact["observations"]
    require(isinstance(observations, list) and len(observations) == 2, "terminal process reconciliation requires exactly two observations")
    source_root = secure_root(root or path.parent)
    epochs: list[int] = []
    for observation in observations:
        exact(observation, {"source", "collected_epoch", "match_count", "unresolved_count", "ignored_infrastructure_count"}, "terminal process observation")
        source_path, _ = resolve_reference(observation["source"], source_root, "terminal process probe")
        replay = parse_process_probe(source_path, f"/home/user100/SDL/{artifact['project']}", artifact["input_stem"])
        require({key: observation[key] for key in replay} == replay, "terminal process observation differs from raw probe")
        require(replay["match_count"] == 0 and replay["unresolved_count"] == 0, "terminal process probe is present or unresolved")
        epochs.append(replay["collected_epoch"])
    duration = epochs[1] - epochs[0]
    require(duration >= 5 and artifact["stable_duration_seconds"] == duration, "terminal process observations are not stably separated")
    return artifact


def build_process_reconciliation(root: Path, project: str, job_id: str, input_stem: str, input_path: Path, receipt_path: Path, probes: list[Path], output: Path) -> dict[str, Any]:
    lexical_root = Path(os.path.abspath(root)); root = secure_root(lexical_root)
    output = Path(os.path.abspath(output)); require(output.parent.resolve() == root and not output.parent.is_symlink(), "process reconciliation output must be directly inside package root")
    receipt = load_json(receipt_path)
    require(receipt.get("schema") == "gaussian-terminal-inspection-receipt/1" and receipt.get("project") == project and receipt.get("job_id") == job_id and receipt.get("input_stem") == input_stem, "terminal receipt differs from process reconciliation scope")
    input_digest = file_sha256(input_path)
    require(receipt.get("input_sha256") == input_digest and receipt.get("receipt_sha256") == transport_digest({key: value for key, value in receipt.items() if key != "receipt_sha256"}), "terminal receipt input or receipt hash is invalid")
    require(len(probes) == 2, "process reconciliation requires exactly two raw probes")
    observations = []
    for probe in probes:
        parsed = parse_process_probe(probe, f"/home/user100/SDL/{project}", input_stem)
        require(parsed["match_count"] == 0 and parsed["unresolved_count"] == 0, "terminal process probe is present or unresolved")
        observations.append({"source": reference(probe, lexical_root), **parsed})
    duration = observations[1]["collected_epoch"] - observations[0]["collected_epoch"]
    require(duration >= 5, "terminal process probes must be separated by at least five seconds")
    artifact = {"schema": PROCESS_RECONCILIATION_SCHEMA, "project": project, "job_id": job_id, "input_stem": input_stem, "input_sha256": input_digest, "terminal_inspection_receipt_sha256": receipt["receipt_sha256"], "observations": observations, "stable_duration_seconds": duration, "process_evidence_status": "absent", "process_alive": False, "scientific_acceptance": False, "calculation_ready": False, "no_submission_authorization": True, "payload_sha256": None}
    artifact["payload_sha256"] = payload_sha256(artifact)
    return publish_json_exclusive(root / output.name, artifact, lambda candidate: validate_process_reconciliation(candidate, root))


def replay_minimum_sources(root: Path, artifact: dict[str, Any]) -> dict[str, Any]:
    v2 = artifact.get("schema") == SCHEMA_V2
    source_fields = ({"origin", "input_approval", "input", "job", "result", "raw_log", "checkpoint", "optimized_coordinates", "terminal_inspection_receipt", "fetch_snapshot"} if v2 else {"selection", "input_approval", "input", "job", "result", "raw_log", "checkpoint", "optimized_coordinates"})
    sources = artifact["sources"]
    require(isinstance(sources, dict) and set(sources) in {frozenset(source_fields), frozenset(source_fields | {"process_reconciliation"})}, "minimum lineage sources fields are invalid")
    selection = None
    endpoint = None
    if v2:
        origin_path, origin_json = resolve_reference(sources["origin"], root, "minimum origin", json_source=True)
        if artifact["source_kind"] == "conformer_selection":
            selection = validate_selection_receipt(origin_path)
            require(selection == origin_json, "selection replay returned different content")
        elif artifact["source_kind"] == "endpoint_structure_review":
            endpoint = owners()["input"].validate_endpoint_structure_review_artifact(origin_path)
            require(endpoint == origin_json, "endpoint owner replay returned different content")
        elif artifact["source_kind"] == "reviewed_result":
            direct_review = normalize_review(origin_json)
            require(direct_review == origin_json, "reviewed-result origin is not deterministically normalized")
        else:
            raise LineageError("minimum lineage source_kind is unsupported")
    else:
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
    if v2:
        receipt_path, receipt = resolve_reference(sources["terminal_inspection_receipt"], root, "terminal inspection receipt", json_source=True)
        snapshot_path, snapshot = resolve_reference(sources["fetch_snapshot"], root, "fetch snapshot", json_source=True)
        execution = job.get("execution_batch") if isinstance(job.get("execution_batch"), dict) else {}
        attempt_id = execution.get("attempt_id")
        require(isinstance(attempt_id, str) and attempt_id.startswith("qsub-attempt-"), "minimum job lacks an exact execution attempt")
        receipt_fields = {"schema", "project", "job_id", "input_stem", "input_sha256", "attempt_id", "terminal_state", "collected_at", "inspection_evidence_sha256", "inspection", "scientific_acceptance", "receipt_sha256"}
        require(set(receipt) == receipt_fields and receipt.get("schema") == "gaussian-terminal-inspection-receipt/1", "minimum terminal receipt is malformed")
        require(receipt.get("project") == job.get("project") and receipt.get("job_id") == job.get("job_id") and receipt.get("attempt_id") == attempt_id and receipt.get("input_sha256") == job.get("input_sha256") and receipt.get("terminal_state") == job.get("status"), "minimum receipt crosses project/job/attempt/input")
        require(receipt.get("scientific_acceptance") is False and receipt.get("receipt_sha256") == transport_digest({key: value for key, value in receipt.items() if key != "receipt_sha256"}), "minimum terminal receipt hash or authority is invalid")
        inspection = receipt.get("inspection")
        require(isinstance(inspection, dict) and inspection.get("schema") == "gaussian-job-inspection/2" and inspection.get("evidence_sha256") == receipt.get("inspection_evidence_sha256") and inspection.get("evidence_sha256") == transport_digest({key: value for key, value in inspection.items() if key != "evidence_sha256"}), "minimum terminal inspection /2 binding is invalid")
        require(
            inspection.get("project") == job.get("project") and inspection.get("job_id") == job.get("job_id")
            and inspection.get("state") == receipt.get("terminal_state")
            and inspection.get("source") == "single_remote_read_only_snapshot"
            and inspection.get("transport_returncode") == 0,
            "minimum terminal inspection crosses project/job/state/source/returncode",
        )
        require(inspection.get("freshness") == "fresh" and inspection.get("transport_classification") == "success" and inspection.get("termination_counts_known") is True and inspection.get("evidence_conflict") is False, "minimum terminal inspection is stale or unknown")
        if inspection.get("process_alive") is not False:
            require("process_reconciliation" in sources, "minimum terminal process evidence remains unknown")
            process_path, process_reconciliation = resolve_reference(sources["process_reconciliation"], root, "terminal process reconciliation", json_source=True)
            process_reconciliation = validate_process_reconciliation(process_path, root)
            require(process_reconciliation.get("project") == job.get("project") and process_reconciliation.get("job_id") == job.get("job_id") and process_reconciliation.get("input_stem") == receipt.get("input_stem") and process_reconciliation.get("input_sha256") == job.get("input_sha256") and process_reconciliation.get("terminal_inspection_receipt_sha256") == receipt.get("receipt_sha256"), "terminal process reconciliation crosses project/job/input/receipt")
        elif "process_reconciliation" in sources:
            process_path, _ = resolve_reference(sources["process_reconciliation"], root, "terminal process reconciliation", json_source=True)
            process_reconciliation = validate_process_reconciliation(process_path, root)
            require(process_reconciliation.get("project") == job.get("project") and process_reconciliation.get("job_id") == job.get("job_id") and process_reconciliation.get("input_sha256") == job.get("input_sha256") and process_reconciliation.get("terminal_inspection_receipt_sha256") == receipt.get("receipt_sha256"), "terminal process reconciliation crosses project/job/input/receipt")
        require(inspection.get("log_size") == log_path.stat().st_size and inspection.get("full_normal_termination_count") == log_path.read_text(encoding="utf-8", errors="replace").count("Normal termination of Gaussian") and inspection.get("full_error_termination_count") == log_path.read_text(encoding="utf-8", errors="replace").count("Error termination"), "minimum terminal inspection differs from raw log")
        require(snapshot.get("schema") == "gaussian-fetch-snapshot/1" and snapshot.get("snapshot_complete") is True and snapshot.get("per_hop_sha256_verified") is True and snapshot.get("payload_sha256") == transport_digest({key: value for key, value in snapshot.items() if key != "payload_sha256"}), "minimum fetch snapshot is incomplete or invalid")
        require(snapshot.get("project") == job.get("project") and snapshot.get("job_id") == job.get("job_id") and snapshot.get("input_sha256") == job.get("input_sha256") and snapshot.get("terminal_inspection_receipt_sha256") == receipt.get("receipt_sha256"), "minimum fetch snapshot crosses project/job/input/receipt")
        require(job.get("terminal_inspection_receipt_sha256") == receipt.get("receipt_sha256") and job.get("fetch_snapshot_sha256") == file_sha256(snapshot_path) and job.get("fetch_snapshot_size") == snapshot_path.stat().st_size, "minimum job does not bind the exact receipt/fetch snapshot")
        require(snapshot_path.parent.resolve() == log_path.parent.resolve() == checkpoint_path.parent.resolve() == result_path.parent.resolve(), "minimum result/log/checkpoint must belong to the exact fetch snapshot")
        for candidate in (log_path, checkpoint_path, result_path, xyz_path):
            expected = {"sha256": file_sha256(candidate), "size": candidate.stat().st_size}
            require(snapshot.get("artifacts", {}).get(candidate.name) == expected, f"minimum fetch snapshot does not bind {candidate.name}")
        for candidate in (log_path, checkpoint_path):
            expected = {"sha256": file_sha256(candidate), "size": candidate.stat().st_size}
            hop = snapshot.get("per_hop", {}).get(candidate.name)
            require(
                isinstance(hop, dict) and set(hop) == {"server_sha256", "rtwin_sha256", "mac_sha256", "size"}
                and all(hop.get(key) == expected["sha256"] for key in ("server_sha256", "rtwin_sha256", "mac_sha256"))
                and hop.get("size") == expected["size"],
                f"minimum fetch per-hop evidence does not bind {candidate.name}",
            )
    settings = artifact["workflow_settings"]
    replay = owner["log"].analyze_workflow_log_text(log_path.read_text(encoding="utf-8", errors="replace"), temperature_k=float(settings["temperature_k"]), standard_state=settings["standard_state"], expected_stages=settings["expected_stages"])
    if result.get("schema") == "gaussian-result/1":
        base_replay = owner["log"].analyze_log_text(log_path.read_text(encoding="utf-8", errors="replace"))
        for key in set(result) - {"log", "optimized_xyz"}:
            require(result.get(key) == base_replay.get(key), f"minimum result differs from raw-log base-parser replay: {key}")
    else:
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
    if selection is not None:
        candidate_elements = selection.get("candidate_atom_elements")
    elif endpoint is not None:
        candidate_elements = [item["element"] for item in endpoint["endpoint_coordinates"]["records"]]
    else:
        candidate_elements = [item["element"] for item in artifact["atom_mapping"]]
    input_elements = [item["element"] for item in parsed_input["atoms"]]
    result_elements = [item.get("element") for item in replay["final_coordinates"]]
    mapped_elements = [item["element"] for item in mapping]
    require(candidate_elements == input_elements == result_elements == mapped_elements, "candidate, input, result, or stable atom mapping element order differs")
    require(artifact["stable_atom_ids"] == [item["atom_id"] for item in mapping], "stable atom ID mapping changed")
    if endpoint is not None:
        require(endpoint["stable_atom_ids"] == artifact["stable_atom_ids"] and endpoint["structure_identity"]["state_id"] == artifact["state_id"], "endpoint state or stable atom mapping differs from minimum lineage")
        require(endpoint["charge"] == parsed_input["charge"] and endpoint["multiplicity"] == parsed_input["multiplicity"], "endpoint charge or multiplicity differs from Opt/Freq input")
    if artifact.get("source_kind") == "reviewed_result":
        require(direct_review["lineage_id"] == artifact["lineage_id"], "reviewed-result lineage ID differs")
        require(direct_review["minimum_id"] == artifact["minimum_id"] and direct_review["state_id"] == artifact["state_id"], "reviewed-result minimum or state differs")
        require(direct_review["stable_atom_ids"] == artifact["stable_atom_ids"] and direct_review["atom_mapping"] == artifact["atom_mapping"], "reviewed-result stable atom mapping differs")
        require(direct_review["structure_review"] == artifact["structure_review"], "reviewed-result structure review differs")
    require(artifact["formula"] == formula(result_elements), "minimum formula differs from exact result composition")
    require(parsed_input["charge"] == artifact["charge"] and parsed_input["multiplicity"] == artifact["multiplicity"], "minimum input charge or multiplicity differs from lineage")
    coordinates = parse_xyz(xyz_path)
    expected_xyz = [{"index": item.get("center", item.get("index")), "element": item.get("element"), "x": item.get("x"), "y": item.get("y"), "z": item.get("z")} for item in replay["final_coordinates"]]
    require(coordinates == expected_xyz, "optimized coordinates differ from the raw-log-replayed result")
    return {"selection": selection, "approval": approval, "input": parsed_input, "job": job, "result": result, "replay": replay}


def validate_artifact(path: Path) -> dict[str, Any]:
    artifact = load_json(path)
    required = {"schema", "lineage_id", "minimum_id", "state_id", "sources", "workflow_settings", "stable_atom_ids", "atom_mapping", "formula", "charge", "multiplicity", "structure_review", "review", "workflow_states", "acceptance", "migration_policy", "immutability", "calculation_ready", "no_submission_authorization", "payload_sha256"}
    if artifact.get("schema") == SCHEMA_V2:
        required.add("source_kind")
    exact(artifact, required, "minimum lineage handoff")
    require(artifact["schema"] in {SCHEMA, SCHEMA_V2} and artifact["payload_sha256"] == payload_sha256(artifact), "minimum lineage schema or payload hash is invalid")
    if artifact["schema"] == SCHEMA_V2:
        require(artifact["source_kind"] in SOURCE_KINDS, "minimum lineage /2 source_kind is invalid")
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


def build(root: Path, paths: dict[str, Path], review_path: Path, output: Path, *, source_kind: str = "conformer_selection") -> dict[str, Any]:
    lexical_root = Path(os.path.abspath(root))
    root = secure_root(lexical_root)
    output = Path(os.path.abspath(output))
    require(output.parent.resolve() == root and not output.parent.is_symlink(), "output must be a new file directly inside package root")
    output = root / output.name
    review = normalize_review(load_json(review_path))
    require(source_kind in SOURCE_KINDS, "minimum source_kind is invalid")
    origin_key = {
        "conformer_selection": "selection",
        "endpoint_structure_review": "endpoint_structure_review",
        "reviewed_result": "reviewed_result",
    }[source_kind]
    selection = validate_selection_receipt(paths[origin_key]) if source_kind == "conformer_selection" else None
    endpoint = owners()["input"].validate_endpoint_structure_review_artifact(paths[origin_key]) if source_kind == "endpoint_structure_review" else None
    direct_review = normalize_review(load_json(paths[origin_key])) if source_kind == "reviewed_result" else None
    if direct_review is not None:
        require(direct_review == review, "reviewed-result origin must be the exact minimum lineage review")
    parsed_input = owners()["input"].parse_cartesian_input(paths["input"])
    sources: dict[str, Any] = {}
    for key, path in paths.items():
        target_key = "origin" if key == origin_key else key
        document = load_json(path) if key in {origin_key, "input_approval", "job", "result", "terminal_inspection_receipt", "fetch_snapshot", "process_reconciliation"} else None
        sources[target_key] = reference(path, lexical_root, json_document=document)
    result = load_json(paths["result"])
    artifact = {
        "schema": SCHEMA_V2, "source_kind": source_kind, "lineage_id": review["lineage_id"], "minimum_id": review["minimum_id"], "state_id": review["state_id"],
        "sources": sources, "workflow_settings": review["workflow_settings"], "stable_atom_ids": review["stable_atom_ids"], "atom_mapping": review["atom_mapping"],
        "formula": review["structure_review"]["formula"], "charge": parsed_input["charge"], "multiplicity": parsed_input["multiplicity"],
        "structure_review": review["structure_review"],
        "review": {key: review[key] for key in ("decision", "explicit_human_review", "reviewer", "rationale", "reviewed_at")},
        "workflow_states": {"human_selected": True, "input_draft_generated": True, "exact_input_approved": True, "job_observed": True, "submission_authorized_by_this_artifact": False, "result_accepted": True},
        "acceptance": {"status": "minimum_accepted", "raw_log_replayed": True, "complete_frequency_gate_passed": True, "zero_imaginary_frequencies": True, "identity_connectivity_stereochemistry_reviewed": True},
        "migration_policy": {"new_bindings": "package_root_relative_only", "absolute_paths": "rejected", "legacy_absolute_artifacts": "owner_controlled_rebuild_or_reviewed_repackage_required", "in_place_rewrite": False},
        "immutability": "append_only_new_revision", "calculation_ready": False, "no_submission_authorization": True, "payload_sha256": None,
    }
    if selection is not None:
        require(selection.get("formula") == artifact["formula"], "selected conformer formula differs from minimum review")
    elif endpoint is not None:
        require(endpoint["structure_identity"]["formula"] == artifact["formula"], "endpoint formula differs from minimum review")
    else:
        require(direct_review["structure_review"]["formula"] == artifact["formula"], "reviewed-result formula differs from minimum review")
    require(result.get("parser", {}).get("schema") == "auto-g16-gaussian-log-parser/2", "minimum result must record parser schema/version")
    artifact["payload_sha256"] = payload_sha256(artifact)
    replay_minimum_sources(root, artifact)
    return publish_json_exclusive(output, artifact, validate_artifact)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    build_parser = commands.add_parser("build")
    build_parser.add_argument("--root", type=Path, required=True)
    build_parser.add_argument("--source-kind", choices=sorted(SOURCE_KINDS), required=True)
    build_parser.add_argument("--selection", type=Path)
    build_parser.add_argument("--endpoint-structure-review", type=Path)
    for name in ("input-approval", "input", "job", "result", "raw-log", "checkpoint", "optimized-coordinates", "terminal-inspection-receipt", "fetch-snapshot", "review", "output"):
        build_parser.add_argument(f"--{name}", type=Path, required=True)
    build_parser.add_argument("--process-reconciliation", type=Path)
    process_parser = commands.add_parser("reconcile-process")
    process_parser.add_argument("--root", type=Path, required=True)
    process_parser.add_argument("--project", required=True)
    process_parser.add_argument("--job-id", required=True)
    process_parser.add_argument("--input-stem", required=True)
    process_parser.add_argument("--input", type=Path, required=True)
    process_parser.add_argument("--terminal-inspection-receipt", type=Path, required=True)
    process_parser.add_argument("--probe", type=Path, action="append", required=True)
    process_parser.add_argument("--output", type=Path, required=True)
    validate_parser = commands.add_parser("validate")
    validate_parser.add_argument("artifact", type=Path)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "validate":
            artifact = validate_artifact(args.artifact)
        elif args.command == "reconcile-process":
            artifact = build_process_reconciliation(args.root, args.project, args.job_id, args.input_stem, args.input, args.terminal_inspection_receipt, args.probe, args.output)
        else:
            if args.source_kind == "conformer_selection":
                origin = args.selection
                require(origin is not None and args.endpoint_structure_review is None, "minimum source kinds are mutually exclusive and require exactly one origin")
                origin_key = "selection"
            elif args.source_kind == "endpoint_structure_review":
                origin = args.endpoint_structure_review
                require(origin is not None and args.selection is None, "minimum source kinds are mutually exclusive and require exactly one origin")
                origin_key = "endpoint_structure_review"
            else:
                origin = args.review
                require(args.selection is None and args.endpoint_structure_review is None, "reviewed_result cannot carry a conformer or IRC-endpoint origin")
                origin_key = "reviewed_result"
            paths = {origin_key: origin, "input_approval": args.input_approval, "input": args.input, "job": args.job, "result": args.result, "raw_log": args.raw_log, "checkpoint": args.checkpoint, "optimized_coordinates": args.optimized_coordinates, "terminal_inspection_receipt": args.terminal_inspection_receipt, "fetch_snapshot": args.fetch_snapshot}
            if args.process_reconciliation is not None:
                paths["process_reconciliation"] = args.process_reconciliation
            artifact = build(args.root, paths, args.review, args.output, source_kind=args.source_kind)
        response = {"schema": artifact["schema"], "payload_sha256": artifact["payload_sha256"], "live_actions": False}
        if "minimum_id" in artifact:
            response["minimum_id"] = artifact["minimum_id"]
        print(json.dumps(response, ensure_ascii=False))
        return 0
    except (LineageError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
