import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {stripTypeScriptTypes} from 'node:module';
const source=await readFile(new URL('../src/contract.ts',import.meta.url),'utf8');
const js=stripTypeScriptTypes(source);
let serial=0;
async function fixture(run){
 const originals={fetch:globalThis.fetch,setTimeout:globalThis.setTimeout,clearTimeout:globalThis.clearTimeout};
 const timers=new Map(),requests=[];let now=0,next=0,active=0,maxActive=0;
 const drain=async()=>{for(let i=0;i<12;i++)await Promise.resolve();};
 globalThis.setTimeout=(fn,ms)=>{const id=++next;timers.set(id,{fn,at:now+ms});return id;};
 globalThis.clearTimeout=id=>timers.delete(id);
 globalThis.fetch=(url,options)=>new Promise((resolve,reject)=>{
  active++;maxActive=Math.max(active,maxActive);let done=false;
  const finish=fn=>{if(done)return;done=true;active--;options.signal.removeEventListener('abort',abort);fn();};
  const abort=()=>finish(()=>reject(new DOMException('Aborted','AbortError')));
  options.signal.addEventListener('abort',abort,{once:true});
  requests.push({url,signal:options.signal,finish:(body={},status=200)=>finish(()=>resolve(new Response(JSON.stringify(body),{status,headers:{'Content-Type':'application/json'}})))});
 });
 const advance=async ms=>{const end=now+ms;while(true){const first=[...timers].sort((a,b)=>a[1].at-b[1].at)[0];if(!first||first[1].at>end)break;now=first[1].at;timers.delete(first[0]);first[1].fn();await drain();}now=end;await drain();};
 try{
  const {requestJSON}=await import('data:text/javascript;base64,'+Buffer.from(js).toString('base64')+'#'+serial++);
  await run({requestJSON,requests,advance,drain,timers,getMax:()=>maxActive});
 }finally{Object.assign(globalThis,originals);}
}
const observe=p=>p.then(value=>({value}),error=>({error}));
const ordinary=(f,c=new AbortController())=>observe(f.requestJSON('/api/projects','',c.signal));
const native=(f,c=new AbortController())=>observe(f.requestJSON('/api/v1/native/projects','',c.signal,'native-scientific-read'));
test('ordinary deadline stays 15s; native succeeds after 20s',()=>fixture(async f=>{
 const a=ordinary(f),b=native(f);await f.advance(15000);
 assert.match((await a).error.message,/15 秒/);assert.equal(f.requests[1].signal.aborted,false);
 await f.advance(5000);f.requests[1].finish({retained:true});assert.deepEqual((await b).value,{retained:true});assert.equal(f.timers.size,0);
}));
test('native timeout is finite, explicit, releases slots and never retries',()=>fixture(async f=>{
 const a=native(f),b=native(f),c=native(f);assert.equal(f.requests.length,2);
 await f.advance(119999);assert.equal(f.requests.length,2);await f.advance(1);
 assert.match((await a).error.message,/120 秒/);assert.match((await b).error.message,/120 秒/);
 assert.equal(f.requests.length,3);assert.equal(f.getMax(),2);f.requests[2].finish({third:true});assert.deepEqual((await c).value,{third:true});
 await f.advance(300000);assert.equal(f.requests.length,3);assert.equal(f.timers.size,0);
}));
test('navigation abandons consumer but keeps its slot until transport settles',()=>fixture(async f=>{
 const control=new AbortController(),a=native(f,control),b=native(f),c=native(f);control.abort();
 assert.equal((await a).error.name,'AbortError');assert.equal(f.requests[0].signal.aborted,false);assert.equal(f.requests.length,2);
 f.requests[0].finish({stale:true});await f.drain();assert.equal(f.requests.length,3);assert.equal(f.getMax(),2);
 f.requests[1].finish();f.requests[2].finish();await Promise.all([b,c]);assert.equal(f.timers.size,0);
}));
test('abandoned in-flight reads are still bounded and queued cancellation sends no request',()=>fixture(async f=>{
 const first=new AbortController(),queued=new AbortController();const a=native(f,first),b=native(f),c=native(f,queued),d=native(f);
 first.abort();queued.abort();assert.equal((await a).error.name,'AbortError');await f.advance(120000);
 assert.match((await b).error.message,/120 秒/);assert.equal((await c).error.name,'AbortError');assert.equal(f.requests.length,3);
 f.requests[2].finish({last:true});assert.deepEqual((await d).value,{last:true});assert.equal(f.getMax(),2);assert.equal(f.timers.size,0);
}));
test('503 and evidence errors remain failures without automatic retries',()=>fixture(async f=>{
 for(const [status,code] of [[503,'store-unavailable'],[409,'native-evidence-mismatch']]){
  const p=native(f),n=f.requests.length;f.requests[n-1].finish({schema:'auto-g16-http-error/1',error:{code}},status);assert.equal((await p).error.message,code);await f.advance(150000);assert.equal(f.requests.length,n);
 }
 assert.equal(f.timers.size,0);
}));
