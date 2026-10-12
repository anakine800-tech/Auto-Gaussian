import {useEffect, useState} from 'react';
import {requestJSON} from './contract';

type Identity = {id:string; payload_sha256:string};
type Revision = Identity & {revision:number};
type Raw = {electronic_energy_hartree:number; zero_point_energy_hartree:number; enthalpy_hartree:number; entropy_hartree_per_kelvin:number; gibbs_free_energy_hartree:number};
type Treated = Pick<Raw,'enthalpy_hartree'|'entropy_hartree_per_kelvin'|'gibbs_free_energy_hartree'> & {entropy_treatment:'grimme'; enthalpy_treatment:'head_gordon'};
type Parameters = {
 temperature_k:number; standard_state:'1atm'|'1M'; entropy_method:'grimme'; enthalpy_method:'head_gordon';
 entropy_frequency_cutoff_cm1:number; enthalpy_frequency_cutoff_cm1:number; frequency_scaling_factor:number;
 zpe_scaling_factor:number; moment_of_inertia:'global_grimme_bav'; degeneracy_excludes_rotational_symmetry:true;
 functional_kernel_implementation_id:string;
};
type Member = {
 member_id:string; is_selected:boolean; degeneracy:number; degeneracy_rationale:string;
 inclusion_status:'included_thermodynamic_eligible'; raw_rrho:Raw; treated_qrrho:Treated; normalized_population:number;
 source:{optimization_attempt_id:string; frequency_attempt_id:string;
  optimization_parsed_result:{result_id:string;payload_sha256:string}; frequency_parsed_result:{result_id:string;payload_sha256:string};
  optimization_result_source:{observation_id:string;payload_sha256:string}; frequency_result_source:{observation_id:string;payload_sha256:string};
  two_stage_minimum_authority_id:string};
};
type Result = {
 artifact_sha256:string; source_ensemble:Revision; qualified_ensemble:Revision; thermodynamic_ensemble:Identity;
 sampling_profile:Identity; request:Identity; parameters:Parameters; members:Member[];
 ensemble_treated_free_energy_hartree:number;
 population_normalization:{population_sum:number;absolute_error:number;numeric_tolerance:number;status:'normalized';tolerance_purpose:'floating_point_normalization_only_not_scientific_selection'};
 coverage_scope:{kind:'frozen_profile_nonexhaustive_scope';rationale:string}; scientific_acceptance:'unavailable';
};
type Data = {source_id:string;attempt_id:string} & (
 {availability:'available';reason:null;selected_member_id:string;result:Result} |
 {availability:'unavailable';reason:'not-registered';selected_member_id:null;result:null});

