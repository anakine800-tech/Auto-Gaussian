"""Export radius-rule components without assigning fragment chemistry.

Scientific scope adapted from propose_endpoint_components in
archive/skills/auto-g16-ts-irc/scripts/ts_irc.py; no archive imports.
"""

from contextlib import ExitStack
from hashlib import sha256
import json
import os
from pathlib import Path

from ag import __version__
from ag.irc_compare import _pairs, load_source
from ag.study import identifier, local_path
from ag.topology import fragments


NOTICE = '片段电荷与多重度需人确认；片段电子能之和不是反应自由能'
LIMITATIONS = [NOTICE, '不推断片段身份，也不决定后续应做分离物种计算还是复合物计算。',
               '半径规则只提供连通片段；不确定接触可能是弱键或配位，须人工审阅。',
               '只有一个片段时仅生成 JSON 和 Markdown 报告，不导出拆分 XYZ。']


def _path(path):
    path = Path(path).expanduser().absolute()
    return local_path(Path(path.anchor), path)


def _load(value, study):
    """Check lexical paths before load_source can resolve an Attempt symlink."""
    given = _path(value)
    root = _path(study) if study else None
    if given.is_file():
        source_path, attempt = given, None
        root = root or _path(Path.cwd())
        facts_path, facts_raw = None, None
    else:
        if given.is_dir():
            attempt = given
            if attempt.parent.name != 'attempts':
                raise ValueError('Attempt must be under a study attempts directory')
            root = root or attempt.parent.parent
            if attempt.parent != root / 'attempts':
                raise ValueError('Attempt does not belong to --study')
        else:
            root = root or _path(Path.cwd())
            attempt = _path(root / 'attempts' / identifier(value))
        _path(attempt / 'manifest.json')
        facts_path = _path(attempt / 'facts.json')
        facts_raw = facts_path.read_bytes()
        facts = json.loads(facts_raw)
        irc = facts.get('irc')
        name = irc.get('end_geometry') if isinstance(irc, dict) else facts.get('final_geometry')
        if (irc is not None and not isinstance(irc, dict)) or not isinstance(name, str) or (
                Path(name).name != name or name in {'.', '..'}):
            raise ValueError('Missing or invalid geometry in facts.json; run ag facts first')
        source_path = _path(attempt / name)
    raw = source_path.read_bytes()
    source = load_source(str(attempt or source_path), allow_xyz=attempt is None)
    # Hash, parsed coordinates and copied rows must describe the same evidence.
    if _path(source_path).read_bytes() != raw or (facts_path is not None and
                                               _path(facts_path).read_bytes() != facts_raw):
        raise ValueError('Source changed during reading; no output written')
    lines = raw.splitlines(keepends=True)
    start = next(i for i, line in enumerate(lines) if line.strip())
    rows = lines[start + 2:start + 2 + len(source['frame'].symbols)]
    name = source_path.relative_to(root).as_posix() if source_path.is_relative_to(root) else source_path.name
    metadata = dict(file=name, sha256=sha256(raw).hexdigest(),
                    geometry_kind=source['geometry_kind'], optimization_note=source['optimization_note'])
    if facts_raw is not None:
        metadata.update(attempt=attempt.name, facts_sha256=sha256(facts_raw).hexdigest())
    return root, source['frame'], rows, metadata


def analyze(frame):
    from rdkit import Chem

    result = fragments(frame)
    membership = {atom: i for i, component in enumerate(result['components'], 1)
                  for atom in component['atoms']}
    table = Chem.GetPeriodicTable()
    contacts, clashes = [], []
    for (i, j), evidence in _pairs(frame, Chem).items():
        elements = [frame.symbols[k - 1] for k in (i, j)]
        ratio = evidence['distance'] / sum(table.GetRcovalent(element) for element in elements)
        item = dict(atoms=[i, j], fragments=[membership[i], membership[j]], elements=elements,
                    distance=evidence['distance'], covalent_radius_ratio=ratio)
        if membership[i] != membership[j] and 1.2 <= ratio <= 1.5:
            contacts.append(item)
        elif ratio < 0.6:
            clashes.append(item)
    result.update(uncertain_contacts=contacts, clashes=clashes,
                  distance_rule=dict(bonded_ratio_interval='[0.6, 1.2)',
                                     uncertain_contact_ratio_interval='[1.2, 1.5]',
                                     clash_below_factor=0.6, radii='RDKit covalent radii'),
                  units=dict(distance='angstrom'),
                  atom_numbering='1-based original row order; no reordering, translation or rotation',
                  notice=NOTICE, limitations=LIMITATIONS, ag_version=__version__)
    return result


