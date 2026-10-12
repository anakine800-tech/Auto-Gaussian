import {test,expect} from '@playwright/test';
import type {Page} from '@playwright/test';
const token='browser-test-only-'+'0'.repeat(32);
async function connect(page:Page,hash=''){await page.goto('/'+hash);await page.getByLabel('只读访问令牌').fill(token);await page.getByRole('button',{name:'连接数据源'}).click();}
test('project search, historical status filter, deterministic sorting and pagination compose',async({page})=>{
  await page.route('**/api/project-library',async route=>{const r=await route.fetch(),d=await r.json(),p=d.items[0];d.items=Array.from({length:27},(_,i)=>({...p,id:`project-${i}`,label:`研究 ${i}`,states:i%2?['RUNNING']:['FAILED']}));await route.fulfill({json:d});});
  await connect(page);await expect(page.locator('.project-card')).toHaveCount(10);await page.getByRole('button',{name:'下一页',exact:true}).click();await expect(page.locator('.project-card').first()).toContainText('研究 10');
  await page.getByLabel('搜索项目',{exact:true}).fill('研究 26');await expect(page.locator('.project-card')).toHaveCount(1);await expect(page.getByText('第 1 / 1 页')).toBeVisible();
  await page.getByLabel('状态筛选').selectOption('RUNNING');await expect(page.locator('.project-card')).toHaveCount(0);await page.getByRole('button',{name:'清除筛选'}).click();
  await page.getByLabel('每页条数').selectOption('25');await expect(page.locator('.project-card')).toHaveCount(25);await page.getByLabel('排序',{exact:true}).selectOption('name-desc');await expect(page.locator('.project-card').first()).toContainText('研究 26');
});
test('project workflow and results views preserve empty tasks and filter declared program',async({page})=>{
  await connect(page,'#/projects/gaussian-demo');await expect(page.locator('.task')).toHaveCount(8);
  await page.getByRole('button',{name:'按计算结果',exact:true}).click();await expect(page.getByRole('heading',{name:'计算结果索引'})).toBeVisible();
  await page.getByLabel('程序筛选').selectOption('gaussian');await page.getByLabel('搜索计算结果',{exact:true}).fill('gaussian-normal');await expect(page.locator('tbody tr')).toHaveCount(1);await expect(page.locator('tbody')).toContainText('STO-3G');await expect(page.locator('tbody')).toContainText('-75');await expect(page.locator('tbody')).toContainText('3 / 1');
  await page.getByRole('button',{name:'按工作流',exact:true}).click();await expect(page.locator('.task')).toHaveCount(8);
});
test('results project changes clear previous records; stale reads cannot replace the selection',async({page})=>{
  await connect(page,'#/results');await page.getByLabel('结果项目').selectOption('gaussian-demo');await expect(page.locator('tbody tr')).toHaveCount(8);
  await page.getByLabel('结果项目').selectOption('empty');await expect(page.locator('tbody tr')).toHaveCount(0);await expect(page.getByText('没有匹配的计算记录。')).toBeVisible();
  await page.getByRole('button',{name:'断开',exact:true}).click();await expect(page.getByLabel('结果项目')).toHaveCount(0);
});
test('archive search and missing frequency preserve scientific meaning',async({page})=>{
  await connect(page,'#/analysis?tab=results');await page.getByLabel('搜索科学结果',{exact:true}).fill('not-existing');await expect(page.locator('.project-card')).toHaveCount(0);await page.getByRole('button',{name:'清除筛选'}).click();await page.getByRole('link',{name:'Synthetic archived calculation'}).click();
  await page.getByRole('button',{name:'结构与结果',exact:true}).click();await expect(page.getByText('未记录频率，虚频数量未知。')).toBeVisible();await page.getByRole('button',{name:'来源与记录',exact:true}).click();await expect(page.getByTestId('review-evidence')).toContainText('尚无绑定');
});
const geometry={units:'angstrom',orientation_kind:'standard-orientation',atoms:[{center:1,atomic_number:8,x:0,y:0,z:0},{center:2,atomic_number:1,x:1,y:0,z:0},{center:3,atomic_number:1,x:0,y:1,z:0}],source_span:{start:10,end:20,sha256:'a'.repeat(64)}};
async function withGeometry(page:Page,invalid=false){
  await page.route('**/api/attempts/gaussian-normal/details',async route=>{const r=await route.fetch(),d=await r.json();d.result.data.last_geometry=structuredClone(geometry);if(invalid)d.result.data.last_geometry.atoms[0].atomic_number=0;d.review={availability:'available',reason:null,source:{kind:'test-historical'},data:{classification:'VALIDATED_MINIMUM',acceptance_state:'not-accepted',selected_final_geometry:{...geometry,source_span:{start:50,end:60},atoms:geometry.atoms.map(a=>({...a,x:a.x*2,y:a.y*2}))},acceptances:[]}};await route.fulfill({json:d});});
}
test('3D rotation and zoom preserve original distances; Review geometry is explicit and resets selection',async({page})=>{
  const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')errors.push(m.text());});
  await withGeometry(page);await connect(page,'#/attempts/gaussian-normal');await page.getByRole('button',{name:'结构与结果',exact:true}).click();const scene=page.getByTestId('molecule-scene');await expect(page.getByTestId('molecule-atom')).toHaveCount(3);
  await page.locator('.structure-tools:not([open]) > summary').click();await page.getByLabel('测距原子 A').selectOption('2');await page.getByLabel('测距原子 B').selectOption('3');await expect(page.getByTestId('atom-distance')).toHaveText('1.4142 Å');
  const atom=page.getByTestId('molecule-atom').filter({has:page.locator('title',{hasText:'H · 2:'})});const before=await atom.getAttribute('transform');await scene.focus();await page.keyboard.press('ArrowRight');await expect(atom).not.toHaveAttribute('transform',before!);
  await page.getByRole('button',{name:'放大结构'}).click();await expect(page.getByTestId('atom-distance')).toHaveText('1.4142 Å');
  await page.getByLabel('结构来源').selectOption('review');await expect(page.getByTestId('atom-distance')).toHaveText('选择两个原子');await page.locator('.structure-tools:not([open]) > summary').click();await page.getByLabel('测距原子 A').selectOption('2');await page.getByLabel('测距原子 B').selectOption('3');await expect(page.getByTestId('atom-distance')).toHaveText('2.8284 Å');
  await page.getByText('当前结构来源与字节区间').click();await expect(page.locator('.molecule-section pre')).toContainText('"start": 50');
  await page.getByRole('button',{name:'断开',exact:true}).click();await expect(scene).toHaveCount(0);expect(errors).toEqual([]);
});
test('invalid atomic identity prevents 3D and full-result display',async({page})=>{await withGeometry(page,true);await connect(page,'#/attempts/gaussian-normal');await page.getByRole('button',{name:'结构与结果',exact:true}).click();await expect(page.getByText('补充证据读取失败或绑定不一致，已停止展示。')).toBeVisible();await expect(page.getByTestId('molecule-scene')).toHaveCount(0);});
test('mobile scientific detail and results index fit viewport with literal untrusted text',async({page})=>{
  await withGeometry(page);await page.setViewportSize({width:390,height:844});await connect(page,'#/attempts/gaussian-normal');await page.getByRole('button',{name:'结构与结果',exact:true}).click();await expect(page.getByTestId('molecule-scene')).toBeVisible();expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.getByRole('link',{name:'分析',exact:true}).click();await expect(page.getByLabel('结果项目')).toBeVisible();expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});

