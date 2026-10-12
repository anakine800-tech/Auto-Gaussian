import {test,expect} from '@playwright/test';
import type {Page} from '@playwright/test';
const token='browser-test-only-'+'0'.repeat(32),a='archive-'+'a'.repeat(64),b='archive-'+'b'.repeat(64);
const groups=[['a','i2c4_opt_01',a],['b','i2c6_freq_02',a],['c','hssm1a_opt_01',b],['t','h2o_smoke_713',b]].map(([id,label,archive])=>({id:'history-'+id,kind:'historical',label,source_label:'GaussianProjects',basis:'source-directory',count:1,task_count:null,states:['normal-termination'],archive_ids:[archive]}));
async function connect(page:Page,hash='#/projects'){
 await page.route('**/api/project-library',r=>r.fulfill({json:{schema:'autog-project-library/1',items:groups}}));
 await page.route('**/api/archives',r=>r.fulfill({json:{schema:'auto-g16-legacy-archive/2',items:[a,b].map((id,i)=>({archive_id:id,title:'calculation-'+i,parser:{status:'parsed'},summary:{termination:'normal-termination',energy_hartree:-100-i,frequency_count:3,imaginary_count:i}}))}}));
 await page.goto('/'+hash);await page.getByLabel('只读访问令牌').fill(token);await page.getByRole('button',{name:'连接数据源'}).click();
}
test('directory series consolidate tasks, deduplicate counts, and keep smoke records separate',async({page})=>{
 await connect(page);await expect(page.locator('.project-card')).toHaveCount(2);const series=page.locator('.project-card').filter({hasText:'i2'});await expect(series.locator('.organized-count')).toContainText('1 份结果');await series.getByText('展开 2 个任务',{exact:true}).click();await expect(series.locator('.member-row')).toHaveCount(2);await expect(page.locator('.organized-projects')).not.toContainText('h2o_smoke');
 await page.getByRole('link',{name:'测试 / 验收',exact:false}).click();await expect(page.getByRole('heading',{name:'测试与验收',exact:true})).toBeVisible();await expect(page.locator('.project-card')).toHaveCount(1);await expect(page.locator('.project-card')).toContainText('h2o_smoke');
});
test('rename and purpose changes persist as local display preferences only',async({page})=>{
 const writes:string[]=[];page.on('request',r=>{if(r.url().includes('/api/')&&r.method()!=='GET')writes.push(r.method());});await connect(page);
 const card=page.locator('.project-card').filter({hasText:'i2'});await card.getByText('重命名 / 整理项目',{exact:true}).click();await card.locator('.organized-actions').getByLabel('展示项目名称',{exact:true}).fill('进攻面研究');await card.locator('.organized-actions').getByLabel('用途分区',{exact:true}).selectOption('test');await card.locator('.organized-actions').getByRole('button',{name:'保存整理',exact:true}).click();await expect(page.locator('.organized-projects')).not.toContainText('i2');
 await page.getByRole('link',{name:'测试 / 验收',exact:false}).click();await expect(page.locator('.project-card').filter({hasText:'进攻面研究'})).toHaveCount(1);await page.reload();await page.getByLabel('只读访问令牌').fill(token);await page.getByRole('button',{name:'连接数据源'}).click();await expect(page.locator('.project-card').filter({hasText:'进攻面研究'})).toHaveCount(1);expect(writes).toEqual([]);
 const stored=await page.evaluate(()=>localStorage.getItem('autog-project-organization/1'));expect(stored).toContain('进攻面研究');expect(stored).not.toContain(token);
});
test('scientific results is a deduplicated data table, not a second project catalog',async({page})=>{
 await connect(page,'#/results');await expect(page.getByRole('heading',{name:'科学结果',exact:true})).toBeVisible();await expect(page.locator('.project-card')).toHaveCount(0);await expect(page.locator('.science-index tbody tr')).toHaveCount(2);await expect(page.locator('.science-index')).toContainText('i2');await expect(page.locator('.science-index')).toContainText('-100');
 await page.getByLabel('结果用途',{exact:true}).selectOption('test');await expect(page.locator('.science-index tbody tr')).toHaveCount(1);await expect(page.locator('.science-index')).toContainText('calculation-1');await page.setViewportSize({width:390,height:844});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});

test('a complete directory series opens one scientific table and selection survives returning',async({page})=>{
 await connect(page);const series=page.locator('.project-card').filter({hasText:'i2'});await series.getByRole('link',{name:'查看项目全部结果'}).click();await expect(page.locator('.science-index tbody tr')).toHaveCount(1);await expect(page.getByLabel('结果项目')).toHaveValue(/^series:/);await page.getByRole('navigation',{name:'主导航'}).getByRole('link',{name:'项目',exact:true}).click();await page.goBack();await expect(page.locator('.science-index tbody tr')).toHaveCount(1);
});

test('an explicitly selected test project is never labeled as calculation purpose',async({page})=>{
 await page.route('**/api/project-library/history-t',r=>r.fulfill({json:{schema:'autog-project-library/1',project:groups[3],items:[{archive_id:b,title:'smoke result',parser:{status:'parsed'},summary:{termination:'normal-termination',energy_hartree:-75,frequency_count:3,imaginary_count:0}}]}}));
 await connect(page,'#/results?project=history-t');await expect(page.getByLabel('结果用途')).toHaveValue('test');await expect(page.getByLabel('结果项目').locator('option:checked')).toContainText('测试');await expect(page.locator('tbody')).toContainText('smoke result');
});
