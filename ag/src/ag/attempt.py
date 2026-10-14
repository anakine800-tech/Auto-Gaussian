"""Immutable preparation and file-bound Attempt lookup."""
from hashlib import sha256
import json
from pathlib import Path
import re
from ag import __version__, cards, crest_input, gaussian_input, journal, render, state, study
from ag.config import select_cluster, for_manifest, scheduler_kind
from ag.locks import claim
from ag.remote import filename


def bundle(files):
    records = [dict(name=name, sha256=sha256(data).hexdigest(), size=len(data)) for name, data in sorted(files.items())]
    digest = sha256(''.join(f"{r['name']}\0{r['sha256']}\n" for r in records).encode()).hexdigest()
    return records, digest


def read_manifest(path):
    study.local_path(path.parent.parent, path / 'manifest.json')
    m = json.loads((path / 'manifest.json').read_text())
    if m['attempt_id'] != path.name or m['study_id'] != path.parent.parent.name:
        raise ValueError('Manifest identity differs from directory')
    return m


def find(cfg, attempt_id):
    study.identifier(attempt_id)
    root = Path(cfg['local']['studies_root'])
    matches = list(root.glob(f'*/attempts/{attempt_id}'))
    if len(matches) != 1:
        raise ValueError('Attempt ID missing or ambiguous')
    path = study.local_path(root, matches[0])
    for name in ('manifest.json', 'status.json', 'inputs', 'outputs'):
        study.local_path(root, path / name)
    read_manifest(path)
    return path


def all_attempts(cfg, name=None):
    root = Path(cfg['local']['studies_root'])
    studies = [study.locate(cfg, name)] if name else sorted(root.glob('*'))
    result = []
    for s in studies:
        study.local_path(root, s)
        for a in sorted((s / 'attempts').glob('*')):
            if a.is_dir():
                study.local_path(root, a)
                if not (a / 'manifest.json').exists():
                    continue
                result.append(dict(attempt_id=a.name, study_id=s.name, **state.read(a)))
    return result


def prepare(cfg, *, study_name, template, input_path, tier, walltime, label, params=None, parents=None, method_basis='兜底方法', constraints=None, cluster='default', card=None):
    cfg = select_cluster(cfg, cluster)
    s = study.locate(cfg, study_name)
    if not (s / 'study.md').is_file() or not (s / 'attempts').is_dir():
        raise ValueError('Initialize the study first')
    study.identifier(label)
    if tier not in ('mini', 'simple', 'general', 'complex'):
        raise ValueError('Invalid resource tier')
    resource = cfg['resources']['tiers'][tier]
    source = Path(input_path)
    name = filename(source.name)
    data = source.read_bytes()
    params = dict(params or {})
    if constraints is not None and template != 'crest':
        raise ValueError('--constraints is only supported for the crest template')
    if '--cinp' in params:
        raise ValueError('Use --constraints to supply a validated CREST constraint file')
    render.parameters(template, params)
    if template == 'gaussian':
        if source.suffix.lower() != '.gjf':
            raise ValueError('Gaussian input must have .gjf extension')
        science = gaussian_input.validate(data.decode(), **resource)
    else:
        if source.suffix.lower() != '.xyz':
            raise ValueError('xTB/CREST input must have .xyz extension')
        rows = data.decode().splitlines()
        if not rows or not rows[0].isdigit() or int(rows[0]) < 1 or len(rows) != int(rows[0]) + 2:
            raise ValueError('Invalid XYZ atom count')
        # The same Cartesian grammar prevents malformed input from becoming a shell option.
        synthetic = f'%nprocshared={resource["cores"]}\n%mem=1GB\n# HF/STO-3G\n\nxyz\n\n{params.get("--chrg", "0")} {int(params.get("--uhf", "0")) + 1}\n' + '\n'.join(rows[2:]) + '\n\n'
        science = gaussian_input.validate(synthetic, **resource)
        science['route'] = render.parameters(template, params)
    constraint_data = None
    if constraints is not None:
        constraint_data = Path(constraints).read_bytes()
        crest_input.validate(constraint_data.decode(), science['n_atoms'])
        params['--cinp'] = 'constraints.inp'
        science['route'] = render.parameters(template, params)
    if not isinstance(method_basis, str) or not method_basis.strip():
        raise ValueError('Method basis must be a DOI/reference or fallback declaration')
    card_record = cards.snapshot(card) if card is not None else None
    parents = parents or []
    for parent in parents:
        parent_path = find(cfg, parent['attempt_id'])
        if parent_path.parent.parent != s:
            raise ValueError('Parent must belong to this study')
        study.identifier(parent['relation'].replace('_', '-'))
    # O_EXCL reserves the numeric sequence, even with concurrent different labels.
    for number in range(1, 1000):
        try:
            claim(s / 'attempts' / f'.sequence-{number:03}')
            break
        except FileExistsError:
            continue
    else:
        raise ValueError('Study sequence exhausted')
    attempt_id = f'{s.name}-{number:03}-{label}'
    study.identifier(attempt_id)
    m = dict(schema='ag-attempt/1', cluster=cluster, scheduler=scheduler_kind(cfg), attempt_id=attempt_id, study_id=s.name, label=label,
             template=template, template_params=params, tier=tier, **resource, walltime=walltime,
             pbs_job_name='ag' + sha256(attempt_id.encode()).hexdigest()[:12],
             remote_dir=f'{s.name}/{attempt_id}', parents=parents, created_at=journal.now(),
             ag_version=__version__, card=card_record, completion_receipts=True, science={**science, 'method_basis': method_basis})
    script = 'job.slurm' if m['scheduler'] == 'slurm' else 'job.pbs'
    files = {name: data, script: render.render(cfg, m, name).encode()}
    if constraint_data is not None:
        files['constraints.inp'] = constraint_data
    m['inputs'], m['bundle_sha256'] = bundle(files)
    path = s / 'attempts' / attempt_id
    path.mkdir()
    (path / 'inputs').mkdir()
    (path / 'outputs').mkdir()
    for n, content in files.items():
        with (path / 'inputs' / n).open('xb') as handle:
            handle.write(content)
    with (path / 'manifest.json').open('x') as handle:
        json.dump(m, handle, indent=2, ensure_ascii=False)
    state.write(path, 'prepared', initial=True)
    journal.append(s, 'prepare', attempt_id, detail={'bundle_sha256': m['bundle_sha256']})
    return m


