import {test,expect} from '@playwright/test';
import type {Page} from '@playwright/test';
const token='browser-test-only-'+'0'.repeat(32);
const hash='a'.repeat(64);
const identity=(id:string)=>({id,payload_sha256:hash});
const fact=(value:unknown,unit:string|null=null)=>({availability:'available',value,unit,source:'synthetic-test',reason:null});
function attempt(attemptId='freq-a'){
 return {source_id:'saved',project_id:'project',workflow_run_id:'run',task_id:'task',attempt_id:attemptId,generation:fact('V31'),program:fact('gaussian'),bound_plan:fact({id:'plan'}),input:fact([]),artifacts:fact([]),axes:{execution:fact('completed')},facts:{energy:fact(-158,'hartree'),thermochemistry:{...fact({sum_electronic_gibbs_hartree:{value_hartree:-157.9987654321,source_span:{artifact_kind:'gaussian-log',envelope_observation_id:'envelope',logical_name:'gaussian.log',sha256:hash,size_bytes:1000,start:100,end:120}}},'hartree'),source:'Result:parsed'}},availability:'available',reason:null,record_inventory:[],history:[],provenance:{parsed_result:{parsed_result_id:'parsed',parser_version:'1.2.0',log:{portable_name:'gaussian.log',sha256:hash,size_bytes:1000}}}};
}
function saved(attemptId='freq-a'):any {
 return {schema:'auto-g16-native-thermodynamics-query/1',kind:'thermodynamics',data:{availability:'available',reason:null,source_id:'saved',attempt_id:attemptId,selected_member_id:attemptId==='freq-a'?'member-a':'member-b',result:{
  artifact_sha256:hash,source_ensemble:{...identity('source-ensemble'),revision:2},qualified_ensemble:{...identity('qualified-ensemble'),revision:3},thermodynamic_ensemble:identity('thermodynamic-ensemble'),sampling_profile:identity('sampling-profile'),request:identity('request'),
  parameters:{temperature_k:298.15,standard_state:'1M',entropy_method:'grimme',enthalpy_method:'head_gordon',entropy_frequency_cutoff_cm1:100,enthalpy_frequency_cutoff_cm1:100,frequency_scaling_factor:1,zpe_scaling_factor:0.99,moment_of_inertia:'global_grimme_bav',degeneracy_excludes_rotational_symmetry:true,functional_kernel_implementation_id:'implementation'},
  members:['a','b'].map((suffix,index)=>({member_id:`member-${suffix}`,is_selected:attemptId===`freq-${suffix}`,degeneracy:index+1,degeneracy_rationale:'explicit synthetic degeneracy',inclusion_status:'included_thermodynamic_eligible',raw_rrho:{electronic_energy_hartree:-158.12345678901234,zero_point_energy_hartree:0,enthalpy_hartree:-158.02,entropy_hartree_per_kelvin:0.000012345678901234,gibbs_free_energy_hartree:-158.03},treated_qrrho:{enthalpy_hartree:-158.04,entropy_hartree_per_kelvin:0.000023456789012345,gibbs_free_energy_hartree:-158.12345678901234+index/1000,entropy_treatment:'grimme',enthalpy_treatment:'head_gordon'},normalized_population:index===0?0.8765432109876543:0.1234567890123457,source:{optimization_attempt_id:`opt-${suffix}`,frequency_attempt_id:`freq-${suffix}`,optimization_parsed_result:{result_id:`parsed-opt-${suffix}`,payload_sha256:hash},frequency_parsed_result:{result_id:`parsed-freq-${suffix}`,payload_sha256:hash},optimization_result_source:{observation_id:`obs-opt-${suffix}`,payload_sha256:hash},frequency_result_source:{observation_id:`obs-freq-${suffix}`,payload_sha256:hash},two_stage_minimum_authority_id:`minimum-${suffix}`}})),
  ensemble_treated_free_energy_hartree:-158.123987654321,population_normalization:{population_sum:1,absolute_error:0,numeric_tolerance:1e-12,status:'normalized',tolerance_purpose:'floating_point_normalization_only_not_scientific_selection'},coverage_scope:{kind:'frozen_profile_nonexhaustive_scope',rationale:'Synthetic frozen two-member scope'},scientific_acceptance:'unavailable'
 }}};
}
async function setup(page:Page,body:unknown=saved(),status=200){
 const requests:string[]=[];
 await page.route('**/api/v1/native/**',async route=>{
  const path=new URL(route.request().url()).pathname;requests.push(path);
  if(path.endsWith('/thermodynamics'))return route.fulfill({status,json:body});
  if(path.includes('/projects/'))return route.fulfill({json:{schema:'auto-g16-native-query/1',kind:'attempts',data:{items:[attempt()]}}});
  return route.fulfill({json:{schema:'auto-g16-native-query/1',kind:'attempt',data:attempt(path.split('/').at(-1))}});
 });
 return requests;
}
async function connect(page:Page,path='/#/native/saved/attempts/freq-a'){
 await page.goto(path);await page.getByLabel('只读访问令牌').fill(token);await page.getByRole('button',{name:'连接数据源'}).click();
}
const card=(page:Page)=>page.getByRole('region',{name:'已保存的集合热化学结果'});

