import {chromium} from '@playwright/test';
import fs from 'node:fs/promises';
const base=process.env.AUTOG_ACCEPT_URL??'http://127.0.0.1:8769';
const out=process.env.AUTOG_ACCEPT_OUTPUT;
if(!out)throw Error('Set AUTOG_ACCEPT_OUTPUT to a local evidence directory.');
await fs.mkdir(out,{recursive:true});
const browser=await chromium.launch({channel:'chrome',headless:true});
const context=await browser.newContext({viewport:{width:1440,height:1000}}),page=await context.newPage();
const errors=[],writes=[],failures=[];
page.on('pageerror',e=>errors.push(e.message));page.on('response',r=>{if(r.url().includes('/api/')&&r.status()>=400)failures.push({url:r.url(),status:r.status()});});
await page.route('**/api/**',async route=>{if(route.request().method()!=='GET'){writes.push(route.request().url());await route.abort();}else await route.continue();});
const jump=async hash=>{await page.evaluate(h=>location.hash=h,hash);};
const check=async()=>{if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1)){await page.screenshot({path:out+'/overflow.png',fullPage:true});await fs.writeFile(out+'/overflow.json',JSON.stringify(await page.evaluate(()=>({route:location.hash,width:innerWidth,scroll:document.documentElement.scrollWidth,offenders:[...document.querySelectorAll('main *, header *, .project-context *')].filter(e=>e.getBoundingClientRect().right>innerWidth+1&&e.getBoundingClientRect().width>0).slice(0,15).map(e=>({tag:e.tagName,cls:e.className,text:e.textContent?.slice(0,80),right:e.getBoundingClientRect().right}))})),null,2));throw Error('Horizontal overflow; see overflow.json');}};
try{
 await page.goto(base+'/#/projects');await page.locator('.organized-card').first().waitFor({timeout:30000});
 const nav=await page.getByRole('navigation',{name:'主导航'}).getByRole('link').allTextContents();if(nav.join(',')!=='项目,计算,分析,监控')throw Error('Wrong navigation');
 await page.screenshot({path:out+'/projects.png',fullPage:true});
 await page.getByRole('navigation',{name:'主导航'}).getByRole('link',{name:'计算',exact:true}).click();await page.getByRole('heading',{name:'运行总览',exact:true}).waitFor();const tabs=await page.getByRole('navigation',{name:'页面分区'}).getByRole('link').allTextContents();if(tabs[0]!=='运行与历史')throw Error('Calculation default/order mismatch');await page.screenshot({path:out+'/calculations.png',fullPage:true});
 await jump('#/analysis?tab=results');await page.locator('.science-index tbody tr').filter({has:page.locator('.calc-normal')}).first().locator('a').first().waitFor({timeout:30000});const target=await page.locator('.science-index tbody tr').filter({has:page.locator('.calc-normal')}).first().locator('a').first().getAttribute('href');await page.locator('.science-index tbody tr').filter({has:page.locator('.calc-normal')}).first().locator('a').first().click();await page.getByRole('button',{name:'结构与结果',exact:true}).waitFor();if(await page.getByLabel('详情显示方式').getByRole('button').count()!==3)throw Error('Expected three detail tabs');await page.locator('.molecule-section').waitFor({timeout:30000});await page.getByRole('button',{name:'导出结果',exact:true}).waitFor({timeout:30000});await check();await page.screenshot({path:out+'/overview.png',fullPage:true});
 await page.getByRole('button',{name:'结构与结果',exact:true}).click();await page.locator('.molecule-section').waitFor({timeout:30000});await check();await page.screenshot({path:out+'/science.png',fullPage:true});
 await page.getByRole('button',{name:'来源与记录',exact:true}).click();await page.getByTestId('result-provenance').waitFor();await check();
 await page.getByRole('button',{name:'导出结果',exact:true}).click();await page.getByRole('dialog',{name:'导出结果',exact:true}).waitFor();await page.screenshot({path:out+'/export-drawer.png'});await page.keyboard.press('Escape');
 await page.getByRole('button',{name:'运行与诊断',exact:true}).click();await page.getByRole('button',{name:'读取报错与优化轨迹'}).click();await page.getByTestId('calculation-analysis').waitFor();
 await jump('#/calculations?tab=drafts');await page.getByRole('heading',{name:'计算草稿',exact:true}).waitFor();await check();await page.screenshot({path:out+'/drafts.png',fullPage:true});
 for(const hash of ['#/drafts','#/offline-science','#/analysis?tab=thermo','#/capabilities']){await jump(hash);await page.locator('h1').waitFor();await check();}
 await page.setViewportSize({width:390,height:844});await jump(target);await page.getByRole('button',{name:'结构与结果',exact:true}).click();await page.getByRole('button',{name:'导出结果',exact:true}).waitFor();await check();await page.screenshot({path:out+'/mobile.png',fullPage:true});
 const capabilities=await page.evaluate(()=>fetch('/api/capabilities').then(r=>r.json()));
 if(capabilities.version!=='0.27.0+local.2'||capabilities.features.execution!==false)throw Error('Unexpected runtime capabilities');
 const optionalUnavailable=failures.filter(r=>capabilities.features.library===false&&r.url.endsWith('/api/library')&&r.status===404);const fatal=failures.filter(r=>!optionalUnavailable.includes(r));if(writes.length||errors.length||fatal.length)throw Error(JSON.stringify({errors,writes,failures:fatal}));
 await fs.writeFile(out+'/acceptance.json',JSON.stringify({status:'PASS',url:base,version:capabilities.version,execution_enabled:false,navigation:nav,writes,errors,failures:fatal,optionalUnavailable,screenshots:['projects','overview','science','export-drawer','drafts','mobile']},null,2));
 console.log('Read-only navigation acceptance PASS');
}finally{await context.close();await browser.close();}
