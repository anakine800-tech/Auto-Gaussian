#!/usr/bin/env python3
"""Pure-offline tests for scientific maturity and minima-first TS gates."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
TOOL = ROOT / "skills" / "auto-g16-reaction-workflow" / "scripts" / "scientific_maturity.py"
DAG_TOOL = ROOT / "skills" / "auto-g16-reaction-workflow" / "scripts" / "calculation_dag.py"
PBS_TOOL = ROOT / "skills" / "auto-g16-rtwin-pbs" / "scripts" / "gaussian_rtwin_pbs.py"
AUTO_TOOL = ROOT / "skills" / "auto-g16-rtwin-pbs" / "scripts" / "gaussian_auto.py"
TS_TOOL = ROOT / "skills" / "auto-g16-ts-irc" / "scripts" / "ts_irc.py"
FIXTURES = ROOT / "tests" / "fixtures" / "reaction_workflow"
REVIEW_SCHEMA = ROOT / "contracts" / "reaction-workflow" / "scientific-maturity-review.schema.json"
GATE_SCHEMA = ROOT / "contracts" / "reaction-workflow" / "scientific-maturity-gate.schema.json"
ACTION_AUTHORIZATION_SCHEMA = ROOT / "contracts" / "reaction-workflow" / "scientific-action-authorization.schema.json"
PATH_ACCEPTANCE_SCHEMA = ROOT / "contracts" / "reaction-workflow" / "ts-irc-path-acceptance.schema.json"

SCHEMA_VALIDATOR_PATH = ROOT / "scripts" / "validate_asymmetric_contract.py"
SCHEMA_SPEC = importlib.util.spec_from_file_location("scientific_maturity_schema_validator", SCHEMA_VALIDATOR_PATH)
assert SCHEMA_SPEC and SCHEMA_SPEC.loader
SCHEMA_VALIDATOR = importlib.util.module_from_spec(SCHEMA_SPEC)
SCHEMA_SPEC.loader.exec_module(SCHEMA_VALIDATOR)

MECHANISM_TEST_PATH = ROOT / "tests" / "test_mechanism_network.py"
SPEC = importlib.util.spec_from_file_location("scientific_maturity_mechanism_fixture", MECHANISM_TEST_PATH)
assert SPEC and SPEC.loader
MECHANISM_FIXTURE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MECHANISM_FIXTURE)

TS_PRECEDENT_TEST_PATH = ROOT / "tests" / "test_ts_precedent_map.py"
TS_PRECEDENT_SPEC = importlib.util.spec_from_file_location("scientific_maturity_ts_precedent_fixture", TS_PRECEDENT_TEST_PATH)
assert TS_PRECEDENT_SPEC and TS_PRECEDENT_SPEC.loader
TS_PRECEDENT_FIXTURE = importlib.util.module_from_spec(TS_PRECEDENT_SPEC)
TS_PRECEDENT_SPEC.loader.exec_module(TS_PRECEDENT_FIXTURE)

GAUSSIAN_LOG_PATH = ROOT / "skills" / "auto-g16-rtwin-pbs" / "scripts" / "gaussian_log.py"
GAUSSIAN_LOG_SPEC = importlib.util.spec_from_file_location("scientific_maturity_gaussian_log_fixture", GAUSSIAN_LOG_PATH)
assert GAUSSIAN_LOG_SPEC and GAUSSIAN_LOG_SPEC.loader
GAUSSIAN_LOG = importlib.util.module_from_spec(GAUSSIAN_LOG_SPEC)
GAUSSIAN_LOG_SPEC.loader.exec_module(GAUSSIAN_LOG)

TS_MODULE_SPEC = importlib.util.spec_from_file_location("scientific_maturity_ts_owner", TS_TOOL)
assert TS_MODULE_SPEC and TS_MODULE_SPEC.loader
TS_MODULE = importlib.util.module_from_spec(TS_MODULE_SPEC)
TS_MODULE_SPEC.loader.exec_module(TS_MODULE)

PBS_MODULE_SPEC = importlib.util.spec_from_file_location("scientific_maturity_pbs_owner", PBS_TOOL)
assert PBS_MODULE_SPEC and PBS_MODULE_SPEC.loader
PBS_MODULE = importlib.util.module_from_spec(PBS_MODULE_SPEC)
sys.path.insert(0, str(PBS_TOOL.parent))
try:
    PBS_MODULE_SPEC.loader.exec_module(PBS_MODULE)
finally:
    sys.path.pop(0)

TS_TEST_SPEC = importlib.util.spec_from_file_location("scientific_maturity_ts_test_fixture", ROOT / "tests" / "test_gaussian_ts_irc.py")
assert TS_TEST_SPEC and TS_TEST_SPEC.loader
TS_TEST_FIXTURE = importlib.util.module_from_spec(TS_TEST_SPEC)
TS_TEST_SPEC.loader.exec_module(TS_TEST_FIXTURE)


def canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n").encode()


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def rehash(value: dict[str, object]) -> None:
    payload = copy.deepcopy(value)
    payload.pop("payload_sha256", None)
    value["payload_sha256"] = hashlib.sha256(canonical_bytes(payload)).hexdigest()


def json_binding(path: Path) -> dict[str, object]:
    value = load_json(path)
    return {"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "size_bytes": path.stat().st_size, "schema": value["schema"]}


def blob_binding(path: Path) -> dict[str, object]:
    return {"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "size_bytes": path.stat().st_size}


class ScientificMaturityTests(unittest.TestCase):
    def run_cli(self, tool: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, str(tool), *args], cwd=ROOT, text=True, capture_output=True, check=False)

    def build_plan(self, root: Path) -> Path:
        helper = MECHANISM_FIXTURE.MechanismNetworkTests("test_help_is_offline_and_exposed")
        mechanism_path, _, result = helper.build_network(root)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        upstream = {name: load_json(root / f"{name}.json") for name in ("intake", "registry", "condition")}
        mechanism = load_json(mechanism_path)
        review = load_json(FIXTURES / "calculation_plan_review.template.json")
        review["intake_payload_sha256"] = upstream["intake"]["payload_sha256"]
        review["species_registry_payload_sha256"] = upstream["registry"]["payload_sha256"]
        review["condition_model_payload_sha256"] = upstream["condition"]["payload_sha256"]
        review["mechanism_network_payload_sha256"] = mechanism["payload_sha256"]
        draft = root / "calculation-review-draft.json"
        finalized = root / "calculation-review.json"
        plan = root / "calculation-plan.json"
        write_json(draft, review)
        result = self.run_cli(DAG_TOOL, "finalize-review", str(draft), "--output", str(finalized))
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        result = self.run_cli(
            DAG_TOOL, "build-plan", str(root / "intake.json"), str(root / "registry.json"),
            str(root / "condition.json"), str(mechanism_path), "--review", str(finalized), "--output", str(plan),
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        return plan

    def minimum_record(self, root: Path, minimum_id: str, state_id: str, atoms: list[str]) -> dict[str, object]:
        elements = ["H", "H", "I", "I", "Pd"]
        atomic_numbers = [1, 1, 53, 53, 46]
        log_path = root / f"{minimum_id}.log"
        rows = "\n".join(
            f" {index:5d} {number:10d} {0:11d} {float(index):15.6f} {0.0:12.6f} {0.0:12.6f}"
            for index, number in enumerate(atomic_numbers, start=1)
        )
        log_text = (
            " SCF Done:  E(RHF) =  -100.000000 A.U.\n"
            " Optimization completed.\n Stationary point found.\n"
            " Standard orientation:\n ----------------------------------------\n header\n ----------------------------------------\n"
            + rows
            + "\n ----------------------------------------\n"
            " Frequencies --  25.0 50.0 100.0\n"
            " Thermal correction to Gibbs Free Energy= 0.010000\n"
            " Normal termination of Gaussian\n Normal termination of Gaussian\n Normal termination of Gaussian\n"
        )
        log_path.write_text(log_text, encoding="utf-8")
        result_path = root / f"{minimum_id}-result.json"
        result = GAUSSIAN_LOG.analyze_workflow_log_text(log_text, temperature_k=298.15, standard_state="1M", expected_stages=3)
        result["chemical_identity"] = {"formula": "H2I2Pd", "charge": 0, "multiplicity": 1}
        rehash(result)
        write_json(result_path, result)
        checkpoint = root / f"{minimum_id}.chk"
        coordinates = root / f"{minimum_id}.xyz"
        checkpoint.write_bytes(f"checkpoint:{minimum_id}".encode())
        coordinates.write_text(
            f"{len(atoms)}\n{minimum_id}\n"
            + "\n".join(f"{element} {float(index)} 0.0 0.0" for index, element in enumerate(elements, start=1))
            + "\n",
            encoding="utf-8",
        )
        facts = {
            "normal_termination": True, "optimization_converged": True,
            "frequency_complete": True, "imaginary_frequency_count": 0,
            "connectivity_identity_reviewed": True, "composition_reviewed": True,
            "charge_multiplicity_reviewed": True, "atom_order_mapping_reviewed": True,
            "duplicate_reviewed": True, "weak_binding_intact_or_not_applicable": True,
            "low_frequency_flagged": True, "checkpoint_retained": True,
            "optimized_coordinates_retained": True,
        }
        return {
            "minimum_id": minimum_id, "state_id": state_id, "composition_signature": "H2I2Pd",
            "formal_charge": 0, "multiplicity": 1, "atom_order": atoms,
            "conformer_origin": {"scope": "minimum_search", "source_id": f"{minimum_id}_conformers", "ts_derivation_allowed": True},
            "source_log": blob_binding(log_path), "workflow_settings": {"temperature_k": 298.15, "standard_state": "1M", "expected_stages": 3},
            "result": json_binding(result_path), "checkpoint": blob_binding(checkpoint),
            "optimized_coordinates": blob_binding(coordinates), "acceptance_facts": facts,
            "decision": "accepted", "reviewer": "offline_fixture_reviewer", "notes": [],
        }

    def review(self, root: Path, plan: Path, *, include_end: bool = True, evidence_class: str = "direct_literature", path_accepted: bool = False) -> dict[str, object]:
        reactant_atoms = ["r_h1", "r_h2", "r_i1", "r_i2", "r_pd"]
        activated_atoms = ["m_h1", "m_h2", "m_i1", "m_i2", "m_pd"]
        minima = [self.minimum_record(root, "minimum_reactants_ok", "state_reactants", reactant_atoms)]
        if include_end:
            minima.append(self.minimum_record(root, "minimum_activated_ok", "state_activated", activated_atoms))
        lanes = []
        lane_ids = [
            "exact_system", "same_catalyst_reaction", "same_substrate_class", "bph3_hbpin_activation",
            "pyridine_regioselectivity", "active_state_ion_pair_lewis_adduct",
            "computational_mechanism_ts_irc_selectivity", "backward_citation_chain",
            "forward_citation_chain", "fulltext_si_coordinates",
        ]
        for lane_id in lane_ids:
            applicable = lane_id not in {"bph3_hbpin_activation", "pyridine_regioselectivity"}
            lanes.append({"lane_id": lane_id, "status": "searched" if applicable else "not_applicable", "scope_or_queries": [f"fixture scope {lane_id}"] if applicable else [], "evidence_refs": ["fixture_source"] if applicable else [], "limitations": ["synthetic offline fixture"]})
        plan_value = load_json(plan)
        review = {
            "schema": "gaussian-scientific-maturity-review/1", "review_id": "maturity_fixture", "study_id": plan_value["study_id"],
            "calculation_plan_payload_sha256": plan_value["payload_sha256"],
            "literature_and_user_intake": {
                "user_seeds": [{"seed_id": "seed_fixture", "kind": "doi", "value": "10.0000/offline.fixture", "authority": "verifiable_seed", "verification_status": "verified"}],
                "active_species_hypotheses": [{"hypothesis_id": "active_fixture", "description": "Reviewed fixture active state", "authority": "user_hypothesis", "status": "reviewed_hypothesis"}],
                "elementary_step_hypotheses": [{"hypothesis_id": "step_activation", "edge_id": "edge_activation", "step_type": "fixture activation", "forming_bonds": [["r_h1", "r_pd"], ["r_h2", "r_pd"]], "breaking_bonds": [["r_h1", "r_h2"]], "transferred_atom_ids": [], "selectivity_determining": True, "authority": "user_hypothesis"}],
                "experimental_intermediate_evidence": [], "coverage_lanes": lanes,
                "search_saturation": {"direct": ["fixture_source"], "analogous": [], "fulltext_or_si_missing": [], "user_provided_unverified": [], "unresolved_questions": [], "decision": "saturated_for_current_scope", "rationale": "Synthetic complete offline review."},
                "key_literature_no_obvious_omissions_confirmed": True,
            },
            "edge_reviews": [{
                "edge_id": "edge_activation", "stereochemical_channel": None, "path_role": "primary", "path_confirmed_by_user": True,
                "evidence_class": evidence_class, "evidence_refs": ["fixture_source"],
                "start_minimum_id": "minimum_reactants_ok", "end_minimum_id": "minimum_activated_ok",
                "active_species_hypothesis_id": "active_fixture", "active_species": "Reviewed fixture active state", "step_type": "fixture activation",
                "forming_bonds": [["r_h1", "r_pd"], ["r_h2", "r_pd"]], "breaking_bonds": [["r_h1", "r_h2"]],
                "transferred_atom_ids": [], "expected_reaction_coordinate": "H-H cleavage with two Pd-H contacts forming",
                "ts_strategy": {"kind": "qst2", "basis": "human_approved", "approved": True, "reviewer": "offline_fixture_reviewer", "rationale": "Synthetic endpoint-derived fixture strategy."},
                "pilot_node_ids": ["ts_candidate_primary"], "formal_ts_node_ids": ["ts_freq_activation"],
                "low_cost_scan_support": "not_run", "blockers": [],
            }],
            "minimum_records": minima,
            "pilot_and_budget": {"default_resource_tier": "simple", "primary_candidates_per_edge": 1, "competing_candidates_per_edge": 1, "no_automatic_expansion": True, "no_automatic_retry_or_chemistry_change": True, "task_budget": {"max_tasks": 4, "max_core_hours": 96, "max_concurrent": 1, "status": "within_budget"}, "resource_upgrades": []},
            "path_validation": [{"edge_id": "edge_activation", "ts_exactly_one_imaginary": path_accepted, "mode_confirmed_along_coordinate": path_accepted, "irc_forward_terminated": path_accepted, "irc_reverse_terminated": path_accepted, "irc_endpoints_identified": path_accepted, "endpoint_reopt_freq_zero_imaginary": path_accepted, "endpoint_matches_expected_minima": path_accepted, "evidence_refs": ["fixture_ts_mode_irc_endpoint_evidence"] if path_accepted else [], "ts_mode_evidence": None, "irc_path_evidence": None, "energy_lineage": None, "endpoint_reopt_minimum_ids": [], "status": "accepted" if path_accepted else "not_started", "blockers": []}],
            "reference_thermochemistry": {"common_reference_inventory": ["state_reactants", "state_activated"], "same_composition": True, "standard_state": "1M", "temperature_k": 298.15, "solvent_model_identity": "reviewed fixture solvent", "catalyst_regeneration_relation": "reviewed fixture cycle relation", "local_and_apparent_barriers_distinguished": True, "minima_and_ts_conformer_coverage": True, "weak_complex_low_frequency_flags": True, "low_frequency_policy_status": "approved_before_thermochemistry", "energies_retained": {"electronic": True, "enthalpy": True, "raw_gibbs": True, "treated_gibbs": True}, "sensitivity_scope": "few_optimized_representatives_only"},
            "stop_conditions": ["key_literature_unverified", "active_state_unresolved", "endpoint_not_minimum", "low_cost_scan_unsupported", "pilot_wrong_imaginary_mode", "xtb_or_dft_state_collapse", "composition_or_mapping_mismatch", "budget_exceeded_without_new_information"],
            "review_decision": "accepted", "reviewer": "offline_fixture_reviewer", "reviewed_at": "2026-07-17T00:00:00Z", "review_notes": ["No live action."], "payload_sha256": None,
        }
        return review

    def build_gate(self, root: Path, *, plan: Path | None = None, include_end: bool = True, evidence_class: str = "direct_literature", path_accepted: bool = False) -> tuple[Path, Path]:
        plan = plan or self.build_plan(root)
        draft = root / "maturity-review-draft.json"
        review = root / "maturity-review.json"
        gate = root / "maturity-gate.json"
        write_json(draft, self.review(root, plan, include_end=include_end, evidence_class=evidence_class, path_accepted=path_accepted))
        result = self.run_cli(TOOL, "finalize-review", str(draft), "--output", str(review))
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        result = self.run_cli(TOOL, "build", str(plan), "--review", str(review), "--output", str(gate))
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        return plan, gate

    def build_owner_gated_plan(self, root: Path) -> Path:
        helper = TS_PRECEDENT_FIXTURE.TsPrecedentMapTests("test_four_analogy_classes_and_novel_de_novo_plan_are_exactly_gated")
        prepared, precedent_path, result = helper.build_map(root)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        intake_path, registry_path, condition_path, mechanism_path = prepared["w1"][:4]
        support_path = prepared["support_path"]
        artifacts = {"intake": load_json(intake_path), "registry": load_json(registry_path), "condition": load_json(condition_path), "mechanism": load_json(mechanism_path), "support": load_json(support_path), "precedent": load_json(precedent_path)}
        review = load_json(FIXTURES / "calculation_plan_review.template.json")
        review["intake_payload_sha256"] = artifacts["intake"]["payload_sha256"]
        review["species_registry_payload_sha256"] = artifacts["registry"]["payload_sha256"]
        review["condition_model_payload_sha256"] = artifacts["condition"]["payload_sha256"]
        review["mechanism_network_payload_sha256"] = artifacts["mechanism"]["payload_sha256"]
        review["mechanism_support_payload_sha256"] = artifacts["support"]["payload_sha256"]
        review["ts_precedent_map_payload_sha256"] = artifacts["precedent"]["payload_sha256"]
        draft = root / "owner-calculation-review-draft.json"
        finalized = root / "owner-calculation-review.json"
        plan = root / "owner-calculation-plan.json"
        write_json(draft, review)
        result = self.run_cli(DAG_TOOL, "finalize-review", str(draft), "--output", str(finalized))
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        result = self.run_cli(
            DAG_TOOL, "build-plan", str(intake_path), str(registry_path), str(condition_path), str(mechanism_path),
            "--review", str(finalized), "--mechanism-support", str(support_path), "--ts-precedent-map", str(precedent_path), "--output", str(plan),
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        return plan

    def test_two_accepted_minima_open_low_cost_ts_pilot_but_preserve_owner_gates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, gate = self.build_gate(root)
            result = self.run_cli(TOOL, "validate", str(gate))
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            result = self.run_cli(TOOL, "check-action", str(gate), "--edge-id", "edge_activation", "--action", "ts_input", "--pilot")
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            formal = self.run_cli(TOOL, "check-action", str(gate), "--edge-id", "edge_activation", "--action", "ts_input")
            self.assertNotEqual(formal.returncode, 0)
            self.assertIn("mechanism_support_owner_gate_missing", formal.stderr)
            barrier = self.run_cli(TOOL, "check-action", str(gate), "--edge-id", "edge_activation", "--action", "formal_barrier_report")
            self.assertNotEqual(barrier.returncode, 0)
            artifact = load_json(gate)
            self.assertTrue(artifact["edge_gates"][0]["endpoint_pair_accepted_and_consistent"])
            pilot_node = next(item for item in artifact["dag_node_gates"] if item["node_id"] == "ts_candidate_primary")
            formal_node = next(item for item in artifact["dag_node_gates"] if item["node_id"] == "ts_freq_activation")
            self.assertEqual(pilot_node["status"], "ready_for_separate_pilot_gate")
            self.assertEqual(formal_node["status"], "blocked")
            self.assertEqual(artifact["scientific_approval_summary"]["route"], "owned_by_protocol_selection_not_this_artifact")
            for schema_path, document_path in ((REVIEW_SCHEMA, root / "maturity-review.json"), (GATE_SCHEMA, gate)):
                schema = load_json(schema_path)
                document = load_json(document_path)
                SCHEMA_VALIDATOR.validate_schema_document(schema)
                SCHEMA_VALIDATOR._validate_schema_instance(document, schema, schema)
            input_audit = root / "ts-input-audit.json"
            protocol = root / "ts-protocol.json"
            family = root / "ts-family.json"
            write_json(input_audit, {"schema": "gaussian-ts-irc-workflow/1", "valid": True})
            write_json(protocol, {
                "workflow_id": "maturity_fixture", "project_prefix": "maturity",
                "expected_reactant_identity": "fixture reactants", "expected_product_identity": "fixture activated state",
                "coordinate_changes": [{"forming": [1, 5]}],
                "routes": {"ts_freq": "#p hf/sto-3g opt=(ts) freq", "irc_forward": "#p hf/sto-3g irc=(forward)", "irc_reverse": "#p hf/sto-3g irc=(reverse)", "endpoint_opt_freq": "#p hf/sto-3g opt freq"},
                "resource_tiers": {"ts_freq": "simple", "irc": "simple", "endpoint": "simple"},
                "temperature_k": 298.15, "standard_state": "1M",
            })
            created = self.run_cli(
                TS_TOOL, "create-family", "--input-audit", str(input_audit), "--protocol", str(protocol),
                "--scientific-maturity", str(gate), "--edge-id", "edge_activation", "--node-id", "ts_candidate_primary", "--pilot", "--output", str(family),
            )
            self.assertEqual(created.returncode, 0, created.stderr or created.stdout)
            self.assertEqual(load_json(family)["schema"], "gaussian-ts-irc-workflow/2")

    def test_missing_endpoint_blocks_ts_input_and_dag_ts_nodes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, gate = self.build_gate(root, include_end=False)
            result = self.run_cli(TOOL, "check-action", str(gate), "--edge-id", "edge_activation", "--action", "ts_input")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("end_minimum_missing", result.stderr)
            artifact = load_json(gate)
            ts_nodes = [item for item in artifact["dag_node_gates"] if item["node_kind"] in {"ts_candidate", "ts_freq"} and item["status"] != "not_applicable"]
            self.assertTrue(ts_nodes)
            self.assertTrue(all(item["status"] == "blocked" for item in ts_nodes))

    def test_unreviewed_active_state_blocks_even_the_single_pilot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = self.build_plan(root)
            payload = self.review(root, plan)
            payload["literature_and_user_intake"]["active_species_hypotheses"][0]["status"] = "unresolved"
            draft = root / "unresolved-active-state.draft.json"
            review = root / "unresolved-active-state.json"
            gate = root / "unresolved-active-state-gate.json"
            write_json(draft, payload)
            finalized = self.run_cli(TOOL, "finalize-review", str(draft), "--output", str(review))
            self.assertEqual(finalized.returncode, 0, finalized.stderr or finalized.stdout)
            built = self.run_cli(TOOL, "build", str(plan), "--review", str(review), "--output", str(gate))
            self.assertEqual(built.returncode, 0, built.stderr or built.stdout)
            blocked = self.run_cli(TOOL, "check-action", str(gate), "--edge-id", "edge_activation", "--action", "ts_input", "--pilot")
            self.assertNotEqual(blocked.returncode, 0)
            self.assertIn("active_state_unresolved", blocked.stderr)

    def test_ts_dag_node_binding_rejects_non_ts_or_cross_edge_nodes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = self.build_plan(root)
            payload = self.review(root, plan)
            payload["edge_reviews"][0]["pilot_node_ids"] = ["minimum_reactants"]
            draft = root / "invalid-node-binding.draft.json"
            review = root / "invalid-node-binding.json"
            write_json(draft, payload)
            finalized = self.run_cli(TOOL, "finalize-review", str(draft), "--output", str(review))
            self.assertEqual(finalized.returncode, 0, finalized.stderr or finalized.stdout)
            blocked = self.run_cli(TOOL, "build", str(plan), "--review", str(review), "--output", str(root / "invalid-gate.json"))
            self.assertNotEqual(blocked.returncode, 0)
            self.assertIn("non-TS DAG node", blocked.stderr)

    def test_owner_validated_support_and_precedent_plus_minima_open_formal_ts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = self.build_owner_gated_plan(root)
            _, gate = self.build_gate(root, plan=plan, path_accepted=True)
            result = self.run_cli(TOOL, "check-action", str(gate), "--edge-id", "edge_activation", "--action", "ts_input")
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            irc = self.run_cli(TOOL, "check-action", str(gate), "--edge-id", "edge_activation", "--action", "irc_input")
            self.assertNotEqual(irc.returncode, 0)
            self.assertIn("owner-validated TS mode evidence", irc.stderr)
            barrier = self.run_cli(TOOL, "check-action", str(gate), "--edge-id", "edge_activation", "--action", "formal_barrier_report")
            self.assertNotEqual(barrier.returncode, 0)
            self.assertIn("owner-validated TS and bidirectional IRC evidence", barrier.stderr)

    def test_blocked_review_decision_blocks_every_action_and_ts_node(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = self.build_plan(root)
            payload = self.review(root, plan)
            payload["review_decision"] = "blocked"
            draft = root / "blocked-review.draft.json"
            review = root / "blocked-review.json"
            gate = root / "blocked-review-gate.json"
            write_json(draft, payload)
            self.assertEqual(self.run_cli(TOOL, "finalize-review", str(draft), "--output", str(review)).returncode, 0)
            built = self.run_cli(TOOL, "build", str(plan), "--review", str(review), "--output", str(gate))
            self.assertEqual(built.returncode, 0, built.stderr or built.stdout)
            for pilot in (False, True):
                args = ["check-action", str(gate), "--edge-id", "edge_activation", "--action", "ts_input"]
                if pilot:
                    args.append("--pilot")
                blocked = self.run_cli(TOOL, *args)
                self.assertNotEqual(blocked.returncode, 0)
                self.assertIn("scientific_maturity_review_not_accepted", blocked.stderr)
            ts_nodes = [item for item in load_json(gate)["dag_node_gates"] if item["node_kind"] in {"ts_candidate", "ts_freq"} and item["status"] != "not_applicable"]
            self.assertTrue(ts_nodes)
            self.assertTrue(all(item["status"] == "blocked" for item in ts_nodes))

    def test_unresolved_or_unverified_literature_gaps_block_formal_ts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = self.build_owner_gated_plan(root)
            payload = self.review(root, plan)
            payload["literature_and_user_intake"]["search_saturation"]["user_provided_unverified"] = ["unverified SI screenshot"]
            payload["literature_and_user_intake"]["search_saturation"]["unresolved_questions"] = ["active ion pair identity"]
            draft = root / "literature-gap.draft.json"
            review = root / "literature-gap.json"
            gate = root / "literature-gap-gate.json"
            write_json(draft, payload)
            self.assertEqual(self.run_cli(TOOL, "finalize-review", str(draft), "--output", str(review)).returncode, 0)
            self.assertEqual(self.run_cli(TOOL, "build", str(plan), "--review", str(review), "--output", str(gate)).returncode, 0)
            formal = self.run_cli(TOOL, "check-action", str(gate), "--edge-id", "edge_activation", "--action", "ts_input")
            self.assertNotEqual(formal.returncode, 0)
            self.assertIn("critical_literature_evidence_gaps_unresolved", formal.stderr)

    def test_ts_derivation_must_be_allowed_for_both_endpoint_minima(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = self.build_plan(root)
            payload = self.review(root, plan)
            payload["minimum_records"][0]["conformer_origin"]["ts_derivation_allowed"] = False
            draft = root / "derivation-blocked.draft.json"
            review = root / "derivation-blocked.json"
            gate = root / "derivation-blocked-gate.json"
            write_json(draft, payload)
            self.assertEqual(self.run_cli(TOOL, "finalize-review", str(draft), "--output", str(review)).returncode, 0)
            self.assertEqual(self.run_cli(TOOL, "build", str(plan), "--review", str(review), "--output", str(gate)).returncode, 0)
            pilot = self.run_cli(TOOL, "check-action", str(gate), "--edge-id", "edge_activation", "--action", "ts_input", "--pilot")
            self.assertNotEqual(pilot.returncode, 0)
            self.assertIn("ts_derivation_not_allowed", pilot.stderr)

    def test_endpoint_atom_order_must_match_mechanism_owner_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = self.build_plan(root)
            payload = self.review(root, plan)
            payload["minimum_records"][1]["atom_order"][0], payload["minimum_records"][1]["atom_order"][2] = payload["minimum_records"][1]["atom_order"][2], payload["minimum_records"][1]["atom_order"][0]
            draft = root / "mapping-mismatch.draft.json"
            review = root / "mapping-mismatch.json"
            gate = root / "mapping-mismatch-gate.json"
            write_json(draft, payload)
            self.assertEqual(self.run_cli(TOOL, "finalize-review", str(draft), "--output", str(review)).returncode, 0)
            self.assertEqual(self.run_cli(TOOL, "build", str(plan), "--review", str(review), "--output", str(gate)).returncode, 0)
            pilot = self.run_cli(TOOL, "check-action", str(gate), "--edge-id", "edge_activation", "--action", "ts_input", "--pilot")
            self.assertNotEqual(pilot.returncode, 0)
            self.assertIn("endpoint_atom_mapping_mismatch", pilot.stderr)

    def test_rehashed_handwritten_minimum_result_cannot_replace_owner_log_replay(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = self.build_plan(root)
            payload = self.review(root, plan)
            result_path = root / "minimum_reactants_ok-result.json"
            result = load_json(result_path)
            result["frequency_count"] = 999
            rehash(result)
            write_json(result_path, result)
            payload["minimum_records"][0]["result"] = json_binding(result_path)
            draft = root / "forged-minimum.draft.json"
            review = root / "forged-minimum.json"
            gate = root / "forged-minimum-gate.json"
            write_json(draft, payload)
            self.assertEqual(self.run_cli(TOOL, "finalize-review", str(draft), "--output", str(review)).returncode, 0)
            self.assertEqual(self.run_cli(TOOL, "build", str(plan), "--review", str(review), "--output", str(gate)).returncode, 0)
            pilot = self.run_cli(TOOL, "check-action", str(gate), "--edge-id", "edge_activation", "--action", "ts_input", "--pilot")
            self.assertNotEqual(pilot.returncode, 0)
            self.assertIn("minimum_not_accepted", pilot.stderr)
            minimum_gate = next(item for item in load_json(gate)["minimum_gates"] if item["minimum_id"] == "minimum_reactants_ok")
            self.assertTrue(any("owner_log_replay" in blocker for blocker in minimum_gate["blockers"]))

    def test_owner_path_acceptance_reconstructs_both_irc_endpoint_audits(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = self.build_owner_gated_plan(root)
            _, gate = self.build_gate(root, plan=plan)
            input_audit = root / "formal-input-audit.json"
            protocol = root / "formal-protocol.json"
            family = root / "formal-family.json"
            write_json(input_audit, {"schema": "gaussian-ts-irc-workflow/1", "valid": True})
            write_json(protocol, {
                "workflow_id": "formal_fixture", "project_prefix": "formal",
                "expected_reactant_identity": "fixture reactants", "expected_product_identity": "fixture product",
                "coordinate_changes": [{"forming": [1, 2]}],
                "routes": {"ts_freq": "#p hf/sto-3g opt=(ts) freq", "irc_forward": "#p hf/sto-3g irc=(forward)", "irc_reverse": "#p hf/sto-3g irc=(reverse)", "endpoint_opt_freq": "#p hf/sto-3g opt freq"},
                "resource_tiers": {"ts_freq": "simple", "irc": "simple", "endpoint": "simple"},
                "temperature_k": 298.15, "standard_state": "1M",
            })
            created = self.run_cli(TS_TOOL, "create-family", "--input-audit", str(input_audit), "--protocol", str(protocol), "--scientific-maturity", str(gate), "--edge-id", "edge_activation", "--node-id", "ts_freq_activation", "--output", str(family))
            self.assertEqual(created.returncode, 0, created.stderr or created.stdout)
            ts_result = TS_MODULE.analyze_ts_log_text(TS_TEST_FIXTURE.LOG)
            ts_result_path = root / "ts-result.json"
            write_json(ts_result_path, ts_result)
            review_dir = root / "mode-review"
            TS_MODULE.create_mode_review(ts_result, [(1, 2)], review_dir, 0.1, TS_MODULE.sha256(ts_result_path))
            mode_review = review_dir / "mode_review.json"
            mode_decision = root / "mode-decision.json"
            TS_MODULE.record_mode_decision(mode_review, "accepted", mode_decision)

            def endpoint(direction: str, side: str) -> dict[str, Path]:
                stem = f"irc_{direction}"
                irc_input = root / f"{stem}.gjf"
                irc_input.write_text(f"%oldchk=ts.chk\n%chk={stem}.chk\n%mem=12GB\n%nprocshared=8\n#p hf/sto-3g irc=(rcfc,{direction},maxpoints=2) geom=allcheck guess=read\n\n")
                log = (
                    " Charge = 0 Multiplicity = 1\n Delta-x Convergence Met\n Point Number: 1 Path Number: 1\n"
                    " Delta-x Convergence Met\n Point Number: 2 Path Number: 1\n Standard orientation:\n"
                    " ---------------------------------------------------------------------\n header\n ---------------------------------------------------------------------\n"
                    "      1          6           0        0.000000    0.000000    0.000000\n"
                    "      2          6           0        1.500000    0.000000    0.000000\n"
                    " ---------------------------------------------------------------------\n"
                    f" Calculation of {direction.upper()} path complete.\n Normal termination of Gaussian 16\n"
                )
                irc_log = root / f"{stem}.log"; irc_log.write_text(log)
                irc_result = root / f"{stem}-result.json"
                write_json(irc_result, {"schema": "gaussian-result/1", "status": "completed", "normal_termination": True, "error_termination": False, "final_energy_hartree": -10.0, "final_coordinates": [{"center": 1, "atomic_number": 6, "element": "C", "x": 0.0, "y": 0.0, "z": 0.0}, {"center": 2, "atomic_number": 6, "element": "C", "x": 1.5, "y": 0.0, "z": 0.0}]})
                checkpoint = root / f"{stem}.chk"; checkpoint.write_bytes(stem.encode())
                job = root / f"{stem}-job.json"
                write_json(job, {"schema": "gaussian-rtwin-pbs/1", "project": stem, "job_id": f"{1 if direction == 'forward' else 2}.master", "status": "completed", "results_fetched": True, "input_sha256": TS_MODULE.sha256(irc_input), "gaussian": {"checkpoint": checkpoint.name, "route": f"#p hf/sto-3g irc=(rcfc,{direction},maxpoints=2) geom=allcheck guess=read"}})
                audit_value = TS_MODULE.audit_irc_endpoint_provenance(irc_input, irc_log, irc_result, job, checkpoint, direction, side, 2, [(1, 2)])
                audit = root / f"{stem}-audit.json"; write_json(audit, audit_value)
                return {"audit": audit, "irc_input": irc_input, "irc_log": irc_log, "irc_result": irc_result, "job": job, "checkpoint": checkpoint}

            forward = endpoint("forward", "reactant")
            reverse = endpoint("reverse", "product")
            acceptance = root / "path-acceptance.json"
            built = TS_MODULE.build_path_acceptance_artifact(family, ts_result_path, mode_review, mode_decision, forward, reverse, acceptance)
            self.assertTrue(built["accepted"])
            self.assertEqual(TS_MODULE.validate_path_acceptance_artifact(acceptance)["edge_id"], "edge_activation")
            path_schema = load_json(PATH_ACCEPTANCE_SCHEMA)
            SCHEMA_VALIDATOR.validate_schema_document(path_schema)
            SCHEMA_VALIDATOR._validate_schema_instance(load_json(acceptance), path_schema, path_schema)
            forward_audit = load_json(forward["audit"])
            forward_audit["completed_point"] = 1
            write_json(forward["audit"], forward_audit)
            forged = load_json(acceptance)
            forged["forward"]["audit"] = blob_binding(forward["audit"])
            forged["payload_sha256"] = TS_MODULE._path_acceptance_payload_sha256(forged)
            write_json(acceptance, forged)
            with self.assertRaisesRegex(ValueError, "owner reconstruction|final point"):
                TS_MODULE.validate_path_acceptance_artifact(acceptance)

    def test_missing_precedent_allows_one_simple_pilot_but_not_formal_ts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, gate = self.build_gate(root, evidence_class="missing_precedent")
            formal = self.run_cli(TOOL, "check-action", str(gate), "--edge-id", "edge_activation", "--action", "ts_input")
            self.assertNotEqual(formal.returncode, 0)
            pilot = self.run_cli(TOOL, "check-action", str(gate), "--edge-id", "edge_activation", "--action", "ts_input", "--pilot", "--resource-tier", "simple")
            self.assertEqual(pilot.returncode, 0, pilot.stderr or pilot.stdout)
            expensive = self.run_cli(TOOL, "check-action", str(gate), "--edge-id", "edge_activation", "--action", "ts_input", "--pilot", "--resource-tier", "general")
            self.assertNotEqual(expensive.returncode, 0)

    def test_pbs_ts_preflight_is_fail_closed_without_maturity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, gate = self.build_gate(root)
            gjf = root / "pilot.gjf"
            gjf.write_text("%chk=pilot.chk\n%mem=12GB\n%nprocshared=8\n#p hf/sto-3g opt=(ts) freq\n\npilot\n\n0 1\nH 0 0 0\nH 0 0 1\n\n", encoding="utf-8")
            blocked = self.run_cli(PBS_TOOL, "preflight", str(gjf), "--project", "pilot")
            self.assertNotEqual(blocked.returncode, 0)
            passed = self.run_cli(PBS_TOOL, "preflight", str(gjf), "--project", "pilot", "--scientific-maturity", str(gate), "--edge-id", "edge_activation", "--node-id", "ts_candidate_primary", "--pilot", "--work-kind", "ts_pilot")
            self.assertEqual(passed.returncode, 0, passed.stderr or passed.stdout)
            report = json.loads(passed.stdout)
            self.assertEqual(next(iter(report)), "scientific_maturity")
            auto_preflight = self.run_cli(
                AUTO_TOOL, "prepare", str(gjf), "--project", "auto_pilot",
                "--local-dir", str(root / "auto_bundle"), "--scientific-maturity", str(gate),
                "--edge-id", "edge_activation", "--node-id", "ts_candidate_primary", "--pilot", "--work-kind", "ts_pilot",
            )
            self.assertEqual(auto_preflight.returncode, 0, auto_preflight.stderr or auto_preflight.stdout)
            self.assertEqual(next(iter(json.loads(auto_preflight.stdout))), "scientific_maturity")
            submit_blocked = self.run_cli(
                PBS_TOOL, "submit", str(gjf), "--project", "pilot_blocked",
                "--local-dir", str(root / "blocked_bundle"), "--confirmed", "--dry-run",
            )
            self.assertNotEqual(submit_blocked.returncode, 0)
            authorization = root / "pilot-action-authorization.json"
            authorized = self.run_cli(
                TOOL, "authorize-action", str(gate), "--input", str(gjf), "--edge-id", "edge_activation",
                "--node-id", "ts_candidate_primary", "--action", "ts_submission", "--pilot",
                "--resource-tier", "simple", "--project", "pilot_passed", "--work-kind", "ts_pilot",
                "--task-count", "1", "--estimated-core-hours", "8", "--planned-concurrency", "1",
                "--output", str(authorization),
            )
            self.assertEqual(authorized.returncode, 0, authorized.stderr or authorized.stdout)
            validated = self.run_cli(TOOL, "validate-action-authorization", str(authorization))
            self.assertEqual(validated.returncode, 0, validated.stderr or validated.stdout)
            action_schema = load_json(ACTION_AUTHORIZATION_SCHEMA)
            SCHEMA_VALIDATOR.validate_schema_document(action_schema)
            SCHEMA_VALIDATOR._validate_schema_instance(load_json(authorization), action_schema, action_schema)
            submit_passed = self.run_cli(
                PBS_TOOL, "submit", str(gjf), "--project", "pilot_passed",
                "--local-dir", str(root / "passed_bundle"), "--confirmed", "--dry-run",
                "--scientific-maturity", str(gate), "--edge-id", "edge_activation", "--node-id", "ts_candidate_primary", "--pilot", "--work-kind", "ts_pilot",
                "--scientific-action-authorization", str(authorization),
            )
            self.assertEqual(submit_passed.returncode, 0, submit_passed.stderr or submit_passed.stdout)
            dry_plan = json.loads(submit_passed.stdout)
            self.assertTrue(dry_plan["dry_run"])
            self.assertTrue(dry_plan["scientific_maturity"]["separate_live_approval_still_required"])
            self.assertEqual(
                dry_plan["input_approval"]["status"],
                "missing_required_for_live_submission",
            )
            self.assertFalse(dry_plan["live_submission_ready"])
            reused = self.run_cli(
                PBS_TOOL, "submit", str(gjf), "--project", "other_project", "--local-dir", str(root / "reused_bundle"),
                "--confirmed", "--dry-run", "--scientific-maturity", str(gate), "--edge-id", "edge_activation", "--node-id", "ts_candidate_primary",
                "--pilot", "--work-kind", "ts_pilot", "--scientific-action-authorization", str(authorization),
            )
            self.assertNotEqual(reused.returncode, 0)
            self.assertIn("project scope differs", reused.stderr)
            gjf.write_text(gjf.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            changed_input = self.run_cli(
                PBS_TOOL, "submit", str(gjf), "--project", "pilot_passed", "--local-dir", str(root / "changed_input_bundle"),
                "--confirmed", "--dry-run", "--scientific-maturity", str(gate), "--edge-id", "edge_activation", "--node-id", "ts_candidate_primary",
                "--pilot", "--work-kind", "ts_pilot", "--scientific-action-authorization", str(authorization),
            )
            self.assertNotEqual(changed_input.returncode, 0)
            self.assertIn("authorized Gaussian input file SHA-256 changed", changed_input.stderr)

    def test_pbs_protected_route_classifier_covers_ts_scan_and_irc(self) -> None:
        self.assertEqual(PBS_MODULE.classify_protected_work("#p hf/sto-3g opt=(ts,calcfc) freq"), "ts")
        self.assertEqual(PBS_MODULE.classify_protected_work("#p hf/sto-3g opt=modredundant"), "ts_scan")
        self.assertEqual(PBS_MODULE.classify_protected_work("#p hf/sto-3g irc=(forward,rcfc) geom=allcheck"), "irc")
        self.assertIsNone(PBS_MODULE.classify_protected_work("#p hf/sto-3g opt freq"))


if __name__ == "__main__":
    unittest.main()
