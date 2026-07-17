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

## Minimum Opt/Freq input and continuity handoff

The versioned workflow identifier is
`main_group_open_shell_minimum_opt_freq_v1`. Its input handoff binds five exact
canonical sources: the accepted electronic-state review, a human-reviewed
Cartesian candidate, protocol options, protocol selection, and an explicit
input specification. The builder preserves atom order and coordinates and
requires equality of candidate identity, coordinate hash, charge,
multiplicity, review hash, selection hash, selected-option hash, U/RO
reference, stability requirement, expected frequency count, and selected
resources. The route must explicitly contain minimum optimization, harmonic
frequency, stability, and the reviewed U/RO method family; TS, QST, IRC, TD,
and broken-symmetry `guess=mix` tokens are outside this contract.

The offline handoff renders exact text only as a hash-bound, non-executable
artifact. It fixes `server_directory` to null and
`server_directory_status` to `not_created_not_authorized`. The input audit
re-parses that text and checks Link 0 resources, route, state, atom order,
coordinates, trailing termination blank line, and input SHA-256.

A result-source binding is supplied evidence, not a transport claim. It binds
the exact handoff payload and input-text SHA-256 to one exact result file
SHA-256. Result observation reuses the electronic-state fact parser. Continuity
acceptance closes candidate→state review→protocol→input→result and requires
normal termination, converged SCF, stationary-point text, exact state and
reference, stable wavefunction evidence, present and in-policy post-annihilation
S2, the reviewed frequency count, and zero imaginary frequencies.

## Authority

All artifacts are canonical JSON with SHA-256 payload seals and exact source
file hashes. They are offline evidence only. The minimum handoff authorizes
only its already-rendered offline text; it never authorizes Gaussian, SSH, PBS,
server-directory creation, submission, retry, cancellation, cleanup,
deployment, evidence promotion, or live smoke testing.
