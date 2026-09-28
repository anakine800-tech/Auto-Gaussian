# Auto-G16 Gaussian successor result and Opt refinement handoff

Status: ACCEPTED for implementation and offline validation on 2026-09-28.
Owner accepted the independently reviewed proposal SHA-256
`fee8a9b8f1d6cfc4df1167055503e882fe561e7cb0e1c400d744574c588cafaa`
with “继续”. Integration base is main `0d40520097d50fe02d9f55bd0b0ba25201d92c7e`.
Only the status/authorization annotation changes the accepted proposal here.
Task: V31-GAUSSIAN-RESULT-REFINEMENT-01, OWNER-GUIDED, non-BUS.
Base: main `60f4686ce4ec2b594d689144084e8d0d1dd6deca`.
Owner requested completion of Q7 integration and successor result-to-refinement
handoff. Implementation permission for that outcome is retained; the exact
new record meanings and scientific-method interpretation below require the
existing contract acceptance gate before implementation.

## Outcome and scope

Close the offline path from an already persisted successful Gaussian successor
Attempt to source-attributed parsed facts, a bounded Opt geometry assessment,
and a revised ConformerEnsemble whose member lineage can be independently
replayed. Preserve old V30 records, IDs, parser grammar, scientific outcome
classifications and execution behavior. Do not manufacture V30 observations
or a V30 ExecutionSnapshot for a successor Attempt.

This slice supports the already selected closed-shell singlet, gas-phase
wB97XD/Def2SVP pure Opt case, with unchanged exact input bytes. It does not
select or execute new chemistry. Q7 adapter6 remains Opt-only. Freq execution,
minimum acceptance, populations, thermochemistry and TS/IRC are excluded.
Historical Gaussian adapter3/4/5 Opt captures may be read as source evidence;
they do not authorize a new run or inherit adapter6 resource semantics.

## Owning boundaries and dependency direction

1. Execution owns the native success proof and captured bytes. Extend the
   existing private historical receipt-source locator with a separate Gaussian
   selector and an exact supported tuple table. Preserve the existing immutable,
   no-follow, fixed-file, original-runtime and read-only store checks. Use the
   existing receipt success owner, not NativeQuery's display summary, a caller
   dictionary, a terminal log marker or a fresh live driver.
2. Result owns deterministic parsing and derived record grammar. Add a private
   successor provenance adapter; it must not import Execution or Transport.
   A composition function in the existing conformer boundary supplies data
   freshly obtained from the owning Execution reader and rechecks that source
   whenever producing a current refinement authority.
3. ScientificValidation owns interpretation. Extract/reuse its pure Gaussian
   fact/geometry checks behind a successor-specific private adapter. Keep the
   existing V30 public validator and outcome vectors unchanged. Result and
   Execution must not import ScientificValidation.
4. Conformer composes the owners and constructs a separately versioned native
   Opt authority. Extend the existing refinement dispatcher and geometry audit;
   do not add a parallel parser, execution engine or approval system.
5. Review/display can project these new derived records only through their
   owning validated reader. No read projection supplies execution or human
   scientific acceptance authority.

## Closed source and derived records

Use existing Core Observation/Result append-only storage, not a schema migration
or new execution-domain record. All added records are explicitly V31-private;
existing `v30-result-*` record meanings and identifiers are unchanged.

A source Observation has type/schema `v31-gaussian-result-source/1`. Its
canonical payload must contain exactly:

- `schema`, `attempt_id`, `calculation_plan_id`, `calculation_plan_revision`;
- `program_execution_snapshot_id`, `snapshot_payload_sha256`,
  `effect_intent_id`, `program_execution_spec_id`, `spec_payload_sha256`;
- `terminal_success_authority_id`, `completion_result_id`,
  `completion_result_payload_sha256`, `capture_authority_id`,
  `assessment_observation_id`, `receipt_sha256`, `epoch_id`;
- `input` and `log`, each containing `logical_role`, `portable_name`, `format`,
  `sha256`, `size_bytes`, and its exact stage/fetch observation identity
  respectively (`stage_observation_id` for input and `fetch_observation_id`
  for log); the full bytes remain in the original owning capture.

