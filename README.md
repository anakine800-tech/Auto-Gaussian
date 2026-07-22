# Auto-G16 — Auto-Gaussian 2.5.3

Auto-Gaussian is the repository and release brand for a guarded family of
Gaussian automation Skills. Every Skill machine name uses `auto-g16-*`, and
every human-facing Skill name begins with `Auto-G16`.

This repository is the version-controlled source of truth. Installed copies
under `~/.codex/skills` are deployment targets and must not be edited
independently.

The 2.4.0 open-shell input-receipt bridge preserves generic receipt `/1`
unchanged and adds offline-only `gaussian-input-approval-receipt/2` for a
reviewed main-group open-shell minimum. `/2` replays the accepted electronic
state, exact minimum Opt/Freq handoff and passed input audit in addition to the
selected protocol, mapping, resources and exact input SHA-256. It recognizes
`optimization`/`frequency` with composite `opt_freq` owner stages, counts only
top-level Gaussian route keywords (so `Stable=Opt` is not a duplicate Opt),
and retains all specialist syntax blockers. It grants no live authority. A
separate closed `auto-g16-live-submission-approval/4` can now bind a fully
owner-replayed `/2` receipt for one exact main-group open-shell minimum only;
`/3` remains restricted to receipt `/1` and is unchanged. Direct and wrapper
dry runs emit only the required schema and exact scope proposal, never an
approved live record. This bridge has been implemented and tested offline only.

Gaussian 16 A.03 open-shell minima that need both Opt/Freq and wavefunction
stability now use a separate versioned two-stage family. Stage 1 contains
Opt/Freq but no `Stable`; only its accepted final checkpoint may feed a
coordinate-free `Stable=Opt Geom=AllCheck Guess=Read` stage 2. Each stage has
its own non-authorizing receipt `/3` and prospective live approval `/5`.
Receipt `/2` and live `/4` retain their single-input meaning. See
`docs/main-group-open-shell-minimum-two-stage-family.md`.

The 2.4.0 release also adds a prospective scientific-maturity
overlay and minima-first TS hard gate. It preserves all historical `/1`
records, requires two accepted Gaussian Opt/Freq zero-imaginary minima before
formal TS input or submission, limits no-direct-precedent work to one reviewed
`simple` pilot, and keeps scientific maturity, input review, and live approval
as three independent gates. Minimum acceptance replays the exact raw log
through the existing Gaussian owner parser; protected submissions additionally
require an offline exact-scope binding for the DAG node, input hash, project,
resource tier and task/core-hour/concurrency budget. That binding explicitly is
not live approval. This checkout has not deployed or exercised that
gate against SSH, PBS, Gaussian, or any live job.

An additional compatibility-preserving owner-evidence `/2` overlay now binds
one exact validated maturity gate `/1` and replays the public calculation-plan,
mechanism-support, TS-precedent, conformer-handoff, applicable main-group
open-shell, and manual-evidence validators. It blocks artifact-presence,
hand-filled conformer provenance, and missing open-shell acceptance bypasses;
manual receipts remain supporting-only. Its exact-scope science actions cover
TS input/submission, IRC input, and formal barrier reporting while retaining
separate input and live gates. No historical `/1` semantics or consumers are
changed. Current owner artifacts do not bind a selected conformer through exact
input approval to the accepted minimum result/log, so `/2` records that explicit
lineage blocker and grants no passed action. IRC and formal reporting remain
fixed fail-closed until exact owner TS-mode and complete thermochemistry/energy
artifacts are added. Complete owner-chain relocation is also unsupported because
historical conformer paths may be absolute and open-shell paths may be
working-directory-relative.

The 2.5.0 release adds explicit human scientific
decisions, evidence-only method briefs, bounded TS-seed portfolios, practical
closure-priority planning, and persistent ten-task execution-batch governance.
`gaussian-v25-integration-review/1` replays those owner contracts and binds the
selected closure nodes to the exact batch review and ledger. The overlay and
every component remain non-executable and non-authorizing; exact input review,
stage dependency evidence, and a fresh live approval per physical attempt are
still independent requirements. See `docs/v2.5-integration-approval.md`.

`gaussian_auto prepare` is intentionally limited to non-authorizing input and
scientific preflight and never proposes a usable live approval. Generate an
exact live `/9`–`/11` scope only with resource-bound `gaussian_auto auto
--dry-run`; its complete execution/resource arguments are replayed again before
any protected submit.

