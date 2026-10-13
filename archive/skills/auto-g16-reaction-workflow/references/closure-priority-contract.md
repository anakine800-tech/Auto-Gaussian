# Auto-G16 Closure-Priority Plan Contract

## Scope and authority

`gaussian-closure-priority-plan/1` is an additive, immutable planning view over
human-reviewed closure-route requests. Its goal is exactly: **use as few PBS
jobs as practical while answering the most important scientific questions and
pursuing a reliable closure.** This means the smallest practical evidence-
complete or conditionally complete bundle, not an absolute mathematical job
minimum that drops necessary evidence.

The plan is non-executable. It fixes `executable: false`,
`calculation_ready: false`, `no_submission_authorization: true`,
`no_automatic_retry: true`, and `no_automatic_search_expansion: true`. It does
not create Gaussian input, select or change chemistry or methods, submit or
monitor PBS work, accept results, retry failures, enumerate Cartesian
combinations, or mutate the calculation DAG.

## Gate-before-rank rule

Every route supplies explicit reviewed decisions for all of these hard gates:

1. reviewed mechanism and active state;
2. exact atom mapping and electronic/chemical state;
3. accepted endpoint minima where required;
4. method evidence and an explicit method decision;
5. user confirmation;
6. reviewed budget; and
7. duplicate and state-collapse checks.

A blocked gate, an over-budget maximum estimate, a human defer/reject decision,
or an incomplete closure bundle prevents ranking. Strong dimension bands can
never compensate for a failed hard gate.

## Auditable ranking and selection

Eligible routes retain separate `high`, `medium`, `low`, or `unknown` records
for scientific value/information gain, evidence strength, mapping clarity,
initial-guess quality, convergence likelihood, expected closure likelihood,
and dependency reuse. Each record carries calibration basis and provenance.
`unknown` requires explicit unavailable provenance. Numeric probabilities and
synthetic numeric likelihood scores are forbidden.

Ranking is deterministic and lexicographic in the documented dimension order;
estimated PBS-job and core-hour cost is last. The first primary route supplies
the smallest practical complete closure bundle. A low-probability exploration
can be added only after a primary selection, when the request explicitly opts
in, the route has explicit review, and its maximum estimate fits the remaining
reviewed budget. Every unselected route retains a defer/reject reason.

## Conditional closure decision DAG

An eligible bundle contains this dependency chain:

`TS/Freq -> intended-imaginary-mode review -> separately approved forward and reverse IRC -> structurally identified endpoints -> endpoint Opt/Freq when scientifically necessary`

Every node records evidence requirements and explicit stop/continue conditions.
Forward and reverse IRC approvals remain separate. Exactly one imaginary
frequency is insufficient without review that its normal mode follows the
intended reaction coordinate. Both IRC directions must terminate and their
endpoints must be structurally identified before closure is claimed. Existing
accepted endpoint minima may make the final endpoint Opt/Freq node unnecessary;
the plan must retain that conditional decision instead of scheduling it
automatically.

## Offline builder

From the repository root:

```bash
./scripts/python core skills/auto-g16-reaction-workflow/scripts/closure_priority.py \
  build closure-priority-request.json --output closure-priority-plan.json
./scripts/python core skills/auto-g16-reaction-workflow/scripts/closure_priority.py \
  validate closure-priority-plan.json
```

The builder uses strict JSON, refuses request symlinks and output overwrite,
binds the request byte hash, emits a canonical payload hash, and performs no
network or live action.
