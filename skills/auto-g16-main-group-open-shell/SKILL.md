---
name: auto-g16-main-group-open-shell
description: Offline, fail-closed review and result acceptance for candidate-bound main-group open-shell electronic states and the separate same-spin-surface TS/Freq/IRC adapter. Use when Codex must audit electron count, multiplicity, wavefunction reference, SCF stability, spin contamination, alternatives, minimum evidence, or explicitly reviewed single-reference doublet/high-spin-triplet TS/IRC continuity without authorizing calculation.
---

# Auto-G16 Main-Group Open-Shell

Keep every operation offline. Never run Gaussian, SSH, PBS, deployment, or a
live smoke test through this Skill.

## Workflow

1. Read [references/electronic-state-contract.md](references/electronic-state-contract.md).
2. Bind one exact candidate and one human review source with `review`.
3. Permit a V1-positive review only for a reviewed single-reference main-group
   doublet or high-spin triplet minimum with Opt/Freq evidence scope.
4. For `main_group_open_shell_minimum_opt_freq_v1`, bind the accepted review,
   exact reviewed Cartesian candidate, exact protocol options/selection, and
   explicit input specification with `open_shell_minimum.py handoff`. Do not
   infer route, resources, reference, stability settings, or frequency count.
5. Run `audit-input` before treating the non-executable handoff as coherent.
   It must preserve state, atom order, coordinates, route, resources, hashes,
   and the absent/not-authorized server-directory state.
6. Parse a supplied Gaussian-like text result with `observe` or a hash-bound
   result source with `observe-result`. Treat parsed output as facts only.
7. Bind the exact input audit and result observation with `accept-result` to
   close candidate→review→protocol→input→result continuity. Fail closed on
   any missing or inconsistent diagnostic or lineage hash.
8. Use `validate` to re-check canonical JSON, hashes, source bindings, and the
   authority boundary.

For Gaussian 16 A.03 minimum work needing Opt/Freq plus `Stable=Opt`, use
`scripts/open_shell_minimum_family.py`. It keeps the operations as independently
approved stages under `main_group_open_shell_minimum_two_stage_v1`; never add
`Stable=Opt` to the Opt/Freq route or treat family artifacts as live authority.
9. For a reviewed multiplicity/state family, read
   [references/multiplicity-family-contract.md](references/multiplicity-family-contract.md),
   then use `scripts/multiplicity_family.py` to build the independent-member
   offline plan and audit supplied result comparability. Retain unsupported
   members as `blocked_needs_specialist`.
10. For the separate same-spin-surface TS/Freq/IRC workflow, read
    [references/open-shell-ts-irc-contract.md](references/open-shell-ts-irc-contract.md)
    and use `scripts/open_shell_ts_irc.py`. It consumes an exact accepted state
    review but does not change the V1 minimum acceptance rules above.

Run `scripts/open_shell_state.py --help` for the electronic-state CLI and
`scripts/open_shell_minimum.py --help` for the V1 input/result-continuity CLI.
Store the closed, versioned JSON Schemas under the repository
`contracts/main-group-open-shell/` directory; do not copy them into this Skill.

Run `scripts/multiplicity_family.py --help` for the multiplicity-family CLI.
Use `bind-result` to deterministically bind the exact member protocol and input
lineage to supplied accepted result evidence before `audit`; missing proof must
remain blocked. The binding never claims transport or live-execution provenance.
It never ranks energies, declares a ground state, mixes thermochemistry, or
places different multiplicities in a conformer ensemble.
Run `scripts/open_shell_ts_irc.py --help` for the TS/Freq/IRC CLI.

## Boundaries

Reject closed-shell singlets into the existing closed-shell path. The original
`open_shell_state.py` minimum workflow continues to block TS/IRC. The separate
TS/IRC adapter blocks open-shell singlets, broken symmetry, unresolved
multireference character, excited states, metals, MECP/spin crossing,
different-multiplicity endpoints, and any state or hash drift.
Classify carbenes by reviewed electronic state: a supported triplet carbene may
enter V1, while singlet or multireference carbene cases remain outside it.

Every emitted artifact must retain `calculation_ready: false` and
`no_submission_authorization: true`. The V1 handoff may contain a rendered
offline input text, but must keep server directory null and authorize no
Gaussian, SSH, PBS, submission, retry, cancellation, cleanup, deployment, or
evidence promotion. Result acceptance does not authorize a new input, retry,
live action, or promotion into another workflow. Multiplicity-family planning
and comparison auditing have the same authority boundary and additionally
exclude spin crossing and MECP.
