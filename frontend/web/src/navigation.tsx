import {useEffect,useRef,useState} from 'react';
import type {ReactNode} from 'react';
import {requestJSON} from './contract';
import {collections,collectionValue,findCollection,useOrganization} from './project-organization';
import type {Group} from './project-organization';

export function canonicalRoute(hash:string):string {
 const [path,query='']=hash.split('?');const q=new URLSearchParams(query);
 const aliases:Record<string,[string,string?]>={
  '#/drafts':['#/calculations','new'],'#/task-center':['#/calculations','drafts'],
  '#/workflows':['#/calculations','runs'],'#/screening':['#/analysis','compare'],
  '#/results':['#/analysis','results'],'#/offline-science':['#/analysis','irc'],
  '#/library':['#/settings','library'],'#/capabilities':['#/settings','capabilities'],
  '#/tests':['#/projects'],'#/archives':['#/projects']
 };
 const alias=aliases[path];if(!alias)return hash||'#/projects';
 if(alias[1])q.set('tab',alias[1]);if(path==='#/tests')q.set('purpose','test');if(path==='#/archives')q.set('source','historical');
 return alias[0]+(q.size?'?'+q.toString():'');
}
export function routeParams(hash=location.hash){return new URLSearchParams(hash.split('?')[1]??'');}
export function routeLink(path:string,values:Record<string,string|undefined>={}){const q=new URLSearchParams();for(const [k,v]of Object.entries(values))if(v!==undefined&&v!=='')q.set(k,v);return path+(q.size?'?'+q.toString():'');}
export function projectFromRoute(hash=location.hash){const path=hash.split('?')[0],q=routeParams(hash);try{return path.startsWith('#/history-projects/')?decodeURIComponent(path.slice(19)):path.startsWith('#/projects/')?decodeURIComponent(path.slice(11)):q.get('project')??q.get('from')??'';}catch{return '';}}
export function useSessionValue<T>(key:string,fallback:T){const [value,setValue]=useState<T>(()=>{try{return JSON.parse(sessionStorage.getItem(key)??'null')??fallback;}catch{return fallback;}});useEffect(()=>{try{sessionStorage.setItem(key,JSON.stringify(value));}catch{}},[key,value]);return [value,setValue] as const;}
export function SectionTabs({path,tab,items,project}:{path:string;tab:string;items:[string,string][];project?:string}){return <nav className="section-tabs" aria-label="页面分区">{items.map(([key,label])=><a key={key} aria-current={tab===key?'page':undefined} href={routeLink(path,{tab:key,project,selection:path==='#/analysis'&&key!=='results'?routeParams().get('selection')??undefined:undefined})}>{label}</a>)}</nav>;}
export function ProjectContext({hash,token}:{hash:string;token:string}){
 const id=projectFromRoute(hash),org=useOrganization();const [group,setGroup]=useState<{id:string;label:string;kind:string;task?:string}|null>(null);
 useEffect(()=>{setGroup(null);if(!id)return;const c=new AbortController();let disposed=false;const timeout=setTimeout(()=>c.abort(),15000);requestJSON('/api/project-library',token,c.signal).then(v=>{const d=v as {schema?:string;items?:Group[]};const items=d.schema==='autog-project-library/1'&&Array.isArray(d.items)?d.items:[];const parent=findCollection(collections(items,org.prefs),id);const member=items.find(g=>g.id===id);const archive=hash.split('?')[0].startsWith('#/archives/')?hash.split('?')[0].slice(11):null;if(parent&&(!archive||(member?member.archive_ids?.includes(archive):parent.groups.some(g=>g.archive_ids?.includes(archive))))&&!disposed&&!c.signal.aborted)setGroup({id:collectionValue(parent),label:parent.name,kind:parent.kind,task:parent.groups.length>1?member?.label:undefined});}).catch(()=>{}).finally(()=>clearTimeout(timeout));return()=>{disposed=true;};},[id,token,hash.split('?')[0],org.prefs]);
 if(!id)return null;
 return <nav className="project-context" aria-label={hash.startsWith('#/archives/')?'来源项目':'当前项目'}><a href="#/projects">项目</a><span> / </span>{group?<a href={routeLink(group.kind==='native'?'#/projects/'+encodeURIComponent(group.id):'#/history-projects/'+encodeURIComponent(group.id))}>{group.label}</a>:<span>{id} · 来源待核对</span>}{group?.task&&<span> / {group.task}</span>}<small>{group?.kind==='historical'?'历史目录 · 浏览归属':group?.kind==='native'?'原生项目':''}</small><a href={routeLink('#/analysis',{tab:'compare',project:group?.id??id})}>分析此项目</a></nav>;
}
export function ActionDrawer({label,children}:{label:string;children:ReactNode}){
 const dialog=useRef<HTMLDialogElement>(null);const [seen,setSeen]=useState(false);
 return <><button onClick={()=>{setSeen(true);dialog.current?.showModal();}}>{label}</button><dialog className="action-drawer" ref={dialog} aria-label={label}><div className="drawer-heading"><h2>{label}</h2><button autoFocus onClick={()=>dialog.current?.close()} aria-label={'关闭'+label}>关闭 ×</button></div>{seen&&children}</dialog></>;
}
// Restore only this tab's UI position. Stop restoring as soon as the user interacts.
export function useRoutePosition(hash:string){
 const previous=useRef(hash),positions=useRef<Record<string,number>>({});
 useEffect(()=>{const save=()=>{positions.current[previous.current]=window.scrollY;};addEventListener('scroll',save,{passive:true});return()=>removeEventListener('scroll',save);},[]);
 useEffect(()=>{previous.current=hash;const y=positions.current[hash]??0;let stopped=false;const restore=()=>{if(!stopped)window.scrollTo(0,y);};restore();const observer=new ResizeObserver(restore);observer.observe(document.querySelector('main')!);const stop=()=>{stopped=true;observer.disconnect();};const timer=setTimeout(stop,5000);addEventListener('wheel',stop,{once:true,passive:true});addEventListener('pointerdown',stop,{once:true});addEventListener('keydown',stop,{once:true});return()=>{stop();clearTimeout(timer);removeEventListener('wheel',stop);removeEventListener('pointerdown',stop);removeEventListener('keydown',stop);};},[hash]);
}

export function ReturnToList({path}:{path:string}){let back='';try{back=sessionStorage.getItem('autog-return:'+path)??'';}catch{}return /^#\/(projects|history-projects|calculations|analysis)(?:[/?]|$)/.test(back)?<a className="context-back" href={back}>← 返回刚才的列表（保留筛选与位置）</a>:<a className="context-back" href="#/analysis?tab=results">← 返回结果索引</a>;}
