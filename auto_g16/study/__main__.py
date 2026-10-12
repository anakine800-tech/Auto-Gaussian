"""Fixed direct-backend commands with exact native preparation authority."""
import argparse
import sys

from ._model import StudyError, encode, require
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
        if name == 'review':
            command.add_argument('--stage')
        if name == 'run':
            command.add_argument('--initialize-local', action='store_true')
            command.add_argument('--stage')
            command.add_argument('--action')
    command = commands.add_parser('install-local')
    command.add_argument('--request', required=True)
    command.add_argument('--sha256', required=True)
    for name in ('authorize-preparation', 'authorize'):
        command = commands.add_parser(name)
        command.add_argument('--directory', required=True)
        command.add_argument('--stage', required=True)
        command.add_argument('--request', required=True)
        command.add_argument('--sha256', required=True)
    try:
        args = parser.parse_args(argv)
        if args.command == 'install-local':
            from ._local_install import publish_local
            result = publish_local(args.request, args.sha256)
        elif args.command == 'run' and args.initialize_local:
            require(args.stage is None and args.action is None, 'invalid-request')
            from ._local_install import initialize_installed
            result = initialize_installed(args.directory)
            # Registration has a separate loader/lock lifetime after initialization.
            from ._registered_runtime import register_local
            register_local(args.directory)
        elif args.command == 'run' and (args.stage is not None or args.action is not None):
            require(args.stage == 'xtb', 'stage-not-supported')
            require(args.action == 'prepare', 'invalid-request')
            from ._xtb_service import prepare
            result = prepare(args.directory)
        elif args.command == 'review' and args.stage is not None:
            require(args.stage == 'xtb', 'stage-not-supported')
            from ._xtb_service import review
            result = review(args.directory)
        elif args.command == 'authorize-preparation':
            require(args.stage == 'xtb', 'stage-not-supported')
            from ._xtb_capture import preparation
            from ._xtb_service import authorize_preparation
            with preparation(args.request, args.sha256) as captured:
                result = authorize_preparation(args.directory, captured)
        elif args.command == 'authorize':
            require(args.stage == 'xtb', 'stage-not-supported')
            from ._xtb_capture import authorization
            from ._xtb_service import authorize
            with authorization(args.request, args.sha256) as captured:
                result = authorize(args.directory, captured)
        else:
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
