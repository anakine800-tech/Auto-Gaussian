"""Local source checks for profile; never changes Attempts or thermo outputs.

Formula parsing is adapted from the pure _parse_formula function in
archive/skills/auto-g16-reaction-workflow/scripts/reaction_workflow.py.
No historical workflow, gates, hashes or approval machinery is used.
"""
from collections import Counter
from importlib.metadata import version
import json
import math
from pathlib import Path
import re

from ag.geometry import read_xyz
from ag.thermo import (boltzmann, _symmetry_evidence, _frequency_evidence, _pairing_evidence,
                       _frequency_input, _frequency_thermo)

# SCF Done is not the final electronic energy for these method families.
# Keep the accepted names explicit: an unknown method is not evidence of SCF
# energy semantics. R/U/RO prefixes are accepted without equating protocols.
SCF_ENERGY_METHODS = frozenset('''
hf lsda svwn svwn5 slyp blyp bp86 bpw91 bpe bpbe g96lyp g96p86 g96pw91
pw91lyp pw91p86 pw91pw91 mpwlyp mpwpw91 mpwpbe pbe pbe0 pbepbe pbe1pbe
b3lyp b3lyp5 b3p86 b3pw91 b1b95 b1lyp b1pw91 b98 b971 b972 b97d b97d3
mpw1pw91 mpw1lyp mpw1pbe mpw3pbe mpw3lyp mpw1b95 mpwlyp1m
o3lyp olyp opbe x3lyp cam-b3lyp lc-wpbe wb97 wb97x wb97xd
m05 m052x m06 m06l m062x m06hf m08hx m08so m11 m11l mn12l mn12sx mn15 mn15l
tpsstpss tpssh revtpss revtpssh vsxc hcth93 hcth147 hcth407 thcth thcthhyb
sogga11 sogga11x n12 n12sx hseh1pbe hse1pbe hse2pbe ohse1pbe ohse2pbe
'''.split())
NON_SCF_METHOD_PREFIXES = (
    'mp2', 'mp3', 'mp4', 'mp5', 'cc', 'qcisd', 'cbs', 'g1', 'g2', 'g3', 'g4',
    'b2', 'mpw2', 'dsd', 'dod', 'revdsd', 'revdod', 'pbe0dh', 'pbeqidh',
    'pwpb95', 'xyg', 'wb97x2', 'oniom', 'am1', 'pm3', 'pm6', 'pm7',
    'pddg', 'mndo', 'cndo', 'indo', 'zindo', 'dftb', 'uff', 'dreiding', 'amber',
    'cis', 'eom', 'bd', 'cas', 'sac', 'td',
)


def _method_variants(method):
    compact = method.lower().replace('-', '')
    return [compact] + [compact[len(prefix):] for prefix in ('ro', 'r', 'u')
                        if compact.startswith(prefix)]


def _scf_method_checked(method):
    variants = _method_variants(method)
    require(not any(value.startswith(NON_SCF_METHOD_PREFIXES) for value in variants)
            and any(value in {m.replace('-', '') for m in SCF_ENERGY_METHODS} for value in variants),
            f'{method}: 当前只支持 SCF 能量的方法 (SCF Done); unsupported or unrecognized method')


def integration_grid(route):
    """Record explicit Int/Integral settings without assuming default equivalence.

    Kept separate from protocol() equality so all its consumers (including
    asm) retain warning-only grid semantics without a custom dict equality.
    """
    route = re.sub(r'\s*([=,])\s*', r'\1', nonempty(route, 'Gaussian route').lower())
    settings = re.findall(r'(?<!\S)(?:integral|int)\b\s*(?:=\s*(\([^)]*\)|[^\s]+)|(\([^)]*\)))', route)
    return '; '.join(re.sub(r'\s+', '', a or b).strip('()') for a, b in settings) if settings else 'program_default'


def grid_warnings(entries):
    if len({grid for _, grid in entries}) <= 1:
        return []
    return ['积分网格设置不同（仅警告）：' + '; '.join(f'{label}={grid}' for label, grid in entries)
            + '。program_default 随程序版本而异，未推断与显式网格等价。']


