"""Local counterpoise diagnostics: geometry matching for a solvent SP."""
import math

NOTICE = '诊断量；未进入 thermo/profile；不构成已校正剖面'


def paired_geometry(cp_geometry, solvent_geometry):
    """Same row mapping, proper rigid alignment, and the requested 0.001 A limit.

    This prevents applying a BSSE correction to a different conformer. Adapted
    from thermo._pairing_evidence's Kabsch calculation without its Freq inputs.
    """
    import numpy as np
    from ag.gaussian_input import cartesian

    rows = [geometry.splitlines() for geometry in (cp_geometry, solvent_geometry)]
    symbols = [cartesian(group, first_line=1) for group in rows]
    if not symbols[0] or symbols[0] != symbols[1]:
        raise ValueError('CP/solvent SP element sequence differs or is empty; atom reordering is forbidden')
    arrays = [np.array([row.split()[1:] for row in group], dtype=float) for group in rows]
    try:
        with np.errstate(over='raise', invalid='raise'):
            reference, moving = [array - array.mean(axis=0) for array in arrays]
            u, _, vt = np.linalg.svd(moving.T @ reference)
            correction = np.eye(3)
            correction[-1, -1] = 1 if np.linalg.det(u @ vt) >= 0 else -1
            rmsd = float(np.sqrt(np.mean(np.sum((moving @ (u @ correction @ vt) - reference)**2, axis=1))))
    except (FloatingPointError, np.linalg.LinAlgError) as exc:
        raise ValueError('CP/solvent SP geometry cannot be aligned numerically') from exc
    if not math.isfinite(rmsd) or rmsd > 1e-3:
        raise ValueError(f'CP/solvent SP RMSD {rmsd:.8g} angstrom exceeds 0.001')
    return dict(rmsd_angstrom=rmsd, threshold_angstrom=1e-3,
                alignment='proper Kabsch; all atoms; fixed row order; no reflection or permutation')

SOLVENT_NOTE = '溶剂相结果 = 溶剂相相互作用能 + 气相 BSSE；假设 BSSE 基本不受溶剂影响'


def reject_cp(directory):
    """Keep diagnostic energies out of existing thermo/profile/ASM consumers."""
    import json
    path = directory / 'manifest.json'
    if path.is_file() and json.loads(path.read_text()).get('template') == 'gaussian-cp':
        raise ValueError(f'{directory.name}: CP 单点仅用于 cp-report')
    path = directory / 'facts.json'
    if path.is_file() and json.loads(path.read_text()).get('program') == 'gaussian-cp':
        raise ValueError(f'{directory.name}: CP 单点仅用于 cp-report')


def _load(evidence, value, template):
    """Hash-bind the local input, fresh parsed log and optional saved facts."""
    import json
    from pathlib import Path
    from ag import attempt, facts, gaussian_input
    from ag.asm import _attempt
    from ag._profile_sources import require, protocol
    directory = _attempt(evidence.root, value)
    manifest = evidence.json(directory / 'manifest.json')
    require(manifest.get('template') == template, f'{directory.name}: expected {template} Attempt')
    inputs = {}
    for item in manifest['inputs']:
        name = item['name']
        require(Path(name).name == name and name not in ('.', '..') and name not in inputs,
                'Invalid/duplicate input filename')
        inputs[name] = evidence.read(directory / 'inputs' / name)
    records, digest = attempt.bundle(inputs)
    require(records == manifest['inputs'] and digest == manifest['bundle_sha256'], 'Input bundle/hash mismatch')
    names = [name for name in inputs if Path(name).suffix.lower() == '.gjf']
    require(len(names) == 1, 'Expected exactly one Gaussian input')
    name = names[0]
    resource = {key: manifest[key] for key in ('cores', 'mem_gb')}
    if template == 'gaussian-cp':
        csv_name = name + '.fragments.csv'
        require(csv_name in inputs, 'Missing CP fragments CSV')
        _, science = gaussian_input.counterpoise_input(inputs[name].decode(), inputs[csv_name],
                                                       **resource, prepared=True)
        science['counterpoise']['file'] = csv_name
    else:
        science = gaussian_input.validate(inputs[name].decode(), **resource,
                                          parent_chk='parent_chk' in manifest)
    require(all(manifest['science'].get(k) == v for k, v in science.items()),
            'Scientific manifest differs from input')
    log = directory / 'outputs' / (Path(name).stem + '.log')
    evidence.read(log)
    # Bind scheduler evidence and any incomplete-fetch descriptor read by facts.
    for related in [directory / 'status.json', *directory.glob('fetch-incomplete-*.json')]:
        if related.exists():
            evidence.read(related)
    for related in ('job.pbs.out', 'job.slurm.err'):
        if (directory / 'outputs' / related).exists():
            evidence.read(directory / 'outputs' / related)
    parsed, geometries = facts.parse_facts(directory)
    require(parsed.get('termination') == 'normal', 'CP report requires normally terminated calculations')
    if template == 'gaussian-cp':
        for declared, printed in zip(science['counterpoise']['fragments'], parsed['counterpoise']['fragments']):
            require((declared['index'], declared['charge'], declared['multiplicity'])
                    == (printed['index'], printed['charge'], printed['multiplicity']),
                    'Output/input fragment state differs')
    require(parsed.get('n_atoms') == science['n_atoms']
            and parsed.get('charge') == science['charge']
            and parsed.get('multiplicity') == science['multiplicity'], 'Output/input atom count or state differs')
    require(protocol(parsed['route'], 1) == protocol(science['route'], 1), 'Output/input method protocol differs')
    xyz = geometries.get('final_input.xyz') or geometries.get('final.xyz')
    require(xyz is not None, 'Missing output geometry')
    paired_geometry(science['geometry'], '\n'.join(xyz.splitlines()[2:]))
    saved = directory / 'facts.json'
    if saved.exists():
        previous = evidence.json(saved)
        content = lambda v: json.dumps({k: x for k, x in v.items() if k != 'ag_provenance'},
                                      sort_keys=True, ensure_ascii=False, allow_nan=False)
        require(content(previous) == content(parsed), 'Saved facts differ from current log; review before refresh')
    return directory, manifest, science, parsed, log


