"""Closed Gaussian receipt semantics built from the reviewed publisher owner."""
from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256

from ._identity import ExecutionValueError, freeze_mapping

_SCHEMA = "auto-g16-v31-program-completion/3"
_Q_SCHEMA = "auto-g16-v31-publisher-qualification/4"
_Q_NAME = "v31-gaussian-publisher-qualification-v4.json"
_MATERIAL_SCHEMA = "v31-completion-rendering-material/5"
_CONTRACT_SHA256 = sha256(b"V31-GAUSSIAN-SUCCESSOR-01\n").hexdigest()
_ENVIRONMENT_KEYS = frozenset(
    {"g16root", "GAUSS_EXEDIR", "LD_LIBRARY_PATH", "GAUSS_SCRDIR"}
)

_GAUSSIAN_ENV_SOURCE = r'''
def gaussian_environment(config,workspace):
    payload=closed(un64(config["material"]["publisher_qualification_base64"]))["payload"]
    declared=payload["runtime"]["gaussian_environment"]
    if set(declared)!={"g16root","GAUSS_EXEDIR","LD_LIBRARY_PATH","GAUSS_SCRDIR"}:fail("gaussian-env-shape")
    executable_root=config["spec"]["invocation"]["executable_identity"]["absolute_path"].rsplit("/",1)[0] or "/"
    for name in ("g16root","GAUSS_EXEDIR","LD_LIBRARY_PATH"):
        if declared[name]!=executable_root:fail("gaussian-env-root")
    scratch=declared["GAUSS_SCRDIR"]
    if scratch!={"mode":"attempt-workspace"}:fail("gaussian-scratch-policy")
    return {"OMP_NUM_THREADS":str(config["cores"]),"g16root":declared["g16root"],"GAUSS_EXEDIR":declared["GAUSS_EXEDIR"],"LD_LIBRARY_PATH":declared["LD_LIBRARY_PATH"],"GAUSS_SCRDIR":workspace}
'''


def _validate_environment(value: object, executable_path: str) -> Mapping[str, object]:
    from ._paths import validate_posix_path
    from .program import _exact_keys

    if not isinstance(value, Mapping):
        raise ExecutionValueError("Gaussian environment must be a closed mapping")
    _exact_keys(value, _ENVIRONMENT_KEYS, "Gaussian environment")
    executable_root = executable_path.rsplit("/", 1)[0] or "/"
    closed: dict[str, object] = {}
    for name in ("g16root", "GAUSS_EXEDIR", "LD_LIBRARY_PATH"):
        path = validate_posix_path(value[name], f"Gaussian environment {name}")
        if path != executable_root:
            raise ExecutionValueError(
                f"Gaussian environment {name} differs from executable root"
            )
        closed[name] = path
    scratch = value["GAUSS_SCRDIR"]
    if not isinstance(scratch, Mapping):
        raise ExecutionValueError("Gaussian scratch declaration must be closed")
    _exact_keys(scratch, {"mode"}, "Gaussian scratch")
    if scratch != {"mode": "attempt-workspace"}:
        raise ExecutionValueError("Gaussian scratch declaration differs")
    closed["GAUSS_SCRDIR"] = dict(scratch)
    return freeze_mapping(closed, "Gaussian environment")


def _validate_data(value: Mapping[str, object]) -> Mapping[str, object]:
    from .program import _validate_gaussian_data
    return _validate_gaussian_data(value)


def _render(executable, input_name, data):
    from .program import _render_gaussian
    return _render_gaussian(executable, input_name, data)


def _output_closure(outputs: Mapping[str, bytes | None]) -> str | None:
    if set(outputs) != {"gaussian.log", "gaussian.chk"}:
        raise ExecutionValueError("Gaussian output inventory differs from v1")
    raw = outputs["gaussian.log"]
    if raw is None:
        return "output-incomplete"
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return "output-invalid"
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if "\x00" in text or not lines or not lines[-1].startswith(
        "Normal termination of Gaussian"
    ):
        return "output-invalid"
    return None