DEFAULT_SETTINGS = {
    'temperature_K': 298.15, 'concentration_mol_L': 1.0, 'qs': 'grimme',
    'qh': 'head_gordon', 's_cutoff_cm1': 100.0, 'h_cutoff_cm1': 100.0,
    'frequency_scale': 1.0, 'zpe_scale': 1.0,
    'rotational_symmetry': 'from_output', 'inertia': 'global',
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def finite(value, label, positive=False):
    require(isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and (not positive or value > 0),
            f'{label}: expected a finite {"positive " if positive else ""}number')
    return float(value)


def integer(value, label, positive=False):
    require(type(value) is int and (not positive or value > 0),
            f'{label}: expected a {"positive " if positive else ""}integer')
    return value


def nonempty(value, label):
    require(isinstance(value, str) and bool(value.strip()), f'{label}: missing text')
    return value


def read_json(path):
    # Duplicate names can silently drop a species or change stoichiometry.
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, f'Duplicate JSON key: {key}')
            result[key] = value
        return result
    value = json.loads(Path(path).read_text(), object_pairs_hook=pairs)
    require(isinstance(value, dict), f'{Path(path).name}: expected a JSON object')
    return value


def parse_formula(value):
    formula = nonempty(value, 'formula')
    position, counts = 0, Counter()
    for match in re.finditer(r'([A-Z][a-z]?)(\d*)', formula):
        require(match.start() == position, f'Unsupported formula: {formula}')
        count = int(match[2] or '1')
        require(count > 0, 'Non-positive element count')
        counts[match[1]] += count
        position = match.end()
    require(position == len(formula) and counts, f'Unsupported formula: {formula}')
    return dict(counts)


def local_path(study, base, value):
    path = (base / nonempty(value, 'local path')).resolve()
    require(path.is_relative_to(study), 'Profile sources must be local to this study')
    require(path.exists(), f'Missing source: {value}')
    return path


def protocol(route):
    """Conservative Gaussian route extraction; ambiguous/custom protocols fail.

    Do not guess Gen/GenECP contents or SCRF=Read dielectric/basis data. Job
    keywords (Opt/Freq/SP) do not distinguish the electronic method layers.
    """
    route = nonempty(route, 'Gaussian route').lower()
    route = re.sub(r'\s*([=,/])\s*', r'\1', route)
    # Preserve whitespace outside parentheses: dropping it joins a basis like
    # 6-31+G(d) to the following Opt/Freq keyword and falsely changes protocol.
    route = re.sub(r'\(\s*', '(', route)
    route = re.sub(r'\s*\)', ')', route)
    # Catch basis-free composite/semiempirical routes and layered ONIOM before
    # the explicit method/basis diagnostic, as well as extra correlated/TD jobs.
    tokens = re.findall(r'(?<!\S)([a-z][a-z0-9-]*)(?=[\s/(=]|$)', route)
    require(not any(value.startswith(NON_SCF_METHOD_PREFIXES)
                    for token in tokens for value in _method_variants(token)),
            '当前只支持 SCF 能量的方法 (SCF Done); correlated/composite/double-hybrid/'
            'semiempirical/ONIOM methods are unsupported')
    pairs = re.findall(r'(?<!\S)([a-z0-9+_()\-]+)/([^\s]+)', route)
    require(len(pairs) == 1, 'Expected one explicit method/basis in Gaussian route')
    method, basis = pairs[0]
    _scf_method_checked(method)
    require(basis not in {'gen', 'genecp', 'chkbasis'} and 'extrabasis' not in route
            and 'pseudo' not in route and 'iop' not in route,
            'Custom basis/ECP/IOp protocol is not supported by profile')
    dispersion = re.findall(r'\b(?:empiricaldispersion|em)=(\([^)]*\)|[^\s]+)', route)
    require(len(dispersion) <= 1, 'Ambiguous dispersion settings')
    model, solvent = 'none', 'none'
    scrf = re.findall(r'\bscrf(?:=)?(\([^)]*\)|[^\s]*)', route)
    require(len(scrf) <= 1, 'Ambiguous solvent settings')
    if scrf:
        options = scrf[0].strip('()').split(',')
        models = [x for x in options if x in {'smd', 'pcm', 'iefpcm', 'cpcm', 'dipole', 'ipcm', 'scipcm'}]
        solvents = [x.split('=', 1)[1] for x in options if x.startswith('solvent=')]
        require(len(models) == len(solvents) == 1 and len(options) == 2,
                'SCRF needs explicit model and solvent; custom/read options are unsupported')
        model, solvent = models[0], solvents[0]
    basis_types = re.findall(r'(?<!\S)(5d|6d|7f|10f)(?!\S)', route)
    require(not ({'5d', '6d'} <= set(basis_types) or {'7f', '10f'} <= set(basis_types)),
            'Conflicting basis function types')
    basis_type = ' '.join(x.upper() for x in ('5d', '6d', '7f', '10f') if x in basis_types)
    return {'method': method, 'basis': basis,
            'basis_function_type': basis_type or 'basis_default',
            'dispersion': dispersion[0] if dispersion else 'method_default',
            'solvent_model': model, 'solvent': solvent}