New TS/IRC qualification requires `gaussian-ts-irc-path-acceptance/2` built
from two owner-replayed `gaussian-endpoint-structure-review/2` artifacts. Both
directions must bind the same accepted TS checkpoint/audit lineage and exact
IRC plan, AllCheck input, attempt, terminal receipt and fetch snapshot.
Historical endpoint review or path acceptance `/1` remains readable for
display/replay only and cannot open maturity, thermochemistry, asymmetric
comparison or any live gate.

## 2.5.3 current release

Auto-Gaussian 2.5.3 is the latest published release. It was published on
2026-07-22 from `main` commit
`bc67fded270ee5fc52efecfafdfc817073430b7a`; annotated tag object
`20cea7e040ef6649f9f695381c802abc8aa7aba0` resolves to that exact commit.

The 2.5.3 increment contains only three first-parent merges after 2.5.2:
PR #45 adds the development handbook, isolated-worktree preflight, exact
Python/CI declarations and their offline audits; PR #46 hardens RTwin terminal
snapshot and staged fetch handling for finite timeouts, sanitized failure
evidence, PBS `qstat` return code 153, and no automatic retry; PR #47 freezes
the 2.5.3 release metadata and checklist. Historical schemas and release
records retain their original meaning. Local static audits do not prove
current GitHub branch protection or a successful CI run.

Publication makes no deployment, SSH, RTwin, PBS, Gaussian, live-smoke or
scientific-success claim. It grants no submission, retry, qdel, cleanup,
result-acceptance or scientific authority.

## 2.5.2 historical release

Auto-Gaussian 2.5.2 was published on 2026-07-20. Its annotated tag permanently
identifies the release commit above. The release contains compatibility-
preserving runtime evidence, immutable fetch, execution/cancellation,
resource, monitoring, TS/Freq/IRC and minimum-result lineage, configuration,
private-migration and release-validation hardening. Publication did not grant
deployment or live/scientific authority.

## 2.5.0 historical release

Auto-Gaussian 2.5.0 is the preceding published release. The annotated
`v2.5.0` tag permanently identifies exact release commit
`18d7f62af3b24cdd0fbe5687f4c0e779f243d572`. This engineering-maintenance
slice started from the then-matching `main` baseline; later `main` development
does not move the release tag. Immutable earlier release history remains
preserved.

The 2.5.0 scope is the offline human-AI decision, method-evidence, bounded
TS-seed, closure-priority, execution-batch, and cross-Skill integration layer.
Every planning and review artifact remains `calculation_ready: false`, every
calculation node remains `executable: false`, and none grants submission
authority. This release does not claim a successful real reaction study,
accepted TS/IRC closure, or real PBS/Gaussian validation. Future execution
still requires exact structure, method, input, resource, server-directory, and
live approvals.

## 2.4.0 historical release

Auto-Gaussian 2.4.0 release metadata was prepared on 2026-07-18 from confirmed
`origin/main` commit `69222eb40fc4485392c753b240989719fcec56a4`. The immutable
2.3.0 release history is preserved. This is historical source evidence only;
it grants no current Skill deployment or live-smoke authority.

The 2.4.0 source adds offline transition-metal P0–P5 readiness and candidate
closure, dual-route conformer discovery and cross-validation, reviewed
main-group open-shell state/minimum/result contracts, multiplicity families,
same-spin open-shell TS/Freq/IRC contracts, open-shell reaction networks, and
scientific-maturity owner gates. It also adds compatibility-preserving input
receipts `/2` and `/3` and distinct prospective live approvals `/4` and `/5`
for single-stage and two-stage open-shell minimum paths. All remain fail-closed
and preserve separate scientific, input-review, and live-action authority.

## 2.3.0 historical release

Auto-Gaussian 2.3.0 release metadata was prepared on 2026-07-16 from reviewed
`main` commit `1d730218048c52a395b379cbe4653c9e2b8def97`. The immutable
`v2.2.0` release remains historical evidence. This section does not describe
the current release state or authorize deployment or live work.

