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
4. Parse a supplied Gaussian text result with `observe`. Treat the output as
   facts only, never as scientific acceptance.
5. Bind one exact accepted review, observation, and predeclared human policy
   with `accept`. Fail closed on any missing or inconsistent diagnostic.
6. Use `validate` to re-check canonical JSON, hashes, source bindings, and the
   authority boundary.

Run `scripts/open_shell_state.py --help` for the offline CLI. Store the closed,
versioned JSON Schemas under the repository `contracts/main-group-open-shell/`
directory; do not copy them into this Skill.

## Boundaries

Reject closed-shell singlets into the existing closed-shell path. Block
open-shell singlets, broken symmetry, unresolved multireference character,
excited states, metals, TS/IRC, MECP/spin crossing, and any state drift.
Classify carbenes by reviewed electronic state: a supported triplet carbene may
enter V1, while singlet or multireference carbene cases remain outside it.

Every emitted artifact must retain `calculation_ready: false` and
`no_submission_authorization: true`. Result acceptance does not authorize an
input draft, submission, retry, live action, or promotion into another workflow.
