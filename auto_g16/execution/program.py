"""Closed offline xTB/CREST execution successor for Auto-G16 V31."""

from __future__ import annotations

# Frozen observation vocabulary; pure snapshot restoration has no Transport
# implementation dependency. Compatibility is checked at the integration seam.
_PROGRAM_EFFECT_RECEIPT_TYPE = "v31-program-effect-receipt/1"

from collections.abc import Mapping
from dataclasses import dataclass, field
from hashlib import sha256
import re
import shlex
from typing import Callable, Final

from auto_g16.core import AttemptState, CalculationPlan, ResourceSpec, SQLiteRuntimeStore

from ._identity import (
    ExecutionValueError,
    freeze_mapping,
    require_positive_integer,
    require_sha256,
    require_text,
    semantic_id,
    semantic_sha256,
)
from ._paths import (
    require_contained,
    validate_portable_name,
    validate_posix_path,
)
from .models import (
    ResolvedResourceRequest,
    ResolvedServerProfile,
    WorkspaceBinding,
    _XTB_RUNTIME_DATA_MANIFEST_NAME,
)
from .project_provisioning import (
    ProjectPhysicalBinding,
    _ProjectProvisioningService,
    _SYNTHETIC_TEST_HARNESS_PRIVILEGE,
)


_PROGRAM_KINDS: Final = frozenset({"gaussian", "xtb", "crest"})
_CREST_SUPPORTED_V2_OPTION_TOKENS: Final = frozenset(
    {
        "-v3",
        "-gfn1",
        "-gfn2",
        "-chrg",
        "-uhf",
        "-mdlen",
        "-ewin",
        "-rthr",
        "-temp",
        "-tnmd",
        "-cross",
    }
)
_SYNTHETIC_SERVER_EXECUTABLE_PATHS: Final = {
    "gaussian": "/opt/auto-g16-fixtures/bin/g16",
    "xtb": "/opt/auto-g16-fixtures/bin/xtb",
    "crest": "/opt/auto-g16-fixtures/bin/crest",
}
_TOKEN: Final = re.compile(r"^[A-Za-z0-9_./:@%+=,-]+$")
_OUTPUT_FIELDS: Final = {
    "logical_role",
    "portable_name",
    "format",
    "cardinality",
    "max_size_bytes",
    "capture_policy",
    "completeness",
}
_INPUT_FIELDS: Final = {"logical_role", "portable_name", "format", "sha256", "size_bytes"}
_INVOCATION_FIELDS: Final = {"executable_identity", "argv", "stdin", "environment"}
_SNAPSHOT_PAYLOAD_FIELDS: Final = {
    "attempt_id",
    "calculation_plan_id",
    "calculation_plan_revision",
    "program_execution_spec_id",
    "program_execution_spec_payload_sha256",
    "project_physical_binding_id",
    "resolved_resource_request_id",
    "resolved_server_profile_id",
    "workspace_binding_id",
    "cwd_binding",
    "scheduler_artifacts",
}


def _exact_keys(value: Mapping[str, object], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise ExecutionValueError(f"{label} must have an exact closed field set")


def _nonnegative_integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ExecutionValueError(f"{label} must be a non-negative integer")
    return value


def _fixed_milli(value: object, label: str) -> str:
    integer = require_positive_integer(value, label)
    whole, fraction = divmod(integer, 1000)
    return f"{whole}.{fraction:03d}"


def _integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ExecutionValueError(f"{label} must be an integer")
    return value


def _token(value: object, label: str) -> str:
    text = require_text(value, label)
    if _TOKEN.fullmatch(text) is None or any(character in text for character in ";&|<>$`(){}[]!\\\"'"):
        raise ExecutionValueError(f"{label} must be one non-shell argv token")
    return text


def _validated_input(value: Mapping[str, object], index: int) -> Mapping[str, object]:
    label = f"exact_inputs[{index}]"
    _exact_keys(value, _INPUT_FIELDS, label)
    for key in ("logical_role", "portable_name", "format"):
        require_text(value[key], f"{label}.{key}")
    validate_portable_name(value["portable_name"], f"{label}.portable_name")  # type: ignore[arg-type]
    require_sha256(value["sha256"], f"{label}.sha256")
    require_positive_integer(value["size_bytes"], f"{label}.size_bytes")
    return freeze_mapping(dict(value), label)


def _validated_output(value: Mapping[str, object], index: int, group: str) -> Mapping[str, object]:
    label = f"{group}[{index}]"
    _exact_keys(value, _OUTPUT_FIELDS, label)
    for key in ("logical_role", "portable_name", "format"):
        require_text(value[key], f"{label}.{key}")
    validate_portable_name(value["portable_name"], f"{label}.portable_name")  # type: ignore[arg-type]
    if value["cardinality"] not in {"exactly-one", "zero-or-one"}:
        raise ExecutionValueError(f"{label}.cardinality is outside the closed set")
    require_positive_integer(value["max_size_bytes"], f"{label}.max_size_bytes")
    if value["capture_policy"] != "exact-file":
        raise ExecutionValueError(f"{label}.capture_policy must be exact-file")
    if value["completeness"] not in {"program-success", "explicit-absence"}:
        raise ExecutionValueError(f"{label}.completeness is outside the closed set")
    return freeze_mapping(dict(value), label)


def _validate_invocation(
    value: Mapping[str, object],
    program_kind: str,
    adapter_contract_version: int,
) -> Mapping[str, object]:
    _exact_keys(value, _INVOCATION_FIELDS, "invocation")
    executable = value["executable_identity"]
    if not isinstance(executable, Mapping):
        raise ExecutionValueError("invocation.executable_identity must be a closed mapping")
    _exact_keys(
        executable,
        {"absolute_path", "size_bytes", "sha256"},
        "executable_identity",
    )
    executable_path = validate_posix_path(
        require_text(executable["absolute_path"], "executable_identity.absolute_path"),
        "executable_identity.absolute_path",
    )
    if executable_path.startswith("/opt/auto-g16-fixtures/") and executable_path != _SYNTHETIC_SERVER_EXECUTABLE_PATHS.get(program_kind):
        raise ExecutionValueError(
            "executable path is not the exact qualified synthetic server identity"
        )
    require_positive_integer(executable["size_bytes"], "executable_identity.size_bytes")
    require_sha256(executable["sha256"], "executable_identity.sha256")
    argv = value["argv"]
    if not isinstance(argv, tuple) or not argv:
        raise ExecutionValueError("invocation.argv must be an ordered non-empty tuple")
    for index, item in enumerate(argv):
        _token(item, f"invocation.argv[{index}]")
    if argv[0] != executable_path:
        raise ExecutionValueError("argv[0] must be the exact bound absolute executable path")
    stdin = value["stdin"]
    if not isinstance(stdin, Mapping):
        raise ExecutionValueError("invocation.stdin must be a closed mapping")
    _exact_keys(stdin, {"mode", "logical_role"}, "invocation.stdin")
    expected_stdin = (
        {"mode": "exact-input", "logical_role": "gaussian-input"}
        if program_kind == "gaussian" and adapter_contract_version in (3, 4, 5)
        else {"mode": "none", "logical_role": None}
    )
    if dict(stdin) != expected_stdin:
        raise ExecutionValueError("invocation stdin differs from its closed adapter")
    omp_environment = freeze_mapping(
        {"name": "OMP_NUM_THREADS", "source": "resolved-resource-request.cores"},
        "OMP_NUM_THREADS",
    )
    expected_environment = (omp_environment,)
    if (program_kind == "xtb" and adapter_contract_version in (2, 3)) or (program_kind == "crest" and adapter_contract_version == 3):
        expected_environment = (
            omp_environment,
            freeze_mapping(
                {
                    "name": "XTBPATH",
                    "source": (
                        "resolved-server-profile.platform_paths.xtb_data_path"
                    ),
                },
                "XTBPATH",
            ),
        )
    if value["environment"] != expected_environment:
        raise ExecutionValueError("invocation environment is not the exact closed adapter input")
    return freeze_mapping(dict(value), "invocation")


def _validate_xtb_data(value: Mapping[str, object]) -> Mapping[str, object]:
    _exact_keys(value, {"model", "charge", "unpaired_electrons", "task", "solvent"}, "xtb program_data")
    if value["model"] not in {"gfn1", "gfn2"}:
        raise ExecutionValueError("xTB model is outside the closed adapter set")
    _integer(value["charge"], "xtb charge")
    _nonnegative_integer(value["unpaired_electrons"], "xtb unpaired_electrons")
    if value["task"] not in {"single-point", "optimize"}:
        raise ExecutionValueError("xTB task is outside the closed adapter set")
    if value["solvent"] is not None:
        validate_portable_name(require_text(value["solvent"], "xtb solvent"), "xtb solvent")
    return freeze_mapping(dict(value), "xtb program_data")


def _validate_gaussian_data(value: Mapping[str, object]) -> Mapping[str, object]:
    _exact_keys(value, {"stage", "completion_mode"}, "Gaussian program_data")
    if value["stage"] not in {"opt", "freq"}:
        raise ExecutionValueError("Gaussian stage is outside the closed adapter set")
    from ._program_completion import _MODE
    if value["completion_mode"] != _MODE:
        raise ExecutionValueError("unknown completion mode")
    return freeze_mapping(dict(value), "Gaussian program_data")


def _gaussian_route_directives(route: str) -> tuple[tuple[str, frozenset[str]], ...]:
    """Tokenize Gaussian keywords enough to close checkpoint-reading options."""

    directives: list[tuple[str, frozenset[str]]] = []
    index = 0
    while index < len(route):
        match = re.match(r"[a-z][a-z0-9]*", route[index:])
        if match is None:
            index += 1
            continue
        name = match.group(0)
        index += len(name)
        cursor = index
        while cursor < len(route) and route[cursor].isspace():
            cursor += 1
        has_equals = cursor < len(route) and route[cursor] == "="
        if has_equals:
            cursor += 1
            while cursor < len(route) and route[cursor].isspace():
                cursor += 1
        sensitive = name in {"geom", "guess", "opt", "freq"}
        values: frozenset[str] = frozenset()
        if cursor < len(route) and route[cursor] == "(":
            end = route.find(")", cursor + 1)
            if sensitive and (end < 0 or "(" in route[cursor + 1 : end]):
                raise ExecutionValueError("Gaussian route option list is malformed")
            if end < 0:
                index = len(route)
            else:
                if sensitive:
                    values = frozenset(
                        re.findall(r"[a-z][a-z0-9]*", route[cursor + 1 : end])
                    )
                index = end + 1
        elif has_equals:
            if sensitive:
                value = re.match(r"[a-z][a-z0-9]*", route[cursor:])
                if value is None:
                    raise ExecutionValueError("Gaussian route option is malformed")
                values = frozenset({value.group(0)})
                index = cursor + len(value.group(0))
            else:
                end = cursor
                while end < len(route) and not route[end].isspace():
                    end += 1
                index = end if end > cursor else cursor + 1
        directives.append((name, values))
    return tuple(directives)


def _validate_gaussian_input(
    input_name: str, input_bytes: bytes, data: Mapping[str, object]
) -> None:
    if not input_name.lower().endswith(".gjf"):
        raise ExecutionValueError("Gaussian input must use the .gjf suffix")
    if b"\x00" in input_bytes or b"\r" in input_bytes:
        raise ExecutionValueError("Gaussian input must be canonical UTF-8 text")
    try:
        text = input_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ExecutionValueError("Gaussian input must be canonical UTF-8 text") from exc
    lines = text.split("\n")
    if any(line.strip().lower() == "--link1--" for line in lines):
        raise ExecutionValueError("Gaussian successor accepts one job only")
    position = 0
    while position < len(lines) and not lines[position].strip():
        position += 1
    link0_count = 0
    while position < len(lines) and lines[position].lstrip().startswith("%"):
        if lines[position].strip().lower() != "%chk=gaussian.chk":
            raise ExecutionValueError("Gaussian Link0 authority is outside the closed set")
        link0_count += 1
        if link0_count > 1:
            raise ExecutionValueError("Gaussian Link0 authority is duplicated")
        position += 1
    if position >= len(lines) or not lines[position].lstrip().startswith("#"):
        raise ExecutionValueError("Gaussian input requires one route section")
    route_lines = []
    while position < len(lines) and lines[position].strip():
        route_lines.append(lines[position].strip())
        position += 1
    route = " ".join(route_lines).lower()
    directives = _gaussian_route_directives(route)
    if (
        any(
            name == "geom"
            and bool({"check", "allcheck", "checkpoint"}.intersection(values))
            for name, values in directives
        )
        or any(name == "guess" and "read" in values for name, values in directives)
        or any(name in {"opt", "freq"} and bool({"readfc", "restart"}.intersection(values)) for name, values in directives)
        or any(name in {"chkbasis", "readfc"} for name, _values in directives)
    ):
        raise ExecutionValueError("Gaussian input depends on checkpoint state")
    has_opt = re.search(r"(?:^|[\s])opt(?:\s*=|\s*\(|\s|$)", route) is not None
    has_freq = re.search(r"(?:^|[\s])freq(?:\s*=|\s*\(|\s|$)", route) is not None
    if (data["stage"] == "opt" and (not has_opt or has_freq)) or (
        data["stage"] == "freq" and (not has_freq or has_opt)
    ):
        raise ExecutionValueError("Gaussian route differs from the exact stage")
    while position < len(lines) and not lines[position].strip():
        position += 1
    if position >= len(lines) or not lines[position].strip():
        raise ExecutionValueError("Gaussian input requires a title")
    position += 1
    while position < len(lines) and not lines[position].strip():
        position += 1
    if position >= len(lines) or re.fullmatch(
        r"[+-]?[0-9]+[ \t]+[1-9][0-9]*", lines[position].strip()
    ) is None:
        raise ExecutionValueError("Gaussian input requires charge and multiplicity")
    position += 1
    atoms = 0
    number = r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[EeDd][+-]?[0-9]+)?"
    atom = re.compile(
        rf"(?:[A-Z][a-z]?|[1-9][0-9]?|1(?:0[0-9]|1[0-8]))"
        rf"\s+{number}\s+{number}\s+{number}"
    )
    while position < len(lines) and lines[position].strip():
        if atom.fullmatch(lines[position].strip()) is None:
            raise ExecutionValueError("Gaussian input coordinates are not closed Cartesian rows")
        atoms += 1
        position += 1
    if atoms == 0 or any(line.strip() for line in lines[position:]):
        raise ExecutionValueError("Gaussian input must end after one Cartesian geometry")


