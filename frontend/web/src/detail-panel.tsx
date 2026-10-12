import {ActionDrawer} from './navigation';
import {ViewGroup} from './workspace-view';
import {ResultExport} from './result-export';
import {HistoricalReview} from './historical-review';
import {HistoricalWorkflow} from './historical-workflow';
import {ConditionsPanel} from './conditions-panel';
import {HistoryLinks} from './history-links';
import {PagedLog} from './paged-log';
import { useEffect, useMemo, useState } from 'react';
import {useDetailView} from './workspace-view';
import { requestJSON } from './contract';
import type { Json } from './contract';
import { MoleculeViewer, isGeometry } from './molecule-viewer';
import { ProvenanceCard, SourceLocation, frequencySources, locateSource } from './provenance';
import type { SourceTarget } from './provenance';
import { vibrationModes } from './vibration-contract';
import { ResultContext } from './result-context';
import { ScientificValidation } from './scientific-validation';
import type { VibrationMode } from './vibration-contract';

type ObjectValue = { [key: string]: Json };
type Field = { availability: 'available' | 'unavailable'; data: ObjectValue | null; reason: string | null; source: ObjectValue | null };
type Details = { result: Field; review: Field; execution: Field; context: unknown };
const obj = (v: unknown): v is Record<string, unknown> => v !== null && typeof v === 'object' && !Array.isArray(v);
const field = (v: unknown): v is Field => obj(v) && (v.availability === 'available' ? obj(v.data) && obj(v.source) && v.reason === null : v.availability === 'unavailable' && v.data === null && v.source === null && typeof v.reason === 'string');
function check(value: unknown, kind: string, id: string): Record<string, unknown> {
  if (!obj(value) || value.schema !== 'auto-g16-detail-evidence/1' || value.kind !== kind || value.id !== id) throw new Error('contract-mismatch');
  return value;
}
function Source({ field: f }: { field: Field }) {
  return f.source && <details><summary>字段来源与哈希</summary><pre>{JSON.stringify(f.source, null, 2)}</pre></details>;
}
function Fields({ value }: { value: Json }) {
  if (value === null) return <p className="muted">未记录</p>;
  if (!obj(value)) return <pre>{JSON.stringify(value, null, 2)}</pre>;
  return <dl>{Object.entries(value).map(([k,v]) => <div className="field" key={k}><dt>{k}</dt><dd>{v === null ? '未记录' : typeof v === 'object' ? <pre>{JSON.stringify(v, null, 2)}</pre> : String(v)}</dd></div>)}</dl>;
}

const thermoLabels: Record<string,string> = {
 zero_point_correction_hartree:'零点能校正', thermal_correction_energy_hartree:'热能校正',
 thermal_correction_enthalpy_hartree:'焓校正', thermal_correction_gibbs_hartree:'Gibbs 自由能校正',
 sum_electronic_zpe_hartree:'电子能 + 零点能', sum_electronic_energy_hartree:'电子能 + 热能',
 sum_electronic_enthalpy_hartree:'电子能 + 焓校正', sum_electronic_gibbs_hartree:'电子能 + Gibbs 校正',
};
function ReviewSummary({data:d}:{data:ObjectValue}) {
 return <><HistoricalReview data={d}/>
 <p>这是已保存的历史报告，未重新运行验证或授予验收。</p><dl><div className="field"><dt>选中频率 / cm⁻¹</dt><dd>{Array.isArray(d.selected_frequencies_cm1)?d.selected_frequencies_cm1.join(' · '):'未记录'}</dd></div><div className="field"><dt>验证结果标识</dt><dd><code>{String(d.outcome_id??'未记录')}</code></dd></div></dl>
 <details><summary>历史报告原始字段</summary><Fields value={d}/></details></>;
}
function ExecutionSummary({data:d}:{data:ObjectValue}) {
 const resources=obj(d.resources)?d.resources:{};const scheduler=obj(d.scheduler)?d.scheduler:{};const receipts=Array.isArray(d.receipts)?d.receipts.filter((v): v is ObjectValue => obj(v)):[];
 const names:Record<string,string>={cores:'请求核数',nprocshared:'声明线程数',memory_mb:'请求内存 / MB',memory:'声明内存',walltime_seconds:'请求时限 / 秒',queue:'队列'};
 return <><div className="resource-cards">{Object.entries(resources).map(([k,v])=><div key={k}><span>{names[k]??k}</span><strong>{typeof v==='object'?JSON.stringify(v):String(v)}</strong></div>)}</div>
 {Object.keys(scheduler).length>0&&<dl>{Object.entries(scheduler).map(([k,v])=><div className="field" key={k}><dt>{{type:'历史调度器',queue:'历史队列',resources:'调度资源声明',job_id:'历史 Job ID',submitted_at_server:'记录提交时间',started_at_server:'记录开始时间',last_observed_state:'最后记录的调度状态'}[k]??k}</dt><dd>{String(v??'未记录')}</dd></div>)}</dl>}
 {receipts.length>0&&<ol className="receipt-timeline">{receipts.map((r,i)=><li key={i}><span className="step-index">{String(r.sequence??i+1)}</span><div><strong>{{'local-workspace':'本地工作目录','remote-workspace':'远程工作目录','input-transfer':'输入传输',submission:'提交回执'}[String(r.kind)]??String(r.kind)}</strong><small>{String(r.state)}{r.job_id?` · Job ${String(r.job_id)}`:''}</small><code>{String(r.receipt_id)}</code></div></li>)}</ol>}
 <details><summary>资源与 Job 原始字段</summary><Fields value={d}/></details></>;
}

