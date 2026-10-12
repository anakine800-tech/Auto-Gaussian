// Explicit, private local acceptance: persisted facts -> DTO -> HTTP -> UI.
import { chromium, expect } from '@playwright/test';
import { spawn } from 'node:child_process';
import { randomBytes, createHash } from 'node:crypto';
import { readFile, stat, readdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';
const [python, directory] = process.argv.slice(2);
if (!python || !directory || !path.isAbsolute(python) || !path.isAbsolute(directory)) throw new Error('Pass absolute installed Python and evidence directory');
const evidence = JSON.parse(await readFile(path.join(directory, 'expectations.json'), 'utf8'));
const origin = 'http://127.0.0.1:18767';
const token = randomBytes(32).toString('base64url');
async function fingerprint() {
  const s = await stat(evidence.database, { bigint: true });
  return { sha256: createHash('sha256').update(await readFile(evidence.database)).digest('hex'), size: String(s.size), inode: String(s.ino),
    mtime_ns: String(s.mtimeNs), ctime_ns: String(s.ctimeNs), directory_entries: (await readdir(path.dirname(evidence.database))).sort() };
}
const before = await fingerprint();
for (const key of ['sha256', 'size', 'inode', 'mtime_ns', 'ctime_ns']) expect(before[key]).toBe(String(evidence.before[key]));
expect(before.directory_entries).toEqual(evidence.before.directory_entries);
const env = { ...process.env, AUTOG_READ_TOKEN: token, PYTHONDONTWRITEBYTECODE: '1' };
delete env.PYTHONPATH; delete env.PYTHONHOME;
// Isolated interpreter and unrelated cwd prove both packages/UI are installed.
const child = spawn(python, ['-I', '-B', '-m', 'autog_frontend', '--database', evidence.database, '--port', '18767', '--ui'], {
  cwd: directory, env, stdio: ['ignore', 'ignore', 'pipe'],
});
let browser;
try {
  let ready = false;
  for (let n = 0; n < 100; n++) {
    if (child.exitCode !== null) throw new Error('Installed preview server failed');
    try { const r = await fetch(origin + '/api/projects'); if (r.status === 401) { ready = true; break; } } catch {}
    await delay(100);
  }
  if (!ready) throw new Error('Installed preview timeout');
  for (const [url, dto] of Object.entries(evidence.expected)) {
    const response = await fetch(origin + url, { headers: { Authorization: `Bearer ${token}` } });
    expect(response.status).toBe(200); expect(await response.json()).toEqual(dto);
  }
  browser = await chromium.launch({ channel: 'chrome' });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1024 } });
  const errors = [], methods = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });
  page.on('request', req => { if (req.url().includes('/api/')) methods.push(req.method()); });
  await page.goto(origin);
  await page.getByLabel('只读访问令牌').fill(token);
  await page.getByRole('button', { name: '连接数据源' }).click();
  await page.locator(`a[href="#/projects/${encodeURIComponent(evidence.project_id)}"]`).click();
  const project = evidence.expected['/api/projects/' + encodeURIComponent(evidence.project_id)];
  await expect(page.getByText(`${project.data.task_count} Tasks / ${project.data.attempt_summary.total} Attempts`)).toBeVisible();
  await page.screenshot({ path: path.join(directory, 'project.png'), fullPage: true });
  await page.locator(`a[href="#/attempts/${encodeURIComponent(evidence.attempt_id)}"]`).click();
  const attemptURL = '/api/attempts/' + encodeURIComponent(evidence.attempt_id);
  const attempt = evidence.expected[attemptURL].data, result = evidence.expected[attemptURL + '/result'];
  await expect(page.getByRole('heading', { name: `计算记录 ${attempt.execution_state}` })).toBeVisible();
  const panel = page.getByRole('region', { name: 'Gaussian Result 摘要' });
  await expect(panel.getByText('摘要可读', { exact: true })).toBeVisible();
  const datum = label => panel.locator('.field').filter({ has: page.locator('dt', { hasText: label }) }).locator('dd');
  await expect(datum('Query 记录状态')).toHaveText(attempt.result_state);
  await expect(datum('优化完成标记')).toHaveText(result.summary.optimization.completed_marker ? '已记录' : '未观察到');
  await expect(datum('驻点标记')).toHaveText(result.summary.optimization.stationary_point_marker ? '已记录' : '未观察到');
  await expect(datum('最终能量 / Hartree')).toHaveText(String(result.summary.final_energy_hartree ?? '未记录'));
  await expect(datum(/^频率数量$/)).toHaveText(String(result.summary.frequency.count ?? '未记录'));
  await expect(datum('虚频数量')).toHaveText(String(result.summary.frequency.imaginary_count ?? '未知（未记录频率）'));
  await expect(datum('终止状态')).toHaveText({ 'normal-termination': '正常终止', 'error-termination': '错误终止', unknown: '未确定' }[result.summary.termination.status]);
  await expect(datum('正常 / 错误终止次数')).toHaveText(`${result.summary.termination.normal_count} / ${result.summary.termination.error_count}`);
  await panel.getByText('所选结果的来源与绑定', { exact: true }).click();
  expect(JSON.parse(await panel.locator('pre').first().textContent())).toEqual(result.source);
  await panel.getByText(`归档历史 · ${result.history.length} 次采集`, { exact: true }).click();
  await expect(panel.locator('.log')).toHaveCount(result.history.length);
  for (const history of result.history) {
    const row = panel.locator('.log').filter({ has: page.getByText(`Envelope · ${history.envelope_id}`, { exact: true }) });
    await expect(row.locator('strong')).toHaveText(`采集 ${history.capture_sequence} · ${history.selected ? '当前选中' : '历史记录'} · ${history.capture_completeness}`);
    await expect(row.getByText(history.capture_source_id, { exact: true })).toBeVisible();
    await expect(row.locator('div > code')).toHaveCount(history.results.length);
    for (const record of history.results) {
      const item = row.getByText(`Result · ${record.result_id}`, { exact: true });
      await expect(item).toBeVisible();
      await expect(item.locator('..').locator('p')).toHaveText(`${record.parser.qualification} · ${record.parser.parse_status}`);
    }
  }
  await panel.getByText(`记录清单 · ${result.record_inventory.length}`, { exact: true }).click();
  expect(JSON.parse(await panel.locator('pre').last().textContent())).toEqual(result.record_inventory);
  await page.screenshot({ path: path.join(directory, 'attempt-desktop.png'), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: path.join(directory, 'attempt-mobile.png'), fullPage: true });
  await page.getByRole('button', { name: '断开', exact: true }).click();
  await expect(panel).toHaveCount(0);
  expect(errors).toEqual([]); expect(methods.every(x => x === 'GET')).toBe(true);
  expect(await fingerprint()).toEqual(before);
  const receipt = { schema: 'autog-real-gaussian-acceptance/1', checked_at: new Date().toISOString(), status: 'PASS',
    source_sha256: before.sha256, source_unchanged: true, source_fact_checks: evidence.source_fact_checks,
    exact_http_dto_routes: Object.keys(evidence.expected).length, browser_value_source_history_match: true,
    core_state: attempt.execution_state, result_availability: result.availability, browser_errors: 0, only_get: true,
    installed_isolated_runtime: true, bundled_ui: true, scientific_acceptance_inferred: false };
  await writeFile(path.join(directory, 'receipt.json'), JSON.stringify(receipt, null, 2) + '\n');
  console.log(JSON.stringify(receipt));
} finally {
  if (browser) await browser.close();
  if (child.exitCode === null) { child.kill('SIGTERM'); await new Promise(resolve => child.once('exit', resolve)); }
}
