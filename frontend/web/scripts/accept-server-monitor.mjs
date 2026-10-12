// Explicit real, read-only acceptance against the installed localhost service.
import {chromium,expect} from '@playwright/test';
import {readFile,writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import path from 'node:path';
const directory=process.argv[2],port=Number(process.argv[3]);
if(!path.isAbsolute(directory)||![8767,8768].includes(port))throw Error('explicit candidate and local port required');
const origin=`http://127.0.0.1:${port}`,sha=b=>createHash('sha256').update(b).digest('hex');
const get=async p=>{const r=await fetch(origin+p,{headers:{Connection:'close'}});expect(r.status).toBe(200);return r.json();};
const fixed=JSON.parse(await readFile(path.join(directory,'data-before.json'),'utf8'));
const receipt=JSON.parse(await readFile(path.join(directory,'dist/frontend-wheel-receipt.json'),'utf8'));
for(const [name,digest] of Object.entries(receipt.files).filter(([p])=>p.startsWith('autog_frontend/ui/'))){
  const p=name.replace('autog_frontend/ui/','');let b=Buffer.from(await(await fetch(origin+'/'+(p==='index.html'?'':p),{headers:{Connection:'close'}})).arrayBuffer());
  if(p==='index.html')b=Buffer.from(b.toString().replace('<meta name="autog-access" content="local-no-token">',''));
  expect(sha(b)).toBe(digest);
}
const initial=await get('/api/monitor');expect(initial.state).toBe('fresh');expect(initial.sample.hostname).toBe('master');expect(initial.sample.issues).toEqual([]);expect(initial.history.length).toBeGreaterThanOrEqual(2);
expect(initial.sample.metrics.logical_cpus).toBe(44);expect(initial.sample.metrics.memory_total_mib).toBeGreaterThan(100000);
const browser=await chromium.launch({channel:'chrome'}),errors=[],writes=[];
try{
  const p=await browser.newPage({viewport:{width:1440,height:900}});
  p.on('pageerror',e=>errors.push(e.message));p.on('request',r=>{if(r.url().includes('/api/')&&r.method()!=='GET')writes.push(r.method());});
  await p.goto(origin+'/#/monitor');await expect(p.getByRole('status')).toHaveText('采样正常');await expect(p.locator('.monitor-kpis')).toContainText('44 个逻辑核');await expect(p.locator('.monitor-queue')).toContainText('user100');await expect(p.locator('.monitor-page tbody')).toContainText('l502.exe');
  await expect(p.locator('.monitor-evidence')).not.toHaveAttribute('open','');await expect(p.locator('.monitor-trend polyline').first()).toBeVisible();
  expect(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await p.screenshot({path:path.join(directory,`monitor-desktop-${port}.png`),fullPage:true});
  await p.setViewportSize({width:390,height:844});expect(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await p.screenshot({path:path.join(directory,`monitor-mobile-${port}.png`),fullPage:true});
  await p.getByRole('link',{name:'工作流'}).click();await expect(p.getByRole('heading',{name:/项目库/})).toBeVisible();
  expect(errors).toEqual([]);expect(writes).toEqual([]);
}finally{await browser.close();}
for(const [p,digest] of Object.entries(fixed))expect(sha(await readFile(p))).toBe(digest);
const result={status:'PASS',origin,sampled_at:initial.sample.sampled_at,raw_sha256:initial.sample.raw_sha256,history_points:initial.history.length,real_ssh_sample:true,installed_assets_match:true,scientific_data_unchanged:true,mobile_no_overflow:true,no_http_writes:true};
await writeFile(path.join(directory,`monitor-acceptance-${port}.json`),JSON.stringify(result,null,2)+'\n');console.log(result);