function requireContract(condition:unknown):asserts condition {if(!condition)throw Error('contract-mismatch');}
function closed(value:unknown, keys:string[]):Record<string,unknown> {
 requireContract(value!==null&&typeof value==='object'&&!Array.isArray(value));
 const row=value as Record<string,unknown>;
 requireContract(Object.keys(row).length===keys.length&&keys.every(k=>Object.hasOwn(row,k)));
 return row;
}
const id=(v:unknown)=>typeof v==='string'&&/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}$/.test(v);
const digest=(v:unknown)=>typeof v==='string'&&/^[a-f0-9]{64}$/.test(v);
const finite=(v:unknown):v is number=>typeof v==='number'&&Number.isFinite(v);
const positive=(v:unknown)=>finite(v)&&v>0;
const integer=(v:unknown)=>Number.isSafeInteger(v)&&Number(v)>0;
const text=(v:unknown)=>typeof v==='string'&&v.length>0&&v===v.trim();
const rawKeys=['electronic_energy_hartree','zero_point_energy_hartree','enthalpy_hartree','entropy_hartree_per_kelvin','gibbs_free_energy_hartree'];
const treatedNumbers=['enthalpy_hartree','entropy_hartree_per_kelvin','gibbs_free_energy_hartree'];
function identity(value:unknown, key='id', revision=false){
 const row=closed(value,[key,'payload_sha256',...(revision?['revision']:[])]);
 requireContract(id(row[key])&&digest(row.payload_sha256)&&(!revision||integer(row.revision)));
}
/** Validate the public projection only. Never derive energies or re-normalize populations. */
export function decodeThermodynamics(value:unknown, sourceId:string, attemptId:string):Data {
 const envelope=closed(value,['schema','kind','data']);
 requireContract(envelope.schema==='auto-g16-native-thermodynamics-query/1'&&envelope.kind==='thermodynamics');
 const data=closed(envelope.data,['availability','reason','source_id','attempt_id','selected_member_id','result']);
 requireContract(id(data.source_id)&&id(data.attempt_id)&&data.source_id===sourceId&&data.attempt_id===attemptId);
 if(data.availability==='unavailable'){
  requireContract(data.reason==='not-registered'&&data.selected_member_id===null&&data.result===null);
  return data as Data;
 }
 requireContract(data.availability==='available'&&data.reason===null&&id(data.selected_member_id));
 const r=closed(data.result,['artifact_sha256','source_ensemble','qualified_ensemble','thermodynamic_ensemble','sampling_profile','request','parameters','members','ensemble_treated_free_energy_hartree','population_normalization','coverage_scope','scientific_acceptance']);
 requireContract(digest(r.artifact_sha256)&&r.scientific_acceptance==='unavailable'&&finite(r.ensemble_treated_free_energy_hartree));
 identity(r.source_ensemble,'id',true);identity(r.qualified_ensemble,'id',true);
 for(const key of ['thermodynamic_ensemble','sampling_profile','request'])identity(r[key]);
 const p=closed(r.parameters,['temperature_k','standard_state','entropy_method','enthalpy_method','entropy_frequency_cutoff_cm1','enthalpy_frequency_cutoff_cm1','frequency_scaling_factor','zpe_scaling_factor','moment_of_inertia','degeneracy_excludes_rotational_symmetry','functional_kernel_implementation_id']);
 for(const key of ['temperature_k','entropy_frequency_cutoff_cm1','enthalpy_frequency_cutoff_cm1','frequency_scaling_factor','zpe_scaling_factor'])requireContract(positive(p[key]));
 requireContract((p.standard_state==='1atm'||p.standard_state==='1M')&&p.entropy_method==='grimme'&&p.enthalpy_method==='head_gordon'&&p.moment_of_inertia==='global_grimme_bav'&&p.degeneracy_excludes_rotational_symmetry===true&&id(p.functional_kernel_implementation_id));
 const norm=closed(r.population_normalization,['population_sum','absolute_error','numeric_tolerance','status','tolerance_purpose']);
 requireContract(positive(norm.population_sum)&&finite(norm.absolute_error)&&norm.absolute_error>=0&&norm.absolute_error<=1e-12&&norm.numeric_tolerance===1e-12&&norm.status==='normalized'&&norm.tolerance_purpose==='floating_point_normalization_only_not_scientific_selection');
 const scope=closed(r.coverage_scope,['kind','rationale']);
 requireContract(scope.kind==='frozen_profile_nonexhaustive_scope'&&text(scope.rationale));
 requireContract(Array.isArray(r.members)&&r.members.length===2);
 const memberIds=new Set(), optAttempts=new Set(), freqAttempts=new Set();
 let selected=0;
 for(const member of r.members){
  const m=closed(member,['member_id','is_selected','degeneracy','degeneracy_rationale','inclusion_status','raw_rrho','treated_qrrho','normalized_population','source']);
  requireContract(id(m.member_id)&&!memberIds.has(m.member_id)&&typeof m.is_selected==='boolean'&&m.is_selected===(m.member_id===data.selected_member_id));
  memberIds.add(m.member_id);
  requireContract(integer(m.degeneracy)&&text(m.degeneracy_rationale)&&m.inclusion_status==='included_thermodynamic_eligible'&&finite(m.normalized_population)&&m.normalized_population>=0&&m.normalized_population<=1);
  const raw=closed(m.raw_rrho,rawKeys);
  requireContract(rawKeys.every(k=>finite(raw[k])));
  const treated=closed(m.treated_qrrho,[...treatedNumbers,'entropy_treatment','enthalpy_treatment']);
  requireContract(treatedNumbers.every(k=>finite(treated[k]))&&treated.entropy_treatment==='grimme'&&treated.enthalpy_treatment==='head_gordon');
  const s=closed(m.source,['optimization_attempt_id','frequency_attempt_id','optimization_parsed_result','frequency_parsed_result','optimization_result_source','frequency_result_source','two_stage_minimum_authority_id']);
  requireContract(id(s.optimization_attempt_id)&&id(s.frequency_attempt_id)&&id(s.two_stage_minimum_authority_id)&&s.optimization_attempt_id!==s.frequency_attempt_id&&!optAttempts.has(s.optimization_attempt_id)&&!freqAttempts.has(s.frequency_attempt_id));
  optAttempts.add(s.optimization_attempt_id);freqAttempts.add(s.frequency_attempt_id);
  for(const key of ['optimization_parsed_result','frequency_parsed_result'])identity(s[key],'result_id');
  for(const key of ['optimization_result_source','frequency_result_source'])identity(s[key],'observation_id');
  if(m.is_selected){selected++;requireContract(s.frequency_attempt_id===attemptId);}
 }
 requireContract(selected===1);
 return data as Data;
}

