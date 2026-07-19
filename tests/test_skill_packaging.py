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
        knowledge = package.package_files(ROOT, "auto-g16-knowledge-base")
        asymmetric = package.package_files(ROOT, "auto-g16-asymmetric-catalysis")
        open_shell = package.package_files(ROOT, "auto-g16-main-group-open-shell")
        conformer = package.package_files(ROOT, "auto-g16-conformer-search")
        rtwin = package.package_files(ROOT, "auto-g16-rtwin-pbs")
        ts_irc = package.package_files(ROOT, "auto-g16-ts-irc")
        ts_seed = package.package_files(ROOT, "auto-g16-ts-seed")
        self.assertEqual(
            reaction[Path("contracts/reaction-workflow/candidate-target-import.schema.json")],
            ROOT / "contracts/reaction-workflow/candidate-target-import.schema.json",
        )
        self.assertEqual(
            knowledge[Path("contracts/knowledge-base/manual-evidence-receipt.schema.json")],
            ROOT / "contracts/knowledge-base/manual-evidence-receipt.schema.json",
        )
        self.assertEqual(
            reaction[Path("contracts/reaction-workflow/mechanism-support-matrix.schema.json")],
            ROOT / "contracts/reaction-workflow/mechanism-support-matrix.schema.json",
        )
        self.assertEqual(
            reaction[Path("contracts/reaction-workflow/mechanism-support-matrix-review.schema.json")],
            ROOT / "contracts/reaction-workflow/mechanism-support-matrix-review.schema.json",
        )
        self.assertEqual(
            reaction[Path("scripts/mechanism_support_matrix.py")],
            ROOT / "skills/auto-g16-reaction-workflow/scripts/mechanism_support_matrix.py",
        )
        self.assertEqual(
            reaction[Path("references/mechanism-support-matrix-contract.md")],
            ROOT / "skills/auto-g16-reaction-workflow/references/mechanism-support-matrix-contract.md",
        )
        self.assertEqual(
            reaction[Path("scripts/scientific_maturity_v2.py")],
            ROOT / "skills/auto-g16-reaction-workflow/scripts/scientific_maturity_v2.py",
        )
        self.assertEqual(
            reaction[Path("references/scientific-maturity-owner-evidence-v2-contract.md")],
            ROOT / "skills/auto-g16-reaction-workflow/references/scientific-maturity-owner-evidence-v2-contract.md",
        )
        self.assertEqual(
            reaction[Path("contracts/reaction-workflow/scientific-evidence-receipt.schema.json")],
            ROOT / "contracts/reaction-workflow/scientific-evidence-receipt.schema.json",
        )
        for contract in (
            "minimum-lineage-handoff-v2.schema.json",
            "ts-freq-result-v2.schema.json",
            "ts-irc-path-acceptance-v2.schema.json",
            "endpoint-structure-review-v2.schema.json",
            "fragment-endpoint-validation-v2.schema.json",
            "checkpoint-geometry-audit-v2.schema.json",
        ):
            with self.subTest(contract=contract):
                installed = Path("contracts/reaction-workflow") / contract
                self.assertEqual(
                    reaction[installed],
                    ROOT / "contracts" / "reaction-workflow" / contract,
                )
        self.assertEqual(
            reaction[Path("contracts/reaction-workflow/v25-integration-review.schema.json")],
            ROOT / "contracts/reaction-workflow/v25-integration-review.schema.json",
        )
        self.assertEqual(
            reaction[Path("scripts/v25_integration.py")],
            ROOT / "skills/auto-g16-reaction-workflow/scripts/v25_integration.py",
        )
        self.assertEqual(
            reaction[Path("references/v25-integration-contract.md")],
            ROOT / "skills/auto-g16-reaction-workflow/references/v25-integration-contract.md",
        )
        self.assertEqual(
            conformer[Path("scripts/conformer_core.py")],
            ROOT / "skills/auto-g16-conformer-search/scripts/conformer_core.py",
        )
        self.assertEqual(
            asymmetric[Path("scripts/validate_asymmetric_contract.py")],
            ROOT / "scripts/validate_asymmetric_contract.py",
        )
        self.assertEqual(
            asymmetric[Path("contracts/asymmetric-catalysis/candidate.schema.json")],
            ROOT / "contracts/asymmetric-catalysis/candidate.schema.json",
        )
        self.assertEqual(
            open_shell[Path("contracts/main-group-open-shell/electronic-state-review.schema.json")],
            ROOT / "contracts/main-group-open-shell/electronic-state-review.schema.json",
        )
        self.assertEqual(
            open_shell[Path("contracts/main-group-open-shell/minimum-two-stage-family-contracts.schema.json")],
            ROOT / "contracts/main-group-open-shell/minimum-two-stage-family-contracts.schema.json",
        )
        self.assertEqual(
            rtwin[Path("contracts/rtwin-pbs/input-draft-review-v2.schema.json")],
            ROOT / "contracts/rtwin-pbs/input-draft-review-v2.schema.json",
        )
        self.assertEqual(
            rtwin[Path("contracts/rtwin-pbs/input-approval-receipt.schema.json")],
            ROOT / "contracts/rtwin-pbs/input-approval-receipt.schema.json",
        )
        self.assertEqual(
            rtwin[Path("contracts/rtwin-pbs/live-submission-approval-v4.schema.json")],
            ROOT / "contracts/rtwin-pbs/live-submission-approval-v4.schema.json",
        )
        self.assertEqual(
            rtwin[Path("contracts/rtwin-pbs/live-submission-approval-v5.schema.json")],
            ROOT / "contracts/rtwin-pbs/live-submission-approval-v5.schema.json",
        )
        self.assertEqual(
            rtwin[Path("contracts/rtwin-pbs/execution-batch.schema.json")],
            ROOT / "contracts/rtwin-pbs/execution-batch.schema.json",
        )
        self.assertEqual(
            rtwin[Path("contracts/rtwin-pbs/execution-batch-review.schema.json")],
            ROOT / "contracts/rtwin-pbs/execution-batch-review.schema.json",
        )
        self.assertEqual(
            ts_irc[Path("contracts/qst-raw-input-syntax-audit.schema.json")],
            ROOT / "skills/auto-g16-ts-irc/contracts/qst-raw-input-syntax-audit.schema.json",
        )
        self.assertEqual(
            ts_irc[Path("contracts/installed-g16-qst-syntax-evidence.schema.json")],
            ROOT / "skills/auto-g16-ts-irc/contracts/installed-g16-qst-syntax-evidence.schema.json",
        )
        self.assertEqual(
            ts_seed[Path("contracts/ts-seed/candidate.schema.json")],
            ROOT / "contracts/ts-seed/candidate.schema.json",
        )
        self.assertEqual(
            ts_seed[Path("contracts/ts-seed/portfolio.schema.json")],
            ROOT / "contracts/ts-seed/portfolio.schema.json",
        )
        self.assertFalse(
            (ROOT / "skills/auto-g16-reaction-workflow/contracts").exists(),
            "deployment contracts must be mapped, not duplicated in the repository Skill",
        )
        self.assertFalse(
            (ROOT / "skills/auto-g16-asymmetric-catalysis/scripts/validate_asymmetric_contract.py").exists(),
            "the specialist validator must remain single-source in the repository",
        )
        self.assertFalse(
            (ROOT / "skills/auto-g16-rtwin-pbs/contracts").exists(),
            "RTwin/PBS contracts must be mapped from the repository root, not duplicated",
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
                "auto-g16-knowledge-base",
                "auto-g16-reaction-literature",
                "auto-g16-asymmetric-catalysis",
                "auto-g16-conformer-search",
                "auto-g16-main-group-open-shell",
                "auto-g16-ts-irc",
                "auto-g16-ts-seed",
                "auto-g16-rtwin-pbs",
                "auto-g16-view-rt-win",
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
            dag = installed / "auto-g16-reaction-workflow/scripts/calculation_dag.py"
            dag_help = subprocess.run(
                [sys.executable, str(dag), "--help"],
                cwd=root,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(dag_help.returncode, 0, dag_help.stdout + dag_help.stderr)
            self.assertIn("build-plan", dag_help.stdout)
            self.assertIn("build-node-update", dag_help.stdout)
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
            matrix = installed / "auto-g16-reaction-workflow/scripts/mechanism_support_matrix.py"
            matrix_help = subprocess.run(
                [sys.executable, str(matrix), "--help"],
                cwd=root,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(matrix_help.returncode, 0, matrix_help.stdout + matrix_help.stderr)
            self.assertIn("mechanism-support matrix", matrix_help.stdout)
            self.assertTrue(
                (installed / "auto-g16-reaction-workflow/contracts/reaction-workflow/mechanism-support-matrix.schema.json").is_file()
            )
            self.assertTrue(
                (installed / "auto-g16-reaction-workflow/contracts/reaction-workflow/mechanism-support-matrix-review.schema.json").is_file()
            )
            maturity = installed / "auto-g16-reaction-workflow/scripts/scientific_maturity.py"
            maturity_help = subprocess.run(
                [sys.executable, str(maturity), "--help"],
                cwd=root,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(maturity_help.returncode, 0, maturity_help.stdout + maturity_help.stderr)
            self.assertIn("authorize-action", maturity_help.stdout)
            self.assertTrue(
                (installed / "auto-g16-reaction-workflow/contracts/reaction-workflow/scientific-maturity-gate.schema.json").is_file()
            )
            maturity_v2 = installed / "auto-g16-reaction-workflow/scripts/scientific_maturity_v2.py"
            maturity_v2_help = subprocess.run(
                [sys.executable, str(maturity_v2), "--help"],
                cwd=root,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(maturity_v2_help.returncode, 0, maturity_v2_help.stdout + maturity_v2_help.stderr)
            self.assertIn("build-evidence-receipt", maturity_v2_help.stdout)
            self.assertIn("build-action", maturity_v2_help.stdout)
            for schema_name in (
                "scientific-maturity-review-v2.schema.json", "scientific-evidence-receipt.schema.json",
                "scientific-maturity-gate-v2.schema.json", "scientific-maturity-action-v2.schema.json",
            ):
                self.assertTrue(
                    (installed / "auto-g16-reaction-workflow/contracts/reaction-workflow" / schema_name).is_file()
                )
            v25 = installed / "auto-g16-reaction-workflow/scripts/v25_integration.py"
            v25_help = subprocess.run(
                [sys.executable, str(v25), "--help"],
                cwd=root,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(v25_help.returncode, 0, v25_help.stdout + v25_help.stderr)
            self.assertIn("finalize", v25_help.stdout)
            self.assertIn("validate", v25_help.stdout)
            self.assertTrue(
                (installed / "auto-g16-reaction-workflow/contracts/reaction-workflow/v25-integration-review.schema.json").is_file()
            )
            conformer = installed / "auto-g16-conformer-search/scripts/conformer_search.py"
            conformer_help = subprocess.run(
                [sys.executable, str(conformer), "--help"], cwd=root, text=True, capture_output=True, check=False,
            )
            self.assertEqual(conformer_help.returncode, 0, conformer_help.stdout + conformer_help.stderr)
            self.assertIn("validate-handoff", conformer_help.stdout)
            ts_seed = installed / "auto-g16-ts-seed/scripts/ts_seed.py"
            ts_seed_help = subprocess.run(
                [sys.executable, str(ts_seed), "--help"], cwd=root, text=True, capture_output=True, check=False,
            )
            self.assertEqual(ts_seed_help.returncode, 0, ts_seed_help.stdout + ts_seed_help.stderr)
            self.assertIn("build-candidate", ts_seed_help.stdout)
            self.assertIn("build-portfolio", ts_seed_help.stdout)
            manual = installed / "auto-g16-knowledge-base/scripts/manual_evidence.py"
            manual_help = subprocess.run(
                [sys.executable, str(manual), "--help"],
                cwd=root,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(manual_help.returncode, 0, manual_help.stdout + manual_help.stderr)
            self.assertIn("build-receipt", manual_help.stdout)
            self.assertTrue(
                (installed / "auto-g16-knowledge-base/contracts/knowledge-base/manual-evidence-receipt.schema.json").is_file()
            )
            self.assertTrue(
                (installed / "auto-g16-ts-irc/contracts/qst-raw-input-syntax-audit.schema.json").is_file()
            )
            self.assertTrue(
                (installed / "auto-g16-ts-irc/contracts/installed-g16-qst-syntax-evidence.schema.json").is_file()
            )
            owner_loader_smoke = "\n".join(
                (
                    "import importlib.util, pathlib, sys",
                    "root = pathlib.Path(sys.argv[1])",
                    "for name, relative in ((\"ts\", \"auto-g16-ts-irc/scripts/ts_irc.py\"), (\"pbs\", \"auto-g16-rtwin-pbs/scripts/gaussian_rtwin_pbs.py\")):",
                    "    path = root / relative",
                    "    sys.path.insert(0, str(path.parent))",
                    "    spec = importlib.util.spec_from_file_location(f\"packaged_{name}\", path)",
                    "    module = importlib.util.module_from_spec(spec)",
                    "    spec.loader.exec_module(module)",
                    "    owner = module._load_scientific_maturity()",
                    "    assert owner.GATE_SCHEMA == \"gaussian-scientific-maturity-gate/1\"",
                    "print(\"deployed-owner-loaders-ok\")",
                )
            )
            owner_loaders = subprocess.run(
                [sys.executable, "-c", owner_loader_smoke, str(installed)],
                cwd=root,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(owner_loaders.returncode, 0, owner_loaders.stdout + owner_loaders.stderr)
            self.assertIn("deployed-owner-loaders-ok", owner_loaders.stdout)
            runtime_loader_smoke = "\n".join(
                (
                    "import importlib.util, os, pathlib, sys, tempfile",
                    "installed = pathlib.Path(sys.argv[1])",
                    "for name in ('auto-g16-rtwin-pbs', 'auto-g16-view-rt-win'):",
                    "    path = installed / name / 'scripts/runtime_config.py'",
                    "    with tempfile.TemporaryDirectory() as temporary:",
                    "        base = pathlib.Path(temporary).resolve()",
                    "        missing = base / 'missing/runtime.json'",
                    "        os.environ['AUTO_G16_RUNTIME_CONFIG'] = str(missing)",
                    "        spec = importlib.util.spec_from_file_location('packaged_runtime_' + name, path)",
                    "        module = importlib.util.module_from_spec(spec)",
                    "        spec.loader.exec_module(module)",
                    "        assert module.VALUES == {} and module.load() == {}",
                    "        real = base / 'real'",
                    "        real.mkdir()",
                    "        linked = base / 'linked'",
                    "        linked.symlink_to(real, target_is_directory=True)",
                    "        os.environ['AUTO_G16_RUNTIME_CONFIG'] = str(linked / 'runtime.json')",
                    "        try:",
                    "            module.load()",
                    "        except ValueError as exc:",
                    "            assert 'symlink or non-directory' in str(exc)",
                    "        else:",
                    "            raise AssertionError('ancestor symlink was accepted')",
                    "print('deployed-runtime-loaders-ok')",
                )
            )
            runtime_loaders = subprocess.run(
                [sys.executable, "-c", runtime_loader_smoke, str(installed)],
                cwd=root,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(runtime_loaders.returncode, 0, runtime_loaders.stdout + runtime_loaders.stderr)
            self.assertIn("deployed-runtime-loaders-ok", runtime_loaders.stdout)
            rtwin_cli = installed / "auto-g16-rtwin-pbs/scripts/gaussian_rtwin_pbs.py"
            rtwin_help = subprocess.run(
                [sys.executable, str(rtwin_cli), "--help"],
                cwd=root,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(rtwin_help.returncode, 0, rtwin_help.stdout + rtwin_help.stderr)
            self.assertIn("finalize-input-review", rtwin_help.stdout)
            self.assertIn("build-input-approval", rtwin_help.stdout)
            self.assertIn("validate-input-approval", rtwin_help.stdout)
            for name in (
                "input-draft-review-v2.schema.json",
                "input-approval-receipt.schema.json",
                "live-submission-approval-v4.schema.json",
                "live-submission-approval-v5.schema.json",
                "execution-batch.schema.json",
                "execution-batch-review.schema.json",
            ):
                deployed_schema = installed / "auto-g16-rtwin-pbs/contracts/rtwin-pbs" / name
                source_schema = ROOT / "contracts/rtwin-pbs" / name
                self.assertTrue(deployed_schema.is_file())
                self.assertEqual(deployed_schema.read_bytes(), source_schema.read_bytes())
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
