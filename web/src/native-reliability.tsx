import {useEffect,useState} from 'react';
import {requestJSON} from './contract';
import {decodeLifecycle,decodePopulations} from './native-reliability-contract';
import {NativeThermodynamics} from './native-thermodynamics';

type Props={sourceId:string;attemptId:string;token:string};
function useSaved(kind:'lifecycle'|'populations',props:Props){
 const {sourceId,attemptId,token}=props,key=JSON.stringify([sourceId,attemptId,token]);
 const [state,setState]=useState<{key:string;data:Record<string,any>|null;error:string}>({key,data:null,error:''});
 useEffect(()=>{const c=new AbortController();setState({key,data:null,error:''});
 requestJSON(`/api/v1/native/sources/${encodeURIComponent(sourceId)}/attempts/${encodeURIComponent(attemptId)}/${kind}`,token,c.signal,'native-scientific-read')
 .then(v=>{if(!c.signal.aborted)setState({key,data:(kind==='lifecycle'?decodeLifecycle:decodePopulations)(v,sourceId,attemptId),error:''});})
 .catch(e=>{if(!c.signal.aborted)setState({key,data:null,error:e instanceof Error?e.message:'request-failed'});});return()=>c.abort();},[key,kind,sourceId,attemptId,token]);
 return state.key===key?state:{data:null,error:''};
}
function Status({data,error}:{data:Record<string,any>|null;error:string}){return error?<p role="alert">读取失败：{error}</p>:!data?<p role="status">正在读取…</p>:<p>不可用（unavailable · {data.reason}）</p>;}
function Lifecycle(props:Props){const state=useSaved('lifecycle',props),r=state.data?.result;
 return <section className="native-saved-thermodynamics" aria-label="三轴历史状态"><h2>三轴历史状态</h2><p>历史保存记录；程序 exit 0 仅表示进程结束。Gaussian normal termination 与科学核验仍以原有解析来源为准。</p>
 {!r?<Status {...state}/>:<><p>Core：{r.core_state} · job：{r.job_id} · 最后 Observation：{r.projection_as_of_observation_id??'未记录'}</p><div className="native-grid">{(['program','scheduler','collection'] as const).map(k=>{const a=r[k];return <article key={k} aria-label={k}><h3>{{program:'程序结束',scheduler:'PBS 历史状态',collection:'结果采集'}[k]}</h3><strong>{a.state??'未记录'}</strong><p>{a.availability} · {a.reason}</p><p>观测时间：未记录</p>{k==='program'?<><p>结束时间：{a.completed_at??'未记录'}</p><p>exit：{a.exit_code??'未记录'} · signal：{a.signal??'未记录'}</p></>:k==='scheduler'?<><p>presence：{a.presence}</p><p>原始 PBS code：未记录 · {a.raw_state_reason}</p></>:<><p>条件：{a.condition}</p><p>Result：{a.result_id??'未记录'}</p></>}<details><summary>轴证据来源</summary><pre>{JSON.stringify(a.evidence_refs,null,2)}</pre></details></article>})}</div><details><summary>生命周期身份</summary><pre>{JSON.stringify({schema:r.schema,attempt_id:r.attempt_id,snapshot_id:r.snapshot_id,projection_as_of_observation_id:r.projection_as_of_observation_id},null,2)}</pre></details></>}
 </section>;
}
function Populations(props:Props&{thermoHash:string|null}){const state=useSaved('populations',props),r=state.data?.result;
 const mismatch=r&&props.thermoHash!==null&&r.source_pair_sha256!==props.thermoHash;
 return <section className="native-saved-thermodynamics" aria-label="RRHO 与 qRRHO 已保存布居"><h2>RRHO 与 qRRHO 已保存布居</h2>
 {!r?<Status {...state}/>:mismatch?<p role="alert">读取失败：contract-mismatch（热化学 pair 来源不一致）</p>:<>
 <p>温度：{String(r.parameters.temperature_k)} K · 标准态：{r.parameters.standard_state} · ΔG 参考成员：<strong>{r.reference_member_id}</strong></p>
 <p>当前成员：{state.data?.selected_member_id}。ΔG 是每个代表构象相对参考的已保存值；布居仅转换为百分比显示。</p>
 <p>{props.thermoHash===null?'低频参数尚未取得或未核对；不能据此确认与原热化学面板的关联。':'pair hash 已匹配；低频截断、缩放和处理方法见下方已保存参数。'}</p>
 <div className="native-saved-members">{r.members.map((m:any)=><article key={m.member_id}><h3>{m.member_id}{m.is_selected?' · 当前成员':''}</h3><p>g = {m.degeneracy} · {m.degeneracy_rationale}</p><p>Gaussian 原始 σ = {String(m.reported_rotational_symmetry_number)} · {m.symmetry_rationale}</p><div className="native-population-scroll"><table><caption>已保存双方案</caption><thead><tr><th>方案</th><th>G / Hartree</th><th>ΔG / kcal/mol</th><th>布居 / %</th></tr></thead><tbody>{['rrho','qrrho'].map(s=><tr key={s}><th>{s==='rrho'?'RRHO':'qRRHO'}</th><td>{String(m[s].gibbs_free_energy_hartree)}</td><td>{String(m[s].delta_g_kcal_per_mol)}</td><td>{String(m[s].normalized_population*100)}%</td></tr>)}</tbody></table></div><details><summary>成员完整公开来源与保存值</summary><pre>{JSON.stringify({source:m.source,rrho:m.rrho,qrrho:m.qrrho},null,2)}</pre></details></article>)}</div>
 <p>g 排除转动对称性；不额外乘镜像或旋转因子。仅代表冻结范围：{r.coverage_scope.rationale}。科学验收：{r.scientific_acceptance}。</p>
 <details><summary>双方案参数、归一化记录与 artifact/pair 摘要</summary><pre>{JSON.stringify({artifact_id:r.artifact_id,payload_sha256:r.payload_sha256,artifact_sha256:r.artifact_sha256,source_pair_sha256:r.source_pair_sha256,qualified_ensemble:r.qualified_ensemble,thermodynamic_ensemble:r.thermodynamic_ensemble,parameters:r.parameters,normalization:r.normalization,coverage_scope:r.coverage_scope},null,2)}</pre></details>
 </>}
 </section>;
}
export function NativeReliability(props:Props){
 const key=JSON.stringify([props.sourceId,props.attemptId,props.token]);
 return <BoundReliability key={key} {...props}/>;
}
function BoundReliability(props:Props){const [thermoHash,setThermoHash]=useState<string|null>(null);
 return <><Lifecycle {...props}/><Populations {...props} thermoHash={thermoHash}/><NativeThermodynamics {...props} onArtifact={setThermoHash}/></>;
}
