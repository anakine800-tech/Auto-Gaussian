"""FC01–FC15 inert synthetic completion evidence; no production qualification."""
from dataclasses import replace
from hashlib import sha256
import json
import os
import sys
import subprocess
import threading
import sqlite3
import fcntl
import select
import signal
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from auto_g16 import core, execution
from auto_g16.execution import program as adapter
from auto_g16.execution import program_runtime as runtime
from auto_g16.execution import _program_completion as completion
from auto_g16.execution._program_completion_wrapper import _WRAPPER_SOURCE
from auto_g16.transport import program as transport
from auto_g16.transport._canonical import TransportBoundaryError
from auto_g16.transport._program_rtwin import _RTWinProgramEffectDriver
from tests.v3.execution import test_v31_lane_a as lane
from tests.v31.transport import test_program_composition as composition


def manifest():
    roots = {}
    for name, (platform, attestation) in completion._ROOT_RULES.items():
        shell = name == "server_remote_shell"
        content = (name + " synthetic\n").encode()
        roots[name] = {"path": "/opt/auto-g16-fixtures/bin/" + name, "platform": platform, "attestation_mode": attestation, "deployment_identity": "synthetic-only", "expected_sha256": None if shell else sha256(content).hexdigest(), "expected_size_bytes": None if shell else len(content), "shell_grammar": "posix-sh-v1" if shell else None}
    return {"schema": "auto-g16-v3-transport-deployment-manifest/3", "deployment_id": "synthetic-completion", "bootstrap_protocol": "auto-g16-v31-rtwin-bootstrap/1", "trust_roots": roots}




# Module-private constant, copied without product edits.
_FORK_REGISTRATION_WINDOW_PROBE = r'''"""External inert draft: native fork/FD/SQLite registration-window assertions.

Arguments: repository root, mode (fd or sqlite). No product lock substitutions.
All atfork hooks and instrumentation die with this short-lived interpreter.
"""
import errno
import json
import os
import signal
import sys

def child_watchdog():
    signal.signal(signal.SIGALRM, signal.SIG_DFL)
    signal.alarm(4)

# Registered BEFORE importing transport: this after-child hook runs first,
# including before a regressed product hook could block on an inherited mutex.
os.register_at_fork(after_in_child=child_watchdog)
signal.signal(signal.SIGALRM, signal.SIG_DFL)
signal.alarm(20)
sys.path.insert(0, sys.argv[1])
from auto_g16.transport import program as transport
from auto_g16.transport._canonical import TransportBoundaryError
import fcntl
from pathlib import Path
import select
import subprocess
import tempfile
import threading
import warnings
from unittest.mock import patch

mode = sys.argv[2]
assert mode in ('fd', 'sqlite')
entered = threading.Event()
release = threading.Event()
witness = threading.Event()
fork_returned = threading.Event()
worker_finished = threading.Event()
finish_worker = threading.Event()
captured = {}
errors = []
result = {}
creator_pid = os.getpid()

def pause_window():
    assert transport._DIRECTORY_MUTEX.locked()
    entered.set()
    if not release.wait(8):
        raise AssertionError('test coordinator failed to release registration window')

# Registered AFTER transport: before hooks run in reverse registration order.
# Witness proves os.fork entered while the worker still owns the product mutex.
def before_fork_witness():
    if threading.current_thread().name == 'window-fork':
        assert transport._DIRECTORY_MUTEX.locked()
        witness.set()
os.register_at_fork(before=before_fork_witness)

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp).resolve()
    path = root / 'owner.sqlite3'
    owner = transport._ProgramTransportStore._create_completion_store(path, approved_root=root)
    separate = root / 'separate'
    separate.mkdir()
    second_path = separate / 'second.sqlite3'
    second = transport._ProgramTransportStore._create_completion_store(second_path, approved_root=root)
    second.close()
    read_fd, write_fd = os.pipe()
    original_open = os.open
    original_registry = transport._STORE_HANDLES

    def instrumented_open(*args, **kwargs):
        fd = original_open(*args, **kwargs)
        if mode == 'fd' and threading.current_thread().name == 'window-worker' and 'fd' not in captured:
            # FD is actually open, but _directory_walk has not appended/registered it.
            captured['fd'] = fd
            captured['identity'] = (os.fstat(fd).st_dev, os.fstat(fd).st_ino)
            assert fd not in transport._DIRECTORY_FDS
            pause_window()
        return fd

    class RegistryProbe:
        def add(self, value):
            if mode == 'sqlite' and threading.current_thread().name == 'window-worker' and 'store' not in captured:
                # The real sqlite3.connect already returned and was assigned.
                captured['store'] = value
                assert value not in original_registry
                assert value._connection.execute('SELECT 1').fetchone() == (1,)
                pause_window()
            return original_registry.add(value)
        def __iter__(self):
            return iter(original_registry)

    def worker():
        try:
            if mode == 'fd':
                with transport._directory_walk(str(second_path), str(root)):
                    worker_finished.set()
                    assert finish_worker.wait(8)
            else:
                value = transport._ProgramTransportStore.open_existing(second_path, approved_root=root)
                try:
                    worker_finished.set()
                    assert finish_worker.wait(8)
                finally:
                    value.close()
        except BaseException as exc:
            errors.append(('worker', repr(exc)))

    def fork_worker():
        pid = None
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('ignore', DeprecationWarning)
                pid = os.fork()
            if pid == 0:
                try:
                    os.close(read_fd)
                    assert transport._FORK_CHILD_QUARANTINED
                    assert not transport._DIRECTORY_FDS
                    if mode == 'fd':
                        try:
                            os.fstat(captured['fd'])
                        except OSError as exc:
                            assert exc.errno == errno.EBADF
                        else:
                            raise AssertionError('newly registered descriptor survived child hook')
                    else:
                        assert any(value is captured['store'] for value in transport._FORK_QUARANTINE)
                        # No inherited SQLite call or close is made in the child.
                        for action in (captured['store']._attest, captured['store'].close):
                            try:
                                action()
                            except TransportBoundaryError:
                                pass
                            else:
                                raise AssertionError('inherited handle accepted')
                    try:
                        transport._ProgramTransportStore.create_new(root / 'forbidden.sqlite3', approved_root=root)
                    except TransportBoundaryError:
                        pass
                    else:
                        raise AssertionError('child create accepted before exec')
                    os.write(write_fd, b'child-closed-and-quarantined')
                except BaseException as exc:
                    os.write(write_fd, ('ERROR:' + repr(exc)).encode()[:2048])
                    os._exit(2)
                os._exit(0)
            fork_returned.set()
            assert select.select([read_fd], [], [], 6)[0], 'child did not report'
            result['payload'] = os.read(read_fd, 2048).decode()
        except BaseException as exc:
            errors.append(('fork', repr(exc)))
        finally:
            if pid:
                result['status'] = os.waitpid(pid, 0)[1]

    worker_thread = threading.Thread(target=worker, name='window-worker', daemon=True)
    fork_thread = threading.Thread(target=fork_worker, name='window-fork', daemon=True)
    try:
        with owner._completion_guard() as token:
            with patch.object(os, 'open', side_effect=instrumented_open), patch.object(transport, '_STORE_HANDLES', RegistryProbe()):
                worker_thread.start()
                assert entered.wait(5), 'registration boundary was not entered'
                fork_thread.start()
                assert witness.wait(5), 'real fork request did not reach before callback'
                assert not fork_returned.wait(0.15), 'fork bypassed the held registration mutex'
                release.set()
                assert worker_finished.wait(5), 'worker did not finish registration'
                fork_thread.join(7)
                assert not fork_thread.is_alive(), 'fork worker failed to reap child'
                assert not errors, errors
                assert result == {'payload': 'child-closed-and-quarantined', 'status': 0}, result
                assert not (root / 'forbidden.sqlite3').exists()
                owner._require_completion_guard(token)
                # A real independent interpreter must still lose: the child hook
                # must close inherited descriptors WITHOUT issuing LOCK_UN.
                probe = subprocess.run([sys.executable, '-c',
                    'import os,fcntl,sys; fd=os.open(sys.argv[1],os.O_RDONLY|os.O_DIRECTORY)\n'
                    'try: fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)\n'
                    'except BlockingIOError: print("busy")\n'
                    'else: print("ACQUIRED")\n', str(root)], capture_output=True, text=True, timeout=5)
                assert probe.returncode == 0 and probe.stdout.strip() == 'busy', (probe.returncode, probe.stdout, probe.stderr)
                finish_worker.set()
                worker_thread.join(5)
                assert not worker_thread.is_alive() and not errors, errors
        print(json.dumps({'mode': mode, 'native_fork': True, 'registration_window_entered': True,
                          'fork_blocked_until_registered': True, 'child_reaped': True,
                          'parent_lock_preserved': True, 'result': result}, sort_keys=True))
    finally:
        release.set()
        finish_worker.set()
        if worker_thread.ident is not None: worker_thread.join(5)
        if fork_thread.ident is not None: fork_thread.join(7)
        os.close(read_fd)
        os.close(write_fd)
        owner.close()
signal.alarm(0)
'''



_SUPPLEMENT_WRAPPER_CHILD = r'''
import json,os,signal,subprocess,sys
from types import SimpleNamespace
from auto_g16.execution._program_completion_wrapper import _WRAPPER_SOURCE
signal.signal(signal.SIGALRM,signal.SIG_DFL)
signal.alarm(12)
config=json.loads(open(sys.argv[1]).read())
phase=sys.argv[2]
namespace={'__name__':'inert_process_death'}
exec(compile(_WRAPPER_SOURCE,'reviewed-wrapper','exec'),namespace)
launches=[]
writers=[]
def checkpoint(value):
    message={'phase':value,'launches':len(launches),'pid':os.getpid()}
    if writers:
        assert writers[0].returncode==0
        try:os.waitpid(writers[0].pid,os.WNOHANG)
        except ChildProcessError:pass
        else:raise AssertionError('inert writer was not already reaped')
        message.update(writer_reaped=True,writer_returncode=0)
    print(json.dumps(message),flush=True)
    os.read(0,1)
    raise AssertionError('death checkpoint unexpectedly released')
def launch(*args,**kwargs):
    assert kwargs['shell'] is False
    assert kwargs['executable'].startswith('/proc/self/fd/')
    assert kwargs['env']=={'OMP_NUM_THREADS':'8','XTBPATH':config['xtb_data_path']}
    launches.append(True)
    assert len(launches)==1
    if phase=='writer-reaped-before-link':
        # Real direct child, real waitpid, known short-lived Python bytes only.
        # This is NOT /proc execution of the reviewed scientific executable.
        code='import os,signal;signal.signal(signal.SIGALRM,signal.SIG_DFL);signal.alarm(2);os.write(1,b"actual inert direct writer\\n")'
        writer=subprocess.Popen([sys.executable,'-c',code],stdin=subprocess.DEVNULL,stdout=kwargs['stdout'],stderr=kwargs['stderr'],env=kwargs['env'],shell=False)
        writers.append(writer)
        return writer
    os.write(kwargs['stdout'],b'inert never-executed scientific program\n')
    return SimpleNamespace(pid=123,returncode=None)
def wait(pid,deadline):
    if writers:
        assert pid==writers[0].pid
        return original_wait(pid,deadline)
    assert pid==123
    if phase=='after-inert-launch':checkpoint(phase)
    return 0
original_link=os.link
original_wait=namespace['wait_all']
def link(*args,**kwargs):
    if phase in ('before-link','writer-reaped-before-link'):checkpoint(phase)
    result=original_link(*args,**kwargs)
    if phase=='after-link':checkpoint(phase)
    return result
namespace['subreaper']=lambda:None
namespace['wait_all']=wait
namespace['subprocess']=SimpleNamespace(Popen=launch,DEVNULL=-3)
os.link=link
os.environ['PBS_JOBID']='123.server'
namespace['run'](config)
raise AssertionError('wrapper finished instead of reaching the death checkpoint')
'''

def _supplement_wrapper_config(self, workspace):
    data = workspace / 'data'
    data.mkdir()
    for name in lane.XTB_RUNTIME_DATA_FILES:
        (data / name).write_bytes(name.encode())
    executable = workspace / 'inert-program'
    executable.write_bytes(b'never executed\n')
    (workspace / 'input.xyz').write_bytes(lane.XYZ)
    (workspace / '.auto-g16-v31-submit-intent').write_bytes(completion._receipt_json({'program_execution_snapshot_id':'synthetic','effect_intent_id':'synthetic'}))
    python_path = Path(sys.executable).resolve()
    python_raw = python_path.read_bytes()
    spec = json.loads(completion._receipt_json(self.snapshot.program_execution_spec.semantic_payload()))
    spec['invocation']['executable_identity'] = {'absolute_path':str(executable),'size_bytes':executable.stat().st_size,'sha256':sha256(executable.read_bytes()).hexdigest()}
    spec['invocation']['argv'][0] = str(executable)
    material = dict(self.snapshot._completion_material())
    deployment = manifest()
    deployment['trust_roots']['server_python'].update(path=str(python_path),expected_size_bytes=len(python_raw),expected_sha256=sha256(python_raw).hexdigest())
    material['deployment_manifest_base64'] = completion.base64.b64encode(completion._receipt_json(deployment)).decode()
    fields = {k:v for k,v in self.snapshot._identity_payload.items() if k != 'scheduler_artifacts'}
    fields.update(cwd_binding={'location_kind':'server','path':str(workspace)}, program_execution_spec_payload_sha256=runtime.semantic_sha256(spec))
    binding = completion._prebinding(fields, material)
    return {'prebinding':binding,'prebinding_sha256':runtime.semantic_sha256(binding),'spec':spec,'material':material,'xtb_data_path':str(data),'cores':8,'walltime_seconds':1}

