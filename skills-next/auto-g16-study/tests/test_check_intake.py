"""Only invented intake data; exercise safety, evidence binding and draft output."""
import csv
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys

import pytest

SCRIPT = Path(__file__).parents[1] / 'scripts/check_intake.py'
spec = importlib.util.spec_from_file_location('intake_check', SCRIPT)
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)
FIXTURE = Path(__file__).parent / 'fixtures/intake.md'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_study(root):
    root.mkdir(parents=True, exist_ok=True)
    (root / 'analyses/intake').mkdir(parents=True)
    (root / 'structures').mkdir()
    (root / 'structures/methane.smi').write_text('C\n')
    (root / 'analyses/intake/species-check.md').write_text('# 合成结构报告\n')
    (root / 'analyses/synthetic-manifest.json').write_text('{}\n')
    report = {'species': [{'species_id': 'methane', 'status': 'all_match', 'multiplicity': 1,
                          'checks': {'formula': {'status': 'match'}, 'cip': {'status': 'match'}}, 'read_errors': []}],
              'reaction': {'status': 'unknown', 'reason': 'reaction CSV not supplied'},
              'inputs': [{'path': 'structures/methane.smi', 'sha256': sha(root / 'structures/methane.smi')}]}
    (root / check.SPECIES_REPORT).write_text(json.dumps(report))
    (root / 'atoms.csv').write_text('atom_id,species_id,structure_file,atom_index_1based,element,reaction_role,mapping_source,review_status,reviewer_date,notes\nC1,methane,structures/methane.smi,1,C,其他,合成记录,已确认,合成角色 2000-01-01,不用于科学判断\n')
    text = FIXTURE.read_text()
    for token, path in {'REPORT_HASH': check.SPECIES_REPORT, 'MARKDOWN_HASH': 'analyses/intake/species-check.md',
                        'SOURCE_HASH': 'structures/methane.smi', 'MANIFEST_HASH': 'analyses/synthetic-manifest.json'}.items():
        text = text.replace(token, sha(root / path))
    (root / 'study.md').write_text(text)
    return root


def edit(root, old, new, name='study.md'):
    path = root / name
    text = path.read_text(); assert old in text
    path.write_text(text.replace(old, new))


def report_change(root, change):
    path = root / check.SPECIES_REPORT
    previous = sha(path)
    report = json.loads(path.read_text()); change(report)
    path.write_text(json.dumps(report))
    edit(root, previous, sha(path))


def run(root, **kwargs):
    return check.run(root, 'analyses/intake/check.json', **kwargs)


def finding(report, name):
    return next(c['status'] for c in report['checks'] if c['id'] == name)


def test_complete_intake_drafts_preserve_originals_and_values(tmp_path):
    root = make_study(tmp_path)
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in root.rglob('*') if p.is_file()}
    report = run(root, draft=True)
    assert report['all_present'], report['checks']
    assert {c['status'] for c in report['checks']} == {'present'}
    assert all((p.read_bytes(), p.stat().st_mtime_ns) == value for p, value in before.items())
    draft = (root / check.DRAFTS[0]).read_text()
    headings = lambda text: [line for line in text.splitlines() if line.startswith('## ')]
    assert headings(draft) == headings((check.REFERENCES / 'study-md-template.md').read_text())
    assert '| methane，反应物 |' in draft
    assert '#p B3LYP/6-31G(d) SP' in draft and '298.15 K' in draft
    assert '计算方案待人审阅签字' in draft
    signature = dict(check.sections(draft))['里程碑签字']
    assert signature.count('| 待签 | 待签 | 待确认 |') == 4
    assert '合成角色' not in signature
    assert '../../study.md#' in draft
    with (root / check.DRAFTS[1]).open(newline='') as stream:
        reader = csv.DictReader(stream); rows = list(reader)
    assert reader.fieldnames == ['channel_id', 'product_branch', 'ensemble_manifests', 'note']
    assert rows[0]['channel_id'] == 'single' and rows[0]['product_branch'] == '甲烷模型'
    assert rows[0]['ensemble_manifests'] == '' and '采样后填写' in rows[0]['note']


