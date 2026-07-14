#!/usr/bin/env python3
"""Offline forward tests for the real Wang 2024 CAT2 study package."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
MODULE = ROOT / "skills" / "auto-g16-asymmetric-catalysis" / "scripts" / "asymmetric_catalysis.py"
CASE_DIR = ROOT / "studies" / "wang_2024_cat2_alpha_alkylation"
CASE_PATH = CASE_DIR / "forward-study.json"
BF3_DIR = ROOT / "studies" / "wang_2024_bf3_ts"
SPEC = importlib.util.spec_from_file_location("asymmetric_catalysis_real_case", MODULE)
assert SPEC and SPEC.loader
ASYM = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ASYM)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class AsymmetricRealCaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.case = json.loads(CASE_PATH.read_text(encoding="utf-8"))

    def test_real_reaction_identity_and_provenance_are_explicit(self) -> None:
        self.assertEqual(self.case["citation"]["doi"], "10.1021/jacs.4c09067")
        self.assertEqual(
            self.case["citation"]["supporting_information_sha256"],
            "e81d7b62a850e9db86f634112098c597d08b9e1e06fed1544d376f404047569b",
        )
        experiment = self.case["experimental_case"]
        self.assertEqual(experiment["substrate"]["identity"], "2-ethylbenzoxazole")
        self.assertEqual(experiment["electrophile"]["identity"], "tert-butyl acrylate")
        self.assertEqual(experiment["product"]["source_assigned_configuration"], "S")
        self.assertEqual(experiment["product"]["isolated_yield_percent"], 86)
        self.assertEqual(experiment["product"]["ee_percent"], 92)
        self.assertEqual(experiment["reaction_conditions"]["reaction_temperature_k"], 263.15)

    def test_unresolved_science_is_null_and_blocks_formal_study(self) -> None:
        self.assertEqual(self.case["status"], "reviewed_offline_blocked")
        self.assertEqual(
            self.case["formal_contract_status"],
            "not_emitted_because_required_science_is_unresolved",
        )
        self.assertFalse(self.case["calculation_ready"])
        self.assertTrue(self.case["no_submission_authorization"])
        state = self.case["active_catalyst_state_hypothesis"]
        for field in (
            "structure", "atom_inventory", "charge", "multiplicity", "aggregation_state",
            "coordination_state", "substrate_binding", "base_binding", "counterion_or_ion_pair",
        ):
            self.assertIsNone(state[field], field)
        mechanism = self.case["mechanism_hypothesis"]
        self.assertIsNone(mechanism["selectivity_determining_step"])
        self.assertIsNone(mechanism["turnover_limiting_step"])
        self.assertFalse(mechanism["transfer_from_bf3_or_bcf_to_cat2_established"])
        protocol = self.case["comparison_protocol"]
        self.assertFalse(protocol["approved"])
        for field in (
            "optimization_and_frequency_route", "single_point_route", "method",
            "basis_and_ecp", "solvent_model", "temperature_k", "standard_state",
            "low_frequency_policy", "reference_energy_definition", "aggregation_model",
        ):
            self.assertIsNone(protocol[field], field)

    def test_candidate_space_records_both_channels_without_fake_geometries(self) -> None:
        channels = {item["channel_id"]: item for item in self.case["stereochemical_channels"]}
        self.assertEqual(
            set(channels),
            {"channel_si_assigned_s_4a", "channel_counterfactual_r_4a"},
        )
        for channel in channels.values():
            self.assertIsNone(channel["substrate_face"])
            self.assertIsNone(channel["candidate_atom_map"])
            self.assertIsNone(channel["endpoint_mapping"])
        space = self.case["candidate_space_review"]
        self.assertFalse(space["ready_for_enumeration"])
        self.assertFalse(space["cartesian_product_generated"])
        dimensions = {item["dimension_id"]: item for item in space["dimensions"]}
        self.assertEqual(
            dimensions["boron_center"]["review_levels"],
            ["cat2_boron_a_unmapped", "cat2_boron_b_unmapped"],
        )
        for dimension_id in (
            "boron_coordination_state", "binding_mode", "catalyst_conformer", "base_additive_placement",
        ):
            self.assertEqual(dimensions[dimension_id]["review_levels"], [])
            self.assertEqual(dimensions[dimension_id]["status"], "blocked")
        self.assertEqual(self.case["materialization"]["candidate_count"], 0)
        self.assertFalse(self.case["materialization"]["promotion_allowed"])

    def test_bf3_coordinates_are_hash_bound_but_cannot_become_ee_candidates(self) -> None:
        link = self.case["published_bf3_mechanistic_submodel"]
        ledger_path = (CASE_DIR / link["artifact"]["path"]).resolve()
        self.assertEqual(ledger_path, (BF3_DIR / "candidate-ledger.json").resolve())
        self.assertEqual(digest(ledger_path), link["artifact"]["sha256"])
        self.assertEqual(link["role"], "achiral_mechanistic_submodel_only")
        self.assertFalse(link["is_cat2_geometry"])
        self.assertFalse(link["is_ee_ensemble"])
        self.assertFalse(link["can_supply_cat2_atom_map"])
        with tempfile.TemporaryDirectory() as tmp:
            rebuilt = Path(tmp) / "bf3-ledger.json"
            ASYM.build_literature_benchmark(BF3_DIR / "benchmark-source.json", rebuilt)
            self.assertEqual(rebuilt.read_bytes(), ledger_path.read_bytes())

    def test_existing_builders_refuse_materialization_and_smoke(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaisesRegex(ASYM.OfflineError, "unrecognized ledger schema"):
                ASYM.materialize_candidates(CASE_PATH, CASE_PATH, CASE_PATH, root / "candidates")
            with self.assertRaisesRegex(ASYM.OfflineError, "requires a literature benchmark ledger"):
                ASYM.propose_smoke(CASE_PATH, "cat2_in_situ_identity_incomplete", root / "smoke.json")
            self.assertFalse((root / "candidates").exists())
            self.assertFalse((root / "smoke.json").exists())

    def test_package_contains_no_promotion_or_live_authorization(self) -> None:
        serialized = CASE_PATH.read_text(encoding="utf-8").lower()
        self.assertNotIn("promoted_offline", serialized)
        for forbidden in ("qsub", "#p ", "%chk", "/home/user100/sdl"):
            self.assertNotIn(forbidden, serialized)
        refused = {gate["gate_id"]: gate["status"] for gate in self.case["gates"]}
        self.assertEqual(refused["candidate_promotion"], "refused")
        self.assertEqual(refused["live_smoke"], "refused")


if __name__ == "__main__":
    unittest.main()
