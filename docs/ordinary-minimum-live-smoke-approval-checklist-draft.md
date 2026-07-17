# Auto-G16 ordinary/minimum single-job live smoke approval checklist (draft)

Status: **blocked draft; no live authority**. This document is a review aid. It
is not an `auto-g16-live-submission-approval/3` record and does not authorize
SSH, directory creation, upload, PBS, Gaussian, retry, cancellation, cleanup,
deletion, deployment, or any other live action.

## Source gate and current blocker

- [ ] Select exactly one input source: an existing, verifiable repository
      artifact/fixture or explicit human-supplied input.
- [ ] Record the source path or human handoff identifier and its SHA-256.
- [ ] Confirm that the source is an exact, reviewed, self-contained Cartesian
      input eligible for generic `gaussian-input-approval-receipt/1` as either
      `ordinary` or `minimum`.

No qualifying real owner-approved input exists in this checkout. The H2
ordinary/minimum examples in `tests/test_gaussian_auto_gate.py` are temporary
synthetic test data whose input approvals are mocked. The tracked `.gjf`
fixtures are QST/TS or metal-observation inputs and are therefore protected or
specialist material, not generic ordinary/minimum live-smoke candidates. None
may be promoted to live use by this checklist.

**Blocking action:** an owner must explicitly supply or select one exact
ordinary/minimum input and its reviewed protocol artifacts. Until then, every
field below remains unapproved and no exact input hash or server project name
can be finalized.

## Exact scientific identity review

- [ ] Work kind is exactly one of `ordinary` or `minimum`: `<BLOCKED>`.
- [ ] Chemical identity and composition: `<BLOCKED: owner input required>`.
- [ ] Full Cartesian structure and atom order were displayed and reviewed.
- [ ] Stereochemistry, including a statement that stereochemistry is absent or
      not applicable when appropriate: `<BLOCKED>`.
- [ ] Charge: `<BLOCKED>`.
- [ ] Multiplicity: `<BLOCKED>`.
- [ ] The selected electronic state is within the supported generic receipt
      boundary; no metal, open-shell specialist, crossing, TS, scan, path,
      checkpoint-derived, or ambiguous state is hidden by the work-kind label.

## Protocol and exact input review

- [ ] `gaussian-protocol-options/1` presents the reviewed `loose`, `standard`,
      and `strict` candidates without inferred scientific choices.
- [ ] `gaussian-protocol-selection/1` records the owner's exact selection and
      replays against the options payload.
- [ ] Exact route: `<BLOCKED: must come from the selected owner protocol>`.
- [ ] Method, basis/ECP, solvent/environment, SCF, numerical settings, and any
      thermochemistry choices are explicitly mapped to the selected protocol;
      none are inferred from the molecule or smoke-test label.
- [ ] The input contains one route section and is self-contained Cartesian. It
      contains no `--Link1--`, `%oldchk`, `Geom=Check`, `Geom=AllCheck`,
      `Guess=Read`, QST, `FOpt`, `POpt`, IRC, scan, relaxed-scan tail, specialist
      path keyword, or protected `Opt(Saddle=N)` with `N >= 1`.
- [ ] For `ordinary`, the route contains no optimization or frequency family.
- [ ] For `minimum`, the route contains a non-TS, non-scan `Opt`; any requested
      minimum claim also requires a completed frequency calculation with zero
      imaginary frequencies after the run.
- [ ] Exact complete input text was displayed and reviewed.
- [ ] Exact input SHA-256: `<BLOCKED: compute only after input bytes are final>`.
- [ ] `gaussian-input-draft-review/2` was finalized without overwrite.
- [ ] `gaussian-input-approval-receipt/1` replays successfully and binds the
      exact protocol files, task/profile subset, route mapping, identity,
      resources, atom inventory, charge, multiplicity, and input SHA-256.

## Resources and fresh server scope

- [ ] Resource tier is `simple`: 12 GB memory and 8 cores. Any different or
      smaller explicitly chosen custom smoke-test resource must be separately
      justified and approved; `general` or `complex` is not implicit.
