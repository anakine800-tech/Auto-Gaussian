---
name: chemdraw-gaussian-pipeline
description: Convert ChemDraw CDX/CDXML/MOL/SDF structures or SMILES into reviewed Cartesian-coordinate Gaussian 09 inputs, open preview geometries in GaussView, optionally run them in the configured Windows Gaussian VM, and preserve machine-readable manifests. Use when the user wants ChemDraw-to-Gaussian conversion or GaussView inspection; do not silently guess ambiguous connectivity, stereochemistry, charge, multiplicity, or metal-complex protocols.
---

# ChemDraw to Gaussian

## Purpose

Orchestrate the handoff from a user-approved chemical structure to a reproducible Gaussian 09 job. Use the existing `chemdraw-structures` workflow to normalize images/names/ligands into a chemically explicit structure, use the bundled converter for deterministic 3D coordinates and Gaussian syntax, and use `gaussian-parallels-vm` for VM execution and GaussView inspection.

This skill is an orchestrator, not a replacement for chemical judgment. A structure must be resolved and confirmed before a calculation is launched.

## Runtime prerequisites

- Use an RDKit environment; the configured default is `/Users/sundeli/miniforge3/envs/chem/bin/python`.
- For direct `.cdx/.cdxml` parsing, require `Chem.HasChemDrawCDXSupport()`. If unavailable, ask for a ChemDraw-exported MOL/SDF instead of attempting to decode the binary format manually.
- For Windows execution or GaussView opening, require the `gaussian-parallels-vm` Skill and its configured VM credentials. The bundled scripts do not store credentials.

## Operating modes

Choose the mode from the user's wording:

- **GaussView preview mode**: phrases such as “转换成笛卡尔坐标”, “在 Gaussian View 打开”, or “只测试流程”. Parse and inspect the structure, generate a Cartesian `.gjf`, copy it to the VM, and call `open-gview`. Do not call `run` and do not start Gaussian.
- **Gaussian calculation mode**: only when the user explicitly asks to calculate/submit/run Gaussian. Require a reviewed preflight summary and resolved stereochemistry, charge, multiplicity, and protocol before calling `run`.

Passing `--allow-ambiguous-stereo` is permitted only for preview mode. It creates a clearly warned geometry for visual inspection; it never authorizes a scientific calculation.

## Supported entry points

- ChemDraw-exported `.cdx`, `.cdxml`, `.mol`, or `.sdf` files: preferred input for direct conversion when the local RDKit build supports ChemDraw parsing.
- SMILES: accepted directly by the converter or first normalized through the structure skill.
- Screenshots, scanned drawings, and compound names: first use `chemdraw-structures` to create a MOL/SDF plus PNG preview; then continue from the approved MOL/SDF. For `.cdx/.cdxml`, parse directly when supported, but still inspect the imported structure and stereochemistry.
- Existing Gaussian `.gjf/.com`: inspect and validate rather than regenerating coordinates unless the user asks for a new geometry.

Do not treat a PNG preview as a calculation-ready structure. Do not parse CDXML by guessing its XML semantics when a ChemDraw MOL/SDF export is available.

## Required workflow

### 1. Normalize and identify the structure

Use the supplied structure file as the source of truth. For `.cdx/.cdxml`, use `scripts/inspect_chemdraw.py` when the RDKit build reports ChemDraw support. The shared importer reads with `removeHs=False`, restores supported ChemDraw `_MolFileBondCfg` wedge/dash directions, then assigns tetrahedral tags and CIP labels. It writes MOL/SDF review copies, a stereochemical SMILES, a preview PNG, and a manifest. For images, names, or ligand descriptions, invoke `chemdraw-structures` and obtain a structure file and preview first.

Never diagnose a CDX tetrahedral center from the default `removeHs=True` import. An explicit wedge hydrogen may be the only stereochemical carrier. Convert calculations directly from the corrected in-memory CDX molecule. If the manifest says MOL/SDF round-trip stereochemistry changed, treat those files as review-only and use the source CDX/CDXML or emitted `*_stereo.smi` instead.

The CDX/CDXML import may emit parser warnings such as conflicting wedge directions. Preserve those warnings in the user-facing summary. Do not silently repair or reinterpret a conflicting wedge.

Record or derive:

- canonical isomeric SMILES;
- formula and molecular weight;
- atom connectivity, aromaticity, formal charges, and disconnected components;
- specified stereochemistry, including CIP centers and any axial/atropisomeric limitation;
- total charge and spin multiplicity;
- source file and any assumptions.

