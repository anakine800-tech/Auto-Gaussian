---
name: gaussian-rtwin-pbs
description: Prepare, submit, monitor, fetch, and analyze Gaussian 16 calculations through the user's RTwin Windows SSH bridge to the private PBS server, including audited Opt-Freq-single-point Link1 workflows, thermochemistry and Boltzmann aggregation, reviewed conformer handoff, per-hop SHA-256, duplicate/overwrite prevention, robust state classification, repeated-evidence PBS zombie diagnosis, and explicit-confirmation scheduler cleanup or cancellation. Use for organic Gaussian jobs on <PBS_PRIVATE_IP> reachable only through RTwin. All server data and scratch are strictly confined to /home/user100/SDL.
---

# Gaussian RTwin PBS

Use `scripts/gaussian_auto.py` for the closed loop and `scripts/gaussian_rtwin_pbs.py` for individual operations. Keep scientific approval as the only human gate; after approval, allow preparation, submission, monitoring, fetching, and analysis to run unattended.

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
- Use `qsub/qstat` and explicitly approved `qdel` only for PBS-owned state. Never access scheduler spool directories.

## One-command workflow

1. Resolve structure, stereochemistry, charge, multiplicity, protocol, and resource tier. Use `general` when complexity is not clearly simple or complex. For CDX/CDXML, rely on the corrected explicit-H/CFG importer in `gaussian-view-rt-win`.
2. Run `prepare` when approval is still needed. Show source hash, identity, warnings, route, charge/multiplicity, atom count, cores, memory, and remote directory.
3. After exact approval, run `auto --confirmed --watch`. It prepares or audits the input, submits once, monitors, fetches, and writes `result.json` plus `optimized.xyz` when coordinates are available.
4. Classify state from three sources: PBS record, PBS session process, and Gaussian log. A live PBS `R` session always outranks an earlier `Normal termination` in a multi-stage input such as `Opt ... Freq`; do not fetch or interpret a partial log as final. A stale PBS `R` without a process is not a running calculation, but one observation is only a zombie candidate.
5. On failure, stop after analysis. Do not silently add SCF options, change geometry, change method/basis, or resubmit. Report diagnostics and require explicit approval for any restart.

```bash
AUTO="$HOME/.codex/skills/gaussian-rtwin-pbs/scripts/gaussian_auto.py"

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

Read [references/protocols.md](references/protocols.md) before choosing a default protocol.

## Opt-Freq-single-point workflow

Use `scripts/gaussian_workflow.py build` to turn one selected, audited Cartesian input into three linked stages. Require an explicit single-point route and standard state; never infer a research protocol from the molecule.

```bash
WORKFLOW="$HOME/.codex/skills/gaussian-rtwin-pbs/scripts/gaussian_workflow.py"
AUTO="$HOME/.codex/skills/gaussian-rtwin-pbs/scripts/gaussian_auto.py"

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

Accept only conformers promoted by `gaussian-view-rt-win/scripts/prepare_conformers.py select --confirmed`. The transport preflight must refuse manifests marked `candidate_only` or `calculation_ready: false`. Treat MMFF94s/UFF energies as prescreening values, not Gaussian energies. Build and calculate each retained conformer with the same approved workflow before Boltzmann aggregation.

## Individual operations

For a checkpoint-dependent continuation such as an approved IRC, declare `%oldchk=<reviewed-basename>.chk` explicitly and place that exact non-symlink checkpoint beside the input. The staging layer requires `%oldchk` and `%chk` to be distinct local basenames, includes the old checkpoint in `checksums.sha256`, and transfers it through both hops. It refuses paths, symlinks, missing files, and implicit checkpoint discovery.

```bash
HELPER="$HOME/.codex/skills/gaussian-rtwin-pbs/scripts/gaussian_rtwin_pbs.py"

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

Treat scheduler cleanup as a separate, confirmation-gated operation after results are fetched. Never infer permission to run `qdel` from permission to submit, monitor, or fetch.

1. Run `diagnose-zombie` first. It binds the request to local `job.json`, requires `results_fetched: true`, and observes the same job twice at least 5 seconds apart.
2. Classify `confirmed_scheduler_zombie` only when both observations show the exact PBS job name, PBS `R`, a present session ID with no session process, unchanged log size and mtime, and terminal Gaussian evidence. A Link1 workflow must have all expected normal terminations or a definite error termination.
3. Show the exact project, job ID, evidence, and the fact that only scheduler state will change. Obtain explicit user approval for that exact job.
4. Only then run `cleanup-zombie --confirmed`. It diagnoses again, issues at most one exact `qdel <job-id>`, and verifies with `qstat`. Never retry `qdel` automatically.
5. If the record self-purges during diagnosis, report `self_purged` and issue no `qdel`. Refuse cleanup for `Q`, `H`, `E`, a live or unknown session, a changing log, a job-name mismatch, missing terminal evidence, or results not yet fetched.

```bash
HELPER="$HOME/.codex/skills/gaussian-rtwin-pbs/scripts/gaussian_rtwin_pbs.py"

# Read-only two-observation diagnosis
python3 "$HELPER" diagnose-zombie \
  --project example --job-id 565.master --input-stem example \
  --local-dir /path/to/bundle --stability-seconds 10

# Only after the user explicitly confirms this exact project and job ID
python3 "$HELPER" cleanup-zombie \
  --project example --job-id 565.master --input-stem example \
  --local-dir /path/to/bundle --stability-seconds 10 \
  --verify-seconds 5 --confirmed
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

- `scripts/gaussian_auto.py`: one-command preparation through analyzed results.
- `scripts/gaussian_rtwin_pbs.py`: preflight, stage, submit, inspect, watch, fetch, analyze, repeated-evidence zombie diagnosis, confirmation-gated scheduler cleanup, and cancellation.
- `scripts/gaussian_log.py`: deterministic Gaussian result and geometry parser.
- `scripts/gaussian_workflow.py`: build and analyze Opt-Freq-single-point workflows and aggregate conformer populations.
