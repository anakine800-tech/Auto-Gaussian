"""Private CREST 3.0.2 completion semantics; no authority from decoded files."""
from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
import re

from ._identity import ExecutionValueError, freeze_mapping

_SCHEMA = "auto-g16-v31-program-completion/2"
_Q_SCHEMA = "auto-g16-v31-publisher-qualification/2"
_Q_NAME = "v31-crest-publisher-qualification-v2.json"
_MATERIAL_SCHEMA = "v31-completion-rendering-material/3"
_CONTRACT_SHA256 = "8a42aa6a82b28b13413412073c78802ecb426f26c251686191a0d157fbf5601e"
_POLICY = {"atom_order_policy": "preserve-input-order", "calculator_policy": "internal-tblite"}
_NAMES = ("crest.out", "crest_best.xyz", "crest_conformers.xyz", "crest.energies")
_AUTOKCAL = Decimal("627.50947428")
_ENERGY_TOLERANCE = Decimal("0.0005") + Decimal("0.00000001") * _AUTOKCAL


def _validate_data(value):
    from .program import _validate_crest_imtd_gc_v2_data
    from ._program_completion import _MODE
    if any(value.get(k) != v for k, v in {**_POLICY, "completion_mode": _MODE}.items()):
        raise ExecutionValueError("CREST v3 requires exact completion and internal atom-order policy")
    _validate_crest_imtd_gc_v2_data({k: v for k, v in value.items() if k not in {*_POLICY, "completion_mode"}})
    return freeze_mapping(value, "CREST v3 program data")


def _render(executable, input_name, data):
    from .program import _render_crest_imtd_gc_v2, _invocation, _outputs
    invocation, _, _ = _render_crest_imtd_gc_v2(executable, input_name, data)
    argv = tuple(invocation["argv"])
    cross = argv.index("-cross")
    argv = (*argv[:cross + 1], "-nozs", *argv[cross + 1:])
    required, optional = _outputs(required=(
        ("program-log", "crest.out", "text"),
        ("best-geometry", "crest_best.xyz", "xyz"),
        ("conformer-ensemble", "crest_conformers.xyz", "xyz-trajectory"),
        ("conformer-energies", "crest.energies", "text"),
    ), optional=())
    return _invocation(executable, argv, program_kind="crest", xtb_data_authority=True), required, optional


def _frames(raw: bytes):
    """Read the exact finite numeric XYZ writer, retaining printed precision."""
    from ._program_completion import _xyz_elements
    if type(raw) is not bytes or not raw or len(raw) > 64 * 1024 * 1024 or not raw.endswith(b"\n") or b"\r" in raw:
        raise ValueError("XYZ size/type")
    lines = raw.decode("utf-8").splitlines()
    result = []
    pos = 0
    while pos < len(lines):
        if re.fullmatch(r"\s*[1-9][0-9]*\s*", lines[pos]) is None:
            raise ValueError("XYZ frame count")
        count = int(lines[pos])
        block = lines[pos:pos + count + 2]
        if len(block) != count + 2:
            raise ValueError("XYZ incomplete frame")
        _xyz_elements((str(count) + "\n" + "\n".join(block[1:]) + "\n").encode())
        if re.fullmatch(r"\s*-?[0-9]+\.[0-9]{8}\s*", block[1]) is None:
            raise ValueError("CREST energy comment precision")
        energy = Decimal(block[1].strip())
        rows = [line.split() for line in block[2:]]
        if any(re.fullmatch(r"-?[0-9]+\.[0-9]{10}", token) is None for row in rows for token in row[1:]):
            raise ValueError("CREST coordinate writer precision")
        atoms = tuple((tokens[0], *(Decimal(x) for x in tokens[1:])) for tokens in rows)
        if not energy.is_finite() or not all(x.is_finite() for a in atoms for x in a[1:]):
            raise ValueError("nonfinite XYZ")
        result.append((energy, atoms))
        pos += count + 2
    return tuple(result)