test('saved values preserve precision, units, canonical order and original report; one GET',async({page})=>{
 const requests=await setup(page);await connect(page);
 await expect(card(page).locator('article')).toHaveCount(2);
 await expect(card(page).locator('article h3')).toHaveText(['member-a · 当前成员','member-b']);
 for(const value of ['-158.12345678901235','0.8765432109876543','-158.123987654321','0.000012345678901234','Hartree/K','298.15 K','100 cm⁻¹','1M','grimme / head_gordon','global_grimme_bav','科学验收：unavailable','不表示穷尽采样或全局最低'])await expect(card(page)).toContainText(value);
 await expect(card(page).getByRole('row',{name:'零点能 0 不适用 Hartree',exact:true})).toHaveCount(2);
 await expect(page.locator('.native-thermochemistry')).toContainText('-157.9987654321');
 await expect(card(page).getByRole('button')).toHaveCount(0);await expect(card(page).locator('input,select')).toHaveCount(0);
 await card(page).getByText('集合与请求身份',{exact:true}).click();await expect(card(page)).toContainText(hash);
 expect(requests.filter(p=>p.endsWith('/thermodynamics'))).toHaveLength(1);
});

test('list does not request saved thermodynamics',async({page})=>{
 const requests=await setup(page);await connect(page,'/#/native/saved/projects/project');
 await expect(page.locator('.native-thermochemistry')).toContainText('-157.9987654321');
 await expect(card(page)).toHaveCount(0);expect(requests.some(p=>p.endsWith('/thermodynamics'))).toBe(false);
});

