import {chromium} from '@playwright/test';
import {mkdir,writeFile,readFile} from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
const [origin,destination,installedPackage]=process.argv.slice(2);
if(!/^http:\/\/127\.0\.0\.1:(8767|8769)$/.test(origin)||!path.isAbsolute(destination)||!path.isAbsolute(installedPackage))throw Error('explicit local origin, output and package required');
await mkdir(destination,{recursive:true});
const browser=await chromium.launch({channel:'chrome',headless:true});
const context=await browser.newContext({viewport:{width:1440,height:1000}}),page=await context.newPage();
const errors=[],writes=[];page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(r.url().includes('/api/')&&r.method()!=='GET')writes.push(r.url());});
const checks=[];const get=async p=>{const r=await context.request.get(origin+p);assert.equal(r.status(),200,p);return r.json();};
try{
 const caps=await get('/api/capabilities');assert.equal(caps.version,'0.26.0+local.1');assert.equal(caps.features.execution,false);assert.equal(caps.features.v31_dag,false);checks.push('actual-capabilities');
 await page.goto(origin+'/#/capabilities');await page.getByRole('heading',{name:'工作台能力与版本'}).waitFor();await page.getByText('0.26.0+local.1',{exact:true}).waitFor();await page.screenshot({path:path.join(destination,'capabilities.png')});
 for(const asset of await page.locator('script[src],link[rel=stylesheet]').evaluateAll(es=>es.map(e=>e.getAttribute('src')??e.getAttribute('href')))){
  const r=await context.request.get(origin+asset),bytes=await r.body(),local=await readFile(path.join(installedPackage,'ui',asset));assert.equal(createHash('sha256').update(bytes).digest('hex'),createHash('sha256').update(local).digest('hex'));}checks.push('installed-assets-match');
 const list=await get('/api/archives');assert.equal(list.items.length,83);let selected;
 for(const row of list.items){const a=await get('/api/archives/'+encodeURIComponent(row.archive_id)+'/analysis');if(a.availability==='available'&&a.data.segments.some(s=>s.points.length>1)){selected=row;break;}}
 assert(selected);await page.goto(origin+'/#/archives/'+encodeURIComponent(selected.archive_id));await page.getByRole('button',{name:'导出结果与来源 JSON'}).waitFor();await page.getByRole('button',{name:'读取报错与优化轨迹',exact:true}).click();await page.getByLabel('优化步骤').waitFor();await page.getByLabel('优化步骤').selectOption('1');await page.getByRole('heading',{name:'修复输入预览',exact:true}).waitFor();await page.locator('.calculation-analysis').screenshot({path:path.join(destination,'real-analysis.png')});checks.push('real-analysis-repair-export');
 for(const hash of ['#/drafts','#/offline-science','#/screening']){await page.goto(origin+'/'+hash);await page.locator('h1').waitFor();await page.screenshot({path:path.join(destination,hash.slice(2)+'.png')});}
 await page.setViewportSize({width:390,height:844});for(const hash of ['#/drafts','#/offline-science','#/capabilities']){await page.goto(origin+'/'+hash);await page.locator('h1').waitFor();assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));}await page.screenshot({path:path.join(destination,'mobile.png')});checks.push('new-pages-mobile');
 assert.deepEqual(writes,[]);assert.deepEqual(errors,[]);checks.push('no-http-writes','no-page-errors');
 await writeFile(path.join(destination,'receipt.json'),JSON.stringify({status:'PASS',origin,checks,capabilities:caps,writes,errors},null,2));console.log(JSON.stringify({status:'PASS',checks}));
}catch(error){await page.screenshot({path:path.join(destination,'failure.png'),fullPage:true});await writeFile(path.join(destination,'failure.txt'),await page.locator('body').innerText());throw error;}finally{await context.close();await browser.close();}
