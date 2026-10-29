"""Immutable preparation and file-bound Attempt lookup."""
from hashlib import sha256
from datetime import datetime
from contextlib import nullcontext
import json
from pathlib import Path
import re
from ag import __version__, cards, crest_input, gaussian_input, journal, render, state, study
from ag.config import (select_cluster, for_manifest, scheduler_kind, cluster_name,
                       shared_cap_summary, RESOURCE_TIERS, resolve_tier, validate_walltime)
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


def prepare(cfg, *, study_name, autonomous=None, **kwargs):
    """Serialize publication with a new round and enforce the backend writer.

    A durable manual writer is kept through the operation; neither the machine
    mutex nor the study mutex spans a CREST installation query.
    All existing callers pass through this boundary, including the frontend.
    """
    from ag import autonomy
    if autonomous is None:
        with autonomy.manual_write_guard(cfg, study_name, action='prepare'):
            return _prepare(cfg, study_name=study_name, **kwargs)
    from ag.submit import prepare_autonomous, WaitingForRoute
    from ag.transport import TransportError
    try:
        return prepare_autonomous(cfg, study_name=study_name, context=autonomous, options=kwargs)
    except WaitingForRoute:
        raise
    except (ValueError, OSError, TransportError):
        autonomy.pause_if_current_owner(cfg, study_name, autonomous.get('run_id'), autonomous.get('token'),
            'Autonomous preparation stopped; review retained evidence')
        raise


def reroute_input_identity(manifest, files):
    """Compare frozen scientific bytes while allowing only declared resources.

    The scheduler script is regenerated for the new Attempt/target. Gaussian
    may change its two validated Link0 resource directives; every other input
    byte, attachment, program parameter and scientific summary stays exact.
    Call only after the ordinary input/bundle validation has succeeded.
    """
    if (manifest.get('template') not in ('gaussian', 'gaussian-cp', 'crest', 'xtb')
            or 'parent_chk' in manifest or 'input_validation' in manifest):
        raise ValueError('Reroute requires a supported strict input without checkpoint dependencies')
    scientific = {}
    for name, data in files.items():
        if name in ('job.slurm', 'job.pbs'):
            continue
        if manifest['template'] in ('gaussian', 'gaussian-cp') and name.endswith('.gjf'):
            lines = data.splitlines(keepends=True)
            kept, link0 = [], True
            for line in lines:
                if not line.startswith(b'%'):
                    link0 = False
                if link0 and re.fullmatch(rb'%(?:nprocshared|mem)\s*=.*(?:\r?\n)?', line, re.I):
                    continue
                kept.append(line)
            data = b''.join(kept)
        scientific[name] = dict(size=len(data), sha256=sha256(data).hexdigest())
    return dict(template=manifest['template'], template_params=manifest['template_params'],
                science=manifest['science'], inputs=scientific)


