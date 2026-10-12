"""Read-only result queries; separately enabled local human mode records."""

from __future__ import annotations

import json
from pathlib import Path
import re
import secrets
from collections.abc import Callable

from fastapi import FastAPI, Request
from starlette.exceptions import HTTPException
from starlette.responses import Response

from auto_g16.query import QUERY_SCHEMA, QueryError, QueryService
from .result_query import ResultSummaryQuery

ERROR_SCHEMA = "auto-g16-http-error/1"
ERROR_STATUS = {
    "invalid-id": 400,
    "exactly-one-parent-required": 400,
    "not-found": 404,
    "store-unavailable": 503,
    "invalid-evidence": 409,
    "response-too-large": 413,
    "invalid-review-request": 400,
    "review-writing-disabled": 403,
    "review-target-changed": 409,
    "review-request-conflict": 409,
    "review-store-invalid": 409,
    "review-store-unavailable": 503,
    "review-store-limit": 413,
    "invalid-task-request": 400,
    "task-conflict": 409,
    "task-review-changed": 409,
    "task-capacity-busy": 409,
    "task-queue-full": 413,
    "execution-unavailable": 503,
}
SAFE_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
}


def error_response(code: str, status: int) -> Response:
    headers = dict(SAFE_HEADERS)
    if status == 401:
        headers["WWW-Authenticate"] = "Bearer"
    if status == 405:
        headers["Allow"] = "GET"
    return Response(
        json.dumps({"schema": ERROR_SCHEMA, "error": {"code": code}}, sort_keys=True),
        status_code=status, media_type="application/json", headers=headers,
    )


class ReadOnlyBoundary:
    """Authorize before routing; only the opted-in local mode-record POST may write."""

    def __init__(self, app, *, token: str, local_no_token: bool = False, public_paths: frozenset[str] = frozenset(), mode_review_enabled: bool = False, library_enabled: bool = False, tasks_enabled: bool = False):
        self.app = app
        self.authorization = ("Bearer " + token).encode("ascii")
        self.public_paths = public_paths
        self.local_no_token = local_no_token
        self.mode_review_enabled = mode_review_enabled
        self.library_enabled = library_enabled
        self.tasks_enabled = tasks_enabled

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1008})
                return
            await self.app(scope, receive, send)
            return
        headers = scope.get("headers", [])
        authorization = [v for k, v in headers if k.lower() == b"authorization"]
        failure = None
        public = scope["path"] in self.public_paths
        if not public and not self.local_no_token and (len(authorization) != 1 or not secrets.compare_digest(authorization[0], self.authorization)):
            failure = error_response("unauthorized", 401)
        else:
            hosts = [v for k, v in headers if k.lower() == b"host"]
            origins = [v for k, v in headers if k.lower() == b"origin"]
            host = hosts[0] if len(hosts) == 1 else b""
            lengths = [v for k, v in headers if k.lower() == b"content-length"]
            transfer = [v for k, v in headers if k.lower() == b"transfer-encoding"]
            raw_path = scope.get("raw_path", scope["path"].encode())
            review_post = self.mode_review_enabled and scope['method'] == 'POST' and bool(re.fullmatch(r'/api/attempts/[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}/mode-review', scope['path']))
            library_post = self.library_enabled and scope['method']=='POST' and scope['path'] in ('/api/library/settings','/api/library/capture','/api/library/retry')
            task_post = self.tasks_enabled and scope['method']=='POST' and scope['path'] in ('/api/task-center/draft','/api/task-center/enqueue','/api/task-center/submit','/api/task-center/withdraw','/api/task-center/reconcile')
            write_post = review_post or library_post or task_post
            if self.local_no_token and (not scope.get('client') or scope['client'][0] not in ('127.0.0.1', '::1')):
                failure = error_response("local-client-required", 403)
            elif self.local_no_token and any(v == b'cross-site' for k,v in headers if k.lower() == b'sec-fetch-site'):
                failure = error_response("origin-not-allowed", 403)
            elif not re.fullmatch(rb"(?:127\.0\.0\.1|localhost)(?::[0-9]{1,5})?", host):
                failure = error_response("invalid-host", 400)
            elif origins and origins != [b"http://" + host]:
                failure = error_response("origin-not-allowed", 403)
            elif scope["method"] != "GET" and not write_post:
                failure = error_response("method-not-allowed", 405)
            elif len(raw_path) > 2048 or sum(len(k) + len(v) for k, v in headers) > 8192:
                failure = error_response("request-too-large", 413)
            elif scope.get("query_string"):
                failure = error_response("query-parameters-not-supported", 400)
            elif not write_post and (transfer or lengths not in ([], [b"0"])):
                failure = error_response("request-body-not-supported", 400)
            elif re.search(rb"%2f|%5c", raw_path, re.IGNORECASE):
                failure = error_response("invalid-id", 400)
            elif write_post:
                content_types = [v for k,v in headers if k.lower() == b'content-type']
                actions = [v for k,v in headers if k.lower() == (b'x-autog-task' if task_post else b'x-autog-library' if library_post else b'x-autog-review')]
                fetch_sites = [v for k,v in headers if k.lower() == b'sec-fetch-site']
                if (not scope.get('client') or scope['client'][0] not in ('127.0.0.1','::1')
                        or origins != [b'http://'+host] or actions != ([b'task-command/1'] if task_post else [b'library/1'] if library_post else [b'intended-mode/1'])
                        or fetch_sites not in ([],[b'same-origin'])):
                    failure = error_response('review-origin-required',403)
                elif content_types != [b'application/json'] or transfer or len(lengths) != 1 or not re.fullmatch(rb'[0-9]{1,5}', lengths[0]):
                    failure = error_response('invalid-review-request',400)
                elif not 1 <= int(lengths[0]) <= 16384:
                    failure = error_response('request-too-large',413)
        if failure is not None:
            await failure(scope, receive, send)
            return
        await self.app(scope, receive, send)


