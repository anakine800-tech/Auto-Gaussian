#!/usr/bin/env python3
"""Strict standard-library schema validation tests for asymmetric artifacts."""

from __future__ import annotations

import copy
import importlib.util
import json
import math
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
MODULE = ROOT / "scripts" / "validate_asymmetric_contract.py"
FIXTURES = ROOT / "tests" / "fixtures" / "asymmetric_catalysis"
SCHEMAS = ROOT / "contracts" / "asymmetric-catalysis"
SPEC = importlib.util.spec_from_file_location("validate_asymmetric_contract_strict", MODULE)
assert SPEC and SPEC.loader
CONTRACT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONTRACT)


def load(path: Path) -> dict:
    return CONTRACT.load_json(path)


def artifact(path: str = "fixture://artifact") -> dict:
    return {"path": path, "sha256": "a" * 64}


def space_instance() -> dict:
    dimensions = []
    for number in range(5):
        dimensions.append(
            {
                "dimension_id": f"dimension_{number}",
                "levels": [{"level_id": f"level_{number}", "equivalence_key": f"eq_{number}", "metadata": {}}],
            }
        )
    return {
        "schema": "gaussian-asymmetric-candidate-space-spec/1",
        "study_id": "study_fixture",
        "study_sha256": "b" * 64,
        "comparison_group_id": "group_fixture",
        "candidate_id_prefix": "candidate_fixture",
        "catalyst_state_ids": ["state_fixture"],
        "geometry_dedup_tolerance_angstrom": 0.01,
        "dimensions": dimensions,
        "exclusion_rules": [],
    }


def ledger_instance() -> dict:
    return {
        "schema": "gaussian-asymmetric-candidate-ledger/1",
        "study_id": "study_fixture",
        "study_sha256": "b" * 64,
        "comparison_group_id": "group_fixture",
        "mechanism_id": "mechanism_fixture",
        "protocol_id": "protocol_fixture",
        "calculation_ready": False,
        "no_submission_authorization": True,
        "candidate_space_spec": artifact("fixture://space"),
        "geometry_dedup_tolerance_angstrom": 0.01,
        "dimension_ids": [f"dimension_{number}" for number in range(5)],
        "entries": [],
        "excluded_combinations": [],
        "counts": {
            "enumerated": 0,
            "retained": 0,
            "logical_duplicates": 0,
            "excluded": 0,
            "materialized_unique": 0,
            "geometry_duplicates": 0,
        },
    }


def energy_instance() -> dict:
    return {
        "schema": "gaussian-asymmetric-energy-record/1",
        "result_id": "result_fixture",
        "candidate_id": "candidate_fixture",
        "energy_unit": "kcal_mol",
        "electronic_energy": -100.0,
        "thermal_gibbs_correction": 0.1,
        "comparison_free_energy": 10.0,
        "comparison_energy_definition": "common fixture zero",
        "temperature_k": 298.15,
        "standard_state": "1M",
        "low_frequency_policy": "raw harmonic fixture",
        "inventory_key": "fixture_inventory",
        "degeneracy": 1,
    }


def materializations_instance() -> dict:
    return {"schema": "gaussian-asymmetric-materializations/1", "ledger_sha256": "c" * 64, "records": []}


def metal_support_instance() -> dict:
    return {
        "schema": "gaussian-asymmetric-metal-support-design/1",
        "study_id": "study_fixture",
        "study_sha256": "d" * 64,
        "calculation_ready": False,
        "no_submission_authorization": True,
        "runtime_support_status": "unsupported_requires_extension",
        "submission_decision": "refused",
        "states": [
            {
                "state_id": "state_fixture",
                "support_status": "unsupported_transition_metal",
                "submission_decision": "refused",
                "checks": {},
                "known_hypotheses": [],
                "unresolved": ["offline only"],
            }
        ],
        "acceptance_gates": ["review required"],
        "refusal_tests": ["submission remains refused"],
    }


