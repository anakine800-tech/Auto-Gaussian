/** Public saved projections only: validation never derives scientific values. */
function check(v:unknown):asserts v {if(!v)throw Error('contract-mismatch');}
function obj(v:unknown,keys:string[]):Record<string,any>{check(v!==null&&typeof v==='object'&&!Array.isArray(v));const r=v as Record<string,any>;check(Object.keys(r).length===keys.length&&keys.every(k=>Object.hasOwn(r,k)));return r;}
const id=(v:unknown)=>typeof v==='string'&&/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}$/.test(v);
const hash=(v:unknown)=>typeof v==='string'&&/^[a-f0-9]{64}$/.test(v);
const num=(v:unknown):v is number=>typeof v==='number'&&Number.isFinite(v);
const pos=(v:unknown)=>num(v)&&v>0;
const integer=(v:unknown)=>Number.isSafeInteger(v)&&Number(v)>0;
const text=(v:unknown)=>typeof v==='string'&&v.length>0&&v===v.trim();
function timestamp(v:unknown){if(typeof v!=='string'||!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$/.test(v)||v.startsWith('0000'))return false;const t=Date.parse(v);return Number.isFinite(t)&&new Date(t).toISOString().slice(0,23)===v.slice(0,23);}
function ref(v:unknown,key='id'){const r=obj(v,[key,'payload_sha256']);check(id(r[key])&&hash(r.payload_sha256));}
function envelope(v:unknown,kind:string,source:string,attempt:string,extra:string[]=[]){const e=obj(v,['schema','kind','data']);check(e.schema===`auto-g16-native-${kind}-query/1`&&e.kind===kind);const d=obj(e.data,['source_id','attempt_id','availability','reason','result',...extra]);check(id(d.source_id)&&id(d.attempt_id)&&d.source_id===source&&d.attempt_id===attempt);return d;}
const common=['availability','reason','observed_at','evidence_refs'];
function axis(v:unknown,keys:string[]){const a=obj(v,[...common,...keys]);check(['available','missing','unavailable'].includes(a.availability)&&a.observed_at===null&&Array.isArray(a.evidence_refs)&&a.evidence_refs.every(id)&&new Set(a.evidence_refs).size===a.evidence_refs.length);return a;}
function triple(a:Record<string,any>,state:string,availability:string,reason:string){check(a.state===state&&a.availability===availability&&a.reason===reason);}
export function decodeLifecycle(v:unknown,source:string,attempt:string){
 const d=envelope(v,'lifecycle',source,attempt);
 if(d.availability==='unavailable'){check(['not-registered','backend-unavailable','lifecycle-job-not-established'].includes(d.reason)&&d.result===null);return d;}
 check(d.availability==='available'&&d.reason===null);
 const r=obj(d.result,['schema','attempt_id','snapshot_id','core_state','job_id','projection_as_of_observation_id','program','scheduler','collection']);
 check(r.schema==='auto-g16-program-lifecycle/1'&&r.attempt_id===attempt&&id(r.snapshot_id)&&id(r.job_id)&&(r.projection_as_of_observation_id===null||id(r.projection_as_of_observation_id))&&['PLANNED','SUBMISSION_INTENT_RECORDED','SUBMITTED','UNKNOWN','RUNNING','SUCCEEDED','FAILED','NOT_SUBMITTED'].includes(r.core_state));
 const p=axis(r.program,['state','completed_at','exit_code','signal']);
 if(p.availability==='missing'){triple(p,'unknown','missing','program-completion-not-captured');check(p.completed_at===null&&p.exit_code===null&&p.signal===null&&p.evidence_refs.length===0);}
 else {check(p.availability==='available'&&p.reason==='observation-time-not-recorded'&&timestamp(p.completed_at)&&p.evidence_refs.length===3);check((Number.isSafeInteger(p.exit_code)&&p.exit_code>=0&&p.exit_code<=255&&p.signal===null)||(p.exit_code===null&&integer(p.signal)&&p.signal<=64));check(p.state===(p.exit_code===0?'completed':'failed'));}
 const s=axis(r.scheduler,['state','presence','raw_state','raw_state_reason']);
 check(s.raw_state===null&&s.raw_state_reason==='raw-pbs-state-not-retained');
 if(s.availability==='missing'){check(s.state===null&&s.reason==='scheduler-not-observed'&&s.presence==='unknown'&&s.evidence_refs.length===0);}
 else if(s.availability==='unavailable'){triple(s,'unknown','unavailable','scheduler-read-unknown');check(s.presence==='unknown'&&s.evidence_refs.length>0);}
 else {check(['queued','running','held','exiting','terminal','absent'].includes(s.state)&&s.reason==='observation-time-not-recorded'&&s.presence===(s.state==='absent'?'absent':'present')&&s.evidence_refs.length>0);}
 const c=axis(r.collection,['state','condition','result_id']);
 const combos:Record<string,string[]>= {none:['collected','available','observation-time-not-recorded'],awaiting_scheduler_absence:['pending','available','observation-time-not-recorded'],reconciliation_required:['unknown','unavailable','collection-acquisition-unknown'],evidence_incomplete:['pending','available','collection-evidence-incomplete'],not_recorded:['pending','missing','collection-not-recorded']};
 check(Object.hasOwn(combos,c.condition));const [state,availability,reason]=combos[c.condition];triple(c,state,availability,reason);
 check(c.condition==='not_recorded'?c.evidence_refs.length===0:c.evidence_refs.length>0);
 check(c.state==='collected'?id(c.result_id)&&p.availability==='available'&&JSON.stringify(c.evidence_refs)===JSON.stringify([...p.evidence_refs,c.result_id]):c.result_id===null);
 return d;
}
export function decodePopulations(v:unknown,source:string,attempt:string){
 const d=envelope(v,'populations',source,attempt,['selected_member_id']);
 if(d.availability==='unavailable'){check(['not-registered','backend-unavailable'].includes(d.reason)&&d.result===null&&d.selected_member_id===null);return d;}
 check(d.availability==='available'&&d.reason===null&&id(d.selected_member_id));
 const r=obj(d.result,['artifact_id','payload_sha256','artifact_sha256','source_pair_sha256','qualified_ensemble','thermodynamic_ensemble','reference_member_id','parameters','members','normalization','coverage_scope','scientific_acceptance']);
 check(id(r.artifact_id)&&hash(r.payload_sha256)&&hash(r.artifact_sha256)&&hash(r.source_pair_sha256)&&id(r.reference_member_id)&&r.scientific_acceptance==='unavailable');ref(r.qualified_ensemble);ref(r.thermodynamic_ensemble);
 const p=obj(r.parameters,['temperature_k','standard_state','gas_constant_binding','hartree_to_kcal_per_mol','thermochemistry_policy_id','thermochemistry_policy_payload_sha256','functional_kernel_implementation_id','population_implementation_id','degeneracy_excludes_rotational_symmetry']);
 check(pos(p.temperature_k)&&['1atm','1M'].includes(p.standard_state)&&pos(p.hartree_to_kcal_per_mol)&&id(p.thermochemistry_policy_id)&&hash(p.thermochemistry_policy_payload_sha256)&&id(p.functional_kernel_implementation_id)&&p.population_implementation_id==='auto-g16-native-dual-population/1'&&p.degeneracy_excludes_rotational_symmetry===true);
 const gas=obj(p.gas_constant_binding,['gas_constant_j_per_mol_k','joule_per_hartree_mol','gas_constant_hartree_per_mol_k','unit_convention']);check(pos(gas.gas_constant_j_per_mol_k)&&pos(gas.joule_per_hartree_mol)&&pos(gas.gas_constant_hartree_per_mol_k)&&gas.unit_convention==='per_mole_hartree_kelvin');
 const scope=obj(r.coverage_scope,['kind','rationale']);check(scope.kind==='frozen_profile_nonexhaustive_scope'&&text(scope.rationale));
 const norm=obj(r.normalization,['rrho','qrrho']);for(const scheme of ['rrho','qrrho']){const n=obj(norm[scheme],['population_sum','absolute_error','numeric_tolerance']);check(pos(n.population_sum)&&num(n.absolute_error)&&n.absolute_error>=0&&n.absolute_error<=1e-12&&n.numeric_tolerance===1e-12);}
 check(Array.isArray(r.members)&&r.members.length===2);const ids=new Set(),attempts=new Set();let selected=0;
 for(const value of r.members){
  const m=obj(value,['member_id','is_selected','degeneracy','degeneracy_rationale','symmetry_rationale','reported_rotational_symmetry_number','rrho','qrrho','source']);
  check(id(m.member_id)&&!ids.has(m.member_id)&&typeof m.is_selected==='boolean'&&m.is_selected===(m.member_id===d.selected_member_id)&&integer(m.degeneracy)&&text(m.degeneracy_rationale)&&text(m.symmetry_rationale)&&integer(m.reported_rotational_symmetry_number));ids.add(m.member_id);
  for(const scheme of ['rrho','qrrho']){const row=obj(m[scheme],['gibbs_free_energy_hartree','delta_g_hartree','delta_g_kcal_per_mol','log_relative_weight','normalized_population']);check(Object.values(row).every(num)&&row.normalized_population>=0&&row.normalized_population<=1);}
  const s=obj(m.source,['optimization_attempt_id','frequency_attempt_id','two_stage_minimum_authority_id','optimization_parsed_result','optimization_result_source','frequency_parsed_result','frequency_result_source']);check(id(s.two_stage_minimum_authority_id));
  for(const k of ['optimization_attempt_id','frequency_attempt_id']){check(id(s[k])&&!attempts.has(s[k]));attempts.add(s[k]);}
  for(const k of ['optimization_parsed_result','frequency_parsed_result'])ref(s[k],'result_id');for(const k of ['optimization_result_source','frequency_result_source'])ref(s[k],'observation_id');
  if(m.is_selected){selected++;check(s.frequency_attempt_id===attempt);}
 }
 check(selected===1&&ids.has(r.reference_member_id));return d;
}