class CompletionTests(lane.LaneAFixture):
    """Native directory flock and default SQLite, including on Darwin."""
    def profile(self, **kwargs):
        profile = super().profile(**kwargs)
        return replace(profile, runtime_contents={**profile.runtime_contents, completion._DEPLOYMENT_NAME: completion._receipt_json(manifest())})

    def resolved(self, **kwargs):
        return execution.resolve_server_profile(self.profile(**kwargs))

    def completion_spec(self, **changes):
        return adapter._prepare_program_execution_spec(program_kind="xtb", executable_path=lane.XTB_EXECUTABLE_PATH, executable_size_bytes=len(lane.XTB_EXECUTABLE_BYTES), executable_sha256=sha256(lane.XTB_EXECUTABLE_BYTES).hexdigest(), input_name="input.xyz", input_bytes=lane.XYZ, program_data=self.xtb_data(**changes), resolved_profile=self.resolved(), completion_mode=completion._MODE)

    def completion_snapshot(self, **changes):
        return self.snapshot_service.prepare(self.store, attempt_id="attempt-1", calculation_plan_id="plan-1", resource_spec_id="resource-1", program_execution_spec=self.completion_spec(**changes), project_physical_binding=self.physical_binding(), resolved_resource_request=self.resources(), resolved_server_profile=self.resolved(), workspace_binding=self.workspace(), completion_rendering_material=completion._prepare_completion_rendering_material(self.profile(), self.resolved()))

    def setUp(self):
        super().setUp()
        root = self.root / "transport"
        root.mkdir()
        self.program_transport_store = transport._ProgramTransportStore._create_completion_store(root / "program.sqlite3", approved_root=root)
        self.addCleanup(self.program_transport_store.close)
        self.snapshot = self.completion_snapshot()
        self.driver = composition._Driver()
        self.input_bytes = {"input.xyz": lane.XYZ}
        self.scheduler_bytes = {"xtb.pbs": self.snapshot.scheduler_artifacts[0]["content_utf8"].encode()}

    execute = composition.ProgramCompositionTests.execute

    def kwargs(self):
        return dict(snapshot=self.snapshot, program_transport_store=self.program_transport_store, driver=self.driver)

    def publish(self, *, code=0, signal=None, **overrides):
        receipt = dict(completion._receipt_binding(self.snapshot, "123.server", "workspace-token-v31"))
        receipt.update(termination={"kind": "signaled" if signal else "exited", "returncode": None if signal else code, "signal": signal}, finished_at="2026-09-14T01:02:03.000004Z", outputs=[])
        for declaration in (*self.snapshot.program_execution_spec.required_outputs, *self.snapshot.program_execution_spec.optional_outputs):
            content = self.driver.outputs.get(declaration["portable_name"])
            receipt["outputs"].append({**{key: declaration[key] for key in ("logical_role", "portable_name", "format")}, "presence": "absent" if content is None else "present", "sha256": None if content is None else sha256(content).hexdigest(), "size_bytes": None if content is None else len(content)})
        receipt.update(overrides)
        self.driver.outputs["v31-completion.json"] = completion._receipt_json(receipt)
        self.driver.query_response = {"job_id": "123.server", "state": "absent"}
        return receipt

    def collect(self):
        return runtime._collect_program_completion(self.store, **self.kwargs(), input_bytes=self.input_bytes)

    def test_success_durable_bundle_and_zero_read_replay(self):
        self.execute(); self.publish()
        assessment = self.collect()
        self.assertEqual(assessment.data["diagnostic"], "completed")
        self.assertEqual(self.store.attempt_state("attempt-1"), core.AttemptState.SUCCEEDED)
        self.assertEqual(len(self.store.results_for_attempt("attempt-1")), 1)
        calls = len(self.driver.calls)
        self.assertEqual(runtime._replay_program_completion(self.store, **self.kwargs()), assessment)
        proof = runtime._assert_program_receipt_success_authority(self.store, **self.kwargs())
        self.assertEqual(proof["schema"], "program-terminal-success-authority/2")
        self.assertEqual(len(self.driver.calls), calls)

    def test_default_strict_renderer_and_mode_are_unchanged(self):
        strict = self.successor_snapshot()
        self.assertEqual(strict.program_execution_spec.adapter_contract_version, 2)
        self.assertNotIn("completion_mode", strict.program_execution_spec.program_data)
        self.assertEqual(strict.scheduler_artifacts[0]["content_utf8"].splitlines()[1], "# auto-g16-v31-scheduler/1")
        self.assertNotEqual(strict.program_execution_snapshot_id, self.snapshot.program_execution_snapshot_id)
        self.snapshot.assert_identity_closed()

    def test_material_missing_or_strict_injection_rejected(self):
        with self.assertRaises(ValueError):
            self.successor_snapshot(spec=self.completion_spec())
        with self.assertRaises(ValueError):
            adapter._render_scheduler_artifact(self.xtb_spec(), self.resources(), self.resolved(), completion_rendering_material=self.snapshot._completion_material())

    def test_rendered_source_and_material_reclose(self):
        script = self.snapshot.scheduler_artifacts[0]["content_utf8"]
        self.assertIn(" -I -S -B -c ", script)
        material = self.snapshot._completion_material()
        self.assertEqual(material, completion._prepare_completion_rendering_material(self.profile(), self.resolved()))
        for changed in (script.replace("# completion-material-base64:", "# moved:"), script + script.splitlines()[2] + "\n"):
            with self.assertRaises(ValueError):
                completion._material_from_artifact(({"content_utf8": changed},), self.resolved())

    def test_production_driver_is_unconditionally_blocked(self):
        with self.assertRaisesRegex(TransportBoundaryError, "publisher-not-qualified"):
            _RTWinProgramEffectDriver(snapshot=self.snapshot, current_profile=self.profile(), program_transport_store=self.program_transport_store)
        self.driver.runtime_qualification = {**self.driver.runtime_qualification, "bootstrap_protocol": "auto-g16-v31-rtwin-bootstrap/1"}
        with self.assertRaisesRegex(TransportBoundaryError, "publisher-not-qualified"):
            runtime._snapshot_binding(self.snapshot, self.program_transport_store, self.driver)
        self.assertEqual(self.driver.calls, [])

    def test_terminal_scheduler_cannot_complete_receipt_mode(self):
        self.execute()
        self.driver.query_response = {"job_id": "123.server", "state": "terminal", "exit_status": 0}
        result = self.collect()
        self.assertEqual(result.data["diagnostic"], "awaiting-absence")
        self.assertEqual(self.store.attempt_state("attempt-1"), core.AttemptState.SUBMITTED)

    def test_running_receipt_cannot_complete(self):
        self.execute(); self.publish()
        self.driver.query_response = {"job_id": "123.server", "state": "running"}
        self.assertEqual(self.collect().data["diagnostic"], "scheduler-active")
        self.assertEqual(self.store.attempt_state("attempt-1"), core.AttemptState.RUNNING)

    def test_absence_without_receipt_is_unknown(self):
        self.execute(); self.driver.query_response = {"job_id": "123.server", "state": "absent"}
        self.assertEqual(self.collect().data["diagnostic"], "receipt-missing")
        self.assertEqual(self.store.attempt_state("attempt-1"), core.AttemptState.SUBMITTED)

    def test_nonzero_with_absent_required_output_is_failed(self):
        self.execute(); self.driver.outputs = {}; self.publish(code=7)
        self.assertEqual(self.collect().data["diagnostic"], "program-nonzero")
        self.assertEqual(self.store.attempt_state("attempt-1"), core.AttemptState.FAILED)

    def test_zero_with_absent_required_output_is_failed(self):
        self.execute(); self.driver.outputs = {}; self.publish()
        self.assertEqual(self.collect().data["diagnostic"], "output-incomplete")

    def test_direct_signal_with_absent_output_is_failed(self):
        self.execute(); self.driver.outputs = {}; self.publish(signal=15)
        self.assertEqual(self.collect().data["diagnostic"], "program-signaled")

    def test_invalid_geometry_is_execution_failure(self):
        self.execute(); self.driver.outputs["xtbopt.xyz"] = b"1\nfixture\nH nan 0 0\n"; self.publish()
        self.assertEqual(self.collect().data["diagnostic"], "output-invalid")

    def test_changed_receipt_binding_precedes_nonzero(self):
        self.execute(); self.publish(code=8, effect_intent_id="foreign-intent")
        self.assertEqual(self.collect().data["diagnostic"], "receipt-invalid")
        self.assertEqual(self.store.attempt_state("attempt-1"), core.AttemptState.SUBMITTED)

    def test_missing_input_bytes_stops_without_remote_reads(self):
        self.execute(); self.publish(); self.input_bytes = {}
        calls = len(self.driver.calls)
        self.assertEqual(self.collect().data["diagnostic"], "acquisition-unknown")
        self.assertEqual(len(self.driver.calls), calls)

    def test_fetch_timeout_is_not_absence_or_nonzero(self):
        self.execute(); self.publish(code=4)
        self.driver.raise_operation = ("FETCH_EXACT_FILE", TimeoutError())
        self.assertEqual(self.collect().data["diagnostic"], "acquisition-unknown")

    def test_guard_blocks_another_store_handle_without_effects(self):
        self.execute(); self.publish()
        other = transport._ProgramTransportStore.open_existing(self.program_transport_store._path, approved_root=self.program_transport_store._root)
        self.addCleanup(other.close)
        before = self.store.observations_for_attempt("attempt-1")
        calls = len(self.driver.calls)
        with other._completion_guard():
            with self.assertRaisesRegex(TransportBoundaryError, "busy"):
                self.collect()
        self.assertEqual(len(self.driver.calls), calls)
        self.assertEqual(self.store.observations_for_attempt("attempt-1"), before)

    def test_later_unknown_blocks_promotion_without_rollback(self):
        self.execute(); self.publish(); self.collect()
        self.driver.query_response = {"job_id": "123.server", "state": "unknown"}
        runtime._query_program_scheduler(self.store, **self.kwargs())
        self.assertEqual(runtime._replay_program_completion(self.store, **self.kwargs()).data["diagnostic"], "acquisition-unknown")
        with self.assertRaises(TransportBoundaryError):
            runtime._assert_program_receipt_success_authority(self.store, **self.kwargs())
        self.assertEqual(self.store.attempt_state("attempt-1"), core.AttemptState.SUCCEEDED)

    def test_later_active_is_conflict_without_rollback(self):
        self.execute(); self.publish(); self.collect()
        self.driver.query_response = {"job_id": "123.server", "state": "queued"}
        runtime._query_program_scheduler(self.store, **self.kwargs())
        self.assertEqual(runtime._replay_program_completion(self.store, **self.kwargs()).data["diagnostic"], "evidence-conflict")
        self.assertEqual(self.store.attempt_state("attempt-1"), core.AttemptState.SUCCEEDED)

    def test_contradictory_terminal_exit_blocks_nonzero(self):
        self.execute()
        self.driver.query_response = {"job_id": "123.server", "state": "terminal", "exit_status": 0}
        runtime._query_program_scheduler(self.store, **self.kwargs())
        self.publish(code=1)
        self.assertEqual(self.collect().data["diagnostic"], "evidence-conflict")

    def test_receipt_grammar_rejects_duplicate_fields_and_bad_types(self):
        valid = self.publish()
        for raw in (completion._receipt_json(valid).replace(b'"schema":', b'"schema":"duplicate","schema":', 1), completion._receipt_json({**valid, "adapter_contract_version": True}), completion._receipt_json({**valid, "extra": 1}), b"\xef\xbb\xbf" + completion._receipt_json(valid), completion._receipt_json(valid) + b"\n"):
            with self.subTest(raw=raw[:60]), self.assertRaises(ValueError):
                completion._decode_receipt(raw)

    def test_wrapper_source_compiles_and_no_replace_publication(self):
        namespace = {"__name__": "offline_wrapper_fixture"}
        exec(compile(_WRAPPER_SOURCE, "completion-wrapper", "exec"), namespace)
        directory = self.root / "publication"
        directory.mkdir()
        fd, token = namespace["directory"](str(directory))
        self.addCleanup(os.close, fd)
        raw = b'{"inert":true}\n'
        namespace["publish"](fd, str(directory), token, raw)
        self.assertEqual((directory / "v31-completion.json").read_bytes(), raw)
        self.assertEqual((directory / "v31-completion.pending").stat().st_ino, (directory / "v31-completion.json").stat().st_ino)
        with self.assertRaises(FileExistsError):
            namespace["publish"](fd, str(directory), token, b"different")
        self.assertEqual((directory / "v31-completion.json").read_bytes(), raw)

    def test_single_point_optional_absence_succeeds(self):
        self.snapshot = self.completion_snapshot(task="single-point")
        self.scheduler_bytes = {"xtb.pbs": self.snapshot.scheduler_artifacts[0]["content_utf8"].encode()}
        self.execute(); self.driver.outputs.pop("xtbopt.xyz"); self.publish()
        self.assertEqual(self.collect().data["diagnostic"], "completed")

    def test_fresh_attempt_only_and_bad_material_before_attestation(self):
        with patch.object(type(self.project_provisioning), "_attest_current", side_effect=AssertionError("must not attest")):
            with self.assertRaises(ValueError):
                self.successor_snapshot(spec=self.completion_spec())
        self.execute()
        with self.assertRaisesRegex(ValueError, "fresh unconsumed"):
            self.completion_snapshot()

    def test_material_and_manifest_adversarial_vectors(self):
        from auto_g16.transport._driver import _parse_deployment_manifest
        raw = completion._receipt_json(manifest())
        self.assertEqual(_parse_deployment_manifest(raw, successor=True).deployment_id, "synthetic-completion")
        for path in ("deployment_id", "root"):
            value = manifest()
            if path == "root":
                value["trust_roots"]["server_python"]["deployment_identity"] = "a\nb"
            else:
                value[path] = "a\nb"
            raw = completion._receipt_json(value)
            with self.assertRaises(ValueError):
                completion._deployment_projection(raw)
            with self.assertRaises(TransportBoundaryError):
                _parse_deployment_manifest(raw, successor=True)
        material = dict(self.snapshot._completion_material())
        for key, value in (("schema", "unknown"), ("resolved_server_profile_id", "foreign"), ("deployment_manifest_base64", material["deployment_manifest_base64"] + "="), ("xtb_runtime_data_manifest_base64", completion.base64.b64encode(b"{}\n").decode())):
            with self.subTest(key=key), self.assertRaises(ValueError):
                completion._validate_material({**material, key: value}, self.resolved())
        with self.assertRaises(ValueError):
            completion._prepare_completion_rendering_material(self.profile(profile_revision=2), self.resolved())

    def test_byte_bundle_missing_or_spliced_stops_replay(self):
        self.execute(); self.publish(); self.collect()
        calls = len(self.driver.calls)
        with patch.object(self.store, "results_for_attempt", return_value=()):
            self.assertEqual(runtime._replay_program_completion(self.store, **self.kwargs()).data["diagnostic"], "evidence-conflict")
        self.assertEqual(len(self.driver.calls), calls)
        with self.assertRaises(TransportBoundaryError):
            runtime._assert_program_receipt_success_authority(self.store, **self.kwargs())

    def test_assessment_transition_crash_reopens_without_reads(self):
        self.execute(); self.publish()
        advance = self.store.advance_attempt
        def crash(attempt, state):
            if state is core.AttemptState.SUCCEEDED:
                raise RuntimeError("synthetic crash after assessment")
            return advance(attempt, state)
        with patch.object(self.store, "advance_attempt", side_effect=crash):
            with self.assertRaises(RuntimeError):
                self.collect()
        self.assertEqual(self.store.attempt_state("attempt-1"), core.AttemptState.SUBMITTED)
        self.store.close()
        self.store = core.SQLiteRuntimeStore(self.database)
        self.addCleanup(self.store.close)
        self.program_transport_store.close()
        self.program_transport_store = transport._ProgramTransportStore.open_existing(self.program_transport_store._path, approved_root=self.program_transport_store._root)
        self.addCleanup(self.program_transport_store.close)
        calls = len(self.driver.calls)
        self.assertEqual(runtime._replay_program_completion(self.store, **self.kwargs()).data["diagnostic"], "completed")
        self.assertEqual(self.store.attempt_state("attempt-1"), core.AttemptState.SUCCEEDED)
        self.assertEqual(len(self.driver.calls), calls)

    def test_bundle_before_assessment_crash_replays(self):
        self.execute(); self.publish()
        with patch.object(runtime, "_persist_completion_assessment", side_effect=RuntimeError("synthetic crash")):
            with self.assertRaises(RuntimeError):
                self.collect()
        self.assertEqual(len(self.store.results_for_attempt("attempt-1")), 1)
        calls = len(self.driver.calls)
        self.assertEqual(runtime._replay_program_completion(self.store, **self.kwargs()).data["diagnostic"], "completed")
        self.assertEqual(len(self.driver.calls), calls)

    def test_restat_identity_drift_overrides_exit(self):
        self.execute(); self.publish(code=5)
        original = self.driver.stat_exact_file
        count = {}
        def changed(request):
            name = request["payload"]["portable_name"]
            count[name] = count.get(name, 0) + 1
            response = original(request)
            if name == "xtb.out" and count[name] == 2:
                return {**response, "file_physical_token": "same-size-new-inode"}
            return response
        self.driver.stat_exact_file = changed
        self.assertEqual(self.collect().data["diagnostic"], "evidence-conflict")

    def test_optional_absence_drift_is_conflict(self):
        self.snapshot = self.completion_snapshot(task="single-point")
        self.scheduler_bytes = {"xtb.pbs": self.snapshot.scheduler_artifacts[0]["content_utf8"].encode()}
        self.execute(); self.driver.outputs.pop("xtbopt.xyz"); self.publish()
        original = self.driver.stat_exact_file
        count = 0
        def changed(request):
            nonlocal count
            if request["payload"]["portable_name"] == "xtbopt.xyz":
                count += 1
                if count == 2:
                    self.driver.outputs["xtbopt.xyz"] = lane.XYZ
            return original(request)
        self.driver.stat_exact_file = changed
        self.assertEqual(self.collect().data["diagnostic"], "evidence-conflict")

    def test_final_query_unknown_is_not_absence(self):
        self.execute(); self.publish()
        original = self.driver.query_scheduler
        count = 0
        def changed(request):
            nonlocal count
            count += 1
            if count == 2:
                self.driver.query_response = {"job_id": "123.server", "state": "unknown"}
            return original(request)
        self.driver.query_scheduler = changed
        self.assertEqual(self.collect().data["diagnostic"], "acquisition-unknown")

    def test_guard_rejects_foreign_token_and_allows_native_sqlite(self):
        with self.assertRaises(TransportBoundaryError):
            runtime._collect_program_completion(self.store, **self.kwargs(), input_bytes=self.input_bytes, _completion_token=object())
        self.execute(); self.publish()
        self.assertEqual(self.collect().data["diagnostic"], "completed")
        self.assertIsNone(self.program_transport_store._completion_owner)
        self.assertFalse(self.program_transport_store._completion_lock.locked())

    def test_wrapper_runtime_dotfiles_and_symlinks(self):
        namespace = {"__name__": "offline_wrapper_fixture"}
        exec(compile(_WRAPPER_SOURCE, "completion-wrapper", "exec"), namespace)
        directory = self.root / "runtime-data"
        directory.mkdir()
        for name in lane.XTB_RUNTIME_DATA_FILES:
            raw = name.encode()
            path = directory / name
            path.write_bytes(raw)
            namespace["file_identity"](str(path), len(raw), sha256(raw).hexdigest())
        link = directory / "linked"
        link.symlink_to(directory / ".param_gfnff.xtb")
        with self.assertRaises(OSError):
            namespace["file_identity"](str(link), 1, "0" * 64)

    def test_wrapper_pinned_parent_chain_rejects_replacement(self):
        namespace = {"__name__": "offline_wrapper_fixture"}
        exec(compile(_WRAPPER_SOURCE, "completion-wrapper", "exec"), namespace)
        directory = self.root / "workspace"
        directory.mkdir()
        fd, token, chain = namespace["pin_directory"](str(directory))
        try:
            directory.rename(self.root / "retained-workspace")
            directory.mkdir()
            with self.assertRaises(ValueError):
                namespace["reattest_directory"](str(directory), token, chain)
            with self.assertRaises(ValueError):
                namespace["publish"](fd, str(directory), token, b"{}\n", chain)
            self.assertEqual(list(directory.iterdir()), [])
            self.assertEqual(list((self.root / "retained-workspace").iterdir()), [])
        finally:
            for descriptor in reversed(chain):
                os.close(descriptor)

    def test_wrapper_waits_adopted_descendants_and_uses_direct_status(self):
        namespace = {"__name__": "offline_wrapper_fixture"}
        exec(compile(_WRAPPER_SOURCE, "completion-wrapper", "exec"), namespace)
        with patch("os.waitpid", side_effect=[(123, 7 << 8), (456, 0), ChildProcessError()] ) as waiting:
            self.assertEqual(namespace["wait_all"](123, namespace["time"].monotonic() + 1), 7 << 8)
            self.assertEqual(waiting.call_count, 3)
        with patch("os.waitpid", return_value=(0, 0)):
            with self.assertRaisesRegex(ValueError, "not-terminated"):
                namespace["wait_all"](123, 0)

    def test_wrapper_prelink_failure_retains_pending_only(self):
        namespace = {"__name__": "offline_wrapper_fixture"}
        exec(compile(_WRAPPER_SOURCE, "completion-wrapper", "exec"), namespace)
        directory = self.root / "publish-failure"
        directory.mkdir()
        fd, token = namespace["directory"](str(directory))
        try:
            with patch("os.link", side_effect=OSError("synthetic link failure")):
                with self.assertRaises(OSError):
                    namespace["publish"](fd, str(directory), token, b"{}\n")
            self.assertTrue((directory / "v31-completion.pending").is_file())
            self.assertFalse((directory / "v31-completion.json").exists())
        finally:
            os.close(fd)

    def test_new_epoch_cannot_replace_accepted_capture(self):
        self.execute(); self.publish(); self.collect()
        self.driver.outputs["xtb.out"] = b"different log\n"
        self.publish()
        self.assertEqual(self.collect().data["diagnostic"], "evidence-conflict")
        with self.assertRaises(TransportBoundaryError):
            runtime._assert_program_receipt_success_authority(self.store, **self.kwargs())

    def test_null_result_unknown_cannot_erase_accepted_capture(self):
        self.execute(); self.publish(); self.collect()
        self.input_bytes = {}
        self.assertEqual(self.collect().data["diagnostic"], "acquisition-unknown")
        self.input_bytes = {"input.xyz": lane.XYZ}
        self.driver.outputs["xtb.out"] = b"different log\n"
        self.publish()
        self.assertEqual(self.collect().data["diagnostic"], "evidence-conflict")

    def test_null_result_unknown_cannot_hide_missing_accepted_bundle(self):
        self.execute(); self.publish(); self.collect()
        self.input_bytes = {}; self.collect()
        calls = len(self.driver.calls)
        with patch.object(self.store, "results_for_attempt", return_value=()):
            self.assertEqual(runtime._replay_program_completion(self.store, **self.kwargs()).data["diagnostic"], "evidence-conflict")
        self.assertEqual(len(self.driver.calls), calls)

    def test_newer_orphan_bundle_after_unknown_is_replayed_without_reads(self):
        self.execute(); self.publish(); self.input_bytes = {}; self.collect()
        self.input_bytes = {"input.xyz": lane.XYZ}
        with patch.object(runtime, "_persist_completion_assessment", side_effect=RuntimeError("synthetic crash")):
            with self.assertRaises(RuntimeError):
                self.collect()
        calls = len(self.driver.calls)
        self.assertEqual(runtime._replay_program_completion(self.store, **self.kwargs()).data["diagnostic"], "completed")
        self.assertEqual(len(self.driver.calls), calls)

    def test_conflict_replay_is_idempotent(self):
        self.execute(); self.publish(); self.collect()
        self.driver.query_response = {"job_id": "123.server", "state": "queued"}
        runtime._query_program_scheduler(self.store, **self.kwargs())
        conflict = runtime._replay_program_completion(self.store, **self.kwargs())
        before = self.store.observations_for_attempt("attempt-1")
        self.assertEqual(runtime._replay_program_completion(self.store, **self.kwargs()), conflict)
        self.assertEqual(self.store.observations_for_attempt("attempt-1"), before)

    def test_boolean_bundle_size_and_missing_assessment_refs_rejected(self):
        self.execute(); self.driver.outputs["xtb.out"] = b"a"; self.publish(); self.collect()
        _base, receipts, job, workspace = runtime._completion_context(self.store, self.snapshot, self.program_transport_store, self.driver)
        record = self.store.results_for_attempt("attempt-1")[0]
        data = json.loads(completion._receipt_json(record.data))
        data["captured_files"][1]["size_bytes"] = True
        altered = core.Result(result_id=runtime.semantic_id("program-completion-evidence", data), attempt_id="attempt-1", result_type=record.result_type, data=data)
        observations = self.store.observations_for_attempt("attempt-1")
        with self.assertRaises((ValueError, TransportBoundaryError)):
            runtime._validate_completion_bundle(altered, self.snapshot, job, workspace, receipts, observations)
        data = {**observations[-1].data, "evidence_observation_ids": ()}
        altered = core.Observation(observation_id=runtime.semantic_id("program-completion-assessment", data), attempt_id="attempt-1", observation_type=runtime._COMPLETION_ASSESSMENT, data=data)
        with self.assertRaisesRegex(TransportBoundaryError, "omits exact"):
            runtime._verify_completion_assessments((*observations[:-1], altered), self.snapshot, job)

    def test_unlock_failure_releases_in_process_guard(self):
        original = fcntl.flock
        def failure(fd, operation):
            original(fd, operation)
            if operation == fcntl.LOCK_UN:
                raise OSError("synthetic unlock failure")
        with patch("fcntl.flock", side_effect=failure):
            with self.assertRaisesRegex(TransportBoundaryError, "unlock failed"):
                with self.program_transport_store._completion_guard():
                    pass
        self.assertFalse(self.program_transport_store._completion_lock.locked())
        self.assertIsNone(self.program_transport_store._completion_owner)
        self.assertTrue(self.program_transport_store._invalid)
        with self.assertRaises(TransportBoundaryError):
            with self.program_transport_store._completion_guard():
                self.fail("uncertain owner reused")

    def test_wrapper_inert_invocation_failure_and_publication_matrix(self):
        """Exercise full wrapper control flow with Popen/wait/subreaper replaced.

        This proves no Linux kernel/host qualification and executes no program.
        """
        namespace = {"__name__": "offline_wrapper_fixture"}
        exec(compile(_WRAPPER_SOURCE, "completion-wrapper", "exec"), namespace)
        python_path = Path(sys.executable).resolve()
        python_raw = python_path.read_bytes()
        for scenario in ("zero", "nonzero", "signal", "launch-failure", "log-replaced", "log-same-bytes-new-inode", "log-missing-after-close"):
            with self.subTest(scenario=scenario):
                workspace = self.root / ("wrapper-" + scenario)
                workspace.mkdir(mode=0o700)
                data_path = workspace / "runtime-data"
                data_path.mkdir()
                for name in lane.XTB_RUNTIME_DATA_FILES:
                    (data_path / name).write_bytes(name.encode())
                executable = workspace / "inert-xtb"
                executable.write_bytes(b"inert synthetic bytes; never executed\n")
                (workspace / "input.xyz").write_bytes(lane.XYZ)
                (workspace / ".auto-g16-v31-submit-intent").write_bytes(completion._receipt_json({"program_execution_snapshot_id": "synthetic-snapshot", "effect_intent_id": "synthetic-intent"}))
                spec = json.loads(completion._receipt_json(self.snapshot.program_execution_spec.semantic_payload()))
                spec["invocation"]["executable_identity"] = {"absolute_path": str(executable), "size_bytes": executable.stat().st_size, "sha256": sha256(executable.read_bytes()).hexdigest()}
                spec["invocation"]["argv"][0] = str(executable)
                material = dict(self.snapshot._completion_material())
                deployment = manifest()
                deployment["trust_roots"]["server_python"].update(path=str(python_path), expected_size_bytes=len(python_raw), expected_sha256=sha256(python_raw).hexdigest())
                material["deployment_manifest_base64"] = completion.base64.b64encode(completion._receipt_json(deployment)).decode()
                fields = {key: value for key, value in self.snapshot._identity_payload.items() if key != "scheduler_artifacts"}
                fields.update(cwd_binding={"location_kind": "server", "path": str(workspace)}, program_execution_spec_payload_sha256=runtime.semantic_sha256(spec))
                binding = completion._prebinding(fields, material)
                config = json.loads(completion._receipt_json({"prebinding": binding, "prebinding_sha256": runtime.semantic_sha256(binding), "spec": spec, "material": material, "xtb_data_path": str(data_path), "cores": 8, "walltime_seconds": 1}))
                self.assertEqual(namespace["semantic"](config["prebinding"]), config["prebinding_sha256"])
                launches = []
                class InertChild:
                    pid = 123
                    returncode = None
                def launch(argv, **kwargs):
                    launches.append((argv, kwargs))
                    self.assertFalse(kwargs["shell"])
                    self.assertEqual(kwargs["env"], {"OMP_NUM_THREADS": "8", "XTBPATH": str(data_path)})
                    if scenario == "launch-failure":
                        raise OSError("synthetic launch failure")
                    os.write(kwargs["stdout"], b"inert program log\n")
                    if scenario in {"log-replaced", "log-same-bytes-new-inode"}:
                        (workspace / "xtb.out").rename(workspace / "original-log")
                        (workspace / "xtb.out").write_bytes(b"inert program log\n" if scenario == "log-same-bytes-new-inode" else b"substitute log\n")
                    return InertChild()
                status = 15 if scenario == "signal" else (7 << 8 if scenario == "nonzero" else 0)
                original_read = namespace["read_name"]
                def read_after_close(parent, name, *args, **kwargs):
                    if scenario == "log-missing-after-close" and name == "xtb.out":
                        (workspace / "xtb.out").rename(workspace / "retained-closed-log")
                    return original_read(parent, name, *args, **kwargs)
                original_cwd = Path.cwd()
                try:
                    with patch.dict(os.environ, {"PBS_JOBID": "123.server"}), patch.object(sys, "executable", str(python_path)), patch.dict(namespace, {"subreaper": lambda: None, "wait_all": lambda pid, deadline: status, "read_name": read_after_close}), patch("subprocess.Popen", side_effect=launch):
                        if scenario in {"launch-failure", "log-replaced", "log-same-bytes-new-inode", "log-missing-after-close"}:
                            with self.assertRaises((OSError, ValueError)):
                                namespace["run"](config)
                            self.assertFalse((workspace / "v31-completion.json").exists())
                        else:
                            self.assertEqual(namespace["run"](config), 143 if scenario == "signal" else 7 if scenario == "nonzero" else 0)
                            receipt = completion._decode_receipt((workspace / "v31-completion.json").read_bytes())
                            self.assertEqual(receipt["termination"]["kind"], "signaled" if scenario == "signal" else "exited")
                            self.assertEqual(receipt["outputs"][1]["presence"], "absent")
                        with self.assertRaises((ValueError, FileExistsError)):
                            namespace["run"](config)
                    self.assertEqual(len(launches), 1)
                finally:
                    os.chdir(original_cwd)

    def test_changed_original_input_bytes_is_conflict_before_reads(self):
        self.execute(); self.publish(); self.input_bytes = {"input.xyz": b"changed"}
        calls = len(self.driver.calls)
        self.assertEqual(self.collect().data["diagnostic"], "evidence-conflict")
        self.assertEqual(len(self.driver.calls), calls)

    def test_fetch_identity_mismatch_is_conflict_before_exit(self):
        self.execute(); self.publish(code=5)
        original = self.driver.fetch_exact_file
        def replaced(request):
            return {**original(request), "file_physical_token": "new-file-object"}
        self.driver.fetch_exact_file = replaced
        self.assertEqual(self.collect().data["diagnostic"], "evidence-conflict")

    def test_final_terminal_contradiction_precedes_awaiting_absence(self):
        self.execute(); self.publish(code=7)
        original = self.driver.query_scheduler
        count = 0
        def changed(request):
            nonlocal count
            count += 1
            if count == 2:
                self.driver.query_response = {"job_id": "123.server", "state": "terminal", "exit_status": 0}
            return original(request)
        self.driver.query_scheduler = changed
        self.assertEqual(self.collect().data["diagnostic"], "evidence-conflict")

    def test_all_receipt_authority_fields_checked_before_returncode(self):
        receipt = self.publish(code=7)
        expected = completion._receipt_binding(self.snapshot, "123.server", "workspace-token-v31")
        for key, value in expected.items():
            if key == "inputs":
                replacement = [*receipt["inputs"], *receipt["inputs"]]
            elif key.endswith("sha256"):
                replacement = "f" * 64 if value != "f" * 64 else "e" * 64
            elif type(value) is int:
                replacement = value + 1
            elif key == "remote_workspace":
                replacement = "/home/user100/SDL/foreign/attempt-1"
            else:
                replacement = "foreign"
            with self.subTest(key=key), self.assertRaises(ValueError):
                completion._bound_receipt(completion._receipt_json({**receipt, key: replacement}), self.snapshot, "123.server", "workspace-token-v31")

    def test_snapshot_review_reopen_uses_only_embedded_material(self):
        from auto_g16.execution.program import _validate_program_review_semantics
        reviewed = self.snapshot._approval_semantics()
        with patch("auto_g16.execution._program_completion.resolve_server_profile", side_effect=AssertionError("no current profile source")):
            self.assertEqual(_validate_program_review_semantics(reviewed), reviewed)
        altered = json.loads(completion._receipt_json(reviewed))
        altered["scheduler_artifacts"][0]["content_utf8"] += "# altered\n"
        with self.assertRaises(ValueError):
            _validate_program_review_semantics(altered)

    def test_strict_consumer_and_historical_collection_reject(self):
        with self.assertRaisesRegex(TransportBoundaryError, "strict consumer"):
            runtime._assert_program_terminal_success_authority(self.store, **self.kwargs(), capture=None)
        with self.assertRaises(TransportBoundaryError):
            runtime._capture_program_outputs(self.store, **self.kwargs())
        strict = self.successor_snapshot()
        with self.assertRaises(TransportBoundaryError):
            runtime._collect_program_completion(self.store, snapshot=strict, program_transport_store=self.program_transport_store, driver=self.driver, input_bytes=self.input_bytes)
        self.assertEqual(self.driver.calls, [])


    def test_wrapper_post_open_enoent_is_not_safe_absence(self):
        namespace = {"__name__": "offline_wrapper_fixture"}
        exec(compile(_WRAPPER_SOURCE, "completion-wrapper", "exec"), namespace)
        directory = self.root / "metadata-failure"
        directory.mkdir()
        (directory / "xtb.out").write_bytes(b"still exists\n")
        fd, _token = namespace["directory"](str(directory))
        try:
            with patch("os.stat", side_effect=FileNotFoundError("synthetic final metadata failure")):
                with self.assertRaises(FileNotFoundError) as error:
                    namespace["read_name"](fd, "xtb.out")
                self.assertNotIsInstance(error.exception, namespace["AbsentFile"])
            self.assertEqual((directory / "xtb.out").read_bytes(), b"still exists\n")
            with self.assertRaises(namespace["AbsentFile"]):
                namespace["read_name"](fd, "not-created")
        finally:
            os.close(fd)

    def test_c4_old_receipt_store_and_strict_v2_reject_before_effects(self):
        legacy = transport._ProgramTransportStore.create_new(self.root / "old.sqlite3", approved_root=self.root)
        self.addCleanup(legacy.close)
        observations = self.store.observations_for_attempt("attempt-1")
        with self.assertRaisesRegex(TransportBoundaryError, "completion-store-not-qualified"):
            runtime._collect_program_completion(self.store, snapshot=self.snapshot, program_transport_store=legacy, driver=self.driver, input_bytes=self.input_bytes)
        with self.assertRaisesRegex(TransportBoundaryError, "completion-store-not-qualified"):
            runtime._snapshot_binding(self.snapshot, legacy, self.driver)
        with self.assertRaisesRegex(TransportBoundaryError, "strict requires"):
            runtime._snapshot_binding(self.successor_snapshot(), self.program_transport_store, self.driver)
        self.assertEqual(self.store.observations_for_attempt("attempt-1"), observations)
        self.assertEqual(self.driver.calls, [])

    def test_c4_drift_during_driver_stops_before_receipt_or_assessment(self):
        self.execute(); self.publish()
        observations = self.store.observations_for_attempt("attempt-1")
        original = self.driver.query_scheduler
        def drift(request):
            response = original(request)
            os.link(self.program_transport_store._path, self.root / "unexpected-hardlink")
            return response
        self.driver.query_scheduler = drift
        with self.assertRaises(TransportBoundaryError):
            self.collect()
        self.assertEqual(self.store.observations_for_attempt("attempt-1"), observations)
        self.assertEqual(self.store.results_for_attempt("attempt-1"), ())
        self.assertEqual(self.store.attempt_state("attempt-1"), core.AttemptState.SUBMITTED)

    def test_c4_drift_after_bundle_keeps_bytes_without_assessment_or_transition(self):
        self.execute(); self.publish()
        original = self.store.append_result
        def append_then_drift(record):
            original(record)
            os.link(self.program_transport_store._path, self.root / "unexpected-hardlink")
        with patch.object(self.store, "append_result", side_effect=append_then_drift):
            with self.assertRaises(TransportBoundaryError):
                self.collect()
        self.assertEqual(len(self.store.results_for_attempt("attempt-1")), 1)
        self.assertFalse(any(o.observation_type == runtime._COMPLETION_ASSESSMENT for o in self.store.observations_for_attempt("attempt-1")))
        self.assertEqual(self.store.attempt_state("attempt-1"), core.AttemptState.SUBMITTED)

    def test_c4_drift_after_assessment_prevents_core_transition(self):
        self.execute(); self.publish()
        original = self.store.append_observation
        def append_then_drift(record):
            original(record)
            if record.observation_type == runtime._COMPLETION_ASSESSMENT:
                os.link(self.program_transport_store._path, self.root / "unexpected-hardlink")
        with patch.object(self.store, "append_observation", side_effect=append_then_drift):
            with self.assertRaises(TransportBoundaryError):
                self.collect()
        self.assertEqual(len(self.store.results_for_attempt("attempt-1")), 1)
        self.assertTrue(any(o.observation_type == runtime._COMPLETION_ASSESSMENT for o in self.store.observations_for_attempt("attempt-1")))
        self.assertEqual(self.store.attempt_state("attempt-1"), core.AttemptState.SUBMITTED)

    def test_c4_reconcile_drift_cannot_advance_unknown(self):
        self.driver.raise_operation = ("SUBMIT_QSUB_ONCE", transport._ProgramEffectUnknown("synthetic uncertain submission"))
        self.execute()
        self.assertEqual(self.store.attempt_state("attempt-1"), core.AttemptState.UNKNOWN)
        self.driver.raise_operation = None
        self.driver.reconcile_response = {"outcome": "SUCCEEDED", "job_id": "999.server"}
        original = runtime._append_receipt
        def append_then_drift(*args, **kwargs):
            record = original(*args, **kwargs)
            if kwargs["operation"] == "RECONCILE_SUBMISSION":
                os.link(self.program_transport_store._path, self.root / "unexpected-hardlink")
            return record
        with patch.object(runtime, "_append_receipt", side_effect=append_then_drift):
            with self.assertRaises(TransportBoundaryError):
                runtime._reconcile_program_submission(self.store, **self.kwargs())
        self.assertEqual(self.store.attempt_state("attempt-1"), core.AttemptState.UNKNOWN)
        self.assertEqual(self.store.observations_for_attempt("attempt-1")[-1].data["operation"], "RECONCILE_SUBMISSION")

    def test_closeout_receipt_nested_closed_grammar_and_limits(self):
        valid = self.publish()
        clone = lambda value: json.loads(completion._receipt_json(value))
        cases = []
        for location in ((), ("termination",), ("inputs", 0), ("outputs", 0)):
            target = valid
            for key in location:
                target = target[key]
            for key in target:
                altered = clone(valid); node = altered
                for part in location:
                    node = node[part]
                del node[key]
                cases.append((str(location) + " missing " + key, altered))
            altered = clone(valid); node = altered
            for part in location:
                node = node[part]
            node["unexpected"] = 1
            cases.append((str(location) + " extra", altered))
        for location, key, values in (
            ((), "wrapper_source_size_bytes", (True, 1.5, 0, 67108865)),
            (("inputs", 0), "size_bytes", (False, 1.5, 0, 67108865)),
            (("outputs", 0), "size_bytes", (True, 1.5, -1, 67108865, None)),
            (("termination",), "returncode", (True, 1.5, -1, 256, None)),
            (("termination",), "signal", (1, True)),
            ((), "finished_at", ("2026-02-30T01:02:03.000004Z", "2026-09-14T01:02:03Z", "2026-09-14T01:02:03.000004+00:00", 1)),
            (("outputs", 0), "presence", (None, "unknown", True)),
            (("outputs", 0), "sha256", (None, "x", "A" * 64)),
            (("inputs", 0), "portable_name", ("../input.xyz", "v31-completion.json", "bad name")),
        ):
            for value in values:
                altered = clone(valid); node = altered
                for part in location:
                    node = node[part]
                node[key] = value
                cases.append((str((location, key, value)), altered))
        for termination in ({"kind":"signaled","returncode":0,"signal":15}, {"kind":"signaled","returncode":None,"signal":0}, {"kind":"signaled","returncode":None,"signal":65}, {"kind":"signaled","returncode":None,"signal":True}, {"kind":"unknown","returncode":0,"signal":None}):
            cases.append((str(termination), {**valid, "termination":termination}))
        altered=clone(valid); altered["outputs"][0]["presence"]="absent"
        cases.append(("absent has content", altered))
        for name, altered in cases:
            with self.subTest(case=name), self.assertRaises(ValueError):
                completion._decode_receipt(completion._receipt_json(altered))
        raw = completion._receipt_json(valid)
        for token in (b'"kind":', b'"logical_role":', b'"presence":'):
            duplicate = raw.replace(token, token + b'"duplicate",' + token, 1)
            with self.subTest(duplicate=token), self.assertRaises(ValueError):
                completion._decode_receipt(duplicate)
        for raw in (b"\xff", b"\x00", b"x" * 65537, b"", completion._receipt_json(valid).replace(b'"returncode":0', b'"returncode":0.0')):
            with self.subTest(raw=raw[:30]), self.assertRaises(ValueError):
                completion._decode_receipt(raw)

    def test_closeout_receipt_inventory_order_scope_and_output_caps(self):
        valid = self.publish()
        clone = lambda: json.loads(completion._receipt_json(valid))
        cases = []
        for inventory in ("inputs", "outputs"):
            for values in ([], [*valid[inventory], valid[inventory][0]], valid[inventory][:-1]):
                altered=clone(); altered[inventory]=values; cases.append(altered)
        altered=clone(); altered["outputs"].reverse(); cases.append(altered)
        altered=clone(); altered["outputs"][0]["size_bytes"]=self.snapshot.program_execution_spec.required_outputs[0]["max_size_bytes"]+1; cases.append(altered)
        # Grammar may express multiple unique inputs; the concrete adapter cannot.
        extra={**valid["inputs"][0],"logical_role":"second-input","portable_name":"second.xyz"}
        multi={**valid,"inputs":[*valid["inputs"],extra]}
        self.assertEqual(len(completion._decode_receipt(completion._receipt_json(multi))["inputs"]),2)
        cases.append(multi)
        for altered in cases:
            with self.subTest(inventory=altered), self.assertRaises(ValueError):
                completion._bound_receipt(completion._receipt_json(altered), self.snapshot, "123.server", "workspace-token-v31")

    def test_closeout_operation_output_shape_vectors(self):
        for log in (b"", b"\xff", b"log\x00"):
            self.assertEqual(completion._output_closure("optimize",lane.XYZ,{"xtb.out":log,"xtbopt.xyz":lane.XYZ}),"output-invalid")
        for geometry in (b"0\ncomment\n", b"1\ncomment\nC nan 0 0\n", b"1\ncomment\nC inf 0 0\n", b"1\ncomment\nC 0 0 0 extra\n", b"1\ncomment\nUnknown 0 0 0\n", b"1\ncomment\nC 0 0 0\ntrailing\n", b"2\ncomment\nC 0 0 0\n", b"1\ncomment\nHe 0 0 0\n"):
            with self.subTest(geometry=geometry):
                self.assertEqual(completion._output_closure("optimize",lane.XYZ,{"xtb.out":b"log","xtbopt.xyz":geometry}),"output-invalid")
        self.assertIsNone(completion._output_closure("single-point",lane.XYZ,{"xtb.out":b"log","xtbopt.xyz":None}))
        self.assertEqual(completion._output_closure("optimize",lane.XYZ,{"xtb.out":b"log","xtbopt.xyz":None}),"output-incomplete")
        with self.assertRaises(ValueError):
            completion._output_closure("optimize",lane.XYZ,{"xtb.out":b"log","xtbopt.xyz":lane.XYZ,"extra":b"x"})

    def test_closeout_material_dag_and_nested_manifest_mismatch(self):
        import shlex
        artifact=self.snapshot.scheduler_artifacts[0]
        script=artifact["content_utf8"]
        argv=shlex.split(script[script.index("exec "):])
        self.assertEqual(argv[2:6],["-I","-S","-B","-c"])
        self.assertEqual(argv[6],_WRAPPER_SOURCE)
        config=json.loads(completion.base64.b64decode(argv[-1]))
        fields={k:v for k,v in self.snapshot._identity_payload.items() if k!="scheduler_artifacts"}
        expected={**fields, "binding_schema":"v31-completion-prebinding/2", "wrapper_source_sha256":sha256(_WRAPPER_SOURCE.encode()).hexdigest(), "wrapper_source_size_bytes":len(_WRAPPER_SOURCE.encode()), "rendering_material_sha256":runtime.semantic_sha256(self.snapshot._completion_material())}
        self.assertEqual(config["prebinding"],json.loads(completion._receipt_json(expected)))
        self.assertEqual(config["prebinding_sha256"],runtime.semantic_sha256(expected))
        self.assertEqual(expected["rendering_material_sha256"],runtime.semantic_sha256(config["material"]))
        self.assertEqual(artifact["sha256"],sha256(script.encode()).hexdigest())
        self.snapshot.assert_identity_closed()
        lines=script.splitlines(); relocated=[*lines[:2],lines[3],lines[2],*lines[4:]]
        with self.assertRaises(ValueError):
            completion._material_from_artifact(({"content_utf8":"\n".join(relocated)+"\n"},),self.resolved())
        material=dict(self.snapshot._completion_material())
        for key in material:
            altered={k:v for k,v in material.items() if k!=key}
            with self.subTest(missing=key),self.assertRaises(ValueError):completion._validate_material(altered,self.resolved())
        with self.assertRaises(ValueError):completion._validate_material({**material,"extra":1},self.resolved())
        for field,value in (("platform","windows"),("attestation_mode","unsupported"),("extra",1)):
            deployment=manifest(); deployment["trust_roots"]["server_python"][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):completion._deployment_projection(completion._receipt_json(deployment))
        for field in ("path","platform","attestation_mode","expected_sha256","expected_size_bytes"):
            deployment=manifest();del deployment["trust_roots"]["server_python"][field]
            with self.subTest(missing=field),self.assertRaises(ValueError):completion._deployment_projection(completion._receipt_json(deployment))
        for name in ("deployment_manifest_base64","xtb_runtime_data_manifest_base64"):
            content=completion.base64.b64decode(material[name])
            for changed in (content+b" ", bytes([content[0]^1])+content[1:]):
                with self.subTest(name=name,changed=changed[:10]),self.assertRaises(ValueError):
                    completion._validate_material({**material,name:completion.base64.b64encode(changed).decode()},self.resolved())
        namespace={"__name__":"inert_binding"};exec(compile(_WRAPPER_SOURCE,"wrapper","exec"),namespace)
        for changed in ({**config,"prebinding_sha256":"0"*64},{**config,"material":{**config["material"],"schema":"wrong"}}):
            with patch("subprocess.Popen",side_effect=AssertionError("no launch")),self.assertRaises(ValueError):namespace["run"](changed)

    def test_closeout_scheduler_state_and_terminal_priority_table(self):
        def observation(state,code=None,index=0,outcome="SUCCEEDED"):
            response={"state":state,"job_id":"123.server"}
            if code is not None:response["exit_status"]=code
            return core.Observation(observation_id="synthetic-query-"+str(index),attempt_id="attempt-1",observation_type=runtime._transport._RECEIPT_TYPE,data={"operation":"QUERY_SCHEDULER","outcome":outcome,"response":response})
        for state in ("queued","running","held","exiting"):
            self.assertEqual(runtime._scheduler_diagnostic((observation(state),)),"scheduler-active")
        self.assertEqual(runtime._scheduler_diagnostic((observation("terminal",0),)),"awaiting-absence")
        self.assertEqual(runtime._scheduler_diagnostic((observation("unknown"),)),"acquisition-unknown")
        self.assertIsNone(runtime._scheduler_diagnostic((observation("absent"),)))
        self.assertEqual(runtime._scheduler_diagnostic((observation("absent",outcome="UNKNOWN"),)),"acquisition-unknown")
        for sequence in ((observation("terminal",0),observation("terminal",7,1)),(observation("terminal",0),observation("running",index=1)),(observation("terminal",index=0),observation("absent",index=1))):
            self.assertEqual(runtime._scheduler_diagnostic(sequence),"evidence-conflict")
        self.assertIsNone(runtime._scheduler_diagnostic((observation("terminal",0),observation("terminal",0,1),observation("absent",index=2)),0))
        self.assertEqual(runtime._scheduler_diagnostic((observation("terminal",0),observation("absent",index=1)),7),"evidence-conflict")

    def test_closeout_proof_epoch_prefix_bytes_and_order(self):
        self.execute(); self.publish(finished_at="2099-12-31T23:59:59.000001Z"); assessment=self.collect()
        proof=runtime._assert_program_receipt_success_authority(self.store,**self.kwargs())
        keys={"schema","attempt_id","program_execution_snapshot_id","effect_intent_id","job_authority_id","completion_mode","epoch_id","evidence_result_id","capture_authority_id","receipt_sha256","observation_prefix_sha256","assessment_observation_id","initial_absence_observation_id","final_absence_observation_id","program_terminal_success_authority_id"}
        self.assertEqual(set(proof),keys)
        payload={k:v for k,v in proof.items() if k!="program_terminal_success_authority_id"}
        self.assertEqual(proof["program_terminal_success_authority_id"],runtime.semantic_id("program-terminal-success-authority",payload))
        observations=self.store.observations_for_attempt("attempt-1")
        prefix=observations[:observations.index(assessment)]
        raw_prefix=tuple({"observation_id":o.observation_id,"attempt_id":o.attempt_id,"observation_type":o.observation_type,"data":o.data} for o in prefix)
        self.assertEqual(proof["observation_prefix_sha256"],runtime.semantic_sha256(raw_prefix))
        epoch={k:proof[k] for k in ("attempt_id","program_execution_snapshot_id","effect_intent_id","job_authority_id","initial_absence_observation_id")}
        self.assertEqual(proof["epoch_id"],runtime.semantic_id("program-completion-epoch",epoch))
        self.assertLess([o.observation_id for o in prefix].index(proof["initial_absence_observation_id"]),[o.observation_id for o in prefix].index(proof["final_absence_observation_id"]))
        _base,receipts,job,workspace=runtime._completion_context(self.store,self.snapshot,self.program_transport_store,self.driver)
        record=self.store.results_for_attempt("attempt-1")[0]
        self.assertEqual(proof["evidence_result_id"],record.result_id)
        self.assertEqual(proof["assessment_observation_id"],assessment.observation_id)
        self.assertEqual(proof["capture_authority_id"],assessment.data["capture_authority_id"])
        self.assertEqual(proof["receipt_sha256"],record.data["captured_files"][0]["sha256"])
        for field in ("attempt_id","program_execution_snapshot_id","effect_intent_id","job_authority_id","epoch_id","completion_mode"):
            self.assertEqual(proof[field],assessment.data[field])
        for field,value in (("epoch_id","foreign"),("attempt_id","foreign")):
            altered=core.Result(result_id=record.result_id,attempt_id=record.attempt_id,result_type=record.result_type,data={**record.data,field:value})
            with self.subTest(field=field),self.assertRaises(ValueError):runtime._validate_completion_bundle(altered,self.snapshot,job,workspace,receipts,prefix)
        for field in ("stat_observation_id","fetch_observation_id","restat_observation_id"):
            data=json.loads(completion._receipt_json(record.data));data["captured_files"][0][field]="foreign"
            altered=core.Result(result_id=runtime.semantic_id("program-completion-evidence",data),attempt_id="attempt-1",result_type=record.result_type,data=data)
            with self.subTest(field=field),self.assertRaises(ValueError):runtime._validate_completion_bundle(altered,self.snapshot,job,workspace,receipts,prefix)
        with self.assertRaises(ValueError):runtime._verify_completion_assessments(tuple(reversed(observations)),self.snapshot,job)
        later=self.publish(finished_at="2000-01-01T00:00:00.000001Z")
        self.assertEqual(later["finished_at"],"2000-01-01T00:00:00.000001Z")
        self.assertEqual(self.collect().data["diagnostic"],"evidence-conflict")

    def test_closeout_corrupt_and_spliced_durable_bytes_block_replay(self):
        for kind in ("bit-flip","cross-member"):
            with self.subTest(kind=kind):
                fixture=CompletionTests(methodName="test_success_durable_bundle_and_zero_read_replay");fixture.setUp()
                try:
                    fixture.execute();fixture.publish();fixture.collect()
                    original=fixture.store.results_for_attempt("attempt-1")[0]
                    observations=fixture.store.observations_for_attempt("attempt-1")
                    _base,receipts,job,workspace=runtime._completion_context(fixture.store,fixture.snapshot,fixture.program_transport_store,fixture.driver)
                    data=json.loads(completion._receipt_json(original.data));files=data["captured_files"]
                    raw=completion.base64.b64decode(files[0]["content_base64"])
                    changed=bytes([raw[0]^1])+raw[1:] if kind=="bit-flip" else completion.base64.b64decode(files[1]["content_base64"])
                    files[0].update(content_base64=completion.base64.b64encode(changed).decode(),sha256=sha256(changed).hexdigest(),size_bytes=len(changed))
                    forged=core.Result(result_id=runtime.semantic_id("program-completion-evidence",data),attempt_id=original.attempt_id,result_type=original.result_type,data=data)
                    with self.assertRaises(ValueError):runtime._validate_completion_bundle(forged,fixture.snapshot,job,workspace,receipts,observations)
                    calls=len(fixture.driver.calls)
                    with patch.object(fixture.store,"results_for_attempt",return_value=(forged,)):
                        self.assertEqual(runtime._replay_program_completion(fixture.store,**fixture.kwargs()).data["diagnostic"],"evidence-conflict")
                        with self.assertRaises(ValueError):runtime._assert_program_receipt_success_authority(fixture.store,**fixture.kwargs())
                    self.assertEqual(len(fixture.driver.calls),calls)
                finally:fixture.doCleanups()

    def test_closeout_result_append_failure_keeps_attempt_unfinished(self):
        self.execute();self.publish()
        with patch.object(self.store,"append_result",side_effect=RuntimeError("inert append failure")):
            self.assertEqual(self.collect().data["verdict"],"UNKNOWN")
        self.assertEqual(self.store.results_for_attempt("attempt-1"),())
        self.assertEqual(self.store.attempt_state("attempt-1"),core.AttemptState.SUBMITTED)
        self.assertEqual(sum(op=="SUBMIT_QSUB_ONCE" for op,_ in self.driver.calls),1)

    def test_closeout_result_readback_failure_and_same_id_conflict(self):
        self.execute();self.publish()
        original=self.store.results_for_attempt
        def unavailable(attempt):
            values=original(attempt)
            return () if values else values
        with patch.object(self.store,"results_for_attempt",side_effect=unavailable):
            self.assertEqual(self.collect().data["verdict"],"UNKNOWN")
        self.assertEqual(self.store.attempt_state("attempt-1"),core.AttemptState.SUBMITTED)
        record=original("attempt-1")[0]
        with self.assertRaises(core.RuntimeStoreError):
            self.store.append_result(core.Result(result_id=record.result_id,attempt_id=record.attempt_id,result_type=record.result_type,data={**record.data,"epoch_id":"conflict"}))
        self.assertEqual(original("attempt-1"),(record,))

    def test_closeout_after_transition_crash_replay_is_idempotent(self):
        self.execute();self.publish()
        advance=self.store.advance_attempt
        def advance_then_crash(*args):
            advance(*args)
            raise RuntimeError("inert crash after transition")
        with patch.object(self.store,"advance_attempt",side_effect=advance_then_crash):
            with self.assertRaises(RuntimeError):self.collect()
        before=self.store.observations_for_attempt("attempt-1");calls=len(self.driver.calls)
        self.store.close();self.store=core.SQLiteRuntimeStore(self.database);self.addCleanup(self.store.close)
        self.program_transport_store.close()
        self.program_transport_store=transport._ProgramTransportStore.open_existing(self.program_transport_store._path,approved_root=self.program_transport_store._root);self.addCleanup(self.program_transport_store.close)
        self.assertEqual(runtime._replay_program_completion(self.store,**self.kwargs()).data["verdict"],"SUCCEEDED")
        self.assertEqual(self.store.observations_for_attempt("attempt-1"),before)
        self.assertEqual(len(self.driver.calls),calls)
        self.assertEqual(sum(op=="SUBMIT_QSUB_ONCE" for op,_ in self.driver.calls),1)

    def test_closeout_overlapping_collections_have_one_winner(self):
        self.execute();self.publish()
        entered,release=threading.Event(),threading.Event()
        original=self.driver.query_scheduler;results=[];errors=[]
        def blocked(request):
            entered.set()
            if not release.wait(10):raise RuntimeError("inert rendezvous expired")
            return original(request)
        def winner():
            local = core.SQLiteRuntimeStore(self.database)
            try:
                results.append(runtime._collect_program_completion(local, **self.kwargs(), input_bytes=self.input_bytes))
            except BaseException as exc:
                errors.append(exc)
            finally:
                local.close()
        with patch.object(self.driver,"query_scheduler",side_effect=blocked):
            thread=threading.Thread(target=winner);thread.start()
            self.assertTrue(entered.wait(10), repr(errors))
            before=self.store.observations_for_attempt("attempt-1");calls=len(self.driver.calls)
            try:
                with self.assertRaises(TransportBoundaryError):self.collect()
                self.assertEqual(self.store.observations_for_attempt("attempt-1"),before)
                self.assertEqual(len(self.driver.calls),calls)
            finally:release.set();thread.join(10)
        self.assertFalse(thread.is_alive());self.assertEqual(errors,[])
        self.assertEqual([r.data["verdict"] for r in results],["SUCCEEDED"])
        self.assertEqual(len(self.store.results_for_attempt("attempt-1")),1)


    def test_closeout_wrapper_identity_infrastructure_and_link_faults(self):
        """Inert Popen/wait/subreaper model; no real Linux qualification."""
        from types import SimpleNamespace
        scenarios = ("marker-malformed", "input-mismatch", "input-symlink", "executable-mismatch", "existing-lock", "existing-final", "existing-pending", "existing-log", "wait-error", "log-fsync", "log-close", "log-hash", "python-replaced", "executable-replaced", "input-replaced", "marker-replaced", "runtime-replaced", "pending-corruption", "before-link", "after-link")
        for scenario in scenarios:
            with self.subTest(scenario=scenario):
                namespace={"__name__":"inert_closeout"};exec(compile(_WRAPPER_SOURCE,"wrapper","exec"),namespace)
                workspace=self.root/("closeout-"+scenario);workspace.mkdir()
                data=workspace/"data";data.mkdir()
                for name in lane.XTB_RUNTIME_DATA_FILES:(data/name).write_bytes(name.encode())
                executable=workspace/"inert-program";executable.write_bytes(b"never executed\n")
                (workspace/"input.xyz").write_bytes(lane.XYZ)
                marker=workspace/".auto-g16-v31-submit-intent";marker.write_bytes(completion._receipt_json({"program_execution_snapshot_id":"synthetic","effect_intent_id":"synthetic"}))
                python_path=Path(sys.executable).resolve();python_raw=python_path.read_bytes()
                spec=json.loads(completion._receipt_json(self.snapshot.program_execution_spec.semantic_payload()))
                spec["invocation"]["executable_identity"]={"absolute_path":str(executable),"size_bytes":executable.stat().st_size,"sha256":sha256(executable.read_bytes()).hexdigest()};spec["invocation"]["argv"][0]=str(executable)
                material=dict(self.snapshot._completion_material());deployment=manifest()
                deployment["trust_roots"]["server_python"].update(path=str(python_path),expected_size_bytes=len(python_raw),expected_sha256=sha256(python_raw).hexdigest())
                material["deployment_manifest_base64"]=completion.base64.b64encode(completion._receipt_json(deployment)).decode()
                fields={k:v for k,v in self.snapshot._identity_payload.items() if k!="scheduler_artifacts"}
                fields.update(cwd_binding={"location_kind":"server","path":str(workspace)},program_execution_spec_payload_sha256=runtime.semantic_sha256(spec))
                binding=completion._prebinding(fields,material)
                config=json.loads(completion._receipt_json({"prebinding":binding,"prebinding_sha256":runtime.semantic_sha256(binding),"spec":spec,"material":material,"xtb_data_path":str(data),"cores":8,"walltime_seconds":1}))
                preexisting={"existing-lock":"v31-completion-launch.lock","existing-final":"v31-completion.json","existing-pending":"v31-completion.pending","existing-log":"xtb.out"}
                if scenario in preexisting:(workspace/preexisting[scenario]).write_bytes(b"retained original\n")
                if scenario=="marker-malformed":marker.write_bytes(b'{}\n')
                if scenario=="input-mismatch":(workspace/"input.xyz").write_bytes(b"changed")
                if scenario=="input-symlink":
                    (workspace/"input.xyz").rename(workspace/"retained-input");(workspace/"input.xyz").symlink_to(workspace/"retained-input")
                if scenario=="executable-mismatch":executable.write_bytes(b"wrong executable bytes")
                state={"launches":0,"logfd":None,"close_failed":False,"hash_phase":False}
                def launch(*args,**kwargs):
                    state["launches"]+=1;state["logfd"]=kwargs["stdout"];os.write(kwargs["stdout"],b"inert log\n")
                    target={"executable-replaced":executable,"input-replaced":workspace/"input.xyz","marker-replaced":marker,"runtime-replaced":data/lane.XTB_RUNTIME_DATA_FILES[0]}.get(scenario)
                    if target is not None:
                        raw=target.read_bytes();target.rename(target.with_name(target.name+".retained"));target.write_bytes(raw)
                    return SimpleNamespace(pid=123,returncode=None)
                real_close,real_fsync,real_link=os.close,os.fsync,os.link
                real_identity,real_read,real_exclusive=namespace["file_identity"],namespace["read_name"],namespace["exclusive"]
                def close(fd):
                    if scenario=="log-close" and fd==state["logfd"] and not state["close_failed"]:
                        state["close_failed"]=True;raise OSError("inert log close failure")
                    return real_close(fd)
                def fsync(fd):
                    if scenario=="log-fsync" and fd==state["logfd"]:raise OSError("inert log fsync failure")
                    return real_fsync(fd)
                def wait(pid,deadline):
                    if scenario=="wait-error":raise OSError("inert wait failure")
                    return 0
                def identity(path,*args):
                    result=real_identity(path,*args)
                    if scenario=="python-replaced" and state["launches"] and path==str(python_path):
                        return ([*result[0][:1],result[0][1]+1,*result[0][2:]],result[1])
                    return result
                def read(parent,name,*args,**kwargs):
                    result=real_read(parent,name,*args,**kwargs)
                    if scenario=="log-hash" and name=="xtb.out":state["hash_phase"]=True
                    return result
                def hash_bytes(raw):
                    if state["hash_phase"]:raise OSError("inert hash failure")
                    return sha256(raw)
                def exclusive(parent,name,raw):
                    result=real_exclusive(parent,name,raw)
                    if scenario=="pending-corruption" and name=="v31-completion.pending":
                        with (workspace/name).open("ab") as stream:stream.write(b"corrupt")
                    return result
                def link(*args,**kwargs):
                    if scenario=="before-link":raise OSError("inert pre-link crash")
                    result=real_link(*args,**kwargs)
                    if scenario=="after-link":raise OSError("inert post-link crash")
                    return result
                cwd=Path.cwd()
                try:
                    with patch.dict(os.environ,{"PBS_JOBID":"123.server"}),patch.object(sys,"executable",str(python_path)),patch.dict(namespace,{"subreaper":lambda:None,"wait_all":wait,"file_identity":identity,"read_name":read,"exclusive":exclusive,"hashlib":SimpleNamespace(sha256=hash_bytes)}),patch("subprocess.Popen",side_effect=launch),patch("os.close",side_effect=close),patch("os.fsync",side_effect=fsync),patch("os.link",side_effect=link):
                        with self.assertRaises((OSError,ValueError)):namespace["run"](config)
                    final=workspace/"v31-completion.json"
                    if scenario=="after-link":
                        self.assertEqual(completion._decode_receipt(final.read_bytes())["termination"]["returncode"],0)
                        self.assertEqual(final.stat().st_ino,(workspace/"v31-completion.pending").stat().st_ino)
                    elif scenario!="existing-final":self.assertFalse(final.exists())
                    if scenario in preexisting:self.assertEqual((workspace/preexisting[scenario]).read_bytes(),b"retained original\n")
                    early=scenario in preexisting or scenario in ("marker-malformed","input-mismatch","input-symlink","executable-mismatch")
                    self.assertEqual(state["launches"],0 if early else 1)
                finally:os.chdir(cwd)

    def test_closeout_expanded_review_and_old_version_mode_rejection(self):
        reviewed=self.snapshot._approval_semantics()
        self.assertEqual(reviewed["program_execution_spec"]["program_data"]["completion_mode"],completion._MODE)
        self.assertEqual(reviewed["program_execution_spec"],self.snapshot.program_execution_spec.semantic_payload())
        self.assertEqual(reviewed["resolved_resource_request"],self.snapshot.resolved_resource_request.semantic_payload())
        self.assertEqual(reviewed["workspace_binding"],self.snapshot.workspace_binding.semantic_payload())
        self.assertEqual(reviewed["scheduler_artifacts"],self.snapshot.scheduler_artifacts)
        old_data={"model":"gfn2","search_mode":"ttconf","preset":"normal","charge":0,"unpaired_electrons":0,"energy_window_millikcal_per_mol":6000,"rmsd_threshold_milliangstrom":500,"temperature_millikelvin":298150,"random_seed":17}
        executable={"absolute_path":lane.CREST_EXECUTABLE_PATH,"size_bytes":len(lane.CREST_EXECUTABLE_BYTES),"sha256":sha256(lane.CREST_EXECUTABLE_BYTES).hexdigest()}
        invocation,required,optional=adapter._ADAPTER_REGISTRY[("crest","auto-g16-v31-crest",1)][3](executable,"seed.xyz",old_data)
        crest_v1=execution.ProgramExecutionSpec._from_closed(program_kind="crest",adapter_id="auto-g16-v31-crest",adapter_contract_version=1,exact_inputs=self.crest_spec().exact_inputs,program_data=old_data,invocation=invocation,required_outputs=required,optional_outputs=optional)
        for spec in (self.xtb_v1_spec(),self.xtb_spec(),crest_v1,self.crest_spec()):
            values=dict(spec.semantic_payload());values.pop("program_execution_spec_id")
            values["program_data"]={**values["program_data"],"completion_mode":completion._MODE}
            with self.subTest(kind=spec.program_kind,version=spec.adapter_contract_version),self.assertRaises(ValueError):
                execution.ProgramExecutionSpec._from_closed(**values)
        from auto_g16 import approval
        confirmation=approval.ExactOperationalConfirmation.for_snapshot(self.store,self.snapshot,confirmer_id="offline-closeout",confirmer_evidence={})
        different_input=adapter._prepare_program_execution_spec(program_kind="xtb",executable_path=lane.XTB_EXECUTABLE_PATH,executable_size_bytes=len(lane.XTB_EXECUTABLE_BYTES),executable_sha256=sha256(lane.XTB_EXECUTABLE_BYTES).hexdigest(),input_name="input.xyz",input_bytes=lane.XYZ.replace(b"0.74",b"0.75"),program_data=self.xtb_data(),resolved_profile=self.resolved(),completion_mode=completion._MODE)
        different_resources=execution.ResolvedResourceRequest(resource_spec=self.store.load_resource_spec("resource-1"),cores=4,memory_mb=6144,walltime_seconds=1800,queue="simple")
        parent=self.local_root/"different-local-parent";parent.mkdir()
        different_workspace=execution.WorkspaceBinding(project=self.store.load_project("project-1"),attempt_id="attempt-1",local_approved_root=str(self.local_root),local_attempt_dir=str(parent/"attempt-1"),rtwin_approved_root=r"C:\RTWIN",rtwin_attempt_dir=r"C:\RTWIN\project-1\attempt-1",remote_approved_root=execution.LEGACY_REMOTE_ROOT,remote_attempt_dir="/home/user100/SDL/project-1/attempt-1")
        changes=[self.successor_snapshot(),self.completion_snapshot(task="single-point")]
        for spec,resources,workspace in ((different_input,self.resources(),self.workspace()),(self.completion_spec(),different_resources,self.workspace()),(self.completion_spec(),self.resources(),different_workspace)):
            changes.append(self.snapshot_service.prepare(self.store,attempt_id="attempt-1",calculation_plan_id="plan-1",resource_spec_id="resource-1",program_execution_spec=spec,project_physical_binding=self.physical_binding(),resolved_resource_request=resources,resolved_server_profile=self.resolved(),workspace_binding=workspace,completion_rendering_material=completion._prepare_completion_rendering_material(self.profile(),self.resolved())))
        self.assertEqual(len({snapshot.program_execution_snapshot_id for snapshot in changes}),5)
        for changed in changes:
            with self.subTest(snapshot=changed.program_execution_snapshot_id),patch.object(self.store,"record_submission_intent") as claim:
                with self.assertRaises(approval.ApprovalError):confirmation.assert_current(self.store,changed)
                claim.assert_not_called()
        self.assertEqual(self.driver.calls,[])

    def test_closeout_fresh_v2_cannot_import_existing_job_authority(self):
        self.execute();self.publish();before=self.store.observations_for_attempt("attempt-1");calls=len(self.driver.calls)
        fresh=transport._ProgramTransportStore._create_completion_store(self.root/"transport"/"fresh.sqlite3",approved_root=self.root/"transport");self.addCleanup(fresh.close)
        with self.assertRaises(TransportBoundaryError):
            runtime._collect_program_completion(self.store,snapshot=self.snapshot,program_transport_store=fresh,driver=self.driver,input_bytes=self.input_bytes)
        self.assertEqual(self.store.observations_for_attempt("attempt-1"),before)
        self.assertEqual(self.driver.calls[calls:],[])
        self.assertEqual(self.store.results_for_attempt("attempt-1"),())

    def test_closeout_assessment_append_failure_reopens_durable_bundle(self):
        self.execute();self.publish();append=self.store.append_observation
        def fail_assessment(observation):
            if observation.observation_type==runtime._COMPLETION_ASSESSMENT:raise RuntimeError("inert assessment append failure")
            return append(observation)
        with patch.object(self.store,"append_observation",side_effect=fail_assessment):
            with self.assertRaises(RuntimeError):self.collect()
        self.assertEqual(self.store.attempt_state("attempt-1"),core.AttemptState.SUBMITTED)
        self.assertEqual(len(self.store.results_for_attempt("attempt-1")),1)
        self.store.close();self.store=core.SQLiteRuntimeStore(self.database);self.addCleanup(self.store.close)
        path,root=self.program_transport_store._path,self.program_transport_store._root
        self.program_transport_store.close();self.program_transport_store=transport._ProgramTransportStore.open_existing(path,approved_root=root);self.addCleanup(self.program_transport_store.close)
        calls=len(self.driver.calls)
        self.assertEqual(runtime._replay_program_completion(self.store,**self.kwargs()).data["verdict"],"SUCCEEDED")
        self.assertEqual(len(self.driver.calls),calls)
        self.assertEqual(sum(op=="SUBMIT_QSUB_ONCE" for op,_ in self.driver.calls),1)

    def test_closeout_assessment_readback_failure_prevents_transition(self):
        self.execute();self.publish();observations=self.store.observations_for_attempt
        def missing_assessment(attempt):
            return tuple(o for o in observations(attempt) if o.observation_type!=runtime._COMPLETION_ASSESSMENT)
        with patch.object(self.store,"observations_for_attempt",side_effect=missing_assessment):
            with self.assertRaises(TransportBoundaryError):self.collect()
        self.assertEqual(self.store.attempt_state("attempt-1"),core.AttemptState.SUBMITTED)
        self.assertEqual(len(self.store.results_for_attempt("attempt-1")),1)
        self.assertEqual(sum(o.observation_type==runtime._COMPLETION_ASSESSMENT for o in observations("attempt-1")),1)
        calls=len(self.driver.calls)
        self.assertEqual(runtime._replay_program_completion(self.store,**self.kwargs()).data["verdict"],"SUCCEEDED")
        self.assertEqual(len(self.driver.calls),calls)

    def test_closeout_same_result_id_conflict_during_collection_never_advances(self):
        self.execute();self.publish();append=self.store.append_result
        def conflicting(record):
            append(core.Result(result_id=record.result_id,attempt_id=record.attempt_id,result_type=record.result_type,data={**record.data,"epoch_id":"foreign"}))
            return append(record)
        with patch.object(self.store,"append_result",side_effect=conflicting):
            self.assertEqual(self.collect().data["diagnostic"],"evidence-conflict")
        self.assertEqual(self.store.attempt_state("attempt-1"),core.AttemptState.SUBMITTED)
        self.assertEqual(self.store.results_for_attempt("attempt-1")[0].data["epoch_id"],"foreign")
        self.assertEqual(sum(op=="SUBMIT_QSUB_ONCE" for op,_ in self.driver.calls),1)

    def test_closeout_manifest_root_inventory_nested_duplicates_and_data_list(self):
        original=manifest()
        for name in original["trust_roots"]:
            value=json.loads(completion._receipt_json(original));del value["trust_roots"][name]
            with self.subTest(missing_root=name),self.assertRaises(ValueError):completion._deployment_projection(completion._receipt_json(value))
        value=json.loads(completion._receipt_json(original));value["trust_roots"]["extra"]=value["trust_roots"]["server_python"]
        with self.assertRaises(ValueError):completion._deployment_projection(completion._receipt_json(value))
        raw=completion._receipt_json(original)
        for token in (b'"trust_roots":',b'"server_python":',b'"platform":'):
            with self.subTest(token=token),self.assertRaises(ValueError):completion._deployment_projection(raw.replace(token,token+b'null,'+token,1))
        valid=json.loads(completion.base64.b64decode(self.snapshot._completion_material()["xtb_runtime_data_manifest_base64"]))
        for scenario in ("missing","extra"):
            value=json.loads(completion._receipt_json(valid));name=next(iter(value["files"]))
            if scenario=="missing":del value["files"][name]
            else:value["files"]["unexpected-parameters"]=value["files"][name]
            raw=completion._receipt_json(value)
            if scenario=="missing":
                with self.assertRaises(ValueError):completion._canonical_xtb_runtime_data_manifest(raw)
            else:
                # The legacy data grammar permits additional pinned files; changing
                # the reviewed inventory still must fail its profile identity.
                self.assertIn("unexpected-parameters",json.loads(completion._canonical_xtb_runtime_data_manifest(raw))["files"])
            material={**self.snapshot._completion_material(),"xtb_runtime_data_manifest_base64":completion.base64.b64encode(raw).decode()}
            with self.subTest(scenario=scenario),self.assertRaises(ValueError):completion._validate_material(material,self.resolved())

    def test_closeout_capture_drift_and_signal_scheduler_subconditions(self):
        for scenario in ("receipt-restat","required-absence","same-size-cross-file","signal-agrees","signal-disagrees","terminal-after-opening"):
            with self.subTest(scenario=scenario):
                fixture=CompletionTests(methodName="test_success_durable_bundle_and_zero_read_replay")
                fixture.setUp()
                try:
                    fixture.execute()
                    if scenario=="required-absence":fixture.driver.outputs.pop("xtbopt.xyz")
                    fixture.publish(signal=15 if scenario.startswith("signal-") else None)
                    original_stat=fixture.driver.stat_exact_file;original_query=fixture.driver.query_scheduler
                    counts={};queries=[]
                    def stat(request):
                        name=request["payload"]["portable_name"];counts[name]=counts.get(name,0)+1
                        result=original_stat(request)
                        # The stock driver uses a constant token. Model the metadata
                        # change a qualified file owner observes after the write.
                        if scenario=="same-size-cross-file" and name=="xtb.out" and counts[name]==2:
                            return {**result,"file_physical_token":"same-inode-new-mtime-ctime"}
                        if scenario=="receipt-restat" and name=="v31-completion.json" and counts[name]==2:return {**result,"file_physical_token":"replaced-receipt"}
                        if scenario=="required-absence" and name=="xtbopt.xyz" and counts[name]==2:
                            fixture.driver.outputs[name]=lane.XYZ;return original_stat(request)
                        if scenario=="same-size-cross-file" and name=="xtbopt.xyz" and counts[name]==1:
                            old=fixture.driver.outputs["xtb.out"];fixture.driver.outputs["xtb.out"]=bytes([old[0]^1])+old[1:]
                        return result
                    def query(request):
                        queries.append(True)
                        return original_query(request)
                    fixture.driver.stat_exact_file=stat
                    if scenario.startswith("signal-"):
                        fixture.driver.query_response={"job_id":"123.server","state":"terminal","exit_status":143 if scenario=="signal-agrees" else 0}
                        runtime._query_program_scheduler(fixture.store,**fixture.kwargs())
                        fixture.driver.query_response={"job_id":"123.server","state":"absent"}
                    if scenario=="terminal-after-opening":
                        def query(request):
                            queries.append(True)
                            if len(queries)==2:fixture.driver.query_response={"job_id":"123.server","state":"terminal","exit_status":0}
                            return original_query(request)
                        fixture.driver.query_scheduler=query
                    assessment=fixture.collect()
                    expected="program-signaled" if scenario=="signal-agrees" else "awaiting-absence" if scenario=="terminal-after-opening" else "evidence-conflict"
                    self.assertEqual(assessment.data["diagnostic"],expected)
                    self.assertEqual(sum(op=="SUBMIT_QSUB_ONCE" for op,_ in fixture.driver.calls),1)
                    self.assertEqual(fixture.store.load_attempt("attempt-1").ordinal,1)
                    if scenario!="signal-agrees":self.assertEqual(fixture.store.attempt_state("attempt-1"),core.AttemptState.SUBMITTED)
                finally:fixture.doCleanups()

    def test_closeout_same_assessment_id_conflict_never_advances(self):
        self.execute();self.publish();append=self.store.append_observation
        def conflict(observation):
            if observation.observation_type==runtime._COMPLETION_ASSESSMENT:
                append(core.Observation(observation_id=observation.observation_id,attempt_id=observation.attempt_id,observation_type=observation.observation_type,data={**observation.data,"diagnostic":"foreign"}))
            return append(observation)
        with patch.object(self.store,"append_observation",side_effect=conflict):
            with self.assertRaises(core.RuntimeStoreError):self.collect()
        self.assertEqual(self.store.attempt_state("attempt-1"),core.AttemptState.SUBMITTED)
        self.assertEqual(len(self.store.results_for_attempt("attempt-1")),1)
        self.assertEqual(sum(op=="SUBMIT_QSUB_ONCE" for op,_ in self.driver.calls),1)



    def test_supplement_pending_same_bytes_new_inode_rejected(self):
        from auto_g16.execution._program_completion_wrapper import _WRAPPER_SOURCE
        namespace = {'__name__': 'inert_pending_supplement'}
        exec(compile(_WRAPPER_SOURCE, 'reviewed-wrapper', 'exec'), namespace)
        workspace = self.root / 'pending-inode-window'
        workspace.mkdir()
        parent, token, chain = namespace['pin_directory'](str(workspace))
        original_read = namespace['read_name']
        reads = []
        raw = b'{"synthetic":"pending identity only"}\n'
        def read(parent_fd, name, *args, **kwargs):
            value = original_read(parent_fd, name, *args, **kwargs)
            if name == 'v31-completion.pending':
                reads.append(value[1])
                if len(reads) == 1:
                    # Keep the old object and recreate the exact same bytes under
                    # the pending name after the first trusted read, before re-read.
                    os.rename(name, 'retained-original.pending', src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
                    namespace['exclusive'](parent_fd, name, value[0])
                    self.assertNotEqual(value[1][:2], namespace['identity'](os.stat(name, dir_fd=parent_fd, follow_symlinks=False))[:2])
            return value
        try:
            with patch.dict(namespace, {'read_name': read}), patch('os.link', wraps=os.link) as linked:
                with self.assertRaisesRegex(ValueError, 'receipt-replaced'):
                    namespace['publish'](parent, str(workspace), token, raw, chain)
                self.assertEqual(linked.call_count, 0)
            self.assertEqual(len(reads), 2)
            self.assertEqual((workspace / 'v31-completion.pending').read_bytes(), raw)
            self.assertEqual((workspace / 'retained-original.pending').read_bytes(), raw)
            self.assertFalse((workspace / 'v31-completion.json').exists())
        finally:
            for fd in reversed(chain):
                os.close(fd)

    def test_supplement_actual_inert_wrapper_process_death(self):
        """Real Darwin wrapper-process death; subreaper and scientific launch modeled."""
        for phase in ('after-inert-launch', 'before-link', 'after-link', 'writer-reaped-before-link'):
            with self.subTest(phase=phase):
                workspace = self.root / ('actual-inert-death-' + phase)
                workspace.mkdir()
                config = _supplement_wrapper_config(self, workspace)
                config_path = workspace / 'inert-config.json'
                config_path.write_bytes(completion._receipt_json(config))
                # Qualified current interpreter, exact known repository/module path.
                # No inherited program-store handles survive the exec boundary.
                child = subprocess.Popen([str(Path(sys.executable).resolve()), '-c', _SUPPLEMENT_WRAPPER_CHILD, str(config_path), phase],
                                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                         cwd=Path(__file__).resolve().parents[3])
                try:
                    self.assertTrue(select.select([child.stdout], [], [], 8)[0], 'child never reached the death checkpoint')
                    message = json.loads(child.stdout.readline())
                    expected = {'phase':phase,'launches':1,'pid':child.pid}
                    if phase == 'writer-reaped-before-link':
                        expected.update(writer_reaped=True,writer_returncode=0)
                    self.assertEqual(message, expected)
                    self.assertIsNone(child.poll())
                    final, pending = workspace / 'v31-completion.json', workspace / 'v31-completion.pending'
                    before = {p.name:(p.read_bytes(),p.stat().st_dev,p.stat().st_ino) for p in workspace.iterdir() if p.is_file()}
                    self.assertIn('v31-completion-launch.lock', before)
                    self.assertIn('xtb.out', before)
                    if phase == 'after-inert-launch':
                        self.assertFalse(pending.exists())
                        self.assertFalse(final.exists())
                    elif phase in ('before-link', 'writer-reaped-before-link'):
                        self.assertTrue(pending.is_file())
                        self.assertFalse(final.exists())
                        completion._decode_receipt(pending.read_bytes())
                    else:
                        self.assertEqual(final.read_bytes(), pending.read_bytes())
                        self.assertEqual((final.stat().st_dev, final.stat().st_ino), (pending.stat().st_dev, pending.stat().st_ino))
                        completion._decode_receipt(final.read_bytes())
                    # Only this directly owned child is signaled. Never a group,
                    # process-name search, fake pid 123, scheduler or scientific job.
                    child.send_signal(signal.SIGKILL)
                    remaining, errors = child.communicate(timeout=5)
                    self.assertEqual(child.returncode, -signal.SIGKILL)
                    self.assertEqual(remaining, b'')
                    self.assertEqual(errors, b'')
                    after = {p.name:(p.read_bytes(),p.stat().st_dev,p.stat().st_ino) for p in workspace.iterdir() if p.is_file()}
                    self.assertEqual(after, before)
                    self.assertEqual(final.exists(), phase == 'after-link')
                finally:
                    if child.poll() is None:
                        # Cleanup of this test-owned child on assertion failure only.
                        child.kill()
                    child.communicate(timeout=5)
                    for pipe in (child.stdin, child.stdout, child.stderr):
                        pipe.close()

    def test_supplement_historical_source_four_version_golden_bytes_and_ids(self):
        from auto_g16.execution import models
        encoded = completion._receipt_json
        raw=(Path(__file__).parents[2]/"fixtures"/"v31"/"historical-spec-snapshot-goldens.json").read_bytes()
        self.assertEqual(sha256(raw).hexdigest(),"d83e1f247223b8c49915859f1cadfa4cebe114dcfc6055e5aebd41ef73ff93ba")
        golden=json.loads(raw)
        self.assertEqual(golden["source_commit"],"6b2ece4443951381f0206c93e55e581ca175dd5e")
        self.assertEqual([r["name"] for r in golden["records"]],["xtb-v1","xtb-v2","crest-v1","crest-v2"])
        for record in golden["records"]:
            with self.subTest(version=record["name"]):
                payload=dict(adapter.freeze_mapping(record["spec"],"historical synthetic spec"));payload.pop("program_execution_spec_id")
                spec=execution.ProgramExecutionSpec._from_closed(**payload)
                self.assertEqual(spec.program_execution_spec_id,record["spec_id"])
                self.assertEqual(encoded(spec.semantic_payload()),encoded(record["spec"]))
                self.assertEqual(sha256(encoded(spec.semantic_payload())).hexdigest(),record["spec_bytes_sha256"])
                with patch.object(models,"require_local_workspace_anchor",side_effect=AssertionError("golden replay must not claim fresh filesystem authority")):
                    replay=adapter._validate_program_review_semantics(record["expanded_snapshot"])
                self.assertEqual(encoded(replay),encoded(record["expanded_snapshot"]))
                self.assertEqual(sha256(encoded(replay)).hexdigest(),record["expanded_snapshot_bytes_sha256"])
                self.assertEqual(replay["program_execution_snapshot_id"],record["snapshot_id"])
                self.assertEqual(replay["effect_intent_id"],record["effect_intent_id"])
                self.assertEqual(replay["program_execution_spec"]["program_execution_spec_id"],record["spec_id"])


class NativeCompletionStoreTests(unittest.TestCase):
    """Real OS ownership, unmodified SQLite; never a remote driver."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.path = self.root / "program.sqlite3"
        self.owner = transport._ProgramTransportStore._create_completion_store(self.path, approved_root=self.root)
        self.addCleanup(self.owner.close)

    def subprocess_open(self, path=None, root=None):
        code = """
import sys
from auto_g16.transport.program import _ProgramTransportStore
from auto_g16.transport._canonical import TransportBoundaryError
try:
    value = _ProgramTransportStore.open_existing(sys.argv[1], approved_root=sys.argv[2])
    with value._completion_guard():
        value._connection.execute('SELECT * FROM program_transport_meta').fetchall()
    value.close()
    print('acquired')
except TransportBoundaryError:
    print('rejected')
"""
        result = subprocess.run([sys.executable, "-c", code, str(path or self.path), str(root or self.root)], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def test_native_cross_process_and_same_parent_ownership(self):
        other = transport._ProgramTransportStore.open_existing(self.path, approved_root=self.root)
        self.addCleanup(other.close)
        sibling = transport._ProgramTransportStore._create_completion_store(self.root / "sibling.sqlite3", approved_root=self.root)
        self.addCleanup(sibling.close)
        with self.owner._completion_guard() as token:
            self.assertEqual(self.subprocess_open(), "rejected")
            for candidate in (other, sibling):
                with self.assertRaises(TransportBoundaryError):
                    with candidate._completion_guard():
                        self.fail("contender entered")
            with self.assertRaises(TransportBoundaryError):
                other.attest_runtime(program_execution_snapshot_id="snapshot", resolved_server_profile_id="profile", qualification=composition._Driver().runtime_qualification)
            self.owner._require_completion_guard(token)
            self.assertFalse(os.get_inheritable(self.owner._completion_owner[3]))
        self.assertEqual(self.subprocess_open(), "acquired")

    def test_native_threads_foreign_tokens_and_close_lifecycle(self):
        other = transport._ProgramTransportStore.open_existing(self.path, approved_root=self.root)
        with self.owner._completion_guard() as token:
            errors = []
            def contender():
                for operation in (lambda: self.owner._require_completion_guard(token), self.owner.close, lambda: self.owner.attest_runtime(program_execution_snapshot_id="s", resolved_server_profile_id="p", qualification=composition._Driver().runtime_qualification)):
                    try:
                        operation()
                    except TransportBoundaryError:
                        errors.append(True)
            thread = threading.Thread(target=contender)
            thread.start(); thread.join(10)
            self.assertFalse(thread.is_alive())
            self.assertEqual(errors, [True, True, True])
            other.close()
            fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
            os.close(fd)
            self.assertEqual(self.subprocess_open(), "rejected")
            with self.assertRaises(TransportBoundaryError):
                self.owner.close()
            with self.assertRaises(TransportBoundaryError):
                other._require_completion_guard(token)
        with self.assertRaises(TransportBoundaryError):
            self.owner._require_completion_guard(token)
        self.assertEqual(self.subprocess_open(), "acquired")

    def test_separate_parent_progress_and_strict_open_unchanged(self):
        strict_path = self.root / "strict.sqlite3"
        strict = transport._ProgramTransportStore.create_new(strict_path, approved_root=self.root)
        strict_id = strict.program_transport_store_id
        strict.close()
        separate_root = self.root / "separate"
        separate_root.mkdir()
        separate = transport._ProgramTransportStore._create_completion_store(separate_root / "program.sqlite3", approved_root=self.root)
        self.addCleanup(separate.close)
        with self.owner._completion_guard():
            reopened = transport._ProgramTransportStore.open_existing(strict_path, approved_root=self.root)
            self.assertEqual(reopened.program_transport_store_id, strict_id)
            reopened.close()
            with separate._completion_guard():
                separate._attest()

    def test_no_create_retry_or_existing_target_overwrite(self):
        before = self.path.read_bytes()
        with self.assertRaises((TransportBoundaryError, OSError)):
            transport._ProgramTransportStore._create_completion_store(self.path, approved_root=self.root)
        self.assertEqual(self.path.read_bytes(), before)
        incomplete = self.root / "incomplete.sqlite3"
        with patch.object(transport._ProgramTransportStore, "_create_schema", side_effect=RuntimeError("inert initialization crash")):
            with self.assertRaisesRegex(RuntimeError, "initialization crash"):
                transport._ProgramTransportStore._create_completion_store(incomplete, approved_root=self.root)
        self.assertTrue(incomplete.is_file())
        with self.assertRaises(TransportBoundaryError):
            transport._ProgramTransportStore.open_existing(incomplete, approved_root=self.root)
        with self.assertRaises((TransportBoundaryError, OSError)):
            transport._ProgramTransportStore._create_completion_store(incomplete, approved_root=self.root)

    def test_schema_binding_is_closed_and_append_only(self):
        row = self.owner._connection.execute("SELECT * FROM program_transport_meta").fetchone()
        self.assertEqual(len(row), 10)
        self.assertEqual(row[-1], transport.canonical_bytes(self.owner._guard_binding))
        self.assertEqual(self.owner._connection.execute("PRAGMA user_version").fetchone()[0], 2)
        with self.assertRaises(sqlite3.IntegrityError):
            self.owner._connection.execute("UPDATE program_transport_meta SET completion_guard_binding=?", (b"wrong",))
        for raw in (b"wrong", transport.canonical_bytes({**self.owner._guard_binding, "extra": 1}), transport.canonical_bytes({**self.owner._guard_binding, "component_identities": [[True, 1]]})):
            directory = self.root / str(len(list(self.root.iterdir())))
            directory.mkdir()
            path = directory / "bad.sqlite3"
            bad = transport._ProgramTransportStore._create_completion_store(path, approved_root=directory)
            bad.close()
            with sqlite3.connect(path) as database:
                database.execute("DROP TRIGGER program_transport_meta_no_update")
                database.execute("UPDATE program_transport_meta SET completion_guard_binding=?", (raw,))
                database.execute(dict(transport._PROGRAM_STORE_TRIGGERS)["program_transport_meta_no_update"])
            database.close()
            with self.assertRaises(TransportBoundaryError):
                transport._ProgramTransportStore.open_existing(path, approved_root=directory)

    def test_hardlink_copy_and_lexical_alias_rejected(self):
        alias = self.root / "alias.sqlite3"
        os.link(self.path, alias)
        with self.assertRaises(TransportBoundaryError):
            with self.owner._completion_guard():
                self.fail("hardlinked database accepted")
        self.assertEqual(self.subprocess_open(alias), "rejected")
        copied = self.root / "copy.sqlite3"
        copied.write_bytes(self.path.read_bytes())
        self.assertEqual(self.subprocess_open(copied), "rejected")
        self.assertEqual(self.subprocess_open(str(self.root) + "/./program.sqlite3"), "rejected")

    def test_persistent_parent_anchor_rejects_same_inode_relocation(self):
        parent = self.root / "parent"
        parent.mkdir()
        path = parent / "program.sqlite3"
        bound = transport._ProgramTransportStore._create_completion_store(path, approved_root=self.root)
        self.addCleanup(bound.close)
        with self.assertRaises(TransportBoundaryError), bound._completion_guard():
            parent.rename(self.root / "retained-parent")
            parent.mkdir()
            (self.root / "retained-parent" / "program.sqlite3").rename(path)
            self.assertEqual(self.subprocess_open(path, self.root), "rejected")
            with self.assertRaises(TransportBoundaryError):
                bound._require_current_completion_owner()
            # Final guard attestation also rejects; preserve the invalidated owner.

    @unittest.skipUnless(hasattr(os, "fork"), "native fork unavailable")
    def test_fork_child_rejects_inherited_handles_before_locks(self):
        read_fd, write_fd = os.pipe()
        with self.owner._completion_guard():
            with self.owner._lock:
                pid = os.fork()
                if pid == 0:
                    try:
                        os.close(read_fd)
                        rejected = 0
                        for operation in (
                            self.owner.close, self.owner._attest, self.owner._require_current_completion_owner,
                            lambda: transport._ProgramTransportStore.create_new(self.root / "child-v1.sqlite3", approved_root=self.root),
                            lambda: transport._ProgramTransportStore._create_completion_store(self.root / "child-v2.sqlite3", approved_root=self.root),
                            lambda: transport._ProgramTransportStore.open_existing(self.path, approved_root=self.root),
                        ):
                            try:
                                operation()
                            except TransportBoundaryError:
                                rejected += 1
                        os.write(write_fd, str(rejected).encode())
                    finally:
                        os._exit(0)
                os.close(write_fd)
                self.assertEqual(os.read(read_fd, 8), b"6")
                os.close(read_fd)
                self.assertEqual(os.waitpid(pid, 0)[1], 0)
                self.assertFalse((self.root / "child-v1.sqlite3").exists())
                self.assertFalse((self.root / "child-v2.sqlite3").exists())
                self.assertEqual(self.subprocess_open(), "rejected")
        self.assertEqual(self.subprocess_open(), "acquired")

    @unittest.skipUnless(hasattr(os, "fork"), "native fork unavailable")
    def test_abrupt_owner_exit_with_living_fork_child_releases_lock(self):
        code = """
import os,sys,json
from auto_g16.transport.program import _ProgramTransportStore
value = _ProgramTransportStore.open_existing(sys.argv[1], approved_root=sys.argv[2])
with value._completion_guard():
    r,w = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(r)
        os.write(w,b'ready')
        os.close(w)
        os.read(int(sys.argv[3]),1)
        os._exit(0)
    os.close(w)
    assert os.read(r,5)==b'ready'
    os.close(r)
    os.close(int(sys.argv[3]))
    print(json.dumps({'child_pid':pid}),flush=True)
    sys.stdin.read(1)
    os._exit(77)
"""
        read_fd, write_fd = os.pipe()
        holder = subprocess.Popen([sys.executable, "-c", code, str(self.path), str(self.root), str(read_fd)], pass_fds=(read_fd,), stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        os.close(read_fd)
        try:
            child = json.loads(holder.stdout.readline())["child_pid"]
            self.assertEqual(self.subprocess_open(), "rejected")
            holder.stdin.write("x"); holder.stdin.flush()
            self.assertEqual(holder.wait(timeout=10), 77)
            os.kill(child, 0)
            self.assertEqual(self.subprocess_open(), "acquired")
        finally:
            os.write(write_fd, b"x"); os.close(write_fd)
            holder.stdin.close(); holder.stdout.close()


    @unittest.skipUnless(hasattr(os, "fork"), "native fork unavailable")
    def test_real_exec_restores_fork_child_store_open(self):
        code = """
import sys
from auto_g16.transport.program import _ProgramTransportStore
from auto_g16.transport._canonical import TransportBoundaryError
try:
    value=_ProgramTransportStore.open_existing(sys.argv[1],approved_root=sys.argv[2])
    value.close()
    print('acquired',flush=True)
except TransportBoundaryError:
    print('rejected',flush=True)
"""
        def fork_exec():
            read_fd, write_fd = os.pipe()
            pid = os.fork()
            if pid == 0:
                try:
                    os.close(read_fd)
                    os.dup2(write_fd, 1)
                    os.close(write_fd)
                    os.execv(sys.executable, [sys.executable, "-c", code, str(self.path), str(self.root)])
                finally:
                    os._exit(91)
            os.close(write_fd)
            result = os.read(read_fd, 100)
            os.close(read_fd)
            self.assertEqual(os.waitpid(pid, 0)[1], 0)
            return result.strip()
        with self.owner._completion_guard():
            self.assertEqual(fork_exec(), b"rejected")
        self.assertEqual(fork_exec(), b"acquired")

    def test_close_admission_race_rechecks_after_lock(self):
        original = self.owner._lock
        entered, proceed = threading.Event(), threading.Event()
        errors = []
        class AdmissionLock:
            def __enter__(inner):
                if threading.current_thread().name == "inert-close-contender":
                    entered.set()
                    if not proceed.wait(10):
                        raise AssertionError("test rendezvous timed out")
                original.acquire()
                return inner
            def __exit__(inner, *args):
                original.release()
        def close_contender():
            try:
                self.owner.close()
            except TransportBoundaryError:
                errors.append(True)
        with patch.object(self.owner, "_lock", AdmissionLock()):
            thread = threading.Thread(target=close_contender, name="inert-close-contender")
            thread.start()
            self.assertTrue(entered.wait(10))
            with self.owner._completion_guard():
                proceed.set(); thread.join(10)
                self.assertFalse(thread.is_alive())
                self.assertEqual(errors, [True])
                self.assertFalse(self.owner._closed)
        self.owner._attest()

    def test_factory_teardown_failure_closes_connection_and_keeps_artifact(self):
        captured = []
        original_open = transport._ProgramTransportStore._open
        original_flock = fcntl.flock
        def observe(*args, **kwargs):
            value = original_open(*args, **kwargs)
            captured.append(value)
            return value
        def fail_unlock(fd, operation):
            original_flock(fd, operation)
            if operation == fcntl.LOCK_UN:
                raise OSError("inert release failure")
        fresh = self.root / "retained.sqlite3"
        with patch.object(transport._ProgramTransportStore, "_open", side_effect=observe), patch("fcntl.flock", side_effect=fail_unlock):
            with self.assertRaises(TransportBoundaryError):
                transport._ProgramTransportStore._create_completion_store(fresh, approved_root=self.root)
        self.assertTrue(fresh.exists())
        self.assertTrue(captured and all(value._closed for value in captured))
        captured.clear()
        with patch.object(transport._ProgramTransportStore, "_open", side_effect=observe), patch("fcntl.flock", side_effect=fail_unlock):
            with self.assertRaises(TransportBoundaryError):
                transport._ProgramTransportStore.open_existing(fresh, approved_root=self.root)
        self.assertTrue(captured and all(value._closed for value in captured))

    def test_ancestor_symlink_and_replacement_are_not_rebound(self):
        ancestor = self.root / "ancestor"
        parent = ancestor / "parent"
        parent.mkdir(parents=True)
        path = parent / "program.sqlite3"
        value = transport._ProgramTransportStore._create_completion_store(path, approved_root=self.root)
        self.addCleanup(value.close)
        saved = self.root / "retained-ancestor"
        ancestor.rename(saved)
        ancestor.symlink_to(saved, target_is_directory=True)
        with self.assertRaises(TransportBoundaryError):
            transport._ProgramTransportStore.open_existing(path, approved_root=self.root)
        with self.assertRaises(TransportBoundaryError):
            with value._completion_guard():
                self.fail("symlink ancestor entered")
        alias = str(saved / "parent" / "program.sqlite3")
        self.assertEqual(self.subprocess_open(alias, self.root), "rejected")

    def test_closeout_nested_owner_and_same_descriptor_relock(self):
        with self.owner._completion_guard() as token:
            descriptor = self.owner._completion_owner[3]
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual(self.subprocess_open(), "rejected")
            for supplied in (None, object()):
                with self.assertRaises(TransportBoundaryError):
                    self.owner._require_completion_guard(supplied)
            with self.assertRaises(TransportBoundaryError):
                with self.owner._completion_guard():
                    self.fail("nested admission")
            self.owner._require_completion_guard(token)
        self.assertEqual(self.subprocess_open(), "acquired")
        with self.assertRaises(TransportBoundaryError):
            self.owner._require_completion_guard(token)

    def test_closeout_full_schema_and_independent_v2_identity(self):
        from uuid import UUID, uuid5
        definitions = dict(self.owner._connection.execute("SELECT name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"))
        tables = ("program_transport_meta", "program_runtime_attestation", "program_effect_physical_authority")
        expected_names = {*tables, *(table + "_no_" + verb for table in tables for verb in ("update", "delete"))}
        self.assertEqual(set(definitions), expected_names)
        self.assertEqual([r[1] for r in self.owner._connection.execute("PRAGMA table_info(program_transport_meta)")], ["singleton", "schema_identity", "program_transport_store_id", "store_instance_id", "creation_nonce", "approved_store_root", "approved_store_path", "store_device", "store_inode", "completion_guard_binding"])
        for table in tables:
            for verb in ("update", "delete"):
                self.assertEqual(definitions[table + "_no_" + verb], f"CREATE TRIGGER {table}_no_{verb} BEFORE {verb.upper()} ON {table} BEGIN SELECT RAISE(ABORT,'append-only'); END")
        row = self.owner._connection.execute("SELECT * FROM program_transport_meta").fetchone()
        ordered = [definitions[t] for t in tables] + [definitions[t + "_no_" + v] for t in tables for v in ("update", "delete")]
        self.assertEqual(row[1], transport.canonical_bytes(ordered))
        self.assertEqual(self.owner._connection.execute("PRAGMA application_id").fetchone()[0], 1093879637)
        def identifier(domain, payload):
            ns = uuid5(UUID("a51f091c-dfd0-59b6-bf26-86a505a5cb43"), "auto-g16-v31-program-effect/1/" + domain)
            return str(uuid5(ns, transport.canonical_bytes(payload).decode("ascii")))
        payload = {"schema":"auto-g16-v31-program-transport-store/2", "approved_store_root":str(self.root), "approved_store_path":str(self.path)}
        store_id = identifier("program-transport-store", payload)
        self.assertEqual(row[2], store_id)
        expected = {**payload, "program_transport_store_id":store_id, "creation_nonce_sha256":sha256(row[4]).hexdigest(), "store_device":self.path.stat().st_dev, "store_inode":self.path.stat().st_ino, "completion_guard_binding_sha256":sha256(row[9]).hexdigest()}
        self.assertEqual(row[3], identifier("program-transport-store-instance", expected))
        binding = self.owner._guard_binding
        self.assertEqual(set(binding), {"schema", "lock_directory", "component_identities"})
        components = [Path("/"), *reversed(list(self.root.parents)[:-1]), self.root]
        self.assertEqual(binding["component_identities"], [[p.stat().st_dev,p.stat().st_ino] for p in components])
        qualification = self.owner.attest_runtime(program_execution_snapshot_id="synthetic-snapshot", resolved_server_profile_id="synthetic-profile", qualification=composition._Driver().runtime_qualification)
        raw = self.owner._connection.execute("SELECT payload FROM program_runtime_attestation WHERE runtime_attestation_id=?", (qualification,)).fetchone()[0]
        payload = {"schema":"auto-g16-v31-program-transport-store/2", "program_transport_store_id":store_id, "store_instance_id":row[3], "program_execution_snapshot_id":"synthetic-snapshot", "resolved_server_profile_id":"synthetic-profile", "protocol":"auto-g16-v31-program-effect/1", "operation_table_sha256":transport._OPERATION_TABLE_SHA256, "qualified_runtime":composition._Driver().runtime_qualification}
        self.assertEqual(raw, transport.canonical_bytes(payload))
        self.assertEqual(qualification, identifier("program-runtime-attestation", payload))

    def test_closeout_schema_meta_and_chain_corruption_fail_closed(self):
        cases = [("user_version", 3), ("application_id", 0), ("missing-table", None), ("changed-ddl", None), ("schema_identity", b"wrong"), ("creation_nonce", b"x"*32), ("program_transport_store_id", "foreign"), ("store_instance_id", "foreign"), ("chain-order", None), ("chain-length", None)]
        for index, (field, value) in enumerate(cases):
            with self.subTest(field=field):
                directory=self.root/str(index);directory.mkdir();path=directory/"store.sqlite3"
                owner=transport._ProgramTransportStore._create_completion_store(path,approved_root=directory)
                binding=dict(owner._guard_binding);owner.close()
                with sqlite3.connect(path) as database:
                    if field in ("user_version","application_id"):
                        database.execute("PRAGMA " + field + "=" + str(value))
                    elif field == "missing-table":
                        database.execute("DROP TABLE program_effect_physical_authority")
                    elif field == "changed-ddl":
                        database.execute("ALTER TABLE program_runtime_attestation ADD COLUMN unexpected TEXT")
                    else:
                        if field.startswith("chain-"):
                            chain=binding["component_identities"]
                            binding["component_identities"]=list(reversed(chain)) if field=="chain-order" else chain[:-1]
                            field="completion_guard_binding";value=transport.canonical_bytes(binding)
                        database.execute("DROP TRIGGER program_transport_meta_no_update")
                        database.execute("UPDATE program_transport_meta SET " + field + "=?",(value,))
                        database.execute(dict(transport._PROGRAM_STORE_TRIGGERS)["program_transport_meta_no_update"])
                database.close()
                with self.assertRaises(TransportBoundaryError):
                    transport._ProgramTransportStore.open_existing(path,approved_root=directory)
                self.assertTrue(path.exists())

    def test_closeout_root_escape_and_original_path_database_replacement(self):
        outside=self.root.parent/(self.root.name+"-outside.sqlite3")
        with self.assertRaises(TransportBoundaryError):
            transport._ProgramTransportStore._create_completion_store(outside,approved_root=self.root)
        self.assertFalse(outside.exists())
        raw=self.path.read_bytes();self.path.rename(self.root/"retained-original.sqlite3");self.path.write_bytes(raw)
        with self.assertRaises(TransportBoundaryError):
            with self.owner._completion_guard():
                self.fail("replacement admitted")
        self.assertEqual(self.subprocess_open(),"rejected")
        self.assertEqual(self.path.read_bytes(),raw)

    def test_closeout_drift_between_connect_and_authority_closes_connection(self):
        parent=self.root/"parent";parent.mkdir();path=parent/"store.sqlite3"
        owner=transport._ProgramTransportStore._create_completion_store(path,approved_root=self.root);owner.close()
        original=transport._ProgramTransportStore._open;captured=[]
        def drift(*args,**kwargs):
            value=original(*args,**kwargs);captured.append(value)
            retained=self.root/"retained-parent";parent.rename(retained);parent.mkdir();(retained/path.name).rename(path)
            return value
        with patch.object(transport._ProgramTransportStore,"_open",side_effect=drift):
            with self.assertRaises(TransportBoundaryError):
                transport._ProgramTransportStore.open_existing(path,approved_root=self.root)
        self.assertEqual(len(captured),1);self.assertTrue(captured[0]._closed)
        with self.assertRaises(sqlite3.ProgrammingError):captured[0]._connection.execute("SELECT 1")
        self.assertTrue(path.exists())

    @unittest.skipUnless(hasattr(os,"fork"),"native fork unavailable")
    def test_closeout_fork_rejects_before_other_thread_owned_rlock(self):
        entered,release=threading.Event(),threading.Event()
        def holder():
            with self.owner._lock:
                entered.set();release.wait(10)
        thread=threading.Thread(target=holder);thread.start()
        self.assertTrue(entered.wait(10))
        read_fd,write_fd=os.pipe()
        pid=None
        try:
            import warnings
            with warnings.catch_warnings(record=True) as observed:
                warnings.simplefilter("always", DeprecationWarning)
                pid=os.fork()
            if pid==0:
                try:
                    import signal
                    signal.alarm(3)  # Bound this synthetic child even under a lock regression.
                    os.close(read_fd)
                    try:self.owner._attest()
                    except TransportBoundaryError:os.write(write_fd,b"rejected")
                finally:os._exit(0)
            os.close(write_fd);write_fd=None
            if sys.version_info >= (3, 12):
                self.assertTrue(any(isinstance(item.message, DeprecationWarning) for item in observed))
            import select
            self.assertTrue(select.select([read_fd],[],[],5)[0],"child blocked on inherited RLock")
            self.assertEqual(os.read(read_fd,16),b"rejected")
            status=os.waitpid(pid,0)[1];pid=None
            self.assertEqual(status,0)
        finally:
            os.close(read_fd)
            if write_fd is not None:os.close(write_fd)
            if pid is not None:os.waitpid(pid,0)  # Child's own alarm bounds all failure paths.
            release.set();thread.join(10)
        self.assertFalse(thread.is_alive())


    def _assert_supplement_fork_registration_window(self, mode):
        repository = Path(__file__).resolve().parents[3]
        result = subprocess.run(
            [sys.executable, "-c", _FORK_REGISTRATION_WINDOW_PROBE, str(repository), mode],
            cwd=repository, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stderr, "")
        report = json.loads(result.stdout)
        self.assertEqual(report["mode"], mode)
        for key in ("native_fork", "registration_window_entered", "fork_blocked_until_registered", "child_reaped", "parent_lock_preserved"):
            self.assertIs(report[key], True)
        self.assertEqual(report["result"], {"payload":"child-closed-and-quarantined", "status":0})

    @unittest.skipUnless(hasattr(os, "fork"), "native fork unavailable")
    def test_supplement_fork_during_descriptor_registration(self):
        self._assert_supplement_fork_registration_window("fd")

    @unittest.skipUnless(hasattr(os, "fork"), "native fork unavailable")
    def test_supplement_fork_during_sqlite_registration(self):
        self._assert_supplement_fork_registration_window("sqlite")

    def test_supplement_full_ddl_matches_historical_contract(self):
        # Independent literals: pre-C2 transport blob 3e49198f64e746b7e28a25189abc7a9230ce6cb4
        # plus accepted boundary 7409a69:5686-5692 (meta-only appended column).
        # Reconstructed historical-source golden, not a retained runtime database.
        expected = [
            'CREATE TABLE program_transport_meta(singleton INTEGER PRIMARY KEY CHECK(singleton=1),schema_identity BLOB NOT NULL,program_transport_store_id TEXT NOT NULL UNIQUE,store_instance_id TEXT NOT NULL UNIQUE,creation_nonce BLOB NOT NULL CHECK(length(creation_nonce)=32),approved_store_root TEXT NOT NULL,approved_store_path TEXT NOT NULL,store_device INTEGER NOT NULL,store_inode INTEGER NOT NULL,completion_guard_binding BLOB NOT NULL)',
            'CREATE TABLE program_runtime_attestation(runtime_attestation_id TEXT PRIMARY KEY,program_transport_store_id TEXT NOT NULL,store_instance_id TEXT NOT NULL,program_execution_snapshot_id TEXT NOT NULL,resolved_server_profile_id TEXT NOT NULL,protocol TEXT NOT NULL,operation_table_sha256 TEXT NOT NULL,qualified_runtime_sha256 TEXT NOT NULL,payload BLOB NOT NULL)',
            'CREATE TABLE program_effect_physical_authority(physical_effect_authority_id TEXT PRIMARY KEY,program_transport_store_id TEXT NOT NULL,store_instance_id TEXT NOT NULL,runtime_attestation_id TEXT NOT NULL REFERENCES program_runtime_attestation(runtime_attestation_id),attempt_id TEXT NOT NULL,program_execution_snapshot_id TEXT NOT NULL,effect_intent_id TEXT NOT NULL,operation TEXT NOT NULL,request_sha256 TEXT NOT NULL,effect_classification TEXT NOT NULL,job_id TEXT,submit_once_key TEXT UNIQUE,payload BLOB NOT NULL)',
            "CREATE TRIGGER program_transport_meta_no_update BEFORE UPDATE ON program_transport_meta BEGIN SELECT RAISE(ABORT,'append-only'); END",
            "CREATE TRIGGER program_transport_meta_no_delete BEFORE DELETE ON program_transport_meta BEGIN SELECT RAISE(ABORT,'append-only'); END",
            "CREATE TRIGGER program_runtime_attestation_no_update BEFORE UPDATE ON program_runtime_attestation BEGIN SELECT RAISE(ABORT,'append-only'); END",
            "CREATE TRIGGER program_runtime_attestation_no_delete BEFORE DELETE ON program_runtime_attestation BEGIN SELECT RAISE(ABORT,'append-only'); END",
            "CREATE TRIGGER program_effect_physical_authority_no_update BEFORE UPDATE ON program_effect_physical_authority BEGIN SELECT RAISE(ABORT,'append-only'); END",
            "CREATE TRIGGER program_effect_physical_authority_no_delete BEFORE DELETE ON program_effect_physical_authority BEGIN SELECT RAISE(ABORT,'append-only'); END",
        ]
        actual = list(self.owner._connection.execute(
            "SELECT type,name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"))
        self.assertEqual(len(actual), 9)
        self.assertEqual({row[2] for row in actual}, set(expected))
        def string(value):
            raw = value.encode("utf-8")
            return b"s" + str(len(raw)).encode("ascii") + b":" + raw
        encoded = b"a9:" + b"".join(string(value) for value in expected)
        self.assertEqual(sha256(encoded).hexdigest(),
                         "725c9fae3fc3027b9b5b81e95e48f96c32931ee4d601b85df552569e00417e80")
        stored = self.owner._connection.execute(
            "SELECT schema_identity FROM program_transport_meta WHERE singleton=1").fetchone()[0]
        self.assertEqual(stored, encoded)
        self.assertEqual(self.owner._connection.execute("PRAGMA user_version").fetchone()[0], 2)
