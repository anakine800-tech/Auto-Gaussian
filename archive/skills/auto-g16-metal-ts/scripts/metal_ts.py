#!/usr/bin/env python3
"""Deterministic offline-only transition-metal TS P2-P4 contracts."""
from __future__ import annotations

import argparse, copy, hashlib, importlib.util, json, math, re
from pathlib import Path
from typing import Any

class ContractError(ValueError): pass

def require(ok: bool, message: str) -> None:
    if not ok: raise ContractError(message)

def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()

def file_digest(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def payload_hash(obj: dict[str, Any], field: str) -> str:
    return digest({k: v for k, v in obj.items() if k != field})

def verify(obj: dict[str, Any], field: str, label: str) -> None:
    require(obj.get(field) == payload_hash(obj, field), f"{label} payload hash mismatch")

def load(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8")); require(isinstance(value, dict), "JSON object required"); return value

def write(path: Path, value: dict[str, Any]) -> None:
    require(not path.exists(), f"refusing to overwrite {path}"); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")

DENIALS = {"render_input": False, "ssh": False, "pbs": False, "gaussian": False, "submit": False, "retry": False, "cancel": False, "cleanup": False, "deploy": False}

def _load_repo_module(name: str, relative: str):
    path=Path(__file__).resolve().parents[3]/relative
    spec=importlib.util.spec_from_file_location(name,path); require(spec is not None and spec.loader is not None,f"cannot load {relative}")
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module

ASYM=_load_repo_module("auto_g16_asymmetric_validator","scripts/validate_asymmetric_contract.py")
PROTOCOL=_load_repo_module("auto_g16_protocol_selection","skills/auto-g16-rtwin-pbs/scripts/protocol_selection.py")

def _validate_local_schema(value: dict[str, Any], filename: str) -> None:
    schema=load(Path(__file__).resolve().parents[3]/"contracts/metal-ts"/filename)
    ASYM.validate_schema_document(schema); ASYM._validate_schema_instance(value,schema,schema)

def _validate_repo_schema(value: dict[str, Any], relative: str) -> None:
    schema=load(Path(__file__).resolve().parents[3]/relative)
    ASYM.validate_schema_document(schema); ASYM._validate_schema_instance(value,schema,schema)

def _validate_metal_protocol(options: dict[str, Any], selection: dict[str, Any], candidate: dict[str, Any], source: dict[str, Any], candidate_path: Path, m1_path: Path) -> dict[str, Any]:
    """Strict protocol validation with an explicit M1-bound metal extension adapter."""
    try:
        _validate_repo_schema(options,"contracts/gaussian-protocol/options.schema.json")
        _validate_repo_schema(selection,"contracts/gaussian-protocol/selection.schema.json")
    except Exception as exc: raise ContractError(f"strict protocol schema validation failed: {exc}") from exc
    request=options.get("request_snapshot",{}); PROTOCOL.validate_request(request)
    require(request.get("support_status")=="unsupported","metal request must retain unsupported support status")
    adapter=source.get("metal_support_adapter",{})
    require(adapter=={"status":"reviewed_m1_extension","candidate_sha256":file_digest(candidate_path),"m1_review_sha256":file_digest(m1_path)},"metal support adapter is absent or unbound")
    request_source=options.get("request_source",{}); request_path=Path(str(request_source.get("path",""))).expanduser().resolve()
    require(request_path.is_file() and not request_path.is_symlink(),"protocol request artifact is unavailable")
    require(file_digest(request_path)==request_source.get("sha256") and load(request_path)==request,"options request snapshot differs from bound request artifact")
    require(request.get("structure",{}).get("sha256")==candidate.get("geometry",{}).get("artifact",{}).get("sha256"),"options request candidate structure mismatch")
    require(request.get("structure",{}).get("charge")==candidate.get("electronic_state",{}).get("charge") and request.get("structure",{}).get("multiplicity")==candidate.get("electronic_state",{}).get("multiplicity"),"options request candidate scope mismatch")
    candidate_elements=[x.get("element") for x in candidate.get("atom_map",[])]; structure=request.get("structure",{})
    require(structure.get("atom_count")==len(candidate_elements) and set(structure.get("elements",[]))==set(candidate_elements) and len(structure.get("elements",[]))==len(set(structure.get("elements",[]))),"options request atom count/elements mismatch")
    formula=candidate.get("atom_inventory",{}).get("formula"); require(not formula or structure.get("formula")==formula,"options request formula mismatch")
    require(options.get("schema")=="gaussian-protocol-options/1" and options.get("status")=="ready_for_selection" and options.get("calculation_ready") is False and options.get("no_input_render_authorization") is True and options.get("no_submission_authorization") is True,"protocol options boundary mismatch")
    option_list=options.get("options",[]); require(len(option_list)==3 and {x.get("tier") for x in option_list}=={"loose","standard","strict"},"options require complete three-tier artifacts")
    require(len({x.get("option_id") for x in option_list})==3,"protocol option IDs must be unique")
    supported=copy.deepcopy(request); supported["support_status"]="supported"
    for option in option_list:
        PROTOCOL._validate_option(option,supported)
        require(option.get("option_payload_sha256")==PROTOCOL.payload_sha256(PROTOCOL._without(option,"option_payload_sha256")),f"option[{option.get('tier')}]: payload hash mismatch")
    require(len({PROTOCOL._scientific_signature(x) for x in option_list})>1,"all three protocol options are scientifically identical")
    require(options.get("proposal_payload_sha256")==PROTOCOL.payload_sha256(PROTOCOL._without(options,"proposal_payload_sha256")),"options proposal payload hash mismatch")
    require(selection.get("schema")=="gaussian-protocol-selection/1" and selection.get("status")=="selected_for_input_draft" and selection.get("calculation_ready") is False and selection.get("no_submission_authorization") is True,"protocol selection boundary mismatch")
    require(selection.get("request_sha256")==request_source.get("sha256") and selection.get("proposal_payload_sha256")==options.get("proposal_payload_sha256"),"selection request/options binding mismatch")
    options_source=selection.get("options_source",{}); bound_options=Path(str(options_source.get("path",""))).expanduser().resolve()
    require(bound_options.is_file() and not bound_options.is_symlink() and options_source.get("sha256")==file_digest(bound_options),"selection options source file/hash mismatch")
    option=PROTOCOL.get_selected_option(options,selection); require(option.get("option_status")=="selectable" and option.get("unresolved")==[],"selected protocol option is blocked or unresolved")
    require(selection.get("alternatives_reviewed")==["loose","standard","strict"],"selection alternatives review is incomplete")
    require(isinstance(selection.get("decision_reason"),str) and selection["decision_reason"].strip(),"selection decision reason missing")
    approval=selection.get("approval_evidence",{}); require(approval.get("kind")=="explicit_user_selection" and approval.get("explicit_confirmation") is True,"selection explicit confirmation missing")
    approval_path=Path(str(approval.get("path",""))).expanduser().resolve(); require(approval_path.is_file() and not approval_path.is_symlink() and file_digest(approval_path)==approval.get("sha256"),"selection approval evidence file/hash mismatch")
    expected_scope={"structure_sha256":request["structure"]["sha256"],"charge":request["structure"]["charge"],"multiplicity":request["structure"]["multiplicity"],"task_types":request["task_types"]}
    require(selection.get("scope_binding")==expected_scope,"selection calculation scope mismatch")
    require(selection.get("selection_payload_sha256")==PROTOCOL.payload_sha256(PROTOCOL._without(selection,"selection_payload_sha256")),"selection payload hash mismatch")
    return option

def approve_input_paths(r: dict[str, Any]) -> dict[str, Any]:
    """Pre-run approval: no result, log, M2d, or live action is required."""
    paths=r["artifact_paths"]
    candidate_path=Path(paths["candidate"]); m1_path=Path(paths["m1_review"])
    options_path=Path(paths["protocol_options"]); selection_path=Path(paths["protocol_selection"])
    observation_path=Path(paths["input_observation"]); source_path=Path(paths["input_approval_source"])
    all_paths=(candidate_path,m1_path,options_path,selection_path,observation_path,source_path)
    for path in all_paths:
        require(path.is_file() and not path.is_symlink(), f"artifact path must be a regular non-symlink file: {path}")
    raw_c,raw_m,raw_o,raw_s,raw_i,source=map(load,all_paths)
    try:
        ASYM.validate_structure(raw_c,"candidate"); ASYM.validate_structure(raw_m,"metal-scientific-review"); ASYM.validate_structure(raw_i,"metal-input-observation")
    except Exception as exc: raise ContractError(f"strict asymmetric artifact validation failed: {exc}") from exc
    require(source.get("schema")=="auto-g16-metal-ts-input-approval-source/1","input approval source schema mismatch")
    try: _validate_local_schema(source,"input-approval-source.schema.json")
    except Exception as exc: raise ContractError(f"strict input approval source validation failed: {exc}") from exc
    require(raw_m.get("review_payload_sha256")==ASYM.payload_sha256({k:v for k,v in raw_m.items() if k!="review_payload_sha256"}),"M1 payload hash mismatch")
    require(raw_i.get("audit_payload_sha256")==ASYM.payload_sha256({k:v for k,v in raw_i.items() if k!="audit_payload_sha256"}),"input observation payload hash mismatch")
    require(raw_o.get("proposal_payload_sha256")==PROTOCOL.payload_sha256(PROTOCOL._without(raw_o,"proposal_payload_sha256")),"options payload hash mismatch")
    require(raw_s.get("selection_payload_sha256")==PROTOCOL.payload_sha256(PROTOCOL._without(raw_s,"selection_payload_sha256")),"selection payload hash mismatch")
    verify(source,"source_payload_sha256","input approval source")
    c_file=file_digest(candidate_path); require(raw_m.get("candidate_source",{}).get("sha256")==c_file,"M1 candidate file SHA-256 mismatch")
    require(raw_c.get("support_status")=="unsupported_transition_metal" and raw_c.get("calculation_ready") is False and raw_c.get("no_submission_authorization") is True,"candidate support/authority boundary mismatch")
    require(raw_c.get("chemical_state",{}).get("charge")==raw_c.get("electronic_state",{}).get("charge") and raw_c.get("chemical_state",{}).get("multiplicity")==raw_c.get("electronic_state",{}).get("multiplicity"),"candidate chemical/electronic state mismatch")
    require(raw_s.get("proposal_payload_sha256")==raw_o["proposal_payload_sha256"],"selection options payload mismatch")
    require(raw_i.get("candidate_source",{}).get("sha256")==c_file,"input observation candidate file SHA-256 mismatch")
    require(raw_i.get("scientific_review_source",{}).get("sha256")==file_digest(m1_path),"input observation M1 file SHA-256 mismatch")
    expected_source={"candidate_sha256":candidate_path,"m1_review_sha256":m1_path,"protocol_options_sha256":options_path,"protocol_selection_sha256":selection_path,"input_observation_sha256":observation_path}
    for field,path in expected_source.items(): require(source.get("source_bindings",{}).get(field)==file_digest(path),f"input approval source {field} mismatch")
    require(raw_m.get("completion",{}).get("metal_m1_scientific_review_status")=="reviewed_bounded_example_runtime_unsupported","real M1 status required")
    require(raw_m.get("review_scope",{}).get("scope_kind") in {"primary_literature_bound_review","mixed_primary_and_reviewer_evidence"},"real M1 evidence scope required")
    for name in ("electron_accounting","spin_surface","wavefunction","coordination","method_protocol","ts_and_path"):
        require(raw_m.get("sections",{}).get(name,{}).get("status")=="reviewed_for_bounded_example",f"M1 section {name} is not reviewed")
    require(source.get("scope",{}).get("scope_kind")=="reviewer_bound_real_case" and source.get("scope",{}).get("reviewer") and re.fullmatch(r"\d{4}-\d{2}-\d{2}",str(source.get("scope",{}).get("review_date",""))),"reviewer-bound real input approval required")
    require(source.get("decision")=="approved_for_offline_result_intake" and source.get("confirmed") is True and source.get("unresolved")==[],"input approval source is not fully approved")
    candidate_payload=digest(raw_c)
    atom_order=source["identity"]["atom_order"]
    require(source["identity"]["atom_count"]==len(atom_order) and [x["index"] for x in atom_order]==list(range(1,len(atom_order)+1)),"atom order must be contiguous, indexed, and count-bound")
    require([x["element"] for x in atom_order]==[x["element"] for x in raw_c["atom_map"]],"candidate/M2d atom order mismatch")
    identity={"charge":raw_c["electronic_state"]["charge"],"multiplicity":raw_c["electronic_state"]["multiplicity"],"atom_count":len(atom_order),"atom_order":atom_order,"state_id":raw_c["catalyst_state_id"]}
    require(source.get("identity")==identity,"input approval source identity mismatch")
    require(source.get("wavefunction",{}).get("state_id")==identity["state_id"] and source.get("wavefunction",{}).get("wavefunction"),"input approval wavefunction/state mismatch")
    require(raw_m.get("candidate_id")==raw_c.get("candidate_id") and raw_m.get("identity_binding",{}).get("total_charge")==identity["charge"] and raw_m.get("identity_binding",{}).get("multiplicity")==identity["multiplicity"],"M1 normalized candidate identity mismatch")
    option=_validate_metal_protocol(raw_o,raw_s,raw_c,source,candidate_path,m1_path)
    scope=raw_s.get("scope_binding",{})
    require(set(scope.get("task_types",[]))>={"transition_state_optimization","harmonic_frequency"},"protocol selection task scope mismatch")
    reviews=source["reviews"]; coverage=reviews["basis_ecp_relativistic"]; elements={x["element"] for x in atom_order}; ecp=set(coverage.get("ecp_elements",[]))
    require(set(coverage.get("basis_by_element",{}))==elements,"basis coverage incomplete")
    require(set(coverage.get("ecp_by_element",{}))==ecp and ecp<=elements,"ECP inventory mismatch")
    require(isinstance(coverage.get("relativistic_treatment"),str) and coverage["relativistic_treatment"].strip(),"relativistic treatment required")
    for el in ecp:
        item=coverage["ecp_by_element"][el]; require(item.get("name") and isinstance(item.get("core_electrons"),int) and item.get("evidence_id"),"ECP coverage incomplete")
    require(coverage.get("selected_option_payload_sha256")==option.get("option_payload_sha256"),"basis/ECP review is not bound to selected profile")
    exact_tasks=[x for x in option.get("task_plan",[]) if x.get("stage_type") in {"transition_state_optimization","harmonic_frequency"}]
    exact_profile_ids={x.get("profile_id") for x in exact_tasks}
    require({x.get("stage_type") for x in exact_tasks}=={"transition_state_optimization","harmonic_frequency"} and len(exact_profile_ids)==1,"TS optimization and frequency tasks must reference one exact-input profile")
    normalized_profiles=[]
    for profile in option.get("method_profiles",[]):
        if profile.get("profile_id") not in exact_profile_ids: continue
        basis={}; profile_ecp={}
        for stack in profile.get("basis_stack",[]):
            for element in stack.get("elements",[]): basis[element]=stack.get("orbital_basis")
            if stack.get("ecp") is not None:
                for element in stack.get("elements",[]): profile_ecp[element]={"name":stack.get("ecp"),"core_electrons":stack.get("ecp_core_electrons")}
        normalized_profiles.append((basis,profile_ecp,profile.get("relativistic_treatment")))
    require(normalized_profiles and all(x[0]==coverage.get("basis_by_element") for x in normalized_profiles),"basis review differs from selected method profile")
    require(all(set(x[1])==ecp and all(x[1][el]["name"]==coverage["ecp_by_element"][el]["name"] and x[1][el]["core_electrons"]==coverage["ecp_by_element"][el]["core_electrons"] for el in ecp) for x in normalized_profiles),"ECP review differs from selected method profile")
    require(all(x[2]==coverage.get("relativistic_treatment") for x in normalized_profiles),"relativistic review differs from selected method profile")
    if not ecp:
        text=coverage["relativistic_treatment"].lower(); require("all-electron" in text and "no-ecp" in text,"all-electron metal review must explicitly state all-electron/no-ECP")
    observed=raw_i.get("input_observations",{}); route=observed.get("route_text",""); route_lower=route.lower()
    require(observed.get("route_sha256")==hashlib.sha256(route.encode()).hexdigest(),"input observation route hash mismatch")
    require(source.get("reviews",{}).get("route",{}).get("evidence_sha256")==observed.get("route_sha256"),"route review is not bound to observed route")
    require(all(token not in route_lower for token in ("qst2","qst3","irc","scan","neb","string","mecp")),"unsupported TS/path strategy observed in route")
    tasks=observed.get("task_text_observations",{}); require(tasks.get("opt_text_observed") and tasks.get("freq_text_observed") and tasks.get("ts_text_observed") and ("calcfc" in route_lower or "readfc" in route_lower),"route is not an exact Hessian-guided TS Opt/Freq task")
    for name in ("solvent","thermochemistry","resources"):
        require(reviews.get(name,{}).get("evidence_sha256")==option.get("option_payload_sha256"),f"{name} review is not bound to selected option")
    for name in ("route","solvent","thermochemistry","resources","server_path"):
        require(reviews.get(name,{}).get("accepted") is True and re.fullmatch(r"[0-9a-f]{64}",str(reviews[name].get("evidence_sha256",""))),f"{name} review is incomplete")
    require(re.fullmatch(r"/home/user100/SDL/[A-Za-z0-9_]+",reviews["server_path"].get("remote_workdir","")) is not None,"server path review is outside SDL")
    seed=reviews["seed_strategy"]; require(seed.get("type")=="hessian_guided_single_guess","unsupported seed strategy")
    require(seed.get("state_id")==identity["state_id"]==seed.get("hessian_state_id")==seed.get("checkpoint_state_id"),"cross-state checkpoint/Hessian reuse forbidden")
    require(re.fullmatch(r"[0-9a-f]{64}",str(seed.get("hessian_sha256",""))) and re.fullmatch(r"[0-9a-f]{64}",str(seed.get("checkpoint_sha256",""))),"Hessian/checkpoint hashes required")
    coordinate=seed.get("intended_coordinate",[]); require(len(coordinate)>=2 and len(coordinate)==len(set(coordinate)) and all(isinstance(x,int) and 1<=x<=identity["atom_count"] for x in coordinate),"seed intended coordinate indices are invalid")
    candidate_coordinates=[x.get("atoms") for x in raw_c.get("coordinate_changes",[])]; m1_coordinates=[x.get("atoms") for x in raw_m.get("sections",{}).get("ts_and_path",{}).get("facts",{}).get("coordinate_changes",[])]
    require(coordinate in candidate_coordinates and coordinate in m1_coordinates,"seed intended coordinate differs from candidate/M1 TS-path review")
    ib=raw_i["identity_binding"]
    normalized={"wavefunction_review":copy.deepcopy(source["wavefunction"]),"basis_ecp_review":copy.deepcopy(coverage),"seed_strategy":copy.deepcopy(seed),"decision":source["decision"],"confirmed":source["confirmed"],"candidate":seal_local({"identity":identity,"candidate_id":raw_c["candidate_id"],"source_sha256":c_file,"normalized_payload_sha256":candidate_payload},"candidate_payload_sha256"),"m1_review":seal_local({"candidate_sha256":None,"completion":{"metal_m1_scientific_review_status":raw_m["completion"]["metal_m1_scientific_review_status"]},"source_sha256":file_digest(m1_path),"normalized_payload_sha256":digest(raw_m)},"review_payload_sha256"),"protocol_options":seal_local({"source_sha256":file_digest(options_path),"normalized_payload_sha256":digest(raw_o)},"options_payload_sha256"),"protocol_selection":seal_local({"options_payload_sha256":None,"candidate_sha256":None,"source_sha256":file_digest(selection_path),"normalized_payload_sha256":digest(raw_s)},"selection_payload_sha256"),"input_observation":seal_local({"candidate_sha256":None,"observed":{"charge":ib["charge"],"multiplicity":ib["multiplicity"],"atom_order":ib["atom_order"],"input_sha256":raw_i["input_source"]["sha256"]},"source_sha256":file_digest(observation_path),"normalized_payload_sha256":digest(raw_i)},"audit_payload_sha256")}
    ch=normalized["candidate"]["candidate_payload_sha256"]; normalized["m1_review"]["candidate_sha256"]=ch; normalized["m1_review"]["review_payload_sha256"]=payload_hash(normalized["m1_review"],"review_payload_sha256")
    oh=normalized["protocol_options"]["options_payload_sha256"]; normalized["protocol_selection"].update(options_payload_sha256=oh,candidate_sha256=ch); normalized["protocol_selection"]["selection_payload_sha256"]=payload_hash(normalized["protocol_selection"],"selection_payload_sha256")
    normalized["input_observation"]["candidate_sha256"]=ch; normalized["input_observation"]["audit_payload_sha256"]=payload_hash(normalized["input_observation"],"audit_payload_sha256")
    normalized["identity_review"]={"atom_count":identity["atom_count"],"atom_order":copy.deepcopy(atom_order),"charge":identity["charge"],"multiplicity":identity["multiplicity"],"state_id":identity["state_id"]}
    out=approve_input(normalized); out["schema"]="auto-g16-metal-ts-input-approval/1"; out["input_approval_source_sha256"]=file_digest(source_path)
    out["path_bindings"]={name:{"sha256":file_digest(path),"normalized_payload_sha256":digest(load(path))} for name,path in zip(("candidate","m1_review","protocol_options","protocol_selection","input_observation","input_approval_source"),all_paths)}
    out["approval_payload_sha256"]=payload_hash(out,"approval_payload_sha256"); _validate_local_schema(out,"input-approval.schema.json"); return out

def seal_local(obj: dict[str, Any], field: str) -> dict[str, Any]:
    obj[field]=payload_hash(obj,field); return obj

def approve_input(r: dict[str, Any]) -> dict[str, Any]:
    c,m,o,s,i = (r[k] for k in ("candidate","m1_review","protocol_options","protocol_selection","input_observation"))
    for obj,field,label in ((c,"candidate_payload_sha256","candidate"),(m,"review_payload_sha256","M1"),(o,"options_payload_sha256","options"),(s,"selection_payload_sha256","selection"),(i,"audit_payload_sha256","input observation")): verify(obj,field,label)
    require(m.get("completion",{}).get("metal_m1_scientific_review_status") == "reviewed_bounded_example_runtime_unsupported", "real completed M1 required")
    require(m.get("candidate_sha256") == c["candidate_payload_sha256"], "M1 candidate binding mismatch")
    require(s.get("options_payload_sha256") == o["options_payload_sha256"], "protocol selection/options mismatch")
    require(s.get("candidate_sha256") == c["candidate_payload_sha256"], "protocol selection candidate mismatch")
    require(i.get("candidate_sha256") == c["candidate_payload_sha256"], "input observation candidate mismatch")
    ident=r["identity_review"]; expected=c["identity"]
    for k in ("charge","multiplicity","atom_order","state_id"): require(ident.get(k)==expected.get(k), f"wrong {k}")
    require(i.get("observed",{}).get("charge")==ident["charge"] and i.get("observed",{}).get("multiplicity")==ident["multiplicity"], "input charge/multiplicity mismatch")
    require(i.get("observed",{}).get("atom_order")==ident["atom_order"], "input atom order mismatch")
    require(r.get("seed_strategy",{}).get("type")=="hessian_guided_single_guess", "unsupported seed strategy")
    seed=r["seed_strategy"]; require(seed.get("state_id")==ident["state_id"] and seed.get("hessian_state_id")==ident["state_id"] and seed.get("checkpoint_state_id")==ident["state_id"], "cross-state checkpoint/Hessian reuse forbidden")
    require(seed.get("evidence_ids") and seed.get("intended_coordinate"), "Hessian-guided seed evidence incomplete")
    coverage=r["basis_ecp_review"]; elements={x["element"] if isinstance(x,dict) else x for x in ident["atom_order"]}
    require(set(coverage.get("basis_by_element",{}))==elements, "basis coverage incomplete")
    ecp=set(coverage.get("ecp_elements",[])); require(set(coverage.get("ecp_by_element",{}))==ecp and ecp<=elements,"ECP inventory mismatch")
    for el in ecp:
        e=coverage.get("ecp_by_element",{}).get(el,{}); require(e.get("name") and isinstance(e.get("core_electrons"),int) and e.get("evidence_id"), "ECP coverage incomplete")
    if not ecp:
        text=str(coverage.get("relativistic_treatment","")).lower(); require("all-electron" in text and "no-ecp" in text,"all-electron metal review must explicitly state all-electron/no-ECP")
    require(r.get("decision")=="approved_for_offline_result_intake" and r.get("confirmed") is True, "explicit input approval required")
    out={"schema":"auto-g16-metal-ts-input-approval/1","candidate_sha256":c["candidate_payload_sha256"],"m1_review_sha256":m["review_payload_sha256"],"protocol_options_sha256":o["options_payload_sha256"],"protocol_selection_sha256":s["selection_payload_sha256"],"input_observation_sha256":i["audit_payload_sha256"],"input_sha256":i["observed"]["input_sha256"],"identity":copy.deepcopy(ident),"wavefunction":copy.deepcopy(r["wavefunction_review"]),"basis_ecp_review":copy.deepcopy(coverage),"seed_strategy":copy.deepcopy(seed),"decision":"approved_for_offline_result_intake","authorizations":copy.deepcopy(DENIALS),"submission_decision":"refused"}
    out["schema"]="auto-g16-metal-ts-normalized-input-approval-internal/1"
    out["approval_payload_sha256"]=payload_hash(out,"approval_payload_sha256"); return out

def accept_result(r: dict[str, Any]) -> dict[str, Any]:
    a,x=r["input_approval"],r["result_observation"]; verify(a,"approval_payload_sha256","input approval"); verify(x,"audit_payload_sha256","result observation")
    require(x.get("candidate_sha256")==a["candidate_sha256"] and x.get("input_sha256")==a["input_sha256"], "result lineage mismatch")
    f=x["facts"]; ident=a["identity"]
    for k in ("charge","multiplicity","atom_order","state_id"): require(f.get(k)==ident.get(k), f"result wrong {k}")
    require(f.get("normal_termination") is True and f.get("stationary_point") is True, "terminal/stationary evidence failed")
    freqs=f.get("frequencies",[]); require(f.get("frequency_complete") is True and len(freqs)==f.get("expected_frequency_count"), "incomplete frequencies")
    require(sum(v<0 for v in freqs)==1, "result must have exactly one imaginary frequency")
    wf=r["wavefunction_acceptance"]; require(wf.get("state_id")==ident["state_id"] and wf.get("wavefunction")==a["wavefunction"]["wavefunction"], "wrong electronic state/wavefunction")
    require(wf.get("stability_tested") is True and wf.get("stable") is True, "stability evidence required")
    s2=float(wf["s2_after"]); require(math.isfinite(s2) and abs(s2-float(wf["s2_target"]))<=float(wf["s2_tolerance"]), "spin contamination exceeds reviewed bound")
    coord=r["coordination_acceptance"]; require(coord.get("ligand_inventory_retained") is True and coord.get("observed_ligands")==coord.get("expected_ligands"), "ligand inventory loss")
    for contact in coord.get("contacts",[]): require(contact["minimum"]<=contact["observed"]<=contact["maximum"], "coordination contact outside reviewed range")
    mode=r["mode_evidence"]; require(mode.get("result_observation_sha256")==x["audit_payload_sha256"], "mode evidence result binding mismatch")
    require(mode.get("imaginary_frequency_index")==freqs.index(next(v for v in freqs if v<0)) and mode.get("intended_coordinate_confirmed") is True and mode.get("unintended_coordination_or_ligand_loss") is False and mode.get("reviewer") and mode.get("evidence_sha256"), "wrong or incomplete imaginary-mode evidence")
    require(r.get("decision")=="accepted_for_explicit_promotion_review" and r.get("confirmed") is True, "explicit result acceptance required")
    out={"schema":"auto-g16-metal-ts-result-acceptance/1","input_approval_sha256":a["approval_payload_sha256"],"candidate_sha256":a["candidate_sha256"],"result_observation_sha256":x["audit_payload_sha256"],"wavefunction_acceptance":wf,"coordination_acceptance":coord,"mode_evidence":mode,"decision":"accepted_for_explicit_promotion_review","promotion_decision":"not_yet_made","authorizations":DENIALS,"submission_decision":"refused"}
    out["schema"]="auto-g16-metal-ts-normalized-result-acceptance-internal/1"
    out["acceptance_payload_sha256"]=payload_hash(out,"acceptance_payload_sha256"); return out

def accept_result_paths(r: dict[str, Any]) -> dict[str, Any]:
    paths=r["artifact_paths"]; names=("input_approval","result_observation","m2d_acceptance","mode_evidence","log")
    ps={name:Path(paths[name]) for name in names}
    for path in ps.values(): require(path.is_file() and not path.is_symlink(),f"artifact path must be a regular non-symlink file: {path}")
    approval,result,m2d=load(ps["input_approval"]),load(ps["result_observation"]),load(ps["m2d_acceptance"])
    try:
        _validate_local_schema(approval,"input-approval.schema.json")
        ASYM.validate_structure(result,"metal-result-observation")
        ASYM.validate_structure(m2d,"metal-acceptance-review")
    except Exception as exc: raise ContractError(f"strict post-run artifact validation failed: {exc}") from exc
    verify(approval,"approval_payload_sha256","input approval")
    require(result.get("audit_payload_sha256")==ASYM.payload_sha256({k:v for k,v in result.items() if k!="audit_payload_sha256"}),"result observation payload hash mismatch")
    require(m2d.get("review_payload_sha256")==ASYM.payload_sha256({k:v for k,v in m2d.items() if k!="review_payload_sha256"}),"M2d payload hash mismatch")
    approval_file_sha=file_digest(ps["input_approval"]); result_file_sha=file_digest(ps["result_observation"])
    require(result.get("candidate_source",{}).get("sha256")==approval.get("path_bindings",{}).get("candidate",{}).get("sha256"),"result/candidate lineage mismatch")
    require(result.get("log_source",{}).get("sha256")==file_digest(ps["log"]),"result observation/log file SHA-256 mismatch")
    require(m2d.get("candidate_source",{}).get("sha256")==approval.get("path_bindings",{}).get("candidate",{}).get("sha256"),"M2d/candidate lineage mismatch")
    require(m2d.get("input_observation_source",{}).get("sha256")==approval.get("path_bindings",{}).get("input_observation",{}).get("sha256"),"M2d/input observation lineage mismatch")
    require(m2d.get("result_observation_source",{}).get("sha256")==result_file_sha,"M2d/result file mismatch")
    require(m2d.get("scope",{}).get("scope_kind")=="reviewer_bound_real_case" and set(m2d.get("decision_summary",{}).get("accepted_sections",[]))=={"wavefunction","coordination","mode","input_acceptance"},"real four-section accepted M2d required")
    ident=result["identity_binding"]
    for key in ("charge","multiplicity","atom_count","atom_order"): require(ident[key]==approval["identity"][key],f"result {key} differs from approved identity")
    term=result["termination_observations"]; require(term["normal_termination_count"]>=1 and term["error_termination_count"]==0 and term["optimization_completed_observed"] and term["stationary_point_observed"],"terminal/stationary evidence failed")
    freq=result["frequency_observations"]; n=ident["atom_count"]; expected=3*n-(5 if r.get("linearity_review")=="linear" else 6)
    require(r.get("linearity_review") in {"linear","nonlinear"},"explicit linearity review required")
    require(freq["frequency_count"]==len(freq["frequencies_cm_1"])==expected,"frequency count is incomplete for reviewed atom count/linearity")
    require(freq["raw_imaginary_frequency_count"]==1 and sum(x<0 for x in freq["frequencies_cm_1"])==1,"exactly one raw imaginary frequency required")
    wave=m2d["sections"]["wavefunction"]["facts"]; require(wave["stability_statement_observed"] is True and wave["observed_s2_count"]==len(result["wavefunction_observations"]["s2_observations"]),"wavefunction stability/S**2 evidence mismatch")
    coord=m2d["sections"]["coordination"]["facts"]; require(coord["contact_assessments"] and all(x["within_reviewed_window"] for x in coord["contact_assessments"]),"non-empty passed coordination contacts required")
    require(coord["ligand_inventory_assessment"].strip() and coord["hapticity_assessment"].strip() and coord["unintended_state_change"] is False,"ligand/hapticity retention review failed")
    mode=m2d["sections"]["mode"]["facts"]; require(re.fullmatch(r"[0-9a-f]{64}",mode["mode_evidence_sha256"]) and mode["mode_evidence_sha256"]==file_digest(ps["mode_evidence"]),"mode evidence file SHA-256 mismatch")
    require(mode["raw_imaginary_frequency_count"]==1 and mode["intended_coordinate_assessment"].strip() and mode["unintended_coordination_loss_assessment"].strip(),"mode assessment incomplete")
    require(r.get("decision")=="accepted_for_explicit_promotion_review" and r.get("confirmed") is True,"explicit result acceptance required")
    input_facts=m2d["sections"]["input_acceptance"]["facts"]
    require(input_facts.get("input_sha256")==approval["input_sha256"] and input_facts.get("protocol_options_sha256")==approval["protocol_options_sha256"] and input_facts.get("protocol_selection_sha256")==approval["protocol_selection_sha256"],"M2d input acceptance lineage mismatch")
    lineage=digest({"input_approval_file_sha256":approval_file_sha,"result_observation_file_sha256":result_file_sha})
    require(input_facts.get("input_approval_sha256")==approval_file_sha and input_facts.get("input_result_lineage_sha256")==lineage,"M2d approval/result lineage digest mismatch")
    out={"schema":"auto-g16-metal-ts-result-acceptance/1","input_approval_sha256":approval_file_sha,"input_result_lineage_sha256":lineage,"candidate_sha256":approval["candidate_sha256"],"result_observation_sha256":result["audit_payload_sha256"],"m2d_acceptance_sha256":m2d["review_payload_sha256"],"source_file_bindings":{name:{"sha256":file_digest(path)} for name,path in ps.items()},"wavefunction_acceptance":copy.deepcopy(m2d["sections"]["wavefunction"]),"coordination_acceptance":copy.deepcopy(m2d["sections"]["coordination"]),"mode_evidence":copy.deepcopy(m2d["sections"]["mode"]),"decision":"accepted_for_explicit_promotion_review","promotion_decision":"not_yet_made","authorizations":copy.deepcopy(DENIALS),"submission_decision":"refused"}
    out["acceptance_payload_sha256"]=payload_hash(out,"acceptance_payload_sha256"); _validate_local_schema(out,"result-acceptance.schema.json"); return out

def decide_promotion(r: dict[str, Any]) -> dict[str, Any]:
    a=r["result_acceptance"]; verify(a,"acceptance_payload_sha256","result acceptance")
    require(a.get("decision")=="accepted_for_explicit_promotion_review", "unaccepted result cannot be promoted")
    require(r.get("decision") in {"promoted_for_offline_downstream_review","rejected","blocked"} and r.get("confirmed") is True and r.get("reviewer") and r.get("rationale"), "explicit promotion decision incomplete")
    out={"schema":"auto-g16-metal-ts-promotion-decision/1","result_acceptance_sha256":a["acceptance_payload_sha256"],"candidate_sha256":a["candidate_sha256"],"decision":r["decision"],"reviewer":r["reviewer"],"rationale":r["rationale"],"claim_ceiling":"offline_metal_ts_candidate_only_no_path_or_selectivity_claim","authorizations":DENIALS,"submission_decision":"refused"}
    out["promotion_payload_sha256"]=payload_hash(out,"promotion_payload_sha256"); return out

def decide_promotion_paths(r: dict[str, Any]) -> dict[str, Any]:
    path=Path(r["result_acceptance_path"]); require(path.is_file() and not path.is_symlink(),"result acceptance path must be a regular non-symlink file")
    acceptance=load(path); verify(acceptance,"acceptance_payload_sha256","result acceptance")
    out=decide_promotion({"result_acceptance":acceptance,"decision":r["decision"],"confirmed":r["confirmed"],"reviewer":r["reviewer"],"rationale":r["rationale"]})
    out["result_acceptance_file_sha256"]=file_digest(path); out["promotion_payload_sha256"]=payload_hash(out,"promotion_payload_sha256"); return out

def main() -> int:
    p=argparse.ArgumentParser(); sub=p.add_subparsers(dest="cmd",required=True)
    for name in ("approve-input-paths","accept-result-paths","decide-promotion-paths"):
        q=sub.add_parser(name); q.add_argument("request"); q.add_argument("--output",required=True)
    args=p.parse_args(); r=load(args.request); fn={"approve-input-paths":approve_input_paths,"accept-result-paths":accept_result_paths,"decide-promotion-paths":decide_promotion_paths}[args.cmd]
    try: write(Path(args.output),fn(r)); return 0
    except (ContractError,KeyError,TypeError,ValueError) as e: print(f"refused: {e}"); return 2
if __name__=="__main__": raise SystemExit(main())
