"""Explicit local launch. Never choose a data source from an HTTP request."""

import argparse
import os
import sys
import json
import secrets
import subprocess
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Auto-Gaussian local read-only HTTP API")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--database", type=Path, help="Canonical absolute Core database path")
    source.add_argument("--profile", type=Path, help="Explicit local source profile, no credentials")
    parser.add_argument("--native-sources", type=Path, help="Explicit pinned native source registry")
    parser.add_argument("--native-sources-sha256", help="SHA-256 of the native source registry")
    parser.add_argument("--port", default=8765, type=int)
    parser.add_argument("--archive-index", type=Path, help="Canonical absolute offline legacy archive index")
    parser.add_argument("--archive-sha256", help="Pinned SHA-256 of the offline archive index")
    parser.add_argument("--evidence-catalog", type=Path, help="Pinned local artifact catalog")
    parser.add_argument("--evidence-sha256")
    parser.add_argument('--mode-review-directory',type=Path,help='Enable append-only local human mode confirmations in this existing directory')
    parser.add_argument('--library-config',type=Path,help='Opt-in local archive settings and completed-fetch queue')
    parser.add_argument('--monitor-config',type=Path,help='Opt-in fixed read-only SSH telemetry; isolated local history')
    parser.add_argument('--task-queue-directory',type=Path,help='Enable local drafts and durable submit queue in an existing separate directory')
    parser.add_argument('--execution-provider',help='Trusted installed module:factory returning RuntimeGateway; local launch only')
    parser.add_argument('--max-active-tasks',type=int,default=1,help='Maximum active jobs submitted by this queue')
    access = parser.add_mutually_exclusive_group()
    access.add_argument("--no-token", action="store_true", help="Local read-only access without a bearer token")
    access.add_argument("--copy-token", action="store_true", help="Generate a session token and copy it to the macOS clipboard")
    ui = parser.add_mutually_exclusive_group()
    ui.add_argument("--ui-directory", type=Path, help="Trusted local Vite build directory")
    ui.add_argument("--ui", action="store_true", help="Serve the UI bundled in the installed wheel")
    args = parser.parse_args()
    if not sys.dont_write_bytecode:
        parser.error("start Python with -B or PYTHONDONTWRITEBYTECODE=1")
    if args.profile:
        try:
            profile = json.loads(args.profile.read_text())
            if set(profile) - {'database','port','archive_index','archive_sha256','evidence_catalog','evidence_sha256'}:
                raise ValueError('unexpected profile field')
            args.database = Path(profile['database'])
            args.port = profile.get('port', args.port)
            for k in ('archive_index','archive_sha256','evidence_catalog','evidence_sha256'):
                if k in profile:
                    setattr(args,k,Path(profile[k]) if k.endswith(('index','catalog')) else profile[k])
        except (OSError, ValueError, KeyError, TypeError):
            parser.error('invalid local source profile')
    if not args.database.is_absolute() or type(args.port) is not int or not 1024 <= args.port <= 65535:
        parser.error("use an absolute database path and a port between 1024 and 65535")
    if bool(args.native_sources) != bool(args.native_sources_sha256):
        parser.error('--native-sources and --native-sources-sha256 are required together')
    native_sources = None
    if args.native_sources:
        from .native_sources import load_native_sources
        try:
            native_sources = load_native_sources(args.native_sources, args.native_sources_sha256)
        except (OSError, ValueError, KeyError, TypeError):
            parser.error('invalid pinned native source registration')
    try:
        from .api import create_app
    except ModuleNotFoundError:
        parser.error("install the complete hash-locked local candidate bundle")
    try:
        token = "" if args.no_token else secrets.token_urlsafe(32) if args.copy_token else os.environ.get("AUTOG_READ_TOKEN", "")
        library_manager=None
        if args.library_config:
            if not args.profile:parser.error('--library-config requires --profile')
            from .library import LibraryManager
            library_manager=LibraryManager(args.library_config,args.profile)
        monitor=None
        if args.monitor_config:
            from .monitor import Monitor
            monitor=Monitor(args.monitor_config)
        task_queue=None
        if args.execution_provider and not args.task_queue_directory:
            parser.error('--execution-provider requires --task-queue-directory')
        if args.task_queue_directory:
            from .task_queue import TaskQueue, RuntimeGateway
            gateway=None
            if args.execution_provider:
                import importlib,re
                if not re.fullmatch(r'[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*:[A-Za-z_]\w*',args.execution_provider):
                    parser.error('invalid execution provider')
                module,factory=args.execution_provider.split(':')
                gateway=getattr(importlib.import_module(module),factory)()
                if not isinstance(gateway,RuntimeGateway):parser.error('execution provider must return RuntimeGateway')
            task_queue=TaskQueue(args.task_queue_directory,gateway,args.max_active_tasks)
        app = create_app(args.database, token=token, local_no_token=args.no_token,
                         ui_directory=(Path(__file__).resolve().parent / "ui") if args.ui else args.ui_directory,
                         archive_index=args.archive_index, archive_sha256=args.archive_sha256,
                         evidence_catalog=args.evidence_catalog, evidence_sha256=args.evidence_sha256,
                         native_sources=native_sources,mode_review_directory=args.mode_review_directory,library_manager=library_manager,monitor=monitor,task_queue=task_queue)
    except ValueError as error:
        parser.error(str(error))
    if args.copy_token:
        if sys.platform != 'darwin':
            parser.error('--copy-token requires macOS')
        subprocess.run(['/usr/bin/pbcopy'], input=token.encode(), check=True)
        print(f'http://127.0.0.1:{args.port} — session token copied to clipboard', flush=True)
    if args.no_token:
        print(f'http://127.0.0.1:{args.port} — local access, calculation results read-only, no token', flush=True)
    if args.mode_review_directory:
        print('Human intended-mode confirmations enabled; original results remain read-only.',flush=True)
    if args.monitor_config:
        print('Read-only server telemetry enabled; runs while this local service is open.',flush=True)
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False, proxy_headers=False,
                server_header=False, limit_concurrency=8, timeout_keep_alive=5,
                h11_max_incomplete_event_size=8192, log_level="warning")


if __name__ == "__main__":
    main()