def _render_gaussian(
    executable: Mapping[str, object],
    input_name: str,
    data: Mapping[str, object],
) -> tuple[Mapping[str, object], tuple[Mapping[str, object], ...], tuple[Mapping[str, object], ...]]:
    required, optional = _outputs(
        required=(("program-log", "gaussian.log", "text"),),
        optional=(("checkpoint", "gaussian.chk", "gaussian-checkpoint"),),
    )
    return (
        _invocation(
            executable,
            (str(executable["absolute_path"]),),
            program_kind="gaussian",
            stdin={"mode": "exact-input", "logical_role": "gaussian-input"},
        ),
        required,
        optional,
    )


def _validate_xtb_completion_data(value: Mapping[str, object]) -> Mapping[str, object]:
    from ._program_completion import _MODE
    if value.get("completion_mode") != _MODE:
        raise ExecutionValueError("unknown completion mode")
    _validate_xtb_data({key: item for key, item in value.items() if key != "completion_mode"})
    return freeze_mapping(dict(value), "xtb completion program_data")


def _validate_crest_v1_data(value: Mapping[str, object]) -> Mapping[str, object]:
    _exact_keys(
        value,
        {
            "model",
            "search_mode",
            "preset",
            "charge",
            "unpaired_electrons",
            "energy_window_millikcal_per_mol",
            "rmsd_threshold_milliangstrom",
            "temperature_millikelvin",
            "random_seed",
        },
        "CREST program_data",
    )
    if value["model"] not in {"gfn1", "gfn2"}:
        raise ExecutionValueError("CREST model is outside the closed adapter set")
    if value["search_mode"] != "ttconf" or value["preset"] not in {
        "fast",
        "normal",
        "accurate",
    }:
        raise ExecutionValueError("CREST search mode/preset is outside the closed adapter set")
    _integer(value["charge"], "CREST charge")
    _nonnegative_integer(value["unpaired_electrons"], "CREST unpaired_electrons")
    require_positive_integer(value["energy_window_millikcal_per_mol"], "CREST energy window")
    require_positive_integer(value["rmsd_threshold_milliangstrom"], "CREST RMSD threshold")
    require_positive_integer(value["temperature_millikelvin"], "CREST temperature")
    _nonnegative_integer(value["random_seed"], "CREST random seed")
    return freeze_mapping(dict(value), "CREST program_data")


def _validate_crest_imtd_gc_v2_data(
    value: Mapping[str, object],
) -> Mapping[str, object]:
    _exact_keys(
        value,
        {
            "provider",
            "sampling_mode",
            "engine_version",
            "runtype_selector",
            "model",
            "charge",
            "unpaired_electrons",
            "metadynamics_length_millipicoseconds",
            "cregen_energy_window_millikcal_per_mol",
            "cregen_rmsd_threshold_milliangstrom",
            "cregen_temperature_millikelvin",
            "normal_md_temperature_millikelvin",
            "stochastic_policy",
            "sampling_configuration_identity",
        },
        "CREST iMTD-GC v2 program_data",
    )
    if value["provider"] != "crest" or value["sampling_mode"] != "imtd-gc":
        raise ExecutionValueError("CREST v2 provider/mode must be exact iMTD-GC")
    if value["engine_version"] != "3.0.2":
        raise ExecutionValueError("CREST v2 supports exactly engine version 3.0.2")
    if value["runtype_selector"] != "-v3":
        raise ExecutionValueError(
            "CREST v2 requires the explicit version-qualified -v3 iMTD-GC selector"
        )
    if value["model"] not in {"gfn1", "gfn2"}:
        raise ExecutionValueError("CREST model is outside the closed adapter set")
    _integer(value["charge"], "CREST charge")
    _nonnegative_integer(value["unpaired_electrons"], "CREST unpaired electrons")
    for key, label in (
        ("metadynamics_length_millipicoseconds", "CREST MTD length"),
        ("cregen_energy_window_millikcal_per_mol", "CREGEN energy window"),
        ("cregen_rmsd_threshold_milliangstrom", "CREGEN RMSD threshold"),
        ("cregen_temperature_millikelvin", "CREGEN sorting temperature"),
        ("normal_md_temperature_millikelvin", "CREST normal-MD temperature"),
    ):
        require_positive_integer(value[key], label)
    stochastic = value["stochastic_policy"]
    if not isinstance(stochastic, Mapping):
        raise ExecutionValueError("CREST stochastic_policy must be a closed mapping")
    _exact_keys(
        stochastic,
        {"mode", "seed", "replay_semantics"},
        "CREST stochastic_policy",
    )
    if (
        stochastic["mode"] != "engine_managed_stochastic"
        or stochastic["seed"] is not None
        or stochastic["replay_semantics"]
        != "configuration_replay_not_bitwise_trajectory_replay"
    ):
        raise ExecutionValueError(
            "CREST v2 stochasticity must use the closed engine-managed policy"
        )
    require_sha256(
        value["sampling_configuration_identity"],
        "CREST sampling_configuration_identity",
    )
    return freeze_mapping(dict(value), "CREST iMTD-GC v2 program_data")


