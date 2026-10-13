# Auto-G16 v3 boundary: review

Component of [boundary-spec.md](../../boundary-spec.md); it retains that document's
authority and unchanged technical requirements. Read the selected component,
its cited dependencies and applicable Owner decisions together. Relocation
does not reopen historical permissions or replace a reviewed successor.

<!-- Moved from docs/v3/boundary-spec.md:1826-2113 at 394e88bbac54a15d42973cf8b607e515343b1814. -->

## V30-REVIEW-MIN-CONTRACT-01 Minimum ReviewBundle Contract

**Contract status: FROZEN CANDIDATE; IMPLEMENTATION NOT AUTHORIZED.** The
future public package is `auto_g16.review`, with focused tests under
`tests/v3/review/`. It owns only a deterministic human-review projection. It
may depend on public Core, Result, and ScientificValidation surfaces; it does
not import Execution merely to repeat snapshot semantics. No upstream package
imports Review. This contract changes no upstream API/schema and grants no
selector, implementation, persistence, acceptance, effect, retry, viewer, or
live authority.

### Exact public boundary

The public inventory is exactly:

```text
ReviewAcceptanceState
ReviewBundle
ReviewBundleError
build_review_bundle
render_review_bundle_json
```

`ReviewAcceptanceState` is exactly a `str, Enum` with
`INELIGIBLE = "ineligible"`,
`ELIGIBLE_UNACCEPTED = "eligible-unaccepted"`, and
`ACCEPTED = "accepted"`. It describes only what the exact supplied records
establish for this projection. It does not select an acceptance or perform an
acceptance operation.

`ReviewBundle` is exactly
`@dataclass(frozen=True, slots=True, kw_only=True, init=False)` with these and
only these public fields:

```python
schema_version: int
review_bundle_id: str  # init=False; deterministic UUIDv5
calculation_plan: Mapping[str, object]
attempt: Mapping[str, object]
input_binding: Mapping[str, object]
execution_snapshot_id: str
output_envelope: Mapping[str, object]
parse_outcome: Mapping[str, object]
selected_final_geometry: Mapping[str, object] | None
selected_frequency_blocks: tuple[Mapping[str, object], ...]
selected_frequencies_cm1: tuple[float, ...]
minimum_validation_outcome: Mapping[str, object]
minimum_validation_classification: MinimumValidationClassification
primary_reason_code: str
scientific_acceptance_state: ReviewAcceptanceState
scientific_acceptances: tuple[Mapping[str, object], ...]
```

Every mapping is a deeply immutable canonical semantic copy of the named
public record. `calculation_plan` has exactly `calculation_plan_id`, `task_id`,
`revision`, and complete `intent`; `attempt` has exactly `attempt_id`,
`task_id`, and `ordinal`. MinimumValidationOutcome and ScientificAcceptance
mappings preserve every public field of their exact typed source records,
using enum values and the complete expanded mappings already frozen by their
owner.

The InputBinding projection has exactly these 11 keys and no others:

```text
schema_version
observation_id
attempt_id
calculation_plan_id
calculation_plan_revision
prepared_input_binding_id
execution_snapshot_id
input_format
logical_name
sha256
size_bytes
```

`observation_id` is obtained from and must equal the exact validated typed
`InputBinding.observation_id`; the builder accepts no independent replacement
ID. Every other value comes from that same typed InputBinding.

The OutputEnvelope projection has exactly these 12 keys and no others:

