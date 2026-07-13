# Protocol selection

## Built-in protocols

### smoke-test

- Route: `#p b3lyp/sto-3g opt`
- Resources: 4 cores, 2 GB
- Purpose: verify conversion, transfer, PBS, G16, monitoring, fetch, and analysis with a very small molecule
- Boundary: workflow testing only; do not use its energy or geometry as a research-quality recommendation

### organic-opt

- Route: `#p b3lyp/6-31g(d) opt`
- Default resources: general tier, 22 cores and 50 GB
- Purpose: previously approved example for an ordinary closed-shell organic geometry optimization
- Boundary: still require user approval; it is not universal for ions, radicals, excited states, metals, transition states, solvation, conformer populations, or high-accuracy thermochemistry

## Resource tiers

- `simple`: 8 cores and 12 GB. Use for small, straightforward structures and inexpensive calculations.
- `general`: 22 cores and 50 GB. Use for ordinary calculations and whenever complexity is not clearly at either extreme.
- `complex`: 44 cores and 120 GB. Use for very complex structures or clearly expensive calculations.

Keep the smoke-test exception at 4 cores and 2 GB. Treat the resource tier independently from method/basis selection: a larger tier does not make an unsuitable chemical protocol valid. Show the selected tier, exact `%mem`, and `%nprocshared` before submission. For an existing `.gjf` or `.com`, do not silently rewrite resources; verify that its Link 0 values match the selected tier or stop for review.

## Approval rules

Require explicit method, basis, job type, charge, multiplicity, cores, and memory before submission. Treat a command containing `--confirmed` as valid only when those exact values were shown or supplied by the user.

Do not automatically add `Freq` after `Opt`. Do not automatically retry with `SCF=XQC`, `Opt=CalcFC`, `Opt=Restart`, solvent, dispersion, or a different basis. Generate diagnostics and request approval first.

For an explicitly approved Opt-Freq-single-point workflow, record separate Opt/Freq and single-point routes, temperature, standard state, and resource tier. Deriving Freq from the approved Opt method does not authorize changing functional, basis, dispersion, solvent, integration grid, or convergence options.
