import {test,expect} from '@playwright/test';
const token='browser-test-only-'+'0'.repeat(32);
test('malformed native routes stay inside the page and issue no native reads',async({page})=>{
 const errors:string[]=[],reads:string[]=[];
 page.on('pageerror',e=>errors.push(String(e)));
 page.on('request',r=>{if(r.url().includes('/api/v1/native/'))reads.push(r.url());});
 await page.goto('/#/native/%/attempts/example');
 await page.getByLabel('只读访问令牌').fill(token);
 await page.getByRole('button',{name:'连接数据源'}).click();
 for(const hash of ['#/native/%/attempts/example','#/native/source/unknown/example','#/native/source/attempts',
     '#/native/source/attempts/example/extra','#/native/source/projects/%E0%A4','#/native//attempts/example']){
  await page.evaluate(h=>location.hash=h,hash);
  await expect(page.getByRole('alert')).toContainText('invalid-route');
  await expect(page.getByRole('navigation',{name:'主导航'}).getByRole('link')).toHaveText(['项目','计算','分析','监控']);
 }
 expect(errors).toEqual([]);expect(reads).toEqual([]);
 await page.getByRole('navigation',{name:'主导航'}).getByRole('link',{name:'项目',exact:true}).click();
 await expect(page.getByRole('navigation',{name:'项目来源分区'})).toBeVisible();
});
test('native results remain a project subdestination with the current main navigation',async({page})=>{
 await page.goto('/#/projects');await page.getByLabel('只读访问令牌').fill(token);
 await page.getByRole('button',{name:'连接数据源'}).click();
 await page.getByRole('navigation',{name:'项目来源分区'}).getByRole('link',{name:'原生计算结果'}).click();
 await expect(page.getByRole('heading',{name:'原生计算结果',exact:true})).toBeVisible();
 await expect(page.getByRole('navigation',{name:'主导航'}).getByRole('link')).toHaveText(['项目','计算','分析','监控']);
 await expect(page.getByRole('navigation',{name:'主导航'}).getByRole('link',{name:'项目',exact:true})).toHaveAttribute('aria-current','page');
});

test('late native response cannot replace a new route or survive an invalid route',async({page})=>{
 let finishOld!:()=>void,arrived!:()=>void;
 const oldRequest=new Promise<void>(resolve=>{arrived=resolve;}),release=new Promise<void>(resolve=>{finishOld=resolve;});
 await page.route('**/api/v1/native/sources/test/projects/old/attempts',async route=>{
  arrived();await release;await route.fulfill({json:{schema:'wrong-old-response',kind:'attempts',data:{items:[]}}});
 });
 await page.route('**/api/v1/native/sources/test/projects/new/attempts',route=>route.fulfill({json:{schema:'auto-g16-native-query/1',kind:'attempts',data:{items:[]}}}));
 await page.goto('/#/native/test/projects/old');await page.getByLabel('只读访问令牌').fill(token);await page.getByRole('button',{name:'连接数据源'}).click();await oldRequest;
 await page.evaluate(()=>{location.hash='#/native/test/projects/new';});await expect(page.getByText('此项目尚无 Attempt。')).toBeVisible();
 const oldResponse=page.waitForResponse('**/api/v1/native/sources/test/projects/old/attempts');finishOld();await (await oldResponse).finished();await expect(page.getByRole('alert')).toHaveCount(0);await expect(page.getByText('此项目尚无 Attempt。')).toBeVisible();
 await page.evaluate(()=>{location.hash='#/native/%/attempts/example';});await expect(page.getByRole('alert')).toContainText('invalid-route');await expect(page.getByText('此项目尚无 Attempt。')).toHaveCount(0);
});

test('native panel waits beyond ordinary 15-second deadline without retrying',async({page})=>{
 let release!:()=>void,arrived!:()=>void,reads=0;
 const ready=new Promise<void>(resolve=>{arrived=resolve;}),pending=new Promise<void>(resolve=>{release=resolve;});
 await page.clock.install();
 await page.route('**/api/v1/native/sources/test/projects/slow/attempts',async route=>{
  reads++;arrived();await pending;await route.fulfill({json:{schema:'auto-g16-native-query/1',kind:'attempts',data:{items:[]}}});
 });
 await page.goto('/#/native/test/projects/slow');await page.getByLabel('只读访问令牌').fill(token);await page.getByRole('button',{name:'连接数据源'}).click();await ready;
 await page.clock.fastForward(20000);await expect(page.getByRole('status')).toContainText('正在读取');await expect(page.getByRole('alert')).toHaveCount(0);
 release();await expect(page.getByText('此项目尚无 Attempt。')).toBeVisible();expect(reads).toBe(1);
});