def _quantity(hartree, operands, formula=None):
    from ag._parse_outputs import HARTREE_TO_KCAL
    from ag._profile_sources import finite
    finite(hartree, 'CP report value')
    return dict(hartree=hartree, kcal_mol=hartree * HARTREE_TO_KCAL,
                sources=operands, formula=formula)


def _gas_values(cp, log_source):
    from copy import deepcopy
    cp = deepcopy(cp)
    def bind(item):
        item['source'] = {**log_source, 'line': item['source']['line']}
        if 'calculation_source' in item:
            item['calculation_source'] = {**log_source, 'line': item['calculation_source']['line']}
        return item
    for key, item in cp.items():
        if isinstance(item, dict) and 'source' in item:
            bind(item)
    for fragment in cp['fragments']:
        bind(fragment['dcbs'])
        bind(fragment['mcbs'])
        fragment['state_source'] = {**log_source, 'line': fragment['state_source']['line']}
    values = {key: _quantity(cp[key]['value'], [cp[key]['source']])
              for key in ('uncorrected_energy', 'corrected_energy', 'bsse', 'sum_fragments')}
    for key, energy_key in (('interaction_raw', 'uncorrected_energy'), ('interaction_corrected', 'corrected_energy')):
        values[key] = _quantity(cp[energy_key]['value'] - cp['sum_fragments']['value'],
                               [cp[energy_key]['source'], cp['sum_fragments']['source']],
                               energy_key + ' - sum_fragments')
    return dict(**values, fragments=cp['fragments'],
                printed_interaction_raw=cp['interaction_raw_printed'],
                printed_interaction_corrected=cp['interaction_corrected_printed'])


