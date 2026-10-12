"""Fixed direct-backend command surface, no live execution handlers."""
import argparse
import sys

from ._model import StudyError, encode
from .service import operate


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise StudyError('invalid-request')


def main(argv=None):
    parser = _Parser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('create', 'review', 'status', 'query', 'audit', 'recover', 'run'):
        command = commands.add_parser(name)
        command.add_argument('--directory', required=True)
        if name == 'create':
            command.add_argument('--request', required=True)
            command.add_argument('--sha256', required=True)
    try:
        args = parser.parse_args(argv)
        result = operate(args.command, args.directory, request_path=getattr(args, 'request', None),
                         request_sha256=getattr(args, 'sha256', None))
    except FileNotFoundError:
        print(encode(dict(schema='auto-g16-direct-study-error/1', error='not-found')).decode())
        return 2
    except Exception as exc:
        code = str(exc) if type(exc) is StudyError else 'invalid-evidence'
        result = dict(schema='auto-g16-direct-study-error/1', error=code)
        print(encode(result).decode())
        return 2
    print(encode(result).decode())
    return 0


if __name__ == '__main__':
    sys.exit(main())
