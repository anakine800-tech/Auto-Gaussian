"""Local review skeletons and read-only completeness/freshness checks."""
from hashlib import sha256
from contextlib import ExitStack
import json
import os
import re

from ag import attempt, cards, study
from ag.facts import (_publication_recheck, _local_review_write, _attempt_publication_sources,
                      _publication_stage, _publication_unchanged)


def cell(value):
    return str(value).replace('|', '&#124;').replace('\n', ' ')


def expected(manifest, facts=None):
    card = manifest.get('card')
    if not card:
        raise ValueError('Manifest has no card; use review init --card to specify review criteria')
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
            target = int(next(iter(counts))) if len(counts) == 1 else None
            if facts and facts.get('monatomic') is True:
                target = 0
            fields.append(('n_imag', target))
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
    if key == 'freq_step_converged':
        for field in ('freq_step_gaussian_stationary', 'freq_step_review',
                      'freq_step_threshold_set', 'freq_step_converged_tight'):
            if field in facts:
                evidence += f'；facts.json: {field}=' + json.dumps(facts[field], ensure_ascii=False)
        if facts.get('freq_step_review') == 'manual_review':
            evidence += '；四项未全部通过，但 Gaussian 判定驻点：需人工判定；thermo 不自动接受'
        if (facts.get('freq_step_threshold_set') == 'default'
                and value is True and facts.get('freq_step_converged_tight') is False):
            evidence += '；Freq 步按默认阈值通过、按 Tight 阈值未通过；若父优化为 Opt=Tight，需人工判定是否接受'
    if key == 'multiplicity':
        for field in ('s2', 's2_after_annihilation', 's2_line', 'wavefunction_stability',
                      'wavefunction_stability_line', 'wavefunction_stability_line_number',
                      'wavefunction_stability_lowest_eigenvalue'):
            if field in facts:
                evidence += f'；facts.json: {field}=' + json.dumps(facts[field], ensure_ascii=False)
    valid = value is not None and target is not None and type(value) is type(target)
    if key == 'termination':
        valid = value in ('normal', 'error', 'incomplete')
    if key == 'n_imag':
        valid = valid and value >= 0
        if facts.get('monatomic') is True:
            evidence += '；期望值依据：monatomic=true，单原子无振动模式'
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
    if key == 'freq_step_converged' and value is False and facts.get('freq_step_review') == 'manual_review':
        conclusion = '无法判断'
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
    fingerprint = dict(sha256=sha256(data).hexdigest(), mtime_ns=stamp)
    if isinstance(facts.get('ag_provenance'), dict):
        fingerprint['ag_provenance'] = facts['ag_provenance']
    return facts, fingerprint


def init(path, card=None, *, run_id=None, token=None, plan_sha256=None):
    with _local_review_write(path.parent.parent, run_id=run_id, token=token,
                             plan_sha256=plan_sha256) as publication, ExitStack() as sources:
        verify = _attempt_publication_sources(path, sources)
        return _init(path, card, publication, verify, pending=run_id is not None)


