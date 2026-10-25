"""Balanced reaction free-energy profiles from local species ensembles."""
from collections import Counter
import json
import math
from pathlib import Path
import re

from ag._profile_sources import (DEFAULT_SETTINGS, finite, integer, load_species,
                                 nonempty, read_json, require, grid_warnings)
from ag.thermo import HARTREE_TO_KCAL, R_HARTREE

R_KCAL = R_HARTREE * HARTREE_TO_KCAL
R_L_ATM = 0.082057366080960
K_B_OVER_H = 1.380649e-23 / 6.62607015e-34
DECOMPOSITION_NOTE = ('H_ens = sum(p_i qh_H_i); S_ens = (H_ens - G_ens)/T; '
                      'p_i proportional to d_i exp(-qh_G_i/RT). '
                      '标准态修正和显式溶剂浓度修正全部记入 −TΔS；构象熵与简并度包含在系综 S 中。'
                      'SMD 下这些是模型审计分项，不是实验溶液的焓熵分解。')
KINETICS_NOTE = ('k = (k_B T/h) exp(-ΔG‡/RT); half_life = ln(2)/k; κ = 1。'
                 '没有隧穿校正，不是微观动力学模型；半衰期仅为不可逆一级/准一级近似。'
                 '超出浮点表示范围的指数结果记为 null，并保留自然对数。')
SELECTIVITY_NOTE = ('w_p = sum(paths * exp(-G_TS/RT)); fraction_p = w_p / sum(w_p); '
                    '有效能垒为 -RT ln w_p，相对最低者；ΔΔG‡ = G_eff(b) - G_eff(a)，ratio_a_over_b = w_a/w_b。'
                    '构象简并度已含在系综 G 中，paths 仅计未枚举的等价反应路径，不重复计权。'
                    '相同前因子、κ = 1、共同反应物参考态；比例和 ee 是简单 TST 下的表观值。'
                    '仅对映产物可解释为 ee；可逆步骤或后续选择性捕获时不能等同于实验 ee。'
                    '最低构象仅作敏感性参考。计算采用平移后的对数权重，比例溢出记 null 并保留自然对数。')
SPAN_DOI = '10.1021/ar1000956'
FORMULAS = {
    'ensemble': 'G_s = -RT ln sum_i d_i exp(-G_si/RT); never sum_i p_i G_si',
    'composite': 'G_si = E_SP,si + (G_qh,freq,si - E_freq,si)',
    'standard_state': 'G_s(target) = G_s(source) + RT ln(C_target/C_source); C_1atm = 1/(R_L_atm T)',
    'explicit_solvent': 'G_s(c) = G_s(target) + RT ln(c_s/C_target)',
    'state': 'G_state = sum_s nu_s G_s; DeltaG_state = G_state - G_reference',
    'forward': 'DeltaG_forward = G_TS - G_reactant',
    'reverse': 'DeltaG_reverse = G_TS - G_product',
    'reaction': 'DeltaG_reaction = G_product - G_reactant',
    'span': 'deltaE = max_ij [G_TS_i - G_I_j + (DeltaG_cycle if TS_i precedes I_j else 0)]; DeltaG_cycle = G_end - G_start',
}


def energetic_span(states):
    """Kozuch–Shaik eq 9: ordered, one-turnover profile, terminal replica excluded.

    Include all co-maximal pairs instead of arbitrarily declaring a single
    rate-controlling state when two contributions are equal within rounding.
    """
    reaction = states[-1]['relative_G_kcal'] - states[0]['relative_G_kcal']
    pairs = []
    for i, ts in enumerate(states[:-1]):
        if ts['kind'] != 'ts':
            continue
        for j, intermediate in enumerate(states[:-1]):
            if intermediate['kind'] != 'minimum':
                continue
            correction = reaction if i < j else 0.0
            pairs.append({'TDTS': ts['id'], 'TDI': intermediate['id'],
                          'cycle_correction_kcal': correction,
                          'delta_E_kcal': ts['relative_G_kcal'] - intermediate['relative_G_kcal'] + correction})
    require(bool(pairs), 'A catalytic cycle needs intermediates and transition states')
    maximum = max(p['delta_E_kcal'] for p in pairs)
    dominant = [p for p in pairs if math.isclose(p['delta_E_kcal'], maximum, rel_tol=0, abs_tol=1e-8)]
    return {'delta_E_kcal': maximum, 'TDTS': sorted({p['TDTS'] for p in dominant}),
            'TDI': sorted({p['TDI'] for p in dominant}), 'determining_pairs': dominant,
            'pairs': pairs, 'reaction_G_kcal': reaction, 'doi': SPAN_DOI,
            'formula': FORMULAS['span'],
            'note': 'Forward-cycle energetic-span approximation, not a full microkinetic model or proof of mechanism. '
                    'For non-exergonic cycles this is a formal span, not a forward TOF estimate.'}


