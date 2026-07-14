---
name: auto-g16-chemdraw-structures
description: Rapidly reconstruct, validate, and create ChemDraw-compatible structures and complete reaction schemes from names, identifiers, SMILES/InChI, screenshots, figures, papers, drugs, ligands, catalysts, and stereochemical requests. Supports explicit final command suffixes `，快速` for a best-effort editable draft within two minutes and `，严格` for full chemical, depiction, transcription, and native ChemDraw validation. Use when Codex must convert images into editable molecules, reproduce both sides of arrows, capture conditions and quantities, preserve conventional orientations, consolidate one panel into one CDXML/CDX file, research complex structures, or verify identity and stereochemistry.
---

# Auto-G16 ChemDraw Structures

## Objective

Produce editable, chemically defensible ChemDraw structures and consolidated reaction documents. When the source is one screenshot, panel, page region, or interface, reproduce all visible structures, arrows, conditions, labels, and table/grid elements in one ChemDraw-native document unless the user explicitly requests separation.

## Environment and outputs

Resolve a Python interpreter with RDKit and Pillow once per task and refer to it as `$CHEM_PYTHON`. Prefer an active environment; otherwise locate a compatible Conda or virtual environment. Never hand-write MOL blocks for chiral or complex structures.

Save user-facing deliverables under the current workspace `outputs/` directory:

- `.mol` for one molecule; `.sdf` for a set
- `.rxn` only when every reactant and product is resolved
- `.cdxml`/`.cdx` for a consolidated editable source panel when a reliable writer or ChemDraw automation is available
- `.png` preview, `.csv` manifest, and `.zip` bundle
- `.json` normalized reaction transcription, step/component `.csv` files, and `.svg` scheme preview when arrows or conditions are present

Prefer MOL/SDF over an image-only answer. MOL/SDF is ChemDraw-compatible but does not guarantee native document styling; apply `ACS Document 1996` in ChemDraw when needed.

## Two-mode command protocol

Read [validation-levels.md](references/validation-levels.md) before acting. The public interface has two modes selected by a final suffix:

- `<任务>，快速` — create a best-effort editable CDXML in a 120-second delivery budget. Strip the suffix from the chemistry request, skip research and native GUI work, and label the output `quick-draft`.
- `<任务>，严格` — perform the full identity, stereochemistry, literature-depiction, transcription, serialization, and native ChemDraw validation workflow.

Also accept an ASCII comma plus `快速`/`严格`, and the English aliases `fast`/`strict`. Only a terminal directive selects a mode. An explicit suffix overrides automatic classification even for a drug, natural product, ligand, catalyst, or fragile stereochemical structure; quick output for such chemistry remains an unvalidated draft.

When no suffix is supplied, automatically choose Quick for clear ordinary chemistry and Strict for drugs, natural products, ligands, catalysts, organometallic/coordination structures, complex stereochemistry, ambiguous images, and publication-grade work.

## Quick execution path

1. Inspect the source once and use one layout JSON as the single source of truth.
2. Reuse persistent depiction memory or the source orientation. Generate directly from `smiles` in the layout; avoid intermediate MOL/SDF packages.
3. Reproduce every visible molecule on both sides of arrows plus arrows, text, conditions, quantities, yields, and table lines in one CDXML.
4. Run `scripts/finalize_chemdraw_panel.py layout.json output_dir --stem NAME --quick`. This avoids the slow ChemDraw GUI round trip, preview export, evidence bundle, and ZIP creation while still checking XML integrity, object counts, and visible text.
5. Make one visual spot check only. At about 105 seconds, stop optional work and deliver the generated CDXML.
6. If anything is ambiguous, preserve it as `?`, `R`, or `unresolved` rather than silently inventing detail. Do not delay the quick draft for multi-source confirmation.

Quick mode is a speed/assurance tradeoff requested by the user. Never describe a quick draft as chemically validated.

## Depiction memory

