import {useState} from 'react';
import type {WorkflowLayout,LayoutEvidence} from './workflow-layout';

// Presentation-only allowlist. Exact task_kind values, never filenames, job names,
// frequency presence, or a successful Attempt imply a workflow stage or winner.
export const stages = [
  {id:'conformer',label:'构象搜索',kind:'conformer-search'},
  {id:'selection',label:'候选筛选',kind:'candidate-selection'},
  {id:'optimization',label:'优化',kind:'gaussian-opt'},
  {id:'frequency',label:'频率',kind:'gaussian-freq'},
  {id:'single-point',label:'单点能',kind:'gaussian-single-point'},
  {id:'review',label:'人工审核',kind:'scientific-review'},
] as const;
export type StageID = typeof stages[number]['id'];
export type StageFilter = StageID|'unclassified'|'';
export type StageTask = {task_id:string;task_kind:string;project_id:string;workflow_run_id:string;workflow_name:string;attempts:{core_state:string}[]};
export function taskStages(task:StageTask,layout?:WorkflowLayout|null):StageID[] {
  const explicit=layout?.availability==='available'?layout.nodes.filter(n=>n.project_id===task.project_id&&n.workflow_run_id===task.workflow_run_id&&n.task_ids.includes(task.task_id)):[];
  if(explicit.length)return [...new Set(explicit.map(n=>n.stage))];
  if(task.task_kind==='gaussian-opt-freq')return ['optimization','frequency'];
  return stages.filter(s=>s.kind===task.task_kind).map(s=>s.id);
}
export function matchesStage(task:StageTask,stage:StageFilter,layout?:WorkflowLayout|null){const ids=taskStages(task,layout);return !stage||stage==='unclassified'&&ids.length===0||ids.includes(stage as StageID);}
export function validStage(value:string):StageFilter{return value==='unclassified'||stages.some(s=>s.id===value)?value as StageFilter:'';}
export function stageLabel(task:StageTask,layout?:WorkflowLayout|null){return taskStages(task,layout).map(id=>stages.find(s=>s.id===id)!.label).join(' + ')||'未分类';}
function history(tasks:StageTask[]){
  const all=tasks.flatMap(t=>t.attempts);
  const counts=[['RUNNING','运行记录'],['SUBMITTED','提交记录'],['SUCCEEDED','成功记录'],['FAILED','失败记录'],['UNKNOWN','状态未知']] as const;
  return counts.map(([state,label])=>{const count=all.filter(a=>a.core_state===state).length;return count?`${label} ${count}`:'';}).filter(Boolean).join(' · ')|| (all.length?`${all.length} 次历史尝试`:'尚无尝试记录');
}
export function WorkflowStages({tasks,layout,value,onChange}:{tasks:StageTask[];layout:WorkflowLayout|null;value:StageFilter;onChange:(v:StageFilter)=>void}){
 const unclassified=tasks.filter(t=>taskStages(t,layout).length===0);
 return <section className="wf-stages" aria-label="工作流阶段分类">
  <div className="wf-stage-heading"><h2>工作流阶段</h2><div><button aria-pressed={value===''} onClick={()=>onChange('')}>全部任务 · {tasks.length}</button><button aria-pressed={value==='unclassified'} onClick={()=>onChange('unclassified')}>未分类 · {unclassified.length}</button></div></div>
  <div className="wf-stage-strip">{stages.map(s=>{const rows=tasks.filter(t=>taskStages(t,layout).includes(s.id));return <button key={s.id} aria-pressed={value===s.id} className={'wf-stage wf-stage-'+s.id} onClick={()=>onChange(value===s.id?'':s.id)} aria-label={`阶段：${s.label}`}><strong>{s.label}</strong><span>{rows.length?<><b>{rows.length}</b> 个任务</>:'未记录匹配任务'}</span><small>{rows.length?history(rows):'不代表未开始'}</small></button>;})}</div>
  <p className="wf-caption">按明确阶段记录或任务类型分类，点击筛选下表；组合任务可出现在多个阶段。数量按项目 / 运行范围统计，状态为全部历史尝试，不代表阶段已完成。</p>
 </section>;
}
export function WorkflowGroups({tasks,layout,onTask}:{tasks:StageTask[];layout:WorkflowLayout|null;onTask:(task:StageTask)=>void}){
 const runs=new Map<string,StageTask[]>();for(const t of tasks){const key=JSON.stringify([t.project_id,t.workflow_run_id]);runs.set(key,[...(runs.get(key)??[]),t]);}
 return <details className="wf-groups"><summary>任务分组与分支 · {runs.size} 个运行记录</summary>
  {layout?.availability==='available'?<RecordedBranches layout={layout} tasks={tasks} onTask={onTask}/>:<p className="wf-caption">流程依赖接口未接入。以下仅按已记录的 Workflow Run 分组，不推断先后、分支或汇合。</p>}
  {[...runs.entries()].map(([key,rows])=><details className="wf-run-group" key={key}><summary>{rows[0].workflow_name} · {rows.length} 个任务</summary><small>项目 {rows[0].project_id} · Run {rows[0].workflow_run_id}</small><ul>{rows.map(t=><li key={t.task_id}><span className="wf-stage-tag">{stageLabel(t,layout)}</span><button onClick={()=>onTask(t)}>{t.task_id}</button><small>{history([t])}</small></li>)}</ul></details>)}
  {!tasks.length&&<p className="wf-caption">当前范围暂无任务。</p>}
  <BranchExample/>
 </details>;
}
// A separate, explicitly fictional renderer preview. It never contributes to
// production filters, counts, Task/Attempt selection, or review records.
function BranchExample(){
 const [selected,setSelected]=useState<string|null>(null);
 const paths=[{id:'A',label:'候选 A',tone:'good',status:'成功记录'},{id:'B',label:'候选 B',tone:'run',status:'运行记录'}];
 return <details className="wf-branch-example"><summary>查看分支布局示例（非项目数据）</summary>
  <p className="wf-demo-note">布局示例 · 以下名称、状态和连线均为虚构，不对应任何真实任务，也不会启动计算。</p>
  <div className="wf-demo-entry"><span>构象搜索</span><span aria-hidden="true">→</span><span>候选筛选</span><small>示例分流为两个候选</small></div>
  <div className="wf-demo-paths">{paths.map(p=><div key={p.id} className="wf-demo-path"><strong>{p.label}</strong><div>{['优化','频率','单点能'].map((label,i)=><span className="wf-demo-step" key={label}>{i>0&&<span aria-hidden="true">→</span>}<button aria-pressed={selected===p.id+label} onClick={()=>setSelected(selected===p.id+label?null:p.id+label)}>{label}<small className={'wf-chip wf-'+(p.id==='A'||i===0?'good':i===1?p.tone:'quiet')}>{p.id==='A'||i===0?'成功记录':i===1?p.status:'计划记录'}</small></button></span>)}</div></div>)}</div>
  <div className="wf-demo-entry"><span>人工审核</span><small>示例汇合点 · 等待人工判断</small></div>
  {selected&&<p className="wf-demo-detail" role="status">示例节点：候选 {selected}。正式接入后，此处展示绑定任务、前置依赖和来源记录；执行成功不等于科学验收。</p>}
 </details>;
}

