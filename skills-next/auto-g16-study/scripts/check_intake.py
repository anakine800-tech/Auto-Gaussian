#!/usr/bin/env python3
"""Check local intake completeness and optionally write unsigned, exclusive drafts."""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit, quote

REFERENCES = Path(__file__).resolve().parents[1] / 'references'
SPECIES_REPORT = 'analyses/intake/species-check.json'
DRAFTS = ('analyses/intake/study.md.draft', 'analyses/intake/channels.csv.draft')
PLACEHOLDER = re.compile(r'<(?!https?://)[^<>\n]+>|\b(?:TODO|TBD)\b')
PENDING = re.compile(r'待确认|待答|转述待核实|未确认|未签')
TOKEN = re.compile(r'\[[^\]\n]*\]\(<?([^\n)>]+)>?\)|`([^`\n]+)`')
HASH = re.compile(r'(?<![0-9a-fA-F])[0-9a-fA-F]{64}(?![0-9a-fA-F])')


def digest(data):
    return hashlib.sha256(data).hexdigest()


# Adapted from the maintained T80 check_species.py: reject links/escapes and
# recheck read bytes before exclusively publishing. No ag or remote imports.
def safe_path(root, relative):
    path = Path(relative)
    if not str(relative) or path.is_absolute() or '..' in path.parts or '\\' in str(relative):
        raise ValueError('paths must be relative and stay inside the study')
    current = root
    for part in path.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f'symlink refused: {relative}')
    return current


def study_root(study):
    root = Path(study).expanduser().absolute()
    if '..' in root.parts or any(p.is_symlink() for p in (root, *root.parents)):
        raise ValueError('study path must not contain symlinks or parent traversal')
    if not root.is_dir():
        raise ValueError('study directory must already exist')
    return root


def read_bytes(root, relative, inputs):
    data = safe_path(root, relative).read_bytes()
    entry = {'path': Path(relative).as_posix(), 'sha256': digest(data)}
    if inputs.setdefault(entry['path'], entry) != entry:
        raise ValueError(f'input changed during check: {relative}')
    return data


def clean(text):
    """Comments and fenced examples cannot impersonate completed record sections."""
    text = re.sub(r'<!--[\s\S]*?-->', '', text)
    return re.sub(r'(?m)^\s*(```|~~~)[^\n]*\n[\s\S]*?^\s*\1\s*$', '', text)


def sections(text):
    text = clean(text)
    matches = list(re.finditer(r'(?m)^(#{2,6})\s+([^\n]+)$', text))
    result = []
    for index, match in enumerate(matches):
        end = next((m.start() for m in matches[index + 1:] if len(m[1]) <= len(match[1])), len(text))
        result.append((match[2].strip(), text[match.end():end].strip()))
    return result


def cells(line):
    return [cell.strip().replace(r'\|', '|') for cell in re.split(r'(?<!\\)\|', line.strip().strip('|'))]


def tables(text):
    lines = text.splitlines()
    result = []
    i = 0
    while i + 1 < len(lines):
        if lines[i].lstrip().startswith('|') and all(re.fullmatch(r':?-{3,}:?', c) for c in cells(lines[i + 1])):
            start = i
            header = cells(lines[i]); i += 2
            rows = []
            while i < len(lines) and lines[i].lstrip().startswith('|'):
                rows.append(cells(lines[i])); i += 1
            result.append((header, rows, '\n'.join(lines[start:i])))
        else:
            i += 1
    return result


def has_placeholder(text):
    # Markdown link angle brackets are delimiters, not template placeholders.
    text = re.sub(r'\]\(<[^>]+>\)', '](link)', text)
    return bool(PLACEHOLDER.search(text))


def filled(text):
    return bool(text.strip()) and not has_placeholder(text)


def table_error(table):
    header, rows, _ = table
    if len(header) != len(set(header)):
        return 'mismatch', 'duplicate table columns'
    if not rows:
        return 'missing', 'table has no data rows'
    for index, row in enumerate(rows, 1):
        if len(row) != len(header):
            return 'mismatch', f'table row {index} has wrong column count'
        if not all(filled(c) for c in row):
            return 'missing', f'table row {index} has blank cells or placeholders'
    return None


def fields(text):
    return dict(re.findall(r'(?m)^- ([^：\n]+)：([^\n]*)$', text))


def file_tokens(text):
    for match in TOKEN.finditer(text):
        target = match[1] or match[2]
        parsed = urlsplit(target)
        if parsed.scheme or parsed.netloc or not parsed.path:
            continue
        path = unquote(parsed.path)
        if Path(path).suffix:
            yield path, match.start(), match.end()