def step_table(states):
    return [{'reactant': a['id'], 'ts': ts['id'], 'product': b['id'],
             'forward_barrier_kcal': ts['relative_G_kcal'] - a['relative_G_kcal'],
             'reverse_barrier_kcal': ts['relative_G_kcal'] - b['relative_G_kcal'],
             'reaction_G_kcal': b['relative_G_kcal'] - a['relative_G_kcal'],
             'formulas': {'forward': f"G({ts['id']}) - G({a['id']})",
                          'reverse': f"G({ts['id']}) - G({b['id']})",
                          'reaction': f"G({b['id']}) - G({a['id']})"}}
            for a, ts, b in zip(states[::2], states[1::2], states[2::2])]


def _represented_exp(log_value):
    # Extreme barriers must not make an otherwise valid legacy profile fail
    # or silently turn a tiny positive rate into zero/infinite half-life.
    try:
        value = math.exp(log_value)
    except OverflowError:
        return None
    return value if value > 0 else None


def eyring(barrier_kcal, temperature):
    log_k = math.log(K_B_OVER_H * temperature) - barrier_kcal / (R_KCAL * temperature)
    log_half_life = math.log(math.log(2)) - log_k
    return {'k_s-1': _represented_exp(log_k), 'half_life_s': _represented_exp(log_half_life),
            'ln_k_s-1': log_k, 'ln_half_life_s': log_half_life}


def step_decomposition(steps, states, species, temperature, standard_state):
    for step, (a, ts, b) in zip(steps, zip(states[::2], states[1::2], states[2::2])):
        step['molecule_counts'] = {key: row['molecule_count'] for key, row in
                                   (('reactant', a), ('ts', ts), ('product', b))}
        step['molecularity_change'] = ts['molecule_count'] - a['molecule_count']
        step['reverse_molecularity_change'] = ts['molecule_count'] - b['molecule_count']
        step['reaction_molecularity_change'] = b['molecule_count'] - a['molecule_count']
        for direction, start, end, g_key in (
                ('forward', a, ts, 'forward_barrier_kcal'),
                ('reverse', b, ts, 'reverse_barrier_kcal'),
                ('reaction', a, b, 'reaction_G_kcal')):
            dh = math.fsum((end['species'].get(s, 0) - start['species'].get(s, 0))
                           * item['ensemble_H_hartree'] * HARTREE_TO_KCAL
                           for s, item in species.items())
            step[f'{direction}_dH_kcal'] = dh
            step[f'{direction}_minus_TdS_kcal'] = step[g_key] - dh
            if direction == 'reaction':
                continue
            # Cancel explicit spectators before identifying bimolecularity.
            reacting_count = sum(max(n - end['species'].get(s, 0), 0)
                                 for s, n in start['species'].items())
            notes = []
            if end['molecule_count'] < start['molecule_count']:
                notes.append('按标准态浓度的准一级近似，受缔合熵模型影响')
            elif end['molecule_count'] > start['molecule_count']:
                notes.append('分子数变化，受缔合熵模型影响（反向为缔合）')
            if standard_state == '1M' and reacting_count == 2 and step[g_key] < 5:
                notes.append('接近扩散控制，不宜用 TST 速率解释')
            step[f'{direction}_kinetics'] = {**eyring(step[g_key], temperature), 'notes': notes}


def selectivity_definitions(data, specs):
    entries = data.get('selectivity', [])
    require(isinstance(entries, list), 'selectivity must be a list')
    identifiers, used = set(), set()
    for entry in entries:
        require(isinstance(entry, dict) and {'id', 'products'} <= set(entry)
                and set(entry) <= {'id', 'products', 'perturb_kcal'},
                'Each selectivity entry needs id, products and optional perturb_kcal')
        label = nonempty(entry['id'], 'selectivity id')
        require(label not in identifiers, f'Duplicate selectivity id: {label}')
        identifiers.add(label)
        products = entry['products']
        require(isinstance(products, dict) and len(products) >= 2,
                f'{label}: selectivity needs at least two products')
        # Repeated TS entries double-count flux or assign it to two products.
        locations = {}
        for product, channels in products.items():
            nonempty(product, f'{label}: product label')
            require(isinstance(channels, list) and channels, f'{label}/{product}: empty TS channels')
            for index, channel in enumerate(channels, 1):
                require(isinstance(channel, dict) and 'species' in channel
                        and set(channel) <= {'species', 'paths'}, f'{label}: channel needs species and optional paths')
                name = nonempty(channel['species'], f'{label}: TS species')
                require(name in specs, f'{label}: missing species {name}')
                location = f'product {product!r} channel {index}'
                if name in locations:
                    raise ValueError(f'{label}: duplicate TS species {name!r} at {location}; '
                                     f'first at {locations[name]}; express path degeneracy using paths')
                locations[name] = location
                integer(channel.get('paths', 1), f'{label}/{name}: paths', positive=True)
                used.add(name)
        if 'perturb_kcal' in entry:
            value = finite(entry['perturb_kcal'], f'{label}: perturb_kcal')
            require(value >= 0, f'{label}: perturb_kcal must be non-negative')
    return entries, used


