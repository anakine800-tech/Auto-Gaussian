#!/usr/bin/env python3
"""Focused offline tests for the main-group open-shell W3/DAG overlay."""

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

from tests import test_protocol_selection as PROTOCOL_FIXTURE


ROOT = Path(__file__).parents[1]
TOOL = ROOT / "skills" / "auto-g16-reaction-workflow" / "scripts" / "open_shell_reaction_network.py"
OWNER = ROOT / "skills" / "auto-g16-main-group-open-shell" / "scripts" / "open_shell_state.py"
FIXTURES = ROOT / "tests" / "fixtures" / "reaction_workflow"
SCHEMA_VALIDATOR_PATH = ROOT / "scripts" / "validate_asymmetric_contract.py"
SPEC = importlib.util.spec_from_file_location("open_shell_network_schema_validator", SCHEMA_VALIDATOR_PATH)
assert SPEC and SPEC.loader
VALIDATOR = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(VALIDATOR)


def canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n").encode()


def write_canonical(path: Path, value: object) -> None:
    path.write_bytes(canonical_bytes(value))


def binding(path: Path, schema: str, payload: str) -> dict[str, object]:
    return {"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "size_bytes": path.stat().st_size, "schema": schema, "payload_sha256": payload}


class OpenShellReactionNetworkTests(unittest.TestCase):
    def run_tool(self, tool: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, str(tool), *args], cwd=ROOT, text=True, capture_output=True, check=False)

    def prepare(self, root: Path, *, source_charge: int = 0, source_multiplicity: int = 2, target_charge: int = 0, target_multiplicity: int = 2, target_element: str = "C") -> tuple[Path, dict[str, object]]:
        structure_a = root / "radical_a.xyz"; structure_b = root / "radical_b.xyz"
        structure_text = "4\nsynthetic reviewed structure\nC 0 0 0\nH 0 0 1\nH 1 0 0\nH 0 1 0\n"
        structure_a.write_text(structure_text); structure_b.write_text(structure_text)
        structure_hash = hashlib.sha256(structure_a.read_bytes()).hexdigest()
        candidates, reviews = [], []
        for suffix, charge, multiplicity in (("a", source_charge, source_multiplicity), ("b", target_charge, target_multiplicity)):
            element = target_element if suffix == "b" else "C"
            atoms = [{"index": 1, "element": element}, {"index": 2, "element": "H"}, {"index": 3, "element": "H"}, {"index": 4, "element": "H"}]
            state_family = "high_spin_triplet_ground_state" if multiplicity == 3 else "doublet_ground_state"
            candidate = {"schema": "auto-g16-main-group-open-shell-candidate/1", "candidate_id": f"radical_{suffix}", "structure_sha256": structure_hash, "atoms": atoms, "charge": charge, "multiplicity": multiplicity, "state_family": state_family, "electronic_scope": "single_reference_ground_state", "structure_role": "minimum", "task_types": ["optimization", "frequency"], "calculation_ready": False, "no_submission_authorization": True}
            candidate_path = root / f"candidate_{suffix}.json"; write_canonical(candidate_path, candidate)
            source = {"schema": "auto-g16-main-group-open-shell-review-source/1", "review_id": f"radical_{suffix}_review", "credible_multiplicities": [multiplicity], "wavefunction_reference": "U", "stability_required": True, "expected_frequency_count": 6, "spin_contamination_policy": {"metric": "post_annihilation_absolute_s2_deviation", "target_s2": 0.75 if multiplicity == 2 else 2.0, "max_abs_deviation": 0.1, "missing_diagnostic": "block"}, "alternative_solutions": [{"multiplicity": 1, "state_family": "closed_shell_singlet", "disposition": "excluded_by_evidence", "evidence": "Human-reviewed synthetic fixture."}], "multireference_risk": {"level": "low", "evidence": ["Human-reviewed synthetic fixture."], "action": "accept_single_reference"}, "reviewer_decision": {"decision": "accepted_for_v1_protocol_gate", "rationale": "Human-reviewed synthetic fixture.", "confirmed": True}, "calculation_ready": False, "no_submission_authorization": True}
            source_path = root / f"review_source_{suffix}.json"; write_canonical(source_path, source)
            review_path = root / f"state_review_{suffix}.json"
            built = self.run_tool(OWNER, "review", str(candidate_path), "--review-source", str(source_path), "--output", str(review_path))
            if element == "C":
                self.assertEqual(built.returncode, 0, built.stderr)
            candidates.append((candidate_path, candidate)); reviews.append((review_path, json.loads(review_path.read_text()) if review_path.exists() else None))

        if target_element != "C":
            # Forge a hash-consistent accepted review to prove the network owner independently rejects metals.
            candidate_path, candidate = candidates[1]
            base = copy.deepcopy(reviews[0][1]); base["review_id"] = "radical_b_review"; base["candidate_snapshot"] = candidate
            base["candidate_source"] = {"path": str(candidate_path), "sha256": hashlib.sha256(candidate_path.read_bytes()).hexdigest()}
            metal_review_source = root / "review_source_b.json"
            base["review_source"] = {"path": str(metal_review_source), "sha256": hashlib.sha256(metal_review_source.read_bytes()).hexdigest()}
            base["atom_inventory"]["atoms"] = candidate["atoms"]; base["atom_inventory"]["elements"] = ["H", target_element]; base["atom_inventory"]["atomic_number_sum"] = 29
            base["electron_accounting"] = {"charge": 0, "electron_count": 29, "electron_parity": "odd", "multiplicity": 2, "multiplicity_parity_consistent": True}
            base["payload_sha256"] = hashlib.sha256(canonical_bytes({k: v for k, v in base.items() if k != "payload_sha256"})).hexdigest()
            review_path = root / "state_review_b.json"; write_canonical(review_path, base); reviews[1] = (review_path, base)

        atom_ids_a = ["a_c", "a_h1", "a_h2", "a_h3"]; atom_ids_b = ["b_c", "b_h1", "b_h2", "b_h3"]
        lineages = []
        states = []
        for suffix, structure, atom_ids, candidate_pair, review_pair in (("a", structure_a, atom_ids_a, candidates[0], reviews[0]), ("b", structure_b, atom_ids_b, candidates[1], reviews[1])):
            candidate_path, candidate = candidate_pair; review_path, state_review = review_pair
            candidate_payload = hashlib.sha256(canonical_bytes(candidate)).hexdigest()
            state_binding = binding(review_path, "auto-g16-main-group-open-shell-review/1", state_review["payload_sha256"])
            lineage_id = f"lineage_{suffix}"
            protocol_binding = None
            protocol_status = "unresolved"
            if target_element == "C" or suffix == "a":
                request = PROTOCOL_FIXTURE.open_shell_request_fixture(review_path, state_review)
                request["request_id"] = f"radical_{suffix}_protocol_request"
                request["structure"].update({"sha256": candidate["structure_sha256"], "charge": candidate["charge"], "multiplicity": candidate["multiplicity"]})
                request_path = root / f"protocol_request_{suffix}.json"; PROTOCOL_FIXTURE.dump(request_path, request)
                profiles = PROTOCOL_FIXTURE.open_shell_profiles_fixture(state_review)
                profiles["proposal_id"] = f"radical_{suffix}_protocol_options"
                for option in profiles["options"]:
                    option["option_id"] = f"radical_{suffix}_{option['tier']}"
                profiles_path = root / f"protocol_profiles_{suffix}.json"; PROTOCOL_FIXTURE.dump(profiles_path, profiles)
                options = PROTOCOL_FIXTURE.PROTOCOL.build_options(request_path, profiles_path)
                options_path = root / f"protocol_options_{suffix}.json"; PROTOCOL_FIXTURE.PROTOCOL.write_new_json(options_path, options)
                approval_path = root / f"protocol_approval_{suffix}.json"
                PROTOCOL_FIXTURE.dump(approval_path, {"decision": "selected", "tier": "standard", "explicit_confirmation": True, "decision_reason": "Synthetic explicit offline protocol selection."})
                selection = PROTOCOL_FIXTURE.PROTOCOL.build_selection(options_path, "standard", approval_path, f"radical_{suffix}_selection")
                selection_path = root / f"protocol_selection_{suffix}.json"; PROTOCOL_FIXTURE.PROTOCOL.write_new_json(selection_path, selection)
                protocol_binding = binding(selection_path, "gaussian-protocol-selection/1", selection["selection_payload_sha256"])
                protocol_status = "reviewed"
            lineages.append({"lineage_id": lineage_id, "protocol_selection": protocol_binding, "candidate_id": candidate["candidate_id"], "state_review_payload_sha256": state_review["payload_sha256"], "status": protocol_status, "reviewer": "fixture reviewer", "rationale": "Exact owner-validated protocol lineage, or explicit unresolved metal fixture lineage."})
            states.append({"state_id": f"state_{suffix}", "structure": {"path": structure.name, "sha256": hashlib.sha256(structure.read_bytes()).hexdigest()}, "candidate": binding(candidate_path, "auto-g16-main-group-open-shell-candidate/1", candidate_payload), "state_review": state_binding, "atom_ids": atom_ids, "fragment_spin_coupling": {"status": "reviewed", "total_multiplicity": candidate["multiplicity"], "fragments": [{"fragment_id": f"fragment_{suffix}", "atom_ids": atom_ids, "multiplicity": candidate["multiplicity"]}], "coupling_model": "Human reviewed single-fragment spin state; not derived from fragment multiplicities.", "reviewer": "fixture reviewer", "rationale": "Explicit total-spin review."}, "protocol_lineage_id": lineage_id})
        surface_family = "high_spin_triplet_ground_state" if source_multiplicity == 3 else "doublet_ground_state"
        review = json.loads((FIXTURES / "open_shell_network_review.template.json").read_text())
        review["surface_review"]["multiplicity"] = source_multiplicity
        review["surface_review"]["state_family"] = surface_family
        review["protocol_lineages"] = lineages; review["states"] = states
        review["edges"][0]["total_multiplicity_review"]["multiplicity"] = source_multiplicity
        review["nodes"][0]["state_review_bindings"] = [reviews[0][1]["payload_sha256"]]
        review["nodes"][1]["state_review_bindings"] = [reviews[0][1]["payload_sha256"], reviews[1][1]["payload_sha256"]]
        review_path = root / "network_review.json"; review_path.write_text(json.dumps(review, indent=2) + "\n")
        return review_path, review

    def test_positive_doublet_network_is_hash_bound_and_non_authorizing(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            root = Path(tmp); review_path, _ = self.prepare(root); output = root / "network.json"
            review_schema = json.loads((ROOT / "contracts" / "reaction-workflow" / "open-shell-network-review.schema.json").read_text())
            VALIDATOR._validate_schema_instance(json.loads(review_path.read_text()), review_schema, review_schema)
            built = self.run_tool(TOOL, "build", str(review_path), "--output", str(output)); self.assertEqual(built.returncode, 0, built.stderr)
            artifact = json.loads(output.read_text())
            output_schema = json.loads((ROOT / "contracts" / "reaction-workflow" / "open-shell-network.schema.json").read_text())
            VALIDATOR._validate_schema_instance(artifact, output_schema, output_schema)
            self.assertEqual(artifact["schema"], "gaussian-reaction-open-shell-network/1")
            self.assertTrue(all(item["elements_conserved"] and item["charge_conserved"] and item["electron_count_conserved"] for item in artifact["diagnostics"]["edges"]))
            self.assertTrue(all(not item["executable"] for item in artifact["nodes"]))
            self.assertEqual(artifact["handoff"], {"kind": "hash_bound_non_executable_calculation_dag", "ts_authorized": False, "irc_authorized": False, "execution_authorized": False, "energy_ranking_authorized": False})
            checked = self.run_tool(TOOL, "validate", str(output)); self.assertEqual(checked.returncode, 0, checked.stderr); self.assertFalse(json.loads(checked.stdout)["live_actions"])

    def test_positive_high_spin_triplet_surface_is_supported_without_crossing(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            root = Path(tmp)
            review_path, _ = self.prepare(root, source_charge=1, source_multiplicity=3, target_charge=1, target_multiplicity=3)
            output = root / "triplet-network.json"
            result = self.run_tool(TOOL, "build", str(review_path), "--output", str(output))
            self.assertEqual(result.returncode, 0, result.stderr)
            artifact = json.loads(output.read_text())
            self.assertEqual(artifact["surface_review"]["multiplicity"], 3)
            self.assertTrue(artifact["surface_review"]["crossing_excluded"])

    def test_negative_fixtures_fail_closed(self) -> None:
        cases = json.loads((FIXTURES / "open_shell_network_negative_cases.json").read_text())["cases"]
        for case in cases:
            with self.subTest(case=case["case_id"]), tempfile.TemporaryDirectory(dir=ROOT) as tmp:
                root = Path(tmp)
                kwargs = {"target_charge": 2} if case["mutation"] == "target_charge_drift" else {"target_charge": 1, "target_multiplicity": 3} if case["mutation"] == "multiplicity_drift" else {"target_element": "Fe"} if case["mutation"] == "metal_candidate" else {}
                review_path, review = self.prepare(root, **kwargs)
                mutation = case["mutation"]
                if mutation == "drop_atom_mapping": review["edges"][0]["atom_mapping"].pop()
                elif mutation == "state_review_hash_drift": review["states"][1]["state_review"]["payload_sha256"] = "f"*64
                elif mutation == "unresolved_coupling": review["states"][1]["fragment_spin_coupling"]["status"] = "unresolved"
                elif mutation == "unreviewed_edge_multiplicity": review["edges"][0]["total_multiplicity_review"]["status"] = "unresolved"
                elif mutation == "candidate_lineage_drift": review["edges"][0]["candidate_lineage"]["to_candidate_id"] = "radical_a"
                elif mutation == "protocol_lineage_drift": review["edges"][0]["protocol_lineage_ids"] = ["lineage_a"]
                elif mutation == "node_state_review_drift": review["nodes"][1]["state_review_bindings"] = [review["nodes"][0]["state_review_bindings"][0]]
                review_path.write_text(json.dumps(review, indent=2) + "\n")
                result = self.run_tool(TOOL, "build", str(review_path), "--output", str(root / "out.json"))
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertRegex(result.stderr.lower(), case["expected"])

    def test_contract_schemas_are_closed_and_static_valid(self) -> None:
        for name in ("open-shell-network-review.schema.json", "open-shell-network.schema.json"):
            schema = json.loads((ROOT / "contracts" / "reaction-workflow" / name).read_text())
            VALIDATOR.validate_schema_document(schema)
            self.assertFalse(schema["additionalProperties"])

    def test_old_closed_shell_contracts_remain_unchanged_in_scope(self) -> None:
        mechanism = json.loads((ROOT / "contracts" / "reaction-workflow" / "mechanism-network.schema.json").read_text())
        plan = json.loads((ROOT / "contracts" / "reaction-workflow" / "calculation-plan.schema.json").read_text())
        self.assertEqual(mechanism["properties"]["schema"]["const"], "gaussian-reaction-mechanism-network/1")
        self.assertEqual(plan["properties"]["schema"]["const"], "gaussian-reaction-calculation-plan/1")


if __name__ == "__main__":
    unittest.main()
