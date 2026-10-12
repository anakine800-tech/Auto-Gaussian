# Auto-G16 direct study local creation and historical reuse /1

Continuation of BUTANE-RELIABILITY-UNIFIED-E2E-01, explicit Owner instruction
2026-10-12: implement through same-scope pass, retain evidence, no duplicate
calculations. No remote effect, installation, scientific recomputation, result
republication, commit or merge. This appendix narrows the approved D direction
and replaces the unfrozen D0 per-record disk-write design with one immutable
native Core snapshot publication. It does not freeze a live run command.

## Exact input and identity

`python -m auto_g16.study {create,review,status,query,audit,recover,run}`.
create takes --directory ABS --request ABS --sha256 HEX. Other commands take
--directory ABS only. No environment loading, module/plugin/script handler,
command or shell inputs. run always rejects execution-contract-not-frozen with
zero effects. Local startup paths are trusted operator inputs, never HTTP input.

Request JSON (duplicates, extra/missing fields, nonfinite values rejected) is
exactly {schema,creation_key,title,initial_xtb,catalog}; schema
`auto-g16-direct-study-request/1`. creation_key is explicit UUID (different keys
remain different studies); title nonempty <=200 characters. initial_xtb exactly
{input_sha256,charge,multiplicity,cores,memory_mb,walltime_seconds,queue}; initial
values explicit, no defaults or method inference. catalog is an exact physical
file binding {path,parent_chain,file_identity,sha256,size_bytes}. Input cap 1 MiB.

UUID5(creation_key, fixed role) preallocates Project, WorkflowRun, and each of
xtb,crest,anti_opt,anti_freq,gauche_opt,gauche_freq,thermochemistry,populations
stage identity slots. Only xtb initially materializes unbatched Task, revision1
CalculationPlan intent (explicit request fields plus mode historical-reuse),
ResourceSpec and ordinal1 PLANNED Attempt. Core Project and WorkflowRun are new.
No downstream executable plans or approvals are invented. Catalog source
Attempts/Results are external historical associations, never rewritten or
imported as results of the new PLANNED Attempt. Query reports historical-reuse
and distinguishes new request IDs, historical source IDs and downstream slots.

## Local persistence

Caller supplies an existing empty dedicated directory. Open its full component
chain O_DIRECTORY/O_NOFOLLOW, record dev/inode, hold directory flock (exclusive
create, shared reads; nonblocking busy error), validate all identities before
and after each operation. Every created file is relative to held directory fd,
O_EXCL/O_NOFOLLOW, one-link regular file, fsync file and directory, exact readback.
No overwrite, rename, unlink or truncation. All files bounded; reject unknown
names, symlink/hardlink/nonregular files, partial files or physical replacement.

Closed ordered journal files: 0001-intent.json, 0002-core.json,
0003-complete.json. Events exactly {schema,sequence,previous_sha256,kind,data},
schema auto-g16-direct-study-event/1, previous hash null only for1.
INTENT data exactly {request,request_sha256,directory_chain,identities}; contains
all deterministic IDs before any Core persistence. CORE data exactly
{path,sha256,size_bytes,file_identity,records}; path is core.sqlite3; records are
six expected native record IDs and canonical field hashes. COMPLETE data exactly
{request_sha256,core_sha256}. Full event canonical bytes validated and sequence
strict. No other event kind/extra file accepted; unknown/corrupt evidence fails
closed and is retained.

Create the six records through existing public Core store methods in a NEW
in-memory SQLiteRuntimeStore, export via a narrow new public Core
`export_memory_snapshot()` owner method: only idle, memory-only main, valid
schema and foreign keys; returns bytes, no filesystem or database mutation.
Publish core.sqlite3 once; after restart it is opened only through native
SQLiteRuntimeStore.read_snapshot and compared to all expected model values,
PLANNED state and no observations/results/submission intent. The Core bytes
are immutable after publication. No disk constructor is used on existing data.

