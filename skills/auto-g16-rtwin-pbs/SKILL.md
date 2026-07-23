---
name: auto-g16-rtwin-pbs
description: Present and record hash-bound loose/standard/strict Gaussian protocol candidates before input drafting, then prepare, submit, monitor, fetch, and analyze approved Gaussian 16 calculations through the user's configured RTwin Windows SSH bridge to a private PBS server. Includes audited Opt-Freq-single-point workflows, thermochemistry, conformer aggregation, per-hop SHA-256, overwrite prevention, robust state classification, scheduler-zombie cleanup, and confirmation-gated cancellation. Use for protocol-rigor comparisons or organic Gaussian jobs reachable only through RTwin. All server data and scratch are confined to /home/user100/SDL.
---

# Auto-G16 RTwin PBS

Use `scripts/gaussian_auto.py` only with an already reviewed `.gjf/.com` input;
it does not choose or render a method. Use `scripts/gaussian_rtwin_pbs.py` for
individual operations. After a separate exact live-approval record binds the
input and job scope, submission, monitoring, fetching and analysis may run
unattended.

## Input-before protocol gate

For a TS/QST route, first display and validate the reaction-workflow maturity
gate under its declared `/1` or `/2` schema. It shows maturity, evidence, accepted
endpoint minima and blockers before route/resources/hash. Protocol selection
cannot begin formal TS input review while this gate is blocked. A no-direct-
precedent exception is limited to one reviewed simple-tier pilot after two
accepted minima; it never establishes literature support.

For every new calculation need, read
[`references/protocol-rigor.md`](references/protocol-rigor.md) before writing a
Gaussian input. First present exactly three reviewed protocol candidates named
`loose`, `standard` and `strict` in a `gaussian-protocol-options/1` artifact,
then record the user's explicit selection in a separate hash-bound
`gaussian-protocol-selection/1` artifact. Use
`scripts/protocol_selection.py` for proposal, selection and validation. Do not
infer or auto-select a functional,
basis/ECP, solvent, numerical settings, thermochemistry or path method from the
molecule or the requested label.

Keep the options artifact route-free and input-free. Record stage-specific
method, basis/ECP, environment, numerical, thermochemistry, validation and
resource fields instead. Only a confirmed selection may authorize composing
the exact offline Gaussian route and input draft for the separate input-hash
review.

Any candidate with unresolved chemistry or unsupported electronic structure
must remain `blocked`; all three labels may be shown without making all three
runnable. `strict` is a stronger evidence or sensitivity plan, not an accuracy
guarantee. Protocol rigor is independent of the `simple`, `general` and
`complex` resource tiers.

The selection authorizes only creation of the exact offline input draft. It
does not authorize transfer, server-directory creation, PBS submission, IRC,
retry, cancellation or cleanup. After rendering, show the full input and its
SHA-256 and use the existing exact live approval gate.

## Local configuration

Copy the repository's `config/runtime.example.json` to
`~/.config/auto-g16/runtime.json` and fill only local, non-secret paths. An
environment variable overrides the matching JSON value.

- Mac SSH alias: `rtwin` in the ignored local config selected by `AUTO_G16_RTWIN_SSH_CONFIG`
- RTwin server alias: `gaussian-server` in the Windows config selected by `AUTO_G16_WINDOWS_SERVER_CONFIG`
- Server data root: `/home/user100/SDL`
- PBS/Torque queue: `batch`; Gaussian 16 at `/opt/soft/g16/g16`
- Capacity: 44 CPU cores and 120 GB physical memory
- Resource tiers: simple = 12 GB/8 cores; general = 50 GB/22 cores; complex = 120 GB/44 cores

Never store or echo passwords. Never replace a changed SSH host key silently.

## Non-negotiable filesystem boundary

- Hard-code `/home/user100/SDL`; provide no remote-root override.
- Resolve the root and project with `realpath`. Refuse symlinks or paths outside the root.
- Refuse upload to any non-empty server project directory. Use a new project name; never overwrite implicitly.
- Put Gaussian scratch in `/home/user100/SDL/<project>/scratch`, never `/tmp`.
- Provide no server data deletion command. Never issue `rm`, `rmdir`, truncation, or recursive replacement. A future deletion requires exact paths, canonical containment proof, impact preview, and a separate final confirmation.
- Use `qsub/qstat` only for PBS-owned state. Permit one exact automatic `qdel` for a repeatedly proven terminal scheduler zombie; require exact approval for cancellation of a queued or running job. Never access scheduler spool directories.

