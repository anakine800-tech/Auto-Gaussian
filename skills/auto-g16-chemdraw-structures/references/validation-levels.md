# Execution modes

The user-facing interface has exactly two explicit modes. Parse the final directive after trimming whitespace and terminal punctuation, remove it from the chemistry request, and apply it before classifying the structure.

| Final directive | Mode | Meaning |
| --- | --- | --- |
| `，快速`, `, 快速`, `,fast` | Quick | Best-effort editable draft, normally delivered within two minutes |
| `，严格`, `, 严格`, `,strict` | Strict | Fully checked chemical identity, depiction, transcription, and ChemDraw round trip |

The suffix must be the final instruction, not merely a word occurring inside a compound name or quoted source text. An explicit suffix overrides automatic risk classification, including for drugs, natural products, ligands, catalysts, and stereochemically complex structures.

## Quick

Use a 120-second delivery budget from receipt of actionable input. At roughly 105 seconds stop optional work and finish the generated CDXML.

- Treat a clear supplied image or explicit SMILES as the working authority.
- Use depiction memory and direct in-layout SMILES; do not build a separate evidence package.
- Do not browse, seek a second source, establish literature consensus, run the ChemDraw GUI, export a preview, or create a ZIP unless the structure cannot be drawn at all without one direct lookup.
- Reproduce all visible molecules, arrows, conditions, quantities, labels, and table lines from one source panel in one editable CDXML.
- Run `finalize_chemdraw_panel.py ... --quick`. It performs only fast XML, object-count, and visible-text integrity checks.
- Make at most one visual pass and do not iterate for cosmetic perfection.
- Preserve visible stereobonds and charges, but do not claim that identity, absolute configuration, hidden/cropped content, or conventional literature orientation was validated.
- If a token or cropped group is unclear, use an explicit `?`, `R`, or `unresolved` label when that yields a usable drawing. Never silently invent a precise atom, bond, stereochemistry, reagent, amount, or condition.
- Deliver the `.cdxml` first with status `quick-draft`. Do not call it validated.

## Strict

Use when the user ends the request with `，严格`, or when automatic mode selection chooses strict.

- Resolve exact constitution, charge, form, salt/solvate, isotope, stereochemistry, and coordination.
- Use authoritative and independent evidence where appropriate; establish the conventional literature orientation for drugs, natural products, ligands, catalysts, and familiar complex scaffolds.
- Check every visible molecule, arrow, condition, quantity, label, and source-exact token.
- Validate RDKit sanitization, canonical isomeric round trips, formula, formal charge, fragment count, expected CIP labels, geometry, overlap, and applicable representation limits.
- Run the native ChemDraw open/save/export round trip and inspect the preview at readable resolution.
- Deliver only after every applicable gate passes; otherwise label the result `review-only` and state what remains unresolved.

Strict mode has no two-minute promise because research, ambiguity resolution, and native GUI validation are part of the requested result.

## Automatic mode when no suffix is supplied

Use Quick for clear ordinary structures and routine legible screenshots. Use Strict for drugs, natural products, ligands, catalysts, organometallic/coordination chemistry, axial/planar/helical chirality, polymers/Markush structures, ambiguous images, or publication-grade requests. Internal standard-level checks may be used as a bridge, but do not expose a third command mode.
