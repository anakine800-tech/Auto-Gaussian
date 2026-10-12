import {test,expect} from '@playwright/test';
import type {Page} from '@playwright/test';
import {scientificFacts,screenCandidate} from '../src/scientific-assessment';
const artifact={artifact_kind:'gaussian-log',envelope_observation_id:'envelope',logical_name:'fixture.log',sha256:'a'.repeat(64),size_bytes:1000};
const span=(start:number,end:number)=>({...artifact,start,end});
function fixture(frequencies=[-123.4,200,300]){
 return {source:{artifact,result_id:'fixture-result',parser:'auto-g16-v3-gaussian-job',parser_version:'1.1.0'},data:{frequencies_cm1:frequencies,frequency_blocks:[{'frequencies_cm-1':frequencies,source_span:span(300,400)}],scientific_facts:{schema:'auto-g16-scientific-display-facts/1',job_section:span(0,1000),program_status:'normal-termination',normal_termination_count:1,error_termination_count:0,termination_evidence:[{kind:'normal-termination',source_span:span(900,1000)}],optimization_completed_marker:true,optimization_completed_evidence:[span(100,150)],stationary_point_marker:true,stationary_point_evidence:[span(150,200)],frequency_parse_complete:true,frequency_count:frequencies.length,imaginary_frequency_count:frequencies.filter(v=>v<0).length}}};
}
test('zero, one and multiple imaginary frequencies are only provisional count-based candidates',()=>{
 for(const [freqs,code] of [[[100,200,300],'MINIMUM_CANDIDATE'],[[-.01,200,300],'TS_CANDIDATE'],[[-123.4,-.01,300],'NOT_FIRST_ORDER']] as const){const p=fixture([...freqs]);expect(screenCandidate(scientificFacts(p.data,p.source)).code).toBe(code);}
 const p=fixture();p.data.scientific_facts.frequency_parse_complete=false;expect(screenCandidate(scientificFacts(p.data,p.source)).code).toBe('FREQUENCY_INCOMPLETE');
 p.data.scientific_facts.frequency_parse_complete=true;p.data.scientific_facts.optimization_completed_marker=false;p.data.scientific_facts.optimization_completed_evidence=[];expect(screenCandidate(scientificFacts(p.data,p.source)).code).toBe('EVIDENCE_INCOMPLETE');
 p.data.scientific_facts.program_status='error-termination';p.data.scientific_facts.termination_evidence=[{kind:'error-termination',source_span:span(900,1000)}];p.data.scientific_facts.normal_termination_count=0;p.data.scientific_facts.error_termination_count=1;expect(screenCandidate(scientificFacts(p.data,p.source)).code).toBe('PROGRAM_FAILED');
});
test('mismatched counts, source spans and flags cannot produce candidate classification',()=>{
 for(const corrupt of [
  (p:ReturnType<typeof fixture>)=>{p.data.scientific_facts.imaginary_frequency_count=0;},
  (p:ReturnType<typeof fixture>)=>{p.data.scientific_facts.termination_evidence[0].source_span.sha256='b'.repeat(64);},
  (p:ReturnType<typeof fixture>)=>{p.data.scientific_facts.optimization_completed_evidence=[];},
  (p:ReturnType<typeof fixture>)=>{p.data.frequency_blocks[0].source_span.end=1001;},
  (p:ReturnType<typeof fixture>)=>{p.data.scientific_facts.program_status='error-termination';},
  (p:ReturnType<typeof fixture>)=>{p.data.frequency_blocks[0]['frequencies_cm-1']=[123.4,200,300];},
 ]){const p=fixture();corrupt(p);expect(scientificFacts(p.data,p.source)).toBeNull();expect(screenCandidate(scientificFacts(p.data,p.source)).code).toBe('EVIDENCE_UNAVAILABLE');}
});
async function connect(page:Page,id='gaussian-normal'){await page.goto('/#/attempts/'+id);await page.getByLabel('只读访问令牌').fill('browser-test-only-'+'0'.repeat(32));await page.getByRole('button',{name:'连接数据源'}).click();await page.getByRole('button',{name:'结构与结果',exact:true}).click();await page.getByTestId('scientific-validation').locator('summary').first().click();await expect(page.getByTestId('scientific-validation')).toBeVisible();}
test('one imaginary frequency shows pending human review; no acceptance control or write is issued',async({page})=>{
 const methods:string[]=[];page.on('request',r=>{if(r.url().includes('/api/'))methods.push(r.method());});await connect(page);
 const card=page.getByTestId('scientific-validation');await expect(card).toContainText('TS candidate');await expect(card).toContainText('PENDING HUMAN REVIEW');await expect(card).toContainText('-123.4');await expect(card).toContainText('Mode 1');await expect(card).toContainText('待核对计算类型与完整模式集');
 await expect(card.getByRole('checkbox')).toHaveCount(0);await expect(card.getByRole('button',{name:/Accept|接受|确认/})).toHaveCount(0);
 await card.getByRole('button',{name:'读取虚频位移'}).click();await expect(card).toContainText('未接入合格位移');await expect(card.getByRole('button',{name:'▶ 播放'})).toHaveCount(0);
 expect(methods.every(m=>m==='GET')).toBe(true);
});
test('missing frequency and error termination cannot be promoted to a minimum or TS',async({page})=>{
 await connect(page,'gaussian-no-frequency');await expect(page.getByTestId('candidate-assessment')).toContainText('FREQUENCY_INCOMPLETE');await expect(page.getByTestId('scientific-validation')).toContainText('虚频数量未知');
 await page.goto('/#/attempts/gaussian-error');await page.getByRole('button',{name:'结构与结果',exact:true}).click();await page.getByTestId('scientific-validation').locator('summary').first().click();await expect(page.getByTestId('candidate-assessment')).toContainText('PROGRAM_FAILED');await expect(page.getByTestId('candidate-assessment')).not.toContainText('TS candidate');
 await page.goto('/#/attempts/gaussian-v31');await page.getByRole('button',{name:'结构与结果',exact:true}).click();await page.getByTestId('scientific-validation').locator('summary').first().click();await expect(page.getByTestId('candidate-assessment')).toContainText('EVIDENCE_UNAVAILABLE');
});
test('unbound evidence withholds the card classification and mobile card stays in viewport',async({page})=>{
 await page.route('**/api/attempts/gaussian-normal/details',async route=>{const r=await route.fetch(),d=await r.json();d.result.data.scientific_facts.termination_evidence[0].source_span.sha256='b'.repeat(64);await route.fulfill({json:d});});
 await page.setViewportSize({width:390,height:844});await connect(page);await expect(page.getByTestId('candidate-assessment')).toContainText('EVIDENCE_UNAVAILABLE');expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await page.getByRole('button',{name:'断开',exact:true}).click();await expect(page.getByTestId('scientific-validation')).toHaveCount(0);
});