def _solvent(evidence, value, cp_science, gas):
    import re
    from ag._parse_outputs import NUMBER, number
    from ag._profile_sources import require, protocol, section_source, integration_grid, grid_warnings
    directory, manifest, science, facts, log = _load(evidence, value, 'gaussian')
    sections = facts['job_sections']
    route = facts['route']
    require(len(sections) == 1 and not re.search(
        r'\b(opt|freq|irc|scan|counterpoise|force|polar|stable|td|cis|guess)\b', route, re.I),
        'Solvent overlay requires one ordinary Gaussian single point')
    pairing = paired_geometry(cp_science['geometry'], science['geometry'])
    require((cp_science['charge'], cp_science['multiplicity']) == (science['charge'], science['multiplicity']),
            'CP/solvent SP overall state differs')
    method = protocol(science['route'], science['multiplicity'])
    require(method['solvent_model'] != 'none', '--solvent-sp requires an explicit solvent model')
    require(all(method[k] == cp_science['protocol'][k]
                for k in ('method', 'basis', 'basis_function_type', 'dispersion')),
            'CP/solvent SP method/basis/dispersion differs')
    source = section_source(facts, directory.name, frequency=False, directory=directory)
    require(source.get('printed_conditions', {}).get('solvent') is not None,
            'Solvent SP needs printed solvent execution evidence; route echo is insufficient')
    lines = evidence.saved[log].decode(errors='replace').splitlines()
    matches = [(i, re.fullmatch(r'\s*SCF Done:\s+E\([^)]+\)\s*=\s*(' + NUMBER
                               + r')\s+A\.U\. after\s+\d+\s+cycles\s*', line))
               for i, line in enumerate(lines, 1) if re.match(r'\s*SCF Done:', line)]
    require(len(matches) == 1 and matches[0][1] is not None, 'Ambiguous solvent SP SCF energy')
    line, match = matches[0]
    energy = number(match[1])
    require(abs(energy - facts['energies']['scf']) <= 1e-8, 'Solvent SCF energy differs from parsed facts')
    energy_source = {**evidence.reference(log), 'line': line}
    # Ordinary Gaussian SP supplies E_AB only. Do not infer solvent monomer
    # energies from Mulliken populations or reuse gas MCBS/DCBS values.
    return dict(attempt=directory.name, pairing=pairing, protocol=source['protocol'],
                complex_energy=_quantity(energy, [energy_source]),
                complex_energy_plus_gas_bsse=_quantity(energy + gas['bsse']['hartree'],
                    [energy_source, *gas['bsse']['sources']], 'E_AB(solvent) + BSSE(gas)'),
                interaction_raw=None, interaction_corrected=None,
                fragment_energies=[dict(index=f['index'], energy=None) for f in cp_science['counterpoise']['fragments']],
                missing=[f"片段 {f['index']} ({f['fragment']}) 的同几何溶剂相单点能量"
                         for f in cp_science['counterpoise']['fragments']],
                note=SOLVENT_NOTE,
                limitation='普通单个溶剂相 SP 不提供两个片段能量；仅报告溶剂相复合物能量 + 气相 BSSE 修正量，不是相互作用能。',
                warnings=grid_warnings([('CP', integration_grid(cp_science['route'])),
                                        ('solvent SP', integration_grid(science['route']))]))


def _asm_comparison(evidence, value):
    from pathlib import Path
    from ag.study import local_path
    from ag._profile_sources import require, finite
    path = Path(value).expanduser()
    path = local_path(evidence.root / 'analyses', path if path.is_absolute() else evidence.root / path)
    data = evidence.json(path)
    require(data.get('schema') == 'ag-asm/1' and data.get('units', {}).get('energy') == 'Hartree',
            '--asm requires an ag-asm/1 report in Hartree')
    # A stale report is not valid comparison evidence even though it is not
    # added to CP energies. Recheck all of its recorded source hashes.
    for item in data['sources']:
        source = local_path(evidence.root, evidence.root / item['path'])
        evidence.read(source)
        require(evidence.reference(source)['sha256'] == item['sha256'], 'ASM source hash mismatch')
    rows = []
    for index, system in enumerate(data['systems']):
        amount = system['E_dist_total']
        if amount is not None:
            finite(amount['hartree'], 'ASM deformation energy')
        rows.append(dict(label=system['label'], complex_attempt=system['complex']['attempt'],
                         deformation=amount, source={**evidence.reference(path),
                         'json_pointer': f'/systems/{index}/E_dist_total'}))
    return dict(systems=rows, note='仅并列展示原 ASM 形变能；不与 CP 组合成新的结合能结论。')


def report(value, *, study=None, solvent_sp=None, asm=None):
    from ag.asm import _root
    from ag.ensemble import _Evidence
    from ag._profile_sources import integration_grid
    from ag import __version__
    from ag._parse_outputs import HARTREE_TO_KCAL
    evidence = _Evidence(_root(study, value))
    directory, manifest, science, facts, log = _load(evidence, value, 'gaussian-cp')
    gas = _gas_values(facts['counterpoise'], evidence.reference(log))
    fragments = {**science['counterpoise'],
                 'source': evidence.reference(directory / 'inputs' / science['counterpoise']['file'])}
    result = dict(schema='ag-cp/1', ag_version=__version__, attempt=directory.name,
                  program_version=facts.get('program_version'), protocol=science['protocol'],
                  integration_grid=integration_grid(science['route']), fragments=fragments,
                  units=dict(energy='Hartree', converted_energy='kcal/mol', distance='angstrom'),
                  hartree_to_kcal_mol=HARTREE_TO_KCAL, gas=gas,
                  solvent=_solvent(evidence, solvent_sp, science, gas) if solvent_sp else None,
                  asm=_asm_comparison(evidence, asm) if asm else None, notice=NOTICE)
    evidence.verify()
    result['sources'] = [evidence.reference(path) for path in sorted(evidence.saved)]
    return result


