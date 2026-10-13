#!/usr/bin/env python3
"""Validate a reaction-scheme transcription and create review artifacts."""

from __future__ import annotations

import csv
import html
import json
import math
import sys
import textwrap
import zipfile
from pathlib import Path
from typing import Any


ARROW_TYPES = {
    "forward",
    "equilibrium",
    "resonance",
    "retrosynthetic",
    "dashed",
    "no_reaction",
    "custom",
}
ARROW_DIRECTIONS = {"right", "left", "bidirectional", "up", "down", "custom"}
ROLES = {
    "reagent",
    "catalyst",
    "ligand",
    "base",
    "acid",
    "oxidant",
    "reductant",
    "additive",
    "initiator",
    "solvent",
    "gas",
    "energy",
    "workup",
    "purification",
    "other",
}
CONFIDENCE = {"certain", "probable", "uncertain", "unresolved"}


def fail(message: str) -> None:
    raise SystemExit(message)


def ensure_finite(value: Any, path: str = "root") -> None:
    if isinstance(value, float) and not math.isfinite(value):
        fail(f"Non-finite number at {path}")
    if isinstance(value, dict):
        for key, child in value.items():
            ensure_finite(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            ensure_finite(child, f"{path}[{index}]")


def string_list(value: Any, field: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        fail(f"{field} must be a string or a list of strings")
    return value


def entities(value: Any, field: str) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        fail(f"{field} must be a list")
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        if isinstance(item, str):
            normalized.append({"label": item})
        elif isinstance(item, dict) and str(item.get("label", "")).strip():
            normalized.append(dict(item))
        else:
            fail(f"{field}[{index}] requires a non-empty label")
    return normalized


def validate_component(component: Any, field: str) -> dict[str, Any]:
    if not isinstance(component, dict):
        fail(f"{field} must be an object")
    raw_text = str(component.get("raw_text", "")).strip()
    if not raw_text:
        fail(f"{field}.raw_text is required")
    role = str(component.get("role", "other")).strip().lower()
    if role not in ROLES:
        fail(f"{field}.role must be one of {sorted(ROLES)}")
    confidence = str(component.get("confidence", "certain")).strip().lower()
    if confidence not in CONFIDENCE:
        fail(f"{field}.confidence must be one of {sorted(CONFIDENCE)}")
    for key in ("equivalents", "mol_percent"):
        value = component.get(key)
        if isinstance(value, (int, float)) and value < 0:
            fail(f"{field}.{key} cannot be negative")
    result = dict(component)
    result["raw_text"] = raw_text
    result["role"] = role
    result["confidence"] = confidence
    result["alternatives"] = string_list(result.get("alternatives"), f"{field}.alternatives")
    return result


def validate_scheme(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        fail("Top-level JSON must be an object")
    ensure_finite(data)
    scheme_id = str(data.get("scheme_id", "scheme")).strip() or "scheme"
    raw_steps = data.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        fail("steps must be a non-empty list")

    seen: set[str] = set()
    steps: list[dict[str, Any]] = []
    for index, raw_step in enumerate(raw_steps):
        field = f"steps[{index}]"
        if not isinstance(raw_step, dict):
            fail(f"{field} must be an object")
        step = dict(raw_step)
        step_id = str(step.get("step_id", index + 1)).strip()
        if not step_id or step_id in seen:
            fail(f"{field}.step_id must be non-empty and unique")
        seen.add(step_id)

        arrow = step.get("arrow", {})
        if not isinstance(arrow, dict):
            fail(f"{field}.arrow must be an object")
        arrow_type = str(arrow.get("type", "")).strip().lower()
        direction = str(arrow.get("direction", "right")).strip().lower()
        if arrow_type not in ARROW_TYPES:
            fail(f"{field}.arrow.type must be one of {sorted(ARROW_TYPES)}")
        if direction not in ARROW_DIRECTIONS:
            fail(f"{field}.arrow.direction must be one of {sorted(ARROW_DIRECTIONS)}")
        arrow = dict(arrow)
        arrow["type"] = arrow_type
        arrow["direction"] = direction

        step["step_id"] = step_id
        step["arrow"] = arrow
        step["reactants"] = entities(step.get("reactants"), f"{field}.reactants")
        step["products"] = entities(step.get("products"), f"{field}.products")
        step["text_above"] = string_list(step.get("text_above"), f"{field}.text_above")
        step["text_below"] = string_list(step.get("text_below"), f"{field}.text_below")
        step["notes"] = string_list(step.get("notes"), f"{field}.notes")
        components = step.get("components", [])
        if not isinstance(components, list):
            fail(f"{field}.components must be a list")
        step["components"] = [
            validate_component(component, f"{field}.components[{component_index}]")
            for component_index, component in enumerate(components)
        ]
        confidence = str(step.get("confidence", "certain")).strip().lower()
        if confidence not in CONFIDENCE:
            fail(f"{field}.confidence must be one of {sorted(CONFIDENCE)}")
        step["confidence"] = confidence
        steps.append(step)

    normalized = dict(data)
    normalized["scheme_id"] = scheme_id
    normalized["steps"] = steps
    return normalized


def compact(value: Any) -> str:
    if value in (None, "", [], {}):
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def entity_text(items: list[dict[str, Any]]) -> str:
    return " + ".join(str(item["label"]) for item in items) or "?"


def arrow_symbol(arrow_type: str, direction: str) -> str:
    if arrow_type == "equilibrium":
        return "⇌"
    if arrow_type == "resonance":
        return "↔"
    if arrow_type == "retrosynthetic":
        return "⇒" if direction != "left" else "⇐"
    if arrow_type == "no_reaction":
        return "↛"
    if direction == "left":
        return "←"
    if direction == "up":
        return "↑"
    if direction == "down":
        return "↓"
    if direction == "bidirectional":
        return "↔"
    return "→"


def write_steps_csv(path: Path, scheme: dict[str, Any]) -> None:
    fields = [
        "scheme_id", "step_id", "reactants", "products", "arrow_type",
        "arrow_direction", "arrow_geometry", "text_above", "text_below",
        "temperature", "time", "pressure", "atmosphere", "concentration",
        "yield", "selectivity", "workup", "purification", "confidence",
        "source_region", "notes",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for step in scheme["steps"]:
            arrow = step["arrow"]
            writer.writerow({
                "scheme_id": scheme["scheme_id"],
                "step_id": step["step_id"],
                "reactants": compact(step["reactants"]),
                "products": compact(step["products"]),
                "arrow_type": arrow["type"],
                "arrow_direction": arrow["direction"],
                "arrow_geometry": arrow.get("geometry", "horizontal"),
                "text_above": compact(step["text_above"]),
                "text_below": compact(step["text_below"]),
                "temperature": compact(step.get("temperature")),
                "time": compact(step.get("time")),
                "pressure": compact(step.get("pressure")),
                "atmosphere": compact(step.get("atmosphere")),
                "concentration": compact(step.get("concentration")),
                "yield": compact(step.get("yield")),
                "selectivity": compact(step.get("selectivity")),
                "workup": compact(step.get("workup")),
                "purification": compact(step.get("purification")),
                "confidence": step["confidence"],
                "source_region": compact(step.get("source_region")),
                "notes": compact(step["notes"]),
            })


def write_components_csv(path: Path, scheme: dict[str, Any]) -> None:
    fields = [
        "scheme_id", "step_id", "sequence", "role", "raw_text",
        "normalized_name", "amount_value", "amount_unit", "equivalents",
        "mol_percent", "concentration_value", "concentration_unit",
        "confidence", "source_region", "alternatives", "notes",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for step in scheme["steps"]:
            for sequence, component in enumerate(step["components"], start=1):
                writer.writerow({
                    "scheme_id": scheme["scheme_id"],
                    "step_id": step["step_id"],
                    "sequence": sequence,
                    "role": component["role"],
                    "raw_text": component["raw_text"],
                    "normalized_name": component.get("normalized_name", ""),
                    "amount_value": component.get("amount_value", ""),
                    "amount_unit": component.get("amount_unit", ""),
                    "equivalents": component.get("equivalents", ""),
                    "mol_percent": component.get("mol_percent", ""),
                    "concentration_value": component.get("concentration_value", ""),
                    "concentration_unit": component.get("concentration_unit", ""),
                    "confidence": component["confidence"],
                    "source_region": compact(component.get("source_region")),
                    "alternatives": compact(component["alternatives"]),
                    "notes": compact(component.get("notes")),
                })


def write_text(path: Path, scheme: dict[str, Any]) -> None:
    lines = [f"Scheme: {scheme['scheme_id']}"]
    for step in scheme["steps"]:
        arrow = step["arrow"]
        symbol = arrow_symbol(arrow["type"], arrow["direction"])
        lines.extend([
            "",
            f"Step {step['step_id']}: {entity_text(step['reactants'])} {symbol} {entity_text(step['products'])}",
            f"Above: {' | '.join(step['text_above']) or '(none)'}",
            f"Below: {' | '.join(step['text_below']) or '(none)'}",
        ])
        if step["components"]:
            lines.append("Components:")
            for component in step["components"]:
                lines.append(
                    f"  - [{component['role']}; {component['confidence']}] {component['raw_text']}"
                )
        for key in ("temperature", "time", "pressure", "atmosphere", "concentration", "yield", "selectivity", "workup", "purification"):
            if step.get(key) not in (None, "", [], {}):
                lines.append(f"{key.replace('_', ' ').title()}: {compact(step[key])}")
        if step["notes"]:
            lines.append(f"Notes: {' | '.join(step['notes'])}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def svg_text_lines(texts: list[str], width: int = 65) -> list[str]:
    lines: list[str] = []
    for text in texts:
        wrapped = textwrap.wrap(text, width=width, break_long_words=False) or [""]
        lines.extend(wrapped)
    return lines


def svg_text_block(
    text: str, x: int, center_y: int, width: int = 30, css_class: str = "label"
) -> str:
    lines = textwrap.wrap(text, width=width, break_long_words=False) or [""]
    line_height = 22
    first_y = center_y - ((len(lines) - 1) * line_height) // 2
    return "".join(
        f'<text x="{x}" y="{first_y + index * line_height}" text-anchor="middle" class="{css_class}">{html.escape(line)}</text>'
        for index, line in enumerate(lines)
    )


def render_arrow(arrow: dict[str, Any], y: int) -> str:
    arrow_type = arrow["type"]
    direction = arrow["direction"]
    x1, x2 = (430, 970) if direction != "left" else (970, 430)
    dash = ' stroke-dasharray="10 8"' if arrow_type == "dashed" else ""
    if arrow_type == "equilibrium":
        return (
            f'<line x1="430" y1="{y-6}" x2="970" y2="{y-6}" class="arrow" marker-end="url(#head)"/>'
            f'<line x1="970" y1="{y+6}" x2="430" y2="{y+6}" class="arrow" marker-end="url(#head)"/>'
        )
    if arrow_type == "resonance" or direction == "bidirectional":
        return f'<line x1="430" y1="{y}" x2="970" y2="{y}" class="arrow" marker-start="url(#headStart)" marker-end="url(#head)"/>'
    if arrow_type == "retrosynthetic":
        return (
            f'<line x1="{x1}" y1="{y-4}" x2="{x2}" y2="{y-4}" class="arrow" marker-end="url(#openHead)"/>'
            f'<line x1="{x1}" y1="{y+4}" x2="{x2}" y2="{y+4}" class="arrow"/>'
        )
    line = f'<line x1="{x1}" y1="{y}" x2="{x2}" y2="{y}" class="arrow"{dash} marker-end="url(#head)"/>'
    if arrow_type == "no_reaction":
        line += f'<line x1="688" y1="{y-18}" x2="712" y2="{y+18}" class="arrow"/><line x1="712" y1="{y-18}" x2="688" y2="{y+18}" class="arrow"/>'
    return line


def write_svg(path: Path, scheme: dict[str, Any]) -> None:
    width = 1400
    row_height = 280
    height = 70 + row_height * len(scheme["steps"])
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<defs><marker id="head" markerWidth="10" markerHeight="8" refX="9" refY="4" orient="auto"><path d="M0,0 L10,4 L0,8 z" fill="#111"/></marker>',
        '<marker id="headStart" markerWidth="10" markerHeight="8" refX="1" refY="4" orient="auto"><path d="M10,0 L0,4 L10,8 z" fill="#111"/></marker>',
        '<marker id="openHead" markerWidth="12" markerHeight="10" refX="11" refY="5" orient="auto"><path d="M0,0 L11,5 L0,10" fill="none" stroke="#111" stroke-width="1.5"/></marker></defs>',
        '<style>.label{font:20px Arial,sans-serif;fill:#111}.small{font:16px Arial,sans-serif;fill:#111}.meta{font:14px Arial,sans-serif;fill:#555}.arrow{stroke:#111;stroke-width:2;fill:none}</style>',
        f'<rect x="0" y="0" width="{width}" height="{height}" fill="white"/>',
        f'<text x="40" y="35" class="label">{html.escape(str(scheme["scheme_id"]))}</text>',
    ]
    for index, step in enumerate(scheme["steps"]):
        top = 65 + index * row_height
        arrow_y = top + 125
        parts.append(f'<text x="40" y="{top+20}" class="meta">Step {html.escape(step["step_id"])}</text>')
        parts.append(svg_text_block(entity_text(step["reactants"]), 220, arrow_y + 7))
        parts.append(svg_text_block(entity_text(step["products"]), 1180, arrow_y + 7))
        parts.append(render_arrow(step["arrow"], arrow_y))
        for line_index, line in enumerate(svg_text_lines(step["text_above"])):
            parts.append(f'<text x="700" y="{top+32+line_index*19}" text-anchor="middle" class="small">{html.escape(line)}</text>')
        for line_index, line in enumerate(svg_text_lines(step["text_below"])):
            parts.append(f'<text x="700" y="{arrow_y+35+line_index*19}" text-anchor="middle" class="small">{html.escape(line)}</text>')
        meta = f"{step['arrow']['type']} / {step['arrow']['direction']} / confidence: {step['confidence']}"
        parts.append(f'<text x="700" y="{top+252}" text-anchor="middle" class="meta">{html.escape(meta)}</text>')
        parts.append(f'<line x1="40" y1="{top+270}" x2="1360" y2="{top+270}" stroke="#ddd"/>')
    parts.append("</svg>\n")
    path.write_text("".join(parts), encoding="utf-8")


def main() -> int:
    if len(sys.argv) != 3:
        print("Usage: create_reaction_scheme_package.py input.json output_dir", file=sys.stderr)
        return 2
    input_path = Path(sys.argv[1])
    out_dir = Path(sys.argv[2])
    if out_dir.exists() and any(out_dir.iterdir()):
        fail(f"Output directory is not empty; choose or clear a run directory: {out_dir}")
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        data = json.loads(input_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"Could not read reaction transcription JSON: {exc}")
    scheme = validate_scheme(data)

    normalized_path = out_dir / "normalized_scheme.json"
    steps_path = out_dir / "reaction_steps.csv"
    components_path = out_dir / "reaction_components.csv"
    text_path = out_dir / "reaction_conditions.txt"
    svg_path = out_dir / "reaction_scheme.svg"
    normalized_path.write_text(
        json.dumps(scheme, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    write_steps_csv(steps_path, scheme)
    write_components_csv(components_path, scheme)
    write_text(text_path, scheme)
    write_svg(svg_path, scheme)

    zip_path = out_dir.with_suffix(".zip")
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for artifact in sorted(out_dir.iterdir()):
            archive.write(artifact, arcname=f"{out_dir.name}/{artifact.name}")
    for artifact in (normalized_path, steps_path, components_path, text_path, svg_path, zip_path):
        print(artifact)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
