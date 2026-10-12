import {test,expect} from '@playwright/test';
import type {Page} from '@playwright/test';
import {inferDisplayBonds,measure,rotate,cameraBasis} from '../src/molecule-math';
const atom=(center:number,atomic_number:number,x:number,y:number,z:number)=>({center,atomic_number,x,y,z});
const water=[atom(1,8,0,0,0),atom(2,1,1,0,0),atom(3,1,0,1,0)];
const geometry={units:'angstrom',orientation_kind:'standard-orientation',atoms:water,source_span:{start:10,end:20}};
test('display connectivity gives water two bonds, methane four and leaves fragments separate',()=>{
  const original=structuredClone(water);expect(inferDisplayBonds(water).bonds.map(b=>[b.a,b.b])).toEqual([[1,2],[1,3]]);expect(water).toEqual(original);
  const methane=[atom(1,6,0,0,0),atom(2,1,.63,.63,.63),atom(3,1,.63,-.63,-.63),atom(4,1,-.63,.63,-.63),atom(5,1,-.63,-.63,.63)];expect(inferDisplayBonds(methane).bonds).toHaveLength(4);
  expect(inferDisplayBonds([atom(1,6,0,0,0),atom(2,6,1.54,0,0),atom(3,6,10,0,0),atom(4,6,11.54,0,0)]).bonds.map(b=>[b.a,b.b])).toEqual([[1,2],[3,4]]);
});
test('unknown elements, coincident coordinates and excessive inferred graphs are withheld',()=>{
  const unsupported=inferDisplayBonds([atom(1,118,0,0,0),atom(2,6,1,0,0)]);expect(unsupported.bonds).toEqual([]);expect(unsupported.unsupported).toEqual([118]);
  const close=inferDisplayBonds([atom(1,6,0,0,0),atom(2,6,.01,0,0)]);expect(close.bonds).toEqual([]);expect(close.closePairs).toBe(1);
  const crowded=Array.from({length:150},(_,i)=>atom(i+1,6,Math.cos(i*2*Math.PI/150),Math.sin(i*2*Math.PI/150),0));const large=inferDisplayBonds(crowded);expect(large.overflow).toBe(true);expect(large.bonds).toEqual([]);
});
test('measurements use original coordinates, signed dihedral and reject degenerate angles',()=>{
  expect(measure([water[1],water[2]],'distance')).toBeCloseTo(Math.sqrt(2),12);expect(measure([water[1],water[0],water[2]],'angle')).toBeCloseTo(90,12);
  const torsion=[atom(1,6,1,0,0),atom(2,6,0,0,0),atom(3,6,0,1,0),atom(4,6,0,1,1)];expect(measure(torsion,'torsion')).toBeCloseTo(-90,12);expect(measure([...torsion.slice(0,3),atom(4,6,0,1,-1)],'torsion')).toBeCloseTo(90,12);
  expect(measure([water[0],water[0],water[1]],'angle')).toBeNull();expect(measure([atom(1,6,0,0,0),atom(2,6,1,0,0),atom(3,6,2,0,0),atom(4,6,3,0,0)],'torsion')).toBeNull();
  const rotated=water.map(a=>({...a,...rotate(a.x,a.y,a.z,[.78,1.34])}));expect(measure([rotated[1],rotated[2]],'distance')).toBeCloseTo(Math.sqrt(2),12);
});
async function connect(page:Page){
  await page.route('**/api/attempts/gaussian-normal/details',async route=>{const r=await route.fetch(),d=await r.json();d.result.data.last_geometry=geometry;await route.fulfill({json:d});});
  await page.goto('/#/attempts/gaussian-normal');await page.getByLabel('只读访问令牌').fill('browser-test-only-'+'0'.repeat(32));await page.getByRole('button',{name:'连接数据源'}).click();await page.getByRole('button',{name:'结构与结果',exact:true}).click();await expect(page.getByTestId('molecule-atom')).toHaveCount(3);await page.locator('.structure-tools > summary').click();
}
test('ball-and-stick is default, display modes and hydrogen visibility preserve source coordinates',async({page})=>{
  const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')errors.push(m.text());});
  await connect(page);await expect(page.getByLabel('原子标签',{exact:true})).toHaveValue('none');await expect(page.locator('.atom-label')).toHaveCount(0);await expect(page.getByLabel('分子显示方式')).toHaveValue('ball-stick');await expect(page.getByTestId('molecule-bond')).toHaveCount(2);await expect(page.getByTestId('bond-count')).toHaveText('2 条推测连接');
  for(const mode of ['tube','wire','ball-stick']){await page.getByLabel('分子显示方式').selectOption(mode);await expect(page.getByTestId('molecule-bond')).toHaveCount(2);await expect(page.getByTestId('molecule-atom')).toHaveCount(3);}
  await page.getByLabel('显示氢原子',{exact:true}).uncheck();await expect(page.getByTestId('molecule-atom')).toHaveCount(1);await expect(page.getByTestId('molecule-bond')).toHaveCount(0);await page.getByLabel('显示氢原子',{exact:true}).check();
  await page.getByLabel('显示推测连接',{exact:true}).uncheck();await expect(page.getByTestId('molecule-bond')).toHaveCount(0);await page.getByLabel('显示推测连接',{exact:true}).check();await expect(page.getByTestId('molecule-bond')).toHaveCount(2);
  await page.getByLabel('原子标签',{exact:true}).selectOption('none');await expect(page.locator('.atom-label')).toHaveCount(0);await page.getByLabel('原子标签',{exact:true}).selectOption('both');await expect(page.locator('.atom-label')).toHaveCount(3);expect(errors).toEqual([]);
});
test('angle measurements, pan, wheel zoom and preset views do not modify distance or angles',async({page})=>{
  await connect(page);await page.getByLabel('测量方式').selectOption('angle');for(const [label,id] of [['A','2'],['B','1'],['C','3']])await page.getByLabel('测距原子 '+label).selectOption(id);await expect(page.getByTestId('atom-distance')).toHaveText('90.00 °');
  await page.getByLabel('预设视角').selectOption('top');await expect(page.getByTestId('atom-distance')).toHaveText('90.00 °');await page.getByTestId('molecule-scene').scrollIntoViewIfNeeded();const a=page.locator('[data-testid="molecule-atom"][data-center="1"]'),before=await a.getAttribute('transform');
  await page.getByTestId('molecule-scene').focus();await page.keyboard.press('Shift+ArrowRight');await expect(a).not.toHaveAttribute('transform',before!);
  const circle=page.locator('[data-testid="molecule-atom"][data-center="1"] circle'),radius=Number(await circle.getAttribute('r'));await page.getByTestId('molecule-scene').hover();await page.keyboard.down('Alt');await page.mouse.wheel(0,-100);await page.keyboard.up('Alt');await expect.poll(async()=>Number(await circle.getAttribute('r'))).toBeGreaterThan(radius);await expect(page.getByTestId('atom-distance')).toHaveText('90.00 °');
  await page.getByRole('button',{name:'重置视角'}).click();await expect(page.getByTestId('atom-distance')).toHaveText('选择 3 个原子');
});
test('mobile bonded viewer, expanded layout and controls stay within viewport',async({page})=>{
  await page.setViewportSize({width:390,height:844});await connect(page);await page.getByRole('button',{name:'放大查看区'}).click();await expect(page.getByTestId('molecule-bond')).toHaveCount(2);await page.getByText('显示尺寸与元素配色',{exact:true}).click();expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);await page.getByRole('button',{name:'断开',exact:true}).click();await expect(page.getByTestId('molecule-bond')).toHaveCount(0);
});

