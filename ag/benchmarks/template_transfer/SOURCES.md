# Inputs, provenance and limits

Status (2026-10-29): the owner deferred T191 until after V4.8. The prototype
and all source, mapping and failure evidence are retained in this branch and
Draft PR #379. Algorithm research for this release has ended; this work is
excluded from V4.8 capabilities and acceptance. No further algorithm trials or
real TS calculations are authorized. Offline tests passing do not establish
successful TS transfer. No merge, deployment or deletion is part of this closeout.

This directory contains original T191 code and independently transcribed mapped
SMILES for four pairs plus one attributed public small-molecule TS coordinate
transcription. It contains no Gaussian logs, checkpoints, copied upstream code,
or unpublished/private research-study data.

- Maryasin, B.; Maulide, N. *On the Stability of Disubstituted Cyclobutenes – A
  Computational Study*. Eur. J. Org. Chem. 2019, 338–341.
  DOI: https://doi.org/10.1002/ejoc.201801243.
  Primary article: https://chemistry-europe.onlinelibrary.wiley.com/doi/10.1002/ejoc.201801243.
  Scheme 3 identifies B–F; Scheme 4/Table 1 identify the trans/outward E,E route;
  Computational Details reports frequency classification, without the complete
  bidirectional IRC evidence required here. Article is CC BY; the
  [PMC article](https://pmc.ncbi.nlm.nih.gov/articles/PMC6472590/) identifies version 4.0.
  SI `ejoc201801243-sup-0001-SupMat.pdf` was unavailable from Wiley (HTTP 403),
  but was obtained from the legitimate public
  [BioStudies mirror](https://www.ebi.ac.uk/biostudies/files/S-EPMC6472590/EJOC-2019-338-s001.pdf)
  on 2026-10-29. Official API metadata agrees with the 383353-byte file.
  SHA-256: `e3655680791f915c7e57466569f5d07f976880b0ab1fc8b0f264c61285ea45da`.
  The Europe PMC article XML explicitly specifies CC BY 4.0 and lists this PDF
  as attached media; the entire SI has no contrary license notice. We checked
  the file, not just the article's open-access label.
- `B_TS_trans_1.xyz` transcribes the 15 coordinate rows on printed S17 (PDF page
  18) with unchanged order and decimal precision. Only XYZ header/comment are
  added. Attribution: Boris Maryasin and Nuno Maulide, the paper above.
  `B_TS_trans_1.source.json` records file hashes, original label/page, attribution
  and our explicit row permutation. The full PDF is not redistributed.
  B reactant coordinates span S16–S17; its E,E product is also on S17.
  These are published coordinates, **not a scientifically validated template**:
  no complete frequency-mode or bidirectional IRC evidence is provided.
  Main text SMD(THF) conflicts with the SI S1/S13 DCM heading. No full Gaussian
  input resolves the conflict; no solvent or damping choice is silently made.
- `pairs.json` is our transcription, with our mapping and choice of one trans
  enantiomer. It is not an author-supplied file or the author's atom numbering.
  The product graphs preserve mapped element identities and specify E,E.
- Synthetic test geometries are produced at test time from the ordinary B
  **reactant** using RDKit ETKDGv3, seed 191. They are not TS geometries and carry
  no energy, frequency or IRC claim. No synthetic geometry is mislabeled as
  published data. All generated files remain in temporary test directories.
- RDKit API references (consulted 2026-10-29):
  https://www.rdkit.org/docs/source/rdkit.Chem.rdDistGeom.html and
  https://www.rdkit.org/docs/GettingStartedInPython.html#constrained-embedding.
  We call installed RDKit APIs; no RDKit/autodE implementation is copied or
  vendored. No dependency changes are introduced.
- xTB's [xcontrol documentation](https://xtb-docs.readthedocs.io/en/latest/xcontrol.html)
  specifies one-based atom rows, distance targets in angstrom and force constants
  in Eh/Bohr². Existing `ag.crest_input.validate` and `ag.catalog_v2.xyz` validate
  outputs. The force constant is mandatory; 0.5 in tests is a syntax fixture,
  not a recommended scientific setting.

## Local experiment API

There is no installed CLI or automatic registry integration. Load `prototype.py`
from this directory and call `generate` for exactly `B-C`, `B-D`, `B-E`, or `B-F`.
Provide a B template XYZ and a separate explicit description:

```python
from prototype import generate

report = generate(
    "B-C", template_xyz=template_xyz, output_dir=new_directory,
    force_constant=reviewed_force_constant,
    description={
        "template_id": "B-trans-outward",
        "reactant": fixed_B_mapped_smiles,
        "sha256": verified_template_sha256,
        "row_by_atom": reviewed_complete_row_permutation,
        "source": {
            "doi": "10.1002/ejoc.201801243",
            "location": verified_file_and_coordinate_pages,
            "status": "unvalidated-source-geometry",
        },
    },
)
```

`row_by_atom` maps every atom in `molecule(fixed_B_mapped_smiles)` (including
RDKit-added H) to a one-based row in the supplied XYZ. A complete element-matched
permutation is mandatory. Same-element swaps require human checking; this code
cannot prove chemical correspondence from XYZ. For synthetic tests use the
explicit `synthetic-test-only` source status; neither status means validated.
The public B TS and its mapping are included, so this API can be exercised
locally. With the tested RDKit version all four targets currently refuse that
seed: the real benchmark is not ready to run.

The target is its ordinary reactant graph. Mapped atoms 1–7 (four ring atoms and
COOH) receive the template coordinates and pair distances. ETKDGv3 embeds the
remaining substituent/H atoms using that graph, explicit core coordinates and
adjusted core distance bounds. It does not infer bonds from the TS or introduce
half bonds, run a force field/quantum preoptimization or retry with alternative
seeds. RDKit's internal distance-geometry iteration is not a QM optimization.
Output drift beyond 0.02 angstrom, failed embedding, planar/incorrect reactant
handedness and obvious collisions refuse output. Nonbonded distances below
0.65 times the covalent-radius sum (or any distance below 0.4 angstrom) are
conservative collision screens, not a vdW/contact or TS-quality criterion.

The prototype may refuse valid late TS geometries whose core bounds conflict
with the reactant graph, or whose reactive stereocentres are nearly planar.
The public B seed currently triggers this refusal for all four targets. Two
offline diagnostic alternatives did not satisfy all constraints, so neither
was adopted. The owner has now deferred this work until after V4.8; algorithm
research for the current release is ended and the failure evidence is retained. This is not permission to relax checks or change the reaction. It cannot certify outward rotation, diene geometry or
frequency direction. Those require the full scientific protocol.

A successful call exclusively creates a new directory with `guess.xyz`,
`constraints.inp` (all 21 core pair distances), and `transform.json` (source,
input/output hashes, exact atom rows, seed, version and limitations). Existing
or symbolic-link paths are refused. A partial filesystem failure leaves the
new directory occupied; use a new name. No study, catalog or Attempt is written.

For the verified **existing** candidate/prepare interfaces see
`ag/tests/test_template_transfer_benchmark.py::test_local_catalog_and_xtb_prepare_only`.
That test creates a disposable synthetic study, registers via `catalog.change`
with `origin='template-transform'`, then calls `attempt.prepare(template='xtb',
constraints=..., params={'--gfn':'2','--opt':'tight','--chrg':'0','--uhf':'0'}, ...)`.
It rejects construction of `SSHTransport` and asserts no submit claim or
submission record. No real configuration is read. Do not copy the synthetic
DOI association as evidence of source geometry. CREST prepare may probe a
configured executable remotely; this local interface test deliberately uses xTB.

The full sample, denominator, cost and stop rules are in
[the benchmark protocol](../../../docs/benchmarks/template-transfer.md).
