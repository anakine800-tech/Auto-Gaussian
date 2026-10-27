"""ag command line, with optional T2/T5 subcommand registration."""
import argparse
from importlib import import_module
import json
import sys
from ag import __version__
from ag.config import load_config, select_cluster, for_manifest, RESOURCE_TIERS


CONFIG_COMMANDS = ('init', 'prepare', 'approve', 'submit', 'status', 'fetch', 'snapshot', 'cancel', 'list', 'doctor', 'monitor', 'review', 'clusters', 'nodes')


def core_command(args):
    from ag import approval, attempt, cancel, doctor, fetch, snapshot, status, study, submit
    from ag.transport import SSHTransport
    cfg = args.config
    command = args.command
    if command == 'monitor':
        from ag.monitor import run, retry
        if args.retry is not None:
            return retry(cfg, args.retry, auth_fixed=args.auth_fixed, json_output=args.json, track=args.track)
        if args.auth_fixed:
            raise ValueError('--auth-fixed requires --retry')
        return run(cfg, args.watch, json_output=args.json)
    if command == 'review':
        from ag import review
        result = review.run(cfg, args.action, args.id, card=getattr(args, 'card', None))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return int(args.action == 'check' and (not result['complete'] or result['stale']))
    if command == 'clusters':
        from ag.clusters import describe
        result = describe(cfg, verify_studies_root=args.verify_studies_root)
    elif command == 'nodes':
        from ag.node_targeting import candidates
        result = candidates(cfg, args.cluster)
    elif command == 'init':
        result = study.init(cfg, args.directory)
    elif command == 'approve':
        result = approval.create(cfg, args.study, args.attempt, args.quote, args.hours)
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
                                 target_node=args.target_node, node_fraction=args.node_fraction,
                                 parent_chk=args.parent_chk, analysis=args.analysis, grid=args.grid, fragments=args.fragments,
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
        elif command == 'snapshot':
            path = snapshot.find(cfg, args.id, args.study)
            cfg = for_manifest(cfg, attempt.read_manifest(path))
        elif command in ('fetch', 'cancel'):
            cfg = for_manifest(cfg, attempt.read_manifest(attempt.find(cfg, args.id)))
        elif command == 'submit':
            cfg = submit.preflight(cfg, args.ids)
        transport = None if command == 'status' else SSHTransport(cfg, read_only=command in ('doctor', 'fetch', 'snapshot'))
        if command == 'doctor':
            result = doctor.doctor(cfg, transport)
            result['approval_policies'] = cfg.get('approval', {}).get('policies', {})
        elif command == 'submit':
            result = submit.submit(cfg, args.ids, transport, approval_id=args.approval, policy_name=args.policy)
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
        elif command == 'snapshot':
            result = snapshot.capture(cfg, path, transport, max_bytes=args.max_bytes)
        elif command == 'fetch':
            path = attempt.find(cfg, args.id)
            result = fetch.fetch(cfg, path, transport,
                                 add_missing=args.add_missing, incomplete=getattr(args, 'incomplete', False))
            skip = ('add-missing' if args.add_missing else
                    'no-facts' if getattr(args, 'no_facts', False) else None)
            result['facts'] = fetch.auto_facts(path, skip=skip)
        else:
            result = cancel.cancel(cfg, attempt.find(cfg, args.id), transport)
    if command == 'status' and not args.json:
        print(status.format_status(result))
    elif command == 'snapshot' and not args.json:
        print(snapshot.format_snapshot(result))
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
        if name in ('prepare', 'doctor', 'nodes'):
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
            child.add_argument('directory', nargs='?', help='Local study directory')
            child.add_argument('--study', help='Local study directory (alternative to positional)')
            child.add_argument('--accept-unresolved', action='store_true',
                               help='Confirm the listed unresolved references before writing')
            child.add_argument('--json', action='store_true', default=argparse.SUPPRESS)
            child.set_defaults(func=review_manifest)
        elif name == 'monitor':
            from ag.monitor import watch_seconds
            mode = p.add_mutually_exclusive_group()
            mode.add_argument('--watch', type=watch_seconds, metavar='SECONDS',
                              help='Sample in the foreground every 30–600 seconds; Ctrl-C exits')
            mode.add_argument('--retry', metavar='ENTRY', help='Queue one local monitor retry')
            p.add_argument('--track', action='store_true',
                           help='Return a retry identity (requires --retry and --json)')
            p.add_argument('--auth-fixed', action='store_true',
                           help='Confirm authentication or host-key configuration has been repaired')
        elif name == 'prepare':
            p.add_argument('--study', required=True)
            p.add_argument('--template', choices=('gaussian', 'gaussian-cp', 'xtb', 'crest', 'multiwfn'), required=True)
            p.add_argument('--input', help='Program input; omit for Multiwfn IGMH')
            p.add_argument('--analysis', choices=('igm', 'igmh'))
            p.add_argument('--grid', choices=('low', 'medium', 'high'))
            p.add_argument('--fragments', help='Multiwfn: fragment,atoms (2–4); gaussian-cp: fragment,atoms,charge,multiplicity (exactly 2)')
            p.add_argument('--card', help='Recipe name; capture its text, Skills Git commit and dirty state')
            p.add_argument('--constraints', help='xTB/CREST xcontrol file, bundled as constraints.inp')
            p.add_argument('--target-node', help='Explicit PBS node; no automatic selection')
            p.add_argument('--node-fraction', choices=('1/2', '1/4'))
            p.add_argument('--tier', choices=RESOURCE_TIERS, required=True)
            p.add_argument('--walltime', required=True)
            p.add_argument('--label', required=True)
            p.add_argument('--method-basis', required=True,
                           metavar='文献先例/本课题既有方案/兜底方法',
                           help='文献先例：DOI 及位置；本课题既有方案：来源，且声明不是文献先例、精度未经验证；兜底方法：明确声明')
            p.add_argument('--parent', action='append', default=[])
            p.add_argument('--parent-chk', help='Completed parent Attempt ID:checkpoint filename')
            p.add_argument('--relation', action='append', default=[])
            p.add_argument('--param', action='append', default=[], help='Template option, e.g. --param=--gfn=2 or --param=--quick')
        elif name == 'approve':
            p.add_argument('--study', required=True)
            p.add_argument('--attempt', action='append', required=True)
            p.add_argument('--quote', required=True, help='Verbatim explicit approval from the human in this study conversation')
            p.add_argument('--hours', type=float, default=24, help='Validity in hours, positive and at most 24')
        elif name == 'submit':
            p.add_argument('ids', nargs='+')
            authorization = p.add_mutually_exclusive_group()
            authorization.add_argument('--approval', help='Single-use approval ID in the same study')
            authorization.add_argument('--policy', help='Explicit machine-local approval policy name')
        elif name == 'snapshot':
            from ag.snapshot import DEFAULT_MAX_BYTES
            p.add_argument('id')
            p.add_argument('--study')
            p.add_argument('--max-bytes', type=int, default=DEFAULT_MAX_BYTES,
                           help='Copy at most this many trailing log bytes (default: 20000000)')
        elif name in ('fetch', 'cancel'):
            p.add_argument('id')
            if name == 'fetch':
                p.add_argument('--no-facts', action='store_true',
                               help='Skip automatic local facts parsing after successful fetch')
                mode = p.add_mutually_exclusive_group()
                mode.add_argument('--add-missing', action='store_true',
                               help='Verify existing outputs and collect only missing files for a fetched Attempt')
                mode.add_argument('--incomplete', action='store_true',
                                  help='Read-only fetch of available outputs after verified job termination')
        elif name in ('status', 'list'):
            p.add_argument('--study')
            if name == 'status':
                p.add_argument('id', nargs='?')


def main(argv=None):
    parser = argparse.ArgumentParser(prog='ag')
    parser.add_argument('--version', action='version', version=__version__)
    subparsers = parser.add_subparsers(dest='command')
    register(subparsers)
    from ag.route import register as register_route
    register_route(subparsers)
    for name in ('facts', 'thermo', 'dedup', 'cluster', 'graph', 'irc_compare', 'profile', 'coverage', 'scan_peak', 'qst_endpoints', 'topology', 'mode_review', 'fragments', 'ensemble', 'channel_coverage', 'asm', 'irc_review', 'nci_report', 'cp_report', 'catalog', 'g0'):
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
        if args.command == 'monitor' and args.track and (args.retry is None or not args.json):
            raise ValueError('--track requires --retry and --json')
        if args.command in CONFIG_COMMANDS and not (args.command == 'review' and args.action == 'manifest'):
            args.config = load_config(local_only=True) if args.command in ('review', 'approve') else load_config()
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
