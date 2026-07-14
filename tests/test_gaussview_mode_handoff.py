#!/usr/bin/env python3
"""Offline tests for GaussView structure-file handoff."""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).parents[1]
MODULE = ROOT / "skills" / "auto-g16-view-rt-win" / "scripts" / "windows_gaussview.py"
sys.path.insert(0, str(MODULE.parent))
SPEC = importlib.util.spec_from_file_location("windows_gaussview", MODULE)
assert SPEC and SPEC.loader
GVIEW = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GVIEW)


class GaussViewModeHandoffTests(unittest.TestCase):
    def test_scp_destination_uses_configured_target_and_root(self) -> None:
        with mock.patch.object(GVIEW, "TARGET", "rtwin-test"), mock.patch.object(
            GVIEW, "REMOTE_ROOT", r"D:\ReviewedProjects"
        ):
            self.assertEqual(
                GVIEW.scp_destination("project_1", "input.gjf"),
                "rtwin-test:D:/ReviewedProjects/project_1/input.gjf",
            )

    def test_scp_destination_refuses_ambiguous_remote_paths(self) -> None:
        with mock.patch.object(GVIEW, "REMOTE_ROOT", r"D:\Fresh Projects"):
            with self.assertRaisesRegex(ValueError, "without whitespace"):
                GVIEW.scp_destination("project_1", "input.gjf")

    def test_xyz_is_allowed_for_visual_mode_review(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "mode_plus.xyz"
            path.write_text("1\nmode\nH 0 0 0\n", encoding="utf-8")
            self.assertEqual(GVIEW.validate_open_source(path), path.resolve())

    def test_xyz_becomes_audited_non_gaussian_mol_preview(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "mode_plus.xyz"
            path.write_text(
                "5\nmode +0.1\nC 0 0 0\nH 1.09 0 0\nH -1.09 0 0\n"
                "H 0 1.09 0\nH 0 0 1.09\n",
                encoding="utf-8",
            )
            preview, manifest_path, manifest = GVIEW.prepare_visual_source(path)
            self.assertEqual(preview.suffix, ".mol")
            self.assertIsNotNone(manifest_path)
            self.assertEqual(manifest["schema"], "gaussview-visual-preview/1")
            self.assertFalse(manifest["gaussian_input"])
            self.assertFalse(manifest["calculation_ready"])
            self.assertEqual(manifest["atom_count"], 5)
            self.assertEqual(manifest["bond_count"], 4)
            text = preview.read_text(encoding="utf-8")
            self.assertIn("V2000", text)
            self.assertTrue(text.endswith("M  END\n"))
            self.assertNotIn("#p", text.lower())
            self.assertNotIn("%chk", text.lower())
            stored = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(stored["source_sha256"], GVIEW.sha256(path))
            self.assertEqual(stored["preview_sha256"], GVIEW.sha256(preview))

    def test_matching_preview_is_reused_but_stale_preview_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "mode_minus.xyz"
            path.write_text("2\nmode\nH 0 0 0\nH 0 0 0.74\n", encoding="utf-8")
            first = GVIEW.prepare_visual_source(path)
            second = GVIEW.prepare_visual_source(path)
            self.assertEqual(first[0], second[0])
            manifest_path = first[1]
            altered = json.loads(manifest_path.read_text(encoding="utf-8"))
            altered["calculation_ready"] = True
            manifest_path.write_text(json.dumps(altered), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "refusing to overwrite"):
                GVIEW.prepare_visual_source(path)
            manifest_path.write_text(json.dumps(first[2], indent=2) + "\n", encoding="utf-8")
            path.write_text("2\nchanged\nH 0 0 0\nH 0 0 0.75\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "refusing to overwrite"):
                GVIEW.prepare_visual_source(path)

    def test_xyz_atom_count_and_close_contact_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            mismatch = root / "mismatch.xyz"
            mismatch.write_text("2\nmode\nH 0 0 0\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "atom-count mismatch"):
                GVIEW.prepare_visual_source(mismatch)
            close = root / "close.xyz"
            close.write_text("2\nmode\nH 0 0 0\nH 0 0 0.2\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "only 0.2000"):
                GVIEW.prepare_visual_source(close)

    def test_load_probe_rejects_ui_error_and_requires_loaded_true(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unknown file type"):
            GVIEW.validate_load_probe(
                {"loaded": False, "errors": ["CFileAction::LoadFile(). Unknown file type"]}
            )
        with self.assertRaisesRegex(ValueError, "not confirmed"):
            GVIEW.validate_load_probe({"loaded": False, "reason": "not confirmed"})
        GVIEW.validate_load_probe({"loaded": True, "errors": []})

    def test_probe_script_checks_document_and_unknown_file_error(self) -> None:
        text = GVIEW.PROBE_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("ExpectedPath", text)
        self.assertIn("OutputPath", text)
        self.assertIn("Unknown file type", text)
        self.assertIn("document_window_confirmed", text)

    def test_load_probe_is_scheduled_in_interactive_session(self) -> None:
        text = GVIEW.MODULE_TEXT if hasattr(GVIEW, "MODULE_TEXT") else MODULE.read_text()
        self.assertIn("/RU INTERACTIVE", text)
        self.assertIn("wscript.exe", text)
        self.assertIn("run_gaussview_load_probe.vbs", text)
        self.assertIn("stale_result_cleanup", text)
        self.assertIn("check=False", text)

    def test_log_is_not_an_open_structure_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "job.log"
            path.write_text("Normal termination", encoding="utf-8")
            with self.assertRaises(ValueError):
                GVIEW.validate_open_source(path)


if __name__ == "__main__":
    unittest.main()
