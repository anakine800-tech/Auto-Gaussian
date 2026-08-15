#!/usr/bin/env python3
"""Focused offline tests for fail-closed changed-path validation selection."""

from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "select_validation.py"
MANIFEST = ROOT / "config" / "validation-selection.json"
SPEC = importlib.util.spec_from_file_location("validation_selector", SCRIPT)
assert SPEC and SPEC.loader
SELECTOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SELECTOR)


def change(status: str, *paths: str) -> dict[str, object]:
    return {"status": status, "paths": list(paths)}


class ValidationSelectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = SELECTOR.load_manifest(MANIFEST)

    def select(self, *changes: dict[str, object]) -> dict[str, object]:
        return SELECTOR.select_changes(self.manifest, list(changes))

    def test_representative_routes_cover_all_four_lanes(self) -> None:
        cases = (
            ((), "v3-full", False),
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

    def test_transport_and_result_fail_closed_until_v3_evidence_exists(self) -> None:
        expected = {
            "auto_g16/transport/openssh.py": {
                "approval-owner-separation",
                "at-most-one-submission",
                "no-overwrite",
                "reconciliation",
                "still-applicable-descriptor-capability",
                "timeout-slow-running-is-not-failure",
                "unknown-no-automatic-retry",
            },
            "auto_g16/result/parser.py": {"unknown-no-automatic-retry"},
        }
        for path, safety in expected.items():
            with self.subTest(path=path):
                result = self.select(change("A", path))
                self.assertEqual(result["lane"], "legacy-release")
                self.assertTrue(result["fail_closed"])
                self.assertEqual(result["tests"], [])
                self.assertEqual(set(result["safety_evidence"]), safety)

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
                SELECTOR.load_manifest(path)

            overlap = copy.deepcopy(self.manifest)
            overlap["routes"][0]["exact_paths"].append("auto_g16/core/store.py")
            path.write_text(json.dumps(overlap), encoding="utf-8")
            with self.assertRaisesRegex(SELECTOR.SelectionError, "ambiguous exact path"):
                SELECTOR.load_manifest(path)

            missing = copy.deepcopy(self.manifest)
            del missing["safety_evidence"]["no-overwrite"]
            path.write_text(json.dumps(missing), encoding="utf-8")
            with self.assertRaisesRegex(SELECTOR.SelectionError, "unavailable safety evidence"):
                SELECTOR.load_manifest(path)

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

    def test_cli_invalid_identity_emits_legacy_release_result(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            returncode = SELECTOR.main(
                ["--base", "short", "--head", "also-short", "--repo", str(ROOT)]
            )
        self.assertEqual(returncode, 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result["lane"], "legacy-release")
        self.assertTrue(result["fail_closed"])
        self.assertEqual(result["tests"], [])
        self.assertIsNone(result["base"])
        self.assertIsNone(result["head"])


if __name__ == "__main__":
    unittest.main()
