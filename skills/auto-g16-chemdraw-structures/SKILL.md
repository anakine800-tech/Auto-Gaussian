---
name: auto-g16-chemdraw-structures
description: Create ChemDraw-compatible chemical structure files from compound names, SMILES, screenshots, reaction images, ligands, catalysts, or chiral structure requests. Use when the user asks to draw molecules for ChemDraw, generate MOL/SDF/RXN/CDXML-like deliverables, convert chemical structures into files ChemDraw can open, make previews, package multiple compounds, or verify stereochemistry such as R/S, S,S, E/Z, cis/trans, BOX/PyBOX ligands, drugs, catalysts, and reaction components.
---

# Auto-G16 ChemDraw Structures

## Overview

Create ChemDraw-ready chemical structure deliverables using RDKit when available. Prefer deterministic structure files plus a preview image so the user can confirm the chemistry before using ChemDraw.

## Environment

Use the user's RDKit environment first:

```bash
<MAC_HOME>/miniforge3/envs/chem/bin/python
```

If that path is missing, locate another Python with RDKit before generating files. Do not silently fall back to hand-written MOL blocks for chiral or complex molecules.

## Outputs

Save final user-facing files under the current workspace `outputs/` folder.

Use:

- `.mol` for a single molecule
- `.sdf` for multiple molecules
- `.rxn` for simple reaction skeletons when reactants/products are known
- `.cdxml` or ChemDraw document output when page/style fidelity matters and a reliable writer is available
- `.png` preview for user confirmation
- `.csv` manifest for names, formulas, molecular weights, SMILES, and stereochemistry
- `.zip` when multiple files belong together

## Workflow

1. Identify each requested structure from a name, SMILES, image, or user-provided context.
2. If the identity, regioisomer, tautomer, salt form, protonation state, or stereochemistry is ambiguous, ask for confirmation before finalizing.
3. For named compounds, use reliable known SMILES only when confident; otherwise search or ask the user for a structure reference.
4. Generate 2D coordinates with RDKit. Prefer CoordGen when available, especially for fused aromatics, biaryls, macrocycles, and ligands.
5. Export ChemDraw-compatible `.mol` or `.sdf` files.
6. Generate a preview PNG and inspect it when possible. Check that the structure is symmetric/pleasant for common publication depictions, not merely parseable.
7. Validate chemistry-specific features: aromatic single/double bond placement, formal charges, valence, atom connectivity, stereochemistry, and ligand donor atoms.
8. Report the output links and any assumptions, especially stereochemistry.

## Depiction Quality Rules

For molecules intended for publication or ChemDraw editing:

- Prefer the ChemDraw `ACS Document 1996` document style when creating or post-processing ChemDraw-native files. This is the default requested style unless the user asks for a different journal or template.
- Inspect the preview image before finalizing. The drawing should be balanced, readable, and close to common journal depictions for that molecule class.
- For symmetric ligands, make the ligand look symmetric when the chemistry is symmetric. RDKit coordinates may be chemically valid but visually awkward; regenerate coordinates with CoordGen, rotate the molecule, or use a better SMILES atom order when needed.
- For fused aromatics and heteroaromatics, verify that alternating bonds and aromatic perception are correct. Do not accept a preview where benzene, naphthyl, pyridyl, indolyl, or BINOL-like rings have broken or implausible single/double-bond placement.
- Avoid cluttered atom labels and crossing bonds around the pharmacophore or metal-binding pocket. If the central donor atoms are crowded, adjust the structure source or coordinates and regenerate.
- If the file will be edited in ChemDraw, prefer chemically correct MOL/SDF plus a PNG preview over a hand-drawn image-only answer.

## ChemDraw Style Rules

Default to `ACS Document 1996` for ChemDraw formatting:

- If generating or editing a ChemDraw-native document such as `.cdx` or `.cdxml`, apply `ACS Document 1996`-style settings whenever the available tooling can do so reliably.
- If delivering `.mol` or `.sdf`, state that the structure is ChemDraw-compatible but the full ChemDraw document style may need to be applied after opening: `File -> Apply Document Settings from -> ACS Document 1996` or the equivalent ChemDraw style/template command.
- When checking previews, judge bond lengths, label sizes, stereobonds, and spacing against the compact ACS-style look, not a large poster-style depiction.
- Do not sacrifice chemical correctness to force a style. Correct connectivity, valence, stereochemistry, and aromatic bond placement come first; style comes after the structure is verified.

## CSV and Input Hygiene

Use a CSV writer or quote fields when names or notes contain commas. A name like `BINOL-derived N,N-dimethyl phosphoramidite ligand` will otherwise be split into multiple CSV columns and the script may try to parse a fragment such as `N-dimethyl` as SMILES.

