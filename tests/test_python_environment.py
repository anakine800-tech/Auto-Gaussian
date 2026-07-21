#!/usr/bin/env python3
"""Offline contract tests for deterministic local Python selection."""

from __future__ import annotations

import importlib.util
import json
import shutil
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

    def test_registry_rejects_unknown_top_level_and_profile_fields(self) -> None:
        registry = ENVIRONMENTS.load_registry()
        for target, key in ((registry, "extra"), (registry["profiles"]["core"], "extra")):
            with self.subTest(key=key, target=set(target)):
                changed = json.loads(json.dumps(registry))
                destination = changed if target is registry else changed["profiles"]["core"]
                destination[key] = "forbidden"
                with tempfile.TemporaryDirectory() as temporary:
                    path = Path(temporary) / "registry.json"
                    path.write_text(json.dumps(changed), encoding="utf-8")
                    with self.assertRaisesRegex(ENVIRONMENTS.EnvironmentError, "closed"):
                        ENVIRONMENTS.load_registry(path)

    def test_registry_rejects_duplicate_json_keys(self) -> None:
        raw = (ROOT / "config" / "python-environments.json").read_text(encoding="utf-8")
        raw = raw.replace(
            '"default_profile": "core",',
            '"default_profile": "core",\n  "default_profile": "chem",',
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "registry.json"
            path.write_text(raw, encoding="utf-8")
            with self.assertRaisesRegex(ENVIRONMENTS.EnvironmentError, "duplicate JSON key"):
                ENVIRONMENTS.load_registry(path)

    def test_duplicate_json_key_error_escapes_control_characters(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "registry.json"
            path.write_text('{"bad\\nkey": 1, "bad\\nkey": 2}', encoding="utf-8")
            with self.assertRaises(ENVIRONMENTS.EnvironmentError) as caught:
                ENVIRONMENTS.load_registry(path)
        self.assertNotIn("bad\nkey", str(caught.exception))
        self.assertIn(r"bad\nkey", str(caught.exception))

    def test_registry_rejects_invalid_v1_field_semantics(self) -> None:
        mutations = (
            ("core", "python_version", "3.13"),
            ("core", "environment_variable", "PYTHON"),
            ("core", "runtime_config_key", "rdkit_python"),
            ("core", "fallback", "../python"),
            ("core", "fallback", "~/bin/\npython"),
            ("core", "requirements", "requirements/core.txt"),
            ("chem", "requirements", "../chemistry.lock.txt"),
            ("chem", "requirements", "requirements/化学.txt"),
        )
        original = ENVIRONMENTS.load_registry()
        for profile, key, value in mutations:
            with self.subTest(profile=profile, key=key):
                changed = json.loads(json.dumps(original))
                changed["profiles"][profile][key] = value
                with tempfile.TemporaryDirectory() as temporary:
                    path = Path(temporary) / "registry.json"
                    path.write_text(json.dumps(changed), encoding="utf-8")
                    with self.assertRaises(ENVIRONMENTS.EnvironmentError):
                        ENVIRONMENTS.load_registry(path)

    def test_registry_rejects_symlink_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            regular = root / "regular.json"
            shutil.copy2(ROOT / "config" / "python-environments.json", regular)
            alias = root / "alias.json"
            alias.symlink_to(regular)
            with self.assertRaisesRegex(ENVIRONMENTS.EnvironmentError, "non-symlink"):
                ENVIRONMENTS.load_registry(alias)

    def test_environment_variable_precedes_runtime_config(self) -> None:
        registry = ENVIRONMENTS.load_registry()
        with tempfile.TemporaryDirectory() as temporary:
            # Runtime configuration intentionally rejects every symlinked
            # ancestor; macOS exposes /var as an OS alias, so use its canonical
            # synthetic fixture path rather than weakening the production gate.
            root = Path(temporary).resolve()
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
