"""Offline traceability: disposable Git repository and synthetic water facts."""
import json
import os
from pathlib import Path
import subprocess

import pytest
from ag import attempt, cards, cli, review, study
from test_core import cfg, prepared, INPUT
from test_slurm import multi


CARD = '''# Test recipe

## 6. 结果判据清单

- `termination=normal`、`opt_converged=true`、`freq_step_converged=true`、`n_imag=0`；还需核对完整日志。
- 身份与立体化学正确；输出中的 A | B 需人工核对。
- 多行判据第一行
  后续依据也必须保留。

### 补充检查

- 补充科学判断。

## 7. 常见失败与处理

- 不属于结果判据。
'''


@pytest.fixture
def repository(tmp_path, monkeypatch):
    root = tmp_path / 'recipes-repo'
    directory = root / 'skills-next/auto-g16-recipes/cards'
    directory.mkdir(parents=True)
    (directory / 'opt-freq.md').write_text(CARD)
    (directory / 'ts.md').write_text(CARD.replace('n_imag=0', 'n_imag=1'))
    def git(*args):
        return subprocess.check_output(['git', '-C', str(root), *args], text=True).strip()
    git('init', '-q')
    git('add', 'skills-next')
    git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
        '-c', 'commit.gpgsign=false', 'commit', '-qm', 'Fixture recipes')
    monkeypatch.setattr(cards, 'directory', lambda: directory)
    return root, directory, git


def prepare_card(cfg, tmp_path, name='opt-freq'):
    study.init(cfg, 'smoke')
    source = tmp_path / 'water.gjf'
    source.write_text(INPUT.replace(' SP', ' Opt Freq'))
    manifest = attempt.prepare(cfg, method_basis='兜底方法：合成测试', study_name='smoke', template='gaussian', input_path=source,
                               tier='simple', walltime='00:30:00', label='opt', card=name)
    path = attempt.find(cfg, manifest['attempt_id'])
    return path, manifest


def facts(path, manifest, **changes):
    data = dict(termination='normal', opt_converged=True, freq_step_converged=True,
                n_imag=0, route=manifest['science']['route'], charge=0, multiplicity=1,
                freq_step_convergence={'line': 42})
    data.update(changes)
    (path / 'facts.json').write_text(json.dumps(data))


def complete(path):
    p = path / 'review.md'
    p.write_text(p.read_text().replace(' |  |  |', ' | outputs/water.log:42 | 无法判断 |'))


def test_prepare_records_card_commit_and_clean_state(cfg, tmp_path, repository):
    _, directory, git = repository
    path, m = prepare_card(cfg, tmp_path, 'opt-freq.md')
    assert m['card'] == dict(name='opt-freq', git_commit=git('rev-parse', 'HEAD'), dirty=False, content=CARD)
    assert attempt.read_manifest(path)['card'] == m['card']
    summary = attempt.summary(cfg, m)
    assert f"Card: opt-freq | Skills: {m['card']['git_commit'][:7]}" in summary
    # Changed/current card never substitutes for the saved decision criteria.
    (directory / 'opt-freq.md').write_text('Changed since preparation')
    review.init(path)
    assert '补充科学判断' in (path / 'review.md').read_text()


@pytest.mark.parametrize('kind', ['unstaged', 'staged', 'untracked'])
def test_prepare_marks_dirty(cfg, tmp_path, repository, kind):
    root, directory, git = repository
    if kind == 'untracked':
        (root / 'new-note.md').write_text('new')
    else:
        (directory / 'opt-freq.md').write_text(CARD + '\nnew advice\n')
        if kind == 'staged':
            git('add', 'skills-next')
    _, m = prepare_card(cfg, tmp_path)
    assert m['card']['dirty'] is True
    assert '(dirty)' in attempt.summary(cfg, m)


def test_deployed_symlink_uses_its_repository(tmp_path, monkeypatch):
    deployed = tmp_path / '.codex/skills/auto-g16-recipes'
    deployed.parent.mkdir(parents=True)
    target = tmp_path / 'repo/skills-next/auto-g16-recipes'
    (target / 'cards').mkdir(parents=True)
    deployed.symlink_to(target, target_is_directory=True)
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    assert cards.directory() == target.resolve() / 'cards'


@pytest.mark.parametrize('name', ['../opt-freq', '/opt-freq', 'missing'])
def test_invalid_card_leaves_no_attempt(cfg, tmp_path, repository, name):
    with pytest.raises((ValueError, FileNotFoundError)):
        prepare_card(cfg, tmp_path, name)
    assert list((Path(cfg['local']['studies_root']) / 'smoke/attempts').iterdir()) == []