As of 2026-07-16, the 2.3.0 candidate source includes the guarded RTwin/PBS
workflow, audited main-group TS–Freq–IRC workflow, offline asymmetric-catalysis
planning/audit module, W1 reaction-intake/reaction-literature foundations, W2
immutable knowledge records and reviewed store/import/export foundation, and
the W3 offline mechanism-network slice. The candidate adds the
offline mechanism-support two-gate, separate mechanism-support matrix view,
TS-precedent/de novo-planning stages, and the smallest deterministic
calculation-plan DAG and read-only reaction-study index over exact immutable
upstream artifacts. It also includes
transition-metal M1/M2 observation and review contracts while preserving the
unconditional metal runtime refusal. Every layer retains its individual
scientific and live-action approval gates.

The 2.3.0 candidate also contains the first offline calculation-
artifact adapter slice: immutable candidate-target imports, exact reviewed
closed-shell main-group TS/Freq input handoffs, blocked/electronic-only energy
lineage, and observation-only attempt links that bind the exact handoff, job
observation, terminal intake, parsed result, mode review, and scientific
decision. Standalone validation reconstructs derived facts rather than trusting
a newly rehashed document. It does not implement or mutate a calculation DAG
and grants no staging, submission, retry, cleanup, deployment, or live-smoke
authority.

`main` is the stable release branch. Feature work uses short-lived `codex/`
branches and reaches `main` only through reviewed pull requests with the
required offline checks passing.

See `docs/repository-status.md` for the evidence, limitations, and next gates.
See `docs/end-to-end-reaction-computation-workflow.md` for the project target:
an auditable workflow from a ChemDraw reaction and experimental conditions to
reviewed reusable structure/method/literature knowledge, reproducible literature
evidence and TS precedents, reviewed mechanism networks, calculation evidence,
thermochemistry, kinetics/selectivity, uncertainty, and bounded conclusions.

All repository-owned Skill machine names and folders use the `auto-g16-`
prefix; their human-facing display names begin with `Auto-G16`. The same rule
applies to every future project Skill. Versioned scientific artifact schemas
retain their existing names for compatibility and provenance.

## Baseline Skills

- `skills/auto-g16-gaussian-learning-library`: self-contained beginner-facing
  Gaussian and computational-chemistry teaching library with 72 searchable
  knowledge cards. It explains concepts and evidence boundaries but does not
  select production protocols or authorize calculations.
- `skills/auto-g16-chemdraw-structures`: quick or strict ChemDraw-compatible structure and complete reaction-scheme reconstruction, including native round-trip validation.
- `skills/auto-g16-chemdraw-pipeline`: audited ChemDraw-to-Cartesian conversion.
- `skills/auto-g16-main-group-open-shell`: offline, hash-bound electronic-state
  review and result acceptance for explicitly reviewed single-reference
  main-group doublet and high-spin triplet minima, plus the immutable
  `main_group_open_shell_minimum_opt_freq_v1` input-handoff, input-audit, and
  result-continuity closure. It blocks open-shell singlets, multireference
  states, metals, TS/IRC, server-directory creation, and all live actions.
- `skills/auto-g16-view-rt-win`: stereochemistry-preserving structure/conformer preparation and RTwin GaussView review.
- `skills/auto-g16-conformer-search`: offline, hash-bound A/A1/A2 and B/B1/B2 conformer/complex discovery planning, supplied-candidate legality auditing, composite structural cross-validation, negative-evidence preservation, clustering, medoids, and candidate-only handoff. It never executes xTB, CREST, Gaussian, PBS, or SSH.
- `skills/auto-g16-rtwin-pbs`: guarded RTwin/PBS submission, monitoring,
  retrieval, Opt–Freq–SP analysis, scheduler-state handling, and locked
  ten-task execution-batch governance with separate task/attempt/core-hour
  accounting.
- `skills/auto-g16-ts-irc`: offline TS/Freq audit, QST atom-order checks,
  minima-gated prospective `/2` family creation, imaginary-mode review
  artifacts, explicit mode promotion, and hash-bound forward/reverse IRC
  plans. It intentionally performs no network, PBS, or G16 execution.