test('initial camera preserves distances and handedness while exposing the main molecular plane',()=>{
 const basis=cameraBasis(water);const dot=(a:number[],b:number[])=>a.reduce((s,x,i)=>s+x*b[i],0);
 for(let i=0;i<3;i++)for(let j=0;j<3;j++)expect(dot(basis[i],basis[j])).toBeCloseTo(i===j?1:0,10);
 const [a,b,c]=basis;const cross=[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]];expect(dot(cross,c)).toBeCloseTo(1,10);
 const aligned=water.map(a=>{const p=basis.map(row=>dot(row,[a.x,a.y,a.z]));return {...a,x:p[0],y:p[1],z:p[2]};});expect(measure([aligned[1],aligned[2]],'distance')).toBeCloseTo(Math.sqrt(2),10);expect(Math.abs(aligned[0].z-aligned[1].z)).toBeLessThan(1e-10);
});

test('compact model sits left of tools and ordinary wheel scrolls without changing the structure',async({page})=>{
 await connect(page);const scene=page.getByTestId('molecule-scene');await scene.hover();
 const model=(await scene.boundingBox())!,tools=(await page.getByRole('group',{name:'结构显示与测量工具'}).boundingBox())!;
 expect(model.width).toBeLessThanOrEqual(520);expect(model.x+model.width).toBeLessThan(tools.x);
 const atoms=page.getByTestId('molecule-atom'),before=await atoms.evaluateAll(es=>es.map(e=>e.getAttribute('transform'))),scroll=await page.evaluate(()=>scrollY);
 await page.mouse.wheel(0,220);await expect.poll(()=>page.evaluate(()=>scrollY)).toBeGreaterThan(scroll+50);
 expect(await atoms.evaluateAll(es=>es.map(e=>e.getAttribute('transform')))).toEqual(before);
 await expect(page.getByTestId('atom-distance')).toHaveText('选择两个原子');
 await scene.hover();const circle=atoms.first().locator('circle'),radius=Number(await circle.getAttribute('r'));
 await page.keyboard.down('Alt');await page.mouse.wheel(0,-100);await page.keyboard.up('Alt');
 await expect.poll(async()=>Number(await circle.getAttribute('r'))).toBeGreaterThan(radius);
});

