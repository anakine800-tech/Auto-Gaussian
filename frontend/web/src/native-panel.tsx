import {useEffect, useState} from 'react';
import {requestJSON} from './contract';
import type {Field} from './contract';
import './native.css';
import {NativeReliability} from './native-reliability';
type Fact = Field & {unit: string|null};
type NativeAttempt = {source_id:string; project_id:string; workflow_run_id:string; task_id:string; attempt_id:string; generation:Fact; program:Fact; bound_plan:Fact; input:Fact; artifacts:Fact; axes:Record<string,Fact>; facts:Record<string,Fact>; availability:string; reason:string|null; record_inventory:unknown[]; provenance:unknown; history:unknown[]};
type Project = {source_id:string; project_id:string; workflow_run_ids:string[]; identity_collision:boolean};
type Projects = {items:Project[];sources:{source_id:string;availability:string;reason:string|null}[]};
function decode(value:unknown,kind:string):unknown{
  if(!value || typeof value!=='object')throw Error('contract-mismatch');
  const v=value as {schema?:string;kind?:string;data?:unknown};
  if(v.schema!=='auto-g16-native-query/1'||v.kind!==kind||!v.data||typeof v.data!=='object')throw Error('contract-mismatch');
  return v.data;
}
const names:Record<string,string>={execution:'执行状态',capture:'捕获',result:'Result 记录',validation:'科学验证',review:'人工审阅',energy:'能量',geometry:'已归属结构块',frequencies:'已归属频率块',optimization:'优化标记',sampling:'采样事实'};
function Value({fact}:{fact:Fact}){return <div className="native-fact"><strong>{fact.availability==='available'?(typeof fact.value==='object'?JSON.stringify(fact.value):String(fact.value)):fact.availability==='missing'?'缺失 (missing)':'不可用 (unavailable)'}</strong>{fact.unit&&<span> · {fact.unit}</span>}<small>{fact.reason??fact.source}</small></div>}
function FrequencySummary({item}:{item:NativeAttempt}) {
 const provenance=item.provenance as {parsed_result?:Record<string,unknown>}|null;
 const p=provenance?.parsed_result;
 if(!p||p.frequency_unit!=='cm^-1')return null;
 const count=(key:string)=>p[key]===null?'未知 / unavailable':String(p[key]);
 return <div className="native-frequency-summary"><h3>Opt → Freq</h3><p>频率单位：cm^-1 · 模式数：{count('frequency_count')} · 负频：{count('imaginary_frequency_count')} · 零频：{count('zero_frequency_count')}</p><p>Opt Attempt：{String(p.optimization_attempt_id)} → Freq Attempt：{String(p.frequency_attempt_id)}</p><p>解析版本：{String(p.parser_version)}。两阶段机器证据不代表人工科学验收或热力学验收。</p></div>;
}
const thermalLabels = {
 zero_point_correction_hartree:'零点能校正', thermal_correction_energy_hartree:'热能校正',
 thermal_correction_enthalpy_hartree:'热焓校正', thermal_correction_gibbs_hartree:'热自由能校正',
 sum_electronic_zpe_hartree:'电子能与零点能之和', sum_electronic_enthalpy_hartree:'电子能与热焓校正之和',
 sum_electronic_gibbs_hartree:'电子能与热自由能校正之和',
};
type ThermalItem = {value_hartree:number; source_span:Record<string,unknown>};
function record(value:unknown):value is Record<string,unknown>{return !!value && typeof value==='object' && !Array.isArray(value)}
function exactKeys(value:Record<string,unknown>,keys:string[]){return Object.keys(value).length===keys.length&&keys.every(k=>Object.hasOwn(value,k))}
function thermalReport(item:NativeAttempt):Record<string,ThermalItem>|null {
 const f=item.facts.thermochemistry;
 if(!record(f)||!exactKeys(f,['availability','reason','source','value','unit'])||f.unit!=='hartree')throw Error('invalid');
 if(f.availability==='missing'||f.availability==='unavailable'){
  if(f.value!==null||f.source!==null||f.reason!==(f.availability==='missing'?'thermochemistry-not-recorded':'thermochemistry-unavailable'))throw Error('invalid');
  return null;
 }
 const provenance=record(item.provenance)?item.provenance.parsed_result:null;
 const p=record(provenance)?provenance:null;
 const log=p&&record(p.log)?p.log:null;
 const id=(v:unknown)=>typeof v==='string'&&/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}$/.test(v);
 if(f.availability!=='available'||f.reason!==null||!record(f.value)||!Object.keys(f.value).length||
    !p||!id(p.parsed_result_id)||p.parser_version!=='1.2.0'||f.source!==`Result:${p.parsed_result_id}`||
    !log||log.portable_name!=='gaussian.log'||typeof log.sha256!=='string'||!/^[a-f0-9]{64}$/.test(log.sha256)||
    !Number.isSafeInteger(log.size_bytes)||Number(log.size_bytes)<=0)throw Error('invalid');
 let envelope:unknown;
 for(const [key,value] of Object.entries(f.value)){
  if(!Object.hasOwn(thermalLabels,key)||!record(value)||!exactKeys(value,['value_hartree','source_span'])||
     typeof value.value_hartree!=='number'||!Number.isFinite(value.value_hartree)||!record(value.source_span))throw Error('invalid');
  const span=value.source_span;
  if(!exactKeys(span,['artifact_kind','envelope_observation_id','logical_name','sha256','size_bytes','start','end'])||
     span.artifact_kind!=='gaussian-log'||!id(span.envelope_observation_id)||span.logical_name!==log.portable_name||
     span.sha256!==log.sha256||span.size_bytes!==log.size_bytes||!Number.isSafeInteger(span.start)||!Number.isSafeInteger(span.end)||
     Number(span.start)<0||Number(span.start)>=Number(span.end)||Number(span.end)>Number(log.size_bytes)||
     (envelope!==undefined&&envelope!==span.envelope_observation_id))throw Error('invalid');
  envelope=span.envelope_observation_id;
 }
 return f.value as Record<string,ThermalItem>;
}
function ThermochemistrySummary({item}:{item:NativeAttempt}) {
 const f=item.facts.thermochemistry;
 let values:Record<string,ThermalItem>|null=null;
 let invalid=false;
 if(f!==undefined){try{values=thermalReport(item)}catch{invalid=true}}
 return <section className="native-thermochemistry"><h3>Gaussian热化学原始报告</h3>
  <p>这些是 Gaussian 原始报告值，未绑定本页的可比较热化学条件，未作 qRRHO、集合布居或科学验收。</p>
  {f===undefined?<p>热化学读取未连接（unavailable）</p>:invalid?<p role="alert">invalid-thermochemistry-fact</p>:<>
   {f.availability==='unavailable'?<p>不可用 (unavailable) · thermochemistry-unavailable</p>:<>
    {f.availability==='missing'&&<p>缺失 (missing) · thermochemistry-not-recorded</p>}
    <table><caption>Gaussian 原始热化学值 · hartree</caption><thead><tr><th scope="col">报告项</th><th scope="col">数值</th><th scope="col">单位</th></tr></thead>
     <tbody>{Object.entries(thermalLabels).map(([key,label])=><tr key={key}><th scope="row">{label}</th><td>{values?.[key]?String(values[key].value_hartree):'缺失 (missing)'}</td><td>hartree</td></tr>)}</tbody></table>
   </>}
   {values&&<details><summary>热化学来源与字节位置</summary><p>{f.source} · 解析版本：1.2.0</p><pre>{JSON.stringify(Object.fromEntries(Object.entries(values).map(([k,v])=>[k,v.source_span])),null,2)}</pre></details>}
  </>}
 </section>;
}
function Summary({item}:{item:NativeAttempt}){return <><p className="native-path">{item.source_id} / {item.project_id} → {item.workflow_run_id} → {item.task_id} → {item.attempt_id}</p><div className="native-grid"><div><h3>执行代际</h3><Value fact={item.generation}/></div><div><h3>程序</h3><Value fact={item.program}/></div>{Object.entries(item.axes).map(([key,fact])=><div key={key}><h3>{names[key]}</h3><Value fact={fact}/></div>)}</div><FrequencySummary item={item}/><p>事实可用性：{item.availability} {item.reason&&`· ${item.reason}`}</p><div className="native-grid">{Object.entries(item.facts).filter(([key])=>key!=='thermochemistry').map(([key,fact])=><div key={key}><h3>{names[key]}</h3><Value fact={fact}/></div>)}</div><ThermochemistrySummary item={item}/></>}
function nativeRoute(hash:string){
 try {
  if(hash==='#/native')return {source:'',group:'',identity:'',kind:'projects'};
  const parts=hash.split('/');
  if(parts.length!==5||parts[0]!=='#'||parts[1]!=='native')return null;
  const [source,group,identity]=parts.slice(2).map(decodeURIComponent);
  if(!/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}$/.test(source)||!identity||!['projects','attempts'].includes(group))return null;
  return {source,group,identity,kind:group==='projects'?'attempts':'attempt'};
 }catch{return null;}
}
export function NativePanel({token,hash}:{token:string;hash:string}){
 type Data=Projects|{items:NativeAttempt[]}|NativeAttempt|null;
 const [state,setState]=useState<{hash:string;token:string;data:Data;error:string}>({hash,token,data:null,error:''});
 const {data,error}=state.hash===hash&&state.token===token?state:{data:null,error:''};
 const parsed=nativeRoute(hash);const {source,group,identity,kind}=parsed??{source:'',group:'',identity:'',kind:'invalid'};
 useEffect(()=>{setState({hash,token,data:null,error:''});if(!parsed){setState({hash,token,data:null,error:'invalid-route'});return;}const c=new AbortController();let path='/api/v1/native/projects';if(source&&identity)path=`/api/v1/native/sources/${encodeURIComponent(source)}/${group}/${encodeURIComponent(identity)}${group==='projects'?'/attempts':''}`;
 requestJSON(path,token,c.signal,'native-scientific-read').then(v=>{if(!c.signal.aborted)setState({hash,token,data:decode(v,kind) as Data,error:''});}).catch(e=>{if(!c.signal.aborted)setState({hash,token,data:null,error:e instanceof Error?e.message:'request-failed'});});return()=>c.abort()},[hash,token]);
 return <section className="panel native-panel"><div className="eyebrow">READ ONLY · NATIVE RECORDS</div><h1>原生计算结果</h1><p>按来源保留 Project → WorkflowRun → Task → Attempt。执行成功和结果存在不代表科学验收。历史档案仍在原入口。</p>{source&&<a href="#/native">← 全部原生来源</a>}{error?<p role="alert">读取失败：{error}。<button onClick={()=>location.reload()}>重试</button></p>:!data?<p role="status">正在读取…</p>:kind==='projects'?<>{(data as Projects).sources.map(s=><p key={s.source_id}>来源 {s.source_id}：{s.availability} {s.reason}</p>)}{(data as Projects).items.map(p=><article key={`${p.source_id}:${p.project_id}`}><h2><a href={`#/native/${encodeURIComponent(p.source_id)}/projects/${encodeURIComponent(p.project_id)}`}>{p.project_id}</a></h2><p>来源：{p.source_id} · {p.workflow_run_ids.length} 个 WorkflowRun {p.identity_collision&&' · 跨来源同名，保持独立'}</p></article>)}</>:kind==='attempts'?<>{(data as {items:NativeAttempt[]}).items.length===0&&<p>此项目尚无 Attempt。</p>}{(data as {items:NativeAttempt[]}).items.map(item=><article key={item.attempt_id}><h2><a href={`#/native/${encodeURIComponent(item.source_id)}/attempts/${encodeURIComponent(item.attempt_id)}`}>{item.attempt_id}</a></h2><Summary item={item}/></article>)}</>:<><Summary item={data as NativeAttempt}/><NativeReliability sourceId={source} attemptId={identity} token={token}/><h2>来源追溯</h2><h3>精确绑定计划</h3><Value fact={(data as NativeAttempt).bound_plan}/><h3>输入</h3><Value fact={(data as NativeAttempt).input}/><h3>产物身份</h3><Value fact={(data as NativeAttempt).artifacts}/><details><summary>记录 ID 与契约</summary><pre>{JSON.stringify((data as NativeAttempt).record_inventory,null,2)}</pre></details><details><summary>Result 来源与历史</summary><pre>{JSON.stringify({provenance:(data as NativeAttempt).provenance,history:(data as NativeAttempt).history},null,2)}</pre></details></>}</section>
}
