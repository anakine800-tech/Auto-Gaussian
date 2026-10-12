# Auto-G16 fresh butane study /2

Continuation of BUTANE-RELIABILITY-UNIFIED-E2E-01, OWNER-GUIDED, non-BUS, L3.
This freezes the new local intake and read model after independent review;
the execution and active-acquisition appendices below remain prerequisites to
their implementation. It does not relabel historical /1 acceptance as E2E.

## Local command and request contract

Keep `python -m auto_g16.study` and its existing commands. Dispatch `create`
by the strict canonical request schema; other local commands dispatch by the
persisted first event. A directory cannot mix /1 and /2. Preserve /1 byte and
reader behavior, including its disabled run. There is no CLI backend, module,
handler, environment, shell, source-catalog or installed-configuration override.
`run` rejects execution-contract-not-frozen before opening any directory or
request, independent of request version. Errors retain the existing common
envelope exactly {schema:auto-g16-direct-study-error/1,error:CODE}, exit 2;
success exits 0. Codes are invalid-request, not-found, busy, invalid-evidence,
initialization-unresolved and execution-contract-not-frozen. OS/SQLite failures
map to invalid-evidence except missing paths map to not-found. No raw exception
text is returned. An empty existing directory read reports not-found and is
never initialized implicitly. Only explicit create may write a local suffix.

The new request is exactly {schema,creation_key,title,structure,protocol,
resources,thermochemistry}; schema `auto-g16-direct-study-request/2`. Every
field is required; unknown keys, duplicate JSON keys, noncanonical bytes,
nonfinite or bool-as-numeric values reject before any publication. The request
and inline structure are bounded by the existing 1 MiB request cap. UUID and
title validation match /1. A new creation_key is a new study, not a retry.

structure is exactly {xyz_utf8,sha256,charge,multiplicity}. Its digest binds the
exact UTF-8 bytes. A single XYZ frame has exactly 14 atoms, four C and ten H,
finite Cartesian coordinates and no other trailing frame. Charge is exactly
0, multiplicity exactly 1. This validates intake, not connectivity or minimum
acceptance. Chemical geometry validation remains a native downstream gate.
The initial structure is displayed in review with its complete hash.

protocol is exactly {xtb,crest,gaussian}; the finite supported explicit values
are xtb={method:GFN2-xTB,optimization:engine_default_opt}, meaning the original
exact `--opt` argument without an added tolerance argument;
crest={method:GFN2-xTB,search:iMTD-GC,metadynamics_length_ps:1,
energy_window_kcal_mol:6,rmsd_threshold_angstrom:0.125,
cregen_temperature_k:298.15,normal_md_temperature_k:400,
calculator:internal-tblite,atom_order:preserve-input-order,
randomness:engine_managed_stochastic}, and gaussian={method:wB97XD,basis:Def2SVP,
environment:gas,scf:Tight_MaxCycle128,integration_grid:UltraFine,symmetry:NoSymm,
optimization_max_cycles:128}. Reject other policies instead of selecting a
default or translating an arbitrary route. These are the existing reviewed
butane conditions, not a general calculation language or new method choice.

resources is an object with exactly xtb,crest,anti_opt,anti_freq,gauche_opt,
gauche_freq. Each value has exactly {cores,memory_mb,walltime_seconds,queue}.
This bounded acceptance supports exactly 4 cores, 12288 MiB and batch, with
1800 seconds for xTB and 3600 for the other stages. Gaussian's explicit
memory allocation remains 8192 MiB plus 4096 MiB headroom, verified later by
the native resource owner. There is no resource override during resume.

thermochemistry is exactly {temperature_k,pressure_atm,frequency_scale_factor,
entropy_model,enthalpy_model,low_frequency_cutoff_cm1,zpe_scale_factor,
interpolation_alpha,bav_kg_m2,degeneracy_policy}, with
explicit existing values 298.15,1,1,grimme,head_gordon,100,1,4,1e-44 and
one_gauche_representative_weight_two. RRHO and qRRHO are both requested.
Rotational symmetry must be read from actual new Gaussian outputs and checked
independently; the gauche multiplicity never multiplies a rotational symmetry
correction. Intake alone creates no thermochemistry eligibility or acceptance.
CREST configuration replay is not a promise of an identical stochastic
trajectory. These explicit values were checked against the retained original
native program specifications and thermochemistry policy, not inferred from
the molecule. The initial draft's xTB "tight" label was rejected during this
source comparison and corrected before any real creation or execution.

## Native local records and immutable publication

Use a /2-specific UUID5 role prefix under creation_key, including the schema
in every role. This prevents accidental identity collisions with a /1 study
even if an operator mistakenly repeats the creation key across schemas.
The exact UUID5 name is `auto-g16-direct-study-request/2:` concatenated with
`project`, `workflow`, or `<stage>:<field>`. Ordered stages are xtb, crest,
anti_opt, anti_freq, gauche_opt, gauche_freq, thermochemistry, populations;
each field is task_id, plan_id, resource_id or attempt_id. Even local scientific
stages have reserved ID slots only: these do not imply that their native owner
will create a Task or Attempt.
Preallocate six stage identity slots, plus two local scientific stage slots.
Only initial xTB creates native Task, revision-1 CalculationPlan, ResourceSpec
and PLANNED Attempt, alongside Project and WorkflowRun. Its plan intent binds
the complete fresh request and mode=fresh-execution. Downstream slots are
explicitly unmaterialized, not eight runnable or completed Attempts.

