"""Local, append-only inventories of the evidence presented for a signature."""
from datetime import datetime, timezone
from hashlib import sha256
import errno
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlsplit

from ag.facts import ag_provenance
from ag.study import local_path


def _references(path, data, *, root=None):
    """Explicit Markdown paths and JSON analysis links; never infer from prose."""
    if path.name == 'facts.json' or path.suffix.lower() not in {'.md', '.json', '.txt'}:
        return []
    text = data.decode('utf-8')
    if path.suffix.lower() == '.json':
        value = json.loads(text)
        if isinstance(value, dict) and value.get('schema') == 'ag-review-manifest/1':
            return []  # A prior signed inventory is itself evidence, not a new selection.
        def strings(item, key='', field='$'):
            if isinstance(item, dict):
                for k, v in item.items():
                    yield from strings(v, k, field + '[' + json.dumps(k, ensure_ascii=False) + ']')
            elif isinstance(item, list):
                for index, v in enumerate(item):
                    yield from strings(v, key, f'{field}[{index}]')
            elif isinstance(item, str):
                yield item, (key in {'thermo', 'frozen_evidence'}
                             or (key in {'path', 'file', 'source', 'definition'}
                                 and bool(Path(item).suffix))), field, key
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
            location = f'line {text.count(chr(10), 0, match.start()) + 1}'
            plain[match.start():match.end()] = ' ' * (match.end() - match.start())
            if index == 2 and any(char.isspace() for char in value):
                # Keep existing quoted evidence (including spaced names) under
                # the same source/root and safety rules. A missing code span is
                # prose; never extract an analyses/ argument from its command.
                reference = _analysis_reference(root or path.parent, path, value, explicit,
                                                location, analysis_names=set())
                if reference is not None and reference[0] is None and reference[1] in {
                        'missing', 'unqualified_name'}:
                    continue
            refs.append((value, explicit, location, ''))
    # Quoted paths stay intact; ASCII-only bare paths stop before surrounding prose.
    refs += [(match.group(1).rstrip('.,;'), True,
              f'line {text.count(chr(10), 0, match.start()) + 1}', '') for match in re.finditer(
        r'(?<![A-Za-z0-9_/.])((?:\.{1,2}/)*analyses/[A-Za-z0-9._/-]+)', ''.join(plain))]
    return refs


class UnresolvedReferences(ValueError):
    """The complete list needs human review before an inventory can be written."""

    def __init__(self, references, outside_analyses, unqualified_names):
        self.references = references
        self.outside_analyses = outside_analyses
        self.unqualified_names = unqualified_names
        super().__init__('Unresolved evidence references; 核对后加 --accept-unresolved 重新运行')


def _analysis_reference(root, source, value, explicit, field='reference', key='', analysis_names=None):
    def invalid(reason):
        if explicit:
            raise ValueError(f'Invalid evidence reference in {source.relative_to(root)} '
                             f'(field {field}): {reason}') from None
        return None

    def unresolved(reason):
        if key in {'thermo', 'frozen_evidence'}:
            raise ValueError(f'Invalid evidence reference in {source.relative_to(root)} '
                             f'(field {field}): {reason}')
        return None, reason

    if '\n' in value or '\r' in value:
        return invalid('path contains a newline')
    url = urlsplit(value.strip())
    if url.scheme or url.netloc or not url.path:
        return None  # Remote references are not downloaded or signed as local files.
    value = unquote(url.path)
    if '\n' in value or '\r' in value:
        return invalid('path contains a newline')
    if any(len(part.encode('utf-8')) > 255 for part in value.split('/')):
        return invalid('path component exceeds 255 bytes')
    try:
        relative = value.removeprefix('./')
        is_text = source.suffix.lower() in {'.md', '.txt'}
        strict = source.suffix.lower() == '.json' and key in {'thermo', 'frozen_evidence'}
        # Retain T62's explicit text analyses/ prefix; ordinary JSON uses the
        # source/root ambiguity check approved for T64.
        base = root if ((is_text and value.startswith('analyses/')) or
                        (strict and relative.startswith('analyses/'))) else source.parent
        analyses = root / 'analyses'
        mentions_analysis = 'analyses' in Path(value).parts

        def checked(base):
            raw = base / value
            # Classify lexical escapes without probing paths outside this study.
            candidate = Path(os.path.abspath(raw))
            if not candidate.is_relative_to(root):
                return candidate
            # Keep raw components: normalizing a link/.. first could hide a link.
            for part in (raw, *raw.parents):
                if Path(os.path.abspath(part)).is_relative_to(root) and part.is_symlink():
                    raise ValueError('Symbolic links are not allowed in evidence references')
            return candidate

        candidate = checked(base)
        if not candidate.is_relative_to(root):
            return unresolved('escapes_study')
        resolved_from = None
        # Ordinary JSON follows the same source/root resolution as text. Explicit
        # ./ and ../ retain their source-relative meaning; strict pointers keep
        # their original base and never gain this fallback.
        if not strict and not Path(value).is_absolute() and not value.startswith(('./', '../')):
            fallback = checked(root)
            if fallback != candidate and fallback.exists():
                if candidate.exists():
                    if not candidate.samefile(fallback):
                        raise ValueError(f'Ambiguous evidence reference in {source.relative_to(root)} '
                                         f'(field {field}): {value}')
                else:
                    candidate = fallback
                    resolved_from = 'study_root'
        # Keep ordinary JSON labels out of the reference lists.
        if not (explicit or mentions_analysis or
                (candidate.is_relative_to(analyses) and candidate.is_file())):
            return None
        candidate = local_path(root, candidate)
        if not candidate.exists():
            if not strict and '/' not in value:
                if analysis_names is None:
                    analysis_names = {p.name for p in analyses.rglob('*') if p.is_file()}
                if value not in analysis_names:
                    return None, 'unqualified_name'
            return unresolved('missing')
        if not candidate.is_relative_to(analyses):
            return (candidate, resolved_from) if explicit else None
        if not (candidate.is_file() or candidate.is_dir()):
            raise ValueError(f'Evidence must be a regular file: {candidate.relative_to(root)}')
        return candidate, resolved_from
    except OSError as exc:
        if exc.errno != errno.ENAMETOOLONG:
            raise
        return invalid('path exceeds the filesystem length limit (ENAMETOOLONG)')