def add(checks, name, status, detail, source=None):
    item = dict(id=name, status=status, detail=detail)
    if source:
        item['source'] = source
    checks.append(item)


def one_table(body, expected):
    found = [t for t in tables(body) if t[0] == expected]
    if len(found) != 1:
        return None, ('mismatch' if tables(body) else 'missing', 'expected exactly one table with columns: ' + ' | '.join(expected))
    return found[0], table_error(found[0])


def check_sections(text, checks):
    template = dict(sections((REFERENCES / 'intake-template.md').read_text(encoding='utf-8')))
    actual = sections(text)
    selected = {}
    for title, template_body in template.items():
        match = re.match(r'([1-9])\. ', title)
        if not match:
            continue
        number = int(match[1]); key = f'section.{number}'
        found = [body for heading, body in actual if heading == title]
        if len(found) != 1:
            add(checks, key, 'mismatch' if found else 'missing', 'expected one section: ' + title)
            continue
        body = found[0]; selected[number] = (title, body)
        error = None
        if not filled(body):
            error = ('missing', 'empty section or remaining template placeholders')
        elif number in {1, 2, 3, 5, 6, 7, 9}:
            _, error = one_table(body, tables(template_body)[0][0])
        for table in tables(body):
            error = error or table_error(table)
        # Numbered template sections with bullet fields must keep those fields.
        required = fields(template_body)
        for name in required:
            if not filled(fields(body).get(name, '')):
                error = error or ('missing', 'missing field: ' + name)
        if number == 4 and not any(p == 'atoms.csv' for p, _, _ in file_tokens(body)):
            error = error or ('missing', 'section 4 must explicitly reference atoms.csv')
        add(checks, key, *(error or ('present', 'required section and fields filled')))
    return selected


def collect_documents(root, intake, inputs, checks):
    documents = {}
    queue = [intake]
    if intake != 'study.md' and safe_path(root, 'study.md').exists():
        queue.append('study.md')
    while queue:
        name = queue.pop(0)
        if name in documents:
            continue
        try:
            text = read_bytes(root, name, inputs).decode('utf-8-sig')
        except FileNotFoundError:
            add(checks, 'document:' + name, 'missing', 'referenced document not found', name)
            documents[name] = ''
            continue
        documents[name] = text
        for relative, _, _ in file_tokens(clean(text)):
            # Evidence references are explicitly study-relative. External URLs
            # are never downloaded; repository teaching links are not records.
            if relative.endswith('.md') and (relative.startswith('analyses/') or relative == 'study.md'):
                safe_path(root, relative)
                if relative not in documents and relative not in queue:
                    queue.append(relative)
            elif relative.endswith('.md') and (relative.startswith(('/', '../')) or '\\' in relative):
                raise ValueError('document references must stay inside the study')
    return documents


def check_atoms(root, inputs, checks):
    try:
        data = read_bytes(root, 'atoms.csv', inputs).decode('utf-8-sig')
    except FileNotFoundError:
        add(checks, 'atoms', 'missing', 'atoms.csv not found'); return
    expected = [row[0] for row in tables(dict(sections((REFERENCES / 'intake-template.md').read_text(encoding='utf-8')))['4. 原子对应（atoms.csv）'])[0][1]]
    reader = csv.DictReader(io.StringIO(data))
    if not reader.fieldnames or len(reader.fieldnames) != len(set(reader.fieldnames)) or not set(expected).issubset(reader.fieldnames):
        add(checks, 'atoms', 'mismatch', 'atoms.csv columns do not match section 4'); return
    rows = list(reader)
    status = 'present'
    if not rows or any(None in row or not all(filled(row.get(k) or '') for k in expected) for row in rows):
        status = 'missing'
    add(checks, 'atoms', status, 'atom mapping cells checked; mapping correctness requires human review')


def hash_references(root, body, inputs, checks):
    references = {}
    for line in body.splitlines():
        tokens = list(file_tokens(line))
        for index, (relative, _, end) in enumerate(tokens):
            # Only the hashes expressly paired with file paths are evidence.
            stop = tokens[index + 1][1] if index + 1 < len(tokens) else len(line)
            hashes = HASH.findall(line[end:stop])
            if not hashes:
                continue
            if len(hashes) != 1 or (relative in references and references[relative] != hashes[0].lower()):
                add(checks, 'reference:' + relative, 'mismatch', 'ambiguous file/hash binding'); continue
            expected = hashes[0].lower(); references[relative] = expected
            try:
                actual = digest(read_bytes(root, relative, inputs))
            except FileNotFoundError:
                add(checks, 'reference:' + relative, 'missing', 'confirmed file not found'); continue
            add(checks, 'reference:' + relative, 'present' if actual == expected else 'mismatch', 'confirmed SHA-256 compared with current bytes')
    return references


