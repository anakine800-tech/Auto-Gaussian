#!/usr/bin/env python3
"""Create one editable CDXML document from molecules, arrows, text, and lines."""

from __future__ import annotations

import json
import math
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import numpy as np
from rdkit import Chem
from rdkit.Chem import rdDepictor


class Ids:
    def __init__(self, start: int = 10) -> None:
        self.value = start

    def next(self) -> str:
        result = str(self.value)
        self.value += 1
        return result


def fail(message: str) -> None:
    raise SystemExit(message)


def fnum(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


def load_molecule(spec: dict[str, Any], base_dir: Path) -> Chem.Mol:
    if spec.get("mol_file"):
        path = Path(str(spec["mol_file"])).expanduser()
        if not path.is_absolute():
            path = base_dir / path
        mol = Chem.MolFromMolFile(str(path), sanitize=True, removeHs=False)
        if mol is None:
            fail(f"Could not read molecule file: {path}")
    elif spec.get("smiles"):
        mol = Chem.MolFromSmiles(str(spec["smiles"]), sanitize=True)
        if mol is None:
            fail(f"Could not parse SMILES for {spec.get('id', 'molecule')}")
    else:
        fail(f"Molecule {spec.get('id', '?')} requires mol_file or smiles")
    if mol.GetNumConformers() == 0:
        rdDepictor.Compute2DCoords(mol)
    return mol


def _signed_area(points: list[tuple[float, float]]) -> float:
    return 0.5 * sum(
        x1 * y2 - x2 * y1
        for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1])
    )


