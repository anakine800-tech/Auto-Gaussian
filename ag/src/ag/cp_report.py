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
    output_geometry = '\n'.join(xyz.splitlines()[2:])
    paired_geometry(science['geometry'], output_geometry)
    saved = directory / 'facts.json'
    if saved.exists():
        previous = evidence.json(saved)
        content = lambda v: json.dumps({k: x for k, x in v.items() if k != 'ag_provenance'},
                                      sort_keys=True, ensure_ascii=False, allow_nan=False)
        require(content(previous) == content(parsed), 'Saved facts differ from current log; review before refresh')
    return directory, manifest, science, parsed, log, output_geometry


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


def _solvent_source(evidence, value, reference, *, fragment_mode=False):
    import re
    from ag._parse_outputs import NUMBER, number
    from ag._profile_sources import require, protocol, section_source, integration_grid
    directory, manifest, science, facts, log, output_geometry = _load(evidence, value, 'gaussian')
    sections = facts['job_sections']
    route = facts['route']
    require(len(sections) == 1 and not re.search(
        r'\b(opt|freq|irc|scan|counterpoise|force|polar|stable|td|cis|guess)\b', route, re.I),
        'Solvent overlay requires one ordinary Gaussian single point')
    pairing = paired_geometry(reference['geometry'], science['geometry'])
    output_pairing = paired_geometry(reference['geometry'], output_geometry) if fragment_mode else None
    require((reference['charge'], reference['multiplicity']) == (science['charge'], science['multiplicity']),
            'CP/solvent SP declared state differs')
    method = protocol(science['route'], science['multiplicity'])
    require(method['solvent_model'] != 'none', '--solvent-sp requires an explicit solvent model')
    require(all(method[k] == reference['protocol'][k]
                for k in ('method', 'basis', 'basis_function_type', 'dispersion')),
            'CP/solvent SP method/basis/dispersion differs')
    source = section_source(facts, directory.name, frequency=False, directory=directory)
    require(source.get('printed_conditions', {}).get('solvent') is not None,
            'Solvent SP needs printed solvent execution evidence; route echo is insufficient')
    lines = evidence.saved[log].decode(errors='replace').splitlines()
    if fragment_mode:
        from ag.gaussian_input import counterpoise_route
        require(method['solvent_model'] == 'smd', 'Solvent fragment mode requires SMD for every solvent SP')
        # Reuse the reviewed SP route subset to exclude hidden geometry/basis
        # changes, checkpoint inheritance and extra tasks from own-basis SPs.
        for candidate in (science['route'], route):
            without_scrf = re.sub(r'\bscrf\s*=?\s*\([^)]*\)', '', candidate, flags=re.I)
            counterpoise_route(without_scrf + ' Counterpoise=2')
        # Free-text titles can mention Counterpoise/Bq/NewBq or "in fragment 1".
        # Reject execution diagnostics, not those words; _load separately
        # validates real-atom input and output geometry against the CP subset.
        require(not re.search(
            r'^[ \t]*(?:Counterpoise:[ \t]*doing\b|Counterpoise corrected energy[ \t]*='
            r'|NewBq[ \t]*=[ \t]*[TF]\b'
            r'|Charge[ \t]*=[ \t]*-?\d+[ \t]+Multiplicity[ \t]*=[ \t]*\d+'
            r'[ \t]+in fragment[ \t]+\d+\b'
            r'|Bq(?:[ \t]+' + NUMBER + r'){3}[ \t]*$)', '\n'.join(lines), re.I | re.M),
                'Solvent fragment mode requires ordinary own-basis SP output without ghost/CP fragments')
    matches = [(i, re.fullmatch(r'\s*SCF Done:\s+E\(([^)]+)\)\s*=\s*(' + NUMBER
                               + r')\s+A\.U\. after\s+\d+\s+cycles\s*', line))
               for i, line in enumerate(lines, 1) if re.match(r'\s*SCF Done:', line)]
    require(len(matches) == 1 and matches[0][1] is not None, 'Ambiguous solvent SP SCF energy')
    line, match = matches[0]
    if fragment_mode:
        from ag._profile_sources import normalized_method
        require(normalized_method(match[1], science['multiplicity']) == method['method'],
                'Solvent SP SCF method differs from route')
    energy = number(match[2])
    require(abs(energy - facts['energies']['scf']) <= 1e-8, 'Solvent SCF energy differs from parsed facts')
    energy_source = {**evidence.reference(log), 'line': line}
    input_name = next(item['name'] for item in manifest['inputs'] if item['name'].lower().endswith('.gjf'))
    return dict(attempt=directory.name, pairing=pairing, output_pairing=output_pairing,
                protocol=source['protocol'], integration_grid=integration_grid(science['route']),
                input_source=evidence.reference(directory / 'inputs' / input_name),
                section_source={**source, **evidence.reference(log)},
                energy=_quantity(energy, [energy_source]))


