#!/usr/bin/env python3
"""Offline tests for normalized energies, analysis, uncertainty, and reports."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
WORKFLOW_SCRIPTS = ROOT / "skills" / "auto-g16-reaction-workflow" / "scripts"
LITERATURE_SCRIPTS = ROOT / "skills" / "auto-g16-reaction-literature" / "scripts"
PROTOCOL_SCRIPTS = ROOT / "skills" / "auto-g16-rtwin-pbs" / "scripts"
for directory in (WORKFLOW_SCRIPTS, LITERATURE_SCRIPTS, PROTOCOL_SCRIPTS):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

import reaction_analysis as analysis
import reaction_orchestrator as orchestrator
import reaction_workflow as rw


SCHEMA_VALIDATOR_PATH = ROOT / "scripts" / "validate_asymmetric_contract.py"
SCHEMA_SPEC = importlib.util.spec_from_file_location("reaction_analysis_schema_validator", SCHEMA_VALIDATOR_PATH)
assert SCHEMA_SPEC and SCHEMA_SPEC.loader
SCHEMA_VALIDATOR = importlib.util.module_from_spec(SCHEMA_SPEC)
SCHEMA_SPEC.loader.exec_module(SCHEMA_VALIDATOR)


def write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class ReactionAnalysisTests(unittest.TestCase):
    def build_chain(self, root: Path) -> dict[str, object]:
        from tests.test_reaction_orchestrator import ReactionOrchestratorTests

        helper = ReactionOrchestratorTests("test_main_group_candidate_is_materialized_but_not_calculation_ready")
        chain = helper.build_supported_chain(root, nonmetal=True)
        network = chain["network"]
        nodes = []
        for state in network["states"]:
            nodes.append({
                "node_id": f"minimum_{state['state_id']}", "node_type": "minimum_opt_freq",
                "target_kind": "state", "target_id": state["state_id"], "candidate": None,
                "protocol_selection": None, "dependencies": [], "required": True,
                "completion": {"status": "not_started", "rationale": "Synthetic contract fixture; no calculation was run."},
                "evidence": [], "review_status": "reviewed_plan", "blockers": [], "notes": [],
            })
        for edge in network["edges"]:
            nodes.append({
                "node_id": f"ts_{edge['edge_id']}", "node_type": "transition_state_opt_freq",
                "target_kind": "edge", "target_id": edge["edge_id"], "candidate": None,
                "protocol_selection": None, "dependencies": [], "required": True,
                "completion": {"status": "not_started", "rationale": "Synthetic contract fixture; no calculation was run."},
                "evidence": [], "review_status": "reviewed_plan", "blockers": [], "notes": [],
            })
        compute_ids = [item["node_id"] for item in nodes]
        nodes.extend([
            {
                "node_id": "thermochemistry_all", "node_type": "thermochemistry", "target_kind": "study",
                "target_id": network["study_id"], "candidate": None, "protocol_selection": None,
                "dependencies": compute_ids, "required": True,
                "completion": {"status": "not_started", "rationale": "Awaiting reviewed energy records."},
                "evidence": [], "review_status": "reviewed_plan", "blockers": [], "notes": [],
            },
            {
                "node_id": "kinetics_all", "node_type": "kinetics", "target_kind": "study",
                "target_id": network["study_id"], "candidate": None, "protocol_selection": None,
                "dependencies": ["thermochemistry_all"], "required": True,
                "completion": {"status": "not_started", "rationale": "Awaiting thermochemistry."},
                "evidence": [], "review_status": "reviewed_plan", "blockers": [], "notes": [],
            },
            {
                "node_id": "bounded_report_all", "node_type": "report", "target_kind": "study",
                "target_id": network["study_id"], "candidate": None, "protocol_selection": None,
                "dependencies": ["kinetics_all"], "required": True,
                "completion": {"status": "not_started", "rationale": "Awaiting bounded analysis."},
                "evidence": [], "review_status": "reviewed_plan", "blockers": [], "notes": [],
            },
        ])
        dag_review = {
            "schema": orchestrator.DAG_REVIEW_SCHEMA,
            "study_id": network["study_id"],
            "mechanism_network_payload_sha256": network["payload_sha256"],
            "ts_precedent_payload_sha256": chain["ts_map"]["payload_sha256"],
            "nodes": nodes,
            "review_decision": "accepted_with_blockers",
            "review_notes": ["Finite synthetic analysis DAG; no execution authority."],
        }
        dag_review_path = root / "analysis_dag_review.json"
        write_json(dag_review_path, dag_review)
        dag_path = root / "analysis_dag.json"
        dag = orchestrator.build_dag(chain["network_path"], chain["ts_map_path"], dag_review_path, dag_path)
        index_path = root / "analysis_index.json"
        index = orchestrator.build_index(chain["network_path"], chain["support_path"], chain["ts_map_path"], dag_path, [], index_path)
        chain.update({"dag_review_path": dag_review_path, "dag_path": dag_path, "dag": dag, "index_path": index_path, "index": index})
        return chain

    def build_energy(
        self,
        chain: dict[str, object],
        root: Path,
        *,
        record_id: str,
        target_kind: str,
        target_id: str,
        energy_kcal_mol: float,
        conformer_id: str,
        degeneracy: int = 1,
        temperature_k: float = 298.15,
    ) -> tuple[Path, dict[str, object]]:
        source = {
            "schema": analysis.SYNTHETIC_RESULT_SCHEMA,
            "study_id": chain["network"]["study_id"],
            "record_id": record_id,
            "electronic_energy_hartree": -100.0 + energy_kcal_mol / analysis.HARTREE_TO_KCAL_MOL,
            "thermal_gibbs_correction_hartree": 0.0,
            "temperature_k": temperature_k,
            "standard_state": "1M",
            "optimization_success": True,
            "normal_termination": True,
            "imaginary_frequency_count": 0 if target_kind == "state" else 1,
            "calculation_ready": False,
            "no_submission_authorization": True,
        }
        rw.finalize_artifact(source)
        source_path = root / f"source_{record_id}.json"
        rw.write_json(source_path, source)
        review = {
            "schema": analysis.ENERGY_REVIEW_SCHEMA,
            "study_id": chain["network"]["study_id"],
            "mechanism_network_payload_sha256": chain["network"]["payload_sha256"],
            "calculation_dag_payload_sha256": chain["dag"]["payload_sha256"],
            "record_id": record_id,
            "target_kind": target_kind,
            "target_id": target_id,
            "dag_node_id": f"minimum_{target_id}" if target_kind == "state" else f"ts_{target_id}",
            "conformer_id": conformer_id,
            "energy_model_id": "synthetic_model",
            "source_kind": "synthetic_fixture",
            "source_result": rw._artifact_ref(source_path),
            "source_fields": {
                "electronic_energy_hartree": "/electronic_energy_hartree",
                "thermal_gibbs_correction_hartree": "/thermal_gibbs_correction_hartree",
                "temperature_k": "/temperature_k",
                "standard_state": "/standard_state",
                "optimization_success": "/optimization_success",
                "normal_termination": "/normal_termination",
                "imaginary_frequency_count": "/imaginary_frequency_count",
            },
            "standard_state_correction_kcal_mol": 0.0,
            "low_frequency_correction_kcal_mol": 0.0,
            "low_frequency_policy": "No correction; synthetic contract fixture only.",
            "comparison_energy_definition": "Synthetic electronic energy plus explicit zero-valued correction fields.",
            "degeneracy": degeneracy,
            "mode_review": None,
            "mode_decision": None,
            "review_decision": "accepted_with_blockers",
            "review_notes": ["Synthetic values validate contracts and have no scientific meaning."],
        }
        review_path = root / f"review_{record_id}.json"
        write_json(review_path, review)
        output = root / f"energy_{record_id}.json"
        artifact = analysis.build_energy_record(chain["network_path"], chain["dag_path"], review_path, output)
        return output, artifact

    def build_energy_set(self, chain: dict[str, object], root: Path, *, direct_barrier: float = 10.0) -> tuple[list[Path], list[dict[str, object]]]:
        specs = [
            ("energy_reactant_a", "state", "state_reactants", 0.0, "reactant_conformer_a", 1),
            ("energy_reactant_b", "state", "state_reactants", 0.5, "reactant_conformer_b", 2),
            ("energy_activated_a", "state", "state_activated", 3.0, "activated_conformer_a", 1),
            ("energy_products_a", "state", "state_products", -6.0, "product_conformer_a", 1),
            ("energy_direct_ts", "edge", "edge_direct", direct_barrier, "direct_ts_conformer", 1),
            ("energy_competing_ts", "edge", "edge_activation", 11.5, "competing_ts_conformer", 1),
            ("energy_release_ts", "edge", "edge_release", 12.0, "release_ts_conformer", 1),
        ]
        paths, records = [], []
        for record_id, target_kind, target_id, energy, conformer, degeneracy in specs:
            path, record = self.build_energy(
                chain, root, record_id=record_id, target_kind=target_kind, target_id=target_id,
                energy_kcal_mol=energy, conformer_id=conformer, degeneracy=degeneracy,
            )
            paths.append(path)
            records.append(record)
        return paths, records

    def analysis_review(self, chain: dict[str, object], records: list[dict[str, object]], *, decision: str = "accepted") -> dict[str, object]:
        return {
            "schema": analysis.ANALYSIS_REVIEW_SCHEMA,
            "study_id": chain["network"]["study_id"],
            "mechanism_network_payload_sha256": chain["network"]["payload_sha256"],
            "calculation_dag_payload_sha256": chain["dag"]["payload_sha256"],
            "energy_record_payload_sha256s": [item["payload_sha256"] for item in records],
            "temperature_k": 298.15,
            "standard_state": "1M",
            "energy_model_id": "synthetic_model",
            "reference_state_id": "state_reactants",
            "activity_factors": [
                {"edge_id": "edge_direct", "activity_product": 1.0, "rationale": "Explicit dimensionless fixture activity."},
                {"edge_id": "edge_activation", "activity_product": 1.0, "rationale": "Explicit dimensionless fixture activity."},
            ],
            "selectivity_groups": [{
                "group_id": "group_competing_channels", "label": "Synthetic competing channels",
                "edge_ids": ["edge_direct", "edge_activation"],
                "rationale": "Both reviewed fixture edges start from the same state.",
            }],
            "uncertainty_scenarios": [
                {
                    "scenario_id": "compressed_gap",
                    "energy_offsets_kcal_mol": [
                        {"record_id": "energy_direct_ts", "offset_kcal_mol": 0.5},
                        {"record_id": "energy_competing_ts", "offset_kcal_mol": -0.5},
                    ],
                    "rationale": "Compress the synthetic channel gap by one kcal/mol.",
                },
                {
                    "scenario_id": "expanded_gap",
                    "energy_offsets_kcal_mol": [
                        {"record_id": "energy_direct_ts", "offset_kcal_mol": -0.5},
                        {"record_id": "energy_competing_ts", "offset_kcal_mol": 0.5},
                    ],
                    "rationale": "Expand the synthetic channel gap by one kcal/mol.",
                },
            ],
            "review_decision": decision,
            "review_notes": ["Synthetic full-analysis contract fixture only."],
        }

    def test_full_energy_analysis_uncertainty_and_report_chain(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            chain = self.build_chain(root)
            energy_paths, records = self.build_energy_set(chain, root)
            for path, record in zip(energy_paths, records, strict=True):
                self.assertFalse(record["scientific_claim_eligible"])
                self.assertEqual(record["record_status"], "retained_not_claim_eligible")
                analysis.validate_energy_record(path)
            review = self.analysis_review(chain, records)
            review_path = root / "analysis_review.json"
            write_json(review_path, review)
            analysis_path = root / "reaction_analysis.json"
            artifact = analysis.build_analysis(chain["network_path"], chain["dag_path"], energy_paths, review_path, analysis_path)
            self.assertEqual(artifact["analysis_status"], "complete_for_contract_fixture")
            self.assertEqual(artifact["claim_ceiling"], "contract_fixture_only")
            self.assertFalse(artifact["scientific_claim_eligible"])
            self.assertFalse(artifact["mechanism_proven"])
            self.assertEqual(artifact["blockers"], [])
            direct = next(item for item in artifact["baseline"]["edges"] if item["edge_id"] == "edge_direct")
            competing = next(item for item in artifact["baseline"]["edges"] if item["edge_id"] == "edge_activation")
            self.assertAlmostEqual(competing["barrier_kcal_mol"] - direct["barrier_kcal_mol"], 1.5, places=8)
            selectivity = artifact["baseline"]["selectivities"][0]
            direct_fraction = next(item["fraction"] for item in selectivity["fractions"] if item["edge_id"] == "edge_direct")
            self.assertGreater(direct_fraction, 0.9)
            direct_range = next(item for item in artifact["uncertainty"]["selectivity_ranges"] if item["edge_id"] == "edge_direct")
            self.assertLess(direct_range["minimum_fraction"], direct_fraction)
            self.assertGreater(direct_range["maximum_fraction"], direct_fraction)
            analysis.validate_analysis(analysis_path)

            report_review = {
                "schema": analysis.REPORT_REVIEW_SCHEMA,
                "study_id": chain["network"]["study_id"],
                "study_index_payload_sha256": chain["index"]["payload_sha256"],
                "analysis_payload_sha256": artifact["payload_sha256"],
                "title": "Synthetic bounded reaction workflow report",
                "review_decision": "accepted",
                "review_notes": ["This report is a deterministic contract fixture."],
            }
            report_review_path = root / "report_review.json"
            write_json(report_review_path, report_review)
            markdown_path = root / "reaction_report.md"
            report_path = root / "reaction_report.json"
            report = analysis.build_report(chain["index_path"], analysis_path, report_review_path, markdown_path, report_path)
            self.assertEqual(report["claim_ceiling"], "contract_fixture_only")
            self.assertEqual(report["report_status"], "bounded_complete")
            self.assertIn("does not prove the mechanism", markdown_path.read_text(encoding="utf-8"))
            analysis.validate_report(report_path)

            for schema_name, instance in (
                ("energy-record.schema.json", records[0]),
                ("reaction-analysis.schema.json", artifact),
                ("reaction-report.schema.json", report),
            ):
                schema = json.loads((ROOT / "contracts" / "reaction-workflow" / schema_name).read_text(encoding="utf-8"))
                SCHEMA_VALIDATOR.validate_schema_document(schema)
                SCHEMA_VALIDATOR._validate_schema_instance(instance, schema, schema)
            markdown_path.write_text(markdown_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            with self.assertRaisesRegex(rw.OfflineError, "markdown identity mismatch"):
                analysis.validate_report(report_path)

    def test_hash_drift_and_mixed_conditions_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            chain = self.build_chain(root)
            energy_paths, records = self.build_energy_set(chain, root)
            drift_source = root / "source_energy_direct_ts.json"
            drift_source.write_text(drift_source.read_text(encoding="utf-8") + " ", encoding="utf-8")
            with self.assertRaisesRegex(rw.OfflineError, "identity mismatch"):
                analysis.validate_energy_record(next(path for path in energy_paths if path.name == "energy_energy_direct_ts.json"))

            # Rebuild cleanly in a second directory to test cross-record conditions.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            chain = self.build_chain(root)
            energy_paths, records = self.build_energy_set(chain, root)
            warm_path, warm = self.build_energy(
                chain, root, record_id="energy_warm_extra", target_kind="state", target_id="state_products",
                energy_kcal_mol=-6.0, conformer_id="warm_product_conformer", temperature_k=310.0,
            )
            review = self.analysis_review(chain, records + [warm])
            review_path = root / "mixed_review.json"
            write_json(review_path, review)
            with self.assertRaisesRegex(rw.OfflineError, "mixed energy-record temperatures"):
                analysis.build_analysis(chain["network_path"], chain["dag_path"], energy_paths + [warm_path], review_path, root / "mixed.json")

    def test_formal_electronic_only_energy_cannot_enter_comparison_layer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            chain = self.build_chain(root)
            self.build_energy_set(chain, root)
            review = json.loads((root / "review_energy_direct_ts.json").read_text(encoding="utf-8"))
            formal_record = {
                "schema": "gaussian-reviewed-energy-record/1",
                "comparison_eligible": False,
                "calculation_ready": False,
                "no_submission_authorization": True,
            }
            rw.finalize_artifact(formal_record)
            formal_path = root / "formal_electronic_only_energy.json"
            write_json(formal_path, formal_record)
            review["source_kind"] = "reviewed_calculation_result"
            review["source_result"] = rw._artifact_ref(formal_path)
            review_path = root / "formal_energy_reaction_review.json"
            write_json(review_path, review)
            with self.assertRaisesRegex(
                rw.OfflineError,
                "electronic-only and comparison_eligible: false",
            ):
                analysis.build_energy_record(
                    chain["network_path"], chain["dag_path"], review_path,
                    root / "forbidden_comparison_energy.json",
                )

    def test_legacy_result_file_evidence_uses_canonical_fields_and_remains_gated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            chain = self.build_chain(root)
            result = {
                "schema": "gaussian-opt-freq-sp-result/1",
                "status": "completed",
                "execution_complete": True,
                "frequency_complete": True,
                "minimum_validated": True,
                "workflow_success": True,
                "optimization_success": True,
                "normal_termination": True,
                "imaginary_frequency_count": 0,
                "thermochemistry": {
                    "single_point_energy_hartree": -100.0,
                    "thermal_correction_gibbs_hartree": 0.01,
                    "temperature_k": 298.15,
                    "standard_state": "1M",
                },
            }
            result_path = root / "legacy_minimum_result.json"
            write_json(result_path, result)
            dag_review = json.loads(chain["dag_review_path"].read_text(encoding="utf-8"))
            node = next(item for item in dag_review["nodes"] if item["node_id"] == "minimum_state_reactants")
            node["completion"] = {"status": "terminal_evidence_reviewed", "rationale": "Immutable legacy result was reviewed."}
            node["evidence"] = [orchestrator._file_ref(result_path, result)]
            terminal_review_path = root / "terminal_dag_review.json"
            write_json(terminal_review_path, dag_review)
            terminal_dag_path = root / "terminal_dag.json"
            terminal_dag = orchestrator.build_dag(chain["network_path"], chain["ts_map_path"], terminal_review_path, terminal_dag_path)
            terminal_node = next(item for item in terminal_dag["nodes"] if item["node_id"] == "minimum_state_reactants")
            self.assertEqual(terminal_node["readiness"], "completed_with_reviewed_evidence")
            self.assertNotIn("payload_sha256", terminal_node["evidence"][0])
            orchestrator.validate_dag(terminal_dag_path)

            energy_review = {
                "schema": analysis.ENERGY_REVIEW_SCHEMA,
                "study_id": chain["network"]["study_id"],
                "mechanism_network_payload_sha256": chain["network"]["payload_sha256"],
                "calculation_dag_payload_sha256": terminal_dag["payload_sha256"],
                "record_id": "legacy_minimum_energy",
                "target_kind": "state",
                "target_id": "state_reactants",
                "dag_node_id": "minimum_state_reactants",
                "conformer_id": "legacy_minimum_conformer",
                "energy_model_id": "legacy_model",
                "source_kind": "reviewed_calculation_result",
                "source_result": rw._artifact_ref(result_path),
                "source_fields": dict(analysis.REAL_SOURCE_FIELD_BINDINGS[result["schema"]]),
                "standard_state_correction_kcal_mol": 0.0,
                "low_frequency_correction_kcal_mol": 0.0,
                "low_frequency_policy": "Canonical legacy result reports no quasi-harmonic correction.",
                "comparison_energy_definition": "Canonical single-point plus thermal Gibbs correction.",
                "degeneracy": 1,
                "mode_review": None,
                "mode_decision": None,
                "review_decision": "accepted",
                "review_notes": ["Result binding test; candidate and protocol remain intentionally absent."],
            }
            energy_review_path = root / "legacy_energy_review.json"
            write_json(energy_review_path, energy_review)
            energy_path = root / "legacy_energy.json"
            energy = analysis.build_energy_record(chain["network_path"], terminal_dag_path, energy_review_path, energy_path)
            self.assertFalse(energy["scientific_claim_eligible"])
            limitations = " ".join(energy["claim_limitations"])
            self.assertNotIn("not complete with reviewed terminal evidence", limitations)
            self.assertNotIn("not listed as immutable evidence", limitations)
            self.assertIn("no reviewed candidate binding", limitations)
            self.assertIn("no reviewed protocol-selection binding", limitations)
            analysis.validate_energy_record(energy_path)

            bad_review = dict(energy_review)
            bad_review["source_fields"] = dict(energy_review["source_fields"])
            bad_review["source_fields"]["electronic_energy_hartree"] = "/thermochemistry/temperature_k"
            bad_review_path = root / "bad_legacy_energy_review.json"
            write_json(bad_review_path, bad_review)
            with self.assertRaisesRegex(rw.OfflineError, "canonical source-field bindings"):
                analysis.build_energy_record(chain["network_path"], terminal_dag_path, bad_review_path, root / "bad_legacy_energy.json")

            dag_schema = json.loads((ROOT / "contracts" / "reaction-workflow" / "calculation-dag.schema.json").read_text(encoding="utf-8"))
            energy_schema = json.loads((ROOT / "contracts" / "reaction-workflow" / "energy-record.schema.json").read_text(encoding="utf-8"))
            SCHEMA_VALIDATOR._validate_schema_instance(terminal_dag, dag_schema, dag_schema)
            SCHEMA_VALIDATOR._validate_schema_instance(energy, energy_schema, energy_schema)

    def test_asymmetric_ts_result_preserves_parsed_mode_lineage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            chain = self.build_chain(root)
            parsed = {"schema": "gaussian-ts-freq-result/1", "status": "completed", "raw_imaginary_frequency_count": 1}
            parsed_path = root / "parsed_ts.json"
            write_json(parsed_path, parsed)
            parsed_sha = rw.sha256_file(parsed_path)
            mode_review = {
                "schema": "gaussian-ts-mode-review/1", "ts_result_sha256": parsed_sha,
                "scientific_decision": "required",
            }
            mode_review_path = root / "mode_review.json"
            write_json(mode_review_path, mode_review)
            mode_decision = {
                "schema": "gaussian-ts-mode-decision/1",
                "mode_review_sha256": rw.sha256_file(mode_review_path),
                "ts_result_sha256": parsed_sha,
                "decision": "accepted", "confirmed": True,
            }
            mode_decision_path = root / "mode_decision.json"
            write_json(mode_decision_path, mode_decision)
            result = {
                "schema": "gaussian-asymmetric-ts-result/1",
                "validation_level": "mode_reviewed",
                "artifacts": {
                    "parsed_ts_result": {"path": str(parsed_path), "sha256": parsed_sha},
                    "mode_review": {"path": str(mode_review_path), "sha256": rw.sha256_file(mode_review_path)},
                    "mode_decision": {"path": str(mode_decision_path), "sha256": rw.sha256_file(mode_decision_path)},
                },
                "termination": {"stationary_point": True, "normal_termination": True},
                "frequency_evidence": {"raw_imaginary_frequency_count": 1},
                "energies": {
                    "energy_unit": "hartree", "electronic_energy": -99.98,
                    "thermal_gibbs_correction": 0.01, "temperature_k": 298.15,
                    "standard_state": "1M",
                },
                "comparison_eligibility": {"eligible": True, "reasons": []},
            }
            result_path = root / "asymmetric_ts_result.json"
            write_json(result_path, result)
            dag_review = json.loads(chain["dag_review_path"].read_text(encoding="utf-8"))
            node = next(item for item in dag_review["nodes"] if item["node_id"] == "ts_edge_direct")
            node["completion"] = {"status": "terminal_evidence_reviewed", "rationale": "Aggregate TS result and mode lineage were reviewed."}
            node["evidence"] = [orchestrator._file_ref(result_path, result)]
            terminal_review_path = root / "ts_terminal_dag_review.json"
            write_json(terminal_review_path, dag_review)
            terminal_dag_path = root / "ts_terminal_dag.json"
            terminal_dag = orchestrator.build_dag(chain["network_path"], chain["ts_map_path"], terminal_review_path, terminal_dag_path)
            review = {
                "schema": analysis.ENERGY_REVIEW_SCHEMA,
                "study_id": chain["network"]["study_id"],
                "mechanism_network_payload_sha256": chain["network"]["payload_sha256"],
                "calculation_dag_payload_sha256": terminal_dag["payload_sha256"],
                "record_id": "reviewed_ts_energy",
                "target_kind": "edge", "target_id": "edge_direct",
                "dag_node_id": "ts_edge_direct", "conformer_id": "reviewed_ts_conformer",
                "energy_model_id": "reviewed_ts_model",
                "source_kind": "reviewed_calculation_result",
                "source_result": rw._artifact_ref(result_path),
                "source_fields": dict(analysis.REAL_SOURCE_FIELD_BINDINGS[result["schema"]]),
                "standard_state_correction_kcal_mol": 0.0,
                "low_frequency_correction_kcal_mol": 0.0,
                "low_frequency_policy": "No additional correction in this lineage test.",
                "comparison_energy_definition": "Aggregate TS electronic plus thermal Gibbs correction.",
                "degeneracy": 1,
                "mode_review": rw._artifact_ref(mode_review_path),
                "mode_decision": rw._artifact_ref(mode_decision_path),
                "review_decision": "accepted",
                "review_notes": ["Parsed-result mode lineage is accepted; candidate/protocol remain absent."],
            }
            review_path = root / "reviewed_ts_energy_review.json"
            write_json(review_path, review)
            output = root / "reviewed_ts_energy.json"
            record = analysis.build_energy_record(chain["network_path"], terminal_dag_path, review_path, output)
            self.assertTrue(record["stationary_point_audit"]["intended_mode_accepted"])
            self.assertFalse(record["scientific_claim_eligible"])
            self.assertNotIn("unique imaginary mode lacks", " ".join(record["claim_limitations"]))
            analysis.validate_energy_record(output)

    def test_negative_barrier_blocks_kinetics_without_erasing_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            chain = self.build_chain(root)
            energy_paths, records = self.build_energy_set(chain, root, direct_barrier=-1.0)
            review = self.analysis_review(chain, records, decision="accepted_with_blockers")
            review_path = root / "negative_review.json"
            write_json(review_path, review)
            output = root / "negative_analysis.json"
            artifact = analysis.build_analysis(chain["network_path"], chain["dag_path"], energy_paths, review_path, output)
            self.assertEqual(artifact["analysis_status"], "incomplete")
            self.assertIn("negative_edge_direct_barrier", {item["blocker_id"] for item in artifact["blockers"]})
            direct = next(item for item in artifact["baseline"]["edges"] if item["edge_id"] == "edge_direct")
            self.assertIsNone(direct["rate_constant_s_inv"])
            self.assertEqual(direct["kinetics_status"], "negative_barrier_requires_model_review")
            analysis.validate_analysis(output)
            report_review = {
                "schema": analysis.REPORT_REVIEW_SCHEMA,
                "study_id": chain["network"]["study_id"],
                "study_index_payload_sha256": chain["index"]["payload_sha256"],
                "analysis_payload_sha256": artifact["payload_sha256"],
                "title": "Blocked synthetic kinetics report",
                "review_decision": "accepted",
                "review_notes": ["The negative barrier is retained as an explicit blocker."],
            }
            report_review_path = root / "negative_report_review.json"
            write_json(report_review_path, report_review)
            markdown_path = root / "negative_report.md"
            report_path = root / "negative_report.json"
            report = analysis.build_report(chain["index_path"], output, report_review_path, markdown_path, report_path)
            self.assertEqual(report["report_status"], "bounded_incomplete")
            self.assertIn("negative", markdown_path.read_text(encoding="utf-8").lower())
            analysis.validate_report(report_path)
            analysis_schema = json.loads((ROOT / "contracts" / "reaction-workflow" / "reaction-analysis.schema.json").read_text(encoding="utf-8"))
            report_schema = json.loads((ROOT / "contracts" / "reaction-workflow" / "reaction-report.schema.json").read_text(encoding="utf-8"))
            SCHEMA_VALIDATOR._validate_schema_instance(artifact, analysis_schema, analysis_schema)
            SCHEMA_VALIDATOR._validate_schema_instance(report, report_schema, report_schema)

    def test_negative_barrier_in_uncertainty_scenario_blocks_the_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            chain = self.build_chain(root)
            energy_paths, records = self.build_energy_set(chain, root)
            review = self.analysis_review(chain, records)
            review["uncertainty_scenarios"] = [{
                "scenario_id": "negative_gap",
                "energy_offsets_kcal_mol": [
                    {"record_id": "energy_direct_ts", "offset_kcal_mol": -20.0}
                ],
                "rationale": "Adversarial sensitivity fixture that creates a negative barrier.",
            }]
            review_path = root / "scenario_negative_review.json"
            write_json(review_path, review)
            with self.assertRaisesRegex(rw.OfflineError, "derived blockers"):
                analysis.build_analysis(
                    chain["network_path"], chain["dag_path"], energy_paths,
                    review_path, root / "scenario_negative_unqualified.json",
                )

            review["review_decision"] = "accepted_with_blockers"
            write_json(review_path, review)
            output = root / "scenario_negative_analysis.json"
            artifact = analysis.build_analysis(
                chain["network_path"], chain["dag_path"], energy_paths,
                review_path, output,
            )
            blocker_ids = {item["blocker_id"] for item in artifact["blockers"]}
            self.assertIn("scenario_negative_gap_edge_direct_negative_barrier", blocker_ids)
            self.assertIn("scenario_negative_gap_group_competing_channels_selectivity", blocker_ids)
            scenario = next(
                item for item in artifact["uncertainty"]["scenarios"]
                if item["scenario_id"] == "negative_gap"
            )
            direct = next(
                item for item in scenario["model"]["edges"]
                if item["edge_id"] == "edge_direct"
            )
            self.assertIsNone(direct["rate_constant_s_inv"])
            self.assertEqual(direct["kinetics_status"], "negative_barrier_requires_model_review")
            self.assertEqual(artifact["analysis_status"], "incomplete")
            analysis.validate_analysis(output)

    def test_analysis_cli_and_schemas_are_offline_and_closed(self) -> None:
        script = WORKFLOW_SCRIPTS / "reaction_analysis.py"
        for command in ("build-energy", "validate-energy", "build-analysis", "validate-analysis", "build-report", "validate-report"):
            result = subprocess.run([sys.executable, str(script), command, "--help"], cwd=ROOT, check=False, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        for name in ("energy-record.schema.json", "reaction-analysis.schema.json", "reaction-report.schema.json"):
            schema = json.loads((ROOT / "contracts" / "reaction-workflow" / name).read_text(encoding="utf-8"))
            self.assertFalse(schema["additionalProperties"])
            SCHEMA_VALIDATOR.validate_schema_document(schema)


if __name__ == "__main__":
    unittest.main()