def verified_files(cfg, path, manifest):
    m = manifest
    cfg = for_manifest(cfg, m)
    script = 'job.slurm' if m.get('scheduler') == 'slurm' else 'job.pbs'
    resource = cfg['resources']['tiers'].get(m['tier'])
    if not resource or any(m[k] != resource[k] for k in ('cores', 'mem_gb')):
        raise ValueError('Resource configuration changed since preparation')
    if m['pbs_job_name'] != 'ag' + sha256(m['attempt_id'].encode()).hexdigest()[:12]:
        raise ValueError('Invalid PBS name')
    files = {}
    for p in (path / 'inputs').iterdir():
        if p.is_symlink() or not p.is_file():
            raise ValueError('Only regular input files are allowed')
        files[filename(p.name)] = p.read_bytes()
    records, digest = bundle(files)
    if records != m['inputs'] or digest != m['bundle_sha256']:
        raise ValueError('Input bundle differs from confirmed manifest')
    names = set(files) - {script}
    constrained = m['template'] == 'crest' and m['template_params'].get('--cinp') == 'constraints.inp'
    if constrained:
        if 'constraints.inp' not in names:
            raise ValueError('Missing CREST constraints.inp input')
        names.remove('constraints.inp')
    if len(names) != 1:
        raise ValueError('Expected one program input, job.pbs and optional declared CREST constraints')
    name = next(iter(names))
    if constrained:
        rows = files[name].decode().splitlines()
        if not rows or not rows[0].isdigit() or int(rows[0]) < 1 or len(rows) != int(rows[0]) + 2:
            raise ValueError('Invalid XYZ atom count')
        crest_input.validate(files['constraints.inp'].decode(), int(rows[0]))
    if files[script] != render.render(cfg, m, name).encode():
        raise ValueError('Prepared script differs from current reviewed template/configuration')
    if m['template'] == 'gaussian':
        science = gaussian_input.validate(files[name].decode(), **resource)
        if any(m['science'].get(k) != v for k, v in science.items()):
            raise ValueError('Scientific summary differs from submitted input')
    return files


def summary(cfg, m):
    from ag.remote import attempt_dir
    cfg = for_manifest(cfg, m)
    science = m['science']
    from ag import budget
    budget_line = budget.summary(cfg, budget.requested(m)) if m.get('scheduler') == 'slurm' else ''
    geometry = f"```text\n{science['geometry']}\n```\n\n"
    if science.get('qst_mode'):
        geometry = f"{science['qst_mode']} structures (input atom order):\n\n"
        for i, structure in enumerate(science['structures'], 1):
            role = ('reactant', 'product', 'TS guess')[i - 1]
            geometry += (f"Group {i} ({role}) | Title: {structure['title']} | Atoms: {structure['n_atoms']}\n\n"
                         f"Charge / multiplicity: {structure['charge']} / {structure['multiplicity']}\n\n"
                         f"```text\n{structure['geometry']}\n```\n\n")
        geometry += ('Largest reactant/product displacements after Kabsch alignment '
                     f"(fixed row mapping, {science['displacement_unit']}; up to 5 atoms):\n\n")
        geometry += '\n'.join(f"- Atom {row['atom_index']} ({row['element']}): {row['displacement']:.8f}"
                              for row in science['largest_displacements']) + '\n\n'
    return (f"### {m['attempt_id']}\n\nCluster: {m.get('cluster', 'default')}\n\n{cost_line(m)}\n{budget_line}\n\nTemplate: {m['template']} | Tier: {m['tier']} | "
            f"Cores: {m['cores']} | Memory: {m['mem_gb']} GB | Walltime: {m['walltime']}\n\n"
            f"{cards.label(m)}\n\nRemote directory: {attempt_dir(cfg, m)}\n\nBundle SHA-256: {m['bundle_sha256']}\n\n"
            f"Method basis: {m['science']['method_basis']}\n\nRoute: {m['science']['route']}\n\n"
            f"Charge / multiplicity: {m['science']['charge']} / {m['science']['multiplicity']}\n\n"
            f"{m['science']['stereochemistry_warning']}\n\n" + geometry +
            '\n'.join(f"- {r['name']}: {r['sha256']}" for r in m['inputs']))


def cost_line(m):
    hours, minutes, seconds = map(int, m['walltime'].split(':'))
    cost = m['cores'] * (hours + minutes / 60 + seconds / 3600)
    return f"估算核时 = 核数 × walltime = {cost:g} 核时（实际费用以平台计费为准）"
