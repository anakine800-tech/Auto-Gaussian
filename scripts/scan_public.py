#!/usr/bin/env python3
"""Scan Git-tracked files (or staged blobs); never print matched values.

No project-specific sensitive terms belong here. Archive findings are warnings
pending T116 P4 authorization. Local terms always fail, including in archive/.
"""
from __future__ import annotations

import argparse
import ipaddress
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import unittest


IPV4 = re.compile(r'(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])')
IPV6 = re.compile(r'(?<![\w:])[\da-fA-F:.]*:[\da-fA-F:.]*:[\da-fA-F:.]*(?:%[\w.-]+)?(?![\w:])')
EMAIL = re.compile(r'(?<![\w.+-])[A-Za-z0-9_][\w.!#$%&*+/=?^`{|}~-]*@(?:[\w-]+\.)+[A-Za-z]{2,}(?![\w.-])')
PATTERNS = {
    'user-directory': re.compile(r'/(?:Users|home)/[^/\s<>"\x27`]+/'),
    'windows-user-directory': re.compile(r'[A-Za-z]:\\+Users\\+[^\\/\s<>"\x27`]+[\\/]', re.I),
    'private-key': re.compile(r'-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----'),
    'token': re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-(?:proj-|ant-)?[A-Za-z0-9_-]{20,}|xox[baprs]-[A-Za-z0-9-]{10,}|AKIA[A-Z0-9]{16})(?![A-Za-z0-9_])'),
}
ALLOW = re.compile(r'# scan-public: allow\b(.*)')
DOCUMENTATION = tuple(ipaddress.ip_network(n) for n in (
    '192.0.2.0/24', '198.51.100.0/24', '203.0.113.0/24', '2001:db8::/32', '3fff::/20'))


def exempt_ip(value):
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return True  # Versions and malformed addresses are not IP addresses.
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    return address.is_loopback or address.is_unspecified or any(
        address.version == network.version and address in network for network in DOCUMENTATION)


def generic_findings(line, *, python_source=False):
    allow = ALLOW.search(line)
    if allow:
        # Markdown/JS comment delimiters alone do not constitute a reason.
        reason = allow.group(1).strip(' \t`<>!*/-')
        if re.search(r'\w', reason):
            return []
        return ['allow-without-reason']
    labels = [label for label, pattern in PATTERNS.items() if pattern.search(line)]
    for label, pattern in (('ipv4', IPV4), ('ipv6', IPV6)):
        if any(not exempt_ip(m.group()) and not (
                python_source and label == 'ipv6'
                and re.fullmatch(r'\d*::\d*', m.group())
                and re.search(r'\w+\[$', line[:m.start()])
                and line[m.end():].startswith(']')) for m in pattern.finditer(line)):
            labels.append(label)
    for match in EMAIL.finditer(line):
        local, domain = match.group().lower().split('@', 1)
        if local not in {'noreply', 'no-reply'} and 'noreply' not in domain.split('.'):
            labels.append('email')
            break
    return labels


def git(*args):
    return subprocess.check_output(['git', *args], stderr=subprocess.PIPE)


def blobs(staged):
    if staged:
        paths = git('diff', '--cached', '--name-only', '-z', '--diff-filter=ACMRT', '--').split(b'\0')
        for raw in filter(None, paths):
            path = os.fsdecode(raw)
            yield path, git('show', ':' + path)
    else:
        # Includes every tracked file, even ignored files already in Git.
        for raw in filter(None, git('ls-files', '-z').split(b'\0')):
            path = os.fsdecode(raw)
            target = Path(path)
            try:
                mode = target.lstat().st_mode
            except FileNotFoundError:
                continue  # An unstaged deletion has no current bytes to scan.
            if stat.S_ISLNK(mode):
                yield path, os.fsencode(os.readlink(target))
            elif stat.S_ISREG(mode):
                yield path, target.read_bytes()
            else:
                raise ValueError('unsupported tracked file type')


def load_terms(path):
    if path is None:
        return []
    try:
        lines = path.read_text(encoding='utf-8').splitlines()
    except FileNotFoundError:
        print('Local sensitive-term list missing; skipped (generic scan still required).')
        return []
    terms = []
    for number, line in enumerate(lines, 1):
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        try:
            terms.append(re.compile(line))
        except re.error:
            raise ValueError(f'invalid local regex at list line {number}') from None
    return terms