Default recover/status/review/query/audit never writes. Recover validates strict
journal prefix and existing Core snapshot. It reports initializing,
local-created, initialization-unresolved or invalid-evidence. Exact repeated
create may add only missing declared COMPLETE/CORE events or missing core bytes
if the intent is intact and current existing bytes/records exactly match the
expected in-memory image. It never replaces a partial/corrupt/foreign file.
Unknown partial INTENT itself requires retained evidence and operator action.
Absent core after a saved CORE event, changed core identity or content, terminal
new Attempt or changed request rejects. Repeated complete create is zero-write.
Readers publish output only after directory/pin/owner exit checks succeed.

## Historical catalogue and composition

Catalog schema `auto-g16-direct-study-catalog/1`, exactly {schema,stages,
frequency_readout,thermodynamic_readout,population_readout}. Each readout is an
exact physical file binding loaded only by its native owning loader. Stages are
exact ordered six entries xtb,crest,anti_opt,anti_freq,gauche_opt,gauche_freq;
each exactly {stage,database,snapshot}, both exact physical bindings. Every
source is pinned throughout query and checked on exit. Snapshots are
ProgramReadSnapshot, never executable snapshots. Six unique Attempts and
matching xtb/crest/gaussian adapter semantics required. Native Query/Program
readers verify original Core/receipt/Result associations; frequency/readout
owners verify Gaussian Opt→Freq and thermo/populations provenance. Core stage
Project topology is returned as historical and must not be rebased to newProject.
Catalog initial xTB snapshot input hash and resource fields must match request.
Every stage must have its original SUCCEEDED state and captured collected
lifecycle to qualify as historical-reuse-complete. xTB/CREST inventory is
historical completion evidence, not a newly performed conformer search.

Query invokes native owners for six stages and the registered pair, returns
saved scientific values and public sources without re-derivation. Audit adds
request/catalog/journal/record/source hashes and identity mapping; it does not
invent physical chronology or infer upstream atom mapping. If original native
owners cannot prove a cross-program predecessor edge, expose it as
unverified-historical-edge, never all-stage causal-chain accepted. Native Opt→Freq
and thermo source relations remain verified by their existing owners. No query
can promote new Core state, issue scientific acceptance or claim fresh execution.

Result envelopes exactly {schema,command,study_id,request_sha256,status,data},
schema auto-g16-direct-study-response/1. Local complete means local-created;
scientific source query uses historical-reuse-complete only when all owned
stages and saved results validate. It always reports execution_performed=false,
new_attempt_state=PLANNED, fresh_execution_e2e=false. Scientific acceptance
remains unavailable. Failures return nonzero with stable errors, no partial data.

## Acceptance

Closed malformed requests/catalogs, duplicate IDs, wrong hashes/resources,
wrong source membership, physically replaced/symlink/hardlink files, source
mutation at exit, journal tamper/gaps/conflicts and unknown files fail closed.
Actual child-process termination before/after intent/Core/core-event/complete
publication; fresh default recovery zero writes; explicit exact create only
fills provable missing suffix; repeated create/query/recover preserves identities
and zero submit. Real concurrent process lock must refuse busy without effects.
Read commands forbid Core writes (except native owners' precise memory replay
initialization), builders, savers, execution, subprocess and network. Actual
historical sources are outside Git. One new local Project/CalculationPlan is
created through the same package CLI used in tests, without task-local
orchestration scripts. Eight fixed stage slots and original six job identities
survive process restart. Preserve complete evidence and limits. Local source
reuse acceptance is not fresh six-job scientific execution E2E.

## Review corrections, authoritative over provisional details above

Catalog stages.database is always original Core. The four Gaussian stage
bindings must equal the Freq reader optimization/frequency sources original.core
and snapshot bytes/hash, aligned by the two ordered source members (anti then
gauche). Thermodynamic reader.readout must exactly equal Freq registration;
population.thermodynamic_readout must exactly equal the thermo registration.

Catalog additionally requires xtb_crest, exactly {sources,seed,handoff}. seed and
handoff are physical bindings. sources is exactly two original receipt-source
records, ordered xTB/CREST, each {snapshot_id,core,transport,
bootstrap_source_sha256,bootstrap_source_size_bytes}. Core/snapshot identities
must match corresponding stages. Transport approved root is its parent directory.
The exact two sources are installed only in a new request-local context owner
`_historical_receipt_sources` in execution/_receipt_source.py. It accepts only
two distinct exact _FixedReceiptSource values, no project association, and may
be consumed only by xtb or crest matching that snapshot ID. Nested use rejects,
context resets on all exits, production fixed globals and Gaussian context are
unchanged. It neither grants live qualification nor accepts a driver.

