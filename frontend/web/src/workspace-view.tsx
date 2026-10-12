import {createContext,useContext,useEffect,useState} from 'react';
import type {ReactNode} from 'react';
import {useSessionValue,routeParams} from './navigation';
export type DetailView='science'|'evidence'|'provenance';
const Context=createContext<{view:DetailView;showEvidence:(anchor?:string)=>void}>({view:'science',showEvidence:()=>{}});
export const useDetailView=()=>useContext(Context);
export function DetailWorkspace({children,identity=location.hash.split('?')[0]}:{children:ReactNode;identity?:string}){
 const initial=routeParams().get('view');
 const [saved,setView]=useSessionValue<DetailView>('autog-detail-view:'+identity,initial==='evidence'||initial==='provenance'?initial:'science');
 useEffect(()=>{if(initial==='overview'||initial==='science'||initial==='evidence'||initial==='provenance')setView(initial==='overview'?'science':initial);},[identity,initial]);
 const view:DetailView=['science','evidence','provenance'].includes(saved)?saved:'science';
 const [target,setTarget]=useState<{anchor:string}|null>(null);
 const showEvidence=(anchor='workflow-evidence')=>{setView(['scientific-review','evidence-provenance'].includes(anchor)?'provenance':'evidence');setTarget({anchor});};
 useEffect(()=>{if(target){const frame=requestAnimationFrame(()=>document.getElementById(target.anchor)?.scrollIntoView({block:'start'}));return()=>cancelAnimationFrame(frame);}},[view,target]);
 return <Context.Provider value={{view,showEvidence}}><div id="detail-overview" className="view-switch detail-view-switch" aria-label="详情显示方式">{([['science','结构与结果'],['evidence','运行与诊断'],['provenance','来源与记录']] as [DetailView,string][]).map(([key,label])=><button key={key} aria-pressed={view===key} onClick={()=>{setView(key);setTarget(null);}}>{label}</button>)}<span>{{science:'主要结果 · 计算条件 · 结构 · 频率 · 科学判断',evidence:'执行记录 · 报错 · 优化轨迹 · 日志',provenance:'原始文件 · 来源链 · 历史审核 · 人工备注'}[view]}</span></div>{children}</Context.Provider>;
}
export function ViewGroup({view,children,id}:{view:DetailView;children:ReactNode;id?:string}){const current=useDetailView().view;const [visited,setVisited]=useState(current===view);useEffect(()=>{if(current===view)setVisited(true);},[current,view]);return <div hidden={current!==view} id={id} data-view={view}>{(visited||current===view)&&children}</div>;}
