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
MATURITY_SPEC = importlib.util.spec_from_file_location("scientific_maturity_owner_under_test", TOOL)
assert MATURITY_SPEC and MATURITY_SPEC.loader
MATURITY_MODULE = importlib.util.module_from_spec(MATURITY_SPEC); MATURITY_SPEC.loader.exec_module(MATURITY_MODULE)

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

ASYM_TOOL = ROOT / "skills" / "auto-g16-asymmetric-catalysis" / "scripts" / "asymmetric_catalysis.py"
ASYM_SPEC = importlib.util.spec_from_file_location("scientific_maturity_asymmetric_consumer", ASYM_TOOL)
assert ASYM_SPEC and ASYM_SPEC.loader
ASYM_MODULE = importlib.util.module_from_spec(ASYM_SPEC)
ASYM_SPEC.loader.exec_module(ASYM_MODULE)

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
            f" {index:5d} {number:10d} {0:11d} {float(index):15.6f} {(1.0 if index == 3 else 0.0):12.6f} {0.0:12.6f}"
            for index, number in enumerate(atomic_numbers, start=1)
        )
        log_text = (
            " SCF Done:  E(RHF) =  -100.000000 A.U.\n"
            " Optimization completed.\n Stationary point found.\n"
            " Standard orientation:\n ----------------------------------------\n header\n ----------------------------------------\n"
            + rows
            + "\n ----------------------------------------\n"
            " Frequencies --  25.0 50.0 75.0\n"
            " Frequencies --  100.0 125.0 150.0\n"
            " Frequencies --  175.0 200.0 225.0\n"
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
            + "\n".join(f"{element} {float(index)} {1.0 if index == 3 else 0.0} 0.0" for index, element in enumerate(elements, start=1))
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

    def test_real_path_acceptance_v2_is_replayed_by_scientific_maturity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); plan = self.build_owner_gated_plan(root); _, initial_gate = self.build_gate(root, plan=plan)
            plan_document = load_json(plan); mechanism_path = root / plan_document["mechanism_network"]["path"]
            mechanism = load_json(mechanism_path); edge = next(item for item in mechanism["edges"] if item["edge_id"] == "edge_activation")
            states = {item["state_id"]: item for item in mechanism["states"]}; from_state, to_state = states[edge["from_state_id"]], states[edge["to_state_id"]]
            elements = [atom["element"] for atom in from_state["atoms"]]; numbers = {"H": 1, "I": 53, "Pd": 46}; coordinates = [(float(index), 1.0 if index == 3 else 0.0, 0.0) for index in range(1, 6)]
            route = "#p hf/sto-3g opt=(ts,calcfc) freq"
            ts_input = root / "formal_ts.gjf"; ts_input.write_text("%chk=formal_ts.chk\n" + route + "\n\nformal fixture\n\n0 1\n" + "\n".join(f"{element} {x} {y} {z}" for element, (x, y, z) in zip(elements, coordinates)) + "\n\n")
            input_audit = root / "formal-v2-input-audit.json"; write_json(input_audit, TS_MODULE.validate_input_family("single_guess", {"ts": TS_MODULE.parse_cartesian_input(ts_input)}, [1, 2, 3, 4, 5]))
            forward_route = "#p hf/sto-3g irc=(rcfc,forward,maxpoints=2) geom=allcheck guess=read"
            reverse_route = "#p hf/sto-3g irc=(rcfc,reverse,maxpoints=2) geom=allcheck guess=read"
            protocol = root / "formal-v2-protocol.json"; write_json(protocol, {"workflow_id": "formal_fixture", "project_prefix": "formal", "expected_reactant_identity": "fixture reactants", "expected_product_identity": "fixture activated", "coordinate_changes": [{"forming": [1, 5]}], "routes": {"ts_freq": route, "irc_forward": forward_route, "irc_reverse": reverse_route, "endpoint_opt_freq": "#p hf/sto-3g opt freq"}, "resource_tiers": {"ts_freq": "simple", "irc": "simple", "endpoint": "simple"}, "temperature_k": 298.15, "standard_state": "1M"})
            family = root / "formal-v2-family.json"; created = self.run_cli(TS_TOOL, "create-family", "--input-audit", str(input_audit), "--protocol", str(protocol), "--scientific-maturity", str(initial_gate), "--edge-id", "edge_activation", "--node-id", "ts_freq_activation", "--output", str(family)); self.assertEqual(created.returncode, 0, created.stderr)

            orientation = "\n".join(f" {index} {numbers[element]} 0 {x:.6f} {y:.6f} {z:.6f}" for index, (element, (x, y, z)) in enumerate(zip(elements, coordinates), 1))
            frequencies = [-500.0] + [float(value) for value in range(100, 900, 100)]
            blocks = []
            for offset in range(0, 9, 3):
                values = frequencies[offset:offset + 3]
                displacement = "\n".join(f" {index} {numbers[element]} 0.1 0 0 0 0.1 0 0 0 0.1" for index, element in enumerate(elements, 1))
                blocks.append(" Frequencies -- " + " ".join(str(value) for value in values) + "\n Red. masses -- 1 1 1\n Atom AN X Y Z X Y Z X Y Z\n" + displacement)
            ts_log = root / "formal_ts.log"; ts_log.write_text(" Gaussian 16, Revision C.01,\n Charge = 0 Multiplicity = 1\n Optimization completed.\n Stationary point found.\n Standard orientation:\n ----------------------------------------\n header\n ----------------------------------------\n" + orientation + "\n ----------------------------------------\n" + "\n".join(blocks) + "\n SCF Done: E(RHF) = -100.0 A.U.\n Normal termination of Gaussian\n")
            project, job_id, attempt_id = "formal_ts", "20.master", "qsub-attempt-formal-ts"
            inspection = {"schema": "gaussian-job-inspection/2", "project": project, "job_id": job_id, "state": "completed", "collected_at": "2026-07-19T12:00:00Z", "source": "single_remote_read_only_snapshot", "freshness": "fresh", "transport_classification": "success", "transport_returncode": 0, "termination_counts_known": True, "evidence_conflict": False, "process_alive": False, "log_size": ts_log.stat().st_size, "full_normal_termination_count": 1, "full_error_termination_count": 0}; inspection["evidence_sha256"] = TS_MODULE._transport_digest(inspection)
            receipt = {"schema": "gaussian-terminal-inspection-receipt/1", "project": project, "job_id": job_id, "input_stem": ts_input.stem, "input_sha256": TS_MODULE.sha256(ts_input), "attempt_id": attempt_id, "terminal_state": "completed", "collected_at": inspection["collected_at"], "inspection_evidence_sha256": inspection["evidence_sha256"], "inspection": inspection, "scientific_acceptance": False}; receipt["receipt_sha256"] = TS_MODULE._transport_digest(receipt)
            receipt_path = root / "formal-ts-terminal.json"; write_json(receipt_path, receipt)
            ts_checkpoint = root / "formal_ts.chk"; ts_checkpoint.write_bytes(b"accepted formal TS checkpoint")
            log_digest = TS_MODULE.sha256(ts_log); checkpoint_digest = TS_MODULE.sha256(ts_checkpoint); snapshot = {"schema": "gaussian-fetch-snapshot/1", "project": project, "job_id": job_id, "input_stem": ts_input.stem, "input_sha256": TS_MODULE.sha256(ts_input), "snapshot_complete": True, "terminal_inspection_receipt_sha256": receipt["receipt_sha256"], "per_hop_sha256_verified": True, "exact_log": ts_log.name, "artifacts": {ts_log.name: {"sha256": log_digest, "size": ts_log.stat().st_size}, ts_checkpoint.name: {"sha256": checkpoint_digest, "size": ts_checkpoint.stat().st_size}}, "per_hop": {ts_log.name: {"server_sha256": log_digest, "rtwin_sha256": log_digest, "mac_sha256": log_digest, "size": ts_log.stat().st_size}, ts_checkpoint.name: {"server_sha256": checkpoint_digest, "rtwin_sha256": checkpoint_digest, "mac_sha256": checkpoint_digest, "size": ts_checkpoint.stat().st_size}}}; snapshot["payload_sha256"] = TS_MODULE._transport_digest(snapshot)
            snapshot_path = root / "formal-ts-transfer.json"; write_json(snapshot_path, snapshot)
            job = {"schema": "gaussian-rtwin-pbs/1", "project": project, "job_id": job_id, "status": "completed", "results_fetched": True, "input_sha256": TS_MODULE.sha256(ts_input), "execution_batch": {"attempt_id": attempt_id}, "terminal_inspection_receipt_sha256": receipt["receipt_sha256"], "fetch_snapshot_sha256": TS_MODULE.sha256(snapshot_path), "fetch_snapshot_size": snapshot_path.stat().st_size}
            job_path = root / "formal-ts-job.json"; write_json(job_path, job)
            ts_result_path = root / "formal-ts-result.json"; ts_result = TS_MODULE.build_ts_result_v2(ts_log, ts_result_path, {"family": family, "input": ts_input, "job": job_path, "terminal_inspection_receipt": receipt_path, "fetch_snapshot": snapshot_path})
            mode_dir = root / "formal-mode"; TS_MODULE.create_mode_review(ts_result, [(1, 5)], mode_dir, 0.1, TS_MODULE.sha256(ts_result_path)); mode_review = mode_dir / "mode_review.json"; mode_decision = root / "formal-mode-decision.json"; TS_MODULE.record_mode_decision(mode_review, "accepted", mode_decision)
            checkpoint_audit = root / "formal-ts-checkpoint-audit.json"; write_json(checkpoint_audit, TS_MODULE.audit_checkpoint_provenance(ts_input, ts_log, ts_result_path, ts_checkpoint, mode_review, mode_decision, owner_dir=root))
            irc_plan = root / "formal-irc-plan.json"; write_json(irc_plan, TS_MODULE.build_irc_plan(load_json(family), ts_result_path, ts_checkpoint, mode_review, mode_decision, "C.01", forward_route, reverse_route, "formal_forward", "formal_reverse"))

            def endpoint(direction: str, side: str, state: dict[str, object], serial: int) -> Path:
                stem = f"formal_{direction}"; irc_input = root / f"{stem}.gjf"; exact_route = forward_route if direction == "forward" else reverse_route
                TS_MODULE.build_allcheck_irc_input(checkpoint_audit, ts_checkpoint, irc_input, exact_route, direction, "12GB", 8)
                allcheck_manifest = irc_input.with_suffix(".json")
                rows = "\n".join(f" {index} {numbers[element]} 0 {x:.6f} {y:.6f} {z:.6f}" for index, (element, (x, y, z)) in enumerate(zip(elements, coordinates), 1))
                log = root / f"{stem}.log"; log.write_text(" Charge = 0 Multiplicity = 1\n Delta-x Convergence Met\n Point Number: 1 Path Number: 1\n Delta-x Convergence Met\n Point Number: 2 Path Number: 1\n Standard orientation:\n ----------------------------------------\n header\n ----------------------------------------\n" + rows + "\n ----------------------------------------\n" + f" Calculation of {direction.upper()} path complete.\n Normal termination of Gaussian 16\n")
                result_path = root / f"{stem}-result.json"; write_json(result_path, {"schema": "gaussian-result/1", "status": "completed", "normal_termination": True, "error_termination": False, "final_energy_hartree": -100.0, "final_coordinates": [{"center": index, "atomic_number": numbers[element], "element": element, "x": x, "y": y, "z": z} for index, (element, (x, y, z)) in enumerate(zip(elements, coordinates), 1)]})
                checkpoint = root / f"{stem}.chk"; checkpoint.write_bytes(stem.encode()); endpoint_job_id = f"{serial}.master"; endpoint_attempt = f"qsub-attempt-{stem}"
                endpoint_inspection = {"schema": "gaussian-job-inspection/2", "project": stem, "job_id": endpoint_job_id, "state": "completed", "collected_at": "2026-07-19T12:00:00Z", "source": "single_remote_read_only_snapshot", "freshness": "fresh", "transport_classification": "success", "transport_returncode": 0, "termination_counts_known": True, "evidence_conflict": False, "process_alive": False, "log_size": log.stat().st_size, "full_normal_termination_count": 1, "full_error_termination_count": 0}; endpoint_inspection["evidence_sha256"] = TS_MODULE._transport_digest(endpoint_inspection)
                endpoint_receipt = {"schema": "gaussian-terminal-inspection-receipt/1", "project": stem, "job_id": endpoint_job_id, "input_stem": irc_input.stem, "input_sha256": TS_MODULE.sha256(irc_input), "attempt_id": endpoint_attempt, "terminal_state": "completed", "collected_at": endpoint_inspection["collected_at"], "inspection_evidence_sha256": endpoint_inspection["evidence_sha256"], "inspection": endpoint_inspection, "scientific_acceptance": False}; endpoint_receipt["receipt_sha256"] = TS_MODULE._transport_digest(endpoint_receipt)
                endpoint_receipt_path = root / f"{stem}-terminal.json"; write_json(endpoint_receipt_path, endpoint_receipt)
                artifacts = {}; hops = {}
                for source in (log, result_path, checkpoint):
                    digest = TS_MODULE.sha256(source); artifacts[source.name] = {"sha256": digest, "size": source.stat().st_size}; hops[source.name] = {"server_sha256": digest, "rtwin_sha256": digest, "mac_sha256": digest, "size": source.stat().st_size}
                endpoint_snapshot = {"schema": "gaussian-fetch-snapshot/1", "project": stem, "job_id": endpoint_job_id, "input_stem": irc_input.stem, "input_sha256": TS_MODULE.sha256(irc_input), "snapshot_complete": True, "terminal_inspection_receipt_sha256": endpoint_receipt["receipt_sha256"], "per_hop_sha256_verified": True, "exact_log": log.name, "artifacts": artifacts, "per_hop": hops}; endpoint_snapshot["payload_sha256"] = TS_MODULE._transport_digest(endpoint_snapshot)
                endpoint_snapshot_path = root / f"{stem}-transfer.json"; write_json(endpoint_snapshot_path, endpoint_snapshot)
                endpoint_job = {"schema": "gaussian-rtwin-pbs/1", "project": stem, "job_id": endpoint_job_id, "status": "completed", "results_fetched": True, "input_sha256": TS_MODULE.sha256(irc_input), "execution_batch": {"attempt_id": endpoint_attempt}, "terminal_inspection_receipt_sha256": endpoint_receipt["receipt_sha256"], "fetch_snapshot_sha256": TS_MODULE.sha256(endpoint_snapshot_path), "fetch_snapshot_size": endpoint_snapshot_path.stat().st_size, "gaussian": {"checkpoint": checkpoint.name, "route": exact_route}}
                endpoint_job_path = root / f"{stem}-job.json"; write_json(endpoint_job_path, endpoint_job)
                audit_value = TS_MODULE.audit_irc_endpoint_provenance(irc_input, log, result_path, endpoint_job_path, checkpoint, direction, side, 2, [(1, 5)], ts_checkpoint_path=ts_checkpoint, checkpoint_audit_path=checkpoint_audit, irc_plan_path=irc_plan, allcheck_manifest_path=allcheck_manifest); audit_path = root / f"{stem}-audit.json"; write_json(audit_path, audit_value)
                stable_ids = [atom["atom_id"] for atom in state["atoms"]]; draft = {"schema": "gaussian-endpoint-structure-review-draft/1", "review_id": f"{stem}_review", "direction": direction, "chemical_side": side, "stable_atom_ids": stable_ids, "structure_identity": {"state_id": state["state_id"], "identity_label": f"reviewed {side} fixture", "formula": "H2I2Pd", "connectivity": [], "stereochemistry": []}, "decision": "accepted", "explicit_human_review": True, "reviewer": "offline fixture reviewer", "rationale": "Exact endpoint structure reviewed.", "reviewed_at": "2026-07-19T12:00:00Z"}; draft_path = root / f"{stem}-review.draft.json"; write_json(draft_path, draft)
                output = root / f"{stem}-review.json"; TS_MODULE.build_endpoint_structure_review_artifact({"family": family, "audit": audit_path, "irc_input": irc_input, "irc_log": log, "irc_result": result_path, "job": endpoint_job_path, "checkpoint": checkpoint, "terminal_inspection_receipt": endpoint_receipt_path, "fetch_snapshot": endpoint_snapshot_path, "ts_checkpoint": ts_checkpoint, "checkpoint_audit": checkpoint_audit, "irc_plan": irc_plan, "allcheck_input_manifest": allcheck_manifest}, draft_path, output); return output

            forward_review = endpoint("forward", "reactant", from_state, 21); reverse_review = endpoint("reverse", "product", to_state, 22)
            acceptance = root / "formal-path-v2.json"; path_value = TS_MODULE.build_path_acceptance_v2_artifact(family, ts_result_path, mode_review, mode_decision, forward_review, reverse_review, mechanism_path, acceptance)
            asymmetric_candidate = load_json(ROOT / "tests/fixtures/asymmetric_catalysis/boron_candidate_r.json")
            asymmetric_candidate["study_id"] = mechanism["study_id"]
            asymmetric_candidate_path = root / "asymmetric-candidate.json"; write_json(asymmetric_candidate_path, asymmetric_candidate)
            asymmetric_energy = {
                "schema": "gaussian-asymmetric-energy-record/1", "result_id": "res_real_path_v2",
                "candidate_id": asymmetric_candidate["candidate_id"], "energy_unit": "kcal_mol",
                "electronic_energy": -100.0, "thermal_gibbs_correction": 10.0,
                "comparison_free_energy": 10.0, "comparison_energy_definition": "offline real owner-chain fixture",
                "temperature_k": 298.15, "standard_state": "1M",
                "low_frequency_policy": "raw harmonic fixture values; no correction",
                "inventory_key": asymmetric_candidate["atom_inventory"]["inventory_key"], "degeneracy": 1,
            }
            asymmetric_energy_path = root / "asymmetric-energy.json"; write_json(asymmetric_energy_path, asymmetric_energy)
            asymmetric_output = root / "asymmetric-path-result.json"
            asymmetric_result = ASYM_MODULE.ingest_result(
                asymmetric_candidate_path, ts_result_path, asymmetric_energy_path, asymmetric_output,
                mode_review, mode_decision, path_acceptance_path=acceptance,
            )
            self.assertEqual(asymmetric_result["validation_level"], "path_validated")
            self.assertTrue(asymmetric_result["comparison_eligibility"]["eligible"])
            payload = self.review(root, plan, path_accepted=True); payload["path_validation"][0]["irc_path_evidence"] = {"path": acceptance.name, "sha256": TS_MODULE.sha256(acceptance), "size_bytes": acceptance.stat().st_size, "schema": path_value["schema"], "payload_sha256": path_value["payload_sha256"]}
            draft = root / "path-v2-maturity.draft.json"; review_path = root / "path-v2-maturity.json"; gate_path = root / "path-v2-gate.json"; write_json(draft, payload)
            self.assertEqual(self.run_cli(TOOL, "finalize-review", str(draft), "--output", str(review_path)).returncode, 0)
            built = self.run_cli(TOOL, "build", str(plan), "--review", str(review_path), "--output", str(gate_path)); self.assertEqual(built.returncode, 0, built.stderr)
            edge_gate = next(item for item in load_json(gate_path)["edge_gates"] if item["edge_id"] == "edge_activation")
            self.assertTrue(edge_gate["owner_irc_path_evidence_valid"])
            self.assertFalse(MATURITY_MODULE._path_acceptance_matches_current_mechanism(
                {"schema": "gaussian-ts-irc-path-acceptance/1", "edge_id": "edge_activation"},
                plan_document["mechanism_network"], mechanism, plan_document["study_id"], "edge_activation",
            ))

            def resolve_bound(owner: Path, reference: dict[str, object]) -> Path:
                candidate = Path(str(reference["path"]))
                return candidate if candidate.is_absolute() else owner.parent / candidate

            other_root = root / "other-valid-study"; other_root.mkdir()
            intake_path = resolve_bound(mechanism_path, mechanism["intake"])
            registry_path = resolve_bound(mechanism_path, mechanism["species_registry"])
            condition_path = resolve_bound(mechanism_path, mechanism["condition_model"])
            intake = load_json(intake_path); registry = load_json(registry_path); condition = load_json(condition_path)
            request_path = resolve_bound(intake_path, intake["source_package"]["request"])
            scheme_path = resolve_bound(intake_path, intake["source_package"]["normalized_scheme"])
            other_request = load_json(request_path); other_request["study_id"] = "other_valid_study"
            other_request["source_files"][0]["path"] = str(request_path.parent / other_request["source_files"][0]["path"])
            other_scheme = load_json(scheme_path); other_scheme["scheme_id"] = "other_valid_study"
            other_request_path = other_root / "request.json"; other_scheme_path = other_root / "scheme.json"
            write_json(other_request_path, other_request); write_json(other_scheme_path, other_scheme)
            other_intake_path = other_root / "intake.json"
            built_other_intake = self.run_cli(MECHANISM_FIXTURE.W1_TOOL, "build-intake", str(other_request_path), "--scheme", str(other_scheme_path), "--output", str(other_intake_path)); self.assertEqual(built_other_intake.returncode, 0, built_other_intake.stderr)
            other_intake = load_json(other_intake_path)

            registry_review = load_json(resolve_bound(registry_path, registry["review_source"])); registry_review["study_id"] = "other_valid_study"; registry_review["intake_payload_sha256"] = other_intake["payload_sha256"]
            registry_review_path = other_root / "registry-review.json"; write_json(registry_review_path, registry_review)
            other_registry_path = other_root / "registry.json"
            built_other_registry = self.run_cli(MECHANISM_FIXTURE.W1_TOOL, "build-registry", str(other_intake_path), "--review", str(registry_review_path), "--output", str(other_registry_path)); self.assertEqual(built_other_registry.returncode, 0, built_other_registry.stderr)
            other_registry = load_json(other_registry_path)

            condition_review = load_json(resolve_bound(condition_path, condition["review_source"])); condition_review["study_id"] = "other_valid_study"; condition_review["intake_payload_sha256"] = other_intake["payload_sha256"]; condition_review["registry_payload_sha256"] = other_registry["payload_sha256"]
            condition_review_path = other_root / "condition-review.json"; write_json(condition_review_path, condition_review)
            other_condition_path = other_root / "condition.json"
            built_other_condition = self.run_cli(MECHANISM_FIXTURE.W1_TOOL, "build-condition-model", str(other_intake_path), str(other_registry_path), "--review", str(condition_review_path), "--output", str(other_condition_path)); self.assertEqual(built_other_condition.returncode, 0, built_other_condition.stderr)
            other_condition = load_json(other_condition_path)

            mechanism_review = load_json(resolve_bound(mechanism_path, mechanism["review_source"])); mechanism_review["study_id"] = "other_valid_study"; mechanism_review["intake_payload_sha256"] = other_intake["payload_sha256"]; mechanism_review["registry_payload_sha256"] = other_registry["payload_sha256"]; mechanism_review["condition_model_payload_sha256"] = other_condition["payload_sha256"]
            mechanism_review_path = other_root / "mechanism-review.json"; write_json(mechanism_review_path, mechanism_review)
            other_mechanism_path = other_root / "mechanism.json"
            built_other_mechanism = self.run_cli(MECHANISM_FIXTURE.W3_TOOL, "build", str(other_intake_path), str(other_registry_path), str(other_condition_path), "--review", str(mechanism_review_path), "--output", str(other_mechanism_path)); self.assertEqual(built_other_mechanism.returncode, 0, built_other_mechanism.stderr)
            cross_study = copy.deepcopy(path_value)
            cross_study["mechanism_network"] = TS_MODULE._closure_json_ref(other_mechanism_path, root, "other valid mechanism")
            cross_study["mechanism_binding"]["study_id"] = "other_valid_study"
            cross_study["payload_sha256"] = TS_MODULE._payload_sha256(cross_study)
            cross_path = root / "cross-study-path-v2.json"; write_json(cross_path, cross_study)
            TS_MODULE.validate_path_acceptance_v2_artifact(cross_path)
            cross_payload = self.review(root, plan, path_accepted=True)
            cross_payload["path_validation"][0]["irc_path_evidence"] = {
                "path": cross_path.name, "sha256": TS_MODULE.sha256(cross_path),
                "size_bytes": cross_path.stat().st_size, "schema": cross_study["schema"],
                "payload_sha256": cross_study["payload_sha256"],
            }
            cross_draft = root / "cross-study-maturity.draft.json"; cross_review = root / "cross-study-maturity.json"; cross_gate = root / "cross-study-gate.json"
            write_json(cross_draft, cross_payload)
            self.assertEqual(self.run_cli(TOOL, "finalize-review", str(cross_draft), "--output", str(cross_review)).returncode, 0)
            cross_built = self.run_cli(TOOL, "build", str(plan), "--review", str(cross_review), "--output", str(cross_gate)); self.assertEqual(cross_built.returncode, 0, cross_built.stderr)
            cross_edge_gate = next(item for item in load_json(cross_gate)["edge_gates"] if item["edge_id"] == "edge_activation")
            self.assertFalse(cross_edge_gate["owner_irc_path_evidence_valid"])

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