- Treat local depiction memory as the first source for common drawing conventions. Initialize it once per workspace with `scripts/depiction_memory.py init`; by default it uses `.chemdraw-depiction-memory/`, or `CHEMDRAW_DEPICTION_MEMORY` when set.
- The built-in memory contains two independent 50-entry catalogs: `common` for high-frequency carbocyclic/heterocyclic structures and `ligand-scaffold` for recurring ligand skeleton families. The latter spans P(III), P,P/P,N, polypyridyl, oxazoline, diamine, N/O chelates, carbene, pincer, pi, beta-diketiminate, and scorpionate frameworks.
- A ligand-scaffold entry is an editable donor-topology prototype, not permission to substitute a named commercial ligand for the source structure. Read `variable_sites`, rebuild every source-specific substituent, and retain the catalog's donor-pocket direction and conventional core orientation. In Strict or automatic mode a ligand still requires strict validation; an explicit Quick command may use the prototype immediately but the result must remain a quick draft.
- Tetrahedral ligand prototypes carry isomeric SMILES, wedged MOL coordinates, and CIP read-back. Entries marked `chirality.encoding: visual-only` (axial, spiro, or ferrocene-planar) must never be mirrored automatically and require comparison with a stereochemically explicit source plus native ChemDraw review. Entries marked `native_review_required` retain that requirement even when a connectivity/orientation MOL is present.
- dppf/Josiphos-type ferrocene skeletons intentionally have no ordinary MOL template because disconnected fragments cannot encode eta-5 bonding or planar chirality faithfully. Cp/indenyl MOL templates represent only the anionic ring and require native hapticity notation once coordinated.
- Query one time per distinct familiar scaffold batch by repeating `--name` and/or `--smiles`, for example `lookup --name indole --name pyridine --name PHOX --name PyBOX`. Prefer exact-structure matches, then scaffold matches, then built-in name conventions. Reuse the returned absolute `template_mol` whenever the source does not require a different conventional view. Use `list-builtins --catalog ligand-scaffold` or `validate-builtins --catalog ligand-scaffold` when auditing only ligand memory.
- Treat a clear source figure as the authority for its rotation and substituent direction. Use the built-in template to preserve ring geometry and recognizable atom placement, not to override an intentional source orientation.
- Record only a user-approved or literature-reviewed depiction with `record`; never learn from an ambiguous or merely generated draft. Store the exact canonical SMILES, Murcko scaffold, orientation note, provenance, and optional matching MOL template.
- Reuse memory silently in later Quick tasks, while still spot-checking that substituent positions and visible stereochemistry match the current request.

## Required workflow

1. Normalize the request into a structure specification: names/identifiers, exact form, charge, protonation, salt/solvate, isotope, stereochemistry, and requested output.
2. In Strict or automatic mode, choose the applicable intake route. In explicit Quick mode, load only the image/reaction reference needed to reconstruct the supplied panel and skip research/literature references:
   - For names, identifiers, or autonomous online research, read [references/research-and-evidence.md](references/research-and-evidence.md).
   - For screenshots, figures, schemes, or other images, also read [references/image-reconstruction.md](references/image-reconstruction.md).
   - For arrows, reagents, solvents, quantities, conditions, yields, or full reaction schemes, also read [references/reaction-scheme-transcription.md](references/reaction-scheme-transcription.md).
   - For chiral, organometallic, coordination, ligand, polymeric, or otherwise fragile chemistry, also read [references/chemistry-validation.md](references/chemistry-validation.md).
   - For any ligand or catalyst task, also read [references/ligand-scaffold-depictions.md](references/ligand-scaffold-depictions.md) and query the `ligand-scaffold` memory catalog before fresh depiction research.
   - For drugs, natural products, ligands, catalysts, other strict familiar structures, or publication-ready drawings, also read [references/literature-depiction.md](references/literature-depiction.md).
3. Build a detailed evidence ledger only for Strict work or when requested. For Quick reconstruction, the layout plus quick validation report is sufficient.
4. Resolve the structures and transcribe the scheme. Preserve both source-exact text and normalized fields; do not let normalization overwrite ambiguous or unusual source notation.
5. In Strict mode, stop for confirmation when an ambiguity changes constitution, regioisomer, tautomer, salt/protonation state, isotope, stereoisomer, or coordination. In Quick mode, preserve the uncertain feature explicitly and continue when a usable draft is possible.
6. Establish depiction from persistent memory first. Perform fresh literature comparison only in Strict mode when memory is absent or inadequate.
7. Generate 2D coordinates with RDKit, preferring a reviewed literature template and otherwise CoordGen. Use `scripts/create_chemdraw_structures.py` for one or more resolved SMILES.
8. For a screenshot/panel, create one layout JSON and run `scripts/finalize_chemdraw_panel.py` so reactant/product structures, arrows, conditions, labels, and visible table/grid objects share one editable CDXML canvas. Run `scripts/create_reaction_scheme_package.py` only when structured reaction extraction is requested.
9. In Strict mode, inspect every preview at readable resolution and check every ring fusion, substituent position, bond order, charge, stereobond, atom label, fragment, reaction-side assignment, arrow type/direction, text placement, condition token, unit, scaffold orientation, and viewing angle. In Quick mode, do one spot check without iterative polishing.
10. Perform all applicable structure, transcription, and serialization validation in Strict mode. In Quick mode, run the lightweight document-integrity checks only.
11. Deliver the editable CDXML first. Strict output also includes evidence, confidence, depiction convention, source-exact reaction text, normalized conditions, assumptions, and representation limitations.

