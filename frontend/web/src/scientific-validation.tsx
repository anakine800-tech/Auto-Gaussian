import {HistoricalReview} from './historical-review';
import type {ReactNode} from 'react';
import {object,SourceLocation,frequencySources} from './provenance';
import type {SourceTarget} from './provenance';
import {scientificFacts,screenCandidate} from './scientific-assessment';
import type {VibrationMode} from './vibration-contract';
import {useDetailView} from './workspace-view';
import {HumanModeReview} from './mode-review';

type Props={token:string;activeMode?:VibrationMode;data:unknown;source:unknown;review:unknown;kind:'attempt'|'archive';id:string;modes:VibrationMode[]|null;modeStatus:string;onRead:()=>void;onPlay:(m:VibrationMode)=>void;onLocate:(target:SourceTarget)=>void};
export function ScientificValidation({data,source,review,kind,id,modes,modeStatus,onRead,onPlay,onLocate,token,activeMode}:Props){
 const {showEvidence}=useDetailView();
 const f=scientificFacts(data,source),screen=screenCandidate(f),s=object(source)?source:{},d=object(data)?data:{},r=object(review)?review:{};
 const frequencies=f?d.frequencies_cm1 as number[]:[],imaginary=frequencies.flatMap((v,i)=>v<0?[{value:v,index:i}]:[]),spans=frequencySources(frequencies,d.frequency_blocks,s.artifact);
 const row=(label:string,value:ReactNode,span?:unknown)=><div className="field"><dt>{label}</dt><dd>{value}{span!==undefined&&<SourceLocation span={span} parent={s.artifact} label={label} onLocate={onLocate}/>}</dd></div>;
 const yes=(v:boolean|undefined)=>v===undefined?'? 未知':v?'✓ 已记录':'? 未观察到';
 return <details className="scientific-validation" aria-label="Scientific validation" data-testid="scientific-validation">
  <summary className="validation-summary"><strong>科学验证 · 结果只读</strong><span>{screen.label} · 虚频 {f&&f.frequency_count?(f.frequency_parse_complete?f.imaginary_frequency_count:`至少 ${f.imaginary_frequency_count}`):'未知'}</span><small>展开事实与人工复核</small></summary><div className="validation-body">
  <h4>程序事实</h4><dl>
   {row('Gaussian 终止',!f?'? 不可用':f.program_status==='normal-termination'?'✓ Normal termination':f.program_status==='error-termination'?'× Error termination':'? 未记录终止',f?.termination_evidence.at(-1)?.source_span)}
   {row('优化完成标记',yes(f?.optimization_completed_marker),f?.optimization_completed_evidence.at(-1))}
   {row('驻点标记',yes(f?.stationary_point_marker),f?.stationary_point_evidence.at(-1))}
   {row('频率解析',!f?'? 不可用':f.frequency_count===0?'? 未记录频率':f.frequency_parse_complete?`✓ 已解析 ${f.frequency_count} 个频率`:`? 解析不完整 · 已读 ${f.frequency_count} 个`)}
   {row('虚频数量',!f||!f.frequency_count?'未知':f.frequency_parse_complete?f.imaginary_frequency_count:`至少 ${f.imaginary_frequency_count} 个（不完整）`)}
   {row('频率任务完成性','待核对计算类型与完整模式集')}
  </dl><details className="validation-explanation"><summary>判读边界与证据说明</summary><p className="micro muted">完成/驻点标记为日志事实；未重新验证收敛阈值。解析完整不等于完整 Hessian 或已核对 3N−6 / 3N−5 个模式。</p></details>
  <div className="candidate-assessment" data-testid="candidate-assessment"><h4>候选筛查 · 展示规则 v1</h4><strong>{screen.label}</strong><p>{screen.reason}</p><code>{screen.code}</code></div>
  <details className="validation-explanation"><summary>候选筛查规则</summary><p className="micro muted">仅对当前已记录频率作初步提示，不是新运行的 Auto-Gaussian validator。计算条件一致性、结构与频率对应关系及近零频率仍需审查；所有负值都计入，不自动忽略小虚频。</p></details>
  {imaginary.length>0&&<div className="imaginary-modes"><h4>虚频模式 / cm⁻¹</h4>{imaginary.map(({value,index})=><div key={index}><strong className="negative-frequency">{value}</strong><span>Mode {index+1}</span>{modes?.[index]?<button aria-label={`查看虚频模式 ${index+1}`} onClick={()=>onPlay(modes[index])}>▶ 播放</button>:<span className="micro">位移尚不可用</span>}<SourceLocation span={spans[index]} parent={s.artifact} label={`验证卡虚频 ${index+1}`} onLocate={onLocate}/></div>)}{modeStatus==='idle'?<button onClick={onRead}>读取虚频位移</button>:modeStatus==='loading'?<p role="status">正在核对位移来源…</p>:modeStatus==='error'?<p role="status">位移来源校验失败，无法播放。</p>:modeStatus==='unavailable'?<p>未接入合格位移；不能从频率数字补造动画。</p>:null}</div>}
  <h4>已有 Auto-Gaussian 验证</h4><HistoricalReview data={r}/>
  {typeof r.classification==='string'&&<><p className="micro">仅沿用历史范围；原因：{String(r.reason_code??'未记录')}。历史接受不等于本次 TS 确认。</p><button onClick={()=>showEvidence('scientific-review')}>查看历史报告与验收范围 ↗</button></>}
  <h4>人的科学判断</h4><HumanModeReview key={JSON.stringify(source)+id+token} id={id} kind={kind} source={source} activeMode={activeMode} token={token} tsCandidate={screen.code==='TS_CANDIDATE'}/>
  <details><summary>本卡身份与来源</summary><dl>{row(kind==='attempt'?'Attempt ID':'Archive ID',<code>{id}</code>)}{row('Result ID',<code>{String(s.result_id??'未记录')}</code>)}{row('解析器',<code>{String(s.parser??'未记录')} / {String(s.parser_version??'未记录')}</code>)}</dl><p className="micro">数据来自同一次 details 查询中的持久化 Result。筛查针对该 Result 记录的频率，不随显示坐标切换；历史 Review 选中频率仍单独展示。</p></details>
 </div></details>;
}