@pytest.mark.parametrize('old,new,key,status', [
    ('| 甲烷单点输入准备 |', '| <填写> |', 'section.9', 'missing'),
    ('| 不提交；不做 TS |', '|  |', 'section.9', 'missing'),
    ('## 结构确认条目（0c）', '## 无确认', 'structure.confirmation', 'missing'),
    ('- 确认人：合成角色（非真实签字）。', '- 确认人：待确认', 'structure.confirmation', 'missing'),
    ('确认；仅虚构测试条目', '不确认；仅虚构测试条目', 'structure.species:methane', 'missing'),
    ('## 检索覆盖记录', '## 未检索', 'literature.coverage', 'missing'),
    ('## 会话转述与定稿', '## 未定稿', 'discussion.finalization', 'missing'),
    ('| 确认人、日期/未决项 |', '| 错列 |', 'channels', 'mismatch'),
    ('无反应取向 → 甲烷模型', '无反应取向', 'channels', 'mismatch'),
    ('| 兜底方法 |', '| 未指定 |', 'method:最终 SP', 'mismatch'),
    ('- 动力学模型：不适用：无反应速率目标。', '', 'section.8', 'missing'),
])
def test_missing_or_mismatched_items_block_drafts(tmp_path, old, new, key, status):
    root = make_study(tmp_path); edit(root, old, new)
    report = run(root, draft=True)
    assert finding(report, key) == status and not report['all_present']
    assert not any((root / name).exists() for name in check.DRAFTS)


@pytest.mark.parametrize('name', ['analyses/intake/species-check.md', 'structures/methane.smi', 'analyses/synthetic-manifest.json'])
def test_confirmed_files_changed_or_missing(tmp_path, name):
    root = make_study(tmp_path)
    (root / name).write_text('changed')
    report = run(root)
    assert not report['all_present']
    assert finding(report, 'reference:' + name) == 'mismatch'


def test_hash_must_be_bound_in_confirmation_entry(tmp_path):
    root = make_study(tmp_path)
    value = sha(root / check.SPECIES_REPORT)
    edit(root, f'SHA-256 `{value}`', f'SHA-256 `{"0" * 64}`')
    with (root / 'study.md').open('a') as stream: stream.write('\n## 无关签字\n' + value)
    report = run(root)
    assert finding(report, 'reference:' + check.SPECIES_REPORT) == 'mismatch'


@pytest.mark.parametrize('status,accepted', [('has_mismatch', False), ('has_mismatch', True), ('incomplete', False), ('incomplete', True), ('out_of_scope', True)])
def test_issues_need_specific_acceptance_and_scope_never_expands(tmp_path, status, accepted):
    root = make_study(tmp_path)
    def change(report):
        report['species'][0]['status'] = status
        report['species'][0]['checks']['formula']['status'] = 'unknown' if status == 'incomplete' else 'mismatch'
    report_change(root, change)
    edit(root, 'all_match', status)
    if accepted:
        edit(root, '| 无 |\n\n- 确认人', '| 接受 formula；理由：虚构测试缺项；影响：只验证记录；后续处理：不运行 |\n\n- 确认人')
    report = run(root)
    assert report['all_present'] == (accepted and status != 'out_of_scope')


def test_partial_acceptance_does_not_hide_other_issue(tmp_path):
    root = make_study(tmp_path)
    def change(report):
        item = report['species'][0]; item['status'] = 'has_mismatch'
        item['checks'] = {'formula': {'status': 'mismatch'}, 'cip': {'status': 'unknown'}}
    report_change(root, change); edit(root, 'all_match', 'has_mismatch')
    edit(root, '| 无 |\n\n- 确认人', '| 接受 formula；理由：测试；影响：仅测试 |\n\n- 确认人')
    assert not run(root)['all_present']


@pytest.mark.parametrize('target', [*check.DRAFTS, 'analyses/intake/check.json'])
def test_existing_outputs_refused_without_partial_writes(tmp_path, target):
    root = make_study(tmp_path); (root / target).write_text('retain')
    before = set(root.rglob('*'))
    with pytest.raises(ValueError, match='already exists'): run(root, draft=True)
    assert (root / target).read_text() == 'retain' and set(root.rglob('*')) == before


@pytest.mark.parametrize('target', ['study.md', check.SPECIES_REPORT, 'structures/methane.smi', 'atoms.csv', *check.DRAFTS, 'analyses/intake/check.json', 'analyses'])
def test_symlinks_refused(tmp_path, target):
    root = make_study(tmp_path / 'study'); outside = tmp_path / 'outside'; outside.mkdir()
    path = root / target
    if path.is_dir(): path.rename(root / 'saved-analyses')
    elif path.exists(): path.unlink()
    path.symlink_to(outside if target == 'analyses' else outside / 'missing')
    with pytest.raises(ValueError, match='symlink'): run(root, draft=True)
    assert not list(outside.iterdir())


