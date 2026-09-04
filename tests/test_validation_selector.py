#!/usr/bin/env python3
"""Focused offline tests for fail-closed changed-path validation selection."""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

from tests.v3 import execution as EXECUTION_PACKAGE
from tests.v3 import result as RESULT_PACKAGE


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "select_validation.py"
MANIFEST = ROOT / "config" / "validation-selection.json"
WORKFLOW = ROOT / ".github" / "workflows" / "offline-tests.yml"
SPEC = importlib.util.spec_from_file_location("validation_selector", SCRIPT)
assert SPEC and SPEC.loader
SELECTOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SELECTOR)


EXEC_SAFETY = [
    "approval-owner-separation",
    "at-most-one-submission",
    "no-overwrite",
    "reconciliation",
    "still-applicable-descriptor-capability",
    "timeout-slow-running-is-not-failure",
    "unknown-no-automatic-retry",
]
EXEC_TESTS = [
    "tests.test_direct_one_hop_transport",
    "tests.test_direct_qstat_acquisition",
    "tests.test_execution_authorization",
    "tests.test_legacy_descriptor_mutation_capability",
    "tests.test_legacy_root_authority_contract",
    "tests.test_live_approval_effect_time_replay",
    "tests.test_resource_monitor_efficiency",
    "tests.v3.core.test_store",
    "tests.v3.execution",
]
TRANSPORT_SAFETY = [
    "approval-owner-separation",
    "at-most-one-submission",
    "no-overwrite",
    "reconciliation",
    "still-applicable-descriptor-capability",
    "timeout-slow-running-is-not-failure",
    "unknown-no-automatic-retry",
]
# Transport owns both the ExecutionPort mechanics and the scheduler/fetch
# read-side boundary. The selected set therefore closes the existing Execution
# safety evidence and adds only the owned Transport tests plus the public
# Observe consumer needed for scheduler projection.
TRANSPORT_TESTS = [
    "tests.test_direct_one_hop_transport",
    "tests.test_direct_qstat_acquisition",
    "tests.test_execution_authorization",
    "tests.test_legacy_descriptor_mutation_capability",
    "tests.test_legacy_root_authority_contract",
    "tests.test_live_approval_effect_time_replay",
    "tests.test_resource_monitor_efficiency",
    "tests.v3.core.test_store",
    "tests.v3.execution",
    "tests.v3.observe",
    "tests.v3.transport",
]
APPROVAL_SAFETY = [
    "approval-owner-separation",
    "at-most-one-submission",
    "reconciliation",
    "unknown-no-automatic-retry",
]
APPROVAL_TESTS = [
    "tests.test_execution_authorization",
    "tests.test_live_approval_effect_time_replay",
    "tests.v3.approval",
    "tests.v3.core.test_store",
    "tests.v3.execution",
]
RESULT_SAFETY = ["no-overwrite", "unknown-no-automatic-retry"]
RESULT_TESTS = ["tests.v3.core.test_store", "tests.v3.result"]
SCIENTIFIC_VALIDATION_SAFETY = ["no-overwrite", "unknown-no-automatic-retry"]
SCIENTIFIC_VALIDATION_TESTS = [
    "tests.v3.core.test_store",
    "tests.v3.result",
    "tests.v3.scientific_validation",
]
WORKFLOW_SAFETY = ["approval-owner-separation", "unknown-no-automatic-retry"]
# Workflow owns its future package tests; Core store anchors exact record/replay and
# UNKNOWN invariants; Approval anchors HumanGate non-authority. The two legacy
# modules are the existing carriers required by approval-owner-separation.
WORKFLOW_TESTS = [
    "tests.test_execution_authorization",
    "tests.test_live_approval_effect_time_replay",
    "tests.v3.approval",
    "tests.v3.core.test_store",
    "tests.v3.workflow",
]
OBSERVE_SAFETY = [
    "no-overwrite",
    "timeout-slow-running-is-not-failure",
    "unknown-no-automatic-retry",
]
# Observe owns typed read-only projections over Core Observation history. Core
# anchors exact Attempt binding, append-only replay, and UNKNOWN/no-retry; the
# two acquisition tests are the existing slow/running-is-not-failure carriers.
# The whole Execution package is intentionally excluded because the frozen
# Observe contract imports Core only and owns no effect behavior.
OBSERVE_TESTS = [
    "tests.test_direct_qstat_acquisition",
    "tests.test_resource_monitor_efficiency",
    "tests.v3.core.test_store",
    "tests.v3.observe",
]
REVIEW_SAFETY = ["no-overwrite", "unknown-no-automatic-retry"]
# Review is a pure projection over public Core, Result, and
# ScientificValidation authority. ExecutionSnapshot identity reaches it through
# exact Result provenance, so the baseline route intentionally does not import
# or select the Execution package.
REVIEW_TESTS = [
    "tests.v3.core.test_store",
    "tests.v3.result",
    "tests.v3.review",
    "tests.v3.scientific_validation",
]
CONFORMER_TESTS = ["tests.test_conformer_search", "tests.v31.conformer"]
# Thermochemistry consumes the future ConformerEnsemble handoff and the existing
# deterministic Gaussian thermochemistry lineage. It does not select the legacy
# conformer Skill as an ownership path; that whole skills/ surface stays legacy.
THERMOCHEMISTRY_TESTS = [
    "tests.test_scientific_closure_lineage",
    "tests.v31.conformer",
    "tests.v31.thermochemistry",
]
V31_OFFLINE_E2E_TESTS = [
    "tests.test_scientific_closure_lineage",
    "tests.v3.core.test_store",
    "tests.v3.execution.test_v31_lane_a",
    "tests.v31.conformer",
    "tests.v31.integration",
    "tests.v31.thermochemistry",
    "tests.v31.transport.test_program_composition",
]


def change(status: str, *paths: str) -> dict[str, object]:
    return {"status": status, "paths": list(paths)}


def suite_ids(suite: unittest.TestSuite) -> list[str]:
    identifiers: list[str] = []
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            identifiers.extend(suite_ids(item))
        else:
            identifiers.append(item.id())
    return identifiers


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(root), *args],
        text=True,
    ).strip()


def initialize_repository(root: Path, files: dict[str, str]) -> str:
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "Selector Test"], check=True)
    subprocess.run(
        ["git", "-C", str(root), "config", "user.email", "selector@example.invalid"],
        check=True,
    )
    content = {SELECTOR.MANIFEST_RELATIVE: MANIFEST.read_text(encoding="utf-8"), **files}
    for relative, value in content.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "--", *content], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "base"], check=True)
    return git(root, "rev-parse", "HEAD")


def commit_change(root: Path, path: str, content: str, message: str = "candidate") -> str:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "--", path], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", message], check=True)
    return git(root, "rev-parse", "HEAD")


def commit_files(root: Path, files: dict[str, str], message: str = "candidate") -> str:
    for relative, content in files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "--", *files], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", message], check=True)
    return git(root, "rev-parse", "HEAD")


def raw_copy_diff(root: Path, base: str, head: str) -> list[dict[str, object]]:
    raw = subprocess.check_output(
        [
            "git",
            "-C",
            str(root),
            "diff",
            "--name-status",
            "-z",
            "--find-renames=50%",
            "--find-copies=50%",
            "--find-copies-harder",
            base,
            head,
            "--",
        ]
    )
    return SELECTOR.parse_name_status(raw)


def workflow_route_scripts() -> list[str]:
    text = WORKFLOW.read_text(encoding="utf-8")
    marker = "      - name: Resolve exact validation route\n"
    sections = text.split(marker)
    if len(sections) != 3:
        raise AssertionError("workflow must contain exactly two validation route steps")
    scripts: list[str] = []
    for section in sections[1:]:
        step = section.split("\n      - name:", 1)[0]
        run_marker = "        run: |\n"
        if step.count(run_marker) != 1:
            raise AssertionError("validation route step must contain one literal run block")
        scripts.append(textwrap.dedent(step.split(run_marker, 1)[1]))
    return scripts


def initialize_workflow_repository(root: Path) -> str:
    return initialize_repository(
        root,
        {
            ".gitignore": (ROOT / ".gitignore").read_text(encoding="utf-8"),
            ".github/workflows/offline-tests.yml": WORKFLOW.read_text(encoding="utf-8"),
            "scripts/select_validation.py": SCRIPT.read_text(encoding="utf-8"),
            "AGENTS.md": "baseline repository authority\n",
            "README.md": "baseline readme\n",
            "auto_g16/core/models.py": "baseline models\n",
            "auto_g16/core/store.py": "baseline store\n",
            "tests/v3/core/test_store.py": "baseline store tests\n",
            "docs/v3/STATUS.md": "baseline closeout\n",
        },
    )


