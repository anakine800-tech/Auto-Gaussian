#!/usr/bin/env python3
"""Build one ChemDraw panel in quick-draft or strict native-validated mode."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any

from PIL import Image
from rdkit import Chem

import create_chemdraw_document as cdxml_writer


CHEMDRAW_APP_ID = os.environ.get("CHEMDRAW_APP_ID", "com.perkinelmer.ChemDraw.16")
CHEMDRAW_APP_PATH = os.environ.get(
    "CHEMDRAW_APP_PATH", "/Applications/ChemDraw Professional 16.0.app"
)


def fail(message: str) -> None:
    raise SystemExit(message)


def load_layout(path: Path) -> dict[str, Any]:
    try:
        return cdxml_writer.validate_layout(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"Could not read layout JSON: {exc}")


def referenced_files(layout: dict[str, Any], base_dir: Path) -> list[Path]:
    result: list[Path] = []
    for spec in layout.get("molecules", []):
        value = spec.get("mol_file")
        if not value:
            continue
        path = Path(str(value)).expanduser()
        if not path.is_absolute():
            path = base_dir / path
        path = path.resolve()
        if not path.is_file():
            fail(f"Referenced molecule file does not exist: {path}")
        result.append(path)
    return result


def input_digest(
    layout_path: Path,
    molecule_files: list[Path],
    native: bool,
    bundle: bool,
    quick: bool,
) -> str:
    digest = hashlib.sha256()
    for label, path in (
        ("layout", layout_path),
        ("writer", Path(cdxml_writer.__file__ or "")),
        ("finalizer", Path(__file__)),
    ):
        digest.update(label.encode("utf-8"))
        digest.update(path.resolve().read_bytes())
    for path in molecule_files:
        digest.update(str(path).encode("utf-8"))
        digest.update(path.read_bytes())
    digest.update(
        f"quick={quick};native={native};bundle={bundle};app={CHEMDRAW_APP_ID}".encode(
            "ascii"
        )
    )
    return digest.hexdigest()


def artifact_paths(out_dir: Path, stem: str) -> dict[str, Path]:
    return {
        "generated": out_dir / f"{stem}_generated.cdxml",
        "final": out_dir / f"{stem}.cdxml",
        "native_png": out_dir / f"{stem}_native.png",
        "preview": out_dir / f"{stem}_preview.png",
        "report": out_dir / f"{stem}_validation.json",
        "bundle": out_dir / f"{stem}_complete.zip",
    }


def cache_hit(
    paths: dict[str, Path], digest: str, native: bool, bundle: bool
) -> dict[str, Any] | None:
    if not paths["report"].is_file() or not paths["final"].is_file():
        return None
    try:
        report = json.loads(paths["report"].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    required = [paths["final"]]
    if native:
        required.append(paths["preview"])
    if bundle:
        required.append(paths["bundle"])
    if report.get("input_digest") != digest or not all(path.is_file() for path in required):
        return None
    return report


def native_roundtrip(generated: Path, final: Path, native_png: Path) -> None:
    token = f"{os.getpid()}_{int(time.time() * 1000)}"
    launch_input = generated
    temp_cdxml = final.with_name(f"{final.stem}_native_{token}.cdxml")
    temp_png = native_png.with_name(f"{native_png.stem}_native_{token}.png")

    def apple_string(value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"')

    try:
        open_script = f'''
with timeout of 30 seconds
    tell application "{apple_string(CHEMDRAW_APP_PATH)}"
        activate
        open POSIX file "{apple_string(str(launch_input))}" as "ChemDraw XML"
    end tell
end timeout
'''
        subprocess.run(
            ["osascript", "-e", open_script],
            check=True,
            timeout=35,
            capture_output=True,
            text=True,
        )
        print("phase=chemdraw_open_sent", flush=True)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                query = subprocess.run(
                    [
                        "osascript",
                        "-e",
                        f'tell application "{apple_string(CHEMDRAW_APP_PATH)}" to get name of every document',
                    ],
                    check=True,
                    timeout=3,
                    capture_output=True,
                    text=True,
                )
            except subprocess.TimeoutExpired:
                time.sleep(0.15)
                continue
            if launch_input.name in query.stdout:
                break
            time.sleep(0.25)
        else:
            fail(
                f"ChemDraw did not open {launch_input.name} within 30 seconds"
            )
        print("phase=chemdraw_document_ready", flush=True)

        script = f'''
with timeout of 150 seconds
    tell application "{apple_string(CHEMDRAW_APP_PATH)}"
        set targetName to "{apple_string(launch_input.name)}"
        set targetDoc to missing value
        repeat with d in documents
            if name of d is targetName then
                set targetDoc to d
                exit repeat
            end if
        end repeat
        if targetDoc is missing value then error "Opened ChemDraw document not found"
        save targetDoc in POSIX file "{apple_string(str(temp_cdxml))}"
        save targetDoc in POSIX file "{apple_string(str(temp_png))}"
        close targetDoc saving no
    end tell
end timeout
'''
        subprocess.run(
            ["osascript", "-e", script],
            check=True,
            timeout=170,
            capture_output=True,
            text=True,
        )
        print("phase=chemdraw_native_saved", flush=True)
        if not temp_cdxml.is_file() or not temp_png.is_file():
            fail("ChemDraw did not create the expected native CDXML and PNG outputs")
        os.replace(temp_cdxml, final)
        os.replace(temp_png, native_png)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        fail(f"ChemDraw native round trip failed: {detail.strip()}")
    finally:
        for path in (temp_cdxml, temp_png):
            if path.exists():
                path.unlink()


def flatten_png(source: Path, target: Path) -> None:
    image = Image.open(source).convert("RGBA")
    background = Image.new("RGBA", image.size, "white")
    background.alpha_composite(image)
    background.convert("RGB").save(target)


def canonical_smiles(mol: Chem.Mol) -> str:
    return Chem.MolToSmiles(mol, canonical=True, isomericSmiles=True)


def validate_final(
    path: Path,
    layout: dict[str, Any],
    source_molecules: dict[str, Chem.Mol],
) -> tuple[dict[str, int], list[str]]:
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        fail(f"Final CDXML is not valid XML: {exc}")

    counts = {
        # ChemDraw expands GenericNickname labels into nested definition fragments.
        # Count only molecular fragments placed directly on a document page.
        "fragments": len(root.findall(".//page/fragment")),
        "texts": len(root.findall(".//t")),
        "graphics": len(root.findall(".//graphic")),
        "schemes": len(root.findall(".//scheme")),
        "red_bonds": len(root.findall(".//page/fragment/b[@color='4']")),
    }
    expected_fragments = len(layout.get("molecules", []))
    expected_graphics = len(layout.get("arrows", [])) + len(layout.get("lines", []))
    expected_schemes = 1 if layout.get("reactions") else 0
    if counts["fragments"] != expected_fragments:
        fail(f"Fragment count changed: expected {expected_fragments}, found {counts['fragments']}")
    if counts["graphics"] != expected_graphics:
        fail(f"Graphic count changed: expected {expected_graphics}, found {counts['graphics']}")
    if counts["schemes"] != expected_schemes:
        fail(f"Scheme count changed: expected {expected_schemes}, found {counts['schemes']}")

    expected_red_styles = [
        style
        for molecule in layout.get("molecules", [])
        for style in molecule.get("bond_styles", {}).values()
        if str(style.get("color", "")).lower() == "red"
    ]
    if counts["red_bonds"] != len(expected_red_styles):
        fail(
            f"Red bond count changed: expected {len(expected_red_styles)}, "
            f"found {counts['red_bonds']}"
        )
    expected_widths = sorted(
        float(style["line_width"])
        for style in expected_red_styles
        if style.get("line_width") is not None
    )
    found_widths = sorted(
        float(bond.get("LineWidth"))
        for bond in root.findall(".//page/fragment/b[@color='4']")
        if bond.get("LineWidth") is not None
    )
    if expected_widths and expected_widths != found_widths:
        fail(f"Styled red-bond widths changed: expected {expected_widths}, found {found_widths}")

    all_text = "\n".join(text for text in root.itertext() if text)
    for spec in layout.get("texts", []):
        for line in str(spec.get("text", "")).splitlines():
            if line and line not in all_text:
                fail(f"Text disappeared during ChemDraw round trip: {line!r}")

    warnings: list[str] = []
    try:
        restored = list(Chem.MolsFromCDXMLFile(str(path), sanitize=True, removeHs=False))
    except Exception as exc:
        fail(f"RDKit could not parse final CDXML molecules: {exc}")
    if len(restored) != expected_fragments:
        fail(f"RDKit extracted {len(restored)} molecules; expected {expected_fragments}")

    for spec, result in zip(layout.get("molecules", []), restored):
        logical_id = str(spec["id"])
        if spec.get("atom_labels"):
            warnings.append(
                f"{logical_id}: conventional atom-label abbreviation prevents a strict full-graph CDXML round trip"
            )
            continue
        source = source_molecules[logical_id]
        if canonical_smiles(source) != canonical_smiles(result):
            fail(
                f"Structure changed during CDXML round trip for {logical_id}: "
                f"{canonical_smiles(source)} -> {canonical_smiles(result)}"
            )
    return counts, warnings


def validate_quick(
    path: Path,
    layout: dict[str, Any],
) -> tuple[dict[str, int], list[str]]:
    """Run only inexpensive document-integrity checks for a usable quick draft."""
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        fail(f"Generated CDXML is not valid XML: {exc}")

    counts = {
        "fragments": len(root.findall(".//page/fragment")),
        "texts": len(root.findall(".//t")),
        "graphics": len(root.findall(".//graphic")),
        "schemes": len(root.findall(".//scheme")),
        "red_bonds": len(root.findall(".//page/fragment/b[@color='4']")),
    }
    expected = {
        "fragments": len(layout.get("molecules", [])),
        "graphics": len(layout.get("arrows", [])) + len(layout.get("lines", [])),
        "schemes": 1 if layout.get("reactions") else 0,
    }
    for key, value in expected.items():
        if counts[key] != value:
            fail(f"Quick CDXML {key} count mismatch: expected {value}, found {counts[key]}")

    all_text = "\n".join(text for text in root.itertext() if text)
    for spec in layout.get("texts", []):
        for line in str(spec.get("text", "")).splitlines():
            if line and line not in all_text:
                fail(f"Text missing from quick CDXML: {line!r}")

    warnings = [
        "Quick draft: identity, stereochemistry, literature convention, and native "
        "ChemDraw round trip were not strictly validated."
    ]
    return counts, warnings


def write_bundle(
    path: Path,
    artifacts: list[Path],
    molecule_files: list[Path],
) -> None:
    token = f"{os.getpid()}_{int(time.time() * 1000)}"
    temporary = path.with_name(f".{path.stem}_{token}.zip")
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        used: set[str] = set()
        for item in artifacts + molecule_files:
            if not item.is_file():
                continue
            name = item.name
            if name in used:
                name = f"molecules/{name}"
            used.add(name)
            archive.write(item, arcname=name)
    os.replace(temporary, path)


def emit(
    paths: dict[str, Path],
    cache: bool,
    elapsed: float,
    native: bool,
    bundle: bool,
) -> None:
    print(f"cache={'hit' if cache else 'miss'}")
    print(f"elapsed_seconds={elapsed:.3f}")
    keys = ["final", "report"]
    if native:
        keys.append("preview")
    if bundle:
        keys.append("bundle")
    for key in keys:
        if paths[key].is_file():
            print(f"{key}={paths[key]}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("layout", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--stem", help="Output filename stem; defaults to the layout stem")
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Create a usable CDXML draft without GUI round trip, preview, or ZIP bundle",
    )
    parser.add_argument("--no-native", action="store_true", help="Skip ChemDraw round trip (review-only)")
    parser.add_argument("--no-bundle", action="store_true", help="Skip the ZIP bundle")
    parser.add_argument("--force", action="store_true", help="Ignore a matching cached build")
    args = parser.parse_args()

    started = time.perf_counter()
    layout_path = args.layout.expanduser().resolve()
    out_dir = args.output_dir.expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = args.stem or layout_path.stem
    quick = args.quick
    native = not args.no_native and not quick
    bundle = not args.no_bundle and not quick
    paths = artifact_paths(out_dir, stem)
    layout = load_layout(layout_path)
    molecule_files = referenced_files(layout, layout_path.parent)
    digest = input_digest(layout_path, molecule_files, native, bundle, quick)

    if not args.force and cache_hit(paths, digest, native, bundle):
        emit(paths, True, time.perf_counter() - started, native, bundle)
        return 0

    source_molecules = cdxml_writer.build_document(
        layout, layout_path.parent, paths["generated"]
    )
    print("phase=cdxml_generated", flush=True)
    if native:
        native_roundtrip(paths["generated"], paths["final"], paths["native_png"])
        flatten_png(paths["native_png"], paths["preview"])
    else:
        shutil.copy2(paths["generated"], paths["final"])

    if quick:
        counts, warnings = validate_quick(paths["final"], layout)
    else:
        counts, warnings = validate_final(paths["final"], layout, source_molecules)
    report = {
        "status": "quick-draft" if quick else ("validated" if native else "review-only"),
        "execution_mode": "quick" if quick else "strict",
        "validation_level": "quick" if quick else layout.get("validation_level", "strict"),
        "input_digest": digest,
        "native_roundtrip": native,
        "counts": counts,
        "warnings": warnings,
        "final_cdxml": str(paths["final"]),
        "preview": str(paths["preview"]) if native and paths["preview"].is_file() else "",
    }
    paths["report"].write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if bundle:
        write_bundle(
            paths["bundle"],
            [paths["final"], paths["preview"], paths["report"], layout_path],
            molecule_files,
        )
    emit(paths, False, time.perf_counter() - started, native, bundle)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
