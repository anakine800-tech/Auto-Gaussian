# Auto-G16 RTwin Gaussian Automation Skills

This repository is the version-controlled source for the Gaussian automation Skills used on this Mac. Installed copies under `~/.codex/skills` are deployment targets, not the development source of truth.

## Current repository status

As of 2026-07-14, the guarded RTwin/PBS workflow, audited main-group
TS–Freq–IRC workflow, offline asymmetric-catalysis planning/audit module, and
the W1 reaction-intake foundation are integrated on `codex/Auto-Gaussian`.
These layers retain their individual scientific and live-action approval gates.

`codex/Auto-Gaussian` is the sole target integration branch for the final
whole-reaction workflow. W0/W1 was developed on
`codex/w0-w1-reaction-intake`; its offline gates and separately approved real
strict native-ChemDraw smoke test passed on 2026-07-14 before integration.

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
  species registry, balance review and condition-to-model decisions. Its W1
  artifacts explicitly grant no calculation or live authorization. Its future
  W2 references define a reusable structure/method/literature knowledge layer,
  reproducible literature search, evidence extraction, applicability review and
  TS-precedent artifacts; those tools are not yet implemented.

## Planned W2 knowledge modules

- `auto-g16-knowledge-base`: future reviewed structure/catalyst,
  computational-method, and literature/book registries with permissions,
  provenance, typed links and immutable per-study snapshots.
- `auto-g16-reaction-literature`: future reproducible primary/SI search,
  extraction, applicability audit and TS-precedent translation layer.

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

All Skill-managed server data and scratch must remain below `/home/user100/SDL`. The repository contains no password, private key, local SSH configuration, Gaussian checkpoint, or calculation output.

## Development sequence

1. Keep `main` stable and use `codex/Auto-Gaussian` as the sole final workflow
   integration branch.
2. Develop each workflow slice on a separate `codex/` feature branch, run
   offline validation first, and merge only after the applicable explicitly
   approved smoke gate.
3. Reconcile repository/deployed Skill drift, then extend the implemented W1
   reaction-intake/species/condition foundation with the W2 reusable knowledge
   databases, literature-evidence and TS-precedent layer. It must preserve group
   catalyst/ligand structures, complete method provenance, papers/SI/books and
   exact source anchors, then translate only reviewed analogies into mechanism/
   TS-seed proposals.
4. Implement the W3 mechanism-network, calculation-DAG and evidence-index layer.
   Existing Skills remain specialist components rather than a monolithic
   automatic mechanism generator.
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
