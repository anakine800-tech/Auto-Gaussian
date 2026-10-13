# Ligand-scaffold depiction catalog

Use this reference for any ligand, precatalyst, catalyst, or coordination-complex task. The machine-readable catalog is `common-ligand-scaffolds.json`; its `orientation`, `donors`, `variable_sites`, `chirality`, `representation_limit`, and `native_review_required` fields are operational requirements.

## What an entry means

- Each entry is a scaffold family and donor topology, not a claim that one commercial ligand is the generic structure.
- The stored molecule is a recognizable prototype that supplies conventional core geometry. Replace every variable site from the source image, name, or primary record.
- A catalog hit is never sufficient evidence for an exact chiral ligand. Confirm constitution, substituents, charge, stereochemical descriptor, and coordination mode from the requested source.
- Preserve literature-conventional donor-pocket direction. Do not rotate individual rings into a chemically misleading donor arrangement merely to reduce page width.

## Included 50 skeleton families

| Group | Included skeletons |
|---|---|
| Monodentate P | triarylphosphine; trialkylphosphine; dialkylbiarylphosphine; phosphite; phosphoramidite |
| Classical and wide-bite P,P | dppm; dppe; dppp; o-phenylene bisphosphine; xanthene P,P; diphenyl-ether P,P; ferrocene-1,1'-P,P |
| Chiral P,P/P,N | binaphthyl P,P; biphenyl P,P; SEGPHOS; DuPhos; BPE; CHIRAPHOS; Josiphos; PHOX |
| Polypyridyl/diamine | 2,2'-bipyridine; 1,10-phenanthroline; terpyridine; alpha-diimine; ethylenediamine; trans-DACH; DPEN |
| Oxazoline/N,O/O,O | BOX; PyBOX; PyOx; salen; salan; BINOL; SPINOL; TADDOL; porphyrin; acetylacetonate |
| Carbene | normal NHC; saturated NHC; triazolylidene MIC; CAAC |
| Pincer | aryl PCP; aryl PNP; aliphatic PNP; aryl POCOP; aryl NCN |
| Pi/anionic/tripodal | cyclopentadienyl; indenyl; beta-diketiminate (nacnac); hydrotris(pyrazolyl)borate (Tp) |

## Stereochemical handling

1. Tetrahedral prototypes (DuPhos, BPE, CHIRAPHOS, PHOX, DACH, BOX, PyBOX, PyOx, salen, salan, TADDOL, and DPEN) must preserve their isomeric SMILES, MOL wedge/dash data, and catalog `expected_cip` on round trip.
2. BINAP/BINOL/BIPHEP/SEGPHOS-like axial chirality, SPINOL-like spirochirality, and substituted-ferrocene planar chirality are not validated by an empty RDKit tetrahedral-center list. Require an explicit stereochemical source, forbid mirroring, and inspect the native ChemDraw document.
3. Josiphos combines planar and central chirality. Do not generate an enantiomer from a connectivity-only disconnected ferrocene SMILES.
4. If a family name lacks an enantiomer descriptor, record chirality as unresolved instead of selecting the prototype's hand.

## Geometry and format handling

- Use the catalog template for the invariant core, then place variable branches into free exterior angular sectors without distorting regular 3-6-member rings.
- PubChem-derived cached 2D coordinates are used for selected dense P,P prototypes where unconstrained RDKit layout tends to fold aryl groups into the donor pocket.
- Ordinary MOL cannot encode eta-5 Cp/indenyl/ferrocene bonding. Use native ChemDraw hapticity/coordination objects for the final complex.
- A free bpy/terpy ligand may be shown in a familiar extended conformation; a coordinated complex must orient all donor atoms toward the actual metal center shown in the source.

## Selection evidence

There is no universal frequency-ranked list of exactly 50 ligand skeletons. Selection therefore combines breadth in the Kraken monodentate-P database (DOI `10.1021/jacs.1c09718`), the P,P/P,N Ligand Knowledge Base (DOI `10.1021/om700840h`), recurring families in *Privileged Chiral Ligands and Catalysts* (DOI `10.1002/9783527635207`), and family reviews for oxazolines, salen, polypyridyls, carbenes, pincers, and planar-chiral ferrocenes. Treat this as a high-frequency working vocabulary, not a numerical popularity ranking.
