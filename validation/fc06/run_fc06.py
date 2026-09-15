#!/usr/bin/env python3
"""Bounded external FC06 evidence; executes the exact unmodified wrapper source.

Synthetic config and a compiled inert actor exercise publisher process behavior.
They grant no production adapter, profile, scheduler or scientific authority.
Every output directory is new; all evidence is retained. Stop on first failure.
"""
import argparse
import ast
import base64
import ctypes
import hashlib
import json
import os
from pathlib import Path
import platform
import signal
import subprocess
import sys
import time

HEAD = "3116d1f1919eff164ef3593171d0ed7f42c778b5"
TREE = "32fe6df47c947988311497fbd4b2de75d97c1a34"
FILE_HASH = "664e6ea75ac2b9e1b7d880e198b5a41b195054f54d956548fa8e0ce5c2e6ba09"
SOURCE_HASH = "58167de5436ec2d5ae9ef89dde458f386cdc2860f4f00a41c81c0a390f782333"
CASES = (
    ("adoption", 0, 0), ("direct_zero_descendant_nonzero", 0, 7),
    ("direct_nonzero_descendant_zero", 9, 0), ("direct_signal", 0, 0),
    ("descendant_timeout", 0, 0), ("wrapper_death", 0, 0),
    ("publication_boundary", 0, 0), ("prctl_denied", 0, 0),
)

def canonical(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode() + b"\n"

def digest(raw):
    return hashlib.sha256(raw).hexdigest()

def node(value):
    if value is None: return ["null", None]
    if type(value) is bool: return ["boolean", value]
    if type(value) is int: return ["integer", value]
    if type(value) is str: return ["string", value]
    if type(value) is list: return ["sequence", [node(v) for v in value]]
    if type(value) is dict: return ["mapping", [[k, node(value[k])] for k in sorted(value)]]
    raise TypeError(type(value))

def semantic(value):
    return digest(json.dumps(node(value), ensure_ascii=False, separators=(",", ":")).encode())

def write_new(path, raw):
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())

def save(path, value):
    write_new(path, canonical(value))

def wait_for(predicate, seconds, label):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = predicate()
        if value: return value
        time.sleep(0.01)
    raise AssertionError("bounded wait expired: " + label)

def read_event(path):
    if not path.exists(): return None
    try: return json.loads(path.read_bytes())
    except json.JSONDecodeError: return None  # Exclusive creation can precede write.

def process(pid):
    try:
        raw = Path(f"/proc/{pid}/stat").read_text()
    except FileNotFoundError:
        return None
    fields = raw[raw.rfind(")") + 2:].split()
    return {"pid": pid, "state": fields[0], "ppid": int(fields[1]), "start_ticks": int(fields[19])}

def signal_owned(info, sig):
    current = process(info["pid"])
    assert current and current["start_ticks"] == info["start_ticks"], "owned process identity changed"
    # pidfd pins the target between identity checking and signal delivery.
    fd = os.pidfd_open(info["pid"])
    try:
        check = process(info["pid"])
        assert check and check["start_ticks"] == info["start_ticks"]
        signal.pidfd_send_signal(fd, sig)
    finally:
        os.close(fd)

def no_receipt(workspace):
    assert not (workspace / "v31-completion.pending").exists(), "pending published while writer alive"
    assert not (workspace / "v31-completion.json").exists(), "final published while writer alive"

