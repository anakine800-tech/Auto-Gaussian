"""Finite fresh-study intake; no executable snapshots or approval authority."""
from math import isfinite
from pathlib import Path
from uuid import UUID, uuid5
import re
import sqlite3
import sys

from auto_g16.core import SQLiteRuntimeStore
from auto_g16.core.models import Project, WorkflowRun, Task, CalculationPlan, ResourceSpec, Attempt
from ._model import STAGES, closed, decode, digest, encode, require

SCHEMA = 'auto-g16-direct-study-request/2'
PROTOCOL = {
    'xtb': {'method': 'GFN2-xTB', 'optimization': 'engine_default_opt'},
    'crest': {'method': 'GFN2-xTB', 'search': 'iMTD-GC',
              'metadynamics_length_ps': 1, 'energy_window_kcal_mol': 6,
              'rmsd_threshold_angstrom': 0.125, 'cregen_temperature_k': 298.15,
              'normal_md_temperature_k': 400, 'calculator': 'internal-tblite',
              'atom_order': 'preserve-input-order', 'randomness': 'engine_managed_stochastic'},
    'gaussian': {'method': 'wB97XD', 'basis': 'Def2SVP', 'environment': 'gas',
                 'scf': 'Tight_MaxCycle128', 'integration_grid': 'UltraFine',
                 'symmetry': 'NoSymm', 'optimization_max_cycles': 128},
}
THERMOCHEMISTRY = {
    'temperature_k': 298.15, 'pressure_atm': 1, 'frequency_scale_factor': 1,
    'entropy_model': 'grimme', 'enthalpy_model': 'head_gordon',
    'low_frequency_cutoff_cm1': 100, 'zpe_scale_factor': 1,
    'interpolation_alpha': 4, 'bav_kg_m2': 1e-44,
    'degeneracy_policy': 'one_gauche_representative_weight_two',
}


def _xyz(structure):
    closed(structure, {'xyz_utf8', 'sha256', 'charge', 'multiplicity'}, 'invalid-request')
    require(type(structure['charge']) is int and structure['charge'] == 0
            and type(structure['multiplicity']) is int and structure['multiplicity'] == 1,
            'invalid-request')
    text = structure['xyz_utf8']
    require(type(text) is str and '\x00' not in text and '\r' not in text, 'invalid-request')
    try:
        raw = text.encode('utf-8')
    except UnicodeError as exc:
        from ._model import StudyError
        raise StudyError('invalid-request') from exc
    require(type(structure['sha256']) is str and digest(raw) == structure['sha256'],
            'invalid-request')
    lines = text.splitlines()
    require(len(lines) == 16 and lines[0].strip() == '14', 'invalid-request')
    elements = []
    for line in lines[2:]:
        fields = line.split()
        require(len(fields) == 4 and fields[0] in {'C', 'H'}, 'invalid-request')
        require(all(re.fullmatch(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?', v)
                    for v in fields[1:]), 'invalid-request')
        require(all(isfinite(float(v)) for v in fields[1:]), 'invalid-request')
        elements.append(fields[0])
    require(elements.count('C') == 4 and elements.count('H') == 10, 'invalid-request')


def request(raw, expected):
    require(type(expected) is str and re.fullmatch('[0-9a-f]{64}', expected)
            and digest(raw) == expected, 'invalid-request')
    value = closed(decode(raw, 'invalid-request'),
        {'schema', 'creation_key', 'title', 'structure', 'protocol', 'resources',
         'thermochemistry'}, 'invalid-request')
    require(raw == encode(value) and value['schema'] == SCHEMA, 'invalid-request')
    try:
        require(str(UUID(value['creation_key'])) == value['creation_key'], 'invalid-request')
    except (ValueError, TypeError, AttributeError) as exc:
        from ._model import StudyError
        raise StudyError('invalid-request') from exc
    require(type(value['title']) is str and value['title'] == value['title'].strip()
            and 0 < len(value['title']) <= 200, 'invalid-request')
    _xyz(value['structure'])
    # Canonical comparisons also reject True == 1 and unintended numeric forms.
    require(encode(value['protocol']) == encode(PROTOCOL), 'invalid-request')
    require(encode(value['thermochemistry']) == encode(THERMOCHEMISTRY), 'invalid-request')
    resources = closed(value['resources'], STAGES[:6], 'invalid-request')
    for stage in STAGES[:6]:
        expected_resource = dict(cores=4, memory_mb=12288, queue='batch',
                                 walltime_seconds=1800 if stage == 'xtb' else 3600)
        require(encode(resources[stage]) == encode(expected_resource), 'invalid-request')
    return value


def identities(value):
    namespace = UUID(value['creation_key'])
    def make(role):
        return str(uuid5(namespace, SCHEMA + ':' + role))
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
                        intent={'mode': 'fresh-execution', 'request': value}),
        ResourceSpec(resource_spec_id=stage['resource_id'], task_id=stage['task_id'],
                     resources=value['resources']['xtb']),
        Attempt(attempt_id=stage['attempt_id'], task_id=stage['task_id'], ordinal=1))


def record_receipts(value):
    from dataclasses import fields
    return [dict(kind=type(r).__name__, id=getattr(r, fields(r)[0].name),
                 sha256=digest(encode(r))) for r in records(value)]


def core_image(value):
    with SQLiteRuntimeStore(':memory:') as store:
        methods = (store.store_project, store.store_workflow_run, store.store_task,
                   store.store_calculation_plan, store.store_resource_spec, store.create_attempt)
        for method, record in zip(methods, records(value)):
            method(record)
        return store.export_memory_snapshot()


def generator():
    root = Path(__file__).parents[1]
    return dict(schema='auto-g16-direct-study-core-image/2',
                python=f'{sys.version_info.major}.{sys.version_info.minor}', sqlite=sqlite3.sqlite_version,
                source_sha256={p: digest((root / p).read_bytes()) for p in
                               ('core/models.py', 'core/store.py', 'study/_fresh_model.py')})


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
