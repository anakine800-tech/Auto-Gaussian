# Gaussian input policy

This reference is loaded when the user needs help selecting or reviewing a Gaussian input rather than merely converting a structure.

## Route card

The skill should preserve the user's method, basis, job type, solvent model, dispersion, SCF settings, and any special keywords. A route card is user intent, not a universal default.

Examples of syntax only:

```text
#p b3lyp/6-31g(d) opt
#p wb97xd/def2svp opt freq
#p m062x/def2tzvp scrf=(smd,solvent=acetonitrile) opt
```

Do not silently add `freq`, `td`, `irc`, `opt=ts`, unrestricted keywords, or an ECP. For transition metals, ask for a basis/ECP and spin state. For a solvent calculation, ask for the solvent and whether the user wants implicit SMD/PCM or an explicit solvent cluster.

## Charge and multiplicity

The Gaussian charge/multiplicity line is mandatory. The formal charge inferred from the structure is a useful check, not permission to override the user's intended protonation or salt form.

- Closed-shell neutral or ionic organic structures commonly use multiplicity 1.
- A radical requires an explicit multiplicity.
- Open-shell transition-metal systems require an explicit spin state and often a carefully selected unrestricted method.
- If a structure is a mixture of disconnected ions, confirm whether to calculate the full ion pair or separate components.

## Geometry provenance

ChemDraw coordinates are normally 2D and should not be treated as a physically meaningful starting geometry. The bundled converter creates a reproducible RDKit ETKDGv3 conformer, keeps stereochemical constraints, and attempts MMFF94s or UFF. This is suitable as a starting point for common main-group organics, not as a guarantee of the global minimum.

For flexible molecules, consider generating and comparing multiple conformers. For transition states, reaction paths, organometallics, and unusual valence states, request or construct a chemically reviewed 3D geometry and protocol.

## VM resource constraint

The configured Gaussian 09 Windows installation is known to report a 32-bit memory ceiling. Prefer `%mem=1200MB` and `%nprocshared=3` for this VM unless a verified 64-bit installation is being used. A high memory directive can be accepted and then fail early in Link 1.

## Completion checks

The result is successful only when the log contains `Normal termination`. A visible GaussView window is not a completion signal. Preserve the `.gjf`, `.log`, `.chk`, manifest, and any preview together under one project folder.
