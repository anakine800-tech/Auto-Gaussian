"""Local parent declaration and submit-time checks for the single chk attachment."""
from hashlib import sha256
import math
import re
from ag import attempt, remote, state, submission
from ag.config import for_manifest


def _parent(cfg, parent_id, source_name):
    path = attempt.find(cfg, parent_id)
    manifest = attempt.read_manifest(path)
    current = state.read(path)
    from ag.fetch import incomplete_record
    incomplete = incomplete_record(path)
    if (current['state'] not in ('finished', 'fetched')
            and not (current['state'] == 'interrupted' and incomplete is not None)):
        raise ValueError('Parent chk requires a finished or fetched Attempt')
    if manifest.get('cluster', 'default') != cfg.get('_cluster', 'default'):
        raise ValueError('Parent and child must belong to the same cluster')
    cfg = for_manifest(cfg, manifest)
    job = submission.verified_job(path, manifest, current)
    remote.attempt_dir(cfg, manifest)
    remote.filename(source_name)
    if manifest['template'] != 'gaussian':
        raise ValueError('Parent chk must come from a Gaussian Attempt')
    # Older manifests bind %chk through their hashed Gaussian input, not a
    # separate checkpoint field. Never trust an unbound filename in science.
    inputs = [r for r in manifest['inputs'] if r['name'] not in ('job.pbs', 'job.slurm')]
    if len(inputs) != 1:
        raise ValueError('Expected one declared parent Gaussian input')
    record = inputs[0]
    source = path / 'inputs' / remote.filename(record['name'])
    if source.is_symlink() or not source.is_file():
        raise ValueError('Parent input must be a regular file')
    data = source.read_bytes()
    if (len(data), sha256(data).hexdigest()) != (record['size'], record['sha256']):
        raise ValueError('Parent input differs from its manifest')
    link0 = data.decode().split('#', 1)[0]
    chk = re.findall(r'^%chk\s*=\s*([^\r\n]+)', link0, re.I | re.M)
    if len(chk) != 1 or chk[0].strip() != source_name or not source_name.endswith('.chk'):
        raise ValueError('Source filename differs from parent manifest %chk')
    return manifest, job


def declare(cfg, study, template, parents, value):
    if template != 'gaussian':
        raise ValueError('--parent-chk requires the gaussian template')
    parent_id, separator, name = value.partition(':')
    if not separator or parent_id not in [p['attempt_id'] for p in parents]:
        raise ValueError('--parent-chk must also appear in --parent')
    parent, _ = _parent(cfg, parent_id, name)
    if parent['study_id'] != study.name:
        raise ValueError('Parent must belong to this study')
    return dict(attempt_id=parent_id, source_name=name, target_name='parent.chk',
                cluster=parent.get('cluster', 'default'))


def validate_force_constant_frame(cfg, attachment, science):
    """L3: a rotated equivalent structure does not match the stored Hessian frame."""
    if not re.search(r'\b(?:rcfc|readfc|readcartesianfc)\b', science['route'], re.I):
        return
    from ag.geometry import read_xyz, finite_number
    from cclib.parser.utils import PeriodicTable

    hint = 'rcfc 读到的力常数是父作业输入取向下的，请改用 final_input.xyz 的坐标，或者改用 calcfc'
    # XYZ is in angstrom; do not silently compare Bohr coordinates as angstrom.
    if re.search(r'\bunits?\b', science['route'], re.I):
        raise ValueError('rcfc 坐标比较要求默认 Å 单位，请移除 Units 选项；' + hint)
    path = attempt.find(cfg, attachment['attempt_id'])
    manifest = attempt.read_manifest(path)
    # declare() already checked these input bytes against the parent manifest.
    record = next(r for r in manifest['inputs'] if r['name'] not in ('job.pbs', 'job.slurm'))
    text = (path / 'inputs' / record['name']).read_text()
    route = re.search(r'(?ms)^[ \t]*(#.*?)\n\s*\n', text)
    nosymm = route is not None and re.search(r'\bnosymm(?:etry)?\b', route[1], re.I)
    names = ['final_input.xyz', 'final.xyz'] if nosymm else ['final_input.xyz']
    references = []
    for name in names:
        target = path / name
        if target.is_symlink():
            raise ValueError(f'父作业 {name} 不能是符号链接')
        if not target.exists():
            continue
        frames = read_xyz(target)
        if len(frames) != 1:
            raise ValueError(f'父作业 {name} 必须只有一个几何')
        references.append(frames[0])
    if not references:
        raise ValueError('缺少父作业取向坐标，请先运行 ag facts；' + hint)
    table = PeriodicTable().element
    for structure in science.get('structures', [science]):
        symbols, coordinates = [], []
        for row in structure['geometry'].splitlines():
            symbol, *xyz = row.split()
            if symbol.isdigit() and 0 < int(symbol) < len(table):
                symbol = table[int(symbol)]
            symbols.append(symbol)
            coordinates.append(tuple(finite_number(x) for x in xyz))
        # Fixed atom rows, no rotation, translation, permutation or RMSD dilution.
        if not any(tuple(symbols) == frame.symbols and all(
                math.dist(a, b) <= 1e-4 for a, b in zip(coordinates, frame.coordinates))
                   for frame in references):
            raise ValueError(hint)


def resolve(cfg, child, jobs=None):
    cfg = for_manifest(cfg, child)
    attachment = child['parent_chk']
    if set(attachment) != {'attempt_id', 'source_name', 'target_name', 'cluster'}:
        raise ValueError('Invalid parent chk declaration')
    if child['template'] != 'gaussian' or attachment['target_name'] != 'parent.chk':
        raise ValueError('Only Gaussian parent.chk attachments are supported')
    if attachment['attempt_id'] not in [p['attempt_id'] for p in child['parents']]:
        raise ValueError('Parent chk must also appear in --parent')
    parent, job = _parent(cfg, attachment['attempt_id'], attachment['source_name'])
    if parent['study_id'] != child['study_id'] or parent['attempt_id'] == child['attempt_id']:
        raise ValueError('Expected a distinct parent in the same study')
    if not (parent.get('cluster', 'default') == child.get('cluster', 'default') == attachment['cluster'] == cfg['_cluster']):
        raise ValueError('Parent and child must belong to the same cluster')
    # Even a retained C record is still present in the scheduler: refuse it.
    if jobs is not None and any(j['job_id'] == job for j in jobs):
        raise ValueError('Parent job is still present in the scheduler')
    return parent


def summary(attachment, observation=None):
    text = (f"Parent chk: {attachment['attempt_id']} | {attachment['source_name']}"
            f" -> {attachment['target_name']}")
    if observation is None:
        return text + ' | size/SHA256 and scheduler absence checked read-only before submit confirmation'
    size, digest = observation
    return text + f' | {size} bytes | SHA256 {digest[:12]}'
