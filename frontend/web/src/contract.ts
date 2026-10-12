// UI contract is JSON DTO v1. No domain objects, SQL, or filesystem paths.
export type Json = null | boolean | number | string | Json[] | { [key: string]: Json };
export type Field = { availability: 'available' | 'missing' | 'unavailable'; value: Json; source: string | null; reason: string | null };
export const STATES = ['PLANNED', 'SUBMISSION_INTENT_RECORDED', 'SUBMITTED', 'UNKNOWN', 'RUNNING', 'SUCCEEDED', 'FAILED', 'NOT_SUBMITTED'] as const;
export type Project = {
  project_id: string; name: Field; created_at: Field; last_activity_at: Field;
  task_count: number; workflow_run_ids: string[]; current_task_state: Field;
  attempt_summary: { scope: 'all-persisted-attempts'; source: string; total: number; state_counts: Record<string, number> };
};
export type Task = { task_id: string; project_id: string; workflow_run_id: string; workflow_name: string; task_kind: string; batch_id: string | null; attempt_ids: string[] };
export type Attempt = {
  attempt_id: string; task_id: string; project_id: string; workflow_run_id: string; ordinal: number;
  parent_attempt_id: string | null; execution_state: string; result_state: string;
  bound_plan: Json; declared_science: Record<'program' | 'method' | 'basis' | 'charge' | 'multiplicity', Field>;
  effect: Field; input: Field; resources: Field; job: Field; collection: Field; validation: Field; review: Field; logs_availability: Field;
  observation: { observation_count: number; scheduler: Field; process: Field; gaussian: Field };
  coverage: { status: string; unprojected_observations: { observation_id: string; observation_type: string }[]; unprojected_results: { result_id: string; result_type: string }[] };
  logs: { envelope_observation_id: string; artifact_kind: string; logical_name: string; sha256: string; size_bytes: number; content: Field }[];
};
type KindMap = { projects: { items: Project[] }; project: Project; tasks: { items: Task[] }; attempts: { items: Attempt[] }; attempt: Attempt };
const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const text = (v: unknown): v is string => typeof v === 'string';
const nullableText = (v: unknown) => v === null || text(v);
const count = (v: unknown): v is number => Number.isSafeInteger(v) && (v as number) >= 0;
const strings = (v: unknown) => Array.isArray(v) && v.every(text);
const field = (v: unknown) => object(v) && ['available', 'missing', 'unavailable'].includes(String(v.availability)) && 'value' in v && nullableText(v.source) && nullableText(v.reason);
const fields = (v: Record<string, unknown>, keys: string[]) => keys.every(k => field(v[k]));
function project(v: unknown): boolean {
  if (!object(v) || !object(v.attempt_summary)) return false;
  const s = v.attempt_summary;
  return text(v.project_id) && count(v.task_count) && strings(v.workflow_run_ids) &&
    fields(v, ['name', 'created_at', 'last_activity_at', 'current_task_state']) &&
    s.scope === 'all-persisted-attempts' && text(s.source) && count(s.total) && object(s.state_counts) &&
    STATES.every(k => object(s.state_counts) && count(s.state_counts[k]));
}
function task(v: unknown): boolean {
  return object(v) && ['task_id', 'project_id', 'workflow_run_id', 'workflow_name', 'task_kind'].every(k => text(v[k])) && nullableText(v.batch_id) && strings(v.attempt_ids);
}
function attempt(v: unknown): boolean {
  if (!object(v) || !object(v.observation) || !object(v.coverage) || !object(v.declared_science)) return false;
  const c = v.coverage;
  return ['attempt_id', 'task_id', 'project_id', 'workflow_run_id', 'result_state'].every(k => text(v[k])) &&
    STATES.includes(v.execution_state as typeof STATES[number]) && count(v.ordinal) && nullableText(v.parent_attempt_id) && 'bound_plan' in v &&
    fields(v, ['effect', 'input', 'resources', 'job', 'collection', 'validation', 'review', 'logs_availability']) &&
    fields(v.declared_science, ['program', 'method', 'basis', 'charge', 'multiplicity']) &&
    fields(v.observation, ['scheduler', 'process', 'gaussian']) && count(v.observation.observation_count) &&
    ['recognized-protocols-only', 'unsupported-protocols-present'].includes(String(c.status)) &&
    Array.isArray(c.unprojected_observations) && c.unprojected_observations.every(x => object(x) && text(x.observation_id) && text(x.observation_type)) &&
    Array.isArray(c.unprojected_results) && c.unprojected_results.every(x => object(x) && text(x.result_id) && text(x.result_type)) &&
    Array.isArray(v.logs) && v.logs.every(x => object(x) && ['envelope_observation_id', 'artifact_kind', 'logical_name', 'sha256'].every(k => text(x[k])) && count(x.size_bytes) && field(x.content));
}
export function parseDTO<K extends keyof KindMap>(value: unknown, kind: K): KindMap[K] {
  if (!object(value) || value.schema !== 'auto-g16-query/1' || value.kind !== kind) throw new Error('contract-mismatch');
  const validators = { project, attempt, projects: project, tasks: task, attempts: attempt };
  const valid = ['projects', 'tasks', 'attempts'].includes(kind)
    ? object(value.data) && Array.isArray(value.data.items) && value.data.items.every(validators[kind])
    : validators[kind](value.data);
  if (!valid) throw new Error('contract-mismatch');
  return value.data as KindMap[K];
}
// One budget for the whole page, including index polling and detail panels.
// Idle HTTP/1 connections also count against the local server's finite limit.
let activeQueries=0;
const queryWaiters:Array<()=>void>=[];
export async function requestJSON(path: string, token: string, signal: AbortSignal, policy: 'ordinary'|'native-scientific-read' = 'ordinary'): Promise<unknown> {
  if(activeQueries>=2)await new Promise<void>(resolve=>queryWaiters.push(resolve));else activeQueries++;
  const release=()=>{const next=queryWaiters.shift();if(next)next();else activeQueries--;};
  if(signal.aborted){release();throw new DOMException('Aborted','AbortError');}
  // Navigation abandons the consumer, not the in-flight HTTP slot: a canceled
  // browser fetch can still be executing on the local server. Drain that read
  // before releasing the shared budget, bounded by a transport deadline.
  const milliseconds=policy==='native-scientific-read'?120000:15000;
  const transport=new AbortController();let timedOut=false;
  const deadline=setTimeout(()=>{timedOut=true;transport.abort();},milliseconds);
  const pending=fetchJSON(path,token,transport.signal).catch(error=>{
    if(timedOut)throw new Error(`读取超时（${milliseconds/1000} 秒）。可稍后手动重试。`);
    throw error;
  }).finally(()=>{clearTimeout(deadline);release();});
  let cancel=()=>{};
  const abandoned=new Promise<never>((_resolve,reject)=>{cancel=()=>reject(new DOMException('Aborted','AbortError'));signal.addEventListener('abort',cancel,{once:true});});
  try{return await Promise.race([pending,abandoned]);}finally{signal.removeEventListener('abort',cancel);}
}