test('touch swipes scroll by default and rotate only after explicitly enabling structure interaction',async({browser})=>{
 const context=await browser.newContext({baseURL:'http://127.0.0.1:18765',viewport:{width:390,height:844},hasTouch:true,isMobile:true});
 try {
  const page=await context.newPage();await connect(page);const scene=page.getByTestId('molecule-scene'),atoms=page.getByTestId('molecule-atom');
  const cdp=await context.newCDPSession(page);
  const swipe=async()=>{await scene.scrollIntoViewIfNeeded();const b=(await scene.boundingBox())!,x=b.x+b.width*.5,y=b.y+b.height*.75;
   await cdp.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x,y}]});
   for(let i=1;i<=6;i++)await cdp.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x:x+i*5,y:y-i*14}]});
   await cdp.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});
  };
  await scene.scrollIntoViewIfNeeded();const before=await atoms.evaluateAll(es=>es.map(e=>e.getAttribute('transform'))),scroll=await page.evaluate(()=>scrollY);
  await swipe();await expect.poll(()=>page.evaluate(()=>scrollY)).toBeGreaterThan(scroll+20);
  expect(await atoms.evaluateAll(es=>es.map(e=>e.getAttribute('transform')))).toEqual(before);
  await expect(page.getByTestId('atom-distance')).toHaveText('选择两个原子');
  await page.getByRole('checkbox',{name:'启用触屏操作结构'}).check();await scene.scrollIntoViewIfNeeded();
  const enabledScroll=await page.evaluate(()=>scrollY);await swipe();
  await expect.poll(()=>atoms.evaluateAll(es=>es.map(e=>e.getAttribute('transform')))).not.toEqual(before);
  expect(await page.evaluate(()=>scrollY)).toBe(enabledScroll);
  await page.getByRole('checkbox',{name:'启用触屏操作结构'}).uncheck();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 } finally {await context.close();}
});