def _outputs(*, required: tuple[tuple[str, str, str], ...], optional: tuple[tuple[str, str, str], ...]) -> tuple[tuple[Mapping[str, object], ...], tuple[Mapping[str, object], ...]]:
    required_values = tuple(
        freeze_mapping(
            {
                "logical_role": role,
                "portable_name": name,
                "format": format_name,
                "cardinality": "exactly-one",
                "max_size_bytes": 64 * 1024 * 1024,
                "capture_policy": "exact-file",
                "completeness": "program-success",
            },
            f"required output {role}",
        )
        for role, name, format_name in required
    )
    optional_values = tuple(
        freeze_mapping(
            {
                "logical_role": role,
                "portable_name": name,
                "format": format_name,
                "cardinality": "zero-or-one",
                "max_size_bytes": 64 * 1024 * 1024,
                "capture_policy": "exact-file",
                "completeness": "explicit-absence",
            },
            f"optional output {role}",
        )
        for role, name, format_name in optional
    )
    return required_values, optional_values


def _render_xtb(
    executable: Mapping[str, object],
    input_name: str,
    data: Mapping[str, object],
) -> tuple[Mapping[str, object], tuple[Mapping[str, object], ...], tuple[Mapping[str, object], ...]]:
    argv = [str(executable["absolute_path"]), input_name, "--gfn", str(data["model"])[-1], "--chrg", str(data["charge"]), "--uhf", str(data["unpaired_electrons"])]
    if data["task"] == "optimize":
        argv.append("--opt")
    if data["solvent"] is not None:
        argv.extend(("--alpb", str(data["solvent"])))
    required = (("program-log", "xtb.out", "text"),)
    optional = (("optimized-geometry", "xtbopt.xyz", "xyz"),)
    if data["task"] == "optimize":
        required += (("optimized-geometry", "xtbopt.xyz", "xyz"),)
        optional = ()
    required_values, optional_values = _outputs(required=required, optional=optional)
    return _invocation(
        executable,
        tuple(argv),
        program_kind="xtb",
        xtb_data_authority=True,
    ), required_values, optional_values


def _render_xtb_v1(
    executable: Mapping[str, object],
    input_name: str,
    data: Mapping[str, object],
) -> tuple[Mapping[str, object], tuple[Mapping[str, object], ...], tuple[Mapping[str, object], ...]]:
    invocation, required, optional = _render_xtb(executable, input_name, data)
    return (
        _invocation(
            executable,
            tuple(invocation["argv"]),
            program_kind="xtb",
            xtb_data_authority=False,
        ),
        required,
        optional,
    )


def _render_crest_v1(
    executable: Mapping[str, object],
    input_name: str,
    data: Mapping[str, object],
) -> tuple[Mapping[str, object], tuple[Mapping[str, object], ...], tuple[Mapping[str, object], ...]]:
    argv = (
        str(executable["absolute_path"]),
        input_name,
        "-ttconf",
        str(data["preset"]),
        f"--{data['model']}",
        "--chrg",
        str(data["charge"]),
        "--uhf",
        str(data["unpaired_electrons"]),
        "-ttewin",
        _fixed_milli(data["energy_window_millikcal_per_mol"], "CREST energy window"),
        "-ttseed",
        str(data["random_seed"]),
        "--rthr",
        _fixed_milli(data["rmsd_threshold_milliangstrom"], "CREST RMSD threshold"),
        "--temp",
        _fixed_milli(data["temperature_millikelvin"], "CREST temperature"),
    )
    required, optional = _outputs(
        required=(
            ("program-log", "crest.out", "text"),
            ("conformer-ensemble", "crest_conformers.xyz", "xyz-trajectory"),
        ),
        optional=(("conformer-energies", "crest.energies", "text"),),
    )
    return _invocation(executable, argv, program_kind="crest"), required, optional


def _render_crest_imtd_gc_v2(
    executable: Mapping[str, object],
    input_name: str,
    data: Mapping[str, object],
) -> tuple[Mapping[str, object], tuple[Mapping[str, object], ...], tuple[Mapping[str, object], ...]]:
    # CREST 3.0.2 documents -v3 as an explicit iMTD-GC runtype selector.
    # That release exposes no user-facing iMTD-GC integer seed option.
    options = (
        (str(data["runtype_selector"]), ()),
        ("-cross", ()),
        (f"-{data['model']}", ()),
        ("-chrg", (str(data["charge"]),)),
        ("-uhf", (str(data["unpaired_electrons"]),)),
        (
            "-mdlen",
            (
                _fixed_milli(
                    data["metadynamics_length_millipicoseconds"],
                    "CREST MTD length",
                ),
            ),
        ),
        (
            "-ewin",
            (
                _fixed_milli(
                    data["cregen_energy_window_millikcal_per_mol"],
                    "CREGEN energy window",
                ),
            ),
        ),
        (
            "-rthr",
            (
                _fixed_milli(
                    data["cregen_rmsd_threshold_milliangstrom"],
                    "CREGEN RMSD threshold",
                ),
            ),
        ),
        (
            "-temp",
            (
                _fixed_milli(
                    data["cregen_temperature_millikelvin"],
                    "CREGEN sorting temperature",
                ),
            ),
        ),
        (
            "-tnmd",
            (
                _fixed_milli(
                    data["normal_md_temperature_millikelvin"],
                    "CREST normal-MD temperature",
                ),
            ),
        ),
    )
    _validate_crest_v2_option_tokens(options)
    argv = (
        str(executable["absolute_path"]),
        input_name,
        *(item for option, values in options for item in (option, *values)),
    )
    required, optional = _outputs(
        required=(
            ("program-log", "crest.out", "text"),
            ("conformer-ensemble", "crest_conformers.xyz", "xyz-trajectory"),
        ),
        optional=(("conformer-energies", "crest.energies", "text"),),
    )
    return _invocation(executable, argv, program_kind="crest"), required, optional


def _validate_crest_v2_option_tokens(
    options: tuple[tuple[str, tuple[str, ...]], ...],
) -> None:
    """Validate structured CREST v2 options before argv flattening."""

    for option, _values in options:
        if option.startswith("--") or option not in _CREST_SUPPORTED_V2_OPTION_TOKENS:
            raise ExecutionValueError(
                "CREST v2 option token is outside the exact single-dash allowlist"
            )


def _invocation(
    executable: Mapping[str, object],
    argv: tuple[str, ...],
    *,
    program_kind: str,
    xtb_data_authority: bool = False,
    stdin: Mapping[str, object] | None = None,
) -> Mapping[str, object]:
    environment: tuple[Mapping[str, object], ...] = (
        freeze_mapping(
            {
                "name": "OMP_NUM_THREADS",
                "source": "resolved-resource-request.cores",
            },
            "OMP_NUM_THREADS",
        ),
    )
    if xtb_data_authority:
        environment += (
            freeze_mapping(
                {
                    "name": "XTBPATH",
                    "source": (
                        "resolved-server-profile.platform_paths.xtb_data_path"
                    ),
                },
                "XTBPATH",
            ),
        )
    return freeze_mapping(
        {
            "executable_identity": executable,
            "argv": argv,
            "stdin": dict(stdin or {"mode": "none", "logical_role": None}),
            "environment": environment,
        },
        "closed program invocation",
    )


_Adapter = tuple[
    str,
    int,
    Callable[[Mapping[str, object]], Mapping[str, object]],
    Callable[[Mapping[str, object], str, Mapping[str, object]], tuple[Mapping[str, object], tuple[Mapping[str, object], ...], tuple[Mapping[str, object], ...]]],
]
from . import _crest_completion

_ADAPTER_REGISTRY: Final[Mapping[tuple[str, str, int], _Adapter]] = {
    ("gaussian", "auto-g16-v31-gaussian", 5): (
        "auto-g16-v31-gaussian", 5, _validate_gaussian_data, _render_gaussian,
    ),
    ("gaussian", "auto-g16-v31-gaussian", 4): (
        "auto-g16-v31-gaussian", 4, _validate_gaussian_data, _render_gaussian,
    ),
    ("gaussian", "auto-g16-v31-gaussian", 3): (
        "auto-g16-v31-gaussian", 3, _validate_gaussian_data, _render_gaussian,
    ),
    ("crest", "auto-g16-v31-crest", 3): (
        "auto-g16-v31-crest", 3, _crest_completion._validate_data, _crest_completion._render,
    ),
    ("xtb", "auto-g16-v31-xtb", 3): (
        "auto-g16-v31-xtb", 3, _validate_xtb_completion_data, _render_xtb,
    ),
    ("xtb", "auto-g16-v31-xtb", 1): (
        "auto-g16-v31-xtb",
        1,
        _validate_xtb_data,
        _render_xtb_v1,
    ),
    ("xtb", "auto-g16-v31-xtb", 2): (
        "auto-g16-v31-xtb",
        2,
        _validate_xtb_data,
        _render_xtb,
    ),
    ("crest", "auto-g16-v31-crest", 1): (
        "auto-g16-v31-crest",
        1,
        _validate_crest_v1_data,
        _render_crest_v1,
    ),
    ("crest", "auto-g16-v31-crest", 2): (
        "auto-g16-v31-crest",
        2,
        _validate_crest_imtd_gc_v2_data,
        _render_crest_imtd_gc_v2,
    ),
}
_INITIAL_ADAPTER_KEYS: Final[Mapping[str, tuple[str, str, int] | None]] = {
    "gaussian": None,
    "xtb": ("xtb", "auto-g16-v31-xtb", 2),
    "crest": ("crest", "auto-g16-v31-crest", 2),
}


