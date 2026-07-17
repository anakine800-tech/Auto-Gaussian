# Auto-G16 main-group open-shell reaction-network contract

Status: offline V1 extension. This contract emits
`gaussian-reaction-open-shell-network-review/1` and
`gaussian-reaction-open-shell-network/1`. It does not change the existing
closed-shell `gaussian-reaction-mechanism-network/1` or
`gaussian-reaction-calculation-plan/1` contracts.

## Scope and immutable bindings

V1 supports only one explicitly human-reviewed main-group,
single-reference doublet or high-spin triplet ground-state surface. Every
state binds an exact structure file, candidate artifact, accepted
`auto-g16-main-group-open-shell-review/1`, stable atom IDs, reviewed fragment
partition/coupling, and protocol-lineage ID. Every DAG node repeats the exact
candidate IDs, state-review payload hashes, and protocol-lineage IDs for its
state targets. Every edge binds both endpoint candidates and all endpoint
protocol lineages.

A reviewed protocol lineage either binds one exact
`gaussian-protocol-selection/1` artifact or explicitly remains `unresolved`.
The builder replays the bound selection through its protocol owner, but does
not select, infer, repair, or copy method, basis, solvent, resource,
wavefunction, threshold, or calculation settings.
An unresolved lineage is never silently replaced with a default.

## Conservation and state audit

The builder and replay validator independently require:

- a complete, one-to-one, element-preserving atom map for every edge;
- equal explicit element inventory, total formal charge, and recomputed
  electron count on both endpoints;
- an accepted owner-validated state review whose candidate, structure hash,
  charge, multiplicity, atom inventory, electronic scope, and state family do
  not drift;
- one common reviewed multiplicity and state family for the complete network;
- an explicit human `total_multiplicity_review` for every edge; and
- an explicit human fragment-spin-coupling review and exact atom partition for
  every state, plus a separate edge coupling review.

Fragment multiplicities are recorded evidence only. The builder never combines
them to derive total multiplicity. A missing or unresolved coupling, state or
multiplicity drift, hash drift, nonconservation, metal, or graph cycle is a
hard contract error.

## Exclusions and comparison boundary

V1 rejects spin crossing, MECP, open-shell singlets, broken symmetry,
multireference or excited states, mixed multiplicity/state-family surfaces,
transition metals, f-block elements, and any state outside the main-group
open-shell owner contract. State-distinct energy lineages cannot enter one
artifact and the emitted handoff explicitly sets
`energy_ranking_authorized: false`.

The output is a hash-bound, non-executable planning DAG/handoff. Every node has
`executable: false`; the artifact fixes `calculation_ready: false` and
`no_submission_authorization: true`. The presence of `ts_candidate`,
`ts_freq`, or IRC bookkeeping node names grants no TS, IRC, input, calculation,
submission, retry, cancellation, cleanup, or result-acceptance authority.

## CLI

```bash
TOOL="skills/auto-g16-reaction-workflow/scripts/open_shell_reaction_network.py"
python3 "$TOOL" build reviewed-open-shell-network.json --output open-shell-network.json
python3 "$TOOL" validate open-shell-network.json
```

Both commands are offline, reject unknown fields and symlinked inputs, refuse
overwrite, and replay the exact human review plus the main-group electronic-
state and protocol owner validators.
