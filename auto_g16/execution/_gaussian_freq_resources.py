"""Explicit adapter-7 pure Freq tuple; historical resource sources stay frozen."""
import base64
from hashlib import sha256
import sys
import zlib
from . import _gaussian_resources as previous
from . import _gaussian_file_carrier as carrier
from auto_g16.transport._gaussian_freq_submit import PROTOCOL_SOURCE, protocol_namespace
from auto_g16.transport._gaussian_file_handoff import rewrite_exact

_ADAPTER_VERSION = 7
_MATERIAL_SCHEMA = "v31-completion-rendering-material/9"
_Q_SCHEMA = "auto-g16-v31-publisher-qualification/8"
_Q_NAME = "v31-gaussian-publisher-qualification-v8.json"
_CONTRACT_SHA256 = sha256(b"V31-GAUSSIAN-FREQ-RESOURCE-01/binary-MiB-explicit-headroom-v1\n").hexdigest()
_HEADER = "# auto-g16-v31-scheduler/10"
_PAYLOAD_NAME = previous._PAYLOAD_NAME
ROUTE = "#p wB97XD/Def2SVP Freq SCF=(Tight,MaxCycle=128) Integral=UltraFine NoSymm"


def _wrapper_sources():
    wrapper, probe = previous._wrapper_sources()
    wrapper = rewrite_exact(wrapper, (
        ('material.get("schema")!="v31-completion-rendering-material/8"', 'material.get("schema")!="v31-completion-rendering-material/9"'),
        ('binding.get("binding_schema")!="v31-completion-prebinding/9"', 'binding.get("binding_schema")!="v31-completion-prebinding/10"'),
        ('payload["schema"]!="auto-g16-v31-publisher-qualification/7"', 'payload["schema"]!="auto-g16-v31-publisher-qualification/8"'),
        ('spec["adapter_contract_version"]!=6', 'spec["adapter_contract_version"]!=7'),
        ('    selected=config["spec"]["program_data"]["gaussian_resources"]',
         '    if config["spec"]["program_data"]["stage"]!="freq" or next((line for line in raw.decode("utf-8").splitlines() if line.startswith("#")),None)!=' + repr(ROUTE) + ':raise ValueError("Freq stage/route differs")\n    selected=config["spec"]["program_data"]["gaussian_resources"]'),
    ), "Gaussian Freq wrapper")
    return wrapper, probe


_LOADER_BODY = rewrite_exact(previous._LOADER_BODY, (
    ('material["schema"]!="v31-completion-rendering-material/8"', 'material["schema"]!="v31-completion-rendering-material/9"'),
    ('binding["binding_schema"]!="v31-completion-prebinding/9"', 'binding["binding_schema"]!="v31-completion-prebinding/10"'),
    ('spec["adapter_contract_version"]!=6', 'spec["adapter_contract_version"]!=7'),
), "Gaussian Freq loader")
_DECODED_LOADER_SOURCE = PROTOCOL_SOURCE + "\n" + _LOADER_BODY
_LOADER_SOURCE = ("import base64,zlib\nexec(compile(zlib.decompress(base64.b64decode("
    + repr(base64.b64encode(zlib.compress(_DECODED_LOADER_SOURCE.encode(), 9)).decode())
    + ")), '<auto-g16-v31-gaussian-freq-loader>', 'exec', dont_inherit=True, optimize=0))\n")


def _payload(artifacts):
    return carrier._payload(artifacts, _owner=sys.modules[__name__])


def _render(config, deployment, resources, project_binding):
    return carrier._render(config, deployment, resources, project_binding, _owner=sys.modules[__name__])


def _derived_artifacts(snapshot):
    return carrier._derived_artifacts(snapshot, _owner=sys.modules[__name__])


def _review_disclosure(snapshot):
    return carrier._review_disclosure(snapshot, _owner=sys.modules[__name__])
