"""Recovery-only bounded process reader; predecessor process semantics are frozen."""
import os
import selectors
import subprocess
import time

from . import _driver
from ._canonical import TransportBoundaryError


class _RecoveryProcessOwner(_driver._SubprocessRTWinDriver):
    def _communicate_bounded(self, process, request, operation):
        streams = {"stdin": process.stdin, "stdout": process.stdout, "stderr": process.stderr}
        output = {"stdout": bytearray(), "stderr": bytearray()}
        eof = {"stdout": False, "stderr": False}
        selector = selectors.DefaultSelector()
        status, code, offset = "transport-error", None, 0
        try:
            for name, stream in streams.items():
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_WRITE if name == "stdin" else selectors.EVENT_READ, name)
            deadline = time.monotonic() + operation.timeout_seconds
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    status = "timeout"
                    break
                events = selector.select(remaining)
                if not events:
                    status = "timeout"
                    break
                for key, _mask in events:
                    name, stream = key.data, key.fileobj
                    if name == "stdin":
                        try:
                            written = os.write(stream.fileno(), request[offset:offset + 65536])
                        except BrokenPipeError:
                            written = 0
                        offset += written
                        if offset == len(request) or written == 0:
                            selector.unregister(stream)
                            stream.close()
                        continue
                    cap = operation.stdout_cap if name == "stdout" else operation.stderr_cap
                    chunk = os.read(stream.fileno(), min(65536, cap + 1 - len(output[name])))
                    if not chunk:
                        eof[name] = True
                        selector.unregister(stream)
                        continue
                    output[name].extend(chunk)
                    if len(output[name]) > cap:
                        del output[name][cap:]
                        status = "output-cap"
                        raise ValueError("output cap")
            else:
                try:
                    code = process.wait(timeout=max(.001, deadline - time.monotonic()))
                    status = "completed"
                except subprocess.TimeoutExpired:
                    status = "timeout"
        except (OSError, ValueError, AttributeError):
            if status != "output-cap":
                status = "transport-error"
        finally:
            selector.close()
            if status != "completed" or process.poll() is None:
                self._kill(process)
                process.wait()
            for stream in streams.values():
                if stream is not None:
                    stream.close()
        return bytes(output["stdout"]), bytes(output["stderr"]), code, status, eof["stdout"], eof["stderr"]

    def _run(self, snapshot, invocation):
        from ._program_rtwin import _prepare_program_invocation
        command, request = _prepare_program_invocation(snapshot, invocation)
        if invocation.operation.name != "RECONCILE_SUBMISSION":
            raise TransportBoundaryError("recovery process requires exact reconciliation")
        roots, effect = invocation.authority.manifest.trust_roots, invocation.authority.ssh_effect
        if type(effect) is not _driver._MacProxyJumpEffectAuthority:
            raise TransportBoundaryError("recovery process requires fixed ProxyJump")
        def local_identity():
            result = {"mac_ssh": _driver._attest_local(roots["mac_ssh"])}
            for bound in (effect.config, effect.rtwin_known_hosts, effect.final_known_hosts, effect.final_public_key):
                result[bound.name] = _driver._attest_local_effect_file(bound)
            for index, (path, expected) in enumerate(((effect.rtwin_target.identity_file, None), (effect.final_target.identity_file, effect.final_identity_file_identity))):
                result[f"identity-{index}"] = _driver._attest_identity_reference(path, expected)
            return result
        before = local_identity()
        raw = (b"", b"", None, "transport-error", False, False)
        process = None
        try:
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       env=dict(_driver._FIXED_ENV), shell=False, start_new_session=True)
            raw = self._communicate_bounded(process, request, invocation.operation)
            if before != local_identity():
                self._kill(process)
                return (*raw[:3], "identity-drift", *raw[4:])
            return raw
        except (OSError, TransportBoundaryError):
            if process is not None:
                self._kill(process)
                process.wait()
            return (*raw[:3], "transport-error", *raw[4:])
