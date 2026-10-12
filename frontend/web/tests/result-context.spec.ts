import {test,expect} from '@playwright/test';
import type {Page} from '@playwright/test';
test.skip(process.env.AUTOG_TEST_CONTEXT!=='1','requires result-bound context fixture');
const id='synthetic-mode-review';
async function connect(page:Page,hash='#/attempts/'+id){await page.goto('/'+hash);await page.getByLabel('只读访问令牌').fill('browser-test-only-'+'0'.repeat(32));await page.getByRole('button',{name:'连接数据源'}).click();await page.getByRole('button',{name:'来源与记录',exact:true}).click();await expect(page.getByTestId('result-context')).toBeVisible();}
test('bound conditions and exact lineage show separately from unverified log conditions on mobile',async({page})=>{
 const methods:string[]=[];page.on('request',r=>{if(r.url().includes('/api/'))methods.push(r.method());});await page.setViewportSize({width:390,height:844});await connect(page);
 const c=page.getByTestId('result-context');await expect(c).toContainText('B3LYP');await expect(c).toContainText('STO-3G');await expect(c).toContainText('气相（gas_phase）');
 await expect(c.getByRole('row').filter({hasText:'Charge / 电荷'}).locator('td').first()).toHaveText('0');
 await expect(c.getByRole('row').filter({hasText:'Method / 方法'}).locator('td').last()).toHaveText('未接入');await expect(c).toContainText('可比性尚未评估');
 await c.getByText('计划、输入与来源身份',{exact:true}).click();await expect(c).toContainText('auto-g16-v30-a-calculation-plan-intent/1');await expect(c).not.toContainText('unbound-later-plan');
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);await c.screenshot({path:'../.local/result-context/synthetic-context-mobile.png'});
 await c.getByRole('link',{name:'gaussian-demo',exact:true}).click();await expect(page.getByRole('link',{name:'← 所有项目'})).toBeVisible();expect(methods.every(m=>m==='GET')).toBe(true);
});
test('context with a different Result is withheld without destroying original result facts',async({page})=>{
 await page.route('**/api/attempts/'+id+'/details',async route=>{const response=await route.fetch(),d=await response.json();d.context.lineage.result_source.result_id='wrong-result';await route.fulfill({json:d});});
 await page.goto('/#/attempts/'+id);await page.getByLabel('只读访问令牌').fill('browser-test-only-'+'0'.repeat(32));await page.getByRole('button',{name:'连接数据源'}).click();await page.getByRole('button',{name:'结构与结果',exact:true}).click();await expect(page.locator('.science-detail').getByText('来源上下文缺失或绑定不一致，暂不展示计算条件。')).toBeVisible();await expect(page.getByTestId('result-context')).toHaveCount(0);await expect(page.getByTestId('scientific-validation')).toContainText('TS candidate');
});
test('unknown schema stays unknown; injected observed verification is rejected',async({page})=>{
 await connect(page,'#/attempts/gaussian-normal');await expect(page.getByTestId('result-context')).toContainText('计划格式尚未接入');await expect(page.getByTestId('result-context')).not.toContainText('气相（gas_phase）');
 await page.route('**/api/attempts/'+id+'/details',async route=>{const response=await route.fetch(),d=await response.json();d.context.conditions.observed.method={...d.context.conditions.declared.method};await route.fulfill({json:d});});
 await page.goto('/#/attempts/'+id);await page.getByRole('button',{name:'结构与结果',exact:true}).click();await expect(page.locator('.science-detail').getByText('来源上下文缺失或绑定不一致，暂不展示计算条件。')).toBeVisible();
});
test('legacy archive retains archive identity and never fabricates Core parents',async({page})=>{
 await connect(page);await page.goto('/#/analysis?tab=results');await page.locator('main a[href^="#/archives/"]').first().click();await page.getByRole('button',{name:'来源与记录',exact:true}).click();const c=page.getByTestId('result-context');await expect(c).toContainText('历史 Archive · 非 Core Attempt');await expect(c).toContainText('历史目录归属不会升级为 Core Project、Task 或 Attempt 绑定');await expect(c.getByRole('link')).toHaveCount(0);
});
