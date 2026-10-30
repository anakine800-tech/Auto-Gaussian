"""Study directory creation and lookup."""
from pathlib import Path
from hashlib import sha256
import os
import re
import stat
from uuid import uuid4
from ag import journal


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,79}', value):
        raise ValueError('IDs must contain only lowercase letters, digits and hyphens (max 80)')
    return value


def local_path(root, path):
    root, path = Path(root).absolute(), Path(path).absolute()
    if not path.is_relative_to(root) or '..' in path.parts:
        raise ValueError('Local path escapes studies_root')
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError('Symbolic links are not allowed in study paths')
    return path


def locate(cfg, name):
    root = Path(cfg['local']['studies_root'])
    path = Path(name)
    if not path.is_absolute():
        path = root / identifier(name)
    path = local_path(root, path)
    if path.parent != root:
        raise ValueError('Study must be an immediate child of studies_root')
    identifier(path.name)
    return path


def init(cfg, name):
    path = locate(cfg, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.mkdir()
    for child in ('structures', 'attempts', 'analyses', 'lessons'):
        (path / child).mkdir()
    (path / 'study.md').write_text(
        f'# {path.name}\n\n## 主会话\n\n<会话标识；其他会话只读>\n\n## 目标\n\n## 体系\n\n## 方法与依据\n\n## 计划与进度\n\n'
        '## 待你决定\n\n<事项、所需信息与证据、选项及影响；无则写无；每次结束前更新>\n\n## 里程碑签字\n\n- 结构：待签字\n- 代表构象集合：待签字\n- 最终结果：待签字\n\n## 结论\n',
        encoding='utf-8')
    journal.append(path, 'init')
    return {'study_id': path.name}


_SUMMARY_START = b'<!-- ag:autonomy-study-summary sha256='
_SUMMARY_END = b'<!-- /ag:autonomy-study-summary -->'


def _summary_stamp(info):
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError('Study summary inputs must be regular files with one link')
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _summary_render(original, snapshot):
    """Replace only the checksummed generated block; human text is opaque."""
    original.decode('utf-8')  # Do not normalize the human document's bytes/newlines.
    state = snapshot['state']
    plan_id = state['current_plan']
    plan_sha = state['plans'][plan_id]['sha256']

    def literal(value):
        # Indented code keeps source text from forging headings/signatures/markers.
        value = value.replace('\r\n', '\n').replace('\r', '\n')
        return '\n'.join('    ' + line for line in value.split('\n')) + '\n'

    body = ('## 自主目录链接\n\n'
            '[自主记录](autonomy/) · [状态](autonomy/state.json) · '
            '[追加日志](autonomy/journal.jsonl) · '
            f'[本轮计划](autonomy/plan-{plan_id}.json)\n\n'
            f'来源：事件 {snapshot["seq"]}，日志 `{snapshot["journal_sha256"]}`；'
            f'计划 `{plan_sha}`。\n\n'
            '## 待你决定（自主记录）\n\n')
    body += '\n'.join(literal(item) for item in state['pending']) if state['pending'] else '无。\n'
    body += ('\n## 结束摘要（自主记录）\n\n'
             '以下为当前 summary 的整理副本，待人确认；不代表研究完成、科学结论或里程碑签字。\n\n')
    body += literal(state['summary']) if state['summary'] else '尚未记录摘要。\n'
    raw = body.encode('utf-8')
    block = (_SUMMARY_START + sha256(raw).hexdigest().encode() + b' -->\n'
             + raw + _SUMMARY_END + b'\n')
    # Refuse damaged/duplicated markers and human edits inside a generated block.
    # Unmarked headings (including the study skeleton's pending section) survive.
    starts = list(re.finditer(rb'(?m)^<!-- ag:autonomy-study-summary[^\n]*', original))
    ends = list(re.finditer(rb'(?m)^<!-- /ag:autonomy-study-summary[^\n]*', original))
    if not starts and not ends:
        return original + (b'\n\n' if original and not original.endswith(b'\n') else b'\n') + block
    if len(starts) != 1 or len(ends) != 1:
        raise ValueError('Study summary markers are damaged or duplicated; preserve human edits')
    start, end = starts[0], ends[0]
    match = re.fullmatch(re.escape(_SUMMARY_START) + rb'([0-9a-f]{64}) -->', start.group())
    if (match is None or end.group() != _SUMMARY_END or start.end() >= end.start()
            or original[start.end():start.end()+1] != b'\n'):
        raise ValueError('Study summary markers are damaged; preserve human edits')
    previous = original[start.end()+1:end.start()]
    if sha256(previous).hexdigest().encode() != match[1]:
        raise ValueError('Generated study summary was edited; preserve human edits')
    stop = end.end() + (original[end.end():end.end()+1] == b'\n')
    return original[:start.start()] + block + original[stop:]


def publish_autonomy_summary(cfg, name, *, run_id, token, plan_sha256):
    """Publish the three fixed study.md sections from existing autonomy state.

    Large document IO/rendering/fsync stays outside the machine mutex. The final
    guard fences cooperating owners; metadata detects intervening editor saves.
    No state mutation, scientific signature, arbitrary text/path or remote IO.
    Failed staging is retained; replacement/fsync errors never trigger rollback.
    """
    from ag import autonomy as a, _autonomy_store as disk

    root = locate(cfg, name)
    rootfd = disk.directory(root)
    documentfd = None
    try:
        identity = os.fstat(rootfd)
        directory_identity = (identity.st_dev, identity.st_ino)
        # Pin the source directory and every authoritative file across rendering.
        with disk.locked(cfg, name) as store:
            source_dir = os.fstat(store.fd)
            source_identity = (source_dir.st_dev, source_dir.st_ino)
            source_names = ['store.lock', 'state.json', 'journal.jsonl'] + [
                key for key in os.listdir(store.fd) if re.fullmatch(r'plan-[a-z0-9-]+\.json', key)]
            source_stamps = {key: _summary_stamp(os.stat(key, dir_fd=store.fd,
                             follow_symlinks=False)) for key in source_names}
            snapshot, _ = a.load(store)
            a.text(token, 'Observation owner token')
            a._sha256(plan_sha256, 'Expected immutable plan')
            a.eligible(snapshot['state'], run_id, sha256(token.encode()).hexdigest(),
                       a.versions(), a.now(), 'organize', plan_sha256)
            for key, stamp in source_stamps.items():
                if _summary_stamp(os.stat(key, dir_fd=store.fd, follow_symlinks=False)) != stamp:
                    raise ValueError('Autonomy source changed during reading')

        documentfd = disk.Store(rootfd).open('study.md', os.O_RDONLY)
        before = _summary_stamp(os.fstat(documentfd))
        with os.fdopen(os.dup(documentfd), 'rb') as handle:
            original = handle.read()
        if _summary_stamp(os.fstat(documentfd)) != before:
            raise ValueError('Study document changed during reading')
        candidate = _summary_render(original, snapshot)
        changed = candidate != original
        result = dict(changed=changed, study_sha256=sha256(candidate).hexdigest(),
                      source_seq=snapshot['seq'], source_journal_sha256=snapshot['journal_sha256'],
                      plan_sha256=plan_sha256)
        staged = None
        if changed:
            staged = '.autonomy-study-' + uuid4().hex + '.tmp'
            disk.Store(rootfd).exclusive(staged, candidate)
            candidate_stamp = _summary_stamp(os.stat(staged, dir_fd=rootfd, follow_symlinks=False))
            if (disk.Store(rootfd).read(staged) != candidate
                    or _summary_stamp(os.stat(staged, dir_fd=rootfd,
                                              follow_symlinks=False)) != candidate_stamp):
                raise ValueError('Staged study summary changed during preparation')

        with a.observation_publication_guard(cfg, name, run_id, token, action='organize',
                plan_sha256=plan_sha256,
                expected_source=(snapshot['seq'], snapshot['journal_sha256'])) as current:
            current_versions = a.versions()
            currentfd = disk.directory(root)
            try:
                info = os.fstat(currentfd)
                if (info.st_dev, info.st_ino) != directory_identity:
                    raise ValueError('Study directory changed before publication')
                sourcefd = os.open('autonomy', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                   dir_fd=currentfd)
                try:
                    info = os.fstat(sourcefd)
                    if (info.st_dev, info.st_ino) != source_identity:
                        raise ValueError('Autonomy directory changed before publication')
                    for key, stamp in source_stamps.items():
                        if _summary_stamp(os.stat(key, dir_fd=sourcefd, follow_symlinks=False)) != stamp:
                            raise ValueError('Autonomy source changed before publication')
                finally:
                    os.close(sourcefd)
                if changed and _summary_stamp(os.stat(staged, dir_fd=currentfd,
                                                     follow_symlinks=False)) != candidate_stamp:
                    raise ValueError('Staged study summary changed before publication')
                # Directory/source checks must not carry an owner beyond its deadline.
                at = a.now()
                if at < current['updated_at']:
                    raise ValueError('Autonomy clock moved backwards')
                a.eligible(current, run_id, sha256(token.encode()).hexdigest(),
                           current_versions, at, 'organize', plan_sha256)
                if (before != _summary_stamp(os.fstat(documentfd))
                        or before != _summary_stamp(os.stat('study.md', dir_fd=currentfd,
                                                           follow_symlinks=False))):
                    raise ValueError('Study document changed before publication')
                if changed:
                    try:
                        os.replace(staged, 'study.md', src_dir_fd=currentfd, dst_dir_fd=currentfd)
                        os.fsync(currentfd)
                    except OSError as exc:
                        raise OSError('Study summary publication may have occurred; inspect study.md '
                                      'before another call. Autonomy state was not changed.') from exc
            finally:
                os.close(currentfd)
        return result
    finally:
        if documentfd is not None:
            os.close(documentfd)
        os.close(rootfd)