def issue_names(item):
    issues = [name for name, value in item.get('checks', {}).items() if value.get('status') in {'mismatch', 'unknown'}]
    if item.get('multiplicity') is None:
        issues.append('multiplicity')
    if item.get('read_errors'):
        issues.append('read_errors')
    return issues


def accepted(text, issues):
    return ('接受' in text and not re.search(r'不接受|未接受|待接受|待答|待确认', text)
            and all(re.search(r'(?<![\w])' + re.escape(name) + r'(?![\w])', text) for name in issues)
            and bool(re.search(r'理由[：:]\s*\S', text)) and bool(re.search(r'影响[：:]\s*\S', text)))


def check_structure(root, documents, inputs, checks):
    try:
        data = read_bytes(root, SPECIES_REPORT, inputs)
    except FileNotFoundError:
        add(checks, 'structure.report', 'missing', 'species-check.json not found'); return
    try:
        report = json.loads(data)
    except (ValueError, UnicodeError):
        add(checks, 'structure.report', 'mismatch', 'invalid species-check JSON'); return
    if not isinstance(report, dict) or not isinstance(report.get('species'), list) or not report['species']:
        add(checks, 'structure.report', 'mismatch', 'species report must contain nonempty species list'); return
    add(checks, 'structure.report', 'present', 'nonempty species report found')
    entries = [(name, body) for name, text in documents.items() for title, body in sections(text)
               if title in {'结构确认', '结构确认条目（0c）'}]
    if not entries:
        add(checks, 'structure.confirmation', 'missing', '结构确认 entry not found'); return
    # Select the explicit binding, not the most recent-looking text or a hash
    # found elsewhere in the document. Conflicting duplicate entries are refused.
    candidates = [(name, body) for name, body in entries if any(p == SPECIES_REPORT for p, _, _ in file_tokens(body))]
    if len(candidates) != 1:
        add(checks, 'structure.confirmation', 'mismatch', 'need one confirmation binding the current species-check.json'); return
    source, body = candidates[0]
    metadata = fields(body)
    required = ('确认对象', '核验报告', '预览与输入', '既有证据清单', '确认人', '确认日期', '原话及出处', '确认范围与限制', '对原记录的引用')
    valid = all(filled(metadata.get(k, '')) and not PENDING.search(metadata[k]) for k in required)
    add(checks, 'structure.confirmation', 'present' if valid else 'missing', 'confirmation fields, person, date and original statement required', source)
    references = hash_references(root, body, inputs, checks)
    for field in ('核验报告', '预览与输入', '既有证据清单'):
        paths = [p for p, _, _ in file_tokens(metadata.get(field, ''))]
        add(checks, 'structure.hashes:' + field,
            'present' if paths and all(p in references for p in paths) else 'missing',
            'each referenced evidence file needs a paired SHA-256')
    add(checks, 'structure.report_binding', 'present' if SPECIES_REPORT in references else 'missing', 'report path must be paired with its SHA-256 in the confirmation entry')
    expected = ['物种 ID', '报告汇总状态与位置', '人工结论及依据', '接受的未决项、理由、影响与后续处理']
    table, error = one_table(body, expected)
    if error:
        add(checks, 'structure.species_confirmation', *error); return
    rows = {row[0]: row for row in table[1]}
    if len(rows) != len(table[1]):
        add(checks, 'structure.species_confirmation', 'mismatch', 'duplicate species confirmation rows')
    ids = set()
    for item in report['species']:
        if not isinstance(item, dict) or not isinstance(item.get('species_id'), str):
            add(checks, 'structure.report', 'mismatch', 'malformed species entry'); continue
        name, status = item['species_id'], item.get('status'); row = rows.get(name)
        comparisons = item.get('checks')
        if (not isinstance(comparisons, dict) or not comparisons
                or any(not isinstance(v, dict) or v.get('status') not in {'match', 'mismatch', 'unknown'} for v in comparisons.values())):
            add(checks, 'structure.species:' + name, 'mismatch', 'malformed species comparisons'); continue
        if name in ids:
            add(checks, 'structure.report', 'mismatch', 'duplicate species ID')
        ids.add(name)
        result, detail = 'present', 'explicit species confirmation present'
        if status not in {'all_match', 'has_mismatch', 'incomplete', 'out_of_scope'}:
            result, detail = 'mismatch', 'unrecognized report status'
        elif not row or not re.match(r'^确认(?:[；;：:，,。\s]|$)', row[2]) or PENDING.search(row[2]):
            result, detail = 'missing', 'species lacks explicit confirmation'
        elif status not in row[1]:
            result, detail = 'mismatch', 'confirmation must quote the report status'
        elif status == 'out_of_scope':
            result, detail = 'mismatch', 'out_of_scope cannot be accepted to expand tool scope'
        elif status in {'has_mismatch', 'incomplete'} and not accepted(row[3], issue_names(item) or [status]):
            result, detail = 'mismatch', 'unaccepted issues: ' + ', '.join(issue_names(item) or [status])
        add(checks, 'structure.species:' + name, result, detail)
    source_refs = report.get('inputs')
    if not isinstance(source_refs, list) or not source_refs:
        add(checks, 'structure.inputs', 'mismatch', 'species report lacks hashed input references'); return
    for ref in source_refs:
        if not isinstance(ref, dict) or not isinstance(ref.get('path'), str) or not HASH.fullmatch(str(ref.get('sha256', ''))):
            add(checks, 'structure.inputs', 'mismatch', 'malformed input reference'); continue
        relative = ref['path']
        try:
            current = digest(read_bytes(root, relative, inputs))
        except FileNotFoundError:
            add(checks, 'structure.input:' + relative, 'missing', 'report input is missing'); continue
        add(checks, 'structure.input:' + relative, 'present' if current == ref['sha256'].lower() else 'mismatch', 'source bytes compared with species report')
    reaction = report.get('reaction', {})
    if not isinstance(reaction, dict):
        add(checks, 'structure.reaction', 'mismatch', 'malformed reaction record'); return
    if reaction.get('status') != 'match' and reaction.get('reason') != 'reaction CSV not supplied':
        row = rows.get('reaction')
        add(checks, 'structure.reaction', 'present' if row and accepted(row[3], ['reaction']) else 'mismatch', 'declared reaction differences require explicit acceptance')