def selectivity_distribution(products, energies, temperature):
    rt = R_KCAL * temperature
    origin = min(energies.values())
    logs = {}
    for label, channels in products.items():
        weights = [math.log(c.get('paths', 1)) - (energies[c['species']] - origin) / rt for c in channels]
        offset = max(weights)
        logs[label] = offset + math.log(math.fsum(math.exp(w - offset) for w in weights))
    maximum = max(logs.values())
    total = math.fsum(math.exp(w - maximum) for w in logs.values())
    rows = {label: {'fraction': math.exp(w - maximum) / total,
                    'effective_barrier_relative_kcal': rt * (maximum - w)} for label, w in logs.items()}
    labels = list(products)
    pairwise = []
    for i, a in enumerate(labels):
        for b in labels[i + 1:]:
            log_ratio = logs[a] - logs[b]
            pairwise.append({'a': a, 'b': b, 'ddG_barrier_kcal': rt * log_ratio,
                             'ratio_a_over_b': _represented_exp(log_ratio), 'ln_ratio_a_over_b': log_ratio})
    result = {'products': rows, 'pairwise': pairwise,
              'dominant_products': [label for label in labels if math.isclose(logs[label], maximum, rel_tol=0, abs_tol=1e-12)]}
    if len(labels) == 2:
        result['ee_percent'] = 100 * math.tanh((logs[labels[0]] - logs[labels[1]]) / 2)
        result['ee_sign_convention'] = f'100 × (P({labels[0]}) − P({labels[1]}))；第一个标签占优为正，仅对映产物解释为 ee。'
    return result


def selectivity_results(entries, species, temperature):
    rows = []
    for entry in entries:
        products, label = entry['products'], entry['id']
        names = list(dict.fromkeys(c['species'] for channels in products.values() for c in channels))
        baseline = species[names[0]]
        channels = {}
        for product, definitions in products.items():
            channels[product] = []
            for channel in definitions:
                name = channel['species']
                item = species[name]
                require(item['n_imag'] == 1, f'{label}/{name}: selectivity requires TS species (n_imag=1)')
                require(item['elements'] == baseline['elements'], f'{label}: selectivity elemental composition differs')
                require(item['charge'] == baseline['charge'], f'{label}: selectivity charge differs')
                channels[product].append({**channel, 'paths': channel.get('paths', 1),
                    'paths_source': '显式指定' if 'paths' in channel else '默认 1',
                    'conformer_degeneracies': [{'attempt_id': c['attempt_id'], 'degeneracy': c['degeneracy']}
                                             for c in item['conformers']]})

        def evaluate(key):
            energies = {name: species[name][key] for name in names}
            result = selectivity_distribution(products, energies, temperature)
            if 'perturb_kcal' not in entry:
                return result
            variants = []
            for name in names:
                for sign in (-1, 1):
                    shift = sign * entry['perturb_kcal']
                    altered = {**energies, name: energies[name] + shift}
                    variant = selectivity_distribution(products, altered, temperature)
                    variants.append({'perturbed_species': name, 'shift_kcal': shift,
                                     'fractions': {p: v['fraction'] for p, v in variant['products'].items()},
                                     'dominant_products': variant['dominant_products'],
                                     'dominant_changed': variant['dominant_products'] != result['dominant_products'],
                                     'dominant_product_flipped': not set(variant['dominant_products']) & set(result['dominant_products'])})
            ranges = {}
            for product, values in result['products'].items():
                fractions = [values['fraction']] + [v['fractions'][product] for v in variants]
                ranges[product] = {'min': min(fractions), 'max': max(fractions)}
            result['sensitivity'] = {'perturb_kcal': entry['perturb_kcal'], 'fraction_ranges': ranges,
                                    'variants': variants,
                                    'dominant_changed': any(v['dominant_changed'] for v in variants),
                                    'dominant_product_flipped': any(v['dominant_product_flipped'] for v in variants),
                                    'scope': '一次只扰动一个 TS 物种（其所有出现位置一起变化）；区间包含基线，不是联合误差界。'
                                             '翻转指新旧占优产物集合无交集；新增或消失并列另报 dominant_changed。'}
            return result

        rows.append({'id': label, 'product_order': list(products), 'channels': channels,
                     **evaluate('corrected_G_kcal'),
                     'lowest_conformer': evaluate('corrected_lowest_conformer_G_kcal')})

        branches = {}
        for product, definitions in products.items():
            candidates = []
            for channel in definitions:
                name = channel['species']
                item = species[name]
                # Reuse the species corrections; do not recalculate their formulas.
                for conformer in sorted(item['conformers'], key=lambda c: c['attempt_id']):
                    candidates.append({'species': name, 'attempt_id': conformer['attempt_id'],
                        'corrected_G_kcal': (conformer['qh_G_hartree'] * HARTREE_TO_KCAL
                                            + item['standard_state_correction_kcal']
                                            + item['concentration_correction_kcal']),
                        'paths': channel.get('paths', 1),
                        'conformer_degeneracy': conformer['degeneracy']})
            minimum = min(c['corrected_G_kcal'] for c in candidates)
            # Candidates are ordered by channel definition, then Attempt ID.
            tied = [c for c in candidates if math.isclose(
                c['corrected_G_kcal'], minimum, rel_tol=0, abs_tol=1e-9)]
            branches[product] = {**tied[0], 'ties': [
                {'species': c['species'], 'attempt_id': c['attempt_id']}
                for c in tied] if len(tied) > 1 else []}
        # One channel/structure per product; only paths enters its weight.
        single = selectivity_distribution(
            {p: [{'species': b['species'], 'paths': b['paths']}] for p, b in branches.items()},
            {b['species']: b['corrected_G_kcal'] for b in branches.values()}, temperature)
        lowest_ts = {'definition': '每个产物分支取修正后自由能最低的单个 TS 结构；'
                                  '保留其通道 paths；不对构象求和；不乘构象简并度。',
                     'branches': branches, 'pairwise': []}
        for pair, ensemble in zip(single['pairwise'], rows[-1]['pairwise']):
            lowest_ts['pairwise'].append({
                'a': pair['a'], 'b': pair['b'],
                'lowest_ts_ddG_kcal': pair['ddG_barrier_kcal'],
                'ensemble_ddG_kcal': ensemble['ddG_barrier_kcal'],
                'difference_kcal': ensemble['ddG_barrier_kcal'] - pair['ddG_barrier_kcal'],
                'ratio_a_over_b': pair['ratio_a_over_b']})
        if 'ee_percent' in single:
            lowest_ts.update(ee_percent=single['ee_percent'],
                             ee_sign_convention=single['ee_sign_convention'])
        rows[-1]['lowest_ts'] = lowest_ts
    return rows


