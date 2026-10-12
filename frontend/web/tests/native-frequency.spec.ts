import {test,expect} from '@playwright/test';
const token='browser-test-only-'+'0'.repeat(32);
const fact=(value:unknown,unit:string|null=null)=>({availability:'available',value,unit,source:'synthetic-test',reason:null});
for(const parsed of [true,false]){
 test(`frequency count ${parsed?'zero is retained':'unknown is not zero'}`,async({page})=>{
  await page.route('**/api/v1/native/sources/freq/attempts/freq-attempt',route=>route.fulfill({json:{schema:'auto-g16-native-query/1',kind:'attempt',data:{
   source_id:'freq',project_id:'synthetic-project',workflow_run_id:'run',task_id:'task',attempt_id:'freq-attempt',
   generation:fact('V31'),program:fact('gaussian'),bound_plan:fact({id:'plan'}),input:fact([]),artifacts:fact([]),
   axes:{execution:fact('completed'),validation:fact({classification:parsed?'VALIDATED_TWO_STAGE_MINIMUM':'INCOMPLETE'})},
   facts:{energy:fact(-158,'hartree'),frequencies:fact([], 'cm^-1')},availability:'available',reason:null,record_inventory:[],history:[],
   provenance:{parsed_result:{parser_version:'1.2.0',frequency_unit:'cm^-1',frequency_count:parsed?36:null,
    imaginary_frequency_count:parsed?0:null,zero_frequency_count:parsed?1:null,optimization_attempt_id:'opt-attempt',frequency_attempt_id:'freq-attempt'}}
  }}}));
  await page.goto('/#/native/freq/attempts/freq-attempt');
  await page.getByLabel('只读访问令牌').fill(token);await page.getByRole('button',{name:'连接数据源'}).click();
  const summary=page.locator('.native-frequency-summary');
  await expect(summary).toContainText('cm^-1');await expect(summary).toContainText('opt-attempt → Freq Attempt：freq-attempt');
  if(parsed){await expect(summary).toContainText('模式数：36 · 负频：0 · 零频：1');}
  else{await expect(summary).toContainText('负频：未知 / unavailable');await expect(summary).not.toContainText('负频：0');}
  await expect(summary).toContainText('不代表人工科学验收或热力学验收');
 });
}