@pytest.mark.parametrize('option,value', [('intake', '../outside.md'), ('intake', '/outside.md'), ('report_file', '../outside.json'), ('report_file', 'analyses/elsewhere.json')])
def test_argument_escape_refused(tmp_path, option, value):
    root = make_study(tmp_path)
    kwargs = {'report_file': 'analyses/intake/check.json', option: value}
    with pytest.raises(ValueError): check.run(root, **kwargs)


def test_report_input_escape_refused(tmp_path):
    root = make_study(tmp_path)
    report_change(root, lambda report: report['inputs'][0].update(path='../outside.smi'))
    with pytest.raises(ValueError, match='relative'): run(root)


def test_split_records_and_intake_without_existing_study(tmp_path):
    root = make_study(tmp_path)
    text = (root / 'study.md').read_text()
    intake, records = text.split('## 检索覆盖记录', 1)
    (root / 'analyses/records.md').write_text('## 检索覆盖记录' + records)
    (root / 'analyses/intake/intake.md').write_text(intake + '\n记录：[记录](analyses/records.md)\n')
    (root / 'study.md').unlink()
    report = run(root, intake='analyses/intake/intake.md', draft=True)
    assert report['all_present'], report['checks']
    assert not (root / 'study.md').exists()
    assert 'intake.md#' in (root / check.DRAFTS[0]).read_text()


def test_changed_input_during_draft_not_published(tmp_path, monkeypatch):
    root = make_study(tmp_path); original = check.make_drafts
    def changing(*args):
        (root / 'study.md').write_text('changed')
        return original(*args)
    monkeypatch.setattr(check, 'make_drafts', changing)
    with pytest.raises(ValueError, match='input changed'): run(root, draft=True)
    assert not (root / 'analyses/intake/check.json').exists()
    assert not (root / check.DRAFTS[0]).exists()


def test_template_guidance_is_not_finalization(tmp_path):
    root = make_study(tmp_path)
    guidance = dict(check.sections((check.REFERENCES / 'discussion-record.md').read_text()))['会话转述与定稿']
    edit(root, '合成决定 D-1：按上述首轮范围定稿；出处为虚构测试输入，非真实科研签字。', guidance)
    assert finding(run(root), 'discussion.finalization') == 'missing'


def test_cli_failure_writes_report_but_not_drafts(tmp_path):
    root = make_study(tmp_path); (root / check.SPECIES_REPORT).unlink()
    result = subprocess.run([sys.executable, str(SCRIPT), '--study', str(root), '--report', 'analyses/intake/check.json', '--draft'], capture_output=True, text=True)
    assert result.returncode == 1, result.stderr
    assert not json.loads(result.stdout)['all_present']
    assert not (root / check.DRAFTS[0]).exists()


@pytest.mark.parametrize('section', range(1, 10))
def test_each_required_section_is_checked(tmp_path, section):
    root = make_study(tmp_path)
    edit(root, f'## {section}. ', f'## omitted-{section}. ')
    assert finding(run(root), f'section.{section}') == 'missing'


@pytest.mark.parametrize('name', [check.SPECIES_REPORT, 'atoms.csv', 'analyses/intake/species-check.md'])
def test_missing_files_reported(tmp_path, name):
    root = make_study(tmp_path); (root / name).unlink()
    assert not run(root)['all_present']


@pytest.mark.parametrize('value', ['not-json', '[]', '{}', '{"species": [null]}'])
def test_bad_species_reports_fail_closed(tmp_path, value):
    root = make_study(tmp_path)
    previous = sha(root / check.SPECIES_REPORT)
    (root / check.SPECIES_REPORT).write_text(value)
    edit(root, previous, sha(root / check.SPECIES_REPORT))
    assert not run(root)['all_present']


def test_hashes_required_for_each_confirmed_report(tmp_path):
    root = make_study(tmp_path)
    edit(root, sha(root / 'analyses/intake/species-check.md'), 'omitted')
    assert finding(run(root), 'structure.hashes:核验报告') == 'missing'


def test_symlink_study_root_refused(tmp_path):
    root = make_study(tmp_path / 'study')
    alias = tmp_path / 'alias'; alias.symlink_to(root)
    with pytest.raises(ValueError, match='symlink'): run(alias)


def test_channel_csv_quotes_commas_and_escaped_pipes(tmp_path):
    root = make_study(tmp_path)
    edit(root, '甲烷模型', '甲烷,模型')
    edit(root, '纳入，单模型流程测试', r'纳入，A\|B')
    assert run(root, draft=True)['all_present']
    with (root / check.DRAFTS[1]).open(newline='') as stream:
        row = next(csv.DictReader(stream))
    assert row['product_branch'] == '甲烷,模型' and 'A|B' in row['note']
