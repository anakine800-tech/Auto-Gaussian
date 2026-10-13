#!/usr/bin/env python3
"""Offline regressions for the additive protected QST3 adapter."""

from __future__ import annotations

import importlib.util
import hashlib
import json
import re
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).parents[1]
ADAPTER_PATH = ROOT / "skills/auto-g16-rtwin-pbs/scripts/protected_qst3_adapter.py"
MATURITY_PATH = ROOT / "skills/auto-g16-reaction-workflow/scripts/scientific_maturity_v2.py"
TS_PATH = ROOT / "skills/auto-g16-ts-irc/scripts/ts_irc.py"
LEGACY_PATH = ROOT / "skills/auto-g16-rtwin-pbs/scripts/legacy_rtwin_pbs.py"
PROTECTED_SUBMIT_PATH = ROOT / "scripts/protected_submit_contract.py"


def module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    sys.path.insert(0, str(path.parent))
    try:
        spec.loader.exec_module(value)
    except Exception:
        sys.modules.pop(name, None)
        raise
    finally:
        sys.path.pop(0)
    return value


ADAPTER = module("protected_qst3_adapter_test", ADAPTER_PATH)
MATURITY = module("protected_qst3_maturity_test", MATURITY_PATH)
TS = module("protected_qst3_ts_result_test", TS_PATH)
LEGACY = module("protected_qst3_legacy_successor_test", LEGACY_PATH)
PROTECTED_SUBMIT = module("protected_qst3_submit_contract_test", PROTECTED_SUBMIT_PATH)


