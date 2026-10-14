"""Local review skeletons and read-only completeness/freshness checks."""
from hashlib import sha256
import json
import os
import re

from ag import attempt, cards, study


def cell(value):
    return str(value).replace('|', '&#124;').replace('\n', ' ')


def expected(manifest):
    card = manifest.get('card')
    if not card:
        raise ValueError('Manifest has no card; cannot reconstruct its review criteria')
    items = cards.criteria(card['content'])
    checklist = ' '.join(items)
    science = manifest['science']
    fields = [('termination', 'normal')]
    if manifest['template'] == 'gaussian':
        route = science['route'].lower()
        if 'opt_converged' in checklist or re.search(r'\bopt\b', route):
            fields.append(('opt_converged', True))
        if 'freq_step_converged' in checklist or 'n_imag' in checklist or re.search(r'\bfreq\b', route):
            fields.append(('freq_step_converged', True))
            # Counts alone never certify complete modes or a reaction direction.
            counts = set(re.findall(r'\bn_imag\s*=\s*(\d+)\b', checklist))
            fields.append(('n_imag', int(next(iter(counts))) if len(counts) == 1 else None))
    fields.extend((key, science.get(key)) for key in ('route', 'charge', 'multiplicity'))
    return fields, items


def fact_row(key, target, facts):
    value = facts.get(key)
    criterion = f'facts 核对：{key} = {json.dumps(target, ensure_ascii=False)}'
    evidence = f'facts.json: {key}={json.dumps(value, ensure_ascii=False)}'
    if key in ('route', 'charge', 'multiplicity'):
        evidence += f'；manifest.json: science.{key}={json.dumps(target, ensure_ascii=False)}'
    if key == 'freq_step_converged' and facts.get('freq_step_convergence'):
        evidence += '；facts.json: freq_step_convergence=' + json.dumps(facts['freq_step_convergence'], ensure_ascii=False)
    valid = value is not None and target is not None and type(value) is type(target)
    if key == 'termination':
        valid = value in ('normal', 'error', 'incomplete')
    if key == 'n_imag':
        valid = valid and value >= 0
    if key == 'multiplicity':
        valid = valid and value >= 1
    if key == 'route':
        valid = valid and bool(value.strip())
    if not valid:
        evidence += '；缺失、类型不符或无适用的预期值，需查原日志/卡片'
        conclusion = '无法判断'
    else:
        # Only normalize formatting, never infer scientific method equivalence.
        normalize = lambda v: ' '.join(v.lower().split()) if key == 'route' else v
        conclusion = '通过' if normalize(value) == normalize(target) else '不通过'
    return criterion, evidence, conclusion


def facts_snapshot(path):
    source = study.local_path(path.parent.parent, path / 'facts.json')
    if not source.exists():
        return {}, None
    with source.open('rb') as handle:
        data = handle.read()
        stamp = os.fstat(handle.fileno()).st_mtime_ns
    facts = json.loads(data)
    if not isinstance(facts, dict):
        raise ValueError('facts.json must be an object')
    return facts, dict(sha256=sha256(data).hexdigest(), mtime_ns=stamp)


def init(path):
    destination = study.local_path(path.parent.parent, path / 'review.md')
    if destination.exists():
        raise FileExistsError('review.md already exists; will not overwrite')
    manifest = attempt.read_manifest(path)
    fields, items = expected(manifest)
    facts, fingerprint = facts_snapshot(path)
    rows = [fact_row(key, target, facts) for key, target in fields]
    rows += [(item, '', '') for item in items]
    text = (f"# Review: {path.name}\n\n{cards.label(manifest)}\n\n"
            '<!-- facts: ' + json.dumps(fingerprint) + ' -->\n\n'
            '判据来自 manifest 中保存的卡片第 6 节。facts 核对仅证明对应字段，'
            '不能替代整条科学判据；其余行由 LLM 填写，结论限通过 / 不通过 / 无法判断。'
            '依据需指向 facts 字段、日志行号或文件；无法判断也须说明缺失的证据。\n\n'
            '| 判据 | 依据（facts 字段、日志行号或文件） | 结论 |\n'
            '|---|---|---|\n')
    text += ''.join('| ' + ' | '.join(cell(v) for v in row) + ' |\n' for row in rows)
    with destination.open('x', encoding='utf-8') as handle:
        handle.write(text)
    return dict(attempt_id=path.name, review='review.md', rows=len(rows))


def check(path):
    destination = study.local_path(path.parent.parent, path / 'review.md')
    text = destination.read_text(encoding='utf-8')
    manifest = attempt.read_manifest(path)
    fields, items = expected(manifest)
    required = [cell(fact_row(key, target, {})[0]) for key, target in fields] + [cell(item) for item in items]
    issues, found = [], []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.lstrip().startswith('|'):
            continue
        columns = [part.strip() for part in line.strip().strip('|').split('|')]
        if columns[0] == '判据' or all(re.fullmatch(r':?-+:?', part) for part in columns):
            continue
        if len(columns) != 3:
            issues.append(f'第 {number} 行：应为判据、依据、结论三栏（内容中的 | 请写成 &#124;）')
            continue
        criterion, evidence, conclusion = columns
        found.append(criterion)
        if not criterion:
            issues.append(f'第 {number} 行：缺少判据')
        if evidence in ('', '-', '待填写', 'TODO', '<填写>'):
            issues.append(f'第 {number} 行：缺少依据')
        if conclusion not in ('通过', '不通过', '无法判断'):
            issues.append(f'第 {number} 行：缺少有效结论（通过 / 不通过 / 无法判断）')
    # Prevent deleting an unfinished row from turning an incomplete review green.
    for criterion in required:
        if criterion not in found:
            issues.append('缺少判据行：' + criterion)
    _, current = facts_snapshot(path)
    recorded = re.search(r'^<!-- facts: (.+) -->$', text, re.M)
    try:
        original = json.loads(recorded.group(1)) if recorded else None
    except json.JSONDecodeError:
        original = None
        recorded = None
    stale = (not recorded or original != current or
             (current is not None and current['mtime_ns'] > destination.stat().st_mtime_ns))
    warnings = ['review 可能过期：facts.json 已重新生成、改变或缺少原始快照；请重新核对依据'] if stale else []
    result = dict(attempt_id=path.name, complete=not issues, stale=stale, issues=issues, warnings=warnings)
    if stale:
        result['current_facts'] = current
    return result


def run(cfg, action, attempt_id):
    path = attempt.find(cfg, attempt_id)
    return init(path) if action == 'init' else check(path)