def test_init_prefills_only_deterministic_facts(cfg, tmp_path, repository):
    path, m = prepare_card(cfg, tmp_path)
    facts(path, m)
    result = review.init(path)
    text = (path / 'review.md').read_text()
    assert result['rows'] == 11  # Seven facts, four full scientific criteria.
    for key in ('termination', 'opt_converged', 'freq_step_converged', 'n_imag', 'route', 'charge', 'multiplicity'):
        line = next(line for line in text.splitlines() if '| facts 核对：' + key in line)
        assert f'facts.json: {key}=' in line and line.endswith('| 通过 |')
    assert 'freq_step_convergence=' in text and '42' in text
    assert '多行判据第一行 后续依据也必须保留。 |  |  |' in text
    assert 'A &#124; B' in text
    assert '不属于结果判据' not in text
    assert review.check(path)['complete'] is False
    complete(path)
    assert review.check(path) == dict(attempt_id=path.name, complete=True, stale=False, issues=[], warnings=[])


@pytest.mark.parametrize('key,value,conclusion', [
    ('termination', 'error', '不通过'), ('termination', 'incomplete', '不通过'),
    ('opt_converged', False, '不通过'), ('freq_step_converged', False, '不通过'),
    ('freq_step_converged', None, '无法判断'), ('n_imag', 1, '不通过'),
    ('charge', 1, '不通过'), ('multiplicity', 3, '不通过'), ('route', '# HF/STO-3G', '不通过'),
    ('charge', None, '无法判断'), ('n_imag', False, '无法判断'), ('opt_converged', 'true', '无法判断'),
])
def test_fact_failures_and_unknowns(cfg, tmp_path, repository, key, value, conclusion):
    path, m = prepare_card(cfg, tmp_path)
    facts(path, m, **{key: value})
    review.init(path)
    line = next(line for line in (path / 'review.md').read_text().splitlines() if '| facts 核对：' + key in line)
    assert line.endswith('| ' + conclusion + ' |')


def test_ts_count_does_not_approve_direction(cfg, tmp_path, repository):
    path, m = prepare_card(cfg, tmp_path, 'ts')
    facts(path, m, n_imag=1)
    review.init(path)
    assert '| facts 核对：n_imag = 1 | facts.json: n_imag=1 | 通过 |' in (path / 'review.md').read_text()
    assert not review.check(path)['complete']


@pytest.mark.parametrize('card', ['opt-freq', 'ts'])
@pytest.mark.parametrize('n_imag,conclusion', [(0, '通过'), (None, '无法判断')])
def test_monatomic_expected_count_and_basis(cfg, tmp_path, repository, card, n_imag, conclusion):
    path, m = prepare_card(cfg, tmp_path, card)
    facts(path, m, n_atoms=1, monatomic=True, n_imag=n_imag, freq_step_converged=None)
    review.init(path)
    text = (path / 'review.md').read_text()
    line = next(line for line in text.splitlines() if '| facts 核对：n_imag' in line)
    assert 'n_imag = 0' in line and '期望值依据：monatomic=true，单原子无振动模式' in line
    assert line.endswith('| ' + conclusion + ' |')
    assert not review.check(path)['complete']
    complete(path)
    assert review.check(path)['complete']
    assert not review.check(path)['stale']


def test_missing_facts_stays_unknown(cfg, tmp_path, repository):
    path, _ = prepare_card(cfg, tmp_path)
    review.init(path)
    assert (path / 'review.md').read_text().count('| 无法判断 |') == 7
    assert not review.check(path)['stale']


def test_existing_review_is_not_overwritten(cfg, tmp_path, repository):
    path, _ = prepare_card(cfg, tmp_path)
    (path / 'review.md').write_text('preserve bytes')
    with pytest.raises(FileExistsError):
        review.init(path)
    assert (path / 'review.md').read_text() == 'preserve bytes'


def test_legacy_manifest_is_not_guessed(prepared):
    path, _ = prepared
    with pytest.raises(ValueError, match='no card'):
        review.init(path)
    assert not (path / 'review.md').exists()


def test_check_missing_evidence_and_deleted_row_read_only(cfg, tmp_path, repository):
    path, m = prepare_card(cfg, tmp_path)
    facts(path, m)
    review.init(path)
    complete(path)
    p = path / 'review.md'
    p.write_text(p.read_text().replace('outputs/water.log:42', '').replace('| 补充科学判断。 |  | 无法判断 |\n', ''))
    before = {f.name: (f.read_bytes(), f.stat().st_mtime_ns) for f in path.iterdir() if f.is_file()}
    result = review.check(path)
    assert any('缺少依据' in s for s in result['issues'])
    assert any('缺少判据行' in s for s in result['issues'])
    assert before == {f.name: (f.read_bytes(), f.stat().st_mtime_ns) for f in path.iterdir() if f.is_file()}


