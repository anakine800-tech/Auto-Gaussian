# Auto-G16 protected production ingress boundary

The additive production-ingress successor accepts only the exact sealed
owner-consumer capability. It replays the already durable uncertain receipt,
claims the already sealed effect-plan inputs once, snapshots only those
owner-derived values, and exposes one non-executable production ingress plus
one single-claim legacy factory port.

The contract binds the exact production facade `_submit_new()` identity and
the exact legacy module, effect-plan factory, transaction/plan/raw-owner
types, source bytes and 13 plan-input fields. The current factory still
accepts only the CLI-owned transaction plan, so the machine-readable status
keeps `production_submit_wired=false`,
`current_factory_accepts_port=false`, `factory_invoked=false`,
`effect_plan_created=false` and `raw_effect_owner_created=false`.

The owner never reads caller paths or runtime configuration, stages, reserves,
writes, consumes runtime state again, constructs a legacy plan or raw owner,
calls an adapter or runner, or performs transport/PBS/Gaussian. Schema
validity is structural and never issues a seal. Exact owner replay rejects
wrong import order, foreign identical modules/classes, pre-call cache
replacement and source drift before the predecessor plan inputs are claimed.
Integral JSON numbers at the three declared `integer` positions normalize to
exact Python `int` before semantic and hash closure; booleans,
fractional/non-finite numbers and values outside `1..9007199254740991`
remain rejected by both Schema and helper. The `2^53-1` maximum prevents
cross-language JSON-number precision folding after binary-float parsing.
It does not claim atomic protection against arbitrary same-process
`sys.modules` mutation after the final check.

See
[`docs/v2.6-protected-production-ingress-contract.md`](../../../docs/v2.6-protected-production-ingress-contract.md)
for the ownership matrix, exact call-chain inputs and remaining production
wiring gate.
