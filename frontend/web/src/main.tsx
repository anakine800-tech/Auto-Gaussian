import {NativePanel} from './native-panel';
import {ReturnToList} from './navigation';
import {parseSelection} from './result-selection';
import {canonicalRoute,routeParams,routeLink,projectFromRoute,SectionTabs,ProjectContext,useRoutePosition} from './navigation';
import './navigation.css';
import {DraftPanel} from './draft-panel';
import {OfflineSciencePanel} from './offline-science-panel';
import {CapabilitiesPanel} from './capabilities-panel';
import './pre-v31.css';
import {TaskCenter} from './task-center';
import {ScreeningPanel} from './screening-panel';
import './operations.css';
import {WorkflowPanel,WorkflowAttemptEvidence} from './workflow-panel';
import {MonitorPanel} from './monitor-panel';
import {ProjectLibrary} from './project-library';
import { useEffect, useState } from 'react';
import type { FormEvent, ReactNode } from 'react';
import { createRoot } from 'react-dom/client';
import { link, read, requestJSON, route, STATES } from './contract';
import type { Attempt, Field, Json, Project, Task } from './contract';
import './style.css';
import './density.css';
import './molecule-layout.css';
import './scientific-validation.css';
import { LibraryPanel } from './library-panel';
import { ResultPanel } from './result-panel';
import { ArchivePanel } from './archive-panel';
import { DetailWorkspace, ViewGroup } from './workspace-view';
import './focused-layout.css';
import './compact-science.css';
import './workspace-theme.css';
import { DetailPanel } from './detail-panel';
import { useCollection, Filters, Pagination, WorkflowBrowser, AttemptsBrowser, AttemptRows, } from './browse';

