#!/usr/bin/env python3
"""Statically audit the offline Auto-G16 required-check declaration contract."""

from __future__ import annotations

import argparse
import itertools
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


SCHEMA = "auto-g16-required-checks/1"
RESULT_SCHEMA = "auto-g16-ci-contract-audit-result/1"
TOP_LEVEL_KEYS = {
    "schema",
    "version",
    "description",
    "source_evidence",
    "required_checks",
    "remote_branch_protection_snapshot",
    "limitations",
}
CHECK_KEYS = {"context", "workflow_file", "workflow_name", "job_id", "matrix"}
PLACEHOLDER = re.compile(r"\$\{\{\s*matrix\.([A-Za-z0-9_-]+)\s*\}\}")
KEY = r"[A-Za-z0-9_-]+"


class ContractError(ValueError):
    """The contract or supported workflow syntax is invalid."""


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContractError(f"duplicate JSON key is forbidden: {ascii(key)}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ContractError(f"non-standard JSON numeric constant is forbidden: {value}")


def find_root(start: Path) -> Path:
    result = subprocess.run(
        ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return Path(result.stdout.strip()).resolve()
    candidate = Path(__file__).resolve().parents[1]
    if (candidate / "config" / "required-checks.json").is_file():
        return candidate
    raise ContractError("repository root could not be located")


def load_contract(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ContractError("required-check contract must be a regular non-symlink file")
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=_reject_constant,
            object_pairs_hook=_object,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"invalid required-check contract: {exc}") from exc
    if not isinstance(value, dict) or set(value) != TOP_LEVEL_KEYS:
        raise ContractError("required-check contract must be a closed object")
    if value["schema"] != SCHEMA or value["version"] != 1:
        raise ContractError("unsupported required-check contract schema/version")
    for key in ("description",):
        if not isinstance(value[key], str) or not value[key].strip():
            raise ContractError(f"{key} must be a non-empty string")
    if not isinstance(value["limitations"], list) or not value["limitations"] or not all(
        isinstance(item, str) and item.strip() for item in value["limitations"]
    ):
        raise ContractError("limitations must be a non-empty string array")
    checks = value["required_checks"]
    if not isinstance(checks, list) or not checks:
        raise ContractError("required_checks must be a non-empty array")
    contexts: list[str] = []
    for index, check in enumerate(checks):
        if not isinstance(check, dict) or set(check) != CHECK_KEYS:
            raise ContractError(f"required_checks[{index}] must be a closed check mapping")
        for key in ("context", "workflow_file", "workflow_name", "job_id"):
            if not isinstance(check[key], str) or not check[key].strip():
                raise ContractError(f"required_checks[{index}].{key} must be a non-empty string")
        if not isinstance(check["matrix"], dict) or not all(
            isinstance(key, str) and isinstance(item, str) for key, item in check["matrix"].items()
        ):
            raise ContractError(f"required_checks[{index}].matrix must map strings to strings")
        path = Path(check["workflow_file"])
        if path.is_absolute() or ".." in path.parts or path.suffix not in {".yml", ".yaml"}:
            raise ContractError(f"required_checks[{index}].workflow_file is unsafe")
        if not re.fullmatch(KEY, check["job_id"]):
            raise ContractError(f"required_checks[{index}].job_id is unsupported")
        contexts.append(check["context"])
    if len(contexts) != len(set(contexts)):
        raise ContractError("required check contexts must be unique")
    evidence = value["source_evidence"]
    if not isinstance(evidence, dict) or set(evidence) != {"observed_at", "successful_run_id", "workflow_name", "basis"}:
        raise ContractError("source_evidence must be a closed evidence object")
    for key in ("observed_at", "workflow_name", "basis"):
        if not isinstance(evidence[key], str) or not evidence[key].strip():
            raise ContractError(f"source_evidence.{key} must be a non-empty string")
    if (
        not isinstance(evidence["successful_run_id"], int)
        or isinstance(evidence["successful_run_id"], bool)
        or evidence["successful_run_id"] <= 0
    ):
        raise ContractError("source_evidence.successful_run_id must be positive")
    snapshot = value["remote_branch_protection_snapshot"]
    snapshot_keys = {
        "observed_at",
        "strict",
        "app_id",
        "required_contexts",
        "enforce_admins",
        "required_conversation_resolution",
        "allow_force_pushes",
        "allow_deletions",
        "rulesets_count",
        "status",
        "note",
    }
    if not isinstance(snapshot, dict) or set(snapshot) != snapshot_keys:
        raise ContractError("remote_branch_protection_snapshot must be a closed snapshot object")
    for key in ("observed_at", "status", "note"):
        if not isinstance(snapshot[key], str) or not snapshot[key].strip():
            raise ContractError(f"snapshot {key} must be a non-empty string")
    if snapshot["status"] not in {"aligned", "known_mismatch"}:
        raise ContractError("snapshot status must be aligned or known_mismatch")
    for key in ("strict", "enforce_admins", "required_conversation_resolution", "allow_force_pushes", "allow_deletions"):
        if not isinstance(snapshot[key], bool):
            raise ContractError(f"snapshot {key} must be boolean")
    for key in ("app_id", "rulesets_count"):
        if not isinstance(snapshot[key], int) or isinstance(snapshot[key], bool) or snapshot[key] < 0:
            raise ContractError(f"snapshot {key} must be a non-negative integer")
    if not isinstance(snapshot["required_contexts"], list) or not all(
        isinstance(item, str) and item.strip() for item in snapshot["required_contexts"]
    ):
        raise ContractError("snapshot required_contexts must be a string array")
    if len(snapshot["required_contexts"]) != len(set(snapshot["required_contexts"])):
        raise ContractError("snapshot required_contexts must be unique")
    return value


def _scalar(raw: str, label: str) -> str:
    value = raw.strip()
    if not value or value[0] in "[|>&*!{" or value.startswith(("null", "~")):
        raise ContractError(f"{label} uses unsupported YAML scalar syntax")
    if value[0] in {'"', "'"}:
        if len(value) < 2 or value[-1] != value[0]:
            raise ContractError(f"{label} has an unterminated quoted scalar")
        return value[1:-1]
    if " #" in value:
        value = value.split(" #", 1)[0].rstrip()
    return value


def _workflow_job_blocks(path: Path) -> tuple[str, list[tuple[str, list[str]]]]:
    """Return explicit job blocks from the repository's restricted YAML subset."""
    if path.is_symlink() or not path.is_file():
        raise ContractError(f"{path.name}: workflow must be a regular non-symlink file")
    text = path.read_text(encoding="utf-8")
    if "\t" in text or re.search(r"(?m)^\s*(?:<<:|[^#\n]*[&*][A-Za-z0-9_-]+)", text):
        raise ContractError(f"{path.name}: tabs, anchors, aliases, and merge keys are unsupported")
    lines = text.splitlines()
    workflow_names = [match.group(1) for line in lines if (match := re.fullmatch(r"name:\s*(.+)", line))]
    if len(workflow_names) != 1:
        raise ContractError(f"{path.name}: exactly one top-level workflow name is required")
    workflow_name = _scalar(workflow_names[0], f"{path.name}: workflow name")
    try:
        jobs_index = lines.index("jobs:")
    except ValueError as exc:
        raise ContractError(f"{path.name}: top-level jobs mapping is missing") from exc
    job_starts: list[tuple[int, str]] = []
    for index in range(jobs_index + 1, len(lines)):
        match = re.fullmatch(rf"  ({KEY}):\s*", lines[index])
        if match:
            job_starts.append((index, match.group(1)))
        elif lines[index] and not lines[index].startswith(" "):
            break
    if not job_starts:
        raise ContractError(f"{path.name}: no supported jobs were found")
    blocks = [
        (
            job_id,
            lines[
                start + 1 : job_starts[position + 1][0]
                if position + 1 < len(job_starts)
                else len(lines)
            ],
        )
        for position, (start, job_id) in enumerate(job_starts)
    ]
    return workflow_name, blocks


def parse_workflow(path: Path) -> tuple[str, dict[str, set[tuple[str, tuple[tuple[str, str], ...]]]]]:
    """Parse and expand the repository's deliberately small YAML subset."""
    workflow_name, job_blocks = _workflow_job_blocks(path)
    expanded: dict[str, set[tuple[str, tuple[tuple[str, str], ...]]]] = {}
    for job_id, block in job_blocks:
        names = [match.group(1) for line in block if (match := re.fullmatch(r"    name:\s*(.+)", line))]
        if len(names) != 1:
            raise ContractError(f"{path.name}:{job_id}: one explicit job name is required")
        template = _scalar(names[0], f"{path.name}:{job_id}: job name")
        matrix_headers = [index for index, line in enumerate(block) if line == "      matrix:"]
        matrix: dict[str, list[str]] = {}
        if matrix_headers:
            if len(matrix_headers) != 1:
                raise ContractError(f"{path.name}:{job_id}: multiple matrix mappings are unsupported")
            index = matrix_headers[0] + 1
            while index < len(block) and (not block[index] or block[index].startswith("        ")):
                line = block[index]
                if line and not line.lstrip().startswith("#"):
                    match = re.fullmatch(rf"        ({KEY}):\s*(\[.*\])\s*", line)
                    if not match:
                        raise ContractError(f"{path.name}:{job_id}: only inline string-array matrix axes are supported")
                    try:
                        values = json.loads(match.group(2))
                    except json.JSONDecodeError as exc:
                        raise ContractError(f"{path.name}:{job_id}: matrix values must use JSON-compatible quoting") from exc
                    if not isinstance(values, list) or not values or not all(isinstance(item, str) and item for item in values):
                        raise ContractError(f"{path.name}:{job_id}: matrix values must be non-empty strings")
                    if len(values) != len(set(values)):
                        raise ContractError(f"{path.name}:{job_id}: duplicate matrix values are forbidden")
                    matrix[match.group(1)] = values
                index += 1
        placeholders = set(PLACEHOLDER.findall(template))
        if "${{" in template and not placeholders:
            raise ContractError(f"{path.name}:{job_id}: unsupported job-name expression")
        if placeholders != set(matrix):
            raise ContractError(f"{path.name}:{job_id}: job-name matrix placeholders must exactly match matrix axes")
        axes = sorted(matrix)
        combinations = itertools.product(*(matrix[axis] for axis in axes)) if axes else [()]
        for values in combinations:
            binding = dict(zip(axes, values, strict=True))
            context = template
            for axis, value in binding.items():
                context = re.sub(r"\$\{\{\s*matrix\." + re.escape(axis) + r"\s*\}\}", value, context)
            if "${{" in context:
                raise ContractError(f"{path.name}:{job_id}: unresolved job-name expression")
            if context in expanded:
                raise ContractError(f"{path.name}: duplicate expanded check name: {context}")
            expanded[context] = {(job_id, tuple(sorted(binding.items())))}
    return workflow_name, expanded


def parse_setup_python_versions(path: Path) -> dict[str, list[str]]:
    """Extract setup-python selectors without introducing another YAML parser."""
    _workflow_name, job_blocks = _workflow_job_blocks(path)
    result: dict[str, list[str]] = {}
    for job_id, block in job_blocks:
        selectors: list[str] = []
        step_starts = [
            index
            for index, line in enumerate(block)
            if re.fullmatch(r"      - (?:uses|name|run):.*", line)
        ]
        for position, start in enumerate(step_starts):
            line = block[start]
            if not re.fullmatch(r"      - uses:\s*actions/setup-python@[0-9a-f]{40}\s*", line):
                continue
            end = step_starts[position + 1] if position + 1 < len(step_starts) else len(block)
            step = block[start + 1 : end]
            with_headers = [index for index, item in enumerate(step) if item == "        with:"]
            if len(with_headers) != 1:
                raise ContractError(
                    f"{path.name}:{job_id}: setup-python requires one explicit with mapping"
                )
            python_versions = [
                match.group(1)
                for item in step[with_headers[0] + 1 :]
                if (match := re.fullmatch(r"          python-version:\s*(.+)", item))
            ]
            if len(python_versions) != 1:
                raise ContractError(
                    f"{path.name}:{job_id}: setup-python requires one explicit python-version"
                )
            selectors.append(
                _scalar(
                    python_versions[0],
                    f"{path.name}:{job_id}: setup-python python-version",
                )
            )
        result[job_id] = selectors
    return result


def parse_run_commands(path: Path) -> dict[str, list[str]]:
    """Extract explicit run payloads from the repository's restricted workflow form."""
    _workflow_name, job_blocks = _workflow_job_blocks(path)
    result: dict[str, list[str]] = {}
    for job_id, block in job_blocks:
        commands: list[str] = []
        for index, line in enumerate(block):
            match = re.fullmatch(r"        run:\s*(.*)", line)
            if not match:
                continue
            raw = match.group(1)
            if raw in {"|", "|-", "|+", ">", ">-", ">+"}:
                payload: list[str] = []
                cursor = index + 1
                while cursor < len(block) and (
                    not block[cursor] or block[cursor].startswith("          ")
                ):
                    payload.append(block[cursor][10:] if block[cursor] else "")
                    cursor += 1
                commands.append("\n".join(payload))
            elif raw:
                commands.append(_scalar(raw, f"{path.name}:{job_id}: run command"))
            else:
                raise ContractError(f"{path.name}:{job_id}: empty run command is unsupported")
        result[job_id] = commands
    return result


def audit(root: Path, contract: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    declared: dict[str, tuple[str, str, tuple[tuple[str, str], ...]]] = {}
    workflow_files = sorted((root / ".github" / "workflows").glob("*.y*ml"))
    if not workflow_files:
        errors.append("no GitHub Actions workflow exists; a green required-check contract cannot be inferred")
    for path in workflow_files:
        relative = path.relative_to(root).as_posix()
        try:
            workflow_name, contexts = parse_workflow(path)
        except (ContractError, OSError, UnicodeError) as exc:
            errors.append(str(exc))
            continue
        for context, mapping_set in contexts.items():
            job_id, binding = next(iter(mapping_set))
            if context in declared:
                errors.append(f"duplicate local workflow check name: {context}")
                continue
            declared[context] = (relative, workflow_name, binding + (("__job_id__", job_id),))
    expected = {item["context"]: item for item in contract["required_checks"]}
    for context in sorted(expected.keys() - declared.keys()):
        errors.append(f"contract context is not declared by local workflows: {context}")
    for context in sorted(declared.keys() - expected.keys()):
        errors.append(f"local workflow check is missing from the required contract: {context}")
    for context in sorted(expected.keys() & declared.keys()):
        item = expected[context]
        workflow_file, workflow_name, packed = declared[context]
        packed_map = dict(packed)
        job_id = packed_map.pop("__job_id__")
        if workflow_file != item["workflow_file"] or workflow_name != item["workflow_name"] or job_id != item["job_id"] or packed_map != item["matrix"]:
            errors.append(f"contract mapping does not exactly match local workflow expansion: {context}")
    evidence_name = contract["source_evidence"]["workflow_name"]
    if any(item["workflow_name"] != evidence_name for item in contract["required_checks"]):
        errors.append("source evidence workflow_name does not match every required check")

    snapshot = contract["remote_branch_protection_snapshot"]
    snapshot_context_list = snapshot["required_contexts"]
    snapshot_contexts = set(snapshot_context_list)
    missing_in_snapshot = sorted(set(expected) - snapshot_contexts)
    extra_in_snapshot = sorted(snapshot_contexts - set(expected))
    snapshot_differs = bool(missing_in_snapshot or extra_in_snapshot)
    if not snapshot_differs and snapshot_context_list != list(expected):
        errors.append("recorded remote snapshot context order differs from the expected contract")
    if snapshot["status"] == "aligned" and snapshot_differs:
        errors.append("recorded remote snapshot is labelled aligned but differs from the expected contract")
    elif snapshot["status"] == "known_mismatch" and not snapshot_differs:
        errors.append(
            "recorded remote snapshot is labelled known_mismatch but matches the expected contract"
        )
    elif snapshot_differs:
        warnings.append(
            "recorded remote snapshot differs from the expected contract; it is historical evidence and requires live read-only re-verification before merge or release"
        )
    status = "fail" if errors else ("pass_with_warnings" if warnings else "pass")
    return {
        "schema": RESULT_SCHEMA,
        "status": status,
        "claim": "local workflow declarations and snapshot metadata are compatible with the required-check contract" if not errors else "local workflow declarations or snapshot metadata are not compatible with the required-check contract",
        "remote_branch_protection_verified": False,
        "actual_ci_success_verified": False,
        "summary": {"errors": len(errors), "warnings": len(warnings), "declared_contexts": len(declared)},
        "declared_contexts": sorted(declared),
        "errors": errors,
        "warnings": warnings,
        "snapshot_difference": {"missing_expected_contexts": missing_in_snapshot, "unexpected_contexts": extra_in_snapshot},
        "limitations": [
            "Static YAML inspection proves declaration compatibility only.",
            "It cannot prove current GitHub branch protection, required-check configuration, permissions, run completion, or CI success.",
            "The parser intentionally supports only explicit job names and simple inline string matrices used by this repository; other syntax fails closed.",
        ],
    }


def _print_text(report: dict[str, Any]) -> None:
    print(f"Auto-G16 CI contract audit: {report['status']}")
    print(report["claim"])
    for item in report["errors"]:
        print(f"ERROR: {item}", file=sys.stderr)
    for item in report["warnings"]:
        print(f"WARNING: {item}")
    print("Remote branch protection and actual CI success: not verified by this offline audit")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="repository path or a path inside it")
    parser.add_argument("--config", type=Path, help="required-check contract path; defaults inside the repository")
    parser.add_argument("--json", action="store_true", help="emit one machine-readable JSON document")
    args = parser.parse_args(argv)
    try:
        root = find_root(args.repo)
        config_path = args.config
        if config_path is None:
            config_path = root / "config" / "required-checks.json"
        elif not config_path.is_absolute():
            config_path = root / config_path
        report = audit(root, load_contract(config_path))
    except (ContractError, OSError, UnicodeError) as exc:
        error = {"schema": RESULT_SCHEMA, "status": "error", "error": str(exc)}
        if args.json:
            print(json.dumps(error, ensure_ascii=False, sort_keys=True))
        else:
            print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    else:
        _print_text(report)
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
