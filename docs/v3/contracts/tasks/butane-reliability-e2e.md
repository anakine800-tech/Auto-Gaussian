# Auto-G16 butane reliability and direct study contract

Task `BUTANE-RELIABILITY-UNIFIED-E2E-01`, v3, OWNER-GUIDED, non-BUS, L3.
Base `b4c7ccb5faab0bb412946c226e834c196068e826`; isolated branch
`codex/butane-reliability-e2e`. Owner accepted the A–D proposal and explicitly
approved accurate contract freeze, independent review, implementation and
offline validation. Commit, publication, integration, installation and new live
execution are not inferred. Earlier operational records stay outside Git.
The development handbook remains binding. Initial independent review accepted
the direction and required the exact boundaries below.

## Four-part continuation authorization, 2026-10-12

The Owner subsequently requested "完成全部四项", explicitly referring to the
fresh unified backend, frontend lifecycle acceptance, integration/deployment,
and one new computational end-to-end acceptance. This continues this exact
OWNER-GUIDED task and the previously authorized frontend companion. It permits
same-scope repairs through passing validation, independent review, commits,
publication, required CI, dependency integration, merge and reviewed deployment
after their prerequisites. It supersedes the earlier action exclusions for
this scope; it does not turn an incomplete prerequisite into a pass.

The unintegrated presubmit recovery dependency must be reviewed and integrated
through its own Git history, never silently copied. Record exact baseline,
candidate, source and installed loader for every integration. Historical /1
studies and jobs remain immutable. A fresh study must have new Project,
WorkflowRun, Task/Plan and Attempt identities and use native handoffs from its
own new outputs. Reusing initial molecular coordinates is distinguishable from
reusing calculated results. Historical reuse is not fresh execution.

Scientific approval still requires the actual structure, route, resources,
server Attempt directory and input digest. Downstream inputs do not exist until
their native predecessor is accepted; expose these as pending review rather
than manufacturing future approvals. Prepare exact packets and request only
missing exact decisions. No previous execution window is extended, no old
launcher is rerun, and UNKNOWN never automatically creates a replacement.
The new acquisition/installation contracts must be independently reviewed
before implementation; current qualification is not inferred for a new caller.

The fresh local request contract is [direct-study-fresh.md](direct-study-fresh.md).
Its implementation and later runtime activation must be reported separately.

## Lifecycle projection boundary

This section freezes the first additive surface. It does not freeze a new
active acquisition protocol by implication. `ProgramReadQuery.get_lifecycle`
accepts the same `ProgramReadSnapshot` as `get_summary`, on the caller's Core
read view. No files, driver, clock, kernel, parser, write or executable snapshot
are acquired. Historical content validation is identical to `get_summary`.
The old summary DTO remains unchanged. Missing completion evidence with a valid
nonterminal assessment is normal; an assessment referencing missing Result or
capture evidence remains invalid. Every assessment retains exact prefix and
snapshot/job binding verification, including active ones without a Result.

The returned closed object has keys `schema`, `attempt_id`, `snapshot_id`,
`core_state`, `job_id`, `projection_as_of_observation_id`, `program`, `scheduler`,
`collection`. Schema is `auto-g16-program-lifecycle/1`. As-of is the last Core
Observation ID or null, not a newly manufactured wall clock timestamp.

All three axes contain `availability`, `reason`, `observed_at`, `evidence_refs`.
Availability is `available|missing|unavailable`; reason is null or one of the
closed codes below. IDs refer to retained Core Observations/Results. Historical
receipts do not retain acquisition timestamps or literal PBS state codes;
those fields are null with explicit reasons, never guessed from current time
or reverse-mapped from a normalized scheduler state. Stale-known is not UNKNOWN.

* Program adds `state`, `completed_at`, `exit_code`, `signal`.
  State `completed|failed|unknown`; zero exit produces completed, nonzero or
  signal produces failed, solely from the exact bound captured completion
  receipt. This is process termination, not Gaussian normal-termination or
  scientific acceptance. No completion receipt means missing/unknown with
  reason `program-completion-not-captured`. completed_at uses saved finished_at; observed_at remains null. Available
  program evidence has reason `observation-time-not-recorded`, because process
  termination time is not acquisition time.
  There is no inference of program running from Core RUNNING or scheduler R.