def settings_checked(settings):
    require(isinstance(settings, dict) and set(settings) == set(DEFAULT_SETTINGS),
            'Incomplete or unsupported thermo settings')
    for key in ('temperature_K', 'concentration_mol_L', 's_cutoff_cm1',
                'h_cutoff_cm1', 'frequency_scale', 'zpe_scale'):
        finite(settings[key], key, positive=True)
    require(settings['qs'] in {'grimme', 'truhlar'} and settings['qh'] == 'head_gordon'
            and settings['rotational_symmetry'] == 'from_output'
            and settings['inertia'] == 'global', 'Unsupported low-frequency/symmetry treatment')
    return settings


def _printed_solvent(block, offset, label):
    """Read bounded PCM summaries, never route/checkpoint defaults.

    Gaussian's PCM/SMD layout is also documented in cclib's Gaussian parser:
    https://github.com/cclib/cclib/blob/master/cclib/parser/gaussianparser.py
    Every repeated summary must be complete and agree; a truncated final block
    must not borrow an earlier optimization cycle's solvent parameters.
    """
    from ag._parse_outputs import NUMBER, number
    lines = block.splitlines()
    starts = [i for i, line in enumerate(lines)
              if re.fullmatch(r'\s*Polarizable Continuum Model \(PCM\)\s*', line)]
    result, locations = None, []
    for start in starts:
        end = next((i for i in range(start + 1, len(lines))
                    if re.fullmatch(r'\s*-{5,}\s*', lines[i])), None)
        require(end is not None, f'{label}: incomplete printed solvent parameter block')
        fields, field_indent, current = {}, None, None
        for line in lines[start + 1:end]:
            if not line.strip():
                continue
            if not fields and re.fullmatch(r'\s*={5,}\s*', line):
                continue
            indent = len(line) - len(line.lstrip())
            # Gaussian aligns continued cavity/derivative descriptions after
            # the colon. They can themselves contain colons; keep them with
            # their owning field rather than inventing duplicate field names.
            if field_indent is not None and indent > field_indent:
                fields[current] += ' ' + ' '.join(line.lower().split())
                continue
            match = re.fullmatch(r'\s*([^:]+?)\s*:\s*(\S.*?)\s*', line)
            require(match is not None, f'{label}: unparseable printed solvent parameter block')
            key = ' '.join(match[1].lower().split())
            require(key not in fields, f'{label}: duplicate printed solvent parameter {key}')
            fields[key] = ' '.join(match[2].lower().split())
            field_indent, current = indent, key
        require(all(k in fields for k in ('model', 'atomic radii', 'solvent')),
                f'{label}: missing model/radii/solvent in printed parameter block')
        printed_model = fields.pop('model').removesuffix('.')
        radii = fields.pop('atomic radii').removesuffix('.')
        require(printed_model in {'pcm', 'iefpcm', 'c-pcm'},
                f'{label}: unsupported printed solvent model {printed_model!r}')
        solvent = re.fullmatch(r'([a-z][a-z0-9_() +,\-]*?),\s*eps\s*=\s*(' + NUMBER
                              + r')\s+eps\(inf\)\s*=\s*(' + NUMBER + r')', fields.pop('solvent'), re.I)
        require(solvent is not None and solvent[1] != 'generic',
                f'{label}: missing named solvent/epsilon/epsilon_infinite in printed block')
        epsilon, epsilon_infinite = number(solvent[2]), number(solvent[3])
        require(epsilon > 0 and epsilon_infinite > 0,
                f'{label}: invalid printed solvent dielectric constants')
        require(radii != 'smd-coulomb' or printed_model in {'pcm', 'iefpcm'},
                f'{label}: unsupported SMD electrostatic model')
        values = {'model': 'smd' if radii == 'smd-coulomb' else printed_model.replace('c-pcm', 'cpcm'),
                  'solvent': solvent[1], 'epsilon': epsilon, 'epsilon_infinite': epsilon_infinite,
                  'printed_model': printed_model, 'atomic_radii': radii,
                  'other_parameters': fields}
        require(result is None or result == values,
                f'{label}: conflicting printed solvent parameter blocks within section')
        result = values
        locations.append({'start_line': offset + start + 1, 'end_line': offset + end + 1})
    return {'values': result, 'blocks': locations} if result is not None else None