def symmetry_report(species, temperature):
    warnings = []
    routes = {c['nosymm'] for item in species.values() for c in item['conformers']}
    if len(routes) > 1:
        warnings.append('剖面中混用 nosymm 与未使用 nosymm 的结构；请核对对称处理一致性。')
    for name, item in species.items():
        sigmas = {c['rotational_symmetry_number'] for c in item['conformers']}
        if len(sigmas) > 1:
            warnings.append(f'{name}: 同一物种不同构象的 σ 不同。')
        if max(sigmas) > 1:
            warnings.append(f'{name}: 存在 σ > 1；请核对真实几何与对称处理。')
        for conformer in item['conformers']:
            conformer['RT_ln_sigma_kcal'] = R_KCAL * temperature * math.log(conformer['rotational_symmetry_number'])
    return {'warnings': warnings,
            'note': '每个构象列出 RT ln σ，表示固定其他项时相对 σ=1 的 G 贡献估算，'
                    '不自动修正能量；混合系综不能直接用此值修正能垒。'
                    'σ 与构象简并度及路径数分别审阅；GoodVibes 默认值不等于物理对称数已确认。'}


def sensitivity(states, perturb, cycle):
    def determining(rows):
        if cycle:
            span = energetic_span(rows)
            return {'pairs': [[p['TDTS'], p['TDI']] for p in span['determining_pairs']],
                    'delta_E_kcal': span['delta_E_kcal']}
        steps = step_table(rows)
        highest = max(s['forward_barrier_kcal'] for s in steps)
        return {'highest_local_barrier_TS': [s['ts'] for s in steps if math.isclose(
            s['forward_barrier_kcal'], highest, rel_tol=0, abs_tol=1e-8)],
                'barrier_kcal': highest}
    baseline = determining(states)
    key = 'pairs' if cycle else 'highest_local_barrier_TS'
    variants = []
    for index, state in enumerate(states):
        if state['kind'] != 'ts':
            continue
        for sign in (-1, 1):
            shifted = [dict(s) for s in states]
            shifted[index]['relative_G_kcal'] += sign * perturb
            result = determining(shifted)
            variants.append({'perturbed_TS': state['id'], 'shift_kcal': sign * perturb,
                             **result, 'changed': result[key] != baseline[key]})
    return {'perturb_kcal': perturb, 'baseline': baseline, 'variants': variants,
            'any_changed': any(v['changed'] for v in variants),
            'scope': 'One TS state at a time, +/- x kcal/mol; not simultaneous independent errors. '
                     'For non-cycles only the highest local forward barrier is compared, not a kinetic RDS.'}


