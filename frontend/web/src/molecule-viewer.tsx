import { useEffect, useId, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import type { VibrationMode } from './vibration-contract';
import { inferDisplayBonds, measure, rotate, cameraBasis } from './molecule-math';
export type Atom={center:number;atomic_number:number;x:number;y:number;z:number};
export type Geometry={atoms:Atom[];units?:string;source_span?:unknown;orientation_kind?:string};
const symbols='? H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au Hg Tl Pb Bi Po At Rn Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf Es Fm Md No Lr Rf Db Sg Bh Hs Mt Ds Rg Cn Nh Fl Mc Lv Ts Og'.split(' ');
const colors:Record<number,string>={1:'#f0f2f7',6:'#58616b',7:'#315fe0',8:'#e04445',9:'#48a986',15:'#dc9440',16:'#c6a22a',17:'#389b68',35:'#a35439',53:'#8553ac'};
export function isGeometry(v:unknown):v is Geometry {
  if(!v||typeof v!=='object'||!('units'in v)||v.units!=='angstrom'||!('atoms'in v)||!Array.isArray(v.atoms)||!v.atoms.length)return false;
  return v.atoms.every(a=>a&&typeof a==='object'&&Number.isSafeInteger(a.center)&&a.center>0&&Number.isSafeInteger(a.atomic_number)&&a.atomic_number>=1&&a.atomic_number<=118&&['x','y','z'].every(k=>typeof a[k]==='number'&&Number.isFinite(a[k])&&Math.abs(a[k])<1e8))&&new Set(v.atoms.map(a=>a.center)).size===v.atoms.length;
}
type Display='ball-stick'|'tube'|'wire';
type Measurement='distance'|'angle'|'torsion';
function CoordinateScene({geometry,vibration,onClearVibration,modePanel}:{geometry:Geometry;vibration?:VibrationMode;onClearVibration?:()=>void;modePanel?:ReactNode}) {
  const [playing,setPlaying]=useState(false),[phase,setPhase]=useState(0),[amplitude,setAmplitude]=useState(.45),[speed,setSpeed]=useState(.6);
  const clock=useRef(0);
  useEffect(()=>{clock.current=0;setPhase(0);setPlaying(Boolean(vibration));},[vibration]);
  useEffect(()=>{if(!playing||!vibration)return;let frame=0,last=0;const tick=(time:number)=>{if(last){clock.current+=Math.min(.08,(time-last)/1000)*speed;setPhase(Math.sin(clock.current*2*Math.PI));}last=time;frame=requestAnimationFrame(tick);};frame=requestAnimationFrame(tick);const hide=()=>{if(document.hidden)setPlaying(false);};document.addEventListener('visibilitychange',hide);return()=>{cancelAnimationFrame(frame);document.removeEventListener('visibilitychange',hide);};},[playing,vibration,speed]);
  const displacement=useMemo(()=>new Map(vibration?.displacements.map(v=>[v.center,v])??[]),[vibration]);
  const uid=useId().replace(/:/g,'');
  const [angles,setAngles]=useState([-.25,.35]),[zoom,setZoom]=useState(1),[pan,setPan]=useState([0,0]);
  const [display,setDisplay]=useState<Display>('ball-stick'),[labels,setLabels]=useState('none'),[hydrogen,setHydrogen]=useState(true),[showBonds,setShowBonds]=useState(true),[large,setLarge]=useState(false);
  const [aligned,setAligned]=useState(true),[touchEnabled,setTouchEnabled]=useState(false);
  const [interaction,setInteraction]=useState('rotate'),[mode,setMode]=useState<Measurement>('distance'),[selected,setSelected]=useState<(number|null)[]>([null,null]);
  const [atomSize,setAtomSize]=useState(1),[bondSize,setBondSize]=useState(1);
  const svg=useRef<SVGSVGElement>(null),drag=useRef<{id:number;x:number;y:number;moved:boolean;pan:boolean}|null>(null);
  const changeZoom=(factor:number)=>setZoom(z=>Math.max(.3,Math.min(4,z*factor)));
  useEffect(()=>{const el=svg.current;if(!el)return;const wheel=(e:WheelEvent)=>{if(!e.altKey||e.ctrlKey||e.metaKey)return;e.preventDefault();changeZoom(Math.exp(-Math.max(-100,Math.min(100,e.deltaY))*.003));};el.addEventListener('wheel',wheel,{passive:false});return()=>el.removeEventListener('wheel',wheel);},[]);
  const normalized=useMemo(()=>{const atoms=geometry.atoms;const c=atoms.reduce((v,a)=>[v[0]+a.x/atoms.length,v[1]+a.y/atoms.length,v[2]+a.z/atoms.length],[0,0,0]);const points=atoms.map(a=>({...a,x:a.x-c[0],y:a.y-c[1],z:a.z-c[2]}));return {points,radius:Math.max(1,...points.map(a=>Math.hypot(a.x,a.y,a.z)))};},[geometry]);
  const basis=useMemo(()=>cameraBasis(geometry.atoms),[geometry]);
  const orient=(x:number,y:number,z:number)=>{const p=aligned?basis.map(row=>row[0]*x+row[1]*y+row[2]*z):[x,y,z];return rotate(p[0],p[1],p[2],angles);};
  const connectivity=useMemo(()=>inferDisplayBonds(geometry.atoms),[geometry]);
  const originals=useMemo(()=>new Map(geometry.atoms.map(a=>[a.center,a])),[geometry]);
  const visible=geometry.atoms.filter(a=>hydrogen||a.atomic_number!==1);
  const scale=136/normalized.radius*zoom;
  const projected=normalized.points.filter(a=>hydrogen||a.atomic_number!==1).map(a=>{const d=displacement.get(a.center),factor=vibration?phase*amplitude:0;const p=orient(a.x+(d?.dx??0)*factor,a.y+(d?.dy??0)*factor,a.z+(d?.dz??0)*factor);return {...a,px:300+pan[0]+p.x*scale,py:185+pan[1]-p.y*scale,depth:p.z};});
  const positions=new Map(projected.map(a=>[a.center,a]));
  const bonds=connectivity.bonds.filter(b=>positions.has(b.a)&&positions.has(b.b));
  const width=display==='wire'?1.8:Math.max(2,.115*scale*bondSize);
  const radius=(n:number)=>display==='wire'?3:display==='tube'?width*.6:Math.max(4,(n===1?.155:.24)*scale*atomSize);
  const picked=selected.filter((x):x is number=>x!==null).map(c=>originals.get(c)!);
  const value=selected.every(x=>x!==null)?measure(picked,mode):null;
  const formatted=value===null?(selected.every(x=>x!==null)?'几何退化，无法定义':selected.length===2?'选择两个原子':`选择 ${selected.length} 个原子`):`${value.toFixed(mode==='distance'?4:2)} ${mode==='distance'?'Å':'°'}`;
  const pick=(center:number)=>setSelected(s=>s.includes(center)?s.map(x=>x===center?null:x):s.includes(null)?s.map((x,i)=>i===s.indexOf(null)?center:x):[...s.slice(1),center]);
  function setMeasurement(next:Measurement){setMode(next);setSelected(Array(next==='distance'?2:next==='angle'?3:4).fill(null));}
  const reset=()=>{setAngles([-.25,.35]);setAligned(true);setZoom(1);setPan([0,0]);setSelected(s=>s.map(()=>null));};
  // Short tube segments and atoms share a depth order, so foreground connections
  // are not always hidden behind every atom. No inferred bond order is rendered.
  const primitives:{depth:number;key:string;node:ReactNode}[]=[];
  if(showBonds)for(const bond of bonds){const a=positions.get(bond.a)!,b=positions.get(bond.b)!;const steps=bonds.length>400?4:12;const length=Math.hypot(b.px-a.px,b.py-a.py);const start=length>0?Math.min(.49,radius(a.atomic_number)*.92/length):.49,end=length>0?Math.max(.51,1-radius(b.atomic_number)*.92/length):.51;for(let i=0;i<steps;i++){
    const t=start+(end-start)*Math.max(0,(i-.08)/steps),u=start+(end-start)*Math.min(1,(i+1.08)/steps);const color=colors[((t+u)/2<.5?a:b).atomic_number]??'#976abc';const highlight='#'+[1,3,5].map(k=>Math.round(parseInt(color.slice(k,k+2),16)*.75+255*.25).toString(16).padStart(2,'0')).join('');
    const coords={x1:a.px+(b.px-a.px)*t,y1:a.py+(b.py-a.py)*t,x2:a.px+(b.px-a.px)*u,y2:a.py+(b.py-a.py)*u};
    primitives.push({depth:a.depth+(b.depth-a.depth)*(t+u)/2,key:`bond-${a.center}-${b.center}-${i}`,node:<g data-testid={i===0?'molecule-bond':undefined} data-pair={`${a.center}-${b.center}`} className="display-bond"><line {...coords} stroke={color} strokeWidth={width} strokeLinecap="butt"/>{display!=='wire'&&<line {...coords} stroke={highlight} strokeWidth={width*.25} strokeLinecap="butt"/>}<title>距离推测连接 · {a.center}–{b.center} · {bond.distance.toFixed(4)} Å（无键级）</title></g>});
  }}
  for(const a of projected){const original=originals.get(a.center)!;primitives.push({depth:a.depth,key:`atom-${a.center}`,node:<g data-testid="molecule-atom" data-center={a.center} transform={`translate(${a.px} ${a.py})`}><circle r={radius(a.atomic_number)} fill={display==='wire'?(colors[a.atomic_number]??'#976abc'):`url(#${uid}-atom-${a.atomic_number})`} stroke={selected.includes(a.center)?'#862e91':'#4e465e'} strokeOpacity={selected.includes(a.center)?1:.26} strokeWidth={selected.includes(a.center)?3:1}/><title>{symbols[a.atomic_number]} · {a.center}: {original.x}, {original.y}, {original.z} Å</title></g>});}
  primitives.sort((a,b)=>a.depth-b.depth||a.key.localeCompare(b.key));
  const overlayPoints=selected.map(c=>c===null?null:positions.get(c));
  return <div className={`molecule-viewer ${large?'expanded-view':''}`}>
    <div className="molecule-viewport"><div className="molecule-stage"><svg className={touchEnabled?'touch-interaction':undefined} ref={svg} viewBox="0 0 600 370" role="img" aria-label="可旋转三维原子坐标，方向键旋转，加减键缩放" tabIndex={0} data-testid="molecule-scene"
      onKeyDown={e=>{if(!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','+','-','Home'].includes(e.key))return;e.preventDefault();if(e.key==='Home')reset();else if(e.key==='+')changeZoom(1.2);else if(e.key==='-')changeZoom(1/1.2);else if(e.shiftKey)setPan(([x,y])=>[x+(e.key==='ArrowLeft'?-10:e.key==='ArrowRight'?10:0),y+(e.key==='ArrowUp'?-10:e.key==='ArrowDown'?10:0)]);else setAngles(([x,y])=>[x+(e.key==='ArrowUp'?.15:e.key==='ArrowDown'?-.15:0),y+(e.key==='ArrowLeft'?-.15:e.key==='ArrowRight'?.15:0)]);}}
      onPointerDown={e=>{if(!e.isPrimary||drag.current||(e.pointerType==='touch'&&!touchEnabled)||(e.button!==0&&e.button!==1))return;e.preventDefault();e.currentTarget.focus();drag.current={id:e.pointerId,x:e.clientX,y:e.clientY,moved:false,pan:interaction==='pan'||e.shiftKey||e.button===1};e.currentTarget.setPointerCapture(e.pointerId);}}
      onPointerMove={e=>{const d=drag.current;if(!d||d.id!==e.pointerId)return;const dx=e.clientX-d.x,dy=e.clientY-d.y;if(Math.abs(dx)+Math.abs(dy)>2)d.moved=true;if(d.moved){if(d.pan){const rect=e.currentTarget.getBoundingClientRect();setPan(([x,y])=>[x+dx*600/rect.width,y+dy*370/rect.height]);}else setAngles(([x,y])=>[x+dy*.012,y+dx*.012]);d.x=e.clientX;d.y=e.clientY;}}}
      onPointerUp={e=>{const d=drag.current;if(!d||d.id!==e.pointerId)return;if(!d.moved){const rect=e.currentTarget.getBoundingClientRect();const x=(e.clientX-rect.left)/rect.width*600,y=(e.clientY-rect.top)/rect.height*370;const atom=[...projected].sort((a,b)=>b.depth-a.depth).find(a=>Math.hypot(a.px-x,a.py-y)<Math.max(radius(a.atomic_number),12*600/rect.width));if(atom)pick(atom.center);}drag.current=null;}}
      onPointerCancel={()=>{drag.current=null;}} onLostPointerCapture={()=>{drag.current=null;}}>
      <defs>{[...new Set(visible.map(a=>a.atomic_number))].map(n=><radialGradient id={`${uid}-atom-${n}`} key={n} cx="29%" cy="23%" r="78%"><stop offset="0" stopColor="#fff"/><stop offset=".25" stopColor={colors[n]??'#976abc'}/><stop offset=".68" stopColor={colors[n]??'#976abc'}/><stop offset="1" stopColor={n===1?'#9b9fae':'#202537'}/></radialGradient>)}</defs>
      {primitives.map(p=><g key={p.key}>{p.node}</g>)}
      {overlayPoints.slice(1).map((p,i)=>{const prev=overlayPoints[i];return p&&prev?<line key={i} x1={prev.px} y1={prev.py} x2={p.px} y2={p.py} stroke="#9637a7" strokeWidth="2" strokeDasharray="4 4" className="measurement-overlay"/>:null;})}
      {projected.map(a=>labels!=='none'?<text key={a.center} x={a.px} y={a.py+radius(a.atomic_number)+15} textAnchor="middle" className="atom-label">{labels==='number'?'':symbols[a.atomic_number]}{labels==='element'?'':a.center}</text>:null)}
      {[['X',1,0,0,'#c34458'],['Y',0,1,0,'#3d9354'],['Z',0,0,1,'#4675d9']].map(([label,x,y,z,color])=>{const p=orient(Number(x),Number(y),Number(z));return <g key={String(label)}><line x1="43" y1="326" x2={43+p.x*27} y2={326-p.y*27} stroke={String(color)} strokeWidth="2"/><text x={43+p.x*38} y={329-p.y*38} fill={String(color)} className="model-axis">{label}</text></g>;})}
      {visible.length===0&&<text x="300" y="185" textAnchor="middle" className="atom-label">请显示氢原子以查看此结构</text>}
    </svg><div className="scene-caption"><span>{visible.length} / {geometry.atoms.length} 原子</span><span data-testid="bond-count">{showBonds?bonds.length:0} 条推测连接</span><span>Å · 正交视图</span></div></div>
    <p className="model-hint">拖动旋转 · Shift 平移 · Alt / Option + 滚轮缩放<br/>连接为距离推测，不代表键级或科学验收。</p><details className="interaction-help"><summary>鼠标与触屏操作说明</summary><p>普通滚轮和触屏默认滑动页面。可使用工具按钮、方向键与 + / −；启用触屏操作后可拖动及点选原子。</p></details></div>
    <div className="molecule-tools" role="group" aria-label="结构显示与测量工具">
    {modePanel}
    {vibration&&<div className="vibration-controls" data-testid="vibration-controls"><div><strong>模式 {vibration.mode_number} · {vibration.frequency_cm1} cm⁻¹ {vibration.frequency_cm1<0?'· 虚频方向示意':''}</strong><p>原始打印位移 × 显示幅度 × sin(相位)。播放速度不代表真实频率；测量使用参考坐标，连接保持参考结构。</p></div><button onClick={()=>setPlaying(!playing)}>{playing?'暂停动画':'继续播放'}</button><button onClick={()=>{setPlaying(false);clock.current=0;setPhase(0);}}>回到参考结构</button><button onClick={onClearVibration}>关闭模式</button><label>显示幅度 / Å<input aria-label="振动显示幅度" type="range" min="0.05" max="0.8" step="0.05" value={amplitude} onChange={e=>setAmplitude(Number(e.target.value))}/><output>{amplitude.toFixed(2)}</output></label><label>播放速度 / 周期·s⁻¹<input aria-label="振动播放速度" type="range" min="0.2" max="1.5" step="0.1" value={speed} onChange={e=>setSpeed(Number(e.target.value))}/><output>{speed.toFixed(1)}</output></label><span role="status">{playing?'播放中':'已暂停'}</span></div>}
    <details className="structure-tools"><summary>结构工具 · 显示 / 测量 / 视角</summary><div className="molecule-toolbar"><label>显示方式<select aria-label="分子显示方式" value={display} onChange={e=>setDisplay(e.target.value as Display)}><option value="ball-stick">球棍 · Ball & Stick</option><option value="tube">管状 · Tube</option><option value="wire">线框 · Wireframe</option></select></label>
      <label>标签<select aria-label="原子标签" value={labels} onChange={e=>setLabels(e.target.value)}><option value="both">元素与编号</option><option value="element">仅元素</option><option value="number">仅编号</option><option value="none">不显示</option></select></label>
      <label className="check-control"><input type="checkbox" checked={showBonds} onChange={e=>setShowBonds(e.target.checked)}/>显示推测连接</label>
      <label className="check-control"><input type="checkbox" checked={hydrogen} onChange={e=>{setHydrogen(e.target.checked);setSelected(s=>s.map(()=>null));}}/>显示氢原子</label>
      <button aria-pressed={large} onClick={()=>setLarge(!large)}>{large?'收起大视图':'放大查看区'}</button>
    </div>
    <label className="touch-toggle"><input type="checkbox" checked={touchEnabled} onChange={e=>{drag.current=null;setTouchEnabled(e.target.checked);}}/>启用触屏操作结构<span>关闭时可直接滑动页面</span></label>
    <div className="molecule-controls"><button aria-pressed={interaction==='rotate'} onClick={()=>setInteraction('rotate')}>旋转</button><button aria-pressed={interaction==='pan'} onClick={()=>setInteraction('pan')}>平移</button><button aria-label="放大结构" onClick={()=>changeZoom(1.2)}>＋ 放大</button><button aria-label="缩小结构" onClick={()=>changeZoom(1/1.2)}>− 缩小</button><button onClick={reset}>重置视角</button><label>预设视角<select aria-label="预设视角" value="" onChange={e=>{setAligned(false);setAngles(e.target.value==='front'?[0,0]:e.target.value==='top'?[Math.PI/2,0]:[0,Math.PI/2]);setPan([0,0]);}}><option value="" disabled>选择方向</option><option value="front">正视 XY</option><option value="top">俯视 XZ</option><option value="side">侧视 ZY</option></select></label></div>
    <details className="display-options"><summary>显示尺寸与元素配色</summary><div className="size-controls"><label>原子大小<input type="range" min="0.6" max="1.5" step="0.1" value={atomSize} onChange={e=>setAtomSize(Number(e.target.value))} disabled={display!=='ball-stick'}/></label><label>键线粗细<input type="range" min="0.6" max="1.8" step="0.1" value={bondSize} onChange={e=>setBondSize(Number(e.target.value))} disabled={display==='wire'}/></label></div><div className="element-legend">{[...new Set(visible.map(a=>a.atomic_number))].sort((a,b)=>a-b).map(n=><span key={n}><svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="6" fill={colors[n]??'#976abc'} stroke="#aaa"/></svg>{symbols[n]}</span>)}</div></details>
    <div className="measurement"><label>几何测量<select aria-label="测量方式" value={mode} onChange={e=>setMeasurement(e.target.value as Measurement)}><option value="distance">键长 / 原子间距</option><option value="angle">键角 A–B–C</option><option value="torsion">二面角 A–B–C–D</option></select></label><div>{selected.map((v,i)=><label key={i}>原子 {'ABCD'[i]}<select aria-label={`测距原子 ${'ABCD'[i]}`} value={v??''} onChange={e=>{const next=Number(e.target.value);setSelected(s=>s.map((x,j)=>j===i?next:x===next?null:x));}}><option value="" disabled>选择原子</option>{visible.map(a=><option value={a.center} key={a.center}>{symbols[a.atomic_number]} · {a.center}</option>)}</select></label>)}</div><output data-testid="atom-distance">{formatted}</output><button onClick={()=>setSelected(s=>s.map(()=>null))}>清除选择</button></div>
    {connectivity.overflow&&<p role="status">候选连接超过 3,000 条，已停用自动连线；请核对结构。</p>}
    <details><summary>连接推测规则与结构来源</summary><p className="muted micro">距离范围：√0.5 Å ≤ d ≤ 两原子显示连接半径之和 + 0.25 Å。未提供半径的元素不自动连线；不识别配位类型、氢键、芳香性或反应中的成断键。球尺寸为显示比例。</p>{connectivity.unsupported.length>0&&<p>未推测元素：{connectivity.unsupported.map(n=>symbols[n]).join('、')}</p>}{connectivity.closePairs>0&&<p>排除 {connectivity.closePairs} 对过近原子。</p>}</details>
    <details><summary>当前结构来源与字节区间</summary><pre>{JSON.stringify({orientation_kind:geometry.orientation_kind,units:geometry.units,source_span:geometry.source_span},null,2)}</pre></details>
    </details></div>
  </div>;
}
export function MoleculeViewer({last,review,renderSource,vibration,onClearVibration,scientificPanel,modePanel,frameLabel}:{last:unknown;frameLabel?:string;review?:unknown;renderSource?:(source:string,geometry:unknown)=>ReactNode;vibration?:VibrationMode;onClearVibration?:()=>void;scientificPanel?:ReactNode;modePanel?:ReactNode}) {
  const [source,setSource]=useState('last');const geometry=source==='review'?review:last;
  useEffect(()=>{if(vibration)setSource('last');},[vibration]);
  return <section className="molecule-section" aria-label="三维分子结构"><div className="section-heading"><div><div className="eyebrow">MOLECULAR GEOMETRY</div><h3>结构与振动</h3></div><label>坐标来源<select aria-label="结构来源" value={source} onChange={e=>{onClearVibration?.();setSource(e.target.value);}}><option value="last">{frameLabel??'最后记录结构'}</option>{isGeometry(review)&&<option value="review">Review 选中结构</option>}</select></label></div>
    <p className="muted">{source==='last'?(frameLabel?'当前选中优化周期的坐标；不表示最终结构或科学验收。':'日志最后一个已解析坐标块，不自动等同科学验收结构。'):'历史 Review 明确选中的坐标块；沿用报告的验收范围。'}</p>
    {!isGeometry(geometry)?<p className="empty compact">暂无可安全展示的坐标。</p>:geometry.atoms.length>2000?<p className="notice">结构超过本版 2,000 原子的交互显示上限；坐标表仍保留。</p>:<CoordinateScene key={source} geometry={geometry} vibration={source==='last'?vibration:undefined} onClearVibration={onClearVibration} modePanel={modePanel}/>}
    {(!isGeometry(geometry)||geometry.atoms.length>2000)&&modePanel}
    {renderSource?.(source,geometry)}
    {scientificPanel}
  </section>;
}
