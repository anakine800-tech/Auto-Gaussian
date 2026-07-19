#!/usr/bin/env python3
"""Offline closed-schema runtime configuration tests."""

from __future__ import annotations

import importlib.util
import json
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

    def test_load_rejects_symlink_and_relative_config_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            real = root / "runtime.json"
            real.write_text(json.dumps({"core_python": "/opt/python"}), encoding="utf-8")
            link = root / "runtime-link.json"
            link.symlink_to(real)
            with self.assertRaisesRegex(RUNTIME.RuntimeConfigError, "symlink"):
                RUNTIME.load(link)
        with self.assertRaisesRegex(RUNTIME.RuntimeConfigError, "absolute"):
            RUNTIME.load(Path("runtime.json"))


if __name__ == "__main__":
    unittest.main()