def markdown(result):
    import json
    def cell(value):
        return str(value).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace(
            '|', '&#124;').replace('`', '&#96;').replace('\n', ' ').replace('\r', ' ')
    def sources(value):
        return '; '.join(f"{s['path']}:{s.get('line', s.get('json_pointer', ''))} SHA-256 {s['sha256']}"
                         for s in value['sources'])
    def table(rows):
        return ['| 项目 | Hartree | kcal/mol | 来源 |', '| --- | ---: | ---: | --- |',
                *[f"| {cell(name)} | {v['hartree']:.12f} | {v['kcal_mol']:.8f} | {cell(sources(v))} |"
                  for name, v in rows]]
    gas = result['gas']
    lines = ['# Counterpoise 诊断', '', NOTICE, '', f"Attempt: {cell(result['attempt'])}", '',
             f"方法口径：{cell(json.dumps(result['protocol'], ensure_ascii=False))}", '',
             f"1 Hartree = {result['hartree_to_kcal_mol']} kcal/mol。", '',
             *table([(key, gas[key]) for key in ('uncorrected_energy', 'corrected_energy', 'bsse',
                                               'sum_fragments', 'interaction_raw', 'interaction_corrected')]), '',
             '## 片段', '', f"CSV SHA-256: {result['fragments']['sha256']}", '']
    for definition, energies in zip(result['fragments']['fragments'], gas['fragments']):
        lines += [f"- {cell(definition['fragment'])}: 原子 {definition['atoms']}，{definition['formula']}，"
                  f"电荷/多重度 {definition['charge']}/{definition['multiplicity']}", '']
        lines += table([(key.upper(), _quantity(energies[key]['value'], [energies[key]['source']]))
                        for key in ('mcbs', 'dcbs')]) + ['']
    if result['solvent']:
        solvent = result['solvent']
        lines += ['## 溶剂相叠加', '', SOLVENT_NOTE, '', solvent['limitation'], '',
                  *table([(key, solvent[key]) for key in ('complex_energy', 'complex_energy_plus_gas_bsse')]), '',
                  '缺失：' + '；'.join(solvent['missing']), '',
                  '溶剂相相互作用能（未校正/校正）：未知。', '', *solvent['warnings'], '']
    if result['asm']:
        lines += ['## ASM 并列对照', '', result['asm']['note'], '']
        for row in result['asm']['systems']:
            lines += [f"- {cell(row['label'])} ({cell(row['complex_attempt'])}): "
                      f"{cell(row['deformation'])}；来源 {cell(row['source'])}"]
    lines += ['', '## 来源', '']
    lines += [f"- {cell(item['path'])}；SHA-256 {item['sha256']}" for item in result['sources']]
    return '\n'.join(lines) + '\n'


def run(args):
    import json
    from ag.asm import _root, _output
    from ag.fragments import _write_outputs
    root = _root(args.study, args.attempt)
    target = _output(root, args.out, '.json')
    result = report(args.attempt, study=str(root), solvent_sp=args.solvent_sp, asm=args.asm)
    content = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    _write_outputs(target.parent, {target.name: content.encode(),
                                  target.with_suffix('.md').name: markdown(result).encode()})
    print(content if args.json else markdown(result), end='')
    return 0


def register(subparsers):
    parser = subparsers.add_parser('cp-report', help='Local gas-phase Counterpoise diagnostics (ag-cp/1)')
    parser.add_argument('attempt', help='gaussian-cp Attempt ID or directory')
    parser.add_argument('--study', help='Study directory; inferred from absolute Attempt directory')
    parser.add_argument('--solvent-sp', help='Same-geometry ordinary Gaussian solvent SP Attempt')
    parser.add_argument('--asm', help='Existing ag-asm/1 report under study analyses/')
    parser.add_argument('--out', required=True, help='New JSON under study analyses/; also writes Markdown')
    parser.add_argument('--json', action='store_true')
    parser.set_defaults(func=run)
