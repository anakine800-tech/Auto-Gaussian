import { test, expect } from '@playwright/test';

async function connect(page: import('@playwright/test').Page) {
  await page.goto('/#/analysis?tab=results');
  await page.getByLabel('只读访问令牌').fill('browser-test-only-' + '0'.repeat(32));
  await page.getByRole('button', { name: '连接数据源' }).click();
}
test('archive navigates to exact input and facts without Core authority', async ({ page }) => {
  const methods: string[] = [];
  page.on('request', r => { if (r.url().includes('/api/')) methods.push(r.method()); });
  await connect(page);
  await page.getByRole('link', { name: 'Synthetic archived calculation' }).click();
  await page.getByRole('button',{name:'来源与记录',exact:true}).click();await expect(page.getByTestId('archive-input')).toContainText('hf/sto-3g');
  await expect(page.getByTestId('archive-facts')).toContainText('-75');
  await expect(page.getByTestId('archive-facts')).toContainText('未知（未记录频率）');
  await page.getByRole('button',{name:'来源与记录',exact:true}).click();await expect(page.getByText('Core Attempt / 实时状态 / 科学验收 / Review：不可用')).toBeVisible();
  await expect(page.locator('.log strong').getByText('synthetic.log', { exact: true })).toBeVisible();
  expect(methods.length).toBeGreaterThanOrEqual(2);
  expect(methods.every(m => m === 'GET')).toBeTruthy();
  await page.getByRole('button', { name: '断开', exact: true }).click();
  await expect(page.getByTestId('archive-facts')).toHaveCount(0);
  await expect(page.getByTestId('archive-input')).toHaveCount(0);
});
test('archive rejects wrong source contract without rendering facts', async ({ page }) => {
  await page.route('**/api/archives', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ schema: 'future/1', kind: 'archives', items: [] }) }));
  await connect(page);
  await expect(page.getByRole('alert')).toBeVisible();
  await expect(page.getByTestId('archive-facts')).toHaveCount(0);
});
test('archive mobile detail remains within viewport', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await connect(page);
  await page.getByRole('link', { name: 'Synthetic archived calculation' }).click();
  await page.getByRole('button',{name:'来源与记录',exact:true}).click();await expect(page.getByTestId('archive-input')).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
});

test('local log-only v2 archive displays unknown input without inventing legacy metadata', async ({page})=>{
 await page.route(/\/api\/archives(?:\/[^/]+)?$/,async route=>{const response=await route.fetch();const dto=await response.json();dto.schema='auto-g16-legacy-archive/2';const records=dto.kind==='archives'?dto.items:[dto.data];for(const r of records){r.source_kind='local_log_archive';if(r.artifacts){r.artifacts=r.artifacts.filter((a:{role:string})=>a.role==='log');r.input=null;r.legacy_metadata=null;}}await route.fulfill({json:dto});});
 await connect(page);await page.getByRole('link',{name:'Synthetic archived calculation'}).click();await expect(page.getByTestId('archive-facts')).toContainText('-75');await page.getByRole('button',{name:'来源与记录',exact:true}).click();await expect(page.getByText('未建立输入与日志的可靠绑定；配套文件保留在本地导入清单，不由同名文件推断归属。')).toBeVisible();await expect(page.getByTestId('archive-input')).toHaveCount(0);await expect(page.getByText('本地日志档案：未接入合格的历史调度或验收记录。')).toBeVisible();
});
test('v1 cannot silently acquire log-only semantics', async ({page})=>{
 await page.route('**/api/archives',async route=>{const response=await route.fetch();const dto=await response.json();dto.schema='auto-g16-legacy-archive/1';dto.items[0].source_kind='local_log_archive';await route.fulfill({json:dto});});await connect(page);await expect(page.getByRole('alert')).toBeVisible();
});
