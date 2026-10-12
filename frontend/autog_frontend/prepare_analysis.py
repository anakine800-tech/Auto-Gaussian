"""Explicit offline sidecar preparation; creates a new profile, preserves sources."""
import argparse
import json
from pathlib import Path
from hashlib import sha256
from .archive import LOG_LIMIT, LIMIT, read_pinned
from .details import document
from .calculation_analysis import extract


def prepare(profile_path, destination):
    if not destination.is_absolute() or destination.exists() or destination.parent.resolve() != destination.parent:
        raise ValueError('new canonical destination required')
    profile = json.loads(profile_path.read_bytes())
    catalog = json.loads(read_pinned(Path(profile['evidence_catalog']), profile['evidence_sha256']))
    index = json.loads(read_pinned(Path(profile['archive_index']), profile['archive_sha256']))
    names = {r['archive_id']: next(a['logical_name'] for a in r['artifacts'] if a['role'] == 'log') for r in index['records']}
    destination.mkdir()
    prepared, failures = 0, []
    for entry in catalog['entries']:
        if 'log' not in entry:
            continue
        try:
            if entry['kind'] == 'archive':
                name = names[entry['id']]
            else:
                from .archive import ArchiveQuery
                from .details import DetailQuery
                query = DetailQuery(profile['database'], ArchiveQuery(Path(profile['archive_index']), profile['archive_sha256']),
                                    Path(profile['evidence_catalog']), profile['evidence_sha256'])
                name = query.get_details('attempt', entry['id'])['result']['source']['artifact']['logical_name']
            packet = extract(document(entry['log'], limit=LOG_LIMIT), name)
            raw = json.dumps(packet, sort_keys=True, allow_nan=False).encode()
            if len(raw) > LIMIT:
                raise ValueError('analysis exceeds sidecar limit')
            file = destination / (sha256((entry['kind'] + ':' + entry['id']).encode()).hexdigest() + '.json')
            file.write_bytes(raw)
            entry['analysis'] = dict(path=str(file), sha256=sha256(raw).hexdigest(), size_bytes=len(raw))
            prepared += 1
        except (ValueError, KeyError, TypeError, OSError):
            failures.append(dict(kind=entry['kind'], id=entry['id'], reason='analysis-preparation-failed'))
    raw = json.dumps(catalog, sort_keys=True).encode()
    if len(raw) > LIMIT:
        raise ValueError('catalog too large')
    catalog_path = destination / 'catalog.json'
    catalog_path.write_bytes(raw)
    (destination / 'profile.json').write_text(json.dumps(dict(profile, evidence_catalog=str(catalog_path), evidence_sha256=sha256(raw).hexdigest()), indent=2))
    report = dict(prepared=prepared, failures=failures, source_profile_sha256=sha256(profile_path.read_bytes()).hexdigest())
    (destination / 'report.json').write_text(json.dumps(report, indent=2))
    return report


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--profile', type=Path, required=True)
    p.add_argument('--destination', type=Path, required=True)
    args = p.parse_args()
    print(json.dumps(prepare(args.profile, args.destination)))
