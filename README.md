# RTwin Gaussian automation Skills

This repository is the version-controlled source for the Gaussian automation Skills used on this Mac. Installed copies under `~/.codex/skills` are deployment targets, not the development source of truth.

## Current repository status

As of 2026-07-14, the guarded RTwin/PBS workflow and the audited main-group
TS–Freq–IRC workflow are both present on `main`. The current feature branch,
`codex/Chiral-Ligand`, adds an offline asymmetric-catalysis planning/audit
Skill, literature record, design contract, schemas, deterministic offline
builders, validator, and synthetic fixtures. It does not authorize a Gaussian
submission.

See `docs/repository-status.md` for the evidence, limitations, and next gates.

## Baseline Skills

- `skills/chemdraw-structures`: ChemDraw-compatible structure generation and stereochemical review artifacts.
- `skills/chemdraw-gaussian-pipeline`: audited ChemDraw-to-Cartesian conversion.
- `skills/gaussian-view-rt-win`: stereochemistry-preserving structure/conformer preparation and RTwin GaussView review.
- `skills/gaussian-rtwin-pbs`: guarded RTwin/PBS submission, monitoring, retrieval, Opt–Freq–SP analysis, and scheduler-state handling.
- `skills/gaussian-ts-irc`: offline TS/Freq audit, QST atom-order checks, imaginary-mode review artifacts, explicit mode promotion, and hash-bound forward/reverse IRC plans. It intentionally performs no network, PBS, or G16 execution.

## Offline planning/audit module

- `skills/gaussian-asymmetric-catalysis`: literature-grounded planning and
  audit workflow for metal–chiral-ligand and chiral-boron catalytic TS
  ensembles, stereochemical-channel coverage, candidate ledgers, TS-result
  ingestion, and selectivity aggregation. It contains no Gaussian execution
  builder or live handoff. Its current development priority is the
  refusal-preserving transition-metal TS state/search design; chiral-boron
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

1. Keep the baseline Skills stable on `main`.
2. Keep asymmetric-catalysis work on `codex/Chiral-Ligand` until its offline
   contracts, validators, and fixtures are accepted.
3. Review the implemented offline builders, deduplication, result ingestion,
   ensemble aggregation, and refusal-preserving metal TS design; the existing
   `gaussian-ts-irc` transition-metal refusal must not be bypassed.
4. Accept BF3-TS2-B1 only after stable terminal evidence, a complete frequency
   parse with exactly one imaginary mode, and manual review of the C13–C21
   motion. That decision does not authorize B2, a retry, or IRC.

See `docs/ts-freq-irc-design.md` for the implemented TS–Freq–IRC design history.
Repository-wide operational rules are in `AGENTS.md`.

## Repository helpers

- `config/*.example` contains placeholders only; real SSH/server configuration stays ignored.
- `scripts/check_skill_sync.py` compares repository Skill hashes with installed copies.
- `templates/g16_job.pbs.template` preserves the SDL-only work/scratch guard for review and testing.