@dataclass(frozen=True, slots=True, kw_only=True, init=False)
class ProgramExecutionSpec:
    program_execution_spec_id: str
    program_kind: str
    adapter_id: str
    adapter_contract_version: int
    exact_inputs: tuple[Mapping[str, object], ...]
    program_data: Mapping[str, object]
    invocation: Mapping[str, object]
    required_outputs: tuple[Mapping[str, object], ...]
    optional_outputs: tuple[Mapping[str, object], ...]
    _identity_payload: Mapping[str, object] = field(repr=False, compare=False)

    def __init__(self) -> None:
        raise TypeError("ProgramExecutionSpec is created only by the closed adapter registry")

    @classmethod
    def _from_closed(
        cls,
        *,
        program_kind: str,
        adapter_id: str,
        adapter_contract_version: int,
        exact_inputs: tuple[Mapping[str, object], ...],
        program_data: Mapping[str, object],
        invocation: Mapping[str, object],
        required_outputs: tuple[Mapping[str, object], ...],
        optional_outputs: tuple[Mapping[str, object], ...],
    ) -> ProgramExecutionSpec:
        if program_kind not in _PROGRAM_KINDS:
            raise ExecutionValueError("program_kind is outside the closed V31 registry")
        adapter = _ADAPTER_REGISTRY.get(
            (program_kind, adapter_id, adapter_contract_version)
        )
        if adapter is None:
            if program_kind == "gaussian":
                raise ExecutionValueError(
                    "Gaussian successor is reserved but not implemented"
                )
            raise ExecutionValueError("unknown private adapter identity or version")
        expected_id, expected_version, validate_data, renderer = adapter
        if adapter_id != expected_id or adapter_contract_version != expected_version:
            raise ExecutionValueError("unknown private adapter identity or version")
        if not isinstance(exact_inputs, tuple) or len(exact_inputs) != 1:
            raise ExecutionValueError("closed adapters require exactly one immutable input")
        inputs = tuple(_validated_input(item, index) for index, item in enumerate(exact_inputs))
        expected_input = (
            ("gaussian-input", "gaussian-gjf")
            if program_kind == "gaussian"
            else ("structure", "xyz")
        )
        if (inputs[0]["logical_role"], inputs[0]["format"]) != expected_input:
            raise ExecutionValueError("program input declaration differs from its adapter")
        data = validate_data(program_data)
        if program_kind in {"gaussian", "xtb", "crest"} and adapter_contract_version in (3, 4, 5):
            from ._program_completion import _RESERVED_NAMES
            names = [item["portable_name"] for item in (*inputs, *required_outputs, *optional_outputs)]
            if len(set(names)) != len(names) or any(
                name in _RESERVED_NAMES or name == f"{program_kind}.pbs"
                or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", str(name)) is None
                for name in names
            ):
                raise ExecutionValueError("completion file names collide or are unsafe")
        closed_invocation = _validate_invocation(
            invocation, program_kind, adapter_contract_version
        )
        required = tuple(_validated_output(item, index, "required_outputs") for index, item in enumerate(required_outputs))
        optional = tuple(_validated_output(item, index, "optional_outputs") for index, item in enumerate(optional_outputs))
        if not required:
            raise ExecutionValueError("required_outputs must be non-empty")
        output_keys = tuple((item["logical_role"], item["portable_name"]) for item in (*required, *optional))
        if len(set(output_keys)) != len(output_keys):
            raise ExecutionValueError("required and optional outputs must be disjoint")
        expected_invocation, expected_required, expected_optional = renderer(
            closed_invocation["executable_identity"],
            str(inputs[0]["portable_name"]),
            data,
        )
        if (
            closed_invocation != expected_invocation
            or required != expected_required
            or optional != expected_optional
        ):
            raise ExecutionValueError(
                "ProgramExecutionSpec invocation/output semantics differ from its exact adapter"
            )
        payload = freeze_mapping(
            {
                "program_kind": program_kind,
                "adapter_id": adapter_id,
                "adapter_contract_version": adapter_contract_version,
                "exact_inputs": inputs,
                "program_data": data,
                "invocation": closed_invocation,
                "required_outputs": required,
                "optional_outputs": optional,
            },
            "ProgramExecutionSpec identity payload",
        )
        value = object.__new__(cls)
        for name, item in payload.items():
            object.__setattr__(value, name, item)
        object.__setattr__(value, "_identity_payload", payload)
        object.__setattr__(value, "program_execution_spec_id", semantic_id("program-execution-spec", payload))
        return value

    def semantic_payload(self) -> Mapping[str, object]:
        return freeze_mapping(
            {"program_execution_spec_id": self.program_execution_spec_id, **{key: self._identity_payload[key] for key in self._identity_payload}},
            "ProgramExecutionSpec",
        )

    def assert_identity_closed(self) -> None:
        rebuilt = ProgramExecutionSpec._from_closed(
            program_kind=self.program_kind,
            adapter_id=self.adapter_id,
            adapter_contract_version=self.adapter_contract_version,
            exact_inputs=self.exact_inputs,
            program_data=self.program_data,
            invocation=self.invocation,
            required_outputs=self.required_outputs,
            optional_outputs=self.optional_outputs,
        )
        if rebuilt.semantic_payload() != self.semantic_payload():
            raise ExecutionValueError("ProgramExecutionSpec identity is stale")


def _prepare_program_execution_spec(
    *,
    program_kind: str,
    executable_path: str,
    executable_size_bytes: int,
    executable_sha256: str,
    input_name: str,
    input_bytes: bytes,
    program_data: Mapping[str, object],
    resolved_profile: ResolvedServerProfile | None = None,
    completion_mode: str | None = None,
    startup_mode: str | None = None,
) -> ProgramExecutionSpec:
    if program_kind not in _PROGRAM_KINDS:
        raise ExecutionValueError("unknown program kind")
    adapter_key = _INITIAL_ADAPTER_KEYS.get(program_kind)
    if completion_mode is not None:
        from ._program_completion import _MODE
        if program_kind not in {"gaussian", "xtb", "crest"} or completion_mode != _MODE or "completion_mode" in program_data:
            raise ExecutionValueError("unknown or duplicate explicit completion mode")
        adapter_key = (program_kind, f"auto-g16-v31-{program_kind}", 3)
        program_data = {**program_data, "completion_mode": completion_mode}
    if startup_mode is not None:
        from ._gaussian_startup import _Q_NAME as old_name
        from ._gaussian_file_carrier import _Q_NAME as file_name
        version = {"short-entry-physical-handoff-v1": (4, old_name), "short-entry-file-carrier-v2": (5, file_name)}.get(startup_mode)
        if program_kind != "gaussian" or version is None or completion_mode is None or resolved_profile is None or version[1] not in resolved_profile.runtime_identities:
            raise ExecutionValueError("Gaussian short entry requires explicit qualified selection")
        adapter_key = ("gaussian", "auto-g16-v31-gaussian", version[0])
    if adapter_key is None:
        if program_kind != "gaussian" or completion_mode is None:
            raise ExecutionValueError("Gaussian successor reserved route requires its exact completion mode")
    adapter = _ADAPTER_REGISTRY[adapter_key]
    validate_portable_name(input_name, "input_name")
    if not isinstance(input_bytes, bytes) or not input_bytes:
        raise ExecutionValueError("program input must be non-empty immutable bytes")
    adapter_id, version, validate_data, renderer = adapter
    data = validate_data(program_data)
    if program_kind == "gaussian":
        _validate_gaussian_input(input_name, input_bytes, data)
    absolute_path = validate_posix_path(executable_path, "executable_path")
    expected_path = _SYNTHETIC_SERVER_EXECUTABLE_PATHS.get(program_kind)
    if absolute_path != expected_path and resolved_profile is None:
        raise ExecutionValueError(
            "executable path is not the exact qualified synthetic server identity"
        )
    executable = freeze_mapping(
        {
            "absolute_path": absolute_path,
            "size_bytes": require_positive_integer(
                executable_size_bytes, "executable_size_bytes"
            ),
            "sha256": require_sha256(executable_sha256, "executable_sha256"),
        },
        "closed executable identity",
    )
    if program_kind == "xtb" and resolved_profile is None:
        raise ExecutionValueError(
            "xTB ProgramExecutionSpec requires resolved XTBPATH authority"
        )
    invocation, required, optional = renderer(executable, input_name, data)
    exact_input = freeze_mapping(
        {
            "logical_role": "gaussian-input" if program_kind == "gaussian" else "structure",
            "portable_name": input_name,
            "format": "gaussian-gjf" if program_kind == "gaussian" else "xyz",
            "sha256": sha256(input_bytes).hexdigest(),
            "size_bytes": len(input_bytes),
        },
        "structure input declaration",
    )
    spec = ProgramExecutionSpec._from_closed(
        program_kind=program_kind,
        adapter_id=adapter_id,
        adapter_contract_version=version,
        exact_inputs=(exact_input,),
        program_data=data,
        invocation=invocation,
        required_outputs=required,
        optional_outputs=optional,
    )
    if resolved_profile is not None:
        resolved_profile.assert_identity_closed()
        if program_kind == "gaussian":
            if absolute_path != resolved_profile.platform_paths.get(
                "gaussian_executable_path"
            ):
                raise ExecutionValueError(
                    "Gaussian executable path differs from the resolved profile"
                )
        else:
            _assert_executable_matches_resolved_profile(spec, resolved_profile)
    return spec


