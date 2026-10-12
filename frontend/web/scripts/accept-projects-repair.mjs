import {chromium,expect} from '@playwright/test';
import {readFile,writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
const out=process.argv[2],port=Number(process.argv[3]??8768),dist=process.argv[4]??'dist';
if(![8767,8768].includes(port)||!['dist','dist-r2','dist-r3'].includes(dist))throw Error('explicit local candidate required');
const origin='http://127.0.0.1:'+port;
const fetchLocal=url=>fetch(url,{headers:{Connection:'close'}});
const get=async path=>{const r=await fetchLocal(origin+path);expect(r.status).toBe(200);return r.json();};
const profile=JSON.parse(await readFile(out+'/profile.json','utf8'));
const paths=[profile.database,profile.archive_index,profile.evidence_catalog];
const sha=b=>createHash('sha256').update(b).digest('hex');
const before=Object.fromEntries(await Promise.all(paths.map(async p=>[p,sha(await readFile(p))])));
const build=JSON.parse(await readFile(out+'/'+dist+'/frontend-wheel-receipt.json','utf8'));
for(const [name,digest] of Object.entries(build.files).filter(([p])=>p.startsWith('autog_frontend/ui/'))){
 const url=name.replace('autog_frontend/ui/','');let bytes=Buffer.from(await(await fetchLocal(origin+'/' +(url==='index.html'?'':url))).arrayBuffer());
 if(url==='index.html')bytes=Buffer.from(bytes.toString().replace('<meta name="autog-access" content="local-no-token">',''));
 expect(sha(bytes)).toBe(digest);
}
const catalog=await get('/api/project-library'),archives=await get('/api/archives');
expect(catalog.snapshot.content_sha256).toMatch(/^[a-f0-9]{64}$/);expect(catalog.snapshot.latest_archive_capture).toBeTruthy();
const browser=await chromium.launch({channel:'chrome'}),errors=[],writes=[],httpFailures=[];
let receipt;
try{
const page=await browser.newPage({viewport:{width:1440,height:960}});page.on('pageerror',e=>errors.push(e.message));page.on('response',r=>{if(r.url().includes('/api/')&&r.status()>=400)httpFailures.push({url:r.url(),status:r.status()});});page.on('request',r=>{if(r.url().includes('/api/')&&r.method()!=='GET')writes.push(r.method());});
await page.goto(origin+'/#/projects');await expect(page.locator('.organized-card').first()).toBeVisible();
await page.getByLabel('状态筛选').selectOption('unparseable');await expect(page.locator('.member-row').first()).toBeVisible();await expect(page.locator('.member-row').first()).toContainText('unparseable');
for(const width of [390,320]){await page.setViewportSize({width,height:900});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);expect(await page.locator('.collection-members').evaluateAll(es=>es.every(e=>e.scrollWidth<=e.clientWidth))).toBe(true);await page.screenshot({path:out+'/projects-'+width+'.png',fullPage:true});}
await page.setViewportSize({width:1440,height:960});
const b5=catalog.items.find(g=>g.kind==='historical'&&g.label.startsWith('b5'));
expect(b5).toBeTruthy();await page.goto(origin+'/#/history-projects/'+b5.id);await page.locator('tbody a').first().click();await expect(page.getByRole('navigation',{name:'来源项目'})).toContainText('返回 '+b5.label);
await page.getByRole('link',{name:'返回 '+b5.label,exact:true}).click();await page.getByLabel('结果项目').selectOption('');await expect(page.locator('.science-index')).toBeVisible();await expect(page.getByLabel('结果用途',{exact:true})).toHaveValue('all');
const native=catalog.items.find(g=>g.kind==='native');expect(native).toBeTruthy();await page.goto(origin+'/#/projects/'+encodeURIComponent(native.id));
const attempts=await get('/api/projects/'+encodeURIComponent(native.id)+'/attempts');const last=attempts.data.items.find(a=>a.ordinal===4);expect(last).toBeTruthy();
const row=page.locator('tr').filter({has:page.getByRole('link',{name:'Attempt 4'})});await expect(row).toContainText('摘要可读');await expect(row).toContainText('B3LYP');await expect(row).toContainText('STO-3G');await expect(row).toContainText('不是研究级结果');
await page.screenshot({path:out+'/native-list.png',fullPage:true});
await page.goto(origin+'/#/workflows');await page.getByLabel('运行用途').selectOption('all');await page.getByRole('button',{name:'展开 4 次尝试'}).click();await page.getByRole('button',{name:'Attempt 4 · 查看证据'}).click();await expect(page.getByRole('region',{name:'任务详情'})).toContainText('不是研究级结果');await page.screenshot({path:out+'/sidebar.png',fullPage:true});
await page.getByRole('link',{name:'科学结果 / 振动 / 原日志'}).click();await expect(page.getByTestId('science-conditions')).toContainText('B3LYP');await page.getByRole('button',{name:'读取振动模式',exact:true}).click();await expect(page.getByRole('button',{name:'播放模式 1',exact:true})).toBeVisible();await page.getByRole('button',{name:'播放模式 1',exact:true}).click();await expect(page.getByRole('button',{name:'播放模式 1',exact:true})).toHaveAttribute('aria-pressed','true');
expect(writes).toEqual([]);expect(errors).toEqual([]);expect(httpFailures).toEqual([]);
for(const [p,h] of Object.entries(before))expect(sha(await readFile(p))).toBe(h);
receipt={status:'PASS',origin,version:build.version,wheel_sha256:build.wheel_sha256,http_failures:httpFailures,installed_assets_match:true,source_groups:catalog.items.length,archives:archives.items.length,source_snapshot:catalog.snapshot,source_files_unchanged:true,no_http_writes:true,browser_errors:errors,native_attempt4_bound_summary:true,scoped_historical_review:true,verified_breadcrumb:true,all_archive_navigation:true,mobile_member_overflow:false,vibration_read_and_play:true};
}finally{await browser.close();}
await writeFile(out+(port===8767?'/cutover-acceptance.json':'/real-acceptance.json'),JSON.stringify(receipt,null,2)+'\n');console.log(JSON.stringify(receipt,null,2));