* Scheduler adds `state`, `presence`, `raw_state`, `raw_state_reason`.
  State is the existing owner vocabulary
  `queued|running|held|exiting|terminal|absent|unknown`, or null before a query.
  Presence is `present|absent|unknown`. Last appended validated scheduler
  receipt wins; historical known states retain `available`, with reason
  `observation-time-not-recorded`. A failed/unknown read is unavailable with
  `scheduler-read-unknown`; no query is missing/`scheduler-not-observed`.
  raw_state is null, raw_state_reason=`raw-pbs-state-not-retained`. A later
  acquisition protocol must persist the original PBS code before projecting it.
* Collection adds `state`, `condition`, `result_id`.
  State `collected|pending|unknown`. A fully verified completion bundle is
  collected, even if a crash preceded a terminal Core transition; collection
  is not parse/validation/acceptance. Otherwise valid active/awaiting-absence
  assessments are pending with condition `awaiting_scheduler_absence`;
  acquisition-unknown is unknown/`reconciliation_required`; other incomplete
  assessments are pending/`evidence_incomplete`; no assessment is
  pending/`not_recorded`. Captured evidence has condition `none`.
  A collected or scheduler-active/awaiting-absence axis is available with reason
  `observation-time-not-recorded`; other assessed-pending axes use
  `collection-evidence-incomplete`; no assessment is missing with reason
  `collection-not-recorded`; acquisition-unknown is unavailable with reason
  `collection-acquisition-unknown`. All observed_at values are null for this historical
  format.
  An audit alone cannot establish a live collector or interrupted process.
  No inferred timeout/interrupted label is added without owned evidence.

`NativeQueryService.get_lifecycle(source_id, attempt_id)` returns exactly
`{schema,kind,data}`, schema `auto-g16-native-lifecycle-query/1`, kind
`lifecycle`; data is exactly `{source_id,attempt_id,availability,reason,result}`.
Successful data has availability=available, reason=null and the complete owner
result. It confirms Attempt membership through the existing read-only Core snapshot,
uses exactly one registered matching snapshot, and calls only the Execution
owner. No registration gives unavailable/not-registered/null result; invalid
matching evidence fails closed with `QueryError('invalid-evidence')`. Existing
invalid-id/not-found/store-unavailable error handling remains unchanged.
The owner requires a successful job-establishing predecessor. Query returns
unavailable/`lifecycle-job-not-established`/null result for PLANNED or
SUBMISSION_INTENT_RECORDED/UNKNOWN Attempts; these are explicitly outside this
first historical reader slice, not calculation failures. Evidence references
are duplicate-free arrays, preserving Observation append order, with Result IDs
appended after referenced Observations where applicable. A collected axis includes
the Result and the exact completion metadata FETCH Observation.
No old DTO or scientific field gains a new meaning.

## Lifecycle acceptance

Synthetic native owners must demonstrate scheduler running + missing program
completion + pending capture; scheduler absent + captured program exit0 +
collected; program nonzero separate from collection; valid nonterminal UNKNOWN
assessment without a Result; missing terminal Result, foreign job, forged
assessment prefix or binding rejected. Native query tests enforce source and
Attempt separation, detached data and zero remote/write/scientific operations.
Latest scheduler unknown replaces older known evidence. A complete bundle
before Core terminal transition still projects collected. Old reader tests remain, including orphan terminal assessment rejection.
The recorded real 749/750 intervals are regression motivation, not fixtures
or new acquisition authority.

## Remaining exact freezes within the approved direction

The following required surfaces remain open until their accurate appendices
and independent review are recorded. Their implementation is already authorized
once those prerequisites pass; do not request the same general permission.