## Non-negotiable evidence rules

- Browse in Strict mode when the user asks Codex to find a structure online or when a supplied name/image is not independently resolvable from trusted local data. In Quick mode, make at most one direct lookup only when no usable structure can otherwise be drawn.
- Prefer primary or authoritative machine-readable sources. Treat vendor pages, search snippets, and image matches as leads, not sole proof for complex or stereochemical structures.
- Require two independent agreeing sources only for Strict ambiguous reconstruction or a complex named structure when practical. A clear screenshot is sufficient working authority for a Quick draft.
- Never invent hidden bonds, cropped substituents, stereochemistry, counterions, or metal coordination. Use `unresolved` rather than a confident-looking guess.
- Never invent an unreadable reagent, decimal point, unit, equivalent, mol%, temperature, arrow direction, or yield. Preserve uncertain tokens with a confidence flag and source-region note.
- Do not cite a database record unless its identity and exact chemical form match the requested compound.

## Generation and validation gates

Use a CSV with:

```csv
name,smiles,expected_cip,template_mol,depiction_reference_url,literature_examples,literature_consensus,source_url,source_id,source_role,secondary_source_url,secondary_source_id,accessed_at,confidence,representation_limits,note
```

Run:

```bash
"$CHEM_PYTHON" scripts/create_chemdraw_structures.py input.csv outputs/my_structures
```

For one-panel reconstruction, prefer:

```bash
"$CHEM_PYTHON" scripts/finalize_chemdraw_panel.py layout.json outputs/panel --stem panel
```

For Quick mode, always add `--quick`:

```bash
"$CHEM_PYTHON" scripts/finalize_chemdraw_panel.py layout.json outputs/panel --stem panel --quick
```

Quick mode requires only a well-formed CDXML, expected editable object counts, and preservation of supplied visible text. It intentionally skips native round trip and full chemical identity/stereochemistry validation. Label it `quick-draft`.

Before declaring Strict success, require all of the following as applicable:

- RDKit sanitization succeeds and no requested stereocenter remains `?`.
- Canonical isomeric SMILES survives MOL and SDF round trips.
- Formula, formal charge, fragment count, and exact structure form match the evidence.
- Expected CIP labels match when tetrahedral stereochemistry is specified.
- Common structures, drugs, ligands, and catalysts match the modal literature scaffold orientation or document why another convention was selected.
- A supplied `template_mol` is chemically compatible, has 2D coordinates, and successfully constrains the generated depiction.
- The preview is visually checked, not merely generated.
- The manifest contains provenance, confidence, warnings, and representation limits in Strict mode or when requested.

If a Strict gate fails, fix the representation or label the artifact `review-only`; do not call it validated.

For a Strict reaction-scheme package, additionally require:

- Every arrow has a type, direction, step ID, and explicit reactant/product association.
- Arrow-above and arrow-below text are stored separately and preserve source order.
- Reagent, catalyst, solvent, additive, atmosphere, energy input, workup, and purification roles are not conflated.
- Amounts distinguish `equiv`, `mol%`, mass/volume, concentration, pressure, and unspecified catalytic use.
- Source-exact and normalized values coexist; `rt`, `overnight`, `trace`, and similar terms are not converted to invented numbers.
- The SVG/text preview is compared with the source image or paper panel.
- Every molecule visibly before or after an arrow is drawn as an editable structure or an explicitly documented ChemDraw abbreviation, never replaced by a name-only label.
- One source screenshot/panel/interface produces one consolidated ChemDraw-native file. Preserve relative coordinates, scale, orientation, arrow length, line breaks, table columns, and grouping closely enough for direct side-by-side comparison.
- Open the generated CDXML/CDX in ChemDraw and verify the document before calling it final. Re-extract all molecular fragments and compare them with the validated sources when the format supports round-trip parsing.

