# Literature-consistent depiction

## Goal

Make a reader recognize a familiar molecule immediately. For common structures, drugs, ligands, and catalysts, chemical connectivity alone is insufficient: use the scaffold orientation, viewing angle, ring layout, donor-pocket direction, and stereobond placement most often used in the relevant literature.

## Establish the convention

1. Collect at least three independent, chemically matching depictions when practical. Favor original or influential papers, recent reviews, authoritative drug/database records with 2D coordinates, and established supplier drawings. Do not count mirrored or reposted copies as independent evidence.
2. Confirm that every candidate is the same constitution, salt/form, oxidation state, and stereoisomer before comparing layout.
3. Identify the modal convention rather than copying the first image found. Compare:
   - scaffold rotation and left-to-right reading direction
   - fused-ring geometry and ring-junction placement
   - orientation of carbonyls, heteroatoms, substituents, and protecting groups
   - wedges/dashes and whether stereochemistry is shown with an explicit H
   - ligand donor atoms and the direction of the binding pocket
   - catalyst metal/ligand placement, counterions, and coordination annotations
4. Record representative URLs or DOIs, the number of examples reviewed, and a short consensus statement.
5. Select or create a reviewed 2D MOL template embodying that consensus. Use `template_mol` in the generation CSV so the script constrains the final coordinates to it.

If two conventions are both common, choose the one used by the target journal, reaction class, or subfield and disclose the choice. If no consensus exists, use the clearest chemically faithful view and mark the depiction convention as `no clear consensus`.

## Molecule-class guidance

### Familiar organic molecules and drugs

- Preserve the conventional orientation of signature fused rings, beta-lactams, steroids, alkaloids, nucleosides, sugars, macrocycles, and other instantly recognizable cores.
- Prefer the same main scaffold direction used in labels, reviews, and medicinal chemistry schemes; avoid a novel rotation that makes analog comparison harder.
- Keep pharmacophore-defining heteroatoms and side chains visible and uncrowded.

### Ligands

- Orient chelating donor atoms toward a readable common binding pocket and bulky substituents outward when this matches the literature.
- Preserve the conventional views of BINOL/BINAP/SPINOL, BOX/PyBOX, salen, phosphoramidite, NHC, pincer, and related ligand families.
- For axial or planar chirality, use a trusted depiction of the exact stereoisomer. A visually pleasing mirror image may communicate the opposite stereoisomer.
- Keep a ligand series on a shared core template so structural differences can be scanned without mental rotation.

### Catalysts and complexes

- Follow the convention used for the active catalyst or precatalyst actually requested; do not silently replace one with the other.
- Place metal, donor atoms, hapticity/bridging marks, counterions, and charge where the literature normally shows them.
- Use native ChemDraw review when MOL/SDF cannot preserve dative, haptic, multicenter, or coordination semantics.

## Template rules

- Download or redraw the template only from a depiction whose identity and stereochemistry have been verified.
- Preserve its 2D coordinates; do not run unconstrained cleanup afterward.
- A template may be the exact molecule or a common substructure. It must match the target chemically and contain a 2D conformer.
- Inspect the constrained result because unmatched substituents can still be placed poorly.
- Save a local copy of the reviewed template with the run artifacts when licensing and source terms permit; otherwise record the direct reference and create an original coordinate template based on the consensus.

## Acceptance gate

Do not finalize a familiar drug, ligand, or catalyst until a human reader can compare the preview with the representative literature depictions without mentally rotating or mirroring the main scaffold. Record `template-constrained`, `manual literature match`, or `no clear consensus` in the manifest.
