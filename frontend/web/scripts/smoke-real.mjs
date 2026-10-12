// Real local-store UI check. Credentials stay in memory; output contains no IDs.
import { chromium, expect } from '@playwright/test';
import { spawn } from 'node:child_process';
import { randomBytes, createHash } from 'node:crypto';
import { readFile, stat, readdir, mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { setTimeout as delay } from 'node:timers/promises';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const database = process.argv[2];
if (!database || !path.isAbsolute(database)) throw new Error('Pass one absolute local Core database path');
const directory = path.join(root, '.local/ui-smoke');
const token = randomBytes(32).toString('base64url');
const origin = 'http://127.0.0.1:18766';
async function fingerprint() {
  const s = await stat(database);
  return { sha256: createHash('sha256').update(await readFile(database)).digest('hex'), size: s.size, inode: s.ino, mtime: s.mtimeMs, ctime: s.ctimeMs, entries: (await readdir(path.dirname(database))).sort() };
}
const before = await fingerprint();
const child = spawn(path.join(root, '.venv/bin/python'), ['-B', '-m', 'autog_frontend', '--database', database, '--port', '18766', '--ui-directory', path.join(root, 'web/dist')], {
  cwd: root, env: { ...process.env, AUTOG_READ_TOKEN: token, PYTHONDONTWRITEBYTECODE: '1' }, stdio: ['ignore', 'ignore', 'pipe'],
});
let browser;
try {
  let ready = false;
  for (let n = 0; n < 100; n++) {
    if (child.exitCode !== null) throw new Error('Preview server could not start');
    try { const r = await fetch(origin + '/api/projects', { headers: { Authorization: `Bearer ${token}` } }); if (r.ok) { ready = true; break; } } catch { /* startup */ }
    await delay(100);
  }
  if (!ready) throw new Error('Local preview startup timeout');
  const get = async url => { const r = await fetch(origin + url, { headers: { Authorization: `Bearer ${token}` } }); if (!r.ok) throw new Error('Source query unavailable'); return r.json(); };
  const projects = (await get('/api/projects')).data.items;
  if (!projects.length) throw new Error('No Project in selected source');
  const project = projects[0];
  const tasks = (await get(`/api/projects/${encodeURIComponent(project.project_id)}/tasks`)).data.items;
  const attempts = (await get(`/api/projects/${encodeURIComponent(project.project_id)}/attempts`)).data.items;
  if (!attempts.length) throw new Error('No Attempt in selected source');
  const attempt = attempts[0];
  await mkdir(directory, { recursive: true });
  browser = await chromium.launch({ channel: 'chrome' });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1024 } });
  const errors = []; const methods = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });
  page.on('request', req => { if (req.url().includes('/api/')) methods.push(req.method()); });
  await page.goto(origin);
  await page.getByLabel('只读访问令牌').fill(token);
  await page.getByRole('button', { name: '连接数据源' }).click();
  await expect(page.getByRole('heading', { name: `Projects ${projects.length}` })).toBeVisible();
  await page.screenshot({ path: path.join(directory, 'projects.png'), fullPage: true });
  await page.locator(`a[href="#/projects/${encodeURIComponent(project.project_id)}"]`).click();
  await expect(page.getByText(`${tasks.length} Tasks / ${attempts.length} Attempts`)).toBeVisible();
  await page.screenshot({ path: path.join(directory, 'project-detail.png'), fullPage: true });
  await page.locator(`a[href="#/attempts/${encodeURIComponent(attempt.attempt_id)}"]`).click();
  await expect(page.getByRole('heading', { name: `计算记录 ${attempt.execution_state}` })).toBeVisible();
  await expect(page.getByText('结构、逐项频率、热化学与原始日志内容待接入。', { exact: true })).toBeVisible();
  await expect(page.locator('.result-panel')).toContainText(attempt.result_state);
  await expect(page.locator('.result-panel [role=status]')).toHaveCount(0);
  await expect(page.locator('.result-panel [role=alert]')).toHaveCount(0);
  await page.screenshot({ path: path.join(directory, 'attempt-detail.png'), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: path.join(directory, 'attempt-mobile.png'), fullPage: true });
  expect(errors).toEqual([]);
  expect(methods.every(x => x === 'GET')).toBe(true);
  expect(await fingerprint()).toEqual(before);
  const report = { checked_at: new Date().toISOString(), source_sha256: before.sha256, projects: projects.length, tasks: tasks.length, attempts: attempts.length, execution_state: attempt.execution_state, result_state: attempt.result_state, source_unchanged: true, browser_errors: errors.length, only_get: true, screenshots: 4 };
  await writeFile(path.join(directory, 'receipt.json'), JSON.stringify(report, null, 2) + '\n');
  console.log(JSON.stringify(report));
} finally {
  if (browser) await browser.close();
  if (child.exitCode === null) {
    child.kill('SIGTERM');
    await new Promise(resolve => child.once('exit', resolve));
  }
}