def _render_scheduler_artifact(
    spec: ProgramExecutionSpec,
    resources: ResolvedResourceRequest,
    profile: ResolvedServerProfile,
    *, prebinding_fields: Mapping[str, object] | None = None,
    completion_rendering_material: Mapping[str, object] | None = None,
    project_physical_binding: ProjectPhysicalBinding | None = None,
) -> tuple[Mapping[str, object], ...]:
    if _uses_completion_receipt(spec):
        from ._program_completion import _render_completion_scheduler
        if prebinding_fields is None or completion_rendering_material is None:
            raise ExecutionValueError("completion rendering material is required")
        return _render_completion_scheduler(spec, resources, profile, prebinding_fields, completion_rendering_material, project_binding=project_physical_binding)
    if completion_rendering_material is not None:
        raise ExecutionValueError("strict adapters reject completion rendering material")
    argv = tuple(spec.invocation["argv"])
    command = " ".join(shlex.quote(str(token)) for token in argv)
    program_log = next(
        str(item["portable_name"])
        for item in spec.required_outputs
        if item["logical_role"] == "program-log"
    )
    lines = [
        "#!/bin/bash",
        "# auto-g16-v31-scheduler/1",
        f"#PBS -l nodes=1:ppn={resources.cores}",
        f"#PBS -l mem={resources.memory_mb}mb",
        f"#PBS -l walltime={resources.walltime_seconds}",
    ]
    if resources.queue is not None:
        lines.append(f"#PBS -q {resources.queue}")
    lines.append(f"export OMP_NUM_THREADS={resources.cores}")
    if _uses_xtb_runtime_data_authority(spec):
        xtb_data_path = _assert_xtb_runtime_data_authority(profile)
        lines.append(f"export XTBPATH={shlex.quote(xtb_data_path)}")
    lines.append(f"exec {command} > {shlex.quote(program_log)} 2>&1")
    content = ("\n".join(lines) + "\n").encode("utf-8")
    return (
        freeze_mapping(
            {
                "logical_role": "scheduler-script",
                "portable_name": f"{spec.program_kind}.pbs",
                "format": "pbs-shell-utf8",
                "sha256": sha256(content).hexdigest(),
                "size_bytes": len(content),
                "content_utf8": content.decode("utf-8"),
            },
            "scheduler artifact",
        ),
    )


def _assert_executable_matches_resolved_profile(
    spec: ProgramExecutionSpec, profile: ResolvedServerProfile
) -> None:
    executable = spec.invocation["executable_identity"]
    if not isinstance(executable, Mapping):
        raise ExecutionValueError("ProgramExecutionSpec executable identity is malformed")
    path_key = f"{spec.program_kind}_executable_path"
    profile_path = profile.platform_paths.get(path_key)
    if not isinstance(profile_path, str):
        raise ExecutionValueError(
            "resolved target/profile lacks the exact program executable path authority"
        )
    qualified_profile_path = validate_posix_path(
        profile_path, f"resolved_server_profile.platform_paths.{path_key}"
    )
    if qualified_profile_path.startswith("/opt/auto-g16-fixtures/") and qualified_profile_path != _SYNTHETIC_SERVER_EXECUTABLE_PATHS.get(spec.program_kind):
        raise ExecutionValueError(
            "resolved target/profile executable path is not the qualified synthetic "
            "server identity"
        )
    if spec.program_kind == "gaussian":
        if executable["absolute_path"] != qualified_profile_path:
            raise ExecutionValueError(
                "Gaussian executable path differs from the resolved profile"
            )
        # The executable bytes are private installed material. Their exact size
        # and digest are bound by the closed Gaussian qualification carried into
        # snapshot rendering, where the invocation is compared before effects.
        return
    runtime_identity = profile.runtime_identities.get(spec.program_kind)
    if not isinstance(runtime_identity, Mapping):
        raise ExecutionValueError(
            "resolved target/profile lacks the exact program runtime identity"
        )
    if set(runtime_identity) != {"sha256", "size_bytes"}:
        raise ExecutionValueError(
            "resolved target/profile program runtime identity is not closed"
        )
    expected_executable = freeze_mapping(
        {
            "absolute_path": qualified_profile_path,
            "size_bytes": require_positive_integer(
                runtime_identity["size_bytes"],
                f"resolved_server_profile.runtime_identities.{spec.program_kind}.size_bytes",
            ),
            "sha256": require_sha256(
                runtime_identity["sha256"],
                f"resolved_server_profile.runtime_identities.{spec.program_kind}.sha256",
            ),
        },
        "resolved-profile executable authority",
    )
    if executable != expected_executable:
        raise ExecutionValueError(
            "bound executable differs from resolved profile executable authority"
        )
    if _uses_xtb_runtime_data_authority(spec):
        _assert_xtb_runtime_data_authority(profile)


def _uses_xtb_runtime_data_authority(spec: ProgramExecutionSpec) -> bool:
    return (
        spec.program_kind,
        spec.adapter_id,
        spec.adapter_contract_version,
    ) in {("xtb", "auto-g16-v31-xtb", 2), ("xtb", "auto-g16-v31-xtb", 3), ("crest", "auto-g16-v31-crest", 3)}


def _uses_completion_receipt(spec: ProgramExecutionSpec) -> bool:
    return (spec.program_kind, spec.adapter_id, spec.adapter_contract_version) in {("gaussian", "auto-g16-v31-gaussian", 3), ("gaussian", "auto-g16-v31-gaussian", 4), ("gaussian", "auto-g16-v31-gaussian", 5), ("xtb", "auto-g16-v31-xtb", 3), ("crest", "auto-g16-v31-crest", 3)}


def _assert_xtb_runtime_data_authority(profile: ResolvedServerProfile) -> str:
    data_path = profile.platform_paths.get("xtb_data_path")
    if not isinstance(data_path, str):
        raise ExecutionValueError(
            "resolved target/profile lacks the exact XTBPATH authority"
        )
    qualified_data_path = validate_posix_path(
        data_path, "resolved_server_profile.platform_paths.xtb_data_path"
    )
    manifest_identity = profile.runtime_identities.get(
        _XTB_RUNTIME_DATA_MANIFEST_NAME
    )
    if not isinstance(manifest_identity, Mapping) or set(manifest_identity) != {
        "sha256",
        "size_bytes",
    }:
        raise ExecutionValueError(
            "resolved target/profile lacks the exact xTB runtime-data identity"
        )
    require_sha256(
        manifest_identity["sha256"],
        "resolved_server_profile xTB runtime-data manifest sha256",
    )
    require_positive_integer(
        manifest_identity["size_bytes"],
        "resolved_server_profile xTB runtime-data manifest size_bytes",
    )
    return qualified_data_path


