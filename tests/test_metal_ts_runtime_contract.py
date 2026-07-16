#!/usr/bin/env python3
from __future__ import annotations
import copy, importlib.util, json, tempfile, unittest
from pathlib import Path

ROOT=Path(__file__).parents[1]
P=ROOT/"skills/auto-g16-metal-ts/scripts/metal_ts.py"
spec=importlib.util.spec_from_file_location("metal_ts",P); assert spec and spec.loader
M=importlib.util.module_from_spec(spec); spec.loader.exec_module(M)
AP=ROOT/"skills/auto-g16-asymmetric-catalysis/scripts/asymmetric_catalysis.py"
aspec=importlib.util.spec_from_file_location("asym_builder_for_metal_runtime",AP); assert aspec and aspec.loader
A=importlib.util.module_from_spec(aspec); aspec.loader.exec_module(A)

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
        root=Path(root); cp=root/"candidate.json"; cp.write_bytes((ROOT/"tests/fixtures/asymmetric_catalysis/metal_candidate.json").read_bytes()); candidate=json.loads(cp.read_text())
        design=ROOT/"studies/metal_m4_p0_p1_baseline/contract-probe/m0-design.json"; template=ROOT/"studies/metal_m4_p0_p1_baseline/contract-probe/m2a-template.json"
        review_source=json.loads((ROOT/"tests/fixtures/asymmetric_catalysis/metal_scientific_review_complete.json").read_text())
        review_source["provenance"].update(scope_kind="primary_literature_bound_review",reviewer="chemist",review_date="2026-07-16")
        review_source["provenance"]["sources"][0].update(source_type="primary_article",citation="Bound test primary record",locator="test primary record")
        rsp=root/"m1-source.json"; rsp.write_text(json.dumps(review_source))
        mp=root/"m1.json"; A.build_metal_scientific_review(design,template,cp,rsp,mp)
        atoms=[{"index":x["index"],"atomic_number":{"Pd":46,"P":15,"C":6,"H":1}[x["element"]],"element":x["element"]} for x in candidate["atom_map"]]
        gjf=root/"input.gjf"; lines=["%chk=metal.chk","# b3lyp/genecp opt=(ts,calcfc) freq","","metal test","","0 1"]+[f"{x['element']} {x['index']}.0 0.0 0.0" for x in candidate["atom_map"]]+[""]; gjf.write_text("\n".join(lines))
        ip=root/"input-observation.json"; A.audit_metal_input_observation(template,cp,mp,gjf,ip)
        request={"schema":"gaussian-calculation-request/1","request_id":"metal_request","goal":"Bound offline metal TS input review","claim_scope":"No execution or path claim","task_types":["transition_state_optimization","harmonic_frequency"],"calculation_ready":False,"no_submission_authorization":True,"structure":{"sha256":candidate["geometry"]["artifact"]["sha256"],"formula":candidate["atom_inventory"]["formula"],"atom_count":len(atoms),"elements":["Pd","P","C","H"],"charge":0,"multiplicity":1},"support_status":"unsupported"}
        rp=root/"request.json"; rp.write_text(json.dumps(request))
        def make_option(tier,method,rank):
            profile={"profile_id":f"{tier}_profile","stages":["opt_freq"],"functional_or_method":method,"basis_stack":[{"elements":["Pd"],"orbital_basis":"b-pd","ecp":"ecp","ecp_core_electrons":28},{"elements":["P"],"orbital_basis":"b-p","ecp":None,"ecp_core_electrons":None},{"elements":["C"],"orbital_basis":"b-c","ecp":None,"ecp_core_electrons":None},{"elements":["H"],"orbital_basis":"b-h","ecp":None,"ecp_core_electrons":None}],"dispersion":{},"solvation":{"mode":"gas_phase"},"scf":{},"grid":"ultrafine","relativistic_treatment":"reviewed ECP scalar treatment","software_compatibility":"Gaussian 16 reviewed"}
            option={"tier":tier,"rigor_rank":M.PROTOCOL.RANKS[tier],"display_name":M.PROTOCOL.DISPLAY_NAMES[tier],"option_id":f"metal_{tier}","option_status":"selectable","purpose":f"{tier} bounded review","applicability":{},"limitations":["No accuracy guarantee"],"provenance":["reviewer-bound test fixture"],"unresolved":[],"resources":{"resource_tier":"simple","mem_gb":12,"cores":8,"job_count":1,"relative_cost_units":rank,"assumptions":["offline contract only"]},"expected_cost":{"band":tier,"drivers":["metal TS"]},"method_profiles":[profile],"task_plan":[{"stage_type":"transition_state_optimization","profile_id":profile["profile_id"],"acceptance_checks":["reviewed only"]},{"stage_type":"harmonic_frequency","profile_id":profile["profile_id"],"acceptance_checks":["reviewed only"]}],"validation_plan":{"mode":"offline"},"coverage_plan":{"scope":"bounded"}}
            option["option_payload_sha256"]=M.PROTOCOL.payload_sha256(option); return option
        opts=[make_option("loose","method_loose",1),make_option("standard","method_standard",2),make_option("strict","method_strict",3)]
        options={"schema":"gaussian-protocol-options/1","proposal_id":"metal_protocol","status":"ready_for_selection","calculation_ready":False,"no_input_render_authorization":True,"no_submission_authorization":True,"request_source":{"path":str(rp),"sha256":M.file_digest(rp)},"request_snapshot":request,"difficulty_assessment":{},"common_constraints":{},"options":opts,"comparison_notes":["Three reviewed alternatives"],"non_claims":["Strict is not an accuracy guarantee"]}; options["proposal_payload_sha256"]=M.PROTOCOL.payload_sha256(options); op=root/"options.json"; op.write_text(json.dumps(options))
        option=opts[1]; approval_note=root/"selection-approval.txt"; approval_note.write_text("explicit standard selection")
        selection={"schema":"gaussian-protocol-selection/1","selection_id":"metal_standard_selection","status":"selected_for_input_draft","calculation_ready":False,"no_submission_authorization":True,"options_source":{"path":str(op),"sha256":M.file_digest(op)},"request_sha256":M.file_digest(rp),"proposal_payload_sha256":options["proposal_payload_sha256"],"selected_option":{k:option[k] for k in ("option_id","option_payload_sha256","tier")},"scope_binding":{"structure_sha256":candidate["geometry"]["artifact"]["sha256"],"charge":0,"multiplicity":1,"task_types":["transition_state_optimization","harmonic_frequency"]},"approval_evidence":{"kind":"explicit_user_selection","explicit_confirmation":True,"path":str(approval_note),"sha256":M.file_digest(approval_note)},"decision_reason":"Bound standard option selected for offline fixture review.","alternatives_reviewed":["loose","standard","strict"],"authorizations":{"render_input_draft":True,"submit":False,"create_server_directory":False,"retry":False,"irc":False,"cancel":False,"cleanup":False}}
        selection["selection_payload_sha256"]=M.PROTOCOL.payload_sha256(selection); sp=root/"selection.json"; sp.write_text(json.dumps(selection))
        observed=json.loads(ip.read_text())["input_observations"]; review=lambda h: {"accepted":True,"evidence_sha256":h}
        source={"schema":"auto-g16-metal-ts-input-approval-source/1","source_bindings":{"candidate_sha256":M.file_digest(cp),"m1_review_sha256":M.file_digest(mp),"protocol_options_sha256":M.file_digest(op),"protocol_selection_sha256":M.file_digest(sp),"input_observation_sha256":M.file_digest(ip)},"metal_support_adapter":{"status":"reviewed_m1_extension","candidate_sha256":M.file_digest(cp),"m1_review_sha256":M.file_digest(mp)},"scope":{"scope_kind":"reviewer_bound_real_case","reviewer":"chemist","review_date":"2026-07-16"},"identity":{"charge":0,"multiplicity":1,"atom_count":len(atoms),"atom_order":atoms,"state_id":candidate["catalyst_state_id"]},"wavefunction":{"wavefunction":"restricted_closed_shell","state_id":candidate["catalyst_state_id"]},"reviews":{"route":review(observed["route_sha256"]),"basis_ecp_relativistic":{"basis_by_element":{"Pd":"b-pd","P":"b-p","C":"b-c","H":"b-h"},"ecp_elements":["Pd"],"ecp_by_element":{"Pd":{"name":"ecp","core_electrons":28,"evidence_id":"ecp_ev"}},"relativistic_treatment":"reviewed ECP scalar treatment","selected_option_payload_sha256":option["option_payload_sha256"]},"solvent":review(option["option_payload_sha256"]),"thermochemistry":review(option["option_payload_sha256"]),"resources":review(option["option_payload_sha256"]),"server_path":review("b"*64)|{"remote_workdir":"/home/user100/SDL/metal_case"},"seed_strategy":{"type":"hessian_guided_single_guess","state_id":candidate["catalyst_state_id"],"hessian_state_id":candidate["catalyst_state_id"],"checkpoint_state_id":candidate["catalyst_state_id"],"hessian_sha256":"c"*64,"checkpoint_sha256":"d"*64,"evidence_ids":["seed_ev"],"intended_coordinate":[1,4]}},"decision":"approved_for_offline_result_intake","confirmed":True,"unresolved":[]}
        M.seal_local(source,"source_payload_sha256"); ap=root/"approval-source.json"; ap.write_text(json.dumps(source))
        return {"artifact_paths":{"candidate":str(cp),"m1_review":str(mp),"protocol_options":str(op),"protocol_selection":str(sp),"input_observation":str(ip),"input_approval_source":str(ap)}}

    def make_post_path_case(self, root):
        root=Path(root); pre=self.make_path_case(root); approval=M.approve_input_paths(pre); approval_path=root/"input-approval.json"; approval_path.write_text(json.dumps(approval))
        candidate_path=Path(pre["artifact_paths"]["candidate"]); m1_path=Path(pre["artifact_paths"]["m1_review"]); input_obs_path=Path(pre["artifact_paths"]["input_observation"])
        template=ROOT/"studies/metal_m4_p0_p1_baseline/contract-probe/m2a-template.json"
        log_text=(ROOT/"tests/fixtures/asymmetric_catalysis/metal_observation_success.txt").read_text().replace(" Normal termination", " Frequencies --   410.0 520.0 630.0\n Frequencies --   740.0 850.0 960.0\n Frequencies --  1070.0 1180.0 1290.0\n Normal termination")
        log_path=root/"result.log"; log_path.write_text(log_text)
        result_path=root/"result-observation.json"; A.audit_metal_result_observation(template,candidate_path,log_path,result_path)
        mode_path=root/"mode-evidence.txt"; mode_path.write_text("reviewer-bound intended-coordinate displacement evidence")
        source=json.loads((ROOT/"tests/fixtures/asymmetric_catalysis/metal_acceptance_review_complete.json").read_text())
        result_sha=M.file_digest(result_path); approval_sha=M.file_digest(approval_path); lineage=M.digest({"input_approval_file_sha256":approval_sha,"result_observation_file_sha256":result_sha})
        source["source_bindings"]={"template_sha256":M.file_digest(template),"candidate_sha256":M.file_digest(candidate_path),"scientific_review_sha256":M.file_digest(m1_path),"input_observation_sha256":M.file_digest(input_obs_path),"result_observation_sha256":result_sha}
        source["scope"]={"scope_kind":"reviewer_bound_real_case","reviewer":"chemist","review_date":"2026-07-16","notes":["offline lineage contract fixture only"]}
        for section in source["sections"].values():
            for evidence in section["evidence"]: evidence["evidence_kind"]="reviewer_record"
        source["sections"]["mode"]["facts"]["mode_evidence_sha256"]=M.file_digest(mode_path)
        facts=source["sections"]["input_acceptance"]["facts"]; facts.update(input_sha256=approval["input_sha256"],protocol_options_sha256=approval["protocol_options_sha256"],protocol_selection_sha256=approval["protocol_selection_sha256"],input_approval_sha256=approval_sha,input_result_lineage_sha256=lineage)
        source_path=root/"m2d-source.json"; source_path.write_text(json.dumps(source))
        m2d_path=root/"m2d.json"; A.build_metal_acceptance_review(template,candidate_path,m1_path,input_obs_path,result_path,source_path,m2d_path)
        return {"artifact_paths":{"input_approval":str(approval_path),"result_observation":str(result_path),"m2d_acceptance":str(m2d_path),"mode_evidence":str(mode_path),"log":str(log_path)},"linearity_review":"nonlinear","decision":"accepted_for_explicit_promotion_review","confirmed":True}

    def test_pre_run_path_adapter_needs_no_result_but_binds_file_and_payload_hashes(self):
        with tempfile.TemporaryDirectory() as td:
            req=self.make_path_case(td); out=M.approve_input_paths(req)
            self.assertNotIn("result_observation",req["artifact_paths"]); self.assertIn("normalized_payload_sha256",out["path_bindings"]["candidate"])
            p=Path(req["artifact_paths"]["candidate"]); data=json.loads(p.read_text()); data["candidate_id"]="forged"; p.write_text(json.dumps(data))
            with self.assertRaisesRegex(M.ContractError,"M1 candidate file SHA-256 mismatch"): M.approve_input_paths(req)

    def test_pre_run_path_adapter_fails_closed_on_missing_gate(self):
        with tempfile.TemporaryDirectory() as td:
            req=self.make_path_case(td); p=Path(req["artifact_paths"]["input_approval_source"]); source=json.loads(p.read_text()); source["unresolved"]=["basis gap"]; M.seal_local(source,"source_payload_sha256"); p.write_text(json.dumps(source))
            with self.assertRaisesRegex(M.ContractError,"strict input approval source validation|not fully approved"): M.approve_input_paths(req)

    def test_pre_run_strict_schemas_reject_rehashed_unknown_fields(self):
        for key, hash_field, hasher, pattern in (("protocol_options","proposal_payload_sha256",lambda d:M.PROTOCOL.payload_sha256(M.PROTOCOL._without(d,"proposal_payload_sha256")),"strict protocol schema"),("protocol_selection","selection_payload_sha256",lambda d:M.PROTOCOL.payload_sha256(M.PROTOCOL._without(d,"selection_payload_sha256")),"strict protocol schema"),("input_approval_source","source_payload_sha256",lambda d:M.payload_hash(d,"source_payload_sha256"),"strict input approval source")):
            with self.subTest(key=key), tempfile.TemporaryDirectory() as td:
                req=self.make_path_case(td); path=Path(req["artifact_paths"][key]); data=json.loads(path.read_text()); data["unknown_field"]="forged"; data[hash_field]=hasher(data); path.write_text(json.dumps(data))
                if key == "protocol_options":
                    selection_path=Path(req["artifact_paths"]["protocol_selection"]); selection=json.loads(selection_path.read_text()); selection["proposal_payload_sha256"]=data["proposal_payload_sha256"]; selection["options_source"]["sha256"]=M.file_digest(path); selection["selection_payload_sha256"]=M.PROTOCOL.payload_sha256(M.PROTOCOL._without(selection,"selection_payload_sha256")); selection_path.write_text(json.dumps(selection))
                source_path=Path(req["artifact_paths"]["input_approval_source"]); source=json.loads(source_path.read_text())
                if key in {"protocol_options","protocol_selection"}:
                    source["source_bindings"]["protocol_options_sha256"]=M.file_digest(req["artifact_paths"]["protocol_options"]); source["source_bindings"]["protocol_selection_sha256"]=M.file_digest(req["artifact_paths"]["protocol_selection"]); source["source_payload_sha256"]=M.payload_hash(source,"source_payload_sha256"); source_path.write_text(json.dumps(source))
                with self.assertRaisesRegex(M.ContractError,pattern): M.approve_input_paths(req)

    def test_post_run_path_is_strictly_forward_and_accepts_original_approval(self):
        with tempfile.TemporaryDirectory() as td:
            req=self.make_post_path_case(td); out=M.accept_result_paths(req)
            self.assertEqual(out["input_approval_sha256"],M.file_digest(req["artifact_paths"]["input_approval"]))
            self.assertEqual(out["input_result_lineage_sha256"],M.digest({"input_approval_file_sha256":M.file_digest(req["artifact_paths"]["input_approval"]),"result_observation_file_sha256":M.file_digest(req["artifact_paths"]["result_observation"])}))

    def test_post_run_path_rejects_file_and_schema_tampering(self):
        mutations=[("log","log_source|payload hash|log file"),("mode_evidence","mode evidence"),("result_observation","payload hash|strict post-run|Extra data"),("m2d_acceptance","payload hash|strict post-run|Extra data")]
        for name,pattern in mutations:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as td:
                req=self.make_post_path_case(td); path=Path(req["artifact_paths"][name]); path.write_bytes(path.read_bytes()+b"\nTAMPER")
                with self.assertRaisesRegex((M.ContractError,json.JSONDecodeError),pattern): M.accept_result_paths(req)
        with tempfile.TemporaryDirectory() as td:
            req=self.make_post_path_case(td); path=Path(req["artifact_paths"]["result_observation"]); data=json.loads(path.read_text()); data["unknown_field"]="forged"; data["audit_payload_sha256"]=A.sha256_data({k:v for k,v in data.items() if k!="audit_payload_sha256"}); path.write_text(json.dumps(data))
            with self.assertRaisesRegex(M.ContractError,"strict post-run"): M.accept_result_paths(req)

    def test_post_run_rejects_resealed_m2d_lineage_forgery(self):
        for field in ("input_approval_sha256","input_result_lineage_sha256"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as td:
                req=self.make_post_path_case(td); path=Path(req["artifact_paths"]["m2d_acceptance"]); data=json.loads(path.read_text()); data["sections"]["input_acceptance"]["facts"][field]="f"*64; data["review_payload_sha256"]=A.sha256_data({k:v for k,v in data.items() if k!="review_payload_sha256"}); path.write_text(json.dumps(data))
                with self.assertRaisesRegex(M.ContractError,"lineage"): M.accept_result_paths(req)

    def test_post_run_rejects_resealed_result_candidate_lineage_forgery(self):
        with tempfile.TemporaryDirectory() as td:
            req=self.make_post_path_case(td); result_path=Path(req["artifact_paths"]["result_observation"]); result=json.loads(result_path.read_text()); result["candidate_source"]["sha256"]="e"*64; result["audit_payload_sha256"]=A.sha256_data({k:v for k,v in result.items() if k!="audit_payload_sha256"}); result_path.write_text(json.dumps(result))
            m2d_path=Path(req["artifact_paths"]["m2d_acceptance"]); m2d=json.loads(m2d_path.read_text()); m2d["result_observation_source"]["sha256"]=M.file_digest(result_path); m2d["review_payload_sha256"]=A.sha256_data({k:v for k,v in m2d.items() if k!="review_payload_sha256"}); m2d_path.write_text(json.dumps(m2d))
            with self.assertRaisesRegex(M.ContractError,"result/candidate lineage mismatch"): M.accept_result_paths(req)

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