const thermalKeys=['zero_point_correction_hartree','thermal_correction_energy_hartree','thermal_correction_enthalpy_hartree','thermal_correction_gibbs_hartree','sum_electronic_zpe_hartree','sum_electronic_enthalpy_hartree','sum_electronic_gibbs_hartree'];
const log={portable_name:'gaussian.log',sha256:'a'.repeat(64),size_bytes:1000};
function thermalAttempt(){
 const value=Object.fromEntries(thermalKeys.map((k,i)=>[k,{value_hartree:i===0?0:-158+i/100,source_span:{artifact_kind:'gaussian-log',envelope_observation_id:'envelope',logical_name:'gaussian.log',sha256:log.sha256,size_bytes:1000,start:100+i*10,end:110+i*10}}]));
 return {source_id:'freq',project_id:'project',workflow_run_id:'run',task_id:'task',attempt_id:'freq-attempt',generation:fact('V31'),program:fact('gaussian'),bound_plan:fact({id:'plan'}),input:fact([]),artifacts:fact([]),axes:{execution:fact('completed')},facts:{energy:fact(-158,'hartree'),thermochemistry:{...fact(value,'hartree'),source:'Result:parsed'}},availability:'available',reason:null,record_inventory:[],history:[],provenance:{parsed_result:{parsed_result_id:'parsed',parser_version:'1.2.0',log}}};
}
for(const kind of ['attempt','attempts']){
 test(`thermal reported facts ${kind}`,async({page})=>{
  const item=thermalAttempt();
  const routePath=kind==='attempt'?'attempts/freq-attempt':'projects/project/attempts';
  await page.route(`**/api/v1/native/sources/freq/${routePath}`,route=>route.fulfill({json:{schema:'auto-g16-native-query/1',kind,data:kind==='attempt'?item:{items:[item]}}}));
  await page.goto(`/#/native/freq/${kind==='attempt'?'attempts/freq-attempt':'projects/project'}`);
  await page.getByLabel('只读访问令牌').fill(token);await page.getByRole('button',{name:'连接数据源'}).click();
  const card=page.locator('.native-thermochemistry');
  await expect(card.locator('tbody tr')).toHaveCount(7);
  await expect(card.getByRole('row',{name:'零点能校正 0 hartree',exact:true})).toBeVisible();
  await expect(card).toContainText('-157.94');
  await expect(card).toContainText('未作 qRRHO、集合布居或科学验收');
  await card.getByText('热化学来源与字节位置').click();
  await expect(card).toContainText('Result:parsed · 解析版本：1.2.0');
  await expect(card).toContainText(log.sha256);await expect(card).toContainText('"start": 100');
 });
}
for(const state of ['old-backend','missing','unavailable','partial','wrong-unit','wrong-result','wrong-parser','wrong-hash','bad-range','boolean','nonfinite','unknown-key','extra-span','bad-envelope','array','empty-available','missing-with-value']){
 test(`thermal state ${state}`,async({page})=>{
  const item=thermalAttempt();
  const f=item.facts.thermochemistry as Record<string,any>;
  const first=f.value[thermalKeys[0]];
  if(state==='old-backend')delete (item.facts as Record<string,unknown>).thermochemistry;
  if(state==='missing'||state==='unavailable')Object.assign(f,{availability:state,value:null,source:null,reason:state==='missing'?'thermochemistry-not-recorded':'thermochemistry-unavailable'});
  if(state==='partial')f.value={[thermalKeys[0]]:first};
  if(state==='wrong-unit')f.unit='kcal/mol';
  if(state==='wrong-result')f.source='Result:other';
  if(state==='wrong-parser')item.provenance.parsed_result.parser_version='old';
  if(state==='wrong-hash')first.source_span.sha256='b'.repeat(64);
  if(state==='bad-range')first.source_span.end=1001;
  if(state==='boolean')first.value_hartree=false;
  if(state==='nonfinite')first.value_hartree=Infinity;
  if(state==='unknown-key')f.value.unknown=first;
  if(state==='extra-span')first.source_span.private_path='/private/should-not-display';
  if(state==='bad-envelope')first.source_span.envelope_observation_id='different';
  if(state==='array')f.value=[];
  if(state==='empty-available')f.value={};
  if(state==='missing-with-value'){f.availability='missing';f.reason='thermochemistry-not-recorded';}
  await page.route('**/api/v1/native/sources/freq/attempts/freq-attempt',route=>route.fulfill({json:{schema:'auto-g16-native-query/1',kind:'attempt',data:item}}));
  await page.goto('/#/native/freq/attempts/freq-attempt');
  await page.getByLabel('只读访问令牌').fill(token);await page.getByRole('button',{name:'连接数据源'}).click();
  const card=page.locator('.native-thermochemistry');
  if(state==='old-backend')await expect(card).toContainText('热化学读取未连接（unavailable）');
  else if(state==='unavailable')await expect(card).toContainText('不可用 (unavailable)');
  else if(state==='missing'||state==='partial'){
   await expect(card.locator('tbody tr')).toHaveCount(7);
   await expect(card.locator('td').filter({hasText:'缺失 (missing)'})).toHaveCount(state==='partial'?6:7);
  }else{
   await expect(card.getByRole('alert')).toHaveText('invalid-thermochemistry-fact');
   await expect(card.locator('table')).toHaveCount(0);
  }
  await expect(page.locator('.native-fact').filter({hasText:'-158'})).toBeVisible();
  await expect(card).not.toContainText('/private/should-not-display');
 });
}
