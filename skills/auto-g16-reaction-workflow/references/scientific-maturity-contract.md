# Auto-G16 Scientific Maturity and Minima-First TS Contract

Status: prospective offline implementation. The owner artifacts are
`gaussian-scientific-maturity-review/1` and
`gaussian-scientific-maturity-gate/1`. They overlay an exact validated
`gaussian-reaction-calculation-plan/1`; they never edit the plan or any older
record, choose a method, render an input, or authorize a live action.

## Three separate gates

1. **Scientific maturity**: literature saturation, active-state and elementary-
   step review, accepted endpoint minima, TS strategy, pilot/resource budget,
   path evidence, common references and stop conditions.
2. **Input review**: protocol selection, exact structure/route/resources and
   rendered input hash. Passing scientific maturity only permits this separate
   review to begin.
3. **Execution approval**: exact live approval for the rendered input and fresh
   project. Before that live approval, the offline
   `gaussian-scientific-action-authorization/1` binds one passed scientific
   check to the exact DAG node, input hash, project, work kind, resource tier
   and task/core-hour/concurrency request. PBS reconstructs both records for
   protected routes. Neither offline gate grants submission authority.

Approval summaries present `maturity`, `evidence`, `endpoints`, and `blockers`
before route, resources and input hash.

## Literature and mechanism intake

The review records user-supplied paper, author, group, DOI, title, screenshot
and SI seeds only as `verifiable_seed` or `user_hypothesis`. It separately
records active-species, elementary-step, bond-change, selectivity-determining
and experimental-intermediate hypotheses. No seed is promoted automatically.

The closed search overlay covers exact systems, catalyst/reaction matches,
substrate-class analogies, BPh3/HBpin activation, pyridine regioselectivity,
active states/ion pairs/Lewis adducts, computational mechanism/TS/IRC/
selectivity, backward and forward citation chains, and full text/SI/
coordinates. A lane may be `not_applicable` only explicitly. Saturation reports
direct, analogous, missing full text/SI, unverified user material and unresolved
questions. Formal mechanism support remains blocked until the user confirms no
obvious key-literature omission.

Each active edge binds the exact mechanism-network edge and stereochemical
channel, primary/competing path decision, evidence class, active species, step
type, transfers, forming/breaking bonds, expected coordinate, endpoint minima
and TS strategy. Evidence classes are exactly `direct_literature`,
`analogous_literature`, `user_hypothesis`,
`internal_exploratory_hypothesis`, and `missing_precedent`.

The active species is not a free-floating label: each edge binds an exact
`active_species_hypothesis_id` from intake, and that hypothesis must already be
in `reviewed_hypothesis` state. Every active edge also classifies exactly one
DAG node as its low-cost pilot and explicitly lists its formal TS nodes.
Unclassified, missing, non-TS or cross-edge node bindings are rejected.

Formal TS readiness additionally requires the exact owner-validated mechanism-
support and TS-precedent artifacts already bound by the calculation plan. The
overlay's explicit edge/channel mapping cannot replace or weaken either owner.
Geometry permutations cannot promote an edge.

## Minima-first hard dependency

The enforced order is component/active state, conformer search, low-cost
preoptimization, Gaussian Opt, complete Freq, zero-imaginary identity review,
an accepted endpoint pair, TS pilot, TS/Freq and mode review, bidirectional IRC,
then IRC-endpoint re-Opt/Freq.

An accepted minimum binds the exact raw Gaussian log, workflow-analysis
settings, parsed result JSON, checkpoint and optimized coordinates. The owner
validator replays the raw log through the RTwin/PBS Gaussian parser and requires
the supplied result to agree. It then requires normal termination, converged
optimization/stationary-point evidence, complete frequency evidence, zero
imaginary frequencies, matching composition/charge/multiplicity/atom count,
and explicit review of connectivity/identity, exact mechanism-owner element and
atom order/mapping, duplicates,
weak association, low modes and retained files. Both endpoint minima must match
the mechanism edge and have compatible composition, charge, multiplicity and
atom count. Missing or rejected endpoints block both TS input and TS submission
and project that blocker onto every active TS DAG node.