## One-command workflow

1. Resolve structure, stereochemistry, charge, multiplicity and scientific scope. For CDX/CDXML, rely on the corrected explicit-H/CFG importer in `auto-g16-view-rt-win`.
2. Create the three-candidate protocol proposal, show every candidate and blocked reason, and record the user's hash-bound selection. Select the resource tier separately; use `general` when execution complexity is not clearly simple or complex.
3. Only after selection, render or audit the offline input draft. Show source hash, identity, warnings, exact route, charge/multiplicity, atom count, cores, memory and remote directory. `gaussian_auto.py` refuses raw structures and SMILES so it cannot bypass this gate.
4. After separate exact review of the rendered input, finalize
   `gaussian-input-draft-review/2` and build
   `gaussian-input-approval-receipt/1`. For a main-group open-shell minimum,
   the builder additionally requires and replays the electronic-state review,
   minimum input handoff and passed input audit, and emits the versioned,
   offline-only `gaussian-input-approval-receipt/2`. The receipt replays the
   exact protocol
   options and selection, selected option, the non-empty task/profile subset
   consumed by this input, human-confirmed route/method/basis/solvent/SCF
   mapping, resources, identity and input SHA-256. It never claims whole-family
   completion and grants no live authority. For ordinary or closed-shell
   minimum work, historical replay uses `auto-g16-live-submission-approval/3`;
   `/6` is retained for package-2 historical replay; every new resource-bound
   protected submit uses its time-bounded, one-time `/9` successor.
   Generic `/9` ordinary execution is singlet-only. Ordinary multiplicity
   greater than one is blocked early because no specialist ordinary open-shell
   owner/schema exists; never finish a generic receipt and fail only at live
   approval, and never silently broaden `/9`.
   For one main-group open-shell minimum, historical replay uses the separate
   closed `auto-g16-live-submission-approval/4`, while a new protected submit
   uses `/10` (`/7` remains historical replay only), to bind a fully owner-replayed
   receipt `/2`, its exact file/payload/input hashes, open-shell owner workflow,
   state-review/handoff/audit/selected-option payloads, U/RO reference,
   resource tier and replay result. `/3` semantics are unchanged, and receipt
   `/2` itself remains `calculation_ready: false` with
   `no_submission_authorization: true`. A checkpoint-bound two-stage open-shell
   minimum instead requires one exact
   `gaussian-input-approval-receipt/3`; historical replay uses one closed live
   approval `/5` per stage, package-2 historical replay uses `/8`, and every
   new protected submit uses `/11`. A closed-shell fixed-coordinate
   preoptimization uses the additive `gaussian-input-draft-review/3`,
   `auto-g16-fixed-constraint-input-audit/1`, and
   `gaussian-input-approval-receipt/4` chain. It accepts only one explicit
   Cartesian singlet minimum input with one ModRedundant/AddRedundant Opt and
   1–64 validated B/A/D `F` directives; Freq, TS/QST, `S` scans, GIC, IRC,
   checkpoint syntax, Link1 and unknown tail lines remain blocked. Its new
   protected submit requires live approval `/12`; neither review, audit nor
   receipt grants live authority. `/9`-`/12`
   require approver identity, approved/expires timestamps, active revocation
   state, a one-time approval ID, and exact batch/task/attempt/idempotency
   binding. Old approvals without those fields cannot enter a new submit. The
   stability receipt additionally binds the accepted Opt/Freq final
   checkpoint and owner manifest. A prior failed combined input uses family
   handoff `/1`; a fresh prospective family uses `/2` and explicitly carries no
   prior-failure hash. This does not extend receipt `/2` or live `/4`.
   Protected TS/scan/IRC prospective live work is currently
   fail-closed: maturity gate `/1` is replay-only, while current `/2` has no
   positive action because minimum lineage and specialist owners remain open.
   A future protected chain must provide an exact maturity action `/2`, action
   authorization `/2`, and specialist input receipt; generic input receipt plus
   live `/3` cannot substitute. Historical live `/1` and `/2` records remain
   replayable under their original contracts but do not satisfy a new
   submission chain. The low-level `submit` command
   independently validates the same shared receipt; `--confirmed` is only an
   additional command confirmation.