- `skills/auto-g16-reaction-workflow`: offline, hash-bound reaction intake,
  species registry, balance review, condition-to-model decisions, reviewed
  mechanism-network hypotheses, edge/channel mechanism-support classification,
  independent exploration and claim-support gates, a separate immutable
  row-by-evidence comparison matrix, TS-precedent/de novo seed planning, the
  2.3.0 calculation-plan/study-index slice, and a
  narrow exact-reviewed calculation-artifact adapter. The
  planning layer binds the exact W1/network chain and calls owner validators
  before clearing only matching precedent-coverage blockers. Because the DAG
  review currently carries edge IDs but no reviewed stereochemical-channel
  mapping, even owner-validated mechanism support remains explicitly blocked.
  The adapter exports only external targets and immutable specialist
  handoffs; it does not own DAG node identities. A separate DAG-owned reviewed
  mapping can attach one exact external target to one `ts_candidate` through
  an append-only, non-promoting node update. Every calculation node remains
  non-executable. The scientific-maturity overlay adds explicit literature,
  edge/channel, accepted-minimum, pilot/budget, TS/IRC, common-reference and
  stop-condition gates and projects their blockers onto the exact DAG without
  mutating it; these artifacts grant no calculation or live authorization.
- `skills/auto-g16-reaction-literature`: offline-first query planning,
  Crossref/OpenAlex metadata retrieval, DOI deduplication, transparent
  screening, evidence templates and fail-closed source-review validation. It
  does not infer a mechanism, choose a computational protocol, or authorize a
  calculation.
- `skills/auto-g16-knowledge-base`: offline validation and deterministic
  finalization for immutable structure identity/state/geometry, computational
  method, literature/book source, typed-link and per-study snapshot records.
  W2B-2 adds immutable record/object-store verification, deterministic SQLite
  rebuild, exact permission-filtered queries, reviewed import with lawful
  object ingestion, redacted JSON export and snapshot verification; it has no
  method selection, input generation or live action.

## W2 knowledge modules

- `auto-g16-knowledge-base` W2A is implemented with five closed contracts,
  canonical SHA-256 validation, review/access/provenance rules, frozen
  identity/state/geometry, method, article/book, link and snapshot fixtures,
  and fail-closed duplicate/conflict auditing without automatic merge.
- W2B-1 implements the immutable record/object layout, content-addressed object
  checks, deterministic SQLite migration/rebuild, stale-index refusal, exact
  offline principal-filtered queries and snapshot dependency verification.
- W2B-2 implements hash-bound plan-review-apply import, exact lawful-object
  ingestion, full/metadata-redacted JSON export, `no_export` exclusion and
  dependency-aware downgrade. Binary objects are never exported.
- W2 still requires authentication, signatures, durable audit logging,
  chemical search and multi-user enforcement.
- strict edge/channel mechanism-support and source-to-target TS-precedent
  review are implemented in `auto-g16-reaction-workflow`. A reviewed novel
  hypothesis may be exploration-eligible without a direct precedent while its
  mechanism claim remains unsupported and unvalidated. Seed-geometry
  construction remains a future extension.
- `gaussian-reaction-mechanism-support-matrix/1` is a downstream view over the
  unchanged `gaussian-reaction-mechanism-support/1` owner gate. It provides
  complete cross-evidence cells and explicit row dispositions but cannot
  weaken an owner blocker, validate a mechanism, or create an executable DAG
  node. Experimental PR #19 artifacts are not aliases for the merged gate and
  require an explicit new matrix build if migrated.

## Offline planning/audit module

- `skills/auto-g16-asymmetric-catalysis`: literature-grounded planning and
  audit workflow for metal–chiral-ligand and chiral-boron catalytic TS
  ensembles, stereochemical-channel coverage, candidate ledgers, TS-result
  ingestion, and selectivity aggregation. It contains no Gaussian execution
  builder or live handoff. Its current development priority is the
  refusal-preserving transition-metal TS state/search design and candidate-
  bound result-audit templates; chiral-boron
  expansion follows that milestone. Its design and
  versioned data contracts are in `docs/asymmetric-catalysis-design.md` and
  `docs/asymmetric-catalysis-offline-contract.md`.
- `studies/wang_2024_bf3_ts`: hash-bound, non-runnable literature coordinates
  and expected-result ledger for BF3-TS1 followed by BF3-TS2-B1/B2.
- `studies/wang_2024_cat2_alpha_alkylation`: real-reaction offline forward
  study for the reported CAT2 asymmetric reaction. It records the experimental
  identity and selectivity while refusing to invent the unresolved active
  state, atom maps, candidate geometries, or comparison protocol.

## Safety boundary

All Skill-managed server data and scratch must remain below `/home/user100/SDL`.
That root is fixed and has no runtime override. The repository contains no
password, private key, local SSH configuration, Gaussian checkpoint, or
calculation output.