Conformer-search provenance must be `minimum_search`. TS derivation is allowed
only from reviewed minima provenance; FF/xTB energies remain screening evidence
and cannot be reported as formal barriers.

## Pilot, resources and path acceptance

The default TS pilot uses `simple` (12 GB/8 cores), one primary candidate per
edge and at most one competing candidate. Failure returns to mechanism or
endpoint review. Automatic candidate expansion, retry or chemistry change is
forbidden. General/complex tiers require a reviewed successful-pilot evidence
reference plus scale, memory and cost rationale. The review fixes maximum
tasks, core-hours and concurrency.

No direct precedent may still permit one simple pilot when the edge is an
explicit hypothesis and both minima pass. It never permits a literature-
supported claim or formal TS promotion. Formal path acceptance requires exactly
one imaginary frequency, manual intended-coordinate confirmation, terminated
forward and reverse IRC, structurally identified endpoints, and endpoint
re-Opt/Freq with zero imaginary frequencies matching the expected minima. An
accepted TS mode binds an owner-validated calculation-attempt link; the two IRC
directions bind owner-built `gaussian-ts-irc-path-acceptance/2`. Its owner
replays the exact mechanism network/edge/study, TS family/result and mode,
direction endpoint execution, charge, multiplicity and stable atom-to-element
mapping. Historical `/1` remains replayable but cannot weaken this gate. Endpoint
re-Opt/Freq binds two additional accepted minimum records rather than reusing
the original endpoints. An accepted path must cite auditable evidence for that complete chain;
partial or isolated acceptance flags cannot open IRC, downstream DAG nodes or
formal barrier reporting. Those stages also recheck the formal mechanism-
support and TS-precedent owner gates rather than inheriting the pilot exception.

Common reference inventories require identical composition, 1 M standard
state, explicit temperature/solvent/catalyst-regeneration relation, local versus
apparent barrier distinction, minima/TS conformer coverage, approved low-
frequency policy, and retention of electronic energy, enthalpy, raw Gibbs and
treated Gibbs. Sensitivity work is limited to a few optimized representatives.

## Commands and migration

```bash
TOOL="skills/auto-g16-reaction-workflow/scripts/scientific_maturity.py"
python3 "$TOOL" finalize-review maturity-review.draft.json --output maturity-review.json
python3 "$TOOL" build calculation-plan.json --review maturity-review.json --output maturity-gate.json
python3 "$TOOL" validate maturity-gate.json
python3 "$TOOL" check-action maturity-gate.json --edge-id edge_id --action ts_input --pilot
python3 "$TOOL" authorize-action maturity-gate.json --input pilot.gjf \
  --edge-id edge_id --node-id pilot_node --action ts_submission --pilot \
  --resource-tier simple --project fresh_project --work-kind ts_pilot \
  --task-count 1 --estimated-core-hours 8 --planned-concurrency 1 \
  --output scientific-action-authorization.json
python3 "$TOOL" validate-action-authorization scientific-action-authorization.json
```

Historical calculation plans, TS-family `/1` artifacts and live approvals `/1`
remain immutable and valid under their original contracts. TS-family `/1` is
replay-only and cannot create a new IRC plan. New TS-family CLI
creation emits `gaussian-ts-irc-workflow/2` and requires the maturity gate.
Historical TS live approvals `/2` and non-TS approvals `/1` remain replayable
under their original contracts. New live submissions use
`auto-g16-live-submission-approval/3`, which also binds explicit `work_kind`
and the exact generic input-approval receipt file/payload hashes. For TS work
the `/3` scope additionally retains the `/2` maturity and scientific-action
authorization bindings. No in-place migration is permitted; a correction
creates a new review/gate and later artifact revision.

### Known `/1` owner-integration blocker

Historical `gaussian-scientific-maturity-gate/1` formal readiness checks bind
the exact calculation plan but do not yet independently project the target
edge/channel promotion state from both owner artifacts. The reproducible
constraint is recorded in
`tests/fixtures/reaction_workflow/maturity_v2_owner_evidence_constraint.json`;
it is not an expected failure in the green suite. Do not change the `/1`
reconstruction semantics in place; close this in a later versioned
scientific-maturity owner-evidence integration. Input approval and exact live
approval remain separate mandatory gates and do not repair or replace this
scientific blocker.
