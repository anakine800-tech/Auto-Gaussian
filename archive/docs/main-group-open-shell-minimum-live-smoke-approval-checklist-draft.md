# Auto-G16 main-group open-shell minimum live-smoke approval checklist draft

This is an offline review checklist, not an
`auto-g16-live-submission-approval/4` record. It grants no submission,
directory-creation, retry, cancellation, cleanup, deletion or deployment
authority.

## Exact prerequisites

- [ ] The Gaussian input is one self-contained Cartesian main-group
      open-shell minimum Opt/Freq job: no TS, IRC, scan, QST2/QST3, Link1,
      checkpoint-derived geometry/wavefunction, metal, open-shell singlet,
      broken-symmetry or multireference state.
- [ ] Charge, multiplicity 2 or 3, route, U/RO reference, structure identity,
      selected protocol option, resource tier, memory and cores were reviewed.
- [ ] `gaussian-input-approval-receipt/2` fully owner-replays the exact
      electronic-state review, minimum input handoff and passed input audit.
- [ ] Receipt `/2` still has `calculation_ready: false` and
      `no_submission_authorization: true`; it is not treated as live approval.
- [ ] The project is fresh, matches `^[A-Za-z0-9][A-Za-z0-9_-]{0,14}$`, and
      the canonical remote directory is exactly
      `/home/user100/SDL/<project>` with no symlink or pre-existing contents.

## Exact `/4` fields to show for separate owner approval

- [ ] `schema` is exactly `auto-g16-live-submission-approval/4`; `decision` is
      `approved` and `explicit_confirmation` is `true` only after review.
- [ ] Scope binds project, canonical remote directory, exact input SHA-256,
      exact route, memory, cores, charge, multiplicity and
      `work_kind: minimum`.
- [ ] `input_approval` binds receipt schema `/2`, receipt file SHA-256, receipt
      payload SHA-256, input SHA-256 and matching work kind.
- [ ] `open_shell_owner` binds owner
      `auto-g16-main-group-open-shell`, workflow
      `main_group_open_shell_minimum_opt_freq_v1`, electronic-state-review,
      handoff, audit and selected-option payload SHA-256 values, input SHA-256,
      exact route, charge, multiplicity, U/RO reference, resource tier, memory,
      cores and `owner_replay_passed: true`.
- [ ] Authorizations are exactly: create fresh server directory `true`, submit
      once `true`, retry `false`, cancel `false`, cleanup `false`, and delete
      server data `false`.
- [ ] Direct `submit` and wrapper `auto` produce the same required schema and
      scope proposal in offline dry-run before this record is created.

## Minimum live-smoke success and stop conditions

Success requires one exact submitted job, a complete newly fetched log,
Gaussian normal termination, explicit optimization/stationary-point evidence,
a complete frequency parse, exactly zero imaginary frequencies, reviewed
open-shell stability/reference evidence, and retained hashes matching the
approved input and owner chain.

Stop immediately without retry, input/method/resource mutation, cancellation,
cleanup or deletion if any preflight hash or field differs; the server path is
not the exact fresh directory; transport or scheduler identity is uncertain;
upload/staging bytes differ; submission outcome is uncertain; PBS/process/log
state conflicts; Gaussian terminates abnormally; optimization fails; frequency
output is incomplete; any imaginary frequency appears; wavefunction stability,
spin contamination or reference evidence fails owner policy; or any result
cannot be tied back to the exact approved input. A new attempt requires a new
reviewed chain and a new exact live approval.
