"""Immutable preparation and file-bound Attempt lookup."""
from hashlib import sha256
import json
from pathlib import Path
import re
from ag import __version__, cards, crest_input, gaussian_input, journal, render, state, study
from ag.config import select_cluster, for_manifest, scheduler_kind, cluster_name
from ag.locks import claim
from ag.remote import filename


def bundle(files):
    records = [dict(name=name, sha256=sha256(data).hexdigest(), size=len(data)) for name, data in sorted(files.items())]
    digest = sha256(''.join(f"{r['name']}\0{r['sha256']}\n" for r in records).encode()).hexdigest()
    return records, digest


def read_manifest(path):
    try:
        study.local_path(path.parent.parent, path / 'manifest.json')
        m = json.loads((path / 'manifest.json').read_text())
        if m['attempt_id'] != path.name or m['study_id'] != path.parent.parent.name:
            raise ValueError('Manifest identity differs from directory')
        cluster_name(m.get('cluster', 'default'))
        return m
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError(f'Attempt {path.name} (study {path.parent.parent.name}): invalid manifest.json') from exc


def local_record(path, cluster=None, scheduler=None):
    """Filter before reading status: another cluster's records cannot poison a scan.

    Shared by monitor, submission accounting and status/list. A missing manifest
    cannot safely be guessed to be a legacy PBS Attempt.
    """
    from ag import submission
    m = read_manifest(path)
    if cluster is not None and m.get('cluster', 'default') != cluster:
        return None
    try:
        kind = m.get('scheduler', 'pbs' if 'cluster' not in m else None)
        if kind not in ('pbs', 'slurm') or ('cluster' not in m and kind != 'pbs'):
            raise ValueError('Cannot determine Attempt scheduler')
        if scheduler is not None and kind != scheduler:
            raise ValueError('Scheduler changed since preparation')
        study.local_path(path.parent.parent, path / 'status.json')
        current = state.read(path)
        if current['state'] not in state.TRANSITIONS:
            raise ValueError('Invalid local state')
        job = submission.raw_job(m, current['job_id']) if current.get('job_id') is not None else None
        target = study.local_path(path.parent.parent, path / 'submission.json')
        if job is not None and 'cluster' in m:
            submission.verified_job(path, m, current)
        if target.exists():
            record = json.loads(target.read_text())
            recorded = submission.verified_job(path, m, {'job_id': record['job_id']})
            if job is not None and job != recorded:
                raise ValueError('Submission manifest/status/cluster mismatch')
            job = recorded
        if job is None and current['state'] in ('submitted', 'running', 'finished', 'fetched', 'cancelled'):
            raise ValueError('Missing recorded job identity')
        return m, current, job
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ValueError(f'Attempt {path.name} (study {path.parent.parent.name}): invalid local record ({exc})') from exc


def local_records(root, cluster=None, scheduler=None):
    for path in sorted(Path(root).glob('*/attempts/*')):
        if path.is_dir():
            record = local_record(path, cluster, scheduler)
            if record is not None:
                yield path, *record


def find(cfg, attempt_id):
    study.identifier(attempt_id)
    root = Path(cfg['local']['studies_root'])
    matches = list(root.glob(f'*/attempts/{attempt_id}'))
    if len(matches) != 1:
        raise ValueError(f'Attempt {attempt_id}: ID missing or ambiguous')
    path = study.local_path(root, matches[0])
    for name in ('manifest.json', 'status.json', 'inputs', 'outputs'):
        study.local_path(root, path / name)
    read_manifest(path)
    return path


def all_attempts(cfg, name=None):
    root = Path(cfg['local']['studies_root'])
    scope = study.locate(cfg, name) if name else None
    paths = sorted((scope / 'attempts').glob('*') if scope else root.glob('*/attempts/*'))
    result = []
    for path in paths:
        if not path.is_dir():
            continue
        record = local_record(path, cfg.get('_cluster'),
                              scheduler_kind(cfg) if '_cluster' in cfg else None)
        if record is not None:
            m, current, _ = record
            result.append(dict(attempt_id=path.name, study_id=m['study_id'], **current))
    return result


