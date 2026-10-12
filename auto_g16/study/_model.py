"""Closed request and deterministic native Core image for direct study /1."""
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
import sqlite3
import sys
from uuid import UUID, uuid5

from auto_g16.core import SQLiteRuntimeStore
from auto_g16.core.models import Project, WorkflowRun, Task, CalculationPlan, ResourceSpec, Attempt

STAGES = ('xtb', 'crest', 'anti_opt', 'anti_freq', 'gauche_opt', 'gauche_freq',
          'thermochemistry', 'populations')
BINDING_KEYS = {'path', 'parent_chain', 'file_identity', 'sha256', 'size_bytes'}


class StudyError(ValueError):
    pass


def require(condition, code='invalid-evidence'):
    if not condition:
        raise StudyError(code)


def plain(value):
    if is_dataclass(value):
        return {f.name: plain(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, Mapping):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [plain(v) for v in value]
    return value


def encode(value):
    return json.dumps(plain(value), sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True, allow_nan=False).encode()


def digest(raw):
    return sha256(raw).hexdigest()


def decode(raw, code='invalid-evidence', cap=1024 * 1024):
    require(type(raw) is bytes and 0 < len(raw) <= cap, code)
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, code)
            result[key] = value
        return result
    def nonfinite(_):
        raise StudyError(code)
    try:
        value = json.loads(raw, object_pairs_hook=pairs, parse_constant=nonfinite)
        encode(value)  # Reject overflowing JSON numbers too.
        return value
    except (ValueError, TypeError, OverflowError) as exc:
        raise StudyError(code) from exc


def closed(value, keys, code='invalid-evidence'):
    require(type(value) is dict and set(value) == set(keys), code)
    return value


def binding(value, code='invalid-catalog'):
    from auto_g16.transport._program_rtwin import _PublisherFileBinding
    closed(value, BINDING_KEYS, code)
    require(type(value['parent_chain']) is list and type(value['file_identity']) is list
            and all(type(n) is list for n in value['parent_chain']), code)
    path = value['path']
    require(type(path) is str and path.startswith('/') and len(path.encode()) <= 4096
            and not any(c in path for c in '\x00\r\n')
            and all(p not in {'', '.', '..'} for p in path[1:].split('/')), code)
    require(len(value['parent_chain']) == len(path[1:].split('/')) <= 128, code)
    for node in [*value['parent_chain'], value['file_identity']]:
        require(len(node) == 2 and type(node[0]) is int and 0 <= node[0] <= 2**63 - 1
                and type(node[1]) is int and 1 <= node[1] <= 2**63 - 1, code)
    require(type(value['sha256']) is str and re.fullmatch('[0-9a-f]{64}', value['sha256'])
            and type(value['size_bytes']) is int and 1 <= value['size_bytes'] <= 64 * 1024 * 1024, code)
    return _PublisherFileBinding(value['path'], tuple(tuple(n) for n in value['parent_chain']),
                                 tuple(value['file_identity']), value['sha256'], value['size_bytes'])


def request(raw, expected):
    require(type(expected) is str and re.fullmatch('[0-9a-f]{64}', expected)
            and digest(raw) == expected, 'invalid-request')
    value = closed(decode(raw, 'invalid-request'),
                   {'schema', 'creation_key', 'title', 'initial_xtb', 'catalog'}, 'invalid-request')
    require(raw == encode(value), 'invalid-request')
    require(value['schema'] == 'auto-g16-direct-study-request/1', 'invalid-request')
    try:
        require(str(UUID(value['creation_key'])) == value['creation_key'], 'invalid-request')
    except (ValueError, TypeError, AttributeError) as exc:
        raise StudyError('invalid-request') from exc
    require(type(value['title']) is str and value['title'] == value['title'].strip()
            and 0 < len(value['title']) <= 200, 'invalid-request')
    initial = closed(value['initial_xtb'], {'input_sha256', 'charge', 'multiplicity', 'cores',
        'memory_mb', 'walltime_seconds', 'queue'}, 'invalid-request')
    limits = {'charge': (-32, 32), 'multiplicity': (1, 33), 'cores': (1, 256),
              'memory_mb': (1, 1048576), 'walltime_seconds': (1, 604800)}
    for key, (low, high) in limits.items():
        require(type(initial[key]) is int and low <= initial[key] <= high, 'invalid-request')
    for key, pattern in [('input_sha256', '[0-9a-f]{64}'), ('queue', '[A-Za-z0-9_.-]{1,64}')]:
        require(type(initial[key]) is str and re.fullmatch(pattern, initial[key]), 'invalid-request')
    binding(value['catalog'], 'invalid-request')
    return value


def identities(value):
    namespace = UUID(value['creation_key'])
    make = lambda role: str(uuid5(namespace, role))
    return dict(project_id=make('project'), workflow_run_id=make('workflow'), stages={
        stage: {field: make(stage + ':' + field) for field in
                ('task_id', 'plan_id', 'resource_id', 'attempt_id')} for stage in STAGES})


def records(value):
    ids = identities(value)
    stage = ids['stages']['xtb']
    return (
        Project(project_id=ids['project_id']),
        WorkflowRun(workflow_run_id=ids['workflow_run_id'], project_id=ids['project_id'],
                    workflow_name=value['title']),
        Task(task_id=stage['task_id'], workflow_run_id=ids['workflow_run_id'], task_kind='xtb'),
        CalculationPlan(calculation_plan_id=stage['plan_id'], task_id=stage['task_id'], revision=1,
                        intent={'mode': 'historical-reuse', 'request': value}),
        ResourceSpec(resource_spec_id=stage['resource_id'], task_id=stage['task_id'],
                     resources={k: value['initial_xtb'][k] for k in
                                ('cores', 'memory_mb', 'walltime_seconds', 'queue')}),
        Attempt(attempt_id=stage['attempt_id'], task_id=stage['task_id'], ordinal=1))


def record_receipts(value):
    return [dict(kind=type(r).__name__, id=getattr(r, fields(r)[0].name),
                 sha256=digest(encode(r))) for r in records(value)]


def core_image(value):
    store = SQLiteRuntimeStore(':memory:')
    try:
        methods = (store.store_project, store.store_workflow_run, store.store_task,
                   store.store_calculation_plan, store.store_resource_spec, store.create_attempt)
        for method, record in zip(methods, records(value)):
            method(record)
        return store.export_memory_snapshot()
    finally:
        store.close()


def generator():
    root = Path(__file__).parents[1]
    return dict(schema='auto-g16-direct-study-core-image/1',
                python=f'{sys.version_info.major}.{sys.version_info.minor}', sqlite=sqlite3.sqlite_version,
                source_sha256={p: digest((root / p).read_bytes()) for p in
                               ('core/models.py', 'core/store.py', 'study/_model.py')})


def validate_core(path, value):
    ids = identities(value)
    stage = ids['stages']['xtb']
    with SQLiteRuntimeStore.read_snapshot(path) as store:
        actual = (store.load_project(ids['project_id']), store.load_workflow_run(ids['workflow_run_id']),
                  store.load_task(stage['task_id']), store.load_calculation_plan(stage['plan_id']),
                  store.load_resource_spec(stage['resource_id']), store.load_attempt(stage['attempt_id']))
        require(encode(actual) == encode(records(value)))
        require(store.attempt_state(stage['attempt_id']).value == 'PLANNED'
                and store.load_submission_intent(stage['attempt_id']) is None
                and not store.observations_for_attempt(stage['attempt_id'])
                and not store.results_for_attempt(stage['attempt_id']))