```text
schema_version
observation_id
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

`observation_id` is obtained from and must equal the exact validated typed
`OutputEnvelope.observation_id`; the builder accepts no independent replacement
ID. `capture_status` and `capture_completeness` are their exact public enum
values. `artifacts` preserves the normalized typed-record order, and every
artifact mapping has exactly `artifact_kind`, `logical_name`, `sha256`, and
`size_bytes`. Artifact paths, mtimes, local source paths, and an added
capture/currentness field are forbidden. The exact persisted `captured_at_utc`
remains part of the upstream record and is neither replaced nor interpreted as
currentness.

The ParseOutcome projection has exactly these 10 keys and no others:

```text
schema_version
result_id
attempt_id
envelope_observation_id
parser_name
parser_version
result_kind
parse_status
facts
diagnostics
```

`result_id` is obtained from and must equal the exact validated typed
`ParseOutcome.result_id`; the builder accepts no independent replacement ID.
`parse_status` is its exact public enum value, `facts` is the already-frozen
public semantic mapping from that typed ParseOutcome, and `diagnostics`
preserves exact tuple order. Raw output, artifact bytes, parser-local prose,
and latest/current markers are forbidden.

These three mappings do not use `payload()` verbatim because those public
payload helpers intentionally omit the corresponding derived authority ID.
The builder starts with the complete typed public semantic fields, adds the
typed record's derived public ID, and fails closed if reconstruction/replay
does not reproduce that ID. No additional record-kind discriminator is added;
the enclosing ReviewBundle field determines the record type. No path, raw
output, artifact bytes, mtime, newly generated display timestamp, viewer state,
or private object is a bundle field.

The selected geometry and frequencies are byte-semantic copies of the exact
`selected_geometry_block`, `selected_frequency_blocks`, and
`selected_frequencies_cm1` already stored in the supplied
MinimumValidationOutcome. Review never calls a parser, reads a span from disk,
selects another geometry, shortens the complete frequency suffix, applies a
tolerance, or derives a new scientific fact. `primary_reason_code` is the exact
outcome `reason_code`, and `minimum_validation_classification` is its exact
classification.

The one builder signature is:

```python
build_review_bundle(
    core_store: SQLiteRuntimeStore,
    validation_store: SQLiteScientificValidationStore,
    *,
    input_binding: InputBinding,
    output_envelope: OutputEnvelope,
    parse_outcome: ParseOutcome,
    minimum_validation_outcome_id: str,
    scientific_acceptance_ids: tuple[str, ...] = (),
) -> ReviewBundle
```

The builder loads the exact persisted MinimumValidationOutcome and every
explicitly named ScientificAcceptance. It also loads the exact CalculationPlan
and Attempt and replays the persisted same-Attempt InputBinding, OutputEnvelope,
and ParseOutcome through public Core records. It requires the complete plan,
task, Attempt, InputBinding observation, envelope observation, Result ID,
parser tuple, and ScientificValidation policy bindings to agree. It requires
the one `execution_snapshot_id` in InputBinding and OutputEnvelope to agree and
projects that identity without reconstructing or authenticating an
ExecutionSnapshot. Missing, malformed, duplicate acceptance IDs, or any
cross-plan, cross-Task, cross-Attempt, cross-input, cross-envelope,
cross-Result, cross-policy, or cross-outcome splice raises
`ReviewBundleError` before a bundle is returned.

`ReviewBundleError` inherits `ValueError` and owns every invalid public input,
relationship/provenance mismatch, unsupported canonical value, forged bundle
identity, and rendering failure in this slice. There is no second public error
class and Review never translates an upstream record into a different upstream
error or status.

The explicit acceptance-ID tuple is a closed caller-supplied review set, not a
query or latest/current selector. The builder sorts its distinct loaded
ScientificAcceptance records lexically by `scientific_acceptance_id`. A
non-`VALIDATED_MINIMUM` outcome requires an empty set and projects
`INELIGIBLE`. A `VALIDATED_MINIMUM` with no explicit acceptance projects
`ELIGIBLE_UNACCEPTED`; one or more exact acceptances for that outcome project
`ACCEPTED`. Multiple acceptances remain separate complete mappings and no
winner, newest, preferred reviewer, or implicit revocation is inferred.

### Deterministic identity and rendering

Schema version is exactly `1`. The source-controlled Review namespace root is
`061dffea-e54e-580e-9928-e284abc0997f`. The only identity domain is
`review-bundle`, whose namespace is
`62e6a827-7dbf-5efe-8625-729e43bc9d46`, derived exactly as:

```python
uuid5(REVIEW_NAMESPACE, "auto_g16.review/v1/review-bundle")
```

`review_bundle_id` is UUIDv5 in that domain over every field above except
itself, with enum values substituted for enum objects. It uses the same frozen
tagged canonical-value grammar as the ScientificValidation public-shape
contract: distinct null/Boolean/integer/finite-float/string/mapping/sequence
tags, lexical mapping-key order, sequence-order preservation, and compact
UTF-8 canonical JSON. Review extracts that reviewed algorithm into one private
helper and imports no private Core, Result, ScientificValidation, Workflow, or
Execution helper. Exact replay gives the same ID; any projected source,
selected evidence, reason, classification, acceptance set, or acceptance-state
change gives a new ID. Unsupported values, non-finite numbers, cycles, or a
forged/stale identity fail closed.

The exact InputBinding, OutputEnvelope, and ParseOutcome mappings specified
above are the same semantic values used by both ReviewBundle UUIDv5 identity
and deterministic JSON rendering; Review maintains no separate identity-only
or render-only projection. Consequently, adding, removing, or changing one of
their derived authority IDs changes ReviewBundle identity. Caller mapping
insertion order does not change identity because canonical mapping keys are
ordered lexically.

The only public renderer is:

```python
render_review_bundle_json(bundle: ReviewBundle) -> str
```

It first recomputes the complete bundle identity and rejects drift. It renders
the exact complete public payload including `review_bundle_id` using
`json.dumps(..., ensure_ascii=False, allow_nan=False, indent=2,
sort_keys=True, separators=(",", ": "))` followed by exactly one LF. Output is
deterministic JSON text; when encoded as bytes its required encoding is UTF-8,
with no filesystem access, hidden field, prose inference, current-time value,
scientific recommendation, or authority flag. A renderer does not persist the
bundle, write a geometry file, open a viewer, or grant ScientificAcceptance.

The bundle itself is sufficient for v3.0 human review: the selected geometry
mapping contains exact ordered atomic numbers and Cartesian coordinates, and
the selected frequency evidence contains exact Result source bindings and
values. A later external-viewer adapter may transform this explicit geometry
projection under a separate gate. Viewer file generation, inferred bonds,
GaussView opening, SSH transfer, and load probing are not Review public APIs.

### Narrow reuse and ownership preparation

The reuse audit is limited to the public Core/Execution/Result and frozen
ScientificValidation shapes, the existing reaction-workflow review/projection
helpers adjacent to `calculation_artifacts.py`, and the
`auto-g16-view-rt-win` preview/GaussView handoff with its adjacent tests.

- **PORT:** public `CalculationPlan` and `Attempt` records, Result
  InputBinding/OutputEnvelope/ParseOutcome payloads, the frozen
  MinimumValidationOutcome and ScientificAcceptance records, and their exact
  append-only identities and source bindings. Only the ExecutionSnapshot ID
  already present in Result provenance is ported; no Execution internals are.
- **EXTRACT:** deeply immutable semantic projection, exact relationship replay,
  deterministic tagged canonical identity, stable JSON rendering, and the
  adjacent no-overwrite/non-authorizing review tests. Each extracted behavior
  receives Review-owned cross-splice and determinism tests.
- **WRAP:** a future explicitly authorized viewer adapter may consume the exact
  selected geometry projection and wrap the existing GaussView handoff. The
  wrapper remains outside Review authority and may not reinterpret geometry or
  make a calculation-ready artifact.
- **REWRITE:** the bundle builder and renderer are clean typed projections
  because legacy review/report helpers mix chemistry-specific policy, paths,
  hashes, mutable files, reviewer decisions, and `calculation_ready`/
  submission flags. Porting them would create a second authority and the wrong
  dependency direction.
- **DROP:** hash-currentness, file-path identity, implicit latest/current
  selection, favorable evidence selection, raw-log parsing, embedded approval
  or readiness decisions, effect flags, and any receipt/owner/capability
  governance as Review authority.
- **DEFER:** GUI, HTML/rich report, ReviewBundle persistence, geometry-file
  export, bond inference, normal-mode animation, external-viewer invocation,
  SSH/RTwin transfer, viewer load probing, TS/IRC/connectivity review, and all
  live work.

After this contract is integrated, `V30-VAL-REVIEW-01` may separately propose
one `affected / fail_closed=false` selector route for `auto_g16/review/` and
`tests/v3/review/`. The smallest expected evidence is `tests.v3.review`,
`tests.v3.scientific_validation`, `tests.v3.result`, and
`tests.v3.core.test_store`, retaining `no-overwrite` and
`unknown-no-automatic-retry`. Selector, test package, and product bytes are not
created by this contract candidate. Review implementation remains `WAIT` until
ScientificValidation implementation is integrated and a separate Owner Gate
opens.