@pytest.mark.parametrize('change', ['regenerated', 'changed', 'removed', 'created'])
def test_check_stale_facts(cfg, tmp_path, repository, change):
    path, m = prepare_card(cfg, tmp_path)
    if change != 'created':
        facts(path, m)
    review.init(path)
    complete(path)
    if change == 'removed':
        (path / 'facts.json').unlink()
    else:
        facts(path, m, n_imag=1 if change == 'changed' else 0)
        newer = (path / 'review.md').stat().st_mtime_ns + 1_000_000
        os.utime(path / 'facts.json', ns=(newer, newer))
    result = review.check(path)
    assert result['complete'] and result['stale']
    assert any('review 可能过期' in warning for warning in result['warnings'])


def test_cli_prepare_review_are_local(cfg, tmp_path, repository, monkeypatch, capsys):
    study.init(cfg, 'smoke')
    source = tmp_path / 'water.gjf'
    source.write_text(INPUT)
    monkeypatch.setattr(cli, 'load_config', lambda **_: cfg)
    monkeypatch.setattr('ag.transport.SSHTransport', lambda *a, **k: pytest.fail('local review must not connect'))
    assert cli.main(['prepare', '--method-basis', '兜底方法：合成测试', '--study', 'smoke', '--template', 'gaussian', '--input', str(source),
                     '--tier', 'simple', '--walltime', '00:30:00', '--label', 'sp', '--card', 'opt-freq', '--json']) == 0
    m = json.loads(capsys.readouterr().out)
    assert m['card']['name'] == 'opt-freq'
    assert cli.main(['review', 'init', m['attempt_id'], '--json']) == 0
    capsys.readouterr()
    assert cli.main(['review', 'check', m['attempt_id'], '--json']) == 1
    assert not json.loads(capsys.readouterr().out)['complete']


def test_stale_review_can_be_explicitly_reassessed(cfg, tmp_path, repository):
    path, m = prepare_card(cfg, tmp_path)
    facts(path, m)
    review.init(path)
    complete(path)
    facts(path, m, n_imag=1)
    result = review.check(path)
    assert result['stale']
    # A reviewer must reassess the row, then record the examined facts snapshot.
    import re
    p = path / 'review.md'
    text = p.read_text().replace('facts.json: n_imag=0 | 通过', 'facts.json: n_imag=1 | 不通过')
    text = re.sub(r'<!-- facts: .+ -->', '<!-- facts: ' + json.dumps(result['current_facts']) + ' -->', text)
    p.write_text(text)
    assert review.check(path)['stale'] is False


@pytest.mark.parametrize('dirty', [False, True, None])
def test_changed_evidence_reports_bound_ag_commit(cfg, tmp_path, repository, dirty):
    path, m = prepare_card(cfg, tmp_path)
    bound = {'git_commit': 'a' * 40, 'dirty': dirty}
    facts(path, m, ag_provenance=bound)
    review.init(path)
    complete(path)
    # The new parser commit and Skills commit must never replace the bound one.
    facts(path, m, n_imag=1, ag_provenance={'git_commit': 'b' * 40, 'dirty': False})
    before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in path.iterdir() if p.is_file()}
    result = review.check(path)
    assert result['stale'] and result['bound_ag_commit'] == 'a' * 40
    warning = result['warnings'][0]
    assert '证据文件已变化' in warning and 'a' * 40 in warning
    assert 'b' * 40 not in warning and m['card']['git_commit'] not in warning
    assert ('仅该提交不能保证复现' in warning) == (dirty is not False)
    assert before == {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in path.iterdir() if p.is_file()}


def test_legacy_changed_evidence_does_not_invent_commit(cfg, tmp_path, repository):
    path, m = prepare_card(cfg, tmp_path)
    facts(path, m)
    review.init(path)
    facts(path, m, n_imag=1)
    result = review.check(path)
    assert result['bound_ag_commit'] is None
    assert '证据文件已变化' in result['warnings'][0]
    assert '历史记录未保存 ag 提交号' in result['warnings'][0]


def test_missing_git_provenance_is_not_invented(tmp_path, monkeypatch):
    directory = tmp_path / 'cards'
    directory.mkdir()
    (directory / 'sp.md').write_text(CARD)
    monkeypatch.setattr(cards, 'directory', lambda: directory)
    with pytest.raises(ValueError, match='Git provenance'):
        cards.snapshot('sp')


