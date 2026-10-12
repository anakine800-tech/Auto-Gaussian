import { test, expect } from '@playwright/test';
import type { Page } from '@playwright/test';
const token = 'browser-test-only-' + '0'.repeat(32);
const project = '#/projects/' + encodeURIComponent('测试%2F?project');
const attempt = '#/attempts/' + encodeURIComponent('attempt%2F中文');
async function connect(page: Page, hash = '') {
  await page.goto('/' + hash);
  await page.getByLabel('只读访问令牌').fill(token);
  await page.getByRole('button', { name: '连接数据源' }).click();
}
test('real HTTP navigation preserves IDs, missing fields and historical semantics', async ({ page }) => {
  const failures: string[] = [];
  page.on('pageerror', e => failures.push(e.message));
  page.on('console', msg => { if (msg.type() === 'error') failures.push(msg.text()); });
  const methods: string[] = [];
  page.on('request', req => { if (req.url().includes('/api/')) methods.push(req.method()); });
  await connect(page);
  await expect(page.getByRole('heading', { name: '项目库' })).toBeVisible();
  await expect(page.getByText('原生计算项目与历史目录分组集中浏览。', { exact: false })).toBeVisible();
  await page.getByRole('link', {name:'测试 / 验收'}).click();
  await page.locator(`a[href="${project}"]`).click();
  await expect(page.getByText('此 Task 尚无 Attempt。')).toBeVisible();
  await expect(page.getByText('2 Tasks / 1 Attempts')).toBeVisible();
  await page.getByRole('link', { name: 'Attempt 1' }).click();
  await expect(page.getByRole('heading', { name: '计算记录 UNKNOWN' })).toBeVisible();
  await page.getByRole('button',{name:'结构与结果',exact:true}).click();await expect(page.getByRole('heading', { name: '完整结果与历史证据', exact: true })).toBeVisible();
  await expect(page.getByText('部分证据协议尚未支持。', { exact: false })).toBeVisible();
  await expect(page.locator('body')).not.toContainText('must-not-expose');
  await page.getByRole('button',{name:'运行与诊断',exact:true}).click();await page.getByText('尚未投影的证据类型', { exact: false }).click();
  await expect(page.getByText('future-result/1', { exact: true })).toBeVisible();
  await expect(page.locator('body')).not.toContainText(token);
  expect(await page.evaluate(() => ({ local: localStorage.length, containsToken:Object.values(sessionStorage).some(v=>v.includes('browser-test-only-')), cookies: document.cookie }))).toEqual({ local: 0, containsToken:false, cookies: '' });
  expect(methods.length).toBeGreaterThanOrEqual(5); expect(methods.every(x => x === 'GET')).toBe(true);
  expect(failures).toEqual([]);
  await page.getByRole('button', { name: '断开', exact: true }).click();
  await expect(page.getByLabel('只读访问令牌')).toHaveValue('');
  await expect(page.getByRole('heading', { name: '计算记录 UNKNOWN' })).toHaveCount(0);
});
test('hard refresh loses the in-memory token', async ({ page }) => {
  await connect(page, attempt);
  await expect(page.getByRole('heading', { name: '计算记录 UNKNOWN' })).toBeVisible();
  await page.reload();
  await expect(page.getByLabel('只读访问令牌')).toHaveValue('');
  await expect(page.getByText('结构、逐项频率、热化学与原始日志内容待接入。', { exact: true })).toHaveCount(0);
});
test('empty project stays empty', async ({ page }) => {
  await connect(page, '#/projects/empty');
  await expect(page.getByText('暂无 Task。')).toBeVisible();
  await expect(page.getByText('0 Tasks / 0 Attempts')).toBeVisible();
});
for (const [status, code, text] of [[401, 'unauthorized', '只读令牌无效'], [404, 'not-found', '未找到这条记录'], [409, 'invalid-evidence', '证据结构无法通过校验'], [413, 'response-too-large', '数据超过本版读取上限'], [503, 'store-unavailable', '当前数据源不可读取']] as const) {
  test(`error ${status} clears the data view`, async ({ page }) => {
    await page.route('**/api/project-library', route => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify({ schema: 'auto-g16-http-error/1', error: { code } }) }));
    await connect(page); await expect(page.getByRole('alert')).toContainText(text);
    await expect(page.locator('.project-card')).toHaveCount(0);
  });
}
test('malformed contract fails closed', async ({ page }) => {
  await page.route('**/api/project-library', route => route.fulfill({ json: { schema: 'auto-g16-query/2', kind: 'projects', data: { items: [] } } }));
  await connect(page); await expect(page.getByRole('alert')).toContainText('不符合查询契约');
});
test('late responses cannot replace a newer route', async ({ page }) => {
  let release: (() => void) | undefined;
  const delay = new Promise<void>(resolve => { release = resolve; });
  await page.route('**/api/project-library', async route => { await delay; await route.continue().catch(() => {}); });
  await connect(page); await page.evaluate(hash => { location.hash = hash; }, attempt);
  await expect(page.getByRole('heading', { name: '计算记录 UNKNOWN' })).toBeVisible();
  release!(); await page.getByRole('button', { name: '刷新', exact: true }).click();
  await expect(page.getByRole('heading', { name: '计算记录 UNKNOWN' })).toBeVisible();
  await expect(page.locator('.project-card')).toHaveCount(0);
});
for (const hash of ['', project, attempt]) {
  test(`mobile layout has no page-level horizontal overflow: ${hash || 'projects'}`, async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 }); await connect(page, hash);
    await expect(page.locator('.read-time')).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}
test('available metadata remains literal text, including zero charge and hostile filenames', async ({ page }) => {
  await page.route('**/api/attempts/*', async route => {
    const response = await route.fetch(); const dto = await response.json();
    const available = (value: unknown) => ({ availability: 'available', value, source: 'test-only-bound-plan', reason: null });
    dto.data.declared_science = { program: available('gaussian'), method: available('B3LYP'), basis: available('6-31G(d)'), charge: available(0), multiplicity: available(1) };
    dto.data.input = available({ logical_name: '<img src=x onerror="alert(1)">.gjf', sha256: 'a'.repeat(64), size_bytes: 500 });
    await route.fulfill({ response, json: dto });
  });
  await connect(page, attempt);
  await page.getByRole('button', {name:'运行与诊断',exact:true}).click();
  await expect(page.getByText('B3LYP', { exact: true })).toBeVisible();
  await expect(page.locator('.field').filter({ has: page.locator('dt', { hasText: /^电荷$/ }) }).locator('.value')).toHaveText('0');
  await page.locator('.field').filter({has:page.locator('dt',{hasText:'输入文件引用'})}).getByText('查看结构化记录',{exact:true}).click();
  await expect(page.locator('pre').filter({ hasText: '<img src=x' })).toBeVisible();
  await expect(page.locator('main img')).toHaveCount(0);
});
