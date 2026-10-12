"""Result-bound display context from public records; never parse or infer conditions."""
from hashlib import sha256
import json
from .archive_import import plain

SCHEMA = 'auto-g16-result-context/1'
PLAN_SCHEMA = 'auto-g16-v30-a-calculation-plan-intent/1'
PATHS = {
    'method': ('method', 'electronic_structure_method'),
    'basis': ('method', 'basis'),
    'environment': ('method', 'environment'),
    'charge': ('molecule', 'charge'),
    'multiplicity': ('molecule', 'multiplicity'),
    'dispersion': ('method', 'dispersion'),
}
KEYS = (*PATHS, 'temperature_k', 'pressure_atm')


def field(reason, source=None, *, missing=False):
    return dict(availability='missing' if missing else 'unavailable', value=None, source=source, reason=reason)


def base(kind, identity, lineage, input_artifact=None):
    return dict(schema=SCHEMA, kind=kind, id=identity, lineage=lineage, input=input_artifact,
                plan=None, conditions=dict(
                    declared={k: field('qualified-bound-plan-required') for k in KEYS},
                    observed={k: field('qualified-parser-does-not-project-condition') for k in KEYS}),
                comparison_status='not-assessed')


def native_context(store, attempt):
    task = store.load_task(attempt.task_id)
    run = store.load_workflow_run(task.workflow_run_id)
    project = store.load_project(run.project_id)
    return base('attempt', attempt.attempt_id, dict(
        scope='public-core-hierarchy', project_id=project.project_id,
        workflow_run_id=run.workflow_run_id, workflow_name=run.workflow_name,
        task_id=task.task_id, attempt_id=attempt.attempt_id, archive_id=None,
        result_source=None, input_binding_observation_id=None))


def bind_result(context, plan, binding, outcome, result_source, envelope):
    if (plan.task_id != context['lineage']['task_id']
            or binding.attempt_id != context['id']
            or binding.calculation_plan_id != plan.calculation_plan_id
            or binding.calculation_plan_revision != plan.revision
            or outcome.attempt_id != context['id']
            or outcome.envelope_observation_id != envelope.observation_id
            or envelope.input_binding_observation_id != binding.observation_id
            or envelope.attempt_id != binding.attempt_id
            or envelope.execution_snapshot_id != binding.execution_snapshot_id
            or outcome.result_id != result_source['result_id']):
        raise ValueError('result context identity mismatch')
    intent = plain(plan.intent)
    digest = sha256(json.dumps(dict(calculation_plan_id=plan.calculation_plan_id,
        task_id=plan.task_id, revision=plan.revision, intent=intent), ensure_ascii=True,
        sort_keys=True, allow_nan=False, separators=(',', ':')).encode()).hexdigest()
    source = dict(kind='bound-calculation-plan-declaration', calculation_plan_id=plan.calculation_plan_id,
                  revision=plan.revision, plan_sha256=digest, input_binding_observation_id=binding.observation_id)
    context['plan'] = {**source, 'intent_schema': intent.get('schema') if isinstance(intent.get('schema'), str) else None}
    context['lineage'].update(result_source=result_source, input_binding_observation_id=binding.observation_id)
    context['input'] = {k: plain(binding.payload())[k] for k in ('logical_name', 'sha256', 'size_bytes', 'input_format')}
    for key in KEYS:
        if intent.get('schema') != PLAN_SCHEMA:
            value = field('unsupported-plan-intent-schema', source)
        elif key not in PATHS:
            value = field('condition-not-projected-by-plan-contract', source)
        else:
            section, name = PATHS[key]
            where = {**source, 'field_path': 'intent.' + section + '.' + name}
            obj = intent.get(section)
            if obj is not None and not isinstance(obj, dict):
                value = field('invalid-declared-condition', where)
            elif not isinstance(obj, dict) or name not in obj or obj[name] is None:
                value = field('not-recorded-in-bound-plan', where, missing=True)
            else:
                raw = obj[name]
                valid = (type(raw) is int and -1000 <= raw <= 1000 if key == 'charge' else
                         type(raw) is int and 1 <= raw <= 1000 if key == 'multiplicity' else
                         isinstance(raw, str) and 0 < len(raw) <= 256 and raw == raw.strip()
                         and not any(ord(c) < 32 or ord(c) == 127 for c in raw))
                value = (dict(availability='available', value=raw, source=where, reason=None)
                         if valid else field('invalid-declared-condition', where))
        context['conditions']['declared'][key] = value
    return context


def archive_context(record, result_source=None):
    # Parsing context IDs from offline imports never become native Core lineage.
    inp = next((a for a in record['artifacts'] if a['role'] == 'input'), None)
    context = base('archive', record['archive_id'], dict(
        scope='legacy-archive-not-core-lineage', project_id=None, workflow_run_id=None,
        workflow_name=None, task_id=None, attempt_id=None, archive_id=record['archive_id'],
        result_source=result_source, input_binding_observation_id=None),
        {k: inp[k] for k in ('logical_name', 'sha256', 'size_bytes')} if inp else None)
    context['conditions']['declared'] = {k: field('archive-has-no-qualified-native-plan') for k in KEYS}
    return context
