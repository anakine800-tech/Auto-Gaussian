# Auto-G16 Asymmetric-Catalysis v1 Merge and Deployment Readiness

Status date: 2026-07-14

This is a preparation record. It authorizes neither merging nor deployment and
contains no live-computation authority.

## Proposed merge scope

Merge only the `codex/Chiral-Ligand` feature branch changes relative to
`02ae9bb` after the final offline checks pass. The intended v1 scope is:

- versioned asymmetric-catalysis schemas and semantic validator;
- deterministic study/candidate-space builders and provenance ledgers;
- chiral-boron enumeration/deduplication already implemented offline;
- TS-result ingestion, ensemble Boltzmann aggregation, ee and sensitivity;
- transition-metal state/search-family design with mandatory runtime refusal;
- Wang-group literature references and the BF3 benchmark/evidence ledgers;
- protocol-rigor artifacts and tests shared with the guarded Gaussian Skills.

Exclude machine-local images, operational `live/` bundles, Gaussian logs,
checkpoints, credentials, server scratch and any unrelated untracked file.

## Merge gates

Before merge:

1. all repository unit tests pass offline;
2. all repository Skill copies pass structural validation;
3. `git diff --check` passes;
4. the intended staged paths receive sensitive-string and private-key scans;
5. the staged list contains no unrelated local file;
6. transition-metal submission remains refused in schema, builder, validator,
   tests and the downstream `auto-g16-ts-irc` boundary; and
7. the B1 terminal package is recognized as an acceptance plan, not authority
   for a retry, B2, IRC, cancellation or cleanup.

## Named deployment plan

The repository `skills/` tree is the source of truth. Installed copies under
`~/.codex/skills` are deployment targets.

After merge approval, compare and synchronize only these named Skills:

1. `auto-g16-asymmetric-catalysis` — deployed Skill;
2. `auto-g16-rtwin-pbs` — protocol-rigor documentation and offline selector;
3. `auto-g16-ts-irc` — protocol contract and preserved metal refusal.

For each name, validate the repository copy, review the exact repo-to-installed
diff, synchronize that directory only, and rerun the sync comparison. Do not
deploy studies, contracts, tests, docs, server data or machine-local files into
the Skill directory.

Current comparison at W1 integration review:

- `auto-g16-asymmetric-catalysis`: repository/deployed script drift remains;
- `auto-g16-rtwin-pbs`: synchronized; and
- `auto-g16-ts-irc`: repository/deployed script drift remains.

This W1 integration does not authorize deployment or synchronization of those
drifting Skills.

## B1 terminal acceptance package

`studies/wang_2024_bf3_ts/bf3_ts2_b1/terminal-acceptance-plan.json` binds the
exact literature ledger, atom map, selected protocol, rendered input and their
hashes. On a stable terminal state it requires:

- final scheduler, Gaussian-process and log-termination evidence;
- successful optimization/stationary-point and complete frequency evidence;
- 228 harmonic modes for the nonlinear 78-atom system;
- exactly one raw imaginary frequency; and
- independent manual confirmation that its displacement follows the intended
  C13–C21 bond-forming coordinate.

The completed B1 result passed the numerical terminal gates with 228 modes and
one -389.3384 cm⁻¹ imaginary frequency; the reported literature value is
-389.1 cm⁻¹. Frequency count, numerical proximity or the static C13–C21
distance cannot replace animation review. Every non-accepted outcome stops
without automatic retry. Even an accepted B1 proves no IRC path and grants no
B2 live authority.

## Development priority after v1

1. Complete transition-metal milestone M1 scientific review using a concrete
   metal–chiral-ligand reaction.
2. Apply the implemented candidate-bound M2a audit template, then design the
   remaining M2/M3 structured-result parsers and adversarial fixtures while
   retaining runtime refusal.
3. Preserve the first B1 IRC pair as incomplete evidence. The later matched
   recalculation pair was stopped by the user for time constraints and has no
   retained terminal results; treat any future resumption as a fresh,
   separately approved calculation need.
4. Preserve B2 as a failed optimization-limit result with no frequency or mode
   evidence. Any restart remains separately gated.
5. Resolve the BF3-TS1/DIPEA terminal-template hash defect without backdating
   provenance, then perform the required C13–H14–N22 mode review before any TS
   acceptance.
6. Return to broader chiral-boron construction and enumeration afterward.
