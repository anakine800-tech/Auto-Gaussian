import type { ReactNode } from 'react';
export const object = (v:unknown):v is Record<string,unknown> => v!==null&&typeof v==='object'&&!Array.isArray(v);
export type Artifact={artifact_kind:string;envelope_observation_id:string;logical_name:string;sha256:string;size_bytes:number};
export type SourceSpan=Artifact&{start:number;end:number};
export type SourceTarget={label:string;span:SourceSpan};
export function artifact(v:unknown):v is Artifact {
 return object(v)&&['artifact_kind','envelope_observation_id','logical_name'].every(k=>typeof v[k]==='string'&&Boolean(v[k]))&&typeof v.sha256==='string'&&/^[a-f0-9]{64}$/.test(v.sha256)&&Number.isSafeInteger(v.size_bytes)&&Number(v.size_bytes)>0;
}
export function boundSpan(v:unknown,parent:unknown):v is SourceSpan {
 return artifact(parent)&&artifact(v)&&['artifact_kind','envelope_observation_id','logical_name','sha256','size_bytes'].every(k=>v[k as keyof Artifact]===parent[k as keyof Artifact])&&'start' in v&&'end' in v&&Number.isSafeInteger(v.start)&&Number.isSafeInteger(v.end)&&Number(v.start)>=0&&Number(v.start)<Number(v.end)&&Number(v.end)<=parent.size_bytes;
}
export function frequencySources(values:number[],blocks:unknown,parent:unknown):(SourceSpan|null)[] {
 const missing=values.map(()=>null);if(!Array.isArray(blocks))return missing;
 const flat:number[]=[],spans:(SourceSpan|null)[]=[];
 for(const b of blocks){if(!object(b)||!Array.isArray(b['frequencies_cm-1']))return missing;for(const v of b['frequencies_cm-1']){if(typeof v!=='number'||!Number.isFinite(v))return missing;flat.push(v);spans.push(boundSpan(b.source_span,parent)?b.source_span:null);}}
 return flat.length===values.length&&flat.every((v,i)=>v===values[i])?spans:missing;
}
export function SourceLocation({span,parent,label,onLocate}:{span:unknown;parent:unknown;label:string;onLocate:(target:SourceTarget)=>void}) {
 return boundSpan(span,parent)?<span className="source-location"><span>字节 [{span.start}, {span.end})</span><button className="source-link" onClick={()=>onLocate({label,span})} aria-label={`定位原日志：${label}`}>定位原日志 ↗</button></span>:<span className="source-missing">来源区间未绑定</span>;
}
export function ProvenanceCard({source,reviewSource}:{source:unknown;reviewSource:unknown}) {
 const s=object(source)?source:{},a=artifact(s.artifact)?s.artifact:null,r=object(reviewSource)?reviewSource:{};
 const row=(name:string,value:unknown):ReactNode=><div className="field" key={name}><dt>{name}</dt><dd><code>{typeof value==='string'||typeof value==='number'?String(value):'未记录'}</code></dd></div>;
 return <section className="provenance-card" aria-label="结果来源" data-testid="result-provenance"><div className="section-heading"><div><div className="eyebrow">RESULT PROVENANCE</div><h3>结果来源</h3></div><span className="badge">{a?'已记录解析来源':'来源信息不足'}</span></div>
 <p className="muted">此结果来自已保存的解析记录。定位日志时另行核对文件 SHA-256、大小与字节区间；来源一致不等于科学验收。</p>
 <dl className="provenance-grid">{row('Result ID',s.result_id)}{row('解析器',s.parser)}{row('解析器版本',s.parser_version)}{row('日志文件',a?.logical_name)}{row('日志大小 / bytes',a?.size_bytes)}{row('Output envelope',a?.envelope_observation_id)}{row('日志 SHA-256',a?.sha256)}{row('历史 ReviewBundle',r.review_bundle_id)}{row('Review 报告 SHA-256',r.sha256)}</dl>
 <div className="evidence-levels"><div><strong>计算坐标</strong><p>取已解析的日志坐标块；最后记录与 Review 选中结构分别展示。</p></div><div><strong>推测连接</strong><p>由坐标距离和固定共价半径生成，仅用于显示。</p></div><div><strong>明确记录的键级</strong><p>当前契约未提供，显示为未接入。</p></div></div>
 <p className="micro muted">字节区间采用 UTF-8、从 0 开始、左闭右开 [start, end)。未绑定区间不生成日志定位。日志尚未连接时保留明确的缺失状态。</p></section>;
}
// Validate exact bytes before mapping offsets to line numbers; never treat byte
// offsets as JavaScript string indexes (CJK, CRLF and supplementary Unicode).
export async function locateSource(text:string,source:unknown,logicalName:unknown,target:SourceTarget){
 const {span}=target;const bytes=new TextEncoder().encode(text);
 if(!object(source)||source.kind!=='verified-local-log'||source.sha256!==span.sha256||source.size_bytes!==span.size_bytes||logicalName!==span.logical_name||bytes.length!==span.size_bytes)throw Error('source-mismatch');
 const digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))).map(n=>n.toString(16).padStart(2,'0')).join('');
 if(digest!==span.sha256||!boundSpan(span,span))throw Error('source-mismatch');
 const decoder=new TextDecoder('utf-8',{fatal:true,ignoreBOM:true});const before=decoder.decode(bytes.slice(0,span.start)),excerpt=decoder.decode(bytes.slice(span.start,span.end));
 const firstLine=before.split('\n').length-1;const lastLine=firstLine+excerpt.replace(/\r?\n$/,'').split('\n').length-1;
 return {firstLine,lastLine,excerpt};
}