def markdown(result):
    lines = ['# 连通片段与坐标导出', '', f"片段数：{result['count']}", '',
             f"来源：{result['source']['file']}", f"SHA-256：{result['source']['sha256']}",
             result['source']['optimization_note'], '', result['rule'],
             '不确定接触半径比：[1.2, 1.5]；过近接触：< 0.6。共价半径来自 RDKit，距离单位 Å。',
             result['formula_note'], '原子编号从 1 开始，保留原始行序与坐标，不平移、不旋转。', '',
             '| 片段 | 分子式 | 原始原子编号 | XYZ |', '| --- | --- | --- | --- |']
    for i, component in enumerate(result['components'], 1):
        atoms = ', '.join(map(str, component['atoms']))
        lines.append(f"| {i} | {component['formula']} | {atoms} | {component['xyz_file'] or '不导出'} |")
    lines.extend(['', '## 跨片段不确定接触', ''])
    if result['uncertain_contacts']:
        lines.append('以下接触可能存在弱键或配位，不能直接视为独立物种：')
        for contact in result['uncertain_contacts']:
            lines.append(f"- 原子 {contact['atoms'][0]}–{contact['atoms'][1]}："
                         f"距离 {contact['distance']:.6g} Å，半径比 {contact['covalent_radius_ratio']:.6g}。")
    else:
        lines.append('未发现半径比 [1.2, 1.5] 的跨片段接触；这不是片段身份确认。')
    if result['clashes']:
        lines.extend(['', '存在半径比 < 0.6 的过近接触，须核对坐标；这些接触不作为确定相连边。',
                      '```json', json.dumps(result['clashes'], ensure_ascii=False, indent=2), '```'])
    lines.extend(['', '## 需人工确认', '', *('- ' + item for item in result['limitations'])])
    return '\n'.join(lines) + '\n'


def _write_outputs(parent, payloads):
    """Exclusive local outputs; roll back only files created by this invocation.

    Directory descriptors prevent a symlink swap redirecting writes outside
    analyses. Reserving all names first avoids a half-export after a collision.
    """
    with ExitStack() as stack:
        directory = os.open(parent.anchor, os.O_RDONLY | os.O_DIRECTORY)
        stack.callback(os.close, directory)
        for part in parent.parts[1:]:
            directory = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            stack.callback(os.close, directory)
        created = []
        try:
            with ExitStack() as files:
                handles = []
                for name, content in payloads.items():
                    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                 0o600, dir_fd=directory)
                    info = os.fstat(fd)
                    created.append((name, info.st_dev, info.st_ino))
                    handle = files.enter_context(os.fdopen(fd, 'wb'))
                    handles.append((handle, content))
                for handle, content in handles:
                    handle.write(content)
        except BaseException:
            for name, device, inode in reversed(created):
                try:
                    info = os.stat(name, dir_fd=directory, follow_symlinks=False)
                    if (info.st_dev, info.st_ino) == (device, inode):
                        os.unlink(name, dir_fd=directory)
                except FileNotFoundError:
                    pass
            raise


def run(args):
    root, frame, rows, source = _load(args.source, args.study)
    out = args.out.expanduser()
    if not out.is_absolute():
        out = root / out
    out = local_path(root / 'analyses', out)
    if out.suffix.lower() != '.json':
        raise ValueError('--out must be a new .json report under study analyses/')
    try:
        result = analyze(frame)
    except ImportError as exc:
        raise ValueError('fragments requires the local chemistry dependencies (RDKit)') from exc
    except RuntimeError as exc:
        raise ValueError('Cannot determine covalent radii for source elements') from exc
    result['source'] = source
    payloads = {}
    for i, component in enumerate(result['components'], 1):
        name = f'{out.stem}.frag{i}.xyz' if result['count'] > 1 else None
        component['xyz_file'] = name
        if name is not None:
            atoms = ','.join(map(str, component['atoms']))
            comment = f"source={json.dumps(source['file'], ensure_ascii=False)}; fragment={i}; original_atoms={atoms}"
            payloads[name] = (f"{len(component['atoms'])}\n{comment}\n".encode('utf-8') +
                              b''.join(rows[atom - 1].rstrip(b'\r\n') + b'\n' for atom in component['atoms']))
    content = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    payloads[out.name] = content.encode('utf-8')
    payloads[out.with_suffix('.md').name] = markdown(result).encode('utf-8')
    for name in payloads:
        target = local_path(root / 'analyses', out.parent / name)
        if target.exists():
            raise FileExistsError(f'Output already exists: {target.name}')
    _write_outputs(out.parent, payloads)
    if args.json:
        print(content, end='')
    else:
        print(f"片段数：{result['count']}；报告：{out}。{NOTICE}")
    return 0


def register(subparsers):
    parser = subparsers.add_parser('fragments', description=__doc__)
    parser.add_argument('source', help='Attempt ID/directory or one XYZ frame (angstrom)')
    parser.add_argument('--study', help='Study directory; inferred from Attempt directory, otherwise current directory')
    parser.add_argument('--out', type=Path, required=True, help='New JSON under study analyses/; relative to study')
    parser.add_argument('--json', action='store_true')
    parser.set_defaults(func=run)
