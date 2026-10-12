# Auto-G16 direct butane execution and public study reads

Status: DRAFT FOR INDEPENDENT REVIEW. Not frozen; no implementation or live
activation is conferred by this document. Continuation of
BUTANE-RELIABILITY-UNIFIED-E2E-01, OWNER-GUIDED, non-BUS, L3, under OD-46 and
[the four-part authorization](butane-reliability-e2e.md#four-part-continuation-authorization-2026-10-12).
This drafting step is authorized within that continuation, not a new approval
request. Worktree codex/butane-reliability-e2e; original base
b4c7ccb5faab0bb412946c226e834c196068e826. Author changes only this document;
independent contract review precedes implementation. Read-only preflight passed
with the existing owned-dirty-worktree warning. No remote action or test ran.

## 1. Product boundary and unchanged owners

Compose the fixed butane graph only. Preserve /1 historical reuse and /2
[immutable intake](direct-study-fresh.md), including scientific parameters.
Never modify offline Workflow into an executor. Study owns coordination,
immutable operation records and public projection; Core owns records/state,
Approval owns authority, Execution owns snapshots/claim/completion, Transport
owns effects/collection and provisioning owns Project identity. Native science
owners own parsing, geometry decisions, thermodynamics and population artifacts.

One Study has four native Projects and four WorkflowRuns. Root xTB keeps its
original /2 Project, WorkflowRun, Task, Plan, Resource and Attempt IDs. CREST
uses a new Project and remote directory: `_assert_receipt_seed_handoff` rejects
equal source/destination Project IDs or remote directories, and this guard is
unchanged. Anti and gauche use separate Gaussian Projects and WorkflowRuns; each
Opt/Freq pair uses the native Q7-to-Q8 association. No Project needs a later
Q7 preparation after its Q8 association. Neither
that association nor a Study edge authorizes reparenting a native record.

The /2 stage slots and their reserved task/plan/resource/attempt IDs remain
unchanged. New Project and WorkflowRun UUID5 names under creation_key are
`auto-g16-direct-study-execution/1:crest:project`, `:crest:workflow`,
`:anti:project`, `:anti:workflow`, `:gauche:project`, `:gauche:workflow`
(each colon suffix follows the same full prefix). No random IDs on restart. Immutable stage map:

| role | Project | prerequisites | native product |
|---|---|---|---|
| xtb | root | reviewed initial structure | optimized receipt geometry |
| crest | crest | xtb accepted seed handoff | captured conformer ensemble |
| anti_opt | anti | crest reviewed anti member | Gaussian Opt6/Q7 |
| anti_freq | anti | accepted anti_opt | Gaussian Freq7/Q8 |
| gauche_opt | gauche | crest reviewed gauche representative | Gaussian Opt6/Q7 |
| gauche_freq | gauche | accepted gauche_opt | Gaussian Freq7/Q8 |
| thermochemistry | no invented Task/Attempt | both accepted frequencies | native saved pair |
| populations | no invented Task/Attempt | saved thermochemistry pair | dual-scheme artifact |

Selection order is xtb, crest, anti_opt, anti_freq, gauche_opt, gauche_freq,
thermochemistry, populations. No parallel calculations, retries, alternative
methods, replacement Attempts or dynamic graph in this slice. A stop in one
stage prevents dependent materialization; it does not erase independent facts.

## 2. Storage, stable identities and operation replay

The four-file /2 creation directory stays immutable. A separate runtime
container is selected once by the installed local storage owner below its
reviewed root, named by study_id, and bound by a no-follow descriptor chain.
No CLI or browser argument selects a remote root or installation. Store creation
requires absent destinations; never overwrite or delete even partial files.

Runtime contains `core.sqlite3`, `approval.sqlite3`, `transport.sqlite3`,
`project-journal.sqlite3`, fixed `binding.json`, `operations/`, `artifacts/`,
`reviews/`, `public/`. Each native store uses its own schema and native creator;
Study must not create owner tables or synthesize receipts. Initial six records
are loaded through the immutable snapshot reader then persisted with public
Core methods, comparing every returned canonical record. Runtime Core may
subsequently change; immutable creation image may not. Bind stores by role,
physical identity and verified owner schema, not a stale whole-file hash.
Use stable transaction/record receipts for mutable store content claims.

`binding.json` schema `auto-g16-study-runtime/1`, exactly
{schema,study_id,request_sha256,creation_core_sha256,creation_chain,
runtime_chain,identities,installation_id,installation_sha256}. `identities`
contains {root_project_id,root_workflow_run_id,crest_project_id,
crest_workflow_run_id,anti_project_id,anti_workflow_run_id,gauche_project_id,
gauche_workflow_run_id,stages};
stages is the exact eight-slot mapping from /2. Chain entries use the existing
private descriptor identity representation; never expose them over HTTP.

Operations are canonical, exclusive files named by contiguous sequence.
Envelope exactly {schema,sequence,previous_sha256,operation_id,stage,kind,data};
schema `auto-g16-study-operation/1`. operation_id is UUID5 under creation_key
with `auto-g16-direct-study-execution/1:operation:<stage>:<kind>:<ordinal>`;
ordinal is committed by an intent before an owner call, not regenerated from
a timestamp. stage is one fixed role or `study`. Kinds/payloads:

| kind | exact data keys |
|---|---|
| INTENT | action,request_sha256,dependencies,expected_identities,authority_refs |
| RECEIPT | intent_sha256,owner,owner_receipts,artifact_refs |
| STOP | intent_sha256,domain,code,attempt_id,owner_evidence_refs |
| PUBLICATION | receipt_prefix_sha256,projection_sha256,source_manifest_sha256 |
| ACCEPTANCE | receipt_prefix_sha256,acceptance_kind,authority_ref,evidence_refs |

References are closed {kind,id,sha256}; artifact references add size_bytes and
private relative path in their private schema only. Existing owner payloads
retain their exact owner schema, are stored as separately bound artifacts and
are not arbitrary inline journal JSON. action is one of initialize,
provision-project,prepare-stage,record-approvals,submit-once,collect-once,
reconcile-submission,repair-local,select-members,accept-geometry,
compute-thermochemistry,compute-populations,publish-read-model,record-acceptance.
Owner is core,approval,execution,transport,project,conformer,thermochemistry,
populations,study. INTENT dependencies and expected identities must exactly
match the fixed graph; their detailed values are derived from verified native
records, never accepted as caller overrides. Domain/reason enums are in §7.

Execution/derivation steps take one cross-process exclusive Study lock, then
native locks in this order: Project, Core, Approval, Transport, scientific
source owners in their existing prescribed order. These steps NEVER acquire
the registry lock while holding any Study/native lock. Publication is a separate
entry: release execution locks, acquire registry exclusive, then Study exclusive,
then native read locks in that same order; revalidate the committed prefix
before publication. No call from inside the execution critical section may
invoke publication. A crash between execution and publication leaves an
unpublished native receipt, recoverable by the separate publication entry. Never hold a
scientific source lock while taking an earlier lock. Public read projection
uses a shared Study lock; no lock stealing, automatic worker replacement or
lease-expiry-based takeover. Native execute/collection guards remain mandatory.

Crash replay compares the persisted intent, exact native receipts and original
IDs. A committed native record without a Study RECEIPT is adopted only after
owner validation of its exact intent, identity and complete evidence prefix.
No arbitrary record scanning, latest-file guess, fabricated receipt or replay
of the effect. A partially initialized owner store needs its owner's qualified
recovery API; if absent, stop initialization-unresolved with bytes retained.
Partial journal files, unknown names, chain forks, extra fields, inode changes,
missing receipts or ambiguous owner state stop, without truncation/repair.

A local derived calculation may resume its pure in-memory build, but a saved
artifact is adopted only after exact bytes and native readback agree. Exclusive
saver failure never silently chooses another filename. Submission intent is
always claimed solely by `execute_once`; Study INTENT is not submission authority.
Existing native submission intent always prevents a new submit path. UNKNOWN
is never interpreted as not-submitted. Only an explicit authorized native
reconciliation may classify it; even a no-submit disposition does not cause
this Study to create a replacement Attempt or submit again.

## 3. Commands, authority and bounded effects

`python -m auto_g16.study` is the only product coordination CLI; no task-local
script, handler/module path, Python callback, shell text, environment-selected
implementation or caller-created execution port is accepted. Existing local
create/review/status/query/audit/default recover retain zero remote effects.
They read local authority/progress only. Review displays exact input, routes,
resources, remote workspace, snapshot digest and missing native approvals
when prepared; missing geometry is shown as not prepared, never preapproved.

Add a closed `run --action` selector: `prepare`, `submit`, `collect`, `derive`,
`publish`. Exactly one bounded eligible action is executed per invocation;
repeat invocations progress the persisted state machine, not a manual module
handoff. A configured service may invoke these same owner methods, but cannot
supply missing approvals or restart after a stop. No hidden daemon is required.
Without a qualified installation, reject before remote access.

- prepare: materialize the next eligible stage through native owners. Local
  input build may proceed from reviewed source; Project observation/provision
  and snapshot preparation require a separately recorded exact operational
  preparation scope. `ProgramExecutionSnapshotService.prepare` is not local:
  its native Project observation is disclosed and checked. Provisioning only
  uses the installed profile root and native Project owner; at most one intent
  per Project, with unknown provisioning handled by native reconciliation.
- submit: exact prepared snapshot plus original scientific approval, finite
  batch member and current operational confirmation; one execute_once call.
  No next-stage submission in the same command. Every Gaussian input must
  first have its exact geometry/hash shown and approved. A study-level method
  approval cannot approve future unknown coordinates or future input hashes.
- collect: native bounded read epoch only, tied to current snapshot, job,
  authority and finite window. No prepare/stage/qsub permission is present.
  Native consumed/incomplete epochs are not reused. Continuation requires a
  newly approved exact read epoch; it is never an automatic timeout retry.
- derive: native scientific builders plus exclusive savers for the next local
  stage, after accepted inputs and exact registered policy. No shell compute.
- publish: validate owner receipts and publish a new immutable public prefix;
  no scientific computation, new owner artifact or remote observation.

Explicit `recover --action repair-local|reconcile-submission|collect` may invoke
only the corresponding qualified native capability and must reference its
exact current authorization. Default recover remains read-only. No recovery
path calls prepare, stage or qsub. Local repair may adopt already-complete
owner evidence, not complete an interrupted remote read. CLI authority input
is an ID in the installed native approval registry, not a user-supplied object
or boolean. Approval issuance/import uses the native Approval owner; Study
must verify persistence/currentness and cannot manufacture approved records.
A narrow local approval-recording CLI adapter is a required new integration
surface if existing native issuance cannot be reached without scripts.

Return private CLI `auto-g16-study-execution-response/1` exactly
{schema,command,action,study_id,operation_id,revision,outcome,next_action};
outcome is unchanged,committed,awaiting-approval,blocked; next_action is null or
one closed selector above. Errors retain common error/1 and exit 2; success 0.
Return only after exit checks. Detailed review/public status remains separate.

## 4. Required native session and deployment extension

Current `_FixedPilotRun`, `_FIXED_PILOT_RUN`, `_FIXED_PUBLISHER_INSTALLATION`
and `_FIXED_COLLECTION_INSTALLATION` target one installed run and enforce
object identity. They cannot implement a multi-stage Study by rebinding globals.
This is a real implementation prerequisite, not a configuration workaround.

Add an owner-private `open_study_stage_session` factory under the existing
Controller/Transport owners. It accepts only a verified installed Study binding,
fixed stage identity and persisted operation/authority references. It returns
an owner-created context exposing prepare, execute_once, collect_once or
reconcile according to one selected capability. No caller injects a port,
driver, callback, profile, path or snapshot instance. Stage manifest is created
and validated by the native owner after real inputs exist; never preinstall
six fake snapshots. Validation includes immutable installation code/qualification,
current profile, store handles/inodes, snapshot/current Core, exact input/PBS
bytes, original three approvals and current live window. Gaussian's claimed
phase callback must remain the real `_current_gaussian_handoff_approvals`
logic, constructed by the Controller, not a supplied dictionary lambda.

Owner-held per-session binding is immutable and compared by identity before
each effect and on exit. A scoped context may hold one session, reject nested
or mixed Study/stage bindings and reset on exit; it cannot weaken legacy fixed
installation paths or be a caller-visible setter. Original fixed pilot entry
points remain byte-compatible. Qualification must cover new factory effects,
restart, binding substitution and concurrent stage refusal before activation.

Deployment choice: an immutable verified source archive containing auto_g16,
scripts/run_v31_publisher_pilot.py and its actual transitive Controller imports,
plus locked runtime dependencies. Current wheel includes only auto_g16* and
is insufficient for this Controller. Installation receipt binds commit/tree,
archive hash, full source manifest, Python/dependency identities, fixed profile,
owner probe evidence and source readback. Launch from the exact qualified
archive; no editable worktree or cwd-dependent import fallback. A future move
of Controller into the package is a separate compatibility change, not an
implicit part of this draft. No task-local launcher ships in the archive.

## 5. Scientific edges and saved results

Use corrected /2 policy verbatim. Preserve exact original CREST -v3/-cross/-nozs,
engine identity, internal-tblite and seed=null semantics; configuration replay
is not bitwise trajectory replay. Prepared native spec/argv must compare against
this finite mapping, not merely against a display label.

xTB result acceptance verifies receipt, capture hash, exact input and atom/order/
connectivity through existing owner. CREST seed uses the native receipt handoff
and real optimized coordinates; no copy-and-relabel. CREST ensemble ingestion
uses native captured bytes and owner parser; retain every frame and observation.
Member selection is an explicit reviewed local artifact with exactly
{schema,study_id,crest_snapshot_id,ensemble_sha256,anti_member_id,
gauche_member_id,source_frame_refs,review_authority_ref}. IDs must be distinct
existing members, with original frame index/order/coordinates and connectivity.
No automatic frame-zero, lowest-file or silent geometry classification rule.
Until exact native geometry classification/acceptance interface is frozen,
stop awaiting-geometry-review; do not invent anti/gauche angle thresholds.

Native Opt refinement and Freq successor owners validate original members,
actual Gaussian inputs/outputs, Project association, checkpoints and accepted
optimized geometry. Both final structures remain reviewed anti/gauche with
correct C4H10 connectivity. Each Freq must contain all 36 modes, zero imaginary
modes and native minimum eligibility, plus independent geometry review.
Wrong geometry or incomplete frequency evidence stops local scientific promotion
without relabelling scheduler or program completion as failure.

Thermochemistry uses actual newly accepted frequency sources, native pair
builder and exclusive saver at the frozen 298.15 K/1 atm/scales/cutoffs/alpha/Bav.
Both RRHO/qRRHO persist with all contributions and source hashes. Independent
oracle validation uses a second implementation, not reading saved values back;
its evidence is an acceptance artifact, never a substitute source. Population
builder/saver consumes that saved pair, one anti weight 1 and one gauche weight 2;
read actual rotational symmetry independently and avoid multiplying degeneracy
twice. The existing native population closed schema/readers are reused.
New results preserve all original Project/Run/Task/Attempt/member IDs and hashes.
No historically computed result can satisfy fresh stage acceptance.

## 6. Public registry, revision and readonly owner

Select append-only manifest discovery. An operator-installed, no-follow pinned
registry root contains immutable numbered registration records. Startup config
binds that root's identity and registry schema, not its changing tail hash.
No environment or browser path override. Historical /1–/5 registrations remain
unchanged. Max 64 studies; safe registry keys [a-z0-9-]{1,64}; no duplicates or
key rebind. A new Study appears only after an explicit native publisher call.
No overwrite/remove/tombstone in this slice.

Registration schema `auto-g16-study-registration/1`, exact
{schema,sequence,previous_sha256,key,study_id,request_sha256,creation_binding,
runtime_binding}; private bindings use reviewed physical owner schemas.
Readers validate a stable contiguous prefix under shared registry lock. Partial
append or unknown files yields registry-unavailable, never an empty success.
One record per Study. Stage updates live in that Study's public prefix, not
replaced startup source configuration. Registry reader takes registry shared, copies and validates registration
bindings, releases it, then takes a Study shared lock; it never reacquires
registry while holding Study. Registry/publication writer takes registry
exclusive before Study exclusive, as specified in §2; no native effect is
executed in this entry. A new registry record is appended only after its first
Study publication commits. If a process exits between those writes, rerunning
publish validates and adopts the existing exact public prefix before appending
the absent registration; it cannot append a second registration.

Each PUBLICATION commits immutable projection and source-manifest bytes, then
a journal receipt. revision is SHA256 of this PUBLICATION event; as_of_event_id
is its operation_id. Projection binds the exact preceding owner-receipt prefix
and is revalidated against registered immutable evidence, never live mutable
facts silently mixed with an old revision. An incomplete publication is not
readable success. Readers return last committed prefix explicitly as such;
publication-in-progress returns busy where a stable prefix cannot be proven.

Public owner `NativeStudyReadQuery` exposes
list_studies() and get_study(study_id, *, revision=None), plus get_stage_result(
study_id,stage,kind,*,revision). Only registry-created instances may operate;
no arbitrary per-request source binding. kind is optimization,frequency,
thermodynamics,populations. Results use the exact existing owner DTOs without adding private fields:
optimization/frequency use NativeQuery.get_attempt / auto-g16-native-query/1,
thermodynamics uses NativeQuery.get_thermodynamics /
auto-g16-native-thermodynamics-query/1, populations uses
NativeQuery.get_populations / auto-g16-native-populations-query/1. These named
existing schema validators are normative nested schemas, not arbitrary JSON.
They are returned inside an outer {schema,study_id,stage,revision,result_binding,
result} wrapper, schema=auto-g16-native-study-result/1;
result_binding is {kind,id,sha256}. Not-ready is explicit unavailable. Scientific
reads use pinned sources/exit checks and do no builder/saver calls. At most one
deep read per Study concurrently; no automatic retry or polling. Cheap overview
reads only committed lifecycle/materialization facts, no expensive science.

Public envelope `auto-g16-native-study-query/1`, exactly {schema,kind,data}.
kind=studies: data {items,sources,consistency}; items up to 64 rows each exactly
{key,study_id,project_id,workflow_run_id,title,mode,revision,state}; sources each
{key,availability,reason}; consistency is committed-prefix. kind=study: data
exactly {study_id,project_id,workflow_run_id,title,request_sha256,mode,revision,
as_of_event_id,state,stages,edges,recovery,claims}. mode=fresh-execution only
for this new registry slice; do not disguise /1 reuse as fresh. title <=200.

stages exactly eight ordered rows:
{role,stage_id,dependencies,project_id,workflow_run_id,reserved_ids,
materialized,task_id,attempt_id,attempt_history,origin,state,reason,core_state,
program,scheduler,collection,result_refs}. stage_id is reserved task_id as
opaque stable slot ID; reserved_ids has the four existing /2 IDs. Unmaterialized
actual IDs are null; local derived stages never get native Task/Attempt values.
attempt_history has zero/one rows {attempt_id,source_key,snapshot_id}; snapshot
may be null before preparation. source_key is registry-owned, not a pathname.
origin is not-produced,new-execution,new-derived. Axis objects have the exact closed keys and enums below; null before a
submitted native job and captured axis evidence exist. This is a new Study
schema, not a widening of historical lifecycle /1. No inferred PBS raw R or
observation timestamp. Result refs max 8 each {kind,id,sha256,source_key,member_ids};
kind is optimization,frequency,thermodynamics,populations. id is native Result
UUID for Opt/Freq or the exact existing artifact schema identity for derived
results; sha256 is its native canonical payload/artifact digest. member_ids is
an ordered unique array of canonical member UUIDs (length 1 for Opt/Freq;
length 2 for pair thermodynamics/populations). Stage-kind mapping is anti_opt
and gauche_opt to optimization, anti_freq and gauche_freq to frequency,
thermochemistry to thermodynamics, populations to populations. xTB/CREST expose
no such panel ref; their accepted artifacts are represented by edge provenance.
No path or private native payload is allowed.

source_key is canonical UUID5 under creation_key, exact name
`auto-g16-direct-study-execution/1:public-source:<role>`, for one of the eight
roles. It resolves only in the source manifest committed by the same revision.
Its immutable tuple is (study_id,role,Project/WorkflowRun IDs,Task/Attempt IDs or
null, snapshot digest or null, result registration digest or null). A stage's
null-to-materialized progression creates a new revision manifest, never
changes an already-published tuple. attempt_history length <=1; its source_key
must resolve to that same stage and exact Attempt. A result_ref source_key
must resolve to the exact native result and member set, with the full dependent
source closure validated by its existing owner. A wrong or unknown key is
invalid-evidence, never fallback to another registration.

All axes share {availability,reason,observed_at,evidence_refs}; availability is
missing,available,unavailable (separate from registry/source availability).
observed_at is null in the historical projection; evidence_refs is an ordered
unique array of native observation/Result UUIDs, at most 64. Program adds
{state,completed_at,exit_code,signal}; state unknown,completed,failed; timestamps
are null or the exact captured RFC3339 UTC receipt time; exit_code/signal are
null or native integers (bool rejected). Scheduler adds
{state,presence,raw_state,raw_state_reason}; state null or queued,running,held,
exiting,terminal,absent,unknown; presence present,absent,unknown; raw_state=null,
raw_state_reason=raw-pbs-state-not-retained. Collection adds
{state,condition,result_id}; state pending,unknown,collected; condition
not_recorded,reconciliation_required,awaiting_scheduler_absence,evidence_incomplete,
none; result_id null or native Result UUID. Axis reason is exactly one of
program-completion-not-captured,scheduler-not-observed,collection-not-recorded,
observation-time-not-recorded,scheduler-read-unknown,collection-acquisition-unknown,
collection-evidence-incomplete. Missing/available/unavailable and reason
combinations are the exact existing ProgramReadQuery.get_lifecycle mapping;
no reason=null is introduced on those historical axes. Active program-only
completion observations cannot be represented as captured terminal Result here
until their separate owner schema and projection mapping are frozen.

core_state is null or exactly PLANNED,SUBMISSION_INTENT_RECORDED,SUBMITTED,
RUNNING,SUCCEEDED,FAILED,UNKNOWN,NOT_SUBMITTED; materialized computational stage must read it
from Core. Derived stages have materialized=true only after their artifact is
published, with all native Project/Workflow/Task/Attempt fields null; reserved
IDs remain opaque unused slots. Dependencies are exact role arrays from §1.

edges are the fixed graph, rows {from,to,kind,provenance_ref}; kind is seed,
member,opt-frequency,frequency-thermo,thermo-population. provenance_ref is null
before native acceptance, otherwise closed {kind,id,sha256}. Definitions never
change with array order or discovery time. recovery exactly {state,stage,
attempt_id,domain,code,last_committed_event_id,receipt_ref}; state none,needed,
blocked,completed; a proposed recovery cannot have completed or receipt_ref.
claims exactly {execution_performed,all_stages_complete,scientific_acceptance,
fresh_execution_e2e}; each {value,evidence_refs}, value true,false,unknown.
A true acceptance requires its independent ACCEPTANCE event and exact full
native dependency closure; program success alone cannot populate it.

All DTOs are detached only after locks/pins and exit checks pass. Reject
unknown fields/schema/duplicates/bool-numeric. JSON cap 2 MiB, depth <=24,
max evidence refs 64 per claim, identifiers canonical UUID/digest where defined,
reason codes <=64 safe ASCII characters; arbitrary exception strings forbidden.

A supplied revision must match a committed available projection or return
revision-conflict; do not replace it with newer or older data. Every deep result
wrapper carries the exact requested revision and artifact bindings. Frontend
must not merge incomparable revisions. Existing global two-request budget and
120-second read deadline apply; client timeout never cancels backend work.
HTTP GET only; exact routes /api/v1/native/studies and /{study_id}, plus
/{study_id}/stages/{stage}/results/{kind}?revision=..., with no subprocess CLI.
Auth/origin/no-store/token protections and old native endpoints remain intact.

## 7. Closed states, errors and honest completion

Management/stage state: unmaterialized,planned,awaiting-approval,prepared,
submitted,collecting,awaiting-scientific-review,complete,blocked. Raw Core state
is independent. Domain: initialization,authority,installation,execution,
transport,collection,scientific,publication,registry. Registry/source availability
is available,unavailable,busy; available requires reason=null. This rule does
not override the independently enumerated historical axis reason mappings in §6. Closed reason/error codes:
not-found,busy,invalid-request,invalid-evidence,initialization-unresolved,
installation-unqualified,authority-required,authority-expired,
submission-unknown,collection-incomplete,collection-timeout,process-interrupted,
awaiting-geometry-review,scientific-not-accepted,result-not-ready,
source-unavailable,registry-unavailable,revision-conflict.

Unknown evidence is never converted to a positive claim. Active scheduler with
program termination and uncaptured result remains three separate axes. Local
process disappearance does not imply Gaussian/PBS failure. Source errors do
not erase previously published revisions, but UI marks retained data as prior.
HTTP mapping: invalid-request 400, not-found 404, busy/revision-conflict 409,
source/registry unavailable 503, invalid-evidence 422; closed error envelope
{schema:auto-g16-native-study-error/1,error:code}. No tracebacks or private paths.

## 8. Required new native boundaries and acceptance gates

The following are missing capabilities to implement under a reviewed exact
extension, not assumed existing facts or a broad new workflow engine:

1. Qualified stage-session factory and data-bound preparation/approval adapters
   in Controller/Transport/Execution, with no _FIXED_* rebinding or fake callback.
2. Recoverable four-store initialization, intent-to-owner-receipt adoption and
   fixed cross-Project Study map without mutable changes to /2 creation image.
3. Public owner, registry/publication writer, snapshot-bound dynamic attempt
   source lookup and revision-consistent scientific links.
4. Native program-complete observation while scheduler remains active, if not
   already qualified: read-only stat/fetch/parse capability in its own approved
   epoch, no terminal Result promotion until native completion acceptance.
5. Packaged/versioned source-archive Controller installation and target
   qualification for the exact new code; current wheel alone is not activation.
6. Native geometry selection/acceptance adapter and independent scientific
   oracle entry reachable through product coordination, not task-local scripts.

Before freezing implementation, review this draft's closed interfaces and
supply exact owner subcontracts for items 1, 4 and 6 where existing schemas do
not already determine inputs/outputs. Their absence blocks those effects, not
read-only design or already authorized independent engineering preparation.
Never describe this draft as a completed executable contract.

Validation must cover every operation before/after intent, native persistence,
remote handoff boundary and journal acknowledgement with real process exit,
fresh-process restore, actual SQLite/store locks, no duplicate IDs/submission,
all unknown/partial prefixes retained, strict binding substitution negatives,
three-approval expiry/revocation, installation identity drift, source/target
Project mismatch, same-Project CREST rejection, and active program/PBS/collection
divergence. Test synthetic wire plus explicitly approved native target evidence;
no unit test may trigger live effects. Concurrent old/new revision requests,
registry partial append, source drift on exit, no GET effects and private-field
leak negatives are mandatory. Preserve /1, /2, native pilot and owner suites.

Final acceptance has separate records for offline implementation, independent
review, required CI, merge, installation/target qualification, frontend joint
readback and fresh scientific E2E. Last requires one new Study carried through
this product CLI, actual six newly approved computations (each Attempt at most
one submission), native accepted geometries/frequencies, independently checked
RRHO/qRRHO and populations, saved/queryable artifacts, exercised recovery and
browser evidence on the installed read entry. Historical jobs and segmented
manual scripts cannot supply that claim. No server deletion or automatic qdel.

## 9. Evidence behind the four-Project choice

This is a conservative new Study arrangement, not a claim that historical
747–750 used four Projects. Read-only historical snapshot comparison found all
four Gaussian stages used Project c71ceb17-ca53-4207-a34b-9b6679febaf3. Opt
snapshots (execution-02 and execution-01/gauche-native) used original Q7 binding
8c606ba0-a088-5bbd-b525-85ab65e94346 and profile
45ae028d-c879-583d-bdc7-483bb237dc96. Anti Freq used associated binding
352d0325-0ad3-542a-842c-8399339d7032; gauche Freq used
364921d9-1cfd-5de9-872d-208726dae042; both used Q8 profile
91ede99b-8f47-5022-8963-24be426e911c. These are historical provenance IDs only,
never new Study authority or public source registrations.

Native source findings: `_project_association.profile_delta` permits only Q7
to Q8, while `binding_payload` creates a derived association without changing
the original creation binding. `_ProjectProvisioningService._assert_owned_binding`
validates an associated binding against the read-only original journal and
validates an unassociated binding by exact durable equality. Thus no static
rule found here categorically invalidates original Q7 after an association.
However the historical gauche Opt snapshot already existed in execution-01;
its later submission does not prove first-time Q7 preparation after Q8 under
a newly qualified multi-stage installation. That sequence and factory remain
unqualified. Four Projects remove this dependency without inventing a Q8-to-Q7
conversion or relaxing a native guard. Qualification still must establish each
new anti/gauche Q7 creation and one-way Q8 association, separately bound.