def calculate_profile(definition, *, perturb=None):
    path = Path(definition).expanduser().resolve()
    require(path.parent.name == 'analyses', 'Profile definition must be in study/analyses/')
    study, analyses = path.parent.parent, path.parent
    data = read_json(path)
    require(set(data) <= {'species', 'states', 'reference', 'temperature_K', 'standard_state',
                         'explicit_solvent_concentrations_M', 'thermo_settings', 'catalytic_cycle', 'selectivity'},
            'Unknown profile field')
    specs, states = data.get('species'), data.get('states')
    require(isinstance(specs, dict) and bool(specs), 'Missing species definitions')
    require(isinstance(states, list) and len(states) >= 3 and len(states) % 2 == 1,
            'Provide ordered minimum/ts/minimum states for each step')
    used, state_ids = set(), []
    for index, state in enumerate(states):
        require(isinstance(state, dict) and set(state) == {'id', 'kind', 'species'},
                'Each state needs id, kind and species')
        sid = nonempty(state['id'], 'state id')
        require(sid not in state_ids, f'Duplicate state: {sid}')
        state_ids.append(sid)
        require(state['kind'] == ('ts' if index % 2 else 'minimum'),
                'States must alternate minimum/ts/minimum in reaction order')
        components = state['species']
        require(isinstance(components, dict) and bool(components), f'{sid}: missing species')
        for name, coefficient in components.items():
            require(name in specs, f'{sid}: missing species {name}')
            integer(coefficient, f'{sid}/{name}: stoichiometry', positive=True)
            used.add(name)
    selections, selection_species = selectivity_definitions(data, specs)
    used.update(selection_species)
    require(used == set(specs), 'Unused species definitions: remove them or include them in states/selectivity')
    reference = data.get('reference')
    require(reference in state_ids, 'Reference state is missing')
    cycle = data.get('catalytic_cycle', False)
    require(type(cycle) is bool, 'catalytic_cycle must be boolean')
    if perturb is not None:
        finite(perturb, 'perturb', positive=False)
        require(perturb >= 0, 'perturb must be non-negative')
    direct_settings = dict(DEFAULT_SETTINGS)
    overrides = data.get('thermo_settings', {})
    require(isinstance(overrides, dict) and set(overrides) <= set(DEFAULT_SETTINGS), 'Unknown thermo_settings')
    direct_settings.update(overrides)
    if 'temperature_K' in data:
        if 'temperature_K' in overrides:
            require(data['temperature_K'] == overrides['temperature_K'], 'Conflicting temperature settings')
        direct_settings['temperature_K'] = finite(data['temperature_K'], 'temperature_K', positive=True)
    # Infer optional temperature/settings from a supplied thermo table, so an
    # omitted temperature does not silently mix 298.15 K with another value.
    tables = [spec for spec in specs.values() if isinstance(spec, dict) and 'thermo' in spec]
    if tables and not overrides:
        from ag._profile_sources import local_path, settings_checked
        first = read_json(local_path(study, analyses, tables[0]['thermo']))
        direct_settings = dict(settings_checked(first.get('settings')))
    from ag.cp_report import reject_cp
    from ag._profile_sources import local_path
    for spec in specs.values():
        if not isinstance(spec, dict):
            continue  # Existing source validation reports malformed definitions.
        rows = (read_json(local_path(study, analyses, spec['thermo'])).get('rows', [])
                if 'thermo' in spec else spec.get('attempts', []))
        for row in rows if isinstance(rows, list) else []:
            for key in ('attempt_id', 'spc_attempt_id'):
                if isinstance(row, dict) and row.get(key):
                    reject_cp(local_path(study, study / 'attempts', row[key]))
    species = {name: load_species(name, spec, study, analyses, direct_settings)
               for name, spec in specs.items()}
    baseline = next(iter(species.values()))
    for name, item in species.items():
        require(item['program_version'] == baseline['program_version'], f'{name}: inconsistent program versions within profile')
        require(item['settings'] == baseline['settings'], f'{name}: inconsistent temperature/standard state/low-frequency settings')
        require(item['protocol'] == baseline['protocol'], f'{name}: inconsistent method/basis/dispersion/solvent protocol')
    settings = baseline['settings']
    for key, value in overrides.items():
        require(settings[key] == value, f'Requested thermo_settings {key} differs from source')
    temperature = settings['temperature_K']
    if 'temperature_K' in data:
        require(temperature == data['temperature_K'], 'Requested temperature differs from source thermochemistry; recompute it')
    standard_state = data.get('standard_state', '1M')
    require(standard_state in ('1M', '1atm'), 'standard_state must be 1M or 1atm')
    target_c = 1.0 if standard_state == '1M' else 1.0 / (R_L_ATM * temperature)
    concentrations = data.get('explicit_solvent_concentrations_M', {})
    require(isinstance(concentrations, dict) and set(concentrations) <= set(species),
            'Explicit solvent concentration refers to missing species')
    rt = R_KCAL * temperature
    for name, item in species.items():
        standard_correction = rt * math.log(target_c / settings['concentration_mol_L'])
        solvent_correction = 0.0
        if name in concentrations:
            require(item['n_imag'] == 0, 'Explicit solvent must be a minimum species')
            concentration = finite(concentrations[name], f'{name}: concentration', positive=True)
            solvent_correction = rt * math.log(concentration / target_c)
        item['standard_state_correction_kcal'] = standard_correction
        item['concentration_correction_kcal'] = solvent_correction
        item['corrected_G_kcal'] = (item['ensemble_G_hartree'] * HARTREE_TO_KCAL
                                    + standard_correction + solvent_correction)
        item['corrected_S_hartree_per_K'] = (item['ensemble_H_hartree']
                                            - item['corrected_G_kcal'] / HARTREE_TO_KCAL) / temperature
        item['corrected_lowest_conformer_G_kcal'] = (item['lowest_conformer_G_hartree'] * HARTREE_TO_KCAL
                                                    + standard_correction + solvent_correction)
    rows = []
    for state in states:
        elements, charge, ts_count = Counter(), 0, 0
        for name, coefficient in state['species'].items():
            item = species[name]
            elements.update({e: n * coefficient for e, n in item['elements'].items()})
            charge += item['charge'] * coefficient
            ts_count += item['n_imag'] * coefficient
        require(ts_count == (1 if state['kind'] == 'ts' else 0),
                f"{state['id']}: minimum requires only n_imag=0; ts requires exactly one TS species")
        rows.append({**state, 'elements': dict(elements), 'charge': charge,
                     'molecule_count': sum(state['species'].values()),
                     'G_kcal': math.fsum(species[s]['corrected_G_kcal'] * n for s, n in state['species'].items())})
    ref = rows[state_ids.index(reference)]
    for row in rows:
        require(row['elements'] == ref['elements'], f"{row['id']}: elemental composition is not conserved")
        require(row['charge'] == ref['charge'], f"{row['id']}: total charge is not conserved")
        # Subtract species contributions before summing: spectator species
        # cancel exactly and large absolute molecular energies lose fewer bits.
        row['relative_G_kcal'] = math.fsum((row['species'].get(s, 0) - ref['species'].get(s, 0))
                                         * species[s]['corrected_G_kcal'] for s in species)
    result = {'schema': 'ag-profile/1', 'units': 'kcal/mol', 'reference': reference,
              'temperature_K': temperature, 'standard_state': standard_state,
              'explicit_solvent_concentrations_M': concentrations,
              'species': species, 'states': rows, 'steps': step_table(rows), 'formulas': FORMULAS,
              'catalytic_cycle': cycle,
              'note': 'Finite supplied conformer ensembles; equilibration, mechanism and cycle closure are reviewed scientific assumptions.'}
    result['warnings'] = grid_warnings([
        (f"{name}/{conformer['attempt_id']}/{layer}", grid)
        for name, item in species.items() for conformer in item['conformers']
        for layer, grid in conformer['integration_grid'].items() if grid is not None])
    if cycle:
        result['energetic_span'] = energetic_span(rows)
    if perturb is not None:
        result['sensitivity'] = sensitivity(rows, perturb, cycle)
    step_decomposition(result['steps'], rows, species, temperature, standard_state)
    result['decomposition_note'] = DECOMPOSITION_NOTE
    result['kinetics_note'] = KINETICS_NOTE
    result['selectivity'] = selectivity_results(selections, species, temperature)
    result['selectivity_note'] = SELECTIVITY_NOTE
    result['symmetry'] = symmetry_report(species, temperature)
    # Check derived numbers as well (e.g. overflow from malformed large input).
    try:
        json.dumps(result, allow_nan=False)
    except ValueError as exc:
        raise ValueError('Profile contains non-finite derived energy') from exc
    return result


