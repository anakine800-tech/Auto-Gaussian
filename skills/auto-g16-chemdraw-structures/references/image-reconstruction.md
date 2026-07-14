# Image and screenshot reconstruction

## Principle

Treat image-to-structure as evidence reconstruction, not ordinary OCR. Text recognition can recover labels and compound numbers, but chemistry must be rebuilt and checked atom by atom.

## Procedure

1. Inspect the original image at the highest available resolution. Preserve the unmodified source.
2. Crop individual molecules or reaction components when this improves readability, but retain a map back to the full figure.
3. Transcribe visible names, compound numbers, reagents, solvents, catalysts, quantities, units, arrow types, arrow-above/below text, stereochemical labels, charges, atom labels, and captions.
   Treat a colored or bold bond as a styled chemical bond when it coincides with connectivity; never reproduce it as a detached line overlay.
4. Search the paper, patent, supporting information, catalog, or database record suggested by those labels. Prefer a machine-readable representation of the same numbered compound.
5. Reconstruct each component independently. Explicitly count rings, ring junctions, substituent positions, bond orders, heteroatoms, charges, counterions, wedges/dashes, E/Z geometry, and attachment points.
6. Render a local preview and compare it side by side with the source at the same orientation when useful.
7. Check ring geometry and substituent angles numerically as well as visually. Regularize ordinary three-, five-, and six-member rings and fused shared edges, then place singly anchored substituents on exterior-angle or free-sector bisectors without changing stereochemistry. Reject cleanup that creates overlaps; do not preserve accidental screenshot distortion merely because it is visible. Preserve a deliberately non-regular conformation only when chemically or editorially meaningful and record the exception.
8. Obtain a second independent confirmation when practical. If the image is the only evidence, mark the result provisional and enumerate uncertain features.
9. Preserve source grouping: everything visible in one screenshot or panel belongs in one consolidated ChemDraw document unless the user explicitly requests separate files.

## Reaction schemes

- Segment reactants, reagents/conditions, catalysts, intermediates, and products before drawing.
- Read [reaction-scheme-transcription.md](reaction-scheme-transcription.md) and create a step-level record before redrawing arrows or text.
- Do not encode reagents above the arrow as reactants unless they contribute atoms and that role is established.
- Create `.rxn` only if all reactant and product structures are resolved. Otherwise provide separate MOL/SDF files plus a manifest of unresolved scheme elements.
- Draw structures on both sides of every arrow. Names or compound numbers may accompany structures but must not replace them when the source shows molecular drawings.
- Preserve atom mapping only when it exists in a trusted source or can be established unambiguously; never fabricate mapping.

## Failure conditions

Stop and request a better image or user confirmation when any material feature is hidden, blurred, cropped, or visually ambiguous, including:

- bond order or aromatic fusion
- substituent attachment position
- wedge versus dash or E/Z geometry
- charge/counterion
- R-group definition or Markush variable
- metal hapticity/coordination
- arrow direction/type or whether text belongs above versus below the arrow
- decimal points, minus signs, degree symbols, equivalents, mol%, concentration, pressure, time, or yield

Never output a polished file that conceals these uncertainties.