def _prepare(cfg, *, study_name, template, input_path, tier=None, walltime, label, params=None, parents=None, method_basis, constraints=None, cluster='default', card=None, parent_chk=None, analysis=None, grid=None, fragments=None, transport=None, target_node=None, node_fraction=None, publication=None, reroute_evidence=None):
    from ag import node_targeting
    cfg = select_cluster(cfg, cluster)
    tier = resolve_tier(cfg, tier)
    binding = node_targeting.prepare(cfg, cluster, template, tier, target_node, node_fraction)
    if 'allowed_templates' in cfg and template not in cfg['allowed_templates']:
        allowed = ', '.join(cfg['allowed_templates']) or '(none)'
        raise ValueError(f'Cluster {cluster}: template {template} is not allowed; allowed_templates: {allowed}')
    validate_walltime(cfg, walltime)
    s = study.locate(cfg, study_name)
    if not (s / 'study.md').is_file() or not (s / 'attempts').is_dir():
        raise ValueError('Initialize the study first')
    study.identifier(label)
    resource = cfg['resources']['tiers'][tier]
    if template != 'multiwfn' and any(v is not None for v in (analysis, grid)):
        raise ValueError('--analysis/--grid require the multiwfn template')
    if fragments is not None and template not in ('multiwfn', 'gaussian-cp'):
        raise ValueError('--fragments requires the multiwfn or gaussian-cp template')
    if template == 'multiwfn':
        if params:
            raise ValueError('Use --analysis and --grid, not custom Multiwfn parameters')
        params = {'--analysis': analysis, '--grid': grid}
        name, data = None, None
    else:
        if input_path is None:
            raise ValueError('--input is required for this template')
        source = Path(input_path)
        name = filename(source.name)
        data = source.read_bytes()
    params = dict(params or {})
    if constraints is not None and template not in ('crest', 'xtb'):
        raise ValueError('--constraints is only supported for the crest or xtb template')
    if '--cinp' in params or '--input' in params:
        raise ValueError('Use --constraints to supply a validated xTB/CREST constraint file')
    render.parameters(template, params)
    if template == 'gaussian-cp' and parent_chk is not None:
        raise ValueError('gaussian-cp does not support parent checkpoints')
    attachment = None
    if parent_chk is not None:
        from ag.parent_chk import declare
        attachment = declare(cfg, s, template, parents or [], parent_chk)
    nci_files = None
    cp_fragments = None
    auto_nprocshared = None
    auto_mem = None
    if template in ('gaussian', 'gaussian-cp'):
        data, auto_nprocshared = gaussian_input.fill_nprocshared(data, resource['cores'])
        data, auto_mem = gaussian_input.fill_memory(data, **resource)
    if template == 'multiwfn':
        from ag.nci_report import prepare_inputs
        science, nci_files = prepare_inputs(cfg, params, input_path, fragments, attachment, cores=resource['cores'])
        name = 'ensemble.xyz' if analysis == 'igm' else 'parent-context.json'
        data = nci_files[name]
    elif template == 'gaussian-cp':
        if source.suffix.lower() != '.gjf' or fragments is None:
            raise ValueError('gaussian-cp requires a .gjf input and --fragments CSV')
        cp_fragments = Path(fragments).read_bytes()
        data, science = gaussian_input.counterpoise_input(data.decode(), cp_fragments, **resource)
        # Sort after the .gjf so existing output_names still selects its stem.
        science['counterpoise']['file'] = name + '.fragments.csv'
    elif template == 'gaussian':
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
            # Check coordinates against original XYZ line numbers before the
            # existing ensemble parser checks matching frames and its limits.
            cursor = 0
            while cursor < len(rows):
                if not rows[cursor].strip():
                    cursor += 1
                    continue
                if not rows[cursor].strip().isdigit() or int(rows[cursor]) < 1:
                    raise ValueError(f'line {cursor + 1}: Invalid XYZ atom count')
                end = cursor + int(rows[cursor]) + 2
                if end > len(rows):
                    raise ValueError(f'line {cursor + 1}: Truncated XYZ frame')
                gaussian_input.cartesian(rows[cursor + 2:end], first_line=cursor + 3)
                cursor = end
            frames = crest_input.xyz_ensemble(data.decode())
            rows = [str(len(frames[0][0])), ''] + frames[0][1]
        if not rows or not rows[0].isdigit() or int(rows[0]) < 1 or len(rows) != int(rows[0]) + 2:
            raise ValueError('Invalid XYZ atom count')
        symbols = gaussian_input.cartesian(rows[2:], first_line=3)
        charge, multiplicity = int(params.get('--chrg', '0')), int(params.get('--uhf', '0')) + 1
        gaussian_input.check_electrons(symbols, charge, multiplicity,
                                      location='XYZ --chrg/--uhf parameters')
        # Retain the existing parser/resource checks and summary normalization;
        # the preflight above reports new errors against XYZ, not this wrapper.
        synthetic = f'%nprocshared={resource["cores"]}\n%mem=1GB\n# HF/STO-3G\n\nxyz\n\n{charge} {multiplicity}\n' + '\n'.join(rows[2:]) + '\n\n'
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
        raise ValueError('Method basis must be nonblank: 文献先例（DOI 及位置）、本课题既有方案（来源；不是文献先例，精度未经验证）或兜底方法声明')
    card_record = cards.snapshot(card) if card is not None else None
    parents = parents or []
    for parent in parents:
        parent_path = find(cfg, parent['attempt_id'])
        if parent_path.parent.parent != s:
            raise ValueError('Parent must belong to this study')
        study.identifier(parent['relation'].replace('_', '-'))
    if template == 'crest' and 'crest' in cfg['programs']:
        # An explicit independent install must work before an immutable bundle
        # is created. The fixed read-only check never falls back or retries SSH.
        from ag.config import crest_executable
        from ag.remote import executable
        from ag.transport import SSHTransport, require_ok
        # read_only=True currently enables automatic SSH retries. Disable that
        # mode to stop on the first failure; this call site runs only the fixed
        # read-only executable check and never uses upload or write commands.
        checker = transport if transport is not None else SSHTransport(cfg, read_only=False)
        require_ok(checker.run(executable(crest_executable(cfg['programs']))), 'crest executable')
    program_files = dict(nci_files or {name: data})
    if cp_fragments is not None:
        program_files[name + '.fragments.csv'] = cp_fragments
    if constraint_data is not None:
        program_files['constraints.inp'] = constraint_data
    if reroute_evidence is not None:
        # The owner adapter supplies a verified source and its frozen science.
        # Compare the actual parsed bytes before allocating a new Attempt;
        # submission independently re-verifies the immutable source later.
        candidate = dict(template=template, template_params=params,
                         science={**science, 'method_basis': method_basis})
        if attachment is not None:
            candidate['parent_chk'] = attachment
        if reroute_input_identity(candidate, program_files) != reroute_evidence['scientific_identity']:
            raise ValueError('Reroute changed scientific input; only declared resource changes are allowed')
    with publication() if publication is not None else nullcontext():
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
        if template == 'crest':
            m['crest_output_set'] = 'diagnostics-v1'
        if binding is not None:
            m['node_target'] = binding
        if attachment is not None:
            m['parent_chk'] = attachment
        if auto_nprocshared is not None:
            m['auto_nprocshared'] = auto_nprocshared
        if auto_mem is not None:
            m['auto_mem_gb'] = auto_mem
        if reroute_evidence is not None:
            m['reroute_source'] = reroute_evidence['source']
        script = 'job.slurm' if m['scheduler'] == 'slurm' else 'job.pbs'
        files = {**program_files, script: render.render(cfg, m, name).encode()}
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
    validate_walltime(cfg, m['walltime'])
    from ag.node_targeting import validate_binding
    validate_binding(cfg, m)
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
    if m['template'] == 'multiwfn':
        from ag.nci_report import verify_prepared
        name = verify_prepared(cfg, m, files)
        if files[script] != render.render(cfg, m, name).encode():
            raise ValueError('Prepared script differs from current reviewed template/configuration')
        if 'parent_chk' in m:
            from ag.parent_chk import resolve
            resolve(cfg, m)
        return files
    names = set(files) - {script}
    if m['template'] == 'gaussian-cp':
        fragment_name = m['science']['counterpoise']['file']
        if fragment_name not in names or 'parent_chk' in m:
            raise ValueError('Counterpoise requires a fragments CSV and no parent checkpoint')
        names.remove(fragment_name)
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
    if m['template'] == 'gaussian-cp':
        if Path(name).suffix.lower() != '.gjf' or fragment_name != name + '.fragments.csv':
            raise ValueError('Counterpoise input must be .gjf')
        _, science = gaussian_input.counterpoise_input(files[name].decode(), files[fragment_name],
                                                       **resource, prepared=True)
        science['counterpoise']['file'] = fragment_name
        if any(m['science'].get(k) != v for k, v in science.items()):
            raise ValueError('Counterpoise scientific summary differs from submitted input')
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
    from ag.route import prepare_hint
    hint = prepare_hint(cfg, m)
    cfg = for_manifest(cfg, m)
    science = m['science']
    from ag import budget
    cost = (budget.summary(cfg, budget.requested(m)) if m.get('scheduler') == 'slurm'
            else cost_line(m))
    from ag.node_targeting import summary as node_summary
    destination = f"Cluster: {m.get('cluster', 'default')}"
    if 'display_name' in cfg:
        destination = f"Cluster: {cfg['display_name']}（{m.get('cluster', 'default')}）"
    if m.get('scheduler') == 'slurm':
        destination += f"\n\nPartition: {cfg.get('partition', 'scheduler default')}"
    destination += node_summary(m)
    shared_text = shared_cap_summary(cfg)
    if shared_text:
        destination += '\n\n' + shared_text
    geometry = f"```text\n{science['geometry']}\n```\n\n"
    if science.get('n_frames') and m['template'] == 'crest':
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
    if m['template'] == 'multiwfn':
        from ag.nci_report import summary as nci_summary
        geometry += nci_summary(m) + '\n\n'
    if m['template'] == 'gaussian-cp':
        definition = science['counterpoise']
        geometry += f"Fragments CSV SHA-256: {definition['sha256']}\n\n"
        for fragment in definition['fragments']:
            geometry += (f"- Fragment {fragment['index']} ({fragment['fragment']}): "
                         f"{fragment['n_atoms']} atoms; {fragment['formula']}; "
                         f"charge / multiplicity: {fragment['charge']} / {fragment['multiplicity']}\n")
        geometry += '\n'
    attachment_summary = ''
    if 'parent_chk' in m:
        from ag.parent_chk import summary
        attachment_summary = summary(m['parent_chk']) + '\n\n'
    return (f"### {m['attempt_id']}\n\n{destination}\n\n{cost}\n\nTemplate: {m['template']} | Tier: {m['tier']} | "
            f"Cores: {m['cores']} | Memory: {m['mem_gb']} GB | Walltime: {m['walltime']}\n\n"
            f"{resource_summary(cfg, m)}\n\n"
            f"{cards.label(m)}\n\nRemote directory: {attempt_dir(cfg, m)}\n\nBundle SHA-256: {m['bundle_sha256']}\n\n"
            f"Method basis: {m['science']['method_basis']}\n\nRoute: {m['science']['route']}\n\n"
            f"Charge / multiplicity: {m['science']['charge']} / {m['science']['multiplicity']}\n\n"
            f"{m['science']['stereochemistry_warning']}\n\n" + geometry + attachment_summary +
            '\n'.join(f"- {r['name']}: {r['sha256']}" for r in m['inputs']) + hint)


