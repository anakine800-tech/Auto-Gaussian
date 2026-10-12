import {test,expect} from '@playwright/test';
import type {Page} from '@playwright/test';
const token='browser-test-only-'+'0'.repeat(32);
const ev=(id:string,time:string|null=null)=>({record_id:id,source:'synthetic-workflow-record',sha256:'a'.repeat(64),recorded_at:time});
const task=(id:string,kind:string)=>({task_id:id,task_kind:kind,project_id:'fixture-project',workflow_run_id:'fixture-run',workflow_name:'示例反应路径',attempts:[],dependency_status:'not-projected',current_attempt_id:null});
const tasks=[task('combined','gaussian-opt-freq'),task('opt-freq-in-name-is-not-evidence','unknown-kind'),task('opt-A','gaussian-opt'),task('opt-B','gaussian-opt'),task('freq-A','gaussian-freq'),task('human','scientific-review')];
const empty={schema:'autog-workflow-layout/1',availability:'unavailable',reason:'v31-workflow-source-not-connected',nodes:[],edges:[]};
const node=(id:string,stage:string,taskID:string,branch:string|null)=>({node_id:id,project_id:'fixture-project',workflow_run_id:'fixture-run',stage,label:id+' 节点',task_ids:[taskID],branch_id:branch,evidence:[ev(id+'-record')]});
function graph(){return {schema:'autog-workflow-layout/1',availability:'available',reason:null,nodes:[node('a-opt','optimization','opt-A','构象 A'),node('a-freq','frequency','freq-A','构象 A'),node('b-opt','optimization','opt-B','构象 B'),node('review','review','human',null)],edges:[{from:'a-opt',to:'a-freq',evidence:[ev('dependency-1')]},{from:'a-freq',to:'review',evidence:[ev('dependency-2','2026-09-25T02:00:00Z')]},{from:'b-opt',to:'review',evidence:[ev('dependency-3')]}]};}
async function connect(page:Page,layout:unknown=empty){
 await page.route('**/api/workflows',route=>route.fulfill({json:{schema:'autog-workflow-overview/1',read_at:'2026-09-25T02:00:00Z',tasks,layout,server_jobs:[],queue_status:'unavailable',monitor_state:'unavailable'}}));
 await page.goto('/#/workflows');await page.getByLabel('只读访问令牌').fill(token);await page.getByRole('button',{name:'连接数据源'}).click();await expect(page.getByRole('heading',{name:'运行总览',exact:true})).toBeVisible();await page.getByLabel('运行用途',{exact:true}).selectOption('all');
}
test('stage counts use exact type, allow combined tasks, never invent stage completion',async({page})=>{
 const writes:string[]=[];page.on('request',r=>{if(r.method()!=='GET')writes.push(r.method());});await connect(page);
 await expect(page.getByRole('button',{name:'阶段：优化',exact:true})).toContainText('3 个任务');await expect(page.getByRole('button',{name:'阶段：频率',exact:true})).toContainText('2 个任务');
 await expect(page.getByRole('button',{name:'阶段：构象搜索',exact:true})).toContainText('未记录匹配任务');await expect(page.getByRole('button',{name:'阶段：构象搜索',exact:true})).toContainText('不代表未开始');
 await page.getByRole('button',{name:'阶段：频率',exact:true}).click();await expect(page.locator('.wf-task-table tbody tr')).toHaveCount(2);await expect(page.locator('.wf-task-table')).not.toContainText('opt-freq-in-name');
 await page.getByRole('button',{name:'未分类 · 1',exact:true}).click();await expect(page.locator('.wf-task-table tbody tr')).toHaveCount(1);await expect(page.locator('.wf-task-table')).toContainText('opt-freq-in-name');expect(writes).toEqual([]);
});
test('stage selection persists across routes, independent of search and example selection',async({page})=>{
 await connect(page);await page.getByRole('button',{name:'阶段：优化',exact:true}).click();await page.getByLabel('搜索运行任务',{exact:true}).fill('combined');await page.getByRole('link',{name:'项目与历史目录'}).click();await page.goBack();
 await expect(page.getByRole('button',{name:'阶段：优化',exact:true})).toHaveAttribute('aria-pressed','true');await expect(page.getByLabel('搜索运行任务',{exact:true})).toHaveValue('combined');await expect(page.locator('.wf-task-table tbody tr')).toHaveCount(1);
});
test('branch preview is opt-in, fictional, isolated, and fits mobile',async({page})=>{
 await page.setViewportSize({width:390,height:844});await connect(page);await expect(page.locator('.wf-demo-paths')).not.toBeVisible();await page.locator('.wf-groups>summary').click();await expect(page.locator('.wf-groups')).toContainText('流程依赖接口未接入');await page.getByText('查看分支布局示例（非项目数据）',{exact:true}).click();await page.locator('.wf-demo-step button').first().click();await expect(page.locator('.wf-demo-detail')).toContainText('示例节点');await expect(page.locator('.wf-task-table tbody tr')).toHaveCount(6);
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);await page.screenshot({path:'test-results/workflow-stages-mobile.png',fullPage:true});
});
test('recorded branches expose exact edges and provenance; locate resets conflicting filters',async({page})=>{
 await connect(page,graph());await page.getByRole('button',{name:'阶段：单点能',exact:true}).click();await page.getByLabel('搜索运行任务',{exact:true}).fill('no-match');await page.locator('.wf-groups>summary').click();
 const b=page.locator('.wf-recorded-branches');await b.getByText('构象 A · 2 个节点 · fixture-run',{exact:true}).click();await b.getByText('前置依赖：a-opt 节点 → a-freq 节点',{exact:true}).click();await expect(b).toContainText('dependency-1');
 await b.getByRole('button',{name:'freq-A · 定位任务',exact:true}).click();await expect(page.getByLabel('搜索运行任务',{exact:true})).toHaveValue('freq-A');await expect(page.locator('.wf-task-table tbody tr')).toHaveCount(1);await expect(page.locator('.wf-task-table')).toContainText('freq-A');await expect(page.getByRole('button',{name:'全部任务 · 6',exact:true})).toHaveAttribute('aria-pressed','true');
 await page.screenshot({path:'test-results/workflow-stages-desktop.png',fullPage:true});
});
for(const issue of ['cycle','wrong-run','missing-task','duplicate-node','no-evidence','cross-run-edge'] as const)test(`invalid layout ${issue} hides relationships without hiding tasks`,async({page})=>{
 const g=graph();if(issue==='cycle')g.edges.push({from:'review',to:'a-opt',evidence:[ev('bad')]});if(issue==='wrong-run')g.nodes[0].workflow_run_id='other-run';if(issue==='missing-task')g.nodes[0].task_ids=['missing'];if(issue==='duplicate-node')g.nodes.push(g.nodes[0]);if(issue==='no-evidence')g.edges[0].evidence=[];if(issue==='cross-run-edge'){g.nodes[0].project_id='other-project';}
 await connect(page,g);await expect(page.getByRole('alert')).toContainText('停止展示关系');await expect(page.locator('.wf-task-table tbody tr')).toHaveCount(6);await expect(page.locator('.wf-recorded-branches')).toHaveCount(0);
});

test('explicit stage mapping takes priority over display aliases and appears in rows',async({page})=>{
 const g=graph();g.nodes[0].task_ids=['opt-freq-in-name-is-not-evidence'];g.nodes[0].stage='conformer';await connect(page,g);await page.getByRole('button',{name:'阶段：构象搜索',exact:true}).click();await expect(page.locator('.wf-task-table tbody tr')).toHaveCount(1);await expect(page.locator('.wf-task-table tbody tr strong').first()).toHaveText('构象搜索');
});