If any of the following is unresolved, stop and ask the user to confirm before creating a runnable job: regioisomer/tautomer, salt or solvate, protonation, stereochemistry, total charge, multiplicity, coordination mode, or whether a metal complex should be treated with a special basis/ECP.

For ordinary closed-shell organic molecules, a default singlet is reasonable only when the structure contains no radical electrons and the user has not indicated an open-shell state. For radicals, transition metals, excited states, broken-symmetry systems, or complexes, require an explicit multiplicity and a user-specified protocol.

### 2. Show a preflight summary

Before running Gaussian, show the user a concise summary similar to:

```text
Structure: example.mol
SMILES:   <canonical isomeric SMILES>
Formula:  C...H...N...
Charge/multiplicity: 0 1
Stereochemistry: (1:R), (7:S); axial chirality unspecified
Geometry: RDKit ETKDGv3 + MMFF94s, explicit H retained
Route:    #p b3lyp/6-31g(d) opt
Resources: %mem=1200MB, %nprocshared=3
```

Ask for confirmation when the user has not already provided the route, charge, multiplicity, solvent, or job type. It is acceptable to prepare the input for review without confirmation; do not launch the job without confirmation of the summary.

### 3. Generate the Gaussian input

Run the bundled deterministic converter:

```bash
/Users/sundeli/miniforge3/envs/chem/bin/python \
  /path/to/chemdraw-gaussian-pipeline/scripts/make_gaussian_input.py \
  /path/to/structure.cdx \
  --output /path/to/outputs/example.gjf \
  --route "#p b3lyp/6-31g(d) opt" \
  --charge 0 --multiplicity 1 \
  --mem 1200MB --nproc 3
```

The converter accepts `.cdx`, `.cdxml`, `.mol`, `.sdf`, or a SMILES string. It adds hydrogens, generates a 3D conformer with RDKit ETKDGv3 while enforcing tetrahedral stereochemistry, uses MMFF94s or UFF when parameters are available, and writes:

- a Gaussian `.gjf` input;
- a same-stem `.xyz` Cartesian-coordinate file;
- a same-stem `.json` manifest containing identity, geometry provenance, and route settings.

Use a user-approved route card. If no method/basis has been chosen, ask; do not imply that B3LYP/6-31G(d) is universally appropriate. For a basic organic geometry optimization, `#p b3lyp/6-31g(d) opt` is a usable example, not a scientific recommendation.

Use `%mem=1200MB` and `%nprocshared=3` for the known 32-bit Gaussian 09 VM unless the user has explicitly confirmed a different installation. The installed VM may accept `%mem=7GB` syntactically but fail in Link 1 because it reports a 32-bit memory ceiling.

Keep at least one blank line after the charge/multiplicity line and after the final coordinate. Malformed termination can produce `End of file in ZSymb`.

### 4. GaussView preview mode

For a structure-only preview, use the normalized review artifacts and `.gjf`; do not run Gaussian:

```bash
/Users/sundeli/miniforge3/envs/chem/bin/python \
  /path/to/chemdraw-gaussian-pipeline/scripts/inspect_chemdraw.py \
  /path/to/AAtest.cdx /path/to/outputs/AAtest

/Users/sundeli/miniforge3/envs/chem/bin/python \
  /path/to/chemdraw-gaussian-pipeline/scripts/make_gaussian_input.py \
  /path/to/AAtest.cdx \
  --output /path/to/outputs/AAtest/AAtest_cartesian.gjf \
  --charge 0 --multiplicity 1 \
  --allow-ambiguous-stereo

python3 /Users/sundeli/.codex/skills/gaussian-parallels-vm/scripts/gaussian_vm.py \
  copy-to-vm /path/to/outputs/AAtest/AAtest_cartesian.gjf \
  'C:\Users\sundeli\Desktop\GaussianProjects\AAtest_cartesian\AAtest_cartesian.gjf'

python3 /Users/sundeli/.codex/skills/gaussian-parallels-vm/scripts/gaussian_vm.py \
  open-gview --kill-existing \
  'C:\Users\sundeli\Desktop\GaussianProjects\AAtest_cartesian\AAtest_cartesian.gjf'
```

Report the local `.gjf` link, the Windows path, the formula/atom count, and all stereochemistry warnings. A Gaussian input opened this way contains Cartesian coordinates after the charge/multiplicity line; it is not evidence that Gaussian has run.

### 5. Validate before submission or calculation

Check the JSON manifest and input text. At minimum verify:

