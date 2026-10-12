import {test,expect} from '@playwright/test';
import type {Page} from '@playwright/test';
const token='browser-test-only-'+'0'.repeat(32);
test.skip(process.env.AUTOG_TEST_WORKFLOW!=='1','explicit synthetic workflow fixtures required');
async function connect(p:Page){await p.goto('/#/workflows');await p.getByLabel('只读访问令牌').fill(token);await p.getByRole('button',{name:'连接数据源'}).click();await expect(p.getByRole('heading',{name:'运行总览',exact:true})).toBeVisible();await p.getByLabel('运行项目',{exact:true}).selectOption('workflow-live-project');}
async function open(p:Page){await p.getByRole('button',{name:'展开 1 次尝试'}).click();await p.getByRole('button',{name:'Attempt 1 · 查看证据'}).click();await expect(p.getByRole('region',{name:'任务详情'})).toContainText('workflow-live-attempt');}
test('real API binds before Result, keeps Core unchanged, and exposes timestamped and undated evidence',async({page})=>{
 const writes:string[]=[];page.on('request',r=>{if(r.method()!=='GET')writes.push(r.method());});await connect(page);await open(page);
 const side=page.getByRole('region',{name:'任务详情'});await expect(side).toContainText('历史回执确认');await expect(side).toContainText('运行中');await expect(side).toContainText('计划中');await expect(side).toContainText('回执顺序 1 · 时间未记录');await expect(side).toContainText('ReadOnlyTelemetry');
 await expect(side).toContainText('尚无可用结果');await page.goBack();await expect(side).toHaveCount(0);expect(writes).toEqual([]);
});
test('filters survive detail navigation and returning; dense mobile panels stay within viewport',async({page})=>{
 const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));await page.setViewportSize({width:390,height:844});await connect(page);await page.getByLabel('搜索运行任务',{exact:true}).fill('workflow-live-task');await open(page);
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);await page.getByRole('button',{name:'结构与结果',exact:true}).click();await expect(page.getByRole('heading',{name:/计算记录/})).toBeVisible();await page.goBack();await expect(page.getByLabel('运行项目',{exact:true})).toHaveValue('workflow-live-project');await expect(page.getByLabel('搜索运行任务',{exact:true})).toHaveValue('workflow-live-task');expect(errors).toEqual([]);
});
test('cross-attempt response cannot populate selected side panel',async({page})=>{
 await page.route('**/api/workflows/attempts/workflow-live-attempt',async route=>{const r=await route.fetch(),d=await r.json();d.attempt.attempt_id='other';await route.fulfill({json:d});});await connect(page);await page.getByRole('button',{name:'展开 1 次尝试'}).click();await page.getByRole('button',{name:'Attempt 1 · 查看证据'}).click();await expect(page.getByRole('alert')).toContainText('身份不一致');await expect(page.locator('.wf-selected')).toHaveCount(0);
});
test('stale queue never becomes a current zero-count and disconnected data is labeled',async({page})=>{
 await page.route('**/api/workflows',async route=>{const r=await route.fetch(),d=await r.json();d.monitor_state='stale';d.queue_status='unavailable';d.server_jobs=[];await route.fulfill({json:d});});await connect(page);await expect(page.locator('.wf-summary>div').nth(2)).toContainText('—');await expect(page.getByText('队列明细不可用，不能解释为空队列。')).toBeVisible();
});
test('side panel separates recorded stage evidence from execution evidence without inventing times',async({page})=>{
 await page.route('**/api/workflows',async route=>{const response=await route.fetch(),d=await response.json();d.layout={schema:'autog-workflow-layout/1',availability:'available',reason:null,nodes:[{node_id:'n',project_id:'workflow-live-project',workflow_run_id:'workflow-live-run',stage:'optimization',label:'已记录优化阶段',task_ids:['workflow-live-task'],branch_id:'分支 A',evidence:[{record_id:'plan-record',source:'synthetic-plan',sha256:'a'.repeat(64),recorded_at:'2026-09-25T01:00:00Z'},{record_id:'undated-plan-record',source:'synthetic-dependency',sha256:'b'.repeat(64),recorded_at:null}]}],edges:[]};await route.fulfill({json:d});});
 await connect(page);await page.getByRole('button',{name:'阶段：优化',exact:true}).click();await open(page);await page.locator('.wf-task-stage-context>summary').click();await expect(page.locator('.wf-task-stage-context')).toContainText('分支 A');await expect(page.locator('.wf-task-stage-context')).toContainText('plan-record');await page.getByText('未记录时间的流程证据 · 1',{exact:true}).click();await expect(page.locator('.wf-task-stage-context')).toContainText('时间未记录');await expect(page.locator('.wf-timeline').first()).toContainText('ReadOnlyTelemetry');
});