const reasons: Record<string, string> = {
  'not-recorded-by-core': 'Core 未记录此字段',
  'no-authoritative-project-activity-clock': '尚无权威的项目活动时间来源',
  'no-canonical-current-task-attempt-selection': '尚未定义当前 Task 的 Attempt 选择规则',
  'unsupported-evidence-protocol': '存在尚未支持的证据协议',
  'execution-receipt-reader-not-connected': '基础查询未提供；补充来源见下方历史证据',
  'attempt-snapshot-reader-not-connected': '基础查询未提供实测资源；提交时请求见下方历史证据',
  'validation-store-readonly-interface-unavailable': '基础查询未提供；已连接的历史报告见下方',
  'no-exact-attempt-input-binding': '尚无绑定到此 Attempt 的输入记录',
  'field-not-declared-in-bound-plan': '绑定计划中未声明此字段',
  'no-persisted-observe-sample': '尚无持久化的 Observe 样本',
  'no-persisted-output-envelope': '尚无持久化的输出封套',
  'artifact-content-access-not-enabled': '基础查询仅提供引用；已连接的本地日志可在下方读取',
};
const errors: Record<string, string> = {
  unauthorized: '只读令牌无效或已失效。请断开后重新连接。',
  'not-found': '未找到这条记录。它可能不属于当前数据源。',
  'store-unavailable': '当前数据源不可读取。请确认使用受支持的静止本地快照。',
  'invalid-evidence': '证据结构无法通过校验，已停止展示。',
  'response-too-large': '数据超过本版读取上限，未展示不完整结果。',
  'contract-mismatch': '接口返回的数据不符合查询契约 v1，已停止展示。',
};
function Value({ value }: { value: Json }) {
  if (value === null) return <span className="muted">null</span>;
  if (typeof value !== 'object') return <span className="value">{String(value)}</span>;
  return <pre>{JSON.stringify(value, null, 2)}</pre>;
}
function FieldView({ label, field }: { label: string; field: Field }) {
  return <div className="field"><dt>{label}</dt><dd>{field.availability === 'available'
    ? (field.value!==null&&typeof field.value==='object'?<details className="inline-record"><summary>查看结构化记录</summary><Value value={field.value}/></details>:<Value value={field.value}/>) : <span className="muted">{field.availability === 'missing' ? '未记录' : '不可用'}</span>}
    <small>{field.source ? `来源 · ${field.source}` : reasons[field.reason ?? ''] ?? field.reason}</small>
  </dd></div>;
}
function Badge({ state }: { state: string }) { return <span className={`badge state-${state.toLowerCase()}`}>{state}</span>; }
function Panel({ title, eyebrow, children }: { title: string; eyebrow?: string; children: ReactNode }) {
  return <section className="panel">{eyebrow && <div className="eyebrow">{eyebrow}</div>}<h2>{title}</h2>{children}</section>;
}
function Summary({ project }: { project: Project }) {
  return <div className="stats"><div><strong>{project.task_count}</strong><span>任务 · Tasks</span></div><div><strong>{project.attempt_summary.total}</strong><span>全部历史 Attempts</span></div>
    <div className="state-summary">{STATES.map(s => <span key={s}>{s} <b>{project.attempt_summary.state_counts[s]}</b></span>)}</div></div>;
}
function ProjectPage({ project: p, tasks, attempts, token }: { project: Project; tasks: Task[]; attempts: Attempt[]; token:string }) {
  const [mode,setMode]=useState(()=>{try{return sessionStorage.getItem('autog-project-view:'+p.project_id)==='results'?'results':'workflow';}catch{return 'workflow';}});
  useEffect(()=>{try{sessionStorage.setItem('autog-project-view:'+p.project_id,mode);}catch{}},[p.project_id,mode]);
  const taskIds = new Set(tasks.map(t => t.task_id));
  const detached = attempts.filter(a => !taskIds.has(a.task_id));
  return <><a className="back" href="#/projects">← 所有项目</a><div className="page-heading"><div className="eyebrow">PROJECT / RESEARCH RECORDS</div><h1>{p.name.availability === 'available' ? String(p.name.value) : '未记录项目名称'}</h1><code>{p.project_id}</code></div>
    <Summary project={p}/><div className="notice">全历史统计，不选择“当前胜者”。以下列表分别读取独立快照；创建时间未由 Core 记录。</div>
    <div className="section-heading"><h2>任务与尝试</h2><span>{tasks.length} Tasks / {attempts.length} Attempts</span></div>
    <div className="view-switch" aria-label="项目显示方式"><button aria-pressed={mode==='workflow'} onClick={()=>setMode('workflow')}>按工作流</button><button aria-pressed={mode==='results'} onClick={()=>setMode('results')}>按计算结果</button></div>
    {mode==='workflow'?<WorkflowBrowser tasks={tasks} attempts={attempts} token={token}/>:<AttemptsBrowser attempts={attempts} token={token}/>}
    {mode==='workflow'&&detached.length>0&&<Panel title="其他读取记录"><p className="notice">Task 列表与 Attempt 列表来自不同快照，请刷新核对。</p><AttemptRows attempts={detached} token={token}/></Panel>}
    <Panel title="项目元数据"><dl><FieldView label="创建时间" field={p.created_at} /><FieldView label="最近活动" field={p.last_activity_at} /><FieldView label="当前 Task 状态" field={p.current_task_state} /></dl></Panel>
  </>;
}
function AttemptPage({ attempt: a, token }: { attempt: Attempt; token: string }) {
  const unprojected = [...a.coverage.unprojected_observations.map(x => ({ id: x.observation_id, type: x.observation_type })), ...a.coverage.unprojected_results.map(x => ({ id: x.result_id, type: x.result_type }))];
  const workflow=<>
    <div className="detail-grid"><Panel title="状态与来源" eyebrow="01 / IDENTITY"><dl>
      <div className="field"><dt>Execution</dt><dd><Badge state={a.execution_state} /><small>来源 · Core.attempt_state（本地持久化状态）</small></dd></div>
      <div className="field"><dt>Task</dt><dd><code>{a.task_id}</code></dd></div>
      <div className="field"><dt>Workflow Run</dt><dd><code>{a.workflow_run_id}</code></dd></div>
      <div className="field"><dt>父 Attempt</dt><dd>{a.parent_attempt_id ?? '无'}</dd></div>
      <div className="field"><dt>创建时间</dt><dd className="muted">未记录<small>当前查询契约未提供此字段</small></dd></div>
      <FieldView label="Effect" field={a.effect} /></dl></Panel>
      <Panel title="输入与计算方法" eyebrow="02 / DECLARED INPUT"><dl>
        <FieldView label="输入文件引用" field={a.input} />
        {(['program', 'method', 'basis', 'charge', 'multiplicity'] as const).map(k => <FieldView key={k} label={{program:'计算程序',method:'方法',basis:'基组',charge:'电荷',multiplicity:'自旋多重度'}[k]} field={a.declared_science[k]} />)}
      </dl><details><summary>输入绑定与计划引用</summary><Value value={a.bound_plan} /></details></Panel>
      <Panel title="资源与调度" eyebrow="03 / EXECUTION EVIDENCE"><dl><FieldView label="实际资源" field={a.resources} /><FieldView label="Scheduler / Job" field={a.job} /><FieldView label="Collection" field={a.collection} /></dl></Panel>
      <Panel title="Observe" eyebrow="04 / PERSISTED OBSERVATIONS"><p className="muted">{a.observation.observation_count} 条持久化样本；不进行实时查询。</p><dl>{(['scheduler', 'process', 'gaussian'] as const).map(k => <FieldView key={k} label={k} field={a.observation[k]} />)}</dl></Panel>
    </div>
    <Panel title="原始日志引用" eyebrow="ARTIFACT REFERENCES"><dl><FieldView label="引用覆盖范围" field={a.logs_availability} /></dl>
      {a.logs.length === 0 ? <p className="muted">当前投影中没有可展示的日志引用。</p> : a.logs.map((log, i) => <div className="log" key={`${log.envelope_observation_id}-${i}`}><strong>{log.logical_name}</strong><span>{log.artifact_kind} · {log.size_bytes} bytes</span><code>SHA-256 {log.sha256}</code><dl><FieldView label="日志内容" field={log.content} /></dl></div>)}
    </Panel>
</>;
  return <><nav className="archive-breadcrumb" aria-label="计算位置"><a href="#/projects">项目</a> / <a href={link('projects',a.project_id)}>{a.project_id}</a> / <span>{a.task_id}</span> / 第 {a.ordinal} 次尝试</nav><a className="back" href={link('projects', a.project_id)}>← 返回项目</a><div className="page-heading"><div className="eyebrow">ATTEMPT DETAIL / 第 {a.ordinal} 次尝试</div><h1>计算记录 <Badge state={a.execution_state} /></h1><code>{a.attempt_id}</code></div>
    {a.coverage.status === 'unsupported-protocols-present' && <div className="notice warning">部分证据协议尚未支持。Core 状态保持原值；不可用字段不表示失败，也不表示结果不存在。</div>}
    <DetailWorkspace identity={a.attempt_id}>
    <ViewGroup view="evidence" id="workflow-evidence"><WorkflowAttemptEvidence id={a.attempt_id} project={a.project_id} task={a.task_id} run={a.workflow_run_id} token={token}/>{workflow}</ViewGroup>
    <ResultPanel attemptId={a.attempt_id} token={token} resultState={a.result_state}/>
    <DetailPanel kind="attempt" id={a.attempt_id} token={token}/>
    <ViewGroup view="evidence">{unprojected.length > 0 && <details className="panel"><summary>基础查询尚未投影的证据类型 · {unprojected.length}</summary>{unprojected.map((x, i) => <div className="log" key={i}><strong>{x.type}</strong><code>{x.id}</code></div>)}</details>}</ViewGroup>
    </DetailWorkspace>
  </>;
}
type Loaded = { kind: 'projects'; projects: Project[] } | { kind: 'project'; project: Project; tasks: Task[]; attempts: Attempt[] } | { kind: 'attempt'; attempt: Attempt };
function Workspace({ token, hash, revision, onProject }: { token: string; hash: string; revision: number;onProject?:(project:string)=>void }) {
  const [data, setData] = useState<Loaded | null>(null);
  const [error, setError] = useState('');
  const [time, setTime] = useState('');
  useEffect(() => {
    const controller = new AbortController(); const r = route(hash);
    async function load() {
      try {
        let result: Loaded;
        if (r.kind === 'invalid') throw new Error('not-found');
        if (r.kind === 'projects') result = { kind: 'projects', projects: (await read('/api/projects', 'projects', token, controller.signal)).items };
        else if (r.kind === 'project') {
          const base = `/api/projects/${encodeURIComponent(r.id)}`;
          const [project, tasks, attempts] = await Promise.all([read(base, 'project', token, controller.signal), read(`${base}/tasks`, 'tasks', token, controller.signal), read(`${base}/attempts`, 'attempts', token, controller.signal)]);
          result = { kind: 'project', project, tasks: tasks.items, attempts: attempts.items };
        } else result = { kind: 'attempt', attempt: await read(`/api/attempts/${encodeURIComponent(r.id)}`, 'attempt', token, controller.signal) };
        if (!controller.signal.aborted) { setData(result);if(result.kind==='attempt')onProject?.(result.attempt.project_id);setTime(new Date().toLocaleString('zh-CN')); }
      } catch (e) { if (!controller.signal.aborted) setError(e instanceof Error ? e.message : 'network-error'); }
    }
    void load(); return () => controller.abort();
  }, [hash, token, revision]);
  if (error) return <div className="error" role="alert"><h1>暂时无法展示记录</h1><p>{errors[error] ?? '读取失败。请检查本地服务后重试。'}</p><code>{error in errors ? error : 'request-failed'}</code><p><a href="#/projects">返回项目列表</a></p></div>;
  if (!data) return <div className="empty" role="status">正在读取本地记录…</div>;
  return <><div className="read-time">页面读取时间 · {time} <span>每个请求独立快照</span></div>{data.kind === 'projects' ? <ProjectLibrary token={token}/> : data.kind === 'project' ? <ProjectPage {...data} token={token} /> : <AttemptPage attempt={data.attempt} token={token} />}</>;
}
const localAccess = document.querySelector('meta[name="autog-access"]')?.getAttribute('content') === 'local-no-token';
function App() {
  const [token, setToken] = useState(''); const [draft, setDraft] = useState(''); const [invalid, setInvalid] = useState(false);
  const connected=localAccess||Boolean(token);
  const [hash, setHash] = useState(()=>canonicalRoute(location.hash)); const [revision, setRevision] = useState(0);
  useEffect(() => { const change = () => {const next=canonicalRoute(location.hash);if(next!==location.hash)history.replaceState(null,'',next);setHash(next);};change();addEventListener('hashchange',change);return()=>removeEventListener('hashchange',change);},[]);
  useRoutePosition(hash);
  const [boundProject,setBoundProject]=useState({path:'',id:''});
  const path=hash.split('?')[0],params=routeParams(hash),project=(boundProject.path===path?boundProject.id:'')||projectFromRoute(hash),tab=params.get('tab')??(path==='#/calculations'?'runs':path==='#/analysis'?'results':'library');
  const section=path==='#/settings'?'settings':path==='#/monitor'?'monitor':path==='#/analysis'?'analysis':path==='#/calculations'||path.startsWith('#/attempts/')?'calculations':'projects';
  useEffect(()=>{
    if(!connected||!['#/projects','#/analysis'].includes(hash.split('?')[0]))return;
    const c=new AbortController();let previous:string|null=null;let timer:ReturnType<typeof setTimeout>|undefined;
    async function checkLibrary(){try{const v=await requestJSON('/api/library',token,c.signal) as {schema?:string;profile_revision?:string};
      if(v.schema!=='autog-local-library/1'||typeof v.profile_revision!=='string')return;
      if(!c.signal.aborted){if(previous!==null&&previous!==v.profile_revision)setRevision(r=>r+1);previous=v.profile_revision;timer=setTimeout(checkLibrary,8000);}
    }catch{/* No optional library: retain ordinary read-only browsing. */}}
    void requestJSON('/api/capabilities',token,c.signal).then(v=>{if(!c.signal.aborted&&(v as {features?:{library?:boolean}}).features?.library===true)void checkLibrary();}).catch(()=>{});return()=>{c.abort();clearTimeout(timer);};
  },[connected,hash,token]);
  function connect(e: FormEvent) { e.preventDefault(); if (!/^[A-Za-z0-9_-]{32,256}$/.test(draft)) { setInvalid(true); return; } setToken(draft); setDraft(''); setInvalid(false); }
  return <div className="shell"><aside><a className="brand" href="#/projects"><span className="brand-mark">AG</span><span>Auto-Gaussian<small>RESEARCH WORKSPACE</small></span></a><div className="nav-label">RESEARCH / 研究空间</div><nav className="main-nav" aria-label="主导航">{[['projects','项目'],['calculations','计算'],['analysis','分析'],['monitor','监控']].map(([key,label])=><a key={key} className={'nav-item '+(section===key?'active':'')} aria-current={section===key?'page':undefined} href={routeLink('#/'+key,{project:['calculations','analysis'].includes(key)?project:undefined})}>{label}</a>)}</nav><nav className="settings-nav" aria-label="设置导航"><a className={'nav-item '+(section==='settings'?'active':'')} href="#/settings">⚙ 设置</a></nav><div className="side-foot"><span className="readonly-dot" /> LOCAL WORKSPACE<p>结果查看 · 任务管理</p><small>提交需核对具体任务</small></div></aside>
    <div className="workspace"><header><span>计算工作台 <span className="divider">/</span> 本地记录</span><div><a className="new-calculation" href={routeLink('#/calculations',{tab:'new',project})}>＋ 新建计算</a><span className="readonly-pill">计算结果只读</span>{connected && <><button onClick={() => setRevision(r => r + 1)}>刷新</button>{!localAccess&&<button onClick={() => { setToken(''); setDraft(''); }}>断开</button>}</>}</div></header>
    <ProjectContext hash={connected&&!path.startsWith('#/attempts/')?(project&&!projectFromRoute(hash)?routeLink(path,{project}):hash):''} token={token}/><main onClick={e=>{const a=(e.target as Element).closest('a');const dest=a?.getAttribute('href');if(dest&&/^#\/(archives|attempts)\//.test(dest))try{sessionStorage.setItem('autog-return:'+dest.split('?')[0],hash);}catch{}}}>{connected&&(path==='#/projects'||path.startsWith('#/native'))&&<nav className="section-tabs" aria-label="项目来源分区"><a href="#/projects" aria-current={path==='#/projects'?'page':undefined}>目录与归档</a><a href="#/native" aria-current={path.startsWith('#/native')?'page':undefined}>原生计算结果</a></nav>}{connected&&path==='#/calculations'&&<SectionTabs path={path} tab={tab==='new'?'drafts':tab} project={project} items={[['runs','运行与历史'],['drafts','草稿'],['queue','待处理任务']]}/>} {connected&&path==='#/analysis'&&<SectionTabs path={path} tab={tab} project={project} items={[['results','结果索引'],['compare','筛选与比较'],['irc','IRC'],['thermo','热化学']]}/>} {connected&&path==='#/settings'&&<SectionTabs path={path} tab={tab} items={[['library','数据源与本地库'],['capabilities','能力与版本']]}/>} {connected&&/^#\/(archives|attempts)\//.test(path)&&<ReturnToList path={path}/>} {!connected ? <section className="connect panel"><div className="eyebrow">CONNECT TO YOUR RECORDS</div><h1>连接本地只读数据</h1><p>使用本地服务的只读令牌，查看 Project → Task → Attempt。</p><form onSubmit={connect}><label htmlFor="token">只读访问令牌</label><input id="token" type="password" autoComplete="off" spellCheck={false} value={draft} onChange={e => setDraft(e.target.value)} required /><button className="primary" type="submit">连接数据源 →</button>{invalid && <p role="alert">请输入 32–256 位 URL-safe 令牌。</p>}</form><small>令牌只保存在当前页面内存中，刷新页面后需重新输入。</small></section> : path==='#/native'||path.startsWith('#/native/') ? <NativePanel key={hash+revision} token={token} hash={path}/> : path === '#/calculations' ? (tab==='new'?<DraftPanel key={project+':'+(params.get('record')??'new')} recordId={params.get('record')??undefined} project={project}/>:tab==='runs'?<WorkflowPanel key={project+revision} token={token} projectId={project}/>:<TaskCenter key={tab+revision} token={token} mode={tab==='queue'?'queue':'drafts'}/>) : path === '#/analysis' ? (tab==='compare'?<ScreeningPanel key={hash+revision} token={token} projectId={project} initialSelection={parseSelection(params.get('selection'))}/>:tab==='irc'||tab==='thermo'?<OfflineSciencePanel key={project} tool={tab}/>:<ProjectLibrary key={hash} token={token} revision={revision} results resultProject={project}/>) : path === '#/settings' ? (tab==='capabilities'?<CapabilitiesPanel token={token}/>:<LibraryPanel key={revision} token={token}/>) : path === '#/monitor' ? <MonitorPanel key={revision} token={token}/> : path.startsWith('#/history-projects/') ? <ProjectLibrary key={hash} token={token} revision={revision} id={decodeURIComponent(path.slice('#/history-projects/'.length))}/> : path==='#/projects'||path==='#/' ? <ProjectLibrary key={params.get('purpose')??'calculation'} token={token} revision={revision} testsOnly={params.get('purpose')==='test'} sourceFilter={params.get('source')??'all'}/> : path.startsWith('#/archives/') ? <ArchivePanel key={path+revision} token={token} fromProject={params.get('from')??undefined} id={path.slice('#/archives/'.length)}/> : <Workspace key={path+revision} token={token} hash={path} revision={revision} onProject={id=>setBoundProject({path,id})}/>}</main>
    <footer><span>Auto-Gaussian <b>·</b> Query v1</span><span>展示本地持久化事实，不代表实时调度状态或科学验收。</span></footer></div></div>;
}
createRoot(document.getElementById('root')!).render(<App />);