## Stereochemistry Rules

Encode stereochemistry explicitly when the user specifies `(R)`, `(S)`, `(R,R)`, `(S,S)`, `E`, `Z`, `cis`, `trans`, `alpha`, or `beta`.

For chiral molecules:

- Run `Chem.AssignStereochemistry(..., force=True, cleanIt=True)`.
- Run `Chem.FindMolChiralCenters(..., includeUnassigned=True, useLegacyImplementation=False)`.
- Report detected CIP centers in the manifest or final response.
- If a requested chiral center is detected as `?`, stop and fix the SMILES or ask for confirmation.
- When reviewing CDX/CDXML, never rely on RDKit's default hydrogen-removing import. Preserve explicit H, restore supported `_MolFileBondCfg` wedge/dash directions, and assign stereochemistry afterward; a wedged explicit H may be the only carrier for a tetrahedral center.
- Verify a MOL/SDF serialization round trip against the source canonical isomeric SMILES. If stereochemistry changes, label MOL/SDF as review-only and retain the source CDX/CDXML or a stereochemical SMILES as the calculation source.

For racemates or unspecified commercial materials, state that stereochemistry is unspecified rather than inventing a single enantiomer.

For atropisomeric ligands such as BINOL, BINAP, SPINOL, and phosphoramidite ligands derived from them:

- Do not treat an empty `FindMolChiralCenters` result as proof that the ligand is achiral. RDKit may not encode/report axial chirality from a simple SMILES.
- If the user asks for `(R)-BINOL`, `(S)-BINOL`, `(R)-MonoPhos`, `(S)-MonoPhos`, or related axial chirality, ask for or use a trusted structure reference that explicitly represents the atropisomer, and state any limitation in the manifest.
- If axial chirality cannot be encoded in the generated MOL/SDF, label the file as stereochemistry/atropisomer unspecified rather than silently implying a single enantiomer.

## Phosphoramidite Ligand Checks

For phosphoramidite ligands, including BINOL-derived phosphoramidites:

- Confirm the phosphorus is P(III), neutral, and three-coordinate unless the user explicitly requests an oxide, borane adduct, salt, or metal complex.
- Confirm the phosphorus has one `P-N` bond and two `P-O` bonds for a simple phosphoramidite. Do not accidentally draw `P=O`, phosphoramidate, phosphate, or phosphinite structures.
- Check that amine substituents are correctly attached to nitrogen, not directly to phosphorus or oxygen.
- For BINOL-derived cyclic phosphoramidites, confirm both oxygens connect to the two BINOL oxygen positions and close the `P-O-C...C-O-P` ring.
- Verify the biaryl/BINOL core and naphthyl aromatic bonds in the preview. The most common failure modes are missing aromatic bonds, wrong oxygen attachment position, and unreported axial chirality.

## Script

Use `scripts/create_chemdraw_structures.py` for repeated SMILES-to-ChemDraw generation. Prepare a CSV with columns:

```csv
name,smiles,expected_cip,note
```

`expected_cip` is optional. Use values like `S`, `R`, `S,S`, or leave blank for achiral/unspecified compounds.

Example:

```bash
<MAC_HOME>/miniforge3/envs/chem/bin/python scripts/create_chemdraw_structures.py input.csv outputs/my_structures
```

The script writes individual `.mol` files, one combined `.sdf`, a preview `.png`, a manifest `.csv`, and a `.zip`.

## Known Useful SMILES

Use these only when they match the user's request:

- Aspirin: `CC(=O)Oc1ccccc1C(=O)O`
- Loratadine: `O=C(OCC)N4CC/C(=C2/c1ccc(Cl)cc1CCc3cccnc23)CC4`
- Ibuprofen, stereochemistry unspecified: `CC(C)Cc1ccc(cc1)C(C)C(=O)O`
- `(S,S)-tBu-PyBOX`: `n1c(C8=N[C@@H](C(C)(C)C)CO8)cccc1C9=N[C@@H](C(C)(C)C)CO9`
- BINOL-derived `N,N-dimethyl` phosphoramidite ligand, atropisomer unspecified: `CN(C)P1Oc2ccc3ccccc3c2-c2c(O1)ccc3ccccc23`

## ChemDraw Notes

ChemDraw can usually open `.mol` and `.sdf` directly. If macOS cannot launch an old ChemDraw app automatically, still provide the structure files and tell the user to use ChemDraw `File -> Open`. After opening, use the `ACS Document 1996` document settings unless the user requested another style.