const rawLabels:Record<keyof Raw,string>={electronic_energy_hartree:'电子能',zero_point_energy_hartree:'零点能',enthalpy_hartree:'焓 H',entropy_hartree_per_kelvin:'熵 S',gibbs_free_energy_hartree:'自由能 G'};
function SavedResult({data}:{data:Extract<Data,{availability:'available'}>}){
 const r=data.result,p=r.parameters;
 return <>
  <p>当前成员：<strong>{data.selected_member_id}</strong> · 集合 treated G：<strong>{String(r.ensemble_treated_free_energy_hartree)}</strong> Hartree</p>
  <p>仅反映冻结采样范围内已保存的结果，不表示穷尽采样或全局最低。科学验收：{r.scientific_acceptance}。</p>
  <p>采样范围：{r.coverage_scope.kind} · {r.coverage_scope.rationale}</p>
  <div className="native-saved-members">{r.members.map(m=><article key={m.member_id}>
   <h3>{m.member_id}{m.is_selected?' · 当前成员':''}</h3>
   <p>treated G：{String(m.treated_qrrho.gibbs_free_energy_hartree)} Hartree · 布居：{String(m.normalized_population)}（无量纲）</p>
   <p>简并度：{m.degeneracy} · {m.degeneracy_rationale} · {m.inclusion_status}</p>
   <table><caption>已保存成员值 · raw RRHO / treated qRRHO</caption><thead><tr><th scope="col">报告项</th><th scope="col">raw RRHO</th><th scope="col">treated qRRHO</th><th scope="col">单位</th></tr></thead><tbody>
    {(Object.keys(rawLabels) as (keyof Raw)[]).map(key=><tr key={key}><th scope="row">{rawLabels[key]}</th><td>{String(m.raw_rrho[key])}</td><td>{Object.hasOwn(m.treated_qrrho,key)?String(m.treated_qrrho[key as keyof Treated]):'不适用'}</td><td>{key==='entropy_hartree_per_kelvin'?'Hartree/K':'Hartree'}</td></tr>)}
   </tbody></table>
   <p>熵处理：{m.treated_qrrho.entropy_treatment} · 焓处理：{m.treated_qrrho.enthalpy_treatment}</p>
   <details><summary>成员来源身份</summary><pre>{JSON.stringify(m.source,null,2)}</pre></details>
  </article>)}</div>
  <h3>已保存参数</h3><dl className="native-saved-parameters">
   <dt>温度</dt><dd>{String(p.temperature_k)} K</dd><dt>标准态</dt><dd>{p.standard_state}</dd>
   <dt>熵 / 焓处理</dt><dd>{p.entropy_method} / {p.enthalpy_method}</dd>
   <dt>熵频率截断</dt><dd>{String(p.entropy_frequency_cutoff_cm1)} cm⁻¹</dd><dt>焓频率截断</dt><dd>{String(p.enthalpy_frequency_cutoff_cm1)} cm⁻¹</dd>
   <dt>频率 / 零点能缩放因子</dt><dd>{String(p.frequency_scaling_factor)} / {String(p.zpe_scaling_factor)}</dd>
   <dt>转动惯量约定</dt><dd>{p.moment_of_inertia}</dd><dt>简并度排除转动对称性</dt><dd>{String(p.degeneracy_excludes_rotational_symmetry)}</dd>
   <dt>计算内核身份</dt><dd>{p.functional_kernel_implementation_id}</dd>
  </dl>
  <p>已保存布居和：{String(r.population_normalization.population_sum)} · 绝对误差：{String(r.population_normalization.absolute_error)} · 数值容差：{String(r.population_normalization.numeric_tolerance)} · {r.population_normalization.status}。容差仅用于浮点归一化，不作为科学筛选条件。</p>
  <details><summary>集合与请求身份</summary><pre>{JSON.stringify({artifact_sha256:r.artifact_sha256,source_ensemble:r.source_ensemble,qualified_ensemble:r.qualified_ensemble,thermodynamic_ensemble:r.thermodynamic_ensemble,sampling_profile:r.sampling_profile,request:r.request},null,2)}</pre></details>
 </>;
}
export function NativeThermodynamics({sourceId,attemptId,token,onArtifact}:{sourceId:string;attemptId:string;token:string;onArtifact?:(hash:string|null)=>void}){
 const key=JSON.stringify([sourceId,attemptId,token]);
 const [state,setState]=useState<{key:string;data:Data|null;error:string}>({key,data:null,error:''});
 useEffect(()=>{
  const controller=new AbortController();setState({key,data:null,error:''});
  requestJSON(`/api/v1/native/sources/${encodeURIComponent(sourceId)}/attempts/${encodeURIComponent(attemptId)}/thermodynamics`,token,controller.signal,'native-scientific-read')
   .then(value=>{if(!controller.signal.aborted)setState({key,data:decodeThermodynamics(value,sourceId,attemptId),error:''});})
   .catch(error=>{if(!controller.signal.aborted)setState({key,data:null,error:error instanceof Error?error.message:'request-failed'});});
  return()=>controller.abort();
 },[sourceId,attemptId,token,key]);
 const {data,error}=state.key===key?state:{data:null,error:''};
 useEffect(()=>{onArtifact?.(data?.availability==='available'?data.result.artifact_sha256:null);},[data,onArtifact]);
 return <section className="native-saved-thermodynamics" aria-label="已保存的集合热化学结果"><h2>已保存的集合热化学结果</h2>
  {error?<p role="alert">读取失败：{error}</p>:!data?<p role="status">正在读取已保存的热化学结果…</p>:data.availability==='unavailable'?<p>未登记（unavailable · not-registered）</p>:<SavedResult data={data}/>}
 </section>;
}
