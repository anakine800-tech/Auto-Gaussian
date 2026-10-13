from __future__ import annotations

import hashlib
import json
import re
import subprocess
import unittest
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable


TERMINAL_RELATIVE = Path(
    "tests/fixtures/rtwin_pbs/qst3_package_integration_terminal.json"
)
PREDECESSOR_COMMIT = "4d4d8be1551729e527f229b91af97b40167ea748"
PREDECESSOR_TREE = "aa6063fc4fff23d62cf81e45d7756297497e16ea"
CANDIDATE_COMMIT = "695307f0577b236f827a630bfb8058d3f089e8e1"
CANDIDATE_TREE = "6ba29c79062861978b665df357d73d6cc23e8d38"
PRODUCT_PATHS = frozenset(
    {
        "contracts/execution/execution-authorization.schema.json",
        "contracts/execution/execution-request.schema.json",
        "contracts/execution/protected-submit-bundle.schema.json",
        "scripts/execution_authorization.py",
        "scripts/protected_submit_contract.py",
        "skills/auto-g16-rtwin-pbs/SKILL.md",
        "skills/auto-g16-rtwin-pbs/references/input-approval-receipt.md",
        "skills/auto-g16-rtwin-pbs/references/live-approval-record.md",
        "skills/auto-g16-rtwin-pbs/scripts/legacy_rtwin_pbs.py",
    }
)
VERIFIER_PATHS = frozenset(
    {
        "tests/test_direct_onboarding.py",
        "tests/test_execution_batch_reservation_capability.py",
        "tests/test_legacy_effect_owner.py",
        "tests/test_local_state_binding.py",
        "tests/test_protected_legacy_effect_handoff.py",
        "tests/test_protected_lifecycle_contract.py",
        "tests/test_protected_local_materialization.py",
        "tests/test_protected_owner_consumer_contract.py",
        "tests/test_protected_production_ingress_contract.py",
        "tests/test_protected_runtime_state_contract.py",
        "tests/test_protected_submit_contract.py",
        "tests/test_resource_effect_time_replay_owner.py",
    }
)
SUPPORTING_TEST_PATHS = frozenset({"tests/test_legacy_v254_golden.py"})
HISTORICAL_PATH = (
    "tests/fixtures/rtwin_pbs/protected_qst3_production_successor.json"
)
_SHA1 = re.compile(r"[0-9a-f]{40}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SCOPE = {
    "historical_fixtures_unchanged": True,
    "production_semantics_unchanged": True,
    "scientific_semantics_unchanged": True,
    "live_semantics_unchanged": True,
    "package_behavior_unchanged": True,
    "self_sha_bound": False,
    "mutable_verifier_sha_bound": False,
    "test_only_lineage_infrastructure": True,
}


class LineageError(RuntimeError):
    pass


def _no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise LineageError(f"duplicate terminal key: {key}")
        result[key] = value
    return result


