# T146 — Paired v4.6.2 patch release

Status: release preparation; T145 is reviewed and merged in both repositories.
Owner has authorized execution of merge, paired publication and development-machine deployment in sequence; the release PRs still require supervisory review before merging. Real calculation and research-machine deployment remain separately approved.

## Baselines and scope

- Backend T145 #345 reviewed HEAD: 361cb56e11e30847044ddf4b2fcc1eb38736a2e6; merge: d1f7d5420fa897bc527593608c9a2bd931a47cb7.
- Frontend T145 #44 reviewed HEAD: 7c3852e939de9c9afba45cd3c78a7e5c175c84e9; merge: 0ecdfc2349d48962349d869cb3568b4a98ccbdda.
- These are the only first-parent changes after each repository's v4.6.1 tag. The frontend supervisor conclusion is retained privately because its GitHub publication was unavailable.
- T146 and the v4.6.2 tag were checked before creation. Each repository uses one isolated codex/t146-release-v4.6.2 branch and one PR, with Task: T146 on the first description line (frontend may add its qualifier).
- Only versions, version assertion and release/validation documentation. No feature logic, dependencies, templates, scheduler commands, existing Attempt rewrites, production configuration or research data changes in these PRs.

## Allowed paths

Backend:
- ag/pyproject.toml, ag/src/ag/__init__.py, ag/tests/test_smoke.py: version and assertion only.
- CHANGELOG.md, README.md, docs/handoff-v4.md, docs/OPERATIONS.md.
- docs/redesign-tasks/T146-release-v4.6.2.md, docs/redesign-tasks/open-tasks.txt.

Frontend:
- pyproject.toml, web/package.json; web/pnpm-lock.yaml only if package-version synchronization requires it, without dependency changes.
- CHANGELOG.md, README.md.
- docs/redesign-tasks/T146-release-v4.6.2.md, docs/redesign-tasks/open-tasks.txt.
- Preserve the runtime __version__ legacy exception, documented separately from package/web versions.

Keep historical CHANGELOG sections unchanged. Remove the verified-completed T144 registry item; retain its historical task. Additional feature work requires a separate scope.

## Release notes and compatibility

- Explicit per-entry PBS targeting for new Gaussian Attempts, with immutable node/fraction/queue/resources and script/bundle hashes. Opt-out entries retain scheduling and script bytes.
- Original priority_group and overall order, preserving group member order; no default node selection. Half default, optional quarter, existing tier correspondence, restricted/forbidden nodes disabled.
- Q/H/W/T placement remains pending even with exec_host. R/E/S/C requires exact complete allocation evidence; missing/abnormal evidence or mismatch stops automatic operations without cancellation or retry.
- Strict targeting parse failures retain ordinary read-only monitoring with a diagnostic but cannot authorize a target.
- Preserve Gaussian-only, resource limits, four/five-card and node details, Slurm views, approval/Claim/UNKNOWN and immutable submission semantics.
- No automatic configuration activation or data migration. Special CPU mapping and non-atomic cross-client races remain site acceptance limits. Duplicate node records affecting read-only aggregate capacity remain a separate non-blocking data-quality follow-up.

## Validation

Full backend ag/tests and skills-next, including legacy PBS/Slurm byte regressions; frontend Python, typecheck/build and full synthetic Playwright; actual paired candidate/preparation integration; effective local private-term full/staged scans, diff/scope and noreply checks. Use synthetic temporary data, no SSH or live calculation.
Record results for the release commits, not only prior feature commits. Screenshots use test-specific output directories; incidental tracked fixture rewrites are retained privately then restored.

## Publication and deployment

After supervisory review of both release PRs, merge under the existing owner authorization with exact HEAD checks. Record actual release merge commits; matching v4.6.2 tags/releases must point to those commits, not a later main. Verify both before deployment; partial publication is not a deployable pair.
Development-machine deployment follows OPERATIONS and the private owner instructions, keeping one monitor and one operation frontend. Verify all configured entries, bounded first snapshots/heartbeat, node selection and the authorized observation period.
Real synthetic compute needs separate approval and actual placement/output/completion evidence. The current nodefile guard checks but does not archive the original nodefile; resolve authorized evidence collection before claiming that live criterion. Research-machine work requires complete development-machine acceptance and its own maintenance approval.
Rollback restores the prior compatible configuration and execution environment; never rewrite new node-bound Attempts into an old format. If old software cannot safely handle new records, stop affected operations and report partial recovery.
Actual entry/node policy, resource values, routes, queues, paths, credentials and raw records remain only in private local handoff files.