def scan(staged=False, terms_file=None):
    root = git('rev-parse', '--show-toplevel').decode().strip()
    os.chdir(root)
    # Read the selected Git bytes once: unstaged edits cannot hide staged data.
    files = list(blobs(staged))
    failures = warnings = binary = 0
    text_files = []
    for path, data in files:
        if b'\0' in data:
            binary += 1
            continue
        try:
            data.decode('utf-8')
        except UnicodeDecodeError:
            binary += 1
            continue
        text_files.append((path, data))
    for path, data in text_files:
        for number, line in enumerate(data.decode('utf-8', errors='replace').splitlines(), 1):
            for category in generic_findings(line, python_source=path.endswith('.py')):
                warning = path.startswith('archive/')
                warnings += int(warning)
                failures += int(not warning)
                print(f'{"WARN" if warning else "ERROR"} {path}:{number}: {category}')
    # A generic allow annotation cannot suppress private local terms.
    terms = load_terms(terms_file)
    if terms:
        for path, data in text_files:
            for number, line in enumerate(data.decode('utf-8', errors='replace').splitlines(), 1):
                if any(term.search(line) for term in terms):
                    failures += 1
                    print(f'ERROR {path}:{number}: local-sensitive-term')
    print(f'Public scan: {len(files)} files, {failures} errors, {warnings} archive warnings, {binary} binary files skipped.')
    return int(bool(failures))