test('non-angstrom geometry is rejected instead of relabeling units',async({page})=>{
  await page.route('**/api/attempts/gaussian-normal/details',async route=>{const r=await route.fetch(),d=await r.json();d.result.data.last_geometry={...geometry,units:'bohr'};await route.fulfill({json:d});});
  await connect(page,'#/attempts/gaussian-normal');await page.getByRole('button',{name:'结构与结果',exact:true}).click();await expect(page.getByText('补充证据读取失败或绑定不一致，已停止展示。')).toBeVisible();await expect(page.getByTestId('molecule-scene')).toHaveCount(0);
});

test('pointer rotation, picking and reset work in the actual SVG viewport',async({page})=>{
 await withGeometry(page);await connect(page,'#/attempts/gaussian-normal');await page.getByRole('button',{name:'结构与结果',exact:true}).click();const scene=page.getByTestId('molecule-scene');await scene.scrollIntoViewIfNeeded();const box=(await scene.boundingBox())!;
 const atom=page.locator('[data-testid="molecule-atom"][data-center="2"]');const before=await atom.getAttribute('transform');await page.mouse.move(box.x+box.width*.5,box.y+box.height*.4);await page.mouse.down();await page.mouse.move(box.x+box.width*.6,box.y+box.height*.6,{steps:8});await page.mouse.up();await expect(atom).not.toHaveAttribute('transform',before!);
 await page.locator('.structure-tools > summary').click();await page.getByRole('button',{name:'重置视角'}).click();await expect(atom).toHaveAttribute('transform',before!);await scene.scrollIntoViewIfNeeded();await page.locator('[data-testid="molecule-atom"][data-center="1"] circle').click();await expect(page.getByLabel('测距原子 A')).toHaveValue('1');await atom.locator('circle').click();await expect(page.getByTestId('atom-distance')).toHaveText('1.0000 Å');
});

