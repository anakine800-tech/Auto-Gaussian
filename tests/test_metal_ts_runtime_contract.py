#!/usr/bin/env python3
from __future__ import annotations
import copy, importlib.util, unittest
from pathlib import Path

ROOT=Path(__file__).parents[1]
P=ROOT/"skills/auto-g16-metal-ts/scripts/metal_ts.py"
spec=importlib.util.spec_from_file_location("metal_ts",P); assert spec and spec.loader
M=importlib.util.module_from_spec(spec); spec.loader.exec_module(M)

def seal(obj, field): obj[field]=M.payload_hash(obj,field); return obj

def input_request():
    candidate=seal({"identity":{"charge":0,"multiplicity":1,"atom_order":["Pd","P","C","H"],"state_id":"pd0_singlet"}},"candidate_payload_sha256")
    m1=seal({"candidate_sha256":candidate["candidate_payload_sha256"],"completion":{"metal_m1_scientific_review_status":"reviewed_bounded_example_runtime_unsupported"}},"review_payload_sha256")
    opts=seal({"options":["loose","standard","strict"]},"options_payload_sha256")
    sel=seal({"options_payload_sha256":opts["options_payload_sha256"],"candidate_sha256":candidate["candidate_payload_sha256"],"tier":"standard"},"selection_payload_sha256")
    obs=seal({"candidate_sha256":candidate["candidate_payload_sha256"],"observed":{"charge":0,"multiplicity":1,"atom_order":["Pd","P","C","H"],"input_sha256":"1"*64}},"audit_payload_sha256")
    return {"candidate":candidate,"m1_review":m1,"protocol_options":opts,"protocol_selection":sel,"input_observation":obs,"identity_review":copy.deepcopy(candidate["identity"]),"wavefunction_review":{"wavefunction":"restricted_closed_shell","state_id":"pd0_singlet"},"basis_ecp_review":{"basis_by_element":{"Pd":"b-pd","P":"b-p","C":"b-c","H":"b-h"},"ecp_elements":["Pd"],"ecp_by_element":{"Pd":{"name":"ecp","core_electrons":28,"evidence_id":"ev-ecp"}}},"seed_strategy":{"type":"hessian_guided_single_guess","state_id":"pd0_singlet","hessian_state_id":"pd0_singlet","checkpoint_state_id":"pd0_singlet","evidence_ids":["ev-seed"],"intended_coordinate":[2,3]},"decision":"approved_for_offline_result_intake","confirmed":True}

def result_request():
    approval=M.approve_input(input_request())
    obs=seal({"candidate_sha256":approval["candidate_sha256"],"input_sha256":approval["input_sha256"],"facts":{"charge":0,"multiplicity":1,"atom_order":["Pd","P","C","H"],"state_id":"pd0_singlet","normal_termination":True,"stationary_point":True,"frequency_complete":True,"expected_frequency_count":6,"frequencies":[-211.0,10,20,30,40,50]}},"audit_payload_sha256")
    return {"input_approval":approval,"result_observation":obs,"wavefunction_acceptance":{"state_id":"pd0_singlet","wavefunction":"restricted_closed_shell","stability_tested":True,"stable":True,"s2_target":0.0,"s2_after":0.01,"s2_tolerance":0.05},"coordination_acceptance":{"expected_ligands":["L1"],"observed_ligands":["L1"],"ligand_inventory_retained":True,"contacts":[{"atoms":[1,2],"minimum":2.0,"maximum":2.5,"observed":2.2}]},"mode_evidence":{"result_observation_sha256":obs["audit_payload_sha256"],"imaginary_frequency_index":0,"intended_coordinate_confirmed":True,"unintended_coordination_or_ligand_loss":False,"reviewer":"chemist","evidence_sha256":"2"*64},"decision":"accepted_for_explicit_promotion_review","confirmed":True}