The identity is the existing canonical semantic-ID derivation under the new
`v31-gaussian-result-source` domain. Reject duplicate/extra keys, mismatched
Attempt/plan/spec/snapshot/input/log/capture, missing or incomplete source,
non-Gaussian inputs, unknown tuples, and any mixed V30/successor records for
the same Attempt. No current target observation is required for historical
reading; original source qualification remains explicit.

A derived Result has type/schema `v31-gaussian-parsed-result/1`, with exactly
`schema`, `attempt_id`, `source_observation_id`, `source_payload_sha256`,
`parser_name`, `parser_version`, `result_kind`, `parse_status`, `facts`,
`diagnostics`. Its semantic ID uses domain `v31-gaussian-parsed-result`.
Reuse GaussianJobParser's exact-byte grammar and spans. An ephemeral parser
artifact/envelope representation is only a parsing carrier: do not persist it
as a V30 capture or use it to assert execution provenance. Every result source
span must resolve to the same bound log bytes and source observation; any
necessary parser carrier identity is deterministic and derived from this
source, never caller supplied. A parsed result is not a scientific acceptance.

The owning composition writer explicitly appends only the source Observation
and derived Result to a selected destination native Core store containing the
same Attempt and plan. It never opens a private store implicitly, changes Core
Attempt state, creates an execution intent or invokes Transport. Exact replay
is idempotent; differing source/result records are never overwritten. Source
inspection and current authority reconstruction are zero-write operations.

## Opt assessment and member lineage

A private `v31-conformer-successor-opt-authority/1` payload binds the exact
ensemble/member and their payload hashes; source Observation and parsed Result
IDs/hashes; source geometry/atom order/map/stereochemistry; plan/input;
method identity; selected final geometry with log spans; optimization and
stationary-point spans; and a bounded assessment. Recompute its semantic ID
and re-read its source records rather than accepting a caller's claimed PASS.
Reacquire proof/capture from the owning Execution reader, rerun the fixed
Result parser on those bytes, and compare the complete canonical derived
payload including every fact, diagnostic and span. Then rerun the SV
assessment and compare its complete canonical payload. A stored result with
a valid self-hash is insufficient; rehashed forged facts must fail.

For the positive Opt geometry path require one normal termination, zero error
termination, a complete accepted optimization convergence table, stationary
point evidence, selected final geometry, exact atom inventory/mapping and no
frequency section. Connectivity and stereochemistry continue through the
existing ensemble audit. Geometry convergence is not a minimum: its scientific
classification remains INCOMPLETE with reason `incomplete-mode-count`; no
ScientificAcceptance or thermodynamic eligibility may be created.

Missing success proof or required capture rejects source/derived record and
authority creation. Only a complete authenticated capture whose content is
truncated, unsupported or scientifically invalid may produce a typed negative
or incomplete assessment with source provenance; it yields no positive geometry
member. Native completion success does not override parser or geometry failure.
A completed program with an invalid scientific result retains its existing
Core state and receives separate scientific evidence.

The new authority has its own versioned source/assessment fields. It must not
populate the legacy `v30_outcome` field with a fabricated record. The existing
V30 refinement authority and callers remain unchanged; dispatch explicitly
by the new native variant and reuse geometry/deduplication helpers.

## Method contract delta

Introduce a new explicit refinement route/method variant for the previously
approved wB97XD/Def2SVP, gas-phase, charge0/multiplicity1 Opt case. Bind restricted
closed-shell identity and intrinsic wB97XD dispersion explicitly; no separate
dispersion addition. Preserve the exact approved Opt/SCF/grid/NoSymm tokens and
input Link0 bytes. Do not generalize the method regex, infer unrestricted states,
change the user's method, infer solvent or create a default.

The old route contract retains RHF/RB3LYP behavior and all existing identities.
No Freq/minimum/thermal promotion follows from this new Opt-only variant.


## Exact v1 closure rules

### Historical source tuples

