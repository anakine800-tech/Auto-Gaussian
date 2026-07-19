# Auto-G16 scientific closure lineage contract

`gaussian-minimum-lineage-handoff/2` is a portable closed-shell minimum
acceptance that binds one exact project/job/attempt chain. Its mutually
exclusive source is either a non-authorizing conformer-selection receipt or an
owner-replayed IRC endpoint-structure review. The endpoint branch additionally
binds the reviewed endpoint state, stable atom IDs, charge, multiplicity and
audited checkpoint. Both branches bind one owner-validated exact input
approval and its input bytes; the observed job, terminal-inspection receipt,
fetch snapshot, raw Gaussian log, parsed result, checkpoint and optimized XYZ;
and a human identity, connectivity and stereochemistry review. Evidence from
different projects, jobs, attempts, endpoints or fetch snapshots cannot be
combined.

The owner replays the raw log with `auto-g16-gaussian-log-parser/2`. A complete
single-route `Opt Freq` job may explicitly declare one expected stage; staged
families must declare their exact larger count. The owner derives
atom count and linearity from the final orientation and requires exactly
`3N-6` modes for a nonlinear structure or `3N-5` for a linear structure.
Truncation, missing geometry, malformed or non-finite frequency tokens,
result/log drift, empty checkpoints, atom-order drift, or coordinate drift fail
closed.

Every new binding is relative to one explicit package root and rejects
absolute paths, `..`, root escape, the leaf symlink, and every existing
symlinked ancestor below the package root. The owner checks each lexical path
component with `lstat` before resolution. Historical artifacts with
absolute paths are not edited in place. They require an owner-controlled
rebuild or an explicitly reviewed repackage producing a new immutable lineage
revision.

Publication is validation-before-publish and atomic no-clobber. The owner
writes one private same-directory file with exclusive creation, validates that
inode, and then hard-links it to the final name. An existing or concurrent
target wins unchanged. Validation failure removes only the private temporary
file and never unlinks a target path.

The handoff separates human-selected, input-draft-generated,
exact-input-approved, job-observed, submission-authorized-by-this-artifact,
and result-accepted states. A selection receipt never supplies approval,
submission, or accepted-result authority. The lineage remains
`calculation_ready: false` and `no_submission_authorization: true`; it cannot
submit, retry, cancel, fetch, or clean up.

```bash
python3 skills/auto-g16-reaction-workflow/scripts/scientific_closure_lineage.py build \
  --root portable-package --source-kind conformer_selection \
  --selection selection.json \
  --input-approval input-approval.json --input minimum.gjf \
  --job job.json --result result.json --raw-log minimum.log \
  --checkpoint minimum.chk --optimized-coordinates minimum.xyz \
  --terminal-inspection-receipt terminal-receipt.json \
  --fetch-snapshot fetch-snapshot.json \
  --review minimum-lineage-review.json --output minimum-lineage.json
python3 skills/auto-g16-reaction-workflow/scripts/scientific_closure_lineage.py validate \
  portable-package/minimum-lineage.json
```

Historical scientific-maturity `/1` and owner-evidence `/2` records remain
immutable. They do not gain this authority automatically. A consumer must
explicitly migrate to and replay the new lineage artifact; adding its hash to
an old review does not clear an old blocker.