def live_smoke_evidence_instance() -> dict:
    evidence = {
        "schema": "gaussian-asymmetric-live-smoke-evidence/1",
        "evidence_id": "bf3_ts1_smoke_evidence_fixture",
        "status": "passed",
        "recorded_date": "2026-07-14",
        "calculation_ready": False,
        "no_submission_authorization": True,
        "sanitized": True,
        "contains_job_id": False,
        "contains_server_path": False,
        "contains_gaussian_log": False,
        "contains_checkpoint": False,
        "source_bindings": {
            name: {"sha256": character * 64}
            for name, character in zip(
                (
                    "smoke_proposal", "literature_ledger", "input_approval", "input",
                    "job_record", "parsed_ts_result", "mode_review", "mode_decision",
                ),
                "abcdef01",
                strict=True,
            )
        },
        "chemical_system": {
            "candidate_id": "wang2024_bf3_ts1",
            "formula": "C18H30BF3N4O",
            "atom_count": 57,
            "charge": 0,
            "multiplicity": 1,
            "canonical_coordinate_block_sha256": "9" * 64,
        },
        "execution": {
            "g16_revision": "Gaussian 16 reviewed revision",
            "route": "reviewed exact route bound by the input hash",
            "resource_tier": "simple",
            "memory": "12GB",
            "nprocshared": 8,
            "terminal_state_confirmed": True,
            "transport_hashes_verified": True,
            "fresh_project_guard_passed": True,
            "resource_policy_reviewed": True,
        },
        "ts_validation": {
            "normal_termination": True,
            "error_termination": False,
            "stationary_point": True,
            "frequency_complete": True,
            "raw_imaginary_frequency_count": 1,
            "first_order_saddle_candidate": True,
            "featured_imaginary_frequency_cm1": -1455.35,
        },
        "mode_validation": {
            "decision": "accepted",
            "confirmed": True,
            "intended_coordinate": "H14 displacement along the reviewed C13-H14-N23 coordinate",
            "coordinate_projection_reviewed": True,
        },
        "limitations": [
            "Sanitized workflow evidence only; it does not authorize another job or an IRC calculation."
        ],
    }
    evidence["evidence_payload_sha256"] = CONTRACT.payload_sha256(evidence)
    return evidence


