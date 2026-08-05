#!/usr/bin/env python3
"""Adversarial offline tests for the static Python version contract."""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
MODULE_PATH = ROOT / "scripts" / "audit_python_contract.py"
SPEC = importlib.util.spec_from_file_location("auto_g16_python_contract_test", MODULE_PATH)
assert SPEC and SPEC.loader
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)

SCHEMA_DRAFT202012_TEST_MODULES = (
    "tests.test_direct_durable_submission_journal_schema_draft202012",
    "tests.test_direct_effect_time_replay_ingress_schema_draft202012",
    "tests.test_direct_root_fixed_mutation_schema_draft202012",
    "tests.test_direct_root_mutation_boundary_schema_draft202012",
    "tests.test_direct_root_owner_schema_draft202012",
    "tests.test_direct_trusted_session_schema_draft202012",
    "tests.test_execution_batch_reservation_capability_schema_draft202012",
    "tests.test_legacy_root_authority_schema_draft202012",
    "tests.test_live_approval_effect_time_replay_schema_draft202012",
    "tests.test_local_state_binding_schema_draft202012",
    "tests.test_protected_invocation_schema_draft202012",
    "tests.test_protected_job_runtime_coordinator_schema_draft202012",
    "tests.test_protected_legacy_effect_handoff_schema_draft202012",
    "tests.test_protected_lifecycle_schema_draft202012",
    "tests.test_protected_local_materialization_schema_draft202012",
    "tests.test_protected_owner_consumer_schema_draft202012",
    "tests.test_protected_production_factory_consumer_schema_draft202012",
    "tests.test_protected_production_ingress_schema_draft202012",
    "tests.test_protected_runtime_state_schema_draft202012",
    "tests.test_protected_submit_schema_draft202012",
    "tests.test_resource_effect_time_replay_schema_draft202012",
)

FIXTURE_FILES = (
    "pyproject.toml",
    ".python-version",
    "config/python-environments.json",
    "config/required-checks.json",
    "environment.yml",
    "environment-chem.yml",
    "requirements/chemistry.txt",
    "requirements/chemistry.lock.txt",
    "requirements/schema-validation.txt",
    "requirements/schema-validation.lock.txt",
    ".github/workflows/offline-tests.yml",
) + tuple(
    f"{module.replace('.', '/')}.py"
    for module in SCHEMA_DRAFT202012_TEST_MODULES
)


class PythonContractAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        for relative in FIXTURE_FILES:
            source = ROOT / relative
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        subprocess.run(
            ["git", "-C", str(self.root), "init", "-b", "main"],
            check=True,
            capture_output=True,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def path(self, relative: str) -> Path:
        return self.root / relative

    def replace(self, relative: str, old: str, new: str) -> None:
        path = self.path(relative)
        text = path.read_text(encoding="utf-8")
        self.assertIn(old, text)
        path.write_text(text.replace(old, new, 1), encoding="utf-8")

    def load_registry(self) -> dict[str, object]:
        return json.loads(self.path("config/python-environments.json").read_text(encoding="utf-8"))

    def write_registry(self, value: dict[str, object]) -> None:
        self.path("config/python-environments.json").write_text(
            json.dumps(value), encoding="utf-8"
        )

    def load_required(self) -> dict[str, object]:
        return json.loads(self.path("config/required-checks.json").read_text(encoding="utf-8"))

    def write_required(self, value: dict[str, object]) -> None:
        self.path("config/required-checks.json").write_text(
            json.dumps(value), encoding="utf-8"
        )

    def test_repository_contract_passes_and_derives_exact_supported_minors(self) -> None:
        report = AUDIT.audit(self.root)
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["supported_python_minors"], ["3.11", "3.12", "3.13"])
        self.assertFalse(report["interpreter_availability_verified"])
        self.assertFalse(report["remote_branch_protection_verified"])
        self.assertFalse(report["actual_ci_success_verified"])
        self.assertEqual(
            report["test_only_schema_validation"]["pins"],
            AUDIT.SCHEMA_VALIDATION_PINS,
        )
        self.assertFalse(
            report["test_only_schema_validation"]["core_runtime_dependency"]
        )
        self.assertFalse(
            report["test_only_schema_validation"]["chemistry_runtime_dependency"]
        )
        self.assertEqual(
            AUDIT.SCHEMA_DRAFT202012_TEST_MODULES,
            SCHEMA_DRAFT202012_TEST_MODULES,
        )
        self.assertEqual(
            report["test_only_schema_validation"]["modules"],
            list(SCHEMA_DRAFT202012_TEST_MODULES),
        )

    def test_pyproject_range_expansion_outside_311_to_313_is_contract_drift(self) -> None:
        for value in (">=3.9,<3.14", ">=3.10,<3.14", ">=3.11,<3.15"):
            with self.subTest(value=value):
                original = self.path("pyproject.toml").read_text(encoding="utf-8")
                changed = original.replace(">=3.11,<3.14", value)
                self.path("pyproject.toml").write_text(changed, encoding="utf-8")
                report = AUDIT.audit(self.root)
                self.assertEqual(report["status"], "fail")
                self.path("pyproject.toml").write_text(original, encoding="utf-8")

    def test_unsupported_or_empty_pyproject_range_fails_closed(self) -> None:
        for value in (">=3.11", ">=3.13,<3.13", "~=3.11"):
            with self.subTest(value=value):
                original = self.path("pyproject.toml").read_text(encoding="utf-8")
                changed = original.replace(">=3.11,<3.14", value)
                self.path("pyproject.toml").write_text(changed, encoding="utf-8")
                with self.assertRaises(AUDIT.ContractError):
                    AUDIT.audit(self.root)
                self.path("pyproject.toml").write_text(original, encoding="utf-8")

    def test_ci_matrix_missing_312_or_containing_extra_minor_fails(self) -> None:
        for matrix in ('["3.11", "3.13"]', '["3.11", "3.12", "3.13", "3.14"]'):
            with self.subTest(matrix=matrix):
                original = self.path(".github/workflows/offline-tests.yml").read_text(encoding="utf-8")
                changed = original.replace('["3.11", "3.12", "3.13"]', matrix)
                self.path(".github/workflows/offline-tests.yml").write_text(changed, encoding="utf-8")
                report = AUDIT.audit(self.root)
                self.assertEqual(report["status"], "fail")
                self.assertTrue(any("CI" in item for item in report["errors"]))
                self.path(".github/workflows/offline-tests.yml").write_text(original, encoding="utf-8")

    def test_duplicate_ci_matrix_minor_fails_closed(self) -> None:
        self.replace(
            ".github/workflows/offline-tests.yml",
            '["3.11", "3.12", "3.13"]',
            '["3.11", "3.12", "3.12", "3.13"]',
        )
        with self.assertRaisesRegex(AUDIT.CI_CONTRACT.ContractError, "duplicate matrix"):
            AUDIT.audit(self.root)

    def test_ci_matrix_and_required_context_order_are_exact(self) -> None:
        self.replace(
            ".github/workflows/offline-tests.yml",
            '["3.11", "3.12", "3.13"]',
            '["3.13", "3.12", "3.11"]',
        )
        self.assertTrue(
            any("matrix" in item for item in AUDIT.audit(self.root)["errors"])
        )
        shutil.copy2(
            ROOT / ".github/workflows/offline-tests.yml",
            self.path(".github/workflows/offline-tests.yml"),
        )
        value = self.load_required()
        checks = value["required_checks"]
        assert isinstance(checks, list)
        checks[0], checks[2] = checks[2], checks[0]
        self.write_required(value)
        self.assertTrue(
            any("required Python compatibility contexts" in item for item in AUDIT.audit(self.root)["errors"])
        )

    def test_python_contract_audit_runs_once_outside_matrix(self) -> None:
        workflow = self.path(".github/workflows/offline-tests.yml")
        original = workflow.read_text(encoding="utf-8")
        source_step = """      - name: Audit static Python version contract
        run: python scripts/audit_python_contract.py
"""
        self.assertIn(source_step, original)
        matrix_anchor = """      - name: Compile Python sources
        run: python -m compileall -q scripts skills tests
"""
        moved = original.replace(source_step, "", 1).replace(
            matrix_anchor, source_step + matrix_anchor, 1
        )
        workflow.write_text(moved, encoding="utf-8")
        self.assertTrue(
            any("audit invocation" in item for item in AUDIT.audit(self.root)["errors"])
        )
        duplicated = original.replace(matrix_anchor, source_step + matrix_anchor, 1)
        workflow.write_text(duplicated, encoding="utf-8")
        self.assertTrue(
            any("audit invocation" in item for item in AUDIT.audit(self.root)["errors"])
        )

    def test_core_python_version_and_conda_drift_are_detected(self) -> None:
        self.path(".python-version").write_text("3.13.12\n", encoding="utf-8")
        report = AUDIT.audit(self.root)
        self.assertTrue(any(".python-version" in item for item in report["errors"]))
        self.path(".python-version").write_text("3.13.13\n", encoding="utf-8")
        self.replace("environment.yml", "python=3.13.13", "python=3.13.12")
        report = AUDIT.audit(self.root)
        self.assertTrue(any("core Conda Python" in item for item in report["errors"]))

    def test_registry_core_and_chem_version_drift_are_detected(self) -> None:
        value = self.load_registry()
        value["profiles"]["core"]["python_version"] = "3.13.12"
        self.write_registry(value)
        report = AUDIT.audit(self.root)
        self.assertTrue(any(".python-version" in item for item in report["errors"]))
        self.assertTrue(any("core Conda Python" in item for item in report["errors"]))
        shutil.copy2(ROOT / "config/python-environments.json", self.path("config/python-environments.json"))
        value = self.load_registry()
        value["profiles"]["chem"]["python_version"] = "3.11.14"
        self.write_registry(value)
        report = AUDIT.audit(self.root)
        self.assertTrue(any("chem Conda Python" in item for item in report["errors"]))

    def test_ambiguous_python_version_file_and_duplicate_conda_pin_fail_closed(self) -> None:
        self.path(".python-version").write_text("3.13.13\n3.12.0\n", encoding="utf-8")
        self.assertEqual(AUDIT.audit(self.root)["status"], "fail")
        self.path(".python-version").write_text("3.13.13\n", encoding="utf-8")
        self.replace("environment.yml", "  - pip=26.1.2", "  - pip=26.1.2\n  - python=3.13.13")
        with self.assertRaisesRegex(AUDIT.ContractError, "duplicate dependency"):
            AUDIT.audit(self.root)

    def test_chem_conda_lock_and_ci_selector_drift_are_detected(self) -> None:
        self.replace("environment-chem.yml", "rdkit=2026.03.3", "rdkit=2026.03.2")
        self.assertTrue(any("chem Conda rdkit" in item for item in AUDIT.audit(self.root)["errors"]))
        self.replace("environment-chem.yml", "rdkit=2026.03.2", "rdkit=2026.03.3")
        self.replace("requirements/chemistry.lock.txt", "numpy==2.4.6", "numpy==2.4.5")
        self.assertTrue(any("chemistry lock" in item for item in AUDIT.audit(self.root)["errors"]))
        self.replace("requirements/chemistry.lock.txt", "numpy==2.4.5", "numpy==2.4.6")
        self.replace('.github/workflows/offline-tests.yml', 'python-version: "3.11"', 'python-version: "3.12"')
        self.assertTrue(any("chemistry-dependencies" in item for item in AUDIT.audit(self.root)["errors"]))

    def test_source_archive_selector_must_match_core_minor(self) -> None:
        self.replace('.github/workflows/offline-tests.yml', 'python-version: "3.13"', 'python-version: "3.12"')
        report = AUDIT.audit(self.root)
        self.assertTrue(any("source-archive-release" in item for item in report["errors"]))

    def test_missing_required_context_is_detected(self) -> None:
        value = self.load_required()
        checks = value["required_checks"]
        assert isinstance(checks, list)
        value["required_checks"] = [
            item for item in checks if item["context"] != "python-compatibility (3.12)"
        ]
        self.write_required(value)
        report = AUDIT.audit(self.root)
        self.assertEqual(report["status"], "fail")
        self.assertTrue(any("required Python compatibility contexts" in item for item in report["errors"]))

    def test_duplicate_and_malicious_registry_fields_fail_closed(self) -> None:
        registry_path = self.path("config/python-environments.json")
        original = registry_path.read_text(encoding="utf-8")
        registry_path.write_text(
            original.replace(
                '"schema": "auto-g16-python-environments/1",',
                '"schema": "auto-g16-python-environments/1",\n  "schema": "malicious",',
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(AUDIT.PYTHON_ENVIRONMENT.EnvironmentError, "duplicate"):
            AUDIT.audit(self.root)
        registry_path.write_text(original, encoding="utf-8")
        value = self.load_registry()
        value["profiles"]["chem"]["requirements"] = "../outside.txt"
        self.write_registry(value)
        with self.assertRaisesRegex(AUDIT.PYTHON_ENVIRONMENT.EnvironmentError, "repository-relative"):
            AUDIT.audit(self.root)

    def test_registry_environment_runtime_fallback_and_package_types_fail_closed(self) -> None:
        mutations = (
            ("environment_variable", "PYTHON"),
            ("runtime_config_key", "windows_target"),
            ("fallback", "../python"),
            ("python_version", "3.13"),
        )
        for key, invalid in mutations:
            with self.subTest(key=key):
                value = self.load_registry()
                value["profiles"]["core"][key] = invalid
                self.write_registry(value)
                with self.assertRaises(AUDIT.PYTHON_ENVIRONMENT.EnvironmentError):
                    AUDIT.audit(self.root)
                shutil.copy2(ROOT / "config/python-environments.json", self.path("config/python-environments.json"))
        value = self.load_registry()
        value["profiles"]["chem"]["packages"]["numpy"] = 246
        self.write_registry(value)
        with self.assertRaises(AUDIT.PYTHON_ENVIRONMENT.EnvironmentError):
            AUDIT.audit(self.root)

    def test_duplicate_lock_pin_fails_closed(self) -> None:
        lock = self.path("requirements/chemistry.lock.txt")
        lock.write_text(lock.read_text(encoding="utf-8") + "numpy==2.4.6\n", encoding="utf-8")
        with self.assertRaisesRegex(AUDIT.ContractError, "duplicate requirement"):
            AUDIT.audit(self.root)

    def test_schema_validation_lock_and_entrypoint_are_exact_and_test_only(self) -> None:
        self.replace(
            "requirements/schema-validation.lock.txt",
            "jsonschema==4.26.0",
            "jsonschema==4.25.1",
        )
        report = AUDIT.audit(self.root)
        self.assertTrue(
            any("Schema-validation lock" in item for item in report["errors"])
        )
        shutil.copy2(
            ROOT / "requirements/schema-validation.lock.txt",
            self.path("requirements/schema-validation.lock.txt"),
        )
        entrypoint = self.path("requirements/schema-validation.txt")
        original = entrypoint.read_text(encoding="utf-8")
        entrypoint.write_text(
            original + "jsonschema==4.26.0\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(AUDIT.ContractError, "exactly one active line"):
            AUDIT.audit(self.root)
        entrypoint.write_text(original, encoding="utf-8")
        self.replace(
            "pyproject.toml",
            "dependencies = []",
            'dependencies = ["jsonschema==4.26.0"]',
        )
        with self.assertRaisesRegex(AUDIT.ContractError, "test-only validators"):
            AUDIT.audit(self.root)

    def test_chemistry_requirement_entrypoint_rejects_extra_active_content(self) -> None:
        entrypoint = self.path("requirements/chemistry.txt")
        original = entrypoint.read_text(encoding="utf-8")
        for extra in (
            "requests==2.32.4",
            "-r other.lock.txt",
            "--index-url https://example.invalid/simple",
            "https://example.invalid/package.whl",
        ):
            with self.subTest(extra=extra):
                entrypoint.write_text(original + extra + "\n", encoding="utf-8")
                with self.assertRaisesRegex(AUDIT.ContractError, "exactly one active line"):
                    AUDIT.audit(self.root)
        entrypoint.write_text(original, encoding="utf-8")

    def test_chemistry_requirement_entrypoint_symlink_is_rejected(self) -> None:
        entrypoint = self.path("requirements/chemistry.txt")
        entrypoint.unlink()
        entrypoint.symlink_to("chemistry.lock.txt")
        with self.assertRaisesRegex(AUDIT.ContractError, "symlink"):
            AUDIT.audit(self.root)

    def test_ci_chemistry_install_must_use_the_reviewed_entrypoint(self) -> None:
        self.replace(
            ".github/workflows/offline-tests.yml",
            "python -m pip install --requirement requirements/chemistry.txt",
            "python -m pip install --requirement requirements/chemistry.lock.txt",
        )
        report = AUDIT.audit(self.root)
        self.assertEqual(report["status"], "fail")
        self.assertTrue(any("chemistry job run commands" in item for item in report["errors"]))

    def test_ci_schema_validation_dependency_and_required_gate_are_exact(self) -> None:
        self.replace(
            ".github/workflows/offline-tests.yml",
            (
                "python -m pip install --requirement "
                "requirements/schema-validation.txt"
            ),
            (
                "python -m pip install --requirement "
                "requirements/schema-validation.lock.txt"
            ),
        )
        report = AUDIT.audit(self.root)
        self.assertTrue(
            any("Schema validation CI boundary" in item for item in report["errors"])
        )
        shutil.copy2(
            ROOT / ".github/workflows/offline-tests.yml",
            self.path(".github/workflows/offline-tests.yml"),
        )
        self.replace(
            ".github/workflows/offline-tests.yml",
            'AUTO_G16_REQUIRE_JSONSCHEMA: "1"',
            'AUTO_G16_REQUIRE_JSONSCHEMA: "0"',
        )
        report = AUDIT.audit(self.root)
        self.assertTrue(
            any("fail-closed environment gate" in item for item in report["errors"])
        )

    def test_schema_module_inventory_and_ci_command_drift_fail_closed(self) -> None:
        workflow = self.path(".github/workflows/offline-tests.yml")
        original = workflow.read_text(encoding="utf-8")
        command = AUDIT.SCHEMA_VALIDATION_TEST_COMMAND
        self.assertIn(command, original)
        first, second, *rest = SCHEMA_DRAFT202012_TEST_MODULES
        mutations = (
            command.replace(f" {first}", "", 1),
            command.replace(" -v", " tests.test_unreviewed_schema_draft202012 -v", 1),
            command.replace(f"{first} {second}", f"{second} {first}", 1),
            command.replace(rest[0], "tests.test_replaced_schema_draft202012", 1),
        )
        for changed_command in mutations:
            with self.subTest(changed_command=changed_command):
                workflow.write_text(
                    original.replace(command, changed_command, 1),
                    encoding="utf-8",
                )
                report = AUDIT.audit(self.root)
                self.assertEqual(report["status"], "fail")
                self.assertTrue(
                    any("chemistry job run commands" in item for item in report["errors"])
                )
        workflow.write_text(original, encoding="utf-8")

        missing = self.path(f"{first.replace('.', '/')}.py")
        missing.unlink()
        report = AUDIT.audit(self.root)
        self.assertTrue(
            any("test module inventory" in item for item in report["errors"])
        )
        shutil.copy2(ROOT / f"{first.replace('.', '/')}.py", missing)

        extra = self.path("tests/test_unreviewed_schema_draft202012.py")
        extra.write_text("# unreviewed inventory entry\n", encoding="utf-8")
        report = AUDIT.audit(self.root)
        self.assertTrue(
            any("test module inventory" in item for item in report["errors"])
        )

    def test_schema_validator_cannot_enter_core_or_source_archive_jobs(self) -> None:
        workflow = self.path(".github/workflows/offline-tests.yml")
        original = workflow.read_text(encoding="utf-8")
        source_anchor = (
            "      - name: Audit required-check declarations\n"
            "        run: python scripts/audit_ci_contract.py\n"
        )
        self.assertIn(source_anchor, original)
        workflow.write_text(
            original.replace(
                source_anchor,
                (
                    "      - name: Unreviewed core validator install\n"
                    "        run: python -m pip install --requirement "
                    "requirements/schema-validation.txt\n"
                    + source_anchor
                ),
                1,
            ),
            encoding="utf-8",
        )
        report = AUDIT.audit(self.root)
        self.assertTrue(
            any("Schema validation CI boundary" in item for item in report["errors"])
        )

    def test_ci_chemistry_job_rejects_every_extra_run_command(self) -> None:
        workflow = self.path(".github/workflows/offline-tests.yml")
        original = workflow.read_text(encoding="utf-8")
        anchor = (
            "      - name: Import and report optional chemistry dependencies\n"
            "        run: python -c \"import numpy, PIL, rdkit;"
        )
        self.assertIn(anchor, original)
        for command in (
            "python -m pip --quiet install requests",
            "python -m pip --index-url https://example.invalid/simple install requests",
            "uv pip install requests",
        ):
            with self.subTest(command=command):
                changed = original.replace(
                    anchor,
                    f"      - name: Unreviewed installer\n        run: {command}\n{anchor}",
                    1,
                )
                workflow.write_text(changed, encoding="utf-8")
                report = AUDIT.audit(self.root)
                self.assertEqual(report["status"], "fail")
                self.assertTrue(
                    any("chemistry job run commands" in item for item in report["errors"])
                )
        workflow.write_text(original, encoding="utf-8")

    def test_chemistry_lock_cannot_move_away_from_its_entrypoint(self) -> None:
        moved = self.path("requirements/locks/chemistry.lock.txt")
        moved.parent.mkdir()
        shutil.copy2(self.path("requirements/chemistry.lock.txt"), moved)
        self.replace(
            "pyproject.toml",
            'chemistry-lock = "requirements/chemistry.lock.txt"',
            'chemistry-lock = "requirements/locks/chemistry.lock.txt"',
        )
        value = self.load_registry()
        value["profiles"]["chem"]["requirements"] = "requirements/locks/chemistry.lock.txt"
        self.write_registry(value)
        with self.assertRaisesRegex(AUDIT.ContractError, "share one directory"):
            AUDIT.audit(self.root)

    def test_json_cli_from_subdirectory_reports_limits(self) -> None:
        subdirectory = self.root / "nested" / "path"
        subdirectory.mkdir(parents=True)
        result = subprocess.run(
            [sys.executable, str(MODULE_PATH), "--repo", str(subdirectory), "--json"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "pass")
        self.assertFalse(payload["interpreter_availability_verified"])
        self.assertFalse(payload["remote_branch_protection_verified"])
        self.assertFalse(payload["actual_ci_success_verified"])
        from_cwd = subprocess.run(
            [sys.executable, str(MODULE_PATH), "--json"],
            cwd=subdirectory,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(from_cwd.returncode, 0, from_cwd.stderr)
        self.assertEqual(json.loads(from_cwd.stdout)["status"], "pass")

    def test_cli_exit_codes_distinguish_drift_from_invalid_configuration(self) -> None:
        self.path(".python-version").write_text("3.13.12\n", encoding="utf-8")
        drift = subprocess.run(
            [sys.executable, str(MODULE_PATH), "--repo", str(self.root), "--json"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(drift.returncode, 1)
        self.assertEqual(json.loads(drift.stdout)["status"], "fail")
        self.path(".python-version").write_text("3.13.13\n", encoding="utf-8")
        self.replace("pyproject.toml", ">=3.11,<3.14", ">=3.11")
        invalid = subprocess.run(
            [sys.executable, str(MODULE_PATH), "--repo", str(self.root), "--json"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(invalid.returncode, 2)
        self.assertEqual(json.loads(invalid.stdout)["status"], "error")

    def test_symlinked_contract_path_is_rejected(self) -> None:
        external = self.root.parent / f"{self.root.name}-external-pyproject.toml"
        shutil.copy2(self.path("pyproject.toml"), external)
        self.path("pyproject.toml").unlink()
        self.path("pyproject.toml").symlink_to(external)
        try:
            with self.assertRaisesRegex(AUDIT.ContractError, "symlink"):
                AUDIT.audit(self.root)
        finally:
            external.unlink()

    def test_missing_non_utf8_and_malformed_contract_files_fail_closed(self) -> None:
        cases = (
            ("pyproject.toml", b"[project\n", "invalid pyproject"),
            ("environment.yml", b"name:\tbad\n", "unsupported"),
            (".python-version", b"\xff\n", "could not read"),
        )
        for relative, payload, message in cases:
            with self.subTest(relative=relative):
                original = self.path(relative).read_bytes()
                self.path(relative).write_bytes(payload)
                with self.assertRaisesRegex(AUDIT.ContractError, message):
                    AUDIT.audit(self.root)
                self.path(relative).write_bytes(original)
        self.path("requirements/chemistry.lock.txt").unlink()
        with self.assertRaisesRegex(AUDIT.ContractError, "unavailable"):
            AUDIT.audit(self.root)

    def test_symlinked_workflow_ancestor_is_rejected(self) -> None:
        github = self.path(".github")
        external = self.root / "external-github"
        github.rename(external)
        github.symlink_to(external, target_is_directory=True)
        with self.assertRaisesRegex(AUDIT.ContractError, "symlink"):
            AUDIT.audit(self.root)


if __name__ == "__main__":
    unittest.main()
