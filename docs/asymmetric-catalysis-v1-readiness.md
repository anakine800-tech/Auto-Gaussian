# Asymmetric-catalysis v1 merge and deployment readiness

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
   tests and the downstream `gaussian-ts-irc` boundary; and
7. the B1 terminal package is recognized as an acceptance plan, not authority
   for a retry, B2, IRC, cancellation or cleanup.

## Named deployment plan

The repository `skills/` tree is the source of truth. Installed copies under
`~/.codex/skills` are deployment targets.

After merge approval, compare and synchronize only these named Skills:

1. `gaussian-asymmetric-catalysis` — new deployed Skill;
2. `gaussian-rtwin-pbs` — protocol-rigor documentation and offline selector;
3. `gaussian-ts-irc` — protocol contract and preserved metal refusal.

For each name, validate the repository copy, review the exact repo-to-installed
diff, synchronize that directory only, and rerun the sync comparison. Do not
deploy studies, contracts, tests, docs, server data or machine-local files into
the Skill directory.

Current comparison before deployment:

- `gaussian-asymmetric-catalysis`: installed copy is absent;
- `gaussian-rtwin-pbs`: repository protocol-rigor additions differ from the
  installed copy; and
- `gaussian-ts-irc`: repository Skill/protocol contract differs from the
  installed copy.

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

The reported literature value of -389.1 cm⁻¹ is a comparison datum only.
Frequency count, numerical proximity or the static C13–C21 distance cannot
replace animation review. Every non-accepted outcome stops without automatic
retry. Even an accepted B1 proves no IRC path and grants no B2 authority.

## Development priority after v1

1. Complete transition-metal milestone M1 scientific review using a concrete
   metal–chiral-ligand reaction.
2. Design M2/M3 offline contracts, parsers and adversarial fixtures while
   retaining runtime refusal.
3. Independently finish B1 terminal/mode acceptance when the running job ends.
4. Decide whether to prepare B2 only after B1 manual acceptance.
5. Return to broader chiral-boron construction and enumeration afterward.
