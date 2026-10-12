import {object,boundSpan} from './provenance';
import type {SourceSpan} from './provenance';
import {isGeometry} from './molecule-viewer';
export type Displacement={center:number;atomic_number:number;dx:number;dy:number;dz:number};
export type VibrationMode={mode_number:number;frequency_index:number;block_index:number;column_index:number;frequency_cm1:number;source_span:SourceSpan;frequency_source_span:SourceSpan;displacements:Displacement[]};
const equal=(a:unknown,b:unknown):boolean=>{
 if(a===b)return true;if(Array.isArray(a)&&Array.isArray(b))return a.length===b.length&&a.every((v,i)=>equal(v,b[i]));
 if(object(a)&&object(b)){const keys=Object.keys(a);return keys.length===Object.keys(b).length&&keys.every(k=>Object.hasOwn(b,k)&&equal(a[k],b[k]));}return false;
};
export function vibrationModes(response:unknown,kind:string,id:string,source:unknown,data:unknown):VibrationMode[]|null {
 const fail=()=>{throw Error('mode-contract-mismatch');};
 if(!object(response)||response.schema!=='auto-g16-mode-evidence/1'||response.kind!==kind||response.id!==id||!object(response.vibrations))return fail();
 const f=response.vibrations;
 if(f.availability==='unavailable'&&f.data===null&&f.source===null&&typeof f.reason==='string')return null;
 if(f.availability!=='available'||!object(f.data)||!object(f.source)||f.source.kind!=='pinned-offline-vibration-modes'||typeof f.source.sha256!=='string'||! /^[a-f0-9]{64}$/.test(f.source.sha256)||!Number.isSafeInteger(f.source.size_bytes)||!object(source)||!object(data))return fail();
 const p=f.data;
 if(p.schema!=='auto-g16-vibration-modes/1'||p.kind!==kind||p.id!==id||!['1.0.0','1.1.0'].some(version=>equal(p.decoder,{name:'autog-gaussian-cartesian-display-modes',version}))||p.vector_convention!=='gaussian-printed-normalized-cartesian-displacements'||!equal(p.result_source,source)||!equal(p.reference_geometry,data.last_geometry)||!isGeometry(p.reference_geometry)||p.reference_geometry.orientation_kind!=='standard-orientation'||!Array.isArray(p.modes)||!Array.isArray(data.frequencies_cm1)||!Array.isArray(data.frequency_blocks))return fail();
 const g=p.reference_geometry,modes=p.modes,frequencies=data.frequencies_cm1,blocks=data.frequency_blocks;
 if(!boundSpan(g.source_span,source.artifact)||g.atoms.length>2000||modes.length<1||modes.length!==frequencies.length||modes.length>Math.min(6000,3*g.atoms.length))return fail();
 const flat:unknown[]=[],positions:{block:number;column:number;span:unknown}[]=[];
 for(const [bi,b] of blocks.entries()){if(!object(b)||!Array.isArray(b['frequencies_cm-1']))return fail();for(const [ci,v] of b['frequencies_cm-1'].entries()){flat.push(v);positions.push({block:bi,column:ci,span:b.source_span});}}
 if(!equal(flat,frequencies))return fail();
 for(const [i,m] of modes.entries()){
  const pos=positions[i];if(!object(m)||m.frequency_index!==i||m.mode_number!==i+1||m.block_index!==pos.block||m.column_index!==pos.column||m.frequency_cm1!==frequencies[i]||typeof m.frequency_cm1!=='number'||!Number.isFinite(m.frequency_cm1)||!equal(m.frequency_source_span,pos.span)||!boundSpan(m.frequency_source_span,source.artifact)||!boundSpan(m.source_span,source.artifact)||m.source_span.start!==m.frequency_source_span.start||m.source_span.end<=m.frequency_source_span.end||m.source_span.start<g.source_span.end||!Array.isArray(m.displacements)||m.displacements.length!==g.atoms.length)return fail();
  let norm=0;for(const [j,v] of m.displacements.entries()){const atom=g.atoms[j];if(!object(v)||v.center!==atom.center||v.atomic_number!==atom.atomic_number)return fail();for(const k of ['dx','dy','dz']){const n=v[k];if(typeof n!=='number'||!Number.isFinite(n)||Math.abs(n)>1.05)return fail();norm+=n*n;}}
  if(Math.abs(Math.sqrt(norm)-1)>.03+.005*Math.sqrt(3*g.atoms.length))return fail();
 }
 return modes as VibrationMode[];
}
