#!/usr/bin/env python3
"""Offline closed-schema runtime configuration tests."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
MODULE_PATH = ROOT / "scripts" / "runtime_config.py"
SPEC = importlib.util.spec_from_file_location("auto_g16_runtime_config_test", MODULE_PATH)
assert SPEC and SPEC.loader
RUNTIME = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNTIME)


class RuntimeConfigTests(unittest.TestCase):
    SKILL_LOCAL_MODULES = (
        ROOT / "skills" / "auto-g16-rtwin-pbs" / "scripts" / "runtime_config.py",
        ROOT / "skills" / "auto-g16-view-rt-win" / "scripts" / "runtime_config.py",
    )

    @staticmethod
    def _load_skill_local(module: Path, config: Path) -> subprocess.CompletedProcess[str]:
        code = (
            "import importlib.util, json; "
            f"s=importlib.util.spec_from_file_location('skill_runtime', {str(module)!r}); "
            "m=importlib.util.module_from_spec(s); s.loader.exec_module(m); "
            "print(json.dumps(m.VALUES, sort_keys=True))"
        )
        environment = os.environ.copy()
        environment["AUTO_G16_RUNTIME_CONFIG"] = str(config)
        return subprocess.run(
            [sys.executable, "-c", code],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_example_matches_closed_schema(self) -> None:
        example = ROOT / "config" / "runtime.example.json"
        value = RUNTIME.load(example)
        self.assertEqual(set(value), RUNTIME.ALLOWED_KEYS)

    def test_duplicate_unknown_and_non_object_json_are_rejected(self) -> None:
        cases = (
            ('{"core_python":"/a","core_python":"/b"}', "duplicate"),
            ('{"unexpected":"value"}', "unknown"),
            ('["not", "an", "object"]', "object"),
        )
        for raw, pattern in cases:
            with self.subTest(raw=raw), self.assertRaisesRegex(RUNTIME.RuntimeConfigError, pattern):
                RUNTIME.parse(raw)

    def test_path_kinds_are_checked_lexically_without_live_access(self) -> None:
        invalid = (
            {"core_python": "relative/python"},
            {"windows_project_root": "GaussianProjects"},
            {"gaussview_exe": r"Gaussian\gview.exe"},
            {"windows_server_config": r"..\server_config"},
        )
        for value in invalid:
            with self.subTest(value=value), self.assertRaisesRegex(
                RUNTIME.RuntimeConfigError,
                r"absolute|relative|traversal",
            ):
                RUNTIME.validate(value)

    def test_load_rejects_leaf_and_caller_controlled_ancestor_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            real = root / "runtime.json"
            real.write_text(json.dumps({"core_python": "/opt/python"}), encoding="utf-8")
            link = root / "runtime-link.json"
            link.symlink_to(real)
            with self.assertRaisesRegex(RUNTIME.RuntimeConfigError, "symlink"):
                RUNTIME.load(link)
            real_parent = root / "real-config-parent"
            real_parent.mkdir()
            nested = real_parent / "runtime.json"
            nested.write_text(json.dumps({"core_python": "/opt/python"}), encoding="utf-8")
            linked_parent = root / "linked-config-parent"
            linked_parent.symlink_to(real_parent, target_is_directory=True)
            with self.assertRaisesRegex(RUNTIME.RuntimeConfigError, "symlink.*ancestor"):
                RUNTIME.load(linked_parent / "runtime.json")
        with self.assertRaisesRegex(RUNTIME.RuntimeConfigError, "absolute"):
            RUNTIME.load(Path("runtime.json"))

    def test_missing_optional_config_remains_compatible_without_following_links(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            self.assertEqual(RUNTIME.load(root / "missing" / "runtime.json", missing_ok=True), {})

    def test_skill_local_loaders_match_strict_closed_contract_offline(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            valid = root / "runtime.json"
            value = {
                "core_python": "/opt/auto-g16/python",
                "windows_project_root": r"C:\\GaussianProjects",
                "windows_server_config": r".config\\auto-g16\\server.json",
            }
            valid.write_text(json.dumps(value), encoding="utf-8")
            for module in self.SKILL_LOCAL_MODULES:
                with self.subTest(module=module.name, case="valid"):
                    result = self._load_skill_local(module, valid)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(json.loads(result.stdout), value)

            invalid_cases = {
                "duplicate": '{"core_python":"/a","core_python":"/b"}',
                "unknown": '{"unknown":"/a"}',
                "relative": '{"core_python":"relative/python"}',
            }
            for label, raw in invalid_cases.items():
                candidate = root / f"{label}.json"
                candidate.write_text(raw, encoding="utf-8")
                for module in self.SKILL_LOCAL_MODULES:
                    with self.subTest(module=module.name, case=label):
                        result = self._load_skill_local(module, candidate)
                        self.assertNotEqual(result.returncode, 0)

            linked = root / "runtime-link.json"
            linked.symlink_to(valid)
            for module in self.SKILL_LOCAL_MODULES:
                with self.subTest(module=module.name, case="symlink"):
                    result = self._load_skill_local(module, linked)
                    self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
