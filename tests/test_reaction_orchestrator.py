#!/usr/bin/env python3
"""Offline tests for candidate materialization, calculation DAGs, and indexes."""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).parents[1]
WORKFLOW_SCRIPTS = ROOT / "skills" / "auto-g16-reaction-workflow" / "scripts"
LITERATURE_SCRIPTS = ROOT / "skills" / "auto-g16-reaction-literature" / "scripts"
PROTOCOL_SCRIPTS = ROOT / "skills" / "auto-g16-rtwin-pbs" / "scripts"
for directory in (WORKFLOW_SCRIPTS, LITERATURE_SCRIPTS, PROTOCOL_SCRIPTS):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

import reaction_orchestrator as orchestrator
import reaction_workflow as rw
import calculation_artifacts as formal_adapter


SCHEMA_VALIDATOR_PATH = ROOT / "scripts" / "validate_asymmetric_contract.py"
SCHEMA_SPEC = importlib.util.spec_from_file_location("orchestrator_schema_validator", SCHEMA_VALIDATOR_PATH)
assert SCHEMA_SPEC and SCHEMA_SPEC.loader
SCHEMA_VALIDATOR = importlib.util.module_from_spec(SCHEMA_SPEC)
SCHEMA_SPEC.loader.exec_module(SCHEMA_VALIDATOR)