def markdown(result):
    def cell(value):
        return str(value).replace('|', '\\|').replace('\n', ' ')
    lines = ['# Reaction free-energy profile', '',
             f"Reference: {cell(result['reference'])}; {result['temperature_K']} K; {result['standard_state']}; kcal/mol.", '',
             '| State | Kind | Composition | ΔG |', '|---|---|---|---:|']
    for row in result['states']:
        composition = ' + '.join(f'{n} {s}' for s, n in row['species'].items())
        lines.append(f"| {cell(row['id'])} | {row['kind']} | {cell(composition)} | {row['relative_G_kcal']:.6f} |")
    lines += ['', '| Step | Forward barrier | Reverse barrier | Reaction ΔG |', '|---|---:|---:|---:|']
    for step in result['steps']:
        label = f"{step['reactant']} → {step['ts']} → {step['product']}"
        lines.append(f"| {cell(label)} | {step['forward_barrier_kcal']:.6f} | {step['reverse_barrier_kcal']:.6f} | {step['reaction_G_kcal']:.6f} |")
    lines += ['', '| Species | Ensemble G (Hartree) | Standard-state correction | Concentration correction | Single-conformer reason |',
              '|---|---:|---:|---:|---|']
    for name, item in result['species'].items():
        lines.append(f"| {cell(name)} | {item['ensemble_G_hartree']:.10f} | {item['standard_state_correction_kcal']:.6f} | {item['concentration_correction_kcal']:.6f} | {cell(item['single_conformer_reason'] or '—')} |")
    lines += ['', '## 输入一致性证据', '',
              '| Species | Attempt | Layer | Protocol | Integration grid |', '|---|---|---|---|---|']
    for name, item in result['species'].items():
        for conformer in item['conformers']:
            for layer, grid in conformer['integration_grid'].items():
                if grid is not None:
                    lines.append(f"| {cell(name)} | {cell(conformer['attempt_id'])} | {layer} | "
                                 f"{cell(json.dumps(item['protocol'][layer]))} | {cell(grid)} |")
    lines += ['', *[f'- 警告：{cell(warning)}' for warning in result.get('warnings', [])], '',
              '| Frequency Attempt | SP Attempt | RMSD (Å) | SP input geometry SHA-256 | Frequency final geometry SHA-256 |',
              '|---|---|---:|---|---|']
    for item in result['species'].values():
        for conformer in item['conformers']:
            evidence = conformer['pairing_evidence']
            if evidence is not None:
                lines.append(f"| {cell(conformer['attempt_id'])} | {cell(conformer['spc_attempt_id'])} | "
                             f"{evidence['rmsd_angstrom']:.10g} | {evidence['sp_input_geometry_sha256']} | "
                             f"{evidence['frequency_final_geometry_sha256']} |")
    lines += ['', '## Formulas', '']
    lines += [f'- {name}: `{formula}`' for name, formula in result['formulas'].items()]
    for step in result['steps']:
        lines += ['', cell(f"{step['reactant']} → {step['product']}: ") + '; '.join(
            f'{key} = {cell(value)}' for key, value in step['formulas'].items())]
    if 'energetic_span' in result:
        span = result['energetic_span']
        lines += ['', '## Energetic span', '', f"δE = {span['delta_E_kcal']:.6f} kcal/mol; ΔG_cycle = {span['reaction_G_kcal']:.6f} kcal/mol.",
                  '', 'TDTS/TDI pairs: ' + '; '.join(f"{cell(p['TDTS'])} / {cell(p['TDI'])}" for p in span['determining_pairs']),
                  '', f'[Kozuch–Shaik, eq 9](https://doi.org/{SPAN_DOI}). ' + span['note']]
    if 'sensitivity' in result:
        sensitivity_result = result['sensitivity']
        lines += ['', '## TS perturbations', '', sensitivity_result['scope'], '',
                  '| TS | Shift | Determining states / highest local barrier | Changed |', '|---|---:|---|---|']
        for variant in sensitivity_result['variants']:
            controlling = variant.get('pairs', variant.get('highest_local_barrier_TS'))
            lines.append(f"| {cell(variant['perturbed_TS'])} | {variant['shift_kcal']:+.6f} | {cell(json.dumps(controlling, ensure_ascii=False))} | {variant['changed']} |")
    lines += ['', result['note'], '', '## 焓熵分项', '', result['decomposition_note'], '',
              '| Step | ΔH‡ forward | −TΔS‡ forward | ΔH‡ reverse | −TΔS‡ reverse | ΔH | −TΔS | Molecules R/TS/P | Δn TS−R |',
              '|---|---:|---:|---:|---:|---:|---:|---|---:|']
    for step in result['steps']:
        label = cell(f"{step['reactant']} → {step['ts']} → {step['product']}")
        terms = ' | '.join(f'{step[key]:.6f}' for key in (
            'forward_dH_kcal', 'forward_minus_TdS_kcal', 'reverse_dH_kcal',
            'reverse_minus_TdS_kcal', 'reaction_dH_kcal', 'reaction_minus_TdS_kcal'))
        counts = '/'.join(str(step['molecule_counts'][key]) for key in ('reactant', 'ts', 'product'))
        lines.append(f"| {label} | {terms} | {counts} | {step['molecularity_change']} |")
    lines += ['', '## 动力学换算', '', result['kinetics_note'], '',
              '| Step | Direction | k (s⁻¹) | Half-life (s) | Notes |', '|---|---|---:|---:|---|']
    def number(value):
        return f'{value:.6g}' if value is not None else 'null (see JSON logarithm)'
    for step in result['steps']:
        for direction in ('forward', 'reverse'):
            kinetics = step[f'{direction}_kinetics']
            label = cell(f"{step['reactant']} ⇌ {step['product']}")
            lines.append(f"| {label} | {direction} | {number(kinetics['k_s-1'])} | {number(kinetics['half_life_s'])} | {cell('; '.join(kinetics['notes']))} |")
    lines += ['', '## 产物选择性', '', result['selectivity_note'], '']
    if not result['selectivity']:
        lines += ['未指定 selectivity。']
    for selection in result['selectivity']:
        lines += ['', f"### {cell(selection['id'])}", '',
                  '| Product | TS species | paths | Source | Conformer degeneracies (already in ensemble G) |',
                  '|---|---|---:|---|---|']
        for product, channels in selection['channels'].items():
            for channel in channels:
                degeneracies = ', '.join(f"{c['attempt_id']}: {c['degeneracy']}" for c in channel['conformer_degeneracies'])
                lines.append(f"| {cell(product)} | {cell(channel['species'])} | {channel['paths']} | {channel['paths_source']} | {cell(degeneracies)} |")
        for basis, values in (('系综', selection), ('最低构象（敏感性参考）', selection['lowest_conformer'])):
            lines += ['', f'#### {basis}', '', '| Product | Proportion (%) | Relative effective barrier (kcal/mol) |',
                      '|---|---:|---:|']
            for product, row in values['products'].items():
                lines.append(f"| {cell(product)} | {100 * row['fraction']:.6f} | {row['effective_barrier_relative_kcal']:.6f} |")
            lines += ['', '占优产物：' + ', '.join(cell(p) for p in values['dominant_products'])]
            if 'ee_percent' in values:
                lines += ['', f"ee = {values['ee_percent']:+.6f}%；{cell(values['ee_sign_convention'])}"]
            lines += ['', '| a / b | ΔΔG‡ = G_eff(b)−G_eff(a) (kcal/mol) | Ratio a/b (dr) |', '|---|---:|---:|']
            for pair in values['pairwise']:
                lines.append(f"| {cell(pair['a'])} / {cell(pair['b'])} | {pair['ddG_barrier_kcal']:.6f} | {number(pair['ratio_a_over_b'])} |")
            if 'sensitivity' in values:
                report = values['sensitivity']
                lines += ['', f"逐 TS 物种 ±{report['perturb_kcal']} kcal/mol；占优产物翻转：{report['dominant_product_flipped']}；占优集合改变：{report['dominant_changed']}。",
                          report['scope'], '', '| Product | Minimum proportion (%) | Maximum proportion (%) |', '|---|---:|---:|']
                for product, bounds in report['fraction_ranges'].items():
                    lines.append(f"| {cell(product)} | {100 * bounds['min']:.6f} | {100 * bounds['max']:.6f} |")
        if 'lowest_ts' in selection:
            lowest_ts = selection['lowest_ts']
            lines += ['', '#### 最低 TS / 系综 / 差值', '', lowest_ts['definition'], '',
                      '| a / b | 最低 TS ΔΔG‡ (kcal/mol) | 系综 ΔΔG‡ (kcal/mol) | 差值（系综−最低 TS）(kcal/mol) | a 最低 TS species / Attempt | b 最低 TS species / Attempt |',
                      '|---|---:|---:|---:|---|---|']
            for pair in lowest_ts['pairwise']:
                a, b = (lowest_ts['branches'][pair[key]] for key in ('a', 'b'))
                lines.append(f"| {cell(pair['a'])} / {cell(pair['b'])} | {pair['lowest_ts_ddG_kcal']:.6f} | "
                             f"{pair['ensemble_ddG_kcal']:.6f} | {pair['difference_kcal']:.6f} | "
                             f"{cell(a['species'])} / {cell(a['attempt_id'])} | {cell(b['species'])} / {cell(b['attempt_id'])} |")
            lines += ['', '单结构结果和系综结果不是同一个物理量；“差值大”说明结论对构象采样敏感，不代表哪个更正确。']
    lines += ['', '## 对称数', '', result['symmetry']['note'], '']
    lines += [f'- 警告：{cell(warning)}' for warning in result['symmetry']['warnings']]
    if not result['symmetry']['warnings']:
        lines += ['未触发 σ/nosymm 混用警告。']
    lines += ['', '| Species | Attempt | σ | Source | nosymm | RT ln σ (kcal/mol) |',
              '|---|---|---:|---|---|---:|']
    for name, item in result['species'].items():
        for conformer in item['conformers']:
            source = conformer['rotational_symmetry_source']
            evidence = source['kind']
            if source.get('file'):
                evidence += f" ({source['file']}:{source.get('line')})"
            lines.append(f"| {cell(name)} | {cell(conformer['attempt_id'])} | {conformer['rotational_symmetry_number']} | {cell(evidence)} | {conformer['nosymm']} | {conformer['RT_ln_sigma_kcal']:.6f} |")
    for name, item in result['species'].items():
        for conformer in item['conformers']:
            note = conformer.get('frequency_evidence', {}).get('note')
            if note:
                lines += ['', f"{cell(name)}/{cell(conformer['attempt_id'])}: {cell(note)}", '']
    return '\n'.join(lines + [''])


