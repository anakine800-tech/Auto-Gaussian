---
name: auto-g16-structures
description: Read ChemDraw or SMILES structures, review identity and stereochemistry, run local RDKit force-field prescreening, and prepare Cartesian Gaussian inputs within a study.
---

# Structure preparation

Use when a new structure enters a study, local force-field prescreening is needed,
or a reviewed single-frame XYZ needs conversion to Gaussian input. Run the
scripts with `conda run -n chem python`; they use sibling modules and need no
runtime configuration or installed legacy Skill. RDKit with ChemDraw CDX support
is required for CDX/CDXML inputs.

Read `study.md` and `references/chemistry-boundaries.md`. Multiplicity must come
from the researcher or `study.md`, never be inferred from a structure. This first
version handles connected, closed-shell main-group organic molecules. Stop and
ask the researcher about radicals, metals, coordination systems, disconnected
complexes, or unclear protonation/tautomer/stereochemistry. Unassigned tetrahedral
centers and conflicting/unsupported ChemDraw CFG stop the scripts. Do not remove
stereo annotations or change the source drawing to make an error disappear.

## Workflow

1. Read the source directly with `scripts/prepare_preview.py SOURCE --study STUDY
   --name structure-review --multiplicity MULT`. ChemDraw, MOL, SDF and SMILES
   are accepted. `inspect_chemdraw.py` offers the same study/name/multiplicity
   options for ChemDraw-specific review artifacts.
2. Present `summary.json` and `preview.png`: canonical isomeric SMILES, formula,
   source atom count, explicit-H atom count, charge, supplied multiplicity, CIP
   centers, import diagnostics and warnings. Atom indices are zero-based. Source
   atom count may differ from the Cartesian count because implicit H are expanded.
   If MOL/SDF roundtrip loses stereo, retain the original source or `stereo.smi`.
3. **Ask the researcher to confirm the structure (milestone 1).** Record their
   confirmation in `study.md` before screening. A successful script is not a
   human signature. Do not invent a signature from a test run.
4. Follow `references/conformer-workflow.md`: TS families, key intermediates and
   complexes require two sampling routes; flexible molecules are also recommended.
   Use CREST + ETKDG for supported minima, CREST + hypothesis-directed constrained
   CREST for TS/complexes. Construct and review the proposed interaction/attack
   direction before constrained CREST and label that route `directed`; do not feed
   disconnected complexes/TS into the connected-only force-field script. The
   coverage report cannot prove completeness. For supported minima run
   `scripts/prepare_conformers.py generate SOURCE --study STUDY --name ff-screen
   --multiplicity MULT`. Inspect warnings and force-field convergence. Keep the
   original source for ChemDraw so explicit-H wedge information survives.
5. Hand `structures/ff-screen/conformers.xyz` and `summary.json` to `ag dedup`
   (consult `ag dedup --help` for its installed interface). XYZ comment lines
   begin with absolute force-field energy followed by the force field and
   `kcal/mol`; these are **not Hartree, DFT energies or Gibbs energies**. Keep
   this unit explicit when using dedup/cluster. Review the representative set
   with the study Skill before DFT work.
6. To draft a Gaussian input from one reviewed XYZ frame, use:

   ```sh
   conda run -n chem python scripts/make_gaussian_input.py FRAME.xyz \
     --study STUDY --name opt-input --route 'METHOD/BASIS opt freq' \
     --charge CHARGE --multiplicity MULT --nprocshared CORES \
     --mem MEMORY --chk structure.chk
   ```

   Supply the literature-based route or explicitly declared fallback, reviewed
   charge and multiplicity, and resource values appropriate for `ag prepare`.
   XYZ has no bonds: verify its atom order and identity against the confirmed
   structure; the converter cannot determine radicals or stereochemistry from
   XYZ. Multiple frames are rejected to prevent silently choosing one conformer.
   The helper also retains direct structure-to-3D conversion for reviewed source
   inputs. Audit the GJF with `scripts/audit_cartesian_input.py INPUT.gjf`, then
   pass the GJF to `ag prepare`. No script submits or starts Gaussian.

Every writer uses a fresh `STUDY/structures/NAME/` directory and refuses an
existing name, including a partially written run. Choose a new descriptive name
for a rerun. Read-only `audit_cartesian_input.py` needs no `--study` option.

Optional GaussView inspection can still use the frozen
`skills/auto-g16-view-rt-win/scripts/windows_gaussview.py` and
`gaussview_load_probe.ps1` manually when requested. They are not imported or
invoked by this Skill. `runtime_config.py` is omitted: no retained operation
needs its machine paths or remote settings.

## Migration and validation

Source files are credited in each script header; applicable chemistry notes
were adapted in `references/`. The CDX loader and Cartesian auditor retain their
chemical behavior. Conformer embedding, minimization, energy ranking and RMSD
filtering retain the original algorithm; output is now a multi-frame XYZ and
summary instead of individual GJF drafts and selection artifacts.

Run `conda run -n chem python -m pytest skills-next/auto-g16-structures/tests` from
the repository root. CDX tests skip only when RDKit lacks CDX support; they must
pass locally. Fixtures are synthetic butane and explicit-H chiral 2-butanol;
the previously suggested reaction-scheme fixture contains no molecular graph.
