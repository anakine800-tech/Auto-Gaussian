# Protocol selection

Before using any protocol below, read
[`protocol-rigor.md`](protocol-rigor.md). Every new calculation request must
first receive a three-candidate `loose`/`standard`/`strict`
`gaussian-protocol-options/1` proposal and a separate explicit
`gaussian-protocol-selection/1` user selection. Do not write a Gaussian input
before that selection exists. The selected candidate authorizes only an
offline input draft; the rendered input hash and live job still require their
own approval.

The built-in entries below are constrained examples, not the three rigor
candidates and not universal defaults. They cannot bypass a blocked proposal
or supply missing method, basis, solvent, charge, multiplicity, spin, TS, IRC,
thermochemistry or low-frequency decisions.

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

Resource tiers are orthogonal to protocol rigor. Do not map `loose` to
`simple`, `standard` to `general`, or `strict` to `complex`. System size and
execution demand determine resources after the scientific protocol candidate
has been reviewed.

A reaction-workflow TS pilot is a narrower prospective rule: use `simple`, one
primary candidate per edge and at most one competing candidate. General or
complex TS work requires the exact maturity gate's successful-pilot evidence
and reviewed scale/memory/cost rationale; job type alone never upgrades it.
Every protected TS, relaxed-scan or IRC route also requires an explicit
`--work-kind`; inference from only QST/`Opt=TS` is insufficient. A protected
submission must bind the exact input/project/node and requested
task/core-hour/concurrency budget in a reconstructed offline scientific action
authorization before the separate live approval is considered.

## Approval rules

If any scientific field needed by a candidate is unresolved, mark that
candidate `blocked`. Keep all three candidate names visible, but do not invent a
runnable route to complete the table. Unsupported transition-metal, open-shell,
broken-symmetry, excited-state or multireference cases remain blocked under the
owning scientific Skill.

Require explicit method, basis, job type, charge, multiplicity, cores, and memory before submission. Treat a command containing `--confirmed` as valid only when those exact values were shown or supplied by the user.

Protocol selection is not submission confirmation. It authorizes only
rendering the exact selected offline input draft. Any later change in method,
basis, solvent, numerical settings, thermochemistry, resources or job type
requires a new proposal and selection, followed by a new input-hash approval.

`strict` means a stronger evidence, convergence or sensitivity plan for the
stated question. It does not guarantee accuracy or validate the chemical model.

Do not automatically add `Freq` after `Opt`. Do not automatically retry with `SCF=XQC`, `Opt=CalcFC`, `Opt=Restart`, solvent, dispersion, or a different basis. Generate diagnostics and request approval first.

For an explicitly approved Opt-Freq-single-point workflow, record separate Opt/Freq and single-point routes, temperature, standard state, and resource tier. Deriving Freq from the approved Opt method does not authorize changing functional, basis, dispersion, solvent, integration grid, or convergence options.