@pytest.mark.parametrize('name', ['review.md', 'facts.json'])
def test_review_rejects_symlink_files(cfg, tmp_path, repository, name):
    path, m = prepare_card(cfg, tmp_path)
    outside = tmp_path / 'outside'
    outside.write_text('{}')
    (path / name).symlink_to(outside)
    with pytest.raises(ValueError, match='Symbolic links'):
        review.init(path)
    assert outside.read_text() == '{}'


def test_real_card_nested_checklists_and_continuations():
    root = Path(__file__).resolve().parents[2] / 'skills-next/auto-g16-recipes/cards'
    items = cards.criteria((root / 'opt-freq.md').read_text())
    assert len(items) == 12
    assert any('实际方法、电荷或多重度不符' in item for item in items)
    profile = cards.criteria((root / 'profile.md').read_text())
    assert any('符合实验 ee 或速率不能证明唯一机理' in item for item in profile)


def test_submit_dialog_includes_card_provenance(cfg, tmp_path, repository, monkeypatch):
    from ag import confirm, submit
    from test_core import Fake
    path, m = prepare_card(cfg, tmp_path)
    seen = []
    monkeypatch.setattr(confirm, 'confirm', lambda text: seen.append(text) or False)
    with pytest.raises(submit.UserCancelled):
        submit.submit(cfg, [path.name], Fake(cfg))
    assert f"Card: opt-freq | Skills: {m['card']['git_commit'][:7]}" in seen[0]


@pytest.mark.parametrize('expressions,target', [('n_imag=2', 2), ('missing', None), ('n_imag=0 / n_imag=1', None)])
def test_count_target_comes_from_saved_card_not_its_name(cfg, tmp_path, repository, expressions, target):
    _, directory, _ = repository
    (directory / 'opt-freq.md').write_text(CARD.replace('n_imag=0', expressions))
    path, m = prepare_card(cfg, tmp_path)
    facts(path, m, n_imag=2)
    review.init(path)
    text = (path / 'review.md').read_text()
    line = next(line for line in text.splitlines() if '| facts 核对：n_imag' in line)
    assert f'n_imag = {json.dumps(target)}' in line
    assert line.endswith('| ' + ('通过' if target == 2 else '无法判断') + ' |')


def test_card_and_slurm_cluster_survive_integration(multi, tmp_path, repository, monkeypatch, capsys):
    from ag import config, confirm, submit
    from test_slurm import SlurmFake
    study.init(multi, 'smoke')
    source = tmp_path / 'water.gjf'
    source.write_text(INPUT.replace(' SP', ' Opt Freq'))
    monkeypatch.setattr(cli, 'load_config', lambda **_: multi)
    monkeypatch.setattr('ag.transport.SSHTransport', lambda *a, **k: pytest.fail('prepare/review are local'))
    assert cli.main(['prepare', '--method-basis', '兜底方法：合成测试', '--study', 'smoke', '--template', 'gaussian', '--input', str(source),
                     '--tier', 'simple', '--walltime', '01:30:00', '--label', 'opt',
                     '--cluster', 'batch', '--card', 'opt-freq', '--json']) == 0
    m = json.loads(capsys.readouterr().out)
    path = attempt.find(multi, m['attempt_id'])
    assert (m['cluster'], m['scheduler'], m['card']['name']) == ('batch', 'slurm', 'opt-freq')
    files = attempt.verified_files(multi, path, m)
    assert 'job.slurm' in files and 'job.pbs' not in files
    assert '--no-requeue' in files['job.slurm'].decode()
    for token in ('Cluster: batch', '12 核时', cards.label(m)):
        assert token in attempt.summary(multi, m)
    facts(path, m)
    assert cli.main(['review', 'init', path.name, '--json']) == 0
    capsys.readouterr()
    complete(path)
    assert cli.main(['review', 'check', path.name, '--json']) == 0
    capsys.readouterr()
    seen = []
    monkeypatch.setattr(confirm, 'confirm', lambda text: seen.append(text) or False)
    fake = SlurmFake(config.select_cluster(multi, 'batch'))
    with pytest.raises(submit.UserCancelled):
        submit.submit(multi, [path.name], fake)
    for token in ('Cluster: batch', '12 核时', cards.label(m)):
        assert token in seen[0]
    assert 'submit' not in fake.operations() and not (path / '.submit-claim').exists()


