#!/usr/bin/env python3
"""Offline tests for the TS–Freq–IRC skill; no network or scheduler access."""
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
MODULE = ROOT / "skills" / "gaussian-ts-irc" / "scripts" / "ts_irc.py"
SPEC = importlib.util.spec_from_file_location("ts_irc", MODULE)
assert SPEC and SPEC.loader
TS = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(TS)

LOG = """\
 Optimization completed.
 -- Stationary point found.
 Standard orientation:
 ---------------------------------------------------------------------
 Center     Atomic      Atomic             Coordinates (Angstroms)
 Number     Number       Type             X           Y           Z
 ---------------------------------------------------------------------
      1          1           0        0.000000    0.000000    0.000000
      2          1           0        1.000000    0.000000    0.000000
 ---------------------------------------------------------------------
 Frequencies --  -500.00  100.00  200.00
 Red. masses --     1.00    1.00    1.00
 Frc consts  --     0.10    0.10    0.10
 IR Inten    --     1.00    1.00    1.00
  Atom  AN      X      Y      Z        X      Y      Z        X      Y      Z
    1   1     0.10   0.00   0.00     0.00   0.10   0.00     0.00   0.00   0.10
    2   1    -0.10   0.00   0.00     0.00  -0.10   0.00     0.00   0.00  -0.10
 SCF Done:  E(RHF) =  -1.100000 A.U.
 Normal termination of Gaussian 16
"""


class TsIrcTests(unittest.TestCase):
    def test_one_imaginary_mode_is_candidate_and_displacement_parses(self) -> None:
        result = TS.analyze_ts_log_text(LOG)
        self.assertTrue(result["first_order_saddle_candidate"])
        self.assertEqual(result["raw_imaginary_frequency_count"], 1)
        self.assertEqual(len(result["imaginary_modes"][0]["displacements"]), 2)

    def test_two_imaginary_modes_is_not_candidate(self) -> None:
        result = TS.analyze_ts_log_text(LOG.replace("-500.00  100.00  200.00", "-500.00 -100.00  200.00"))
        self.assertFalse(result["first_order_saddle_candidate"])
        self.assertEqual(result["raw_imaginary_frequency_count"], 2)

    def test_qst2_rejects_atom_order_mismatch(self) -> None:
        structure = {"charge": 0, "multiplicity": 1, "atoms": [{"element": "C"}, {"element": "H"}]}
        swapped = {"charge": 0, "multiplicity": 1, "atoms": [{"element": "H"}, {"element": "C"}]}
        report = TS.validate_input_family("qst2", {"reactant": structure, "product": swapped}, [1, 2])
        self.assertFalse(report["valid"])

    def test_cartesian_input_allows_multiline_route(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "input.gjf"
            path.write_text("%mem=1GB\n#p Opt=(TS)\n B3LYP/6-31G(d)\n\nTitle\n\n0 1\nH 0 0 0\nH 0 0 1\n\n")
            parsed = TS.parse_cartesian_input(path)
            self.assertEqual(parsed["charge"], 0)
            self.assertEqual(len(parsed["atoms"]), 2)

    def test_mode_review_and_irc_plan_require_explicit_promotion(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); result = TS.analyze_ts_log_text(LOG)
            TS.create_mode_review(result, [(1, 2)], root / "review", 0.1)
            self.assertTrue((root / "review" / "mode_plus.xyz").is_file())
            self.assertTrue((root / "review" / "mode_minus.xyz").is_file())
            result_path = root / "ts.json"; result_path.write_text(json.dumps(result))
            with self.assertRaises(ValueError): TS.build_irc_plan({"schema": TS.SCHEMA}, result_path, root / "ts.chk", "#p IRC", "#p IRC", "abc_if", "abc_ir")
            TS.record_mode_decision(result_path, "accepted")
            checkpoint = root / "ts.chk"; checkpoint.write_bytes(b"checkpoint")
            plan = TS.build_irc_plan({"schema": TS.SCHEMA, "workflow_id": "test"}, result_path, checkpoint, "#p IRC=(Forward)", "#p IRC=(Reverse)", "abc_if", "abc_ir")
            self.assertEqual(plan["submission_status"], "planned_not_submitted")

    def test_family_manifest_requires_explicit_routes_and_tiers(self) -> None:
        audit = {"schema": TS.SCHEMA, "valid": True}
        protocol = {"workflow_id": "test", "project_prefix": "test_ts", "expected_reactant_identity": "A", "expected_product_identity": "B", "coordinate_changes": [{"forming": [1, 2]}], "routes": {"ts_freq": "#p Opt=(TS) Freq", "irc_forward": "#p IRC=(Forward)", "irc_reverse": "#p IRC=(Reverse)", "endpoint_opt_freq": "#p Opt Freq"}, "resource_tiers": {"ts_freq": "simple", "irc": "simple", "endpoint": "simple"}, "temperature_k": 298.15, "standard_state": "1M"}
        manifest = TS.create_family_manifest(audit, protocol)
        self.assertEqual(manifest["status"], "prepared_not_submitted")
        self.assertTrue(manifest["safety"]["no_submission_authorization"])


if __name__ == "__main__":
    unittest.main()
