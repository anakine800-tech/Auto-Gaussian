import {projectFromRoute} from './navigation';
import {DraftShelf} from './draft-shelf';
import {useEffect,useRef,useState} from 'react';
import {requestJSON} from './contract';
import {object} from './provenance';

type Review={id:string;title:string;attempt_id:string;snapshot_id:string;input_sha256:string;input_text:string;template_sha256:string;structure_review:string;resources:Record<string,unknown>;remote_directory:string;profile_sha256:string};
type Prepared={available:boolean;id?:string;reason?:string;review?:Review;review_sha256?:string};
type Item={id:string;prepared_id:string|null;state:string;reason:string|null;payload:Record<string,unknown>;created_at:number;updated_at:number};
type Queue={schema:string;enabled:boolean;execution_enabled:boolean;max_active:number;items:Item[];prepared:Prepared[]};
const labels:Record<string,string>={DRAFT:'计算草稿',QUEUED:'本地待提交',BLOCKED:'提交前检查未通过',SUBMITTING:'提交中',SUBMITTED:'已提交服务器',RUNNING:'运行中',UNKNOWN:'提交状态待核对',SUCCEEDED:'执行完成',FAILED:'执行失败',NOT_SUBMITTED:'确认未提交',WITHDRAWN:'已撤回本地请求'};
const reasons:Record<string,string>={'review-or-prerequisite-changed':'输入、审批或依赖条件已变化，请重新准备任务。','receipt-unavailable-no-retry':'未取得可靠回执，已停止自动提交。','interrupted-before-receipt':'服务中断发生在取得回执之前，需要核对执行端记录。'};
const errors:Record<string,string>={'task-conflict':'已有相同请求或任务状态已变化，请刷新核对。','task-review-changed':'输入或审批已变化，请重新读取提交预览。','task-capacity-busy':'当前已有待提交或运行任务，请使用“加入待提交队列”。','execution-unavailable':'执行端尚未配置。','method-not-allowed':'本地任务队列尚未启用。'};
export async function taskAction(action:string,body:unknown,token:string){
 const response=await fetch('/api/task-center/'+action,{method:'POST',headers:{'Content-Type':'application/json','X-Autog-Task':'task-command/1',...(token?{Authorization:'Bearer '+token}:{})},body:JSON.stringify(body),credentials:'omit',redirect:'error'});
 const value=await response.json();if(!response.ok)throw Error(errors[value?.error?.code]??'请求未确认，请刷新核对；不要重复发起提交。');return value;
}
function parseQueue(value:unknown):Queue {
 if(!object(value)||value.schema!=='autog-task-center/1'||typeof value.enabled!=='boolean'||typeof value.execution_enabled!=='boolean'||!Array.isArray(value.items)||!Array.isArray(value.prepared)||!Number.isSafeInteger(value.max_active))throw Error('队列数据不符合接口契约。');
 if(!value.items.every(r=>object(r)&&typeof r.id==='string'&&typeof r.state==='string'&&r.state in labels&&object(r.payload)))throw Error('队列状态无效。');
 for(const p of value.prepared){
  if(!object(p)||typeof p.available!=='boolean')throw Error('任务数据无效。');
  if(p.available){const r=p.review;if(!object(r)||!['id','title','attempt_id','snapshot_id','input_text','structure_review','remote_directory'].every(k=>typeof r[k]==='string')||!['input_sha256','template_sha256','profile_sha256'].every(k=>/^[a-f0-9]{64}$/.test(String(r[k])))||!/^[a-f0-9]{64}$/.test(String(p.review_sha256))||!object(r.resources))throw Error('提交预览无效。');}
 }
 return value as unknown as Queue;
}
export function TaskCenter({token,mode='drafts'}:{token:string;mode?:'drafts'|'queue'}){
 const [data,setData]=useState<Queue|null>(null),[error,setError]=useState(''),[revision,setRevision]=useState(0),[selected,setSelected]=useState<Prepared|null>(null),[confirmed,setConfirmed]=useState(false),[busy,setBusy]=useState(false);
 const request=useRef<string|null>(null);
 useEffect(()=>{const c=new AbortController();let timer:number;const load=async()=>{try{const v=parseQueue(await requestJSON('/api/task-center',token,c.signal));if(!c.signal.aborted){setData(v);setError('');timer=window.setTimeout(load,5000);}}catch(e){if(!c.signal.aborted)setError(e instanceof Error?e.message:'队列读取失败');}};void load();return()=>{c.abort();clearTimeout(timer);};},[token,revision]);
 async function run(action:string,item?:Item){if(busy)return;setBusy(true);setError('');try{const body=item?{id:item.id}:{request_id:request.current??(request.current=crypto.randomUUID()),prepared_id:selected?.review?.id,review_sha256:selected?.review_sha256};setData(parseQueue(await taskAction(action,body,token)));setSelected(null);setConfirmed(false);request.current=null;}catch(e){setError(e instanceof Error?e.message:'请求失败');}finally{setBusy(false);}}
 return <><div className="page-heading"><div className="eyebrow">TASK CENTER</div><h1>{mode==='drafts'?'计算草稿':'待处理任务'}</h1><p>{mode==='drafts'?'输入草稿、修复草稿和下一阶段准备集中查看。':'核对已准备输入，查看本地排队和提交状态。'}</p></div>
 {projectFromRoute()&&<p className="micro">此处显示全部本地任务；项目上下文用于新建草稿，不会把其他项目的任务改归此项目。</p>}<div className="task-actions"><button onClick={()=>{setRevision(x=>x+1);setError('');}}>刷新队列</button></div>{mode==='drafts'&&<section className="panel"><h2>浏览器与服务端草稿</h2><DraftShelf/></section>}

 {error&&<p role="alert" className="notice warning">{error}</p>}{!data?<p role="status">读取任务队列…</p>:<>
 {!data.enabled?<div className="notice">本地任务队列未启用。启动时配置独立的任务队列目录后，可保存计算草稿。</div>:<p className="operations-note">本队列最多同时保留 {data.max_active} 个活动提交；本地待提交与 PBS 排队分别显示。执行完成不代表科学验收。</p>}
 {!data.execution_enabled&&<div className="notice">执行端尚未接入：可以查看结果{data.enabled?'并保存下一步计算草稿':''}。真实提交需由后端提供已准备的输入、审批与执行快照。</div>}
 {mode==='queue'&&<section className="panel"><h2>已准备的任务</h2>{!data.prepared.length?<p>暂无后端提供的已准备任务。</p>:data.prepared.map((p,i)=><article className="task-card" key={p.review?.id??p.id??i}><strong>{p.review?.title??p.id}</strong><p>{p.available?'输入与审批可核对':'输入或审批暂不可用'}</p>{p.available&&<button disabled={busy} onClick={()=>{setSelected(p);setConfirmed(false);request.current=null;}}>查看提交预览</button>}</article>)}</section>}
 {selected?.review&&<section className="task-review" aria-label="提交预览"><h2>{selected.review.title} · 提交预览</h2><p>Attempt：{selected.review.attempt_id}</p><p>结构与立体化学审核：{selected.review.structure_review}</p><p>服务器目录：{selected.review.remote_directory}</p><pre>{JSON.stringify(selected.review.resources,null,2)}</pre><h3>完整 Gaussian 输入</h3><pre>{selected.review.input_text}</pre><p>输入 SHA-256：<code>{selected.review.input_sha256}</code></p><details><summary>执行绑定</summary><pre>{JSON.stringify({snapshot:selected.review.snapshot_id,profile:selected.review.profile_sha256,template:selected.review.template_sha256,review:selected.review_sha256},null,2)}</pre></details><label><input type="checkbox" checked={confirmed} onChange={e=>setConfirmed(e.target.checked)}/>我已核对结构、立体化学、电荷、多重度、关键词、资源、目录与输入摘要，确认按此预览执行一次。</label><div className="task-actions"><button disabled={!confirmed||busy} onClick={()=>void run('submit')}>确认立即提交</button><button disabled={!confirmed||busy} onClick={()=>void run('enqueue')}>确认加入待提交队列</button><button disabled={busy} onClick={()=>setSelected(null)}>关闭预览</button></div></section>}
 <section className="panel"><h2>{mode==='drafts'?'服务端 · 下一阶段草稿':'本地队列'}</h2>{!data.items.filter(i=>mode==='drafts'?i.state==='DRAFT':i.state!=='DRAFT').length?<p>暂无任务。可从初筛工作台选择候选并准备下一阶段草稿。</p>:data.items.filter(i=>mode==='drafts'?i.state==='DRAFT':i.state!=='DRAFT').map(item=><article className="task-card" key={item.id}><span className="draft-origin">本地服务端 · 任务库</span><span className="task-state">{labels[item.state]}</span><h3>{String(item.payload.title??item.prepared_id??'计算草稿')}</h3>{item.reason&&<p>{reasons[item.reason]??'请检查任务记录。'}</p>}{item.payload.stage!==undefined&&<p>下一阶段：{String(item.payload.stage)}</p>}{object(item.payload.source)&&<p>候选来源：<a href={`#/${item.payload.source.kind==='archive'?'archives':'attempts'}/${encodeURIComponent(String(item.payload.source.id))}`}>{String(item.payload.source.id)}</a></p>}{typeof item.payload.attempt_id==='string'&&<a href={'#/attempts/'+encodeURIComponent(item.payload.attempt_id)}>查看 Attempt 与执行回执 →</a>}{item.state==='UNKNOWN'&&<button disabled={busy} onClick={()=>void run('reconcile',item)}>核对本地执行回执</button>}{['DRAFT','QUEUED','BLOCKED'].includes(item.state)&&<div className="task-actions"><button disabled={busy} onClick={()=>void run('withdraw',item)}>撤回本地请求</button></div>}</article>)}</section>
 </>}</>;
}