This repository is public and accepts only publication-backed studies,
synthetic fixtures, and release-cleared material. Keep all unpublished research
in the external owner-only directory defined by
`docs/data-confidentiality.md`; never add that directory as a worktree,
submodule, symlink, or remote.

## Installation and local configuration

The repository has two explicit local profiles. `core` is the default and is
fixed to Miniforge Python 3.13.13; it runs the standard-library-only planning,
parsing, audit, deployment and test flows. `chem` is fixed to Python 3.11.15
and is reserved for RDKit, NumPy and Pillow workflows. `.python-version`,
`pyproject.toml`, `environment.yml`, `environment-chem.yml` and
`config/python-environments.json` record this contract. The exact optional
package versions live in `requirements/chemistry.lock.txt`.

Use the repository launcher for both execution and installation. It resolves
an absolute interpreter from an environment variable, the ignored runtime
configuration, or the reviewed Miniforge fallback; validates the exact Python
version; and then replaces itself with that interpreter. It never chooses
`python3` from `PATH`:

```bash
./scripts/python core scripts/run_tests.py
./scripts/python chem -m pip install --requirement requirements/chemistry.txt
./scripts/python chem path/to/rdkit_script.py --help
```

The timed runner preserves normal `unittest` pass/fail behavior and prints a
readable slow-test table. Local full runs include the 1101-node/128-level DAG
pressure test. CI runs ordinary compatibility coverage on Python 3.11, 3.12,
and 3.13, then runs the complete pressure and source-archive replay once on
Python 3.13. The chemistry job separately executes a real RDKit structure,
3D-conformer, and 2D-depiction smoke.

The Python-file shebangs remain portable compatibility metadata. Repository
and deployed Skill commands must invoke scripts with the selected interpreter
instead of executing those files directly.

ChemDraw, GaussView, Gaussian and PBS remain separately licensed external
software and are not distributed here.

Copy `config/*.example` to the corresponding ignored local files and configure
SSH aliases locally. For desktop use, copy `config/runtime.example.json` to
`~/.config/auto-g16/runtime.json`; set `AUTO_G16_RUNTIME_CONFIG` only when a
different local path is needed. Environment variables override the JSON keys:

- `AUTO_G16_CORE_PYTHON`
- `AUTO_G16_RDKIT_PYTHON`
- `AUTO_G16_BOOTSTRAP_PYTHON` (launcher bootstrap only; normally unnecessary)
- `AUTO_G16_RTWIN_SSH_CONFIG`
- `AUTO_G16_WINDOWS_TARGET`
- `AUTO_G16_WINDOWS_HOST` (connection probe only)
- `AUTO_G16_WINDOWS_CONTROL_SOCKET` (optional)
- `AUTO_G16_WINDOWS_PROJECT_ROOT`
- `AUTO_G16_WINDOWS_SERVER_CONFIG`
- `AUTO_G16_GAUSSVIEW_EXE`
- `AUTO_G16_PIPELINE_SCRIPTS`

Do not commit the resolved values. Inspect both environments, including the
selected executable, exact Python version, pip module path and the installed
RDKit, NumPy and Pillow versions, with:

```bash
./scripts/python check
```

Validate the ignored runtime file offline before any operational command. The
closed-schema validator rejects duplicate keys, unknown fields, path-type
mismatches, parent traversal, relative interpreter/config paths, and config
leaf or ancestor symlinks. The loader opens each component with
`O_DIRECTORY|O_NOFOLLOW` and the leaf with `O_NOFOLLOW`; paths intentionally
routed through symlinked configuration directories must be changed to their
canonical absolute path. Validation performs no SSH, Windows, Gaussian, or PBS
access:

```bash
./scripts/python core scripts/runtime_config.py ~/.config/auto-g16/runtime.json
```

Add `--skill-sync` to compare every repository Skill deployment package with
its installed `~/.codex/skills/<name>` copy using the same reviewed core
interpreter:

```bash
./scripts/python check --skill-sync
```

The sync check is read-only. Deployment remains a separate, review-gated
`scripts/sync_named_skill.py` dry-run/plan-hash/apply workflow. Neither Python
environment setup nor Skill synchronization changes the RTwin, Windows,
Gaussian or PBS approval boundaries.

## Development sequence

Start with the [`Auto-G16 development handbook`](docs/development-handbook.md).
It defines the mandatory task/worktree/branch mapping, read-only preflight,
offline validation ladder, review and CI contract, integration cleanup, and
separate deployment/live approvals. `AGENTS.md` remains the binding safety
policy; versioned release checklists retain release-specific details.

