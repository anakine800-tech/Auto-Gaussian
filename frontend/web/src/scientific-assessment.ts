import {object,artifact,boundSpan} from './provenance';
import type {SourceSpan} from './provenance';

export type ScientificFacts={
 schema:'auto-g16-scientific-display-facts/1';job_section:SourceSpan;
 program_status:'normal-termination'|'error-termination'|'no-terminal-marker';
 normal_termination_count:number;error_termination_count:number;
 termination_evidence:{kind:'normal-termination'|'error-termination';source_span:SourceSpan}[];
 optimization_completed_marker:boolean;optimization_completed_evidence:SourceSpan[];
 stationary_point_marker:boolean;stationary_point_evidence:SourceSpan[];
 frequency_parse_complete:boolean;frequency_count:number;imaginary_frequency_count:number;
};
const count=(v:unknown):v is number=>Number.isSafeInteger(v)&&Number(v)>=0;
export function scientificFacts(data:unknown,source:unknown):ScientificFacts|null {
 if(!object(data)||!object(source)||!artifact(source.artifact)||!((source.parser==='auto-g16-v3-gaussian-job'&&source.parser_version==='1.1.0')||(source.parser==='autog-local-gaussian-job'&&source.parser_version==='1.0.0'))||typeof source.result_id!=='string'||!source.result_id)return null;
 const f=data.scientific_facts,frequencies=data.frequencies_cm1,blocks=data.frequency_blocks;
 if(!object(f)||f.schema!=='auto-g16-scientific-display-facts/1'||!boundSpan(f.job_section,source.artifact)||
    !Array.isArray(frequencies)||!frequencies.every(v=>typeof v==='number'&&Number.isFinite(v))||!Array.isArray(blocks))return null;
 const section=f.job_section,inside=(span:unknown)=>boundSpan(span,source.artifact)&&span.start>=section.start&&span.end<=section.end;
 if(!['normal-termination','error-termination','no-terminal-marker'].includes(String(f.program_status))||
    !['normal_termination_count','error_termination_count','frequency_count','imaginary_frequency_count'].every(k=>count(f[k]))||
    !['optimization_completed_marker','stationary_point_marker','frequency_parse_complete'].every(k=>typeof f[k]==='boolean')||
    f.frequency_count!==frequencies.length||f.imaginary_frequency_count!==frequencies.filter(v=>v<0).length)return null;
 const flat:number[]=[];let previousEnd=section.start;
 for(const block of blocks){if(!object(block)||!boundSpan(block.source_span,source.artifact)||!inside(block.source_span)||block.source_span.start<previousEnd||!Array.isArray(block['frequencies_cm-1']))return null;flat.push(...block['frequencies_cm-1']);previousEnd=block.source_span.end;}
 if(flat.length!==frequencies.length||!flat.every((v,i)=>v===frequencies[i]))return null;
 for(const [flag,key] of [['optimization_completed_marker','optimization_completed_evidence'],['stationary_point_marker','stationary_point_evidence']]){
  const spans=f[key];if(!Array.isArray(spans)||!spans.every(inside)||f[flag]!==Boolean(spans.length))return null;
 }
 const terminals=f.termination_evidence;
 if(!Array.isArray(terminals)||!terminals.every(t=>object(t)&&['normal-termination','error-termination'].includes(String(t.kind))&&inside(t.source_span))||
    terminals.filter(t=>t.kind==='normal-termination').length!==f.normal_termination_count||terminals.filter(t=>t.kind==='error-termination').length!==f.error_termination_count||
    (terminals.at(-1)?.kind??'no-terminal-marker')!==f.program_status)return null;
 // Display projection is independently checked before deriving any label.
 return f as ScientificFacts;
}
export function screenCandidate(f:ScientificFacts|null) {
 if(!f)return {code:'EVIDENCE_UNAVAILABLE',label:'验证事实不可用',reason:'缺少绑定一致的程序事实，无法给出候选提示。'};
 if(f.program_status==='error-termination'||f.error_termination_count>0)return {code:'PROGRAM_FAILED',label:'程序失败 · 暂不给出候选分类',reason:'日志存在错误终止，不能由频率数量提升为候选结果。'};
 if(f.frequency_count===0||!f.frequency_parse_complete)return {code:'FREQUENCY_INCOMPLETE',label:'frequency incomplete',reason:'频率缺失或解析不完整；虚频总数未知。'};
 if(f.program_status!=='normal-termination'||!f.optimization_completed_marker||!f.stationary_point_marker)return {code:'EVIDENCE_INCOMPLETE',label:'驻点证据待补齐',reason:'正常终止、优化完成或驻点标记尚未齐备；频率计数仍可查阅。'};
 if(f.imaginary_frequency_count>1)return {code:'NOT_FIRST_ORDER',label:'not a first-order saddle candidate',reason:'已记录多个负频率，不符合一级鞍点的频率计数条件。'};
 if(f.imaginary_frequency_count===1)return {code:'TS_CANDIDATE',label:'TS candidate',reason:'reaction-coordinate confirmation required'};
 return {code:'MINIMUM_CANDIDATE',label:'minimum candidate',reason:'零虚频仅支持极小值候选提示，不表示结构身份、计算条件或科学验收已确认。'};
}