def write_profile(result, definition, name=None):
    definition = Path(definition).resolve()
    require(definition.parent.name == 'analyses', 'Output must be in study/analyses/')
    name = name or definition.stem + '-profile'
    require(isinstance(name, str) and re.fullmatch(r'[\w-]+', name), 'Output name must be a plain filename stem')
    paths = [definition.parent / (name + ext) for ext in ('.json', '.md')]
    payloads = [json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + '\n', markdown(result)]
    for path in paths:
        if path.exists() or path.is_symlink():
            raise FileExistsError(f'Output already exists: {path.name}')
    created = []
    try:
        for path, payload in zip(paths, payloads):
            with path.open('x') as stream:
                created.append(path)
                stream.write(payload)
    except BaseException:
        # Only our newly created local files; never an existing analysis.
        for path in created:
            path.unlink()
        raise
    return tuple(paths)


def _run(args):
    try:
        result = calculate_profile(args.definition, perturb=args.perturb)
        paths = write_profile(result, args.definition, args.name)
        print(json.dumps(result, indent=2, ensure_ascii=False) if args.json else paths[1].read_text())
        return 0
    except (ImportError, ValueError, OSError, KeyError, TypeError) as exc:
        # Malformed local sources must not produce a partial profile.
        if args.json:
            print(json.dumps({'error': str(exc), 'exit_code': 1}, ensure_ascii=False))
        else:
            import sys
            print(str(exc), file=sys.stderr)
        return 1


def register(subparsers):
    parser = subparsers.add_parser('profile', help='Check and assemble a local reaction free-energy profile')
    parser.add_argument('definition', help='Profile JSON in study/analyses/')
    parser.add_argument('--perturb', type=float, metavar='KCAL', help='Perturb each TS state separately by +/- KCAL')
    parser.add_argument('--name', help='New output filename stem in analyses/ (never overwrite)')
    parser.add_argument('--json', action='store_true')
    parser.set_defaults(func=_run)
