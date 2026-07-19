# Auto-G16 reaction thermochemistry readiness contract

## Scope

`gaussian-reaction-thermochemistry-readiness-audit/1` is an immutable blocker
audit, not a thermochemistry comparison. The tool invokes public owner
validators for supplied artifacts and reports which owner contracts are still
missing. It performs no energy arithmetic and has no formal barrier success
state.

Minimum evidence explicitly dispatches by schema to
`gaussian-scientific-maturity-gate/1` or `/2`. Successful `/1` replay always
produces `minimum_owner_evidence_v2_required`. Successful `/2` replay consumes
each supplied `gaussian-minimum-lineage-handoff/2` through its public owner;
only minima lacking an exact replayed candidate/endpoint-to-input/job/attempt/
receipt/fetch/result lineage produce
`minimum_candidate_input_result_lineage_unavailable_v2`. Neither version grants
comparison or submission authority.

The TS readiness slice requires both a validated
`gaussian-calculation-attempt-link/1` and a validated
`gaussian-ts-irc-path-acceptance/2`. New evidence uses `/2`, replayed
through `ts_irc.validate_path_acceptance_v2_artifact`, including exact
mechanism study/edge, family, mode, direction endpoint execution lineage,
charge/multiplicity and stable atom-element mapping. Historical path acceptance
or endpoint review `/1` is replay-only compatibility and always emits a
`path_acceptance_v2_required` blocker. The two chains must bind the same exact TS-result hash.
Attempt-link-only evidence remains a blocker.

`gaussian-energy-lineage/1` is replayable but remains electronic-only. It does
not supply the exact owner mappings needed for ZPE, thermal correction,
enthalpy, raw Gibbs, quantity identity, unit, temperature, `1M` standard state,
solvent, or SP//geometry lineage. No current public owner validates an approved
per-species low-frequency policy application. Consequently treated Gibbs and
all formal barriers remain unavailable.

## Input and path contract

The closed readiness request binds at most one artifact for each role:
minimum evidence, TS attempt, TS path acceptance and energy lineage. Each
binding carries a package-relative path, file SHA-256, byte size, schema and
payload SHA-256. Role and schema are fixed by code; the request cannot select a
validator implementation or supply authoritative cached facts.

Every owner-internal reference is also interpreted relative to the explicit
readiness package root. Absolute paths, `..`, root escape, symlink components
and hash drift are rejected before owner replay. This is an intentionally
stricter packaging prerequisite for the new audit. A legitimate historical
artifact whose internal paths use another convention must be copied into a new
reviewed package and rebuilt by its existing owner builder with package-relative
bindings. The readiness audit does not rewrite it, approve it, or grant the old
artifact any new meaning.

Synthetic integration tests invoke the current scientific-maturity and
calculation-attempt builders and first prove that their public owner validators
accept the generated artifacts. They then prove that older nested absolute or
owner-relative provenance does **not** satisfy the readiness package-root
namespace. Those fixtures therefore require an owner-controlled rebuild or
repackage before they can be included in a readiness audit. The tests do not
pretend that ordinary historical output already meets the new packaging
contract. The audit records the actual validator implementation used; no
caller-reported validator ID is accepted.

## Immutable output and authority

The builder serializes to a same-directory temporary file, flushes it, then
publishes with an atomic hard link. An existing target and concurrent second
writer are never overwritten. Validation rebuilds the complete audit from the
hash-bound request and repeats every owner replay.

The output contains only owner replay records and structured blockers. It
always sets:

- `formal_comparison_ready: false`
- `formal_barrier_available: false`
- `arithmetic_performed: false`
- `calculation_ready: false`
- `no_submission_authorization: true`

It does not validate a method, accept a reaction path, change scientific
maturity, authorize a Gaussian input or submission, or interpret FF/xTB as a
formal energy source. It never uses SSH, PBS, Gaussian, or a live service.

## Future comparison requirements

A separate comparison feature should not be introduced until a positive
synthetic chain closes all of the following through real public owner
validators:

- minimum owner-evidence maturity `/2`, including conformer and electronic-state
  ownership;
- exact TS/Freq/mode/bidirectional-IRC ownership sharing one TS-result hash;
- complete per-species electronic, ZPE, thermal, enthalpy and raw-Gibbs
  quantity/context mappings;
- exact reviewed low-frequency policy and application records for treated
  Gibbs;
- complete selected minima, TS and component/free-species coverage;
- one exact common composition/reference inventory and catalyst-regeneration
  relation.

Only then may a separate comparator implement
`sum(activated terms) - sum(reference terms)` and distinguish local from
apparent barriers. This audit neither implements nor authorizes that arithmetic.
