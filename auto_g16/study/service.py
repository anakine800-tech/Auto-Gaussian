"""Unified direct local management; exact resume publishes only a provable suffix."""
import re
from . import _catalog
from ._files import Directory, read_request
from ._model import (StudyError, closed, core_image, decode, digest, encode, generator,
                     identities, record_receipts, request, require, validate_core)

FILES = ('0001-intent.json', '0002-core.json', '0003-sources.json', '0004-complete.json')
KINDS = ('INTENT', 'CORE', 'HISTORICAL_SOURCES_VERIFIED', 'LOCAL_CREATE_COMPLETE')
ALLOWED = {*FILES, 'core.sqlite3'}


def _events(directory):
    names = directory.names()
    require(names <= ALLOWED)
    events, previous = [], None
    for index, name in enumerate(FILES):
        if name not in names:
            require(not any(p in names for p in FILES[index + 1:]), 'initialization-unresolved')
            break
        raw, _ = directory.read(name, 2 * 1024 * 1024)
        event = closed(decode(raw, 'initialization-unresolved', 2 * 1024 * 1024),
                       {'schema', 'sequence', 'previous_sha256', 'kind', 'data'})
        require(raw == encode(event) and event['schema'] == 'auto-g16-direct-study-event/1'
                and type(event['sequence']) is int and event['sequence'] == index + 1
                and event['previous_sha256'] == previous and event['kind'] == KINDS[index])
        events.append(event)
        previous = digest(raw)
    return events


def _append(directory, events, data):
    index = len(events)
    event = dict(schema='auto-g16-direct-study-event/1', sequence=index + 1,
                 previous_sha256=digest(encode(events[-1])) if events else None,
                 kind=KINDS[index], data=data)
    directory.publish(FILES[index], encode(event))
    events.append(event)


def _intent(directory, event):
    data = closed(event['data'], {'request', 'request_sha256', 'directory_chain', 'identities',
                                 'core_image_generator'})
    value = data['request']
    request(encode(value), data['request_sha256'])
    require(data['identities'] == identities(value) and data['directory_chain'] == directory.chain)
    saved_generator = closed(data['core_image_generator'], {'schema', 'python', 'sqlite', 'source_sha256'})
    require(saved_generator['schema'] == 'auto-g16-direct-study-core-image/1')
    for field in ('python', 'sqlite'):
        require(type(saved_generator[field]) is str and re.fullmatch(r'\d+\.\d+(?:\.\d+)?', saved_generator[field]))
    hashes = closed(saved_generator['source_sha256'], {'core/models.py', 'core/store.py', 'study/_model.py'})
    require(all(type(h) is str and re.fullmatch('[0-9a-f]{64}', h) for h in hashes.values()))
    return value


def _core(directory, events, value):
    present = 'core.sqlite3' in directory.names()
    require(present or len(events) == 1, 'initialization-unresolved')
    if not present:
        return None
    raw, physical = directory.read('core.sqlite3')
    receipt = dict(path='core.sqlite3', sha256=digest(raw), size_bytes=len(raw),
                   file_identity=physical, records=record_receipts(value))
    if len(events) > 1:
        require(events[1]['data'] == receipt)
    else:
        require(events[0]['data']['core_image_generator'] == generator(), 'initialization-unresolved')
        require(raw == core_image(value), 'initialization-unresolved')
    validate_core(str(directory.path / 'core.sqlite3'), value)
    return receipt


def _sources_event(events, value, core):
    if len(events) >= 3:
        saved = closed(events[2]['data'], {'catalog_sha256', 'verification_sha256'})
        require(saved['catalog_sha256'] == value['catalog']['sha256'])
        require(type(saved['verification_sha256']) is str and re.fullmatch('[0-9a-f]{64}', saved['verification_sha256']))
        if len(events) == 4:
            require(events[3]['data'] == dict(request_sha256=events[0]['data']['request_sha256'],
                core_sha256=core['sha256'], verification_sha256=saved['verification_sha256'],
                source_event_sha256=digest(encode(events[2]))))


