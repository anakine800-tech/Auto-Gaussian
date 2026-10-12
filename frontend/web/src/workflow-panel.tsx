import {HistoricalReview} from './historical-review';
import {useEffect,useRef,useState} from 'react';
import {requestJSON} from './contract';
import {useCollection,Filters,Pagination} from './browse';
import './workflow.css';
import {WorkflowStages,WorkflowGroups,TaskStageContext,matchesStage,validStage,stageLabel} from './workflow-stages';
import type {StageFilter} from './workflow-stages';
import {readLayout} from './workflow-layout';
import type {WorkflowLayout} from './workflow-layout';
import {useOrganization} from './project-organization';
import type {Group} from './project-organization';

type Job={job_id:string;fields:Record<string,string>;sampled_at:string;freshness:string;association:string;attempt_id:string|null};
type Event={kind:string;id:string;time:string|null;sequence?:number;label:string;status:string;source:string;data:Record<string,unknown>};
type Attempt={attempt_id:string;task_id:string;project_id:string;workflow_run_id:string;ordinal:number;core_state:string;parent_attempt_id:string|null;program:string;issues:string[];binding:{status:string;reason:string|null;job_id:string|null;receipt_id?:string;server?:{host:string;port:number;user:string}|null;workspace?:string|null;packet_source?:unknown};live:{status:string;reason:string|null;job:Job|null};result:{availability:string;summary:null|{termination:{status:string};frequency:{count:number|null;imaginary_count:number|null}};source:{result_id?:string}|null};input:null|{logical_name:string;sha256:string};requested_resources:Record<string,unknown>|null;timeline:Event[];review?:{historical:{availability:string;data?:{classification:string;acceptance_state:string}}|null;human_mode:{records:unknown[];other_target_count:number;reason:string|null}|null}};
type Task={task_id:string;task_kind:string;project_id:string;workflow_run_id:string;workflow_name:string;attempts:Attempt[]};
type Overview={layout?:unknown;schema:string;read_at:string;tasks:Task[];server_jobs:Job[];queue_status:string;monitor_state:string};
const core:Record<string,string>={PLANNED:'计划中',SUBMISSION_INTENT_RECORDED:'提交意图已记录',NOT_SUBMITTED:'未提交',SUBMITTED:'已提交',RUNNING:'运行记录',SUCCEEDED:'成功记录',FAILED:'失败记录',UNKNOWN:'状态未知'};
const effects:Record<string,string>={'local-workspace':'准备本地工作区','remote-workspace':'准备远端工作区','input-transfer':'传输输入','submission':'提交作业','submission-reconciliation':'提交结果核对','input-binding':'绑定输入','output-capture':'回收输出','parse-result':'解析结果',scheduler:'调度观测',process:'进程观测',gaussian:'程序观测','human-intended-mode':'人工确认目标振动'};
const reasons:Record<string,string>={'no-confirmed-submission-receipt':'缺少确认提交的回执','invalid-or-conflicting-receipts':'提交回执冲突','receipt-input-snapshot-conflict':'输入与回执身份冲突','execution-packet-conflict':'执行来源不一致','submission-birth-identity-not-recorded':'提交回执未记录作业创建信息，无法排除编号重用','different-server-or-account':'采样服务器或账号不同','telemetry-not-fresh':'监控样本已过期','not-observed-does-not-imply-completion':'本轮未观察到作业，不代表已完成','job-id-reused-or-birth-identity-conflicts':'作业创建信息冲突，可能重用了编号','exact-workspace-not-observed':'未核实相同工作目录','multiple-attempts-claim-job':'多个 Attempt 声明同一作业','scheduler-detail-unavailable':'调度明细尚不可用','historical-binding-required':'缺少可靠的历史提交关联'};
const liveNames:Record<string,string>={R:'运行中',Q:'排队中',H:'挂起',W:'等待',E:'退出中',C:'调度已结束',T:'迁移中',S:'暂停'};
const saved=(key:string)=>{try{return sessionStorage.getItem(key)??'';}catch{return '';}};
const savedExpanded=()=>{try{const v=JSON.parse(saved('autog-workflow-expanded')||'[]');return Array.isArray(v)?v.filter((x:unknown)=>typeof x==='string').slice(0,1000) as string[]:[];}catch{return [];}};
const date=(v:string)=>new Date(v).toLocaleString('zh-CN',{hour12:false});
const tone=(v:string)=>['FAILED','conflict','error-termination','unparseable'].includes(v)?'bad':['UNKNOWN','possibly_effectful','stale','Q','H'].includes(v)?'wait':['R','RUNNING','SUBMITTED'].includes(v)?'run':['SUCCEEDED','confirmed_effect','parsed','normal-termination','verified'].includes(v)?'good':'quiet';
function Chip({value,label}:{value:string;label?:string}){return <span className={`wf-chip wf-${tone(value)}`}>{label??core[value]??liveNames[value]??value}</span>;}
function check(v:unknown):Overview{
  const d=v as Overview;if(!d||d.schema!=='autog-workflow-overview/1'||!Array.isArray(d.tasks)||!Array.isArray(d.server_jobs)||!d.tasks.every(t=>typeof t.task_id==='string'&&typeof t.project_id==='string'&&Array.isArray(t.attempts)&&t.attempts.every(a=>a.task_id===t.task_id&&a.project_id===t.project_id&&a.workflow_run_id===t.workflow_run_id&&typeof a.attempt_id==='string'&&Number.isInteger(a.ordinal)&&a.binding&&a.live&&a.result&&Array.isArray(a.issues))))throw Error('invalid-workflow');return d;
}
function taskSearch(t:Task){return {id:t.task_id,name:t.workflow_name+' '+t.task_id,search:[t.workflow_name,t.task_id,t.project_id,t.workflow_run_id,t.task_kind,...t.attempts.flatMap(a=>[a.attempt_id,a.binding.job_id??'',a.input?.logical_name??''])].join(' '),states:t.attempts.map(a=>core[a.core_state]??a.core_state),programs:t.attempts.map(a=>a.program)};}
export function WorkflowPanel({token,projectId=''}:{token:string;projectId?:string}){
 const org=useOrganization();
 const [purpose,setPurpose]=useState(()=>saved('autog-workflow-purpose')||'calculation');
 useEffect(()=>{try{sessionStorage.setItem('autog-workflow-purpose',purpose);}catch{}},[purpose]);
 const projectGroup=(id:string):Group=>({id,kind:'native',label:id,source_label:'Core',basis:'public-core-hierarchy',count:0,task_count:0,states:[]});
 const [data,setData]=useState<Overview|null>(null),[error,setError]=useState(false),[selected,setSelected]=useState<string|null>(null);
 const [project,setProject]=useState(()=>projectId||saved('autog-workflow-project')),[run,setRun]=useState(()=>saved('autog-workflow-run'));
 const [stage,setStage]=useState<StageFilter>(()=>validStage(saved('autog-workflow-stage')));
 useEffect(()=>{try{sessionStorage.setItem('autog-workflow-stage',stage);}catch{}},[stage]);
 const [detail,setDetail]=useState<Attempt|null>(null),[detailError,setDetailError]=useState(false),[expanded,setExpanded]=useState<string[]>(savedExpanded);
 useEffect(()=>{try{sessionStorage.setItem('autog-workflow-expanded',JSON.stringify(expanded));}catch{}},[expanded]);
 const table=useRef<HTMLDivElement>(null);
 const side=useRef<HTMLElement>(null),opener=useRef<HTMLButtonElement|null>(null);
 useEffect(()=>{try{sessionStorage.setItem('autog-workflow-project',project);sessionStorage.setItem('autog-workflow-run',run);}catch{}},[project,run]);
 useEffect(()=>{const c=new AbortController();let timer:ReturnType<typeof setTimeout>|undefined;async function poll(){try{const v=check(await requestJSON('/api/workflows',token,c.signal));if(!c.signal.aborted){setData(v);setError(false);}}catch{if(!c.signal.aborted)setError(true);}finally{if(!c.signal.aborted)timer=setTimeout(poll,15000);}}void poll();return()=>{c.abort();clearTimeout(timer);};},[token]);
 useEffect(()=>{setDetail(null);setDetailError(false);},[selected,token]);
 useEffect(()=>{if(!selected)return;const c=new AbortController();
  requestJSON('/api/workflows/attempts/'+encodeURIComponent(selected),token,c.signal).then(v=>{const d=v as {schema:string;attempt:Attempt};if(d.schema!=='autog-workflow-overview/1'||d.attempt.attempt_id!==selected||!Array.isArray(d.attempt.timeline))throw Error();if(!c.signal.aborted){setDetail(d.attempt);setDetailError(false);}}).catch(()=>{if(!c.signal.aborted)setDetailError(true);});return()=>c.abort();
 },[selected,token,data?.read_at]);
 const layoutRead=readLayout(data?.layout,data?.tasks??[]);
 const layout=layoutRead.layout;
 const tasks=(data?.tasks??[]).filter(t=>(purpose==='all'||org.info(projectGroup(t.project_id)).bucket===purpose)&&(!project||t.project_id===project)&&(!run||t.workflow_run_id===run)),all=tasks.flatMap(t=>t.attempts),c=useCollection(tasks.filter(t=>matchesStage(t,stage,layout)),taskSearch,'workflow-overview');
 const chooseStage=(value:StageFilter)=>{setStage(value);c.setPage(1);};
 const linked=(data?.server_jobs??[]).filter(j=>j.association==='verified'),unlinked=(data?.server_jobs??[]).filter(j=>j.association!=='verified');
 const close=()=>{setSelected(null);opener.current?.focus();};
 function open(a:Attempt,button:HTMLButtonElement){try{sessionStorage.setItem('autog-return:#/attempts/'+encodeURIComponent(a.attempt_id),location.hash);}catch{}location.hash='#/attempts/'+encodeURIComponent(a.attempt_id)+'?view=evidence&project='+encodeURIComponent(a.project_id);}
 const projects=[...new Set(data?.tasks.filter(t=>purpose==='all'||org.info(projectGroup(t.project_id)).bucket===purpose).map(t=>t.project_id)??[])],runs=[...new Set(data?.tasks.filter(t=>!project||t.project_id===project).map(t=>t.workflow_run_id)??[])];
 return <section className="workflow-page"><div className="wf-heading"><div><div className="eyebrow">WORKFLOW / OPERATIONS</div><h1>运行总览</h1><p>任务、运行观测与科学结果分栏查看，点击尝试展开证据。</p></div><a href="#/projects">项目与历史目录 ↗</a></div>
  {error&&<p className="notice warning" role="alert">刷新失败，保留的记录已过期；不能作为当前运行状态。</p>}
  {!data?<p role="status">{error?'工作流数据不可用。':'正在读取工作流…'}</p>:<>
  <div className="wf-summary"><div><small>本地计算任务</small><strong>{tasks.length}<em>个</em></strong></div><div><small>全部历史尝试</small><strong>{all.length}<em>次</em></strong></div><div><small>已关联的实时作业 · 全账号</small><strong>{data.queue_status==='available'&&['fresh','partial'].includes(data.monitor_state)?linked.length:'—'}<em>个</em></strong></div><div><small>尚未关联的服务器作业 · 全账号</small><strong>{data.queue_status==='available'&&['fresh','partial'].includes(data.monitor_state)?unlinked.length:'—'}<em>个</em></strong></div></div>
  <div className="wf-scope"><label>用途分区<select aria-label="运行用途" value={purpose} onChange={e=>{setPurpose(e.target.value);setProject('');setRun('');}}><option value="calculation">计算记录</option><option value="test">测试 / 验收</option><option value="all">全部用途</option></select></label><label>项目<select aria-label="运行项目" value={project} onChange={e=>{setProject(e.target.value);setRun('');}}><option value="">全部本地项目</option>{projects.map(p=><option key={p} value={p}>{org.info(projectGroup(p)).project}</option>)}</select></label><label>Workflow Run<select aria-label="工作流运行筛选" value={run} onChange={e=>setRun(e.target.value)}><option value="">全部运行记录</option>{runs.map(r=><option key={r}>{r}</option>)}</select></label><small>读取 {date(data.read_at)} · 每 15 秒刷新本地快照<br/>服务器采样：{['fresh','partial'].includes(data.monitor_state)?'可读取':'过期或不可用'}</small></div>
  <WorkflowStages tasks={tasks} layout={layout} value={stage} onChange={chooseStage}/>
  {layoutRead.invalid&&<p className="notice warning" role="alert">阶段依赖数据不完整或身份冲突，已停止展示关系；任务表仍可查看。</p>}
  <WorkflowGroups tasks={tasks} layout={layout} onTask={t=>{setSelected(null);setStage('');c.clear();c.setQuery(t.task_id);setExpanded(v=>v.includes(t.task_id)?v:[...v,t.task_id]);requestAnimationFrame(()=>table.current?.scrollIntoView({block:'start'}));}}/>
  <details className="wf-evidence-coverage"><summary>流程证据覆盖</summary><div className="wf-coverage" aria-label="历史证据覆盖"><span>输入已绑定 <b>{all.filter(a=>a.input).length}/{all.length}</b></span><span>确认提交回执 <b>{all.filter(a=>a.binding.status==='historical-confirmed').length}/{all.length}</b></span><span>结果摘要可读 <b>{all.filter(a=>a.result.availability==='available').length}/{all.length}</b></span><span>科学审核 <b>按具体结果核对</b></span></div>
  <p className="wf-caption">以上为全部历史 Attempts 的证据覆盖，不是完成百分比；未定义当前 Task 胜者或依赖关系。</p></details>
  <div className={`wf-layout ${selected?'with-detail':''}`}><div className="wf-list"><Filters collection={c} label="搜索运行任务"/>
   <div ref={table} className="table-scroll wf-task-table"><table><thead><tr><th>计算任务 / 工作流</th><th>历史执行记录</th><th>Job 关联</th><th>计算结果</th><th>科学复核</th><th>尝试与证据</th></tr></thead><tbody>{c.rows.map(t=>{
    const states=[...new Set(t.attempts.map(a=>a.core_state))],shown=expanded.includes(t.task_id);
    return <TaskRows key={t.task_id} task={t} layout={layout} shown={shown} states={states} onToggle={()=>setExpanded(v=>shown?v.filter(id=>id!==t.task_id):[...v,t.task_id])} onOpen={open}/>;
   })}</tbody></table>{c.rows.length===0&&<p className="empty compact">没有匹配的本地任务。</p>}</div><Pagination collection={c} unit="个任务"/>
   <section className="panel wf-unlinked"><div className="wf-heading"><h2>服务器作业 · 尚未关联</h2><a href="#/monitor">服务器监控 ↗</a></div><p>这些作业可被观测，但尚未核实到当前本地库中的 Attempt。名称相似不构成关联。</p>
    {data.queue_status!=='available'?<p className="notice warning">队列明细不可用，不能解释为空队列。</p>:unlinked.length===0?<p>本轮没有未关联作业；作业消失不代表计算成功。</p>:<div className="table-scroll"><table><thead><tr><th>Job / 名称</th><th>观测状态</th><th>已运行 / 分配</th><th>身份与来源</th></tr></thead><tbody>{unlinked.map(j=><tr key={j.job_id}><td><strong>{j.job_id}</strong><small>{j.fields.Job_Name??'未知'}</small></td><td><Chip value={j.fields.job_state??'UNKNOWN'}/><small>{j.freshness==='fresh'||j.freshness==='partial'?'最近采样':'过期样本'}</small></td><td>{j.fields['resources_used.walltime']??'未知'}<small>{j.fields.exec_host??'节点未知'}</small></td><td><details><summary>查看身份</summary><dl><dt>工作目录</dt><dd>{j.fields.init_work_dir??'未记录'}</dd><dt>作业创建时间 · 服务器原文</dt><dd>{j.fields.ctime??'未记录'}</dd><dt>采样时间</dt><dd>{date(j.sampled_at)}</dd></dl></details></td></tr>)}</tbody></table></div>}
   </section>
  </div>
  {selected&&<section ref={side} tabIndex={-1} className="wf-side panel" aria-label="任务详情" onKeyDown={e=>{if(e.key==='Escape')close();}}><div className="wf-side-head"><h2>任务详情与证据</h2><button aria-label="关闭任务详情" onClick={close}>关闭 ×</button></div>
   {detailError?<p role="alert">详情无法读取或身份不一致。没有展示其他任务的旧数据。</p>:!detail?<p role="status">读取所选 Attempt…</p>:<><TaskStageContext layout={layout} task={data.tasks.find(t=>t.task_id===detail.task_id&&t.project_id===detail.project_id&&t.workflow_run_id===detail.workflow_run_id)}/><AttemptDetail a={detail}/></>}
  </section>}
  </div></>}
 </section>;
}
function TaskRows({task:t,layout,shown,states,onToggle,onOpen}:{task:Task;layout:WorkflowLayout|null;shown:boolean;states:string[];onToggle:()=>void;onOpen:(a:Attempt,b:HTMLButtonElement)=>void}){
 return <><tr><td><strong>{stageLabel(t,layout)}</strong><small>{t.task_kind}</small><small>{t.workflow_name}</small><code>{t.task_id}</code></td><td>{states.length?states.map(s=><div key={s}><Chip value={s}/> × {t.attempts.filter(a=>a.core_state===s).length}</div>):'无 Attempt'}</td><td>{t.attempts.filter(a=>a.binding.status==='historical-confirmed').map(a=><div key={a.attempt_id}><code>{a.binding.job_id}</code><small>历史回执 · Attempt {a.ordinal}</small></div>)}{!t.attempts.some(a=>a.binding.status==='historical-confirmed')&&'尚未核实'}{t.attempts.some(a=>a.binding.status==='conflict')&&<Chip value="conflict" label="关联冲突"/>}</td><td>{t.attempts.filter(a=>a.result.availability==='available').length} / {t.attempts.length} 次摘要可读</td><td>按 Result 独立核对<small>不由执行成功推断</small></td><td><button aria-expanded={shown} onClick={onToggle}>{shown?'收起':'展开'} {t.attempts.length} 次尝试</button></td></tr>
 {shown&&t.attempts.map(a=><tr className="wf-attempt-row" key={a.attempt_id}><td><button className="wf-attempt-link" onClick={e=>onOpen(a,e.currentTarget)}>Attempt {a.ordinal} · 查看证据 →</button><code>{a.attempt_id}</code></td><td><Chip value={a.core_state}/><small>{a.live.status==='verified'?'实时 PBS：'+(liveNames[a.live.job?.fields.job_state??'']??a.live.job?.fields.job_state):'实时关联未核实'}</small></td><td>{a.binding.job_id??'—'}<small>{a.binding.status==='historical-confirmed'?'提交回执已确认':a.binding.status==='conflict'?'来源冲突':'无确认提交回执'}</small></td><td>{a.result.summary?<><Chip value={a.result.summary.termination.status} label={a.result.summary.termination.status==='normal-termination'?'正常结束':a.result.summary.termination.status==='error-termination'?'异常结束':'终止未知'}/><small>频率 / 虚频 {a.result.summary.frequency.count??'未知'} / {a.result.summary.frequency.imaginary_count??'未知'}</small></>:<span>{a.result.availability==='missing'?'尚无结果':a.result.availability==='unsupported'?'来源尚不支持':'结果待核对'}</span>}</td><td>{a.result.summary?.frequency.imaginary_count===1?'核对目标振动方向':'查看绑定审核记录'}</td><td><button onClick={e=>onOpen(a,e.currentTarget)}>详情</button></td></tr>)}</>;
}
function AttemptDetail({a}:{a:Attempt}){
 const hist=a.review?.historical,mode=a.review?.human_mode;
 const dated=a.timeline.filter(e=>e.time).sort((x,y)=>Date.parse(x.time!)-Date.parse(y.time!)),undated=a.timeline.filter(e=>!e.time);
 return <><div className="wf-selected"><strong>Attempt {a.ordinal}</strong> <Chip value={a.core_state}/><code>{a.attempt_id}</code><small>所选尝试，不代表 Task 当前胜者</small></div>
  <div className="wf-side-actions"><a className="wf-action" href={'#/attempts/'+encodeURIComponent(a.attempt_id)}>科学结果 / 振动 / 原日志 ↗</a><a href={'#/projects/'+encodeURIComponent(a.project_id)}>项目记录 ↗</a></div>
  <dl className="wf-facts"><dt>Job 关联</dt><dd>{a.binding.status==='historical-confirmed'?<><strong>{a.binding.job_id}</strong> · 历史回执确认</>:reasons[a.binding.reason??'']??'不可用'}</dd><dt>实时观测</dt><dd>{a.live.status==='verified'?<><Chip value={a.live.job?.fields.job_state??'UNKNOWN'}/><small>采样 {date(a.live.job!.sampled_at)}</small></>:reasons[a.live.reason??'']??'未核实'}</dd><dt>服务器 / 账号</dt><dd>{a.binding.server?`${a.binding.server.host}:${a.binding.server.port} · ${a.binding.server.user}`:'未绑定'}</dd><dt>输入</dt><dd>{a.input?.logical_name??'未接入'}</dd><dt>请求资源</dt><dd>{a.requested_resources?`${a.requested_resources.cores} 核 · ${a.requested_resources.memory_mb} MiB · ${a.requested_resources.queue}`:'未记录'}<small>提交时请求，不是实测用量</small></dd><dt>结果摘要</dt><dd>{a.result.availability==='available'?'已解析，可打开科学结果':a.result.availability==='missing'?'尚无可用结果':'结果来源待核对'}</dd><dt>科学复核</dt><dd><HistoricalReview data={hist?.availability==='available'?hist.data:null}/><small>{mode?.records.length?`目标振动已有 ${mode.records.length} 条人工确认（不等于 TS 验收）`:mode?.reason==='single-imaginary-candidate-required'?'目标振动确认不适用于当前结果':mode?.reason==='review-writing-disabled'?'目标振动确认记录未接入':'目标振动：未读取到当前结果的人工确认'}</small></dd></dl>
  {a.issues.length>0&&<p className="notice warning">部分证据不可用：{a.issues.join(' · ')}</p>}
  <h3>证据时间线</h3><p className="wf-caption">有时间戳的事实按来源时间排序；没有时间戳的记录单独列出，不补造发生时间。</p>
  <ol className="wf-timeline">{dated.map(e=><EventRow key={e.id} event={e}/>)}{dated.length===0&&<li>尚无带时间戳的证据。</li>}</ol>
  <details open className="wf-undated"><summary>未记录时间的证据 · {undated.length}</summary><p className="wf-caption">提交回执保留 effect sequence；不同证据类型之间不推断先后关系。</p><ol className="wf-timeline">{undated.map(e=><EventRow key={e.id} event={e}/>)}</ol></details>
  <details><summary>关联依据与身份</summary><pre>{JSON.stringify(a.binding,null,2)}</pre><p className="wf-caption">作业名称、PID 或目录相似度不能替代提交证据。查询不会提交、取消或重新计算。</p></details>
 </>;
}
function EventRow({event:e}:{event:Event}){return <li><div><strong>{effects[e.label]??e.label}</strong><Chip value={e.status} label={{confirmed_effect:'已确认发生',confirmed_no_effect:'已确认未发生',possibly_effectful:'发生与否待核对',recorded:'已记录',captured:'已回收',parsed:'已解析',unparseable:'无法解析',absent:'当时未观察到'}[e.status]??e.status}/></div><small>{e.time?date(e.time):e.sequence?`回执顺序 ${e.sequence} · 时间未记录`:'时间未记录'}</small><details><summary>来源 · {e.source}</summary><code>{e.id}</code><pre>{JSON.stringify(e.data,null,2)}</pre></details></li>;}

