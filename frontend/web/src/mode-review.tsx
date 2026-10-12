import {useEffect,useRef,useState} from 'react';
import {requestJSON} from './contract';
import {object} from './provenance';
import type {VibrationMode} from './vibration-contract';
const SCHEMA='auto-g16-intended-mode-review/1';
type Target={schema:string;attempt_id:string;result_source:unknown;frequency_cm1:number;mode_number:number;frequency_index:number;scope:string;displacements_sha256:string;mode_source_span:unknown;frequency_source_span:unknown;vector_digest_format:string};
type Command={schema:string;request_id:string;target_sha256:string;reviewer:string;note:string;decision:string};
type RecordValue={schema:string;record_id:string;recorded_at_utc:string;reviewer_identity:string;command:Command;target:Target;record_sha256:string};
type View={schema:string;attempt_id:string;enabled:boolean;target:Target|null;target_sha256:string|null;reason:string|null;records:RecordValue[];other_target_count:number};
const equal=(a:unknown,b:unknown):boolean=>{if(a===b)return true;if(Array.isArray(a)&&Array.isArray(b))return a.length===b.length&&a.every((v,i)=>equal(v,b[i]));if(object(a)&&object(b))return Object.keys(a).length===Object.keys(b).length&&Object.keys(a).every(k=>equal(a[k],b[k]));return false;};
const hash=(v:unknown):v is string=>typeof v==='string'&&/^[0-9a-f]{64}$/.test(v);
function isTarget(t:unknown,id:string):t is Target{return object(t)&&t.schema==='auto-g16-intended-mode-target/1'&&t.attempt_id===id&&object(t.result_source)&&typeof t.frequency_cm1==='number'&&Number.isFinite(t.frequency_cm1)&&t.frequency_cm1<0&&Number.isSafeInteger(t.mode_number)&&Number(t.mode_number)>0&&t.frequency_index===Number(t.mode_number)-1&&t.scope==='human-intended-mode-only-not-ts-acceptance'&&hash(t.displacements_sha256)&&t.vector_digest_format==='ieee754-be-f64-center-atomic-number-dxyz/1';}
function isRecord(r:unknown,id:string):r is RecordValue{return object(r)&&r.schema===SCHEMA&&typeof r.record_id==='string'&&typeof r.recorded_at_utc==='string'&&Number.isFinite(Date.parse(r.recorded_at_utc))&&r.reviewer_identity==='self-declared-local-user'&&isTarget(r.target,id)&&hash(r.record_sha256)&&object(r.command)&&r.command.schema===SCHEMA&&typeof r.command.request_id==='string'&&r.record_id==='mode-review-'+r.command.request_id&&hash(r.command.target_sha256)&&typeof r.command.reviewer==='string'&&typeof r.command.note==='string'&&r.command.decision==='intended-reaction-coordinate';}
function parseView(v:unknown,id:string,source:unknown):View {
 if(!object(v)||v.schema!==SCHEMA||v.attempt_id!==id||typeof v.enabled!=='boolean'||!Number.isSafeInteger(v.other_target_count)||Number(v.other_target_count)<0||
  !(v.target===null?v.target_sha256===null&&typeof v.reason==='string':isTarget(v.target,id)&&equal(v.target.result_source,source)&&hash(v.target_sha256)&&v.reason===null)||
  !Array.isArray(v.records)||!v.records.every(r=>isRecord(r,id)&&r.command.target_sha256===v.target_sha256&&equal(r.target,v.target)))throw Error('review-target-changed');
 return v as View;
}
const reasons:Record<string,string>={'review-writing-disabled':'当前服务未开启人工确认。','qualified-result-required':'需要有明确来源的结果。','single-imaginary-candidate-required':'仅对具有一个虚频的候选开放方向确认。','bound-displacements-required':'需要先接入与结果绑定的真实位移。'};
export function HumanModeReview({id,kind,source,activeMode,token,tsCandidate}:{id:string;kind:'attempt'|'archive';source:unknown;activeMode?:VibrationMode;token:string;tsCandidate:boolean}){
 const [view,setView]=useState<View|null>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false),[reviewer,setReviewer]=useState(''),[note,setNote]=useState(''),[checked,setChecked]=useState(false),[revision,setRevision]=useState(0);
 const pending=useRef<Command|null>(null),mounted=useRef(true),sending=useRef(false);
 const [vectorHash,setVectorHash]=useState('');
 useEffect(()=>{let alive=true;setVectorHash('');if(activeMode){const bytes=new Uint8Array(activeMode.displacements.length*40),buffer=new DataView(bytes.buffer);activeMode.displacements.forEach((v,i)=>[v.center,v.atomic_number,v.dx,v.dy,v.dz].forEach((n,j)=>buffer.setFloat64(i*40+j*8,n,false)));void crypto.subtle.digest('SHA-256',bytes).then(hash=>{if(alive)setVectorHash(Array.from(new Uint8Array(hash),v=>v.toString(16).padStart(2,'0')).join(''));});}return()=>{alive=false;};},[activeMode]);
 const path=`/api/attempts/${encodeURIComponent(id)}/mode-review`;
 useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;};},[]);
 useEffect(()=>{if(kind!=='attempt')return;const c=new AbortController();setView(null);setError('');setChecked(false);
  requestJSON(path,token,c.signal).then(v=>{const next=parseView(v,id,source);if(!c.signal.aborted){setView(next);if(pending.current&&next.records.some(r=>r.command.request_id===pending.current?.request_id))pending.current=null;}}).catch(()=>{if(!c.signal.aborted)setError('来源或确认记录无法核对，请刷新结果后重试。');});return()=>c.abort();
 },[path,kind,id,source,token,revision]);
 const active=Boolean(view?.target&&activeMode&&vectorHash===view.target.displacements_sha256&&equal(activeMode.source_span,view.target.mode_source_span)&&equal(activeMode.frequency_source_span,view.target.frequency_source_span)&&activeMode.mode_number===view.target.mode_number&&activeMode.frequency_index===view.target.frequency_index&&activeMode.frequency_cm1===view.target.frequency_cm1);
 useEffect(()=>setChecked(false),[activeMode]);
 async function submit(){
  if(sending.current||!view?.target||!view.target_sha256||!checked||!active||!reviewer.trim())return;
  const cmd=pending.current??{schema:SCHEMA,request_id:crypto.randomUUID(),target_sha256:view.target_sha256,reviewer:reviewer.trim(),note:note.trim(),decision:'intended-reaction-coordinate'};
  pending.current=cmd;sending.current=true;setBusy(true);setError('');
  try{
   const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-AutoG-Review':'intended-mode/1',...(token?{Authorization:`Bearer ${token}`}:{})},body:JSON.stringify(cmd),credentials:'omit',cache:'no-store',redirect:'error'});
   const packet:unknown=await response.json();
   if(!response.ok)throw Error('write-not-confirmed');
   if(!object(packet)||packet.schema!==SCHEMA||packet.attempt_id!==id||!isRecord(packet.record,id)||!equal(packet.record.command,cmd)||!equal(packet.record.target,view.target))throw Error('write-not-confirmed');
   if(mounted.current){pending.current=null;setChecked(false);setRevision(v=>v+1);}
  }catch{if(mounted.current)setError('未能确认写入结果。可先核对记录，或用同一请求重试；请勿更改原确认内容。');}
  finally{sending.current=false;if(mounted.current)setBusy(false);}
 }
 return <div className="human-mode-review" data-testid="human-mode-review">
  <div className="human-review-status"><strong>{view?.records.length?'目标振动方向已记录 · 非 TS 接受':tsCandidate?'PENDING HUMAN REVIEW':'本次未新增科学验收'}</strong><p>确认仅表示你判断该模式对应目标反应坐标。完整 TS 接受仍需另行核对 IRC / 端点等证据。</p></div>
  {kind==='archive'?<p>历史档案尚无原生 Attempt 绑定，暂不开放方向确认。</p>:<>
   {error&&<p role="alert">{error}</p>}
   {!view&&!error&&<p role="status">正在核对人工确认记录…</p>}
   {view?.reason&&<p>{reasons[view.reason]??'当前证据不足，不能提交方向确认。'}</p>}
   {view?.other_target_count? <p>此 Attempt 另有 {view.other_target_count} 条其他结果/模式的历史确认，未套用到当前结果。</p>:null}
   {view?.records.map(r=><div className="mode-review-record" key={r.record_id}><strong>{r.command.reviewer}</strong><small>确认者自行填写，非已认证账号</small><time>{r.recorded_at_utc}</time><p>Mode {r.target.mode_number} · {r.target.frequency_cm1} cm⁻¹</p>{r.command.note&&<p>{r.command.note}</p>}<details><summary>不可覆盖的确认记录</summary><pre>{JSON.stringify(r,null,2)}</pre></details></div>)}
   {view?.enabled&&view.target&&<form onSubmit={e=>{e.preventDefault();void submit();}}>
    <p className="micro">将追加一条独立记录，绑定此 Attempt / Result / Mode {view.target.mode_number}（{view.target.frequency_cm1} cm⁻¹）；原始结果不变。</p>
    {!active&&<p>请先播放上方对应虚频，再核对目标方向。</p>}
    <label>确认者<input aria-label="模式确认者" autoComplete="off" maxLength={120} value={reviewer} disabled={busy||Boolean(pending.current)} onChange={e=>setReviewer(e.target.value)} required/></label>
    <label>备注（可选）<input aria-label="模式确认备注" maxLength={2000} value={note} disabled={busy||Boolean(pending.current)} onChange={e=>setNote(e.target.value)}/></label>
    <label className="mode-review-check"><input type="checkbox" checked={checked} disabled={!active||busy} onChange={e=>setChecked(e.target.checked)}/>我已查看此模式，确认它对应目标反应坐标；这不是完整 TS 验收。</label>
    <button disabled={busy||!active||!checked||!reviewer.trim()} type="submit">{busy?'正在记录…':pending.current?'重试原确认请求':'记录目标振动方向确认'}</button>
   </form>}
   {(error||pending.current)&&<button disabled={busy} onClick={()=>setRevision(v=>v+1)}>只读核对已保存记录</button>}
  </>}
 </div>;
}