Execution owner adds `_restore_receipt_seed_handoff(payload)` that decodes the
saved exact payload, freezes it, derives its pre-existing semantic IDs and calls
assert_identity_closed. It does not create a new source authority or publish.
Existing `_ingest_receipt_crest_conformers_xyz` performs the full native readonly
receipt/handoff/plan/profile/target/output proof against original sources.
The coordinator restores the existing SamplingProfile from pinned Freq material,
requires exact payload equality, restores saved handoff, and calls that native
consumer. Its parsed observations must equal the entire saved original
sampling_observations, and original Project/CalculationPlan equal the CREST
snapshot. No new ensemble/dedup, handoff publication or scientific kernel is
called. Native consumer internal handoff replay is validation of the saved
identity, not a new persisted handoff. The four Gaussian sources are validated
through the existing Freq and thermo/population owners. These checks are mandatory;
no unverified historical edge is accepted as complete.

Journal adds 0003-sources.json (HISTORICAL_SOURCES_VERIFIED), with exact data
{catalog_sha256,verification_sha256}, and 0004-complete.json (LOCAL_CREATE_COMPLETE)
with data {request_sha256,core_sha256,verification_sha256}. This replaces the
provisional 0003-complete shape. Verification is the canonical closed query data
{mode,execution_enabled,execution_performed,fresh_execution_e2e,
new_attempt_state,result_origin,stages,edges,thermodynamics,populations}.
mode=historical-reuse, booleans false, new_attempt_state=PLANNED,
result_origin=historical-native-source. Stages are ordered six closed records
{stage,project_id,task_id,attempt_id,summary,lifecycle}; summary/lifecycle are
unchanged Execution DTOs. Edges is exactly seven fixed key strings mapped to
verified: xtb->crest,crest->anti_opt,crest->gauche_opt,anti_opt->anti_freq,
gauche_opt->gauche_freq,frequencies->thermodynamics,thermodynamics->populations.
Thermo/populations are unchanged existing NativeQuery envelopes for anti Freq;
those envelopes include both members and exact saved source identities.

create first freezes request in INTENT, publishes and verifies Core, then calls
all source/edge owners and only after every pin/owner exit succeeds writes the
source verification event followed by COMPLETE. Complete repeat create and
query/audit/recover revalidate sources and require the same verification digest.
status/review may return local prefix status without expensive source replay,
explicitly source_verification=not-refreshed. Default recover is always readonly;
only explicit same-request create fills provable suffix. Partial source replay
never writes a source event. Source binding changes reject, not refresh or rerun.
New Core Attempt must remain PLANNED and absent SubmissionIntent/results at all
times, including when management_state=historical-reuse-complete.

Core export memory method checks exact in-memory main (no attached database),
idle transaction, existing schema identity and foreign keys, then returns native
SQLite serialization. File-backed/attached/transactional stores reject. Study
uses no direct SQL or private Core connection. Core record receipt hashes are
canonical dataclass fields (CalculationPlan/ResourceSpec semantic maps detached)
in fixed six-record order. No synthetic success data is admitted by the real
catalog verifier; tests may substitute verifier only for local persistence fault
cases and must label that evidence separately from actual-source CLI acceptance.

## Final closed details

There are FOUR journal events (not five): INTENT, CORE, SOURCES, COMPLETE as named
above. COMPLETE also includes source_event_sha256; it must equal event3 hash.
Response data is exactly {local,source_verification}. local is exactly
{identities,journal,core,execution_enabled,local_attempt_state,management_state};
identities contains project_id,workflow_run_id and stages (eight fixed stage
keys, each exactly task_id,plan_id,resource_id,attempt_id). journal contains
{sequence,kind,sha256} refs. core is null or event2 data. execution_enabled=false;
local_attempt_state is null until the original six Core records exist, else
PLANNED. management_state is initializing or local-created (four complete
journal events). source_verification is exactly {state,data}, state
not-refreshed/data=null for status/review, or verified/data=closed verification
for create/query/audit/recover. Query/recover on partial initialization returns
not-refreshed and its honest local state; it does not silently complete it.
Top status repeats management_state except a fresh full source validation with
complete journal gives historical-reuse-complete. Source validation never
changes the local Attempt state. Before intent, absent study fails not-found.

