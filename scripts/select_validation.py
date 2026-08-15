#!/usr/bin/env python3
"""Select offline validation from an exact Git diff and a closed routing manifest."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_RELATIVE = "config/validation-selection.json"
MANIFEST_SCHEMA = "auto-g16-validation-selection/1"
RESULT_SCHEMA = "auto-g16-validation-selection-result/2"
LANES = ("focused", "affected", "v3-full", "legacy-release")
MANIFEST_KEYS = {
    "schema",
    "version",
    "lane_order",
    "fallback_lane",
    "v3_full_tests",
    "self_protecting_paths",
    "generated_prefixes",
    "safety_evidence",
    "routes",
}
ROUTE_KEYS = {
    "id",
    "exact_paths",
    "prefixes",
    "lane",
    "tests",
    "required_safety",
    "fail_closed",
}
RESULT_KEYS = {
    "schema",
    "version",
    "base",
    "head",
    "merge_base",
    "head_tree",
    "changed_paths",
    "changes",
    "lane",
    "tests",
    "matched_routes",
    "safety_evidence",
    "fail_closed",
    "reasons",
    "repository_root",
    "repository_identity",
    "manifest_path",
    "manifest_blob",
    "git_executable",
    "git_version",
}
FULL_SHA = re.compile(r"[0-9a-f]{40}")


class SelectionError(ValueError):
    """Selector input or routing data is unavailable, invalid, or ambiguous."""


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SelectionError(f"duplicate JSON key is forbidden: {ascii(key)}")
        result[key] = value
    return result


def _string_list(value: Any, label: str, *, allow_empty: bool = True) -> list[str]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item and item == item.strip() for item in value
    ):
        raise SelectionError(f"{label} must be a trimmed string array")
    if not allow_empty and not value:
        raise SelectionError(f"{label} must not be empty")
    if len(value) != len(set(value)):
        raise SelectionError(f"{label} must not contain duplicates")
    return value


def _relative_path(value: str, label: str, *, prefix: bool = False) -> str:
    if "\\" in value or value.startswith("/"):
        raise SelectionError(f"{label} must be a repository-relative POSIX path")
    path = PurePosixPath(value)
    if not value or any(part in {"", ".", ".."} for part in path.parts):
        raise SelectionError(f"{label} must be a normalized repository-relative path")
    canonical = path.as_posix() + ("/" if value.endswith("/") else "")
    if value != canonical:
        raise SelectionError(f"{label} must be a normalized repository-relative path")
    if not prefix and value.endswith("/"):
        raise SelectionError(f"{label} must not end with /")
    return value


def _test_names(value: Any, label: str, *, allow_empty: bool = True) -> list[str]:
    names = _string_list(value, label, allow_empty=allow_empty)
    if any(not item.startswith("tests.") for item in names):
        raise SelectionError(f"{label} entries must be dotted tests.* names")
    return names


def validate_manifest(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != MANIFEST_KEYS:
        raise SelectionError("validation selection manifest must be a closed object")
    if value["schema"] != MANIFEST_SCHEMA or value["version"] != 1:
        raise SelectionError("unsupported validation selection manifest schema/version")
    if value["lane_order"] != list(LANES) or value["fallback_lane"] != "legacy-release":
        raise SelectionError("lane order and fail-closed fallback must remain exact")
    _test_names(value["v3_full_tests"], "v3_full_tests", allow_empty=False)

    self_paths = _string_list(value["self_protecting_paths"], "self_protecting_paths", allow_empty=False)
    for index, path in enumerate(self_paths):
        _relative_path(path, f"self_protecting_paths[{index}]")
    generated = _string_list(value["generated_prefixes"], "generated_prefixes", allow_empty=False)
    for index, prefix in enumerate(generated):
        _relative_path(prefix, f"generated_prefixes[{index}]", prefix=True)
        if not prefix.endswith("/"):
            raise SelectionError(f"generated_prefixes[{index}] must end with /")

    safety = value["safety_evidence"]
    if not isinstance(safety, dict) or not safety:
        raise SelectionError("safety_evidence must be a non-empty object")
    for tag, tests in safety.items():
        if not isinstance(tag, str) or not tag or tag != tag.strip():
            raise SelectionError("safety_evidence keys must be trimmed strings")
        _test_names(tests, f"safety_evidence[{tag!r}]", allow_empty=False)

    routes = value["routes"]
    if not isinstance(routes, list) or not routes:
        raise SelectionError("routes must be a non-empty array")
    route_ids: set[str] = set()
    route_exact: dict[str, str] = {}
    route_prefixes: list[tuple[str, str]] = []
    for index, route in enumerate(routes):
        label = f"routes[{index}]"
        if not isinstance(route, dict) or set(route) != ROUTE_KEYS:
            raise SelectionError(f"{label} must be a closed route object")
        route_id = route["id"]
        if not isinstance(route_id, str) or not route_id or route_id != route_id.strip():
            raise SelectionError(f"{label}.id must be a trimmed string")
        if route_id in route_ids:
            raise SelectionError(f"duplicate route id is forbidden: {route_id}")
        route_ids.add(route_id)
        exact_paths = _string_list(route["exact_paths"], f"{label}.exact_paths")
        prefixes = _string_list(route["prefixes"], f"{label}.prefixes")
        if not exact_paths and not prefixes:
            raise SelectionError(f"{label} must own at least one path or prefix")
        for item_index, path in enumerate(exact_paths):
            _relative_path(path, f"{label}.exact_paths[{item_index}]")
            if path in route_exact:
                raise SelectionError(f"ambiguous exact path appears in multiple routes: {path}")
            route_exact[path] = route_id
        for item_index, prefix in enumerate(prefixes):
            _relative_path(prefix, f"{label}.prefixes[{item_index}]", prefix=True)
            route_prefixes.append((prefix, route_id))
        if route["lane"] not in LANES:
            raise SelectionError(f"{label}.lane is unsupported")
        tests = _test_names(route["tests"], f"{label}.tests")
        if route["lane"] in {"focused", "affected"} and not tests:
            raise SelectionError(f"{label} focused/affected routes must select tests")
        required = _string_list(route["required_safety"], f"{label}.required_safety")
        if any(tag not in safety for tag in required):
            raise SelectionError(f"{label} references unavailable safety evidence")
        if not isinstance(route["fail_closed"], bool):
            raise SelectionError(f"{label}.fail_closed must be boolean")

    for exact, exact_owner in route_exact.items():
        for prefix, prefix_owner in route_prefixes:
            if exact.startswith(prefix) and exact_owner != prefix_owner:
                raise SelectionError(f"ambiguous manifest ownership for path: {exact}")
    for index, (left, left_owner) in enumerate(route_prefixes):
        for right, right_owner in route_prefixes[index + 1 :]:
            if left_owner != right_owner and (left.startswith(right) or right.startswith(left)):
                raise SelectionError(f"ambiguous manifest prefixes: {left} and {right}")
    return value


def _decode_manifest(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_object)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise SelectionError(f"invalid validation selection manifest: {exc}") from exc
    return validate_manifest(value)


def _load_manifest_for_test(path: Path) -> dict[str, Any]:
    """Load an alternate manifest only for the closed in-process test seam."""
    if path.is_symlink() or not path.is_file():
        raise SelectionError("validation selection manifest must be a regular non-symlink file")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise SelectionError(f"invalid validation selection manifest: {exc}") from exc
    return _decode_manifest(raw)


def resolve_git() -> tuple[str, str]:
    located = shutil.which("git")
    if not located:
        raise SelectionError("Git executable is unavailable")
    try:
        executable = Path(located).resolve(strict=True)
    except OSError as exc:
        raise SelectionError("Git executable identity is unavailable") from exc
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise SelectionError("Git executable is not a runnable regular file")
    result = subprocess.run(
        [str(executable), "--version"],
        check=False,
        capture_output=True,
        text=True,
    )
    version = result.stdout.strip()
    if result.returncode != 0 or not version.startswith("git version ") or "\n" in version:
        raise SelectionError("Git executable version is unavailable or malformed")
    return str(executable), version


def _git(
    git_executable: str,
    root: Path,
    *args: str,
    text: bool = False,
) -> subprocess.CompletedProcess[Any]:
    return subprocess.run(
        [git_executable, "-C", str(root), *args],
        check=False,
        capture_output=True,
        text=text,
    )


def find_root(start: Path, git_executable: str) -> Path:
    result = _git(git_executable, start, "rev-parse", "--show-toplevel", text=True)
    if result.returncode != 0:
        raise SelectionError("repository root is unavailable")
    return Path(result.stdout.strip()).resolve()


def _resolve_commit(root: Path, value: str, label: str, git_executable: str) -> str:
    if not FULL_SHA.fullmatch(value):
        raise SelectionError(f"{label} must be a full lowercase 40-character commit SHA")
    result = _git(
        git_executable,
        root,
        "rev-parse",
        "--verify",
        f"{value}^{{commit}}",
        text=True,
    )
    if result.returncode != 0 or result.stdout.strip() != value:
        raise SelectionError(f"{label} commit is unavailable or does not resolve exactly")
    return value


def parse_name_status(raw: bytes) -> list[dict[str, Any]]:
    fields = raw.split(b"\0")
    if fields and fields[-1] == b"":
        fields.pop()
    changes: list[dict[str, Any]] = []
    index = 0
    while index < len(fields):
        try:
            status = fields[index].decode("ascii", errors="strict")
        except UnicodeError as exc:
            raise SelectionError("Git diff status is not ASCII") from exc
        index += 1
        kind = status[:1]
        if kind not in {"A", "C", "D", "M", "R", "T"}:
            raise SelectionError(f"unsupported or unresolved Git diff status: {status!r}")
        path_count = 2 if kind in {"C", "R"} else 1
        if index + path_count > len(fields):
            raise SelectionError("Git diff contains an incomplete path record")
        paths: list[str] = []
        for offset in range(path_count):
            try:
                path = fields[index + offset].decode("utf-8", errors="strict")
            except UnicodeError as exc:
                raise SelectionError("Git diff path is not valid UTF-8") from exc
            paths.append(_relative_path(path, "Git diff path"))
        index += path_count
        changes.append({"status": status, "paths": paths})
    return changes


def inspect_git_range(
    root: Path,
    base: str,
    head: str,
    *,
    git_executable: str | None = None,
) -> tuple[list[dict[str, Any]], str, str]:
    if git_executable is None:
        git_executable, _version = resolve_git()
    base = _resolve_commit(root, base, "base", git_executable)
    head = _resolve_commit(root, head, "head", git_executable)
    merge = _git(git_executable, root, "merge-base", "--all", base, head, text=True)
    merge_bases = merge.stdout.splitlines() if merge.returncode == 0 else []
    if len(merge_bases) != 1 or not FULL_SHA.fullmatch(merge_bases[0]):
        raise SelectionError("base and head must have exactly one available merge base")
    merge_base = merge_bases[0]
    tree = _git(
        git_executable,
        root,
        "rev-parse",
        "--verify",
        f"{head}^{{tree}}",
        text=True,
    )
    if tree.returncode != 0 or not FULL_SHA.fullmatch(tree.stdout.strip()):
        raise SelectionError("head tree is unavailable")
    diff = _git(
        git_executable,
        root,
        "diff",
        "--name-status",
        "-z",
        "--find-renames=50%",
        "--find-copies=50%",
        "--find-copies-harder",
        merge_base,
        head,
        "--",
    )
    if diff.returncode != 0:
        raise SelectionError("Git diff could not be inspected")
    return parse_name_status(diff.stdout), merge_base, tree.stdout.strip()


def _repository_identity(root: Path, git_executable: str) -> str:
    result = _git(
        git_executable,
        root,
        "rev-parse",
        "--path-format=absolute",
        "--git-common-dir",
        text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise SelectionError("repository identity is unavailable")
    try:
        identity = Path(result.stdout.strip()).resolve(strict=True)
    except OSError as exc:
        raise SelectionError("repository identity is unavailable") from exc
    if not identity.is_dir():
        raise SelectionError("repository identity is not a directory")
    return str(identity)


def _candidate_manifest(
    root: Path,
    head: str,
    git_executable: str,
) -> tuple[dict[str, Any], str]:
    entry = _git(
        git_executable,
        root,
        "ls-tree",
        "-z",
        head,
        "--",
        MANIFEST_RELATIVE,
    )
    expected_suffix = b"\t" + MANIFEST_RELATIVE.encode("utf-8") + b"\0"
    if entry.returncode != 0 or not entry.stdout.endswith(expected_suffix):
        raise SelectionError("canonical manifest is absent from the exact candidate")
    metadata = entry.stdout[: -len(expected_suffix)]
    parts = metadata.split(b" ")
    if len(parts) != 3 or parts[0] != b"100644" or parts[1] != b"blob":
        raise SelectionError("canonical manifest candidate entry is not a regular file")
    try:
        blob = parts[2].decode("ascii", errors="strict")
    except UnicodeError as exc:
        raise SelectionError("canonical manifest blob identity is malformed") from exc
    if not FULL_SHA.fullmatch(blob):
        raise SelectionError("canonical manifest blob identity is malformed")
    content = _git(git_executable, root, "cat-file", "blob", blob)
    if content.returncode != 0:
        raise SelectionError("canonical manifest blob is unavailable")
    return _decode_manifest(content.stdout), blob


def _verify_exact_checkout(root: Path, head: str, git_executable: str) -> None:
    current = _git(
        git_executable,
        root,
        "rev-parse",
        "--verify",
        "HEAD^{commit}",
        text=True,
    )
    if current.returncode != 0 or current.stdout.strip() != head:
        raise SelectionError("checked-out HEAD does not match the exact candidate")
    status = _git(
        git_executable,
        root,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
    )
    if status.returncode != 0 or status.stdout:
        raise SelectionError("working tree does not exactly match the candidate tree")


def _empty_authority() -> dict[str, Any]:
    return {
        "repository_root": None,
        "repository_identity": None,
        "manifest_path": MANIFEST_RELATIVE,
        "manifest_blob": None,
        "git_executable": None,
        "git_version": None,
    }


def _route_for_path(manifest: dict[str, Any], path: str) -> dict[str, Any] | None:
    matches = [
        route
        for route in manifest["routes"]
        if path in route["exact_paths"] or any(path.startswith(prefix) for prefix in route["prefixes"])
    ]
    if len(matches) > 1:
        raise SelectionError(f"changed path has ambiguous route ownership: {path}")
    return matches[0] if matches else None


def _covered(evidence: str, selected: list[str]) -> bool:
    return any(evidence == item or evidence.startswith(item + ".") for item in selected)


def fallback_result(
    *,
    base: str | None,
    head: str | None,
    changes: list[dict[str, Any]] | None,
    reason: str,
    merge_base: str | None = None,
    head_tree: str | None = None,
) -> dict[str, Any]:
    safe_base = base if isinstance(base, str) and FULL_SHA.fullmatch(base) else None
    safe_head = head if isinstance(head, str) and FULL_SHA.fullmatch(head) else None
    changed_paths = sorted(
        {path for change in changes or [] for path in change.get("paths", [])}
    )
    return {
        "schema": RESULT_SCHEMA,
        "version": 2,
        "base": safe_base,
        "head": safe_head,
        "merge_base": merge_base,
        "head_tree": head_tree,
        "changed_paths": changed_paths,
        "changes": changes or [],
        "lane": "legacy-release",
        "tests": [],
        "matched_routes": [],
        "safety_evidence": [],
        "fail_closed": True,
        "reasons": [reason],
        **_empty_authority(),
    }


def select_changes(
    manifest: dict[str, Any],
    changes: list[dict[str, Any]],
    *,
    base: str | None = None,
    head: str | None = None,
    merge_base: str | None = None,
    head_tree: str | None = None,
) -> dict[str, Any]:
    paths = sorted({path for change in changes for path in change["paths"]})
    if not paths:
        return {
            "schema": RESULT_SCHEMA,
            "version": 2,
            "base": base,
            "head": head,
            "merge_base": merge_base,
            "head_tree": head_tree,
            "changed_paths": [],
            "changes": changes,
            "lane": "v3-full",
            "tests": list(manifest["v3_full_tests"]),
            "matched_routes": [],
            "safety_evidence": [],
            "fail_closed": False,
            "reasons": ["unchanged range selects the bounded v3 full inventory"],
            **_empty_authority(),
        }

    self_paths = set(manifest["self_protecting_paths"])
    if any(path in self_paths for path in paths):
        return fallback_result(
            base=base,
            head=head,
            changes=changes,
            merge_base=merge_base,
            head_tree=head_tree,
            reason="selector, manifest, runner, or selector-test bytes changed",
        )
    if any(
        path.startswith(prefix)
        for path in paths
        for prefix in manifest["generated_prefixes"]
    ):
        return fallback_result(
            base=base,
            head=head,
            changes=changes,
            merge_base=merge_base,
            head_tree=head_tree,
            reason="generated path has no reviewed generator-to-consumer evidence mapping",
        )

    selected_routes: list[dict[str, Any]] = []
    for path in paths:
        try:
            route = _route_for_path(manifest, path)
        except SelectionError as exc:
            return fallback_result(
                base=base,
                head=head,
                changes=changes,
                merge_base=merge_base,
                head_tree=head_tree,
                reason=str(exc),
            )
        if route is None:
            return fallback_result(
                base=base,
                head=head,
                changes=changes,
                merge_base=merge_base,
                head_tree=head_tree,
                reason=f"changed path is not mapped: {path}",
            )
        if route not in selected_routes:
            selected_routes.append(route)

    lane_index = max(LANES.index(route["lane"]) for route in selected_routes)
    lane = LANES[lane_index]
    if lane == "legacy-release":
        tests: list[str] = []
    elif lane == "v3-full":
        tests = list(manifest["v3_full_tests"])
    else:
        tests = sorted({test for route in selected_routes for test in route["tests"]})

    required_tags = sorted(
        {tag for route in selected_routes for tag in route["required_safety"]}
    )
    for tag in required_tags:
        evidence = manifest["safety_evidence"].get(tag)
        if not evidence:
            return fallback_result(
                base=base,
                head=head,
                changes=changes,
                merge_base=merge_base,
                head_tree=head_tree,
                reason=f"required safety evidence is unavailable: {tag}",
            )
        if lane != "legacy-release" and not all(_covered(item, tests) for item in evidence):
            return fallback_result(
                base=base,
                head=head,
                changes=changes,
                merge_base=merge_base,
                head_tree=head_tree,
                reason=f"selected tests do not carry required safety evidence: {tag}",
            )

    route_fail_closed = any(route["fail_closed"] for route in selected_routes)
    return {
        "schema": RESULT_SCHEMA,
        "version": 2,
        "base": base,
        "head": head,
        "merge_base": merge_base,
        "head_tree": head_tree,
        "changed_paths": paths,
        "changes": changes,
        "lane": lane,
        "tests": tests,
        "matched_routes": sorted(route["id"] for route in selected_routes),
        "safety_evidence": required_tags,
        "fail_closed": route_fail_closed,
        "reasons": [
            "reviewed route requires conservative expansion"
            if route_fail_closed
            else "all changed paths have one reviewed route"
        ],
        **_empty_authority(),
    }


def validate_result(value: Any, *, require_authority: bool = True) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != RESULT_KEYS:
        raise SelectionError("selection result must be a closed object")
    if value["schema"] != RESULT_SCHEMA or value["version"] != 2:
        raise SelectionError("unsupported selection result schema/version")

    sha_keys = ("base", "head", "merge_base", "head_tree", "manifest_blob")
    for key in sha_keys:
        item = value[key]
        if item is None:
            if require_authority:
                raise SelectionError(f"selection result {key} must bind an exact SHA")
        elif not isinstance(item, str) or not FULL_SHA.fullmatch(item):
            raise SelectionError(f"selection result {key} must be a full SHA")

    string_keys = (
        "repository_root",
        "repository_identity",
        "git_executable",
        "git_version",
    )
    for key in string_keys:
        item = value[key]
        if item is None:
            if require_authority:
                raise SelectionError(f"selection result {key} must bind exact authority")
        elif not isinstance(item, str) or not item or item != item.strip():
            raise SelectionError(f"selection result {key} is malformed")
    if value["manifest_path"] != MANIFEST_RELATIVE:
        raise SelectionError("selection result manifest_path is not canonical")
    if require_authority:
        for key in ("repository_root", "repository_identity", "git_executable"):
            item = value[key]
            assert isinstance(item, str)
            if not Path(item).is_absolute():
                raise SelectionError(f"selection result {key} must be absolute")

    for key in ("changed_paths", "matched_routes", "safety_evidence", "reasons"):
        items = _string_list(value[key], f"selection result {key}")
        if key == "changed_paths":
            for index, path in enumerate(items):
                _relative_path(path, f"selection result changed_paths[{index}]")
    if not value["reasons"]:
        raise SelectionError("selection result reasons must not be empty")
    if not isinstance(value["changes"], list) or not isinstance(value["fail_closed"], bool):
        raise SelectionError("selection result changes/fail_closed fields are invalid")
    change_paths: list[str] = []
    for change in value["changes"]:
        if not isinstance(change, dict) or set(change) != {"status", "paths"}:
            raise SelectionError("selection result change must be a closed status/path object")
        status = change["status"]
        paths = change["paths"]
        if not isinstance(status, str) or not status:
            raise SelectionError("selection result change status is invalid")
        expected = 2 if status[:1] in {"C", "R"} else 1
        if status[:1] not in {"A", "C", "D", "M", "R", "T"}:
            raise SelectionError("selection result change status is unsupported")
        if not isinstance(paths, list) or len(paths) != expected:
            raise SelectionError("selection result change paths do not match status")
        for index, path in enumerate(paths):
            if not isinstance(path, str):
                raise SelectionError("selection result change path is invalid")
            _relative_path(path, f"selection result change paths[{index}]")
        change_paths.extend(paths)
    if value["changed_paths"] != sorted(set(change_paths)):
        raise SelectionError("selection result changed_paths do not match change records")

    lane = value["lane"]
    tests = _test_names(value["tests"], "selection result tests")
    if lane not in LANES:
        raise SelectionError("selection result lane is unsupported")
    if lane == "legacy-release" and tests:
        raise SelectionError("legacy-release must use full discovery, not partial tests")
    if lane != "legacy-release" and not tests:
        raise SelectionError("non-legacy selections must contain tests")
    if value["fail_closed"] and lane != "legacy-release":
        raise SelectionError("fail-closed selection must expand to legacy-release")
    return value


def compute_selection(repository: Path, base: str, head: str) -> dict[str, Any]:
    """Reconstruct one canonical decision from an exact clean candidate checkout."""
    git_executable, git_version = resolve_git()
    requested = repository.resolve(strict=True)
    root = find_root(requested, git_executable)
    if root != requested:
        raise SelectionError("repository argument is not the canonical repository root")
    _resolve_commit(root, head, "head", git_executable)
    _verify_exact_checkout(root, head, git_executable)
    repository_identity = _repository_identity(root, git_executable)
    manifest, manifest_blob = _candidate_manifest(root, head, git_executable)
    changes, merge_base, head_tree = inspect_git_range(
        root,
        base,
        head,
        git_executable=git_executable,
    )
    result = select_changes(
        manifest,
        changes,
        base=base,
        head=head,
        merge_base=merge_base,
        head_tree=head_tree,
    )
    result.update(
        {
            "repository_root": str(root),
            "repository_identity": repository_identity,
            "manifest_path": MANIFEST_RELATIVE,
            "manifest_blob": manifest_blob,
            "git_executable": git_executable,
            "git_version": git_version,
        }
    )
    return validate_result(result)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, help="full base commit SHA")
    parser.add_argument("--head", required=True, help="full head commit SHA")
    args = parser.parse_args(argv)

    try:
        result = compute_selection(ROOT, args.base, args.head)
    except SelectionError as exc:
        result = fallback_result(
            base=args.base,
            head=args.head,
            changes=None,
            reason=str(exc),
        )
        validate_result(result, require_authority=False)
    assert set(result) == RESULT_KEYS
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