Publish an immutable `core.sqlite3` using the existing memory export owner.
This file is the initial creation snapshot, never the mutable execution store.
The later runtime store must be separately declared, initialized from the
verified initial records through native owners and fully cross-bound to this
snapshot. A reader must never interpret PLANNED in this immutable image as
the latest execution state once an execution registry exists.

Reuse Directory's held full no-follow chain, exclusive writer/shared reader
lock, one-link file checks, O_EXCL, fsync and exit rechecks. Exactly four files
are allowed for this slice: 0001-intent.json, core.sqlite3, 0002-core.json,
0003-complete.json. Event envelope {schema,sequence,previous_sha256,kind,data}
uses `auto-g16-direct-study-event/2`. Kinds are INTENT,CORE,LOCAL_CREATE_COMPLETE.
INTENT data {request,request_sha256,directory_chain,identities,core_image_generator}.
CORE data {path,sha256,size_bytes,file_identity,records}; six native records.
COMPLETE data {request_sha256,core_sha256}. Generator binds core models/store,
the /2 model, Python minor and SQLite version. All bytes are canonical.

Read-only recovery returns the verified prefix and missing local step without
writing. Exact repeated create may only publish a provable missing suffix; an
existing core without its event must exactly equal the currently bound native
memory export. Partial, changed, extra, orphaned, replaced or foreign files
fail closed and remain untouched. An unresolved prefix never grants execution.

## Read model and explicit incompleteness

Return `auto-g16-direct-study-response/2` with exactly {schema,command,study_id,
request_sha256,status,data}. status is initializing or local-created.
data exactly {mode,identities,journal,creation_snapshot,stages,review,
execution_performed,fresh_execution_e2e,execution_readiness,next_local_step}.
identities has the /1 exact shape {project_id,workflow_run_id,stages}; stages
is the exact ordered-name mapping to {task_id,plan_id,resource_id,attempt_id}.
journal is an array of {sequence,kind,sha256} for the verified prefix only.
creation_snapshot is null if absent or the complete CORE data object described
above; records is an ordered array of {kind,id,sha256} for Project, WorkflowRun,
Task, CalculationPlan, ResourceSpec and Attempt. file_identity is [device,inode].
next_local_step is null when complete; otherwise exactly core-image,
core-event or complete-event, describing the first missing publication.
mode=fresh-execution. For this intake slice execution_performed=false,
fresh_execution_e2e=false; execution_readiness={state:blocked,
reason:execution-contract-not-frozen}. No source catalogue is accepted or
historical scientific result projected into a new study.

stages contains ordered eight entries with exactly {stage,ids,materialized,
core_state,program,scheduler,collection,scientific_result}. Initial xTB is
materialized only when its verified Core exists, core_state=PLANNED. Other
slots have materialized=false and core_state=null. program/scheduler/collection
and scientific_result are null because evidence has not been acquired.
review exactly {structure,protocol,resources,thermochemistry,approvals};
approvals={scientific:pending,batch:pending,operational:pending}. No display
token or request value supplies approval authority. Read commands output only
after all descriptors and source owners have passed exit checks.

## Local acceptance

Exercise real package CLI create/query/audit/recover on synthetic C4H10;
prove new native Project/Plan/Attempt, six records only, all eight fixed slots,
strictly zero submission intent, Approval, transport, network and scientific
kernel activity. No historical catalog loader may be called. Reject malformed
XYZ/hash/charge/spin/policy/resources/thermochemistry, bool-as-number, nonfinite
coordinates, unknown fields, wrong event schema, mixed /1 contents, symlink,
hardlink, replaced inode, corrupt/missing Core and changed request. Preserve
all /1 regressions. Real child exits before/after each of four publications,
fresh-process read recovery and exact create suffix completion, and actual
concurrent lock refusal must demonstrate no identity changes or second claim.

## Runtime and active acquisition: not yet frozen

The actual runner must use a closed installed native recipe, retain the sole
execute_once claim owner and exact native Approval replay, and contain no
task-local Python launchers. Preparation, installed-source qualification,
physical Project association, CREST seed handoff, geometry selection, exact
Opt/Freq input review, mutable-store restore, thermochemistry save, automatic
read-only registry publication and frontend snapshot-consistency contracts
must be specified and independently reviewed before activation. Future
registries are not accepted by the strict local-only reader until that change
is frozen and implemented. Run remains a zero-effect error in this slice.

Independent active receipt acquisition must be a separate consumed epoch,
not a collection retry. It must retain original scheduler bytes and acquisition
time, read only declared completion metadata through successful stat/fetch/
restat, and never convert PBS R to absent or program completion to collection.
Real target qualification, interruption/timeout/restart evidence and the exact
new input/live approvals remain required for the final four-part acceptance.
