import {object,artifact} from './provenance';
const SCHEMA='auto-g16-result-context/1',PLAN='auto-g16-v30-a-calculation-plan-intent/1';
const paths:Record<string,string>={method:'intent.method.electronic_structure_method',basis:'intent.method.basis',environment:'intent.method.environment',charge:'intent.molecule.charge',multiplicity:'intent.molecule.multiplicity',dispersion:'intent.method.dispersion'};
const labels:Record<string,string>={method:'Method / 方法',basis:'Basis / 基组',environment:'溶剂 / 环境',charge:'Charge / 电荷',multiplicity:'Multiplicity / 多重度',dispersion:'色散',temperature_k:'温度 / K',pressure_atm:'压力 / atm'};
const keys=Object.keys(labels);
type Field={availability:'available'|'missing'|'unavailable';value:string|number|null;source:Record<string,unknown>|null;reason:string|null};
type Context={schema:string;kind:'attempt'|'archive';id:string;lineage:Record<string,unknown>;plan:Record<string,unknown>|null;input:Record<string,unknown>|null;conditions:{declared:Record<string,Field>;observed:Record<string,Field>};comparison_status:string};
const text=(v:unknown):v is string=>typeof v==='string'&&v.length>0;
const hash=(v:unknown)=>typeof v==='string'&&/^[a-f0-9]{64}$/.test(v);
const equal=(a:unknown,b:unknown):boolean=>a===b||(object(a)&&object(b)&&Object.keys(a).length===Object.keys(b).length&&Object.keys(a).every(k=>equal(a[k],b[k])));
const planSource=(s:Record<string,unknown>,p:Record<string,unknown>)=>['kind','calculation_plan_id','revision','plan_sha256','input_binding_observation_id'].every(k=>s[k]===p[k]);
export function resultContext(v:unknown,kind:string,id:string,source:unknown):Context|null{
 if(!object(v)||v.schema!==SCHEMA||v.kind!==kind||v.id!==id||!object(v.lineage)||v.comparison_status!=='not-assessed'||!object(v.conditions)||!object(v.conditions.declared)||!object(v.conditions.observed))return null;
 const l=v.lineage,p=v.plan;
 if(!equal(l.result_source,source??null))return null;
 if(l.result_source!==null&&(!object(l.result_source)||!text(l.result_source.result_id)||!artifact(l.result_source.artifact)))return null;
 if(kind==='attempt'){
  if(l.scope!=='public-core-hierarchy'||l.attempt_id!==id||l.archive_id!==null||!['project_id','workflow_run_id','workflow_name','task_id'].every(k=>text(l[k])))return null;
 }else if(l.scope!=='legacy-archive-not-core-lineage'||l.archive_id!==id||['project_id','workflow_run_id','workflow_name','task_id','attempt_id','input_binding_observation_id'].some(k=>l[k]!==null)||p!==null)return null;
 if(p!==null&&(!object(p)||p.kind!=='bound-calculation-plan-declaration'||!text(p.calculation_plan_id)||!Number.isSafeInteger(p.revision)||Number(p.revision)<1||!hash(p.plan_sha256)||!text(p.input_binding_observation_id)||p.input_binding_observation_id!==l.input_binding_observation_id||!object(source)||(p.intent_schema!==null&&typeof p.intent_schema!=='string')))return null;
 if(kind==='attempt'&&((p===null)!==(l.result_source===null)||p===null&&l.input_binding_observation_id!==null))return null;
 if(v.input!==null&&(!object(v.input)||!text(v.input.logical_name)||!hash(v.input.sha256)||!Number.isSafeInteger(v.input.size_bytes)||Number(v.input.size_bytes)<0))return null;
 if(kind==='attempt'&&(p!==null)!==(v.input!==null))return null;
 for(const lane of ['declared','observed']){
  const values=v.conditions[lane];if(!object(values)||Object.keys(values).length!==keys.length)return null;
  for(const key of keys){const f=values[key];if(!object(f)||!['available','missing','unavailable'].includes(String(f.availability)))return null;
   if(f.availability==='available'){
    if(lane!=='declared'||!object(p)||p.intent_schema!==PLAN||!object(f.source)||!planSource(f.source,p)||f.source.field_path!==paths[key]||!paths[key]||f.reason!==null)return null;
    if(key==='charge'||key==='multiplicity'){if(!Number.isSafeInteger(f.value)||Number(f.value)<(key==='charge'?-1000:1)||Number(f.value)>1000)return null;}
    else if(!text(f.value)||f.value.length>256||f.value.trim()!==f.value||/[\x00-\x1f\x7f]/.test(f.value))return null;
   }else if(f.value!==null||!text(f.reason))return null;
   if(lane==='observed'&&(f.availability!=='unavailable'||f.source!==null||f.reason!=='qualified-parser-does-not-project-condition'))return null;
   if(lane==='declared'&&f.source!==null&&(!object(f.source)||!object(p)||!planSource(f.source,p)))return null;
  }
 }
 return v as Context;
}
const reasons:Record<string,string>={'not-recorded-in-bound-plan':'绑定计划未记录','unsupported-plan-intent-schema':'计划格式尚未接入','condition-not-projected-by-plan-contract':'计划契约尚未投影此项','archive-has-no-qualified-native-plan':'历史档案无合格原生计划','qualified-bound-plan-required':'暂无与此结果绑定的合格计划','invalid-declared-condition':'声明值格式不合格'};
export function ResultContext({value,kind,id,source,view='evidence'}:{value:unknown;kind:'attempt'|'archive';id:string;source:unknown;view?:'science'|'evidence'}){
 const c=resultContext(value,kind,id,source);
 if(!c)return <section className="result-context"><h3>来源链与计算条件</h3><p>来源上下文缺失或绑定不一致，暂不展示计算条件。</p></section>;
 if(view==='science')return <section className="condition-strip" data-testid="science-conditions"><div className="section-heading"><h3>计算条件 <small>绑定计划声明</small></h3><span className="micro muted">日志独立核对未接入 · 可比性未评估</span></div><dl>{keys.map(key=>{const f=c.conditions.declared[key];return <div key={key} title={f.reason?reasons[f.reason]??'来源不可用':String(f.source?.field_path)}><dt>{labels[key]}</dt><dd>{f.availability==='available'?(f.value==='gas_phase'?'气相':String(f.value)):f.availability==='missing'?'未记录':'未接入'}</dd></div>;})}</dl></section>;
 const l=c.lineage,s=object(l.result_source)?l.result_source:null;
 const item=(label:string,v:unknown,href?:string)=><div><small>{label}</small>{typeof v==='string'?(href?<a href={href}><code>{v}</code></a>:<code>{v}</code>):<span>未绑定</span>}</div>;
 return <section className="result-context" data-testid="result-context" aria-label="来源链与计算条件"><div className="section-heading"><div><div className="eyebrow">LINEAGE & CALCULATION CONDITIONS</div><h3>来源链与计算条件</h3></div><span className="badge">可比性尚未评估</span></div>
 <div className="result-lineage">{kind==='attempt'?<>{item('Project',l.project_id,`#/projects/${encodeURIComponent(String(l.project_id))}`)}{item('Task',l.task_id)}{item('Attempt',l.attempt_id)}</>:item('历史 Archive · 非 Core Attempt',l.archive_id)}{item('Result',s?.result_id)}{item('原始 log',object(s?.artifact)?s.artifact.logical_name:null)}</div>
 {kind==='attempt'&&<><table className="calculation-conditions"><thead><tr><th>计算条件</th><th>绑定计划声明</th><th>结果日志独立核对</th></tr></thead><tbody>{keys.map(key=>{const f=c.conditions.declared[key];return <tr key={key}><th>{labels[key]}</th><td><span>{f.availability==='available'?(f.value==='gas_phase'?'气相（gas_phase）':String(f.value)):f.availability==='missing'?'未记录':'未接入'}</span>{f.availability!=='available'&&<small>{reasons[f.reason??'']??'来源不可用'}</small>}</td><td><span>未接入</span></td></tr>;})}</tbody></table>
 <p className="micro muted">左列来自与该结果精确绑定的计划，不代表日志已验证这些条件。当前解析契约未提供右列字段；未知溶剂不默认作气相，未知温度不默认作 298.15 K。此处不授予能量可比性或科学接受。</p></>}
 {kind==='archive'&&<p className="micro">日志计算条件与历史输入声明集中显示在“科学结果”视图，并附原文件位置；这里保留来源链。历史目录归属不会升级为 Core Project、Task 或 Attempt 绑定。</p>}
 <details><summary>计划、输入与来源身份</summary><dl>{item('Workflow run',l.workflow_run_id)}{item('Workflow name',l.workflow_name)}{item('Calculation plan',c.plan?.calculation_plan_id)}{item('Plan revision',c.plan?.revision===undefined?null:String(c.plan.revision))}{item('Plan SHA-256',c.plan?.plan_sha256)}{item('Intent schema',c.plan?.intent_schema)}{item('Input binding',l.input_binding_observation_id)}{item('Input file',c.input?.logical_name)}{item('Input SHA-256（存储声明）',c.input?.sha256)}</dl><p className="micro">来源链来自本次 details 查询中的公共记录；输入文件哈希为存储声明，本卡不读取输入文件重新验哈希。</p><details><summary>逐字段来源</summary><pre>{JSON.stringify(c.conditions,null,2)}</pre></details></details>
 </section>;
}