1. Active completion acquisition: Execution-owned independent domain/epoch,
   consumed before any read, bound exact declared receipt, successful stat /
   bounded fetch / restat and original physical receipts. Persist acquired_at,
   all identities, complete input SHA bindings and receipt bytes/digest. It
   cannot poll through an already-consumed epoch or contaminate a collection
   epoch; query never calls it. This requires source/qualification reassessment.
2. Gaussian recovery matrix: Opt adapter6/Q7 and Freq adapter7/Q8 using actual
   restored source and profile association, real child exits at audit before/
   after, wire before receipt, Result before/after, assessment after, transition
   before/after, timeout and concurrent guard. Complete bundle permits only
   local repair; consumed incomplete epoch needs exact new continuation; zero
   prepare/stage/qsub/new Attempt on recovery. Compare immutable old records
   plus permitted additions, not a blanket unchanged-store hash after repair.
3. Dual-scheme populations: computation owner persists a new immutable artifact
   bound to the native thermo pair. Save RRHO/qRRHO G/deltaG/population, T,
   standard state, constants, degeneracy and symmetry provenance. A separate
   versioned Query projects saved values only; old normalized_population stays
   qRRHO. Never calculate new science inside a read request.
4. Direct study: finite recipe xTB→CREST→anti Opt/Freq→gauche Opt/Freq→thermo /
   populations / save. Additive `auto_g16.study` is a restricted composition
   role, not an effect owner or a change to offline `auto_g16.workflow`.
   `execute_once` alone claims Core WINNER, after current Approval PLANNED replay.
   Immutable request, preallocated IDs, append-only journal and exact predecessor
   hashes must survive initialization/operation crashes without replacements.
   `create/review/status/query` and default `recover` are local; `run` consumes
   existing exact three-gate approvals. Remote recovery requires exact installed
   continuation, never implicit launch. Candidate-selection/geometry algorithms,
   fixed production installation and closed command/journal schemas must be
   frozen before code. No plugin/module path, shell or task-local script input.

The old presubmit UNKNOWN worktree is an unintegrated dependency. Its code must
not be silently copied; unsupported pre-submit uncertainty remains explicit.
Native source qualification, independent review, frontend synthetic/real visual
acceptance and an exact new live packet are separate requirements. Module tests,
read-only replay, saved results or historical jobs are never full-chain E2E.

## Validation and delivery

### Gaussian process-fault appendix

The Owner continued the same task with actual interruption, timeout, restart
and no-duplicate validation. This appendix freezes offline fault evidence for
Opt adapter 6/Q7 and Freq adapter 7/Q8. It grants no remote effects. Test setup
uses native stores, the installed source/file bindings, actual project profile
association, approved synthetic snapshots and exactly one inert submission.
Only the final wire peer is synthetic; production restore, receipt validation,
collection guard, persistence and reconciliation checks run unchanged.

Each case starts a real collector process. Injection points are before/after
the collection audit, after wire response before receipt persistence, before/
after Result persistence, after assessment, and before/after Core transition.
The child must terminate with the recorded injected exit code. A separate
process then restores the same snapshot/Attempt/job. Before audit, first
collection is allowed. A consumed incomplete epoch rejects with zero wire;
only a separately installed synthetic continuation may perform bounded reads.
A complete captured bundle permits local idempotent completion and zero wire.
Subsequent replay must preserve the result identity and all existing rows.

Timeout evidence uses a real local blocking peer launched by the production
transport subprocess/timeout owner, with its real deadline and classification;
the fixture must not manufacture timeout/UNKNOWN after its own wait. Record the
peer PID, termination and reaping. The child is reaped, and no scientific
failure or automatic replay is inferred. A second collector process under an
actually held native guard, established by a deterministic handshake, must
reject before wire. Wire exits distinguish before physical Transport receipt
from after physical persistence but before Core receipt; both are required.
All restore paths prohibit
prepare, stage, allocation and submission; an independent persistent wire log
records operation/PID before the peer reply. Baseline submission count remains
one after every crash, rejection, continuation and terminal replay.