class AsymmetricSchemaValidationTests(unittest.TestCase):
    def artifact_instances(self) -> dict[str, dict]:
        result = load(FIXTURES / "boron_result_r.json")
        result["artifacts"].setdefault("checkpoint_audit", None)
        result["artifacts"].setdefault("irc_plan", None)
        return {
            "study": load(FIXTURES / "boron_study.json"),
            "candidate": load(FIXTURES / "boron_candidate_r.json"),
            "result": result,
            "analysis": load(FIXTURES / "boron_analysis.json"),
            "space": space_instance(),
            "ledger": ledger_instance(),
            "energy-record": energy_instance(),
            "materializations": materializations_instance(),
            "metal-support": metal_support_instance(),
            "smoke-proposal": load(ROOT / "docs" / "asymmetric-catalysis-smoke-proposal.json"),
            "live-smoke-evidence": live_smoke_evidence_instance(),
            "literature-benchmark": load(ROOT / "studies" / "wang_2024_bf3_ts" / "candidate-ledger.json"),
        }

    def test_all_twelve_schema_documents_use_supported_keywords(self) -> None:
        expected = set(CONTRACT.SCHEMA_IDS)
        found = set()
        for path in SCHEMAS.glob("*.schema.json"):
            schema = load(path)
            CONTRACT.validate_schema_document(schema)
            found.add(path.name.removesuffix(".schema.json"))
        self.assertEqual(found, expected)

        unsupported = {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object", "if": {}}
        with self.assertRaisesRegex(CONTRACT.ContractError, "unsupported keyword"):
            CONTRACT.validate_schema_document(unsupported)

    def test_all_twelve_artifact_types_have_a_structural_entry_point(self) -> None:
        instances = self.artifact_instances()
        self.assertEqual(set(instances), set(CONTRACT.SCHEMA_IDS))
        for kind, instance in instances.items():
            with self.subTest(kind=kind):
                self.assertEqual(CONTRACT.validate_structure(instance), kind)
                self.assertEqual(CONTRACT.validate_structure(instance, kind), kind)

    def test_internal_refs_required_fields_and_additional_properties_are_enforced(self) -> None:
        bad_id = energy_instance()
        bad_id["candidate_id"] = "INVALID-ID"
        with self.assertRaisesRegex(CONTRACT.ContractError, "pattern"):
            CONTRACT.validate_structure(bad_id, "energy-record")

        missing = energy_instance()
        missing.pop("degeneracy")
        with self.assertRaisesRegex(CONTRACT.ContractError, "missing required"):
            CONTRACT.validate_structure(missing, "energy-record")

        extra = energy_instance()
        extra["submission_authorized"] = True
        with self.assertRaisesRegex(CONTRACT.ContractError, "additional property"):
            CONTRACT.validate_structure(extra, "energy-record")

    def test_non_finite_numbers_and_non_standard_json_are_rejected(self) -> None:
        for value in (math.nan, math.inf, -math.inf):
            record = energy_instance()
            record["comparison_free_energy"] = value
            with self.subTest(value=value), self.assertRaisesRegex(CONTRACT.ContractError, "type|non-finite"):
                CONTRACT.validate_structure(record, "energy-record")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for token in ("NaN", "Infinity", "-Infinity"):
                path = root / f"{token.replace('-', 'minus')}.json"
                path.write_text(f'{{"value": {token}}}\n', encoding="utf-8")
                with self.subTest(token=token), self.assertRaisesRegex(CONTRACT.ContractError, "non-standard JSON"):
                    CONTRACT.load_json(path)

    def test_duplicate_json_keys_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "duplicate.json"
            path.write_text('{"schema":"one","schema":"two"}\n', encoding="utf-8")
            with self.assertRaisesRegex(CONTRACT.ContractError, "duplicate JSON object key"):
                CONTRACT.load_json(path)

    def test_integer_constraints_do_not_accept_booleans_or_zero_degeneracy(self) -> None:
        for value in (False, 0, -1):
            record = energy_instance()
            record["degeneracy"] = value
            with self.subTest(value=value), self.assertRaises(CONTRACT.ContractError):
                CONTRACT.validate_energy_record(record)

    def test_offline_refusal_boundaries_are_structural_and_hash_bound(self) -> None:
        smoke = self.artifact_instances()["smoke-proposal"]
        ledger_path = ROOT / "studies" / "wang_2024_bf3_ts" / "candidate-ledger.json"
        literature = load(ledger_path)
        CONTRACT.validate_smoke_proposal(smoke, literature, ledger_path)

        calculation_ready = copy.deepcopy(smoke)
        calculation_ready["calculation_ready"] = True
        with self.assertRaisesRegex(CONTRACT.ContractError, "const"):
            CONTRACT.validate_smoke_proposal(calculation_ready)

        route = copy.deepcopy(smoke)
        route["proposed_gaussian"]["route"] = "#p opt=(ts) freq"
        route["proposal_payload_sha256"] = CONTRACT.payload_sha256(
            {key: value for key, value in route.items() if key != "proposal_payload_sha256"}
        )
        with self.assertRaisesRegex(CONTRACT.ContractError, "runnable route"):
            CONTRACT.validate_smoke_proposal(route)

        tampered = copy.deepcopy(smoke)
        tampered["purpose"] += " tampered"
        with self.assertRaisesRegex(CONTRACT.ContractError, "payload hash mismatch"):
            CONTRACT.validate_smoke_proposal(tampered)

    def test_literature_payload_and_atom_inventory_are_bound(self) -> None:
        ledger = self.artifact_instances()["literature-benchmark"]
        CONTRACT.validate_literature_benchmark(ledger)

        tampered = copy.deepcopy(ledger)
        tampered["candidates"][0]["atom_inventory"]["atom_count"] += 1
        with self.assertRaisesRegex(CONTRACT.ContractError, "payload hash mismatch"):
            CONTRACT.validate_literature_benchmark(tampered)

        bad_inventory = copy.deepcopy(ledger)
        bad_inventory["candidates"][0]["atom_inventory"]["atom_count"] += 1
        bad_inventory["ledger_payload_sha256"] = CONTRACT.payload_sha256(
            {key: value for key, value in bad_inventory.items() if key != "ledger_payload_sha256"}
        )
        with self.assertRaisesRegex(CONTRACT.ContractError, "atom order/count mismatch"):
            CONTRACT.validate_literature_benchmark(bad_inventory)

    def test_live_smoke_evidence_requires_complete_approval_and_mode_chain(self) -> None:
        evidence = live_smoke_evidence_instance()
        CONTRACT.validate_live_smoke_evidence(evidence)

        tampered = copy.deepcopy(evidence)
        tampered["source_bindings"]["input"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(CONTRACT.ContractError, "payload hash mismatch"):
            CONTRACT.validate_live_smoke_evidence(tampered)

        missing_approval = copy.deepcopy(evidence)
        missing_approval["source_bindings"].pop("input_approval")
        missing_approval["evidence_payload_sha256"] = CONTRACT.payload_sha256(
            {key: value for key, value in missing_approval.items() if key != "evidence_payload_sha256"}
        )
        with self.assertRaisesRegex(CONTRACT.ContractError, "missing required"):
            CONTRACT.validate_live_smoke_evidence(missing_approval)

        unreviewed_mode = copy.deepcopy(evidence)
        unreviewed_mode["mode_validation"].update(
            decision="not_reviewed", confirmed=False, coordinate_projection_reviewed=False
        )
        unreviewed_mode["evidence_payload_sha256"] = CONTRACT.payload_sha256(
            {key: value for key, value in unreviewed_mode.items() if key != "evidence_payload_sha256"}
        )
        with self.assertRaisesRegex(CONTRACT.ContractError, "accepted mode decision"):
            CONTRACT.validate_live_smoke_evidence(unreviewed_mode)

    def test_ledger_rejects_cross_channel_deduplication_and_bad_counts(self) -> None:
        ledger = ledger_instance()
        dimensions = {dimension_id: "level" for dimension_id in ledger["dimension_ids"]}
        base = {
            "candidate_id": "candidate_one",
            "channel_id": "channel_one",
            "catalyst_state_id": "state_fixture",
            "dimensions": dimensions,
            "canonical_key": "1" * 64,
            "logical_equivalence_key": "2" * 64,
            "status": "unmaterialized",
            "duplicate_of": None,
            "candidate_artifact": None,
            "geometry_fingerprint": None,
            "diagnostics": [],
        }
        duplicate = copy.deepcopy(base)
        duplicate.update(
            candidate_id="candidate_two",
            channel_id="channel_two",
            canonical_key="3" * 64,
            status="duplicate_logical",
            duplicate_of="candidate_one",
        )
        ledger["entries"] = [base, duplicate]
        ledger["counts"].update(enumerated=2, retained=1, logical_duplicates=1)
        with self.assertRaisesRegex(CONTRACT.ContractError, "cross-channel deduplication"):
            CONTRACT.validate_ledger(ledger)

        bad_counts = ledger_instance()
        bad_counts["counts"]["enumerated"] = 1
        with self.assertRaisesRegex(CONTRACT.ContractError, "enumerated count mismatch"):
            CONTRACT.validate_ledger(bad_counts)

    def test_materialization_is_hash_bound_to_ledger(self) -> None:
        ledger = ledger_instance()
        with tempfile.TemporaryDirectory() as tmp:
            ledger_path = Path(tmp) / "ledger.json"
            ledger_path.write_text(json.dumps(ledger) + "\n", encoding="utf-8")
            materializations = materializations_instance()
            with self.assertRaisesRegex(CONTRACT.ContractError, "ledger hash mismatch"):
                CONTRACT.validate_materializations(materializations, ledger, ledger_path)

    def test_path_validated_result_requires_bound_checkpoint_and_irc_artifacts(self) -> None:
        candidate_path = FIXTURES / "boron_candidate_r.json"
        candidate = load(candidate_path)
        result = load(FIXTURES / "boron_result_r.json")
        result["validation_level"] = "path_validated"
        result["path_evidence"].update(
            forward="completed_and_identified",
            reverse="completed_and_identified",
            endpoint_identity_reviewed=True,
        )
        with self.assertRaisesRegex(CONTRACT.ContractError, "checkpoint_audit artifact required"):
            CONTRACT.validate_result(result, candidate, candidate_path)


if __name__ == "__main__":
    unittest.main()