def _regular_polygon_fit(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Fit a same-handed regular polygon to an ordered ring without mirroring it."""
    count = len(points)
    target = np.asarray(points, dtype=float)
    regular = np.asarray(
        [(math.cos(2 * math.pi * i / count), math.sin(2 * math.pi * i / count)) for i in range(count)],
        dtype=float,
    )
    if _signed_area(points) * _signed_area([tuple(point) for point in regular]) < 0:
        regular[:, 1] *= -1
    source_center = regular.mean(axis=0)
    target_center = target.mean(axis=0)
    source_zero = regular - source_center
    target_zero = target - target_center
    u, singular, vt = np.linalg.svd(source_zero.T @ target_zero)
    rotation = u @ vt
    if np.linalg.det(rotation) < 0:
        u[:, -1] *= -1
        rotation = u @ vt
    scale = singular.sum() / max(float((source_zero * source_zero).sum()), 1e-12)
    fitted = source_zero @ rotation * scale + target_center
    return [(float(x), float(y)) for x, y in fitted]


def _regular_polygon_from_edge(
    count: int,
    first_index: int,
    second_index: int,
    first: tuple[float, float],
    second: tuple[float, float],
    reference: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    """Place a regular polygon on an already-fixed shared edge."""
    regular = np.asarray(
        [(math.cos(2 * math.pi * i / count), math.sin(2 * math.pi * i / count)) for i in range(count)],
        dtype=float,
    )
    source_edge = regular[second_index] - regular[first_index]
    target_edge = np.asarray(second, dtype=float) - np.asarray(first, dtype=float)
    source_angle = math.atan2(source_edge[1], source_edge[0])
    target_angle = math.atan2(target_edge[1], target_edge[0])
    angle = target_angle - source_angle
    rotation = np.asarray(
        [[math.cos(angle), -math.sin(angle)], [math.sin(angle), math.cos(angle)]],
        dtype=float,
    )
    scale = float(np.linalg.norm(target_edge) / max(np.linalg.norm(source_edge), 1e-12))
    placed = (regular - regular[first_index]) @ rotation.T * scale + np.asarray(first)
    candidate = [(float(x), float(y)) for x, y in placed]
    if _signed_area(candidate) * _signed_area(reference) < 0:
        # Reflect across the fixed edge while leaving both shared atoms in place.
        origin = np.asarray(first, dtype=float)
        unit = target_edge / max(float(np.linalg.norm(target_edge)), 1e-12)
        reflected = []
        for point in placed:
            relative = point - origin
            projection = origin + unit * float(relative @ unit)
            mirrored = 2 * projection - point
            reflected.append((float(mirrored[0]), float(mirrored[1])))
        candidate = reflected
    return candidate


def _largest_angular_gap_midpoint(angles: list[float]) -> float:
    """Return the midpoint of the least-crowded sector, in radians."""
    if not angles:
        return 0.0
    if len(angles) == 1:
        return (angles[0] + math.pi) % (2 * math.pi)
    ordered = sorted(angle % (2 * math.pi) for angle in angles)
    gaps = [
        ((ordered[(index + 1) % len(ordered)] - angle) % (2 * math.pi), angle)
        for index, angle in enumerate(ordered)
    ]
    gap, start = max(gaps)
    return (start + gap / 2) % (2 * math.pi)


def _component_positions_about_anchor(
    component: set[int],
    anchor: int,
    root: int,
    target_angle: float,
    original: dict[int, tuple[float, float]],
    updated: dict[int, tuple[float, float]],
) -> dict[int, tuple[float, float]]:
    old_dx = original[root][0] - original[anchor][0]
    old_dy = original[root][1] - original[anchor][1]
    old_angle = math.atan2(old_dy, old_dx)
    delta = target_angle - old_angle
    cos_a, sin_a = math.cos(delta), math.sin(delta)
    anchor_x, anchor_y = updated[anchor]
    result = {}
    for index in component:
        dx = original[index][0] - original[anchor][0]
        dy = original[index][1] - original[anchor][1]
        result[index] = (
            anchor_x + dx * cos_a - dy * sin_a,
            anchor_y + dx * sin_a + dy * cos_a,
        )
    return result


def _minimum_component_clearance(
    candidate: dict[int, tuple[float, float]],
    anchor: int,
    updated: dict[int, tuple[float, float]],
) -> float:
    outside = [point for index, point in updated.items() if index not in candidate and index != anchor]
    if not outside:
        return float("inf")
    return min(
        math.hypot(point[0] - other[0], point[1] - other[1])
        for point in candidate.values()
        for other in outside
    )


def regularize_ring_geometry(mol: Chem.Mol) -> None:
    """Regularize simple 3-6 member fused-ring systems while preserving handedness."""
    rings = [list(ring) for ring in mol.GetRingInfo().AtomRings() if 3 <= len(ring) <= 6]
    if not rings or mol.GetNumConformers() == 0:
        return
    conformer = mol.GetConformer()
    original = {
        index: (conformer.GetAtomPosition(index).x, conformer.GetAtomPosition(index).y)
        for index in range(mol.GetNumAtoms())
    }
    bond_lengths = [
        math.hypot(
            original[bond.GetBeginAtomIdx()][0] - original[bond.GetEndAtomIdx()][0],
            original[bond.GetBeginAtomIdx()][1] - original[bond.GetEndAtomIdx()][1],
        )
        for bond in mol.GetBonds()
    ]
    typical_bond_length = float(np.median(bond_lengths)) if bond_lengths else 1.0
    updated = dict(original)
    processed_atoms: set[int] = set()
    pending = sorted(rings, key=lambda ring: (-len(ring), tuple(ring)))

    while pending:
        selected_index = None
        for index, ring in enumerate(pending):
            shared = [atom for atom in ring if atom in processed_atoms]
            if len(shared) == 2:
                positions = [ring.index(atom) for atom in shared]
                if (positions[0] - positions[1]) % len(ring) in (1, len(ring) - 1):
                    selected_index = index
                    break
        if selected_index is None:
            selected_index = 0
        ring = pending.pop(selected_index)
        reference = [original[index] for index in ring]
        shared = [index for index in ring if index in processed_atoms]
        if len(shared) == 2:
            first_index, second_index = ring.index(shared[0]), ring.index(shared[1])
            if (second_index - first_index) % len(ring) not in (1, len(ring) - 1):
                continue
            fitted = _regular_polygon_from_edge(
                len(ring), first_index, second_index, updated[shared[0]], updated[shared[1]], reference
            )
        elif not shared:
            fitted = _regular_polygon_fit(reference)
        else:
            # Spiro, bridged, or over-constrained systems need a reviewed template.
            continue
        for atom_index, point in zip(ring, fitted):
            if atom_index not in processed_atoms:
                updated[atom_index] = point
        processed_atoms.update(ring)

    ring_atoms = set().union(*(set(ring) for ring in rings))
    unvisited = set(range(mol.GetNumAtoms())) - ring_atoms
    components: list[tuple[set[int], set[int]]] = []
    while unvisited:
        seed = unvisited.pop()
        component = {seed}
        queue = [seed]
        while queue:
            current = queue.pop()
            for neighbor in mol.GetAtomWithIdx(current).GetNeighbors():
                index = neighbor.GetIdx()
                if index in unvisited and index not in ring_atoms:
                    unvisited.remove(index)
                    component.add(index)
                    queue.append(index)
        anchors = {
            neighbor.GetIdx()
            for index in component
            for neighbor in mol.GetAtomWithIdx(index).GetNeighbors()
            if neighbor.GetIdx() in ring_atoms
        }
        components.append((component, anchors))

    by_anchor: dict[int, list[tuple[set[int], int, float]]] = {}
    for component, anchors in components:
        if len(anchors) != 1:
            if anchors:
                dx = sum(updated[index][0] - original[index][0] for index in anchors) / len(anchors)
                dy = sum(updated[index][1] - original[index][1] for index in anchors) / len(anchors)
                for index in component:
                    updated[index] = (original[index][0] + dx, original[index][1] + dy)
            continue
        anchor = next(iter(anchors))
        roots = [
            index
            for index in component
            if mol.GetBondBetweenAtoms(anchor, index) is not None
        ]
        if len(roots) != 1:
            continue
        root = roots[0]
        original_angle = math.atan2(
            original[root][1] - original[anchor][1],
            original[root][0] - original[anchor][0],
        ) % (2 * math.pi)
        by_anchor.setdefault(anchor, []).append((component, root, original_angle))

    for anchor, branches in by_anchor.items():
        anchor_x, anchor_y = updated[anchor]
        occupied = []
        for neighbor in mol.GetAtomWithIdx(anchor).GetNeighbors():
            index = neighbor.GetIdx()
            if index not in ring_atoms:
                continue
            occupied.append(math.atan2(updated[index][1] - anchor_y, updated[index][0] - anchor_x))
        remaining = list(branches)
        while remaining:
            target = _largest_angular_gap_midpoint(occupied)
            component, root, original_angle = min(
                remaining,
                key=lambda item: abs(math.atan2(math.sin(item[2] - target), math.cos(item[2] - target))),
            )
            candidates = []
            for offset_degrees in (0, -10, 10, -20, 20, -30, 30):
                angle = (target + math.radians(offset_degrees)) % (2 * math.pi)
                if occupied:
                    separation = min(
                        abs(math.atan2(math.sin(angle - value), math.cos(angle - value)))
                        for value in occupied
                    )
                    if separation < math.radians(25):
                        continue
                positions = _component_positions_about_anchor(
                    component, anchor, root, angle, original, updated
                )
                clearance = _minimum_component_clearance(positions, anchor, updated)
                candidates.append((clearance, angle, positions))
            if not candidates:
                fail("Could not place a ring substituent without an acute bond angle")
            acceptable = [
                item for item in candidates if item[0] >= typical_bond_length * 0.35
            ]
            if acceptable:
                clearance, chosen_angle, positions = acceptable[0]
            else:
                clearance, chosen_angle, positions = max(candidates, key=lambda item: item[0])
            if clearance < typical_bond_length * 0.35:
                fail("Ring-angle cleanup would overlap nonbonded atoms; use a reviewed 2D template")
            updated.update(positions)
            occupied.append(chosen_angle)
            remaining.remove((component, root, original_angle))

    for index, (x, y) in updated.items():
        conformer.SetAtomPosition(index, (x, y, 0.0))


def small_ring_geometry_metrics(mol: Chem.Mol) -> list[dict[str, float | int]]:
    conformer = mol.GetConformer()
    metrics: list[dict[str, float | int]] = []
    for ring in mol.GetRingInfo().AtomRings():
        if len(ring) not in (3, 5):
            continue
        points = [
            np.asarray((conformer.GetAtomPosition(index).x, conformer.GetAtomPosition(index).y), dtype=float)
            for index in ring
        ]
        lengths = [float(np.linalg.norm(points[(i + 1) % len(points)] - points[i])) for i in range(len(points))]
        mean_length = sum(lengths) / len(lengths)
        cv = float(np.std(lengths) / max(mean_length, 1e-12))
        target_angle = 180.0 * (len(points) - 2) / len(points)
        errors = []
        for i, point in enumerate(points):
            left = points[i - 1] - point
            right = points[(i + 1) % len(points)] - point
            cosine = float(left @ right / max(np.linalg.norm(left) * np.linalg.norm(right), 1e-12))
            angle = math.degrees(math.acos(max(-1.0, min(1.0, cosine))))
            errors.append(abs(angle - target_angle))
        metrics.append({
            "size": len(ring),
            "side_cv": cv,
            "max_angle_error_deg": max(errors),
        })
    return metrics


def transformed_coords(mol: Chem.Mol, spec: dict[str, Any]) -> list[tuple[float, float]]:
    conformer = mol.GetConformer()
    raw = [(conformer.GetAtomPosition(i).x, -conformer.GetAtomPosition(i).y) for i in range(mol.GetNumAtoms())]
    cx = sum(x for x, _ in raw) / len(raw)
    cy = sum(y for _, y in raw) / len(raw)
    angle = math.radians(float(spec.get("rotate", 0)))
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    flip_x = bool(spec.get("mirror_x", False))
    flip_y = bool(spec.get("mirror_y", False))
    if flip_x != flip_y:
        encoded_stereo = any(
            atom.GetChiralTag() != Chem.ChiralType.CHI_UNSPECIFIED for atom in mol.GetAtoms()
        ) or any(bond.GetBondDir() != Chem.BondDir.NONE for bond in mol.GetBonds())
        if encoded_stereo:
            fail(
                f"Molecule {spec.get('id', '?')} has encoded stereochemistry and cannot be mirrored; "
                "use rotation or a reviewed stereochemistry-preserving template"
            )
    mirror_x = -1.0 if flip_x else 1.0
    mirror_y = -1.0 if flip_y else 1.0
    adjusted = []
    for x, y in raw:
        x = (x - cx) * mirror_x
        y = (y - cy) * mirror_y
        adjusted.append((x * cos_a - y * sin_a, x * sin_a + y * cos_a))
    min_x = min(x for x, _ in adjusted)
    max_x = max(x for x, _ in adjusted)
    min_y = min(y for _, y in adjusted)
    max_y = max(y for _, y in adjusted)
    width = max(float(spec.get("width", 120)), 1.0)
    height = max(float(spec.get("height", 100)), 1.0)
    scale = min(width / max(max_x - min_x, 0.1), height / max(max_y - min_y, 0.1))
    center_x = float(spec["x"])
    center_y = float(spec["y"])
    acx = (min_x + max_x) / 2
    acy = (min_y + max_y) / 2
    return [(center_x + (x - acx) * scale, center_y + (y - acy) * scale) for x, y in adjusted]


def atom_label(atom: Chem.Atom, labels: dict[str, str]) -> tuple[str, bool]:
    override = labels.get(str(atom.GetIdx()))
    if override:
        return override, True
    if atom.GetAtomicNum() == 0:
        return atom.GetProp("atomLabel") if atom.HasProp("atomLabel") else "R", True
    return atom.GetSymbol(), False


def add_atom_text(node: ET.Element, ids: Ids, x: float, y: float, label: str, generic: bool) -> None:
    if generic:
        node.set("NodeType", "GenericNickname")
        node.set("GenericNickname", label)
        node.set("NumHydrogens", "0")
    box_width = max(8.0, len(label) * 6.2)
    text = ET.SubElement(node, "t", {
        "id": ids.next(),
        "p": f"{fnum(x - box_width / 2)} {fnum(y + 3.5)}",
        "BoundingBox": f"{fnum(x - box_width / 2)} {fnum(y - 5)} {fnum(x + box_width / 2)} {fnum(y + 5)}",
        "LabelJustification": "Center",
        "Justification": "Center",
    })
    span = ET.SubElement(text, "s", {"font": "3", "size": "10", "face": "96"})
    span.text = label


def add_fragment(
    page: ET.Element,
    ids: Ids,
    spec: dict[str, Any],
    base_dir: Path,
) -> tuple[str, Chem.Mol]:
    mol = load_molecule(spec, base_dir)
    display = Chem.Mol(mol)
    try:
        Chem.Kekulize(display, clearAromaticFlags=True)
    except Chem.KekulizeException:
        pass
    ring_geometry = str(spec.get("ring_geometry", "regular")).lower()
    if ring_geometry not in ("regular", "preserve"):
        fail(f"Molecule {spec.get('id', '?')} ring_geometry must be regular or preserve")
    if ring_geometry == "regular":
        regularize_ring_geometry(display)
        for metric in small_ring_geometry_metrics(display):
            if metric["side_cv"] > 0.03 or metric["max_angle_error_deg"] > 4.0:
                fail(
                    f"Molecule {spec.get('id', '?')} has a non-regular {metric['size']}-member ring "
                    f"after cleanup (side CV={metric['side_cv']:.3f}, "
                    f"max angle error={metric['max_angle_error_deg']:.1f} deg); "
                    "supply a reviewed 2D template or explicitly set ring_geometry=preserve"
                )
    chiral_atoms = {
        atom.GetIdx()
        for atom in display.GetAtoms()
        if atom.GetChiralTag() != Chem.ChiralType.CHI_UNSPECIFIED
    }
    preserve_wedges = bool(spec.get("preserve_wedge_bonds", False))
    if chiral_atoms and preserve_wedges:
        # RDKit assigns tetrahedral tags while reading V2000 and clears the
        # live BondDir, but retains the source column as _MolFileBondStereo.
        # Restore exactly those source-selected perspective bonds.
        for bond in display.GetBonds():
            if not bond.HasProp("_MolFileBondStereo"):
                continue
            value = int(bond.GetIntProp("_MolFileBondStereo"))
            if value == 1:
                bond.SetBondDir(Chem.BondDir.BEGINWEDGE)
            elif value == 6:
                bond.SetBondDir(Chem.BondDir.BEGINDASH)
        directed_origins = {
            bond.GetBeginAtomIdx()
            for bond in display.GetBonds()
            if bond.GetBondDir() in (Chem.BondDir.BEGINWEDGE, Chem.BondDir.BEGINDASH)
        }
        missing = sorted(chiral_atoms - directed_origins)
        if missing:
            fail(
                f"Molecule {spec.get('id', '?')} requested preserve_wedge_bonds but "
                f"stereocenters {missing} have no source-directed wedge/hash bond"
            )
    elif chiral_atoms:
        Chem.WedgeMolBonds(display, display.GetConformer())
    coords = transformed_coords(display, spec)
    min_x = min(x for x, _ in coords) - 12
    max_x = max(x for x, _ in coords) + 12
    min_y = min(y for _, y in coords) - 12
    max_y = max(y for _, y in coords) + 12
    fragment_id = ids.next()
    fragment = ET.SubElement(page, "fragment", {
        "id": fragment_id,
        "BoundingBox": f"{fnum(min_x)} {fnum(min_y)} {fnum(max_x)} {fnum(max_y)}",
    })
    atom_ids: dict[int, str] = {}
    labels = {str(key): str(value) for key, value in spec.get("atom_labels", {}).items()}
    raw_bond_styles = spec.get("bond_styles", {})
    if not isinstance(raw_bond_styles, dict):
        fail(f"Molecule {spec.get('id', '?')} bond_styles must be an object")
    bond_styles: dict[tuple[int, int], dict[str, Any]] = {}
    for key, value in raw_bond_styles.items():
        try:
            first, second = (int(part) for part in str(key).split("-", 1))
        except (TypeError, ValueError):
            fail(f"Invalid bond_styles key {key!r}; use atom-index pairs such as 3-4")
        if not isinstance(value, dict):
            fail(f"Bond style {key!r} must be an object")
        if display.GetBondBetweenAtoms(first, second) is None:
            fail(f"Bond style {key!r} does not identify a bond in molecule {spec.get('id', '?')}")
        bond_styles[tuple(sorted((first, second)))] = value
    for atom, (x, y) in zip(display.GetAtoms(), coords):
        atom_id = ids.next()
        atom_ids[atom.GetIdx()] = atom_id
        attrs = {"id": atom_id, "p": f"{fnum(x)} {fnum(y)}", "Z": atom_id}
        label, generic = atom_label(atom, labels)
        if atom.GetAtomicNum() not in (0, 6):
            attrs["Element"] = str(atom.GetAtomicNum())
            attrs["NumHydrogens"] = str(atom.GetTotalNumHs(includeNeighbors=True))
            attrs["NeedsClean"] = "yes"
        node = ET.SubElement(fragment, "n", attrs)
        if atom.GetAtomicNum() not in (6,) or generic:
            add_atom_text(node, ids, x, y, label, generic)

    for bond in display.GetBonds():
        order = bond.GetBondTypeAsDouble()
        attrs = {
            "id": ids.next(),
            "Z": ids.next(),
            "B": atom_ids[bond.GetBeginAtomIdx()],
            "E": atom_ids[bond.GetEndAtomIdx()],
        }
        if order != 1.0:
            attrs["Order"] = str(int(order)) if order.is_integer() else fnum(order)
        direction = bond.GetBondDir()
        if direction == Chem.BondDir.BEGINWEDGE:
            attrs["Display"] = "WedgeBegin"
        elif direction == Chem.BondDir.BEGINDASH:
            attrs["Display"] = "WedgedHashBegin"
        style = bond_styles.get(tuple(sorted((bond.GetBeginAtomIdx(), bond.GetEndAtomIdx()))), {})
        color = str(style.get("color", "")).lower()
        if color:
            if color != "red":
                fail(f"Unsupported bond color {color!r}; currently only red is supported")
            attrs["color"] = "4"
        if style.get("line_width") is not None:
            attrs["LineWidth"] = fnum(float(style["line_width"]))
        ET.SubElement(fragment, "b", attrs)
    return fragment_id, mol


def text_box(text: str, x: float, y: float, size: float, align: str) -> tuple[float, float, float, float]:
    lines = text.splitlines() or [""]
    width = max(sum(1.0 if ord(ch) < 128 else 1.8 for ch in line) for line in lines) * size * 0.58
    height = len(lines) * size * 1.25
    if align == "center":
        return x - width / 2, y - height, x + width / 2, y + 2
    if align == "right":
        return x - width, y - height, x, y + 2
    return x, y - height, x + width, y + 2


def add_text(page: ET.Element, ids: Ids, spec: dict[str, Any]) -> str:
    object_id = ids.next()
    text_value = str(spec.get("text", ""))
    x, y = float(spec["x"]), float(spec["y"])
    size = float(spec.get("size", 12))
    align = str(spec.get("align", "left")).lower()
    left, top, right, bottom = text_box(text_value, x, y, size, align)
    attrs = {
        "id": object_id,
        "p": f"{fnum(x)} {fnum(y)}",
        "BoundingBox": f"{fnum(left)} {fnum(top)} {fnum(right)} {fnum(bottom)}",
        "Z": object_id,
        "LineHeight": "auto",
    }
    if align == "center":
        attrs["Justification"] = "Center"
        attrs["CaptionJustification"] = "Center"
    elif align == "right":
        attrs["Justification"] = "Right"
    lines = text_value.splitlines()
    if len(lines) > 1:
        offset = 0
        starts = []
        for line in lines:
            offset += len(line) + 1
            starts.append(str(offset))
        attrs["LineStarts"] = " ".join(starts)
    text = ET.SubElement(page, "t", attrs)
    span_attrs = {"font": "5" if any(ord(ch) > 255 for ch in text_value) else "3", "size": fnum(size)}
    if spec.get("bold", False):
        span_attrs["face"] = "1"
    if spec.get("color") == "red":
        # CDXML color IDs are offset from the zero-based child position:
        # white=2, black=3, red=4 in the standard ChemDraw color table.
        span_attrs["color"] = "4"
        text.set("color", "4")
    span = ET.SubElement(text, "s", span_attrs)
    span.text = text_value
    return object_id


def add_graphic(page: ET.Element, ids: Ids, spec: dict[str, Any], arrow: bool) -> str:
    object_id = ids.next()
    x1, y1 = float(spec["x1"]), float(spec["y1"])
    x2, y2 = float(spec["x2"]), float(spec["y2"])
    attrs = {
        "id": object_id,
        "BoundingBox": f"{fnum(x1)} {fnum(y1)} {fnum(x2)} {fnum(y2)}",
        "Z": object_id,
        "GraphicType": "Line",
    }
    if arrow:
        # ChemDraw places the arrowhead at the first BoundingBox endpoint.
        # Therefore x1/y1 are the head and x2/y2 are the tail.
        arrow_type = str(spec.get("type", "forward"))
        attrs["ArrowType"] = {
            "forward": "FullHead",
            "equilibrium": "Equilibrium",
            "resonance": "Resonance",
            "retrosynthetic": "RetroSynthetic",
        }.get(arrow_type, "FullHead")
        attrs["HeadSize"] = str(spec.get("head_size", 1000))
    if spec.get("line_width"):
        attrs["LineWidth"] = str(spec["line_width"])
    ET.SubElement(page, "graphic", attrs)
    return object_id


def validate_layout(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        fail("Layout JSON must be an object")
    page = data.get("page", {})
    if not isinstance(page, dict) or float(page.get("width", 0)) <= 0 or float(page.get("height", 0)) <= 0:
        fail("page.width and page.height must be positive")
    for key in ("molecules", "arrows", "texts", "lines"):
        if not isinstance(data.get(key, []), list):
            fail(f"{key} must be a list")
    validation_level = str(data.get("validation_level", "fast")).lower()
    if validation_level not in ("fast", "standard", "strict"):
        fail("validation_level must be fast, standard, or strict")
    data["validation_level"] = validation_level
    return data


def build_document(layout: dict[str, Any], base_dir: Path, output: Path) -> dict[str, Chem.Mol]:
    ids = Ids()
    page_spec = layout["page"]
    width, height = float(page_spec["width"]), float(page_spec["height"])
    # ChemDraw 16 on macOS prompts for confirmation when a CDXML page uses an
    # arbitrary custom paper rectangle. Keep the drawing/content bounds exact,
    # but place them on the native printable-page grid used by ChemDraw.
    printable_width = float(page_spec.get("printable_page_width", 523))
    printable_height = float(page_spec.get("printable_page_height", 770))
    width_pages = max(1, math.ceil(width / printable_width))
    height_pages = max(1, math.ceil(height / printable_height))
    paper_width = printable_width * width_pages
    paper_height = printable_height * height_pages
    root = ET.Element("CDXML", {
        "CreationProgram": "Codex ChemDraw Structures",
        "Name": output.name,
        "BoundingBox": f"0 0 {fnum(width)} {fnum(height)}",
        "FractionalWidths": "yes",
        "InterpretChemically": "yes",
        "ShowAtomStereo": "no",
        "ShowBondStereo": "no",
        "ShowTerminalCarbonLabels": "no",
        "ShowNonTerminalCarbonLabels": "no",
        "HideImplicitHydrogens": "no",
        "LabelFont": "3",
        "LabelSize": "10",
        "LabelFace": "96",
        "CaptionFont": "3",
        "CaptionSize": "12",
        "BondLength": str(page_spec.get("bond_length", 30)),
        "LineWidth": "1",
        "BoldWidth": "4",
        "ChainAngle": "120",
        "LabelJustification": "Auto",
        "CaptionJustification": "Left",
        "PrintMargins": "36 36 36 36",
        "MacPrintInfo": "000300000048004800000000030F022FFFEEFFEE033802410367057B03DF000000000000000000000000000000000000006400000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000",
        "color": "0",
        "bgcolor": "1",
    })
    colors = ET.SubElement(root, "colortable")
    for red, green, blue in ((1, 1, 1), (0, 0, 0), (1, 0, 0)):
        ET.SubElement(colors, "color", {"r": str(red), "g": str(green), "b": str(blue)})
    fonts = ET.SubElement(root, "fonttable")
    ET.SubElement(fonts, "font", {"id": "3", "charset": "iso-8859-1", "name": "Arial"})
    ET.SubElement(fonts, "font", {"id": "5", "charset": "unicode", "name": "PingFang SC"})
    page = ET.SubElement(root, "page", {
        "id": ids.next(),
        "BoundingBox": f"0 0 {fnum(paper_width)} {fnum(paper_height)}",
        "HeaderPosition": "36",
        "FooterPosition": "36",
        "PrintTrimMarks": "yes",
        "HeightPages": str(height_pages),
        "WidthPages": str(width_pages),
    })

    object_ids: dict[str, str] = {}
    source_molecules: dict[str, Chem.Mol] = {}
    for spec in layout.get("molecules", []):
        logical_id = str(spec["id"])
        if logical_id in object_ids:
            fail(f"Duplicate object id: {logical_id}")
        fragment_id, mol = add_fragment(page, ids, spec, base_dir)
        object_ids[logical_id] = fragment_id
        source_molecules[logical_id] = mol
    for spec in layout.get("texts", []):
        object_ids[str(spec["id"])] = add_text(page, ids, spec)
    for spec in layout.get("arrows", []):
        object_ids[str(spec["id"])] = add_graphic(page, ids, spec, True)
    for spec in layout.get("lines", []):
        object_ids[str(spec["id"])] = add_graphic(page, ids, spec, False)

    reactions = layout.get("reactions", [])
    if reactions:
        scheme = ET.SubElement(page, "scheme", {"id": ids.next()})
        for reaction in reactions:
            def refs(key: str) -> str:
                return " " + " ".join(object_ids[str(item)] for item in reaction.get(key, [])) if reaction.get(key) else ""
            attrs = {"id": ids.next()}
            mapping = {
                "reactants": "ReactionStepReactants",
                "products": "ReactionStepProducts",
                "arrows": "ReactionStepArrows",
                "above": "ReactionStepObjectsAboveArrow",
                "below": "ReactionStepObjectsBelowArrow",
            }
            for source_key, cdxml_key in mapping.items():
                value = refs(source_key)
                if value:
                    attrs[cdxml_key] = value
            ET.SubElement(scheme, "step", attrs)

    xml_body = ET.tostring(root, encoding="unicode")
    output.write_text(
        '<?xml version="1.0" encoding="UTF-8" ?>\n'
        '<!DOCTYPE CDXML SYSTEM "http://www.cambridgesoft.com/xml/cdxml.dtd" >\n'
        + xml_body
        + "\n",
        encoding="utf-8",
    )
    return source_molecules


def main() -> int:
    if len(sys.argv) != 3:
        print("Usage: create_chemdraw_document.py layout.json output.cdxml", file=sys.stderr)
        return 2
    layout_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])
    if output_path.suffix.lower() != ".cdxml":
        fail("Output must use the .cdxml extension")
    try:
        layout = validate_layout(json.loads(layout_path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"Could not read layout JSON: {exc}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    molecules = build_document(layout, layout_path.resolve().parent, output_path)
    print(output_path)
    print(f"molecules={len(molecules)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
