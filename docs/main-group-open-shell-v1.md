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

The `main_group_open_shell_minimum_opt_freq_v1` extension adds a reviewed
Cartesian candidate, explicit input specification, immutable non-executable
input handoff, input audit, result-source binding, result observation, and
result-continuity acceptance. It binds candidate→state review→protocol
options/selection→input text→result file with exact file, payload, coordinate,
input-text, and result SHA-256 values. The builder does not infer route,
method, basis, solvent, resources, multiplicity, U/RO reference, stability
policy, frequency count, or server location.

The handoff accepts only explicit U/RO minimum Opt/Freq routes with stability
testing and rejects TS/QST, IRC, TD and `guess=mix`. It preserves exact atom
order and Cartesian coordinates, requires protocol-selected resources, keeps
the server directory null/not authorized, and grants no execution authority.
The result closure requires normal termination, SCF convergence, a stationary
minimum, exact state/reference continuity, stable-wavefunction evidence,
in-policy post-annihilation S2, the reviewed frequency count, and no imaginary
frequencies. Positive sanitized fixtures cover CH3 doublet and triplet CH2;
negative tests cover state, hash, reference, stability, S2, frequency, route,
resource, and structure drift plus closed-shell, metal, open-shell singlet, and
multireference routing boundaries.

All artifacts use closed versioned schemas under
`contracts/main-group-open-shell/`, canonical JSON, payload and exact-file
SHA-256 bindings, duplicate-key/non-finite/unknown-field rejection, symlink
refusal, and no-overwrite writes. Every artifact retains
`calculation_ready: false` and `no_submission_authorization: true`. This slice
has no Gaussian, SSH, PBS, deployment, or live-smoke execution surface and
does not modify the existing closed-shell single-guess TS/Freq adapter.
