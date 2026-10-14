"""Prevent stale CLI examples, completed-task blockers and copied method drift.

Read the actual CLI registration without parsing arguments or dispatching commands.
No configuration, private studies, chemistry programs or network are used here.
"""
import argparse
from pathlib import Path
import re
import shlex

import pytest

ROOT = Path(__file__).resolve().parents[2]
SKILLS = ROOT / 'skills-next'
CARDS = SKILLS / 'auto-g16-recipes/cards'
METHODS = SKILLS / 'auto-g16-study/references/acceptance-methods.md'
# Include references too: teaching cards and linked command examples must not drift.
DOCUMENTS = sorted(SKILLS.glob('auto-g16-*/**/*.md'))
CODE = re.compile(r'```[^\n]*\n(?P<block>.*?)```|`(?P<inline>[^`]+)`', re.S)
PENDING = re.compile(r'待\s*(T\d+(?:[a-z]|-\d+)?)(?![A-Za-z0-9_-])', re.I)
PAIR = re.compile(r'(?<![\w<>/])([A-Za-z][A-Za-z0-9+-]*)/([A-Za-z0-9][A-Za-z0-9+*,()_-]*)')


@pytest.fixture(scope='module')
def cli_parser():
    from ag import cli

    class Captured(Exception):
        pass

    captured = []

    def capture(parser, *args, **kwargs):
        captured.append(parser)
        raise Captured

    # Capture main's parser, including future modules, rather than duplicating its list.
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(argparse.ArgumentParser, 'parse_args', capture)
        with pytest.raises(Captured):
            cli.main([])
    return captured[0]


def commands(text):
    """Scan fenced/inline examples (including wrapped ones), then plain prose lines."""
    spans = list(CODE.finditer(text))
    pieces = [(m.start(), m.group('block') if m.group('block') is not None
               else m.group('inline').replace('\n', ' ')) for m in spans]
    plain = list(text)
    for m in spans:
        plain[m.start():m.end()] = ' ' * (m.end() - m.start())
    pieces.extend((m.start(), m.group()) for m in re.finditer(r'[^\n]+', ''.join(plain)))
    for offset, piece in sorted(pieces):
        piece = re.sub(r'\\\n\s*', ' ', piece)
        # A command ends at another command, shell separator or prose punctuation.
        for match in re.finditer(r'(?<![\w/])ag\s+(?=[a-z-])(.+?)(?=(?<![\w/])ag\s+|[;|&；。\n]|$)', piece, re.S):
            command = match.group(1)
            yield text.count('\n', 0, offset) + 1, command


def check_command(parser, command):
    # Placeholders may contain spaces or punctuation; they are values, not options.
    command = re.sub(r'<[^>]*>', 'VALUE', command)
    tokens = shlex.split(command.replace('[--', '--').replace(']', ''))
    current = parser
    i = 0
    while i < len(tokens):
        token = tokens[i]
        actions = current._option_string_actions
        children = next((a.choices for a in current._actions
                         if isinstance(a, argparse._SubParsersAction)), None)
        if token.startswith('-'):
            option, equals, _ = token.partition('=')
            assert option in actions, f'unknown option {option} for {current.prog}'
            action = actions[option]
            # Values such as --param="--gfn 2" belong to the program template.
            if not equals and action.nargs != 0:
                if action.nargs in (None, '?'):
                    if i + 1 < len(tokens) and (option == '--param' or not tokens[i + 1].startswith('--')):
                        i += 1
                elif isinstance(action.nargs, int):
                    i += action.nargs
                else:
                    while i + 1 < len(tokens) and not tokens[i + 1].lstrip('[').startswith('-'):
                        i += 1
        elif children is not None:
            assert token in children, f'unknown subcommand {token} for {current.prog}'
            current = children[token]
        i += 1


@pytest.mark.parametrize('path', DOCUMENTS, ids=lambda p: str(p.relative_to(SKILLS)))
def test_documented_cli_exists(path, cli_parser):
    for line, command in commands(path.read_text()):
        try:
            check_command(cli_parser, command)
        except (AssertionError, ValueError) as exc:
            pytest.fail(f'{path.relative_to(ROOT)}:{line}: {command}: {exc}')


