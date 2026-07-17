# Auto-G16 Main-Group Open-Shell V1

This offline slice adds candidate-bound electronic-state review, read-only
Gaussian result observation, protocol selection gating, and result acceptance
for explicitly reviewed single-reference main-group doublet and high-spin
triplet minima. The positive evidence scope is optimization plus harmonic
frequency only. A reviewed triplet carbene is classified by its triplet state
and may enter this scope.

The electronic-state review recomputes atomic-number and electron totals,
checks electron/multiplicity parity, binds the credible multiplicity set,
records U or RO reference policy, requires SCF stability, fixes the target
`S(S+1)` and post-annihilation S2 threshold, records alternative solutions,
binds a human-reviewed expected frequency count without guessing linearity
from a name or formula, and blocks unresolved multireference risk. A caller-provided
`support_status: supported` cannot make an open-shell protocol option
selectable without the exact accepted review and a matching reference,
stability, and S2 method profile.

The Gaussian observation parser records charge/multiplicity, SCF and energy,
termination, S2 before/after annihilation, stability text, stationary-point
text, and frequencies. It grants no scientific acceptance. Result acceptance
binds the exact review, observation, and a predeclared human policy and fails
closed on missing diagnostics, state or reference drift, instability,
excessive S2 deviation, a frequency count different from the reviewed
expectation, incomplete Opt/Freq facts, or an imaginary frequency.

V1 explicitly excludes restricted closed-shell singlets (owned by the
existing closed-shell path), open-shell singlets and broken symmetry,
unresolved or material multireference character, excited states, metals,
transition states, IRC, MECP and spin crossing. Singlet carbenes follow their
reviewed electronic state: ordinary restricted closed-shell cases remain in
the old path; open-shell or multireference singlets are blocked here.

All three artifacts use closed versioned schemas under
`contracts/main-group-open-shell/`, canonical JSON, payload and exact-file
SHA-256 bindings, duplicate-key/non-finite/unknown-field rejection, symlink
refusal, and no-overwrite writes. Every artifact retains
`calculation_ready: false` and `no_submission_authorization: true`. This slice
has no Gaussian, SSH, PBS, deployment, or live-smoke execution surface and
does not modify the existing closed-shell single-guess TS/Freq adapter.

## Multiplicity-family extension

The offline multiplicity-family V1 extension records multiple independently
reviewed multiplicity/state branches under one human-confirmed composition and
structure relationship. Every member retains its own candidate, state review,
protocol, input, and result lineage; file hashes may not be reused across
members.

Only independently accepted single-reference doublet or high-spin triplet
members can remain eligible for a later, separately approved input handoff.
Quartets, open-shell singlets, and other unsupported states remain visible as
`blocked_needs_specialist`; they are not silently omitted.

Comparison requires an explicitly approved common electronic-energy protocol,
exact common reference, settings hash, and comparability statement. The audit
does not order energies, declare a ground state, mix thermochemistry, infer
multireference character from energy proximity, model spin crossing or MECP,
or combine multiplicities in one conformer ensemble. The contracts are under
`contracts/main-group-open-shell/`; the detailed boundary is in
`references/multiplicity-family-contract.md` in the Skill.