def _section_protocol(section, block, label):
    route = section.get('route') or ''
    require(len(re.findall(r'\bscrf\b', route, re.I)) <= 1, 'Ambiguous solvent settings')
    check = r'\bscrf\b\s*=?\s*(?:\(\s*check\s*\)|check\b)'
    inherited_solvent = bool(re.search(check, route, re.I))
    method = protocol(re.sub(check, '', route, flags=re.I) if inherited_solvent else route)
    require(method['dispersion'].strip('()') not in {'check', 'read'},
            f'{label}: unsupported inherited dispersion; explicit or recognized printed evidence is required')
    solvent = _printed_solvent(block, section['start_line'] - 1, label) if block is not None else None
    require(not inherited_solvent or solvent is not None,
            f'{label}: SCRF=Check requires a complete printed solvent parameter block')
    evidence = {}
    if solvent is not None:
        values = solvent['values']
        # Explicit declarations must agree with this same section's output.
        # The parent's route is never used to resolve an inherited solvent.
        if not inherited_solvent and method['solvent_model'] != 'none':
            require(method['solvent_model'] == values['model'] and method['solvent'] == values['solvent'],
                    f'{label}: explicit solvent route disagrees with its printed parameter block')
        method.update(solvent_model=values['model'], solvent=values['solvent'],
                      solvent_parameters={k: v for k, v in values.items() if k not in {'model', 'solvent'}})
        evidence['solvent'] = solvent
    return method, evidence


def _printed_condition(block, offset, key, label):
    """Resolve only recognized same-section basis/dispersion diagnostics."""
    matches = []
    for i, line in enumerate((block or '').splitlines(), offset + 1):
        if key == 'dispersion':
            match = re.search(r'^\s*R6Disp:\s+Grimme-(D2|D3\(BJ\)|D3)\s+Dispersion energy\s*=', line, re.I)
            value = {'d2': 'gd2', 'd3': 'gd3', 'd3(bj)': 'gd3bj'}.get(match[1].lower()) if match else None
        else:
            match = re.fullmatch(r'\s*Standard basis:\s*\S+\s+\((5D|6D),\s*(7F|10F)\)\s*', line, re.I)
            value = f'{match[1].upper()} {match[2].upper()}' if match else None
        if value is not None:
            matches.append((i, value))
    require(matches and len({v for _, v in matches}) == 1,
            f'{label}: missing or conflicting same-section printed {key} evidence')
    return {'value': matches[0][1], 'lines': [i for i, _ in matches]}