## Depiction and ChemDraw quality

Apply every item below in Strict mode. In Quick mode use them as best-effort conventions without delaying delivery or claiming validation.

- Prioritize chemistry over style, then target the compact `ACS Document 1996` look.
- Treat literature familiarity as part of correctness: preserve the recognizable scaffold orientation, ring layout, donor-pocket direction, and conventional stereobond placement used by most relevant publications.
- Do not rotate or mirror a familiar scaffold merely to fill space. Never mirror a stereochemical depiction unless the chemical stereochemistry remains correct and the literature convention genuinely requires that view.
- Prefer balanced, symmetric layouts for symmetric molecules and ligands.
- Regenerate or reorient crowded fused aromatics, biaryls, macrocycles, and donor pockets.
- Check alternating bonds and aromatic perception in benzene, naphthyl, pyridyl, indolyl, BINOL-like, and related systems.
- Regularize ordinary 3-6 member ring systems before finalization. A three-member ring must be visually equilateral and an unconstrained five-member ring must be visually regular; fused systems must use consistent shared-edge lengths and conventional polygon geometry. Use `ring_geometry: preserve` only when a trusted source intentionally uses a non-regular conformation, and document that exception.
- Reject rather than deliver a three- or five-member ring whose side-length coefficient of variation exceeds 3% or whose maximum internal-angle error from the regular polygon exceeds 4°, unless the documented source-preservation exception applies.
- After ring cleanup, rotate each singly anchored acyclic substituent as one rigid branch into the largest free angular sector. Place N-substituents on the exterior angle bisector, center substituents attached to cyclopropane carbons in the exterior 300° sector, and center explicit stereochemical H bonds in the remaining free sector. Preserve branch shape, bond length, wedge/dash meaning, scaffold orientation, and connectivity.
- Prefer balanced conventional 2D angles without forcing tetrahedral 109.5° into the page. For trigonal ring nitrogens, distribute the two exterior angles evenly; at fused stereocenters, bisect the available angular gap. Revert or use a reviewed template if angle cleanup creates atom, label, or bond overlap.
- Avoid crossing bonds, unreadable labels, and ambiguous wedging. Preserve explicit H when it carries stereochemical meaning.
- When a source figure deliberately places wedge/hash bonds on particular perspective bonds, encode those directions in the reviewed MOL and set molecule `preserve_wedge_bonds: true`. This requires one directed wedge/hash origin at every tetrahedral center and prevents the CDXML writer from moving an equivalent stereobond onto a less readable ring bond.
- Preserve source-significant bond colors and emphasis as properties of the editable bond, not as an overlaid graphic. Use molecule `bond_styles` keyed by atom-index pairs (for example `"3-4": {"color": "red", "line_width": 4}`), and verify those styles survive the ChemDraw native round trip.

## Stereochemistry and special representations

Apply these as validation gates in Strict mode. In Quick mode preserve visible stereochemical marks but label the result unvalidated.

- Encode explicit R/S, E/Z, cis/trans, alpha/beta, isotope, and relative stereochemical requirements.
- Use `Chem.AssignStereochemistry(..., force=True, cleanIt=True)` and report `Chem.FindMolChiralCenters(..., includeUnassigned=True, useLegacyImplementation=False)`.
- Do not infer a pure enantiomer for a racemate or unspecified commercial material.
- Do not treat an empty tetrahedral-center list as proof that BINOL/BINAP/SPINOL or another atropisomer is achiral. Plain SMILES and V2000 MOL may not encode axial chirality reliably; retain a trusted stereochemical source and state the limitation.
- When importing CDX/CDXML, preserve explicit H and supported wedge/dash bond configuration before stereochemistry assignment.
- For organometallics, hapticity, dative bonds, polymers, Markush structures, and reaction annotations, state format limitations and prefer native ChemDraw review when MOL/SDF cannot preserve the semantics.

## Completion standard

For Quick, return the consolidated editable `.cdxml` first within the time budget and state `模式：快速；状态：quick-draft`. Preview, ZIP, native GUI confirmation, literature evidence, and detailed manifests are optional and normally omitted.

For Strict, return the native-round-tripped `.cdxml` first, then the inspected preview and archive. Add transcription JSON/CSVs, MOL/SDF, manifest, and detailed evidence when applicable. State `模式：严格` plus unresolved stereochemistry and representation limits. Do not claim “accurate” solely because RDKit or OCR accepted the input.