test('unregistered is distinct from errors and has no zero or empty table',async({page})=>{
 const body=saved();Object.assign(body.data,{availability:'unavailable',reason:'not-registered',selected_member_id:null,result:null});
 await setup(page,body);await connect(page);await expect(card(page)).toContainText('未登记（unavailable · not-registered）');
 await expect(card(page).locator('table')).toHaveCount(0);await expect(card(page).getByRole('alert')).toHaveCount(0);
});
for(const [status,code] of [[400,'invalid-id'],[404,'not-found'],[409,'invalid-evidence'],[503,'store-unavailable'],[500,'internal-error']] as const){
 test(`error ${status} keeps old detail and does not retry`,async({page})=>{
  const requests=await setup(page,{schema:'auto-g16-http-error/1',error:{code}},status);await connect(page);
  await expect(card(page).getByRole('alert')).toContainText(code);await expect(card(page).locator('table')).toHaveCount(0);
  await expect(page.locator('.native-thermochemistry')).toContainText('-157.9987654321');
  expect(requests.filter(p=>p.endsWith('/thermodynamics'))).toHaveLength(1);
 });
}
const invalidCases:Record<string,(v:any)=>void>={
 'extra envelope':v=>v.private_path='/must-not-display',
 'missing result':v=>delete v.data.result,
 'wrong schema':v=>v.schema='auto-g16-native-query/1',
 'wrong kind':v=>v.kind='attempt',
 'wrong source':v=>v.data.source_id='other',
 'wrong attempt':v=>v.data.attempt_id='freq-b',
 'wrong member':v=>v.data.selected_member_id='member-b',
 'wrong selected attempt':v=>v.data.result.members[0].source.frequency_attempt_id='other',
 'duplicate member':v=>v.data.result.members[1].member_id='member-a',
 'duplicate frequency attempt':v=>v.data.result.members[1].source.frequency_attempt_id='freq-a',
 'multiple selected':v=>v.data.result.members[1].is_selected=true,
 'numeric selected':v=>v.data.result.members[0].is_selected=1,
 'empty members':v=>v.data.result.members=[],
 'invalid id':v=>v.data.result.request.id='../private',
 'uppercase digest':v=>v.data.result.artifact_sha256='A'.repeat(64),
 'extra identity':v=>v.data.result.source_ensemble.path='/must-not-display',
 'missing nested identity':v=>delete v.data.result.members[0].source.frequency_parsed_result.payload_sha256,
 'invented authority digest':v=>v.data.result.members[0].source.two_stage_minimum_authority_sha256=hash,
 'private source':v=>v.data.result.members[0].source.transport_root='/must-not-display',
 'boolean revision':v=>v.data.result.source_ensemble.revision=true,
 'fractional degeneracy':v=>v.data.result.members[0].degeneracy=1.1,
 'zero degeneracy':v=>v.data.result.members[0].degeneracy=0,
 'empty rationale':v=>v.data.result.members[0].degeneracy_rationale='',
 'boolean number':v=>v.data.result.members[0].raw_rrho.enthalpy_hartree=false,
 'nonfinite number':v=>v.data.result.members[0].treated_qrrho.gibbs_free_energy_hartree=Infinity,
 'extra raw':v=>v.data.result.members[0].raw_rrho.relative_energy=1,
 'missing treated':v=>delete v.data.result.members[0].treated_qrrho.entropy_hartree_per_kelvin,
 'population outside range':v=>v.data.result.members[0].normalized_population=1.1,
 'invalid temperature':v=>v.data.result.parameters.temperature_k=0,
 'boolean cutoff':v=>v.data.result.parameters.entropy_frequency_cutoff_cm1=true,
 'wrong standard state':v=>v.data.result.parameters.standard_state='1bar',
 'wrong method':v=>v.data.result.parameters.enthalpy_method='rrho',
 'wrong inertia':v=>v.data.result.parameters.moment_of_inertia='new-default',
 'symmetry included':v=>v.data.result.parameters.degeneracy_excludes_rotational_symmetry=false,
 'missing parameter':v=>delete v.data.result.parameters.zpe_scaling_factor,
 'extra parameter':v=>v.data.result.parameters.default=true,
 'wrong treatment':v=>v.data.result.members[0].treated_qrrho.entropy_treatment='rrho',
 'wrong inclusion':v=>v.data.result.members[0].inclusion_status='excluded',
 'bad normalization':v=>v.data.result.population_normalization.absolute_error=-1,
 'wrong tolerance':v=>v.data.result.population_normalization.numeric_tolerance=0.1,
 'extra normalization':v=>v.data.result.population_normalization.private_path='/must-not-display',
 'wrong scope':v=>v.data.result.coverage_scope.kind='exhaustive',
 'claimed acceptance':v=>v.data.result.scientific_acceptance='accepted',
 'unavailable with values':v=>{v.data.availability='unavailable';v.data.reason='not-registered';},
};
for(const [name,mutate] of Object.entries(invalidCases))test(`reject ${name}`,async({page})=>{
 const value=saved();mutate(value);await setup(page,value);await connect(page);
 await expect(card(page).getByRole('alert')).toContainText('contract-mismatch');await expect(card(page).locator('table')).toHaveCount(0);
 await expect(card(page)).not.toContainText('/must-not-display');await expect(page.locator('.native-thermochemistry')).toContainText('-157.9987654321');
});

test('awaits old detail; abandons old thermodynamics on navigation',async({page})=>{
 let releaseDetail!:()=>void, releaseThermo!:()=>void;
 const detailGate=new Promise<void>(r=>releaseDetail=r),thermoGate=new Promise<void>(r=>releaseThermo=r);
 const requests:string[]=[];
 await page.route('**/api/v1/native/**',async route=>{
  const p=new URL(route.request().url()).pathname;requests.push(p);
  const thermo=p.endsWith('/thermodynamics'),id=p.includes('freq-b')?'freq-b':'freq-a';
  if(id==='freq-a')await (thermo?thermoGate:detailGate);
  await route.fulfill({json:thermo?saved(id):{schema:'auto-g16-native-query/1',kind:'attempt',data:attempt(id)}});
 });
 await connect(page);await expect(page.getByRole('status',{name:''})).toContainText('正在读取');
 expect(requests.some(p=>p.endsWith('/thermodynamics'))).toBe(false);releaseDetail();
 await expect(card(page).getByRole('status')).toContainText('正在读取已保存');
 await page.evaluate(()=>{location.hash='#/native/saved/attempts/freq-b'});
 await expect(card(page)).toContainText('当前成员：member-b');releaseThermo();
 await expect(card(page)).toContainText('当前成员：member-b');
 expect(requests.filter(p=>p.endsWith('/thermodynamics'))).toHaveLength(2);
});