function Results({ field: f, review, onLocate,kind,id,token,context }: { field: Field; review: Field; onLocate:(target:SourceTarget)=>void;kind:'attempt'|'archive';id:string;token:string;context:unknown }) {
  const {view}=useDetailView();
  const [requested,setRequested]=useState(false),[modes,setModes]=useState<VibrationMode[]|null>(null),[mode,setMode]=useState<VibrationMode|undefined>(),[modeStatus,setModeStatus]=useState('idle');
  useEffect(()=>{if(view!=='science')setMode(undefined);},[view]);
  useEffect(()=>{if(!requested)return;const controller=new AbortController();setModeStatus('loading');requestJSON(`/api/${kind==='attempt'?'attempts':'archives'}/${encodeURIComponent(id)}/vibrations`,token,controller.signal).then(dto=>{const found=vibrationModes(dto,kind,id,f.source,f.data);if(!controller.signal.aborted){setModes(found);setModeStatus(found?'available':'unavailable');}}).catch(()=>{if(!controller.signal.aborted){setModes(null);setMode(undefined);setModeStatus('error');}});return()=>controller.abort();},[requested,kind,id,token,f]);
  const play=(m:VibrationMode)=>{setMode({...m});document.querySelector('.molecule-section')?.scrollIntoView({block:'start'});};
  const validation=<ScientificValidation token={token} activeMode={mode} data={f.data} source={f.source} review={review.data} kind={kind} id={id} modes={modes} modeStatus={modeStatus} onRead={()=>setRequested(true)} onPlay={play} onLocate={onLocate}/>;
  const provenanceContext=kind==='archive'?null:<ResultContext view="science" value={context} kind={kind} id={id} source={f.source}/>;
  if (!f.data) return <>{provenanceContext}<p className="muted">此记录尚无合格的完整解析结果。</p>{validation}</>;
  const data = f.data;
  const frequencies = data.frequencies_cm1 as number[];
  const thermo = data.thermochemistry as Record<string, { value_hartree: number; source_span?:unknown }>;
  const geometry = data.last_geometry as null | { atoms: { center: number; atomic_number: number; x: number; y: number; z: number }[] };
  const parent=f.source?.artifact;
  const spans=frequencySources(frequencies,data.frequency_blocks,parent);
  const modePanel=<section className="frequency-dock" aria-label="频率与振动"><div className="frequency-heading"><h4>频率与振动 <small>cm⁻¹</small></h4><span>{frequencies.length ? `${frequencies.length} 个模式 · ${frequencies.filter(v=>v<0).length} 个虚频` : '频率未记录'}</span></div><div className="vibration-loader">{modeStatus==='idle'?<button onClick={()=>setRequested(true)} disabled={!frequencies.length}>读取振动模式</button>:<p role="status">{{loading:'正在核对模式来源…',available:`已接入 ${modes?.length??0} 个模式`,unavailable:'暂无绑定的振动位移数据，无法播放。',error:'模式读取失败或来源不一致，已禁止播放。'}[modeStatus]}</p>}</div>{frequencies.length?<div className="table-scroll frequency-scroll" tabIndex={0} aria-label="全部频率，可滚动"><table data-testid="full-frequencies"><thead><tr><th>模式</th><th>频率</th><th>播放</th><th>来源</th></tr></thead><tbody>{frequencies.map((v,i)=><tr key={i} className={mode?.mode_number===i+1?'active-mode':''}><td>{i+1}</td><td className={v<0?'negative-frequency':''}>{v}{v<0?' 虚':''}</td><td>{modes?.[i]?<button aria-label={`播放模式 ${i+1}`} aria-pressed={mode?.mode_number===i+1} onClick={()=>play(modes[i])}>▶ {v<0?'虚频':'播放'}</button>:<span className="source-missing">{modeStatus==='idle'?'待读取':'不可用'}</span>}</td><td><SourceLocation span={spans[i]} parent={parent} label={`频率 ${i+1}（${v} cm⁻¹）`} onLocate={onLocate}/></td></tr>)}</tbody></table></div>:<p>未记录频率，虚频数量未知。</p>}<p className="micro muted frequency-note">虚频方向需人工确认；播放不代表接受为目标 TS。</p></section>;
  return <>{provenanceContext}<div className="thermo-overview" aria-label="关键热化学结果"><span>结果汇总 · Hartree</span>{['sum_electronic_gibbs_hartree','sum_electronic_enthalpy_hartree','sum_electronic_zpe_hartree'].map(k=><div key={k}><small>{{sum_electronic_gibbs_hartree:'G · 电子能 + Gibbs 校正',sum_electronic_enthalpy_hartree:'H · 电子能 + 焓校正',sum_electronic_zpe_hartree:'E + ZPE'}[k]}</small><strong>{thermo[k]?.value_hartree??'未记录'}</strong></div>)}<small>按已保存结果汇总，未绑定所选日志步骤</small></div>
  <MoleculeViewer modePanel={modePanel} scientificPanel={validation} vibration={mode} onClearVibration={()=>setMode(undefined)} last={geometry} review={review.data?.selected_final_geometry} renderSource={(which,g)=><div className="geometry-source">{mode&&which==='last'&&<SourceLocation span={mode.source_span} parent={parent} label={`振动模式 ${mode.mode_number}`} onLocate={onLocate}/>}<strong>{which==='review'?'Review 选中坐标来源':'最后记录坐标来源'}</strong><SourceLocation span={obj(g)?g.source_span:null} parent={parent} label={which==='review'?'Review 选中坐标':'最后记录坐标'} onLocate={onLocate}/></div>}/>
  <div className="supplementary-results"><details className="thermochemistry-details"><summary>完整热化学与校正项 · Hartree</summary><p className="muted">展示日志中已解析的数值，不替代计算条件审查或科学验收。</p>{Object.keys(thermo).length?<dl data-testid="full-thermochemistry">{Object.entries(thermo).map(([k,v])=><div className="field" key={k}><dt>{thermoLabels[k]??k}<small>{k}</small></dt><dd>{v.value_hartree}<SourceLocation span={v.source_span} parent={parent} label={thermoLabels[k]??k} onLocate={onLocate}/></dd></div>)}</dl>:<p>未记录热化学数据。</p>}</details><details className="coordinate-table"><summary>最后记录的结构 / Å · 坐标表</summary><p className="muted">取日志最后一个已解析坐标块。它不自动等同于 Review 选中的结构。</p>{geometry?<div className="table-scroll"><table data-testid="full-geometry"><thead><tr>{['Center','原子序数','X','Y','Z'].map(k=><th key={k}>{k}</th>)}</tr></thead><tbody>{geometry.atoms.map(a=><tr key={a.center}><td>{a.center}</td><td>{a.atomic_number}</td><td>{a.x}</td><td>{a.y}</td><td>{a.z}</td></tr>)}</tbody></table></div>:<p>未记录结构。</p>}</details></div></>;

}
function validResult(f: Field) {
  if (!f.data) return true;
  const d=f.data;
  return Array.isArray(d.frequencies_cm1) && d.frequencies_cm1.every(v=>typeof v==='number'&&Number.isFinite(v)) && obj(d.thermochemistry) &&
    Object.values(d.thermochemistry).every(v=>obj(v)&&typeof v.value_hartree==='number'&&Number.isFinite(v.value_hartree)) &&
    (d.last_geometry===null || isGeometry(d.last_geometry));
}
export function parseDetails(value:unknown,kind:string,id:string):Details {
 const d=check(value,kind,id);if(!field(d.result)||!field(d.review)||!field(d.execution)||!validResult(d.result))throw new Error('contract-mismatch');
 return {result:d.result,review:d.review,execution:d.execution,context:d.context};
}
export function DetailPanel({ kind, id, token }: { kind: 'attempt' | 'archive'; id: string; token: string }) {
  const {view,showEvidence}=useDetailView();
  const [target,setTarget]=useState<SourceTarget|null>(null);
  const onLocate=(next:SourceTarget)=>{setTarget({...next});showEvidence('raw-log-section');};
  const [data,setData]=useState<Details|null>(null); const [error,setError]=useState(false);
  const base=`/api/${kind==='attempt'?'attempts':'archives'}/${encodeURIComponent(id)}`;
  useEffect(()=>{const c=new AbortController();setData(null);setError(false);setTarget(null);
    requestJSON(base+'/details',token,c.signal).then(value=>{const d=parseDetails(value,kind,id);if(!c.signal.aborted)setData(d);}).catch(()=>{if(!c.signal.aborted)setError(true);});return()=>c.abort();
  },[base,kind,id,token]);
  return <div className="detail-evidence">{error&&<p role="alert">补充证据读取失败或绑定不一致，已停止展示。</p>}
    {data&&!error&&<div className="detail-actions"><ActionDrawer label="导出结果"><ResultExport kind={kind} id={id} detail={data} mode="export"/></ActionDrawer><ActionDrawer label="补充来源备注"><ResultExport kind={kind} id={id} detail={data} mode="notes"/></ActionDrawer></div>}
    <ViewGroup view="science"><section className="panel"><h2>结果与待核对事项</h2>{!data&&!error?<p role="status">正在读取补充证据…</p>:data&&<><div className="detail-overview-grid"><div><small>G · 电子能 + Gibbs 校正 / Hartree</small><strong>{String(obj(data.result.data?.thermochemistry)&&obj(data.result.data.thermochemistry.sum_electronic_gibbs_hartree)?data.result.data.thermochemistry.sum_electronic_gibbs_hartree.value_hartree:'未记录')}</strong></div><div><small>科学复核 · 独立于执行状态</small><HistoricalReview data={data.review.data}/></div><div><small>结果证据</small><strong>{data.result.availability==='available'?'已读取保存结果':'不可用'}</strong><p>{data.result.reason??'结构与频率见下方，原始来源见“来源与记录”。'}</p></div></div></>}{kind==='archive'&&<ConditionsPanel id={id} token={token} onLocate={onLocate}/>}</section></ViewGroup>
    <ViewGroup view="science"><section className="panel science-detail"><h2 className="visually-quiet">完整结果与历史证据</h2>{data&&!error?<Results context={data.context} field={data.result} review={data.review} onLocate={onLocate} kind={kind} id={id} token={token}/>:!error&&<p role="status">正在读取补充证据…</p>}</section></ViewGroup>
    <ViewGroup view="provenance"><div className="evidence-panels" data-testid="evidence-panels">{data&&<><section className="panel evidence-provenance" id="evidence-provenance"><ResultContext view="evidence" value={data.context} kind={kind} id={id} source={data.result.source}/><ProvenanceCard source={data.result.source} reviewSource={data.review.source}/><Source field={data.result}/><details><summary>完整结果字段与源字节区间</summary><pre>{JSON.stringify(data.result.data,null,2)}</pre></details></section><section className="panel" id="scientific-review" data-testid="review-evidence"><h2>Scientific Validation / 历史 Review</h2>{data.review.data?<><ReviewSummary data={data.review.data}/><Source field={data.review}/></>:<p>尚无绑定到此结果的历史科学验证和 Review 报告。</p>}</section></>}{kind==='archive'&&<HistoryLinks id={id} token={token}/>}</div></ViewGroup>
    <ViewGroup view="evidence"><CalculationAnalysis active={view==='evidence'} key={`${kind}:${id}`} kind={kind} id={id} token={token} onLocate={onLocate}/>{data&&<section className="panel" id="execution-evidence" data-testid="execution-evidence"><h2>资源请求与历史 Job</h2><p className="muted">资源为提交时请求或历史声明，不代表实测分配与消耗。Job 回执也不代表当前调度状态。</p>{data.execution.data?<><ExecutionSummary data={data.execution.data}/><Source field={data.execution}/></>:<p>暂无合格的执行来源。</p>}</section>}{kind==='archive'&&<HistoricalWorkflow id={id} token={token}/>}<LogViewer key={`${kind}:${id}:${token}`} base={base} kind={kind} id={id} token={token} target={target??undefined}/></ViewGroup>
  </div>;
}

