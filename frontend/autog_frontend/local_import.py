"""Explicit offline local-folder import. No Core writes, remote access or execution.

Publishes one new immutable batch directory. The caller separately selects its
profile for the viewer. Original files, previous indexes and reviews stay intact.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
import uuid

from auto_g16.result import GaussianJobParser, OutputArtifact, OutputEnvelope
from .archive import AUTHORITY, LOCAL_SCHEMA, LOG_LIMIT, PARSE_LIMIT, LIMIT, ArchiveQuery, read_pinned, _fingerprint, validate_index
from .archive_import import plain
from .archive_parser import GaussianArchiveParser
from .details import full_result
from .vibrations import build_modes

SMALL_SUFFIXES = {'.gjf', '.com', '.json', '.xyz', '.mol', '.pbs', '.sha256', '.txt', '.inp'}


def stable_bytes(path, limit):
    if not path.is_absolute() or path.resolve(strict=True) != path:
        raise ValueError('noncanonical or linked source')
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
        raise ValueError('unsupported source type or size')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as f:
        if _fingerprint(before) != _fingerprint(os.fstat(f.fileno())):
            raise ValueError('source changed before read')
        raw = f.read(limit + 1)
        if (_fingerprint(before) != _fingerprint(os.fstat(f.fileno()))
                or _fingerprint(before) != _fingerprint(path.lstat()) or len(raw) != before.st_size):
            raise ValueError('source changed during read')
    return raw, before


def parse_log(raw, name, title, timestamp):
    digest = sha256(raw).hexdigest(); identity = 'archive-' + digest
    if len(raw) > LOG_LIMIT or not re.fullmatch(r'[A-Za-z0-9_.-]{1,200}', name) or name in ('.', '..'):
        raise ValueError('unsupported log name or size')
    artifact = dict(role='log', logical_name=name, sha256=digest, size_bytes=len(raw))
    envelope = OutputEnvelope(attempt_id=identity, input_binding_observation_id='archive-unbound-input',
        execution_snapshot_id='archive-no-execution-snapshot', capture_source_id='archive-local-import',
        capture_sequence=1, capture_status='captured', capture_completeness='complete',
        artifacts=(OutputArtifact(artifact_kind='gaussian-log', logical_name=name, sha256=digest, size_bytes=len(raw)),),
        capture_manifest_sha256=sha256(json.dumps(artifact, sort_keys=True).encode()).hexdigest(), captured_at_utc=timestamp)
    outcome = GaussianArchiveParser().parse(envelope, {name: raw}); f = plain(outcome.facts)
    summary = None
    if outcome.parse_status.value == 'parsed':
        n = f['frequency_count']
        summary = dict(termination=f['program_status'], normal_count=f['normal_termination_count'],
            error_count=f['error_termination_count'], energy_hartree=f['final_energy_hartree'],
            optimization=f['optimization_completed_marker'], stationary_point=f['stationary_point_marker'],
            frequency_count=n or None, imaginary_count=f['imaginary_frequency_count'] if n else None)
    record = dict(archive_id=identity, title=title[:512], source_kind='local_log_archive',
        source_location='Mac 本地文件夹导入', captured_at=timestamp, artifacts=[artifact], input=None,
        legacy_metadata=None, parser=dict(name=outcome.parser_name, version=outcome.parser_version,
        status=outcome.parse_status.value, diagnostics=list(outcome.diagnostics)), summary=summary, authority=dict(AUTHORITY))
    validate_index(dict(schema=LOCAL_SCHEMA, records=[record]))
    return record, plain(outcome.payload()), outcome


def import_folder(source, destination, previous_profile):
    if source.resolve(strict=True) != source or not source.is_dir():
        raise ValueError('explicit canonical source directory required')
    if not destination.is_absolute() or destination.exists() or source == destination or source in destination.parents:
        raise ValueError('new destination outside source required')
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.parent.resolve() != destination.parent:
        raise ValueError('linked destination parent')
    stage = destination.parent / ('.pending-' + uuid.uuid4().hex); stage.mkdir()
    timestamp = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    profile = json.loads(previous_profile.read_bytes())
    previous = ArchiveQuery(Path(profile['archive_index']), profile['archive_sha256'])._read()
    catalog = json.loads(read_pinned(Path(profile['evidence_catalog']), profile['evidence_sha256']))
    records = {r['archive_id']: r for r in previous['records']}
    entries = {(e['kind'], e['id']): e for e in catalog['entries']}
    manifest = []; failures = []; seen = set(); parsed_count = Counter(); mode_count = 0

    def save(name, raw, limit=LIMIT):
        if len(raw) > limit: raise ValueError('derived artifact exceeds limit: ' + name)
        path = stage / name; path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            if path.read_bytes() != raw: raise ValueError('content-address collision')
        else:
            with path.open('xb') as f: f.write(raw)
        return dict(path=str(destination / name), sha256=sha256(raw).hexdigest(), size_bytes=len(raw))
    def save_json(name, value, limit=LIMIT):
        return save(name, json.dumps(value, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(',', ':')).encode(), limit)

    for base, dirs, names in os.walk(source, followlinks=False):
        dirs.sort()
        for name in list(dirs):
            p = Path(base) / name
            if p.is_symlink():
                manifest.append(dict(relative_path=str(p.relative_to(source)), status='excluded-link')); dirs.remove(name)
        for name in sorted(names):
            p = Path(base) / name; relative = str(p.relative_to(source)); st = p.lstat()
            item = dict(relative_path=relative, size_bytes=st.st_size, mtime_ns=st.st_mtime_ns); manifest.append(item)
            if not stat.S_ISREG(st.st_mode): item['status'] = 'excluded-nonregular'; continue
            suffix = p.suffix.lower(); is_log = suffix in ('.log', '.out')
            if st.st_size == 0: item['status'] = 'empty-file'; continue
            if not is_log and suffix not in SMALL_SUFFIXES:
                item['status'] = 'retained-at-source-not-copied'; continue
            try:
                raw, _ = stable_bytes(p, LOG_LIMIT if is_log else LIMIT)
                h = sha256(raw).hexdigest(); item['sha256'] = h
                item['artifact'] = save('artifacts/' + h, raw, LOG_LIMIT)
                item['status'] = 'copied'
                if not is_log: continue
                identity = 'archive-' + h; item['archive_id'] = identity
                if identity in seen: item['status'] = 'duplicate-log'; continue
                seen.add(identity)
                if identity in records: item['status'] = 'already-indexed'; continue
                title = relative.split('/')[0] + ' · ' + p.stem
                record, payload, outcome = parse_log(raw, p.name, title, timestamp)
                parsed_ref = save_json('parsed/' + h + '.json', payload, PARSE_LIMIT)
                entry = dict(kind='archive', id=identity, log=item['artifact'], parse_outcome=parsed_ref)
                if record['summary'] and record['summary']['frequency_count']:
                    try:
                        modes = build_modes(dict(kind='archive', id=identity, result=full_result(outcome)), raw)
                        entry['vibrations'] = save_json('modes/' + h + '.json', modes); mode_count += 1
                    except (ValueError, KeyError, TypeError) as e:
                        item['mode_status'] = 'unavailable: ' + str(e)
                records[identity] = record; entries[('archive', identity)] = entry
                parsed_count[record['parser']['status']] += 1; item['status'] = 'indexed'
                print(json.dumps(dict(indexed=len(records), status=record['parser']['status'])), flush=True)
            except (ValueError, OSError, KeyError, TypeError) as e:
                item['status'] = 'failed'; item['reason'] = str(e); failures.append(relative)
    from .history_links import build_links
    def staged_read(ref):
        p=Path(ref['path']);raw=(stage/p.relative_to(destination)).read_bytes()
        if sha256(raw).hexdigest()!=ref['sha256']:raise ValueError('staged artifact changed')
        return raw
    for identity,packet in build_links(manifest,staged_read).items():
        entries[('archive',identity)]['history_links']=save_json('history/'+identity+'.json',packet)
    from .enrich import additions
    fresh=[r for key,r in records.items() if key not in {old['archive_id'] for old in previous['records']}]
    def read_staged(ref,limit=LIMIT):return staged_read(ref)
    additions(fresh,entries,manifest,source.name,save_json,read_staged)
    index = dict(schema=LOCAL_SCHEMA, records=list(records.values())); validate_index(index)
    index_ref = save_json('archive-index.json', index)
    catalog_ref = save_json('evidence-catalog.json', dict(schema='auto-g16-local-evidence-catalog/1', entries=list(entries.values())))
    if len(entries) > 1000: raise ValueError('catalog entry capacity exceeded')
    profile.update(archive_index=index_ref['path'], archive_sha256=index_ref['sha256'], evidence_catalog=catalog_ref['path'], evidence_sha256=catalog_ref['sha256'])
    save_json('profile.json', profile)
    report = dict(schema='autog-local-import-report/1', source=str(source), destination=str(destination), imported_at=timestamp,
        files=manifest, failures=failures, unique_nonempty_logs=len(seen), new_parser_statuses=dict(parsed_count),
        indexed_archives=len(records), modes_prepared=mode_count, original_files_modified=False,
        scientific_acceptance='unavailable', checkpoints='retained-at-source-not-copied')
    save_json('import-report.json', report, PARSE_LIMIT)
    # Never replace an existing batch; one successful rename publishes all files.
    if destination.exists(): raise ValueError('destination appeared during import')
    stage.rename(destination)
    return {k: v for k, v in report.items() if k not in ('files', 'source', 'destination')}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', required=True, type=Path); p.add_argument('--destination', required=True, type=Path)
    p.add_argument('--previous-profile', required=True, type=Path)
    a = p.parse_args(); print(json.dumps(import_folder(a.source, a.destination, a.previous_profile), ensure_ascii=False))
