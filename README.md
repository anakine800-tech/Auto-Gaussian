# RTwin Gaussian automation Skills

This repository is the version-controlled source for the Gaussian automation Skills used on this Mac. Installed copies under `~/.codex/skills` are deployment targets, not the development source of truth.

## Baseline Skills

- `skills/chemdraw-structures`: ChemDraw-compatible structure generation and stereochemical review artifacts.
- `skills/chemdraw-gaussian-pipeline`: audited ChemDraw-to-Cartesian conversion.
- `skills/gaussian-view-rt-win`: stereochemistry-preserving structure/conformer preparation and RTwin GaussView review.
- `skills/gaussian-rtwin-pbs`: guarded RTwin/PBS submission, monitoring, retrieval, Opt–Freq–SP analysis, and scheduler-state handling.

## Experimental Skills

- `skills/gaussian-ts-irc`: offline TS/Freq audit, QST atom-order checks, imaginary-mode review artifacts, explicit mode promotion, and hash-bound forward/reverse IRC plans. It intentionally performs no network, PBS, or G16 execution.

## Safety boundary

All Skill-managed server data and scratch must remain below `/home/user100/SDL`. The repository contains no password, private key, local SSH configuration, Gaussian checkpoint, or calculation output.

## Development sequence

1. Keep the baseline Skills stable on `main`.
2. Develop the TS–Freq–IRC workflow on `codex/ts-irc` from this baseline.
3. Validate offline before requesting one explicitly approved small-molecule G16 smoke test.
4. Develop asymmetric-selectivity orchestration only after TS–Freq–IRC is accepted and merged.

See `docs/ts-freq-irc-design.md` for the next workflow contract. Repository-wide operational rules are in `AGENTS.md`.

## Repository helpers

- `config/*.example` contains placeholders only; real SSH/server configuration stays ignored.
- `scripts/check_skill_sync.py` compares repository Skill hashes with installed copies.
- `templates/g16_job.pbs.template` preserves the SDL-only work/scratch guard for review and testing.