Retain child return codes/stdout/stderr, wire logs, all four native stores,
immutable row-prefix comparisons and file digests, snapshot and installed
source bindings. Synthetic scientific outputs carry no real Gaussian claim.
Passing this matrix is process-fault evidence, not qualification of live SSH,
PBS or Gaussian. Historical real jobs are not fault-injected or resubmitted.
Allowed related changes are a dedicated Gaussian recovery test module and its
test-only fixture, plus exact validation/context routing for these tests.

The observed before-Result failure additionally permits a narrow private pure
validator in `auto_g16/execution/program_runtime.py` and its selector call.
With no saved Result, one complete old read frame may be recognized only after
a separately authorized continuation has passed existing validation and its
start audit is persisted. The frame contains exactly opening absence, declared
STAT/FETCH pairs, identical restats and closing absence. Metadata and required
outputs must be present; only optional outputs may be absent. All receipts must
be verified, unique, ordered, bound to the same job and in one audit epoch.
Empty audit-only epochs may surround it; extra evidence, assessments, or an
audit splitting the frame forbid this recognition. This only establishes that
there is no orphan FETCH to repair: the new bounded collection reads afresh.
No old content is promoted, no Result is fabricated and no success is inferred.
Old continuation consumption, approval, effect and Result semantics are unchanged.
Malformed frames fall through the existing conservative orphan rules; original
IR01–IR08 behavior remains required. Exact helper negative tests plus both native
Gaussian before-Result process cases are mandatory. Timeout checks require the
real transport timeout classification, UNKNOWN/acquisition-unknown, SUBMITTED
Core, consumed replay rejection and zero wire. Four-store row prefixes are saved
immediately after each crash/timeout and preserved through recovery; only the
Attempt state field may change, never its identity or submission count.

Allowed first slice: `auto_g16/execution/readonly.py`,
`auto_g16/query/native.py`, matching query tests, this contract, Owner/boundary/
acceptance links and exact existing validation/context ownership maps. This is
an additive frozen task document under conservative v3-full routing; required
checks and selector behavior are not relaxed. Preflight passed seven checks.
Use focused affected tests before independent findings-first review. No change
to transport or an installed service is part of the first slice.

### Dual-scheme saved population appendix

This freezes the already approved dual-population direction. It adds an offline
scientific builder in `auto_g16/thermochemistry/native_populations.py`, a pinned
single-file reader/writer in `auto_g16/conformer/populations_readonly.py`, and a
separate native Query. It does not alter old thermodynamics schemas or the old
qRRHO `normalized_population`, select new scientific parameters, submit jobs,
install code, or expand scientific acceptance.

The input is an exact `NativeThermodynamicReadout` with its trusted physical
artifact binding, plus an explicit `reference_member_id` that must occur in the
two-member pair. The builder reads and fully validates the existing pair/source
chain before deriving any values. Both RRHO and qRRHO G values, T, standard
state, gas constant and Hartree conversion come from the saved pair. It never
reparses frequencies or chooses a low-frequency correction. Degeneracy comes
from the approved member policy; it excludes rotational symmetry. Save the
Gaussian-reported rotational symmetry number and the exact approved symmetry
rationale. The one-gauche-representative policy carries g=2; the builder does
not infer or multiply by mirror counts itself.

For each scheme, save delta_G_i = G_i - G_reference (per representative,
without -RT ln g), log_weight_i = ln(g_i) - delta_G_i/(R_h T), and normalized
population using stable log-sum-exp. Save delta G in Hartree and kcal/mol,
using the pair's joule_per_hartree_mol / 4184 conversion. This is a new offline
scientific computation. All values must be finite, T/R/conversion positive,
degeneracies exact positive integers, and the normalized sum within 1e-12.
qRRHO populations must agree with the old saved qRRHO populations within 1e-12;
a mismatch rejects the new artifact. This does not replace independent oracle
comparison against the actual-source Decimal/GoodVibes validation.

