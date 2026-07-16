# Auto-G16 — Auto-Gaussian 2.3.0

Auto-Gaussian is the repository and release brand for a guarded family of
Gaussian automation Skills. Every Skill machine name uses `auto-g16-*`, and
every human-facing Skill name begins with `Auto-G16`.

This repository is the version-controlled source of truth. Installed copies
under `~/.codex/skills` are deployment targets and must not be edited
independently.

## 2.3.0 release candidate

Auto-Gaussian 2.3.0 release metadata was prepared on 2026-07-16 from reviewed
`main` commit `1d730218048c52a395b379cbe4653c9e2b8def97`. The immutable
`v2.2.0` release remains published history. An annotated `v2.3.0` tag and
GitHub Release are separate publication actions and have not been authorized
or created by this release-preparation change.

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
- `skills/auto-g16-view-rt-win`: stereochemistry-preserving structure/conformer preparation and RTwin GaussView review.
- `skills/auto-g16-rtwin-pbs`: guarded RTwin/PBS submission, monitoring, retrieval, Opt–Freq–SP analysis, and scheduler-state handling.
- `skills/auto-g16-ts-irc`: offline TS/Freq audit, QST atom-order checks, imaginary-mode review artifacts, explicit mode promotion, and hash-bound forward/reverse IRC plans. It intentionally performs no network, PBS, or G16 execution.
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
  non-executable; these artifacts grant no calculation or live authorization.
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
./scripts/python core -m unittest discover -s tests -v
./scripts/python chem -m pip install --requirement requirements/chemistry.txt
./scripts/python chem path/to/rdkit_script.py --help
```

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
  version or chemistry-package drift before normal execution.
- `scripts/check_skill_sync.py` compares the exact named-Skill deployment
  package, including manifest-mapped authoritative contracts, with installed
  copies.
- `scripts/sync_named_skill.py` prints a no-write named-Skill deployment plan
  by default and applies it only with `--apply --confirmed --plan-sha256
  <REVIEWED_HASH>`; it refuses symlinks, path escape and implicit deletion of
  unexpected installed files.
- `templates/g16_job.pbs.template` preserves the SDL-only work/scratch guard for review and testing.

## License

Auto-Gaussian is released under the [MIT License](LICENSE). Gaussian,
GaussView, ChemDraw and other external tools retain their own licenses.
