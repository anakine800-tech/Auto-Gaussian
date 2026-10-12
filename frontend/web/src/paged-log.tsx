import {useEffect,useState} from 'react';
import {requestJSON} from './contract';
import {object} from './provenance';
import type {SourceTarget} from './provenance';
type Window={schema:string;kind:string;id:string;mode:string;sha256:string;size_bytes:number;logical_name:string;start:number;end:number;first_line:number;last_line:number;total_lines:number;text:string;segment_sha256:string;match_count:number|null};
const hash=async(b:Uint8Array)=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',b as BufferSource))).map(n=>n.toString(16).padStart(2,'0')).join('');
function encoded(v:string){return btoa(String.fromCharCode(...new TextEncoder().encode(v))).replaceAll('+','-').replaceAll('/','_').replaceAll('=','');}
export function PagedLog({kind,id,token,target}:{kind:string;id:string;token:string;target?:SourceTarget}){
 const [data,setData]=useState<Window|null>(null),[error,setError]=useState(false),[route,setRoute]=useState('log-window/0/120'),[query,setQuery]=useState('');
 const base=`/api/${kind==='archive'?'archives':'attempts'}/${encodeURIComponent(id)}`;
 useEffect(()=>{if(target)setRoute(`log-span/${target.span.start}/${target.span.end}/${target.span.sha256}`);},[target]);
 useEffect(()=>{const c=new AbortController();setError(false);setData(null);requestJSON(base+'/'+route,token,c.signal).then(async v=>{
  if(!object(v)||v.schema!=='auto-g16-log-window/1'||v.kind!==kind||v.id!==id||typeof v.text!=='string'||typeof v.logical_name!=='string'||typeof v.sha256!=='string'||!/^[a-f0-9]{64}$/.test(v.sha256)||!['start','end','first_line','last_line','total_lines','size_bytes'].every(k=>Number.isSafeInteger(v[k])&&Number(v[k])>=0)||Number(v.start)>=Number(v.end)||Number(v.end)>Number(v.size_bytes)||Number(v.last_line)>=Number(v.total_lines)||Number(v.first_line)>Number(v.last_line))throw Error('invalid-window');
  const b=new TextEncoder().encode(v.text);if(b.length!==Number(v.end)-Number(v.start)||await hash(b)!==v.segment_sha256)throw Error('invalid-bytes');
  if(route.startsWith('log-span/')&&target&&(v.start!==target.span.start||v.end!==target.span.end||v.sha256!==target.span.sha256||v.size_bytes!==target.span.size_bytes||v.logical_name!==target.span.logical_name))throw Error('source-mismatch');
  if(!c.signal.aborted)setData(v as unknown as Window);
 }).catch(()=>{if(!c.signal.aborted)setError(true);});return()=>c.abort();},[route,base,token,kind,id,target]);
 const find=(q:string,from:number|'last')=>{if(q)setRoute('log-find/'+encoded(q)+'/'+from);};
 return <div className="paged-log" data-testid="paged-log"><p>大日志分段读取 · 服务端每次核对完整文件 SHA-256，浏览器另核对返回片段。</p>{error?<p role="alert">日志片段不可读或来源不一致，已停止显示。</p>:!data?<p role="status">正在核对日志片段…</p>:<>
 <p>{data.logical_name} · 共 {data.total_lines} 行 · 第 {data.first_line+1}–{data.last_line+1} 行</p>
 {data.mode==='span'&&target&&<div data-testid="source-excerpt"><strong>{target.label}</strong><p>服务端已核对 SHA-256 · 字节 [{data.start}, {data.end}) · 第 {data.first_line+1}–{data.last_line+1} 行</p><pre>{data.text}</pre></div>}
 <div className="log-controls"><button disabled={data.first_line===0} onClick={()=>setRoute(`log-window/${Math.max(0,data.first_line-120)}/120`)}>上一段</button><button disabled={data.last_line+1>=data.total_lines} onClick={()=>setRoute(`log-window/${data.last_line+1}/120`)}>下一段</button><button onClick={()=>find('Normal termination','last')}>最后一次正常终止</button><button onClick={()=>find('Error termination','last')}>最后一次错误终止</button></div>
 <div className="log-controls"><label>搜索完整日志<input maxLength={128} aria-label="搜索完整日志" value={query} onChange={e=>setQuery(e.target.value)}/></label><button disabled={!query} onClick={()=>find(query,Math.min(data.last_line+1,data.total_lines-1))}>搜索下一处</button>{data.match_count!==null&&<span>{data.match_count} 个匹配行</span>}</div>
 <pre className="log-content" data-testid="raw-log">{data.text}</pre>
 </>}</div>;
}