function Evidence({items}:{items:LayoutEvidence[]}){return <ol className="wf-layout-evidence">{items.map((e,i)=><li key={i}><strong>{e.source}</strong><code>{e.record_id}</code><code>SHA-256 · {e.sha256}</code><small>{e.recorded_at?new Date(e.recorded_at).toLocaleString('zh-CN',{hour12:false}):'时间未记录'}</small></li>)}</ol>;}
function RecordedBranches({layout,tasks,onTask}:{layout:WorkflowLayout;tasks:StageTask[];onTask:(task:StageTask)=>void}){
 const nodes=layout.nodes.filter(n=>tasks.some(t=>t.project_id===n.project_id&&t.workflow_run_id===n.workflow_run_id&&n.task_ids.includes(t.task_id)));
 const groups=new Map<string,typeof nodes>();for(const n of nodes){const key=JSON.stringify([n.project_id,n.workflow_run_id,n.branch_id]);groups.set(key,[...(groups.get(key)??[]),n]);}
 return <div className="wf-recorded-branches" aria-label="已记录的流程分支"><p className="wf-caption">连线仅来自明确依赖记录；阶段顺序不代表已完成，执行成功不等于人工验收。</p>{[...groups.entries()].map(([key,rows])=><details key={key}><summary>{rows[0].branch_id??'公共节点'} · {rows.length} 个节点 · {rows[0].workflow_run_id}</summary>{rows.map(n=><div key={n.node_id} className="wf-recorded-node"><strong>{n.label}</strong><span className="wf-stage-tag">{stages.find(s=>s.id===n.stage)!.label}</span><div>{n.task_ids.map(id=>{const t=tasks.find(t=>t.task_id===id&&t.project_id===n.project_id&&t.workflow_run_id===n.workflow_run_id);return t&&<button key={id} onClick={()=>onTask(t)}>{id} · 定位任务</button>;})}</div><details><summary>节点来源</summary><Evidence items={n.evidence}/></details>{layout.edges.filter(e=>e.to===n.node_id).map(e=><details key={e.from}><summary>前置依赖：{layout.nodes.find(a=>a.node_id===e.from)!.label} → {n.label}</summary><Evidence items={e.evidence}/></details>)}</div>)}</details>)}</div>;
}

export function TaskStageContext({layout,task}:{layout:WorkflowLayout|null;task:StageTask|undefined}){
 if(!task)return null;
 const nodes=layout?.availability==='available'?layout.nodes.filter(n=>n.project_id===task.project_id&&n.workflow_run_id===task.workflow_run_id&&n.task_ids.includes(task.task_id)):[];
 const related=layout?.edges.filter(e=>nodes.some(n=>n.node_id===e.to||n.node_id===e.from))??[];
 const refs=[...nodes.flatMap(n=>n.evidence),...related.flatMap(e=>e.evidence)];
 const unique=[...new Map(refs.map(e=>[JSON.stringify(e),e])).values()];
 const dated=unique.filter(e=>e.recorded_at).sort((a,b)=>Date.parse(a.recorded_at!)-Date.parse(b.recorded_at!)),undated=unique.filter(e=>!e.recorded_at);
 return <details className="wf-task-stage-context"><summary>阶段与流程来源 · {taskStages(task,layout).map(id=>stages.find(s=>s.id===id)!.label).join(' + ')||'未分类'}</summary><p className="wf-caption">{nodes.length?'阶段来源：明确流程记录':'阶段来源：Task.task_kind 精确分类；不代表计划依赖或科学完成'} · {task.task_kind}</p>
 {nodes.map(n=><p key={n.node_id}>{n.label} · {n.branch_id??'未指定分支'}</p>)}
 {related.map(e=><p key={JSON.stringify([e.from,e.to])}>{layout!.nodes.find(n=>n.node_id===e.from)!.label} → {layout!.nodes.find(n=>n.node_id===e.to)!.label}</p>)}
 {!nodes.length&&<p className="wf-caption">流程依赖与阶段证据尚未接入。</p>}
 {dated.length>0&&<><h3>流程来源时间线</h3><Evidence items={dated}/></>}
 {undated.length>0&&<details><summary>未记录时间的流程证据 · {undated.length}</summary><Evidence items={undated}/></details>}
 </details>;
}
