import {ArchiveStatus,StatusLegend} from './status-badge';
import { useEffect, useState } from 'react';
import { requestJSON } from './contract';
import {DetailWorkspace,ViewGroup} from './workspace-view';
import { DetailPanel } from './detail-panel';
import { useCollection, Filters, Pagination } from './browse';

type Summary = { termination: string; normal_count: number; error_count: number; energy_hartree: number | null; optimization: boolean; stationary_point: boolean; frequency_count: number | null; imaginary_count: number | null };
type Archive = { archive_id: string; title: string; source_kind: 'legacy_archive'|'local_log_archive'; source_location: string; captured_at: string; parser: { name: string; version: string; status: string; diagnostics: string[] }; summary: Summary | null; authority: Record<string, string> };
type Detail = Archive & { artifacts: { role: string; logical_name: string; sha256: string; size_bytes: number }[]; input: { text: string; binding: string }|null; legacy_metadata: { schema: string; recorded_status: string; scope: string }|null };
const obj = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const text = (v: unknown): v is string => typeof v === 'string';
const count = (v: unknown): v is number => Number.isSafeInteger(v) && (v as number) >= 0;
function summary(s: unknown): boolean {
  if (s === null) return true;
  if (!obj(s)) return false;
  return ['normal-termination', 'error-termination', 'no-terminal-marker'].includes(String(s.termination)) && count(s.normal_count) && count(s.error_count) &&
    (s.energy_hartree === null || typeof s.energy_hartree === 'number' && Number.isFinite(s.energy_hartree)) && typeof s.optimization === 'boolean' && typeof s.stationary_point === 'boolean' &&
    (s.frequency_count === null && s.imaginary_count === null || count(s.frequency_count) && s.frequency_count > 0 && count(s.imaginary_count) && s.imaginary_count <= s.frequency_count);
}
function archive(v: unknown): v is Archive {
  return obj(v) && text(v.archive_id) && /^archive-[0-9a-f]{64}$/.test(v.archive_id) &&
    ['title', 'source_location', 'captured_at'].every(k => text(v[k])) && ['legacy_archive','local_log_archive'].includes(String(v.source_kind)) &&
    obj(v.authority) && ['core_attempt', 'live_state', 'scientific_acceptance', 'review'].every(k => obj(v.authority) && v.authority[k] === 'unavailable') &&
    obj(v.parser) && ((v.parser.name === 'auto-g16-v3-gaussian-job' && v.parser.version === '1.1.0')||(v.parser.name === 'autog-local-gaussian-job' && v.parser.version === '1.0.0')) &&
    ['parsed', 'partial', 'unparseable', 'unsupported'].includes(String(v.parser.status)) && Array.isArray(v.parser.diagnostics) && v.parser.diagnostics.every(text) &&
    (v.parser.status === 'parsed' ? v.summary !== null && summary(v.summary) : v.summary === null);
}
function detail(v: unknown): v is Detail {
  if (!archive(v)) return false;
  const r = v as unknown as Record<string, unknown>;
  if(r.source_kind==='local_log_archive')return r.input===null&&r.legacy_metadata===null&&Array.isArray(r.artifacts)&&r.artifacts.length===1&&r.artifacts.every(a=>obj(a)&&a.role==='log'&&text(a.logical_name)&&text(a.sha256)&&/^[0-9a-f]{64}$/.test(a.sha256)&&r.archive_id===`archive-${a.sha256}`&&count(a.size_bytes)&&a.size_bytes<=32*1024*1024);
  return Array.isArray(r.artifacts) && r.artifacts.length === 3 && r.artifacts.every(a => obj(a) && ['log', 'input', 'legacy_metadata'].includes(String(a.role)) && text(a.logical_name) && text(a.sha256) && /^[0-9a-f]{64}$/.test(a.sha256) && count(a.size_bytes)) &&
    new Set(r.artifacts.map(a => a.role)).size === 3 && r.artifacts.some(a => a.role === 'log' && r.archive_id === `archive-${a.sha256}`) &&
    obj(r.input) && text(r.input.text) && r.input.binding === 'legacy-job-input-hash-matched' && obj(r.legacy_metadata) && r.legacy_metadata.schema === 'codex-gaussian-pbs/1' && text(r.legacy_metadata.recorded_status) && r.legacy_metadata.scope === 'historical-sidecar-claim';
}
function Facts({ data,compact=false,evidence=false }: { data: Archive;compact?:boolean;evidence?:boolean }) {
  const s = data.summary;
  if (!s) return <p className="notice warning"><ArchiveStatus status={data.parser.status}/>当前解析器未能提供摘要：{data.parser.status}。原文件引用仍保留。</p>;
  const values = [
    ['日志终止标记', { 'normal-termination': '正常终止', 'error-termination': '错误终止', 'no-terminal-marker': '未观察到终止标记' }[s.termination]],
    ['正常 / 错误终止次数', `${s.normal_count} / ${s.error_count}`], ['最终能量 / Hartree', s.energy_hartree ?? '未记录'],
    ['优化完成标记', s.optimization ? '已记录' : '未观察到'], ['驻点标记', s.stationary_point ? '已记录' : '未观察到'],
    ['频率数量', s.frequency_count ?? '未记录'], ['虚频数量', s.imaginary_count ?? '未知（未记录频率）'],
  ];
  return <dl data-testid={evidence?"archive-evidence-facts":"archive-facts"}><div className="field"><dt>计算 / 解析状态</dt><dd><ArchiveStatus status={data.parser.status} termination={s.termination}/></dd></div>{values.map(([k, v]) => <div hidden={compact&&['正常 / 错误终止次数','优化完成标记','驻点标记','日志终止标记'].includes(String(k))} className="field" key={k}><dt>{k}</dt><dd>{v}</dd></div>)}</dl>;
}
export function ArchivePanel({ token, id, fromProject }: { token: string; id: string | null; fromProject?:string }) {
  const [items, setItems] = useState<Archive[] | null>(null);
  const [record, setRecord] = useState<Detail | null>(null);
  const [configured, setConfigured] = useState(true);
  const [error, setError] = useState('');
  const c=useCollection(items??[],a=>({id:a.archive_id,name:a.title,search:[a.title,a.archive_id,a.source_location].join(' '),states:[a.summary?.termination??a.parser.status],programs:['Gaussian']}), 'archives');
  useEffect(() => {
    const c = new AbortController();
    async function load() {
      try {
        if (id !== null && !/^archive-[0-9a-f]{64}$/.test(id)) throw new Error('not-found');
        const dto = await requestJSON(id ? `/api/archives/${id}` : '/api/archives', token, c.signal);
        if (!obj(dto) || !['auto-g16-legacy-archive/1','auto-g16-legacy-archive/2'].includes(String(dto.schema))) throw new Error('contract-mismatch');
        if(dto.schema==='auto-g16-legacy-archive/1'&&(id?obj(dto.data)&&dto.data.source_kind==='local_log_archive':Array.isArray(dto.items)&&dto.items.some(a=>obj(a)&&a.source_kind==='local_log_archive')))throw new Error('contract-mismatch');
        if (id) {
          if (dto.kind !== 'archive' || !detail(dto.data) || dto.data.archive_id !== id) throw new Error('contract-mismatch');
          if (!c.signal.aborted) setRecord(dto.data);
        } else {
          if (dto.kind !== 'archives' || typeof dto.configured !== 'boolean' || !Array.isArray(dto.items) || !dto.items.every(archive) || new Set(dto.items.map(a => a.archive_id)).size !== dto.items.length) throw new Error('contract-mismatch');
          if (!c.signal.aborted) { setItems(dto.items); setConfigured(dto.configured); }
        }
      } catch (e) { if (!c.signal.aborted) setError(e instanceof Error ? e.message : 'network-error'); }
    }
    void load(); return () => c.abort();
  }, [token, id]);
  return <>{!id&&<><div className="page-heading"><div className="eyebrow">HISTORICAL ARCHIVES</div><h1>历史计算档案</h1><p>读取已核对的历史文件副本，保留输入、结果摘要和文件来源。</p></div>
    <StatusLegend/><div className="notice">历史档案没有原生 Core Task / Attempt 绑定。旧状态仅为历史记录；实时调度、Scientific Validation 与 Review 均未接入。</div></>}
    {error ? <div role="alert" className="error">历史档案暂不可读，或来源校验失败。请检查本地索引和访问令牌后刷新。</div> : record ? <>

      <DetailWorkspace identity={record.archive_id}>
      <section className="panel archive-overview"><h2>{record.title}</h2><ViewGroup view="evidence" id="workflow-evidence"><code>{record.archive_id}</code><p className="muted">本次归档读取时间 · {record.captured_at}（不是计算完成时间）</p></ViewGroup>
        <ViewGroup view="science"><Facts data={record} compact/></ViewGroup><ViewGroup view="evidence"><p className="notice">历史目录归属，未验证原生 Task / Attempt 绑定；实时调度与原生 Review 未接入。</p><Facts data={record} evidence/><p className="muted">来源 · {record.parser.name} / {record.parser.version}；日志事实不代表科学验收。</p></ViewGroup>
      </section>
      <DetailPanel kind="archive" id={record.archive_id} token={token}/>
      <ViewGroup view="provenance"><section className="panel"><h2>历史输入文件</h2><p>{record.input?'输入 SHA-256 与历史 job.json 一致；未建立新的 Core 输入绑定。':'未建立输入与日志的可靠绑定；配套文件保留在本地导入清单，不由同名文件推断归属。'}</p>{record.input&&<pre data-testid="archive-input">{record.input.text}</pre>}</section>
      <section className="panel"><h2>原始文件引用</h2>{record.artifacts.map(a => <div className="log" key={a.role}><strong>{a.logical_name}</strong><span>{a.size_bytes} bytes · {a.role}</span><code>SHA-256 {a.sha256}</code></div>)}<p className="muted">已连接的日志可在下方读取；检查点下载尚未开放。</p></section>
      <section className="panel"><h2>历史记录与可用范围</h2><p>{record.legacy_metadata?<>job.json 当时记录的状态：<code>{record.legacy_metadata.recorded_status}</code>（非当前状态）</>:'本地日志档案：未接入合格的历史调度或验收记录。'}</p><p>Core Attempt / 实时状态 / 科学验收 / Review：不可用</p><details><summary>解析诊断</summary><pre>{JSON.stringify(record.parser.diagnostics, null, 2)}</pre></details></section></ViewGroup></DetailWorkspace>

    </> : items ? <>{!configured && <p className="empty">此服务尚未配置历史档案索引。</p>}{configured && items.length === 0 && <p className="empty">暂无已接入档案。</p>}<Filters collection={c} label="搜索历史档案"/>{c.count===0&&items.length>0&&<p className="empty">没有匹配的历史档案。</p>}{c.rows.map(a => <article className="project-card" key={a.archive_id}><div className="eyebrow">{a.source_location}</div><h2><a href={`#/archives/${a.archive_id}`}>{a.title} ↗</a></h2><code>{a.archive_id}</code><Facts data={a} /></article>)}<Pagination collection={c}/></> : <p role="status">正在读取历史档案…</p>}
  </>;
}