- atom count and formula are consistent with the intended structure;
- charge and multiplicity are explicit;
- the route contains the requested job type;
- the checkpoint filename is local to the job folder;
- no unresolved `?` stereocenter remains unless the user explicitly accepted unspecified stereochemistry;
- special elements, disconnected salts, or force-field failures are surfaced as warnings;
- the input ends with a blank line.

In preview mode, unresolved stereo may remain only when explicitly marked in the manifest. In calculation mode, unresolved `?` centers, wedge conflicts, or uncertain protonation must stop the workflow and be resolved first.

Run the Cartesian audit after conversion, before copying any complex input to the VM:

```bash
/Users/sundeli/miniforge3/envs/chem/bin/python \
  /path/to/chemdraw-gaussian-pipeline/scripts/audit_cartesian_input.py \
  /path/to/outputs/example.gjf
```

The audit verifies parsing, finite coordinates, element counts, a configurable closest-pair threshold, charge/multiplicity, and the required trailing blank line. It does not validate a force field, conformer energy, or the scientific suitability of the route card.

For stereogenic or atropisomeric molecules, retain the ChemDraw preview and manifest next to the input so the user can compare the intended drawing with the computational geometry. A simple SMILES may not encode axial chirality for BINOL/BINAP/SPINOL-derived structures.

### 6. Run in the Windows Gaussian VM when requested

Use the existing Gaussian VM skill and its bundled script. The local `.gjf` should be the reviewed artifact:

```bash
python3 /Users/sundeli/.codex/skills/gaussian-parallels-vm/scripts/gaussian_vm.py status
python3 /Users/sundeli/.codex/skills/gaussian-parallels-vm/scripts/gaussian_vm.py \
  run /path/to/outputs/example.gjf --project-name example --wait
```

For long jobs, omit `--wait`, report the Windows project path and the local input/manifest, and later use `tail-log` and `finished`. Do not launch a second copy merely because the first job is still running.

Treat `Normal termination` near the end of the log as success. For `Error termination`, inspect the final 80–120 lines and report the cause before retrying. If Link 1 fails with a memory ceiling, reduce `%mem` to a known safe value; if it reports `End of file in ZSymb`, repair the input terminator and rerun only after checking that no other changes are needed.

### 7. Open and inspect the result

After a successful run, open the Windows-side `.log` or `.chk` with:

```bash
python3 /Users/sundeli/.codex/skills/gaussian-parallels-vm/scripts/gaussian_vm.py \
  open-gview 'C:\Users\sundeli\Desktop\GaussianProjects\example\example.log'
```

If GaussView is not visible, use `--kill-existing`, confirm that the visible Windows session is logged in, and check that the path exists before relaunching. Report whether the calculation terminated normally, not merely that GaussView opened.

## Geometry and chemistry boundaries

The automatic 3D generation is intended for common main-group organic molecules. It is not a validated protocol for:

- transition-metal or lanthanide complexes;
- organometallic hapticity or coordination geometries;
- salts where ion pairing matters;
- multiple conformers, transition states, IRCs, excited states, or nonadiabatic calculations;
- unrestricted, broken-symmetry, or multireference systems;
- structures whose axial chirality is not encoded in the input.

For these cases, preserve the user-provided coordinates when reliable, request an explicit protocol, or stop with a targeted question. Do not silently choose an ECP, spin state, or coordination geometry.

## Future remote-server extension

Keep local generation and execution separate. A future server adapter should consume the same `.gjf` and `.json` manifest and implement only `submit`, `status`, `fetch`, and `cancel`, with an explicit scheduler/account/partition and no credentials in the Skill. See [references/remote-server-contract.md](references/remote-server-contract.md). The VM workflow remains the default until a server adapter is configured.

## Bundled resources

- `scripts/make_gaussian_input.py`: deterministic CDX/CDXML/MOL/SDF/SMILES to Gaussian input and manifest conversion.
- `scripts/inspect_chemdraw.py`: normalize one CDX/CDXML file into MOL/SDF, a preview, and a stereochemistry manifest.
- `scripts/cdx_stereo.py`: preserve explicit-H ChemDraw wedge stereochemistry and audit MOL-block round trips.
- `scripts/audit_cartesian_input.py`: validate Gaussian/XYZ Cartesian coordinates before preview or submission.
- `references/gaussian-input-policy.md`: route-card, charge/multiplicity, geometry, and special-case guidance.
- `references/remote-server-contract.md`: minimal interface for adding SSH/Slurm or another compute backend later.