def _sampling_log(raw):
    if type(raw) is not bytes or not raw or len(raw) > 64 * 1024 * 1024:
        return False
    text = raw.decode("utf-8")
    if "\x00" in text:
        return False
    markers = ("CREST iMTD-GC SAMPLING", "Meta-Dynamics Iteration 1", "MTD Simulations done", "Final Ensemble Information", "CREST terminated normally.")
    sequence = [line.strip(" \t│|*") for line in text.splitlines()]
    found = [line for line in sequence if line in markers]
    # header, one or more full MAINLOOP cycles, final summary, normal end.
    if len(found) < 5 or found[0] != markers[0] or found[-2:] != list(markers[3:]):
        return False
    middle = found[1:-2]
    return len(middle) % 2 == 0 and middle == list(markers[1:3]) * (len(middle) // 2)


def _output_closure(input_content: bytes, outputs: Mapping[str, bytes | None]):
    from ._program_completion import _xyz_elements
    if set(outputs) != set(_NAMES):
        raise ExecutionValueError("CREST output inventory differs from v3")
    if any(outputs[name] is None for name in _NAMES):
        return "output-incomplete"
    try:
        if not _sampling_log(outputs["crest.out"]):
            return "output-invalid"
        original = _xyz_elements(input_content)
        best = _frames(outputs["crest_best.xyz"])
        frames = _frames(outputs["crest_conformers.xyz"])
        if len(best) != 1 or best[0] != frames[0]:
            return "output-invalid"
        if any(tuple(a[0] for a in atoms) != original for _, atoms in frames):
            return "output-invalid"
        raw = outputs["crest.energies"]
        if type(raw) is not bytes or not raw or len(raw) > 64 * 1024 * 1024:
            return "output-invalid"
        lines = raw.decode("utf-8").splitlines()
        if len(lines) != len(frames):
            return "output-invalid"
        previous = Decimal("-Infinity")
        for index, (line, (energy, _atoms)) in enumerate(zip(lines, frames), 1):
            match = re.fullmatch(r"\s*([1-9][0-9]*)\s+(-?[0-9]+\.[0-9]{3})\s*", line)
            if match is None or int(match[1]) != index:
                return "output-invalid"
            relative = Decimal(match[2])
            if relative < 0 or relative < previous or energy < frames[index - 2][0] and index > 1:
                return "output-invalid"
            if index == 1 and relative != 0 or abs(relative - (energy - frames[0][0]) * _AUTOKCAL) > _ENERGY_TOLERANCE:
                return "output-invalid"
            previous = relative
    except (ValueError, UnicodeError, InvalidOperation, IndexError):
        return "output-invalid"
    return None


def _wrapper_sources():
    """New source-controlled tuple; historical R4 source remains byte-identical."""
    from ._program_completion_wrapper import _PUBLISHER_WRAPPER_SOURCE, _PUBLISHER_PROBE_SOURCE
    from ._crest_loader import _SOURCE as loader_source
    replacements = (
        ('"v31-completion-rendering-material/2"', '"v31-completion-rendering-material/3"'),
        ('"v31-completion-prebinding/3"', '"v31-completion-prebinding/4"'),
        ('"auto-g16-v31-publisher-qualification/1"', '"auto-g16-v31-publisher-qualification/2"'),
        ('("workspace-root","server-python","xtb","xtb-data-root"),(remote_root,runtime["server_python"]["path"],runtime["xtb"]["path"],data_root)', '("workspace-root","server-python","xtb","xtb-data-root","crest"),(remote_root,runtime["server_python"]["path"],runtime["xtb"]["path"],data_root,runtime["crest"]["path"])'),
        ('for key in ("server_python","xtb"):', 'for key in ("server_python","xtb","crest"):'),
        ('    return {"host_key":semantic({"machine_id_sha256":machine}),', '    closure=runtime["crest_loader_closure"]\n    if closure["host_key"]!=semantic({"machine_id_sha256":machine}):fail("crest-loader-host")\n    roots=[o for o in closure["objects"] if o["object_id"]==closure["root_object_id"]]\n    if len(roots)!=1 or {k:roots[0][k] for k in ("path","sha256","size_bytes")}!=runtime["crest"]:fail("crest-loader-root")\n    cl_guard(runtime["crest"]["path"],closure)\n    return {"host_key":semantic({"machine_id_sha256":machine}),'),
    )
    sources = []
    for source in (_PUBLISHER_WRAPPER_SOURCE, _PUBLISHER_PROBE_SOURCE):
        for old, new in replacements:
            if source.count(old) != 1:
                raise ExecutionValueError("CREST source derivation predecessor drift")
            source = source.replace(old, new, 1)
        sources.append(loader_source + "\n" + source)
    source = sources[0]
    for old, new in (
        ('spec["program_kind"]!="xtb"', 'spec["program_kind"]!="crest"'),
        ('"auto-g16-v31-program-completion/1"', '"auto-g16-v31-program-completion/2"'),
        ('"program_kind":"xtb"', '"program_kind":"crest"'),
        ('"operation":spec["program_data"]["task"]', '"operation":"imtd-gc"'),
        ('"xtb.pbs"', '"crest.pbs"'),
    ):
        if source.count(old) != 1:
            raise ExecutionValueError("CREST wrapper predecessor drift")
        source = source.replace(old, new, 1)
    return source, sources[1]


__all__: tuple[str, ...] = ()