def check_records(documents, selected, checks):
    all_sections = [(name, title, body) for name, text in documents.items() for title, body in sections(text)]
    coverage = [(name, body) for name, title, body in all_sections if title == '检索覆盖记录']
    expected = tables(dict(sections((REFERENCES / 'literature-record.md').read_text(encoding='utf-8')))['检索覆盖记录'])[0][0]
    errors = [one_table(body, expected)[1] for _, body in coverage]
    add(checks, 'literature.coverage', 'present' if errors and all(error is None for error in errors) else 'missing', '检索覆盖记录 needs a filled, nonempty coverage table')
    final = [body for _, title, body in all_sections if title == '会话转述与定稿']
    guidance = dict(sections((REFERENCES / 'discussion-record.md').read_text(encoding='utf-8')))['会话转述与定稿']
    add(checks, 'discussion.finalization', 'present' if final and all(filled(b) and b != guidance and not PENDING.search(b) for b in final) else 'missing', '会话转述与定稿 needs an actual finalized record, not template guidance')
    if 7 in selected:
        expected = tables(dict(sections((REFERENCES / 'intake-template.md').read_text(encoding='utf-8')))[selected[7][0]])[0][0]
        table, error = one_table(selected[7][1], expected)
        if not error:
            for row in table[1]:
                add(checks, 'method:' + row[0], 'present' if row[2] in {'文献先例', '本课题既有方案', '兜底方法'} else 'mismatch', 'method basis must use an existing category')


def channel_rows(selected, checks):
    if 5 not in selected:
        return []
    expected = tables(dict(sections((REFERENCES / 'intake-template.md').read_text(encoding='utf-8')))[selected[5][0]])[0][0]
    table, error = one_table(selected[5][1], expected)
    if error:
        add(checks, 'channels', *error); return []
    result, ids = [], set()
    for row in table[1]:
        # Keep the complete explicitly supplied product branch after the arrow.
        # CIP labels alone do not determine branch identity.
        parts = row[1].split('→')
        if row[0] in ids or len(parts) != 2 or not all(p.strip() for p in parts):
            add(checks, 'channels', 'mismatch', 'unique channel IDs and one explicit spatial → product mapping required'); return []
        ids.add(row[0])
        result.append(dict(channel_id=row[0], product_branch=parts[1].strip(), ensemble_manifests='',
                           note='采样后填写 ensemble_manifests；' + '；'.join(f'{key}：{value}' for key, value in zip(table[0][1:], row[1:]))))
    add(checks, 'channels', 'present', 'channel columns and explicit product mappings checked')
    return result