1. Keep `main` stable and integrate changes through reviewed pull requests.
2. Develop each workflow slice on a separate short-lived `codex/` feature
   branch, run offline validation first, and merge only after the applicable
   explicitly approved smoke gate.
3. Continue W2 from the implemented W2B-2 store/import/export foundation with
   authenticated enforcement, durable audit logging, chemical search and
   later independent evidence revisions for mechanism claims.
4. Continue the implemented W3 mechanism-network/support/TS-planning and
   offline calculation-plan/study-index foundation with the implemented first
   specialist adapter slice and a future reaction-level evidence index.
   Existing Skills remain
   specialist components rather than a monolithic automatic mechanism
   generator.
5. Extend the implemented first candidate/protocol/input and electronic-only
   result/energy adapter slice only through reviewed contracts; then validate a
   small closed-shell main-group reaction from ChemDraw through minima, TS,
   path, and common-reference energy evidence. DAG node binding remains owned
   by the implemented DAG's narrow reviewed mapping and append-only update
   bridge; the calculation-artifact adapter does not acquire DAG ownership.
6. Continue the refusal-preserving transition-metal M1–M3 design; the existing
   `auto-g16-ts-irc` transition-metal refusal must not be bypassed.
7. BF3-TS2-B1 has an accepted hash-bound C13–C21 mode decision. Its first IRC
   pair remains incomplete, and the later matched recalculation pair was
   stopped by the user for time constraints with no terminal results retained.
   BF3-TS2-B2 exhausted its 100-cycle optimization limit before frequency
   analysis and is not accepted. A separate BF3-TS1/DIPEA candidate completed
   Opt/Freq with 150 modes and one raw imaginary frequency, but its formal
   terminal intake is blocked by a template-hash mismatch and manual
   C13–H14–N22 mode review is still pending. None of these histories authorizes
   a retry, replacement, IRC, cancellation or cleanup.

See `docs/ts-freq-irc-design.md` for the implemented TS–Freq–IRC design history.
Repository-wide operational rules are in `AGENTS.md`.

## Repository helpers

- `config/*.example` contains placeholders only; real SSH/server configuration stays ignored.
- `scripts/python` is the only documented repository Python entry point;
  `scripts/python_environment.py` resolves absolute interpreters and rejects
  version, chemistry-package, or strict runtime-config drift before normal
  execution.
- `scripts/run_tests.py` preserves `unittest` semantics and reports the slowest
  offline tests; `scripts/static_quality.py` applies a small dependency-free
  AST rule set only to the explicitly listed high-risk modules in
  `config/static-quality.json`, avoiding repository-wide formatting churn.
- `scripts/private_study_migration.py` implements an operational
  plan-review-apply copy migration into the owner-only external private-study
  root. Plans are private artifacts and are refused inside this checkout;
  apply requires the exact reviewed plan hash, completes full source/conflict
  preflight, incrementally validates and scans UTF-8 files of any size for
  source-path rewrites, explicitly classifies binary files, binds actual I/O
  to no-follow directory descriptors, and never overwrites or deletes the
  source. See `docs/private-data-migration.md`.
- `scripts/check_skill_sync.py` compares the exact named-Skill deployment
  package, including manifest-mapped authoritative contracts, with installed
  copies.
- `scripts/sync_named_skill.py` prints a no-write named-Skill deployment plan
  by default and applies it only with `--apply --confirmed --plan-sha256
  <REVIEWED_HASH>`; it refuses symlinks, path escape and implicit deletion of
  unexpected installed files.
- Every repository Skill directory is deployable by that synchronizer. An
  optional `deployment-package.json` is required only when the installed Skill
  must also receive authoritative files outside its own directory; its absence
  does not authorize ad-hoc copying or imply that the Skill is undeployable.
- Cross-Skill changes must be dry-run and smoke-tested as one reviewed set.
  Deploy owner Skills before consumers, retain every per-Skill plan hash, and
  stop on the first mismatch instead of widening the deployment scope.
- `templates/g16_job.pbs.template` preserves the SDL-only work/scratch guard for review and testing.

## License

Auto-Gaussian is released under the [MIT License](LICENSE). Gaussian,
GaussView, ChemDraw and other external tools retain their own licenses.
