import { test, expect } from '@playwright/test';
import type { Page } from '@playwright/test';
const token = 'browser-test-only-' + '0'.repeat(32);
async function connect(page: Page, name = 'normal') {
  await page.goto('/#/attempts/gaussian-' + name);
  await page.getByLabel('只读访问令牌').fill(token);
  await page.getByRole('button', { name: '连接数据源' }).click();
}
const panel = (page: Page) => page.getByRole('region', { name: 'Gaussian Result 摘要' });
const datum = (page: Page, label: string | RegExp) => panel(page).locator('.field').filter({ has: page.locator('dt', { hasText: label }) }).locator('dd');

test('stored Gaussian facts reach browser with exact source and history', async ({ page }) => {
  const errors: string[] = [], methods: string[] = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });
  page.on('request', request => { if (request.url().includes('/api/')) methods.push(request.method()); });
  await connect(page);
  await expect(page.getByTestId('result-facts')).toBeVisible();
  await expect(datum(page, '最终能量 / Hartree')).toHaveText('-75');
  await expect(datum(page, /^虚频数量$/)).toHaveText('1');
  await expect(page.getByRole('heading', { name: '计算记录 PLANNED' })).toBeVisible();
  await page.getByRole('button',{name:'来源与记录',exact:true}).click();await panel(page).getByText('所选结果的来源与绑定', { exact: true }).click();
  await expect(panel(page).locator('details').filter({has:page.getByText('所选结果的来源与绑定',{exact:true})}).locator('pre')).toContainText('normal-capture-2');
  await expect(panel(page).locator('details').filter({has:page.getByText('所选结果的来源与绑定',{exact:true})}).locator('pre')).toContainText('auto-g16-v3-gaussian-job');
  await panel(page).getByText('归档历史 · 2 次采集', { exact: true }).click();
  await expect(panel(page).getByText('采集 1 · 历史记录 · complete')).toBeVisible();
  await expect(panel(page).getByText('采集 2 · 当前选中 · complete')).toBeVisible();
  expect(errors).toEqual([]); expect(methods.every(m => m === 'GET')).toBe(true);
  await page.screenshot({ path: '../.local/result-ui-desktop.png', fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: '../.local/result-ui-mobile.png', fullPage: true });
});
test('missing frequencies stay unknown and error termination does not become success', async ({ page }) => {
  await connect(page, 'no-frequency');
  await expect(datum(page, '虚频数量')).toHaveText('未知（未记录频率）');
  await expect(datum(page, '频率数量')).toHaveText('未记录');
  await page.evaluate(() => { location.hash = '#/attempts/gaussian-error'; });
  await expect(datum(page, '终止状态')).toHaveText('错误终止');
  await expect(page.getByRole('heading', { name: '计算记录 PLANNED' })).toBeVisible();
});
for (const [name, label] of [
  ['missing', '尚无精确输入绑定'], ['partial', '输出采集不完整'],
  ['unknown', '存在尚未支持的记录协议，摘要已停止展示'],
  ['v31', 'V31 Gaussian 来源尚未具备接入资格'], ['legacy', '历史解析器的结果未具备摘要接入资格'],
]) {
  test(`real synthetic source ${name} withholds scientific facts`, async ({ page }) => {
    await connect(page, name);
    await expect(panel(page)).toContainText(label);
    await expect(panel(page).getByTestId('result-facts')).toHaveCount(0);
    await expect(panel(page)).not.toContainText('must-not-expose');
  });
}
test('domain conflict remains separate from Core and from a failed HTTP read', async ({ page }) => {
  await page.route('**/api/attempts/gaussian-normal/result', async route => {
    const response = await route.fetch(), dto = await response.json();
    await route.fulfill({ json: { ...dto, availability: 'conflict', reasons: ['mixed-execution-generations'], summary: null, source: null, history: [] } });
  });
  await connect(page);
  await expect(panel(page)).toContainText('证据存在冲突');
  await expect(panel(page).getByTestId('result-facts')).toHaveCount(0);
  await expect(page.getByRole('heading', { name: '计算记录 PLANNED' })).toBeVisible();
});
test('Result HTTP error removes old facts but preserves the Core detail', async ({ page }) => {
  await connect(page); await expect(datum(page, '最终能量 / Hartree')).toHaveText('-75');
  await page.route('**/api/attempts/gaussian-normal/result', route => route.fulfill({ status: 503, json: { schema: 'auto-g16-http-error/1', error: { code: 'store-unavailable' } } }));
  await page.getByRole('button', { name: '刷新', exact: true }).click();
  await expect(panel(page).getByRole('alert')).toContainText('暂时不可读');
  await expect(panel(page).getByTestId('result-facts')).toHaveCount(0);
  await expect(page.getByRole('heading', { name: '计算记录 PLANNED' })).toBeVisible();
});
for (const change of ['version', 'identity', 'frequency-null', 'count', 'withheld-facts', 'energy', 'source']) {
  test(`malformed Result ${change} fails closed`, async ({ page }) => {
    await page.route('**/api/attempts/gaussian-normal/result', async route => {
      const response = await route.fetch(), dto = await response.json();
      if (change === 'version') dto.schema = 'gaussian-result-summary/2';
      if (change === 'identity') dto.attempt_id = 'another-attempt';
      if (change === 'frequency-null') dto.summary.frequency = { availability: 'missing', count: 0, imaginary_count: 0 };
      if (change === 'count') dto.summary.frequency.imaginary_count = 4;
      if (change === 'withheld-facts') dto.availability = 'unsupported';
      if (change === 'energy') dto.summary.final_energy_hartree = 'not-a-number';
      if (change === 'source') dto.source.input.sha256 = 'bad-digest';
      await route.fulfill({ json: dto });
    });
    await connect(page);
    await expect(panel(page).getByRole('alert')).toContainText('契约或身份不匹配');
    await expect(panel(page).getByTestId('result-facts')).toHaveCount(0);
  });
}
test('late Result cannot replace newer Attempt or survive disconnect', async ({ page }) => {
  let release!: () => void;
  const delay = new Promise<void>(resolve => { release = resolve; });
  await page.route('**/api/attempts/gaussian-normal/result', async route => { await delay; await route.continue().catch(() => {}); });
  await connect(page); await expect(panel(page).getByRole('status')).toBeVisible();
  await page.evaluate(() => { location.hash = '#/attempts/gaussian-no-frequency'; });
  await expect(datum(page, '虚频数量')).toHaveText('未知（未记录频率）');
  release();
  await page.getByRole('button', { name: '断开', exact: true }).click();
  await expect(panel(page)).toHaveCount(0);
  expect(await page.evaluate(() => ({ local: localStorage.length, containsToken: Object.values(sessionStorage).some(v=>v.includes(token)), cookie: document.cookie }))).toEqual({ local: 0, containsToken: false, cookie: '' });
});
