"""ag command line, with optional T2/T5 subcommand registration."""
import argparse
from importlib import import_module
import json
import sys
from ag import __version__
from ag.config import load_config


CONFIG_COMMANDS = ('init', 'prepare', 'submit', 'status', 'fetch', 'cancel', 'list', 'doctor', 'monitor')


def core_command(args):
    from ag import attempt, cancel, doctor, fetch, status, study, submit
    from ag.transport import SSHTransport
    cfg = args.config
    command = args.command
    if command == 'monitor':
        from ag.monitor import run
        return run(cfg, args.watch)
    if command == 'init':
        result = study.init(cfg, args.directory)
    elif command == 'prepare':
        if len(args.parent) != len(args.relation):
            raise ValueError('Each --parent needs one --relation, in matching order')
        params = {}
        for item in args.param:
            key, _, value = item.partition('=')
            if key in params:
                raise ValueError('Duplicate template parameter')
            params[key] = value
        result = attempt.prepare(cfg, study_name=args.study, template=args.template,
                                 input_path=args.input, tier=args.tier, walltime=args.walltime,
                                 label=args.label, params=params, method_basis=args.method_basis,
                                 parents=[dict(attempt_id=p, relation=r) for p, r in zip(args.parent, args.relation)])
        if not args.json:
            print(attempt.summary(cfg, result))
            return 0
    elif command == 'list':
        result = attempt.all_attempts(cfg, args.study)
    else:
        transport = SSHTransport(cfg, read_only=command in ('doctor', 'status', 'fetch'))
        if command == 'doctor':
            result = doctor.doctor(cfg, transport)
        elif command == 'submit':
            result = submit.submit(cfg, args.ids, transport)
        elif command == 'status':
            if args.id and args.study:
                raise ValueError('Use an Attempt ID or --study, not both')
            ids = [args.id] if args.id else [a['attempt_id'] for a in attempt.all_attempts(cfg, args.study)]
            result = [dict(attempt_id=id_, **status.check(cfg, attempt.find(cfg, id_), transport)) for id_ in ids]
        elif command == 'fetch':
            result = fetch.fetch(cfg, attempt.find(cfg, args.id), transport)
        else:
            result = cancel.cancel(cfg, attempt.find(cfg, args.id), transport)
    if command == 'status' and not args.json:
        print(status.format_status(result))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    if command == 'status' and any(r['state'] == 'unknown' for r in result):
        return 3
    return 0


def register(subparsers):
    for name in CONFIG_COMMANDS:
        p = subparsers.add_parser(name)
        p.add_argument('--json', action='store_true')
        p.set_defaults(func=core_command)
        if name == 'init':
            p.add_argument('directory')
        elif name == 'monitor':
            from ag.monitor import watch_seconds
            p.add_argument('--watch', type=watch_seconds, metavar='SECONDS',
                           help='Sample in the foreground every 60–600 seconds; Ctrl-C exits')
        elif name == 'prepare':
            p.add_argument('--study', required=True)
            p.add_argument('--template', choices=('gaussian', 'xtb', 'crest'), required=True)
            p.add_argument('--input', required=True)
            p.add_argument('--tier', choices=('mini', 'simple', 'general', 'complex'), required=True)
            p.add_argument('--walltime', required=True)
            p.add_argument('--label', required=True)
            p.add_argument('--method-basis', default='兜底方法')
            p.add_argument('--parent', action='append', default=[])
            p.add_argument('--relation', action='append', default=[])
            p.add_argument('--param', action='append', default=[], help='Template option, e.g. --param=--gfn=2 or --param=--quick')
        elif name == 'submit':
            p.add_argument('ids', nargs='+')
        elif name in ('fetch', 'cancel'):
            p.add_argument('id')
        elif name in ('status', 'list'):
            p.add_argument('--study')
            if name == 'status':
                p.add_argument('id', nargs='?')


def main(argv=None):
    parser = argparse.ArgumentParser(prog='ag')
    parser.add_argument('--version', action='version', version=__version__)
    subparsers = parser.add_subparsers(dest='command')
    register(subparsers)
    for name in ('facts', 'thermo', 'dedup', 'cluster', 'graph'):
        module_name = f'ag.{name}'
        try:
            module = import_module(module_name)
        except ModuleNotFoundError as exc:
            if exc.name != module_name:
                raise
            continue
        module.register(subparsers)
    args = parser.parse_args(argv)
    if not hasattr(args, 'func'):
        parser.print_help()
        return 0
    from ag.submit import UnknownSubmission
    try:
        if args.command in CONFIG_COMMANDS:
            args.config = load_config()
        return args.func(args)
    except UnknownSubmission as exc:
        code = 3
        message = str(exc)
    except (ValueError, FileExistsError) as exc:
        code = 1
        message = str(exc)
    except (OSError, KeyError) as exc:
        code = 2
        message = str(exc)
    if getattr(args, 'json', False):
        print(json.dumps({'error': message, 'exit_code': code}, ensure_ascii=False))
    else:
        print(message, file=sys.stderr)
    return code


if __name__ == '__main__':
    raise SystemExit(main())