5. Classify state from three sources: PBS record, PBS session process, and Gaussian log. PBS and process evidence are fail-closed three-state observations: `present`, `absent`, or `unknown`. SSH failures, non-recognized command return codes and parse failures are `unknown`; they never prove interruption, self-purge, process absence or a zombie. Treat PBS `Q` with no session/process/log as a valid queued job, not a failed launch. For a 44-core full-node request, unavailable capacity is a common explanation, but `Q` alone does not prove the server is full; report a specific reason only when PBS exposes one. Wait without duplicate submission, automatic resource reduction, cancellation, or method changes. A live PBS `R` session always outranks an earlier `Normal termination` in a multi-stage input such as `Opt ... Freq`; do not fetch or interpret a partial log as final. A stale PBS `R` with explicitly absent process evidence is not a running calculation, but one observation is only a zombie candidate. After a verified terminal fetch, `watch` automatically performs the repeated zombie audit and issues at most one exact `qdel` only if every cleanup check passes.
   Package 4 collects qstat, session process, log size/mtime/tail/terminal counts,
   manifest, collection time, transport and freshness in one remote read-only
   snapshot call per job per poll. Conflicts, timeout, stale evidence or parse
   failure are `unknown`. Job and `/3` ledger observations are append-only and
   never change scientific acceptance.
6. On failure, stop after analysis. Do not silently add SCF options, change geometry, change method/basis, or resubmit. Report diagnostics and create a new proposal and selection for any changed restart.

```bash
AUTO="$HOME/.codex/skills/auto-g16-rtwin-pbs/scripts/gaussian_auto.py"

# Review an already rendered input only
"${AUTO_G16_CORE_PYTHON:-$HOME/miniforge3/bin/python3}" "$AUTO" prepare /path/to/reviewed.gjf \
  --project example --local-dir /path/to/outputs/example

# Approved ordinary/minimum unattended run
"${AUTO_G16_CORE_PYTHON:-$HOME/miniforge3/bin/python3}" "$AUTO" auto /path/to/reviewed.gjf \
  --project example --local-dir /path/to/outputs/example \
  --work-kind minimum \
  --input-approval-record /path/to/exact-input-approval.json \
  --approval-record /path/to/resource-bound-live-approval-v9-v10-v11-or-v12.json \
  --execution-batch-ledger /path/to/execution-batch-v3.json \
  --scientific-task-id scientific-task-<sha256> \
  --idempotency-key operator-attempt-key \
  --estimated-core-hours 8 \
  --estimated-core-hours-evidence-source reviewed-estimate-record \
  --estimated-core-hours-evidence-sha256 <sha256> \
  --resource-policy /path/to/resource-policy-v1.json \
  --scheduler-resource-snapshot /path/to/fresh-scheduler-resource-snapshot-v1.json \
  --resource-gate /path/to/exact-resource-gate-v2.json \
  --resource-tier simple --resource-cores 8 --resource-memory-gb 12 \
  --walltime-seconds 86400 \
  --confirmed --watch
```

For a local dry run that performs no SSH, PBS or Gaussian action:

```bash
"${AUTO_G16_CORE_PYTHON:-$HOME/miniforge3/bin/python3}" "$AUTO" auto /path/to/reviewed.gjf \
  --project dry_test --local-dir /path/to/outputs/dry_test \
  --confirmed --dry-run
```

