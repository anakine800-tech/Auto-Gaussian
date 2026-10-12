import {useEffect,useState} from 'react';
export type Group={id:string;kind:'native'|'historical';label:string;source_label:string;basis:string;count:number;task_count:number|null;states:string[];state_counts?:Record<string,number>;issue_archive_ids?:string[];issue_count?:number;archive_ids?:string[]};
export type Bucket='calculation'|'test';
export type Organization={bucket:Bucket;project:string;pinned?:boolean};
type Preferences=Record<string,Organization>;
const key='autog-project-organization/1';
export const groupKey=(g:Pick<Group,'kind'|'id'>)=>g.kind+':'+g.id;
function load():Preferences{try{const v=JSON.parse(localStorage.getItem(key)??'{}');if(!v||typeof v!=='object'||Array.isArray(v))return {};return Object.fromEntries(Object.entries(v).filter(([,x])=>{const p=x as Organization;return p&&['calculation','test'].includes(p.bucket)&&typeof p.project==='string'&&p.project.trim().length>0&&p.project.length<=100&&(p.pinned===undefined||typeof p.pinned==='boolean');})) as Preferences;}catch{return {};}}
export function automaticBucket(g:Pick<Group,'label'|'id'>):Bucket{return /(?:^|[-_\s])(test|smoke|fixture|synthetic)(?:[-_\s]|$)|(?:^|[-_])first-live(?:[-_]|$)|测试|联测/i.test(g.label+' '+g.id)?'test':'calculation';}
export function directorySeries(g:Group){
 if(g.kind==='native'||g.basis==='unassigned'||!g.label.includes('_'))return g.label;
 // Visual grouping by directory prefix only; no chemical-project or Core ancestry claim.
 const first=g.label.split('_')[0];
 const parts=first.match(/^([a-z]+)(\d+)?/i);
 const prefix=parts?(parts[1].length>=3?parts[1]:parts[1]+(parts[2]??'')):first;
 return prefix===g.label?g.label:prefix+' · 目录系列';
}
export function organization(g:Group,prefs:Preferences):Organization{return prefs[groupKey(g)]??{bucket:automaticBucket(g),project:directorySeries(g)};}
export function useOrganization(){
 const [prefs,setPrefs]=useState<Preferences>(load),[error,setError]=useState('');
 useEffect(()=>{const update=()=>setPrefs(load());window.addEventListener('storage',update);window.addEventListener(key,update);return()=>{window.removeEventListener('storage',update);window.removeEventListener(key,update);};},[]);
 function change(groups:Group[],value:Organization|null){const next={...prefs};for(const g of groups){if(value)next[groupKey(g)]=value;else delete next[groupKey(g)];}setPrefs(next);try{localStorage.setItem(key,JSON.stringify(next));setError('');window.dispatchEvent(new Event(key));}catch{setError('浏览器无法保存整理偏好，本次修改仅在当前页面有效。');}}
 function pin(groups:Group[],pinned:boolean){const next={...prefs};for(const g of groups)next[groupKey(g)]={...organization(g,prefs),pinned};setPrefs(next);try{localStorage.setItem(key,JSON.stringify(next));setError('');window.dispatchEvent(new Event(key));}catch{setError('浏览器无法保存置顶偏好，本次修改仅在当前页面有效。');}}
 return {prefs,error,change,pin,info:(g:Group)=>organization(g,prefs),custom:(g:Group)=>Object.hasOwn(prefs,groupKey(g))};
}
export type Collection={id:string;legacyId?:string;name:string;bucket:Bucket;kind:'native'|'historical';groups:Group[];states:string[];count:number;pinned:boolean};
export function collections(groups:Group[],prefs:Preferences):Collection[]{
 const out=new Map<string,Collection>();for(const g of groups){const info=organization(g,prefs);const id=JSON.stringify([g.kind,g.source_label,info.bucket,info.project]);let c=out.get(id);if(!c){c={id,name:info.project,bucket:info.bucket,kind:g.kind,groups:[],states:[],count:0,pinned:false};out.set(id,c);}c.pinned ||= info.pinned===true;c.groups.push(g);c.states=[...new Set([...c.states,...g.states])];}
 for(const c of out.values()){c.legacyId=c.id;c.id=JSON.stringify([c.kind,c.groups[0].source_label,'project',c.groups.map(g=>g.id).sort()[0]]);if(c.groups.length===1&&(!Object.hasOwn(prefs,groupKey(c.groups[0]))||prefs[groupKey(c.groups[0])].project===directorySeries(c.groups[0])))c.name=c.groups[0].label;c.name=c.name.replace(/ · 目录系列$/,'');c.count=c.groups.every(g=>g.archive_ids)?new Set(c.groups.flatMap(g=>g.archive_ids!)).size:c.groups.reduce((n,g)=>n+g.count,0);}
 return [...out.values()].sort((a,b)=>Number(b.pinned)-Number(a.pinned)||a.name.localeCompare(b.name,'zh-CN',{numeric:true}));
}

export const collectionValue=(c:Collection)=>c.groups.length===1?c.groups[0].id:'series:'+c.id;
export function findCollection(items:Collection[],value:string){return items.find(c=>collectionValue(c)===value||'series:'+c.id===value||'series:'+c.legacyId===value||c.groups.some(g=>g.id===value));}
