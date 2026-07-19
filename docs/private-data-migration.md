# Auto-G16 private study data migration

This tool moves no Git artifact and grants no scientific or live-compute
authority. It prepares an operational copy migration from a reviewed local
source directory into the external private root
`~/Documents/Auto-G16-Private-Studies`. Migration plans contain private path
names, file hashes, sizes, conflicts, and absolute-path references, so keep the
plan itself outside this public checkout in an owner-only directory.

The workflow is deliberately plan-review-apply:

1. `plan` walks regular files without following links, hashes source and
   planned bytes, identifies existing destinations, and incrementally validates
   UTF-8 for every file regardless of size. Text files receive a complete,
   bounded-stream scan of absolute POSIX/Windows references with occurrence
   counts; source-root references are rewritten only at matching path/literal
   boundaries. Invalid UTF-8 or NUL-bearing files are explicitly classified as
   binary, marked `not_applicable_binary`, and copied byte-for-byte rather than
   being reported as text with an empty scan. The plan schema is
   `auto-g16-private-study-migration-plan/2`. Planning creates no target
   directory and copies no study file.
2. `review` reloads the closed-schema plan and fully rescans the source and
   target. Any source change, conflict change, hash drift, symlink, permission
   drift, or plan edit fails closed.
3. `apply` requires both the exact reviewed `plan_sha256` and a non-empty
   reviewer identity. Before creating the target, it completes a full
   descriptor-bound preflight of every source size/hash and every destination
   conflict. It then copies with `0600` files into an owner-owned `0700`
   target, refuses every overwrite, and checks source and planned hashes again
   immediately before each write.

Create an owner-only plan directory outside the checkout, then plan and review
an exact source:

```bash
mkdir -m 700 ~/Documents/Auto-G16-Migration-Plans
./scripts/python core scripts/private_study_migration.py plan \
  /absolute/path/to/reviewed-study-source \
  --target ~/Documents/Auto-G16-Private-Studies \
  --plan-out ~/Documents/Auto-G16-Migration-Plans/study.plan.json
./scripts/python core scripts/private_study_migration.py review \
  ~/Documents/Auto-G16-Migration-Plans/study.plan.json
```

Review the private JSON plan directly. Confirm its source and target roots,
file count, byte totals, source/planned tree hashes, per-file hashes,
content kind and scan status, conflicts, every absolute-path reference and
occurrence count, and every proposed rewrite. External absolute references are
reported for review but are not rewritten.

Apply is a later, separately authorized operational action. It is intentionally
not performed during feature development, testing against real data, release,
deployment, or scientific calculation work:

```bash
./scripts/python core scripts/private_study_migration.py apply \
  ~/Documents/Auto-G16-Migration-Plans/study.plan.json \
  --confirm-plan-sha256 <EXACT_REVIEWED_PLAN_SHA256> \
  --reviewed-by <REVIEWER_ID>
```

Safety boundaries:

- source, target, plan output, and every source entry must be symlink-free;
- apply opens or creates every source and destination component relative to an
  already-open directory descriptor. Directory components use
  `O_DIRECTORY|O_NOFOLLOW`; source leaves use `O_RDONLY|O_NOFOLLOW`; destination
  leaves use `O_NOFOLLOW|O_EXCL`. A path swap therefore cannot redirect actual
  I/O through a symlink after a lexical check;
- the target must be outside the public checkout and, if it already exists,
  owned by the current user with exact mode `0700`;
- plans cannot be written inside the checkout or overwrite an existing plan;
- apply cannot proceed with any conflict, stale byte/hash/path state, wrong
  confirmation, or empty reviewer;
- apply is copy-only and never deletes, moves, truncates, cleans up, or
  overwrites the source or an existing destination;
- full preflight avoids ordinary stale-source/conflict failures after copying
  starts. A concurrent post-preflight change or unexpected local I/O failure
  can still leave a partial collection. The error reports how many files and
  bytes completed, labels the target for manual inspection, and performs no
  automatic rollback deletion. An operator must compare the target with the
  reviewed plan and choose a separate, explicitly authorized recovery action;
- the tool performs no SSH, RTwin, PBS, Gaussian, scheduler, deployment, or
  network action.

After a successful copy, source retirement is a separate manual data-governance
decision. This tool never interprets a copy result as permission to delete the
old source.