def _wrapper_sources() -> tuple[str, str]:
    """Derive one source-controlled Gaussian owner; historical sources stay exact."""
    from ._program_completion_wrapper import (
        _PUBLISHER_PROBE_SOURCE,
        _PUBLISHER_WRAPPER_SOURCE,
    )

    def host_source(source: str) -> str:
        replacements = (
            (
                "def observe_publisher_host(runtime,remote_root,data_root):",
                "def observe_publisher_host(runtime,remote_root):",
            ),
            (
                'zip(("workspace-root","server-python","xtb","xtb-data-root"),(remote_root,runtime["server_python"]["path"],runtime["xtb"]["path"],data_root))',
                'zip(("workspace-root","server-python","gaussian"),(remote_root,runtime["server_python"]["path"],runtime["gaussian"]["path"]))',
            ),
            ('for key in ("server_python","xtb"):', 'for key in ("server_python","gaussian"):'),
        )
        for old, new in replacements:
            if source.count(old) != 1:
                raise ExecutionValueError("Gaussian host guard predecessor drift")
            source = source.replace(old, new, 1)
        return source

    wrapper = host_source(_PUBLISHER_WRAPPER_SOURCE)
    if wrapper.count("def run(config):\n") != 1:
        raise ExecutionValueError("Gaussian environment predecessor drift")
    wrapper = wrapper.replace(
        "def run(config):\n", _GAUSSIAN_ENV_SOURCE + "\ndef run(config):\n", 1
    )
    replacements = (
        (
            'if set(config)!={"prebinding","prebinding_sha256","spec","material","xtb_data_path","cores","walltime_seconds"}',
            'if set(config)!={"prebinding","prebinding_sha256","spec","material","cores","walltime_seconds"}',
        ),
        ('spec["program_kind"]!="xtb"', 'spec["program_kind"]!="gaussian"'),
        ('"auto-g16-v31-program-completion/1"', f'"{_SCHEMA}"'),
        ('"program_kind":"xtb"', '"program_kind":"gaussian"'),
        ('"operation":spec["program_data"]["task"]', '"operation":spec["program_data"]["stage"]'),
        ('"xtb.pbs"', '"gaussian.pbs"'),
        ('        env={"OMP_NUM_THREADS":str(config["cores"]),"XTBPATH":config["xtb_data_path"]}\n', ''),
        ('material.get("schema")!="v31-completion-rendering-material/2"', f'material.get("schema")!="{_MATERIAL_SCHEMA}"'),
        ('binding.get("binding_schema")!="v31-completion-prebinding/3"', 'binding.get("binding_schema")!="v31-completion-prebinding/6"'),
        ('payload["schema"]!="auto-g16-v31-publisher-qualification/1"', f'payload["schema"]!="{_Q_SCHEMA}"'),
        (
            'actual=observe_publisher_host(payload["runtime"],payload["execution_domain"]["remote_root"],config["xtb_data_path"])',
            'actual=observe_publisher_host(payload["runtime"],payload["execution_domain"]["remote_root"])',
        ),
        (
            '    data_manifest=closed(un64(material["xtb_runtime_data_manifest_base64"]))\n'
            '        data_identities=[]\n'
            '        for name,item in sorted(data_manifest["files"].items()):\n'
            '            data_identities.append((name,file_identity(config["xtb_data_path"]+"/"+name,item["size_bytes"],item["sha256"])))\n',
            '    data_identities=[]\n',
        ),
        (
            '        for name,ident in data_identities:\n'
            '            item=data_manifest["files"][name]\n'
            '            if file_identity(config["xtb_data_path"]+"/"+name,item["size_bytes"],item["sha256"])!=ident:fail("runtime-data-replaced")\n',
            '',
        ),
        (
            '    data_raw=un64(material["xtb_runtime_data_manifest_base64"])\n'
            '    if {"sha256":hashlib.sha256(data_raw).hexdigest(),"size_bytes":len(data_raw)}!=payload["runtime"]["xtb_runtime_data_manifest"]:fail("publisher-data-manifest")\n'
            '    data=closed(data_raw)\n'
            '    if set(data)!={"schema","files"} or data["schema"]!="auto-g16-v31-xtb-runtime-data-manifest/1":fail("publisher-data-schema")\n'
            '    # This observation is compared with launch_host at both child and link seams.\n'
            '    # A stable data-root inode alone cannot detect file replacement or content drift.\n'
            '    actual["runtime_data_files"]=[(name,file_identity(config["xtb_data_path"]+"/"+name,item["size_bytes"],item["sha256"])) for name,item in sorted(data["files"].items())]\n',
            '',
        ),
        (
            '    logfd=None;execfd=None\n'
            '    try:\n',
            '    logfd=None;execfd=None;inputfd=None\n'
            '    try:\n',
        ),
        (
            '            inputs.append(declaration);input_identities.append(ident)\n'
            '        data_identities=[]\n',
            '            inputs.append(declaration);input_identities.append(ident)\n'
            '        env=gaussian_environment(config,workspace)\n'
            '        inputfd=os.open(inputs[0]["portable_name"],RF,dir_fd=parent)\n'
            '        if identity(os.fstat(inputfd))!=input_identities[0] or identity(os.stat(inputs[0]["portable_name"],dir_fd=parent,follow_symlinks=False))!=input_identities[0]:fail("input-replaced")\n'
            '        data_identities=[]\n',
        ),
        (
            'stdin=subprocess.DEVNULL,stdout=logfd',
            'stdin=inputfd,stdout=logfd',
        ),
        (
            '        status=wait_all(proc.pid,time.monotonic()+config["walltime_seconds"])\n',
            '        os.close(inputfd);inputfd=None\n'
            '        status=wait_all(proc.pid,time.monotonic()+config["walltime_seconds"])\n',
        ),
        (
            '        if execfd is not None:os.close(execfd)\n',
            '        if execfd is not None:os.close(execfd)\n'
            '        if inputfd is not None:os.close(inputfd)\n',
        ),
    )
    for old, new in replacements:
        if wrapper.count(old) != 1:
            raise ExecutionValueError("Gaussian wrapper predecessor drift")
        wrapper = wrapper.replace(old, new, 1)
    probe = host_source(_PUBLISHER_PROBE_SOURCE)
    guard_start = probe.find("\ndef publisher_host_guard(config):")
    main_start = probe.find('\nif __name__=="__main__":', guard_start)
    if guard_start < 0 or main_start < 0:
        raise ExecutionValueError("Gaussian probe host-guard predecessor drift")
    probe = probe[:guard_start] + probe[main_start:]
    probe_replacements = (
        ('if set(request)!={"runtime","remote_root","xtb_data_path"}', 'if set(request)!={"runtime","remote_root"}'),
        ('observe_publisher_host(request["runtime"],request["remote_root"],request["xtb_data_path"])', 'observe_publisher_host(request["runtime"],request["remote_root"])'),
    )
    for old, new in probe_replacements:
        if probe.count(old) != 1:
            raise ExecutionValueError("Gaussian probe predecessor drift")
        probe = probe.replace(old, new, 1)
    return wrapper, probe


__all__: tuple[str, ...] = ()