class ScannerTests(unittest.TestCase):
    def test_patterns(self):
        samples = {
            'ipv4': '10.' + '23.45.67',
            'ipv6': 'fd42:' + '1234::5',  # scan-public: allow synthetic scanner positive example
            'user-directory': '/' + 'Users/synthetic/file',
            'windows-user-directory': 'C:' + '\\Users\\synthetic\\file',
            'email': 'synthetic' + '@example.com',
            'private-key': '-----BEGIN ' + 'RSA PRIVATE KEY-----',
            'token': 'ghp_' + 'a' * 36,
        }
        for category, sample in samples.items():
            with self.subTest(category=category):
                self.assertIn(category, generic_findings(sample))
                self.assertEqual([], generic_findings(sample + ' # scan-public:' + ' allow synthetic test'))
        for sample in ('/' + 'home/synthetic/file', 'C:' + '\\\\Users\\\\synthetic\\\\file'):
            self.assertTrue(generic_findings(sample))
        for prefix in ('github_pat_', 'sk-proj-', 'sk-ant-', 'xoxb-', 'AKIA'):
            self.assertIn('token', generic_findings(prefix + 'A' * (16 if prefix == 'AKIA' else 40)))

    def test_addresses_and_exemptions(self):
        for address in ('127.0.0.1', '0.0.0.0', '192.0.2.1', '198.51.100.3', '203.0.113.8',
                        '::1', '::', '2001:db8::7', '3fff::1', '::ffff:192.0.2.1'):
            self.assertEqual([], generic_findings(address), address)
        for address in ('fd42:' + ':1', 'fe80:' + ':123%eth0', '::ffff:' + '10.23.45.67',  # scan-public: allow synthetic scanner positive example
                        'fd42:' + '1:2:3:4:5:6:7'):
            self.assertIn('ipv6', generic_findings('https://[' + address + ']:443/'))
        for address in ('user@users.noreply.github.com', 'noreply@example.com', 'no-reply@example.com'):
            self.assertEqual([], generic_findings(address))
        for suffix in ('', '   ', ' -->', ' */'):
            self.assertEqual(['allow-without-reason'], generic_findings('# scan-public:' + ' allow' + suffix))

    def test_syntax_false_positives(self):
        self.assertEqual([], generic_findings("'@parent.gjf'"))
        self.assertEqual([], generic_findings('items[1::2]', python_source=True))
        self.assertIn('ipv6', generic_findings("host='1::2'", python_source=True))  # scan-public: allow synthetic scanner positive example

    def test_scanner_source_is_clean(self):
        for number, line in enumerate(Path(__file__).read_text().splitlines(), 1):
            self.assertEqual([], generic_findings(line, python_source=True), number)

    def test_git_and_hook(self):
        script = str(Path(__file__).resolve())
        with tempfile.TemporaryDirectory(prefix='public-scan-') as directory:
            root = Path(directory)
            def run(*args, **kwargs):
                return subprocess.run(args, cwd=root, text=True, capture_output=True, **kwargs)
            def scan_cli(*args):
                return run(sys.executable, script, *args)
            self.assertEqual(run('git', 'init', '-q').returncode, 0)
            run('git', 'config', 'user.name', 'Synthetic')
            run('git', 'config', 'user.email', 'noreply@example.com')
            (root / 'data.txt').write_text('safe\n')
            run('git', 'add', 'data.txt')
            self.assertEqual(scan_cli('--staged').returncode, 0)
            run('git', 'commit', '-qm', 'synthetic baseline')
            secret = '10.' + '23.45.67'
            (root / 'data.txt').write_text(secret + '\n')
            run('git', 'add', 'data.txt')
            (root / 'data.txt').write_text('unstaged safe\n')
            result = scan_cli('--staged')
            self.assertEqual(result.returncode, 1)
            self.assertNotIn(secret, result.stdout)
            self.assertEqual(scan_cli().returncode, 0)
            run('git', 'add', 'data.txt')
            (root / 'archive').mkdir()
            (root / 'archive/data.txt').write_text(secret)
            run('git', 'add', 'archive/data.txt')
            self.assertEqual(scan_cli('--staged').returncode, 0)
            self.assertIn('WARN archive/', scan_cli().stdout)
            run('git', 'mv', 'data.txt', 'renamed.txt')
            terms = root / 'private-list'
            terms.write_text('unstaged.*safe\n')
            result = scan_cli('--staged', '--terms-file', str(terms))
            self.assertEqual(result.returncode, 1)
            self.assertNotIn('unstaged', result.stdout)
            terms.write_bytes(b'private-invalid-byte-' + bytes([255]))
            invalid = scan_cli('--staged', '--terms-file', str(terms))
            self.assertEqual(invalid.returncode, 2)
            self.assertNotIn('private-invalid-byte', invalid.stderr)
            terms.write_text('[')
            self.assertEqual(scan_cli('--staged', '--terms-file', str(terms)).returncode, 2)
            # Exercise a real commit through the shipped hook when available.
            hook_source = Path(script).parent.parent / '.githooks/pre-commit'
            if hook_source.is_file():
                (root / 'scripts').mkdir()
                (root / 'scripts/scan_public.py').write_bytes(Path(script).read_bytes())
                hook = root / '.git/hooks/pre-commit'
                hook.write_bytes(hook_source.read_bytes())
                hook.chmod(0o755)
                env = dict(os.environ, SCAN_PUBLIC_TERMS_FILE=str(terms))
                terms.write_text('unstaged.*safe\n')
                self.assertNotEqual(run('git', 'commit', '-qm', 'must reject', env=env).returncode, 0)
                terms.write_text('never-matches-synthetic\n')
                self.assertEqual(run('git', 'commit', '-qm', 'safe commit', env=env).returncode, 0)
                (root / 'renamed.txt').write_text('next safe\n')
                run('git', 'add', 'renamed.txt')
                terms.unlink()
                result = run('git', 'commit', '-qm', 'missing optional terms', env=env)
                self.assertEqual(result.returncode, 0)
                self.assertIn('list missing', result.stdout + result.stderr)
            run('git', 'rm', '-q', 'renamed.txt')
            self.assertEqual(scan_cli('--staged').returncode, 0)
            missing = scan_cli('--staged', '--terms-file', str(root / 'absent'))
            self.assertEqual(missing.returncode, 0)
            self.assertIn('list missing', missing.stdout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--staged', action='store_true', help='scan added/modified staged blobs')
    parser.add_argument('--terms-file', type=Path, help='optional private newline-separated regex list')
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    if args.self_test:
        result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ScannerTests))
        return int(not result.wasSuccessful())
    try:
        return scan(args.staged, args.terms_file)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        # Never expose Git stderr, matched text, private paths, or regex content.
        detail = str(error) if type(error) is ValueError else type(error).__name__
        print(f'Public scan failed: {detail}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
