import {test,expect,Page} from '@playwright/test';
import {attempt,saved,lifecycle,populations} from './reliability-fixture';
const token='browser-test-only-'+'0'.repeat(32);
const card=(p:Page)=>p.getByRole('region',{name:'RRHO 与 qRRHO 已保存布居'});
const axes=(p:Page)=>p.getByRole('region',{name:'三轴历史状态'});
async function setup(page:Page,changes:{lifecycle?:any;populations?:any;thermodynamics?:any;status?:number;body?:string}={}){
 const requests:{path:string;method:string}[]=[];
 await page.route('**/api/v1/native/**',async route=>{const path=new URL(route.request().url()).pathname;requests.push({path,method:route.request().method()});const id=path.includes('freq-b')?'freq-b':'freq-a';const kind=path.split('/').at(-1)!;
 if(['lifecycle','populations','thermodynamics'].includes(kind)){
  if(changes.status)return route.fulfill({status:changes.status,json:{error:'invalid-evidence'}});
  if(changes.body)return route.fulfill({body:changes.body,contentType:'application/json'});
  const value=Object.hasOwn(changes,kind)?changes[kind as keyof typeof changes]:kind==='lifecycle'?lifecycle(id):kind==='populations'?populations(id):saved(id);
  return route.fulfill({json:value});
 }
 return route.fulfill({json:{schema:'auto-g16-native-query/1',kind:path.includes('/projects/')?'attempts':'attempt',data:path.includes('/projects/')?{items:[attempt(id)]}:attempt(id)}});
 });return requests;
}
async function connect(page:Page,path='/#/native/saved/attempts/freq-a'){await page.goto(path);await page.getByLabel('只读访问令牌').fill(token);await page.getByRole('button',{name:'连接数据源'}).click();}