def _strict_json(path: Path) -> dict:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_no_duplicates,
            parse_constant=lambda value: (_ for _ in ()).throw(
                LineageError(f"non-finite terminal value: {value}")
            ),
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LineageError(f"invalid terminal JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise LineageError("terminal must be an object")
    return value


def _git(root: Path, *args: str, binary: bool = False):
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=root,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=not binary,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise LineageError(f"immutable Git object check failed: {' '.join(args)}") from exc
    return result.stdout


def _safe_relative(relative: str) -> None:
    value = PurePosixPath(relative)
    if value.is_absolute() or ".." in value.parts or str(value) != relative:
        raise LineageError(f"unsafe terminal path: {relative}")


def _object_at(root: Path, commit: str, relative: str) -> tuple[str, str, str]:
    line = _git(root, "ls-tree", commit, "--", relative).strip()
    try:
        metadata, listed = line.split("\t", 1)
        mode, kind, oid = metadata.split()
    except ValueError as exc:
        raise LineageError(f"missing immutable Git blob: {commit}:{relative}") from exc
    if listed != relative or kind != "blob" or not _SHA1.fullmatch(oid):
        raise LineageError(f"invalid immutable Git blob: {commit}:{relative}")
    payload = _git(root, "cat-file", "blob", oid, binary=True)
    return mode, oid, hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class TerminalOwner:
    root: Path
    records: dict[str, tuple[str, ...]]

    def integrate(self, relative: str, predecessor_sha256: str) -> str:
        """Map only the exact reviewed main blob to the payload blob."""
        if relative not in self.records:
            return predecessor_sha256
        record = self.records[relative]
        if predecessor_sha256 != record[2]:
            raise LineageError(
                f"lineage predecessor mismatch for {relative}: {predecessor_sha256}"
            )
        return record[5]

    def candidate_from_git_predecessor(self, relative: str) -> str:
        if relative not in self.records:
            raise LineageError(f"terminal does not own path: {relative}")
        return self.integrate(relative, self.records[relative][2])

    def assert_candidate(self, testcase: unittest.TestCase, relative: str) -> None:
        expected = self.candidate_from_git_predecessor(relative)
        if relative in VERIFIER_PATHS | SUPPORTING_TEST_PATHS:
            testcase.assertEqual(expected, self.records[relative][5])
            return
        testcase.assertEqual(
            hashlib.sha256((self.root / relative).read_bytes()).hexdigest(),
            expected,
        )


def load(root: Path) -> TerminalOwner:
    root = root.resolve()
    if not (root / ".git").exists():
        raise unittest.SkipTest("QST3 integration lineage requires immutable Git objects")
    document = _strict_json(root / TERMINAL_RELATIVE)
    if set(document) != {
        "schema",
        "predecessor",
        "candidate",
        "scope",
        "product_package_objects",
        "immutable_verifier_objects",
        "immutable_supporting_test_objects",
        "historical_evidence_objects",
    }:
        raise LineageError("terminal top-level keys mismatch")
    if document["schema"] != "auto-g16-qst3-package-integration-terminal/1":
        raise LineageError("terminal schema mismatch")
    if document["predecessor"] != {
        "commit": PREDECESSOR_COMMIT,
        "tree": PREDECESSOR_TREE,
    }:
        raise LineageError("terminal predecessor mismatch")
    if document["candidate"] != {
        "commit": CANDIDATE_COMMIT,
        "tree": CANDIDATE_TREE,
        "parent": PREDECESSOR_COMMIT,
    }:
        raise LineageError("terminal candidate mismatch")
    if document["scope"] != _SCOPE:
        raise LineageError("terminal scope mismatch")
    if set(document["product_package_objects"]) != PRODUCT_PATHS:
        raise LineageError("terminal product/package path set mismatch")
    if set(document["immutable_verifier_objects"]) != VERIFIER_PATHS:
        raise LineageError("terminal verifier path set mismatch")
    if set(document["immutable_supporting_test_objects"]) != SUPPORTING_TEST_PATHS:
        raise LineageError("terminal supporting test path set mismatch")
    if set(document["historical_evidence_objects"]) != {HISTORICAL_PATH}:
        raise LineageError("terminal historical evidence path set mismatch")

    for commit, tree in (
        (PREDECESSOR_COMMIT, PREDECESSOR_TREE),
        (CANDIDATE_COMMIT, CANDIDATE_TREE),
    ):
        _git(root, "cat-file", "-e", f"{commit}^{{commit}}")
        actual_tree = _git(root, "rev-parse", f"{commit}^{{tree}}").strip()
        if actual_tree != tree:
            raise LineageError(f"immutable commit tree mismatch: {commit}")
    if _git(root, "rev-parse", f"{CANDIDATE_COMMIT}^1").strip() != PREDECESSOR_COMMIT:
        raise LineageError("candidate parent mismatch")

    records: dict[str, tuple[str, ...]] = {}
    for group in (
        "product_package_objects",
        "immutable_verifier_objects",
        "immutable_supporting_test_objects",
    ):
        for relative, raw in document[group].items():
            _safe_relative(relative)
            if relative == TERMINAL_RELATIVE.as_posix():
                raise LineageError("terminal must not bind itself")
            if not isinstance(raw, list) or len(raw) != 6:
                raise LineageError(f"invalid object record: {relative}")
            record = tuple(raw)
            if record[0] != "100644" or record[3] != "100644":
                raise LineageError(f"invalid object mode: {relative}")
            if not _SHA1.fullmatch(record[1]) or not _SHA1.fullmatch(record[4]):
                raise LineageError(f"invalid object OID: {relative}")
            if not _SHA256.fullmatch(record[2]) or not _SHA256.fullmatch(record[5]):
                raise LineageError(f"invalid object SHA-256: {relative}")
            if _object_at(root, PREDECESSOR_COMMIT, relative) != record[:3]:
                raise LineageError(f"predecessor Git object mismatch: {relative}")
            if _object_at(root, CANDIDATE_COMMIT, relative) != record[3:]:
                raise LineageError(f"candidate Git object mismatch: {relative}")
            records[relative] = record

    historical = document["historical_evidence_objects"][HISTORICAL_PATH]
    if not isinstance(historical, list) or len(historical) != 3:
        raise LineageError("invalid historical evidence record")
    _safe_relative(HISTORICAL_PATH)
    if _object_at(root, CANDIDATE_COMMIT, HISTORICAL_PATH) != tuple(historical):
        raise LineageError("historical QST3 successor Git object mismatch")
    return TerminalOwner(root=root, records=records)


def dependency_edges() -> frozenset[tuple[str, str]]:
    return frozenset(
        {(relative, "shared-lineage-owner") for relative in VERIFIER_PATHS}
        | {
            ("shared-lineage-owner", TERMINAL_RELATIVE.as_posix()),
            (TERMINAL_RELATIVE.as_posix(), f"git:{PREDECESSOR_COMMIT}"),
            (TERMINAL_RELATIVE.as_posix(), f"git:{CANDIDATE_COMMIT}"),
        }
    )


def active_mutable_current_cycles(edges: Iterable[tuple[str, str]]) -> tuple[tuple[str, ...], ...]:
    graph: dict[str, set[str]] = {}
    for left, right in edges:
        graph.setdefault(left, set()).add(right)
        graph.setdefault(right, set())
    index = 0
    stack: list[str] = []
    active: set[str] = set()
    indices: dict[str, int] = {}
    low: dict[str, int] = {}
    cycles: list[tuple[str, ...]] = []

    def visit(node: str) -> None:
        nonlocal index
        indices[node] = low[node] = index
        index += 1
        stack.append(node)
        active.add(node)
        for target in graph[node]:
            if target not in indices:
                visit(target)
                low[node] = min(low[node], low[target])
            elif target in active:
                low[node] = min(low[node], indices[target])
        if low[node] == indices[node]:
            component = []
            while True:
                target = stack.pop()
                active.remove(target)
                component.append(target)
                if target == node:
                    break
            if len(component) > 1 and any(value in VERIFIER_PATHS for value in component):
                cycles.append(tuple(sorted(component)))

    for node in graph:
        if node not in indices:
            visit(node)
    return tuple(sorted(cycles))


def validate_dependency_graph(edges: Iterable[tuple[str, str]]) -> None:
    cycles = active_mutable_current_cycles(edges)
    if cycles:
        raise LineageError(f"active mutable current cycle: {cycles}")
