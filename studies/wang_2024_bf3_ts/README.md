# Wang 2024 BF3 transition-state offline benchmark

This directory is the version-controlled, non-runnable source of truth for the
first literature transition-state benchmark selected for the asymmetric-
catalysis workflow.

Source: JACS 2024, DOI `10.1021/jacs.4c09067`, Supporting Information sections
S67-S78 and Cartesian-coordinate tables S116-S121.

## Sequence

1. `wang2024_bf3_ts1` (57 atoms) is the first closed-shell main-group test.
   Its required manual mode review is the C13-H14-N23 proton transfer.
2. Only after BF3-TS1 succeeds and receives a hash-bound accepted mode decision,
   consider `wang2024_bf3_ts2_b1` and `wang2024_bf3_ts2_b2` (78 atoms each).
   Their declared coordinate is formation of C13-C21.
3. Full B(C6F5)3 TS1 (87 atoms) and TS2-B1 (108 atoms) remain deferred size
   benchmarks. Their coordinates are intentionally not materialized here.

## Files

- `benchmark-source.json`: reviewed literature identity, provenance,
  electronic-state proposal with explicit unresolved status, expected values,
  reaction-coordinate atom indices, and workflow gates.
- `coordinates/*.xyz`: SI Cartesian coordinates with the published atom order.
- `candidate-ledger.json`: deterministic builder output containing exact file
  hashes, canonical coordinate hashes, geometry fingerprints, formulas, atom
  counts, measured coordinate distances, and non-authorization flags.

Rebuild without overwriting the checked artifact:

```bash
python3 skills/gaussian-asymmetric-catalysis/scripts/asymmetric_catalysis.py \
  build-literature-benchmark studies/wang_2024_bf3_ts/benchmark-source.json \
  --output /tmp/wang2024-bf3-ledger.json
cmp /tmp/wang2024-bf3-ledger.json \
  studies/wang_2024_bf3_ts/candidate-ledger.json
```

The SI does not expose all metadata needed for a runnable reproduction input.
In particular, source-reported charge/multiplicity, complete Gaussian routes,
the SMD solvent identity in the method paragraph, standard-state and
low-frequency policies, and candidate-specific IRC endpoints remain unresolved.
The neutral-singlet values in the ledger are review proposals, not source facts.

No file in this directory authorizes Gaussian, SSH, PBS, server-directory
creation, deployment, cancellation, or IRC execution.