The canonical JSON envelope is exactly {schema, artifact_id, payload_sha256,
payload}, schema `auto-g16-native-populations-artifact/1`. Identity is generated
by the existing `_identified_payload('native-populations', payload)` convention.
The payload is exactly:
- schema = `auto-g16-native-populations/1`;
- source_pair_sha256, conformer_ensemble_id, conformer_ensemble_payload_sha256,
  thermodynamic_ensemble_id, thermodynamic_ensemble_payload_sha256;
- reference_member_id, source_member_ids (exact ordered two members);
- temperature_k, standard_state, standard_state_binding, gas_constant_binding,
  hartree_to_kcal_per_mol;
- thermochemistry_policy_id, thermochemistry_policy_payload_sha256,
  functional_kernel_implementation_id,
  population_implementation_id = `auto-g16-native-dual-population/1`;
- degeneracy_excludes_rotational_symmetry = true, coverage_scope;
- members, normalization.
Each member is exactly {member_id, degeneracy, degeneracy_rationale,
symmetry_rationale, reported_rotational_symmetry_number, source_provenance,
rrho, qrrho}. source_provenance copies the complete existing member provenance,
including minimum/source Result and Observation identities. Each scheme row is
exactly {gibbs_free_energy_hartree, delta_g_hartree, delta_g_kcal_per_mol,
log_relative_weight, normalized_population}. normalization has rrho and qrrho,
each {population_sum, absolute_error, numeric_tolerance}, tolerance exactly1e-12.

Interfaces are exactly:
- `build_native_populations(readout, *, reference_member_id)` returns a deeply
  immutable artifact envelope mapping, requiring exact NativeThermodynamicReadout;
- `encode_native_populations(artifact)` returns canonical candidate bytes;
- `save_native_populations(readout, *, artifact, expected_sha256, destination)`
  returns the trusted _PublisherFileBinding; destination is exactly the existing
  _NativeThermoDestination;
- `NativePopulationReadout(thermodynamic_readout=..., artifact=...).read()`
  returns the immutable saved envelope;
- `load_native_population_readout(content: bytes, digest: str)` returns that
  exact reader after trusted startup binding validation.
Artifact cap is 16 MiB, startup registration cap 1 MiB, and source registration
caps remain the owning existing limits. Exactly two distinct ordered members
are required; reference must occur in that order. Reject unknown/missing fields,
nonfinite values, bool-as-number, noninteger degeneracy, duplicate JSON keys and
noncanonical bytes. This contract does not support a third explicit gauche member.

The builder returns a deeply immutable mapping, and an encoder returns only
canonical candidate bytes, not trusted authority. A save operation requires an
independently accepted expected SHA-256 and revalidates the exact pair/source
association before exclusive creation. Keep approved directory containment,
component-by-component O_NOFOLLOW, held descriptors, O_EXCL, fsync and readback;
filename is `native-populations-<sha256>.json`. No replacement, deletion or path
accepted from HTTP. Refactor the existing private `_Directory` writer only into
a shared fixed-prefix helper with a closed two-prefix allowlist; the old writer
retains its exact filename and public signature. Reading an existing accepted
artifact is the recovery path, never re-saving over it. A shared private
`_replayed_native_pair(reader)` context may be extracted from the existing pair
reader, retaining its exact public behavior. Population build/save/read keeps
the source pair pin, native source replay and all exit checks active over the
whole computation/validation/write. Saved population pins also stay held until
these checks finish. Do not read() and close the source before bare publication.
A source, directory or file replacement causes failure, retains any created
file and permits no automatic replacement/deletion/retry.

`NativePopulationReadout` holds an exact NativeThermodynamicReadout plus an exact
_PublisherFileBinding. Its read pins both artifact and source pair, verifies
canonical bytes, trusted digest, model identity, every source/member/policy
binding and finite closed stored values, and returns a detached immutable
artifact only after exit checks. It does not run the builder, exponentiate,
normalize, or recompute any G/deltaG/population. It may compare saved G,
degeneracy, symmetry, policy and saved qRRHO population to their source pair.
Derived-number correctness is established by the reviewed builder, independent
oracle and accepted digest; source hash validation is not a mathematical oracle. Saved values alone do not issue
ScientificAcceptance. The trusted startup registration schema is exactly
`auto-g16-native-populations-readout-registration/1`, with fields schema,
thermodynamic_registration and artifact; each binding uses the existing closed
{path,parent_chain,file_identity,sha256,size_bytes} shape. HTTP cannot install it.

