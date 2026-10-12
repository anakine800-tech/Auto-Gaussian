import {test,expect} from '@playwright/test';
import type {Page} from '@playwright/test';
const token='browser-test-only-'+'0'.repeat(32);
const metrics={cpu_percent:50,logical_cpus:4,load_1m:2,load_5m:1,load_15m:.5,memory_total_mib:8192,memory_available_mib:6144,memory_used_mib:2048,swap_total_mib:4096,swap_used_mib:0};
const sample={sampled_at:'2026-09-25T01:00:00Z',server_time:'2026-09-24T21:00:00-0400',hostname:'test-node',user:'testuser',metrics,process_count:1,processes:[{pid:123,ppid:12,cpu_percent:200,rss_mib:1024,elapsed:'02:00:00',command:'l502.exe'}],issues:[] as string[],raw_sha256:'a'.repeat(64),sources:{queue:{exit_code:0,text:'Job ID  User  Jobname  State\nfixture  testuser  test-only  R'},nodes:{exit_code:0,text:'test-node\n    jobs = 0-3/fixture'}}};
function dto(){return {schema:'autog-server-monitor/1',enabled:true,state:'fresh',error:null as string|null,interval_seconds:30,age_seconds:2,route:'Mac → SSH → test server',retention_samples:2880,sample:structuredClone(sample),history:[{at:'2026-09-25T00:59:00Z',metrics,error:null},{at:'2026-09-25T00:59:30Z',metrics:null,error:'timeout'},{at:'2026-09-25T01:00:00Z',metrics,error:null}]};}
async function connect(page:Page){await page.goto('/#/monitor');await page.getByLabel('只读访问令牌').fill(token);await page.getByRole('button',{name:'连接数据源'}).click();}
test('monitor disabled by default does not expose a command or host form',async({page})=>{
  await connect(page);await expect(page.getByText('未启用采样',{exact:true})).toBeVisible();await expect(page.locator('.monitor-page input')).toHaveCount(0);
});
test('real units, separate queue, collapsed sources, gap-aware trends and mobile fit',async({page})=>{
  const writes:string[]=[],errors:string[]=[];page.on('request',r=>{if(r.method()!=='GET')writes.push(r.method());});page.on('pageerror',e=>errors.push(e.message));
  const d=dto();d.sample.processes[0].command='<img src=x onerror=alert(1)>';
  await page.route('**/api/monitor',r=>r.fulfill({json:d}));await connect(page);
  await expect(page.getByRole('status')).toHaveText('采样正常');await expect(page.locator('.monitor-kpis')).toContainText('50.0');await expect(page.locator('.monitor-kpis')).toContainText('2.0 / 8.0 GiB');
  await expect(page.locator('.monitor-trend-cpu .monitor-trend-value')).toContainText('50.0%');await expect(page.locator('.monitor-trend-memory .monitor-trend-value')).toContainText('25.0%');await expect(page.locator('.monitor-trend-memory .monitor-trend-value')).toContainText('2.0 / 8.0 GiB');await expect(page.locator('.monitor-axis')).toHaveCount(10);await expect(page.locator('.monitor-trend-cpu .monitor-axis')).toHaveText(['0%','25%','50%','75%','100%']);
  await expect(page.locator('.monitor-queue')).toContainText('fixture');await expect(page.locator('.monitor-page tbody')).toContainText('200.0');await expect(page.locator('.monitor-page tbody')).toContainText('<img src=x onerror=alert(1)>');await expect(page.locator('.monitor-page tbody img')).toHaveCount(0);
  await expect(page.locator('.monitor-evidence')).not.toHaveAttribute('open','');await expect(page.locator('.monitor-trend').first().locator('polyline')).toHaveCount(2);
  await page.setViewportSize({width:390,height:844});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);expect(errors).toEqual([]);expect(writes).toEqual([]);
});
test('failure keeps old measurements visibly stale, unavailable queue is not empty queue',async({page})=>{
  const d=dto();d.state='stale';d.error='timeout';d.sample.sources.queue={exit_code:124,text:''};d.sample.issues=['queue'];
  await page.route('**/api/monitor',r=>r.fulfill({json:d}));await connect(page);await expect(page.getByRole('status')).toContainText('已过期');await expect(page.getByRole('alert')).toContainText('采样超时');await expect(page.getByText('队列读取不可用，不能解释为空队列。')).toBeVisible();await expect(page.locator('.monitor-kpis')).toContainText('50.0');
});
test('browser connection loss labels cached telemetry and navigation cancels polling',async({page})=>{
  let reads=0;
  await page.route('**/api/monitor',r=>++reads===1?r.fulfill({json:dto()}):r.abort());
  await connect(page);await expect(page.getByRole('status')).toHaveText('采样正常');await expect(page.getByRole('status')).toHaveText('页面连接中断',{timeout:8000});await expect(page.locator('.monitor-kpis')).toBeVisible();
  await page.getByRole('navigation',{name:'主导航'}).getByRole('link',{name:'项目',exact:true}).click();await expect(page.locator('.monitor-page')).toHaveCount(0);const before=reads;await page.waitForTimeout(5100);expect(reads).toBe(before);
});