Errors exactly {schema,error}, schema auto-g16-direct-study-error/1; codes
invalid-request, invalid-catalog, invalid-evidence, initialization-unresolved,
source-unavailable, busy, not-found, execution-contract-not-frozen. CLI returns
2 for errors; does not expose partial source data or exception detail. Programmer
failures retain traceback locally in tests; CLI maps unexpected owner failures
to invalid-evidence. All read commands fully close contexts before printing.

Creation identity scope is one dedicated physical directory and explicit
creation_key. Same key/content in that directory is idempotent. Cross-directory
cloning with the same key is not a globally registered deduplication service;
intent binds directory identities and copies to other directories reject.
No global catalog scanning or promise of global key uniqueness is made.

INTENT additionally binds core_image_generator exactly {schema,python,sqlite,
source_sha256}; schema=auto-g16-direct-study-core-image/1, python is major.minor,
sqlite the native SQLite version, source_sha256 maps Core models.py, store.py and
study/_model.py to actual source digests. Continuation requires the same generator
and compares the entire rebuilt image bytes, not just known records. Default
read-only recovery reports generator mismatch as initialization-unresolved if
an unacknowledged Core exists; completed snapshots still validate through native
read owner and saved digest/physical binding. Partial intent/Core/event bytes
are never overwritten; interruption inside a write is explicitly unresolved.

initial_xtb integer fields reject bool. charge -32..32, multiplicity 1..33,
cores 1..256, memory_mb 1..1048576, walltime_seconds 1..604800; queue matches
[A-Za-z0-9_.-]{1,64}; input digest exactly lowercase 64hex. All are required and
must equal original xTB input/spec/resources, including charge and multiplicity
(unpaired_electrons+1); receipt consumer separately closes against CREST profile.

The historical source context is an exact mapping with keys xtb and crest and
exact _FixedReceiptSource values. Selection uses kind + matching snapshot ID;
when active, absent or mismatched source rejects without fixed-global fallback.
Check identity on exit and reset on all exits. Gaussian logic stays unchanged.
Historical ProgramExecutionSnapshot semantic objects may be restored from pinned
bytes solely because native ingestion requires that type. prepare, installation,
Approval and execution remain prohibited. The typed saved handoff loader accepts
bytes plus expected digest, rejects duplicate/nonfinite/missing/extra fields,
and calls the saved object's identity validator. Its fixed payload keys are
schema,xtb_snapshot_id,xtb_effect_intent_id,xtb_project_id,
xtb_project_physical_binding_id,xtb_project_physical_binding,
xtb_terminal_success_authority,optimized_geometry_sha256,
optimized_geometry_size_bytes,crest_spec_id,crest_spec_payload_sha256,
sampling_profile_id,sampling_profile_payload_sha256. Full native assertion
validates nested content. Native parser descriptor/relevance maps are taken
only from the pinned original sampling observations, keyed by saved frame index;
no new selection or descriptors. All file pins stay open over owner exits.

## Implementation review narrowing: canonical request and final inventory

The request file must use canonical UTF-8 JSON: sorted keys, ASCII escapes,
compact comma/colon separators, finite JSON values and no trailing newline.
Noncanonical request bytes reject before INTENT creation. Thus the exact input
digest is reproducible from the persisted request object; recovery must compare
that digest to INTENT.request_sha256, not validate a newly computed digest
against itself. This adds no execution authority. Before returning any result,
the held study directory rechecks its exact sealed filename inventory after all
file rereads. Source pins likewise remain open through every native owner exit,
then recheck before closing; no successful output precedes these checks.

Native receipt reads retain their exclusive source-directory locks. Parallel
readers may therefore return `busy` for a proven lock-contention cause. A native
Query `store-unavailable` DTO, whose private cause is deliberately erased,
maps to `source-unavailable`. Neither is evidence corruption or a calculation
failure; no command retries or relaxes the source owner's lock automatically.
