"""Synthetic archival capture, never remote data."""
import hashlib
import json
from pathlib import Path
from .result_fixture import PREFIX, INPUT, FREQUENCY


def archive_capture(root: Path, *, frequency=False, invalid=False):
    log = b"not Gaussian\n" if invalid else PREFIX + (FREQUENCY if frequency else b"") + b" Normal termination of Gaussian 16\n"
    job = {"schema": "codex-gaussian-pbs/1", "project": "Synthetic archived calculation",
           "status": "completed", "input_sha256": hashlib.sha256(INPUT).hexdigest(),
           "result": {"log": "synthetic.log"}}
    files = []
    for name, raw in [("synthetic.log", log), ("synthetic.gjf", INPUT), ("job.json", json.dumps(job).encode())]:
        p = root / name
        p.write_bytes(raw)
        digest = hashlib.sha256(raw).hexdigest()
        files.append({"path": "C:\\Archive\\" + name, "local_file": str(p), "size": len(raw),
                      "sha256": digest, "sha256_after": digest})
    return {"schema": "rtwin-archive-capture/1", "source": "rtwin-local",
            "observed_at": "2026-09-24T00:00:00Z", "files": files}