test('deadline is 120 seconds and failure never retries',async({page})=>{
 await page.clock.install();let release!:()=>void;const gate=new Promise<void>(r=>release=r);
 const requests=await setup(page);
 await page.route('**/thermodynamics',async route=>{requests.push(new URL(route.request().url()).pathname);await gate;await route.fulfill({json:saved()}).catch(()=>{});});
 await connect(page);await expect(card(page).getByRole('status')).toBeVisible();
 await page.clock.fastForward(119000);await expect(card(page).getByRole('status')).toBeVisible();
 await page.clock.fastForward(1001);await expect(card(page).getByRole('alert')).toContainText('读取超时（120 秒）');
 expect(requests.filter(p=>p.endsWith('/thermodynamics'))).toHaveLength(1);release();
});

test('narrow screen wraps full identities without page overflow',async({page})=>{
 await page.setViewportSize({width:375,height:812});await setup(page);await connect(page);await expect(card(page).locator('article')).toHaveCount(2);
 await card(page).getByText('集合与请求身份',{exact:true}).click();await card(page).getByText('成员来源身份',{exact:true}).first().click();
 await page.screenshot({path:process.env.AUTOG_THERMO_SCREENSHOT??'test-results/native-thermodynamics-mobile.png',fullPage:true});
 expect(await page.evaluate(()=>Array.from(document.querySelectorAll('main *')).filter(e=>e.getBoundingClientRect().right>innerWidth).map(e=>({tag:e.tagName,class:e.className,width:e.getBoundingClientRect().width,right:e.getBoundingClientRect().right})))).toEqual([]);
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});

test('changed token abandons an old response and sends one new read',async({page})=>{
 let release!:()=>void;const gate=new Promise<void>(r=>release=r),headers:string[]=[];
 await setup(page);
 await page.route('**/thermodynamics',async route=>{
  const authorization=route.request().headers().authorization;headers.push(authorization);
  if(headers.length===1){await gate;const old=saved();old.data.result.coverage_scope.rationale='OBSOLETE TOKEN RESPONSE';await route.fulfill({json:old});}
  else await route.fulfill({json:saved()});
 });
 await connect(page);await expect(card(page).getByRole('status')).toBeVisible();
 await page.getByRole('button',{name:'断开',exact:true}).click();await expect(card(page)).toHaveCount(0);
 const nextToken='different-token-'+'1'.repeat(32);
 await page.getByLabel('只读访问令牌').fill(nextToken);await page.getByRole('button',{name:'连接数据源'}).click();
 await expect(card(page)).toContainText('Synthetic frozen two-member scope');
 const oldResponse=page.waitForResponse(r=>r.url().endsWith('/thermodynamics'));
 release();await oldResponse;await expect(card(page)).not.toContainText('OBSOLETE TOKEN RESPONSE');
 expect(headers).toEqual([`Bearer ${token}`,`Bearer ${nextToken}`]);
});

test('abandoned reads retain the two-request page budget until drained',async({page})=>{
 let releaseA!:()=>void,releaseB!:()=>void;
 const gateA=new Promise<void>(r=>releaseA=r),gateB=new Promise<void>(r=>releaseB=r);
 const requests:string[]=[];let active=0,maxActive=0;
 await page.route('**/api/v1/native/**',async route=>{
  const path=new URL(route.request().url()).pathname;requests.push(path);active++;maxActive=Math.max(maxActive,active);
  const thermo=path.endsWith('/thermodynamics'),id=path.includes('freq-b')?'freq-b':'freq-a';
  if(thermo)await(id==='freq-a'?gateA:gateB);
  active--;await route.fulfill({json:thermo?saved(id):path.includes('/projects/')?{schema:'auto-g16-native-query/1',kind:'attempts',data:{items:[attempt()]}}:{schema:'auto-g16-native-query/1',kind:'attempt',data:attempt(id)}});
 });
 await connect(page);await expect(card(page).getByRole('status')).toBeVisible();
 await page.evaluate(()=>{location.hash='#/native/saved/attempts/freq-b'});await expect(card(page).getByRole('status')).toBeVisible();
 await expect.poll(()=>requests.filter(p=>p.endsWith('/thermodynamics')).length).toBe(2);
 await page.evaluate(()=>{location.hash='#/native/saved/projects/project'});await expect(card(page)).toHaveCount(0);
 expect(requests.some(p=>p.includes('/projects/'))).toBe(false);
 releaseA();await expect(page.locator('.native-thermochemistry')).toContainText('-157.9987654321');
 releaseB();expect(maxActive).toBe(2);
});
