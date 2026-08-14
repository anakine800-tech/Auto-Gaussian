# Auto-G16 v3 Owner Decisions

These decisions close the design questions accepted in Phase 0 and Phase 0.6.
They govern v3 planning until changed by a later reviewed Git commit.

## OD-01: Clean core and compatibility

v3 deliberately breaks v2 runtime compatibility. It is a clean-core,
selective rewrite: reuse is decided capability by capability, and preserved
data does not imply preservation of the v2 runtime ABI.

## OD-02: Semantic approval and edited inputs

Approval applies to the current `CalculationPlan` and its displayed meaning.
Manual editing of an input file is valid. After an edit, the controller must:

1. parse the current file again;
2. display the semantic diff;
3. obtain approval for the current `CalculationPlan`.

A hash may record artifact identity, but it is not a lock on an earlier
approval. v3 does not add a new hash-bound owner-approval mechanism.

## OD-03: Mutable profiles and execution snapshots

`ServerProfile` is mutable configuration. Every execution produces an
`ExecutionSnapshot` that captures the effective execution inputs for that
run. Review targets current semantics; the snapshot records what was used.

## OD-04: Project reuse and the no-overwrite boundary

An existing `Project` directory may continue to be used. The no-overwrite
boundary is a new `Attempt`; it does not require the entire `Project` to remain
forever fresh. A new execution must allocate a new `Attempt` and must not
overwrite a prior attempt's artifacts.

## OD-05: Single submission and uncertainty

Each `Attempt` may invoke `qsub` at most once. An ambiguous submission becomes
`UNKNOWN` / `submission_uncertain` and enters reconciliation. It must never be
retried automatically.

## OD-06: Transport targets

Direct SSH is the v3.0 transport target, implemented behind a new thin
`OpenSSHTransport`. It does not inherit the old single-use capability or
private owner-chain architecture. The legacy RTwin path remains an adapter and
a reuse source for existing operation. Live deployment always requires
separate, explicit authorization.

## OD-07: Safety semantics and governance implementation

v3 keeps reviewed execution-safety semantics while separating them from the
old governance implementation. Safety requirements are expressed at the v3
core and boundary level; the old governance machinery is not the v3
architecture.

## OD-08: Runtime and change-aware CI

The controller requires Python 3.11 or newer. Python 3.13 is the primary
full-validation runtime. Python 3.11 and 3.12 run compatibility and affected
tests by default instead of duplicating the complete full suite. CI is
change-aware and expands only when the affected surface requires it.

## OD-09: Conformer policy must be benchmarked again

v3 may extract existing conformer-science primitives, but sampling, coverage,
and DFT policy must be benchmarked again. Historical A/B route quotas are not
permanent scientific rules.
