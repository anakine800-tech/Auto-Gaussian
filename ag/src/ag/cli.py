"""ag command line, with optional T2/T5 subcommand registration."""
import argparse
from importlib import import_module
import json
import sys
from ag import __version__
from ag.config import load_config, select_cluster, for_manifest


CONFIG_COMMANDS = ('init', 'prepare', 'submit', 'status', 'fetch', 'cancel', 'list', 'doctor', 'monitor', 'review', 'clusters')


def core_command(args):
    from ag import attempt, cancel, doctor, fetch, status, study, submit
    from ag.transport import SSHTransport
    cfg = args.config
    command = args.command
    if command == 'monitor':
        from ag.monitor import run
        return run(cfg, args.watch)
    if command == 'review':
        from ag import review
        result = review.run(cfg, args.action, args.id, card=getattr(args, 'card', None))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return int(args.action == 'check' and (not result['complete'] or result['stale']))
    if command == 'clusters':
        from ag.clusters import describe
        result = describe(cfg, verify_studies_root=args.verify_studies_root)
    elif command == 'init':
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
                                 constraints=args.constraints, cluster=args.cluster, card=args.card,
                                 parent_chk=args.parent_chk,
                                 parents=[dict(attempt_id=p, relation=r) for p, r in zip(args.parent, args.relation)])
        if not args.json:
            print(attempt.summary(cfg, result))
            return 0
    elif command == 'list':
        result = attempt.all_attempts(cfg, args.study)
    else:
        # Select from immutable Attempt identity before constructing SSH options.
        if command == 'doctor':
            cfg = select_cluster(cfg, getattr(args, 'cluster', 'default'))
        elif command in ('fetch', 'cancel'):
            cfg = for_manifest(cfg, attempt.read_manifest(attempt.find(cfg, args.id)))
        elif command == 'submit':
            names = {attempt.read_manifest(attempt.find(cfg, id_)).get('cluster', 'default') for id_ in args.ids}
            if len(names) != 1:
                raise ValueError('Submit one cluster per confirmed batch')
            cfg = for_manifest(cfg, attempt.read_manifest(attempt.find(cfg, args.ids[0])))
        transport = None if command == 'status' else SSHTransport(cfg, read_only=command in ('doctor', 'fetch'))
        if command == 'doctor':
            result = doctor.doctor(cfg, transport)
        elif command == 'submit':
            result = submit.submit(cfg, args.ids, transport)
        elif command == 'status':
            if args.id and args.study:
                raise ValueError('Use an Attempt ID or --study, not both')
            ids = [args.id] if args.id else [a['attempt_id'] for a in attempt.all_attempts(cfg, args.study)]
            result = []
            for id_ in ids:
                path = attempt.find(cfg, id_)
                selected = for_manifest(cfg, attempt.read_manifest(path))
                transport = SSHTransport(selected, read_only=True)
                result.append(dict(attempt_id=id_, **status.check(selected, path, transport)))
        elif command == 'fetch':
            result = fetch.fetch(cfg, attempt.find(cfg, args.id), transport)
        else:
            result = cancel.cancel(cfg, attempt.find(cfg, args.id), transport)
    if command == 'status' and not args.json:
        print(status.format_status(result))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    if command == 'doctor' and result.get('ok') is False:
        return 2
    if command == 'status' and any(r['state'] == 'unknown' for r in result):
        return 3
    return 0


def register(subparsers):
    for name in CONFIG_COMMANDS:
        p = subparsers.add_parser(name)
        p.add_argument('--json', action='store_true')
        p.set_defaults(func=core_command)
        if name in ('prepare', 'doctor'):
            p.add_argument('--cluster', default='default')
        if name == 'init':
            p.add_argument('directory')
        elif name == 'clusters':
            p.add_argument('--verify-studies-root', metavar='PATH',
                           help='Compare resolved study roots; return only a boolean, never paths')
        elif name == 'review':
            actions = p.add_subparsers(dest='action', required=True)
            for action in ('init', 'check'):
                child = actions.add_parser(action)
                child.add_argument('id')
                if action == 'init':
                    child.add_argument('--card', help='Recipe for legacy manifests without a recorded card')
                child.add_argument('--json', action='store_true', default=argparse.SUPPRESS)
            from ag._review_manifest import run as review_manifest
            child = actions.add_parser('manifest', help='Freeze a signature evidence inventory')
            child.add_argument('--study', required=True, help='Local study directory')
            child.add_argument('--json', action='store_true', default=argparse.SUPPRESS)
            child.set_defaults(func=review_manifest)
        elif name == 'monitor':
            from ag.monitor import watch_seconds
            p.add_argument('--watch', type=watch_seconds, metavar='SECONDS',
                           help='Sample in the foreground every 60–600 seconds; Ctrl-C exits')
        elif name == 'prepare':
            p.add_argument('--study', required=True)
            p.add_argument('--template', choices=('gaussian', 'xtb', 'crest'), required=True)
            p.add_argument('--input', required=True)
            p.add_argument('--card', help='Recipe name; capture its text, Skills Git commit and dirty state')
            p.add_argument('--constraints', help='xTB/CREST xcontrol file, bundled as constraints.inp')
            p.add_argument('--tier', choices=('mini', 'simple', 'general', 'complex'), required=True)
            p.add_argument('--walltime', required=True)
            p.add_argument('--label', required=True)
            p.add_argument('--method-basis', default='兜底方法')
            p.add_argument('--parent', action='append', default=[])
            p.add_argument('--parent-chk', help='Completed parent Attempt ID:checkpoint filename')
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
    for name in ('facts', 'thermo', 'dedup', 'cluster', 'graph', 'irc_compare', 'profile', 'coverage', 'scan_peak'):
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
        if args.command in CONFIG_COMMANDS and not (args.command == 'review' and args.action == 'manifest'):
            args.config = load_config(local_only=True) if args.command == 'review' else load_config()
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
    if args.command == 'clusters':
        # This discovery endpoint must not leak paths or config values through
        # exception text, even when loading the configuration itself fails.
        message = 'Cannot read local cluster configuration or budget; check local files'
    if getattr(args, 'json', False):
        print(json.dumps({'error': message, 'exit_code': code}, ensure_ascii=False))
    else:
        print(message, file=sys.stderr)
    return code


if __name__ == '__main__':
    raise SystemExit(main())