def write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class ReactionOrchestratorTests(unittest.TestCase):
    def build_supported_chain(self, root: Path, *, nonmetal: bool = True) -> dict[str, object]:
        from tests.reaction_ultimate_fixture import build_supported_chain

        return build_supported_chain(root, nonmetal=nonmetal)

    def build_candidate(self, chain: dict[str, object], root: Path) -> tuple[Path, dict[str, object]]:
        precedent = next(item for item in chain["ts_map"]["records"] if item["candidate_construction_gate"] == "candidate_construction_eligible")
        review = {
            "schema": orchestrator.CANDIDATE_REVIEW_SCHEMA,
            "study_id": chain["ts_map"]["study_id"],
            "ts_precedent_payload_sha256": chain["ts_map"]["payload_sha256"],
            "precedent_id": precedent["precedent_id"],
            "candidate_id": "main_group_ts_seed_a",
            "candidate_kind": "transition_state_seed",
            "review_decision": "accepted",
            "review_notes": ["Synthetic main-group coordinate materialization fixture only."],
        }
        review_path = root / "candidate_review.json"
        write_json(review_path, review)
        output = root / "candidate.json"
        xyz = root / "candidate.xyz"
        candidate = orchestrator.build_candidate(chain["ts_map_path"], review_path, xyz, output)
        return output, candidate

    def build_state_candidate(self, chain: dict[str, object], root: Path) -> tuple[Path, dict[str, object]]:
        state = next(item for item in chain["network"]["states"] if item["state_id"] == "state_reactants")
        source = ROOT / "tests" / "fixtures" / "reaction_workflow" / "ts_precedent_source_main_group.xyz"
        atom_order = [
            {"atom_id": atom_id, "element": element}
            for atom_id, element in (("r_h1", "H"), ("r_h2", "H"), ("r_i1", "I"), ("r_i2", "I"), ("r_pd", "B"))
        ]
        self.assertEqual({item["atom_id"] for item in state["atoms"]}, {item["atom_id"] for item in atom_order})
        review = {
            "schema": orchestrator.STATE_CANDIDATE_REVIEW_SCHEMA,
            "study_id": chain["network"]["study_id"],
            "mechanism_network_payload_sha256": chain["network"]["payload_sha256"],
            "state_id": state["state_id"],
            "candidate_id": "reactant_complex_seed_a",
            "candidate_kind": "complex_seed",
            "coordinate_source": {"path": str(source), "sha256": rw.sha256_file(source), "size_bytes": source.stat().st_size},
            "atom_order": atom_order,
            "geometry_provenance": "explicit_reviewed_complex_coordinates",
            "review_decision": "accepted",
            "review_notes": ["Synthetic disconnected reactant-complex fixture only."],
        }
        review_path = root / "state_candidate_review.json"
        write_json(review_path, review)
        output = root / "state_candidate.json"
        xyz = root / "state_candidate.xyz"
        candidate = orchestrator.build_state_candidate(chain["network_path"], review_path, xyz, output)
        return output, candidate

    def build_dag(self, chain: dict[str, object], candidate_path: Path, candidate: dict[str, object], root: Path, state_candidate_path: Path | None = None, state_candidate: dict[str, object] | None = None) -> tuple[Path, dict[str, object]]:
        study_id = chain["network"]["study_id"]
        state_ids = [item["state_id"] for item in chain["network"]["states"]]
        minimum_state_id = state_candidate["target"]["state_id"] if state_candidate is not None else state_ids[0]
        edge_id = chain["network"]["edges"][0]["edge_id"]
        nodes = [
            {
                "node_id": "minimum_reactants", "node_type": "minimum_opt_freq",
                "target_kind": "state", "target_id": minimum_state_id, "candidate": None if state_candidate is None else orchestrator._rich_ref(state_candidate_path, state_candidate),
                "protocol_selection": None, "dependencies": [], "required": True,
                "completion": {"status": "not_started", "rationale": "No calculation has been authorized or run."},
                "evidence": [], "review_status": "reviewed_plan", "blockers": [], "notes": [],
            },
            {
                "node_id": "ts_direct", "node_type": "transition_state_opt_freq",
                "target_kind": "edge", "target_id": edge_id,
                "candidate": orchestrator._rich_ref(candidate_path, candidate),
                "protocol_selection": None, "dependencies": [], "required": True,
                "completion": {"status": "not_started", "rationale": "No calculation has been authorized or run."},
                "evidence": [], "review_status": "reviewed_plan", "blockers": [], "notes": [],
            },
            {
                "node_id": "irc_direct_forward", "node_type": "irc_forward",
                "target_kind": "edge", "target_id": edge_id,
                "candidate": orchestrator._rich_ref(candidate_path, candidate),
                "protocol_selection": None, "dependencies": ["ts_direct"], "required": True,
                "completion": {"status": "not_started", "rationale": "IRC remains separately gated."},
                "evidence": [], "review_status": "reviewed_plan", "blockers": [], "notes": [],
            },
            {
                "node_id": "irc_direct_reverse", "node_type": "irc_reverse",
                "target_kind": "edge", "target_id": edge_id,
                "candidate": orchestrator._rich_ref(candidate_path, candidate),
                "protocol_selection": None, "dependencies": ["ts_direct"], "required": True,
                "completion": {"status": "not_started", "rationale": "IRC remains separately gated."},
                "evidence": [], "review_status": "reviewed_plan", "blockers": [], "notes": [],
            },
            {
                "node_id": "thermochemistry_profile", "node_type": "thermochemistry",
                "target_kind": "study", "target_id": study_id, "candidate": None,
                "protocol_selection": None, "dependencies": ["minimum_reactants", "ts_direct", "irc_direct_forward", "irc_direct_reverse"], "required": True,
                "completion": {"status": "not_started", "rationale": "Energy evidence is not available."},
                "evidence": [], "review_status": "reviewed_plan", "blockers": [], "notes": [],
            },
            {
                "node_id": "kinetics_model", "node_type": "kinetics",
                "target_kind": "study", "target_id": study_id, "candidate": None,
                "protocol_selection": None, "dependencies": ["thermochemistry_profile"], "required": True,
                "completion": {"status": "not_started", "rationale": "Thermochemistry is incomplete."},
                "evidence": [], "review_status": "reviewed_plan", "blockers": [], "notes": [],
            },
            {
                "node_id": "bounded_report", "node_type": "report",
                "target_kind": "study", "target_id": study_id, "candidate": None,
                "protocol_selection": None, "dependencies": ["kinetics_model"], "required": True,
                "completion": {"status": "not_started", "rationale": "Analysis is incomplete."},
                "evidence": [], "review_status": "reviewed_plan", "blockers": [], "notes": [],
            },
        ]
        review = {
            "schema": orchestrator.DAG_REVIEW_SCHEMA,
            "study_id": study_id,
            "mechanism_network_payload_sha256": chain["network"]["payload_sha256"],
            "ts_precedent_payload_sha256": chain["ts_map"]["payload_sha256"],
            "nodes": nodes,
            "review_decision": "accepted_with_blockers",
            "review_notes": ["Finite offline DAG fixture; no execution authority."],
        }
        review_path = root / "dag_review.json"
        write_json(review_path, review)
        output = root / "calculation_dag.json"
        dag = orchestrator.build_dag(chain["network_path"], chain["ts_map_path"], review_path, output)
        return output, dag

    def test_main_group_candidate_is_materialized_but_not_calculation_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            chain = self.build_supported_chain(root)
            for diagnostic in chain["network"]["diagnostics"]["network_catalyst_projection_closure"]:
                self.assertTrue(diagnostic["catalyst_cycle_closed"])
            network_schema = json.loads((ROOT / "contracts" / "reaction-workflow" / "mechanism-network.schema.json").read_text(encoding="utf-8"))
            SCHEMA_VALIDATOR._validate_schema_instance(chain["network"], network_schema, network_schema)
            candidate_path, candidate = self.build_candidate(chain, root)
            self.assertEqual(candidate["candidate_status"], "materialized_for_offline_review")
            self.assertTrue(candidate["requires_visible_review"])
            self.assertFalse(candidate["calculation_ready"])
            self.assertTrue(candidate["no_input_render_authorization"])
            self.assertTrue(candidate["no_submission_authorization"])
            self.assertEqual({atom["element"] for atom in candidate["atoms"]}, {"B", "H", "I"})
            orchestrator.validate_candidate(candidate_path)
            tampered_candidate = copy.deepcopy(candidate)
            tampered_candidate["target"]["stereochemical_channel"] = "tampered_channel"
            rw.finalize_artifact(tampered_candidate)
            tampered_candidate_path = root / "candidate_rebound_tamper.json"
            write_json(tampered_candidate_path, tampered_candidate)
            with self.assertRaisesRegex(rw.OfflineError, "target differs from its accepted precedent"):
                orchestrator.validate_candidate(tampered_candidate_path)

            state_candidate_path, state_candidate = self.build_state_candidate(chain, root)
            self.assertEqual(state_candidate["candidate_kind"], "complex_seed")
            self.assertEqual(state_candidate["target"]["component_count"], 3)
            self.assertTrue(state_candidate["requires_visible_review"])
            self.assertFalse(state_candidate["calculation_ready"])
            orchestrator.validate_state_candidate(state_candidate_path)
            tampered_state_candidate = copy.deepcopy(state_candidate)
            tampered_state_candidate["unreviewed_override"] = True
            rw.finalize_artifact(tampered_state_candidate)
            tampered_state_path = root / "state_candidate_rebound_tamper.json"
            write_json(tampered_state_path, tampered_state_candidate)
            with self.assertRaisesRegex(rw.OfflineError, "unknown fields"):
                orchestrator.validate_state_candidate(tampered_state_path)

            invalid_review = json.loads((root / "state_candidate_review.json").read_text(encoding="utf-8"))
            invalid_review["candidate_id"] = "invalid_minimum_seed"
            invalid_review["candidate_kind"] = "minimum_seed"
            invalid_review["geometry_provenance"] = "reviewed_structure_coordinates"
            invalid_review_path = root / "invalid_minimum_review.json"
            write_json(invalid_review_path, invalid_review)
            with self.assertRaisesRegex(rw.OfflineError, "minimum_seed requires a reviewed single-component"):
                orchestrator.build_state_candidate(chain["network_path"], invalid_review_path, root / "invalid_minimum.xyz", root / "invalid_minimum.json")
            for schema_name, instance in (
                ("candidate-materialization.schema.json", candidate),
                ("state-candidate-materialization.schema.json", state_candidate),
            ):
                schema = json.loads((ROOT / "contracts" / "reaction-workflow" / schema_name).read_text(encoding="utf-8"))
                SCHEMA_VALIDATOR._validate_schema_instance(instance, schema, schema)

    def test_relative_inputs_and_nested_outputs_remain_validatable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            chain = self.build_supported_chain(root)
            precedent = next(
                item for item in chain["ts_map"]["records"]
                if item["candidate_construction_gate"] == "candidate_construction_eligible"
            )
            review = {
                "schema": orchestrator.CANDIDATE_REVIEW_SCHEMA,
                "study_id": chain["ts_map"]["study_id"],
                "ts_precedent_payload_sha256": chain["ts_map"]["payload_sha256"],
                "precedent_id": precedent["precedent_id"],
                "candidate_id": "relative_nested_seed",
                "candidate_kind": "transition_state_seed",
                "review_decision": "accepted",
                "review_notes": ["Relative-path regression fixture; no scientific claim."],
            }
            review_path = root / "relative_candidate_review.json"
            write_json(review_path, review)
            previous_directory = Path.cwd()
            os.chdir(root)
            try:
                artifact = orchestrator.build_candidate(
                    chain["ts_map_path"].relative_to(root),
                    review_path.relative_to(root),
                    Path("nested/relative_seed.xyz"),
                    Path("nested/relative_candidate.json"),
                )
                self.assertTrue(Path(artifact["geometry"]["path"]).is_absolute())
                checked = orchestrator.validate_candidate(Path("nested/relative_candidate.json"))
                self.assertEqual(checked["candidate_id"], "relative_nested_seed")
            finally:
                os.chdir(previous_directory)

    def test_transition_metal_candidate_materialization_remains_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            chain = self.build_supported_chain(root, nonmetal=False)
            precedent = chain["ts_map"]["records"][0]
            review = {
                "schema": orchestrator.CANDIDATE_REVIEW_SCHEMA,
                "study_id": chain["ts_map"]["study_id"],
                "ts_precedent_payload_sha256": chain["ts_map"]["payload_sha256"],
                "precedent_id": precedent["precedent_id"],
                "candidate_id": "metal_ts_seed_refused",
                "candidate_kind": "transition_state_seed",
                "review_decision": "accepted",
                "review_notes": ["Refusal test."],
            }
            review_path = root / "metal_candidate_review.json"
            write_json(review_path, review)
            with self.assertRaisesRegex(rw.OfflineError, "transition-metal candidate materialization remains unsupported"):
                orchestrator.build_candidate(chain["ts_map_path"], review_path, root / "metal.xyz", root / "metal.json")

    def test_calculation_dag_and_study_index_are_derived_and_non_authorizing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            chain = self.build_supported_chain(root)
            candidate_path, candidate = self.build_candidate(chain, root)
            state_candidate_path, state_candidate = self.build_state_candidate(chain, root)
            dag_path, dag = self.build_dag(chain, candidate_path, candidate, root, state_candidate_path, state_candidate)
            self.assertEqual(dag["gate_status"], "reviewed_with_blockers")
            self.assertFalse(dag["execution_authorized"])
            self.assertFalse(dag["calculation_ready"])
            self.assertIn("ts_direct_protocol_missing", {item["blocker_id"] for item in dag["blockers"]})
            self.assertEqual(next(item for item in dag["nodes"] if item["node_id"] == "ts_direct")["readiness"], "blocked_missing_protocol")
            orchestrator.validate_dag(dag_path)

            index_path = root / "study_index.json"
            index = orchestrator.build_index(chain["network_path"], chain["support_path"], chain["ts_map_path"], dag_path, [candidate_path, state_candidate_path], index_path)
            self.assertTrue(index["status_is_derived_not_editable"])
            self.assertFalse(index["execution_authorized"])
            self.assertIn("review_protocol_candidates", {item["action"] for item in index["next_safe_actions"]})
            self.assertNotIn("materialize_reviewed_candidates", {item["action"] for item in index["next_safe_actions"]})
            orchestrator.validate_index(index_path)
            for schema_name, instance in (
                ("calculation-dag.schema.json", dag),
                ("orchestration-index.schema.json", index),
            ):
                schema = json.loads((ROOT / "contracts" / "reaction-workflow" / schema_name).read_text(encoding="utf-8"))
                SCHEMA_VALIDATOR._validate_schema_instance(instance, schema, schema)

    def test_dag_rejects_cycles_and_unbound_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            chain = self.build_supported_chain(root)
            candidate_path, candidate = self.build_candidate(chain, root)
            dag_path, _ = self.build_dag(chain, candidate_path, candidate, root)
            review_path = root / "dag_review.json"
            review = json.loads(review_path.read_text(encoding="utf-8"))
            review["nodes"][0]["dependencies"] = ["bounded_report"]
            cycle_path = root / "dag_cycle_review.json"
            write_json(cycle_path, review)
            with self.assertRaisesRegex(rw.OfflineError, "dependency cycle"):
                orchestrator.build_dag(chain["network_path"], chain["ts_map_path"], cycle_path, root / "cycle.json")
            self.assertTrue(dag_path.is_file())

    def test_dag_delegates_formal_adapter_evidence_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            chain = self.build_supported_chain(root)
            candidate_path, candidate = self.build_candidate(chain, root)
            self.build_dag(chain, candidate_path, candidate, root)
            review = json.loads((root / "dag_review.json").read_text(encoding="utf-8"))
            forged_lineage = {
                "schema": "gaussian-energy-lineage/1",
                "comparison_eligible": False,
                "calculation_ready": False,
                "no_submission_authorization": True,
            }
            rw.finalize_artifact(forged_lineage)
            forged_path = root / "forged_formal_energy_lineage.json"
            write_json(forged_path, forged_lineage)
            review["nodes"][0]["evidence"] = [
                orchestrator._rich_ref(forged_path, forged_lineage)
            ]
            review_path = root / "dag_formal_evidence_review.json"
            write_json(review_path, review)
            with self.assertRaisesRegex(
                rw.OfflineError,
                "formal calculation-artifact evidence failed its owning validator",
            ):
                orchestrator.build_dag(
                    chain["network_path"], chain["ts_map_path"], review_path,
                    root / "dag_with_forged_formal_evidence.json",
                )

    def test_formal_adapter_evidence_cannot_complete_an_unmapped_dag_node(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            chain = self.build_supported_chain(root)
            candidate_path, candidate = self.build_candidate(chain, root)
            self.build_dag(chain, candidate_path, candidate, root)
            review = json.loads((root / "dag_review.json").read_text(encoding="utf-8"))
            formal_evidence = {
                "schema": "gaussian-sanitized-job-observation/1",
                "calculation_ready": False,
                "no_submission_authorization": True,
            }
            rw.finalize_artifact(formal_evidence)
            formal_path = root / "formal_job_observation.json"
            write_json(formal_path, formal_evidence)
            node = review["nodes"][0]
            node["evidence"] = [orchestrator._rich_ref(formal_path, formal_evidence)]
            node["completion"] = {
                "status": "terminal_evidence_reviewed",
                "rationale": "Deliberately invalid cross-object completion claim.",
            }
            terminal_review_path = root / "dag_unmapped_terminal_review.json"
            write_json(terminal_review_path, review)
            with mock.patch.object(formal_adapter, "validate_artifact", return_value=None):
                with self.assertRaisesRegex(rw.OfflineError, "external-target-to-DAG mapping"):
                    orchestrator.build_dag(
                        chain["network_path"], chain["ts_map_path"], terminal_review_path,
                        root / "dag_unmapped_terminal.json",
                    )

                node["completion"] = {
                    "status": "not_started",
                    "rationale": "Evidence is retained pending reviewed target mapping.",
                }
                pending_review_path = root / "dag_unmapped_pending_review.json"
                write_json(pending_review_path, review)
                dag = orchestrator.build_dag(
                    chain["network_path"], chain["ts_map_path"], pending_review_path,
                    root / "dag_unmapped_pending.json",
                )
            retained_node = next(item for item in dag["nodes"] if item["node_id"] == node["node_id"])
            self.assertEqual(retained_node["readiness"], "blocked_by_review")
            self.assertIn(
                "Validated formal calculation-artifact evidence is retained, but its external target has no reviewed mapping to this DAG node.",
                retained_node["blockers"],
            )

    def test_orchestrator_schemas_are_closed_and_cli_is_offline(self) -> None:
        script = WORKFLOW_SCRIPTS / "reaction_orchestrator.py"
        for command in ("build-candidate", "build-state-candidate", "validate-candidate", "build-dag", "validate-dag", "build-index", "validate-index"):
            result = subprocess.run([sys.executable, str(script), command, "--help"], cwd=ROOT, check=False, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        for name in ("candidate-materialization.schema.json", "state-candidate-materialization.schema.json", "calculation-dag.schema.json", "study-index.schema.json"):
            schema = json.loads((ROOT / "contracts" / "reaction-workflow" / name).read_text(encoding="utf-8"))
            self.assertFalse(schema["additionalProperties"])
            SCHEMA_VALIDATOR.validate_schema_document(schema)


if __name__ == "__main__":
    unittest.main()