- [ ] Exact `%mem`: `12GB` unless a reviewed custom value is approved.
- [ ] Exact `%nprocshared`: `8` unless a reviewed custom value is approved.
- [ ] Fresh project name: `<BLOCKED: choose only after the exact input is set>`.
- [ ] Canonical remote directory:
      `/home/user100/SDL/<BLOCKED-fresh-project>`.
- [ ] A read-only preflight proves the resolved project path is a non-symlink
      below canonical `/home/user100/SDL` and the target project directory is
      new and empty. Never upload to a non-empty directory or overwrite a job.
- [ ] Scratch is exactly below the fresh project directory, never `/tmp`.

## Exact live `/3` approval

- [ ] Create a new `auto-g16-live-submission-approval/3` only after every field
      above is complete and shown to the owner.
- [ ] The `/3` scope binds the exact project, canonical remote directory, input
      SHA-256, route, memory, cores, charge, multiplicity, and explicit
      `work_kind`.
- [ ] Its `input_approval` object binds the exact
      `gaussian-input-approval-receipt/1` file SHA-256, payload SHA-256, input
      SHA-256, and matching work kind.
- [ ] Decision is `approved` with explicit confirmation for one submission.
- [ ] Authorizations are exactly: create the fresh server directory `true`,
      submit once `true`, retry `false`, cancel `false`, cleanup `false`, and
      delete server data `false`.
- [ ] Historical live `/1` or `/2` records are not reused. Generic input receipt
      plus live `/3` is not used for any protected TS/scan/IRC work.
- [ ] `--confirmed` is treated only as command confirmation and never as a
      substitute for either exact receipt.

## Success and stop conditions

Success requires all of the following for the one exact job:

- terminal PBS/process classification and a newly fetched complete log;
- Gaussian `Normal termination` appropriate to the exact single-stage input;
- for optimization, explicit optimization/stationary-point evidence;
- when frequencies are requested, a complete frequency parse;
- for a minimum claim, exactly zero imaginary frequencies; and
- a parsed structured result whose input and retained evidence hashes match the
  approved scope.

Stop without retry, mutation, cancellation, or cleanup if any of the following
occurs:

- any identity, stereochemistry, charge, multiplicity, route, resource, input,
  receipt, project, or hash mismatch;
- the project path is outside `/home/user100/SDL`, is a symlink, already exists
  non-empty, or would overwrite data;
- the input is classified as protected/specialist or no longer matches the
  approved ordinary/minimum contract;
- SSH/host-key, transfer, PBS, process, or Gaussian state is ambiguous;
- error termination, incomplete stage, missing stationary-point/frequency
  evidence, an imaginary frequency for a claimed minimum, or another
  scientific acceptance failure;
- budget or resource scope differs from approval; or
- any change to chemistry, method, route, resources, project, or bytes would be
  needed. Such a change requires a fresh proposal, input review, receipts, and
  exact approval; there is no automatic retry.

## Evidence retention and claim limits

- [ ] Preserve the exact input, protocol options and selection, input review,
      input-approval receipt, live `/3` record, manifests, input and transfer
      checksums, PBS file, immutable source snapshot, local `job.json`, full
      fetched log, checkpoint when produced, `result.json`, optimized XYZ when
      produced, and terminal PBS/process observations.
- [ ] Record job ID and every retained artifact hash without recording secrets,
      credentials, local SSH configuration, or private server data in Git.
- [ ] Report a queued job as queued unless PBS exposes a more specific reason.
- [ ] Do not report final energies or frequencies from a partial log.
- [ ] Do not claim a minimum without the required frequency evidence, and do
      not generalize one smoke job into method validation, family completion,
      deployment readiness, TS/IRC validation, or scientific accuracy.
- [ ] No server-file deletion is authorized. Active-job cancellation requires
      separate approval for the exact PBS job ID; terminal scheduler-zombie
      handling remains governed by its separate repeated-evidence policy.

## Release-candidate disposition

Current disposition: **blocked before exact input review**. Candidate release
testing may validate this checklist and the offline fail-closed implementation,
but the release-candidate task must not perform the live smoke. A later live
operator must obtain owner approval for the exact completed scope in a separate
task before invoking any non-dry-run command.
