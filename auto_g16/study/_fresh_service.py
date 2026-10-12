"""Immutable fresh creation image; native runtime has not been activated."""
import re

from . import _fresh_model as model
from ._model import closed, decode, digest, encode, require, STAGES

FILES = ('0001-intent.json', '0002-core.json', '0003-complete.json')
KINDS = ('INTENT', 'CORE', 'LOCAL_CREATE_COMPLETE')


def _events(directory):
    names = directory.names()
    require(names <= {*FILES, 'core.sqlite3'})
    events, previous = [], None
    for index, name in enumerate(FILES):
        if name not in names:
            require(not any(p in names for p in FILES[index + 1:]), 'initialization-unresolved')
            break
        raw, _ = directory.read(name, 2 * 1024 * 1024)
        event = closed(decode(raw, 'initialization-unresolved', 2 * 1024 * 1024),
                       {'schema', 'sequence', 'previous_sha256', 'kind', 'data'})
        require(raw == encode(event) and event['schema'] == 'auto-g16-direct-study-event/2'
                and type(event['sequence']) is int and event['sequence'] == index + 1
                and event['previous_sha256'] == previous and event['kind'] == KINDS[index])
        events.append(event)
        previous = digest(raw)
    return events


def _append(directory, events, data):
    index = len(events)
    event = dict(schema='auto-g16-direct-study-event/2', sequence=index + 1,
                 previous_sha256=digest(encode(events[-1])) if events else None,
                 kind=KINDS[index], data=data)
    directory.publish(FILES[index], encode(event))
    events.append(event)


def _intent(directory, event):
    data = closed(event['data'], {'request', 'request_sha256', 'directory_chain', 'identities',
                                 'core_image_generator'})
    value = model.request(encode(data['request']), data['request_sha256'])
    require(data['identities'] == model.identities(value) and data['directory_chain'] == directory.chain)
    saved = closed(data['core_image_generator'], {'schema', 'python', 'sqlite', 'source_sha256'})
    require(saved['schema'] == 'auto-g16-direct-study-core-image/2')
    for field in ('python', 'sqlite'):
        require(type(saved[field]) is str and re.fullmatch(r'\d+\.\d+(?:\.\d+)?', saved[field]))
    hashes = closed(saved['source_sha256'], {'core/models.py', 'core/store.py', 'study/_fresh_model.py'})
    require(all(type(h) is str and re.fullmatch('[0-9a-f]{64}', h) for h in hashes.values()))
    return value


def _core(directory, events, value):
    present = 'core.sqlite3' in directory.names()
    require(present or len(events) == 1, 'initialization-unresolved')
    if not present:
        return None
    raw, physical = directory.read('core.sqlite3')
    receipt = dict(path='core.sqlite3', sha256=digest(raw), size_bytes=len(raw),
                   file_identity=physical, records=model.record_receipts(value))
    if len(events) > 1:
        require(events[1]['data'] == receipt)
    else:
        require(events[0]['data']['core_image_generator'] == model.generator(), 'initialization-unresolved')
        require(raw == model.core_image(value), 'initialization-unresolved')
    model.validate_core(str(directory.path / 'core.sqlite3'), value)
    return receipt


def operate_locked(command, target, incoming, request_sha256):
    """Called only by fixed dispatch while its Directory context remains held."""
    require(command in {'create', 'review', 'status', 'query', 'audit', 'recover'}, 'invalid-request')
    events = _events(target)
    if not events:
        require(not target.names(), 'initialization-unresolved')
        require(command == 'create', 'not-found')
        _append(target, events, dict(request=incoming, request_sha256=request_sha256,
            directory_chain=target.chain, identities=model.identities(incoming),
            core_image_generator=model.generator()))
    value = _intent(target, events[0])
    if command == 'create':
        require(incoming == value and request_sha256 == events[0]['data']['request_sha256'], 'invalid-request')
    core = _core(target, events, value)
    if command == 'create' and len(events) == 1:
        require(events[0]['data']['core_image_generator'] == model.generator(), 'initialization-unresolved')
        if core is None:
            target.publish('core.sqlite3', model.core_image(value))
            core = _core(target, events, value)
        _append(target, events, core)
    complete = dict(request_sha256=events[0]['data']['request_sha256'],
                    core_sha256=core['sha256']) if core else None
    if len(events) == 3:
        require(events[2]['data'] == complete)
    elif command == 'create' and len(events) == 2:
        _append(target, events, complete)
    target.seal({*FILES[:len(events)], *({'core.sqlite3'} if core else set())})
    ids = model.identities(value)
    next_step = None if len(events) == 3 else (
        'core-image' if core is None else 'core-event' if len(events) == 1 else 'complete-event')
    return dict(schema='auto-g16-direct-study-response/2', command=command,
        study_id=ids['project_id'], request_sha256=events[0]['data']['request_sha256'],
        status='local-created' if len(events) == 3 else 'initializing', data=dict(
            mode='fresh-execution', identities=ids, journal=[dict(sequence=e['sequence'],
                kind=e['kind'], sha256=digest(encode(e))) for e in events],
            creation_snapshot=core, stages=[dict(stage=stage, ids=ids['stages'][stage],
                materialized=stage == 'xtb' and core is not None,
                core_state='PLANNED' if stage == 'xtb' and core is not None else None,
                program=None, scheduler=None, collection=None, scientific_result=None) for stage in STAGES],
            review={**{key: value[key] for key in ('structure', 'protocol', 'resources', 'thermochemistry')},
                    'approvals': dict(scientific='pending', batch='pending', operational='pending')},
            execution_performed=False, fresh_execution_e2e=False,
            execution_readiness=dict(state='blocked', reason='execution-contract-not-frozen'),
            next_local_step=next_step))