test('result summaries fetch only visible pages with bounded concurrency',async({page})=>{
 const ids:string[]=[];let active=0,maximum=0;
 await page.route('**/api/projects/gaussian-demo/attempts',async route=>{const r=await route.fetch(),d=await r.json();d.data.items=Array.from({length:27},(_,i)=>({...d.data.items[0],attempt_id:'paged-'+i,task_id:'one-task',ordinal:i+1}));await route.fulfill({json:d});});
 await page.route('**/api/attempts/paged-*/result',async route=>{const id=route.request().url().split('/').at(-2)!;ids.push(id);active++;maximum=Math.max(active,maximum);await new Promise(r=>setTimeout(r,30));active--;await route.fulfill({json:{schema:'gaussian-result-summary/1',attempt_id:id,availability:'missing',reasons:['awaiting-capture'],source:null,summary:null,record_inventory:[],history:[]}});});
 await connect(page,'#/results');await page.getByLabel('结果项目').selectOption('gaussian-demo');await expect.poll(()=>ids.length).toBe(10);expect(new Set(ids)).toEqual(new Set(Array.from({length:10},(_,i)=>'paged-'+i)));expect(maximum).toBeLessThanOrEqual(3);
 await page.getByRole('button',{name:'下一页',exact:true}).click();await expect.poll(()=>ids.length).toBe(20);expect(new Set(ids.slice(10))).toEqual(new Set(Array.from({length:10},(_,i)=>'paged-'+(i+10))));
});
test('late result-index summaries cannot enter a different project',async({page})=>{
 let release:()=>void=()=>{};const gate=new Promise<void>(r=>{release=r;});let called=false;
 await page.route('**/api/attempts/gaussian-*/result',async route=>{called=true;await gate;await route.continue().catch(()=>{});});
 try{await connect(page,'#/results');await page.getByLabel('结果项目').selectOption('gaussian-demo');await expect.poll(()=>called).toBe(true);await page.getByLabel('结果项目').selectOption('empty');await expect(page.getByText('没有匹配的计算记录。')).toBeVisible();release();await expect(page.locator('tbody tr')).toHaveCount(0);}finally{release();}
});
