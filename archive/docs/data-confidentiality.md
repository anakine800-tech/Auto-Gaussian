# Auto-G16 data confidentiality boundary

This repository is public. It may contain code, synthetic fixtures, and
publication-backed benchmark studies only. Unpublished structures, reaction
schemes, experimental observations, Gaussian inputs or outputs, approval
records, notebooks, spectra, and project names must remain outside this
checkout and outside its Git history.

The machine-local private research root is:

```text
~/Documents/Auto-G16-Private-Studies
```

That directory is intentionally outside the public repository and must remain
owner-only (`0700`). Do not add it as a Git submodule, worktree, symlink, or
repository remote. If remote collaboration becomes necessary, create a
separate private repository after reviewing its membership, retention, backup,
and access policy.

Before adding a public study under `studies/`:

1. Record a publication DOI in the study `README.md`.
2. Confirm that every structure and result is either published, synthetic, or
   explicitly cleared for public release.
3. Keep raw Gaussian logs, checkpoints, server paths, job IDs, credentials,
   local paths, and native experimental source files out of Git.
4. Run `./scripts/python core -m unittest tests.test_release_hygiene -v`.

The ignore rules and release-hygiene tests are guardrails, not declassification
tools. They cannot make confidential content safe after it has entered Git
history. If an unpublished artifact is ever committed, stop pushing, make the
remote private, preserve an audit copy, and plan an explicit history rewrite
and credential review before restoring any public remote.