export function WorkflowAttemptEvidence({id,project,task,run,token}:{id:string;project:string;task:string;run:string;token:string}){
 const [detail,setDetail]=useState<Attempt|null>(null),[overview,setOverview]=useState<Overview|null>(null),[error,setError]=useState(false);
 const supported=/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}$/.test(id);
 useEffect(()=>{if(!supported)return;const c=new AbortController();Promise.all([requestJSON('/api/workflows/attempts/'+encodeURIComponent(id),token,c.signal),requestJSON('/api/workflows',token,c.signal)]).then(([raw,all])=>{const d=raw as {schema:string;attempt:Attempt};if(d.schema!=='autog-workflow-overview/1'||d.attempt.attempt_id!==id||d.attempt.project_id!==project||d.attempt.task_id!==task||d.attempt.workflow_run_id!==run||!Array.isArray(d.attempt.timeline))throw Error('identity');const o=check(all);if(!c.signal.aborted){setDetail(d.attempt);setOverview(o);}}).catch(()=>{if(!c.signal.aborted)setError(true);});return()=>c.abort();},[id,project,task,run,token]);
 const layout=overview?readLayout(overview.layout,overview.tasks):null;
 return <section className="panel" aria-label="任务详情" tabIndex={-1}>{!supported?<p>此标识的运行补充视图尚不支持；下方保留原生状态与已绑定证据。</p>:error?<p role="alert">运行补充详情无法读取或身份不一致，未展示其他任务的数据。</p>:!detail?<p role="status">读取运行补充证据…</p>:<><TaskStageContext layout={layout?.layout??null} task={overview?.tasks.find(t=>t.task_id===task&&t.project_id===project&&t.workflow_run_id===run)}/><AttemptDetail a={detail}/></>}</section>;
}
