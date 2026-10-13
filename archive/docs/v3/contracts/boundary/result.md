# Auto-G16 v3 boundary: result

Component of [boundary-spec.md](../../boundary-spec.md); it retains that document's
authority and unchanged technical requirements. Read the selected component,
its cited dependencies and applicable Owner decisions together. Relocation
does not reopen historical permissions or replace a reviewed successor.

### Companion sections

The retained text uses directional references from the original combined
document. Read the applicable linked sections with this component; these
links preserve the existing dependencies and successor relationships.

- [Additive Gaussian job attribution contract](result-attribution.md#additive-gaussian-job-attribution-contract)

<!-- Moved from docs/v3/boundary-spec.md:539-685 at 394e88bbac54a15d42973cf8b607e515343b1814. -->

## V30-RESULT-01 Frozen Result Provenance Contract

**Contract status: FROZEN; IMPLEMENTATION INTEGRATED ON
`main@2911451eb91a63c4c1df7601b4ac49610b6205a3`.** The public package is
`auto_g16.result`; focused tests belong under `tests/v3/result/`. It may depend
on `auto_g16.core`, but not live Transport, PBS, or RTwin, and it does not
change the Core schema. The only legal append-only chain is:

```text
CalculationPlan
→ Attempt
→ exact input-binding Observation
→ program-output-envelope Observation
→ Result
```

Ownership is resolved only through `Project -> WorkflowRun -> Task -> Attempt`;
provenance payloads do not copy a second ownership truth. The exact
CalculationPlan must bind the Attempt through the frozen Core relationships.
Directory names, mtimes, current filenames, cross-Attempt joins, and
cross-capture joins are not provenance authority.

### Deterministic record identities

Each record type uses a source-controlled, domain-separated UUIDv5 namespace;
a caller cannot choose a namespace or identity. The canonical tuples are:

```text
input-binding Observation = uuid5(
  NS_INPUT_BINDING,
  canonical(
    attempt_id,
    calculation_plan_id,
    calculation_plan_revision,
    prepared_input_binding_id,
    execution_snapshot_id
  )
)

output-envelope Observation = uuid5(
  NS_OUTPUT_ENVELOPE,
  canonical(
    attempt_id,
    input_binding_observation_id,
    capture_source_id,
    capture_manifest_sha256,
    capture_completeness
  )
)

Result = uuid5(
  NS_PARSED_RESULT,
  canonical(
    envelope_observation_id,
    parser_name,
    parser_version,
    result_kind
  )
)
```

Exact replay produces the same identity. A new capture source or manifest,
capture completeness, parser name/version, or result kind produces the
corresponding new identity. Timestamps do not participate. The same identity
with different content is a Core conflict and cannot be evaded with another
caller-chosen ID.

The input-binding Observation payload has mandatory semantics
`schema_version`, `attempt_id`, `calculation_plan_id`,
`calculation_plan_revision`, `prepared_input_binding_id`,
`execution_snapshot_id`, `input_format`, `logical_name`, `sha256`, and
`size_bytes`. It records one exact durable input binding; it authorizes neither
execution nor scientific acceptance.

Each `OutputArtifact` has mandatory semantics `artifact_kind`, `logical_name`,
`sha256`, and `size_bytes`. Artifact kinds are allowlisted, and a local
absolute path is not portable identity. The output-envelope payload has
mandatory semantics:

```text
schema_version
attempt_id
input_binding_observation_id
execution_snapshot_id
capture_source_id
capture_sequence
capture_status
capture_completeness
artifacts
capture_manifest_sha256
captured_at_utc
```

`capture_completeness` is exactly `partial` or `complete`; partial capture is
never promoted to complete. `capture_status` expresses capture-layer fact only
and does not replace Core runtime state. A caller- or owner-issued `capture_id`
is not authority; the frozen tuple uses the resolved `capture_source_id` and
exact capture manifest.

The Result payload has mandatory semantics `schema_version`, `attempt_id`,
`envelope_observation_id`, `parser_name`, `parser_version`, `result_kind`,
`parse_status`, `facts`, and `diagnostics`. `parse_status` supports exactly the
frozen outcomes `parsed`, `partial`, `unparseable`, and `unsupported`. Facts
are program/output facts, not scientific acceptance, and a parser cannot
modify Attempt state or complete facts across captures.

### Envelope, parsing, and durable views

Malformed envelope metadata or relationships are provenance-boundary invalid:
they produce diagnostics but are not persisted as a legal envelope. By
contrast, a valid envelope with exact captured-byte identities remains legal
when a parser cannot interpret the program output. The envelope is preserved
and a Result records the explicit `unparseable` or `unsupported` parse outcome;
this is neither execution failure nor scientific rejection. A partial capture
remains explicitly partial and is never treated as complete.

These are all legal durable prefixes:

```text
Attempt only
Attempt + input binding
Attempt + input binding + partial envelope
Attempt + input binding + complete envelope
Attempt + input binding + envelope + parse outcome
```

Readers distinguish `awaiting-input-binding`, `awaiting-capture`,
`capture-incomplete`, `awaiting-parse`, `parsed`, `unparseable`, and
`unsupported`. Missing later records are explicitly incomplete, not failure
and not permission to synthesize a record.

Captures, envelopes, and parser Results are append-only. One Result binds one
exact envelope; no fact or provenance is spliced across captures, and new
captures or parser versions never overwrite history. The current view resolves
the Core ownership relationships, selects the latest legal complete capture by
deterministic Core insertion order, or the latest partial capture when no
complete capture exists while marking it incomplete. It exposes all prior
captures and Results plus the selection reason. Filesystem mtime and scan order
never select the current view; runtime status comes from Core, not the parser.

Result creation and reading never advance or reconcile Attempt runtime state,
infer execution success or failure, or grant retry authority. Program status,
capture completeness, parse status, Result existence, and scientific
acceptance remain separate facts. Minimum, transition-state, IRC, workflow,
and other scientific acceptance require a later independent review. Core API
and schema remain unchanged.

<!-- Moved from docs/v3/boundary-spec.md:1302-1355 at 394e88bbac54a15d42973cf8b607e515343b1814. -->

### Composite internal-step Gaussian job successor

The additive successor retains the public `GaussianJobParser` name and
`gaussian-job-facts` kind but freezes a new exact tuple and grammar:

```text
parser_name    = auto-g16-v3-gaussian-job
parser_version = 1.1.0
result_kind    = gaussian-job-facts
grammar_id     = auto-g16-v3-gaussian-job-grammar/2
```

The existing `1.0.0` tuple remains bound only to grammar-1. Both tuples use
outer `ParseOutcome` schema version 1, coexist append-only for one envelope,
and retain distinct deterministic Result identities. No old outcome is
migrated, reinterpreted, overwritten, or backfilled.

Grammar-2 admits exactly one external `JOB_START`. It rejects a second
external `JOB_START` and `LINK1_LITERAL`. An internal step is an exact
`Proceeding to internal job step number N.` marker, optionally with the
Gaussian-emitted `Link1:` prefix; the first `N` is 2 and later values must be
3, 4, and so on without gaps, repeats, or decreases. An internal step may
start only after the preceding component's exact normal terminal and never
after an error terminal. The parser must close every component and the final
component before returning `PARSED`.

At parser top level, an exact `GRAD_BOUNDARY` is a structural separator within
the same external invocation and emits no scientific fact. The same anchor in
an unfinished optimization, frequency, geometry, or other admitted child
production fails under that child production. It is never a free wildcard.

`job_section` spans the complete external invocation through the final
terminal. `termination_evidence` contains every physical terminal item in
strict byte order; the normal and error counts equal those exact items. Overall
`normal-termination` requires one or more terminal items, all normal, a closed
contiguous internal-step chain, no error item, and a final normal terminal.
Any error item yields `error-termination` and forbids continuation. Extra or
unexplained terminals are unparseable.

The existing optimization, stationary, geometry, and frequency fact shapes
remain unchanged. ScientificValidation dispatches on the complete tuple.
Grammar-1 retains its singular terminal rule and final-pair selection.
Grammar-2 requires an all-normal terminal sequence and chooses the rightmost
closed optimization/stationary pair whose stationary span ends no later than
the first attributed frequency block. The unique rightmost complete geometry
before that optimization span and the complete ordered frequency-block suffix
after that stationary span are then evaluated under the unchanged nonlinear
minimum policy. A frequency block with no preceding closed pair is
`INCOMPLETE`; no raw bytes are reopened by ScientificValidation.

This successor changes no public fact field, Core/Result schema, validation
classification, reason vocabulary, acceptance record, execution authority, or
live boundary.