def cost_line(m):
    hours, minutes, seconds = map(int, m['walltime'].split(':'))
    cost = m['cores'] * (hours + minutes / 60 + seconds / 3600)
    return f"估算核时 = 核数 × walltime = {cost:g} 核时（实际费用以平台计费为准）"


def resource_summary(cfg, m):
    cores = (f"%nprocshared 由 ag 自动填写：{m['auto_nprocshared']}\n\n"
             if 'auto_nprocshared' in m else '')
    memory = (f"%mem 由 ag 自动填写：{m['auto_mem_gb']} GB（规则 R1）\n\n"
              if 'auto_mem_gb' in m else '')
    return cores + memory + resource_references(cfg, m)


def resource_references(cfg, target):
    """Local, advisory history only; malformed/unrelated records cannot block prepare."""
    from ag._profile_sources import protocol
    title = '资源参考（仅提示，不替人选择档位或 walltime）'
    try:
        science = target['science']
        wanted = protocol(science['route'], science['multiplicity'])
        count = science['n_atoms']
        if type(count) is not int or count < 1:
            raise ValueError('Unknown atom count')
    except (ValueError, KeyError, TypeError):
        return title + '：无参考'
    root = Path(cfg['local']['studies_root'])
    candidates = []
    for path in sorted(root.glob('*/attempts/*')):
        try:
            study.local_path(root, path)
            if not path.is_dir():
                continue
            m, current, job = local_record(path)
            if m['template'] != target['template'] or current['state'] not in ('finished', 'fetched'):
                continue
            facts_path = study.local_path(root, path / 'facts.json')
            facts = json.loads(facts_path.read_text())
            atoms = facts['n_atoms']
            if type(atoms) is not int or not count * 0.8 <= atoms <= count * 1.2:
                continue
            historical = protocol(facts['route'], facts['multiplicity'])
            if any(historical[key] != wanted[key] for key in ('method', 'basis')):
                continue
            # IDs, never paths; validate before formatting local record text.
            study.identifier(m['study_id'])
            study.identifier(m['attempt_id'])
            elapsed = receipt_elapsed(current, m, job)
            row = (f"- {m['study_id']} / {m['attempt_id']} | 集群 {m.get('cluster', 'default')} | "
                   f"档位 {m.get('tier', '未知')} / {m.get('cores', '未知')} 核 | "
                   f"{atoms} 原子 | 实际耗时 {elapsed} | termination: {facts['termination']}")
            candidates.append((abs(atoms - count), m['study_id'], m['attempt_id'], row))
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            continue
    return title + ('：\n\n' + '\n'.join(row[-1] for row in sorted(candidates)[:5])
                    if candidates else '：无参考')


def receipt_elapsed(current, manifest, job):
    """Never substitute queue age or CPU time for missing program receipts."""
    try:
        start, end = (current['receipts'][key] for key in ('start', 'exit'))
        key = 'job_id' if manifest.get('scheduler') == 'slurm' else 'PBS_JOBID'
        if not job or start[key] != job or end[key] != job:
            return '未知'
        before = datetime.fromisoformat(start['started_at'].replace('Z', '+00:00'))
        after = datetime.fromisoformat(end['finished_at'].replace('Z', '+00:00'))
        if before.tzinfo is None or after.tzinfo is None or after < before:
            return '未知'
        return f'{(after - before).total_seconds():g} 秒'
    except (ValueError, KeyError, TypeError, AttributeError):
        return '未知'
