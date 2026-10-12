import type {Geometry,Atom} from './molecule-viewer';
import {SYMBOLS} from './local-records';
export type DraftForm={title:string;job:'opt'|'optfreq'|'sp';method:string;basis:string;environment:string;charge:string;multiplicity:string;cores:string;memory:string;walltime:string;extra:string};
export const emptyForm:DraftForm={title:'',job:'optfreq',method:'',basis:'',environment:'',charge:'',multiplicity:'',cores:'',memory:'',walltime:'',extra:''};
const numeric=(s:string)=>{if(!/^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eEdD][+-]?\d+)?$/.test(s))throw Error('坐标包含非数值。');const n=Number(s.replace(/[dD]/,'e'));if(!Number.isFinite(n)||Math.abs(n)>1e6)throw Error('坐标超出支持范围。');return n;};
function atom(line:string,i:number):Atom {const a=line.trim().split(/\s+/);if(a.length!==4)throw Error('仅支持普通笛卡尔坐标：元素 X Y Z；不接受冻结标记或 Z-matrix。');const z=/^\d+$/.test(a[0])?Number(a[0]):SYMBOLS.indexOf(a[0]);if(z<1||z>118)throw Error('不支持的元素符号。');return {center:i+1,atomic_number:z,x:numeric(a[1]),y:numeric(a[2]),z:numeric(a[3])};}
export function parseStructure(text:string,name:string):{geometry:Geometry;charge?:number;multiplicity?:number;route?:string;warnings:string[]} {
 if(text.length>2*1024*1024)throw Error('结构文件超过 2 MiB。');const lines=text.replace(/\r\n?/g,'\n').split('\n');let atoms:Atom[]=[],charge:number|undefined,multiplicity:number|undefined,route:string|undefined;const warnings:string[]=[];
 if(/\.(gjf|com)$/i.test(name)){
  if(/--Link1--/i.test(text))throw Error('请拆分 Link1 输入后分别导入。');const r=lines.findIndex(l=>/^\s*#/.test(l));if(r<0)throw Error('未找到 Gaussian route。');let end=r;while(end<lines.length&&lines[end].trim())end++;route=lines.slice(r,end).join(' ');
  if(/\b(?:geom\s*=\s*(?:allcheck|check)|units\b)/i.test(route))throw Error('需要显式 Å 笛卡尔坐标；不读取 checkpoint 或 Bohr 坐标。');
  let i=end+1;while(i<lines.length&&!lines[i].trim())i++;while(i<lines.length&&lines[i].trim())i++;while(i<lines.length&&!lines[i].trim())i++;
  const cm=lines[i]?.trim().match(/^(-?\d+)\s+(\d+)$/);if(!cm)throw Error('缺少单体系电荷/多重度。');charge=Number(cm[1]);multiplicity=Number(cm[2]);i++;while(i<lines.length&&lines[i].trim()){atoms.push(atom(lines[i++],atoms.length));}
  warnings.push('已提取坐标与电荷/多重度。方法、资源和关键词需重新明确；额外基组/ECP、连接表不会自动复制。');
 }else if(/\.(sdf|mol)$/i.test(name)){
  if(!lines[3]?.includes('V2000')||text.includes('V3000'))throw Error('仅支持单分子 SDF/MOL V2000。');if(text.split('$$$$').slice(1).some(s=>s.trim()))throw Error('请一次导入一个分子。');const count=Number(lines[3].slice(0,3));if(!Number.isInteger(count)||count<1||count>2000)throw Error('原子数无效。');
  for(let i=0;i<count;i++){const l=lines[4+i];if(!l||l.length<34)throw Error('SDF 坐标块不完整。');if(l.slice(34,39).trim()&&Number(l.slice(34,39))!==0)warnings.push('SDF 包含同位素或电荷编码，请人工核对电子态。');atoms.push(atom(`${l.slice(31,34).trim()} ${l.slice(0,10).trim()} ${l.slice(10,20).trim()} ${l.slice(20,30).trim()}`,i));}
  if(!lines.some(l=>/^M  END/.test(l)))throw Error('SDF 缺少 M  END。');warnings.push('仅提取坐标；SDF 键级/立体标记未转换为科学身份，2D 坐标需先准备可信 3D 几何。');
 }else if(/\.xyz$/i.test(name)){
  const count=Number(lines[0]);if(!/^\d+$/.test(lines[0].trim())||count<1||count>2000||lines.length<count+2||lines.slice(count+2).some(l=>l.trim()))throw Error('需要一个完整 XYZ 帧（1–2000 原子）。');atoms=lines.slice(2,count+2).map(atom);
 }else throw Error('支持 .xyz、.gjf、.com、.sdf、.mol。');
 if(!atoms.length||atoms.length>2000)throw Error('坐标为空或超过 2000 原子。');return {geometry:{units:'angstrom',atoms},charge,multiplicity,route,warnings:[...new Set(warnings)]};
}
export function buildInput(f:DraftForm,g:Geometry){
 const fail=(s:string):never=>{throw Error(s);};const integer=(s:string,min:number,max:number,label:string)=>{if(!/^-?\d+$/.test(s)||Number(s)<min||Number(s)>max)fail(label+'必须明确填写且在范围内。');return Number(s);};
 if(!f.title.trim()||f.title.length>160||/[\r\n]/.test(f.title))fail('填写单行标题（最多 160 字）。');if(!['opt','optfreq','sp'].includes(f.job))fail('不支持的计算类型。');
 for(const [label,value] of [['方法',f.method],['基组',f.basis]])if(!/^[A-Za-z0-9+*(),.\-]+$/.test(value)||value.length>100)fail(label+'需明确填写一个受支持的名称。');
 if(/^(gen|genecp|chkbasis)$/i.test(f.basis))fail('混合基组/ECP 需要独立输入审核，本向导不生成。');
 if(!f.environment.trim()||/[\r\n#%]/.test(f.environment)||f.environment.length>160)fail('请明确环境：gas 或完整 SCRF=(...)。');
 if(f.environment!=='gas'&&!/^SCRF=\([A-Za-z0-9=(),.\-]+\)$/i.test(f.environment))fail('环境格式为 gas 或 SCRF=(模型,Solvent=溶剂)。');
 for(const value of [f.method,f.basis,f.environment,f.extra]){let depth=0;for(const c of value){if(c==='(')depth++;if(c===')')depth--;if(depth<0)fail('关键词括号不匹配。');}if(depth!==0)fail('关键词括号不匹配。');}
 const q=integer(f.charge,-100,100,'电荷'),m=integer(f.multiplicity,1,100,'多重度'),n=integer(f.cores,1,512,'核数'),mem=integer(f.memory,1,4096,'内存 GiB');
 if(!/^\d{1,4}:[0-5]\d:[0-5]\d$/.test(f.walltime)||f.walltime==='00:00:00')fail('Walltime 格式为小时:分:秒。');
 const electrons=g.atoms.reduce((s,a)=>s+a.atomic_number,0)-q;if(electrons<1||m-1>electrons||(electrons-(m-1))%2!==0)fail('电子数与多重度奇偶或范围不相容。');
 if(/[\r\n#%]/.test(f.extra)||f.extra.length>500||/\b(?:opt|freq|sp|irc|geom|units|guess|oniom|qst2|qst3|scrf|gen|genecp|chkbasis)\b/i.test(f.extra))fail('附加关键词不得覆盖任务、几何、单位或 checkpoint 读取方式。');
 if(!/^[A-Za-z0-9=(),.\-+* /]*$/.test(f.extra))fail('附加关键词含未支持字符。');
 const route=[`${f.method}/${f.basis}`,f.job==='sp'?'SP':f.job==='opt'?'Opt':'Opt Freq',f.environment==='gas'?'':f.environment,f.extra].filter(Boolean).join(' ');
 return `%nprocshared=${n}\n%mem=${mem}GB\n# ${route}\n\n${f.title}\n\n${q} ${m}\n${g.atoms.map(a=>`${SYMBOLS[a.atomic_number]} ${a.x} ${a.y} ${a.z}`).join('\n')}\n\n`;
}
export function routePatch(input:string,kind:'scf'|'opt',cycles:number){
 if(!Number.isInteger(cycles)||cycles<1||cycles>10000)throw Error('MaxCycle 需为 1–10000。');if(/--Link1--/i.test(input))throw Error('修复预览只支持一个 Gaussian job。');const match=input.match(/(^[ \t]*#[^\r\n]*(?:\r?\n[^\r\n]+)*)/m);if(!match)throw Error('未找到单一 route。');
 const route=match[0].replace(/\r?\n/g,' '),key=kind==='scf'?'SCF':'Opt';const pattern=new RegExp('\\b'+key+'(?:\\s*=\\s*(?:\\([^()]*\\)|[^\\s]+))?','ig');if(new RegExp('\\b'+key+'\\s*=\\s*\\([^)]*\\(','i').test(route))throw Error('嵌套关键词需手工审核，不生成局部替换。');const found=[...route.matchAll(pattern)];if(found.length>1)throw Error('重复关键词，需手工审核。');if(kind==='opt'&&!found.length)throw Error('原输入没有 Opt，不能自动添加优化任务。');
 let options=found.length?found[0][0].replace(new RegExp('^'+key+'\\s*=?\\s*','i'),'').replace(/^\(|\)$/g,'').split(',').filter(Boolean):[];
 options=options.filter(x=>!/^MaxCycles?\s*=/i.test(x));if(kind==='scf'){if(options.some(x=>/^(QC|YQC|XQC)$/i.test(x)))options=options.filter(x=>! /^(QC|YQC|XQC)$/i.test(x));options.push('XQC');}options.push('MaxCycle='+cycles);
 const value=key+'=('+options.join(',')+')';return input.replace(match[0],found.length?route.replace(pattern,value):route+' '+value);
}
export function lineDiff(a:string,b:string){const left=a.split('\n'),right=b.split('\n');let head=0;while(head<left.length&&head<right.length&&left[head]===right[head])head++;let tail=0;while(tail<left.length-head&&tail<right.length-head&&left[left.length-1-tail]===right[right.length-1-tail])tail++;return [...left.slice(0,head).map(l=>'  '+l),...left.slice(head,left.length-tail).map(l=>'- '+l),...right.slice(head,right.length-tail).map(l=>'+ '+l),...right.slice(right.length-tail).map(l=>'  '+l)].join('\n');}
