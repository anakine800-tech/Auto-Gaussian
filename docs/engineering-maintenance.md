# Auto-G16 engineering maintenance design

## Calculation-DAG replay performance

The deep calculation-plan validator must preserve four independent checks:
path/symlink confinement, byte size and file SHA-256 binding, artifact schema
and payload SHA-256 binding, and deterministic owner reconstruction. The
optimization therefore uses no persistent cache and trusts no path or mtime.

Within one validation process, an immutable content identity is the tuple
`(schema, file_sha256, size_bytes, payload_sha256)`. Every explicit reference
is still read and hash-checked. Only two already verified results are reused:

- deterministic owner-validator replay for the same identity and resolution
  root; and
- ancestry bindings that were already validated as direct links lower in the
  same supersession walk, rebased after path/symlink confinement checks.

This removes repeated owner reconstruction and quadratic ancestor re-reading
without weakening fail-closed replay. Cached and uncached public validation
summaries are tested for exact equality. A second in-process validation after
upstream byte drift must still fail before cached owner replay can be used.

On the same local core interpreter and worktree, the existing combined
1101-node supersession/128-level plan-ancestry test changed from `59.20s` wall
before the patch to `13.59s` wall after the patch, about `4.36x` faster. These
numbers describe one local engineering run, not CI or scientific performance.

## Progressive static quality

`scripts/static_quality.py` is a dependency-free AST check with an explicit
closed path list in `config/static-quality.json`. It currently rejects bare
`except`, star imports, builtin `eval`/`exec`, and `shell=True` in the selected
high-risk maintenance modules. Expansion is an intentional reviewed config
change. It does not reformat code and is not presented as whole-repository
lint coverage.

## Large-script and duplicate-helper inventory

The largest current scripts include the guarded PBS adapter, asymmetric-
catalysis owner, TS/IRC owner, calculation DAG, asymmetric-contract validator,
and calculation-artifact adapter. Their size reflects versioned contract and
safety coupling, so line-count reduction alone is not a safe maintenance goal.
In particular, extracting transport or scientific-acceptance logic during this
engineering slice would cross the explicit package boundaries.

The low-risk shared core implemented here is the repository runtime-config
validator. `scripts/python_environment.py` now consumes the exact strict module
for duplicate-key, closed-schema, and lexical path checks instead of keeping a
second repository-level parser.

Two small `runtime_config.py` loaders remain intentionally duplicated inside
`auto-g16-rtwin-pbs` and `auto-g16-view-rt-win`. A deployed Skill must remain
self-contained, and changing these live-facing import surfaces in this package
would violate the no-live-core-change boundary. A later isolated slice may add
a checked-in loader template plus a generator `--check` mode, generate both
Skill-local copies, run named Skill packaging/sync comparisons, and obtain the
normal live-smoke approval before integration. Until then, the strict offline
repository validator is the documented preflight and deployment remains
separate.

Future decomposition should start with pure formatting/schema helpers only,
preserve every versioned contract and error message under regression fixtures,
and avoid importing repository-relative modules into deployed Skills.

## CI allocation

- Python 3.11, 3.12, and 3.13 each compile selected sources, run progressive
  static checks, and run the ordinary offline compatibility suite.
- The 1101-node/128-level pressure case is skipped only in that three-version
  matrix and remains enabled by default locally.
- A Python 3.13 source-archive release job runs the complete suite, including
  the pressure case, once from a `.git`-free archive.
- The timed runner prints the slowest tests in every suite.
- The chemistry-dependency job performs a deterministic real RDKit chiral
  structure, ETKDG conformer/UFF, and 2D depiction smoke.

None of these jobs contacts RTwin, SSH, PBS, Gaussian, a scheduler, or private
study data.
