import {parseDetails} from './detail-panel';
import {useEffect,useState} from 'react';
import {requestJSON} from './contract';
import {readResult} from './result-contract';
import type {GaussianResult} from './result-contract';
import {resultContext} from './result-context';
import {object} from './provenance';
export const resultLabel=(v:string)=>({available:'摘要可读',partial:'证据不完整',missing:'尚无绑定结果',unsupported:'来源尚不支持',conflict:'来源冲突',error:'读取失败'}[v]??'读取中…');
type Evidence={result:GaussianResult|'error';review:unknown;context:ReturnType<typeof resultContext>;detailStatus:string};
export function useAttemptEvidence(ids:string[],token?:string){
 const key=JSON.stringify(ids),[loaded,setLoaded]=useState<{key:string;data:Record<string,Evidence>}>({key:'',data:{}});
 useEffect(()=>{if(token===undefined)return;const ac=new AbortController();setLoaded({key,data:{}});
 async function load(){const identities=JSON.parse(key) as string[];for(let i=0;i<identities.length&&!ac.signal.aborted;i+=3)await Promise.all(identities.slice(i,i+3).map(async id=>{
 if(ac.signal.aborted)return;
 let result:GaussianResult|'error'='error',review:unknown=null,context:ReturnType<typeof resultContext>=null,detailStatus='补充证据读取失败';
 const [r]=await Promise.allSettled([readResult(id,token!,ac.signal)]);
 if(ac.signal.aborted)return;
 const [d]=await Promise.allSettled([requestJSON('/api/attempts/'+encodeURIComponent(id)+'/details',token!,ac.signal)]);
 if(r.status==='fulfilled')result=r.value;
 if(d.status==='fulfilled'){try{const v=parseDetails(d.value,'attempt',id);
 const src=object(v.result.source)?v.result.source:null;
 // Separate endpoint snapshots may differ; never combine mismatched Result identities.
 if(result!=='error'&&result.availability==='available'&&src?.result_id===result.source?.result_id){
 context=resultContext(v.context,'attempt',id,src);review=v.review.availability==='available'?v.review.data:null;detailStatus='已核对绑定来源';
 }else if(v.result.availability==='unavailable'&&result!=='error'&&result.availability!=='available')detailStatus='尚无可核对的补充结果';
 else detailStatus='来源尚未核对或快照不同，请打开详情核对';
 }catch{/* Invalid or cross-identity details are never projected. */}}
 if(!ac.signal.aborted)setLoaded(s=>s.key===key?{key,data:{...s.data,[id]:{result,review,context,detailStatus}}}:s);
 }));}void load();return()=>ac.abort();},[key,token]);
 return loaded.key===key?loaded.data:{};
}
