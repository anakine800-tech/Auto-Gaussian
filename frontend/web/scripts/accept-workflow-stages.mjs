import {chromium,expect} from '@playwright/test';
import {readFile,writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import path from 'node:path';
const directory=process.argv[2],port=Number(process.argv[3]);
if(!path.isAbsolute(directory)||![8767,8768].includes(port))throw Error('explicit candidate and port required');
const origin=`http://127.0.0.1:${port}`,sha=b=>createHash('sha256').update(b).digest('hex');
const get=async p=>{const r=await fetch(origin+p,{headers:{Connection:'close'}});expect(r.status).toBe(200);return r.json();};
const receipt=JSON.parse(await readFile(path.join(directory,'dist/frontend-wheel-receipt.json'),'utf8'));
for(const [name,digest] of Object.entries(receipt.files).filter(([p])=>p.startsWith('autog_frontend/ui/'))){
 const p=name.replace('autog_frontend/ui/','');let b=Buffer.from(await(await fetch(origin+'/'+(p==='index.html'?'':p),{headers:{Connection:'close'}})).arrayBuffer());if(p==='index.html')b=Buffer.from(b.toString().replace('<meta name="autog-access" content="local-no-token">',''));expect(sha(b)).toBe(digest);
}
const dto=await get('/api/workflows');expect(dto.layout).toEqual({schema:'autog-workflow-layout/1',availability:'unavailable',reason:'v31-workflow-source-not-connected',nodes:[],edges:[]});
const target=dto.tasks.find(t=>t.task_kind==='gaussian-opt-freq');expect(target).toBeTruthy();
const browser=await chromium.launch({channel:'chrome'}),errors=[],writes=[];
try{
 const p=await browser.newPage({viewport:{width:1440,height:900}});p.on('pageerror',e=>errors.push(e.message));p.on('request',r=>{if(r.url().includes('/api/')&&r.method()!=='GET')writes.push(r.method());});
 await p.goto(origin+'/#/workflows');await expect(p.getByRole('heading',{name:'运行总览',exact:true})).toBeVisible();await expect(p.getByRole('button',{name:'阶段：优化',exact:true})).toContainText('1 个任务');await expect(p.getByRole('button',{name:'阶段：频率',exact:true})).toContainText('1 个任务');
 await expect(p.locator('.wf-groups')).not.toHaveAttribute('open','');await p.screenshot({path:path.join(directory,`stages-overview-${port}.png`),fullPage:true});
 await p.getByRole('button',{name:'阶段：频率',exact:true}).click();await p.getByRole('button',{name:`展开 ${target.attempts.length} 次尝试`,exact:true}).click();const a=target.attempts.at(-1);await p.getByRole('button',{name:`Attempt ${a.ordinal} · 查看证据`,exact:false}).click();
 await p.locator('.wf-task-stage-context>summary').click();await expect(p.locator('.wf-task-stage-context')).toContainText('优化 + 频率');await expect(p.locator('.wf-task-stage-context')).toContainText('流程依赖与阶段证据尚未接入');
 await p.getByRole('link',{name:'科学结果 / 振动 / 原日志'}).click();await expect(p.getByRole('heading',{name:/计算记录/})).toBeVisible();await p.goBack();await expect(p.getByRole('button',{name:'阶段：频率',exact:true})).toHaveAttribute('aria-pressed','true');
 await p.locator('.wf-groups>summary').click();await p.getByText('查看分支布局示例（非项目数据）',{exact:true}).click();await expect(p.locator('.wf-demo-note')).toContainText('虚构');await p.screenshot({path:path.join(directory,`stages-example-${port}.png`),fullPage:true});
 await p.setViewportSize({width:390,height:844});expect(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);await p.screenshot({path:path.join(directory,`stages-mobile-${port}.png`),fullPage:true});expect(errors).toEqual([]);expect(writes).toEqual([]);
}finally{await browser.close();}
const before=JSON.parse(await readFile(path.join(directory,'data-before.json'),'utf8'));for(const [p,digest] of Object.entries(before))expect(sha(await readFile(p))).toBe(digest);
const result={status:'PASS',origin,installed_assets_match:true,real_combined_task_classified:true,actual_layout_source:'unavailable',synthetic_example_isolated:true,stage_filter_retained:true,mobile_no_overflow:true,scientific_files_unchanged:true,no_http_writes:true};await writeFile(path.join(directory,`stages-acceptance-${port}.json`),JSON.stringify(result,null,2)+'\n');console.log(result);
