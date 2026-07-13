---
name: gaussian-view-rt-win
description: Convert ChemDraw CDX/CDXML/MOL/SDF or SMILES structures into chemically reviewed Cartesian Gaussian inputs, generate and rank stereochemistry-preserving conformer ensembles, promote only explicitly reviewed conformers, transfer audited inputs to the physical Windows 11 PC, and open them in visible GaussView without running Gaussian. Use for structure and conformer preparation, chiral review, and RTwin GaussView inspection.
---

# Gaussian View RT win

Run one integrated preview workflow. Do not invoke the older component Skills unless this Skill reports a missing dependency or an unsupported chemistry case.

## Fixed environment

- RDKit Python: `/Users/sundeli/miniforge3/envs/chem/bin/python`
- Windows SSH: `10261@100.76.152.81`
- SSH control socket: `/tmp/codex-windows-gaussview.sock`
- Windows project root: `C:\Users\10261\Desktop\GaussianProjects`
- GaussView: `D:\gs\g16\G16W\gview.exe`
- Local outputs: current workspace `outputs/<project>/`

Never store or echo a password. Windows Hello PIN is not an SSH password.

## Fast accurate workflow

1. Identify the source. Accept `.cdx`, `.cdxml`, `.mol`, `.sdf`, or an unambiguous SMILES. For screenshots, names, uncertain tautomers, salts, protonation, stereochemistry, metal complexes, or disconnected components, resolve the chemistry before conversion.
2. Run `scripts/prepare_preview.py`. It imports CDX/CDXML with explicit hydrogens retained, restores supported ChemDraw CFG wedge/dash directions, converts directly from that source without a lossy MOL/SDF intermediate, generates Cartesian coordinates, writes `.gjf/.xyz/.json`, audits coordinates and termination, computes SHA-256, and emits one consolidated report.
3. Inspect the generated 2D preview for CDX/CDXML inputs and read every warning. Stop on an unassigned tetrahedral center unless the user explicitly requests a preview with unresolved stereo. Never use preview acceptance as calculation approval.
4. Show a concise preflight: source, canonical isomeric SMILES, formula, charge/multiplicity, stereochemistry, geometry method, route, atom count, warnings.
5. Reuse one SSH master connection for all remote operations. If absent, run `scripts/windows_gaussview.py master`; let the user type the Windows account password once in Terminal.
6. Run `scripts/windows_gaussview.py open <structure> --project <name>` for `.gjf`, `.com`, `.mol`, `.sdf`, or visualization-only `.xyz` sources. For XYZ, preserve the source and derive a hash-bound V2000 MOL plus `gaussview-visual-preview/1` manifest; the MOL is explicitly non-runnable and its single-bond topology is a reviewed visualization aid. Transfer and hash-check the source, preview, and manifest.
7. Require the Windows load probe to find the exact project/file in GaussView's visible window tree and no error dialog. Treat process-only evidence as insufficient; never report success on `Unknown file type`, `CFileAction::LoadFile`, or a document-window timeout.
8. Report local and Windows source/preview paths and hashes. State explicitly that opening a preview is not a Gaussian calculation.

## Commands

Prepare a preview:

```bash
/Users/sundeli/miniforge3/envs/chem/bin/python \
  ~/.codex/skills/gaussian-view-rt-win/scripts/prepare_preview.py \
  /path/to/structure.cdx --output-dir /path/to/outputs/project
```

Pass `--charge` or `--multiplicity` when known. For a visual-only review of unresolved tetrahedral stereo, pass `--allow-ambiguous-stereo` and preserve the warning.

Open/reuse the SSH master:

```bash
/Users/sundeli/miniforge3/envs/chem/bin/python \
  ~/.codex/skills/gaussian-view-rt-win/scripts/windows_gaussview.py master
```

Transfer, verify, and open:

```bash
/Users/sundeli/miniforge3/envs/chem/bin/python \
  ~/.codex/skills/gaussian-view-rt-win/scripts/windows_gaussview.py \
  open /path/to/project_cartesian.gjf --project project
```

Open TS imaginary-mode displacement artifacts. The wrapper keeps each XYZ immutable and creates an audited, non-Gaussian MOL preview automatically:

```bash
python3 ~/.codex/skills/gaussian-view-rt-win/scripts/windows_gaussview.py \
  open /path/to/mode_plus.xyz --project ts_mode_plus
```

## Accuracy gates

