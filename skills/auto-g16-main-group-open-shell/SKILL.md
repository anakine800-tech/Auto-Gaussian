---
name: auto-g16-main-group-open-shell
description: Offline, fail-closed review and result acceptance for candidate-bound main-group open-shell electronic states. Use when Codex must audit electron count, multiplicity, wavefunction reference, SCF stability, spin contamination, alternatives, or Gaussian Opt/Freq evidence for reviewed single-reference doublet or high-spin triplet minima without authorizing calculation.
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

Run `scripts/open_shell_state.py --help` for the electronic-state CLI and
`scripts/open_shell_minimum.py --help` for the V1 input/result-continuity CLI.
Store the closed, versioned JSON Schemas under the repository
`contracts/main-group-open-shell/` directory; do not copy them into this Skill.

## Boundaries

Reject closed-shell singlets into the existing closed-shell path. Block
open-shell singlets, broken symmetry, unresolved multireference character,
excited states, metals, TS/IRC, MECP/spin crossing, and any state drift.
Classify carbenes by reviewed electronic state: a supported triplet carbene may
enter V1, while singlet or multireference carbene cases remain outside it.

Every emitted artifact must retain `calculation_ready: false` and
`no_submission_authorization: true`. The V1 handoff may contain a rendered
offline input text, but must keep server directory null and authorize no
Gaussian, SSH, PBS, submission, retry, cancellation, cleanup, deployment, or
evidence promotion. Result acceptance does not authorize a new input or live
action.
