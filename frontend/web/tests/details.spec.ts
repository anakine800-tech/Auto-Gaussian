import {test,expect} from '@playwright/test';
async function connect(page:import('@playwright/test').Page, hash:string){
  await page.goto('/'+hash);await page.getByLabel('只读访问令牌').fill('browser-test-only-'+'0'.repeat(32));await page.getByRole('button',{name:'连接数据源'}).click();
}
test('archive log search and terminal jump show exact lines; disconnect clears',async({page})=>{
  await connect(page,'#/analysis?tab=results');await page.getByRole('link',{name:'Synthetic archived calculation'}).click();
  await page.getByRole('button',{name:'运行与诊断',exact:true}).click();await page.getByRole('button',{name:'读取已归档日志'}).click();
  await expect(page.getByTestId('raw-log')).toContainText('SCF Done:');
  await page.getByLabel('搜索日志',{exact:true}).fill('SCF Done');await page.getByRole('button',{name:'下一个匹配'}).click();
  await expect(page.locator('.selected-line')).toContainText('SCF Done');
  await page.getByRole('button',{name:'最后一次正常终止'}).click();await expect(page.locator('.selected-line')).toContainText('Normal termination');
  await page.getByRole('button',{name:'断开',exact:true}).click();await expect(page.getByTestId('raw-log')).toHaveCount(0);
});
test('native full frequency values are shown with missing Review explicitly',async({page})=>{
  await connect(page,'#/attempts/gaussian-normal');await page.getByRole('button',{name:'结构与结果',exact:true}).click();await expect(page.getByTestId('full-frequencies')).toContainText('-123.4');
  await page.getByRole('button',{name:'来源与记录',exact:true}).click();await expect(page.getByTestId('review-evidence')).toContainText('尚无绑定');
  await page.getByRole('button',{name:'运行与诊断',exact:true}).click();await page.getByRole('button',{name:'读取已归档日志'}).click();await expect(page.getByText('尚未连接与此结果匹配的本地日志。')).toBeVisible();
});
test('cross-identity details are rejected without rendering values',async({page})=>{
  await page.route('**/api/attempts/gaussian-normal/details',async route=>{
    const r=await route.fetch();const d=await r.json();d.id='other';await route.fulfill({json:d});
  });await connect(page,'#/attempts/gaussian-normal');
  await expect(page.getByText('补充证据读取失败或绑定不一致，已停止展示。')).toBeVisible();await expect(page.getByTestId('full-frequencies')).toHaveCount(0);
});
test('log source failure cannot expose stale raw content',async({page})=>{
  await page.route('**/api/archives/*/log',route=>route.fulfill({status:409,json:{schema:'auto-g16-http-error/1',error:{code:'invalid-evidence'}}}));
  await connect(page,'#/analysis?tab=results');await page.getByRole('link',{name:'Synthetic archived calculation'}).click();await page.getByRole('button',{name:'运行与诊断',exact:true}).click();await page.getByRole('button',{name:'读取已归档日志'}).click();
  await expect(page.getByText('日志不可读或哈希不匹配，已停止展示。')).toBeVisible();await expect(page.getByTestId('raw-log')).toHaveCount(0);
});