def section_source(facts, attempt_id, *, frequency=True, directory=None):
    """Bind a thermo layer to the section that supplied its facts.

    The first route and last SCF can belong to different jobs. Never relabel
    one layer with another job's protocol, or guess checkpoint-only settings.
    """
    sections = facts.get('job_sections')
    sources = facts.get('fact_sources', {})
    require(isinstance(sections, list) and bool(sections),
            f'{attempt_id}: missing job section evidence; regenerate ag facts')
    key = 'n_imag' if frequency else 'energies.scf'
    index = sources.get(key)
    selected = [s for s in sections if s.get('index') == index]
    require(type(index) is int and len(selected) == 1,
            f'{attempt_id}: ambiguous {key} section source; regenerate ag facts')
    section = selected[0]
    require(section.get('termination') == 'normal',
            f'{attempt_id}: section {index} has non-normal termination')
    # Cached single-job tests/legacy records may lack logs; explicit routes
    # retain their old handling. Checkpoint inheritance always requires a log.
    blocks = {}
    if directory is not None and (directory / 'manifest.json').is_file() and (directory / 'outputs').is_dir():
        from ag.facts import gaussian_log
        from ag._parse_outputs import gaussian_job_sections, gaussian_section_text
        text = gaussian_log(directory).read_text(errors='replace')
        actual, _ = gaussian_job_sections(text)
        require(len(actual) == len(sections) and all(
            all(a[k] == s.get(k) for k in ('index', 'route', 'start_line', 'end_line', 'termination'))
            for a, s in zip(actual, sections)),
            f'{attempt_id}: job sections differ from facts; regenerate ag facts')
        blocks = {s['index']: gaussian_section_text(text, s) for s in sections}
    route = section.get('route')
    try:
        method, evidence = _section_protocol(section, blocks.get(index), f'{attempt_id}: section {index}')
    except ValueError as exc:
        raise ValueError(f'{attempt_id}: section {index} protocol: {exc}') from exc
    if frequency:
        require(bool(re.search(r'\bfreq\b', route, re.I)),
                f'{attempt_id}: section {index} has no explicit Freq route')
        keys = ('freq_step_converged', 'freq_step_convergence', 'vibrational_modes_complete',
                'n_vibrational_modes', 'expected_vibrational_modes', 'frequencies_low', 'imag_modes')
        keys += tuple('energies.' + k for k in ('zpe', 'e_thermal', 'h', 'g')
                      if facts.get('energies', {}).get(k) is not None)
        require(all(sources.get(k) == index for k in keys if k in facts or k.startswith('energies.')),
                f'{attempt_id}: frequency/thermal facts have inconsistent section sources')
        differences, comparisons = [], []
        participants = [(section, method, evidence)]
        for other in sections:
            if other['index'] == index or not re.search(r'\bopt\b', other.get('route') or '', re.I):
                continue
            try:
                opt, opt_evidence = _section_protocol(other, blocks.get(other['index']),
                                                      f"{attempt_id}: Opt section {other['index']}")
            except ValueError as exc:
                raise ValueError(f"{attempt_id}: Opt section {other['index']} protocol: {exc}") from exc
            participants.append((other, opt, opt_evidence))
        # Resolve omitted conditions for all sections before comparing any
        # pair. Otherwise a later Opt could change the selected protocol after
        # an earlier Opt has already been checked. Never copy the Opt route.
        for key, default, diagnostic in (
                ('dispersion', 'method_default', r'^\s*R6Disp:'),
                ('basis_function_type', 'basis_default', r'^\s*Standard basis:')):
            values = {p[1][key] for p in participants}
            printed_any = any(re.search(diagnostic, blocks.get(s['index'], ''), re.M)
                              for s, _, _ in participants)
            # A normal Standard basis line is not itself evidence of a chk
            # override. Preserve the existing gas-phase basis_default layer;
            # resolve its type only when a section's route differs.
            if default in values and (len(values) > 1 or key == 'dispersion' and printed_any):
                for selected_section, values, record in participants:
                    try:
                        printed = _printed_condition(blocks.get(selected_section['index']),
                            selected_section['start_line'] - 1, key,
                            f"{attempt_id}: section {selected_section['index']}")
                        agrees = (values[key] in (default, printed['value']) or
                                  (key == 'basis_function_type'
                                   and set(values[key].split()) <= set(printed['value'].split())))
                        require(agrees,
                                f'{attempt_id}: explicit {key} disagrees with same-section printed evidence')
                        values[key] = printed['value']
                        record[key] = printed
                    except ValueError as exc:
                        differences.append(str(exc))
        for other, opt, opt_evidence in participants[1:]:
            differences.extend(f"{key}: Opt section {other['index']}={opt.get(key)!r}; "
                               f"Freq section {index}={method.get(key)!r}"
                               for key in sorted(method.keys() | opt.keys()) if opt.get(key) != method.get(key))
            if opt_evidence:
                comparisons.append({'section_index': other['index'], 'printed_conditions': opt_evidence})
        require(not differences, f'{attempt_id}: inconsistent Opt/Freq protocols:\n' + '\n'.join(differences))
    source = {'attempt_id': attempt_id, 'section_index': index,
            'start_line': section['start_line'], 'end_line': section['end_line'],
            'route': route, 'protocol': method}
    if evidence:
        source['printed_conditions'] = evidence
        if frequency:
            source['compared_opt_sections'] = comparisons
    return source


