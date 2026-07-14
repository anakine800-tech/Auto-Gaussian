#!/usr/bin/env python3
"""Audit Cartesian coordinates in a Gaussian input or XYZ file."""

from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter
from pathlib import Path


COORDINATE = re.compile(
    r"^\s*([A-Z][a-z]?)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s*$"
)
CHARGE_MULTIPLICITY = re.compile(r"^\s*(-?\d+)\s+(\d+)\s*$")


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def parse(path: Path):
    lines = path.read_text(encoding="utf-8").splitlines()
    if path.suffix.lower() == ".xyz":
        if len(lines) < 3:
            fail("XYZ file is too short")
        try:
            expected = int(lines[0].strip())
        except ValueError:
            fail("first XYZ line must be the atom count")
        body = lines[2 : 2 + expected]
        if len(body) != expected:
            fail("XYZ coordinate count does not match its header")
        charge_mult = None
    else:
        start = next((i for i, line in enumerate(lines) if CHARGE_MULTIPLICITY.match(line)), None)
        if start is None:
            fail("could not find a Gaussian charge/multiplicity line")
        match = CHARGE_MULTIPLICITY.match(lines[start])
        charge_mult = {"charge": int(match.group(1)), "multiplicity": int(match.group(2))}
        body = []
        for line in lines[start + 1 :]:
            if not line.strip():
                break
            body.append(line)

    coordinates = []
    for line in body:
        match = COORDINATE.match(line)
        if match is None:
            fail(f"invalid Cartesian coordinate line: {line!r}")
        symbol = match.group(1)
        xyz = tuple(float(match.group(i)) for i in range(2, 5))
        if not all(math.isfinite(value) for value in xyz):
            fail(f"non-finite coordinate for {symbol}")
        coordinates.append((symbol, *xyz))
    if not coordinates:
        fail("no Cartesian coordinates found")
    return coordinates, charge_mult, lines


def min_pair_distance(coordinates):
    closest = (math.inf, None)
    for i, atom in enumerate(coordinates):
        for j, other in enumerate(coordinates[:i]):
            distance = math.dist(atom[1:], other[1:])
            if distance < closest[0]:
                closest = (distance, {"atom_1": j, "element_1": other[0], "atom_2": i, "element_2": atom[0]})
    return closest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="Gaussian .gjf/.com input or .xyz coordinate file")
    parser.add_argument("--min-distance", type=float, default=0.4, help="Fail if any atom pair is closer than this value in Å")
    args = parser.parse_args()
    path = Path(args.input).expanduser().resolve()
    if not path.exists():
        fail(f"file does not exist: {path}")
    coordinates, charge_mult, lines = parse(path)
    distance, pair = min_pair_distance(coordinates)
    if distance < args.min_distance:
        fail(f"closest atom pair is {distance:.4f} Å, below --min-distance {args.min_distance:.4f} Å")
    result = {
        "input": str(path),
        "atom_count": len(coordinates),
        "element_count": dict(sorted(Counter(atom[0] for atom in coordinates).items())),
        "charge_multiplicity": charge_mult,
        "closest_pair_distance_angstrom": round(distance, 6),
        "closest_pair": pair,
        "trailing_blank_line": bool(lines and not lines[-1].strip()) if path.suffix.lower() != ".xyz" else None,
    }
    if path.suffix.lower() != ".xyz" and not result["trailing_blank_line"]:
        fail("Gaussian input must end with a blank line")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