function LogViewer({base,kind,id,token,target}:{base:string;kind:string;id:string;token:string;target:SourceTarget|null|undefined}) {
  const [requested,setRequested]=useState(false);const [data,setData]=useState<Field|null>(null);const [error,setError]=useState(false);
  const [located,setLocated]=useState<{firstLine:number;lastLine:number;excerpt:string;target:SourceTarget}|null>(null);const [locateError,setLocateError]=useState(false);
  useEffect(()=>{if(target){setRequested(true);document.getElementById('raw-log-section')?.scrollIntoView({block:'start'});}},[target]);
  useEffect(()=>{let active=true;setLocated(null);setLocateError(false);if(target&&data?.data&&typeof data.data.text==='string'){locateSource(data.data.text,data.source,data.data.logical_name,target).then(found=>{if(active){setLocated({...found,target});setSelected(found.firstLine);setCursor(Math.max(0,found.firstLine-4));}}).catch(()=>{if(active)setLocateError(true);});}return()=>{active=false;};},[target,data]);
  const [search,setSearch]=useState('');const [cursor,setCursor]=useState(0);const [selected,setSelected]=useState(0);
  useEffect(()=>{if(!requested)return;const c=new AbortController();requestJSON(base+'/log',token,c.signal).then(v=>{const d=check(v,kind,id);if(!field(d.log)||d.log.data&&(typeof d.log.data.text!=='string'||typeof d.log.data.logical_name!=='string'))throw new Error('contract-mismatch');if(!c.signal.aborted)setData(d.log);}).catch(()=>{if(!c.signal.aborted)setError(true);});return()=>c.abort();},[requested,base,kind,id,token]);
  const lines=useMemo(()=>typeof data?.data?.text==='string'?data.data.text.split(/\r?\n/):[],[data]);
  const matches=useMemo(()=>search?lines.flatMap((line,i)=>line.toLowerCase().includes(search.toLowerCase())?[i]:[]):[],[lines,search]);
  function jump(marker:string){for(let i=lines.length-1;i>=0;i--)if(lines[i].includes(marker)){setSelected(i);setCursor(Math.max(0,i-20));return;}}
  const next=()=>{const i=matches.find(i=>i>selected)??matches[0];if(i!==undefined){setSelected(i);setCursor(Math.max(0,i-20));}};
  return <section className="panel" id="raw-log-section" aria-label="原始日志只读查看"><h2>原始日志只读查看</h2>{!requested ? <button onClick={()=>setRequested(true)}>读取已归档日志</button> : error ? <p role="alert">日志不可读或哈希不匹配，已停止展示。</p> : !data ? <p role="status">正在核对日志…</p> : !data.data&&data.reason==='log-exceeds-inline-limit' ? <PagedLog kind={kind} id={id} token={token} target={target ?? undefined}/> : !data.data ? <p>{data.reason==='log-exceeds-inline-limit'?'原始日志已归档，超过当前 2 MiB 网页全文查看上限；结果摘要、结构和频率仍可查看。完整原件保存在本地结果目录。':'尚未连接与此结果匹配的本地日志。'}</p> : <>
    <p>{String(data.data.logical_name)} · {String(data.data.line_count)} 行</p><Source field={data}/>
    {target&&<div className="source-excerpt" data-testid="source-excerpt"><strong>{target.label}</strong>{locateError?<p role="alert">来源定位失败：日志与结果绑定不一致，或字节区间无效。</p>:located?.target===target?<><p>已核对 SHA-256 · 字节 [{target.span.start}, {target.span.end}) · 第 {located.firstLine+1}–{located.lastLine+1} 行</p><pre>{located.excerpt}</pre></>:<p role="status">正在核对来源字节…</p>}</div>}
    <div className="log-controls"><label>搜索日志<input aria-label="搜索日志" value={search} onChange={e=>{setSearch(e.target.value);setSelected(-1);}}/></label><button onClick={next} disabled={!matches.length}>下一个匹配</button><span>{matches.length} 个匹配行</span></div>
    <div className="log-controls"><button onClick={()=>jump('Normal termination')}>最后一次正常终止</button><button onClick={()=>jump('Error termination')}>最后一次错误终止</button><button onClick={()=>setCursor(Math.max(0,cursor-120))} disabled={cursor===0}>上一段</button><button onClick={()=>setCursor(Math.min(lines.length-1,cursor+120))} disabled={cursor+120>=lines.length}>下一段</button></div>
    <p className="muted">显示第 {cursor+1}–{Math.min(cursor+120,lines.length)} 行；搜索覆盖完整已读取日志。</p>
    <pre className="log-content" data-testid="raw-log">{lines.slice(cursor,cursor+120).map((line,i)=><span className={cursor+i===selected?'selected-line':''} key={cursor+i}>{String(cursor+i+1).padStart(6,' ')}  {line}{'\n'}</span>)}</pre>
  </>}</section>;
}
import {CalculationAnalysis} from './calculation-analysis';