def prepare(cfg, *, study_name, template, input_path, tier, walltime, label, params=None, parents=None, method_basis='兜底方法', constraints=None, cluster='default', card=None, parent_chk=None):
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
    if constraints is not None and template not in ('crest', 'xtb'):
        raise ValueError('--constraints is only supported for the crest or xtb template')
    if '--cinp' in params or '--input' in params:
        raise ValueError('Use --constraints to supply a validated xTB/CREST constraint file')
    render.parameters(template, params)
    attachment = None
    if parent_chk is not None:
        from ag.parent_chk import declare
        attachment = declare(cfg, s, template, parents or [], parent_chk)
    if template == 'gaussian':
        if source.suffix.lower() != '.gjf':
            raise ValueError('Gaussian input must have .gjf extension')
        science = gaussian_input.validate(data.decode(), **resource, parent_chk=attachment is not None)
        if attachment is not None:
            from ag.parent_chk import validate_force_constant_frame
            validate_force_constant_frame(cfg, attachment, science)
    else:
        if source.suffix.lower() != '.xyz':
            raise ValueError('xTB/CREST input must have .xyz extension')
        rows = data.decode().splitlines()
        mdopt = template == 'crest' and '--mdopt' in params
        if mdopt:
            if name in render.declaration('crest')['mdopt_outputs']:
                raise ValueError('CREST --mdopt input must not collide with an output filename')
            frames = crest_input.xyz_ensemble(data.decode())
            rows = [str(len(frames[0][0])), ''] + frames[0][1]
        if not rows or not rows[0].isdigit() or int(rows[0]) < 1 or len(rows) != int(rows[0]) + 2:
            raise ValueError('Invalid XYZ atom count')
        # The same Cartesian grammar prevents malformed input from becoming a shell option.
        synthetic = f'%nprocshared={resource["cores"]}\n%mem=1GB\n# HF/STO-3G\n\nxyz\n\n{params.get("--chrg", "0")} {int(params.get("--uhf", "0")) + 1}\n' + '\n'.join(rows[2:]) + '\n\n'
        science = gaussian_input.validate(synthetic, **resource)
        if mdopt:
            science['n_frames'] = len(frames)
        science['route'] = render.parameters(template, params)
    constraint_data = None
    if constraints is not None:
        constraint_data = Path(constraints).read_bytes()
        scan = crest_input.validate(constraint_data.decode(), science['n_atoms'], allow_scan=template == 'xtb')
        if scan:
            from ag._scan import coordinate, input_geometry
            symbols, _ = input_geometry(science['geometry'])
            scan['coordinate'] = coordinate(**scan['coordinate'], symbols=symbols)
            science['scan'] = scan
            # xTB suppresses per-point convergence reports without verbose.
            params['--verbose'] = ''
        params['--cinp' if template == 'crest' else '--input'] = 'constraints.inp'
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
    if attachment is not None:
        m['parent_chk'] = attachment
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
    constraint_option = {'crest': '--cinp', 'xtb': '--input'}.get(m['template'])
    constrained = constraint_option and m['template_params'].get(constraint_option) == 'constraints.inp'
    if constrained:
        if 'constraints.inp' not in names:
            raise ValueError('Missing constraints.inp input')
        names.remove('constraints.inp')
    if len(names) != 1:
        raise ValueError('Expected one program input, job.pbs and optional declared constraints')
    name = next(iter(names))
    if constrained:
        rows = files[name].decode().splitlines()
        mdopt = m['template'] == 'crest' and '--mdopt' in m['template_params']
        if mdopt:
            if name in render.declaration('crest')['mdopt_outputs']:
                raise ValueError('CREST --mdopt input must not collide with an output filename')
            frames = crest_input.xyz_ensemble(files[name].decode())
            rows = [str(len(frames[0][0])), ''] + frames[0][1]
        if not rows or not rows[0].isdigit() or int(rows[0]) < 1 or len(rows) != int(rows[0]) + 2:
            raise ValueError('Invalid XYZ atom count')
        scan = crest_input.validate(files['constraints.inp'].decode(), int(rows[0]),
                                    allow_scan=m['template'] == 'xtb')
        if scan:
            from ag._scan import coordinate, input_geometry
            symbols, _ = input_geometry('\n'.join(rows[2:]))
            scan['coordinate'] = coordinate(**scan['coordinate'], symbols=symbols)
        if scan != m['science'].get('scan'):
            raise ValueError('Scientific scan summary differs from submitted input')
    if files[script] != render.render(cfg, m, name).encode():
        raise ValueError('Prepared script differs from current reviewed template/configuration')
    if m['template'] == 'gaussian':
        if 'parent_chk' in m:
            from ag.parent_chk import resolve
            resolve(cfg, m)
        science = gaussian_input.validate(files[name].decode(), **resource, parent_chk='parent_chk' in m)
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
    if science.get('n_frames'):
        geometry = (f"CREST mdopt ensemble: {science['n_frames']} frames; first frame preview below. "
                    "Review every frame in the hashed input XYZ before submission.\n\n" + geometry)
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
    from ag._scan import summary as scan_summary
    geometry += scan_summary(science)
    attachment_summary = ''
    if 'parent_chk' in m:
        from ag.parent_chk import summary
        attachment_summary = summary(m['parent_chk']) + '\n\n'
    return (f"### {m['attempt_id']}\n\nCluster: {m.get('cluster', 'default')}\n\n{cost_line(m)}\n{budget_line}\n\nTemplate: {m['template']} | Tier: {m['tier']} | "
            f"Cores: {m['cores']} | Memory: {m['mem_gb']} GB | Walltime: {m['walltime']}\n\n"
            f"{cards.label(m)}\n\nRemote directory: {attempt_dir(cfg, m)}\n\nBundle SHA-256: {m['bundle_sha256']}\n\n"
            f"Method basis: {m['science']['method_basis']}\n\nRoute: {m['science']['route']}\n\n"
            f"Charge / multiplicity: {m['science']['charge']} / {m['science']['multiplicity']}\n\n"
            f"{m['science']['stereochemistry_warning']}\n\n" + geometry + attachment_summary +
            '\n'.join(f"- {r['name']}: {r['sha256']}" for r in m['inputs']))


def cost_line(m):
    hours, minutes, seconds = map(int, m['walltime'].split(':'))
    cost = m['cores'] * (hours + minutes / 60 + seconds / 3600)
    return f"估算核时 = 核数 × walltime = {cost:g} 核时（实际费用以平台计费为准）"
