"""Adapter-7 Freq identity over the unchanged Q7 file-carrier mechanism."""
from . import _gaussian_resource_submit as previous
from ._gaussian_file_handoff import rewrite_exact

PROTOCOL_SOURCE = rewrite_exact(previous.PROTOCOL_SOURCE, (
    ('v["adapter_contract_version"]!=6', 'v["adapter_contract_version"]!=7'),
    ('h["adapter_contract_version"]!=6', 'h["adapter_contract_version"]!=7'),
), "Gaussian Freq handoff")
SUBMIT_SOURCE = rewrite_exact(previous.SUBMIT_SOURCE, (
    ('"adapter_id":"auto-g16-v31-gaussian","adapter_contract_version":6',
     '"adapter_id":"auto-g16-v31-gaussian","adapter_contract_version":7'),
    ('"schema":"auto-g16-v31-gaussian-launch-handoff-auth/1","adapter_contract_version":6',
     '"schema":"auto-g16-v31-gaussian-launch-handoff-auth/1","adapter_contract_version":7'),
), "Gaussian Freq submit")
SOURCE_NAME = "v31-gaussian-freq-resource-bootstrap-v4.py"
QSUB_CHILD_TIMEOUT_SECONDS = previous.QSUB_CHILD_TIMEOUT_SECONDS
RECEIPT_PERSISTENCE_BUDGET_SECONDS = previous.RECEIPT_PERSISTENCE_BUDGET_SECONDS
SUBMIT_EFFECT_TIMEOUT_SECONDS = previous.SUBMIT_EFFECT_TIMEOUT_SECONDS


def protocol_namespace():
    namespace = {"__name__": "gaussian_freq_handoff_protocol"}
    exec(compile(PROTOCOL_SOURCE, "<gaussian-freq-handoff-protocol>", "exec"), namespace)
    return namespace


def source_bytes():
    old = (previous.PROTOCOL_SOURCE + "\n" + previous.SUBMIT_SOURCE).encode()
    source = previous.source_bytes()
    if source.count(old) != 1:
        raise ValueError("Gaussian Freq bootstrap predecessor drift")
    return source.replace(old, (PROTOCOL_SOURCE + "\n" + SUBMIT_SOURCE).encode(), 1)


def assert_submit_timeout_contract():
    previous.assert_submit_timeout_contract()
    if (QSUB_CHILD_TIMEOUT_SECONDS, RECEIPT_PERSISTENCE_BUDGET_SECONDS, SUBMIT_EFFECT_TIMEOUT_SECONDS) != (30, 90, 120):
        raise ValueError("Gaussian Freq submit deadlines differ")
