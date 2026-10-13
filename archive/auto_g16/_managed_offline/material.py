"""Typed material, integer XYZ and scientific join; no chemistry inference."""

from dataclasses import dataclass
from hashlib import sha256
import re
import unicodedata
from uuid import UUID

from auto_g16.execution.program import ProgramExecutionSpec, _prepare_program_execution_spec

from .common import Rejected, copy_data, digest, exact, json_bytes

_FIELDS = {"schema", "intake_id", "structure_identity", "stereochemistry_review",
           "atoms", "model", "task", "charge", "multiplicity", "unpaired_electrons", "solvent"}
_COORDS = ("x_microangstrom", "y_microangstrom", "z_microangstrom")
_ELECTRONS = {"H": 1, "C": 6, "N": 7, "O": 8}


def _integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise Rejected("BAD_MATERIAL")


def _label(value):
    if (type(value) is not str or unicodedata.normalize("NFC", value) != value
            or not 1 <= len(value.encode("utf-8")) <= 2048
            or any(unicodedata.category(c).startswith("C") or c in "\n\r\u2028\u2029" for c in value)):
        raise Rejected("BAD_MATERIAL")


def uuid4_text(value):
    try:
        parsed = UUID(value)
        if type(value) is not str or str(parsed) != value or parsed.version != 4:
            raise ValueError
    except (ValueError, TypeError, AttributeError) as exc:
        raise Rejected("BAD_MATERIAL") from exc


def _coordinate(value):
    sign = "-" if value < 0 else ""
    whole, fraction = divmod(abs(value), 1_000_000)
    return f"{sign}{whole}.{fraction:06d}"


def encode_xyz(atoms):
    lines = [str(len(atoms)), "Auto-G16 managed structure"]
    lines.extend(" ".join([a["element"], *(_coordinate(a[k]) for k in _COORDS)]) for a in atoms)
    return ("\n".join(lines) + "\n").encode("ascii")


def decode_xyz(raw):
    try:
        lines = raw.decode("ascii").splitlines()
        if len(lines) < 3 or lines[1] != "Auto-G16 managed structure":
            raise ValueError
        count = int(lines[0])
        if str(count) != lines[0] or len(lines) != count + 2:
            raise ValueError
        atoms = []
        for line in lines[2:]:
            tokens = line.split(" ")
            if len(tokens) != 4 or tokens[0] not in _ELECTRONS:
                raise ValueError
            atom = {"element": tokens[0]}
            for key, token in zip(_COORDS, tokens[1:]):
                if not re.fullmatch(r"-?(0|[1-9][0-9]*)\.[0-9]{6}", token):
                    raise ValueError
                whole, fraction = token.lstrip("-").split(".")
                atom[key] = (-1 if token.startswith("-") else 1) * (int(whole) * 1_000_000 + int(fraction))
            atoms.append(atom)
        if encode_xyz(atoms) != raw:
            raise ValueError
        return atoms
    except (ValueError, UnicodeError, AttributeError) as exc:
        raise Rejected("BAD_MATERIAL") from exc


@dataclass(frozen=True)
class Material:
    canonical_payload: bytes
    xyz: bytes

    @property
    def payload(self):
        import json
        return json.loads(self.canonical_payload)

    @property
    def identity(self):
        return digest(self.payload)

    @property
    def input_identity(self):
        return {"portable_name": "structure.xyz", "format": "xyz",
                "sha256": sha256(self.xyz).hexdigest(), "size_bytes": len(self.xyz)}

    @property
    def program_data(self):
        return {k: self.payload[k] for k in ("model", "task", "charge", "unpaired_electrons", "solvent")}

    @property
    def intent(self):
        p = self.payload
        return {"schema": "auto-g16-xtb-material-intent/1", "material_sha256": self.identity,
                **{k: p[k] for k in _FIELDS - {"schema", "intake_id"}},
                "input_identity": self.input_identity, "program_kind": "xtb"}

    @property
    def display(self):
        return {"intent": self.intent, "coordinate_unit": "microangstrom (10^-6 angstrom)",
                "xyz": self.xyz.decode("ascii"),
                "limitations": "Electron parity and coordinates do not establish connectivity, stereochemistry or ground state. Human review required. Offline prototype only."}


def validate_material(payload):
    try:
        exact(payload, _FIELDS)
        if payload["schema"] != "auto-g16-xtb-local-material/1":
            raise Rejected("BAD_MATERIAL")
        uuid4_text(payload["intake_id"])
        _label(payload["structure_identity"])
        _label(payload["stereochemistry_review"])
        if payload["model"] not in ("gfn1", "gfn2") or payload["task"] != "single-point" or payload["solvent"] is not None:
            raise Rejected("BAD_MATERIAL")
        for key, value in (("charge", 0), ("multiplicity", 1), ("unpaired_electrons", 0)):
            _integer(payload[key], value, value)
        atoms = payload["atoms"]
        if type(atoms) is not list or not 1 <= len(atoms) <= 128:
            raise Rejected("BAD_MATERIAL")
        seen, electrons = set(), 0
        for atom in atoms:
            exact(atom, {"element", *_COORDS})
            if type(atom["element"]) is not str or atom["element"] not in _ELECTRONS:
                raise Rejected("BAD_MATERIAL")
            point = tuple(atom[k] for k in _COORDS)
            for number in point:
                _integer(number, -1_000_000_000, 1_000_000_000)
            if point in seen:
                raise Rejected("BAD_MATERIAL")
            seen.add(point)
            electrons += _ELECTRONS[atom["element"]]
        if electrons % 2:
            raise Rejected("BAD_MATERIAL")
        xyz = encode_xyz(atoms)
        if decode_xyz(xyz) != atoms:
            raise Rejected("BAD_MATERIAL")
        raw = json_bytes(payload)
        if len(raw) > 65536:
            raise Rejected("BAD_MATERIAL")
        return Material(raw, xyz)
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise Rejected("BAD_MATERIAL") from exc


def build_spec(material, profile):
    """Fixed adapter builder; profile comes from composition, never wire data."""
    profile.assert_identity_closed()
    executable = profile.runtime_identities["xtb"]
    return _prepare_program_execution_spec(
        program_kind="xtb", executable_path=profile.platform_paths["xtb_executable_path"],
        executable_size_bytes=executable["size_bytes"], executable_sha256=executable["sha256"],
        input_name="structure.xyz", input_bytes=material.xyz,
        program_data=material.program_data, resolved_profile=profile,
        completion_mode="receipt-on-absence-v1")


def semantic_join(material, plan, spec):
    checked = validate_material(material.payload)
    if checked != material or copy_data(plan.intent) != material.intent or plan.revision != 1:
        raise Rejected("STALE")
    if type(spec) is not ProgramExecutionSpec:
        raise Rejected("MISSING_DEPENDENCY")
    spec.assert_identity_closed()
    if (spec.program_kind != "xtb" or spec.adapter_id != "auto-g16-v31-xtb"
            or spec.adapter_contract_version != 3
            or copy_data(spec.program_data) != {**material.program_data, "completion_mode": "receipt-on-absence-v1"}
            or copy_data(spec.exact_inputs) != [{"logical_role": "structure", **material.input_identity}]):
        raise Rejected("STALE")