async function fetchJSON(path: string, token: string, signal: AbortSignal): Promise<unknown> {
  const response = await fetch(path, { method: 'GET', headers: token ? { Authorization: `Bearer ${token}` } : {}, cache: 'no-store', credentials: 'omit', redirect: 'error', signal });
  if (!response.ok) {
    let code = `http-${response.status}`;
    try { const body = await response.json(); if (body.schema === 'auto-g16-http-error/1' && typeof body.error?.code === 'string') code = body.error.code; } catch { /* retain HTTP status */ }
    throw new Error(code);
  }
  return response.json();
}
export async function read<K extends keyof KindMap>(path: string, kind: K, token: string, signal: AbortSignal): Promise<KindMap[K]> {
  return parseDTO(await requestJSON(path, token, signal), kind);
}
export type Route = { kind: 'projects' } | { kind: 'project' | 'attempt'; id: string } | { kind: 'invalid' };
export function route(hash: string): Route {
  if (!hash || hash === '#/' || hash === '#/projects') return { kind: 'projects' };
  const match = /^#\/(projects|attempts)\/([^/]+)$/.exec(hash);
  if (!match) return { kind: 'invalid' };
  try { return { kind: match[1] === 'projects' ? 'project' : 'attempt', id: decodeURIComponent(match[2]) }; } catch { return { kind: 'invalid' }; }
}
export const link = (type: 'projects' | 'attempts', id: string) => `#/${type}/${encodeURIComponent(id)}`;
