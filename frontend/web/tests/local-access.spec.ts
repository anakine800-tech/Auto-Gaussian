import {test,expect} from '@playwright/test';
test.skip(process.env.AUTOG_TEST_NO_TOKEN!=='1','Dedicated local no-token mode suite');
test('opens and refreshes without credentials or login form; API requests omit Authorization',async({page})=>{
 const headers:unknown[]=[];page.on('request',r=>{if(r.url().includes('/api/'))headers.push(r.headers()['authorization']);});
 await page.goto('/#/projects');await expect(page.getByRole('heading',{name:'项目库'})).toBeVisible();await expect(page.getByLabel('只读访问令牌')).toHaveCount(0);await expect(page.getByRole('button',{name:'断开',exact:true})).toHaveCount(0);
 await page.reload();await expect(page.locator('.project-card')).not.toHaveCount(0);await page.getByRole('button',{name:'刷新',exact:true}).click();await expect(page.locator('.project-card')).not.toHaveCount(0);expect(headers.length).toBeGreaterThan(1);expect(headers.every(h=>h===undefined)).toBe(true);
});
test('deep-linked result and read-only mode lookup need no token',async({page})=>{
 await page.goto('/#/attempts/gaussian-normal');await page.getByRole('button',{name:'结构与结果',exact:true}).click();await expect(page.getByTestId('full-frequencies')).toContainText('-123.4');await page.getByRole('button',{name:'读取振动模式'}).click();await expect(page.getByText('暂无绑定的振动位移数据，无法播放。')).toBeVisible();await expect(page.getByLabel('只读访问令牌')).toHaveCount(0);
});
