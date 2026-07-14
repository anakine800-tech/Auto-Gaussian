---
name: auto-g16-rtwin-pbs
description: Present and record hash-bound loose/standard/strict Gaussian protocol candidates before input drafting, then prepare, submit, monitor, fetch, and analyze approved Gaussian 16 calculations through the user's RTwin Windows SSH bridge to the private PBS server. Includes audited Opt-Freq-single-point workflows, thermochemistry, conformer aggregation, per-hop SHA-256, overwrite prevention, robust state classification, scheduler-zombie cleanup, and confirmation-gated cancellation. Use for protocol-rigor comparisons or organic Gaussian jobs on <PBS_PRIVATE_IP> reachable only through RTwin. All server data and scratch are confined to /home/user100/SDL.
---

# Auto-G16 RTwin PBS

Use `scripts/gaussian_auto.py` for the closed loop and `scripts/gaussian_rtwin_pbs.py` for individual operations. Keep scientific approval as the only human gate; after separate exact live approval, allow preparation, submission, monitoring, fetching, and analysis to run unattended.

## Input-before protocol gate

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

## Fixed environment

- Mac SSH alias: `rtwin` in `<MAC_HOME>/Documents/用RTwin进行计算/config/ssh_config`
- RTwin server alias: `gaussian-server` in `<WINDOWS_HOME>\.ssh\gaussian_server_config`
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
3. Only after selection, render or audit the offline input draft. Show source hash, identity, warnings, exact route, charge/multiplicity, atom count, cores, memory and remote directory.
4. After separate exact approval of the rendered input and job, run the approved execution path. It submits once, monitors, fetches, and writes `result.json` plus `optimized.xyz` when coordinates are available.
5. Classify state from three sources: PBS record, PBS session process, and Gaussian log. Treat PBS `Q` with no session/process/log as a valid queued job, not a failed launch. For a 44-core full-node request, unavailable capacity is a common explanation, but `Q` alone does not prove the server is full; report a specific reason only when PBS exposes one. Wait without duplicate submission, automatic resource reduction, cancellation, or method changes. A live PBS `R` session always outranks an earlier `Normal termination` in a multi-stage input such as `Opt ... Freq`; do not fetch or interpret a partial log as final. A stale PBS `R` without a process is not a running calculation, but one observation is only a zombie candidate. After terminal fetch, `watch` automatically performs the repeated zombie audit and issues at most one exact `qdel` only if every cleanup check passes.
6. On failure, stop after analysis. Do not silently add SCF options, change geometry, change method/basis, or resubmit. Report diagnostics and create a new proposal and selection for any changed restart.

```bash
AUTO="$HOME/.codex/skills/auto-g16-rtwin-pbs/scripts/gaussian_auto.py"

# Review only
python3 "$AUTO" prepare /path/to/structure.cdx \
  --project example --local-dir /path/to/outputs/example \
  --protocol organic-opt --resource-tier general \
  --charge 0 --multiplicity 1

# Approved unattended run
python3 "$AUTO" auto /path/to/structure.cdx \
  --project example --local-dir /path/to/outputs/example \
  --protocol organic-opt --resource-tier general \
  --charge 0 --multiplicity 1 \
  --confirmed --watch
```

For a fast workflow test only:

```bash
python3 "$AUTO" auto 'O' \
  --project h2o_test --local-dir /path/to/outputs/h2o_test \
  --protocol smoke-test --charge 0 --multiplicity 1 \
  --confirmed --watch --poll-seconds 5 --timeout-seconds 600
```

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
AUTO="$HOME/.codex/skills/auto-g16-rtwin-pbs/scripts/gaussian_auto.py"

python3 "$WORKFLOW" build selected.gjf \
  --output project_ofs.gjf \
  --sp-route '#p <approved-single-point-method/basis> <approved-solvent>' \
  --temperature 298.15 --standard-state 1M

python3 "$AUTO" auto project_ofs.gjf \
  --project project_ofs --local-dir /path/to/project_ofs \
  --confirmed --watch
```

The first stage uses the approved Opt route. The second stage uses the same method with Freq, `Geom=AllCheck`, and `Guess=Read` unless an explicit Freq route is supplied. The third stage uses the explicit single-point route. Gaussian execution proceeds after normal Link1 termination; scientific acceptance occurs after parsing. Require three normal terminations, optimization/stationary-point evidence, zero imaginary frequencies for a minimum, frequency thermal corrections, and a final single-point SCF energy.

Fetch automatically recognizes the workflow manifest and writes composite thermochemistry to `result.json`. Do not claim a minimum when an imaginary frequency remains. Do not claim quasi-harmonic treatment: the bundled parser reports low modes but applies no quasi-harmonic correction. Read [references/scientific-workflows.md](references/scientific-workflows.md) before building or interpreting this workflow.

Use `gaussian_workflow.py aggregate` only on scientifically valid workflow results at the same temperature and standard state. It reports relative Gibbs energies and Boltzmann populations.

## Conformer handoff

Accept only conformers promoted by `auto-g16-view-rt-win/scripts/prepare_conformers.py select --confirmed`. The transport preflight must refuse manifests marked `candidate_only` or `calculation_ready: false`. Treat MMFF94s/UFF energies as prescreening values, not Gaussian energies. Build and calculate each retained conformer with the same approved workflow before Boltzmann aggregation.

## Individual operations

For a checkpoint-dependent continuation such as an approved IRC, declare `%oldchk=<reviewed-basename>.chk` explicitly and place that exact non-symlink checkpoint beside the input. The staging layer requires `%oldchk` and `%chk` to be distinct local basenames, includes the old checkpoint in `checksums.sha256`, and transfers it through both hops. It refuses paths, symlinks, missing files, and implicit checkpoint discovery.

When the first route uses `Geom=AllCheck`, require a same-stem `gaussian-allcheck-input-manifest/1` created from the TS Skill's passed checkpoint audit. Require the input to end immediately after the route blank line: no title, charge/multiplicity, or coordinates. Recompute and compare the input and `%oldchk` SHA-256, validate contiguous one-based atom order, and report charge/multiplicity/atom count as checkpoint-derived audited metadata. Refuse staging if any hash or atom-order evidence differs.

```bash
HELPER="$HOME/.codex/skills/auto-g16-rtwin-pbs/scripts/gaussian_rtwin_pbs.py"

python3 "$HELPER" preflight /path/to/job.gjf --project example
python3 "$HELPER" submit /path/to/job.gjf --project example \
  --local-dir /path/to/bundle --confirmed
python3 "$HELPER" inspect --project example --job-id 563.master \
  --input-stem example_cartesian --local-dir /path/to/bundle
python3 "$HELPER" watch --project example --job-id 563.master \
  --input-stem example_cartesian --local-dir /path/to/bundle \
  --output-dir /path/to/results --fetch
python3 "$HELPER" analyze /path/to/results/example_cartesian.log \
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
python3 "$HELPER" diagnose-zombie \
  --project example --job-id 565.master --input-stem example \
  --local-dir /path/to/bundle --stability-seconds 10

# Automatic only after the repeated evidence gate passes
python3 "$HELPER" cleanup-zombie \
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
- `scripts/gaussian_auto.py`: one-command preparation through analyzed results.
- `scripts/gaussian_rtwin_pbs.py`: preflight, stage, submit, inspect, watch, fetch, analyze, repeated-evidence automatic zombie cleanup, and confirmation-gated active-job cancellation.
- `scripts/gaussian_log.py`: deterministic Gaussian result and geometry parser.
- `scripts/gaussian_workflow.py`: build and analyze Opt-Freq-single-point workflows and aggregate conformer populations.
