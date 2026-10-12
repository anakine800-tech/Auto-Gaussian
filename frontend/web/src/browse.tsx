import {SelectResult,SelectionActions} from './result-selection';
import {HistoricalReview} from './historical-review';
import {useAttemptEvidence,resultLabel} from './attempt-evidence';
import {StatusLegend} from './status-badge';
import { useEffect, useState } from 'react';
import { link, read } from './contract';
import type { Attempt, Field, Project, Task } from './contract';
import type { GaussianResult } from './result-contract';

export const fieldText = (f: Field) => f.availability === 'available' ? typeof f.value === 'object' ? JSON.stringify(f.value) : String(f.value) : f.availability === 'missing' ? '未记录' : '不可用';
export type SearchItem = { id: string; name: string; search: string; states: string[]; programs: string[]; pinned?:boolean };
export function useCollection<T>(items: T[], describe: (item: T) => SearchItem, persistKey?:string) {
  const storageKey=persistKey?'autog-browse/1:'+persistKey:null;
  const [saved]=useState(()=>{try{const v=JSON.parse(storageKey?sessionStorage.getItem(storageKey)??'{}':'{}');return v&&typeof v==='object'?v:{};}catch{return {};}});
  const [query,setQuery]=useState(typeof saved.query==='string'?saved.query:''),[state,setState]=useState(typeof saved.state==='string'?saved.state:''),[program,setProgram]=useState(typeof saved.program==='string'?saved.program:''),[sort,setSort]=useState(['name','name-desc','id'].includes(saved.sort)?saved.sort:'name'),[size,setSize]=useState([10,25,50].includes(saved.size)?saved.size:10),[page,setPage]=useState(Number.isSafeInteger(saved.page)&&saved.page>0?saved.page:1);
  useEffect(()=>{if(storageKey)try{sessionStorage.setItem(storageKey,JSON.stringify({query,state,program,sort,size,page}));}catch{/* Browsing remains usable if storage is disabled. */}},[storageKey,query,state,program,sort,size,page]);
  const described=items.map(item=>({item,...describe(item)}));
  const filtered=described.filter(x=>x.search.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())&&(!state||x.states.includes(state))&&(!program||x.programs.includes(program)));
  filtered.sort((a,b)=>Number(!!b.pinned)-Number(!!a.pinned)||(sort==='name-desc'?-1:1)*((sort==='id'?a.id.localeCompare(b.id):a.name.localeCompare(b.name,'zh-CN',{numeric:true}))||a.id.localeCompare(b.id)));
  const pages=Math.max(1,Math.ceil(filtered.length/size)),current=Math.min(page,pages);
  const reset=(fn:()=>void)=>{fn();setPage(1);};
  return { rows:filtered.slice((current-1)*size,current*size).map(x=>x.item),total:items.length,count:filtered.length,pages,page:current,size,
    query,state,program,sort,states:[...new Set(described.flatMap(x=>x.states))].sort(),programs:[...new Set(described.flatMap(x=>x.programs))].sort(),
    setQuery:(v:string)=>reset(()=>setQuery(v)),setState:(v:string)=>reset(()=>setState(v)),setProgram:(v:string)=>reset(()=>setProgram(v)),setSort:(v:string)=>reset(()=>setSort(v)),setSize:(v:number)=>reset(()=>setSize(v)),setPage,
    clear:()=>reset(()=>{setQuery('');setState('');setProgram('');}) };
}
type Collection = ReturnType<typeof useCollection>;
export function Filters({collection:c,label,programs=true,states=true,stateLabel='状态',placeholder='搜索名称或标识…'}:{collection:Collection;label:string;programs?:boolean;states?:boolean;stateLabel?:string;placeholder?:string}) {
  return <div className="browse-controls" role="search" aria-label={label+'筛选区'}><label className="search-box">搜索<input aria-label={label} placeholder={placeholder} value={c.query} onChange={e=>c.setQuery(e.target.value)}/></label>
    {programs&&<label>程序<select aria-label="程序筛选" value={c.program} onChange={e=>c.setProgram(e.target.value)}><option value="">全部程序</option>{c.programs.map(x=><option key={x}>{x}</option>)}</select></label>}
    {states&&<label>{stateLabel}<select aria-label="状态筛选" value={c.state} onChange={e=>c.setState(e.target.value)}><option value="">全部状态</option>{c.states.map(x=><option key={x}>{x}</option>)}</select></label>}
    <label>排序<select aria-label="排序" value={c.sort} onChange={e=>c.setSort(e.target.value)}><option value="name">名称 / 序号升序</option><option value="name-desc">名称 / 序号降序</option><option value="id">标识升序</option></select></label>
    {(c.query||c.state||c.program)&&<button onClick={c.clear}>清除筛选</button>}
  </div>;
}
export function Pagination({collection:c,unit='条记录'}:{collection:Collection;unit?:string}) {
  return <div className="pagination"><span role="status">匹配 {c.count} / {c.total} {unit}</span><label>每页 <select aria-label="每页条数" value={c.size} onChange={e=>c.setSize(Number(e.target.value))}>{[10,25,50].map(n=><option key={n}>{n}</option>)}</select></label><div><button aria-label="上一页" disabled={c.page<=1} onClick={()=>c.setPage(c.page-1)}>←</button><span>第 {c.page} / {c.pages} 页</span><button aria-label="下一页" disabled={c.page>=c.pages} onClick={()=>c.setPage(c.page+1)}>→</button></div></div>;
}
const describeAttempt=(a:Attempt):SearchItem=>({id:a.attempt_id,name:`${a.task_id} ${a.ordinal}`,search:[a.attempt_id,a.task_id,a.workflow_run_id,...Object.values(a.declared_science).map(fieldText),fieldText(a.input)].join(' '),states:[a.execution_state],programs:[fieldText(a.declared_science.program)]});
export function AttemptRows({attempts,results=false,token}:{attempts:Attempt[];results?:boolean;token?:string}) {
 const evidence=useAttemptEvidence(attempts.map(a=>a.attempt_id),token);
 return <div className="table-scroll"><table><thead><tr>{(results?['计算记录','方法 / 基组','执行状态','能量 / Hartree','频率 / 虚频','历史科学验证与范围']:['Attempt','Program / 方法','Execution · Core','Collection','历史 Validation 与范围','Result']).map(h=><th key={h}>{h}</th>)}</tr></thead><tbody>{attempts.map(a=>{
 const e=evidence[a.attempt_id],r=e?.result;
 const condition=(k:'method'|'basis')=>e?.context?.conditions.declared[k]?.availability==='available'?String(e.context.conditions.declared[k].value):fieldText(a.declared_science[k]);
 const program=a.declared_science.program.availability==='available'?fieldText(a.declared_science.program):r&&r!=='error'&&r.availability==='available'?'Gaussian · 绑定结果来源':'基础投影未提供程序';
 const review=<><HistoricalReview data={e?.review}/><small>{e?.detailStatus??'补充证据读取中…'}</small></>;
 return <tr key={a.attempt_id}><td><SelectResult item={{kind:'attempt',id:a.attempt_id,title:'Attempt '+a.ordinal+' · '+a.attempt_id,project:a.project_id}}/> <a href={link('attempts',a.attempt_id)}>Attempt {a.ordinal} ↗</a><code>{a.attempt_id}</code></td><td><strong>{results?condition('method'):program}</strong><small>{results?condition('basis')+' · '+program:condition('method')+' / '+condition('basis')}</small>{e?.context?.plan&&<small>精确绑定计划声明</small>}</td><td><span className={`badge state-${a.execution_state.toLowerCase()}`}>{a.execution_state}</span></td>{results?<><ResultCells data={r}/><td>{review}</td></>:<><td>{fieldText(a.collection)}</td><td>{review}</td><td>{resultLabel(r==='error'?'error':r?.availability??'loading')}<small>基础投影：{a.result_state}（不代表全部来源）</small></td></>}</tr>;
 })}</tbody></table></div>;
}
function ResultCells({data}:{data:GaussianResult|'error'|undefined}) {
  const state=resultLabel(data==='error'?'error':data?.availability??'loading');
  if(!data||data==='error'||!data.summary)return <><td className="muted">{state}</td><td className="muted">—</td></>;
  return <><td className="energy-cell">{data.summary.final_energy_hartree??'未记录'}<details><summary>结果来源</summary><code>{String(data.source?.result_id??'未记录')}</code></details></td><td>{data.summary.frequency.count??'未记录'} / {data.summary.frequency.imaginary_count??'未知'}</td></>;
}
export function AttemptsBrowser({attempts,token}:{attempts:Attempt[];token:string}) {
  const c=useCollection(attempts,describeAttempt,'attempts:'+(attempts[0]?.project_id??'empty'));
  return <section className="panel"><div className="section-heading"><h2>计算结果索引</h2><span>打开记录查看能量、频率与结构</span></div><SelectionActions/><StatusLegend/><Filters collection={c} label="搜索计算结果"/>{c.rows.length?<AttemptRows attempts={c.rows} results token={token}/>:<p className="empty compact">没有匹配的计算记录。</p>}<Pagination collection={c}/><p className="muted micro">这里展示全部历史尝试，不自动选择 Task 胜者。列表状态来自 Core；科学验收以详情中绑定的报告为准。分页作用于本次已读取数据；仅当前页读取结果摘要，不跨记录推断能量高低。</p></section>;
}
export function WorkflowBrowser({tasks,attempts,token}:{tasks:Task[];attempts:Attempt[];token:string}) {
  const c=useCollection(tasks,t=>{const rows=attempts.filter(a=>a.task_id===t.task_id);return {id:t.task_id,name:t.workflow_name+' '+t.task_id,search:[t.task_id,t.workflow_name,t.workflow_run_id,t.task_kind,...rows.map(a=>describeAttempt(a).search)].join(' '),states:rows.length?rows.map(a=>a.execution_state):['无 Attempt'],programs:rows.flatMap(a=>describeAttempt(a).programs)};}, 'workflow:'+location.hash);
  return <><SelectionActions/><Filters collection={c} label="搜索工作流与任务"/>{c.rows.length===0&&<p className="empty">{tasks.length?'没有匹配的任务。':'暂无 Task。'}</p>}{c.rows.map(t=><WorkflowTask key={t.task_id} task={t} attempts={attempts.filter(a=>a.task_id===t.task_id)} state={c.state} program={c.program} token={token}/>)}<Pagination collection={c} unit="个任务"/></>;
}
function WorkflowTask({task:t,attempts,state,program,token}:{task:Task;attempts:Attempt[];state:string;program:string;token:string}) {
  const rows=attempts.filter(a=>(!state||state==='无 Attempt'||a.execution_state===state)&&(!program||fieldText(a.declared_science.program)===program));
  const c=useCollection(rows,describeAttempt,'task:'+t.task_id);
  return <section className="panel task"><div className="card-top"><div><div className="eyebrow">TASK · {t.task_kind}</div><h2>{t.workflow_name}</h2><code>{t.task_id}</code></div><span className="source-tag">{attempts.length} Attempts</span></div><p className="muted">Workflow Run · <code>{t.workflow_run_id}</code></p>{attempts.length===0?<div className="empty compact">此 Task 尚无 Attempt。</div>:<><AttemptRows attempts={c.rows} token={token}/>{rows.length>10&&<Pagination collection={c}/>}</>}{attempts.length!==t.attempt_ids.length&&<p className="notice">两次读取的 Attempt 数量不同，请刷新重新核对。</p>}</section>;
}
export function ResultsExplorer({token}:{token:string}) {
  const [projects,setProjects]=useState<Project[]|null>(null),[selected,setSelected]=useState(''),[attempts,setAttempts]=useState<Attempt[]|null>(null),[error,setError]=useState(false);
  useEffect(()=>{const c=new AbortController();read('/api/projects','projects',token,c.signal).then(d=>{if(!c.signal.aborted)setProjects(d.items);}).catch(()=>{if(!c.signal.aborted)setError(true);});return()=>c.abort();},[token]);
  const projectId=selected||projects?.[0]?.project_id;
  useEffect(()=>{setAttempts(null);if(!projectId)return;const c=new AbortController();setError(false);read(`/api/projects/${encodeURIComponent(projectId)}/attempts`,'attempts',token,c.signal).then(d=>{if(d.items.some(a=>a.project_id!==projectId))throw new Error('identity');if(!c.signal.aborted)setAttempts(d.items);}).catch(()=>{if(!c.signal.aborted)setError(true);});return()=>c.abort();},[token,projectId]);
  return <><div className="page-heading"><div className="eyebrow">COMPUTATIONAL CHEMISTRY / RESULTS</div><h1>结果工作台</h1><p>从计算条件找到结果，再核对结构、频率与科学证据。</p></div>
    {error?<p role="alert" className="error">结果索引读取失败或身份不一致，已停止展示。</p>:projects===null?<p role="status">正在读取项目…</p>:<><div className="project-selector"><label>项目范围<select aria-label="结果项目" value={projectId??''} onChange={e=>{setAttempts(null);setSelected(e.target.value);}}>{projects.map(p=><option value={p.project_id} key={p.project_id}>{p.name.availability==='available'?fieldText(p.name):p.project_id}</option>)}</select></label><a href="#/archives">查看无 Core 绑定的历史档案 ↗</a></div>{!projects.length?<p className="empty">暂无项目。</p>:attempts?<AttemptsBrowser key={projectId} attempts={attempts} token={token}/>:<p role="status">正在读取计算结果索引…</p>}</>}
  </>;
}