@dataclass(frozen=True, slots=True, kw_only=True, init=False)
class ProgramExecutionSnapshot:
    program_execution_snapshot_id: str
    attempt_id: str
    effect_intent_id: str
    calculation_plan_id: str
    calculation_plan_revision: int
    program_execution_spec: ProgramExecutionSpec
    program_execution_spec_payload_sha256: str
    project_physical_binding: ProjectPhysicalBinding
    resolved_resource_request: ResolvedResourceRequest
    resolved_server_profile: ResolvedServerProfile
    workspace_binding: WorkspaceBinding
    cwd_binding: Mapping[str, object]
    scheduler_artifacts: tuple[Mapping[str, object], ...]
    _identity_payload: Mapping[str, object] = field(repr=False, compare=False)

    def __init__(self) -> None:
        raise TypeError("ProgramExecutionSnapshot is created only by the successor service")

    @property
    def program_execution_spec_id(self) -> str:
        return self.program_execution_spec.program_execution_spec_id

    @property
    def project_physical_binding_id(self) -> str:
        return self.project_physical_binding.project_physical_binding_id

    @classmethod
    def _from_verified(cls, *, payload: Mapping[str, object], effect_intent_id: str, snapshot_id: str, spec: ProgramExecutionSpec, binding: ProjectPhysicalBinding, resources: ResolvedResourceRequest, profile: ResolvedServerProfile, workspace: WorkspaceBinding) -> ProgramExecutionSnapshot:
        value = object.__new__(cls)
        object.__setattr__(value, "program_execution_snapshot_id", snapshot_id)
        object.__setattr__(value, "effect_intent_id", effect_intent_id)
        object.__setattr__(value, "program_execution_spec", spec)
        object.__setattr__(value, "project_physical_binding", binding)
        object.__setattr__(value, "resolved_resource_request", resources)
        object.__setattr__(value, "resolved_server_profile", profile)
        object.__setattr__(value, "workspace_binding", workspace)
        for name in ("attempt_id", "calculation_plan_id", "calculation_plan_revision", "program_execution_spec_payload_sha256", "cwd_binding", "scheduler_artifacts"):
            object.__setattr__(value, name, payload[name])
        object.__setattr__(value, "_identity_payload", payload)
        return value

    def semantic_payload(self) -> Mapping[str, object]:
        return freeze_mapping(
            {"program_execution_snapshot_id": self.program_execution_snapshot_id, "effect_intent_id": self.effect_intent_id, **{key: self._identity_payload[key] for key in self._identity_payload}},
            "ProgramExecutionSnapshot",
        )

    def _approval_semantics(self) -> Mapping[str, object]:
        """Expanded review evidence; the existing snapshot identity is unchanged."""
        from . import _gaussian_startup, _gaussian_file_carrier
        short_version = self.program_execution_spec.adapter_contract_version if self.program_execution_spec.program_kind == "gaussian" else None
        return freeze_mapping({
            **dict(self.semantic_payload()),
            "program_execution_spec": self.program_execution_spec.semantic_payload(),
            "project_physical_binding": self.project_physical_binding.semantic_payload(),
            "resolved_resource_request": self.resolved_resource_request.semantic_payload(),
            "resolved_server_profile": self.resolved_server_profile.semantic_payload(),
            "resolved_server_profile_identity": self.resolved_server_profile._identity_payload,
            "workspace_binding": self.workspace_binding.semantic_payload(),
            "workspace_descriptor_anchor": {
                "approved_root": self.workspace_binding._local_approved_root,
                "parent_parts": self.workspace_binding._local_parent_parts,
                "component_identities": self.workspace_binding._local_component_identities,
            },
            **({"gaussian_startup_review": (_gaussian_file_carrier if short_version == 5 else _gaussian_startup)._review_disclosure(self)} if short_version in (4, 5) else {}),
        }, "expanded ProgramExecutionSnapshot review evidence")

    @staticmethod
    def _approval_field_set(*, gaussian_short: bool = False) -> frozenset[str]:
        return frozenset(_SNAPSHOT_PAYLOAD_FIELDS | {
            "program_execution_snapshot_id", "effect_intent_id", "program_execution_spec",
            "project_physical_binding", "resolved_resource_request", "resolved_server_profile",
            "resolved_server_profile_identity", "workspace_binding", "workspace_descriptor_anchor",
        } | ({"gaussian_startup_review"} if gaussian_short else set()))

    @staticmethod
    def _validate_approval_semantics(value: Mapping[str, object]) -> Mapping[str, object]:
        """Purely reclose persisted review bytes, without returning effect authority."""
        return _validate_program_review_semantics(value)

    def _completion_material(self) -> Mapping[str, object] | None:
        if not _uses_completion_receipt(self.program_execution_spec):
            return None
        from ._program_completion import _material_from_artifact
        return _material_from_artifact(self.scheduler_artifacts, self.resolved_server_profile)

    def _assert_current_core(self, store: SQLiteRuntimeStore) -> None:
        self.assert_identity_closed()
        attempt = store.load_attempt(self.attempt_id)
        task = store.load_task(attempt.task_id)
        workflow = store.load_workflow_run(task.workflow_run_id)
        project = store.load_project(workflow.project_id)
        plan = store.load_calculation_plan(self.calculation_plan_id)
        resource = store.load_resource_spec(self.resolved_resource_request.resource_spec_id)
        if (
            plan.task_id != task.task_id or plan.revision != self.calculation_plan_revision
            or resource.task_id != task.task_id
            or self.project_physical_binding.project_id != project.project_id
            or self.workspace_binding.project_id != project.project_id
        ):
            raise ExecutionValueError("ProgramExecutionSnapshot differs from current Core records")

    def assert_identity_closed(self) -> None:
        self.program_execution_spec.assert_identity_closed()
        self.project_physical_binding.assert_identity_closed()
        self.resolved_resource_request.assert_identity_closed()
        self.resolved_server_profile.assert_identity_closed()
        self.workspace_binding.assert_identity_closed()
        if set(self._identity_payload) != _SNAPSHOT_PAYLOAD_FIELDS:
            raise ExecutionValueError(
                "ProgramExecutionSnapshot payload has an invalid closed field set"
            )
        spec_digest = semantic_sha256(self.program_execution_spec.semantic_payload())
        if spec_digest != self.program_execution_spec_payload_sha256:
            raise ExecutionValueError("ProgramExecutionSpec payload hash is stale")
        _assert_executable_matches_resolved_profile(
            self.program_execution_spec, self.resolved_server_profile
        )
        if (
            self.project_physical_binding.project_id
            != self.workspace_binding.project_id
            or self.workspace_binding.attempt_id != self.attempt_id
            or self.project_physical_binding.resolved_server_profile_id
            != self.resolved_server_profile.resolved_server_profile_id
            or self.project_physical_binding.resolved_target_identity
            != self.resolved_server_profile.target_identity
            or self.project_physical_binding.remote_root
            != self.resolved_server_profile.remote_root
        ):
            raise ExecutionValueError(
                "ProgramExecutionSnapshot embedded authority graph is inconsistent"
            )
        remote_attempt_dir = validate_posix_path(
            f"{self.project_physical_binding.remote_project_dir}/{self.attempt_id}",
            "remote_attempt_dir",
        )
        if self.workspace_binding.remote_attempt_dir != remote_attempt_dir:
            raise ExecutionValueError(
                "ProgramExecutionSnapshot workspace is outside its bound remote Project"
            )
        cwd_binding = freeze_mapping(
            {"location_kind": "server", "path": remote_attempt_dir},
            "verified cwd binding",
        )
        scheduler = _render_scheduler_artifact(
            self.program_execution_spec,
            self.resolved_resource_request,
            self.resolved_server_profile,
            prebinding_fields={key: value for key, value in self._identity_payload.items() if key != "scheduler_artifacts"},
            completion_rendering_material=self._completion_material(),
            project_physical_binding=self.project_physical_binding,
        )
        if self.cwd_binding != cwd_binding or self.scheduler_artifacts != scheduler:
            raise ExecutionValueError(
                "ProgramExecutionSnapshot derived public fields are stale"
            )
        expected_payload = freeze_mapping(
            {
                "attempt_id": self.attempt_id,
                "calculation_plan_id": self.calculation_plan_id,
                "calculation_plan_revision": self.calculation_plan_revision,
                "program_execution_spec_id": self.program_execution_spec_id,
                "program_execution_spec_payload_sha256": spec_digest,
                "project_physical_binding_id": self.project_physical_binding_id,
                "resolved_resource_request_id": (
                    self.resolved_resource_request.resolved_resource_request_id
                ),
                "resolved_server_profile_id": (
                    self.resolved_server_profile.resolved_server_profile_id
                ),
                "workspace_binding_id": self.workspace_binding.workspace_binding_id,
                "cwd_binding": cwd_binding,
                "scheduler_artifacts": scheduler,
            },
            "ProgramExecutionSnapshot verified identity payload",
        )
        if expected_payload != self._identity_payload:
            raise ExecutionValueError(
                "ProgramExecutionSnapshot fields differ from its identity payload"
            )
        expected_intent = semantic_id("program-effect-intent", expected_payload)
        if expected_intent != self.effect_intent_id:
            raise ExecutionValueError("successor effect intent identity is stale")
        snapshot_payload = freeze_mapping(
            {
                "effect_intent_id": expected_intent,
                **{key: expected_payload[key] for key in expected_payload},
            },
            "ProgramExecutionSnapshot verification payload",
        )
        if semantic_id("program-execution-snapshot", snapshot_payload) != self.program_execution_snapshot_id:
            raise ExecutionValueError("ProgramExecutionSnapshot identity is stale")


def _validate_program_review_semantics(raw: Mapping[str, object]) -> Mapping[str, object]:
    """Pure validation stays mapping-only; it conveys no restoration authority."""
    return _decode_program_review_semantics(raw)._approval_semantics()