def create(directory, *, accept_unresolved=False):
    root = Path(directory).expanduser().absolute()
    root = local_path(root, root)
    if not (root / 'study.md').is_file() or not (root / 'analyses').is_dir():
        raise ValueError('Expected a study directory with study.md and analyses/')
    pending = {root / 'study.md'}
    analysis_names = set()
    # Refuse linked subtrees rather than silently omitting their evidence.
    for path in root.rglob('*'):
        if path.is_symlink():
            raise ValueError('Symbolic links are not allowed in study evidence')
        if path.is_relative_to(root / 'analyses') and path.is_file():
            analysis_names.add(path.name)
        if path.name in {'facts.json', 'review.md'}:
            if not path.is_file():
                raise ValueError(f'Evidence must be a regular file: {path.relative_to(root)}')
            pending.add(path)
    files, expanded_from, resolved_from = {}, {}, {}
    unresolved_references, referenced_outside_analyses, unqualified_names = [], [], []
    while pending:
        path = min(pending)
        pending.remove(path)
        if path in files:
            continue
        data = local_path(root, path).read_bytes()
        files[path] = dict(path=path.relative_to(root).as_posix(), size=len(data),
                           sha256=sha256(data).hexdigest())
        for value, explicit, field, key in _references(path, data, root=root):
            reference = _analysis_reference(root, path, value, explicit, field, key, analysis_names)
            if reference is None:
                continue
            referenced, origin = reference
            if referenced is None:
                # Preserve the original spelling/anchor, but never disclose absolute paths.
                absolute = Path(unquote(urlsplit(value.strip()).path)).is_absolute()
                entry = dict(source=path.relative_to(root).as_posix(), location=field,
                             value='<absolute path>' if absolute else value)
                if origin == 'unqualified_name':
                    unqualified_names.append(entry)
                else:
                    unresolved_references.append(dict(**entry, reason=origin))
                continue
            if not referenced.is_relative_to(root / 'analyses'):
                entry = dict(source=path.relative_to(root).as_posix(), location=field,
                             path=referenced.relative_to(root).as_posix())
                if origin:
                    entry['resolved_from'] = origin
                referenced_outside_analyses.append(entry)
                continue
            if referenced.is_dir():
                members = []
                for child in sorted(referenced.rglob('*')):
                    child = local_path(root, child)
                    if child.is_dir():
                        continue
                    if not child.is_file():
                        raise ValueError(f'Evidence must be a regular file: {child.relative_to(root)}')
                    members.append(child)
                if not members:
                    raise ValueError(f'Empty referenced analysis directory: {referenced.relative_to(root)}')
                for child in members:
                    expanded_from.setdefault(child, set()).add(referenced.relative_to(root).as_posix())
                    if origin:
                        resolved_from[child] = origin
                    pending.add(child)
            else:
                if origin:
                    resolved_from[referenced] = origin
                pending.add(referenced)
    # Catch evidence edited during collection before publishing a mixed inventory.
    for path, entry in files.items():
        if path in expanded_from:
            entry['expanded_from'] = sorted(expanded_from[path])
        if path in resolved_from:
            entry['resolved_from'] = resolved_from[path]
        if sha256(local_path(root, path).read_bytes()).hexdigest() != entry['sha256']:
            raise ValueError(f'Evidence changed while collecting: {entry["path"]}')
    if unresolved_references and not accept_unresolved:
        raise UnresolvedReferences(unresolved_references, referenced_outside_analyses, unqualified_names)
    now = datetime.now(timezone.utc)
    manifest = dict(schema='ag-review-manifest/1', created_at=now.isoformat(),
                    ag_provenance=ag_provenance(),
                    files=sorted(files.values(), key=lambda item: item['path']))
    if unqualified_names:
        manifest['unqualified_names'] = unqualified_names
    if referenced_outside_analyses:
        manifest['referenced_outside_analyses'] = referenced_outside_analyses
    if unresolved_references:
        manifest.update(unresolved_references=unresolved_references,
                        unresolved_accepted=True, unresolved_accepted_at=now.isoformat())
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
    directory = args.study or args.directory
    if not directory or (args.study and args.directory):
        raise ValueError('Specify one study directory: <study> or --study <study>')
    try:
        result = create(directory, accept_unresolved=args.accept_unresolved)
    except UnresolvedReferences as exc:
        result = dict(error=str(exc), exit_code=4, unresolved_references=exc.references)
        if exc.unqualified_names:
            result['unqualified_names'] = exc.unqualified_names
        if exc.outside_analyses:
            result['referenced_outside_analyses'] = exc.outside_analyses
        code = 4
    else:
        code = 0
    # Information-only entries remain in the saved inventory; the terminal
    # reports counts so source-file descriptions do not flood the review list.
    for key, label in [('referenced_outside_analyses', 'outside_analyses'),
                       ('unqualified_names', 'unqualified_name')]:
        entries = result.pop(key, [])
        if entries:
            result[label + '_count'] = len(entries)
            print(f'{label}: {len(entries)} 条（仅供参考，无需确认）', file=sys.stderr)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return code
