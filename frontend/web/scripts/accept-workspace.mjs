// Nankai UI: exact HTTP evidence plus workflow/results browsing and coordinate interaction.
// The clipboard must contain that launcher's fresh session token; never persist it.
import { chromium, expect } from '@playwright/test';
import { readFile, stat, readdir, writeFile } from 'node:fs/promises';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import path from 'node:path';
const directory = process.argv[2];
if (!directory || !path.isAbsolute(directory)) throw new Error('Pass absolute private evidence directory');
const root = path.resolve(directory, '../..');
const json = async file => JSON.parse(await readFile(file, 'utf8'));
const profile = await json(path.join(directory, 'profile.json'));
const catalog = await json(profile.evidence_catalog);
const index = await json(profile.archive_index);
const previous = await json(path.join(root, '.local/real-gaussian-installed-acceptance/expectations.json'));
const expected = Object.fromEntries(await Promise.all(['attempt','archive'].map(async k => [k, await json(path.join(directory, k+'-expected.json'))])));
const files = [...new Set([profile.database, profile.archive_index, profile.evidence_catalog,
  ...catalog.entries.flatMap(e => Object.values(e).filter(v => v && typeof v === 'object' && v.path).map(v => v.path))])];
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
async function fingerprint() {
  return Promise.all(files.map(async file => { const s=await stat(file,{bigint:true}); return {
    sha256:sha(await readFile(file)),size:String(s.size),inode:String(s.ino),mtime_ns:String(s.mtimeNs),ctime_ns:String(s.ctimeNs),
    directory_entries:(await readdir(path.dirname(file))).sort()}; }));
}
// Write screenshots/receipts to a distinct child so evidence-directory entries stay fixed.
const output = path.join(directory,'acceptance');
const before = await fingerprint();
const token=execFileSync('/usr/bin/pbpaste',{encoding:'utf8'}).trim();
if (!/^[A-Za-z0-9_-]{32,256}$/.test(token)) throw new Error('Fresh preview token required');
const origin=`http://127.0.0.1:${profile.port}`;
const get=async url=>{const r=await fetch(origin+url,{headers:{Authorization:`Bearer ${token}`}});expect(r.status).toBe(200);return r.json();};
expect((await fetch(origin+'/api/projects')).status).toBe(401);
for(const [url,dto] of Object.entries(previous.expected)) expect(await get(url)).toEqual(dto);
expect((await get('/api/archives')).items).toHaveLength(1);
expect((await get('/api/archives/'+index.records[0].archive_id)).data).toEqual(index.records[0]);
for(const entry of catalog.entries){
  const base='/api/'+(entry.kind==='attempt'?'attempts':'archives')+'/'+encodeURIComponent(entry.id);
  expect(await get(base+'/details')).toEqual(expected[entry.kind]);
  const log=(await get(base+'/log')).log;
  expect(log.availability).toBe('available');
  const bytes=await readFile(entry.log.path);
  expect(sha(bytes)).toBe(entry.log.sha256);expect(log.data.text).toBe(bytes.toString('utf8'));
  expect(log.data.line_count).toBe(bytes.toString('utf8').trimEnd().split(/\r?\n/).length);
}
expect(expected.attempt.result.data.frequencies_cm1).toEqual([2017.6012,3611.7356,3835.6281]);
expect(Object.keys(expected.attempt.result.data.thermochemistry)).toHaveLength(7);
expect(expected.attempt.result.data.last_geometry.atoms).toHaveLength(3);
expect(expected.attempt.review.data.classification).toBe('VALIDATED_MINIMUM');
expect(expected.attempt.review.data.acceptances[0].review_evidence.scope).toBe('v30-a-first-live-plumbing-smoke-test');
expect(expected.attempt.execution.data.resources).toEqual({cores:4,memory_mb:2048,walltime_seconds:1800,queue:'batch'});
expect(expected.attempt.execution.data.receipts.at(-1).job_id).toBe('681.master');
expect(expected.archive.result.data.last_geometry.atoms).toHaveLength(17);
expect(expected.archive.result.data.frequencies_cm1).toEqual([]);
expect(expected.archive.review.availability).toBe('unavailable');
expect(expected.archive.execution.data.scheduler.job_id).toBe('562.master');
const browser=await chromium.launch({channel:'chrome'});
try {
  const page=await browser.newPage({viewport:{width:1440,height:1000}});const errors=[],methods=[];
  page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')errors.push(m.text());});
  page.on('request',r=>{if(r.url().includes('/api/'))methods.push(r.method());});
  await page.goto(origin+'/#/attempts/'+expected.attempt.id);
  await page.getByLabel('只读访问令牌').fill(token);await page.getByRole('button',{name:'连接数据源'}).click();
  for(const kind of ['attempt','archive']){
    const d=expected[kind];
    if(kind==='archive')await page.goto(origin+'/#/archives/'+d.id);
    await expect(page.getByRole('heading',{name:'完整结果与历史证据'})).toBeVisible();
    await expect(page.getByTestId('full-geometry').locator('tbody tr')).toHaveCount(d.result.data.last_geometry.atoms.length);
    if(kind==='attempt'){
      await expect(page.getByTestId('full-frequencies').locator('tbody tr')).toHaveCount(3);
      for(const value of d.result.data.frequencies_cm1)await expect(page.getByTestId('full-frequencies')).toContainText(String(value));
      for(const v of Object.values(d.result.data.thermochemistry))await expect(page.getByTestId('full-thermochemistry')).toContainText(String(v.value_hartree));
      await expect(page.getByTestId('review-evidence')).toContainText('v30-a-first-live-plumbing-smoke-test');
      await expect(page.getByTestId('review-evidence')).toContainText('not research-quality scientific result');
      await expect(page.getByTestId('execution-evidence')).toContainText('681.master');
    }else{
      await expect(page.getByTestId('full-frequencies')).toHaveCount(0);
      await expect(page.getByTestId('review-evidence')).toContainText('尚无绑定');
      await expect(page.getByTestId('execution-evidence')).toContainText('562.master');
    }
    await page.getByRole('button',{name:'读取已归档日志'}).click();await expect(page.getByTestId('raw-log')).toBeVisible();
    await page.getByLabel('搜索日志',{exact:true}).fill('SCF Done');await page.getByRole('button',{name:'下一个匹配'}).click();
    await expect(page.locator('.selected-line')).toContainText('SCF Done');
    await page.getByRole('button',{name:'最后一次正常终止'}).click();await expect(page.locator('.selected-line')).toContainText('Normal termination');
    await page.setViewportSize({width:1440,height:1000});
    await page.getByRole('heading',{name:'完整结果与历史证据'}).scrollIntoViewIfNeeded();
    await page.screenshot({path:path.join(output,kind+'-desktop.png')});
    await page.setViewportSize({width:390,height:844});
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    await page.getByRole('heading',{name:'完整结果与历史证据'}).scrollIntoViewIfNeeded();
    await page.screenshot({path:path.join(output,kind+'-mobile.png')});
    await page.getByTestId('raw-log').screenshot({path:path.join(output,kind+'-log.png')});
  }
  await page.setViewportSize({width:1440,height:1050});
  await page.goto(origin+'/#/attempts/'+expected.attempt.id);
  const geometry=expected.attempt.result.data.last_geometry;
  await expect(page.getByTestId('molecule-atom')).toHaveCount(geometry.atoms.length);
  for(const a of geometry.atoms)await expect(page.locator(`[data-testid="molecule-atom"][data-center="${a.center}"] title`)).toContainText(`${a.x}, ${a.y}, ${a.z} Å`);
  const distance=g=>Math.hypot(g.atoms[0].x-g.atoms[1].x,g.atoms[0].y-g.atoms[1].y,g.atoms[0].z-g.atoms[1].z).toFixed(4)+' Å';
  await page.getByLabel('测距原子 A').selectOption(String(geometry.atoms[0].center));await page.getByLabel('测距原子 B').selectOption(String(geometry.atoms[1].center));
  await expect(page.getByTestId('atom-distance')).toHaveText(distance(geometry));
  await page.getByTestId('molecule-scene').focus();await page.keyboard.press('ArrowRight');await page.getByRole('button',{name:'放大结构'}).click();await expect(page.getByTestId('atom-distance')).toHaveText(distance(geometry));
  await page.getByLabel('结构来源').selectOption('review');const reviewed=expected.attempt.review.data.selected_final_geometry;
  await expect(page.getByTestId('atom-distance')).toHaveText('选择两个原子');
  await page.getByText('当前结构来源与字节区间',{exact:true}).click();expect(JSON.parse(await page.locator('.molecule-section pre').textContent()).source_span).toEqual(reviewed.source_span);
  await page.getByRole('button',{name:'工作流与输入',exact:true}).click();await expect(page.getByRole('heading',{name:'状态与来源',exact:true})).toBeVisible();
  await page.screenshot({path:path.join(output,'workflow-desktop.png')});
  await page.getByRole('button',{name:'结果与分子结构',exact:true}).click();await page.locator('.molecule-section').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(output,'molecule-desktop.png')});
  await page.setViewportSize({width:390,height:844});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);await page.locator('.molecule-stage').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(output,'molecule-mobile.png')});
  await page.getByRole('link',{name:'结果工作台'}).click();await page.getByLabel('结果项目').selectOption(previous.project_id);
  await page.getByRole('textbox',{name:'搜索计算结果',exact:true}).fill(expected.attempt.id);await expect(page.locator('tbody tr')).toHaveCount(1);
  await expect(page.locator('tbody')).toContainText('-75.3227750502');await expect(page.locator('tbody')).toContainText('3 / 0');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:path.join(output,'results-mobile.png')});
  await page.setViewportSize({width:1440,height:1050});await page.getByRole('button',{name:'清除筛选'}).click();await expect(page.locator('tbody tr')).toHaveCount(4);
  await page.screenshot({path:path.join(output,'results-desktop.png')});
  await page.getByRole('button',{name:'断开',exact:true}).click();await expect(page.getByTestId('raw-log')).toHaveCount(0);
  await expect(page.getByTestId('full-geometry')).toHaveCount(0);expect(errors).toEqual([]);expect(methods.every(m=>m==='GET')).toBe(true);
  expect(await fingerprint()).toEqual(before);
  const installed=await json(path.join(directory,'installed-verification.json'));
  const receipt={schema:'autog-nankai-workspace-acceptance/1',status:'PASS',observed_at:new Date().toISOString(),
    runtime:installed,exact_http_routes:Object.keys(previous.expected).length+6,unchanged_source_files:files.length,
    source_fingerprints:before.map(({directory_entries,...f})=>f),browser_errors:0,only_get:true,
    native_and_archive_logs_exact:true,full_results_match:true,historical_review_scope_preserved:true,
    historical_job_resources_match:true,desktop_and_mobile:true,disconnect_clears:true,
    workflow_and_results_navigation:true,visible_result_summary_exact:true,coordinate_atoms_exact:true,
    measurement_from_original_coordinates:true,rotation_zoom_preserve_distance:true,review_geometry_source_exact:true,
    scientific_acceptance_created:false,live_scheduler_queried:false};
  await writeFile(path.join(output,'receipt.json'),JSON.stringify(receipt,null,2)+'\n',{flag:'wx'});
  console.log(JSON.stringify({status:receipt.status,routes:receipt.exact_http_routes,unchanged_sources:files.length,browser_errors:0}));
}finally{await browser.close();}