def _decode_program_review_semantics(raw: Mapping[str, object]) -> ProgramExecutionSnapshot:
    value = freeze_mapping(raw, "persisted successor review semantics")
    _exact_keys(value, set(ProgramExecutionSnapshot._approval_field_set(gaussian_short="gaussian_startup_review" in value)), "successor review semantics")

    def closed(name: str, keys: set[str]) -> Mapping[str, object]:
        item = value[name]
        if not isinstance(item, Mapping):
            raise ExecutionValueError(f"{name} must be a closed mapping")
        _exact_keys(item, keys, name)
        return item

    spec_data = closed("program_execution_spec", {
        "program_execution_spec_id", "program_kind", "adapter_id", "adapter_contract_version",
        "exact_inputs", "program_data", "invocation", "required_outputs", "optional_outputs",
    })
    spec = ProgramExecutionSpec._from_closed(**{key: item for key, item in spec_data.items() if key != "program_execution_spec_id"})
    if spec.semantic_payload() != spec_data:
        raise ExecutionValueError("persisted program spec identity is stale")
    binding_data = closed("project_physical_binding", {
        "project_physical_binding_id", "project_id", "provisioning_contract_version",
        "transport_kind", "resolved_server_profile_id", "resolved_target_identity",
        "provisioning_authority_id", "locations",
    })
    binding = object.__new__(ProjectPhysicalBinding)
    for key, item in binding_data.items():
        object.__setattr__(binding, key, item)
    object.__setattr__(binding, "_identity_payload", freeze_mapping({key: item for key, item in binding_data.items() if key != "project_physical_binding_id"}, "persisted Project identity"))
    binding.assert_identity_closed()
    resource_data = closed("resolved_resource_request", {
        "resolved_resource_request_id", "resource_spec_id", "cores", "memory_mb", "walltime_seconds", "queue",
    })
    resources = object.__new__(ResolvedResourceRequest)
    for key, item in resource_data.items():
        object.__setattr__(resources, key, item)
    for key in ("cores", "memory_mb", "walltime_seconds"):
        require_positive_integer(resource_data[key], key)
    require_text(resource_data["resource_spec_id"], "resource_spec_id")
    if resources.queue is not None:
        validate_portable_name(resources.queue, "queue")
    resources.assert_identity_closed()
    profile_data = closed("resolved_server_profile", {
        "resolved_server_profile_id", "server_profile_id", "profile_revision", "effective_config_sha256",
        "transport_kind", "target_identity", "remote_user", "remote_root", "platform_paths", "runtime_identities",
    })
    profile_identity = closed("resolved_server_profile_identity", {
        "server_profile_id", "profile_revision", "effective_config_sha256", "transport_kind",
        "target_identity", "remote_user", "remote_root", "platform_paths", "runtime_identities", "ordered_config_content",
    })
    profile = ResolvedServerProfile._from_resolved(**dict(profile_data), identity_payload=profile_identity)
    profile.assert_identity_closed()
    target = profile.target_identity
    _exact_keys(target, {"destination_host", "destination_port", "jump_topology", "host_key_policy", "batch_mode", "identities_only"}, "target identity")
    if profile.transport_kind != "legacy_rtwin_pbs" or target["host_key_policy"] != "strict" or target["batch_mode"] is not True or target["identities_only"] is not True:
        raise ExecutionValueError("persisted successor target is not the closed RTwin target")
    require_positive_integer(profile.profile_revision, "profile_revision")
    for name in ("destination_host",):
        require_text(target[name], name)
    require_positive_integer(target["destination_port"], "destination_port")
    if not isinstance(target["jump_topology"], tuple):
        raise ExecutionValueError("jump_topology must be an ordered tuple")
    for hop in target["jump_topology"]:
        _exact_keys(hop, {"host", "port", "user"}, "jump hop")
        require_text(hop["host"], "hop host")
        require_text(hop["user"], "hop user")
        require_positive_integer(hop["port"], "hop port")
    for identity in profile.runtime_identities.values():
        _exact_keys(identity, {"sha256", "size_bytes"}, "runtime identity")
        require_sha256(identity["sha256"], "runtime sha256")
        _nonnegative_integer(identity["size_bytes"], "runtime size")
    if not isinstance(profile_identity["ordered_config_content"], tuple) or not profile_identity["ordered_config_content"]:
        raise ExecutionValueError("persisted config inventory is missing")
    for identity in profile_identity["ordered_config_content"]:
        _exact_keys(identity, {"logical_name", "sha256", "size_bytes"}, "config identity")
        validate_portable_name(identity["logical_name"], "config logical name")
        require_sha256(identity["sha256"], "config sha256")
        _nonnegative_integer(identity["size_bytes"], "config size")
    workspace_data = closed("workspace_binding", {
        "workspace_binding_id", "project_id", "attempt_id", "local_attempt_dir", "rtwin_attempt_dir", "remote_attempt_dir", "local_descriptor_anchor_sha256",
    })
    anchor = closed("workspace_descriptor_anchor", {"approved_root", "parent_parts", "component_identities"})
    if not isinstance(anchor["parent_parts"], tuple) or not isinstance(anchor["component_identities"], tuple) or not anchor["component_identities"]:
        raise ExecutionValueError("persisted workspace anchor is malformed")
    for part in anchor["parent_parts"]:
        validate_portable_name(part, "workspace parent component")
    for pair in anchor["component_identities"]:
        if not isinstance(pair, tuple) or len(pair) != 2 or any(type(item) is not int or item < 0 for item in pair):
            raise ExecutionValueError("workspace physical component is malformed")
    workspace = object.__new__(WorkspaceBinding)
    for key, item in workspace_data.items():
        if key != "local_descriptor_anchor_sha256":
            object.__setattr__(workspace, key, item)
    for key, item in {
        "_local_anchor_sha256": workspace_data["local_descriptor_anchor_sha256"],
        "_local_approved_root": anchor["approved_root"], "_local_parent_parts": anchor["parent_parts"],
        "_local_component_identities": anchor["component_identities"], "_local_parent_identity": anchor["component_identities"][-1],
    }.items():
        object.__setattr__(workspace, key, item)
    workspace.assert_identity_closed()
    require_text(value["attempt_id"], "attempt_id")
    require_text(value["calculation_plan_id"], "calculation_plan_id")
    require_positive_integer(value["calculation_plan_revision"], "calculation_plan_revision")
    snapshot = ProgramExecutionSnapshot._from_verified(
        payload=freeze_mapping({key: value[key] for key in _SNAPSHOT_PAYLOAD_FIELDS}, "persisted snapshot identity"),
        effect_intent_id=value["effect_intent_id"], snapshot_id=value["program_execution_snapshot_id"],
        spec=spec, binding=binding, resources=resources, profile=profile, workspace=workspace,
    )
    snapshot.assert_identity_closed()
    if snapshot._approval_semantics() != value:
        raise ExecutionValueError("expanded successor review semantics are stale")
    return snapshot


def _assert_collection_local_workspace(snapshot):
    from ._paths import require_local_workspace_anchor
    workspace = snapshot.workspace_binding
    current = require_local_workspace_anchor(workspace.local_attempt_dir, workspace._local_approved_root)
    if current != (workspace._local_approved_root, workspace._local_parent_parts, workspace._local_component_identities):
        raise ExecutionValueError("restored local workspace anchor changed")


class _ProgramExecutionSnapshotService:
    """Private snapshot factory that owns its Project provisioning authority."""

    __slots__ = ("_project_provisioning",)

    def __init__(self) -> None:
        raise TypeError("snapshot service requires an owned provisioning authority")

    @classmethod
    def _for_production(cls, *, project_provisioning: _ProjectProvisioningService, target: ResolvedServerProfile) -> _ProgramExecutionSnapshotService:
        if type(project_provisioning) is not _ProjectProvisioningService:
            raise ExecutionValueError("production snapshot factory requires durable RTwin Project authority")
        project_provisioning._assert_production_authority(target)
        value = object.__new__(cls)
        value._project_provisioning = project_provisioning
        return value

    @classmethod
    def _for_privileged_synthetic_tests(
        cls,
        *,
        privilege: object,
        project_provisioning: _ProjectProvisioningService,
    ) -> _ProgramExecutionSnapshotService:
        if privilege is not _SYNTHETIC_TEST_HARNESS_PRIVILEGE:
            raise ExecutionValueError("synthetic snapshot-service privilege is required")
        if type(project_provisioning) is not _ProjectProvisioningService:
            raise ExecutionValueError(
                "snapshot service requires the exact owning provisioning service"
            )
        value = object.__new__(cls)
        value._project_provisioning = project_provisioning
        return value

    def prepare(
        self,
        store: SQLiteRuntimeStore,
        *,
        attempt_id: str,
        calculation_plan_id: str,
        resource_spec_id: str,
        program_execution_spec: ProgramExecutionSpec,
        project_physical_binding: ProjectPhysicalBinding,
        resolved_resource_request: ResolvedResourceRequest,
        resolved_server_profile: ResolvedServerProfile,
        workspace_binding: WorkspaceBinding,
        completion_rendering_material: Mapping[str, object] | None = None,
    ) -> ProgramExecutionSnapshot:
        fixture = str(program_execution_spec.invocation["executable_identity"]["absolute_path"]).startswith("/opt/auto-g16-fixtures/")
        production = self._project_provisioning._journal is not None
        if fixture == production:
            raise ExecutionValueError("program executable and Project authority generations differ")
        return _prepare_program_execution_snapshot_owned(
            self._project_provisioning,
            store,
            attempt_id=attempt_id,
            calculation_plan_id=calculation_plan_id,
            resource_spec_id=resource_spec_id,
            program_execution_spec=program_execution_spec,
            project_physical_binding=project_physical_binding,
            resolved_resource_request=resolved_resource_request,
            resolved_server_profile=resolved_server_profile,
            workspace_binding=workspace_binding,
            completion_rendering_material=completion_rendering_material,
        )

    def restore_for_collection(self, store: SQLiteRuntimeStore, *, reviewed_semantics: Mapping[str, object]) -> ProgramExecutionSnapshot:
        return self._restore_existing(store, reviewed_semantics=reviewed_semantics, reconciliation=False)

    def restore_for_reconciliation(self, store: SQLiteRuntimeStore, *, reviewed_semantics: Mapping[str, object]) -> ProgramExecutionSnapshot:
        """Existing UNKNOWN only (or exact disposition replay); never prepare."""
        return self._restore_existing(store, reviewed_semantics=reviewed_semantics, reconciliation=True)

    def _restore_existing(self, store, *, reviewed_semantics, reconciliation):
        """Restore data for an existing submission; never attest/provision remotely.

        Controller owns original approvals and physical four-store binding. The
        runtime must additionally close dual-source receipts under its guard
        before this snapshot can be used by the collect-only composition.
        """
        from auto_g16.core import SubmissionOutcome
        from .project_provisioning import _ProductionProvisioningJournal
        from .runtime import _replay_submission_intent
        from auto_g16.core import SubmissionIntentClaim
        if type(store) is not SQLiteRuntimeStore:
            raise ExecutionValueError("restoration requires the original Core store")
        snapshot = _decode_program_review_semantics(reviewed_semantics)
        service = self._project_provisioning
        if type(service._journal) is not _ProductionProvisioningJournal:
            raise ExecutionValueError("restoration requires a production Project journal")
        service._assert_production_authority(snapshot.resolved_server_profile)
        restorable_schemas = (
            {"v31-completion-rendering-material/3", "v31-completion-rendering-material/4"}
            if snapshot.program_execution_spec.program_kind == "crest"
            else {"v31-completion-rendering-material/5", "v31-completion-rendering-material/6", "v31-completion-rendering-material/7"}
            if snapshot.program_execution_spec.program_kind == "gaussian"
            else {"v31-completion-rendering-material/2"}
        )
        if not _uses_completion_receipt(snapshot.program_execution_spec) or snapshot._completion_material()["schema"] not in restorable_schemas:
            raise ExecutionValueError("restoration requires the original publisher tuple")
        state = store.attempt_state(snapshot.attempt_id)
        allowed = {AttemptState.SUBMITTED, AttemptState.RUNNING, AttemptState.SUCCEEDED, AttemptState.FAILED}
        if reconciliation:
            allowed.add(AttemptState.UNKNOWN)
        if state not in allowed:
            raise ExecutionValueError("restoration requires an already submitted Attempt")
        receipts = [item for item in store.observations_for_attempt(snapshot.attempt_id) if item.observation_type == _PROGRAM_EFFECT_RECEIPT_TYPE]
        reconciliations = [item for item in receipts if item.data.get("operation") == "RECONCILE_SUBMISSION"]
        submits = [item for item in receipts if item.data.get("operation") == "SUBMIT_QSUB_ONCE"]
        recovered = len(submits) == 1 and submits[0].data.get("outcome") == "UNKNOWN" and len(reconciliations) == 1 and reconciliations[0].data.get("response", {}).get("schema") == "v31-exact-observed-job-reconciliation-proof/1"
        pending = reconciliation and state is AttemptState.UNKNOWN and len(submits) == 1 and submits[0].data.get("outcome") == "UNKNOWN" and not reconciliations
        if not (recovered or pending) and (reconciliations or len(submits) != 1 or submits[0].data.get("outcome") != "SUCCEEDED"):
            raise ExecutionValueError("restoration requires one original successful submission")
        if recovered or pending:
            from . import _submission_recovery as recovery
            recovery.document(snapshot)  # Separate installed authority is mandatory.
            if recovered:
                receipt = reconciliations[0]
                recovery.validate_proof(store, snapshot, tuple(receipts[:receipts.index(receipt)]), receipt.data["request"], receipt.data["response"])
                if not reconciliation and receipt.data["outcome"] != "SUCCEEDED":
                    raise ExecutionValueError("unresolved recovery cannot collect")
        snapshot._assert_current_core(store)
        _assert_collection_local_workspace(snapshot)
        attempt = store.load_attempt(snapshot.attempt_id)
        project = store.load_project(store.load_workflow_run(store.load_task(attempt.task_id).workflow_run_id).project_id)
        service._assert_owned_binding(binding=snapshot.project_physical_binding, project=project,
                                      target=snapshot.resolved_server_profile,
                                      remote_project_dir=snapshot.project_physical_binding.remote_project_dir)
        resources = snapshot.resolved_resource_request
        rebuilt = ResolvedResourceRequest(resource_spec=store.load_resource_spec(resources.resource_spec_id),
                                          cores=resources.cores, memory_mb=resources.memory_mb,
                                          walltime_seconds=resources.walltime_seconds, queue=resources.queue)
        if rebuilt != resources:
            raise ExecutionValueError("restored resources differ from Core")
        # In these states the existing Core APIs can only replay exact records;
        # missing/conflicting intent/outcome raises, never takes a WINNER branch.
        if _replay_submission_intent(store, snapshot.attempt_id, snapshot.effect_intent_id) is not SubmissionIntentClaim.REPLAY:
            raise ExecutionValueError("restoration cannot claim an Attempt")
        # Reconciled branches replay UNKNOWN verbatim, never rewrite its history.
        outcome = SubmissionOutcome.UNKNOWN if recovered or pending else SubmissionOutcome.SUBMITTED
        if store.record_submission_outcome(snapshot.attempt_id, snapshot.effect_intent_id, outcome) is not state:
            raise ExecutionValueError("restoration changed submission state")
        if recovered and not reconciliation:
            from auto_g16.core import ReconciliationResolution
            if store.reconcile_unknown(snapshot.attempt_id, reconciliations[0].observation_id, ReconciliationResolution.SUBMITTED) is not state:
                raise ExecutionValueError("reconciliation replay changed state")
        return snapshot


