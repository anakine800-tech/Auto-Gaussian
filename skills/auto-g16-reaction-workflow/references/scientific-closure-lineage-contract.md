# Auto-G16 scientific closure lineage contract

`gaussian-minimum-lineage-handoff/1` is a portable closed-shell minimum
acceptance that binds one exact chain: a non-authorizing conformer-selection
receipt; stable candidate/input/result atom mapping; one owner-validated exact
input approval and its input bytes; the observed job, raw Gaussian log, parsed
result, checkpoint and optimized XYZ; and a human identity, connectivity and
stereochemistry review.

The owner replays the raw log with `auto-g16-gaussian-log-parser/2`. It derives
atom count and linearity from the final orientation and requires exactly
`3N-6` modes for a nonlinear structure or `3N-5` for a linear structure.
Truncation, missing geometry, malformed or non-finite frequency tokens,
result/log drift, empty checkpoints, atom-order drift, or coordinate drift fail
closed.

Every new binding is relative to one explicit package root and rejects
absolute paths, `..`, root escape, and symlinks. Historical artifacts with
absolute paths are not edited in place. They require an owner-controlled
rebuild or an explicitly reviewed repackage producing a new immutable lineage
revision.

The handoff separates human-selected, input-draft-generated,
exact-input-approved, job-observed, submission-authorized-by-this-artifact,
and result-accepted states. A selection receipt never supplies approval,
submission, or accepted-result authority. The lineage remains
`calculation_ready: false` and `no_submission_authorization: true`; it cannot
submit, retry, cancel, fetch, or clean up.

```bash
python3 skills/auto-g16-reaction-workflow/scripts/scientific_closure_lineage.py build \
  --root portable-package --selection selection.json \
  --input-approval input-approval.json --input minimum.gjf \
  --job job.json --result result.json --raw-log minimum.log \
  --checkpoint minimum.chk --optimized-coordinates minimum.xyz \
  --review minimum-lineage-review.json --output minimum-lineage.json
python3 skills/auto-g16-reaction-workflow/scripts/scientific_closure_lineage.py validate \
  portable-package/minimum-lineage.json
```

Historical scientific-maturity `/1` and owner-evidence `/2` records remain
immutable. They do not gain this authority automatically. A consumer must
explicitly migrate to and replay the new lineage artifact; adding its hash to
an old review does not clear an old blocker.