class MetalRuntimeTests(unittest.TestCase):
    def test_happy_path_is_offline_and_promotion_is_explicit(self):
        a=M.approve_input(input_request()); self.assertEqual(a["submission_decision"],"refused")
        x=M.accept_result(result_request()); self.assertEqual(x["promotion_decision"],"not_yet_made")
        p=M.decide_promotion({"result_acceptance":x,"decision":"promoted_for_offline_downstream_review","confirmed":True,"reviewer":"chemist","rationale":"bounded fixture"})
        self.assertFalse(any(p["authorizations"].values())); self.assertIn("no_path",p["claim_ceiling"])

    def assert_input_refused(self, mutate, pattern):
        r=input_request(); mutate(r)
        with self.assertRaisesRegex(M.ContractError,pattern): M.approve_input(r)

    def assert_result_refused(self, mutate, pattern):
        r=result_request(); mutate(r)
        with self.assertRaisesRegex(M.ContractError,pattern): M.accept_result(r)

    def test_m3_input_adversaries(self):
        cases=[
          (lambda r:r["identity_review"].update(charge=1),"wrong charge"),
          (lambda r:r["identity_review"].update(multiplicity=3),"wrong multiplicity"),
          (lambda r:r["identity_review"].update(atom_order=["Pd","C","P","H"]),"wrong atom_order"),
          (lambda r:r["identity_review"].update(state_id="triplet"),"wrong state_id"),
          (lambda r:r["seed_strategy"].update(hessian_state_id="triplet"),"cross-state"),
          (lambda r:r["basis_ecp_review"]["basis_by_element"].pop("H"),"basis coverage"),
          (lambda r:r["basis_ecp_review"]["ecp_by_element"]["Pd"].pop("core_electrons"),"ECP coverage"),
          (lambda r:r["seed_strategy"].update(type="qst2"),"unsupported seed"),
        ]
        for mutate,pattern in cases:
            with self.subTest(pattern=pattern): self.assert_input_refused(mutate,pattern)

    def test_m3_result_adversaries(self):
        cases=[
          (lambda r:r["result_observation"]["facts"].update(state_id="triplet"),"wrong state_id"),
          (lambda r:r["wavefunction_acceptance"].update(stability_tested=False),"stability"),
          (lambda r:r["wavefunction_acceptance"].update(s2_after=0.8),"spin contamination"),
          (lambda r:r["coordination_acceptance"].update(observed_ligands=[]),"ligand inventory"),
          (lambda r:r["coordination_acceptance"]["contacts"][0].update(observed=3.3),"coordination contact"),
          (lambda r:r["mode_evidence"].update(intended_coordinate_confirmed=False),"imaginary-mode"),
          (lambda r:r["result_observation"]["facts"].update(frequency_complete=False),"incomplete frequencies"),
        ]
        for mutate,pattern in cases:
            with self.subTest(pattern=pattern):
                def both(r, m=mutate):
                    m(r)
                    if "facts" in r["result_observation"]: r["result_observation"]["audit_payload_sha256"]=M.payload_hash(r["result_observation"],"audit_payload_sha256")
                    r["mode_evidence"]["result_observation_sha256"]=r["result_observation"]["audit_payload_sha256"]
                self.assert_result_refused(both,pattern)

    def test_rehash_forgery_cannot_launder_upstream_semantics(self):
        r=input_request(); r["candidate"]["identity"]["charge"]=1; r["candidate"]["candidate_payload_sha256"]=M.payload_hash(r["candidate"],"candidate_payload_sha256")
        with self.assertRaisesRegex(M.ContractError,"M1 candidate binding mismatch"): M.approve_input(r)

    def test_main_group_ts_refusal_is_unchanged(self):
        text=(ROOT/"skills/auto-g16-ts-irc/SKILL.md").read_text()
        self.assertIn("Refuse transition-metal",text)
        self.assertNotIn("auto-g16-metal-ts",(ROOT/"skills/auto-g16-ts-irc/scripts/ts_irc.py").read_text())

if __name__=="__main__": unittest.main()
