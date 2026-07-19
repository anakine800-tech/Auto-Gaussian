#!/usr/bin/env python3
"""Synthetic offline tests for private-study plan-review-apply migration."""

from __future__ import annotations

import importlib.util
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
MODULE_PATH = ROOT / "scripts" / "private_study_migration.py"
SPEC = importlib.util.spec_from_file_location("auto_g16_private_migration_test", MODULE_PATH)
assert SPEC and SPEC.loader
MIGRATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MIGRATION)


class PrivateStudyMigrationTests(unittest.TestCase):
    def synthetic_tree(self, root: Path) -> tuple[Path, Path, Path]:
        source = root / "source-study"
        source.mkdir(mode=0o700)
        nested = source / "nested"
        nested.mkdir(mode=0o700)
        (nested / "notes.txt").write_text(
            f"local artifact: {source}/outputs/result.json\nexternal tool: /opt/example/tool\n",
            encoding="utf-8",
        )
        (source / "payload.bin").write_bytes(b"\x00\x01synthetic\xff")
        target = root / "Auto-G16-Private-Studies"
        plan_path = root / "migration-plan.json"
        return source, target, plan_path

    def test_plan_and_review_report_hashes_conflicts_and_rewrites_without_apply(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            source, target, plan_path = self.synthetic_tree(root)
            plan = MIGRATION.build_plan(source, target, created_at="2026-07-19T00:00:00+00:00")
            MIGRATION.write_new(plan_path, plan)

            self.assertFalse(target.exists())
            self.assertEqual(plan["file_count"], 2)
            self.assertEqual(plan["conflicts"], [])
            self.assertEqual(plan["rewrite_count"], 1)
            self.assertRegex(plan["source_tree_sha256"], r"^[a-f0-9]{64}$")
            self.assertRegex(plan["planned_tree_sha256"], r"^[a-f0-9]{64}$")
            self.assertEqual(stat.S_IMODE(plan_path.stat().st_mode), 0o600)
            notes = next(item for item in plan["entries"] if item["relative_path"] == "nested/notes.txt")
            actions = {item["action"] for item in notes["absolute_path_references"]}
            self.assertEqual(
                actions,
                {"rewrite_source_root_to_target_root", "review_external_absolute_reference"},
            )
            self.assertEqual(MIGRATION.review_plan(plan_path), plan)
            self.assertTrue(source.exists())

    def test_apply_requires_exact_confirmation_and_then_copies_without_deleting_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            source, target, plan_path = self.synthetic_tree(root)
            plan = MIGRATION.build_plan(source, target, created_at="2026-07-19T00:00:00+00:00")
            MIGRATION.write_new(plan_path, plan)

            with self.assertRaisesRegex(MIGRATION.MigrationError, "confirmation"):
                MIGRATION.apply_plan(plan_path, confirmation="0" * 64, reviewer="fixture-reviewer")
            self.assertFalse(target.exists())

            result = MIGRATION.apply_plan(
                plan_path,
                confirmation=plan["plan_sha256"],
                reviewer="fixture-reviewer",
            )
            self.assertEqual(result["copied_file_count"], 2)
            self.assertFalse(result["source_deleted"])
            self.assertTrue(source.is_dir())
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o700)
            for copied in target.rglob("*"):
                if copied.is_file():
                    self.assertEqual(stat.S_IMODE(copied.stat().st_mode), 0o600)
            copied_text = (target / "nested" / "notes.txt").read_text(encoding="utf-8")
            self.assertIn(str(target / "outputs" / "result.json"), copied_text)
            self.assertNotIn(str(source / "outputs" / "result.json"), copied_text)
            self.assertEqual((target / "payload.bin").read_bytes(), b"\x00\x01synthetic\xff")

    def test_symlinks_non_owner_only_target_conflicts_and_stale_source_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            source, target, plan_path = self.synthetic_tree(root)
            link = source / "linked.txt"
            link.symlink_to(source / "nested" / "notes.txt")
            with self.assertRaisesRegex(MIGRATION.MigrationError, "symlink"):
                MIGRATION.build_plan(source, target)
            link.unlink()

            target.mkdir(mode=0o755)
            os.chmod(target, 0o755)
            with self.assertRaisesRegex(MIGRATION.MigrationError, "0700"):
                MIGRATION.build_plan(source, target)
            os.chmod(target, 0o700)
            (target / "payload.bin").write_bytes(b"conflict")
            conflict_plan = MIGRATION.build_plan(source, target, created_at="2026-07-19T00:00:00+00:00")
            self.assertEqual(conflict_plan["conflicts"], ["payload.bin"])

            (target / "payload.bin").unlink()
            clean_plan = MIGRATION.build_plan(source, target, created_at="2026-07-19T00:00:00+00:00")
            MIGRATION.write_new(plan_path, clean_plan)
            (source / "payload.bin").write_bytes(b"changed")
            with self.assertRaisesRegex(MIGRATION.MigrationError, "stale"):
                MIGRATION.review_plan(plan_path)

    def test_plan_output_inside_checkout_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            source, target, _plan_path = self.synthetic_tree(root)
            plan = MIGRATION.build_plan(source, target)
            with self.assertRaisesRegex(MIGRATION.MigrationError, "outside"):
                MIGRATION.write_new(ROOT / "forbidden-private-plan.json", plan)
            self.assertFalse((ROOT / "forbidden-private-plan.json").exists())


if __name__ == "__main__":
    unittest.main()
