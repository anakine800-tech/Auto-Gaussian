#!/usr/bin/env python3
"""Offline contract tests for deterministic local Python selection."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
MODULE_PATH = ROOT / "scripts" / "python_environment.py"
SPEC = importlib.util.spec_from_file_location("auto_g16_python_environment", MODULE_PATH)
assert SPEC and SPEC.loader
ENVIRONMENTS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ENVIRONMENTS)


class PythonEnvironmentTests(unittest.TestCase):
    def test_registry_defines_closed_core_and_chem_profiles(self) -> None:
        registry = ENVIRONMENTS.load_registry()
        self.assertEqual(registry["default_profile"], "core")
        self.assertEqual(set(registry["profiles"]), {"core", "chem"})
        self.assertEqual(registry["profiles"]["core"]["python_version"], "3.13.13")
        self.assertEqual(registry["profiles"]["chem"]["python_version"], "3.11.15")
        self.assertEqual(registry["profiles"]["core"]["packages"], {})
        self.assertEqual(
            registry["profiles"]["chem"]["packages"],
            {"numpy": "2.4.6", "Pillow": "12.3.0", "rdkit": "2026.03.3"},
        )

    def test_lock_and_conda_files_match_the_registry(self) -> None:
        registry = ENVIRONMENTS.load_registry()
        packages = registry["profiles"]["chem"]["packages"]
        lock = (ROOT / "requirements" / "chemistry.lock.txt").read_text(encoding="utf-8")
        chemistry_environment = (ROOT / "environment-chem.yml").read_text(encoding="utf-8")
        for package, version in packages.items():
            self.assertIn(f"{package}=={version}".lower(), lock.lower())
            self.assertIn(f"- {package}={version}".lower(), chemistry_environment.lower())
        self.assertIn(
            f"- python={registry['profiles']['chem']['python_version']}",
            chemistry_environment,
        )
        core_environment = (ROOT / "environment.yml").read_text(encoding="utf-8")
        self.assertIn(
            f"- python={registry['profiles']['core']['python_version']}",
            core_environment,
        )

    def test_environment_variable_precedes_runtime_config(self) -> None:
        registry = ENVIRONMENTS.load_registry()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / "runtime.json"
            config.write_text(json.dumps({"core_python": "/does/not/exist"}), encoding="utf-8")
            selected, source = ENVIRONMENTS.resolve_profile(
                "core",
                registry=registry,
                environ={
                    "AUTO_G16_RUNTIME_CONFIG": str(config),
                    "AUTO_G16_CORE_PYTHON": sys.executable,
                },
                home=root,
            )
        self.assertEqual(selected, Path(sys.executable))
        self.assertEqual(source, "AUTO_G16_CORE_PYTHON")

    def test_probe_reports_executable_pip_and_optional_packages(self) -> None:
        report = ENVIRONMENTS.probe(Path(sys.executable))
        self.assertEqual(report["executable"], str(Path(sys.executable).resolve()))
        self.assertEqual(report["python_version"], sys.version.split()[0])
        self.assertTrue(report["pip"]["path"])
        self.assertEqual(set(report["packages"]), {"numpy", "Pillow", "rdkit"})

    def test_launcher_bootstraps_only_from_absolute_paths(self) -> None:
        launcher = (ROOT / "scripts" / "python").read_text(encoding="utf-8")
        self.assertNotIn("command -v", launcher)
        self.assertNotIn("/usr/bin/env python", launcher)
        self.assertIn("$HOME_DIR/miniforge3/bin/python3", launcher)
        self.assertIn("exec \"$BOOTSTRAP\"", launcher)


if __name__ == "__main__":
    unittest.main()
