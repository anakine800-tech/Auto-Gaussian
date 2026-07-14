#!/usr/bin/env python3
"""Build and analyze audited Opt -> Freq -> single-point Gaussian workflows."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

import gaussian_rtwin_pbs as transport
from gaussian_log import HARTREE_J_MOL, analyze_workflow_log_file


def fail(message: str, code: int = 2) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(code)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_route(route: str) -> str:
    route = " ".join(route.strip().split())
    if not route:
        fail("Gaussian route cannot be empty")
    return route if route.startswith("#") else "#p " + route


def route_tokens(route: str) -> list[str]:
    tokens: list[str] = []
    current: list[str] = []
    depth = 0
    for character in (route.split(maxsplit=1)[1] if " " in route else ""):
        if character.isspace() and depth == 0:
            if current:
                tokens.append("".join(current))
                current = []
            continue
        current.append(character)
        if character == "(":
            depth += 1
        elif character == ")" and depth:
            depth -= 1
    if current:
        tokens.append("".join(current))
    return tokens


def route_prefix(route: str) -> str:
    match = re.match(r"^(#[A-Za-z]*)", route)
    return match.group(1) if match else "#p"


def contains_job(route: str, job: str) -> bool:
    return any(token.lower() == job or token.lower().startswith(job + "=") or token.lower().startswith(job + "(") for token in route_tokens(route))


def derive_frequency_route(opt_route: str, temperature_k: float) -> str:
    tokens = [
        token for token in route_tokens(opt_route)
        if not (
            token.lower() == "opt"
            or token.lower().startswith("opt=")
            or token.lower().startswith("opt(")
            or token.lower() == "freq"
            or token.lower().startswith("freq=")
            or token.lower().startswith("freq(")
            or token.lower().startswith("temperature=")
            or token.lower().startswith("geom=")
            or token.lower().startswith("guess=")
        )
    ]
    tokens.extend(["freq", "geom=allcheck", "guess=read"])
    if not math.isclose(temperature_k, 298.15, rel_tol=0.0, abs_tol=1e-8):
        tokens.append(f"temperature={temperature_k:g}")
    return route_prefix(opt_route) + " " + " ".join(tokens)


def prepare_followup_route(route: str, *, required_job: str | None) -> str:
    route = normalize_route(route)
    if required_job and not contains_job(route, required_job):
        fail(f"route must contain {required_job}")
    if required_job != "opt" and contains_job(route, "opt"):
        fail("follow-up route must not contain Opt")
    if required_job is None and contains_job(route, "freq"):
        fail("single-point route must not contain Freq")
    tokens = route_tokens(route)
    lower = [token.lower() for token in tokens]
    if not any(token.startswith("geom=") for token in lower):
        tokens.append("geom=allcheck")
    if not any(token.startswith("guess=") for token in lower):
        tokens.append("guess=read")
    return route_prefix(route) + " " + " ".join(tokens)


def parse_cartesian_input(path: Path) -> dict[str, Any]:
    audit = transport.parse_gaussian(path)
    lines = path.read_text(encoding="utf-8").splitlines()
    route_start = next(i for i, line in enumerate(lines) if line.lstrip().startswith("#"))
    route_end = route_start
    while route_end < len(lines) and lines[route_end].strip():
        route_end += 1
    index = route_end
    while index < len(lines) and not lines[index].strip():
        index += 1
    title_lines: list[str] = []
    while index < len(lines) and lines[index].strip():
        title_lines.append(lines[index].strip())
        index += 1
    while index < len(lines) and not lines[index].strip():
        index += 1
    charge_line = lines[index].strip()
    index += 1
    coordinates: list[str] = []
    while index < len(lines) and lines[index].strip():
        coordinates.append(lines[index].rstrip())
        index += 1
    if len(coordinates) != audit["atom_count"]:
        fail("coordinate extraction does not match audited atom count")
    return {
        "audit": audit,
        "title": " ".join(title_lines) or path.stem,
        "charge_line": charge_line,
        "coordinates": coordinates,
    }


def command_build(args) -> None:
    source = Path(args.input).expanduser().resolve()
    output = Path(args.output).expanduser().resolve()
    if output.suffix.lower() not in {".gjf", ".com"}:
        fail("output must end in .gjf or .com")
    parsed = parse_cartesian_input(source)
    audit = parsed["audit"]
    opt_route = normalize_route(args.opt_route or audit["route"])
    if not contains_job(opt_route, "opt"):
        fail("optimization route must contain Opt")
    freq_route = normalize_route(args.freq_route) if args.freq_route else derive_frequency_route(opt_route, args.temperature)
    freq_route = prepare_followup_route(freq_route, required_job="freq")
    sp_route = prepare_followup_route(args.sp_route, required_job=None)
    mem = args.mem or audit["mem"]
    nproc = args.nproc or audit["nprocshared"]
    transport.parse_memory(mem)
    if not 1 <= nproc <= transport.MAX_CORES:
        fail(f"nproc must be between 1 and {transport.MAX_CORES}")
    if transport.parse_memory(mem) > transport.MAX_MEMORY_BYTES:
        fail("memory exceeds the 120 GB server ceiling")
    if not 1.0 <= args.temperature <= 5000.0:
        fail("temperature must be between 1 and 5000 K")

    checkpoint = output.stem + ".chk"
    link0 = f"%chk={checkpoint}\n%mem={mem}\n%nprocshared={nproc}\n"
    first = (
        link0 + opt_route + "\n\n"
        + parsed["title"] + "\n\n"
        + parsed["charge_line"] + "\n"
        + "\n".join(parsed["coordinates"]) + "\n\n"
    )
    linked = (
        first
        + "--Link1--\n" + link0 + freq_route + "\n\n"
        + "--Link1--\n" + link0 + sp_route + "\n\n"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(linked, encoding="utf-8")
    xyz = output.with_suffix(".xyz")
    xyz.write_text(
        f"{len(parsed['coordinates'])}\n{parsed['title']}\n"
        + "\n".join(parsed["coordinates"]) + "\n",
        encoding="utf-8",
    )
    source_manifest = source.with_suffix(".json")
    inherited: dict[str, Any] = {}
    if source_manifest.is_file():
        inherited = json.loads(source_manifest.read_text(encoding="utf-8"))
    manifest = {
        "schema": "gaussian-opt-freq-sp/1",
        "calculation_ready": True,
        "candidate_only": False,
        "source_input": str(source),
        "source_input_sha256": sha256(source),
        "species_id": args.species_id or inherited.get("canonical_isomeric_smiles"),
        "chemical_identity": {
            "canonical_isomeric_smiles": inherited.get("canonical_isomeric_smiles"),
            "formula": inherited.get("formula"),
            "charge": audit["charge"],
            "multiplicity": audit["multiplicity"],
        },
        "gaussian_input": str(output),
        "checkpoint": checkpoint,
        "charge_used": audit["charge"],
        "multiplicity_used": audit["multiplicity"],
        "atom_count_in_gaussian_input": audit["atom_count"],
        "chiral_centers": inherited.get("chiral_centers", []),
        "stages": [
            {"name": "optimization", "route": opt_route, "success_gate": "Optimization completed and normal termination"},
            {"name": "frequency", "route": freq_route, "success_gate": "Normal termination and zero imaginary frequencies for a minimum"},
            {"name": "single_point", "route": sp_route, "success_gate": "Normal termination and final SCF energy"},
        ],
        "expected_stage_count": 3,
        "temperature_k": args.temperature,
        "standard_state": args.standard_state,
        "standard_state_correction": "ideal-gas 1 atm to 1 M per species" if args.standard_state == "1M" else "none",
        "quasi_harmonic_correction": "not applied",
        "mem": mem,
        "nprocshared": nproc,
        "warnings": [],
    }
    manifest_path = output.with_suffix(".json")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    built_audit = transport.parse_gaussian(output)
    print(json.dumps({"input": str(output), "manifest": str(manifest_path), "xyz": str(xyz), "audit": built_audit}, ensure_ascii=False, indent=2))


def workflow_settings(manifest_path: Path) -> tuple[float, str, int]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != "gaussian-opt-freq-sp/1":
        fail("manifest is not a gaussian-opt-freq-sp workflow")
    return (
        float(manifest["temperature_k"]),
        str(manifest["standard_state"]),
        int(manifest.get("expected_stage_count", 3)),
    )


def command_analyze(args) -> None:
    log_path = Path(args.log).expanduser().resolve()
    manifest_path = Path(args.manifest).expanduser().resolve() if args.manifest else log_path.with_suffix(".json")
    if not log_path.is_file() or not manifest_path.is_file():
        fail("log and workflow manifest must both exist")
    temperature, state, stages = workflow_settings(manifest_path)
    output_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else log_path.parent
    result = analyze_workflow_log_file(
        log_path, output_dir,
        temperature_k=temperature,
        standard_state=state,
        expected_stages=stages,
    )
    manifest_value = json.loads(manifest_path.read_text(encoding="utf-8"))
    result["workflow_manifest"] = str(manifest_path)
    result["species_id"] = manifest_value.get("species_id")
    result["chemical_identity"] = manifest_value.get("chemical_identity")
    result["workflow_protocol"] = {
        "stages": manifest_value.get("stages"),
        "temperature_k": manifest_value.get("temperature_k"),
        "standard_state": manifest_value.get("standard_state"),
    }
    result_path = output_dir / "result.json"
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


def command_aggregate(args) -> None:
    records = []
    temperature = args.temperature
    species_id = None
    workflow_protocol = None
    for value in args.results:
        path = Path(value).expanduser().resolve()
        result = json.loads(path.read_text(encoding="utf-8"))
        if not result.get("workflow_success"):
            fail(f"workflow result is not scientifically valid: {path}")
        thermo = result.get("thermochemistry", {})
        energy = thermo.get("composite_gibbs_target_hartree")
        if energy is None:
            fail(f"workflow result lacks composite Gibbs energy: {path}")
        result_species = result.get("species_id")
        if not result_species:
            fail(f"workflow result lacks species_id; rebuild with --species-id: {path}")
        if species_id is None:
            species_id = result_species
        elif species_id != result_species:
            fail("all conformer results must represent the same species_id")
        result_protocol = result.get("workflow_protocol")
        if not result_protocol:
            fail(f"workflow result lacks protocol identity: {path}")
        if workflow_protocol is None:
            workflow_protocol = result_protocol
        elif workflow_protocol != result_protocol:
            fail("all conformer results must use the same Opt/Freq/SP protocol")
        result_temperature = float(thermo["temperature_k"])
        if temperature is None:
            temperature = result_temperature
        if not math.isclose(temperature, result_temperature, abs_tol=1e-6):
            fail("all workflow results must use the same temperature")
        records.append({"result": str(path), "energy_hartree": float(energy)})
    assert temperature is not None
    minimum = min(item["energy_hartree"] for item in records)
    factors = []
    for item in records:
        delta_hartree = item["energy_hartree"] - minimum
        factor = math.exp(-delta_hartree * HARTREE_J_MOL / (8.31446261815324 * temperature))
        factors.append(factor)
        item["relative_gibbs_kcal_mol"] = delta_hartree * 627.5094740631
    total = sum(factors)
    for item, factor in zip(records, factors):
        item["boltzmann_population"] = factor / total
    records.sort(key=lambda item: item["energy_hartree"])
    summary = {
        "schema": "gaussian-conformer-population/1",
        "species_id": species_id,
        "workflow_protocol": workflow_protocol,
        "temperature_k": temperature,
        "population_sum": sum(item["boltzmann_population"] for item in records),
        "conformers": records,
    }
    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build", help="build one audited three-stage linked Gaussian input")
    build.add_argument("input")
    build.add_argument("--output", required=True)
    build.add_argument("--opt-route")
    build.add_argument("--freq-route")
    build.add_argument("--sp-route", required=True)
    build.add_argument("--temperature", type=float, default=298.15)
    build.add_argument("--standard-state", choices=("1atm", "1M"), required=True)
    build.add_argument("--species-id", help="stable species identity; inferred from a conformer manifest when available")
    build.add_argument("--mem")
    build.add_argument("--nproc", type=int)
    build.set_defaults(func=command_build)

    analyze = sub.add_parser("analyze", help="extract validation and composite thermochemistry")
    analyze.add_argument("log")
    analyze.add_argument("--manifest")
    analyze.add_argument("--output-dir")
    analyze.set_defaults(func=command_analyze)

    aggregate = sub.add_parser("aggregate", help="Boltzmann-weight valid workflow results")
    aggregate.add_argument("results", nargs="+")
    aggregate.add_argument("--temperature", type=float)
    aggregate.add_argument("--output", required=True)
    aggregate.set_defaults(func=command_aggregate)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    args.func(args)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        fail("interrupted", code=130)
