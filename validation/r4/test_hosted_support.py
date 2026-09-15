"""Offline rejection tests only: no product imports, sudo, C build or Linux run."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

HERE = Path(__file__).resolve().parent


def load(name):
    spec = importlib.util.spec_from_file_location(name, HERE / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SUPPORT = load('hosted_support')
PROVISION = load('provision_fixture_roots')


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
    def test_existing_or_symlinked_either_root_causes_zero_creation(self):
        for index in (0, 1):
            for kind in ('file', 'directory', 'symlink'):
                with self.subTest(index=index, kind=kind), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp).resolve()
                    parents = [root / 'opt', root / 'home']
                    for path in parents:
                        path.mkdir()
                    target = parents[index] / ('auto-g16-fixtures', 'user100')[index]
                    if kind == 'file':
                        target.write_text('retain')
                    elif kind == 'directory':
                        target.mkdir()
                    else:
                        target.symlink_to(root / 'absent')
                    descriptors = [os.open(path, PROVISION.DF) for path in parents]
                    try:
                        with self.assertRaises(FileExistsError):
                            PROVISION.create_roots(*descriptors, os.getuid(), os.getgid(), [])
                        self.assertEqual(list(parents[1-index].iterdir()), [])
                        self.assertTrue(os.path.lexists(target))
                        if kind == 'file':
                            self.assertEqual(target.read_text(), 'retain')
                    finally:
                        for fd in descriptors:
                            os.close(fd)

    def test_new_roots_are_exact_and_recorded_by_descriptor(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            parents = [root / 'opt', root / 'home']
            for path in parents:
                path.mkdir()
            descriptors = [os.open(path, PROVISION.DF) for path in parents]
            observations = []
            try:
                PROVISION.create_roots(*descriptors, os.getuid(), os.getgid(), observations)
                self.assertEqual(len([x for x in observations if 'owned' in x]), 4)
                self.assertEqual(sorted(str(x.relative_to(root)) for x in root.rglob('*')), [
                    'home', 'home/user100', 'home/user100/SDL', 'opt', 'opt/auto-g16-fixtures', 'opt/auto-g16-fixtures/bin'])
                for path in (parents[0] / 'auto-g16-fixtures/bin', parents[1] / 'user100/SDL'):
                    self.assertEqual(path.stat().st_mode & 0o777, 0o700)
            finally:
                for fd in descriptors:
                    os.close(fd)


if __name__ == '__main__':
    unittest.main()