def _solvent(evidence, value, cp_science, gas, fragment_sps, binding):
    from ag._profile_sources import require, integration_grid, grid_warnings
    complex_sp = _solvent_source(evidence, value, cp_science, fragment_mode=bool(fragment_sps))
    energy = complex_sp['energy']
    # Ordinary Gaussian SP supplies E_AB only. Do not infer solvent monomer
    # energies from Mulliken populations or reuse gas MCBS/DCBS values.
    result = dict(attempt=complex_sp['attempt'], pairing=complex_sp['pairing'], protocol=complex_sp['protocol'],
                complex_energy=energy,
                complex_energy_plus_gas_bsse=_quantity(energy['hartree'] + gas['bsse']['hartree'],
                    [*energy['sources'], *gas['bsse']['sources']], 'E_AB(solvent) + BSSE(gas)'),
                interaction_raw=None, interaction_corrected=None,
                fragment_energies=[dict(index=f['index'], energy=None) for f in cp_science['counterpoise']['fragments']],
                missing=[f"片段 {f['index']} ({f['fragment']}) 的同几何溶剂相单点能量"
                         for f in cp_science['counterpoise']['fragments']],
                note=SOLVENT_NOTE,
                limitation='普通单个溶剂相 SP 不提供两个片段能量；仅报告溶剂相复合物能量 + 气相 BSSE 修正量，不是相互作用能。',
                warnings=grid_warnings([('CP', integration_grid(cp_science['route'])),
                                        ('solvent SP', complex_sp['integration_grid'])]))
    if not fragment_sps:
        return result
    result['complex_source'] = complex_sp
    rows = cp_science['geometry'].splitlines()
    grids = [('CP', integration_grid(cp_science['route'])), ('solvent SP', complex_sp['integration_grid'])]
    missing = []
    for definition, item in zip(cp_science['counterpoise']['fragments'], result['fragment_energies']):
        index = definition['index']
        if index not in fragment_sps:
            missing.append(f"片段 {index} ({definition['fragment']}) 的同几何溶剂相单点能量")
            continue
        reference = dict(geometry='\n'.join(rows[i - 1] for i in definition['atoms']),
                         charge=definition['charge'], multiplicity=definition['multiplicity'],
                         protocol=cp_science['protocol'])
        fragment = _solvent_source(evidence, fragment_sps[index], reference, fragment_mode=True)
        require(fragment['protocol'] == complex_sp['protocol'],
                f'Fragment {index}: solvent SP method or printed solvent parameters differ from complex')
        item.update(fragment)
        item['binding'] = dict(**binding, fragment_index=index, fragment=definition['fragment'],
                               charge=definition['charge'], multiplicity=definition['multiplicity'],
                               atom_mapping=[dict(complex_atom=atom, fragment_atom=local)
                                             for local, atom in enumerate(definition['atoms'], 1)])
        grids.append((f'fragment {index} solvent SP', fragment['integration_grid']))
    result['missing'] = missing
    result['warnings'] = grid_warnings(grids)
    result['limitation'] = ('complex_energy_plus_gas_bsse 不是相互作用能。'
                            '相互作用能使用复合物几何下各片段自身基组的 SMD 单点；'
                            '加气相 BSSE 的结果是近似诊断量，不是计算出的结合自由能。')
    if not missing:
        a, b = [item['energy'] for item in result['fragment_energies']]
        raw = energy['hartree'] - a['hartree'] - b['hartree']
        sources = [*energy['sources'], *a['sources'], *b['sources']]
        result['interaction_raw'] = _quantity(raw, sources, 'E_AB(SMD) - E_A(SMD) - E_B(SMD)')
        result['interaction_corrected'] = _quantity(raw + gas['bsse']['hartree'],
            [*sources, *gas['bsse']['sources']], 'E_AB(SMD) - E_A(SMD) - E_B(SMD) + BSSE(gas)')
        pointers = ['/solvent/complex_energy', '/solvent/fragment_energies/0/energy',
                    '/solvent/fragment_energies/1/energy']
        result['interaction_raw']['operand_pointers'] = pointers
        result['interaction_corrected']['operand_pointers'] = [*pointers, '/gas/bsse']
    return result


