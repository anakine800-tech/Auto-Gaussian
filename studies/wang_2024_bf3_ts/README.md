# Wang 2024 BF3 transition-state offline benchmark

This directory is the version-controlled, non-runnable source of truth for the
first literature transition-state benchmark selected for the asymmetric-
catalysis workflow.

Source: JACS 2024, DOI `10.1021/jacs.4c09067`, Supporting Information sections
S67-S78 and Cartesian-coordinate tables S116-S121.

## Sequence

1. `wang2024_bf3_ts1` (57 atoms) is the first closed-shell main-group test.
   Its required manual mode review is the C13-H14-N23 proton transfer. The
   exact `r01` run is now recorded as a mode-consistent first-order saddle
   candidate in `bf3-ts1-live-smoke-evidence.json`; no IRC claim is made.
2. Only after BF3-TS1 succeeds and receives a hash-bound accepted mode decision,
   consider `wang2024_bf3_ts2_b1` and `wang2024_bf3_ts2_b2` (78 atoms each).
   Their declared coordinate is formation of C13-C21. The BF3-TS2-B1
   prerequisite is satisfied, `standard` with 120 GB/44 cores has been
   selected, and a hash-bound offline input draft is under `bf3_ts2_b1/`. The
   exact input later received a separate live approval and is running; it has
   not yet produced terminal or scientific acceptance evidence.
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
- `workflow-status.json`: companion execution/preparation status ledger. It
  keeps run evidence and live-authority state separate from the immutable
  literature ledger.
- `bf3-ts1-live-smoke-evidence.json`: sanitized, hash-bound successful TS/Freq
  and accepted-mode evidence for the exact BF3-TS1 `r01` run.
- `bf3_ts2_b1/`: three-tier protocol review, explicit `standard` selection,
  identity atom map, audited Gaussian input draft, input-draft manifest, and a
  sanitized in-flight status. Its machine-local `live/` operation bundle is
  preserved but excluded from version control.

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

No tracked file in this directory grants standing authority for Gaussian
execution, SSH, PBS, another server directory, upload, submission, retry,
deployment, cancellation, cleanup, or IRC execution. Historical status records
describe actions already approved elsewhere; they do not authorize new ones.
