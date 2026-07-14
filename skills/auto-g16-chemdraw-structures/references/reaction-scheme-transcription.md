# Reaction-scheme arrows and conditions

## Preserve two layers

Keep a source-faithful layer and a normalized layer. The source-faithful layer preserves exact spelling, punctuation, symbols, line breaks, order, and placement above/below the arrow. The normalized layer supports checking and reuse. Never silently replace the source text with an interpretation.

## Segment each step

Assign a stable `step_id` and record:

- reactants, products, intermediates, and their visible labels or linked MOL files
- arrow type: `forward`, `equilibrium`, `resonance`, `retrosynthetic`, `dashed`, `no_reaction`, or `custom`
- arrow direction and whether the arrow is horizontal, vertical, curved, branched, or multi-step
- exact `text_above` and `text_below` arrays in visual reading order
- every condition component with role, raw text, normalized name, quantity, unit, and confidence
- temperature, time, pressure, atmosphere, concentration, wavelength/light, current/potential, microwave/ultrasound, yield, conversion, dr, er/ee, and regioselectivity when shown
- workup and purification text separately from reaction conditions
- source page/panel/crop or bounding-region description for uncertain tokens

## Role classification

Use distinct roles: `reagent`, `catalyst`, `ligand`, `base`, `acid`, `oxidant`, `reductant`, `additive`, `initiator`, `solvent`, `gas`, `energy`, `workup`, `purification`, and `other`. A component may have multiple roles only when the source/context supports them.

Do not infer that:

- text above the arrow is a reactant
- the first listed liquid is the solvent
- `cat.` implies a numerical mol%
- a parenthetical number is automatically equivalents
- `rt` is exactly 20, 23, or 25 °C
- `overnight` has a fixed duration
- `quant.` is 100.0% analytical yield

## Symbols and OCR hazards

Visually verify `μ/µ`, `°`, `±`, `−`, decimal points, commas, primes, superscripts/subscripts, `hν`, `Δ`, `N₂`, `H₂`, `O₂`, `mol%`, `equiv`, `M`, `mM`, `atm`, `bar`, `psi`, `W`, `nm`, `mA`, and `V`. Common OCR confusions include `1/l/I`, `0/O`, `5/S`, `Cl/CI`, `rn/m`, minus/dash, and a decimal point disappearing against a bond or arrow.

For each uncertain token, retain the best transcription, set confidence to `uncertain`, and state alternatives. Do not average or guess unreadable numerical values.

## Normalization

- Store numerical value and unit separately while retaining `raw_text`.
- Store equivalents in `equivalents` and catalyst loading in `mol_percent`; do not put both into one generic amount field.
- Normalize common solvent/reagent names only when unambiguous; retain abbreviations such as THF, DCM, DMF, DMSO, MeCN, and EtOAc in the source layer.
- Preserve ranges and inequalities as text unless the schema explicitly represents them.
- Keep multistage operations (`i`, `ii`, `then`, sequential additions) as ordered substeps.

## Arrow and text generation

When the user requests structured extraction or an audit package, use `scripts/create_reaction_scheme_package.py input.json output_dir` to validate the transcription and generate:

- `normalized_scheme.json`
- `reaction_steps.csv`
- `reaction_components.csv`
- `reaction_conditions.txt`
- `reaction_scheme.svg`
- a ZIP bundle

The SVG is a visual QA/import artifact. For fully editable ChemDraw arrows and text, recreate the validated layout through reliable ChemDraw-native automation or a proven CDXML writer, open the result in ChemDraw, and compare it with both the SVG and the source. Never call an untested hand-written CDXML file final.

## Consolidated ChemDraw document

Treat a screenshot, paper panel, page region, or single application interface as one layout unit. Put every visible reactant and product structure, arrow, condition line, caption, screening table, separator line, and result note into one CDXML/CDX page. Do not deliver molecule files and a separate arrow/text graphic as the primary result.

Use `scripts/finalize_chemdraw_panel.py layout.json output_dir --stem NAME` for the normal end-to-end path. It calls the CDXML writer once, opens and saves the result in ChemDraw once, exports the native preview, validates the final fragments/text/graphics/scheme, bundles the result, and reuses an unchanged build by content hash. Use the lower-level `scripts/create_chemdraw_document.py layout.json output.cdxml` only for debugging or when native ChemDraw automation is unavailable.

During coordinate/text iteration, add `--no-native` and treat the result as review-only; run without that flag once for the final changed layout. If ChemDraw has a modal dialog or stops responding to open events, the finalizer fails within 20 seconds. Clear the dialog and retry. Never force-quit ChemDraw while an unrelated user document is open.

The layout JSON must contain explicit page coordinates for molecules, arrows, texts, and lines plus reaction-object associations. Use MOL files for fully resolved structures that need a reviewed depiction; direct `smiles` is faster for unambiguous achiral structures that do not need a separate structure deliverable. Use ChemDraw generic nickname nodes only for conventional visible abbreviations such as Bpin when matching the source, and keep the expanded validated structure in the companion SDF/manifest.

For arrow objects, `x1,y1` is the arrowhead endpoint and `x2,y2` is the tail endpoint in this writer. Confirm the rendered direction in ChemDraw; do not infer direction merely from increasing x-coordinates. `mirror_x` and `mirror_y` are allowed only for achiral depictions; the writer rejects a single-axis reflection when encoded tetrahedral/wedge stereochemistry is present. Use a reviewed template and rotation for stereochemical molecules.

After generation:

1. Parse the CDXML and confirm the expected fragment count.
2. Compare extractable molecular fragments with the validated source structures; document any abbreviation that prevents a full graph round trip.
3. Open the file in ChemDraw and verify that structures remain editable, arrow associations are intact, text is not clipped, Chinese characters and scientific symbols render, and table alignment matches the source.
4. Compare the whole page side by side with the screenshot. Rework coordinates until the relative layout, structure orientation, scale, arrow length, line breaks, and table geometry are acceptably close.

## Acceptance gate

Compare the reconstructed scheme with the source at high resolution. Check step order, arrowhead direction/type, which line sits above/below each arrow, punctuation, every value/unit, reagent order, and the association of conditions with the correct step. Deliver unresolved tokens explicitly rather than hiding them in a clean redraw.