def _prepare_program_execution_snapshot_owned(
    owned_project_provisioning: _ProjectProvisioningService,
    store: SQLiteRuntimeStore,
    *,
    attempt_id: str,
    calculation_plan_id: str,
    resource_spec_id: str,
    program_execution_spec: ProgramExecutionSpec,
    project_physical_binding: ProjectPhysicalBinding,
    resolved_resource_request: ResolvedResourceRequest,
    resolved_server_profile: ResolvedServerProfile,
    workspace_binding: WorkspaceBinding,
    completion_rendering_material: Mapping[str, object] | None = None,
) -> ProgramExecutionSnapshot:
    if not isinstance(store, SQLiteRuntimeStore):
        raise ExecutionValueError("successor preparation requires the exact Core store")
    attempt = store.load_attempt(require_text(attempt_id, "attempt_id"))
    task = store.load_task(attempt.task_id)
    workflow = store.load_workflow_run(task.workflow_run_id)
    project = store.load_project(workflow.project_id)
    plan: CalculationPlan = store.load_calculation_plan(require_text(calculation_plan_id, "calculation_plan_id"))
    resource: ResourceSpec = store.load_resource_spec(require_text(resource_spec_id, "resource_spec_id"))
    if plan.task_id != task.task_id or resource.task_id != task.task_id:
        raise ExecutionValueError("Attempt, plan, and resources must belong to one Task")
    for value, expected, label in (
        (program_execution_spec, ProgramExecutionSpec, "program_execution_spec"),
        (project_physical_binding, ProjectPhysicalBinding, "project_physical_binding"),
        (resolved_resource_request, ResolvedResourceRequest, "resolved_resource_request"),
        (resolved_server_profile, ResolvedServerProfile, "resolved_server_profile"),
        (workspace_binding, WorkspaceBinding, "workspace_binding"),
    ):
        if not isinstance(value, expected):
            raise ExecutionValueError(f"{label} has an invalid type")
        value.assert_identity_closed()
    if project_physical_binding.project_id != project.project_id or workspace_binding.project_id != project.project_id:
        raise ExecutionValueError("Project physical or workspace binding belongs to another Project")
    if workspace_binding.attempt_id != attempt.attempt_id:
        raise ExecutionValueError("workspace binding belongs to another Attempt")
    if resolved_resource_request.resource_spec_id != resource.resource_spec_id:
        raise ExecutionValueError("resolved resources differ from the loaded ResourceSpec")
    if type(owned_project_provisioning) is not _ProjectProvisioningService:
        raise ExecutionValueError(
            "snapshot preparation requires the trusted Project provisioning service"
        )
    _assert_executable_matches_resolved_profile(
        program_execution_spec, resolved_server_profile
    )
    if _uses_completion_receipt(program_execution_spec):
        from ._program_completion import _validate_material, _validate_publisher_invocation
        material = _validate_material(completion_rendering_material, resolved_server_profile)
        _validate_publisher_invocation(material, program_execution_spec, resolved_resource_request)
        if store.attempt_state(attempt.attempt_id) is not AttemptState.PLANNED:
            raise ExecutionValueError("completion preparation requires a fresh unconsumed Attempt")
    elif completion_rendering_material is not None:
        raise ExecutionValueError("strict adapters reject completion rendering material")
    current_proof = owned_project_provisioning._attest_current(
        project_physical_binding, resolved_server_profile
    )
    remote_project_dir = owned_project_provisioning._consume_current(
        binding=project_physical_binding,
        target=resolved_server_profile,
        proof=current_proof,
    )
    remote_attempt_dir = validate_posix_path(
        f"{remote_project_dir}/{attempt.attempt_id}", "remote_attempt_dir"
    )
    require_contained(remote_attempt_dir, remote_project_dir, "remote_attempt_dir")
    if workspace_binding.remote_attempt_dir != remote_attempt_dir:
        raise ExecutionValueError(
            "workspace binding differs from the exact remote Project/Attempt authority"
        )
    spec_digest = semantic_sha256(program_execution_spec.semantic_payload())
    payload = freeze_mapping(
        {
            "attempt_id": attempt.attempt_id,
            "calculation_plan_id": plan.calculation_plan_id,
            "calculation_plan_revision": plan.revision,
            "program_execution_spec_id": program_execution_spec.program_execution_spec_id,
            "program_execution_spec_payload_sha256": spec_digest,
            "project_physical_binding_id": project_physical_binding.project_physical_binding_id,
            "resolved_resource_request_id": resolved_resource_request.resolved_resource_request_id,
            "resolved_server_profile_id": resolved_server_profile.resolved_server_profile_id,
            "workspace_binding_id": workspace_binding.workspace_binding_id,
            "cwd_binding": {
                "location_kind": "server",
                "path": remote_attempt_dir,
            },
        },
        "ProgramExecutionSnapshot identity payload",
    )
    scheduler = _render_scheduler_artifact(
        program_execution_spec, resolved_resource_request, resolved_server_profile,
        prebinding_fields=payload,
        completion_rendering_material=completion_rendering_material,
        project_physical_binding=project_physical_binding,
    )
    payload = freeze_mapping({**payload, "scheduler_artifacts": scheduler}, "ProgramExecutionSnapshot identity payload")
    effect_intent_id = semantic_id("program-effect-intent", payload)
    snapshot_payload = freeze_mapping(
        {"effect_intent_id": effect_intent_id, **{key: payload[key] for key in payload}},
        "ProgramExecutionSnapshot payload",
    )
    snapshot_id = semantic_id("program-execution-snapshot", snapshot_payload)
    snapshot = ProgramExecutionSnapshot._from_verified(
        payload=payload,
        effect_intent_id=effect_intent_id,
        snapshot_id=snapshot_id,
        spec=program_execution_spec,
        binding=project_physical_binding,
        resources=resolved_resource_request,
        profile=resolved_server_profile,
        workspace=workspace_binding,
    )
    snapshot.assert_identity_closed()
    return snapshot


__all__ = ["ProgramExecutionSnapshot", "ProgramExecutionSpec"]