def _fragment_arguments(values, solvent_sp):
    import re
    from ag._profile_sources import require
    from ag.study import identifier
    result = {}
    for value in values or []:
        match = re.fullmatch(r'([12]):(.+)', value)
        require(match is not None, '--solvent-fragment-sp requires 1:<attempt_id> or 2:<attempt_id>')
        index, attempt_id = int(match[1]), identifier(match[2])
        require(index not in result, f'Duplicate solvent fragment index {index}')
        require(attempt_id not in result.values(), 'Same Attempt cannot supply both solvent fragments')
        result[index] = attempt_id
    require(not result or solvent_sp, '--solvent-fragment-sp requires --solvent-sp')
    return result


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


def report(value, *, study=None, solvent_sp=None, solvent_fragment_sp=None, asm=None):
    from ag.asm import _root
    from ag.ensemble import _Evidence
    from ag._profile_sources import integration_grid
    from ag import __version__
    from ag._parse_outputs import HARTREE_TO_KCAL
    fragment_sps = _fragment_arguments(solvent_fragment_sp, solvent_sp)
    evidence = _Evidence(_root(study, value))
    directory, manifest, science, facts, log, _ = _load(evidence, value, 'gaussian-cp')
    gas = _gas_values(facts['counterpoise'], evidence.reference(log))
    fragments = {**science['counterpoise'],
                 'source': evidence.reference(directory / 'inputs' / science['counterpoise']['file'])}
    binding = dict(cp_attempt=directory.name, fragments_source=fragments['source'],
                   complex_input_source=evidence.reference(directory / 'inputs' /
                       science['counterpoise']['file'].removesuffix('.fragments.csv')))
    result = dict(schema='ag-cp/1', ag_version=__version__, attempt=directory.name,
                  program_version=facts.get('program_version'), protocol=science['protocol'],
                  integration_grid=integration_grid(science['route']), fragments=fragments,
                  units=dict(energy='Hartree', converted_energy='kcal/mol', distance='angstrom'),
                  hartree_to_kcal_mol=HARTREE_TO_KCAL, gas=gas,
                  solvent=_solvent(evidence, solvent_sp, science, gas, fragment_sps, binding) if solvent_sp else None,
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
                  '缺失：' + ('；'.join(solvent['missing']) or '无'), '']
        for fragment in solvent['fragment_energies']:
            if fragment['energy'] is not None:
                lines += table([(f"片段 {fragment['index']} 自身基组 SMD", fragment['energy'])]) + ['']
                lines += [f"片段来源与几何匹配：{cell(json.dumps(fragment, ensure_ascii=False))}", '']
        if solvent['interaction_raw'] is None:
            lines += ['溶剂相相互作用能（未校正/校正）：未知。', '']
        else:
            lines += table([('SMD 相互作用能', solvent['interaction_raw']),
                            ('SMD 相互作用能 + 气相 BSSE（近似）', solvent['interaction_corrected'])]) + ['']
            lines += [f"公式：{cell(solvent[key]['formula'])}" for key in ('interaction_raw', 'interaction_corrected')]
        if 'complex_source' in solvent:
            lines += ['', f"复合物来源与几何匹配：{cell(json.dumps(solvent['complex_source'], ensure_ascii=False))}"]
        lines += ['', *solvent['warnings'], '']
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
    result = report(args.attempt, study=str(root), solvent_sp=args.solvent_sp,
                    solvent_fragment_sp=args.solvent_fragment_sp, asm=args.asm)
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
    parser.add_argument('--solvent-fragment-sp', action='append', default=[], metavar='INDEX:ATTEMPT',
                        help='Existing own-basis SMD SP for CP fragment 1 or 2; repeat for each fragment')
    parser.add_argument('--asm', help='Existing ag-asm/1 report under study analyses/')
    parser.add_argument('--out', required=True, help='New JSON under study analyses/; also writes Markdown')
    parser.add_argument('--json', action='store_true')
    parser.set_defaults(func=run)
