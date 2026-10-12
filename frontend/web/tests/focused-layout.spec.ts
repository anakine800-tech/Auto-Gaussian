import {test,expect} from '@playwright/test';
async function connect(page:import('@playwright/test').Page){await page.goto('/#/attempts/gaussian-normal');await page.getByLabel('只读访问令牌').fill('browser-test-only-'+'0'.repeat(32));await page.getByRole('button',{name:'连接数据源'}).click();await expect(page.getByTestId('science-conditions')).toBeVisible();await page.getByRole('button',{name:'结构与结果',exact:true}).click();}
test('scientific and workflow material occupy separate views; source jump returns to exact log',async({page})=>{
 const methods:string[]=[];page.on('request',r=>{if(r.url().includes('/api/'))methods.push(r.method());});await connect(page);
 await expect(page.getByTestId('result-facts')).toBeVisible();await expect(page.getByTestId('full-frequencies')).toBeVisible();await expect(page.getByTestId('result-provenance')).toBeHidden();await expect(page.getByTestId('execution-evidence')).toBeHidden();await expect(page.getByRole('heading',{name:'状态与来源',exact:true})).toBeHidden();
 await page.getByRole('button',{name:/定位原日志：频率 1/}).click();await expect(page.getByRole('button',{name:'运行与诊断',exact:true})).toHaveAttribute('aria-pressed','true');await expect(page.getByText('尚未连接与此结果匹配的本地日志。')).toBeVisible();await expect(page.getByTestId('full-frequencies')).toBeHidden();await page.getByRole('button',{name:'来源与记录',exact:true}).click();await expect(page.getByTestId('result-provenance')).toBeVisible();
 await page.getByRole('button',{name:'结构与结果',exact:true}).click();await expect(page.getByTestId('full-frequencies')).toBeVisible();expect(methods.every(m=>m==='GET')).toBe(true);
 for(const width of [1440,390]){await page.setViewportSize({width,height:960});for(const name of ['结构与结果','运行与诊断','来源与记录']){await page.getByRole('button',{name,exact:true}).click();expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);}}
});

test('viewer is compact with scientific review collapsed, expandable without losing geometry',async({page})=>{
 await connect(page);const card=page.getByTestId('scientific-validation');await expect(card).not.toHaveAttribute('open','');await expect(card.locator('.validation-body')).toBeHidden();await expect(card.locator('summary').first()).toContainText('科学验证 · 结果只读');
 for(const width of [1440,1024,390]){await page.setViewportSize({width,height:960});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);}
 await card.locator('summary').first().click();await expect(card.locator('.validation-body')).toBeVisible();await expect(card).toContainText('PENDING HUMAN REVIEW');await card.locator('summary').first().click();await expect(card.locator('.validation-body')).toBeHidden();
});
