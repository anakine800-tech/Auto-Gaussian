import {chromium,expect} from '@playwright/test';
import {writeFile} from 'node:fs/promises';
import path from 'node:path';
const dir=process.argv[2],id=process.argv[3];if(!dir||!path.isAbsolute(dir)||!id)throw Error('absolute output dir');
const browser=await chromium.launch({channel:'chrome'});try{const page=await browser.newPage({viewport:{width:1440,height:960}});await page.goto('http://127.0.0.1:8767/#/attempts/'+encodeURIComponent(id));await expect(page.getByTestId('molecule-atom')).toHaveCount(3);const metrics=await page.evaluate(()=>({height:document.documentElement.scrollHeight,moleculeTop:document.querySelector('.molecule-section').getBoundingClientRect().top+scrollY}));await writeFile(path.join(dir,'baseline-layout.json'),JSON.stringify(metrics));await page.screenshot({path:path.join(dir,'before-desktop.png')});console.log(metrics);}finally{await browser.close();}
