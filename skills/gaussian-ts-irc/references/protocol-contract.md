# TS–Freq–IRC protocol contract

## Manifest: `gaussian-ts-irc-workflow/1`

Record a workflow ID, PBS-safe prefix (1–15 letters/digits/underscores), source paths and SHA-256 values, input identities/formula/components, charge, multiplicity, atom count, explicit shared atom map, intended forming/breaking/transferring pairs, entry mode, all complete approved routes, parsed method/basis/dispersion/solvent/grid/SCF fields when available, temperature/standard state/low-mode policy, per-stage resource tier, expected Gaussian stage counts, review decisions, project names, job IDs, and parent/child artifact hashes.

The complete TS/Freq, forward-IRC, reverse-IRC, endpoint Opt/Freq routes are user-supplied protocol values. Never use a placeholder or convert a route between stages implicitly. Confirm exact G16 IRC keyword support for the installed revision before generating a real input.

## Results

`gaussian-ts-freq-result/1` holds termination/error evidence, stationary-point status, energy, frequencies, raw imaginary count, parsed displacement vectors, final geometry, candidate status, mode-review status, hashes, and diagnostics. Exactly one negative frequency makes `first_order_saddle_candidate` true only when normal/stationary/frequency evidence is also present.

`gaussian-irc-plan/1` is a local submission plan, not a job. It records direction, reviewed TS result hash, checkpoint hash, supplied route, resource tier, and fresh project. It must be handed to the PBS layer only after G3 approval.

Final validation needs both complete IRC direction results plus endpoint Opt/Freq evidence. A failed IRC does not by itself disprove the stationary point; it means the intended connection was not established.

## Resource tiers

Use `simple` (12 GB/8 cores), `general` (50 GB/22 cores), or `complex` (120 GB/44 cores). Job type never selects a tier automatically. Show `%mem`, `%nprocshared`, PBS request, and expected stage count before any submission.