def config_for(case, workspace, events, actor, python):
    name, direct_rc, descendant_rc = case
    xyz = b"1\nFC06 inert input\nH 0 0 0\n"
    write_new(workspace / "input.xyz", xyz)
    data = workspace / "data"
    data.mkdir(mode=0o700)
    write_new(data / "fixture.dat", b"FC06 inert runtime data\n")
    marker = {"program_execution_snapshot_id": "fc06-synthetic-snapshot-" + name, "effect_intent_id": "fc06-synthetic-effect-" + name}
    save(workspace / ".auto-g16-v31-submit-intent", marker)
    python_raw = python.read_bytes()
    actor_raw = actor.read_bytes()
    roots = {"server_python": {"path": str(python), "expected_size_bytes": len(python_raw), "expected_sha256": digest(python_raw)}}
    raw_data = (data / "fixture.dat").read_bytes()
    runtime = {"files": {"fixture.dat": {"size_bytes": len(raw_data), "sha256": digest(raw_data)}}}
    material = {"deployment_manifest_base64": base64.b64encode(canonical({"trust_roots": roots})).decode(), "xtb_runtime_data_manifest_base64": base64.b64encode(canonical(runtime)).decode()}
    spec = {
        "program_kind": "xtb", "adapter_id": "auto-g16-v31-xtb", "adapter_contract_version": 3,
        "program_execution_spec_id": "fc06-synthetic-spec-" + name,
        "program_data": {"task": "single-point", "completion_mode": "receipt-on-absence-v1"},
        "exact_inputs": [{"logical_role": "structure", "portable_name": "input.xyz", "format": "xyz", "size_bytes": len(xyz), "sha256": digest(xyz)}],
        "required_outputs": [{"logical_role": "program-log", "portable_name": "xtb.out", "format": "text", "max_size_bytes": 65536}],
        "optional_outputs": [],
        "invocation": {"executable_identity": {"absolute_path": str(actor), "size_bytes": len(actor_raw), "sha256": digest(actor_raw)},
                       "argv": [str(actor), str(events), "signal" if name == "direct_signal" else "normal", str(direct_rc), str(descendant_rc), "6000"]},
    }
    binding = {"attempt_id": "fc06-" + name, "cwd_binding": {"path": str(workspace)},
               "program_execution_spec_id": spec["program_execution_spec_id"],
               "program_execution_spec_payload_sha256": semantic(spec),
               "rendering_material_sha256": semantic(material), "workspace_binding_id": "fc06-synthetic-workspace-" + name,
               "wrapper_source_sha256": SOURCE_HASH, "wrapper_source_size_bytes": 14181}
    return {"prebinding": binding, "prebinding_sha256": semantic(binding), "spec": spec, "material": material,
            "xtb_data_path": str(data), "cores": 1, "walltime_seconds": 1 if name == "descendant_timeout" else 10}

