"""Study directory creation and lookup."""
from pathlib import Path
import re
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
        f'# {path.name}\n\n## 目标\n\n## 体系\n\n## 方法与依据\n\n## 计划与进度\n\n'
        '## 里程碑签字\n\n- 结构：待签字\n- 代表构象集合：待签字\n- 最终结果：待签字\n\n## 结论\n',
        encoding='utf-8')
    journal.append(path, 'init')
    return {'study_id': path.name}
