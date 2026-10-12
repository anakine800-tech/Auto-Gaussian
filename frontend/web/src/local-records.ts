// Separate browser-local research notes. Never Core records or approvals.
export type SourceRef={name:string;sha256:string;kind:string;id?:string};
export type LocalRecord={schema:'autog-local-note/1';id:string;created_at:string;kind:'draft'|'lineage';parent:string|null;reason:string;payload:Record<string,unknown>;sha256:string};
export const canonical=(v:unknown):string=>{
 if(v===null||typeof v!=='object')return JSON.stringify(v);
 if(Array.isArray(v))return '['+v.map(canonical).join(',')+']';
 return '{'+Object.keys(v).sort().map(k=>JSON.stringify(k)+':'+canonical((v as Record<string,unknown>)[k])).join(',')+'}';
};
export async function sha256(text:string|ArrayBuffer){const b=typeof text==='string'?new TextEncoder().encode(text):text;return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',b))).map(x=>x.toString(16).padStart(2,'0')).join('');}
export async function localFile(file:File,max=8*1024*1024){if(file.size>max)throw Error('文件超过读取上限。');const bytes=await file.arrayBuffer();const text=new TextDecoder('utf-8',{fatal:true}).decode(bytes);if(text.includes('\0'))throw Error('仅支持 UTF-8 文本文件。');return {text,source:{name:file.name,kind:'user-import',sha256:await sha256(bytes)} as SourceRef};}
function db():Promise<IDBDatabase>{return new Promise((resolve,reject)=>{const r=indexedDB.open('autog-local-workbench-v1',1);r.onupgradeneeded=()=>r.result.createObjectStore('records',{keyPath:'id'});r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(Error('本地草稿库不可用，请使用导出保存。'));});}
export async function records():Promise<LocalRecord[]>{const d=await db();try{return await new Promise((resolve,reject)=>{const r=d.transaction('records').objectStore('records').getAll();r.onsuccess=()=>resolve(r.result.sort((a:LocalRecord,b:LocalRecord)=>a.created_at.localeCompare(b.created_at)||a.id.localeCompare(b.id)));r.onerror=()=>reject(r.error);});}finally{d.close();}}
export async function verifyRecord(v:unknown):Promise<LocalRecord>{
 if(!v||typeof v!=='object')throw Error('记录格式不正确。');const r=v as LocalRecord;
 if(Object.keys(r).sort().join(',')!=='created_at,id,kind,parent,payload,reason,schema,sha256'||r.schema!=='autog-local-note/1'||!['draft','lineage'].includes(r.kind)||typeof r.id!=='string'||!/^[\w-]{1,80}$/.test(r.id)||typeof r.reason!=='string'||!r.reason.trim()||r.reason.length>2000||typeof r.created_at!=='string'||!Number.isFinite(Date.parse(r.created_at))||!(r.parent===null||typeof r.parent==='string')||!r.payload||typeof r.payload!=='object'||Array.isArray(r.payload)||typeof r.sha256!=='string')throw Error('记录字段不正确。');
 const {sha256:digest,...body}=r;if(canonical(body).length>2*1024*1024||await sha256(canonical(body))!==digest)throw Error('记录摘要不匹配。');return r;
}
export async function appendRecord(kind:LocalRecord['kind'],payload:Record<string,unknown>,reason:string,parent:string|null=null){
 const body={schema:'autog-local-note/1' as const,id:crypto.randomUUID(),created_at:new Date().toISOString(),kind,parent,reason:reason.trim(),payload};
 const record=await verifyRecord({...body,sha256:await sha256(canonical(body))});await importRecords([record]);return record;
}
export async function importRecords(input:unknown){
 if(!Array.isArray(input)||!input.length||input.length>500)throw Error('导入需要 1–500 条记录。');const checked=await Promise.all(input.map(verifyRecord));if(new Set(checked.map(r=>r.id)).size!==checked.length)throw Error('重复记录 ID。');
 const d=await db();try{await new Promise<void>((resolve,reject)=>{const t=d.transaction('records','readwrite'),s=t.objectStore('records');let failure='';t.oncomplete=()=>resolve();t.onabort=()=>reject(Error(failure||'保存失败，原记录保留。'));t.onerror=()=>{};
 const req=s.getAll();req.onsuccess=()=>{const all=new Map<string,LocalRecord>(req.result.map((r:LocalRecord)=>[r.id,r]));for(const r of checked){const old=all.get(r.id);if(old&&old.sha256!==r.sha256){failure='同一 ID 已存在不同内容。';t.abort();return;}all.set(r.id,r);}
 for(const r of checked){let p=r.parent;const seen=new Set([r.id]);while(p){if(seen.has(p)||!all.has(p)){failure='父记录缺失或谱系存在循环。';t.abort();return;}seen.add(p);p=all.get(p)!.parent;}if(!req.result.some((x:LocalRecord)=>x.id===r.id))s.add(r);}};});}finally{d.close();}
}
export function download(name:string,content:string,mime='text/plain;charset=utf-8'){const url=URL.createObjectURL(new Blob([content],{type:mime}));const a=document.createElement('a');a.href=url;a.download=name.replace(/[^\w.\-\u4e00-\u9fff]/g,'_');a.click();setTimeout(()=>URL.revokeObjectURL(url),10000);}
export function csv(rows:unknown[][]){return '\ufeff'+rows.map(r=>r.map(v=>{const x=String(v??'');const safe=/^[\s]*[=+@]/.test(x)||(/^[\s]*-/.test(x)&&!Number.isFinite(Number(x)))?"'"+x:x;return '"'+safe.replace(/"/g,'""')+'"';}).join(',')).join('\r\n');}
export function xyz(g:{atoms:{atomic_number:number;x:number;y:number;z:number}[]},title='exported geometry'){return g.atoms.length+'\n'+title.replace(/[\r\n]/g,' ')+'\n'+g.atoms.map(a=>`${SYMBOLS[a.atomic_number]} ${a.x} ${a.y} ${a.z}`).join('\n')+'\n';}
export const SYMBOLS='? H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au Hg Tl Pb Bi Po At Rn Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf Es Fm Md No Lr Rf Db Sg Bh Hs Mt Ds Rg Cn Nh Fl Mc Lv Ts Og'.split(' ');

export function exportSVG(svg:Element,name:string){const clone=svg.cloneNode(true) as Element;const live=[svg,...svg.querySelectorAll('*')],copies=[clone,...clone.querySelectorAll('*')];for(let i=0;i<live.length;i++){const css=getComputedStyle(live[i]);for(const key of ['fill','stroke','stroke-width','stroke-dasharray','font-family','font-size','font-weight','opacity'])copies[i].setAttribute(key,css.getPropertyValue(key));}clone.setAttribute('xmlns','http://www.w3.org/2000/svg');download(name,new XMLSerializer().serializeToString(clone),'image/svg+xml');}
