# Auto-G16 v2.5 method-evidence design

## Purpose and boundary

This slice lets the knowledge layer collect and summarize method evidence for
one reviewed calculation context. It is offline and evidence-only. It does not
choose a functional, basis set, ECP, solvent model, reference, composite
protocol, or resource tier. It cannot create user approval, calculation
readiness, Gaussian input, submission authority, or a success probability.

The existing five canonical knowledge-record types are unchanged. The new
artifacts are immutable supporting contracts and do not enter the canonical
SQLite record registries automatically.

## Contracts

- `auto-g16-method-selection-context/1` binds the reviewed calculation family,
  elements and ECP scope, charge and multiplicity, electronic-state and
  wavefunction-reference constraints, phase/solvent, target properties, and
  resource ceilings.
- `auto-g16-method-benchmark-case/1` binds a method-record revision to a
  benchmark context, anchored sources, benchmark quality, feasibility,
  convergence history, observed outcomes, and cost observations.
- `auto-g16-method-run-observation/1` stores a sanitized observation linked to
  method and result/calculation revisions. Raw Gaussian output, scheduler job
  IDs, hosts, credentials, and automatic retry authority are out of scope.
- `auto-g16-method-evidence-brief/1` binds the exact context and evidence
  revisions, explicit exclusions, query counts, permission-derived access, and
  per-method multidimensional summaries.

Every artifact has canonical JSON SHA-256 binding, explicit revision links,
review/access/provenance metadata, exclusions, and hard constants:
`calculation_ready: false`, `no_submission_authorization: true`,
`no_method_selection_authorization: true`, and
`no_approval_authorization: true`.

## Query and summary behavior

`method_evidence.py query` accepts one finalized context plus explicit
benchmark/run-observation paths. It validates hashes before use, filters by the
same offline principal declaration used by the knowledge store, and requires a
matching calculation family and target property. Other context fields determine
`direct`, `near`, or `indirect` chemical applicability without a composite
score.

`build-brief` keeps five independent dimensions:

1. chemical directness/applicability;
2. benchmark quality;
3. technical feasibility;
4. convergence history;
5. cost/resource observations.

The derived brief is never less restrictive than its accessible inputs.
Permission-denied evidence contributes only to a count and is not identified in
the report. Context exclusions retain exact artifact refs and reasons. If no
evidence matches, or any required dimension has no supplied observation, the
brief reports `insufficient`; unknown values remain `unknown`. A fully populated
brief may be `reviewable`, which means only that a human can review the five
dimensions. `method_selection.status` remains `not_performed`, and
`approval.status` remains `not_granted` in every case.

## Integration limits

This slice does not change reaction-workflow, RTwin/PBS, protocol approval,
input review, live approval, or result-acceptance gates. A later integration may
reference a reviewed evidence brief by exact hash, but must still request an
independent human method decision and all existing scientific approvals.
