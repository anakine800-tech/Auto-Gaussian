#!/usr/bin/env python3
"""Deterministic offline-only transition-metal TS P2-P4 contracts."""
from __future__ import annotations

import argparse, hashlib, json, math
from pathlib import Path
from typing import Any

class ContractError(ValueError): pass

def require(ok: bool, message: str) -> None:
    if not ok: raise ContractError(message)

def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()

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
    coverage=r["basis_ecp_review"]; elements=set(ident["atom_order"])
    require(set(coverage.get("basis_by_element",{}))==elements, "basis coverage incomplete")
    for el in coverage.get("ecp_elements",[]):
        e=coverage.get("ecp_by_element",{}).get(el,{}); require(e.get("name") and isinstance(e.get("core_electrons"),int) and e.get("evidence_id"), "ECP coverage incomplete")
    require(r.get("decision")=="approved_for_offline_result_intake" and r.get("confirmed") is True, "explicit input approval required")
    out={"schema":"auto-g16-metal-ts-input-approval/1","candidate_sha256":c["candidate_payload_sha256"],"m1_review_sha256":m["review_payload_sha256"],"protocol_options_sha256":o["options_payload_sha256"],"protocol_selection_sha256":s["selection_payload_sha256"],"input_observation_sha256":i["audit_payload_sha256"],"input_sha256":i["observed"]["input_sha256"],"identity":ident,"wavefunction":r["wavefunction_review"],"basis_ecp_review":coverage,"seed_strategy":seed,"decision":"approved_for_offline_result_intake","authorizations":DENIALS,"submission_decision":"refused"}
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
    out["acceptance_payload_sha256"]=payload_hash(out,"acceptance_payload_sha256"); return out

def decide_promotion(r: dict[str, Any]) -> dict[str, Any]:
    a=r["result_acceptance"]; verify(a,"acceptance_payload_sha256","result acceptance")
    require(a.get("decision")=="accepted_for_explicit_promotion_review", "unaccepted result cannot be promoted")
    require(r.get("decision") in {"promoted_for_offline_downstream_review","rejected","blocked"} and r.get("confirmed") is True and r.get("reviewer") and r.get("rationale"), "explicit promotion decision incomplete")
    out={"schema":"auto-g16-metal-ts-promotion-decision/1","result_acceptance_sha256":a["acceptance_payload_sha256"],"candidate_sha256":a["candidate_sha256"],"decision":r["decision"],"reviewer":r["reviewer"],"rationale":r["rationale"],"claim_ceiling":"offline_metal_ts_candidate_only_no_path_or_selectivity_claim","authorizations":DENIALS,"submission_decision":"refused"}
    out["promotion_payload_sha256"]=payload_hash(out,"promotion_payload_sha256"); return out

def main() -> int:
    p=argparse.ArgumentParser(); sub=p.add_subparsers(dest="cmd",required=True)
    for name in ("approve-input","accept-result","decide-promotion"):
        q=sub.add_parser(name); q.add_argument("request"); q.add_argument("--output",required=True)
    args=p.parse_args(); r=load(args.request); fn={"approve-input":approve_input,"accept-result":accept_result,"decide-promotion":decide_promotion}[args.cmd]
    try: write(Path(args.output),fn(r)); return 0
    except (ContractError,KeyError,TypeError,ValueError) as e: print(f"refused: {e}"); return 2
if __name__=="__main__": raise SystemExit(main())
