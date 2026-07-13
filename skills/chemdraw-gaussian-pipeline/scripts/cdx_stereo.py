#!/usr/bin/env python3
"""Load ChemDraw files without losing explicit-H wedge stereochemistry."""

from __future__ import annotations

from typing import Any


def _cfg_value(bond) -> int | None:
    if not bond.HasProp("_MolFileBondCfg"):
        return None
    try:
        return int(bond.GetIntProp("_MolFileBondCfg"))
    except Exception:
        return int(bond.GetProp("_MolFileBondCfg"))


def load_chemdraw_molecules(path: str, Chem) -> tuple[list, list[dict[str, Any]]]:
    """Return CDX/CDXML molecules plus import diagnostics.

    RDKit's ChemDraw reader defaults to ``removeHs=True`` and, in affected
    builds, preserves ChemDraw CFG values only as private bond properties.
    An explicit wedge H can therefore disappear before tetrahedral chirality
    is assigned.  Preserve H, restore supported CFG directions, and then ask
    RDKit to assign tetrahedral tags and CIP labels.
    """

    molecules = list(Chem.MolsFromCDXMLFile(str(path), True, False))
    diagnostics: list[dict[str, Any]] = []
    cfg_to_direction = {
        1: Chem.BondDir.BEGINWEDGE,
        3: Chem.BondDir.BEGINDASH,
    }

    for molecule_index, mol in enumerate(molecules):
        applied: list[dict[str, Any]] = []
        conflicts: list[dict[str, Any]] = []
        unsupported: list[dict[str, Any]] = []
        explicit_hydrogens = [
            atom.GetIdx() for atom in mol.GetAtoms() if atom.GetAtomicNum() == 1
        ]

        for bond in mol.GetBonds():
            cfg = _cfg_value(bond)
            if cfg is None:
                continue
            item = {
                "bond_index": int(bond.GetIdx()),
                "begin_atom": int(bond.GetBeginAtomIdx()),
                "end_atom": int(bond.GetEndAtomIdx()),
                "cfg": int(cfg),
            }
            expected = cfg_to_direction.get(cfg)
            if expected is None:
                unsupported.append(item)
                continue
            existing = bond.GetBondDir()
            if existing not in (Chem.BondDir.NONE, expected):
                item["existing_direction"] = str(existing)
                item["expected_direction"] = str(expected)
                conflicts.append(item)
                continue
            bond.SetBondDir(expected)
            item["direction"] = str(expected)
            applied.append(item)

        Chem.AssignChiralTypesFromBondDirs(mol, replaceExistingTags=False)
        Chem.AssignStereochemistry(mol, force=True, cleanIt=True)
        centers = Chem.FindMolChiralCenters(
            mol, includeUnassigned=True, useLegacyImplementation=False
        )
        diagnostics.append(
            {
                "molecule_index": molecule_index,
                "explicit_hydrogen_atom_indices": explicit_hydrogens,
                "restored_bond_cfg": applied,
                "conflicting_bond_cfg": conflicts,
                "unsupported_bond_cfg": unsupported,
                "chiral_centers": [
                    {"atom_index": int(index), "cip": cip} for index, cip in centers
                ],
            }
        )
    return molecules, diagnostics


def molblock_stereo_roundtrip(mol, Chem) -> dict[str, Any]:
    """Check whether an RDKit MOL block preserves the imported stereochemistry."""

    source_smiles = Chem.MolToSmiles(mol, isomericSmiles=True)
    block = Chem.MolToMolBlock(mol)
    restored = Chem.MolFromMolBlock(block, sanitize=True, removeHs=False)
    restored_smiles = (
        Chem.MolToSmiles(restored, isomericSmiles=True) if restored is not None else None
    )
    return {
        "stereo_preserved": restored_smiles == source_smiles,
        "source_isomeric_smiles": source_smiles,
        "roundtrip_isomeric_smiles": restored_smiles,
    }
