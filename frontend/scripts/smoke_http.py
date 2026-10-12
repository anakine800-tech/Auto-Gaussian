"""Explicit local HTTP smoke against one existing Core store; never a calculation."""

import argparse
import hashlib
import http.client
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
from urllib.parse import quote

from auto_g16.query import QueryService


def fingerprint(database):
    fd = os.open(database, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        digest = hashlib.sha256()
        while chunk := os.read(fd, 1024 * 1024):
            digest.update(chunk)
        return digest.hexdigest(), info.st_size, info.st_ino, info.st_mtime_ns, info.st_ctime_ns
    finally:
        os.close(fd)


def smoke(database):
    query = QueryService(database)
    projects = query.list_projects()  # Qualify source before launching a listener.
    if not projects["data"]["items"]:
        raise RuntimeError("smoke requires an existing Project and Attempt")
    project_id = projects["data"]["items"][0]["project_id"]
    attempts = query.list_attempts(project_id=project_id)
    if not attempts["data"]["items"]:
        raise RuntimeError("smoke requires an existing Attempt")
    attempt_id = attempts["data"]["items"][0]["attempt_id"]
    expected = {
        "/api/projects": projects,
        f"/api/projects/{quote(project_id, safe='')}": query.get_project(project_id),
        f"/api/projects/{quote(project_id, safe='')}/attempts": attempts,
        f"/api/attempts/{quote(attempt_id, safe='')}": query.get_attempt(attempt_id),
    }
    before = fingerprint(database)
    entries = sorted(p.name for p in database.parent.iterdir())
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    token = secrets.token_urlsafe(32)
    process = subprocess.Popen(
        [sys.executable, "-B", "-m", "autog_frontend", "--database", str(database), "--port", str(port)],
        env={**os.environ, "AUTOG_READ_TOKEN": token, "PYTHONDONTWRITEBYTECODE": "1"},
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    try:
        ready = False
        for _ in range(100):
            if process.poll() is not None:
                raise RuntimeError("local HTTP process exited before readiness")
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=0.2)
            try:
                connection.request("GET", "/api/projects")
                response = connection.getresponse()
                ready = response.status == 401
                response.read()
            except OSError:
                pass
            finally:
                connection.close()
            if ready:
                break
            time.sleep(0.05)
        if not ready:
            raise RuntimeError("local HTTP process did not become ready")

        statuses = []
        for path, dto in expected.items():
            # Token travels on stdin, never in curl argv, shell history or report.
            config = f'url = "http://127.0.0.1:{port}{path}"\nheader = "Authorization: Bearer {token}"\n'
            result = subprocess.run(["/usr/bin/curl", "--silent", "--show-error", "--fail",
                                     "--noproxy", "*", "--max-time", "10", "--config", "-"],
                                    input=config, text=True, capture_output=True, check=True)
            if json.loads(result.stdout) != dto:
                raise RuntimeError("HTTP response differs from public QueryService")
            statuses.append(200)
        unchanged = before == fingerprint(database) and entries == sorted(p.name for p in database.parent.iterdir())
        if not unchanged:
            raise RuntimeError("source changed during HTTP smoke; no result accepted")
        detail = expected[f"/api/attempts/{quote(attempt_id, safe='')}"]["data"]
        return {"status": "PASS", "routes_checked": len(statuses), "http_statuses": statuses,
                "unauthenticated_status": 401, "source_sha256": before[0], "source_unchanged": True,
                "project_count": len(projects["data"]["items"]),
                "attempt_count": len(attempts["data"]["items"]),
                "local_core_state": detail["execution_state"], "result_state": detail["result_state"],
                "server_stopped_after_test": True}
    finally:
        process.terminate()  # Only this smoke's local HTTP child; no scheduler operation.
        try:
            process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path)
    args = parser.parse_args()
    if not sys.dont_write_bytecode or not args.database.is_absolute():
        parser.error("use Python -B and an absolute database path")
    print(json.dumps(smoke(args.database), indent=2, sort_keys=True))
