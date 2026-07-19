---
name: auto-g16-ts-seed
description: Build and review hash-bound, non-executable Gaussian transition-state seed candidates and bounded 1+1 seed portfolios from exact reviewed targets, analogous reaction cores, endpoint/QST lineages, scans, or last-resort de novo hypotheses. Use when proposing scientific TS initial guesses, recording atom mapping and reaction-coordinate provenance, deduplicating cosmetic geometry variants, or preparing candidate-only handoffs before the separate TS/IRC, open-shell, metal, protocol, and submission gates.
---

# Auto-G16 TS Seed

Create scientific initial-guess evidence only. Never create Gaussian input,
execute a calculation, authorize PBS submission, or treat a seed as a TS.

## Workflow

1. Read `references/contract-guide.md` before creating or reviewing an
   artifact.
2. Require exact reviewed target coordinates, endpoint hashes, atom mapping,
   charge, multiplicity, electronic-state label, stereochemical/binding mode,
   and an explicit method/protocol artifact. Never infer a method or protocol.
3. Select the first scientifically available provenance source in this order:
   exact reviewed target coordinates; truly analogous reaction-core transfer;
   reviewed endpoint/QST2; reviewed QST3; constrained/directional scan; de
   novo. Record why every higher-priority source was unavailable or rejected.
4. For complex systems, define candidates by distinct chemical hypotheses and
   reaction-coordinate lineages. Do not enumerate Cartesian face, angle, or
   distance permutations. The builder rejects a cosmetic-permutation flag.
5. Record forming/breaking bonds or a reviewed collective coordinate, complete
   atom correspondence, geometry sanity, clashes, provenance, confidence, and
   review status. Keep blocked candidates as negative evidence; do not promote
   them into a portfolio.
6. Route main-group open-shell cases to `auto-g16-main-group-open-shell` and
   transition-metal cases to `auto-g16-metal-ts`. A pending specialist review
   keeps the candidate ineligible.
7. Build a portfolio with exactly one primary and normally no more than one
   independently justified backup. Reject identical structural fingerprints
   and identical scientific-hypothesis signatures. More candidates require a
   new scientific rationale and explicit user review.
8. Treat both contracts as candidate-only evidence. Use later specialist and
   `auto-g16-ts-irc` gates for downstream review; use `auto-g16-rtwin-pbs` only
   after its separate exact approvals. This Skill grants none.

## Commands

```bash
python3 scripts/ts_seed.py build-candidate candidate-source.json --output candidate.json
python3 scripts/ts_seed.py build-portfolio portfolio-source.json --output portfolio.json
python3 scripts/ts_seed.py validate candidate-or-portfolio.json
```

All writers refuse overwrite. Keep referenced JSON files package-relative and
hash-bound; parent traversal, symlinks, missing payload hashes, and drift fail
closed.
