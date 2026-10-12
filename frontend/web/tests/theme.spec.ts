import {test,expect} from '@playwright/test';
test('neutral surfaces preserve semantic result colors and readable status contrast',async({page})=>{
 await page.goto('/#/analysis?tab=results');await page.getByLabel('只读访问令牌').fill('browser-test-only-'+'0'.repeat(32));await page.getByRole('button',{name:'连接数据源'}).click();
 await expect(page.locator('.badge.calc-normal').first()).toBeVisible();
 const colors=await page.locator('.badge.calc-normal').first().evaluate(e=>{const s=getComputedStyle(e);return {fg:s.color,bg:s.backgroundColor,body:getComputedStyle(document.body).backgroundColor};});
 expect(colors.fg).toBe('rgb(36, 102, 59)');expect(colors.bg).toBe('rgb(233, 245, 236)');expect(colors.body).toBe('rgb(243, 246, 249)');
 function luminance(s:string){const rgb=s.match(/\d+/g)!.slice(0,3).map(Number).map(v=>{const c=v/255;return c<=.04045?c/12.92:((c+.055)/1.055)**2.4;});return .2126*rgb[0]+.7152*rgb[1]+.0722*rgb[2];}
 expect((luminance(colors.bg)+.05)/(luminance(colors.fg)+.05)).toBeGreaterThan(4.5);
 await page.setViewportSize({width:390,height:844});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});
