# RTwin Gaussian automation Skills

This repository is the version-controlled source for the Gaussian automation Skills used on this Mac. Installed copies under `~/.codex/skills` are deployment targets, not the development source of truth.

## Current repository status

As of 2026-07-14, the guarded RTwin/PBS workflow, audited main-group
TS–Freq–IRC workflow, and the offline asymmetric-catalysis planning/audit
module are present on `main`. The asymmetric module includes its literature
record, design contract, schemas, deterministic offline builders, validator,
and synthetic fixtures. It does not authorize a Gaussian submission.

See `docs/repository-status.md` for the evidence, limitations, and next gates.
See `docs/end-to-end-reaction-computation-workflow.md` for the project target:
an auditable workflow from a ChemDraw reaction and experimental conditions to
reviewed mechanism networks, calculation evidence, thermochemistry,
kinetics/selectivity, uncertainty, and bounded conclusions.

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

1. Keep the baseline Skills stable on `main`.
2. Reconcile repository/deployed Skill drift, then develop new workflow slices
   on `codex/` feature branches with offline tests first.
3. Implement the reaction-intake, species/atom-map, condition-model,
   mechanism-network, calculation-DAG, and evidence-index layer described in
   the end-to-end design. Existing Skills remain specialist components rather
   than a monolithic automatic mechanism generator.
4. Connect candidate/protocol/input and result/energy adapters, then validate a
   small closed-shell main-group reaction from ChemDraw through minima, TS,
   path, and common-reference energy evidence.
5. Continue the refusal-preserving transition-metal M1–M3 design; the existing
   `gaussian-ts-irc` transition-metal refusal must not be bypassed.
6. BF3-TS2-B1 has an accepted hash-bound C13–C21 mode decision and separately
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