def pending_tasks(text):
    return set(PENDING.findall(text))


def check_pending(text, open_tasks):
    missing = pending_tasks(text) - open_tasks
    assert not missing, f'completed/unregistered pending tasks {missing}'


def test_pending_tasks_are_open():
    registry = ROOT / 'docs/redesign-tasks/open-tasks.txt'
    entries = [line.split('#', 1)[0].strip() for line in registry.read_text().splitlines()]
    entries = [line for line in entries if line]
    assert len(entries) == len(set(entries)), 'duplicate open task'
    assert all(re.fullmatch(r'T\d+(?:[a-z]|-\d+)?', entry) for entry in entries)
    for path in DOCUMENTS:
        try:
            check_pending(path.read_text(), set(entries))
        except AssertionError as exc:
            pytest.fail(f'{path.relative_to(ROOT)}: {exc}')


def routes(text):
    """Yield fenced, inline and bare routes with a locally scoped example label."""
    spans = list(CODE.finditer(text))
    for match in spans:
        code = match.group('block') or match.group('inline')
        before = text[:match.start()].rstrip()
        context = before.rsplit('\n\n', 1)[-1]
        for route in re.finditer(r'(?:^|\n)\s*#[pPnN]?\s+([^\n]+(?:\n(?!\s*\n)[^\n]+)*)', code):
            yield route.group(), context
    # Bare #p/#n lines are route examples too; Markdown prose headings are not.
    for match in re.finditer(r'^#[pPnN]?[ \t]+[^\n]+', text, re.M):
        if any(span.start() <= match.start() < span.end() for span in spans):
            continue
        if not re.match(r'^#[pPnN]\s', match.group()) and not PAIR.search(match.group()):
            continue
        yield match.group(), text[:match.start()].rstrip().rsplit('\n\n', 1)[-1]


def combination(route):
    pairs = PAIR.findall(route)
    if not pairs:
        assert '<方法/基组>' in route, 'route must use <方法/基组> or an explicit method/basis'
        return None
    assert len(pairs) == 1, 'route must contain one method/basis combination'
    dispersion = re.search(r'EmpiricalDispersion\s*=\s*(\w+)', route, re.I)
    method, basis = pairs[0]
    return method.lower(), basis.lower(), dispersion.group(1).lower() if dispersion else 'none'


def allowed_combinations():
    text = METHODS.read_text()
    table = text.split('<!-- gaussian-combinations -->', 1)[1].split('<!-- /gaussian-combinations -->', 1)[0]
    return {combination(value) for value in re.findall(r'`([^`]+)`', table)}


def check_routes(text, allowed):
    for route, context in routes(text):
        signature = combination(route)
        if signature:
            assert signature in allowed, f'method/basis/dispersion absent from acceptance-methods.md: {signature}'
            assert '流程验收示例' in context, 'concrete route needs its own 流程验收示例 label'
        else:
            assert 'acceptance-methods.md' in text, 'method placeholder needs acceptance-methods.md link'


@pytest.mark.parametrize('path', sorted(CARDS.glob('*.md')), ids=lambda p: p.stem)
def test_card_methods_have_one_definition(path):
    check_routes(path.read_text(), allowed_combinations())


def test_cli_checker_rejects_drift(cli_parser):
    for command in ('imaginary --json', 'prepare --typo value', 'review missing x',
                    'review check x --card ts', 'facts x --cluster default',
                    'prepare --stud value', 'prepare --input --typo'):
        with pytest.raises(AssertionError):
            check_command(cli_parser, command)
    for command in ('prepare --param=--gfn=2 --param "--alpb water" --json',
                    'review init x --card ts --json', 'scan-peak x --out new.xyz [--json]'):
        check_command(cli_parser, command)