def run_case(case, root, actor, python, source):
    name, direct_rc, descendant_rc = case
    case_root = root / name
    case_root.mkdir(mode=0o700)
    workspace, events = case_root / "workspace", case_root / "events"
    workspace.mkdir(mode=0o700)
    events.mkdir(mode=0o700)
    config = config_for(case, workspace, events, actor, python)
    save(case_root / "config.json", config)
    command = [str(python), "-I", "-S", "-B", "-c", source, base64.b64encode(canonical(config)).decode()]
    if name == "prctl_denied": command = [str(actor), "--deny-prctl", *command]
    save(case_root / "intent.json", {"case": name, "monotonic_ns": time.monotonic_ns(), "source_sha256": SOURCE_HASH,
                                    "config_sha256": digest(canonical(config)), "watchdog_and_reap_ceiling_seconds": 60, "synthetic_invocation": True})
    proc = None
    result = {"case": name, "status": "FAIL", "observations": []}
    started = time.monotonic()
    try:
        with (case_root / "wrapper.stdout").open("xb") as out, (case_root / "wrapper.stderr").open("xb") as err:
            proc = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                                    env={"PBS_JOBID": "fc06.synthetic", "LC_ALL": "C"}, close_fds=True)
            wrapper = wait_for(lambda: process(proc.pid), 2, "wrapper identity")
            save(case_root / "start.json", {"wrapper": wrapper, "supervisor_pid": os.getpid(), "monotonic_ns": time.monotonic_ns()})
            if name == "prctl_denied":
                assert proc.wait(timeout=10) == 125
                assert b"FC06_REAL_PRCTL_DENIED errno=1" in (case_root / "wrapper.stderr").read_bytes()
                assert not (events / "direct.json").exists() and not (workspace / "xtb.out").exists()
                no_receipt(workspace)
                result["real_prctl_errno"] = 1
                result["actor_launches"] = 0
            else:
                direct = wait_for(lambda: read_event(events / "direct.json"), 3, "direct launch")
                adopted = wait_for(lambda: read_event(events / "adopted.json"), 3, "real descendant adoption")
                descendant = process(adopted["pid"])
                assert direct["ppid"] == proc.pid and adopted["ppid"] == proc.pid
                assert descendant and descendant["ppid"] == proc.pid
                result["direct"] = direct
                result["adopted"] = adopted
                result["descendant_identity"] = descendant
                held = Path(f"/proc/{descendant['pid']}/fd/1").stat()
                log_object = (workspace / "xtb.out").stat()
                assert (held.st_dev, held.st_ino) == (log_object.st_dev, log_object.st_ino)
                result["descendant_log_fd"] = {"device": held.st_dev, "inode": held.st_ino}
                # A held release gate establishes live-writer/no-publication ordering.
                for _ in range(20):
                    live = process(descendant["pid"])
                    assert live and live["state"] != "Z" and live["start_ticks"] == descendant["start_ticks"]
                    no_receipt(workspace)
                    time.sleep(0.01)
                result["observations"].append({"event": "writer_alive_no_receipt", "monotonic_ns": time.monotonic_ns()})
                if name == "direct_signal":
                    target = process(direct["pid"])
                    assert target and target["ppid"] == proc.pid
                    signal_owned(target, signal.SIGTERM)
                    result["direct_signal_target"] = target
                    result["delivered_signal"] = int(signal.SIGTERM)
                    no_receipt(workspace)
                if name == "wrapper_death":
                    signal_owned(wrapper, signal.SIGKILL)
                    assert proc.wait(timeout=5) == -signal.SIGKILL
                elif name == "descendant_timeout":
                    assert proc.wait(timeout=5) == 125
                if name in {"wrapper_death", "descendant_timeout"}:
                    no_receipt(workspace)
                    survivor = process(descendant["pid"])
                    assert survivor and survivor["ppid"] == os.getpid() and survivor["state"] != "Z"
                    result["survivor_after_wrapper_exit"] = survivor
                save(events / "release", {"monotonic_ns": time.monotonic_ns()})
                if name not in {"wrapper_death", "descendant_timeout"}:
                    expected = 128 + signal.SIGTERM if name == "direct_signal" else direct_rc
                    assert proc.wait(timeout=10) == expected
                    pending, final = workspace / "v31-completion.pending", workspace / "v31-completion.json"
                    assert pending.is_file() and final.is_file()
                    before, published = pending.stat(), final.stat()
                    assert (before.st_dev, before.st_ino) == (published.st_dev, published.st_ino)
                    raw = final.read_bytes()
                    receipt = json.loads(raw)
                    assert canonical(receipt) == raw and pending.read_bytes() == raw
                    term = {"kind": "signaled", "returncode": None, "signal": 15} if name == "direct_signal" else {"kind": "exited", "returncode": direct_rc, "signal": None}
                    assert receipt["termination"] == term
                    log = (workspace / "xtb.out").read_bytes()
                    assert log == b"FC06_DESCENDANT_FINAL_BYTES\n"
                    assert receipt["outputs"][0]["sha256"] == digest(log)
                    assert receipt["outputs"][0]["size_bytes"] == len(log)
                    assert process(descendant["pid"]) is None, "descendant not reaped before publication"
                    middle = read_event(events / "middle.json")
                    assert middle and process(middle["pid"]) is None
                    assert process(direct["pid"]) is None
                    result["receipt"] = {"sha256": digest(raw), "termination": term, "inode": published.st_ino, "device": published.st_dev}
                else:
                    # The supervisor adopts only fixture descendants after wrapper exit.
                    wait_for(lambda: read_event(events / "descendant_exit.json"), 5, "owned survivor self-exit")
                    def reap_survivor():
                        pair = os.waitpid(descendant["pid"], os.WNOHANG)
                        return pair if pair[0] else None
                    pid, status = wait_for(reap_survivor, 5, "owned survivor reap")
                    assert pid == descendant["pid"] and os.waitstatus_to_exitcode(status) == descendant_rc
                    result["supervisor_reaped_survivor"] = {"pid": pid, "wait_status": status}
                    no_receipt(workspace)
                result["actor_launches"] = 1
            result["status"] = "PASS"
    except BaseException as exc:
        result["error"] = type(exc).__name__ + ": " + str(exc)
        raise
    finally:
        # Never replace an original case error with an independent cleanup error.
        cleanup_errors = []
        reaped = []
        try:
            if proc is not None and proc.poll() is None:
                try:
                    proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    result["owned_wrapper_watchdog"] = "SIGKILL"
                    current = process(proc.pid)
                    if current:
                        signal_owned(current, signal.SIGKILL)
                    proc.wait(timeout=3)
        except BaseException as exc:
            cleanup_errors.append({"stage": "wrapper_watchdog", "error": type(exc).__name__ + ": " + str(exc)})
        try:
            until = time.monotonic() + 8
            while time.monotonic() < until:
                try:
                    pid, status = os.waitpid(-1, os.WNOHANG)
                except ChildProcessError:
                    break
                if pid:
                    reaped.append({"pid": pid, "wait_status": status})
                else:
                    time.sleep(0.01)
            else:
                cleanup_errors.append({"stage": "descendant_reap", "error": "bounded reap expired"})
        except BaseException as exc:
            cleanup_errors.append({"stage": "descendant_reap", "error": type(exc).__name__ + ": " + str(exc)})
        finally:
            if cleanup_errors:
                result["status"] = "FAIL"
            result["cleanup_errors"] = cleanup_errors
            result["supervisor_other_reaps"] = reaped
            result["duration_seconds"] = time.monotonic() - started
            result["wrapper_returncode"] = proc.returncode if proc else None
            save(case_root / "result.json", result)
    assert result["status"] == "PASS", result
    return result

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--evidence", required=True, type=Path)
    args = parser.parse_args()
    root = args.evidence.absolute()
    root.mkdir(mode=0o700)  # Existing run roots are never reused.
    results = []
    summary = {"status": "FAIL", "passed_cases": 0, "planned_cases": len(CASES),
               "candidate_head": HEAD, "candidate_tree": TREE, "results": results,
               "production_qualified": False}
    started = time.monotonic()
    stage = "environment"
    try:
        python = Path(sys.executable).resolve(strict=True)
        here = Path(__file__).resolve().parent
        environment = {"candidate_head": HEAD, "candidate_tree": TREE,
                       "wrapper_file_sha256": FILE_HASH, "wrapper_source_sha256": SOURCE_HASH,
                       "python": str(python), "python_version": sys.version,
                       "python_sha256": digest(python.read_bytes()), "kernel": platform.release(),
                       "machine": platform.machine(), "platform": sys.platform, "uid": os.getuid(),
                       "actor_source_sha256": digest((here / "fc06_actor.c").read_bytes()),
                       "harness_sha256": digest(Path(__file__).read_bytes()),
                       "validation_commit": os.environ.get("GITHUB_SHA"),
                       "ci_run_id": os.environ.get("GITHUB_RUN_ID"),
                       "ci_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
                       "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                       "synthetic_invocation": True, "production_qualified": False}
        save(root / "environment.json", environment)
        assert sys.platform == "linux", "real Linux required; no mocked fallback"
        assert hasattr(os, "pidfd_open") and hasattr(signal, "pidfd_send_signal")
        write_new(root / "proc-self-mountinfo.txt", Path("/proc/self/mountinfo").read_bytes())
        write_new(root / "os-release.txt", Path("/etc/os-release").read_bytes())
        stage = "candidate_identity"
        repo = args.candidate.resolve(strict=True)
        def git(*argv):
            return subprocess.check_output(["git", "-C", str(repo), *argv], timeout=10)
        assert git("rev-parse", "HEAD").decode().strip() == HEAD
        assert git("rev-parse", "HEAD^{tree}").decode().strip() == TREE
        assert not git("status", "--porcelain=v1")
        raw = (repo / "auto_g16/execution/_program_completion_wrapper.py").read_bytes()
        assert digest(raw) == FILE_HASH
        module = ast.parse(raw)
        source = next(ast.literal_eval(n.value) for n in module.body if isinstance(n, ast.Assign)
                      and any(isinstance(t, ast.Name) and t.id == "_WRAPPER_SOURCE" for t in n.targets))
        assert digest(source.encode()) == SOURCE_HASH and len(source.encode()) == 14181
        write_new(root / "wrapper-source.py", source.encode())
        stage = "supervisor_subreaper"
        libc = ctypes.CDLL(None, use_errno=True)
        assert libc.prctl(36, 1, 0, 0, 0) == 0
        value = ctypes.c_int()
        assert libc.prctl(37, ctypes.byref(value), 0, 0, 0) == 0 and value.value == 1
        save(root / "supervisor.json", {"pid": os.getpid(), "subreaper_readback": value.value})
        stage = "build"
        actor = root / "fc06_actor"
        command = ["/usr/bin/timeout", "--signal=KILL", "30s", "/usr/bin/cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-O2",
                   str(here / "fc06_actor.c"), "-o", str(actor)]
        save(root / "build-intent.json", {"command": command, "group_timeout_seconds": 30,
             "outer_wait_seconds": 35, "reap_seconds": 8,
             "timeout_sha256": digest(Path("/usr/bin/timeout").read_bytes()),
             "cc_resolved_path": str(Path("/usr/bin/cc").resolve(strict=True)),
             "cc_sha256": digest(Path("/usr/bin/cc").read_bytes())})
        # Regular output files avoid an inherited PIPE blocking timeout handling.
        build_result = {"returncode": None, "actor_sha256": None, "cleanup_errors": []}
        build_proc = None
        try:
            with (root / "build.stdout").open("xb") as out, (root / "build.stderr").open("xb") as err:
                build_proc = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                                              start_new_session=True)
                build_result["pid"] = build_proc.pid
                build_result["session_leader"] = build_proc.pid
                build_result["scope"] = "new session; GNU timeout kills its compiler process group at 30s"
                build_proc.wait(timeout=35)
                build_result["returncode"] = build_proc.returncode
                assert build_proc.returncode == 0, "compiler failed; see build.stderr"
                build_result["actor_sha256"] = digest(actor.read_bytes())
        except BaseException as exc:
            build_result["error"] = type(exc).__name__ + ": " + str(exc)
            raise
        finally:
            try:
                if build_proc is not None and build_proc.poll() is None:
                    current = process(build_proc.pid)
                    if current:
                        signal_owned(current, signal.SIGKILL)
                    build_proc.wait(timeout=3)
                # Adopted compiler children get a finite observation window.
                # Never wait on inherited output pipes or launch a second compile.
                reaped = []
                until = time.monotonic() + 8
                while time.monotonic() < until:
                    try:
                        pid, status = os.waitpid(-1, os.WNOHANG)
                    except ChildProcessError:
                        break
                    if pid:
                        reaped.append({"pid": pid, "wait_status": status})
                    else:
                        time.sleep(0.01)
                else:
                    raise AssertionError("compiler descendants not reaped within bound; CI job ceiling remains")
                build_result["other_reaps"] = reaped
            except BaseException as exc:
                build_result["cleanup_errors"].append(type(exc).__name__ + ": " + str(exc))
            finally:
                build_result["returncode"] = build_proc.returncode if build_proc else None
                save(root / "build-result.json", build_result)
        assert not build_result["cleanup_errors"], "compiler cleanup failed; see build-result.json"
        for case in CASES:
            stage = case[0]
            print("START " + stage, flush=True)
            results.append(run_case(case, root, actor, python, source))
            print("PASS " + stage, flush=True)
        stage = "final_candidate_clean"
        assert not git("status", "--porcelain=v1")
        summary["status"] = "PASS"
    except BaseException as exc:
        summary["error"] = type(exc).__name__ + ": " + str(exc)
        # Each failing case also retains its own result and raw files.
        summary["failure_stage"] = stage
        raise
    finally:
        summary["passed_cases"] = len(results)
        summary["duration_seconds"] = time.monotonic() - started
        summary["not_passed_cases"] = [case[0] for case in CASES if case[0] not in {r["case"] for r in results}]
        save(root / "summary.json", summary)

if __name__ == "__main__":
    main()
