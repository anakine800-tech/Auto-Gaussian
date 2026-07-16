#!/usr/bin/env python3
from __future__ import annotations
import copy, importlib.util, json, tempfile, unittest
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
    def make_path_case(self, root):
        root=Path(root); candidate=json.loads((ROOT/"tests/fixtures/asymmetric_catalysis/metal_candidate.json").read_text())
        cp=root/"candidate.json"; cp.write_text(json.dumps(candidate))
        atoms=[{"index":x["index"],"atomic_number":{"Pd":46,"P":15,"C":6,"H":1}[x["element"]],"element":x["element"]} for x in candidate["atom_map"]]
        sections={k:{"status":"reviewed_for_bounded_example"} for k in ("electron_accounting","spin_surface","wavefunction","coordination","method_protocol","ts_and_path")}
        m1={"schema":"gaussian-asymmetric-metal-scientific-review/1","candidate_source":{"sha256":M.file_digest(cp)},"candidate_id":candidate["candidate_id"],"identity_binding":{"total_charge":0,"multiplicity":1},"review_scope":{"scope_kind":"primary_literature_bound_review"},"sections":sections,"completion":{"metal_m1_scientific_review_status":"reviewed_bounded_example_runtime_unsupported"}}
        M.seal_local(m1,"review_payload_sha256"); mp=root/"m1.json"; mp.write_text(json.dumps(m1))
        option={"option_id":"metal_standard","tier":"standard","option_status":"selectable","unresolved":[]}; M.seal_local(option,"option_payload_sha256")
        options={"schema":"gaussian-protocol-options/1","options":[option]}; M.seal_local(options,"proposal_payload_sha256"); op=root/"options.json"; op.write_text(json.dumps(options))
        selection={"schema":"gaussian-protocol-selection/1","options_source":{"sha256":M.file_digest(op)},"proposal_payload_sha256":options["proposal_payload_sha256"],"selected_option":{k:option[k] for k in ("option_id","option_payload_sha256","tier")},"scope_binding":{"structure_sha256":candidate["geometry"]["artifact"]["sha256"],"charge":0,"multiplicity":1,"task_types":["transition_state_optimization","harmonic_frequency"]}}
        M.seal_local(selection,"selection_payload_sha256"); sp=root/"selection.json"; sp.write_text(json.dumps(selection))
        obs={"schema":"gaussian-asymmetric-metal-input-observation/1","candidate_source":{"sha256":M.file_digest(cp)},"scientific_review_source":{"sha256":M.file_digest(mp)},"input_source":{"sha256":"a"*64},"identity_binding":{"charge":0,"multiplicity":1,"atom_order":atoms}}
        M.seal_local(obs,"audit_payload_sha256"); ip=root/"input-observation.json"; ip.write_text(json.dumps(obs))
        review=lambda: {"accepted":True,"evidence_sha256":"b"*64}
        source={"schema":"auto-g16-metal-ts-input-approval-source/1","source_bindings":{"candidate_sha256":M.file_digest(cp),"m1_review_sha256":M.file_digest(mp),"protocol_options_sha256":M.file_digest(op),"protocol_selection_sha256":M.file_digest(sp),"input_observation_sha256":M.file_digest(ip)},"scope":{"scope_kind":"reviewer_bound_real_case","reviewer":"chemist","review_date":"2026-07-16"},"identity":{"charge":0,"multiplicity":1,"atom_count":len(atoms),"atom_order":atoms,"state_id":candidate["catalyst_state_id"]},"wavefunction":{"wavefunction":"restricted_closed_shell","state_id":candidate["catalyst_state_id"]},"reviews":{"route":review(),"basis_ecp_relativistic":{"basis_by_element":{"Pd":"b","P":"b","C":"b","H":"b"},"ecp_elements":["Pd"],"ecp_by_element":{"Pd":{"name":"ecp","core_electrons":28,"evidence_id":"ecp_ev"}},"relativistic_treatment":"reviewed ECP scalar treatment"},"solvent":review(),"thermochemistry":review(),"resources":review(),"server_path":review()|{"remote_workdir":"/home/user100/SDL/metal_case"},"seed_strategy":{"type":"hessian_guided_single_guess","state_id":candidate["catalyst_state_id"],"hessian_state_id":candidate["catalyst_state_id"],"checkpoint_state_id":candidate["catalyst_state_id"],"hessian_sha256":"c"*64,"checkpoint_sha256":"d"*64,"evidence_ids":["seed_ev"],"intended_coordinate":[3,4]}},"decision":"approved_for_offline_result_intake","confirmed":True,"unresolved":[]}
        M.seal_local(source,"source_payload_sha256"); ap=root/"approval-source.json"; ap.write_text(json.dumps(source))
        return {"artifact_paths":{"candidate":str(cp),"m1_review":str(mp),"protocol_options":str(op),"protocol_selection":str(sp),"input_observation":str(ip),"input_approval_source":str(ap)}}

    def test_pre_run_path_adapter_needs_no_result_but_binds_file_and_payload_hashes(self):
        with tempfile.TemporaryDirectory() as td:
            req=self.make_path_case(td); out=M.approve_input_paths(req)
            self.assertNotIn("result_observation",req["artifact_paths"]); self.assertIn("normalized_payload_sha256",out["path_bindings"]["candidate"])
            p=Path(req["artifact_paths"]["candidate"]); data=json.loads(p.read_text()); data["candidate_id"]="forged"; p.write_text(json.dumps(data))
            with self.assertRaisesRegex(M.ContractError,"M1 candidate file SHA-256 mismatch"): M.approve_input_paths(req)

    def test_pre_run_path_adapter_fails_closed_on_missing_gate(self):
        with tempfile.TemporaryDirectory() as td:
            req=self.make_path_case(td); p=Path(req["artifact_paths"]["input_approval_source"]); source=json.loads(p.read_text()); source["unresolved"]=["basis gap"]; M.seal_local(source,"source_payload_sha256"); p.write_text(json.dumps(source))
            with self.assertRaisesRegex(M.ContractError,"source input_observation_sha256 mismatch|not fully approved"): M.approve_input_paths(req)

    def test_metal_schemas_are_fail_closed_at_top_and_key_nesting(self):
        schemas=ROOT/"contracts/metal-ts"
        for path in schemas.glob("*.schema.json"):
            schema=json.loads(path.read_text()); self.assertIs(schema.get("additionalProperties"),False,path.name)
            self.assertEqual(set(schema["required"]),set(schema["properties"]),path.name)
        approval=json.loads((schemas/"input-approval.schema.json").read_text())
        for key in ("identity","wavefunction","seed_strategy","path_bindings","authorizations"):
            node=approval["properties"][key]
            if "$ref" in node: node=approval["$defs"][node["$ref"].split("/")[-1]]
            self.assertIs(node.get("additionalProperties"),False,key)

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
