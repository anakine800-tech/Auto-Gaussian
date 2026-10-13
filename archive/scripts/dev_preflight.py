#!/usr/bin/env python3
"""Read-only, offline preflight for an isolated Auto-G16 development task."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


SCHEMA = "auto-g16-dev-preflight-result/1"
REQUIRED_PATHS = (
    "AGENTS.md",
    "README.md",
    "docs/development-handbook.md",
    "pyproject.toml",
    "config/python-environments.json",
    "config/required-checks.json",
    "config/static-quality.json",
    ".github/workflows/offline-tests.yml",
    "scripts/python",
    "scripts/run_tests.py",
)
PRIVATE_PARTS = {
    "confidential",
    "outputs",
    "private-studies",
    "scratch",
    "secrets",
    "studies-private",
    "unpublished",
}
PRIVATE_NAMES = {
    ".env",
    "gaussian_server.json",
    "id_ed25519",
    "id_rsa",
    "known_hosts",
    "rtwin_gaussian_server_ssh_config",
    "runtime.json",
    "ssh_config",
}
PRIVATE_SUFFIXES = {".chk", ".fchk", ".key", ".pem", ".rwf"}
LIVE_ENV = re.compile(r"^AUTO_G16_.*(?:LIVE|DEPLOY|SUBMIT|QSUB|QDEL)")
TEST_MODIFIER_ENV = {"AUTO_G16_REQUIRE_RDKIT", "AUTO_G16_SKIP_PRESSURE_TESTS"}


class PreflightError(RuntimeError):
    """The repository could not be inspected safely."""


def _git(start: Path, *args: str, text: bool = True) -> subprocess.CompletedProcess[Any]:
    return subprocess.run(
        ["git", "-C", str(start), *args],
        check=False,
        capture_output=True,
        text=text,
    )


def find_git_root(start: Path) -> Path:
    """Resolve the containing Git worktree without changing it."""
    result = _git(start, "rev-parse", "--show-toplevel")
    if result.returncode != 0:
        raise PreflightError("the requested path is not inside a Git worktree")
    return Path(result.stdout.strip()).resolve()


def _check(check_id: str, status: str, summary: str, **details: Any) -> dict[str, Any]:
    item: dict[str, Any] = {"id": check_id, "status": status, "summary": summary}
    if details:
        item["details"] = details
    return item


def _status_entries(root: Path) -> list[tuple[str, tuple[str, ...]]]:
    result = _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all", text=False)
    if result.returncode != 0:
        raise PreflightError("git status failed")
    fields = result.stdout.split(b"\0")
    entries: list[tuple[str, tuple[str, ...]]] = []
    index = 0
    while index < len(fields) and fields[index]:
        field = fields[index]
        if len(field) < 4:
            raise PreflightError("git status returned an unsupported record")
        status = field[:2].decode("ascii", errors="strict")
        path = field[3:].decode("utf-8", errors="strict")
        index += 1
        paths = [path]
        if "R" in status or "C" in status:
            if index >= len(fields) or not fields[index]:
                raise PreflightError("git status returned an incomplete rename record")
            paths.append(fields[index].decode("utf-8", errors="strict"))
            index += 1
        entries.append((status, tuple(paths)))
    return entries


def _is_private_risk(raw: str) -> bool:
    path = Path(raw)
    parts = {part.lower() for part in path.parts}
    name = path.name.lower()
    return bool(
        parts.intersection(PRIVATE_PARTS)
        or name in PRIVATE_NAMES
        or name.startswith(".env.")
        or path.suffix.lower() in PRIVATE_SUFFIXES
    )


def inspect(
    root: Path,
    environment: dict[str, str] | None = None,
    *,
    require_clean: bool = False,
) -> dict[str, Any]:
    """Return sanitized preflight findings; file contents and env values are never read."""
    checks: list[dict[str, Any]] = []
    branch_result = _git(root, "symbolic-ref", "--quiet", "--short", "HEAD")
    if branch_result.returncode != 0:
        checks.append(_check("branch", "blocker", "detached HEAD cannot own feature work"))
        branch = None
    else:
        branch = branch_result.stdout.strip()
        if branch in {"main", "master"}:
            checks.append(_check("branch", "blocker", "feature development on the stable branch is forbidden", branch=branch))
        elif not branch.startswith("codex/"):
            checks.append(_check("branch", "blocker", "feature branch must use the repository codex/ prefix", branch=branch))
        else:
            checks.append(_check("branch", "pass", "isolated feature branch naming is compatible", branch=branch))

    git_dir = _git(root, "rev-parse", "--absolute-git-dir")
    common_dir = _git(root, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if git_dir.returncode or common_dir.returncode:
        raise PreflightError("Git worktree metadata could not be resolved")
    linked = Path(git_dir.stdout.strip()).resolve() != Path(common_dir.stdout.strip()).resolve()
    checks.append(
        _check(
            "worktree",
            "pass" if linked else "warning",
            "linked worktree isolation detected" if linked else "primary checkout detected; confirm this task is independently isolated",
            linked_worktree=linked,
        )
    )

    entries = _status_entries(root)
    staged = sum(status[0] not in {" ", "?"} for status, _paths in entries)
    unstaged = sum(status[1] not in {" ", "?"} for status, _paths in entries)
    untracked = sum(status == "??" for status, _paths in entries)
    if entries:
        checks.append(
            _check(
                "working_tree",
                "blocker" if require_clean else "warning",
                (
                    "working tree must be clean for this handoff"
                    if require_clean
                    else "working tree is dirty; classify and carry only changes owned by this task"
                ),
                staged=staged,
                unstaged=unstaged,
                untracked=untracked,
                total=len(entries),
            )
        )
    else:
        checks.append(_check("working_tree", "pass", "working tree is clean", staged=0, unstaged=0, untracked=0, total=0))

    risk_count = sum(any(_is_private_risk(path) for path in paths) for _status, paths in entries)
    tracked = _git(root, "ls-files", "-z", text=False)
    if tracked.returncode != 0:
        raise PreflightError("tracked-file inventory failed")
    tracked_risks = sum(
        _is_private_risk(item.decode("utf-8", errors="strict"))
        for item in tracked.stdout.split(b"\0")
        if item
    )
    if risk_count or tracked_risks:
        checks.append(
            _check(
                "private_paths",
                "blocker",
                "private, credential-like, or Gaussian runtime path risk detected; names are withheld",
                dirty_risk_count=risk_count,
                tracked_risk_count=tracked_risks,
            )
        )
    else:
        checks.append(_check("private_paths", "pass", "no private-path class was found in tracked or dirty path metadata"))

    missing = [
        relative
        for relative in REQUIRED_PATHS
        if (root / relative).is_symlink() or not (root / relative).is_file()
    ]
    checks.append(
        _check(
            "required_files",
            "blocker" if missing else "pass",
            "required repository files are missing" if missing else "required development and test configuration is present",
            missing=missing,
        )
    )

    selected_environment = os.environ if environment is None else environment
    live_names = sorted(name for name in selected_environment if LIVE_ENV.match(name))
    checks.append(
        _check(
            "live_opt_in",
            "blocker" if live_names else "pass",
            "live/deploy/submit-like environment flags are set; values were not read" if live_names else "no live/deploy/submit-like Auto-G16 environment flag is set",
            variable_names=live_names,
        )
    )
    modifiers = sorted(name for name in TEST_MODIFIER_ENV if name in selected_environment)
    checks.append(
        _check(
            "test_isolation",
            "warning" if modifiers else "pass",
            "test coverage modifier is set; record it with validation evidence" if modifiers else "no known test coverage modifier is set",
            variable_names=modifiers,
        )
    )

    blockers = sum(item["status"] == "blocker" for item in checks)
    warnings = sum(item["status"] == "warning" for item in checks)
    return {
        "schema": SCHEMA,
        "status": "blocked" if blockers else ("pass_with_warnings" if warnings else "pass"),
        "repository_root": str(root),
        "branch": branch,
        "summary": {"blockers": blockers, "warnings": warnings, "checks": len(checks)},
        "checks": checks,
        "limitations": [
            "This is a local read-only preflight; it does not verify GitHub, CI success, branch protection, deployment, or live authority.",
            "Dirty-path classification uses Git metadata only and never reads candidate secret contents.",
        ],
    }


def _print_text(report: dict[str, Any]) -> None:
    print(f"Auto-G16 development preflight: {report['status']}")
    print(f"branch: {report['branch'] or '(detached)'}")
    for item in report["checks"]:
        print(f"[{item['status'].upper()}] {item['id']}: {item['summary']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="path inside the target worktree")
    parser.add_argument("--json", action="store_true", help="emit one machine-readable JSON document")
    parser.add_argument(
        "--require-clean",
        action="store_true",
        help="treat any staged, unstaged, or untracked entry as a policy blocker",
    )
    args = parser.parse_args(argv)
    try:
        report = inspect(find_git_root(args.repo), require_clean=args.require_clean)
    except (OSError, UnicodeError, PreflightError) as exc:
        error = {"schema": SCHEMA, "status": "error", "error": str(exc)}
        if args.json:
            print(json.dumps(error, ensure_ascii=False, sort_keys=True))
        else:
            print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    else:
        _print_text(report)
    return 1 if report["summary"]["blockers"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