The program and adapter ID are exactly `gaussian` and
`auto-g16-v31-gaussian`. The only admitted adapter/material/prebinding/Q suffix
combinations are `(3,5,6,4)`, `(4,6,7,5)`, `(5,7,8,6)` and `(6,8,9,7)`, using
`v31-completion-rendering-material/N`, `v31-completion-prebinding/N` and
`auto-g16-v31-publisher-qualification/N`. Each uses its original owning
module's frozen contract hash, bootstrap source identity, profile validation,
and recorded runtime qualification; tuple membership alone is not proof.
Adapter6 is available only after reviewed Q7 source integration. Unknown or
cross-combined tuples reject. A separate private Gaussian locator cannot fall
back to the xTB or CREST locator. Synthetic Gaussian sources are allowed only
through the existing explicitly inert test qualification, never a real-path
fallback. The parser tuple for new derived records is exactly
`(auto-g16-v3-gaussian-job, 1.1.0, gaussian-job-facts)`.

### Destination and partial-write recovery

The source Core and Transport databases and their bytes remain immutable.
The destination must be an explicitly supplied distinct native Core store;
reject the same connection, same canonical path, symlink alias, or identical
file `(device,inode)` to either source. Recheck physical identity before and
after writes using existing no-follow owners. Do not initialize or clone a
source implicitly. Compare full persisted Project/Task/Attempt ownership,
CalculationPlan revision/content, generation, and exact ProgramExecutionSpec
and Snapshot identity with the source, not just UUID strings. Destination
ownership must already exist; this writer cannot manufacture execution history.
Its execution state is not source authority and is never changed here.

Before either append, validate both deterministic payloads and all destination
conflicts. Existing identical source/result records are reused. A crash after
only the source Observation has durably appended leaves a non-authoritative
partial pair: a later explicitly invoked identical import revalidates original
proof/bytes and appends only its exact missing Result. A Result without its
matching source, different result/source for the same import, or mixed V30
result/execution bindings rejects without repair or overwrite. Readers reject
partial pairs. This recovery is local append completion, not execution replay.

### Closed authority and assessment

The authority fields are exactly `authority_schema`,
`optimization_geometry_authority_id`, `source`, `method_id`, `method_binding`,
`calculation_plan`, `input`, `result_source`, `parsed_result`, `selected_geometry`,
`recovered_atom_map`, `assessment`.

- `source` uses the existing `_SOURCE_KEYS` and `_source` values from
  `conformer/refinement_authority.py` unchanged.
- `method_binding` has the exact existing `_METHOD_KEYS`, with only the new
  values specified below; `method_id` is SHA-256 of the canonical payload
  `{domain: v31-conformer-successor-opt-method/1, method: method_binding}`.
- `calculation_plan` has exactly `calculation_plan_id`, `revision`,
  `payload_sha256`; its hash covers the complete owning canonical plan.
- `input` equals the full source Observation's input descriptor.
- `result_source` has exactly `observation_id`, `payload_sha256`.
- `parsed_result` has exactly `result_id`, `payload_sha256`.
- `selected_geometry` is the existing Gaussian parser geometry fact, including
  its unchanged source-span grammar, or null for no usable geometry.
- `recovered_atom_map` uses the existing canonical member atom mapping, or
  null if recovery fails; it must be derived from exact inventory/order checks.
- `assessment` has exactly `classification`, `reason_codes`,
  `geometry_disposition`, `optimization_spans`, `stationary_point_spans`.
  Span arrays reuse the parser's closed span grammar and are fully replayed.
  `classification` uses existing SV classifications. Positive geometry requires
  `INCOMPLETE`, reason `incomplete-mode-count`, and `geometry_disposition`
  `accepted_opt_geometry`; other cases have `rejected_opt_geometry`, null
  unusable geometry/map, and the exact recomputed existing SV reason codes.

The authority schema is `v31-conformer-successor-opt-authority/1`; its ID is
SHA-256 over the canonical object `{domain: authority_schema, payload: P}`,
where P is the complete authority minus `optimization_geometry_authority_id`.
No claimed field or recomputed ID substitutes for original-proof/parser/SV
replay. Invalid source identity rejects before scientific classification.

### Exact method variant

