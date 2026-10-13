"""Additive adapter-6 identity over the unchanged file-carrier mechanism."""
from . import _gaussian_file_submit as previous
from ._gaussian_file_handoff import rewrite_exact

PROTOCOL_SOURCE = rewrite_exact(previous.PROTOCOL_SOURCE, (
    ('g_keys(c,"cores material prebinding prebinding_sha256 spec walltime_seconds")',
     'g_keys(c,"cores material memory_mb prebinding prebinding_sha256 spec walltime_seconds")'),
    ('v["adapter_contract_version"]!=5', 'v["adapter_contract_version"]!=6'),
    ('h["adapter_contract_version"]!=5', 'h["adapter_contract_version"]!=6'),
), "Gaussian resource handoff")
SUBMIT_SOURCE = rewrite_exact(previous.SUBMIT_SOURCE, (
    ('"adapter_id":"auto-g16-v31-gaussian","adapter_contract_version":5',
     '"adapter_id":"auto-g16-v31-gaussian","adapter_contract_version":6'),
    ('"schema":"auto-g16-v31-gaussian-launch-handoff-auth/1","adapter_contract_version":5',
     '"schema":"auto-g16-v31-gaussian-launch-handoff-auth/1","adapter_contract_version":6'),
), "Gaussian resource submit")
SOURCE_NAME = "v31-gaussian-resource-bootstrap-v3.py"
QSUB_CHILD_TIMEOUT_SECONDS = previous.QSUB_CHILD_TIMEOUT_SECONDS
RECEIPT_PERSISTENCE_BUDGET_SECONDS = previous.RECEIPT_PERSISTENCE_BUDGET_SECONDS
SUBMIT_EFFECT_TIMEOUT_SECONDS = previous.SUBMIT_EFFECT_TIMEOUT_SECONDS


def protocol_namespace():
    namespace = {"__name__": "gaussian_resource_handoff_protocol"}
    exec(compile(PROTOCOL_SOURCE, "<gaussian-resource-handoff-protocol>", "exec"), namespace)
    return namespace


def source_bytes():
    old = (previous.PROTOCOL_SOURCE + "\n" + previous.SUBMIT_SOURCE).encode()
    source = previous.source_bytes()
    if source.count(old) != 1:
        raise ValueError("Gaussian resource bootstrap predecessor drift")
    return source.replace(old, (PROTOCOL_SOURCE + "\n" + SUBMIT_SOURCE).encode(), 1)


def assert_submit_timeout_contract():
    previous.assert_submit_timeout_contract()
    if (QSUB_CHILD_TIMEOUT_SECONDS, RECEIPT_PERSISTENCE_BUDGET_SECONDS, SUBMIT_EFFECT_TIMEOUT_SECONDS) != (30, 90, 120):
        raise ValueError("Gaussian resource submit deadlines differ")
    if source_bytes().count(previous._QSUB_CHILD_DEADLINE_SOURCE) != 1:
        raise ValueError("Gaussian resource child deadline source drift")