- Preserve connectivity, formal charge, explicit stereochemistry, and component count from the reviewed source.
- Require finite Cartesian coordinates, atom/formula consistency, closest-pair distance at least `0.4 Å`, explicit charge/multiplicity, and a trailing blank line.
- Treat axial/atropisomeric chirality as unresolved unless the source encodes it reliably and the preview confirms it.
- Stop for radicals without explicit multiplicity and for transition-metal, lanthanide, coordination, ECP, broken-symmetry, excited-state, transition-state, or multireference cases without a user-specified protocol.
- Compare SHA-256 after transfer; never open a mismatched remote file.
- For an XYZ handoff, reject malformed atom counts, non-finite coordinates, contacts below `0.4 Å`, unsupported elements, and distance-inferred connectivities exceeding the audited neighbor limits. Record that inferred bond orders are visualization-only.
- Require `file_loaded: true` from the UI probe. Starting `gview.exe` alone is not successful loading.
- Never run Gaussian unless the user makes a separate explicit calculation request and approves method, basis, job type, charge, multiplicity, and resource settings.

## Proven compatibility notes

- Before calling a CDX center unassigned, require the explicit-H import and ChemDraw CFG restoration performed by the shared pipeline. Default RDKit import can delete a wedged explicit H and falsely report `?` at that carbon.
- Treat any center still marked `?`, any conflicting CFG direction, or any unsupported CFG value after corrected import as a real review gate.
- Treat a reported MOL/SDF stereo round-trip mismatch as an artifact-format warning: keep those files for review only and convert from the original CDX/CDXML or emitted stereochemical SMILES.
- Permit `--allow-ambiguous-stereo` only when the user explicitly requests visual preview. Keep the warning in the report and state that the geometry is not calculation-ready.
- Expect UFF fallback for structures containing boron when MMFF94s lacks parameters. Report the fallback; do not present it as a validated conformer protocol.
- Decode localized Windows SSH output defensively. Chinese `schtasks` output may use OEM/GBK bytes rather than UTF-8; preserve ASCII control tokens and avoid locale-dependent crashes.
- Require GaussView to appear as `gview.exe` in the `Console` session. A process in `Services` session 0 is not a visible launch.
- GaussView 6.0.16 on this RTwin rejects raw XYZ command-line loading with `CFileAction::LoadFile(). Unknown file type`. Never pass raw XYZ to GaussView; use the audited MOL derivative and retain the XYZ hash as provenance.

## Speed rules

- Use the wrapper scripts rather than separate inspection, conversion, audit, hash, copy, and launch calls.
- Reuse the SSH control socket for up to 15 minutes, so the user enters one password and remote commands avoid repeated handshakes.
- Skip ChemDraw normalization only for already reviewed MOL/SDF inputs; never skip Cartesian audit or hash verification.
- Reuse an existing reviewed manifest only when its source SHA-256 still matches.

Read [references/chemistry-boundaries.md](references/chemistry-boundaries.md) only for ambiguous or advanced structures.

## Conformer workflow

Generate multiple candidates only when the chemical identity, tetrahedral stereochemistry, charge, multiplicity, Opt route, and resource tier are resolved:

```bash
CHEM_PY=/Users/sundeli/miniforge3/envs/chem/bin/python
CONF="$HOME/.codex/skills/gaussian-view-rt-win/scripts/prepare_conformers.py"

"$CHEM_PY" "$CONF" generate /path/to/structure.cdx \
  --output-dir /path/to/conformers --project example \
  --route '#p <approved-method/basis> opt' \
  --resource-tier general --num-conformers 50 \
  --energy-window 6 --rmsd-threshold 0.5
```

Use ETKDGv3 with chirality enforcement, MMFF94s when fully parameterized, otherwise UFF, then filter by force-field energy and RMSD. Preserve the ensemble SDF, candidate GJF/XYZ/JSON files, rankings, and warnings. Treat every generated input as `candidate_only`; the PBS Skill must refuse it.

Open candidates in GaussView when 3D inspection matters. After explicit review, promote exactly one candidate at a time:

```bash
"$CHEM_PY" "$CONF" select example_conformers.json \
  --rank 1 --output-dir /path/to/selected --confirmed
```

Selection is not evidence that rank 1 is the only relevant conformer. Retain all candidates within the approved energy window, calculate them with the same Opt-Freq-single-point protocol, and use Gaussian Gibbs energies for Boltzmann populations. Read [references/conformer-workflow.md](references/conformer-workflow.md) before generating or selecting an ensemble.

## Bundled scripts

- `scripts/prepare_preview.py`: create and audit one preview input.
- `scripts/prepare_conformers.py`: generate, rank, review-gate, and select conformer candidates.
- `scripts/windows_gaussview.py`: derive audited non-runnable previews when needed, transfer with SHA-256 verification, open visible GaussView, and require document-level load evidence.
- `scripts/gaussview_load_probe.ps1`: detect the exact loaded document or a visible GaussView error dialog.