def write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class ProtectedQST3AdapterTests(unittest.TestCase):
    maxDiff = None

    @staticmethod
    def _candidate_endpoints(atom_count: int = 84) -> dict:
        def endpoint(role: str) -> dict:
            return {
                "minimum_id": f"minimum_{role}",
                "state_id": f"state_{role}",
                "charge": 0,
                "multiplicity": 1,
                "stable_atom_ids": [f"atom_{index:03d}" for index in range(1, atom_count + 1)],
                "coordinates": [
                    {"index": index, "element": "H", "x": float(index), "y": 0.0, "z": 0.0}
                    for index in range(1, atom_count + 1)
                ],
            }
        return {"reactant": endpoint("reactant"), "product": endpoint("product")}

    def test_endpoint_anchored_candidate_is_one_84_atom_general_attempt_with_no_claim(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = MATURITY._finalize({
                "schema": MATURITY.BASE_GATE_SCHEMA,
                "scientific_approval_summary": {
                    "resources": {"task_budget": {"max_tasks": 2, "max_core_hours": 2000, "max_concurrent": 2}}
                },
            })
            base_path = root / "base-gate.json"; write(base_path, base)
            gate = MATURITY._finalize({
                "schema": MATURITY.GATE_SCHEMA,
                "base_gate": {
                    "path": base_path.name, "sha256": MATURITY._file_sha(base_path),
                    "size_bytes": base_path.stat().st_size, "schema": MATURITY.BASE_GATE_SCHEMA,
                    "payload_sha256": base["payload_sha256"],
                },
            })
            gate_path = root / "gate.json"; write(gate_path, gate)
            action = MATURITY._finalize({
                "schema": MATURITY.ACTION_SCHEMA, "study_id": "study_qst3_candidate",
                "scope": {"edge_id": "edge_h30_c4", "node_id": "node_qst3_candidate", "action": "ts_submission", "pilot": True},
                "scientific_maturity": {
                    "path": gate_path.name, "sha256": MATURITY._file_sha(gate_path),
                    "size_bytes": gate_path.stat().st_size, "schema": MATURITY.GATE_SCHEMA,
                    "payload_sha256": gate["payload_sha256"],
                },
            })
            action_path = root / "submission-action.json"; write(action_path, action)
            input_path = root / "candidate.gjf"; input_path.write_text("candidate bytes\n", encoding="utf-8")
            output = root / "candidate-authorization.json"
            endpoints = self._candidate_endpoints()
            with mock.patch.object(MATURITY, "validate_action", return_value=action), mock.patch.object(MATURITY, "resolve_ts_endpoint_minimum_lineages", return_value=endpoints):
                built = MATURITY.build_action_authorization(
                    action_path, input_path, output,
                    project="h30c4q3c_0809", work_kind=MATURITY.ENDPOINT_ANCHORED_TS_CANDIDATE,
                    resource_tier="general", task_count=1, estimated_core_hours=1584,
                    planned_concurrency=1,
                )
                self.assertEqual(MATURITY.validate_action_authorization(output), built)
                for changed in (
                    {"resource_tier": "simple", "task_count": 1, "planned_concurrency": 1},
                    {"resource_tier": "general", "task_count": 2, "planned_concurrency": 1},
                    {"resource_tier": "general", "task_count": 1, "planned_concurrency": 2},
                ):
                    with self.subTest(changed=changed), self.assertRaises(MATURITY.EvidenceOverlayError):
                        MATURITY._make_action_authorization(
                            action_path, input_path, "h30c4q3c_0809",
                            MATURITY.ENDPOINT_ANCHORED_TS_CANDIDATE,
                            changed["resource_tier"], changed["task_count"], 1584,
                            changed["planned_concurrency"], output,
                        )
            candidate = built["candidate_search"]
            self.assertEqual(candidate["atom_count"], 84)
            self.assertFalse(candidate["automatic_retry"])
            self.assertFalse(candidate["mechanism_claim_authorized"])
            self.assertFalse(candidate["accepted_ts_claim_authorized"])
            with mock.patch.object(MATURITY, "validate_action", return_value=action), mock.patch.object(MATURITY, "resolve_ts_endpoint_minimum_lineages", return_value=self._candidate_endpoints(83)):
                with self.assertRaisesRegex(MATURITY.EvidenceOverlayError, "84-atom minima"):
                    MATURITY._make_action_authorization(
                        action_path, input_path, "h30c4q3c_0809",
                        MATURITY.ENDPOINT_ANCHORED_TS_CANDIDATE,
                        "general", 1, 1584, 1, output,
                    )

    def test_action_authorization_v2_is_deterministic_and_project_input_resource_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = MATURITY._finalize({
                "schema": MATURITY.BASE_GATE_SCHEMA,
                "scientific_approval_summary": {
                    "resources": {"task_budget": {"max_tasks": 3, "max_core_hours": 500, "max_concurrent": 1}}
                },
            })
            base_path = root / "base-gate.json"; write(base_path, base)
            gate = MATURITY._finalize({
                "schema": MATURITY.GATE_SCHEMA,
                "base_gate": {
                    "path": base_path.name, "sha256": MATURITY._file_sha(base_path),
                    "size_bytes": base_path.stat().st_size, "schema": MATURITY.BASE_GATE_SCHEMA,
                    "payload_sha256": base["payload_sha256"],
                },
            })
            gate_path = root / "gate.json"; write(gate_path, gate)
            action = MATURITY._finalize({
                "schema": MATURITY.ACTION_SCHEMA, "study_id": "study_qst3",
                "scope": {"edge_id": "edge_h30_c4", "node_id": "node_qst3", "action": "ts_submission", "pilot": False},
                "scientific_maturity": {
                    "path": gate_path.name, "sha256": MATURITY._file_sha(gate_path),
                    "size_bytes": gate_path.stat().st_size, "schema": MATURITY.GATE_SCHEMA,
                    "payload_sha256": gate["payload_sha256"],
                },
            })
            action_path = root / "submission-action.json"; write(action_path, action)
            input_path = root / "qst3.gjf"; input_path.write_text("%mem=50GB\n%nprocshared=22\n#p x/y opt=(qst3,calcfc) freq\n", encoding="utf-8")
            output = root / "authorization.json"
            with mock.patch.object(MATURITY, "validate_action", return_value=action):
                built = MATURITY.build_action_authorization(
                    action_path, input_path, output,
                    project="h30c4q3s_0809", work_kind="formal_ts", resource_tier="general",
                    task_count=1, estimated_core_hours=216, planned_concurrency=1,
                )
                self.assertEqual(MATURITY.validate_action_authorization(output), built)
            self.assertEqual(built["input"]["sha256"], MATURITY._file_sha(input_path))
            self.assertEqual(built["scope"]["project"], "h30c4q3s_0809")
            self.assertFalse(built["calculation_ready"])
            self.assertTrue(built["no_submission_authorization"])
            changed = json.loads(output.read_text()); changed["scope"]["project"] = "another"
            changed["payload_sha256"] = MATURITY._payload_sha256(changed); write(output, changed)
            with mock.patch.object(MATURITY, "validate_action", return_value=action):
                with self.assertRaisesRegex(MATURITY.EvidenceOverlayError, "project scope differs"):
                    MATURITY.validate_action_authorization(output, project="h30c4q3s_0809")

    def _owner_binding(
        self, sha: str = "a" * 64, *, candidate: bool = False,
    ) -> dict:
        work_kind = (
            MATURITY.ENDPOINT_ANCHORED_TS_CANDIDATE
            if candidate else "formal_ts"
        )
        project = "h30c4q3c_0809" if candidate else "h30c4q3s_0809"
        maturity = {
            "schema": ADAPTER.MATURITY_ACTION_SCHEMA, "edge_id": "edge_h30_c4",
            "node_id": "node_qst3_candidate" if candidate else "node_qst3",
            "pilot": candidate,
            "maturity_gate_sha256": "b" * 64, "maturity_gate_payload_sha256": "c" * 64,
            "scientific_action_authorization_sha256": "d" * 64,
            "scientific_action_authorization_payload_sha256": "e" * 64,
        }
        def endpoint(role: str) -> dict:
            return {
                "minimum_id": f"minimum_{role}",
                "state_id": f"state_{role}",
                "lineage_payload_sha256": "6" * 64,
                "optimized_coordinates_sha256": "7" * 64,
                "charge": 0,
                "multiplicity": 1,
                "stable_atom_ids": [f"h_{role}"],
                "coordinates": [
                    {
                        "index": 1, "element": "H", "x": 0.0,
                        "y": 0.0, "z": 0.0,
                    }
                ],
            }

        return {
            "owner": "auto-g16-ts-irc", "workflow": ADAPTER.WORKFLOW,
            "work_kind": work_kind,
            "candidate_search": {
                "schema": "gaussian-endpoint-anchored-ts-candidate-scope/1",
                "endpoint_minimum_ids": [
                    "minimum_reactant", "minimum_product",
                ],
                "atom_count": 84,
                "resource_tier": "general",
                "task_limit": 1,
                "automatic_retry": False,
                "mechanism_claim_authorized": False,
                "accepted_ts_claim_authorized": False,
            } if candidate else None,
            "qst_raw_audit_payload_sha256": "f" * 64, "ts_family_sha256": "1" * 64,
            "ts_input_action_payload_sha256": "2" * 64, "ts_submission_action_payload_sha256": "3" * 64,
            "scientific_action_authorization_sha256": "d" * 64,
            "scientific_action_authorization_payload_sha256": "e" * 64,
            "selected_option_payload_sha256": "4" * 64, "project": project,
            "input_sha256": sha, "exact_route": "#p x/y opt=(qst3,calcfc) freq",
            "input_family": "qst3", "structure_count": 3, "atom_count": 84,
            "charge": 0, "multiplicity": 1, "scientific_maturity": maturity,
            "endpoint_minimum_lineages": {
                "schema": "gaussian-ts-endpoint-minimum-lineage-projection/1",
                "edge_id": "edge_h30_c4", "node_id": "node_qst3",
                "from_state_id": "state_reactant",
                "to_state_id": "state_product",
                "atom_mapping": [{
                    "from_atom_id": "h_reactant",
                    "to_atom_id": "h_product",
                }],
                "reactant": endpoint("reactant"),
                "product": endpoint("product"),
                "calculation_ready": False,
                "no_submission_authorization": True,
            },
            "atom_identity_mapping": {
                "schema": "gaussian-qst3-mechanism-atom-identity/1",
                "declared_atom_map": [1],
                "reviewed_guess_index_basis": "reactant",
                "index_bindings": [{
                    "reactant_index": 1,
                    "reactant_stable_atom_id": "h_reactant",
                    "product_index": 1,
                    "product_stable_atom_id": "h_product",
                    "mechanism_to_atom_id": "h_product",
                }],
            },
            "coordinate_equivalence": {
                "scheme": "absolute_cartesian_tolerance/1",
                "unit": "angstrom",
                "absolute_tolerance": 1e-8,
                "relative_tolerance": 0.0,
            },
            "authorized_budget": {
                "task_count": 1,
                "estimated_core_hours": 1584 if candidate else 216,
                "planned_concurrency": 1,
            },
            "resources": {"resource_tier": "general", "mem_gb": 50, "cores": 22},
            "owner_replay_passed": True,
        }

    def test_live_scope_is_exactly_project_resource_and_maturity_bound(self) -> None:
        owner = self._owner_binding()
        receipt = {
            "schema": ADAPTER.INPUT_SCHEMA, "payload_sha256": "5" * 64,
            "work_kind": "formal_ts",
            "input": {"sha256": "a" * 64}, "specialist_owner_binding": owner,
        }
        report = {
            "input_sha256": "a" * 64, "route": owner["exact_route"], "mem": "50GB",
            "nprocshared": 22, "charge": 0, "multiplicity": 1,
        }
        legacy = SimpleNamespace(parse_gaussian=lambda _path: report, sha256=lambda _path: "6" * 64)
        execution = {
            "batch_id": "batch", "review_sha256": "7" * 64,
            "scientific_task_id": "scientific-task-" + "8" * 64,
            "attempt_id": "qsub-attempt-" + "9" * 64, "idempotency_key": "qst3-attempt",
            "estimated_core_hours": 216.0,
            "estimated_core_hours_evidence": {"source": "review", "sha256": "a" * 64},
            "resource_binding": {
                "policy_id": "policy", "policy_sha256": "b" * 64,
                "gate_id": "gate", "gate_sha256": "c" * 64,
                "resource_tier": "general", "cores": 22, "memory_gb": 50,
                "walltime_seconds": 259200,
            },
        }
        with mock.patch.object(ADAPTER, "validate_receipt", return_value=receipt), mock.patch.object(ADAPTER, "_owners", return_value=(legacy, None, None)):
            scope = ADAPTER.expected_live_scope(Path("receipt.json"), Path("input.gjf"), "h30c4q3s_0809", execution)
            self.assertEqual(scope["work_kind"], "formal_ts")
            self.assertEqual(scope["scientific_maturity"]["edge_id"], "edge_h30_c4")
            self.assertEqual(scope["ts_qst_owner"], owner)
            drift = json.loads(json.dumps(execution)); drift["resource_binding"]["cores"] = 44
            with self.assertRaisesRegex(ADAPTER.ProtectedQST3Error, "live resources differ"):
                ADAPTER.expected_live_scope(Path("receipt.json"), Path("input.gjf"), "h30c4q3s_0809", drift)
            invalid = json.loads(json.dumps(execution))
            invalid["resource_binding"]["walltime_seconds"] = -1
            with self.assertRaisesRegex(ADAPTER.ProtectedQST3Error, "budget/walltime"):
                ADAPTER.expected_live_scope(
                    Path("receipt.json"), Path("input.gjf"),
                    "h30c4q3s_0809", invalid,
                )

            validated_input = {
                "status": "validated_exact_input_approval",
                "schema": ADAPTER.INPUT_SCHEMA,
                "sha256": "6" * 64,
                "payload_sha256": receipt["payload_sha256"],
                "input_sha256": report["input_sha256"],
                "work_kind": "formal_ts",
                "specialist_owner_binding": owner,
            }
            maturity = {
                "schema": ADAPTER.MATURITY_ACTION_SCHEMA,
                "edge_id": "edge_h30_c4",
                "node_id": "node_qst3",
                "pilot": False,
                "exact_action_authorization": {
                    "sha256": owner[
                        "scientific_action_authorization_sha256"
                    ],
                    "payload_sha256": owner[
                        "scientific_action_authorization_payload_sha256"
                    ],
                },
            }
            legacy_summary = LEGACY.live_approval_summary(
                "h30c4q3s_0809", report, maturity,
                "formal_ts", validated_input,
            )
            legacy_summary["execution"] = execution
            schema, legacy_scope = LEGACY.expected_live_approval_scope(
                legacy_summary
            )
            self.assertEqual(schema, ADAPTER.LIVE_SCHEMA)
            self.assertEqual(legacy_scope, scope)
            from tests import test_live_approval_effect_time_replay as live_support

            replay_summary = live_support.REPLAY._summary_from_approval(
                {"schema": ADAPTER.LIVE_SCHEMA, "scope": scope}
            )
            replay_schema, replay_scope = LEGACY.expected_live_approval_scope(
                replay_summary
            )
            self.assertEqual((replay_schema, replay_scope), (schema, scope))
            self.assertIn(
                ADAPTER.INPUT_SCHEMA,
                PROTECTED_SUBMIT.SUPPORTED_INPUT_APPROVALS,
            )
            self.assertIn(
                ADAPTER.LIVE_SCHEMA,
                PROTECTED_SUBMIT.SUPPORTED_LIVE_APPROVALS,
            )

    def test_effect_boundary_is_explicit_and_never_calls_qsub(self) -> None:
        status = ADAPTER.production_effect_status()
        self.assertFalse(status["production_submit_wired"])
        self.assertFalse(status["parallel_effect_owner_created"])
        self.assertEqual(status["qsub_calls"], 0)
        self.assertEqual(
            status["blocker"],
            "protected_qst3_production_entry_not_connected",
        )
        with self.assertRaisesRegex(ADAPTER.ProtectedQST3Error, "sole legacy"):
            ADAPTER.submit_once()

    def test_candidate_live_v13_effect_time_replay_preserves_pilot_and_scope(
        self,
    ) -> None:
        owner = self._owner_binding(candidate=True)
        receipt = {
            "schema": ADAPTER.INPUT_SCHEMA,
            "payload_sha256": "5" * 64,
            "work_kind": MATURITY.ENDPOINT_ANCHORED_TS_CANDIDATE,
            "input": {"sha256": "a" * 64},
            "specialist_owner_binding": owner,
        }
        report = {
            "input_sha256": "a" * 64,
            "route": owner["exact_route"],
            "mem": "50GB",
            "nprocshared": 22,
            "charge": 0,
            "multiplicity": 1,
        }
        legacy = SimpleNamespace(
            parse_gaussian=lambda _path: report,
            sha256=lambda _path: "6" * 64,
        )
        execution = {
            "batch_id": "batch",
            "review_sha256": "7" * 64,
            "scientific_task_id": "scientific-task-" + "8" * 64,
            "attempt_id": "qsub-attempt-" + "9" * 64,
            "idempotency_key": "qst3-candidate-attempt",
            "estimated_core_hours": 1584.0,
            "estimated_core_hours_evidence": {
                "source": "review", "sha256": "a" * 64,
            },
            "resource_binding": {
                "policy_id": "policy", "policy_sha256": "b" * 64,
                "gate_id": "gate", "gate_sha256": "c" * 64,
                "resource_tier": "general", "cores": 22,
                "memory_gb": 50, "walltime_seconds": 259200,
            },
        }
        with mock.patch.object(
            ADAPTER, "validate_receipt", return_value=receipt,
        ), mock.patch.object(
            ADAPTER, "_owners", return_value=(legacy, None, None),
        ):
            scope = ADAPTER.expected_live_scope(
                Path("receipt.json"), Path("input.gjf"),
                "h30c4q3c_0809", execution,
            )
        self.assertTrue(scope["scientific_maturity"]["pilot"])
        self.assertEqual(
            scope["ts_qst_owner"]["candidate_search"],
            owner["candidate_search"],
        )
        from tests import test_live_approval_effect_time_replay as live_support

        replay_summary = live_support.REPLAY._summary_from_approval(
            {"schema": ADAPTER.LIVE_SCHEMA, "scope": scope}
        )
        self.assertTrue(replay_summary["scientific_maturity"]["pilot"])
        self.assertEqual(
            replay_summary["scientific_maturity"]
            ["exact_action_authorization"]["candidate_search"],
            owner["candidate_search"],
        )
        schema, replayed_scope = LEGACY.expected_live_approval_scope(
            replay_summary
        )
        self.assertEqual(schema, ADAPTER.LIVE_SCHEMA)
        self.assertEqual(replayed_scope, scope)

        changed = json.loads(json.dumps(scope))
        changed["scientific_maturity"]["pilot"] = False
        changed_summary = live_support.REPLAY._summary_from_approval(
            {"schema": ADAPTER.LIVE_SCHEMA, "scope": changed}
        )
        changed_schema, reconstructed = LEGACY.expected_live_approval_scope(
            changed_summary
        )
        self.assertEqual(changed_schema, ADAPTER.LIVE_SCHEMA)
        self.assertNotEqual(reconstructed, changed)
        self.assertTrue(reconstructed["scientific_maturity"]["pilot"])

    def test_same_element_atom_swap_cannot_change_mechanism_identity(self) -> None:
        endpoints = {
            "reactant": {"stable_atom_ids": ["h30_r", "h31_r"]},
            "product": {"stable_atom_ids": ["h30_p", "h31_p"]},
            "atom_mapping": [
                {"from_atom_id": "h30_r", "to_atom_id": "h30_p"},
                {"from_atom_id": "h31_r", "to_atom_id": "h31_p"},
            ],
        }
        accepted = ADAPTER._bind_mechanism_atom_identity(endpoints, [1, 2])
        self.assertEqual(
            accepted["index_bindings"][0]["mechanism_to_atom_id"],
            "h30_p",
        )
        with self.assertRaisesRegex(
            ADAPTER.ProtectedQST3Error,
            "exact mechanism edge atom identity mapping",
        ):
            ADAPTER._bind_mechanism_atom_identity(endpoints, [2, 1])

    def test_nonidentity_atom_map_requires_actual_product_row_reordering(self) -> None:
        endpoints = {
            "reactant": {
                "charge": 0,
                "multiplicity": 1,
                "stable_atom_ids": ["h30_r", "h31_r"],
                "coordinates": [
                    {"index": 1, "element": "H", "x": 0.0, "y": 0.0, "z": 0.0},
                    {"index": 2, "element": "H", "x": 1.0, "y": 0.0, "z": 0.0},
                ],
            },
            "product": {
                "charge": 0,
                "multiplicity": 1,
                "stable_atom_ids": ["h31_p", "h30_p"],
                "coordinates": [
                    {"index": 1, "element": "H", "x": 1.1, "y": 0.0, "z": 0.0},
                    {"index": 2, "element": "H", "x": 0.1, "y": 0.0, "z": 0.0},
                ],
            },
            "atom_mapping": [
                {"from_atom_id": "h30_r", "to_atom_id": "h30_p"},
                {"from_atom_id": "h31_r", "to_atom_id": "h31_p"},
            ],
        }
        identity = ADAPTER._bind_mechanism_atom_identity(endpoints, [2, 1])
        self.assertEqual(identity["declared_atom_map"], [2, 1])
        expected_raw_rows = ADAPTER._expected_raw_endpoint_rows(
            endpoints, "product", [2, 1]
        )
        correctly_reordered = [
            endpoints["product"]["coordinates"][1],
            endpoints["product"]["coordinates"][0],
        ]
        self.assertTrue(ADAPTER._coordinates_equivalent(
            correctly_reordered, expected_raw_rows, "product"
        ))
        self.assertFalse(ADAPTER._coordinates_equivalent(
            endpoints["product"]["coordinates"],
            expected_raw_rows,
            "product",
        ))

        def qst3_text(product_rows: list[tuple[float, float, float]]) -> str:
            def rows(values: list[tuple[float, float, float]]) -> str:
                return "\n".join(f"H {x} {y} {z}" for x, y, z in values)
            return (
                "%chk=rows.chk\n%mem=1GB\n%nprocshared=1\n"
                "#p hf/sto-3g opt=(qst3,calcfc)\n\nreactant\n\n0 1\n"
                + rows([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)])
                + "\n\nproduct\n\n0 1\n" + rows(product_rows)
                + "\n\nguess\n\n0 1\n"
                + rows([(0.05, 0.0, 0.0), (1.05, 0.0, 0.0)])
                + "\n\n"
            )

        with tempfile.TemporaryDirectory() as temporary:
            good_path = Path(temporary) / "good.gjf"
            good_path.write_text(qst3_text([(0.1, 0.0, 0.0), (1.1, 0.0, 0.0)]))
            good_product = TS.parse_raw_qst_input(good_path)["structures"][1]
            ADAPTER._require_raw_endpoint_row_order(
                good_product, endpoints, "product", [2, 1]
            )
            bad_path = Path(temporary) / "bad.gjf"
            bad_path.write_text(qst3_text([(1.1, 0.0, 0.0), (0.1, 0.0, 0.0)]))
            bad_product = TS.parse_raw_qst_input(bad_path)["structures"][1]
            with self.assertRaisesRegex(
                ADAPTER.ProtectedQST3Error, "raw row order/coordinates"
            ):
                ADAPTER._require_raw_endpoint_row_order(
                    bad_product, endpoints, "product", [2, 1]
                )

    def test_qst3_result_binding_replays_all_three_raw_structures(self) -> None:
        input_path = ROOT / "tests/fixtures/qst_raw_input/qst3_plain.gjf"
        parsed = TS.parse_raw_qst_input(input_path)
        by_role = {item["role"]: item for item in parsed["structures"]}
        family = {
            "schema": TS.SCHEMA_V2,
            "pilot": False,
            "mechanism_edge_id": "edge_h30_c4",
            "dag_node_id": "node_qst3",
            "project_prefix": "h30c4q3s",
            "protocol": {"routes": {"ts_freq": "#p x/y opt=(qst3,calcfc) freq"}},
            "input_audit": {
                "schema": TS.SCHEMA,
                "entry_mode": "qst3",
                "valid": True,
                "atom_map": list(range(1, parsed["structures"][0]["atom_count"] + 1)),
                "structures": {
                    "reactant": by_role["reactant"],
                    "product": by_role["product"],
                    "ts": by_role["reviewed_guess"],
                },
            },
        }
        with tempfile.TemporaryDirectory() as temporary:
            family_path = Path(temporary) / "family.json"
            write(family_path, family)
            atom_count = parsed["structures"][0]["atom_count"]
            receipt = {
                "schema": "gaussian-input-approval-receipt/5",
                "work_kind": "formal_ts",
                "input": {"sha256": TS.sha256(input_path)},
                "specialist_owner_binding": {
                    "ts_family_sha256": TS.sha256(family_path),
                    "work_kind": "formal_ts",
                    "candidate_search": None,
                    "scientific_maturity": {"pilot": False},
                    "atom_count": atom_count,
                    "atom_identity_mapping": {
                        "declared_atom_map": list(range(1, atom_count + 1)),
                    },
                    "endpoint_minimum_lineages": {
                        "edge_id": "edge_h30_c4", "node_id": "node_qst3",
                    },
                },
            }
            owner = SimpleNamespace(validate_receipt=lambda _path: receipt)
            with mock.patch.object(
                TS, "_load_protected_qst3_input_owner", return_value=owner
            ), mock.patch.object(
                TS, "validate_family_artifact",
                side_effect=lambda path: json.loads(path.read_text()),
            ):
                self.assertEqual(
                    TS.validate_qst3_result_input_binding(
                        family_path, input_path, Path("input-approval.json")
                    ),
                    receipt,
                )
                drift = json.loads(json.dumps(family))
                drift["input_audit"]["structures"]["ts"]["atoms"][1]["x"] = 9.5
                write(family_path, drift)
                receipt["specialist_owner_binding"]["ts_family_sha256"] = TS.sha256(family_path)
                with self.assertRaisesRegex(
                    ValueError, "endpoint/guess coordinates differ"
                ):
                    TS.validate_qst3_result_input_binding(
                        family_path, input_path, Path("input-approval.json")
                    )
                for field, changed in (
                    ("mechanism_edge_id", "edge_wrong"),
                    ("dag_node_id", "node_wrong"),
                    ("project_prefix", "wrongproject"),
                    ("protocol", {"routes": {"ts_freq": "#p wrong"}}),
                ):
                    with self.subTest(field=field):
                        drift = json.loads(json.dumps(family))
                        drift[field] = changed
                        write(family_path, drift)
                        receipt["specialist_owner_binding"]["ts_family_sha256"] = "0" * 64
                        with self.assertRaisesRegex(ValueError, "family hash"):
                            TS.validate_qst3_result_input_binding(
                                family_path, input_path,
                                Path("input-approval.json"),
                            )

    def test_candidate_qst3_result_binding_allows_review_but_rejects_splices(
        self,
    ) -> None:
        atom_lines = "\n".join(
            f"H {float(index):.8f} 0.00000000 0.00000000"
            for index in range(84)
        )
        input_text = (
            "%mem=50GB\n%nprocshared=22\n"
            "#p x/y opt=(qst3,calcfc) freq\n\nreactant\n\n0 1\n"
            + atom_lines
            + "\n\nproduct\n\n0 1\n"
            + atom_lines
            + "\n\nreviewed guess\n\n0 1\n"
            + atom_lines
            + "\n\n"
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_path = root / "candidate.gjf"
            input_path.write_text(input_text, encoding="utf-8")
            parsed = TS.parse_raw_qst_input(input_path)
            by_role = {item["role"]: item for item in parsed["structures"]}
            family = {
                "schema": TS.SCHEMA_V2,
                "pilot": True,
                "mechanism_edge_id": "edge_h30_c4",
                "dag_node_id": "node_qst3_candidate",
                "project_prefix": "h30c4q3c_0809",
                "protocol": {
                    "routes": {
                        "ts_freq": "#p x/y opt=(qst3,calcfc) freq",
                    }
                },
                "input_audit": {
                    "schema": TS.SCHEMA,
                    "entry_mode": "qst3",
                    "valid": True,
                    "atom_map": list(range(1, 85)),
                    "structures": {
                        "reactant": by_role["reactant"],
                        "product": by_role["product"],
                        "ts": by_role["reviewed_guess"],
                    },
                },
            }
            family_path = root / "family.json"
            write(family_path, family)
            receipt = {
                "schema": "gaussian-input-approval-receipt/5",
                "work_kind": MATURITY.ENDPOINT_ANCHORED_TS_CANDIDATE,
                "input": {"sha256": TS.sha256(input_path)},
                "specialist_owner_binding": {
                    "ts_family_sha256": TS.sha256(family_path),
                    "work_kind": MATURITY.ENDPOINT_ANCHORED_TS_CANDIDATE,
                    "candidate_search": {
                        "schema": "gaussian-endpoint-anchored-ts-candidate-scope/1",
                        "atom_count": 84,
                        "resource_tier": "general",
                        "task_limit": 1,
                        "automatic_retry": False,
                        "mechanism_claim_authorized": False,
                        "accepted_ts_claim_authorized": False,
                    },
                    "scientific_maturity": {"pilot": True},
                    "atom_count": 84,
                    "atom_identity_mapping": {
                        "declared_atom_map": list(range(1, 85)),
                    },
                    "endpoint_minimum_lineages": {
                        "edge_id": "edge_h30_c4",
                        "node_id": "node_qst3_candidate",
                    },
                },
            }
            owner = SimpleNamespace(validate_receipt=lambda _path: receipt)
            with mock.patch.object(
                TS, "_load_protected_qst3_input_owner", return_value=owner,
            ), mock.patch.object(
                TS, "validate_family_artifact",
                side_effect=lambda path: json.loads(path.read_text()),
            ):
                self.assertEqual(
                    TS.validate_qst3_result_input_binding(
                        family_path, input_path, root / "receipt.json"
                    ),
                    receipt,
                )
                for label, mutate in (
                    (
                        "pilot",
                        lambda value: value["specialist_owner_binding"]
                        ["scientific_maturity"].__setitem__("pilot", False),
                    ),
                    (
                        "work_kind",
                        lambda value: value.__setitem__(
                            "work_kind", "formal_ts"
                        ),
                    ),
                    (
                        "claim",
                        lambda value: value["specialist_owner_binding"]
                        ["candidate_search"].__setitem__(
                            "accepted_ts_claim_authorized", True
                        ),
                    ),
                ):
                    with self.subTest(label=label):
                        changed = json.loads(json.dumps(receipt))
                        mutate(changed)
                        changed_owner = SimpleNamespace(
                            validate_receipt=lambda _path, value=changed: value
                        )
                        with mock.patch.object(
                            TS, "_load_protected_qst3_input_owner",
                            return_value=changed_owner,
                        ), self.assertRaises(ValueError):
                            TS.validate_qst3_result_input_binding(
                                family_path, input_path,
                                root / "receipt.json",
                            )

    def test_new_contract_documents_are_valid_json_schemas(self) -> None:
        validator = module("protected_qst3_schema_validator", ROOT / "scripts/validate_asymmetric_contract.py")
        for relative in (
            "contracts/reaction-workflow/scientific-action-authorization-v2.schema.json",
            "contracts/rtwin-pbs/input-approval-receipt-v5.schema.json",
            "contracts/rtwin-pbs/live-submission-approval-v13.schema.json",
        ):
            with self.subTest(relative=relative):
                schema = json.loads((ROOT / relative).read_text(encoding="utf-8"))
                validator.validate_schema_document(schema)

    def test_successor_manifest_binds_the_complete_candidate_without_live_effects(self) -> None:
        path = (
            ROOT
            / "tests/fixtures/rtwin_pbs/"
            "protected_qst3_production_successor.json"
        )
        manifest = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(
            manifest["schema"],
            "auto-g16-protected-qst3-production-successor/1",
        )
        self.assertEqual(
            manifest["base_commit"],
            "2a870b2f01c6b5bafaf5dbdf4b8d952944fbdc0e",
        )
        self.assertTrue(manifest["scope"]["sole_legacy_effect_owner_retained"])
        self.assertFalse(manifest["scope"]["live_actions"])
        self.assertFalse(manifest["scope"]["historical_fixtures_rewritten"])
        self.assertEqual(
            hashlib.sha256(path.read_bytes()).hexdigest(),
            "de1d78de7ba3e4c1f40a093412734fb1e72af057763f4703a08c6fd2f599fef2",
        )
        expected_paths = {
            "contracts/execution/execution-authorization.schema.json",
            "contracts/execution/execution-request.schema.json",
            "contracts/execution/protected-submit-bundle.schema.json",
            "contracts/live-approval-replay/live-approval-effect-time-replay.schema.json",
            "contracts/reaction-workflow/scientific-action-authorization-v2.schema.json",
            "contracts/reaction-workflow/scientific-evidence-receipt.schema.json",
            "contracts/reaction-workflow/scientific-maturity-gate-v2.schema.json",
            "contracts/reaction-workflow/scientific-maturity-review-v2.schema.json",
            "contracts/reaction-workflow/scientific-maturity-review.schema.json",
            "contracts/reaction-workflow/minimum-lineage-handoff-v2.schema.json",
            "contracts/reaction-workflow/terminal-process-reconciliation.schema.json",
            "contracts/reaction-workflow/ts-freq-result-v2.schema.json",
            "contracts/rtwin-pbs/input-approval-receipt.schema.json",
            "contracts/rtwin-pbs/input-approval-receipt-v5.schema.json",
            "contracts/rtwin-pbs/input-draft-review-v2.schema.json",
            "contracts/rtwin-pbs/live-submission-approval-v13.schema.json",
            "scripts/execution_authorization.py",
            "scripts/live_approval_effect_time_replay.py",
            "scripts/protected_submit_contract.py",
            "skills/auto-g16-reaction-workflow/SKILL.md",
            "skills/auto-g16-reaction-workflow/references/scientific-maturity-owner-evidence-v2-contract.md",
            "skills/auto-g16-reaction-workflow/scripts/scientific_maturity_v2.py",
            "skills/auto-g16-reaction-workflow/scripts/scientific_maturity.py",
            "skills/auto-g16-reaction-workflow/scripts/scientific_closure_lineage.py",
            "skills/auto-g16-rtwin-pbs/SKILL.md",
            "skills/auto-g16-rtwin-pbs/references/input-approval-receipt.md",
            "skills/auto-g16-rtwin-pbs/references/live-approval-record.md",
            "skills/auto-g16-rtwin-pbs/scripts/legacy_rtwin_pbs.py",
            "skills/auto-g16-rtwin-pbs/scripts/protected_qst3_adapter.py",
            "skills/auto-g16-ts-irc/SKILL.md",
            "skills/auto-g16-ts-irc/scripts/ts_irc.py",
            "tests/test_execution_authorization.py",
            "tests/test_execution_batch_reservation_capability.py",
            "tests/test_gaussian_ts_irc.py",
            "tests/test_legacy_effect_owner.py",
            "tests/test_legacy_v254_golden.py",
            "tests/test_local_state_binding.py",
            "tests/test_protected_legacy_effect_handoff.py",
            "tests/test_protected_invocation_contract.py",
            "tests/test_protected_lifecycle_contract.py",
            "tests/test_protected_local_materialization.py",
            "tests/test_protected_owner_consumer_contract.py",
            "tests/test_protected_production_ingress_contract.py",
            "tests/test_protected_qst3_adapter.py",
            "tests/test_protected_qst3_real_chain.py",
            "tests/test_protected_runtime_state_contract.py",
            "tests/test_protected_submit_contract.py",
            "tests/test_resource_effect_time_replay_owner.py",
            "tests/test_scientific_closure_lineage.py",
            "tests/test_scientific_maturity.py",
            "tests/test_scientific_maturity_v2.py",
            "tests/test_skill_packaging.py",
        }
        self.assertEqual(set(manifest["files"]), expected_paths)
        reconciliation = json.loads(
            (
                ROOT
                / "tests/fixtures/rtwin_pbs/"
                "protected_qst3_package_reconciliation.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(
            reconciliation["schema"],
            "auto-g16-protected-qst3-package-reconciliation/1",
        )
        self.assertEqual(
            reconciliation["main"]["commit"],
            "4d4d8be1551729e527f229b91af97b40167ea748",
        )
        self.assertEqual(
            reconciliation["qst3_source"]["commit"],
            "c6aa1b8df12ed3e7f2bd8db632e65202ead98803",
        )
        self.assertFalse(
            any(relative.startswith("tests/") for relative in reconciliation["files"])
        )
        for relative, binding in reconciliation["files"].items():
            with self.subTest(relative=relative):
                self.assertEqual(
                    set(binding),
                    {
                        "main_sha256",
                        "qst3_source_sha256",
                        "sha256",
                        "change_class",
                    },
                )
                self.assertEqual(
                    hashlib.sha256(
                        (ROOT / relative).read_bytes()
                    ).hexdigest(),
                    binding["sha256"],
                )
                for hash_key in (
                    "main_sha256",
                    "qst3_source_sha256",
                    "sha256",
                ):
                    value = binding[hash_key]
                    self.assertTrue(
                        value is None
                        or re.fullmatch(r"[0-9a-f]{64}", value) is not None
                    )


if __name__ == "__main__":
    unittest.main()