test('synthetic independent axes and exact saved dual populations; public sources; GET only',async({page})=>{
 const requests=await setup(page);await connect(page);
 await expect(axes(page).getByLabel('program')).toContainText('completed');await expect(axes(page).getByLabel('scheduler')).toContainText('running');await expect(axes(page).getByLabel('collection')).toContainText('collected');
 await expect(axes(page)).toContainText('原始 PBS code：未记录');await expect(axes(page).getByText('观测时间：未记录',{exact:true})).toHaveCount(3);
 await expect(card(page).locator('article')).toHaveCount(2);await expect(card(page)).toContainText('298.15 K · 标准态：1atm');
 for(const value of ['59%','41%','80%','20%','0.6275094740631','1.2550189481262','g = 2','Gaussian 原始 σ = 2','pair hash 已匹配'])await expect(card(page)).toContainText(value);
 await card(page).getByText('成员完整公开来源与保存值',{exact:true}).first().click();await card(page).getByText('双方案参数、归一化记录与 artifact/pair 摘要',{exact:true}).click();
 for(const v of ['parsed-opt-a','parsed-freq-a','obs-opt-a','obs-freq-a','source_pair_sha256','population-artifact'])await expect(card(page)).toContainText(v);
 expect(requests.every(r=>r.method==='GET')).toBe(true);for(const k of ['lifecycle','populations','thermodynamics'])expect(requests.filter(r=>r.path.endsWith('/'+k))).toHaveLength(1);
 await expect(card(page).locator('input,button,select')).toHaveCount(0);await expect(page.locator('.native-thermochemistry')).toContainText('-157.9987654321');
 await page.screenshot({path:'test-results/reliability-synthetic-desktop.png',fullPage:true});
 await axes(page).screenshot({path:'test-results/reliability-synthetic-axes.png'});
 await card(page).screenshot({path:'test-results/reliability-synthetic-populations.png'});
});
for(const variant of ['missing-running-pending','failed-absent-collected','unknown-read','collected-before-core-terminal'])test(`three axes ${variant}`,async({page})=>{
 const l=lifecycle(),r=l.data.result;
 if(variant==='missing-running-pending'){Object.assign(r.program,{availability:'missing',reason:'program-completion-not-captured',evidence_refs:[],state:'unknown',completed_at:null,exit_code:null});Object.assign(r.collection,{state:'pending',condition:'awaiting_scheduler_absence',result_id:null,evidence_refs:['assessment']});}
 if(variant==='failed-absent-collected'){Object.assign(r.program,{state:'failed',exit_code:1});Object.assign(r.scheduler,{state:'absent',presence:'absent'});}
 if(variant==='unknown-read'){Object.assign(r.scheduler,{availability:'unavailable',reason:'scheduler-read-unknown',state:'unknown',presence:'unknown'});Object.assign(r.collection,{availability:'unavailable',reason:'collection-acquisition-unknown',state:'unknown',condition:'reconciliation_required',result_id:null,evidence_refs:['assessment']});}
 await setup(page,{lifecycle:l});await connect(page);await expect(axes(page).getByLabel('program')).toContainText(r.program.state);await expect(axes(page).getByLabel('scheduler')).toContainText(r.scheduler.state);await expect(axes(page).getByLabel('collection')).toContainText(r.collection.state);await expect(axes(page).getByRole('alert')).toHaveCount(0);
});
for(const reason of ['not-registered','backend-unavailable'])test(`unavailable ${reason}`,async({page})=>{const l=lifecycle(),p=populations();Object.assign(l.data,{availability:'unavailable',reason,result:null});Object.assign(p.data,{availability:'unavailable',reason,result:null,selected_member_id:null});await setup(page,{lifecycle:l,populations:p});await connect(page);await expect(card(page)).toContainText(reason);await expect(axes(page)).toContainText(reason);await expect(card(page).locator('table')).toHaveCount(0);});
for(const changes of [{status:422},{body:'{bad'}])test(`bad response ${JSON.stringify(changes)}`,async({page})=>{await setup(page,changes);await connect(page);await expect(card(page).getByRole('alert')).toBeVisible();await expect(axes(page).getByRole('alert')).toBeVisible();await expect(page.locator('.native-thermochemistry')).toBeVisible();});
const invalid:Record<string,(v:any)=>void>={missing:v=>delete v.data.result,extra:v=>v.private_path='/must-not-display',schema:v=>v.schema='future/2',source:v=>v.data.source_id='foreign',attempt:v=>v.data.attempt_id='freq-b',reference:v=>v.data.result.reference_member_id='foreign',member:v=>v.data.result.members[1].member_id='member-a',selected:v=>v.data.selected_member_id='member-b',sourceBinding:v=>v.data.result.members[0].source.frequency_attempt_id='foreign',privateSource:v=>v.data.result.members[0].source.path='/must-not-display',extraGas:v=>v.data.result.parameters.gas_constant_binding.private=true,boolNumber:v=>v.data.result.members[0].rrho.delta_g_hartree=true,nonfinite:v=>v.data.result.members[0].qrrho.gibbs_free_energy_hartree=Infinity,fractionalG:v=>v.data.result.members[0].degeneracy=1.5,sigma:v=>v.data.result.members[0].reported_rotational_symmetry_number=0,population:v=>v.data.result.members[0].rrho.normalized_population=1.2,normalization:v=>v.data.result.normalization.rrho.numeric_tolerance=0.01,acceptance:v=>v.data.result.scientific_acceptance='accepted',pairMismatch:v=>v.data.result.source_pair_sha256='c'.repeat(64)};
for(const [name,mutate] of Object.entries(invalid))test(`population closed contract ${name}`,async({page})=>{const p=populations();mutate(p);await setup(page,{populations:p});await connect(page);await expect(card(page).getByRole('alert')).toContainText('contract-mismatch');await expect(card(page).locator('table')).toHaveCount(0);await expect(card(page)).not.toContainText('/must-not-display');});
const badAxes:Record<string,(v:any)=>void>={exitRange:v=>Object.assign(v.data.result.program,{exit_code:256,state:'failed'}),signalRange:v=>Object.assign(v.data.result.program,{exit_code:null,signal:65,state:'failed'}),dateShort:v=>v.data.result.program.completed_at='123',dateCalendar:v=>v.data.result.program.completed_at='2026-02-30T01:00:00.000000Z',dateFormat:v=>v.data.result.program.completed_at='2026-10-12T01:00:00Z',missingFetch:v=>v.data.result.collection.evidence_refs=['captured'],wrongOrder:v=>v.data.result.collection.evidence_refs=['fetch','stat','restat','captured'],schema:v=>v.data.result.schema='future/2',time:v=>v.data.result.scheduler.observed_at='2026-10-12',rawR:v=>v.data.result.scheduler.raw_state='R',inferredRunning:v=>v.data.result.program.state='running',badExit:v=>v.data.result.program.exit_code=true,extra:v=>v.data.result.collection.raw='/must-not-display',source:v=>v.data.source_id='foreign',missing:v=>delete v.data.result.program.reason,duplicateEvidence:v=>v.data.result.program.evidence_refs=['same','same'],badState:v=>v.data.result.collection.state='failed'};
for(const [name,mutate] of Object.entries(badAxes))test(`lifecycle closed contract ${name}`,async({page})=>{const l=lifecycle();mutate(l);await setup(page,{lifecycle:l});await connect(page);await expect(axes(page).getByRole('alert')).toContainText('contract-mismatch');await expect(axes(page).locator('article')).toHaveCount(0);});
test('member switch and list do not retain stale panels',async({page})=>{const requests=await setup(page);await connect(page);await expect(card(page)).toContainText('当前成员：member-a');await page.evaluate(()=>{location.hash='#/native/saved/attempts/freq-b'});await expect(card(page)).toContainText('当前成员：member-b');await expect(card(page).locator('article h3')).toHaveText(['member-a','member-b · 当前成员']);await page.evaluate(()=>{location.hash='#/native/saved/projects/project'});await expect(card(page)).toHaveCount(0);expect(requests.filter(r=>r.path.endsWith('/populations'))).toHaveLength(2);});
test('narrow synthetic layout',async({page})=>{await page.setViewportSize({width:375,height:812});await setup(page);await connect(page);await expect(card(page)).toContainText('pair hash 已匹配');await card(page).getByText('双方案参数、归一化记录与 artifact/pair 摘要',{exact:true}).click();await page.screenshot({path:'test-results/reliability-synthetic-mobile.png',fullPage:true});await card(page).screenshot({path:'test-results/reliability-synthetic-mobile-panel.png'});expect(await card(page).locator('td').evaluateAll(cells=>cells.every(c=>getComputedStyle(c).whiteSpace==='nowrap'))).toBe(true);expect(await card(page).locator('.native-population-scroll').first().evaluate(e=>e.scrollWidth>e.clientWidth)).toBe(true);expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);});

