import { useEffect, useState } from 'react';
import {useDetailView} from './workspace-view';
import { readResult } from './result-contract';
import type { GaussianResult } from './result-contract';

const availability = { available: '摘要可读', partial: '证据不完整', missing: '尚无可用结果', unsupported: '来源尚不支持', conflict: '证据存在冲突' };
const reasons: Record<string, string> = {
  'awaiting-input-binding': '尚无精确输入绑定', 'awaiting-capture': '尚无归档输出',
  'awaiting-parse': '输出已归档，尚无持久化解析结果', 'capture-partial': '输出采集不完整',
  'parse-partial': '解析结果不完整', 'parse-unparseable': '当前解析器未能提供可归属的摘要',
  'legacy-parser-not-qualified': '历史解析器的结果未具备摘要接入资格',
  'unsupported-records-present': '存在尚未支持的记录协议，摘要已停止展示',
  'v31-gaussian-source-not-qualified': 'V31 Gaussian 来源尚未具备接入资格',
  'mixed-execution-generations': '同一次尝试中混有不同执行代际的证据',
  'unsafe-identifier': '此记录的身份格式不在当前 Result 契约支持范围内',
  'unsupported-input-format': '输入格式尚未获得 Gaussian 摘要支持',
  'provenance-conflict': '结果与来源绑定未能通过校验',
  'frequency-missing': '未记录频率；不能据此判断虚频数为零', 'energy-missing': '未记录最终能量',
};
const errors: Record<string, string> = {
  unauthorized: '只读令牌无效，请断开后重新连接。', 'not-found': '此数据源中未找到这次尝试。',
  'store-unavailable': 'Result 数据源暂时不可读。', 'invalid-evidence': 'Result 证据未能通过校验。',
  'response-too-large': 'Result 超过读取上限，未展示截断结果。',
  'contract-mismatch': 'Result 接口契约或身份不匹配，已停止展示。',
};
function Datum({ label, value, hidden=false }: { label: string; value: string | number; hidden?:boolean }) {
  return <div hidden={hidden} className="field"><dt>{label}</dt><dd>{value}</dd></div>;
}
export function ResultPanel({ attemptId, token, resultState }: { attemptId: string; token: string; resultState: string }) {
  const [data, setData] = useState<GaussianResult | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    setData(null); setError('');
    readResult(attemptId, token, controller.signal).then(dto => {
      if (!controller.signal.aborted) setData(dto);
    }).catch(e => { if (!controller.signal.aborted) setError(e instanceof Error ? e.message : 'network-error'); });
    return () => controller.abort();
  }, [attemptId, token]);
  const facts = data?.summary;
  const {view}=useDetailView();
  return <section hidden={view!=='science'&&view!=='provenance'} className={`panel result-panel ${view==='science'?'compact-result-summary':''}`} aria-label="Gaussian Result 摘要">
    <h2>{view==='science'?'Gaussian · 结果摘要':'结果采集与解析记录'}</h2>
    <p className="micro muted">已归档事实 · 非科学验收</p>
    <div hidden={view!=='provenance'}><dl><Datum label="Query 记录状态" value={resultState} /></dl></div>
    {error ? <div role="alert" className="notice warning">{errors[error] ?? 'Result 读取失败，请刷新重试。'}</div> : !data ?
      <p role="status">正在读取 Result…</p> : <>
      <div hidden={view==='science'&&data.availability==='available'} className={`notice ${data.availability === 'conflict' || data.availability === 'unsupported' ? 'warning' : ''}`}>
        <strong>{availability[data.availability]}</strong> <code>{data.availability}</code>
        {data.reasons.map(reason => <p key={reason}>{reasons[reason] ?? '当前来源无法提供完整摘要'} <code>{reason}</code></p>)}
      </div>
      {facts && <dl hidden={view!=='science'} data-testid="result-facts">
        <Datum label="终止状态" value={{ 'normal-termination': '正常终止', 'error-termination': '错误终止', unknown: '未确定' }[facts.termination.status]} />
        <Datum hidden label="正常 / 错误终止次数" value={`${facts.termination.normal_count} / ${facts.termination.error_count}`} />
        <Datum label="最终能量 / Hartree" value={facts.final_energy_hartree ?? '未记录'} />
        <Datum hidden label="优化完成标记" value={facts.optimization.completed_marker ? '已记录' : '未观察到'} />
        <Datum hidden label="驻点标记" value={facts.optimization.stationary_point_marker ? '已记录' : '未观察到'} />
        <Datum label="频率数量" value={facts.frequency.count ?? '未记录'} />
        <Datum label="虚频数量" value={facts.frequency.imaginary_count ?? '未知（未记录频率）'} />
      </dl>}
      <div hidden={view!=='provenance'}>{facts&&<details><summary>已保存摘要事实</summary><pre>{JSON.stringify(facts,null,2)}</pre></details>}{data.source && <details><summary>所选结果的来源与绑定</summary><pre>{JSON.stringify(data.source, null, 2)}</pre></details>}
      <details><summary>归档历史 · {data.history.length} 次采集</summary>
        {data.history.length === 0 ? <p>暂无受支持的采集历史。</p> : data.history.map(h => <div className="log" key={h.envelope_id}>
          <strong>采集 {h.capture_sequence} · {h.selected ? '当前选中' : '历史记录'} · {h.capture_completeness}</strong>
          <code>{h.capture_source_id}</code><code>Envelope · {h.envelope_id}</code>
          {h.results.map(r => <div key={r.result_id}><code>Result · {r.result_id}</code><p>{String(r.parser.qualification)} · {String(r.parser.parse_status)}</p></div>)}
        </div>)}
      </details>
      <details><summary>记录清单 · {data.record_inventory.length}</summary><pre>{JSON.stringify(data.record_inventory, null, 2)}</pre></details>
      </div>
    </>}
    <p hidden={view!=='provenance'} className="muted">来源 · Result 公共只读接口；与 Core 详情分别读取快照。</p>

  </section>;
}
