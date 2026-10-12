"""Explicitly qualified read-only parser pairs; no prefix/version guessing."""
PARSER_PAIRS = frozenset({('auto-g16-v3-gaussian-job', '1.1.0'), ('autog-local-gaussian-job', '1.0.0')})
def qualified_parser(name, version):
    return (name, version) in PARSER_PAIRS