test('late old lifecycle and population responses cannot cross member navigation; two slots',async({page})=>{
 const requests=await setup(page);let release!:()=>void;const gate=new Promise<void>(r=>release=r);let active=0,max=0;
 await page.route(/\/(lifecycle|populations)$/,async route=>{const path=route.request().url(),kind=path.endsWith('lifecycle')?'lifecycle':'populations',old=path.includes('freq-a');active++;max=Math.max(max,active);if(old)await gate;active--;const value=kind==='lifecycle'?lifecycle(old?'freq-a':'freq-b'):populations(old?'freq-a':'freq-b');await route.fulfill({json:value});});
 await connect(page);await expect(card(page).getByRole('status')).toBeVisible();await page.evaluate(()=>{location.hash='#/native/saved/attempts/freq-b'});
 release();await expect(card(page)).toContainText('当前成员：member-b');await expect(card(page)).not.toContainText('当前成员：member-a');expect(max).toBeLessThanOrEqual(2);expect(requests.every(r=>r.method==='GET')).toBe(true);
});
test('new panels retain 120 second deadline and never retry',async({page})=>{
 await page.clock.install();await setup(page);let release!:()=>void;const gate=new Promise<void>(r=>release=r);let count=0;
 await page.route(/\/(lifecycle|populations)$/,async route=>{count++;await gate;await route.fulfill({json:route.request().url().endsWith('lifecycle')?lifecycle():populations()}).catch(()=>{});});
 await connect(page);await expect(card(page).getByRole('status')).toBeVisible();await page.clock.fastForward(119000);await expect(card(page).getByRole('status')).toBeVisible();await page.clock.fastForward(1001);await expect(card(page).getByRole('alert')).toContainText('读取超时（120 秒）');await expect(axes(page).getByRole('alert')).toContainText('读取超时（120 秒）');expect(count).toBe(2);release();
});
