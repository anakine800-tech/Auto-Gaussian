# Auto-G16 — Auto-Gaussian 2.2.0

Auto-Gaussian is the repository and release brand for a guarded family of
Gaussian automation Skills. Every Skill machine name uses `auto-g16-*`, and
every human-facing Skill name begins with `Auto-G16`.

This repository is the version-controlled source of truth. Installed copies
under `~/.codex/skills` are deployment targets and must not be edited
independently.

## Current repository status

As of 2026-07-16, the Auto-G16 feature line includes the guarded RTwin/PBS
workflow, audited main-group TS–Freq–IRC workflow, offline asymmetric-catalysis
planning/audit module, W1 reaction-intake/reaction-literature foundations, W2
immutable knowledge records and reviewed store/import/export foundation, and
the W3 offline mechanism-network slice. The current Unreleased work adds the
smallest deterministic calculation-plan DAG and read-only reaction-study index
over exact immutable upstream artifacts. The 2.2.0 release also includes
transition-metal M1/M2 observation and review contracts while preserving the
unconditional metal runtime refusal. Every layer retains its individual
scientific and live-action approval gates.

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

- `skills/auto-g16-chemdraw-structures`: quick or strict ChemDraw-compatible structure and complete reaction-scheme reconstruction, including native round-trip validation.
- `skills/auto-g16-chemdraw-pipeline`: audited ChemDraw-to-Cartesian conversion.
- `skills/auto-g16-view-rt-win`: stereochemistry-preserving structure/conformer preparation and RTwin GaussView review.
- `skills/auto-g16-rtwin-pbs`: guarded RTwin/PBS submission, monitoring, retrieval, Opt–Freq–SP analysis, and scheduler-state handling.
- `skills/auto-g16-ts-irc`: offline TS/Freq audit, QST atom-order checks, imaginary-mode review artifacts, explicit mode promotion, and hash-bound forward/reverse IRC plans. It intentionally performs no network, PBS, or G16 execution.
- `skills/auto-g16-reaction-workflow`: offline, hash-bound reaction intake,
  species registry, balance review, condition-to-model decisions, reviewed W3
  mechanism-network hypotheses, and the Unreleased calculation-plan/study-
  index slice.
  The latter binds the exact W1 chain and finalized mechanism network, retains
  missing mechanism-support and TS-precedent artifacts as blockers, treats any
  supplied sidecar as bound-but-unvalidated until its owner validator exists,
  and keeps every calculation node non-executable. These artifacts grant no
  calculation or live authorization.
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
- mechanism-support matrices, source-to-target atom correspondence, and
  reviewed target TS-seed proposals remain future extensions to the implemented
  reaction-literature layer.

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

The offline planning, parsing and audit layers use Python 3.11 or later and
have no third-party runtime dependency. The ChemDraw and conformer layers
additionally require the packages recorded in
`requirements/chemistry.txt` (RDKit, Pillow and NumPy). Install them in an
isolated environment when those optional paths are needed:

```bash
python3 -m pip install -r requirements/chemistry.txt
```

ChemDraw, GaussView, Gaussian and PBS remain separately licensed external
software and are not distributed here.

Copy `config/*.example` to the corresponding ignored local files and configure
SSH aliases locally. For desktop use, copy `config/runtime.example.json` to
`~/.config/auto-g16/runtime.json`; set `AUTO_G16_RUNTIME_CONFIG` only when a
different local path is needed. Environment variables override the JSON keys:

- `AUTO_G16_RDKIT_PYTHON`
- `AUTO_G16_RTWIN_SSH_CONFIG`
- `AUTO_G16_WINDOWS_TARGET`
- `AUTO_G16_WINDOWS_HOST` (connection probe only)
- `AUTO_G16_WINDOWS_CONTROL_SOCKET` (optional)
- `AUTO_G16_WINDOWS_PROJECT_ROOT`
- `AUTO_G16_WINDOWS_SERVER_CONFIG`
- `AUTO_G16_GAUSSVIEW_EXE`
- `AUTO_G16_PIPELINE_SCRIPTS`

Do not commit the resolved values. Run the offline suite with:

```bash
python3 -m unittest discover -s tests -v
```

## Development sequence

1. Keep `main` stable and integrate changes through reviewed pull requests.
2. Develop each workflow slice on a separate short-lived `codex/` feature
   branch, run offline validation first, and merge only after the applicable
   explicitly approved smoke gate.
3. Continue W2 from the implemented W2B-2 store/import/export foundation with
   authenticated enforcement, durable audit logging and chemical search. Then
   extend the separate literature-evidence
   layer toward mechanism support and TS precedents.
4. Continue W3 from the implemented mechanism network and Unreleased offline
   calculation-plan/study-index slice toward specialist evidence adapters and
   a reaction-level evidence index. Existing Skills remain specialist
   components rather than a monolithic automatic mechanism generator.
5. Connect candidate/protocol/input and result/energy adapters, then validate a
   small closed-shell main-group reaction from ChemDraw through minima, TS,
   path, and common-reference energy evidence.
6. Continue the refusal-preserving transition-metal M1–M3 design; the existing
   `auto-g16-ts-irc` transition-metal refusal must not be bypassed.
7. BF3-TS2-B1 has an accepted hash-bound C13–C21 mode decision and separately
   submitted bidirectional IRC work. BF3-TS2-B2 now has a B1-matched standard
   offline input candidate with exact coordinate, route and hash audits. That
   exact B2 input subsequently received one-time live approval and is queued;
   no retry, replacement, IRC, cancellation or cleanup is authorized.

See `docs/ts-freq-irc-design.md` for the implemented TS–Freq–IRC design history.
Repository-wide operational rules are in `AGENTS.md`.

## Repository helpers

- `config/*.example` contains placeholders only; real SSH/server configuration stays ignored.
- `scripts/check_skill_sync.py` compares repository Skill hashes with installed copies.
- `templates/g16_job.pbs.template` preserves the SDL-only work/scratch guard for review and testing.

## License

Auto-Gaussian is released under the [MIT License](LICENSE). Gaussian,
GaussView, ChemDraw and other external tools retain their own licenses.