@pytest.mark.parametrize('cluster', ['default', 'batch'])
@pytest.mark.parametrize('legacy', [False, True])
def test_review_cli_reads_multicluster_toml(multi, tmp_path, repository, monkeypatch, capsys, cluster, legacy):
    from ag import config
    from test_core import write_config
    from test_slurm import prepare
    path, m = prepare(multi, tmp_path, cluster, 'review')
    if not legacy:
        m['card'] = cards.snapshot('opt-freq')
        (path / 'manifest.json').write_text(json.dumps(m))
    else:
        m.pop('card', None)
        (path / 'manifest.json').write_text(json.dumps(m))
    original = (path / 'manifest.json').read_bytes()
    facts(path, m)
    # Exercise the actual TOML loader, including a pure multi-cluster file
    # without top-level ssh/scheduler/resources, rather than mocking load_config.
    home = tmp_path / 'home'
    conf = home / '.config/ag'
    conf.mkdir(parents=True)
    multi['_config_dir'] = str(conf)
    write_config(multi)
    monkeypatch.setattr(Path, 'home', lambda: home)
    monkeypatch.setattr('ag.transport.SSHTransport', lambda *a, **k: pytest.fail('review is local'))
    assert 'clusters' in config.load_config()
    args = ['review', 'init', path.name, '--json']
    if legacy:
        args += ['--card', 'opt-freq']
    assert cli.main(args) == 0
    assert json.loads(capsys.readouterr().out)['review'] == 'review.md'
    assert cli.main(['review', 'check', path.name, '--json']) == 1
    assert not json.loads(capsys.readouterr().out)['complete']
    complete(path)
    assert cli.main(['review', 'check', path.name, '--json']) == 0
    assert json.loads(capsys.readouterr().out)['complete']
    assert (path / 'manifest.json').read_bytes() == original


@pytest.mark.parametrize('problem', ['ssh', 'gaussian-field'])
def test_local_review_does_not_require_remote_cluster_credentials(multi, tmp_path, repository, monkeypatch, capsys, problem):
    from ag import config
    from test_core import write_config
    path, m = prepare_card(multi, tmp_path)
    facts(path, m)
    home = tmp_path / 'home'
    conf = home / '.config/ag'
    conf.mkdir(parents=True)
    multi['_config_dir'] = str(conf)
    if problem == 'ssh':
        del multi['clusters']['batch']['ssh']
        error = 'Missing or invalid local configuration'
    else:
        multi['clusters']['batch']['programs']['gaussian']['legacy_note'] = 'fixture'
        error = 'Unsupported Gaussian environment field'
    write_config(multi)
    monkeypatch.setattr(Path, 'home', lambda: home)
    monkeypatch.setattr('ag.transport.SSHTransport', lambda *a, **k: pytest.fail('review is local'))
    with pytest.raises(config.ConfigError, match=error):
        config.load_config()  # Submission still requires complete remote configuration.
    assert cli.main(['review', 'init', path.name, '--json']) == 0
    capsys.readouterr()
    complete(path)
    assert cli.main(['review', 'check', path.name, '--json']) == 0
    assert json.loads(capsys.readouterr().out)['complete']


def test_legacy_review_captures_card_without_changing_manifest(prepared, repository):
    path, m = prepared
    m.pop('card', None)
    (path / 'manifest.json').write_text(json.dumps(m))
    original = (path / 'manifest.json').read_bytes()
    facts(path, m)
    _, directory, git = repository
    review.init(path, card='opt-freq')
    text = (path / 'review.md').read_text()
    assert '卡片为审阅时补指定，非准备时记录' in text
    assert git('rev-parse', 'HEAD') in text
    assert 'Card: opt-freq' in text
    complete(path)
    # Later edits or removal of the current card cannot silently change criteria.
    (directory / 'opt-freq.md').unlink()
    assert review.check(path)['complete']
    p = path / 'review.md'
    p.write_text(p.read_text().replace('| 补充科学判断。 | outputs/water.log:42 | 无法判断 |\n', ''))
    assert not review.check(path)['complete']
    assert (path / 'manifest.json').read_bytes() == original


def test_review_card_cannot_replace_preparation_record(cfg, tmp_path, repository):
    path, _ = prepare_card(cfg, tmp_path)
    with pytest.raises(ValueError, match='cannot replace'):
        review.init(path, card='ts')
    assert not (path / 'review.md').exists()


@pytest.mark.parametrize('snapshot', ['', '<!-- review-card: {} -->\n', '<!-- review-card: {broken} -->\n'])
def test_legacy_check_rejects_missing_or_damaged_snapshot(prepared, snapshot):
    path, _ = prepared
    (path / 'review.md').write_text(snapshot)
    with pytest.raises(ValueError, match=path.name):
        review.check(path)