def make_drafts(intake, selected, channels):
    template = (REFERENCES / 'study-md-template.md').read_text(encoding='utf-8')
    relative = Path(os.path.relpath(intake, 'analyses/intake')).as_posix()
    def reference(number):
        title, body = selected[number]
        anchor = re.sub(r'[^\w\-\s]', '', title).replace(' ', '-').lower()
        link = f'[开题包第 {number} 节](<{quote(relative, safe="/.")}#{quote(anchor)}>)'
        return link + '\n\n' + body
    replacements = {
        '目标': reference(1),
        '体系': reference(3) + '\n\n' + reference(2) + '\n\n' + reference(4),
        '计算方案': reference(7) + '\n\n' + reference(8) + '\n\n计算方案待人审阅签字；沿用原有里程碑。\n\n### 计算平台与软件许可\n\n待负责人核对平台与许可依据，参见开题包第 7 节。',
        '机理假设（机理研究必填，纯单分子性质研究写不适用）': reference(6) + '\n\n待人审阅；不生成签字。',
        '参考态与动力学模型（机理研究）': reference(8),
        '计划': reference(9) + '\n\n' + reference(5) + '\n\n通道 CSV 草稿：`analyses/intake/channels.csv.draft`；ensemble_manifests 采样后填写，当前不能直接用于 channel-coverage。',
        '当前阻塞': '科学审阅：草稿待审阅合并；计算方案及适用的机理假设待签，尚未准备第一批 Attempt。',
        '结论': '尚未完成。此文件仅是开题草稿。',
    }
    # Replace only full level-two sections; preserve all template headings.
    matches = list(re.finditer(r'(?m)^## (.+)$', template))
    output = '# 开题包生成的 study 骨架（草稿，待人审阅合并）\n\n'
    output += '保密级别与公开范围：沿用开题包，待负责人核对；本草稿不含任何新签字。\n\n'
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(template)
        body = replacements.get(match[1], template[match.end():end].strip())
        output += match[0] + '\n\n' + body + '\n\n'
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=['channel_id', 'product_branch', 'ensemble_manifests', 'note'])
    writer.writeheader(); writer.writerows(channels)
    return output.encode('utf-8'), stream.getvalue().encode('utf-8')


def run(study, report_file, intake='study.md', draft=False):
    root = study_root(study)
    path = Path(report_file)
    if path.parts[:2] != ('analyses', 'intake') or len(path.parts) < 3 or path.suffix != '.json':
        raise ValueError('--report must be a new .json below analyses/intake/')
    targets = [report_file, *(DRAFTS if draft else ())]
    for name in targets:
        if safe_path(root, name).exists():
            raise ValueError('output already exists: ' + name)
    inputs, checks = {}, []
    documents = collect_documents(root, intake, inputs, checks)
    selected = check_sections(documents.get(intake, ''), checks)
    check_atoms(root, inputs, checks)
    check_structure(root, documents, inputs, checks)
    check_records(documents, selected, checks)
    channels = channel_rows(selected, checks)
    passed = all(item['status'] == 'present' for item in checks)
    report = dict(intake=intake, checks=checks, all_present=passed, inputs=list(inputs.values()),
                  drafts=list(DRAFTS) if draft and passed else [],
                  scope='Completeness only; no scientific judgment, signature, preparation or submission.')
    payloads = {report_file: (json.dumps(report, ensure_ascii=False, indent=2) + '\n').encode('utf-8')}
    if draft and passed:
        payloads.update(zip(DRAFTS, make_drafts(intake, selected, channels)))
    for entry in list(inputs.values()):
        read_bytes(root, entry['path'], inputs)
    for name, data in payloads.items():
        target = safe_path(root, name)
        target.parent.mkdir(parents=True, exist_ok=True)
        with safe_path(root, name).open('xb') as stream:
            stream.write(data)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', required=True)
    parser.add_argument('--intake', default='study.md', help='study-relative Markdown file; default study.md')
    parser.add_argument('--report', required=True, help='new study-relative analyses/intake/*.json')
    parser.add_argument('--draft', action='store_true', help='write unsigned drafts only when all checks are present')
    args = parser.parse_args()
    try:
        report = run(args.study, args.report, args.intake, args.draft)
    except (ValueError, OSError, UnicodeError) as exc:
        parser.exit(2, f'ERROR: {str(exc).replace(str(Path(args.study).absolute()), "STUDY")}\n')
    print(json.dumps({'all_present': report['all_present'], 'report': args.report, 'checks': report['checks'],
                      'drafts': report['drafts']}, ensure_ascii=False))
    return 0 if report['all_present'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
