# Auto-G16 Main-Group Open-Shell TS/Freq/IRC V1 Contract

## Scope and ownership

This is a separate offline adapter. Its workflow kind is
`main_group_open_shell_single_surface_ts_freq_irc` and its owner artifact is
`auto-g16-main-group-open-shell-ts-irc-workflow/1`. It does not alter or
generalize the historical
`closed_shell_main_group_single_guess_ts_freq` adapter.

The workflow consumes three exact sources: an accepted
`auto-g16-main-group-open-shell-review/1`, a reviewed
`auto-g16-main-group-open-shell-ts-candidate/1`, and an explicit
`auto-g16-main-group-open-shell-ts-irc-protocol-source/1`. File and payload
hashes bind every source. The candidate, review, and protocol must agree on
charge, multiplicity, state family, atom order, and U/RO reference.

Only reviewed, single-reference, same-spin-surface doublets and high-spin
triplets are supported. Transition metals, open-shell singlets,
broken-symmetry states, material or unresolved multireference character,
excited states, spin crossing/MECP, and endpoints with another multiplicity
are rejected. The adapter never selects or infers a method, basis, solvent,
resource statement, wavefunction reference, S2 threshold, route, or numerical
setting.

## Artifact sequence

1. `build-workflow` binds the exact accepted state review, TS candidate, and
   reviewed protocol.
2. `audit-input` checks one already supplied TS/Freq or directional IRC input
   against the exact workflow, protocol-selection payload, input bytes, route,
   atom order, charge, multiplicity, state family, and reference. It does not
   render an input.
   The auditor reads the single route section back from the exact input bytes,
   rejects Link1 or multiple route sections, compares normalized route meaning
   with the reviewed protocol, and applies the same stage audit to both.
   V1 route auditing supports only a single-candidate `Opt=TS` TS/Freq route
   with `Freq` and an explicit `Stable=Opt` setting. Ordinary minimum Opt/Freq,
   frequency-only, QST2/QST3, IRC, TD, crossing/MECP, conical and avoided-state
   routes fail closed. QST2/QST3 would require a later independent
   multi-structure source contract. Each IRC route must contain exactly one IRC
   keyword and exactly one direction as its own IRC option, plus the explicit
   stability setting; mixed, missing or duplicated directions are rejected.
3. The existing `open_shell_state.py observe` parser owns Gaussian text facts.
   `accept-ts` binds its deterministic observation, the TS input audit, and a
   separate human mode decision. Acceptance requires normal termination, a
   stationary point, exactly one imaginary frequency, explicit confirmation
   that that mode follows the intended reaction coordinate, matching U/RO
   reference, stable wavefunction, and S2 within the reviewed threshold.
4. `plan-irc` requires an accepted TS and separate exact forward and reverse
   input audits. The result is an offline evidence plan only and fixes
   `irc_validated: false`.
5. `accept-irc` consumes both reviewed endpoint sources. It can emit
   `irc_validated` only when both directions complete normally, the two
   structures are explicitly identified as one reactant and one product, and
   charge, multiplicity, state lineage, U/RO reference, stability, S2 policy,
   plan hash, and direction-specific input-audit hashes remain continuous.

Every emitted artifact uses canonical JSON, a SHA-256 payload seal, immutable
source bindings, `calculation_ready: false`, and
`no_submission_authorization: true`. All Gaussian, SSH, PBS, submission,
retry, cancellation, cleanup, deployment, and input-rendering authorizations
are false. IRC path acceptance does not establish endpoint minima,
thermochemistry, kinetics, or permission for any live action.

The closed JSON Schema union is stored at
`contracts/main-group-open-shell/ts-irc-contracts.schema.json`. Synthetic
fixtures contain no raw Gaussian output or checkpoint data.
