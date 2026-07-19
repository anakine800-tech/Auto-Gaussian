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
from unittest import mock


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
            self.assertFalse(result["partial_copy"])
            self.assertFalse(result["manual_partial_copy_review_required"])
            self.assertFalse(result["automatic_rollback_deletion"])
            receipt_path = target / result["destination_receipt"]["relative_path"]
            self.assertTrue(receipt_path.is_file())
            self.assertEqual(MIGRATION.file_sha256(receipt_path) if hasattr(MIGRATION, "file_sha256") else __import__("hashlib").sha256(receipt_path.read_bytes()).hexdigest(), result["destination_receipt"]["sha256"])
            receipt = json.loads(receipt_path.read_text())
            self.assertEqual({item["relative_path"] for item in receipt["entries"]}, {"nested/notes.txt", "payload.bin"})
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

    def test_target_ancestor_swap_is_rejected_by_descriptor_open(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            source, target, plan_path = self.synthetic_tree(root)
            target.mkdir(mode=0o700)
            (target / "nested").mkdir(mode=0o700)
            plan = MIGRATION.build_plan(source, target, created_at="2026-07-19T00:00:00+00:00")
            MIGRATION.write_new(plan_path, plan)
            original_preflight = MIGRATION._preflight_destination_conflicts
            outside = root / "outside"
            outside.mkdir(mode=0o700)

            def swap_after_preflight(target_fd: int | None, entries: list[dict[str, object]]) -> None:
                original_preflight(target_fd, entries)
                os.rename(target / "nested", target / "nested-original")
                (target / "nested").symlink_to(outside, target_is_directory=True)

            with mock.patch.object(
                MIGRATION,
                "_preflight_destination_conflicts",
                side_effect=swap_after_preflight,
            ), self.assertRaisesRegex(MIGRATION.MigrationError, "partial copy.*manual inspection"):
                MIGRATION.apply_plan(
                    plan_path,
                    confirmation=plan["plan_sha256"],
                    reviewer="fixture-reviewer",
                )
            self.assertFalse((outside / "notes.txt").exists())
            self.assertFalse((target / "payload.bin").exists())

    def test_source_leaf_symlink_after_preflight_is_not_followed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            source, target, plan_path = self.synthetic_tree(root)
            plan = MIGRATION.build_plan(source, target, created_at="2026-07-19T00:00:00+00:00")
            MIGRATION.write_new(plan_path, plan)
            original_preflight = MIGRATION._preflight_destination_conflicts
            decoy = root / "decoy.bin"
            decoy.write_bytes(b"must-not-be-copied")

            def swap_leaf_after_preflight(target_fd: int | None, entries: list[dict[str, object]]) -> None:
                original_preflight(target_fd, entries)
                os.rename(source / "payload.bin", source / "payload-original.bin")
                (source / "payload.bin").symlink_to(decoy)

            with mock.patch.object(
                MIGRATION,
                "_preflight_destination_conflicts",
                side_effect=swap_leaf_after_preflight,
            ), self.assertRaisesRegex(MIGRATION.MigrationError, "partial copy.*manual inspection"):
                MIGRATION.apply_plan(
                    plan_path,
                    confirmation=plan["plan_sha256"],
                    reviewer="fixture-reviewer",
                )
            self.assertTrue((target / "nested" / "notes.txt").is_file())
            self.assertFalse((target / "payload.bin").exists())
            self.assertEqual(decoy.read_bytes(), b"must-not-be-copied")

    def test_destination_leaf_symlink_after_preflight_is_not_followed_or_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            source, target, plan_path = self.synthetic_tree(root)
            target.mkdir(mode=0o700)
            (target / "nested").mkdir(mode=0o700)
            plan = MIGRATION.build_plan(source, target, created_at="2026-07-19T00:00:00+00:00")
            MIGRATION.write_new(plan_path, plan)
            original_preflight = MIGRATION._preflight_destination_conflicts
            decoy = root / "destination-decoy.txt"
            decoy.write_text("unchanged", encoding="utf-8")

            def add_leaf_symlink(target_fd: int | None, entries: list[dict[str, object]]) -> None:
                original_preflight(target_fd, entries)
                (target / "nested" / "notes.txt").symlink_to(decoy)

            with mock.patch.object(
                MIGRATION,
                "_preflight_destination_conflicts",
                side_effect=add_leaf_symlink,
            ), self.assertRaisesRegex(MIGRATION.MigrationError, "partial copy.*manual inspection"):
                MIGRATION.apply_plan(
                    plan_path,
                    confirmation=plan["plan_sha256"],
                    reviewer="fixture-reviewer",
                )
            self.assertEqual(decoy.read_text(encoding="utf-8"), "unchanged")
            self.assertTrue((target / "nested" / "notes.txt").is_symlink())
            self.assertFalse((target / "payload.bin").exists())

    def test_conflict_appearing_after_review_fails_before_any_copy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            source, target, plan_path = self.synthetic_tree(root)
            plan = MIGRATION.build_plan(source, target, created_at="2026-07-19T00:00:00+00:00")
            MIGRATION.write_new(plan_path, plan)
            original_preflight = MIGRATION._preflight_source_entries

            def add_conflict_after_source_preflight(*args: object, **kwargs: object) -> object:
                result = original_preflight(*args, **kwargs)
                target.mkdir(mode=0o700)
                (target / "payload.bin").write_bytes(b"existing")
                return result

            with mock.patch.object(
                MIGRATION,
                "_preflight_source_entries",
                side_effect=add_conflict_after_source_preflight,
            ), self.assertRaisesRegex(MIGRATION.MigrationError, "conflicts appeared"):
                MIGRATION.apply_plan(
                    plan_path,
                    confirmation=plan["plan_sha256"],
                    reviewer="fixture-reviewer",
                )
            self.assertFalse((target / "nested" / "notes.txt").exists())
            self.assertEqual((target / "payload.bin").read_bytes(), b"existing")

    def test_full_source_preflight_failure_creates_no_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            source, target, plan_path = self.synthetic_tree(root)
            plan = MIGRATION.build_plan(source, target, created_at="2026-07-19T00:00:00+00:00")
            MIGRATION.write_new(plan_path, plan)
            (source / "payload.bin").write_bytes(b"preflight-drift")

            with mock.patch.object(MIGRATION, "review_plan", return_value=plan), self.assertRaisesRegex(
                MIGRATION.MigrationError, "source size bytes changed"
            ):
                MIGRATION.apply_plan(
                    plan_path,
                    confirmation=plan["plan_sha256"],
                    reviewer="fixture-reviewer",
                )
            self.assertFalse(target.exists())

    def test_reserved_destination_receipt_conflicts_before_any_copy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve(); source, target, plan_path = self.synthetic_tree(root)
            plan = MIGRATION.build_plan(source, target, created_at="2026-07-19T00:00:00+00:00")
            MIGRATION.write_new(plan_path, plan)
            target.mkdir(mode=0o700)
            receipt = target / MIGRATION.DESTINATION_RECEIPT_NAME
            receipt.write_bytes(b"immutable-old-receipt")
            with mock.patch.object(MIGRATION, "review_plan", return_value=plan), self.assertRaisesRegex(
                MIGRATION.MigrationError, "conflicts appeared"
            ):
                MIGRATION.apply_plan(plan_path, confirmation=plan["plan_sha256"], reviewer="fixture-reviewer")
            self.assertEqual(receipt.read_bytes(), b"immutable-old-receipt")
            self.assertFalse((target / "nested" / "notes.txt").exists())
            self.assertFalse((target / "payload.bin").exists())

    def test_reserved_source_receipt_name_blocks_plan_and_apply_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve(); source, target, plan_path = self.synthetic_tree(root)
            plan = MIGRATION.build_plan(source, target, created_at="2026-07-19T00:00:00+00:00")
            MIGRATION.write_new(plan_path, plan)
            reserved = source / MIGRATION.DESTINATION_RECEIPT_NAME
            reserved.write_bytes(b"source collision")
            with self.assertRaisesRegex(MIGRATION.MigrationError, "reserved destination receipt"):
                MIGRATION.build_plan(source, target)
            with self.assertRaisesRegex(MIGRATION.MigrationError, "reserved destination receipt"):
                MIGRATION.apply_plan(plan_path, confirmation=plan["plan_sha256"], reviewer="fixture-reviewer")
            self.assertFalse(target.exists())

    def test_apply_streams_large_and_many_files_without_full_source_reads(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve(); source, target, plan_path = self.synthetic_tree(root)
            large = source / "large.chk"; large.write_bytes((b"0123456789abcdef" * 200_000) + b"tail")
            many = source / "many"; many.mkdir()
            for index in range(32):
                (many / f"entry-{index:02d}.txt").write_text(f"{source}/artifact-{index}\n", encoding="utf-8")
            plan = MIGRATION.build_plan(source, target, created_at="2026-07-19T00:00:00+00:00")
            MIGRATION.write_new(plan_path, plan)
            original_read = MIGRATION._read_source_at
            read_requests: list[int] = []
            original_os_read = MIGRATION.os.read

            def guarded_full_read(fd: int, relative: Path) -> bytes:
                if relative.as_posix() != MIGRATION.DESTINATION_RECEIPT_NAME:
                    raise AssertionError("apply attempted an unbounded whole-file source read")
                return original_read(fd, relative)

            def observed_read(fd: int, size: int) -> bytes:
                read_requests.append(size)
                return original_os_read(fd, size)

            with mock.patch.object(MIGRATION, "review_plan", return_value=plan), mock.patch.object(
                MIGRATION, "_read_source_at", side_effect=guarded_full_read
            ), mock.patch.object(MIGRATION.os, "read", side_effect=observed_read):
                result = MIGRATION.apply_plan(plan_path, confirmation=plan["plan_sha256"], reviewer="fixture-reviewer")
            self.assertEqual(result["copied_file_count"], plan["file_count"])
            self.assertLessEqual(max(read_requests), MIGRATION.STREAM_CHUNK_SIZE)
            self.assertEqual((target / "large.chk").read_bytes(), large.read_bytes())
            self.assertIn(str(target), (target / "many" / "entry-00.txt").read_text())


if __name__ == "__main__":
    unittest.main()
