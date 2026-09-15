"""Offline rejection tests only: no product imports, sudo, C build or Linux run."""
import ast
from contextlib import ExitStack
import copy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent


def load(name):
    spec = importlib.util.spec_from_file_location(name, HERE / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SUPPORT = load('hosted_support')
PROVISION = load('provision_fixture_roots')
LAUNCHER = load('hosted_launcher')


class HostedScopeTests(unittest.TestCase):
    def setUp(self):
        self.plan = json.loads((HERE / 'run-plan.json').read_bytes())
        self.owner = json.loads((HERE / 'owner-request-and-scope.json').read_bytes())
        self.ci = dict(GITHUB_REPOSITORY=self.plan['repository'], GITHUB_REPOSITORY_ID=str(self.owner['repository_id']),
            GITHUB_REF='refs/heads/' + self.plan['branch'], GITHUB_SHA='a' * 40, GITHUB_EVENT_NAME='push',
            GITHUB_RUN_ID='123456', GITHUB_RUN_ATTEMPT='1', GITHUB_WORKSPACE=self.plan['workspace'],
            RUNNER_TEMP=self.plan['runner_temp'], RUNNER_OS='Linux', RUNNER_ENVIRONMENT='github-hosted')
        self.platform = dict(status='OBSERVED', ci=self.ci, uid=1001,
            uid_baseline={'uid': 1001, 'threads': 40}, production_qualified=False)

    def test_ci_rejects_reruns_and_context_drift(self):
        self.assertEqual(SUPPORT.validate_ci(self.plan, self.owner, self.ci), self.ci)
        for key, value in [('GITHUB_RUN_ATTEMPT', '2'), ('GITHUB_EVENT_NAME', 'workflow_dispatch'),
            ('GITHUB_REF', 'refs/heads/main'), ('GITHUB_SHA', 'not-a-commit'), ('GITHUB_RUN_ID', '0'),
            ('RUNNER_ENVIRONMENT', 'self-hosted'), ('GITHUB_REPOSITORY_ID', '1'), ('RUNNER_TEMP', '/tmp')]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                SUPPORT.validate_ci(self.plan, self.owner, {**self.ci, key: value})
        with self.assertRaises(ValueError):
            SUPPORT.validate_ci(self.plan, self.owner, {**self.ci, 'EXTRA': 'not-accepted'})

    def test_thread_budget_has_finite_ceiling(self):
        self.assertEqual(SUPPORT.nproc_budget(self.plan, {'uid': 1001, 'threads': 224}), 256)
        for baseline in ({'uid': 1001, 'threads': 225}, {'uid': 0, 'threads': 1},
                         {'uid': 1001, 'threads': True}, {'uid': 1001, 'threads': 0}):
            with self.subTest(baseline=baseline), self.assertRaises(ValueError):
                SUPPORT.nproc_budget(self.plan, baseline)

    def test_scope_replay_binds_observation_plan_and_owner(self):
        first = SUPPORT.derive_scope(self.plan, 'b' * 64, 'c' * 64, self.platform)
        self.assertEqual(first, SUPPORT.derive_scope(self.plan, 'b' * 64, 'c' * 64, copy.deepcopy(self.platform)))
        self.assertFalse(first['production_qualified'])
        self.assertFalse(first['scope_is_authority_token'])
        self.assertEqual(first['owner_request_sha256'], SUPPORT.OWNER_SHA)
        self.assertEqual(first['case_names'], self.owner['case_names'])
        changed = copy.deepcopy(self.platform)
        changed['ci']['GITHUB_RUN_ID'] = '234567'
        second = SUPPORT.derive_scope(self.plan, 'b' * 64, 'c' * 64, changed)
        self.assertNotEqual(first['platform_evidence_sha256'], second['platform_evidence_sha256'])
        for key in ('status', 'production_qualified'):
            invalid = {**self.platform, key: 'bad'}
            with self.assertRaises(ValueError):
                SUPPORT.derive_scope(self.plan, 'b' * 64, 'c' * 64, invalid)

    def test_closed_json_rejects_duplicate_and_noninteger_numbers(self):
        for raw in ('{"a":1,"a":2}', '{"a":NaN}', '{"a":1.0}'):
            with self.assertRaises(ValueError):
                SUPPORT.closed_json(raw)

    def test_package_and_source_inventory_preserved(self):
        binding = json.loads((HERE / 'binding.json').read_bytes())
        self.assertEqual(set(binding['package_files']), SUPPORT.PACKAGE_FILES)
        for name, expected in binding['package_files'].items():
            self.assertEqual(SUPPORT.digest((HERE / name).read_bytes()), expected, name)
        self.assertEqual(SUPPORT.digest((HERE / 'owner-request-and-scope.json').read_bytes())['sha256'], SUPPORT.OWNER_SHA)
        self.assertEqual(binding['candidate']['head'], self.owner['product_head'])
        self.assertEqual(binding['candidate']['tree'], self.owner['product_tree'])
        self.assertEqual(len(binding['candidate']['files']), 437)


class ProvisionTests(unittest.TestCase):
    def test_existing_or_symlinked_root_causes_zero_creation(self):
        for top, leaf in (('auto-g16-fixtures', 'bin'), ('user100', 'SDL')):
            for kind in ('file', 'directory', 'symlink'):
                with self.subTest(top=top, kind=kind), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp).resolve()
                    target = root / top
                    if kind == 'file':
                        target.write_text('retain')
                    elif kind == 'directory':
                        target.mkdir()
                    else:
                        target.symlink_to(root / 'absent')
                    fd = os.open(root, PROVISION.DF)
                    observations = []
                    try:
                        with self.assertRaisesRegex(ValueError, 'existing fixture root'):
                            PROVISION.create_pair(fd, str(root), top, leaf, os.getuid(), os.getgid(), observations)
                        self.assertEqual(list(root.iterdir()), [target])
                        self.assertEqual(observations[0]['before']['state'], 'EXISTS')
                        if kind == 'file':
                            self.assertEqual(target.read_text(), 'retain')
                    finally:
                        os.close(fd)

    def test_runner_creation_never_chowns_and_preserves_parent_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            root.chmod(0o777)
            fd = os.open(root, PROVISION.DF)
            observations = []
            try:
                with patch.object(PROVISION.os, 'fchown', side_effect=AssertionError('ordinary runner must not chown')):
                    PROVISION.create_pair(fd, '/opt', 'auto-g16-fixtures', 'bin', os.getuid(), os.getgid(), observations)
                self.assertEqual(len([x for x in observations if 'owned' in x]), 2)
                self.assertEqual(root.stat().st_mode & 0o777, 0o777)
                self.assertEqual((root / 'auto-g16-fixtures/bin').stat().st_mode & 0o777, 0o700)
            finally:
                os.close(fd)

    def test_actual_main_tool_loop_then_opt_creation_has_no_name_shadow(self):
        # Execute only the two actual main blocks implicated in this regression.
        # Private parent FDs and synthetic tool bytes; no Linux entry or sudo.
        tree = ast.parse((HERE / 'hosted_launcher.py').read_text())
        main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'main')
        parent_block = next(n for n in main.body if isinstance(n, ast.With))
        tool_loop = next(n for n in parent_block.body if isinstance(n, ast.For))
        opt_start = next(i for i, n in enumerate(parent_block.body) if isinstance(n, ast.Assign)
                         and isinstance(n.targets[0], ast.Name) and n.targets[0].id == 'opt_result')
        section = ast.Module(body=[tool_loop, *parent_block.body[opt_start:]], type_ignores=[])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / 'opt').mkdir()
            fds = {'/': os.open(root, PROVISION.DF), '/opt': os.open(root / 'opt', PROVISION.DF)}
            records = []
            class ToolPath:
                def resolve(self, strict=True):
                    return self
                def __str__(self):
                    return '/synthetic/tool'
            scope = dict(vars(LAUNCHER), python=ToolPath(), Path=lambda path: ToolPath(), tools={},
                parents=fds, record=lambda name, raw: records.append((name, raw)), read=lambda *args: b'synthetic tool')
            try:
                # A shared namespace models function-local binding across both
                # actual blocks: restoring the old `entry` loop name fails here.
                exec(compile(section, str(HERE / 'hosted_launcher.py'), 'exec'), scope, scope)
                self.assertEqual(scope['opt_result']['status'], 'PASS')
                self.assertEqual(set(scope['tools']), {'python', 'cc', 'timeout', 'bash', 'sudo'})
                self.assertEqual(records[0][0], 'runner-opt-provision.json')
                self.assertTrue((root / 'opt/auto-g16-fixtures/bin').is_dir())
            finally:
                for fd in reversed(list(fds.values())):
                    os.close(fd)

    def test_runner_denied_creation_has_no_privileged_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            fd = os.open(root, PROVISION.DF)
            observations = []
            try:
                with patch.object(PROVISION.os, 'mkdir', side_effect=PermissionError('denied')) as mkdir, \
                     patch.object(PROVISION.os, 'fchown', side_effect=AssertionError('no fallback')) as chown:
                    with self.assertRaises(PermissionError):
                        PROVISION.create_pair(fd, '/opt', 'auto-g16-fixtures', 'bin', os.getuid(), os.getgid(), observations)
                    mkdir.assert_called_once()
                    chown.assert_not_called()
                self.assertEqual(list(root.iterdir()), [])
                self.assertEqual(observations[0]['before'], {'state': 'ABSENT'})
            finally:
                os.close(fd)

    def test_invalid_new_top_is_retained_without_leaf_creation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            fd = os.open(root, PROVISION.DF)
            try:
                with self.assertRaisesRegex(ValueError, 'runner top directory identity'):
                    PROVISION.create_pair(fd, '/opt', 'auto-g16-fixtures', 'bin', os.getuid(), os.getgid() + 1, [])
                self.assertTrue((root / 'auto-g16-fixtures').is_dir())
                self.assertFalse((root / 'auto-g16-fixtures/bin').exists())
            finally:
                os.close(fd)

    def observe_temporary_parents(self, root):
        original_open = os.open
        def local_open(path, *args, **kwargs):
            return original_open(str(root) if path == '/' else path, *args, **kwargs)
        with ExitStack() as stack, patch.object(LAUNCHER.os, 'open', side_effect=local_open):
            _, observations = LAUNCHER.observe_parents(stack)
        return observations

    def test_open_failure_retains_exact_parent_and_target_observations(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / 'home').mkdir()
            (root / 'opt').symlink_to(root / 'home')
            result = self.observe_temporary_parents(root)
            self.assertEqual(result['errors'][0]['path'], '/opt')
            self.assertIn('open/fstat', result['errors'][0]['operation'])
            self.assertEqual(result['parents']['/opt']['entry']['state'], 'EXISTS')
            self.assertEqual(result['targets']['/home/user100'], {'state': 'ABSENT'})
            self.assertIn('node', result['parents']['/home'])
            with self.assertRaisesRegex(ValueError, 'parent observation failed'):
                LAUNCHER.validate_parents(result)

    def test_both_absences_and_home_trust_gate_precede_creation(self):
        # Values describe a private synthetic policy fixture, not a hosted VM.
        good = dict(errors=[], parents={
            '/': dict(root_owned=True, non_group_world_writable=True),
            '/opt': dict(root_owned=True, non_group_world_writable=False, named_identity_matches=True),
            '/home': dict(root_owned=True, non_group_world_writable=True, named_identity_matches=True)},
            targets={'/opt/auto-g16-fixtures': {'state': 'ABSENT'}, '/home/user100': {'state': 'ABSENT'}})
        LAUNCHER.validate_parents(good)
        for path in good['targets']:
            invalid = copy.deepcopy(good)
            invalid['targets'][path]['state'] = 'EXISTS'
            with self.assertRaisesRegex(ValueError, 'existing run target'):
                LAUNCHER.validate_parents(invalid)
        for predicate in ('root_owned', 'non_group_world_writable'):
            invalid = copy.deepcopy(good)
            invalid['parents']['/home'][predicate] = False
            with self.assertRaisesRegex(ValueError, 'untrusted system parent: /home'):
                LAUNCHER.validate_parents(invalid)


if __name__ == '__main__':
    unittest.main()