def operate(command, directory, *, request_path=None, request_sha256=None):
    """All contexts close before return. No caller callbacks or injectable runtime."""
    require(command in {'create', 'review', 'status', 'query', 'audit', 'recover', 'run'}, 'invalid-request')
    if command == 'run':
        raise StudyError('execution-contract-not-frozen')
    incoming = None
    if command == 'create':
        raw = read_request(request_path)
        candidate = decode(raw, 'invalid-request')
        require(type(candidate) is dict, 'invalid-request')
        if candidate.get('schema') == 'auto-g16-direct-study-request/2':
            from ._fresh_model import request as fresh_request
            incoming = fresh_request(raw, request_sha256)
        else:
            incoming = request(raw, request_sha256)
    else:
        require(request_path is None and request_sha256 is None, 'invalid-request')
    with Directory(directory, write=command == 'create') as target:
        fresh = incoming is not None and incoming['schema'] == 'auto-g16-direct-study-request/2'
        if '0001-intent.json' in target.names():
            raw, _ = target.read('0001-intent.json', 2 * 1024 * 1024)
            first = decode(raw, 'initialization-unresolved', 2 * 1024 * 1024)
            require(type(first) is dict, 'initialization-unresolved')
            stored_fresh = first.get('schema') == 'auto-g16-direct-study-event/2'
            if command == 'create':
                require(fresh == stored_fresh, 'invalid-request')
            fresh = stored_fresh
        if fresh:
            from ._fresh_service import operate_locked
            return operate_locked(command, target, incoming, request_sha256)
        events = _events(target)
        if not events:
            require(not target.names(), 'initialization-unresolved')
            require(command == 'create', 'not-found')
            _append(target, events, dict(request=incoming, request_sha256=request_sha256,
                directory_chain=target.chain, identities=identities(incoming), core_image_generator=generator()))
        value = _intent(target, events[0])
        if command == 'create':
            require(incoming == value and request_sha256 == events[0]['data']['request_sha256'], 'invalid-request')
        core = _core(target, events, value)
        if command == 'create' and len(events) == 1:
            require(events[0]['data']['core_image_generator'] == generator(), 'initialization-unresolved')
            if core is None:
                target.publish('core.sqlite3', core_image(value))
                core = _core(target, events, value)
            _append(target, events, core)
        _sources_event(events, value, core)
        verified = None
        if command == 'create' or (len(events) == 4 and command in {'query', 'audit', 'recover'}):
            verified = _catalog.verify(value)
            verification_sha = digest(encode(verified))
            if len(events) >= 3:
                require(events[2]['data']['verification_sha256'] == verification_sha)
            if command == 'create' and len(events) == 2:
                _append(target, events, dict(catalog_sha256=value['catalog']['sha256'],
                                            verification_sha256=verification_sha))
            if command == 'create' and len(events) == 3:
                _append(target, events, dict(request_sha256=events[0]['data']['request_sha256'],
                    core_sha256=core['sha256'], verification_sha256=verification_sha,
                    source_event_sha256=digest(encode(events[2]))))
        target.seal({*(FILES[:len(events)]), *({'core.sqlite3'} if core else set())})
        state = 'local-created' if len(events) == 4 else 'initializing'
        result = dict(schema='auto-g16-direct-study-response/1', command=command,
            study_id=identities(value)['project_id'], request_sha256=events[0]['data']['request_sha256'],
            status='historical-reuse-complete' if verified is not None and len(events) == 4 else state,
            data=dict(local=dict(identities=identities(value), journal=[
                dict(sequence=e['sequence'], kind=e['kind'], sha256=digest(encode(e))) for e in events],
                core=core, execution_enabled=False, local_attempt_state='PLANNED' if core else None,
                management_state=state), source_verification=dict(
                    state='verified' if verified is not None else 'not-refreshed', data=verified)))
    return result
