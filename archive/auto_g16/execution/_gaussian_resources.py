"""Gaussian Opt resource adapter-6 sources, derived without changing Q6 bytes."""
from __future__ import annotations

import base64
from hashlib import sha256
import sys
import zlib

from . import _gaussian_file_carrier as previous
from ._identity import ExecutionValueError
from auto_g16.transport._gaussian_resource_submit import PROTOCOL_SOURCE, protocol_namespace
from auto_g16.transport._gaussian_file_handoff import rewrite_exact

_ADAPTER_VERSION = 6
_MATERIAL_SCHEMA = "v31-completion-rendering-material/8"
_Q_SCHEMA = "auto-g16-v31-publisher-qualification/7"
_Q_NAME = "v31-gaussian-publisher-qualification-v7.json"
_CONTRACT_SHA256 = sha256(b"V31-GAUSSIAN-OPT-RESOURCE-01/binary-MiB-explicit-headroom-v1\n").hexdigest()
_HEADER = "# auto-g16-v31-scheduler/9"
_PAYLOAD_NAME = previous._PAYLOAD_NAME

# One source owns the byte-unit conversion both locally and in the child
# wrapper. It never derives, changes or supplies a scheduler resource request.
_RESOURCE_SOURCE = r'''
def gaussian_resource_facts(raw):
    lines=raw.decode("utf-8").split("\n");fields={};started=False
    for line in lines:
        if not line.strip() and not started:continue
        if not line.startswith("%"):break
        started=True
        match=re.fullmatch(r"%(chk|mem|nprocshared)=(gaussian\.chk|[1-9][0-9]{0,8}(?:MB|GB)?)",line,re.I|re.A)
        if match is None:raise ValueError("Gaussian resource Link0 syntax")
        key,value=match[1].lower(),match[2]
        if key in fields:raise ValueError("Gaussian resource duplicate")
        fields[key]=value
    if set(fields)!={"chk","mem","nprocshared"} or fields["chk"]!="gaussian.chk":raise ValueError("Gaussian resource inventory")
    memory=re.fullmatch(r"([1-9][0-9]{0,8})(MB|GB)",fields["mem"],re.I|re.A)
    if memory is None or re.fullmatch(r"[1-9][0-9]{0,8}",fields["nprocshared"],re.A) is None:raise ValueError("Gaussian resource units")
    return {"memory_mib":int(memory[1])*(1024 if memory[2].upper()=="GB" else 1),"cores":int(fields["nprocshared"])}

def gaussian_resource_check(config,raw):
    selected=config["spec"]["program_data"]["gaussian_resources"]
    if set(selected)!={"memory_mib","cores","headroom_mib"} or any(type(v) is not int or v<1 for v in selected.values()):raise ValueError("Gaussian resource fields")
    if gaussian_resource_facts(raw)!={k:selected[k] for k in ("memory_mib","cores")}:raise ValueError("Gaussian resource input differs from spec")
    if type(config["cores"]) is not int or type(config["memory_mb"]) is not int or config["cores"]!=selected["cores"] or config["memory_mb"]!=selected["memory_mib"]+selected["headroom_mib"]:raise ValueError("Gaussian resources differ from snapshot")
'''


def _resource_facts(raw):
    import re
    namespace = {"re": re}
    exec(compile(_RESOURCE_SOURCE, "<gaussian-resource-semantics>", "exec"), namespace)
    try:
        return namespace["gaussian_resource_facts"](raw)
    except (ValueError, UnicodeError) as exc:
        raise ExecutionValueError(str(exc)) from exc


def _wrapper_sources():
    wrapper, probe = previous._wrapper_sources()
    wrapper = rewrite_exact(wrapper, (
        ('material.get("schema")!="v31-completion-rendering-material/7"', 'material.get("schema")!="v31-completion-rendering-material/8"'),
        ('binding.get("binding_schema")!="v31-completion-prebinding/8"', 'binding.get("binding_schema")!="v31-completion-prebinding/9"'),
        ('payload["schema"]!="auto-g16-v31-publisher-qualification/6"', 'payload["schema"]!="auto-g16-v31-publisher-qualification/7"'),
        ('spec["adapter_contract_version"]!=5', 'spec["adapter_contract_version"]!=6'),
        ('"material","cores","walltime_seconds"}', '"material","cores","memory_mb","walltime_seconds"}'),
        ('def run(config):\n', _RESOURCE_SOURCE + '\ndef run(config):\n'),
        ('        env=gaussian_environment(config,workspace)\n', '        gaussian_resource_check(config,raw)\n        env=gaussian_environment(config,workspace)\n'),
    ), "Gaussian resource wrapper")
    return wrapper, probe


_LOADER_BODY = rewrite_exact(previous._LOADER_BODY, (
    ('material["schema"]!="v31-completion-rendering-material/7"', 'material["schema"]!="v31-completion-rendering-material/8"'),
    ('binding["binding_schema"]!="v31-completion-prebinding/8"', 'binding["binding_schema"]!="v31-completion-prebinding/9"'),
    ('spec["adapter_contract_version"]!=5', 'spec["adapter_contract_version"]!=6'),
), "Gaussian resource loader")
_DECODED_LOADER_SOURCE = PROTOCOL_SOURCE + "\n" + _LOADER_BODY
_LOADER_SOURCE = (
    "import base64,zlib\nexec(compile(zlib.decompress(base64.b64decode("
    + repr(base64.b64encode(zlib.compress(_DECODED_LOADER_SOURCE.encode(), 9)).decode())
    + ")), '<auto-g16-v31-gaussian-resource-loader>', 'exec', dont_inherit=True, optimize=0))\n"
)


def _payload(artifacts):
    return previous._payload(artifacts, _owner=sys.modules[__name__])


def _render(config, deployment, resources, project_binding):
    return previous._render(config, deployment, resources, project_binding, _owner=sys.modules[__name__])


def _derived_artifacts(snapshot):
    return previous._derived_artifacts(snapshot, _owner=sys.modules[__name__])


def _review_disclosure(snapshot):
    return previous._review_disclosure(snapshot, _owner=sys.modules[__name__])
