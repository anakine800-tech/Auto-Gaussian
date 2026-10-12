import {test,expect} from '@playwright/test';
import type {Page} from '@playwright/test';
const token='browser-test-only-'+'0'.repeat(32);
async function connect(page:Page,hash='#/projects'){await page.goto('/'+hash);await page.getByLabel('只读访问令牌').fill(token);await page.getByRole('button',{name:'连接数据源'}).click();}
const group=(n:number,archive:string)=>({id:'history-'+n,label:'b5_step_'+n,kind:'historical',source_label:'fixture',basis:'source-directory',count:1,task_count:null,states:n===17?['unparseable']:['normal-termination','parsed'],state_counts:n===17?{unparseable:1}:{'normal-termination':1,parsed:1},issue_archive_ids:n===17?[archive]:[],archive_ids:[archive]});
test('slow refresh keeps snapshot, failure offers retry, recovery updates freshness',async({page})=>{
 test.setTimeout(25000);let mode='ok';
 await page.route('**/api/project-library',async r=>{if(mode==='slow'){await new Promise(resolve=>setTimeout(resolve,8200));await r.abort();}else await r.continue();});
 await connect(page);await expect(page.locator('.organized-card').first()).toBeVisible();const before=await page.locator('.organized-projects').innerText();
 await expect(page.locator('.index-freshness')).toContainText('索引内容指纹');mode='slow';await page.getByRole('button',{name:'刷新',exact:true}).click();
 await expect(page.getByText('读取较慢',{exact:false})).toBeVisible();expect(await page.locator('.organized-projects').innerText()).toBe(before);
 await expect(page.getByRole('alert')).toContainText('上次成功快照',{timeout:10000});expect(await page.locator('.organized-projects').innerText()).toBe(before);
 mode='ok';await page.getByRole('button',{name:'重试项目索引'}).click();await expect(page.getByRole('alert')).toHaveCount(0);await expect(page.locator('.organized-card').first()).toBeVisible();
});
test('initial failure has in-place retry and does not claim a snapshot',async({page})=>{
 let failed=true;await page.route('**/api/project-library',r=>failed?r.abort():r.continue());await connect(page);await expect(page.getByRole('alert')).toContainText('尚无可展示快照');failed=false;await page.getByRole('button',{name:'重试项目索引'}).click();await expect(page.locator('.organized-card').first()).toBeVisible();
});
test('long series paginates without horizontal scroll and filtering locates member 18',async({page})=>{
 const groups=Array.from({length:18},(_,i)=>group(i,'archive-'+i.toString(16).padStart(64,'0')));
 await page.route('**/api/project-library',r=>r.fulfill({json:{schema:'autog-project-library/1',items:groups}}));await connect(page);
 await expect(page.getByLabel('搜索项目',{exact:true})).toHaveAttribute('placeholder','搜索名称或标识…');
 for(const width of [390,320]){await page.setViewportSize({width,height:844});const members=page.locator('.collection-members');if(!await members.evaluate(e=>e.hasAttribute('open')))await members.locator(':scope > summary').click();await expect(members.locator('.member-row')).toHaveCount(10);expect(await members.evaluate(e=>e.scrollWidth<=e.clientWidth)).toBe(true);expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);}
 await page.locator('.collection-members').getByRole('button',{name:'下一页',exact:true}).click();await expect(page.locator('.member-row')).toHaveCount(8);
 await page.getByLabel('状态筛选').selectOption('unparseable');await expect(page.locator('.member-row')).toHaveCount(1);await expect(page.locator('.member-row')).toContainText('b5_step_17');await expect(page.locator('.organized-card')).toContainText('异常 / 待核对历史成员：1');
});
test('historical result retains a verified source breadcrumb; all archives opens results',async({page})=>{
 const response=await page.request.get('/api/archives',{headers:{Authorization:'Bearer '+token}});const archives=(await response.json()).items;const g={...group(0,archives[0].archive_id),label:'b5'};
 await page.route('**/api/project-library',r=>r.fulfill({json:{schema:'autog-project-library/1',items:[g]}}));
 await page.route('**/api/project-library/history-0',r=>r.fulfill({json:{schema:'autog-project-library/1',project:g,items:archives}}));
 await connect(page,'#/history-projects/history-0');await page.getByRole('link',{name:archives[0].title,exact:true}).click();await expect(page.getByRole('navigation',{name:'来源项目'})).toContainText('b5');await page.getByRole('navigation',{name:'来源项目'}).getByRole('link',{name:'b5',exact:true}).click();
 await page.getByLabel('结果项目').selectOption('');await expect(page).toHaveURL(/#\/analysis\?project=&tab=results$/);await expect(page.locator('.science-index')).toBeVisible();await expect(page.getByLabel('结果用途',{exact:true})).toHaveValue('all');
});
const review={classification:'VALIDATED_MINIMUM',acceptance_state:'accepted',acceptances:[{review_evidence:{scope:'v30-a-first-live-plumbing-smoke-test',limitations:['仅测试链路']}}]};
test('native list uses bound result despite unavailable Core projection and always shows review scope',async({page})=>{
 await page.route('**/api/projects/gaussian-demo/attempts',async r=>{const d=await(await r.fetch()).json();for(const a of d.data.items){a.declared_science.program={availability:'unavailable',value:null,source:null,reason:'unsupported-evidence-protocol'};a.result_state='unavailable';}await r.fulfill({json:d});});
 await page.route('**/api/attempts/gaussian-normal/details',async r=>{const d=await(await r.fetch()).json();d.review={availability:'available',reason:null,source:{kind:'synthetic-review'},data:review};await r.fulfill({json:d});});
 await connect(page,'#/projects/gaussian-demo');const row=page.locator('tr').filter({has:page.getByRole('link',{name:'Attempt 1'} )}).filter({hasText:'gaussian-normal'});
 await expect(row).toContainText('Gaussian · 绑定结果来源');await expect(row).toContainText('摘要可读');await expect(row).toContainText('不是研究级结果');await expect(row).toContainText('历史验证');
 await page.getByRole('button',{name:'按计算结果',exact:true}).click();await page.getByLabel('搜索计算结果',{exact:true}).fill('gaussian-normal');await expect(page.locator('tbody')).toContainText('-75');await expect(page.locator('tbody')).toContainText('不是研究级结果');
});
test('mismatched detail identity cannot supply a review to the list',async({page})=>{
 await page.route('**/api/attempts/gaussian-normal/details',async r=>{const d=await(await r.fetch()).json();d.id='other';d.review={availability:'available',reason:null,source:{kind:'synthetic'},data:review};await r.fulfill({json:d});});
 await connect(page,'#/results?project=gaussian-demo');await page.getByLabel('搜索计算结果',{exact:true}).fill('gaussian-normal');await expect(page.locator('tbody')).toContainText('补充证据读取失败');await expect(page.locator('tbody')).not.toContainText('VALIDATED_MINIMUM');
});

test('workflow sidebar carries smoke scope next to accepted; missing scope stays explicit',async({page})=>{
 let missing=false;await page.route('**/api/workflows/attempts/workflow-live-attempt',async r=>{const d=await(await r.fetch()).json();d.attempt.review={historical:{availability:'available',data:missing?{...review,acceptances:[]}:review},human_mode:null};await r.fulfill({json:d});});
 await connect(page,'#/workflows');await page.getByLabel('运行项目',{exact:true}).selectOption('workflow-live-project');await page.getByRole('button',{name:'展开 1 次尝试'}).click();await page.getByRole('button',{name:'Attempt 1 · 查看证据'}).click();const side=page.getByRole('region',{name:'任务详情'});await expect(side).toContainText('不是研究级结果');await expect(side).toContainText('历史验证');
 missing=true;await page.goBack();await page.getByRole('button',{name:'Attempt 1 · 查看证据'}).click();await expect(side).toContainText('原报告未记录，不能据此推断研究级验收');
});

test('evidence budget is shared across multiple visible Task tables',async({page})=>{
 let active=0,maximum=0,requests=0;const rejected:string[]=[];
 await page.route(/\/api\/attempts\/[^/]+\/(result|details)$/,async r=>{active++;maximum=Math.max(maximum,active);requests++;try{if(active>2){rejected.push(r.request().url());await r.fulfill({status:503,body:'Service Unavailable'});}else{await new Promise(resolve=>setTimeout(resolve,40));await r.fulfill({response:await r.fetch()});}}finally{active--;}});
 await connect(page,'#/projects/gaussian-demo');await expect(page.locator('.task')).toHaveCount(8);await expect.poll(()=>requests).toBe(16);await expect.poll(()=>active).toBe(0);expect(maximum).toBeLessThanOrEqual(2);expect(rejected).toEqual([]);
});

test('archive detail panels share the page request budget and canceled reads do not block navigation',async({page})=>{
 let active=0,maximum=0;const rejected:string[]=[];
 await page.route('**/api/**',async r=>{active++;maximum=Math.max(maximum,active);try{if(active>2){rejected.push(r.request().url());await r.fulfill({status:503,body:'Service Unavailable'});}else{await new Promise(resolve=>setTimeout(resolve,40));await r.fulfill({response:await r.fetch()});}}finally{active--;}});
 await connect(page,'#/analysis?tab=results');await page.getByRole('link',{name:'Synthetic archived calculation'}).click();await expect(page.getByTestId('full-frequencies')).toHaveCount(0);await page.getByRole('button',{name:'结构与结果',exact:true}).click();await expect(page.locator('.detail-evidence')).toContainText('完整结果与历史证据');await page.getByRole('button',{name:'来源与记录',exact:true}).click();await expect(page.getByTestId('review-evidence')).toContainText('尚无绑定');await page.getByRole('navigation',{name:'主导航'}).getByRole('link',{name:'项目',exact:true}).click();await expect(page.locator('.organized-card').first()).toBeVisible();await expect.poll(()=>active).toBe(0);expect(maximum).toBeLessThanOrEqual(2);expect(rejected).toEqual([]);
});
