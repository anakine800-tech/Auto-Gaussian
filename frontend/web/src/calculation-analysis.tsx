import {ActionDrawer} from './navigation';
import {RepairPanel} from './draft-panel';
import {download,exportSVG} from './local-records';
import {useEffect,useState} from 'react';
import {requestJSON} from './contract';
import {MoleculeViewer,isGeometry} from './molecule-viewer';
import type {Geometry} from './molecule-viewer';
import {artifact,boundSpan,object,SourceLocation} from './provenance';
import type {SourceSpan,SourceTarget} from './provenance';

type Metric={label:string;value:number;threshold:number;converged:boolean;source_span:SourceSpan};
type Point={index:number;printed_step:number|null;energy:{energy_hartree:number;energy_kind:string;source_span:SourceSpan};geometry:Geometry;metrics:Metric[];source_span:SourceSpan};
type Segment={index:number;reason:string;points:Point[];scf_observations:Point['energy'][]};
export type Analysis={source:SourceSpan;segments:Segment[];errors:{code:string;title:string;suggestion:string;excerpt:string;source_span:SourceSpan;line:number;segment:number}[]};
export function parseAnalysis(v:unknown,kind:string,id:string):Analysis|null {
 if(!object(v)||v.schema!=='autog-calculation-analysis/1'||v.kind!==kind||v.id!==id)throw Error('contract');
 if(v.availability==='unavailable'&&v.data===null)return null;
 const d=v.data;if(v.availability!=='available'||!object(d)||d.schema!=='autog-calculation-analysis/1'||!artifact(d.source)||!Array.isArray(d.segments)||!Array.isArray(d.errors))throw Error('contract');
 const finite=(x:unknown):x is number=>typeof x==='number'&&Number.isFinite(x);
 for(const s of d.segments){if(!object(s)||!Number.isSafeInteger(s.index)||!Array.isArray(s.points)||!Array.isArray(s.scf_observations))throw Error('segment');
  for(const e of s.scf_observations)if(!object(e)||!finite(e.energy_hartree)||!boundSpan(e.source_span,d.source))throw Error('energy');
  for(const p of s.points){if(!object(p)||!Number.isSafeInteger(p.index)||!object(p.energy)||!finite(p.energy.energy_hartree)||typeof p.energy.energy_kind!=='string'||!boundSpan(p.energy.source_span,d.source)||!isGeometry(p.geometry)||!boundSpan(p.geometry.source_span,d.source)||!boundSpan(p.source_span,d.source)||!Array.isArray(p.metrics)||p.metrics.length!==4||!p.metrics.every(m=>object(m)&&typeof m.label==='string'&&finite(m.value)&&finite(m.threshold)&&m.threshold>0&&typeof m.converged==='boolean'&&boundSpan(m.source_span,d.source)))throw Error('point');}
 }
 if(!d.errors.every(e=>object(e)&&['code','title','suggestion','excerpt'].every(k=>typeof e[k]==='string')&&Number.isSafeInteger(e.line)&&boundSpan(e.source_span,d.source)))throw Error('error');
 return d as unknown as Analysis;
}
function Plot({values,selected,onSelect,label,threshold=false}:{values:number[];selected:number;onSelect:(i:number)=>void;label:string;threshold?:boolean}){
 const min=Math.min(...values,threshold?1:Infinity),max=Math.max(...values,threshold?1:-Infinity),range=max-min||1;
 const xy=(v:number,i:number)=>[70+i*650/Math.max(1,values.length-1),185-(v-min)/range*145];
 return <svg className="optimization-plot" viewBox="0 0 760 230" role="img" aria-label={label}>
  <text x="20" y="20">{label}</text><text x="2" y="45" fontSize="9">{threshold?max.toPrecision(4):max.toFixed(6)}</text><text x="2" y="185" fontSize="9">{threshold?min.toPrecision(4):min.toFixed(6)}</text>
  <path className="plot-axis" d="M70 35 V190 H735"/>
  {threshold&&<path className="plot-threshold" d={`M70 ${xy(1,0)[1]} H735`}/>}
  <polyline className="plot-line" points={values.map((v,i)=>xy(v,i).join(',')).join(' ')}/>
  {values.map((v,i)=>{const [x,y]=xy(v,i);return <circle key={i} cx={x} cy={y} r={i===selected?6:4} className={i===selected?'plot-point selected':'plot-point'} role="button" tabIndex={0} aria-label={`${label} 第 ${i+1} 步 ${v}`} onClick={()=>onSelect(i)} onKeyDown={e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();onSelect(i);}}}><title>点 {i+1}: {v}</title></circle>;})}
  <text x="70" y="215">1</text><text x="680" y="215">{values.length} 步</text>
 </svg>;
}
export function CalculationAnalysis({kind,id,token,onLocate,active=true}:{active?:boolean;kind:'attempt'|'archive';id:string;token:string;onLocate:(target:SourceTarget)=>void}){
 const [requested,setRequested]=useState(false),[data,setData]=useState<Analysis|null>(null),[loaded,setLoaded]=useState(false),[error,setError]=useState(false);
 const [segment,setSegment]=useState(0),[step,setStep]=useState(0),[metric,setMetric]=useState(0),[playing,setPlaying]=useState(false);
 useEffect(()=>{if(!requested)return;const c=new AbortController();setLoaded(false);setError(false);requestJSON(`/api/${kind==='attempt'?'attempts':'archives'}/${encodeURIComponent(id)}/analysis`,token,c.signal).then(v=>{setData(parseAnalysis(v,kind,id));setLoaded(true);}).catch(()=>{if(!c.signal.aborted)setError(true);});return()=>c.abort();},[requested,kind,id,token]);
 useEffect(()=>{if(!active)setPlaying(false);},[active]);
 const segments=data?.segments.filter(s=>s.points.length)??[],points=segments[segment]?.points??[],p=points[step];
 useEffect(()=>{if(!playing||points.length<2)return;const tick=window.setInterval(()=>setStep(n=>(n+1)%points.length),700);const stop=()=>{if(document.hidden)setPlaying(false);};document.addEventListener('visibilitychange',stop);return()=>{clearInterval(tick);document.removeEventListener('visibilitychange',stop);};},[playing,points.length]);
 return <section className="panel calculation-analysis" data-testid="calculation-analysis"><h2>报错与优化轨迹</h2>{!requested?<button onClick={()=>setRequested(true)}>读取报错与优化轨迹</button>:error?<p role="alert">轨迹来源不一致或读取失败。</p>:!loaded?<p role="status">读取已准备的轨迹…</p>:!data?<p>尚未准备该日志的轨迹数据。日志及最终结果仍可查看。</p>:<>
  <div className="error-diagnostics"><h3>日志诊断</h3>{!data.errors.length?<p>未识别到支持的错误标记；不据此认定计算成功。</p>:data.errors.map((e,i)=><article className="notice warning" key={i}><strong>{e.title}</strong><p>{e.excerpt}</p><p>{e.suggestion}</p><SourceLocation span={e.source_span} parent={data.source} label={`报错 · 第 ${e.line} 行`} onLocate={onLocate}/></article>)}</div>
  {p?<><div className="analysis-controls"><label>计算分段<select value={segment} onChange={e=>{setSegment(Number(e.target.value));setStep(0);setPlaying(false);}}>{segments.map((s,i)=><option value={i} key={s.index}>第 {s.index} 段 · {s.points.length} 步</option>)}</select></label><label>优化步骤<select value={step} onChange={e=>setStep(Number(e.target.value))}>{points.map((v,i)=><option value={i} key={i}>点 {i+1}{v.printed_step===null?'':` · 日志步号 ${v.printed_step}`}</option>)}</select></label><button onClick={()=>setPlaying(v=>!v)} disabled={points.length<2}>{playing?'暂停轨迹':'播放轨迹'}</button></div>
  <p>第 {step+1} 个完整优化周期 · {p.energy.energy_kind} = <strong>{p.energy.energy_hartree} Hartree</strong></p>
  <div className="analysis-workspace"><div className="analysis-structure"><MoleculeViewer last={p.geometry} review={null} frameLabel="当前优化步结构"/></div><div className="analysis-plots"><Plot values={points.map(x=>x.energy.energy_hartree)} selected={step} onSelect={setStep} label="优化能量 / Hartree"/><div><label>收敛指标<select value={metric} onChange={e=>setMetric(Number(e.target.value))}>{p.metrics.map((m,i)=><option key={m.label} value={i}>{m.label}</option>)}</select></label><Plot values={points.map(x=>x.metrics[metric].value/x.metrics[metric].threshold)} selected={step} onSelect={setStep} label="指标 / 阈值（虚线 = 1）" threshold/></div></div></div>
  <div className="table-scroll"><table><thead><tr><th>收敛指标</th><th>值</th><th>阈值</th><th>日志结论</th></tr></thead><tbody>{p.metrics.map(m=><tr key={m.label}><td>{m.label}</td><td>{m.value}</td><td>{m.threshold}</td><td>{m.converged?'YES':'NO'}</td></tr>)}</tbody></table></div>
  <SourceLocation span={p.energy.source_span} parent={data.source} label="该步能量来源" onLocate={onLocate}/><SourceLocation span={p.source_span} parent={data.source} label="该步收敛表来源" onLocate={onLocate}/>
  <button onClick={e=>{const svg=e.currentTarget.closest(".calculation-analysis")?.querySelector("svg.optimization-plot");if(svg)exportSVG(svg,"optimization.svg");}}>导出优化曲线 SVG</button><p className="muted">仅连接同一分段内完整的坐标、SCF 能量和收敛表。优化轨迹不是势能扫描或反应路径；曲线下降不等于科学验收。</p>
  </>:<p>未找到可配对的完整优化周期。保留了 {data.segments.reduce((n,s)=>n+s.scf_observations.length,0)} 条 SCF 观测，不将它们冒充优化步骤。</p>}
 <ActionDrawer label="生成修复草稿"><RepairPanel source={{name:data.source.logical_name,sha256:data.source.sha256,kind,id}} geometry={points.at(-1)?.geometry}/></ActionDrawer></>}</section>;
}
