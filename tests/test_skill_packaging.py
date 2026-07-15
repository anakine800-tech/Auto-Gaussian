#!/usr/bin/env python3
"""Offline tests for fail-closed named-Skill deployment packages."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import skill_package as package  # noqa: E402
import sync_named_skill as sync  # noqa: E402


def load_adapter():
    path = ROOT / "skills" / "auto-g16-reaction-workflow" / "scripts" / "calculation_artifacts.py"
    spec = importlib.util.spec_from_file_location("packaging_test_calculation_artifacts", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ADAPTER = load_adapter()


class SkillPackagingTests(unittest.TestCase):
    def test_package_manifests_map_authoritative_contracts_without_repository_duplicates(self) -> None:
        reaction = package.package_files(ROOT, "auto-g16-reaction-workflow")
        asymmetric = package.package_files(ROOT, "auto-g16-asymmetric-catalysis")
        self.assertEqual(
            reaction[Path("contracts/reaction-workflow/candidate-target-import.schema.json")],
            ROOT / "contracts/reaction-workflow/candidate-target-import.schema.json",
        )
        self.assertEqual(
            asymmetric[Path("scripts/validate_asymmetric_contract.py")],
            ROOT / "scripts/validate_asymmetric_contract.py",
        )
        self.assertEqual(
            asymmetric[Path("contracts/asymmetric-catalysis/candidate.schema.json")],
            ROOT / "contracts/asymmetric-catalysis/candidate.schema.json",
        )
        self.assertFalse(
            (ROOT / "skills/auto-g16-reaction-workflow/contracts").exists(),
            "deployment contracts must be mapped, not duplicated in the repository Skill",
        )
        self.assertFalse(
            (ROOT / "skills/auto-g16-asymmetric-catalysis/scripts/validate_asymmetric_contract.py").exists(),
            "the specialist validator must remain single-source in the repository",
        )

    def test_dry_run_does_not_write_and_apply_refuses_installed_extras(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            installed = Path(temporary) / "skills"
            result = sync.sync_skill(
                ROOT, installed, "auto-g16-reaction-workflow", apply=False, confirmed=False
            )
            self.assertTrue(result["missing"])
            first = result["missing"][0]
            self.assertRegex(result["details"][first]["sha256"], r"^[a-f0-9]{64}$")
            self.assertGreater(result["details"][first]["size_bytes"], 0)
            self.assertFalse(installed.exists())
            with self.assertRaisesRegex(package.PackageError, "exact current dry-run"):
                sync.sync_skill(
                    ROOT, installed, "auto-g16-reaction-workflow", apply=True,
                    confirmed=True, plan_sha256="0" * 64,
                )
            self.assertFalse(installed.exists())
            installed.mkdir()
            applied = sync.sync_skill(
                ROOT, installed, "auto-g16-reaction-workflow", apply=True,
                confirmed=True, plan_sha256=result["plan_sha256"],
            )
            self.assertTrue(applied["applied"])
            extra = installed / "auto-g16-reaction-workflow" / "unexpected.txt"
            extra.write_text("do not delete implicitly\n", encoding="utf-8")
            with self.assertRaisesRegex(package.PackageError, "extra files"):
                drifted = sync.sync_skill(
                    ROOT, installed, "auto-g16-reaction-workflow", apply=False, confirmed=False
                )
                sync.sync_skill(
                    ROOT, installed, "auto-g16-reaction-workflow", apply=True,
                    confirmed=True, plan_sha256=drifted["plan_sha256"],
                )
            self.assertEqual(extra.read_text(encoding="utf-8"), "do not delete implicitly\n")

    def test_apply_refuses_symlink_install_root_and_invalid_skill_name(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            real = root / "real-skills"
            real.mkdir()
            linked = root / "linked-skills"
            try:
                linked.symlink_to(real, target_is_directory=True)
            except OSError:
                self.skipTest("symlinks unavailable")
            with self.assertRaisesRegex(package.PackageError, "installed root.*symlink"):
                dry = sync.sync_skill(
                    ROOT, linked, "auto-g16-reaction-workflow", apply=False, confirmed=False
                )
                sync.sync_skill(
                    ROOT, linked, "auto-g16-reaction-workflow", apply=True,
                    confirmed=True, plan_sha256=dry["plan_sha256"],
                )
            with self.assertRaisesRegex(package.PackageError, "valid auto-g16"):
                package.package_files(ROOT, "auto-g16-../../escape")

    def test_deployed_named_skills_import_and_validate_with_packaged_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            installed = root / "skills"
            installed.mkdir()
            names = (
                "auto-g16-reaction-workflow",
                "auto-g16-asymmetric-catalysis",
                "auto-g16-ts-irc",
                "auto-g16-rtwin-pbs",
            )
            for name in names:
                dry = sync.sync_skill(ROOT, installed, name, apply=False, confirmed=False)
                result = sync.sync_skill(
                    ROOT, installed, name, apply=True, confirmed=True,
                    plan_sha256=dry["plan_sha256"],
                )
                self.assertTrue(result["applied"])
            checked = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/check_skill_sync.py"),
                    "--repo-root", str(ROOT),
                    "--installed-root", str(installed),
                    *[item for name in names for item in ("--skill", name)],
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
            adapter = installed / "auto-g16-reaction-workflow/scripts/calculation_artifacts.py"
            help_result = subprocess.run(
                [sys.executable, str(adapter), "--help"],
                cwd=root,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(help_result.returncode, 0, help_result.stdout + help_result.stderr)
            self.assertIn("export-targets", help_result.stdout)
            observation = ADAPTER._finalize(
                {
                    "schema": ADAPTER.SANITIZED_JOB_SCHEMA,
                    "observation_id": "packaged_job_observation",
                    "source_job_sha256": "1" * 64,
                    "input_sha256": "2" * 64,
                    "status": "completed",
                    "last_inspection_state": "completed",
                    "redacted_fields": ["job_id", "remote_workdir"],
                    "calculation_ready": False,
                    "no_submission_authorization": True,
                }
            )
            artifact = root / "sanitized-job-observation.json"
            artifact.write_bytes(ADAPTER.rw.canonical_bytes(observation))
            validation = subprocess.run(
                [sys.executable, str(adapter), "validate", str(artifact)],
                cwd=root,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(validation.returncode, 0, validation.stdout + validation.stderr)
            summary = json.loads(validation.stdout)
            self.assertEqual(summary["schema"], ADAPTER.SANITIZED_JOB_SCHEMA)
            self.assertFalse(summary["live_actions"])

    def test_manifest_and_target_paths_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skill = root / "skills/auto-g16-fixture"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text("fixture\n", encoding="utf-8")
            source = root / "contract.json"
            source.write_text("{}\n", encoding="utf-8")
            manifest = skill / package.MANIFEST_NAME
            invalid_documents = (
                '{"schema":"auto-g16-named-skill-package/1","schema":"duplicate","skill":"auto-g16-fixture","include":[]}',
                json.dumps({
                    "schema": package.MANIFEST_SCHEMA,
                    "skill": "auto-g16-fixture",
                    "include": [{"source": "../escape", "target": "contracts/value.json"}],
                }),
                json.dumps({
                    "schema": package.MANIFEST_SCHEMA,
                    "skill": "auto-g16-fixture",
                    "include": [{"source": "contract.json", "target": "SKILL.md"}],
                }),
            )
            for document in invalid_documents:
                with self.subTest(document=document):
                    manifest.write_text(document + "\n", encoding="utf-8")
                    with self.assertRaises(package.PackageError):
                        package.package_files(root, "auto-g16-fixture")
            link = root / "linked-contract.json"
            try:
                link.symlink_to(source)
            except OSError:
                return
            manifest.write_text(
                json.dumps({
                    "schema": package.MANIFEST_SCHEMA,
                    "skill": "auto-g16-fixture",
                    "include": [{"source": "linked-contract.json", "target": "contracts/value.json"}],
                }) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(package.PackageError, "symlink"):
                package.package_files(root, "auto-g16-fixture")


if __name__ == "__main__":
    unittest.main()