def create_app(database: str | Path, *, token: str = "", local_no_token: bool = False, max_response_bytes: int = 4 * 1024 * 1024,
               ui_directory: Path | None = None, archive_index: Path | None = None,
               archive_sha256: str | None = None, evidence_catalog: Path | None = None,
               evidence_sha256: str | None = None, mode_review_directory: Path | None = None, library_manager=None, monitor=None, task_queue=None, native_sources=None) -> FastAPI:
    """No database I/O at construction. An optional trusted UI bundle is read once."""
    if QUERY_SCHEMA != "auto-g16-query/1":
        raise ValueError("unsupported query contract")
    if type(local_no_token) is not bool or (local_no_token and token != ""):
        raise ValueError("local no-token mode must not include a token")
    if not local_no_token and (not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{32,256}", token)):
        raise ValueError("a 32-256 character URL-safe bearer token is required")
    if type(max_response_bytes) is not int or not 256 <= max_response_bytes <= 16 * 1024 * 1024:
        raise ValueError("invalid response limit")
    query = QueryService(database)
    result_query = ResultSummaryQuery(database)
    from .archive import ArchiveQuery
    archive_query = ArchiveQuery(archive_index, archive_sha256)
    from .details import DetailQuery
    detail_query = DetailQuery(database, archive_query, evidence_catalog, evidence_sha256)
    if library_manager is not None:
        from .library import LiveArchives, LiveDetails
        archive_query, detail_query = LiveArchives(library_manager), LiveDetails(library_manager)
    from .mode_review import ModeReviewService
    mode_reviews = ModeReviewService(detail_query,mode_review_directory)
    from contextlib import asynccontextmanager
    @asynccontextmanager
    async def lifespan(_app):
        if library_manager is not None:library_manager.start()
        try:
            if monitor is not None:monitor.start()
            if task_queue is not None:task_queue.start()
            yield
        finally:
            if monitor is not None:monitor.close()
            if task_queue is not None:task_queue.close()
            if library_manager is not None:library_manager.close()
    app = FastAPI(lifespan=lifespan, title="Auto-Gaussian Read-only API", version="0.1.0",
                  docs_url=None, redoc_url=None, openapi_url=None, redirect_slashes=False)
    from .static_ui import load_ui
    public_files = load_ui(ui_directory) if ui_directory is not None else {}
    if local_no_token and '/' in public_files:
        body, mime = public_files['/']
        require_marker = b'</head>'
        if body.count(require_marker) != 1:
            raise ValueError('UI requires one head for local access mode')
        public_files['/'] = (body.replace(require_marker, b'<meta name="autog-access" content="local-no-token"></head>'), mime)
    app.add_middleware(ReadOnlyBoundary, token=token, local_no_token=local_no_token, public_paths=frozenset(public_files), mode_review_enabled=mode_review_directory is not None, library_enabled=library_manager is not None, tasks_enabled=task_queue is not None)
    def static_handler(content, mime):
        def static_endpoint():
            return Response(content, media_type=mime, headers={
                **SAFE_HEADERS,
                "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self'; "
                "connect-src 'self'; img-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
                "Referrer-Policy": "no-referrer",
            })
        return static_endpoint

    for url, (body, media_type) in public_files.items():
        app.add_api_route(url, static_handler(body, media_type), methods=["GET"], include_in_schema=False)

    @app.exception_handler(HTTPException)
    async def route_error(_request, error):
        return error_response("not-found" if error.status_code == 404 else "method-not-allowed",
                              error.status_code)

    def invoke(operation: Callable, *args, **kwargs) -> Response:
        try:
            for identifier in (*args, *kwargs.values()):
                if (not isinstance(identifier, str) or len(identifier) > 512
                        or identifier in (".", "..") or "/" in identifier or "\\" in identifier
                        or any(ord(c) < 32 or ord(c) == 127 for c in identifier)):
                    return error_response("invalid-id", 400)
            # The owning service finishes its snapshot checks before anything is serialized.
            dto = operation(*args, **kwargs)
            body = bytearray()
            encoder = json.JSONEncoder(ensure_ascii=True, sort_keys=True, allow_nan=False,
                                       separators=(",", ":"))
            for chunk in encoder.iterencode(dto):
                encoded = chunk.encode("ascii")
                if len(body) + len(encoded) > max_response_bytes:
                    return error_response("response-too-large", 413)
                body.extend(encoded)
            return Response(bytes(body), media_type="application/json", headers=SAFE_HEADERS)
        except QueryError as error:
            status = ERROR_STATUS.get(error.code)
            return error_response(error.code, status) if status else error_response("internal-error", 500)
        except Exception:
            # Neither local source paths nor payloads are returned or logged.
            return error_response("internal-error", 500)

    @app.get('/api/capabilities')
    def capabilities():
        from . import __version__
        return invoke(lambda: dict(schema='autog-workbench-capabilities/1', version=__version__,
            features=dict(result_browsing=True, analysis=True, local_drafts=True,
                          local_science=True, local_queue=task_queue is not None,
                          execution=task_queue is not None and task_queue.gateway is not None,
                          monitor=monitor is not None, library=library_manager is not None,
                          mode_review=mode_review_directory is not None, v31_dag=False)))

    @app.get('/api/monitor')
    def server_monitor():
        if monitor is None:
            return invoke(lambda: {'schema': 'autog-server-monitor/1', 'enabled': False})
        return invoke(monitor.snapshot)

    from .calculation_analysis import query_analysis
    @app.get('/api/{group}/{identity}/analysis')
    def calculation_analysis(group: str, identity: str):
        if group not in ('attempts','archives'): return error_response('not-found',404)
        return invoke(lambda i: query_analysis(detail_query,'attempt' if group=='attempts' else 'archive',i),identity)

    @app.get('/api/task-center')
    def task_center():
        if task_queue is None:
            return invoke(lambda: dict(schema='autog-task-center/1',enabled=False,execution_enabled=False,items=[],prepared=[],max_active=0))
        return invoke(task_queue.snapshot)

    if task_queue is not None:
        @app.post('/api/task-center/{action}')
        async def task_action(action: str, request: Request):
            raw=bytearray()
            try:
                async for part in request.stream():
                    raw.extend(part)
                    if len(raw)>16384:return error_response('request-too-large',413)
                if len(raw)!=int(request.headers['content-length']):raise ValueError()
                from .archive import _object
                body=json.loads(raw,object_pairs_hook=_object,parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
            except (ValueError,KeyError):return error_response('invalid-task-request',400)
            from starlette.concurrency import run_in_threadpool
            return await run_in_threadpool(invoke,lambda:task_queue.action(action,body))

    from .workflow_query import WorkflowQuery
    workflows=WorkflowQuery(database,detail_query,monitor,mode_reviews)
    @app.get('/api/workflows')
    def workflow_overview():return invoke(workflows.overview)

    @app.get('/api/workflows/attempts/{identity}')
    def workflow_attempt(identity: str):return invoke(workflows.attempt,identity)

    from .project_catalog import ProjectLibrary
    project_library=ProjectLibrary(query,detail_query)
    @app.get('/api/project-library')
    def all_projects():return invoke(project_library.list_projects)
    @app.get('/api/project-library/{identity}')
    def historical_project(identity: str):return invoke(project_library.get_project,identity)
    @app.get('/api/archives/{identity}/workflow')
    def archive_workflow(identity: str):return invoke(detail_query.get_workflow,identity)
    @app.get('/api/archives/{identity}/conditions')
    def archive_conditions(identity: str):return invoke(detail_query.get_conditions,identity)

    if native_sources is not None:
        from auto_g16.query import NativeQueryService
        native_query = NativeQueryService(tuple(native_sources))

        @app.get('/api/v1/native/sources')
        def native_sources_list():
            return invoke(native_query.list_sources)

        @app.get('/api/v1/native/projects')
        def native_projects():
            return invoke(native_query.list_projects)

        @app.get('/api/v1/native/sources/{source_id}/projects/{project_id}/attempts')
        def native_attempts(source_id: str, project_id: str):
            return invoke(native_query.list_attempts, source_id, project_id)

        @app.get('/api/v1/native/sources/{source_id}/attempts/{attempt_id}')
        def native_attempt(source_id: str, attempt_id: str):
            return invoke(native_query.get_attempt, source_id, attempt_id)

        @app.get('/api/v1/native/sources/{source_id}/attempts/{attempt_id}/thermodynamics')
        def native_thermodynamics(source_id: str, attempt_id: str):
            return invoke(lambda source, attempt: native_query.get_thermodynamics(source, attempt),
                          source_id, attempt_id)

    # Optional additive owners: older backends remain explicitly unavailable.
    if native_sources is not None:
        def native_optional(kind, source, attempt):
            operation = getattr(native_query, 'get_' + kind, None)
            if operation is not None:
                return operation(source, attempt)
            native_query.get_attempt(source, attempt)  # membership; no invented result
            data = dict(source_id=source, attempt_id=attempt, availability='unavailable',
                        reason='backend-unavailable', result=None)
            if kind == 'populations':
                data['selected_member_id'] = None
            return dict(schema='auto-g16-native-' + kind + '-query/1', kind=kind, data=data)

        @app.get('/api/v1/native/sources/{source_id}/attempts/{attempt_id}/lifecycle')
        def native_lifecycle(source_id: str, attempt_id: str):
            return invoke(lambda source, attempt: native_optional('lifecycle', source, attempt),
                          source_id, attempt_id)

        @app.get('/api/v1/native/sources/{source_id}/attempts/{attempt_id}/populations')
        def native_populations(source_id: str, attempt_id: str):
            return invoke(lambda source, attempt: native_optional('populations', source, attempt),
                          source_id, attempt_id)

    @app.get("/api/projects")
    def projects():
        return invoke(query.list_projects)

    @app.get("/api/archives")
    def archives():
        return invoke(archive_query.list_archives)

    @app.get("/api/archives/{archive_id}")
    def archive(archive_id: str):
        return invoke(archive_query.get_archive, archive_id)

    @app.get("/api/archives/{archive_id}/details")
    def archive_details(archive_id: str):
        return invoke(detail_query.get_details, 'archive', archive_id)

    @app.get("/api/archives/{archive_id}/log")
    def archive_log(archive_id: str):
        return invoke(detail_query.get_log, 'archive', archive_id)

    @app.get("/api/attempts/{attempt_id}/details")
    def attempt_details(attempt_id: str):
        return invoke(detail_query.get_details, 'attempt', attempt_id)

    @app.get("/api/attempts/{attempt_id}/log")
    def attempt_log(attempt_id: str):
        return invoke(detail_query.get_log, 'attempt', attempt_id)

    @app.get("/api/attempts/{attempt_id}/vibrations")
    def attempt_vibrations(attempt_id: str):
        return invoke(detail_query.get_vibrations, 'attempt', attempt_id)

    @app.get("/api/archives/{archive_id}/vibrations")
    def archive_vibrations(archive_id: str):
        return invoke(detail_query.get_vibrations, 'archive', archive_id)

    from .log_window import read_window
    def window(*args,**kwargs):
        return detail_query.log_window(*args,**kwargs) if library_manager is not None else read_window(detail_query,*args,**kwargs)
    @app.get('/api/{group}/{identity}/log-window/{start}/{count}')
    def log_window(group: str, identity: str, start: str, count: str):
        if group not in ('archives','attempts'): return error_response('not-found',404)
        return invoke(lambda i,s,c: window('archive' if group=='archives' else 'attempt',i,'page',s,c),identity,start,count)

    @app.get('/api/{group}/{identity}/log-span/{start}/{end}/{digest}')
    def log_span(group: str, identity: str, start: str, end: str, digest: str):
        if group not in ('archives','attempts'): return error_response('not-found',404)
        return invoke(lambda i,s,e,h: window('archive' if group=='archives' else 'attempt',i,'span',s,e,h),identity,start,end,digest)

    @app.get('/api/{group}/{identity}/log-find/{term}/{start}')
    def log_find(group: str, identity: str, term: str, start: str):
        if group not in ('archives','attempts'): return error_response('not-found',404)
        return invoke(lambda i,t,s: window('archive' if group=='archives' else 'attempt',i,'find',s,'120',term=t),identity,term,start)

    @app.get("/api/projects/{project_id}")
    def project(project_id: str):
        return invoke(query.get_project, project_id)

    @app.get("/api/projects/{project_id}/attempts")
    def attempts(project_id: str):
        return invoke(query.list_attempts, project_id=project_id)

    @app.get("/api/projects/{project_id}/tasks")
    def tasks(project_id: str):
        return invoke(query.list_tasks, project_id)

    @app.get("/api/attempts/{attempt_id}")
    def attempt(attempt_id: str):
        return invoke(query.get_attempt, attempt_id)

    @app.get("/api/attempts/{attempt_id}/result")
    def result_summary(attempt_id: str):
        return invoke(result_query.get_summary, attempt_id)

    @app.get('/api/attempts/{attempt_id}/mode-review')
    def get_mode_reviews(attempt_id: str):
        return invoke(mode_reviews.get,attempt_id)

    if mode_review_directory is not None:
        @app.post('/api/attempts/{attempt_id}/mode-review')
        async def confirm_mode(attempt_id: str, request: Request):
            # Bounded actual stream, independently of the declared length.
            raw = bytearray()
            try:
                async for part in request.stream():
                    raw.extend(part)
                    if len(raw) > 16384:
                        return error_response('request-too-large',413)
                if len(raw) != int(request.headers['content-length']):
                    return error_response('invalid-review-request',400)
                from .archive import _object
                body = json.loads(raw,object_pairs_hook=_object,parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
            except (ValueError,KeyError):
                return error_response('invalid-review-request',400)
            # The closure keeps body out of the generic identifier validator.
            from starlette.concurrency import run_in_threadpool
            return await run_in_threadpool(invoke,lambda identity: mode_reviews.confirm(identity,body),attempt_id)


    @app.get('/api/archives/{archive_id}/history-links')
    def history_links(archive_id: str):
        return invoke(detail_query.get_history_links,archive_id)

    @app.get('/api/library')
    def library_status():
        if library_manager is None:return error_response('library-disabled',404)
        return invoke(library_manager.status)

    if library_manager is not None:
        @app.post('/api/library/{action}')
        async def library_action(action: str,request: Request):
            raw=bytearray()
            try:
                async for part in request.stream():
                    raw.extend(part)
                    if len(raw)>16384:return error_response('request-too-large',413)
                if len(raw)!=int(request.headers['content-length']):raise ValueError()
                from .archive import _object
                body=json.loads(raw,object_pairs_hook=_object)
                if not isinstance(body,dict):raise ValueError()
            except (ValueError,KeyError):return error_response('invalid-library-request',400)
            def run():
                try:
                    if action=='settings':value=library_manager.configure(body)
                    elif action=='retry' and set(body)=={'id'}:value=library_manager.retry(body['id'])
                    elif action=='capture' and set(body)=={'source'} and isinstance(body['source'],str):
                        from .library import capture_completed
                        identity=capture_completed(Path(body['source']),library_manager.config)
                        if library_manager.settings()['auto_archive']:library_manager.wake.set()
                        value=dict(schema='autog-local-capture/1',id=identity,status='receipt-ready')
                    else:raise ValueError()
                    return invoke(lambda:value)
                except (ValueError,OSError,KeyError,TypeError):return error_response('invalid-library-request',400)
            from starlette.concurrency import run_in_threadpool
            return await run_in_threadpool(run)

    return app
