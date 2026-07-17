# Auto-G16 Main-Group Open-Shell V1 Contract

## V1 positive scope

- Bind the exact candidate file and preserve its atom order, element inventory,
  structure hash, charge, and proposed multiplicity.
- Recompute the electron count from atomic numbers and charge. Require electron
  parity to agree with multiplicity parity.
- Accept only reviewed single-reference doublet or high-spin triplet minima
  whose task scope is exactly optimization plus harmonic frequency.
- Require a reviewed U or RO reference, an SCF stability test, a target
  `S(S+1)`, and a finite absolute post-annihilation S2 deviation threshold.
- Require alternative-state consideration and a resolved low multireference
  risk before allowing the protocol gate.
- Bind a human-reviewed expected harmonic-frequency count; never infer
  linearity from a molecule name or formula.

## Explicit exclusions

Route closed-shell restricted singlets to the existing closed-shell workflow.
Block open-shell singlets and broken-symmetry states even when their total
multiplicity is one. Block unresolved or material multireference risk, excited
states, transition metals and f-block elements, transition states, IRC, MECP,
spin crossing, and any task other than minimum Opt/Freq evidence.

Treat `triplet_carbene` as a supported state family when every other V1 check
passes. Do not treat the word “carbene” itself as evidence for a state.

## Result evidence

The observation parser records only text facts: charge, multiplicity, SCF
energy and reference family, normal/error termination, stationary-point text,
S2 before and after annihilation, stability text, and frequency values. Missing
text remains missing; the parser never fills a scientific default.

Acceptance binds exact review, observation, and policy artifacts. It blocks on
missing S2, excessive post-annihilation S2 deviation, instability, reference or
state drift, incomplete SCF/termination/frequency facts, a frequency count
different from the reviewed expectation, any imaginary frequency for a
minimum, or any review outside the V1 positive scope.

## Authority

All artifacts are canonical JSON with SHA-256 payload seals and exact source
file hashes. They are offline evidence only. They never authorize Gaussian,
SSH, PBS, server directories, input rendering, retry, cancellation, cleanup,
deployment, or live smoke testing.
