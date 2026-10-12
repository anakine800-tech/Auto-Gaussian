import {test,expect} from '@playwright/test';
import type {Page} from '@playwright/test';
import {createHash} from 'node:crypto';
import {boundSpan,frequencySources,locateSource} from '../src/provenance';
const text='来源 🧪\r\n Frequencies -- -123.4\r\n Frequencies -- -123.4\r\n 热化学 -75.1\r\n Normal termination\r\n';
const bytes=Buffer.from(text),sha=createHash('sha256').update(bytes).digest('hex');
const artifact={artifact_kind:'gaussian-log',logical_name:'synthetic.log',envelope_observation_id:'fixture-envelope',sha256:sha,size_bytes:bytes.length};
const start=bytes.indexOf(' Frequencies'),end=bytes.indexOf(' Frequencies',start+1),last=bytes.indexOf(' 热化学');
const first={...artifact,start,end},second={...artifact,start:end,end:last};
const logSource={kind:'verified-local-log',sha256:sha,size_bytes:bytes.length};
test('spans require the exact artifact identity and bounded integer offsets',()=>{
 expect(boundSpan(first,artifact)).toBe(true);
 for(const changed of [{start:-1},{end:bytes.length+1},{start:1.5},{end:start},{sha256:'a'.repeat(64)},{envelope_observation_id:'other'},{logical_name:'other.log'},{size_bytes:1},{artifact_kind:'other'}])expect(boundSpan({...first,...changed},artifact)).toBe(false);
 expect(boundSpan({start,end},artifact)).toBe(false);
});
test('duplicate frequency values retain ordinal source blocks and mismatched arrays withhold attribution',()=>{
 const blocks=[{'frequencies_cm-1':[-123.4],source_span:first},{'frequencies_cm-1':[-123.4],source_span:second}];
 expect(frequencySources([-123.4,-123.4],blocks,artifact)).toEqual([first,second]);expect(frequencySources([-123.4,100],blocks,artifact)).toEqual([null,null]);expect(frequencySources([-123.4],null,artifact)).toEqual([null]);
});
test('UTF-8 source mapping handles CJK, emoji and CRLF; tampering and split codepoints are rejected',async()=>{
 const actual=await locateSource(text,logSource,'synthetic.log',{label:'first',span:first});expect(actual).toEqual({firstLine:1,lastLine:1,excerpt:' Frequencies -- -123.4\r\n'});
 await expect(locateSource(text.replace('-75.1','-75.2'),logSource,'synthetic.log',{label:'first',span:first})).rejects.toThrow();
 await expect(locateSource(text,logSource,'other.log',{label:'first',span:first})).rejects.toThrow();
 await expect(locateSource(text,logSource,'synthetic.log',{label:'bad',span:{...first,start:1}})).rejects.toThrow();
});
async function connect(page:Page){await page.goto('/#/attempts/gaussian-normal');await page.getByLabel('只读访问令牌').fill('browser-test-only-'+'0'.repeat(32));await page.getByRole('button',{name:'连接数据源'}).click();await page.getByRole('button',{name:'结构与结果',exact:true}).click();}
async function fixture(page:Page,missing=false,wrongLog=false){
 await page.route('**/api/attempts/gaussian-normal/details',async route=>{const r=await route.fetch(),d=await r.json();d.result.source={kind:'persisted-attributed-result',result_id:'fixture-result',parser:'auto-g16-v3-gaussian-job',parser_version:'1.1.0',artifact};d.result.data.frequencies_cm1=[-123.4,-123.4];d.result.data.frequency_blocks=[{'frequencies_cm-1':[-123.4],source_span:missing?{...first,sha256:'b'.repeat(64)}:first},{'frequencies_cm-1':[-123.4],source_span:second}];d.result.data.thermochemistry={sum_electronic_gibbs_hartree:{value_hartree:-75.1,source_span:{...artifact,start:last,end:bytes.indexOf(' Normal')}}};await route.fulfill({json:d});});
 await page.route('**/api/attempts/gaussian-normal/log',route=>route.fulfill({json:{schema:'auto-g16-detail-evidence/1',kind:'attempt',id:'gaussian-normal',log:{availability:'available',reason:null,source:wrongLog?{...logSource,sha256:'c'.repeat(64)}:logSource,data:{text,logical_name:'synthetic.log',line_count:5}}}}));
}
test('provenance shows parser/hash and separates facts; each repeated frequency locates its own exact bytes',async({page})=>{
 await fixture(page);await connect(page);await page.getByRole('button',{name:'来源与记录',exact:true}).click();const card=page.getByTestId('result-provenance');await expect(card).toContainText(sha);await expect(card).toContainText('fixture-result');await expect(card).toContainText('明确记录的键级');await expect(card).toContainText('未接入');
 await page.getByRole('button',{name:'结构与结果',exact:true}).click();await page.getByRole('button',{name:'定位原日志：频率 2（-123.4 cm⁻¹）',exact:true}).click();await expect(page.getByTestId('source-excerpt')).toContainText('第 3–3 行');await expect(page.getByTestId('source-excerpt').locator('pre')).toHaveText(' Frequencies -- -123.4\r\n');
 await page.getByRole('button',{name:'结构与结果',exact:true}).click();await page.locator('.thermochemistry-details > summary').click();await page.getByRole('button',{name:'定位原日志：电子能 + Gibbs 校正',exact:true}).click();await expect(page.getByTestId('source-excerpt')).toContainText('第 4–4 行');await expect(page.getByTestId('source-excerpt')).toContainText('热化学 -75.1');
});
test('unbound spans cannot be clicked and mismatched log hash cannot produce a verified excerpt',async({page})=>{
 await fixture(page,true,true);await connect(page);await expect(page.getByTestId('full-frequencies').locator('tbody tr').first()).toContainText('来源区间未绑定');await expect(page.getByRole('button',{name:'定位原日志：频率 1（-123.4 cm⁻¹）',exact:true})).toHaveCount(0);
 await page.getByRole('button',{name:'结构与结果',exact:true}).click();await page.getByRole('button',{name:'定位原日志：频率 2（-123.4 cm⁻¹）',exact:true}).click();await expect(page.getByTestId('source-excerpt')).toContainText('来源定位失败');await expect(page.getByTestId('source-excerpt').locator('pre')).toHaveCount(0);
});
test('Review selected geometry follows its own source span, separate from the last geometry',async({page})=>{
 await fixture(page);await page.unroute('**/api/attempts/gaussian-normal/details');
 await page.route('**/api/attempts/gaussian-normal/details',async route=>{const r=await route.fetch(),d=await r.json();const g={units:'angstrom',orientation_kind:'fixture-orientation',atoms:[{center:1,atomic_number:1,x:0,y:0,z:0}],source_span:first};d.result.source={...d.result.source,artifact};d.result.data.last_geometry=g;d.review={availability:'available',reason:null,source:{kind:'historical-review-report',review_bundle_id:'fixture-review',sha256:'d'.repeat(64)},data:{classification:'TEST_ONLY',acceptances:[],selected_final_geometry:{...g,source_span:second}}};await route.fulfill({json:d});});
 await connect(page);await page.getByRole('button',{name:'定位原日志：最后记录坐标',exact:true}).click();await expect(page.getByTestId('source-excerpt')).toContainText('第 2–2 行');await page.getByRole('button',{name:'结构与结果',exact:true}).click();await page.getByLabel('结构来源').selectOption('review');await page.getByRole('button',{name:'定位原日志：Review 选中坐标',exact:true}).click();await expect(page.getByTestId('source-excerpt')).toContainText('第 3–3 行');await page.getByRole('button',{name:'来源与记录',exact:true}).click();await expect(page.getByTestId('result-provenance')).toContainText('fixture-review');
});
test('mobile provenance and exact source excerpt fit viewport; disconnect clears evidence',async({page})=>{
 await fixture(page);await page.setViewportSize({width:390,height:844});await connect(page);await page.getByRole('button',{name:'来源与记录',exact:true}).click();await expect(page.getByTestId('result-provenance')).toBeVisible();await page.getByRole('button',{name:'结构与结果',exact:true}).click();expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);await page.getByRole('button',{name:'定位原日志：频率 1（-123.4 cm⁻¹）',exact:true}).click();await expect(page.getByTestId('source-excerpt')).toContainText('已核对 SHA-256');expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);await page.getByRole('button',{name:'断开',exact:true}).click();await expect(page.getByTestId('result-provenance')).toHaveCount(0);await expect(page.getByTestId('source-excerpt')).toHaveCount(0);
});
test('unavailable local log keeps explicit missing status after a source jump',async({page})=>{
 await connect(page);await page.getByRole('button',{name:/定位原日志：频率 1/}).click();await expect(page.getByText('尚未连接与此结果匹配的本地日志。')).toBeVisible();await expect(page.getByTestId('source-excerpt')).toHaveCount(0);
});
