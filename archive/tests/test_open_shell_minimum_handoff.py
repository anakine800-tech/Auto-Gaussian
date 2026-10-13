#!/usr/bin/env python3
"""Focused offline tests for the open-shell minimum Opt/Freq V1 closure."""

from __future__ import annotations

import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "main_group_open_shell"


def module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


MINIMUM = module("open_shell_minimum_test", ROOT / "skills" / "auto-g16-main-group-open-shell" / "scripts" / "open_shell_minimum.py")
PROTOCOL_TESTS = module("protocol_test_fixtures", ROOT / "tests" / "test_protocol_selection.py")
INPUT_AUDITOR = module("cartesian_input_auditor", ROOT / "skills" / "auto-g16-chemdraw-pipeline" / "scripts" / "audit_cartesian_input.py")
SCHEMA_VALIDATOR = module("open_shell_schema_validator", ROOT / "scripts" / "validate_asymmetric_contract.py")


def canonical(path: Path, value: dict) -> Path:
    path.write_bytes(MINIMUM.canonical_bytes(value))
    return path


class OpenShellMinimumHandoffTests(unittest.TestCase):
    def build_chain(self, root: Path, prefix: str = "ch3") -> dict:
        root = root.resolve()
        candidate_path = FIXTURES / f"{prefix}_candidate.json"
        structure_path = FIXTURES / f"{prefix}_cartesian_candidate.json"
        review_source_path = FIXTURES / f"{prefix}_review_source.json"
        result_path = FIXTURES / f"{prefix}_success.synthetic.txt"
        candidate = json.loads(candidate_path.read_text())
        structure = json.loads(structure_path.read_text())
        review = MINIMUM.state.build_review(candidate_path, review_source_path)
        review_path = root / "review.json"
        MINIMUM.state.write_new_json(review_path, review)

        request = PROTOCOL_TESTS.open_shell_request_fixture(review_path, review)
        request["request_id"] = f"{prefix}_minimum_opt_freq"
        request["structure"].update({
            "sha256": candidate["structure_sha256"],
            "formula": "CH3" if prefix == "ch3" else "CH2",
            "atom_count": len(candidate["atoms"]),
            "charge": candidate["charge"],
            "multiplicity": candidate["multiplicity"],
        })
        request_path = root / "request.json"
        PROTOCOL_TESTS.dump(request_path, request)
        profiles = PROTOCOL_TESTS.open_shell_profiles_fixture(review)
        profiles["proposal_id"] = f"{prefix}_minimum_protocols"
        for option in profiles["options"]:
            option["option_id"] = f"{prefix}_{option['tier']}_minimum"
            option["method_profiles"][0]["basis_stack"][0]["elements"] = ["C", "H"]
        profiles_path = root / "profiles.json"
        PROTOCOL_TESTS.dump(profiles_path, profiles)
        options = MINIMUM.protocol.build_options(request_path, profiles_path)
        options_path = root / "options.json"
        MINIMUM.protocol.write_new_json(options_path, options)
        approval_path = root / "approval.json"
        PROTOCOL_TESTS.dump(approval_path, {"decision": "selected", "tier": "standard", "explicit_confirmation": True, "decision_reason": "Synthetic explicit selection for an offline contract test."})
        selection = MINIMUM.protocol.build_selection(options_path, "standard", approval_path)
        selection_path = root / "selection.json"
        MINIMUM.protocol.write_new_json(selection_path, selection)
        selected = MINIMUM.protocol.get_selected_option(options, selection)
        wf = review["wavefunction_policy"]
        spec_doc = {
            "schema": MINIMUM.SCHEMA_SPEC,
            "specification_id": f"{prefix}_input_specification",
            "workflow": MINIMUM.WORKFLOW,
            "route": "#p ub3lyp/6-31g(d) opt freq stable=opt",
            "title": f"Synthetic {prefix} open-shell minimum",
            "checkpoint": f"{prefix}.chk",
            "charge": candidate["charge"],
            "multiplicity": candidate["multiplicity"],
            "reference_family": wf["reference"],
            "stability_required": True,
            "expected_frequency_count": review["state_assessment"]["expected_frequency_count"],
            "resources": {key: selected["resources"][key] for key in ("resource_tier", "mem_gb", "cores")},
            "server_directory": None,
            "server_directory_status": "not_created_not_authorized",
            "selection_payload_sha256": selection["selection_payload_sha256"],
            "selected_option_payload_sha256": selected["option_payload_sha256"],
            "explicit_review": {"route": True, "resources": True, "state": True, "reference": True, "stability": True, "frequency_count": True, "confirmed": True},
            "calculation_ready": False,
            "no_submission_authorization": True,
        }
        spec_doc["payload_sha256"] = MINIMUM.payload_sha256(spec_doc)
        spec_path = canonical(root / "spec.json", spec_doc)
        handoff = MINIMUM.build_handoff(review_path, structure_path, selection_path, spec_path, f"{prefix}_handoff")
        handoff_path = root / "handoff.json"
        MINIMUM.state.write_new_json(handoff_path, handoff)
        audit = MINIMUM.build_input_audit(handoff_path, f"{prefix}_input_audit")
        audit_path = root / "audit.json"
        MINIMUM.state.write_new_json(audit_path, audit)
        result_binding = {
            "schema": MINIMUM.SCHEMA_RESULT_BINDING,
            "result_id": f"{prefix}_result",
            "handoff": MINIMUM.binding(handoff_path, handoff),
            "input_sha256": handoff["input_sha256"],
            "result_source": {"path": str(result_path), "sha256": MINIMUM.file_sha256(result_path)},
            "transport_claim": "supplied_offline_source_binding_only",
            "calculation_ready": False,
            "no_submission_authorization": True,
        }
        result_binding["payload_sha256"] = MINIMUM.payload_sha256(result_binding)
        binding_path = canonical(root / "result-binding.json", result_binding)
        observation = MINIMUM.build_result_observation(binding_path, f"{prefix}_result_observation")
        observation_path = root / "result-observation.json"
        MINIMUM.state.write_new_json(observation_path, observation)
        continuity = MINIMUM.build_continuity(audit_path, observation_path, f"{prefix}_continuity")
        continuity_path = root / "continuity.json"
        MINIMUM.state.write_new_json(continuity_path, continuity)
        return locals()

    def test_ch3_doublet_and_triplet_ch2_positive_hash_bound_closures(self) -> None:
        for prefix in ("ch3", "triplet_ch2"):
            with self.subTest(prefix=prefix), tempfile.TemporaryDirectory(dir=ROOT) as tmp:
                chain = self.build_chain(Path(tmp), prefix)
                self.assertEqual(chain["handoff"]["workflow"], "main_group_open_shell_minimum_opt_freq_v1")
                self.assertEqual(chain["audit"]["status"], "passed")
                self.assertEqual(chain["continuity"]["status"], "accepted")
                self.assertFalse(chain["continuity"]["calculation_ready"])
                self.assertTrue(chain["continuity"]["no_submission_authorization"])
                self.assertTrue(all(value is False for value in chain["continuity"]["authorizations"].values()))
                for name in ("handoff_path", "audit_path", "observation_path", "continuity_path"):
                    self.assertEqual(MINIMUM.validate_artifact(chain[name])["schema"], json.loads(chain[name].read_text())["schema"])

    def test_v1_schema_documents_and_positive_instances_validate_offline(self) -> None:
        schema_names = {
            MINIMUM.SCHEMA_STRUCTURE: "cartesian-candidate.schema.json",
            MINIMUM.SCHEMA_SPEC: "input-specification.schema.json",
            MINIMUM.SCHEMA_HANDOFF: "minimum-opt-freq-input-handoff.schema.json",
            MINIMUM.SCHEMA_AUDIT: "minimum-opt-freq-input-audit.schema.json",
            MINIMUM.SCHEMA_RESULT_BINDING: "result-source-binding.schema.json",
            MINIMUM.SCHEMA_RESULT_OBSERVATION: "minimum-opt-freq-result-observation.schema.json",
            MINIMUM.SCHEMA_CONTINUITY: "minimum-opt-freq-result-continuity.schema.json",
        }
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            chain = self.build_chain(Path(tmp))
            instances = [chain[key] for key in ("structure", "spec_doc", "handoff", "audit", "result_binding", "observation", "continuity")]
            for instance in instances:
                schema = json.loads((ROOT / "contracts" / "main-group-open-shell" / schema_names[instance["schema"]]).read_text())
                SCHEMA_VALIDATOR.validate_schema_document(schema)
                SCHEMA_VALIDATOR._validate_schema_instance(instance, schema, schema)

    def test_handoff_audits_converter_cartesian_output_and_has_no_server_or_live_authority(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            chain = self.build_chain(Path(tmp))
            handoff = chain["handoff"]
            gjf = Path(tmp) / "offline-audit.gjf"
            gjf.write_text(handoff["input_text"], encoding="utf-8")
            coordinates, state_line, _ = INPUT_AUDITOR.parse(gjf)
            self.assertEqual(len(coordinates), 4)
            self.assertEqual(state_line, {"charge": 0, "multiplicity": 2})
            self.assertIsNone(handoff["server_directory"])
            self.assertFalse(handoff["authorizations"]["submit"])
            self.assertEqual(handoff["structure_candidate"]["payload_sha256"], chain["structure"]["payload_sha256"])

    def test_route_audit_normalizes_opt_options_and_rejects_specialist_bypasses(self) -> None:
        allowed = (
            "#p ub3lyp/6-31g(d) opt freq stable=opt",
            "#P UB3LYP/6-31G(d) Opt=(CalcFC,Tight) Freq Stable=Opt",
            "#p ub3lyp/6-31g(d) oPt = ( CalcFC , Tight ) fReQ sTaBlE = oPt",
            "#p ub3lyp/6-31g(d) Opt(CalcFC,Tight) Frequency Stable(Opt)",
        )
        for route in allowed:
            with self.subTest(route=route):
                audit = MINIMUM._route_audit(route, "U")
                self.assertTrue(all(audit[key] for key in ("opt", "freq", "stable", "reference")))
                self.assertEqual(audit["forbidden_tokens"], [])

        forbidden = (
            "#p ub3lyp/6-31g(d) Opt=(TS,CalcFC) Freq Stable=Opt",
            "#P UB3LYP/6-31G(d) oPt = ( tS , CalcFC ) FREQ STABLE = OPT",
            "#p ub3lyp/6-31g(d) Opt(TS,CalcFC) Freq Stable=Opt",
            "#p ub3lyp/6-31g(d) Opt=QST2 Freq Stable=Opt",
            "#p ub3lyp/6-31g(d) Opt=(QST3,CalcFC) Freq Stable=Opt",
            "#p ub3lyp/6-31g(d) Opt=(Saddle=1,CalcFC) Freq Stable=Opt",
            "#p ub3lyp/6-31g(d) FOpt=(QST2,CalcFC) Freq Stable=Opt",
            "#p ub3lyp/6-31g(d) Opt Freq IRC=(Forward,CalcFC) Stable=Opt",
            "#p ub3lyp/6-31g(d) Opt Freq IRCMax(CalcFC) Stable=Opt",
            "#p ub3lyp/6-31g(d) Opt Freq TD=(NStates=3) Stable=Opt",
            "#p ub3lyp/6-31g(d) Opt Freq Guess = ( Mix , Always ) Stable=Opt",
            "#p ub3lyp/6-31g(d) Opt=(ModRedundant) Freq Stable=Opt",
            "#p ub3lyp/6-31g(d) Opt=(Conical) Freq Stable=Opt",
            "#p ub3lyp/6-31g(d) Opt=(TS,CalcFC Freq Stable=Opt",
        )
        for route in forbidden:
            with self.subTest(route=route):
                self.assertTrue(MINIMUM._route_audit(route, "U")["forbidden_tokens"])

    def test_state_hash_reference_route_resource_and_structure_drift_fail_closed(self) -> None:
        mutators = {
            "selection hash": lambda spec: spec.__setitem__("selection_payload_sha256", "f" * 64),
            "reference-family drift": lambda spec: spec.__setitem__("reference_family", "RO"),
            "route outside": lambda spec: spec.__setitem__("route", "#p ub3lyp/6-31g(d) Opt=(TS,CalcFC) Freq Stable=Opt"),
            "resource drift": lambda spec: spec["resources"].__setitem__("cores", spec["resources"]["cores"] + 1),
        }
        for label, mutate in mutators.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory(dir=ROOT) as tmp:
                chain = self.build_chain(Path(tmp))
                spec = copy.deepcopy(chain["spec_doc"])
                mutate(spec)
                spec["payload_sha256"] = MINIMUM.payload_sha256(spec)
                drift_path = canonical(Path(tmp) / "drift-spec.json", spec)
                with self.assertRaises(MINIMUM.ContractError):
                    MINIMUM.build_handoff(chain["review_path"], chain["structure_path"], chain["selection_path"], drift_path, "drift_handoff")

        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            chain = self.build_chain(Path(tmp))
            structure = copy.deepcopy(chain["structure"])
            structure["atoms"][1]["x_angstrom"] += 0.01
            structure["payload_sha256"] = MINIMUM.payload_sha256(structure)
            structure_path = canonical(Path(tmp) / "structure-drift.json", structure)
            with self.assertRaisesRegex(MINIMUM.ContractError, "coordinate hash mismatch"):
                MINIMUM.build_handoff(chain["review_path"], structure_path, chain["selection_path"], chain["spec_path"], "structure_drift")

    def _continuity_for_mutated_result(self, root: Path, replace: tuple[str, str]):
        chain = self.build_chain(root)
        source = FIXTURES / "ch3_success.synthetic.txt"
        result = root / "mutated.synthetic.txt"
        result.write_text(source.read_text().replace(*replace), encoding="utf-8")
        result_binding = copy.deepcopy(chain["result_binding"])
        result_binding["result_id"] = "mutated_result"
        result_binding["result_source"] = {"path": str(result), "sha256": MINIMUM.file_sha256(result)}
        result_binding["payload_sha256"] = MINIMUM.payload_sha256(result_binding)
        binding_path = canonical(root / "mutated-binding.json", result_binding)
        observation = MINIMUM.build_result_observation(binding_path, "mutated_observation")
        observation_path = root / "mutated-observation.json"
        MINIMUM.state.write_new_json(observation_path, observation)
        return MINIMUM.build_continuity(chain["audit_path"], observation_path, "mutated_continuity")

    def test_result_reference_stability_s2_frequency_state_and_termination_fail_closed(self) -> None:
        cases = {
            "reference": ("E(UB3LYP)", "E(ROB3LYP)"),
            "stability": ("wavefunction is stable under the perturbations considered", "wavefunction has an internal instability"),
            "s2": ("after 0.7505", "after 1.2505"),
            "frequency": ("Frequencies -- 1200.0 1500.0 3000.0", "Frequencies -- -20.0 1500.0 3000.0"),
            "state": ("Multiplicity = 2", "Multiplicity = 4"),
            "termination": ("Normal termination of Gaussian", "Error termination"),
        }
        for expected, replacement in cases.items():
            with self.subTest(expected=expected), tempfile.TemporaryDirectory(dir=ROOT) as tmp:
                continuity = self._continuity_for_mutated_result(Path(tmp).resolve(), replacement)
                self.assertEqual(continuity["status"], "blocked")
                key = {"frequency": "minimum_frequencies", "termination": "normal_termination", "s2": "s2_within_policy"}.get(expected, expected)
                self.assertFalse(continuity["checks"][key])

    def test_result_and_handoff_hash_lineage_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            chain = self.build_chain(Path(tmp))
            bad = copy.deepcopy(chain["result_binding"])
            bad["input_sha256"] = "0" * 64
            bad["payload_sha256"] = MINIMUM.payload_sha256(bad)
            bad_path = canonical(Path(tmp) / "bad-input-binding.json", bad)
            with self.assertRaisesRegex(MINIMUM.ContractError, "input hash lineage"):
                MINIMUM.build_result_observation(bad_path, "bad_input_lineage")

            bad = copy.deepcopy(chain["result_binding"])
            bad["result_source"]["sha256"] = "0" * 64
            bad["payload_sha256"] = MINIMUM.payload_sha256(bad)
            bad_path = canonical(Path(tmp) / "bad-result-binding.json", bad)
            with self.assertRaisesRegex(MINIMUM.ContractError, "result source hash"):
                MINIMUM.build_result_observation(bad_path, "bad_result_lineage")

    def test_closed_shell_metal_open_shell_singlet_and_multireference_cannot_enter_handoff(self) -> None:
        candidate_base = json.loads((FIXTURES / "ch3_candidate.json").read_text())
        source_base = json.loads((FIXTURES / "ch3_review_source.json").read_text())
        cases = []
        closed = copy.deepcopy(candidate_base); closed.update({"candidate_id": "closed_shell_case", "multiplicity": 1, "state_family": "closed_shell_singlet"})
        cases.append(("closed", closed, source_base))
        singlet = copy.deepcopy(candidate_base); singlet.update({"candidate_id": "open_singlet_case", "multiplicity": 1, "state_family": "open_shell_singlet", "electronic_scope": "broken_symmetry"})
        cases.append(("singlet", singlet, source_base))
        metal = copy.deepcopy(candidate_base); metal["candidate_id"] = "metal_case"; metal["atoms"][0]["element"] = "Fe"
        cases.append(("metal", metal, source_base))
        mr_source = copy.deepcopy(source_base); mr_source["multireference_risk"] = {"level": "unresolved", "evidence": ["Synthetic unresolved risk."], "action": "escalate"}
        mr = copy.deepcopy(candidate_base); mr["candidate_id"] = "multireference_case"
        cases.append(("multireference", mr, mr_source))
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            root = Path(tmp)
            for name, candidate, source in cases:
                source = copy.deepcopy(source); source["review_id"] = f"{name}_review"; source["reviewer_decision"] = {"decision": "blocked", "rationale": "Synthetic negative boundary fixture.", "confirmed": True}
                if candidate["multiplicity"] == 1:
                    source["credible_multiplicities"] = [1]; source["spin_contamination_policy"]["target_s2"] = 0.0
                candidate_path = root / f"{name}-candidate.json"; source_path = root / f"{name}-source.json"
                PROTOCOL_TESTS.dump(candidate_path, candidate); PROTOCOL_TESTS.dump(source_path, source)
                review = MINIMUM.state.build_review(candidate_path, source_path)
                self.assertEqual(review["status"], "blocked")


if __name__ == "__main__":
    unittest.main()
