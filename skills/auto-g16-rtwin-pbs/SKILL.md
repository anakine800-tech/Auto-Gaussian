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

For a TS/QST route, first display and validate the reaction-workflow
`gaussian-scientific-maturity-gate/1`. It shows maturity, evidence, accepted
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
   `gaussian-input-approval-receipt/1`. The receipt replays the exact protocol
   options and selection, selected option, the non-empty task/profile subset
   consumed by this input, human-confirmed route/method/basis/solvent/SCF
   mapping, resources, identity and input SHA-256. It never claims whole-family
   completion and grants no live authority. Record a new
   `auto-g16-live-submission-approval/3` that binds explicit `work_kind` plus
   the exact input-approval receipt file and payload hashes. TS `/3` scopes also
   bind the exact maturity and scientific-action authorization. Historical live
   `/1` and `/2` records remain replayable under their original contracts but
   do not satisfy the new submission chain. The low-level `submit` command
   independently validates the same shared receipt; `--confirmed` is only an
   additional command confirmation.
5. Classify state from three sources: PBS record, PBS session process, and Gaussian log. Treat PBS `Q` with no session/process/log as a valid queued job, not a failed launch. For a 44-core full-node request, unavailable capacity is a common explanation, but `Q` alone does not prove the server is full; report a specific reason only when PBS exposes one. Wait without duplicate submission, automatic resource reduction, cancellation, or method changes. A live PBS `R` session always outranks an earlier `Normal termination` in a multi-stage input such as `Opt ... Freq`; do not fetch or interpret a partial log as final. A stale PBS `R` without a process is not a running calculation, but one observation is only a zombie candidate. After terminal fetch, `watch` automatically performs the repeated zombie audit and issues at most one exact `qdel` only if every cleanup check passes.
6. On failure, stop after analysis. Do not silently add SCF options, change geometry, change method/basis, or resubmit. Report diagnostics and create a new proposal and selection for any changed restart.

```bash
AUTO="$HOME/.codex/skills/auto-g16-rtwin-pbs/scripts/gaussian_auto.py"

# Review an already rendered input only
"${AUTO_G16_CORE_PYTHON:-$HOME/miniforge3/bin/python3}" "$AUTO" prepare /path/to/reviewed.gjf \
  --project example --local-dir /path/to/outputs/example

# Approved unattended run
"${AUTO_G16_CORE_PYTHON:-$HOME/miniforge3/bin/python3}" "$AUTO" auto /path/to/reviewed.gjf \
  --project example --local-dir /path/to/outputs/example \
  --scientific-maturity /path/to/maturity-gate.json --edge-id reviewed_edge \
  --node-id reviewed_pilot_node --pilot --work-kind ts_pilot \
  --scientific-action-authorization /path/to/scientific-action-authorization.json \
  --input-approval-record /path/to/exact-input-approval.json \
  --approval-record /path/to/live-submission-approval-v3.json \
  --confirmed --watch
```

For a local dry run that performs no SSH, PBS or Gaussian action:

```bash
"${AUTO_G16_CORE_PYTHON:-$HOME/miniforge3/bin/python3}" "$AUTO" auto /path/to/reviewed.gjf \
  --project dry_test --local-dir /path/to/outputs/dry_test \
  --confirmed --dry-run
```

A dry run may omit the input and live receipts for diagnostic use, but then
reports `live_submission_ready: false` and the exact missing gates. A supplied
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
  --approval-record /path/to/live-submission-approval-v3.json --confirmed
"${AUTO_G16_CORE_PYTHON:-$HOME/miniforge3/bin/python3}" "$HELPER" inspect --project example --job-id 563.master \
  --input-stem example_cartesian --local-dir /path/to/bundle
"${AUTO_G16_CORE_PYTHON:-$HOME/miniforge3/bin/python3}" "$HELPER" watch --project example --job-id 563.master \
  --input-stem example_cartesian --local-dir /path/to/bundle \
  --output-dir /path/to/results --fetch
"${AUTO_G16_CORE_PYTHON:-$HOME/miniforge3/bin/python3}" "$HELPER" analyze /path/to/results/example_cartesian.log \
  --output-dir /path/to/results
```

Run `cancel --confirmed` only after the user explicitly identifies the job to stop. Cancellation never authorizes file deletion.

## PBS zombie records

Treat terminal scheduler-zombie cleanup as an automatic evidence-gated operation after results are fetched. This standing policy applies only to a repeatedly proven zombie bound to the exact local job record; it never authorizes cancellation of a queued or running job.

1. Run `diagnose-zombie` first. It binds the request to local `job.json`, requires `results_fetched: true`, and observes the same job twice at least 5 seconds apart.
2. Classify `confirmed_scheduler_zombie` only when both observations show the exact PBS job name, PBS `R`, a present session ID with no session process, unchanged log size and mtime, and terminal Gaussian evidence. A Link1 workflow must have all expected normal terminations or a definite error termination.
3. Record the exact project, job ID, evidence, and the fact that only scheduler state will change. No per-job confirmation is required after every eligibility check passes.
4. Run `cleanup-zombie`, or let `watch --fetch` invoke it automatically. It diagnoses again, issues at most one exact `qdel <job-id>`, and verifies with `qstat`. Never retry `qdel` automatically.
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
- Fetch only after terminal classification, then parse the newly fetched log. If a prior fetch ended during a running second stage, fetch again before reporting frequencies, thermochemistry, or a TS conclusion.
- Report final SCF energy only from a completed log.
- If frequencies were requested, report imaginary-frequency count; never imply a minimum without a frequency calculation.

Read [references/environment-and-failures.md](references/environment-and-failures.md) for connection, stale PBS, fetch, and restart decisions.

## Bundled scripts

- `scripts/protocol_selection.py`: standard-library-only three-tier proposal,
  explicit selection, hash verification and offline input-draft authorization.
- `scripts/gaussian_auto.py`: exact-input approval gate and one-command
  submission through analyzed results; raw structure-to-method preparation is
  intentionally unsupported.
- `scripts/gaussian_rtwin_pbs.py`: preflight, stage, submit, inspect, watch, fetch, analyze, repeated-evidence automatic zombie cleanup, and confirmation-gated active-job cancellation.
- `scripts/gaussian_log.py`: deterministic Gaussian result and geometry parser.
- `scripts/gaussian_workflow.py`: build and analyze Opt-Freq-single-point workflows and aggregate conformer populations.

Read [references/live-approval-record.md](references/live-approval-record.md)
before creating an exact live approval or invoking a non-dry-run `auto` command.