test('imaginary-mode action preserves the full frequency ordinal and never grants acceptance',async({page})=>{
 let packet:unknown;
 await page.route('**/api/attempts/gaussian-normal/details',async route=>{
  const response=await route.fetch(),d=await response.json(),a=d.result.source.artifact;
  const g={units:'angstrom',orientation_kind:'standard-orientation',source_span:{...a,start:408,end:500},atoms:[{center:1,atomic_number:8,x:0,y:0,z:0},{center:2,atomic_number:1,x:1,y:0,z:0},{center:3,atomic_number:1,x:0,y:1,z:0}]};
  d.result.data.last_geometry=g;d.result.data.frequencies_cm1=[200,-123.4,300];d.result.data.frequency_blocks[0]['frequencies_cm-1']=[200,-123.4,300];
  packet={schema:'auto-g16-mode-evidence/1',kind:'attempt',id:d.id,vibrations:{availability:'available',reason:null,source:{kind:'pinned-offline-vibration-modes',sha256:'b'.repeat(64),size_bytes:3000},data:{schema:'auto-g16-vibration-modes/1',kind:'attempt',id:d.id,decoder:{name:'autog-gaussian-cartesian-display-modes',version:'1.0.0'},vector_convention:'gaussian-printed-normalized-cartesian-displacements',result_source:d.result.source,reference_geometry:g,modes:d.result.data.frequencies_cm1.map((v:number,i:number)=>({mode_number:i+1,frequency_index:i,block_index:0,column_index:i,frequency_cm1:v,frequency_source_span:d.result.data.frequency_blocks[0].source_span,source_span:{...d.result.data.frequency_blocks[0].source_span,end:d.result.data.frequency_blocks[0].source_span.end+10},displacements:[{center:1,atomic_number:8,dx:0,dy:0,dz:-.07},{center:2,atomic_number:1,dx:0,dy:.45,dz:.54},{center:3,atomic_number:1,dx:0,dy:-.45,dz:.54}]}))}}};
  await route.fulfill({json:d});
 });
 await page.route('**/api/attempts/gaussian-normal/vibrations',route=>route.fulfill({json:packet}));
 await connect(page);const card=page.getByTestId('scientific-validation'),atom=page.locator('[data-testid="molecule-atom"][data-center="2"]'),before=await atom.getAttribute('transform');
 await expect(card).toContainText('Mode 2');await card.getByRole('button',{name:'读取虚频位移'}).click();await card.getByRole('button',{name:'查看虚频模式 2'}).click();
 await expect(page.getByTestId('vibration-controls')).toContainText('模式 2 · -123.4');await expect(atom).not.toHaveAttribute('transform',before!);
 await expect(card).toContainText('PENDING HUMAN REVIEW');await expect(card.getByRole('checkbox')).toHaveCount(0);
});
