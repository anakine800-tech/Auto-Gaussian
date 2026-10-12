import {test,expect} from '@playwright/test';
import path from 'node:path';
const enabled=process.env.AUTOG_TEST_LIBRARY==='1';
test('completed local fetch archives automatically, preserves unknown links and plays genuine modes',async({page,request})=>{
 test.skip(!enabled,'requires isolated library fixture');test.setTimeout(45000);
 const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
 const token='browser-test-only-'+'0'.repeat(32),headers={Authorization:'Bearer '+token};
 const s=await (await request.get('/api/library',{headers})).json();
 await page.goto('/#/library');await page.getByLabel('只读访问令牌').fill(token);await page.getByRole('button',{name:'连接数据源'}).click();await expect(page.getByRole('heading',{name:'本地库设置'})).toBeVisible();
 await page.getByLabel('已完成回收的文件夹',{exact:true}).fill(path.join(path.dirname(s.root),'fetch-complete'));
 await expect(page.getByRole('button',{name:'核验并归档本地文件'})).toBeDisabled();
 await page.getByRole('checkbox',{name:'文件传输已结束，目录内容已完整'}).check();await page.getByRole('button',{name:'核验并归档本地文件'}).click();
 await expect(page.getByText('已入库',{exact:true})).toBeVisible({timeout:20000});
 const archives=await(await request.get('/api/archives',{headers})).json();const record=archives.items.find((r:{title:string})=>r.title.includes('recovered'));
 expect(record).toBeTruthy();await page.goto('/#/archives/'+record.archive_id);await page.getByRole('button',{name:'结构与结果',exact:true}).click();
 await expect(page.getByTestId('molecule-scene')).toBeVisible();
 await page.getByRole('button',{name:'来源与记录',exact:true}).click();
 const history=page.locator('details').filter({has:page.locator('summary', {hasText:'历史输入与任务来源'})}).first();await history.locator('summary').first().click();
 await expect(history).toContainText('输入与声明 SHA-256 一致');await expect(history).toContainText('日志关联未知');await expect(history).toContainText('historic-test-attempt');
 await page.getByRole('button',{name:'运行与诊断',exact:true}).click();await page.getByRole('button',{name:'读取已归档日志'}).click();await expect(page.getByTestId('paged-log')).toBeVisible();await expect(page.getByTestId('raw-log')).toContainText('Entering Gaussian');await page.getByRole('button',{name:'下一段',exact:true}).click();await expect(page.getByTestId('paged-log')).toContainText('第 121');
 await page.getByRole('button',{name:'最后一次正常终止'}).click();await expect(page.getByTestId('raw-log')).toContainText('Normal termination');
 await page.getByRole('button',{name:'结构与结果',exact:true}).click();await page.getByRole('button',{name:'定位原日志：最后记录坐标',exact:true}).click();await expect(page.getByTestId('source-excerpt')).toContainText('Standard orientation');
 await page.getByRole('button',{name:'结构与结果',exact:true}).click();
 const modes=await(await request.get('/api/archives/'+record.archive_id+'/vibrations',{headers})).json();expect(modes.vibrations.availability).toBe('available');expect(modes.vibrations.data.modes).toHaveLength(3);
 await page.getByRole('button',{name:'读取振动模式'}).click();await page.getByRole('button',{name:'播放模式 1',exact:true}).click();await expect(page.getByTestId('vibration-controls')).toContainText('播放中');await page.getByRole('button',{name:'暂停动画',exact:true}).click();
 await page.setViewportSize({width:390,height:844});await expect(page.getByTestId('molecule-scene')).toBeVisible();expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);expect(errors).toEqual([]);
});

test('archive listing updates when a new completed local capture is archived',async({page,request})=>{
 test.skip(!enabled,'requires isolated library fixture');test.setTimeout(30000);
 const token='browser-test-only-'+'0'.repeat(32),headers={Authorization:'Bearer '+token};
 const status=await(await request.get('/api/library',{headers})).json();
 const fs=await import('node:fs/promises');const root=path.dirname(status.root);expect(path.basename(root)).toMatch(/^autog-ui-test-/);
 const source=path.join(root,'second-fetch');await fs.mkdir(source);const raw=await fs.readFile(path.join(root,'fetch-complete','recovered.log'),'utf8');await fs.writeFile(path.join(source,'new-result.log'),raw.replace('-75.000000','-76.000000'));
 await page.goto('/#/analysis?tab=results');await page.getByLabel('只读访问令牌').fill(token);const initial=page.waitForResponse(r=>r.url().endsWith('/api/library'));await page.getByRole('button',{name:'连接数据源'}).click();await initial;
 const before=await(await request.get('/api/archives',{headers})).json();await expect(page.locator('.science-index tbody tr')).toHaveCount(before.items.length);
 const captured=await request.post('/api/library/capture',{headers:{...headers,Origin:'http://127.0.0.1:18765','X-Autog-Library':'library/1'},data:{source}});expect(captured.status()).toBe(200);
 await expect(page.locator('.science-index tbody tr')).toHaveCount(before.items.length+1,{timeout:20000});
});
