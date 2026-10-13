"""Redact machine identifiers in small-molecule logs before manual publication review.

This cannot decide whether a molecule or free-text title is unpublished research.
Only feed independently verified non-research examples to this tool.
"""

import argparse
from pathlib import Path
import re
import textwrap


def sanitize_log(text, identifiers=()):
    """Preserve numerical data while replacing paths, hosts, users and PIDs."""
    secrets = set(identifiers)

    def archive(match):
        block = ''.join(line.strip() for line in match.group().splitlines())
        fields = block.split('\\')
        if len(fields) > 7:
            secrets.update((fields[2][5:], fields[7]))
            fields[2] = 'GINC-HOST'
            fields[7] = 'USER'
        return '\n'.join(' ' + line for line in textwrap.wrap(
            '\\'.join(fields), width=70, break_on_hyphens=False,
            replace_whitespace=False, drop_whitespace=False))

    text = re.sub(r'(?m)^\s*1\\1\\GINC-[\s\S]*?\\@', archive, text)
    # Keep executable basenames: error-link recognition needs lNNN.exe.
    def path(match):
        name = re.split(r'[/\\]', match.group().rstrip('/\\'))[-1]
        return 'PATH/' + (name if re.fullmatch(r'l\d+\.exe', name) else 'FILE')

    text = re.sub(r'(?<![\w])(?:[A-Za-z]:[\\/]|/)[A-Za-z_.][^\s"\'<>),;]*', path, text)
    text = re.sub(r'(?i)\b(PID\s*[=:]?\s*)\d+', r'\g<1>0', text)
    text = re.sub(r'(?i)\bGau-\d+', 'Gau-PID', text)
    text = re.sub(r'(?i)\b(host(?:name)?|user(?:name)?)\s*[=:]\s*[\w.@-]+',
                  lambda m: m.group(1) + '=REDACTED', text)
    for secret in sorted(filter(None, secrets), key=len, reverse=True):
        if secret not in {'HOST', 'USER'}:
            text = re.sub(r'(?<![\w])' + re.escape(secret) + r'(?![\w])',
                          'REDACTED', text, flags=re.I)
    return "\n".join(line.rstrip() for line in text.splitlines()) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('destination', type=Path)
    parser.add_argument('--redact', action='append', default=[], help='additional known identifier')
    args = parser.parse_args(argv)
    cleaned = sanitize_log(args.source.read_text(), args.redact)
    with args.destination.open('x') as stream:
        stream.write(cleaned)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