A dry run may omit the input and live receipts for diagnostic use, but then
reports `live_submission_ready: false` and the exact missing gates. The
`prepare` subcommand is only an input/scientific preflight: even with a valid
input receipt it emits an `incomplete_non_authorizing_preflight` marker and no
live-approval scope. Only `auto --dry-run` with the complete execution-batch,
positive core-hour estimate/evidence, policy, gate, scheduler snapshot and
exact resource tuple emits the canonical non-authorizing `/9`, `/10`, or `/11`
scope consumed by the live validator; it never creates an approved record. A supplied
input receipt is validated; a supplied live receipt is evaluated only after
the input receipt succeeds. A plain `stage` remains a pure offline packaging
operation; its `job.json` explicitly
retains `calculation_ready: false` and `no_submission_authorization: true` and
cannot be promoted by a later live `submit` without the required receipts.

Read [references/input-approval-receipt.md](references/input-approval-receipt.md)
for the exact compatibility boundary and offline construction commands.

Read [references/protocols.md](references/protocols.md) before proposing protocol candidates.

The command examples below the gate describe input preparation and execution
syntax only. Run them only after the required options and selection artifacts
exist and after applying the separate approval appropriate to the action.

The BF3-TS1 run already in progress predates this gate. Never backdate a
proposal or selection for it. Apply the gate to every later retry, candidate,
IRC or endpoint.

## Reviewed execution batches

Use `scripts/execution_batch.py` and
[references/execution-batch-governance.md](references/execution-batch-governance.md)
when several reviewed calculations share one operator batch. One immutable
`gaussian-execution-batch-review/1` initializes one persistent,
hash-bound `gaussian-execution-batch/1` planning ledger with a hard limit of ten
distinct scientific tasks. A task identity binds structure, chemical
hypothesis, method/protocol, calculation objective and relevant input hashes;
filenames, PBS names, aliases, splits and retries cannot reset the cap.

`/1` planning and `/2` idempotent ledgers remain historical. Before every new
live submit, explicitly migrate `/1 -> /2 -> gaussian-execution-batch/3` with
the offline owner CLIs. `/3` consumes one exact reviewed resource policy, one
fresh scheduler-resource snapshot, and one exact resource gate under the
ledger lock before any network action.

The gate binds `/3`'s resource-state projection hash/revision, not the whole
monitor journal. Append-only same/unknown/conflict observations stay hash-
chained without invalidating unrelated reviewed gates; any task, attempt-state,
resource, estimate, or accounting change advances the resource revision.

Reserve each physical attempt atomically before qsub. The reservation begins
as `submission_uncertain` and remains counted and blocks another attempt until
read-only evidence reconciles it. An exact retry consumes no new task slot but
requires a new live approval and the ordinary exact-input hash replay. Any
scientific identity change consumes a new reviewed task slot. The ledger may
classify a failure and support a retry proposal, but it never submits, retries,
changes chemistry, cancels or expands work automatically.

Monitoring is read-only: important state/error events are immediate and the
default cumulative operator-summary cadence is 60 minutes. Batch monitoring
does not broaden the separate repeated-evidence scheduler-zombie qdel policy.

For the v2.5 cross-Skill chain, initialize the reviewed ledger first and then
validate it with `auto-g16-reaction-workflow/scripts/v25_integration.py`. The
overlay requires the immutable review and ledger task sets to equal the
selected closure calculation nodes and preserves the ten-task cap. This is an
offline planning binding only; every attempt still needs the ordinary exact
input review, dependency evidence, and a fresh live approval.

Real `submit` requires the `/3` ledger, stable task ID, idempotency key,
estimated core-hours and its evidence source/hash, exact tier/cores/memory,
explicit walltime, resource policy, scheduler snapshot, and gate. It reserves under lock
before any SSH/SCP/qsub, claims the server project with one atomic `mkdir`
(pre-existing empty directories are refused), uploads exact hashes, and
publishes immutable local/remote receipts. Ambiguous qsub output remains
`submission_uncertain`; never rerun qsub. `reconcile-submission` reads only
remote intent/receipt and exact qstat bindings. One unique match backfills the
job ID; zero or multiple matches stay closed unless absence of the atomic
project directory proves qsub was never reachable.

Build the scheduler input operationally without manual resource inference:

```bash
python scripts/gaussian_rtwin_pbs.py batch-status \
  --job-id 123.master --job-id 124.master > batch-qstat.json
python scripts/resource_efficiency.py build-scheduler-snapshot execution-batch-v3.json batch-qstat.json \
  --snapshot-id reviewed-poll-1 --max-age-seconds 120 --output scheduler-resource-snapshot.json
python scripts/resource_efficiency.py evaluate-gate execution-batch-v3.json \
  --policy resource-policy.json --scheduler-snapshot scheduler-resource-snapshot.json \
  --gate-id gate-1 --evaluated-at 2026-07-19T10:00:00Z \
  --scientific-task-id scientific-task-<sha256> --attempt-id qsub-attempt-<sha256> \
  --project example --input-sha256 <sha256> --resource-tier simple \
  --cores 8 --memory-gb 12 --walltime-seconds 86400 --estimated-core-hours 8 \
  --output resource-gate.json
```

`batch-status` makes one read-only qstat call for the complete active PBS-user
scope; optional `--job-id` values are expectations, never a filter. No IDs plus
rc=0 is the first zero-active path; rc=153 does not prove an empty scope.
Duplicate blocks/resources, owner conflicts, warning/non-job output outside
exact blocks, and incomplete parsing are unknown.
The builder rejects absent/unknown records, missing ledger attempts, state or
resource conflicts, and records without exact cores/memory; multi-node cores
are `nodes * ppn`.

Fresh successful exact monitor evidence may reconcile queued/running/terminal
execution state only when the attempt already has the same non-null scheduler
reference and exact project/input binding. Monitoring never advances
`submission_uncertain`; only `reconcile-submission` may bind its job. Timeout,
stale or conflicting evidence stays append-only.
Only repeated stable interruption proof maps execution to `failed` to release
occupancy; this never accepts a scientific result. The proof needs explicit
scheduler absence, stable log metadata, zero whole-log terminal counts, and at
least 60 seconds of stability/log age. A still-present stale PBS record never
qualifies. Whole-log normal/error counts drive terminal state even when the
marker is outside the tail. Fetch requires the immutable exact terminal
inspection receipt; mutable terminal status alone is never authority.

## Opt-Freq-single-point workflow

Use `scripts/gaussian_workflow.py build` to turn one selected, audited Cartesian input into three linked stages. Require an explicit single-point route and standard state; never infer a research protocol from the molecule.

```bash
WORKFLOW="$HOME/.codex/skills/auto-g16-rtwin-pbs/scripts/gaussian_workflow.py"

"${AUTO_G16_CORE_PYTHON:-$HOME/miniforge3/bin/python3}" "$WORKFLOW" build selected.gjf \
  --output project_ofs.gjf \
  --sp-route '#p <approved-single-point-method/basis> <approved-solvent>' \
  --temperature 298.15 --standard-state 1M
```

The builder is offline only. Its checkpoint-derived `Geom=AllCheck` and
`Guess=Read` stages are outside generic input-approval receipt `/1`; live
submission is fail-closed until a versioned workflow/checkpoint specialist
owner approval is integrated. Do not split or relabel this workflow as an
`ordinary` input to bypass that boundary. Once such an owner contract exists,
the first stage uses the approved Opt route, the second uses Freq, and the third
uses the explicit single-point route. Scientific acceptance still requires
three normal terminations, optimization/stationary-point evidence, zero
imaginary frequencies for a minimum, frequency thermal corrections, and a
final single-point SCF energy.

Fetch automatically recognizes the workflow manifest and writes composite thermochemistry to `result.json`. Do not claim a minimum when an imaginary frequency remains. Do not claim quasi-harmonic treatment: the bundled parser reports low modes but applies no quasi-harmonic correction. Read [references/scientific-workflows.md](references/scientific-workflows.md) before building or interpreting this workflow.

Use `gaussian_workflow.py aggregate` only on scientifically valid workflow results at the same temperature and standard state. It reports relative Gibbs energies and Boltzmann populations.

## Conformer handoff

Accept only conformers promoted by `auto-g16-view-rt-win/scripts/prepare_conformers.py select --confirmed`. The transport preflight must refuse manifests marked `candidate_only` or `calculation_ready: false`. Treat MMFF94s/UFF energies as prescreening values, not Gaussian energies. Build and calculate each retained conformer with the same approved workflow before Boltzmann aggregation.

## Individual operations

