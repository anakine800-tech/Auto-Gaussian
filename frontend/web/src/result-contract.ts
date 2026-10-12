import { requestJSON } from './contract';
import type { Json } from './contract';

export type GaussianResult = {
  schema: 'gaussian-result-summary/1'; attempt_id: string | null;
  availability: 'available' | 'partial' | 'missing' | 'unsupported' | 'conflict';
  reasons: string[]; source: { [key: string]: Json } | null;
  summary: null | {
    termination: { status: 'normal-termination' | 'error-termination' | 'unknown'; normal_count: number; error_count: number };
    final_energy_hartree: number | null;
    optimization: { completed_marker: boolean; stationary_point_marker: boolean };
    frequency: { availability: 'available' | 'missing'; count: number | null; imaginary_count: number | null };
  };
  record_inventory: { record_kind: 'result' | 'observation'; record_id: string; source_type: string; source_type_sha256: string }[];
  history: { envelope_id: string; capture_source_id: string; capture_sequence: number; capture_completeness: string; selected: boolean; results: { result_id: string; parser: { [key: string]: Json } }[] }[];
};
const obj = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const str = (v: unknown): v is string => typeof v === 'string';
const id = (v: unknown) => str(v) && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}$/.test(v);
const hash = (v: unknown) => str(v) && /^[0-9a-f]{64}$/.test(v);
const count = (v: unknown): v is number => Number.isSafeInteger(v) && (v as number) >= 0;
const nullable = (check: (v: unknown) => boolean, v: unknown) => v === null || check(v);
function parser(v: unknown): boolean {
  return obj(v) && ['attributed', 'legacy'].includes(String(v.qualification)) &&
    ['name', 'version', 'grammar_id'].every(k => nullable(str, v[k])) && str(v.kind) &&
    ['parsed', 'partial', 'unparseable'].includes(String(v.parse_status));
}
function source(v: unknown): boolean {
  if (v === null) return true;
  return obj(v) && str(v.protocol) && ['input_binding_id', 'prepared_input_binding_id', 'calculation_plan_id', 'execution_snapshot_id'].every(k => id(v[k])) &&
    count(v.calculation_plan_revision) && obj(v.input) && hash(v.input.sha256) && count(v.input.size_bytes) &&
    ['envelope_id', 'capture_source_id', 'result_id'].every(k => nullable(id, v[k])) &&
    nullable(hash, v.capture_manifest_sha256) && nullable(str, v.capture_completeness) && nullable(str, v.capture_status) &&
    nullable(parser, v.parser) && Array.isArray(v.outputs) && v.outputs.every(x => obj(x) && str(x.artifact_kind) && hash(x.sha256) && count(x.size_bytes));
}
function summary(v: unknown): boolean {
  if (!obj(v) || !obj(v.termination) || !obj(v.frequency) || !obj(v.optimization)) return false;
  const t = v.termination, f = v.frequency, o = v.optimization;
  return ['normal-termination', 'error-termination', 'unknown'].includes(String(t.status)) && count(t.normal_count) && count(t.error_count) &&
    nullable(x => typeof x === 'number' && Number.isFinite(x), v.final_energy_hartree) &&
    typeof o.completed_marker === 'boolean' && typeof o.stationary_point_marker === 'boolean' &&
    (f.availability === 'missing' ? f.count === null && f.imaginary_count === null :
      f.availability === 'available' && count(f.count) && f.count > 0 && count(f.imaginary_count) && f.imaginary_count <= f.count);
}
export function parseResult(value: unknown, attemptId: string): GaussianResult {
  if (!obj(value) || value.schema !== 'gaussian-result-summary/1' ||
    !['available', 'partial', 'missing', 'unsupported', 'conflict'].includes(String(value.availability)) ||
    !Array.isArray(value.reasons) || !value.reasons.every(str) ||
    !(value.attempt_id === attemptId || (value.attempt_id === null && value.availability === 'conflict' && value.reasons.includes('unsafe-identifier'))) ||
    !source(value.source) ||
    !(value.availability === 'available' ? summary(value.summary) && value.source !== null : value.summary === null) ||
    (value.availability === 'conflict' && (value.source !== null || !Array.isArray(value.history) || value.history.length !== 0)) ||
    !Array.isArray(value.record_inventory) || !value.record_inventory.every(x => obj(x) && ['result', 'observation'].includes(String(x.record_kind)) && id(x.record_id) && str(x.source_type) && hash(x.source_type_sha256)) ||
    !Array.isArray(value.history) || !value.history.every(x => obj(x) && id(x.envelope_id) && id(x.capture_source_id) && count(x.capture_sequence) && str(x.capture_completeness) && typeof x.selected === 'boolean' &&
      Array.isArray(x.results) && x.results.every(r => obj(r) && id(r.result_id) && parser(r.parser)))) throw new Error('contract-mismatch');
  return value as GaussianResult;
}
export async function readResult(attemptId: string, token: string, signal: AbortSignal): Promise<GaussianResult> {
  return parseResult(await requestJSON(`/api/attempts/${encodeURIComponent(attemptId)}/result`, token, signal), attemptId);
}