def run_workflow_route(
    script: str,
    root: Path,
    runner: Path,
    *,
    event_name: str,
    base: str = "",
    head: str = "",
    ref: str = "refs/heads/main",
    created: str = "false",
    deleted: str = "false",
    forced: str = "false",
) -> tuple[subprocess.CompletedProcess[str], dict[str, str]]:
    output = runner / "github-output.txt"
    output.write_text("", encoding="utf-8")
    environment = os.environ.copy()
    environment.update(
        {
            "EVENT_NAME": event_name,
            "PR_BASE_SHA": base if event_name == "pull_request" else "",
            "PR_HEAD_SHA": head if event_name == "pull_request" else "",
            "PUSH_BASE_SHA": base if event_name == "push" else "",
            "PUSH_HEAD_SHA": head if event_name == "push" else "",
            "PUSH_REF": ref if event_name == "push" else "",
            "PUSH_CREATED": created if event_name == "push" else "",
            "PUSH_DELETED": deleted if event_name == "push" else "",
            "PUSH_FORCED": forced if event_name == "push" else "",
            "RUNNER_TEMP": str(runner),
            "GITHUB_OUTPUT": str(output),
        }
    )
    result = subprocess.run(
        ["bash", "-c", script],
        cwd=root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    metadata: dict[str, str] = {}
    for line in output.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if separator:
            metadata[key] = value
    return result, metadata


class ValidationSelectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = SELECTOR._load_manifest_for_test(MANIFEST)

    def select(self, *changes: dict[str, object]) -> dict[str, object]:
        return SELECTOR.select_changes(self.manifest, list(changes))

    def test_workflow_uses_identical_canonical_route_steps_without_yaml_path_routing(self) -> None:
        scripts = workflow_route_scripts()
        self.assertEqual(scripts[0], scripts[1])
        self.assertEqual(scripts[0].count("python scripts/select_validation.py"), 1)
        self.assertNotIn("changed_paths", scripts[0])
        self.assertNotIn("README.md", scripts[0])
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertEqual(workflow.count("python scripts/select_validation.py"), 2)
        self.assertIn("if: steps.validation-route.outputs.authoritative == 'true'", workflow)
        self.assertIn("if: steps.validation-route.outputs.authoritative != 'true'", workflow)
        self.assertNotIn("if: github.event_name == 'pull_request' &&", workflow)
        self.assertIn('--selection "${{ steps.validation-route.outputs.selection }}"', workflow)

    def test_main_push_route_matrix_executes_real_canonical_selection(self) -> None:
        script = workflow_route_scripts()[0]
        cases = (
            ("AGENTS.md", "v3 authority routing\n", "v3-full", False),
            ("README.md", "focused readme\n", "focused", False),
            ("auto_g16/core/store.py", "affected store\n", "affected", False),
            ("auto_g16/approval/service.py", "approval owner\n", "affected", False),
            ("auto_g16/execution/service.py", "execution owner\n", "affected", False),
            ("auto_g16/transport/rtwin.py", "transport owner\n", "affected", False),
            ("auto_g16/result/parser.py", "result owner\n", "affected", False),
            (
                "auto_g16/scientific_validation/service.py",
                "scientific validation owner\n",
                "affected",
                False,
            ),
            ("auto_g16/observe/service.py", "observe owner\n", "affected", False),
            ("tests/v3/core/test_store.py", "core safety\n", "v3-full", False),
            ("docs/v3/STATUS.md", "closeout after\n", "v3-full", False),
            ("config/context-map.toml", "status = 'contract-frozen'\n", "v3-full", False),
            (
                ".github/workflows/offline-tests.yml",
                WORKFLOW.read_text(encoding="utf-8") + "\n# control-plane candidate\n",
                "legacy-release",
                True,
            ),
            ("unmapped/new_surface.py", "unknown\n", "legacy-release", True),
        )
        for path, content, lane, fail_closed in cases:
            with self.subTest(path=path), tempfile.TemporaryDirectory() as temporary, tempfile.TemporaryDirectory() as runner_temp:
                root = Path(temporary)
                base = initialize_workflow_repository(root)
                head = commit_change(root, path, content)
                result, metadata = run_workflow_route(
                    script,
                    root,
                    Path(runner_temp),
                    event_name="push",
                    base=base,
                    head=head,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(metadata["lane"], lane)
                self.assertEqual(metadata["authoritative"], "true")
                self.assertEqual(metadata.get("base"), base)
                self.assertEqual(metadata.get("head"), head)
                selection_path = Path(metadata["selection"])
                self.assertTrue(selection_path.is_file())
                selection = json.loads(selection_path.read_text(encoding="utf-8"))
                self.assertEqual(selection["lane"], lane)
                self.assertEqual(selection["fail_closed"], fail_closed)
                if not fail_closed:
                    self.assertTrue(selection["tests"])

    def test_main_push_identity_and_history_ambiguity_fall_back_to_full(self) -> None:
        script = workflow_route_scripts()[0]
        with tempfile.TemporaryDirectory() as temporary, tempfile.TemporaryDirectory() as runner_temp:
            root = Path(temporary)
            runner = Path(runner_temp)
            base = initialize_workflow_repository(root)
            head = commit_change(root, "README.md", "candidate readme\n")
            cases = (
                ("missing before", {"base": ""}),
                ("zero before", {"base": "0" * 40}),
                ("invalid before", {"base": "short"}),
                ("unresolved before", {"base": "f" * 40}),
                ("zero head", {"head": "0" * 40}),
                ("invalid head", {"head": "short"}),
                ("unresolved head", {"head": "e" * 40}),
                ("branch creation", {"created": "true"}),
                ("branch deletion", {"deleted": "true"}),
                ("force push payload", {"forced": "true"}),
                ("wrong ref", {"ref": "refs/heads/not-main"}),
            )
            for label, overrides in cases:
                with self.subTest(label=label):
                    arguments = {"base": base, "head": head, **overrides}
                    result, metadata = run_workflow_route(
                        script,
                        root,
                        runner,
                        event_name="push",
                        **arguments,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(metadata, {"lane": "legacy-release", "authoritative": "false"})

            git(root, "checkout", "-q", "--detach", base)
            other_base = commit_change(root, "README.md", "divergent base\n", "divergent")
            git(root, "checkout", "-q", "--detach", head)
            result, metadata = run_workflow_route(
                script,
                root,
                runner,
                event_name="push",
                base=other_base,
                head=head,
                forced="false",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(metadata, {"lane": "legacy-release", "authoritative": "false"})

            newer = commit_change(root, "README.md", "checkout mismatch\n", "newer")
            self.assertNotEqual(newer, head)
            result, metadata = run_workflow_route(
                script,
                root,
                runner,
                event_name="push",
                base=base,
                head=head,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(metadata, {"lane": "legacy-release", "authoritative": "false"})

    def test_pull_request_requires_authority_but_accepts_canonical_fail_closed(self) -> None:
        script = workflow_route_scripts()[0]
        with tempfile.TemporaryDirectory() as temporary, tempfile.TemporaryDirectory() as runner_temp:
            root = Path(temporary)
            runner = Path(runner_temp)
            base = initialize_workflow_repository(root)
            head = commit_change(root, "README.md", "candidate readme\n")

            result, metadata = run_workflow_route(
                script,
                root,
                runner,
                event_name="pull_request",
                base=base,
                head=head,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(metadata["lane"], "focused")
            self.assertEqual(metadata["authoritative"], "true")

            result, metadata = run_workflow_route(
                script,
                root,
                runner,
                event_name="pull_request",
                base="",
                head=head,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(metadata, {"lane": "legacy-release", "authoritative": "false"})

            newer = commit_change(root, "README.md", "checkout mismatch\n", "newer")
            self.assertNotEqual(newer, head)
            result, metadata = run_workflow_route(
                script,
                root,
                runner,
                event_name="pull_request",
                base=base,
                head=head,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(metadata, {"lane": "legacy-release", "authoritative": "false"})
            git(root, "checkout", "-q", "--detach", head)

            selector_path = root / "scripts" / "select_validation.py"
            original = selector_path.read_text(encoding="utf-8")
            for label, replacement in (
                ("selector process error", "raise SystemExit(2)\n"),
                ("malformed selector result", "print('{}')\n"),
            ):
                with self.subTest(label=label):
                    selector_path.write_text(replacement, encoding="utf-8")
                    result, metadata = run_workflow_route(
                        script,
                        root,
                        runner,
                        event_name="pull_request",
                        base=base,
                        head=head,
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(metadata, {"lane": "legacy-release", "authoritative": "false"})
            selector_path.write_text(original, encoding="utf-8")

            fail_closed_base = git(root, "rev-parse", "HEAD")
            fail_closed_head = commit_change(
                root,
                ".github/workflows/offline-tests.yml",
                WORKFLOW.read_text(encoding="utf-8") + "\n# control-plane candidate\n",
            )
            result, metadata = run_workflow_route(
                script,
                root,
                runner,
                event_name="pull_request",
                base=fail_closed_base,
                head=fail_closed_head,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(metadata["lane"], "legacy-release")
            self.assertEqual(metadata["authoritative"], "true")
            selection = json.loads(Path(metadata["selection"]).read_text(encoding="utf-8"))
            self.assertTrue(selection["fail_closed"])

    def test_selection_or_artifact_closure_failure_falls_back_to_full(self) -> None:
        script = workflow_route_scripts()[0]
        with tempfile.TemporaryDirectory() as temporary, tempfile.TemporaryDirectory() as runner_temp:
            root = Path(temporary)
            base = initialize_workflow_repository(root)
            head = commit_change(root, "README.md", "candidate readme\n")
            selector_path = root / "scripts" / "select_validation.py"
            original = selector_path.read_text(encoding="utf-8")
            for label, replacement in (
                ("selection command failure", "raise SystemExit(2)\n"),
                ("invalid selection artifact", "print('{}')\n"),
            ):
                with self.subTest(label=label):
                    selector_path.write_text(replacement, encoding="utf-8")
                    result, metadata = run_workflow_route(
                        script,
                        root,
                        Path(runner_temp),
                        event_name="push",
                        base=base,
                        head=head,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(metadata, {"lane": "legacy-release", "authoritative": "false"})
            selector_path.write_text(original, encoding="utf-8")

    def test_manual_and_release_like_events_retain_full_attestation(self) -> None:
        script = workflow_route_scripts()[0]
        with tempfile.TemporaryDirectory() as temporary, tempfile.TemporaryDirectory() as runner_temp:
            root = Path(temporary)
            initialize_workflow_repository(root)
            for event_name in ("workflow_dispatch", "release"):
                with self.subTest(event_name=event_name):
                    result, metadata = run_workflow_route(
                        script,
                        root,
                        Path(runner_temp),
                        event_name=event_name,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(metadata, {"lane": "legacy-release", "authoritative": "false"})

    def test_representative_routes_cover_all_four_lanes(self) -> None:
        cases = (
            ((), "v3-full", False),
            ((change("M", "README.md"),), "focused", False),
            ((change("M", "tests/v3/core/test_models.py"),), "focused", False),
            ((change("M", "auto_g16/core/store.py"),), "affected", False),
            ((change("M", "docs/v3/STATUS.md"),), "v3-full", False),
            ((change("M", "skills/auto-g16-rtwin-pbs/SKILL.md"),), "legacy-release", False),
        )
        for changes, lane, fail_closed in cases:
            with self.subTest(changes=changes):
                result = self.select(*changes)
                self.assertEqual(result["lane"], lane)
                self.assertEqual(result["fail_closed"], fail_closed)

    def test_v3_control_docs_select_v3_full_deterministically(self) -> None:
        agents = change("M", "AGENTS.md")
        context_map = change("M", "config/context-map.toml")
        handbook = change("M", "docs/development-handbook.md")
        status = change("M", "docs/v3/STATUS.md")
        decisions = {
            "agents only": self.select(agents),
            "context map only": self.select(context_map),
            "handbook only": self.select(handbook),
            "status only": self.select(status),
            "exact closeout pair": self.select(handbook, status),
            "reversed closeout pair": self.select(status, handbook),
        }
        for label, decision in decisions.items():
            with self.subTest(label=label):
                self.assertEqual(decision["lane"], "v3-full")
                self.assertFalse(decision["fail_closed"])
                self.assertNotEqual(decision["lane"], "legacy-release")
                self.assertEqual(decision["matched_routes"], ["v3-control-docs"])

        for field in (
            "changed_paths",
            "lane",
            "tests",
            "matched_routes",
            "safety_evidence",
            "fail_closed",
        ):
            self.assertEqual(
                decisions["exact closeout pair"][field],
                decisions["reversed closeout pair"][field],
            )

    def test_transport_route_owns_future_product_and_test_prefixes(self) -> None:
        product = change("A", "auto_g16/transport/rtwin.py")
        tests = change("A", "tests/v3/transport/test_rtwin.py")
        decisions = {
            "product only": self.select(product),
            "tests only": self.select(tests),
            "product then tests": self.select(product, tests),
            "tests then product": self.select(tests, product),
        }
        for label, decision in decisions.items():
            with self.subTest(label=label):
                self.assertEqual(decision["lane"], "affected")
                self.assertEqual(decision["matched_routes"], ["v30-transport"])
                self.assertEqual(decision["tests"], TRANSPORT_TESTS)
                self.assertEqual(decision["safety_evidence"], TRANSPORT_SAFETY)
                self.assertFalse(decision["fail_closed"])

        for field in (
            "changed_paths",
            "lane",
            "tests",
            "matched_routes",
            "safety_evidence",
            "fail_closed",
        ):
            self.assertEqual(
                decisions["product then tests"][field],
                decisions["tests then product"][field],
            )

    def test_transport_upstream_route_unions_are_deterministic_and_closed(self) -> None:
        transport = change("M", "auto_g16/transport/rtwin.py")
        cases = (
            (
                "core store",
                change("M", "auto_g16/core/store.py"),
                ["core-store", "v30-transport"],
                sorted({*TRANSPORT_TESTS, "tests.v3.core.test_models"}),
            ),
            (
                "approval",
                change("M", "auto_g16/approval/service.py"),
                ["v30-approval", "v30-transport"],
                sorted({*TRANSPORT_TESTS, *APPROVAL_TESTS}),
            ),
            (
                "workflow",
                change("M", "auto_g16/workflow/service.py"),
                ["v30-transport", "v30-workflow"],
                sorted({*TRANSPORT_TESTS, *WORKFLOW_TESTS}),
            ),
            (
                "execution",
                change("M", "auto_g16/execution/service.py"),
                ["v30-execution", "v30-transport"],
                TRANSPORT_TESTS,
            ),
            (
                "observe",
                change("M", "auto_g16/observe/service.py"),
                ["v30-observe", "v30-transport"],
                TRANSPORT_TESTS,
            ),
            (
                "result",
                change("M", "auto_g16/result/parser.py"),
                ["v30-result", "v30-transport"],
                sorted({*TRANSPORT_TESTS, *RESULT_TESTS}),
            ),
        )
        for label, upstream, routes, tests in cases:
            with self.subTest(label=label):
                forward = self.select(transport, upstream)
                reverse = self.select(upstream, transport)
                for field in (
                    "lane",
                    "tests",
                    "matched_routes",
                    "safety_evidence",
                    "fail_closed",
                ):
                    self.assertEqual(forward[field], reverse[field])
                self.assertEqual(forward["lane"], "affected")
                self.assertEqual(forward["matched_routes"], routes)
                self.assertEqual(forward["tests"], tests)
                self.assertEqual(forward["safety_evidence"], TRANSPORT_SAFETY)
                self.assertFalse(forward["fail_closed"])

    def test_transport_never_weakens_unmapped_or_self_protection(self) -> None:
        transport = change("M", "auto_g16/transport/rtwin.py")
        cases = (
            ("unmapped", change("A", "unmapped/future_surface.py")),
            ("manifest", change("M", "config/validation-selection.json")),
            ("selector tests", change("M", "tests/test_validation_selector.py")),
        )
        for label, protected in cases:
            with self.subTest(label=label):
                decision = self.select(transport, protected)
                self.assertEqual(decision["lane"], "legacy-release")
                self.assertTrue(decision["fail_closed"])
                self.assertEqual(decision["tests"], [])

    def test_future_transport_route_does_not_require_current_package(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = initialize_repository(root, {"README.md": "baseline\n"})
            self.assertFalse((root / "auto_g16" / "transport").exists())
            self.assertFalse((root / "tests" / "v3" / "transport").exists())
            head = commit_files(
                root,
                {
                    "auto_g16/transport/rtwin.py": "RTWIN_ADAPTER = 1\n",
                    "tests/v3/transport/test_rtwin.py": "TRANSPORT_TEST = 1\n",
                },
            )
            decision = SELECTOR.compute_selection(root, base, head)

        self.assertEqual(decision["lane"], "affected")
        self.assertEqual(decision["matched_routes"], ["v30-transport"])
        self.assertEqual(decision["tests"], TRANSPORT_TESTS)
        self.assertEqual(decision["safety_evidence"], TRANSPORT_SAFETY)
        self.assertFalse(decision["fail_closed"])

    def test_execution_and_result_routes_own_product_and_test_prefixes(self) -> None:
        cases = (
            (
                "execution product",
                "auto_g16/execution/service.py",
                "v30-execution",
                EXEC_TESTS,
                EXEC_SAFETY,
            ),
            (
                "execution tests",
                "tests/v3/execution/test_service.py",
                "v30-execution",
                EXEC_TESTS,
                EXEC_SAFETY,
            ),
            (
                "result product",
                "auto_g16/result/parser.py",
                "v30-result",
                RESULT_TESTS,
                RESULT_SAFETY,
            ),
            (
                "result tests",
                "tests/v3/result/test_parser.py",
                "v30-result",
                RESULT_TESTS,
                RESULT_SAFETY,
            ),
        )
        for label, path, route, tests, safety in cases:
            with self.subTest(label=label):
                result = self.select(change("A", path))
                self.assertEqual(result["lane"], "affected")
                self.assertEqual(result["matched_routes"], [route])
                self.assertEqual(result["tests"], tests)
                self.assertEqual(result["safety_evidence"], safety)
                self.assertFalse(result["fail_closed"])

    def test_scientific_validation_route_owns_future_product_and_test_prefixes(self) -> None:
        product = change("A", "auto_g16/scientific_validation/service.py")
        tests = change("A", "tests/v3/scientific_validation/test_service.py")
        decisions = {
            "product only": self.select(product),
            "tests only": self.select(tests),
            "product then tests": self.select(product, tests),
            "tests then product": self.select(tests, product),
        }
        for label, decision in decisions.items():
            with self.subTest(label=label):
                self.assertEqual(decision["lane"], "affected")
                self.assertEqual(
                    decision["matched_routes"], ["v30-scientific-validation"]
                )
                self.assertEqual(decision["tests"], SCIENTIFIC_VALIDATION_TESTS)
                self.assertEqual(
                    decision["safety_evidence"], SCIENTIFIC_VALIDATION_SAFETY
                )
                self.assertFalse(decision["fail_closed"])

        for field in (
            "changed_paths",
            "lane",
            "tests",
            "matched_routes",
            "safety_evidence",
            "fail_closed",
        ):
            self.assertEqual(
                decisions["product then tests"][field],
                decisions["tests then product"][field],
            )

    def test_scientific_validation_and_result_union_is_deterministic(self) -> None:
        scientific_validation = change(
            "M", "auto_g16/scientific_validation/service.py"
        )
        result = change("M", "auto_g16/result/parser.py")
        forward = self.select(scientific_validation, result)
        reverse = self.select(result, scientific_validation)
        for field in (
            "lane",
            "tests",
            "matched_routes",
            "safety_evidence",
            "fail_closed",
        ):
            self.assertEqual(forward[field], reverse[field])
        self.assertEqual(forward["lane"], "affected")
        self.assertEqual(
            forward["matched_routes"],
            ["v30-result", "v30-scientific-validation"],
        )
        self.assertEqual(forward["tests"], SCIENTIFIC_VALIDATION_TESTS)
        self.assertEqual(
            forward["safety_evidence"], SCIENTIFIC_VALIDATION_SAFETY
        )
        self.assertFalse(forward["fail_closed"])

    def test_scientific_validation_and_context_map_escalate_to_v3_full(self) -> None:
        scientific_validation = change(
            "M", "auto_g16/scientific_validation/service.py"
        )
        context_map = change("M", "config/context-map.toml")
        forward = self.select(scientific_validation, context_map)
        reverse = self.select(context_map, scientific_validation)
        for field in (
            "lane",
            "tests",
            "matched_routes",
            "safety_evidence",
            "fail_closed",
        ):
            self.assertEqual(forward[field], reverse[field])
        self.assertEqual(forward["lane"], "v3-full")
        self.assertEqual(
            forward["matched_routes"],
            ["v3-control-docs", "v30-scientific-validation"],
        )
        self.assertFalse(forward["fail_closed"])

    def test_future_scientific_validation_route_does_not_require_current_package(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = initialize_repository(root, {"README.md": "baseline\n"})
            self.assertFalse((root / "auto_g16" / "scientific_validation").exists())
            self.assertFalse((root / "tests" / "v3" / "scientific_validation").exists())
            head = commit_files(
                root,
                {
                    "auto_g16/scientific_validation/service.py": "SERVICE = 1\n",
                    "tests/v3/scientific_validation/test_service.py": "TEST = 1\n",
                },
            )
            decision = SELECTOR.compute_selection(root, base, head)

        self.assertEqual(decision["lane"], "affected")
        self.assertEqual(
            decision["matched_routes"], ["v30-scientific-validation"]
        )
        self.assertEqual(decision["tests"], SCIENTIFIC_VALIDATION_TESTS)
        self.assertEqual(
            decision["safety_evidence"], SCIENTIFIC_VALIDATION_SAFETY
        )
        self.assertFalse(decision["fail_closed"])

    def test_approval_route_owns_future_product_and_test_prefixes(self) -> None:
        product = change("A", "auto_g16/approval/service.py")
        tests = change("A", "tests/v3/approval/test_service.py")
        decisions = {
            "product only": self.select(product),
            "tests only": self.select(tests),
            "product then tests": self.select(product, tests),
            "tests then product": self.select(tests, product),
        }
        for label, decision in decisions.items():
            with self.subTest(label=label):
                self.assertEqual(decision["lane"], "affected")
                self.assertEqual(decision["matched_routes"], ["v30-approval"])
                self.assertEqual(decision["tests"], APPROVAL_TESTS)
                self.assertEqual(decision["safety_evidence"], APPROVAL_SAFETY)
                self.assertFalse(decision["fail_closed"])

        for field in (
            "changed_paths",
            "lane",
            "tests",
            "matched_routes",
            "safety_evidence",
            "fail_closed",
        ):
            self.assertEqual(
                decisions["product then tests"][field],
                decisions["tests then product"][field],
            )

    def test_approval_and_execution_union_is_deterministic(self) -> None:
        approval = change("M", "auto_g16/approval/service.py")
        execution = change("M", "auto_g16/execution/service.py")
        forward = self.select(approval, execution)
        reverse = self.select(execution, approval)
        for field in ("lane", "tests", "matched_routes", "safety_evidence", "fail_closed"):
            self.assertEqual(forward[field], reverse[field])
        self.assertEqual(forward["lane"], "affected")
        self.assertEqual(forward["matched_routes"], ["v30-approval", "v30-execution"])
        self.assertEqual(forward["tests"], sorted({*APPROVAL_TESTS, *EXEC_TESTS}))
        self.assertEqual(forward["safety_evidence"], EXEC_SAFETY)
        self.assertFalse(forward["fail_closed"])

    def test_workflow_route_owns_future_product_and_test_prefixes(self) -> None:
        product = change("A", "auto_g16/workflow/models.py")
        tests = change("A", "tests/v3/workflow/test_models.py")
        decisions = {
            "product only": self.select(product),
            "tests only": self.select(tests),
            "product then tests": self.select(product, tests),
            "tests then product": self.select(tests, product),
        }
        for label, decision in decisions.items():
            with self.subTest(label=label):
                self.assertEqual(decision["lane"], "affected")
                self.assertEqual(decision["matched_routes"], ["v30-workflow"])
                self.assertEqual(decision["tests"], WORKFLOW_TESTS)
                self.assertEqual(decision["safety_evidence"], WORKFLOW_SAFETY)
                self.assertFalse(decision["fail_closed"])

        for field in (
            "changed_paths",
            "lane",
            "tests",
            "matched_routes",
            "safety_evidence",
            "fail_closed",
        ):
            self.assertEqual(
                decisions["product then tests"][field],
                decisions["tests then product"][field],
            )

    def test_workflow_and_core_store_union_is_deterministic_and_closed(self) -> None:
        workflow = change("M", "auto_g16/workflow/models.py")
        core_store = change("M", "auto_g16/core/store.py")
        forward = self.select(workflow, core_store)
        reverse = self.select(core_store, workflow)
        for field in ("lane", "tests", "matched_routes", "safety_evidence", "fail_closed"):
            self.assertEqual(forward[field], reverse[field])
        self.assertEqual(forward["lane"], "affected")
        self.assertEqual(forward["matched_routes"], ["core-store", "v30-workflow"])
        self.assertEqual(
            forward["tests"],
            sorted({*WORKFLOW_TESTS, "tests.v3.core.test_models"}),
        )
        self.assertEqual(
            forward["safety_evidence"],
            [
                "approval-owner-separation",
                "at-most-one-submission",
                "no-overwrite",
                "reconciliation",
                "unknown-no-automatic-retry",
            ],
        )
        self.assertFalse(forward["fail_closed"])

    def test_workflow_and_approval_union_is_deterministic_and_closed(self) -> None:
        workflow = change("M", "auto_g16/workflow/models.py")
        approval = change("M", "auto_g16/approval/service.py")
        forward = self.select(workflow, approval)
        reverse = self.select(approval, workflow)
        for field in ("lane", "tests", "matched_routes", "safety_evidence", "fail_closed"):
            self.assertEqual(forward[field], reverse[field])
        self.assertEqual(forward["lane"], "affected")
        self.assertEqual(forward["matched_routes"], ["v30-approval", "v30-workflow"])
        self.assertEqual(forward["tests"], sorted({*WORKFLOW_TESTS, *APPROVAL_TESTS}))
        self.assertEqual(forward["safety_evidence"], APPROVAL_SAFETY)
        self.assertFalse(forward["fail_closed"])

    def test_workflow_never_weakens_legacy_or_fail_closed_selection(self) -> None:
        workflow = change("M", "auto_g16/workflow/models.py")
        legacy = self.select(workflow, change("M", "scripts/legacy_adapter.py"))
        self.assertEqual(legacy["lane"], "legacy-release")
        self.assertEqual(legacy["matched_routes"], ["legacy-touch", "v30-workflow"])

        cases = (
            ("unmapped", change("A", "unmapped/future_surface.py")),
            ("manifest", change("M", "config/validation-selection.json")),
            ("selector tests", change("M", "tests/test_validation_selector.py")),
        )
        for label, protected in cases:
            with self.subTest(label=label):
                decision = self.select(workflow, protected)
                self.assertEqual(decision["lane"], "legacy-release")
                self.assertTrue(decision["fail_closed"])
                self.assertEqual(decision["tests"], [])

    def test_future_workflow_route_does_not_require_current_package(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = initialize_repository(root, {"README.md": "baseline\n"})
            self.assertFalse((root / "auto_g16" / "workflow").exists())
            self.assertFalse((root / "tests" / "v3" / "workflow").exists())
            head = commit_files(
                root,
                {
                    "auto_g16/workflow/models.py": "WORKFLOW_MODEL = 1\n",
                    "tests/v3/workflow/test_models.py": "WORKFLOW_TEST = 1\n",
                },
            )
            decision = SELECTOR.compute_selection(root, base, head)

        self.assertEqual(decision["lane"], "affected")
        self.assertEqual(decision["matched_routes"], ["v30-workflow"])
        self.assertEqual(decision["tests"], WORKFLOW_TESTS)
        self.assertEqual(decision["safety_evidence"], WORKFLOW_SAFETY)
        self.assertFalse(decision["fail_closed"])

    def test_observe_route_owns_future_product_and_test_prefixes(self) -> None:
        product = change("A", "auto_g16/observe/service.py")
        tests = change("A", "tests/v3/observe/test_service.py")
        decisions = {
            "product only": self.select(product),
            "tests only": self.select(tests),
            "product then tests": self.select(product, tests),
            "tests then product": self.select(tests, product),
        }
        for label, decision in decisions.items():
            with self.subTest(label=label):
                self.assertEqual(decision["lane"], "affected")
                self.assertEqual(decision["matched_routes"], ["v30-observe"])
                self.assertEqual(decision["tests"], OBSERVE_TESTS)
                self.assertEqual(decision["safety_evidence"], OBSERVE_SAFETY)
                self.assertFalse(decision["fail_closed"])

        for field in (
            "changed_paths",
            "lane",
            "tests",
            "matched_routes",
            "safety_evidence",
            "fail_closed",
        ):
            self.assertEqual(
                decisions["product then tests"][field],
                decisions["tests then product"][field],
            )

    def test_observe_and_core_store_union_is_deterministic_and_closed(self) -> None:
        observe = change("M", "auto_g16/observe/service.py")
        core_store = change("M", "auto_g16/core/store.py")
        forward = self.select(observe, core_store)
        reverse = self.select(core_store, observe)
        for field in ("lane", "tests", "matched_routes", "safety_evidence", "fail_closed"):
            self.assertEqual(forward[field], reverse[field])
        self.assertEqual(forward["lane"], "affected")
        self.assertEqual(forward["matched_routes"], ["core-store", "v30-observe"])
        self.assertEqual(
            forward["tests"],
            sorted({*OBSERVE_TESTS, "tests.v3.core.test_models"}),
        )
        self.assertEqual(
            forward["safety_evidence"],
            [
                "at-most-one-submission",
                "no-overwrite",
                "reconciliation",
                "timeout-slow-running-is-not-failure",
                "unknown-no-automatic-retry",
            ],
        )
        self.assertFalse(forward["fail_closed"])

    def test_observe_and_execution_union_is_deterministic_and_closed(self) -> None:
        observe = change("M", "auto_g16/observe/service.py")
        execution = change("M", "auto_g16/execution/service.py")
        forward = self.select(observe, execution)
        reverse = self.select(execution, observe)
        for field in ("lane", "tests", "matched_routes", "safety_evidence", "fail_closed"):
            self.assertEqual(forward[field], reverse[field])
        self.assertEqual(forward["lane"], "affected")
        self.assertEqual(
            forward["matched_routes"], ["v30-execution", "v30-observe"]
        )
        self.assertEqual(forward["tests"], sorted({*EXEC_TESTS, "tests.v3.observe"}))
        self.assertEqual(forward["safety_evidence"], EXEC_SAFETY)
        self.assertFalse(forward["fail_closed"])

    def test_observe_never_weakens_unmapped_or_self_protection(self) -> None:
        observe = change("M", "auto_g16/observe/service.py")
        cases = (
            ("unmapped", change("A", "unmapped/future_surface.py")),
            ("manifest", change("M", "config/validation-selection.json")),
            ("selector tests", change("M", "tests/test_validation_selector.py")),
        )
        for label, protected in cases:
            with self.subTest(label=label):
                decision = self.select(observe, protected)
                self.assertEqual(decision["lane"], "legacy-release")
                self.assertTrue(decision["fail_closed"])
                self.assertEqual(decision["tests"], [])

    def test_future_observe_route_does_not_require_current_package(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = initialize_repository(root, {"README.md": "baseline\n"})
            self.assertFalse((root / "auto_g16" / "observe").exists())
            self.assertFalse((root / "tests" / "v3" / "observe").exists())
            head = commit_files(
                root,
                {
                    "auto_g16/observe/service.py": "OBSERVE_SERVICE = 1\n",
                    "tests/v3/observe/test_service.py": "OBSERVE_TEST = 1\n",
                },
            )
            decision = SELECTOR.compute_selection(root, base, head)

        self.assertEqual(decision["lane"], "affected")
        self.assertEqual(decision["matched_routes"], ["v30-observe"])
        self.assertEqual(decision["tests"], OBSERVE_TESTS)
        self.assertTrue(decision["tests"])
        self.assertEqual(decision["safety_evidence"], OBSERVE_SAFETY)
        self.assertFalse(decision["fail_closed"])

    def test_review_route_owns_future_product_and_test_prefixes(self) -> None:
        product = change("A", "auto_g16/review/service.py")
        tests = change("A", "tests/v3/review/test_service.py")
        decisions = {
            "product only": self.select(product),
            "tests only": self.select(tests),
            "product then tests": self.select(product, tests),
            "tests then product": self.select(tests, product),
        }
        for label, decision in decisions.items():
            with self.subTest(label=label):
                self.assertEqual(decision["lane"], "affected")
                self.assertEqual(decision["matched_routes"], ["v30-review"])
                self.assertEqual(decision["tests"], REVIEW_TESTS)
                self.assertEqual(decision["safety_evidence"], REVIEW_SAFETY)
                self.assertFalse(decision["fail_closed"])
                self.assertNotIn("tests.v3.execution", decision["tests"])

        for field in (
            "changed_paths",
            "lane",
            "tests",
            "matched_routes",
            "safety_evidence",
            "fail_closed",
        ):
            self.assertEqual(
                decisions["product then tests"][field],
                decisions["tests then product"][field],
            )

    def test_review_upstream_route_unions_are_deterministic_and_closed(self) -> None:
        review = change("M", "auto_g16/review/service.py")
        cases = (
            (
                "scientific validation",
                change("M", "auto_g16/scientific_validation/service.py"),
                ["v30-review", "v30-scientific-validation"],
                REVIEW_TESTS,
                REVIEW_SAFETY,
            ),
            (
                "result",
                change("M", "auto_g16/result/parser.py"),
                ["v30-result", "v30-review"],
                REVIEW_TESTS,
                REVIEW_SAFETY,
            ),
            (
                "core store",
                change("M", "auto_g16/core/store.py"),
                ["core-store", "v30-review"],
                sorted({*REVIEW_TESTS, "tests.v3.core.test_models"}),
                [
                    "at-most-one-submission",
                    "no-overwrite",
                    "reconciliation",
                    "unknown-no-automatic-retry",
                ],
            ),
            (
                "execution",
                change("M", "auto_g16/execution/service.py"),
                ["v30-execution", "v30-review"],
                sorted({*EXEC_TESTS, *REVIEW_TESTS}),
                EXEC_SAFETY,
            ),
        )
        for label, upstream, routes, tests, safety in cases:
            with self.subTest(label=label):
                forward = self.select(review, upstream)
                reverse = self.select(upstream, review)
                for field in (
                    "lane",
                    "tests",
                    "matched_routes",
                    "safety_evidence",
                    "fail_closed",
                ):
                    self.assertEqual(forward[field], reverse[field])
                self.assertEqual(forward["lane"], "affected")
                self.assertEqual(forward["matched_routes"], routes)
                self.assertEqual(forward["tests"], tests)
                self.assertEqual(forward["safety_evidence"], safety)
                self.assertFalse(forward["fail_closed"])

    def test_review_never_weakens_unmapped_or_self_protection(self) -> None:
        review = change("M", "auto_g16/review/service.py")
        cases = (
            ("unmapped", change("A", "unmapped/future_surface.py")),
            ("manifest", change("M", "config/validation-selection.json")),
            ("selector tests", change("M", "tests/test_validation_selector.py")),
        )
        for label, protected in cases:
            with self.subTest(label=label):
                decision = self.select(review, protected)
                self.assertEqual(decision["lane"], "legacy-release")
                self.assertTrue(decision["fail_closed"])
                self.assertEqual(decision["tests"], [])

    def test_v31_routes_own_future_product_and_test_prefixes(self) -> None:
        cases = (
            (
                "conformer",
                "v31-conformer",
                CONFORMER_TESTS,
                "auto_g16/conformer/models.py",
                "tests/v31/conformer/test_models.py",
            ),
            (
                "thermochemistry",
                "v31-thermochemistry",
                THERMOCHEMISTRY_TESTS,
                "auto_g16/thermochemistry/models.py",
                "tests/v31/thermochemistry/test_models.py",
            ),
        )
        for label, route, selected_tests, product_path, test_path in cases:
            product = change("A", product_path)
            tests = change("A", test_path)
            decisions = {
                "product only": self.select(product),
                "tests only": self.select(tests),
                "product then tests": self.select(product, tests),
                "tests then product": self.select(tests, product),
            }
            for decision_label, decision in decisions.items():
                with self.subTest(package=label, decision=decision_label):
                    self.assertEqual(decision["lane"], "affected")
                    self.assertEqual(decision["matched_routes"], [route])
                    self.assertEqual(decision["tests"], selected_tests)
                    self.assertEqual(decision["safety_evidence"], [])
                    self.assertFalse(decision["fail_closed"])

            for field in (
                "changed_paths",
                "lane",
                "tests",
                "matched_routes",
                "safety_evidence",
                "fail_closed",
            ):
                self.assertEqual(
                    decisions["product then tests"][field],
                    decisions["tests then product"][field],
                )

    def test_v31_routes_keep_upstream_dependencies_and_deterministic_union(self) -> None:
        conformer = change("M", "auto_g16/conformer/service.py")
        thermochemistry = change("M", "auto_g16/thermochemistry/service.py")
        forward = self.select(conformer, thermochemistry)
        reverse = self.select(thermochemistry, conformer)
        for field in (
            "changed_paths",
            "lane",
            "tests",
            "matched_routes",
            "safety_evidence",
            "fail_closed",
        ):
            self.assertEqual(forward[field], reverse[field])
        self.assertEqual(forward["lane"], "affected")
        self.assertEqual(
            forward["matched_routes"],
            ["v31-conformer", "v31-thermochemistry"],
        )
        self.assertEqual(
            forward["tests"],
            sorted({*CONFORMER_TESTS, *THERMOCHEMISTRY_TESTS}),
        )
        self.assertEqual(forward["safety_evidence"], [])
        self.assertFalse(forward["fail_closed"])

    def test_v31_offline_e2e_route_is_exact_and_adversarially_bounded(self) -> None:
        for path in (
            "tests/v31/integration/test_v31_offline_end_to_end.py",
            "tests/v31/integration/__init__.py",
        ):
            with self.subTest(path=path):
                decision = self.select(change("A", path))
                self.assertEqual(decision["matched_routes"], ["v31-offline-e2e"])
                self.assertEqual(decision["lane"], "affected")
                self.assertEqual(decision["tests"], V31_OFFLINE_E2E_TESTS)
                self.assertEqual(decision["safety_evidence"], [])
                self.assertFalse(decision["fail_closed"])

        existing_owners = (
            (
                "tests/v31/conformer/test_x.py",
                "v31-conformer",
                CONFORMER_TESTS,
            ),
            (
                "tests/v31/thermochemistry/test_x.py",
                "v31-thermochemistry",
                THERMOCHEMISTRY_TESTS,
            ),
        )
        for path, route, selected_tests in existing_owners:
            with self.subTest(path=path):
                decision = self.select(change("A", path))
                self.assertEqual(decision["matched_routes"], [route])
                self.assertEqual(decision["lane"], "affected")
                self.assertEqual(decision["tests"], selected_tests)
                self.assertFalse(decision["fail_closed"])

        for path in (
            "tests/v31/unknown_future_surface/test_x.py",
            "tests/v31/integration_extra/test_x.py",
            "tests/v31/future/test_x.py",
        ):
            with self.subTest(path=path):
                decision = self.select(change("A", path))
                self.assertEqual(decision["matched_routes"], [])
                self.assertEqual(decision["lane"], "legacy-release")
                self.assertEqual(decision["tests"], [])
                self.assertTrue(decision["fail_closed"])

    def test_v31_routes_never_weaken_unmapped_or_self_protection(self) -> None:
        owners = (
            change("M", "auto_g16/conformer/service.py"),
            change("M", "auto_g16/thermochemistry/service.py"),
        )
        protected_paths = (
            "unmapped/new_surface.py",
            "config/validation-selection.json",
            "scripts/select_validation.py",
            "scripts/run_tests.py",
            "tests/test_validation_selector.py",
            "tests/test_test_runner.py",
        )
        for owner in owners:
            for protected_path in protected_paths:
                with self.subTest(owner=owner, protected_path=protected_path):
                    decision = self.select(owner, change("M", protected_path))
                    self.assertEqual(decision["lane"], "legacy-release")
                    self.assertTrue(decision["fail_closed"])
                    self.assertEqual(decision["tests"], [])

    def test_future_review_route_does_not_require_current_package(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = initialize_repository(root, {"README.md": "baseline\n"})
            self.assertFalse((root / "auto_g16" / "review").exists())
            self.assertFalse((root / "tests" / "v3" / "review").exists())
            head = commit_files(
                root,
                {
                    "auto_g16/review/service.py": "REVIEW_SERVICE = 1\n",
                    "tests/v3/review/test_service.py": "REVIEW_TEST = 1\n",
                },
            )
            decision = SELECTOR.compute_selection(root, base, head)

        self.assertEqual(decision["lane"], "affected")
        self.assertEqual(decision["matched_routes"], ["v30-review"])
        self.assertEqual(decision["tests"], REVIEW_TESTS)
        self.assertTrue(decision["tests"])
        self.assertEqual(decision["safety_evidence"], REVIEW_SAFETY)
        self.assertFalse(decision["fail_closed"])

    def test_approval_and_core_store_close_required_safety_evidence(self) -> None:
        approval = change("M", "auto_g16/approval/service.py")
        core_store = change("M", "auto_g16/core/store.py")
        forward = self.select(approval, core_store)
        reverse = self.select(core_store, approval)
        for field in ("lane", "tests", "matched_routes", "safety_evidence", "fail_closed"):
            self.assertEqual(forward[field], reverse[field])
        self.assertEqual(forward["lane"], "affected")
        self.assertEqual(forward["matched_routes"], ["core-store", "v30-approval"])
        self.assertEqual(
            forward["tests"],
            sorted({*APPROVAL_TESTS, "tests.v3.core.test_models"}),
        )
        self.assertEqual(
            forward["safety_evidence"],
            [
                "approval-owner-separation",
                "at-most-one-submission",
                "no-overwrite",
                "reconciliation",
                "unknown-no-automatic-retry",
            ],
        )
        self.assertFalse(forward["fail_closed"])

    def test_mixed_execution_and_result_change_uses_deterministic_union(self) -> None:
        execution = change("M", "auto_g16/execution/service.py")
        result = change("M", "auto_g16/result/parser.py")
        forward = self.select(execution, result)
        reverse = self.select(result, execution)
        for field in ("lane", "tests", "matched_routes", "safety_evidence", "fail_closed"):
            self.assertEqual(forward[field], reverse[field])
        self.assertEqual(forward["lane"], "affected")
        self.assertEqual(forward["matched_routes"], ["v30-execution", "v30-result"])
        self.assertEqual(forward["tests"], sorted({*EXEC_TESTS, *RESULT_TESTS}))
        self.assertEqual(forward["safety_evidence"], EXEC_SAFETY)
        self.assertFalse(forward["fail_closed"])

    def test_execution_and_result_packages_discover_real_tests(self) -> None:
        for package in (EXECUTION_PACKAGE, RESULT_PACKAGE):
            with self.subTest(package=package.__name__):
                loader = unittest.TestLoader()
                suite = loader.loadTestsFromName(package.__name__)
                self.assertGreater(suite.countTestCases(), 0)
                self.assertEqual(loader.errors, [])
                self.assertTrue(
                    all(
                        identifier.startswith(f"{package.__name__}.test_")
                        for identifier in suite_ids(suite)
                    )
                )

    def test_synthetic_empty_ownership_packages_fail_closed(self) -> None:
        for package in (EXECUTION_PACKAGE, RESULT_PACKAGE):
            with self.subTest(package=package.__name__), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                with (
                    mock.patch.object(package, "__file__", str(directory / "__init__.py")),
                    mock.patch.object(package, "__path__", [str(directory)]),
                ):
                    standard_tests = unittest.TestSuite()
                    suite = package.load_tests(
                        unittest.TestLoader(), standard_tests, "test*.py"
                    )
                    self.assertIs(suite, standard_tests)
                    self.assertEqual(suite.countTestCases(), 0)

                    loader = unittest.TestLoader()
                    failed_suite = loader.loadTestsFromName(package.__name__)
                    outcome = unittest.TestResult()
                    failed_suite.run(outcome)
                    self.assertEqual(failed_suite.countTestCases(), 1)
                    self.assertFalse(outcome.wasSuccessful())
                    self.assertEqual(len(loader.errors), 1)
                    self.assertIn(
                        "contains no direct test*.py test modules", loader.errors[0]
                    )

    def test_package_aggregation_is_stable_direct_and_nonrecursive(self) -> None:
        for package in (EXECUTION_PACKAGE, RESULT_PACKAGE):
            with self.subTest(package=package.__name__), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                (directory / "test_zeta.py").write_text(
                    "import unittest\n"
                    "class ZetaTests(unittest.TestCase):\n"
                    "    def test_zeta(self): self.assertTrue(True)\n",
                    encoding="utf-8",
                )
                (directory / "test_alpha.py").write_text(
                    "import unittest\n"
                    "class AlphaTests(unittest.TestCase):\n"
                    "    def test_alpha(self): self.assertTrue(True)\n",
                    encoding="utf-8",
                )
                nested = directory / "nested"
                nested.mkdir()
                (nested / "test_nested.py").write_text(
                    "raise AssertionError('recursive discovery is forbidden')\n",
                    encoding="utf-8",
                )
                module_names = [
                    f"{package.__name__}.test_alpha",
                    f"{package.__name__}.test_zeta",
                ]
                try:
                    with (
                        mock.patch.object(package, "__file__", str(directory / "__init__.py")),
                        mock.patch.object(package, "__path__", [str(directory)]),
                    ):
                        first = package.load_tests(
                            unittest.TestLoader(), unittest.TestSuite(), None
                        )
                        second = package.load_tests(
                            unittest.TestLoader(), unittest.TestSuite(), "test*.py"
                        )
                finally:
                    for name in module_names:
                        sys.modules.pop(name, None)

                expected = [
                    f"{package.__name__}.test_alpha.AlphaTests.test_alpha",
                    f"{package.__name__}.test_zeta.ZetaTests.test_zeta",
                ]
                self.assertEqual(suite_ids(first), expected)
                self.assertEqual(suite_ids(second), expected)
                self.assertEqual(first.countTestCases(), 2)

    def test_package_aggregation_rejects_test_modules_with_zero_tests(self) -> None:
        for package in (EXECUTION_PACKAGE, RESULT_PACKAGE):
            with self.subTest(package=package.__name__), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                (directory / "test_empty.py").write_text("VALUE = 'no tests'\n", encoding="utf-8")
                module_name = f"{package.__name__}.test_empty"
                try:
                    with (
                        mock.patch.object(package, "__file__", str(directory / "__init__.py")),
                        mock.patch.object(package, "__path__", [str(directory)]),
                        self.assertRaisesRegex(RuntimeError, "discovered zero tests"),
                    ):
                        package.load_tests(unittest.TestLoader(), unittest.TestSuite(), None)
                finally:
                    sys.modules.pop(module_name, None)

    def test_unknown_generated_and_self_changes_fail_closed(self) -> None:
        cases = (
            "unmapped/new_surface.py",
            "generated/contracts.json",
            "config/validation-selection.json",
            "scripts/select_validation.py",
            "scripts/run_tests.py",
            "tests/test_validation_selector.py",
            "tests/test_test_runner.py",
        )
        for path in cases:
            with self.subTest(path=path):
                result = self.select(change("M", path))
                self.assertEqual(result["lane"], "legacy-release")
                self.assertTrue(result["fail_closed"])
                self.assertEqual(result["tests"], [])

    def test_core_store_selection_carries_every_required_safety_tag(self) -> None:
        result = self.select(change("M", "auto_g16/core/store.py"))
        self.assertEqual(result["lane"], "affected")
        self.assertEqual(
            result["safety_evidence"],
            [
                "at-most-one-submission",
                "no-overwrite",
                "reconciliation",
                "unknown-no-automatic-retry",
            ],
        )
        self.assertEqual(
            result["tests"],
            ["tests.v3.core.test_models", "tests.v3.core.test_store"],
        )

    def test_every_declared_safety_evidence_name_resolves(self) -> None:
        loader = unittest.TestLoader()
        for tag, names in self.manifest["safety_evidence"].items():
            for name in names:
                with self.subTest(tag=tag, name=name):
                    suite = loader.loadTestsFromName(name)
                    self.assertGreater(suite.countTestCases(), 0)
                    self.assertEqual(loader.errors, [])

    def test_missing_safety_carrier_fails_closed(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        manifest["routes"][1]["tests"] = ["tests.v3.core.test_models"]
        result = SELECTOR.select_changes(
            manifest,
            [change("M", "auto_g16/core/store.py")],
        )
        self.assertEqual(result["lane"], "legacy-release")
        self.assertTrue(result["fail_closed"])
        self.assertIn("required safety evidence", result["reasons"][0])

    def test_rename_uses_old_and_new_paths_and_delete_uses_owned_old_path(self) -> None:
        renamed = self.select(
            change("R100", "auto_g16/core/models.py", "unmapped/models.py")
        )
        self.assertEqual(
            renamed["changed_paths"],
            ["auto_g16/core/models.py", "unmapped/models.py"],
        )
        self.assertEqual(renamed["lane"], "legacy-release")
        self.assertTrue(renamed["fail_closed"])

        deleted = self.select(change("D", "auto_g16/core/store.py"))
        self.assertEqual(deleted["changed_paths"], ["auto_g16/core/store.py"])
        self.assertEqual(deleted["lane"], "affected")

        copied_forward = self.select(
            change("C100", "skills/high-risk.py", "auto_g16/core/models.py")
        )
        copied_reverse = self.select(
            change("C100", "auto_g16/core/models.py", "skills/high-risk.py")
        )
        for copied in (copied_forward, copied_reverse):
            self.assertEqual(copied["lane"], "legacy-release")
            self.assertFalse(copied["fail_closed"])

    def test_diff_parser_rejects_unknown_and_incomplete_records(self) -> None:
        self.assertEqual(
            SELECTOR.parse_name_status(b"R100\0old.py\0new.py\0D\0gone.py\0"),
            [
                {"status": "R100", "paths": ["old.py", "new.py"]},
                {"status": "D", "paths": ["gone.py"]},
            ],
        )
        for raw in (b"U\0conflict.py\0", b"R100\0old.py\0"):
            with self.subTest(raw=raw), self.assertRaises(SELECTOR.SelectionError):
                SELECTOR.parse_name_status(raw)

    def test_manifest_rejects_duplicates_overlap_and_missing_safety(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "manifest.json"
            original = MANIFEST.read_text(encoding="utf-8")
            path.write_text(original.replace('"version": 1,', '"version": 1,\n  "version": 1,'), encoding="utf-8")
            with self.assertRaisesRegex(SELECTOR.SelectionError, "duplicate JSON key"):
                SELECTOR._load_manifest_for_test(path)

            overlap = copy.deepcopy(self.manifest)
            overlap["routes"][0]["exact_paths"].append("auto_g16/core/store.py")
            path.write_text(json.dumps(overlap), encoding="utf-8")
            with self.assertRaisesRegex(SELECTOR.SelectionError, "ambiguous exact path"):
                SELECTOR._load_manifest_for_test(path)

            missing = copy.deepcopy(self.manifest)
            del missing["safety_evidence"]["no-overwrite"]
            path.write_text(json.dumps(missing), encoding="utf-8")
            with self.assertRaisesRegex(SELECTOR.SelectionError, "unavailable safety evidence"):
                SELECTOR._load_manifest_for_test(path)

    def test_exact_git_range_records_rename_identity_and_rejects_short_sha(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(["git", "-C", str(root), "config", "user.name", "Selector Test"], check=True)
            subprocess.run(["git", "-C", str(root), "config", "user.email", "selector@example.invalid"], check=True)
            source = root / "auto_g16" / "core"
            source.mkdir(parents=True)
            (source / "models.py").write_text("value = 1\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "auto_g16/core/models.py"], check=True)
            subprocess.run(["git", "-C", str(root), "commit", "-qm", "base"], check=True)
            base = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
            (root / "unmapped").mkdir()
            subprocess.run(
                ["git", "-C", str(root), "mv", "auto_g16/core/models.py", "unmapped/models.py"],
                check=True,
            )
            subprocess.run(["git", "-C", str(root), "commit", "-qam", "rename"], check=True)
            head = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()

            changes, merge_base, head_tree = SELECTOR.inspect_git_range(root, base, head)
            result = SELECTOR.select_changes(
                self.manifest,
                changes,
                base=base,
                head=head,
                merge_base=merge_base,
                head_tree=head_tree,
            )
            self.assertEqual(result["lane"], "legacy-release")
            self.assertTrue(result["fail_closed"])
            self.assertEqual(result["base"], base)
            self.assertEqual(result["head"], head)
            self.assertRegex(result["head_tree"], r"^[0-9a-f]{40}$")
            self.assertEqual(
                result["changed_paths"],
                ["auto_g16/core/models.py", "unmapped/models.py"],
            )
            with self.assertRaisesRegex(SELECTOR.SelectionError, "full lowercase"):
                SELECTOR.inspect_git_range(root, base[:12], head)

    def test_actual_unchanged_source_copies_preserve_both_paths_conservatively(self) -> None:
        cases = (
            (
                "skills/high-risk.py",
                "auto_g16/core/models.py",
                "legacy source copied to focused destination",
            ),
            (
                "auto_g16/core/models.py",
                "skills/high-risk.py",
                "focused source copied to legacy destination",
            ),
        )
        for source, destination, label in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                payload = "identity-preserving copy\nsecond line\n"
                base = initialize_repository(root, {source: payload})
                head = commit_change(root, destination, payload)
                changes, _merge_base, _tree = SELECTOR.inspect_git_range(root, base, head)
                self.assertEqual(
                    changes,
                    [{"status": "C100", "paths": [source, destination]}],
                )
                decision = SELECTOR.compute_selection(root, base, head)
                self.assertEqual(decision["lane"], "legacy-release")
                self.assertEqual(decision["changed_paths"], sorted({source, destination}))

    def test_reviewer_copy_fixture_enumerates_hidden_high_risk_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload = "reviewer identical blob\nsecond line\n"
            low_source = "auto_g16/core/models.py"
            high_source = "auto_g16/core/store.py"
            destination = "tests/v3/core/test_models.py"
            base = initialize_repository(
                root,
                {low_source: payload, high_source: payload},
            )
            head = commit_change(root, destination, payload)

            self.assertEqual(
                raw_copy_diff(root, base, head),
                [{"status": "C100", "paths": [low_source, destination]}],
            )
            changes, _merge_base, _tree = SELECTOR.inspect_git_range(root, base, head)
            decision = SELECTOR.compute_selection(root, base, head)

        self.assertEqual(
            changes,
            [{"status": "C100", "paths": [low_source, high_source, destination]}],
        )
        self.assertEqual(decision["lane"], "affected")
        self.assertEqual(
            decision["tests"],
            ["tests.v3.core.test_models", "tests.v3.core.test_store"],
        )
        self.assertEqual(
            decision["safety_evidence"],
            [
                "at-most-one-submission",
                "no-overwrite",
                "reconciliation",
                "unknown-no-automatic-retry",
            ],
        )
        self.assertFalse(decision["fail_closed"])

    def test_multiple_exact_sources_use_maximum_tier_and_union_safety(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload = "shared across all tiers\nsecond line\n"
            sources = {
                "auto_g16/core/models.py": payload,
                "auto_g16/core/store.py": payload,
                "skills/high-risk.py": payload,
            }
            destination = "tests/v3/core/test_models.py"
            base = initialize_repository(root, sources)
            head = commit_change(root, destination, payload)
            decision = SELECTOR.compute_selection(root, base, head)

        self.assertEqual(decision["lane"], "legacy-release")
        self.assertEqual(decision["tests"], [])
        self.assertEqual(
            decision["safety_evidence"],
            [
                "at-most-one-submission",
                "no-overwrite",
                "reconciliation",
                "unknown-no-automatic-retry",
            ],
        )
        self.assertFalse(decision["fail_closed"])
        self.assertEqual(
            decision["changed_paths"],
            sorted([*sources, destination]),
        )

    def test_copy_closure_is_stable_across_git_attribution_and_order(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload = "stable attribution blob\nsecond line\n"
            low_source = "auto_g16/core/models.py"
            high_source = "auto_g16/core/store.py"
            destinations = (
                "auto_g16/core/__init__.py",
                "tests/v3/core/test_models.py",
            )
            base = initialize_repository(
                root,
                {low_source: payload, high_source: payload},
            )
            head = commit_files(root, {item: payload for item in destinations})
            git_executable, _version = SELECTOR.resolve_git()
            low_attribution = SELECTOR._close_exact_copy_sources(
                root,
                base,
                head,
                [
                    change("C100", low_source, destinations[0]),
                    change("C100", low_source, destinations[1]),
                ],
                git_executable,
            )
            high_attribution_reversed = SELECTOR._close_exact_copy_sources(
                root,
                base,
                head,
                [
                    change("C100", high_source, destinations[1]),
                    change("C100", high_source, destinations[0]),
                ],
                git_executable,
            )

        self.assertEqual(low_attribution, high_attribution_reversed)
        for record in low_attribution:
            self.assertEqual(record["paths"][:2], [low_source, high_source])

    def test_one_exact_copy_source_remains_precise(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload = "one exact source\nsecond line\n"
            source = "auto_g16/core/models.py"
            destination = "tests/v3/core/test_models.py"
            base = initialize_repository(root, {source: payload})
            head = commit_change(root, destination, payload)
            changes, _merge_base, _tree = SELECTOR.inspect_git_range(root, base, head)
            decision = SELECTOR.compute_selection(root, base, head)

        self.assertEqual(
            changes,
            [{"status": "C100", "paths": [source, destination]}],
        )
        self.assertEqual(decision["lane"], "focused")
        self.assertEqual(decision["tests"], ["tests.v3.core.test_models"])
        self.assertEqual(decision["safety_evidence"], [])

    def test_non_exact_or_blob_mismatched_copy_fails_closed(self) -> None:
        cases = (
            ("C099", "same exact blob\nsecond line\n"),
            ("C100", "different destination blob\nsecond line\n"),
        )
        for status, destination_payload in cases:
            with self.subTest(status=status), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source = "auto_g16/core/models.py"
                destination = "tests/v3/core/test_models.py"
                source_payload = "same exact blob\nsecond line\n"
                base = initialize_repository(root, {source: source_payload})
                head = commit_change(root, destination, destination_payload)
                with mock.patch.object(
                    SELECTOR,
                    "parse_name_status",
                    return_value=[change(status, source, destination)],
                ):
                    decision = SELECTOR.compute_selection(root, base, head)

            self.assertEqual(decision["lane"], "legacy-release")
            self.assertTrue(decision["fail_closed"])
            self.assertEqual(decision["tests"], [])
            self.assertIn("ambiguous_copy_source", decision["reasons"][0])

    def test_unclosable_exact_candidate_enumeration_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload = "exact but unclosable copy\nsecond line\n"
            source = "auto_g16/core/models.py"
            destination = "tests/v3/core/test_models.py"
            base = initialize_repository(root, {source: payload})
            head = commit_change(root, destination, payload)
            with mock.patch.object(
                SELECTOR,
                "_base_blob_paths",
                side_effect=SELECTOR.SelectionError("synthetic incomplete tree"),
            ):
                decision = SELECTOR.compute_selection(root, base, head)

        self.assertEqual(decision["lane"], "legacy-release")
        self.assertTrue(decision["fail_closed"])
        self.assertEqual(decision["tests"], [])
        self.assertIn("ambiguous_copy_source", decision["reasons"][0])

    def test_unmapped_exact_source_candidate_uses_unknown_path_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload = "unmapped twin blob\nsecond line\n"
            mapped = "auto_g16/core/models.py"
            unmapped = "unmapped/twin.py"
            destination = "tests/v3/core/test_models.py"
            base = initialize_repository(root, {mapped: payload, unmapped: payload})
            head = commit_change(root, destination, payload)
            decision = SELECTOR.compute_selection(root, base, head)

        self.assertEqual(decision["lane"], "legacy-release")
        self.assertTrue(decision["fail_closed"])
        self.assertIn(f"changed path is not mapped: {unmapped}", decision["reasons"][0])

    def test_actual_delete_retains_the_owned_old_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = "auto_g16/core/store.py"
            base = initialize_repository(root, {path: "value = 1\n"})
            (root / path).unlink()
            subprocess.run(["git", "-C", str(root), "add", "--", path], check=True)
            subprocess.run(["git", "-C", str(root), "commit", "-qm", "delete"], check=True)
            head = git(root, "rev-parse", "HEAD")
            changes, _merge_base, _tree = SELECTOR.inspect_git_range(root, base, head)
            self.assertEqual(changes, [{"status": "D", "paths": [path]}])
            self.assertEqual(SELECTOR.compute_selection(root, base, head)["lane"], "affected")

    def test_candidate_authority_is_exact_and_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = initialize_repository(
                root,
                {"auto_g16/core/models.py": "value = 1\n"},
            )
            head = commit_change(root, "auto_g16/core/models.py", "value = 2\n")
            first = SELECTOR.compute_selection(root, base, head)
            second = SELECTOR.compute_selection(root, base, head)

        self.assertEqual(first, second)
        self.assertEqual(first["lane"], "focused")
        self.assertEqual(first["manifest_path"], SELECTOR.MANIFEST_RELATIVE)
        self.assertRegex(first["manifest_blob"], r"^[0-9a-f]{40}$")
        self.assertTrue(Path(first["git_executable"]).is_absolute())
        self.assertTrue(first["git_version"].startswith("git version "))
        self.assertRegex(first["head_tree"], r"^[0-9a-f]{40}$")

    def test_mixed_path_maximum_and_delete_remain_deterministic(self) -> None:
        forward = self.select(
            change("M", "auto_g16/core/models.py"),
            change("M", "auto_g16/core/store.py"),
        )
        reverse = self.select(
            change("M", "auto_g16/core/store.py"),
            change("M", "auto_g16/core/models.py"),
        )
        for field in ("lane", "tests", "matched_routes", "safety_evidence", "fail_closed"):
            self.assertEqual(forward[field], reverse[field])
        self.assertEqual(forward["lane"], "affected")
        self.assertEqual(
            self.select(change("D", "auto_g16/core/store.py"))["lane"],
            "affected",
        )

    def test_production_cli_rejects_external_manifest_and_repository_authority(self) -> None:
        with self.assertRaises(SystemExit) as manifest:
            SELECTOR.main(
                [
                    "--base",
                    "0" * 40,
                    "--head",
                    "1" * 40,
                    "--manifest",
                    "/tmp/external.json",
                ]
            )
        self.assertEqual(manifest.exception.code, 2)
        with self.assertRaises(SystemExit) as repository:
            SELECTOR.main(
                ["--base", "0" * 40, "--head", "1" * 40, "--repo", "/tmp"]
            )
        self.assertEqual(repository.exception.code, 2)

    def test_cli_invalid_identity_emits_legacy_release_result(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            returncode = SELECTOR.main(["--base", "short", "--head", "also-short"])
        self.assertEqual(returncode, 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result["lane"], "legacy-release")
        self.assertTrue(result["fail_closed"])
        self.assertEqual(result["tests"], [])
        self.assertIsNone(result["base"])
        self.assertIsNone(result["head"])


if __name__ == "__main__":
    unittest.main()
