---
name: auto-g16-metal-ts
description: Offline-only P2-P4 transition-metal TS input approval, result acceptance, and explicit promotion contracts. Never submits or runs Gaussian/PBS/SSH.
---

# Auto-G16 Metal TS Runtime Contract

## Scope

This Skill is the metal-specific offline P2-P4 boundary. It does not extend
`auto-g16-ts-irc`; that Skill must continue to refuse every transition-metal
case. It has no SSH, PBS, Gaussian, input-rendering, retry, cancellation, or
deployment command.

The only supported seed strategy is `hessian_guided_single_guess`. QST2/QST3,
relaxed scans, MECP, NEB/string, and every unknown strategy are blocked until
they receive a separate evidence contract and implementation.

## State transitions

1. `approve-input-paths` binds the exact candidate, completed real M1 review,
   protocol options and selection, observed existing input, basis/ECP coverage,
   electronic state, atom order, charge/multiplicity, Hessian provenance, and
   a reviewer decision. It grants offline input acceptance only.
2. `accept-result-paths` binds that approval and an existing result observation. It
   requires identity, state/wavefunction and stability evidence, bounded
   `S**2`, retained coordination/ligand inventory, complete frequencies,
   exactly one imaginary frequency, and hash-bound intended-mode evidence.
3. `decide-promotion-paths` records an explicit human promotion decision bound to an
   accepted result. Acceptance never promotes implicitly.

Every artifact denies live/submission authority. Any changed upstream payload
or rehashed-but-semantically-altered object is rejected by recomputing and
checking its bindings.

```bash
python skills/auto-g16-metal-ts/scripts/metal_ts.py approve-input-paths REQUEST.json --output APPROVAL.json
python skills/auto-g16-metal-ts/scripts/metal_ts.py accept-result-paths REQUEST.json --output ACCEPTANCE.json
python skills/auto-g16-metal-ts/scripts/metal_ts.py decide-promotion-paths REQUEST.json --output PROMOTION.json
```

See `references/runtime-contract.md` for the complete evidence and refusal
rules. Outputs are local immutable JSON and refuse overwrite.