def attempt_facts(study, attempt_id, *, cached, frequency=True):
    require(isinstance(attempt_id, str) and re.fullmatch(r'[A-Za-z0-9_-]+', attempt_id),
            'Expected a local Attempt ID')
    directory = local_path(study, study / 'attempts', attempt_id)
    if cached and (directory / 'facts.json').is_file():
        facts = read_json(directory / 'facts.json')
        require(facts.get('termination') == 'normal', f'{attempt_id}: non-normal termination')
        if frequency:
            require(type(facts.get('n_imag')) is int and facts['n_imag'] in (0, 1),
                    f'{attempt_id}: n_imag must be 0 or 1')
            _frequency_evidence(facts, attempt_id)
        source = section_source(facts, attempt_id, frequency=frequency, directory=directory)
        geometry = local_path(study, directory, facts.get('final_geometry'))
        frames = read_xyz(geometry)
        require(len(frames) == 1, f'{attempt_id}: expected one final geometry')
        elements = Counter(frames[0].symbols)
    else:
        from ag._parse_outputs import parse_gaussian
        from ag.facts import gaussian_log
        facts, geometry = parse_gaussian(gaussian_log(directory), directory / 'outputs' / 'job.pbs.out')
        require(facts.get('termination') == 'normal', f'{attempt_id}: non-normal termination')
        if frequency:
            require(type(facts.get('n_imag')) is int and facts['n_imag'] in (0, 1),
                    f'{attempt_id}: n_imag must be 0 or 1')
            _frequency_evidence(facts, attempt_id)
        source = section_source(facts, attempt_id, frequency=frequency, directory=directory)
        if frequency:
            _, geometry = _frequency_input(directory, facts, source)
        require(geometry is not None, f'{attempt_id}: missing final geometry')
        elements = Counter(line.split()[0] for line in geometry.splitlines()[2:] if line.strip())
    require(facts.get('termination') == 'normal', f'{attempt_id}: non-normal termination')
    require(facts.get('n_atoms') == sum(elements.values()), f'{attempt_id}: atom count mismatch')
    integer(facts.get('charge'), f'{attempt_id} charge')
    integer(facts.get('multiplicity'), f'{attempt_id} multiplicity', positive=True)
    return directory, facts, dict(elements), source['protocol']


def check_review(directory):
    review = (directory / 'review.md').read_text()
    # The existing prose review has no machine-readable verdict. These two
    # explicit result lines avoid interpreting a negated sentence as a pass.
    require(re.findall(r'^profile_review:\s*(\S+)\s*$', review, re.M) == ['pass']
            and re.findall(r'^imaginary_mode_matches:\s*(\S+)\s*$', review, re.M) == ['true'],
            f'{directory.name}: TS review must pass and confirm imaginary-mode direction')


