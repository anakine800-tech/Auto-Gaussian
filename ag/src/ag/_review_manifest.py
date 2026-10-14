"""Local, append-only inventories of the evidence presented for a signature."""
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

from ag.facts import ag_provenance
from ag.study import local_path


def _references(path, data):
    """Explicit Markdown paths and JSON analysis links; never infer from prose."""
    if path.name == 'facts.json' or path.suffix.lower() not in {'.md', '.json', '.txt'}:
        return []
    text = data.decode('utf-8')
    if path.suffix.lower() == '.json':
        value = json.loads(text)
        if isinstance(value, dict) and value.get('schema') == 'ag-review-manifest/1':
            return []  # A prior signed inventory is itself evidence, not a new selection.
        def strings(item, key=''):
            if isinstance(item, dict):
                for k, v in item.items():
                    yield from strings(v, k)
            elif isinstance(item, list):
                for v in item:
                    yield from strings(v, key)
            elif isinstance(item, str):
                yield item, key == 'thermo' or (key in {'path', 'file', 'source', 'definition'}
                                                and bool(Path(item).suffix))
        return list(strings(value))
    refs, plain = [], list(text)
    patterns = [r'!?\[[^\]\n]*\]\(\s*(?:<([^>]+)>|([^\s)]+))(?:\s+"[^"]*")?\s*\)',
                r'^\s*\[[^\]]+\]:\s*(?:<([^>]+)>|([^\s]+))',
                r'`([^`\n]+)`']
    for index, pattern in enumerate(patterns):
        for match in re.finditer(pattern, text, re.M):
            value = next(group for group in match.groups() if group is not None)
            explicit = index < 2 or bool(re.fullmatch(
                r'[^\n]+\.(?:json|md|csv|tsv|txt|xyz|pdf|png|svg|html)', value))
            refs.append((value, explicit))
            plain[match.start():match.end()] = ' ' * (match.end() - match.start())
    # Do not parse a second, truncated path from a quoted filename with spaces.
    refs += [(m.rstrip('.,;，。；'), True) for m in re.findall(
        r'(?<![\w/])((?:\.{1,2}/)*analyses/[^\s`<>"\]\)|，。；、]+)', ''.join(plain))]
    return refs


def _analysis_reference(root, source, value, explicit):
    if '\n' in value:
        return None
    url = urlsplit(value.strip())
    if url.scheme or url.netloc or not url.path:
        return None  # Remote references are not downloaded or signed as local files.
    value = unquote(url.path)
    if value.endswith('/'):
        return None
    relative = value.removeprefix('./')
    base = root if relative.startswith('analyses/') else source.parent
    raw = base / value
    # Check symlinks before lexical normalization; resolving first could hide one.
    for part in (raw, *raw.parents):
        if part.is_symlink():
            raise ValueError('Symbolic links are not allowed in evidence references')
    candidate = Path(os.path.abspath(raw))
    analyses = root / 'analyses'
    mentions_analysis = 'analyses' in Path(value).parts
    if not candidate.is_relative_to(root):
        if mentions_analysis or (source.is_relative_to(analyses) and explicit):
            raise ValueError(f'Evidence reference escapes study: {value}')
        return None
    if not candidate.is_relative_to(analyses):
        return None
    # JSON often contains labels, units, or log basenames. Only an existing
    # analysis file or explicit local path is an analysis-output reference.
    if not (explicit or mentions_analysis or candidate.is_file()):
        return None
    candidate = local_path(root, candidate)
    if not candidate.is_file():
        raise ValueError(f'Missing referenced analysis output: {candidate.relative_to(root)}')
    return candidate


def create(directory):
    root = Path(directory).expanduser().absolute()
    root = local_path(root, root)
    if not (root / 'study.md').is_file() or not (root / 'analyses').is_dir():
        raise ValueError('Expected a study directory with study.md and analyses/')
    pending = {root / 'study.md'}
    # Refuse linked subtrees rather than silently omitting their evidence.
    for path in root.rglob('*'):
        if path.is_symlink():
            raise ValueError('Symbolic links are not allowed in study evidence')
        if path.name in {'facts.json', 'review.md'}:
            if not path.is_file():
                raise ValueError(f'Evidence must be a regular file: {path.relative_to(root)}')
            pending.add(path)
    files = {}
    while pending:
        path = pending.pop()
        if path in files:
            continue
        data = local_path(root, path).read_bytes()
        files[path] = dict(path=path.relative_to(root).as_posix(), size=len(data),
                           sha256=sha256(data).hexdigest())
        for value, explicit in _references(path, data):
            referenced = _analysis_reference(root, path, value, explicit)
            if referenced is not None and referenced not in files:
                pending.add(referenced)
    # Catch evidence edited during collection before publishing a mixed inventory.
    for path, entry in files.items():
        if sha256(local_path(root, path).read_bytes()).hexdigest() != entry['sha256']:
            raise ValueError(f'Evidence changed while collecting: {entry["path"]}')
    now = datetime.now(timezone.utc)
    manifest = dict(schema='ag-review-manifest/1', created_at=now.isoformat(),
                    ag_provenance=ag_provenance(),
                    files=sorted(files.values(), key=lambda item: item['path']))
    name = 'review-manifest-' + now.strftime('%Y%m%dT%H%M%S%fZ') + '.json'
    destination = local_path(root, root / 'analyses' / name)
    content = (json.dumps(manifest, indent=2, ensure_ascii=False, allow_nan=False) + '\n').encode('utf-8')
    # xb is O_CREAT | O_EXCL: collisions never overwrite or retry another name.
    with destination.open('xb') as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    return dict(manifest=destination.relative_to(root).as_posix(),
                size=len(content), sha256=sha256(content).hexdigest(), **manifest)


def run(args):
    result = create(args.study)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0