def test_scanner_covers_inline_fenced_prose_and_continuations():
    text = ('`ag review init x --card ts`\n```sh\nag prepare \\\n'
            ' --input x --typo z\n```\nag facts x --json。\n'
            '`ag prepare --template xtb\n--constraints x --typo z`')
    found = [command for _, command in commands(text)]
    assert len(found) == 4
    assert '--typo' in found[1]
    assert '--json' in found[2]
    assert '--typo' in found[3]


def test_pending_checker_rejects_completed_task():
    assert pending_tasks('待 T13；待T13-2，待 T24；已完成 T21') == {'T13', 'T13-2', 'T24'}
    check_pending('待 T24；已完成 T13', {'T24'})
    with pytest.raises(AssertionError, match='T13'):
        check_pending('缺功能待T13实现', {'T24'})


def test_route_checker_rejects_drift():
    allowed = allowed_combinations()
    example = '流程验收示例：\n\n```text\n#p B3LYP/6-31G(d) EmpiricalDispersion=GD3BJ Opt Freq\n\n```'
    check_routes(example, allowed)
    check_routes('见 acceptance-methods.md\n\n`#p <方法/基组> Opt Freq`', allowed)
    for invalid in (example.replace('流程验收示例', '研究骨架'),
                    example.replace('6-31G(d)', 'def2SVP'),
                    example.replace(' EmpiricalDispersion=GD3BJ', ''),
                    example.replace('B3LYP', 'InventedFunctional'),
                    '#p B3LYP/def2SVP SP',
                    example + '\n\n研究骨架：\n\n`#p B3LYP/6-31G(d) EmpiricalDispersion=GD3BJ SP`'):
        with pytest.raises(AssertionError):
            check_routes(invalid, allowed)


def test_recipe_knowledge_ids_exist():
    library = SKILLS / 'auto-g16-gaussian-learning-library/references'
    known = set()
    for path in library.glob('*.md'):
        known.update(re.findall(r'^### (GKB-\d{4})\b', path.read_text(), re.M))
    for path in CARDS.glob('*.md'):
        text = path.read_text()
        ids = set(re.findall(r'GKB-\d{4}', text))
        assert ids and ids <= known, f'{path.name}: missing/unknown GKB link {ids - known}'


def check_prepare_method_basis(text):
    """Full study-scoped examples must not silently inherit a fallback basis."""
    for line, command in commands(text):
        tokens = shlex.split(re.sub(r'<[^>]*>', 'VALUE', command))
        if tokens[:2] != ['prepare', '--study'] or any(t in ('...', '…') for t in tokens):
            continue
        assert any(t.split('=', 1)[0] == '--method-basis' for t in tokens), (
            f'line {line}: ag prepare --study example must include --method-basis')


@pytest.mark.parametrize('path', sorted(CARDS.glob('*.md')) +
                         sorted((SKILLS / 'auto-g16-study').rglob('*.md')),
                         ids=lambda p: str(p.relative_to(SKILLS)))
def test_prepare_examples_have_explicit_method_basis(path):
    check_prepare_method_basis(path.read_text())


@pytest.mark.parametrize('wrapper', ('`{command}`', '```sh\n{command}\n```',
                                     '```sh\n{command} \\\n  --json\n```'))
@pytest.mark.parametrize('template', ('gaussian', 'xtb', 'crest'))
def test_prepare_basis_checker_catches_missing_parameter(wrapper, template):
    command = (f'ag prepare --study <study_id> --template {template} --input <input> '
               '--tier simple --walltime 00:30:00 --label example')
    with pytest.raises(AssertionError, match='must include --method-basis'):
        check_prepare_method_basis(wrapper.format(command=command))
    for basis in (' --method-basis <文献先例 DOI 及位置 / 本课题既有方案及来源 / 兜底方法声明>',
                  ' --method-basis="兜底方法：合成测试"'):
        check_prepare_method_basis(wrapper.format(command=command + basis))
    # A mention inside another argument is not the method-basis option.
    with pytest.raises(AssertionError, match='must include --method-basis'):
        check_prepare_method_basis(wrapper.format(command=command + ' --card "--method-basis text"'))