def load_species(name, spec, study, analyses, direct_settings):
    require(isinstance(spec, dict), f'{name}: expected species object')
    require(set(spec) <= {'thermo', 'attempts', 'single_conformer_reason', 'formula', 'charge'},
            f'{name}: unknown species field')
    require(('thermo' in spec) != ('attempts' in spec), f'{name}: choose thermo or attempts')
    cached = 'thermo' in spec
    if cached:
        source = local_path(study, analyses, spec['thermo'])
        data = read_json(source)
        require(data.get('schema') == 'ag-thermo/1' and data.get('goodvibes_version') == '4.3.0'
                and data.get('units', {}).get('energy') == 'Hartree', f'{name}: expected ag thermo output')
        settings = settings_checked(data.get('settings'))
        rows = data.get('rows')
        require(isinstance(rows, list) and rows, f'{name}: empty thermo ensemble')
    else:
        settings = settings_checked(dict(direct_settings))
        rows = spec['attempts']
        require(isinstance(rows, list) and rows, f'{name}: empty Attempt ensemble')
        from goodvibes.thermo import ThermoOptions
        from ag.facts import gaussian_log
        require(version('goodvibes') == '4.3.0', 'profile requires GoodVibes 4.3.0')
        options = ThermoOptions(QS=settings['qs'], QH=True,
            s_freq_cutoff=settings['s_cutoff_cm1'], h_freq_cutoff=settings['h_cutoff_cm1'],
            temperature=settings['temperature_K'], concentration=settings['concentration_mol_L'],
            freq_scale_factor=settings['frequency_scale'], zpe_scale_factor=settings['zpe_scale'])
    if len(rows) == 1:
        nonempty(spec.get('single_conformer_reason'), f'{name}: single_conformer_reason')
    identities, protocols, energies, degeneracies, ids, program_versions = [], [], [], [], [], []
    conformers = []
    grids = []
    for row in rows:
        require(isinstance(row, dict), f'{name}: each Attempt must be an object')
        aid = row.get('attempt_id')
        require(aid not in ids, f'{name}: duplicate Attempt')
        directory, facts, elements, freq_protocol = attempt_facts(study, aid, cached=cached)
        frequency_source = section_source(facts, aid, directory=directory)
        electronic_source = frequency_source
        ids.append(aid)
        program_versions.append(nonempty(facts.get('program_version'), f'{aid}: program version missing; regenerate ag facts'))
        n_imag = facts.get('n_imag')
        require(type(n_imag) is int and n_imag in (0, 1), f'{aid}: n_imag must be 0 or 1')
        frequency_evidence = _frequency_evidence(facts, aid)
        frequency_grid = integration_grid(frequency_source['route'])
        grids.append((f'{aid}/frequency', frequency_grid))
        if n_imag == 1:
            check_review(directory)
        identities.append((elements, facts['charge'], facts['multiplicity'], n_imag))
        sp_protocol, delta = None, 0.0
        sp_id = row.get('spc_attempt_id')
        pairing = row.get('pairing_evidence') if cached else None
        sp_grid = None
        if not cached:
            block, geometry = _frequency_input(directory, facts, frequency_source)
            result = _frequency_thermo(block, options, facts['program_version'])
        if sp_id:
            sp_directory, sp_facts, sp_elements, sp_protocol = attempt_facts(
                study, sp_id, cached=cached, frequency=False)
            electronic_source = section_source(sp_facts, sp_id, frequency=False, directory=sp_directory)
            sp_grid = integration_grid(electronic_source['route'])
            grids.append((f'{sp_id}/single_point', sp_grid))
            program_versions.append(nonempty(sp_facts.get('program_version'), f'{sp_id}: program version missing; regenerate ag facts'))
            require((elements, facts['charge'], facts['multiplicity']) ==
                    (sp_elements, sp_facts['charge'], sp_facts['multiplicity']),
                    f'{aid}: SPC identity mismatch')
            sp_energy = finite(sp_facts.get('energies', {}).get('scf'), 'SP energy')
            if cached:
                # Preserve the cached-layer finite-energy checks. A multi-job
                # facts SCF can be a trailing SP, so use the bound thermo value.
                finite(row.get('frequency_E') if len(facts['job_sections']) > 1 else
                       facts.get('energies', {}).get('scf'), 'frequency energy')
            if not cached:
                # Reuse the exact thermo input-hash and fixed-row Kabsch check,
                # including TS refinement. Parse geometry in memory only.
                pairing = _pairing_evidence(directory, facts, sp_directory, sp_facts, geometry)
                delta = sp_energy - finite(result.scf_energy, 'frequency energy')
        protocols.append({'frequency': freq_protocol, 'single_point': sp_protocol})
        if cached:
            # Old multi-section caches may have labeled Freq data with Opt's
            # route. Require explicit binding instead of silently endorsing it.
            if (len(facts['job_sections']) > 1 or row.get('frequency_source') is not None
                    or 'printed_conditions' in frequency_source
                    or sp_id and (len(sp_facts['job_sections']) > 1 or 'printed_conditions' in electronic_source)):
                require(row.get('frequency_source') == frequency_source
                        and row.get('electronic_energy_source') == electronic_source,
                        f'{aid}: cached thermo section sources differ or are missing; regenerate ag thermo')
            energy = finite(row.get('qh_G'), f'{aid}: qh_G')
            enthalpy = finite(row.get('qh_H'), f'{aid}: qh_H')
            entropy = finite(row.get('qh_S'), f'{aid}: qh_S')
            symmetry = {key: row.get(key) for key in
                        ('rotational_symmetry_number', 'rotational_symmetry_source')}
        else:
            require(set(row) <= {'attempt_id', 'degeneracy', 'spc_attempt_id'}, f'{aid}: unknown Attempt field')
            energy = finite(getattr(result, 'qh_gibbs_free_energy', None), f'{aid}: qh_G') + delta
            enthalpy = finite(getattr(result, 'qh_enthalpy', None), f'{aid}: qh_H') + delta
            entropy = finite(getattr(result, 'qh_entropy', None), f'{aid}: qh_S')
            symmetry = _symmetry_evidence(result, gaussian_log(directory), frequency_source)
        # Prevent mismatched qh/RRHO or SPC columns from inventing an entropy term.
        require(math.isclose(enthalpy - settings['temperature_K'] * entropy, energy,
                             rel_tol=0, abs_tol=1e-6), f'{aid}: qh_H - T*qh_S disagrees with qh_G')
        integer(symmetry['rotational_symmetry_number'], f'{aid}: rotational_symmetry_number', positive=True)
        provenance = symmetry['rotational_symmetry_source']
        require(isinstance(provenance, dict) and provenance.get('kind') in
                {'gaussian_output', 'goodvibes_default'}, f'{aid}: missing rotational symmetry source')
        conformers.append({'attempt_id': aid, 'qh_G_hartree': energy,
                          'frequency_evidence': frequency_evidence,
                          'frequency_source': frequency_source, 'electronic_energy_source': electronic_source,
                          'pairing_evidence': pairing,
                          'spc_attempt_id': sp_id,
                          'integration_grid': {'frequency': frequency_grid, 'single_point': sp_grid},
                          'qh_H_hartree': enthalpy, 'qh_S_hartree_per_K': entropy,
                          **symmetry, 'nosymm': bool(re.search(r'\bnosymm\b', frequency_source['route'], re.I))})
        energies.append(energy)
        degeneracies.append(integer(row.get('degeneracy', 1), f'{aid}: degeneracy', positive=True))
    require(all(x == identities[0] for x in identities), f'{name}: mixed conformer identities or n_imag')
    # Different revisions can change numerical energies even at the same route.
    require(len(set(program_versions)) == 1, f'{name}: inconsistent program versions within species/SPC')
    require(all(x == protocols[0] for x in protocols), f'{name}: mixed conformer protocols')
    populations, _, ensemble = boltzmann(energies, degeneracies, settings['temperature_K'])
    if cached:
        supplied = finite(data.get('ensemble_G'), f'{name}: ensemble_G')
        require(math.isclose(ensemble, supplied, rel_tol=0, abs_tol=1e-9),
                f'{name}: ensemble_G disagrees with conformer partition sum')
        ensemble = supplied
    enthalpy = math.fsum(p * c['qh_H_hartree'] for p, c in zip(populations, conformers))
    for conformer, population, degeneracy in zip(conformers, populations, degeneracies):
        conformer.update(population=population, degeneracy=degeneracy)
    elements, charge, multiplicity, n_imag = identities[0]
    if 'formula' in spec:
        require(parse_formula(spec['formula']) == elements, f'{name}: declared formula differs from geometry')
    if 'charge' in spec:
        require(integer(spec['charge'], 'declared charge') == charge, f'{name}: declared charge mismatch')
    return {'ensemble_G_hartree': ensemble, 'elements': elements, 'charge': charge,
            'ensemble_H_hartree': enthalpy,
            'ensemble_S_hartree_per_K': (enthalpy - ensemble) / settings['temperature_K'],
            'lowest_conformer_G_hartree': min(energies), 'conformers': conformers,
            'multiplicity': multiplicity, 'n_imag': n_imag, 'settings': settings,
            'protocol': protocols[0], 'attempts': ids, 'program_version': program_versions[0],
            'warnings': grid_warnings(grids),
            'single_conformer_reason': spec.get('single_conformer_reason')}