All `_METHOD_KEYS` are mandatory. Values are `program=gaussian16`,
`method=wB97XD`, `basis=Def2SVP`, `dispersion=intrinsic_wB97XD`, `solvent=gas`,
`reference=restricted_closed_shell`, integer `charge=0`, integer
`multiplicity=1`, `integration_grid=UltraFine`,
`scf_policy=Tight_MaxCycle128`,
`route_contract_version=auto_g16_v31_successor_opt_route_1`.
The exact route is
`#p wB97XD/Def2SVP Opt=(MaxCycles=128) SCF=(Tight,MaxCycle=128) Integral=UltraFine NoSymm`.
Validate the actual bound input, charge/multiplicity and reviewed species,
including electron parity and output reference/charge/spin facts. This adds
no input renderer or new approval. Existing input bytes, Link0 and approved
resource binding remain exact; the old method variant is untouched.

### Opt-only member and ensemble semantics

Add a separately selected private Opt-only refinement entry point; retain the
old two-stage builder's requirement for a Freq disposition. For each selected
member require exactly one recomputed positive or negative Opt authority.
Unselected members retain coordinates and provenance and have explicit
`post_dft_status=optimization_pending`; this permits anti-first retention
without pretending gauche was processed. Require at least one selected member.
Surviving accepted Opt geometries have
`post_dft_status=optimized_frequency_pending`,
`post_dft_minimum_evidence_available=false`, `two_stage_minimum_authority=null`,
and `negative_frequency_authority=null`. Failed, identity-rejected and duplicate
members use the existing respective statuses and retain negative evidence.
Never fall through to `validated_minimum` for this variant.

Run existing connectivity/stereochemistry audit and mapped-RMSD dedup only on
accepted optimized geometries with matching method; unprocessed geometries
cannot be asserted to be post-Opt duplicates. Preserve the source coverage
object unchanged: sampling coverage never becomes DFT or Freq coverage.
The new revision's `thermodynamic_eligible_members` and `ts_seed_members` are
empty. Member audit entries record pending/processed disposition and source
IDs; an Opt-only revision cannot issue ScientificAcceptance or population data.
A later separately authorized Freq integration must replay these sources;
it is outside this contract. Old ensemble schema and old member payloads are
not rewritten. New fields/statuses live only in this explicitly selected
private refinement variant of the existing immutable ensemble revision.

## Acceptance and validation

- Positive chain: native persisted success/capture -> new source/parsed record
  -> current Opt geometry authority -> refined ensemble member; fresh-process
  replay yields the same identities with zero wire calls and source writes.
- Adversarial: swapped members, inputs, logs, snapshot/plan/spec/capture IDs,
  forged success/parsed facts, partial/missing output, unknown parser tuple,
  changed artifact bytes/spans, mixed generations, repeat/conflicting writes,
  connection/geometry/stereochemistry drift and unsupported method all reject
  or remain explicitly incomplete. Core state and original stores are unchanged.
- Compatibility: historical V30 and xTB/CREST identities and read paths remain
  unchanged; existing Gaussian parser, SV, Review, conformer and thermochemistry
  tests pass. Q7 support is checked after integration without broadening /6.
- Use synthetic fixtures and already-retained real outputs for offline evidence.
  Do not submit a job merely to test ingestion. Reuse closed target evidence;
  any new native filesystem-safety claim needs its own applicable evidence.
- Record exact base/head, focused/affected results and independent review;
  honor selector ownership and complete-full deduplication.

## Allowed implementation paths and release boundary

After exact acceptance: existing owning modules under `auto_g16/execution/`
(historical reader only), `auto_g16/result/`, `auto_g16/scientific_validation/`,
`auto_g16/review/`, `auto_g16/conformer/`, their focused tests, and owning contract,
acceptance/context-map/validation routing documents. No Core schema, transport
operations, live publisher/submit code, frontend, native production activation,
server paths, cleanup, UNKNOWN disposition or actual scientific approvals change.
Default repair budget is four cycles/30 active minutes for an ordinary offline
failure, with the existing halt/escalation policy. Implementation and validation
remain authorized once this exact contract is accepted; do not request those
same steps again. Publication/merge scope for this new feature is recorded
separately from step1's already authorized PR188 integration.
