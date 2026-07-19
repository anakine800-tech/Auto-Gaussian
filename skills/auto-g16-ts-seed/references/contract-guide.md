# Auto-G16 TS Seed Contract Guide

## Candidate contract

`gaussian-ts-seed-candidate/1` records one reviewed scientific hypothesis and
one reaction-coordinate lineage. Its source JSON supplies every scientific
field; the builder adds only schema identifiers, deterministic hashes,
eligibility, and fixed non-execution flags.

Every artifact reference has `path`, file `sha256`, `size_bytes`, `schema`, and
`payload_sha256`. Paths are relative to the source package. Referenced JSON
must contain and reproduce its declared payload hash.

The ordered `precedence_review` contains all six strategies. The selected
strategy has status `selected`; every higher-priority strategy is `unavailable`
or `rejected_with_rationale`; lower-priority strategies are
`not_evaluated_lower_priority`. De novo is therefore possible only after all
five stronger sources have explicit dispositions.

`portfolio_eligible` is derived, never asserted by the author. It is true only
when scientific review, geometry sanity, clash review, and any required
open-shell/metal specialist review all pass.

## Portfolio contract

`gaussian-ts-seed-portfolio/1` binds candidate files by file and payload hash.
It requires exactly one primary and permits at most one backup under normal
policy. Both must have distinct coordinate fingerprints and distinct
hypothesis signatures; changing only a face, angle, distance, or Cartesian
placement cannot create an independent backup.

A portfolio larger than two requires `exception_review.approved: true`, a
non-empty `new_scientific_rationale`, `user_reviewed: true`, and `additional`
roles after the normal primary and backup. This is a review exception, never a
search-expansion permission.

Both artifacts fix `calculation_ready: false`, `executable: false`, and
`no_submission_authorization: true`. They cannot authorize input drafting,
Gaussian execution, SSH, PBS, or submission.