For a checkpoint-dependent continuation such as an approved IRC, declare `%oldchk=<reviewed-basename>.chk` explicitly and place that exact non-symlink checkpoint beside the input. The staging layer requires `%oldchk` and `%chk` to be distinct local basenames, includes the old checkpoint in `checksums.sha256`, and transfers it through both hops. It refuses paths, symlinks, missing files, and implicit checkpoint discovery.

When the first route uses `Geom=AllCheck`, require a same-stem `gaussian-allcheck-input-manifest/1` created from the TS Skill's passed checkpoint audit. Require the input to end immediately after the route blank line: no title, charge/multiplicity, or coordinates. Recompute and compare the input and `%oldchk` SHA-256, validate contiguous one-based atom order, and report charge/multiplicity/atom count as checkpoint-derived audited metadata. Refuse staging if any hash or atom-order evidence differs.

```bash
HELPER="$HOME/.codex/skills/auto-g16-rtwin-pbs/scripts/gaussian_rtwin_pbs.py"

"${AUTO_G16_CORE_PYTHON:-$HOME/miniforge3/bin/python3}" "$HELPER" preflight /path/to/job.gjf --project example \
  --scientific-maturity /path/to/maturity-gate.json --edge-id reviewed_edge \
  --node-id reviewed_pilot_node --pilot --work-kind ts_pilot
"${AUTO_G16_CORE_PYTHON:-$HOME/miniforge3/bin/python3}" "$HELPER" submit /path/to/job.gjf --project example \
  --local-dir /path/to/bundle \
  --scientific-maturity /path/to/maturity-gate.json --edge-id reviewed_edge \
  --node-id reviewed_pilot_node --pilot --work-kind ts_pilot \
  --scientific-action-authorization /path/to/scientific-action-authorization.json \
  --input-approval-record /path/to/exact-input-approval.json \
  --approval-record /path/to/live-submission-approval-v3-or-v4.json --confirmed
"${AUTO_G16_CORE_PYTHON:-$HOME/miniforge3/bin/python3}" "$HELPER" inspect --project example --job-id 563.master \
  --input-stem example_cartesian --local-dir /path/to/bundle
"${AUTO_G16_CORE_PYTHON:-$HOME/miniforge3/bin/python3}" "$HELPER" watch --project example --job-id 563.master \
  --input-stem example_cartesian --local-dir /path/to/bundle \
  --output-dir /path/to/results --fetch
"${AUTO_G16_CORE_PYTHON:-$HOME/miniforge3/bin/python3}" "$HELPER" fetch \
  --project example --job-id 563.master --input-stem example_cartesian \
  --local-dir /path/to/bundle --output-dir /path/to/new-results-snapshot
"${AUTO_G16_CORE_PYTHON:-$HOME/miniforge3/bin/python3}" "$HELPER" analyze /path/to/results/example_cartesian.log \
  --output-dir /path/to/results
```

Active cancellation does not rely on `--confirmed`. It requires a fresh
`auto-g16-exact-cancellation-approval/1` binding approver/time/project/job ID,
current local job-state hash and exact attempt hash, then consumes it into one
immutable receipt. Cancellation never authorizes retry, cleanup or deletion.

## PBS zombie records

Treat terminal scheduler-zombie cleanup as an automatic evidence-gated operation after results are fetched. This standing policy applies only to a repeatedly proven zombie bound to the exact local job record; it never authorizes cancellation of a queued or running job.

1. Run `diagnose-zombie` first. It binds the request to local `job.json`, requires `results_fetched: true`, and observes the same job twice at least 5 seconds apart.
2. Classify `confirmed_scheduler_zombie` only when both observations show the exact PBS job name, PBS `R`, a present session ID with no session process, unchanged log size and mtime, and terminal Gaussian evidence. A Link1 workflow must have all expected normal terminations or a definite error termination.
3. Record the exact project, job ID, evidence, and the fact that only scheduler state will change. No per-job confirmation is required after every eligibility check passes.
4. Run `cleanup-zombie`, or let `watch --fetch` invoke it automatically. It diagnoses again, issues at most one exact `qdel <job-id>`, and verifies with `qstat`. `cleared` requires an accepted qdel outcome (`0` or explicit `Unknown Job Id`) and an explicit post-qdel `Unknown Job Id`; qdel, qstat, transport or parse failure is `cleanup_unverified`. Never retry `qdel` automatically.
5. If the record self-purges during diagnosis, report `self_purged` and issue no `qdel`. Refuse cleanup for `Q`, `H`, `E`, a live or unknown session, a changing log, a job-name mismatch, missing terminal evidence, or results not yet fetched.