def _init(path, card, publication, verify, *, pending):
    destination = study.local_path(path.parent.parent, path / 'review.md')
    if destination.exists():
        raise FileExistsError('review.md already exists; will not overwrite')
    manifest = attempt.read_manifest(path)
    provenance = ''
    source = '判据来自 manifest 中保存的卡片第 6 节。'
    if card is not None:
        if manifest.get('card'):
            raise ValueError('--card cannot replace a card recorded during preparation')
        snapshot = cards.snapshot(card)
        manifest = {**manifest, 'card': snapshot}
        source = '卡片为审阅时补指定，非准备时记录。判据来自补指定卡片的第 6 节。'
        # Save the recipe here so a later Skills update cannot change check's criteria.
        encoded = json.dumps(snapshot, ensure_ascii=False).replace('<', r'\u003c').replace('>', r'\u003e')
        provenance = (f'Skills commit: {snapshot["git_commit"]}\n\n'
                      f'<!-- review-card: {encoded} -->\n\n')
    facts, fingerprint = facts_snapshot(path)
    fields, items = expected(manifest, facts)
    rows = [fact_row(key, target, facts) for key, target in fields]
    rows += [(item, '', '') for item in items]
    text = (f"# Review: {path.name}\n\n{cards.label(manifest)}\n\n"
            + provenance + '<!-- facts: ' + json.dumps(fingerprint) + ' -->\n\n'
            + source + 'facts 核对仅证明对应字段，'
            '不能替代整条科学判据；其余行由 LLM 填写，结论限通过 / 不通过 / 无法判断。'
            '依据需指向 facts 字段、日志行号或文件；无法判断也须说明缺失的证据。\n\n'
            '| 判据 | 依据（facts 字段、日志行号或文件） | 结论 |\n'
            '|---|---|---|\n')
    text += ''.join('| ' + ' | '.join(cell(v) for v in row) + ' |\n' for row in rows)
    if pending:
        text += '\n自主临时审阅：待人确认；不构成科学结论或里程碑签字。\n'
    staged = []
    with ExitStack() as sources:
        temporary, proof = _publication_stage(path, text.encode('utf-8'), sources, staged,
                                              prefix='.review-stage-')
        with publication() as recheck:
            verify()
            _publication_unchanged(proof)
            study.local_path(path.parent.parent, destination)
            _publication_recheck(recheck)
            os.link(temporary, destination, follow_symlinks=False)
    temporary.unlink()
    return dict(attempt_id=path.name, review='review.md', rows=len(rows))


def check(path):
    destination = study.local_path(path.parent.parent, path / 'review.md')
    text = destination.read_text(encoding='utf-8')
    manifest = attempt.read_manifest(path)
    if not manifest.get('card'):
        recorded_cards = re.findall(r'^<!-- review-card: (.+) -->$', text, re.M)
        try:
            if len(recorded_cards) != 1:
                raise ValueError('Missing or ambiguous review card snapshot')
            snapshot = json.loads(recorded_cards[0])
            if (not re.fullmatch(r'[a-z0-9][a-z0-9-]*', snapshot['name'])
                    or not re.fullmatch(r'[0-9a-f]{40}', snapshot['git_commit'])
                    or type(snapshot['dirty']) is not bool or not isinstance(snapshot['content'], str)):
                raise ValueError('Invalid review card snapshot')
        except (ValueError, KeyError, TypeError) as exc:
            raise ValueError(f'Attempt {path.name}: invalid or missing review-time card snapshot') from exc
        manifest = {**manifest, 'card': snapshot}
    facts, current = facts_snapshot(path)
    fields, items = expected(manifest, facts)
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
    if isinstance(original, dict) and original.get('sha256') != (current or {}).get('sha256'):
        # Use the provenance bound to the reviewed bytes, never today's HEAD or
        # the Skills commit (which identifies criteria, not the facts parser).
        provenance = original.get('ag_provenance') or {}
        commit = provenance.get('git_commit') if isinstance(provenance, dict) else None
        dirty = provenance.get('dirty') if isinstance(provenance, dict) else None
        if not isinstance(commit, str) or not re.fullmatch(r'[0-9a-f]{40}', commit):
            commit = None
        result['bound_ag_commit'] = commit
        result['bound_ag_dirty'] = dirty
        message = '证据文件已变化：facts.json 与签字/审阅绑定的 SHA-256 不符。'
        if commit:
            message += f'绑定版本的 ag 提交号：{commit}。'
            if dirty is not False:
                message += '生成时工作区不干净或状态未知，仅该提交不能保证复现。'
            else:
                message += '可用该提交及原始日志、相同依赖复现并核对绑定哈希。'
        else:
            message += '历史记录未保存 ag 提交号，无法确定可复现的代码版本。'
        warnings.insert(0, message)
    if stale:
        result['current_facts'] = current
    return result


def run(cfg, action, attempt_id, *, card=None, run_id=None, token=None, plan_sha256=None):
    path = attempt.find(cfg, attempt_id)
    if action == 'check':
        if any(value is not None for value in (run_id, token, plan_sha256)):
            raise ValueError('Read-only review check does not accept write ownership')
        return check(path)
    return init(path, card=card, run_id=run_id, token=token, plan_sha256=plan_sha256)