NativeSource gets optional population_readout; it requires the already registered
thermodynamic_readout and exact equality of its artifact and frequency-source
registration. `get_populations(source_id, attempt_id)` returns exactly
{schema,kind,data}, schema `auto-g16-native-populations-query/1`, kind populations.
Data is exactly {source_id,attempt_id,availability,reason,selected_member_id,result}.
No registration returns unavailable/not-registered with null member/result after
only local membership confirmation. Registered reads require the one matching
Freq snapshot and source member. Available data has availability=available, reason=null. Result is an explicit
public whitelist, never the full stored source_provenance:
- artifact_id, payload_sha256, artifact_sha256, source_pair_sha256;
- qualified_ensemble and thermodynamic_ensemble, each {id,payload_sha256};
- reference_member_id;
- parameters exactly {temperature_k,standard_state,gas_constant_binding,
  hartree_to_kcal_per_mol,thermochemistry_policy_id,
  thermochemistry_policy_payload_sha256,functional_kernel_implementation_id,
  population_implementation_id,degeneracy_excludes_rotational_symmetry};
  gas_constant_binding retains the exact existing closed four-key pair shape;
- members with {member_id,is_selected,degeneracy,degeneracy_rationale,
  symmetry_rationale,reported_rotational_symmetry_number,rrho,qrrho,source};
  scheme rows retain the five closed saved numbers above. source retains the
  exact existing thermodynamics Query whitelist: optimization_attempt_id,
  frequency_attempt_id,two_stage_minimum_authority_id,
  optimization_parsed_result,optimization_result_source,frequency_parsed_result,
  frequency_result_source. Parsed Result refs are {result_id,payload_sha256};
  source refs are {observation_id,payload_sha256};
- normalization and coverage_scope with the exact saved closed shapes above;
- scientific_acceptance = unavailable.
No local paths, physical bindings, raw logs, arbitrary private fields or extra
nested keys are projected. Existing
source/id/store and thermodynamics error mapping applies. Returned containers
are detached; no Query path calls builder, saver, launch, remote transport or
scientific kernel. Old DTOs remain byte-compatible.

Required evidence: independent Decimal oracle for both schemes and shift/reference
invariance; g=1/2 and explicit equal-energy multiplicity behavior; no duplicate
symmetry factor; qRRHO agreement; invalid/nonfinite inputs; foreign source,
member, policy, reference and energy bindings; wrong digest/noncanonical/duplicate
JSON keys; directory and file replacement/symlink/no-overwrite; descriptor closure;
actual save/read and fresh-process byte-identical recovery; zero-compute Query
tripwires and source/Attempt isolation. Preserve actual butane comparison separately
from synthetic tests. Frontend projects these stored fields and source references;
no frontend arithmetic supplies the scientific record.

## Direct study historical reuse implementation

Owner continuation 2026-10-12 authorizes implementation and same-scope repair
through pass under the independently reviewed
[closed command/journal contract](direct-study-reuse.md). This is the existing
isolated task's D continuation; no new calculations, installation, commit or
integration. The immutable local Core image is created through native Core
methods. Original six execution identities remain external historical sources.

The unified trusted local entry is `python -m auto_g16.study`. `create` takes
`--directory`, `--request`, and the exact request `--sha256`; it validates the
native six-stage source catalogue before recording local completion. The other
commands `review`, `status`, `query`, `audit`, `recover` take `--directory` only.
`recover` is read-only; only an explicit identical `create` can fill a provable
missing local journal suffix. Partial files stay unresolved and are retained.
The `run` command rejects before opening any study. Fresh execution E2E remains
unavailable under this no-new-calculation scope.