```bash
HELPER="$HOME/.codex/skills/auto-g16-rtwin-pbs/scripts/gaussian_rtwin_pbs.py"

# Read-only two-observation diagnosis
"${AUTO_G16_CORE_PYTHON:-$HOME/miniforge3/bin/python3}" "$HELPER" diagnose-zombie \
  --project example --job-id 565.master --input-stem example \
  --local-dir /path/to/bundle --stability-seconds 10

# Automatic only after the repeated evidence gate passes
"${AUTO_G16_CORE_PYTHON:-$HOME/miniforge3/bin/python3}" "$HELPER" cleanup-zombie \
  --project example --job-id 565.master --input-stem example \
  --local-dir /path/to/bundle --stability-seconds 10 \
  --verify-seconds 5
```

Zombie cleanup changes only a PBS-owned record. It never deletes or modifies `/home/user100/SDL/<project>` data.

## Completion evidence

- For optimization success, require `Normal termination` and optimization/stationary-point evidence. For a same-input `Opt ... Freq` job, require the expected final frequency output and a terminal process/PBS observation; the first normal termination can belong only to the Opt stage.
- Preserve input, manifest, PBS file, checksums, log, checkpoint, local `job.json`, `result.json`, and optimized XYZ.
- Fetch only after terminal classification. Bind the request to the exact local `job.json` project/job/input stem, generate a server allowlist from staged checksums plus the exact log and named outputs, and copy only those basenames. Scratch and unrelated files are excluded. Verify SHA-256 on server, RTwin and Mac before parsing only `<input_stem>.log`.
- Every fetch target is one immutable snapshot. It must be new or empty; an old, concurrent or partially transferred target is rejected. A failed attempt leaves its local in-progress marker for audit. Retry transfer into a new output directory; no retry submits, qdel, deletes or overwrites anything.
- `fetch --reuse-snapshot <old-transfer-or-directory>` may reuse only old complete
  files whose exact project/job/input binding, remote manifest size/hash and
  freshly recomputed local size/hash all match. Reuse makes a private fsynced
  no-clobber copy (never a shared inode); only changed files cross
  server -> RTwin -> Mac. The new snapshot is still a full independent set.
- Report final SCF energy only from a completed log.
- If frequencies were requested, report imaginary-frequency count; never imply a minimum without a frequency calculation.

Read [references/environment-and-failures.md](references/environment-and-failures.md) for connection, stale PBS, fetch, and restart decisions.
Read [references/runtime-safety-compatibility.md](references/runtime-safety-compatibility.md) for additive inspection fields and the direct-fetch migration.

## Bundled scripts

- `scripts/protocol_selection.py`: standard-library-only three-tier proposal,
  explicit selection, hash verification and offline input-draft authorization.
- `scripts/execution_batch.py`: standard-library-only locked execution-batch
  ledger, explicit `/1` to `/2` migration, stable scientific-task identity,
  evidence-bound core-hour accounting, retry classification and read-only
  monitoring summaries.
- `scripts/gaussian_auto.py`: exact-input approval gate and one-command
  submission through analyzed results; raw structure-to-method preparation is
  intentionally unsupported.
- `scripts/gaussian_rtwin_pbs.py`: preflight, stage, submit, inspect, watch, fetch, analyze, repeated-evidence automatic zombie cleanup, and confirmation-gated active-job cancellation.
- `scripts/gaussian_log.py`: deterministic Gaussian result and geometry parser.
- `scripts/gaussian_workflow.py`: build and analyze Opt-Freq-single-point workflows and aggregate conformer populations.

Read [references/live-approval-record.md](references/live-approval-record.md)
before creating an exact live approval or invoking a non-dry-run `auto` command.
